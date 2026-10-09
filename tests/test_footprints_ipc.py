"""IPC-7351B mathematics (partforge.footprints.ipc7351).

Reference values: docs/entwicklung/recherche/ipc-work/examples.md, produced by the verified
reference implementation ipc7351b_ref.py (F = 0.10, P = 0.05, KiCad round-off).
"""
from __future__ import annotations

import math

import pytest

from partforge.footprints import ipc7351 as ipc
from partforge.footprints.models import Tol

F, P = 0.10, 0.05

# (name, L, T, W, table, round base, Z/G/X at M, N, L)
REFERENCE_ROWS = [
    ("R 01005 (0402M)", (0.38, 0.42), (0.07, 0.13), (0.18, 0.22), "chip_small", 0.02, (1.1, 0.1, 0.4), (0.9, 0.1, 0.3), (0.7, 0.1, 0.2)),
    ("R 0201 (0603M)", (0.57, 0.63), (0.05, 0.15), (0.27, 0.33), "chip_small", 0.02, (1.3, 0.28, 0.5), (1.1, 0.28, 0.4), (0.9, 0.28, 0.3)),
    ("R 0402 (1005M)", (0.95, 1.05), (0.1, 0.3), (0.45, 0.55), "chip_small", 0.02, (1.7, 0.42, 0.7), (1.5, 0.42, 0.6), (1.3, 0.42, 0.5)),
    ("R 0603 (1608M)", (1.5, 1.65), (0.1, 0.5), (0.75, 0.95), "chip", 0.05, (2.8, 0.65, 1.1), (2.4, 0.65, 1.0), (2.0, 0.65, 0.9)),
    ("R 0805 (2012M)", (1.9, 2.2), (0.1, 0.5), (1.1, 1.4), "chip", 0.05, (3.3, 1.1, 1.5), (2.9, 1.1, 1.4), (2.5, 1.1, 1.3)),
    ("R 1206 (3216M)", (3.0, 3.3), (0.2, 0.6), (1.45, 1.75), "chip", 0.05, (4.4, 2.0, 1.85), (4.0, 2.0, 1.75), (3.6, 2.0, 1.65)),
    ("R 1210 (3225M)", (3.0, 3.4), (0.2, 0.6), (2.3, 2.7), "chip", 0.05, (4.5, 2.05, 2.8), (4.1, 2.05, 2.7), (3.7, 2.05, 2.6)),
    ("R 2010 (5025M)", (4.85, 5.15), (0.4, 0.8), (2.35, 2.65), "chip", 0.05, (6.25, 3.45, 2.75), (5.85, 3.45, 2.65), (5.45, 3.45, 2.55)),
    ("R 2512 (6332M)", (6.1, 6.5), (0.4, 0.8), (3.0, 3.3), "chip", 0.05, (7.6, 4.75, 3.4), (7.2, 4.75, 3.3), (6.8, 4.75, 3.2)),
    ("C 0402 (1005M)", (0.95, 1.05), (0.2, 0.4), (0.45, 0.55), "chip_small", 0.02, (1.7, 0.22, 0.7), (1.5, 0.22, 0.6), (1.3, 0.22, 0.5)),
    ("C 0603 (1608M)", (1.45, 1.75), (0.2, 0.5), (0.65, 0.95), "chip", 0.05, (2.85, 0.65, 1.05), (2.45, 0.65, 0.95), (2.05, 0.65, 0.85)),
    ("C 0805 (2012M)", (1.8, 2.2), (0.25, 0.75), (1.05, 1.45), "chip", 0.05, (3.3, 0.6, 1.55), (2.9, 0.6, 1.45), (2.5, 0.6, 1.35)),
    ("C 1206 (3216M)", (3.0, 3.4), (0.25, 0.75), (1.4, 1.8), "chip", 0.05, (4.5, 1.8, 1.9), (4.1, 1.8, 1.8), (3.7, 1.8, 1.7)),
    ("C 1210 (3225M)", (3.0, 3.4), (0.25, 0.75), (2.3, 2.7), "chip", 0.05, (4.5, 1.8, 2.8), (4.1, 1.8, 2.7), (3.7, 1.8, 2.6)),
    ("C 1812 (4532M)", (4.2, 4.8), (0.25, 0.95), (2.9, 3.5), "chip", 0.05, (5.9, 2.7, 3.6), (5.5, 2.7, 3.5), (5.1, 2.7, 3.4)),
    ("Ta A 3216-18", (3.0, 3.4), (0.5, 1.0), (1.1, 1.3), "inward_l", 0.05, (5.0, 0.8, 1.35), (4.4, 1.0, 1.25), (3.8, 1.15, 1.15)),
    ("Ta B 3528-21", (3.3, 3.7), (0.5, 0.9), (2.1, 2.3), "inward_l", 0.05, (5.3, 1.25, 2.35), (4.7, 1.45, 2.25), (4.1, 1.6, 2.15)),
    ("Ta C 6032-28", (5.7, 6.3), (1.0, 1.6), (2.1, 2.3), "inward_l", 0.05, (7.9, 2.35, 2.35), (7.3, 2.55, 2.25), (6.7, 2.75, 2.15)),
    ("Ta D 7343-31", (7.0, 7.6), (1.0, 1.6), (2.3, 2.5), "inward_l", 0.05, (9.2, 3.65, 2.55), (8.6, 3.85, 2.45), (8.0, 4.05, 2.35)),
    ("MicroMELF 0102 (Vishay MMU)", (2.1, 2.2), (0.35, 0.45), (1.0, 1.1), "melf", 0.05, (3.45, 0.85, 1.35), (3.05, 1.05, 1.25), (2.65, 1.2, 1.15)),
    ("MiniMELF 0204 (Vishay MMA)", (3.4, 3.6), (0.7, 0.9), (1.3, 1.4), "melf", 0.05, (4.85, 1.3, 1.65), (4.45, 1.5, 1.55), (4.05, 1.65, 1.45)),
    ("MELF 0207 (Vishay MMB)", (5.65, 5.8), (1.05, 1.25), (2.0, 2.2), "melf", 0.05, (7.05, 2.85, 2.45), (6.65, 3.05, 2.35), (6.25, 3.2, 2.25)),
    ("MiniMELF SOD-80 (Diodes)", (3.3, 3.7), (0.28, 0.5), (1.3, 1.6), "melf", 0.05, (4.9, 2.05, 1.8), (4.5, 2.25, 1.7), (4.1, 2.4, 1.65)),
    ("SMA DO-214AC", (4.8, 5.59), (0.76, 1.52), (1.27, 1.63), "inward_l", 0.05, (7.2, 1.75, 1.65), (6.6, 1.95, 1.55), (6.0, 2.1, 1.45)),
    ("SMB DO-214AA", (5.0, 5.59), (0.76, 1.52), (1.96, 2.21), "inward_l", 0.05, (7.2, 1.9, 2.25), (6.6, 2.1, 2.15), (6.0, 2.25, 2.05)),
    ("SMC DO-214AB", (7.75, 8.13), (0.76, 1.52), (2.75, 3.18), "inward_l", 0.05, (9.75, 4.6, 3.2), (9.15, 4.8, 3.1), (8.55, 4.95, 3.0)),
    ("SOD-123 (Diodes)", (3.55, 3.85), (0.25, 0.4), (0.52, 0.62), "gullwing", 0.05, (4.95, 1.95, 0.75), (4.55, 2.15, 0.75), (4.15, 2.35, 0.7)),
    ("SOD-323 (Nexperia)", (2.3, 2.7), (0.15, 0.45), (0.25, 0.4), "gullwing", 0.05, (3.8, 0.7, 0.55), (3.4, 0.9, 0.5), (3.0, 1.1, 0.45)),
    ("SOD-123F (Nexperia, flat)", (3.4, 3.6), (0.35, 0.55), (0.55, 0.7), "flat_lead", 0.05, (4.25, 2.4, 0.85), (4.05, 2.4, 0.75), (3.85, 2.4, 0.65)),
    ("SOD-523 (Nexperia, flat)", (1.55, 1.7), (0.1, 0.3), (0.26, 0.34), "flat_lead", 0.02, (2.34, 1.04, 0.5), (2.14, 1.04, 0.4), (1.94, 1.04, 0.3)),
    ("SOT-23-3 TO-236AB (JEDEC via KiCad)", (2.1, 2.64), (0.4, 0.6), (0.3, 0.5), "gullwing", 0.05, (3.75, 0.15, 0.65), (3.35, 0.35, 0.6), (2.95, 0.55, 0.55)),
    ("SOT-23-5/6 MO-178 (TI DBV)", (2.6, 3.0), (0.3, 0.6), (0.3, 0.5), "gullwing", 0.05, (4.1, 0.7, 0.65), (3.7, 0.9, 0.6), (3.3, 1.1, 0.55)),
    ("SOT-323/363 SC-70 (Nexperia)", (2.0, 2.2), (0.15, 0.45), (0.2, 0.3), "gullwing", 0.05, (3.35, 0.35, 0.45), (2.95, 0.55, 0.4), (2.55, 0.75, 0.35)),
    ("SOT-523/SC-75 (Diodes SOT523)", (1.45, 1.75), (0.2, 0.4), (0.15, 0.3), "gullwing_fine", 0.05, (2.85, -0.1, 0.35), (2.45, 0.1, 0.3), (2.05, 0.3, 0.25)),
    ("SOT-223 leads (Nexperia)", (6.7, 7.3), (0.7, 1.1), (0.6, 0.8), "gullwing", 0.05, (8.4, 3.9, 0.95), (8.0, 4.1, 0.9), (7.6, 4.3, 0.85)),
    ("SOIC-8 MS-012 (Nexperia SOT96-1)", (5.8, 6.2), (0.4, 1.27), (0.31, 0.51), "gullwing", 0.05, (7.3, 2.8, 0.65), (6.9, 3.0, 0.6), (6.5, 3.2, 0.55)),
    ("TSSOP-16 MO-153 (Nexperia SOT403-1)", (6.2, 6.6), (0.45, 0.75), (0.19, 0.3), "gullwing", 0.05, (7.7, 4.0, 0.45), (7.3, 4.2, 0.4), (6.9, 4.4, 0.35)),
    ("MSOP-8 MO-187 (Nexperia SOT505-1)", (4.7, 5.1), (0.4, 0.7), (0.25, 0.45), "gullwing", 0.05, (6.2, 2.6, 0.6), (5.8, 2.8, 0.55), (5.4, 3.0, 0.5)),
    ("MSOP-10 0.5 MO-187BA (E 4.9+-0.15 assumed)", (4.75, 5.05), (0.4, 0.8), (0.17, 0.33), "gullwing_fine", 0.05, (6.15, 2.45, 0.4), (5.75, 2.65, 0.35), (5.35, 2.85, 0.3)),
    ("SSOP-20 5.3mm MO-150", (7.4, 8.2), (0.55, 0.95), (0.22, 0.38), "gullwing", 0.05, (9.3, 4.9, 0.5), (8.9, 5.1, 0.5), (8.5, 5.3, 0.45)),
    ("LQFP-48 7x7 0.5 (span 9.0+-0.2 assumed)", (8.8, 9.2), (0.45, 0.75), (0.17, 0.27), "gullwing_fine", 0.05, (10.3, 6.6, 0.35), (9.9, 6.8, 0.3), (9.5, 7.0, 0.25)),
    ("LQFP-32 7x7 0.8 (NXP SOT358-1)", (8.85, 9.15), (0.45, 0.75), (0.3, 0.4), "gullwing", 0.05, (10.25, 6.65, 0.55), (9.85, 6.85, 0.5), (9.45, 7.05, 0.45)),
    ("LQFP-100 14x14 0.5 (NXP SOT407-1)", (15.75, 16.25), (0.45, 0.75), (0.17, 0.27), "gullwing_fine", 0.05, (17.35, 13.55, 0.35), (16.95, 13.75, 0.3), (16.55, 13.95, 0.25)),
    ("QFN-16 3x3 0.5 (body +-0.05 assumed)", (2.95, 3.05), (0.3, 0.5), (0.18, 0.3), "qfn", 0.05, (3.9, 2.05, 0.25), (3.7, 2.05, 0.25), (3.5, 2.05, 0.25)),
    ("QFN-32 5x5 0.5 (ADI 05-08-1693)", (4.9, 5.1), (0.3, 0.5), (0.2, 0.3), "qfn", 0.05, (5.95, 4.0, 0.25), (5.75, 4.0, 0.25), (5.55, 4.0, 0.25)),
]


