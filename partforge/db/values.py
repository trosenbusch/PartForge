"""Field values: parsing, normalisation, canonical formatting and description templates.

Every value in a category table is text (Altium parameters are strings). The field
``kind``/``unit`` tells PartForge how to interpret it:

* ``quantity``  engineering value, stored as canonical display text: ``"10k"`` -> ``"10kΩ"``,
  ``"100n"`` -> ``"100nF"``, ``"1"`` (unit %) -> ``"±1%"``, ``"1/10W"`` -> ``"0.1W"``.
  Precision is preserved (``"32.768kHz"`` stays exact).
* ``range``     two quantities: ``"-55 to 155"`` -> ``"-55°C … 155°C"``.
* ``int``, ``bool`` (``Ja``/``Nein``), ``enum`` (canonical option spelling), ``date`` (ISO),
  ``url`` and ``path`` (workspace-relative with backslashes).

Invalid input never raises here: :func:`normalize_cell` returns the (trimmed) text
together with a German warning, or an error for hard violations (forbidden characters
in the part number). Length limits are soft (warnings only): every Altium-visible
column is ``TEXT`` (Altium truncates ``VARCHAR(n)`` values at ``n`` – VERIFIED).

Templates (``"RES {Size} {Resistance} {Tolerance}"``) support the format specs
``si``, ``rkm`` (``4k7``, ``100n``, ``6V3``), ``nounit`` (``4.7k``), ``upper``, ``lower``.
Whitespace-separated tokens whose placeholders are all empty are dropped.

Parsing and formatting of engineering values is delegated to :mod:`partforge.domain.units`
(the one canonical path, exact digits): this module only adds the field rules – the field
unit wins over the typed one, relative tolerances get "±", ``ppm`` and ``ppm/K`` inputs are
interchangeable, and units unknown to :mod:`~partforge.domain.units` are accepted as a
plain suffix.

Asymmetric bands of relative quantities (fields in ``%``, ``ppm``, ``ppm/K``) are values too:
``"-100~+350ppm/℃"``, ``"+350/-100 ppm/K"``, ``"-20 % … +80 %"`` are stored as
``"-100 … +350ppm/K"`` / ``"-20 … +80%"`` (both bounds signed, unit once; a symmetric band
becomes ``"±100ppm/K"``); :func:`numeric_value` of a band is its worst case (``350``).

0-Ω jumpers (:func:`is_jumper`: the category's value field is a resistance and the part's value
is 0 Ω) have no tolerance, TCR, power rating or working voltage – the datasheets rate a jumper
by its maximum resistance and rated current (e.g. Panasonic ERJ "For Jumper", UNI-ROYAL
"Rated Current of Jumper", Vishay "Jumper, Imax"). :func:`not_applicable` names those columns;
required-field checks skip them.
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from ..domain.units import (
    RKM_UNIT_LETTERS,
    Quantity,
    ambiguous_thousands,
    format_quantity,
    format_rkm,
    normalize_unit,
    parse_quantity,
    resolve_commas,
)
from ..domain.text import FORMAT_CHARS, identity_text
from .models import CategoryDef, FieldDef

log = logging.getLogger(__name__)

__all__ = [
    "CellResult",
    "JUMPER_EXEMPT_UNITS",
    "PART_NUMBER",
    "RELATIVE_UNITS",
    "canonical_unit",
    "format_band",
    "invisible_characters",
    "is_jumper",
    "length_limit",
    "length_warning",
    "format_field_quantity",
    "format_range",
    "format_rkm_value",
    "normalize_cell",
    "not_applicable",
    "numeric_value",
    "parse_date",
    "parse_field_band",
    "parse_field_quantity",
    "parse_field_range",
    "render_template",
    "template_columns",
    "template_tokens",
    "to_text",
    "units_compatible",
]

PART_NUMBER = "Part Number"
MPN_COLUMN = "Manufacturer Part Number"
#: Fields that identify a part: stored in NFC without invisible format characters (soft hyphen, zero-width
#: space, BOM, bidi overrides …, :func:`partforge.domain.text.identity_text`), compared by
#: :func:`partforge.db.parts.pn_key` / :func:`partforge.db.parts.mpn_key`.
IDENTITY_COLUMNS = frozenset({PART_NUMBER, MPN_COLUMN})
# German names of the invisible characters met most often in copied part numbers
_FORMAT_CHAR_NAMES = {0x00AD: "weiches Trennzeichen", 0x200B: "Leerzeichen ohne Breite", 0x200C: "Bindehemmer",
                      0x200D: "Verbinder ohne Breite", 0x200E: "Links-nach-rechts-Marke",
                      0x200F: "Rechts-nach-links-Marke", 0x202E: "Richtungsumkehr", 0x2060: "Wortverbinder",
                      0xFEFF: "Byte-Order-Mark"}

# Relative tolerances and temperature coefficients are always shown with "±" (one spelling: "±100ppm/K", whether
# the user typed "100", "±100ppm" or "-100 … +100").
_PLUS_MINUS_UNITS = frozenset({"%", "ppm", "ppm/K"})
# "ppm" (ratio) and "ppm/K" (temperature coefficient) accept each other's spelling as input.
_PPM_UNITS = frozenset({"ppm", "ppm/K"})
#: Units of values relative to a nominal value (tolerances, TCR): they may be asymmetric bands.
RELATIVE_UNITS = frozenset({"%", "ppm", "ppm/K"})
#: Field units that do not apply to a 0-Ω jumper (see the module docstring): tolerance and TCR are
#: relative to a nominal value of 0, power rating and working voltage belong to the resistive element.
JUMPER_EXEMPT_UNITS = frozenset({"%", "ppm", "ppm/K", "W", "V"})
# Separators of an asymmetric band: "…", "...", "~", "to", "bis" – or "/" between two signed numbers
# ("+350/-100ppm/K"; the "/" of "ppm/K" is never one)
_BAND_SPLIT = re.compile(r"\s*(?:\.\.\.|…|~|\bto\b|\bbis\b)\s*|(?<=[\d%])\s*/\s*(?=[+-]\s*\d)")
# Datasheet spellings: full-width/small plus signs, full-width tilde, the degree-Celsius sign
_BAND_CHARS = str.maketrans({"＋": "+", "﹢": "+", "～": "~", "〜": "~", "℃": "°C"})
# Units whose values practically always carry a prefix: a plain "100" gets a warning
_PREFIX_EXPECTED_UNITS = frozenset({"F", "H"})
_PLAIN_NUMBER = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")

_SPECIAL_LENGTHS = {"Description": 1000, "Notes": 4000, "ComponentLink1URL": 2000}
DEFAULT_LENGTH = 255
# Unicode minus/dash characters accepted as a sign in numbers ("−40 … 125" from PDFs/Word)
_MINUS_SIGNS = str.maketrans({"−": "-", "‒": "-", "–": "-", "‐": "-", "‑": "-",
                              "﹣": "-", "－": "-"})

_FORBIDDEN_PN_CHARS = set("'{}|") | {chr(c) for c in range(32)} | {"\x7f"}
# invisible control characters from copy & paste (tab/newline are handled as whitespace)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_TRUE_WORDS = {"ja", "j", "yes", "y", "true", "wahr", "1", "x", "✓", "on", "an"}
_FALSE_WORDS = {"nein", "n", "no", "false", "falsch", "0", "off", "aus"}

_RANGE_SPLIT = re.compile(
    r"\s*(?:\.\.\.|…|\bto\b|\bbis\b|~|(?<=[\dΩa-zA-Z%°])\s*-\s*(?=[-+]?\d))\s*"
)
_PLACEHOLDER = re.compile(r"\{([^{}:]+?)(?::([A-Za-z]+))?\}")
_SEPARATOR_TOKEN = re.compile(r"^[,;/|\-–—·]+$")
_URL_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_WIN_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


@dataclass(slots=True)
class CellResult:
    """Outcome of :func:`normalize_cell`: the value to store plus optional diagnostics.

    ``unreadable``: the input could not be interpreted for the field kind (no number, wrong unit, no
    date, no Ja/Nein, ambiguous comma …) – it is stored as typed with ``warning``; the strict import
    rejects such rows. Free text outside an enum's list, length limits and the "no unit prefix" hint
    are not unreadable. ``note``: how an input was read that needed the source's number format
    (``thousands=True``: „2,000 pF“ read with thousands separator) – information, no problem.
    """

    value: str | None
    warning: str | None = None
    error: str | None = None
    unreadable: bool = False
    note: str | None = None


# --------------------------------------------------------------------------- basics


def length_limit(field: FieldDef) -> int | None:
    """Soft length limit of a field in characters (``None`` = unlimited).

    ``FieldDef.length``: ``None`` = default (255; Description 1000, Notes 4000, URLs 2000),
    ``0`` = no limit, ``n`` = n characters. Longer values only produce a warning – the
    columns are ``TEXT``, so nothing is truncated."""
    if field.length is not None:
        return int(field.length) if int(field.length) > 0 else None
    if field.column in _SPECIAL_LENGTHS:
        return _SPECIAL_LENGTHS[field.column]
    if field.kind == "url":
        return 2000
    return DEFAULT_LENGTH


def length_warning(field: FieldDef, value: str | None) -> str | None:
    """German warning if ``value`` exceeds the soft length limit of ``field``."""
    limit = length_limit(field)
    if value is None or limit is None or len(value) <= limit:
        return None
    return f"Der Wert ist {len(value)} Zeichen lang (empfohlen sind höchstens {limit})."


@lru_cache(maxsize=512)
def canonical_unit(unit: str | None) -> str:
    """Canonical unit symbol of a field unit (``ohm`` -> ``Ω``; ``ppm`` stays distinct from ``ppm/K``)."""
    return normalize_unit(unit)


@lru_cache(maxsize=2048)
def units_compatible(parsed_unit: str | None, field_unit: str | None) -> bool:
    """True if a parsed unit fits the field unit (no unit given is always fine).

    ``ppm`` and ``ppm/K`` are accepted for each other ("±20ppm" for a TCR field): the
    field unit decides how the value is stored."""
    if not parsed_unit:
        return True
    fu = canonical_unit(field_unit)
    if not fu:
        return True
    parsed = canonical_unit(parsed_unit)
    if fu in _PPM_UNITS:
        return parsed in _PPM_UNITS
    return parsed == fu


def _float_text(value: float) -> str:
    if math.isnan(value) or math.isinf(value):
        return str(value)
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    text = f"{value:.15g}"
    if "e" in text or "E" in text:
        try:
            text = format(Decimal(repr(value)), "f")
        except InvalidOperation:  # pragma: no cover - defensive
            return text
    return text


def to_text(raw: Any, *, multiline: bool = False) -> str | None:
    """Convert any input (spreadsheet cell, JSON value) to trimmed text; empty -> None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        text = "Ja" if raw else "Nein"
    elif isinstance(raw, int):
        text = str(raw)
    elif isinstance(raw, float):
        if math.isnan(raw):
            return None
        text = _float_text(raw)
    elif isinstance(raw, _dt.datetime):
        text = raw.isoformat(sep=" ", timespec="seconds")
    elif isinstance(raw, _dt.date):
        text = raw.isoformat()
    else:
        text = str(raw)
    text = _CONTROL_CHARS.sub("", text).replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    if multiline:
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
        text = "\n".join(lines).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()
    return text or None


