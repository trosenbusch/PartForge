"""SchLib records (``partforge.altium.schrecords``) and the house fonts (``partforge.altium.schstyle``)."""
from __future__ import annotations

import struct

import pytest
from records_support import box_symbol, file_header, pin_record, text_record

from partforge.altium import schrecords as S
from partforge.altium import schstyle
from partforge.workspace import SymbolStyle

# --------------------------------------------------------------------------- FileHeader / fonts


def test_header_round_trip_and_font_table():
    fonts = [S.SchFont(), S.SchFont("Verdana", 10), S.SchFont("Verdana", 10, underline=True),
             S.SchFont("Arial", 8, bold=True, italic=True, rotation=90)]
    data = file_header(fonts, components=["IC1", "R_0603"])
    header = S.parse_header(data)
    assert header.to_bytes() == data
    assert header.fonts() == fonts
    assert header.get("CompCount") == "2" and header.get("libref1") == "R_0603"
    assert fonts[3].label() == "Arial 8 (fett, kursiv)"


def test_set_fonts_replaces_the_table_in_place():
    header = S.parse_header(file_header([S.SchFont()]))
    keys_before = [k for k, _ in header.pairs()]
    header.set_fonts([S.SchFont(), S.SchFont("Verdana", 12)])
    keys_after = [k for k, _ in header.pairs()]
    assert header.fonts() == [S.SchFont(), S.SchFont("Verdana", 12)]
    # the font block stays where it was, everything else keeps its order
    others = [k for k in keys_before if not k.startswith(("FontIdCount", "Size", "FontName"))]
    assert [k for k in keys_after if k in others] == others
    assert keys_after.index("FontIdCount") == keys_before.index("FontIdCount")
    with pytest.raises(S.SchRecordError):
        header.set_fonts([])


def test_header_errors():
    with pytest.raises(S.SchRecordError):
        S.parse_header(b"\x01")
    with pytest.raises(S.SchRecordError, match="nullterminiert"):
        S.parse_header(struct.pack("<I", 3) + b"|A=")


# --------------------------------------------------------------------------- records


def test_records_round_trip():
    records = box_symbol(pins=4)
    data = S.build_records(records)
    parsed = S.parse_records(data)
    assert S.build_records(parsed) == data
    assert [r.record_type for r in parsed] == ["1", "14", "2", "2", "2", "2", "34", "41", "41"]
    assert sum(r.is_pin for r in parsed) == 4
    with pytest.raises(S.SchRecordError):
        S.parse_records(data[:-3])


def test_text_record_get_and_set():
    record = text_record(RECORD=34, OwnerPartId=-1, Text="IC?", Name="Designator")
    assert record.get("Text") == "IC?" and record.get("FontID") is None
    assert record.set("Text", "U?") is True
    assert record.set("Text", "U?") is False  # unchanged
    assert record.set("FontID", "3", after=("Color", "OwnerPartId")) is True
    assert bytes(record.payload) == b"|RECORD=34|OwnerPartId=-1|FontID=3|Text=U?|Name=Designator\x00"
    assert record.set("FontID", None) is True and record.get("FontID") is None
    assert record.set("Missing", None) is False
    binary = pin_record("1", "A", x=0, y=0)
    with pytest.raises(S.SchRecordError):
        binary.set("Text", "x")
    assert binary.get("Text") is None


def test_pin_view_fields():
    record = pin_record("12", "VCC", x=-30, y=40, length=20, orientation="down", part=2, color=0x112233,
                        show_name=False)
    pin = S.PinView(record)
    assert (pin.designator, pin.name) == ("12", "VCC")
    assert pin.owner_part == 2 and pin.display_mode == 0
    assert pin.orientation == "down" and not pin.show_name and pin.show_designator and not pin.hidden
    assert pin.length == 20 and pin.location == (-30, 40) and pin.tip() == (-30, 20)
    assert pin.color == 0x112233
    pin.set_length(10)
    pin.set_color(0)
    reparsed = S.PinView(S.parse_records(record.to_bytes())[0])
    assert reparsed.length == 10 and reparsed.color == 0 and reparsed.name == "VCC"
    with pytest.raises(S.SchRecordError):
        pin.set_length(-1)
    with pytest.raises(S.SchRecordError):
        S.PinView(text_record(RECORD=34))


