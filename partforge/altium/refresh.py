"""Make a running Altium see PartForge's database changes (``recherche/altium-refresh.md``).

Altium loads an installed DbLib as a hidden server document whose ODBC connection pins
a SQLite snapshot (VERIFIED); new or changed rows only become visible after that
document is closed. :class:`AltiumRefreshService` does this automatically:

* it listens to :data:`partforge.events.PARTS_CHANGED` (emitted by :mod:`partforge.db.parts`
  after every committed write) and to schema changes;
* a schema notification is compared with the structure Altium can see – tables, their
  ``altium_enabled`` flag, their physical columns and the database engine. Purely
  cosmetic edits (label, colour, icon, help, column width, field order …) are ignored;
  added, renamed or removed columns, a rewritten DbLib
  (:class:`~partforge.altium.dblib.DbLibAutoWriter`) and a restored backup (the engine is
  replaced) rebuild Altium's component index – Altium caches the column list of every
  table, closing the hidden document alone does not show a new column (VERIFIED,
  ``altium-e2e.md``);
* changes are **debounced** (~2 s) so a burst of writes causes one refresh;
* when ``settings.altium.auto_refresh`` is on and Altium is running, a background job
  ``altium.refresh`` runs :meth:`~partforge.altium.bridge.core.AltiumBridge.refresh_dblib` –
  with ``rebuild_index=True`` if parts were inserted since the last refresh (clears
  Altium's "not found" cache, ~3 s), else only the fast close (~0.3 s + script start);
* the cached install state decides whether that is worth a script run: installed (checked in
  this Altium session) → refresh; unknown, not installed or cached in an earlier Altium session →
  first the read-only install-state check, and only if **this** DbLib is installed the refresh –
  the bridge's refresh matches DbLibs by file name, so it must never run for a library whose
  DbLib is not installed (it would close and re-index another library's ``PartForge.DbLib``);
  not installed according to a check in the current Altium session → skipped until the next
  session or a manual action. An automatic run that found no installation ends with
  ``result.quiet = true`` (the UI shows no message for it) and does not count as a refresh
  (``RefreshStatus.last_refresh`` stays);
* deleted parts (``pf_audit`` entries ``delete`` since the last refresh) also rebuild the index:
  after a close-only refresh Altium still loads the old symbol of a deleted key from its cache;
* :meth:`AltiumRefreshService.refresh_now` is the manual "In Altium aktualisieren"; a
  manual request that arrives while a refresh runs is carried out right after it (also
  when the automatic refresh is switched off).

Nothing here blocks the thread that wrote to the database: event handlers only compare
cached metadata, set flags and (re)start a timer; the bridge runs in a job thread. After
a failure the service does not retry on its own (except when the bridge was busy) – the
next change or the manual action tries again, so a broken Altium script never runs in a loop.

In the automated test suite the default bridge never reaches a real Altium (it reports
Altium as not running) unless ``PARTFORGE_TEST_ALTIUM=1`` enables the live tests, and an
automatic refresh never probes an unknown install state there (test libraries use the
default file name, which the user's own installed DbLib may share).

:func:`start_services` / :func:`stop_services` (called from the Altium router's lifespan)
start the refresh service together with the :class:`~partforge.altium.dblib.DbLibAutoWriter`.
"""
from __future__ import annotations

import contextlib
import logging
import os
import sys
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, Field

from .. import events
from ..config import AppSettings, load_settings
from ..jobs import Job, JobContext, JobManager, jobs
from ..workspace import Workspace, WorkspaceNotOpen, current_or_none
from .bridge.core import (
    AltiumBridge,
    AltiumNotRunning,
    BridgeBusyError,
    BridgeError,
    DbLibInstallState,
    DbLibRefreshResult,
    InstalledDbLib,
)
from .bridge.process import X2_IMAGE
from .dblib import (
    DbLibAutoWriter,
    DbLibWriteResult,
    cached_install_state,
    database_matches,
    remember_install_state,
    same_path,
)
from .texts import SETTINGS_ALTIUM

log = logging.getLogger(__name__)

__all__ = [
    "JOB_KIND",
    "installed_here",
    "not_installed_message",
    "AltiumRefreshService",
    "RefreshStatus",
    "altium_started_at",
    "default_bridge",
    "describe_refresh",
    "get_auto_writer",
    "get_refresh_service",
    "live_altium_allowed",
    "note_refresh_result",
    "set_refresh_service",
    "start_services",
    "stop_services",
]

JOB_KIND: Final = "altium.refresh"
DEFAULT_DEBOUNCE_S: Final = 2.0
MAX_WAIT_S: Final = 15.0  # continuous writes: refresh at least this often
BUSY_RETRY_S: Final = 10.0
MAX_BUSY_RETRIES: Final = 3
#: Without a known Altium start time, a cached install state is re-checked after this.
STALE_INSTALL_STATE_S: Final = 3600.0

