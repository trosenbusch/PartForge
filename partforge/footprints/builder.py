"""House-style footprint builder.

Collects pads and graphics and enforces the house rules of the user's TR_* libraries
(docs/entwicklung/recherche/user-lib-style.md §8):

* SMD pads rounded rectangle with ``style.pad_corner_radius_pct``; THT round, pin 1 square
* silkscreen on ``top_silk`` in style widths, **always** at least ``style.silk_pad_clearance``
  away from copper (segments are clipped against inflated pad rectangles)
* pin-1 dot: arc r = ``style.pin1_dot_radius`` with width 2r (filled disc of radius 2r)
* assembly outline on ``assembly`` (0.1 mm), component centre/outline (Mech 17/19)
* courtyard rectangle on ``courtyard`` (0.05 mm) + optional centre cross
* ``.Designator`` / ``.Comment`` centred at the origin on the ``designator``/``comment`` layers
* 3D bodies as extruded prisms
"""
from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Sequence
from typing import Literal

from ..geometry.model import Arc, Body3D, FootprintSpec, FpLayer, FpText, Pad, PadShape, Region, Track
from ..workspace import FootprintStyle
from . import geom
from .geom import XY, Rect, r6
from .ipc7351 import courtyard_rect, fmt_mm, round_down, round_to

# Realistic 3D colours (#RRGGBB)
TIN = "#C9CDD2"
GOLD = "#D4AF37"
COPPER = "#B87333"
IC_BODY = "#262626"
BLACK_BODY = "#1E1E1E"
RESISTOR_BODY = "#1C1C1C"
MLCC_BODY = "#C8A27C"
INDUCTOR_BODY = "#4A4A4A"
FERRITE_BODY = "#2E2E2E"
LED_BODY = "#F3F1E4"
TANTALUM_BODY = "#E8B30E"
TANTALUM_BAND = "#7A4A1A"
DIODE_BAND = "#B8BCC2"
MELF_RESISTOR = "#4A86B8"
MELF_GLASS = "#B5651D"
BGA_SUBSTRATE = "#2F5D34"
ELKO_SLEEVE = "#1C2D4A"
ELKO_STRIPE = "#C9D1D9"
ALUMINIUM = "#B8BEC6"
AXIAL_RESISTOR = "#D9C9A3"
HEADER_PLASTIC = "#1A1A1A"

CROSS_WIDTH = 0.1  # mm, centre crosses (courtyard + component centre), house style


