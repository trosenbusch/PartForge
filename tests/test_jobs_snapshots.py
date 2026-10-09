"""Job snapshots (partforge.jobs): brief results for job lists, structured progress (``detail``),
``cancel_reason``/``cancel_requested``, the final message of every job (safety net, cancel and failure
texts) and the user-facing error texts."""
from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from partforge.db.errors import CategoryNotFound, DatabaseNotOpen
from partforge.importers.spreadsheet import SpreadsheetError
from partforge.jobs import (
    BRIEF_RESULT_MAX_BYTES,
    CANCEL_LIBRARY_SWITCH,
    CANCELLED_BY_SWITCH_MESSAGE,
    CANCELLED_MESSAGE,
    DONE_MESSAGE,
    Job,
    JobCancelled,
    JobContext,
    JobManager,
    LibraryBusy,
    LibraryChanged,
    brief_result,
    error_text,
    is_progress_text,
)


def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Bedingung nicht erreicht")


def compact_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


@pytest.fixture
def manager() -> Iterator[JobManager]:
    mgr = JobManager(max_workers=2)
    try:
        yield mgr
    finally:
        mgr.shutdown()


def big_import_result() -> dict[str, Any]:
    """Shaped like the result of a large import."""
    return {
        "outcome": "partial",
        "message": "Import fertig: 600 neu, 250 abgelehnt",
        "strict": False,
        "created": 600,
        "ratio": 0.5,
        "backup": None,
        "note": "x" * 300,
        "error_count": 250,
        "errors": {f"R-{i:04d}": "Widerstand: Pflichtfeld ist leer." for i in range(250)},
        "warnings": [f"Warnung {i}" for i in range(30)],
        "missing": [],
        "created_part_numbers": [f"R-{i:04d}" for i in range(600)],
        "nested": {"a": 1, "b": [1, 2]},
    }


# --------------------------------------------------------------------------- brief results


def test_brief_result_keeps_small_results_unchanged() -> None:
    small = {"created": 3, "errors": {"R-1": "kaputt"}, "created_part_numbers": ["R-1", "R-2"]}
    assert brief_result(small) is small
    assert brief_result(None) is None
    assert brief_result([1, 2, 3]) == [1, 2, 3]
    assert brief_result("fertig") == "fertig"


def test_brief_result_threshold_is_8_kb_of_compact_utf8_json() -> None:
    assert BRIEF_RESULT_MAX_BYTES == 8192
    at_limit = {"text": "a" * (8192 - len('{"text":""}'))}
    assert compact_size(at_limit) == 8192 and brief_result(at_limit) is at_limit
    over = {"text": "a" * (8193 - len('{"text":""}'))}
    assert compact_size(over) == 8193
    assert brief_result(over) == {"text": "a" * 199 + "…", "result_truncated": True}
    # bytes, not characters: "ä" counts twice
    umlauts = {"text": "ä" * 4091}
    assert len(json.dumps(umlauts, ensure_ascii=False, separators=(",", ":"))) < 8192 < compact_size(umlauts)
    assert brief_result(umlauts)["result_truncated"] is True


def test_brief_result_keeps_scalars_counts_and_samples() -> None:
    result = big_import_result()
    brief = brief_result(result)
    assert brief == {
        "outcome": "partial",
        "message": "Import fertig: 600 neu, 250 abgelehnt",
        "strict": False,
        "created": 600,
        "ratio": 0.5,
        "backup": None,
        "note": "x" * 199 + "…",  # strings up to 200 characters
        "error_count": 250,
        "errors": {f"R-{i:04d}": "Widerstand: Pflichtfeld ist leer." for i in range(5)},
        "errors_count": 250,
        "warnings": ["Warnung 0", "Warnung 1", "Warnung 2", "Warnung 3", "Warnung 4"],
        "warnings_count": 30,
        "missing": [],
        "missing_count": 0,
        "created_part_numbers_count": 600,  # other lists/dicts: only their length
        "nested_count": 2,
        "result_truncated": True,
    }
    assert len(brief["note"]) == 200
    assert compact_size(brief) < 2000
    assert result["errors"]["R-0100"]  # the job's own result is untouched


