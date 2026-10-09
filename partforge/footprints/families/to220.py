"""TO-220 vertical (TO-220AB 3 leads / TO-220AC 2 leads), through-hole.

Top view: leads in a row along X (pin 1 left, square), body in front (-Y), metal tab at the back (+Y).
Dimensions: Nexperia SOT78 "3-lead TO-220AB" (S20); q = lead axis to back of the tab.
"""
from __future__ import annotations

import math

from ...geometry.model import FootprintSpec, PadShape
from .. import ipc7351 as ipc
from .. import naming
from ..builder import BLACK_BODY, TIN
from ..models import FamilyInfo, Preset
from ..params import nom
from .base import COMMON_THT, FamilyDef, GenContext, describe, p_enum, p_float, p_tol

BASE = {"E": (9.7, 10.3), "A": (4.1, 4.7), "A1": (1.25, 1.40), "D": (15.2, 16.0), "D1": (5.9, 6.6),
        "b": (0.6, 0.9), "c": (0.4, 0.7), "q": (2.7, 3.0)}

PARAMS = [
    p_enum("pins", "Anschlüsse", ["2", "3"], default="3", group="Anschlüsse",
           help="3: TO-220AB (Pins 1–3); 2: TO-220AC (äußere Positionen)."),
    p_float("e", "Raster e", default=2.54, minimum=1.0, maximum=5.08, group="Anschlüsse"),
    p_tol("E", "Körperbreite E", default={"min": 9.7, "max": 10.3}),
    p_tol("A", "Gesamtdicke A", default={"min": 4.1, "max": 4.7}, help="Kunststoffkörper inkl. Kühlfahne."),
    p_tol("A1", "Dicke Kühlfahne A1", default={"min": 1.25, "max": 1.40}),
    p_tol("D", "Höhe gesamt D", default={"min": 15.2, "max": 16.0}, help="Körper und Kühlfahne."),
    p_tol("D1", "Höhe Kühlfahne über Körper D1", default={"min": 5.9, "max": 6.6}),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse", default={"min": 0.6, "max": 0.9}),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.4, "max": 0.7}),
    p_tol("q", "Anschlussachse bis Rückseite q", default={"min": 2.7, "max": 3.0}),
    p_float("standoff", "Montagehöhe", default=3.0, minimum=0.0, maximum=30.0,
            help="Abstand Platine – Körperunterseite."),
    *COMMON_THT,
]

INFO = FamilyInfo(
    key="to220",
    label="TO-220 (stehend)",
    group="Bedrahtet",
    description="TO-220 stehend montiert, Kühlfahne hinten.",
    params=PARAMS,
    presets=[
        Preset(key="TO-220-3", label="TO-220-3 (TO-220AB) stehend", source="Nexperia SOT78",
               params={"pins": "3", "e": 2.54, **{k: {"min": v[0], "max": v[1]} for k, v in BASE.items()}}),
        Preset(key="TO-220-2", label="TO-220-2 (TO-220AC) stehend", source="Nexperia SOT78 (Körper), 2 Anschlüsse",
               params={"pins": "2", "e": 2.54, **{k: {"min": v[0], "max": v[1]} for k, v in BASE.items()}}),
    ],
    ipc_table="IPC-2222 / IPC-2221",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    pins = int(p.enum("pins", "3"))
    e = p.float("e", 2.54)
    E, A, A1, D, D1, b_, c, q = (p.tol(n) for n in ("E", "A", "A1", "D", "D1", "b", "c", "q"))  # noqa: N806
    standoff = p.float("standoff", 3.0)
    if A1.max >= A.min:
        raise ValueError("Die Kühlfahne (A1) muss dünner als das Gehäuse (A) sein.")
    pitch = e if pins == 3 else 2 * e
    land = ctx.tht_land(math.hypot(b_.max, c.max), pitch)
    xs = (-e, 0.0, e) if pins == 3 else (-e, e)
    b = ctx.builder()
    for i, x in enumerate(xs):
        shape: PadShape = "rect" if i == 0 else ("oval" if land.shape == "oval" else "circle")
        b.tht_pad(str(i + 1), x, 0.0, land.width, land.height, land.hole, shape=shape)
    en, an, a1n, qn = nom(E), nom(A), nom(A1), nom(q)
    y_back, y_tab, y_front = qn, qn - a1n, qn - an
    body = b.body((-en / 2, y_front, en / 2, y_back))
    b.silk_outline_outside(body)
    b.silk_line((-en / 2, y_tab), (en / 2, y_tab), min_len=0.1)
    b.assembly_rect(body)
    b.line("assembly", (-en / 2, y_tab), (en / 2, y_tab), b.style.assembly_width)

    height = standoff + D.max
    b.box("Body", (-en / 2, y_front, en / 2, y_tab), standoff, standoff + nom(D) - nom(D1), BLACK_BODY)
    b.box("Tab", (-en / 2, y_tab, en / 2, y_back), standoff, height, TIN)
    bn, cn = nom(b_), nom(c)
    for pad in b.pads:
        b.box(f"Lead {pad.designator}", (pad.x - bn / 2, -cn / 2, pad.x + bn / 2, cn / 2), 0.0, standoff + 0.5, TIN)

    level = ipc.THT_LEVEL[ctx.density]
    ipc_name = naming.ipc_to_tht("TO220V", e, pins, level)
    house_name = naming.house(f"TO-220-{pins} VERTICAL", ctx.density)
    description = describe("TO-220 Vertical", pins, en, an, ctx.density, pitch=e)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"TO-220-{pins} stehend", height=height, courtyard_kind="tht")


ALIAS_PARAMS = {
    "to220ab": {"pins": "3"}, "to220-3": {"pins": "3"}, "to220ac": {"pins": "2"}, "to220-2": {"pins": "2"},
}

# names carry pitch and pin count only; heights (D, D1) and standoff are 3D only
FAMILIES = [FamilyDef(INFO, build, aliases=("to-220", "sot78"), alias_params=ALIAS_PARAMS,
                      free_params=frozenset({"D", "D1", "standoff"}))]
