"""Dual in-line packages (JEDEC MS-001 300 mil / MS-011 600 mil), through-hole.

Holes per IPC-2222 (max lead diagonal + allowance A/B/C = density M/N/L), lands per IPC-2221
(hole + 2 × 0.05 annular ring + fabrication allowance). Pin 1 square, upper left, counter-clockwise.
"""
from __future__ import annotations

import math

from ...geometry.model import Arc, FootprintSpec, PadShape
from .. import ipc7351 as ipc
from .. import naming
from ..builder import IC_BODY, TIN
from ..geom import r6, rect_centered
from ..models import FamilyInfo, Preset
from ..params import ParamError, nom
from .base import COMMON_THT, NAMING_PARAMS, FamilyDef, GenContext, describe, p_enum, p_float, p_int, p_tol

_TYP = "typische Werte nach JEDEC MS-001/MS-011 – Datenblatt prüfen"
_LENGTHS = {4: (4.6, 5.1), 6: (8.13, 8.89), 8: (9.02, 10.16), 14: (18.67, 19.69), 16: (18.67, 19.69),
            18: (22.35, 23.37), 20: (24.89, 26.92), 24: (31.24, 32.26)}
_LENGTHS_W = {24: (31.24, 32.26), 28: (35.05, 37.08), 40: (51.82, 52.58)}


def _presets() -> list[Preset]:
    out = []
    for pins, d in _LENGTHS.items():
        out.append(Preset(key=f"DIP-{pins}", label=f"DIP-{pins} (300 mil)", source=_TYP,
                          params={"pins": pins, "eA": 7.62, "D": {"min": d[0], "max": d[1]},
                                  "E1": {"min": 6.10, "max": 7.11}}))
    for pins, d in _LENGTHS_W.items():
        out.append(Preset(key=f"DIP-{pins}W", label=f"DIP-{pins} breit (600 mil)", source=_TYP,
                          params={"pins": pins, "eA": 15.24, "D": {"min": d[0], "max": d[1]},
                                  "E1": {"min": 13.21, "max": 14.22}}))
    return out


PARAMS = [
    p_int("pins", "Anzahl Anschlüsse", default=8, minimum=4, maximum=64),
    p_float("e", "Raster e", default=2.54, minimum=1.0, maximum=5.08, group="Anschlüsse"),
    p_float("eA", "Reihenabstand eA", default=7.62, minimum=5.0, maximum=30.0, group="Anschlüsse",
            help="Mitte–Mitte der beiden Reihen (300 mil = 7,62 mm, 600 mil = 15,24 mm)."),
    p_tol("E1", "Körperbreite E1", default={"min": 6.10, "max": 7.11}),
    p_tol("D", "Körperlänge D", default={"min": 9.02, "max": 10.16}),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse", default={"min": 0.36, "max": 0.56}),
    p_tol("b1", "Schulterbreite b1", group="Anschlüsse", default={"min": 1.14, "max": 1.78}),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.20, "max": 0.38}),
    p_tol("A", "Bauhöhe A", default={"min": 3.6, "max": 5.33}, help="Platine bis Oberkante."),
    p_tol("A1", "Abstand A1", default={"min": 0.38, "max": 1.02}, help="Platine bis Körperunterseite."),
    p_enum("pad_shape", "Padform", ["round", "oval"], default="round", group="Optionen",
           help="oval: lange Pads quer zur Reihe (bessere Lötbarkeit von Hand)."),
    *NAMING_PARAMS,
    *COMMON_THT,
]

