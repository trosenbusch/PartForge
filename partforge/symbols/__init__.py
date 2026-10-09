"""Schematic symbol generator (contract: docs/entwicklung/ARCHITEKTUR.md §7).

Public API::

    kinds() -> list[SymbolKindInfo]
    generate(req: SymbolRequest, style: SymbolStyle | None = None) -> SymbolSpec
    ic_symbol(name, pins: list[IcPin], *, parts=None, style=None, ...) -> SymbolSpec
    auto_assign_sides(pins: list[IcPin], *, regulator=None) -> list[IcPin]
    standard_symbol_for(category_table: str, values: dict, *, pins=None, footprint=None) -> SymbolRequest | None
    suggest_symbol(category_table, values, *, pins=None, footprint=None, style=None) -> SymbolSuggestion
    render_svg(spec, *, theme="altium", part=None, ...) -> str      # thumbnails / previews
    render_parts(spec, **kw) -> list[str]                              # one SVG per part
    render_thumbnail(spec, *, theme="dark", style=None) -> str        # sans font, constant stroke width
    check_spec(spec, *, grid=100) -> list[str]                         # writer-level checks
    spec_warnings(spec, *, grid=100) -> list[str]                      # check_spec + soft hints
    example_request(kind) -> SymbolRequest                             # default request per kind

Generated specs carry ``generator = {"kind", "version", "params", "request", "style",
"pinmap"?, "text_positions": {"designator"|"comment": {"x", "y", "justify"}}, "default_name",
"name"?}`` (mil); IC symbols add ``"layout": {"width", "height", "parts", "sizes": [[w, h] per part]}``.
``default_name`` is the name the request gives without an explicit name; ``name`` is only present
for a custom name (``SymbolRequest.name`` other than ``default_name``, e.g. ``MY_OPAMP``) and then
also stands in ``request.name`` – regenerating reproduces it. :func:`with_name_record` keeps both
right when a spec is saved under another name.

Symbol names are fixed per kind + pinout: a name without a pin-map suffix always means the
canonical map (e.g. diode pin 1 = cathode), whatever the house style says.

``style=None`` uses the open workspace's ``SymbolStyle`` (or the defaults). Invalid
requests raise :class:`SymbolError` (a ``ValueError`` with a German message).
"""

from __future__ import annotations

from typing import Any

from ..geometry.model import SymbolSpec
from ..workspace import SymbolStyle
from .errors import SymbolError
from .ic import MAX_PINS_PER_SIDE, auto_assign_sides, build_ic, classify_pin, ic_default_name, ic_symbol, is_regulator
from .mapping import NC_PADS_KEY, UNUSED_PADS_OK, free_pads, standard_symbol_for, suggest_symbol, unused_pads_ok
from .models import IcPin, SymbolKindInfo, SymbolParamSpec, SymbolRequest, SymbolSuggestion
from .render import THEMES, render_parts, render_svg, render_thumbnail
from .standard import GENERATOR_VERSION, build_standard, kind_defs
from .style import StyleKit
from .util import check_name, check_prefix
from .validate import check_spec, spec_warnings

__all__ = [
    "NC_PADS_KEY",
    "THEMES",
    "UNUSED_PADS_OK",
    "IcPin",
    "SymbolError",
    "SymbolKindInfo",
    "SymbolParamSpec",
    "SymbolRequest",
    "SymbolSuggestion",
    "auto_assign_sides",
    "check_spec",
    "classify_pin",
    "example_request",
    "free_pads",
    "generate",
    "generated_name",
    "ic_symbol",
    "is_regulator",
    "kinds",
    "render_parts",
    "render_svg",
    "render_thumbnail",
    "spec_warnings",
    "standard_symbol_for",
    "suggest_symbol",
    "unused_pads_ok",
    "with_name_record",
]

IC_KIND = "ic"

