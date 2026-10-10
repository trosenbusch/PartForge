"""Background jobs with progress reporting (polled or streamed via SSE), and the library guard.

Usage inside a route::

    job = jobs.submit("series", "Widerstandsserie erzeugen", run, payload)
    return job.snapshot()

    def run(ctx: JobContext, payload):
        for i, item in enumerate(items):
            ctx.check_cancelled()
            ctx.progress(i / len(items), f"{item} …")
        return {"created": 42}          # becomes job.result (must be JSON-serialisable)

**Library guard.** The database functions always work on the library that is open *now*. Every
job that writes registry rows or library files therefore holds the library it was started for
(:data:`LIBRARY_JOB_KINDS`), and opening, creating or closing a library goes through
:func:`library_switch`::

    def run(ctx: JobContext, root: Path) -> dict:
        with library_hold(ctx, root) as ws:   # LibraryChanged if ``root`` is not the open library
            ...                               # the library cannot be switched in here

    with library_switch():                    # cancels the holders, waits until they stopped
        open_database(new_ws)                 # (LibraryBusy after LIBRARY_JOB_STOP_TIMEOUT_S)

* :func:`library_hold` is shared: any number of jobs (and direct writes in request threads,
  ``ctx=None``) hold the library at the same time; nested holds of one thread are free.
* :func:`library_switch` is exclusive: it marks the running holders cancelled
  (:data:`CANCEL_LIBRARY_SWITCH`; they stop at their next ``check_cancelled`` – e.g. after the
  library file they are writing) and waits until every hold is released. New holds wait while a
  switch waits or runs; afterwards they find out whether their library is still the open one.
* A job never writes into a library that was opened after it started: a queued job whose library
  was closed meanwhile stops at :func:`library_hold` with :class:`LibraryChanged` (a
  :class:`JobCancelled`), a running one is cancelled before the database is swapped. Queued jobs
  are not cancelled by a switch – if their library stays open (failed or refused switch) they run.

**Snapshots** (:meth:`Job.snapshot`, the API's ``JobSnapshot``): ``id``, ``kind``, ``title``, ``status``,
``progress``, ``message``, ``log``, ``result``, ``error``, ``error_type``, ``detail``, ``cancel_reason``,
``cancel_requested``, ``created``, ``started``, ``finished``, ``version``, ``library``, ``library_name``.

* ``library`` / ``library_name``: root folder and name of the library that was open when the job was
  submitted (``None`` without an open library) – pages that show the progress of their own jobs (Altium
  check, series, import) ignore jobs of another library; the job dock lists every job with its library.

* ``cancel_reason``: why the job was (asked to be) cancelled – :data:`CANCEL_LIBRARY_SWITCH` (a library
  switch or close; also a job that stopped with :class:`LibraryChanged` because its library was no
  longer open) or ``None`` (by the user, or not cancelled). ``cancel_requested``: a cancel request is
  pending or was made.
* **Final message**: every job ends with a German sentence that reports its outcome in ``message``.
  The job sets it itself (``ctx.progress(1.0, "Import fertig: 120 neu, 4 aktualisiert")``); the
  safety net of :meth:`JobManager._run` replaces a message that is still a progress text (empty or
  ending with ``…``/``...``, :func:`is_progress_text`) of a ``done`` job by the result's ``message``
  or ``summary`` text if it has one, else by :data:`DONE_MESSAGE`. ``cancelled``: the text of the
  :class:`JobCancelled` if it has one (not :class:`LibraryChanged`), else
  :data:`CANCELLED_BY_SWITCH_MESSAGE` or :data:`CANCELLED_MESSAGE`. ``failed``: the error text
  (= ``error``, see :func:`error_text`).
* **Brief results** (``brief=True``, job lists ``GET /api/jobs?brief=true`` and
  ``GET /api/jobs/events?brief=true``): a result whose compact JSON encoding is larger than
  :data:`BRIEF_RESULT_MAX_BYTES` (8 KB, UTF-8) is replaced by :func:`brief_result` – see there.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback
import uuid
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from .workspace import Workspace

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]

#: ``Job.cancel_reason`` of the jobs a library switch cancels.
CANCEL_LIBRARY_SWITCH = "library_switch"
#: Final message of a ``done`` job that never reported its outcome (safety net of ``JobManager._run``).
DONE_MESSAGE = "Abgeschlossen"
#: Final message of a job cancelled by the user (or without a reason).
CANCELLED_MESSAGE = "Abgebrochen"
#: Final message of a job cancelled because its library was switched or closed.
CANCELLED_BY_SWITCH_MESSAGE = "Abgebrochen – die Bibliothek wurde gewechselt oder geschlossen"
#: Brief job lists: results whose compact JSON (UTF-8) is larger than this are shortened (:func:`brief_result`).
BRIEF_RESULT_MAX_BYTES = 8 * 1024
#: Brief results keep strings up to this many characters; longer ones are cut to it (ending with "…").
BRIEF_TEXT_MAX_CHARS = 200
#: List/dict fields of which a brief result keeps the first :data:`BRIEF_SAMPLE_SIZE` entries.
BRIEF_SAMPLE_FIELDS: frozenset[str] = frozenset({"errors", "warnings", "missing"})
BRIEF_SAMPLE_SIZE = 5
#: Seconds :func:`library_switch` waits for the library jobs to stop (then :class:`LibraryBusy`, HTTP 409).
LIBRARY_JOB_STOP_TIMEOUT_S = 20.0
#: Job kinds that write parts, registry rows or library files and hold the library for their whole run
#: (the contract of the API routes; the guard itself tracks the holders, whatever their kind).
LIBRARY_JOB_KINDS: frozenset[str] = frozenset({
    "libraries",  # "Bibliotheken schreiben" after creating a library (routes_system)
    "libraries.sync",  # routes_libraries: sync, scan, save, delete, layer header
    "libraries.scan",
    "libraries.save",
    "libraries.delete",
    "libraries.layers",
    "series",  # series commit (routes_series)
    "datasheet-commit",  # datasheet commit (datasheet.proposal.commit_proposal)
    "import",  # spreadsheet import (routes_parts -> importers.spreadsheet.run_import(library=…))
    "libraries.import",  # library import (routes_libimport -> altium.libimport.run_import)
    "libraries.conform",  # batch edit to the house style (routes_housestyle -> altium.housestyle.apply/undo_last)
})
#: Job log line of a job a library switch stopped (unless the job reports it itself).
LIBRARY_SWITCH_MESSAGE = (
    "Die Bibliothek wird geschlossen oder gewechselt – der Job wurde abgebrochen. In die andere Bibliothek wurde "
    "nichts geschrieben."
)
_WAIT_MESSAGE = "Wartet, bis der Bibliothekswechsel abgeschlossen ist …"
_POLL_S = 0.2  # a waiting hold re-checks the job's cancellation this often


def error_text(exc: BaseException) -> str:
    """User-facing text of a job failure. PartForge's own exceptions and ``ValueError``/``RuntimeError``/
    ``OSError`` carry German messages and are shown as they are (no Python class name); anything else is
    an internal error and keeps its class name for the bug report (the traceback is in the job log)."""
    message = str(exc).strip()
    own = type(exc).__module__.startswith("partforge")
    if message and (own or isinstance(exc, (ValueError, RuntimeError, OSError))):
        return message
    return f"Interner Fehler ({type(exc).__name__}){': ' + message if message else ''}"


def is_progress_text(message: str | None) -> bool:
    """Whether ``message`` is no final sentence: empty or a progress text ending with ``…`` or ``...``."""
    text = (message or "").rstrip()
    return not text or text.endswith(("…", "..."))


def _final_message(result: Any) -> str:
    """Final message of a ``done`` job whose message is still a progress text: the result's own
    ``message`` (or ``summary``) sentence, else :data:`DONE_MESSAGE`."""
    if isinstance(result, Mapping):
        for key in ("message", "summary"):
            text = result.get(key)
            if isinstance(text, str) and not is_progress_text(text):
                return text.strip()
    return DONE_MESSAGE


def _cancel_message(job: Job, exc: JobCancelled) -> str:
    """Final message of a cancelled job: the text of the :class:`JobCancelled` (German, e.g. the series'
    own note) – except :class:`LibraryChanged`, whose long text is in the job log – else the standard
    text for a library switch or a user cancel."""
    text = str(exc).strip()
    if text and not isinstance(exc, LibraryChanged):
        return text
    return CANCELLED_BY_SWITCH_MESSAGE if job.cancel_reason == CANCEL_LIBRARY_SWITCH else CANCELLED_MESSAGE


def _json_larger_than(value: Any, limit: int) -> bool:
    """Whether the compact JSON encoding of ``value`` (UTF-8) is larger than ``limit`` bytes.

    Stops encoding at the limit (cheap for huge results); values that cannot be encoded count as large."""
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), default=str)
    size = 0
    try:
        for chunk in encoder.iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > limit:
                return True
    except (TypeError, ValueError, RecursionError):
        return True
    return False


def _sample(value: Mapping[Any, Any] | list[Any] | tuple[Any, ...]) -> dict[Any, Any] | list[Any]:
    if isinstance(value, Mapping):
        return dict(list(value.items())[:BRIEF_SAMPLE_SIZE])
    return list(value[:BRIEF_SAMPLE_SIZE])


def brief_result(result: Any) -> Any:
    """The result of a job snapshot in brief job lists (``brief=True``).

    A result whose compact JSON encoding (UTF-8) is at most :data:`BRIEF_RESULT_MAX_BYTES` bytes
    (8 KB) – or ``None`` – is returned unchanged. A larger result becomes a dict with:

    * every scalar top-level field: numbers, booleans and ``null`` unchanged, strings up to
      :data:`BRIEF_TEXT_MAX_CHARS` (200) characters unchanged, longer strings cut to 200 characters
      (the last one is ``…``);
    * for every list/dict field its length as ``<name>_count`` (a field of that name the result
      already has wins); the fields themselves are left out, except ``errors``, ``warnings`` and
      ``missing``, which keep their first :data:`BRIEF_SAMPLE_SIZE` (5) entries (dict: first 5 items);
    * other values (objects) are left out;
    * ``"result_truncated": true``.

    A larger result that is no dict becomes ``{"result_count": <length>, "result_truncated": true}``
    (lists) or ``{"result_truncated": true}``.
    """
    if result is None or not _json_larger_than(result, BRIEF_RESULT_MAX_BYTES):
        return result
    if not isinstance(result, Mapping):
        if isinstance(result, (list, tuple)):
            return {"result_count": len(result), "result_truncated": True}
        return {"result_truncated": True}
    brief: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for key, value in result.items():
        name = str(key)
        if value is None or isinstance(value, (bool, int, float)):
            brief[name] = value
        elif isinstance(value, str):
            brief[name] = value if len(value) <= BRIEF_TEXT_MAX_CHARS else value[: BRIEF_TEXT_MAX_CHARS - 1] + "…"
        elif isinstance(value, (Mapping, list, tuple)):
            counts[f"{name}_count"] = len(value)
            if name in BRIEF_SAMPLE_FIELDS:
                brief[name] = _sample(value)
    for name, count in counts.items():
        brief.setdefault(name, count)
    brief["result_truncated"] = True
    return brief


class JobCancelled(Exception):
    """Raised by :meth:`JobContext.check_cancelled` when the job was cancelled (the job ends ``cancelled``).

    A German text (``JobCancelled("Serie abgebrochen …")``) becomes the job's final message."""


