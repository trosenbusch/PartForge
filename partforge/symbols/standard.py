"""House-style standard symbols (generic symbols for the DbLib: no parameters, no footprint links).

Conventions (``docs/entwicklung/recherche/user-lib-style.md`` §3.3–3.6, writer limits from
``rust-writer.md`` §6 / ``altium-verify-rust.md`` §3):

* unit mil, +Y up, origin at the body centre of 2-terminal parts; pin 1 on the left;
* every pin end and tip on the 10 mil raster, every pin tip (connection point) and pin row on
  the symbol grid; pin lengths follow ``SymbolStyle.discrete_pin_length`` and are adjusted
  so the tips land on the grid; graphics on a 5 mil raster;
* discretes: blue lines (house colour), filled shapes solid blue, pin names and numbers
  hidden; op-amps, optocouplers, relays and 4-pin switches show pin numbers;
* pad numbering matches the footprint generator: diode cathode = pad 1 (default of
  ``diode_pin1``), polarised capacitors pin 1 = plus, SOT-23 transistors 1=B/G 2=E/S 3=C/D,
  SOT-223/DPAK tab, exposed drain pads; several pads of one function become stacked pins
  (``SSSGDDDD``, ``SSSGDDDDD``);
* IC-like kinds (connectors, oscillator) use the house pin pitch of 100 mil whatever the grid;
* free text only as labels (the writer has no working text primitive), no pin decorations.

Every symbol name is fixed for a kind + pinout ("NPN", "NPN (EBC)", "Connector 2x05") so the
same symbol is reused across parts. A name without a pin-map suffix always means the kind's
canonical map, independent of the house style: an anode-first diode is "Diode (AK)" in every
workspace, so changing ``diode_pin1`` never changes what an existing name means.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..geometry.model import ElectricalType, PinOrientation, SymbolSpec
from .builder import SymbolBuilder
from .errors import SymbolError
from .ic import PIN_PITCH, build_ic
from .models import IcPin, SymbolKindInfo, SymbolParamSpec, SymbolRequest
from .pinmap import PinFunction, PinMapSpec, ResolvedPinMap, resolve_pinmap
from .style import MINUS_COLOR, PLUS_COLOR, StyleKit
from .util import check_name, check_prefix

log = logging.getLogger(__name__)

__all__ = [
    "GENERATOR_VERSION",
    "KindDef",
    "build_standard",
    "get_kind",
    "is_diode_kind",
    "kind_defs",
    "kind_pinmap",
    "tab_function",
]

GENERATOR_VERSION = 1
XY = tuple[float, float]


# ======================================================================================
# parameter specs
# ======================================================================================
def _p_enum(
    name: str,
    label: str,
    options: Mapping[str, str],
    default: str,
    help: str | None = None,
    *,
    allow_custom: bool = False,
) -> SymbolParamSpec:
    return SymbolParamSpec(
        name=name,
        label=label,
        kind="enum",
        default=default,
        options=list(options),
        option_labels=dict(options),
        help=help,
        allow_custom=allow_custom,
    )


def _p_bool(name: str, label: str, default: bool, help: str | None = None) -> SymbolParamSpec:
    return SymbolParamSpec(name=name, label=label, kind="bool", default=default, help=help)


def _p_int(name: str, label: str, default: int, minimum: int, maximum: int, help: str | None = None) -> SymbolParamSpec:
    return SymbolParamSpec(
        name=name, label=label, kind="int", default=default, minimum=minimum, maximum=maximum, help=help
    )


def _p_pinmap(
    spec: PinMapSpec, help: str, *, default: str | None = None, auto_label: str | None = None
) -> SymbolParamSpec:
    options: dict[str, str] = {}
    if auto_label:
        options["auto"] = auto_label
    for key in spec.presets:
        options[key] = spec.preset_labels.get(key, key)
    return _p_enum("pinmap", "Pinbelegung", options, default or spec.default, help, allow_custom=True)


_TRUE = {"1", "true", "ja", "yes", "y", "on", "wahr", "x"}
_FALSE = {"0", "false", "nein", "no", "n", "off", "falsch", ""}


def _coerce(spec: SymbolParamSpec, raw: Any, what: str) -> Any:
    label = f"{what}: Parameter „{spec.label}“"
    if spec.kind == "bool":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)) and raw in (0, 1):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise SymbolError(f"{label} erwartet Ja/Nein, nicht {raw!r}.")
    if spec.kind == "int":
        try:
            if isinstance(raw, bool):
                raise ValueError
            value = float(str(raw).replace(",", ".")) if not isinstance(raw, (int, float)) else float(raw)
            if not value.is_integer():
                raise ValueError
            number = int(value)
        except (TypeError, ValueError):
            raise SymbolError(f"{label} erwartet eine ganze Zahl, nicht {raw!r}.") from None
        if (spec.minimum is not None and number < spec.minimum) or (spec.maximum is not None and number > spec.maximum):
            raise SymbolError(f"{label} muss zwischen {spec.minimum} und {spec.maximum} liegen (ist {number}).")
        return number
    if spec.kind == "enum":
        if spec.allow_custom and isinstance(raw, Mapping):
            return dict(raw)
        if isinstance(raw, bool):
            raw = str(raw).lower()
        text = str(raw).strip()
        for option in spec.options:
            if option.lower() == text.lower():
                return option
        if spec.allow_custom:
            return text
        options = ", ".join(spec.options)
        raise SymbolError(f"{label}: ungültiger Wert {raw!r} (möglich: {options}).")
    return "" if raw is None else str(raw)


# ======================================================================================
# kind registry
# ======================================================================================
@dataclass
class Ctx:
    """Mutable state while one standard symbol is drawn."""

    kit: StyleKit
    kind: KindDef
    params: dict[str, Any]
    req: SymbolRequest
    b: SymbolBuilder
    suffix: list[str] = field(default_factory=list)
    description: str = ""
    text_positions: dict[str, dict[str, Any]] | None = None
    pinmap: ResolvedPinMap | None = None
    functions: tuple[PinFunction, ...] = ()
    spec: SymbolSpec | None = None  # set by box-style kinds that build through the IC generator

    @property
    def show_numbers(self) -> bool:
        return self.kind.show_numbers

    def pin(self, designator: str, name: str, x: int, y: int, orientation: PinOrientation, **kw: Any) -> None:
        kw.setdefault("show_designator", self.show_numbers)
        self.b.pin(designator, name, x, y, orientation, **kw)

    def func_pins(self, function: str, x: int, y: int, orientation: PinOrientation, **kw: Any) -> None:
        """Pins of a pin-map function (stacked when the function has several pads)."""
        if self.pinmap is None:
            raise RuntimeError("pin map not resolved")
        name = kw.pop("name", None)
        if name is None:
            name = next(f.name for f in self.functions if f.key == function)
        kw.setdefault("show_designator", self.show_numbers)
        self.b.stacked_pins(self.pinmap.designators(function), name, x, y, orientation, **kw)


@dataclass(frozen=True)
class KindDef:
    key: str
    label: str  # German UI label
    group: str  # "Passiv", "Halbleiter", "ICs", "Verbinder", "Sonstige"
    base_name: str
    prefix: str
    description: str  # English library description (ASCII, ends up in the SchLib)
    help: str  # German UI help
    categories: tuple[str, ...]
    draw: Callable[[Ctx], None]
    params: tuple[SymbolParamSpec, ...] = ()
    show_numbers: bool = False

    def info(self) -> SymbolKindInfo:
        return SymbolKindInfo(
            key=self.key,
            label=self.label,
            group=self.group,
            default_name=self.base_name,
            params=[p.model_copy(deep=True) for p in self.params],
            categories=list(self.categories),
            description=self.help,
            prefix=self.prefix,
        )


# ======================================================================================
# shared drawing helpers
# ======================================================================================
def _round10_down(v: float) -> int:
    return math.floor(v / 10.0) * 10


def _graphics_extent(ctx: Ctx) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of the graphics of part 1 plus pin attach points."""
    tmp = SymbolSpec(name="tmp", graphics=[g for g in ctx.b.graphics if g.part in (0, 1)])
    x1, y1, x2, y2 = tmp.bbox()
    for p in ctx.b.pins:
        if p.part in (0, 1):
            x1, x2 = min(x1, p.x), max(x2, p.x)
            y1, y2 = min(y1, p.y), max(y2, p.y)
    return x1, y1, x2, y2


def _labels_at(ctx: Ctx, designator: XY, comment: XY) -> None:
    ctx.text_positions = {
        "designator": {"x": int(designator[0]), "y": int(designator[1]), "justify": "bottom_left"},
        "comment": {"x": int(comment[0]), "y": int(comment[1]), "justify": "bottom_left"},
    }


def _labels_above_below(ctx: Ctx, x0: float = -50) -> None:
    """House placement: designator just above the body, Comment just below (bottom-left anchors)."""
    _, y1, _, y2 = _graphics_extent(ctx)
    top = max(y2, 40)
    bottom = min(y1, -40)
    _labels_at(ctx, (x0, top + 10), (x0, _round10_down(bottom - 10 - ctx.kit.em)))


def _labels_right(ctx: Ctx, dx: float = 30) -> None:
    """Designator and Comment stacked right of the body (symbols with vertical pins)."""
    _, _, x2, _ = _graphics_extent(ctx)
    x = math.ceil((x2 + dx) / 10.0) * 10
    _labels_at(ctx, (x, 10), (x, _round10_down(-10 - ctx.kit.em)))


def _resistor_body(ctx: Ctx, half: int = 100) -> int:
    """IEC rectangle or ANSI zigzag between x = -half..half; returns the top y of the body."""
    b = ctx.b
    if ctx.kit.resistor_style == "ansi":
        # five peaks 2*half/5 apart with half-step lead-in/out:
        # (-100,0) (-80,30) (-40,-30) (0,30) (40,-30) (80,30) (100,0)
        peak = 2 * half / 5
        pts: list[XY] = [(-half, 0)]
        pts += [(-half + peak / 2 + i * peak, 30 if i % 2 == 0 else -30) for i in range(5)]
        pts.append((half, 0))
        b.line(*pts)
        return 30
    b.rect(-half, -40, half, 40)
    return 40


