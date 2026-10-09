"""Small drawing API used by the standard-symbol and IC generators.

Coordinates are mil, +Y up. Pins are validated on creation (10-mil raster, row on the
grid, tip on the grid); graphics get explicit house-style colours so the resulting
:class:`~partforge.geometry.model.SymbolSpec` is self-contained.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..geometry.model import (
    ElectricalType,
    LineWidth,
    PinOrientation,
    Point,
    SymArc,
    SymbolSpec,
    SymEllipse,
    SymGraphic,
    SymLine,
    SymPin,
    SymPolygon,
    SymRect,
    SymText,
    TextJustify,
    TextPos,
)
from .style import RASTER, GraphicStyle, StyleKit

__all__ = ["XY", "SymbolBuilder", "text_pos"]

XY = tuple[float, float]


def text_pos(value: Any) -> TextPos | None:
    """``{"x", "y", "justify"}`` (generator ``text_positions`` entry) as :class:`TextPos`, else ``None``."""
    if not isinstance(value, Mapping):
        return None
    try:
        return TextPos(x=int(value["x"]), y=int(value["y"]), justify=value.get("justify", "bottom_left"))
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def _num(v: float) -> float:
    """Normalise -0.0 and float noise (graphics may be on a 5-mil raster)."""
    out = round(float(v), 4)
    return 0.0 if out == 0 else out


class SymbolBuilder:
    """Collects pins and graphics of one symbol."""

    def __init__(self, kit: StyleKit, *, part_count: int = 1, graphic: GraphicStyle | None = None) -> None:
        self.kit = kit
        self.part_count = part_count
        self.graphic = graphic or kit.discrete
        self.pins: list[SymPin] = []
        self.graphics: list[SymGraphic] = []

    # ------------------------------------------------------------------ graphics
    def _base(self, part: int, color: str | None, width: LineWidth | None, fill: str | None = None) -> dict[str, Any]:
        return {
            "part": part,
            "color": color or self.graphic.color,
            "line_width": width or self.graphic.width,
            "fill_color": fill,
        }

    def line(self, *points: XY, part: int = 1, color: str | None = None, width: LineWidth | None = None) -> None:
        """Open polyline through ``points`` (two points = simple line)."""
        if len(points) < 2:
            raise ValueError("Linie braucht mindestens zwei Punkte")
        self.graphics.append(
            SymLine(points=[Point(x=_num(x), y=_num(y)) for x, y in points], **self._base(part, color, width))
        )

    def polygon(
        self,
        *points: XY,
        part: int = 1,
        filled: bool = True,
        color: str | None = None,
        fill: str | None = None,
        width: LineWidth | None = None,
    ) -> None:
        if len(points) < 3:
            raise ValueError("Polygon braucht mindestens drei Punkte")
        fill_color = (fill or self.graphic.fill) if filled else None
        self.graphics.append(
            SymPolygon(
                points=[Point(x=_num(x), y=_num(y)) for x, y in points],
                filled=filled,
                **self._base(part, color, width, fill_color),
            )
        )

    def rect(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        part: int = 1,
        filled: bool = False,
        color: str | None = None,
        fill: str | None = None,
        width: LineWidth | None = None,
    ) -> None:
        fill_color = (fill or self.graphic.fill) if filled else None
        self.graphics.append(
            SymRect(
                x1=_num(min(x1, x2)),
                y1=_num(min(y1, y2)),
                x2=_num(max(x1, x2)),
                y2=_num(max(y1, y2)),
                filled=filled,
                **self._base(part, color, width, fill_color),
            )
        )

    def arc(
        self,
        cx: float,
        cy: float,
        r: float,
        start: float,
        end: float,
        *,
        part: int = 1,
        color: str | None = None,
        width: LineWidth | None = None,
    ) -> None:
        """Arc counter-clockwise from ``start`` to ``end`` degrees (0 = +X)."""
        self.graphics.append(
            SymArc(
                cx=_num(cx), cy=_num(cy), r=_num(r), start=_num(start), end=_num(end), **self._base(part, color, width)
            )
        )

    def circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        part: int = 1,
        filled: bool = False,
        color: str | None = None,
        fill: str | None = None,
        width: LineWidth | None = None,
    ) -> None:
        fill_color = (fill or self.graphic.fill) if filled else None
        self.graphics.append(
            SymEllipse(
                cx=_num(cx),
                cy=_num(cy),
                rx=_num(r),
                ry=_num(r),
                filled=filled,
                **self._base(part, color, width, fill_color),
            )
        )

    def text(
        self,
        x: float,
        y: float,
        value: str,
        *,
        part: int = 1,
        justify: TextJustify = "middle_center",
        color: str | None = None,
    ) -> None:
        """Free text (written as an Altium *label*, font 1 = house font)."""
        self.graphics.append(
            SymText(
                x=_num(x),
                y=_num(y),
                text=value,
                size=self.kit.font_size,
                justify=justify,
                **self._base(part, color, None),
            )
        )

    # ------------------------------------------------------------------ composite glyphs
    def plus_sign(self, cx: float, cy: float, half: float = 20, *, part: int = 1, color: str | None = None) -> None:
        self.line((cx - half, cy), (cx + half, cy), part=part, color=color)
        self.line((cx, cy - half), (cx, cy + half), part=part, color=color)

    def minus_sign(self, cx: float, cy: float, half: float = 20, *, part: int = 1, color: str | None = None) -> None:
        self.line((cx - half, cy), (cx + half, cy), part=part, color=color)

    def arrow_head(
        self, tip: XY, direction: tuple[int, int], length: float = 30, half_width: float = 10, *, part: int = 1
    ) -> None:
        """Filled arrow head with its point at ``tip``.

        ``direction`` is an integer vector with components in -1..1 (axis-aligned or 45°);
        with integer ``length``/``half_width`` the corners stay on the raster.
        """
        dx, dy = direction
        px, py = -dy, dx  # perpendicular
        bx, by = tip[0] - length * dx, tip[1] - length * dy
        self.polygon(
            tip, (bx + half_width * px, by + half_width * py), (bx - half_width * px, by - half_width * py), part=part
        )

    def arrow(self, tail: XY, tip: XY, *, part: int = 1, length: float = 20, half_width: float = 10) -> None:
        """Line from ``tail`` to ``tip`` with a filled head at ``tip`` (axis-aligned or 45°)."""
        dx = (tip[0] > tail[0]) - (tip[0] < tail[0])
        dy = (tip[1] > tail[1]) - (tip[1] < tail[1])
        self.line(tail, tip, part=part)
        self.arrow_head(tip, (dx, dy), length, half_width, part=part)

    def dashed(self, a: XY, b: XY, dash: float = 20, gap: float = 20, *, part: int = 1) -> None:
        """Dashed straight line (individual segments)."""
        (x1, y1), (x2, y2) = a, b
        length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if length == 0:
            return
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        pos = 0.0
        while pos < length - 1e-6:
            end = min(pos + dash, length)
            self.line((x1 + ux * pos, y1 + uy * pos), (x1 + ux * end, y1 + uy * end), part=part)
            pos = end + gap

    # ------------------------------------------------------------------ pins
    def pin(
        self,
        designator: str,
        name: str,
        x: int,
        y: int,
        orientation: PinOrientation,
        *,
        length: int | None = None,
        electrical: ElectricalType = "passive",
        part: int = 1,
        show_name: bool = False,
        show_designator: bool = False,
        hidden: bool = False,
        description: str | None = None,
        group: str | None = None,
    ) -> SymPin:
        """Add a pin; ``length=None`` fits the discrete pin length so the tip lands on the grid."""
        if length is None:
            length = self.kit.fit_pin_length(x, y, orientation)
        pin = SymPin(
            designator=str(designator),
            name=name,
            x=int(x),
            y=int(y),
            orientation=orientation,
            length=int(length),
            electrical=electrical,
            part=part,
            show_name=show_name,
            show_designator=show_designator,
            hidden=hidden,
            description=description,
            group=group,
        )
        self._check_pin(pin)
        self.pins.append(pin)
        return pin

    def stacked_pins(
        self,
        designators: Sequence[str],
        name: str,
        x: int,
        y: int,
        orientation: PinOrientation,
        **kwargs: Any,
    ) -> list[SymPin]:
        """One pin per designator at the same location (Altium stacked pins: one net, several pads)."""
        length = kwargs.pop("length", None)
        if length is None:
            length = self.kit.fit_pin_length(x, y, orientation)
        return [self.pin(d, name, x, y, orientation, length=length, **kwargs) for d in designators]

    def _check_pin(self, pin: SymPin) -> None:
        tip_x, tip_y = pin.tip()
        for label, value in (
            ("x", pin.x),
            ("y", pin.y),
            ("Länge", pin.length),
            ("Spitze x", tip_x),
            ("Spitze y", tip_y),
        ):
            if value % RASTER:
                raise ValueError(f"Pin {pin.designator}: {label}={value} liegt nicht im {RASTER}-mil-Raster")
        if pin.length <= 0:
            raise ValueError(f"Pin {pin.designator}: Länge muss positiv sein")
        if not pin.hidden and (tip_x % self.kit.grid or tip_y % self.kit.grid):
            raise ValueError(
                f"Pin {pin.designator}: Spitze ({tip_x}, {tip_y}) liegt nicht im {self.kit.grid}-mil-Raster"
            )

    # ------------------------------------------------------------------ output
    def extend(self, graphics: Iterable[SymGraphic]) -> None:
        self.graphics.extend(graphics)

    def build(
        self,
        *,
        name: str,
        description: str,
        prefix: str,
        generator: dict[str, Any] | None = None,
        comment: str = "*",
    ) -> SymbolSpec:
        """The finished spec; ``generator["text_positions"]`` also fills ``designator_pos``/``comment_pos``."""
        positions = (generator or {}).get("text_positions")
        positions = positions if isinstance(positions, Mapping) else {}
        return SymbolSpec(
            name=name,
            description=description,
            designator_prefix=prefix,
            comment=comment,
            designator_pos=text_pos(positions.get("designator")),
            comment_pos=text_pos(positions.get("comment")),
            part_count=self.part_count,
            pins=list(self.pins),
            graphics=list(self.graphics),
            generator=generator,
        )
