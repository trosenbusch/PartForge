"""Library sync with the real Rust writer (``altium-designer-mcp.exe``, marker ``rustwriter``)."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from test_sync_support import make_part
from test_writer_samples import chip_0603, ic8_symbol, resistor_symbol

from partforge.altium import libwriter, stackup, sync
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.db import parts, registry, seed_examples
from partforge.footprints import FootprintRequest
from partforge.footprints import generate as generate_footprint
from partforge.symbols import SymbolRequest
from partforge.symbols import generate as generate_symbol

pytestmark = pytest.mark.rustwriter


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture(autouse=True)
def _no_altium(monkeypatch):
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_sync_of_generated_libraries(workspace):
    seed_examples(workspace)
    summary = sync.sync_pending()
    assert summary["errors"] == [] and summary["missing"] == []
    assert summary["symbols"]["ok"] == summary["symbols"]["total"] > 0
    assert summary["footprints"]["ok"] == summary["footprints"]["total"] > 0
    ops = RustLibraryOps(workspace=workspace)
    for rec in registry.list_symbols():
        assert rec.status == "ok", (rec.name, rec.status_message)
        assert rec.name in ops.list_components(workspace.abs(rec.library))  # type: ignore[arg-type]
    stack = stackup.effective_stack(stackup.default_stack(), workspace.settings.layers)
    for rec in registry.list_footprints():
        assert rec.status == "ok", (rec.name, rec.status_message)
        lib = workspace.abs(rec.library)
        assert lib is not None and stackup.pcblib_layer_problems(lib, stack) == []
        if rec.step_file:
            assert (workspace.root / rec.step_file.replace("\\", "/")).is_file()
    files = sync.library_files()
    assert files and all(f.managed and f.in_sync for f in files)
    assert all(f.layers_ok for f in files if f.kind == "pcblib")
    # the parts of the examples point to the written libraries
    health = sync.library_health()
    assert [i for i in health["issues"] if i.severity == "error"] == []


def test_synced_footprints_carry_their_heights(workspace):
    """Regression (altium-e2e.md §6.2/Welle 3): Rust-written footprints had Height 0 in Altium.
    After the sync every footprint has its registry height, the height patch is PartForge's own
    write (no "changed outside"), and a later write keeps the heights of the other footprints."""
    from partforge.altium import heights

    seed_examples(workspace)
    assert sync.sync_pending()["errors"] == []
    records = registry.list_footprints()
    assert records

    def check() -> None:
        for rec in registry.list_footprints():
            lib = workspace.abs(rec.library)
            assert lib is not None and rec.spec is not None
            expected = heights.footprint_height(rec.spec)
            assert expected, rec.name
            stored = heights.read_footprint_heights(lib)[rec.name]
            assert heights.mm_to_coord(stored) == heights.mm_to_coord(expected), (rec.name, stored, expected)

    check()
    files = [f for f in sync.library_files() if f.kind == "pcblib"]
    assert files and all(f.managed and f.in_sync and not f.external_changes for f in files)
    added = chip_0603("RESC1608X55N_HT")
    added.height = 0.65
    assert sync.ensure_footprints([added])[0].status == "ok"  # same family file: PF_CHIP rewritten
    check()
    files = [f for f in sync.library_files() if f.kind == "pcblib"]
    assert all(f.managed and not f.external_changes for f in files)


def test_step_model_is_embedded_and_unchanged_files_are_kept(workspace):
    spec = generate_footprint(FootprintRequest(family="soic", params={"preset": "SOIC-8"}))
    rec = sync.ensure_footprints([spec])[0]
    assert rec.status == "ok" and rec.step_file
    lib = workspace.abs(rec.library)
    assert lib is not None
    read = RustLibraryOps(workspace=workspace).read_footprint(lib, spec.name)
    assert read is not None and read.step is not None and read.height == spec.height
    assert (workspace.root / read.step.file).is_file()
    digest = _sha(lib)
    again = sync.ensure_footprints([generate_footprint(FootprintRequest(family="soic", params={"preset": "SOIC-8"}))])
    assert again[0].status == "ok" and _sha(lib) == digest  # unchanged geometry: not rewritten


def test_managed_rewrite_and_foreign_components(workspace):
    ops = RustLibraryOps(workspace=workspace)
    a = generate_symbol(SymbolRequest(kind="resistor"))
    b = generate_symbol(SymbolRequest(kind="capacitor"))
    sync.ensure_symbols([a, b])
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    assert ops.list_components(lib) == ["Resistor", "Capacitor"]
    changed = a.model_copy(update={"description": "Widerstand, geändert"})
    assert sync.ensure_symbols([changed])[0].status == "ok"
    back = ops.read_symbol(lib, "Resistor")
    assert back is not None and back.description == "Widerstand, geändert"
    assert ops.list_components(lib) == ["Resistor", "Capacitor"]  # order kept by the full rewrite
    assert ops.upsert_symbols(lib, [resistor_symbol("USER_DRAWN")]).ok  # a component PartForge does not know
    libwriter.forget_component_names()
    c = generate_symbol(SymbolRequest(kind="inductor"))
    assert sync.ensure_symbols([c])[0].status == "ok"
    assert sorted(ops.list_components(lib)) == ["Capacitor", "Inductor", "Resistor", "USER_DRAWN"]


def test_pinout_change_refused_with_the_real_writer(workspace):
    spec = ic8_symbol("TIMER")
    spec.footprints = []
    sync.ensure_symbols([spec])
    lib = workspace.symbols_dir / "PF_ICs.SchLib"
    digest = _sha(lib)
    other = spec.model_copy(deep=True)
    other.pins[0].designator, other.pins[1].designator = other.pins[1].designator, other.pins[0].designator
    rec = sync.ensure_symbols([other])[0]
    assert rec.status == "error" and "Pinbelegung" in (rec.status_message or "")
    assert _sha(lib) == digest


def test_parts_relinked_and_deleted_with_the_real_writer(workspace):
    make_part("Resistors", "R-100", Library_Ref="Resistor", Footprint_Ref="RESC1608X50N")
    sync.ensure_symbols([generate_symbol(SymbolRequest(kind="resistor"))])
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    sync.ensure_footprints([fp, generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0805"}))])
    part = parts.get_part("Resistors", "R-100")
    assert part is not None and part["Library Path"] == "Symbols\\PF_Passives.SchLib"
    assert part["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"
    result = sync.delete_footprints(["RESC2012X60N", "RESC1608X50N"])
    assert result["deleted"] == ["RESC2012X60N"] and "RESC1608X50N" in result["refused"]
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    assert RustLibraryOps(workspace=workspace).list_components(lib) == ["RESC1608X50N"]
    assert stackup.pcblib_layer_problems(lib, stackup.effective_stack(stackup.default_stack(), workspace.settings.layers)) == []


def test_scan_finds_differences_in_real_files(workspace):
    sync.ensure_symbols([generate_symbol(SymbolRequest(kind="resistor")), generate_symbol(SymbolRequest(kind="capacitor"))])
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    ops = RustLibraryOps(workspace=workspace)
    assert ops.delete_components(lib, ["Capacitor"]).ok
    assert ops.upsert_symbols(lib, [resistor_symbol("HANDMADE")]).ok
    libwriter.forget_component_names()
    result = sync.scan_workspace(register=True)
    assert registry.get_symbol("Capacitor").status == "pending"  # type: ignore[union-attr]
    handmade = registry.get_symbol("HANDMADE")
    assert handmade is not None and handmade.source == "imported" and handmade.spec is not None
    assert result["registered"][0]["name"] == "HANDMADE"
    sync.sync_pending()
    assert sorted(ops.list_components(lib)) == ["Capacitor", "HANDMADE", "Resistor"]


def test_imported_footprint_with_embedded_step_stays_rewritable(workspace):
    from test_writer_samples import chip_with_step, write_step

    step = write_step(workspace.root / "Exports" / "vendor_box.step")
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    ops = RustLibraryOps(workspace=workspace)
    assert ops.write_library_full(lib, [chip_with_step(str(step))]).ok  # written outside PartForge's registry
    step.unlink()  # only the embedded copy is left
    libwriter.forget_component_names()
    result = sync.scan_workspace(register=True)
    assert result["registered"] == [{"kind": "footprint", "name": "CAPC2012X125N", "library": "Footprints\\PF_CHIP.PcbLib"}]
    rec = registry.get_footprint("CAPC2012X125N")
    assert rec is not None and rec.spec is not None and rec.spec.step is not None
    assert (workspace.root / rec.spec.step.file).is_file()  # extracted into the workspace 3D folder
    # an imported footprint is never regenerated from its read-back: a new one is added by upsert
    new = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    assert sync.ensure_footprints([new])[0].status == "ok"
    back = ops.read_footprint(lib, "CAPC2012X125N")
    assert back is not None and back.step is not None
    assert sorted(ops.list_components(lib)) == ["CAPC2012X125N", new.name]
    # saving it from PartForge (explicitly) writes it with its extracted model
    saved = sync.ensure_footprints([rec.spec.model_copy(update={"description": "neu"})])[0]
    assert saved.status == "ok"
    again = ops.read_footprint(lib, "CAPC2012X125N")
    assert again is not None and again.step is not None and again.description == "neu"


def _raw_footprint_with_unmapped_layer(workspace, lib: Path, name: str) -> list[str]:
    """Write a footprint with a track on Mechanical 5 (no LayerMap role) directly with the
    writer – PartForge's model cannot hold it. Returns the track layers in the file."""
    from partforge.altium.rustwriter import _posix, footprint_to_rust
    from partforge.footprints import chip_request

    ops = RustLibraryOps(workspace=workspace)
    spec = generate_footprint(chip_request("C", "0805")).model_copy(update={"name": name, "bodies": []})
    payload = footprint_to_rust(spec, workspace.settings.layers, workspace.settings.footprint)
    payload["tracks"].append({"x1": -1.0, "y1": -1.0, "x2": 1.0, "y2": 1.0, "width": 0.1, "layer": "Mechanical 5"})
    ops.client().call_tool("write_pcblib", {"filepath": _posix(lib), "append": lib.exists(), "footprints": [payload]})
    return _track_layers(workspace, lib, name)


