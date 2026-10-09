"""House-style helpers: :class:`~partforge.workspace.SymbolStyle` -> colours, line widths,
pin lengths, grid snapping and text metrics.

All values are sanitised once in :meth:`StyleKit.from_style`, so the generators can rely on
them: the grid divides 100 mil (10, 20, 50 or 100), IC pin lengths are a multiple of the
grid (pin tips stay on the grid when the body edges are on it) and colours are ``#RRGGBB``.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from typing import Literal

from ..geometry.model import LineWidth, PinOrientation
from ..workspace import SymbolStyle
from . import text as _text

log = logging.getLogger(__name__)

__all__ = [
    "ALLOWED_GRIDS",
    "MINUS_COLOR",
    "MIN_PIN_LENGTH",
    "PLUS_COLOR",
    "RASTER",
    "TEXT_COLOR",
    "GraphicStyle",
    "StyleKit",
    "resolve_style",
]

RASTER = 10  # mil: every pin coordinate/length is a multiple of this (writer: 10-mil units)
ALLOWED_GRIDS = (10, 20, 50, 100)  # the grid must divide 100 mil (house pin rows are 100 mil apart)
MIN_PIN_LENGTH = 10
MAX_PIN_LENGTH = 1000
TEXT_COLOR = "#000080"  # Altium designator/parameter text (house: 8388608)
PLUS_COLOR = "#EE0E22"  # house power-part "+" label (2232046)
MINUS_COLOR = "#11037F"  # house power-part "-" label (8323857)

_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_DEFAULTS = SymbolStyle()


def resolve_style(style: SymbolStyle | None) -> SymbolStyle:
    """``style`` itself, else the open workspace's symbol style, else the defaults."""
    if style is not None:
        return style
    from ..workspace import current_or_none  # runtime lookup, no import-time state

    ws = current_or_none()
    return ws.settings.symbol if ws is not None else SymbolStyle()


def _color(value: str, default: str, what: str) -> str:
    m = _HEX_RE.match(value.strip()) if isinstance(value, str) else None
    if not m:
        log.warning("Symbolstil: ungültige Farbe %s=%r, verwende %s", what, value, default)
        return default.upper()
    return "#" + m.group(1).upper()


@dataclass(frozen=True)
class GraphicStyle:
    """Colour/width set applied to one class of graphics."""

    color: str
    fill: str
    width: LineWidth


@dataclass(frozen=True)
class StyleKit:
    """Sanitised symbol house style plus geometry helpers (all lengths in mil)."""

    grid: int
    ic_pin_length: int
    discrete_pin_length: int
    ic_line_color: str
    ic_fill_color: str
    discrete_line_color: str
    pin_color: str
    line_width: LineWidth
    font: str
    font_size: int
    diode_pin1: Literal["cathode", "anode"]
    resistor_style: Literal["iec", "ansi"]

    # -- construction ------------------------------------------------------------------
    @classmethod
    def from_style(cls, style: SymbolStyle | None = None) -> StyleKit:
        s = resolve_style(style)
        grid = int(s.grid)
        if grid not in ALLOWED_GRIDS:
            log.warning("Symbolstil: Raster %s mil wird nicht unterstützt, verwende 100 mil", s.grid)
            grid = 100
        ic_len = max(grid, round(int(s.ic_pin_length) / grid) * grid)
        ic_len = min(ic_len, MAX_PIN_LENGTH)
        disc_len = max(MIN_PIN_LENGTH, round(int(s.discrete_pin_length) / RASTER) * RASTER)
        disc_len = min(disc_len, MAX_PIN_LENGTH)
        size = int(s.font_size) if 4 <= int(s.font_size) <= 72 else 10
        return cls(
            grid=grid,
            ic_pin_length=ic_len,
            discrete_pin_length=disc_len,
            ic_line_color=_color(s.ic_line_color, _DEFAULTS.ic_line_color, "ic_line_color"),
            ic_fill_color=_color(s.ic_fill_color, _DEFAULTS.ic_fill_color, "ic_fill_color"),
            discrete_line_color=_color(s.discrete_line_color, _DEFAULTS.discrete_line_color, "discrete_line_color"),
            pin_color=_color(s.pin_color, _DEFAULTS.pin_color, "pin_color"),
            line_width=s.line_width,
            font=s.font or _DEFAULTS.font,
            font_size=size,
            diode_pin1=s.diode_pin1,
            resistor_style=s.resistor_style,
        )

    # -- graphic classes ---------------------------------------------------------------
    @property
    def discrete(self) -> GraphicStyle:
        """Discrete symbols: blue lines, blue fill for solid shapes, house line width."""
        return GraphicStyle(self.discrete_line_color, self.discrete_line_color, self.line_width)

    @property
    def ic_body(self) -> GraphicStyle:
        """Box symbols: Altium default border/fill, LineWidth 0 (house: 'Smallest')."""
        return GraphicStyle(self.ic_line_color, self.ic_fill_color, "smallest")

    # -- grid helpers --------------------------------------------------------------------
    def ceil_grid(self, value: float, step: int | None = None) -> int:
        step = step or self.grid
        return math.ceil(round(value, 6) / step) * step

    def floor_grid(self, value: float, step: int | None = None) -> int:
        step = step or self.grid
        return math.floor(round(value, 6) / step) * step

    def on_grid(self, value: float) -> bool:
        return float(value).is_integer() and int(value) % self.grid == 0

    def fit_pin_length(self, x: int, y: int, orientation: PinOrientation, desired: int | None = None) -> int:
        """Pin length close to ``desired`` (default: discrete pin length) whose tip lies on the grid.

        ``x``/``y`` is the body-attach end (10-mil raster). Ties choose the shorter pin.
        """
        if x % RASTER or y % RASTER:
            raise ValueError(f"Pin-Anschlusspunkt ({x}, {y}) liegt nicht im {RASTER}-mil-Raster")
        want = self.discrete_pin_length if desired is None else int(desired)
        g = self.grid
        if orientation in ("left", "right"):
            coord, sign = x, (-1 if orientation == "left" else 1)
        else:
            coord, sign = y, (-1 if orientation == "down" else 1)
        base = (-sign * coord) % g  # length ≡ base (mod grid) puts the tip on the grid
        candidates = [base + k * g for k in range(MAX_PIN_LENGTH // g + 2)]
        candidates = [c for c in candidates if MIN_PIN_LENGTH <= c <= MAX_PIN_LENGTH]
        return min(candidates, key=lambda c: (abs(c - want), c))

    # -- text ------------------------------------------------------------------------------
    @property
    def em(self) -> float:
        return _text.em_mil(self.font_size)

    @property
    def cap_height(self) -> float:
        return _text.cap_height(font=self.font, size=self.font_size)

    def text_width(self, value: str) -> float:
        return _text.text_width(value, font=self.font, size=self.font_size)

    def as_dict(self) -> dict[str, object]:
        """Style values that influence the geometry (stored in ``SymbolSpec.generator``)."""
        return {
            "grid": self.grid,
            "ic_pin_length": self.ic_pin_length,
            "discrete_pin_length": self.discrete_pin_length,
            "line_width": self.line_width,
            "font": self.font,
            "font_size": self.font_size,
            "diode_pin1": self.diode_pin1,
            "resistor_style": self.resistor_style,
        }
