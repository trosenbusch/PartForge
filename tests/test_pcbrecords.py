"""PcbLib footprint records (``partforge.altium.pcbrecords``): lossless round trip, layers, new records, side streams."""
from __future__ import annotations

import struct
import uuid

import pytest
from records_support import PAD_RECORD, chip, footprint, pad, rect, text, track

from partforge.altium import pcbrecords as R


def approx(value: float) -> object:
    return pytest.approx(value, abs=2e-6)


# --------------------------------------------------------------------------- round trip


def test_round_trip_is_byte_identical():
    records = chip("RES0603")
    data = records.to_bytes()
    parsed = R.parse_footprint(data)
    assert parsed.name == "RES0603"
    assert parsed.to_bytes() == data
    assert [p.kind for p in parsed.primitives] == ["pad", "pad"] + ["track"] * 8 + ["text", "text"]


def test_captured_pad_record_parses_completely():
    records = R.parse_footprint(footprint("P").prefix + PAD_RECORD)
    assert len(records.primitives) == 1 and records.trailer == b""
    assert records.primitives[0].kind == "pad"
    assert records.primitives[0].to_bytes() == PAD_RECORD


def test_unknown_record_type_and_truncation_are_errors():
    prefix = footprint("X").prefix
    with pytest.raises(R.PcbRecordError, match="unbekannter Datensatztyp"):
        R.parse_footprint(prefix + b"\x09" + struct.pack("<I", 0))
    with pytest.raises(R.PcbRecordError, match="abgeschnitten"):
        R.parse_footprint(prefix + PAD_RECORD[:40])
    with pytest.raises(R.PcbRecordError):
        R.parse_footprint(b"\x01\x00")


def test_end_marker_keeps_the_rest_verbatim():
    records = footprint("X", [track("Mechanical 13", 0, 0, 1, 0)])
    data = records.to_bytes() + b"\x00garbage"
    parsed = R.parse_footprint(data)
    assert parsed.trailer == b"\x00garbage" and parsed.to_bytes() == data


# --------------------------------------------------------------------------- layers


@pytest.mark.parametrize(
    ("name", "codes"),
    [
        ("Mechanical 1", (57, 0x01020001, "MECHANICAL1")),
        ("Mechanical 16", (72, 0x01020010, "MECHANICAL16")),
        ("Mechanical 17", (72, 0x01020011, "MECHANICAL17")),  # Altium: byte 72 + V7 id
        ("Mechanical 32", (72, 0x01020020, "MECHANICAL32")),
        ("Top Overlay", (33, 0x01030006, "TOPOVERLAY")),
        ("Top Layer", (1, 0x01000001, "TOP")),
    ],
)
def test_layer_codes_follow_altium(name: str, codes: tuple[int, int, str]):
    assert R.layer_codes(name) == codes


def test_layer_codes_reject_layers_primitives_are_never_moved_to():
    with pytest.raises(R.PcbRecordError):
        R.layer_codes("Keep-Out Layer")
    with pytest.raises(R.PcbRecordError):
        R.layer_codes("Mechanical 40")


def test_layer_of_prefers_the_v7_id():
    assert R.layer_of(72, 0x01020011) == "Mechanical 17"
    assert R.layer_of(72) == "Mechanical 16"  # what readers without the V7 id see
    assert R.layer_of(186) == "Mechanical 17"  # Rust writer convention
    assert R.layer_of(0, None, "MECHANICAL13") == "Mechanical 13"
    assert R.layer_of(33, 0x01030006) == "Top Overlay"


@pytest.mark.parametrize("target", ["Mechanical 9", "Mechanical 21", "Mechanical 32", "Top Overlay"])
def test_set_layer_survives_a_round_trip(target: str):
    records = footprint("X", [track("Mechanical 13", -1, 0, 1, 0, 0.2), text("Mechanical 13", ".Designator")])
    for prim in records.primitives:
        prim.set_layer(target)
    parsed = R.parse_footprint(records.to_bytes())
    assert [p.layer for p in parsed.primitives] == [target, target]
    byte, v7, _token = R.layer_codes(target)
    assert parsed.primitives[0].blocks[0][0] == byte
    assert parsed.primitives[0]._v7() == v7


