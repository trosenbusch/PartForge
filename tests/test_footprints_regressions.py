"""Regression tests for the footprint review findings (DIP pad axis, axial sizes, exposed pads,
pin rows, validation gate of generate(), huge values, SOD-523 rounding, fast pad checks)."""
from __future__ import annotations

import itertools
import re

import pytest
from fastapi.testclient import TestClient

from partforge.app import create_app
from partforge.footprints import FootprintRequest, ParamError, generate, preview, validate_footprint
from partforge.footprints import geom
from partforge.footprints.validate import _pad_shape_poly, check_pads
from partforge.geometry.model import FootprintSpec, Pad
from partforge.workspace import FootprintStyle, set_current

STYLE = FootprintStyle()
SHRINK_DIP = {"pins": 28, "e": 1.778, "eA": 10.16, "D": [25.8, 26.4], "E1": [8.4, 8.9]}


# --------------------------------------------------------------------------- DIP: oval narrow along the pitch


@pytest.mark.parametrize("density", ["M", "N", "L"])
@pytest.mark.parametrize("extra", [{}, {"drill": 1.0}, {"pad_diameter": 1.9}, {"pad_shape": "oval"}])
def test_shrink_dip_pads_never_overlap(density, extra):
    pv = preview(FootprintRequest(family="dip", params={**SHRINK_DIP, **extra}, density=density), STYLE, svg=False)
    assert not [i for i in pv.issues if i.code in ("pad_overlap", "pad_clearance")], pv.warnings
    for pad in pv.spec.pads:
        assert pad.height <= 1.778 - 0.15 + 1e-9  # Y = pitch direction
        assert pad.width >= pad.height - 1e-9
    generate(FootprintRequest(family="dip", params={**SHRINK_DIP, **extra}, density=density), STYLE)


def test_shrink_dip_density_m_uses_an_oval_across_the_row():
    spec = generate(FootprintRequest(family="dip", params=SHRINK_DIP, density="M"), STYLE)
    pad2 = spec.pads[1]
    assert (pad2.width, pad2.height, pad2.shape) == (pytest.approx(2.3), pytest.approx(1.62), "oval")
    assert spec.pads[0].shape == "rect"


def test_tht_rows_along_x_keep_the_narrow_side_in_x():
    spec = generate(FootprintRequest(family="radial", params={"F": 2.0, "D": [4.5, 5.5], "H": [6.0, 8.0],
                                                              "d": [0.9, 1.0]}, density="M"), STYLE)
    pad = spec.pads[1]
    assert pad.shape == "oval" and pad.width < pad.height  # neighbours follow along X
    assert pad.width <= 2.0 - 0.15 + 1e-9


def test_narrow_dip_row_spacing_limits_the_pad_width():
    pv = preview(FootprintRequest(family="dip", params={"pins": 8, "eA": 5.0, "E1": [3.8, 4.2], "pad_shape": "oval",
                                                        "b": [0.3, 0.4], "c": [0.2, 0.25]}), STYLE, svg=False)
    assert not [i for i in pv.issues if i.severity == "error"]


# --------------------------------------------------------------------------- axial size sets the dimensions


@pytest.mark.parametrize(("size", "lead_max", "pitch"), [
    ("DO-201AD", 1.30, 15.24), ("DO-41", 0.86, 10.16), ("DO-35", 0.56, 7.62), ("DIN0414", 0.85, 15.24),
])
def test_axial_size_supplies_the_dimensions(size, lead_max, pitch):
    spec = generate(FootprintRequest(family="axial", params={"size": size}), STYLE)
    params = spec.generator["params"]
    assert params["d"]["max"] == lead_max and params["pitch"] == pitch
    assert spec.pads[0].hole >= lead_max + 0.2 - 1e-9  # IPC-2222 level B allowance


def test_do201ad_with_explicit_pitch_gets_a_big_enough_hole():
    pv = preview(FootprintRequest(family="axial", params={"size": "DO-201AD", "pitch": 15.24}), STYLE, svg=False)
    assert pv.spec.pads[0].hole >= 1.5 and not pv.warnings


def test_axial_dimensions_not_matching_the_size_are_reported():
    pv = preview(FootprintRequest(family="axial", params={"size": "DO-201AD", "d": [0.5, 0.6]}), STYLE, svg=False)
    assert any("passen nicht zur Bauform DO-201AD" in w for w in pv.warnings)


