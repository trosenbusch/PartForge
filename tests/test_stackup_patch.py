"""PcbLib layer header patch (``stackup.patch_pcblib_layers``) and its hook in the Rust writer."""
from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest
from test_sync_support import (
    NATIVE_KIND_MAPPING,
    RUST_KINDS,
    library_data,
    rust_like_header,
    synthetic_pcblib,
)
from test_writer_samples import chip_0603, chip_with_step, soic8, write_step

from partforge.altium import stackup
from partforge.altium.rustwriter import RustLibraryOps, RustWriterError, _posix, shutdown_client
from partforge.altium.stackup import (
    LayerStack,
    MechLayer,
    default_stack,
    patch_pcblib_layers,
    pcblib_layer_problems,
    read_library_data,
    read_pcblib_layers,
)
from partforge.workspace import LayerMap, Workspace, set_current


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(path: Path) -> bytes:
    data = read_library_data(path)
    (length,) = struct.unpack_from("<I", data, 0)
    return data[4 : 4 + length - 1]


def _keys(text: bytes) -> dict[bytes, bytes]:
    out: dict[bytes, bytes] = {}
    for seg in text[1:].split(b"|"):
        key, _, value = seg.partition(b"=")
        out.setdefault(key, value.rstrip(b"\r"))
    return out


def _tree(path: Path) -> dict[str, bytes | None]:
    return stackup._read_tree_file(path)


@pytest.fixture
def lib(tmp_path: Path) -> Path:
    return synthetic_pcblib(tmp_path / "PF_TEST.PcbLib")


# --------------------------------------------------------------------------- structure


def test_patch_sets_every_representation(lib: Path):
    stack = default_stack()
    assert pcblib_layer_problems(lib, stack)  # Rust template: Mech 2-7 typed
    before = _tree(lib)
    assert patch_pcblib_layers(lib, stack) == []
    assert pcblib_layer_problems(lib, stack) == []
    keys = _keys(_text(lib))
    # Mechanical 9: V9 cache (77), V8 stack (19) and legacy (65) carry name, enabled flag and kind
    for prefix in (b"V9_CACHE_LAYER77_", b"LAYER_V8_19", b"LAYER65"):
        assert keys[prefix + b"NAME"] == b"Top Assembly"
        assert keys[prefix + b"MECHENABLED"] == b"TRUE"
        assert keys[prefix + b"MECHKIND"] == b"AssemblyTop"
    # Mechanical 17 (component centre) also in the V7 representation
    for prefix in (b"V9_CACHE_LAYER86_", b"LAYER_V8_40", b"LAYERV7_0"):
        assert keys[prefix + b"NAME"] == b"Top Component Center"
        assert keys[prefix + b"MECHKIND"] == b"ComponentCenterTop"
    # the Rust writer's typed Mech 2-7 are replaced (Mech 4 has no kind in the standard)
    assert keys[b"LAYER_V8_14NAME"] == b"Hole Detail" and b"LAYER_V8_14MECHKIND" not in keys
    assert keys[b"V9_CACHE_LAYER70_MECHKIND"] == b"RouteToolPath"
    assert keys[b"LAYER_V8_55MECHENABLED"] == b"FALSE"  # Mechanical 32 stays disabled
    layers = read_pcblib_layers(lib)
    assert {n: (layer.name, layer.kind, layer.enabled) for n, layer in layers.items()} == {
        n: (layer.name, layer.kind, layer.enabled) for n, layer in default_stack().header_layers().items()
    }
    # every other stream (footprints, file header, kind mapping) is byte-identical
    after = _tree(lib)
    assert {k: v for k, v in after.items() if k != "Library/Data"} == {
        k: v for k, v in before.items() if k != "Library/Data"
    }


