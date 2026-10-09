"""Render a :class:`~partforge.geometry.model.SymbolSpec` as SVG (thumbnails, previews, tests).

Themes:

* ``altium`` – white sheet and the colours stored in the spec (house style), black pins,
  navy designator/comment: what the symbol will look like in Altium;
* ``dark`` / ``light`` – PartForge UI palettes (transparent background, body fill in the
  accent colour), see ``docs/entwicklung/FRONTEND.md`` §3.

Coordinates: the SVG user unit is 1 mil with Y flipped (SVG y = -symbol y). Pin names with
Altium overbar syntax are drawn without backslashes plus explicit overbar lines; the text
is stretched to the estimated width (``textLength``) so the bars line up in every font.

Thumbnails (``thumbnail=True``, gallery cards and list previews): a sans-serif UI font instead of
the symbol font and one constant stroke width in screen pixels (``vector-effect:
non-scaling-stroke``), so lines stay crisp and equally strong at every displayed size.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal, get_args
from xml.sax.saxutils import escape, quoteattr

from ..geometry.model import (
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
)
from ..workspace import SymbolStyle
from . import text as _text
from .errors import SymbolError
from .style import TEXT_COLOR, StyleKit
from .util import MAX_PART_COUNT

__all__ = ["THEMES", "THUMBNAIL_FONT", "THUMBNAIL_STROKE_PX", "Theme", "render_parts", "render_svg", "render_thumbnail"]

Theme = Literal["altium", "dark", "light"]
THEMES: tuple[str, ...] = ("altium", "dark", "light")

_STROKE = {"smallest": 5.0, "small": 10.0, "medium": 20.0, "large": 30.0}
_PIN_STROKE = 10.0
#: Thumbnails: font stack of the PartForge UI and the constant stroke width in screen pixels.
THUMBNAIL_FONT = "Inter, 'Segoe UI', Arial, sans-serif"
THUMBNAIL_STROKE_PX = 1.25
_NAME_MARGIN = 50.0
_NUMBER_OFFSET = 40.0
_PART_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_JUSTIFY: frozenset[str] = frozenset(get_args(TextJustify))
COORD_RENDER_LIMIT = 1_000_000  # mil; anything beyond is broken data, not a symbol


@dataclass(frozen=True)
class _Palette:
    background: str | None
    line: str | None  # None = colour from the spec
    body_fill: str | None  # None = colour from the spec
    body_opacity: float
    pin: str
    pin_name: str
    pin_number: str
    label: str


_PALETTES: dict[str, _Palette] = {
    "altium": _Palette("#FFFFFF", None, None, 1.0, "#000000", "#000000", "#000000", TEXT_COLOR),
    "dark": _Palette(None, "#E8EBF2", "#FF8A3D", 0.14, "#9AA3B5", "#9AA3B5", "#7A8296", "#E8EBF2"),
    "light": _Palette(None, "#0E1320", "#E8681A", 0.12, "#4A5468", "#4A5468", "#697285", "#0E1320"),
}


def _f(v: float) -> str:
    """Compact number formatting (deterministic, max. 2 decimals)."""
    out = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


class _Bounds:
    def __init__(self) -> None:
        self.x1 = math.inf
        self.y1 = math.inf
        self.x2 = -math.inf
        self.y2 = -math.inf

    def add(self, x: float, y: float) -> None:
        self.x1, self.x2 = min(self.x1, x), max(self.x2, x)
        self.y1, self.y2 = min(self.y1, y), max(self.y2, y)

    def add_box(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.add(x1, y1)
        self.add(x2, y2)

    @property
    def empty(self) -> bool:
        return self.x1 > self.x2


def _arc_points(g: SymArc, steps: int = 36) -> list[tuple[float, float]]:
    start, end = g.start, g.end
    if end <= start:
        end += 360
    span = end - start
    n = max(2, math.ceil(span / 360 * steps) + 1)
    return [
        (
            g.cx + g.r * math.cos(math.radians(start + span * i / (n - 1))),
            g.cy + g.r * math.sin(math.radians(start + span * i / (n - 1))),
        )
        for i in range(n)
    ]


class _Renderer:
    def __init__(
        self,
        spec: SymbolSpec,
        theme: str,
        part: int,
        kit: StyleKit,
        labels: bool,
        show_hidden: bool,
        pin_color: str | None,
        thumbnail: bool = False,
    ) -> None:
        self.spec = spec
        self.thumbnail = thumbnail
        self.pal = _PALETTES[theme]
        self.theme = theme
        self.part = part
        self.kit = kit
        self.labels = labels
        self.show_hidden = show_hidden
        self.pin_color = pin_color if theme == "altium" and pin_color else self.pal.pin
        self.out: list[str] = []
        self.bounds = _Bounds()
        self.em = kit.em
        self.cap = kit.cap_height

    # -------------------------------------------------------------------- colours
    def stroke(self, g: SymGraphic) -> str:
        if self.pal.line is not None:
            return self.pal.line
        return g.color or self.kit.discrete_line_color

    def fill(self, g: SymGraphic, filled: bool) -> tuple[str, float]:
        if not filled:
            return "none", 1.0
        own = g.fill_color or g.color or self.kit.discrete_line_color
        solid = (g.fill_color or "").upper() == (g.color or "").upper() or g.fill_color is None
        if self.pal.line is None:
            return own, 1.0
        if solid:
            return self.pal.line, 1.0
        return self.pal.body_fill or own, self.pal.body_opacity

    def stroke_width(self, width: float) -> str:
        """``stroke-width`` attribute (mil), or the constant screen width of thumbnails."""
        if self.thumbnail:
            return f'stroke-width="{_f(THUMBNAIL_STROKE_PX)}" vector-effect="non-scaling-stroke"'
        return f'stroke-width="{_f(width)}"'

    # -------------------------------------------------------------------- graphics
    def graphic(self, g: SymGraphic) -> None:
        width = _STROKE.get(g.line_width, 10.0)
        stroke = self.stroke(g)
        common = f'stroke={quoteattr(stroke)} {self.stroke_width(width)} stroke-linejoin="round" stroke-linecap="round"'
        if isinstance(g, SymRect):
            fill, opacity = self.fill(g, g.filled)
            x1, x2 = sorted((g.x1, g.x2))
            y1, y2 = sorted((g.y1, g.y2))
            radius = f' rx="{_f(g.corner_radius)}"' if g.corner_radius else ""
            self.out.append(
                f'<rect x="{_f(x1)}" y="{_f(-y2)}" width="{_f(x2 - x1)}" height="{_f(y2 - y1)}"{radius} '
                f"fill={quoteattr(fill)}{self._opacity(opacity)} {common}/>"
            )
            self.bounds.add_box(x1, y1, x2, y2)
        elif isinstance(g, SymLine):
            pts = " ".join(f"{_f(p.x)},{_f(-p.y)}" for p in g.points)
            self.out.append(f'<polyline points="{pts}" fill="none" {common}/>')
            for p in g.points:
                self.bounds.add(p.x, p.y)
        elif isinstance(g, SymPolygon):
            fill, opacity = self.fill(g, g.filled)
            pts = " ".join(f"{_f(p.x)},{_f(-p.y)}" for p in g.points)
            self.out.append(f'<polygon points="{pts}" fill={quoteattr(fill)}{self._opacity(opacity)} {common}/>')
            for p in g.points:
                self.bounds.add(p.x, p.y)
        elif isinstance(g, SymArc):
            arc_pts = _arc_points(g)
            span = (g.end - g.start) % 360 if (g.end - g.start) % 360 else 360
            if span >= 359.999:
                self.out.append(f'<circle cx="{_f(g.cx)}" cy="{_f(-g.cy)}" r="{_f(g.r)}" fill="none" {common}/>')
            else:
                (sx, sy), (ex, ey) = arc_pts[0], arc_pts[-1]
                large = 1 if span > 180 else 0
                self.out.append(
                    f'<path d="M {_f(sx)} {_f(-sy)} A {_f(g.r)} {_f(g.r)} 0 {large} 0 {_f(ex)} {_f(-ey)}" '
                    f'fill="none" {common}/>'
                )
            for x, y in arc_pts:
                self.bounds.add(x, y)
        elif isinstance(g, SymEllipse):
            fill, opacity = self.fill(g, g.filled)
            self.out.append(
                f'<ellipse cx="{_f(g.cx)}" cy="{_f(-g.cy)}" rx="{_f(g.rx)}" ry="{_f(g.ry)}" '
                f"fill={quoteattr(fill)}{self._opacity(opacity)} {common}/>"
            )
            self.bounds.add_box(g.cx - g.rx, g.cy - g.ry, g.cx + g.rx, g.cy + g.ry)
        elif isinstance(g, SymText):
            color = self.pal.line if self.pal.line is not None else (g.color or TEXT_COLOR)
            self.text_at(g.x, g.y, g.text, color, g.justify, g.rotation, css="pf-text")

    @staticmethod
    def _opacity(value: float) -> str:
        return "" if value >= 1 else f' fill-opacity="{_f(value)}"'

    # -------------------------------------------------------------------- text
    def text_at(self, x: float, y: float, value: str, color: str, justify: str, rotation: int = 0, *, css: str) -> None:
        width = self.kit.text_width(value)
        vertical, horizontal = justify.split("_")
        anchor = {"left": "start", "center": "middle", "right": "end"}[horizontal]
        dx = {"start": 0.0, "middle": -width / 2, "end": -width}[anchor]
        if vertical == "bottom":
            dy = -0.2 * self.em  # baseline above the bottom edge of the text cell
        elif vertical == "top":
            dy = self.cap
        else:
            dy = self.cap / 2
        self._text_group(x, y, value, color, anchor, dx, dy, rotation, css)
        # bounds (unrotated approximation; free text is rarely rotated)
        baseline = y - dy  # symbol coordinates
        self.bounds.add_box(x + dx, baseline - 0.25 * self.em, x + dx + width, baseline + self.cap)

    def _text_group(
        self, x: float, y: float, value: str, color: str, anchor: str, dx: float, dy: float, rotation: int, css: str
    ) -> None:
        """Text (with overbars) at symbol point (x, y); ``dy`` = baseline offset in SVG units (down)."""
        visible = _text.display_text(value)
        if not visible:
            return
        width = self.kit.text_width(value)
        transform = f"translate({_f(x)} {_f(-y)})"
        if rotation:
            transform += f" rotate({_f(-rotation)})"
        parts = [f'<g transform="{transform}" class="{css}">']
        stretch = ""
        if _text.has_overbar(value):
            stretch = f' textLength="{_f(width)}" lengthAdjust="spacingAndGlyphs"'
        parts.append(
            f'<text x="0" y="{_f(dy)}" text-anchor="{anchor}" fill={quoteattr(color)} '
            f'font-size="{_f(self.em)}"{stretch}>{escape(visible)}</text>'
        )
        if _text.has_overbar(value):
            start = dx
            bar_y = dy - self.cap - 12
            chars = _text.parse_overbar(value)
            run_start: float | None = None
            pos = start
            for ch, barred in [*chars, ("", False)]:
                w = self.kit.text_width(ch) if ch else 0.0
                if barred and run_start is None:
                    run_start = pos
                if not barred and run_start is not None:
                    parts.append(
                        f'<line class="overbar" x1="{_f(run_start)}" y1="{_f(bar_y)}" x2="{_f(pos)}" y2="{_f(bar_y)}" '
                        f'stroke={quoteattr(color)} {self.stroke_width(8)}/>'
                    )
                    run_start = None
                pos += w
        parts.append("</g>")
        self.out.append("".join(parts))

    # -------------------------------------------------------------------- pins
    def pin(self, p: SymPin) -> None:
        tx, ty = p.tip()
        self.out.append(
            f'<line class="pin" x1="{_f(p.x)}" y1="{_f(-p.y)}" x2="{_f(tx)}" y2="{_f(-ty)}" '
            f'stroke={quoteattr(self.pin_color)} {self.stroke_width(_PIN_STROKE)} stroke-linecap="round"/>'
        )
        self.bounds.add(p.x, p.y)
        self.bounds.add(tx, ty)
        cap = self.cap
        if p.show_name and p.name:
            w = self.kit.text_width(p.name)
            if p.orientation == "left":
                self._text_group(p.x + _NAME_MARGIN, p.y, p.name, self.pal.pin_name, "start", 0, cap / 2, 0, "pin-name")
                self.bounds.add_box(p.x + _NAME_MARGIN, p.y - cap / 2, p.x + _NAME_MARGIN + w, p.y + cap / 2)
            elif p.orientation == "right":
                self._text_group(p.x - _NAME_MARGIN, p.y, p.name, self.pal.pin_name, "end", -w, cap / 2, 0, "pin-name")
                self.bounds.add_box(p.x - _NAME_MARGIN - w, p.y - cap / 2, p.x - _NAME_MARGIN, p.y + cap / 2)
            elif p.orientation == "up":
                self._text_group(p.x, p.y - _NAME_MARGIN, p.name, self.pal.pin_name, "end", -w, cap / 2, 90, "pin-name")
                self.bounds.add_box(p.x - cap / 2, p.y - _NAME_MARGIN - w, p.x + cap / 2, p.y - _NAME_MARGIN)
            else:
                self._text_group(
                    p.x, p.y + _NAME_MARGIN, p.name, self.pal.pin_name, "start", 0, cap / 2, 90, "pin-name"
                )
                self.bounds.add_box(p.x - cap / 2, p.y + _NAME_MARGIN, p.x + cap / 2, p.y + _NAME_MARGIN + w)
        if p.show_designator and p.designator:
            w = self.kit.text_width(p.designator)
            off = _NUMBER_OFFSET
            if p.orientation == "left":
                self._text_group(p.x - off, p.y, p.designator, self.pal.pin_number, "end", -w, -15, 0, "pin-number")
                self.bounds.add_box(p.x - off - w, p.y + 15, p.x - off, p.y + 15 + cap)
            elif p.orientation == "right":
                self._text_group(p.x + off, p.y, p.designator, self.pal.pin_number, "start", 0, -15, 0, "pin-number")
                self.bounds.add_box(p.x + off, p.y + 15, p.x + off + w, p.y + 15 + cap)
            elif p.orientation == "up":
                self._text_group(p.x, p.y + off, p.designator, self.pal.pin_number, "start", 0, -15, 90, "pin-number")
                self.bounds.add_box(p.x - 15 - cap, p.y + off, p.x - 15, p.y + off + w)
            else:
                self._text_group(p.x, p.y - off, p.designator, self.pal.pin_number, "end", -w, -15, 90, "pin-number")
                self.bounds.add_box(p.x - 15 - cap, p.y - off - w, p.x - 15, p.y - off)

    # -------------------------------------------------------------------- labels
    def designator_and_comment(self) -> None:
        generator = self.spec.generator if isinstance(self.spec.generator, Mapping) else {}
        positions = generator.get("text_positions")
        if not isinstance(positions, Mapping):
            positions = {}  # foreign/broken metadata: fall back to positions around the body
        x1, y1, _, y2 = self.spec.bbox(self.part)
        default: dict[str, dict[str, Any]] = {
            "designator": {"x": x1, "y": y2 + 30, "justify": "bottom_left"},
            "comment": {"x": x1, "y": y1 - 30 - self.cap, "justify": "bottom_left"},
        }
        suffix = _PART_LETTERS[self.part - 1] if self.spec.part_count > 1 and self.part <= len(_PART_LETTERS) else ""
        texts = {
            "designator": f"{self.spec.designator_prefix or 'U'}?{suffix}",
            "comment": self.spec.comment or "*",
        }
        own = {"designator": self.spec.designator_pos, "comment": self.spec.comment_pos}
        for key, value in texts.items():
            explicit = own[key]  # contract fields win over the generator metadata
            pos = explicit.model_dump() if explicit is not None else positions.get(key)
            if not isinstance(pos, Mapping):
                pos = default[key]
            try:
                x, y = float(pos["x"]), float(pos["y"])
                if not _finite(x, y):
                    raise ValueError("coordinate out of range")
                justify = str(pos.get("justify", "bottom_left"))
                if justify not in _JUSTIFY:
                    justify = "bottom_left"
            except (KeyError, TypeError, ValueError):
                x, y, justify = float(default[key]["x"]), float(default[key]["y"]), "bottom_left"
            self.text_at(x, y, value, self.pal.label, justify, css=f"label-{key}")

    # -------------------------------------------------------------------- document
    def visible(self, part: int) -> bool:
        """Primitive of the rendered part (part 0 = shown in every part)."""
        return part in (0, self.part)

    def render(self, scale: float, padding: float) -> str:
        for g in self.spec.graphics:
            if self.visible(g.part):
                self.graphic(g)
        for p in self.spec.pins:
            if self.visible(p.part) and (not p.hidden or self.show_hidden):
                self.pin(p)
        if self.labels:
            self.designator_and_comment()
        b = self.bounds
        if b.empty:
            b.add_box(-100, -100, 100, 100)
        x1, y1, x2, y2 = b.x1 - padding, b.y1 - padding, b.x2 + padding, b.y2 + padding
        w, h = x2 - x1, y2 - y1
        font = THUMBNAIL_FONT if self.thumbnail else self.kit.font + ", Times, serif"
        css = f"pf-symbol pf-symbol-{self.theme}" + (" pf-symbol-thumbnail" if self.thumbnail else "")
        head = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_f(x1)} {_f(-y2)} {_f(w)} {_f(h)}" '
            f'width="{_f(w * scale)}" height="{_f(h * scale)}" class="{css}" '
            f'data-part="{self.part}" data-parts="{self.spec.part_count}" '
            f"font-family={quoteattr(font)}>"
        )
        body = [head, f"<title>{escape(self.spec.name)}</title>"]
        if self.pal.background:
            body.append(
                f'<rect x="{_f(x1)}" y="{_f(-y2)}" width="{_f(w)}" height="{_f(h)}" fill="{self.pal.background}"/>'
            )
        body.extend(self.out)
        body.append("</svg>")
        return "".join(body)


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) and abs(v) <= COORD_RENDER_LIMIT for v in values)


def _coordinates(spec: SymbolSpec) -> Iterator[float]:
    for p in spec.pins:
        yield from (p.x, p.y, *p.tip())
    for g in spec.graphics:
        if isinstance(g, SymRect):
            yield from (g.x1, g.y1, g.x2, g.y2, g.corner_radius)
        elif isinstance(g, (SymLine, SymPolygon)):
            for pt in g.points:
                yield from (pt.x, pt.y)
        elif isinstance(g, SymArc):
            yield from (g.cx, g.cy, g.r, g.start, g.end)
        elif isinstance(g, SymEllipse):
            yield from (g.cx, g.cy, g.rx, g.ry)
        elif isinstance(g, SymText):
            yield from (g.x, g.y)


def _check_renderable(spec: SymbolSpec) -> None:
    """Reject specs that cannot be drawn sensibly (broken imports, hand-made API payloads)."""
    if spec.part_count > MAX_PART_COUNT:
        raise SymbolError(f"Teileanzahl {spec.part_count} ist ungültig (höchstens {MAX_PART_COUNT} Teile).")
    if not all(_finite(v) for v in _coordinates(spec)):
        limit = f"{COORD_RENDER_LIMIT:,}".replace(",", ".")
        raise SymbolError(
            f"Die Symboldaten enthalten ungültige Koordinaten (NaN, unendlich oder außerhalb von ±{limit} mil)."
        )


def render_svg(
    spec: SymbolSpec,
    *,
    theme: Theme | str = "altium",
    part: int | None = None,
    labels: bool = True,
    scale: float = 0.2,
    padding: float = 60,
    show_hidden: bool = False,
    style: SymbolStyle | None = None,
    thumbnail: bool = False,
) -> str:
    """SVG of one part of ``spec`` (default part 1).

    ``scale`` = pixels per mil for the ``width``/``height`` attributes (the viewBox is in mil),
    ``labels`` draws designator and Comment, ``style`` provides font metrics and the pin
    colour of the ``altium`` theme (default: open workspace style or defaults), ``thumbnail``
    renders for previews: sans-serif font and a constant stroke width
    (:data:`THUMBNAIL_STROKE_PX` screen pixels, ``vector-effect="non-scaling-stroke"``).
    """
    if theme not in _PALETTES:
        raise SymbolError(f"Unbekanntes Farbschema {theme!r} (altium, dark oder light).")
    _check_renderable(spec)
    count = max(1, spec.part_count)
    chosen = 1 if part is None else int(part)
    if not 1 <= chosen <= count:
        raise SymbolError(f"Teil {chosen} gibt es nicht; das Symbol hat {count} Teil(e).")
    if not (0 < scale <= 10):
        raise SymbolError("Der Maßstab muss zwischen 0 und 10 Pixel je mil liegen.")
    kit = StyleKit.from_style(style)
    renderer = _Renderer(spec, str(theme), chosen, kit, labels, show_hidden, kit.pin_color, thumbnail)
    return renderer.render(scale, padding)


def render_thumbnail(spec: SymbolSpec, *, theme: Theme | str = "dark", style: SymbolStyle | None = None,
                     scale: float = 0.15) -> str:
    """Preview of part 1 without designator/comment, sans-serif font and constant stroke width
    (gallery cards, library lists, ``/libraries/symbols/{name}/thumbnail.svg``)."""
    return render_svg(spec, theme=theme, labels=False, scale=scale, style=style, thumbnail=True)


def render_parts(spec: SymbolSpec, **kwargs: Any) -> list[str]:
    """One SVG per part (``render_svg`` keyword arguments apply to all parts)."""
    kwargs.pop("part", None)
    _check_renderable(spec)
    return [render_svg(spec, part=p, **kwargs) for p in range(1, max(1, spec.part_count) + 1)]
