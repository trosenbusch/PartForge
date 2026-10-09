"""Integration: creating a library through the API seeds the examples and starts the job
"Bibliotheken schreiben" (api.routes_system -> db.examples -> altium.sync).

The race tests use a writer that blocks inside its first library write, so that opening,
creating or closing a library happens while the job writes – the job must stop before the
database is swapped and never write registry rows into another library.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from partforge.altium import libwriter, sync
from partforge.altium.libwriter import WriterUnavailable
from partforge.altium.models import ComponentInfo, WriteResult
from partforge.api import routes_system
from partforge.api.routes_system import WorkspaceCreateIn, WorkspaceOpenIn
from partforge.db import registry
from partforge.geometry.model import FootprintSpec, SymbolSpec
from partforge.jobs import JobContext, JobManager, jobs
from partforge.workspace import Workspace, WorkspaceSettings, current_or_none

Spec = SymbolSpec | FootprintSpec


def _wait(job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        assert job is not None
        if job.status in ("done", "failed", "cancelled"):
            return job.snapshot()
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} wurde nicht fertig")


def _wait_for(condition: Callable[[], bool], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("Bedingung nicht erreicht")


def _create(client: TestClient, path: Path, **body: Any) -> dict[str, Any]:
    response = client.post("/api/workspace/create", json={"path": str(path), "name": "Demo", **body})
    assert response.status_code == 200, response.text
    return response.json()


def _nonzero(by_status: dict[str, int]) -> dict[str, int]:
    return {status: count for status, count in by_status.items() if count}


class TestWriter:
    """In-memory :class:`~partforge.altium.libwriter.LibraryWriter`; with ``block`` its first
    library write waits for :attr:`release` (signals :attr:`entered`)."""

    __test__ = False  # not a test class
    name = "rust"

    def __init__(self, *, block: bool = False, ready: tuple[bool, str] = (True, "Test-Writer bereit.")) -> None:
        self.block = block
        self.ready = ready
        self.entered = threading.Event()
        self.release = threading.Event()
        self.files: dict[str, dict[str, Spec]] = {}

    @staticmethod
    def _key(library: Path) -> str:
        return os.path.normcase(os.path.abspath(library))

    def _store(self, library: Path, specs: Sequence[Spec], *, replace: bool) -> WriteResult:
        if self.block and not self.entered.is_set():
            self.entered.set()
            if not self.release.wait(30):
                raise RuntimeError("Test-Writer wurde nicht freigegeben")
        components = {} if replace else dict(self.files.get(self._key(library), {}))
        components.update({spec.name: spec for spec in specs})
        self.files[self._key(library)] = components
        Path(library).parent.mkdir(parents=True, exist_ok=True)
        Path(library).write_bytes(f"PartForge-Test {len(components)}".encode())
        return WriteResult(library=str(library), backend="rust", written=[s.name for s in specs])

    def available(self) -> tuple[bool, str]:
        return self.ready

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        return self._store(library, symbols, replace=False)

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        return self._store(library, footprints, replace=False)

    def write_library_full(self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]) -> WriteResult:
        return self._store(library, list(specs), replace=True)

    def delete_components(self, library: Path, names: list[str]) -> WriteResult:
        return WriteResult(library=str(library), backend="rust")

    def list_components(self, library: Path) -> list[str]:
        return list(self.files.get(self._key(library), {}))

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None:
        return None

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None:
        return None

    def scan_library(self, library: Path) -> list[ComponentInfo]:
        return []


def _use_writer(monkeypatch: pytest.MonkeyPatch, writer: Any) -> None:
    monkeypatch.setattr(libwriter, "get_writer", lambda *args, **kwargs: writer)
    monkeypatch.setattr(sync, "get_writer", lambda *args, **kwargs: writer)
    libwriter.forget_component_names()


@pytest.fixture
def close_after(bare_client: TestClient) -> Iterator[TestClient]:
    yield bare_client
    if current_or_none() is not None:
        bare_client.post("/api/workspace/close")


@pytest.fixture
def ready_writer(monkeypatch: pytest.MonkeyPatch) -> TestWriter:
    writer = TestWriter()
    _use_writer(monkeypatch, writer)
    return writer


@pytest.fixture
def blocking_writer(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestWriter]:
    writer = TestWriter(block=True)
    _use_writer(monkeypatch, writer)
    try:
        yield writer
    finally:
        writer.release.set()  # never leave a job thread hanging
        for job in jobs.list(routes_system.LIBRARY_SYNC_JOB_KIND):
            if job.status in ("queued", "running"):
                _wait(job.id)
        if current_or_none() is not None:
            routes_system.close_workspace()
        libwriter.forget_component_names()


# --------------------------------------------------------------------------- creation + job


def test_create_with_examples_starts_library_job(close_after: TestClient, tmp_path: Path, ready_writer: TestWriter,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_sync(ctx: JobContext | None = None) -> dict[str, Any]:
        ws = current_or_none()
        pending = registry.list_symbols(status="pending") + registry.list_footprints(status="pending")
        calls.append({"ctx": ctx, "root": ws.root if ws else None, "pending": len(pending)})
        if ctx is not None:
            ctx.progress(1.0, "fertig")
        return {"written": len(pending), "errors": {}}

    monkeypatch.setattr(sync, "sync_pending", fake_sync)
    info = _create(close_after, tmp_path / "Lib", with_examples=True)
    assert info["name"] == "Demo" and info["root"] == str((tmp_path / "Lib").resolve())  # existing fields kept
    assert info["examples"] == {"parts": 19, "symbols": 15, "footprints": 13} and info["examples_error"] is None
    job = info["job"]
    assert job["kind"] == routes_system.LIBRARY_SYNC_JOB_KIND and job["title"] == "Bibliotheken schreiben"
    done = _wait(job["id"])
    assert done["status"] == "done" and done["result"] == {"written": 28, "errors": {}}
    assert len(calls) == 1 and isinstance(calls[0]["ctx"], JobContext)
    assert calls[0]["root"] == Path(info["root"]) and calls[0]["pending"] == 28
    stats = close_after.get("/api/stats").json()
    assert stats["total_parts"] == 19


def test_create_without_examples_starts_no_job(close_after: TestClient, tmp_path: Path) -> None:
    info = _create(close_after, tmp_path / "Leer", with_examples=False)
    assert info["job"] is None and info["examples"] is None
    assert close_after.get("/api/stats").json()["total_parts"] == 0


def test_examples_can_stay_pending(close_after: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: pytest.fail("darf nicht laufen"))
    info = _create(close_after, tmp_path / "Ausstehend", with_examples=True, write_libraries=False)
    assert info["job"] is None and info["examples"] == {"parts": 19, "symbols": 15, "footprints": 13}
    stats = close_after.get("/api/stats").json()
    assert stats["symbols"]["by_status"]["pending"] == 15 and stats["footprints"]["by_status"]["pending"] == 13


@pytest.mark.parametrize("cause", ["no_writer", "not_ready"])
def test_without_writer_the_examples_stay_pending(cause: str, close_after: TestClient, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Real ``sync_pending`` path: no usable writer ends with a warning, nothing is marked ``error``."""
    if cause == "no_writer":
        def unavailable(*args: Any, **kwargs: Any) -> Any:
            raise WriterUnavailable("Kein Bibliotheks-Writer verfügbar (Test).")

        monkeypatch.setattr(libwriter, "get_writer", unavailable)
        monkeypatch.setattr(sync, "get_writer", unavailable)
        expected = "Kein Bibliotheks-Writer verfügbar (Test)."
    else:
        _use_writer(monkeypatch, TestWriter(ready=(False, "Der Rust-Writer wurde nicht gefunden (Test).")))
        expected = "Der Rust-Writer wurde nicht gefunden (Test)."
    info = _create(close_after, tmp_path / "OhneWriter", with_examples=True)
    done = _wait(info["job"]["id"])
    assert done["status"] == "done" and done["result"]["skipped"] is True, done
    assert done["result"]["reason"].startswith(expected) and "ausstehend" in done["result"]["reason"]
    assert [entry["level"] for entry in done["log"]] == ["warn"]
    stats = close_after.get("/api/stats").json()
    assert _nonzero(stats["symbols"]["by_status"]) == {"pending": 15}
    assert _nonzero(stats["footprints"]["by_status"]) == {"pending": 13}