def T(lo: float, hi: float) -> Tol:  # noqa: N802
    return Tol(min=lo, max=hi)


@pytest.mark.parametrize("row", REFERENCE_ROWS, ids=[r[0] for r in REFERENCE_ROWS])
@pytest.mark.parametrize("density", ["M", "N", "L"])
def test_reference_table(row, density):
    name, L, Tt, W, table, base, *expected = row
    exp = dict(zip("MNL", expected, strict=True))[density]
    calc = ipc.land(T(*L), T(*Tt), T(*W), table=table, density=density, F=F, P=P, base=base)
    assert (calc.z, calc.g, calc.x) == pytest.approx(exp, abs=1e-9), name


def test_kicad_rounding_base_per_table():
    assert ipc.round_base(ipc.J_TABLES["chip_small"], "kicad") == 0.02
    assert ipc.round_base(ipc.J_TABLES["chip"], "kicad") == 0.05
    assert ipc.round_base(ipc.J_TABLES["inward_l_7352"], "kicad") == 0.01
    assert ipc.round_base(ipc.J_TABLES["chip"], "ipc") == 0.01


def test_ipc_rounding_mode_uses_hundredths():
    calc = ipc.land(T(1.5, 1.65), T(0.1, 0.5), T(0.75, 0.95), table="chip", density="N", F=F, P=P, rounding="ipc")
    assert calc.round_base == 0.01
    assert calc.z == pytest.approx(round(calc.z_raw, 2))
    assert calc.g == pytest.approx(round(calc.g_raw, 2))
    assert calc.x == pytest.approx(round(calc.x_raw, 2))


