"""Conversions PartForge model <-> Rust writer JSON (no executable needed)."""
from __future__ import annotations

import pytest
from test_writer_samples import (
    chip_0603,
    chip_with_step,
    header_tht,
    ic8_symbol,
    opamp_symbol,
    qfn16,
    resistor_symbol,
    soic8,
)

from partforge.altium.rustwriter import (
    RustValidationError,
    bgr_to_hex,
    fix_points,
    footprint_to_rust,
    hex_to_bgr,
    rust_to_footprint,
    rust_to_symbol,
    step_body,
    symbol_to_rust,
    update_symbol_payload,
    validate_footprint_payload,
    validate_symbol_payload,
)
from partforge.geometry.model import (
    Body3D,
    FootprintSpec,
    FpText,
    Pad,
    Point,
    StepModel,
    SymbolSpec,
    SymPin,
    SymText,
)
from partforge.workspace import LayerMap

# --------------------------------------------------------------------------- colours


@pytest.mark.parametrize(
    ("hex_color", "bgr"),
    [("#800000", 128), ("#FFFFB0", 11599871), ("#0000FF", 16711680), ("#808080", 8421504), ("00ff00", 0x00FF00)],
)
def test_hex_bgr_roundtrip(hex_color, bgr):
    assert hex_to_bgr(hex_color) == bgr
    assert bgr_to_hex(bgr) == ("#" + hex_color.lstrip("#")).upper()