# --------------------------------------------------------------------------- numbers


def format_field_quantity(value: float, unit: str | None, *, plus_minus: bool = False) -> str:
    """Canonical display text of a quantity for a field unit (exact digits, house style).

    Thin wrapper around :func:`partforge.domain.units.format_quantity`.

    >>> format_field_quantity(4700, "Ω")
    '4.7kΩ'
    >>> format_field_quantity(1, "%", plus_minus=True)
    '±1%'
    """
    return format_quantity(value, canonical_unit(unit), digits=None, plus_minus=plus_minus)


def format_rkm_value(value: float, unit: str | None) -> str:
    """IEC 60062 letter-and-digit code: 4700 Ω -> ``4k7``, 0.47 Ω -> ``R47``,
    100 nF -> ``100n``, 2.2 µF -> ``2u2``, 6.3 V -> ``6V3`` (house style: lower-case k).

    Thin wrapper around :func:`partforge.domain.units.format_rkm` with exact digits."""
    return format_rkm(value, canonical_unit(unit), upper=False, digits=None)


def _strip_plus_minus(text: str) -> str:
    return text.replace("±", "").replace("+/-", "").replace("+-", "").strip()


def _has_plus_minus(text: str) -> bool:
    return "±" in text or "+/-" in text or "+-" in text