def test_round_half_even_like_kicad():
    # exact binary ties: Python round() is half-even, like the KiCad generator
    assert ipc.round_to(0.25, 0.5) == 0.0  # 0.5 -> 0
    assert ipc.round_to(0.75, 0.5) == 1.0  # 1.5 -> 2
    assert ipc.round_to(1.25, 0.5) == 1.0  # 2.5 -> 2
    assert ipc.round_to(1.4999999, 0.05) == 1.5
    assert ipc.round_up(1.2000000001, 0.05) == 1.2
    assert ipc.round_down(1.1999999999, 0.05) == 1.2


def test_inner_span_rms_matches_ipc_7351b_example():
    # Jeff.M (PCB Libraries) quoting IPC-7351B: L 5.8–6.2, T 0.4–1.27 -> Smin 3.26, Smax 5.40, Stol 2.14
    span = ipc.inner_span(T(5.8, 6.2), T(0.4, 1.27))
    assert span.min == pytest.approx(3.26)
    assert span.max == pytest.approx(5.40)
    assert span.tol == pytest.approx(2.14)
    assert span.tol_rms == pytest.approx(math.sqrt(0.4**2 + 2 * 0.87**2))
    assert span.max_rms == pytest.approx(5.40 - (2.14 - span.tol_rms) / 2)
    assert span.max_rms == pytest.approx(4.977, abs=1e-3)  # value quoted in the research report


