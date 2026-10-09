"""Every family × preset × density generates a consistent house-style footprint."""
from __future__ import annotations

import json
import re

import pytest

from partforge.footprints import (
    FootprintRequest,
    ParamError,
    families,
    family_info,
    generate,
    presets,
    preview,
    validate_footprint,
)
from partforge.footprints.params import parse_tol
from partforge.workspace import FootprintStyle

STYLE = FootprintStyle()
SMALL_SILK_FAMILIES = {"chip", "molded", "melf"}
THT_FAMILIES = {"dip", "axial", "radial", "to92", "to220", "pin_header"}


def _ep(params: dict) -> int:
    e2 = params.get("E2")
    if e2 is None:
        return 0
    t = parse_tol(e2)
    return 1 if t is not None and t.max > 0 else 0


def expected_pad_count(family: str, params: dict) -> int:
    if family in ("chip", "molded", "melf", "sod", "do214", "axial", "radial"):
        return 2
    if family in ("sot23", "sc70", "sot523", "to220"):
        return int(params["pins"])
    if family == "sot89":
        return 3
    if family in ("sot223",):
        return 4
    if family == "to92":
        return 3
    if family == "dpak":
        return int(params["leads"]) + 1
    if family in ("gullwing", "qfp", "nolead"):
        return int(params["pins"]) + _ep(params)
    if family == "bga":
        return params["rows"] * params["cols"] - params.get("depop_center", 0) ** 2
    if family == "dip":
        return params["pins"]
    if family == "pin_header":
        return int(params["rows"]) * params["pins_per_row"]
    raise AssertionError(family)


CASES = [(f.key, p.key) for f in families() for p in f.presets]


def test_family_catalogue():
    keys = [f.key for f in families()]
    assert keys == ["chip", "molded", "melf", "sod", "do214", "sot23", "sc70", "sot523", "sot89", "sot223", "dpak",
                    "gullwing", "qfp", "nolead", "bga", "dip", "axial", "radial", "to92", "to220", "pin_header"]
    assert len(CASES) > 150


@pytest.mark.parametrize("family", [f.key for f in families()])
def test_family_metadata(family):
    info = family_info(family)
    assert info.label and info.group and info.description
    assert info.presets, "jede Familie hat Vorlagen"
    names = [p.name for p in info.params]
    assert len(names) == len(set(names))
    for spec in info.params:
        assert spec.kind in ("tol", "float", "int", "bool", "enum", "text")
        assert spec.label.strip()
        assert spec.group
        if spec.kind == "enum":
            assert spec.options
            if spec.default is not None:
                assert spec.default in spec.options
        if spec.kind == "tol" and spec.default is not None:
            assert parse_tol(spec.default) is not None
    preset_keys = [p.key for p in info.presets]
    assert len(preset_keys) == len(set(preset_keys))
    for preset in info.presets:
        assert preset.label
        unknown = set(preset.params) - set(names)
        assert not unknown, f"{preset.key}: unbekannte Parameter {unknown}"
        json.dumps(preset.params)  # JSON-serialisable for the API