def _track_layers(workspace, lib: Path, name: str) -> list[str]:
    from partforge.altium.rustwriter import _posix

    resp = RustLibraryOps(workspace=workspace).client().call_tool(
        "get_component", {"filepath": _posix(lib), "component_name": name}
    )
    component = resp.get("component") or resp
    return sorted({str(t.get("layer")) for t in component.get("tracks") or []})


def test_lossy_read_back_is_never_written_back(workspace):
    """Review finding: a full regeneration from read-back specs dropped content on unmapped layers."""
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    before = _raw_footprint_with_unmapped_layer(workspace, lib, "FOREIGN_C0805")
    assert {"Mechanical 5", "Bottom Courtyard"} & set(before)  # the reader names Mech 5 by its template name
    libwriter.forget_component_names()
    scan = sync.scan_workspace(register=True)
    assert [r["name"] for r in scan["registered"]] == ["FOREIGN_C0805"]
    imported = registry.get_footprint("FOREIGN_C0805")
    assert imported is not None and imported.source == "imported"
    assert "ginge verloren" in (imported.status_message or "")  # the read-back notes are kept
    warnings = sync.component_warnings(imported)
    assert warnings and "verloren" in warnings[0]
    chip = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    assert sync.ensure_footprints([chip])[0].status == "ok"
    assert _track_layers(workspace, lib, "FOREIGN_C0805") == before  # untouched
    assert sync.component_warnings(registry.get_footprint(chip.name)) == []  # type: ignore[arg-type]