def test_direct_span_has_no_rms():
    calc = ipc.land(T(5.8, 6.2), T(0.4, 1.27), T(0.31, 0.51), table="gullwing", density="N", F=F, P=P,
                    S=T(3.3, 5.2))
    assert calc.S.mode == "direct"
    assert calc.S.tol_rms == pytest.approx(1.9)
    expected_g = 5.2 - 2 * 0.35 - math.sqrt(1.9**2 + F**2 + P**2)
    assert calc.g_raw == pytest.approx(expected_g, abs=1e-6)


def test_calculation_record_contents():
    calc = ipc.land(T(5.8, 6.2), T(0.4, 1.27), T(0.31, 0.51), table="gullwing", density="N", F=F, P=P,
                    label="Anschlüsse")
    data = calc.model_dump()
    for key in ("table", "toe", "heel", "side", "F", "P", "L", "T", "W", "S", "z_raw", "g_raw", "x_raw",
                "rounding", "round_base", "z", "g", "x", "pad_length", "pad_width", "pad_center", "clamps"):
        assert key in data
    assert data["table"] == "3-2"
    assert (data["toe"], data["heel"], data["side"]) == (0.35, 0.35, 0.03)
    assert data["pad_length"] == pytest.approx(1.95)
    assert data["pad_center"] == pytest.approx(2.475)
    assert data["S"]["mode"] == "rms"