def _two_terminal(
    ctx: Ctx, left_x: int, right_x: int, names: tuple[str, str] = ("1", "2"), designators: tuple[str, str] = ("1", "2")
) -> None:
    ctx.pin(designators[0], names[0], left_x, 0, "left")
    ctx.pin(designators[1], names[1], right_x, 0, "right")


_UNSET: Any = object()


def _with_pinmap(ctx: Ctx, spec: PinMapSpec, *, default: str | None = None, value: Any = _UNSET) -> ResolvedPinMap:
    """Resolve the ``pinmap`` parameter (or an explicit ``value``) against ``spec``."""
    raw = ctx.params.get("pinmap") if value is _UNSET else value
    resolved = resolve_pinmap(spec, raw, what=ctx.kind.label, default=default)
    ctx.pinmap = resolved
    ctx.functions = spec.functions
    return resolved


# ======================================================================================
# passives
# ======================================================================================
def _draw_resistor(ctx: Ctx) -> None:
    _resistor_body(ctx)
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic resistor"
    _labels_above_below(ctx)


def _wiper_pin(ctx: Ctx) -> None:
    ctx.pin("2", "W", 0, 100, "up")


def _draw_potentiometer(ctx: Ctx) -> None:
    top = _resistor_body(ctx)
    b = ctx.b
    b.line((0, 100), (0, 80))
    b.polygon((0, top), (-20, 80), (20, 80))
    ctx.pin("1", "CCW", -100, 0, "left")
    _wiper_pin(ctx)
    ctx.pin("3", "CW", 100, 0, "right")
    ctx.description = "Generic potentiometer (2 = wiper)"
    _labels_at(ctx, (30, 50), (-50, -150))


def _draw_trimmer(ctx: Ctx) -> None:
    _resistor_body(ctx)
    b = ctx.b
    b.line((0, 100), (0, 50))
    b.line((-30, 50), (30, 50))
    ctx.pin("1", "CCW", -100, 0, "left")
    _wiper_pin(ctx)
    ctx.pin("3", "CW", 100, 0, "right")
    ctx.description = "Generic trimmer potentiometer (2 = wiper)"
    _labels_at(ctx, (40, 60), (-50, -150))


def _draw_capacitor(ctx: Ctx) -> None:
    b = ctx.b
    b.line((-20, -60), (-20, 60))
    b.line((20, -60), (20, 60))
    _two_terminal(ctx, -20, 20)
    ctx.description = "Generic capacitor"
    _labels_above_below(ctx)


_CAP_POL_PINMAP = PinMapSpec(
    functions=(PinFunction("+", "+", "+"), PinFunction("-", "-", "-")),
    presets={"+-": {"+": ("1",), "-": ("2",)}, "-+": {"-": ("1",), "+": ("2",)}},
    default="+-",
    preset_labels={"+-": "1 = Plus (IPC, Tantal/Elko)", "-+": "1 = Minus"},
)


def _draw_capacitor_polarized(ctx: Ctx) -> None:
    pm = _with_pinmap(ctx, _CAP_POL_PINMAP)
    b = ctx.b
    plus_left = pm.designators("+")[0] == "1"
    sign = -1 if plus_left else 1  # x side of the + plate
    if ctx.kit.resistor_style == "ansi":
        b.line((sign * 20, -60), (sign * 20, 60))
        cx = -sign * 100
        start, end = (140, 220) if plus_left else (-40, 40)
        b.arc(cx, 0, 80, start, end)
        minus_x = -sign * 20
    else:
        x_out = sign * 40
        b.rect(sign * 20, -60, x_out, 60)  # + plate (outlined)
        b.rect(-sign * 20, -60, -sign * 40, 60, filled=True)  # - plate (solid)
        minus_x = -sign * 40
    plus_x = sign * (20 if ctx.kit.resistor_style == "ansi" else 40)
    b.plus_sign(sign * 70, 50)
    ctx.func_pins("+", plus_x, 0, "left" if plus_left else "right")
    ctx.func_pins("-", minus_x, 0, "right" if plus_left else "left")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Generic polarized capacitor ({pm.label})"
    _labels_above_below(ctx)


def _draw_inductor(ctx: Ctx) -> None:
    b = ctx.b
    for cx in (-75, -25, 25, 75):
        b.arc(cx, 0, 25, 0, 180)
    core = ctx.params["core"]
    if core == "iron":
        b.line((-100, 50), (100, 50))
        b.line((-100, 70), (100, 70))
        ctx.suffix.append("Iron Core")
    elif core == "ferrite":
        b.dashed((-100, 50), (100, 50), dash=20, gap=10)
        b.dashed((-100, 70), (100, 70), dash=20, gap=10)
        ctx.suffix.append("Ferrite Core")
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic inductor" + {"iron": " with core", "ferrite": " with ferrite core"}.get(core, "")
    _labels_above_below(ctx)


def _draw_ferrite_bead(ctx: Ctx) -> None:
    b = ctx.b
    b.polygon((-60, -80), (0, -80), (60, 80), (0, 80), filled=False)
    b.line((-100, 0), (-30, 0))
    b.line((30, 0), (100, 0))
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic ferrite bead"
    _labels_above_below(ctx)


_CRYSTAL4_PINMAP = PinMapSpec(
    functions=(
        PinFunction("X1", "XTAL1", "Q"),
        PinFunction("X2", "XTAL2", "Q"),
        PinFunction("G1", "GND", "G"),
        PinFunction("G2", "GND", "G"),
    ),
    presets={
        "QGQG": {"X1": ("1",), "G1": ("2",), "X2": ("3",), "G2": ("4",)},
        "QQGG": {"X1": ("1",), "X2": ("2",), "G1": ("3",), "G2": ("4",)},
        "GQGQ": {"G1": ("1",), "X1": ("2",), "G2": ("3",), "X2": ("4",)},
    },
    default="QGQG",
    preset_labels={
        "QGQG": "1, 3 = Quarz; 2, 4 = Gehäuse/GND (Standard)",
        "QQGG": "1, 2 = Quarz; 3, 4 = Gehäuse/GND",
        "GQGQ": "2, 4 = Quarz; 1, 3 = Gehäuse/GND",
    },
)


def _crystal_body(ctx: Ctx) -> None:
    b = ctx.b
    b.line((-50, -60), (-50, 60))
    b.line((50, -60), (50, 60))
    b.rect(-30, -50, 30, 50)


def _draw_crystal_2(ctx: Ctx) -> None:
    _crystal_body(ctx)
    _two_terminal(ctx, -50, 50)
    ctx.description = "Generic crystal"
    _labels_above_below(ctx)


def _draw_crystal_4(ctx: Ctx) -> None:
    pm = _with_pinmap(ctx, _CRYSTAL4_PINMAP)
    _crystal_body(ctx)
    ctx.b.line((-100, -80), (100, -80))
    ctx.func_pins("X1", -50, 0, "left")
    ctx.func_pins("X2", 50, 0, "right")
    ctx.func_pins("G1", -100, -80, "down")
    ctx.func_pins("G2", 100, -80, "down")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Generic crystal with case pins ({pm.label})"
    _labels_at(ctx, (-50, 170), (-50, 70))


def _draw_fuse(ctx: Ctx) -> None:
    b = ctx.b
    b.rect(-100, -40, 100, 40)
    b.line((-100, 0), (100, 0))
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic fuse"
    _labels_above_below(ctx)


def _slash_with_foot(ctx: Ctx) -> None:
    ctx.b.line((-120, -80), (-80, -80), (80, 80))


def _draw_ptc(ctx: Ctx) -> None:
    _resistor_body(ctx)
    _slash_with_foot(ctx)
    ctx.b.text(110, 70, "+t", justify="bottom_left")
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic PTC resettable fuse"
    _labels_above_below(ctx, x0=-150)


def _draw_varistor(ctx: Ctx) -> None:
    _resistor_body(ctx)
    _slash_with_foot(ctx)
    ctx.b.text(110, 70, "U", justify="bottom_left")
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic varistor (VDR)"
    _labels_above_below(ctx, x0=-150)


# ======================================================================================
# diodes
# ======================================================================================
_DIODE_PINMAP = PinMapSpec(
    functions=(PinFunction("A", "A", "A"), PinFunction("K", "K", "K")),
    presets={
        "KA": {"K": ("1",), "A": ("2",)},
        "AK": {"A": ("1",), "K": ("2",)},
        "AxK": {"A": ("1",), "K": ("3",)},
        "KxA": {"K": ("1",), "A": ("3",)},
    },
    default="KA",
    preset_labels={
        "KA": "1 = Kathode, 2 = Anode (IPC)",
        "AK": "1 = Anode, 2 = Kathode",
        "AxK": "SOT-23: 1 = Anode, 3 = Kathode",
        "KxA": "SOT-23: 1 = Kathode, 3 = Anode",
    },
)
#: Option "auto" of the diode pin maps: the setting lives in Einstellungen › Namensregeln › „Dioden: Pin 1“.
DIODE_AUTO_LABEL = "Wie in den Namensregeln (Einstellung „Dioden: Pin 1“)"

_DIODE_PINMAP_PARAM = _p_pinmap(
    _DIODE_PINMAP,
    "Standard folgt den Namensregeln der Bibliothek (Einstellungen › Namensregeln › „Dioden: Pin 1“: "
    "Pin 1 = Kathode bzw. Anode). Der Name ohne Zusatz bedeutet immer Pin 1 = Kathode; Anode zuerst heißt "
    "z. B. „Diode (AK)“. Eigene Belegung als Code, z. B. 'AxK'.",
    default="auto",
    auto_label=DIODE_AUTO_LABEL,
)


