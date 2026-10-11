"""Normalisation and plausibility checks of Claude's answer.

:func:`normalize_extraction` merges the two answers (:class:`~.schema.AiIdentity` – devices, variants, pin
tables; :class:`~.schema.AiGeometry` – package drawings) into the normalised :class:`~.models.ExtractionData`:

* sentinel ``-1`` -> ``None``; other negative dimensions are reported,
* page numbers of the attached subset -> real datasheet pages,
* pin names: free-text hygiene (no ``|``/control characters, Unicode minus -> ``-``) and Altium overbar
  syntax for active-low pins (``R\\E\\S\\E\\T\\``), electrical types -> PartForge (``open_collector`` …),
  exposed pads recognised (by designator or, for rows that are no lead of the package, by name/description –
  "GND: connect to the thermal pad" stays a lead),
* enum answers compared case-insensitively (casing is not guaranteed), units other than mm converted,
* category guess -> a category table of the open library, parameter values normalised with the field
  definitions (``partforge.db.values.normalize_cell``),
* package family -> footprint family key (from the package name first, Claude's guess second),
* terminal arrangement of four-sided packages (counted from pin 1) -> :class:`~.models.TerminalLayout` in the
  generator's terms, only when it differs from the even distribution and fits the pin count.

:func:`validate_extraction` adds German :class:`~.models.Issue` entries; issues with ``vision=True`` trigger
the high-resolution verification pass (pin count vs. package, missing or inconsistent dimensions, …).
:func:`sanitize_extraction` applies the same text rules to an extraction the user edited.
"""
from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from ..db.models import CategoryDef, FieldDef
from ..db.values import normalize_cell
from ..domain.text import clean_free_text, latin1_text
from ..geometry.model import ElectricalType
from .models import (
    DeviceData,
    DimValue,
    ExtractionData,
    Issue,
    LandPatternData,
    PackageData,
    PackageOrigin,
    ParameterData,
    PinData,
    PinTableData,
    RowReference,
    TerminalLayout,
    VariantData,
)
from .pages import to_real_pages
from .schema import AiGeometry, AiIdentity, AiPackage, AiPackageRef, AiPin, AiTerminalLayout, family_keys

log = logging.getLogger(__name__)

__all__ = [
    "ELECTRICAL_TYPES",
    "GEOMETRY_ISSUES",
    "IDENTITY_ISSUES",
    "canonical_mounting",
    "canonical_pad_shape",
    "canonical_row_reference",
    "canonical_unit",
    "clean_pin_name",
    "merge_packages",
    "is_exposed_pad_pin",
    "map_electrical",
    "match_category",
    "normalize_extraction",
    "overbar_name",
    "resolve_family",
    "sanitize_extraction",
    "validate_extraction",
]

ELECTRICAL_TYPES: dict[str, ElectricalType] = {
    "input": "input", "io": "io", "output": "output", "opencollector": "open_collector", "passive": "passive",
    "hiz": "hiz", "openemitter": "open_emitter", "power": "power",
    # tolerated spellings
    "bidirectional": "io", "inout": "io", "i/o": "io", "opendrain": "open_collector", "open_drain": "open_collector",
    "tristate": "hiz", "highz": "hiz", "highimpedance": "hiz",
    "supply": "power", "ground": "power", "analog": "passive", "nc": "passive",
}
# issue codes a re-check of the identity pass (pin tables) or of the geometry pass (drawings) may resolve
IDENTITY_ISSUES = frozenset({"pin_count", "pin_duplicate", "no_pins", "no_device", "exposed_pad"})
GEOMETRY_ISSUES = frozenset({"dims_missing", "dim_order", "dim_negative", "inch_values", "lead_width", "span_body",
                             "land_pattern_incomplete", "land_pattern_overlap", "pitch_mismatch", "layout_missing"})
_QUAD_FAMILIES = frozenset({"nolead", "qfp"})  # footprint families with a terminal layout (QFN/QFP: four sides)
_MAX_NAME = 60
_MAX_FUNCTION = 200
_NC_NAMES = {"NC", "N/C", "N.C.", "N.C", "NO CONNECT", "NOCONNECT"}
# designators that mark the exposed pad as such (a plain number never does – see is_exposed_pad_pin)
_EP_DESIGNATOR = re.compile(r"^(?:EP|EPAD|E-PAD|PAD|TP|HS|DAP|POWERPAD|THERMAL ?PAD)\d{0,2}$")
_EP_NAMES = {"EP", "EPAD", "E-PAD", "PAD", "EXPOSED PAD", "EXPOSEDPAD", "THERMAL PAD", "THERMALPAD", "PGND PAD",
             "POWERPAD", "DAP", "PADDLE"}
_EP_TEXT = re.compile(r"exposed\s*(?:thermal\s*|die\s*|metal\s*|ground\s*)?pad|thermal\s*pad|die\s*attach\s*pad|"
                      r"power\s*pad|\bepad\b|paddle|heat\s*(?:sink|slug)", re.I)
_DASHES = str.maketrans({"−": "-", "–": "-", "—": "-", "‐": "-", "‑": "-", "＋": "+"})
_OVERBAR_MARKERS = re.compile(r"^[/~!]+|[#*]+$")

# --------------------------------------------------------------------------- small helpers