INFO = FamilyInfo(
    key="dip",
    label="DIP (bedrahtet)",
    group="Bedrahtet",
    description="Dual-in-line-Gehäuse 300/600 mil mit Bohrungen nach IPC-2222.",
    params=PARAMS,
    presets=_presets(),
    ipc_table="IPC-2222 / IPC-2221",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    pins = p.int("pins", 8)
    if pins % 2:
        raise ParamError("Die Anzahl der Anschlüsse muss gerade sein (zwei Reihen).", params=("pins",))
    e, ea = p.float("e", 2.54), p.float("eA", 7.62)
    E1, D, b_, b1, c, A, A1 = (p.tol(n) for n in ("E1", "D", "b", "b1", "c", "A", "A1"))  # noqa: N806
    lead = math.hypot(b_.max, c.max)
    land = ctx.tht_land(lead, e, axis="y")  # neighbours follow along Y: an oval stays narrow in Y
    w, h = land.width, land.height
    if p.enum("pad_shape", "round") == "oval":  # elongate across the row (X) only
        w = max(w, min(ipc.round_up(land.diameter + 0.8, 0.05), ipc.round_down(ea - ctx.min_gap - 0.1, 0.05)))
    row_limit = ipc.round_down(ea - ctx.min_gap, 0.01)  # the two rows must not touch either
    if w > row_limit:
        if row_limit <= land.hole + 2 * ipc.THT_ANNULAR_RING_MIN:
            raise ValueError(f"Reihenabstand eA {ipc.fmt_mm(ea)} mm ist für die Pads zu klein.")
        ctx.warn(f"Padbreite {ipc.fmt_mm(w)} mm auf {ipc.fmt_mm(row_limit)} mm begrenzt (Reihenabstand eA "
                 f"{ipc.fmt_mm(ea)} mm).")
        w = row_limit
    shape_other: PadShape = "oval" if (abs(w - h) > 1e-9 or land.shape == "oval") else "circle"
    n = pins // 2
    b = ctx.builder()
    ys = [r6(((n - 1) / 2 - i) * e) for i in range(n)]
    for i, y in enumerate(ys):
        b.tht_pad(str(i + 1), -ea / 2, y, w, h, land.hole, shape="rect" if i == 0 else shape_other)
    for i, y in enumerate(reversed(ys)):
        b.tht_pad(str(n + i + 1), ea / 2, y, w, h, land.hole, shape=shape_other)

    e1n, dn = nom(E1), nom(D)
    body = b.body(rect_centered(0, 0, e1n, dn))
    sw = b.silk_width
    xs = min(e1n / 2 + sw / 2, ea / 2 - w / 2 - b.style.silk_pad_clearance - sw / 2)
    top = dn / 2 + sw / 2
    notch = min(1.0, xs / 2)
    b.silk_polyline([(-notch, top), (-xs, top), (-xs, -top), (xs, -top), (xs, top), (notch, top)])
    b.arcs.append(Arc(layer="top_silk", cx=0.0, cy=r6(top), r=r6(notch), start=180, end=360, width=sw))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

    h_max, a1 = A.max, nom(A1)
    b.box("Body", body, a1, h_max, IC_BODY)
    bn, cn, b1n = nom(b_), nom(c), nom(b1)
    for pad in b.pads:
        b.box(f"Pin {pad.designator}", (pad.x - cn / 2, pad.y - bn / 2, pad.x + cn / 2, pad.y + bn / 2), 0.0,
              a1 + 0.6, TIN)
        s = 1.0 if pad.x > 0 else -1.0
        x_in, x_out = s * (e1n / 2 - 0.1), pad.x + s * cn / 2
        b.box(f"Pin {pad.designator} shoulder", (min(x_in, x_out), pad.y - b1n / 2, max(x_in, x_out),
                                                 pad.y + b1n / 2), a1 + 0.3, a1 + 0.3 + cn, TIN)

    level = ipc.THT_LEVEL[ctx.density]
    ipc_name = naming.ipc_dip(ea, b_.max, e, dn, h_max, pins, level)
    house_name = naming.house(f"DIP-{pins} {naming.short_num(ea)}MM", ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe("DIP", pins, dn, e1n, ctx.density, pitch=e, extra=f"Row Spacing {ea:.2f}mm")
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"DIP-{pins} ({naming.short_num(ea)} mm)", height=h_max, courtyard_kind="tht")


ALIAS_PARAMS = {
    **{f"dip{n}": {"pins": n, "preset": "*"} for n in (4, 6, 8, 14, 16, 18, 20, 24, 28, 40)},
    "ms001": {"eA": 7.62, "preset": "*"}, "ms011": {"eA": 15.24, "preset": "*"},
}

FAMILIES = [FamilyDef(INFO, build, aliases=("pdip", "dil"), alias_params=ALIAS_PARAMS,
                      free_params=frozenset({"A1", "b1"}), max_only=frozenset({"A"}))]
