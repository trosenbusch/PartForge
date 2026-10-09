"""No-lead packages: QFN (4 sides, table 3-15) and DFN/SON (2 sides, table 3-16) with exposed pad.

KiCad rule: the heel side keeps 0.2 mm to the exposed pad (G >= EP + 0.4). The EP gets windowpane
paste apertures (~65 % coverage, KiCad algorithm). The EP designator follows the house style
(``n+1`` or ``EP``) unless ``ep_name`` is given.

Irregular packages (e.g. TI RGY0019B, VQFN-19 3.5×4.5): ``pins_x``/``pins_y`` give the positions per side, ``e_x`` the
pitch of the top/bottom rows when it differs from ``e``, ``pin1 = "top"`` puts pin 1 at the left end of the top side
and ``missing`` lists positions without terminal (counted from pin 1 as if every position had one) – the pins are
numbered consecutively over the remaining positions.
"""
from __future__ import annotations

from collections.abc import Mapping

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import IC_BODY, TIN
from ..geom import rect_centered
from ..ipc7351 import fmt_mm
from ..models import FamilyInfo, Preset
from ..params import ParamError, nom
from .base import (
    COMMON_SMD,
    NAMING_PARAMS,
    FamilyDef,
    GenContext,
    check_row_fits_body,
    describe,
    dot_above,
    dot_corner,
    dot_left,
    dual_row,
    ep_size,
    ic_silk,
    missing_positions,
    p_enum,
    p_float,
    p_int,
    p_text,
    p_tol,
    quad,
)
from .qfp import side_counts

VARIANTS = ["QFN", "DFN", "SON"]


def _preset(key: str, label: str, source: str, variant: str, pins: int, e: float,
            dims: Mapping[str, tuple[float, float]]) -> Preset:
    return Preset(key=key, label=label, source=source,
                  params={"variant": variant, "pins": pins, "e": e,
                          **{k: {"min": v[0], "max": v[1]} for k, v in dims.items()}})


def _qfn(pins: int, size: float, e: float, body: tuple[float, float], L: tuple[float, float],  # noqa: N803
         b: tuple[float, float], ep: tuple[float, float], a: tuple[float, float], source: str) -> Preset:
    return _preset(f"QFN-{pins}-{size:g}x{size:g}-P{e:g}",
                   f"QFN-{pins} {size:g}×{size:g} mm, Raster {e:g}".replace(".", ","), source, "QFN", pins, e,
                   {"E": body, "L": L, "b": b, "E2": ep, "D2": ep, "A": a, "A1": (0.0, 0.05)})


PRESETS = [
    _qfn(16, 3, 0.5, (2.95, 3.05), (0.30, 0.50), (0.18, 0.30), (1.65, 1.85), (0.70, 0.80),
         "onsemi NCN4555 (KiCad-Daten), Körper ±0,05 angenommen"),
    _qfn(20, 4, 0.5, (3.95, 4.05), (0.35, 0.55), (0.18, 0.30), (2.45, 2.75), (0.70, 0.80),
         "Microchip doc2535 (KiCad-Daten)"),
    _qfn(24, 4, 0.5, (3.95, 4.05), (0.30, 0.50), (0.20, 0.30), (2.40, 2.60), (0.80, 0.90),
         "Microchip 00000049BQ (KiCad-Daten)"),
    _qfn(28, 5, 0.5, (4.95, 5.05), (0.35, 0.45), (0.18, 0.30), (3.15, 3.35), (0.80, 1.00), "Microchip (KiCad-Daten)"),
    _qfn(32, 5, 0.5, (4.90, 5.10), (0.30, 0.50), (0.20, 0.30), (3.35, 3.55), (0.70, 0.80), "ADI 05-08-1693"),
    _qfn(48, 7, 0.5, (6.90, 7.10), (0.30, 0.50), (0.20, 0.30), (5.50, 5.70), (0.50, 0.60), "ST UFQFPN48"),
    _qfn(64, 9, 0.5, (8.90, 9.10), (0.30, 0.50), (0.20, 0.30), (7.05, 7.25), (0.70, 0.80), "ADI 229321fa"),
    _qfn(16, 4, 0.65, (3.90, 4.10), (0.35, 0.45), (0.25, 0.35), (2.05, 2.15), (0.85, 0.95), "THAT1580 (KiCad-Daten)"),
    _preset("DFN-8-2x2-P0.5", "DFN-8 2×2 mm, Raster 0,5", "ST (KiCad-Daten); Höhe typisch", "DFN", 8, 0.5,
            {"E": (1.85, 2.15), "D": (1.85, 2.15), "L": (0.20, 0.50), "b": (0.18, 0.30), "E2": (0.75, 1.00),
             "D2": (1.45, 1.70), "A": (0.50, 0.60), "A1": (0.0, 0.05)}),
    _preset("SON-8-3x3-P0.65", "SON-8 3×3 mm, Raster 0,65", "typische Werte (VSON-8) – Datenblatt prüfen", "SON",
            8, 0.65, {"E": (2.90, 3.10), "D": (2.90, 3.10), "L": (0.30, 0.50), "b": (0.25, 0.35),
                      "E2": (1.45, 1.65), "D2": (2.30, 2.50), "A": (0.80, 1.00), "A1": (0.0, 0.05)}),
]

