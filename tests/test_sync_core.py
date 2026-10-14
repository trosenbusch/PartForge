"""Library sync engine (``partforge.altium.sync``) with an in-memory writer.

The writer is replaced by :class:`FakeWriter` and Altium by :class:`FakeBridge`, so these
tests are fast and deterministic; ``test_sync_rust.py`` repeats the important flows with
the real Rust writer.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_sync_support import FakeBridge, FakeWriter, make_part, synthetic_pcblib
from test_writer_samples import chip_0603, ic8_symbol, resistor_symbol

from partforge import events
from partforge.altium import libwriter, stackup, sync
from partforge.altium.bridge.core import BridgeError
from partforge.altium.libwriter import WriterUnavailable
from partforge.altium.rustwriter import RustWriterError
from partforge.config import AppSettings
from partforge.db import parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.footprints import FootprintRequest
from partforge.footprints import generate as generate_footprint
from partforge.geometry.model import Body3D, Point, SymbolSpec, SymPin, SymRect
from partforge.symbols import SymbolRequest
from partforge.symbols import generate as generate_symbol


@pytest.fixture
def fake(workspace, monkeypatch) -> FakeWriter:
    writer = FakeWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *args, **kwargs: writer)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    return writer


@pytest.fixture
def written():
    paths: list[list[str]] = []
    unsubscribe = events.subscribe(events.LIBRARIES_WRITTEN, lambda p: paths.append(list(p)))
    yield paths
    unsubscribe()


def _bridge(monkeypatch, bridge: FakeBridge) -> FakeBridge:
    monkeypatch.setattr(sync, "altium_bridge", lambda: bridge)
    return bridge


def _resistor() -> SymbolSpec:
    return generate_symbol(SymbolRequest(kind="resistor"))


# --------------------------------------------------------------------------- fingerprints / pin-out


def test_symbol_fingerprint_ignores_metadata():
    spec = _resistor()
    other = spec.model_copy(deep=True)
    other.generator = {"kind": "resistor", "version": 99}
    other.pins[0].group = "Versorgung"
    assert sync.symbol_fingerprint(spec) == sync.symbol_fingerprint(other)
    other.description = "neu"
    assert sync.symbol_fingerprint(spec) != sync.symbol_fingerprint(other)


def test_footprint_fingerprint_covers_geometry_not_metadata():
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    assert spec.generator and spec.generator["geometry_hash"]
    meta = spec.model_copy(update={"generator": {}, "parameters": {"x": "y"}, "family": "other", "ipc_name": "X"})
    assert sync.footprint_fingerprint(spec) == sync.footprint_fingerprint(meta)
    moved = spec.model_copy(deep=True)
    moved.pads[0].x += 0.01  # geometry_hash would change as well
    assert sync.footprint_fingerprint(spec) != sync.footprint_fingerprint(moved)
    renamed = spec.model_copy(update={"description": "anders"})
    assert sync.footprint_fingerprint(spec) != sync.footprint_fingerprint(renamed)


def test_pinout_changes():
    old = ic8_symbol()
    new = old.model_copy(deep=True)
    assert sync.pinout(old)["4"] == ("R\\E\\S\\E\\T\\", 1)
    assert sync.pinout_changes(old, new) == []
    new.pins[0].name = "TRIGGER"
    new.pins[1].part = 2
    new.pins.append(SymPin(designator="9", name="EP", x=0, y=-500, orientation="left"))
    del new.pins[2]
    changes = sync.pinout_changes(old, new)
    assert "Pins entfernt: 5" in changes
    assert "Pins hinzugefügt: 9" in changes
    assert "Pin 2: Name „TRIG“ → „TRIGGER“" in changes
    assert "Pin 6: Teil 1 → 2" in changes


# --------------------------------------------------------------------------- ensure: basics


def test_ensure_symbols_registers_and_writes(fake: FakeWriter, workspace, written):
    specs = [_resistor(), generate_symbol(SymbolRequest(kind="capacitor"))]
    records = sync.ensure_symbols(specs, category="Resistors")
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    assert [r.status for r in records] == ["ok", "ok"]
    assert all(r.library == "Symbols\\PF_Passives.SchLib" for r in records)
    assert fake.names(lib) == ["Resistor", "Capacitor"]
    assert fake.writes() == [("write_library_full", str(lib), ["Resistor", "Capacitor"])]  # new file: one call
    stored = registry.get_symbol("Resistor")
    assert stored is not None and stored.status == "ok" and stored.kind == "resistor" and stored.pin_count == 2
    assert stored.spec is not None and sync.symbol_fingerprint(stored.spec) == sync.symbol_fingerprint(specs[0])
    assert written == [[str(lib)]]


def test_unchanged_specs_are_not_rewritten(fake: FakeWriter, workspace, written):
    spec = _resistor()
    sync.ensure_symbols([spec])
    fake.calls.clear()
    written.clear()
    again = sync.ensure_symbols([spec.model_copy(deep=True)])
    assert again[0].status == "ok"
    assert fake.writes() == []
    assert written == []  # nothing written -> no event


def test_generator_metadata_change_updates_only_the_registry(fake: FakeWriter, workspace):
    spec = _resistor()
    sync.ensure_symbols([spec])
    fake.calls.clear()
    newer = spec.model_copy(deep=True)
    newer.generator = {**(spec.generator or {}), "version": 999}
    sync.ensure_symbols([newer])
    assert fake.writes() == []
    stored = registry.get_symbol(spec.name)
    assert stored is not None and stored.spec is not None and stored.spec.generator["version"] == 999  # type: ignore[index]


def test_component_missing_in_file_is_written_again(fake: FakeWriter, workspace):
    spec = _resistor()
    sync.ensure_symbols([spec])
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    fake.libs[fake.key(lib)].clear()
    fake._touch(lib)
    fake.calls.clear()
    sync.ensure_symbols([spec])
    assert fake.writes() and fake.names(lib) == ["Resistor"]


def test_changed_symbol_regenerates_the_managed_library(fake: FakeWriter, workspace):
    a, b = _resistor(), generate_symbol(SymbolRequest(kind="capacitor"))
    sync.ensure_symbols([a, b])
    fake.calls.clear()
    changed = a.model_copy(update={"description": "Widerstand (neu)"})
    records = sync.ensure_symbols([changed])
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    assert records[0].status == "ok"
    assert fake.writes() == [("write_library_full", str(lib), ["Resistor", "Capacitor"])]  # one call, file order
    assert fake.libs[fake.key(lib)]["Resistor"].description == "Widerstand (neu)"


def test_foreign_components_switch_to_upsert(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    fake.put(lib, [resistor_symbol("USER_OWN")])  # not registered: PartForge must not regenerate the file
    records = sync.ensure_symbols([_resistor()])
    assert records[0].status == "ok"
    assert fake.writes() == [("write_symbols", str(lib), ["Resistor"])]
    assert fake.names(lib) == ["USER_OWN", "Resistor"]


def test_pending_entries_of_a_library_are_written_with_it(fake: FakeWriter, workspace):
    registry.upsert_symbol(
        SymbolRecord(name="Capacitor", library="Symbols\\PF_Passives.SchLib", spec=generate_symbol(SymbolRequest(kind="capacitor")),
                     status="error", status_message="vorher fehlgeschlagen")
    )
    sync.ensure_symbols([_resistor()])
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    assert sorted(fake.names(lib)) == ["Capacitor", "Resistor"]
    cap = registry.get_symbol("Capacitor")
    assert cap is not None and cap.status == "ok" and cap.status_message is None


def test_existing_library_assignment_is_kept(fake: FakeWriter, workspace):
    spec = _resistor()
    sync.ensure_symbols([spec], category="Integrated Circuits")
    sync.ensure_symbols([spec.model_copy(update={"description": "x"})], category="Resistors")
    assert registry.get_symbol("Resistor").library == "Symbols\\PF_ICs.SchLib"  # type: ignore[union-attr]


def test_registry_spelling_of_names_wins(fake: FakeWriter, workspace):
    sync.ensure_symbols([_resistor()])
    records = sync.ensure_symbols([_resistor().model_copy(update={"name": "RESISTOR", "description": "neu"})])
    assert records[0].name == "Resistor"
    assert [r.name for r in registry.list_symbols()] == ["Resistor"]


# --------------------------------------------------------------------------- ensure: refusals and errors


def test_pinout_change_is_refused_without_confirmation(fake: FakeWriter, workspace):
    spec = _resistor()
    sync.ensure_symbols([spec])
    make_part("Resistors", "R-1", Library_Ref="Resistor")
    fake.calls.clear()
    swapped = spec.model_copy(deep=True)
    swapped.pins[0].name, swapped.pins[1].name = "B", "A"
    records = sync.ensure_symbols([swapped])
    rec = records[0]
    assert rec.status == "error"
    assert "existiert bereits mit anderer Pinbelegung" in (rec.status_message or "")
    assert "1 Bauteil verwendet es" in (rec.status_message or "")
    assert fake.writes() == []
    stored = registry.get_symbol("Resistor")
    assert stored is not None and stored.status == "ok"  # registry untouched
    assert stored.spec is not None and stored.spec.pins[0].name == spec.pins[0].name
    confirmed = sync.ensure_symbols([swapped], allow_pin_changes=True)
    assert confirmed[0].status == "ok" and fake.writes()


def test_invalid_spec_is_refused_and_not_registered(fake: FakeWriter, workspace):
    bad = resistor_symbol("BAD|NAME")
    off_grid = resistor_symbol("OFFGRID")
    off_grid.pins[0].x = -105
    records = sync.ensure_symbols([bad, off_grid, _resistor()])
    assert [r.status for r in records] == ["error", "error", "ok"]
    assert "ungültig" in (records[0].status_message or "")
    assert "10-mil-Raster" in (records[1].status_message or "")
    assert registry.get_symbol("OFFGRID") is None
    assert fake.writes()[0][2] == ["Resistor"]


def test_duplicate_names_in_one_request(fake: FakeWriter, workspace):
    a = _resistor()
    b = a.model_copy(update={"description": "andere Beschreibung"})
    records = sync.ensure_symbols([a, a.model_copy(deep=True), b])
    # one answer per requested spec: the identical repetition shares the first result
    assert [r.status for r in records] == ["ok", "ok", "error"]
    assert records[0].name == records[1].name == "Resistor"
    assert "mehrfach" in (records[2].status_message or "")
    assert registry.get_symbol("Resistor").spec.description == a.description  # type: ignore[union-attr]
    assert len(fake.writes()) == 1


def test_external_components_are_never_written(fake: FakeWriter, workspace, tmp_path: Path):
    registry.upsert_symbol(
        SymbolRecord(name="Resistor", library=str(tmp_path / "ext.SchLib"), source="external", status="ok")
    )
    records = sync.ensure_symbols([_resistor()])
    assert records[0].status == "error" and "externen Bibliothek" in (records[0].status_message or "")
    assert fake.writes() == []
    with pytest.raises(ValueError, match="externe"):
        sync.ensure_symbols([_resistor()], source="external")


def test_writer_unavailable_keeps_entries_pending(workspace, monkeypatch):
    def unavailable(*args, **kwargs):
        raise WriterUnavailable("Kein Bibliotheks-Writer verfügbar.")

    monkeypatch.setattr(sync, "get_writer", unavailable)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    records = sync.ensure_symbols([_resistor()])
    assert records[0].status == "pending" and "Kein Bibliotheks-Writer" in (records[0].status_message or "")
    assert "nächsten Synchronisieren" in (records[0].status_message or "")
    stored = registry.get_symbol("Resistor")
    assert stored is not None and stored.status == "pending" and stored.spec is not None  # desired state kept
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_resistor().model_copy(update={"description": "neu"})], strict=True)
    assert exc.value.status == 503 and exc.value.records[0].status == "pending"
    fake = FakeWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: fake)
    summary = sync.sync_pending()
    assert summary["symbols"]["ok"] == 1 and registry.get_symbol("Resistor").status == "ok"  # type: ignore[union-attr]


def test_writer_failure_and_exception(fake: FakeWriter, workspace):
    fake.errors = {"Resistor": "Prüfung nach dem Schreiben fehlgeschlagen. Der Vorgang wurde zurückgesetzt."}
    records = sync.ensure_symbols([_resistor()])
    assert records[0].status == "error" and "zurückgesetzt" in (records[0].status_message or "")
    fake.errors = {}
    fake.fail = RustWriterError("Der Rust-Writer meldet einen Fehler.")
    records = sync.ensure_symbols([generate_symbol(SymbolRequest(kind="capacitor"))])
    assert records[0].status == "error" and "Rust-Writer" in (records[0].status_message or "")
    assert registry.get_symbol("Capacitor").status == "error"  # type: ignore[union-attr]


# --------------------------------------------------------------------------- Altium


def test_open_and_modified_library_is_not_written(fake: FakeWriter, workspace, monkeypatch, written):
    sync.ensure_symbols([_resistor()])
    bridge = _bridge(monkeypatch, FakeBridge(open_=True, modified=True))
    fake.calls.clear()
    written.clear()
    records = sync.ensure_symbols([_resistor().model_copy(update={"description": "neu"})])
    assert records[0].status == "error"
    assert sync.ALTIUM_MODIFIED_MESSAGE in (records[0].status_message or "")
    assert fake.writes() == [] and written == []
    assert [c[0] for c in bridge.calls] == ["document_state"]
    stored = registry.get_symbol("Resistor")
    assert stored is not None and stored.status == "error" and stored.spec.description == "neu"  # type: ignore[union-attr]


def test_open_unmodified_library_is_reloaded(fake: FakeWriter, workspace, monkeypatch):
    sync.ensure_symbols([_resistor()])
    bridge = _bridge(monkeypatch, FakeBridge(open_=True, modified=False))
    records = sync.ensure_symbols([_resistor().model_copy(update={"description": "neu"})])
    assert records[0].status == "ok"
    lib = str(workspace.symbols_dir / "PF_Passives.SchLib")
    assert bridge.calls == [("document_state", lib), ("refresh_document", lib)]


def test_reload_respects_the_setting(fake: FakeWriter, workspace, monkeypatch):
    sync.ensure_symbols([_resistor()])
    settings = AppSettings()
    settings.altium.auto_reload_libraries = False
    monkeypatch.setattr(sync, "load_settings", lambda *a, **k: settings)
    bridge = _bridge(monkeypatch, FakeBridge(open_=True, modified=False))
    assert sync.ensure_symbols([_resistor().model_copy(update={"description": "neu"})])[0].status == "ok"
    assert [c[0] for c in bridge.calls] == ["document_state"]


def test_new_library_needs_no_altium_check(fake: FakeWriter, workspace, monkeypatch):
    bridge = _bridge(monkeypatch, FakeBridge(open_=True, modified=True))
    assert sync.ensure_symbols([_resistor()])[0].status == "ok"  # file did not exist -> cannot be open
    assert bridge.calls == []


def test_bridge_errors_do_not_block_writing(fake: FakeWriter, workspace, monkeypatch):
    sync.ensure_symbols([_resistor(), generate_symbol(SymbolRequest(kind="npn"))])

    class Broken(FakeBridge):
        def document_state(self, path):
            self.calls.append(("document_state", str(path)))
            raise BridgeError("Skript hängt")

    bridge = _bridge(monkeypatch, Broken())
    records = sync.ensure_symbols(
        [_resistor().model_copy(update={"description": "a"}), generate_symbol(SymbolRequest(kind="npn")).model_copy(update={"description": "b"})]
    )
    assert [r.status for r in records] == ["ok", "ok"]
    assert len(bridge.calls) == 1  # checks are switched off after the first failure


# --------------------------------------------------------------------------- parts and 3D


def test_parts_are_pointed_to_the_library(fake: FakeWriter, workspace):
    make_part("Resistors", "R-10K", Library_Ref="Resistor", Footprint_Ref="RESC1608X50N")
    sync.ensure_symbols([_resistor()])
    sync.ensure_footprints([generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))])
    part = parts.get_part("Resistors", "R-10K")
    assert part is not None
    assert part["Library Path"] == "Symbols\\PF_Passives.SchLib"
    assert part["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"


def test_sync_aligns_wrong_part_paths(fake: FakeWriter, workspace):
    sync.ensure_symbols([_resistor()])
    sync.ensure_footprints([chip_0603()])
    make_part("Resistors", "R-WRONG", Library_Ref="Resistor", Library_Path="Symbols\\PF_Alt.SchLib",
              Footprint_Ref="RESC1608X55N", Footprint_Path="Symbols\\PF_Passives.SchLib")
    make_part("Resistors", "R-RIGHT", Library_Ref="Resistor", Library_Path="Symbols\\PF_Passives.SchLib")
    issues = {(i.part_number, i.check) for i in sync.library_health()["issues"]}
    assert ("R-WRONG", "library_file_missing") in issues and ("R-WRONG", "component_not_in_file") in issues
    summary = sync.sync_pending()
    assert summary["relinked"] >= 1
    part = parts.get_part("Resistors", "R-WRONG")
    assert part is not None and part["Library Path"] == "Symbols\\PF_Passives.SchLib"
    assert part["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"
    assert [i for i in sync.library_health()["issues"] if i.part_number in ("R-WRONG", "R-RIGHT")] == []


def test_library_outside_the_workspace_is_relocated(fake: FakeWriter, workspace, tmp_path: Path):
    registry.upsert_symbol(SymbolRecord(name="Resistor", library=str(tmp_path / "old.SchLib"), status="pending"))
    make_part("Resistors", "R-1", Library_Ref="Resistor", Library_Path=str(tmp_path / "old.SchLib"))
    records = sync.ensure_symbols([_resistor()])
    assert records[0].library == "Symbols\\PF_Passives.SchLib"
    assert parts.get_part("Resistors", "R-1")["Library Path"] == "Symbols\\PF_Passives.SchLib"  # type: ignore[index]


def test_footprint_bodies_get_a_step_file(fake: FakeWriter, workspace):
    spec = generate_footprint(FootprintRequest(family="soic", params={"preset": "SOIC-8"}))
    assert spec.bodies and spec.step is None
    records = sync.ensure_footprints([spec])
    rec = records[0]
    assert rec.status == "ok" and rec.step_file == f"3D\\{spec.name}.step"
    step = workspace.root / "3D" / f"{spec.name}.step"
    assert step.is_file() and "PartForge 3D model of" in step.read_text(encoding="ascii")
    written_spec = fake.read_footprint(workspace.footprints_dir / "PF_GULLWING.PcbLib", spec.name) or fake.read_footprint(
        workspace.footprints_dir / "PF_SOIC.PcbLib", spec.name
    )
    assert written_spec is not None and written_spec.step is not None and written_spec.step.file == rec.step_file
    fake.calls.clear()
    assert sync.ensure_footprints([spec])[0].status == "ok"
    assert fake.writes() == []  # unchanged incl. the attached STEP model


def test_vendor_step_file_is_never_overwritten(fake: FakeWriter, workspace):
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "C-0805"}))
    vendor = workspace.models_dir / f"{spec.name}.step"
    vendor.write_text("ISO-10303-21; vendor model", encoding="ascii")
    rec = sync.ensure_footprints([spec])[0]
    assert vendor.read_text(encoding="ascii") == "ISO-10303-21; vendor model"
    assert rec.step_file == f"3D\\{spec.name}_PF.step"


def test_missing_step_model_is_regenerated(fake: FakeWriter, workspace):
    first = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    second = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0805"}))
    sync.ensure_footprints([first])
    step = workspace.models_dir / f"{first.name}.step"
    step.unlink()
    sync.ensure_footprints([second])  # full rewrite of PF_CHIP needs the first STEP again
    assert step.is_file()


def test_library_of_an_older_version_is_never_regenerated_silently(fake: FakeWriter, workspace):
    old = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    fake.put(lib, [old])  # registered earlier without a STEP model (an older version, no library manifest)
    registry.upsert_footprint(FootprintRecord(name=old.name, library="Footprints\\PF_CHIP.PcbLib", spec=old, status="ok"))
    in_file = fake.read_footprint(lib, old.name)
    newer = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0805"}))
    sync.ensure_footprints([newer])
    assert fake.writes()[-1] == ("write_footprints", str(lib), [newer.name])  # upsert: the old one is not rewritten
    assert fake.read_footprint(lib, old.name) is in_file
    # saving the old footprint itself writes it (with its STEP model) – it is PartForge's own (registered "ok")
    stored = registry.get_footprint(old.name)
    assert stored is not None and stored.spec is not None
    rec = sync.ensure_footprints([stored.spec.model_copy(update={"description": "neu"})])[0]
    assert rec.status == "ok" and rec.step_file == f"3D\\{old.name}.step"
    assert fake.read_footprint(lib, old.name).step is not None  # type: ignore[union-attr]
    fake.calls.clear()
    sync.ensure_footprints([registry.get_footprint(old.name).spec])  # type: ignore[union-attr]
    assert fake.writes() == []  # registry and file agree now: no further rewrite


def test_footprint_without_bodies_has_no_step(fake: FakeWriter, workspace):
    spec = chip_0603("NOBODY")
    spec.bodies = []
    rec = sync.ensure_footprints([spec])[0]
    assert rec.status == "ok" and rec.step_file is None


# --------------------------------------------------------------------------- pending / hints


def test_sync_pending_generates_from_hints(fake: FakeWriter, workspace):
    registry.upsert_symbols(
        [
            SymbolRecord(name="Widerstand", library="Symbols\\PF_Passives.SchLib", kind="resistor"),
            SymbolRecord(name="Schottky Diode", library="Symbols\\PF_Diodes.SchLib", kind="diode_schottky"),
            SymbolRecord(name="Raetsel", library="Symbols\\PF_Misc.SchLib", kind="flux_capacitor"),
            SymbolRecord(name="MyIC", library="Symbols\\PF_ICs.SchLib", kind="ic"),
        ]
    )
    registry.upsert_footprints(
        [
            FootprintRecord(name="RESC1608X55N", library="Footprints\\PF_CHIP.PcbLib", family="chip",
                            ipc_name="RESC1608X55N", pad_count=2),
            FootprintRecord(name="SOT95P280X145-5N", library="Footprints\\PF_SOT23.PcbLib", family="sot23", pad_count=5),
            FootprintRecord(name="ODD_THING", library="Footprints\\PF_MISC.PcbLib", family="chip"),
        ]
    )
    summary = sync.sync_pending()
    assert summary["symbols"] == {"total": 4, "ok": 2, "error": 0, "missing": 2, "adopted": 0}
    assert summary["footprints"] == {"total": 3, "ok": 2, "error": 0, "missing": 1, "adopted": 0}
    res = registry.get_symbol("Widerstand")  # custom name: a resistor has one pin-out only
    assert res is not None and res.status == "ok" and res.spec is not None and res.spec.name == "Widerstand"
    schottky = registry.get_symbol("Schottky Diode")
    assert schottky is not None and schottky.status == "ok" and schottky.kind == "schottky"
    assert schottky.spec is not None and sync.pinout(schottky.spec) == {"1": ("K", 1), "2": ("A", 1)}
    odd = registry.get_symbol("Raetsel")
    assert odd is not None and odd.status == "missing" and "unbekannt" in (odd.status_message or "")
    ic = registry.get_symbol("MyIC")
    assert ic is not None and ic.status == "missing" and "Pinliste" in (ic.status_message or "")
    chip = registry.get_footprint("RESC1608X55N")
    assert chip is not None and chip.status == "ok" and chip.spec is not None and chip.spec.ipc_name == "RESC1608X55N"
    assert chip.spec.height == 0.55 and chip.step_file == "3D\\RESC1608X55N.step"
    assert registry.get_footprint("SOT95P280X145-5N").status == "ok"  # type: ignore[union-attr]
    missing = registry.get_footprint("ODD_THING")
    assert missing is not None and missing.status == "missing" and "Familie chip" in (missing.status_message or "")
    assert {m["name"] for m in summary["missing"]} == {"Raetsel", "MyIC", "ODD_THING"}
    assert sorted(Path(p).name for p in summary["libraries"]) == [
        "PF_CHIP.PcbLib", "PF_Diodes.SchLib", "PF_Passives.SchLib", "PF_SOT23.PcbLib"
    ]


def test_sync_pending_adopts_a_component_that_already_exists(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    own = resistor_symbol("Resistor")
    own.description = "vom Benutzer gezeichnet"
    fake.put(lib, [own])
    registry.upsert_symbol(SymbolRecord(name="Resistor", library="Symbols\\PF_Passives.SchLib", kind="resistor"))
    fake.calls.clear()
    summary = sync.sync_pending()
    assert summary["symbols"]["adopted"] == 1 and fake.writes() == []
    stored = registry.get_symbol("Resistor")
    assert stored is not None and stored.status == "ok" and stored.spec.description == "vom Benutzer gezeichnet"  # type: ignore[union-attr]


def test_sync_pending_keeps_source_and_retries_errors(fake: FakeWriter, workspace):
    spec = _resistor()
    registry.upsert_symbol(SymbolRecord(name=spec.name, library="Symbols\\PF_Passives.SchLib", source="datasheet", spec=spec,
                                        status="error", status_message="alt"))
    sync.sync_pending()
    stored = registry.get_symbol(spec.name)
    assert stored is not None and stored.status == "ok" and stored.source == "datasheet"


def test_footprint_hints_for_presets_and_density(fake: FakeWriter, workspace):
    from partforge.altium.sync import _footprint_from_hints

    rec = FootprintRecord(name="SOIC127P600X175-8N", library="", family="soic", pad_count=8)
    spec, reason = _footprint_from_hints(workspace, rec)
    assert spec is not None and reason is None and len(spec.pads) == 8
    wrong_pads = FootprintRecord(name="SOIC127P600X175-8N", library="", family="soic", pad_count=9)
    assert _footprint_from_hints(workspace, wrong_pads)[0] is None
    least = FootprintRecord(name="RESC1608X50L", library="", family="chip")
    spec, _ = _footprint_from_hints(workspace, least)
    assert spec is not None and spec.density == "L"


# --------------------------------------------------------------------------- delete


def test_delete_refuses_used_symbols_unless_forced(fake: FakeWriter, workspace, written):
    sync.ensure_symbols([_resistor(), generate_symbol(SymbolRequest(kind="capacitor"))])
    make_part("Resistors", "R-1", Library_Ref="Resistor")
    written.clear()
    result = sync.delete_symbols(["Resistor", "Capacitor", "Unbekannt"])
    assert result["deleted"] == ["Capacitor"] and "Resistor" in result["refused"] and result["not_found"] == ["Unbekannt"]
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    assert fake.names(lib) == ["Resistor"] and registry.get_symbol("Capacitor") is None
    assert written == [[str(lib)]]
    forced = sync.delete_symbols(["Resistor"], force=True)
    assert forced["deleted"] == ["Resistor"] and fake.names(lib) == []


def test_delete_external_only_unregisters(fake: FakeWriter, workspace, tmp_path: Path):
    ext = tmp_path / "ext.PcbLib"
    ext.write_bytes(b"external")
    registry.upsert_footprint(FootprintRecord(name="EXT_FP", library=str(ext), source="external", status="ok"))
    result = sync.delete_footprints(["EXT_FP"])
    assert result["unregistered"] == ["EXT_FP"] and fake.writes() == []
    assert ext.read_bytes() == b"external"


def test_delete_respects_altium(fake: FakeWriter, workspace, monkeypatch):
    sync.ensure_symbols([_resistor()])
    _bridge(monkeypatch, FakeBridge(open_=True, modified=True))
    result = sync.delete_symbols(["Resistor"])
    assert sync.ALTIUM_MODIFIED_MESSAGE in result["errors"]["Resistor"]
    assert registry.get_symbol("Resistor") is not None


# --------------------------------------------------------------------------- files, scan, health


def test_library_files_report(fake: FakeWriter, workspace):
    sync.ensure_symbols([_resistor()])
    sync.ensure_footprints([chip_0603()])
    passives = workspace.symbols_dir / "PF_Passives.SchLib"
    fake.put(passives, [resistor_symbol("FOREIGN")])
    registry.upsert_symbol(SymbolRecord(name="Ghost", library="Symbols\\PF_Ghost.SchLib", status="ok"))
    (workspace.symbols_dir / "PF_Passives.pf0123abcd.SchLib").write_bytes(b"temp")
    infos = {i.rel: i for i in sync.library_files(check_layers=False)}
    assert set(infos) == {"Symbols\\PF_Passives.SchLib", "Footprints\\PF_CHIP.PcbLib", "Symbols\\PF_Ghost.SchLib"}
    p = infos["Symbols\\PF_Passives.SchLib"]
    assert p.components == 2 and p.registered == 1 and p.unregistered == ["FOREIGN"] and not p.managed and not p.in_sync
    chip = infos["Footprints\\PF_CHIP.PcbLib"]
    assert chip.kind == "pcblib" and chip.managed and chip.in_sync and chip.size and chip.modified
    ghost = infos["Symbols\\PF_Ghost.SchLib"]
    assert not ghost.exists and ghost.missing == ["Ghost"] and "fehlt" in (ghost.message or "")


def test_scan_updates_statuses_and_registers(fake: FakeWriter, workspace):
    sync.ensure_symbols([_resistor(), generate_symbol(SymbolRequest(kind="capacitor"))])
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    del fake.libs[fake.key(lib)]["Capacitor"]
    fake.put(lib, [resistor_symbol("FOREIGN")])
    result = sync.scan_workspace()
    assert {"kind": "symbol", "name": "FOREIGN", "library": "Symbols\\PF_Passives.SchLib"} in result["unregistered"]
    cap = registry.get_symbol("Capacitor")
    assert cap is not None and cap.status == "pending" and "neu geschrieben" in (cap.status_message or "")
    assert registry.get_symbol("FOREIGN") is None
    result = sync.scan_workspace(register=True)
    foreign = registry.get_symbol("FOREIGN")
    assert foreign is not None and foreign.source == "imported" and foreign.status == "ok" and foreign.spec is not None
    assert result["registered"] == [{"kind": "symbol", "name": "FOREIGN", "library": "Symbols\\PF_Passives.SchLib"}]
    sync.sync_pending()
    assert registry.get_symbol("Capacitor").status == "ok"  # type: ignore[union-attr]
    registry.set_symbol_status("Capacitor", "missing", "x")
    sync.scan_workspace()
    assert registry.get_symbol("Capacitor").status == "ok"  # type: ignore[union-attr]


def test_scan_never_moves_a_name_registered_elsewhere(fake: FakeWriter, workspace):
    sync.ensure_symbols([_resistor()])  # registered in PF_Passives
    other = workspace.symbols_dir / "PF_Copy.SchLib"
    fake.put(other, [resistor_symbol("Resistor"), resistor_symbol("ONLY_HERE")])
    result = sync.scan_workspace(register=True)
    assert [c["name"] for c in result["conflicts"]] == ["Resistor"]
    assert "registriert ist es aber in Symbols\\PF_Passives.SchLib" in result["conflicts"][0]["message"]
    assert [r["name"] for r in result["registered"]] == ["ONLY_HERE"]
    assert registry.get_symbol("Resistor").library == "Symbols\\PF_Passives.SchLib"  # type: ignore[union-attr]


def test_delete_footprint_removes_only_orphaned_partforge_step_models(fake: FakeWriter, workspace):
    a = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    b = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0805"}))
    sync.ensure_footprints([a, b])
    step_a = workspace.models_dir / f"{a.name}.step"
    step_b = workspace.models_dir / f"{b.name}.step"
    # another footprint shares b's model -> it must stay
    shared = chip_0603("SHARES_B")
    registry.upsert_footprint(FootprintRecord(name="SHARES_B", library="Footprints\\PF_X.PcbLib", spec=shared,
                                              step_file=f"3D\\{b.name}.step", status="pending"))
    assert sync.delete_footprints([a.name, b.name])["deleted"] == [a.name, b.name]
    assert not step_a.exists() and step_b.exists()
    vendor_spec = chip_0603("VENDOR_FP")
    vendor_step = workspace.models_dir / "vendor.step"
    vendor_step.write_text("ISO-10303-21; vendor", encoding="ascii")
    registry.upsert_footprint(FootprintRecord(name="VENDOR_FP", library="Footprints\\PF_CHIP.PcbLib", spec=vendor_spec,
                                              step_file="3D\\vendor.step", status="ok"))
    fake.put(workspace.footprints_dir / "PF_CHIP.PcbLib", [vendor_spec])
    assert sync.delete_footprints(["VENDOR_FP"])["deleted"] == ["VENDOR_FP"]
    assert vendor_step.exists()  # not written by PartForge: never deleted


def test_delete_never_writes_a_registered_external_library(fake: FakeWriter, workspace):
    ext = workspace.root / "Hersteller" / "Vendor.SchLib"
    fake.put(ext, [resistor_symbol("VENDOR_R")])
    sync.add_external_library(str(ext))
    registry.upsert_symbol(SymbolRecord(name="VENDOR_R", library="Hersteller\\Vendor.SchLib", status="ok"))  # not marked external
    fake.calls.clear()
    result = sync.delete_symbols(["VENDOR_R"])
    assert result["unregistered"] == ["VENDOR_R"] and fake.writes() == []
    assert fake.names(ext) == ["VENDOR_R"]


def test_scan_checks_external_components(fake: FakeWriter, workspace, tmp_path: Path):
    ext = tmp_path / "ext.SchLib"
    fake.put(ext, [resistor_symbol("EXT_A")])
    registry.upsert_symbol(SymbolRecord(name="EXT_A", library=str(ext), source="external", status="ok"))
    registry.upsert_symbol(SymbolRecord(name="EXT_B", library=str(ext), source="external", status="ok"))
    result = sync.scan_workspace()
    assert [m["name"] for m in result["external_missing"]] == ["EXT_B"]
    assert registry.get_symbol("EXT_B").status == "missing"  # type: ignore[union-attr]
    assert registry.get_symbol("EXT_A").status == "ok"  # type: ignore[union-attr]


def test_library_health(fake: FakeWriter, workspace):
    sym = ic8_symbol("TIMER")
    sym.footprints = []
    sync.ensure_symbols([sym])
    sync.ensure_footprints([chip_0603()])  # 2 pads vs 8 pins
    make_part("Integrated Circuits", "NE555", Library_Ref="TIMER", Footprint_Ref="RESC1608X55N")
    make_part("Integrated Circuits", "NE556", Library_Ref="TIMER", Footprint_Ref="RESC1608X55N")
    make_part("Integrated Circuits", "BROKEN", Library_Ref="TIMER", Library_Path="Symbols\\PF_Nowhere.SchLib")
    make_part("Integrated Circuits", "WRONG", Library_Ref="TIMER", Library_Path="Footprints\\PF_CHIP.PcbLib")
    registry.upsert_symbol(SymbolRecord(name="LOST", library="Symbols\\PF_Lost.SchLib", status="ok"))
    report = sync.library_health()
    by_check: dict[str, list] = {}
    for issue in report["issues"]:
        by_check.setdefault(issue.check, []).append(issue)
    mismatch = by_check["pin_pad_mismatch"]
    assert len(mismatch) == 1 and "Pins ohne Pad" in mismatch[0].message and "1 weitere" in mismatch[0].message
    assert by_check["library_file_missing"][0].part_number in ("BROKEN", None)
    assert any(i.part_number == "WRONG" for i in by_check["component_not_in_file"])
    assert any("LOST" in i.message for i in by_check["library_file_missing"])
    assert report["checked_parts"] == 4 and report["counts"]["error"] >= 2


# --------------------------------------------------------------------------- external libraries


@pytest.mark.windows
def test_external_library_registration_and_use(fake: FakeWriter, workspace, tmp_path: Path):
    ext = tmp_path / "Hersteller" / "Vendor.SchLib"
    fake.put(ext, [resistor_symbol("VENDOR_R"), ic8_symbol("VENDOR_IC"), resistor_symbol("Resistor")])
    lib = sync.add_external_library(str(ext))
    assert lib.kind == "schlib" and lib.name == "Vendor.SchLib" and lib.exists
    assert sync.add_external_library(f'"{ext}"').id == lib.id  # quoted path, no duplicate
    stored = json.loads((workspace.root / sync.EXTERNAL_FILE).read_text(encoding="utf-8"))
    assert [e["path"] for e in stored["libraries"]] == [str(ext)]
    page = sync.external_components(lib.id, previews=True, search="vendor")
    assert page["total"] == 2 and [c["name"] for c in page["components"]] == ["VENDOR_R", "VENDOR_IC"]
    assert page["components"][0]["svg"].startswith("<svg")
    rec = sync.use_external_component(lib.id, "vendor_ic")
    assert rec.name == "VENDOR_IC" and rec.source == "external" and rec.library == str(ext) and rec.spec is not None
    assert sync.use_external_component(lib.id, "VENDOR_IC").name == "VENDOR_IC"  # idempotent
    sync.ensure_symbols([_resistor()])
    with pytest.raises(sync.SyncError, match="bereits als Symbol registriert") as exc:
        sync.use_external_component(lib.id, "Resistor")
    assert exc.value.status == 409
    listed = sync.list_external_libraries()
    assert listed[0].registered == 1
    assert sync.external_components(lib.id)["components"][2]["conflict"] is True
    removed = sync.remove_external_library(lib.id)
    assert removed["registered_components"] == ["VENDOR_IC"]
    assert sync.list_external_libraries() == []
    assert fake.writes() == [("write_library_full", str(workspace.symbols_dir / "PF_Passives.SchLib"), ["Resistor"])]


def test_external_library_errors(fake: FakeWriter, workspace, tmp_path: Path):
    with pytest.raises(sync.SyncError, match="absolut"):
        sync.add_external_library("relativ.SchLib")
    with pytest.raises(sync.SyncError, match="keine Altium-Bibliothek"):
        sync.add_external_library(str(tmp_path / "x.txt"))
    with pytest.raises(sync.SyncError, match="nicht gefunden") as exc:
        sync.add_external_library(str(tmp_path / "fehlt.PcbLib"))
    assert exc.value.status == 404
    inside = workspace.symbols_dir / "Own.SchLib"
    fake.put(inside, [resistor_symbol("X")])
    with pytest.raises(sync.SyncError, match="Bibliotheksordner"):
        sync.add_external_library(str(inside))
    with pytest.raises(sync.SyncError, match="nicht gefunden"):
        sync.get_external_library("0123456789ab")
    with pytest.raises(sync.SyncError):
        sync.remove_external_library("0123456789ab")
    ext = tmp_path / "e.PcbLib"
    fake.put(ext, [chip_0603()])
    lib = sync.add_external_library(str(ext))
    with pytest.raises(sync.SyncError, match="nicht in e.PcbLib enthalten"):
        sync.use_external_component(lib.id, "NOPE")
    rec = sync.use_external_component(lib.id, "RESC1608X55N")
    assert isinstance(rec, FootprintRecord) and rec.pad_count == 2
    ext.unlink()
    assert sync.list_external_libraries()[0].exists is False
    with pytest.raises(sync.SyncError, match="existiert nicht mehr"):
        sync.external_components(lib.id)


def test_scan_library_errors(fake: FakeWriter, workspace, tmp_path: Path):
    with pytest.raises(sync.SyncError, match="keine Altium-Bibliothek"):
        sync.scan_library(tmp_path / "x.doc")
    with pytest.raises(sync.SyncError, match="nicht gefunden"):
        sync.scan_library(tmp_path / "x.SchLib")
    lib = tmp_path / "ok.SchLib"
    fake.put(lib, [resistor_symbol("A")])
    assert [c.name for c in sync.scan_library(lib)] == ["A"]


# --------------------------------------------------------------------------- layer stack job, helpers


@pytest.mark.windows
def test_apply_layer_stack_patches_workspace_pcblibs(fake: FakeWriter, workspace, written):
    path = synthetic_pcblib(workspace.footprints_dir / "PF_OLD.PcbLib")
    result = sync.apply_layer_stack()
    assert result["patched"] == [str(path)] and result["warnings"] == []
    eff = stackup.effective_stack(stackup.default_stack(), workspace.settings.layers)
    assert stackup.pcblib_layer_problems(path, eff) == []
    assert written == [[str(path)]]
    again = sync.apply_layer_stack()
    assert again["unchanged"] == [str(path)] and again["patched"] == []


@pytest.mark.windows
def test_altium_backend_pcblibs_get_the_layer_stack(workspace, monkeypatch):
    class AltiumFake(FakeWriter):
        name = "altium"
        reader = object()  # has a reader: cheap listings like the real Altium backend with Rust reader

    writer = AltiumFake(compound=True)
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    rec = sync.ensure_footprints([chip_0603()])[0]
    assert rec.status == "ok"
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    eff = stackup.effective_stack(stackup.default_stack(), workspace.settings.layers)
    assert stackup.pcblib_layer_problems(lib, eff) == []
    sync.ensure_footprints([chip_0603("SECOND")])
    assert sync.delete_footprints(["SECOND"])["deleted"] == ["SECOND"]
    assert stackup.pcblib_layer_problems(lib, eff) == []  # patched again after the rebuild


@pytest.mark.windows
def test_apply_layer_stack_switched_off(fake: FakeWriter, workspace, monkeypatch):
    synthetic_pcblib(workspace.footprints_dir / "PF_OLD.PcbLib")
    monkeypatch.setattr(stackup, "HEADER_PATCH_ENABLED", False)
    result = sync.apply_layer_stack()
    assert result["patched"] == [] and "abgeschaltet" in result["warnings"][0]


@pytest.mark.windows
def test_validate_planned_library_and_slow_writes(fake: FakeWriter, workspace, monkeypatch, tmp_path):
    assert sync.validate_spec(_resistor()) == []
    assert sync.validate_spec(resistor_symbol("A|B"))
    spec = _resistor()
    assert sync.planned_library(spec) == workspace.symbols_dir / "PF_Passives.SchLib"
    assert sync.planned_library(spec, category="Integrated Circuits") == workspace.symbols_dir / "PF_ICs.SchLib"
    assert sync.planned_library(chip_0603()) == workspace.footprints_dir / "PF_CHIP.PcbLib"
    settings = AppSettings()
    writer_exe = tmp_path / "altium-designer-mcp.exe"  # a configured writer must be a local .exe
    writer_exe.write_bytes(b"MZ")
    settings.altium.rust_writer_path = str(writer_exe)
    monkeypatch.setattr(sync, "load_settings", lambda *a, **k: settings)
    assert sync.write_is_slow(spec) is False
    fake.put(workspace.symbols_dir / "PF_Passives.SchLib", [resistor_symbol(f"R{i}") for i in range(61)])
    assert sync.write_is_slow(spec) is True
    _bridge(monkeypatch, FakeBridge())
    assert sync.write_is_slow(chip_0603()) is True
    settings.altium.library_backend = "altium"
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    assert sync.write_is_slow(chip_0603()) is True


def test_job_context_progress_log_and_cancellation(fake: FakeWriter, workspace, written):
    from partforge.jobs import JobCancelled, jobs

    seen: list[str] = []

    def run(ctx):
        def cancel_after_first(fraction=None, message=None):
            seen.append(message or "")
            ctx.job.cancel_requested = True  # user presses cancel while the first library is written

        ctx.progress = cancel_after_first  # type: ignore[method-assign]
        return sync.ensure_symbols([_resistor(), generate_symbol(SymbolRequest(kind="npn"))], ctx=ctx)

    job = jobs.run_sync("test", "Abbruch", run)
    assert job.status == "cancelled"
    assert seen == ["PF_Passives.SchLib …"]
    # the first library is complete and registered, the event names it
    assert [Path(p).name for paths in written for p in paths] == ["PF_Passives.SchLib"]
    assert registry.get_symbol("Resistor").status == "ok"  # type: ignore[union-attr]
    assert registry.get_symbol("NPN") is None
    ok = jobs.run_sync("test", "Lauf", lambda ctx: sync.ensure_symbols([generate_symbol(SymbolRequest(kind="npn"))], ctx=ctx))
    assert ok.status == "done" and any("geschrieben" in entry["text"] for entry in ok.log)
    assert JobCancelled  # imported for clarity of the scenario


def test_progress_messages_count_properly(fake: FakeWriter, workspace):
    """Regression: the step message read „Footprinte fertig“ – now „Footprints geschrieben: 1“ (proper plurals)."""
    from partforge.jobs import jobs

    first = jobs.run_sync("test", "FP", lambda ctx: sync.ensure_footprints([chip_0603()], ctx=ctx))
    assert first.message == "Footprints geschrieben: 1"
    assert any(entry["text"] == "PF_CHIP.PcbLib: 1 Footprint geschrieben" for entry in first.log)
    again = jobs.run_sync("test", "FP", lambda ctx: sync.ensure_footprints([chip_0603()], ctx=ctx))
    assert again.message == "Footprints geschrieben: 0 (1 unverändert)"
    syms = jobs.run_sync("test", "SYM", lambda ctx: sync.ensure_symbols(
        [_resistor(), resistor_symbol("A|B")], ctx=ctx))
    assert syms.message == "Symbole geschrieben: 1 (1 mit Fehler)"
    make_part("Resistors", "R-1", Library_Ref="Resistor")
    make_part("Resistors", "R-2", Library_Ref="Resistor")
    rec = sync.delete_symbols(["Resistor"])
    assert rec["refused"]["Resistor"] == "Symbol „Resistor“ wird von 2 Bauteilen verwendet und wird daher nicht gelöscht."


@pytest.mark.windows
def test_scan_and_layer_jobs_end_with_an_outcome(fake: FakeWriter, workspace):
    from partforge.jobs import jobs

    sync.ensure_symbols([_resistor()])
    clean = jobs.run_sync("libraries.scan", "Prüfen", lambda ctx: sync.scan_workspace(ctx))
    assert clean.message == "Bibliotheken geprüft: 1 Datei, alles stimmt mit der Registrierung überein."
    fake.put(workspace.symbols_dir / "PF_Passives.SchLib", [resistor_symbol("FOREIGN")])  # drawn outside PartForge
    scan = jobs.run_sync("libraries.scan", "Prüfen", lambda ctx: sync.scan_workspace(ctx))
    assert scan.message == "Bibliotheken geprüft: 1 Datei – 1 unbekanntes Bauteil, 1 Datei außerhalb geändert."
    taken = jobs.run_sync("libraries.scan", "Prüfen", lambda ctx: sync.scan_workspace(ctx, register=True))
    assert taken.message == "Bibliotheken geprüft: 1 Datei – 1 Bauteil übernommen, 1 Datei außerhalb geändert."
    synthetic_pcblib(workspace.footprints_dir / "PF_OLD.PcbLib")
    layers = jobs.run_sync("libraries.layers", "Lagen", lambda ctx: sync.apply_layer_stack(ctx))
    assert layers.message == "Lagen-Kopf angepasst: 1 Footprint-Bibliothek."
    again = jobs.run_sync("libraries.layers", "Lagen", lambda ctx: sync.apply_layer_stack(ctx))
    assert again.message == "Lagen-Köpfe sind aktuell (1 Footprint-Bibliothek)."
    assert sync.layers_message({"patched": ["a", "b"], "unchanged": ["c"], "skipped": [{"path": "d"}]}) == (
        "Lagen-Kopf angepasst: 2 Footprint-Bibliotheken (1 unverändert, 1 übersprungen)."
    )
    assert sync.layers_message({}) == "Keine Footprint-Bibliothek vorhanden – nichts anzupassen."


def test_altium_bridge_is_never_used_in_tests():
    assert sync.altium_bridge() is None  # pytest without PARTFORGE_TEST_ALTIUM=1


def test_symbol_kind_resolution():
    from partforge.altium.sync import _resolve_symbol_kind

    assert _resolve_symbol_kind(SymbolRecord(name="X", library="", kind="diode_zener")) == "zener"
    assert _resolve_symbol_kind(SymbolRecord(name="Op-Amp Dual", library="")) == "opamp_dual"
    assert _resolve_symbol_kind(SymbolRecord(name="X", library="", kind="RES")) == "resistor"
    assert _resolve_symbol_kind(SymbolRecord(name="X", library="", kind="unknown")) is None


def test_multipart_symbol_round_trip_in_registry(fake: FakeWriter, workspace):
    spec = generate_symbol(SymbolRequest(kind="opamp_dual"))
    rec = sync.ensure_symbols([spec])[0]
    assert rec.part_count == spec.part_count and rec.pin_count == len(spec.pins)


def test_bodies_without_extent_do_not_break(fake: FakeWriter, workspace):
    spec = chip_0603("FLATBODY")
    spec.bodies = [Body3D(outline=[Point(x=0, y=0), Point(x=1, y=0), Point(x=2, y=0)], z_top=1.0)]
    rec = sync.ensure_footprints([spec])[0]
    assert rec.status == "ok" and rec.step_file is None  # degenerate outline: no STEP, extruded body only


def test_graphics_only_symbol_without_pins(fake: FakeWriter, workspace):
    logo = SymbolSpec(name="LOGO", designator_prefix="LOGO", graphics=[SymRect(x1=0, y1=0, x2=100, y2=100)])
    rec = sync.ensure_symbols([logo], category="Mechanical")[0]
    assert rec.status == "ok" and rec.library == "Symbols\\PF_Mechanical.SchLib" and rec.pin_count == 0
