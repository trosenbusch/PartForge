"""Shared library guard (partforge.jobs): library_hold / library_switch semantics, without the API.

Holds are shared (jobs and direct writes hold the library they were started for at the same
time), a switch is exclusive: it cancels the running job holders, waits for every holder and
raises LibraryBusy after its timeout. A job never continues into a library opened after it
started.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from partforge.db import close_database, open_database
from partforge.jobs import (
    CANCEL_LIBRARY_SWITCH,
    LIBRARY_SWITCH_MESSAGE,
    Job,
    JobCancelled,
    JobContext,
    JobManager,
    LibraryBusy,
    LibraryChanged,
    cancelled_by_switch,
    library_guard,
    library_hold,
    library_switch,
    open_library,
)
from partforge.workspace import Workspace, current_for, same_folder, set_current


def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("Bedingung nicht erreicht")


def finished(job: Job) -> Job:
    wait_for(lambda: job.status in ("done", "failed", "cancelled"))
    return job


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


def hold_root(ctx: JobContext, root: Path) -> str:
    with library_hold(ctx, root) as ws:
        return str(ws.root)


def switch_to(ws: Workspace | None) -> None:
    """What a library switch does to the database (bypasses the guard, like a test or a restore)."""
    close_database()
    if ws is not None:
        open_database(ws)
    set_current(ws)


@pytest.fixture
def manager() -> Iterator[JobManager]:
    mgr = JobManager(max_workers=3)
    try:
        yield mgr
    finally:
        mgr.shutdown()


class Gate:
    """Job body that holds the library and "writes a library file" until released."""

    def __init__(self, root: Path, *, announce: bool = True) -> None:
        self.root = root
        self.announce = announce
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, ctx: JobContext) -> str:
        with library_hold(ctx, self.root, announce=self.announce) as ws:
            self.entered.set()
            assert self.release.wait(10), "Gate nicht freigegeben"
            ctx.check_cancelled()  # the next step notices a cancel request
            return str(ws.root)


# --------------------------------------------------------------------------- helpers


def test_same_folder_and_current_for(workspace: Workspace, tmp_path: Path) -> None:
    root = workspace.root
    assert same_folder(root, str(root).upper() + "\\") and same_folder(root, str(root).replace("\\", "/"))
    assert not same_folder(root, tmp_path / "Andere")
    assert current_for(str(root).lower()) is workspace and current_for(tmp_path / "Andere") is None
    assert open_library(root) is workspace


def test_open_library_needs_workspace_and_database(workspace: Workspace, tmp_path: Path) -> None:
    other = Workspace.create(tmp_path / "B", name="B")
    close_database()
    open_database(other)  # database of B, workspace still A (half-way through a switch)
    try:
        assert open_library(workspace.root) is None and open_library(other.root) is None
        with pytest.raises(LibraryChanged), library_hold(None, workspace.root):
            pytest.fail("darf nicht laufen")
    finally:
        switch_to(workspace)


# --------------------------------------------------------------------------- holds


def test_hold_yields_the_open_workspace(workspace: Workspace) -> None:
    assert not library_guard.holding()
    with library_hold(None, workspace.root) as ws:
        assert ws is workspace and library_guard.holding()
        assert library_guard.holders() == [(None, workspace.root)]
        with library_hold(None, workspace.root) as inner:  # nested holds of a thread are free
            assert inner is workspace
        assert library_guard.holding()
    assert not library_guard.holding() and library_guard.holders() == []


def test_hold_of_another_library_raises_library_changed(workspace: Workspace, tmp_path: Path) -> None:
    with pytest.raises(LibraryChanged) as changed, library_hold(None, tmp_path / "Gar nicht offen"):
        pytest.fail("darf nicht laufen")
    assert isinstance(changed.value, JobCancelled)
    assert "nicht mehr geöffnet" in str(changed.value) and changed.value.root == tmp_path / "Gar nicht offen"
    assert library_guard.holders() == []
    switch_to(None)
    try:
        with pytest.raises(LibraryChanged), library_hold(None, workspace.root):
            pytest.fail("darf nicht laufen")
    finally:
        switch_to(workspace)


def test_job_whose_library_is_gone_is_cancelled_with_a_german_warning(workspace: Workspace, tmp_path: Path,
                                                                      manager: JobManager) -> None:
    written: list[str] = []

    def body(ctx: JobContext) -> None:
        with library_hold(ctx, tmp_path / "A"):
            written.append("A")

    job = manager.run_sync("series", "Serie", body)
    assert job.status == "cancelled" and written == []
    assert [(e["level"], "nicht mehr geöffnet" in e["text"]) for e in job.log] == [("warn", True)]

    def quiet_body(ctx: JobContext) -> None:
        with library_hold(ctx, tmp_path / "A", announce=False):
            written.append("A")

    quiet = manager.run_sync("libraries", "Bibliotheken schreiben", quiet_body)
    assert quiet.status == "cancelled" and quiet.log == [] and written == []  # the job reports it itself


# --------------------------------------------------------------------------- switches


def test_switch_cancels_running_jobs_and_waits_for_them(workspace: Workspace, manager: JobManager) -> None:
    gate = Gate(workspace.root)
    job = manager.submit("libraries.sync", "Bibliotheken synchronisieren", gate)
    assert gate.entered.wait(10)
    order: list[str] = []

    def switch() -> None:
        with library_switch(timeout=10):
            order.append("switch")

    thread, outcome = in_thread(switch)
    wait_for(lambda: job.cancel_requested)
    assert job.cancel_reason == CANCEL_LIBRARY_SWITCH and library_guard.switch_pending
    time.sleep(0.1)
    assert thread.is_alive() and order == []  # waits until the job released the library
    gate.release.set()
    thread.join(10)
    assert order == ["switch"] and "error" not in outcome
    assert finished(job).status == "cancelled"
    assert [(e["level"], e["text"]) for e in job.log] == [("warn", LIBRARY_SWITCH_MESSAGE)]
    assert not library_guard.switch_pending


def test_switch_times_out_with_a_german_busy_message(workspace: Workspace, manager: JobManager) -> None:
    gate = Gate(workspace.root)
    job = manager.submit("series", "Serie CRCW", gate)
    assert gate.entered.wait(10)
    with pytest.raises(LibraryBusy) as busy, library_switch(timeout=0.2):
        pytest.fail("darf nicht laufen")
    message = str(busy.value)
    assert "gerade geschrieben" in message and "Job „Serie CRCW“" in message and "erneut versuchen" in message
    assert busy.value.titles == ["Serie CRCW"]
    assert job.cancel_requested and job.cancel_reason == CANCEL_LIBRARY_SWITCH  # the request stays in force
    gate.release.set()
    assert finished(job).status == "cancelled"
    with library_switch(timeout=1):  # free again
        pass


def test_direct_writes_are_waited_for_and_never_cancelled(workspace: Workspace) -> None:
    entered, release = threading.Event(), threading.Event()

    def write() -> str:
        with library_hold(None, workspace.root):
            entered.set()
            assert release.wait(10)
            return "gespeichert"

    writer, written = in_thread(write)
    assert entered.wait(10)
    with pytest.raises(LibraryBusy, match="ein laufender Speichervorgang"), library_switch(timeout=0.1):
        pytest.fail("darf nicht laufen")
    switched: list[str] = []

    def switch() -> None:
        with library_switch(timeout=10):
            switched.append("switch")

    thread, outcome = in_thread(switch)
    time.sleep(0.1)
    assert thread.is_alive() and switched == []
    release.set()
    writer.join(10)
    thread.join(10)
    assert written == {"result": "gespeichert"} and switched == ["switch"] and "error" not in outcome


def test_new_holds_wait_for_a_switch_and_then_find_their_library_gone(workspace: Workspace, tmp_path: Path,
                                                                     manager: JobManager) -> None:
    """Regression: a job started for library A must never write into library B opened meanwhile."""
    other = Workspace.create(tmp_path / "B", name="B")
    written: list[Path] = []

    def body(ctx: JobContext) -> None:
        with library_hold(ctx, workspace.root) as ws:
            written.append(ws.root)

    try:
        with library_switch(timeout=1):
            job = manager.submit("libraries.save", "Symbol speichern", body)
            wait_for(lambda: "Bibliothekswechsel" in job.message)  # waits instead of writing
            assert library_guard.holders() == []
            switch_to(other)
        assert finished(job).status == "cancelled" and written == []
        assert any("nicht mehr geöffnet" in e["text"] for e in job.log)
    finally:
        switch_to(workspace)


def test_failed_switch_lets_waiting_jobs_run_in_their_library(workspace: Workspace, manager: JobManager) -> None:
    """Queued/waiting jobs are not cancelled by a switch: if their library stays open they run."""
    with pytest.raises(RuntimeError, match="Öffnen fehlgeschlagen"), library_switch(timeout=1):
        job = manager.submit("libraries.scan", "Bibliotheken prüfen", lambda ctx: hold_root(ctx, workspace.root))
        wait_for(lambda: "Bibliothekswechsel" in job.message)
        raise RuntimeError("Öffnen fehlgeschlagen")
    assert finished(job).status == "done" and job.result == str(workspace.root)
    assert not job.cancel_requested


def test_waiting_job_cancelled_by_the_user_stops_at_once(workspace: Workspace, manager: JobManager) -> None:
    with library_guard.exclusive:
        job = manager.submit("libraries.sync", "Bibliotheken synchronisieren",
                             lambda ctx: hold_root(ctx, workspace.root))
        wait_for(lambda: "Bibliothekswechsel" in job.message)
        assert manager.cancel(job.id)
        assert finished(job).status == "cancelled"  # while the library is still held exclusively
    assert job.log == [] and not cancelled_by_switch(JobContext(manager, job))


def test_exclusive_lock_makes_jobs_wait_without_cancelling_them(workspace: Workspace, manager: JobManager) -> None:
    lock = library_guard.exclusive
    assert lock.acquire(timeout=1)
    try:
        job = manager.submit("series", "Serie", lambda ctx: hold_root(ctx, workspace.root))
        wait_for(lambda: "Bibliothekswechsel" in job.message)
        assert not lock.acquire(blocking=False)  # exclusive: a second switch has to wait
        assert job.status == "running" and not job.cancel_requested
    finally:
        lock.release()
    assert finished(job).status == "done" and job.result == str(workspace.root)


def test_switch_waiting_for_a_holder_blocks_new_holds(workspace: Workspace) -> None:
    """No starvation: while a switch waits, a new hold does not start (it would keep the switch out)."""
    first_in, first_out = threading.Event(), threading.Event()
    events: list[str] = []

    def first() -> None:
        with library_hold(None, workspace.root):
            first_in.set()
            assert first_out.wait(10)
            with library_hold(None, workspace.root):  # nested: never blocked by the waiting switch
                events.append("verschachtelt")
            events.append("erster fertig")

    def switch() -> None:
        with library_switch(timeout=10):
            events.append("wechsel")
            time.sleep(0.05)

    def second() -> None:
        with library_hold(None, workspace.root):
            events.append("zweiter")

    t1, _ = in_thread(first)
    assert first_in.wait(10)
    t2, switched = in_thread(switch)
    wait_for(lambda: library_guard.switch_pending)
    t3, _ = in_thread(second)
    time.sleep(0.1)
    assert events == [] and [job for job, _root in library_guard.holders()] == [None]  # only the first
    first_out.set()
    for thread in (t1, t2, t3):
        thread.join(10)
    assert events == ["verschachtelt", "erster fertig", "wechsel", "zweiter"] and "error" not in switched


def test_switch_inside_a_hold_is_refused(workspace: Workspace) -> None:
    with (
        library_hold(None, workspace.root),
        pytest.raises(RuntimeError, match="auf sich selbst warten"),
        library_switch(timeout=0.1),
    ):
        pytest.fail("darf nicht laufen")
    with library_switch(timeout=0.1):  # nothing left behind
        assert not library_guard.holding()


# --------------------------------------------------------------------------- cancel reasons


def test_cancel_reason_first_request_wins(manager: JobManager) -> None:
    release = threading.Event()
    job = manager.submit("x", "Test", lambda ctx: release.wait(10))
    wait_for(lambda: job.status == "running")
    ctx = JobContext(manager, job)
    assert ctx.cancel(CANCEL_LIBRARY_SWITCH) and manager.cancel(job.id, reason="benutzer")
    assert job.cancel_reason == CANCEL_LIBRARY_SWITCH and ctx.cancel_reason == CANCEL_LIBRARY_SWITCH
    assert cancelled_by_switch(ctx) and not cancelled_by_switch(None)
    release.set()
    assert finished(job).status == "done"  # the body never checked
    assert not manager.cancel(job.id)  # inactive jobs cannot be cancelled