class FootprintBuilder:
    def __init__(self, style: FootprintStyle, *, silk_width: float | None = None):
        self.style = style
        self.silk_width = silk_width if silk_width is not None else style.silk_width
        self.pads: list[Pad] = []
        self.tracks: list[Track] = []
        self.arcs: list[Arc] = []
        self.regions: list[Region] = []
        self.texts: list[FpText] = []
        self.bodies: list[Body3D] = []
        self.body_rects: list[Rect] = []  # nominal body outlines (courtyard, checks)
        self.courtyard: Rect | None = None
        self.notes: list[str] = []

    # ------------------------------------------------------------------ pads
    def smd_pad(
        self,
        designator: str,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        shape: PadShape = "roundrect",
        thermal: bool = False,
        paste: bool = True,
    ) -> Pad:
        pad = Pad(
            designator=str(designator), x=r6(x), y=r6(y), width=r6(width), height=r6(height), shape=shape,
            corner_radius_pct=self.style.pad_corner_radius_pct if shape == "roundrect" else None,
            side="top", paste=paste, thermal=thermal,
        )
        self.pads.append(pad)
        return pad

    def tht_pad(
        self,
        designator: str,
        x: float,
        y: float,
        width: float,
        height: float,
        hole: float,
        *,
        shape: PadShape = "circle",
    ) -> Pad:
        if width <= hole or height <= hole:
            raise ValueError(f"Pad {designator}: Bohrung {fmt_mm(hole)} mm ist nicht kleiner als das Pad.")
        pad = Pad(
            designator=str(designator), x=r6(x), y=r6(y), width=r6(width), height=r6(height), shape=shape,
            corner_radius_pct=self.style.pad_corner_radius_pct if shape == "roundrect" else None,
            side="through", hole=r6(hole), plated=True, paste=False,
        )
        self.pads.append(pad)
        return pad

    def pads_bbox(self) -> Rect | None:
        return geom.rect_union(geom.pad_bbox(p) for p in self.pads)

    def keepouts(self, width: float) -> list[Rect]:
        """Pad rectangles inflated by silk clearance + half the line width."""
        d = self.style.silk_pad_clearance + width / 2
        return [geom.rect_inflate(geom.pad_bbox(p), d) for p in self.pads]

    # ------------------------------------------------------------------ silkscreen
    def silk_line(self, a: XY, b: XY, *, width: float | None = None, min_len: float | None = None) -> int:
        """Add a silk line, clipped so that it never comes closer than the clearance to copper."""
        w = width if width is not None else self.silk_width
        minimum = min_len if min_len is not None else 1.5 * w
        pieces = geom.clip_segment_outside(a, b, self.keepouts(w), minimum)
        for p, q in pieces:
            self.tracks.append(Track(layer="top_silk", x1=r6(p[0]), y1=r6(p[1]), x2=r6(q[0]), y2=r6(q[1]),
                                     width=w))
        return len(pieces)

    def silk_polyline(self, points: Sequence[XY], *, closed: bool = False, width: float | None = None,
                      min_len: float | None = None) -> int:
        pts = list(points)
        if closed and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        return sum(self.silk_line(a, b, width=width, min_len=min_len) for a, b in itertools.pairwise(pts))

    def silk_rect(self, r: Rect, *, width: float | None = None, min_len: float | None = None) -> int:
        return self.silk_polyline(geom.rect_points(r), closed=True, width=width, min_len=min_len)

    def silk_outline_outside(self, body: Rect, *, width: float | None = None, min_len: float | None = None) -> int:
        """Body outline offset outward by half the line width (no silk on the body), clipped at pads."""
        w = width if width is not None else self.silk_width
        return self.silk_rect(geom.rect_inflate(body, w / 2), width=w, min_len=min_len)

    def dot_ok(self, x: float, y: float) -> bool:
        radius = 2 * self.style.pin1_dot_radius
        need = self.style.silk_pad_clearance + radius - 1e-6
        return all(geom.dist_point_rect((x, y), geom.pad_bbox(p)) >= need for p in self.pads)

    def pin1_dot(self, candidates: Iterable[XY], *, push: XY | None = None) -> XY | None:
        """Place the pin-1 dot at the first candidate with enough copper clearance.

        If none fits, the first candidate is pushed along ``push`` (unit direction) in 0.05 mm steps.
        """
        cands = list(candidates)
        for x, y in cands:
            if self.dot_ok(x, y):
                return self._add_dot(x, y)
        if cands and push is not None:
            x, y = cands[0]
            for step in range(1, 81):
                px, py = x + push[0] * 0.05 * step, y + push[1] * 0.05 * step
                if self.dot_ok(px, py):
                    return self._add_dot(px, py)
        self.notes.append("Pin-1-Punkt im Bestückungsdruck konnte nicht ohne Padkonflikt platziert werden.")
        return None

    def _add_dot(self, x: float, y: float) -> XY:
        r = self.style.pin1_dot_radius
        self.arcs.append(Arc(layer="top_silk", cx=r6(x), cy=r6(y), r=r, start=0, end=360, width=r6(2 * r)))
        return (x, y)

    def dot_radius(self) -> float:
        """Outer radius of the pin-1 dot."""
        return 2 * self.style.pin1_dot_radius

    # ------------------------------------------------------------------ assembly & mechanical
    def line(self, layer: FpLayer, a: XY, b: XY, width: float) -> None:
        self.tracks.append(Track(layer=layer, x1=r6(a[0]), y1=r6(a[1]), x2=r6(b[0]), y2=r6(b[1]), width=width))

    def polyline(self, layer: FpLayer, points: Sequence[XY], width: float, *, closed: bool = False) -> None:
        pts = list(points)
        if closed and pts and pts[0] != pts[-1]:
            pts.append(pts[0])
        for a, b in itertools.pairwise(pts):
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-9:
                self.line(layer, a, b, width)

    def body(self, r: Rect) -> Rect:
        """Declare a nominal body rectangle (used for the courtyard and the checks)."""
        self.body_rects.append(r)
        return r

    def assembly_rect(self, r: Rect, *, chamfer: float = 0.0,
                      corner: Literal["tl", "tr", "bl", "br"] = "tl") -> None:
        """Body outline on the assembly layer, optional pin-1 chamfer at ``corner``."""
        x1, y1, x2, y2 = r
        c = min(chamfer, (x2 - x1) / 2, (y2 - y1) / 2)
        w = self.style.assembly_width
        if c <= 1e-6:
            self.polyline("assembly", geom.rect_points(r), w, closed=True)
            return
        corners = {
            "tl": [(x1 + c, y2), (x2, y2), (x2, y1), (x1, y1), (x1, y2 - c)],
            "tr": [(x2, y2 - c), (x2, y1), (x1, y1), (x1, y2), (x2 - c, y2)],
            "bl": [(x1, y1 + c), (x1, y2), (x2, y2), (x2, y1), (x1 + c, y1)],
            "br": [(x2 - c, y1), (x1, y1), (x1, y2), (x2, y2), (x2, y1 + c)],
        }
        self.polyline("assembly", corners[corner], w, closed=True)

    def assembly_circle(self, cx: float, cy: float, r: float) -> None:
        self.arcs.append(Arc(layer="assembly", cx=r6(cx), cy=r6(cy), r=r6(r), start=0, end=360,
                             width=self.style.assembly_width))

    def assembly_polygon(self, points: Sequence[XY]) -> None:
        self.polyline("assembly", points, self.style.assembly_width, closed=True)

    @staticmethod
    def pin1_chamfer(r: Rect) -> float:
        """KLC: min(1 mm, 25 % of the smaller body side)."""
        return round_down(min(1.0, 0.25 * min(r[2] - r[0], r[3] - r[1])), 0.01)

    def _cross_half(self, ref: Rect | None) -> float:
        if ref is None:
            return 0.5
        size = max(ref[2] - ref[0], ref[3] - ref[1])
        return max(0.1, min(0.5, round_down(0.3 * size, 0.005)))

    def component_marks(self, ref: Rect | None = None) -> None:
        """Mech 17 centre cross (±0.5 mm, smaller on tiny parts) and Mech 19 body outline (house style)."""
        body = ref if ref is not None else geom.rect_union(self.body_rects)
        half = self._cross_half(body)
        self.line("component_center", (-half, 0.0), (half, 0.0), CROSS_WIDTH)
        self.line("component_center", (0.0, -half), (0.0, half), CROSS_WIDTH)
        if body is not None:
            self.polyline("component_outline", geom.rect_points(body), self.style.assembly_width, closed=True)

    def make_courtyard(self, excess: float, grid: float, *, extra: Iterable[Rect] = ()) -> Rect:
        """Courtyard = bbox(pads ∪ bodies ∪ extra) + excess, rounded outward to ``grid``.

        As in IPC-7351B and the house libraries (user-lib-style.md §4.6) the silkscreen is not part of
        the courtyard: silk lines kept clear of the pads and the pin-1 dot may reach slightly beyond it.
        """
        extent = geom.rect_union([*(geom.pad_bbox(p) for p in self.pads), *self.body_rects, *extra])
        if extent is None:
            raise ValueError("Footprint ohne Pads und Körper – Courtyard kann nicht berechnet werden.")
        cy = courtyard_rect(extent, excess, grid)
        self.courtyard = cy
        self.polyline("courtyard", geom.rect_points(cy), self.style.courtyard_width, closed=True)
        if self.style.center_cross:
            half = self._cross_half(geom.rect_union(self.body_rects) or extent)
            self.line("courtyard", (-half, 0.0), (half, 0.0), CROSS_WIDTH)
            self.line("courtyard", (0.0, -half), (0.0, half), CROSS_WIDTH)
        return cy

    def add_texts(self) -> float:
        """``.Designator`` and ``.Comment`` centred at the origin; height scaled down for tiny parts."""
        ref = self.courtyard or self.pads_bbox() or (-1.0, -1.0, 1.0, 1.0)
        short = min(ref[2] - ref[0], ref[3] - ref[1])
        h = min(self.style.text_height, max(0.3, round_down(0.6 * short, 0.05)))
        stroke = r6(max(0.05, round_to(0.15 * h, 0.01)))
        font = self.style.text_font
        font_name = (self.style.text_font_name or "Arial") if font == "truetype" else None
        self.texts.append(FpText(layer="designator", x=0, y=0, text=".Designator", height=h, stroke=stroke,
                                 justify="middle_center", font=font, font_name=font_name))
        self.texts.append(FpText(layer="comment", x=0, y=0, text=".Comment", height=h, stroke=stroke,
                                 justify="middle_center", font=font, font_name=font_name))
        return h

    # ------------------------------------------------------------------ paste
    def paste_windows(self, pad: Pad, coverage: float, *, cell: float = 1.5, min_web: float = 0.15) -> int:
        """Windowpane paste apertures for an exposed/thermal pad (KiCad algorithm, ~65 % coverage)."""
        if coverage >= 0.999:
            pad.paste = True
            return 1
        pad.paste = False
        w, h = pad.width, pad.height
        r = math.sqrt(max(0.05, coverage))
        nx = max(1, math.ceil(w / cell - 1e-9))
        ny = max(1, math.ceil(h / cell - 1e-9))

        def web(size: float, n: int) -> float:
            return size / n - round_to(size * r / n, 0.01)

        while nx > 1 and web(w, nx) < min_web:
            nx -= 1
        while ny > 1 and web(h, ny) < min_web:
            ny -= 1
        ww = round_to(w * r / nx, 0.01)
        wh = round_to(h * r / ny, 0.01)
        for i in range(nx):
            for j in range(ny):
                cx = pad.x - w / 2 + w / nx * (i + 0.5)
                cy = pad.y - h / 2 + h / ny * (j + 0.5)
                pts = geom.rect_points(geom.rect_centered(cx, cy, ww, wh))
                self.regions.append(Region(layer="top_paste", points=geom.to_points(pts)))
        return nx * ny

    # ------------------------------------------------------------------ 3D
    def prism(self, name: str, points: Sequence[XY], z0: float, z1: float, color: str) -> None:
        if z1 - z0 <= 1e-6 or len(points) < 3:
            return
        pts = list(points)
        if geom.polygon_area(pts) < 0:
            pts.reverse()
        self.bodies.append(Body3D(name=name, outline=geom.to_points(pts), z_bottom=r6(z0), z_top=r6(z1),
                                  color=color))

    def box(self, name: str, r: Rect, z0: float, z1: float, color: str) -> None:
        if r[2] - r[0] <= 1e-6 or r[3] - r[1] <= 1e-6:
            return
        self.prism(name, geom.rect_points(r), z0, z1, color)

    def cylinder(self, name: str, cx: float, cy: float, radius: float, z0: float, z1: float, color: str,
                 segments: int = 24) -> None:
        self.prism(name, geom.circle_points(cx, cy, radius, segments), z0, z1, color)

    # ------------------------------------------------------------------ result
    def max_height(self) -> float | None:
        return max((b.z_top for b in self.bodies), default=None)

    def spec(self, **fields: object) -> FootprintSpec:
        return FootprintSpec(
            pads=self.pads, tracks=self.tracks, arcs=self.arcs, regions=self.regions, texts=self.texts,
            bodies=self.bodies, **fields,  # type: ignore[arg-type]
        )