def _num(value: Any) -> float | None:
    """Sentinel-aware number: -1 (and NaN/inf) -> None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or abs(v + 1.0) < 1e-9:
        return None
    return round(v, 6)


def _text(value: Any, limit: int | None = None) -> str:
    return clean_free_text(str(value or "").translate(_DASHES), max_len=limit)


def _real_pages(values: Iterable[Any], selection: Sequence[int]) -> list[int]:
    return to_real_pages([v for v in values if isinstance(v, int) or str(v).strip().isdigit()], selection)


def _real_page(value: Any, selection: Sequence[int]) -> int | None:
    pages = _real_pages([value], selection) if value is not None else []
    return pages[0] if pages else None


def overbar_name(name: str, active_low: bool) -> str:
    """Pin name in Altium overbar syntax.

    Names that already carry backslashes are kept (Claude marks single overlined characters). An
    active-low name without backslashes gets an overbar over the whole name; datasheet markers such as a
    leading ``/``, ``~``, ``!`` or a trailing ``#``/``*`` are removed first.
    """
    text = name.strip()
    if "\\" in text:
        text = re.sub(r"\\{2,}", "\\\\", text)
        return text.lstrip("\\")
    if not active_low or not text:
        return text
    core = _OVERBAR_MARKERS.sub("", text).strip() or text
    return "".join(ch if ch == " " else ch + "\\" for ch in core)


def clean_pin_name(name: str) -> str:
    """Pin name for a SchLib: free-text hygiene, Latin-1, at most 60 characters."""
    text = latin1_text(str(name or "").translate(_DASHES))
    return text[:_MAX_NAME].strip()


def is_exposed_pad_pin(number: str, name: str, function: str, *, pin_count: int | None = None,
                       ep_number: str = "") -> bool:
    """Whether a pin-table row is the exposed (thermal) pad.

    Free text alone never turns a lead into the exposed pad – "GND: ground, connect the thermal pad to GND" is a
    lead. A row is the exposed pad when

    * its number is the package's exposed-pad number (``ep_number``) or an exposed-pad designator (EP, PAD, TP …),
    * or its number is no lead of the package (above ``pin_count``, ``0``, not numeric) and its name is an
      exposed-pad name or its name/description says so ("Exposed Pad (Pin 9): V-").

    With an unknown package size (``pin_count`` None) a numbered row counts as a lead unless it is named like an
    exposed pad.
    """
    num = (number or "").strip().upper()
    if ep_number and num == ep_number.strip().upper():
        return True
    if _EP_DESIGNATOR.match(num):
        return True
    numeric = num.isdigit()
    if numeric and pin_count is not None and 1 <= int(num) <= pin_count:
        return False  # a lead of the package
    if (name or "").strip().upper().replace("\\", "") in _EP_NAMES:
        return True
    if numeric and int(num) >= 1 and pin_count is None:
        return False
    return bool(_EP_TEXT.search(function or "")) or bool(_EP_TEXT.search(name or ""))


def map_electrical(value: str) -> ElectricalType:
    """PartForge electrical type for Claude's Altium type (case-insensitive, tolerant; unknown -> passive)."""
    key = re.sub(r"[\s_-]+", "", str(value or "")).lower()
    return ELECTRICAL_TYPES.get(key, "passive")


# --------------------------------------------------------------------------- enum answers (case-insensitive)


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


_ANGLE_UNITS = {"deg", "degree", "degrees", "°", "grad", "degr"}
_LENGTH_UNITS: dict[str, float] = {
    "mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "millimetre": 1.0, "millimetres": 1.0, "": 1.0,
    "cm": 10.0, "um": 0.001, "micron": 0.001, "microns": 0.001, "micrometer": 0.001, "micrometre": 0.001,
    "in": 25.4, "inch": 25.4, "inches": 25.4, '"': 25.4, "mil": 0.0254, "mils": 0.0254, "thou": 0.0254,
}


def canonical_unit(value: Any) -> tuple[Literal["mm", "deg"], float] | None:
    """``(unit, factor to mm)`` for Claude's unit string (``("deg", 1)`` for angles); ``None`` if unknown."""
    text = str(value or "").strip().lower().replace("µ", "u").replace("μ", "u").rstrip(".")
    if text in _ANGLE_UNITS or text.startswith("deg"):
        return "deg", 1.0
    factor = _LENGTH_UNITS.get(text)
    return ("mm", factor) if factor is not None else None


_ROW_REFERENCE_KEYS: dict[str, RowReference] = {
    "centertocenter": "center_to_center", "centretocentre": "center_to_center", "center": "center_to_center",
    "centre": "center_to_center", "cc": "center_to_center", "padcentertopadcenter": "center_to_center",
    "inneredges": "inner_edges", "inneredge": "inner_edges", "inner": "inner_edges", "gap": "inner_edges",
    "outeredges": "outer_edges", "outeredge": "outer_edges", "outer": "outer_edges",
    "padcentertocomponentcenter": "pad_center_to_component_center",
    "padcentretocomponentcentre": "pad_center_to_component_center",
    "componentcentertopadcenter": "pad_center_to_component_center",
    "componentcentretopadcentre": "pad_center_to_component_center", "half": "pad_center_to_component_center",
    "notapplicable": "not_applicable", "na": "not_applicable", "none": "not_applicable",
    "unclear": "unclear", "unknown": "unclear",
}


def canonical_row_reference(value: Any) -> RowReference:
    """Row-spacing reference of a land pattern (unknown -> ``unclear``)."""
    return _ROW_REFERENCE_KEYS.get(_key(value), "unclear")


_PAD_SHAPE_KEYS = {
    "rectangle": "rectangle", "rectangular": "rectangle", "rect": "rectangle",
    "roundedrectangle": "rounded_rectangle", "roundrect": "rounded_rectangle", "roundedrect": "rounded_rectangle",
    "oval": "oval", "obround": "oval", "oblong": "oval", "circle": "circle", "round": "circle",
    "circular": "circle", "other": "other", "unknown": "unknown", "": "unknown",
}


def canonical_pad_shape(value: Any) -> str:
    """Pad shape of a land pattern (unknown spellings -> ``other``)."""
    return _PAD_SHAPE_KEYS.get(_key(value), "other")


def canonical_mounting(value: Any) -> Literal["SMD", "THT"] | None:
    key = _key(value)
    if key in ("smd", "smt", "surfacemount", "surfacemounted", "surfacemountdevice"):
        return "SMD"
    if key in ("tht", "throughhole", "thruhole", "pth", "throughholetechnology"):
        return "THT"
    return None


# --------------------------------------------------------------------------- categories and parameters

