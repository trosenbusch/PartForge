"""House-style rules (``partforge.altium.conform``): layer roles of foreign libraries and the plans per footprint /
symbol – pure functions on synthetic records."""
from __future__ import annotations

import pytest
from records_support import box_symbol, chip, footprint, pad, rect, text, text_record, track

from partforge.altium import conform as C
from partforge.altium import pcbrecords as R
from partforge.altium import schrecords as S
from partforge.altium import schstyle
from partforge.altium.stackup import MechLayer
from partforge.workspace import FootprintStyle, LayerMap, SymbolStyle

HOUSE = FootprintStyle(text_font="truetype", text_font_name="Arial", text_height=0.8, center_cross=False)
LAYERS = LayerMap()  # assembly 9, designator 11, body3d 13, courtyard 15, center 17, comment 19, outline 21


def approx(value: float) -> object:
    return pytest.approx(value, abs=2e-6)


def roles_of(*footprints: R.FootprintRecords, header: dict[int, MechLayer] | None = None,
             manual: dict[str, str] | None = None) -> dict[str, tuple[str, str]]:
    found = C.infer_layer_roles(footprints, header, manual)
    return {layer: (r.role, r.reason) for layer, r in found.items()}


# --------------------------------------------------------------------------- rules


def test_parse_prefix_map():
    assert C.parse_prefix_map("IC=U, tr = q; X=X\nR?=R, 1=2, =U, LONGPREFIX=U") == {"IC": "U", "TR": "Q"}
    assert C.parse_prefix_map("") == {}


def test_rules_defaults():
    rules = C.ConformRules()
    assert rules.symbols.prefix_map == {"IC": "U"} and not rules.symbols.colors
    assert rules.footprints.layers and not rules.footprints.silk_width and rules.footprints.roles == {}


# --------------------------------------------------------------------------- roles


def test_roles_from_content_outer_outline_is_the_courtyard():
    found = roles_of(chip("A"), chip("B"))
    assert found == {"Mechanical 13": ("assembly", "content"), "Mechanical 15": ("courtyard", "content")}


def test_roles_from_header_kind_win_over_content():
    header = {13: MechLayer(number=13, name="Top 3D Body", kind="3DBodyTop")}
    assert roles_of(chip("A"), header=header)["Mechanical 13"] == ("body3d", "kind")


def test_roles_from_layer_names():
    header = {13: MechLayer(number=13, name="Assembly Top", kind=None),
              15: MechLayer(number=15, name="Courtyard Bottom", kind=None)}
    found = roles_of(chip("A"), header=header)
    assert found["Mechanical 13"] == ("assembly", "name")
    assert found["Mechanical 15"] == ("courtyard", "content")  # "bottom" names are no evidence


def test_manual_roles_win():
    found = roles_of(chip("A"), manual={"Mechanical 15": "keep", "Mechanical 13": "component_outline"})
    assert found == {"Mechanical 13": ("component_outline", "manual"), "Mechanical 15": ("keep", "manual")}


def test_layer_without_evidence_stays_unchanged():
    lonely = footprint("X", [pad("1", 0, 0), track("Mechanical 3", 5, 5, 6, 5)])
    assert roles_of(lonely)["Mechanical 3"] == ("assembly", "content")
    only_texts = footprint("Y", [pad("1", 0, 0), text("Mechanical 4", ".Designator")])
    assert roles_of(only_texts)["Mechanical 4"] == ("keep", "default")


def test_primitive_roles_cross_texts_overlay_and_pads():
    records = footprint("X", [
        pad("1", -0.75, 0), pad("2", 0.75, 0),
        track("Mechanical 13", -0.5, 0, 0.5, 0), track("Mechanical 13", 0, -0.5, 0, 0.5),  # centre cross
        *rect("Mechanical 13", -0.8, -0.4, 0.8, 0.4),
        track("Top Overlay", -0.2, 0.6, 0.2, 0.6),
        text("Mechanical 2", ".Designator"), text("Mechanical 2", ".Comment"), text("Mechanical 2", "free text"),
    ])
    layer_roles = C.infer_layer_roles([records])
    roles = C.primitive_roles(records, layer_roles)
    assert roles[:2] == [None, None]
    assert roles[2:4] == ["component_center", "component_center"]
    assert roles[4:8] == ["assembly"] * 4
    assert roles[8] == "silkscreen"
    assert roles[9:11] == ["designator", "comment"]
    assert roles[11] is None  # free text on a layer without a role stays