# --------------------------------------------------------------------------- PinTextData


def test_pin_text_data_round_trip():
    pins = {
        0: S.PinText(name=S.PinTextPart(font_id=2, color=0), designator=S.PinTextPart(font_id=2)),
        3: S.PinText(name=S.PinTextPart(margin=50000, position_flags=0x02)),
        5: S.PinText(),  # default: left out
    }
    data = S.build_pin_text_data(pins)
    assert data is not None and b"HEADER=PinTextData" in data and b"Weight=2" in data
    parsed = S.parse_pin_text_data(data)
    assert parsed == {0: pins[0], 3: pins[3]}
    assert S.build_pin_text_data({1: S.PinText()}) is None
    assert S.parse_pin_text_data(None) == {}


def test_pin_text_data_rejects_unknown_content():
    data = S.build_pin_text_data({0: S.PinText(name=S.PinTextPart(font_id=1))})
    assert data is not None
    with pytest.raises(S.SchRecordError):
        S.parse_pin_text_data(data.replace(b"HEADER=PinTextData", b"HEADER=SomethingElse"))
    with pytest.raises(S.SchRecordError):
        S.parse_pin_text_data(data[:-2])


# --------------------------------------------------------------------------- house fonts


def test_plan_font_table_keeps_existing_fonts_and_appends_the_house_font():
    style = SymbolStyle(font="Verdana", font_size=10)
    fonts, ids = schstyle.plan_font_table([S.SchFont(), S.SchFont("Arial", 8)], style)
    assert fonts[:2] == [S.SchFont(), S.SchFont("Arial", 8)]
    assert fonts[ids.text - 1] == S.SchFont("Verdana", 10)
    assert fonts[ids.link - 1] == S.SchFont("Verdana", 10, underline=True)
    assert ids.pin == ids.text
    # planning again on the result adds nothing
    again, ids_again = schstyle.plan_font_table(fonts, style)
    assert again == fonts and ids_again == ids


def test_plan_font_table_with_the_system_font_changes_nothing():
    fonts, ids = schstyle.plan_font_table([S.SchFont()], SymbolStyle())
    assert fonts == [S.SchFont()] and (ids.text, ids.link, ids.pin) == (1, 1, None)
    fonts, ids = schstyle.plan_font_table([], SymbolStyle())
    assert fonts == [schstyle.SYSTEM_FONT]


def test_plan_font_table_system_pin_font():
    _fonts, ids = schstyle.plan_font_table([S.SchFont()], SymbolStyle(font="Verdana", pin_font="system"))
    assert ids.pin is None and ids.text == 2


def test_apply_fonts_sets_texts_links_and_pins():
    records = box_symbol(pins=2)
    records.append(text_record(RECORD=41, OwnerPartId=-1, FontID=1, Text="https://example.com",
                               Name="Datasheet URL"))
    ids = schstyle.FontIds(text=2, link=3, pin=2)
    changed, pin_text = schstyle.apply_fonts(records, {}, ids, pin_color=0x000080)
    assert changed
    fonts = {r.get("Name"): r.get("FontID") for r in records if not r.binary and r.get("RECORD") in ("34", "41")}
    assert fonts == {"Designator": "2", "Comment": "2", "Manufacturer": "2", "Datasheet URL": "3"}
    assert pin_text == {i: S.PinText(name=S.PinTextPart(font_id=2, color=0x000080),
                                     designator=S.PinTextPart(font_id=2, color=0x000080)) for i in range(2)}
    # a second pass changes nothing
    changed_again, again = schstyle.apply_fonts(records, pin_text, ids, pin_color=0x000080)
    assert not changed_again and again == pin_text


def test_apply_fonts_system_pin_font_keeps_custom_positions_only():
    records = box_symbol(pins=2)
    old = {0: S.PinText(name=S.PinTextPart(font_id=5, margin=100, position_flags=0x02))}
    changed, pin_text = schstyle.apply_fonts(records, old, schstyle.FontIds(text=1, link=1, pin=None))
    assert changed
    assert pin_text == {0: S.PinText(name=S.PinTextPart(margin=100, position_flags=0x02))}
