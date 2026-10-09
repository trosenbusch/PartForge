"""Quad flat packages with gull-wing leads: LQFP / TQFP / QFP (JEDEC MS-026), optional exposed pad.

Symbols: HE/HD lead span in X/Y (tip to tip; JEDEC MS-026 calls them D/E with D1/E1 = body),
E/D body in X/Y, e pitch, L foot, b lead width, A height. Pin 1 at the top of the left side,
counter-clockwise. Tables 3-2 / 3-3.
"""
from __future__ import annotations

from collections.abc import Mapping

from ...geometry.model import FootprintSpec
from .. import naming
from ..builder import IC_BODY, TIN
from ..geom import rect_centered
from ..ipc7351 import gullwing_table
from ..models import FamilyInfo, Preset
from ..params import ParamError, nom
from .base import (
    COMMON_SMD,
    NAMING_PARAMS,
    FamilyDef,
    GenContext,
    describe,
    dot_corner,
    dot_left,
    ep_size,
    ic_silk,
    p_enum,
    p_float,
    p_int,
    p_tol,
    quad,
)

VARIANTS = ["LQFP", "TQFP", "QFP"]


def _preset(variant: str, pins: int, body: float, e: float, span: tuple[float, float],
            body_tol: tuple[float, float], b: tuple[float, float], a: tuple[float, float], source: str) -> Preset:
    dims: Mapping[str, tuple[float, float]] = {
        "HE": span, "E": body_tol, "L": (0.45, 0.75), "b": b, "A": a, "A1": (0.05, 0.15), "c": (0.09, 0.20),
    }
    return Preset(
        key=f"{variant}-{pins}-{body:g}x{body:g}-P{e:g}",
        label=f"{variant}-{pins} {body:g}×{body:g} mm, Raster {e:g}".replace(".", ","),
        source=source,
        params={"variant": variant, "pins": pins, "e": e, **{k: {"min": v[0], "max": v[1]} for k, v in dims.items()}},
    )


_BSC = "JEDEC MS-026 (Spannweite ±0,20 mm angenommen)"
PRESETS = [
    _preset("LQFP", 32, 7, 0.8, (8.85, 9.15), (6.9, 7.1), (0.30, 0.40), (1.40, 1.60), "NXP SOT358-1"),
    _preset("LQFP", 44, 10, 0.8, (11.8, 12.2), (9.9, 10.1), (0.30, 0.45), (1.40, 1.60), _BSC),
    _preset("LQFP", 48, 7, 0.5, (8.8, 9.2), (6.9, 7.1), (0.17, 0.27), (1.40, 1.60), _BSC),
    _preset("LQFP", 64, 10, 0.5, (11.8, 12.2), (9.8, 10.2), (0.17, 0.27), (1.40, 1.60), "ADI AD7606 (KiCad-Daten)"),
    _preset("LQFP", 100, 14, 0.5, (15.75, 16.25), (13.9, 14.1), (0.17, 0.27), (1.40, 1.60), "NXP SOT407-1"),
    _preset("LQFP", 144, 20, 0.5, (21.8, 22.2), (19.9, 20.1), (0.17, 0.27), (1.40, 1.60), _BSC),
    _preset("TQFP", 32, 7, 0.8, (8.8, 9.2), (6.9, 7.1), (0.30, 0.45), (1.00, 1.20), _BSC),
    _preset("TQFP", 44, 10, 0.8, (11.8, 12.2), (9.9, 10.1), (0.30, 0.45), (1.00, 1.20), _BSC),
    _preset("TQFP", 48, 7, 0.5, (8.8, 9.2), (6.9, 7.1), (0.17, 0.27), (1.00, 1.20), _BSC),
    _preset("TQFP", 100, 14, 0.5, (15.8, 16.2), (13.9, 14.1), (0.17, 0.27), (1.00, 1.20), _BSC),
]

