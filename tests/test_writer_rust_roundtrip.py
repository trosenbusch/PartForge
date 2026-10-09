"""Round trips through the real ``altium-designer-mcp.exe`` (marker ``rustwriter``)."""
from __future__ import annotations

import copy
import hashlib
import re
import shutil
import time
from pathlib import Path

import pytest
from test_writer_samples import (
    STEP_TEXT,
    chip_0603,
    chip_with_step,
    header_tht,
    ic8_symbol,
    opamp_symbol,
    qfn16,
    resistor_symbol,
    soic8,
    write_step,
)

from partforge.altium.libwriter import RustLibraryWriter
from partforge.altium.rustwriter import (
    RustLibraryOps,
    RustToolError,
    RustValidationError,
    _posix,
    get_client,
    shutdown_client,
    symbol_palette,
)
from partforge.config import detect_rust_writer
from partforge.geometry.model import FootprintSpec, SymbolSpec, SymRect
from partforge.workspace import LayerMap, Workspace, set_current

pytestmark = pytest.mark.rustwriter

TOL = 1e-4


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture
def ws(tmp_path: Path):
    workspace = Workspace.create(tmp_path / "Bibliothek", name="Writer-Test")
    set_current(workspace)
    try:
        yield workspace
    finally:
        set_current(None)


@pytest.fixture
def writer(ws) -> RustLibraryWriter:
    return RustLibraryWriter(detect_rust_writer(), workspace=ws)


class SpyClient:
    """Wraps the real client, records tool calls and can inject failures."""

    def __init__(self, inner, fail_on: str | None = None):
        self.inner = inner
        self.calls: list[str] = []
        self.fail_on = fail_on

    def ensure_allowed(self, dirs, *, exact=False):
        self.inner.ensure_allowed(dirs, exact=exact)

    def call_tool(self, name, arguments, *, timeout=None):
        self.calls.append(name)
        if name == self.fail_on:
            raise RustToolError(name, "Failed to write file: injected failure")
        return self.inner.call_tool(name, arguments, timeout=timeout)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- comparisons


def _assert_symbol_equal(expected: SymbolSpec, actual: SymbolSpec) -> None:
    assert actual.name == expected.name
    assert actual.description == expected.description
    assert actual.designator_prefix == expected.designator_prefix
    assert actual.part_count == expected.part_count
    assert actual.comment == (expected.comment if expected.comment.strip() not in ("", "*") else "*")
    assert actual.parameters == expected.parameters
    assert [f.name for f in actual.footprints] == [f.name for f in expected.footprints]
    exp_pins = [
        (p.designator, p.name, p.x, p.y, p.orientation, p.length, p.electrical, p.part, p.show_name, p.show_designator, p.hidden)
        for p in expected.pins
    ]
    act_pins = [
        (p.designator, p.name, p.x, p.y, p.orientation, p.length, p.electrical, p.part, p.show_name, p.show_designator, p.hidden)
        for p in actual.pins
    ]
    assert sorted(act_pins) == sorted(exp_pins)
    line_default, fill_default = symbol_palette(expected)

    def norm(g) -> tuple:
        if g.kind == "rect":
            return ("rect", g.part, min(g.x1, g.x2), min(g.y1, g.y2), max(g.x1, g.x2), max(g.y1, g.y2), g.filled, g.line_width)
        if g.kind in ("line", "polygon"):
            return (g.kind, g.part, tuple((round(p.x, 3), round(p.y, 3)) for p in g.points), g.line_width)
        if g.kind == "arc":
            return ("arc", g.part, g.cx, g.cy, g.r, g.start, g.end)
        if g.kind == "ellipse":
            return ("ellipse", g.part, g.cx, g.cy, g.rx, g.ry, g.filled)
        return ("text", g.part, g.x, g.y, g.text, g.justify, g.rotation)

    assert sorted(map(norm, actual.graphics), key=repr) == sorted(map(norm, expected.graphics), key=repr)
    for g in actual.graphics:
        if isinstance(g, SymRect):
            assert g.color is not None
            assert g.color == ("#800000" if line_default == 128 else "#0000FF")
    del fill_default


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is b
    return abs(a - b) <= TOL