PARAMS = [
    p_enum("variant", "Gehäusetyp", VARIANTS, default="QFN", group="Typ",
           help="QFN: Anschlüsse auf 4 Seiten; DFN/SON: auf 2 Seiten (links/rechts)."),
    p_int("pins", "Anzahl Anschlüsse", default=16, minimum=4, maximum=300, help="Ohne Exposed Pad."),
    p_int("pins_x", "Anschlüsse oben/unten je Seite", minimum=1, maximum=100,
          help="Nur QFN mit ungleicher Verteilung; leer = gleichmäßig. Fehlende Anschlüsse zählen mit."),
    p_int("pins_y", "Anschlüsse links/rechts je Seite", minimum=1, maximum=100),
    p_float("e", "Raster e", default=0.5, minimum=0.3, maximum=1.27, group="Anschlüsse"),
    p_float("e_x", "Raster oben/unten", minimum=0.3, maximum=10.0, group="Anschlüsse",
            help="Nur QFN: Abstand der Anschlüsse auf der oberen und unteren Seite, wenn er vom Raster e abweicht "
                 "(z. B. TI RGY: 1,5 mm). Leer = e."),
    p_enum("pin1", "Lage von Pin 1", ["left", "top"], group="Anschlüsse",
           help="Nur QFN: left = oben auf der linken Seite (JEDEC, Standard); top = am linken Ende der oberen Seite "
                "(z. B. TI RGY). Gezählt wird gegen den Uhrzeigersinn."),
    p_text("missing", "Fehlende Anschlüsse", group="Anschlüsse",
           help="Positionen ohne Anschluss, gezählt ab Pin 1 gegen den Uhrzeigersinn wie bei voller Bestückung; "
                "kommagetrennt, z. B. „14“ oder „5, 6“. Die Pins werden über die übrigen Positionen durchnummeriert."),
    p_tol("E", "Körper X (E)", default={"min": 2.95, "max": 3.05}),
    p_tol("D", "Körper Y (D)", help="Leer = wie X."),
    p_tol("L", "Anschlusslänge L", group="Anschlüsse", default={"min": 0.30, "max": 0.50}),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse", default={"min": 0.18, "max": 0.30}),
    p_tol("A", "Bauhöhe A", default={"min": 0.80, "max": 1.00}),
    p_tol("A1", "Abstand A1", default={"min": 0.0, "max": 0.05}),
    p_tol("E2", "Exposed Pad X (E2)", group="Exposed Pad", default={"min": 1.65, "max": 1.85},
          help="0 = ohne Exposed Pad."),
    p_tol("D2", "Exposed Pad Y (D2)", group="Exposed Pad", help="Leer = wie X."),
    p_text("ep_name", "Bezeichner Exposed Pad", group="Exposed Pad",
           help="Leer = Hausstil (n+1 oder EP), z. B. „HS“."),
    p_float("paste_coverage", "Pastenbedeckung EP", default=0.65, unit=None, minimum=0.3, maximum=1.0,
            group="Exposed Pad", help="Anteil der EP-Fläche mit Lotpaste (Fensterraster); 1 = volle Fläche."),
    *NAMING_PARAMS,
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="nolead",
    label="QFN / DFN / SON",
    group="ICs (No-Lead)",
    description="Gehäuse ohne Anschlussbeinchen mit Exposed Pad und Pastenfenstern.",
    params=PARAMS,
    presets=PRESETS,
    ipc_table="3-15 / 3-16",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    variant = p.enum("variant", "QFN")
    pins = p.int("pins", 16)
    e = p.float("e", 0.5)
    E = p.tol("E")  # noqa: N806
    D = p.tol_opt("D") or E  # noqa: N806
    if variant != "QFN" and not p.given("D") and ctx.any_explicit("E"):
        ctx.warn(f"Körper Y (D) fehlt – quadratischer Körper ({fmt_mm(nom(E))} mm) angenommen; "
                 "DFN/SON-Gehäuse sind oft rechteckig, bitte prüfen.")
    L, b_, A, A1 = (p.tol(n) for n in ("L", "b", "A", "A1"))  # noqa: N806
    E2 = p.tol_opt("E2")  # noqa: N806
    D2 = p.tol_opt("D2") or E2  # noqa: N806
    has_ep = E2 is not None and D2 is not None and E2.max > 0 and D2.max > 0
    ep_w, ep_l = ep_size(ctx, E2, D2) if has_ep else (0.0, 0.0)
    ctx.check_exposed_pad(has_ep, ep_w, ep_l, body=("E", "D"))
    if has_ep and (ep_w >= nom(E) - 2 * nom(L) + 1e-6 or ep_l >= nom(D) - 2 * nom(L) + 1e-6) and variant == "QFN":
        ctx.warn("Das Exposed Pad reicht bis an die Anschlüsse heran – bitte E2/D2 prüfen.")
    table = "qfn" if variant == "QFN" else "son"
    package = f"{variant}-{pins}"
    b = ctx.builder()
    missing = missing_positions(ctx)
    first = "left"
    if variant == "QFN":
        nx, ny = side_counts(ctx, pins, omitted=len(missing))
        missing_positions(ctx, 2 * (nx + ny))  # every listed position exists
        e_x = p.float_opt("e_x") or e
        first = p.enum("pin1") if p.given("pin1") else "left"
        ov = ctx.override
        if ov is not None and ov.row_spacing_y is None and abs(nom(D) - nom(E)) > 0.05:
            # one row spacing cannot fit both pad rows of a rectangular body – never place the other rows silently
            raise ParamError(f"Herstellerempfehlung: für die Anschlüsse oben/unten fehlt der eigene Reihenabstand – "
                             f"bei einem rechteckigen Körper ({fmt_mm(nom(E))} × {fmt_mm(nom(D))} mm) ist er anders "
                             "als links/rechts. Bitte ergänzen oder IPC-7351B verwenden.", params=())
        check_row_fits_body(ctx, pitch=e, positions=ny, lead_width=b_, body=D, package=package)
        check_row_fits_body(ctx, pitch=e_x, positions=nx, lead_width=b_, body=E, package=package, body_symbol="E")
        land_x = ctx.ipc_land(E, L, b_, table, axis="x", label="Anschlüsse links/rechts")
        ctx.finalize_land(land_x, pitch=e, ep=ep_w)
        land_y = ctx.ipc_land(D, L, b_, table, axis="y", label="Anschlüsse oben/unten")
        ctx.finalize_land(land_y, pitch=e_x, ep=ep_l)
        pads = quad(b, land_x, land_y, nx, ny, e, pitch_x=e_x, first=first,  # type: ignore[arg-type]
                    omit=missing)
    else:
        if p.given("e_x") or p.given("pin1"):
            ctx.warn("Raster oben/unten und Lage von Pin 1 gelten nur für QFN – bei DFN/SON ignoriert.")
        positions = pins + len(missing)
        if positions % 2:
            raise ParamError("DFN/SON: die Anzahl der Anschlüsse muss gerade sein (zwei Reihen)" +
                             (" – fehlende Anschlüsse mitgezählt." if missing else "."), params=("pins",))
        missing_positions(ctx, positions)
        check_row_fits_body(ctx, pitch=e, positions=positions // 2, lead_width=b_, body=D, package=package)
        land_x = ctx.ipc_land(E, L, b_, table, axis="x", label="Anschlüsse")
        ctx.finalize_land(land_x, pitch=e, ep=ep_w)
        pads = dual_row(b, land_x, positions // 2, e, omit=missing)
    if has_ep:
        des = p.text("ep_name") or ctx.ep_designator(pins)
        ep = b.smd_pad(des, 0.0, 0.0, ep_w, ep_l, shape="rect", thermal=True)
        windows = b.paste_windows(ep, p.float("paste_coverage", 0.65))
        ctx.extra_calc["paste_windows"] = windows

    en, dn, h, ln, bn = nom(E), nom(D), A.max, nom(L), nom(b_)
    body = b.body(rect_centered(0, 0, en, dn))
    pin1_mark = dot_above(b, pads[0]) if first == "top" else dot_left(b, pads[0])
    ic_silk(b, body, [dot_corner(b, body), pin1_mark], push=(-0.7071, 0.7071),
            rows="quad" if variant == "QFN" else "lr")
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

    b.box("Body", body, nom(A1), h, IC_BODY)
    t = min(0.2, h * 0.4)
    protrude = 0.02
    for pad in pads:
        if abs(abs(pad.x) - land_x.pad_center) < 1e-6 and abs(pad.width - land_x.pad_length) < 1e-6:
            s = 1.0 if pad.x > 0 else -1.0
            xo, xi = s * (en / 2 + protrude), s * (en / 2 - ln)
            b.box(f"Terminal {pad.designator}", (min(xo, xi), pad.y - bn / 2, max(xo, xi), pad.y + bn / 2), 0, t, TIN)
        else:
            s = 1.0 if pad.y > 0 else -1.0
            yo, yi = s * (dn / 2 + protrude), s * (dn / 2 - ln)
            b.box(f"Terminal {pad.designator}", (pad.x - bn / 2, min(yo, yi), pad.x + bn / 2, max(yo, yi)), 0, t, TIN)

    pin_qty = pins + (1 if has_ep else 0)
    if variant == "DFN":
        ipc_name = naming.ipc_dfn(dn, en, h, pin_qty, ctx.density)
    else:
        ipc_name = naming.ipc_qfn(variant, e, en, dn, h, pin_qty, ctx.density)
    ep_text = f" EP{naming.short_num(ep_w)}x{naming.short_num(ep_l)}" if has_ep else ""
    house_name = naming.house(f"{package} {naming.house_body(en, dn)}{ep_text}", ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe(variant, pins, dn, en, ctx.density, pitch=e, thermal=(ep_w, ep_l) if has_ep else None)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=package + ep_text, height=h, courtyard_table=table)


def _alias(variant: str) -> dict[str, str]:
    """Alias -> variant plus the best matching preset (pins/pitch of the request) as base."""
    return {"variant": variant, "preset": "*"}


ALIAS_PARAMS = {
    **{name: _alias("QFN") for name in ("qfn", "vqfn", "wqfn", "uqfn", "xqfn", "lfcsp", "mlf", "mlp")},
    **{name: _alias("DFN") for name in ("dfn", "tdfn", "udfn", "wdfn", "xdfn")},
    **{name: _alias("SON") for name in ("son", "vson", "wson", "uson", "xson")},
}

FAMILIES = [FamilyDef(INFO, build, alias_params=ALIAS_PARAMS, free_params=frozenset({"A1"}),
                      max_only=frozenset({"A"}))]