PARAMS = [
    p_enum("variant", "Gehäusetyp", VARIANTS, default="LQFP", group="Typ"),
    p_int("pins", "Anzahl Anschlüsse", default=48, minimum=8, maximum=400),
    p_int("pins_x", "Anschlüsse oben/unten je Seite", minimum=1, maximum=100,
          help="Nur für rechteckige Gehäuse; leer = gleichmäßig auf 4 Seiten."),
    p_int("pins_y", "Anschlüsse links/rechts je Seite", minimum=1, maximum=100),
    p_float("e", "Raster e", default=0.5, minimum=0.3, maximum=1.27, group="Anschlüsse"),
    p_tol("HE", "Spannweite X (HE)", default={"min": 8.8, "max": 9.2},
          help="Über die Anschlussspitzen in X (JEDEC MS-026: E)."),
    p_tol("HD", "Spannweite Y (HD)", help="Leer = wie X."),
    p_tol("E", "Körper X (E)", default={"min": 6.9, "max": 7.1}, help="Kunststoffkörper (JEDEC MS-026: E1)."),
    p_tol("D", "Körper Y (D)", help="Leer = wie X."),
    p_tol("L", "Fußlänge L", group="Anschlüsse", default={"min": 0.45, "max": 0.75}),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse", default={"min": 0.17, "max": 0.27}),
    p_tol("A", "Bauhöhe A", default={"min": 1.4, "max": 1.6}),
    p_tol("A1", "Abstand A1", default={"min": 0.05, "max": 0.15}),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.09, "max": 0.2}),
    p_tol("E2", "Exposed Pad X (E2)", group="Exposed Pad", help="Leer = ohne Exposed Pad."),
    p_tol("D2", "Exposed Pad Y (D2)", group="Exposed Pad"),
    p_float("paste_coverage", "Pastenbedeckung EP", default=0.65, unit=None, minimum=0.3, maximum=1.0,
            group="Exposed Pad"),
    *NAMING_PARAMS,
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="qfp",
    label="LQFP / TQFP / QFP",
    group="ICs (Gull-Wing)",
    description="Vierseitige Flachgehäuse mit Gull-Wing-Anschlüsse (JEDEC MS-026).",
    params=PARAMS,
    presets=PRESETS,
    ipc_table="3-2 / 3-3",
)


