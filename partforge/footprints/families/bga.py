"""Ball grid arrays (IPC-7351B tables 14-4 … 14-6, courtyard table 3-17).

Lands from the ball diameter: collapsible balls get a reduced land, non-collapsible an enlarged one
(density M = land max/MMC, N = nominal, L = min). Ball A1 upper left; rows A, B, … skipping
I, O, Q, S, X, Z (JEDEC); columns 1 … n. Optional depopulation (centre block or named balls).
Official IPC BGA names carry no density suffix; the nominal density (IPC nominal land) keeps that
name, M and L get the suffix because their lands and courtyards differ (unique names per land).
"""
from __future__ import annotations

import re

from ...geometry.model import FootprintSpec
from .. import ipc7351 as ipc
from .. import naming
from ..builder import BGA_SUBSTRATE, IC_BODY, TIN
from ..geom import circle_points, rect_centered
from ..models import FamilyInfo, Preset
from ..params import nom
from .base import (
    COMMON_SMD,
    NAMING_PARAMS,
    FamilyDef,
    GenContext,
    describe,
    dot_corner,
    p_bool,
    p_float,
    p_int,
    p_text,
    p_tol,
)

_ROW_LETTERS = [c for c in "ABCDEFGHJKLMNPRTUVWY"]


def row_name(index: int) -> str:
    """0 -> A, 19 -> Y, 20 -> AA, … (JEDEC letters without I, O, Q, S, X, Z)."""
    n = len(_ROW_LETTERS)
    if index < n:
        return _ROW_LETTERS[index]
    return row_name(index // n - 1) + _ROW_LETTERS[index % n]


def _preset(pins_rows: int, pins_cols: int, e: float, ball: float, body: float, a: tuple[float, float],
            a1: tuple[float, float], source: str, depop: int = 0) -> Preset:
    count = pins_rows * pins_cols - depop * depop
    return Preset(
        key=f"BGA-{count}-{pins_cols}x{pins_rows}-P{e:g}",
        label=f"BGA-{count} ({pins_cols}×{pins_rows}, Raster {e:g} mm, {body:g}×{body:g} mm)".replace(".", ","),
        source=source,
        params={"rows": pins_rows, "cols": pins_cols, "e": e, "ball": ball,
                "E": {"min": body - 0.1, "max": body + 0.1}, "A": {"min": a[0], "max": a[1]},
                "A1": {"min": a1[0], "max": a1[1]}, "collapsible": True, "depop_center": depop},
    )


_TYP = "typische Werte nach IPC-7351B Tabelle 14-4 (Kugel/Raster) – Datenblatt prüfen"
PRESETS = [
    _preset(8, 8, 0.8, 0.40, 7.0, (1.0, 1.2), (0.25, 0.35), _TYP),
    _preset(10, 10, 0.8, 0.40, 9.0, (1.1, 1.3), (0.25, 0.35), _TYP),
    _preset(12, 12, 0.8, 0.40, 10.0, (1.2, 1.4), (0.25, 0.35), _TYP),
    _preset(14, 14, 1.0, 0.50, 15.0, (1.4, 1.7), (0.30, 0.45), _TYP),
    _preset(16, 16, 1.0, 0.50, 17.0, (1.5, 2.0), (0.30, 0.45), _TYP),
    _preset(10, 10, 0.65, 0.30, 7.0, (0.9, 1.1), (0.15, 0.25), _TYP),
    _preset(9, 9, 0.5, 0.30, 5.0, (0.8, 1.0), (0.15, 0.25), _TYP),
    _preset(12, 12, 0.8, 0.40, 10.0, (1.2, 1.4), (0.25, 0.35), _TYP + "; Mitte 4×4 unbestückt", depop=4),
]

PARAMS = [
    p_int("rows", "Zeilen (A, B, …)", default=8, minimum=1, maximum=60, group="Raster"),
    p_int("cols", "Spalten (1, 2, …)", default=8, minimum=1, maximum=60, group="Raster"),
    p_float("e", "Raster e", default=0.8, minimum=0.3, maximum=2.0, group="Raster"),
    p_float("ball", "Kugeldurchmesser b", default=0.40, minimum=0.1, maximum=1.0, group="Raster",
            help="Nennwert des Kugeldurchmessers."),
    p_bool("collapsible", "Kollabierende Kugeln", default=True, group="Raster",
           help="Ja: SnAgCu-Kugeln (Pad kleiner als Kugel); Nein: Hochtemperatur-/Kupferkern (Pad größer)."),
    p_tol("E", "Körper X (E)", default={"min": 6.9, "max": 7.1}),
    p_tol("D", "Körper Y (D)", help="Leer = wie X."),
    p_tol("A", "Bauhöhe A", default={"min": 1.0, "max": 1.2}),
    p_tol("A1", "Kugelhöhe A1", default={"min": 0.25, "max": 0.35}),
    p_int("depop_center", "Unbestückter Mittelblock", default=0, minimum=0, maximum=58, group="Raster",
          help="Kantenlänge eines zentrierten Blocks ohne Kugeln (0 = alle bestückt)."),
    p_text("missing", "Fehlende Kugeln", group="Raster", help="Kommagetrennt, z. B. „A1, B2, H8“."),
    *NAMING_PARAMS,
    *(s for s in COMMON_SMD if s.name in ("min_copper_gap", "courtyard_excess", "courtyard_grid")),
]

INFO = FamilyInfo(
    key="bga",
    label="BGA (Ball Grid Array)",
    group="ICs (BGA)",
    description="Kugelgitter-Gehäuse mit IPC-Landgrößen aus dem Kugeldurchmesser.",
    params=PARAMS,
    presets=PRESETS,
    ipc_table="14-5 / 14-6, 3-17",
)


def _missing(text: str, rows: int, cols: int) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    names = {row_name(r): r for r in range(rows)}
    for token in re.split(r"[,;\s]+", text.strip().upper()):
        if not token:
            continue
        m = re.fullmatch(r"([A-Z]+)(\d+)", token)
        if not m or m.group(1) not in names or not 1 <= int(m.group(2)) <= cols:
            raise ValueError(f"Kugel „{token}“ gibt es in einem {cols}×{rows}-Raster nicht.")
        out.add((names[m.group(1)], int(m.group(2)) - 1))
    return out


def build(ctx: GenContext) -> FootprintSpec:
    p = ctx.p
    rows, cols = p.int("rows", 8), p.int("cols", 8)
    e = p.float("e", 0.8)
    ball = p.float("ball", 0.4)
    collapsible = p.bool("collapsible", True)
    E = p.tol("E")  # noqa: N806
    D = p.tol_opt("D") or E  # noqa: N806
    A, A1 = p.tol("A"), p.tol("A1")  # noqa: N806
    en, dn = nom(E), nom(D)
    if (cols - 1) * e + ball > en + 1e-6 or (rows - 1) * e + ball > dn + 1e-6:
        raise ValueError("Das Kugelraster ist größer als der Körper – bitte Zeilen/Spalten, Raster oder Körper prüfen.")
    if ball >= e:
        raise ValueError("Der Kugeldurchmesser muss kleiner als das Raster sein.")
    depop = p.int("depop_center", 0)
    if depop and (depop > rows - 2 or depop > cols - 2):
        raise ValueError("Der unbestückte Mittelblock ist zu groß für das Raster.")
    missing = _missing(p.text("missing"), rows, cols)
    land, note = ipc.bga_land(ball, ctx.density, collapsible)
    if land > e - ctx.min_gap:
        limit = ipc.round_down(e - ctx.min_gap, 0.01)
        ctx.warn(f"BGA-Pad {ipc.fmt_mm(land)} mm auf {ipc.fmt_mm(limit)} mm begrenzt (Kupferabstand).")
        land = limit
    ctx.extra_calc["bga"] = {"ball": ball, "collapsible": collapsible, "land": land, "rule": note,
                             "density": ctx.density}

    b = ctx.builder()
    r0, c0 = (rows - depop) // 2, (cols - depop) // 2
    count = 0
    for r in range(rows):
        y = ((rows - 1) / 2 - r) * e
        for c in range(cols):
            if depop and r0 <= r < r0 + depop and c0 <= c < c0 + depop:
                continue
            if (r, c) in missing:
                continue
            x = (c - (cols - 1) / 2) * e
            b.smd_pad(f"{row_name(r)}{c + 1}", x, y, land, land, shape="circle")
            count += 1
    if count == 0:
        raise ValueError("Alle Kugeln sind als fehlend markiert.")
    body = b.body(rect_centered(0, 0, en, dn))
    b.silk_outline_outside(body)
    b.pin1_dot([dot_corner(b, body)], push=(-0.7071, 0.7071))
    b.assembly_rect(body, chamfer=b.pin1_chamfer(body))

    h, a1 = A.max, nom(A1)
    substrate = min(0.36, 0.3 * (h - a1))
    b.box("Substrate", body, a1, a1 + substrate, BGA_SUBSTRATE)
    b.box("Mold", body, a1 + substrate, h, IC_BODY)
    segments = 8 if count <= 256 else 4
    for pad in b.pads:
        b.prism(f"Ball {pad.designator}", circle_points(pad.x, pad.y, ball / 2, segments, start=22.5), 0.0, a1, TIN)

    ipc_name = naming.ipc_bga(count, collapsible, e, cols, rows, dn, en, h)
    if ctx.density != "N":
        ipc_name += ctx.density
    house_name = naming.house(f"BGA-{count} {cols}x{rows} P{naming.short_num(e)} {naming.house_body(en, dn)}",
                              ctx.density, manufacturer=p.text("manufacturer"), code=p.text("package_code"))
    description = describe("BGA", count, dn, en, ctx.density, pitch=e, extra=f"Ball {ball:.2f}mm")
    return ctx.finish(b, ipc_name=ipc_name, house_name=house_name, description=description,
                      package=f"BGA-{count} ({cols}×{rows})", height=h, courtyard_kind="bga")


FAMILIES = [FamilyDef(INFO, build, aliases=("fbga", "lfbga", "tfbga", "vfbga", "wlcsp", "csp", "ball_grid_array"),
                      free_params=frozenset({"A1"}), max_only=frozenset({"A"}))]