def _diode_pins(ctx: Ctx) -> ResolvedPinMap:
    """Anode left, cathode right; numbering per ``pinmap`` (default: house style ``diode_pin1``).

    The *name* is relative to the canonical IPC map ``KA``: an anode-first default is called
    "Diode (AK)", so a name never changes its pinout when the house style changes.
    """
    default = "KA" if ctx.kit.diode_pin1 == "cathode" else "AK"
    pm = _with_pinmap(ctx, _DIODE_PINMAP, default=default)
    ctx.func_pins("A", -50, 0, "left")
    ctx.func_pins("K", 50, 0, "right")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    return pm


def _diode_triangle(ctx: Ctx, x_base: float = -50, x_tip: float = 50, half: float = 50) -> None:
    ctx.b.polygon((x_base, -half), (x_base, half), (x_tip, 0))


def _draw_diode(ctx: Ctx) -> None:
    _diode_triangle(ctx)
    ctx.b.line((50, -50), (50, 50))
    pm = _diode_pins(ctx)
    ctx.description = f"Generic diode ({pm.label})"
    _labels_above_below(ctx)


def _draw_zener(ctx: Ctx) -> None:
    _diode_triangle(ctx)
    ctx.b.line((30, 60), (50, 50), (50, -50), (70, -60))
    pm = _diode_pins(ctx)
    ctx.description = f"Generic zener diode ({pm.label})"
    _labels_above_below(ctx)


def _draw_schottky(ctx: Ctx) -> None:
    _diode_triangle(ctx)
    ctx.b.line((70, -30), (70, -50), (50, -50), (50, 50), (30, 50), (30, 30))
    pm = _diode_pins(ctx)
    ctx.description = f"Generic Schottky diode ({pm.label})"
    _labels_above_below(ctx)


def _draw_tvs_uni(ctx: Ctx) -> None:
    _diode_triangle(ctx)
    ctx.b.line((30, 60), (50, 50), (50, -50), (70, -60))
    pm = _diode_pins(ctx)
    ctx.description = f"Generic TVS diode, unidirectional ({pm.label})"
    _labels_above_below(ctx)


def _draw_tvs_bi(ctx: Ctx) -> None:
    b = ctx.b
    b.polygon((-100, -50), (-100, 50), (0, 0))
    b.polygon((100, -50), (100, 50), (0, 0))
    b.line((-20, 60), (0, 50), (0, -50), (20, -60))
    _two_terminal(ctx, -100, 100)
    ctx.description = "Generic TVS diode, bidirectional"
    _labels_above_below(ctx)


def _draw_led(ctx: Ctx) -> None:
    _diode_triangle(ctx)
    b = ctx.b
    b.line((50, -50), (50, 50))
    b.arrow((-10, 60), (30, 100))
    b.arrow((20, 60), (60, 100))
    pm = _diode_pins(ctx)
    ctx.description = f"Generic LED ({pm.label})"
    _labels_above_below(ctx)


def _draw_photodiode(ctx: Ctx) -> None:
    _diode_triangle(ctx)
    b = ctx.b
    b.line((50, -50), (50, 50))
    b.arrow((30, 100), (-10, 60))
    b.arrow((60, 100), (20, 60))
    pm = _diode_pins(ctx)
    ctx.description = f"Generic photodiode ({pm.label})"
    _labels_above_below(ctx)


_BRIDGE_PINMAP = PinMapSpec(
    functions=(
        PinFunction("+", "+", "+"),
        PinFunction("-", "-", "-"),
        PinFunction("AC1", "~", "A"),
        PinFunction("AC2", "~", "A"),
    ),
    presets={
        "+AA-": {"+": ("1",), "AC1": ("2",), "AC2": ("3",), "-": ("4",)},
        "AA+-": {"AC1": ("1",), "AC2": ("2",), "+": ("3",), "-": ("4",)},
        "A+A-": {"AC1": ("1",), "+": ("2",), "AC2": ("3",), "-": ("4",)},
        "A+-A": {"AC1": ("1",), "+": ("2",), "-": ("3",), "AC2": ("4",)},
        "+-AA": {"+": ("1",), "-": ("2",), "AC1": ("3",), "AC2": ("4",)},
    },
    default="+AA-",
    preset_labels={
        "+AA-": "1 = +, 2/3 = ~, 4 = − (Reihe: KBP, GBU, GBJ)",
        "AA+-": "1/2 = ~, 3 = +, 4 = −",
        "A+A-": "1 = ~, 2 = +, 3 = ~, 4 = −",
        "A+-A": "1 = ~, 2 = +, 3 = −, 4 = ~",
        "+-AA": "1 = +, 2 = −, 3/4 = ~",
    },
)


def _diode_along(ctx: Ctx, start: XY, end: XY) -> None:
    """Diode on a 45° edge from ``start`` (anode) to ``end`` (cathode), with leads."""
    b = ctx.b
    dx = (end[0] > start[0]) - (end[0] < start[0])
    dy = (end[1] > start[1]) - (end[1] < start[1])
    mx, my = (start[0] + end[0]) / 2, (start[1] + end[1]) / 2
    s = 30
    px, py = -dy, dx
    tip = (mx + s * dx, my + s * dy)
    base = (mx - s * dx, my - s * dy)
    b.line(start, base)
    b.line(tip, end)
    b.polygon(tip, (base[0] + s * px, base[1] + s * py), (base[0] - s * px, base[1] - s * py))
    b.line((tip[0] + s * px, tip[1] + s * py), (tip[0] - s * px, tip[1] - s * py))


def _draw_bridge(ctx: Ctx) -> None:
    raw = ctx.params.get("pinmap")
    if isinstance(raw, str):
        raw = raw.replace("~", "A").replace("a", "A")
    pm = _with_pinmap(ctx, _BRIDGE_PINMAP, value=raw)
    left, top, right, bottom = (-200, 0), (0, 200), (200, 0), (0, -200)
    _diode_along(ctx, left, top)
    _diode_along(ctx, right, top)
    _diode_along(ctx, bottom, left)
    _diode_along(ctx, bottom, right)
    ctx.b.plus_sign(40, 250)
    ctx.b.minus_sign(40, -250)
    ctx.func_pins("AC1", -200, 0, "left")
    ctx.func_pins("+", 0, 200, "up")
    ctx.func_pins("AC2", 200, 0, "right")
    ctx.func_pins("-", 0, -200, "down")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Generic bridge rectifier ({pm.label})"
    _labels_at(ctx, (130, 230), (130, 130))


# ======================================================================================
# transistors
# ======================================================================================
_BJT_PINMAP = PinMapSpec(
    functions=(PinFunction("B", "B", "B"), PinFunction("C", "C", "C"), PinFunction("E", "E", "E")),
    presets={
        "BEC": {"B": ("1",), "E": ("2",), "C": ("3",)},
        "EBC": {"E": ("1",), "B": ("2",), "C": ("3",)},
        "CBE": {"C": ("1",), "B": ("2",), "E": ("3",)},
        "BCE": {"B": ("1",), "C": ("2",), "E": ("3",)},
        "ECB": {"E": ("1",), "C": ("2",), "B": ("3",)},
        "CEB": {"C": ("1",), "E": ("2",), "B": ("3",)},
        "BCEC": {"B": ("1",), "C": ("2", "4"), "E": ("3",)},
    },
    default="BEC",
    preset_labels={
        "BEC": "SOT-23: 1 = B, 2 = E, 3 = C",
        "EBC": "1 = E, 2 = B, 3 = C (z. B. TO-92 2N3904)",
        "CBE": "1 = C, 2 = B, 3 = E (z. B. TO-92 BC547)",
        "BCE": "1 = B, 2 = C, 3 = E (SOT-89, TO-220, DPAK mit Fahne 2)",
        "ECB": "1 = E, 2 = C, 3 = B (z. B. TO-126 BD139)",
        "CEB": "1 = C, 2 = E, 3 = B",
        "BCEC": "SOT-223 / 3-Pin-DPAK: 1 = B, 2/4 = C, 3 = E",
    },
)
_FET_PINMAP = PinMapSpec(
    functions=(PinFunction("G", "G", "G"), PinFunction("D", "D", "D"), PinFunction("S", "S", "S")),
    presets={
        "GSD": {"G": ("1",), "S": ("2",), "D": ("3",)},
        "GDS": {"G": ("1",), "D": ("2",), "S": ("3",)},
        "SGD": {"S": ("1",), "G": ("2",), "D": ("3",)},
        "DGS": {"D": ("1",), "G": ("2",), "S": ("3",)},
        "GDSD": {"G": ("1",), "D": ("2", "4"), "S": ("3",)},
        "SSSGDDDD": {"S": ("1", "2", "3"), "G": ("4",), "D": ("5", "6", "7", "8")},
        "SSSGDDDDD": {"S": ("1", "2", "3"), "G": ("4",), "D": ("5", "6", "7", "8", "9")},
        "SSSGDDDD+EP": {"S": ("1", "2", "3"), "G": ("4",), "D": ("5", "6", "7", "8", "EP")},
        "DDGSDD": {"D": ("1", "2", "5", "6"), "G": ("3",), "S": ("4",)},
    },
    default="GSD",
    preset_labels={
        "GSD": "SOT-23: 1 = G, 2 = S, 3 = D",
        "GDS": "1 = G, 2 = D, 3 = S (DPAK/D2PAK mit Fahne 2, SOT-89, TO-220)",
        "SGD": "1 = S, 2 = G, 3 = D (z. B. TO-92 2N7000)",
        "DGS": "1 = D, 2 = G, 3 = S (z. B. TO-92 BS170)",
        "GDSD": "SOT-223 / 3-Pin-DPAK: 1 = G, 2/4 = D, 3 = S",
        "SSSGDDDD": "SO-8: 1–3 = S, 4 = G, 5–8 = D",
        "SSSGDDDDD": "DFN/SON/PowerPAK mit Drain-Pad: 1–3 = S, 4 = G, 5–9 = D (Pad 9 = EP)",
        "SSSGDDDD+EP": "DFN/SON/PowerPAK mit Drain-Pad: 1–3 = S, 4 = G, 5–8 + EP = D",
        "DDGSDD": "TSOP-6 / SOT-23-6: 1, 2, 5, 6 = D, 3 = G, 4 = S (z. B. Si3442)",
    },
)


