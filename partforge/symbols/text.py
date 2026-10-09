"""Text helpers for schematic symbols: Altium overbar syntax and glyph-width estimates.

Altium marks an active-low character with a backslash *after* it (``R\\E\\S\\E\\T\\``).
PartForge keeps that syntax verbatim in pin names; only measuring and rendering
strip the backslashes.

Widths are estimated from the Adobe core-font metrics (Times-Roman for Times New Roman,
which is metrically compatible, and Helvetica for Arial/sans fonts) in 1/1000 em.

Scale: Altium draws a schematic font of ``size`` points with an em of about
``size * 10`` mil (:data:`MIL_PER_POINT`). Calibrated on the user's house libraries:
the designator (y = 50 mil) and Comment (y = -150 mil) of the 200 x 80 mil resistor only
clear the body with a ~100 mil text cell, and a 1000 mil wide DAC box holds
``VREFIO``/``VOUT0`` names side by side.
"""

from __future__ import annotations

from functools import lru_cache

__all__ = [
    "MIL_PER_POINT",
    "cap_height",
    "display_text",
    "em_mil",
    "font_family",
    "has_overbar",
    "parse_overbar",
    "text_width",
]

# fmt: off
# Adobe Times-Roman advance widths (1/1000 em) for printable ASCII (" " .. "~").
_TIMES_ASCII = (
    250, 333, 408, 500, 500, 833, 778, 180, 333, 333, 500, 564, 250, 333, 250, 278,  # ' '..'/'
    500, 500, 500, 500, 500, 500, 500, 500, 500, 500, 278, 278, 564, 564, 564, 444,  # '0'..'?'
    921, 722, 667, 667, 722, 611, 556, 722, 722, 333, 389, 722, 611, 889, 722, 722,  # '@'..'O'
    556, 722, 667, 556, 611, 722, 722, 944, 722, 722, 611, 333, 278, 333, 469, 500,  # 'P'..'_'
    333, 444, 500, 444, 500, 444, 333, 500, 500, 278, 278, 500, 278, 778, 500, 500,  # '`'..'o'
    500, 500, 333, 389, 278, 500, 500, 722, 500, 500, 444, 480, 200, 480, 541,       # 'p'..'~'
)
# Adobe Helvetica advance widths (1/1000 em) for printable ASCII (" " .. "~").
_HELVETICA_ASCII = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
)
# fmt: on
# A few common non-ASCII characters (mapped to an ASCII look-alike for the width).
_FALLBACK_CHARS = {
    "µ": "u",
    "μ": "u",
    "Ω": "O",
    "°": "o",
    "±": "+",
    "ä": "a",
    "ö": "o",
    "ü": "u",
    "Ä": "A",
    "Ö": "O",
    "Ü": "U",
    "ß": "B",
    "–": "-",
    "−": "-",
    "·": ".",
}
_CAP_HEIGHT = {"times": 0.662, "helvetica": 0.718}  # cap height in em
MIL_PER_POINT = 10.0


def parse_overbar(name: str) -> list[tuple[str, bool]]:
    """Split an Altium pin name into ``(character, barred)`` pairs.

    ``"R\\E\\S\\E\\T\\"`` -> all five characters barred; ``"C\\S\\/A"`` -> C and S barred.
    Backslashes that do not follow a character (e.g. a leading one) are ignored.
    """
    out: list[tuple[str, bool]] = []
    i = 0
    n = len(name)
    while i < n:
        ch = name[i]
        if ch == "\\":
            i += 1
            continue
        barred = i + 1 < n and name[i + 1] == "\\"
        out.append((ch, barred))
        i += 2 if barred else 1
    return out


def display_text(name: str) -> str:
    """The visible text of a pin name (overbar backslashes removed)."""
    return "".join(ch for ch, _ in parse_overbar(name))


def has_overbar(name: str) -> bool:
    return any(barred for _, barred in parse_overbar(name))


def font_family(font: str) -> str:
    """Metric family for a font name: ``"times"`` (serif, default) or ``"helvetica"``."""
    f = font.lower()
    if any(key in f for key in ("arial", "helvetica", "sans", "verdana", "tahoma", "segoe", "calibri")):
        return "helvetica"
    return "times"


def em_mil(size: float) -> float:
    """Em size in mil for a font of ``size`` points (see :data:`MIL_PER_POINT`)."""
    return float(size) * MIL_PER_POINT


@lru_cache(maxsize=4096)
def _units(text: str, family: str) -> int:
    table = _HELVETICA_ASCII if family == "helvetica" else _TIMES_ASCII
    total = 0
    for ch in text:
        ch = _FALLBACK_CHARS.get(ch, ch)
        code = ord(ch)
        total += table[code - 32] if 32 <= code <= 126 else 500
    return total


def text_width(text: str, *, font: str = "Times New Roman", size: float = 10) -> float:
    """Estimated advance width (mil) of ``text`` (overbar syntax allowed) in the given font."""
    visible = display_text(text)
    if not visible:
        return 0.0
    return _units(visible, font_family(font)) / 1000.0 * em_mil(size)


def cap_height(*, font: str = "Times New Roman", size: float = 10) -> float:
    """Height of capital letters (mil)."""
    return _CAP_HEIGHT[font_family(font)] * em_mil(size)