class LibraryChanged(JobCancelled):
    """The library a job (or a direct write) was started for is not the open library (any more).

    A :class:`JobCancelled`: a job ends ``cancelled``; API routes answer HTTP 409.
    """

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        super().__init__(
            f"Die Bibliothek „{self.root}“ ist nicht mehr geöffnet (gewechselt oder geschlossen) – abgebrochen, in die "
            "andere Bibliothek wurde nichts geschrieben."
        )


class LibraryBusy(RuntimeError):
    """A library switch could not stop the library jobs in time (German message; API: HTTP 409)."""

    def __init__(self, message: str, titles: list[str] | None = None):
        super().__init__(message)
        self.titles = list(titles or [])


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: JobStatus = "queued"
    progress: float = 0.0
    message: str = ""
    log: list[dict[str, Any]] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    error_type: str | None = None  # exception class of a failed job (for logs/tests; ``error`` is the user text)
    # Structured progress for the UI (merged via JobContext.detail, e.g. {"step": "pins", "cost_usd": 0.12}).
    detail: dict[str, Any] = field(default_factory=dict)
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    version: int = 0
    cancel_requested: bool = False
    cancel_reason: str | None = None  # why it was cancelled (e.g. CANCEL_LIBRARY_SWITCH); None = by the user
    library: str | None = None  # root folder of the library open at submit time (None = none open)
    library_name: str | None = None  # its name (WorkspaceSettings.name)
    # (result, brief result) of the last brief snapshot – the result is final once the job ended
    _brief: tuple[Any, Any] | None = field(default=None, init=False, repr=False, compare=False)

    def _brief_result(self) -> Any:
        """:func:`brief_result` of ``self.result`` (computed once per result object)."""
        result = self.result
        cached = self._brief
        if cached is not None and cached[0] is result:
            return cached[1]
        brief = brief_result(result)
        self._brief = (result, brief)
        return brief

    def snapshot(self, with_log: bool = True, *, brief: bool = False) -> dict[str, Any]:
        """The job as JSON-able dict (see the module docstring). ``brief``: :func:`brief_result` instead
        of a result larger than 8 KB (job lists)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "log": list(self.log) if with_log else [],
            "result": self._brief_result() if brief else self.result,
            "error": self.error,
            "error_type": self.error_type,
            "detail": dict(self.detail),
            "cancel_reason": self.cancel_reason,
            "cancel_requested": self.cancel_requested,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "version": self.version,
            "library": self.library,
            "library_name": self.library_name,
        }


class JobContext:
    def __init__(self, manager: JobManager, job: Job):
        self._manager = manager
        self.job = job

    def progress(self, fraction: float | None = None, message: str | None = None) -> None:
        with self._manager._lock:
            if fraction is not None:
                self.job.progress = max(0.0, min(1.0, float(fraction)))
            if message is not None:
                self.job.message = message
            self.job.version += 1

    def detail(self, **fields: Any) -> None:
        """Merge structured progress into ``job.detail`` (JSON-serialisable values; ``None`` removes a key).

        The UI reads it instead of parsing log lines, e.g. ``ctx.detail(step="pins", pages=[1, 2],
        cost_usd=0.12, datasheet_id="…")``."""
        with self._manager._lock:
            for key, value in fields.items():
                if value is None:
                    self.job.detail.pop(key, None)
                else:
                    self.job.detail[key] = value
            self.job.version += 1

    def log(self, text: str, level: Literal["info", "warn", "error", "success"] = "info") -> None:
        with self._manager._lock:
            self.job.log.append({"ts": time.time(), "level": level, "text": text})
            if len(self.job.log) > 2000:
                del self.job.log[:500]
            self.job.version += 1

    @property
    def cancelled(self) -> bool:
        return self.job.cancel_requested

    @property
    def cancel_reason(self) -> str | None:
        """Why the job was cancelled (:data:`CANCEL_LIBRARY_SWITCH` …; ``None`` = by the user or not at all)."""
        return self.job.cancel_reason

    def cancel(self, reason: str | None = None) -> bool:
        """Request cancellation of this job (see :meth:`JobManager.cancel`)."""
        return self._manager.cancel(self.job.id, reason=reason)

    def check_cancelled(self) -> None:
        if self.job.cancel_requested:
            raise JobCancelled()


def _open_library_fields() -> dict[str, str | None]:
    """``library`` / ``library_name`` of a new job: the library open right now."""
    from .workspace import current_or_none

    ws = current_or_none()
    if ws is None:
        return {"library": None, "library_name": None}
    return {"library": str(ws.root), "library_name": ws.settings.name}


class JobManager:
    def __init__(self, max_workers: int = 4, keep: int = 200):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="partforge-job")
        self._keep = keep

    def submit(self, kind: str, title: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, **_open_library_fields())
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
        ctx = JobContext(self, job)
        self._pool.submit(self._run, ctx, fn, args, kwargs)
        return job

    def _run(self, ctx: JobContext, fn: Callable[..., Any], args: tuple, kwargs: dict) -> None:
        job = ctx.job
        with self._lock:
            job.status = "running"
            job.started = time.time()
            job.version += 1
        try:
            result = fn(ctx, *args, **kwargs)
            with self._lock:
                job.result = result
                job.status = "done"
                job.progress = 1.0
                if is_progress_text(job.message):  # safety net: every job ends with its outcome
                    job.message = _final_message(result)
        except JobCancelled as exc:
            with self._lock:
                if isinstance(exc, LibraryChanged) and not job.cancel_requested:
                    job.cancel_reason = CANCEL_LIBRARY_SWITCH  # its library was switched/closed before it ran
                job.status = "cancelled"
                job.message = _cancel_message(job, exc)
        except Exception as exc:  # noqa: BLE001 - report every failure to the UI
            with self._lock:
                job.status = "failed"
                job.error = error_text(exc)
                job.error_type = type(exc).__name__
                job.message = job.error
                job.log.append({"ts": time.time(), "level": "error", "text": job.error})
                job.log.append({"ts": time.time(), "level": "error", "text": traceback.format_exc(limit=8)})
        finally:
            with self._lock:
                job.finished = time.time()
                job.version += 1

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, kind: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [j for j in self._jobs.values() if kind is None or j.kind == kind]
        return sorted(jobs, key=lambda j: j.created, reverse=True)

    def cancel(self, job_id: str, *, reason: str | None = None) -> bool:
        """Request cancellation (the job stops at its next ``check_cancelled``). ``reason`` is kept
        in ``Job.cancel_reason`` – the first request wins. ``False`` if the job is not active."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job.status not in ("queued", "running"):
                return False
            if not job.cancel_requested:
                job.cancel_reason = reason
            job.cancel_requested = True
            job.version += 1
            return True

    def run_sync(self, kind: str, title: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Job:
        """Run a job function in the calling thread (used by tests and CLI)."""
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, **_open_library_fields())
        with self._lock:
            self._jobs[job.id] = job
        self._run(JobContext(self, job), fn, args, kwargs)
        return job

    def _prune(self) -> None:
        if len(self._jobs) <= self._keep:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status in ("done", "failed", "cancelled")),
            key=lambda j: j.created,
        )
        for job in finished[: len(self._jobs) - self._keep]:
            self._jobs.pop(job.id, None)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


