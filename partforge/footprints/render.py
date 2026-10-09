"""FootprintSpec -> SVG (thumbnails, previews, tests).

Layers are rendered as ``<g data-layer="…" class="pf-layer pf-layer-…">`` groups so the frontend can
toggle them with CSS; ``layers=`` restricts the output. Themes: ``dark`` (PartForge canvas, colours
from docs/entwicklung/FRONTEND.md), ``light`` and ``altium`` (classic Altium layer colours).
Coordinates: mm, Y flipped (SVG Y points down).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal
from xml.sax.saxutils import escape

from ..geometry.model import Arc, FootprintSpec, Pad
from . import geom

Theme = Literal["dark", "light", "altium"]

THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "background": "#05070A", "grid": "#1A1F29", "top_copper": "#E5484D", "bottom_copper": "#4C7DFF",
        "through": "#C9CED8", "hole": "#05070A", "top_silk": "#F2D14B", "bottom_silk": "#B9A23A",
        "courtyard": "#D16BFF", "assembly": "#6FA8FF", "top_paste": "#8D96A8", "bottom_paste": "#8D96A8",
        "top_mask": "#7C5CC4", "bottom_mask": "#7C5CC4", "body3d": "#3DD68C", "designator": "#9AA4B2",
        "comment": "#7D8794", "component_center": "#5E6B7D", "component_outline": "#5E6B7D",
        "keepout": "#FF4FD8", "pad_text": "#0B0E14",
    },
    "light": {
        "background": "#FFFFFF", "grid": "#E6E8EE", "top_copper": "#D93036", "bottom_copper": "#2F5FD0",
        "through": "#9AA2B1", "hole": "#FFFFFF", "top_silk": "#A88A00", "bottom_silk": "#8A7300",
        "courtyard": "#A23DD6", "assembly": "#2F6FD6", "top_paste": "#6B7385", "bottom_paste": "#6B7385",
        "top_mask": "#6A4BB0", "bottom_mask": "#6A4BB0", "body3d": "#1F9E62", "designator": "#4A5468",
        "comment": "#6B7385", "component_center": "#8A93A6", "component_outline": "#8A93A6",
        "keepout": "#C2189A", "pad_text": "#FFFFFF",
    },
    "altium": {
        "background": "#000000", "grid": "#202020", "top_copper": "#FF0000", "bottom_copper": "#0000FF",
        "through": "#C0C0C0", "hole": "#000000", "top_silk": "#FFFF00", "bottom_silk": "#808000",
        "courtyard": "#FF00FF", "assembly": "#00FFFF", "top_paste": "#808080", "bottom_paste": "#800000",
        "top_mask": "#800080", "bottom_mask": "#FF00FF", "body3d": "#00FF00", "designator": "#FFFFFF",
        "comment": "#C0C0C0", "component_center": "#808080", "component_outline": "#808080",
        "keepout": "#FF00FF", "pad_text": "#FFFFFF",
    },
}

LAYER_ORDER = [
    "body3d", "component_outline", "courtyard", "assembly", "component_center", "bottom_copper",
    "top_copper", "through", "top_paste", "top_silk", "designator", "comment", "keepout",
]


def _f(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _pad_layer(p: Pad) -> str:
    if p.side == "through" or p.hole:
        return "through"
    return "bottom_copper" if p.side == "bottom" else "top_copper"


def _pad_svg(p: Pad, color: str) -> str:
    x, y = p.x, -p.y
    w, h = p.width, p.height
    transform = f' transform="rotate({_f(-p.rotation)} {_f(x)} {_f(y)})"' if p.rotation else ""
    if p.shape == "circle" and abs(w - h) < 1e-9:
        return f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(w / 2)}" fill="{color}"/>'
    if p.shape in ("circle", "oval"):
        r = min(w, h) / 2
    elif p.shape == "roundrect":
        pct = 50 if p.corner_radius_pct is None else p.corner_radius_pct
        r = min(w, h) / 2 * pct / 100
    else:
        r = 0.0
    if p.shape == "octagon":
        c = min(w, h) * (1 - 1 / (1 + math.sqrt(2))) / 2
        x1, y1, x2, y2 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
        pts = [(x1 + c, y1), (x2 - c, y1), (x2, y1 + c), (x2, y2 - c), (x2 - c, y2), (x1 + c, y2), (x1, y2 - c),
               (x1, y1 + c)]
        return (f'<polygon points="{" ".join(f"{_f(a)},{_f(b)}" for a, b in pts)}" fill="{color}"'
                f"{transform}/>")
    rr = f' rx="{_f(r)}" ry="{_f(r)}"' if r > 0 else ""
    return (f'<rect x="{_f(x - w / 2)}" y="{_f(y - h / 2)}" width="{_f(w)}" height="{_f(h)}"{rr} fill="{color}"'
            f"{transform}/>")


def _arc_svg(a: Arc, color: str) -> str:
    full = abs((a.end - a.start) % 360) < 1e-9 and a.end != a.start
    if full:
        if a.width >= 2 * a.r - 1e-9:  # filled dot
            return f'<circle cx="{_f(a.cx)}" cy="{_f(-a.cy)}" r="{_f(a.r + a.width / 2)}" fill="{color}"/>'
        return (f'<circle cx="{_f(a.cx)}" cy="{_f(-a.cy)}" r="{_f(a.r)}" fill="none" stroke="{color}" '
                f'stroke-width="{_f(a.width)}"/>')
    sweep = (a.end - a.start) % 360
    s, e = math.radians(a.start), math.radians(a.start + sweep)
    x1, y1 = a.cx + a.r * math.cos(s), -(a.cy + a.r * math.sin(s))
    x2, y2 = a.cx + a.r * math.cos(e), -(a.cy + a.r * math.sin(e))
    large = 1 if sweep > 180 else 0
    return (f'<path d="M {_f(x1)} {_f(y1)} A {_f(a.r)} {_f(a.r)} 0 {large} 0 {_f(x2)} {_f(y2)}" fill="none" '
            f'stroke="{color}" stroke-width="{_f(a.width)}" stroke-linecap="round"/>')


def render_svg(
    spec: FootprintSpec,
    *,
    layers: Iterable[str] | None = None,
    theme: Theme = "dark",
    width_px: int | None = None,
    padding: float = 0.6,
    show_pad_numbers: bool = True,
    show_texts: bool = False,
    grid: bool = True,
    background: bool = True,
) -> str:
    """Render the footprint as standalone SVG string."""
    colors = THEMES.get(theme, THEMES["dark"])
    wanted = set(layers) if layers is not None else None

    def on(layer: str) -> bool:
        return wanted is None or layer in wanted

    groups: dict[str, list[str]] = {name: [] for name in LAYER_ORDER}
    layer: str
    for t in spec.tracks:
        layer = t.layer if t.layer in groups else "keepout"
        dash = ' stroke-dasharray="0.15 0.1"' if t.layer == "courtyard" else ""
        groups[layer].append(
            f'<line x1="{_f(t.x1)}" y1="{_f(-t.y1)}" x2="{_f(t.x2)}" y2="{_f(-t.y2)}" stroke="{colors.get(t.layer, "#888")}"'
            f' stroke-width="{_f(t.width)}" stroke-linecap="round"{dash}/>')
    for a in spec.arcs:
        layer = a.layer if a.layer in groups else "keepout"
        groups[layer].append(_arc_svg(a, colors.get(a.layer, "#888")))
    for rg in spec.regions:
        layer = rg.layer if rg.layer in groups else "keepout"
        pts = " ".join(f"{_f(p.x)},{_f(-p.y)}" for p in rg.points)
        if rg.layer in ("top_paste", "bottom_paste"):
            groups[layer].append(f'<polygon points="{pts}" fill="none" stroke="{colors[rg.layer]}" stroke-width="0.04"/>')
        else:
            groups[layer].append(f'<polygon points="{pts}" fill="{colors.get(rg.layer, "#888")}" fill-opacity="0.85"/>')
    for p in spec.pads:
        layer = _pad_layer(p)
        groups[layer].append(_pad_svg(p, colors[layer]))
        if p.hole:
            hl = p.hole_length or p.hole
            if hl > p.hole + 1e-9:
                groups[layer].append(
                    f'<rect x="{_f(p.x - hl / 2)}" y="{_f(-p.y - p.hole / 2)}" width="{_f(hl)}" height="{_f(p.hole)}" '
                    f'rx="{_f(p.hole / 2)}" fill="{colors["hole"]}"/>')
            else:
                groups[layer].append(f'<circle cx="{_f(p.x)}" cy="{_f(-p.y)}" r="{_f(p.hole / 2)}" fill="{colors["hole"]}"/>')
        if p.paste and p.side != "through" and on("top_paste"):
            groups["top_paste"].append(
                f'<rect x="{_f(p.x - p.width / 2)}" y="{_f(-p.y - p.height / 2)}" width="{_f(p.width)}" '
                f'height="{_f(p.height)}" fill="none" stroke="{colors["top_paste"]}" stroke-width="0.03" '
                f'stroke-dasharray="0.06 0.06"/>')
        if show_pad_numbers:
            size = max(0.12, min(1.0, 0.45 * min(p.width, p.height)))
            if p.hole:  # number sits on the (dark) drill hole
                size = max(0.12, min(size, 0.7 * p.hole))
            text_color = colors["through"] if p.hole else colors["pad_text"]
            groups[layer].append(
                f'<text x="{_f(p.x)}" y="{_f(-p.y)}" font-size="{_f(size)}" fill="{text_color}" '
                f'text-anchor="middle" dominant-baseline="central" font-family="JetBrains Mono, monospace" '
                f'font-weight="600">{escape(p.designator)}</text>')
    for b in spec.bodies:
        pts = " ".join(f"{_f(p.x)},{_f(-p.y)}" for p in b.outline)
        groups["body3d"].append(f'<polygon points="{pts}" fill="none" stroke="{colors["body3d"]}" '
                                f'stroke-width="0.03" stroke-opacity="0.7"/>')
    if show_texts:
        for txt in spec.texts:
            layer = txt.layer if txt.layer in groups else "keepout"
            groups[layer].append(
                f'<text x="{_f(txt.x)}" y="{_f(-txt.y)}" font-size="{_f(txt.height)}" '
                f'fill="{colors.get(txt.layer, "#888")}" text-anchor="middle" dominant-baseline="central" '
                f'font-family="Inter, sans-serif">{escape(txt.text)}</text>')

    box = spec.bbox()
    if box == (0.0, 0.0, 0.0, 0.0):
        box = (-1.0, -1.0, 1.0, 1.0)
    for body in spec.bodies:
        bb = geom.bbox_points(geom.from_points(body.outline))
        if bb:
            box = (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
    x1, y1, x2, y2 = box[0] - padding, box[1] - padding, box[2] + padding, box[3] + padding
    vw, vh = x2 - x1, y2 - y1
    size_attr = ""
    if width_px:
        size_attr = f' width="{width_px}" height="{round(width_px * vh / vw)}"'
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_f(x1)} {_f(-y2)} {_f(vw)} {_f(vh)}"{size_attr} '
           f'data-footprint="{escape(spec.name, {chr(34): "&quot;"})}" role="img">',
           f"<title>{escape(spec.name)}</title>"]
    if background:
        out.append(f'<rect x="{_f(x1)}" y="{_f(-y2)}" width="{_f(vw)}" height="{_f(vh)}" fill="{colors["background"]}"/>')
    if grid:
        step = 1.0 if max(vw, vh) <= 30 else 2.54
        out.append(f'<defs><pattern id="pf-grid" x="0" y="0" width="{_f(step)}" height="{_f(step)}" '
                   f'patternUnits="userSpaceOnUse"><circle cx="0" cy="0" r="{_f(step * 0.03)}" '
                   f'fill="{colors["grid"]}"/></pattern></defs>')
        out.append(f'<rect x="{_f(x1)}" y="{_f(-y2)}" width="{_f(vw)}" height="{_f(vh)}" fill="url(#pf-grid)"/>')
    for name in LAYER_ORDER:
        if groups[name] and on(name):
            out.append(f'<g class="pf-layer pf-layer-{name}" data-layer="{name}">')
            out.extend(groups[name])
            out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)