def _draw_bjt(ctx: Ctx, pnp: bool) -> None:
    pm = _with_pinmap(ctx, _BJT_PINMAP)
    b = ctx.b
    b.line((0, -70), (0, 70))
    b.line((0, 40), (100, 140))
    b.line((0, -40), (100, -140))
    if pnp:
        b.arrow_head((20, -60), (-1, 1), 30, 10)
    else:
        b.arrow_head((70, -110), (1, -1), 30, 10)
    if ctx.params.get("circle"):
        b.circle(50, 0, 120)
        ctx.suffix.append("Circle")
    ctx.func_pins("B", 0, 0, "left")
    ctx.func_pins("C", 100, 140, "up")
    ctx.func_pins("E", 100, -140, "down")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"{'PNP' if pnp else 'NPN'} bipolar transistor ({pm.label})"
    _labels_right(ctx)


def _draw_mosfet(ctx: Ctx, pchannel: bool) -> None:
    pm = _with_pinmap(ctx, _FET_PINMAP)
    b = ctx.b
    b.line((0, -80), (0, 80))  # gate plate
    for y1, y2 in ((60, 100), (-20, 20), (-100, -60)):  # enhancement channel
        b.line((30, y1), (30, y2))
    b.line((30, 80), (100, 80))
    b.line((30, -80), (100, -80))
    b.line((30, 0), (100, 0), (100, -80))
    if pchannel:
        b.arrow_head((70, 0), (1, 0), 30, 10)
    else:
        b.arrow_head((30, 0), (-1, 0), 30, 10)
    if ctx.params.get("body_diode"):
        b.line((100, 80), (160, 80), (160, 30))
        b.line((100, -80), (160, -80), (160, -30))
        if pchannel:  # body diode anode = drain (top), cathode = source
            b.polygon((130, 30), (190, 30), (160, -30))
            b.line((130, -30), (190, -30))
        else:  # anode = source (bottom), cathode = drain
            b.polygon((130, -30), (190, -30), (160, 30))
            b.line((130, 30), (190, 30))
    else:
        ctx.suffix.append("No-Diode")
    if ctx.params.get("circle"):
        b.circle(80, 0, 140)
        ctx.suffix.append("Circle")
    ctx.func_pins("G", 0, 0, "left")
    ctx.func_pins("D", 100, 80, "up")
    ctx.func_pins("S", 100, -80, "down")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    diode = " with body diode" if ctx.params.get("body_diode") else ""
    ctx.description = f"{'P' if pchannel else 'N'}-channel MOSFET{diode} ({pm.label})"
    _labels_right(ctx)


# ======================================================================================
# amplifiers
# ======================================================================================
_OPAMP_FUNCS = (
    PinFunction("IN+", "+IN"),
    PinFunction("IN-", "-IN"),
    PinFunction("OUT", "OUT"),
    PinFunction("V+", "V+"),
    PinFunction("V-", "V-"),
)
_OPAMP_PINMAP = PinMapSpec(
    functions=_OPAMP_FUNCS,
    presets={
        "SOT23-5": {"OUT": ("1",), "V-": ("2",), "IN+": ("3",), "IN-": ("4",), "V+": ("5",)},
        "SOT23-5R": {"OUT": ("1",), "V+": ("2",), "IN+": ("3",), "IN-": ("4",), "V-": ("5",)},
        "SOT23-5U": {"IN+": ("1",), "V-": ("2",), "IN-": ("3",), "OUT": ("4",), "V+": ("5",)},
        "SOIC8": {"IN-": ("2",), "IN+": ("3",), "V-": ("4",), "OUT": ("6",), "V+": ("7",)},
    },
    default="SOT23-5",
    preset_labels={
        "SOT23-5": "SOT-23-5: 1 = OUT, 2 = V−, 3 = +IN, 4 = −IN, 5 = V+",
        "SOT23-5R": "SOT-23-5 (R): 1 = OUT, 2 = V+, 3 = +IN, 4 = −IN, 5 = V−",
        "SOT23-5U": "SOT-23-5 (U): 1 = +IN, 2 = V−, 3 = −IN, 4 = OUT, 5 = V+",
        "SOIC8": "SOIC-8 einzeln: 2 = −IN, 3 = +IN, 4 = V−, 6 = OUT, 7 = V+",
    },
)
# (OUT, IN-, IN+) per channel and (V+, V-) of the standard dual/quad packages
_DUAL_CHANNELS = (("1", "2", "3"), ("7", "6", "5"))
_DUAL_POWER = ("8", "4")
_OPAMP_QUAD_CHANNELS = (("1", "2", "3"), ("7", "6", "5"), ("8", "9", "10"), ("14", "13", "12"))
_OPAMP_QUAD_POWER = ("4", "11")
_COMP_QUAD_CHANNELS = (("2", "4", "5"), ("1", "6", "7"), ("14", "8", "9"), ("13", "10", "11"))
_COMP_QUAD_POWER = ("3", "12")
_PART_LETTERS = "ABCDEFGH"


def _amp_triangle(ctx: Ctx, part: int, comparator: bool) -> None:
    b = ctx.b
    b.polygon((0, -200), (0, 200), (400, 0), part=part, filled=False)
    b.minus_sign(50, 100, part=part)
    b.plus_sign(50, -100, part=part)
    if comparator:  # hysteresis glyph
        b.line((120, -30), (190, -30), (190, 30), part=part)
        b.line((150, -30), (150, 30), (220, 30), part=part)


def _amp_channel(
    ctx: Ctx, part: int, out: str, inm: str, inp: str, out_type: ElectricalType, *, comparator: bool
) -> None:
    _amp_triangle(ctx, part, comparator)
    pin_len = ctx.kit.ic_pin_length
    ctx.pin(inm, "-IN", 0, 100, "left", length=pin_len, electrical="input", part=part, show_designator=True)
    ctx.pin(inp, "+IN", 0, -100, "left", length=pin_len, electrical="input", part=part, show_designator=True)
    ctx.pin(out, "OUT", 400, 0, "right", length=pin_len, electrical=out_type, part=part, show_designator=True)


def _amp_power_part(ctx: Ctx, part: int, vplus: str, vminus: str) -> None:
    b = ctx.b
    pin_len = ctx.kit.ic_pin_length
    b.rect(100, -100, 300, 100, part=part)
    b.plus_sign(200, 50, part=part, color=PLUS_COLOR)
    b.minus_sign(200, -50, part=part, color=MINUS_COLOR)
    ctx.pin(vplus, "V+", 200, 100, "up", length=pin_len, electrical="power", part=part, show_designator=True)
    ctx.pin(vminus, "V-", 200, -100, "down", length=pin_len, electrical="power", part=part, show_designator=True)


def _amp_single(ctx: Ctx, out_type: ElectricalType, comparator: bool) -> ResolvedPinMap:
    pm = _with_pinmap(ctx, _OPAMP_PINMAP)
    _amp_triangle(ctx, 1, comparator)
    pin_len = ctx.kit.ic_pin_length
    ctx.func_pins("IN-", 0, 100, "left", length=pin_len, electrical="input", show_designator=True)
    ctx.func_pins("IN+", 0, -100, "left", length=pin_len, electrical="input", show_designator=True)
    ctx.func_pins("OUT", 400, 0, "right", length=pin_len, electrical=out_type, show_designator=True)
    ctx.func_pins("V+", 200, 100, "up", length=pin_len, electrical="power", show_designator=True)
    ctx.func_pins("V-", 200, -100, "down", length=pin_len, electrical="power", show_designator=True)
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    return pm


def _amp_multi(
    ctx: Ctx,
    channels: tuple[tuple[str, str, str], ...],
    power: tuple[str, str],
    out_type: ElectricalType,
    comparator: bool,
) -> None:
    ctx.b.part_count = len(channels) + 1
    for part, (out, inm, inp) in enumerate(channels, start=1):
        _amp_channel(ctx, part, out, inm, inp, out_type, comparator=comparator)
    _amp_power_part(ctx, len(channels) + 1, *power)


def _amp_labels(ctx: Ctx) -> None:
    _labels_at(ctx, (250, 110), (250, _round10_down(-110 - ctx.kit.em)))


def _draw_opamp(ctx: Ctx) -> None:
    pm = _amp_single(ctx, "output", comparator=False)
    ctx.description = f"Operational amplifier ({pm.label})"
    _amp_labels(ctx)


def _draw_opamp_dual(ctx: Ctx) -> None:
    _amp_multi(ctx, _DUAL_CHANNELS, _DUAL_POWER, "output", comparator=False)
    ctx.description = "Dual operational amplifier, parts A/B + power part C (SOIC-8 pinout)"
    _amp_labels(ctx)


def _draw_opamp_quad(ctx: Ctx) -> None:
    _amp_multi(ctx, _OPAMP_QUAD_CHANNELS, _OPAMP_QUAD_POWER, "output", comparator=False)
    ctx.description = "Quad operational amplifier, parts A-D + power part E (SOIC-14 pinout)"
    _amp_labels(ctx)


