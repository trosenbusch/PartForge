"""Writer enhancements used by the library sync: designator/Comment positions and pin
edge decorations (Rust writer conversion, read-back and the real writer round trip)."""
from __future__ import annotations

from pathlib import Path

import pytest
from test_writer_samples import ic8_symbol, resistor_symbol

from partforge.altium.rustwriter import (
    JUSTIFY_ORDINALS,
    RustLibraryOps,
    RustValidationError,
    rust_to_symbol,
    shutdown_client,
    symbol_to_rust,
    update_symbol_payload,
    validate_symbol_payload,
)
from partforge.geometry.model import TextPos
from partforge.symbols import SymbolRequest, generate
from partforge.workspace import Workspace, set_current

# --------------------------------------------------------------------------- conversion


def test_designator_and_comment_positions_are_written():
    spec = ic8_symbol()
    spec.designator_pos = TextPos(x=0, y=150)
    spec.comment_pos = TextPos(x=10, y=-620, justify="top_left")
    notes: list[str] = []
    payload = symbol_to_rust(spec, notes=notes)
    assert payload["designator_x"] == 0.0 and payload["designator_y"] == 15.0
    comment = payload["parameters"][0]
    assert comment == {
        "name": "Comment",
        "value": "NE555DR",
        "x": 1.0,
        "y": -62.0,
        "owner_part_id": -1,
        "justification": JUSTIFY_ORDINALS["top_left"],
    }
    assert notes == [] and validate_symbol_payload(payload) == []
    # update_component keeps them (designator_x/y are symbol keys)
    assert update_symbol_payload(payload)["designator_x"] == 0.0


def test_generic_symbol_gets_a_comment_placeholder_at_comment_pos():
    spec = generate(SymbolRequest(kind="resistor"))
    assert spec.comment == "*" and spec.comment_pos is not None
    payload = symbol_to_rust(spec)
    assert payload["parameters"] == [
        {"name": "Comment", "value": "*", "x": spec.comment_pos.x / 10, "y": spec.comment_pos.y / 10, "owner_part_id": -1}
    ]
    assert payload["primitive_order"][-1] == "parameter"
    assert payload["designator_x"] == spec.designator_pos.x / 10  # type: ignore[union-attr]


def test_without_positions_the_writer_defaults_apply():
    payload = symbol_to_rust(resistor_symbol())
    assert "designator_x" not in payload and "designator_y" not in payload
    assert payload["parameters"][0]["x"] == -5 and payload["parameters"][0]["y"] == -15


def test_designator_justification_is_reported():
    spec = resistor_symbol()
    spec.designator_pos = TextPos(x=0, y=100, justify="middle_center")
    notes: list[str] = []
    symbol_to_rust(spec, notes=notes)
    assert any("Ausrichtung des Bezeichners" in n for n in notes)


def test_positions_outside_the_sheet_are_rejected():
    spec = resistor_symbol()
    spec.designator_pos = TextPos(x=2_000_000, y=0)
    with pytest.raises(RustValidationError, match="Bezeichner: Position x"):
        symbol_to_rust(spec)
    payload = symbol_to_rust(resistor_symbol())
    payload["designator_x"] = "links"
    payload["parameters"][0]["justification"] = 12
    issues = validate_symbol_payload(payload)
    assert any("designator_x" in i for i in issues)
    assert any("Ausrichtung 12 ungültig" in i for i in issues)


def test_pin_edge_decorations_map_to_rust_fields():
    spec = ic8_symbol()
    spec.pins[0].inner_edge = "clock"
    spec.pins[3].outer_edge = "dot"
    spec.pins[4].inner_edge = "none"
    payload = symbol_to_rust(spec)
    by_designator = {p["designator"]: p for p in payload["pins"]}
    assert by_designator["2"]["symbol_inner_edge"] == "clock" and "symbol_outer_edge" not in by_designator["2"]
    assert by_designator["4"]["symbol_outer_edge"] == "dot"
    assert "symbol_inner_edge" not in by_designator["8"]  # "none" is not sent
    assert validate_symbol_payload(payload) == []