def test_brief_result_edge_cases() -> None:
    padding = ["x" * 100] * 100  # > 8 KB
    # a field "<name>_count" of the result itself wins over the computed length
    assert brief_result({"errors": padding, "errors_count": 999})["errors_count"] == 999
    # text of exactly 200 characters stays, objects and long lists go
    brief = brief_result({"exact": "y" * 200, "items": padding, "obj": object(), "none": None})
    assert brief == {"exact": "y" * 200, "items_count": 100, "none": None, "result_truncated": True}
    # results that are no dict
    assert brief_result(padding) == {"result_count": 100, "result_truncated": True}
    assert brief_result("z" * 9000) == {"result_truncated": True}
    circular: list[Any] = []
    circular.append(circular)
    assert brief_result(circular) == {"result_count": 1, "result_truncated": True}  # not encodable: shortened


def test_snapshot_brief_only_changes_large_results(manager: JobManager) -> None:
    big = manager.run_sync("import", "Import", lambda ctx: big_import_result())
    small = manager.run_sync("export", "Export", lambda ctx: {"rows": 4, "path": "C:\\x.xlsx"})
    full = big.snapshot()
    assert full["result"] == big_import_result() and len(full["result"]["created_part_numbers"]) == 600
    brief = big.snapshot(with_log=False, brief=True)
    assert brief["result"]["result_truncated"] is True and brief["result"]["created_part_numbers_count"] == 600
    assert {k: v for k, v in brief.items() if k not in ("result", "log")} == {
        k: v for k, v in full.items() if k not in ("result", "log")}
    assert brief["log"] == []
    assert small.snapshot(brief=True)["result"] == {"rows": 4, "path": "C:\\x.xlsx"}
    # computed once per result object, recomputed when the result is replaced
    assert big.snapshot(brief=True)["result"] is big.snapshot(brief=True)["result"]
    big.result = {"rows": 1}
    assert big.snapshot(brief=True)["result"] == {"rows": 1}


# --------------------------------------------------------------------------- snapshot fields and detail


def test_snapshot_fields(manager: JobManager) -> None:
    job = manager.run_sync("x", "Test", lambda ctx: ctx.progress(1.0, "Fertig: 2 Bauteile"))
    assert list(job.snapshot()) == [
        "id", "kind", "title", "status", "progress", "message", "log", "result", "error", "error_type", "detail",
        "cancel_reason", "cancel_requested", "created", "started", "finished", "version", "library", "library_name",
    ]
    snap = job.snapshot()
    assert snap["cancel_reason"] is None and snap["cancel_requested"] is False and snap["detail"] == {}
    json.dumps(snap)  # JSON-able


def test_detail_merges_removes_and_shows_in_snapshots(manager: JobManager) -> None:
    seen: list[tuple[int, dict[str, Any]]] = []

    def body(ctx: JobContext) -> dict[str, Any]:
        ctx.detail(step="pins", pages=[1, 2], cost_usd=0.12, datasheet_id="abc")
        seen.append((ctx.job.version, ctx.job.snapshot()["detail"]))
        ctx.detail(step="geometry", pages=None, unknown=None)  # None removes a key (also an unknown one)
        seen.append((ctx.job.version, ctx.job.snapshot(with_log=False, brief=True)["detail"]))
        return {}

    job = manager.run_sync("datasheet", "Datenblatt", body)
    assert seen[0][1] == {"step": "pins", "pages": [1, 2], "cost_usd": 0.12, "datasheet_id": "abc"}
    assert seen[1] == (seen[0][0] + 1, {"step": "geometry", "cost_usd": 0.12, "datasheet_id": "abc"})
    snap = job.snapshot()
    assert snap["detail"] == {"step": "geometry", "cost_usd": 0.12, "datasheet_id": "abc"}  # kept after the end
    snap["detail"]["step"] = "verändert"
    assert job.detail["step"] == "geometry"  # the snapshot holds a copy