def _draw_comparator(ctx: Ctx) -> None:
    channels = int(ctx.params["channels"])
    open_drain = ctx.params["output"] == "open_drain"
    out_type: ElectricalType = "open_collector" if open_drain else "output"
    od = " open-drain" if open_drain else ""
    if channels == 1:
        pm = _amp_single(ctx, out_type, comparator=True)
        ctx.description = f"Comparator{od} ({pm.label})"
    else:
        if ctx.params.get("pinmap") not in (None, "", "auto", _OPAMP_PINMAP.default):
            raise SymbolError("Komparator: Die Pinbelegung ist nur für einkanalige Komparatoren wählbar.")
        if channels == 2:
            _amp_multi(ctx, _DUAL_CHANNELS, _DUAL_POWER, out_type, comparator=True)
            ctx.suffix.insert(0, "Dual")
            ctx.description = f"Dual comparator{od}, parts A/B + power part C (LM393 pinout)"
        else:
            _amp_multi(ctx, _COMP_QUAD_CHANNELS, _COMP_QUAD_POWER, out_type, comparator=True)
            ctx.suffix.insert(0, "Quad")
            ctx.description = f"Quad comparator{od}, parts A-D + power part E (LM339 pinout)"
    if open_drain:
        ctx.suffix.insert(1 if channels > 1 else 0, "OD")
    _amp_labels(ctx)


# ======================================================================================
# oscillator, optocouplers
# ======================================================================================
def _draw_oscillator(ctx: Ctx) -> None:
    pin1 = ctx.params["pin1"]
    first = {
        "OE": IcPin(designator="1", name="OE", electrical="input"),
        "ST": IcPin(designator="1", name="S\\T\\", electrical="input"),
        "NC": IcPin(designator="1", name="NC", electrical="passive"),
    }[pin1]
    pins = [
        first,
        IcPin(designator="2", name="GND", electrical="power"),
        IcPin(designator="3", name="OUT", electrical="output"),
        IcPin(designator="4", name="VDD", electrical="power"),
    ]
    if pin1 != "OE":
        ctx.suffix.append(pin1)
    ctx.description = f"Crystal oscillator, 4 pads (1 = {pin1}, 2 = GND, 3 = OUT, 4 = VDD)"
    ctx.spec = build_ic(ctx.kit, "OSC", pins, description=ctx.description, designator_prefix="Y")


_OPTO4_PINMAP = PinMapSpec(
    functions=(
        PinFunction("A", "A", "A"),
        PinFunction("K", "K", "K"),
        PinFunction("C", "C", "C"),
        PinFunction("E", "E", "E"),
    ),
    presets={
        "AKEC": {"A": ("1",), "K": ("2",), "E": ("3",), "C": ("4",)},
        "AKCE": {"A": ("1",), "K": ("2",), "C": ("3",), "E": ("4",)},
    },
    default="AKEC",
    preset_labels={"AKEC": "1 = A, 2 = K, 3 = E, 4 = C (PC817, TLP291)", "AKCE": "1 = A, 2 = K, 3 = C, 4 = E"},
)
_OPTO6_PINMAP = PinMapSpec(
    functions=(
        PinFunction("A", "A", "A"),
        PinFunction("K", "K", "K"),
        PinFunction("B", "B", "B"),
        PinFunction("C", "C", "C"),
        PinFunction("E", "E", "E"),
    ),
    presets={"AKxECB": {"A": ("1",), "K": ("2",), "E": ("4",), "C": ("5",), "B": ("6",)}},
    default="AKxECB",
    preset_labels={"AKxECB": "DIP-6: 1 = A, 2 = K, 3 = NC, 4 = E, 5 = C, 6 = B (4N35)"},
)
_OPTO6_NOBASE_PINMAP = PinMapSpec(
    functions=(
        PinFunction("A", "A", "A"),
        PinFunction("K", "K", "K"),
        PinFunction("C", "C", "C"),
        PinFunction("E", "E", "E"),
    ),
    presets={"AKxECx": {"A": ("1",), "K": ("2",), "E": ("4",), "C": ("5",)}},
    default="AKxECx",
    preset_labels={"AKxECx": "DIP-6 ohne Basis: 1 = A, 2 = K, 4 = E, 5 = C"},
)


def _opto_led(ctx: Ctx) -> None:
    b = ctx.b
    b.polygon((-140, 30), (-60, 30), (-100, -30))
    b.line((-140, -30), (-60, -30))
    b.line((-200, 100), (-100, 100), (-100, 30))
    b.line((-100, -30), (-100, -100), (-200, -100))
    b.arrow((-40, 20), (10, 20))
    b.arrow((-40, -20), (10, -20))


def _opto_transistor(ctx: Ctx) -> None:
    b = ctx.b
    b.line((60, -70), (60, 70))
    b.line((60, 40), (120, 100), (200, 100))
    b.line((60, -40), (120, -100), (200, -100))
    b.arrow_head((110, -90), (1, -1), 30, 10)


def _draw_optocoupler_4(ctx: Ctx) -> None:
    pm = _with_pinmap(ctx, _OPTO4_PINMAP)
    ctx.b.rect(-200, -200, 200, 200)
    _opto_led(ctx)
    _opto_transistor(ctx)
    ctx.func_pins("A", -200, 100, "left")
    ctx.func_pins("K", -200, -100, "left")
    ctx.func_pins("C", 200, 100, "right")
    ctx.func_pins("E", 200, -100, "right")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Optocoupler, LED + phototransistor ({pm.label})"
    _labels_at(ctx, (-200, 210), (-200, _round10_down(-210 - ctx.kit.em)))


def _draw_optocoupler_6(ctx: Ctx) -> None:
    base = bool(ctx.params.get("base"))
    raw = ctx.params.get("pinmap")
    if not base and isinstance(raw, str) and raw.upper() == _OPTO6_PINMAP.default.upper():
        raw = None  # the parameter default belongs to the variant with base pin
    pm = _with_pinmap(ctx, _OPTO6_PINMAP if base else _OPTO6_NOBASE_PINMAP, value=raw)
    b = ctx.b
    b.rect(-200, -200, 200, 200)
    _opto_led(ctx)
    _opto_transistor(ctx)
    ctx.func_pins("A", -200, 100, "left")
    ctx.func_pins("K", -200, -100, "left")
    ctx.func_pins("C", 200, 100, "right")
    ctx.func_pins("E", 200, -100, "right")
    if base:
        b.line((60, 0), (200, 0))
        ctx.func_pins("B", 200, 0, "right")
    else:
        ctx.suffix.append("No-Base")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Optocoupler 6-pin, LED + phototransistor ({pm.label})"
    _labels_at(ctx, (-200, 210), (-200, _round10_down(-210 - ctx.kit.em)))


# ======================================================================================
# connectors, mechanics
# ======================================================================================
MAX_CONNECTOR_ROW = 100
_NUMBERING = {
    "odd_even": "Ungerade links, gerade rechts (1-2 / 3-4 …, Stiftleiste)",
    "row": "Reihenweise (1…N links, N+1…2N rechts)",
    "dip": "Gegen den Uhrzeigersinn (wie DIP: N+1 unten rechts)",
}


def _connector_designators(pins: int, rows: int, numbering: str) -> list[tuple[str, str]]:
    """(left, right) designators per row; right is '' for single-row connectors."""
    if rows == 1:
        return [(str(i), "") for i in range(1, pins + 1)]
    n = pins // 2
    out: list[tuple[str, str]] = []
    for k in range(n):
        if numbering == "odd_even":
            out.append((str(2 * k + 1), str(2 * k + 2)))
        elif numbering == "row":
            out.append((str(k + 1), str(n + k + 1)))
        else:  # dip
            out.append((str(k + 1), str(2 * n - k)))
    return out


def _draw_connector(ctx: Ctx) -> None:
    pins = int(ctx.params["pins"])
    rows = int(ctx.params["rows"])
    numbering = ctx.params["numbering"]
    if rows == 2 and pins % 2:
        raise SymbolError(
            f"Steckverbinder: {pins} Pole lassen sich nicht auf 2 Reihen verteilen (gerade Anzahl nötig)."
        )
    if rows == 2 and pins < 2:
        raise SymbolError("Steckverbinder: Zweireihig sind mindestens 2 Pole nötig.")
    if pins // rows > MAX_CONNECTOR_ROW:
        raise SymbolError(
            f"Steckverbinder: höchstens {MAX_CONNECTOR_ROW} Pole je Reihe ({pins} Pole in {rows} Reihe(n) angefragt)."
        )
    layout = _connector_designators(pins, rows, numbering)
    names: dict[str, str] = {}
    for p in ctx.req.pins:
        names[p.designator] = p.name
    valid = {d for pair in layout for d in pair if d}
    unknown = sorted(set(names) - valid)
    if unknown:
        raise SymbolError(f"Steckverbinder: Pin {', '.join(unknown)} gibt es bei {pins} Polen nicht.")
    custom = any(names.get(d) for d in valid)
    kit = ctx.kit
    g = PIN_PITCH  # house pin pitch (100 mil), independent of the snap grid
    pin_len = kit.ic_pin_length
    if custom:
        w_left = max((kit.text_width(names.get(lp, "")) for lp, _ in layout), default=0.0)
        w_right = max((kit.text_width(names.get(rp, "")) for _, rp in layout if rp), default=0.0)
        content = 50 + w_left + (100 + w_right + 50 if rows == 2 else 50)
        width = max(2 * g, kit.ceil_grid(content, g))
    else:
        width = max(2 * g, kit.ceil_grid(100 if rows == 1 else 200, g))
    n_rows = len(layout)
    height = (n_rows + 1) * g
    b = ctx.b
    b.graphic = kit.ic_body
    b.rect(0, -height, width, 0, filled=True)
    for k, (lp, rp) in enumerate(layout, start=1):
        y = -k * g
        ctx.pin(lp, names.get(lp) or lp, 0, y, "left", length=pin_len, show_designator=True, show_name=custom)
        if rp:
            ctx.pin(rp, names.get(rp) or rp, width, y, "right", length=pin_len, show_designator=True, show_name=custom)
    if rows == 2 and numbering != "odd_even":
        ctx.suffix.append({"row": "Row", "dip": "DIP"}[numbering])
    if custom and not ctx.req.name:
        digest = hashlib.sha1(json.dumps(sorted(names.items())).encode()).hexdigest()[:6].upper()
        ctx.suffix.append(f"(N{digest})")
    ctx.description = f"Connector {rows}x{pins // rows}" + ("" if rows == 1 else f", numbering {numbering}")
    cap = math.ceil(kit.em)
    _labels_at(ctx, (0, 50), (0, -(height + 50 + cap)))


