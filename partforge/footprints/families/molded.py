"""Molded two-terminal bodies with inward-formed L leads: tantalum capacitors (CAPMP), molded
inductors (INDM), fuses (FUSM) and diodes (DIOM).

KEMET T491 case dimensions (S17): L, W, H, F = terminal width (IPC W), S = terminal length (IPC T).
IPC-7351B table 3-13 (default) or IPC-7352 inward L (KiCad tantalum footprints, rounding 0.01 mm).
"""
from __future__ import annotations

from typing import Any

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import BLACK_BODY, TANTALUM_BAND, TANTALUM_BODY, TIN
from ..models import FamilyInfo, Preset, Tol
from ..params import nom
from .base import COMMON_SMD, FamilyDef, GenContext, describe, p_enum, p_tol, two_terminal

_KEMET = "KEMET T491 (Tantal, Gehäuse nach EIA 535BAAC)"

CASES: dict[str, dict[str, Any]] = {
    "A": {"eia": "3216-18", "imperial": "1206", "L": (3.0, 3.4), "W": (1.4, 1.8), "H": (1.4, 1.8),
          "F": (1.1, 1.3), "S": (0.5, 1.0)},
    "B": {"eia": "3528-21", "imperial": "1411", "L": (3.3, 3.7), "W": (2.6, 3.0), "H": (1.7, 2.1),
          "F": (2.1, 2.3), "S": (0.5, 0.9)},
    "C": {"eia": "6032-28", "imperial": "2312", "L": (5.7, 6.3), "W": (2.9, 3.5), "H": (2.2, 2.8),
          "F": (2.1, 2.3), "S": (1.0, 1.6)},
    "D": {"eia": "7343-31", "imperial": "2917", "L": (7.0, 7.6), "W": (4.0, 4.6), "H": (2.5, 3.1),
          "F": (2.3, 2.5), "S": (1.0, 1.6)},
}

KINDS = {
    "CAPMP": ("Tantal-/Polymerkondensator", "Molded Tantalum Capacitor", "CAP POL"),
    "INDM": ("Induktivität (molded)", "Molded Inductor", "IND"),
    "FUSM": ("Sicherung (molded)", "Molded Fuse", "FUSE"),
    "DIOM": ("Diode (molded)", "Molded Diode", "DIODE"),
}


def _presets() -> list[Preset]:
    out = []
    for case, d in CASES.items():
        out.append(Preset(
            key=f"Tantal-{case}",
            label=f"Tantal Gehäuse {case} (EIA {d['eia']})",
            source=_KEMET,
            params={"kind": "CAPMP", "case": case,
                    **{k: {"min": d[k][0], "max": d[k][1]} for k in ("L", "W", "H", "F", "S")}},
        ))
    return out


