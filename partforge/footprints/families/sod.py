"""SOD diodes: SOD-123 / SOD-323 (gull wing, table 3-2) and SOD-123F / SOD-523 / SOD-923 (flat leads,
table 3-22, IPC prefix SODFL). Pin 1 = cathode (IPC zero orientation: cathode on the left)."""
from __future__ import annotations

from typing import Any

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import BLACK_BODY, TIN
from ..ipc7351 import fmt_mm
from ..models import FamilyInfo, Preset, Tol
from ..params import nom
from .base import (
    COMMON_SMD,
    FamilyDef,
    GenContext,
    describe,
    differs_from,
    p_enum,
    p_tol,
    split_body_3d,
    two_terminal,
)

VARIANTS: dict[str, dict[str, Any]] = {
    "SOD-123": {"lead": "gullwing", "HE": (3.55, 3.85), "D": (2.55, 2.85), "E": (1.40, 1.70), "b": (0.52, 0.62),
                "L": (0.25, 0.40), "A": (1.00, 1.35), "c": (0.10, 0.15), "source": "Diodes Inc. SOD123"},
    "SOD-123F": {"lead": "flat", "HE": (3.4, 3.6), "D": (2.5, 2.7), "E": (1.5, 1.7), "b": (0.55, 0.70),
                 "L": (0.35, 0.55), "A": (1.0, 1.2), "c": (0.10, 0.25), "source": "Nexperia SOD123F"},
    "SOD-323": {"lead": "gullwing", "HE": (2.3, 2.7), "D": (1.6, 1.8), "E": (1.15, 1.35), "b": (0.25, 0.40),
                "L": (0.15, 0.45), "A": (0.8, 1.1), "c": (0.10, 0.25), "source": "Nexperia SOD323 (SC-76)"},
    "SOD-523": {"lead": "flat", "HE": (1.55, 1.70), "D": (1.15, 1.25), "E": (0.75, 0.85), "b": (0.26, 0.34),
                "L": (0.10, 0.30), "A": (0.58, 0.65), "c": (0.11, 0.17), "source": "Nexperia SOD523 (SC-79)"},
    "SOD-923": {"lead": "flat", "HE": (0.95, 1.05), "D": (0.75, 0.85), "E": (0.55, 0.65), "b": (0.15, 0.25),
                "L": (0.07, 0.19), "A": (0.36, 0.43), "c": (0.07, 0.13),
                "source": "MCC/onsemi SOD-923 – typische Werte, bitte Datenblatt prüfen"},
}
_DIMS = ("HE", "D", "E", "b", "L", "A", "c")
SMALL_BODY = 1.55  # mm body length below which KiCad mode rounds to 0.02 mm (SOD-523, SOD-923)


def _presets() -> list[Preset]:
    return [
        Preset(key=key, label=key, source=str(d["source"]),
               params={"variant": key, "lead_style": d["lead"],
                       **{k: {"min": d[k][0], "max": d[k][1]} for k in _DIMS}})
        for key, d in VARIANTS.items()
    ]


