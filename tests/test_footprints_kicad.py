"""The 13 published KiCad footprints that the research reproduced exactly (ipc-footprints.md §1.8),
generated through the full generator in "kicad" rounding mode (F 0.10, P 0.05, density N)."""
from __future__ import annotations

import pytest

from partforge.footprints import FootprintRequest, generate, preview
from partforge.workspace import FootprintStyle

KICAD = FootprintStyle(rounding="kicad", fab_tolerance=0.10, placement_tolerance=0.05, density="N")

# name, family, params, (pad length along span, pad width, |centre offset|)
VECTORS = [
    ("R_0402_1005Metric", "chip", {"kind": "R", "L": [1.0, 1.1], "W": [0.48, 0.6], "T": [0.1, 0.3]},
     (0.54, 0.64, 0.51)),
    ("R_0603_1608Metric", "chip", {"kind": "R", "L": [1.5, 1.7], "W": [0.7, 0.95], "T": [0.15, 0.4]},
     (0.8, 0.95, 0.825)),
    ("R_0805_2012Metric", "chip", {"kind": "R", "L": [1.85, 2.15], "W": [1.1, 1.4], "T": [0.15, 0.65]},
     (1.025, 1.4, 0.9125)),
    ("R_1206_3216Metric", "chip", {"kind": "R", "L": [3.05, 3.35], "W": [1.45, 1.75], "T": [0.25, 0.75]},
     (1.125, 1.75, 1.4625)),
    ("R_2512_6332Metric", "chip", {"kind": "R", "L": [6.15, 6.45], "W": [3.05, 3.35], "T": [0.35, 0.85]},
     (1.225, 3.35, 2.9625)),
    ("C_0805_2012Metric", "chip", {"kind": "C", "L": [1.8, 2.2], "W": [1.05, 1.45], "T": [0.25, 0.55]},
     (1.0, 1.45, 0.95)),
    ("CP_EIA-3216-18_Kemet-A", "molded",
     {"kind": "CAPMP", "L": [3.0, 3.4], "W": [1.4, 1.8], "H": [1.4, 1.8], "F": [1.1, 1.3], "S": [0.5, 1.0],
      "ipc_table": "7352"},
     (1.415, 1.39, 1.3525)),
    ("SOIC-8_3.9x4.9mm_P1.27mm", "gullwing",
     {"variant": "SOIC", "pins": 8, "e": 1.27, "E": [5.8, 6.2], "E1": [3.8, 4.0], "D": [4.8, 5.0],
      "L": [0.4, 1.27], "b": [0.31, 0.51], "A": [1.35, 1.75]},
     (1.95, 0.6, 2.475)),
    ("SOT-23", "sot23", {"pins": "3", "e": 0.95, "E": [2.10, 2.64], "L": [0.30, 0.60], "b": [0.3, 0.5]},
     (1.475, 0.6, 0.9375)),
    ("SOT-23-5", "sot23", {"pins": "5", "e": 0.95, "E": 2.8, "L": [0.3, 0.6], "b": [0.3, 0.5]},
     (1.325, 0.6, 1.1375)),
    ("TSSOP-16_4.4x5mm_P0.65mm", "gullwing",
     {"variant": "TSSOP", "pins": 16, "e": 0.65, "E": 6.4, "E1": [4.3, 4.5], "D": [4.9, 5.1],
      "L": [0.45, 0.75], "b": [0.17, 0.30], "A": [1.0, 1.2]},
     (1.475, 0.4, 2.8625)),
    ("LQFP-48_7x7mm_P0.5mm", "qfp",
     {"pins": 48, "e": 0.5, "HE": 9.0, "E": [6.9, 7.1], "L": [0.45, 0.75], "b": [0.17, 0.27]},
     (1.475, 0.3, 4.1625)),
    ("QFN-16-1EP_3x3mm_P0.5mm_EP1.75", "nolead",
     {"variant": "QFN", "pins": 16, "e": 0.5, "E": 3.0, "L": [0.3, 0.5], "b": [0.18, 0.30], "E2": 1.75,
      "D2": 1.75, "A": [0.7, 0.8]},
     (0.775, 0.25, 1.4625)),
]