def _assert_footprint_equal(expected: FootprintSpec, actual: FootprintSpec) -> None:
    assert actual.name == expected.name
    assert actual.description == expected.description
    assert [p.designator for p in actual.pads] == [p.designator for p in expected.pads]
    for e, a in zip(expected.pads, actual.pads, strict=True):
        for key in ("x", "y", "width", "height", "rotation"):
            assert _close(getattr(e, key), getattr(a, key)), (e.designator, key, getattr(e, key), getattr(a, key))
        assert (a.shape, a.side, a.plated, a.paste) == (e.shape, e.side, e.plated, e.paste), e.designator
        if e.shape == "roundrect":
            assert a.corner_radius_pct == (e.corner_radius_pct if e.corner_radius_pct is not None else 50)
        assert _close(e.hole, a.hole) and _close(e.hole_length, a.hole_length), e.designator
        assert _close(e.mask_expansion, a.mask_expansion)
        if e.paste:
            assert _close(e.paste_expansion, a.paste_expansion)

    def tracks(spec):
        return sorted((t.layer, round(t.x1, 3), round(t.y1, 3), round(t.x2, 3), round(t.y2, 3), round(t.width, 4)) for t in spec.tracks)

    assert tracks(actual) == tracks(expected)
    for e, a in zip(expected.tracks, actual.tracks, strict=True):
        assert all(_close(getattr(e, k), getattr(a, k)) for k in ("x1", "y1", "x2", "y2", "width"))
    assert len(actual.arcs) == len(expected.arcs)
    for e, a in zip(expected.arcs, actual.arcs, strict=True):
        assert e.layer == a.layer
        assert all(_close(getattr(e, k), getattr(a, k)) for k in ("cx", "cy", "r", "start", "end", "width"))
    assert len(actual.regions) == len(expected.regions)
    for e, a in zip(expected.regions, actual.regions, strict=True):
        assert e.layer == a.layer
        assert all(_close(p.x, q.x) and _close(p.y, q.y) for p, q in zip(e.points, a.points, strict=True))
    assert [(t.layer, t.text, t.justify) for t in actual.texts] == [(t.layer, t.text, t.justify) for t in expected.texts]
    for e, a in zip(expected.texts, actual.texts, strict=True):
        assert all(_close(getattr(e, k), getattr(a, k)) for k in ("x", "y", "height", "stroke", "rotation"))
    assert len(actual.bodies) == len(expected.bodies)
    for e, a in zip(expected.bodies, actual.bodies, strict=True):
        assert _close(e.z_bottom, a.z_bottom) and _close(e.z_top, a.z_top)
        assert a.color.upper() == e.color.upper() and _close(e.opacity, a.opacity)
        assert all(_close(p.x, q.x) and _close(p.y, q.y) for p, q in zip(e.outline, a.outline, strict=True))


# --------------------------------------------------------------------------- symbols


def test_symbols_roundtrip(ws, writer):
    lib = ws.symbols_dir / "PF_Mixed.SchLib"
    specs = [resistor_symbol(), ic8_symbol(), opamp_symbol()]
    result = writer.write_symbols(lib, specs)
    assert result.ok, result.errors
    assert result.written == [s.name for s in specs]
    assert result.backend == "rust" and result.library == str(lib)
    assert writer.list_components(lib) == [s.name for s in specs]
    for spec in specs:
        back = writer.read_symbol(lib, spec.name)
        assert back is not None
        _assert_symbol_equal(spec, back)
    assert writer.read_symbol(lib, "DOES_NOT_EXIST") is None
    infos = {i.name: i for i in writer.scan_library(lib)}
    assert infos["LM358_DUAL"].pin_count == 8 and infos["LM358_DUAL"].part_count == 3
    assert infos["PF_RES"].kind == "symbol"


def test_symbol_update_keeps_designator_prefix(ws, writer):
    lib = ws.symbols_dir / "PF_Passives.SchLib"
    assert writer.write_symbols(lib, [resistor_symbol()]).ok
    changed = resistor_symbol()
    changed.description = "Widerstand, geändert"
    result = writer.write_symbols(lib, [changed])
    assert result.ok, result.errors
    back = writer.read_symbol(lib, "PF_RES")
    assert back is not None
    assert back.designator_prefix == "R" and back.description == "Widerstand, geändert"


# --------------------------------------------------------------------------- footprints


def test_footprints_roundtrip_with_house_layers(ws, writer):
    lib = ws.footprints_dir / "PF_TEST.PcbLib"
    specs = [chip_0603(), soic8(), header_tht(), qfn16()]
    result = writer.write_footprints(lib, specs)
    assert result.ok, result.errors
    assert result.written == [s.name for s in specs]
    for spec in specs:
        notes: list[str] = []
        back = writer.ops.read_footprint(lib, spec.name, notes=notes)
        assert back is not None
        assert notes == []
        _assert_footprint_equal(spec, back)
    infos = {i.name: i for i in writer.scan_library(lib)}
    assert infos["QFN50P300X300X80-17N"].pin_count == 17 and infos["QFN50P300X300X80-17N"].has_3d is True
    # the house layers really are Mechanical 9/11/13/15/17/19/21 in the file
    raw = get_client().call_tool("get_component", {"filepath": _posix(lib), "component_name": "RESC1608X55N"})["component"]
    track_layers = {t["layer"] for t in raw["tracks"]}
    assert track_layers == {"Mechanical 9", "Mechanical 15", "Mechanical 17", "Mechanical 21", "Top Overlay"}
    assert {t["layer"] for t in raw["text"]} == {"Mechanical 11", "Mechanical 19"}
    assert raw["component_bodies"][0]["layer"] == "Mechanical 13"


def test_footprints_roundtrip_with_tr_style_alias_layers(ws):
    # older TR_* libraries put assembly/comment on Mechanical 5/7, which the writer reads back
    # as its aliases "Bottom Courtyard"/"Bottom 3D Body"
    tr_layers = LayerMap(
        assembly="Mechanical 5", comment="Mechanical 7", designator="Mechanical 9", component_outline="Mechanical 19"
    )
    ops = RustLibraryOps(workspace=ws, layer_map=tr_layers)
    lib = ws.footprints_dir / "PF_TR.PcbLib"
    specs = [chip_0603(), soic8()]
    assert ops.upsert_footprints(lib, specs).ok
    raw = get_client().call_tool("get_component", {"filepath": _posix(lib), "component_name": "RESC1608X55N"})["component"]
    assert {"Bottom Courtyard", "Mechanical 19"} <= {t["layer"] for t in raw["tracks"]}
    assert {t["layer"] for t in raw["text"]} == {"Mechanical 9", "Bottom 3D Body"}
    for spec in specs:
        notes: list[str] = []
        back = ops.read_footprint(lib, spec.name, notes=notes)
        assert back is not None and notes == []
        _assert_footprint_equal(spec, back)