_CATEGORY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"op(?:erational)?[\s-]*amp|amplifier|comparator|verstärker|komparator", re.I), "Amplifiers"),
    (re.compile(r"\badc\b|\bdac\b|converter|potentiometer|digipot|analog[\s-]*to|digital[\s-]*to|wandler", re.I),
     "Data Converters"),
    (re.compile(r"ldo|linear\s+regulator|voltage\s+reference|shunt\s+regulator|linearregler", re.I), "Power Linear"),
    (re.compile(r"buck|boost|switching|dc[\s/-]*dc|pmic|charge\s+pump|gate\s+driver|schaltregler", re.I),
     "Power Switchmode"),
    (re.compile(r"opto|photocoupler|isolator", re.I), "Optocouplers"),
    (re.compile(r"mosfet|\bfet\b|jfet", re.I), "Transistors FET"),
    (re.compile(r"transistor|\bbjt\b", re.I), "Transistors BJT"),
    (re.compile(r"\bled\b", re.I), "LEDs"),
    (re.compile(r"diode|rectifier|tvs|zener|schottky", re.I), "Diodes"),
    (re.compile(r"resistor|widerstand", re.I), "Resistors"),
    (re.compile(r"capacitor|mlcc|kondensator", re.I), "Capacitors"),
    (re.compile(r"ferrite|bead", re.I), "Ferrite Beads"),
    (re.compile(r"inductor|choke|induktivit", re.I), "Inductors"),
    (re.compile(r"crystal|oscillator|resonator|quarz", re.I), "Oscillators"),
    (re.compile(r"connector|header|socket|steckverbinder", re.I), "Connectors"),
    (re.compile(r"fuse|ptc|varistor|sicherung", re.I), "Fuses"),
    (re.compile(r"relay|switch|button|buzzer|relais|schalter", re.I), "Electromechanical"),
)


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def match_category(raw: str, categories: Sequence[CategoryDef], *, context: str = "") -> CategoryDef | None:
    """The workspace category for Claude's answer (table name or label; keyword fallback on raw + context)."""
    if not categories:
        return None
    wanted = _fold(raw or "")
    if wanted:
        for cat in categories:
            if wanted in (_fold(cat.table), _fold(cat.label)):
                return cat
        for cat in categories:
            if wanted and (wanted in _fold(cat.table) or _fold(cat.table) in wanted):
                return cat
    by_table = {c.table.casefold(): c for c in categories}
    for text in (raw, context):
        for pattern, table in _CATEGORY_HINTS:
            if text and pattern.search(text) and table.casefold() in by_table:
                return by_table[table.casefold()]
    return by_table.get("integrated circuits")


def _field_for(category: CategoryDef, column: str) -> FieldDef | None:
    wanted = _fold(column)
    if not wanted:
        return None
    for f in category.fields:
        if _fold(f.column) == wanted or _fold(f.label) == wanted:
            return f
    return None


def normalize_parameters(raw: Iterable[Any], category: CategoryDef | None, selection: Sequence[int],
                         ws_root: Any = None) -> list[ParameterData]:
    """Normalise Claude's parameter list for the fields of ``category`` (unknown fields are dropped).

    Values are printed in the datasheet, i.e. in English number format: a comma group such as „2,000 pF“ or „32,768 Hz“
    is a thousands separator (``normalize_cell(thousands=True)``, never the German decimal comma of a manual entry);
    such a reading is kept as a hint in ``ParameterData.warning`` (and logged), so the review shows it."""
    if category is None:
        return []
    out: list[ParameterData] = []
    seen: set[str] = set()
    for item in raw:
        column = str(getattr(item, "column", "") or "")
        value = _text(getattr(item, "value", ""), 255)
        f = _field_for(category, column)
        if f is None or not value or f.system or f.column in seen:
            continue
        if f.column in ("Part Number", "Manufacturer Part Number", "Manufacturer", "Description", "Comment", "Value"):
            continue  # filled by PartForge
        cell = normalize_cell(f, value, ws_root=ws_root, thousands=True)
        if cell.error or not cell.value:
            continue
        seen.add(f.column)
        hint = " ".join(t for t in (cell.warning, cell.note) if t) or None
        out.append(ParameterData(column=f.column, value=cell.value, raw=value,
                                 page=_real_page(getattr(item, "page", None), selection), warning=hint))
    return out


# --------------------------------------------------------------------------- packages


def resolve_family(name: str, code: str, claude_family: str) -> str | None:
    """Footprint family key: from the package name (same interpretation as the footprint generator), else
    from the code, else Claude's family guess."""
    from ..footprints.packages import resolve_package

    for candidate in (name, code):
        if not candidate or not candidate.strip():
            continue
        try:
            key, _ = resolve_package(candidate)
            return key
        except ValueError:
            continue
    keys = set(family_keys()) - {"other"}
    guess = (claude_family or "").strip().lower()
    return guess if guess in keys else None


def _scaled(value: float | None, factor: float) -> float | None:
    return round(value * factor, 6) if value is not None and factor != 1.0 else value


_BODY_AXIS = re.compile(r"H?([DE])\d?")  # D, D1, HD -> D (left/right sides of the generator), E… -> E (top/bottom)


def _layout(raw: AiTerminalLayout, dims: Sequence[DimValue], pin_count: int | None, label: str,
            notes: list[str] | None) -> TerminalLayout | None:
    """Claude's terminal arrangement (counted from pin 1) in the generator's terms (:class:`~.models.TerminalLayout`:
    ``pins_y`` on the left/right sides along D, ``pins_x`` on the top/bottom sides along E). None for packages with
    terminals on fewer than four sides, for an evenly distributed one and for an arrangement that contradicts the
    pin count or the body dimensions (noted)."""
    first, other = raw.pin1_side_positions, raw.adjacent_side_positions
    if not 1 <= first <= _MAX_SIDE or not 1 <= other <= _MAX_SIDE:
        return None
    top = bool(raw.pin1_last_on_side)  # pin 1 at the left end of the top side (TI RGY), else top of the left side
    missing = sorted({n for n in raw.missing_positions if 1 <= n <= 2 * (first + other)})
    if pin_count is not None and 2 * (first + other) != pin_count + len(missing):
        if notes is not None:
            notes.append(f"{label}: Anschlussanordnung ({first} und {other} Positionen je Seite) passt nicht zu "
                         f"{pin_count} Anschlüssen – nicht übernommen.")
        return None
    axis = _BODY_AXIS.fullmatch(_text(raw.pin1_side_dimension, 12).upper())
    if axis is not None and axis.group(1) != ("E" if top else "D"):
        if notes is not None:
            notes.append(f"{label}: Anschlussanordnung nicht übernommen – laut Zeichnung misst "
                         f"{_text(raw.pin1_side_dimension, 12)} die Seite mit Pin 1, der Footprint-Generator erwartet "
                         f"dort {'E' if top else 'D'}. Bitte Körpermaße und Anordnung prüfen.")
        return None
    pitch = next((d.value() for d in dims if d.symbol == "e" and d.unit == "mm" and d.value()), None)
    rows_x = _positive(_num(raw.pin1_side_pitch if top else raw.adjacent_side_pitch), 10.0)
    rows_y = _positive(_num(raw.adjacent_side_pitch if top else raw.pin1_side_pitch), 10.0)
    if rows_y is not None and pitch is not None and abs(rows_y - pitch) > 0.005 and notes is not None:
        notes.append(f"{label}: Raster der Anschlüsse auf der Seite mit {other if top else first} Positionen "
                     f"({rows_y:g} mm) weicht vom Raster e ({pitch:g} mm) ab – bitte prüfen.")
    layout = TerminalLayout(pins_x=first if top else other, pins_y=other if top else first,
                            pitch_x=rows_x if rows_x is not None and (pitch is None or abs(rows_x - pitch) > 0.005)
                            else None, pin1="top" if top else "left", missing=missing)
    if layout.pins_x == layout.pins_y and layout.pitch_x is None and layout.pin1 == "left" and not layout.missing:
        return None  # evenly distributed: what the generator does anyway
    return layout


