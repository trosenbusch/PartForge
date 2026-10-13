"""Footprint heights in PcbLib files (``partforge.altium.heights``) and their hook in the Rust writer.

VERIFIED defect (altium-e2e.md §6.2): every footprint the Rust writer stores has
``HEIGHT=0mil``, so Altium showed ``IPCB_LibComponent.Height = 0`` for every PartForge
footprint – and any later mutation of the library reset all heights to 0 again.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
from pathlib import Path

import pytest
from test_sync_support import build_compound, params_stream, synthetic_pcblib, toc_stream
from test_writer_samples import chip_0603, chip_with_step, header_tht, soic8, write_step

from partforge.altium import compound, heights, stackup
from partforge.altium.heights import (
    HeightError,
    coord_to_mm,
    footprint_height,
    format_mil,
    mm_to_coord,
    parse_height,
    patch_footprint_heights,
    read_footprint_heights,
)
from partforge.altium.libwriter import is_temp_library_file
from partforge.altium.rustwriter import RustLibraryOps, RustWriterError, _posix, shutdown_client
from partforge.geometry.model import Body3D, Point
from partforge.workspace import Workspace, set_current


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(text: bytes) -> bytes:
    """``u32 length`` + text + NUL (the framing of ``Parameters`` and the table of contents)."""
    return struct.pack("<I", len(text) + 1) + text + b"\x00"


def _tree(path: Path) -> dict[str, bytes | None]:
    return compound.read_tree_file(path)


def _params(path: Path) -> dict[str, bytes]:
    """``{storage: Parameters text}`` of every component."""
    out: dict[str, bytes] = {}
    for key, data in _tree(path).items():
        if data is not None and key.endswith("/Parameters"):
            (length,) = struct.unpack_from("<I", data, 0)
            assert len(data) == 4 + length and data.endswith(b"\x00")
            out[key.split("/")[0]] = data[4:-1]
    return out


def _height_value(text: bytes) -> bytes:
    return next(seg.partition(b"=")[2] for seg in text[1:].split(b"|") if seg.startswith(b"HEIGHT="))


def _toc(path: Path) -> dict[bytes, bytes]:
    data = _tree(path)["Library/ComponentParamsTOC/Data"]
    assert data is not None
    (length,) = struct.unpack_from("<I", data, 0)
    assert len(data) == 4 + length and data.endswith(b"\x00")
    out: dict[bytes, bytes] = {}
    for line in data[4:-1].split(b"\r\n"):
        if line:
            fields = dict(seg.partition(b"=")[::2] for seg in line.split(b"|"))
            out[fields[b"Name"]] = fields[b"Height"]
    return out


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    return synthetic_pcblib(tmp_path / "PF_TEST.PcbLib", heights={"RESC1608X55N": "0mil", "SOIC-8": "0mil"})


# --------------------------------------------------------------------------- units


@pytest.mark.parametrize(
    ("mm", "text"),
    [
        (0.55, "21.6535"),  # VERIFIED: Altium 26.10 wrote HEIGHT=21.6535mil / Height=21.6535
        (1.75, "68.8976"),  # VERIFIED
        (8.5, "334.6457"),  # VERIFIED (rounded, not truncated)
        (1.35, "53.1496"),  # the user's ON SEMI SOT-23-3 (user-lib-style.md §4.7)
        (2.54, "100"),
        (0.5, "19.685"),
        (0.0, "0"),
    ],
)
def test_format_matches_altium(mm: float, text: str):
    assert format_mil(mm_to_coord(mm)) == text
    assert parse_height(text + "mil") == mm_to_coord(mm)
    assert math.isclose(coord_to_mm(mm_to_coord(mm)), mm, abs_tol=2.54e-6)


def test_parse_height_variants():
    assert parse_height(b"21.6535mil") == 216535
    assert parse_height("0mil") == 0
    assert parse_height("21.6535") == 216535  # table-of-contents style (no unit)
    assert parse_height("0.55mm") == mm_to_coord(0.55)
    for bad in ("", "abc", "-1mil", "1e3mil", "12.5in"):
        assert parse_height(bad) is None, bad


@pytest.mark.parametrize("bad", [-0.1, float("nan"), float("inf"), 5000.1])
def test_invalid_heights_are_refused(bad: float):
    with pytest.raises(HeightError):
        mm_to_coord(bad)


def test_footprint_height_rule():
    spec = chip_0603()
    assert footprint_height(spec) == 0.55
    spec.height = None  # unknown: the highest 3D body (the rule of the Altium backend)
    spec.bodies.append(Body3D(outline=[Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=1)], z_bottom=0.1, z_top=0.9))
    assert footprint_height(spec) == 0.9
    spec.height = 0.0
    assert footprint_height(spec) == 0.9
    spec.bodies = []
    assert footprint_height(spec) is None


# --------------------------------------------------------------------------- patch (synthetic files)


@pytest.mark.windows
def test_patch_sets_parameters_and_table_of_contents(lib: Path):
    before = _tree(lib)
    assert patch_footprint_heights(lib, {"RESC1608X55N": 0.55, "SOIC-8": 1.75}) == []
    params = _params(lib)
    assert params["RESC1608X55N"] == (
        b"|PATTERN=RESC1608X55N|HEIGHT=21.6535mil|DESCRIPTION=Test footprint|ITEMGUID=|REVISIONGUID="
    )
    assert _height_value(params["SOIC-8"]) == b"68.8976mil"
    assert _toc(lib) == {b"RESC1608X55N": b"21.6535", b"SOIC-8": b"68.8976"}
    after = _tree(lib)
    changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
    assert changed == {"RESC1608X55N/Parameters", "SOIC-8/Parameters", "Library/ComponentParamsTOC/Data"}
    assert read_footprint_heights(lib) == pytest.approx({"RESC1608X55N": 0.55, "SOIC-8": 1.75}, abs=2.54e-6)
    assert [p.name for p in lib.parent.iterdir()] == [lib.name]  # no temporary copy left


@pytest.mark.windows
def test_patch_is_idempotent_and_ignores_unknown_names(lib: Path):
    assert patch_footprint_heights(lib, {"RESC1608X55N": 0.55}) == []
    digest = _sha(lib)
    assert patch_footprint_heights(lib, {"RESC1608X55N": 0.55}) == []
    assert patch_footprint_heights(lib, {"RESC1608X55N": 0.5499999}) == []  # same Altium coordinate
    assert patch_footprint_heights(lib, {"GIBT-ES-NICHT": 1.0}) == []
    assert _sha(lib) == digest
    assert _height_value(_params(lib)["SOIC-8"]) == b"0mil"  # not asked for: unchanged


@pytest.mark.windows
def test_patch_fixes_a_stale_table_of_contents_only(tmp_path: Path):
    path = synthetic_pcblib(tmp_path / "Stale.PcbLib", heights={"RESC1608X55N": "21.6535mil"}, toc=False)
    streams = {k: v for k, v in _tree(path).items() if v is not None}
    streams["Library/ComponentParamsTOC/Header"] = struct.pack("<I", 1)
    streams["Library/ComponentParamsTOC/Data"] = toc_stream([("RESC1608X55N", 2, "0", "x"), ("SOIC-8", 8, "0", "y")])
    path.unlink()
    build_compound(path, streams)
    assert patch_footprint_heights(path, {"RESC1608X55N": 0.55}) == []
    assert _toc(path) == {b"RESC1608X55N": b"21.6535", b"SOIC-8": b"0"}


@pytest.mark.windows
def test_without_table_of_contents_or_listing(tmp_path: Path):
    path = synthetic_pcblib(tmp_path / "NoToc.PcbLib", heights={}, toc=False)
    assert patch_footprint_heights(path, {"SOIC-8": 1.75}) == []
    assert _height_value(_params(path)["SOIC-8"]) == b"68.8976mil"
    # a table of contents that does not list the footprint: only Parameters (Altium rebuilds it on save)
    streams = {k: v for k, v in _tree(path).items() if v is not None}
    streams["Library/ComponentParamsTOC/Header"] = struct.pack("<I", 1)
    streams["Library/ComponentParamsTOC/Data"] = toc_stream([("SOIC-8", 8, "68.8976", "y")])
    path.unlink()
    build_compound(path, streams)
    assert patch_footprint_heights(path, {"RESC1608X55N": 0.55}) == []
    assert _height_value(_params(path)["RESC1608X55N"]) == b"21.6535mil"
    assert _toc(path) == {b"SOIC-8": b"68.8976"}


@pytest.mark.windows
def test_long_names_are_matched_by_pattern(tmp_path: Path):
    """Storage names are cut at 31 characters (SectionKeys); the full name lives in PATTERN."""
    name = "RESC1608X55N_YAGEO_RC0603FR-07100KL"
    storage = name[:31]
    path = build_compound(
        tmp_path / "Long.PcbLib",
        {
            "FileHeader": b"x",
            "Library/Data": b"y",
            f"{storage}/Data": b"z",
            f"{storage}/Parameters": params_stream(name),
        },
    )
    assert read_footprint_heights(path) == {name: 0.0}
    assert patch_footprint_heights(path, {name: 0.55}) == []
    assert _height_value(_params(path)[storage]) == b"21.6535mil"


@pytest.mark.parametrize(
    ("streams", "reason"),
    [
        ({"A/Parameters": _record(b"|PATTERN=A|DESCRIPTION=x")}, "HEIGHT fehlt"),
        ({"A/Parameters": params_stream("A"), "B/Parameters": params_stream("A")}, "mehrfach"),
        ({"A/Parameters": params_stream("A")[:-1]}, "Längenangabe"),
        ({"A/Parameters": params_stream("A").replace(b"|PATTERN", b"#PATTERN")}, "beginnt nicht"),
        ({"A/Parameters": _record(b"|PATTERN=A|HEIGHT=0mil|HEIGHT=1mil")}, "HEIGHT ist mehrfach"),
        ({"A/Parameters": _record(b"|PATTERN=|HEIGHT=0mil")}, "leerer PATTERN"),
        ({"A/Parameters": params_stream("A"), "Library/ComponentParamsTOC/Data": b"\x05\x00\x00\x00Name="},
         "nullterminiert"),
        ({"A/Parameters": params_stream("A"),
          "Library/ComponentParamsTOC/Data": _record(b"Name=A|Pad Count=2|Description=x\r\n")},
         "Height fehlt"),
        ({"A/Parameters": params_stream("A"),
          "Library/ComponentParamsTOC/Data": _record(b"Pad Count=2|Name=A|Height=0\r\n")},
         "ohne Name"),
        ({"A/Parameters": params_stream("A"),
          "Library/ComponentParamsTOC/Data": _record(b"Name=A|Height=0\r\nName=A|Height=0\r\n")},
         "mehrfach im Inhaltsverzeichnis"),
    ],
)
@pytest.mark.windows
def test_unexpected_structure_leaves_the_file_untouched(tmp_path: Path, streams: dict[str, bytes], reason: str | None):
    path = build_compound(tmp_path / "Odd.PcbLib", {"FileHeader": b"x", **streams})
    digest = _sha(path)
    warnings = patch_footprint_heights(path, {"A": 1.0})
    assert len(warnings) == 1 and "unerwarteter Aufbau" in warnings[0], warnings
    if reason:
        assert reason in warnings[0]
    assert _sha(path) == digest
    assert [p.name for p in path.parent.iterdir()] == [path.name]


@pytest.mark.windows
def test_invalid_values_are_reported_and_the_rest_is_written(lib: Path):
    warnings = patch_footprint_heights(lib, {"RESC1608X55N": -1.0, "SOIC-8": 1.75, "Ω-Teil": 1.0})
    assert len(warnings) == 2 and "außerhalb" in warnings[0] and "nicht zuordnen" in warnings[1]
    assert _height_value(_params(lib)["RESC1608X55N"]) == b"0mil"
    assert _height_value(_params(lib)["SOIC-8"]) == b"68.8976mil"


def test_other_files_and_missing_files(tmp_path: Path):
    assert "nur bei Footprint-Bibliotheken" in patch_footprint_heights(tmp_path / "x.SchLib", {"A": 1.0})[0]
    assert "nicht gefunden" in patch_footprint_heights(tmp_path / "missing.PcbLib", {"A": 1.0})[0]
    text_file = tmp_path / "text.PcbLib"
    text_file.write_text("kein Compound File", encoding="ascii")
    assert "nicht lesbar" in patch_footprint_heights(text_file, {"A": 1.0})[0]
    with pytest.raises(HeightError, match="nicht lesbar"):
        read_footprint_heights(text_file)
    assert patch_footprint_heights(text_file, {}) == []  # nothing asked: nothing read


@pytest.mark.windows
def test_failed_verify_or_write_leaves_the_file_untouched(lib: Path, monkeypatch):
    digest = _sha(lib)

    def reject(copy: Path) -> None:
        assert copy != lib and copy.parent == lib.parent and is_temp_library_file(copy)
        assert read_footprint_heights(copy)["RESC1608X55N"] == pytest.approx(0.55, abs=2.54e-6)
        raise RustWriterError("Rust-Reader liest die Kopie nicht")

    warnings = patch_footprint_heights(lib, {"RESC1608X55N": 0.55}, verify=reject)
    assert len(warnings) == 1 and "Rust-Reader liest die Kopie nicht" in warnings[0] and "unverändert" in warnings[0]
    assert _sha(lib) == digest and [p.name for p in lib.parent.iterdir()] == [lib.name]

    def broken(path: Path, streams) -> None:
        raise OSError("Datenträger voll")

    monkeypatch.setattr(compound, "write_streams", broken)
    warnings = patch_footprint_heights(lib, {"RESC1608X55N": 0.55})
    assert "Datenträger voll" in warnings[0] and _sha(lib) == digest
    assert [p.name for p in lib.parent.iterdir()] == [lib.name]


@pytest.mark.windows
def test_copy_check_detects_foreign_changes(lib: Path, monkeypatch):
    original = compound.write_streams

    def write_and_damage(path: Path, streams) -> None:
        original(path, {**streams, "RESC1608X55N/Data": b"kaputt"})

    monkeypatch.setattr(compound, "write_streams", write_and_damage)
    digest = _sha(lib)
    warnings = patch_footprint_heights(lib, {"SOIC-8": 1.75})
    assert "nicht identisch" in warnings[0] and "RESC1608X55N/Data" in warnings[0]
    assert _sha(lib) == digest


@pytest.mark.windows
def test_self_check_rejects_a_wrong_plan(lib: Path, monkeypatch):
    monkeypatch.setattr(heights, "format_mil", lambda coord: "1")  # a formatting bug must never reach the file
    digest = _sha(lib)
    warnings = patch_footprint_heights(lib, {"SOIC-8": 1.75})
    assert "Selbstprüfung" in warnings[0] and _sha(lib) == digest


@pytest.mark.windows
def test_layer_and_height_patches_combine(lib: Path):
    assert stackup.patch_pcblib_layers(lib, stackup.default_stack()) == []
    assert patch_footprint_heights(lib, {"RESC1608X55N": 0.55}) == []
    assert stackup.pcblib_layer_problems(lib, stackup.default_stack()) == []
    assert _height_value(_params(lib)["RESC1608X55N"]) == b"21.6535mil"


def test_switch(monkeypatch):
    monkeypatch.delenv(heights.PATCH_ENV, raising=False)
    assert heights.height_patch_enabled()
    monkeypatch.setenv(heights.PATCH_ENV, "0")
    assert not heights.height_patch_enabled()
    monkeypatch.delenv(heights.PATCH_ENV)
    monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", False)
    assert not heights.height_patch_enabled()


# --------------------------------------------------------------------------- real Rust files


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture
def rust_ws(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Bibliothek", name="Hoehen-Test")
    set_current(ws)
    try:
        yield ws
    finally:
        set_current(None)


def _footprints(ops: RustLibraryOps, lib: Path) -> list[dict]:
    return ops.client().call_tool("read_pcblib", {"filepath": _posix(lib)})["footprints"]


def _heights_of(lib: Path) -> dict[str, float]:
    return {name: round(mm, 4) for name, mm in read_footprint_heights(lib).items()}


@pytest.mark.rustwriter
def test_rust_write_sets_the_heights(rust_ws: Workspace):
    lib = rust_ws.footprints_dir / "PF_H.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    result = ops.write_library_full(lib, [chip_0603(), soic8()])
    assert result.ok and result.warnings == [], result.warnings
    assert _heights_of(lib) == {"RESC1608X55N": 0.55, "SOIC127P600X175-8N": 1.75}
    assert _toc(lib) == {b"RESC1608X55N": b"21.6535", b"SOIC127P600X175-8N": b"68.8976"}
    stack = stackup.effective_stack(stackup.default_stack(), rust_ws.settings.layers)
    assert stackup.pcblib_layer_problems(lib, stack) == []
    assert ops.list_components(lib) == ["RESC1608X55N", "SOIC127P600X175-8N"]
    assert [p.name for p in lib.parent.iterdir() if p.suffix == ".PcbLib"] == [lib.name]


@pytest.mark.rustwriter
def test_heights_survive_append_update_delete_and_full_rewrite(rust_ws: Workspace):
    """Regression: every Rust mutation resets all heights to 0 – PartForge restores them."""
    lib = rust_ws.footprints_dir / "PF_MIX.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    assert ops.upsert_footprints(lib, [chip_0603()]).ok
    assert _heights_of(lib) == {"RESC1608X55N": 0.55}
    assert ops.upsert_footprints(lib, [soic8()]).ok  # append
    assert _heights_of(lib) == {"RESC1608X55N": 0.55, "SOIC127P600X175-8N": 1.75}
    changed = soic8()
    changed.description = "geändert"
    changed.height = 1.5
    assert ops.upsert_footprints(lib, [changed]).ok  # update with a new height
    assert _heights_of(lib) == {"RESC1608X55N": 0.55, "SOIC127P600X175-8N": 1.5}
    assert ops.upsert_footprints(lib, [header_tht()]).ok
    header_height = footprint_height(header_tht())
    assert header_height is not None
    assert ops.delete_components(lib, ["SOIC127P600X175-8N"]).ok  # delete of another footprint
    assert _heights_of(lib) == {"RESC1608X55N": 0.55, "HDR_1X03_P2.54_SLOT": round(header_height, 4)}
    assert ops.write_library_full(lib, [chip_0603(), soic8()]).ok
    assert _heights_of(lib) == {"RESC1608X55N": 0.55, "SOIC127P600X175-8N": 1.75}


@pytest.mark.rustwriter
def test_a_height_saved_by_altium_survives_other_writes(rust_ws: Workspace):
    lib = rust_ws.footprints_dir / "PF_KEEP.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    unknown = chip_0603("FOREIGN_0603")
    unknown.height, unknown.bodies = None, []
    assert ops.upsert_footprints(lib, [unknown]).ok
    assert _heights_of(lib) == {"FOREIGN_0603": 0.0}
    assert patch_footprint_heights(lib, {"FOREIGN_0603": 1.0}) == []  # e.g. edited and saved in Altium
    assert ops.upsert_footprints(lib, [soic8()]).ok
    assert _heights_of(lib) == {"FOREIGN_0603": 1.0, "SOIC127P600X175-8N": 1.75}
    assert ops.upsert_footprints(lib, [unknown]).ok  # rewritten without a known height: keeps 1.0
    assert _heights_of(lib)["FOREIGN_0603"] == 1.0


@pytest.mark.rustwriter
def test_heights_with_embedded_step(rust_ws: Workspace):
    step = write_step(rust_ws.models_dir / "box.step")
    lib = rust_ws.footprints_dir / "PF_STEP.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    spec = chip_with_step(rust_ws.rel(step))
    expected = footprint_height(spec)
    assert expected is not None
    result = ops.write_library_full(lib, [spec, chip_0603()])
    assert result.ok, result.errors
    assert _heights_of(lib) == {"CAPC2012X125N": round(expected, 4), "RESC1608X55N": 0.55}
    assert ops.list_components(lib) == ["CAPC2012X125N", "RESC1608X55N"]  # carriers gone


@pytest.mark.rustwriter
def test_patched_library_reads_identically(rust_ws: Workspace, monkeypatch):
    lib = rust_ws.footprints_dir / "PF_RD.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", False)
    assert ops.write_library_full(lib, [chip_0603(), soic8()]).ok
    assert _heights_of(lib) == {"RESC1608X55N": 0.0, "SOIC127P600X175-8N": 0.0}  # switched off: Rust default
    before = json.dumps(_footprints(ops, lib), sort_keys=True)
    assert patch_footprint_heights(lib, {"RESC1608X55N": 0.55, "SOIC127P600X175-8N": 1.75}) == []
    assert json.dumps(_footprints(ops, lib), sort_keys=True) == before
    monkeypatch.setenv(heights.PATCH_ENV, "0")
    monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", True)
    other = rust_ws.footprints_dir / "PF_OFF.PcbLib"
    assert ops.write_library_full(other, [chip_0603()]).ok
    assert _heights_of(other) == {"RESC1608X55N": 0.0}


@pytest.mark.rustwriter
def test_rejected_copy_keeps_the_written_library(rust_ws: Workspace, monkeypatch):
    lib = rust_ws.footprints_dir / "PF_REJ.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    calls: list[str] = []

    def names(client, path: Path) -> list[str]:
        calls.append(path.name)
        return [path.name]  # the copy "reads" differently from the library

    monkeypatch.setattr(RustLibraryOps, "_component_names", staticmethod(names))
    result = ops.write_library_full(lib, [chip_0603()])
    assert result.ok and any("Bauhöhen nicht gesetzt" in w for w in result.warnings), result.warnings
    assert _heights_of(lib) == {"RESC1608X55N": 0.0}
    assert [p.name for p in lib.parent.iterdir() if p.suffix == ".PcbLib"] == [lib.name]
    assert calls  # the Rust reader was asked about the copy


@pytest.mark.rustwriter
def test_unreadable_heights_before_a_write_only_warn(rust_ws: Workspace, monkeypatch):
    lib = rust_ws.footprints_dir / "PF_WARN.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    assert ops.upsert_footprints(lib, [chip_0603()]).ok

    def unreadable(path) -> dict[str, float]:
        raise HeightError("PF_WARN.PcbLib: nicht lesbar (gesperrt).")

    monkeypatch.setattr(heights, "read_footprint_heights", unreadable)
    result = ops.upsert_footprints(lib, [soic8()])
    assert result.ok and any("nicht wiederhergestellt" in w for w in result.warnings), result.warnings
    monkeypatch.undo()
    # the footprints of the call still get their heights; the untouched one keeps its stream byte for byte
    # (partforge.altium.preserve sets back what the writer re-serialised) – its height is not lost any more
    assert _heights_of(lib) == {"RESC1608X55N": pytest.approx(0.55, abs=2.54e-6), "SOIC127P600X175-8N": 1.75}