# --------------------------------------------------------------------------- footprint plan


def _apply(plan: C.FootprintPlan) -> R.FootprintRecords:
    records = plan.records
    R.insert_primitives(records, plan.new, {})
    return records


def test_plan_footprint_moves_restyles_and_completes():
    source = chip("RES0603")
    before = source.to_bytes()
    plan = C.plan_footprint(source, C.infer_layer_roles([source]), C.FootprintRules(), HOUSE, LAYERS)
    assert source.to_bytes() == before  # pure
    assert plan.modified
    rules = {c.rule for c in plan.changes}
    assert rules == {"layers", "widths", "texts", "add_center"}

    result = _apply(plan)
    tracks = result.of_kind("track")
    assert sorted({t.layer for t in tracks}) == ["Mechanical 15", "Mechanical 17", "Mechanical 9"]
    assembly = [t for t in tracks if t.layer == "Mechanical 9"]
    courtyard = [t for t in tracks if t.layer == "Mechanical 15"]
    cross = [t for t in tracks if t.layer == "Mechanical 17"]
    assert len(assembly) == 4 and all(t.width == approx(HOUSE.assembly_width) for t in assembly)
    assert len(courtyard) == 4 and all(t.width == approx(HOUSE.courtyard_width) for t in courtyard)
    assert [t.coords for t in cross] == [(approx(-0.5), 0, approx(0.5), 0), (0, approx(-0.5), 0, approx(0.5))]
    texts = {t.text: t for t in result.of_kind("text")}
    assert texts[".Designator"].layer == "Mechanical 11" and texts[".Comment"].layer == "Mechanical 19"
    for t in texts.values():
        assert t.font_kind == "truetype" and t.font_name == "Arial" and t.height == approx(0.8)
        x, y = C._text_center(t)  # stays centred where it was
        assert (x, y) == (pytest.approx(0, abs=0.01), pytest.approx(0, abs=0.01))
    assert [p.pad_geometry[:2] for p in result.of_kind("pad")] == [(approx(-0.75), 0), (approx(0.75), 0)]


def test_plan_footprint_is_idempotent():
    first = C.plan_footprint(chip("A"), C.infer_layer_roles([chip("A")]), C.FootprintRules(), HOUSE, LAYERS)
    converted = _apply(first)
    again = C.plan_footprint(converted, C.infer_layer_roles([converted]), C.FootprintRules(), HOUSE, LAYERS)
    assert not again.modified, [c.message for c in again.changes]


def test_plan_footprint_adds_missing_texts():
    source = chip("A", texts_on=None)
    plan = C.plan_footprint(source, C.infer_layer_roles([source]), C.FootprintRules(), HOUSE, LAYERS)
    added = {p.text: p for p in plan.new if p.kind == "text"}
    assert set(added) == {".Designator", ".Comment"}
    assert added[".Designator"].layer == "Mechanical 11" and added[".Comment"].layer == "Mechanical 19"
    assert all(p.font_kind == "truetype" and p.height == approx(0.8) for p in added.values())
    assert any(c.rule == "add_texts" for c in plan.changes)


def test_plan_footprint_with_every_rule_off_changes_nothing():
    rules = C.FootprintRules(layers=False, widths=False, texts=False, add_texts=False, add_center=False)
    source = chip("A")
    plan = C.plan_footprint(source, C.infer_layer_roles([source]), rules, HOUSE, LAYERS)
    assert not plan.modified and not plan.new and plan.records.to_bytes() == source.to_bytes()


