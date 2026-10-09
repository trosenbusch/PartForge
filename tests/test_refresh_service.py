"""AltiumRefreshService with a fake bridge: debounce, rebuild flag, gates (setting, Altium
not running, install state per Altium session, wedge), schema-change classification,
manual trigger and follow-ups, failures and the PARTS_CHANGED events emitted by
:mod:`partforge.db.parts`."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from test_refresh_support import FakeBridge, wait_for, wait_job

from partforge import events
from partforge.altium import dblib, refresh
from partforge.altium.bridge.core import (
    AltiumNotRunning,
    BridgeBusyError,
    BridgeCommandError,
    BridgeError,
    DbLibInstallState,
    DbLibRefreshResult,
)
from partforge.altium.dblib import (
    DbLibAutoWriter,
    cached_install_state,
    ensure_dblib,
    forget_install_state,
    remember_install_state,
)
from partforge.altium.refresh import (
    AltiumRefreshService,
    describe_refresh,
    note_refresh_result,
)
from partforge.config import AppSettings
from partforge.db import categories, parts
from partforge.db.errors import PartValidationError
from partforge.db.models import FieldDef
from partforge.jobs import JobManager
from partforge.workspace import Workspace, WorkspaceNotOpen


class Harness:
    """Service with a fake bridge; ``installed`` is the cached install state
    (True/False/None = never checked), ``checked`` when it was checked, ``session`` the
    start time of the running Altium (None = unknown)."""

    def __init__(self, ws: Workspace | None, *, installed: bool | None = True, auto: bool = True,
                 session: float | None = None, **kw):
        self.ws = ws
        self.bridge = FakeBridge(installed=[str(ws.dblib_path)] if ws is not None and installed else [])
        self.bridge.hidden_open.update(self.bridge.installed)
        self.settings = AppSettings()
        self.settings.altium.auto_refresh = auto
        self.installed = installed
        self.checked = time.time()
        self.session = session if session is not None else self.checked - 60.0
        self.manager = JobManager(max_workers=2)
        self.service = AltiumRefreshService(
            debounce_s=kw.pop("debounce_s", 0.05),
            max_wait_s=kw.pop("max_wait_s", 5.0),
            busy_retry_s=kw.pop("busy_retry_s", 0.05),
            bridge_factory=lambda: self.bridge,
            settings_provider=lambda: self.settings,
            workspace_provider=lambda: self.ws,
            install_state_provider=self.install_state,
            session_provider=lambda: self.session,
            probe_install_state=kw.pop("probe", True),  # fake bridge: probing is safe here
            job_manager=self.manager,
        )

    def install_state(self, path: Path) -> DbLibInstallState | None:
        if self.installed is None:
            return None
        return DbLibInstallState(path=str(path), file_name=Path(path).name, installed=self.installed,
                                 checked=self.checked)

    def refreshes(self) -> list[tuple]:
        return [args for name, args in self.bridge.calls if name == "refresh_dblib"]

    def idle(self) -> None:
        assert self.service.wait_idle(10.0)

    def close(self) -> None:
        self.service.stop()
        self.manager.shutdown()


@pytest.fixture
def harness(tmp_path: Path):
    made: list[Harness] = []

    def make(ws: Workspace | None = None, **kw) -> Harness:
        h = Harness(ws if ws is not None else Workspace.create(tmp_path / f"Bib{len(made)}"), **kw)
        made.append(h)
        return h

    yield make
    for h in made:
        h.close()


def wait_job_in(h: Harness, job) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        current = h.manager.get(job.id)
        if current is not None and current.status in ("done", "failed", "cancelled"):
            h.idle()
            return current.snapshot()
        time.sleep(0.01)
    raise AssertionError("Job nicht fertig")


# --------------------------------------------------------------------------- debounce / flags


def test_debounce_merges_a_burst_into_one_refresh(harness):
    h = harness()
    for _ in range(10):
        assert h.service.request(table="Resistors")
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", False)]
    status = h.service.status()
    assert status.refresh_count == 1 and not status.pending and status.last_refresh and status.last_error is None
    assert status.last_result["closed"] == [str(h.ws.dblib_path)]
    assert "neu ein" in status.last_message


def test_burst_creates_no_thread_per_request(harness):
    h = harness(debounce_s=0.3)
    before = threading.active_count()
    for _ in range(200):
        h.service.request()
    assert threading.active_count() - before <= 2
    h.idle()
    assert len(h.refreshes()) == 1


def test_rebuild_flag_follows_inserts(harness):
    h = harness()
    h.service.request(rebuild=False)
    h.service.request(rebuild=True, table="Capacitors")
    h.service.request(rebuild=False)
    h.idle()
    h.service.request(rebuild=False)
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", True), ("PartForge.DbLib", False)]


def test_max_wait_under_continuous_writes(harness):
    h = harness(debounce_s=0.2, max_wait_s=0.3)
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        h.service.request()
        time.sleep(0.04)
    assert len(h.refreshes()) >= 1  # refreshed although the writes never paused for 0.2 s
    h.idle()


# --------------------------------------------------------------------------- gates


def test_disabled_setting_keeps_changes_for_manual_refresh(harness):
    h = harness(auto=False)
    h.service.request(rebuild=True, table="Resistors")
    h.idle()
    assert h.refreshes() == []
    status = h.service.status()
    assert status.pending and status.pending_rebuild and status.pending_tables == ["Resistors"]
    assert "ausgeschaltet" in status.last_skip_reason and status.auto_refresh is False
    job = h.service.refresh_now()
    snap = wait_job_in(h, job)
    assert snap["status"] == "done" and snap["result"]["trigger"] == "manual" and snap["result"]["rebuild_index"]
    assert h.refreshes() == [("PartForge.DbLib", True)] and not h.service.status().pending


def test_altium_not_running_drops_the_request(harness):
    h = harness()
    h.bridge.running = False
    h.service.request(rebuild=True)
    h.idle()
    status = h.service.status()
    assert h.refreshes() == [] and not status.pending and not status.pending_rebuild
    assert "läuft nicht" in status.last_skip_reason
    with pytest.raises(AltiumNotRunning):
        h.service.refresh_now()


def test_known_not_installed_in_this_altium_session_is_skipped(harness):
    h = harness(installed=False)  # checked after the running Altium started
    h.service.request(rebuild=True)
    h.idle()
    status = h.service.status()
    assert h.refreshes() == [] and not status.pending
    assert "nicht installiert" in status.last_skip_reason and "Altium-Sitzung" in status.last_skip_reason


def test_not_installed_from_an_earlier_altium_session_is_checked_again(harness):
    h = harness(installed=False)
    h.session = h.checked + 5.0  # Altium was restarted after the check
    h.service.request(rebuild=True)
    h.idle()
    # F4: a read-only check first – the refresh (by file name!) never runs for a DbLib that is not installed
    assert h.bridge.names() == ["install_state"] and h.refreshes() == []
    job = h.manager.list(refresh.JOB_KIND)[0]
    assert job.result["installed"] is False and job.result["quiet"] is True  # F11: no message for the UI
    status = h.service.status()
    assert status.last_refresh is None and status.refresh_count == 0  # not counted as "aktualisiert"
    assert "nicht installiert" in (status.last_skip_reason or "")


def test_unknown_install_state_is_checked_by_the_refresh(harness):
    h = harness(installed=None)
    h.bridge.installed = [str(h.ws.dblib_path)]  # installed by hand in Altium, never checked by PartForge
    h.bridge.hidden_open.add(str(h.ws.dblib_path))
    h.service.request(rebuild=True)
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", True)]
    assert h.service.status().last_result["closed"] == [str(h.ws.dblib_path)]


def test_no_automatic_probe_inside_the_test_suite(harness):
    """Default (probe_install_state=None) under pytest: an unknown state is never probed –
    with PARTFORGE_TEST_ALTIUM=1 the probe would reach the user's own PartForge.DbLib."""
    h = harness(installed=None, probe=None)
    h.service.request(rebuild=True)
    h.idle()
    status = h.service.status()
    assert h.bridge.calls == [] and status.pending and status.pending_rebuild
    assert "Unbekannt" in status.last_skip_reason and "Installationsstatus prüfen" in status.last_skip_reason
    h.installed, h.checked = False, h.session - 1.0  # "not installed" from an earlier Altium session
    h.service.request()
    h.idle()
    assert h.bridge.calls == [] and "Unbekannt" in h.service.status().last_skip_reason
    h.installed, h.checked = True, time.time()  # known as installed (e.g. "Installationsstatus prüfen"): refreshed
    h.service.request()
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", True)]
    snap = wait_job_in(h, h.service.refresh_now())  # the manual action never needs a probe flag
    assert snap["status"] == "done"