def test_embedded_step_plus_extruded_body(ws, writer):
    write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    specs = [chip_0603(), chip_with_step("3D/box.step")]
    result = writer.write_footprints(lib, specs)
    assert result.ok, result.errors
    assert writer.list_components(lib) == ["RESC1608X55N", "CAPC2012X125N"]  # carriers removed
    client = get_client()
    raw_names = client.call_tool("list_components", {"filepath": _posix(lib)})["components"]
    assert raw_names == ["RESC1608X55N", "CAPC2012X125N"]
    back = writer.read_footprint(lib, "CAPC2012X125N")
    assert back is not None and back.step is not None
    # the embedded model is identical to 3D/box.step -> that file is referenced again
    assert back.step.file == "3D/box.step" and back.step.rotation == (0.0, 0.0, 90.0) and back.step.offset[2] == pytest.approx(0.1)
    assert sorted(p.name for p in ws.models_dir.iterdir()) == ["box.step"]
    assert len(back.bodies) == 1 and back.bodies[0].z_top == pytest.approx(1.25) and back.bodies[0].color == "#C0A060"
    assert back.height == pytest.approx(1.25)
    raw = client.call_tool("get_component", {"filepath": _posix(lib), "component_name": "CAPC2012X125N"})["component"]
    step_bodies = [b for b in raw["component_bodies"] if b.get("embedded")]
    assert len(step_bodies) == 1
    assert step_bodies[0]["overall_height"] == pytest.approx(1.25)  # real height instead of 0
    assert step_bodies[0]["layer"] == "Mechanical 13"
    models = client.call_tool("extract_step_model", {"filepath": _posix(lib), "mode": "list"})["models"]
    assert [m["name"] for m in models] == ["box.step"]
    # update path: the old embedded model must not pile up
    result = writer.write_footprints(lib, [chip_with_step("3D/box.step")])
    assert result.ok, result.errors
    models = client.call_tool("extract_step_model", {"filepath": _posix(lib), "mode": "list"})["models"]
    assert len(models) == 1
    # full rewrite path
    result = writer.write_library_full(lib, [chip_with_step("3D/box.step")])
    assert result.ok, result.errors
    assert writer.list_components(lib) == ["CAPC2012X125N"]
    assert writer.read_footprint(lib, "CAPC2012X125N").step is not None  # type: ignore[union-attr]


def test_missing_step_file_is_rejected_before_writing(ws, writer):
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    with pytest.raises(RustValidationError, match="STEP-Datei nicht gefunden"):
        writer.write_footprints(lib, [chip_with_step("3D/missing.step")])
    assert not lib.exists()


def test_upsert_updates_existing_and_appends_new(ws, writer):
    lib = ws.footprints_dir / "PF_MIX.PcbLib"
    assert writer.write_footprints(lib, [chip_0603("A"), chip_0603("B")]).ok
    before_a = writer.read_footprint(lib, "A")
    changed = chip_0603("B")
    changed.pads[0].width = 1.0
    result = writer.write_footprints(lib, [changed, soic8("C")])
    assert result.ok, result.errors
    assert result.written == ["B", "C"]
    assert writer.list_components(lib) == ["A", "B", "C"]
    assert writer.read_footprint(lib, "B").pads[0].width == pytest.approx(1.0, abs=TOL)  # type: ignore[union-attr]
    assert writer.read_footprint(lib, "A") == before_a
    # no .bak files beside the library; Backups/lib holds exactly the state before the upsert
    assert list(ws.footprints_dir.glob("*.bak")) == []
    backups = _backups(ws, lib)
    assert len(backups) == 1 and _components_of(ws, backups[0], ".PcbLib") == ["A", "B"]


def test_full_rewrite_replaces_library(ws, writer):
    lib = ws.footprints_dir / "PF_FULL.PcbLib"
    assert writer.write_footprints(lib, [chip_0603("A"), chip_0603("B")]).ok
    result = writer.write_library_full(lib, [soic8("X"), qfn16("Y")])
    assert result.ok, result.errors
    assert writer.list_components(lib) == ["X", "Y"]
    sym_lib = ws.symbols_dir / "PF_FULL.SchLib"
    assert writer.write_library_full(sym_lib, [resistor_symbol(), ic8_symbol()]).ok
    assert writer.write_library_full(sym_lib, [opamp_symbol()]).ok
    assert writer.list_components(sym_lib) == ["LM358_DUAL"]
    with pytest.raises(RustValidationError, match="erwartet"):
        writer.write_library_full(sym_lib, [chip_0603()])  # type: ignore[list-item]


def test_delete_components(ws, writer):
    lib = ws.footprints_dir / "PF_DEL.PcbLib"
    assert writer.write_footprints(lib, [chip_0603("A"), chip_0603("B")]).ok
    result = writer.delete_components(lib, ["B", "NOPE"])
    assert result.deleted == ["B"]
    assert any("NOPE" in w for w in result.warnings)
    assert writer.list_components(lib) == ["A"]
    missing = writer.delete_components(ws.footprints_dir / "PF_NONE.PcbLib", ["A"])
    assert missing.deleted == [] and missing.warnings