# --------------------------------------------------------------------------- cancel reasons and final messages


def test_user_cancel_snapshot(manager: JobManager) -> None:
    started, release = threading.Event(), threading.Event()

    def body(ctx: JobContext) -> None:
        ctx.progress(0.5, "Zeile 1 von 2 …")
        started.set()
        assert release.wait(10)
        ctx.check_cancelled()

    job = manager.submit("import", "Import", body)
    assert started.wait(10)
    assert manager.cancel(job.id)
    running = job.snapshot()
    assert running["status"] == "running" and running["cancel_requested"] is True and running["cancel_reason"] is None
    release.set()
    wait_for(lambda: job.status == "cancelled")
    snap = job.snapshot()
    assert snap["cancel_reason"] is None and snap["message"] == CANCELLED_MESSAGE == "Abgebrochen"


def test_library_switch_cancel_snapshot(manager: JobManager) -> None:
    def body(ctx: JobContext) -> None:
        ctx.progress(0.3, "Bibliothek wird geschrieben …")
        ctx.cancel(CANCEL_LIBRARY_SWITCH)  # what a library switch does to a holder
        ctx.check_cancelled()

    snap = manager.run_sync("libraries.sync", "Sync", body).snapshot()
    assert snap["status"] == "cancelled" and snap["cancel_reason"] == CANCEL_LIBRARY_SWITCH == "library_switch"
    assert snap["message"] == CANCELLED_BY_SWITCH_MESSAGE
    assert snap["message"] == "Abgebrochen – die Bibliothek wurde gewechselt oder geschlossen"


def test_library_changed_counts_as_library_switch(manager: JobManager, tmp_path: Path) -> None:
    """A job whose library was gone when it ran (LibraryChanged, no cancel request) was stopped by a switch."""

    def gone(ctx: JobContext) -> None:
        raise LibraryChanged(tmp_path / "A")

    snap = manager.run_sync("series", "Serie", gone).snapshot()
    assert snap["status"] == "cancelled" and snap["cancel_reason"] == CANCEL_LIBRARY_SWITCH
    assert snap["cancel_requested"] is False and snap["message"] == CANCELLED_BY_SWITCH_MESSAGE
    assert snap["error"] is None

    def cancelled_first(ctx: JobContext) -> None:
        ctx.cancel()  # the user was first: the reason stays "by the user"
        raise LibraryChanged(tmp_path / "A")

    snap = manager.run_sync("series", "Serie", cancelled_first).snapshot()
    assert snap["cancel_reason"] is None and snap["message"] == CANCELLED_MESSAGE


def test_cancel_with_own_text(manager: JobManager) -> None:
    text = "Bibliothek gewechselt oder geschlossen – Serie abgebrochen."

    def body(ctx: JobContext) -> None:
        raise JobCancelled(text)

    assert manager.run_sync("series", "Serie", body).message == text


@pytest.mark.parametrize("last", ["Zeile 3 von 3 …", "Wird geschrieben...", "", "Schritt 2 …  ", None])
def test_safety_net_finishes_progress_texts(last: str | None, manager: JobManager) -> None:
    def body(ctx: JobContext) -> dict[str, Any]:
        if last is not None:
            ctx.progress(0.9, last)
        return {"rows": 3}

    job = manager.run_sync("x", "Test", body)
    assert job.status == "done" and job.message == DONE_MESSAGE == "Abgeschlossen"


