"""Plausibility checks (partforge.footprints.validate)."""
from __future__ import annotations

from partforge.footprints import FootprintRequest, generate, validate_footprint
from partforge.geometry.model import Arc, Body3D, FootprintSpec, Pad, Point, Region, Track


def _codes(spec: FootprintSpec, **kwargs) -> dict[str, str]:
    return {i.code: i.severity for i in validate_footprint(spec, **kwargs)}


def _courtyard(x: float, y: float) -> list[Track]:
    pts = [(-x, -y), (x, -y), (x, y), (-x, y), (-x, -y)]
    return [Track(layer="courtyard", x1=a[0], y1=a[1], x2=b[0], y2=b[1], width=0.05) for a, b in zip(pts, pts[1:])]


def _base() -> FootprintSpec:
    return FootprintSpec(
        name="TEST",
        pads=[Pad(designator="1", x=-1, y=0, width=0.8, height=1.0), Pad(designator="2", x=1, y=0, width=0.8,
                                                                          height=1.0)],
        tracks=_courtyard(2, 1),
    )


def test_clean_footprint_has_no_issues():
    assert _codes(_base()) == {}


def test_generated_footprints_are_clean():
    for fam, preset in (("chip", "R-0603"), ("gullwing", "TSSOP-16"), ("nolead", "QFN-32-5x5-P0.5")):
        issues = validate_footprint(generate(FootprintRequest(family=fam, params={"preset": preset})))
        assert [i for i in issues if i.severity != "info"] == []


def test_silk_over_pad_is_an_error():
    spec = _base()
    spec.tracks.append(Track(layer="top_silk", x1=-2, y1=0, x2=2, y2=0, width=0.15))
    codes = _codes(spec)
    assert codes["silk_over_pad"] == "error"


def test_silk_too_close_is_a_warning():
    spec = _base()
    spec.tracks.append(Track(layer="top_silk", x1=-1.5, y1=0.65, x2=1.5, y2=0.65, width=0.1))  # 0.1 mm gap
    assert _codes(spec)["silk_clearance"] == "warning"


def test_silk_dot_and_region_over_pad():
    spec = _base()
    spec.arcs.append(Arc(layer="top_silk", cx=-1, cy=0.4, r=0.125, start=0, end=360, width=0.25))
    assert _codes(spec)["silk_over_pad"] == "error"
    spec = _base()
    spec.regions.append(Region(layer="top_silk", points=[Point(x=0.8, y=-0.2), Point(x=1.2, y=-0.2),
                                                         Point(x=1.2, y=0.2)]))
    assert _codes(spec)["silk_over_pad"] == "error"
    spec = _base()
    spec.arcs.append(Arc(layer="top_silk", cx=0, cy=0, r=1.0, start=0, end=180, width=0.1))
    assert "silk_over_pad" in _codes(spec)


def test_pad_overlap_and_clearance():
    spec = _base()
    spec.pads[1].x = -0.5
    assert _codes(spec)["pad_overlap"] == "error"
    spec = _base()
    spec.pads[1].x = -1 + 0.8 + 0.1  # 0.1 mm gap
    assert _codes(spec)["pad_clearance"] == "warning"
    spec = _base()
    spec.pads.append(Pad(designator="1", x=-1, y=0.5, width=0.8, height=1.0))  # same net: allowed
    codes = _codes(spec)
    assert "pad_overlap" not in codes and codes["duplicate_designator"] == "info"


def test_courtyard_checks():
    spec = _base()
    spec.tracks = []
    assert _codes(spec)["courtyard_missing"] == "error"
    spec = _base()
    spec.tracks = _courtyard(1.2, 1)
    assert _codes(spec)["courtyard"] == "error"
    spec = _base()
    spec.bodies.append(Body3D(outline=[Point(x=-3, y=-0.5), Point(x=3, y=-0.5), Point(x=3, y=0.5)], z_top=1))
    assert _codes(spec)["courtyard_body"] == "error"


def test_tht_annular_ring_and_paste_windows():
    spec = _base()
    spec.pads.append(Pad(designator="3", x=0, y=3, width=1.0, height=1.0, side="through", hole=0.95, shape="circle"))
    spec.tracks = _courtyard(3, 4)
    assert _codes(spec)["annular_ring"] == "error"
    spec = _base()
    spec.pads.append(Pad(designator="EP", x=0, y=3, width=1.0, height=1.0, thermal=True, paste=False))
    spec.regions.append(Region(layer="top_paste", points=[Point(x=2, y=2), Point(x=3, y=2), Point(x=3, y=3)]))
    spec.tracks = _courtyard(4, 4)
    assert _codes(spec)["paste_window"] == "warning"


def test_name_checks():
    spec = _base()
    spec.name = "A/B"
    assert _codes(spec)["name"] == "error"
    spec.name = ""
    assert _codes(spec)["name"] == "error"


def test_calc_gap_check_and_no_pads():
    spec = _base()
    calc = {"lands": [{"label": "Pads", "g": -0.1, "z": 2.0, "table_key": "gullwing"},
                      {"label": "Fahne", "g": -1.5, "z": 9.0, "table_key": "flat_lug"}]}
    issues = validate_footprint(spec, calc=calc)
    assert [i.code for i in issues] == ["gap"]
    assert _codes(FootprintSpec(name="X", tracks=_courtyard(1, 1)))["no_pads"] == "error"