def test_read_back_maps_safe_decorations_and_positions():
    data = {
        "name": "X",
        "designator": "U?",
        "designator_x": -5.0,
        "designator_y": 25,
        "pins": [
            {"designator": "1", "name": "CLK", "x": 0, "y": 0, "length": 20, "orientation": "left",
             "symbol_inner_edge": "clock", "symbol_outer_edge": "dot"},
            {"designator": "2", "name": "OC", "x": 0, "y": -10, "length": 20, "orientation": "left",
             "symbol_inner_edge": "open_collector"},
            {"designator": "3", "name": "Y", "x": 0, "y": -20, "length": 20, "orientation": "left",
             "symbol_inner_edge": "none"},
        ],
        "parameters": [{"name": "Comment", "value": "*", "x": -5, "y": -15, "justification": 6}],
    }
    notes: list[str] = []
    spec = rust_to_symbol(data, notes=notes)
    assert spec.designator_pos == TextPos(x=-50, y=250)
    assert spec.comment_pos == TextPos(x=-50, y=-150, justify="top_left")
    assert spec.comment == "*"
    pins = {p.designator: p for p in spec.pins}
    assert (pins["1"].inner_edge, pins["1"].outer_edge) == ("clock", "dot")
    assert pins["2"].inner_edge is None and pins["3"].inner_edge is None
    assert len(notes) == 1 and "nicht unterstützte Kanten-Symbole an 1 Pin(s)" in notes[0]


def test_read_back_without_positions_keeps_none():
    spec = rust_to_symbol({"name": "X", "pins": [], "parameters": [{"name": "Comment", "value": "LM358"}]})
    assert spec.designator_pos is None and spec.comment_pos is None and spec.comment == "LM358"


def test_round_trip_through_conversion_is_lossless():
    spec = generate(SymbolRequest(kind="npn"))
    spec.pins[0].inner_edge = "active_low_input"
    notes: list[str] = []
    back = rust_to_symbol(symbol_to_rust(spec) | {"designator": f"{spec.designator_prefix}?"}, notes=notes)
    assert notes == []
    assert back.designator_pos == spec.designator_pos and back.comment_pos == spec.comment_pos
    assert [(p.designator, p.inner_edge, p.outer_edge) for p in back.pins] == [
        (p.designator, p.inner_edge, p.outer_edge) for p in spec.pins
    ]


# --------------------------------------------------------------------------- real writer


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.mark.rustwriter
def test_rust_writer_round_trip_of_positions_and_decorations(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Bibliothek", name="Felder")
    set_current(ws)
    try:
        ops = RustLibraryOps(workspace=ws)
        ic = ic8_symbol("TIMER")
        ic.designator_pos = TextPos(x=0, y=100)
        ic.comment_pos = TextPos(x=0, y=-600, justify="top_left")
        ic.pins[0].inner_edge = "clock"
        ic.pins[3].outer_edge = "dot"
        res = generate(SymbolRequest(kind="resistor"))
        lib = ws.symbols_dir / "PF_FIELDS.SchLib"
        result = ops.write_library_full(lib, [ic, res])
        assert result.ok, result.errors
        back = ops.read_symbol(lib, "TIMER")
        assert back is not None
        assert back.designator_pos == TextPos(x=0, y=100)
        assert back.comment_pos == TextPos(x=0, y=-600, justify="top_left")
        pins = {p.designator: p for p in back.pins}
        assert pins["2"].inner_edge == "clock" and pins["4"].outer_edge == "dot"
        back_res = ops.read_symbol(lib, res.name)
        assert back_res is not None and back_res.comment == "*"
        assert back_res.comment_pos == res.comment_pos and back_res.designator_pos == res.designator_pos
        # upsert path (update_component) keeps the fields as well
        ic.designator_pos = TextPos(x=100, y=200)
        assert ops.upsert_symbols(lib, [ic]).ok
        again = ops.read_symbol(lib, "TIMER")
        assert again is not None and again.designator_pos == TextPos(x=100, y=200)
        assert {p.designator: p.inner_edge for p in again.pins}["2"] == "clock"
    finally:
        set_current(None)
