"""Dual-row gull-wing ICs: SOIC, SSOP, TSSOP, MSOP, QSOP (optionally with exposed pad).

JEDEC symbols: e pitch, E lead span (tip to tip), E1 body width, D body length, L foot length,
b lead width, A height, A1 standoff, c lead thickness, E2/D2 exposed pad.
Tables 3-2 (pitch > 0.625 mm) / 3-3 (≤ 0.625 mm). Pin 1 upper left, counter-clockwise.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
    dot_above,
    dual_row,
    ep_size,
    ic_silk,
    p_enum,
    p_float,
    p_int,
    p_tol,
)

VARIANTS = ["SOIC", "SSOP", "TSSOP", "MSOP", "QSOP", "SOP"]
_WORD = {"SOIC": "SOIC", "SSOP": "SSOP", "TSSOP": "TSSOP", "MSOP": "MSOP", "QSOP": "QSOP", "SOP": "SOP"}


def _preset(key: str, label: str, source: str, variant: str, pins: int, e: float,
            dims: Mapping[str, tuple[float, float]], **extra: Any) -> Preset:
    return Preset(key=key, label=label, source=source,
                  params={"variant": variant, "pins": pins, "e": e,
                          **{k: {"min": v[0], "max": v[1]} for k, v in dims.items()}, **extra})


_MS012 = {"E": (5.8, 6.2), "E1": (3.8, 4.0), "L": (0.40, 1.27), "b": (0.31, 0.51), "A": (1.35, 1.75),
          "A1": (0.10, 0.25), "c": (0.10, 0.25)}
_MS013 = {"E": (10.00, 10.65), "E1": (7.40, 7.60), "L": (0.40, 1.27), "b": (0.33, 0.51), "A": (2.35, 2.65),
          "A1": (0.10, 0.30), "c": (0.20, 0.33)}
_MO153 = {"E": (6.2, 6.6), "E1": (4.3, 4.5), "L": (0.45, 0.75), "A": (0.80, 1.20), "A1": (0.05, 0.15),
          "c": (0.09, 0.20)}
_MO150 = {"E": (7.40, 8.20), "E1": (5.00, 5.60), "L": (0.55, 0.95), "b": (0.22, 0.38), "A": (1.70, 2.00),
          "A1": (0.05, 0.25), "c": (0.09, 0.25)}
_MO137 = {"E": (5.84, 6.20), "E1": (3.81, 3.99), "L": (0.41, 0.89), "b": (0.20, 0.30), "A": (1.35, 1.75),
          "A1": (0.10, 0.25), "c": (0.19, 0.25)}

PRESETS: list[Preset] = [
    *(_preset(f"SOIC-{n}", f"SOIC-{n} (3,9 mm, JEDEC MS-012)", "JEDEC MS-012 / Nexperia SOT96-1", "SOIC", n,
              1.27, {**_MS012, "D": d}) for n, d in ((8, (4.8, 5.0)), (14, (8.55, 8.75)), (16, (9.80, 10.00)))),
    *(_preset(f"SOIC-{n}W", f"SOIC-{n} breit (7,5 mm, JEDEC MS-013)", "JEDEC MS-013 / IPC-SM-782A", "SOIC", n,
              1.27, {**_MS013, "D": d}) for n, d in ((16, (10.10, 10.50)), (20, (12.60, 13.00)))),
    *(_preset(f"TSSOP-{n}", f"TSSOP-{n} (4,4 mm, Raster 0,65)", "JEDEC MO-153 / Nexperia SOT403-1", "TSSOP", n,
              0.65, {**_MO153, "b": (0.19, 0.30), "D": d})
      for n, d in ((8, (2.9, 3.1)), (14, (4.9, 5.1)), (16, (4.9, 5.1)), (20, (6.4, 6.6)), (24, (7.7, 7.9)),
                   (28, (9.6, 9.8)))),
    *(_preset(f"TSSOP-{n}-P0.5", f"TSSOP-{n} (4,4 mm, Raster 0,5)", "JEDEC MO-153 (KiCad-Daten)", "TSSOP", n,
              0.5, {**_MO153, "b": (0.17, 0.27), "D": d})
      for n, d in ((20, (4.9, 5.1)), (24, (6.4, 6.6)), (28, (7.7, 7.9)), (38, (9.6, 9.8)))),
    _preset("MSOP-8", "MSOP-8 (Raster 0,65, JEDEC MO-187 AA)", "Nexperia SOT505-1", "MSOP", 8, 0.65,
            {"E": (4.7, 5.1), "E1": (2.9, 3.1), "D": (2.9, 3.1), "L": (0.40, 0.70), "b": (0.25, 0.45),
             "A": (0.80, 1.10), "A1": (0.05, 0.15), "c": (0.15, 0.28)}),
    _preset("MSOP-10", "MSOP-10 (Raster 0,5, JEDEC MO-187 BA)", "ADI RM-10 (MO-187-BA)", "MSOP", 10, 0.5,
            {"E": (4.65, 5.15), "E1": (2.90, 3.10), "D": (2.90, 3.10), "L": (0.40, 0.80), "b": (0.17, 0.33),
             "A": (0.80, 1.10), "A1": (0.05, 0.15), "c": (0.08, 0.23)}),
    *(_preset(f"SSOP-{n}", f"SSOP-{n} (5,3 mm, Raster 0,65)", "JEDEC MO-150 (KiCad-Daten)", "SSOP", n, 0.65,
              {**_MO150, "D": d})
      for n, d in ((8, (2.70, 3.30)), (14, (5.90, 6.50)), (20, (6.90, 7.50)), (24, (7.90, 8.50)),
                   (28, (9.90, 10.50)))),
    *(_preset(f"QSOP-{n}", f"QSOP-{n} (3,9 mm, Raster 0,635)", "JEDEC MO-137 (Maxim 21-0055; D typisch)",
              "QSOP", n, 0.635, {**_MO137, "D": d})
      for n, d in ((16, (4.80, 4.98)), (20, (8.56, 8.74)), (24, (8.56, 8.74)), (28, (9.80, 9.98)))),
]

PARAMS = [
    p_enum("variant", "Gehäusetyp", VARIANTS, default="SOIC", group="Typ",
           help="Bestimmt Namen (SOIC… bzw. SOP…) und Beschreibung."),
    p_int("pins", "Anzahl Anschlüsse", default=8, minimum=4, maximum=100),
    p_float("e", "Raster e", default=1.27, minimum=0.3, maximum=2.54, group="Anschlüsse"),
    p_tol("E", "Gesamtbreite E", default={"min": 5.8, "max": 6.2},
          help="Spannweite über die Anschlussspitzen (Nexperia: HE)."),
    p_tol("E1", "Körperbreite E1", default={"min": 3.8, "max": 4.0}, help="Breite des Kunststoffkörpers (Nexperia: E)."),
    p_tol("D", "Körperlänge D", default={"min": 4.8, "max": 5.0}),
    p_tol("L", "Fußlänge L", group="Anschlüsse", default={"min": 0.4, "max": 1.27},
          help="Auflagelänge des Fußes (Nexperia: Lp)."),
    p_tol("b", "Anschlussbreite b", group="Anschlüsse", default={"min": 0.31, "max": 0.51}),
    p_tol("A", "Bauhöhe A", default={"min": 1.35, "max": 1.75}, help="IPC-Name nutzt den Maximalwert."),
    p_tol("A1", "Abstand A1", default={"min": 0.05, "max": 0.15}),
    p_tol("c", "Anschlussdicke c", group="Anschlüsse", default={"min": 0.1, "max": 0.25}),
    p_tol("E2", "Exposed Pad Breite E2", group="Exposed Pad",
          help="Nur bei Gehäusen mit Thermal Pad (z. B. HTSSOP); leer = ohne."),
    p_tol("D2", "Exposed Pad Länge D2", group="Exposed Pad"),
    p_float("paste_coverage", "Pastenbedeckung EP", default=0.65, unit=None, minimum=0.3, maximum=1.0,
            group="Exposed Pad"),
    *NAMING_PARAMS,
    *COMMON_SMD,
]

INFO = FamilyInfo(
    key="gullwing",
    label="SOIC / SSOP / TSSOP / MSOP / QSOP",
    group="ICs (Gull-Wing)",
    description="Zweireihige ICs mit Gull-Wing-Anschlüssen, optional mit Exposed Pad.",
    params=PARAMS,
    presets=PRESETS,
    ipc_table="3-2 / 3-3",
)


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    variant = p.enum("variant", "SOIC")
    pins = p.int("pins", 8)
    if pins % 2:
        raise ParamError("Die Anzahl der Anschlüsse muss gerade sein (zwei Reihen).", params=("pins",))
    e = p.float("e", 1.27)
    E, E1, D, L, b_, A = (p.tol(n) for n in ("E", "E1", "D", "L", "b", "A"))  # noqa: N806
    A1, c = p.tol("A1"), p.tol("c")  # noqa: N806
    if E1.max >= E.min:
        raise ValueError("Körperbreite E1 muss kleiner als die Gesamtbreite E sein "
                         "(Hinweis: bei Nexperia heißt die Gesamtbreite HE und die Körperbreite E).")
    per_side = pins // 2
    if (per_side - 1) * e > nom(D) + 1e-6:
        ctx.warn("Die Anschlussreihe ist länger als der Körper (Raster × Anzahl > D) – bitte Maße prüfen.")
    E2, D2 = p.tol_opt("E2"), p.tol_opt("D2")  # noqa: N806
    has_ep = E2 is not None and D2 is not None and E2.max > 0 and D2.max > 0
    if (E2 is None) != (D2 is None):
        ctx.warn("Exposed Pad unvollständig (E2 und D2 nötig) – ohne Exposed Pad erzeugt.")
    ep_w, ep_l = ep_size(ctx, E2, D2) if has_ep else (0.0, 0.0)
    ctx.check_exposed_pad(has_ep, ep_w, ep_l, body=("E", "E1", "D"))

    table = gullwing_table(e)
    land = ctx.ipc_land(E, L, b_, table, label="Anschlüsse")
    ctx.finalize_land(land, pitch=e, ep=ep_w)

    b = ctx.builder()
    pads = dual_row(b, land, per_side, e)
    if has_ep:
        ep = b.smd_pad(ctx.ep_designator(pins), 0.0, 0.0, ep_w, ep_l, shape="rect", thermal=True)
        b.paste_windows(ep, p.float("paste_coverage", 0.65))
    e1n, dn, en = nom(E1), nom(D), nom(E)
    body = b.body(rect_centered(0, 0, e1n, dn))
    ic_silk(b, body, [dot_above(b, pads[0])], push=(0.0, 1.0))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

    h, a1, cn, bn, ln = A.max, nom(A1), nom(c), nom(b_), nom(L)
    b.box("Body", body, a1, h, IC_BODY)
    for pad in pads:
        sign = -1.0 if pad.x < 0 else 1.0
        x_body, x_tip, x_foot = sign * (e1n / 2 - 0.05), sign * en / 2, sign * (en / 2 - ln)
        b.box(f"Lead {pad.designator}", (min(x_foot, x_tip), pad.y - bn / 2, max(x_foot, x_tip), pad.y + bn / 2),
              0.0, cn, TIN)
        b.box(f"Lead {pad.designator} leg", (min(x_body, x_foot), pad.y - bn / 2, max(x_body, x_foot),
                                             pad.y + bn / 2), cn, a1 + 0.45 * (h - a1), TIN)

    pin_qty = pins + (1 if has_ep else 0)
    prefix = "SOIC" if variant == "SOIC" else "SOP"
    ipc_name = naming.ipc_pitch_span(prefix, e, en, h, pin_qty, ctx.density)
    ep_text = f" EP{naming.short_num(ep_w)}x{naming.short_num(ep_l)}" if has_ep else ""
    package = f"{variant}-{pins}"
    house_name = naming.house(f"{package} {naming.house_body(e1n, dn)}{ep_text}", ctx.density,
                              manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe(_WORD[variant], pins, dn, e1n, ctx.density, pitch=e,
                           thermal=(ep_w, ep_l) if has_ep else None)
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=package + ep_text, height=h, courtyard_table=table)


def _alias(variant: str) -> dict[str, str]:
    """Alias -> variant plus the best matching preset (pins/pitch of the request) as base."""
    return {"variant": variant, "preset": "*"}


ALIAS_PARAMS = {
    "soic": _alias("SOIC"), "so": _alias("SOIC"), "sopic": _alias("SOIC"),
    "ssop": _alias("SSOP"), "tssop": _alias("TSSOP"), "htssop": _alias("TSSOP"),
    "msop": _alias("MSOP"), "vssop": _alias("MSOP"), "qsop": _alias("QSOP"), "sop": _alias("SOP"),
}

FAMILIES = [FamilyDef(INFO, build, alias_params=ALIAS_PARAMS, free_params=frozenset({"A1", "c"}),
                      max_only=frozenset({"A"}))]