jobs = JobManager()


# --------------------------------------------------------------------------- library guard


def open_library(root: str | os.PathLike[str]) -> Workspace | None:
    """The open workspace if the library folder ``root`` is open – as workspace *and* as the open
    database (both are swapped by a library switch); ``None`` otherwise."""
    from .db import core
    from .workspace import current_for, same_folder

    ws = current_for(root)
    if ws is None:
        return None
    try:
        if not core.is_open() or not same_folder(core.current_workspace().root, root):
            return None
    except Exception:  # noqa: BLE001 - closed concurrently
        return None
    return ws


@dataclass
class _Hold:
    root: Path
    ctx: JobContext | None  # None = a direct write in a request thread (waited for, never cancelled)
    depth: int = 1


class LibraryGuard:
    """Shared holds of the open library by jobs, exclusive library switches (see the module docstring)."""

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._holds: dict[int, _Hold] = {}  # thread ident -> hold (nested holds of a thread count depth)
        self._switching = False  # a switch holds the library exclusively
        self._switches_waiting = 0  # switches waiting for the holders: new holds wait (no starvation)
        self.exclusive = _ExclusiveLock(self)

    # -- holds ------------------------------------------------------------------------
    @contextmanager
    def hold(
        self, ctx: JobContext | None, root: str | os.PathLike[str], *, announce: bool = True
    ) -> Iterator[Workspace]:
        """Hold the library ``root`` (yields its open :class:`~partforge.workspace.Workspace`).

        Waits while a library switch waits or runs; raises :class:`JobCancelled` if the job was
        cancelled meanwhile and :class:`LibraryChanged` if ``root`` is not the open library.
        ``announce``: log a German warning into the job when a library switch stopped it or its
        library is gone (``False`` = the job reports that itself).
        """
        target = Path(os.path.abspath(os.fspath(root)))
        outermost = self._enter(ctx, target)
        try:
            ws = open_library(target)
            if ws is None:
                raise LibraryChanged(target)
            yield ws
        except JobCancelled as exc:
            if announce and outermost and ctx is not None:
                _announce(ctx, exc)
            raise
        finally:
            self._leave()

    def _enter(self, ctx: JobContext | None, target: Path) -> bool:
        """Register the calling thread as holder; ``True`` for its outermost hold."""
        ident = threading.get_ident()
        with self._cond:
            current = self._holds.get(ident)
            if current is not None:
                current.depth += 1
                return False
            told = False
            while (self._switching or self._switches_waiting) and not (ctx is not None and ctx.cancelled):
                if ctx is not None and not told:
                    told = True
                    ctx.progress(None, _WAIT_MESSAGE)
                self._cond.wait(_POLL_S)
            if ctx is not None:
                ctx.check_cancelled()  # cancelled while queued or waiting (nothing held yet)
            self._holds[ident] = _Hold(root=target, ctx=ctx)
            return True

    def _leave(self) -> None:
        ident = threading.get_ident()
        with self._cond:
            hold = self._holds[ident]
            hold.depth -= 1
            if hold.depth <= 0:
                del self._holds[ident]
                self._cond.notify_all()

    def holding(self) -> bool:
        """Whether the calling thread holds the library."""
        with self._cond:
            return threading.get_ident() in self._holds

    def holders(self) -> list[tuple[Job | None, Path]]:
        """``(job or None for a direct write, library root)`` of every current hold."""
        with self._cond:
            return [(h.ctx.job if h.ctx is not None else None, h.root) for h in self._holds.values()]

    @property
    def switch_pending(self) -> bool:
        """A library switch waits for the holders or runs (new holds wait meanwhile)."""
        with self._cond:
            return self._switching or self._switches_waiting > 0

    # -- switches ---------------------------------------------------------------------
    @contextmanager
    def switch(self, timeout: float | None = None) -> Iterator[None]:
        """Hold the library exclusively while it is opened, created or closed.

        Cancels the running library jobs (reason :data:`CANCEL_LIBRARY_SWITCH`) and waits until
        every hold is released – at most ``timeout`` seconds (default
        :data:`LIBRARY_JOB_STOP_TIMEOUT_S`), then :class:`LibraryBusy` with a German message; the
        cancel requests stay in force.
        """
        limit = LIBRARY_JOB_STOP_TIMEOUT_S if timeout is None else timeout
        if not self._acquire(limit, stop_jobs=True):
            raise LibraryBusy(self._busy_message(), [t for t in self._holder_titles() if t])
        try:
            yield
        finally:
            self._release()

    def _acquire(self, timeout: float | None, *, stop_jobs: bool) -> bool:
        deadline = None if timeout is None else time.monotonic() + max(0.0, timeout)
        with self._cond:
            if threading.get_ident() in self._holds:
                raise RuntimeError(
                    "Ein Bibliothekswechsel innerhalb eines Bibliotheks-Jobs würde auf sich selbst warten."
                )
            self._switches_waiting += 1  # from now on no new hold starts
            running = [h.ctx for h in self._holds.values() if h.ctx is not None] if stop_jobs else []
        try:
            for ctx in running:
                cancel = getattr(ctx, "cancel", None)
                if callable(cancel):
                    cancel(CANCEL_LIBRARY_SWITCH)
            with self._cond:
                while self._switching or self._holds:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if remaining is not None and remaining <= 0:
                        return False
                    self._cond.wait(remaining)
                self._switching = True
                return True
        finally:
            with self._cond:
                self._switches_waiting -= 1
                self._cond.notify_all()

    def _release(self) -> None:
        with self._cond:
            self._switching = False
            self._cond.notify_all()

    def _holder_titles(self) -> list[str | None]:
        with self._cond:
            return [h.ctx.job.title if h.ctx is not None else None for h in self._holds.values()]

    def _busy_message(self) -> str:
        titles = self._holder_titles()
        named = list(dict.fromkeys(f"„{t}“" for t in titles if t))
        parts = [("Job " if len(named) == 1 else "Jobs ") + ", ".join(named)] if named else []
        if any(t is None for t in titles):
            parts.append("ein laufender Speichervorgang")
        what = " und ".join(parts) or "ein anderer Vorgang"
        return (
            f"Die Bibliothek wird gerade geschrieben ({what}). Laufende Jobs werden nach dem aktuellen Schritt "
            "abgebrochen – bitte in einigen Sekunden erneut versuchen."
        )