def _package(pkg: AiPackage, selection: Sequence[int], used: set[str], notes: list[str] | None = None) -> PackageData:
    name = _text(pkg.package_name, 80)
    code = _text(pkg.package_code, 40) or name or "PKG"
    unique = _unique(code, used)
    dims = []
    for d in pkg.dimensions:
        symbol = _text(d.symbol, 12)
        unit = canonical_unit(d.unit)
        if unit is None:
            if notes is not None:
                notes.append(f"{name or code}: Maß {symbol or _text(d.description, 40)} mit unbekannter Einheit "
                             f"„{_text(d.unit, 12)}“ ignoriert.")
            continue
        kind, factor = unit
        dims.append(DimValue(symbol=symbol, description=_text(d.description, 120), unit=kind,
                             min=_scaled(_num(d.min), factor), nom=_scaled(_num(d.nom), factor),
                             max=_scaled(_num(d.max), factor)))
    lp = pkg.land_pattern
    land = LandPatternData(
        present=bool(lp.present), pages=_real_pages(lp.source_pages, selection),
        pad_shape=canonical_pad_shape(lp.pad_shape), pad_width=_num(lp.pad_width), pad_length=_num(lp.pad_length),
        pitch=_num(lp.pitch), row_spacing=_num(lp.row_spacing),
        row_spacing_reference=canonical_row_reference(lp.row_spacing_reference),
        thermal_pad_width=_num(lp.thermal_pad_width), thermal_pad_length=_num(lp.thermal_pad_length),
        solder_mask_expansion=_num(lp.solder_mask_expansion), notes=_text(lp.notes, 300),
    )
    pin_count = int(pkg.pin_count) if isinstance(pkg.pin_count, int) and pkg.pin_count > 0 else None
    family = resolve_family(name, code, pkg.family)
    layout = _layout(pkg.terminal_layout, dims, pin_count, name or code, notes) if family in _QUAD_FAMILIES else None
    return PackageData(
        code=unique, name=name, family=family, family_raw=_text(pkg.family, 40),
        pin_count=pin_count, mounting=canonical_mounting(pkg.mounting),
        outline_reference=_text(pkg.outline_reference, 60), exposed_pad=bool(pkg.exposed_pad),
        exposed_pad_number=_text(pkg.exposed_pad_number, 10).replace(" ", ""),
        pages=_real_pages(pkg.source_pages, selection), dimensions=dims, land_pattern=land, layout=layout,
    )


def _package_code(raw: str, packages: Sequence[PackageData]) -> str:
    wanted = (raw or "").strip().casefold()
    if not wanted:
        return packages[0].code if len(packages) == 1 else ""
    for pkg in packages:
        if wanted == pkg.code.casefold() or wanted == pkg.name.casefold():
            return pkg.code
    folded = _fold(raw)
    for pkg in packages:
        if folded and (folded == _fold(pkg.code) or folded == _fold(pkg.name)):
            return pkg.code
    return _text(raw, 40)


# --------------------------------------------------------------------------- pins


def _pin(pin: AiPin, package: PackageData | None) -> PinData:
    number = _text(pin.number, 12).replace(" ", "") or "?"
    raw_name = clean_pin_name(pin.name)
    function = _text(pin.function, _MAX_FUNCTION)
    active_low = bool(pin.active_low) or "\\" in raw_name
    name = overbar_name(raw_name, active_low)
    upper = name.replace("\\", "").upper()
    no_connect = bool(pin.no_connect) or upper in _NC_NAMES
    ep = is_exposed_pad_pin(number, name, function, pin_count=package.pin_count if package is not None else None,
                            ep_number=package.exposed_pad_number if package is not None else "")
    electrical = map_electrical(pin.electrical_type)
    if no_connect:
        electrical = "passive"
    part = pin.part if isinstance(pin.part, int) and 0 <= pin.part <= 64 else 1
    return PinData(number=number, name=name or number, function=function, electrical=electrical,
                   active_low=active_low, no_connect=no_connect, exposed_pad=ep, group=_text(pin.group, 40), part=part)


# --------------------------------------------------------------------------- main entry


def _unique(code: str, used: set[str]) -> str:
    unique, n = code, 2
    while unique.casefold() in used:
        unique, n = f"{code}-{n}", n + 1
    used.add(unique.casefold())
    return unique


def _find_geometry(code: str, name: str, pin_count: int, candidates: Sequence[PackageData]) -> PackageData | None:
    """The geometry entry for a package of the identity pass (code, then name, then a unique pin count)."""
    for pkg in candidates:
        if code and pkg.code.casefold() == code.casefold():
            return pkg
    folded_code, folded_name = _fold(code), _fold(name)
    for pkg in candidates:
        if folded_name and folded_name in (_fold(pkg.name), _fold(pkg.code)):
            return pkg
        if folded_code and folded_code in (_fold(pkg.name), _fold(pkg.code)):
            return pkg
    same_count = [p for p in candidates if pin_count > 0 and p.pin_count == pin_count]
    return same_count[0] if len(same_count) == 1 else None


