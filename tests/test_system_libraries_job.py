"""Final messages of the job "Bibliotheken schreiben" (routes_system._write_libraries): every outcome ends with a
German sentence, and a database that went away under the job counts as a library switch (``cancel_reason``)."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from partforge.altium import sync
from partforge.api import routes_system
from partforge.db import close_database, open_database
from partforge.jobs import CANCEL_LIBRARY_SWITCH, CANCELLED_BY_SWITCH_MESSAGE, JobManager
from partforge.workspace import Workspace

TITLE = routes_system.LIBRARY_SYNC_JOB_TITLE


@pytest.fixture
def manager() -> Iterator[JobManager]:
    mgr = JobManager(max_workers=1)
    try:
        yield mgr
    finally:
        mgr.shutdown()


def test_libraries_written_message() -> None:
    message = routes_system.libraries_written_message
    assert message({"symbols": {"total": 15, "ok": 15}, "footprints": {"total": 13, "ok": 13}}) == (
        "Bibliotheken geschrieben: 15 Symbole und 13 Footprints")
    assert message({"symbols": {"total": 2, "ok": 1, "error": 1}, "footprints": {"total": 2, "ok": 1, "missing": 1}}) == (
        "Bibliotheken geschrieben: 1 Symbol und 1 Footprint, 1 Fehler, 1 Eintrag nicht erzeugbar")
    assert message({"symbols": {"total": 3, "ok": 0, "error": 2, "missing": 1}, "footprints": {"total": 0}}) == (
        "Bibliotheken nicht geschrieben: 2 Fehler, 1 Eintrag nicht erzeugbar")
    assert message({"symbols": {}, "footprints": {}, "libraries": []}) == "Bibliotheken sind aktuell – nichts zu schreiben"
    assert message({"skipped": True, "reason": "kein Writer"}) == routes_system.NOT_WRITTEN_NO_WRITER


def test_job_without_writer_or_library_says_so(workspace: Workspace, tmp_path: Path, manager: JobManager,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: pytest.fail("darf nicht laufen"))
    monkeypatch.setattr(routes_system, "_writer_problem", lambda _ws: "Kein Bibliotheks-Writer verfügbar (Test).")
    job = manager.run_sync("libraries", TITLE, routes_system._write_libraries, workspace.root)
    assert job.status == "done" and job.message == routes_system.NOT_WRITTEN_NO_WRITER
    assert job.result["skipped"] is True and job.result["reason"].startswith("Kein Bibliotheks-Writer verfügbar (Test).")
    assert [e["level"] for e in job.log] == ["warn"]
    gone = manager.run_sync("libraries", TITLE, routes_system._write_libraries, tmp_path / "andere Bibliothek")
    assert gone.status == "done" and gone.message == routes_system.NOT_WRITTEN_CLOSED
    assert "nicht mehr geöffnet" in gone.result["reason"] and [e["level"] for e in gone.log] == ["warn"]


def test_job_reports_what_it_wrote(workspace: Workspace, manager: JobManager, monkeypatch: pytest.MonkeyPatch) -> None:
    summary: dict[str, Any] = {
        "symbols": {"total": 3, "ok": 2, "error": 1, "missing": 0, "adopted": 0},
        "footprints": {"total": 1, "ok": 1, "error": 0, "missing": 0, "adopted": 0},
        "libraries": ["Symbols\\PF_Passives.SchLib"],
        "errors": [{"kind": "symbol", "name": "X", "message": "kaputt"}],
        "missing": [],
        "relinked": 0,
    }

    def fake_sync(ctx: Any = None) -> dict[str, Any]:
        ctx.progress(0.9, "Footprints: PF_CHIP.PcbLib wird geschrieben …")
        return summary

    monkeypatch.setattr(routes_system, "_writer_problem", lambda _ws: None)
    monkeypatch.setattr(sync, "sync_pending", fake_sync)
    job = manager.run_sync("libraries", TITLE, routes_system._write_libraries, workspace.root)
    assert job.status == "done" and job.result is summary
    assert job.message == "Bibliotheken geschrieben: 2 Symbole und 1 Footprint, 1 Fehler"
    assert (job.log[-1]["level"], job.log[-1]["text"]) == ("warn", job.message)
    summary["symbols"] = {"total": 3, "ok": 3, "error": 0, "missing": 0}
    clean = manager.run_sync("libraries", TITLE, routes_system._write_libraries, workspace.root)
    assert clean.message == "Bibliotheken geschrieben: 3 Symbole und 1 Footprint"
    assert (clean.log[-1]["level"], clean.log[-1]["text"]) == ("success", clean.message)


def test_database_closed_under_the_job_counts_as_library_switch(workspace: Workspace, manager: JobManager,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    def closing_sync(ctx: Any = None) -> dict[str, Any]:
        close_database()  # the database goes away bypassing the guard (e.g. a test or a restore)
        raise RuntimeError("Datenbank geschlossen")

    monkeypatch.setattr(routes_system, "_writer_problem", lambda _ws: None)
    monkeypatch.setattr(sync, "sync_pending", closing_sync)
    try:
        job = manager.run_sync("libraries", TITLE, routes_system._write_libraries, workspace.root)
    finally:
        open_database(workspace)
    assert job.status == "cancelled" and job.error is None
    assert job.cancel_reason == CANCEL_LIBRARY_SWITCH and job.message == CANCELLED_BY_SWITCH_MESSAGE
    assert [e["text"] for e in job.log] == [
        f"Die Bibliothek wird geschlossen oder gewechselt – Schreiben abgebrochen. {routes_system._PENDING_HINT}"]