class _ExclusiveLock:
    """The exclusive side of a :class:`LibraryGuard` as a plain lock: while it is held, every
    library hold waits. Unlike :meth:`LibraryGuard.switch` it cancels no job."""

    def __init__(self, guard: LibraryGuard):
        self._guard = guard

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        limit: float | None = (None if timeout is None or timeout < 0 else timeout) if blocking else 0.0
        return self._guard._acquire(limit, stop_jobs=False)

    def release(self) -> None:
        self._guard._release()

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


def _announce(ctx: JobContext, exc: JobCancelled) -> None:
    if isinstance(exc, LibraryChanged):
        ctx.log(str(exc), "warn")
    elif getattr(ctx, "cancel_reason", None) == CANCEL_LIBRARY_SWITCH:
        ctx.log(LIBRARY_SWITCH_MESSAGE, "warn")


library_guard = LibraryGuard()


def library_hold(
    ctx: JobContext | None, root: str | os.PathLike[str], *, announce: bool = True
) -> AbstractContextManager[Workspace]:
    """Hold the library at ``root`` for a job (``ctx``) or a direct write (``ctx=None``); see
    :meth:`LibraryGuard.hold`."""
    return library_guard.hold(ctx, root, announce=announce)


def library_switch(timeout: float | None = None) -> AbstractContextManager[None]:
    """Open, create or close a library: stop the library jobs first; see :meth:`LibraryGuard.switch`."""
    return library_guard.switch(timeout)


def cancelled_by_switch(ctx: JobContext | None) -> bool:
    """Whether a library switch cancelled this job."""
    return ctx is not None and getattr(ctx, "cancel_reason", None) == CANCEL_LIBRARY_SWITCH
