"""Library guard in the API: every job that writes registry rows or library files holds the library it was
started for (partforge.jobs.library_hold); opening, creating or closing a library cancels these jobs and waits for
them (HTTP 409 with a German message after the timeout); neither a job nor a direct write ever writes into
another library. Plus the test-suite guard of conftest.py (no background writer job unless ``library_job``)."""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from test_writer_samples import resistor_symbol

from partforge.altium import editing, housestyle, libimport, sync
from partforge.api import routes_libraries, routes_series, routes_system
from partforge.api.routes_system import WorkspaceCreateIn, WorkspaceOpenIn
from partforge.datasheet import proposal
from partforge.db import backup, parts, registry
from partforge.db.models import SymbolRecord
from partforge.domain import series
from partforge.importers import spreadsheet
from partforge.jobs import (
    CANCEL_LIBRARY_SWITCH,
    LIBRARY_JOB_KINDS,
    JobContext,
    JobManager,
    jobs,
    library_guard,
)
from partforge.workspace import Workspace, current_or_none, same_folder

SERIES_BODY = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "values": ["10k"]}
IMPORT_CSV = "Teilenummer;Widerstand\r\nR-GUARD;10k\r\n"
IMPORT_MAPPING = [{"index": 0, "column": "Part Number"}, {"index": 1, "column": "Resistance"}]