def side_counts(ctx: GenContext, pins: int) -> tuple[int, int]:
    p = ctx.p
    if p.given("pins_x") or p.given("pins_y"):
        nx = p.int("pins_x") if p.given("pins_x") else None
        ny = p.int("pins_y") if p.given("pins_y") else None
        if nx is None:
            nx = pins // 2 - (ny or 0)
        if ny is None:
            ny = pins // 2 - nx
        if 2 * (nx + ny) != pins or nx < 1 or ny < 1:
            raise ParamError(f"Anschlüsse je Seite ({nx} oben/unten, {ny} links/rechts) passen nicht zu {pins} "
                             "Anschlüssen insgesamt.", params=("pins", "pins_x", "pins_y"))
        return nx, ny
    if pins % 4:
        raise ParamError("Bei gleichmäßiger Verteilung muss die Anschlusszahl durch 4 teilbar sein "
                         "(sonst Anschlüsse je Seite angeben).", params=("pins",))
    return pins // 4, pins // 4


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    variant = p.enum("variant", "LQFP")
    pins = p.int("pins", 48)
    nx, ny = side_counts(ctx, pins)
    e = p.float("e", 0.5)
    HE = p.tol("HE")  # noqa: N806
    HD = p.tol_opt("HD") or HE  # noqa: N806
    E = p.tol("E")  # noqa: N806
    D = p.tol_opt("D") or E  # noqa: N806
    L, b_, A, A1, c = (p.tol(n) for n in ("L", "b", "A", "A1", "c"))  # noqa: N806
    if E.max >= HE.min or D.max >= HD.min:
        raise ValueError("Der Körper muss kleiner als die Spannweite sein (Hinweis: JEDEC MS-026 nennt die "
                         "Spannweite D/E und den Körper D1/E1).")
    E2, D2 = p.tol_opt("E2"), p.tol_opt("D2")  # noqa: N806
    has_ep = E2 is not None and D2 is not None and E2.max > 0 and D2.max > 0
    if (E2 is None) != (D2 is None):
        ctx.warn("Exposed Pad unvollständig (E2 und D2 nötig) – ohne Exposed Pad erzeugt.")
    ep_w, ep_l = ep_size(ctx, E2, D2) if has_ep else (0.0, 0.0)
    ctx.check_exposed_pad(has_ep, ep_w, ep_l, body=("HE", "HD", "E", "D"))
    table = gullwing_table(e)
    land_x = ctx.ipc_land(HE, L, b_, table, axis="x", label="Anschlüsse links/rechts")
    ctx.finalize_land(land_x, pitch=e, ep=ep_w)
    land_y = ctx.ipc_land(HD, L, b_, table, axis="y", label="Anschlüsse oben/unten")
    ctx.finalize_land(land_y, pitch=e, ep=ep_l)

    b = ctx.builder()
    pads = quad(b, land_x, land_y, nx, ny, e)
    if has_ep:
        ep = b.smd_pad(ctx.ep_designator(pins), 0.0, 0.0, ep_w, ep_l, shape="rect", thermal=True)
        b.paste_windows(ep, p.float("paste_coverage", 0.65))
    en, dn, hen, hdn = nom(E), nom(D), nom(HE), nom(HD)
    body = b.body(rect_centered(0, 0, en, dn))
    ic_silk(b, body, [dot_corner(b, body), dot_left(b, pads[0])], push=(-0.7071, 0.7071), rows="quad")
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

    h, a1, cn, bn, ln = A.max, nom(A1), nom(c), nom(b_), nom(L)
    b.box("Body", body, a1, h, IC_BODY)
    leg_top = a1 + 0.45 * (h - a1)
    for index, pad in enumerate(pads):
        on_left_right = index < ny or ny + nx <= index < 2 * ny + nx  # quad(): left, bottom, right, top
        if on_left_right:
            s = 1.0 if pad.x > 0 else -1.0
            xb, xt, xf = s * (en / 2 - 0.05), s * hen / 2, s * (hen / 2 - ln)
            b.box(f"Lead {pad.designator}", (min(xf, xt), pad.y - bn / 2, max(xf, xt), pad.y + bn / 2), 0, cn, TIN)
            b.box(f"Lead {pad.designator} leg", (min(xb, xf), pad.y - bn / 2, max(xb, xf), pad.y + bn / 2), cn,
                  leg_top, TIN)
        else:
            s = 1.0 if pad.y > 0 else -1.0
            yb, yt, yf = s * (dn / 2 - 0.05), s * hdn / 2, s * (hdn / 2 - ln)
            b.box(f"Lead {pad.designator}", (pad.x - bn / 2, min(yf, yt), pad.x + bn / 2, max(yf, yt)), 0, cn, TIN)
            b.box(f"Lead {pad.designator} leg", (pad.x - bn / 2, min(yb, yf), pad.x + bn / 2, max(yb, yf)), cn,
                  leg_top, TIN)

    pin_qty = pins + (1 if has_ep else 0)
    ipc_name = naming.ipc_qfp(e, hen, hdn, h, pin_qty, ctx.density)
    package = f"{variant}-{pins}"
    ep_text = f" EP{naming.short_num(ep_w)}x{naming.short_num(ep_l)}" if has_ep else ""
    house_name = naming.house(f"{package} {naming.house_body(en, dn)}{ep_text}", ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe(variant, pins, dn, en, ctx.density, pitch=e,
                           thermal=(ep_w, ep_l) if has_ep else None)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=package + ep_text, height=h, courtyard_table=table)


ALIAS_PARAMS = {
    "lqfp": {"variant": "LQFP", "preset": "*"}, "tqfp": {"variant": "TQFP", "preset": "*"},
    "htqfp": {"variant": "TQFP", "preset": "*"}, "vqfp": {"variant": "TQFP", "preset": "*"},
    "pqfp": {"variant": "QFP"},
}

FAMILIES = [FamilyDef(INFO, build, aliases=("ms026",), alias_params=ALIAS_PARAMS,
                      free_params=frozenset({"A1", "c"}), max_only=frozenset({"A"}))]
