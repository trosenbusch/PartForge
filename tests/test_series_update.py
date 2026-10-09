"""Series commit: updating existing parts, staying in the planned library, monotonic job progress
(altium.sync monkeypatched – no writer, no Altium)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from partforge.altium import sync
from partforge.db import close_database, open_database, parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.domain.series import LIBRARY_SWITCHED, SeriesRequest, commit, preview
from partforge.jobs import JobCancelled, JobContext, JobManager
from partforge.workspace import Workspace, set_current

PN = "CRCW060310K0FKEA"


def req(**kw: Any) -> SeriesRequest:
    base: dict[str, Any] = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "tolerance": "1%", "values": ["10k"]}
    base.update(kw)
    return SeriesRequest.model_validate(base)


@pytest.fixture
def fake_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """ensure_* that register the records as written and report progress 0..1 like the real sync."""

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None):
        if ctx is not None:
            ctx.progress(0.0, "Symbole …")
            ctx.check_cancelled()
            ctx.progress(1.0, "Symbole fertig")
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF_Passives.SchLib", spec=s,
                                                     status="ok") for s in specs])

    def ensure_footprints(specs, *, source="generated", ctx=None):
        if ctx is not None:
            ctx.progress(0.0, "Footprints …")
            ctx.check_cancelled()
            ctx.progress(1.0, "Footprints fertig")
        return registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF_CHIP.PcbLib", spec=s,
                                                           family=s.family, status="ok") for s in specs])

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)


CURATED = {"PF Status": "Freigegeben", "Lifecycle": "Abgekündigt", "ComponentLink1URL": "Datasheets\\crcw_local.pdf",
           "ComponentLink1Description": "Datenblatt (lokal)", "Footprint Ref": "MY_0603_FP", "Library Ref": "MY_RES",
           "TCR": "±250ppm/K", "Supplier 1": "Mouser"}


def test_update_keeps_release_status_lifecycle_link_and_links(workspace: Workspace, fake_sync: None) -> None:
    """Regression: update mode set PF Status back to "Entwurf", Lifecycle to "Aktiv" and replaced the
    datasheet link and a hand-picked footprint."""
    commit(None, req())
    parts.update_part("Resistors", PN, CURATED)
    row = preview(req()).rows[0]
    assert row.status == "exists"
    note = next(m for m in row.messages if m.startswith("Beim Aktualisieren bleiben erhalten"))
    for text in ("Freigabestatus „Freigegeben“", "Lebenszyklus „Abgekündigt“", "Datenblatt-Link",
                 "Symbol „MY_RES“", "Footprint „MY_0603_FP“"):
        assert text in note
    summary = commit(None, req(), mode="update")
    assert summary["updated"] == 1 and summary["errors"] == 0
    stored = parts.get_part("Resistors", PN)
    assert stored is not None
    for column, value in CURATED.items():
        if column != "TCR":
            assert stored[column] == value, column
    assert stored["TCR"] == "±100ppm/K"  # datasheet values are refreshed
    assert stored["Footprint Path"] is None  # the hand-picked footprint is not registered – nothing invented


def test_replace_links_and_explicit_values(workspace: Workspace, fake_sync: None) -> None:
    commit(None, req())
    parts.update_part("Resistors", PN, CURATED)
    summary = commit(None, req(replace_links=True, datasheet_url="https://example.com/crcw.pdf",
                               field_overrides={"Lifecycle": "NRND"}), mode="update")
    assert summary["updated"] == 1
    stored = parts.get_part("Resistors", PN)
    assert stored is not None
    assert stored["Footprint Ref"] == "RESC1608X50N" and stored["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"
    assert stored["Library Ref"] == "Resistor" and stored["Library Path"] == "Symbols\\PF_Passives.SchLib"
    assert stored["ComponentLink1URL"] == "https://example.com/crcw.pdf"
    assert stored["ComponentLink1Description"] == "Datenblatt"
    assert stored["Lifecycle"] == "NRND"
    assert stored["PF Status"] == "Freigegeben"  # the release workflow is never touched by a series


def test_empty_curated_columns_are_filled(workspace: Workspace, fake_sync: None) -> None:
    parts.create_part("Resistors", {"Part Number": PN, "Manufacturer": "Vishay", "Manufacturer Part Number": PN,
                                    "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Library Ref": "Resistor",
                                    "Footprint Ref": "RESC1608X50N"})
    parts.update_part("Resistors", PN, {"PF Status": "Geprüft"})
    summary = commit(None, req(), mode="update")
    assert summary["updated"] == 1
    stored = parts.get_part("Resistors", PN)
    assert stored is not None and stored["Lifecycle"] == "Aktiv" and stored["PF Status"] == "Geprüft"
    assert stored["ComponentLink1URL"] == "https://www.vishay.com/docs/20035/dcrcwe3.pdf"
    assert stored["Footprint Path"] == "Footprints\\PF_CHIP.PcbLib"


def test_template_lifecycle_replaces_only_the_series_default(workspace: Workspace, fake_sync: None) -> None:
    """Panasonic marks 1206 and larger NRND: that replaces "Aktiv", never a user's "Abgekündigt"."""
    request = SeriesRequest(template_id="panasonic-erj-1pct", sizes=["1206"], values=["10k", "22k"])
    commit(None, request)
    assert parts.get_part("Resistors", "ERJ-8ENF1002V")["Lifecycle"] == "NRND"  # type: ignore[index]
    parts.update_part("Resistors", "ERJ-8ENF1002V", {"Lifecycle": "Aktiv"})
    parts.update_part("Resistors", "ERJ-8ENF2202V", {"Lifecycle": "Abgekündigt"})
    commit(None, request, mode="update")
    assert parts.get_part("Resistors", "ERJ-8ENF1002V")["Lifecycle"] == "NRND"  # type: ignore[index]
    assert parts.get_part("Resistors", "ERJ-8ENF2202V")["Lifecycle"] == "Abgekündigt"  # type: ignore[index]