PARAMS = [
    p_enum("kind", "Bauteilart", list(KINDS), default="CAPMP", group="Typ",
           help="CAPMP Tantal/Polymer (gepolt, Pin 1 = Plus), INDM Induktivität, FUSM Sicherung, DIOM Diode."),
    p_enum("case", "Gehäusecode", list(CASES), group="Typ", help="EIA-Gehäuse A/B/C/D (setzt Standardmaße)."),
    p_tol("L", "Gesamtlänge L", help="Länge über die Anschlüsse."),
    p_tol("W", "Körperbreite W"),
    p_tol("H", "Bauhöhe H"),
    p_tol("F", "Anschlussbreite F", group="Anschlüsse", help="Breite der Anschlussfahne (IPC W)."),
    p_tol("S", "Anschlusslänge S", group="Anschlüsse", help="Länge der Anschlussfahne unter dem Körper (IPC T)."),
    p_enum("ipc_table", "Berechnungsbasis", ["7351B", "7352"], default="7351B", group="Optionen",
           help="7351B: Tabelle 3-13; 7352: IPC-7352 (wie KiCad-Tantal-Footprints)."),
    p_enum("cathode_pad", "Kathode an Pad", ["1", "2"], default="1", group="Optionen",
           help="Nur Dioden (DIOM). Tantal: Pin 1 ist immer Plus."),
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="molded",
    label="Molded-Gehäuse (Tantal, Induktivität)",
    group="Chip-Bauteile",
    description="Gespritzte Zweipoler mit nach innen gebogenen Anschlüssen (Tantal A–D, CAPMP/INDM).",
    params=PARAMS,
    presets=_presets(),
    ipc_table="3-13",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    kind = p.enum("kind", "CAPMP")
    case = p.enum("case") if p.given("case") else None
    base = CASES.get(case) if case else (CASES["A"] if not p.given("L") else None)
    if base is not None and case is None:
        case = "A"
        p.resolved["case"] = case

    def dim(name: str) -> Tol:
        default = None
        if base is not None:
            lo, hi = base[name]
            default = Tol(min=lo, max=hi)
        return p.tol(name, default)

    L, W, H, F, S = (dim(n) for n in ("L", "W", "H", "F", "S"))  # noqa: N806
    if 2 * S.max >= L.min:
        raise ValueError("Anschlusslänge S ist zu groß für die Gesamtlänge L (2·S ≥ L).")
    table = "inward_l_7352" if p.enum("ipc_table", "7351B") == "7352" else "inward_l"
    land = ctx.ipc_land(L, S, F, table, label="Anschlüsse")
    ctx.finalize_land(land)

    if kind == "CAPMP":
        mark = "1"
    elif kind == "DIOM":
        mark = ctx.cathode_pad()
    else:
        mark = None
    b = ctx.builder(small_silk=True)
    two_terminal(b, land, body_length=nom(L), body_width=nom(W), mark_pad=mark)

    # 3D: J-lead terminations folded under the body, body (+ polarity band at pin 1 for tantalum)
    ln, wn, fn, sn, h = nom(L), nom(W), nom(F), nom(S), H.max
    t = 0.1
    body_color = TANTALUM_BODY if kind == "CAPMP" else BLACK_BODY
    for sign, label in ((-1, "1"), (1, "2")):
        x_out = sign * ln / 2
        x_in = sign * (ln / 2 - sn)
        b.box(f"Terminal {label}", (min(x_out, x_in), -fn / 2, max(x_out, x_in), fn / 2), 0.0, t, TIN)
        x_face = sign * (ln / 2 - t)
        b.box(f"Terminal {label} face", (min(x_out, x_face), -fn / 2, max(x_out, x_face), fn / 2), t, 0.55 * h, TIN)
    x1, x2 = -ln / 2 + t, ln / 2 - t
    if mark in ("1", "2"):
        band = 0.15 * ln
        band_color = TANTALUM_BAND if kind == "CAPMP" else "#B8BCC2"
        if mark == "1":
            b.box("Polarity band", (x1, -wn / 2, x1 + band, wn / 2), t, h, band_color)
            x1 += band
        else:
            b.box("Polarity band", (x2 - band, -wn / 2, x2, wn / 2), t, h, band_color)
            x2 -= band
    b.box("Body", (x1, -wn / 2, x2, wn / 2), t, h, body_color)

    _, family_word, house_type = KINDS[kind]
    ipc_name = naming.ipc_chip(kind, ln, wn, h, ctx.density)
    if case and base is not None:
        size_text = f"{base['imperial']}_{str(base['eia']).split('-')[0]}"
        package = f"Gehäuse {case} (EIA {base['eia']})"
    else:
        size_text = naming.house_body(ln, wn)
        package = f"{ln:.2f}x{wn:.2f} mm"
    house_name = naming.house_passive(house_type, size_text, ctx.density)
    description = describe(family_word, 2, ln, wn, ctx.density)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description, package=package,
                      height=h, courtyard_table=table)


ALIAS_PARAMS = {
    "tantalum": {"kind": "CAPMP"}, "tantal": {"kind": "CAPMP"}, "capmp": {"kind": "CAPMP"},
    "indm": {"kind": "INDM"}, "fusm": {"kind": "FUSM"},
}

# kind only changes the IPC prefix/house type (always distinct) and the polarity marking, never the land;
# the height enters the footprint (3D, IPC name) only as its maximum.
FAMILIES = [FamilyDef(INFO, build, aliases=("molded_body",), alias_params=ALIAS_PARAMS,
                      free_params=frozenset({"kind"}), max_only=frozenset({"H"}))]