def test_altium_edit_survives_and_same_name_is_adopted(workspace):
    ops = RustLibraryOps(workspace=workspace)
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    sync.ensure_symbols([generate_symbol(SymbolRequest(kind="resistor")), generate_symbol(SymbolRequest(kind="capacitor"))])
    edited = ops.read_symbol(lib, "Capacitor")
    assert edited is not None
    assert ops.upsert_symbols(lib, [edited.model_copy(update={"description": "in Altium geändert"})]).ok  # saved elsewhere
    libwriter.forget_component_names()
    info = next(i for i in sync.library_files(check_layers=False) if i.rel == "Symbols\\PF_Passives.SchLib")
    assert info.external_changes and not info.managed
    assert sync.ensure_symbols([generate_symbol(SymbolRequest(kind="inductor"))])[0].status == "ok"
    back = ops.read_symbol(lib, "Capacitor")
    assert back is not None and back.description == "in Altium geändert"  # not reverted
    # a component of the same name drawn by the user is adopted, never overwritten
    fp_lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    users = chip_0603("RESC1608X50N")
    users.description = "vom Benutzer"
    assert ops.write_library_full(fp_lib, [users]).ok
    libwriter.forget_component_names()
    digest = _sha(fp_lib)
    rec = sync.ensure_footprints([generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))])[0]
    assert rec.status == "ok" and rec.source == "imported" and _sha(fp_lib) == digest


def test_step_model_is_regenerated_after_a_body_edit(workspace):
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    rec = sync.ensure_footprints([spec])[0]
    step = workspace.abs(rec.step_file)
    assert step is not None
    first = step.read_text(encoding="ascii")
    stored = registry.get_footprint(spec.name).spec  # type: ignore[union-attr]
    assert stored is not None
    body = stored.bodies[0]
    taller = stored.model_copy(update={"bodies": [body.model_copy(update={"z_top": body.z_top + 1.0})],
                                       "height": (stored.height or 0) + 1.0})
    assert sync.ensure_footprints([taller])[0].status == "ok"
    assert step.read_text(encoding="ascii") != first
    back = RustLibraryOps(workspace=workspace).read_footprint(workspace.footprints_dir / "PF_CHIP.PcbLib", spec.name)
    assert back is not None and back.step is not None and back.height == taller.height