def test_patch_pairs_layer_sets_and_record_breaks(lib: Path):
    original = _text(lib)
    patch_pcblib_layers(lib, default_stack())
    text = _text(lib)
    keys = _keys(text)
    pairs = [(keys[f"MECHPAIR{i}L1".encode()], keys[f"MECHPAIR{i}L2".encode()]) for i in range(11)]
    assert pairs[:3] == [(b"MECHANICAL15", b"MECHANICAL16"), (b"MECHANICAL13", b"MECHANICAL14"), (b"MECHANICAL9", b"MECHANICAL10")]
    assert b"MECHPAIR11L1" not in keys  # Mechanical 49/50 are not representable
    assert b"MECHANICAL30\r|RECORD=Board" in text  # the record break moved behind the new last pair
    mech = [f"Mechanical{n}".encode() for n in range(1, 32)]  # the standard enables Mech 1-31
    assert keys[b"LAYERSET5LAYERS"].split(b",") == mech  # every enabled layer, numeric order
    all_set = keys[b"LAYERSET1LAYERS"].split(b",")
    # native order (Altium example PCB1.PcbLib): Mech 1-16 before DrillDrawing, Mech 17-32 after it
    assert all_set == [b"MultiLayer", b"TopLayer", b"BottomLayer", b"KeepOutLayer", *mech[:16], b"DrillDrawing", *mech[16:]]
    assert keys[b"LAYERSET2LAYERS"] == b"MultiLayer,TopLayer,BottomLayer"
    assert original.count(b"\r") == text.count(b"\r")


def test_layer_sets_follow_enabled_high_layers(lib: Path):
    stack = LayerStack(
        layers={
            9: MechLayer(number=9, name="Top Assembly", kind="AssemblyTop"),
            21: MechLayer(number=21, name="Top Component Outline", kind="ComponentOutlineTop"),
            17: MechLayer(number=17, name="Top Component Center", kind="ComponentCenterTop"),
            30: MechLayer(number=30, name="Aus", enabled=False),
        },
    )
    assert patch_pcblib_layers(lib, stack) == []
    keys = _keys(_text(lib))
    assert keys[b"LAYERSET5LAYERS"] == b"Mechanical9,Mechanical17,Mechanical21"
    assert keys[b"LAYERSET1LAYERS"].endswith(b"KeepOutLayer,Mechanical9,DrillDrawing,Mechanical17,Mechanical21")
    assert pcblib_layer_problems(lib, stack) == []
    assert patch_pcblib_layers(lib, stack) == []  # idempotent with high layers as well


@pytest.mark.parametrize(
    ("name", "tokens", "expected"),
    [
        # no DrillDrawing: all mechanical layers where the first one was
        (b"&All Layers", [b"TopLayer", b"Mechanical3", b"BottomLayer"], [b"TopLayer", b"Mechanical1", b"Mechanical20", b"BottomLayer"]),
        (b"&All Layers", [b"TopLayer"], [b"TopLayer", b"Mechanical1", b"Mechanical20"]),
        # a stale high layer in front of DrillDrawing moves behind it
        (b"&All Layers", [b"KeepOutLayer", b"Mechanical20", b"DrillDrawing"],
         [b"KeepOutLayer", b"Mechanical1", b"DrillDrawing", b"Mechanical20"]),
        (b"&Mechanical Layers", [], [b"Mechanical1", b"Mechanical20"]),
        (b"&Mechanical Layers", [b"Mechanical5", b"Mechanical31"], [b"Mechanical1", b"Mechanical20"]),
    ],
)
def test_layer_set_rebuild_rules(name: bytes, tokens: list[bytes], expected: list[bytes]):
    assert stackup._rebuild_layer_set(name, tokens, [1], [20]) == expected


NATIVE_LIBS = Path(r"C:\Users\Public\Documents\Altium\AD22\Examples\Harness Demo MB\Libs")


@pytest.mark.skipif(not (NATIVE_LIBS / "PCB1.PcbLib").is_file(), reason="Altium-Beispielbibliothek nicht installiert")
def test_layer_sets_match_a_native_altium_library():
    """PCB1.PcbLib (saved by Altium; read-only) already has the layer sets the patch writes for its own stack."""
    path = NATIVE_LIBS / "PCB1.PcbLib"
    segments, _trailer = stackup._split_library_data(read_library_data(path))
    header = stackup._Header(segments)
    text = b"|".join(s.raw for s in segments).decode("cp1252", "replace")
    own = stackup.parse_stackup_text(text, source=str(path))
    assert any(layer.enabled and n > 16 for n, layer in own.header_layers().items())  # Mech 20/21/23/24 enabled
    plan = stackup._Plan(replace={}, insert_after={}, delete=set())
    stackup._plan_layer_sets(header, own, plan)
    assert plan.replace == {}  # identical to what Altium wrote (incl. Mech 17-32 after DrillDrawing)


