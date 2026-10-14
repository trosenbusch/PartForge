"""Regression tests of the library-sync review: nothing PartForge does not own is lost or
overwritten, hint generation keeps pin-outs, STEP models follow their bodies, library switches
stop operations, missing writers keep entries pending, failures carry HTTP codes.

In-memory writer (:class:`FakeWriter`); ``test_sync_rust.py`` repeats the lossy read-back
scenario with the real Rust writer.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_sync_support import FakeBridge, FakeWriter
from test_writer_samples import chip_0603, resistor_symbol

from partforge import events
from partforge.altium import libwriter, sync
from partforge.altium.bridge.core import BridgeWedgedError, DocumentState
from partforge.altium.bridge.protocol import BridgeProtocolError
from partforge.altium.libwriter import WriterUnavailable
from partforge.altium.rustwriter import RustTimeoutError, RustWriterError
from partforge.db import close_database, open_database, registry, seed_examples
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.footprints import FootprintRequest
from partforge.footprints import generate as generate_footprint
from partforge.geometry.model import SymbolSpec, SymPin
from partforge.jobs import CANCEL_LIBRARY_SWITCH, jobs
from partforge.symbols import SymbolRequest
from partforge.symbols import generate as generate_symbol
from partforge.workspace import SymbolStyle, Workspace, set_current


@pytest.fixture
def fake(workspace, monkeypatch) -> FakeWriter:
    writer = FakeWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *args, **kwargs: writer)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    return writer


def _sym(name: str, prefix: str = "U", pins: tuple[str, ...] = ("A",), description: str = "") -> SymbolSpec:
    return SymbolSpec(
        name=name,
        designator_prefix=prefix,
        description=description,
        pins=[SymPin(designator=str(i + 1), name=pin, x=0, y=-100 * i, orientation="left") for i, pin in enumerate(pins)],
    )


def _diode(order: str, description: str = "") -> SymbolSpec:
    """Two-pin diode, ``order`` = names of pin 1 and 2 ("KA" canonical, "AK" anode first)."""
    return SymbolSpec(
        name="Diode",
        designator_prefix="D",
        description=description,
        pins=[SymPin(designator="1", name=order[0], x=-100, y=0, orientation="left"),
              SymPin(designator="2", name=order[1], x=100, y=0, orientation="right")],
    )


def _passives(workspace: Workspace) -> Path:
    return workspace.symbols_dir / "PF_Passives.SchLib"


# --------------------------------------------------------------------------- never written blindly


def test_listing_failure_never_writes_blindly(fake: FakeWriter, workspace):
    """The writer timed out while listing the file: without its names the ownership check cannot run, so the
    write waits (pending) instead of replacing a foreign component of the same name – and no ownership intent
    is recorded for it."""
    lib = _passives(workspace)
    generated = generate_symbol(SymbolRequest(kind="resistor"))
    assert generated.name == "Resistor"
    fake.put(lib, [generated.model_copy(update={"description": "vom Benutzer gezeichnet"})])
    libwriter.forget_component_names()
    original = fake.list_components
    flaky = {"fail": True}

    def list_components(library):
        if flaky["fail"]:
            flaky["fail"] = False
            raise RustTimeoutError("Zeitüberschreitung beim Lesen")
        return original(library)

    fake.list_components = list_components  # type: ignore[method-assign]
    rec = sync.ensure_symbols([generated])[0]
    assert rec.status == "pending" and "nicht gelesen" in (rec.status_message or "")
    assert fake.writes() == []
    assert fake.libs[fake.key(lib)]["Resistor"].description == "vom Benutzer gezeichnet"
    manifest = sync._load_manifest(workspace.rel(lib))
    assert manifest is None or "resistor" not in manifest.components
    # the next run lists the file, finds the foreign component and takes it over – it is never overwritten
    rec = sync.ensure_symbols([generated])[0]
    assert rec.status == "ok" and rec.source == "imported"
    assert fake.writes() == []
    assert fake.libs[fake.key(lib)]["Resistor"].description == "vom Benutzer gezeichnet"


def test_imported_component_removed_in_altium_is_not_resurrected(fake: FakeWriter, workspace):
    """An imported component's registry spec is only a lossy read-back: when the user deletes the component in
    Altium, the sync must not write that copy back – the record becomes ``missing`` (re-import brings it back)."""
    lib = workspace.symbols_dir / "Import" / "Hersteller" / "Opamps.SchLib"
    foreign = resistor_symbol("LM358")
    fake.put(lib, [foreign])
    libwriter.forget_component_names()
    registry.upsert_symbol(SymbolRecord(name="LM358", library=workspace.rel(lib), source="imported", spec=foreign,
                                        pin_count=len(foreign.pins), status="ok",
                                        status_message="Beim Speichern aus PartForge ginge verloren: Pin-Symbole."))
    fake.libs[fake.key(lib)].clear()  # deleted in Altium and saved
    fake._touch(lib)
    libwriter.forget_component_names()
    fake.calls.clear()
    sync.sync_pending()
    rec = registry.get_symbol("LM358")
    assert fake.writes() == [] and fake.names(lib) == []
    assert rec is not None and rec.status == "missing" and "erneut importieren" in (rec.status_message or "")
    # the file check says the same instead of scheduling a rewrite
    registry.set_symbol_status("LM358", "ok", None)
    result = sync.scan_workspace()
    updated = [u for u in result["updated"] if u["name"] == "LM358"]
    assert updated and updated[0]["status"] == "missing"
    assert registry.get_symbol("LM358").status == "missing"
    # a generated component in the same situation is still rewritten (INT-06)
    fake.calls.clear()
    generated = sync.ensure_symbols([_sym("GenOpamp")])[0]
    gen_lib = workspace.abs(generated.library)
    fake.libs[fake.key(gen_lib)].pop("GenOpamp")
    fake._touch(gen_lib)
    libwriter.forget_component_names()
    sync.sync_pending()
    assert "GenOpamp" in fake.names(gen_lib) and registry.get_symbol("GenOpamp").status == "ok"


class _WedgedBridge(FakeBridge):
    """Altium runs, but the bridge cannot read document states (a script paused in the debugger)."""

    def is_running(self) -> bool:
        return True

    def document_states(self, paths):
        raise BridgeWedgedError("never_started", seconds=45)

    def document_state(self, path: Path) -> DocumentState:
        raise BridgeWedgedError("never_started", seconds=45)


def test_unknown_altium_state_blocks_writes_while_altium_runs(fake: FakeWriter, workspace, monkeypatch):
    """Whether Altium holds the library open and modified cannot be read: nothing is written while Altium runs
    (an open, modified library could be overwritten); without Altium nothing can be open and the write goes on."""
    rec = sync.ensure_symbols([_sym("AAA")])[0]
    assert rec.status == "ok"
    monkeypatch.setattr(sync, "altium_bridge", lambda: _WedgedBridge())
    fake.calls.clear()
    rec = sync.ensure_symbols([_sym("AAA", description="geändert")])[0]
    assert rec.status == "error" and "Skript anhalten" in (rec.status_message or "")
    assert fake.writes() == []

    class _Gone(_WedgedBridge):
        def is_running(self) -> bool:
            return False

    monkeypatch.setattr(sync, "altium_bridge", lambda: _Gone())
    rec = sync.ensure_symbols([_sym("AAA", description="geändert")])[0]
    assert rec.status == "ok" and fake.writes()


def test_prefetched_altium_states_are_asked_again_for_long_batches(workspace, monkeypatch):
    """A batch over many files prefetches the document states once; after PREFETCH_TTL_S they are asked for
    again (one script run), so a library the user opened in Altium meanwhile is not overwritten."""
    lib = _passives(workspace)
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.write_bytes(b"x")

    class _Bridge(FakeBridge):
        def __init__(self) -> None:
            super().__init__()
            self.batches = 0
            self.modified_now = False

        def is_running(self) -> bool:
            return True

        def document_states(self, paths):
            self.batches += 1
            return {os.path.normcase(str(p)): DocumentState(path=str(p), open=self.modified_now, modified=self.modified_now)
                    for p in paths}

    bridge = _Bridge()
    monkeypatch.setattr(sync, "altium_bridge", lambda: bridge)
    guard = sync._AltiumGuard()
    guard.prefetch([lib])
    assert guard.refusal(lib) is None and bridge.batches == 1
    bridge.modified_now = True
    assert guard.refusal(lib) is None  # within the TTL the prefetched answer counts
    monkeypatch.setattr(sync, "PREFETCH_TTL_S", 0.0)
    assert guard.refusal(lib) == sync.ALTIUM_MODIFIED_MESSAGE
    assert bridge.batches == 2 and bridge.calls == []  # never one script run per file


# --------------------------------------------------------------------------- full regeneration only when lossless


def test_full_regeneration_needs_partforge_written_content(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_ICs.SchLib"
    sync.ensure_symbols([_sym("AAA"), _sym("BBB")])
    assert fake.writes()[-1][0] == "write_library_full"  # new file
    sync.ensure_symbols([_sym("CCC")])
    assert fake.writes()[-1] == ("write_library_full", str(lib), ["AAA", "BBB", "CCC"])  # managed: one call
    info = next(i for i in sync.library_files(check_layers=False) if i.rel == "Symbols\\PF_ICs.SchLib")
    assert info.managed and info.in_sync and not info.external_changes


def test_imported_components_block_the_regeneration(fake: FakeWriter, workspace):
    """A component registered from a (possibly lossy) read-back is never rewritten from its spec."""
    lib = workspace.symbols_dir / "PF_ICs.SchLib"
    sync.ensure_symbols([_sym("AAA")])
    fake.put(lib, [_sym("FOREIGN", pins=("X", "Y"))])  # written by someone else
    sync.scan_workspace(register=True)
    foreign = registry.get_symbol("FOREIGN")
    assert foreign is not None and foreign.source == "imported" and foreign.spec is not None
    in_file = fake.read_symbol(lib, "FOREIGN")
    fake.calls.clear()
    assert sync.ensure_symbols([_sym("BBB")])[0].status == "ok"
    assert fake.writes() == [("write_symbols", str(lib), ["BBB"])]  # upsert, no regeneration
    assert fake.read_symbol(lib, "FOREIGN") is in_file  # the file's own content stays untouched
    info = next(i for i in sync.library_files(check_layers=False) if i.rel == "Symbols\\PF_ICs.SchLib")
    assert not info.managed and info.in_sync  # all registered, but not regenerated as a whole


def test_edits_saved_in_altium_are_not_reverted(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_ICs.SchLib"
    sync.ensure_symbols([_sym("AAA"), _sym("BBB")])
    fake.put(lib, [_sym("AAA", description="in Altium bearbeitet")])  # user edits AAA in Altium and saves
    info = next(i for i in sync.library_files(check_layers=False) if i.rel == "Symbols\\PF_ICs.SchLib")
    assert info.external_changes and not info.managed and not info.in_sync and "außerhalb" in (info.message or "")
    assert sync.scan_workspace()["changed_outside"] == ["Symbols\\PF_ICs.SchLib"]
    checks = {i.check for i in sync.library_health()["issues"]}
    assert "library_changed_outside" in checks
    fake.calls.clear()
    assert sync.ensure_symbols([_sym("CCC")])[0].status == "ok"
    assert fake.writes() == [("write_symbols", str(lib), ["CCC"])]
    assert fake.read_symbol(lib, "AAA").description == "in Altium bearbeitet"  # type: ignore[union-attr]
    info = next(i for i in sync.library_files(check_layers=False) if i.rel == "Symbols\\PF_ICs.SchLib")
    assert not info.external_changes and not info.managed  # AAA's content is no longer known exactly
    # an explicit save of AAA from PartForge still writes it (the user asked for it)
    rec = sync.ensure_symbols([_sym("AAA", description="aus PartForge")])[0]
    assert rec.status == "ok" and fake.read_symbol(lib, "AAA").description == "aus PartForge"  # type: ignore[union-attr]


def test_editor_warns_about_changes_outside_partforge(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_ICs.SchLib"
    sync.ensure_symbols([_sym("AAA")])
    assert sync.component_warnings(registry.get_symbol("AAA")) == []  # type: ignore[arg-type]
    fake.put(lib, [_sym("AAA", description="in Altium geändert")])
    warnings = sync.component_warnings(registry.get_symbol("AAA"))  # type: ignore[arg-type]
    assert len(warnings) == 1 and "außerhalb von PartForge geändert" in warnings[0]
    external = SymbolRecord(name="EXT", library=str(workspace.root.parent / "x.SchLib"), source="external")
    assert sync.component_warnings(external) == []


@pytest.mark.windows
def test_layer_stack_job_keeps_the_library_state(workspace, monkeypatch):
    from partforge.altium import stackup

    writer = FakeWriter(compound=True)  # PcbLibs with the Rust writer's header template
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    sync.ensure_footprints([chip_0603("AAA_FP"), chip_0603("BBB_FP")])
    result = sync.apply_layer_stack()
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    assert result["patched"] == [str(lib)]
    eff = stackup.effective_stack(stackup.default_stack(), workspace.settings.layers)
    assert stackup.pcblib_layer_problems(lib, eff) == []
    info = next(i for i in sync.library_files() if i.rel == "Footprints\\PF_CHIP.PcbLib")
    assert not info.external_changes and info.managed and info.layers_ok  # PartForge's own patch, not an outside edit
    writer.calls.clear()
    sync.ensure_footprints([chip_0603("CCC_FP")])
    assert writer.writes()[-1][0] == "write_library_full"  # still regenerated as a whole


def test_altium_backend_never_regenerates_an_existing_library(workspace, monkeypatch):
    class AltiumFake(FakeWriter):
        name = "altium"
        reader = object()  # cheap listings like the real backend with Rust reader

    writer = AltiumFake()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    lib = workspace.symbols_dir / "PF_ICs.SchLib"
    sync.ensure_symbols([_sym("AAA")])
    assert writer.writes() == [("write_library_full", str(lib), ["AAA"])]  # a new file has nothing to lose
    sync.ensure_symbols([_sym("BBB")])
    assert writer.writes()[-1] == ("write_symbols", str(lib), ["BBB"])  # upsert: carries the data-loss guard


# --------------------------------------------------------------------------- same name in the file, not owned


def test_foreign_symbol_with_other_pinout_is_refused(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_Diodes.SchLib"
    fake.put(lib, [_diode("AK")])
    rec = sync.ensure_symbols([_diode("KA")])[0]
    assert rec.status == "error" and "bereits mit anderer Pinbelegung vorhanden" in (rec.status_message or "")
    assert registry.get_symbol("Diode") is None  # nothing registered
    assert fake.read_symbol(lib, "Diode").pins[0].name == "A"  # type: ignore[union-attr]
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_diode("KA")], strict=True)
    assert exc.value.status == 409
    confirmed = sync.ensure_symbols([_diode("KA")], allow_pin_changes=True)[0]
    assert confirmed.status == "ok" and fake.read_symbol(lib, "Diode").pins[0].name == "K"  # type: ignore[union-attr]


def test_foreign_symbol_with_same_pinout_is_adopted(fake: FakeWriter, workspace):
    lib = workspace.symbols_dir / "PF_Diodes.SchLib"
    fake.put(lib, [_diode("KA", description="vom Benutzer")])
    assert sync.foreign_conflict(_diode("KA")) is not None  # the editor refuses such a save
    fake.calls.clear()
    rec = sync.ensure_symbols([_diode("KA", description="generiert")])[0]
    assert rec.status == "ok" and rec.source == "imported" and "übernommen" in (rec.status_message or "")
    assert fake.writes() == []
    stored = registry.get_symbol("Diode")
    assert stored is not None and stored.spec is not None and stored.spec.description == "vom Benutzer"
    assert sync.foreign_conflict(_diode("KA")) is None  # registered now: PartForge owns it
    rec = sync.ensure_symbols([_diode("KA", description="geändert")])[0]  # explicit edit writes it
    assert rec.status == "ok" and fake.read_symbol(lib, "Diode").description == "geändert"  # type: ignore[union-attr]


def test_foreign_footprint_is_adopted_with_a_pad_hint(fake: FakeWriter, workspace):
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    users = chip_0603("RESC1608X50N")
    users.pads = users.pads[:1]  # one pad only
    fake.put(lib, [users])
    fake.calls.clear()
    generated = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    assert generated.name == "RESC1608X50N"
    rec = sync.ensure_footprints([generated])[0]
    assert rec.status == "ok" and rec.source == "imported" and rec.pad_count == 1
    assert "Pads weichen" in (rec.status_message or "")
    assert fake.writes() == [] and fake.read_footprint(lib, "RESC1608X50N") is users


def test_sync_pending_never_overwrites_an_existing_component(fake: FakeWriter, workspace):
    """Seeded entries (pending, with spec) meet components of the same name in existing files."""
    diodes = workspace.symbols_dir / "PF_Diodes.SchLib"
    passives = _passives(workspace)
    fake.put(diodes, [_diode("AK", description="vom Benutzer")])
    fake.put(passives, [resistor_symbol("Resistor")])
    resistor = generate_symbol(SymbolRequest(kind="resistor"))
    registry.upsert_symbols([
        SymbolRecord(name="Diode", library="Symbols\\PF_Diodes.SchLib", spec=_diode("KA"), status="pending"),
        SymbolRecord(name="Resistor", library="Symbols\\PF_Passives.SchLib", spec=resistor, status="pending"),
    ])
    fake.calls.clear()
    summary = sync.sync_pending()
    assert fake.writes() == []
    assert fake.read_symbol(diodes, "Diode").description == "vom Benutzer"  # type: ignore[union-attr]
    diode = registry.get_symbol("Diode")
    assert diode is not None and diode.status == "error" and "anderer Pinbelegung" in (diode.status_message or "")
    assert diode.spec is not None and diode.spec.pins[0].name == "K"  # the desired state is kept
    adopted = registry.get_symbol("Resistor")
    assert adopted is not None and adopted.status == "ok" and adopted.source == "imported"
    assert adopted.spec is not None and adopted.spec.description == resistor_symbol().description
    assert summary["symbols"]["adopted"] == 1 and summary["symbols"]["error"] == 1
    assert [e["name"] for e in summary["errors"]] == ["Diode"]


# --------------------------------------------------------------------------- hints


def test_hints_keep_the_canonical_pinout_in_an_anode_first_workspace(fake: FakeWriter, workspace):
    workspace.settings.symbol.diode_pin1 = "anode"
    canonical = generate_symbol(SymbolRequest(kind="diode"), SymbolStyle())
    registry.upsert_symbols([
        SymbolRecord(name="Diode", library="Symbols\\PF_Diodes.SchLib", kind="diode"),
        SymbolRecord(name="Diode (AK)", library="Symbols\\PF_Diodes.SchLib", kind="diode"),
        SymbolRecord(name="LED (KxA)", library="Symbols\\PF_Diodes.SchLib", kind="led"),
        SymbolRecord(name="Gleichrichter", library="Symbols\\PF_Diodes.SchLib", kind="diode"),
    ])
    summary = sync.sync_pending()
    diode = registry.get_symbol("Diode")
    assert diode is not None and diode.status == "ok" and diode.spec is not None
    assert sync.pinout(diode.spec) == sync.pinout(canonical) == {"1": ("K", 1), "2": ("A", 1)}
    anode_first = registry.get_symbol("Diode (AK)")
    assert anode_first is not None and anode_first.spec is not None
    assert sync.pinout(anode_first.spec) == {"1": ("A", 1), "2": ("K", 1)}
    led = registry.get_symbol("LED (KxA)")
    assert led is not None and led.status == "ok" and led.spec is not None and len(led.spec.pins) == 2
    custom = registry.get_symbol("Gleichrichter")  # custom diode name: the pin-out is not certain
    assert custom is not None and custom.status == "missing" and "nicht eindeutig" in (custom.status_message or "")
    assert summary["symbols"]["missing"] == 1


def test_hints_with_cathode_style_and_named_variants(workspace):
    registry_records = [
        SymbolRecord(name="Diode (AK)", library="", kind="diode"),
        SymbolRecord(name="Connector 2x05", library="", kind="connector"),
        SymbolRecord(name="Battery 2-Cell", library="", kind="battery"),
        SymbolRecord(name="NPN (EBC)", library="", kind="npn"),
        SymbolRecord(name="BC547", library="", kind="npn"),
        SymbolRecord(name="Spule", library="", kind="inductor"),
        SymbolRecord(name="Resistor", library="", kind="resistor", pin_count=3),
    ]
    results = {rec.name: sync._symbol_from_hints(workspace, rec) for rec in registry_records}
    assert sync.pinout(results["Diode (AK)"][0]) == {"1": ("A", 1), "2": ("K", 1)}  # type: ignore[arg-type]
    assert len(results["Connector 2x05"][0].pins) == 10  # type: ignore[union-attr]
    assert results["Battery 2-Cell"][0] is not None
    npn = results["NPN (EBC)"][0]
    assert npn is not None and npn.name == "NPN (EBC)" and sync.pinout(npn)["1"][0] == "E"
    assert results["BC547"][0] is None and "nicht eindeutig" in (results["BC547"][1] or "")  # pin map unknown
    assert results["Spule"][0] is not None and results["Spule"][0].name == "Spule"  # same pins in every variant
    assert results["Resistor"][0] is None  # registered pin count does not match


# --------------------------------------------------------------------------- STEP models


def test_step_model_follows_the_bodies(fake: FakeWriter, workspace):
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    rec = sync.ensure_footprints([spec])[0]
    step = workspace.abs(rec.step_file)
    assert step is not None and step.is_file()
    first = step.read_text(encoding="ascii")
    stored = registry.get_footprint(spec.name).spec  # type: ignore[union-attr]
    assert stored is not None and stored.step is not None  # the editor round trip keeps "step"
    body = stored.bodies[0]
    taller = stored.model_copy(update={"bodies": [body.model_copy(update={"z_top": body.z_top + 2.0}), *stored.bodies[1:]],
                                       "height": (stored.height or 0) + 2.0})
    assert sync.ensure_footprints([taller])[0].status == "ok"
    second = step.read_text(encoding="ascii")
    assert second != first and "PartForge 3D model of RESC1608X50N" in second
    assert fake.read_footprint(workspace.footprints_dir / "PF_CHIP.PcbLib", spec.name).step.file == rec.step_file  # type: ignore[union-attr]


def test_grouped_files_stay_small_also_within_one_batch(fake: FakeWriter, workspace, monkeypatch):
    """perf-library-write: the writer rewrites the whole file on every change – a grouped file takes no further new
    component once it is full (here 2); registered names stay where they are."""
    monkeypatch.setattr(sync, "MAX_LIBRARY_COMPONENTS", 2)
    folder = workspace.footprints_dir
    recs = sync.ensure_footprints([chip_0603(f"R{i}") for i in range(1, 6)])
    assert [r.status for r in recs] == ["ok"] * 5
    assert [r.library for r in recs] == ["Footprints\\PF_CHIP.PcbLib"] * 2 + ["Footprints\\PF_CHIP_2.PcbLib"] * 2 + [
        "Footprints\\PF_CHIP_3.PcbLib"]
    assert fake.names(folder / "PF_CHIP_2.PcbLib") == ["R3", "R4"]
    assert sync.ensure_footprints([chip_0603("R6")])[0].library == "Footprints\\PF_CHIP_3.PcbLib"  # next save
    changed = chip_0603("R1").model_copy(update={"description": "geändert"})
    assert sync.ensure_footprints([changed])[0].library == "Footprints\\PF_CHIP.PcbLib"  # stays in its file
    monkeypatch.setattr(sync, "MAX_LIBRARY_COMPONENTS", 60)
    assert sync.ensure_footprints([chip_0603("R7")])[0].library == "Footprints\\PF_CHIP.PcbLib"


def test_a_locked_step_file_gives_a_german_reason(workspace, monkeypatch):
    """F11 (UX): no English OS text („[Errno 13] Permission denied: 'C:\\\\…'“) in the note of a STEP model."""
    import partforge.footprints as footprints

    def locked(spec, target):
        raise PermissionError(13, "Permission denied", str(target))

    monkeypatch.setattr(footprints, "write_step", locked)
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    _, note = sync._ensure_step_file(workspace, spec)
    assert note is not None and "von einem anderen Programm geöffnet oder schreibgeschützt" in note
    assert "Errno" not in note and "Permission denied" not in note


def test_shared_and_vendor_step_models_are_kept(fake: FakeWriter, workspace):
    owner = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0805"}))
    owner_rec = sync.ensure_footprints([owner])[0]
    owner_step = workspace.abs(owner_rec.step_file)
    assert owner_step is not None
    owner_text = owner_step.read_text(encoding="ascii")
    sharer = chip_0603("SHARES_MODEL")  # different bodies, references the other footprint's model
    sharer.step = owner_rec.spec.step  # type: ignore[union-attr]
    assert sync.ensure_footprints([sharer])[0].status == "ok"
    assert owner_step.read_text(encoding="ascii") == owner_text
    vendor = workspace.models_dir / "vendor.step"
    vendor.write_text("ISO-10303-21; vendor", encoding="ascii")
    with_vendor = chip_0603("USES_VENDOR")
    with_vendor.step = owner_rec.spec.step.model_copy(update={"file": "3D\\vendor.step"})  # type: ignore[union-attr]
    assert sync.ensure_footprints([with_vendor])[0].status == "ok"
    assert vendor.read_text(encoding="ascii") == "ISO-10303-21; vendor"


def test_step_file_name_collision_keeps_the_other_model(fake: FakeWriter, workspace):
    first = chip_0603("CON")  # reserved device name: file stem "PF_CON"
    second = chip_0603("PF_CON")  # the same file stem
    second.bodies[0] = second.bodies[0].model_copy(update={"z_top": 1.5})
    rec_a = sync.ensure_footprints([first])[0]
    rec_b = sync.ensure_footprints([second])[0]
    assert rec_a.status == rec_b.status == "ok"
    assert rec_a.step_file == "3D\\PF_CON.step" and rec_b.step_file != rec_a.step_file
    text_a = workspace.abs(rec_a.step_file).read_text(encoding="ascii")  # type: ignore[union-attr]
    text_b = workspace.abs(rec_b.step_file).read_text(encoding="ascii")  # type: ignore[union-attr]
    assert "PartForge 3D model of CON'" in text_a and "PartForge 3D model of PF_CON'" in text_b
    again = sync.ensure_footprints([first.model_copy(update={"description": "neu"})])[0]
    assert again.step_file == rec_a.step_file  # both keep their own model


# --------------------------------------------------------------------------- library switch


def _switch_to(other: Workspace) -> None:
    close_database()
    open_database(other)
    set_current(other)


def test_switch_during_sync_never_writes_into_the_other_library(workspace, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    other = Workspace.create(tmp_path / "Andere", name="Andere")
    registry.upsert_symbols([
        SymbolRecord(name="AAA", library="Symbols\\PF_ICs.SchLib", spec=_sym("AAA"), status="pending"),
        SymbolRecord(name="DDD", library="Symbols\\PF_Diodes.SchLib", spec=_sym("DDD", "D"), status="pending"),
    ])

    class SwitchingWriter(FakeWriter):
        switched = False

        def write_library_full(self, library, specs):
            result = super().write_library_full(library, specs)
            if not self.switched:  # the user opens another library while the first file is written
                self.switched = True
                _switch_to(other)
            return result

    writer = SwitchingWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)
    try:
        with pytest.raises(sync.SyncError) as exc:
            sync.sync_pending()
        assert exc.value.status == 409 and "gewechselt" in str(exc.value)
        assert registry.list_symbols() == []  # nothing leaked into the other library
        assert list(other.symbols_dir.iterdir()) == []
    finally:
        _switch_to(workspace)
    assert {r.name: r.status for r in registry.list_symbols()} == {"AAA": "pending", "DDD": "pending"}
    # back in the first library: the interrupted file is PartForge's own (recorded before writing)
    writer.switched = True
    summary = sync.sync_pending()
    assert summary["errors"] == [] and summary["symbols"]["adopted"] == 0
    assert {r.name: (r.status, r.source) for r in registry.list_symbols()} == {
        "AAA": ("ok", "generated"), "DDD": ("ok", "generated")
    }


def test_switch_event_cancels_a_job(fake: FakeWriter, workspace, monkeypatch):
    class AnnouncingWriter(FakeWriter):
        def write_library_full(self, library, specs):
            result = super().write_library_full(library, specs)
            events.emit(events.WORKSPACE_CLOSED)  # e.g. "Bibliothek schließen" while the job runs
            return result

    writer = AnnouncingWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)
    job = jobs.run_sync("test", "Speichern", lambda ctx: sync.ensure_symbols([_sym("AAA"), _sym("DDD", "D")], ctx=ctx))
    assert job.status == "cancelled"
    # K11: the reason travels with the job (the UI explains the stop), the final message is the sync's own text
    assert job.cancel_reason == CANCEL_LIBRARY_SWITCH
    assert job.message == sync.LIBRARY_SWITCHED_MESSAGE
    assert not [e for e in job.log if "gewechselt oder geschlossen" in e["text"]]  # announced once, by the guard
    assert registry.list_symbols() == []
    assert len(writer.writes()) == 1  # stopped before the second library


def test_switch_during_a_held_job_is_announced_once(fake: FakeWriter, workspace, monkeypatch):
    """K11: a held library job stopped by a switch bypassing the guard carries ``cancel_reason`` and logs the
    switch exactly once (the guard's announcement, no second warning from the sync)."""
    from partforge.jobs import library_hold

    class AnnouncingWriter(FakeWriter):
        def write_library_full(self, library, specs):
            result = super().write_library_full(library, specs)
            events.emit(events.WORKSPACE_CLOSED)
            return result

    writer = AnnouncingWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)

    def body(ctx):
        with library_hold(ctx, workspace.root):
            return sync.ensure_symbols([_sym("AAA"), _sym("DDD", "D")], ctx=ctx)

    job = jobs.run_sync("libraries.save", "Speichern", body)
    assert job.status == "cancelled" and job.cancel_reason == CANCEL_LIBRARY_SWITCH
    warnings = [e["text"] for e in job.log if e["level"] == "warn"]
    assert len([w for w in warnings if "gewechselt" in w]) == 1, warnings


