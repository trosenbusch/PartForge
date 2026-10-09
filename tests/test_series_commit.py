"""Series commit end to end on a temporary library (altium.sync monkeypatched – no writer, no Altium)."""
from __future__ import annotations

from typing import Any

import pytest

from partforge import events
from partforge.altium import sync
from partforge.db import backup, parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.domain.series import SeriesRequest, commit, preview
from partforge.jobs import JobManager
from partforge.workspace import Workspace


def req(**kw: Any) -> SeriesRequest:
    base: dict[str, Any] = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "tolerance": "1%",
                            "values": ["1k", "4.7k", "10k"], "include_jumper": True}
    base.update(kw)
    return SeriesRequest.model_validate(base)


@pytest.fixture
def fake_sync(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """ensure_symbols/ensure_footprints that register the records as written (status ok)."""
    calls: dict[str, list[Any]] = {"symbols": [], "footprints": []}

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None):
        calls["symbols"].append((list(specs), category))
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF_Passives.SchLib", spec=s,
                                                     status="ok") for s in specs])

    def ensure_footprints(specs, *, source="generated", ctx=None):
        calls["footprints"].append(list(specs))
        return registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF_CHIP.PcbLib",
                                                           spec=s, family=s.family, status="ok") for s in specs])

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    return calls