PARAMS = [
    p_enum("variant", "Bauform", list(VARIANTS), default="SOD-123", group="Typ"),
    p_enum("lead_style", "Anschlussform", ["gullwing", "flat"], group="Typ",
           help="gullwing: gebogene Beinchen (IPC-Tabelle 3-2); flat: flache Anschlüsse (Tabelle 3-22, SODFL)."),
    p_tol("HE", "Gesamtlänge HE", help="Länge über die Anschlussspitzen (IPC L)."),
    p_tol("D", "Körperlänge D"),
    p_tol("E", "Körperbreite E"),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse"),
    p_tol("L", "Fußlänge L", group="Anschlüsse", help="Auflagelänge des Anschlusses (IPC T)."),
    p_tol("A", "Bauhöhe A"),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.1, "max": 0.2}),
    p_enum("cathode_pad", "Kathode an Pad", ["1", "2"], default="1", group="Optionen",
           help="IPC: Kathode an Pad 1 (links)."),
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="sod",
    label="SOD-Dioden (123/123F/323/523/923)",
    group="Dioden",
    description="Dioden im SOD-Gehäuse mit Gull-Wing- oder flachen Anschlüssen.",
    params=PARAMS,
    presets=_presets(),
    ipc_table="3-2 / 3-22",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    variant = p.enum("variant", "SOD-123")
    base = VARIANTS[variant]
    lead_style = p.enum("lead_style") if p.given("lead_style") else str(base["lead"])
    p.resolved["lead_style"] = lead_style

    def dim(name: str) -> Tol:
        lo, hi = base[name]
        return p.tol_or(name, Tol(min=lo, max=hi))

    HE, D, E, b_, L, A, c = (dim(n) for n in _DIMS)  # noqa: N806
    custom = differs_from(base, {"HE": HE, "D": D, "E": E, "b": b_, "L": L, "A": A})
    if nom(HE) <= nom(D):
        raise ValueError(f"Die Gesamtlänge HE ({fmt_mm(nom(HE))} mm) muss größer als die Körperlänge D "
                         f"({fmt_mm(nom(D))} mm) sein – HE ist die Länge über die Anschlussspitzen "
                         "(bei manchen Herstellern H), E die Körperbreite.")
    if 2 * L.max >= HE.min:
        raise ValueError("Fußlänge L ist zu groß für die Gesamtlänge HE (2·L ≥ HE).")
    table = "flat_lead" if lead_style == "flat" else "gullwing"
    # KiCad rounding: 0.02 mm grid for parts smaller than 0603 (as for chips < 0603, ipc-work/examples.md)
    small = ctx.rounding == "kicad" and lead_style == "flat" and nom(D) < SMALL_BODY
    land = ctx.ipc_land(HE, L, b_, table, label="Anschlüsse", base=0.02 if small else None)
    ctx.finalize_land(land)
    mark = ctx.cathode_pad()
    b = ctx.builder()
    two_terminal(b, land, body_length=nom(D), body_width=nom(E), mark_pad=mark)

    dn, en, hen, bn, cn, h = nom(D), nom(E), nom(HE), nom(b_), nom(c), A.max
    lead_start = dn / 2 - (nom(L) if lead_style == "flat" else 0.1)
    for sign, name in ((-1, "Lead 1"), (1, "Lead 2")):
        x_a, x_b = sign * lead_start, sign * hen / 2
        b.box(name, (min(x_a, x_b), -bn / 2, max(x_a, x_b), bn / 2), 0.0, cn, TIN)
    z0 = cn if lead_style == "flat" else min(0.05, cn)
    split_body_3d(b, length=dn, width=en, z0=z0, z1=h, color=BLACK_BODY, band_side=mark)

    prefix = "SODFL" if lead_style == "flat" else "SOD"
    ipc_name = naming.ipc_sod(prefix, hen, en, h, ctx.density)
    package = f"{variant} (angepasst)" if custom else variant
    house_name = naming.house(variant if not custom else f"{variant} {naming.house_body(dn, en)}", ctx.density)
    description = describe(variant.replace("-", ""), 2, dn, en, ctx.density)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description, package=package,
                      height=h, courtyard_table=table)


ALIAS_PARAMS = {
    "sod123": {"variant": "SOD-123"}, "sod123f": {"variant": "SOD-123F"}, "sod323": {"variant": "SOD-323"},
    "sc76": {"variant": "SOD-323"}, "sod523": {"variant": "SOD-523"}, "sc79": {"variant": "SOD-523"},
    "sod923": {"variant": "SOD-923"}, "sodfl": {"variant": "SOD-123F", "lead_style": "flat"},
}

FAMILIES = [FamilyDef(INFO, build, alias_params=ALIAS_PARAMS, free_params=frozenset({"c"}),
                      max_only=frozenset({"A"}))]
