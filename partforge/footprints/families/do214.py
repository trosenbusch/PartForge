"""SMA / SMB / SMC diodes (JEDEC DO-214AC/AA/AB, molded body with inward-formed L leads,
IPC-7351B table 3-13, IPC prefix DIOM). Dimensions: Diodes Inc. package outlines (S19)."""
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
    "SMA": {"jedec": "DO-214AC", "E": (4.80, 5.59), "D": (4.00, 4.60), "W": (2.29, 2.92), "b": (1.27, 1.63),
            "T": (0.76, 1.52), "A": (1.96, 2.40), "c": (0.15, 0.31)},
    "SMB": {"jedec": "DO-214AA", "E": (5.00, 5.59), "D": (4.06, 4.57), "W": (3.30, 3.94), "b": (1.96, 2.21),
            "T": (0.76, 1.52), "A": (2.00, 2.50), "c": (0.15, 0.31)},
    "SMC": {"jedec": "DO-214AB", "E": (7.75, 8.13), "D": (6.60, 7.11), "W": (5.59, 6.22), "b": (2.75, 3.18),
            "T": (0.76, 1.52), "A": (2.00, 2.50), "c": (0.15, 0.31)},
}
_DIMS = ("E", "D", "W", "b", "T", "A", "c")


def _presets() -> list[Preset]:
    return [
        Preset(key=key, label=f"{key} ({d['jedec']})", source="Diodes Inc. Gehäusezeichnung",
               params={"variant": key, **{k: {"min": d[k][0], "max": d[k][1]} for k in _DIMS}})
        for key, d in VARIANTS.items()
    ]


PARAMS = [
    p_enum("variant", "Bauform", list(VARIANTS), default="SMA", group="Typ"),
    p_tol("E", "Gesamtlänge E", help="Länge über die Anschlüsse (IPC L)."),
    p_tol("D", "Körperlänge D"),
    p_tol("W", "Körperbreite W"),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse"),
    p_tol("T", "Anschlusslänge T", group="Anschlüsse", help="Länge der Anschlussfahne auf der Unterseite."),
    p_tol("A", "Bauhöhe A"),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse"),
    p_enum("cathode_pad", "Kathode an Pad", ["1", "2"], default="1", group="Optionen",
           help="IPC: Kathode an Pad 1 (links)."),
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="do214",
    label="SMA / SMB / SMC (DO-214)",
    group="Dioden",
    description="Dioden und TVS im DO-214-Gehäuse (molded, nach innen gebogene Anschlüsse).",
    params=PARAMS,
    presets=_presets(),
    ipc_table="3-13",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    variant = p.enum("variant", "SMA")
    base = VARIANTS[variant]

    def dim(name: str) -> Tol:
        lo, hi = base[name]
        return p.tol_or(name, Tol(min=lo, max=hi))

    E, D, W, b_, T, A, c = (dim(n) for n in _DIMS)  # noqa: N806
    if nom(E) <= nom(D):
        raise ValueError(f"Die Gesamtlänge E ({fmt_mm(nom(E))} mm) muss größer als die Körperlänge D "
                         f"({fmt_mm(nom(D))} mm) sein – E ist die Länge über die Anschlüsse.")
    if 2 * T.max >= E.min:
        raise ValueError("Anschlusslänge T ist zu groß für die Gesamtlänge E (2·T ≥ E).")
    custom = differs_from(base, {"E": E, "D": D, "W": W, "b": b_, "T": T, "A": A})
    land = ctx.ipc_land(E, T, b_, "inward_l", label="Anschlüsse")
    ctx.finalize_land(land)
    mark = ctx.cathode_pad()
    b = ctx.builder()
    two_terminal(b, land, body_length=nom(D), body_width=nom(W), mark_pad=mark)

    dn, wn, en, bn, tn, cn, h = nom(D), nom(W), nom(E), nom(b_), nom(T), nom(c), A.max
    for sign, name in ((-1, "Lead 1"), (1, "Lead 2")):
        x_out, x_in = sign * en / 2, sign * (en / 2 - tn)
        b.box(name, (min(x_out, x_in), -bn / 2, max(x_out, x_in), bn / 2), 0.0, cn, TIN)
        x_body = sign * dn / 2
        b.box(f"{name} bend", (min(x_out, x_body), -bn / 2, max(x_out, x_body), bn / 2), cn, max(cn, 0.45 * h),
              TIN)
    split_body_3d(b, length=dn, width=wn, z0=cn, z1=h, color=BLACK_BODY, band_side=mark, band_fraction=0.12)

    ipc_name = naming.ipc_chip("DIOM", en, wn, h, ctx.density)
    jedec = str(base["jedec"])
    house_base = f"{jedec} {variant}" if not custom else f"{jedec} {variant} {naming.house_body(dn, wn)}"
    house_name = naming.house(house_base, ctx.density)
    description = describe(f"{variant} ({jedec})", 2, dn, wn, ctx.density)
    package = f"{variant} ({jedec})" + (" angepasst" if custom else "")
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description, package=package,
                      height=h, courtyard_table="inward_l")


ALIAS_PARAMS = {
    "sma": {"variant": "SMA"}, "do214ac": {"variant": "SMA"},
    "smb": {"variant": "SMB"}, "do214aa": {"variant": "SMB"},
    "smc": {"variant": "SMC"}, "do214ab": {"variant": "SMC"},
}

FAMILIES = [FamilyDef(INFO, build, aliases=("diom",), alias_params=ALIAS_PARAMS, free_params=frozenset({"c"}),
                      max_only=frozenset({"A"}))]