@lru_cache(maxsize=65536)
def parse_field_quantity(text: str, unit: str | None, *, thousands: bool | None = None) -> Quantity | None:
    """Parse engineering notation for a field unit.

    :func:`partforge.domain.units.parse_quantity` does the work; on top of it the field
    unit is the default unit, ``ppm``/``ppm/K`` inputs take the field's spelling, RKM codes
    with the field's unit letter ("2F2" for a farad field) and plain suffixes of units the
    domain module does not know ("5lm") are accepted. ``thousands``: how an ambiguous comma
    group ("1,000µF") is read – ``None`` (unknown source) gives ``None`` (see
    :func:`partforge.domain.units.resolve_commas`)."""
    if text is None:
        return None
    t = str(text).strip().translate(_MINUS_SIGNS)
    if not t:
        return None
    fu = canonical_unit(unit)
    q = parse_quantity(t, fu or None, thousands=thousands)
    if q is not None:
        if fu in _PPM_UNITS and q.unit in _PPM_UNITS:
            return Quantity(q.value, fu)
        if not q.unit and fu:
            return Quantity(q.value, fu)
        return q
    core = resolve_commas(_strip_plus_minus(t).replace(" ", "").replace(" ", "").replace(" ", ""),
                          thousands)
    if core is None:  # ambiguous comma group ("1,000µF" from an unknown source)
        return None
    # RKM with the field's unit letter as decimal marker: "2F2" (2.2 F), "1H5"
    m = re.fullmatch(r"(\d*)([A-Za-z])(\d+)", core)
    if m and fu and m.group(2) == fu and fu in RKM_UNIT_LETTERS:
        return Quantity(float(f"{m.group(1) or '0'}.{m.group(3)}"), fu)
    if fu:
        suffixes = sorted({fu, unit or "", fu.lower()} - {""}, key=len, reverse=True)
        for suffix in suffixes:
            if core.lower().endswith(suffix.lower()) and len(core) > len(suffix):
                number = core[: -len(suffix)]
                inner = parse_quantity(number, None)
                if inner is not None and not inner.unit:
                    return Quantity(inner.value, fu)
    return None