def test_sessions_unsubscribe_after_use(fake: FakeWriter, workspace):
    sync.ensure_symbols([_sym("AAA")])
    events.emit(events.WORKSPACE_OPENED, workspace)  # no session listens any more
    assert sync.ensure_symbols([_sym("BBB")])[0].status == "ok"


# --------------------------------------------------------------------------- no writer, failures, Altium


def test_sync_pending_without_writer_leaves_everything_pending(workspace, monkeypatch):
    def unavailable(*_a, **_k):
        raise WriterUnavailable("Kein Bibliotheks-Writer verfügbar.")

    monkeypatch.setattr(sync, "get_writer", unavailable)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    seed_examples(workspace)
    summary = sync.sync_pending()
    assert summary["skipped"] is True and "Kein Bibliotheks-Writer" in summary["reason"]
    statuses = {r.status for r in registry.list_symbols()} | {r.status for r in registry.list_footprints()}
    assert statuses == {"pending"} and summary["errors"] == [] and summary["libraries"] == []


def test_strict_saves_report_the_failure_category(fake: FakeWriter, workspace, monkeypatch):
    sync.ensure_symbols([_sym("AAA")])
    fake.fail = RustTimeoutError("Der Rust-Writer antwortet nicht.")
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_sym("AAA", description="neu")], strict=True)
    assert exc.value.status == 503 and registry.get_symbol("AAA").status == "error"  # type: ignore[union-attr]
    fake.fail = RustWriterError("Der Rust-Writer meldet einen Fehler.")
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_sym("AAA", description="neu")], strict=True)
    assert exc.value.status == 400
    fake.fail = None
    monkeypatch.setattr(sync, "altium_bridge", lambda: FakeBridge(open_=True, modified=True))
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_sym("AAA", description="neu")], strict=True)
    assert exc.value.status == 409 and sync.ALTIUM_MODIFIED_MESSAGE in str(exc.value)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_sym("AAA", pins=("B",))], strict=True)  # pin-out change without confirmation
    assert exc.value.status == 409
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_sym("BAD|NAME")], strict=True)
    assert exc.value.status == 400
    # F11: a file another program keeps open is a conflict (409) with the German outcome first, not "invalid"
    fake.errors = {"AAA": "PF_ICs.SchLib wurde nicht geschrieben – die Bibliothek ist unverändert: Die Datei ist von "
                          "einem anderen Programm geöffnet oder schreibgeschützt."}
    with pytest.raises(sync.SyncFailed) as exc:
        sync.ensure_symbols([_sym("AAA", description="gesperrt")], strict=True)
    assert exc.value.status == 409 and str(exc.value).startswith("PF_ICs.SchLib wurde nicht geschrieben")
    fake.errors = {}
    assert [r.status for r in sync.ensure_symbols([_sym("AAA", description="neu")], strict=True)] == ["ok"]