def test_unknown_session_start_uses_the_age_of_the_check(harness):
    h = harness(installed=False)
    h.session = None  # process start time not readable
    h.service.request()
    h.idle()
    assert h.refreshes() == []
    h.checked = time.time() - refresh.STALE_INSTALL_STATE_S - 1
    h.service.request()
    h.idle()
    assert h.bridge.names() == ["install_state"] and h.refreshes() == []  # checked again (read-only)


def test_session_provider_failure_counts_as_unknown(harness):
    h = harness(installed=False)

    def broken() -> float:
        raise OSError("Prozessliste gesperrt")

    h.service._altium_started = broken  # noqa: SLF001 - simulate an unreadable process list
    h.service.request()
    h.idle()
    assert h.refreshes() == []  # recent check, unknown session: still trusted


def test_install_state_is_probed_once_per_altium_session(tmp_path: Path):
    """With the real install cache: the first change after an Altium start checks, the result
    is cached, the next changes in that session do not run Altium scripts for nothing."""
    ws = Workspace.create(tmp_path / "Probe")
    bridge = FakeBridge()  # DbLib not installed
    session = {"start": time.time() - 60.0}
    manager = JobManager(max_workers=2)
    svc = AltiumRefreshService(debounce_s=0.02, bridge_factory=lambda: bridge, settings_provider=AppSettings,
                               workspace_provider=lambda: ws, session_provider=lambda: session["start"],
                               probe_install_state=True, job_manager=manager)
    forget_install_state(ws.dblib_path)
    try:
        svc.request(rebuild=True)
        assert svc.wait_idle(5)
        assert bridge.names() == ["install_state"]  # read-only check, nothing touched
        state = cached_install_state(ws.dblib_path)
        assert state is not None and not state.installed
        svc.request()
        assert svc.wait_idle(5)
        assert bridge.names() == ["install_state"] and "nicht installiert" in svc.status().last_skip_reason
        session["start"] = state.checked + 0.001  # Altium restarted
        svc.request()
        assert svc.wait_idle(5)
        assert bridge.names() == ["install_state", "install_state"]
        bridge.install_library(ws.dblib_path)  # installed by hand in Altium during this session
        svc.request()
        assert svc.wait_idle(5)
        assert bridge.names().count("install_state") == 2  # still known as "not installed" …
        job = svc.refresh_now()  # … until the manual action looks again
        assert svc.wait_idle(5) and job.status == "done" and job.result["installed"] is True
        assert cached_install_state(ws.dblib_path).installed  # type: ignore[union-attr]
        assert bridge.names().count("refresh_dblib") == 1
        svc.request()
        assert svc.wait_idle(5)
        assert bridge.names().count("refresh_dblib") == 2 and bridge.names().count("install_state") == 3
    finally:
        svc.stop()
        manager.shutdown()
        forget_install_state(ws.dblib_path)