_OFF_REASON: Final = f"Die automatische Aktualisierung in Altium ist ausgeschaltet ({SETTINGS_ALTIUM})."


def _under_pytest() -> bool:
    return "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules


def live_altium_allowed() -> bool:
    """False inside the automated test suite (module tests must never start Altium scripts);
    ``PARTFORGE_TEST_ALTIUM=1`` allows it for the live tests."""
    if os.environ.get("PARTFORGE_TEST_ALTIUM") == "1":
        return True
    return not _under_pytest()


def default_bridge(settings: AppSettings | None = None) -> AltiumBridge:
    """Bridge configured from the app settings (X2.EXE, timeout, exchange directory).

    Inside the test suite (see :func:`live_altium_allowed`) it reports Altium as not
    running, so no test reaches the user's Altium by accident."""
    settings = settings or load_settings()
    extra: dict[str, Any] = {}
    if not live_altium_allowed():
        extra["process_check"] = lambda: False
    return AltiumBridge.from_settings(settings, exchange_dir=settings.resolved_bridge_exchange_dir(), **extra)


def altium_started_at(image: str = X2_IMAGE) -> float | None:
    """Start time (Unix seconds) of the oldest running ``X2.EXE``; None if none runs or the
    time is not readable. Read-only (process list and process times, no window access)."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel32.GetProcessTimes.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return None
        pids: list[int] = []
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                if entry.szExeFile.lower() == image.lower():
                    pids.append(int(entry.th32ProcessID))
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        oldest: float | None = None
        for pid in pids:
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                continue
            try:
                created, ended, kernel, user = (wintypes.FILETIME() for _ in range(4))
                if kernel32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(ended),
                                            ctypes.byref(kernel), ctypes.byref(user)):
                    ticks = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
                    started = ticks / 10_000_000 - 11_644_473_600  # FILETIME (1601, 100 ns) -> Unix
                    oldest = started if oldest is None else min(oldest, started)
            finally:
                kernel32.CloseHandle(handle)
        return oldest
    except Exception as exc:  # noqa: BLE001 - only an optimisation of the install-state cache
        log.debug("Startzeit von %s nicht lesbar: %s", image, exc)
        return None


def _audit_position(ws: Workspace) -> int | None:
    """Highest ``pf_audit`` id of the open database of ``ws`` (None: not open / another library)."""
    if not database_matches(ws):
        return None
    try:
        from sqlalchemy import func, select

        from ..db import core
        from ..db.schema import pf_audit

        with core.read() as conn:
            return int(conn.execute(select(func.max(pf_audit.c.id))).scalar() or 0)
    except Exception as exc:  # noqa: BLE001 - only decides about an extra index rebuild
        log.debug("Änderungshistorie nicht lesbar: %s", exc)
        return None


def _deleted_after(ws: Workspace, position: int) -> bool:
    """Whether parts were deleted (``pf_audit`` action ``delete``) after the entry ``position``."""
    if not database_matches(ws):
        return False
    try:
        from sqlalchemy import select

        from ..db import core
        from ..db.schema import pf_audit

        stmt = select(pf_audit.c.id).where(pf_audit.c.id > position, pf_audit.c.action == "delete").limit(1)
        with core.read() as conn:
            return conn.execute(stmt).first() is not None
    except Exception as exc:  # noqa: BLE001
        log.debug("Änderungshistorie nicht lesbar: %s", exc)
        return False


class RefreshStatus(BaseModel):
    """State of the automatic Altium refresh (``GET /api/altium/status``)."""

    auto_refresh: bool
    pending: bool = False  # changes not yet passed on to Altium
    pending_rebuild: bool = False  # parts were inserted -> next refresh rebuilds Altium's index
    pending_tables: list[str] = Field(default_factory=list)
    manual_pending: bool = False  # a manual refresh follows the running one
    running: bool = False
    job_id: str | None = None
    last_request: float | None = None
    last_refresh: float | None = None  # last refresh that reached this DbLib in Altium (not a run that found none)
    last_result: dict[str, Any] | None = None
    last_message: str | None = None
    last_error: str | None = None
    last_error_time: float | None = None
    last_skip_reason: str | None = None  # why the last automatic refresh did not run
    refresh_count: int = 0


@dataclass(frozen=True)
class _Target:
    dblib: Path
    file_name: str


@dataclass(frozen=True)
class _SchemaMark:
    """What Altium can see of the schema: tables, ``altium_enabled``, physical columns, engine."""

    root: str
    engine: Callable[[], Any]  # weak reference to the open DbState (a restored backup replaces it)
    structure: tuple[tuple[str, str, bool, tuple[str, ...]], ...]

    def same_engine(self, other: _SchemaMark) -> bool:
        mine = self.engine()
        return mine is not None and mine is other.engine()


def schema_mark(ws: Workspace) -> _SchemaMark | None:
    """Structure fingerprint of the open database of ``ws`` (None: not open / another library)."""
    from ..db import categories, core

    if not database_matches(ws):
        return None
    try:
        state = core.get_state()
        cats = categories.list_categories(with_counts=False)
    except Exception as exc:  # noqa: BLE001 - closed concurrently: nothing to compare
        log.debug("Schemastand nicht lesbar: %s", exc)
        return None
    structure = tuple(sorted(
        (c.table.casefold(), c.table, bool(c.altium_enabled), tuple(sorted(f.column for f in c.fields))) for c in cats
    ))
    return _SchemaMark(root=os.path.normcase(str(ws.root)), engine=weakref.ref(state), structure=structure)


def note_refresh_result(dblib: Path, result: DbLibRefreshResult) -> DbLibInstallState:
    """Update the cached install state from what a refresh saw in Altium (state afterwards:
    closed documents are closed, skipped ones are still open)."""
    entries = [
        InstalledDbLib(
            index=i,
            path=path,
            same_file=same_path(path, dblib),
            document_open=path in result.skipped,
            document_shown=result.skipped.get(path) == "shown",
            document_modified=result.skipped.get(path) == "modified",
        )
        for i, path in enumerate(result.matched)
    ]
    mine = [e for e in entries if e.same_file]
    previous = cached_install_state(dblib)
    duplicates = [e.path for e in entries if not e.same_file]
    known_kinds = previous.duplicate_kinds if previous else {}
    state = DbLibInstallState(
        path=previous.path if previous else str(dblib),
        file_name=result.file_name,
        installed=bool(mine),
        position=previous.position if previous and mine else None,
        same_name=entries,
        duplicates=duplicates,
        first_match=entries[0].path if entries else None,
        resolves_to_this=bool(entries) and entries[0].same_file,
        installed_count=previous.installed_count if previous else 0,
        duplicate_kinds={p: k for p, k in known_kinds.items() if p in duplicates},
    )
    remember_install_state(state, dblib=dblib)
    return state


def not_installed_message(file_name: str, others: list[str]) -> str:
    """German outcome when this DbLib is not installed in Altium (``others``: same-named DbLibs of other
    libraries – they are never touched)."""
    if others:
        return (f"Diese DbLib ist in Altium nicht installiert – eine gleichnamige DbLib einer anderen Bibliothek ist "
                f"installiert ({', '.join(others[:3])}{' …' if len(others) > 3 else ''}); sie wurde nicht angefasst.")
    return f"Die DbLib „{file_name}“ ist in Altium nicht installiert – nichts zu aktualisieren."


def installed_here(result: DbLibRefreshResult, dblib: Path) -> bool:
    """Whether the refresh found **this** DbLib installed (not only one of the same file name)."""
    return any(same_path(p, dblib) for p in result.matched)


def describe_refresh(result: DbLibRefreshResult, dblib: Path | None = None) -> tuple[str, list[tuple[str, str]]]:
    """German summary and detail lines ``(level, text)`` of a refresh result."""
    lines: list[tuple[str, str]] = []
    if not result.matched:
        message = f"In Altium ist keine DbLib „{result.file_name}“ installiert – nichts zu aktualisieren."
        return message, [("warn", message)]
    if dblib is not None and not any(same_path(p, dblib) for p in result.matched):
        message = not_installed_message(result.file_name, list(result.matched))
        return message, [("warn", message)]
    others = [p for p in result.matched if dblib is not None and not same_path(p, dblib)]
    if others:
        lines.append(("warn", f"Weitere installierte DbLib(s) mit demselben Dateinamen: {', '.join(others)} – Altium "
                              "verwendet die zuerst installierte. Bitte auf der Altium-Seite den Installationsstatus "
                              "prüfen."))
    for path, reason in result.skipped.items():
        if reason == "shown":
            lines.append(("warn", f"Die DbLib ist in Altium in einem Editor-Tab geöffnet ({path}) – bitte den Tab "
                                  "schließen, sonst sieht Altium die Änderungen nicht."))
        elif reason == "modified":
            lines.append(("warn", f"Die DbLib hat in Altium ungespeicherte Änderungen ({path}) – PartForge schließt sie "
                                  "nicht. Bitte in Altium verwerfen oder speichern."))
        else:
            lines.append(("warn", f"Das Altium-Dokument {path} ist keine Datenbankbibliothek und wurde nicht angefasst."))
    if result.refreshed_index:
        seconds = f" in {result.refresh_ms / 1000:.1f} s".replace(".", ",") if result.refresh_ms is not None else ""
        lines.append(("info", f"Bauteilindex der installierten Bibliotheken neu aufgebaut{seconds}."))
    if result.closed:
        message = "Altium liest die Bibliotheksdatenbank neu ein – Änderungen sind jetzt sichtbar."
        lines.append(("success", message))
    elif result.skipped:
        message = "Altium konnte nicht aktualisiert werden (DbLib in Altium geöffnet)."
    else:
        message = "Altium hatte die DbLib nicht geladen – die nächste Abfrage liest ohnehin den aktuellen Stand."
        lines.append(("success", message))
    return message, lines


class AltiumRefreshService:
    """Debounced automatic refresh of the DbLib in a running Altium (see module docstring)."""

    def __init__(
        self,
        *,
        debounce_s: float = DEFAULT_DEBOUNCE_S,
        max_wait_s: float = MAX_WAIT_S,
        busy_retry_s: float = BUSY_RETRY_S,
        bridge_factory: Callable[[], AltiumBridge] | None = None,
        settings_provider: Callable[[], AppSettings] | None = None,
        workspace_provider: Callable[[], Workspace | None] = current_or_none,
        install_state_provider: Callable[[Path], DbLibInstallState | None] = cached_install_state,
        session_provider: Callable[[], float | None] = altium_started_at,
        probe_install_state: bool | None = None,
        job_manager: JobManager | None = None,
    ):
        """``probe_install_state``: let an automatic refresh check an unknown install state
        (None = yes, except inside the automated test suite – there a probe could reach a
        DbLib of the user's Altium that shares the default file name)."""
        self.debounce_s = float(debounce_s)
        self.max_wait_s = max(float(max_wait_s), self.debounce_s)
        self.busy_retry_s = float(busy_retry_s)
        self._bridge_factory = bridge_factory or default_bridge
        self._settings = settings_provider or load_settings
        self._workspace = workspace_provider
        self._install_state = install_state_provider
        self._altium_started = session_provider
        self._probe = (not _under_pytest()) if probe_install_state is None else bool(probe_install_state)
        self._jobs = job_manager or jobs
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._timer: threading.Timer | None = None
        self._timer_due = 0.0  # monotonic time the armed timer fires
        self._deadline = 0.0  # monotonic time the refresh is due (trailing debounce)
        self._first_pending: float | None = None  # monotonic time of the oldest unhandled request
        self._generation = 0
        self._stopped = False  # after stop(): no timers (a job that is still running ends quietly)
        self._target: _Target | None = None
        self._pending = False
        self._pending_rebuild = False
        self._pending_tables: set[str] = set()
        self._job: Job | None = None
        self._rerun = False  # automatic requests arrived while a job ran
        self._manual_rerun = False  # a manual refresh follows the running job (no automatic gate)
        self._checking = 0  # timer threads evaluating the gate outside the lock
        self._busy_retries = 0
        self._schema_seen: _SchemaMark | None = None
        self._unsubscribers: list[Callable[[], None]] = []
        self._last_request: float | None = None
        self._last_refresh: float | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_message: str | None = None
        self._last_error: str | None = None
        self._last_error_time: float | None = None
        self._last_skip: str | None = None
        self._count = 0
        self._audit_mark: tuple[str, int] | None = None  # (library root, highest pf_audit id at the last refresh)

    # -- lifecycle --------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return bool(self._unsubscribers)

    def start(self) -> None:
        """Subscribe to the database events (idempotent) and note the current schema."""
        from ..db import categories

        with self._lock:
            self._stopped = False
            if self._unsubscribers:
                return
            self._unsubscribers = [
                events.subscribe(events.PARTS_CHANGED, self._on_parts_changed),
                events.subscribe(events.SCHEMA_CHANGED, self._on_schema_changed),
                events.subscribe(events.WORKSPACE_OPENED, self._on_workspace_opened),
                categories.on_schema_change(self._on_schema_changed),
            ]
        ws = self._workspace()
        if ws is not None:
            self._note_schema(ws)
            self._note_audit(ws)

    def stop(self) -> None:
        """Unsubscribe and cancel a pending timer (a running job finishes on its own)."""
        with self._lock:
            unsubscribers, self._unsubscribers = self._unsubscribers, []
            self._stopped = True
            self._manual_rerun = False
            self._cancel_timer_locked()
            self._generation += 1
        for unsubscribe in unsubscribers:
            with contextlib.suppress(Exception):
                unsubscribe()

    # -- event handlers (run in the writing thread: flags + timer only) ------------------
    def _on_parts_changed(self, table: str | None = None, inserted: bool = False, *_args: Any, **_kwargs: Any) -> None:
        self.request(rebuild=bool(inserted), table=table)

    def _note_schema(self, ws: Workspace) -> _SchemaMark | None:
        mark = schema_mark(ws)
        if mark is not None:
            with self._lock:
                self._schema_seen = mark
        return mark

    def _on_workspace_opened(self, ws: Workspace | None = None, *_args: Any, **_kwargs: Any) -> None:
        target = ws if isinstance(ws, Workspace) else self._workspace()
        if target is not None:
            self._note_schema(target)  # baseline; a rewritten DbLib is announced by the auto-writer
            self._note_audit(target)

    # -- deletes since the last refresh (Altium keeps the old symbol of a deleted key until the index rebuild) --
    def _note_audit(self, ws: Workspace) -> None:
        position = _audit_position(ws)
        if position is not None:
            with self._lock:
                self._audit_mark = (os.path.normcase(str(ws.root)), position)

    def _deleted_since_mark(self, dblib: Path) -> tuple[bool, int | None]:
        """``(parts were deleted since the last refresh, current audit position)`` of the open library."""
        ws = self._workspace()
        if ws is None or not same_path(ws.dblib_path, dblib):
            return False, None
        position = _audit_position(ws)
        with self._lock:
            mark = self._audit_mark
        if position is None or mark is None or mark[0] != os.path.normcase(str(ws.root)):
            return False, position
        return _deleted_after(ws, mark[1]), position

    def _on_schema_changed(self, *_args: Any, **_kwargs: Any) -> None:
        ws = self._workspace()
        if ws is None:
            return
        with self._lock:
            previous = self._schema_seen
        mark = self._note_schema(ws)
        if mark is None:
            return  # database closed or of another library: nothing Altium reads changed
        # Altium caches the column list of every DbLib table in its library object: closing the
        # hidden document refreshes the rows but not the columns – a new column stays invisible
        # until IntegratedLibrary:RefreshInstalledLibraries (VERIFIED, altium-e2e.md). Every
        # change Altium can see therefore rebuilds the index; metadata-only edits do nothing.
        if previous is None or previous.root != mark.root:
            self.request(rebuild=True)  # no baseline: the columns may have changed
        elif not previous.same_engine(mark):
            self.request(rebuild=True)  # restored backup: rows may be new for Altium's index
        elif previous.structure != mark.structure:
            self.request(rebuild=True)  # columns/tables changed: Altium must reload its column cache
        else:
            log.debug("Schemaänderung ohne Auswirkung auf Altium (nur Metadaten) – keine Aktualisierung")

    def request(self, *, rebuild: bool = False, table: str | None = None, delay_s: float | None = None) -> bool:
        """Note a database change of the open library; the refresh follows after the debounce.

        Returns False when no library is open (nothing to refresh)."""
        ws = self._workspace()
        if ws is None:
            return False
        with self._lock:
            self._target = _Target(dblib=ws.dblib_path, file_name=ws.settings.dblib_file)
            self._pending = True
            self._pending_rebuild = self._pending_rebuild or rebuild
            if table:
                self._pending_tables.add(str(table))
            self._last_request = time.time()
            now = time.monotonic()
            if self._first_pending is None:
                self._first_pending = now
            delay = self.debounce_s if delay_s is None else delay_s
            # trailing debounce, but never later than max_wait_s after the oldest request
            self._schedule_locked(min(delay, max(0.0, self._first_pending + self.max_wait_s - now)))
        return True

    # -- timer ------------------------------------------------------------------------
    # One timer thread per debounce period: an armed timer that fires before the
    # deadline re-arms itself for the rest, so a burst of writes creates no thread churn.

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
            self._idle.notify_all()

    def _arm_locked(self, delay_s: float) -> None:
        generation = self._generation
        timer = threading.Timer(max(0.0, delay_s), self._on_timer, args=(generation,))
        timer.daemon = True
        timer.name = "partforge-altium-refresh"
        self._timer = timer
        self._timer_due = time.monotonic() + max(0.0, delay_s)
        timer.start()

    def _schedule_locked(self, delay_s: float) -> None:
        if self._stopped:
            return
        now = time.monotonic()
        self._deadline = now + max(0.0, delay_s)
        if self._timer is not None and self._timer_due <= self._deadline + 0.001:
            return  # fires earlier and re-arms until the deadline
        self._cancel_timer_locked()
        self._arm_locked(self._deadline - now)

    def _job_running_locked(self) -> bool:
        return self._job is not None and self._job.status in ("queued", "running")

    def _on_timer(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or threading.current_thread() is not self._timer:
                return  # stopped, or replaced by another timer
            remaining = self._deadline - time.monotonic()
            if remaining > 0.002:
                self._arm_locked(remaining)
                return
            self._timer = None
            target = self._target
            if self._job_running_locked():
                self._rerun = self._rerun or self._pending
                return
            if self._manual_rerun and target is not None:  # retry of a manual refresh: no automatic gate
                self._manual_rerun = False
                self._start_quietly_locked(target, "manual")
                return
            if not self._pending or target is None:
                self._idle.notify_all()
                return
            self._checking += 1  # wait_idle() must not report "idle" while the gate is evaluated
        gate: tuple[str, bool] | None = ("Prüfung abgebrochen.", True)
        try:
            gate = self._auto_gate(target)  # settings, process list, install cache – outside the lock
        finally:
            with self._lock:
                self._checking -= 1
                self._after_gate_locked(generation, target, gate)
                self._idle.notify_all()

    def _after_gate_locked(self, generation: int, target: _Target, gate: tuple[str, bool] | None) -> None:
        if generation != self._generation or self._timer is not None:
            return  # stopped or re-armed meanwhile
        if gate is not None:
            reason, keep = gate
            self._last_skip = reason
            self._first_pending = None
            if not keep:
                self._pending = False
                self._pending_rebuild = False
                self._pending_tables.clear()
            log.debug("Automatische Altium-Aktualisierung übersprungen: %s", reason)
            return
        if self._job_running_locked():
            self._rerun = True
            return
        self._start_quietly_locked(target, "auto")

    def _install_state_stale(self, state: DbLibInstallState) -> bool:
        """True if a cached install state may be outdated: checked before the running Altium
        started (or, when its start time is unknown, longer than STALE_INSTALL_STATE_S ago)."""
        try:
            started = self._altium_started()
        except Exception:  # noqa: BLE001
            started = None
        if started is not None:
            return state.checked < started
        return time.time() - state.checked > STALE_INSTALL_STATE_S

    def _auto_gate(self, target: _Target) -> tuple[str, bool] | None:
        """Why an automatic refresh must not run now: ``(reason, keep_pending)``; None = run.

        An unknown install state (or "not installed" from an earlier Altium session) does not
        stop the refresh: ``refresh_dblib`` touches nothing when the DbLib is not installed,
        and its result is cached – one check per Altium session."""
        try:
            if not self._settings().altium.auto_refresh:
                return _OFF_REASON, True
            bridge = self._bridge_factory()
            if not bridge.x2_path:
                return "Altium Designer (X2.EXE) wurde nicht gefunden.", False
            if not bridge.is_running():
                return "Altium Designer läuft nicht – beim nächsten Start liest Altium den aktuellen Stand.", False
            if bridge.last_wedge:
                return ("Die Altium-Brücke hängt (Skript im Debugger angehalten?). Bitte auf der Altium-Seite "
                        "„Skript anhalten“ wählen und danach „In Altium aktualisieren“."), True
            state = self._install_state(target.dblib)
            if state is None or (not state.installed and self._install_state_stale(state)):
                if not self._probe:
                    return ("Unbekannt, ob die DbLib in Altium installiert ist – bitte auf der Altium-Seite "
                            "„Installationsstatus prüfen“ oder „In Altium aktualisieren“ wählen."), True
            elif not state.installed:
                return ("Die DbLib ist in Altium nicht installiert (geprüft in dieser Altium-Sitzung) – nach einer "
                        "Installation von Hand bitte „In Altium aktualisieren“ wählen."), False
        except Exception as exc:  # noqa: BLE001 - a check must never break the timer thread
            log.warning("Prüfung vor der Altium-Aktualisierung fehlgeschlagen: %s", exc)
            return f"Prüfung fehlgeschlagen: {exc}", True
        return None

    # -- jobs -------------------------------------------------------------------------
    def _start_job_locked(self, target: _Target, trigger: str) -> Job:
        rebuild = self._pending_rebuild
        tables = sorted(self._pending_tables)
        title = "Altium aktualisieren (inkl. Bauteilindex)" if rebuild else "Altium aktualisieren"
        job = self._jobs.submit(JOB_KIND, title, self._run, target, rebuild, trigger, tables)  # may raise: state kept
        self._pending = False
        self._pending_rebuild = False
        self._pending_tables.clear()
        self._first_pending = None
        self._last_skip = None
        self._job = job
        return job

    def _start_quietly_locked(self, target: _Target, trigger: str) -> None:
        """Start a job from the timer or a finishing job (never raises)."""
        try:
            self._start_job_locked(target, trigger)
        except RuntimeError as exc:  # job manager shut down (application exit)
            log.warning("Altium-Aktualisierung nicht gestartet: %s", exc)
            self._idle.notify_all()

    def refresh_now(self, rebuild_index: bool | None = None) -> Job:
        """Manual refresh ("In Altium aktualisieren"); ``rebuild_index`` None = rebuild if
        parts were inserted since the last refresh. Returns the job – while a refresh runs,
        that running job; a requested index rebuild or changes made since it started then
        follow in a second job right after it.

        Raises :class:`WorkspaceNotOpen`, :class:`BridgeError` (X2.EXE missing) or
        :class:`AltiumNotRunning`."""
        ws = self._workspace()
        if ws is None:
            raise WorkspaceNotOpen("Es ist keine Bibliothek geöffnet.")
        bridge = self._bridge_factory()
        if not bridge.x2_path:
            raise BridgeError("Altium Designer (X2.EXE) wurde nicht gefunden – Pfad unter Einstellungen › Allgemein › Altium Designer eintragen.")
        if not bridge.is_running():
            raise AltiumNotRunning("Altium Designer ist nicht gestartet. Bitte Altium starten und erneut versuchen.")
        target = _Target(dblib=ws.dblib_path, file_name=ws.settings.dblib_file)
        with self._lock:
            if self._job_running_locked() and self._job is not None:
                if rebuild_index:
                    self._pending = True
                    self._pending_rebuild = True
                if rebuild_index or self._pending:
                    self._target = target
                    self._manual_rerun = True
                return self._job
            self._cancel_timer_locked()
            self._manual_rerun = False
            if rebuild_index is not None:
                self._pending_rebuild = bool(rebuild_index)
            return self._start_job_locked(target, "manual")

    def _installed_here(self, ctx: JobContext, bridge: AltiumBridge, target: _Target) -> DbLibInstallState:
        """Install state of **this** DbLib: the cache when it says "installed" and was checked in the running
        Altium session, else a read-only check through the bridge (its result is cached)."""
        try:
            state = self._install_state(target.dblib)
        except Exception as exc:  # noqa: BLE001 - an unreadable cache only means: check
            log.debug("Installationsstatus nicht lesbar: %s", exc)
            state = None
        if state is not None and state.installed and not self._install_state_stale(state):
            return state
        ctx.progress(0.03, "Installierte Bibliotheken in Altium werden gelesen …")
        fresh = bridge.install_state(target.dblib)
        if state is not None and state.duplicate_kinds:  # the classified duplicates survive the re-read (as in
            fresh.duplicate_kinds = {p: k for p, k in state.duplicate_kinds.items() if p in fresh.duplicates}  # note_refresh_result)
        remember_install_state(fresh, dblib=target.dblib)
        return fresh

    def _run(self, ctx: JobContext, target: _Target, rebuild: bool, trigger: str, tables: list[str]) -> dict[str, Any]:
        failed = False
        not_running = False
        retry_s: float | None = None
        try:
            if tables:
                ctx.log(f"Geänderte Kategorien: {', '.join(tables)}")
            bridge = self._bridge_factory()
            state = self._installed_here(ctx, bridge, target)
            if not state.installed:  # never touch the same-named DbLib of another library (F4)
                message = not_installed_message(state.file_name or target.file_name, list(state.duplicates))
                quiet = trigger == "auto" and not state.duplicates
                ctx.log(message, "info" if quiet else "warn")
                with self._lock:
                    self._last_skip = message
                    self._last_error = None
                    self._last_error_time = None
                    self._busy_retries = 0
                ctx.progress(1.0, message)
                return {"message": message, "trigger": trigger, "rebuild_index": False, "installed": False,
                        "quiet": trigger == "auto", "result": None}
            deleted, position = self._deleted_since_mark(target.dblib)
            if deleted and not rebuild:
                rebuild = True
                ctx.log("Bauteile wurden gelöscht – Altiums Bauteilindex wird neu aufgebaut, damit es die gelöschten "
                        "nicht mehr anbietet.")
            ctx.progress(0.05, "Altium liest die DbLib neu ein …")
            result = bridge.refresh_dblib(target.file_name, rebuild_index=rebuild)
            note_refresh_result(target.dblib, result)
            message, lines = describe_refresh(result, target.dblib)
            for level, text in lines:
                ctx.log(text, level)  # type: ignore[arg-type]
            here = installed_here(result, target.dblib)
            with self._lock:
                if here:
                    self._last_refresh = time.time()
                    self._count += 1
                    if position is not None:
                        ws = self._workspace()
                        if ws is not None and same_path(ws.dblib_path, target.dblib):
                            self._audit_mark = (os.path.normcase(str(ws.root)), position)
                self._last_result = result.model_dump(mode="json")
                self._last_message = message
                self._last_error = None
                self._last_error_time = None
                self._busy_retries = 0
            ctx.progress(1.0, message)
            return {
                "message": message,
                "trigger": trigger,
                "rebuild_index": rebuild,
                "installed": here,
                "quiet": trigger == "auto" and not here,
                "result": result.model_dump(mode="json"),
            }
        except BridgeBusyError as exc:
            failed = True
            with self._lock:
                self._record_error_locked(str(exc), target, rebuild)
                self._busy_retries += 1
                if self._busy_retries <= MAX_BUSY_RETRIES:
                    retry_s = self.busy_retry_s
            raise
        except AltiumNotRunning as exc:
            failed = not_running = True
            with self._lock:  # a fresh Altium start reads the current state anyway
                self._record_error_locked(str(exc), None, False)
            raise
        except Exception as exc:
            failed = True
            with self._lock:
                self._record_error_locked(str(exc), target, rebuild)
            raise
        finally:
            with self._lock:
                if self._job is not None and self._job.id == ctx.job.id:
                    self._job = None
                manual = self._manual_rerun
                self._manual_rerun = False
                follow = self._target or target
                if retry_s is not None:
                    self._rerun = False
                    self._manual_rerun = manual or trigger == "manual"  # the retry keeps the manual intent
                    self._schedule_locked(retry_s)
                elif manual and not not_running and not self._stopped:
                    self._rerun = False
                    self._start_quietly_locked(follow, "manual")
                elif self._rerun and not failed and self._pending:
                    self._rerun = False
                    self._schedule_locked(self.debounce_s)
                else:
                    self._rerun = False
                self._idle.notify_all()

    def _record_error_locked(self, message: str, target: _Target | None, rebuild: bool) -> None:
        self._last_error = message
        self._last_error_time = time.time()
        log.warning("Altium-Aktualisierung fehlgeschlagen: %s", message)
        if target is not None:  # keep the request so the next trigger still rebuilds if needed
            self._pending = True
            self._pending_rebuild = self._pending_rebuild or rebuild
            self._target = self._target or target

    # -- status -----------------------------------------------------------------------
    def status(self) -> RefreshStatus:
        try:
            auto = bool(self._settings().altium.auto_refresh)
        except Exception:  # noqa: BLE001
            auto = False
        with self._lock:
            running = self._job_running_locked()
            return RefreshStatus(
                auto_refresh=auto,
                pending=self._pending,
                pending_rebuild=self._pending_rebuild,
                pending_tables=sorted(self._pending_tables),
                manual_pending=self._manual_rerun,
                running=running,
                job_id=self._job.id if running and self._job is not None else None,
                last_request=self._last_request,
                last_refresh=self._last_refresh,
                last_result=self._last_result,
                last_message=self._last_message,
                last_error=self._last_error,
                last_error_time=self._last_error_time,
                last_skip_reason=self._last_skip,
                refresh_count=self._count,
            )

    def wait_idle(self, timeout_s: float = 10.0) -> bool:
        """Wait until no timer is armed and no refresh job runs (tests, shutdown)."""
        deadline = time.monotonic() + timeout_s
        with self._lock:
            while self._timer is not None or self._checking or self._job_running_locked():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(min(remaining, 0.05))
            return True


# --------------------------------------------------------------------------- service registry

_registry_lock = threading.Lock()
_service: AltiumRefreshService | None = None
_writer: DbLibAutoWriter | None = None
_users = 0


def get_refresh_service() -> AltiumRefreshService:
    """The process-wide refresh service (created on first use, not started)."""
    global _service
    with _registry_lock:
        if _service is None:
            _service = AltiumRefreshService()
        return _service


def set_refresh_service(service: AltiumRefreshService | None) -> AltiumRefreshService | None:
    """Replace the process-wide service (tests); returns the previous one (not stopped)."""
    global _service
    with _registry_lock:
        previous, _service = _service, service
    return previous


def get_auto_writer() -> DbLibAutoWriter | None:
    return _writer


def _on_dblib_written(_ws: Workspace, _result: DbLibWriteResult) -> None:
    # a rewritten DbLib (new tables/fields, moved database) must be re-read by Altium
    get_refresh_service().request(rebuild=True)


def start_services() -> None:
    """Start the DbLib auto-writer and the refresh service (reference counted, idempotent)."""
    global _users, _writer
    with _registry_lock:
        _users += 1
        if _users > 1:
            return
    service = get_refresh_service()
    writer = DbLibAutoWriter(on_written=_on_dblib_written)
    # The writer subscribes first: on a schema change it rewrites the DbLib (the slow part)
    # and requests the index rebuild before the service's own structure check requests the
    # close, so both requests fall into one debounce period (one Altium script).
    writer.start()
    service.start()
    with _registry_lock:
        _writer = writer
    # The launcher reopens the last library before the server (and this lifespan) starts,
    # so WORKSPACE_OPENED was missed: bring its DbLib up to date now.
    ws = current_or_none()
    if ws is not None:
        writer.ensure(ws, reason="Programmstart")
    log.debug("Altium-Dienste gestartet (DbLib-Automatik, Aktualisierung)")


def stop_services() -> None:
    """Stop both services when the last user (app) stops."""
    global _users, _writer
    with _registry_lock:
        _users = max(0, _users - 1)
        if _users:
            return
        writer, _writer = _writer, None
        service = _service
    if writer is not None:
        writer.stop()
    if service is not None:
        service.stop()
    log.debug("Altium-Dienste beendet")