def test_plan_footprint_keeps_silkscreen_width_unless_asked():
    source = footprint("X", [pad("1", 0, 0), track("Top Overlay", -1, 1, 1, 1, 0.12)])
    layer_roles = C.infer_layer_roles([source])
    plan = C.plan_footprint(source, layer_roles, C.FootprintRules(add_texts=False, add_center=False), HOUSE, LAYERS)
    assert not plan.modified
    plan = C.plan_footprint(source, layer_roles, C.FootprintRules(add_texts=False, add_center=False, silk_width=True),
                            HOUSE, LAYERS)
    silk = plan.records.of_kind("track")[0]
    assert silk.layer == "Top Overlay" and silk.width == approx(HOUSE.silk_width)


def test_text_height_and_cross_scale_down_for_tiny_parts():
    tiny = (-0.3, -0.15, 0.3, 0.15)
    assert C.text_height_for(tiny, HOUSE) == pytest.approx(0.3)
    assert C.text_height_for(None, HOUSE) == pytest.approx(0.8)
    assert C.center_cross_half(tiny) == pytest.approx(0.18)
    assert C.center_cross_half(None) == pytest.approx(0.5)


# --------------------------------------------------------------------------- symbols


def _pins(records: list[S.SchRecord]) -> list[S.PinView]:
    return [S.PinView(r) for r in records if r.is_pin]


def test_box_symbol_detection():
    assert C.is_box_symbol(box_symbol())
    no_body = [r for r in box_symbol() if r.binary or r.get("RECORD") != "14"]
    assert not C.is_box_symbol(no_body)


def test_plan_symbol_fonts_pin_length_prefix():
    style = SymbolStyle(font="Verdana", ic_pin_length=100)
    source = box_symbol(pins=4, length=20)
    fonts, ids = schstyle.plan_font_table([S.SchFont()], style)
    assert len(fonts) == 3
    plan = C.plan_symbol("IC1", source, {}, C.SymbolRules(), style, ids)
    assert {c.rule for c in plan.changes} == {"fonts", "pin_length", "prefix"}
    assert [p.length for p in _pins(source)] == [20] * 4  # pure
    assert [p.length for p in _pins(plan.records)] == [10] * 4
    assert plan.pin_lengths == {0: 10, 1: 10, 2: 10, 3: 10}
    designator = next(r for r in plan.records if not r.binary and r.get("RECORD") == "34")
    assert designator.get("Text") == "U?" and designator.get("FontID") == str(ids.text) and plan.prefix == "U"
    assert set(plan.pin_text) == {0, 1, 2, 3} and plan.pin_text_changed
    assert next(c for c in plan.changes if c.rule == "pin_length").message == "4 Pins 200 mil → 100 mil"

    again = C.plan_symbol("IC1", plan.records, plan.pin_text, C.SymbolRules(), style, ids)
    assert not again.modified, [c.message for c in again.changes]


def test_plan_symbol_leaves_discrete_symbols_pin_lengths():
    style = SymbolStyle(ic_pin_length=100)
    resistor = [
        text_record(RECORD=1, LibReference="R", PartCount=2),
        S.SchRecord(*_two_pins()[0]), S.SchRecord(*_two_pins()[1]),
        text_record(RECORD=34, OwnerPartId=-1, Text="R?", Name="Designator"),
    ]
    plan = C.plan_symbol("R", resistor, {}, C.SymbolRules(fonts=False), style, None)
    assert not plan.modified


def _two_pins() -> list[tuple[bool, bytearray, int]]:
    from records_support import pin_record

    return [(r.binary, r.payload, r.flags) for r in (pin_record("1", "1", x=0, y=0, length=30, orientation="left"),
                                                     pin_record("2", "2", x=10, y=0, length=30, orientation="right"))]


