"""SOT-89 (TO-243, SC-62): three flat leads on one side, collector tab connected to pin 2.

Leads in the left column (pin 1 top), land per IPC-7351B table 3-22 (flat leads, SOTFL).
Pad 2 is a single rectangle covering the centre lead and the tab (no duplicate designators);
its width is limited so that pads 1 and 3 keep the minimum copper gap.
Dimensions: Nexperia SOT89 (S20).
"""
from __future__ import annotations

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import IC_BODY, TIN
from ..ipc7351 import fmt_mm, land as ipc_land_calc, round_down
from ..models import FamilyInfo, Preset, Tol
from ..params import nom
from .base import (
    COMMON_SMD,
    NAMING_PARAMS,
    FamilyDef,
    GenContext,
    check_row_fits_body,
    describe,
    differs_from,
    dot_above,
    ic_silk,
    p_float,
    p_tol,
)
from .sot import PITCH_HINT

BASE: dict[str, tuple[float, float]] = {
    "HE": (3.75, 4.25), "E": (2.4, 2.6), "D": (4.4, 4.6), "L": (0.8, 1.2), "b": (0.35, 0.48), "b2": (0.40, 0.53),
    "b3": (1.4, 1.8), "A": (1.4, 1.6), "c": (0.23, 0.44),
}
_DIMS = tuple(BASE)

PARAMS = [
    p_float("e", "Raster e", default=1.5, minimum=1.0, maximum=3.0, group="Anschlüsse",
            help="Abstand benachbarter Anschlüsse (Pin 1 – Pin 2)."),
    p_tol("HE", "Gesamtlänge HE", help="Anschlussspitzen bis Ende der Kühlfahne."),
    p_tol("E", "Körperbreite E", help="Kunststoffkörper in Anschlussrichtung."),
    p_tol("D", "Körperlänge D"),
    p_tol("L", "Anschlusslänge L", group="Anschlüsse", help="Länge der Anschlüsse außerhalb des Körpers (Lp)."),
    p_tol("b", "Anschlussbreite b (Pin 1/3)", group="Anschlüsse"),
    p_tol("b2", "Anschlussbreite b2 (Pin 2)", group="Anschlüsse"),
    p_tol("b3", "Breite Kühlfahne b3", group="Anschlüsse"),
    p_tol("A", "Bauhöhe A"),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse"),
    *NAMING_PARAMS,
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="sot89",
    label="SOT-89",
    group="Transistoren (SOT/TO)",
    description="SOT-89 (TO-243) mit großer Kühlfahne an Pin 2.",
    params=PARAMS,
    presets=[Preset(key="SOT-89-3", label="SOT-89-3 (Nexperia SOT89)", source="Nexperia SOT89",
                    params={"e": 1.5, **{k: {"min": v[0], "max": v[1]} for k, v in BASE.items()}})],
    ipc_table="3-22",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    e = p.float("e", 1.5)
    HE, E, D, L, b_, b2, b3, A, c = (p.tol(n, Tol(min=BASE[n][0], max=BASE[n][1])) for n in _DIMS)  # noqa: N806
    custom = differs_from(BASE, {"HE": HE, "E": E, "D": D, "L": L, "b": b_, "b3": b3, "A": A})
    check_row_fits_body(ctx, pitch=e, positions=3, lead_width=b_, body=D, package="SOT-89", hint=PITCH_HINT)
    land = ctx.ipc_land(HE, L, b_, "flat_lead", label="Anschlüsse 1/3")
    ctx.finalize_land(land, pitch=e)
    tab = ipc_land_calc(HE, L, b3, table="flat_lead", density=ctx.density, F=ctx.F, P=ctx.P,
                        rounding=ctx.rounding, label="Pad 2 (Kühlfahne)")
    tab.z, tab.g = land.z, land.g
    limit = round_down(2 * (e - land.x / 2 - ctx.min_gap), 0.01)
    if tab.x > limit:
        msg = (f"Pad 2 (Kühlfahne) von {fmt_mm(tab.x)} mm auf {fmt_mm(limit)} mm Breite begrenzt, damit "
               f"Pin 1/3 den Mindestabstand {fmt_mm(ctx.min_gap)} mm einhalten.")
        tab.clamps.append(msg)
        tab.x = limit
        ctx.warn(msg)
    ctx.lands.append(tab)

    b = ctx.builder()
    c_ = land.pad_center
    pad1 = b.smd_pad("1", -c_, e, land.pad_length, land.x)
    b.smd_pad("2", 0.0, 0.0, land.z, tab.x)
    b.smd_pad("3", -c_, -e, land.pad_length, land.x)

    hen, en, dn, ln, h, cn = nom(HE), nom(E), nom(D), nom(L), A.max, nom(c)
    x0 = -hen / 2 + ln  # body edge on the lead side
    body = b.body((x0, -dn / 2, x0 + en, dn / 2))
    ic_silk(b, body, [dot_above(b, pad1), (x0 - 0.5, dn / 2 + 0.4)], push=(0.0, 1.0))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))
    b.box("Body", body, cn, h, IC_BODY)
    for des, y, width in (("1", e, nom(b_)), ("2", 0.0, nom(b2)), ("3", -e, nom(b_))):
        b.box(f"Lead {des}", (-hen / 2, y - width / 2, x0 + 0.2, y + width / 2), 0.0, cn, TIN)
    b.box("Tab", (x0 + 0.2, -nom(b3) / 2, hen / 2, nom(b3) / 2), 0.0, cn, TIN)

    ipc_name = f"SOT89{ctx.density}"
    house_name = naming.house("SOT-89-3" + (f" {naming.house_body(en, dn)}" if custom else ""), ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe("SOT89", 3, dn, en, ctx.density, pitch=e)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package="SOT-89-3" + (" (angepasst)" if custom else ""), height=h,
                      courtyard_table="flat_lead")


# the name "SOT89<density>" carries no dimension: height, lead thickness and pin-2 lead width are 3D only
FAMILIES = [FamilyDef(INFO, build, aliases=("sot-89", "to243", "sc62", "sot89-3"),
                      free_params=frozenset({"A", "c", "b2"}))]