def test_invalid_input_rejected_before_sending(ws):
    spy = SpyClient(get_client())
    ops = RustLibraryOps(client=spy, workspace=ws)  # type: ignore[arg-type]
    bad = resistor_symbol()
    bad.pins[0].x = -95
    lib = ws.symbols_dir / "PF_BAD.SchLib"
    with pytest.raises(RustValidationError):
        ops.upsert_symbols(lib, [bad])
    with pytest.raises(RustValidationError, match="Dateiendung"):
        ops.upsert_symbols(ws.symbols_dir / "PF_BAD.PcbLib", [resistor_symbol()])
    with pytest.raises(RustValidationError, match="außerhalb"):
        ops.upsert_footprints(ws.root.parent / "outside.PcbLib", [chip_0603()])
    with pytest.raises(RustValidationError, match="mehrfach"):
        ops.upsert_footprints(ws.footprints_dir / "PF_DUP.PcbLib", [chip_0603(), chip_0603()])
    assert spy.calls == []
    assert not lib.exists()


def test_failed_update_rolls_back_library(ws):
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_ROLL.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603("A"), chip_0603("B")]).ok
    before = _sha(lib)
    spy = SpyClient(get_client(), fail_on="update_component")
    failing = RustLibraryOps(client=spy, workspace=ws)  # type: ignore[arg-type]
    changed = chip_0603("B")
    changed.pads[0].width = 1.2
    result = failing.upsert_footprints(lib, [changed, soic8("C")])
    assert set(result.errors) == {"B", "C"} and result.written == []
    assert "geschrieben" in result.errors["B"]
    assert "write_pcblib" in spy.calls  # C was appended before the failure ...
    assert _sha(lib) == before  # ... and rolled back
    assert ops.list_components(lib) == ["A", "B"]


def test_read_external_library_through_temp_copy(ws, writer, tmp_path):
    lib = ws.footprints_dir / "PF_EXT.PcbLib"
    assert writer.write_footprints(lib, [soic8()]).ok
    external = tmp_path / "external" / "Fremd.PcbLib"
    external.parent.mkdir()
    shutil.copy2(lib, external)
    before = _sha(external)
    back = writer.read_footprint(external, "SOIC127P600X175-8N")
    assert back is not None and len(back.pads) == 8
    assert writer.list_components(external) == ["SOIC127P600X175-8N"]
    assert _sha(external) == before


def test_hundred_footprints_in_one_call_under_three_seconds(ws):
    ops = RustLibraryOps(workspace=ws)
    ops.client().start()  # process start is not part of the measured write
    specs = [chip_0603(f"RES_{i:03d}") for i in range(100)]
    lib = ws.footprints_dir / "PF_PERF.PcbLib"
    started = time.perf_counter()
    result = ops.write_library_full(lib, specs)
    elapsed = time.perf_counter() - started
    assert result.ok, list(result.errors.items())[:3]
    assert len(result.written) == 100
    assert elapsed < 3.0, f"{elapsed:.2f} s"


def test_explicit_workspace_does_not_need_current_workspace(tmp_path):
    other = Workspace.create(tmp_path / "Andere", name="Ohne aktuelle Bibliothek")
    set_current(None)
    ops = RustLibraryOps(workspace=other)
    lib = other.footprints_dir / "PF_CHIP.PcbLib"
    result = ops.upsert_footprints(lib, [chip_0603()])
    assert result.ok, result.errors
    client = get_client(allowed_dirs=ops.allowed_dirs())
    assert any(Path(p) == other.root for p in client.allowed_dirs)
    assert ops.list_components(lib) == ["RESC1608X55N"]


def test_default_sandbox_follows_current_workspace(ws):
    from partforge.altium.rustwriter import temp_dir

    client = get_client()
    dirs = {str(p).lower() for p in client.allowed_dirs}
    assert str(ws.root).lower() in dirs and str(temp_dir()).lower() in dirs
    assert len(dirs) == 2


class OrderDroppingClient(SpyClient):
    """Simulates a writer that ignores primitive_order (pins would be written first)."""

    def call_tool(self, name, arguments, *, timeout=None):
        if name in ("write_schlib", "update_component") and "symbols" in arguments:
            arguments = dict(arguments)
            arguments["symbols"] = [{k: v for k, v in s.items() if k != "primitive_order"} for s in arguments["symbols"]]
        return super().call_tool(name, arguments, timeout=timeout)


def test_symbol_records_are_stored_graphics_first(ws, writer):
    lib = ws.symbols_dir / "PF_ICs.SchLib"
    assert writer.write_symbols(lib, [ic8_symbol(), opamp_symbol()]).ok
    client = get_client()
    raw = client.call_tool("get_component", {"filepath": _posix(lib), "component_name": "NE555DR"})["component"]
    order = raw["primitive_order"]
    assert order.index("pin") > order.index("rectangle")
    assert order == ["rectangle"] + ["pin"] * 8 + ["parameter"] * 2
    # also after an update through update_component
    assert writer.write_symbols(lib, [ic8_symbol()]).ok
    raw = client.call_tool("get_component", {"filepath": _posix(lib), "component_name": "NE555DR"})["component"]
    assert raw["primitive_order"][0] == "rectangle"