def test_update_of_part_found_by_mpn(workspace: Workspace, fake_sync: None) -> None:
    parts.create_part("Resistors", {"Part Number": "R-10K-0603", "Manufacturer": "Vishay",
                                    "Manufacturer Part Number": PN, "Resistance": "10k", "Tolerance": "1%",
                                    "Power": "0.1W", "TCR": "±250ppm/K", "Library Ref": "Resistor",
                                    "Footprint Ref": "RESC1608X50N"})
    skipped = commit(None, req())
    assert skipped["created"] == 0 and skipped["skipped"] == 1
    updated = commit(None, req(), mode="update")
    assert updated["updated"] == 1 and updated["created"] == 0
    found, total = parts.query_parts("Resistors", search=PN, limit=0)
    assert total == 1 and found[0]["Part Number"] == "R-10K-0603" and found[0]["TCR"] == "±100ppm/K"


# --------------------------------------------------------------------------- library binding


def test_library_switch_during_commit_writes_nothing_elsewhere(workspace: Workspace, tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a library opened while the job ran received the backup and the parts."""
    other = Workspace.create(tmp_path / "Andere", name="Andere Bibliothek")

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None):
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF.SchLib", spec=s, status="ok")
                                        for s in specs])

    def ensure_footprints(specs, *, source="generated", ctx=None):
        records = registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF.PcbLib", spec=s,
                                                              status="ok") for s in specs])
        from partforge import events

        close_database()  # the user opens another library while the library files are written
        open_database(other)
        set_current(other)
        events.emit(events.WORKSPACE_CLOSED)
        events.emit(events.WORKSPACE_OPENED, other)
        return records

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("series", "Serie", commit, req(), "skip")
    finally:
        manager.shutdown()
    assert job.status == "cancelled"
    assert any(entry["text"] == LIBRARY_SWITCHED and entry["level"] == "warn" for entry in job.log)
    assert parts.get_part("Resistors", PN) is None  # nothing in the other library
    assert not other.backups_dir.exists() or not any(other.backups_dir.iterdir())  # no backup there either
    close_database()
    open_database(workspace)
    set_current(workspace)
    assert parts.get_part("Resistors", PN) is None


def test_switch_without_event_is_detected_too(workspace: Workspace, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    other = Workspace.create(tmp_path / "Zweite", name="Zweite")

    def ensure_footprints(specs, *, source="generated", ctx=None):
        close_database()
        open_database(other)
        set_current(other)
        return []

    monkeypatch.setattr(sync, "ensure_symbols", lambda specs, **kw: [])
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    with pytest.raises(JobCancelled):
        commit(None, req())
    assert parts.get_part("Resistors", PN) is None


def test_job_for_another_library_does_not_run(workspace: Workspace, fake_sync: None, tmp_path: Path) -> None:
    """The API passes the library open at submit time; a job that starts later in another library stops."""
    with pytest.raises(JobCancelled):
        commit(None, req(), library=tmp_path / "Gar-nicht-offen")
    assert parts.get_part("Resistors", PN) is None
    summary = commit(None, req(), library=workspace.root)
    assert summary["created"] == 1


# --------------------------------------------------------------------------- progress


def test_progress_never_goes_backwards(workspace: Workspace, fake_sync: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: the raw job context went to ensure_* (0..1) – the bar jumped to 100 % and back."""
    seen: list[float] = []
    original = JobContext.progress

    def spy(self: JobContext, fraction: float | None = None, message: str | None = None) -> None:
        if fraction is not None:
            seen.append(round(float(fraction), 4))
        original(self, fraction, message)

    monkeypatch.setattr(JobContext, "progress", spy)
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("series", "Serie", commit, req(values=["10k", "22k"], include_jumper=True), "skip")
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    assert seen == sorted(seen) and seen[-1] == 1.0
    assert len(seen) >= 8  # symbol, footprints, backup, parts and jumper batch all report