def parse_field_range(text: str, unit: str | None, *, thousands: bool | None = None) -> tuple[float, float] | None:
    """Parse ``"-55°C … +155°C"``, ``"-40 to 125"``, ``"1.8V - 5.5V"`` for a field unit."""
    if not text:
        return None
    parts = [p for p in _RANGE_SPLIT.split(str(text).strip().translate(_MINUS_SIGNS)) if p and p.strip()]
    if len(parts) != 2:
        return None
    if any(_has_plus_minus(p) for p in parts):  # "2.8V to ±5.25V" is no plain number range (see _plus_minus_range)
        return None
    hi = parse_field_quantity(parts[1], unit, thousands=thousands)
    lo = parse_field_quantity(parts[0], unit, thousands=thousands)
    if lo is None or hi is None:
        return None
    if not (units_compatible(lo.unit, unit) and units_compatible(hi.unit, unit)):
        return None
    return lo.value, hi.value


def format_range(lo: float, hi: float, unit: str | None) -> str:
    return f"{format_field_quantity(lo, unit)} … {format_field_quantity(hi, unit)}"


def _plus_minus_range(text: str, unit: str | None, thousands: bool | None) -> str | None:
    """Canonical text of a range with a ± bound – symmetric supplies such as ``"2.8V to ±5.25V"`` or
    ``"±2.25V to ±18V"``: ``"2.8V … ±5.25V"``. The ± is kept (it doubles the span) instead of being
    dropped; such a value is no plain number range. ``None`` if ``text`` is not such a range."""
    parts = [p for p in _RANGE_SPLIT.split(str(text).strip().translate(_MINUS_SIGNS)) if p and p.strip()]
    if len(parts) != 2 or not any(_has_plus_minus(p) for p in parts):
        return None
    bounds: list[str] = []
    for part in parts:
        q = parse_field_quantity(part, unit, thousands=thousands)
        if q is None or not units_compatible(q.unit, unit):
            return None
        bounds.append(format_field_quantity(q.value, unit or q.unit, plus_minus=_has_plus_minus(part)))
    return f"{bounds[0]} … {bounds[1]}"


@lru_cache(maxsize=16384)
def parse_field_band(text: str, unit: str | None, *, thousands: bool | None = None) -> tuple[float, float] | None:
    """Asymmetric band ``(low, high)`` of a relative quantity field (unit ``%``, ``ppm``, ``ppm/K``).

    Accepts ``"-100 … +350ppm/K"``, ``"-100~+350 ppm/℃"``, ``"+350/-100ppm/K"``, ``"-20% to +80%"``
    (Unicode minus/plus signs included); ``None`` for anything else, for fields of other units and
    for a "band" whose bounds are equal."""
    if text is None or canonical_unit(unit) not in RELATIVE_UNITS:
        return None
    t = str(text).strip().translate(_MINUS_SIGNS).translate(_BAND_CHARS)
    parts = [p for p in _BAND_SPLIT.split(t) if p and p.strip()]
    if len(parts) != 2:
        return None
    bounds: list[float] = []
    for part in parts:
        q = parse_field_quantity(part, unit, thousands=thousands)
        if q is None or not units_compatible(q.unit, unit):
            return None
        bounds.append(q.value)
    low, high = sorted(bounds)
    if math.isclose(low, high, rel_tol=1e-12, abs_tol=0.0):
        return None
    return low, high


def _signed(value: float, unit: str | None) -> str:
    """Number text of a band bound with its sign ("+350", "-100", "0") – formatted by domain.units."""
    if value == 0:
        return "0"
    number = format_field_quantity(abs(value), unit)
    suffix = canonical_unit(unit)
    if suffix and number.endswith(suffix):
        number = number[: -len(suffix)]
    return ("-" if value < 0 else "+") + number


def format_band(low: float, high: float, unit: str | None) -> str:
    """Canonical text of a tolerance band: ``"-100 … +350ppm/K"``; symmetric -> ``"±100ppm/K"``."""
    if high > 0 and math.isclose(low, -high, rel_tol=1e-12, abs_tol=0.0):
        return format_field_quantity(high, unit, plus_minus=True)
    return f"{_signed(low, unit)} … {_signed(high, unit)}{canonical_unit(unit)}"


@lru_cache(maxsize=131072)
def numeric_value(text: str | None, unit: str | None) -> float | None:
    """Numeric base-unit value of a stored quantity/int text (sorting, filtering).

    A tolerance band (``"-100 … +350ppm/K"``) counts with its worst case (``350``)."""
    if text is None:
        return None
    q = parse_field_quantity(str(text), unit)
    if q is None or not units_compatible(q.unit, unit):
        band = parse_field_band(str(text), unit) if q is None else None
        return max(abs(band[0]), abs(band[1])) if band is not None else None
    return q.value