@pytest.mark.parametrize(("family", "preset"), CASES, ids=[f"{f}:{p}" for f, p in CASES])
@pytest.mark.parametrize("density", ["M", "N", "L"])
def test_every_preset_generates_consistently(family, preset, density):
    params = next(p.params for p in presets(family) if p.key == preset)
    pv = preview(FootprintRequest(family=family, params={"preset": preset}, density=density), STYLE, svg=False)
    spec = pv.spec
    # pads
    assert len(spec.pads) == expected_pad_count(family, params)
    designators = [p.designator for p in spec.pads]
    assert len(designators) == len(set(designators)), "keine doppelten Pad-Bezeichner"
    assert "1" in designators or "A1" in designators
    # checks: no silk over pads, courtyard encloses pads + bodies, no overlapping pads
    bad = [i for i in pv.issues if i.severity == "error"
           or i.code in ("silk_over_pad", "silk_clearance", "pad_overlap", "pad_clearance", "courtyard")]
    assert not bad, [i.message for i in bad]
    # house style primitives
    silk_width = STYLE.silk_width_small if family in SMALL_SILK_FAMILIES else STYLE.silk_width
    silk_tracks = [t for t in spec.tracks if t.layer == "top_silk"]
    tiny_chip = family == "chip" and params.get("size") in ("01005", "0201") and params["kind"] not in ("D", "LED")
    assert bool(silk_tracks) != tiny_chip or family == "bga"
    assert all(t.width == silk_width for t in silk_tracks)
    courtyard = [t for t in spec.tracks if t.layer == "courtyard"]
    assert len([t for t in courtyard if t.width == STYLE.courtyard_width]) == 4
    assert all(t.width == STYLE.assembly_width for t in spec.tracks if t.layer == "assembly")
    assert {(t.layer, t.text, t.x, t.y) for t in spec.texts} == {
        ("designator", ".Designator", 0, 0), ("comment", ".Comment", 0, 0)}
    assert all(0.3 <= t.height <= STYLE.text_height for t in spec.texts)
    assert not [t for t in spec.texts if t.layer == "top_silk"], "keine Texte im Bestückungsdruck"
    for pad in spec.pads:
        if family in THT_FAMILIES:
            assert pad.side == "through" and pad.hole and pad.hole < min(pad.width, pad.height)
            assert pad.shape == ("rect" if pad.designator == "1" else pad.shape)
            assert pad.shape in ("rect", "circle", "oval")
        elif pad.thermal:
            assert pad.shape == "rect"
        elif family == "bga":
            assert pad.shape == "circle"
        else:
            assert pad.shape == "roundrect"
            assert pad.corner_radius_pct == STYLE.pad_corner_radius_pct
    # 3D and metadata
    assert spec.bodies
    assert all(b.z_top > b.z_bottom >= 0 for b in spec.bodies)
    assert all(re.fullmatch(r"#[0-9A-F]{6}", b.color) for b in spec.bodies)
    assert spec.height == pytest.approx(max(b.z_top for b in spec.bodies))
    assert spec.family == family and spec.density == density and spec.ipc_name
    assert spec.description.isascii()
    assert all(v.isascii() for v in spec.parameters.values())
    assert spec.generator and spec.generator["family"] == family and spec.generator["density"] == density
    json.dumps(spec.generator)
    assert pv.calc["pad_count"] == len(spec.pads)
    cy = pv.calc["courtyard"]
    assert cy["x1"] < cy["x2"] and cy["y1"] < cy["y2"]


@pytest.mark.parametrize(("family", "preset"), CASES[::7], ids=[f"{f}:{p}" for f, p in CASES[::7]])
def test_regeneration_from_generator_record(family, preset):
    spec = generate(FootprintRequest(family=family, params={"preset": preset}, density="L"), STYLE)
    g = spec.generator
    again = generate(FootprintRequest(family=g["family"], params=g["params"], density=g["density"]), STYLE)
    assert again.model_dump() == spec.model_dump() | {"generator": again.generator}
    assert again.pads == spec.pads


def test_default_request_per_family_works():
    for info in families():
        spec = generate(FootprintRequest(family=info.key), STYLE)
        assert spec.pads, info.key


def test_density_from_style_unless_request_sets_it():
    style_l = FootprintStyle(density="L")
    assert generate(FootprintRequest(family="chip", params={"preset": "R-0805"}), style_l).density == "L"
    assert generate(FootprintRequest(family="chip", params={"preset": "R-0805"}, density="M"), style_l).density == "M"


def test_density_changes_pads_and_courtyard():
    specs = {d: preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, density=d), STYLE, svg=False)
             for d in "MNL"}
    lengths = {d: pv.spec.pads[0].width for d, pv in specs.items()}
    assert lengths["M"] > lengths["N"] > lengths["L"]
    excess = {d: pv.calc["courtyard"]["excess"] for d, pv in specs.items()}
    assert excess == {"M": 0.5, "N": 0.25, "L": 0.1}