def test_wedged_bridge_pauses_automatic_refresh(harness):
    h = harness()
    h.bridge.last_wedge = {"kind": "did_not_finish"}
    h.service.request()
    h.idle()
    assert h.refreshes() == [] and h.service.status().pending
    assert "Strg+F3" in h.service.status().last_skip_reason
    wait_job_in(h, h.service.refresh_now())  # the manual action still tries
    assert len(h.refreshes()) == 1


def test_missing_x2_and_no_workspace(harness):
    h = harness()
    h.bridge.x2_path = None
    h.service.request()
    h.idle()
    assert h.refreshes() == [] and "X2.EXE" in h.service.status().last_skip_reason
    with pytest.raises(BridgeError, match=r"X2\.EXE"):
        h.service.refresh_now()
    h.ws = None
    assert h.service.request() is False
    with pytest.raises(WorkspaceNotOpen):
        h.service.refresh_now()


def test_failing_settings_keep_the_request(harness):
    h = harness()
    h.service._settings = lambda: (_ for _ in ()).throw(RuntimeError("kaputt"))  # noqa: SLF001
    h.service.request()
    h.idle()
    status = h.service.status()
    assert h.refreshes() == [] and status.pending and "kaputt" in status.last_skip_reason
    assert status.auto_refresh is False