# --------------------------------------------------------------------------- tracks, pads, texts


def test_track_fields():
    prim = track("Mechanical 15", -1.45, -0.75, 1.45, -0.75, 0.05)
    assert prim.kind == "track" and prim.layer == "Mechanical 15"
    assert prim.coords == (approx(-1.45), approx(-0.75), approx(1.45), approx(-0.75))
    assert prim.width == approx(0.05)
    assert R.track_length(prim) == approx(2.9)
    prim.set_width(0.1)
    prim.set_coords(0, 0, 0, 1)
    assert prim.width == approx(0.1) and prim.coords == (0, 0, 0, approx(1.0))
    assert prim.bounds() == (approx(-0.05), approx(-0.05), approx(0.05), approx(1.05))  # incl. half the width


def test_pad_geometry_and_bounds():
    prim = pad("7", 1.0, -0.5, 0.6, 0.8)
    assert prim.pad_designator == "7"
    x, y, w, h, rotation = prim.pad_geometry
    assert (x, y, w, h, rotation) == (approx(1.0), approx(-0.5), approx(0.6), approx(0.8), 0.0)
    assert prim.pad_bounds() == (approx(0.7), approx(-0.9), approx(1.3), approx(-0.1))
    assert prim.layer == "Top Layer"


def test_new_stroke_text():
    prim = R.new_text("Mechanical 11", ".Designator", x=-1.0, y=-0.25, height=0.5, stroke_width=0.08,
                      font="stroke", font_name="Arial", box=(3.3, 0.5))
    assert prim.kind == "text" and prim.text == ".Designator"
    assert prim.layer == "Mechanical 11"
    assert prim.font_kind == "stroke"
    assert prim.height == approx(0.5) and prim.stroke_width == approx(0.08)
    assert prim.position == (approx(-1.0), approx(-0.25))
    assert prim.text_box == (approx(3.3), approx(0.5))
    assert prim.rotation == 0.0 and prim.widestring_index is None


def test_new_truetype_text_and_font_change():
    prim = R.new_text("Mechanical 19", ".Comment", x=0, y=0, height=0.8, stroke_width=0.1, font="truetype",
                      font_name="Verdana", box=(3.0, 0.7))
    assert prim.font_kind == "truetype" and prim.font_name == "Verdana"
    assert not prim.bold and not prim.italic
    prim.set_font("truetype", "Arial", bold=True)
    assert prim.font_name == "Arial" and prim.bold
    prim.set_font("stroke")
    assert prim.font_kind == "stroke"
    parsed = R.parse_footprint(footprint("X", [prim]).to_bytes()).primitives[0]
    assert parsed.font_kind == "stroke" and parsed.text == ".Comment"


def test_text_is_limited_to_255_characters():
    with pytest.raises(R.PcbRecordError, match="zu lang"):
        R.new_text("Mechanical 1", "x" * 256, x=0, y=0, height=1, stroke_width=0.1, font="stroke",
                   font_name="Arial", box=(1, 1))


def test_new_records_copy_a_template():
    template = track("Mechanical 13", 0, 0, 1, 0, 0.25)
    copy = R.new_track("Mechanical 17", -0.5, 0, 0.5, 0, 0.1, template=template)
    assert copy.layer == "Mechanical 17" and copy.width == approx(0.1)
    assert template.layer == "Mechanical 13"  # the template stays as it was


# --------------------------------------------------------------------------- side streams