def test_with_3d_false_and_style_switch():
    req = FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, with_3d=False)
    spec = generate(req, STYLE)
    assert spec.bodies == [] and spec.height == pytest.approx(1.75)
    spec = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}),
                    FootprintStyle(generate_3d=False))
    assert spec.bodies == []


def test_style_options_are_applied():
    style = FootprintStyle(pad_corner_radius_pct=25, silk_width=0.25, silk_width_small=0.12, center_cross=False,
                           exposed_pad_designator="EP", pin1_dot_radius=0.1, courtyard_width=0.06)
    qfn = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5"}), style)
    assert qfn.pads[-1].designator == "EP"
    assert {p.corner_radius_pct for p in qfn.pads if not p.thermal} == {25}
    assert {t.width for t in qfn.tracks if t.layer == "top_silk"} == {0.25}
    assert len([t for t in qfn.tracks if t.layer == "courtyard"]) == 4  # no centre cross
    assert {t.width for t in qfn.tracks if t.layer == "courtyard"} == {0.06}
    dot = next(a for a in qfn.arcs if a.layer == "top_silk")
    assert (dot.r, dot.width) == (0.1, 0.2)
    chip = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}), style)
    assert {t.width for t in chip.tracks if t.layer == "top_silk"} == {0.12}


def test_ep_name_parameter_overrides_style():
    spec = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5", "ep_name": "HS"}))
    assert spec.pads[-1].designator == "HS"


def test_rounding_mode_ipc_gives_hundredths():
    kicad = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}), FootprintStyle(rounding="kicad"))
    ipc = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}), FootprintStyle(rounding="ipc"))
    assert kicad.pads[0].width == pytest.approx(1.95)
    assert ipc.pads[0].width != kicad.pads[0].width
    assert round(ipc.pads[0].height, 2) == ipc.pads[0].height
    override = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8", "rounding": "ipc"}),
                        FootprintStyle(rounding="kicad"))
    assert override.pads[0].width == ipc.pads[0].width


def test_fab_and_placement_tolerance_parameters():
    base = generate(FootprintRequest(family="chip", params={"preset": "R-1206"}))
    loose = generate(FootprintRequest(family="chip", params={"preset": "R-1206", "fab_tolerance": 0.3,
                                                              "placement_tolerance": 0.3}))
    assert loose.pads[0].width > base.pads[0].width


def test_courtyard_parameters():
    pv = preview(FootprintRequest(family="chip", params={"preset": "R-0603", "courtyard_excess": 0.5,
                                                          "courtyard_grid": 0.01}), svg=False)
    cy = pv.calc["courtyard"]
    assert cy["excess"] == 0.5 and cy["grid"] == 0.01
    pad_edge = max(p.x + p.width / 2 for p in pv.spec.pads)
    assert cy["x2"] == pytest.approx(round(pad_edge + 0.5 + 0.005, 2), abs=0.011)


def test_small_parts_get_scaled_text():
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0201"}))
    assert all(t.height < 1.0 for t in spec.texts)
    big = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}))
    assert all(t.height == 1.0 for t in big.texts)


def test_polarised_parts_mark_the_cathode_side():
    left = generate(FootprintRequest(family="sod", params={"preset": "SOD-123"}))
    right = generate(FootprintRequest(family="sod", params={"preset": "SOD-123", "cathode_pad": "2"}))

    def bar_x(spec):  # the vertical silk bar of the bracket
        bars = [t for t in spec.tracks if t.layer == "top_silk" and abs(t.x1 - t.x2) < 1e-9]
        assert len(bars) == 1
        return bars[0].x1

    assert bar_x(left) < 0 < bar_x(right)