def _draw_test_point(ctx: Ctx) -> None:
    ctx.b.circle(0, 0, 40)
    ctx.pin("1", "TP", 0, -40, "down")
    ctx.description = "Test point"
    _labels_at(ctx, (60, 10), (60, _round10_down(-10 - ctx.kit.em)))


def _draw_mounting_hole(ctx: Ctx) -> None:
    b = ctx.b
    b.circle(0, 0, 100)
    b.circle(0, 0, 50)
    if ctx.params.get("plated"):
        ctx.pin("1", "MH", 0, -100, "down")
        ctx.description = "Mounting hole, plated (pin 1)"
    else:
        ctx.suffix.append("NPTH")
        ctx.description = "Mounting hole, non-plated (no pin)"
    _labels_at(ctx, (130, 10), (130, _round10_down(-10 - ctx.kit.em)))


def _draw_fiducial(ctx: Ctx) -> None:
    b = ctx.b
    b.circle(0, 0, 100)
    b.circle(0, 0, 40, filled=True)
    ctx.description = "Fiducial mark (no pin)"
    _labels_at(ctx, (130, 10), (130, _round10_down(-10 - ctx.kit.em)))


def _draw_switch_2(ctx: Ctx) -> None:
    b = ctx.b
    b.line((-100, 0), (-60, 0), (60, 50))
    b.line((60, 0), (100, 0))
    b.line((60, 0), (60, 20))
    _two_terminal(ctx, -100, 100)
    ctx.description = "Switch, SPST normally open"
    _labels_above_below(ctx)


_PUSH_PINMAP = PinMapSpec(
    functions=(
        PinFunction("L1", "L", "L"),
        PinFunction("L2", "L", "L"),
        PinFunction("R1", "R", "R"),
        PinFunction("R2", "R", "R"),
    ),
    presets={
        "LLRR": {"L1": ("1",), "L2": ("2",), "R1": ("3",), "R2": ("4",)},
        "LRLR": {"L1": ("1",), "R1": ("2",), "L2": ("3",), "R2": ("4",)},
        "LRRL": {"L1": ("1",), "R1": ("2",), "R2": ("3",), "L2": ("4",)},
    },
    default="LLRR",
    preset_labels={
        "LLRR": "1+2 und 3+4 intern verbunden",
        "LRLR": "1+3 und 2+4 intern verbunden",
        "LRRL": "1+4 und 2+3 intern verbunden",
    },
)


def _draw_pushbutton_4(ctx: Ctx) -> None:
    pm = _with_pinmap(ctx, _PUSH_PINMAP)
    b = ctx.b
    b.line((-100, 0), (-100, -100))
    b.line((100, 0), (100, -100))
    b.line((-100, -50), (-60, -50))
    b.line((60, -50), (100, -50))
    b.line((-70, -10), (70, -10))
    b.line((0, -10), (0, 40))
    b.line((-30, 40), (30, 40))
    ctx.func_pins("L1", -100, 0, "left")
    ctx.func_pins("L2", -100, -100, "left")
    ctx.func_pins("R1", 100, 0, "right")
    ctx.func_pins("R2", 100, -100, "right")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Pushbutton, 4 pins, normally open ({pm.label})"
    _labels_above_below(ctx)


_RELAY_PINMAP = PinMapSpec(
    functions=(
        PinFunction("A1", "A1"),
        PinFunction("A2", "A2"),
        PinFunction("COM", "COM"),
        PinFunction("NC", "NC"),
        PinFunction("NO", "NO"),
    ),
    presets={"STANDARD": {"A1": ("1",), "A2": ("2",), "COM": ("3",), "NC": ("4",), "NO": ("5",)}},
    default="STANDARD",
    preset_labels={"STANDARD": "1/2 = Spule, 3 = COM, 4 = NC (Öffner), 5 = NO (Schließer)"},
)


def _draw_relay_spdt(ctx: Ctx) -> None:
    pm = _with_pinmap(ctx, _RELAY_PINMAP)
    b = ctx.b
    b.rect(-150, -100, -50, 100)
    b.line((100, 100), (100, 40), (160, 40))  # NC contact
    b.line((300, 100), (300, 40), (240, 40))  # NO contact
    b.line((200, -100), (140, 50))  # blade, resting on NC
    b.dashed((-50, 0), (150, 0), dash=20, gap=20)
    ctx.func_pins("A1", -100, 100, "up")
    ctx.func_pins("A2", -100, -100, "down")
    ctx.func_pins("NC", 100, 100, "up")
    ctx.func_pins("NO", 300, 100, "up")
    ctx.func_pins("COM", 200, -100, "down")
    if not pm.is_canonical:
        ctx.suffix.append(f"({pm.key})")
    ctx.description = f"Relay, 1 changeover contact (SPDT) ({pm.label})"
    _labels_at(ctx, (330, 60), (330, _round10_down(-10 - ctx.kit.em)))


def _draw_buzzer(ctx: Ctx) -> None:
    b = ctx.b
    b.arc(0, 0, 100, 0, 180)
    b.line((-100, 0), (100, 0))
    b.plus_sign(-50, 40)
    ctx.pin("1", "+", -100, 0, "down")
    ctx.pin("2", "-", 100, 0, "down")
    ctx.description = "Buzzer (1 = +)"
    _labels_at(ctx, (130, 60), (130, _round10_down(-10 - ctx.kit.em)))


def _draw_battery(ctx: Ctx) -> None:
    cells = int(ctx.params["cells"])
    b = ctx.b
    first = -(80 * cells - 40) // 2
    x = first
    for i in range(cells):
        b.line((x, -80), (x, 80))  # + plate (long)
        b.line((x + 40, -40), (x + 40, 40), width="medium")  # - plate (short)
        if i < cells - 1:
            b.line((x + 40, 0), (x + 80, 0))
        x += 80
    last = x - 40
    b.plus_sign(first - 40, 60, half=15)
    ctx.pin("1", "+", first, 0, "left")
    ctx.pin("2", "-", last, 0, "right")
    if cells > 1:
        ctx.suffix.append(f"{cells}-Cell")
    ctx.description = "Battery" + (f", {cells} cells" if cells > 1 else "") + " (1 = +)"
    _labels_above_below(ctx)


# ======================================================================================
# registry
# ======================================================================================
_CORE = {"none": "ohne Kern", "iron": "mit Kern (Eisen)", "ferrite": "mit Ferritkern (gestrichelt)"}
_COMP_OUT = {"push_pull": "Gegentakt (Push-Pull)", "open_drain": "Open-Drain / Open-Collector"}
_OSC_PIN1 = {"OE": "Pin 1 = OE (Enable)", "ST": "Pin 1 = S̅T̅ (Standby, low-aktiv)", "NC": "Pin 1 = NC"}

_P_CIRCLE = _p_bool("circle", "Kreis um das Symbol", False)