# --------------------------------------------------------------------------- normalisation


def _ambiguous_warning(text: str, field_unit: str | None, *, what: str = "quantity") -> str:
    """German warning for an ambiguous comma group: both readings and how to type the value unambiguously."""
    readings: list[str] = []
    for thousands in (True, False):
        if what == "int":
            resolved = resolve_commas(text.strip().translate(_MINUS_SIGNS), thousands) or ""
            try:
                number = float(resolved)
            except ValueError:
                readings.append(resolved)
                continue
            readings.append(str(int(number)) if math.isfinite(number) and number == int(number) else resolved)
            continue
        q = parse_field_quantity(text, field_unit, thousands=thousands)
        rng = parse_field_range(text, field_unit, thousands=thousands) if q is None else None
        if q is not None and units_compatible(q.unit, field_unit):
            readings.append(format_field_quantity(q.value, field_unit or q.unit))
        elif rng is not None:
            readings.append(format_range(rng[0], rng[1], field_unit))
        else:
            readings.append("")
    as_thousands, as_decimal = readings
    if as_thousands and as_decimal:
        return (f"„{text}“ ist mehrdeutig: Komma als Tausendertrennzeichen ({as_thousands}) oder als Dezimalkomma "
                f"({as_decimal})? Bitte eindeutig eingeben, z. B. „{as_thousands}“ oder „{as_decimal}“.")
    return (f"„{text}“ ist mehrdeutig: Das Komma kann ein Tausendertrennzeichen oder ein Dezimalkomma sein "
            "(1,000 = 1000 oder 1,0?). Bitte ohne Tausendertrennzeichen eingeben.")


def _thousands_note(text: str, value: str) -> str:
    return f"„{text}“ mit Komma als Tausendertrennzeichen gelesen: {value}."


@lru_cache(maxsize=65536)
def _quantity_text(text: str, field_unit: str | None,
                   thousands: bool | None = None) -> tuple[str, str | None, str | None]:
    """(stored text, warning, note) of a quantity input – pure and therefore cached."""
    q = parse_field_quantity(text, field_unit, thousands=thousands)
    unit_label = field_unit or "-"
    if q is None:
        band = parse_field_band(text, field_unit, thousands=thousands)
        if band is not None:  # asymmetric tolerance / TCR: "-100 … +350ppm/K"
            return format_band(band[0], band[1], field_unit), None, None
        if thousands is None and ambiguous_thousands(text):  # "1,000µF": 1000 µF or 1 µF – never guess
            return text, _ambiguous_warning(text, field_unit), None
        return text, f"„{text}“ ist kein gültiger Wert (erwartet z. B. 10k, 100n, 1%; Einheit {unit_label}).", None
    if not units_compatible(q.unit, field_unit):
        return text, f"Einheit von „{text}“ passt nicht zur Einheit {unit_label} – Wert unverändert übernommen.", None
    unit = field_unit if field_unit else q.unit
    plus_minus = canonical_unit(unit) in _PLUS_MINUS_UNITS or "±" in text or "+/-" in text
    formatted = format_field_quantity(q.value, unit, plus_minus=plus_minus)
    note = _thousands_note(text, formatted) if thousands and ambiguous_thousands(text) else None
    if canonical_unit(unit) in _PREFIX_EXPECTED_UNITS and _PLAIN_NUMBER.match(text) and abs(q.value) >= 1:
        # "100" for a capacitor is almost never 100 F: store it, but ask for a prefix
        return formatted, (f"„{text}“ ohne Einheit wird als {formatted} gelesen – bitte mit Vorsatz angeben "
                           f"(z. B. {text}p, {text}n, {text}u)."), note
    return formatted, None, note


def _norm_quantity(field: FieldDef, text: str, thousands: bool | None = None) -> CellResult:
    value, warning, note = _quantity_text(text, field.unit, thousands)
    # stored unchanged (= not interpreted) means unreadable; a formatted value with a hint was read
    return CellResult(value, warning=warning, unreadable=warning is not None and value == text, note=note)


def _norm_range(field: FieldDef, text: str, thousands: bool | None = None) -> CellResult:
    rng = parse_field_range(text, field.unit, thousands=thousands)
    if rng is not None:
        lo, hi = rng
        value = format_range(lo, hi, field.unit)
        note = _thousands_note(text, value) if thousands and ambiguous_thousands(text) else None
        return CellResult(value, note=note)
    symmetric = _plus_minus_range(text, field.unit, thousands)
    if symmetric is not None:
        return CellResult(symmetric)
    single = _norm_quantity(field, text, thousands)
    if single.warning is None:
        return single
    if thousands is None and ambiguous_thousands(text):
        return CellResult(text, warning=_ambiguous_warning(text, field.unit), unreadable=True)
    return CellResult(text, warning=f"„{text}“ ist kein gültiger Bereich (z. B. -40 … 85; Einheit {field.unit or '-'}).",
                      unreadable=True)