def test_patch_is_idempotent(lib: Path):
    assert patch_pcblib_layers(lib, default_stack()) == []
    digest = _sha(lib)
    assert patch_pcblib_layers(lib, default_stack()) == []
    assert _sha(lib) == digest  # nothing rewritten


def test_component_list_trailer_is_kept(lib: Path):
    data = read_library_data(lib)
    (length,) = struct.unpack_from("<I", data, 0)
    trailer = data[4 + length :]
    patch_pcblib_layers(lib, default_stack())
    patched = read_library_data(lib)
    (new_length,) = struct.unpack_from("<I", patched, 0)
    assert patched[4 + new_length :] == trailer
    assert new_length != length


def test_patch_with_custom_stack_removes_kinds(lib: Path):
    stack = LayerStack(
        layers={
            2: MechLayer(number=2, name="Montage | oben", kind=None),
            5: MechLayer(number=5, name="Bestückung oben", kind="AssemblyTop"),
        },
        pairs=[(5, 6)],
    )
    assert patch_pcblib_layers(lib, stack) == []
    keys = _keys(_text(lib))
    assert keys[b"LAYER58NAME"] == b"Montage / oben"  # '|' must never reach the header
    assert b"LAYER58MECHKIND" not in keys and b"V9_CACHE_LAYER70_MECHKIND" not in keys
    assert keys[b"LAYER61NAME"] == b"Bestueckung oben"  # ASCII only
    assert keys[b"LAYER61MECHKIND"] == b"AssemblyTop"
    assert keys[b"LAYER59NAME"] == b"Mechanical 3" and keys[b"LAYER59MECHENABLED"] == b"FALSE"
    assert [keys[b"MECHPAIR0L1"], keys[b"MECHPAIR0L2"]] == [b"MECHANICAL5", b"MECHANICAL6"]
    assert b"MECHPAIR1L1" not in keys
    assert pcblib_layer_problems(lib, stack) == []


def test_record_break_after_removed_pairs(lib: Path):
    stack = LayerStack(layers={9: MechLayer(number=9, name="A", kind="AssemblyTop")}, pairs=[])
    text_before = _text(lib)
    assert patch_pcblib_layers(lib, stack) == []
    text = _text(lib)
    assert b"MECHPAIR" not in text
    assert text.count(b"\r") == text_before.count(b"\r")


# --------------------------------------------------------------------------- refusals


def test_altium_kind_table_is_left_untouched(tmp_path: Path):
    path = synthetic_pcblib(tmp_path / "Native.PcbLib", mapping=NATIVE_KIND_MAPPING)
    digest = _sha(path)
    warnings = patch_pcblib_layers(path, default_stack())
    assert len(warnings) == 1 and "LayerKindMapping" in warnings[0] and "unerwarteter Aufbau" in warnings[0]
    assert _sha(path) == digest


def test_file_without_kind_table_is_patched(tmp_path: Path):
    path = synthetic_pcblib(tmp_path / "Old.PcbLib", mapping=None)
    assert patch_pcblib_layers(path, default_stack()) == []
    assert pcblib_layer_problems(path, default_stack()) == []