def merge_packages(refs: Sequence[AiPackageRef], geometry: Sequence[PackageData]) -> tuple[list[PackageData], list[str]]:
    """Packages of the identity pass (codes used by variants and pin tables) completed with the geometry pass."""
    remaining = list(geometry)
    used: set[str] = set()
    out: list[PackageData] = []
    notes: list[str] = []
    for ref in refs:
        name = _text(ref.package_name, 80)
        code = _text(ref.package_code, 40) or name or "PKG"
        pin_count = int(ref.pin_count) if isinstance(ref.pin_count, int) and ref.pin_count > 0 else 0
        match = _find_geometry(code, name, pin_count, remaining)
        if match is not None:
            remaining.remove(match)
            if pin_count and match.pin_count and match.pin_count != pin_count:
                notes.append(f"{code}: Anschlusszahl laut Pintabelle {pin_count}, laut Gehäusezeichnung "
                             f"{match.pin_count}.")
            pkg = match.model_copy(update={
                "code": _unique(code, used), "name": match.name or name, "pin_count": pin_count or match.pin_count,
                "exposed_pad": match.exposed_pad or bool(ref.exposed_pad),
            })
        else:
            pkg = PackageData(code=_unique(code, used), name=name, family=resolve_family(name, code, ""),
                              pin_count=pin_count or None, exposed_pad=bool(ref.exposed_pad))
        out.append(pkg)
    for extra in remaining:  # drawn, but not referenced by the identity pass
        out.append(extra.model_copy(update={"code": _unique(extra.code, used)}))
    return out, notes


def normalize_extraction(
    identity: AiIdentity,
    geometry: AiGeometry | None = None,
    *,
    pages: Sequence[int],
    geometry_pages: Sequence[int] | None = None,
    categories: Sequence[CategoryDef] = (),
    ws_root: Any = None,
) -> ExtractionData:
    """Normalise and merge the two answers; ``pages``/``geometry_pages`` = real page numbers of the attached
    subsets of the identity and the geometry pass (in order)."""
    geo_pages = list(geometry_pages if geometry_pages is not None else pages)
    geo_used: set[str] = set()
    unit_notes: list[str] = []
    drawn = [_package(p, geo_pages, geo_used, unit_notes) for p in (geometry.packages if geometry is not None else [])]
    packages, notes = merge_packages(identity.packages, drawn)
    notes = [*unit_notes, *notes]
    by_code = {p.code: p for p in packages}
    devices: list[DeviceData] = []
    seen_parts: set[str] = set()
    for dev in identity.devices:
        base = _text(dev.base_part_number, 64)
        if not base or base.casefold() in seen_parts:
            base = base or f"Bauteil {len(devices) + 1}"
            if base.casefold() in seen_parts:
                base = f"{base} ({len(devices) + 1})"
        seen_parts.add(base.casefold())
        description = _text(dev.description, 120)
        category = match_category(dev.category, categories, context=f"{description} {base}")
        variants: list[VariantData] = []
        mpns: set[str] = set()
        for v in dev.variants:
            mpn = _text(v.mpn, 64).strip()
            if not mpn or mpn.casefold() in mpns:
                continue
            mpns.add(mpn.casefold())
            variants.append(VariantData(
                mpn=mpn, package=_package_code(v.package_code, packages),
                temperature_range=_text(v.temperature_range, 60), packaging=_text(v.packaging, 120),
                status=_text(v.status, 30), notes=_text(v.notes, 200),
                values=normalize_parameters(v.values, category, pages, ws_root=ws_root),
                pages=[p for p in [_real_page(v.page, pages)] if p is not None],
            ))
        tables: list[PinTableData] = []
        for table in dev.pin_tables:
            code = _package_code(table.package_code, packages)
            package = by_code.get(code)
            existing = next((t for t in tables if t.package == code), None)
            pins = [_pin(p, package) for p in table.pins]
            if existing is not None:  # the same package twice: keep the longer table
                if len(pins) > len(existing.pins):
                    existing.pins, existing.pages = pins, _real_pages(table.source_pages, pages)
                continue
            tables.append(PinTableData(package=code, pages=_real_pages(table.source_pages, pages), pins=pins))
        devices.append(DeviceData(
            base_part=base, description=description, category=category.table if category else None,
            category_raw=_text(dev.category, 80),
            parameters=normalize_parameters(dev.parameters, category, pages, ws_root=ws_root),
            variants=variants, pin_tables=tables,
        ))
    warnings = [w for w in (_text(x, 400) for x in identity.warnings) if w]
    if geometry is not None:
        warnings += [w for w in (_text(x, 400) for x in geometry.warnings) if w and w not in warnings]
    data = ExtractionData(
        manufacturer=_text(identity.manufacturer, 80), document_id=_text(identity.document_id, 60),
        title=_text(identity.document_title, 200), date=_text(identity.document_date, 40), devices=devices,
        packages=packages, warnings=warnings + notes,
    )
    data.issues = validate_extraction(data)
    return data


# --------------------------------------------------------------------------- validation

_KEY_DIMS: dict[str, list[tuple[str, ...]]] = {
    "gullwing": [("e", "e1"), ("b", "bp"), ("L", "Lp"), ("D",), ("E", "HE")],
    "sot23": [("e", "e1"), ("b", "bp"), ("L", "Lp"), ("D",), ("E", "HE")],
    "sc70": [("e", "e1"), ("b", "bp"), ("L", "Lp"), ("D",), ("E", "HE")],
    "sot523": [("e", "e1"), ("b", "bp"), ("L", "Lp"), ("D",), ("E", "HE")],
    "qfp": [("e",), ("b", "bp"), ("L", "Lp"), ("D", "HD"), ("E", "HE")],
    "nolead": [("e",), ("b",), ("L",), ("D", "E")],
    "bga": [("e",), ("b",), ("D", "E")],
    "chip": [("L",), ("W",)],
    "dip": [("e",), ("b",), ("D",)],
}
_INCH_PITCHES = (0.05, 0.0256, 0.0197, 0.1, 0.0394, 0.0315)


