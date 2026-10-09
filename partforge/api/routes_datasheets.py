"""API routes: datasheet import with Claude (upload, URL import, datasheet search, page images, cost estimate,
extraction, proposal, commit – also of only the symbols or only the footprints –, packages taken over from another
datasheet) and the AI status/test endpoints.

Long operations run as jobs (``{"job": snapshot}``): text-layer analysis after an upload, URL download, datasheet
search (``datasheet-find``), extraction and commit. Errors: 404 unknown datasheet / no analysis yet, 409 no library
open (or switched meanwhile), 400 business errors, 503 Claude API not available – with
``detail = {"code": …, "message": …}`` (``code``: key_missing, key_rejected, model_unavailable, network,
rate_limited, ai_disabled, unknown).

Jobs report structured progress in ``job.detail`` (``step`` = download | read | select_pages | identity | geometry |
check | save, ``step_label``, ``steps``, ``datasheet_id`` – for URL imports as soon as the PDF is stored –,
``pages_total``, ``pages_selected``, ``pages_active``, ``counters``, ``cost_usd``, ``budget_usd``,
``model_label``) and end with a German outcome sentence in ``job.message``.

Library guard: the commit job holds its library (``commit_proposal`` → :func:`partforge.jobs.library_hold`); the
direct writes (upload, edited extraction, delete) and the short database phases of the analysis/URL jobs hold it with
``ctx=None``, so a library switch waits for them but never cancels a paid analysis. A result whose library was
closed meanwhile is kept in that library's folder and merged when it is opened again (router lifespan: on
``WORKSPACE_OPENED`` and for the library open at start; ``GET /datasheets`` checks again).

The Claude API key never leaves the backend: ``/ai/status`` only reports *whether* and *where* a key is
configured (``key_source = "replay"`` in the replay mode, :mod:`partforge.datasheet.replay`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from ..config import load_settings
from ..datasheet import find, llm, replay, search_costs, store
from ..datasheet.combine import (
    PackageSource,
    PackageTarget,
    merge_package,
    package_sources,
    package_targets,
    unmerge_package,
)
from ..datasheet.errors import (
    AiUnavailable,
    BudgetExceeded,
    DatasheetError,
    DatasheetNotFound,
    NoExtraction,
)
from ..datasheet.estimate import CostEstimate, estimate
from ..datasheet.extract import (
    EXTRACTION_STEPS,
    STEP_LABELS,
    ExtractOptions,
    announce_steps,
    run_extraction,
    store_edited_extraction,
)
from ..datasheet.labels import model_label
from ..datasheet.models import (
    CommitInfo,
    DatasheetMeta,
    ExtractionData,
    PageInfo,
    PartProposal,
    ProposalChoices,
    RunInfo,
)
from ..datasheet.normalize import issue_summary
from ..datasheet.prompts import TEST_PROMPT
from ..datasheet.proposal import build_proposal, commit_proposal
from ..db.audit import resolve_author
from ..db.models import DatasheetRecord
from ..domain.text import plural
from ..jobs import JobContext, LibraryChanged, jobs, library_hold
from ..workspace import Workspace, current_or_none
from .deps import require_workspace
from .routes_categories import db_errors

log = logging.getLogger(__name__)

JOB_KIND = "datasheet"
COMMIT_JOB_KIND = "datasheet-commit"
FIND_JOB_KIND = find.FIND_JOB_KIND
_T = TypeVar("_T")


# --------------------------------------------------------------------------- results of a closed library


def apply_pending_results(ws: Workspace) -> list[str]:
    """Merge the analysis results kept in the folder of ``ws`` while it was closed (no-op without such files)."""
    if not store.pending_files(ws):
        return []
    try:
        with library_hold(None, ws.root):
            return store.apply_pending(ws)
    except LibraryChanged:
        return []


def _on_workspace_opened(ws: Workspace) -> None:
    try:
        applied = apply_pending_results(ws)
    except Exception:  # noqa: BLE001 - opening the library must never fail because of this
        log.exception("Gesicherte Datenblatt-Ergebnisse von %s konnten nicht übernommen werden", ws.root)
        return
    if applied:
        log.info("%s gesicherte Datenblatt-Ergebnisse übernommen (%s)", len(applied), ws.root)


@asynccontextmanager
async def _lifespan(_app: Any) -> AsyncIterator[None]:
    from .. import events

    unsubscribe = events.subscribe(events.WORKSPACE_OPENED, _on_workspace_opened)
    ws = current_or_none()
    if ws is not None:  # the launcher opens the last library before the server starts
        await asyncio.to_thread(_on_workspace_opened, ws)
    try:
        yield
    finally:
        unsubscribe()


router = APIRouter(tags=["datasheets"], lifespan=_lifespan)


# --------------------------------------------------------------------------- models


class DatasheetOut(BaseModel):
    id: str
    file: str  # workspace-relative
    path: str  # absolute
    original_name: str
    title: str | None = None
    manufacturer: str | None = None
    mpns: list[str] = Field(default_factory=list)
    page_count: int = 0
    text_pages: list[int] = Field(default_factory=list)
    created: str | None = None
    source_url: str | None = None
    size_bytes: int = 0
    status: Literal["neu", "gelesen", "analysiert", "übernommen"] = "neu"
    has_extraction: bool = False
    edited: bool = False
    model: str = ""
    model_label: str = ""  # "Claude Opus 5.5" (friendly name of ``model``)
    extracted: str | None = None
    cost_usd: float = 0.0  # all Claude calls of this datasheet, also those of failed analyses
    last_error: str | None = None  # reason of the last failed analysis
    devices: list[str] = Field(default_factory=list)
    issues: dict[str, int] = Field(default_factory=dict)
    package_only: bool = Field(default=False, description="Nur Gehäusezeichnung, kein Bauteil (nur Footprints)")
    saved_symbols: list[str] = Field(default_factory=list, description="Mit „Nur Symbol speichern“ gespeichert")
    saved_footprints: list[str] = Field(default_factory=list, description="Mit „Nur Footprint speichern“ gespeichert")
    merged_from: list[str] = Field(default_factory=list,
                                   description="Dateinamen der Datenblätter, aus denen Gehäuse übernommen wurden")


class DatasheetDetailOut(DatasheetOut):
    pages: list[PageInfo] = Field(default_factory=list)
    selected_pages: list[int] = Field(default_factory=list)
    selection_method: str = ""
    runs: list[RunInfo] = Field(default_factory=list)
    committed: list[CommitInfo] = Field(default_factory=list)


class UploadOut(BaseModel):
    datasheet: DatasheetOut
    duplicate: bool = False
    job: dict[str, Any] | None = None
    warning: str | None = None


class FromUrlIn(BaseModel):
    url: str
    extract: bool = Field(default=False, description="Nach dem Download sofort mit Claude analysieren")
    options: ExtractOptions | None = None
    search_job_id: str | None = Field(
        default=None, description="Job „Datenblatt suchen“, aus dem die Adresse stammt – seine Kosten werden dem "
                                  "Datenblatt zugerechnet")


class JobOut(BaseModel):
    job: dict[str, Any]


class ExtractionOut(BaseModel):
    datasheet_id: str
    extraction: ExtractionData
    model: str = ""
    model_label: str = ""
    effort: str = ""
    extracted: str | None = None
    edited: bool = False
    selected_pages: list[int] = Field(default_factory=list)
    selection_method: str = ""
    runs: list[RunInfo] = Field(default_factory=list)
    cost_usd: float = 0.0
    budget_usd: float = 0.0


class MergePackageIn(BaseModel):
    package: str = Field(description="Gehäusecode in diesem Datenblatt (bekommt die Maße)")
    source_id: str = Field(description="Datenblatt mit der Gehäusezeichnung")
    source_package: str = Field(description="Gehäusecode im anderen Datenblatt")


class UnmergePackageIn(BaseModel):
    package: str = Field(description="Gehäusecode in diesem Datenblatt")


class MergeOut(ExtractionOut):
    notes: list[str] = Field(default_factory=list, description="Hinweise zur Übernahme (deutsch)")


class DeleteOut(BaseModel):
    id: str
    file_deleted: bool
    message: str | None = None


class AiStatusOut(BaseModel):
    enabled: bool
    key_configured: bool
    key_source: str | None  # "env" | "stored" | "file" | "replay" | None (never the key itself)
    key_file_problem: str | None = Field(
        default=None,
        description="Deutscher Hinweis, warum eine konfigurierte Schlüsseldatei keinen gültigen Schlüssel liefert "
                    "(UNC/Gerätepfad, nicht gefunden, zu groß, kein sk-ant-…-Schlüssel) – sonst null",
    )
    model: str
    effort: str
    fast_model: str
    use_fallbacks: bool
    max_cost_per_import_usd: float
    model_label: str = ""  # "Claude Opus 5.5"
    fast_model_label: str = ""  # "Claude Haiku 5.5"


class AiTestOut(BaseModel):
    ok: bool
    model: str
    reply: str
    latency_ms: int
    cost_usd: float
    request_id: str | None = None
    model_label: str = ""


class AiErrorDetail(BaseModel):
    """``detail`` of a 503 (and of every error of ``POST /ai/test``)."""

    code: Literal["key_missing", "key_rejected", "model_unavailable", "network", "rate_limited", "ai_disabled",
                  "unknown"]
    message: str


class AiErrorOut(BaseModel):
    """Body of a 503 response: ``{"detail": {"code": …, "message": …}}``."""

    detail: AiErrorDetail


_AI_ERRORS: dict[int | str, dict[str, Any]] = {503: {"model": AiErrorOut, "description": "Claude nicht verfügbar"}}


# --------------------------------------------------------------------------- helpers


def _ai_detail(exc: AiUnavailable) -> dict[str, str]:
    return {"code": exc.code, "message": str(exc)}


@contextmanager
def ds_errors() -> Iterator[None]:
    """Map datasheet and database errors to HTTP errors with German messages."""
    with db_errors():  # database errors (404/409/400/500); HTTPExceptions pass through
        try:
            yield
        except LibraryChanged as exc:  # the library was switched or closed meanwhile
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (DatasheetNotFound, NoExtraction) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AiUnavailable as exc:
            raise HTTPException(status_code=503, detail=_ai_detail(exc)) from exc
        except (BudgetExceeded, DatasheetError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _package_only(meta: DatasheetMeta) -> bool:
    data = meta.extraction
    return data is not None and not data.devices and any(p.has_geometry() for p in data.packages)


def _status(rec: DatasheetRecord, meta: DatasheetMeta) -> str:
    """„übernommen“ once parts were created from it – or, for a package drawing, its footprints were saved; saving only
    the symbol of a device datasheet keeps it „analysiert“ (the part is still to be created)."""
    if any(c.scope == "part" for c in meta.committed) or (_package_only(meta) and meta.committed):
        return "übernommen"
    if meta.extraction is not None:
        return "analysiert"
    if meta.pages:
        return "gelesen"
    return "neu"


def _saved(meta: DatasheetMeta, scope: Literal["symbols", "footprints"]) -> list[str]:
    names: list[str] = []
    for commit in meta.committed:
        if commit.scope == scope:
            names.extend(commit.symbols if scope == "symbols" else commit.footprints)
    return list(dict.fromkeys(names))


def _out(rec: DatasheetRecord, ws: Workspace, *, detail: bool = False) -> DatasheetOut:
    meta = store.load_meta(rec)
    path = ws.abs(rec.file)
    data = meta.extraction
    merged_from = list(dict.fromkeys(p.origin.file for p in data.packages if p.origin is not None)) if data else []
    base: dict[str, Any] = dict(
        id=rec.id, file=rec.file, path=str(path) if path is not None else "", original_name=rec.original_name,
        title=rec.title, manufacturer=rec.manufacturer, mpns=rec.mpns, page_count=rec.page_count,
        text_pages=rec.text_pages, created=rec.created, source_url=meta.source_url, size_bytes=meta.size_bytes,
        status=_status(rec, meta), has_extraction=data is not None, edited=meta.edited, model=meta.model,
        model_label=model_label(meta.model) if meta.model else "", extracted=meta.extracted, cost_usd=meta.cost_usd,
        last_error=meta.last_error, devices=[d.base_part for d in data.devices] if data else [],
        issues=dict(issue_summary(data.issues)) if data else {}, package_only=_package_only(meta),
        saved_symbols=_saved(meta, "symbols"), saved_footprints=_saved(meta, "footprints"), merged_from=merged_from,
    )
    if not detail:
        return DatasheetOut(**base)
    return DatasheetDetailOut(**base, pages=meta.pages, selected_pages=meta.selected_pages,
                              selection_method=meta.selection_method, runs=meta.runs, committed=meta.committed)


def _extraction_out(rec: DatasheetRecord) -> ExtractionOut:
    meta = store.load_meta(rec)
    if meta.extraction is None:
        raise NoExtraction(rec.id)
    return ExtractionOut(
        datasheet_id=rec.id, extraction=meta.extraction, model=meta.model,
        model_label=model_label(meta.model) if meta.model else "", effort=meta.effort, extracted=meta.extracted,
        edited=meta.edited, selected_pages=meta.selected_pages, selection_method=meta.selection_method,
        runs=meta.runs, cost_usd=meta.cost_usd, budget_usd=load_settings().ai.max_cost_per_import_usd,
    )


def _held(ctx: JobContext, ws: Workspace, fn: Callable[[], _T], what: str) -> _T:
    """``fn()`` while holding the library ``ws`` (short database phase of a job); a switched or closed library ends
    the job ``cancelled`` with a German warning."""
    try:
        with library_hold(None, ws.root):
            return fn()
    except LibraryChanged as exc:
        ctx.log(f"{exc} {what}", "warn")
        raise


def _analysis_job(ctx: JobContext, datasheet_id: str, ws: Workspace, extract: bool,
                  options: ExtractOptions | None) -> dict[str, Any]:
    announce_steps(ctx, EXTRACTION_STEPS if extract else ("read",))
    ctx.detail(datasheet_id=datasheet_id, step="read", step_label=STEP_LABELS["read"])
    ctx.progress(0.02, "Textebene wird gelesen …")
    rec = _held(ctx, ws, lambda: store.get_record(datasheet_id), "Das Datenblatt wurde nicht gelesen.")

    def hook(index: int, total: int) -> None:
        if index % 5 == 0:
            ctx.check_cancelled()
            ctx.progress(0.02 + 0.08 * index / max(1, total), f"Seite {index + 1} von {total} wird gelesen …")

    store.read_texts(rec, ws=ws, progress=hook)  # the slow part, without the library

    def analysed() -> DatasheetRecord:
        return store.analyze(store.get_record(datasheet_id), ws=ws)[0]

    rec = _held(ctx, ws, analysed, "Das Datenblatt wurde nicht gelesen.")
    meta = store.load_meta(rec)
    empty = [p.page for p in meta.pages if p.quality != "ok"]
    ctx.detail(pages_total=rec.page_count)
    ctx.log(f"{rec.page_count} Seiten gelesen" + (f", davon ohne Textebene: {len(empty)}" if empty else ""))
    result: dict[str, Any] = {"datasheet_id": rec.id, "page_count": rec.page_count}
    if extract:
        result["extraction"] = run_extraction(ctx, rec.id, options, ws=ws)
    else:
        ctx.progress(1.0, f"Datenblatt gelesen: {plural(rec.page_count, 'Seite', 'Seiten')}"
                     + (f", davon {len(empty)} ohne Textebene" if empty else ""))
    return result


def _attach_search_costs(rec: DatasheetRecord, search_job_id: str, ctx: JobContext) -> None:
    """Add the paid calls of the datasheet search that found this PDF to the datasheet – once per search: from the
    persistent ledger (:mod:`partforge.datasheet.search_costs`, also after a restart or when the job list no longer
    holds the job), else from the finished job."""
    job = jobs.get(search_job_id)
    if job is not None and (job.kind != FIND_JOB_KIND or job.status != "done" or not isinstance(job.result, dict)):
        return
    if job is not None and job.result.get("attached_to"):
        return
    try:
        claimed = search_costs.claim(search_job_id, rec.id)
        recorded = claimed is not None or search_costs.get(search_job_id) is not None
    except Exception:  # noqa: BLE001 - the costs must never stop the import itself
        log.exception("Kostenprotokoll der Datenblattsuche nicht nutzbar (Suche %s)", search_job_id)
        claimed, recorded = None, False
    if claimed is not None:
        runs = list(claimed.runs)
    elif job is not None and not recorded:  # not in the ledger (could not be written or read)
        runs = [RunInfo.model_validate(r) for r in job.result.get("runs") or []]
    else:  # unknown search, or its costs were attached already (to this or another datasheet)
        return
    if not runs:
        return
    store.add_runs(rec, runs)
    if job is not None:
        job.result = {**job.result, "attached_to": rec.id}  # a new dict: snapshots being serialised keep the old one
    ctx.log(f"Kosten der Datenblattsuche ({sum(r.cost_usd for r in runs):.3f} USD) dem Datenblatt zugerechnet.")


def _url_job(ctx: JobContext, body: FromUrlIn, ws: Workspace) -> dict[str, Any]:
    announce_steps(ctx, ("download", *(EXTRACTION_STEPS if body.extract else ("read",))))
    ctx.detail(step="download", step_label=STEP_LABELS["download"])
    ctx.progress(0.01, "Datenblatt wird heruntergeladen …")
    ctx.log(f"Download: {body.url}")
    if replay.active():  # replay mode: the file a search fixture names, never the network
        data, name, final_url = replay.download(body.url)
    else:
        data, name, final_url = store.download_pdf(body.url, cancelled=lambda: ctx.cancelled)
    ctx.log(f"{len(data) / 1024:.0f} kB heruntergeladen ({name})")

    def ingest() -> tuple[DatasheetRecord, bool]:
        stored, duplicate = store.ingest_bytes(data, name, source_url=final_url, ws=ws)
        if body.search_job_id:
            _attach_search_costs(stored, body.search_job_id, ctx)
        return stored, duplicate

    rec, duplicate = _held(ctx, ws, ingest, "Das heruntergeladene Datenblatt wurde nicht gespeichert.")
    ctx.detail(datasheet_id=rec.id)
    if duplicate:
        ctx.log("Dieses Datenblatt ist bereits in der Bibliothek – vorhandener Eintrag wird verwendet.", "warn")
    result = _analysis_job(ctx, rec.id, ws, body.extract, body.options)
    result["duplicate"] = duplicate
    if not body.extract:
        what = "Bereits vorhanden" if duplicate else "Heruntergeladen"
        ctx.progress(1.0, f"{what}: {name} ({plural(int(result.get('page_count') or 0), 'Seite', 'Seiten')})")
    return result


def _ensure_ai(**context: Any) -> None:
    """503 before a job is started when Claude cannot be used (no key, AI switched off, no recording in the replay
    mode)."""
    llm.get_client(**context)


# --------------------------------------------------------------------------- datasheets


@router.get("/datasheets", response_model=list[DatasheetOut])
def list_datasheets(ws: Workspace = Depends(require_workspace)) -> list[DatasheetOut]:
    from ..db import registry

    _on_workspace_opened(ws)  # results of analyses that finished while this library was closed (never fails)
    with ds_errors():
        return [_out(rec, ws) for rec in registry.list_datasheets()]


@router.post("/datasheets", response_model=UploadOut, status_code=201, responses=_AI_ERRORS)
def upload_datasheet(
    response: Response,
    file: UploadFile = File(...),
    extract: bool = Form(default=False),
    options: str | None = Form(default=None, description="ExtractOptions als JSON (optional)"),
    ws: Workspace = Depends(require_workspace),
) -> UploadOut:
    """Upload a PDF (multipart). Stored content-addressed; the text-layer analysis (and with ``extract=true`` the
    Claude extraction) runs as a job."""
    content = file.file.read(store.MAX_PDF_BYTES + 1)
    if len(content) > store.MAX_PDF_BYTES:
        raise HTTPException(status_code=400, detail=f"Die Datei ist zu groß (höchstens {store.MAX_PDF_BYTES // 2**20} MB).")
    opts: ExtractOptions | None = None
    if options:
        try:
            opts = ExtractOptions.model_validate(json.loads(options))
        except (ValueError, ValidationError) as exc:
            raise HTTPException(status_code=400, detail=f"Ungültige Analyse-Optionen: {exc}") from exc
    with ds_errors():
        with library_hold(None, ws.root):  # a library switch waits for the stored file and its entry
            rec, duplicate = store.ingest_bytes(content, file.filename or "Datenblatt.pdf", ws=ws)
        warning = None
        if extract:
            try:
                _ensure_ai(datasheet_id=rec.id)
            except AiUnavailable as exc:
                warning, extract = f"Datenblatt gespeichert, aber nicht analysiert: {exc}", False
        meta = store.load_meta(rec)
        job = None
        if extract or not meta.pages:
            title = f"Datenblatt „{rec.original_name}“ " + ("analysieren" if extract else "lesen")
            job = jobs.submit(JOB_KIND, title, _analysis_job, rec.id, ws, extract, opts).snapshot()
        if duplicate:
            response.status_code = 200
        return UploadOut(datasheet=_out(rec, ws), duplicate=duplicate, job=job, warning=warning)


@router.post("/datasheets/from-url", response_model=JobOut, responses=_AI_ERRORS)
def import_from_url(body: FromUrlIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Download a datasheet (http/https, PDF only) as a job; the manufacturer URL becomes the datasheet link."""
    if not body.url.strip().lower().startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Bitte eine vollständige Web-Adresse angeben (http:// oder https://).")
    with ds_errors():
        if body.extract:
            _ensure_ai()
    job = jobs.submit(JOB_KIND, f"Datenblatt laden: {body.url[:80]}", _url_job, body, ws)
    return {"job": job.snapshot()}


@router.post("/datasheets/find", response_model=JobOut, responses=_AI_ERRORS)
def find_datasheet(body: find.FindRequest) -> dict[str, Any]:
    """„Datenblatt suchen“ (job ``datasheet-find``): Claude searches the web for the official datasheet PDF; the result
    lists checked candidates (``find.FindResult``). Needs no open library; 503 when Claude is not available, 400 when
    the cost limit is too low for a search."""
    with ds_errors():
        settings = load_settings()
        _ensure_ai(settings=settings, search=body.query)
        find.plan(settings, body)  # BudgetExceeded (400) before anything runs
    title = f"Datenblatt suchen: {body.query}" + (f" ({body.manufacturer})" if body.manufacturer else "")
    job = jobs.submit(FIND_JOB_KIND, title[:120], find.run_find, body)
    return {"job": job.snapshot()}


@router.get("/datasheets/{datasheet_id}", response_model=DatasheetDetailOut)
def get_datasheet(datasheet_id: str, ws: Workspace = Depends(require_workspace)) -> DatasheetOut:
    with ds_errors():
        return _out(store.get_record(datasheet_id), ws, detail=True)


@router.get("/datasheets/{datasheet_id}/file", response_class=FileResponse)
def get_datasheet_file(datasheet_id: str, ws: Workspace = Depends(require_workspace)) -> FileResponse:
    with ds_errors():
        rec = store.get_record(datasheet_id)
        path = store.pdf_path(rec, ws)
    return FileResponse(path, media_type="application/pdf", filename=rec.original_name,
                        content_disposition_type="inline")


@router.get("/datasheets/{datasheet_id}/pages/{page}.png", response_class=FileResponse)
def get_page_image(datasheet_id: str, page: int, dpi: int | None = Query(default=None, ge=1, le=600),
                   ws: Workspace = Depends(require_workspace)) -> FileResponse:
    """Page render (PNG, cached). ``dpi`` 36–300 (default 110; 200 for details)."""
    with ds_errors():
        rec = store.get_record(datasheet_id)
        path = store.page_png(rec, page, dpi, ws=ws)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/datasheets/{datasheet_id}/estimate", response_model=CostEstimate)
def estimate_datasheet(datasheet_id: str, options: ExtractOptions | None = None,
                       ws: Workspace = Depends(require_workspace)) -> CostEstimate:
    """Cost estimate of an analysis with these options (``pages``, ``model``, ``effort`` … as for ``/extract``) from
    the page analysis – no Claude call. A datasheet that was not read yet is read first (text layer, cached)."""
    with ds_errors():
        rec = store.get_record(datasheet_id)
        meta = store.load_meta(rec)
        if not meta.pages:
            store.read_texts(rec, ws=ws)
            with library_hold(None, ws.root):
                rec = store.analyze(store.get_record(datasheet_id), ws=ws)[0]
            meta = store.load_meta(rec)
        return estimate(rec, meta.pages, options)


@router.post("/datasheets/{datasheet_id}/extract", response_model=JobOut, responses=_AI_ERRORS)
def extract_datasheet(datasheet_id: str, options: ExtractOptions | None = None,
                      ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Start the Claude extraction (job). Options: model, effort, pages, triage, vision, cost limit."""
    with ds_errors():
        rec = store.get_record(datasheet_id)
        _ensure_ai(datasheet_id=rec.id)
    job = jobs.submit(JOB_KIND, f"Datenblatt „{rec.original_name}“ analysieren", run_extraction, rec.id, options, ws=ws)
    return {"job": job.snapshot()}


@router.get("/datasheets/{datasheet_id}/extraction", response_model=ExtractionOut)
def get_extraction(datasheet_id: str, ws: Workspace = Depends(require_workspace)) -> ExtractionOut:
    with ds_errors():
        return _extraction_out(store.get_record(datasheet_id))


@router.put("/datasheets/{datasheet_id}/extraction", response_model=ExtractionOut)
def put_extraction(datasheet_id: str, body: ExtractionData, ws: Workspace = Depends(require_workspace)) -> ExtractionOut:
    """Save user corrections of the extraction: cleaned like Claude's answers (no ``|``/control characters, overbar
    pin names, field values normalised) and re-checked; the original answer of Claude is kept."""
    with ds_errors():
        with library_hold(None, ws.root):
            store_edited_extraction(datasheet_id, body, ws=ws)
        return _extraction_out(store.get_record(datasheet_id))


@router.get("/datasheets/{datasheet_id}/package-sources", response_model=list[PackageSource])
def get_package_sources(datasheet_id: str, package: str = Query(..., min_length=1, description="Gehäusecode"),
                        ws: Workspace = Depends(require_workspace)) -> list[PackageSource]:
    """Packages of the other analysed datasheets whose drawing data (dimensions, land pattern) can be taken over into
    ``package`` – best match first, with German notes (``matches``/``problems``)."""
    with ds_errors():
        return package_sources(datasheet_id, package)


@router.get("/datasheets/{datasheet_id}/package-targets", response_model=list[PackageTarget])
def get_package_targets(datasheet_id: str, package: str = Query(..., min_length=1, description="Gehäusecode"),
                        ws: Workspace = Depends(require_workspace)) -> list[PackageTarget]:
    """The other way round: packages of device datasheets that the drawing of ``package`` of this datasheet (e.g. a
    package-outline document) could complete – best match first (missing dimensions first)."""
    with ds_errors():
        return package_targets(datasheet_id, package)


@router.post("/datasheets/{datasheet_id}/merge-package", response_model=MergeOut)
def post_merge_package(datasheet_id: str, body: MergePackageIn,
                       ws: Workspace = Depends(require_workspace)) -> MergeOut:
    """Take over the drawing data of a package of another datasheet (``source_id``/``source_package``) into
    ``package`` of this one – stored like a correction, with the origin (``PackageData.origin``); ``notes`` = hints."""
    with ds_errors():
        with library_hold(None, ws.root):
            result = merge_package(datasheet_id, body.package, body.source_id, body.source_package, ws=ws)
        out = _extraction_out(store.get_record(datasheet_id))
        return MergeOut(**out.model_dump(), notes=result.notes)


@router.post("/datasheets/{datasheet_id}/unmerge-package", response_model=ExtractionOut)
def post_unmerge_package(datasheet_id: str, body: UnmergePackageIn,
                         ws: Workspace = Depends(require_workspace)) -> ExtractionOut:
    """Undo a takeover: ``package`` as it was before the drawing data came from another datasheet."""
    with ds_errors():
        with library_hold(None, ws.root):
            unmerge_package(datasheet_id, body.package, ws=ws)
        return _extraction_out(store.get_record(datasheet_id))


@router.post("/datasheets/{datasheet_id}/proposal", response_model=PartProposal)
def post_proposal(datasheet_id: str, choices: ProposalChoices | None = None,
                  svg: bool = Query(default=True, description="SVG-Vorschauen mitliefern"),
                  ws: Workspace = Depends(require_workspace)) -> PartProposal:
    """Dry run of "Bauteil anlegen": category, rows per variant, symbol(s), footprints, warnings, blockers, readiness
    (also of "Nur Symbol/Footprint speichern") and the ``fingerprint`` the commit checks (``expected_fingerprint``)."""
    with ds_errors():
        return build_proposal(datasheet_id, choices, ws=ws, svg=svg)


_COMMIT_TITLES = {"part": "Bauteil aus „{}“ anlegen", "symbols": "Symbol aus „{}“ speichern",
                  "footprints": "Footprint aus „{}“ speichern"}


@router.post("/datasheets/{datasheet_id}/commit", response_model=JobOut)
def post_commit(datasheet_id: str, choices: ProposalChoices | None = None,
                ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Create symbols, footprints and parts (job) – with ``scope`` = ``symbols`` | ``footprints`` only the symbols or
    only the footprints (no parts). Refuses (failed job, nothing written) unconfirmed blockers (``accept_issues``) and a
    plan that differs from ``expected_fingerprint`` – ``job.detail.code`` says which."""
    with ds_errors():
        rec = store.get_record(datasheet_id)
        if store.load_meta(rec).extraction is None:
            raise NoExtraction(rec.id)
    author = resolve_author(None)
    scope = choices.scope if choices is not None else "part"
    job = jobs.submit(COMMIT_JOB_KIND, _COMMIT_TITLES[scope].format(rec.original_name), commit_proposal, rec.id,
                      choices, ws=ws, author=author)
    return {"job": job.snapshot()}


@router.delete("/datasheets/{datasheet_id}", response_model=DeleteOut)
def delete_datasheet(datasheet_id: str, delete_file: bool = Query(default=True),
                     ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Remove the datasheet entry and its page images; the PDF is kept when parts link to it."""
    with ds_errors(), library_hold(None, ws.root):
        return store.delete_datasheet(datasheet_id, delete_file=delete_file, ws=ws)


# --------------------------------------------------------------------------- AI status / test


@router.get("/ai/status", response_model=AiStatusOut)
def ai_status() -> AiStatusOut:
    settings = load_settings()
    configured, source = llm.key_status(settings)
    from ..config import key_file_status

    return AiStatusOut(
        enabled=settings.ai.enabled, key_configured=configured, key_source=source,
        key_file_problem=key_file_status(settings),
        model=settings.ai.model, effort=settings.ai.effort, fast_model=settings.ai.fast_model,
        use_fallbacks=settings.ai.use_fallbacks, max_cost_per_import_usd=settings.ai.max_cost_per_import_usd,
        model_label=model_label(settings.ai.model), fast_model_label=model_label(settings.ai.fast_model),
    )


AI_TEST_TIMEOUT_S = 30.0  # read timeout of the connection test (connect: llm.CONNECT_TIMEOUT_S)
AI_TEST_RETRIES = 1


@router.post("/ai/test", response_model=AiTestOut,
             responses={503: {"model": AiErrorOut, "description": "Claude nicht verfügbar"},
                        400: {"model": AiErrorOut, "description": "Anfrage abgelehnt"}})
def ai_test() -> AiTestOut:
    """Tiny request with the fast model ("Reply with exactly: OK") – checks key, network and model; answers within
    about a minute even when the network is down (short timeouts, one retry). Errors: ``detail = {code, message}``
    (503 for :class:`AiUnavailable`, 400 when the API rejected the request)."""
    settings = load_settings()
    model = settings.ai.fast_model
    request = llm.LlmRequest(kind="test", model=model, max_tokens=512, timeout_s=AI_TEST_TIMEOUT_S,
                             max_retries=AI_TEST_RETRIES, messages=[{"role": "user", "content": TEST_PROMPT}])
    if model.startswith("claude-haiku"):
        request.thinking = {"type": "disabled"}
    elif llm.supports_effort(model):
        request.effort = "low"
    started = time.perf_counter()
    try:
        client = llm.get_client(settings)
        answer = client.run(request)
    except AiUnavailable as exc:
        raise HTTPException(status_code=503, detail=_ai_detail(exc)) from exc
    except DatasheetError as exc:  # the API rejected the request (ExtractionFailed)
        raise HTTPException(status_code=400, detail={"code": "unknown", "message": str(exc)}) from exc
    reply = " ".join(answer.text.split())[:200]
    return AiTestOut(ok=answer.stop_reason in ("end_turn", "max_tokens") and "OK" in reply.upper(), model=answer.model,
                     reply=reply, latency_ms=int((time.perf_counter() - started) * 1000),
                     cost_usd=round(answer.cost_usd, 6), request_id=answer.request_id,
                     model_label=model_label(answer.model))
