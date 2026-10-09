"""Axial through-hole parts mounted horizontally (resistors DIN 0204 … 0414, diodes DO-35/DO-41/DO-201).

Pin 1 (square) on the left; for diodes pin 1 = cathode by default (band on the pin-1 side).
Body dimensions: Yageo CFR (resistors, assignment to DIN sizes approximate) and typical diode outlines.
"""
from __future__ import annotations

from typing import Any

from ...geometry.model import FootprintSpec
from .. import ipc7351 as ipc
from .. import naming
from ..builder import AXIAL_RESISTOR, BLACK_BODY, DIODE_BAND, TIN
from ..geom import r6
from ..ipc7351 import fmt_mm
from ..models import FamilyInfo, Preset, Tol
from ..params import nom
from .base import COMMON_THT, FamilyDef, GenContext, describe, p_enum, p_float, p_tol

KINDS = {"R": ("RESAD", "RES", "Axial Resistor", AXIAL_RESISTOR), "D": ("DIOAD", "DIODE", "Axial Diode", BLACK_BODY),
         "C": ("CAPAD", "CAP", "Axial Capacitor", "#3C6E9E"), "L": ("INDAD", "IND", "Axial Inductor", "#4E7D4A")}

_SIZES: dict[str, dict[str, Any]] = {
    "DIN0204": {"kind": "R", "L": (2.9, 3.7), "D": (1.5, 2.1), "d": (0.45, 0.55), "pitches": (5.08, 7.62),
                "source": "Yageo CFR-12 (1/8 W), Zuordnung zu DIN 0204 genähert"},
    "DIN0207": {"kind": "R", "L": (5.8, 6.8), "D": (2.0, 2.6), "d": (0.55, 0.65), "pitches": (7.62, 10.16, 15.24),
                "source": "Yageo CFR-25 (1/4 W), Zuordnung zu DIN 0207 genähert"},
    "DIN0309": {"kind": "R", "L": (8.5, 9.5), "D": (2.7, 3.7), "d": (0.55, 0.65), "pitches": (12.7, 15.24),
                "source": "Yageo CFR-50 (1/2 W), Zuordnung zu DIN 0309 genähert"},
    "DIN0411": {"kind": "R", "L": (9.4, 10.4), "D": (3.3, 3.9), "d": (0.70, 0.85), "pitches": (12.7, 15.24),
                "source": "KiCad DIN0411 (L 9,9 / D 3,6), Toleranzen typisch"},
    "DIN0414": {"kind": "R", "L": (10.5, 12.5), "D": (4.0, 5.0), "d": (0.75, 0.85), "pitches": (15.24, 20.32),
                "source": "Yageo CFR100 (1 W), Zuordnung zu DIN 0414 genähert"},
    "DO-35": {"kind": "D", "L": (3.05, 5.08), "D": (1.53, 2.28), "d": (0.46, 0.56), "pitches": (7.62,),
              "source": "JEDEC DO-35, typische Werte"},
    "DO-41": {"kind": "D", "L": (4.06, 5.21), "D": (2.00, 2.71), "d": (0.71, 0.86), "pitches": (10.16,),
              "source": "JEDEC DO-41, typische Werte"},
    "DO-201AD": {"kind": "D", "L": (7.20, 9.50), "D": (4.80, 5.30), "d": (1.20, 1.30), "pitches": (15.24,),
                 "source": "JEDEC DO-201AD, typische Werte"},
}


def _presets() -> list[Preset]:
    out = []
    for size, d in _SIZES.items():
        for pitch in d["pitches"]:
            out.append(Preset(
                key=f"{size}-P{pitch:g}", label=f"{size}, Raster {pitch:g} mm".replace(".", ","), source=str(d["source"]),
                params={"kind": d["kind"], "size": size, "pitch": pitch,
                        **{k: {"min": d[k][0], "max": d[k][1]} for k in ("L", "D", "d")}},
            ))
    return out


PARAMS = [
    p_enum("kind", "Bauteilart", list(KINDS), default="R", group="Typ",
           help="R Widerstand, D Diode, C Kondensator, L Induktivität."),
    p_enum("size", "Bauform", list(_SIZES), group="Typ",
           help="Setzt die Standardmaße L, D, d und das Raster, soweit sie nicht angegeben sind."),
    p_float("pitch", "Rastermaß", default=10.16, minimum=2.54, maximum=60.0, group="Anschlüsse",
            help="Lochabstand Mitte–Mitte."),
    p_tol("L", "Körperlänge L", default={"min": 5.8, "max": 6.8}),
    p_tol("D", "Körperdurchmesser D", default={"min": 2.0, "max": 2.6}),
    p_tol("d", "Drahtdurchmesser d", group="Anschlüsse", default={"min": 0.55, "max": 0.65}),
    p_enum("cathode_pad", "Kathode an Pad", ["1", "2"], default="1", group="Optionen", help="Nur Dioden."),
    *COMMON_THT,
]

