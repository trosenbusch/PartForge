"""TO-92 (SOT54, SC-43A) through-hole, inline leads (pitch 1.27 mm native or 2.54 mm bent).

Top view: flat face to the front (-Y), pins 1-2-3 from left to right, pin 1 square.
Dimensions: Nexperia SOT54 (S20).
"""
from __future__ import annotations

import math

from ...geometry.model import FootprintSpec, PadShape
from .. import ipc7351 as ipc
from .. import naming
from ..builder import BLACK_BODY, TIN
from ..geom import XY, bbox_points, circle_points
from ..models import FamilyInfo, Preset
from ..params import nom
from .base import COMMON_THT, FamilyDef, GenContext, describe, p_enum, p_float, p_tol

BASE = {"D": (4.4, 4.8), "E": (3.6, 4.2), "A": (5.0, 5.2), "b": (0.40, 0.48), "c": (0.38, 0.45),
        "d_flat": (1.4, 1.7)}

PARAMS = [
    p_enum("pitch", "Rastermaß", ["1.27", "2.54"], default="1.27", group="Anschlüsse", unit="mm",
           help="1,27 mm: gerade Anschlüsse (ovale Pads); 2,54 mm: aufgebogene Anschlüsse."),
    p_tol("D", "Körperbreite D", default={"min": 4.4, "max": 4.8}),
    p_tol("E", "Körpertiefe E", default={"min": 3.6, "max": 4.2}),
    p_tol("A", "Körperhöhe A", default={"min": 5.0, "max": 5.2}),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse", default={"min": 0.40, "max": 0.48}),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.38, "max": 0.45}),
    p_tol("d_flat", "Abstand Flachseite – Anschlüsse", default={"min": 1.4, "max": 1.7}),
    p_float("standoff", "Montagehöhe", default=2.0, minimum=0.0, maximum=20.0,
            help="Abstand Platine – Körperunterseite (für 3D und Bauhöhe)."),
    *COMMON_THT,
]

INFO = FamilyInfo(
    key="to92",
    label="TO-92",
    group="Bedrahtet",
    description="TO-92 mit drei Anschlüssen in einer Reihe.",
    params=PARAMS,
    presets=[
        Preset(key="TO-92-P1.27", label="TO-92, Raster 1,27 mm (gerade)", source="Nexperia SOT54",
               params={"pitch": "1.27", **{k: {"min": v[0], "max": v[1]} for k, v in BASE.items()}}),
        Preset(key="TO-92-P2.54", label="TO-92, Raster 2,54 mm (aufgebogen)", source="Nexperia SOT54",
               params={"pitch": "2.54", **{k: {"min": v[0], "max": v[1]} for k, v in BASE.items()}}),
    ],
    ipc_table="IPC-2222 / IPC-2221",
)


def d_shape(width: float, depth: float, flat: float, grow: float = 0.0, segments: int = 40) -> list[XY]:
    """TO-92 outline: flat face at y = -flat, round back; ``grow`` offsets the outline outward."""
    r = width / 2 + grow
    yc = depth - flat - width / 2
    y_flat = -flat - grow
    dy = y_flat - yc
    if abs(dy) >= r:
        raise ValueError("TO-92: Abstand der Flachseite passt nicht zur Körperbreite – bitte Maße prüfen.")
    alpha = math.degrees(math.atan2(dy, math.sqrt(r * r - dy * dy)))
    return circle_points(0.0, yc, r, segments, start=alpha, end=180.0 - alpha)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    pitch = float(p.enum("pitch", "1.27"))
    D, E, A, b_, c, flat = (p.tol(n) for n in ("D", "E", "A", "b", "c", "d_flat"))  # noqa: N806
    standoff = p.float("standoff", 2.0)
    land = ctx.tht_land(math.hypot(b_.max, c.max), pitch)
    b = ctx.builder()
    for i, x in enumerate((-pitch, 0.0, pitch)):
        shape: PadShape = "rect" if i == 0 else ("oval" if land.shape == "oval" else "circle")
        b.tht_pad(str(i + 1), x, 0.0, land.width, land.height, land.hole, shape=shape)
    dn, en, fn = nom(D), nom(E), nom(flat)
    outline = d_shape(dn, en, fn)
    bb = bbox_points(outline)
    assert bb is not None
    b.body(bb)
    b.silk_polyline(d_shape(dn, en, fn, grow=b.silk_width / 2 + 0.05), closed=True, min_len=0.05)
    b.assembly_polygon(outline)
    h = standoff + A.max
    b.prism("Body", outline, standoff, h, BLACK_BODY)
    bn, cn = nom(b_), nom(c)
    for pad in b.pads:
        b.box(f"Lead {pad.designator}", (pad.x - bn / 2, -cn / 2, pad.x + bn / 2, cn / 2), 0.0, standoff + 0.5, TIN)

    level = ipc.THT_LEVEL[ctx.density]
    ipc_name = naming.ipc_to_tht("TO92", pitch, 3, level)
    house_name = naming.house(f"TO-92 P{naming.short_num(pitch)}", ctx.density)
    description = describe("TO-92", 3, dn, en, ctx.density, pitch=pitch)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"TO-92 (Raster {naming.short_num(pitch)} mm)", height=h, courtyard_kind="tht")


# names carry pitch and pin count only; height and standoff are 3D only
FAMILIES = [FamilyDef(INFO, build, aliases=("to-92", "sot54", "sc43", "to92-3"),
                      free_params=frozenset({"A", "standoff"}))]