def wait_for(condition: Callable[[], bool], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Bedingung nicht erreicht")


def wait_job(job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    job = jobs.get(job_id)
    assert job is not None
    wait_for(lambda: job.status in ("done", "failed", "cancelled"), timeout)
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


def forbidden(*_args: Any, **_kwargs: Any) -> Any:
    pytest.fail("darf nicht laufen – die Bibliothek ist nicht mehr geöffnet")


class Gate:
    """Stand-in for the work of a job: "writes a library file" until released, then notices a cancel."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, ctx: JobContext | None) -> dict[str, Any]:
        self.entered.set()
        assert self.release.wait(30), "Gate nicht freigegeben"
        if ctx is not None:
            ctx.check_cancelled()
        return {"ok": True}


@pytest.fixture
def gate() -> Iterator[Gate]:
    g = Gate()
    try:
        yield g
    finally:
        g.release.set()  # never leave a job thread hanging
        for job in jobs.list():
            if job.kind in LIBRARY_JOB_KINDS and job.status in ("queued", "running"):
                wait_for(lambda job=job: job.status not in ("queued", "running"), 30)


# --------------------------------------------------------------------------- how each job is started (as the API does)

Starter = Callable[[TestClient, pytest.MonkeyPatch, Gate, Workspace], str]


def start_sync(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: gate.run(ctx))
    return str(client.post("/api/libraries/sync").json()["job"]["id"])


def start_scan(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    monkeypatch.setattr(sync, "scan_workspace", lambda ctx=None, **_kw: gate.run(ctx))
    return str(client.post("/api/libraries/scan", json={"register_unknown": True}).json()["job"]["id"])


def start_layers(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    monkeypatch.setattr(sync, "apply_layer_stack", lambda ctx=None: gate.run(ctx))
    return str(client.post("/api/libraries/layer-stack/apply").json()["job"]["id"])


def _editor_save(monkeypatch: pytest.MonkeyPatch, ensure: Callable[..., Any]) -> None:
    monkeypatch.setattr(sync, "validate_spec", lambda spec: [])
    monkeypatch.setattr(sync, "foreign_conflict", lambda spec, **_kw: None)
    monkeypatch.setattr(sync, "ensure_symbols", ensure)


def start_save(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    _editor_save(monkeypatch, lambda specs, *, ctx=None, **_kw: gate.run(ctx))
    spec = resistor_symbol("PF_GUARD")
    response = client.put(f"/api/libraries/symbols/{quote(spec.name)}",
                          json={"spec": spec.model_dump(mode="json"), "background": True})
    return str(response.json()["job"]["id"])


def start_delete(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    registry.upsert_symbol(SymbolRecord(name="PF_GUARD_DEL", library="Symbols\\PF_Guard.SchLib", status="ok"))
    monkeypatch.setattr(sync, "delete_symbols", lambda names, *, force=False, ctx=None, **_kw: gate.run(ctx))
    response = client.delete("/api/libraries/symbols/PF_GUARD_DEL", params={"background": "true"})
    return str(response.json()["job"]["id"])


def start_series(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    monkeypatch.setattr(series, "commit", lambda ctx, request, mode="skip", author=None, *, library=None: gate.run(ctx))
    return str(client.post("/api/series/commit", json=SERIES_BODY).json()["job"]["id"])


def start_datasheet_commit(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    """As POST /datasheets/{id}/commit submits it (the hold is part of ``commit_proposal`` itself)."""
    monkeypatch.setattr(proposal, "_commit", lambda ctx, datasheet_id, choices, *, ws, author: gate.run(ctx))
    return jobs.submit("datasheet-commit", "Bauteil anlegen", proposal.commit_proposal, "0123456789abcdef", None,
                       ws=ws).id


def start_libraries(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    monkeypatch.setattr(routes_system, "_writer_problem", lambda _ws: None)
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: gate.run(ctx))
    return routes_system.start_library_sync(ws).id


def start_import(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    """As POST /import/run starts it: the parts are written while the library is held."""
    monkeypatch.setattr(parts, "upsert_parts", lambda table, rows, *, ctx=None, **_kw: gate.run(ctx))
    token = spreadsheet.store_upload(IMPORT_CSV.encode(), "guard.csv")
    body = {"token": token, "table": "Resistors", "mapping": IMPORT_MAPPING, "allow_incomplete": True}
    return str(client.post("/api/import/run", json=body).json()["job"]["id"])


def start_library_import(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    """As POST /library-import/run starts it (for a scan that exists)."""
    scan = libimport.ImportScan(id="guardscan0001", source=r"C:\Quelle", name="Quelle", created="2026-10-09T12:00:00")
    monkeypatch.setattr(libimport, "get_scan", lambda scan_id: scan)
    monkeypatch.setattr(libimport, "run_import", lambda options, *, ctx=None: gate.run(ctx))
    return str(client.post("/api/library-import/run", json={"scan_id": scan.id}).json()["job"]["id"])


def start_conform(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    """As POST /housestyle/apply starts it (Stapelbearbeitung)."""
    monkeypatch.setattr(housestyle, "apply", lambda selection, rules, *, ctx=None: gate.run(ctx))
    return str(client.post("/api/housestyle/apply", json={}).json()["job"]["id"])


def _fake_altium(client: TestClient) -> None:
    from test_refresh_support import FakeBridge

    from partforge.api import routes_altium

    client.app.dependency_overrides[routes_altium.get_bridge] = lambda: FakeBridge()  # type: ignore[attr-defined]


def start_altium_edit(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    """As POST /altium/edit starts it: the baseline of the library file is the step in progress."""
    from types import SimpleNamespace

    from partforge.api import routes_altium_edit

    _fake_altium(client)
    path = ws.root / "Footprints" / "PF_GUARD.PcbLib"
    monkeypatch.setattr(editing, "_editable", lambda _ws, kind, name: (SimpleNamespace(name=name), path))
    monkeypatch.setattr(routes_altium_edit, "get_writer", lambda **_kw: object())
    monkeypatch.setattr(sync, "get_writer", lambda **_kw: object())
    monkeypatch.setattr(editing, "_reader", lambda _writer: object())
    monkeypatch.setattr(editing, "capture_baseline", lambda _writer, _path: (gate.run(None), editing.FileBaseline())[1])
    return str(client.post("/api/altium/edit", json={"kind": "footprint", "name": "PF_GUARD"}).json()["job"]["id"])


def start_altium_take_over(client: TestClient, monkeypatch: pytest.MonkeyPatch, gate: Gate, ws: Workspace) -> str:
    """As POST /altium/edit/sessions/{id}/check (and the watcher) starts it."""
    from partforge.api import routes_altium_edit

    service = editing.AltiumEditService(altium_running=None)
    service.load(ws)
    session = editing.EditSession(id="guard", kind="footprint", library=r"Footprints\PF_GUARD.PcbLib",
                                  targets=["PF_GUARD"], started="2026-10-10T12:00:00",
                                  last_activity="2026-10-10T12:00:00", baseline=editing.FileBaseline())
    service._sessions[session.id] = session
    client.app.dependency_overrides[routes_altium_edit.get_edit_service] = lambda: service  # type: ignore[attr-defined]
    monkeypatch.setattr(editing, "_take_over", lambda s, _service, _id, **_kw: gate.run(s.ctx))
    return str(client.post("/api/altium/edit/sessions/guard/check").json()["job"]["id"])


STARTERS: dict[str, Starter] = {
    "libraries.sync": start_sync,
    "libraries.scan": start_scan,
    "libraries.layers": start_layers,
    "libraries.save": start_save,
    "libraries.delete": start_delete,
    "series": start_series,
    "datasheet-commit": start_datasheet_commit,
    "libraries": start_libraries,
    "import": start_import,
    "libraries.import": start_library_import,
    "libraries.conform": start_conform,
    "altium.edit": start_altium_edit,
    "libraries.altium-edit": start_altium_take_over,
}


def test_every_library_job_kind_is_covered() -> None:
    assert set(STARTERS) == LIBRARY_JOB_KINDS


@pytest.mark.parametrize(
    "kind",
    [pytest.param(k, marks=pytest.mark.library_job) if k == "libraries" else k for k in STARTERS],
)
def test_switch_cancels_every_library_job_and_waits_for_it(kind: str, client: TestClient, workspace: Workspace,
                                                           monkeypatch: pytest.MonkeyPatch, gate: Gate) -> None:
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    job_id = STARTERS[kind](client, monkeypatch, gate, workspace)
    assert gate.entered.wait(30), "der Job hat nicht begonnen"
    job = jobs.get(job_id)
    assert job is not None and job.kind == kind
    assert any(holder is job and same_folder(root, workspace.root) for holder, root in library_guard.holders())
    closer, closed = in_thread(routes_system.close_workspace)
    wait_for(lambda: job.cancel_requested)
    assert job.cancel_reason == CANCEL_LIBRARY_SWITCH
    time.sleep(0.1)
    assert closer.is_alive() and current_or_none() is workspace  # waits: the library is still open
    gate.release.set()  # the step in progress ends in the old library ...
    closer.join(30)
    assert closed == {"result": {"ok": True}} and current_or_none() is None
    snap = wait_job(job_id)
    assert snap["status"] == "cancelled", snap
    warnings = [entry["text"] for entry in snap["log"] if entry["level"] == "warn"]
    assert len(warnings) == 1 and "gewechselt" in warnings[0], warnings  # ... and says why it stopped
    assert not any(entry["level"] == "error" for entry in snap["log"])


# --------------------------------------------------------------------------- never into another library


def _job_body(kind: str, ws: Workspace) -> Callable[[JobContext], Any]:
    root = ws.root
    if kind == "libraries.sync":
        return routes_libraries._held(root, lambda ctx: sync.sync_pending(ctx))
    if kind == "series":
        request = series.SeriesRequest.model_validate(SERIES_BODY)
        return lambda ctx: routes_series.commit_job(ctx, request, "skip", library=root)
    if kind == "datasheet-commit":
        return lambda ctx: proposal.commit_proposal(ctx, "0123456789abcdef", None, ws=ws)
    if kind == "import":
        token = spreadsheet.store_upload(IMPORT_CSV.encode(), "guard.csv")
        options = spreadsheet.ImportOptions(token=token, table="Resistors", mapping=IMPORT_MAPPING,  # type: ignore[arg-type]
                                            allow_incomplete=True)
        return lambda ctx: spreadsheet.run_import(ctx, options, library=root)
    return lambda ctx: routes_system._write_libraries(ctx, root)


@pytest.mark.parametrize("kind", ["libraries.sync", "series", "datasheet-commit", "libraries", "import"])
def test_job_started_for_one_library_never_writes_into_the_next(kind: str, workspace: Workspace, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a job queued for library A that started after B was opened wrote into B."""
    for name in ("sync_pending", "scan_workspace", "ensure_symbols", "ensure_footprints"):
        monkeypatch.setattr(sync, name, forbidden)
    monkeypatch.setattr(routes_system, "_writer_problem", lambda _ws: None)
    monkeypatch.setattr(series, "commit", forbidden)
    monkeypatch.setattr(proposal, "_commit", forbidden)
    monkeypatch.setattr(parts, "upsert_parts", forbidden)
    monkeypatch.setattr(backup, "auto_backup", forbidden)
    body = _job_body(kind, workspace)  # submitted while A is open ...
    routes_system.create_workspace(WorkspaceCreateIn(path=str(tmp_path / "B"), name="B", with_examples=False))
    assert current_or_none().root == (tmp_path / "B").resolve()  # type: ignore[union-attr]
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync(kind, "Test", body)  # ... and runs once B is open
    finally:
        manager.shutdown()
    if kind == "libraries":  # "Bibliotheken schreiben" ends done/skipped – the entries stay pending in A
        assert job.status == "done" and job.result["skipped"] is True
        assert "nicht mehr geöffnet" in job.result["reason"]
    else:
        assert job.status == "cancelled", job.error
    assert [entry["level"] for entry in job.log] == ["warn"] and "nicht mehr geöffnet" in job.log[0]["text"]
    counts = registry.counts()
    assert counts["symbols"]["total"] == 0 and counts["footprints"]["total"] == 0
    assert parts.stats()["total_parts"] == 0


# --------------------------------------------------------------------------- 409 and direct writes


def test_switch_answers_409_while_a_job_does_not_stop(client: TestClient, workspace: Workspace, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch, gate: Gate) -> None:
    monkeypatch.setattr(routes_system, "LIBRARY_JOB_STOP_TIMEOUT_S", 0.2)
    job_id = start_series(client, monkeypatch, gate, workspace)
    assert gate.entered.wait(30)
    refused = client.post("/api/workspace/close")
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert "gerade geschrieben" in detail and "Job „Serie " in detail and "erneut versuchen" in detail, detail
    created = client.post("/api/workspace/create", json={"path": str(tmp_path / "B"), "with_examples": False})
    assert created.status_code == 409 and not (tmp_path / "B").exists()  # nothing created
    assert client.get("/api/workspace").json()["root"] == str(workspace.root)
    gate.release.set()
    assert wait_job(job_id)["status"] == "cancelled"  # the cancel request of the refused switch still applies
    assert client.post("/api/workspace/close").status_code == 200


def test_switch_waits_for_a_direct_save(client: TestClient, workspace: Workspace,
                                        monkeypatch: pytest.MonkeyPatch, gate: Gate) -> None:
    def ensure_symbols(specs: list[Any], *, ctx: JobContext | None = None, **_kw: Any) -> list[SymbolRecord]:
        gate.run(ctx)
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF_Guard.SchLib", spec=s,
                                                     status="ok") for s in specs])

    _editor_save(monkeypatch, ensure_symbols)
    spec = resistor_symbol("PF_DIRECT")
    saver, saved = in_thread(lambda: client.put(f"/api/libraries/symbols/{spec.name}",
                                                json={"spec": spec.model_dump(mode="json"), "background": False}))
    assert gate.entered.wait(30)
    assert [job for job, _root in library_guard.holders()] == [None]  # a direct write, no job
    closer, closed = in_thread(routes_system.close_workspace)
    time.sleep(0.2)
    assert closer.is_alive() and current_or_none() is workspace  # waits, cancels nothing
    gate.release.set()
    saver.join(30)
    closer.join(30)
    assert saved["result"].status_code == 200, saved
    assert saved["result"].json()["record"]["name"] == "PF_DIRECT"
    assert closed == {"result": {"ok": True}}
    routes_system.open_workspace(WorkspaceOpenIn(path=str(workspace.root)))
    assert registry.get_symbol("PF_DIRECT") is not None  # written into the library it was saved in