INFO = FamilyInfo(
    key="axial",
    label="Axial (liegend)",
    group="Bedrahtet",
    description="Axiale Bauteile liegend montiert (Widerstände, Dioden).",
    params=PARAMS,
    presets=_presets(),
    ipc_table="IPC-2222 / IPC-2221",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    size = p.enum("size") if p.given("size") else None
    base = _SIZES.get(size) if size else None
    if p.given("kind") or base is None:
        kind = p.enum("kind", "R")
    else:
        kind = str(base["kind"])
        p.resolved["kind"] = kind

    def dim(name: str) -> Tol:  # the size table supplies every dimension the request does not give
        return p.tol_or(name, Tol(min=base[name][0], max=base[name][1]) if base is not None else None)

    pitch = p.float_or("pitch", float(base["pitches"][0]) if base is not None else None)
    L, D, d = dim("L"), dim("D"), dim("d")  # noqa: N806
    if base is not None:
        off = [n for n, t in (("L", L), ("D", D), ("d", d))
               if ctx.any_explicit(n) and abs(nom(t) - sum(base[n]) / 2) > max(0.1, 0.1 * sum(base[n]) / 2)]
        if off:
            ctx.warn(f"Die Maße {', '.join(off)} passen nicht zur Bauform {size} – Name und Beschreibung nutzen "
                     f"trotzdem {size}, bitte prüfen.")
    if pitch < nom(L) + d.max:
        raise ValueError(f"Rastermaß {fmt_mm(pitch)} mm ist für die Körperlänge {fmt_mm(nom(L))} mm zu klein "
                         "(kein Platz zum Biegen der Anschlüsse).")
    if pitch < L.max + 2 * d.max:
        ctx.warn(f"Rastermaß {fmt_mm(pitch)} mm: bei maximaler Körperlänge {fmt_mm(L.max)} mm müssen die "
                 "Anschlüsse direkt am Körper gebogen werden.")
    land = ctx.tht_land(d.max, pitch)
    b = ctx.builder()
    b.tht_pad("1", -pitch / 2, 0.0, land.width, land.height, land.hole, shape="rect")
    b.tht_pad("2", pitch / 2, 0.0, land.width, land.height, land.hole,
              shape="oval" if land.shape == "oval" else "circle")
    ln, dn, wire = nom(L), nom(D), nom(d)
    body = b.body((-ln / 2, -dn / 2, ln / 2, dn / 2))
    b.silk_outline_outside(body)
    sw = b.silk_width
    b.silk_line((-pitch / 2, 0.0), (-ln / 2 - sw / 2, 0.0), min_len=0.1)
    b.silk_line((ln / 2 + sw / 2, 0.0), (pitch / 2, 0.0), min_len=0.1)
    mark = ctx.cathode_pad() if kind == "D" else None
    if mark:
        s = -1.0 if mark == "1" else 1.0
        x_band = s * (ln / 2 - max(0.3, 0.15 * ln))
        b.silk_line((x_band, -dn / 2), (x_band, dn / 2), min_len=0.0)
        b.line("assembly", (x_band, -dn / 2), (x_band, dn / 2), b.style.assembly_width)
    b.assembly_rect(body)

    prefix, house_type, word, color = KINDS[kind]
    band = max(0.3, 0.15 * ln)
    x1, x2 = -ln / 2, ln / 2
    if mark == "1":
        b.box("Cathode band", (x1, -dn / 2, x1 + band, dn / 2), 0.0, dn, DIODE_BAND)
        x1 += band
    elif mark == "2":
        b.box("Cathode band", (x2 - band, -dn / 2, x2, dn / 2), 0.0, dn, DIODE_BAND)
        x2 -= band
    b.box("Body", (x1, -dn / 2, x2, dn / 2), 0.0, dn, color)
    zc = dn / 2
    for s, name in ((-1.0, "1"), (1.0, "2")):
        xp, xe = s * pitch / 2, s * ln / 2
        b.box(f"Lead {name}", (min(xp, xe), -wire / 2, max(xp, xe), wire / 2), zc - wire / 2, zc + wire / 2, TIN)
        b.box(f"Lead {name} leg", (xp - wire / 2, -wire / 2, xp + wire / 2, wire / 2), 0.0, zc - wire / 2, TIN)

    level = ipc.THT_LEVEL[ctx.density]
    ipc_name = naming.ipc_axial(prefix, pitch, d.max, ln, dn, level)
    size_text = size if size else f"L{naming.short_num(ln, 1)} D{naming.short_num(dn, 1)}"
    house_name = naming.house(f"{house_type} AXIAL {size_text} P{naming.short_num(pitch)}", ctx.density)
    description = describe(word, 2, ln, dn, ctx.density, pitch=pitch)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"Axial {size_text}, Raster {r6(pitch):g} mm", height=dn, courtyard_kind="tht")


ALIAS_PARAMS = {
    **{size.replace("-", "").lower(): {"size": size} for size in _SIZES},  # din0207, do41, do201ad, ...
    "do201": {"size": "DO-201AD"},
    "resad": {"kind": "R"}, "dioad": {"kind": "D", "size": "DO-41"},
}

# kind only changes the IPC prefix/house type (always distinct) and the cathode marking, never the land
FAMILIES = [FamilyDef(INFO, build, aliases=("axial_horizontal",), alias_params=ALIAS_PARAMS,
                      free_params=frozenset({"kind"}))]