# --------------------------------------------------------------------------- exposed pads


def test_default_exposed_pad_with_explicit_body_is_reported():
    pv = preview(FootprintRequest(family="nolead", params={"pins": 32, "E": [4.9, 5.1], "e": 0.5, "L": [0.3, 0.5],
                                                           "b": [0.18, 0.3]}), STYLE, svg=False)
    assert any("Exposed Pad nicht angegeben" in w and "Standardwert" in w for w in pv.warnings)


def test_preset_exposed_pad_is_not_reported():
    pv = preview(FootprintRequest(family="nolead", params={"preset": "QFN-32-5x5-P0.5"}), STYLE, svg=False)
    assert not pv.warnings


def test_preset_exposed_pad_with_changed_body_is_reported():
    pv = preview(FootprintRequest(family="nolead", params={"preset": "QFN-32-5x5-P0.5", "E": [5.9, 6.1]}), STYLE,
                 svg=False)
    assert any("Exposed Pad nicht angegeben" in w and "Vorlage" in w for w in pv.warnings)


def test_exposed_pad_with_one_side_only():
    pv = preview(FootprintRequest(family="nolead", params={"variant": "DFN", "pins": 8, "e": 0.5, "E": 2.0, "D": 2.0,
                                                           "L": [0.2, 0.5], "b": [0.18, 0.3], "E2": [0.75, 1.0]}),
                 STYLE, svg=False)
    assert any("D2 fehlt" in w for w in pv.warnings)
    qfp = preview(FootprintRequest(family="qfp", params={"preset": "LQFP-48-7x7-P0.5", "E2": 4.0}), STYLE, svg=False)
    assert any("Exposed Pad unvollständig" in w for w in qfp.warnings)
    assert not [p for p in qfp.spec.pads if p.thermal]


def test_dfn_without_body_y_is_reported():
    pv = preview(FootprintRequest(family="nolead", params={"variant": "DFN", "pins": 8, "e": 0.65, "E": 3.0,
                                                           "E2": 1.6, "D2": 2.4}), STYLE, svg=False)
    assert any("Körper Y (D) fehlt" in w for w in pv.warnings)


# --------------------------------------------------------------------------- pin rows vs. body


@pytest.mark.parametrize("params", [
    {"preset": "QFN-16-3x3-P0.5", "pins": 32},
    {"variant": "DFN", "pins": 16, "e": 0.5, "E": 2.0, "D": 2.0, "E2": 0},
])
def test_no_lead_rows_longer_than_body_are_rejected(params):
    with pytest.raises(ValueError, match="länger als der Körper"):
        generate(FootprintRequest(family="nolead", params=params), STYLE)


# --------------------------------------------------------------------------- generate() validation gate


def test_generate_refuses_overlapping_pads_that_preview_shows():
    params = {"preset": "TQFP-32-7x7-P0.8", "HE": [7.303, 7.635], "b": [0.322, 0.483]}
    pv = preview(FootprintRequest(family="qfp", params=params, density="M"), STYLE, svg=False)
    assert any(i.code == "pad_overlap" for i in pv.issues)  # preview explains the problem …
    with pytest.raises(ValueError, match="kein gültiger Footprint.*überlappen"):  # … generate refuses it
        generate(FootprintRequest(family="qfp", params=params, density="M"), STYLE)


def test_api_step_uses_the_gate():
    set_current(None)
    token = "gate-test"
    with TestClient(create_app(token=token), headers={"X-PartForge-Token": token}) as client:
        r = client.post("/api/footprints/step", json={"family": "qfp", "density": "M", "params": {
            "preset": "TQFP-32-7x7-P0.8", "HE": [7.303, 7.635], "b": [0.322, 0.483]}})
        assert r.status_code == 400 and "überlappen" in r.json()["detail"]["message"]
        r = client.post("/api/footprints/preview", json={"family": "do214", "params": {"A": 1e300}})
        assert r.status_code == 400 and "unplausibel groß" in r.json()["detail"]["message"]


# --------------------------------------------------------------------------- huge values


