"""Two-terminal chip components: resistors, MLCC, chip inductors, ferrite beads, chip diodes and LEDs.

Dimensions (mm, (min, max)):
* resistors: Vishay D/CRCW e3 (rev. 14-Apr-2026), terminal T = bottom terminal T2 (IPC uses the
  bottom-side termination); 1812 from KiCad R_1812 (Panasonic)
* MLCC: KEMET/YAGEO C1002 X7R (2026-09-01), T = band width B, thickness codes per size
* inductors / ferrite beads / diodes / LEDs: typical vendor values (Murata BLM/LQM, Kingbright) –
  marked "typisch" in the preset source, check against the datasheet
IPC-7351B tables 3-5 (>= 0603) and 3-6 (< 0603, KiCad rounding 0.02 mm).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import BLACK_BODY, FERRITE_BODY, INDUCTOR_BODY, LED_BODY, MLCC_BODY, RESISTOR_BODY
from ..ipc7351 import fmt_mm
from ..models import FamilyInfo, Preset, Tol
from ..params import nom
from .base import (
    COMMON_SMD,
    FamilyDef,
    GenContext,
    describe,
    p_enum,
    p_tol,
    split_body_3d,
    terminals_3d,
    two_terminal,
)

Range = tuple[float, float]

# imperial -> metric code (IPC names use the metric code)
METRIC: dict[str, str] = {
    "01005": "0402", "0201": "0603", "0402": "1005", "0603": "1608", "0805": "2012", "1008": "2520",
    "1206": "3216", "1210": "3225", "1808": "4520", "1812": "4532", "2010": "5025", "2220": "5750",
    "2512": "6332",
}
# house names of the TR_Passives library use 6432 for 2512
HOUSE_METRIC: dict[str, str] = {**METRIC, "2512": "6432"}
_METRIC_TO_IMPERIAL = {v: k for k, v in METRIC.items()}
_METRIC_TO_IMPERIAL["6432"] = "2512"
_AMBIGUOUS = {"0402", "0603"}  # imperial and metric codes that collide


@dataclass(frozen=True)
class ChipDims:
    L: Range
    W: Range
    T: Range
    heights: tuple[tuple[float, float], ...]  # (nominal, ± tolerance); first = default
    source: str


def _hd(*values: tuple[float, float]) -> tuple[tuple[float, float], ...]:
    return values


_VISHAY = "Vishay D/CRCW e3 (Rev. 14.04.2026), T = Anschluss Unterseite"
_KEMET = "KEMET/YAGEO C1002 X7R (2026-09-01), T = Bandbreite B"
_TYP = "typische Herstellerwerte – bitte mit dem Datenblatt prüfen"

RESISTOR: dict[str, ChipDims] = {
    "01005": ChipDims((0.38, 0.42), (0.18, 0.22), (0.07, 0.13), _hd((0.13, 0.02)), _VISHAY),
    "0201": ChipDims((0.57, 0.63), (0.27, 0.33), (0.05, 0.15), _hd((0.23, 0.03)), _VISHAY),
    "0402": ChipDims((0.95, 1.05), (0.45, 0.55), (0.10, 0.30), _hd((0.35, 0.05)), _VISHAY),
    "0603": ChipDims((1.50, 1.65), (0.75, 0.95), (0.10, 0.50), _hd((0.45, 0.05)), _VISHAY),
    "0805": ChipDims((1.90, 2.20), (1.10, 1.40), (0.10, 0.50), _hd((0.50, 0.10)), _VISHAY),
    "1206": ChipDims((3.00, 3.30), (1.45, 1.75), (0.20, 0.60), _hd((0.55, 0.05)), _VISHAY),
    "1210": ChipDims((3.00, 3.40), (2.30, 2.70), (0.20, 0.60), _hd((0.55, 0.05)), _VISHAY),
    "1812": ChipDims((4.30, 4.70), (3.00, 3.40), (0.30, 0.70), _hd((0.60, 0.10)),
                     "KiCad R_1812 (Panasonic); Höhe typisch"),
    "2010": ChipDims((4.85, 5.15), (2.35, 2.65), (0.40, 0.80), _hd((0.60, 0.10)), _VISHAY),
    "2512": ChipDims((6.10, 6.50), (3.00, 3.30), (0.40, 0.80), _hd((0.60, 0.10)), _VISHAY),
}

CAPACITOR: dict[str, ChipDims] = {
    "01005": ChipDims((0.38, 0.42), (0.18, 0.22), (0.07, 0.14), _hd((0.20, 0.02)), f"Murata/Samsung, {_TYP}"),
    "0201": ChipDims((0.57, 0.63), (0.27, 0.33), (0.10, 0.20), _hd((0.30, 0.03)), f"Murata/Samsung, {_TYP}"),
    "0402": ChipDims((0.95, 1.05), (0.45, 0.55), (0.20, 0.40), _hd((0.50, 0.05)), _KEMET),
    "0603": ChipDims((1.45, 1.75), (0.65, 0.95), (0.20, 0.50), _hd((0.80, 0.07)), _KEMET),
    "0805": ChipDims((1.80, 2.20), (1.05, 1.45), (0.25, 0.75), _hd((1.25, 0.20), (0.70, 0.20)), _KEMET),
    "1206": ChipDims((3.00, 3.40), (1.40, 1.80), (0.25, 0.75),
                     _hd((1.60, 0.20), (0.78, 0.10), (1.00, 0.10), (1.25, 0.15)), _KEMET),
    "1210": ChipDims((3.00, 3.40), (2.30, 2.70), (0.25, 0.75),
                     _hd((2.50, 0.30), (0.78, 0.10), (1.25, 0.15), (1.60, 0.20), (2.00, 0.20)), _KEMET),
    "1808": ChipDims((4.20, 5.20), (1.80, 2.20), (0.25, 0.95), _hd((1.60, 0.20)),
                     f"KEMET (Körper/Band); Höhe {_TYP}"),
    "1812": ChipDims((4.20, 4.80), (2.90, 3.50), (0.25, 0.95),
                     _hd((2.50, 0.20), (1.00, 0.10), (1.60, 0.20), (2.00, 0.20)), _KEMET),
    "2220": ChipDims((5.30, 6.10), (4.60, 5.40), (0.25, 0.95), _hd((2.50, 0.30)),
                     f"KEMET (Körper); Band und Höhe {_TYP}"),
}

FERRITE: dict[str, ChipDims] = {
    "0201": ChipDims((0.57, 0.63), (0.27, 0.33), (0.10, 0.20), _hd((0.30, 0.03)), f"Murata BLM03, {_TYP}"),
    "0402": ChipDims((0.95, 1.05), (0.45, 0.55), (0.15, 0.35), _hd((0.50, 0.05)), f"Murata BLM15, {_TYP}"),
    "0603": ChipDims((1.45, 1.75), (0.65, 0.95), (0.20, 0.50), _hd((0.80, 0.15)), f"Murata BLM18, {_TYP}"),
    "0805": ChipDims((1.80, 2.20), (1.05, 1.45), (0.30, 0.70), _hd((0.85, 0.20)), f"Murata BLM21, {_TYP}"),
    "1206": ChipDims((3.00, 3.40), (1.40, 1.80), (0.30, 0.70), _hd((1.10, 0.20)), f"Murata BLM31, {_TYP}"),
}

INDUCTOR: dict[str, ChipDims] = {
    **FERRITE,
    "0402": ChipDims((0.95, 1.05), (0.45, 0.55), (0.15, 0.35), _hd((0.50, 0.05)), f"Murata LQG15/LQW15, {_TYP}"),
    "0603": ChipDims((1.45, 1.75), (0.65, 0.95), (0.20, 0.50), _hd((0.80, 0.15)), f"Murata LQM18/LQW18, {_TYP}"),
    "0805": ChipDims((1.80, 2.20), (1.05, 1.45), (0.30, 0.70), _hd((0.90, 0.20)), f"Murata LQM21, {_TYP}"),
    "1008": ChipDims((2.30, 2.70), (1.80, 2.20), (0.35, 0.85), _hd((1.80, 0.20)),
                     f"KiCad L_1008 (ECS); Höhe {_TYP}"),
}

LED: dict[str, ChipDims] = {
    "0402": ChipDims((0.90, 1.10), (0.40, 0.60), (0.15, 0.35), _hd((0.40, 0.05)), f"Kingbright APHHS1005, {_TYP}"),
    "0603": ChipDims((1.50, 1.70), (0.70, 0.90), (0.20, 0.45), _hd((0.70, 0.10)), f"Kingbright APT1608, {_TYP}"),
    "0805": ChipDims((1.90, 2.10), (1.15, 1.35), (0.30, 0.50), _hd((0.80, 0.10)), f"Kingbright APT2012, {_TYP}"),
    "1206": ChipDims((3.10, 3.30), (1.50, 1.70), (0.40, 0.60), _hd((1.10, 0.10)), f"Kingbright APT3216, {_TYP}"),
}

DIODE: dict[str, ChipDims] = {
    "0603": ChipDims((1.50, 1.70), (0.70, 0.90), (0.20, 0.40), _hd((0.60, 0.10)), f"Chip-Diode 1608, {_TYP}"),
    "0805": ChipDims((1.90, 2.10), (1.15, 1.35), (0.25, 0.55), _hd((0.85, 0.10)), f"Chip-Diode 2012, {_TYP}"),
    "1206": ChipDims((3.00, 3.40), (1.40, 1.80), (0.30, 0.70), _hd((1.05, 0.15)), f"Chip-Diode 3216, {_TYP}"),
}

TABLES: dict[str, dict[str, ChipDims]] = {
    "R": RESISTOR, "C": CAPACITOR, "L": INDUCTOR, "FB": FERRITE, "D": DIODE, "LED": LED,
}
KINDS = list(TABLES)
KIND_LABELS = {
    "R": "Widerstand", "C": "Kondensator", "L": "Induktivität", "FB": "Ferrit", "D": "Diode", "LED": "LED",
}
IPC_PREFIX = {"R": "RESC", "C": "CAPC", "L": "INDC", "FB": "INDC", "D": "DIOC", "LED": "LEDC"}
HOUSE_TYPE = {"R": "RES", "C": "CAP", "L": "IND", "FB": "FER", "D": "DIODE", "LED": "LED"}
FAMILY_WORD = {
    "R": "Chip Resistor", "C": "Chip Capacitor", "L": "Chip Inductor", "FB": "Chip Ferrite Bead",
    "D": "Chip Diode", "LED": "Chip LED",
}
BODY_COLOR = {"R": RESISTOR_BODY, "C": MLCC_BODY, "L": INDUCTOR_BODY, "FB": FERRITE_BODY, "D": BLACK_BODY,
              "LED": LED_BODY}
POLARIZED = {"D", "LED"}
_SIZE_ORDER = ["01005", "0201", "0402", "0603", "0805", "1008", "1206", "1210", "1808", "1812", "2010", "2220",
               "2512"]
SIZES = [s for s in _SIZE_ORDER if any(s in t for t in TABLES.values())]
SMALL_SIZES = {"01005", "0201", "0402"}


def normalize_size(text: str) -> str:
    """EIA imperial code from inputs like "0603", "1608", "1608M", "0603/1608", "R0603", "2512_6332"."""
    raw = str(text).strip().upper().replace(" ", "")
    raw = re.sub(r"^(RESC|CAPC|INDC|DIOC|LEDC|RES|CAP|IND|FER|LED|R|C|L|D|FB)[-_]?", "", raw)
    metric_hint = bool(re.search(r"(M|METRIC)$", raw))
    raw = re.sub(r"(M|METRIC)$", "", raw)
    parts = [p for p in re.split(r"[/_()\-]+", raw) if p]
    for part in parts:
        if metric_hint and part in _METRIC_TO_IMPERIAL:
            return _METRIC_TO_IMPERIAL[part]
        if part in METRIC:
            return part
        if part in _METRIC_TO_IMPERIAL and part not in _AMBIGUOUS:
            return _METRIC_TO_IMPERIAL[part]
    raise ValueError(f"Unbekannte Chip-Baugröße „{text}“ (z. B. 0402, 0603, 0805, 1206 oder metrisch 1608).")


def dims_for(kind: str, size: str) -> tuple[ChipDims, str | None]:
    """Dimensions for kind/size; falls back to the MLCC/resistor body table with a note."""
    table = TABLES[kind]
    if size in table:
        return table[size], None
    for fallback in (CAPACITOR, RESISTOR):
        if size in fallback:
            return fallback[size], (f"Für {KIND_LABELS[kind]} {size} sind keine typischen Maße hinterlegt – "
                                    "Körpermaße der MLCC-/Widerstandstabelle verwendet, bitte Datenblatt prüfen.")
    raise ValueError(f"Baugröße {size} ist für {KIND_LABELS[kind]} nicht hinterlegt – bitte Maße eingeben.")


def match_size(kind: str, L: Tol, W: Tol) -> str | None:  # noqa: N803
    """Standard size whose nominal body matches L/W (for naming custom dimension sets)."""
    best: tuple[float, str] | None = None
    for table in (TABLES[kind], CAPACITOR, RESISTOR):
        for size, d in table.items():
            ln, wn = sum(d.L) / 2, sum(d.W) / 2
            dl, dw = abs(nom(L) - ln), abs(nom(W) - wn)
            if dl <= max(0.1, 0.1 * ln) and dw <= max(0.1, 0.15 * wn):
                score = dl + dw
                if best is None or score < best[0]:
                    best = (score, size)
    return best[1] if best else None


def _tol(r: Range) -> dict[str, float]:
    return {"min": r[0], "max": r[1]}


def _height_tol(h: tuple[float, float]) -> dict[str, float]:
    return {"min": round(h[0] - h[1], 3), "nom": h[0], "max": round(h[0] + h[1], 3)}


def _presets() -> list[Preset]:
    presets: list[Preset] = []
    for kind, table in TABLES.items():
        for size in sorted(table, key=lambda s: METRIC[s]):
            d = table[size]
            for i, h in enumerate(d.heights):
                key = f"{kind}-{size}" if i == 0 else f"{kind}-{size}-{h[0]:.2f}"
                label = f"{KIND_LABELS[kind]} {size} ({METRIC[size]})"
                if len(d.heights) > 1:
                    label += f", Höhe {h[0]:.2f} mm".replace(".", ",")
                presets.append(Preset(
                    key=key, label=label, source=d.source,
                    params={"kind": kind, "size": size, "L": _tol(d.L), "W": _tol(d.W), "T": _tol(d.T),
                            "H": _height_tol(h)},
                ))
    return presets


PARAMS = [
    p_enum("kind", "Bauteilart", KINDS, default="R", group="Typ",
           help="R Widerstand, C Kondensator, L Induktivität, FB Ferrit, D Diode, LED."),
    p_enum("size", "Baugröße (EIA)", SIZES, group="Typ",
           help="Zoll-Code (0603 = 1608 metrisch). Leer, wenn nur eigene Maße verwendet werden."),
    p_tol("L", "Körperlänge L", help="Länge über die Anschlüsse (min/max laut Datenblatt)."),
    p_tol("W", "Körperbreite W"),
    p_tol("T", "Anschlusslänge T", group="Anschlüsse",
          help="Länge der Metallisierung auf der Unterseite (bei MLCC Bandbreite B)."),
    p_tol("H", "Bauhöhe H", help="Höhe (bei MLCC Dickencode); IPC-Name nutzt den Maximalwert."),
    p_enum("cathode_pad", "Kathode an Pad", ["1", "2"], default="1", group="Optionen",
           help="Nur Dioden/LEDs: IPC = Kathode an Pad 1 (links)."),
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="chip",
    label="Chip-Bauteile (R, C, L, Ferrit, Diode, LED)",
    group="Chip-Bauteile",
    description="Zweipolige Chip-Bauteile nach EIA (01005 … 2512) mit IPC-7351B-Lötflächen.",
    params=PARAMS,
    presets=_presets(),
    ipc_table="3-5 / 3-6",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    kind = p.enum("kind", "R")
    size: str | None = None
    if p.given("size"):
        size = normalize_size(p.text("size"))
        p.resolved["size"] = size
    elif not (p.given("L") or p.given("W")):
        size = "0603"
        p.resolved["size"] = size
    base: ChipDims | None = None
    if size is not None:
        base, note = dims_for(kind, size)
        if note:
            ctx.warn(note)
    L = p.tol("L", Tol(min=base.L[0], max=base.L[1]) if base else None)  # noqa: N806
    W = p.tol("W", Tol(min=base.W[0], max=base.W[1]) if base else None)  # noqa: N806
    if base is not None and size is not None and (abs(nom(L) - sum(base.L) / 2) > 0.3
                                                  or abs(nom(W) - sum(base.W) / 2) > 0.3):
        ctx.warn(f"Die Körpermaße passen nicht zur Baugröße {size} – Name und Beschreibung nutzen trotzdem {size}.")
    if size is None:
        size = match_size(kind, L, W)
        if size is not None:
            base, _ = dims_for(kind, size)
    T = p.tol("T", Tol(min=base.T[0], max=base.T[1]) if base else None)  # noqa: N806
    default_h = base.heights[0] if base else None
    if base is not None and size is not None:  # standard dimension sets of this size (identity check)
        ctx.references.extend({"kind": kind, "size": size, "L": _tol(base.L), "W": _tol(base.W),
                               "T": _tol(base.T), "H": _height_tol(h)} for h in base.heights)
    H = p.tol_opt("H")  # noqa: N806
    if H is None:
        if default_h is not None:
            H = Tol(min=default_h[0] - default_h[1], max=default_h[0] + default_h[1], nom=default_h[0])  # noqa: N806
        else:
            H = Tol(min=nom(W), max=nom(W))  # noqa: N806
            ctx.warn(f"Bauhöhe nicht angegeben – {fmt_mm(nom(W))} mm (Körperbreite) angenommen.")
        p.resolved["H"] = {"min": H.min, "nom": nom(H), "max": H.max}
    if T.max * 2 >= L.min:
        raise ValueError("Anschlusslänge T ist zu groß für die Körperlänge L (2·T ≥ L).")

    small = size in SMALL_SIZES if size else nom(L) < 1.55
    table = "chip_small" if small else "chip"
    land = ctx.ipc_land(L, T, W, table, label="Anschlüsse")
    ctx.finalize_land(land)

    polarized = kind in POLARIZED
    mark = ctx.cathode_pad() if polarized else None
    b = ctx.builder(small_silk=True)
    two_terminal(b, land, body_length=nom(L), body_width=nom(W), mark_pad=mark)

    height = H.max
    t3d = min(max(nom(T), 0.05), nom(L) / 3)
    terminals_3d(b, length=nom(L), width=nom(W), t=t3d, z1=height)
    split_body_3d(b, length=nom(L) - 2 * t3d, width=nom(W), z0=0.0, z1=height, color=BODY_COLOR[kind],
                  band_side=mark if kind == "D" else None)

    metric = METRIC.get(size) if size else None
    ipc_name = naming.ipc_chip(IPC_PREFIX[kind], nom(L), nom(W), height, ctx.density, metric_code=metric)
    height_suffix = None
    if kind == "C" and base is not None and default_h is not None and abs(nom(H) - default_h[0]) > 0.005:
        height_suffix = nom(H)
    size_text = f"{size}_{HOUSE_METRIC[size]}" if size else naming.house_body(nom(L), nom(W))
    house_name = naming.house_passive(HOUSE_TYPE[kind], size_text, ctx.density, height=height_suffix)
    package = f"{size} ({METRIC[size]})" if size else f"{nom(L):.2f}x{nom(W):.2f} mm"
    if metric:  # standard EIA size: describe with the nominal metric body (house: "Body 1.60x0.80mm")
        body_l, body_w = int(metric[:2]) / 10, int(metric[2:]) / 10
    else:
        body_l, body_w = nom(L), nom(W)
    description = describe(FAMILY_WORD[kind], 2, body_l, body_w, ctx.density)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description, package=package,
                      height=height, courtyard_table=table)


ALIAS_PARAMS = {
    "resistor": {"kind": "R"}, "resc": {"kind": "R"},
    "capacitor": {"kind": "C"}, "capc": {"kind": "C"}, "mlcc": {"kind": "C"},
    "inductor": {"kind": "L"}, "indc": {"kind": "L"},
    "ferrite": {"kind": "FB"}, "ferrite_bead": {"kind": "FB"},
    "chip_diode": {"kind": "D"}, "dioc": {"kind": "D"},
    "chip_led": {"kind": "LED"}, "ledc": {"kind": "LED"},
}

FAMILIES = [FamilyDef(INFO, build, aliases=("smd_chip", "passive"), alias_params=ALIAS_PARAMS)]
