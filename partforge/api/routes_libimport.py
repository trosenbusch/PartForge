"""API routes: library import (symbols and footprints of existing Altium libraries) and "Bauteile anlegen".

``POST /library-import/scan {path}`` reads a source as a job (``library-import.scan``, reads only): a folder
(recursively), a ``.SchLib``/``.PcbLib``, an ``.IntLib``, a ``.LibPkg`` or a ``.zip`` archive. ``job.result`` is
the short form of the scan (``id``, counts, ``message``); ``GET /library-import/scans/{id}`` returns it with every
file and component (name state: ``new``, ``imported`` – already imported from the same file –, ``taken`` – the
name is registered elsewhere –, ``duplicate`` – twice in the source). ``POST /library-import/run`` (job
``libraries.import``, holds the library) copies the chosen files into ``Symbols\\Import\\<Ziel>`` /
``Footprints\\Import\\<Ziel>`` and registers their components as ``imported`` – optionally followed by the house
style conversion (``convert``, with the rules of the last batch edit). ``GET /library-import/preview`` renders a
component of the source before the import. ``POST /library-import/parts-table`` builds a table of imported symbols with their parameters and
footprint links and returns it as an upload of the spreadsheet import (``ImportPreviewOut``) – the import wizard
continues with the column mapping.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..altium import libimport, sync
from ..altium.libwriter import WriterUnavailable
from ..altium.rustwriter import RustWriterError
from ..importers import spreadsheet
from ..jobs import JobContext, jobs, library_hold
from ..workspace import Workspace
from .deps import require_workspace

log = logging.getLogger(__name__)

router = APIRouter(tags=["library-import"])

SCAN_JOB_KIND = "library-import.scan"  # reads only
IMPORT_JOB_KIND = "libraries.import"  # in partforge.jobs.LIBRARY_JOB_KINDS: holds its library


class ScanIn(BaseModel):
    path: str = Field(description="Ordner oder Bibliotheksdatei (.SchLib, .PcbLib, .IntLib, .LibPkg, .zip), absolut")


class ScanSummary(BaseModel):
    id: str
    source: str
    name: str
    files: int
    symbols: int
    footprints: int
    new: int
    taken: int
    duplicates: int
    imported: int
    notes: list[str] = Field(default_factory=list)
    message: str


class PartsTableIn(BaseModel):
    libraries: list[str] | None = Field(default=None, description="Bibliotheksdateien (relativ), None = alle")
    names: list[str] | None = Field(default=None, description="Einzelne Symbole, None = alle der Bibliotheken")


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, sync.SyncError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, WriterUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


def _summary(scan: libimport.ImportScan) -> dict[str, Any]:
    return ScanSummary(
        id=scan.id, source=scan.source, name=scan.name, files=len(scan.files), symbols=scan.symbols,
        footprints=scan.footprints, new=scan.new, taken=scan.taken, duplicates=scan.duplicates, imported=scan.imported,
        notes=scan.notes, message=scan.message,
    ).model_dump()


@router.post("/library-import/scan")
def start_scan(body: ScanIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Read a source as a job; ``job.result`` = :class:`ScanSummary` (the full scan: ``GET …/scans/{id}``)."""
    path = Path(body.path.strip().strip('"'))
    if not body.path.strip() or not path.is_absolute():
        raise HTTPException(status_code=400, detail="Bitte einen absoluten Pfad zu einem Ordner oder einer Bibliothek angeben.")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path} wurde nicht gefunden.")

    def run(ctx: JobContext) -> dict[str, Any]:
        return _summary(libimport.scan(str(path), ctx=ctx))

    job = jobs.submit(SCAN_JOB_KIND, f"Bibliothek einlesen: {path.name or path}", run)
    return {"job": job.snapshot()}


@router.get("/library-import/scans/{scan_id}", response_model=libimport.ImportScan)
def get_scan(
    scan_id: str,
    target: str | None = Query(default=None, description="Anderer Zielordner (Ziele, vorhandene Dateien und "
                                                          "Namenszustände für ihn)"),
    ws: Workspace = Depends(require_workspace),
) -> libimport.ImportScan:
    try:
        return libimport.scan_for_target(scan_id, target)
    except sync.SyncError as exc:
        raise _http(exc) from exc


@router.post("/library-import/run")
def start_import(body: libimport.LibraryImportOptions, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Import the chosen files of a scan (job ``libraries.import``; ``job.result``: ``copied``, ``unchanged``,
    ``symbols``, ``footprints``, ``libraries``, ``conflicts``, ``skipped``, ``errors``, ``conversion``,
    ``message``)."""
    try:
        scan = libimport.get_scan(body.scan_id)
    except sync.SyncError as exc:
        raise _http(exc) from exc
    root = ws.root

    def run(ctx: JobContext) -> dict[str, Any]:
        with library_hold(ctx, root):
            return libimport.run_import(body, ctx=ctx)

    job = jobs.submit(IMPORT_JOB_KIND, f"Bibliotheksimport: {body.target or scan.name}", run)
    return {"job": job.snapshot()}


@router.get(
    "/library-import/preview",
    response_class=Response,
    responses={200: {"content": {"image/svg+xml": {}}, "description": "SVG-Vorschau"}},
)
def preview(
    scan_id: str,
    rel: str = Query(description="Datei der Quelle (wie im Scan)"),
    name: str = Query(description="Symbol oder Footprint"),
    theme: Literal["altium", "dark", "light"] = "dark",
    ws: Workspace = Depends(require_workspace),
) -> Response:
    """Thumbnail of a component of the source (read through the library writer)."""
    try:
        scan = libimport.get_scan(scan_id)
    except sync.SyncError as exc:
        raise _http(exc) from exc
    wanted = sync._rel_key(rel)
    entry = next((f for f in scan.files if sync._rel_key(f.rel) == wanted), None)
    if entry is None or not Path(entry.path).is_file():
        raise HTTPException(status_code=404, detail="Datei nicht im Scan.")
    session = sync._Session(ws, None)
    try:
        spec = sync._read_component(session.writer(), Path(entry.path), name)
    except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=503, detail=f"Vorschau nicht möglich: {exc}") from exc
    finally:
        session.finish()
    if spec is None:
        raise HTTPException(status_code=404, detail=f"„{name}“ ist nicht in {Path(entry.path).name} enthalten.")
    svg = sync.component_thumbnail(spec, theme)
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=600"})


@router.post("/library-import/parts-table")
def parts_table(body: PartsTableIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Table of imported symbols (parameters, footprint links) as an upload of the spreadsheet import: the import
    wizard continues with ``POST /import/preview/{token}`` (category, mapping) and ``/import/run``."""
    try:
        data, rows = libimport.parts_table(libraries=body.libraries, names=body.names)
    except sync.SyncError as exc:
        raise _http(exc) from exc
    try:
        token = spreadsheet.store_upload(data, "Bibliotheksimport.csv")
    except spreadsheet.SpreadsheetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"token": token, "file_name": "Bibliotheksimport.csv", "rows": rows}