def test_job_skips_a_library_that_was_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workspace: Workspace) -> None:
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: pytest.fail("darf nicht laufen"))
    job = JobManager(max_workers=1).run_sync("libraries", "Bibliotheken schreiben", routes_system._write_libraries,
                                             tmp_path / "andere Bibliothek")
    assert job.status == "done" and job.result["skipped"] is True and "nicht mehr geöffnet" in job.result["reason"]


def test_job_cancelled_before_it_starts_writes_nothing(workspace: Workspace, ready_writer: TestWriter,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: pytest.fail("darf nicht laufen"))
    manager = JobManager(max_workers=1)
    with routes_system._library_jobs_lock:  # the job waits for the library ...
        job = manager.submit("libraries", "Bibliotheken schreiben", routes_system._write_libraries, workspace.root)
        _wait_for(lambda: job.status == "running")
        assert manager.cancel(job.id)  # ... and is cancelled meanwhile (e.g. by the user)
    _wait_for(lambda: job.status not in ("queued", "running"))
    assert job.status == "cancelled"
    assert [entry["text"] for entry in job.log] == [f"Schreiben abgebrochen. {routes_system._PENDING_HINT}"]
    manager.shutdown()


def test_other_sync_errors_fail_the_job(monkeypatch: pytest.MonkeyPatch, workspace: Workspace,
                                        ready_writer: TestWriter) -> None:
    def broken(ctx: JobContext | None = None) -> dict[str, Any]:
        raise RuntimeError("Schreibfehler")

    monkeypatch.setattr(sync, "sync_pending", broken)
    job = JobManager(max_workers=1).run_sync("libraries", "Bibliotheken schreiben", routes_system._write_libraries,
                                             workspace.root)
    assert job.status == "failed" and "Schreibfehler" in (job.error or "")


