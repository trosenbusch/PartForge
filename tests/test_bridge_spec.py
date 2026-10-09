"""Spec files the DelphiScript bridge builds SchLib/PcbLib documents from."""
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
)

from partforge.altium.bridge.spec import (
    ELECTRICAL_CODES,
    IEEE_SYMBOL_CODES,
    JUSTIFY_CODES,
    ORIENTATION_CODES,
    PAD_SHAPE_CODES,
    BridgeSpecError,
    render_pcblib_spec,
    render_schlib_spec,
)
from partforge.geometry.model import FootprintLink, FpText, SymText, TextPos
from partforge.workspace import LayerMap


def _lines(text: str) -> list[str]:
    assert text.isascii() and text.endswith("\r\n")
    return text.split("\r\n")[:-1]


def test_enum_codes_match_altium_constants():
    assert ELECTRICAL_CODES == {
        "input": 0,
        "io": 1,
        "output": 2,
        "open_collector": 3,
        "passive": 4,
        "hiz": 5,
        "open_emitter": 6,
        "power": 7,
    }
    assert ORIENTATION_CODES == {"right": 0, "up": 1, "left": 2, "down": 3}
    assert JUSTIFY_CODES["bottom_left"] == 0 and JUSTIFY_CODES["middle_center"] == 4 and JUSTIFY_CODES["top_right"] == 8
    assert PAD_SHAPE_CODES == {"circle": 1, "oval": 1, "rect": 2, "octagon": 3, "roundrect": 9}


def test_resistor_schlib_spec_exact():
    rendered = render_schlib_spec([resistor_symbol()])
    assert rendered.names == ["PF_RES"] and rendered.warnings == []
    assert _lines(rendered.text) == [
        "PFSPEC|1|SCHLIB",
        "SYMBOL|PF_RES|Widerstand, generisch (IEC)|1|R|=Value",
        "TEXTPOS|designator|-50|50|0",
        "TEXTPOS|comment|-50|-150|0",
        "RECT|1|1|0|-100|-40|100|40|16711680|16711680",
        "PIN|1|1|4|2|-100|0|1|100|0|0|0||0|0",
        "PIN|2|2|4|0|100|0|1|100|0|0|0||0|0",
        "END",
    ]


def test_text_positions_and_pin_decorations():
    spec = ic8_symbol()
    spec.designator_pos = TextPos(x=0, y=150, justify="bottom_left")
    spec.comment_pos = TextPos(x=10, y=-600, justify="top_left")
    spec.pins[0].inner_edge = "clock"
    spec.pins[3].outer_edge = "dot"
    lines = _lines(render_schlib_spec([spec]).text)
    # placement records directly after SYMBOL (the script sets them on the new component)
    assert lines[2:4] == ["TEXTPOS|designator|0|150|0", "TEXTPOS|comment|10|-600|6"]
    pins = {line.split("|")[1]: line.split("|") for line in lines if line.startswith("PIN|")}
    assert pins["2"][13:] == ["3", "0"]  # TIeeeSymbol eClock on the inner edge
    assert pins["4"][13:] == ["0", "1"]  # eDot on the outer edge
    assert pins["6"][13:] == ["0", "0"]
    assert IEEE_SYMBOL_CODES == {
        "none": 0,
        "dot": 1,
        "right_left_signal_flow": 2,
        "clock": 3,
        "active_low_input": 4,
        "analog_signal_in": 5,
        "not_logic_connection": 6,
    }


def _record_kinds(lines: list[str], symbol: str) -> list[str]:
    start = lines.index(next(line for line in lines if line.startswith(f"SYMBOL|{symbol}|")))
    kinds: list[str] = []
    for line in lines[start + 1 :]:
        kind = line.split("|", 1)[0]
        if kind in ("SYMBOL", "END"):
            break
        if kind != "TEXTPOS":  # designator/comment placement, directly after SYMBOL
            kinds.append(kind)
    return kinds