def _norm_int(text: str, thousands: bool | None = None) -> CellResult:
    candidate = resolve_commas(text.strip().translate(_MINUS_SIGNS), thousands)
    if candidate is None:  # "1,000": 1000 or 1,0 – never guess
        return CellResult(text, warning=_ambiguous_warning(text, None, what="int"), unreadable=True)
    try:
        number = float(candidate)
    except ValueError:
        return CellResult(text, warning=f"„{text}“ ist keine ganze Zahl.", unreadable=True)
    if not math.isfinite(number) or number != int(number):
        return CellResult(text, warning=f"„{text}“ ist keine ganze Zahl.", unreadable=True)
    value = str(int(number))
    return CellResult(value, note=_thousands_note(text, value) if thousands and ambiguous_thousands(text) else None)


def _norm_bool(text: str) -> CellResult:
    word = text.strip().lower()
    if word in _TRUE_WORDS:
        return CellResult("Ja")
    if word in _FALSE_WORDS:
        return CellResult("Nein")
    return CellResult(text, warning=f"„{text}“ ist kein Ja/Nein-Wert.", unreadable=True)


def _norm_enum(field: FieldDef, text: str) -> CellResult:
    if not field.options:
        return CellResult(text)
    if text in field.options:
        return CellResult(text)
    folded = text.casefold()
    for option in field.options:
        if option.casefold() == folded:
            return CellResult(option)
    if text.isdigit() and f"0{text}" in field.options:  # "603" from a spreadsheet number -> "0603"
        return CellResult(f"0{text}")
    return CellResult(text, warning=f"„{text}“ ist nicht in der Auswahlliste ({', '.join(field.options[:12])}"
                                     f"{' …' if len(field.options) > 12 else ''}).")


# stored date texts: "2026-10-07" and "2026-10-07 21:30:00" (fast path of parse_date)
_CANONICAL_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$")
_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%d.%m.%y",
    "%Y/%m/%d",
)


def parse_date(text: str | None) -> tuple[_dt.datetime, Literal["day", "minute", "second"]] | None:
    """Date (and time) of an input or stored value with its precision, or ``None``.

    Accepts the formats of the date fields (``2026-10-07``, ``2026-10-07 21:30[:00]``, ``07.10.2026``,
    ``7.10.26``, ``2026/10/07``) and ISO timestamps (``2026-10-07T21:30:00+02:00``, the zone is dropped)."""
    if text is None:
        return None
    candidate = str(text).strip()
    if not candidate:
        return None
    canonical = _CANONICAL_DATE.match(candidate)
    if canonical is not None:  # the stored spelling (PF Created/PF Modified): no strptime loop
        try:
            return _dt.datetime.fromisoformat(candidate), "second" if canonical.group(1) else "day"
        except ValueError:
            pass  # e.g. "2026-02-30": the formats below refuse it as well
    for fmt in _DATE_FORMATS:
        try:
            parsed = _dt.datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        precision: Literal["day", "minute", "second"] = (
            "second" if "%S" in fmt else ("minute" if "%M" in fmt else "day"))
        return parsed, precision
    try:
        parsed = _dt.datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None), "second"


def _norm_date(text: str) -> CellResult:
    parsed = parse_date(text)
    if parsed is None:
        return CellResult(text, warning=f"„{text}“ ist kein gültiges Datum (z. B. 2026-10-07 oder 07.10.2026).",
                          unreadable=True)
    moment, precision = parsed
    if precision == "day":
        return CellResult(moment.date().isoformat())
    return CellResult(moment.isoformat(sep=" ", timespec="seconds"))


_DOMAIN = re.compile(r"^[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}$")
_FILE_EXT = re.compile(r"\.(pdf|html?|txt|docx?|xlsx?|step|stp|zip)$", re.I)


def _norm_url(text: str) -> CellResult:
    candidate = text.strip()
    if _URL_SCHEME.match(candidate) or candidate.lower().startswith("mailto:"):
        return CellResult(candidate)
    if candidate.lower().startswith("www."):
        return CellResult(f"https://{candidate}")
    if _WIN_ABS.match(candidate) or "\\" in candidate:
        return CellResult(candidate)  # local file (absolute or workspace-relative)
    if " " not in candidate:
        head = candidate.split("/", 1)[0]
        if "/" in candidate and _DOMAIN.match(head) and not _FILE_EXT.search(head):
            return CellResult(f"https://{candidate}")  # "ti.com/lit/ds/symlink/lm358.pdf"
        if "/" in candidate or _FILE_EXT.search(candidate):
            return CellResult(candidate)  # relative file path "Datasheets/x.pdf"
        if _DOMAIN.match(candidate):
            return CellResult(f"https://{candidate}")
    return CellResult(candidate, warning=f"„{text}“ sieht nicht wie eine Adresse aus (https://… oder Dateipfad).")


