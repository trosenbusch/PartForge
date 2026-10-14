"""System endpoints: health, app settings, workspace (library folder) management, jobs.

Creating a library (``POST /workspace/create``) with ``with_examples`` seeds the example
parts with their generated symbols and footprints (registry status ``pending``) and starts
the job "Bibliotheken schreiben" (:func:`start_library_sync`), which writes the SchLib/
PcbLib files through :func:`partforge.altium.sync.sync_pending`; the response carries the
job snapshot under ``"job"``.

Library guard (:func:`partforge.jobs.library_hold` / :func:`partforge.jobs.library_switch`):
the job – like every job that writes registry rows or library files – holds the library it
was started for during its whole run. Opening, creating or closing a library first cancels
the running library jobs and waits until they have stopped (e.g. after the library file being
written; at most :data:`LIBRARY_JOB_STOP_TIMEOUT_S`, then HTTP 409 with a German message)
before the database is swapped – so no job ever writes into another library. A job whose
library is no longer open when it starts ends with a warning and leaves everything ``pending``,
as it does without a usable library writer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .. import __version__
from ..config import (
    DEFAULT_LIBRARY_NAME,
    AppSettings,
    default_library_parent,
    exchange_dir_problem,
    executable_path_problem,
    key_file_path_problem,
    key_file_status,
    load_settings,
    remember_workspace,
    save_settings,
    store_api_key,
)
from ..domain.text import plural
from ..jobs import (
    CANCEL_LIBRARY_SWITCH,
    LIBRARY_JOB_STOP_TIMEOUT_S,
    Job,
    JobCancelled,
    JobContext,
    LibraryBusy,
    LibraryChanged,
    cancelled_by_switch,
    jobs,
    library_guard,
    library_hold,
    library_switch,
    open_library,
)
from ..workspace import (
    LOCK_FILE,
    WORKSPACE_FILE,
    LibraryLocked,
    Workspace,
    WorkspaceSettings,
    current_or_none,
    lock_library,
    pn_format_problem,
    same_folder,
    set_current,
    unlock_library,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["system"])

LIBRARY_SYNC_JOB_KIND = "libraries"
LIBRARY_SYNC_JOB_TITLE = "Bibliotheken schreiben"
# LIBRARY_JOB_STOP_TIMEOUT_S (from partforge.jobs): seconds opening/creating/closing a library waits for
# the library jobs to stop (then HTTP 409); read at call time, so it can be lowered per module.
_PENDING_HINT = (
    "Nicht geschriebene Symbole und Footprints bleiben „ausstehend“ und werden beim nächsten Synchronisieren "
    "geschrieben."
)

# Exclusive side of the shared library guard as a plain lock (held by every library switch while
# the database is swapped; library jobs wait for it, none is cancelled).
_library_jobs_lock = library_guard.exclusive


@router.get("/health")
def health() -> dict:
    """Liveness without a token: version and the open library's folder and name – never its settings (the
    PostgreSQL connection string would hand the password to any local process)."""
    ws = current_or_none()
    return {"ok": True, "version": __version__,
            "workspace": {"root": str(ws.root), "name": ws.settings.name} if ws else None}


# --------------------------------------------------------------------------- settings
class SettingsOut(BaseModel):
    settings: AppSettings
    ai_key_configured: bool
    ai_key_source: str | None  # "env" | "stored" | "file" | "replay" | None
    ai_key_file_problem: str | None = Field(
        default=None,
        description="Deutscher Hinweis, warum eine konfigurierte Schlüsseldatei keinen Schlüssel liefert "
                    "(UNC/Gerätepfad, nicht gefunden, zu groß, kein gültiger sk-ant-…-Schlüssel) – sonst null",
    )
    altium_exe: str | None
    rust_writer: str | None


class ApiKeyIn(BaseModel):
    key: str


def _settings_security_problems(settings: AppSettings) -> list[str]:
    """German reasons why executable/key paths in ``settings`` are unsafe (QA sec finding 2).

    The library writer and X2.EXE must be absolute local ``.exe`` files (no UNC/device paths; X2.EXE by
    name); the API-key file must be a local path. Empty values mean "auto-detect"/"no file" and are fine.
    """
    problems: list[str] = []
    writer = (settings.altium.rust_writer_path or "").strip()
    if writer and (problem := executable_path_problem(writer)) is not None:
        problems.append(f"Bibliotheks-Writer: {problem}")
    x2 = (settings.altium.x2_path or "").strip()
    if x2 and (problem := executable_path_problem(x2, require_name="X2.EXE")) is not None:
        problems.append(f"Altium Designer (X2.EXE): {problem}")
    key_file = (settings.ai.api_key_file or "").strip()
    if key_file and (problem := key_file_path_problem(key_file)) is not None:
        problems.append(problem)
    if (problem := exchange_dir_problem(settings.altium.bridge_exchange_dir)) is not None:
        problems.append(f"Altium-Brücke: {problem}")  # Altium runs the scripts written there
    return problems


def _settings_out(settings: AppSettings) -> SettingsOut:
    # same source of truth as GET /api/ai/status (the replay mode counts as configured, source "replay")
    from ..datasheet.llm import key_status

    key_configured, key_source = key_status(settings)
    return SettingsOut(
        settings=settings,
        ai_key_configured=key_configured,
        ai_key_source=key_source,
        ai_key_file_problem=key_file_status(settings),
        altium_exe=settings.resolved_altium_exe(),
        rust_writer=settings.resolved_rust_writer(),
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    return _settings_out(load_settings())


@router.put("/settings", response_model=SettingsOut)
def put_settings(settings: AppSettings) -> SettingsOut:
    problems = _settings_security_problems(settings)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    save_settings(settings)
    return _settings_out(settings)


@router.put("/settings/api-key", response_model=SettingsOut)
def put_api_key(body: ApiKeyIn) -> SettingsOut:
    """Store the Claude API key encrypted (DPAPI) for this Windows user. The key is never returned."""
    if not body.key.strip().startswith("sk-"):
        raise HTTPException(status_code=400, detail="Das sieht nicht wie ein Claude-API-Schlüssel aus (beginnt mit 'sk-').")
    store_api_key(body.key)
    return _settings_out(load_settings())


@router.delete("/settings/api-key", response_model=SettingsOut)
def delete_api_key() -> SettingsOut:
    store_api_key(None)
    return _settings_out(load_settings())


# --------------------------------------------------------------------------- workspace
class WorkspaceOpenIn(BaseModel):
    path: str


class WorkspaceCreateIn(BaseModel):
    path: str
    name: str | None = None
    settings: WorkspaceSettings | None = None
    with_examples: bool = True
    # with examples: start the job "Bibliotheken schreiben" right away (False = stay "pending")
    write_libraries: bool = True


class RecentWorkspace(BaseModel):
    path: str
    name: str | None
    exists: bool


def activate_workspace(ws: Workspace) -> dict:
    """Open ``ws`` as the current workspace (closes a previously open one). Public for the launcher."""
    return _activate(ws)


# ---- library switch: stop the library jobs before the database is swapped


@contextmanager
def _library_switch() -> Iterator[None]:
    """Hold the library exclusively while it is opened, created or closed
    (:func:`partforge.jobs.library_switch`).

    Cancels the running library jobs ("Bibliotheken schreiben", sync, scan, save, series and
    datasheet commits – each stops after its current step, e.g. the library file it is writing)
    and waits until they have released the library. HTTP 409 (German message naming the jobs)
    if they do not stop within :data:`LIBRARY_JOB_STOP_TIMEOUT_S`.
    """
    try:
        with library_switch(timeout=LIBRARY_JOB_STOP_TIMEOUT_S):
            yield
    except LibraryBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _open_locked(ws: Workspace) -> Workspace | None:
    """Open the database of ``ws`` and make it current (caller holds :func:`_library_switch`).

    First the library folder is locked for this process (``partforge.lock``,
    :func:`partforge.workspace.lock_library`): a library open in another PartForge (second window,
    another user or PC) is refused with HTTP 409 – two processes would overwrite each other's database
    and SchLib/PcbLib writes. ``open_database`` validates the new database before it replaces the open
    one: on failure (HTTP 409) the previous library stays open and usable (and keeps its lock). Returns
    the previous workspace; its lock is released.
    """
    from ..db import open_database
    from ..db.errors import DbError
    from ..db.templates import ensure_default_symbol_kinds

    previous = current_or_none()
    try:
        newly_locked = lock_library(ws.root)
    except LibraryLocked as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except OSError as exc:  # read-only folder, no permission – PartForge could not write there anyway
        raise HTTPException(status_code=409, detail=f"Bibliothek kann nicht geöffnet werden: Die Sperrdatei "
                            f"„{LOCK_FILE}“ im Ordner „{ws.root}“ lässt sich nicht anlegen ({exc.strerror or exc}).") from exc
    try:
        open_database(ws)
    except BaseException as exc:
        if newly_locked:
            unlock_library(ws.root)
        if isinstance(exc, DbError):  # corrupt file, schema of a newer PartForge version, network drive, ...
            raise HTTPException(status_code=409, detail=f"Bibliothek kann nicht geöffnet werden: {exc}") from exc
        raise
    if previous is not None and not same_folder(previous.root, ws.root):
        unlock_library(previous.root)
    _note_database_path(ws)
    set_current(ws)
    try:  # data migration of libraries created by older versions (cheap read when nothing to do)
        ensure_default_symbol_kinds()
    except Exception:  # noqa: BLE001 - the library is open and usable; the old names are still understood
        log.exception("Standardsymbole der Kategorien in %s konnten nicht umgestellt werden", ws.root)
    return previous


def _announce_opened(ws: Workspace, previous: Workspace | None) -> dict:
    from .. import events

    if previous is not None:
        events.emit(events.WORKSPACE_CLOSED)
    remember_workspace(str(ws.root))
    events.emit(events.WORKSPACE_OPENED, ws)
    return ws.info()


def _activate(ws: Workspace) -> dict:
    # A library another PartForge holds is refused *before* the switch, which cancels the running jobs of the open
    # library: a refused switch must not cost the user a running import or sync.
    previous = current_or_none()
    early = False
    if previous is not None and not same_folder(previous.root, ws.root):
        try:
            early = lock_library(ws.root)
        except LibraryLocked as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=409, detail=f"Bibliothek kann nicht geöffnet werden: Die Sperrdatei "
                                f"„{LOCK_FILE}“ im Ordner „{ws.root}“ lässt sich nicht anlegen ({exc.strerror or exc}).") from exc
    try:
        with _library_switch():
            previous = _open_locked(ws)
    except BaseException:
        now = current_or_none()
        if early and (now is None or not same_folder(now.root, ws.root)):
            unlock_library(ws.root)
        raise
    return _announce_opened(ws, previous)


@router.get("/workspace")
def get_workspace() -> dict | None:
    ws = current_or_none()
    return ws.info() if ws else None


@router.get("/workspace/recent", response_model=list[RecentWorkspace])
def recent_workspaces() -> list[RecentWorkspace]:
    out = []
    for p in load_settings().recent_workspaces:
        name = None
        exists = Workspace.is_workspace(p)
        if exists:
            try:
                name = Workspace.open(p).settings.name
            except Exception:  # noqa: BLE001
                exists = False
        out.append(RecentWorkspace(path=p, name=name, exists=exists))
    return out


def _note_database_path(ws: Workspace) -> None:
    """A SQLite path Altium cannot use in the DbLib (characters outside Windows-1252, ``;`` …) is shown as a
    warning of the open library (INT-12; a new library in such a folder is refused before it is created)."""
    problem = _database_path_problem(ws.root, ws.settings)
    if problem and problem not in ws.warnings:
        ws.warnings.append(problem)


@router.post("/workspace/open")
def open_workspace(body: WorkspaceOpenIn) -> dict:
    path = Path(body.path)
    if not Workspace.is_workspace(path):
        raise HTTPException(status_code=404, detail=f"Kein PartForge-Bibliotheksordner: {path}")
    try:
        ws = Workspace.open(path)
    except (ValueError, OSError) as exc:  # hand-edited partforge.json (pydantic ValidationError is a ValueError)
        raise HTTPException(status_code=400, detail=f"Die Bibliothek in „{path}“ kann nicht geöffnet werden – "
                            f"„{WORKSPACE_FILE}“ ist ungültig: {exc}") from exc
    return _activate(ws)


# ---- job "Bibliotheken schreiben"


def _writer_problem(ws: Workspace) -> str | None:
    """German reason why no library writer can be used for ``ws`` (``None`` = a writer is ready).

    Cheap: at most one (cached) ``--version`` call of the Rust writer; the Altium backend
    only looks at the process list – no Altium script runs."""
    from ..altium import libwriter
    from ..altium.rustwriter import RustWriterError

    try:
        writer = libwriter.get_writer(workspace=ws)
        ready, message = writer.available()
    except (libwriter.WriterUnavailable, RustWriterError, OSError, RuntimeError) as exc:
        return str(exc).strip() or "Kein Bibliotheks-Writer verfügbar."
    return None if ready else (message or "Kein Bibliotheks-Writer verfügbar.")


def _cancel_message(ctx: JobContext) -> str:
    if cancelled_by_switch(ctx):
        return f"Die Bibliothek wird geschlossen oder gewechselt – Schreiben abgebrochen. {_PENDING_HINT}"
    return f"Schreiben abgebrochen. {_PENDING_HINT}"


#: Final messages of "Bibliotheken schreiben" that wrote nothing (the reason is in the log and ``result.reason``).
NOT_WRITTEN_NO_WRITER = (
    "Bibliotheken nicht geschrieben – kein Bibliotheks-Writer verfügbar; Symbole und Footprints bleiben ausstehend"
)
NOT_WRITTEN_CLOSED = (
    "Bibliotheken nicht geschrieben – die Bibliothek ist nicht mehr geöffnet; Symbole und Footprints bleiben ausstehend"
)


def libraries_written_message(summary: dict[str, Any]) -> str:
    """Final message of "Bibliotheken schreiben" from the summary of :func:`partforge.altium.sync.sync_pending`,
    e.g. „Bibliotheken geschrieben: 15 Symbole und 13 Footprints, 1 Fehler“."""
    if summary.get("skipped"):
        return NOT_WRITTEN_NO_WRITER
    symbols: dict[str, Any] = summary.get("symbols") or {}
    footprints: dict[str, Any] = summary.get("footprints") or {}
    if not symbols.get("total") and not footprints.get("total"):
        return "Bibliotheken sind aktuell – nichts zu schreiben"
    ok_symbols, ok_footprints = int(symbols.get("ok") or 0), int(footprints.get("ok") or 0)
    errors = int(symbols.get("error") or 0) + int(footprints.get("error") or 0)
    missing = int(symbols.get("missing") or 0) + int(footprints.get("missing") or 0)
    problems = ([plural(errors, "Fehler", "Fehler")] if errors else []) + (
        [f"{plural(missing, 'Eintrag', 'Einträge')} nicht erzeugbar"] if missing else []
    )
    if not ok_symbols and not ok_footprints:
        return f"Bibliotheken nicht geschrieben: {', '.join(problems)}" if problems else "Bibliotheken sind aktuell"
    written = f"{plural(ok_symbols, 'Symbol', 'Symbole')} und {plural(ok_footprints, 'Footprint', 'Footprints')}"
    return ", ".join([f"Bibliotheken geschrieben: {written}", *problems])


def _write_libraries(ctx: JobContext, root: Path) -> dict[str, Any]:
    """Job body of "Bibliotheken schreiben": write every pending registry entry of the library at ``root``.

    Holds the library for its whole run (:func:`partforge.jobs.library_hold`). Ends ``done``
    with a warning and ``{"skipped": True, "reason": …}`` – nothing lost, the entries stay
    ``pending`` – when the library is no longer open or no library writer is usable;
    ``cancelled`` (with a warning) when it was cancelled or the library is switched/closed.
    Final message: :func:`libraries_written_message` or :data:`NOT_WRITTEN_NO_WRITER` /
    :data:`NOT_WRITTEN_CLOSED`.
    """
    from ..altium import sync

    target = Path(root).resolve()
    try:
        with library_hold(ctx, target, announce=False) as ws:  # waits while a library switch runs
            problem = _writer_problem(ws)
            if problem is not None:
                reason = f"{problem} {_PENDING_HINT}"
                ctx.log(reason, "warn")
                ctx.progress(1.0, NOT_WRITTEN_NO_WRITER)
                return {"skipped": True, "reason": reason}
            ctx.progress(0.0, "Symbole und Footprints werden in die Bibliotheken geschrieben …")
            try:
                result = sync.sync_pending(ctx)
            except JobCancelled:
                raise
            except Exception:
                if open_library(target) is None:  # the database went away under the job (bypassing the guard)
                    log.warning("Bibliothek %s während des Schreibens geschlossen", target, exc_info=True)
                    ctx.cancel(CANCEL_LIBRARY_SWITCH)  # cancel_reason: the UI explains why it stopped
                    raise JobCancelled() from None
                raise
            summary = result if isinstance(result, dict) else {"result": result}
            message = libraries_written_message(summary)
            if not summary.get("skipped"):  # sync_pending logged its own reason
                problems = (summary.get("symbols") or {}, summary.get("footprints") or {})
                clean = not any(int(p.get("error") or 0) or int(p.get("missing") or 0) for p in problems)
                ctx.log(message, "success" if clean else "warn")
            ctx.progress(1.0, message)
            return summary
    except LibraryChanged:
        reason = f"Die Bibliothek {target} ist nicht mehr geöffnet. {_PENDING_HINT}"
        ctx.log(reason, "warn")
        ctx.progress(1.0, NOT_WRITTEN_CLOSED)
        return {"skipped": True, "reason": reason}
    except JobCancelled:
        ctx.log(_cancel_message(ctx), "warn")
        raise


def start_library_sync(ws: Workspace) -> Job:
    """Start the job "Bibliotheken schreiben" for ``ws`` (writes the pending symbols/footprints)."""
    return jobs.submit(LIBRARY_SYNC_JOB_KIND, LIBRARY_SYNC_JOB_TITLE, _write_libraries, ws.root)


# ---- creating a library


_FOLDER_LABELS: dict[str, str] = {
    "symbols": "Ordner für Symbole",
    "footprints": "Ordner für Footprints",
    "models": "Ordner für 3D-Modelle",
    "datasheets": "Ordner für Datenblätter",
    "backups": "Ordner für Sicherungen",
    "exports": "Ordner für Exporte",
}
_BAD_PATH_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


def _relative_path_problem(label: str, value: str, *, file_name: bool = False) -> str | None:
    """German problem if ``value`` is not a path inside the library folder (``None`` = fine)."""
    text = (value or "").strip()
    if not text:
        return f"{label}: Bitte einen Namen angeben."
    win = PureWindowsPath(text)
    if win.drive or win.root:
        return f"{label} „{text}“ muss relativ zum Bibliotheksordner angegeben werden (ohne Laufwerk oder „\\“ am Anfang)."
    if _BAD_PATH_CHARS.search(text):
        return f"{label} „{text}“ enthält unzulässige Zeichen (< > : \" | ? * oder Steuerzeichen)."
    parts = [p for p in re.split(r"[\\/]+", text) if p not in ("", ".")]
    if ".." in parts:
        return f"{label} „{text}“ muss innerhalb des Bibliotheksordners liegen („..“ ist nicht erlaubt)."
    if not parts:
        return f"{label} „{text}“ ist kein gültiger Name."
    if file_name and len(parts) != 1:
        return f"{label} „{text}“ muss ein reiner Dateiname ohne Ordner sein."
    reserved = next((p for p in parts if p.split(".")[0].strip().upper() in _RESERVED_NAMES), None)
    if reserved is not None:
        return f"{label} „{text}“ verwendet den unter Windows reservierten Namen „{reserved}“."
    return None


def settings_path_problems(settings: WorkspaceSettings) -> list[str]:
    """German problems of the folder and file names in ``settings``.

    The library folder is self-contained: every folder, the database file and the DbLib
    (a plain ``*.DbLib`` file name – Altium resolves the library paths relative to it) must
    lie inside it. Absolute paths, drives and ``..`` are refused (they would create or
    overwrite files elsewhere).
    """
    problems = [
        problem
        for key, label in _FOLDER_LABELS.items()
        if (problem := _relative_path_problem(label, getattr(settings.folders, key))) is not None
    ]
    if settings.db.kind == "sqlite":
        problem = _relative_path_problem("Datenbankdatei", settings.db.sqlite_file)
        if problem:
            problems.append(problem)
    problem = _relative_path_problem("DbLib-Datei", settings.dblib_file, file_name=True)
    if problem:
        problems.append(problem)
    elif not settings.dblib_file.strip().lower().endswith(".dblib"):
        problems.append(f"Die DbLib-Datei „{settings.dblib_file.strip()}“ muss auf „.DbLib“ enden.")
    return problems


@dataclass
class _NewPaths:
    """Folders and files a library creation may add, recorded before it starts, so that a
    failed creation leaves nothing behind (pre-existing folders and files are never touched)."""

    dirs: list[Path] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)

    @classmethod
    def before(cls, root: Path, settings: WorkspaceSettings) -> _NewPaths:
        new = cls()
        sqlite = root / settings.db.sqlite_file
        for folder in [root, *(root / f for f in settings.folders.model_dump().values()), sqlite.parent]:
            missing: list[Path] = []
            current = folder
            while not current.exists() and current not in new.dirs and current.parent != current:
                missing.append(current)
                current = current.parent
            new.dirs.extend(reversed(missing))
        candidates = [root / WORKSPACE_FILE, (root / WORKSPACE_FILE).with_suffix(".tmp"), root / settings.dblib_file,
                      root / LOCK_FILE]
        if settings.db.kind == "sqlite":
            candidates += [sqlite, *(sqlite.with_name(sqlite.name + s) for s in ("-wal", "-shm", "-journal"))]
        new.files = [f for f in candidates if not f.exists()]
        return new

    def remove(self) -> None:
        for path in self.files:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                log.warning("%s konnte nach dem Fehlschlag nicht entfernt werden: %s", path, exc)
        for folder in sorted(self.dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                folder.rmdir()  # only empty folders
            except OSError:
                pass


def _database_path_problem(root: Path, settings: WorkspaceSettings) -> str | None:
    """German problem when the SQLite database path of a library cannot stand in its DbLib (Altium reads the
    DbLib as Windows-1252; ``;``, ``{`` ``}`` and ``"`` break the connection string) – ``None`` if fine."""
    if settings.db.kind != "sqlite":
        return None
    from ..altium import dblib

    database = Path(root).absolute() / settings.db.sqlite_file
    problem = dblib.sqlite_path_problem(database)
    if problem is None:
        return None
    return (f"Der Datenbankpfad „{database}“ enthält {problem}. Altium liest die DbLib-Datei in Windows-1252 und "
            "fände die Datenbank so nicht – die DbLib kann nicht geschrieben werden. Bitte einen Ordner ohne diese "
            "Zeichen wählen (z. B. ohne Ł, Ω, Emoji oder Semikolon).")


def _check_new_library(target: Path, settings: WorkspaceSettings) -> None:
    """Refuse a new library before anything is created (German HTTP errors)."""
    from ..db import core

    problems = settings_path_problems(settings)
    pn_problem = pn_format_problem(settings.internal_pn_format)
    if pn_problem is not None:
        problems.append(pn_problem)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    database_problem = _database_path_problem(target, settings)
    if database_problem is not None:
        raise HTTPException(status_code=400, detail=database_problem)
    if Workspace.is_workspace(target):
        raise HTTPException(status_code=409, detail=f"Ordner enthält bereits eine PartForge-Bibliothek: {target}")
    if settings.db.kind == "sqlite" and core.is_network_path(target):
        raise HTTPException(
            status_code=400,
            detail=f"Der Ordner „{target}“ liegt auf einem Netzlaufwerk. SQLite-Bibliotheken werden dort nicht "
            "unterstützt (der für Altium nötige WAL-Modus funktioniert auf Netzlaufwerken nicht). Bitte einen Ordner "
            "auf einem lokalen Laufwerk wählen oder für die gemeinsame Nutzung PostgreSQL einstellen.",
        )


class DbLibNameUse(BaseModel):
    """A DbLib file PartForge knows – installed in Altium (last check) or of another PartForge library."""

    file_name: str = Field(description="Dateiname, z. B. PartForge.DbLib")
    path: str = Field(description="Vollständiger Pfad der DbLib-Datei")
    installed: bool | None = Field(
        default=None, description="true = in Altium installiert (letzte Prüfung), null = unbekannt (andere Bibliothek)")
    library: str | None = Field(default=None, description="Bibliotheksordner, falls PartForge ihn kennt")


class WorkspaceDefaultsOut(BaseModel):
    """Suggestion for „Neue Bibliothek anlegen“: neutral folder in the user's documents, a name whose folder
    does not exist yet and a DbLib file name no other known DbLib uses."""

    parent: str = Field(description="Vorgeschlagener übergeordneter Ordner (<Dokumente>\\PartForge)")
    name: str = Field(description="Name der Bibliothek (Ordner gibt es noch nicht)")
    path: str = Field(description="parent\\name – vollständiger Pfad des neuen Bibliotheksordners")
    dblib_file: str = Field(description="Vorgeschlagener DbLib-Dateiname (folgt dem Namen, eindeutig)")
    dblib_taken: list[DbLibNameUse] = Field(
        default_factory=list, description="Bekannte DbLib-Dateien (installiert oder anderer Bibliotheken) – ein "
                                          "gleicher Dateiname kollidiert in Altium")


_FOLDER_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _folder_name(name: str) -> str:
    text = _FOLDER_UNSAFE.sub(" ", name or "").strip().rstrip(".")
    text = re.sub(r"\s+", " ", text)
    if not text or text.split(".")[0].upper() in _RESERVED_NAMES:
        return DEFAULT_LIBRARY_NAME
    return text[:80]


def known_dblibs(exclude: Path | None = None) -> list[DbLibNameUse]:
    """DbLib files PartForge knows: installed in Altium (cached install checks) and those of the recently
    used libraries – ``exclude`` (a library folder) left out."""
    from ..altium import dblib as dblib_mod

    found: dict[str, DbLibNameUse] = {}

    def add(path: str, installed: bool | None, library: str | None) -> None:
        if not path:
            return
        if exclude is not None and same_folder(Path(path).parent, exclude):
            return
        key = os.path.normcase(os.path.abspath(path))
        known = found.get(key)
        if known is None:
            found[key] = DbLibNameUse(file_name=Path(path).name, path=path, installed=installed, library=library)
        else:
            known.installed = True if (installed or known.installed) else known.installed
            known.library = known.library or library

    try:
        states = dblib_mod.cached_install_states()
    except Exception:  # noqa: BLE001 - only a hint
        states = []
    for state in states:
        for entry in state.same_name:
            add(entry.path, True, None)
        if state.installed:
            add(state.path, True, None)
    for recent in load_settings().recent_workspaces:
        try:
            if not Workspace.is_workspace(recent):
                continue
            settings = WorkspaceSettings.model_validate_json((Path(recent) / WORKSPACE_FILE).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - unreadable library: skip
            continue
        add(str(Path(recent) / settings.dblib_file), None, str(Path(recent)))
    return sorted(found.values(), key=lambda u: (u.file_name.casefold(), u.path.casefold()))


def dblib_name_warnings(ws: Workspace) -> list[str]:
    """German warnings when another known DbLib has the file name of ``ws``'s DbLib (Altium resolves placed
    parts by the file name only – the first installed one wins)."""
    name = ws.dblib_path.name.casefold()
    clashes = [u for u in known_dblibs(exclude=ws.root) if u.file_name.casefold() == name]
    if not clashes:
        return []
    installed = [u for u in clashes if u.installed]
    where = ", ".join(u.path for u in (installed or clashes)[:2])
    state = "ist in Altium bereits installiert" if installed else "gibt es schon in einer anderen Bibliothek"
    return [f"Eine DbLib „{ws.dblib_path.name}“ {state} ({where}). Altium findet Bauteile nur über den Dateinamen der "
            "DbLib – sind beide installiert, gewinnt die zuerst installierte. Bitte für diese Bibliothek einen anderen "
            "DbLib-Namen wählen (Einstellungen › Bibliothek) oder nur eine der beiden installieren."]


@router.get("/workspace/defaults", response_model=WorkspaceDefaultsOut)
def workspace_defaults(name: str | None = Query(default=None, description="Gewünschter Name der Bibliothek")
                       ) -> WorkspaceDefaultsOut:
    """Neutral suggestion for a new library: ``<Dokumente>\\PartForge\\<Name>`` (a folder that does not exist yet)
    and a DbLib file name that follows the name and collides with no known DbLib (installed in Altium or of
    another PartForge library – listed in ``dblib_taken``)."""
    parent = default_library_parent()
    base = _folder_name(name or DEFAULT_LIBRARY_NAME)
    chosen = base
    for n in range(2, 1000):
        candidate = parent / chosen
        if not candidate.exists() or (candidate.is_dir() and not any(candidate.iterdir())):
            break
        chosen = f"{base} {n}"
    taken = known_dblibs()
    names = {u.file_name.casefold() for u in taken}
    stem = chosen
    dblib_file = f"{stem}.DbLib"
    n = 2
    while dblib_file.casefold() in names:
        dblib_file = f"{stem}-{n}.DbLib"
        n += 1
    return WorkspaceDefaultsOut(parent=str(parent), name=chosen, path=str(parent / chosen), dblib_file=dblib_file,
                                dblib_taken=taken)


@router.post("/workspace/create")
def create_workspace(body: WorkspaceCreateIn) -> dict:
    """Create and open a library folder.

    Response: the workspace info plus ``examples`` (counts of the seeded example parts,
    symbols and footprints, or ``None``), ``examples_error`` (German message if seeding
    failed – the library itself is usable) and ``job`` (snapshot of "Bibliotheken
    schreiben", or ``None`` without examples or with ``write_libraries=False``).

    Refused before anything is written: relative target, folder/file names outside the
    library (400), an existing library (409), SQLite on a network drive (400). If the new
    library cannot be opened, the folders and files this call created are removed again.
    Creating, opening and seeding happen under :func:`_library_switch`, so no other
    library can be opened in between.
    """
    target = Path(body.path.strip()) if body.path.strip() else None
    if target is None or not target.is_absolute():
        raise HTTPException(
            status_code=400,
            detail="Bitte den vollständigen Pfad des Bibliotheksordners angeben (z. B. C:\\Bibliotheken\\Meine Bibliothek).",
        )
    settings = body.settings.model_copy(deep=True) if body.settings is not None else WorkspaceSettings()
    _check_new_library(target, settings)
    examples: dict[str, int] | None = None
    examples_error: str | None = None
    with _library_switch():
        created = _NewPaths.before(target, settings)
        try:
            ws = Workspace.create(target, name=body.name, settings=settings)
        except OSError as exc:  # invalid drive, no permission, a file in the way, created concurrently …
            created.files = [f for f in created.files if f.name != WORKSPACE_FILE]  # never another process's library
            created.remove()
            if Workspace.is_workspace(target):
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            raise HTTPException(
                status_code=400,
                detail=f"Der Bibliotheksordner „{target}“ kann nicht angelegt werden: {exc.strerror or exc}. "
                "Bitte einen anderen Ordner wählen.",
            ) from exc
        try:
            previous = _open_locked(ws)
        except BaseException:
            unlock_library(ws.root)
            created.remove()
            raise
        if body.with_examples:
            from ..db import seed_examples

            try:
                examples = seed_examples(ws)
            except Exception as exc:  # noqa: BLE001 - the library is created and open; report, do not fail
                log.exception("Beispielinhalte für %s konnten nicht angelegt werden", ws.root)
                examples_error = f"Die Beispielinhalte konnten nicht angelegt werden: {exc}"
    for note in dblib_name_warnings(ws):  # F10: placed parts find a DbLib by its file name only
        if note not in ws.warnings:
            ws.warnings.append(note)
    info = _announce_opened(ws, previous)
    info["examples"] = examples
    info["examples_error"] = examples_error
    info["job"] = start_library_sync(ws).snapshot() if examples is not None and body.write_libraries else None
    return info


@router.put("/workspace/settings")
def update_workspace_settings(settings: WorkspaceSettings) -> dict:
    ws = current_or_none()
    if ws is None:
        raise HTTPException(status_code=409, detail="Es ist keine Bibliothek geöffnet.")
    problems = settings_path_problems(settings)
    pn_problem = pn_format_problem(settings.internal_pn_format)
    if pn_problem is not None:
        problems.append(pn_problem)
    if problems:
        raise HTTPException(status_code=400, detail=" ".join(problems))
    ws.settings = settings
    ws.pn_format_warning = None  # the format is valid now
    ws.save()
    return ws.info()


@router.post("/workspace/close")
def close_workspace() -> dict:
    from .. import events
    from ..db import close_database

    with _library_switch():
        previous = current_or_none()
        close_database()
        set_current(None)
        if previous is not None:
            unlock_library(previous.root)
    events.emit(events.WORKSPACE_CLOSED)
    return {"ok": True}


# --------------------------------------------------------------------------- jobs
# Snapshot fields and the brief form of large results: partforge.jobs (module docstring, brief_result).

_BRIEF_DESCRIPTION = (
    "Kurzform: Ergebnisse über 8 KB (kompaktes JSON) nur mit skalaren Feldern (Texte bis 200 Zeichen), "
    "„<name>_count“ je Liste/Objekt, den ersten 5 Einträgen von errors/warnings/missing und "
    "„result_truncated“: true – das volle Ergebnis liefert GET /api/jobs/{id}"
)


@router.get("/jobs")
def list_jobs(
    kind: str | None = None,
    brief: bool = Query(default=False, description=_BRIEF_DESCRIPTION),
) -> list[dict]:
    """All jobs (newest first, without log). ``brief=true``: a result whose compact JSON encoding (UTF-8)
    is larger than 8 KB is replaced by its brief form (:func:`partforge.jobs.brief_result`): every scalar
    top-level field (numbers, booleans, ``null``; strings up to 200 characters, longer ones cut to 200
    ending with "…"), ``<name>_count`` (length) for every list/dict field, the first 5 entries of
    ``errors``, ``warnings`` and ``missing``, and ``"result_truncated": true``. Smaller results and the
    rest of the snapshot are unchanged; ``GET /jobs/{id}`` always has the full result."""
    return [j.snapshot(with_log=False, brief=brief) for j in jobs.list(kind)]


@router.get("/jobs/events")
async def all_job_events(
    request: Request,
    brief: bool = Query(default=False, description=_BRIEF_DESCRIPTION),
) -> StreamingResponse:
    """Server-sent events for ALL jobs: one ``data:`` line ``{"job": snapshot, "new_log": [...]}`` per
    changed job with the snapshot (without log) plus only the log lines added since the previous event
    of that job. ``brief=true``: results larger than 8 KB in their brief form, exactly as
    ``GET /jobs?brief=true`` (:func:`partforge.jobs.brief_result`)."""

    async def stream():
        seen: dict[str, tuple[int, int]] = {}  # job id -> (version, log length)
        yield ": verbunden\n\n"
        idle = 0
        while not await request.is_disconnected():
            changed = False
            for job in jobs.list():
                version, log_len = seen.get(job.id, (-1, 0))
                if job.version == version:
                    continue
                snap = job.snapshot(with_log=False, brief=brief)
                new_log = job.log[log_len:] if len(job.log) >= log_len else list(job.log)
                seen[job.id] = (job.version, len(job.log))
                payload = {"job": snap, "new_log": new_log}
                yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
                changed = True
            idle = 0 if changed else idle + 1
            if idle >= 75:  # keep-alive comment every ~15 s
                idle = 0
                yield ": ping\n\n"
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    """One job with log and the full result (never shortened)."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return job.snapshot()


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """Ask a job to stop (at its next check; ``cancel_reason`` stays ``null`` = by the user)."""
    return {"cancelled": jobs.cancel(job_id)}


@router.get("/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    """Server-sent events: one `data:` line with the job snapshot (with log and the full result) whenever
    it changes; the stream ends after the final snapshot."""
    if not jobs.get(job_id):
        raise HTTPException(status_code=404, detail="Job nicht gefunden")

    async def stream():
        last = -1
        while True:
            if await request.is_disconnected():
                break
            job = jobs.get(job_id)
            if job is None:
                break
            if job.version != last:
                last = job.version
                yield f"data: {json.dumps(job.snapshot(), ensure_ascii=False, default=str)}\n\n"
                if job.status in ("done", "failed", "cancelled"):
                    break
            await asyncio.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