@lru_cache(maxsize=1)
def _registry() -> dict[str, KindDef]:
    defs = [
        # --- passive
        KindDef(
            key="resistor",
            label="Widerstand",
            group="Passiv",
            base_name="Resistor",
            prefix="R",
            description="Generic resistor",
            help="Widerstand nach Hausstil (IEC-Rechteck oder ANSI-Zickzack, Einstellung „Widerstandssymbol“).",
            categories=("Resistors",),
            draw=_draw_resistor,
        ),
        KindDef(
            key="potentiometer",
            label="Potentiometer",
            group="Passiv",
            base_name="Potentiometer",
            prefix="R",
            description="Generic potentiometer",
            help="Potentiometer mit 3 Anschlüssen (2 = Schleifer).",
            categories=("Electromechanical", "Resistors"),
            draw=_draw_potentiometer,
        ),
        KindDef(
            key="trimmer",
            label="Trimmpotentiometer",
            group="Passiv",
            base_name="Trimmer",
            prefix="R",
            description="Generic trimmer",
            help="Trimmpotentiometer mit 3 Anschlüssen (2 = Schleifer).",
            categories=("Electromechanical", "Resistors"),
            draw=_draw_trimmer,
        ),
        KindDef(
            key="capacitor",
            label="Kondensator",
            group="Passiv",
            base_name="Capacitor",
            prefix="C",
            description="Generic capacitor",
            help="Ungepolter Kondensator.",
            categories=("Capacitors",),
            draw=_draw_capacitor,
        ),
        KindDef(
            key="capacitor_polarized",
            label="Kondensator, gepolt",
            group="Passiv",
            base_name="Capacitor Polarized",
            prefix="C",
            description="Generic polarized capacitor",
            help="Gepolter Kondensator (Tantal, Elko, Polymer); Pin 1 = Plus wie im IPC-Footprint.",
            categories=("Capacitors",),
            draw=_draw_capacitor_polarized,
            params=(_p_pinmap(_CAP_POL_PINMAP, "Pin 1 = Plus entspricht den IPC-Footprints (CAPMP, CAPAE)."),),
        ),
        KindDef(
            key="inductor",
            label="Induktivität",
            group="Passiv",
            base_name="Inductor",
            prefix="L",
            description="Generic inductor",
            help="Spule/Induktivität, optional mit Kernlinien.",
            categories=("Inductors",),
            draw=_draw_inductor,
            params=(_p_enum("core", "Kern", _CORE, "none"),),
        ),
        KindDef(
            key="ferrite_bead",
            label="Ferrit",
            group="Passiv",
            base_name="Ferrite Bead",
            prefix="FB",
            description="Generic ferrite bead",
            help="Ferrit-Perle (Chip-Ferrit).",
            categories=("Ferrite Beads", "Inductors"),
            draw=_draw_ferrite_bead,
        ),
        KindDef(
            key="crystal_2",
            label="Quarz (2 Pins)",
            group="Passiv",
            base_name="Crystal",
            prefix="Y",
            description="Generic crystal",
            help="Quarz oder Keramikresonator mit 2 Anschlüssen.",
            categories=("Oscillators",),
            draw=_draw_crystal_2,
        ),
        KindDef(
            key="crystal_4",
            label="Quarz (4 Pins)",
            group="Passiv",
            base_name="Crystal 4-Pin",
            prefix="Y",
            description="Generic crystal with case pins",
            help="SMD-Quarz mit 4 Pads (Quarz an 1/3, Gehäuse an 2/4).",
            categories=("Oscillators",),
            draw=_draw_crystal_4,
            params=(_p_pinmap(_CRYSTAL4_PINMAP, "Code je Pad: Q = Quarz, G = Gehäuse/GND."),),
        ),
        KindDef(
            key="fuse",
            label="Sicherung",
            group="Passiv",
            base_name="Fuse",
            prefix="F",
            description="Generic fuse",
            help="Schmelzsicherung.",
            categories=("Fuses",),
            draw=_draw_fuse,
        ),
        KindDef(
            key="ptc",
            label="PTC-Sicherung",
            group="Passiv",
            base_name="PTC Fuse",
            prefix="F",
            description="Generic PTC fuse",
            help="Rückstellende PTC-Sicherung (Polyfuse).",
            categories=("Fuses",),
            draw=_draw_ptc,
        ),
        KindDef(
            key="varistor",
            label="Varistor",
            group="Passiv",
            base_name="Varistor",
            prefix="RV",
            description="Generic varistor",
            help="Varistor (spannungsabhängiger Widerstand).",
            categories=("Fuses",),
            draw=_draw_varistor,
        ),
        # --- semiconductors
        KindDef(
            key="diode",
            label="Diode",
            group="Halbleiter",
            base_name="Diode",
            prefix="D",
            description="Generic diode",
            help="Gleichrichter- oder Schaltdiode.",
            categories=("Diodes",),
            draw=_draw_diode,
            params=(_DIODE_PINMAP_PARAM,),
        ),
        KindDef(
            key="zener",
            label="Z-Diode",
            group="Halbleiter",
            base_name="Zener Diode",
            prefix="D",
            description="Generic zener diode",
            help="Z-Diode.",
            categories=("Diodes",),
            draw=_draw_zener,
            params=(_DIODE_PINMAP_PARAM,),
        ),
        KindDef(
            key="schottky",
            label="Schottky-Diode",
            group="Halbleiter",
            base_name="Schottky Diode",
            prefix="D",
            description="Generic Schottky diode",
            help="Schottky-Diode.",
            categories=("Diodes",),
            draw=_draw_schottky,
            params=(_DIODE_PINMAP_PARAM,),
        ),
        KindDef(
            key="tvs_uni",
            label="TVS-Diode (unidirektional)",
            group="Halbleiter",
            base_name="TVS Diode",
            prefix="D",
            description="Generic TVS diode",
            help="Unidirektionale Suppressordiode.",
            categories=("Diodes", "Fuses"),
            draw=_draw_tvs_uni,
            params=(_DIODE_PINMAP_PARAM,),
        ),
        KindDef(
            key="tvs_bi",
            label="TVS-Diode (bidirektional)",
            group="Halbleiter",
            base_name="TVS Diode Bidirectional",
            prefix="D",
            description="Generic bidirectional TVS diode",
            help="Bidirektionale Suppressordiode.",
            categories=("Diodes", "Fuses"),
            draw=_draw_tvs_bi,
        ),
        KindDef(
            key="led",
            label="LED",
            group="Halbleiter",
            base_name="LED",
            prefix="D",
            description="Generic LED",
            help="Leuchtdiode.",
            categories=("LEDs",),
            draw=_draw_led,
            params=(_DIODE_PINMAP_PARAM,),
        ),
        KindDef(
            key="photodiode",
            label="Fotodiode",
            group="Halbleiter",
            base_name="Photodiode",
            prefix="D",
            description="Generic photodiode",
            help="Fotodiode.",
            categories=("Optocouplers", "Diodes"),
            draw=_draw_photodiode,
            params=(_DIODE_PINMAP_PARAM,),
        ),
        KindDef(
            key="bridge_rectifier",
            label="Brückengleichrichter",
            group="Halbleiter",
            base_name="Bridge Rectifier",
            prefix="D",
            description="Generic bridge rectifier",
            help="Brückengleichrichter mit 4 Anschlüssen.",
            categories=("Diodes",),
            draw=_draw_bridge,
            params=(_p_pinmap(_BRIDGE_PINMAP, "Code je Pin: + / - / A (= ~ Wechselspannung), z. B. '+AA-'."),),
        ),
        KindDef(
            key="npn",
            label="NPN-Transistor",
            group="Halbleiter",
            base_name="NPN",
            prefix="Q",
            description="NPN transistor",
            help="Bipolartransistor NPN; Standard-Pinbelegung SOT-23.",
            categories=("Transistors BJT",),
            draw=lambda c: _draw_bjt(c, pnp=False),
            params=(_p_pinmap(_BJT_PINMAP, "Code je Pin: B, C, E (x = frei), z. B. 'EBC'."), _P_CIRCLE),
        ),
        KindDef(
            key="pnp",
            label="PNP-Transistor",
            group="Halbleiter",
            base_name="PNP",
            prefix="Q",
            description="PNP transistor",
            help="Bipolartransistor PNP; Standard-Pinbelegung SOT-23.",
            categories=("Transistors BJT",),
            draw=lambda c: _draw_bjt(c, pnp=True),
            params=(_p_pinmap(_BJT_PINMAP, "Code je Pin: B, C, E (x = frei), z. B. 'EBC'."), _P_CIRCLE),
        ),
        KindDef(
            key="nmos",
            label="N-Kanal-MOSFET",
            group="Halbleiter",
            base_name="NMOS",
            prefix="Q",
            description="N-channel MOSFET",
            help="N-Kanal-MOSFET (Anreicherung) mit Bodydiode; Standard-Pinbelegung SOT-23.",
            categories=("Transistors FET",),
            draw=lambda c: _draw_mosfet(c, pchannel=False),
            params=(
                _p_pinmap(_FET_PINMAP, "Code je Pin: G, D, S (x = frei), z. B. 'SSSGDDDD' für SO-8."),
                _p_bool("body_diode", "Bodydiode", True),
                _P_CIRCLE,
            ),
        ),
        KindDef(
            key="pmos",
            label="P-Kanal-MOSFET",
            group="Halbleiter",
            base_name="PMOS",
            prefix="Q",
            description="P-channel MOSFET",
            help="P-Kanal-MOSFET (Anreicherung) mit Bodydiode; Standard-Pinbelegung SOT-23.",
            categories=("Transistors FET",),
            draw=lambda c: _draw_mosfet(c, pchannel=True),
            params=(
                _p_pinmap(_FET_PINMAP, "Code je Pin: G, D, S (x = frei), z. B. 'SSSGDDDD' für SO-8."),
                _p_bool("body_diode", "Bodydiode", True),
                _P_CIRCLE,
            ),
        ),
        KindDef(
            key="optocoupler_4",
            label="Optokoppler (4 Pins)",
            group="Halbleiter",
            base_name="Optocoupler",
            prefix="U",
            description="Optocoupler",
            help="Optokoppler LED + Fototransistor, 4 Pins (PC817, TLP291).",
            categories=("Optocouplers",),
            draw=_draw_optocoupler_4,
            params=(_p_pinmap(_OPTO4_PINMAP, "Code je Pin: A, K, C, E."),),
            show_numbers=True,
        ),
        KindDef(
            key="optocoupler_6",
            label="Optokoppler (6 Pins)",
            group="Halbleiter",
            base_name="Optocoupler 6-Pin",
            prefix="U",
            description="Optocoupler 6-pin",
            help="Optokoppler LED + Fototransistor mit Basisanschluss, DIP-6 (4N35).",
            categories=("Optocouplers",),
            draw=_draw_optocoupler_6,
            params=(
                _p_bool("base", "Basisanschluss (Pin 6)", True),
                _p_pinmap(_OPTO6_PINMAP, "Code je Pin: A, K, B, C, E (x = frei)."),
            ),
            show_numbers=True,
        ),
        # --- ICs
        KindDef(
            key="opamp",
            label="Operationsverstärker",
            group="ICs",
            base_name="Op-Amp",
            prefix="U",
            description="Operational amplifier",
            help="Einfach-OPV mit Versorgungspins (5 Pins).",
            categories=("Amplifiers",),
            draw=_draw_opamp,
            params=(_p_pinmap(_OPAMP_PINMAP, "Gehäuse-Pinbelegung des Einfach-OPVs."),),
            show_numbers=True,
        ),
        KindDef(
            key="opamp_dual",
            label="Operationsverstärker (zweifach)",
            group="ICs",
            base_name="Op-Amp Dual",
            prefix="U",
            description="Dual operational amplifier",
            help="Zweifach-OPV als mehrteiliges Symbol: Teil A/B je Verstärker, Teil C Versorgung (SOIC-8, LM358).",
            categories=("Amplifiers",),
            draw=_draw_opamp_dual,
            show_numbers=True,
        ),
        KindDef(
            key="opamp_quad",
            label="Operationsverstärker (vierfach)",
            group="ICs",
            base_name="Op-Amp Quad",
            prefix="U",
            description="Quad operational amplifier",
            help="Vierfach-OPV als mehrteiliges Symbol: Teil A–D je Verstärker, Teil E Versorgung (SOIC-14, LM324).",
            categories=("Amplifiers",),
            draw=_draw_opamp_quad,
            show_numbers=True,
        ),
        KindDef(
            key="comparator",
            label="Komparator",
            group="ICs",
            base_name="Comparator",
            prefix="U",
            description="Comparator",
            help="Komparator ein-, zwei- oder vierfach (Pinbelegung wie LM393 bzw. LM339).",
            categories=("Amplifiers",),
            draw=_draw_comparator,
            params=(
                _p_enum("channels", "Kanäle", {"1": "1 (einfach)", "2": "2 (LM393)", "4": "4 (LM339)"}, "1"),
                _p_enum("output", "Ausgang", _COMP_OUT, "push_pull"),
                _p_pinmap(_OPAMP_PINMAP, "Nur einkanalig: Gehäuse-Pinbelegung."),
            ),
            show_numbers=True,
        ),
        KindDef(
            key="oscillator",
            label="Oszillator (4 Pins)",
            group="ICs",
            base_name="Oscillator",
            prefix="Y",
            description="Crystal oscillator",
            help="Quarzoszillator mit 4 Pads (1 = OE/ST/NC, 2 = GND, 3 = OUT, 4 = VDD).",
            categories=("Oscillators",),
            draw=_draw_oscillator,
            params=(_p_enum("pin1", "Funktion Pin 1", _OSC_PIN1, "OE"),),
            show_numbers=True,
        ),
        # --- connectors
        KindDef(
            key="connector",
            label="Steckverbinder",
            group="Verbinder",
            base_name="Connector 1x02",
            prefix="J",
            description="Connector",
            help="Stift-/Buchsenleiste ein- oder zweireihig; eigene Pinnamen über die Pinliste.",
            categories=("Connectors",),
            draw=_draw_connector,
            params=(
                _p_int("pins", "Pole gesamt", 2, 1, 200),
                _p_enum("rows", "Reihen", {"1": "1 Reihe", "2": "2 Reihen"}, "1"),
                _p_enum("numbering", "Nummerierung (2 Reihen)", _NUMBERING, "odd_even"),
            ),
            show_numbers=True,
        ),
        KindDef(
            key="test_point",
            label="Testpunkt",
            group="Verbinder",
            base_name="Test Point",
            prefix="TP",
            description="Test point",
            help="Testpunkt mit 1 Pin.",
            categories=("Mechanical", "Connectors"),
            draw=_draw_test_point,
        ),
        # --- other
        KindDef(
            key="mounting_hole",
            label="Befestigungsloch",
            group="Sonstige",
            base_name="Mounting Hole",
            prefix="MH",
            description="Mounting hole",
            help="Befestigungsloch; durchkontaktiert mit Pin 1 (z. B. an GND).",
            categories=("Mechanical",),
            draw=_draw_mounting_hole,
            params=(_p_bool("plated", "Durchkontaktiert (mit Pin 1)", True),),
        ),
        KindDef(
            key="fiducial",
            label="Passermarke",
            group="Sonstige",
            base_name="Fiducial",
            prefix="FID",
            description="Fiducial",
            help="Passermarke für die Bestückung (ohne Pin).",
            categories=("Mechanical",),
            draw=_draw_fiducial,
        ),
        KindDef(
            key="switch_2",
            label="Schalter (2 Pins)",
            group="Sonstige",
            base_name="Switch",
            prefix="SW",
            description="Switch",
            help="Schalter/Taster mit 2 Anschlüssen (Schließer).",
            categories=("Electromechanical",),
            draw=_draw_switch_2,
        ),
        KindDef(
            key="pushbutton_4",
            label="Taster (4 Pins)",
            group="Sonstige",
            base_name="Pushbutton 4-Pin",
            prefix="SW",
            description="Pushbutton",
            help="Kurzhubtaster mit 4 Pins (je 2 intern verbunden).",
            categories=("Electromechanical",),
            draw=_draw_pushbutton_4,
            params=(_p_pinmap(_PUSH_PINMAP, "Code je Pin: L = linker Kontakt, R = rechter Kontakt."),),
            show_numbers=True,
        ),
        KindDef(
            key="relay_spdt",
            label="Relais (Wechsler)",
            group="Sonstige",
            base_name="Relay SPDT",
            prefix="K",
            description="Relay SPDT",
            help="Relais mit Spule und einem Wechselkontakt (COM, NC, NO).",
            categories=("Electromechanical",),
            draw=_draw_relay_spdt,
            params=(_p_pinmap(_RELAY_PINMAP, 'Eigene Belegung als Objekt, z. B. {"A1": "1", "COM": "11"}.'),),
            show_numbers=True,
        ),
        KindDef(
            key="buzzer",
            label="Summer",
            group="Sonstige",
            base_name="Buzzer",
            prefix="BZ",
            description="Buzzer",
            help="Summer/Signalgeber (1 = Plus).",
            categories=("Electromechanical",),
            draw=_draw_buzzer,
        ),
        KindDef(
            key="battery",
            label="Batterie",
            group="Sonstige",
            base_name="Battery",
            prefix="BT",
            description="Battery",
            help="Batterie/Zelle (1 = Plus).",
            categories=("Electromechanical",),
            draw=_draw_battery,
            params=(_p_int("cells", "Zellen", 1, 1, 4),),
        ),
    ]
    return {d.key: d for d in defs}


