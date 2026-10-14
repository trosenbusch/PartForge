"""DPAK (TO-252) and D2PAK (TO-263): gull-wing leads (left, table 3-2) and a large tab land
(right, flat lug table 3-14) with windowpane paste.

Leads: 2 (pins 1 and 3, tab = 2, like KiCad TO-252-2) or 3 (pins 1–3, tab = 4).
The tab land uses IPC-SM-782A tab lengths T2 (DPAK 4.00–5.50, D2PAK 8.00–9.00) unless given.
Dimensions: Vishay TO-252AA (doc 95627) / TO-263AB (doc 91364), both JEDEC-conformant (S21).
"""
from __future__ import annotations

from typing import Any

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import IC_BODY, TIN
from ..ipc7351 import fmt_mm, gullwing_table
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
    p_enum,
    p_float,
    p_tol,
)

VARIANTS: dict[str, dict[str, Any]] = {
    "DPAK": {"jedec": "TO-252", "e": 2.29, "dims": {
        "H": (9.40, 10.41), "L": (1.40, 1.78), "b": (0.64, 0.89), "D": (5.97, 6.22), "E": (6.35, 6.73),
        "L3": (0.89, 1.27), "b_tab": (4.95, 5.46), "T_tab": (4.00, 5.50), "A": (2.18, 2.39), "c": (0.46, 0.61)},
        "source": "Vishay TO-252AA (Dok. 95627), Laschenlänge nach IPC-SM-782A"},
    "D2PAK": {"jedec": "TO-263", "e": 2.54, "dims": {
        "H": (14.61, 15.88), "L": (1.78, 2.79), "b": (0.51, 0.99), "D": (8.38, 9.65), "E": (9.65, 10.67),
        "L3": (1.00, 1.40), "b_tab": (6.22, 6.86), "T_tab": (8.00, 9.00), "A": (4.06, 4.83), "c": (0.38, 0.74)},
        "source": "Vishay TO-263AB (Dok. 91364), Laschenmaße nach IPC-SM-782A; L3 typisch"},
}
_DIMS = ("H", "L", "b", "D", "E", "L3", "b_tab", "T_tab", "A", "c")


def _presets() -> list[Preset]:
    out = []
    for key, v in VARIANTS.items():
        dims = v["dims"]
        for leads in ("2", "3"):
            out.append(Preset(
                key=f"{key}-{leads}", label=f"{key} ({v['jedec']}-{leads})", source=str(v["source"]),
                params={"variant": key, "leads": leads, "e": v["e"],
                        **{k: {"min": r[0], "max": r[1]} for k, r in dims.items()}},
            ))
    return out


