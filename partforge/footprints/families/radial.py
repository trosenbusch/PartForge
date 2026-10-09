"""Radial through-hole capacitors (aluminium electrolytic, CAPPRD polarised / CAPRD unpolarised).

Pin 1 = positive (square) on the left. Dimensions: Panasonic FR-A (S25): D ±0.5, lead d ±0.05,
F ±0.5, L ±1.5 (L ≤ 16) / ±2.0 (L ≥ 20).
"""
from __future__ import annotations

import math

from ...geometry.model import Arc, FootprintSpec
from .. import ipc7351 as ipc
from .. import naming
from ..builder import ALUMINIUM, ELKO_SLEEVE, ELKO_STRIPE
from ..geom import circle_points, pad_bbox, r6, rect_points
from ..models import FamilyInfo, Preset
from ..params import nom
from .base import COMMON_THT, FamilyDef, GenContext, describe, p_enum, p_float, p_tol

_SIZES = [  # (D, L, F, d, source)
    (4.0, 7.0, 1.5, 0.45, "typische Werte – Datenblatt prüfen"),
    (5.0, 11.0, 2.0, 0.5, "Panasonic FR-A"),
    (6.3, 11.0, 2.5, 0.5, "Panasonic FR-A"),
    (8.0, 11.5, 3.5, 0.6, "Panasonic FR-A"),
    (10.0, 12.5, 5.0, 0.6, "Panasonic FR-A"),
    (10.0, 16.0, 5.0, 0.6, "Panasonic FR-A"),
    (12.5, 20.0, 5.0, 0.6, "Panasonic FR-A"),
    (16.0, 25.0, 7.5, 0.8, "Panasonic FR-A"),
    (18.0, 35.5, 7.5, 0.8, "typische Werte – Datenblatt prüfen"),
]


def _presets() -> list[Preset]:
    out = []
    for dia, length, f, wire, source in _SIZES:
        lt = 1.5 if length <= 16 else 2.0
        out.append(Preset(
            key=f"D{dia:g}x{length:g}-P{f:g}", label=f"Elko Ø{dia:g} × {length:g} mm, Raster {f:g} mm".replace(".", ","),
            source=source,
            params={"kind": "CAPPRD", "F": f, "D": {"min": dia - 0.5, "max": dia + 0.5},
                    "H": {"min": length - lt, "max": length + lt}, "d": {"min": wire - 0.05, "max": wire + 0.05}},
        ))
    return out


PARAMS = [
    p_enum("kind", "Bauteilart", ["CAPPRD", "CAPRD"], default="CAPPRD", group="Typ",
           help="CAPPRD gepolter Elko (Pin 1 = Plus), CAPRD ungepolt."),
    p_float("F", "Rastermaß F", default=2.5, minimum=1.0, maximum=30.0, group="Anschlüsse"),
    p_tol("D", "Durchmesser D", default={"min": 5.8, "max": 6.8}),
    p_tol("H", "Höhe H", default={"min": 9.5, "max": 12.5}),
    p_tol("d", "Drahtdurchmesser d", group="Anschlüsse", default={"min": 0.45, "max": 0.55}),
    *COMMON_THT,
]

INFO = FamilyInfo(
    key="radial",
    label="Radial (Elko)",
    group="Bedrahtet",
    description="Radiale Kondensatoren (Elektrolyt) stehend montiert.",
    params=PARAMS,
    presets=_presets(),
    ipc_table="IPC-2222 / IPC-2221",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    kind = p.enum("kind", "CAPPRD")
    f = p.float("F", 2.5)
    D, H, d = p.tol("D"), p.tol("H"), p.tol("d")  # noqa: N806
    dn = nom(D)
    if f >= dn:
        raise ValueError("Das Rastermaß F muss kleiner als der Durchmesser D sein.")
    land = ctx.tht_land(d.max, f)
    b = ctx.builder()
    polarized = kind == "CAPPRD"
    b.tht_pad("1", -f / 2, 0.0, land.width, land.height, land.hole, shape="rect")
    b.tht_pad("2", f / 2, 0.0, land.width, land.height, land.hole,
              shape="oval" if land.shape == "oval" else "circle")
    r = dn / 2
    b.body((-r, -r, r, r))
    sw = b.silk_width
    r_silk = r + sw / 2 + 0.05
    need = b.style.silk_pad_clearance + sw / 2
    corners = [pt for pad in b.pads for pt in rect_points(pad_bbox(pad))]
    if all(r_silk - math.hypot(x, y) >= need for x, y in corners):  # all pads well inside: one true arc
        b.arcs.append(Arc(layer="top_silk", cx=0.0, cy=0.0, r=r6(r_silk), start=0, end=360, width=sw))
    else:
        b.silk_polyline(circle_points(0.0, 0.0, r_silk, 64), closed=True, min_len=0.05)
    if polarized:
        size = max(0.5, min(1.0, 0.15 * dn))
        cx, cy = -(r + 0.2 + size) * math.cos(math.radians(45)), (r + 0.2 + size) * math.sin(math.radians(45))
        b.silk_line((cx - size / 2, cy), (cx + size / 2, cy), min_len=0.0)
        b.silk_line((cx, cy - size / 2), (cx, cy + size / 2), min_len=0.0)
    b.assembly_circle(0.0, 0.0, r)

    h = H.max
    top = 0.12
    b.cylinder("Sleeve", 0.0, 0.0, r, 0.0, h - top, ELKO_SLEEVE, segments=32)
    b.cylinder("Top", 0.0, 0.0, max(0.1, r - 0.25), h - top, h, ALUMINIUM, segments=32)
    if polarized:
        outer = circle_points(0.0, 0.0, r + 0.02, 8, start=-30, end=30)
        inner = list(reversed(circle_points(0.0, 0.0, r - 0.05, 8, start=-30, end=30)))
        b.prism("Minus stripe", outer + inner, min(0.5, h / 4), max(min(0.5, h / 4) + 0.1, h - top - 0.4), ELKO_STRIPE)

    level = ipc.THT_LEVEL[ctx.density]
    ipc_name = naming.ipc_radial(kind, f, d.max, dn, h, level)
    house_type = "CAP POL" if polarized else "CAP"
    house_name = naming.house(f"{house_type} RAD D{naming.short_num(dn, 1)}x{naming.short_num(nom(H), 1)} "
                              f"P{naming.short_num(f)}", ctx.density)
    word = "Radial Polarized Capacitor" if polarized else "Radial Capacitor"
    description = describe(word, 2, dn, dn, ctx.density, pitch=f, extra=f"Height {h:.2f}mm")
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"Radial Ø{naming.short_num(dn, 1)} x {naming.short_num(nom(H), 1)} mm",
                      height=h, courtyard_kind="tht")


ALIAS_PARAMS = {
    "elko": {"kind": "CAPPRD"}, "cappr": {"kind": "CAPPRD"}, "capprd": {"kind": "CAPPRD"},
    "cp_radial": {"kind": "CAPPRD"}, "caprd": {"kind": "CAPRD"}, "bipolar_elko": {"kind": "CAPRD"},
}

# kind only changes the IPC prefix/house type (always distinct) and the polarity marking, never the land
FAMILIES = [FamilyDef(INFO, build, aliases=("radial_cap",), alias_params=ALIAS_PARAMS,
                      free_params=frozenset({"kind"}))]