_IC_PARAMS = [
    SymbolParamSpec(
        name="parts",
        label="Teile",
        kind="enum",
        default="1",
        options=["1", "auto", "2", "3", "4"],
        option_labels={
            "1": "Ein Teil (oder Teile wie in der Pinliste)",
            "auto": f"Automatisch teilen ab {MAX_PINS_PER_SIDE} Pins je Seite",
            "2": "2 Teile",
            "3": "3 Teile",
            "4": "4 Teile",
        },
        allow_custom=True,
        help="Große ICs in mehrere Teile aufteilen; Versorgungs- und Massepins kommen in eigene letzte Teile.",
    ),
    SymbolParamSpec(
        name="order",
        label="Sortierung in Gruppen",
        kind="enum",
        default="name",
        options=["name", "designator", "input"],
        option_labels={"name": "Nach Pinname (natürlich)", "designator": "Nach Pin-Nummer", "input": "Wie eingegeben"},
    ),
    SymbolParamSpec(
        name="max_pins_per_side",
        label="Max. Pins je Seite",
        kind="int",
        default=MAX_PINS_PER_SIDE,
        minimum=4,
        maximum=500,
        help="Grenze für die automatische Aufteilung in Teile.",
    ),
]


def _ic_info() -> SymbolKindInfo:
    return SymbolKindInfo(
        key=IC_KIND,
        label="IC (Pinliste)",
        group="ICs",
        default_name="IC",
        params=[p.model_copy(deep=True) for p in _IC_PARAMS],
        categories=["Integrated Circuits", "Power Linear", "Power Switchmode", "Data Converters", "Amplifiers"],
        description=(
            "Kastensymbol aus einer Pinliste: Versorgung links oben, Masse unten, Eingänge links, Ausgänge sowie "
            "FB/COMP/PG rechts, SW/BST oben; Gruppen mit Leerzeile getrennt; Pinlänge 200 mil, Pinabstand 100 mil."
        ),
        prefix="U",
    )


def kinds() -> list[SymbolKindInfo]:
    """All symbol kinds the generator offers (standard symbols plus ``ic``)."""
    return [d.info() for d in kind_defs()] + [_ic_info()]