def test_ic_pin1_dot_is_outside_copper():
    for fam, preset in (("gullwing", "SOIC-8"), ("sot23", "SOT-23-3"), ("qfp", "LQFP-48-7x7-P0.5"),
                        ("nolead", "QFN-16-3x3-P0.5"), ("bga", "BGA-64-8x8-P0.8"), ("pin_header", "1x04-P2.54")):
        spec = generate(FootprintRequest(family=fam, params={"preset": preset}))
        dots = [a for a in spec.arcs if a.layer == "top_silk" and a.width >= 2 * a.r - 1e-9]
        assert len(dots) == 1, fam
        assert dots[0].cx < 0, fam  # pin 1 is on the left / upper left
        assert not [i for i in validate_footprint(spec) if i.code.startswith("silk")], fam


def test_paste_windows_cover_about_65_percent():
    spec = generate(FootprintRequest(family="nolead", params={"preset": "QFN-32-5x5-P0.5"}))
    ep = next(p for p in spec.pads if p.thermal)
    area = 0.0
    for region in spec.regions:
        xs = [pt.x for pt in region.points]
        ys = [pt.y for pt in region.points]
        area += (max(xs) - min(xs)) * (max(ys) - min(ys))
        assert ep.x - ep.width / 2 <= min(xs) and max(xs) <= ep.x + ep.width / 2
    assert 0.60 <= area / (ep.width * ep.height) <= 0.70
    full = generate(FootprintRequest(family="nolead", params={"preset": "QFN-32-5x5-P0.5", "paste_coverage": 1}))
    assert not full.regions and next(p for p in full.pads if p.thermal).paste


def test_qfn_without_exposed_pad_and_rectangular_qfn():
    spec = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5", "E2": 0}))
    assert len(spec.pads) == 16 and not spec.regions
    rect = generate(FootprintRequest(family="nolead", params={
        "pins": 20, "pins_x": 4, "pins_y": 6, "E": [2.95, 3.05], "D": [3.95, 4.05], "E2": 1.5, "D2": 2.5}))
    assert len(rect.pads) == 21
    left = [p for p in rect.pads if p.x < -1 and not p.thermal]
    assert len(left) == 6


#: TI RGY0019B (VQFN-19 3.5×4.5, qfnd819): pin 1/19 on the top side 1.5 mm apart, 2–9 left, 10/11 bottom, 12–18 right
#: with the position between 13 and 14 empty, exposed pad 20.
RGY0019B = {"variant": "QFN", "pins": 19, "pins_x": 2, "pins_y": 8, "e": 0.5, "e_x": 1.5, "pin1": "top", "missing": "14",
            "E": [3.4, 3.6], "D": [4.4, 4.6], "L": [0.3, 0.5], "b": [0.2, 0.3], "A": [0.8, 1.0], "A1": [0.0, 0.05],
            "E2": {"min": 1.6, "nom": 1.7, "max": 1.8}, "D2": {"min": 2.2, "nom": 2.3, "max": 2.4}, "ep_name": "20"}


def test_irregular_qfn_with_pin_1_on_the_top_side_and_a_missing_position():
    spec = generate(FootprintRequest(family="nolead", params=RGY0019B))
    pads = {p.designator: p for p in spec.pads}
    assert list(pads) == [str(n) for n in range(1, 21)]
    assert pads["20"].thermal and (pads["20"].width, pads["20"].height) == (1.7, 2.3)
    top, bottom = [pads["1"], pads["19"]], [pads["10"], pads["11"]]
    assert [p.x for p in top] == [-0.75, 0.75] and [p.x for p in bottom] == [-0.75, 0.75]
    assert all(p.y > 2 for p in top) and all(p.y < -2 for p in bottom)
    assert all(p.height > p.width for p in top + bottom)  # the end pads point along Y
    left = [pads[str(n)] for n in range(2, 10)]
    assert all(p.x < -1.5 for p in left) and [p.y for p in left] == [1.75, 1.25, 0.75, 0.25, -0.25, -0.75, -1.25, -1.75]
    right = [pads[str(n)] for n in range(12, 19)]  # bottom -> top, position -0.75 stays empty
    assert all(p.x > 1.5 for p in right) and [p.y for p in right] == [-1.75, -1.25, -0.25, 0.25, 0.75, 1.25, 1.75]
    assert spec.ipc_name == "QFN50P350X450X100-20N" and spec.name != spec.ipc_name  # not a standard package: tagged
    assert not validate_footprint(spec)
    dots = [a for a in spec.arcs if a.layer == "top_silk" and a.end - a.start >= 359]
    assert len(dots) == 1 and dots[0].cx < 0 and dots[0].cy > 0


