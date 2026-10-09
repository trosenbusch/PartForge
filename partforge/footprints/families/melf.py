"""MELF / MiniMELF / MicroMELF (cylindrical end caps, IPC-7351B table 3-7).

Vishay MMU 0102 / MMA 0204 / MMB 0207 (S18) and Diodes MiniMELF (SOD-80) / MELF (DO-213AB) (S19).
L = body length, D = diameter (IPC W), K = end-cap length (IPC T).
"""
from __future__ import annotations

from typing import Any

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import BLACK_BODY, MELF_GLASS, MELF_RESISTOR, TIN
from ..models import FamilyInfo, Preset, Tol
from ..params import nom
from .base import COMMON_SMD, FamilyDef, GenContext, describe, p_enum, p_tol, two_terminal

SIZES: dict[str, dict[str, Any]] = {
    "MicroMELF 0102": {"kind": "R", "L": (2.1, 2.2), "D": (1.0, 1.1), "K": (0.35, 0.45),
                       "source": "Vishay MMU 0102"},
    "MiniMELF 0204": {"kind": "R", "L": (3.4, 3.6), "D": (1.3, 1.4), "K": (0.7, 0.9), "source": "Vishay MMA 0204"},
    "MELF 0207": {"kind": "R", "L": (5.65, 5.8), "D": (2.0, 2.2), "K": (1.05, 1.25), "source": "Vishay MMB 0207"},
    "MiniMELF SOD-80": {"kind": "D", "L": (3.3, 3.7), "D": (1.3, 1.6), "K": (0.28, 0.50),
                        "source": "Diodes Inc. MiniMELF (SOD-80, LL-34)"},
    "MELF DO-213AB": {"kind": "D", "L": (4.8, 5.2), "D": (2.4, 2.6), "K": (0.45, 0.65),
                      "source": "Diodes Inc. MELF (DO-213AB, LL-41); Kappe K typisch 0,55 mm"},
}
_HOUSE = {"MicroMELF 0102": "MICROMELF 0102", "MiniMELF 0204": "MINIMELF 0204", "MELF 0207": "MELF 0207",
          "MiniMELF SOD-80": "MINIMELF SOD-80", "MELF DO-213AB": "MELF DO-213AB"}


def _presets() -> list[Preset]:
    return [
        Preset(key=key.replace(" ", "-"), label=key, source=str(d["source"]),
               params={"size": key, "kind": d["kind"],
                       **{k: {"min": d[k][0], "max": d[k][1]} for k in ("L", "D", "K")}})
        for key, d in SIZES.items()
    ]


PARAMS = [
    p_enum("kind", "Bauteilart", ["R", "D"], default="R", group="Typ", help="R Widerstand, D Diode."),
    p_enum("size", "Bauform", list(SIZES), group="Typ"),
    p_tol("L", "Körperlänge L"),
    p_tol("D", "Durchmesser D"),
    p_tol("K", "Kappenlänge K", group="Anschlüsse", help="Länge der metallischen Endkappe (IPC T)."),
    p_enum("cathode_pad", "Kathode an Pad", ["1", "2"], default="1", group="Optionen",
           help="Nur Dioden: IPC = Kathode an Pad 1 (links)."),
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="melf",
    label="MELF (Micro/Mini/MELF)",
    group="Chip-Bauteile",
    description="Zylindrische Bauteile mit Endkappen (Widerstände, Dioden).",
    params=PARAMS,
    presets=_presets(),
    ipc_table="3-7",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    size = p.enum("size") if p.given("size") else (None if p.given("L") else "MiniMELF 0204")
    base = SIZES.get(size) if size else None
    if size and "size" not in p.resolved:
        p.resolved["size"] = size
    if p.given("kind") or base is None:
        kind = p.enum("kind", "R")
    else:
        kind = str(base["kind"])
        p.resolved["kind"] = kind

    def dim(name: str) -> Tol:
        default = None
        if base is not None:
            lo, hi = base[name]
            default = Tol(min=lo, max=hi)
        return p.tol(name, default)

    L, D, K = dim("L"), dim("D"), dim("K")  # noqa: N806
    if 2 * K.max >= L.min:
        raise ValueError("Kappenlänge K ist zu groß für die Körperlänge L (2·K ≥ L).")
    land = ctx.ipc_land(L, K, D, "melf", label="Endkappen")
    ctx.finalize_land(land)
    mark = ctx.cathode_pad() if kind == "D" else None
    b = ctx.builder(small_silk=True)
    two_terminal(b, land, body_length=nom(L), body_width=nom(D), mark_pad=mark)

    ln, dn, kn = nom(L), nom(D), nom(K)
    h = D.max
    b.box("Cap 1", (-ln / 2, -dn / 2, -ln / 2 + kn, dn / 2), 0.0, h, TIN)
    b.box("Cap 2", (ln / 2 - kn, -dn / 2, ln / 2, dn / 2), 0.0, h, TIN)
    x1, x2 = -ln / 2 + kn, ln / 2 - kn
    if mark is not None:
        band = max(0.1, 0.12 * ln)
        if mark == "1":
            b.box("Cathode band", (x1, -dn / 2, x1 + band, dn / 2), 0.0, h, BLACK_BODY)
            x1 += band
        else:
            b.box("Cathode band", (x2 - band, -dn / 2, x2, dn / 2), 0.0, h, BLACK_BODY)
            x2 -= band
    b.box("Body", (x1, -dn / 2, x2, dn / 2), 0.0, h, MELF_GLASS if kind == "D" else MELF_RESISTOR)

    prefix = "DIOMELF" if kind == "D" else "RESMELF"
    ipc_name = naming.ipc_melf(prefix, ln, dn, ctx.density)
    house_base = _HOUSE.get(size, f"MELF {naming.house_body(ln, dn)}") if size else f"MELF {naming.house_body(ln, dn)}"
    native_kind = str(base["kind"]) if base is not None else "R"
    if kind != native_kind:  # e.g. a diode in a resistor body size: the type must be visible in the name
        house_base = ("DIODE " if kind == "D" else "RES ") + house_base
    house_name = naming.house(house_base, ctx.density)
    word = "MELF Diode" if kind == "D" else "MELF Resistor"
    description = describe(word, 2, ln, dn, ctx.density)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=size or f"MELF {ln:.2f}x{dn:.2f} mm", height=h, courtyard_table="melf")


ALIAS_PARAMS = {
    "micromelf": {"size": "MicroMELF 0102"}, "mmu0102": {"size": "MicroMELF 0102"},
    "minimelf": {"size": "MiniMELF 0204"}, "mma0204": {"size": "MiniMELF 0204"},
    "mmb0207": {"size": "MELF 0207"},
    "sod80": {"size": "MiniMELF SOD-80"}, "ll34": {"size": "MiniMELF SOD-80"},
    "do213ab": {"size": "MELF DO-213AB"}, "ll41": {"size": "MELF DO-213AB"},
    "resmelf": {"kind": "R"}, "diomelf": {"kind": "D", "size": "MiniMELF SOD-80"},
}

FAMILIES = [FamilyDef(INFO, build, alias_params=ALIAS_PARAMS)]