@pytest.mark.parametrize(
    ("mutate", "fragment"),
    [
        (lambda t: t.replace(b"|V9_CACHE_LAYER77_LAYERID=16908297", b""), "Mechanical 9 fehlt in der v9-Darstellung"),
        (lambda t: t.replace(b"|LAYERV7_3LAYERID=16908308", b""), "Mechanical 20 fehlt in der V7-Darstellung"),
        (lambda t: t.replace(b"LAYER_V8_19MECHENABLED=FALSE", b"LAYER_V8_19NAME=X"), "doppelter Schl"),
        (lambda t: t.replace(b"|LAYER70NAME=Mechanical 14", b""), "LAYER70"),
        (lambda t: t.replace(b"|MECHPAIR0L1=MECHANICAL2", b"").replace(b"|MECHPAIR1L1", b"|X=1|MECHPAIR1L1"),
         "stehen nicht zusammen"),
    ],
)
def test_unexpected_structure_leaves_file_untouched(tmp_path: Path, mutate, fragment):
    path = synthetic_pcblib(tmp_path / "Odd.PcbLib", header=mutate(rust_like_header()))
    digest = _sha(path)
    warnings = patch_pcblib_layers(path, default_stack())
    assert len(warnings) == 1 and fragment in warnings[0], warnings
    assert _sha(path) == digest


def test_missing_pairs_block_is_unexpected(tmp_path: Path):
    path = synthetic_pcblib(tmp_path / "NoPairs.PcbLib", header=rust_like_header(pairs=False))
    digest = _sha(path)
    assert "MECHPAIR" in patch_pcblib_layers(path, default_stack())[0]
    assert _sha(path) == digest
    # ... unless the stack has no pairs either
    assert patch_pcblib_layers(path, LayerStack(layers={9: MechLayer(number=9, name="A")})) == []


def test_damaged_header_and_wrong_files(tmp_path: Path):
    bad = tmp_path / "Bad.PcbLib"
    from test_sync_support import build_compound

    build_compound(bad, {"Library/Data": b"\x05\x00\x00\x00abc"})
    digest = _sha(bad)
    assert "Längenangabe" in patch_pcblib_layers(bad, default_stack())[0]
    assert _sha(bad) == digest
    assert "nur bei Footprint-Bibliotheken" in patch_pcblib_layers(tmp_path / "x.SchLib", default_stack())[0]
    assert "nicht gefunden" in patch_pcblib_layers(tmp_path / "missing.PcbLib", default_stack())[0]
    text_file = tmp_path / "Text.PcbLib"
    text_file.write_text("no compound file", encoding="ascii")
    assert "nicht lesbar" in patch_pcblib_layers(text_file, default_stack())[0]
    assert text_file.read_text(encoding="ascii") == "no compound file"


def test_invalid_kind_in_stack_is_reported(lib: Path):
    digest = _sha(lib)
    stack = LayerStack(layers={9: MechLayer(number=9, name="A", kind="Assembly Top")})
    warnings = patch_pcblib_layers(lib, stack)
    assert len(warnings) == 1 and "Ungültiger Lagentyp" in warnings[0]
    assert _sha(lib) == digest


def test_failed_verify_or_write_leaves_file_untouched(lib: Path, monkeypatch):
    digest = _sha(lib)

    def reject(_copy: Path) -> None:
        raise RustWriterError("Rust-Reader liest die Kopie nicht")

    warnings = patch_pcblib_layers(lib, default_stack(), verify=reject)
    assert len(warnings) == 1 and "Rust-Reader liest die Kopie nicht" in warnings[0]
    assert _sha(lib) == digest
    assert [p.name for p in lib.parent.iterdir()] == [lib.name]  # no temporary copy left

    def broken_write(path: Path, data: bytes) -> None:
        raise OSError("Datenträger voll")

    monkeypatch.setattr(stackup, "_write_library_data", broken_write)
    warnings = patch_pcblib_layers(lib, default_stack())
    assert "Datenträger voll" in warnings[0] and _sha(lib) == digest
    assert [p.name for p in lib.parent.iterdir()] == [lib.name]


def test_copy_check_detects_foreign_changes(lib: Path, monkeypatch):
    """The re-read of the copy must find every other stream unchanged."""
    original = stackup._write_library_data

    def write_and_damage(path: Path, data: bytes) -> None:
        original(path, data + b"x")  # trailer changed -> Library/Data differs from the plan

    monkeypatch.setattr(stackup, "_write_library_data", write_and_damage)
    digest = _sha(lib)
    warnings = patch_pcblib_layers(lib, default_stack())
    assert "nicht identisch" in warnings[0]
    assert _sha(lib) == digest