def test_plan_symbol_colors_only_when_asked():
    style = SymbolStyle(ic_line_color="#800000", ic_fill_color="#FFFFB0", pin_color="#000080")
    source = box_symbol(pins=2, pin_color=0)
    plan = C.plan_symbol("IC1", source, {}, C.SymbolRules(fonts=False, prefix=False, pin_length=False), style, None)
    assert not plan.modified
    plan = C.plan_symbol("IC1", source, {}, C.SymbolRules(fonts=False, prefix=False, pin_length=False, colors=True),
                         style, None)
    rect_record = next(r for r in plan.records if not r.binary and r.get("RECORD") == "14")
    assert rect_record.get("Color") == str(0x000080) and rect_record.get("AreaColor") == str(0xB0FFFF)
    assert all(p.color == 0x800000 for p in _pins(plan.records))


def test_plan_symbol_prefix_map_is_case_insensitive_and_optional():
    source = box_symbol(prefix="ic?")
    plan = C.plan_symbol("IC1", source, {}, C.SymbolRules(fonts=False, pin_length=False), SymbolStyle(), None)
    assert plan.prefix == "U"
    plan = C.plan_symbol("IC1", source, {}, C.SymbolRules(fonts=False, pin_length=False, prefix=False), SymbolStyle(),
                         None)
    assert plan.prefix is None and not plan.modified


# --------------------------------------------------------------------------- crosses


def _with_crosses(*layers: str) -> R.FootprintRecords:
    prims: list[R.Primitive] = [pad("1", -0.75, 0), pad("2", 0.75, 0)]
    prims += rect("Mechanical 13", -0.8, -0.4, 0.8, 0.4)
    prims += rect("Mechanical 15", -1.45, -0.75, 1.45, 0.75, 0.05)
    for layer in layers:
        prims += [track(layer, -0.5, 0, 0.5, 0), track(layer, 0, -0.5, 0, 0.5)]
    return footprint("X", prims)


def test_courtyard_cross_and_centre_cross_are_told_apart():
    records = _with_crosses("Mechanical 15", "Mechanical 13")  # PartForge style: courtyard cross + centre
    layer_roles = C.infer_layer_roles([records])
    assert {k: v.role for k, v in layer_roles.items()} == {"Mechanical 13": "assembly", "Mechanical 15": "courtyard"}
    center, court = C.center_crosses(records.primitives, layer_roles)
    assert [records.primitives[i].layer for i in center] == ["Mechanical 13"] * 2
    assert [records.primitives[i].layer for i in court] == ["Mechanical 15"] * 2
    plan = C.plan_footprint(records, layer_roles, C.FootprintRules(add_texts=False), HOUSE, LAYERS)
    tracks = plan.records.of_kind("track")
    crosses = [t for t in tracks if R.track_length(t) == approx(1.0)]
    assert sorted(t.layer for t in crosses) == ["Mechanical 15"] * 2 + ["Mechanical 17"] * 2
    assert all(t.width == approx(C.CROSS_WIDTH) for t in crosses)
    assert not any(c.rule == "add_center" for c in plan.changes)


def test_lone_courtyard_cross_depends_on_the_house_style():
    records = _with_crosses("Mechanical 15")
    layer_roles = C.infer_layer_roles([records])
    # house style without courtyard cross: the lone cross is the centre, drawn on the wrong layer
    no_cross = HOUSE.model_copy(update={"center_cross": False})
    plan = C.plan_footprint(records, layer_roles, C.FootprintRules(add_texts=False), no_cross, LAYERS)
    assert sorted(t.layer for t in plan.records.of_kind("track") if R.track_length(t) == approx(1.0)) == \
        ["Mechanical 17"] * 2
    assert not plan.new
    # house style with courtyard cross: it stays, the centre cross is added
    with_cross = HOUSE.model_copy(update={"center_cross": True})
    plan = C.plan_footprint(records, layer_roles, C.FootprintRules(add_texts=False), with_cross, LAYERS)
    assert sorted(t.layer for t in plan.records.of_kind("track") if R.track_length(t) == approx(1.0)) == \
        ["Mechanical 15"] * 2
    assert [t.layer for t in plan.new] == ["Mechanical 17"] * 2