def test_lost_primitive_order_is_detected(ws):
    ops = RustLibraryOps(client=OrderDroppingClient(get_client()), workspace=ws)  # type: ignore[arg-type]
    lib = ws.symbols_dir / "PF_ORDER.SchLib"
    result = ops.upsert_symbols(lib, [ic8_symbol(), resistor_symbol()])
    assert "NE555DR" in result.errors and "verdeckt" in result.errors["NE555DR"]  # filled body
    # all or nothing: the unfilled symbol of the same call is rolled back as well
    assert result.written == [] and "Nicht geschrieben" in result.errors["PF_RES"]
    assert all("zurückgesetzt" in message for message in result.errors.values())
    assert any(w.startswith("PF_RES:") and "Zeichenreihenfolge" in w for w in result.warnings)
    assert not lib.exists()  # the library did not exist before -> removed again
    # an unfilled body alone only gives a warning
    result = ops.upsert_symbols(lib, [resistor_symbol()])
    assert result.ok and result.written == ["PF_RES"]
    assert any(w.startswith("PF_RES:") and "Zeichenreihenfolge" in w for w in result.warnings)


def test_stroke_text_is_stored_with_compensated_anchor(ws, writer):
    lib = ws.footprints_dir / "PF_TEXT.PcbLib"
    assert writer.write_footprints(lib, [chip_0603()]).ok
    raw = get_client().call_tool("get_component", {"filepath": _posix(lib), "component_name": "RESC1608X55N"})["component"]
    designator = next(t for t in raw["text"] if t["text"] == ".Designator")
    assert designator["x"] == pytest.approx(-5.06, abs=TOL) and designator["y"] == pytest.approx(-0.5, abs=TOL)
    back = writer.read_footprint(lib, "RESC1608X55N")
    assert back is not None
    assert [(round(t.x, 4), round(t.y, 4), t.justify) for t in back.texts] == [(0.0, 0.0, "middle_center")] * 2


def test_update_without_step_drops_orphaned_model(ws, writer):
    write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_ORPHAN.PcbLib"
    assert writer.write_footprints(lib, [chip_with_step("3D/box.step")]).ok
    client = get_client()
    assert len(client.call_tool("extract_step_model", {"filepath": _posix(lib), "mode": "list"})["models"]) == 1
    plain = chip_with_step("3D/box.step")
    plain.step = None
    result = writer.write_footprints(lib, [plain])
    assert result.ok, result.errors
    with pytest.raises(RustToolError, match="No embedded 3D models"):
        client.call_tool("extract_step_model", {"filepath": _posix(lib), "mode": "list"})
    assert writer.read_footprint(lib, "CAPC2012X125N").step is None  # type: ignore[union-attr]


def test_many_updates_are_batched(ws):
    spy = SpyClient(get_client())
    ops = RustLibraryOps(client=spy, workspace=ws)  # type: ignore[arg-type]
    lib = ws.footprints_dir / "PF_BATCH.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603(f"R{i}") for i in range(5)]).ok
    spy.calls.clear()
    changed = [chip_0603(f"R{i}") for i in range(4)]
    for spec in changed:
        spec.pads[0].width = 1.1
    result = ops.upsert_footprints(lib, [*changed, chip_0603("NEW")])
    assert result.ok, result.errors
    assert sorted(result.written) == ["NEW", "R0", "R1", "R2", "R3"]
    assert "update_component" not in spy.calls
    assert spy.calls.count("delete_component") == 1 and spy.calls.count("write_pcblib") == 1
    assert sorted(ops.list_components(lib)) == ["NEW", "R0", "R1", "R2", "R3", "R4"]
    assert ops.read_footprint(lib, "R2").pads[0].width == pytest.approx(1.1, abs=TOL)  # type: ignore[union-attr]
    assert ops.read_footprint(lib, "R4").pads[0].width == pytest.approx(0.9, abs=TOL)  # type: ignore[union-attr]
    sym_lib = ws.symbols_dir / "PF_BATCH.SchLib"
    assert ops.upsert_symbols(sym_lib, [resistor_symbol(f"S{i}") for i in range(3)]).ok
    result = ops.upsert_symbols(sym_lib, [resistor_symbol(f"S{i}") for i in range(3)])
    assert result.ok and sorted(result.written) == ["S0", "S1", "S2"]
    assert all(ops.read_symbol(sym_lib, f"S{i}").designator_prefix == "R" for i in range(3))  # type: ignore[union-attr]


def test_batched_update_with_step_models(ws, writer):
    write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_STEPBATCH.PcbLib"
    specs = [chip_with_step("3D/box.step", name=f"C{i}") for i in range(3)]
    assert writer.write_footprints(lib, specs).ok
    result = writer.write_footprints(lib, [chip_with_step("3D/box.step", name=f"C{i}") for i in range(3)])
    assert result.ok, result.errors
    client = get_client()
    models = client.call_tool("extract_step_model", {"filepath": _posix(lib), "mode": "list"})["models"]
    assert len(models) == 1  # one embedded copy shared by all three, old copies dropped
    assert writer.list_components(lib) == ["C0", "C1", "C2"]
    for i in range(3):
        back = writer.read_footprint(lib, f"C{i}")
        assert back is not None and back.step is not None and len(back.bodies) == 1


# --------------------------------------------------------------------------- review regressions: free text