def _norm_path(text: str, ws_root: Path | None) -> CellResult:
    candidate = text.strip().replace("/", "\\")
    if ws_root is not None and _WIN_ABS.match(candidate):
        try:
            rel = Path(candidate).resolve().relative_to(Path(ws_root).resolve())
            return CellResult(str(PureWindowsPath(rel)))
        except (ValueError, OSError):
            return CellResult(
                candidate,
                warning="Absoluter Pfad außerhalb des Bibliotheksordners – die Bibliothek ist dann nicht mehr verschiebbar.",
            )
    return CellResult(candidate)


def invisible_characters(text: str) -> list[str]:
    """German names of the invisible format characters in ``text`` ("U+00AD weiches Trennzeichen", …) –
    at most four, then "…"; empty if there are none."""
    found = list(dict.fromkeys(ord(ch) for ch in text if FORMAT_CHARS.fullmatch(ch)))
    names = [f"U+{c:04X} {_FORMAT_CHAR_NAMES[c]}" if c in _FORMAT_CHAR_NAMES else f"U+{c:04X}" for c in found[:4]]
    return names + (["…"] if len(found) > 4 else [])


def _identity(text: str) -> tuple[str | None, str | None]:
    """(stored spelling, German warning) of a part number / MPN: NFC without invisible format characters."""
    cleaned = identity_text(text)
    if cleaned == text:
        return text, None
    names = invisible_characters(text)
    if not names:  # only the Unicode normal form changed (NFD umlaut -> NFC): looks the same
        return cleaned or None, None
    warning = (f"Unsichtbare Zeichen entfernt ({', '.join(names)}) – sie stammen meist aus kopierten Webseiten oder "
               "PDFs und würden die Nummer von der sichtbar gleichen unterscheiden.")
    return cleaned or None, warning


def _check_part_number(text: str) -> str | None:
    bad = sorted({c for c in text if c in _FORBIDDEN_PN_CHARS})
    if bad:
        shown = " ".join(repr(c) if ord(c) < 32 else c for c in bad)
        return f"Die Teilenummer enthält unzulässige Zeichen ({shown}). Nicht erlaubt sind ' {{ }} | und Steuerzeichen."
    return None


def normalize_cell(field: FieldDef, raw: Any, *, ws_root: Path | None = None,
                   thousands: bool | None = None) -> CellResult:
    """Normalise one input value for a field (never raises).

    ``thousands``: the number format of the source for an ambiguous comma group ("1,000µF", "10,000"):
    ``None`` (manual entry, unknown source) stores the input as typed with a German warning
    („mehrdeutig“, ``unreadable`` – the strict import refuses it), ``True`` (English source such as a
    datasheet) reads a thousands separator (``note`` says so; logged), ``False`` (German source) a decimal
    comma. Unambiguous commas ("2,2µF", "1,000,000") are read the same in every mode."""
    text = to_text(raw, multiline=field.column == "Notes")
    if text is None:
        return CellResult(None)
    identity_warning: str | None = None
    if field.column in IDENTITY_COLUMNS:  # one spelling per part: NFC, no soft hyphen/zero-width/bidi characters
        cleaned, identity_warning = _identity(text)
        if cleaned is None:
            return CellResult(None, warning=identity_warning)
        text = cleaned
    if field.column == PART_NUMBER:
        problem = _check_part_number(text)
        if problem:
            return CellResult(text, error=problem, warning=identity_warning)
    kind = field.kind
    if kind == "quantity":
        result = _norm_quantity(field, text, thousands)
    elif kind == "range":
        result = _norm_range(field, text, thousands)
    elif kind == "int":
        result = _norm_int(text, thousands)
    elif kind == "bool":
        result = _norm_bool(text)
    elif kind == "enum":
        result = _norm_enum(field, text)
    elif kind == "date":
        result = _norm_date(text)
    elif kind == "url":
        result = _norm_url(text)
    elif kind == "path":
        result = _norm_path(text, ws_root)
    else:
        result = CellResult(text)
    if identity_warning:
        result.warning = f"{identity_warning} {result.warning}" if result.warning else identity_warning
    too_long = length_warning(field, result.value)
    if too_long:
        result.warning = f"{result.warning} {too_long}" if result.warning else too_long
    if result.note:
        log.info("%s: %s", field.column, result.note)
    return result


# --------------------------------------------------------------------------- 0-Ω jumpers


def _lookup_value(values: Mapping[str, Any], column: str) -> Any:
    if column in values:
        return values[column]
    folded = column.casefold()
    return next((v for k, v in values.items() if str(k).casefold() == folded), None)


def is_jumper(value_field: FieldDef | None, values: Mapping[str, Any]) -> bool:
    """True for a 0-Ω jumper: ``value_field`` (the category's value field) is a resistance in Ω and the
    part's value is exactly 0 (``0Ω``, ``0R``, ``0``)."""
    if value_field is None or value_field.kind != "quantity" or canonical_unit(value_field.unit) != "Ω":
        return False
    text = to_text(_lookup_value(values, value_field.column))
    if text is None:
        return False
    q = parse_field_quantity(text, value_field.unit)
    return q is not None and q.value == 0 and units_compatible(q.unit, value_field.unit)