def _issue(issues: list[Issue], severity: str, code: str, message: str, *, device: str | None = None,
           package: str | None = None, vision: bool = False) -> None:
    issues.append(Issue(severity=severity, code=code, message=message, device=device, package=package,  # type: ignore[arg-type]
                        vision=vision))


def _check_dims(pkg: PackageData, issues: list[Issue]) -> None:
    label = pkg.label
    for d in pkg.dimensions:
        values = [v for v in (d.min, d.nom, d.max) if v is not None]
        if any(v < 0 for v in values):
            _issue(issues, "error", "dim_negative", f"{label}: Maß {d.symbol or d.description} hat einen negativen Wert.",
                   package=pkg.code, vision=True)
            continue
        lo, mid, hi = d.min, d.nom, d.max
        if (lo is not None and hi is not None and lo > hi + 1e-9) or \
                (mid is not None and ((lo is not None and mid < lo - 1e-9) or (hi is not None and mid > hi + 1e-9))):
            _issue(issues, "error", "dim_order",
                   f"{label}: Maß {d.symbol or d.description} ist widersprüchlich (min {lo}, nom {mid}, max {hi}).",
                   package=pkg.code, vision=True)
    groups = _KEY_DIMS.get(pkg.family or "")
    mm_dims = [d for d in pkg.dimensions if d.unit == "mm" and d.value() is not None]
    if groups:
        missing = [groups_[0] for groups_ in groups if pkg.dim(*groups_) is None]
        if pkg.family == "nolead" and pkg.exposed_pad and pkg.dim("D2", "E2", "EP") is None:
            missing.append("D2/E2 (Exposed Pad)")
        if missing:
            _issue(issues, "warning", "dims_missing", f"{label}: Gehäusemaße fehlen: {', '.join(missing)}.",
                   package=pkg.code, vision=True)
    elif len(mm_dims) < 2:
        _issue(issues, "warning", "dims_missing", f"{label}: Keine verwertbaren Gehäusemaße gefunden.",
               package=pkg.code, vision=True)
    pitch = pkg.dim("e", "e1")
    body = pkg.dim("D", "E", "E1")
    if pitch is not None and body is not None:
        pv, bv = pitch.value() or 0, body.value() or 0
        if any(abs(pv - x) < 1e-4 for x in _INCH_PITCHES) and bv < 0.5:
            _issue(issues, "error", "inch_values",
                   f"{label}: Die Maße sehen nach Zoll statt Millimetern aus (Raster {pv}, Körper {bv}).",
                   package=pkg.code, vision=True)
    lead = pkg.dim("b", "bp")
    if pitch is not None and lead is not None and (lead.value() or 0) >= (pitch.value() or 0) > 0 and pkg.family != "bga":
        _issue(issues, "error", "lead_width",
               f"{label}: Anschlussbreite b ({lead.value()}) ist nicht kleiner als das Raster e ({pitch.value()}).",
               package=pkg.code, vision=True)
    span, width = pkg.dim("E", "HE"), pkg.dim("E1")
    if pkg.family in ("gullwing", "sot23", "sc70") and span is not None and width is not None \
            and (width.value() or 0) >= (span.value() or 0):
        _issue(issues, "warning", "span_body",
               f"{label}: Körperbreite E1 ({width.value()}) ist nicht kleiner als die Anschlussspanne E ({span.value()}).",
               package=pkg.code, vision=True)
    height, standoff = pkg.dim("A"), pkg.dim("A1")
    if height is not None and standoff is not None and (standoff.value() or 0) >= (height.value() or 0) > 0:
        _issue(issues, "warning", "height",
               f"{label}: Abstand A1 ({standoff.value()}) ist nicht kleiner als die Bauhöhe A ({height.value()}).",
               package=pkg.code)
    lp = pkg.land_pattern
    if lp.present:
        if not lp.complete():
            _issue(issues, "warning", "land_pattern_incomplete",
                   f"{label}: Herstellerempfehlung (Land Pattern) unvollständig – IPC-7351B-Berechnung wird verwendet.",
                   package=pkg.code, vision=True)
        if lp.pitch is not None and pitch is not None and abs(lp.pitch - (pitch.value() or 0)) > 0.011:
            _issue(issues, "warning", "pitch_mismatch",
                   f"{label}: Raster der Herstellerempfehlung ({lp.pitch} mm) passt nicht zum Gehäuseraster "
                   f"({pitch.value()} mm).", package=pkg.code, vision=True)
        if lp.row_spacing_reference == "unclear" and lp.row_spacing is not None:
            _issue(issues, "info", "row_reference",
                   f"{label}: Bezug des Reihenabstands der Herstellerempfehlung unklar – Mitte-zu-Mitte angenommen.",
                   package=pkg.code)
        elif lp.row_spacing_reference == "pad_center_to_component_center" and lp.row_spacing is not None:
            _issue(issues, "info", "row_reference_half",
                   f"{label}: Reihenabstand der Herstellerempfehlung ist Mitte Bauteil bis Mitte Pad – Abstand der "
                   f"Padmitten {2 * lp.row_spacing:g} mm.", package=pkg.code)
        center = lp.center_distance()
        if center is not None and lp.pad_length is not None and center < lp.pad_length - 1e-6:
            _issue(issues, "warning", "land_pattern_overlap",
                   f"{label}: Herstellerempfehlung unplausibel – der Abstand der Padmitten ({center:g} mm) ist kleiner "
                   f"als die Padlänge ({lp.pad_length:g} mm), die Pads würden sich überlappen. Vermutlich ist ein "
                   "halber Abstand (Mitte Bauteil bis Mitte Pad) oder ein anderer Bezug gemeint.",
                   package=pkg.code, vision=True)


def _four_sided(pkg: PackageData) -> bool:
    """Whether the footprint generator places the terminals on four sides (QFP; QFN, its default no-lead variant)."""
    from ..footprints.packages import resolve_package

    if pkg.family != "nolead":
        return pkg.family == "qfp"
    try:
        key, implied = resolve_package(pkg.name)  # the generator is chosen by the name first (proposal)
    except ValueError:
        return True
    return key == "qfp" or (key == "nolead" and implied.get("variant", "QFN") == "QFN")