def test_separator_in_free_text_never_reaches_the_writer(ws):
    spy = SpyClient(get_client())
    ops = RustLibraryOps(client=spy, workspace=ws)  # type: ignore[arg-type]
    sym = ic8_symbol()
    sym.parameters = {"Note": "v|IsHidden=F|Name=Evil|Text=pwned"}
    with pytest.raises(RustValidationError, match="Zeichen '\\|'"):
        ops.upsert_symbols(ws.symbols_dir / "PF_INJ.SchLib", [sym])
    fp = chip_0603("REAL_NAME")
    fp.description = "x|PATTERN=EVIL|HEIGHT=99mm"
    with pytest.raises(RustValidationError, match="Beschreibung"):
        ops.write_library_full(ws.footprints_dir / "PF_INJ.PcbLib", [fp, chip_0603("OTHER")])
    sym = resistor_symbol()
    sym.description = "line1\r\nline2"
    with pytest.raises(RustValidationError, match="Steuerzeichen"):
        ops.write_library_full(ws.symbols_dir / "PF_NL.SchLib", [sym])
    assert spy.calls == []
    assert list(ws.symbols_dir.iterdir()) == [] and list(ws.footprints_dir.iterdir()) == []


# --------------------------------------------------------------------------- review regressions: backups


def _components_of(ws: Workspace, backup: Path, suffix: str) -> list[str]:
    """Component names stored in a backup file (read through a copy with a library extension)."""
    copy = ws.exports_dir / f"{backup.stem.replace('.', '_')}{suffix}"
    shutil.copy2(backup, copy)
    try:
        return get_client().call_tool("list_components", {"filepath": _posix(copy)})["components"]
    finally:
        copy.unlink()


def _backups(ws: Workspace, library: Path) -> list[Path]:
    return sorted((ws.backups_dir / "lib").glob(f"{library.name}.*.bak"))


def test_backup_of_batched_update_holds_the_state_before_the_operation(ws):
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_BAK.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603(n) for n in "ABCDE"]).ok
    assert _backups(ws, lib) == []  # the library did not exist before: nothing to back up
    changed = [chip_0603(n) for n in "BCD"]
    for spec in changed:
        spec.pads[0].width = 1.1
    result = ops.upsert_footprints(lib, changed)  # delete + append: several writer calls
    assert result.ok, result.errors
    backups = _backups(ws, lib)
    assert len(backups) == 1
    assert _components_of(ws, backups[0], ".PcbLib") == ["A", "B", "C", "D", "E"]
    assert list(ws.footprints_dir.glob("*.bak")) == []  # the writer's intermediate .bak files are gone
    # the backup really is the old state: B still has the old pad width there
    restore = ws.footprints_dir / "PF_RESTORED.PcbLib"
    shutil.copy2(backups[0], restore)
    assert ops.read_footprint(restore, "B").pads[0].width == pytest.approx(0.9, abs=TOL)  # type: ignore[union-attr]


def test_backup_of_step_upsert_and_full_rewrite(ws):
    write_step(ws.models_dir / "box.step")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_BAK2.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603("X")]).ok
    assert ops.upsert_footprints(lib, [chip_with_step("3D/box.step", name="Y")]).ok  # carrier + append + delete
    backups = _backups(ws, lib)
    assert len(backups) == 1 and _components_of(ws, backups[0], ".PcbLib") == ["X"]
    full = ws.footprints_dir / "PF_F.PcbLib"
    assert ops.write_library_full(full, [chip_0603("OLD1"), chip_0603("OLD2")]).ok
    assert ops.write_library_full(full, [chip_with_step("3D/box.step", name="NEW1")]).ok
    backups = _backups(ws, full)
    assert len(backups) == 1 and _components_of(ws, backups[0], ".PcbLib") == ["OLD1", "OLD2"]
    assert list(ws.footprints_dir.glob("*.bak")) == []


def test_backups_of_symbol_update_and_delete(ws):
    ops = RustLibraryOps(workspace=ws)
    lib = ws.symbols_dir / "PF_S.SchLib"
    assert ops.upsert_symbols(lib, [resistor_symbol("R1"), resistor_symbol("R2")]).ok
    changed = resistor_symbol("R1")
    changed.description = "neu"
    assert ops.upsert_symbols(lib, [changed]).ok  # update_component path
    result = ops.delete_components(lib, ["R2"])
    assert result.deleted == ["R2"]
    backups = _backups(ws, lib)
    assert [_components_of(ws, b, ".SchLib") for b in backups] == [["R1", "R2"], ["R1", "R2"]]
    assert len({b.name for b in backups}) == 2  # millisecond stamps, never overwritten
    assert list(ws.symbols_dir.glob("*.bak")) == []


def test_failed_operation_leaves_no_backup_and_no_writer_bak(ws):
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_FAIL.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603("A"), chip_0603("B")]).ok
    before = _sha(lib)
    failing = RustLibraryOps(client=SpyClient(get_client(), fail_on="update_component"), workspace=ws)  # type: ignore[arg-type]
    changed = chip_0603("B")
    changed.pads[0].width = 1.2
    result = failing.upsert_footprints(lib, [changed, soic8("C")])
    assert not result.ok and all("zurückgesetzt" in m for m in result.errors.values())
    assert _sha(lib) == before
    assert _backups(ws, lib) == [] and list(ws.footprints_dir.glob("*.bak")) == []