def test_irregular_qfn_parameters_change_the_name_only_when_given():
    plain = {k: v for k, v in RGY0019B.items() if k not in ("e_x", "pin1", "missing")}
    plain.update(pins=20, pins_x=2, pins_y=8)
    regular = generate(FootprintRequest(family="nolead", params=plain))
    assert len(regular.pads) == 21 and not {"e_x", "pin1", "missing"} & set(regular.generator["params"])
    irregular = generate(FootprintRequest(family="nolead", params=RGY0019B))
    assert {"e_x", "pin1", "missing"} <= set(irregular.generator["params"]) and irregular.name != regular.name


def test_dfn_with_a_missing_position_numbers_the_remaining_pins():
    spec = generate(FootprintRequest(family="nolead", params={"preset": "SON-8-3x3-P0.65", "pins": 7, "missing": "6"}))
    signal = [p for p in spec.pads if not p.thermal]
    assert [p.designator for p in signal] == ["1", "2", "3", "4", "5", "6", "7"]
    right = [p for p in signal if p.x > 0]  # positions 5 (bottom) … 8 (top), position 6 empty
    assert [p.designator for p in right] == ["5", "6", "7"] and right[0].y < 0 < right[1].y < right[2].y
    assert next(p for p in spec.pads if p.thermal).designator == "8"


def test_manufacturer_land_pattern_of_a_rectangular_qfn_needs_both_row_spacings():
    land = {"pad_width_mm": 0.25, "pad_length_mm": 0.6, "row_spacing_mm": 3.3, "thermal_pad_mm": [1.7, 2.3]}
    with pytest.raises(ValueError, match="oben/unten fehlt der eigene Reihenabstand"):
        generate(FootprintRequest(family="nolead", params=RGY0019B, land_pattern=land))
    spec = generate(FootprintRequest(family="nolead", params=RGY0019B, land_pattern={**land, "row_spacing_y_mm": 4.3}))
    pads = {p.designator: p for p in spec.pads}
    assert (pads["1"].y, pads["10"].y) == (2.15, -2.15) and (pads["2"].x, pads["12"].x) == (-1.65, 1.65)
    assert (pads["1"].width, pads["1"].height) == (0.25, 0.6) and (pads["2"].width, pads["2"].height) == (0.6, 0.25)
    square = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5"}, land_pattern={
        "pad_width_mm": 0.25, "pad_length_mm": 0.7, "row_spacing_mm": 2.9}))
    assert len(square.pads) == 17  # a square body: one spacing fits all four rows


def test_dpak_tab_has_paste_windows_and_three_lead_variant():
    spec = generate(FootprintRequest(family="dpak", params={"preset": "DPAK-2"}))
    assert [p.designator for p in spec.pads] == ["1", "3", "2"]
    assert spec.pads[-1].thermal and not spec.pads[-1].paste
    assert len([r for r in spec.regions if r.layer == "top_paste"]) >= 4
    spec3 = generate(FootprintRequest(family="dpak", params={"preset": "D2PAK-3"}))
    assert [p.designator for p in spec3.pads] == ["1", "2", "3", "4"]
    assert spec3.ipc_name.startswith("TO254P")