@pytest.mark.parametrize(("name", "family", "params", "expected"), VECTORS, ids=[v[0] for v in VECTORS])
def test_kicad_reference_pads(name, family, params, expected):
    spec = generate(FootprintRequest(family=family, params=params), KICAD)
    pad1 = next(p for p in spec.pads if p.designator == "1")
    length, width, centre = expected
    # pin 1 is on the left (2-terminal) / left column (ICs): pads extend along X
    assert pad1.width == pytest.approx(length, abs=1e-9), name
    assert pad1.height == pytest.approx(width, abs=1e-9), name
    assert pad1.x == pytest.approx(-centre, abs=1e-9), name


def test_soic8_pad_positions_and_numbering():
    spec = generate(FootprintRequest(family="gullwing", params=VECTORS[7][2]), KICAD)
    got = [(p.designator, p.x, p.y) for p in spec.pads]
    assert got == [
        ("1", -2.475, 1.905), ("2", -2.475, 0.635), ("3", -2.475, -0.635), ("4", -2.475, -1.905),
        ("5", 2.475, -1.905), ("6", 2.475, -0.635), ("7", 2.475, 0.635), ("8", 2.475, 1.905),
    ]
    assert spec.ipc_name == "SOIC127P600X175-8N"


def test_sot23_pin_layout():
    spec = generate(FootprintRequest(family="sot23", params=VECTORS[8][2]), KICAD)
    assert [(p.designator, p.x, p.y) for p in spec.pads] == [
        ("1", -0.9375, 0.95), ("2", -0.9375, -0.95), ("3", 0.9375, 0.0)]
    spec5 = generate(FootprintRequest(family="sot23", params=VECTORS[9][2]), KICAD)
    assert [(p.designator, round(p.x, 4), p.y) for p in spec5.pads] == [
        ("1", -1.1375, 0.95), ("2", -1.1375, 0.0), ("3", -1.1375, -0.95), ("4", 1.1375, -0.95), ("5", 1.1375, 0.95)]


def test_qfn16_counter_clockwise_with_exposed_pad():
    pv = preview(FootprintRequest(family="nolead", params=VECTORS[12][2]), KICAD, svg=False)
    pads = {p.designator: p for p in pv.spec.pads}
    assert len(pads) == 17
    assert (pads["1"].x, pads["1"].y) == (-1.4625, 0.75)
    assert (pads["4"].x, pads["4"].y) == (-1.4625, -0.75)
    assert (pads["5"].x, pads["5"].y, pads["5"].width, pads["5"].height) == (-0.75, -1.4625, 0.25, 0.775)
    assert (pads["9"].x, pads["9"].y) == (1.4625, -0.75)
    assert (pads["13"].x, pads["13"].y) == (0.75, 1.4625)
    ep = pads["17"]
    assert (ep.x, ep.y, ep.width, ep.height, ep.thermal, ep.paste) == (0.0, 0.0, 1.75, 1.75, True, False)
    # KiCad: heel pulled back to keep 0.2 mm to the EP (G 2.05 -> 2.15)
    land = pv.calc["lands"][0]
    assert land["g_rounded"] == pytest.approx(2.05)
    assert land["g"] == pytest.approx(2.15)
    assert any("Exposed Pad" in w for w in land["clamps"])
    # windowpane paste: 2 x 2 windows of 0.71 mm (KiCad example in the research)
    windows = [r for r in pv.spec.regions if r.layer == "top_paste"]
    assert len(windows) == 4
    xs = sorted({round(pt.x, 4) for pt in windows[0].points})
    assert xs[1] - xs[0] == pytest.approx(0.71)
    assert pv.spec.ipc_name == "QFN50P300X300X80-17N"


def test_lqfp48_layout():
    spec = generate(FootprintRequest(family="qfp", params=VECTORS[11][2]), KICAD)
    assert len(spec.pads) == 48
    pads = {p.designator: p for p in spec.pads}
    assert (pads["1"].x, pads["1"].y) == (-4.1625, 2.75)
    assert (pads["13"].x, pads["13"].y) == (-2.75, -4.1625)
    assert (pads["25"].x, pads["25"].y) == (4.1625, -2.75)
    assert (pads["37"].x, pads["37"].y) == (2.75, 4.1625)
    assert spec.ipc_name == "QFP50P900X900X160-48N"