def _check_layout(pkg: PackageData, issues: list[Issue]) -> None:
    if pkg.layout is not None or not pkg.pin_count or pkg.pin_count % 4 == 0 or not _four_sided(pkg):
        return
    _issue(issues, "warning", "layout_missing",
           f"{pkg.label}: {pkg.pin_count} Anschlüsse lassen sich nicht gleichmäßig auf vier Seiten verteilen – "
           "bitte die Anschlussanordnung (Anschlüsse je Seite) angeben.", package=pkg.code, vision=True)


def _check_pins(dev: DeviceData, table: PinTableData, pkg: PackageData | None, issues: list[Issue]) -> None:
    label = pkg.label if pkg is not None else table.package
    numbers: dict[str, int] = {}
    for pin in table.pins:
        numbers[pin.number.casefold()] = numbers.get(pin.number.casefold(), 0) + 1
    dupes = sorted(n for n, count in numbers.items() if count > 1)
    if dupes:
        _issue(issues, "error", "pin_duplicate",
               f"{dev.base_part} / {label}: Pin-Nummern doppelt: {', '.join(dupes)}.", device=dev.base_part,
               package=table.package, vision=True)
    if pkg is None:
        _issue(issues, "warning", "pin_table_package",
               f"{dev.base_part}: Pintabelle für unbekanntes Gehäuse „{table.package}“.", device=dev.base_part,
               package=table.package)
        return
    leads = [p for p in table.pins if not p.exposed_pad]
    if pkg.pin_count is not None and len(leads) != pkg.pin_count:
        _issue(issues, "error", "pin_count",
               f"{dev.base_part} / {label}: {len(leads)} Pins in der Pintabelle, das Gehäuse hat {pkg.pin_count} "
               "Anschlüsse.", device=dev.base_part, package=pkg.code, vision=True)
    has_ep_pin = any(p.exposed_pad for p in table.pins)
    if has_ep_pin and not pkg.exposed_pad:
        _issue(issues, "warning", "exposed_pad",
               f"{dev.base_part} / {label}: Pintabelle enthält ein Exposed Pad, das Gehäuse aber keines.",
               device=dev.base_part, package=pkg.code, vision=True)
    elif pkg.exposed_pad and not has_ep_pin:
        _issue(issues, "info", "exposed_pad_pin",
               f"{dev.base_part} / {label}: Das Exposed Pad hat keine Pin-Nummer im Datenblatt – es erhält den "
               "Bezeichner des Footprints (Hausstil).", device=dev.base_part, package=pkg.code)


def validate_extraction(data: ExtractionData) -> list[Issue]:
    """Plausibility checks (German messages); see the module docstring."""
    issues: list[Issue] = []
    if not data.devices and any(p.has_geometry() for p in data.packages):
        # a package-outline document (e.g. TI's separate package drawings): nothing to correct – never ask Claude to
        # "find" a device there (it would invent one)
        _issue(issues, "info", "package_only",
               "Nur Gehäusezeichnung, kein Bauteil: Footprint speichern oder das Gehäuse in das Datenblatt des "
               "Bauteils übernehmen.")
    elif not data.devices:
        _issue(issues, "error", "no_device", "Im Datenblatt wurde kein Bauteil erkannt.", vision=True)
    codes = {p.code for p in data.packages}
    for dev in data.devices:
        if dev.category is None:
            _issue(issues, "warning", "category", f"{dev.base_part}: Kategorie nicht erkannt – bitte auswählen.",
                   device=dev.base_part)
        if not dev.variants:
            _issue(issues, "warning", "no_variants",
                   f"{dev.base_part}: Keine Bestellnummern gefunden – bitte die Hersteller-Teilenummer ergänzen.",
                   device=dev.base_part)
        for v in dev.variants:
            if v.package and v.package not in codes:
                _issue(issues, "warning", "variant_package",
                       f"{v.mpn}: Gehäuse „{v.package}“ ist nicht beschrieben.", device=dev.base_part)
        if not dev.pin_tables:
            _issue(issues, "warning", "no_pins", f"{dev.base_part}: Keine Pintabelle gefunden.", device=dev.base_part,
                   vision=True)
        for table in dev.pin_tables:
            _check_pins(dev, table, next((p for p in data.packages if p.code == table.package), None), issues)
    for pkg in data.packages:
        if pkg.family is None:
            _issue(issues, "warning", "unknown_family",
                   f"{pkg.label}: Gehäuse keiner Footprint-Familie zugeordnet – bitte Familie wählen oder einen "
                   "vorhandenen Footprint verwenden.", package=pkg.code)
        _check_dims(pkg, issues)
        _check_layout(pkg, issues)
    return issues


# --------------------------------------------------------------------------- user edits


def _sanitize_parameters(params: Iterable[ParameterData], category: CategoryDef | None,
                         ws_root: Any) -> list[ParameterData]:
    """Parameters of a user-edited extraction: text hygiene; values of known fields normalised (an invalid value
    is kept as typed, with the reason as ``warning``)."""
    out: list[ParameterData] = []
    seen: set[str] = set()
    for p in params:
        column, value = _text(p.column, 64), _text(p.value, 255)
        if not column or not value:
            continue
        field = _field_for(category, column) if category is not None else None
        if field is None:
            if column.casefold() not in seen:
                seen.add(column.casefold())
                out.append(ParameterData(column=column, value=value, raw=_text(p.raw, 255), page=p.page,
                                         warning=_text(p.warning, 200) or None))
            continue
        if field.column.casefold() in seen:
            continue
        seen.add(field.column.casefold())
        cell = normalize_cell(field, value, ws_root=ws_root)
        out.append(ParameterData(column=field.column, value=(cell.value or value) if not cell.error else value,
                                 raw=_text(p.raw, 255) or value, page=p.page, warning=cell.error or cell.warning))
    return out


_MAX_SIDE = 100  # positions per side (footprint generator: pins_x/pins_y)
_MAX_POSITION = 4 * _MAX_SIDE