def test_bga_naming_and_depopulation():
    spec = generate(FootprintRequest(family="bga", params={"rows": 10, "cols": 10, "e": 0.8, "ball": 0.4,
                                                            "E": 9.0, "A": 1.2, "A1": 0.3, "depop_center": 2,
                                                            "missing": "A1, J10"}))
    names = {p.designator for p in spec.pads}
    assert len(spec.pads) == 100 - 4 - 2
    assert "A1" not in names and "J10" not in names and "A2" in names and "K10" in names
    assert "I1" not in {n[0] + "1" for n in names}  # JEDEC skips I


def test_bga_row_names_skip_letters():
    from partforge.footprints.families.bga import row_name

    assert [row_name(i) for i in range(10)] == list("ABCDEFGHJK")
    assert row_name(19) == "Y"
    assert row_name(20) == "AA"
    assert row_name(21) == "AB"


@pytest.mark.parametrize(("family", "params", "message"), [
    ("xyz", {}, "Unbekannte Gehäusefamilie"),
    ("chip", {"preset": "nope"}, "Unbekannte Vorlage"),
    ("chip", {"kind": "X"}, "nicht zulässig"),
    ("chip", {"size": "9999"}, "Unbekannte Chip-Baugröße"),
    ("chip", {"L": [2.4, 2.6], "W": [2.4, 2.6]}, "fehlt"),
    ("chip", {"preset": "R-0603", "T": [0.8, 0.9]}, "zu groß"),
    ("chip", {"preset": "R-0603", "L": [-0.5, 1]}, "negative"),
    ("gullwing", {"pins": 7}, "gerade"),
    ("gullwing", {"E": [3.0, 3.2], "E1": [3.8, 4.0]}, "E1"),
    ("gullwing", {"pins": 3.5}, "ganze Zahl"),
    ("qfp", {"pins": 50}, "durch 4"),
    ("qfp", {"pins": 48, "pins_x": 10, "pins_y": 10}, "passen nicht"),
    ("nolead", {"pins": 19, "pins_x": 2, "pins_y": 8}, "passen nicht zu 19 Anschlüssen insgesamt"),
    ("nolead", {"pins": 19, "pins_x": 3, "pins_y": 8, "missing": "14"}, "19 Anschlüssen und 1 fehlenden"),
    ("nolead", {"pins": 19, "pins_x": 2, "pins_y": 8, "missing": "21"}, "Position 21 gibt es nicht"),
    ("nolead", {"pins": 15, "missing": "A1"}, "keine Positionsnummer"),
    ("nolead", {"variant": "DFN", "pins": 7}, "gerade"),
    ("bga", {"rows": 30, "cols": 30, "e": 1.0, "E": 10}, "Kugelraster"),
    ("bga", {"missing": "Z99"}, "gibt es"),
    ("axial", {"pitch": 5.0}, "zu klein"),
    ("radial", {"F": 10.0}, "kleiner als der Durchmesser"),
    ("sot23", {"pins": "4"}, "nicht zulässig"),
    ("pin_header", {"pins_per_row": 0}, "Minimum"),
])
def test_invalid_parameters_raise_german_value_errors(family, params, message):
    with pytest.raises(ValueError, match=message):
        generate(FootprintRequest(family=family, params=params))


def test_unknown_parameters_are_reported():
    pv = preview(FootprintRequest(family="chip", params={"preset": "R-0603", "pinz": 3}), svg=False)
    assert any("pinz" in w for w in pv.warnings)


def test_radial_silk_is_a_true_circle_when_unclipped():
    spec = generate(FootprintRequest(family="radial", params={"preset": "D10x16-P5"}))
    circles = [a for a in spec.arcs if a.layer == "top_silk" and a.width < 2 * a.r]
    assert len(circles) == 1 and circles[0].r > 5.0
    assert not [i for i in validate_footprint(spec) if i.code.startswith("silk")]


def test_param_error_is_value_error():
    assert issubclass(ParamError, ValueError)