# --------------------------------------------------------------------------- layer types the library declares


def _vendor_header() -> dict[int, MechLayer]:
    """Header of a vendor library with its own scheme (like an Altium IPC-wizard library)."""
    return {
        2: MechLayer(number=2, name="Fab Notes", kind="FabNotes"),
        5: MechLayer(number=5, name="Top Assembly", kind="AssemblyTop"),
        7: MechLayer(number=7, name="Top Value", kind="ValueTop"),
        9: MechLayer(number=9, name="Top Designator", kind="DesignatorTop"),
        11: MechLayer(number=11, name="Top Dimensions", kind="DimensionsTop"),
        15: MechLayer(number=15, name="Top Courtyard", kind="CourtyardTop"),
        18: MechLayer(number=18, name="Bottom Component Center", kind="ComponentCenterBottom"),
        20: MechLayer(number=20, name="Bottom Component Outline", kind="ComponentOutlineBottom"),
    }


def _vendor_footprint(name: str = "CONN") -> R.FootprintRecords:
    return footprint(name, [
        pad("1", -1.25, 0, 1.0, 1.5), pad("2", 1.25, 0, 1.0, 1.5),
        *rect("Mechanical 5", -2.0, -1.5, 2.0, 1.5),                      # assembly drawing
        *rect("Mechanical 15", -2.5, -2.0, 2.5, 2.0, 0.05),               # courtyard
        *rect("Mechanical 11", -3.0, -2.5, 3.0, 2.5),                     # dimensions (bigger than everything)
        *rect("Mechanical 20", -2.6, -2.1, 2.6, 2.1),                     # bottom outline
        track("Mechanical 9", -0.4, 1.0, 0.4, 1.0),                       # graphics on the designator layer
        R.new_track("Mechanical 9", 0, 0.8, 0.2, 1.2, 0.1),
        track("Mechanical 18", -0.5, 0, 0.5, 0), track("Mechanical 18", 0, -0.5, 0, 0.5),  # bottom centre cross
        text("Mechanical 9", ".Designator", height=1.0),
        text("Mechanical 7", ".Comment", height=1.0),
        text("Mechanical 2", ".Designator", height=1.5),                  # fab notes keep their own
    ])


def test_declared_layer_types_without_a_house_role_stay():
    found = roles_of(_vendor_footprint(), header=_vendor_header())
    assert found["Mechanical 2"] == ("keep", "kind")
    assert found["Mechanical 11"] == ("keep", "kind")      # dimensions – content alone would say "courtyard"
    assert found["Mechanical 18"] == ("keep", "kind")
    assert found["Mechanical 20"] == ("keep", "kind")      # bottom side
    assert found["Mechanical 5"] == ("assembly", "kind") and found["Mechanical 9"] == ("designator", "kind")


def test_names_of_note_and_dimension_layers_are_no_roles():
    header = {2: MechLayer(number=2, name="Fab Notes", kind=None), 3: MechLayer(number=3, name="Assembly Notes", kind=None),
              11: MechLayer(number=11, name="Top Dimensions", kind=None)}
    records = footprint("X", [pad("1", 0, 0), *rect("Mechanical 2", -1, -1, 1, 1), *rect("Mechanical 3", -2, -2, 2, 2),
                              *rect("Mechanical 11", -3, -3, 3, 3)])
    found = C.infer_layer_roles([records], header)
    assert set(found) == {"Mechanical 2", "Mechanical 3", "Mechanical 11"}
    assert all(role.reason != "name" for role in found.values())  # "Fab Notes" is no fabrication drawing