def test_seeding_errors_keep_the_new_library_open(close_after: TestClient, tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import partforge.db as db_package

    def broken_seed(ws: Workspace) -> dict[str, int]:
        raise RuntimeError("Testfehler")

    monkeypatch.setattr(db_package, "seed_examples", broken_seed)
    info = _create(close_after, tmp_path / "Fehler", with_examples=True)
    assert info["job"] is None and info["examples"] is None
    assert "Beispielinhalte" in info["examples_error"] and "Testfehler" in info["examples_error"]
    assert close_after.get("/api/workspace").json()["root"] == info["root"]


# --------------------------------------------------------------------------- switching while writing


def _start_library_a(tmp_path: Path, writer: TestWriter) -> str:
    info = routes_system.create_workspace(WorkspaceCreateIn(path=str(tmp_path / "A"), name="A", with_examples=True))
    assert info["job"] is not None
    assert writer.entered.wait(20), "der Job hat nicht zu schreiben begonnen"
    return str(info["job"]["id"])


def _in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - reported to the test
            outcome["error"] = exc

    thread = threading.Thread(target=run, name="library-switch", daemon=True)
    thread.start()
    return thread, outcome


def _registry_totals() -> tuple[int, int]:
    counts = registry.counts()
    return counts["symbols"]["total"], counts["footprints"]["total"]


def test_switching_library_while_writing_never_writes_into_the_new_one(tmp_path: Path,
                                                                        blocking_writer: TestWriter) -> None:
    job_id = _start_library_a(tmp_path, blocking_writer)
    thread, outcome = _in_thread(lambda: routes_system.create_workspace(
        WorkspaceCreateIn(path=str(tmp_path / "B"), name="B", with_examples=False)))
    _wait_for(lambda: jobs.get(job_id).cancel_requested)  # type: ignore[union-attr]
    time.sleep(0.1)
    assert thread.is_alive() and current_or_none().root == (tmp_path / "A").resolve()  # type: ignore[union-attr]
    blocking_writer.release.set()  # the write in progress finishes (in library A) ...
    thread.join(30)
    assert not thread.is_alive() and "error" not in outcome, outcome
    done = _wait(job_id)
    assert done["status"] == "cancelled", done
    assert any("geschlossen oder gewechselt" in entry["text"] for entry in done["log"])
    assert not any(entry["level"] == "error" for entry in done["log"])
    # ... B is untouched
    assert current_or_none().root == (tmp_path / "B").resolve()  # type: ignore[union-attr]
    assert _registry_totals() == (0, 0)
    assert not (tmp_path / "B" / "Symbols" / "PF_Analog.SchLib").exists()
    # A kept everything: the written library is "ok", the rest stays pending
    routes_system.open_workspace(WorkspaceOpenIn(path=str(tmp_path / "A")))
    counts = registry.counts()
    assert counts["symbols"]["total"] == 15 and counts["footprints"]["total"] == 13
    assert _nonzero(counts["symbols"]["by_status"]) == {"ok": 2, "pending": 13}, counts
    assert {r.name for r in registry.list_symbols(status="ok")} == {"Op-Amp", "Op-Amp Dual"}
    assert (tmp_path / "A" / "Symbols" / "PF_Analog.SchLib").is_file()


def test_closing_library_while_writing_cancels_the_job(tmp_path: Path, blocking_writer: TestWriter) -> None:
    job_id = _start_library_a(tmp_path, blocking_writer)
    thread, outcome = _in_thread(routes_system.close_workspace)
    _wait_for(lambda: jobs.get(job_id).cancel_requested)  # type: ignore[union-attr]
    blocking_writer.release.set()
    thread.join(30)
    assert outcome == {"result": {"ok": True}}
    done = _wait(job_id)
    assert done["status"] == "cancelled" and done["error"] is None, done
    assert current_or_none() is None


def test_switch_answers_409_while_a_library_file_is_written(tmp_path: Path, blocking_writer: TestWriter,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes_system, "LIBRARY_JOB_STOP_TIMEOUT_S", 0.2)
    job_id = _start_library_a(tmp_path, blocking_writer)
    with pytest.raises(HTTPException) as busy:
        routes_system.create_workspace(WorkspaceCreateIn(path=str(tmp_path / "B"), with_examples=False))
    assert busy.value.status_code == 409 and "gerade geschrieben" in str(busy.value.detail)
    assert not (tmp_path / "B").exists()  # nothing created
    with pytest.raises(HTTPException) as busy_close:
        routes_system.close_workspace()
    assert busy_close.value.status_code == 409
    assert current_or_none().root == (tmp_path / "A").resolve()  # type: ignore[union-attr]
    blocking_writer.release.set()
    assert _wait(job_id)["status"] == "cancelled"  # the cancel requested by the switch still applies
    routes_system.create_workspace(WorkspaceCreateIn(path=str(tmp_path / "B"), with_examples=False))
    assert current_or_none().root == (tmp_path / "B").resolve()  # type: ignore[union-attr]
    assert _registry_totals() == (0, 0)


# --------------------------------------------------------------------------- refused / rolled back


def test_invalid_folder_gives_german_400(close_after: TestClient, tmp_path: Path) -> None:
    blocker = tmp_path / "Datei.txt"
    blocker.write_text("kein Ordner", encoding="utf-8")
    response = close_after.post("/api/workspace/create", json={"path": str(blocker / "Lib")})
    assert response.status_code == 400 and "kann nicht angelegt werden" in response.json()["detail"]
    for relative in ("", "   ", "Lib", r"..\Lib"):
        response = close_after.post("/api/workspace/create", json={"path": relative})
        assert response.status_code == 400 and "vollständigen Pfad" in response.json()["detail"], relative
    existing = tmp_path / "Doppelt"
    _create(close_after, existing, with_examples=False)
    again = close_after.post("/api/workspace/create", json={"path": str(existing)})
    assert again.status_code == 409 and "bereits eine PartForge-Bibliothek" in again.json()["detail"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda s: setattr(s.folders, "symbols", r"..\außerhalb"), "innerhalb des Bibliotheksordners"),
        (lambda s: setattr(s.folders, "backups", r"C:\Sicherungen"), "relativ zum Bibliotheksordner"),
        (lambda s: setattr(s.folders, "exports", r"\Exporte"), "relativ zum Bibliotheksordner"),
        (lambda s: setattr(s.folders, "datasheets", "Daten|blätter"), "unzulässige Zeichen"),
        (lambda s: setattr(s.folders, "models", "."), "kein gültiger Name"),
        (lambda s: setattr(s.folders, "footprints", "NUL"), "reservierten Namen"),
        (lambda s: setattr(s.db, "sqlite_file", r"..\PartForge.sqlite"), "Datenbankdatei"),
        (lambda s: setattr(s, "dblib_file", r"Unterordner\PartForge.DbLib"), "reiner Dateiname"),
        (lambda s: setattr(s, "dblib_file", "PartForge.txt"), "auf „.DbLib“ enden"),
    ],
)
def test_settings_outside_the_library_are_refused(change: Callable[[WorkspaceSettings], None], message: str,
                                                  close_after: TestClient, tmp_path: Path) -> None:
    settings = WorkspaceSettings()
    change(settings)
    target = tmp_path / "Neu" / "Lib"
    response = close_after.post("/api/workspace/create",
                                json={"path": str(target), "settings": settings.model_dump(mode="json")})
    assert response.status_code == 400 and message in response.json()["detail"], response.text
    assert not (tmp_path / "Neu").exists() and current_or_none() is None


