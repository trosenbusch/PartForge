"""Value codes inside manufacturer part numbers: encode a value, decode a code, match it.

Styles (``ValueFormat.style``)::

    rkm      letter as decimal point, shortest form   10K, 4K7, 100R, 1M, 10K2, R47   (Yageo RC_L)
    rkm4     letter as decimal point, always 3 digits 10K0, 4K70, 100R, 1M00, R100   (Vishay CRCW, Stackpole)
    eia3     2 significant digits + number of zeros   103, 4R7, R47, 104 (pF), 1R0   (5 % resistors, MLCC, µH)
    eia4     3 significant digits + number of zeros   1002, 10R0, 1R00, R100         (1 % resistors)
    uniohm4  4 characters, multiplier digit or letter 1002, 100J, 470K, 0103 (2-digit mode with leading 0)

``ValueFormat.scale`` is the value of one code unit in base units: 1 for Ω, ``1e-12`` for
pF capacitance codes, ``1e-6`` for µH inductance codes. All functions work with values in
base units (Ω, F, H) and raise :class:`ValueCodeError` (German message) when a value cannot
be represented exactly (e.g. 4.99 kΩ in a 2-digit code).
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    "ValueCodeError",
    "ValueFormat",
    "ValueStyle",
    "decode_value",
    "encode_value",
    "value_regex",
]

ValueStyle = Literal["rkm", "rkm4", "eia3", "eia4", "uniohm4"]

_RKM_LETTERS: dict[str, int] = {"R": 0, "K": 3, "M": 6, "G": 9}
_UNIOHM_NEGATIVE: dict[str, int] = {"J": -1, "K": -2, "L": -3, "M": -4, "N": -5, "P": -6}
_REL = 1e-9
#: Largest |exponent| of a letter or small multiplier (10^±24 covers yocto … yotta in any code unit).
MAX_EXPONENT = 24
_LETTER_RE = re.compile(r"[A-Z]")


class ValueCodeError(ValueError):
    """A value cannot be written as (or read from) a part-number value code."""


class ValueFormat(BaseModel):
    """How the value of a part (resistance, capacitance, inductance …) is written in the MPN."""

    style: ValueStyle
    scale: float = Field(default=1.0, gt=0, description="Wert einer Code-Einheit in Basiseinheiten (pF = 1e-12)")
    digits: int | None = Field(default=None, ge=1, le=4, description="Signifikante Stellen (uniohm4: 2 oder 3)")
    small_multipliers: dict[str, int] = Field(
        default_factory=dict,
        description="eia3: Multiplikator-Ziffern für Werte < 10 Code-Einheiten statt R, "
                    "z. B. {'9': -1, '8': -2} (KEMET)",
    )
    letters: dict[str, int] = Field(default_factory=lambda: dict(_RKM_LETTERS),
                                    description="rkm/rkm4: Buchstabe (A–Z) → Zehnerexponent, z. B. R = 0, K = 3")

    @model_validator(mode="after")
    def _check(self) -> ValueFormat:
        if self.style == "uniohm4" and self.digits not in (None, 2, 3):
            raise ValueError("uniohm4 erlaubt nur 2 oder 3 signifikante Stellen.")
        for code, exponent in self.small_multipliers.items():
            if not re.fullmatch(r"\d", code):
                raise ValueError(f"Multiplikator-Code „{code}“ muss eine Ziffer sein.")
            if not -MAX_EXPONENT <= exponent <= MAX_EXPONENT:
                raise ValueError(f"Multiplikator-Code „{code}“: Exponent {exponent} liegt außerhalb von "
                                 f"±{MAX_EXPONENT}.")
        if self.style in ("rkm", "rkm4"):
            self.letters = _checked_letters(self.letters)
        return self

    def significant(self) -> int:
        """Number of significant digits the style writes."""
        if self.digits:
            return self.digits
        return {"rkm": 3, "rkm4": 3, "eia3": 2, "eia4": 3, "uniohm4": 3}[self.style]

    def key(self) -> tuple[object, ...]:
        """Hashable identity (used for caching)."""
        return (self.style, self.scale, self.digits, tuple(sorted(self.small_multipliers.items())),
                tuple(sorted(self.letters.items())))


# --------------------------------------------------------------------------- helpers


def _checked_letters(letters: dict[str, int]) -> dict[str, int]:
    """Decimal-point letters of an rkm format: one upper-case letter A–Z each, unique letters and
    exponents (German ValueError otherwise). Lower-case input is accepted and stored upper case."""
    if not letters:
        raise ValueError("Das Werteformat „rkm“/„rkm4“ braucht Buchstaben als Dezimalpunkt "
                         "(z. B. R = 0, K = 3, M = 6).")
    out: dict[str, int] = {}
    for key, exponent in letters.items():
        letter = str(key).strip().upper()
        if not _LETTER_RE.fullmatch(letter):
            raise ValueError(f"„{key}“ ist kein gültiger Buchstabe für das Werteformat (genau ein Buchstabe A–Z).")
        if letter in out:
            raise ValueError(f"Buchstabe „{letter}“ ist im Werteformat doppelt definiert.")
        if not -MAX_EXPONENT <= exponent <= MAX_EXPONENT:
            raise ValueError(f"Buchstabe „{letter}“: Exponent {exponent} liegt außerhalb von ±{MAX_EXPONENT}.")
        out[letter] = exponent
    exponents = list(out.values())
    if len(set(exponents)) != len(exponents):
        raise ValueError("Zwei Buchstaben des Werteformats haben denselben Zehnerexponenten.")
    return out


def _units(value: float, fmt: ValueFormat) -> float:
    """Value in code units with float noise removed (12 significant digits)."""
    if value is None or not math.isfinite(value):
        raise ValueCodeError("Ungültiger Wert.")
    units = value / fmt.scale
    if units == 0:
        return 0.0
    return float(f"{units:.12g}")


def _sig(units: float, digits: int) -> tuple[int, int]:
    """(integer mantissa with ``digits`` digits, exponent) with mantissa * 10**exp == units."""
    exp = math.floor(math.log10(units)) - (digits - 1)
    mantissa = round(units / 10.0**exp)
    if mantissa >= 10**digits:  # 9.995 -> 10.0
        mantissa //= 10
        exp += 1
    return mantissa, exp


def _exact(mantissa: int, exp: int, units: float) -> bool:
    return math.isclose(mantissa * 10.0**exp, units, rel_tol=_REL)


def _not_exact(units_text: str, fmt: ValueFormat) -> ValueCodeError:
    return ValueCodeError(
        f"Der Wert {units_text} lässt sich im Code ({fmt.style}, {fmt.significant()} Stellen) nicht exakt darstellen."
    )


def _fmt_units(units: float) -> str:
    """Readable number for messages: plain digits in the usual range (1234000, 0.047), else 1.2e+12."""
    if 1e-4 <= abs(units) < 1e10:
        return f"{units:.6f}".rstrip("0").rstrip(".")
    return f"{units:.6g}"


# --------------------------------------------------------------------------- encode


def _encode_rkm(units: float, fmt: ValueFormat, fixed: bool) -> str:
    digits = fmt.significant()
    letters = sorted(fmt.letters.items(), key=lambda kv: kv[1])
    mantissa, exp = _sig(units, digits)
    if not _exact(mantissa, exp, units):
        raise _not_exact(_fmt_units(units), fmt)
    # letter: largest exponent <= magnitude (values below 1 use the smallest letter, "R47")
    magnitude = math.floor(math.log10(units))
    letter, letter_exp = letters[0]
    for name, e in letters:
        if magnitude >= e:
            letter, letter_exp = name, e
    if magnitude >= letter_exp + 3:
        raise ValueCodeError(f"Der Wert {_fmt_units(units)} ist für den Code zu groß.")
    digits_text = str(mantissa)
    # position of the decimal point relative to the digit string
    point = (exp - letter_exp) + len(digits_text)
    if point <= 0:
        whole, frac = "", "0" * (-point) + digits_text
    elif point >= len(digits_text):
        whole, frac = digits_text + "0" * (point - len(digits_text)), ""
    else:
        whole, frac = digits_text[:point], digits_text[point:]
    if fixed:
        total = digits
        frac = (frac + "0" * total)[: max(0, total - len(whole))]
        if len(whole) + len(frac) != total or len(whole) > total:
            raise _not_exact(_fmt_units(units), fmt)
    else:
        frac = frac.rstrip("0")
        if not whole and not frac:
            whole = "0"
    return f"{whole}{letter}{frac}"


def _encode_eia(units: float, fmt: ValueFormat) -> str:
    digits = fmt.significant()
    mantissa, exp = _sig(units, digits)
    if not _exact(mantissa, exp, units):
        raise _not_exact(_fmt_units(units), fmt)
    if exp >= 0:
        if exp > 9:
            raise ValueCodeError(f"Der Wert {_fmt_units(units)} ist für den Code zu groß.")
        return f"{mantissa:0{digits}d}{exp}"
    for code, multiplier in sorted(fmt.small_multipliers.items(), key=lambda kv: -kv[1]):
        m, e = _sig(units, digits)
        if e == multiplier:
            return f"{m:0{digits}d}{code}"
        # mantissa with fewer digits shifted into the multiplier (e.g. 0.5 pF -> 50 x 10^-2)
        shifted = round(units / 10.0**multiplier)
        if 10 ** (digits - 1) <= shifted < 10**digits and _exact(shifted, multiplier, units):
            return f"{shifted:0{digits}d}{code}"
    # R as decimal point: digits+1 characters in total
    text = f"{mantissa}".rjust(digits, "0")
    point = len(text) + exp
    if point < 0:
        raise ValueCodeError(f"Der Wert {_fmt_units(units)} ist für den Code zu klein.")
    return f"{text[:point]}R{text[point:]}"


def _encode_uniohm(units: float, fmt: ValueFormat) -> str:
    digits = fmt.significant()
    mantissa, exp = _sig(units, digits)
    if not _exact(mantissa, exp, units):
        raise _not_exact(_fmt_units(units), fmt)
    if 0 <= exp <= 6:
        code = str(exp)
    else:
        code = next((k for k, v in _UNIOHM_NEGATIVE.items() if v == exp), "")
        if not code:
            raise ValueCodeError(f"Der Wert {_fmt_units(units)} liegt außerhalb des Codebereichs.")
    body = f"{mantissa:0{digits}d}"
    return (body if digits == 3 else "0" + body) + code


def encode_value(value: float, fmt: ValueFormat) -> str:
    """Code for ``value`` (base units). Raises :class:`ValueCodeError` if not representable."""
    if value is None or value <= 0:
        raise ValueCodeError("Nur positive Werte lassen sich codieren (Brücken haben einen eigenen Code).")
    units = _units(value, fmt)
    if fmt.style == "rkm":
        return _encode_rkm(units, fmt, fixed=False)
    if fmt.style == "rkm4":
        return _encode_rkm(units, fmt, fixed=True)
    if fmt.style in ("eia3", "eia4"):
        return _encode_eia(units, fmt)
    return _encode_uniohm(units, fmt)


# --------------------------------------------------------------------------- decode


def _decode_rkm(code: str, fmt: ValueFormat, fixed: bool) -> float:
    letters = "".join(sorted(fmt.letters))
    m = re.fullmatch(rf"(\d*)([{re.escape(letters)}])(\d*)", code)
    if not m or not (m.group(1) or m.group(3)):
        raise ValueCodeError(f"„{code}“ ist kein gültiger Wertcode.")
    if fixed and len(m.group(1)) + len(m.group(3)) != fmt.significant():
        raise ValueCodeError(f"„{code}“ hat nicht {fmt.significant()} Ziffern.")
    number = float(f"{m.group(1) or '0'}.{m.group(3) or '0'}")
    return number * 10.0 ** fmt.letters[m.group(2)]


def _decode_eia(code: str, fmt: ValueFormat) -> float:
    digits = fmt.significant()
    if "R" in code:
        if len(code) != digits + 1 or code.count("R") != 1 or not code.replace("R", "").isdigit():
            raise ValueCodeError(f"„{code}“ ist kein gültiger Wertcode.")
        return float(code.replace("R", "."))
    if len(code) != digits + 1 or not code.isdigit():
        raise ValueCodeError(f"„{code}“ ist kein gültiger Wertcode.")
    multiplier = code[-1]
    exp = fmt.small_multipliers.get(multiplier, int(multiplier))
    return int(code[:-1]) * 10.0**exp


def _decode_uniohm(code: str, fmt: ValueFormat) -> float:
    digits = fmt.significant()
    m = re.fullmatch(r"(\d{3})([0-6JKLMNP])", code)
    if not m:
        raise ValueCodeError(f"„{code}“ ist kein gültiger Wertcode.")
    body = m.group(1)
    if digits == 2 and not body.startswith("0"):
        raise ValueCodeError(f"„{code}“: im 2-stelligen Code beginnt der Wert mit 0.")
    exp = int(m.group(2)) if m.group(2).isdigit() else _UNIOHM_NEGATIVE[m.group(2)]
    return int(body) * 10.0**exp


def decode_value(code: str, fmt: ValueFormat) -> float:
    """Value in base units for a value code. Raises :class:`ValueCodeError`."""
    text = (code or "").strip().upper()
    if not text:
        raise ValueCodeError("Leerer Wertcode.")
    if fmt.style == "rkm":
        units = _decode_rkm(text, fmt, fixed=False)
    elif fmt.style == "rkm4":
        units = _decode_rkm(text, fmt, fixed=True)
    elif fmt.style in ("eia3", "eia4"):
        units = _decode_eia(text, fmt)
    else:
        units = _decode_uniohm(text, fmt)
    return float(f"{units * fmt.scale:.12g}")


# --------------------------------------------------------------------------- matching


@lru_cache(maxsize=256)
def _regex(style: str, digits: int, letters: str) -> str:
    if style == "rkm":
        return rf"(?:\d+[{letters}]\d*|[{letters}]\d+)"
    if style == "rkm4":
        alternatives = [rf"\d{{{a}}}[{letters}]\d{{{digits - a}}}" for a in range(digits, -1, -1)]
        return "(?:" + "|".join(alternatives) + ")"
    if style in ("eia3", "eia4"):
        alternatives = [rf"\d{{{digits + 1}}}"]
        alternatives += [rf"\d{{{a}}}R\d{{{digits - a}}}" for a in range(digits - 1, -1, -1)]
        return "(?:" + "|".join(alternatives) + ")"
    return r"\d{3}[0-6JKLMNP]"


def value_regex(fmt: ValueFormat) -> str:
    """Regular expression (no groups) matching every code of this format (upper case)."""
    letters = re.escape("".join(sorted(fmt.letters)))
    return _regex(fmt.style, fmt.significant(), letters)