PARAMS = [
    p_enum("variant", "Bauform", list(VARIANTS), default="DPAK", group="Typ"),
    p_enum("leads", "Anschlüsse", ["2", "3"], default="2", group="Anschlüsse",
           help="2: Pins 1 und 3, Kühlfahne = 2 (TO-252-2); 3: Pins 1–3, Kühlfahne = 4."),
    p_float("e", "Raster e", minimum=1.0, maximum=5.0, group="Anschlüsse"),
    p_tol("H", "Gesamtlänge H", help="Anschlussspitzen bis Ende der Kühlfahne."),
    p_tol("L", "Fußlänge L", group="Anschlüsse"),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse"),
    p_tol("D", "Körperlänge D", help="Kunststoffkörper in Anschlussrichtung."),
    p_tol("E", "Körperbreite E"),
    p_tol("L3", "Überstand Kühlfahne L3", help="Überstand der Fahne über den Kunststoffkörper."),
    p_tol("b_tab", "Breite Kühlfahne", group="Anschlüsse"),
    p_tol("T_tab", "Länge Kühlfahnen-Lötfläche", group="Anschlüsse",
          help="Lötbare Länge der Fahne auf der Unterseite (IPC-SM-782A T2)."),
    p_tol("A", "Bauhöhe A"),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse"),
    p_float("paste_coverage", "Pastenbedeckung Kühlfahne", default=0.65, unit=None, minimum=0.3, maximum=1.0,
            group="Optionen", help="Anteil der Fläche mit Lotpaste (Fensterraster); 1 = volle Fläche."),
    *NAMING_PARAMS,
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="dpak",
    label="DPAK / D2PAK (TO-252/TO-263)",
    group="Transistoren (SOT/TO)",
    description="Leistungsgehäuse mit großer Kühlfahne und Fensterraster in der Pastenmaske.",
    params=PARAMS,
    presets=_presets(),
    ipc_table="3-2 / 3-14",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    variant = p.enum("variant", "DPAK")
    v = VARIANTS[variant]
    dims: dict[str, tuple[float, float]] = v["dims"]
    leads = int(p.enum("leads", "2"))
    e = p.float("e", float(v["e"]))
    H, L, b_, D, E, L3, b_tab, T_tab, A, c = (  # noqa: N806
        p.tol(n, Tol(min=dims[n][0], max=dims[n][1])) for n in _DIMS)
    if 2 * L.max >= H.min:
        raise ValueError("Fußlänge L ist zu groß für die Gesamtlänge H.")
    # leads at +e/-e (2 leads) or +e/0/-e (3 leads) across the body width E
    check_row_fits_body(ctx, pitch=e, positions=3, lead_width=b_, body=E, package=variant, body_symbol="E",
                        hint="Ist e im Datenblatt der Abstand der äußeren Anschlüsse (e1)? Dann das Raster angeben.")
    custom = differs_from(dims, {"H": H, "L": L, "b": b_, "D": D, "E": E, "A": A})
    table = gullwing_table(e)
    land = ctx.ipc_land(H, L, b_, table, label="Anschlüsse")
    ctx.finalize_land(land, pitch=2 * e if leads == 2 else e)
    # The tab land may extend past the centre (G < 0 is fine: the opposite side holds the leads).
    tab = ctx.ipc_land(H, T_tab, b_tab, "flat_lug", label="Kühlfahne", allow_override=False)
    if tab.z - tab.g <= 0.01:
        raise ValueError("Kühlfahne: keine sinnvolle Padlänge – bitte Laschenlänge prüfen.")
    if ctx.override is not None:  # the manufacturer pattern covers the leads only – never a silent hybrid
        ctx.warn("Herstellerempfehlung: Die Kühlfahne wird nach IPC-7351B berechnet – Größe und Lage bitte mit dem "
                 "Datenblatt vergleichen.")

    b = ctx.builder()
    c_ = land.pad_center
    if leads == 2:
        lead_pads = [("1", e), ("3", -e)]
        tab_des = "2"
    else:
        lead_pads = [("1", e), ("2", 0.0), ("3", -e)]
        tab_des = "4"
    pads = [b.smd_pad(des, -c_, y, land.pad_length, land.x) for des, y in lead_pads]
    gap = tab.g / 2 + land.g / 2
    if gap < ctx.min_gap:
        raise ValueError(f"Kühlfahne und Anschlüsse überlappen (Abstand {fmt_mm(gap)} mm) – bitte Maße prüfen.")
    tab_pad = b.smd_pad(tab_des, tab.pad_center, 0.0, tab.pad_length, tab.x, shape="rect", thermal=True)
    b.paste_windows(tab_pad, p.float("paste_coverage", 0.65), cell=2.5)

    hn, ln, dn, en, l3, h, cn = nom(H), nom(L), nom(D), nom(E), nom(L3), A.max, nom(c)
    x1 = hn / 2 - l3
    body = b.body((x1 - dn, -en / 2, x1, en / 2))
    ic_silk(b, body, [dot_above(b, pads[0])], push=(0.0, 1.0))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))
    b.box("Body", body, 0.0, h, IC_BODY)
    b.box("Tab", (x1 - 0.5, -nom(b_tab) / 2, hn / 2, nom(b_tab) / 2), 0.0, 0.5 * cn + 0.25, TIN)
    bn = nom(b_)
    for des, y in lead_pads:
        b.box(f"Lead {des}", (-hn / 2, y - bn / 2, x1 - dn + 0.1, y + bn / 2), 0.0, cn, TIN)
        b.box(f"Lead {des} leg", (-hn / 2 + ln, y - bn / 2, x1 - dn + 0.1, y + bn / 2), cn, 0.45 * h, TIN)

    jedec = str(v["jedec"])
    pins_total = leads + 1
    ipc_name = naming.ipc_pitch_span("TO", e, hn, h, pins_total, ctx.density)
    package = f"{jedec}-{leads} {variant}"
    house_name = naming.house(package + (f" {naming.house_body(en, dn)}" if custom else ""), ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe(f"{variant} ({jedec})", pins_total, dn, en, ctx.density, pitch=e)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=package + (" (angepasst)" if custom else ""), height=h, courtyard_table=table)


ALIAS_PARAMS = {
    "to252": {"variant": "DPAK"}, "to252aa": {"variant": "DPAK"},
    "d2pak": {"variant": "D2PAK"}, "to263": {"variant": "D2PAK"}, "to263ab": {"variant": "D2PAK"},
    "ddpak": {"variant": "D2PAK"},
}

FAMILIES = [FamilyDef(INFO, build, alias_params=ALIAS_PARAMS, free_params=frozenset({"c"}),
                      max_only=frozenset({"A"}))]