def test_workspace_settings_update_is_validated(close_after: TestClient, tmp_path: Path) -> None:
    info = _create(close_after, tmp_path / "Lib", with_examples=False)
    settings = WorkspaceSettings.model_validate(info["settings"])
    settings.folders.symbols = r"..\außerhalb"
    response = close_after.put("/api/workspace/settings", json=settings.model_dump(mode="json"))
    assert response.status_code == 400 and "innerhalb des Bibliotheksordners" in response.json()["detail"]
    settings.folders.symbols = r"Symbole\Eigene"
    response = close_after.put("/api/workspace/settings", json=settings.model_dump(mode="json"))
    assert response.status_code == 200 and response.json()["settings"]["folders"]["symbols"] == r"Symbole\Eigene"
    assert routes_system.settings_path_problems(WorkspaceSettings()) == []


def test_network_drive_is_refused_before_anything_is_created(close_after: TestClient, tmp_path: Path,
                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    from partforge.db import core

    monkeypatch.setattr(core, "is_network_path", lambda path: True)
    target = tmp_path / "Netz" / "Lib"
    response = close_after.post("/api/workspace/create", json={"path": str(target)})
    assert response.status_code == 400 and "Netzlaufwerk" in response.json()["detail"]
    assert not (tmp_path / "Netz").exists()
    settings = WorkspaceSettings()
    settings.db.kind = "postgres"  # PostgreSQL does not care where the folder lies (it fails later: no URL)
    response = close_after.post("/api/workspace/create",
                                json={"path": str(target), "settings": settings.model_dump(mode="json")})
    assert response.status_code == 409 and "PostgreSQL" in response.json()["detail"]
    assert not (tmp_path / "Netz").exists()  # rolled back


def test_failed_open_removes_only_what_the_creation_added(close_after: TestClient, tmp_path: Path,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    import partforge.db as db_package
    from partforge.db.errors import DbError

    before = _create(close_after, tmp_path / "Vorher", with_examples=False)

    def failing_open(ws: Workspace) -> None:
        ws.sqlite_path.write_bytes(b"halb angelegt")  # what a failed open may leave behind
        raise DbError("Testfehler beim Öffnen")

    monkeypatch.setattr(db_package, "open_database", failing_open)
    fresh = tmp_path / "Neu" / "Tief" / "Lib"
    response = close_after.post("/api/workspace/create", json={"path": str(fresh)})
    assert response.status_code == 409 and "Testfehler beim Öffnen" in response.json()["detail"]
    assert not (tmp_path / "Neu").exists()
    # a folder that existed before keeps its own content
    own = tmp_path / "Eigener Ordner"
    (own / "Symbols").mkdir(parents=True)
    (own / "notiz.txt").write_text("bleibt", encoding="utf-8")
    response = close_after.post("/api/workspace/create", json={"path": str(own)})
    assert response.status_code == 409
    assert sorted(p.name for p in own.iterdir()) == ["Symbols", "notiz.txt"]
    # the previously open library stays open and the folder can be used again later
    assert close_after.get("/api/workspace").json()["root"] == before["root"]
    monkeypatch.undo()
    assert _create(close_after, own, with_examples=False)["root"] == str(own.resolve())


# --------------------------------------------------------------------------- real writer


@pytest.mark.rustwriter
def test_new_library_is_written_by_the_rust_writer(close_after: TestClient, tmp_path: Path) -> None:
    """End to end: API -> examples -> job -> real sync_pending -> altium-designer-mcp.exe (no Altium)."""
    info = _create(close_after, tmp_path / "Echt", with_examples=True)
    done = _wait(info["job"]["id"], timeout=180)
    assert done["status"] == "done", done
    result = done["result"]
    assert result["errors"] == [] and result["missing"] == [], result
    assert result["symbols"]["ok"] == 15 and result["footprints"]["ok"] == 13, result
    stats = close_after.get("/api/stats").json()
    assert _nonzero(stats["symbols"]["by_status"]) == {"ok": 15}
    assert _nonzero(stats["footprints"]["by_status"]) == {"ok": 13}
    root = Path(info["root"])
    assert (root / "Symbols" / "PF_Passives.SchLib").is_file() and (root / "Footprints" / "PF_CHIP.PcbLib").is_file()
