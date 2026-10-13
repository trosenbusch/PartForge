"""Import and export jobs and the library guard (ARCHITEKTUR §8.4).

The spreadsheet import writes parts: it holds the library it was started for (job kind ``import`` in
``LIBRARY_JOB_KINDS``) – a library switch cancels it and waits; the parts are written in one transaction, so a
cancelled import imported nothing, in neither library. The export only reads and holds nothing: a switch does
not wait for it, and it ends ``cancelled`` without writing a file. Plus the German job texts and final messages.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.api import routes_parts, routes_system
from partforge.api.routes_system import WorkspaceCreateIn, WorkspaceOpenIn
from partforge.db import categories, parts
from partforge.importers import spreadsheet as ss
from partforge.importers.spreadsheet import ImportOptions, MappingItem
from partforge.jobs import CANCELLED_BY_SWITCH_MESSAGE, JobCancelled, JobManager, jobs, library_guard
from partforge.workspace import Workspace, current_or_none, same_folder

HEADER = "Teilenummer;Hersteller;MPN;Widerstand;Toleranz;Leistung;Symbol;Footprint;Beschreibung\r\n"


def line(pn: str, value: str) -> str:
    return f"{pn};YAGEO;{pn};{value};1%;0,1W;RES;RESC1608X55N;Widerstand {pn}\r\n"


def wait_for(condition: Callable[[], bool], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Bedingung nicht erreicht")


def wait_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    assert job is not None
    wait_for(lambda: job.status in ("done", "failed", "cancelled"), 30)
    return job.snapshot()


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, outcome


def upload(client: TestClient, text: str) -> dict[str, Any]:
    r = client.post("/api/import/preview", files={"file": ("liste.csv", text.encode("cp1252"), "text/csv")},
                    data={"table": "Resistors"})
    assert r.status_code == 200, r.text
    return r.json()


def start_import(client: TestClient, prev: dict[str, Any], **options: Any) -> str:
    r = client.post("/api/import/run", json={"token": prev["token"], "table": "Resistors", "mapping": prev["mapping"],
                                             **options})
    assert r.status_code == 200, r.text
    return str(r.json()["job"]["id"])


def in_job_thread() -> bool:
    return threading.current_thread().name.startswith("partforge-job")


class InsertGate:
    """Stops the import job right before it inserts its parts – inside the write transaction."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        original = parts._chunks

        def gated(items: Any, *args: Any, **kwargs: Any) -> Iterator[Any]:
            if items and isinstance(items[0], dict) and in_job_thread():  # the rows to insert, not keys
                self.entered.set()
                assert self.release.wait(30), "Gate nicht freigegeben"
            yield from original(items, *args, **kwargs)

        monkeypatch.setattr(parts, "_chunks", gated)


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> Iterator[InsertGate]:
    g = InsertGate(monkeypatch)
    try:
        yield g
    finally:
        g.release.set()  # never leave a job thread hanging


# --------------------------------------------------------------------------- import


def test_import_holds_its_library_and_a_switch_rolls_it_back(client: TestClient, workspace: Workspace,
                                                              gate: InsertGate) -> None:
    job_id = start_import(client, upload(client, HEADER + line("R-A", "1k") + line("R-B", "2k")))
    assert gate.entered.wait(30), "der Import hat nicht zu schreiben begonnen"
    job = jobs.get(job_id)
    assert job is not None and job.kind == "import"
    assert any(holder is job and same_folder(root, workspace.root) for holder, root in library_guard.holders())
    closer, closed = in_thread(routes_system.close_workspace)
    wait_for(lambda: job.cancel_requested)
    time.sleep(0.1)
    assert closer.is_alive() and current_or_none() is workspace  # the switch waits for the import
    gate.release.set()
    closer.join(30)
    assert closed == {"result": {"ok": True}}
    snap = wait_job(job_id)
    assert snap["status"] == "cancelled" and snap["cancel_reason"] == "library_switch" and snap["error"] is None
    assert snap["message"] == CANCELLED_BY_SWITCH_MESSAGE
    assert [e["text"] for e in snap["log"] if e["level"] == "warn"] == [
        "Die Bibliothek wird geschlossen oder gewechselt – Import abgebrochen, es wurde nichts übernommen."]
    routes_system.open_workspace(WorkspaceOpenIn(path=str(workspace.root)))
    assert parts.stats()["total_parts"] == 0  # rolled back: nothing imported into the old library either


def test_cancelled_import_imports_nothing(client: TestClient, workspace: Workspace, gate: InsertGate) -> None:
    job_id = start_import(client, upload(client, HEADER + line("R-A", "1k")))
    assert gate.entered.wait(30)
    assert client.post(f"/api/jobs/{job_id}/cancel").json() == {"cancelled": True}
    gate.release.set()
    snap = wait_job(job_id)
    assert snap["status"] == "cancelled" and snap["cancel_reason"] is None and snap["message"] == "Abgebrochen"
    assert [e["text"] for e in snap["log"] if e["level"] == "warn"] == ["Import abgebrochen – es wurde nichts übernommen."]
    assert parts.stats()["total_parts"] == 0


