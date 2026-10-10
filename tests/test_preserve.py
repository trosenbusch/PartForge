"""Untouched components stay byte-identical across a writer call (``partforge.altium.preserve.restore_plan``)."""
from __future__ import annotations

import struct

from records_support import chip, footprint, pad, text_record

from partforge.altium import pcbrecords as R
from partforge.altium import preserve
from partforge.altium import schrecords as S

GUID = "{0A1B2C3D-4E5F-4A6B-8C7D-9E0F1A2B3C4D}"


def _body(model_id: str) -> R.Primitive:
    props = f"V7_LAYER=MECHANICAL13|MODELID={model_id}|MODEL.EMBED=TRUE".encode("ascii") + b"\x00"
    block = bytearray(18) + struct.pack("<I", len(props)) + props
    block[0] = R.layer_codes("Mechanical 13")[0]
    return R.Primitive(R.CODE_OF["body"], [block])


def _pcblib(a: bytes, b: bytes, *, fonts: bytes = b"\x08\x00\x00\x00fontdata", models: bytes = b"") -> dict[str, bytes | None]:
    tree: dict[str, bytes | None] = {
        "FileHeader": b"PCB 6.0",
        "Library/Data": b"header",
        "Library/EmbeddedFonts": fonts,
        "A": None,
        "A/Data": a,
        "A/Header": struct.pack("<I", 3),
        "A/WideStrings": b"|ENCODEDTEXT0=46,68|",
        "B": None,
        "B/Data": b,
        "B/Header": struct.pack("<I", 3),
    }
    if models:
        tree["Library/Models/Data"] = models
    return tree


def test_untouched_footprint_and_library_streams_are_restored():
    a, b = chip("FP_A").to_bytes(), chip("FP_B").to_bytes()
    before = _pcblib(a, b)
    # the writer re-serialised everything: A lost its WideStrings and changed its Data; B was written
    after = _pcblib(a[:-4] + b"XXXX", b + b"", fonts=b"")
    del after["A/WideStrings"]
    after["B/Data"] = chip("FP_B", width=0.1).to_bytes()
    streams, skipped = preserve.restore_plan(before, after, ["fp_b"], "pcblib")
    assert skipped == []
    assert streams == {"A/Data": a, "A/WideStrings": before["A/WideStrings"],
                       "Library/EmbeddedFonts": before["Library/EmbeddedFonts"]}
    # a library stream the rewritten file does not have is not created
    del after["Library/EmbeddedFonts"]
    streams, _ = preserve.restore_plan(before, after, ["FP_B"], "pcblib")
    assert "Library/EmbeddedFonts" not in streams and "B/Data" not in streams


def test_deleted_or_renamed_components_are_not_restored():
    a, b = chip("FP_A").to_bytes(), chip("FP_B").to_bytes()
    before = _pcblib(a, b)
    after = _pcblib(chip("FP_RENAMED").to_bytes(), b)
    streams, skipped = preserve.restore_plan(before, after, [], "pcblib")
    assert streams == {} and skipped == []


def test_footprint_with_a_lost_embedded_model_stays_as_written():
    with_body = footprint("FP_A", [pad("1", 0, 0), _body(GUID)]).to_bytes()
    models = f"|ID={GUID}|NAME=body.step|".encode("ascii")
    before = _pcblib(with_body, chip("FP_B").to_bytes(), models=models)
    after = _pcblib(with_body + b"", chip("FP_B").to_bytes(), models=b"|ID={00000000-0000-0000-0000-000000000000}|")
    after["A/Data"] = footprint("FP_A", [pad("1", 0, 0)]).to_bytes()
    streams, skipped = preserve.restore_plan(before, after, ["FP_B"], "pcblib")
    assert skipped == ["A"] and "A/Data" not in streams
    # model still embedded after the write: restored
    after["Library/Models/Data"] = models
    streams, skipped = preserve.restore_plan(before, after, ["FP_B"], "pcblib")
    assert skipped == [] and streams["A/Data"] == with_body


def test_linked_models_do_not_block_the_restore():
    with_body = footprint("FP_A", [pad("1", 0, 0), _body(GUID)]).to_bytes()
    before = _pcblib(with_body, chip("FP_B").to_bytes())  # model not embedded (linked)
    after = _pcblib(footprint("FP_A", [pad("1", 0, 0)]).to_bytes(), chip("FP_B").to_bytes())
    streams, skipped = preserve.restore_plan(before, after, ["FP_B"], "pcblib")
    assert skipped == [] and streams["A/Data"] == with_body


def _symbol(name: str, *, font: int = 1) -> bytes:
    return S.build_records([text_record(RECORD=1, LibReference=name, PartCount=2),
                            text_record(RECORD=34, OwnerPartId=-1, FontID=font, Text="U?", Name="Designator")])


def test_untouched_symbols_keep_pin_text_and_images():
    before: dict[str, bytes | None] = {
        "FileHeader": b"header",
        "Storage": b"\x10\x00\x00\x00images-of-the-library",
        "U1": None, "U1/Data": _symbol("U1", font=3), "U1/PinTextData": b"pin fonts",
        "U2": None, "U2/Data": _symbol("U2", font=3),
    }
    after: dict[str, bytes | None] = {
        "FileHeader": b"header2",
        "Storage": b"\x00\x00\x00\x00",
        "U1": None, "U1/Data": _symbol("U1", font=1),
        "U2": None, "U2/Data": _symbol("U2", font=1),
    }
    streams, skipped = preserve.restore_plan(before, after, ["u2"], "schlib")
    assert skipped == []
    assert streams == {"U1/Data": before["U1/Data"], "U1/PinTextData": b"pin fonts", "Storage": before["Storage"]}


def test_component_storages_by_kind():
    tree = _pcblib(chip("FP_A").to_bytes(), b"broken")
    assert preserve.component_storages(tree, "pcblib") == {"A": "fp_a"}
    sym = {"X": None, "X/Data": _symbol("Opamp"), "FileHeader": b""}
    assert preserve.component_storages(sym, "schlib") == {"X": "opamp"}


def test_snapshot_of_a_missing_file(tmp_path):
    assert preserve.snapshot(tmp_path / "missing.PcbLib") is None