@pytest.mark.parametrize("bad", ["red", "#12345", "#GGGGGG", "", None])
def test_hex_to_bgr_rejects_invalid(bad):
    with pytest.raises(ValueError, match="Farbe"):
        hex_to_bgr(bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- symbols


def test_resistor_symbol_payload():
    payload = symbol_to_rust(resistor_symbol())
    assert payload["name"] == "PF_RES"
    assert payload["designator_prefix"] == "R"
    assert payload["part_count"] == 1
    pins = payload["pins"]
    assert pins[0] == {
        "designator": "1",
        "name": "1",
        "x": -10,
        "y": 0,
        "length": 10,
        "orientation": "left",
        "electrical_type": "passive",
        "owner_part_id": 1,
        "show_name": False,
        "show_designator": False,
        "hidden": False,
    }
    assert all(type(p["x"]) is int and type(p["y"]) is int and type(p["length"]) is int for p in pins)
    rect = payload["rectangles"][0]
    assert (rect["x1"], rect["y1"], rect["x2"], rect["y2"]) == (-10.0, -4.0, 10.0, 4.0)
    assert rect["line_color"] == 16711680  # house discrete blue #0000FF as BGR
    assert rect["filled"] is False and rect["line_width"] == 1
    # only the comment parameter (house: visible at (-5, -15)), no other parameters
    assert payload["parameters"] == [{"name": "Comment", "value": "=Value", "x": -5, "y": -15, "owner_part_id": -1}]
    assert "footprints" not in payload
    assert "text" not in payload
    assert validate_symbol_payload(payload) == []


def test_symbol_without_comment_has_no_parameters():
    spec = resistor_symbol()
    spec.comment = "*"
    assert "parameters" not in symbol_to_rust(spec)


def test_ic_symbol_payload_uses_ic_palette_and_enums():
    payload = symbol_to_rust(ic8_symbol())
    rect = payload["rectangles"][0]
    assert rect["line_color"] == 128 and rect["fill_color"] == 11599871 and rect["line_width"] == 0
    assert (rect["x1"], rect["y1"], rect["x2"], rect["y2"]) == (0.0, -50.0, 80.0, 0.0)  # normalised corners
    by_designator = {p["designator"]: p for p in payload["pins"]}
    assert by_designator["7"]["electrical_type"] == "open_collector"
    assert by_designator["4"]["name"] == "R\\E\\S\\E\\T\\"
    assert by_designator["8"]["orientation"] == "right" and by_designator["8"]["x"] == 80
    assert by_designator["2"]["length"] == 20
    params = {p["name"]: p for p in payload["parameters"]}
    assert params["Comment"]["value"] == "NE555DR"
    assert params["Manufacturer"] == {
        "name": "Manufacturer",
        "value": "Texas Instruments",
        "hidden": True,
        "x": -5,
        "y": 15,
        "owner_part_id": -1,
    }
    assert payload["footprints"] == [{"name": "SOIC127P600X175-8N", "description": "SOIC-8"}]


def test_multipart_symbol_payload():
    notes: list[str] = []
    payload = symbol_to_rust(opamp_symbol(), notes=notes)
    assert payload["part_count"] == 3
    parts = sorted({p["owner_part_id"] for p in payload["pins"]})
    assert parts == [1, 2, 3]
    polygons = payload["polygons"]
    assert len(polygons) == 2 and polygons[0]["points"][2] == {"x": 20.0, "y": 0.0}
    assert payload["polylines"][0]["points"] == [{"x": -5.0, "y": 0.0}, {"x": 0.0, "y": 5.0}, {"x": 5.0, "y": 0.0}]
    assert payload["polylines"][0]["line_width"] == 2
    assert payload["arcs"][0]["end_angle"] == 180.0
    assert payload["ellipses"][0]["radius_x"] == 2.0
    labels = payload["labels"]
    assert labels[0]["text"] == "A" and labels[0]["justification"] == "middle_center" and labels[0]["font_id"] == 1
    assert notes == []
    assert validate_symbol_payload(payload) == []


def test_text_size_other_than_10pt_is_reported():
    spec = resistor_symbol()
    spec.graphics.append(SymText(x=0, y=60, text="R", size=12))
    notes: list[str] = []
    symbol_to_rust(spec, notes=notes)
    assert any("12 pt" in n for n in notes)


def test_off_grid_pin_is_rejected_with_german_message():
    spec = resistor_symbol()
    spec.pins[0].x = -95
    with pytest.raises(RustValidationError) as exc:
        symbol_to_rust(spec)
    assert "10-mil-Raster" in str(exc.value)
    assert "nichts geschrieben" in str(exc.value)


def test_pin_on_missing_part_is_rejected():
    spec = resistor_symbol()
    spec.pins[1].part = 2
    with pytest.raises(RustValidationError, match="Teil 2"):
        symbol_to_rust(spec)


@pytest.mark.parametrize("name", ["R_Ω", "SOT-23/5", "A" * 65, " lead", "__PFSTEP_x", ""])
def test_invalid_component_names(name):
    spec = resistor_symbol(name="X")
    spec.name = name
    with pytest.raises(RustValidationError):
        symbol_to_rust(spec)


def test_update_symbol_payload_sets_designator():
    payload = symbol_to_rust(resistor_symbol())
    upd = update_symbol_payload(payload)
    assert upd["designator"] == "R?"
    assert "designator" not in payload  # original untouched


# --------------------------------------------------------------------------- symbol validation


def _pin(**kw):
    base = {"designator": "1", "name": "A", "x": 0, "y": 0, "length": 10, "orientation": "left"}
    base.update(kw)
    return base


@pytest.mark.parametrize(
    ("pin", "fragment"),
    [
        (_pin(x=-10.0), "ganze Zahl"),
        (_pin(designator=1), "Pin-Nummer"),
        (_pin(orientation="west"), "Ausrichtung"),
        (_pin(electrical_type="analog"), "elektrischer Typ"),
        (_pin(symbol_inside="open_collector"), "Pin-Symbol"),
        (_pin(length=10.5), "Pinlänge"),
        (_pin(owner_part_id=3), "Teil 3"),
        (_pin(hidden="yes"), "true/false"),
    ],
)
def test_validate_symbol_payload_pin_issues(pin, fragment):
    issues = validate_symbol_payload({"name": "S", "pins": [pin]})
    assert any(fragment in i for i in issues), issues


def test_validate_symbol_payload_structure_issues():
    issues = validate_symbol_payload(
        {
            "name": "S",
            "pins": [],
            "text": [{"x": 0, "y": 0, "text": "X"}],
            "bogus": 1,
            "polygons": [{"points": [[0, 0], [1, 0], [0, 1]]}],
            "labels": [{"x": 0, "y": 0, "text": "", "justification": "center"}],
            "rectangles": [{"x1": 0, "y1": 0, "x2": 1e9, "y2": 1, "line_width": 7, "fill_color": -1}],
        }
    )
    text = "\n".join(issues)
    assert "labels" in text  # 'text' must not be used
    assert "bogus" in text
    assert "{x, y}" in text
    assert "Text fehlt" in text and "Ausrichtung" in text
    assert "außerhalb" in text and "Linienbreite" in text and "Farbe" in text


# --------------------------------------------------------------------------- footprints


def test_chip_payload_with_house_layers():
    payload = footprint_to_rust(chip_0603(), LayerMap())
    pads = payload["pads"]
    assert pads[0]["shape"] == "rounded_rectangle" and pads[0]["corner_radius_percent"] == 50
    assert pads[0]["layer"] == "Top Layer" and pads[0]["stack_mode"] == "simple"
    assert "hole_size" not in pads[0] and "paste_mask_expansion" not in pads[0]
    layers = {t["layer"] for t in payload["tracks"]}
    assert layers == {"Top Overlay", "Mechanical 15", "Mechanical 9", "Mechanical 17", "Mechanical 21"}
    texts = {t["text"]: t for t in payload["text"]}
    assert texts[".Designator"]["layer"] == "Mechanical 11" and texts[".Comment"]["layer"] == "Mechanical 19"
    assert texts[".Designator"]["justification"] == "middle_center" and texts[".Designator"]["stroke_width"] == 0.15
    body = payload["component_bodies"][0]
    assert body["layer"] == "Mechanical 13" and body["overall_height"] == 0.55 and body["standoff_height"] == 0.0
    assert body["body_color_3d"] == 8421504 and len(body["outline"]) == 4
    assert validate_footprint_payload(payload) == []


def test_pad_shapes_holes_slots_and_plating():
    payload = footprint_to_rust(header_tht())
    pads = {p["designator"]: p for p in payload["pads"]}
    assert pads["1"]["shape"] == "rectangle" and pads["1"]["layer"] == "Multi-Layer" and pads["1"]["hole_size"] == 1.0
    assert pads["2"]["shape"] == "round"
    assert pads["3"]["shape"] == "oval" and pads["3"]["hole_shape"] == "slot"
    assert pads["3"]["hole_slot_length"] == 2.2 and pads["3"]["hole_rotation"] == 90.0  # vertical slot
    assert pads["MH"]["is_plated"] is False
    assert all(p["is_plated"] for k, p in pads.items() if k != "MH")
    assert validate_footprint_payload(payload) == []


def test_exposed_pad_without_paste_and_manual_mask():
    payload = footprint_to_rust(qfn16())
    ep = next(p for p in payload["pads"] if p["designator"] == "17")
    assert ep["paste_mask_expansion"] == -0.85 and ep["paste_mask_expansion_mode"] == "manual"
    assert ep["solder_mask_expansion"] == 0.05 and ep["solder_mask_expansion_mode"] == "manual"
    assert [r["layer"] for r in payload["regions"]] == ["Top Paste"] * 4
    side = next(p for p in payload["pads"] if p["designator"] == "5")
    assert side["rotation"] == 90.0 and side["corner_radius_percent"] == 25


def test_footprint_validation_rejects_inconsistent_pads():
    spec = chip_0603()
    spec.pads[0].hole = 0.5  # hole on an SMD pad
    with pytest.raises(RustValidationError, match="Durchsteck"):
        footprint_to_rust(spec)
    spec = header_tht()
    spec.pads[0].hole = None
    with pytest.raises(RustValidationError, match="ohne Bohrung"):
        footprint_to_rust(spec)
    spec = header_tht()
    spec.pads[2].hole_length = 0.5
    with pytest.raises(RustValidationError, match="Langloch"):
        footprint_to_rust(spec)


@pytest.mark.parametrize(
    ("pad", "fragment"),
    [
        ({"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "layer": "Top Layer"}, "Pad-Form"),
        ({"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "rectangular", "layer": "Top Layer"}, "Pad-Form"),
        ({"designator": "1", "x": 0, "y": 0, "width": 0, "height": 1, "shape": "round", "layer": "Top Layer"}, "größer als 0"),
        ({"designator": "1", "x": 6000, "y": 0, "width": 1, "height": 1, "shape": "round", "layer": "Top Layer"}, "außerhalb"),
        ({"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "round", "layer": "TopLayer"}, "Pad-Lage"),
        (
            {"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "round", "layer": "Top Layer", "stack_mode": "full_stack"},
            "stack_mode",
        ),
        ({"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "round", "layer": "Top Layer", "colour": 1}, "unbekannte Felder"),
        ({"designator": 1, "x": 0, "y": 0, "width": 1, "height": 1, "shape": "round", "layer": "Top Layer"}, "Bezeichner"),
        ({"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "round", "layer": "Top Layer", "hole_size": 0.5}, "Multi-Layer"),
    ],
)
def test_validate_footprint_payload_pad_issues(pad, fragment):
    issues = validate_footprint_payload({"name": "F", "pads": [pad]})
    assert any(fragment in i for i in issues), issues


def test_validate_footprint_payload_other_issues():
    issues = validate_footprint_payload(
        {
            "name": "F",
            "pads": [],
            "tracks": [{"x1": 0, "y1": 0, "x2": 1, "y2": 0, "width": 0.1, "layer": "TopOverlay"}],
            "arcs": [{"x": 0, "y": 0, "radius": 0, "start_angle": 0, "end_angle": 360, "width": 0.1, "layer": "Top Overlay"}],
            "regions": [{"layer": "Top Paste", "vertices": [{"x": 0, "y": 0}]}],
            "text": [{"x": 0, "y": 0, "text": "", "height": 0, "layer": "Mechanical 99"}],
            "component_bodies": [{"overall_height": "1", "body_opacity_3d": 2}],
            "step_model": {"filepath": "x.step", "embed": False},
            "foo": 1,
        }
    )
    text = "\n".join(issues)
    for fragment in ("TopOverlay", "radius", "mindestens 3", "Texthöhe", "Text fehlt", "Mechanical 99", "Gesamthöhe", "Deckkraft", "embed", "foo"):
        assert fragment in text, fragment


def test_step_without_bodies_gets_synthesized_extruded_body():
    spec = chip_with_step("3D/box.step")
    spec.bodies = []
    notes: list[str] = []
    payload = footprint_to_rust(spec, notes=notes)
    body = payload["component_bodies"][0]
    assert body["overall_height"] == 1.25
    assert [(p["x"], p["y"]) for p in body["outline"]] == [(-0.8, -0.4), (0.8, -0.4), (0.8, 0.4), (-0.8, 0.4)]
    assert any("ergänzt" in n for n in notes)
    spec.height = None
    notes.clear()
    payload = footprint_to_rust(spec, notes=notes)
    assert "component_bodies" not in payload
    assert any("Bauhöhe unbekannt" in n for n in notes)


def test_step_body_has_real_height_and_placement():
    spec = chip_with_step("3D/box.step")
    body = step_body(spec, LayerMap(), "{GUID}", "box.step")
    assert body["embedded"] is True and body["model_id"] == "{GUID}" and body["model_name"] == "box.step"
    assert body["overall_height"] == 1.25 and body["standoff_height"] == 0.0
    assert body["layer"] == "Mechanical 13"
    assert body["rotation_z"] == 90.0 and body["z_offset"] == 0.1
    assert body["outline"][0] == {"x": -1.0, "y": -0.625} and body["outline"][2] == {"x": 1.0, "y": 0.625}
    assert validate_footprint_payload({"name": "F", "pads": [], "component_bodies": [body]}) == []


def test_custom_layer_map_is_honoured():
    layer_map = LayerMap(courtyard="Top Courtyard", assembly="Mechanical 2", body3d="Top 3D Body")
    payload = footprint_to_rust(chip_0603(), layer_map)
    layers = {t["layer"] for t in payload["tracks"]}
    assert "Mechanical 4" in layers and "Mechanical 2" in layers
    assert payload["component_bodies"][0]["layer"] == "Mechanical 6"


# --------------------------------------------------------------------------- reverse


def test_rust_to_symbol_reads_point_pairs_and_parameters():
    data = {
        "name": "X",
        "description": "d",
        "designator": "Q?",
        "part_count": 2,
        "pins": [
            {"designator": "1", "name": "B", "x": -20, "y": 0, "length": 20, "orientation": "left", "electrical_type": "bidirectional", "owner_part_id": 1, "hidden": False},
            {"designator": "2", "name": "E", "x": 20, "y": 0, "length": 20, "orientation": "right", "electrical_type": "tristate", "owner_part_id": 0},
        ],
        "polygons": [{"points": [[-2.0, 2.0], [2.0, 2.0], [0.0, 5.0]], "filled": True, "line_color": 255, "fill_color": 65280, "line_width": 1, "owner_part_id": 2}],
        "polylines": [{"points": [[0, 0], [5, 2.5], [10, 0]], "color": 128, "line_width": 2}],
        "lines": [{"x1": -5, "y1": -5, "x2": 5, "y2": 5, "color": 255}],
        "round_rects": [{"x1": 0, "y1": 0, "x2": 10, "y2": 10, "corner_x_radius": 2, "corner_y_radius": 2}],
        "labels": [{"x": 0, "y": 8, "text": "LBL", "justification": "middle_center", "rotation": 90}],
        "text": [{"x": 0, "y": 0, "text": ""}],
        "parameters": [{"name": "Comment", "value": "BC807"}, {"name": "Value", "value": "x"}],
        "footprints": [{"name": "SOT23", "library_path": None, "description": "fp"}],
    }
    spec = rust_to_symbol(data)
    assert spec.designator_prefix == "Q" and spec.comment == "BC807" and spec.parameters == {"Value": "x"}
    assert spec.pins[0].x == -200 and spec.pins[0].electrical == "io" and spec.pins[1].electrical == "hiz"
    assert spec.pins[1].part == 0
    kinds = [g.kind for g in spec.graphics]
    assert kinds.count("polygon") == 1 and kinds.count("line") == 2 and kinds.count("rect") == 1 and kinds.count("text") == 1
    polygon = next(g for g in spec.graphics if g.kind == "polygon")
    assert [(p.x, p.y) for p in polygon.points] == [(-20.0, 20.0), (20.0, 20.0), (0.0, 50.0)]
    assert polygon.color == "#FF0000" and polygon.fill_color == "#00FF00" and polygon.part == 2
    rect = next(g for g in spec.graphics if g.kind == "rect")
    assert rect.corner_radius == 20.0
    label = next(g for g in spec.graphics if g.kind == "text")
    assert label.rotation == 90 and label.justify == "middle_center"
    assert spec.footprints[0].name == "SOT23"


def test_rust_to_footprint_maps_aliases_bodies_and_paste():
    data = {
        "name": "F",
        "pads": [
            {"designator": "1", "x": -0.800001, "y": 0, "width": 0.900001, "height": 0.950001, "shape": "rounded_rectangle", "corner_radius_percent": 25, "layer": "Top Layer"},
            {"designator": "2", "x": 0, "y": 2, "width": 1.7, "height": 1.7, "shape": "round", "layer": "Multi-Layer", "hole_size": 1.0, "is_plated": True},
            {"designator": "3", "x": 0, "y": -2, "width": 3.5, "height": 1.8, "shape": "round", "layer": "Multi-Layer", "hole_size": 1.0, "hole_shape": "slot", "hole_slot_length": 2.6, "is_plated": False},
            {"designator": "17", "x": 0, "y": 0, "width": 1.7, "height": 1.7, "shape": "rectangle", "layer": "Top Layer", "paste_mask_expansion": -0.85, "paste_mask_expansion_mode": "manual", "solder_mask_expansion": 0.05, "solder_mask_expansion_mode": "manual"},
            {"designator": "B", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "octagonal", "layer": "Bottom Layer"},
        ],
        "tracks": [
            {"x1": 0, "y1": 0, "x2": 1, "y2": 0, "width": 0.1, "layer": "Bottom Courtyard"},
            {"x1": 0, "y1": 0, "x2": 1, "y2": 0, "width": 0.1, "layer": "Mechanical 1"},
        ],
        "text": [{"x": 0, "y": 0, "text": ".Comment", "height": 1, "layer": "Bottom 3D Body", "justification": "middle_center"}],
        "fills": [{"x1": -1, "y1": -1, "x2": 1, "y2": 1, "layer": "Top Paste", "rotation": 90}],
        "vias": [{"x": 0, "y": 0, "diameter": 0.5, "hole_size": 0.25}],
        "component_bodies": [
            {"embedded": True, "model_id": "{ID}", "model_name": "box.step", "overall_height": 1.25, "rotation_z": 90, "model_2d_x": 0.1, "z_offset": 0.2, "outline": [[0, 0], [1, 0], [1, 1]]},
            {"embedded": False, "model_id": "", "model_name": "", "overall_height": 0.55, "standoff_height": 0.05, "outline": [[-0.8, -0.4], [0.8, -0.4], [0.8, 0.4]], "body_color_3d": 3158064, "name": " "},
        ],
    }
    notes: list[str] = []
    # layer map of the older TR_* libraries: Mechanical 5/7 come back as Rust aliases
    tr_layers = LayerMap(
        assembly="Mechanical 5", comment="Mechanical 7", designator="Mechanical 9", component_outline="Mechanical 19"
    )
    spec = rust_to_footprint(data, tr_layers, notes=notes)
    pads = {p.designator: p for p in spec.pads}
    assert pads["1"].shape == "roundrect" and pads["1"].corner_radius_pct == 25 and pads["1"].side == "top"
    assert pads["2"].shape == "circle" and pads["2"].side == "through" and pads["2"].hole == 1.0
    assert pads["3"].shape == "oval" and pads["3"].hole_length == 2.6 and pads["3"].plated is False
    assert pads["17"].paste is False and pads["17"].mask_expansion == 0.05
    assert pads["B"].shape == "octagon" and pads["B"].side == "bottom"
    assert [t.layer for t in spec.tracks] == ["assembly"]  # Mechanical 1 is unmapped
    assert spec.texts[0].layer == "comment"
    assert spec.regions[0].layer == "top_paste" and len(spec.regions[0].points) == 4
    assert spec.step is not None and spec.step.file == "box.step" and spec.step.rotation[2] == 90.0
    assert spec.step.offset == (0.1, 0.0, 0.2)
    assert len(spec.bodies) == 1 and spec.bodies[0].z_bottom == 0.05 and spec.bodies[0].color == "#303030"
    assert spec.bodies[0].name == "Body"
    assert spec.height == 1.25
    assert any("Mechanical 1" in n for n in notes) and any("Durchkontaktierung" in n for n in notes)


def test_board_rotation_of_an_imported_model_survives_rewriting():
    """MODEL.2D.ROTATION has no field in the written body: it is folded into the Z rotation."""
    data = {"name": "TURNED", "pads": [], "component_bodies": [
        {"embedded": True, "model_id": "{ID}", "model_name": "turned.step", "rotation_x": 90, "rotation_z": 300,
         "model_2d_rotation": 90, "model_2d_x": 1.5, "overall_height": 1.0, "outline": [[0, 0], [1, 0], [1, 1]]},
    ]}
    spec = rust_to_footprint(data)
    assert spec.step is not None and spec.step.rotation == (90.0, 0.0, 30.0)
    assert spec.step.offset == (1.5, 0.0, 0.0)  # board-plane offsets are not rotated again
    body = step_body(spec, LayerMap(), "{ID}", "turned.step")
    assert (body["rotation_x"], body["rotation_z"], body["model_2d_x"]) == (90.0, 30.0, 1.5)
    assert "model_2d_rotation" not in body


def test_footprint_roundtrip_through_conversions_only():
    for spec in (chip_0603(), soic8(), header_tht(), qfn16()):
        payload = footprint_to_rust(spec)
        # emulate the reader: outlines as point pairs
        for body in payload.get("component_bodies", []):
            body["outline"] = [[p["x"], p["y"]] for p in body["outline"]]
        back = rust_to_footprint(payload)
        assert [p.designator for p in back.pads] == [p.designator for p in spec.pads]
        for a, b in zip(spec.pads, back.pads, strict=True):
            assert (a.x, a.y, a.width, a.height, a.side, a.plated) == (b.x, b.y, b.width, b.height, b.side, b.plated)
            assert a.paste == b.paste
        assert len(back.tracks) == len(spec.tracks)
        assert [(t.layer, t.x1, t.y2) for t in back.tracks] == [(t.layer, t.x1, t.y2) for t in spec.tracks]


def test_fix_points_converts_pairs_only():
    data = {
        "polygons": [{"points": [[0, 0], [1, 0], {"x": 1, "y": 1}]}],
        "polylines": [{"points": [[0, 0], [2, 2]]}],
        "component_bodies": [{"outline": [[0, 0], [1, 0], [1, 1]]}],
        "regions": [{"vertices": [{"x": 0, "y": 0}]}],
    }
    out = fix_points(data)
    assert out["polygons"][0]["points"] == [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]
    assert out["polylines"][0]["points"][1] == {"x": 2, "y": 2}
    assert out["component_bodies"][0]["outline"][2] == {"x": 1, "y": 1}
    assert data["polygons"][0]["points"][0] == [0, 0]  # input untouched


def test_minimal_specs_convert():
    sym = SymbolSpec(name="EMPTY", pins=[SymPin(designator="1", x=0, y=0, orientation="up", length=0)])
    assert symbol_to_rust(sym)["pins"][0]["length"] == 0
    fp = FootprintSpec(name="DOT", pads=[Pad(designator="1", x=0, y=0, width=1, height=1, shape="circle")])
    assert footprint_to_rust(fp)["pads"][0]["shape"] == "round"
    fp.texts = [FpText(layer="top_silk", x=0, y=0, text="X", justify="top_right")]
    assert footprint_to_rust(fp)["text"][0]["layer"] == "Top Overlay"
    fp.bodies = [Body3D(outline=[Point(x=0, y=0), Point(x=1, y=0)], z_top=1)]
    with pytest.raises(RustValidationError, match="Umriss"):
        footprint_to_rust(fp)
    fp.bodies = []
    fp.step = StepModel(file="a.step")
    assert "component_bodies" not in footprint_to_rust(fp)


# --------------------------------------------------------------------------- altium-verify-2 adaptations


def test_symbols_carry_graphics_first_primitive_order():
    payload = symbol_to_rust(resistor_symbol())
    assert payload["primitive_order"] == ["rectangle", "pin", "pin", "parameter"]
    ic = symbol_to_rust(ic8_symbol())
    assert ic["primitive_order"] == ["rectangle"] + ["pin"] * 8 + ["parameter"] * 2
    opamp = symbol_to_rust(opamp_symbol())
    # spec order of the graphics is kept: polygon, label, polygon, label, rect, polyline, arc, ellipse
    assert opamp["primitive_order"][:8] == ["polygon", "label", "polygon", "label", "rectangle", "polyline", "arc", "ellipse"]
    assert opamp["primitive_order"][8:] == ["pin"] * 8 + ["parameter"]
    assert validate_symbol_payload(opamp) == []


def test_primitive_order_is_validated():
    payload = symbol_to_rust(ic8_symbol())
    bad = dict(payload, primitive_order=["round_rectangle", *payload["primitive_order"][1:]])
    assert any("primitive_order" in i and "round_rectangle" in i for i in validate_symbol_payload(bad))
    short = dict(payload, primitive_order=payload["primitive_order"][:-1])
    assert any("nennt 1× 'parameter', vorhanden sind 2" in i for i in validate_symbol_payload(short))


def test_stroke_text_anchor_compensates_bottom_left_anchoring():
    payload = footprint_to_rust(chip_0603())
    texts = {t["text"]: t for t in payload["text"]}
    designator = texts[".Designator"]
    assert designator["justification"] == "middle_center"
    assert designator["x"] == pytest.approx(-11 * 0.92 / 2) and designator["y"] == pytest.approx(-0.5)
    assert texts[".Comment"]["x"] == pytest.approx(-8 * 0.92 / 2)


@pytest.mark.parametrize("justify", ["bottom_left", "middle_center", "top_right", "bottom_center", "middle_left"])
@pytest.mark.parametrize("rotation", [0.0, 90.0, 45.0, 270.0])
def test_stroke_text_anchor_roundtrip(justify, rotation):
    from partforge.altium.rustwriter import stroke_text_anchor, stroke_text_reference

    ax, ay = stroke_text_anchor("U12", 1.5, -2.0, 0.8, rotation, justify)
    if justify == "bottom_left":
        assert (ax, ay) == (1.5, -2.0)
    x, y = stroke_text_reference("U12", ax, ay, 0.8, rotation, justify)
    assert x == pytest.approx(1.5) and y == pytest.approx(-2.0)


def test_rotated_text_anchor_direction():
    from partforge.altium.rustwriter import stroke_text_anchor

    # rotated by 90°: the text runs upwards, so centring moves the anchor down (−y) and right (+x)
    ax, ay = stroke_text_anchor("AB", 0, 0, 1.0, 90, "middle_center")
    assert ax == pytest.approx(0.5) and ay == pytest.approx(-0.92)


def test_texts_survive_conversion_roundtrip_with_anchor():
    spec = soic8()
    back = rust_to_footprint(footprint_to_rust(spec))
    for e, a in zip(spec.texts, back.texts, strict=True):
        assert (a.x, a.y, a.justify) == (pytest.approx(e.x, abs=1e-6), pytest.approx(e.y, abs=1e-6), e.justify)


def test_pcblib_strings_are_latin1():
    spec = chip_0603()
    spec.description = "Widerstand 10 kΩ ±1 % – Gehäuse 0603"
    spec.texts.append(FpText(layer="assembly", x=0, y=0, text="Ω", justify="bottom_left"))
    notes: list[str] = []
    payload = footprint_to_rust(spec, notes=notes)
    assert payload["description"] == "Widerstand 10 kOhm ±1 % - Gehäuse 0603"
    assert payload["text"][-1]["text"] == "Ohm"
    assert len(notes) == 2


# --------------------------------------------------------------------------- free text ('|', control characters)

_PIPE = "enthält das Zeichen '|'"
_CTRL = "Steuerzeichen"


def _set(obj, attr, value):
    setattr(obj, attr, value)


@pytest.mark.parametrize(
    ("mutate", "label", "kind"),
    [
        (lambda s: _set(s, "description", "Timer | 2 MHz"), "Beschreibung", _PIPE),
        (lambda s: _set(s, "description", "first|CompCount=1|LibRef1=GHOST"), "Beschreibung", _PIPE),
        (lambda s: _set(s, "description", "line1\r\nline2"), "Beschreibung", _CTRL),
        (lambda s: _set(s, "comment", "NE555|X"), "Kommentar", _PIPE),
        (lambda s: s.parameters.update({"Note": "v|IsHidden=F|Name=Evil|Text=pwned"}), "Wert", _PIPE),
        (lambda s: s.parameters.update({"Z": "x\x00y"}), "Wert", _CTRL),
        (lambda s: s.parameters.update({"Bad|Name": "1"}), "Parametername", _PIPE),
        (lambda s: s.graphics.append(SymText(x=100, y=-50, text="L|1=2")), "Text", _PIPE),
        (lambda s: s.graphics.append(SymText(x=100, y=-50, text="tab\there")), "Text", _CTRL),
        (lambda s: _set(s.pins[0], "name", "IN|A"), "Pin-Name", _PIPE),
        (lambda s: _set(s.pins[0], "designator", "2|3"), "Pin-Nummer", _PIPE),
        (lambda s: _set(s.pins[0], "description", "del\x7f"), "Pin-Beschreibung", _CTRL),
        (lambda s: _set(s.footprints[0], "description", "SOIC|8"), "Beschreibung", _PIPE),
        (lambda s: _set(s.footprints[0], "library_path", "Footprints\\A|B.PcbLib"), "Bibliothekspfad", _PIPE),
    ],
)
def test_symbol_free_text_with_separator_or_control_characters_is_rejected(mutate, label, kind):
    spec = ic8_symbol()
    mutate(spec)
    with pytest.raises(RustValidationError) as exc:
        symbol_to_rust(spec)
    message = str(exc.value)
    assert label in message and kind in message and "nichts geschrieben" in message


@pytest.mark.parametrize(
    ("mutate", "label", "kind"),
    [
        (lambda f: _set(f, "description", "Chip | 0603"), "Beschreibung", _PIPE),
        (lambda f: _set(f, "description", "x|PATTERN=EVIL|HEIGHT=99mm"), "Beschreibung", _PIPE),
        (lambda f: _set(f, "description", "d1\nd2"), "Beschreibung", _CTRL),
        (lambda f: f.texts.append(FpText(layer="assembly", x=0, y=0, text="A|B")), "Text", _PIPE),
        (lambda f: f.texts.append(FpText(layer="assembly", x=0, y=0, text="A\nB")), "Text", _CTRL),
        (lambda f: _set(f.pads[0], "designator", "1|2"), "Pad-Bezeichner", _PIPE),
        (lambda f: _set(f.bodies[0], "name", "Body|KIND=1"), "Name", _PIPE),
    ],
)
def test_footprint_free_text_with_separator_or_control_characters_is_rejected(mutate, label, kind):
    spec = chip_0603()
    mutate(spec)
    with pytest.raises(RustValidationError) as exc:
        footprint_to_rust(spec)
    assert label in str(exc.value) and kind in str(exc.value)


def test_free_text_rules_also_apply_to_replayed_payloads():
    payload = symbol_to_rust(ic8_symbol())
    payload["description"] = "a|b"
    payload["pins"][0]["name"] = "x\ny"
    payload["pins"][1]["description"] = "p|q"
    payload["parameters"][1]["value"] = "v|w"
    payload["footprints"][0]["description"] = "f|g"
    payload["designator"] = "U?|X"
    issues = "\n".join(validate_symbol_payload(payload))
    for fragment in ("Beschreibung 'a|b'", "Pin-Name", "Pin-Beschreibung", "Wert 'v|w'", "Beschreibung 'f|g'", "Bezeichner"):
        assert fragment in issues, fragment
    labels = symbol_to_rust(opamp_symbol())
    labels["labels"][0]["text"] = "A|B"
    assert any("Text 'A|B'" in i for i in validate_symbol_payload(labels))
    fp = footprint_to_rust(chip_0603())
    fp["description"] = "x|y"
    fp["pads"][0]["designator"] = "1|2"
    fp["text"][0]["text"] = "t\tt"
    fp["component_bodies"][0]["name"] = "B|1"
    issues = "\n".join(validate_footprint_payload(fp))
    for fragment in ("Beschreibung 'x|y'", "Pad-Bezeichner", "Steuerzeichen", "Name 'B|1'"):
        assert fragment in issues, fragment
    fp = footprint_to_rust(chip_0603())
    fp["description"] = 5
    assert any("Beschreibung muss Text sein" in i for i in validate_footprint_payload(fp))


def test_footprint_link_name_with_separator_is_rejected():
    spec = ic8_symbol()
    spec.footprints[0].name = "SOIC|8"
    with pytest.raises(RustValidationError, match="Footprint-Verknüpfung 'SOIC\\|8': unzulässige Zeichen"):
        symbol_to_rust(spec)
    payload = symbol_to_rust(ic8_symbol())
    payload["footprints"][0]["name"] = "A\nB"
    assert any("unzulässige Zeichen" in i for i in validate_symbol_payload(payload))


def test_free_text_allows_ordinary_unicode_and_equals_signs():
    spec = ic8_symbol()
    spec.description = "Timer 10 kΩ ±1 % (a=b; c/d) – ok"
    spec.parameters = {"Datasheet": "https://example.com/ds?a=1&b=2", "Tol": "±1 %"}
    payload = symbol_to_rust(spec)
    assert validate_symbol_payload(payload) == []


# --------------------------------------------------------------------------- read-back loss notes


def test_rust_to_symbol_reports_what_a_write_back_would_lose():
    data = {
        "name": "EXT",
        "part_count": 1,
        "display_mode_count": 2,
        "pins": [
            {"designator": "1", "name": "CLK", "x": 0, "y": 0, "length": 20, "orientation": "left", "symbol_inner_edge": "clock", "symbol_inside": "open_collector"},
            {"designator": "2", "name": "Q", "x": 40, "y": 0, "length": 20, "orientation": "right", "colour": 255, "frac": {"x": 5000, "y": 0, "length": 0}},
            {"designator": "1", "name": "CLK", "x": 0, "y": 0, "length": 20, "orientation": "left", "owner_part_display_mode": 1},
        ],
        "rectangles": [
            {"x1": 0, "y1": -10, "x2": 40, "y2": 10, "line_style": 1},
            {"x1": 0, "y1": -10, "x2": 40, "y2": 10, "owner_part_display_mode": 1},
        ],
        "polylines": [{"points": [[0, 0], [5, 5], [10, 0]], "end_line_shape": 2}],
        "elliptical_arcs": [{"x": 0, "y": 0, "radius": 2, "secondary_radius": 1}],
        "text_frames": [{"x1": 0, "y1": 0, "x2": 5, "y2": 5, "text": "frame"}],
        "images": [{"x1": 0, "y1": 0, "x2": 5, "y2": 5}],
        "labels": [{"x": 0, "y": 0, "text": "hidden", "is_hidden": True}, {"x": 0, "y": 5, "text": "big", "font_id": 3}],
        "parameters": [
            {"name": "Comment", "value": "X", "hidden": False},
            {"name": "Manufacturer", "value": "ACME", "hidden": False},
            {"name": "Note", "value": "n", "hidden": True},
        ],
    }
    notes: list[str] = []
    spec = rust_to_symbol(data, notes=notes)
    assert len(notes) == 1 and notes[0].startswith("Symbol EXT: nicht übernommen:")
    text = notes[0]
    for fragment in (
        "Pin-Symbole",
        "10-mil-Raster",
        "Pinfarben",
        "alternative Darstellungen",
        "Textrahmen (1)",
        "Bilder (1)",
        "elliptische Bögen (1)",
        "Linienstile/Pfeilspitzen (2)",
        "Schriftarten",
        "verborgene Texte",
        "sichtbare Parameter (Manufacturer)",
    ):
        assert fragment in text, fragment
    # only the normal display mode is converted (no duplicate pins / bodies)
    assert [p.designator for p in spec.pins] == ["1", "2"]
    # edge decorations with a safe ordinal are carried over, only the inside symbol is lost
    assert spec.pins[0].inner_edge == "clock" and spec.pins[0].outer_edge is None
    assert sum(1 for g in spec.graphics if g.kind == "rect") == 1
    # a symbol PartForge wrote itself converts without notes
    clean: list[str] = []
    rust_to_symbol(symbol_to_rust(ic8_symbol()) | {"designator": "U?"}, notes=clean)
    assert clean == []


def test_rust_to_footprint_reports_what_a_write_back_would_lose():
    data = {
        "name": "EXT",
        "pads": [
            {"designator": "1", "x": 0, "y": 0, "width": 1, "height": 1, "shape": "rectangle", "layer": "Multi-Layer", "hole_size": 0.5, "hole_shape": "square", "stack_mode": "top_middle_bottom"},
        ],
        "regions": [
            {"layer": "Top Layer", "kind": "cutout", "vertices": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
            {"layer": "Top Paste", "kind": "copper", "vertices": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}]},
        ],
        "text": [
            {"x": 0, "y": 0, "text": "TT", "height": 1, "layer": "Top Overlay", "kind": "true_type", "font_name": "Arial"},
            {"x": 0, "y": 0, "text": "123", "height": 1, "layer": "Top Overlay", "kind": "bar_code"},
        ],
        "component_bodies": [
            {"embedded": True, "model_id": "{A}", "model_name": "a.step", "overall_height": 1, "outline": [[0, 0], [1, 0], [1, 1]]},
            {"embedded": True, "model_id": "{B}", "model_name": "b.step", "overall_height": 1, "outline": [[0, 0], [1, 0], [1, 1]]},
        ],
    }
    notes: list[str] = []
    spec = rust_to_footprint(data, LayerMap(), notes=notes)
    assert len(spec.regions) == 1 and spec.regions[0].layer == "top_paste"  # the cutout is not a filled area
    assert spec.step is not None and spec.step.file == "a.step"
    # TrueType texts are part of the model (font and name kept); only barcodes are a loss
    assert (spec.texts[0].font, spec.texts[0].font_name) == ("truetype", "Arial")
    text = "\n".join(notes)
    for fragment in ("Pad-Stapel", "quadratische Bohrungen (1)", "Aussparungen (1)", "Barcode-Texte (1)", "weitere 3D-Modelle (1)"):
        assert fragment in text, fragment
    assert "TrueType" not in text


def test_step_source_identifies_embedded_and_linked_models():
    from partforge.altium.rustwriter import step_source

    embedded = {"component_bodies": [{"embedded": False, "model_name": ""}, {"embedded": True, "model_id": " {ID} ", "model_name": "box.step"}]}
    assert step_source(embedded) == ("{ID}", "box.step")
    linked = {"component_bodies": [{"embedded": False, "model_id": "{ID}", "model_name": "C:/x/linked.step"}]}
    assert step_source(linked) == (None, "C:/x/linked.step")
    assert step_source({"component_bodies": [{"embedded": True, "model_id": "{ID}"}]}) == ("{ID}", "model.step")
    assert step_source({"component_bodies": [{"overall_height": 1}]}) is None
    assert step_source({}) is None
