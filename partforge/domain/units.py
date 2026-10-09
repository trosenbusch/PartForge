"""Engineering notation: parse and format physical quantities.

This module is the **one canonical path** for engineering values in PartForge: the
database layer (:mod:`partforge.db.values`), the series assistant and the datasheet
import all format through :func:`format_quantity` / :func:`format_rkm`, so a value is
stored with the same text whichever way it was entered.

Accepted inputs (German decimal comma included):
    "10k", "10 kΩ", "10kOhm", "4k7", "4R7", "R47", "0R", "1M5", "2u2", "2,2µF",
    "100nF", "0.1 uF", "1/16W", "0.063 W", "±1 %", "100ppm/K", "±20ppm", "1Meg", "33 mΩ",
    "1.75mm", "120°", "12nC", "6V3", "2A5", "290V/µs", "660nm"

Formatting (house style):
    format_quantity -> "4.7kΩ", "100nF", "2.2µF", "62.5mW", "0.25W", "±1%", "-55°C", "1.75mm"
    format_rkm      -> IEC 60062 letter-and-digit code: "4K7" (or "4k7"), "100R", "R47",
                       "100n", "2u2", "6V3"
    format_power    -> "0.1W" / "62.5mW", or fractions "1/16W"

Rules:
* SI prefixes f … T; never a prefix for the units in :data:`NO_PREFIX_UNITS`
  (%, ppm, ppm/K, °C, °, dB, mm, nm, mil, K, in): "0.5%", "1.75mm", "-55°C", "6500K".
* When parsing, a suffix equal to the default (field) unit is that unit, never a prefix:
  "6500K" with default unit K is 6500 K (a resistance "10K" is still 10 kΩ), so formatted
  values parse back to the same number. In a kelvin field a lone lower-case "k" is the
  unit as well ("6500k" = 6500 K; kilokelvin is "6.5kK", the RKM code "6k5" stays 6500 K).
* Power has no prefix from 0.1 W upward ("0.1W", "0.25W", "2.5W"); below that the prefix
  is used ("62.5mW") – the house style of the TR_* libraries.
* ``ppm`` (a ratio, e.g. the frequency tolerance of a crystal) and ``ppm/K`` (a
  temperature coefficient) are distinct units; :mod:`partforge.db.values` treats them as
  compatible inputs for each other.
* ``digits`` is the maximum number of significant digits (trailing zeros dropped);
  ``digits=None`` uses the exact value (:func:`exact_digits`, 3 … 9 digits) – stored
  values never lose precision ("14.31818MHz" stays exact).
* Non-finite numbers ("1e999", "inf", "nan") are not quantities: parsing returns ``None``.
* Commas: a decimal comma ("2,2µF", "4,7k", "0,100") is read as decimal point. A comma followed
  by exactly three digits is ambiguous when it is the only one ("1,000µF" = 1000 µF in an English
  datasheet, 1 µF in German; "32,768 Hz"): ``thousands=None`` (default, e.g. manual entry) refuses
  to guess – parsing returns ``None`` and :func:`ambiguous_thousands` tells why –, ``thousands=True``
  reads it as thousands separator (English sources such as datasheets), ``thousands=False`` as
  decimal comma (German sources). Several groups ("1,000,000") or a decimal point after the group
  ("1,000.5") are always thousands; a group after a leading 0 ("0,100") is always decimal.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

__all__ = [
    "Quantity",
    "PREFIXES",
    "UNIT_ALIASES",
    "NO_PREFIX_UNITS",
    "RKM_UNIT_LETTERS",
    "ambiguous_thousands",
    "resolve_commas",
    "parse_quantity",
    "parse_value",
    "parse_range",
    "format_quantity",
    "format_rkm",
    "format_power",
    "significant_digits",
    "exact_digits",
    "normalize_unit",
]

PREFIXES: dict[str, float] = {
    "f": 1e-15,
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,  # U+00B5 micro sign
    "μ": 1e-6,  # U+03BC greek mu
    "m": 1e-3,
    "": 1.0,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
    "T": 1e12,
}

# Prefix symbols used when formatting (exponent -> symbol); µ is U+00B5.
_SI_SYMBOLS: dict[int, str] = {-15: "f", -12: "p", -9: "n", -6: "µ", -3: "m", 0: "", 3: "k", 6: "M", 9: "G", 12: "T"}
# RKM letters (ASCII "u" for micro, IEC 60062); the kilo letter follows ``upper``.
_RKM_SYMBOLS: dict[int, str] = {-15: "f", -12: "p", -9: "n", -6: "u", -3: "m", 3: "k", 6: "M", 9: "G", 12: "T"}
_MIN_EXP = -15
_MAX_EXP = 12

# Canonical unit symbols and accepted spellings (compared case-insensitively
# unless the alias is a single character).
UNIT_ALIASES: dict[str, list[str]] = {
    "Ω": ["Ω", "Ω", "ohm", "ohms", "Ohm", "OHM", "R"],
    "F": ["F", "farad"],
    "H": ["H", "henry"],
    "V": ["V", "volt", "VDC", "VAC", "Vdc", "Vac"],
    "A": ["A", "amp", "ampere"],
    "W": ["W", "watt"],
    "Hz": ["Hz", "hz", "HZ"],
    "%": ["%"],
    "ppm/K": ["ppm/K", "ppm/°C", "ppm/C", "ppm/k"],
    "ppm": ["ppm"],  # ratio (frequency tolerance), not a temperature coefficient
    "°C": ["°C", "degC", "C°"],
    "°": ["°", "deg", "grad"],
    "s": ["s", "sec"],
    "dB": ["dB"],
    "cd": ["cd"],
    "C": ["C", "coulomb"],
    "V/µs": ["V/µs", "V/us", "V/μs"],
    # Length units are kept as-is (not converted to metres): datasheet heights, pitches, wavelengths.
    "mm": ["mm"],
    "nm": ["nm"],
    "mil": ["mil", "mils"],
}

#: Units that are never written with SI prefixes ("0.5%" not "500m%", "1.75mm" not "1.75m mm").
NO_PREFIX_UNITS: frozenset[str] = frozenset({"%", "ppm/K", "ppm", "°C", "°", "dB", "mm", "nm", "mil", "K", "in"})
#: Single-letter units that serve as decimal marker in RKM codes ("6V3", "2A5", "2F2").
RKM_UNIT_LETTERS: frozenset[str] = frozenset({"V", "A", "W", "F", "H", "C", "s"})
_POWER_PREFIX_LIMIT = 0.1  # W: no prefix from 0.1 W upward (house style)
_EXACT_MIN_DIGITS = 3
_EXACT_MAX_DIGITS = 9

_ALIAS_LOOKUP: list[tuple[str, str]] = sorted(
    ((alias, canonical) for canonical, aliases in UNIT_ALIASES.items() for alias in aliases),
    key=lambda item: -len(item[0]),
)


@dataclass(frozen=True)
class Quantity:
    """A parsed physical quantity in base units (e.g. 4700.0, "Ω")."""

    value: float
    unit: str = ""

    def format(self, style: str = "si", **kwargs: Any) -> str:
        """``style="si"`` -> :func:`format_quantity`, ``"rkm"`` -> :func:`format_rkm`."""
        if style == "rkm":
            return format_rkm(self.value, self.unit or "Ω", **kwargs)
        return format_quantity(self.value, self.unit, **kwargs)


def normalize_unit(unit: str | None) -> str:
    """Map a unit spelling to its canonical symbol ("ohm" -> "Ω", "ppm/°C" -> "ppm/K")."""
    if not unit:
        return ""
    u = unit.strip()
    for alias, canonical in _ALIAS_LOOKUP:
        if len(alias) == 1:
            if u == alias:
                return canonical
        elif u.lower() == alias.lower():
            return canonical
    return u


# --------------------------------------------------------------------------- parsing


# A number with comma groups of three digits: "1,000", "10,000", "1,000,000", "2,200.5" (not "2,2", "12,34")
_COMMA_GROUPS = re.compile(r"(?<![\d.,])(\d{1,3})((?:,\d{3})+)(\.\d+)?(?![\d,])")
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def resolve_commas(text: str, thousands: bool | None = None) -> str | None:
    """``text`` with the commas of its numbers resolved: thousands separators removed, decimal commas
    turned into decimal points ("2,2µF" -> "2.2µF", "1,000,000" -> "1000000").

    A single group of three digits after a non-zero digit ("1,000µF", "32,768Hz") is ambiguous:
    ``thousands=True`` reads it as thousands separator, ``False`` as decimal comma, ``None``
    (unknown source) returns ``None`` – the caller must not guess."""
    ambiguous = False

    def group(m: re.Match[str]) -> str:
        nonlocal ambiguous
        lead, groups, fraction = m.group(1), m.group(2), m.group(3) or ""
        if fraction or groups.count(",") > 1:  # "1,000.5", "1,000,000": only thousands make sense
            return lead + groups.replace(",", "") + fraction
        if lead.startswith("0"):  # "0,100": a thousands group never follows a leading 0
            return m.group(0)
        if thousands is None:
            ambiguous = True
            return m.group(0)
        return lead + groups.replace(",", "") if thousands else m.group(0)

    resolved = _COMMA_GROUPS.sub(group, text)
    if ambiguous:
        return None
    return _DECIMAL_COMMA.sub(".", resolved)


def ambiguous_thousands(text: str | None) -> bool:
    """Whether ``text`` contains a number whose comma may be a thousands separator or a decimal comma
    ("1,000µF", "10,000 pF", "2,200 uF", "32,768 Hz") – see :func:`resolve_commas`."""
    if not text:
        return False
    compact = str(text).replace(" ", "").replace(" ", "").replace(" ", "")
    return resolve_commas(compact) is None and resolve_commas(compact, True) is not None


def _clean(text: str, thousands: bool | None = None) -> str | None:
    """Input without blanks and ``±``, commas resolved (:func:`resolve_commas`); ``None`` = ambiguous."""
    t = text.strip()
    t = t.replace(" ", "").replace(" ", "").replace(" ", "")
    t = t.replace("±", "").replace("+/-", "")
    t = t.replace("Ω", "Ω")  # OHM SIGN -> GREEK CAPITAL OMEGA
    return resolve_commas(t, thousands)


_RKM_RE = re.compile(r"^(?P<a>\d*)(?P<letter>[RrEkKMGmunpµμfVAW])(?P<b>\d+)(?P<unit>[A-Za-zΩ°/%]*)$")
_NUM_RE = re.compile(
    r"^(?P<num>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"(?P<rest>.*)$"
)
_FRACTION_RE = re.compile(r"^(?P<n>\d+)/(?P<d>\d+)(?P<rest>.*)$")


def _split_prefix_unit(rest: str, default_unit: str | None) -> tuple[float, str] | None:
    """Split a suffix like "kΩ", "nF", "Meg", "mA", "R", "" into (multiplier, unit).

    The default (field) unit itself is never read as a prefix: "6500K" in a kelvin field is
    6500 K (not 6.5 MK), "5T" in a tesla field 5 T – otherwise every re-normalisation of a
    stored value would multiply it. The same holds for a lone "k" in a kelvin field
    ("6500k" = 6500 K); other units keep "k" as kilo ("10k" ohm = 10 kΩ).
    """
    default = normalize_unit(default_unit)
    if rest == "":
        return 1.0, default
    if rest in ("C", "c") and default == "°C":
        return 1.0, "°C"  # "125C" in a temperature field means °C, not coulomb
    if rest == "k" and default == "K":
        return 1.0, "K"  # "6500k" in a kelvin field is 6500 K (kilokelvin is written "kK")
    if default and normalize_unit(rest) == default:
        return 1.0, default
    lower = rest.lower()
    if lower.startswith("meg"):
        unit_part = rest[3:]
        return 1e6, normalize_unit(unit_part) or normalize_unit(default_unit)
    # whole rest is a unit (e.g. "Ω", "V", "ohm", "%", "ppm/K", "R")
    canonical = normalize_unit(rest)
    if canonical != rest or rest in UNIT_ALIASES:
        return 1.0, canonical
    # prefix + unit (e.g. "kΩ", "nF", "mA", "µH", "kHz", "kohm")
    first = rest[0]
    if first in PREFIXES and first != "":
        unit_part = rest[1:]
        canonical = normalize_unit(unit_part) if unit_part else default
        if unit_part == "" or canonical != unit_part or unit_part in UNIT_ALIASES or (default and canonical == default):
            return PREFIXES[first], canonical
    return None


def _finite(q: Quantity | None) -> Quantity | None:
    return q if q is not None and math.isfinite(q.value) else None


def parse_quantity(
    text: str | float | int | None, default_unit: str | None = None, *, thousands: bool | None = None
) -> Quantity | None:
    """Parse engineering notation into a :class:`Quantity`.

    Returns ``None`` if the text cannot be interpreted (or is not a finite number).
    ``default_unit`` is used when the text carries no unit ("10k" with default "Ω" -> 10000 Ω).
    ``thousands``: how to read an ambiguous comma group ("1,000µF") – ``None`` (unknown source)
    gives ``None``, ``True`` thousands separator (English source), ``False`` decimal comma
    (see :func:`resolve_commas`).
    """
    if text is None or isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return _finite(Quantity(float(text), normalize_unit(default_unit)))
    t = _clean(str(text), thousands)
    if not t:
        return None
    return _finite(_parse_text(t, default_unit))


def _parse_text(t: str, default_unit: str | None) -> Quantity | None:
    # Fractions such as "1/16W"
    m = _FRACTION_RE.match(t)
    if m:
        denominator = int(m.group("d"))
        if denominator == 0:
            return None
        frac = float(Fraction(int(m.group("n")), denominator))
        split = _split_prefix_unit(m.group("rest"), default_unit)
        if split is None:
            return None
        mult, unit = split
        return Quantity(frac * mult, unit)

    # RKM / letter-as-decimal-point codes: 4k7, 4R7, R47, 2u2, 1M5, 6V3 (0R is handled below)
    m = _RKM_RE.match(t)
    if m:
        letter = m.group("letter")
        a = m.group("a") or "0"
        b = m.group("b")
        unit_suffix = m.group("unit")
        if letter in ("R", "r", "E"):
            mult, unit = 1.0, "Ω"
        elif letter in ("V", "A", "W"):  # 6V3 = 6.3 V, 2A5 = 2.5 A
            mult, unit = 1.0, letter
        else:
            mult = PREFIXES.get(letter, 1.0)
            unit = normalize_unit(unit_suffix) if unit_suffix else normalize_unit(default_unit)
        if letter in ("R", "r", "E") and unit_suffix:
            unit = normalize_unit(unit_suffix)
        return Quantity(float(f"{a}.{b}") * mult, unit)

    m = _NUM_RE.match(t)
    if not m:
        return None
    num = float(m.group("num"))
    rest = m.group("rest")
    # "0R", "100R", "10RΩ"
    if rest[:1] in ("R", "r") and (len(rest) == 1 or normalize_unit(rest[1:]) == "Ω"):
        return Quantity(num, "Ω")
    split = _split_prefix_unit(rest, default_unit)
    if split is None:
        return None
    mult, unit = split
    return Quantity(num * mult, unit)


def parse_value(
    text: str | float | int | None, default_unit: str | None = None, *, thousands: bool | None = None
) -> float | None:
    """Convenience wrapper returning only the numeric base-unit value."""
    q = parse_quantity(text, default_unit, thousands=thousands)
    return None if q is None else q.value


def parse_range(
    text: str | None, default_unit: str | None = None, *, thousands: bool | None = None
) -> tuple[float, float] | None:
    """Parse ranges such as "-55°C ... +155°C", "-40 to 125 °C", "1Ω - 10MΩ"."""
    if not text:
        return None
    t = str(text).strip()
    parts = re.split(r"\s*(?:\.\.\.|…|\bto\b|\bbis\b|~|(?<=[\dΩa-zA-Z%°])\s*-\s*(?=[-+]?\d))\s*", t)
    parts = [p for p in parts if p and p.strip()]
    if len(parts) != 2:
        return None
    unit = default_unit
    second = parse_quantity(parts[1], unit, thousands=thousands)
    if second is not None and second.unit:
        unit = second.unit
    first = parse_quantity(parts[0], unit, thousands=thousands)
    if first is None or second is None:
        return None
    return first.value, second.value


# --------------------------------------------------------------------------- formatting


def significant_digits(value: float, digits: int = 3) -> float:
    """``value`` rounded to ``digits`` significant digits (0 and non-finite values unchanged)."""
    if value == 0 or not math.isfinite(value):
        return value
    return round(value, -math.floor(math.log10(abs(value))) + (digits - 1))


def exact_digits(value: float) -> int:
    """Smallest number of significant digits (3 … 9) that represents ``value`` exactly."""
    if value == 0 or not math.isfinite(value):
        return _EXACT_MIN_DIGITS
    for digits in range(_EXACT_MIN_DIGITS, _EXACT_MAX_DIGITS + 1):
        if math.isclose(significant_digits(value, digits), value, rel_tol=1e-9):
            return digits
    return _EXACT_MAX_DIGITS


def _plain(value: float, digits: int) -> str:
    """Decimal text with at most ``digits`` significant digits, no exponent, trailing zeros dropped."""
    if value == 0:
        return "0"
    magnitude = math.floor(math.log10(abs(value)))
    decimals = max(0, digits - 1 - magnitude)
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in ("-0", ""):
        text = "0"
    return text


def _engineering(value: float, digits: int, min_exp: int, max_exp: int) -> tuple[str, int]:
    """Mantissa text and engineering exponent (multiple of 3, clamped) of a rounded value."""
    if value == 0:
        return "0", 0
    exp3 = int(math.floor(math.log10(abs(value)) / 3) * 3)
    exp3 = max(min_exp, min(max_exp, exp3))
    text = _plain(value / 10**exp3, digits)
    if abs(float(text)) >= 1000 and exp3 + 3 <= max_exp:  # 999.9996 -> "1000" -> next prefix
        exp3 += 3
        text = _plain(value / 10**exp3, digits)
    return text, exp3


def format_quantity(
    value: float | None,
    unit: str = "",
    *,
    digits: int | None = 6,
    space: bool = False,
    prefixes: bool = True,
    plus_minus: bool = False,
    min_exp: int = _MIN_EXP,
    max_exp: int = _MAX_EXP,
) -> str:
    """Format a value in the house style: 4700, "Ω" -> "4.7kΩ"; 1e-7, "F" -> "100nF";
    32768, "Hz" -> "32.768kHz"; 0.25, "W" -> "0.25W"; 1, "%", plus_minus=True -> "±1%".

    ``digits`` = maximum significant digits (trailing zeros dropped), ``None`` = exact
    (:func:`exact_digits`). Units in :data:`NO_PREFIX_UNITS` are never prefixed, power
    only below 0.1 W. ``plus_minus`` writes "±" before non-negative values (tolerances).
    """
    if value is None:
        return ""
    unit = normalize_unit(unit)
    sep = " " if space else ""
    if not math.isfinite(value):
        return f"{value}{sep}{unit}"
    sign = "±" if plus_minus and value >= 0 else ""
    if value == 0:
        return f"{sign}0{sep}{unit}"
    places = exact_digits(value) if digits is None else max(1, int(digits))
    v = significant_digits(value, places)
    no_prefix = (
        not prefixes
        or unit in NO_PREFIX_UNITS
        or (unit == "W" and abs(value) >= _POWER_PREFIX_LIMIT)
    )
    if no_prefix:
        return f"{sign}{_plain(v, places)}{sep}{unit}"
    text, exp3 = _engineering(v, places, min_exp, max_exp)
    return f"{sign}{text}{sep}{_SI_SYMBOLS.get(exp3, '')}{unit}"


def format_rkm(
    value: float | None,
    unit: str = "Ω",
    *,
    upper: bool = True,
    digits: int | None = 3,
    ohm_letter: str = "R",
) -> str:
    """IEC 60062 letter-and-digit code.

    Resistance: 4700 -> "4K7" (``upper=False``: "4k7"), 100 -> "100R", 0.47 -> "R47", 0 -> "0R".
    Other units use the prefix letter as decimal marker (100 nF -> "100n", 2.2 µF -> "2u2")
    and single-letter units without prefix their own letter (6.3 V -> "6V3", 10 V -> "10V").
    Units that never take a prefix (:data:`NO_PREFIX_UNITS`: "0.5%", "12.5°C", "6500K") and
    other multi-letter units without prefix ("1.5Hz") keep the decimal point, so the code can
    be read back. ``digits`` = maximum significant digits, ``None`` = exact.
    """
    if value is None:
        return ""
    unit = normalize_unit(unit)
    is_ohm = unit == "Ω"
    if value == 0:
        return f"0{ohm_letter}" if is_ohm else f"0{unit}"
    if not math.isfinite(value):
        return f"{value}{unit}"
    places = exact_digits(value) if digits is None else max(1, int(digits))
    v = significant_digits(value, places)
    sign = "-" if v < 0 else ""
    magnitude = abs(v)
    if unit in NO_PREFIX_UNITS:
        return f"{sign}{_plain(magnitude, places)}{unit}"
    if is_ohm and magnitude < 1:
        # sub-ohm values use the R as decimal point: 0.47 -> R47, 0.047 -> R047
        frac = _plain(magnitude, places)
        return f"{sign}{ohm_letter}{frac.split('.', 1)[1] if '.' in frac else frac}"
    text, exp3 = _engineering(magnitude, places, _MIN_EXP, _MAX_EXP)
    if exp3 == 0:
        if not is_ohm and unit and unit not in RKM_UNIT_LETTERS:
            return f"{sign}{text}{unit}"  # "1.5Hz", "290V/µs": no letter can serve as decimal marker
        letter = ohm_letter if is_ohm else (unit or ".")
    elif exp3 == 3:
        letter = "K" if upper else "k"
    else:
        letter = _RKM_SYMBOLS.get(exp3, "")
    if "." in text:
        whole, frac = text.split(".", 1)
        return f"{sign}{whole}{letter}{frac}"
    return f"{sign}{text}{letter}"


_POWER_FRACTIONS = {
    1 / 50: "1/50W",
    1 / 32: "1/32W",
    1 / 20: "1/20W",
    1 / 16: "1/16W",
    1 / 10: "1/10W",
    1 / 8: "1/8W",
    1 / 4: "1/4W",
    1 / 3: "1/3W",
    1 / 2: "1/2W",
    3 / 4: "3/4W",
}


def format_power(watts: float | None, *, style: str = "decimal", digits: int | None = 6) -> str:
    """Format a power rating: style "decimal" -> "0.1W"/"62.5mW", "fraction" -> "1/16W"."""
    if watts is None:
        return ""
    if style == "fraction":
        for frac, text in _POWER_FRACTIONS.items():
            if math.isclose(watts, frac, rel_tol=1e-3):
                return text
    return format_quantity(watts, "W", digits=digits)