def test_direct_save_that_finds_another_library_answers_409(client: TestClient, workspace: Workspace,
                                                             tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = tmp_path / "B"

    def validate(spec: Any) -> list[str]:  # the user opens library B while the save is checked
        routes_system.create_workspace(WorkspaceCreateIn(path=str(other), name="B", with_examples=False))
        return []

    _editor_save(monkeypatch, forbidden)
    monkeypatch.setattr(sync, "validate_spec", validate)
    spec = resistor_symbol("PF_LATE")
    response = client.put(f"/api/libraries/symbols/{spec.name}",
                          json={"spec": spec.model_dump(mode="json"), "background": False})
    assert response.status_code == 409 and "nicht mehr geöffnet" in response.json()["detail"]
    assert current_or_none().root == other.resolve()  # type: ignore[union-attr]
    assert registry.counts()["symbols"]["total"] == 0


# --------------------------------------------------------------------------- conftest: no background writer job


def test_creating_a_library_in_tests_starts_no_writer_job(bare_client: TestClient, tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "sync_pending", forbidden)
    info = bare_client.post("/api/workspace/create", json={"path": str(tmp_path / "Lib"), "with_examples": True})
    assert info.status_code == 200, info.text
    try:
        job = info.json()["job"]
        assert job["kind"] == routes_system.LIBRARY_SYNC_JOB_KIND and job["status"] == "done"
        assert job["result"]["skipped"] is True and "library_job" in job["result"]["reason"]
        stats = bare_client.get("/api/stats").json()
        assert stats["symbols"]["by_status"]["pending"] == info.json()["examples"]["symbols"]
    finally:
        assert bare_client.post("/api/workspace/close").status_code == 200


@pytest.mark.library_job
def test_marked_tests_start_the_real_writer_job(bare_client: TestClient, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Path] = []

    def fake_sync(ctx: JobContext | None = None) -> dict[str, Any]:
        ws = current_or_none()
        assert ws is not None and isinstance(ctx, JobContext)
        seen.append(ws.root)
        return {"written": 1}

    monkeypatch.setattr(routes_system, "_writer_problem", lambda _ws: None)
    monkeypatch.setattr(sync, "sync_pending", fake_sync)
    info = bare_client.post("/api/workspace/create", json={"path": str(tmp_path / "Lib"), "with_examples": True})
    assert info.status_code == 200, info.text
    try:
        snap = wait_job(info.json()["job"]["id"])
        assert snap["status"] == "done" and snap["result"] == {"written": 1}
        assert seen == [(tmp_path / "Lib").resolve()]
    finally:
        assert bare_client.post("/api/workspace/close").status_code == 200