def test_clamp_warnings_reach_the_preview():
    pv = preview(FootprintRequest(family="sot523", params={"preset": "SOT-523"}, density="M"), svg=False)
    assert any("Mindestabstand" in w for w in pv.warnings)
    land = pv.calc["lands"][0]
    assert land["g_rounded"] < 0 < land["g"]
    pv = preview(FootprintRequest(family="gullwing", params={"preset": "MSOP-8"}, density="M"), svg=False)
    assert any("Kupferabstand" in w for w in pv.warnings)


def test_manufacturer_land_pattern_override():
    lp = {"pad_width_mm": 0.6, "pad_length_mm": 2.0, "pad_pitch_mm": 1.27, "row_spacing_mm": 4.8,
          "row_spacing_reference": "center_to_center", "present_in_datasheet": True}
    pv = preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, land_pattern=lp), svg=False)
    pad1 = pv.spec.pads[0]
    assert (pad1.x, pad1.width, pad1.height) == (-2.4, 2.0, 0.6)
    assert pv.calc["lands"][0]["source"] == "manufacturer"
    assert pv.calc["standard"] == "Herstellerempfehlung"
    assert pv.spec.generator["land_pattern"] == lp
    inner = preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"},
                                     land_pattern={"pad_width": 0.6, "pad_length": 2.0, "row_spacing": 2.8,
                                                   "row_spacing_reference": "inner_edges"}), svg=False)
    assert inner.spec.pads[0].x == pytest.approx(-2.4)
    outer = preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"},
                                     land_pattern={"pad_width": 0.6, "pad_length": 2.0, "row_spacing": 6.8,
                                                   "row_spacing_reference": "outer_edges"}), svg=False)
    assert outer.spec.pads[0].x == pytest.approx(-2.4)


def test_incomplete_or_unsupported_override_falls_back_to_ipc():
    pv = preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"},
                                  land_pattern={"pad_width": 0.6}), svg=False)
    assert pv.calc["lands"][0]["source"] == "ipc"
    assert any("unvollständig" in w for w in pv.warnings)
    pv = preview(FootprintRequest(family="bga", params={"preset": "BGA-64-8x8-P0.8"},
                                  land_pattern={"pad_width": 0.3, "pad_length": 0.3, "row_spacing": 1}), svg=False)
    assert any("nicht unterstützt" in w for w in pv.warnings)
    pv = preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"},
                                  land_pattern={"present_in_datasheet": False, "pad_width_mm": -1}), svg=False)
    assert pv.calc["lands"][0]["source"] == "ipc" and not pv.warnings


def test_preview_contains_svg_and_validation_results():
    pv = preview(FootprintRequest(family="chip", params={"preset": "C-0402"}))
    assert pv.svg and pv.svg.startswith("<svg")
    assert isinstance(pv.issues, list)
    assert validate_footprint(pv.spec) == [i for i in pv.issues]


def test_chip_custom_dimensions_match_standard_size_name():
    spec = generate(FootprintRequest(family="chip", params={"kind": "R", "L": [1.85, 2.15], "W": [1.1, 1.4],
                                                            "T": [0.15, 0.65]}))
    assert spec.ipc_name == "RESC2012X60N"  # size 0805 recognised, height from the size table
    custom = preview(FootprintRequest(family="chip", params={"kind": "C", "L": [2.4, 2.6], "W": [2.4, 2.6],
                                                             "T": [0.3, 0.5]}), svg=False)
    assert custom.spec.ipc_name.startswith("CAPC2525X")
    assert any("Bauhöhe nicht angegeben" in w for w in custom.warnings)


def test_chip_kind_without_table_entry_uses_fallback_with_warning():
    pv = preview(FootprintRequest(family="chip", params={"kind": "LED", "size": "2512"}), svg=False)
    assert any("keine typischen Maße" in w for w in pv.warnings)
    assert pv.spec.ipc_name.startswith("LEDC6332")
