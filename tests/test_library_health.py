"""File-level library check (``sync.library_health`` / ``GET /api/libraries/health``): check ids and their
aliases, affected parts, footprint heights in the PcbLib and their one-click repair (in-memory writer that
stores PcbLibs as compound files, no Altium)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from test_sync_support import FakeWriter, make_part, synthetic_pcblib
from test_writer_samples import ic8_symbol, resistor_symbol

from partforge.altium import heights, libwriter, sync
from partforge.db import registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.footprints import FootprintRequest
from partforge.footprints import generate as generate_footprint
from partforge.geometry.model import FootprintSpec


class HeightWriter(FakeWriter):
    """:class:`FakeWriter` whose PcbLibs are compound files with a ``HEIGHT`` per footprint: ``0mil`` like a
    library written before the height patch, or – with ``patch`` – the spec's height for the footprints of a
    call (like the Rust writer with :mod:`partforge.altium.heights`)."""

    def __init__(self) -> None:
        super().__init__(compound=True)
        self.patch = False
        self.stored: dict[str, dict[str, str]] = {}

    def _remember(self, library: Path, specs) -> None:
        if not self.patch or library.suffix.lower() != ".pcblib":
            return
        lib = self.stored.setdefault(self.key(library), {})
        for spec in specs:
            height = heights.footprint_height(spec) if isinstance(spec, FootprintSpec) else None
            lib[spec.name] = f"{heights.format_mil(heights.mm_to_coord(height))}mil" if height else "0mil"

    def write_footprints(self, library, footprints):
        self._remember(library, footprints)
        return super().write_footprints(library, footprints)

    def write_library_full(self, library, specs):
        self._remember(library, specs)
        return super().write_library_full(library, specs)

    def _touch(self, library: Path) -> None:
        if library.suffix.lower() != ".pcblib":
            super()._touch(library)
            return
        self._version += 1
        library.parent.mkdir(parents=True, exist_ok=True)
        names = list(self.libs.get(self.key(library), {})) or ["EMPTY"]
        stored = self.stored.get(self.key(library), {})
        library.unlink(missing_ok=True)
        synthetic_pcblib(library, components=names, heights={n: stored.get(n, "0mil") for n in names})


@pytest.fixture
def writer(monkeypatch) -> HeightWriter:
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    fake = HeightWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: fake)
    return fake


def wait_job(client, job: dict, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Job {job['id']} nicht fertig")


def chip(preset: str = "R-0603") -> FootprintSpec:
    return generate_footprint(FootprintRequest(family="chip", params={"preset": preset}))


def by_check(report: dict, check: str) -> list:
    return [i for i in report["issues"] if (i["check"] if isinstance(i, dict) else i.check) == check]


# --------------------------------------------------------------------------- check ids, aliases, affected parts


@pytest.mark.windows
def test_registry_status_findings_use_the_data_level_ids(workspace, writer):
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    writer.put(lib, [resistor_symbol("BROKEN")])
    registry.upsert_symbol(SymbolRecord(name="BROKEN", library="Symbols\\PF_Passives.SchLib", status="error",
                                        status_message="kaputt", spec=resistor_symbol("BROKEN")))
    fp_lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    spec = chip()
    writer.put(fp_lib, [spec])
    registry.upsert_footprint(FootprintRecord(name=spec.name, library="Footprints\\PF_CHIP.PcbLib", status="missing",
                                              status_message="nicht erzeugbar"))
    make_part("Resistors", "R-2", Library_Ref="BROKEN", Library_Path="Symbols\\PF_Passives.SchLib")
    make_part("Resistors", "R-1", Library_Ref="BROKEN", Library_Path="Symbols\\PF_Passives.SchLib")
    report = sync.library_health()
    error = by_check(report, "registry_error")[0]
    assert error.aliases == ["symbol_error"] and error.kind == "symbol" and error.component == "BROKEN"
    assert error.library == "Symbols\\PF_Passives.SchLib" and error.part_number is None
    assert (error.affected_parts, error.part_numbers) == (2, ["R-1", "R-2"])
    missing = by_check(report, "registry_missing")[0]
    assert missing.aliases == ["footprint_missing"] and missing.component == spec.name and missing.affected_parts == 0
    assert not by_check(report, "symbol_error") and not by_check(report, "footprint_missing")  # old ids are gone
    assert report["summary"]["registry_error"] == 1 and report["summary"]["registry_missing"] == 1


def test_component_and_part_findings_name_the_affected_parts(workspace, writer):
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    writer.put(lib, [resistor_symbol("THERE")])
    registry.upsert_symbol(SymbolRecord(name="LOST", library="Symbols\\PF_Passives.SchLib", status="ok",
                                        spec=resistor_symbol("LOST")))
    for i in range(25):  # more users than the finding lists
        make_part("Resistors", f"R-{i:02d}", Library_Ref="LOST", Library_Path="Symbols\\PF_Passives.SchLib")
    make_part("Resistors", "R-X", Library_Ref="NOWHERE", Library_Path="Symbols\\PF_Passives.SchLib")
    report = sync.library_health()
    lost = by_check(report, "component_missing")[0]
    assert lost.part_number is None and lost.component == "LOST" and lost.affected_parts == 25
    assert lost.part_numbers == [f"R-{i:02d}" for i in range(20)]  # sorted, the first 20
    part_level = [i for i in by_check(report, "component_not_in_file") if i.part_number == "R-X"][0]
    assert (part_level.affected_parts, part_level.part_numbers) == (1, ["R-X"])
    assert part_level.table == "Resistors" and part_level.column == "Library Path" and part_level.component == "NOWHERE"
    # every part with an error or warning, exactly once
    assert report["affected_parts"] == 26 == len(report["affected_part_numbers"])
    assert report["affected_part_numbers"][:2] == ["R-00", "R-01"] and "R-X" in report["affected_part_numbers"]
    # sorted by severity; counts and summary over all findings even when the list is cut
    short = sync.library_health(max_issues=1)
    assert len(short["issues"]) == 1 and short["truncated"] is True and short["issues"][0].severity == "error"
    assert short["counts"] == report["counts"] and short["summary"] == report["summary"]
    assert short["affected_parts"] == report["affected_parts"]


def test_pin_pad_mismatch_counts_every_part_of_the_pair(workspace, writer):
    sym = ic8_symbol("TIMER")
    fp = chip()
    registry.upsert_symbol(SymbolRecord(name="TIMER", library="Symbols\\PF_ICs.SchLib", spec=sym, status="pending"))
    registry.upsert_footprint(FootprintRecord(name=fp.name, library="Footprints\\PF_CHIP.PcbLib", spec=fp,
                                              status="pending"))
    for pn in ("U-3", "U-1", "U-2"):
        make_part("Integrated Circuits", pn, Library_Ref="TIMER", Footprint_Ref=fp.name)
    issue = by_check(sync.library_health(), "pin_pad_mismatch")[0]
    assert issue.part_number == "U-1" and issue.affected_parts == 3 and issue.part_numbers == ["U-1", "U-2", "U-3"]
    assert "(und 2 weitere Bauteile)" in issue.message and issue.component == fp.name


def test_health_endpoint_model(client, workspace, writer):
    registry.upsert_symbol(SymbolRecord(name="LOST", library="Symbols\\PF_Lost.SchLib", status="ok"))
    make_part("Resistors", "R-1", Library_Ref="LOST", Library_Path="Symbols\\PF_Lost.SchLib")
    data = client.get("/api/libraries/health").json()
    registry_level = next(i for i in data["issues"] if i["check"] == "library_file_missing" and not i["part_number"])
    assert registry_level["affected_parts"] == 1 and registry_level["part_numbers"] == ["R-1"]
    assert registry_level["aliases"] == [] and registry_level["fix_action"] is None
    assert data["affected_parts"] == 1 and data["affected_part_numbers"] == ["R-1"]
    assert data["summary"]["library_file_missing"] == 2  # the registry entry and the part's path


# --------------------------------------------------------------------------- footprint heights


def _write_without_heights(workspace, writer, specs) -> None:
    """A library written before the height patch: every footprint has HEIGHT=0mil in the PcbLib."""
    writer.patch = False
    records = sync.ensure_footprints(specs)
    assert all(r.status == "ok" for r in records), [r.status_message for r in records]


@pytest.mark.windows
def test_missing_heights_are_found_and_the_sync_alone_does_not_fix_them(workspace, writer):
    r0603, c0805 = chip("R-0603"), chip("C-0805")
    _write_without_heights(workspace, writer, [r0603, c0805])
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    assert heights.read_footprint_heights(lib) == {r0603.name: 0.0, c0805.name: 0.0}
    make_part("Resistors", "R-1", Footprint_Ref=r0603.name, Footprint_Path="Footprints\\PF_CHIP.PcbLib")
    problems = sync.footprint_height_problems()
    assert [p.name for p in problems] == sorted([r0603.name, c0805.name])
    assert all(p.repairable and p.rel == "Footprints\\PF_CHIP.PcbLib" for p in problems)
    report = sync.library_health()
    found = {i.component: i for i in by_check(report, sync.HEIGHT_CHECK)}
    issue = found[r0603.name]
    assert issue.severity == "warning" and issue.fix_action == sync.REPAIR_HEIGHTS_ACTION
    assert issue.message.startswith("Footprint-Höhe fehlt in der PcbLib: ")
    assert f"{r0603.height:.2f}".replace(".", ",") in issue.message
    assert (issue.affected_parts, issue.part_numbers, issue.kind) == (1, ["R-1"], "footprint")
    # the change detection of the sync does not rewrite them: the spec did not change
    writer.patch = True
    calls = len(writer.writes())
    sync.ensure_footprints([r0603, c0805])
    summary = sync.sync_pending()
    assert len(writer.writes()) == calls and summary["footprints"]["total"] == 0
    assert len(sync.footprint_height_problems()) == 2


@pytest.mark.windows
def test_repair_job_rewrites_the_footprints_through_the_sync(client, workspace, writer):
    r0603, c0805 = chip("R-0603"), chip("C-0805")
    _write_without_heights(workspace, writer, [r0603, c0805])
    writer.patch = True
    resp = client.post("/api/libraries/footprint-heights/repair")
    snap = wait_job(client, resp.json()["job"])
    assert snap["status"] == "done" and snap["kind"] == "libraries.sync", snap
    result = snap["result"]
    assert sorted(result["rewritten"]) == sorted([r0603.name, c0805.name]) and result["remaining"] == []
    assert result["checked"] == 2 and result["skipped"] == [] and result["errors"] == []
    assert snap["message"] == "Footprint-Höhen nachgetragen: 2 Footprints in 1 Bibliothek."
    stored = heights.read_footprint_heights(workspace.footprints_dir / "PF_CHIP.PcbLib")
    assert stored[r0603.name] == pytest.approx(r0603.height, abs=1e-5)
    assert not by_check(client.get("/api/libraries/health").json(), sync.HEIGHT_CHECK)
    again = wait_job(client, client.post("/api/libraries/footprint-heights/repair", json={}).json()["job"])
    assert again["message"] == "Alle Footprint-Höhen sind in den PcbLibs eingetragen – nichts zu tun."


@pytest.mark.windows
def test_repair_only_the_named_footprints(workspace, writer):
    r0603, c0805 = chip("R-0603"), chip("C-0805")
    _write_without_heights(workspace, writer, [r0603, c0805])
    writer.patch = True
    out = sync.repair_footprint_heights([r0603.name.lower()])
    assert out["rewritten"] == [r0603.name] and out["checked"] == 1
    # (a regeneration of the whole library may give the other footprints their height as well)
    assert r0603.name not in [p.name for p in sync.footprint_height_problems()]


@pytest.mark.windows
def test_a_library_changed_outside_partforge_is_not_rewritten(workspace, writer):
    spec = chip()
    _write_without_heights(workspace, writer, [spec])
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    data = lib.read_bytes()
    lib.unlink()
    synthetic_pcblib(lib, components=[spec.name, "IN_ALTIUM_GEZEICHNET"], heights={spec.name: "0mil"})
    assert lib.read_bytes() != data  # saved in Altium meanwhile
    writer.libs[writer.key(lib)]["IN_ALTIUM_GEZEICHNET"] = spec.model_copy(update={"name": "IN_ALTIUM_GEZEICHNET"})
    problem = sync.footprint_height_problems()[0]
    assert problem.name == spec.name and problem.repairable is False
    issue = by_check(sync.library_health(), sync.HEIGHT_CHECK)[0]
    assert issue.fix_action is None and "außerhalb von PartForge" in (issue.fix_hint or "")
    writer.patch = True
    calls = len(writer.writes())
    out = sync.repair_footprint_heights()
    assert out["rewritten"] == [] and out["skipped"][0]["name"] == spec.name and len(writer.writes()) == calls
    assert "übersprungen" in out["message"]


@pytest.mark.windows
def test_imported_footprints_and_unreadable_files_are_not_checked(workspace, writer, monkeypatch):
    spec = chip()
    _write_without_heights(workspace, writer, [spec])
    rec = registry.get_footprint(spec.name)
    assert rec is not None
    registry.upsert_footprint(rec.model_copy(update={"source": "imported"}))
    assert sync.footprint_height_problems() == []
    registry.upsert_footprint(rec)
    assert len(sync.footprint_height_problems()) == 1
    assert rec.spec is not None
    huge = rec.spec.model_copy(update={"height": 6000.0})  # not storable in Altium (> 5 m): nothing to repair
    registry.upsert_footprint(rec.model_copy(update={"spec": huge}))
    assert sync.footprint_height_problems() == [] and not by_check(sync.library_health(), sync.HEIGHT_CHECK)
    registry.upsert_footprint(rec)
    monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", False)  # switched off: nothing to check or repair
    assert sync.footprint_height_problems() == []
    monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", True)
    (workspace.footprints_dir / "PF_CHIP.PcbLib").write_bytes(b"kein Compound-File")
    assert sync.footprint_height_problems() == []


# --------------------------------------------------------------------------- the real Rust writer


@pytest.mark.rustwriter
def test_rust_library_written_without_heights_is_repaired(client, workspace, monkeypatch):
    """A PcbLib written before the height patch (simulated by switching it off) gets the heights by the repair."""
    from partforge.altium.rustwriter import shutdown_client

    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    try:
        spec = chip()
        monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", False)
        assert sync.ensure_footprints([spec])[0].status == "ok"
        monkeypatch.setattr(heights, "HEIGHT_PATCH_ENABLED", True)
        lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
        assert heights.read_footprint_heights(lib)[spec.name] == 0.0
        assert [p.name for p in sync.footprint_height_problems()] == [spec.name]
        snap = wait_job(client, client.post("/api/libraries/footprint-heights/repair").json()["job"], timeout=120)
        assert snap["status"] == "done" and snap["result"]["rewritten"] == [spec.name], snap
        assert heights.read_footprint_heights(lib)[spec.name] == pytest.approx(spec.height, abs=1e-5)
        assert sync.footprint_height_problems() == []
        files = client.get("/api/libraries/files", params={"layers": False}).json()
        assert next(f for f in files if f["kind"] == "pcblib")["external_changes"] is False  # manifest updated
    finally:
        shutdown_client()


# --------------------------------------------------------------------------- review fixes (F2, K1, INT-05, cache)


def _pair(sym, fp, *, parts: tuple[str, ...] = ("U-1",), table: str = "Integrated Circuits") -> None:
    registry.upsert_symbol(SymbolRecord(name=sym.name, library="Symbols\\PF_ICs.SchLib", spec=sym, status="pending",
                                        kind=(sym.generator or {}).get("kind") if isinstance(sym.generator, dict) else None))
    registry.upsert_footprint(FootprintRecord(name=fp.name, library="Footprints\\PF_X.PcbLib", spec=fp, status="pending"))
    for pn in parts:
        make_part(table, pn, Library_Ref=sym.name, Footprint_Ref=fp.name)


def test_nc_pads_of_amplifiers_and_recorded_nc_pads_are_no_mismatch(workspace, writer):
    """F2: „Op-Amp (SOIC8)“ on a SOIC-8 leaves pads 1, 5, 8 free on purpose – the datasheet proposal accepted it,
    the file-level check warned for every such part."""
    from partforge.symbols import SymbolRequest, generate

    soic = generate_footprint(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}))
    opamp = generate(SymbolRequest(kind="opamp", params={"pinmap": "SOIC8"}))
    _pair(opamp, soic, parts=("U-1", "U-2", "U-3"), table="Amplifiers")
    report = sync.library_health(refresh=True)
    assert not by_check(report, "pin_pad_mismatch"), [i.message for i in by_check(report, "pin_pad_mismatch")]
    # an IC symbol from a pin table whose NC pins the datasheet import recorded (generator.nc_pads)
    timer = ic8_symbol("TIMER_NC")
    timer = timer.model_copy(update={"pins": [p for p in timer.pins if p.designator != "5"],
                                     "generator": {"kind": "ic", "nc_pads": ["5"]}})
    _pair(timer, soic, parts=("U-4",))
    assert not by_check(sync.library_health(refresh=True), "pin_pad_mismatch")
    # without the record the same pair is a real mismatch
    plain = timer.model_copy(update={"name": "TIMER_PLAIN", "generator": {"kind": "ic"}})
    _pair(plain, soic, parts=("U-5",))
    mismatch = by_check(sync.library_health(refresh=True), "pin_pad_mismatch")
    assert [(i.severity, i.part_number) for i in mismatch] == [("warning", "U-5")]
    assert "Pads ohne Pin im Symbol: 5" in mismatch[0].message


def test_letter_code_nc_pads_and_exposed_pads(workspace, writer):
    from partforge.symbols import SymbolRequest, generate

    sot23 = generate_footprint(FootprintRequest(family="sot23", params={"preset": "SOT-23-3"}))
    schottky = generate(SymbolRequest(kind="schottky", params={"pinmap": "AxK"}))
    _pair(schottky, sot23, parts=("D-1",), table="Diodes")
    assert not by_check(sync.library_health(refresh=True), "pin_pad_mismatch")
    from test_writer_samples import qfn16
    from partforge.geometry.model import SymPin, SymbolSpec

    qfn = qfn16()
    ic = SymbolSpec(name="IC_QFN16", designator_prefix="U",
                    pins=[SymPin(designator=str(i), name=f"P{i}", x=0, y=-100 * i, orientation="left") for i in range(1, 17)])
    _pair(ic, qfn, parts=("U-9",))
    hint = by_check(sync.library_health(refresh=True), "pin_pad_mismatch")
    assert [(i.severity, i.part_number) for i in hint] == [("info", "U-9")]  # only a hint: connect the EP
    assert "Exposed Pad 17" in hint[0].message


@pytest.mark.windows
def test_status_missing_and_not_in_the_file_is_one_finding(workspace, writer):
    """K1: a registry entry with status ``missing`` that is not in its file was reported twice (component_missing
    and registry_missing) – one finding, the error, with the registry id as alias."""
    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    writer.put(lib, [chip("C-0805")])
    registry.upsert_footprint(FootprintRecord(name="GHOST", library="Footprints\\PF_CHIP.PcbLib", status="missing",
                                              status_message="nicht erzeugbar"))
    report = sync.library_health(refresh=True)
    findings = [i for i in report["issues"] if i.component == "GHOST"]
    assert [(i.check, i.severity) for i in findings] == [("component_missing", "error")]
    assert findings[0].aliases == ["registry_missing", "footprint_missing"] and "nicht erzeugbar" in findings[0].message
    assert "registry_missing" not in report["summary"]


def test_unreadable_file_is_reported(workspace, writer, monkeypatch):
    """INT-05: a corrupt file was invisible (0 errors) – now an error per file naming the affected parts."""
    from partforge.altium.rustwriter import RustToolError

    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    writer.put(lib, [resistor_symbol("R_OK")])
    registry.upsert_symbol(SymbolRecord(name="R_OK", library="Symbols\\PF_Passives.SchLib", status="ok",
                                        spec=resistor_symbol("R_OK")))
    make_part("Resistors", "R-1", Library_Ref="R_OK", Library_Path="Symbols\\PF_Passives.SchLib")
    original = writer.list_components

    def broken(library):
        if Path(library).name == "PF_Passives.SchLib":
            raise RustToolError("list_components", "Invalid OLE structure: Malformed FAT (sector 266 pointed to twice)")
        return original(library)

    monkeypatch.setattr(writer, "list_components", broken)
    libwriter.forget_component_names()
    report = sync.library_health(refresh=True)
    issue = by_check(report, sync.UNREADABLE_CHECK)[0]
    assert issue.severity == "error" and issue.library == "Symbols\\PF_Passives.SchLib" and issue.part_numbers == ["R-1"]
    assert "Malformed FAT" in issue.message and issue.fix_action is None  # the fake writer has no backups to read
    assert report["counts"]["error"] == 1 and report["affected_part_numbers"] == ["R-1"]
    scan = sync.scan_workspace()
    assert scan["unreadable"][0]["library"] == "Symbols\\PF_Passives.SchLib"
    assert sync.scan_message(scan).startswith("Bibliotheken geprüft: 1 Datei – 1 Datei nicht lesbar")


def test_report_is_cached_per_library_state(workspace, writer, monkeypatch):
    """perf: the start page and the Altium page ask for the report after every job – a repeated request for an
    unchanged library is answered from the cache; any change (registry, parts, files) checks again."""
    calls = {"n": 0}
    original = sync._health_findings

    def counting(ws, w):
        calls["n"] += 1
        return original(ws, w)

    monkeypatch.setattr(sync, "_health_findings", counting)
    sync.invalidate_health_cache()
    first = sync.library_health()
    assert sync.library_health() == first and calls["n"] == 1
    registry.upsert_symbol(SymbolRecord(name="NEU", library="Symbols\\PF_Neu.SchLib", status="ok"))
    assert sync.library_health()["summary"] != first["summary"] and calls["n"] == 2
    make_part("Resistors", "R-CACHE", Library_Ref="NEU", Library_Path="Symbols\\PF_Neu.SchLib")
    sync.library_health()
    assert calls["n"] == 3
    sync.library_health(refresh=True)
    assert calls["n"] == 4
    writer.put(workspace.symbols_dir / "PF_Neu.SchLib", [resistor_symbol("NEU")])  # a library file changes
    sync.library_health()
    assert calls["n"] == 5


def test_pending_entries_without_any_writer_are_missing_files(workspace, monkeypatch):
    """F2 (UX): without a library writer the new library's files never come – the check said „Keine Fehler“
    while the overview showed „14 Dateien fehlen“."""
    from partforge.db import seed_examples

    def unavailable(*_a, **_k):
        raise libwriter.WriterUnavailable("Kein Bibliotheks-Writer verfügbar – bitte den Pfad eintragen.")

    monkeypatch.setattr(sync, "get_writer", unavailable)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    seed_examples(workspace)
    report = sync.library_health(refresh=True)
    missing = by_check(report, "library_file_missing")
    assert missing and all(i.severity == "error" and "kein Bibliotheks-Writer" in i.message for i in missing)
    assert missing[0].fix_hint == "Kein Bibliotheks-Writer verfügbar – bitte den Pfad eintragen."
    assert report["affected_parts"] > 0