def test_import_job_texts_are_german(client: TestClient, workspace: Workspace) -> None:
    label = categories.get_category("Resistors").label
    snap = wait_job(start_import(client, upload(client, HEADER + line("R-A", "1k") + line("R-B", "2k")), mode="update"))
    texts = [e["text"] for e in snap["log"]]
    assert texts[0] == f"2 Zeilen aus „liste.csv“ → {label} (Modus: vorhandene aktualisieren)", texts
    assert texts[1].startswith("Sicherung angelegt: PartForge_")
    assert texts[-1] == snap["message"] == snap["result"]["message"] == "Import fertig: 2 neu"
    assert snap["log"][-1]["level"] == "success"
    again = wait_job(start_import(client, upload(client, HEADER + line("R-A", "1k") + line("R-C", "3k"))))
    texts = [e["text"] for e in again["log"]]
    assert texts[0] == f"2 Zeilen aus „liste.csv“ → {label} (Modus: vorhandene überspringen)"
    assert again["message"] == "Import fertig: 1 neu, 1 übersprungen"
    one = wait_job(start_import(client, upload(client, HEADER + line("R-D", "4k7")), mode="error"))
    assert [e["text"] for e in one["log"]][0] == f"1 Zeile aus „liste.csv“ → {label} (Modus: vorhandene ablehnen)"
    for snapshot in (snap, again, one):
        assert not any(word in e["text"] for e in snapshot["log"] for word in ("(skip)", "(update)", "(error)"))


def test_import_summary_and_message() -> None:
    assert ss.import_summary(created=120, updated=4, rejected=2) == "120 neu, 4 aktualisiert, 2 abgelehnt"
    assert ss.import_summary(created=1250, updated=0, unchanged=3, skipped=1) == "1.250 neu, 3 unverändert, 1 übersprungen"
    assert ss.import_summary(created=0, updated=0) == "keine Zeile"
    assert ss.import_message("ok", "3 neu") == "Import fertig: 3 neu"
    assert ss.import_message("partial", "120 neu, 2 abgelehnt") == "Import fertig: 120 neu, 2 abgelehnt"
    assert ss.import_message("failed", "2 abgelehnt") == "Import fehlgeschlagen – nichts übernommen: 2 abgelehnt"
    assert ss.MODE_LABELS == {"skip": "vorhandene überspringen", "update": "vorhandene aktualisieren",
                              "error": "vorhandene ablehnen"}


def test_many_rejected_rows_are_summed_up_in_the_log(workspace: Workspace) -> None:
    token = ss.store_upload(("Teilenummer\r\n" + "".join(f"R-{i:03d}\r\n" for i in range(60))).encode(), "nr.csv")
    options = ImportOptions(token=token, table="Resistors", mapping=[MappingItem(index=0, column="Part Number")])
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("import", "Import", ss.run_import, options)
    finally:
        manager.shutdown()
    assert job.status == "done" and job.result["outcome"] == "failed" and job.result["error_count"] == 60
    assert job.message == job.result["message"] == "Import fehlgeschlagen – nichts übernommen: 60 abgelehnt"
    warnings = [e["text"] for e in job.log if e["level"] == "warn"]
    assert len(warnings) == 52 and warnings[50] == "… und 10 weitere abgelehnte Zeilen" and warnings[51] == job.message


def test_reading_a_big_file_checks_for_cancellation(workspace: Workspace) -> None:
    """The import job can be stopped while it reads a big file (a library switch does not wait for the whole read)."""
    import io

    import openpyxl

    calls: list[int] = []
    token = ss.store_upload(("Teilenummer;Widerstand\r\n" + "".join(f"R-{i};1k\r\n" for i in range(4500))).encode(),
                            "gross.csv")
    data = ss.read_table_file(ss.upload_path(token)[0], check=lambda: calls.append(1))
    assert len(data.rows) == 4500 and len(calls) == 3  # file rows 0, 2000 and 4000
    book = openpyxl.Workbook()
    sheet = book.active
    for i in range(2500):
        sheet.append([f"R-{i}", "1k"])
    buffer = io.BytesIO()
    book.save(buffer)
    token = ss.store_upload(buffer.getvalue(), "gross.xlsx")
    calls.clear()
    assert len(ss.read_table_file(ss.upload_path(token)[0], check=lambda: calls.append(1)).rows) == 2500
    assert len(calls) == 2

    def stop() -> None:
        raise JobCancelled()

    with pytest.raises(JobCancelled):
        ss.read_table_file(ss.upload_path(token)[0], check=stop)