def _guid_streams(records: R.FootprintRecords) -> dict[str, bytes]:
    entries = [(R.COMPONENT_GUID_KIND, 0, uuid.uuid4().bytes_le)]
    entries += [(R.GUID_KINDS[p.kind], i, uuid.uuid4().bytes_le) for i, p in enumerate(records.primitives)]
    unique = b"".join(
        struct.pack("<I", len(rec)) + rec
        for rec in (f"|PRIMITIVEINDEX={i}|PRIMITIVEOBJECTID=Track|UNIQUEID=ABCDEFGH|".encode("ascii")
                    for i, p in enumerate(records.primitives) if p.kind == "track")
    )
    return {
        "Header": R.count_stream(len(records.primitives)),
        "PrimitiveGuids/Header": R.count_stream(len(entries)),
        "PrimitiveGuids/Data": R.build_guid_stream(entries),
        "UniqueIDPrimitiveInformation/Data": unique,
    }


def test_insert_primitives_renumbers_the_side_streams():
    records = footprint("X", [pad("1", -0.5, 0), pad("2", 0.5, 0), track("Mechanical 13", -1, 0, 1, 0),
                              text("Mechanical 13", ".Designator")])
    streams = _guid_streams(records)
    old = R.guid_entries(streams["PrimitiveGuids/Data"])
    assert old is not None
    new_track = track("Mechanical 17", -0.5, 0, 0.5, 0)
    new_text = text("Mechanical 19", ".Comment")
    out = R.insert_primitives(records, [new_track, new_text], streams)

    kinds = [p.kind for p in records.primitives]
    assert kinds == ["pad", "pad", "track", "track", "text", "text"]  # behind the last record of their kind
    assert records.primitives[3] is new_track and records.primitives[5] is new_text
    assert struct.unpack("<I", out["Header"]) == (6,)
    entries = R.guid_entries(out["PrimitiveGuids/Data"])
    assert entries is not None and struct.unpack("<I", out["PrimitiveGuids/Header"]) == (7,)
    assert entries[0][0] == R.COMPONENT_GUID_KIND
    by_guid = {guid: index for _kind, index, guid in entries}
    # existing primitives keep their GUID at their new index: the text moved from 3 to 4
    assert [by_guid[guid] for _kind, _index, guid in old[1:]] == [0, 1, 2, 4]
    assert sorted(index for kind, index, _ in entries if kind != R.COMPONENT_GUID_KIND) == [0, 1, 2, 3, 4, 5]
    assert b"|PRIMITIVEINDEX=2|" in out["UniqueIDPrimitiveInformation/Data"]
    # the result is a valid footprint again
    assert R.parse_footprint(records.to_bytes()).to_bytes() == records.to_bytes()


def test_insert_without_guid_streams_only_counts():
    records = footprint("X", [pad("1", 0, 0)])
    out = R.insert_primitives(records, rect("Mechanical 15", -1, -1, 1, 1), {"Header": R.count_stream(1)})
    assert set(out) == {"Header"} and struct.unpack("<I", out["Header"]) == (5,)


def test_malformed_guid_stream_is_ignored():
    assert R.guid_entries(b"\x00" * 23) is None
    assert R.guid_entries(None) is None


# --------------------------------------------------------------------------- reader correction


def test_correct_layers_fixes_mechanical_17_to_32():
    records = footprint("X", [track("Mechanical 21", 0, 0, 1, 0), track("Mechanical 5", 0, 0, 0, 1)])
    component = {"tracks": [{"layer": "Mechanical 16"}, {"layer": "Mechanical 5"}]}
    assert R.correct_layers(component, records) == 1
    assert [t["layer"] for t in component["tracks"]] == ["Mechanical 21", "Mechanical 5"]
    # counts differ: nothing is guessed
    component = {"tracks": [{"layer": "Mechanical 16"}]}
    assert R.correct_layers(component, records) == 0


def test_angle_close():
    assert R.angle_close(0.0, 360.0) and R.angle_close(-90.0, 270.0)
    assert not R.angle_close(0.0, 1.0)