def test_bridge_errors_of_any_kind_do_not_abort_writing(fake: FakeWriter, workspace, monkeypatch):
    sync.ensure_symbols([_sym("AAA")])

    class Broken(FakeBridge):
        def document_state(self, path):
            raise BridgeProtocolError("Antwort der Altium-Brücke hat ein unbekanntes Format.")

    monkeypatch.setattr(sync, "altium_bridge", lambda: Broken())
    assert sync.ensure_symbols([_sym("BBB")])[0].status == "ok"


@pytest.mark.windows
def test_write_is_slow_counts_embedded_step_models(fake: FakeWriter, workspace, monkeypatch, tmp_path):
    from partforge.config import AppSettings

    settings = AppSettings()
    writer_exe = tmp_path / "altium-designer-mcp.exe"  # a configured writer must be a local .exe
    writer_exe.write_bytes(b"MZ")
    settings.altium.rust_writer_path = str(writer_exe)
    monkeypatch.setattr(sync, "load_settings", lambda *a, **k: settings)
    spec = chip_0603("NEW_ONE")
    assert sync.write_is_slow(spec) is False
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    fake.put(lib, [chip_0603(f"R{i}") for i in range(sync.SLOW_LIBRARY_STEP_MODELS)])
    registry.upsert_footprints([
        FootprintRecord(name=f"R{i}", library="Footprints\\PF_CHIP.PcbLib", step_file=f"3D\\R{i}.step", status="ok")
        for i in range(sync.SLOW_LIBRARY_STEP_MODELS)
    ])
    assert sync.write_is_slow(spec) is True  # one more STEP model than the limit
    assert sync.write_is_slow(spec.model_copy(update={"bodies": [], "step": None})) is False