def test_verify_receives_a_patched_copy(lib: Path):
    seen: list[Path] = []

    def verify(copy: Path) -> None:
        assert copy != lib and copy.parent == lib.parent and copy.suffix == ".PcbLib"
        assert pcblib_layer_problems(copy, default_stack()) == []
        seen.append(copy)

    assert patch_pcblib_layers(lib, default_stack(), verify=verify) == []
    assert len(seen) == 1 and not seen[0].exists()


def test_problems_report_contradicting_representations(tmp_path: Path):
    header = rust_like_header().replace(b"LAYER_V8_19NAME=Mechanical 9", b"LAYER_V8_19NAME=Other")
    path = synthetic_pcblib(tmp_path / "Mixed.PcbLib", header=header)
    problems = pcblib_layer_problems(path)
    assert problems == ["Mechanical 9: die Darstellungen im Bibliothekskopf widersprechen sich."]
    assert patch_pcblib_layers(path, default_stack()) == []  # the patch makes them consistent again
    assert pcblib_layer_problems(path) == []


def test_library_data_helper_matches_rust_framing():
    data = library_data(b"|A=1", ["X"])
    assert data == struct.pack("<I", 5) + b"|A=1\x00" + struct.pack("<I", 1) + struct.pack("<I", 2) + b"\x01X"
    assert set(RUST_KINDS) == {2, 3, 4, 5, 6, 7}


