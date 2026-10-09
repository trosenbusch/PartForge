"""SOT-223 (TO-261, SC-73): three gull-wing leads (left column, pin 1 top) and the wide tab lead
(pin 4) on the right. IPC-7351B table 3-2. Dimensions: Nexperia SOT223 (S20)."""
from __future__ import annotations

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import IC_BODY, TIN
from ..geom import rect_centered
from ..ipc7351 import gullwing_table
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
    "E": (6.7, 7.3), "E1": (3.3, 3.7), "D": (6.3, 6.7), "L": (0.7, 1.1), "b": (0.60, 0.80), "b1": (2.9, 3.1),
    "A": (1.5, 1.8), "A1": (0.01, 0.10), "c": (0.22, 0.32),
}
_DIMS = tuple(BASE)

PARAMS = [
    p_float("e", "Raster e", default=2.3, minimum=1.0, maximum=5.0, group="Anschlüsse"),
    p_tol("E", "Gesamtbreite E", help="Spannweite über die Anschlussspitzen (Nexperia: HE)."),
    p_tol("E1", "Körperbreite E1", help="Kunststoffkörper (Nexperia: E)."),
    p_tol("D", "Körperlänge D"),
    p_tol("L", "Fußlänge L", group="Anschlüsse"),
    p_tol("b", "Anschlussbreite b (Pin 1–3)", group="Anschlüsse"),
    p_tol("b1", "Breite Kühlfahne b1 (Pin 4)", group="Anschlüsse"),
    p_tol("A", "Bauhöhe A"),
    p_tol("A1", "Abstand A1"),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse"),
    *NAMING_PARAMS,
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="sot223",
    label="SOT-223",
    group="Transistoren (SOT/TO)",
    description="SOT-223 mit Kühlfahne (Pin 4).",
    params=PARAMS,
    presets=[Preset(key="SOT-223", label="SOT-223 (Nexperia)", source="Nexperia SOT223",
                    params={"e": 2.3, **{k: {"min": v[0], "max": v[1]} for k, v in BASE.items()}})],
    ipc_table="3-2",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    e = p.float("e", 2.3)
    E, E1, D, L, b_, b1, A, A1, c = (p.tol(n, Tol(min=BASE[n][0], max=BASE[n][1])) for n in _DIMS)  # noqa: N806
    if E1.max >= E.min:
        raise ValueError("Körperbreite E1 muss kleiner als die Gesamtbreite E sein.")
    custom = differs_from(BASE, {"E": E, "E1": E1, "D": D, "L": L, "b": b_, "b1": b1, "A": A})
    check_row_fits_body(ctx, pitch=e, positions=3, lead_width=b_, body=D, package="SOT-223", hint=PITCH_HINT)
    table = gullwing_table(e)
    land = ctx.ipc_land(E, L, b_, table, label="Anschlüsse 1–3")
    ctx.finalize_land(land, pitch=e)
    tab = ctx.ipc_land(E, L, b1, table, label="Kühlfahne (Pin 4)", allow_override=False)
    ctx.finalize_land(tab, what="Kühlfahne")

    b = ctx.builder()
    c_ = land.pad_center
    pad1 = b.smd_pad("1", -c_, e, land.pad_length, land.x)
    b.smd_pad("2", -c_, 0.0, land.pad_length, land.x)
    b.smd_pad("3", -c_, -e, land.pad_length, land.x)
    b.smd_pad("4", tab.pad_center, 0.0, tab.pad_length, tab.x)
    en, e1n, dn, h, a1, cn = nom(E), nom(E1), nom(D), A.max, nom(A1), nom(c)
    body = b.body(rect_centered(0, 0, e1n, dn))
    ic_silk(b, body, [dot_above(b, pad1)], push=(0.0, 1.0))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))
    b.box("Body", body, max(a1, cn), h, IC_BODY)
    for des, y, width, sign in (("1", e, nom(b_), -1), ("2", 0.0, nom(b_), -1), ("3", -e, nom(b_), -1),
                                ("4", 0.0, nom(b1), 1)):
        x_in, x_out = sign * (e1n / 2 - 0.05), sign * en / 2
        b.box(f"Lead {des}", (min(x_in, x_out), y - width / 2, max(x_in, x_out), y + width / 2), 0.0, cn, TIN)

    ipc_name = naming.ipc_pitch_span("SOT", e, en, h, 4, ctx.density)
    house_name = naming.house("SOT-223" + (f" {naming.house_body(e1n, dn)}" if custom else ""), ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe("SOT223", 4, dn, e1n, ctx.density, pitch=e)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package="SOT-223" + (" (angepasst)" if custom else ""), height=h, courtyard_table=table)


FAMILIES = [FamilyDef(INFO, build, aliases=("sot-223", "to261", "sc73", "sot223-4"),
                      free_params=frozenset({"A1", "c"}), max_only=frozenset({"A"}))]