def test_older_writer_backups_are_moved_and_pruned(ws):
    ops = RustLibraryOps(workspace=ws, backup_keep=2)
    lib = ws.footprints_dir / "PF_OLD.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603("A")]).ok
    legacy = ws.footprints_dir / "PF_OLD.PcbLib.20200101_120000.bak"  # e.g. left by a writer run outside PartForge
    shutil.copy2(lib, legacy)
    for i in range(3):
        spec = chip_0603("A")
        spec.pads[0].width = 1.0 + i / 10
        assert ops.upsert_footprints(lib, [spec]).ok
    assert not legacy.exists()
    assert len(_backups(ws, lib)) == 2  # only the newest two are kept


def test_library_outside_the_workspace_keeps_its_backup_beside_it(ws, tmp_path):
    outside = tmp_path / "Extern"
    outside.mkdir()
    ops = RustLibraryOps(workspace=ws, extra_dirs=[outside])
    lib = outside / "Fremd.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603("A")]).ok
    spec = chip_0603("A")
    spec.pads[0].width = 1.0
    assert ops.upsert_footprints(lib, [spec]).ok
    backups = sorted(outside.glob("Fremd.PcbLib.*.bak"))
    assert len(backups) == 1 and re.fullmatch(r"Fremd\.PcbLib\.\d{8}_\d{6}_\d{3}\.bak", backups[0].name)
    assert not (ws.backups_dir / "lib").exists() or _backups(ws, lib) == []


# --------------------------------------------------------------------------- review regressions: rollback on failed checks


class PinDroppingClient(SpyClient):
    """Simulates a writer that silently drops a pin / pad (caught only by the check after writing)."""

    def call_tool(self, name, arguments, *, timeout=None):
        arguments = copy.deepcopy(dict(arguments))
        if name == "write_schlib":
            for symbol in arguments["symbols"]:
                if symbol["name"] == "NE555DR":
                    symbol["pins"] = symbol["pins"][:-1]
                    symbol["primitive_order"] = [t for t in symbol["primitive_order"]][:-1]
        elif name == "update_component" and "symbol" in arguments:
            arguments["symbol"]["pins"] = arguments["symbol"]["pins"][:-1]
        elif name == "write_pcblib":
            for footprint in arguments["footprints"]:
                if footprint["name"] == "BROKEN":
                    footprint["pads"] = footprint["pads"][:1]
        return super().call_tool(name, arguments, timeout=timeout)


def test_failed_check_after_writing_rolls_back_the_whole_call(ws):
    ops = RustLibraryOps(workspace=ws)
    sym_lib = ws.symbols_dir / "PF_ROLL.SchLib"
    assert ops.upsert_symbols(sym_lib, [resistor_symbol("KEEP")]).ok
    before = _sha(sym_lib)
    broken = RustLibraryOps(client=PinDroppingClient(get_client()), workspace=ws)  # type: ignore[arg-type]
    result = broken.upsert_symbols(sym_lib, [ic8_symbol(), resistor_symbol("OTHER")])  # append path
    assert result.written == [] and set(result.errors) == {"NE555DR", "OTHER"}
    assert "zurückgesetzt" in result.errors["NE555DR"] and "Nicht geschrieben" in result.errors["OTHER"]
    assert _sha(sym_lib) == before and ops.list_components(sym_lib) == ["KEEP"]
    assert ops.upsert_symbols(sym_lib, [ic8_symbol()]).ok
    before = _sha(sym_lib)
    result = broken.upsert_symbols(sym_lib, [ic8_symbol()])  # update_component path
    assert not result.ok and _sha(sym_lib) == before
    fp_lib = ws.footprints_dir / "PF_ROLL.PcbLib"
    assert ops.upsert_footprints(fp_lib, [chip_0603("A")]).ok
    before = _sha(fp_lib)
    result = broken.upsert_footprints(fp_lib, [chip_0603("BROKEN"), chip_0603("FINE")])
    assert result.written == [] and "1 statt 2 Pads" in result.errors["BROKEN"]
    assert _sha(fp_lib) == before
    result = broken.write_library_full(fp_lib, [chip_0603("BROKEN")])
    assert not result.ok and _sha(fp_lib) == before
    new_lib = ws.footprints_dir / "PF_NEW.PcbLib"
    assert not broken.upsert_footprints(new_lib, [chip_0603("BROKEN")]).ok
    assert not new_lib.exists()  # created by the failed call -> removed again
    assert _backups(ws, fp_lib) == [] and list(ws.footprints_dir.glob("*.bak")) == []


# --------------------------------------------------------------------------- review regressions: STEP read-back


def test_read_back_step_can_be_written_again_and_copied(ws):
    write_step(ws.models_dir / "box.step")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_RMW.PcbLib"
    assert ops.upsert_footprints(lib, [chip_with_step("3D/box.step", name="C1")]).ok
    back = ops.read_footprint(lib, "C1")
    assert back is not None and back.step is not None and back.step.file == "3D/box.step"
    back.description = "geändert"
    result = ops.upsert_footprints(lib, [back])  # read-modify-write
    assert result.ok, result.errors
    other = ws.footprints_dir / "PF_OTHER.PcbLib"
    assert ops.upsert_footprints(other, [back]).ok  # copy into another library
    copied = ops.read_footprint(other, "C1")
    assert copied is not None and copied.step is not None and copied.description == "geändert"
    assert copied.step.rotation == (0.0, 0.0, 90.0)
    models = get_client().call_tool("extract_step_model", {"filepath": _posix(other), "mode": "list"})["models"]
    assert [m["name"] for m in models] == ["box.step"]