@pytest.mark.parametrize("factory", [ic8_symbol, opamp_symbol, resistor_symbol])
def test_graphics_come_before_pins_parameters_and_links(factory):
    # Altium paints records in file order: pins first would let a filled body hide the pin names
    spec = factory()
    kinds = _record_kinds(_lines(render_schlib_spec([spec]).text), spec.name)
    graphics = {"RECT", "ROUNDRECT", "LINE", "POLYLINE", "POLYGON", "ARC", "ELLIPSE", "LABEL"}
    first_pin = kinds.index("PIN")
    assert set(kinds[:first_pin]) <= graphics and len(kinds[:first_pin]) == len(spec.graphics)
    assert all(kind not in graphics for kind in kinds[first_pin:])
    rest = kinds[first_pin:]
    assert rest == sorted(rest, key=["PIN", "PARAM", "FPLINK"].index)
    # the graphics keep the order of spec.graphics
    expected = [
        {"rect": "RECT", "polygon": "POLYGON", "arc": "ARC", "ellipse": "ELLIPSE", "text": "LABEL"}.get(g.kind)
        or ("LINE" if len(g.points) == 2 else "POLYLINE")  # type: ignore[union-attr]
        for g in spec.graphics
    ]
    assert kinds[:first_pin] == expected


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda s: setattr(s, "description", "Timer | 2 MHz"), "Beschreibung"),
        (lambda s: setattr(s, "comment", "NE555|X"), "Kommentar"),
        (lambda s: s.parameters.update({"Note": "a|b"}), "Wert"),
        (lambda s: s.parameters.update({"N|x": "1"}), "Parametername"),
        (lambda s: setattr(s.pins[0], "name", "IN|A"), "Pin-Name"),
        (lambda s: setattr(s.pins[0], "description", "x\ny"), "Pin-Beschreibung"),
        (lambda s: setattr(s.footprints[0], "description", "SOIC|8"), "Beschreibung"),
        (lambda s: setattr(s.footprints[0], "library_path", "C:\\a|b.PcbLib"), "Bibliothekspfad"),
    ],
)
def test_schlib_spec_rejects_separator_and_control_characters(mutate, fragment):
    spec = ic8_symbol()
    mutate(spec)
    with pytest.raises(BridgeSpecError, match=fragment):
        render_schlib_spec([spec])


def test_pcblib_spec_rejects_separator_and_control_characters():
    spec = chip_0603()
    spec.description = "Chip | 0603"
    with pytest.raises(BridgeSpecError, match="'\\|'"):
        render_pcblib_spec([spec])
    spec = chip_0603()
    spec.texts.append(FpText(layer="assembly", x=0, y=0, text="A\tB"))
    with pytest.raises(BridgeSpecError, match="Steuerzeichen"):
        render_pcblib_spec([spec])
    spec = chip_0603()
    spec.pads[0].designator = "1|2"
    with pytest.raises(BridgeSpecError, match="Pad-Bezeichner"):
        render_pcblib_spec([spec])


def test_bridge_limitations():
    from partforge.altium.bridge.spec import bridge_limitations

    assert bridge_limitations(chip_0603()) == []
    assert bridge_limitations(resistor_symbol()) == []
    assert any("STEP" in item for item in bridge_limitations(chip_with_step("3D/box.step")))
    assert any("Pasten" in item for item in bridge_limitations(qfn16()))
    spec = resistor_symbol()
    spec.graphics.append(SymText(x=0, y=0, text="x", size=14))
    assert any("Schrift" in item for item in bridge_limitations(spec))


def test_ic_and_multipart_spec_records():
    spec = ic8_symbol()
    spec.description = "Timer – 10 kΩ ±1 %"
    spec.footprints.append(FootprintLink(name="DIP-8", library_path="C:\\Libs\\Füße.PcbLib"))
    lines = _lines(render_schlib_spec([spec, opamp_symbol()]).text)
    assert lines[1] == "SYMBOL|NE555DR|Timer - 10 kOhm %u00B11 %u0025|1|U|NE555DR"
    reset = next(line for line in lines if line.startswith("PIN|4|"))
    assert reset == "PIN|4|R\\E\\S\\E\\T\\|0|2|0|-400|1|200|1|1|0||0|0"
    assert "RECT|1|0|1|0|0|800|-500|128|11599871" in lines
    assert "PARAM|Manufacturer|Texas Instruments|1" in lines
    assert "FPLINK|SOIC127P600X175-8N||SOIC-8|1" in lines
    assert "FPLINK|DIP-8|C:\\Libs\\F%u00FC%u00DFe.PcbLib||0" in lines
    assert any(line.startswith("SYMBOL|LM358_DUAL|Dual op-amp (A, B, power)|3|U|LM358") for line in lines)
    assert "POLYGON|1|1|0|16711680|16711680|3|-200|200|-200|-200|200|0" in lines
    assert "LABEL|1|16711680|-150|150|0|4|A" in lines
    assert "POLYLINE|3|2|16711680|3|-50|0|0|50|50|0" in lines
    assert "ARC|3|1|16711680|0|0|30|0|180" in lines
    assert "ELLIPSE|3|1|0|16711680|16711680|0|-50|20|10" in lines
    assert "PIN|8|V+|7|1|0|100|3|200|1|1|0||0|0" in lines
    assert lines[-1] == "END"