def _positive(value: float | None, limit: float = 100.0) -> float | None:
    """A positive, finite length up to ``limit`` mm – anything else is "not given"."""
    if value is None or isinstance(value, bool) or not math.isfinite(value) or not 0 < value <= limit:
        return None
    return value


def _sanitize_layout(layout: TerminalLayout | None) -> TerminalLayout | None:
    """A terminal layout with plausible values only (None when nothing is left): positions per side 1–100, the pitch of
    the top/bottom rows positive, missing positions unique and sorted."""
    if layout is None:
        return None
    pins_x = layout.pins_x if layout.pins_x is not None and 1 <= layout.pins_x <= _MAX_SIDE else None
    pins_y = layout.pins_y if layout.pins_y is not None and 1 <= layout.pins_y <= _MAX_SIDE else None
    missing = sorted({n for n in layout.missing if 1 <= n <= _MAX_POSITION})
    clean = TerminalLayout(pins_x=pins_x, pins_y=pins_y, pitch_x=_positive(layout.pitch_x, 10.0), pin1=layout.pin1,
                           missing=missing)
    return None if clean.is_default() else clean


def _sanitize_origin(origin: PackageOrigin) -> None:
    origin.package = _text(origin.package, 40)
    origin.file, origin.title = _text(origin.file, 200), _text(origin.title, 200)
    origin.label, origin.merged = _text(origin.label, 120), _text(origin.merged, 40)


def _sanitize_pin(pin: PinData, package: PackageData | None) -> PinData:
    number = _text(pin.number, 12).replace(" ", "") or "?"
    raw_name = clean_pin_name(pin.name)
    active_low = bool(pin.active_low) or "\\" in raw_name
    name = overbar_name(raw_name, active_low) or number
    no_connect = bool(pin.no_connect) or name.replace("\\", "").upper() in _NC_NAMES
    ep_number = package.exposed_pad_number if package is not None else ""
    # the user's flag counts; only designators (never free text) add the exposed-pad flag
    exposed = bool(pin.exposed_pad) or bool(_EP_DESIGNATOR.match(number.upper())) or bool(
        ep_number and number.casefold() == ep_number.casefold())
    return PinData(number=number, name=name, function=_text(pin.function, _MAX_FUNCTION),
                   electrical="passive" if no_connect else pin.electrical, active_low=active_low,
                   no_connect=no_connect, exposed_pad=exposed, group=_text(pin.group, 40),
                   part=pin.part if 0 <= pin.part <= 64 else 1)


def sanitize_extraction(data: ExtractionData, *, categories: Sequence[CategoryDef] = (),
                        ws_root: Any = None) -> ExtractionData:
    """An extraction edited by the user (``PUT /datasheets/{id}/extraction``) with the same rules as Claude's
    answers: no ``|``/control characters in any text, length limits, Altium overbar pin names, NC pins and exposed-pad
    designators recognised, page numbers positive, categories and field values checked against the open library.
    The plausibility issues are recomputed."""
    out = data.model_copy(deep=True)
    out.manufacturer = _text(out.manufacturer, 80)
    out.document_id = _text(out.document_id, 60)
    out.title = _text(out.title, 200)
    out.date = _text(out.date, 40)
    out.warnings = [w for w in (_text(x, 400) for x in out.warnings) if w]
    keys = set(family_keys()) - {"other"}
    for pkg in out.packages:
        pkg.name = _text(pkg.name, 80)
        pkg.code = _text(pkg.code, 40) or pkg.name or "PKG"
        pkg.family_raw = _text(pkg.family_raw, 40)
        if pkg.family is not None and pkg.family not in keys:
            pkg.family = resolve_family(pkg.name, pkg.code, pkg.family)
        pkg.outline_reference = _text(pkg.outline_reference, 60)
        pkg.exposed_pad_number = _text(pkg.exposed_pad_number, 10).replace(" ", "")
        pkg.pages = sorted({p for p in pkg.pages if p > 0})
        for d in pkg.dimensions:
            d.symbol, d.description = _text(d.symbol, 12), _text(d.description, 120)
        lp = pkg.land_pattern
        lp.pad_shape, lp.notes = canonical_pad_shape(lp.pad_shape), _text(lp.notes, 300)
        lp.pages = sorted({p for p in lp.pages if p > 0})
        lp.row_spacing_y = _positive(lp.row_spacing_y)
        pkg.layout = _sanitize_layout(pkg.layout)
        if pkg.origin is not None:
            _sanitize_origin(pkg.origin)
    by_table = {c.table.casefold(): c for c in categories}
    for dev in out.devices:
        dev.base_part = _text(dev.base_part, 64) or "Bauteil"
        dev.description = _text(dev.description, 120)
        dev.category_raw = _text(dev.category_raw, 80)
        category = by_table.get(dev.category.casefold()) if dev.category else None
        if category is not None:
            dev.category = category.table
        elif dev.category and by_table:
            dev.category = None  # not a category of the open library -> issue "category"
        dev.parameters = _sanitize_parameters(dev.parameters, category, ws_root)
        for v in dev.variants:
            v.mpn = _text(v.mpn, 64)
            v.package = _text(v.package, 40)
            v.temperature_range, v.packaging = _text(v.temperature_range, 60), _text(v.packaging, 120)
            v.status, v.notes = _text(v.status, 30), _text(v.notes, 200)
            v.values = _sanitize_parameters(v.values, category, ws_root)
            v.pages = sorted({p for p in v.pages if p > 0})
        dev.variants = [v for v in dev.variants if v.mpn]
        for table in dev.pin_tables:
            table.package = _text(table.package, 40)
            table.pages = sorted({p for p in table.pages if p > 0})
            package = out.package(table.package)
            table.pins = [_sanitize_pin(p, package) for p in table.pins]
    out.issues = validate_extraction(out)
    return out


def vision_reasons(issues: Iterable[Issue]) -> list[str]:
    """Issues that a high-resolution re-check of the drawings may resolve (German texts, for the follow-up prompt)."""
    return [i.message for i in issues if i.vision and i.severity in ("error", "warning")]


def issue_summary(issues: Iterable[Issue]) -> Mapping[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for i in issues:
        counts[i.severity] = counts.get(i.severity, 0) + 1
    return counts