# --------------------------------------------------------------------------- failures


def test_failed_refresh_is_not_retried_in_a_loop(harness):
    h = harness()
    h.bridge.fail["refresh_dblib"] = BridgeCommandError("refresh_dblib", "Skriptfehler")
    h.service.request(rebuild=True)
    h.idle()
    time.sleep(0.2)
    h.idle()
    assert len(h.refreshes()) == 1
    status = h.service.status()
    assert "Skriptfehler" in status.last_error and status.pending and status.pending_rebuild
    del h.bridge.fail["refresh_dblib"]
    h.service.request(rebuild=False)  # the next change tries again – still with the index rebuild
    h.idle()
    assert h.refreshes()[-1] == ("PartForge.DbLib", True) and h.service.status().last_error is None


def test_busy_bridge_is_retried(harness):
    h = harness()
    h.bridge.fail["refresh_dblib"] = BridgeBusyError("Die Altium-Brücke wird gerade verwendet.")
    h.service.request()
    assert wait_for(lambda: len(h.refreshes()) >= 2, 5)
    del h.bridge.fail["refresh_dblib"]
    assert wait_for(lambda: h.service.status().refresh_count == 1, 5)
    h.idle()
    count = len(h.refreshes())
    time.sleep(0.2)
    assert len(h.refreshes()) == count  # no further retries after success


def test_busy_retries_are_limited(harness):
    h = harness()
    h.bridge.fail["refresh_dblib"] = BridgeBusyError("belegt")
    h.service.request()
    assert wait_for(lambda: len(h.refreshes()) == 1 + refresh.MAX_BUSY_RETRIES, 5)
    time.sleep(0.3)
    h.idle()
    assert len(h.refreshes()) == 1 + refresh.MAX_BUSY_RETRIES


def test_busy_manual_refresh_is_retried_even_with_auto_off(harness):
    h = harness(auto=False)
    h.bridge.fail["refresh_dblib"] = BridgeBusyError("belegt")
    h.service.refresh_now(rebuild_index=True)
    assert wait_for(lambda: len(h.refreshes()) >= 2, 5)  # retried although auto_refresh is off
    del h.bridge.fail["refresh_dblib"]
    assert wait_for(lambda: h.service.status().refresh_count == 1, 5)
    h.idle()
    assert h.refreshes()[-1] == ("PartForge.DbLib", True) and not h.service.status().pending


def test_altium_closed_during_refresh(harness):
    h = harness()
    h.bridge.fail["refresh_dblib"] = AltiumNotRunning("Altium Designer wurde während des Vorgangs beendet.")
    h.service.request(rebuild=True)
    h.idle()
    status = h.service.status()
    assert "beendet" in status.last_error and not status.pending  # a fresh start reads the current state


# --------------------------------------------------------------------------- running jobs / manual


def test_changes_during_a_running_refresh_trigger_another_one(harness):
    h = harness(debounce_s=0.02)
    h.bridge.delay_s = 0.3
    h.service.request()
    assert wait_for(lambda: h.service.status().running, 2)
    h.service.request(rebuild=True)
    time.sleep(0.1)
    assert len(h.refreshes()) == 1
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", False), ("PartForge.DbLib", True)]


def test_manual_refresh_while_running_returns_the_running_job(harness):
    h = harness(debounce_s=0.02)
    h.bridge.delay_s = 0.3
    first = h.service.refresh_now(rebuild_index=False)
    second = h.service.refresh_now(rebuild_index=True)
    assert second.id == first.id
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", False), ("PartForge.DbLib", True)]


def test_manual_rebuild_while_running_follows_with_auto_off(harness):
    """Regression: the follow-up of a manual request went through the automatic gate and
    was dropped while auto_refresh was off."""
    h = harness(auto=False, debounce_s=0.02)
    h.bridge.delay_s = 0.3
    first = h.service.refresh_now(rebuild_index=False)
    second = h.service.refresh_now(rebuild_index=True)
    assert second.id == first.id and h.service.status().manual_pending
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", False), ("PartForge.DbLib", True)]
    triggers = [j.result["trigger"] for j in reversed(h.manager.list(refresh.JOB_KIND))]
    assert triggers == ["manual", "manual"]
    status = h.service.status()
    assert not status.pending and not status.manual_pending and status.last_skip_reason is None