@pytest.mark.parametrize(("family", "params"), [
    ("do214", {"A": 1e300}), ("sot523", {"preset": "SC-75", "A": 1e300}), ("chip", {"preset": "R-0603", "L": 5000}),
    ("gullwing", {"preset": "SOIC-8", "e": 1e6}), ("bga", {"preset": "BGA-64-8x8-P0.8", "E": [1e9, 2e9]}),
])
def test_absurd_dimensions_raise_german_errors(family, params):
    with pytest.raises(ParamError, match="unplausibel groß"):
        generate(FootprintRequest(family=family, params=params), STYLE)


def test_absurd_land_pattern_numbers_are_ignored():
    pv = preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"},
                                  land_pattern={"pad_width": 1e300, "pad_length": 2.0, "row_spacing": 4.8}),
                 STYLE, svg=False)
    assert pv.calc["lands"][0]["source"] == "ipc" and any("unvollständig" in w for w in pv.warnings)


# --------------------------------------------------------------------------- SOD-523 rounding (examples.md)


@pytest.mark.parametrize(("density", "zgx"), [("M", (2.34, 1.04, 0.50)), ("N", (2.14, 1.04, 0.40)),
                                              ("L", (1.94, 1.04, 0.30))])
def test_sod523_matches_the_documented_example(density, zgx):
    pv = preview(FootprintRequest(family="sod", params={"preset": "SOD-523"}, density=density),
                 FootprintStyle(rounding="kicad"), svg=False)
    land = pv.calc["lands"][0]
    assert (land["z_rounded"], land["g_rounded"], land["x_rounded"]) == pytest.approx(zgx)
    assert land["round_base"] == 0.02 and land["rounding"] == "kicad"


def test_sod123f_keeps_the_005_grid():
    pv = preview(FootprintRequest(family="sod", params={"preset": "SOD-123F"}), FootprintStyle(rounding="kicad"),
                 svg=False)
    assert pv.calc["lands"][0]["round_base"] == 0.05


# --------------------------------------------------------------------------- fast pad checks


def _brute_force(spec: FootprintSpec, min_gap: float) -> list[tuple[str, str, str]]:
    """The former O(n²) pair loop as reference."""
    found = []
    for a, b in itertools.combinations(spec.pads, 2):
        if a.designator == b.designator or not geom.rects_overlap(geom.pad_bbox(a), geom.pad_bbox(b), min_gap):
            continue
        d = geom.dist_polygon_polygon(_pad_shape_poly(a), _pad_shape_poly(b))
        if d <= 1e-4:
            found.append(("pad_overlap", a.designator, b.designator))
        elif d < min_gap - 1e-4:
            found.append(("pad_clearance", a.designator, b.designator))
    return found


def test_sweep_pad_check_equals_brute_force():
    specs = [
        generate(FootprintRequest(family="nolead", params={"preset": "QFN-64-9x9-P0.5"}, density="M"), STYLE),
        generate(FootprintRequest(family="bga", params={"preset": "BGA-128-12x12-P0.8", "missing": "A1, C3"}), STYLE),
        FootprintSpec(name="X", pads=[Pad(designator="1", x=0, y=0, width=1, height=1),
                                      Pad(designator="2", x=0.9, y=0.5, width=1, height=1),
                                      Pad(designator="3", x=2.0, y=0, width=1, height=1),
                                      Pad(designator="4", x=-5, y=0, width=1, height=1),
                                      Pad(designator="5", x=-3.95, y=0.0, width=1, height=1)]),
    ]
    pair = re.compile(r"Pads? (\S+) und (\S+?)[ .]")
    for spec in specs:
        got = []
        for issue in check_pads(spec, 0.15):
            if issue.code in ("pad_overlap", "pad_clearance"):
                m = pair.search(issue.message)
                assert m, issue.message
                got.append((issue.code, *sorted(m.groups())))
        want = [(code, *sorted((a, b))) for code, a, b in _brute_force(spec, 0.15)]
        assert sorted(got) == sorted(want)
    assert sorted(got) == [("pad_clearance", "2", "3"), ("pad_clearance", "4", "5"), ("pad_overlap", "1", "2")]


def test_validation_of_a_large_bga_is_fast():
    import time

    spec = generate(FootprintRequest(family="bga", params={"rows": 40, "cols": 40, "e": 0.5, "ball": 0.3,
                                                           "E": 21.0, "A": 1.2, "A1": 0.2}), STYLE)
    start = time.perf_counter()
    assert not [i for i in validate_footprint(spec) if i.severity == "error"]
    assert time.perf_counter() - start < 2.0