def test_import_cancelled_before_it_holds_the_library(workspace: Workspace) -> None:
    token = ss.store_upload((HEADER + line("R-A", "1k")).encode("cp1252"), "liste.csv")
    options = ImportOptions(token=token, table="Resistors", mapping=[MappingItem(index=0, column="Part Number")])

    def body(ctx: Any) -> Any:
        ctx.cancel()  # e.g. cancelled by the user while it was queued
        return ss.run_import(ctx, options, library=workspace.root)

    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("import", "Import", body)
    finally:
        manager.shutdown()
    assert job.status == "cancelled" and job.cancel_reason is None and job.message == "Abgebrochen"
    assert [e["text"] for e in job.log] == ["Import abgebrochen – es wurde nichts übernommen."]
    assert parts.stats()["total_parts"] == 0


def test_import_without_library_runs_in_the_open_one(workspace: Workspace) -> None:
    """Direct calls (no ``library``): no hold, the open library."""
    token = ss.store_upload((HEADER + line("R-X", "1k")).encode("cp1252"), "direkt.csv")
    prev = ss.preview(ss.upload_path(token)[0], table="Resistors")
    result = ss.run_import(None, ImportOptions(token=token, table="Resistors", mapping=prev["mapping"]))
    assert result["created"] == 1 and result["message"] == "Import fertig: 1 neu"
    assert library_guard.holders() == []


# --------------------------------------------------------------------------- export


def create_resistors(client: TestClient, *pns: str) -> None:
    for pn in pns:
        values = {"Part Number": pn, "Manufacturer": "YAGEO", "Manufacturer Part Number": pn, "Resistance": "1k",
                  "Tolerance": "1", "Power": "0.1", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}
        assert client.post("/api/parts/Resistors", json={"values": values}).status_code == 201


@pytest.mark.windows
def test_export_job_ends_with_its_outcome(client: TestClient, workspace: Workspace) -> None:
    create_resistors(client, "R-A", "R-B")
    snap = wait_job(client.post("/api/export/Resistors/job", json={"format": "csv"}).json()["job"]["id"])
    result = snap["result"]
    assert snap["status"] == "done" and result["rows"] == 2 and result["rel_path"].startswith("Exports\\")
    assert snap["message"] == f"Export fertig: 2 Bauteile in {result['rel_path']}"
    assert snap["log"][-1] == {**snap["log"][-1], "level": "success", "text": snap["message"]}
    assert Path(result["path"]).is_file() and Path(result["path"]).parent == workspace.exports_dir
    one = wait_job(client.post("/api/export/Resistors/job", json={"part_numbers": ["R-A"]}).json()["job"]["id"])
    assert one["message"] == f"Export fertig: 1 Bauteil in {one['result']['rel_path']}"
    assert one["result"]["file_name"].endswith(".xlsx")


@pytest.mark.parametrize("switch", ["close", "open_other"])
def test_switch_ends_a_running_export_cleanly(switch: str, client: TestClient, workspace: Workspace, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    create_resistors(client, "R-A")
    entered, release = threading.Event(), threading.Event()
    original = ss._export_rows

    def gated(*args: Any, **kwargs: Any) -> Any:
        if in_job_thread():
            entered.set()
            assert release.wait(30), "Gate nicht freigegeben"
        return original(*args, **kwargs)

    monkeypatch.setattr(ss, "_export_rows", gated)
    job_id = client.post("/api/export/Resistors/job", json={"format": "xlsx"}).json()["job"]["id"]
    try:
        assert entered.wait(30), "der Export hat nicht zu lesen begonnen"
        if switch == "close":
            switcher, outcome = in_thread(routes_system.close_workspace)
        else:
            switcher, outcome = in_thread(lambda: routes_system.create_workspace(
                WorkspaceCreateIn(path=str(tmp_path / "B"), name="B", with_examples=False)))
        switcher.join(15)
        assert not switcher.is_alive() and "error" not in outcome, outcome  # no hold: the switch does not wait
        job = jobs.get(job_id)
        assert job is not None and job.status == "running" and not job.cancel_requested
    finally:
        release.set()
    snap = wait_job(job_id)
    assert snap["status"] == "cancelled" and snap["cancel_reason"] == "library_switch" and snap["error"] is None
    assert snap["message"] == CANCELLED_BY_SWITCH_MESSAGE
    assert [e["text"] for e in snap["log"] if e["level"] == "warn"] == [routes_parts.EXPORT_CANCELLED_NOTE]
    assert not any(e["level"] == "error" for e in snap["log"])
    assert list(workspace.exports_dir.iterdir()) == []  # no file, neither in the old library ...
    if switch == "open_other":
        assert list((tmp_path / "B" / "Exports").iterdir()) == []  # ... nor in the new one


def test_export_job_of_a_library_that_is_gone(workspace: Workspace, tmp_path: Path) -> None:
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("export", "Export", routes_parts._export_job, "Resistors", routes_parts.PartExportIn(),
                               tmp_path / "andere Bibliothek")
    finally:
        manager.shutdown()
    assert job.status == "cancelled" and job.cancel_reason == "library_switch"
    assert [e["text"] for e in job.log] == [routes_parts.EXPORT_CANCELLED_NOTE]