def test_repeated_manual_click_without_changes_runs_once(harness):
    h = harness(debounce_s=0.02)
    h.bridge.delay_s = 0.2
    first = h.service.refresh_now()
    assert h.service.refresh_now().id == first.id and not h.service.status().manual_pending
    h.idle()
    assert len(h.refreshes()) == 1


def test_manual_follow_up_is_dropped_when_altium_closes(harness):
    h = harness(auto=False, debounce_s=0.02)
    h.bridge.delay_s = 0.2
    h.bridge.fail["refresh_dblib"] = AltiumNotRunning("Altium Designer wurde während des Vorgangs beendet.")
    h.service.refresh_now(rebuild_index=False)
    h.service.refresh_now(rebuild_index=True)
    h.idle()
    assert len(h.refreshes()) == 1 and not h.service.status().manual_pending


def test_stop_cancels_pending_timer(harness):
    h = harness(debounce_s=0.2)
    h.service.start()
    events.emit(events.PARTS_CHANGED, "Resistors", True)
    h.service.stop()
    time.sleep(0.35)
    assert h.refreshes() == [] and h.service.status().pending
    events.emit(events.PARTS_CHANGED, "Resistors", False)  # unsubscribed
    assert h.service.status().pending_tables == ["Resistors"]


def test_shut_down_job_manager_keeps_the_request(harness):
    h = harness()
    h.manager.shutdown()
    h.service.request(rebuild=True)
    h.idle()
    status = h.service.status()
    assert h.refreshes() == [] and status.pending and status.pending_rebuild  # nothing lost, nothing raised


# --------------------------------------------------------------------------- schema changes


def test_schema_changes_are_classified(workspace, harness):
    """Cosmetic metadata edits never run an Altium script; structure changes and a restored
    backup (new engine, rows may be new) rebuild the index – Altium caches the column list,
    the close alone does not show a new column (VERIFIED in Altium 26.10, altium-e2e.md)."""
    from partforge.db import backup

    h = harness(workspace)
    h.service.start()
    h.service.start()  # idempotent
    try:
        categories.update_category("Resistors", {"color": "#123456", "icon": "zap", "label": "Widerstände neu"})
        categories.update_field("Resistors", "Notes", {"label": "Notiz", "grid_width": 333, "help": "Hinweis"})
        columns = [f.column for f in categories.get_category("Resistors").fields]
        categories.reorder_fields("Resistors", list(reversed(columns)))
        events.emit(events.SCHEMA_CHANGED)
        h.idle()
        assert h.refreshes() == []  # metadata only
        categories.add_field("Resistors", FieldDef(column="Prozess", label="Prozess"))
        h.idle()
        assert h.refreshes() == [("PartForge.DbLib", True)]  # new column: Altium reloads its column cache
        categories.update_category("Capacitors", {"altium_enabled": False})
        h.idle()
        assert h.refreshes()[-1] == ("PartForge.DbLib", True)
        name = backup.backup_database("Test").name
        backup.restore_backup(name)
        h.idle()
        assert h.refreshes()[-1] == ("PartForge.DbLib", True)  # restored rows may be new for Altium's index
        categories.update_category("Resistors", {"color": "#654321"})
        h.idle()
        assert len(h.refreshes()) == 3  # new baseline after the restore
    finally:
        h.service.stop()


def test_cosmetic_edits_with_the_auto_writer_cause_no_refresh(workspace, harness):
    """Regression (review chk_exp3): colour/icon/label/width edits rebuilt Altium's index twice."""
    ensure_dblib(workspace)
    h = harness(workspace)
    writer = DbLibAutoWriter(on_written=lambda ws, result: h.service.request(rebuild=True))
    writer.start()  # same order as refresh.start_services: the slow rewrite comes before both requests
    h.service.start()
    try:
        before = workspace.dblib_path.read_bytes()
        categories.update_category("Resistors", {"color": "#123456", "icon": "zap"})
        categories.update_field("Resistors", "Notes", {"label": "Notiz", "grid_width": 333})
        h.idle()
        assert workspace.dblib_path.read_bytes() == before and h.refreshes() == []
        categories.add_field("Resistors", FieldDef(column="Sichtbar", label="Sichtbar", show_on_schematic=True))
        h.idle()
        assert h.refreshes() == [("PartForge.DbLib", True)]  # DbLib rewritten: index rebuild (one job)
    finally:
        writer.stop()
        h.service.stop()