def kind_defs() -> list[KindDef]:
    return list(_registry().values())


def get_kind(key: str) -> KindDef:
    try:
        return _registry()[key]
    except KeyError:
        known = ", ".join(sorted(_registry()))
        raise SymbolError(f"Unbekannter Symboltyp {key!r}. Verfügbar: {known}, ic.") from None


_DIODE_KINDS = frozenset({"diode", "zener", "schottky", "tvs_uni", "led", "photodiode"})
_KIND_PINMAPS: dict[str, PinMapSpec] = {
    **{k: _DIODE_PINMAP for k in _DIODE_KINDS},
    "capacitor_polarized": _CAP_POL_PINMAP,
    "crystal_4": _CRYSTAL4_PINMAP,
    "bridge_rectifier": _BRIDGE_PINMAP,
    "npn": _BJT_PINMAP,
    "pnp": _BJT_PINMAP,
    "nmos": _FET_PINMAP,
    "pmos": _FET_PINMAP,
    "opamp": _OPAMP_PINMAP,
    "optocoupler_4": _OPTO4_PINMAP,
    "pushbutton_4": _PUSH_PINMAP,
    "relay_spdt": _RELAY_PINMAP,
}
# pin function that also takes a tab / exposed pad of the package (several pads, one net)
_TAB_FUNCTIONS = {"npn": "C", "pnp": "C", "nmos": "D", "pmos": "D"}


def kind_pinmap(kind: str, params: Mapping[str, Any] | None = None) -> PinMapSpec | None:
    """Pin-map spec of ``kind`` with ``params`` (``None`` = fixed pinout without ``pinmap``)."""
    params = params or {}
    if kind == "comparator":
        return _OPAMP_PINMAP if str(params.get("channels", "1")) == "1" else None
    if kind == "optocoupler_6":
        base = params.get("base", True)
        has_base = base if isinstance(base, bool) else str(base).strip().lower() not in _FALSE
        return _OPTO6_PINMAP if has_base else _OPTO6_NOBASE_PINMAP
    return _KIND_PINMAPS.get(kind)


def tab_function(kind: str) -> str | None:
    """Function key that a package tab / exposed pad belongs to (MOSFET drain, BJT collector)."""
    return _TAB_FUNCTIONS.get(kind)


def is_diode_kind(kind: str) -> bool:
    """Kinds whose default numbering follows ``SymbolStyle.diode_pin1``."""
    return kind in _DIODE_KINDS


# ======================================================================================
# generation
# ======================================================================================
def normalize_params(kind: KindDef, params: Mapping[str, Any]) -> dict[str, Any]:
    known = {p.name for p in kind.params}
    unknown = sorted(set(params) - known)
    if unknown:
        allowed = ", ".join(sorted(known)) or "keine"
        raise SymbolError(f"{kind.label}: unbekannte Parameter {', '.join(unknown)} (erlaubt: {allowed}).")
    out: dict[str, Any] = {}
    for spec in kind.params:
        raw = params.get(spec.name, spec.default)
        if raw is None:
            raw = spec.default
        out[spec.name] = _coerce(spec, raw, kind.label)
    return out


def _compose_name(base: str, suffix: list[str]) -> str:
    return " ".join([base, *suffix]).strip()


def build_standard(req: SymbolRequest, kit: StyleKit) -> SymbolSpec:
    """Generate a standard symbol for ``req`` with an already sanitised style."""
    kind = get_kind(req.kind)
    params = normalize_params(kind, req.params)
    if req.pins and kind.key != "connector":
        raise SymbolError(f"{kind.label}: eine Pinliste ist nur für ICs und Steckverbinder vorgesehen.")
    b = SymbolBuilder(kit)
    ctx = Ctx(kit=kit, kind=kind, params=params, req=req, b=b)
    kind.draw(ctx)
    base = kind.base_name
    if kind.key == "connector":
        base = f"Connector {int(params['rows'])}x{int(params['pins']) // int(params['rows']):02d}"
    default_name = _compose_name(base, ctx.suffix)
    name = check_name(req.name or default_name)
    prefix = check_prefix(req.designator_prefix or kind.prefix)
    description = req.description if req.description is not None else ctx.description
    generator: dict[str, Any] = {
        "kind": kind.key,
        "version": GENERATOR_VERSION,
        "params": params,
        "request": req.model_dump(mode="json", exclude_defaults=True),
        "style": kit.as_dict(),
        "default_name": default_name,
    }
    if name.casefold() != default_name.casefold():
        generator["name"] = name  # custom name: the generator reproduces it from request.name
    if ctx.pinmap is not None:
        generator["pinmap"] = {"key": ctx.pinmap.key, "pins": {k: list(v) for k, v in ctx.pinmap.pins.items()}}
    if ctx.spec is not None:  # box-style kinds built through the IC generator
        spec = ctx.spec
        gen = dict(spec.generator or {})
        gen.update(generator)
        return spec.model_copy(
            update={"name": name, "designator_prefix": prefix, "description": description, "generator": gen}
        )
    generator["text_positions"] = ctx.text_positions or {}
    return b.build(name=name, description=description, prefix=prefix, generator=generator)