def not_applicable(cat: CategoryDef, values: Mapping[str, Any]) -> frozenset[str]:
    """Columns of ``cat`` that do not apply to the part with ``values`` – for a 0-Ω jumper the quantity
    fields in :data:`JUMPER_EXEMPT_UNITS` (tolerance, TCR, power rating, working voltage), else none.
    Required-field checks (health check, series) skip these columns."""
    value_field = cat.field(cat.value_field) if cat.value_field else None
    if not is_jumper(value_field, values):
        return frozenset()
    return frozenset(f.column for f in cat.fields
                     if f.kind in ("quantity", "range") and canonical_unit(f.unit) in JUMPER_EXEMPT_UNITS)


# --------------------------------------------------------------------------- templates


def template_columns(template: str) -> list[str]:
    """Column names referenced by a template (in order, without duplicates)."""
    seen: list[str] = []
    for m in _PLACEHOLDER.finditer(template or ""):
        name = m.group(1).strip()
        if name not in seen:
            seen.append(name)
    return seen


def _lookup(values: Mapping[str, Any], column: str) -> Any:
    if column in values:
        return values[column]
    folded = column.casefold()
    for key, value in values.items():
        if key.casefold() == folded:
            return value
    return None


def _field_for(fields: Mapping[str, FieldDef], column: str) -> FieldDef | None:
    if column in fields:
        return fields[column]
    folded = column.casefold()
    return next((f for name, f in fields.items() if name.casefold() == folded), None)


def _format_placeholder(column: str, spec: str | None, values: Mapping[str, Any], fields: Mapping[str, FieldDef]) -> str:
    text = to_text(_lookup(values, column))
    if text is None:
        return ""
    if not spec:
        return text
    spec = spec.lower()
    if spec == "upper":
        return text.upper()
    if spec == "lower":
        return text.lower()
    field = _field_for(fields, column)
    unit = field.unit if field is not None else None
    q = parse_field_quantity(text, unit)
    if q is None:
        return text
    effective_unit = unit or q.unit
    if spec == "rkm":
        return format_rkm_value(q.value, effective_unit)
    if spec == "si":
        plus_minus = "±" in text or canonical_unit(effective_unit) in _PLUS_MINUS_UNITS
        return format_field_quantity(q.value, effective_unit, plus_minus=plus_minus)
    if spec in ("nounit", "num"):  # SI mantissa and prefix without unit: "4.7k"
        return format_quantity(q.value, "", digits=None)
    return text


def template_tokens(template: str) -> list[str]:
    """Split a template at whitespace outside of ``{…}`` placeholders
    (``"IC {Manufacturer Part Number} {Channels}CH"`` -> 3 tokens)."""
    return _template_tokens(template or "")


def _template_tokens(template: str) -> list[str]:
    """Split a template at whitespace outside of ``{…}`` placeholders."""
    tokens: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in template:
        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        if ch.isspace() and depth == 0:
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        tokens.append("".join(buf))
    return tokens


Segment = str | tuple[str, str | None]  # literal text or (column, format spec)


@lru_cache(maxsize=1024)
def _compiled(template: str) -> tuple[tuple[Segment, ...], ...]:
    """Template split into tokens of literal/placeholder segments (cached)."""
    tokens: list[tuple[Segment, ...]] = []
    for token in _template_tokens(template):
        segments: list[Segment] = []
        pos = 0
        for m in _PLACEHOLDER.finditer(token):
            if m.start() > pos:
                segments.append(token[pos : m.start()])
            segments.append((m.group(1).strip(), m.group(2)))
            pos = m.end()
        if pos < len(token):
            segments.append(token[pos:])
        tokens.append(tuple(segments))
    return tuple(tokens)


def render_template(template: str | None, values: Mapping[str, Any], fields: Mapping[str, FieldDef] | None = None) -> str:
    """Render a description/comment template.

    Tokens (whitespace separated) whose placeholders are all empty are dropped, so
    ``"IC {Channels}CH {GBW}"`` with empty Channels gives ``"IC <GBW>"``.
    """
    if not template:
        return ""
    fields = fields or {}
    out: list[str] = []
    for segments in _compiled(template):
        has_placeholder = False
        filled = False
        pieces: list[str] = []
        for segment in segments:
            if isinstance(segment, str):
                pieces.append(segment)
                continue
            has_placeholder = True
            value = _format_placeholder(segment[0], segment[1], values, fields)
            if value:
                filled = True
            pieces.append(value)
        rendered = "".join(pieces)
        if not has_placeholder or (filled and rendered.strip()):
            out.append(rendered)
    while out and _SEPARATOR_TOKEN.match(out[0]):
        out.pop(0)
    while out and _SEPARATOR_TOKEN.match(out[-1]):
        out.pop()
    return re.sub(r"\s+", " ", " ".join(out)).strip()