def test_managed_library_is_regenerated_in_one_call(workspace, monkeypatch):
    calls: list[str] = []
    original = RustLibraryOps.write_library_full

    def spy(self, library, specs):
        calls.append(Path(library).name)
        return original(self, library, specs)

    monkeypatch.setattr(RustLibraryOps, "write_library_full", spy)
    sync.ensure_symbols([generate_symbol(SymbolRequest(kind="resistor"))])
    sync.ensure_symbols([generate_symbol(SymbolRequest(kind="capacitor"))])
    assert calls == ["PF_Passives.SchLib", "PF_Passives.SchLib"]  # new file, then managed regeneration
    files = {i.rel: i for i in sync.library_files(check_layers=False)}
    assert files["Symbols\\PF_Passives.SchLib"].managed and files["Symbols\\PF_Passives.SchLib"].in_sync


def _external_library(tmp_path: Path, workspace) -> Path:
    """A writer-generated library outside the workspace (stands in for a vendor library)."""
    vendor_dir = tmp_path / "Hersteller"
    vendor_dir.mkdir()
    scratch = workspace.root / "Exports" / "Vendor.SchLib"
    ops = RustLibraryOps(workspace=workspace)
    assert ops.write_library_full(scratch, [resistor_symbol("VENDOR_R"), ic8_symbol("VENDOR_IC")]).ok
    target = vendor_dir / "Vendor.SchLib"
    target.write_bytes(scratch.read_bytes())
    scratch.unlink()
    return target


def test_external_library_is_read_but_never_written(workspace, tmp_path: Path):
    ext = _external_library(tmp_path, workspace)
    digest = _sha(ext)
    lib = sync.add_external_library(str(ext))
    page = sync.external_components(lib.id, previews=True)
    assert [c["name"] for c in page["components"]] == ["VENDOR_R", "VENDOR_IC"]
    assert all(c["svg"] and c["svg"].startswith("<svg") for c in page["components"])
    assert page["components"][1]["pin_count"] == 8
    rec = sync.use_external_component(lib.id, "VENDOR_IC")
    assert rec.source == "external" and rec.library == str(ext) and rec.spec is not None and len(rec.spec.pins) == 8
    make_part("Integrated Circuits", "NE555-EXT", Library_Ref="VENDOR_IC", Library_Path=str(ext))
    # nothing PartForge does may write the external file
    refused = sync.ensure_symbols([ic8_symbol("VENDOR_IC")])
    assert refused[0].status == "error"
    sync.sync_pending()
    sync.scan_workspace(register=True)
    assert sync.delete_symbols(["VENDOR_IC"], force=True)["unregistered"] == ["VENDOR_IC"]
    assert _sha(ext) == digest
    assert not list(ext.parent.glob("*.bak"))


NATIVE_EXAMPLES = Path(r"C:\Users\Public\Documents\Altium\AD22\Examples\Harness Demo MB\Libs")


@pytest.mark.skipif(not (NATIVE_EXAMPLES / "PCB2.PcbLib").is_file(), reason="Altium-Beispielbibliothek nicht installiert")
def test_native_altium_library_as_external_library(workspace, tmp_path: Path):
    copy = tmp_path / "Beispiele" / "PCB2.PcbLib"  # a copy: the installed example is never touched
    copy.parent.mkdir()
    shutil.copyfile(NATIVE_EXAMPLES / "PCB2.PcbLib", copy)
    digest = _sha(copy)
    lib = sync.add_external_library(str(copy))
    page = sync.external_components(lib.id, previews=True, limit=3)
    assert page["total"] == 6 and len(page["components"]) == 3
    assert all(c["kind"] == "footprint" for c in page["components"])
    assert page["components"][0]["svg"] and page["components"][0]["svg"].startswith("<svg")
    rec = sync.use_external_component(lib.id, "RESC3216X60X45ML15T20")
    assert rec.source == "external" and rec.library == str(copy) and rec.pad_count == 2
    sync.sync_pending()
    sync.scan_workspace()
    assert registry.get_footprint("RESC3216X60X45ML15T20").status == "ok"  # type: ignore[union-attr]
    assert _sha(copy) == digest
    assert sorted(p.name for p in copy.parent.iterdir()) == ["PCB2.PcbLib"]  # no .bak, no temp files


def test_scan_library_of_an_external_pcblib(workspace, tmp_path: Path):
    scratch = workspace.root / "Exports" / "Ext.PcbLib"
    assert RustLibraryOps(workspace=workspace).write_library_full(scratch, [chip_0603()]).ok
    ext = tmp_path / "Ext.PcbLib"
    ext.write_bytes(scratch.read_bytes())
    infos = sync.scan_library(ext)
    assert [(i.name, i.kind, i.pin_count) for i in infos] == [("RESC1608X55N", "footprint", 2)]
