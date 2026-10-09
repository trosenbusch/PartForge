"""API routes: Altium integration – DbLib, ODBC test and the bridge to a running Altium.

``GET`` endpoints never start an Altium script (the install state is cached); everything
that talks to Altium runs as a job and returns ``{"job": snapshot}``::

    GET  /altium/status            backends, Altium running/version, DbLib status, ODBC driver installed?, refresh status
    GET  /altium/dblib             DbLib status (cached Altium install state)
    GET  /altium/dblib/preview     generated DbLib text and the current file, passwords masked
                                   (?raw=true: download – the exact bytes, cp1252/CRLF, of ?which=target (what
                                   PartForge writes now, default) or ?which=file (the file on disk), passwords
                                   included; Content-Disposition attachment with the DbLib's file name)
    POST /altium/dblib/regenerate  write the DbLib now (then refresh Altium automatically); answers the stable
                                   reason id (missing|outdated|wrong_database|settings_changed|forced|up_to_date)
                                   and a German reason_text
    POST /altium/install-state     job: ask Altium whether the DbLib is installed (and same-name DbLibs)
    POST /altium/odbc-test         job: read the database exactly like Altium (pyodbc, same driver)
    POST /altium/install           job: install the DbLib in Altium (optionally replacing an old copy)
    POST /altium/uninstall         job: release the database in Altium and uninstall the DbLib (then: does Altium still
                                   hold the SQLite database open? -> result database_released / database_holders)
    POST /altium/refresh           job: make Altium re-read the database ("In Altium aktualisieren")
    POST /altium/verify            job: resolve parts in Altium (symbol, footprints in their libraries, pins,
                                   Comment, Description and parameter values against the database row) – one
                                   Altium script run per 50 parts (resolve_db_components);
                                   sample "spread" (default) or "first"; the result is stored per library
    GET  /altium/verify/last       the last completed check of the open library (null if none)
    POST /altium/open              job: open a library file (default: the DbLib) in Altium

Every job ends with a German outcome sentence in ``job.message`` (``ctx.progress(1.0, …)``).

Same-name DbLibs: placed parts find their DbLib by file name only. "Ersetzen" uninstalls
another installed DbLib of the same name only when it is an old copy of this library
(same database) or a dead entry (file gone) – never the DbLib of another library.

Errors: Altium not running / script hangs / no writer -> 503 with German hint, bridge busy
-> 409. The router's lifespan starts the DbLib auto-writer and the refresh service.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..altium import libwriter, refresh, verify
from ..altium.bridge.core import (
    RESOLVE_BATCH_SIZE,
    AltiumBridge,
    AltiumNotRunning,
    BridgeBusyError,
    BridgeCommandError,
    BridgeError,
    BridgeWedgedError,
    DbComponentResolution,
)
from ..altium.dblib import (
    DbLibError,
    DbLibStatus,
    RegenerateReason,
    build_dblib,
    classify_install_state,
    dblib_bytes,
    duplicates_message,
    ensure_dblib,
    mask_secrets,
    remember_install_state,
    status_model,
)
from ..altium.models import BackendStatus
from ..altium.odbc import OdbcDriverStatus, driver_status
from ..altium.refresh import AltiumRefreshService, RefreshStatus, note_refresh_result
from ..altium.verify import FootprintCheck, SampleMode, VerifiedPart, VerifyRun, VerifySummary
from ..config import load_settings
from ..domain.text import plural
from ..jobs import JobContext, LibraryChanged, jobs, library_hold
from ..workspace import Workspace, WorkspaceNotOpen, current_or_none
from .deps import require_workspace
from .routes_categories import db_errors

log = logging.getLogger(__name__)

_X2_MISSING = "Altium Designer (X2.EXE) wurde nicht gefunden – Pfad unter Einstellungen › Allgemein › Altium Designer eintragen."
_NOT_RUNNING = "Altium Designer ist nicht gestartet. Bitte Altium starten und erneut versuchen."
OPENABLE_SUFFIXES = (".dblib", ".schlib", ".pcblib", ".intlib", ".dblink")
_STATUS_LEVEL: dict[str, Literal["info", "warn", "error", "success"]] = {
    "ok": "success", "warning": "warn", "error": "error",
}
_FOOTPRINT_REF = re.compile(r"^Footprint Ref(?: ([1-9]\d*))?$", re.IGNORECASE)


@asynccontextmanager
async def _lifespan(_app: Any) -> AsyncIterator[None]:
    refresh.start_services()
    try:
        yield
    finally:
        refresh.stop_services()


router = APIRouter(tags=["altium"], lifespan=_lifespan)


# --------------------------------------------------------------------------- dependencies / errors


def get_bridge() -> AltiumBridge:
    """Bridge configured from the settings (overridden in tests)."""
    return refresh.default_bridge()


def get_refresh_service() -> AltiumRefreshService:
    return refresh.get_refresh_service()


@contextmanager
def altium_errors() -> Iterator[None]:
    """Map Altium/bridge/DbLib errors to HTTP errors with German messages."""
    try:
        with db_errors():
            yield
    except HTTPException:
        raise
    except BridgeBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (AltiumNotRunning, BridgeWedgedError, libwriter.WriterUnavailable) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BridgeCommandError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BridgeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except WorkspaceNotOpen as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DbLibError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_altium(bridge: AltiumBridge) -> None:
    """Fail fast (503) before submitting a job that needs a running Altium."""
    if not bridge.x2_path:
        raise HTTPException(status_code=503, detail=_X2_MISSING)
    if not bridge.is_running():
        raise HTTPException(status_code=503, detail=_NOT_RUNNING)


def _job_out(job: Any) -> AltiumJobOut:
    return AltiumJobOut(job=job.snapshot())


# --------------------------------------------------------------------------- models


class AltiumJobOut(BaseModel):
    """``{"job": JobSnapshot}`` – the result arrives in ``job.result`` (poll /api/jobs/{id} or SSE)."""

    job: dict[str, Any] = Field(description="JobSnapshot (partforge.jobs.Job.snapshot())")


class AltiumStatusOut(BaseModel):
    backends: list[BackendStatus]
    altium_running: bool
    altium_exe: str | None = None
    version: str | None = None
    bridge_wedged: dict[str, Any] | None = None
    workspace_open: bool = False
    dblib: DbLibStatus | None = None
    odbc: OdbcDriverStatus | None = Field(
        default=None, description="ODBC-Treiber der DbLib installiert? (nur mit offener Bibliothek; ohne Verbindungstest)"
    )
    refresh: RefreshStatus


class DbLibPreviewOut(BaseModel):
    path: str
    file_name: str
    text: str  # what PartForge writes (Altium's UI state of the current file kept; passwords masked)
    current: str | None = None  # the file on disk (passwords masked)
    up_to_date: bool = False
    warnings: list[str] = Field(default_factory=list)


class DbLibRegenerateOut(BaseModel):
    written: bool
    reason: RegenerateReason = Field(
        description="missing = fehlte · outdated = veraltet (Kategorien/Felder, auch Format) · wrong_database = verwies "
                    "auf eine andere Datenbank · settings_changed = Datenbankeinstellungen geändert · forced = nur "
                    "neu geschrieben (inhaltlich gleich) · up_to_date = aktuell, nichts geschrieben"
    )
    reason_text: str = Field(description="Deutsche Erklärung des Grundes")
    path: str
    warnings: list[str] = Field(default_factory=list)
    status: DbLibStatus


class OdbcTestIn(BaseModel):
    max_rows: int | None = Field(default=None, ge=1, description="Höchstens so viele Zeilen je Tabelle lesen")


class InstallIn(BaseModel):
    replace_others: bool = Field(
        default=False,
        description="Eine alte Installation dieser Bibliothek mit demselben Dateinamen (alter Ordner, gleiche "
                    "Datenbank, oder Datei nicht mehr vorhanden) deinstallieren",
    )


class RefreshIn(BaseModel):
    rebuild_index: bool | None = Field(
        default=None, description="Bauteilindex neu aufbauen (Standard: wenn seit der letzten Aktualisierung Teile neu sind)"
    )


class VerifyIn(BaseModel):
    limit: int | None = Field(default=20, ge=1, le=100_000, description="Größe der Stichprobe (Höchstzahl geprüfter Bauteile)")
    all: bool = Field(default=False, description="Alle Bauteile prüfen (ignoriert limit und sample)")
    tables: list[str] | None = Field(default=None, description="Nur diese Kategorien (Tabellennamen)")
    part_numbers: list[str] | None = Field(default=None, description="Genau diese Bauteile (ignoriert die übrigen Angaben)")
    sample: SampleMode = Field(
        default="spread",
        description="Stichprobe: spread = über alle Kategorien verteilt (anteilig, mindestens ein Bauteil je Kategorie, "
                    "deterministisch), first = die ersten Bauteile in Kategorie-Reihenfolge",
    )


class OpenIn(BaseModel):
    path: str | None = Field(default=None, description="Bibliotheksdatei (absolut oder relativ zur Bibliothek); Standard: die DbLib")


# --------------------------------------------------------------------------- status & DbLib


@router.get("/altium/status", response_model=AltiumStatusOut)
def altium_status(
    bridge: AltiumBridge = Depends(get_bridge),
    service: AltiumRefreshService = Depends(get_refresh_service),
) -> AltiumStatusOut:
    """Cheap overview (no Altium script): writer backends, Altium process, DbLib and refresh state."""
    settings = load_settings()
    backends = libwriter.backend_status(settings)
    altium = next((b for b in backends if b.name == "altium"), None)
    ws = current_or_none()
    dblib: DbLibStatus | None = None
    odbc: OdbcDriverStatus | None = None
    if ws is not None:
        with altium_errors():
            dblib = status_model(ws)
        odbc = driver_status(ws)
    return AltiumStatusOut(
        backends=backends,
        altium_running=bridge.is_running() if bridge.x2_path else False,
        altium_exe=bridge.x2_path,
        version=altium.version if altium is not None else None,
        bridge_wedged=bridge.last_wedge,
        workspace_open=ws is not None,
        dblib=dblib,
        odbc=odbc,
        refresh=service.status(),
    )


@router.get("/altium/dblib", response_model=DbLibStatus)
def get_dblib_status(ws: Workspace = Depends(require_workspace)) -> DbLibStatus:
    with altium_errors():
        return status_model(ws)


#: Content type of the DbLib download (an INI text file in Windows-1252).
DBLIB_MEDIA_TYPE = "text/plain; charset=windows-1252"


def _attachment(file_name: str) -> str:
    """``Content-Disposition`` of a download (ASCII fallback plus RFC 5987 UTF-8 name)."""
    from urllib.parse import quote

    fallback = "".join(c if 32 <= ord(c) < 127 and c not in '"\\' else "_" for c in file_name) or "PartForge.DbLib"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(file_name, safe='')}"


@router.get(
    "/altium/dblib/preview",
    response_model=DbLibPreviewOut,
    responses={200: {"content": {"text/plain": {}}, "description": "Mit raw=true: die DbLib als Datei (Bytes)"}},
)
def preview_dblib(
    raw: bool = Query(False, description="Die DbLib als Datei herunterladen (exakte Bytes, cp1252/CRLF)"),
    which: Literal["target", "file"] = Query(
        "target", description="Nur mit raw=true: target = wie PartForge sie jetzt schreibt, file = die Datei auf der Platte"
    ),
    ws: Workspace = Depends(require_workspace),
) -> Response | DbLibPreviewOut:
    """The DbLib as PartForge would write it now and the current file, passwords of the
    connection string masked.

    ``raw=true`` downloads the exact bytes instead – ``which=target`` (default) what PartForge
    writes now (Altium's UI state of the current file kept), ``which=file`` the file on disk
    (404 if it does not exist yet) – unmasked, because Altium needs the password in the file;
    ``Content-Disposition: attachment`` with the DbLib's file name (``PartForge.DbLib``)."""
    if raw:
        with altium_errors():
            if which == "file" and not ws.dblib_path.is_file():
                raise HTTPException(
                    status_code=404,
                    detail=f"Die DbLib „{ws.settings.dblib_file}“ existiert noch nicht – „DbLib neu erzeugen“ legt sie an.",
                )
            data = dblib_bytes(ws, which)
        return Response(content=data, media_type=DBLIB_MEDIA_TYPE, headers={
            "Content-Disposition": _attachment(ws.settings.dblib_file),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        })
    with altium_errors():
        build = build_dblib(ws)
        status = status_model(ws)
    text = mask_secrets(build.text)
    current: str | None = None
    if ws.dblib_path.is_file():
        try:
            current = mask_secrets(ws.dblib_path.read_bytes().decode("cp1252", errors="replace"))
        except OSError as exc:
            log.warning("DbLib nicht lesbar: %s", exc)
    return DbLibPreviewOut(
        path=str(ws.dblib_path),
        file_name=ws.settings.dblib_file,
        text=text,
        current=current,
        up_to_date=status.up_to_date,
        warnings=build.warnings,
    )


@router.post("/altium/dblib/regenerate", response_model=DbLibRegenerateOut)
def regenerate_dblib(
    ws: Workspace = Depends(require_workspace),
    service: AltiumRefreshService = Depends(get_refresh_service),
) -> DbLibRegenerateOut:
    """Write the DbLib now; a running Altium re-reads it automatically (if enabled and installed).

    ``reason`` is the stable id of why it was (re)written – the real cause also when the file is
    forced (``forced`` only when nothing but Altium's UI state or the order differed) – and
    ``reason_text`` its German explanation."""
    with altium_errors():
        result = ensure_dblib(ws, force=True)
        if result.written:
            service.request(rebuild=True)
        status = status_model(ws)
    return DbLibRegenerateOut(written=result.written, reason=result.reason_id, reason_text=result.reason_text,
                              path=result.path, warnings=result.warnings, status=status)


# --------------------------------------------------------------------------- ODBC test


def _odbc_job(ctx: JobContext, ws: Workspace, max_rows: int | None) -> dict[str, Any]:
    from ..altium import odbc

    return odbc.test_odbc(ws, ctx=ctx, max_rows=max_rows)


@router.post("/altium/odbc-test", response_model=AltiumJobOut)
def odbc_test(body: OdbcTestIn | None = None, ws: Workspace = Depends(require_workspace)) -> AltiumJobOut:
    """Job: connect with the 64-bit ODBC driver exactly like Altium and read every enabled table."""
    job = jobs.submit("altium.odbc_test", "ODBC-Verbindung testen", _odbc_job, ws, (body or OdbcTestIn()).max_rows)
    return _job_out(job)


# --------------------------------------------------------------------------- install state / install / uninstall


def _install_state_job(ctx: JobContext, bridge: AltiumBridge, ws: Workspace) -> dict[str, Any]:
    ctx.progress(0.1, "Installierte Bibliotheken in Altium werden gelesen …")
    state = bridge.install_state(ws.dblib_path)
    if state.duplicates:
        ctx.progress(0.6, "DbLibs mit demselben Dateinamen werden geprüft …")
    state, duplicates = classify_install_state(ws, state)
    remember_install_state(state, dblib=ws.dblib_path)
    if state.duplicates:
        message = "Achtung: " + duplicates_message(state, duplicates)
        ctx.log(message, "warn")
    elif state.installed:
        message = "Die DbLib ist in Altium installiert."
        ctx.log(message, "success")
    else:
        message = "Die DbLib ist in Altium nicht installiert."
        ctx.log(message)
    ctx.progress(1.0, message)
    return {"message": message, "state": state.model_dump(mode="json"),
            "duplicates": [d.model_dump(mode="json") for d in duplicates]}


@router.post("/altium/install-state", response_model=AltiumJobOut)
def check_install_state(
    ws: Workspace = Depends(require_workspace), bridge: AltiumBridge = Depends(get_bridge)
) -> AltiumJobOut:
    """Job: ask the running Altium whether the DbLib is installed (result is cached for the status)."""
    _require_altium(bridge)
    return _job_out(jobs.submit("altium.install_state", "Altium-Installationsstatus prüfen", _install_state_job, bridge, ws))


def _install_job(ctx: JobContext, bridge: AltiumBridge, ws: Workspace, replace_others: bool) -> dict[str, Any]:
    ctx.progress(0.05, "DbLib wird geprüft …")
    written = ensure_dblib(ws)
    if written.written:
        ctx.log(f"DbLib neu geschrieben: {written.reason_text}")
    ctx.progress(0.2, "Installierte Bibliotheken in Altium werden gelesen …")
    state, duplicates = classify_install_state(ws, bridge.install_state(ws.dblib_path))
    remember_install_state(state, dblib=ws.dblib_path)
    removed: list[str] = []
    if duplicates:
        blocking = [d for d in duplicates if not d.replaceable]
        if blocking or not replace_others:  # never uninstall the DbLib of another library
            raise DbLibError(duplicates_message(state, duplicates))
        ctx.progress(0.4, "Alte Installation mit demselben Dateinamen wird entfernt …")
        bridge.refresh_dblib(state.file_name, rebuild_index=False)  # release their databases first
        for duplicate in duplicates:
            bridge.uninstall_library(Path(duplicate.path))
            removed.append(duplicate.path)
            ctx.log(f"Alte Installation deinstalliert: {duplicate.path}", "warn")
    if not state.installed:
        ctx.progress(0.6, "DbLib wird in Altium installiert …")
        bridge.install_library(ws.dblib_path)
    else:
        ctx.log("Die DbLib war bereits installiert.")
        if written.written:  # Altium still holds the old file: re-read it including the component index
            ctx.progress(0.6, "Altium liest die geänderte DbLib neu ein …")
            note_refresh_result(ws.dblib_path, bridge.refresh_dblib(state.file_name, rebuild_index=True))
    ctx.progress(0.85, "Installation wird geprüft …")
    state, duplicates = classify_install_state(ws, bridge.install_state(ws.dblib_path))
    remember_install_state(state, dblib=ws.dblib_path)
    if not state.installed:
        raise BridgeCommandError("install_library", "Altium hat die DbLib nicht installiert.")
    if duplicates:
        ctx.log(duplicates_message(state, duplicates), "warn")
    message = "Die DbLib ist in Altium installiert."
    if removed:
        message += " " + plural(len(removed), "alte Installation", "alte Installationen") + " ersetzt."
    ctx.log(message, "success")
    ctx.progress(1.0, message)
    return {"message": message, "removed": removed, "dblib_written": written.written,
            "state": state.model_dump(mode="json")}


@router.post("/altium/install", response_model=AltiumJobOut)
def install_dblib(
    body: InstallIn | None = None,
    ws: Workspace = Depends(require_workspace),
    bridge: AltiumBridge = Depends(get_bridge),
) -> AltiumJobOut:
    """Job: install the DbLib in Altium (explicit user action)."""
    _require_altium(bridge)
    replace = (body or InstallIn()).replace_others
    return _job_out(jobs.submit("altium.install", "DbLib in Altium installieren", _install_job, bridge, ws, replace))


def _uninstall_job(ctx: JobContext, bridge: AltiumBridge, ws: Workspace) -> dict[str, Any]:
    ctx.progress(0.1, "Installierte Bibliotheken in Altium werden gelesen …")
    state = bridge.install_state(ws.dblib_path)
    if not state.installed:
        remember_install_state(state, dblib=ws.dblib_path)
        message = "Die DbLib war in Altium nicht installiert – nichts zu tun."
        ctx.log(message)
        ctx.progress(1.0, message)
        return {"message": message, "state": state.model_dump(mode="json")}
    ctx.progress(0.4, "Altium gibt die Datenbank frei …")
    # UninstallLibrary alone leaves Altium's hidden DbLib document (and the database connection) open
    released = bridge.refresh_dblib(state.file_name, rebuild_index=False)
    for path in released.skipped:
        ctx.log(f"Die DbLib ist in Altium noch geöffnet ({path}) – die Datenbank bleibt bis zum Schließen belegt.", "warn")
    ctx.progress(0.7, "DbLib wird deinstalliert …")
    for entry in state.same_name:
        if entry.same_file:
            bridge.uninstall_library(Path(entry.path))
    state = bridge.install_state(ws.dblib_path)
    remember_install_state(state, dblib=ws.dblib_path)
    if state.installed:
        raise BridgeCommandError("uninstall_library", "Altium hat die DbLib nicht deinstalliert.")
    message = "Die DbLib wurde in Altium deinstalliert."
    ctx.log(message, "success")
    ctx.progress(0.9, "Freigabe der Datenbank wird geprüft …")
    released, holders, hint = _database_release(ws)
    if hint:
        message = f"{message} {hint}"
        ctx.log(hint, "warn")
    ctx.progress(1.0, message)
    # database_hint: what to do before moving the folder (None = nothing). outcome "partial" while a program still
    # holds the database: every job list shows "Fertig mit Hinweisen" with the message (E2EREG-2), also after a reload
    return {"message": message, "state": state.model_dump(mode="json"), "database_released": released,
            "database_holders": holders, "database_hint": hint,
            "outcome": "partial" if released is False else "ok"}


def _database_release(ws: Workspace) -> tuple[bool | None, list[dict[str, Any]], str | None]:
    """After the uninstall: does a program (Altium) still hold the SQLite database open? ``(released, holders, German
    hint)`` – Altium usually lets go about a minute later, sometimes only after a restart (review finding F3); until
    then the library folder cannot be moved or renamed. ``released`` is None when it cannot be determined (or the
    library uses PostgreSQL). The hint names what to do first and keeps the outcome sentence of the job short enough
    for a toast (≤ 200 characters, E2EREG-2)."""
    if ws.settings.db.kind != "sqlite":
        return None, [], None
    from ..altium.holders import database_files, file_holders

    holders = file_holders(database_files(ws.sqlite_path))
    if holders is None:
        return None, [], None
    if not holders:
        return True, [], None
    listed = [{"pid": h.pid, "name": h.name} for h in holders]
    altium = [h for h in holders if "altium" in h.name.casefold() or h.name.casefold().startswith("x2")]
    if altium:
        return False, listed, (
            "Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen (sonst Altium neu "
            "starten)."
        )
    names = sorted({h.name for h in holders})
    holds = "hält das Programm" if len(names) == 1 else "halten diese Programme"
    return False, listed, (
        f"Ordner erst nach dem Schließen von {', '.join(names)} verschiebbar – bis dahin {holds} die Datenbank offen."
    )


@router.post("/altium/uninstall", response_model=AltiumJobOut)
def uninstall_dblib(ws: Workspace = Depends(require_workspace), bridge: AltiumBridge = Depends(get_bridge)) -> AltiumJobOut:
    """Job: release the database in Altium and uninstall the DbLib (explicit user action)."""
    _require_altium(bridge)
    return _job_out(jobs.submit("altium.uninstall", "DbLib in Altium deinstallieren", _uninstall_job, bridge, ws))


# --------------------------------------------------------------------------- refresh


@router.post("/altium/refresh", response_model=AltiumJobOut)
def refresh_altium(
    body: RefreshIn | None = None,
    ws: Workspace = Depends(require_workspace),
    service: AltiumRefreshService = Depends(get_refresh_service),
) -> AltiumJobOut:
    """Job: make the running Altium re-read the database (manual "In Altium aktualisieren")."""
    with altium_errors():
        job = service.refresh_now((body or RefreshIn()).rebuild_index)
    return _job_out(job)


# --------------------------------------------------------------------------- verify


def _select_parts(body: VerifyIn) -> verify.Selection:
    """Parts to verify (:func:`partforge.altium.verify.select_parts`)."""
    return verify.select_parts(part_numbers=body.part_numbers, tables=body.tables, all_parts=body.all,
                               limit=body.limit, sample=body.sample)


def _expected_pins(library_ref: str | None, cache: dict[str, int | None]) -> int | None:
    if not library_ref:
        return None
    key = library_ref.casefold()
    if key not in cache:
        from ..db import registry

        record = registry.get_symbol(library_ref)
        cache[key] = record.pin_count if record is not None and record.pin_count else None
    return cache[key]


def _library_reader(ws: Workspace) -> libwriter.LibraryWriter | None:
    """Reader for the component names of PcbLib files (Rust writer), None if not installed."""
    exe = load_settings().resolved_rust_writer()
    return libwriter.RustLibraryWriter(exe, workspace=ws) if exe else None


class _LibraryContents:
    """Component names of the footprint libraries of one verification (each file read once):
    the Rust reader if available, else (or if it cannot read the file) Altium itself."""

    def __init__(self, bridge: AltiumBridge, reader: libwriter.LibraryWriter | None):
        self.bridge = bridge
        self.reader = reader
        self._cache: dict[str, tuple[set[str] | None, str | None]] = {}

    def names(self, library: Path) -> tuple[set[str] | None, str | None]:
        """``(casefolded component names, None)`` or ``(None, German reason)``."""
        key = os.path.normcase(os.path.abspath(library))
        if key not in self._cache:
            self._cache[key] = self._load(library)
        return self._cache[key]

    def _load(self, library: Path) -> tuple[set[str] | None, str | None]:
        reader_error: str | None = None
        if self.reader is not None:
            try:
                names = libwriter.cached_component_names(self.reader, library)
            except Exception as exc:  # noqa: BLE001 - unreadable for the reader: ask Altium
                reader_error = str(exc)
                log.info("Footprint-Bibliothek %s mit dem Rust-Leser nicht lesbar: %s", library, exc)
            else:
                if names is not None:
                    return {n.casefold() for n in names}, None
        try:
            listed = self.bridge.list_components(library)
        except BridgeCommandError as exc:
            return None, reader_error or exc.detail
        return {n.casefold() for n in listed}, None


def _row_value(row: Mapping[str, Any], column: str) -> str:
    folded = column.casefold()
    for key, value in row.items():
        if key.casefold() == folded:
            return str(value or "").strip()
    return ""


def _footprint_links(row: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    """``(ref column, path column, footprint)`` of every filled ``Footprint Ref`` / ``Footprint Ref n``."""
    links: list[tuple[int, str, str, str]] = []
    for column, value in row.items():
        m = _FOOTPRINT_REF.match(str(column))
        name = str(value or "").strip()
        if m is None or not name:
            continue
        number = int(m.group(1)) if m.group(1) else 1
        path_column = "Footprint Path" + (f" {m.group(1)}" if m.group(1) else "")
        links.append((number, str(column), path_column, name))
    return [(ref, path, name) for _, ref, path, name in sorted(links)]


def _check_footprints(ws: Workspace, row: Mapping[str, Any], res: DbComponentResolution,
                      contents: _LibraryContents, errors: list[str], warnings: list[str]) -> list[FootprintCheck]:
    checks: list[FootprintCheck] = []
    assigned = {f.casefold() for f in res.footprints}
    for ref_column, path_column, name in _footprint_links(row):
        stored = _row_value(row, path_column)
        check = FootprintCheck(column=ref_column, footprint=name, library=stored or None,
                               assigned=name.casefold() in assigned)
        if not check.assigned:
            errors.append(f"Footprint „{name}“ ist dem Bauteil in Altium nicht zugeordnet.")
        library = ws.abs(stored) if stored else None
        if library is None:
            errors.append(f"Für den Footprint „{name}“ ist keine Footprint-Bibliothek eingetragen ({path_column}).")
        elif not library.is_file():
            errors.append(f"Footprint-Bibliothek „{stored}“ fehlt.")
        else:
            check.library_found = True
            names, reason = contents.names(library)
            if names is None:
                warnings.append(f"Footprint-Bibliothek „{stored}“ konnte nicht gelesen werden ({reason}) – ob sie "
                                f"„{name}“ enthält, ist ungeprüft.")
            else:
                check.in_library = name.casefold() in names
                if not check.in_library:
                    errors.append(f"Footprint „{name}“ fehlt in „{stored}“.")
        checks.append(check)
    return checks


def _category(table: str, cache: dict[str, Any]) -> Any:
    """Category definition of ``table`` for the parameter comparison (once per verification), None if unknown."""
    key = table.casefold()
    if key not in cache:
        from ..db import categories

        try:
            cache[key] = categories.get_category(table)
        except Exception as exc:  # noqa: BLE001 - deleted meanwhile: the parameters stay unchecked
            log.info("Kategorie %s für den Parametervergleich nicht lesbar: %s", table, exc)
            cache[key] = None
    return cache[key]


def _check_parameters(table: str, row: Mapping[str, Any], res: DbComponentResolution, out: VerifiedPart,
                      warnings: list[str], categories_cache: dict[str, Any]) -> None:
    """Compare the parameters and Description Altium places with the database row (E2EREG-3): every difference
    is a warning. Skipped when Altium reported no parameters at all (no record, or an older bridge script)."""
    if not res.parameters:
        return
    category = _category(table, categories_cache)
    if category is None:
        return
    comparison = verify.compare_parameters(category, row, res.parameters, res.description)
    out.parameters_checked = comparison.checked
    out.parameter_diffs = comparison.diffs
    out.extra_parameters = comparison.extra
    warnings.extend(verify.parameter_message(diff) for diff in comparison.diffs)


def _check_part(ws: Workspace, table: str, row: dict[str, Any], res: DbComponentResolution,
                pins_cache: dict[str, int | None], contents: _LibraryContents,
                categories_cache: dict[str, Any] | None = None) -> VerifiedPart:
    pn = str(row.get("Part Number") or "")
    library_ref = row.get("Library Ref") or None
    # Altium answers a key it no longer finds in the database with the symbol cached under it (after a delete,
    # until the index is rebuilt): no SchLib reference, no parameters – that is not the record (review finding F5)
    record_found = res.loaded and bool(res.symbol_ref or res.parameters)
    out = VerifiedPart(table=table, part_number=pn, status="ok", symbol_found=record_found, library_ref=library_ref,
                       lib_reference=res.lib_reference, symbol_path=res.symbol_path, pin_count=res.pin_count,
                       footprints=res.footprints, comment=res.comment, comment_visible=res.comment_visible,
                       visible_parameters=res.visible_parameters, description=res.description,
                       parameters=dict(res.parameters))
    errors: list[str] = []
    warnings: list[str] = []
    if res.loaded and not record_found:
        errors.append(
            f"Datensatz „{pn}“ in Altium nicht gefunden – Altium liefert nur ein zwischengespeichertes Symbol"
            + (f" „{res.lib_reference}“" if res.lib_reference else "")
            + " ohne Werte aus der Datenbank. „In Altium aktualisieren“ mit Bauteilindex behebt das."
        )
    elif not res.loaded:
        errors.append(f"Symbol „{library_ref or '?'}“ nicht gefunden"
                      + (f" (Bibliothek {res.symbol_path})" if res.symbol_path else " (keine Symbolbibliothek)") + ".")
    elif library_ref and res.lib_reference and res.lib_reference.casefold() != str(library_ref).casefold():
        warnings.append(f"Altium lädt das Symbol „{res.lib_reference}“ statt „{library_ref}“.")
    out.expected_pins = _expected_pins(library_ref, pins_cache)
    if record_found and out.expected_pins is not None and res.pin_count is not None and res.pin_count != out.expected_pins:
        warnings.append(f"Pinanzahl in Altium {res.pin_count}, erwartet {out.expected_pins}.")
    out.footprint_checks = _check_footprints(ws, row, res, contents, errors, warnings)
    if not out.footprint_checks:
        warnings.append("Kein Footprint eingetragen.")
    else:
        out.footprint = out.footprint_checks[0].footprint
        out.footprint_found = all(c.assigned and c.library_found and c.in_library for c in out.footprint_checks)
    if record_found:
        _check_parameters(table, row, res, out, warnings, {} if categories_cache is None else categories_cache)
    out.messages = errors + warnings
    out.status = "error" if errors else ("warning" if warnings else "ok")
    return out


def _selection_text(selection: verify.Selection) -> str:
    """German description of what a check covers (job log)."""
    parts_text = plural(len(selection.parts), "Bauteil", "Bauteile")
    categories = plural(selection.categories, "Kategorie", "Kategorien")
    if selection.scope == "part_numbers":
        return f"Geprüft werden {parts_text} (ausgewählt)."
    if selection.scope == "all":
        return f"Geprüft werden alle {parts_text} aus {categories}."
    how = "über alle Kategorien verteilt" if selection.sample == "spread" else "die ersten in Kategorie-Reihenfolge"
    return f"Stichprobe: {parts_text} aus {categories} ({how}; {plural(selection.total, 'Bauteil', 'Bauteile')} insgesamt)."


def _verify_message(results: Sequence[VerifiedPart]) -> str:
    counts = {s: sum(1 for p in results if p.status == s) for s in ("ok", "warning", "error")}
    if not results:
        return "Keine Bauteile zum Prüfen – die Auswahl ist leer."
    return (f"{plural(len(results), 'Bauteil', 'Bauteile')} in Altium geprüft: {counts['ok']} in Ordnung, "
            f"{counts['warning']} mit Hinweisen, {counts['error']} mit Fehlern.")


def _store_verify_run(ctx: JobContext, ws: Workspace, run: VerifyRun) -> None:
    """Persist the run in the library it was started for (never in another one)."""
    try:
        with library_hold(None, ws.root):  # a library switch waits for this short write
            verify.save_last(run)
    except LibraryChanged:
        ctx.log("Die Bibliothek wurde inzwischen gewechselt – das Prüfergebnis wurde nicht gespeichert.", "warn")
    except Exception as exc:  # noqa: BLE001 - the result itself is still delivered
        log.warning("Prüfergebnis nicht gespeichert: %s", exc)
        ctx.log(f"Das Prüfergebnis konnte nicht gespeichert werden ({exc}).", "warn")


def _verify_result(run: VerifyRun) -> dict[str, Any]:
    """Job result: the flat summary fields, the selection (scope, sample …) and the parts."""
    summary = run.summary
    return {
        **summary.model_dump(mode="json"),
        "scope": run.scope,
        "sample": run.sample,
        "limit": run.limit,
        "tables": run.tables,
        "started": run.started,
        "finished": run.finished,
        "parts": [p.model_dump(mode="json") for p in run.results],
    }


def _verify_job(ctx: JobContext, bridge: AltiumBridge, ws: Workspace, body: VerifyIn) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = verify.now_iso()
    ctx.progress(0.02, "DbLib wird geprüft …")
    written = ensure_dblib(ws)
    selection = _select_parts(body)
    selected, total = selection.parts, selection.total

    def finish(results: list[VerifiedPart], *, temporary: bool = False, runs: int = 0, resolve_s: float = 0.0
               ) -> dict[str, Any]:
        counts = {s: sum(1 for p in results if p.status == s) for s in ("ok", "warning", "error")}
        message = _verify_message(results)
        run = VerifyRun(
            scope=selection.scope, sample=selection.sample, limit=selection.limit, tables=selection.tables,
            started=started_at, finished=verify.now_iso(),
            summary=VerifySummary(message=message, checked=len(results), ok=counts["ok"], warnings=counts["warning"],
                                  errors=counts["error"], total=total,
                                  categories=len({p.table for p in results}), temporarily_installed=temporary,
                                  duration_s=round(time.perf_counter() - started, 2), altium_runs=runs,
                                  resolve_s=round(resolve_s, 2)),
            results=results,
        )
        _store_verify_run(ctx, ws, run)
        ctx.log(message, "success" if not counts["error"] else "warn")
        ctx.progress(1.0, message)
        return _verify_result(run)

    if not selected:
        return finish([])
    ctx.log(_selection_text(selection))
    ctx.progress(0.05, "Installierte Bibliotheken in Altium werden gelesen …")
    state, duplicates = classify_install_state(ws, bridge.install_state(ws.dblib_path))
    remember_install_state(state, dblib=ws.dblib_path)
    if state.duplicates and not state.resolves_to_this:
        raise DbLibError(
            f"Altium verwendet für „{state.file_name}“ eine andere installierte DbLib ({state.first_match}) – eine "
            f"Prüfung wäre nicht aussagekräftig. {duplicates_message(state, duplicates)}"
        )
    temporary = not state.installed
    results: list[VerifiedPart] = []
    pins_cache: dict[str, int | None] = {}
    categories_cache: dict[str, Any] = {}  # category definitions for the parameter comparison
    contents = _LibraryContents(bridge, _library_reader(ws))
    runs = 0
    resolve_s = 0.0
    try:
        if temporary:
            ctx.log("Die DbLib ist nicht installiert – sie wird für die Prüfung vorübergehend installiert.")
            bridge.install_library(ws.dblib_path)
        else:  # current data for the lookups (a rewritten DbLib also needs Altium's index rebuilt)
            result = bridge.refresh_dblib(state.file_name, rebuild_index=written.written)
            note_refresh_result(ws.dblib_path, result)
        for start in range(0, len(selected), RESOLVE_BATCH_SIZE):
            ctx.check_cancelled()
            chunk = selected[start : start + RESOLVE_BATCH_SIZE]
            ctx.progress(0.1 + 0.85 * start / len(selected),
                         f"Bauteile {start + 1}–{start + len(chunk)} von {len(selected)} werden in Altium aufgelöst …")
            keys = [(table, str(row.get("Part Number") or "")) for table, row in chunk]
            t0 = time.perf_counter()
            try:  # one Altium script run for the whole chunk
                resolved: list[DbComponentResolution] | BridgeCommandError = bridge.resolve_db_components(
                    ws.dblib_path, keys
                )
            except BridgeCommandError as exc:
                resolved = exc
            resolve_s += time.perf_counter() - t0
            runs += 1
            for index, (table, row) in enumerate(chunk):
                pn = keys[index][1]
                if isinstance(resolved, BridgeCommandError):
                    part = VerifiedPart(table=table, part_number=pn, status="error",
                                        library_ref=row.get("Library Ref"), footprint=row.get("Footprint Ref"),
                                        messages=[str(resolved)])
                else:
                    part = _check_part(ws, table, row, resolved[index], pins_cache, contents, categories_cache)
                results.append(part)
                ctx.log(f"{table} / {pn}: " + ("in Ordnung" if part.status == "ok" else "; ".join(part.messages)),
                        _STATUS_LEVEL[part.status])
    finally:
        if temporary:
            try:  # release the database (hidden document) before uninstalling, then restore the state
                bridge.refresh_dblib(state.file_name, rebuild_index=False)
                bridge.uninstall_library(ws.dblib_path)
            except Exception as exc:  # noqa: BLE001 - report, but keep the verification result
                log.warning("Vorübergehend installierte DbLib konnte nicht entfernt werden: %s", exc)
                ctx.log(f"Die vorübergehend installierte DbLib konnte nicht entfernt werden: {exc}", "warn")
    # runs = script runs for the lookups (one per RESOLVE_BATCH_SIZE parts)
    return finish(results, temporary=temporary, runs=runs, resolve_s=resolve_s)


@router.post("/altium/verify", response_model=AltiumJobOut)
def verify_in_altium(
    body: VerifyIn | None = None,
    ws: Workspace = Depends(require_workspace),
    bridge: AltiumBridge = Depends(get_bridge),
) -> AltiumJobOut:
    """Job: resolve parts of the open library in Altium (symbol found, footprints present, pins, parameter
    values and Description as in the database – each difference is a warning).

    ``job.result``: ``message, checked, ok, warnings, errors, total, categories,
    temporarily_installed, duration_s, altium_runs, resolve_s`` (= :class:`VerifySummary`),
    ``scope, sample, limit, tables, started, finished`` and ``parts`` (:class:`VerifiedPart`).
    A completed check is stored per library (``GET /altium/verify/last``)."""
    _require_altium(bridge)
    request = body or VerifyIn()
    return _job_out(jobs.submit("altium.verify", verify_title(request), _verify_job, bridge, ws, request))


def _table_labels(tables: Sequence[str]) -> list[str]:
    """German labels of category tables („Widerstände“), the table name where unknown."""
    from ..db import categories

    labels: list[str] = []
    for table in tables:
        try:
            labels.append(categories.get_category(table).label or table)
        except Exception:  # noqa: BLE001 - unknown table: the job reports it, the title just names it
            labels.append(table)
    return labels


def verify_title(request: VerifyIn) -> str:
    """Job title naming what is checked (review finding F6): „Bibliothek in Altium prüfen (alle Bauteile:
    Widerstände)“, „… (Stichprobe: Widerstände, Kondensatoren)“, „… (3 Bauteile)“."""
    base = "Bibliothek in Altium prüfen"
    if request.part_numbers:
        count = len(dict.fromkeys(request.part_numbers))
        return f"{base} ({plural(count, 'Bauteil', 'Bauteile')})"
    labels = _table_labels(list(dict.fromkeys(request.tables or [])))
    where = ""
    if labels:
        where = ": " + (", ".join(labels) if len(labels) <= 3 else plural(len(labels), "Kategorie", "Kategorien"))
    every = request.all or verify.sample_covers_all(request.tables, request.limit)
    return f"{base} ({'alle Bauteile' if every else 'Stichprobe'}{where})"


@router.get("/altium/verify/last", response_model=VerifyRun | None)
def last_verify(ws: Workspace = Depends(require_workspace)) -> VerifyRun | None:
    """The last completed check of the open library (``null`` if it was never checked): scope,
    sample, started, finished, summary and results – stored in the library, so it survives a
    restart."""
    with altium_errors():
        return verify.load_last()


# --------------------------------------------------------------------------- open


def _resolve_open_path(ws: Workspace, raw: str | None) -> Path:
    if not raw:
        ensure_dblib(ws)
        return ws.dblib_path
    path = ws.abs(raw.strip())
    if path is None:
        raise DbLibError("Kein Pfad angegeben.")
    if path.suffix.lower() not in OPENABLE_SUFFIXES:
        raise DbLibError(
            f"„{path.name}“ ist keine Altium-Bibliothek (erlaubt: .DbLib, .SchLib, .PcbLib, .IntLib, .DbLink)."
        )
    if not path.is_file():
        raise DbLibError(f"Die Datei „{path}“ existiert nicht.")
    return path


def _open_job(ctx: JobContext, bridge: AltiumBridge, path: Path) -> dict[str, Any]:
    ctx.progress(0.1, f"{path.name} wird in Altium geöffnet …")
    was_open = bridge.open_document(path)
    message = f"„{path.name}“ ist in Altium {'bereits geöffnet' if was_open else 'geöffnet'}."
    ctx.log(message, "success")
    ctx.progress(1.0, message)
    return {"message": message, "path": str(path), "was_open": was_open}


@router.post("/altium/open", response_model=AltiumJobOut)
def open_in_altium(
    body: OpenIn | None = None,
    ws: Workspace = Depends(require_workspace),
    bridge: AltiumBridge = Depends(get_bridge),
) -> AltiumJobOut:
    """Job: open a library file (default: the DbLib) in Altium – explicit user action."""
    with altium_errors():
        path = _resolve_open_path(ws, (body or OpenIn()).path)
    _require_altium(bridge)
    return _job_out(jobs.submit("altium.open", f"{path.name} in Altium öffnen", _open_job, bridge, path))


__all__ = [
    "AltiumJobOut",
    "AltiumStatusOut",
    "DbLibPreviewOut",
    "DbLibRegenerateOut",
    "FootprintCheck",
    "InstallIn",
    "OdbcTestIn",
    "OpenIn",
    "RefreshIn",
    "VerifiedPart",
    "VerifyIn",
    "VerifyRun",
    "VerifySummary",
    "altium_errors",
    "get_bridge",
    "get_refresh_service",
    "router",
]