def test_schema_notification_without_baseline_or_database(workspace, harness, tmp_path: Path):
    h = harness(workspace)
    h.service._on_schema_changed()  # noqa: SLF001 - no baseline (service not started)
    h.idle()
    assert h.refreshes() == [("PartForge.DbLib", True)]  # unknown what changed: columns may be new
    other = harness(Workspace.create(tmp_path / "Fremd"))  # its database is not the open one
    other.service._on_schema_changed()  # noqa: SLF001
    other.idle()
    assert other.refreshes() == []


def test_workspace_opened_sets_the_baseline(workspace, harness):
    h = harness(workspace)
    h.service.start()
    try:
        events.emit(events.WORKSPACE_OPENED, workspace)
        categories.update_category("Resistors", {"color": "#00AA00"})
        h.idle()
        assert h.refreshes() == []
    finally:
        h.service.stop()


# --------------------------------------------------------------------------- cache / messages


def test_refresh_updates_install_cache_and_describes_result(harness):
    h = harness()
    other = r"D:\Alt\PartForge.DbLib"
    h.bridge.installed.insert(0, other)
    h.bridge.shown.add(other)
    wait_job_in(h, h.service.refresh_now())
    state = cached_install_state(h.ws.dblib_path)
    assert state is not None and state.installed and state.duplicates == [other]
    assert state.first_match == other and not state.resolves_to_this
    assert h.service.status().last_result["skipped"] == {other: "shown"}
    job = h.manager.list(refresh.JOB_KIND)[0]
    texts = " ".join(entry["text"] for entry in job.log)
    assert "Editor-Tab" in texts and "demselben Dateinamen" in texts


def test_note_refresh_result_not_installed(tmp_path: Path):
    lib = tmp_path / "PartForge.DbLib"
    state = note_refresh_result(lib, DbLibRefreshResult(file_name="PartForge.DbLib"))
    assert not state.installed and cached_install_state(lib) is not None
    assert cached_install_state(lib).installed is False  # type: ignore[union-attr]


def test_note_refresh_result_keeps_known_duplicate_kinds(tmp_path: Path):
    lib = tmp_path / "PartForge.DbLib"
    old, gone = str(tmp_path / "Alt" / "PartForge.DbLib"), str(tmp_path / "Weg" / "PartForge.DbLib")
    remember_install_state(DbLibInstallState(path=str(lib), file_name="PartForge.DbLib", installed=True,
                                             duplicates=[old, gone],
                                             duplicate_kinds={old: "same_database", gone: "missing"}), dblib=lib)
    state = note_refresh_result(lib, DbLibRefreshResult(file_name="PartForge.DbLib", matched=[old, str(lib)]))
    assert state.duplicates == [old] and state.duplicate_kinds == {old: "same_database"}
    assert state.installed and not state.resolves_to_this


def test_describe_refresh_messages(tmp_path: Path):
    lib = str(tmp_path / "PartForge.DbLib")
    message, lines = describe_refresh(DbLibRefreshResult(file_name="PartForge.DbLib"))
    assert "keine DbLib" in message and lines[0][0] == "warn"
    closed = DbLibRefreshResult(file_name="PartForge.DbLib", matched=[lib], closed=[lib], refreshed_index=True,
                                refresh_ms=2625)
    message, lines = describe_refresh(closed, Path(lib))
    assert "neu ein" in message and any("2,6 s" in text for _, text in lines)
    modified = DbLibRefreshResult(file_name="PartForge.DbLib", matched=[lib], skipped={lib: "modified"})
    message, lines = describe_refresh(modified, Path(lib))
    assert "nicht aktualisiert" in message and "ungespeicherte" in lines[0][1]
    idle = DbLibRefreshResult(file_name="PartForge.DbLib", matched=[lib], not_open=[lib])
    assert "nicht geladen" in describe_refresh(idle, Path(lib))[0]
    other = DbLibRefreshResult(file_name="PartForge.DbLib", matched=[lib], skipped={lib: "other_kind"})
    assert "keine Datenbankbibliothek" in describe_refresh(other, Path(lib))[1][0][1]