def test_schlib_spec_validation():
    with pytest.raises(BridgeSpecError) as exc:
        render_schlib_spec([resistor_symbol(), resistor_symbol()])
    assert "mehrfach" in str(exc.value) and "nichts gesendet" in str(exc.value)
    bad = resistor_symbol()
    bad.name = "R_Ω"
    with pytest.raises(BridgeSpecError, match="unzulässige Zeichen"):
        render_schlib_spec([bad])
    bad = resistor_symbol()
    bad.pins[0].part = 2
    with pytest.raises(BridgeSpecError, match="Teil 2"):
        render_schlib_spec([bad])
    with pytest.raises(BridgeSpecError, match="Keine Symbole"):
        render_schlib_spec([])


def test_chip_pcblib_spec_layers_and_records():
    rendered = render_pcblib_spec([chip_0603()], layer_map=LayerMap())
    lines = _lines(rendered.text)
    assert lines[0] == "PFSPEC|1|PCBLIB"
    assert lines[1] == "FOOTPRINT|RESC1608X55N|Chip Resistor, 2-Leads, Body 1.60x0.80mm, IPC Medium Density|0.55"
    assert lines[2] == "PAD|1|-0.8|0|0|L1|9|0.9|0.95|50|0|0|0|0|1"
    tokens = {line.split("|")[1] for line in lines if line.startswith("TRACK|")}
    # default LayerMap = user's standard stack: assembly M9, centre M17, outline M21, courtyard M15
    assert tokens == {"L33", "M15", "M9", "M17", "M21"}
    # stroke text is anchored bottom-left in Altium: centred texts get a compensated anchor
    assert "TEXT|M11|-5.06|-0.5|1|0.15|0|.Designator" in lines and "TEXT|M19|-3.68|-0.5|1|0.15|0|.Comment" in lines
    assert "BODY|M13|0|0.55|8421504|1|4|-0.8|-0.4|0.8|-0.4|0.8|0.4|-0.8|0.4" in lines
    assert rendered.warnings == []


def test_tht_slot_and_npth_pads():
    lines = _lines(render_pcblib_spec([header_tht()]).text)
    pads = {line.split("|")[1]: line for line in lines if line.startswith("PAD|")}
    assert pads["1"] == "PAD|1|-2.54|0|0|L74|2|1.7|1.7|0|1|0|0|0|1"
    assert pads["3"] == "PAD|3|2.54|0|0|L74|1|1.7|3|0|1|2|2.2|90|1"
    assert pads["MH"].endswith("|L74|1|3.2|3.2|0|3.2|0|0|0|0")


def test_unsupported_features_become_warnings():
    rendered = render_pcblib_spec([qfn16()])
    assert any("Pasten" in w for w in rendered.warnings)
    lines = _lines(rendered.text)
    assert sum(1 for line in lines if line.startswith("REGION|L35|4|")) == 4
    spec = chip_with_step("3D/box.step")
    spec.bodies = []
    rendered = render_pcblib_spec([spec])
    assert any("STEP" in w for w in rendered.warnings)
    assert any(line.startswith("BODY|M13|0|1.25|") for line in _lines(rendered.text))  # synthesized from height


def test_pcblib_spec_validation():
    bad = header_tht()
    bad.pads[0].hole = None
    with pytest.raises(BridgeSpecError, match="ohne Bohrung"):
        render_pcblib_spec([bad])
    bad = chip_0603()
    bad.pads[0].hole = 0.4
    with pytest.raises(BridgeSpecError, match="Durchsteck"):
        render_pcblib_spec([bad])
    bad = chip_0603()
    bad.texts.append(FpText(layer="top_silk", x=0, y=0, text="x"))
    bad.bodies[0].z_top = 0
    with pytest.raises(BridgeSpecError, match="Oberkante"):
        render_pcblib_spec([bad])
    with pytest.raises(BridgeSpecError, match="Lagenzuordnung"):
        render_pcblib_spec([chip_0603()], layer_map=LayerMap(courtyard="Mechanical 77"))


def test_characters_above_latin1_are_always_transliterated():
    # DelphiScript's Chr wraps modulo 256 (altium-verify-2), so nothing above U+00FF may be sent
    spec = resistor_symbol()
    spec.description = "10 kΩ ±1 %"
    text = render_schlib_spec([spec]).text
    assert "10 kOhm %u00B11 %u0025" in text
    footprint = chip_0603()
    footprint.texts.append(FpText(layer="assembly", x=0, y=0, text="Ω"))
    assert "|Ohm\r\n" in render_pcblib_spec([footprint]).text