def _whole_number(raw: Any) -> int | None:
    """``raw`` as an int when it is a whole number (``2``, ``2.0``, ``"2"``, ``"2,0"``), else ``None``."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    try:
        value = float(raw) if isinstance(raw, float) else float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return int(value) if value.is_integer() else None


def _parse_parts(raw: Any) -> int | str | None:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, str) and raw.strip().lower() == "auto":
        return "auto"
    value = _whole_number(raw)
    if value is None:
        raise SymbolError(f"IC: ungültige Teileangabe {raw!r} (Zahl oder 'auto').")
    return None if value == 1 else value


def _generate_ic(req: SymbolRequest, kit: StyleKit) -> SymbolSpec:
    allowed = {p.name for p in _IC_PARAMS}
    unknown = sorted(set(req.params) - allowed)
    if unknown:
        raise SymbolError(f"IC: unbekannte Parameter {', '.join(unknown)} (erlaubt: {', '.join(sorted(allowed))}).")
    parts = _parse_parts(req.params.get("parts"))
    order = str(req.params.get("order") or "name")
    raw_max = req.params.get("max_pins_per_side", MAX_PINS_PER_SIDE)
    max_side = _whole_number(MAX_PINS_PER_SIDE if raw_max is None else raw_max)
    if max_side is None:
        raise SymbolError(f"IC: 'Max. Pins je Seite' muss eine ganze Zahl sein, nicht {raw_max!r}.")
    if not req.pins:
        raise SymbolError("Für ein IC-Symbol werden Pins benötigt (Pinliste ist leer).")
    default_name = ic_default_name(len(req.pins))
    name = check_name(req.name or default_name)
    prefix = check_prefix(req.designator_prefix or "U")
    generator: dict[str, Any] = {
        "kind": IC_KIND,
        "version": GENERATOR_VERSION,
        "params": {"parts": parts, "order": order, "max_pins_per_side": max_side},
        "request": req.model_dump(mode="json", exclude_defaults=True),
        "style": kit.as_dict(),
        "default_name": default_name,
    }
    if name.casefold() != default_name.casefold():
        generator["name"] = name
    return build_ic(
        kit,
        name,
        req.pins,
        parts=parts,  # type: ignore[arg-type]
        description=req.description or "",
        designator_prefix=prefix,
        order=order,  # type: ignore[arg-type]
        max_pins_per_side=max_side,
        generator=generator,
    )


def generate(req: SymbolRequest, style: SymbolStyle | None = None) -> SymbolSpec:
    """Generate the symbol described by ``req`` in the house style.

    Standard kinds use ``req.params`` (see :func:`kinds`); ``kind="ic"`` uses ``req.pins``.
    """
    kit = StyleKit.from_style(style)
    if req.kind == IC_KIND:
        return _generate_ic(req, kit)
    return build_standard(req, kit)


# --------------------------------------------------------------------------- custom names


def _stored_style(raw: Any) -> SymbolStyle:
    """The workspace style with the generator-relevant values stored in ``generator["style"]``."""
    from .style import resolve_style

    base = resolve_style(None)
    if not isinstance(raw, dict):
        return base
    known = {k: v for k, v in raw.items() if k in SymbolStyle.model_fields}
    try:
        return base.model_copy(update=known)
    except (TypeError, ValueError):
        return base


def generated_name(spec: SymbolSpec) -> str | None:
    """The name the generator gives the request of ``spec`` without an explicit name
    (``generator["default_name"]``; older specs: generated again from ``generator["request"]``),
    ``None`` if unknown (no generator data or not reproducible)."""
    gen = spec.generator if isinstance(spec.generator, dict) else None
    if not gen:
        return None
    default = gen.get("default_name")
    if isinstance(default, str) and default:
        return default
    kind = gen.get("kind")
    request = gen.get("request")
    if not isinstance(kind, str) or not isinstance(request, dict):
        return None
    if kind == IC_KIND:
        pins = request.get("pins")
        return ic_default_name(len(pins)) if isinstance(pins, list) and pins else None
    try:
        req = SymbolRequest.model_validate({**request, "kind": kind, "name": None})
        return generate(req, _stored_style(gen.get("style"))).name
    except Exception:  # noqa: BLE001 - not reproducible: unknown
        return None


def with_name_record(spec: SymbolSpec) -> SymbolSpec:
    """``spec`` with ``generator["name"]`` (and ``generator["request"]["name"]``) = its name when
    that is a **custom** name (other than the name the generator gives its request, e.g.
    ``MY_OPAMP`` instead of ``Op-Amp``) and without ``generator["name"]`` otherwise – regenerating
    from ``generator["request"]`` then reproduces a custom name.

    Specs without generator data are returned unchanged; if the generated name cannot be
    determined, only a stale ``generator["name"]`` is corrected. Never raises."""
    gen = spec.generator if isinstance(spec.generator, dict) else None
    if not gen:
        return spec
    try:
        default = generated_name(spec)
    except Exception:  # noqa: BLE001 - defensive: a save must never fail here
        default = None
    updated = dict(gen)
    if default is None:
        custom = "name" in gen
    else:
        custom = spec.name.casefold() != default.casefold()
        updated.setdefault("default_name", default)
    if custom:
        updated["name"] = spec.name
    else:
        updated.pop("name", None)
    request = gen.get("request")
    if isinstance(request, dict) and (custom or "name" in request) and request.get("name") != spec.name:
        updated["request"] = {**request, "name": spec.name}
    return spec if updated == gen else spec.model_copy(update={"generator": updated})


_EXAMPLE_IC_PINS = (  # small buck regulator: VIN/EN left, FB/PG right, SW top, GND bottom
    ("1", "VIN", "power"),
    ("2", "GND", "power"),
    ("3", "EN", "input"),
    ("4", "FB", "input"),
    ("5", "SW", "output"),
    ("6", "PG", "open_collector"),
)


def example_request(kind: str) -> SymbolRequest:
    """A ready-to-generate request for ``kind`` (default parameters; sample pin list for ``ic``)."""
    if kind == IC_KIND:
        pins = [IcPin(designator=d, name=n, electrical=e) for d, n, e in _EXAMPLE_IC_PINS]  # type: ignore[arg-type]
        return SymbolRequest(kind=IC_KIND, name="IC Beispiel", pins=pins)
    return SymbolRequest(kind=kind)