def test_safety_net_keeps_final_messages_and_uses_the_result_text(manager: JobManager) -> None:
    def final(ctx: JobContext) -> dict[str, Any]:
        ctx.progress(1.0, "3 Bauteile angelegt")
        return {"message": "etwas anderes"}

    assert manager.run_sync("x", "Test", final).message == "3 Bauteile angelegt"

    def with_result_message(ctx: JobContext) -> dict[str, Any]:
        ctx.progress(0.85, "Installation wird geprüft …")
        return {"message": "Die DbLib ist in Altium installiert.", "summary": "nicht diese"}

    assert manager.run_sync("x", "Test", with_result_message).message == "Die DbLib ist in Altium installiert."

    def with_summary(ctx: JobContext) -> dict[str, Any]:
        ctx.progress(0.5, "Tabelle „Resistors“ wird gelesen …")
        return {"summary": "ODBC-Verbindung in Ordnung: 3 Tabellen.", "message": "Läuft …"}

    assert manager.run_sync("x", "Test", with_summary).message == "ODBC-Verbindung in Ordnung: 3 Tabellen."

    def unusable(ctx: JobContext) -> dict[str, Any]:
        return {"message": "Läuft …", "summary": {"ok": 1}}

    assert manager.run_sync("x", "Test", unusable).message == DONE_MESSAGE


def test_is_progress_text() -> None:
    assert is_progress_text("Zeile 1 von 3 …") and is_progress_text("Lädt...") and is_progress_text("")
    assert is_progress_text(None) and is_progress_text("   ") and is_progress_text("Warten … ")
    assert not is_progress_text("Import fertig: 3 neu") and not is_progress_text("Abgeschlossen")


def test_failed_job_reports_the_error_as_its_message(manager: JobManager) -> None:
    def boom(ctx: JobContext) -> None:
        ctx.progress(0.4, "Zeile 2 von 5 …")
        raise SpreadsheetError("Die Datei enthält keine Datenzeilen.")

    job = manager.run_sync("import", "Import", boom)
    assert job.status == "failed" and job.error == job.message == "Die Datei enthält keine Datenzeilen."
    assert job.error_type == "SpreadsheetError"
    assert [entry["level"] for entry in job.log] == ["error", "error"]
    assert job.log[0]["text"] == job.error and "Traceback" in job.log[1]["text"]

    def internal(ctx: JobContext) -> None:
        raise KeyError("pins")

    failed = manager.run_sync("datasheet", "Datenblatt", internal)
    assert failed.error == failed.message == "Interner Fehler (KeyError): 'pins'" and failed.error_type == "KeyError"


# --------------------------------------------------------------------------- error texts


def test_error_text_rules(tmp_path: Path) -> None:
    # German messages are shown as they are, without the Python class name
    assert error_text(ValueError("Ungültiger Wert „x“.")) == "Ungültiger Wert „x“."
    assert error_text(RuntimeError("Der Writer antwortet nicht.")) == "Der Writer antwortet nicht."
    assert error_text(OSError("Datei gesperrt")) == "Datei gesperrt"
    # PartForge's own exceptions – whatever their base class (CategoryNotFound is a KeyError)
    assert error_text(CategoryNotFound("Nope")) == "Kategorie „Nope“ nicht gefunden."
    assert error_text(DatabaseNotOpen()) == "Es ist keine Bibliothek geöffnet."
    assert error_text(LibraryBusy("Die Bibliothek wird gerade geschrieben.")) == "Die Bibliothek wird gerade geschrieben."
    assert error_text(SpreadsheetError("  Leer.  ")) == "Leer."  # trimmed
    # anything else is an internal error: class name for the bug report
    assert error_text(KeyError("pins")) == "Interner Fehler (KeyError): 'pins'"
    assert error_text(TypeError("unsupported operand")) == "Interner Fehler (TypeError): unsupported operand"
    assert error_text(AttributeError("x")) == "Interner Fehler (AttributeError): x"
    # without a message
    assert error_text(ValueError()) == "Interner Fehler (ValueError)"
    assert error_text(RuntimeError("   ")) == "Interner Fehler (RuntimeError)"
    assert error_text(ZeroDivisionError()) == "Interner Fehler (ZeroDivisionError)"


def test_job_dataclass_defaults() -> None:
    job = Job(id="abc", kind="x", title="Test")
    snap = job.snapshot(brief=True)
    assert snap["result"] is None and snap["message"] == "" and snap["cancel_reason"] is None