@pytest.mark.parametrize("table", sorted(ipc.J_TABLES))
def test_every_table_has_three_densities_and_ordered_courtyard(table):
    values = ipc.J_TABLES[table].values
    assert set(values) == {"M", "N", "L"}
    assert values["M"].courtyard >= values["N"].courtyard >= values["L"].courtyard
    assert values["M"].toe >= values["N"].toe >= values["L"].toe


def test_unknown_table_and_density_raise_german_errors():
    with pytest.raises(ValueError, match="Unbekannte IPC-Tabelle"):
        ipc.land(T(1, 1), T(0.2, 0.2), T(0.5, 0.5), table="nope", density="N", F=F, P=P)
    with pytest.raises(ValueError, match="Unbekannte Dichte"):
        ipc.land(T(1, 1), T(0.2, 0.2), T(0.5, 0.5), table="chip", density="X", F=F, P=P)  # type: ignore[arg-type]


def test_gullwing_table_selection_by_pitch():
    assert ipc.gullwing_table(1.27) == "gullwing"
    assert ipc.gullwing_table(0.65) == "gullwing"  # 0.65 > 0.625 -> table 3-2 (KiCad rule)
    assert ipc.gullwing_table(0.5) == "gullwing_fine"


def test_clamp_min_gap_for_sot523_at_density_m():
    calc = ipc.land(T(1.45, 1.75), T(0.2, 0.4), T(0.15, 0.3), table="gullwing_fine", density="M", F=F, P=P)
    assert calc.g == pytest.approx(-0.1)
    messages = ipc.clamp_min_gap(calc, 0.15)
    assert messages and "Mindestabstand" in messages[0]
    assert calc.g == pytest.approx(0.15)
    assert calc.g_rounded == pytest.approx(-0.1)  # original value stays in the record
    assert calc.clamps == messages


def test_clamp_pad_width_vs_pitch():
    calc = ipc.land(T(4.7, 5.1), T(0.4, 0.7), T(0.25, 0.45), table="gullwing", density="M", F=F, P=P)
    assert calc.x == pytest.approx(0.6)
    messages = ipc.clamp_pad_width(calc, 0.65, 0.15)
    assert messages and "Kupferabstand" in messages[0]
    assert calc.x == pytest.approx(0.5)
    assert ipc.clamp_pad_width(calc, 0.65, 0.15) == []  # idempotent