# --------------------------------------------------------------------------- real Rust files


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture
def rust_ws(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Bibliothek", name="Header-Test")
    set_current(ws)
    try:
        yield ws
    finally:
        set_current(None)


def _footprints(ops: RustLibraryOps, lib: Path) -> list[dict]:
    resp = ops.client().call_tool("read_pcblib", {"filepath": _posix(lib)})
    return resp["footprints"]


@pytest.mark.rustwriter
def test_rust_write_gets_the_workspace_stack(rust_ws: Workspace, monkeypatch):
    lib = rust_ws.footprints_dir / "PF_CHIP.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    stack = stackup.effective_stack(default_stack(), LayerMap())
    monkeypatch.setattr(stackup, "HEADER_PATCH_ENABLED", False)
    assert ops.write_library_full(lib, [chip_0603(), soic8()]).ok
    template = read_pcblib_layers(lib)
    assert template[2].name == "Top Assembly" and template[2].kind == "AssemblyTop"  # Rust template
    assert not template[9].enabled
    before = json.dumps(_footprints(ops, lib), sort_keys=True)
    streams_before = _tree(lib)
    assert patch_pcblib_layers(lib, stack) == []
    # ole32 opens the result, every footprint stream is unchanged ...
    streams_after = _tree(lib)
    assert {k: v for k, v in streams_after.items() if k != "Library/Data"} == {
        k: v for k, v in streams_before.items() if k != "Library/Data"
    }
    # ... and the Rust reader returns identical footprints
    assert json.dumps(_footprints(ops, lib), sort_keys=True) == before
    assert ops.list_components(lib) == ["RESC1608X55N", "SOIC127P600X175-8N"]
    # with the switch on (default) the writer applies the stack itself
    monkeypatch.setattr(stackup, "HEADER_PATCH_ENABLED", True)
    other = rust_ws.footprints_dir / "PF_AUTO.PcbLib"
    result = ops.write_library_full(other, [chip_0603(), soic8()])
    assert result.ok and result.warnings == []
    assert pcblib_layer_problems(other, stack) == []


@pytest.mark.rustwriter
def test_header_survives_append_update_delete_and_full_rewrite(rust_ws: Workspace, tmp_path: Path):
    lib = rust_ws.footprints_dir / "PF_MIX.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    stack = stackup.effective_stack(default_stack(), LayerMap())
    assert ops.upsert_footprints(lib, [chip_0603()]).ok
    assert pcblib_layer_problems(lib, stack) == []
    assert ops.upsert_footprints(lib, [soic8()]).ok  # append
    changed = chip_0603()
    changed.description = "geändert"
    assert ops.upsert_footprints(lib, [changed]).ok  # update
    assert pcblib_layer_problems(lib, stack) == []
    assert ops.delete_components(lib, ["SOIC127P600X175-8N"]).ok
    assert pcblib_layer_problems(lib, stack) == []
    assert ops.write_library_full(lib, [chip_0603(), soic8()]).ok  # full rewrite -> template -> patched again
    assert pcblib_layer_problems(lib, stack) == []
    names = [fp["name"] for fp in _footprints(ops, lib)]
    assert names == ["RESC1608X55N", "SOIC127P600X175-8N"]


@pytest.mark.rustwriter
def test_header_patch_with_embedded_step(rust_ws: Workspace):
    step = write_step(rust_ws.models_dir / "box.step")
    lib = rust_ws.footprints_dir / "PF_STEP.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    result = ops.write_library_full(lib, [chip_with_step(rust_ws.rel(step))])
    assert result.ok, result.errors
    assert pcblib_layer_problems(lib, stackup.effective_stack(default_stack(), LayerMap())) == []
    spec = ops.read_footprint(lib, "CAPC2012X125N")
    assert spec is not None and spec.step is not None and Path(rust_ws.root / spec.step.file).is_file()


@pytest.mark.rustwriter
def test_custom_workspace_stack_and_switch(rust_ws: Workspace, monkeypatch):
    stack_file = rust_ws.root / "eigen.stackup"
    stack_file.write_text(
        "STACKUPVERSION=1|LAYER_V8_19NAME=Montage oben|LAYER_V8_19LAYERID=16908297|LAYER_V8_19MECHENABLED=TRUE"
        "|LAYER_V8_19MECHKIND=AssemblyTop|MECHPAIR0L1=MECHANICAL9|MECHPAIR0L2=MECHANICAL10",
        encoding="ascii",
    )
    rust_ws.settings.layer_stackup = "eigen.stackup"
    lib = rust_ws.footprints_dir / "PF_OWN.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    assert ops.write_library_full(lib, [chip_0603()]).ok
    layers = read_pcblib_layers(lib)
    assert layers[9].name == "Montage oben" and layers[9].kind == "AssemblyTop"
    assert layers[11].enabled and layers[11].name == "Top Designator"  # LayerMap layer, enabled by PartForge
    assert not layers[1].enabled and layers[2].kind is None  # not in the stack: plain, disabled
    monkeypatch.setenv(stackup.PATCH_ENV, "0")
    other = rust_ws.footprints_dir / "PF_OFF.PcbLib"
    assert ops.write_library_full(other, [chip_0603()]).ok
    assert read_pcblib_layers(other)[2].kind == "AssemblyTop"  # switched off: Rust template stays


@pytest.mark.rustwriter
def test_unreadable_stack_file_warns_but_writes(rust_ws: Workspace):
    rust_ws.settings.layer_stackup = "fehlt.stackup"
    lib = rust_ws.footprints_dir / "PF_WARN.PcbLib"
    result = RustLibraryOps(workspace=rust_ws).write_library_full(lib, [chip_0603()])
    assert result.ok
    assert any("Lagen-Datei" in w for w in result.warnings)
    assert pcblib_layer_problems(lib, stackup.effective_stack(default_stack(), LayerMap())) == []


@pytest.mark.rustwriter
def test_rejected_copy_keeps_the_written_library(rust_ws: Workspace, monkeypatch):
    lib = rust_ws.footprints_dir / "PF_REJ.PcbLib"
    ops = RustLibraryOps(workspace=rust_ws)
    monkeypatch.setattr(RustLibraryOps, "_component_names", staticmethod(lambda client, path: [path.name]))
    result = ops.write_library_full(lib, [chip_0603()])
    assert result.ok and any("Lagen-Kopf" in w for w in result.warnings)
    assert read_pcblib_layers(lib)[2].kind == "AssemblyTop"  # untouched template
    assert [p.name for p in lib.parent.iterdir() if p.suffix == ".PcbLib"] == [lib.name]