def test_read_back_step_placement_in_the_workspace(ws):
    original = write_step(ws.models_dir / "box.step")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_PLACE.PcbLib"
    assert ops.upsert_footprints(lib, [chip_with_step("3D/box.step", name="C1")]).ok
    embedded = original.read_bytes()
    # the workspace file was edited since -> the embedded model is kept under a hash-suffixed name
    original.write_text(STEP_TEXT.replace("test box", "edited box"), encoding="ascii")
    back = ops.read_footprint(lib, "C1")
    assert back is not None and back.step is not None
    assert re.fullmatch(r"3D/box_[0-9a-f]{8}\.step", back.step.file)
    assert (ws.root / back.step.file).read_bytes() == embedded
    assert ops.read_footprint(lib, "C1").step.file == back.step.file  # type: ignore[union-attr]  # no duplicates
    # an identical file anywhere in the 3D folder is reused
    (ws.root / back.step.file).unlink()
    sub = ws.models_dir / "Hersteller" / "box.step"
    sub.parent.mkdir()
    sub.write_bytes(embedded)
    assert ops.read_footprint(lib, "C1").step.file == "3D/Hersteller/box.step"  # type: ignore[union-attr]
    assert sorted(p.name for p in ws.models_dir.iterdir()) == ["Hersteller", "box.step"]


def test_read_back_step_of_external_library_uses_the_cache(ws, tmp_path):
    from partforge.altium.rustwriter import step_cache_dir

    write_step(ws.models_dir / "box.step")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_EXT.PcbLib"
    assert ops.upsert_footprints(lib, [chip_with_step("3D/box.step", name="C1")]).ok
    external = tmp_path / "external" / "Fremd.PcbLib"
    external.parent.mkdir()
    shutil.copy2(lib, external)
    back = ops.read_footprint(external, "C1")
    assert back is not None and back.step is not None
    path = Path(back.step.file)
    assert path.is_absolute() and path.is_file() and path.read_bytes() == (ws.models_dir / "box.step").read_bytes()
    assert str(path).lower().startswith(str(step_cache_dir()).lower())
    assert sorted(p.name for p in ws.models_dir.iterdir()) == ["box.step"]  # nothing written into the workspace
    assert ops.upsert_footprints(ws.footprints_dir / "PF_IMPORT.PcbLib", [back]).ok  # importable


def test_read_all_extracts_several_models_in_one_call(ws):
    write_step(ws.models_dir / "a.step")
    (ws.models_dir / "b.step").write_text(STEP_TEXT.replace("test box", "second box"), encoding="ascii")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_MULTI.PcbLib"
    specs = [chip_with_step("3D/a.step", name="A"), chip_with_step("3D/b.step", name="B"), chip_0603("PLAIN")]
    assert ops.upsert_footprints(lib, specs).ok
    spy = SpyClient(get_client())
    reader = RustLibraryOps(client=spy, workspace=ws)  # type: ignore[arg-type]
    detailed = reader.read_all_detailed(lib)
    steps = {spec.name: spec.step.file if spec.step else None for spec, _ in detailed}
    assert steps == {"A": "3D/a.step", "B": "3D/b.step", "PLAIN": None}
    assert all(notes == [] for _, notes in detailed)
    assert spy.calls.count("extract_step_model") == 1
    spy.calls.clear()
    reader.read_all(lib)  # cached per library version
    assert "extract_step_model" not in spy.calls
    assert [s.step for s in reader.read_all(lib, extract_step=False) if s.name == "A"][0].file == "a.step"  # type: ignore[union-attr]


class CarrierKeepingClient(SpyClient):
    """Simulates a writer that cannot delete the temporary STEP carriers."""

    def call_tool(self, name, arguments, *, timeout=None):
        names = arguments.get("component_names") or []
        if name == "delete_component" and names and all(n.startswith("__PFSTEP_") for n in names):
            self.calls.append(name)
            return {"results": [{"name": n, "status": "error", "error": "locked"} for n in names]}
        return super().call_tool(name, arguments, timeout=timeout)


def test_leftover_step_carriers_roll_the_call_back(ws):
    write_step(ws.models_dir / "box.step")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_CARRIER.PcbLib"
    assert ops.upsert_footprints(lib, [chip_0603("A")]).ok
    before = _sha(lib)
    keeping = RustLibraryOps(client=CarrierKeepingClient(get_client()), workspace=ws)  # type: ignore[arg-type]
    result = keeping.upsert_footprints(lib, [chip_with_step("3D/box.step", name="S")])
    assert not result.ok and "STEP-Träger" in result.errors["S"]
    assert _sha(lib) == before
    raw = get_client().call_tool("list_components", {"filepath": _posix(lib)})["components"]
    assert raw == ["A"]  # no carrier left behind


def test_unreadable_embedded_step_is_dropped_with_a_note(ws):
    write_step(ws.models_dir / "box.step")
    ops = RustLibraryOps(workspace=ws)
    lib = ws.footprints_dir / "PF_BAD.PcbLib"
    assert ops.upsert_footprints(lib, [chip_with_step("3D/box.step", name="C1")]).ok
    failing = RustLibraryOps(client=SpyClient(get_client(), fail_on="extract_step_model"), workspace=ws)  # type: ignore[arg-type]
    notes: list[str] = []
    back = failing.read_footprint(lib, "C1", notes=notes)
    assert back is not None and back.step is None and len(back.bodies) == 1
    assert any("nicht lesbar" in n for n in notes)