def test_clamp_pad_width_impossible_pitch():
    calc = ipc.land(T(4.7, 5.1), T(0.4, 0.7), T(0.25, 0.45), table="gullwing", density="N", F=F, P=P)
    with pytest.raises(ValueError, match="zu klein"):
        ipc.clamp_pad_width(calc, 0.1, 0.15)


def test_clamp_exposed_pad_kicad_rule():
    calc = ipc.land(T(3.0, 3.0), T(0.3, 0.5), T(0.18, 0.30), table="qfn", density="N", F=F, P=P)
    assert calc.g == pytest.approx(2.05)
    assert ipc.clamp_exposed_pad(calc, 1.75)
    assert calc.g == pytest.approx(2.15)
    assert ipc.clamp_exposed_pad(calc, 0.0) == []


def test_check_land_rejects_degenerate_lands():
    calc = ipc.land(T(1.0, 1.0), T(0.2, 0.2), T(0.5, 0.5), table="chip", density="N", F=F, P=P)
    calc.g = calc.z
    with pytest.raises(ValueError, match="Padlänge"):
        ipc.check_land(calc)
    calc.g, calc.x = 0.1, 0.0
    with pytest.raises(ValueError, match="Padbreite"):
        ipc.check_land(calc)


def test_courtyard_rounds_every_side_outward():
    assert ipc.courtyard_rect((-1.0, -0.475, 1.0, 0.475), 0.25, 0.05) == (-1.25, -0.75, 1.25, 0.75)
    assert ipc.courtyard_rect((-1.0, -0.5, 2.0, 0.5), 0.25, 0.05) == (-1.25, -0.75, 2.25, 0.75)
    x1, _y1, x2, _y2 = ipc.courtyard_rect((-1.234, -0.5, 1.234, 0.5), 0.25, 0.01)
    assert (x1, x2) == (-1.49, 1.49)


@pytest.mark.parametrize(("table", "density", "expected"), [
    ("chip", "M", 0.5), ("chip", "N", 0.25), ("chip", "L", 0.1),
    ("chip_small", "N", 0.15), ("flat_lead", "M", 0.2),
])
def test_courtyard_excess(table, density, expected):
    assert ipc.courtyard_excess(table, density) == expected


def test_courtyard_excess_bga_and_tht():
    assert ipc.courtyard_excess(None, "N", kind="bga") == 1.0
    assert ipc.courtyard_excess(None, "M", kind="bga") == 2.0
    assert ipc.courtyard_excess(None, "L", kind="tht") == 0.1


def test_bga_lands_from_ipc_tables():
    assert ipc.bga_land(0.5, "N", True)[0] == pytest.approx(0.40)
    assert ipc.bga_land(0.5, "M", True)[0] == pytest.approx(0.45)  # MMC
    assert ipc.bga_land(0.5, "L", True)[0] == pytest.approx(0.35)
    assert ipc.bga_land(0.4, "N", False)[0] == pytest.approx(0.45)
    # between rows: lower row's values (0.47 -> 0.45 row)
    assert ipc.bga_land(0.47, "N", True)[0] == pytest.approx(0.35)
    value, note = ipc.bga_land(1.0, "N", True)  # outside the table
    assert value == pytest.approx(0.8)
    assert "außerhalb" in note


@pytest.mark.parametrize(("lead", "density", "hole", "pad"), [
    (0.905, "N", 1.15, 1.75),  # 2.54 header, 0.64 square post (IPC-2222 level B)
    (0.65, "M", 0.9, 1.6),  # axial DIN0207 lead, level A
    (0.677, "L", 0.85, 1.35),  # DIP lead, level C
])
def test_tht_hole_and_land(lead, density, hole, pad):
    h = ipc.tht_hole(lead, density)
    assert h == pytest.approx(hole)
    assert ipc.tht_pad(h, density) == pytest.approx(pad)


def test_fmt_mm_german_decimal_comma():
    assert ipc.fmt_mm(0.15) == "0,15"
    assert ipc.fmt_mm(-0.0) == "0,00"
    assert ipc.fmt_mm(2.4751, 3) == "2,475"