def test_vendor_footprint_converts_without_touching_declared_layers():
    records = _vendor_footprint()
    layer_roles = C.infer_layer_roles([records], _vendor_header())
    plan = C.plan_footprint(records, layer_roles, C.FootprintRules(), HOUSE, LAYERS)  # graphics on Mech 9: no crash
    result = _apply(plan)
    by_layer: dict[str, list[R.Primitive]] = {}
    for prim in result.primitives:
        by_layer.setdefault(prim.layer or "", []).append(prim)
    # the designator layer's graphics and text move to the house designator layer; only the text is restyled
    assert sorted(p.kind for p in by_layer["Mechanical 11"]) == ["text"] + ["track"] * 6  # 4 dimension tracks stay too
    designator = next(p for p in by_layer["Mechanical 11"] if p.kind == "text")
    assert designator.text == ".Designator" and designator.font_kind == "truetype" and designator.height == approx(0.8)
    assert next(p for p in by_layer["Mechanical 19"] if p.kind == "text").text == ".Comment"
    # fab notes, dimensions, bottom layers: untouched (the fab notes' .Designator keeps its style)
    fab = next(p for p in by_layer["Mechanical 2"] if p.kind == "text")
    assert fab.font_kind == "stroke" and fab.height == approx(1.5)
    assert len(by_layer["Mechanical 18"]) == 2 and len(by_layer["Mechanical 20"]) == 4
    # the bottom centre cross is no top centre: the house centre cross is added
    assert [t.layer for t in plan.new if t.kind == "track"] == ["Mechanical 17", "Mechanical 17"]


def test_without_a_designator_layer_every_designator_is_the_designator():
    header = {5: MechLayer(number=5, name="Top Assembly", kind="AssemblyTop")}
    records = footprint("X", [pad("1", 0, 0), *rect("Mechanical 5", -1, -1, 1, 1), text("Mechanical 5", ".Designator")])
    layer_roles = C.infer_layer_roles([records], header)
    roles = C.primitive_roles(records, layer_roles)
    assert roles[-1] == "designator"


def test_declared_layers_move_to_the_house_layer_of_the_same_type():
    kind_layers = {"DimensionsTop": "Mechanical 23", "ComponentOutlineBottom": "Mechanical 22",
                   "ComponentCenterBottom": "Mechanical 18", "AssemblyTop": "Mechanical 9"}
    role_layers = {"Mechanical 9": "Bestückungszeichnung", "Mechanical 11": "Bezeichner"}
    records = _vendor_footprint()
    layer_roles = C.infer_layer_roles([records], _vendor_header(), kind_layers=kind_layers, role_layers=role_layers)
    assert (layer_roles["Mechanical 11"].target, layer_roles["Mechanical 20"].target) == ("Mechanical 23", "Mechanical 22")
    assert layer_roles["Mechanical 18"].target is None  # same number in the house stack: stays
    assert layer_roles["Mechanical 11"].note == "wandert nach Mechanical 23 (gleicher Lagentyp DimensionsTop)"
    assert layer_roles["Mechanical 2"].note is None and layer_roles["Mechanical 2"].kind == "FabNotes"
    plan = C.plan_footprint(records, layer_roles, C.FootprintRules(), HOUSE, LAYERS)
    layers = [p.layer for p in _apply(plan).primitives]
    assert layers.count("Mechanical 23") == 4 and layers.count("Mechanical 22") == 4 and layers.count("Mechanical 20") == 0
    assert "Top Dimensions: Mechanical 11 → Mechanical 23 (4)" in [c.message for c in plan.changes]
    # rule off: nothing moves
    off = C.plan_footprint(records, layer_roles, C.FootprintRules(layers=False), HOUSE, LAYERS)
    assert "Mechanical 23" not in [p.layer for p in _apply(off).primitives]


def test_kept_layer_on_a_house_role_layer_gets_a_note():
    header = {9: MechLayer(number=9, name="User Notes", kind="UserNotesX")}
    records = footprint("X", [pad("1", 0, 0), track("Mechanical 9", 5, 5, 6, 5)])
    found = C.infer_layer_roles([records], header, kind_layers={}, role_layers={"Mechanical 9": "Bestückungszeichnung"})
    assert found["Mechanical 9"].role == "keep" and found["Mechanical 9"].target is None
    assert found["Mechanical 9"].note == "bleibt – im Hausstil ist Mechanical 9 die Lage „Bestückungszeichnung“"