def test_commit_creates_parts_symbol_and_footprints(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    seen: list[tuple[Any, ...]] = []
    unsubscribe = events.subscribe(events.PARTS_CHANGED, lambda *args: seen.append(args))
    try:
        planned = preview(req())
        summary = commit(None, req())
    finally:
        unsubscribe()
    assert summary["created"] == 4 and summary["errors"] == 0 and summary["skipped"] == 0
    assert summary["symbol"] == "Resistor" and summary["symbol_created"]
    assert summary["footprints_created"] == ["RESC1608X50N"] and not summary["pending"]
    assert summary["backup"] and summary["backup"].startswith("PartForge_")
    assert set(summary["created_part_numbers"]) == {"CRCW06031K00FKEA", "CRCW06034K70FKEA", "CRCW060310K0FKEA",
                                                    "CRCW06030000Z0EA"}
    assert seen and set(seen) == {("Resistors", True)}  # announced by db.parts (parts + jumper batch)
    assert fake_sync["symbols"][0][1] == "Resistors" and fake_sync["symbols"][0][0][0].name == "Resistor"
    assert [s.name for s in fake_sync["footprints"][0]] == ["RESC1608X50N"]
    stored = parts.get_part("Resistors", "CRCW060310K0FKEA")
    assert stored is not None
    row = next(r for r in planned.rows if r.mpn == "CRCW060310K0FKEA")
    for column, value in row.values.items():
        assert stored[column] == value, column
    assert stored["Library Path"] == "Symbols\\PF_Passives.SchLib"
    assert stored["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"
    assert stored["Description"] == "RES 0603 10kΩ ±1% 0.1W Dickschicht" and stored["Comment"] == "10k"
    assert stored["PF Status"] == "Entwurf" and stored["Lifecycle"] == "Aktiv"
    assert stored["ComponentLink1Description"] == "Datenblatt"
    jumper = parts.get_part("Resistors", "CRCW06030000Z0EA")
    assert jumper is not None and jumper["Resistance"] == "0Ω" and jumper["Tolerance"] is None
    assert backup.list_backups()


def test_commit_modes(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    commit(None, req(include_jumper=False))
    again = commit(None, req(include_jumper=False))
    assert again["created"] == 0 and again["skipped"] == 3
    parts.update_part("Resistors", "CRCW060310K0FKEA", {"TCR": "±250ppm/K", "Supplier 1": "Mouser"})
    updated = commit(None, req(include_jumper=False, values=["10k", "22k"]), mode="update")
    assert updated["updated"] == 1 and updated["created"] == 1
    refreshed = parts.get_part("Resistors", "CRCW060310K0FKEA")
    assert refreshed is not None and refreshed["TCR"] == "±100ppm/K" and refreshed["Supplier 1"] == "Mouser"
    unchanged = commit(None, req(include_jumper=False, values=["10k"]), mode="update")
    assert unchanged["unchanged"] == 1 and unchanged["updated"] == 0
    with pytest.raises(ValueError, match="Modus"):
        commit(None, req(), mode="error")  # type: ignore[arg-type]


def test_conflicts_and_invalid_rows_are_not_written(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    parts.create_part("Capacitors", {"Part Number": "CRCW06034K70FKEA", "Manufacturer": "x",
                                     "Manufacturer Part Number": "x", "Capacitance": "1n", "Voltage": "50V",
                                     "Library Ref": "CAP", "Footprint Ref": "C"})
    summary = commit(None, req(include_jumper=False, values=["1k", "4.7k", "22M"]))
    assert summary["created"] == 1 and summary["conflicts"] == 1 and summary["invalid"] == 1
    assert parts.get_part("Resistors", "CRCW06034K70FKEA") is None


def test_nothing_to_write(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    summary = commit(None, req(include_jumper=False, values=["22M"]))
    assert summary["created"] == 0 and summary["invalid"] == 1 and not fake_sync["symbols"]


def test_pending_registry_when_sync_is_not_available(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    def not_implemented(*args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    monkeypatch.setattr(sync, "ensure_symbols", not_implemented)
    monkeypatch.setattr(sync, "ensure_footprints", not_implemented)
    summary = commit(None, SeriesRequest(template_id="kemet-c-x7r", sizes=["0603"], voltages=["50V"],
                                         values=["100n", "10n"]))
    assert summary["created"] == 2
    assert len(summary["pending"]) == 1 + len(registry.list_footprints())  # one note per symbol/footprint
    symbol = registry.get_symbol("Capacitor")
    assert symbol is not None and symbol.status == "pending" and symbol.library == "Symbols\\PF_Passives.SchLib"
    assert symbol.spec is not None and symbol.kind == "capacitor"
    footprints = {f.name: f for f in registry.list_footprints()}
    assert footprints and all(f.status == "pending" for f in footprints.values())
    stored = parts.get_part("Capacitors", "C0603C104K5RACTU")
    assert stored is not None and stored["Library Path"] == "Symbols\\PF_Passives.SchLib"
    assert stored["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"
    assert stored["Footprint Ref"] in footprints and stored["Height"] == "0.95mm"
    again = commit(None, SeriesRequest(template_id="kemet-c-x7r", sizes=["0603"], voltages=["50V"], values=["1n"]))
    assert again["created"] == 1 and not again["symbol_created"]


def test_commit_as_job_with_progress_and_cancel(workspace: Workspace, fake_sync: dict[str, list[Any]],
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("series", "Serie", commit, req(), "skip")
        assert job.status == "done", job.error
        assert job.progress == 1.0 and job.result["created"] == 4
        assert any("4 neu" in entry["text"] for entry in job.log)

        def cancelling(specs, *, source="generated", ctx=None):
            ctx.job.cancel_requested = True
            return []

        monkeypatch.setattr(sync, "ensure_footprints", cancelling)
        cancelled = manager.run_sync("series", "Serie", commit, req(values=["33k"], include_jumper=False), "skip")
        assert cancelled.status == "cancelled"
        assert parts.get_part("Resistors", "CRCW060333K0FKEA") is None
    finally:
        manager.shutdown()


def test_writer_errors_block_the_rows_and_are_reported(workspace: Workspace,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """INT-04/F1: a symbol/footprint that was not written is never reported as created, and the rows using it
    are not written (like the datasheet commit) – the parts would point to a component missing from the file."""
    def failing_symbols(specs, *, category=None, source="generated", ctx=None):
        return [SymbolRecord(name=s.name, library="Symbols\\PF_Passives.SchLib", status="error",
                             status_message="Rust-Writer nicht gefunden") for s in specs]

    def failing_footprints(specs, *, source="generated", ctx=None):
        return [FootprintRecord(name=s.name, library="Footprints\\PF_CHIP.PcbLib", status="error",
                                status_message="Rust-Writer nicht gefunden") for s in specs]

    monkeypatch.setattr(sync, "ensure_symbols", failing_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", failing_footprints)
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("series", "Serie", commit, req(include_jumper=False, values=["10k"]), "skip")
    finally:
        manager.shutdown()
    assert job.status == "done" and job.result["created"] == 0 and job.result["errors"] == 1
    assert not job.result["symbol_created"] and job.result["footprints_created"] == []
    assert job.result["error_details"]["CRCW060310K0FKEA"].startswith("Nicht angelegt – Symbol „Resistor“")
    problems = {(p["kind"], p["name"]): p for p in job.result["library_problems"]}
    assert problems[("symbol", "Resistor")]["status"] == "error"
    assert problems[("footprint", "RESC1608X50N")] == {
        "kind": "footprint", "name": "RESC1608X50N", "library": "Footprints\\PF_CHIP.PcbLib", "status": "error",
        "message": "Rust-Writer nicht gefunden", "parts": 1}
    assert any("„RESC1608X50N“ wurde nicht in Footprints\\PF_CHIP.PcbLib geschrieben" in w
               for w in job.result["warnings"])
    assert "1 Fehler" in job.message and "1 Symbol nicht geschrieben" in job.message
    assert "1 Footprint nicht geschrieben" in job.message
    warnings = [e["text"] for e in job.log if e["level"] == "warn"]
    assert any("Symbol Resistor" in w for w in warnings) and any("Footprint RESC1608X50N" in w for w in warnings)
    assert parts.get_part("Resistors", "CRCW060310K0FKEA") is None


def test_only_rows_of_the_failed_footprint_are_refused(workspace: Workspace, fake_sync: dict[str, list[Any]],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """File locked (PF_CHIP.PcbLib, other process): 2512 fails, 0603 is written – one series, two outcomes."""
    written = sync.ensure_footprints

    def locked(specs, *, source="generated", ctx=None):
        good = [s for s in specs if not s.name.startswith("RESC6332")]
        records = written(good, source=source, ctx=ctx) if good else []
        bad = [FootprintRecord(name=s.name, library="Footprints\\PF_CHIP.PcbLib", spec=s, status="error",
                               status_message="konnte vor dem Schreiben nicht gesichert werden: Permission denied")
               for s in specs if s.name.startswith("RESC6332")]
        return [*records, *registry.upsert_footprints(bad)]

    monkeypatch.setattr(sync, "ensure_footprints", locked)
    summary = commit(None, req(sizes=["0603", "2512"], include_jumper=False, values=["1k", "10k"]))
    assert summary["created"] == 2 and summary["errors"] == 2
    assert summary["footprints_created"] == ["RESC1608X50N"]
    assert [(p["name"], p["status"], p["parts"]) for p in summary["library_problems"]] == [
        ("RESC6332X70N", "error", 2)]
    assert all(v.startswith("Nicht angelegt – Footprint „RESC6332X70N“ konnte nicht geschrieben werden")
               for v in summary["error_details"].values())
    assert len(summary["error_details"]) == 2
    assert summary["message"] == ("Serie erzeugt: 2 neu, 0 aktualisiert, 0 übersprungen, 2 Fehler, 1 Footprint neu, "
                                  "1 Footprint nicht geschrieben")
    for pn in summary["error_details"]:
        assert parts.get_part("Resistors", pn) is None
    assert parts.get_part("Resistors", "CRCW06031K00FKEA") is not None


def test_pending_symbols_and_footprints_are_reported(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    """No library writer: the entries stay pending, the parts are written, the result says what is missing."""
    def pending_symbols(specs, *, category=None, source="generated", ctx=None):
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF_Passives.SchLib", spec=s,
                                                     status="pending",
                                                     status_message="Kein Bibliotheks-Writer verfügbar")
                                        for s in specs])

    def pending_footprints(specs, *, source="generated", ctx=None):
        return registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF_CHIP.PcbLib", spec=s,
                                                           status="pending",
                                                           status_message="Kein Bibliotheks-Writer verfügbar")
                                           for s in specs])

    monkeypatch.setattr(sync, "ensure_symbols", pending_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", pending_footprints)
    summary = commit(None, req(include_jumper=False, values=["10k"]))
    assert summary["created"] == 1 and summary["errors"] == 0
    assert not summary["symbol_created"] and summary["footprints_created"] == []
    assert {(p["kind"], p["status"]) for p in summary["library_problems"]} == {("symbol", "pending"),
                                                                               ("footprint", "pending")}
    assert len(summary["pending"]) == 2
    assert all("Bibliotheksdateien synchronisieren" in n for n in summary["pending"])
    assert summary["message"].endswith("1 Symbol ausstehend, 1 Footprint ausstehend")
    assert parts.get_part("Resistors", "CRCW060310K0FKEA") is not None


def test_footprint_log_counts_only_new_footprints(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    """K8: footprints that are registered already are checked, not "angelegt"."""
    commit(None, req(include_jumper=False, values=["1k"]))
    ctx = RecordingJob()
    commit(ctx, req(include_jumper=False, values=["2.2k"]), "skip")  # type: ignore[arg-type]
    texts = [e["text"] for e in ctx.job.log]
    assert "1 vorhandener Footprint wird geprüft …" in texts and "Symbol „Resistor“ wird geprüft …" in texts
    ctx = RecordingJob()
    commit(ctx, req(sizes=["0603", "0805"], include_jumper=False, values=["3.3k"]), "skip")  # type: ignore[arg-type]
    assert "1 Footprint wird angelegt (1 vorhanden) …" in [e["text"] for e in ctx.job.log]


def test_internal_part_numbers_are_assigned(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    workspace.settings.part_number_scheme = "internal"
    summary = commit(None, req(include_jumper=False, values=["10k"]))
    assert summary["created"] == 1
    pn = summary["created_part_numbers"][0]
    assert pn.startswith("R-")
    stored = parts.get_part("Resistors", pn)
    assert stored is not None and stored["Manufacturer Part Number"] == "CRCW060310K0FKEA"
    again = commit(None, req(include_jumper=False, values=["10k"]))
    assert again["created"] == 0 and again["skipped"] == 1


class RecordingJob:
    """Job context that records every progress message, detail update and log line (thread-free)."""

    def __init__(self) -> None:
        from partforge.jobs import Job

        self.job = Job(id="t", kind="series", title="Serie")
        self.details: list[dict[str, Any]] = []
        self.messages: list[str] = []

    def progress(self, fraction: float | None = None, message: str | None = None) -> None:
        if fraction is not None:
            self.job.progress = fraction
        if message is not None:
            self.job.message = message
            self.messages.append(message)

    def detail(self, **fields: Any) -> None:
        for key, value in fields.items():
            if value is None:
                self.job.detail.pop(key, None)
            else:
                self.job.detail[key] = value
        self.details.append(dict(self.job.detail))

    def log(self, text: str, level: str = "info") -> None:
        self.job.log.append({"ts": 0.0, "level": level, "text": text})

    @property
    def cancelled(self) -> bool:
        return False

    @property
    def cancel_reason(self) -> str | None:
        return None

    def check_cancelled(self) -> None:
        return None


def test_commit_job_logs_phases_and_structured_progress(workspace: Workspace,
                                                        fake_sync: dict[str, list[Any]]) -> None:
    from partforge.domain.series import SeriesCommitResult

    ctx = RecordingJob()
    summary = commit(ctx, req(sizes=["0603", "0805"]), "skip")  # type: ignore[arg-type]
    result = SeriesCommitResult.model_validate(summary)  # the job result is the typed model
    assert result.created == 8 and result.footprints_created == ["RESC1608X50N", "RESC2012X60N"]
    expected = "Serie erzeugt: 8 neu, 0 aktualisiert, 0 übersprungen, 2 Footprints neu"
    assert result.message == expected and ctx.job.message == expected
    texts = [e["text"] for e in ctx.job.log]
    for line in ("Serie wird berechnet …", "Serie berechnet: 8 Zeilen – 8 neu, 0 vorhanden.",
                 "Symbol „Resistor“ wird angelegt …", "2 Footprints werden angelegt …", "Sicherung wird angelegt …",
                 "8 Bauteile werden gespeichert …", expected):
        assert line in texts, (line, texts)
    assert ctx.job.log[-1] == {"ts": 0.0, "level": "success", "text": expected}
    phases = [d.get("phase") for d in ctx.details]
    assert [p for i, p in enumerate(phases) if i == 0 or p != phases[i - 1]] == [
        "plan", "symbol", "footprints", "backup", "parts", "done"]
    footprints = [d for d in ctx.details if d.get("phase") == "footprints"]
    assert footprints[0]["total"] == 2 and footprints[-1]["done"] == 2
    stored = [d for d in ctx.details if d.get("phase") == "parts"]
    assert stored[0] == {"phase": "parts", "done": 0, "total": 8} and stored[-1]["done"] == 8
    assert all(b["done"] >= a["done"] for a, b in zip(stored, stored[1:], strict=False))  # never backwards
    assert ctx.job.detail == {"phase": "done", "done": 8, "total": 8}
    assert ctx.messages[0] == "Serie wird berechnet …" and ctx.messages[-1] == expected
    assert ctx.job.progress == 1.0


def test_final_message_formats_numbers_and_mentions_rows_not_written(workspace: Workspace,
                                                                     fake_sync: dict[str, list[Any]]) -> None:
    from partforge.domain.series import SeriesCommitResult, _final_message

    big = SeriesCommitResult(table="Resistors", template="x", rows=1260, created=1248, updated=12,
                             footprints_created=["A"] * 6)
    assert _final_message(big) == "Serie erzeugt: 1.248 neu, 12 aktualisiert, 0 übersprungen, 6 Footprints neu"
    one = SeriesCommitResult(table="Resistors", template="x", rows=3, created=1, unchanged=2, errors=1,
                             footprints_created=["A"], invalid=1, conflicts=1)
    assert _final_message(one) == ("Serie erzeugt: 1 neu, 0 aktualisiert, 2 unverändert, 0 übersprungen, 1 Fehler, "
                                   "1 Footprint neu (nicht geschrieben: 1 ungültig, 1 Konflikt)")
    ctx = RecordingJob()
    nothing = commit(ctx, req(include_jumper=False, values=["22M"]), "skip")  # type: ignore[arg-type]
    assert nothing["message"] == "Serie: nichts zu schreiben – 1 ungültig." == ctx.job.message
    assert ctx.job.detail == {"phase": "done", "done": 0, "total": 0}
    commit(None, req(include_jumper=False))
    again = commit(RecordingJob(), req(include_jumper=False), "skip")  # type: ignore[arg-type]
    assert again["message"] == "Serie: nichts zu schreiben – 3 bereits vorhanden."


def test_jumper_batch_has_no_required_field_notes(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    """db.parts knows that tolerance, TCR, power and voltage do not apply to a 0-Ω jumper (K9): no "Pflichtfeld
    ist leer" notes."""
    summary = commit(None, req(values=["10k"]))
    assert summary["created"] == 2 and summary["part_warnings"] == {}
    jumper = parts.get_part("Resistors", "CRCW06030000Z0EA")
    assert jumper is not None and jumper["Power"] is None and jumper["Notes"].endswith("Nennstrom 2A")


def test_footprint_written_after_a_failure_counts_as_new(workspace: Workspace, fake_sync: dict[str, list[Any]],
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """A footprint registered with status error is not in its file: writing it later is „neu angelegt“."""
    working = sync.ensure_footprints

    def failing(specs, *, source="generated", ctx=None):
        return registry.upsert_footprints([FootprintRecord(name=s.name, library=r"Footprints\PF_CHIP.PcbLib", spec=s,
                                                           status="error", status_message="gesperrt") for s in specs])

    monkeypatch.setattr(sync, "ensure_footprints", failing)
    first = commit(None, req(include_jumper=False, values=["1k"]))
    assert first["created"] == 0 and first["footprints_created"] == []
    monkeypatch.setattr(sync, "ensure_footprints", working)
    ctx = RecordingJob()
    again = commit(ctx, req(include_jumper=False, values=["1k"]), "skip")  # type: ignore[arg-type]
    assert again["created"] == 1 and again["footprints_created"] == ["RESC1608X50N"]
    assert "1 Footprint wird angelegt …" in [e["text"] for e in ctx.job.log]