# --------------------------------------------------------------------------- database events


def test_db_writes_emit_parts_changed(workspace):
    seen: list[tuple[str | None, bool]] = []
    handler = lambda table=None, inserted=False: seen.append((table, inserted))  # noqa: E731
    unsubscribe = events.subscribe(events.PARTS_CHANGED, handler)
    base = {"Manufacturer": "YAGEO", "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Description": "R",
            "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}
    try:
        parts.create_part("Resistors", {"Part Number": "R-1", **base})
        parts.update_part("Resistors", "R-1", {"Tolerance": "5%"})
        parts.update_part("Resistors", "R-1", {"Tolerance": "5%"})  # unchanged: no event
        parts.update_part("Resistors", "R-1", {"Part Number": "R-1B"})  # rename = new key for Altium
        parts.duplicate_part("Resistors", "R-1B", "R-2")
        parts.bulk_update("Resistors", ["R-1B", "R-2"], {"Notes": "Serie"})
        parts.regenerate_texts("Resistors", ["R-2"], columns=["Description"])
        result = parts.upsert_parts("Resistors", [{"Part Number": "R-3", **base}, {"Part Number": "R-2", "Notes": "x"}],
                                    mode="update")
        assert result.created == ["R-3"] and result.updated == ["R-2"]
        parts.upsert_parts("Resistors", [{"Part Number": "R-3", **base}], mode="skip")  # nothing written
        parts.set_library_path("footprint", "RESC1608X55N", "Footprints\\PF_CHIP.PcbLib")
        parts.delete_parts("Resistors", ["R-1B", "R-2", "R-3"])
        parts.delete_parts("Resistors", ["gibt-es-nicht"])
        with pytest.raises(PartValidationError):
            parts.create_part("Resistors", {"Part Number": "R-3B"})  # validation error: no event
    finally:
        unsubscribe()
    assert seen == [
        ("Resistors", True),
        ("Resistors", False),
        ("Resistors", True),
        ("Resistors", True),
        ("Resistors", False),
        ("Resistors", False),
        ("Resistors", True),
        (None, False),
        ("Resistors", False),
    ]


def test_service_reacts_to_real_part_writes(workspace, harness):
    h = harness(workspace)
    h.service.start()
    try:
        parts.create_part("Resistors", {"Part Number": "R-77", "Manufacturer": "YAGEO", "Resistance": "1k",
                                        "Tolerance": "1%", "Power": "0.1W", "Description": "R",
                                        "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"})
        h.idle()
        parts.update_part("Resistors", "R-77", {"Notes": "geprüft"})
        h.idle()
    finally:
        h.service.stop()
    assert h.refreshes() == [("PartForge.DbLib", True), ("PartForge.DbLib", False)]



def test_deleted_parts_rebuild_the_index(workspace, harness):
    """F5: after a close-only refresh Altium still loads the old symbol of a deleted key from its cache – a delete
    since the last refresh rebuilds the index (also when the event only says "changed", not "inserted")."""
    h = harness(workspace)
    h.service.start()
    base = {"Manufacturer": "YAGEO", "Resistance": "1k", "Tolerance": "1%", "Power": "0.1W", "Description": "R",
            "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}
    try:
        parts.create_part("Resistors", {"Part Number": "R-DEL", **base})
        h.idle()
        parts.update_part("Resistors", "R-DEL", {"Notes": "geändert"})
        h.idle()
        parts.delete_parts("Resistors", ["R-DEL"])
        h.idle()
        parts.create_part("Resistors", {"Part Number": "R-NEU", **base})
        h.idle()
        parts.update_part("Resistors", "R-NEU", {"Notes": "geändert"})
        h.idle()
    finally:
        h.service.stop()
    assert h.refreshes() == [
        ("PartForge.DbLib", True),  # insert
        ("PartForge.DbLib", False),  # update: close only
        ("PartForge.DbLib", True),  # delete: index rebuilt
        ("PartForge.DbLib", True),  # insert
        ("PartForge.DbLib", False),  # the delete was already handled
    ]
    job = [j for j in h.manager.list(refresh.JOB_KIND) if j.result and j.result["rebuild_index"]][1]
    assert any("gelöscht" in entry["text"] for entry in job.log)


def test_same_named_dblib_of_another_library_is_never_touched(harness, tmp_path: Path):
    """F4: library B (its PartForge.DbLib not installed) must not close and re-index library A's installed DbLib of
    the same file name – neither automatically (quiet, no message) nor by the manual action (warning)."""
    h = harness(installed=None)
    other = str(tmp_path / "A" / "PartForge.DbLib")
    h.bridge.installed = [other]
    h.bridge.hidden_open.add(other)
    h.service.request(rebuild=True)
    h.idle()
    assert h.refreshes() == [] and other in h.bridge.hidden_open  # A's document stays open, no index rebuild
    auto = h.manager.list(refresh.JOB_KIND)[0]
    assert auto.result["installed"] is False and "anderen Bibliothek" in auto.message and other in auto.message
    snap = wait_job_in(h, h.service.refresh_now())
    assert snap["status"] == "done" and snap["result"]["installed"] is False and snap["result"]["quiet"] is False
    assert "nicht installiert" in snap["message"] and h.refreshes() == []
    assert any(entry["level"] == "warn" and "anderen Bibliothek" in entry["text"] for entry in snap["log"])
    assert h.service.status().last_refresh is None


def test_describe_refresh_of_another_librarys_dblib(tmp_path: Path):
    mine = tmp_path / "B" / "PartForge.DbLib"
    other = str(tmp_path / "A" / "PartForge.DbLib")
    result = DbLibRefreshResult(file_name="PartForge.DbLib", matched=[other], closed=[other])
    message, lines = describe_refresh(result, mine)
    assert "nicht installiert" in message and "anderen Bibliothek" in message and lines == [("warn", message)]
    assert refresh.installed_here(result, mine) is False


# --------------------------------------------------------------------------- registry / helpers


def test_start_and_stop_services_reference_counted(tmp_path: Path, monkeypatch):
    h = Harness(Workspace.create(tmp_path / "Svc"))
    previous = refresh.set_refresh_service(h.service)
    try:
        refresh.start_services()
        refresh.start_services()
        assert h.service.running and refresh.get_auto_writer() is not None
        refresh.stop_services()
        assert h.service.running  # still used by the first app
        refresh.stop_services()
        assert not h.service.running and refresh.get_auto_writer() is None
        refresh.stop_services()  # extra stop is harmless
    finally:
        refresh.set_refresh_service(previous)
        h.close()


def test_get_refresh_service_is_a_singleton():
    previous = refresh.set_refresh_service(None)
    try:
        first = refresh.get_refresh_service()
        assert refresh.get_refresh_service() is first and isinstance(first, AltiumRefreshService)
    finally:
        refresh.set_refresh_service(previous)


def test_default_bridge_uses_settings(tmp_path: Path):
    settings = AppSettings()
    settings.altium.bridge_exchange_dir = str(tmp_path / "tausch")
    settings.altium.script_timeout_s = 42.0
    bridge = refresh.default_bridge(settings)
    assert bridge.exchange_dir == tmp_path / "tausch" and bridge.timeout_s == 42.0


def test_default_bridge_never_reaches_altium_in_the_test_suite(monkeypatch):
    monkeypatch.delenv("PARTFORGE_TEST_ALTIUM", raising=False)
    assert refresh.live_altium_allowed() is False
    assert refresh.default_bridge(AppSettings()).is_running() is False  # even if Altium runs on this PC
    monkeypatch.setenv("PARTFORGE_TEST_ALTIUM", "1")
    assert refresh.live_altium_allowed() is True


def test_altium_started_at_reads_process_start_times():
    assert refresh.altium_started_at("pf-gibt-es-nicht-4711.exe") is None
    started = refresh.altium_started_at(Path(sys.executable).name)
    assert started is not None and 946_684_800 < started <= time.time()  # after 2000-01-01


def test_wait_job_helper_with_global_jobs():
    from partforge.jobs import jobs

    snap = wait_job(jobs.submit("test", "Test", lambda ctx: 42))
    assert snap["result"] == 42


def test_dblib_module_cache_is_isolated():
    assert str(dblib._cache_path()).startswith(str(Path(__import__("os").environ["PARTFORGE_HOME"])))
