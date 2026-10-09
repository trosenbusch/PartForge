"""Datasheet extraction with Claude (runs as a background job).

Pipeline (:func:`run_extraction`):

1. text-layer analysis (page quality, keyword categories) – cached in the record,
2. page selection (heuristic, optional triage with the fast model, user pages), capped at ~12 pages (user pages at
   :data:`~.pages.MANUAL_PAGE_LIMIT`) and split into the pages for the two passes,
3. **identity pass**: PDF subset (base64 document block with ``cache_control``) + the identity schema –
   manufacturer, devices, orderable variants, field values, pin tables, package list,
4. **geometry pass**: PDF subset of the drawing pages + the geometry schema – outline dimensions and land
   pattern of exactly the packages found in step 3 (one combined schema exceeds the grammar size limit,
   see :mod:`.schema`),
5. normalisation + plausibility checks; when checks fail (pin count vs. package, missing or inconsistent
   dimensions …) a verification turn with 200 dpi renders is appended to the conversation of the affected
   pass (cache hit on its PDF prefix). Its answer is merged per item (:mod:`.merge` – it never drops data) and kept
   only if the checks do not get worse; a failed verification keeps the result of the passes,
6. the result, the raw answers, every API call and the costs are stored in ``pf_datasheets``.

**Paid calls are never lost**: every call is recorded as soon as its answer arrives (also an unusable one, with
the reason in :attr:`~.models.RunInfo.error`); when the analysis fails or is cancelled, the calls, their costs and
the reason (:attr:`~.models.DatasheetMeta.last_error`) are still stored.

**Library guard** (ARCHITEKTUR §8.4): the job holds its library only for the short database phases – reading the
record and the page analysis before the first paid call, saving the result – with ``library_hold(None, root)``, like
the direct writes: a library switch waits for these phases only and never cancels the paid calls. A result (or the
costs of a failed analysis) whose library is no longer open when it is saved is kept in that library's folder
(:func:`.store.save_pending`) and merged into it when it is opened again – nothing is ever written into another
library.

**Progress** (``JobContext.detail``): ``step`` (one of :data:`EXTRACTION_STEPS`: read, select_pages, identity,
geometry, check, save), ``step_label`` (German), ``steps``, ``datasheet_id``, ``pages_total``, ``pages_selected``,
``pages_active``, ``counters`` (mpns, pins, parameters, packages, dimensions), ``cost_usd`` (running), ``budget_usd``
and ``model_label`` ("Claude Opus 5.5 · Gründlichkeit niedrig"). The job ends with an outcome sentence ("Analyse fertig:
14 Bestellvarianten, 13 Pins, 2 Gehäuse – 0,23 $").

Default model/effort from ``AISettings`` (effort only for models that accept it); ``fallbacks="default"`` when
``use_fallbacks`` is on. The cost limit ``max_cost_per_import_usd`` is enforced before each call (input
estimate) and by capping ``max_tokens`` to the remaining budget. Progress and German log lines go to the job.
"""
from __future__ import annotations

import base64
import dataclasses
import logging
import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError, field_validator

from ..config import AppSettings
from ..db import categories as db_categories
from ..domain.text import plural
from ..jobs import JobCancelled, JobContext, LibraryChanged, library_hold
from ..workspace import Workspace, current
from . import labels, store
from . import pdf as pdfio
from .costs import Budget, estimate_pdf_tokens
from .errors import BudgetExceeded, DatasheetError, ExtractionFailed
from .llm import (
    CANCELLED_RUN_ERROR,
    LlmClient,
    LlmRequest,
    LlmResponse,
    RequestCancelled,
    ai_enabled_or_raise,
    get_client,
    supports_effort,
)
from .merge import Scope, merge_geometry, merge_identity, scope_from_issues
from .models import DatasheetMeta, ExtractionData, Issue, PageInfo, PendingResult, RunInfo, RunKind
from .normalize import GEOMETRY_ISSUES, IDENTITY_ISSUES, issue_summary, normalize_extraction
from .pages import MANUAL_PAGE_LIMIT, PageSelection, needs_triage, select_pages, triage_digest
from .prompts import (
    SYSTEM_PROMPT,
    TRIAGE_SYSTEM,
    geometry_instruction,
    identity_instruction,
    triage_instruction,
    verification_instruction,
)
from .schema import AiGeometry, AiIdentity, Triage, geometry_schema, identity_schema, triage_schema

log = logging.getLogger(__name__)

__all__ = [
    "EXTRACTION_STEPS",
    "STEP_LABELS",
    "ExtractOptions",
    "ExtractionSummary",
    "apply_verification",
    "parse_geometry",
    "parse_identity",
    "run_extraction",
    "split_pages",
    "store_edited_extraction",
]

MAX_TOKENS_IDENTITY = 32_000
MAX_TOKENS_GEOMETRY = 24_000
MAX_TOKENS_RETRY = 64_000
TRIAGE_MAX_TOKENS = 8_000
MAX_VISION_IMAGES = 6
VISION_DPI = 200
MAX_REQUEST_BYTES = 30 * 1024 * 1024  # API limit 32 MB per request (base64 grows by 4/3)
HARD_BUDGET_CAP = 25.0

#: Stable step ids of the datasheet jobs (``detail.step``) and their German labels. ``download`` precedes ``read`` in
#: URL imports; a read-only job has just ``read``.
STEP_LABELS: dict[str, str] = {
    "download": "Datenblatt herunterladen",
    "read": "Datenblatt lesen",
    "select_pages": "Seiten auswählen",
    "identity": "Bauteile und Pins",
    "geometry": "Gehäusemaße",
    "check": "Prüfung",
    "save": "Ergebnis speichern",
}
EXTRACTION_STEPS: tuple[str, ...] = ("read", "select_pages", "identity", "geometry", "check", "save")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,99}$")

Effort = Literal["low", "medium", "high"]
Switch = Literal["auto", "on", "off"]
PassKind = Literal["identity", "geometry"]
_M = TypeVar("_M", bound=BaseModel)

_GEOMETRY_REASONS = {"package", "land_pattern", "drawing", "triage:package_outline", "triage:land_pattern"}
_IDENTITY_REASONS = {"first page", "pins", "ordering", "triage:pinout", "triage:ordering"}


class ExtractOptions(BaseModel):
    """Options of ``POST /datasheets/{id}/extract`` (all optional)."""

    model: str | None = Field(default=None, description="Claude-Modell (Standard: Einstellungen)")
    effort: Effort | None = Field(default=None, description="Gründlichkeit (Standard: Einstellungen)")
    pages: list[int] | None = Field(default=None, max_length=500,
                                    description=f"Seiten manuell wählen (1-basiert, höchstens {MANUAL_PAGE_LIMIT})")
    max_pages: int = Field(default=12, ge=1, le=40)
    triage: Switch = Field(default="auto", description="Seiten-Vorauswahl mit dem schnellen Modell")
    vision: Switch = Field(default="auto", description="Kontrolle mit hochaufgelösten Seitenbildern")
    max_cost_usd: float | None = Field(default=None, gt=0, le=HARD_BUDGET_CAP,
                                       description="Kostenlimit für diesen Import (Standard: Einstellungen)")

    @field_validator("model")
    @classmethod
    def _model(cls, value: str | None) -> str | None:
        """Blank = the model of the settings; otherwise a plausible model id."""
        if value is None or not value.strip():
            return None
        text = value.strip()
        if not _MODEL_ID.match(text):
            raise ValueError(f"Ungültige Modellbezeichnung „{text[:40]}“.")
        return text

    @field_validator("pages")
    @classmethod
    def _pages(cls, value: list[int] | None) -> list[int] | None:
        if not value:
            return None
        if any(p < 1 for p in value):
            raise ValueError("Seitenzahlen beginnen bei 1.")
        return sorted(set(value))


class ExtractionSummary(BaseModel):
    datasheet_id: str
    model: str
    served_model: str
    effort: str
    pages: list[int]
    identity_pages: list[int]
    geometry_pages: list[int]
    selection_method: str
    devices: list[str]
    mpns: int
    packages: list[str]
    pins: int
    issues: dict[str, int]
    vision: bool
    cost_usd: float
    duration_s: float
    model_label: str = ""  # "Claude Opus 5.5 · Gründlichkeit niedrig"
    # where the result went: "library" = the record of the open library; "pending" = the library was closed meanwhile,
    # the result is kept in its folder and appears when it is opened again
    stored: Literal["library", "pending"] = "library"
    message: str = ""  # the outcome sentence of the job


# --------------------------------------------------------------------------- parsing

_ERROR_TEXTS = {
    "json_invalid": "kein gültiges JSON", "missing": "Angabe fehlt", "string_type": "Text erwartet",
    "int_type": "ganze Zahl erwartet", "int_parsing": "ganze Zahl erwartet", "float_type": "Zahl erwartet",
    "float_parsing": "Zahl erwartet", "bool_type": "Ja/Nein erwartet", "bool_parsing": "Ja/Nein erwartet",
    "list_type": "Liste erwartet", "model_type": "Objekt erwartet", "dict_type": "Objekt erwartet",
    "literal_error": "unzulässiger Wert", "enum": "unzulässiger Wert", "int_from_float": "ganze Zahl erwartet",
}


def _german(error: Any) -> str:
    kind = str(error.get("type", ""))
    text = _ERROR_TEXTS.get(kind, "ungültiger Wert")
    if kind == "json_invalid" and "EOF" in str(error.get("msg", "")):
        text = "JSON unvollständig"
    return text


def _parse(model: type[_M], text: str, what: str) -> _M:
    try:
        return model.model_validate_json(text)
    except ValidationError as exc:
        errors = exc.errors()
        first = errors[0] if errors else {}
        where = ".".join(str(p) for p in first.get("loc", ())) or "Antwort"
        more = f" und {len(errors) - 1} weitere Abweichung(en)" if len(errors) > 1 else ""
        raise ExtractionFailed(f"Die Antwort von Claude ({what}) passt nicht zum erwarteten Format "
                               f"({where}: {_german(first)}{more}).") from exc


def parse_identity(text: str) -> AiIdentity:
    return _parse(AiIdentity, text, "Bauteile und Pins")


def parse_geometry(text: str) -> AiGeometry:
    return _parse(AiGeometry, text, "Gehäusemaße")


def _parse_answer(parser: Callable[[str], _M], response: LlmResponse, run: RunInfo | None = None) -> _M:
    """Parse the answer; after a server-side fallback the text after the boundary is a second candidate. The
    reason of a failure is recorded in the run."""
    first_error: ExtractionFailed | None = None
    for text in response.text_candidates():
        try:
            return parser(text)
        except ExtractionFailed as exc:
            first_error = first_error or exc
    assert first_error is not None  # text_candidates() is never empty
    if run is not None:
        run.error = str(first_error)
    raise first_error


def _check_stop(response: LlmResponse) -> None:
    if response.stop_reason == "refusal":
        category = (response.stop_details or {}).get("category")
        raise ExtractionFailed(
            "Claude hat die Analyse abgelehnt" + (f" (Kategorie „{category}“)" if category else "")
            + ". Bitte andere Seiten wählen oder ein anderes Modell einstellen."
        )
    if response.stop_reason not in ("end_turn", "max_tokens", None):
        raise ExtractionFailed(f"Die Antwort von Claude ist unvollständig (Grund: {response.stop_reason}).")


# --------------------------------------------------------------------------- runs (paid calls)


@dataclass
class _Runs:
    """Every paid API call of one analysis, recorded as soon as its answer arrives (also an unusable one); the running
    cost goes to ``detail.cost_usd`` of the job."""

    budget: Budget
    items: list[RunInfo] = field(default_factory=list)
    ctx: JobContext | None = None

    def add(self, response: LlmResponse, request: LlmRequest) -> RunInfo:
        self.budget.add(response.cost_usd)
        run = response.run_info(request)
        self.items.append(run)
        if self.ctx is not None:
            self.ctx.detail(cost_usd=round(self.budget.spent_usd, 4))
        return run


def _checked(response: LlmResponse, run: RunInfo) -> None:
    try:
        _check_stop(response)
    except ExtractionFailed as exc:
        run.error = str(exc)
        raise


# --------------------------------------------------------------------------- progress


class _Progress:
    """Turns streamed JSON text into live counters for the job (partial JSON parse every ~2 kB): the progress message
    ("… 1 Bauteil, 14 Bestellnummern, 13 Pins") and ``detail.counters`` (``base`` = the counters of earlier passes)."""

    def __init__(self, ctx: JobContext | None, start: float, span: float, label: str, *,
                 base: dict[str, int] | None = None) -> None:
        self.ctx, self.start, self.span, self.label = ctx, start, span, label
        self.base = dict(base or {})
        self.buffer: list[str] = []
        self.chars = 0
        self._next = 1500
        self._announced = False

    def restart(self) -> None:
        """A new request of the same pass (longer output limit): the answer starts from scratch."""
        self.buffer.clear()
        self.chars = 0
        self._next = 1500

    def fallback(self, model: str) -> None:
        """Server-side fallback: the text received so far stays, the fallback model continues it."""
        if self.ctx is not None:
            target = f" auf {labels.model_label(model)}" if model else ""
            self.ctx.log(f"Claude hat das Modell gewechselt (Server-Fallback{target}) – die Antwort wird fortgesetzt.",
                         "warn")

    def text(self, delta: str) -> None:
        if not delta:
            return
        self.buffer.append(delta)
        self.chars += len(delta)
        if self.ctx is None or self.chars < self._next:
            return
        self._next = self.chars + 2000
        counts, counters = self._counts()
        if counters:
            self.ctx.detail(counters={**self.base, **counters})
        fraction = self.start + self.span * (1 - math.exp(-self.chars / 7000))
        self.ctx.progress(fraction, f"{self.label} … {counts}" if counts else f"{self.label} …")

    def _partial(self) -> dict[str, Any]:
        try:
            from jiter import from_json
        except ImportError:  # pragma: no cover - jiter ships with the anthropic SDK
            return {}
        try:
            value = from_json("".join(self.buffer).encode("utf-8"), partial_mode="trailing-strings")
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def _counts(self) -> tuple[str, dict[str, int]]:
        data = self._partial()
        manufacturer = data.get("manufacturer")
        if isinstance(manufacturer, str) and len(manufacturer) > 1 and len(data) > 1 and not self._announced \
                and self.ctx is not None:
            self._announced = True
            self.ctx.log(f"Hersteller erkannt: {manufacturer}")
        devices = [d for d in data.get("devices") or [] if isinstance(d, dict)]
        packages = [p for p in data.get("packages") or [] if isinstance(p, dict)]
        variants = sum(len(d.get("variants") or []) for d in devices)
        pins = sum(len(t.get("pins") or []) for d in devices for t in d.get("pin_tables") or [] if isinstance(t, dict))
        dims = sum(len(p.get("dimensions") or []) for p in packages)
        parameters = sum(len(d.get("parameters") or []) for d in devices) + sum(
            len(v.get("values") or []) for d in devices for v in d.get("variants") or [] if isinstance(v, dict))
        counters: dict[str, int] = {}
        if devices:
            counters.update(mpns=variants, pins=pins, parameters=parameters)
        if packages:
            counters["packages"] = len(packages)
        if dims:
            counters["dimensions"] = dims
        parts = []
        if devices:
            parts.append(f"{len(devices)} Bauteil{'e' if len(devices) != 1 else ''}")
        if variants:
            parts.append(f"{variants} Bestellnummern")
        if pins:
            parts.append(f"{pins} Pins")
        if packages:
            parts.append(f"{len(packages)} Gehäuse")
        if dims:
            parts.append(f"{dims} Maße")
        return ", ".join(parts), counters


def _call(client: LlmClient, request: LlmRequest, ctx: JobContext | None, progress: _Progress | None) -> LlmResponse:
    return client.run(
        request,
        on_text=progress.text if progress is not None else None,
        on_fallback=progress.fallback if progress is not None else None,
        cancelled=(lambda: ctx.cancelled) if ctx is not None else None,
    )


def _log(ctx: JobContext | None, text: str, level: Literal["info", "warn", "error", "success"] = "info") -> None:
    if ctx is not None:
        ctx.log(text, level)
    log.info("%s", text)


def _step(ctx: JobContext | None, fraction: float, step: str, message: str, **detail: Any) -> None:
    """Next step of the job: cancellation point, ``detail.step``/``step_label`` (+ ``detail``) and the message."""
    if ctx is not None:
        ctx.check_cancelled()
        ctx.detail(step=step, step_label=STEP_LABELS.get(step, step), **detail)
        ctx.progress(fraction, message)


def _detail(ctx: JobContext | None, **fields: Any) -> None:
    if ctx is not None:
        ctx.detail(**fields)


def announce_steps(ctx: JobContext | None, steps: Sequence[str]) -> None:
    """``detail.steps`` = the steps this job will go through (the outer job of a URL import sets its own first)."""
    if ctx is not None and "steps" not in ctx.job.detail:
        ctx.detail(steps=list(steps))


def counters_of(data: ExtractionData) -> dict[str, int]:
    """``detail.counters`` of a normalised result."""
    return {
        "mpns": len(data.mpns()),
        "pins": sum(len(t.pins) for d in data.devices for t in d.pin_tables),
        "parameters": sum(len(d.parameters) + sum(len(v.values) for v in d.variants) for d in data.devices),
        "packages": len(data.packages),
        "dimensions": sum(len(p.dimensions) for p in data.packages),
    }


def _pages_text(pages: Sequence[int]) -> str:
    """1, 2, 17, 21–24"""
    out: list[str] = []
    run: list[int] = []

    def flush() -> None:
        if run:
            out.append(f"{run[0]}–{run[-1]}" if len(run) > 2 else ", ".join(map(str, run)))

    for p in sorted(pages):
        if run and p == run[-1] + 1:
            run.append(p)
            continue
        flush()
        run = [p]
    flush()
    return ", ".join(out)


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("ascii")


def _progress_hook(ctx: JobContext | None) -> Callable[[int, int], None] | None:
    if ctx is None:
        return None

    def hook(index: int, total: int) -> None:
        if index % 5 == 0:
            ctx.check_cancelled()
            ctx.progress(0.02 + 0.03 * index / max(1, total), f"Seite {index + 1} von {total} wird gelesen …")

    return hook


# --------------------------------------------------------------------------- page split


def split_pages(selection: PageSelection, page_count: int | None = None) -> tuple[list[int], list[int]]:
    """(identity pages, geometry pages) of a selection; pages may belong to both passes.

    Manual, complete and scan selections send every page to both passes. A drawing without any keyword in the
    first half of the document (``page_count``) may be a pinout drawing and goes to both passes."""
    pages = list(selection.pages)
    if selection.method in ("manual", "all", "scan", "empty"):
        return pages, pages
    identity: list[int] = []
    geometry: list[int] = []
    for page in pages:
        reasons = set(selection.reasons.get(page, []))
        if reasons & _GEOMETRY_REASONS:
            geometry.append(page)
        early_drawing = reasons == {"drawing"} and page_count is not None and page <= page_count / 2
        if reasons & _IDENTITY_REASONS or not reasons & _GEOMETRY_REASONS or early_drawing:
            identity.append(page)
    return identity or pages, geometry or pages


# --------------------------------------------------------------------------- triage


def _triage(client: LlmClient, texts: Sequence[pdfio.PageText], settings: AppSettings, runs: _Runs,
            ctx: JobContext | None) -> dict[int, list[str]]:
    model = settings.ai.fast_model
    digest = triage_digest(texts)
    tokens = 1500 + len(digest) // 3
    max_tokens = runs.budget.max_tokens_for(model, input_tokens=tokens, wanted=TRIAGE_MAX_TOKENS, minimum=1000,
                                            cache_write=False, what="Die Seiten-Vorauswahl")
    request = LlmRequest(kind="triage", model=model, system=TRIAGE_SYSTEM,
                         effort="low" if supports_effort(model) else None, schema=triage_schema(),
                         max_tokens=max_tokens, messages=[{"role": "user", "content": triage_instruction(digest)}])
    _log(ctx, f"Seiten-Vorauswahl mit {labels.model_label(model)} …")
    response = _call(client, request, ctx, None)
    run = runs.add(response, request)
    if response.stop_reason != "end_turn":
        run.error = f"Seiten-Vorauswahl unvollständig ({response.stop_reason})."
        raise ExtractionFailed(run.error)
    triage = _parse_answer(lambda text: _parse(Triage, text, "Seiten-Vorauswahl"), response, run)
    wanted = {"pinout", "ordering", "package_outline", "land_pattern"}
    extra: dict[int, list[str]] = {}
    for vote in triage.pages:
        categories = [c for c in (str(x).strip().lower() for x in vote.categories) if c in wanted]
        if categories:
            extra[vote.page] = categories
    return extra


# --------------------------------------------------------------------------- passes


@dataclass
class _Pass:
    kind: PassKind
    pages: list[int]  # real pages of the attached subset (in order)
    request: LlmRequest
    response: LlmResponse
    runs: list[RunInfo]


def _document_messages(subset: bytes, instruction: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": [
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": _b64(subset)},
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instruction},
    ]}]


def _run_pass(client: LlmClient, kind: PassKind, *, pages: list[int], path: Path, total_pages: int,
              instruction: str, model: str, effort: str | None, fallbacks: bool, runs: _Runs,
              infos: Sequence[PageInfo], ctx: JobContext | None, progress: _Progress,
              encrypted: bool = False) -> _Pass:
    # the API rejects encrypted PDFs: owner-password files are always re-written (unencrypted subset)
    whole = len(pages) == total_pages and not encrypted
    subset = path.read_bytes() if whole else pdfio.subset_pdf(path, pages)
    if len(subset) * 4 // 3 > MAX_REQUEST_BYTES:
        raise DatasheetError(f"Die ausgewählten Seiten sind zu groß für die Claude-API ({len(subset) / 1e6:.0f} MB). "
                             "Bitte weniger Seiten wählen.")
    by_page = {i.page: i for i in infos}
    drawings = sum(1 for p in pages if by_page.get(p) is not None and by_page[p].quality != "ok")
    input_tokens = estimate_pdf_tokens(len(pages) - drawings, drawings) + len(instruction) // 3
    wanted = MAX_TOKENS_IDENTITY if kind == "identity" else MAX_TOKENS_GEOMETRY
    what = "Die Analyse der Bauteile" if kind == "identity" else "Die Analyse der Gehäusemaße"
    max_tokens = runs.budget.max_tokens_for(model, input_tokens=input_tokens, wanted=wanted, minimum=4000, what=what)
    request = LlmRequest(kind=kind, model=model, system=SYSTEM_PROMPT, effort=effort,
                         schema=identity_schema() if kind == "identity" else geometry_schema(),
                         max_tokens=max_tokens, messages=_document_messages(subset, instruction), fallbacks=fallbacks,
                         pages=list(pages))
    first = len(runs.items)
    response = _call(client, request, ctx, progress)
    run = runs.add(response, request)
    _checked(response, run)
    if response.stop_reason == "max_tokens":
        run.error = "Antwort abgeschnitten (Ausgabelimit erreicht)."
        try:
            retry_tokens = runs.budget.max_tokens_for(model, input_tokens=2000, wanted=MAX_TOKENS_RETRY,
                                                      minimum=max_tokens + 1, cache_write=False,
                                                      what="Die Wiederholung mit längerer Antwort")
        except BudgetExceeded as exc:
            raise ExtractionFailed("Die Antwort von Claude wurde abgeschnitten (zu lang). Bitte weniger Seiten oder "
                                   "ein höheres Kostenlimit wählen.") from exc
        _log(ctx, "Antwort zu lang – neuer Versuch mit größerem Ausgabelimit …", "warn")
        request = dataclasses.replace(request, max_tokens=retry_tokens)
        progress.restart()
        response = _call(client, request, ctx, progress)
        run = runs.add(response, request)
        _checked(response, run)
        if response.stop_reason == "max_tokens":
            run.error = "Antwort abgeschnitten (Ausgabelimit erreicht)."
            raise ExtractionFailed("Die Antwort von Claude wurde abgeschnitten (zu lang). Bitte weniger Seiten wählen.")
    return _Pass(kind=kind, pages=list(pages), request=request, response=response, runs=runs.items[first:])


def _vision_pages(kind: PassKind, data: ExtractionData, issues: Sequence[Issue], pass_pages: Sequence[int],
                  infos: Sequence[PageInfo]) -> list[int]:
    """Pages of a pass to render for its verification turn (affected items first, then drawings)."""
    wanted: list[int] = []

    def add(pages: Sequence[int]) -> None:
        for p in pages:
            if p in pass_pages and p not in wanted:
                wanted.append(p)

    affected = {i.package for i in issues if i.package}
    if kind == "identity":
        for dev in data.devices:
            for table in dev.pin_tables:
                if not affected or table.package in affected:
                    add(table.pages)
    else:
        for pkg in data.packages:
            if not affected or pkg.code in affected:
                add(pkg.pages)
                add(pkg.land_pattern.pages)
    by_page = {i.page: i for i in infos}
    add([p for p in pass_pages if by_page.get(p) is not None
         and (by_page[p].quality != "ok" or "drawing" in by_page[p].categories)])
    if not wanted:
        add([p for p in pass_pages if p != 1] or list(pass_pages))
    return wanted[:MAX_VISION_IMAGES]


def _verify(client: LlmClient, done: _Pass, issues: Sequence[Issue], data: ExtractionData, infos: Sequence[PageInfo],
            path: Path, runs: _Runs, ctx: JobContext | None, progress: _Progress) -> _Pass | None:
    pages = _vision_pages(done.kind, data, issues, done.pages, infos)
    if not pages:
        return None
    content: list[dict[str, Any]] = []
    image_tokens = 0
    numbers: list[int] = []
    for real in pages:
        png, size = pdfio.render_page(path, real, dpi=VISION_DPI, mode="gray", max_edge=pdfio.VISION_MAX_EDGE,
                                      max_visual_tokens=pdfio.VISION_MAX_TOKENS)
        image_tokens += pdfio.visual_tokens(size)
        number = done.pages.index(real) + 1
        numbers.append(number)
        content.append({"type": "text", "text": f"Render of attached-PDF page {number}:"})
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": _b64(png)}})
    content[-1]["cache_control"] = {"type": "ephemeral"}
    content.append({"type": "text", "text": verification_instruction([i.message for i in issues], numbers)})
    messages = [*done.request.messages, {"role": "assistant", "content": done.response.assistant_content()},
                {"role": "user", "content": content}]
    new_tokens = image_tokens + done.response.usage.output_tokens + 800  # the PDF prefix is a cache read
    max_tokens = runs.budget.max_tokens_for(done.request.model, input_tokens=new_tokens,
                                            wanted=done.request.max_tokens, minimum=3000,
                                            what="Die Kontrolle mit Seitenbildern")
    kind: RunKind = "verify_identity" if done.kind == "identity" else "verify_geometry"
    request = dataclasses.replace(done.request, kind=kind, messages=messages, max_tokens=max_tokens, pages=pages)
    what = "Pintabellen" if done.kind == "identity" else "Gehäusezeichnungen"
    _detail(ctx, pages_active=list(pages))
    _log(ctx, f"Kontrolle der {what} mit hochaufgelösten Seitenbildern (Seiten {_pages_text(pages)}) …")
    first = len(runs.items)
    response = _call(client, request, ctx, progress)
    runs.add(response, request)
    return _Pass(kind=done.kind, pages=done.pages, request=request, response=response, runs=runs.items[first:])


def _score(data: ExtractionData, codes: frozenset[str]) -> tuple[int, int]:
    errors = sum(1 for i in data.issues if i.severity == "error" and i.code in codes)
    warnings = sum(1 for i in data.issues if i.vision and i.severity == "warning" and i.code in codes)
    return errors, warnings


def _item_scores(data: ExtractionData, codes: frozenset[str]) -> dict[tuple[str, str], tuple[int, int]]:
    """(errors, re-checkable warnings) per item (device, package) of the checks a pass can influence."""
    scores: dict[tuple[str, str], list[int]] = {}
    for issue in data.issues:
        if issue.code not in codes:
            continue
        if issue.severity == "error":
            index = 0
        elif issue.severity == "warning" and issue.vision:
            index = 1
        else:
            continue
        scores.setdefault((issue.device or "", issue.package or ""), [0, 0])[index] += 1
    return {key: (value[0], value[1]) for key, value in scores.items()}


def _combine(identity: AiIdentity, geometry: AiGeometry, verified: AiIdentity | AiGeometry, scope: Scope,
             keep: Scope | None = None) -> tuple[AiIdentity, AiGeometry, list[str]]:
    """Both answers with the verification merged into the pass it belongs to."""
    if isinstance(verified, AiIdentity):
        merged_identity, notes = merge_identity(identity, verified, scope, keep)
        return merged_identity, geometry, notes
    merged_geometry, notes = merge_geometry(geometry, verified, scope, keep)
    return identity, merged_geometry, notes


def _regressions(before: ExtractionData, after: ExtractionData, codes: frozenset[str]) -> list[Issue]:
    """Items whose checks got worse through a merged verification (as issues naming device/package)."""
    old, new = _item_scores(before, codes), _item_scores(after, codes)
    return [Issue(severity="error", code="regression", message="", device=device or None, package=package or None)
            for (device, package), score in new.items() if score > old.get((device, package), (0, 0))]


Normalizer = Callable[[AiIdentity, AiGeometry], ExtractionData]


def apply_verification(identity: AiIdentity, geometry: AiGeometry, data: ExtractionData,
                       verified: AiIdentity | AiGeometry, issues: Sequence[Issue], codes: frozenset[str],
                       normalize: Normalizer) -> tuple[AiIdentity, AiGeometry, ExtractionData, list[str]] | None:
    """Merge a verification answer (:mod:`.merge`, scope = the items of ``issues``), keep the first answer for every
    item whose checks got worse and return ``(identity, geometry, normalised data, notes)`` – or ``None`` when the
    result is still worse than before (``data``)."""
    scope = scope_from_issues(issues)
    new_identity, new_geometry, notes = _combine(identity, geometry, verified, scope)
    candidate = normalize(new_identity, new_geometry)
    worse = _regressions(data, candidate, codes)
    if worse:
        new_identity, new_geometry, notes = _combine(identity, geometry, verified, scope, scope_from_issues(worse))
        candidate = normalize(new_identity, new_geometry)
    if _score(candidate, codes) > _score(data, codes):
        return None
    return new_identity, new_geometry, candidate, notes


# --------------------------------------------------------------------------- main entry


def _failure_text(exc: BaseException) -> str:
    if isinstance(exc, JobCancelled):
        return "Analyse abgebrochen."
    if isinstance(exc, DatasheetError):
        return str(exc)
    return f"Unerwarteter Fehler bei der Analyse ({type(exc).__name__})."


def _keep(ws: Workspace, result: PendingResult) -> tuple[Any, Path | None]:
    """Save ``result`` into the record of its library – or, when that library is no longer open, keep it in the
    library's folder. Returns ``(record or None, kept file or None)``."""
    try:
        with library_hold(None, ws.root):
            rec = store.get_record(result.datasheet_id)
            return store.apply_result(rec, result), None
    except LibraryChanged:
        return None, store.save_pending(ws, result)


def _persist_failure(datasheet_id: str, ws: Workspace, runs: _Runs, exc: BaseException,
                     ctx: JobContext | None = None) -> None:
    """Store the paid calls, their costs and the reason of a failed analysis – in the library it ran for, or kept in
    its folder when that library is no longer open (only when there were paid calls)."""
    if isinstance(exc, LibraryChanged) and not runs.items:
        return  # the library was gone before the first paid call: nothing to keep
    result = PendingResult(datasheet_id=datasheet_id, created=store.now_iso(), kind="failure", runs=list(runs.items),
                           last_error=_failure_text(exc))
    try:
        try:
            with library_hold(None, ws.root):
                rec = store.get_record(datasheet_id)
                store.apply_result(rec, result)
        except LibraryChanged:
            if not runs.items:
                return
            path = store.save_pending(ws, result)
            _log(ctx, f"Die Bibliothek „{ws.root.name}“ ist nicht mehr geöffnet – die Kosten der Analyse wurden in ihrem "
                      f"Ordner gesichert ({path.name}) und erscheinen, sobald sie wieder geöffnet wird.", "warn")
    except Exception:  # noqa: BLE001 - never hide the original error
        log.exception("Kosten der fehlgeschlagenen Analyse von %s konnten nicht gespeichert werden", datasheet_id)
        return
    if runs.items:
        log.info("Fehlgeschlagene Analyse von %s: %d Anfrage(n), %.4f USD gespeichert", datasheet_id, len(runs.items),
                 sum(r.cost_usd for r in runs.items))


def run_extraction(
    ctx: JobContext | None,
    datasheet_id: str,
    options: ExtractOptions | None = None,
    *,
    ws: Workspace | None = None,
    client: LlmClient | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Job function: analyse the datasheet with Claude and store the normalised result (see the module docstring for
    the library guard and the progress details)."""
    options = options or ExtractOptions()
    ws = ws or current()
    settings = ai_enabled_or_raise(settings)
    budget = Budget(limit_usd=min(options.max_cost_usd or settings.ai.max_cost_per_import_usd, HARD_BUDGET_CAP))
    runs = _Runs(budget, ctx=ctx)
    announce_steps(ctx, EXTRACTION_STEPS)
    _detail(ctx, datasheet_id=datasheet_id, budget_usd=round(budget.limit_usd, 4), cost_usd=0.0)
    try:
        client = client or get_client(settings, datasheet_id=datasheet_id)
        return _extract(ctx, datasheet_id, options, ws=ws, client=client, settings=settings, runs=runs)
    except BaseException as exc:
        if isinstance(exc, RequestCancelled) and exc.partial is not None:  # the request that ran when cancelled
            runs.add(exc.partial, exc.request).error = CANCELLED_RUN_ERROR
        _persist_failure(datasheet_id, ws, runs, exc, ctx)
        if ctx is not None:
            spent = sum(r.cost_usd for r in runs.items)
            if runs.items:
                ctx.log(f"Bisherige Kosten dieses Imports gespeichert: {spent:.3f} USD "
                        f"({len(runs.items)} Anfrage(n)).", "warn")
            if isinstance(exc, LibraryChanged) and not runs.items:
                ctx.log(f"{exc} Die Analyse wurde nicht gestartet, es sind keine Kosten entstanden.", "warn")
        raise  # the job's final message is the error text (partforge.jobs)


def _extract(ctx: JobContext | None, datasheet_id: str, options: ExtractOptions, *, ws: Workspace,
             client: LlmClient, settings: AppSettings, runs: _Runs) -> dict[str, Any]:
    started = time.perf_counter()
    model = options.model or settings.ai.model.strip()
    effort = options.effort or settings.ai.effort
    pass_effort = effort if supports_effort(model) else None
    run_label = labels.run_label(model, pass_effort)
    _detail(ctx, model_label=run_label)

    # 1. read the PDF (no database), then hold the library briefly: record, page analysis, categories
    _step(ctx, 0.02, "read", "Datenblatt wird gelesen …")
    with library_hold(None, ws.root):
        rec = store.get_record(datasheet_id)
    store.read_texts(rec, ws=ws, progress=_progress_hook(ctx))
    with library_hold(None, ws.root):
        rec = store.get_record(datasheet_id)
        rec, texts = store.analyze(rec, ws=ws)
        analysed = store.load_meta(rec)
        cats = db_categories.list_categories(with_counts=False)
    infos = analysed.pages
    path = store.pdf_path(rec, ws)
    no_text = [i.page for i in infos if i.quality != "ok"]
    _detail(ctx, pages_total=rec.page_count)
    _log(ctx, f"Datenblatt „{rec.original_name}“: {plural(rec.page_count, 'Seite', 'Seiten')}"
         + (f", ohne lesbare Textebene: {_pages_text(no_text)} (Claude liest sie als Bild)" if no_text else ""))
    if pass_effort is None:
        _log(ctx, f"Das Modell {labels.model_label(model)} lässt keine Gründlichkeit wählen – Anfrage mit der "
                  "Standardeinstellung des Modells.", "warn")

    # 2. page selection (+ triage with the fast model)
    _step(ctx, 0.06, "select_pages", "Seiten werden ausgewählt …")
    selection = select_pages(infos, max_pages=options.max_pages, forced=options.pages)
    if selection.dropped:
        _log(ctx, f"Seiten {_pages_text(selection.dropped)} nicht übernommen (gibt es im Datenblatt nicht oder mehr "
                  f"als {MANUAL_PAGE_LIMIT} Seiten gewählt).", "warn")
    if not selection.pages:
        raise DatasheetError("Keine Seiten für die Analyse ausgewählt.")
    if selection.method == "scan":
        _log(ctx, f"Das Datenblatt hat (fast) keine Textebene – es werden die Seiten {_pages_text(selection.pages)} als "
                  "Bild gelesen. Fehlen danach Angaben, bitte die Seiten mit Pinbelegung und Gehäusezeichnung manuell "
                  "wählen.", "warn")
    if not options.pages and (options.triage == "on" or (options.triage == "auto" and needs_triage(infos, selection))):
        try:
            extra = _triage(client, texts, settings, runs, ctx)
            selection = select_pages(infos, max_pages=options.max_pages, extra=extra)
        except (ExtractionFailed, BudgetExceeded) as exc:
            _log(ctx, f"Seiten-Vorauswahl übersprungen: {exc}", "warn")
    identity_pages, geometry_pages = split_pages(selection, rec.page_count)
    _detail(ctx, pages_selected=list(selection.pages))
    _log(ctx, f"Seitenauswahl: {_pages_text(selection.pages)} ({len(selection.pages)} von {rec.page_count} Seiten, "
              f"{selection.method}); Bauteile/Pins: {_pages_text(identity_pages)}, "
              f"Gehäuse: {_pages_text(geometry_pages)}")

    # 3. pass 1: identity and pins
    pages_label = plural(len(identity_pages), "Seite", "Seiten")
    _step(ctx, 0.1, "identity", f"Claude liest Bauteile und Pins ({pages_label}) …", pages_active=list(identity_pages))
    _log(ctx, f"{run_label} liest Bauteile und Pins ({pages_label}) …")
    first = _run_pass(client, "identity", pages=identity_pages, path=path, total_pages=rec.page_count,
                      instruction=identity_instruction(cats, page_count=len(identity_pages),
                                                       total_pages=rec.page_count),
                      model=model, effort=pass_effort, fallbacks=settings.ai.use_fallbacks, runs=runs, infos=infos,
                      ctx=ctx, progress=_Progress(ctx, 0.1, 0.35, "Claude liest Bauteile und Pins"),
                      encrypted=analysed.encrypted)
    identity = _parse_answer(parse_identity, first.response, first.runs[-1])
    refs = [(r.package_code, r.package_name, r.pin_count) for r in identity.packages]
    identity_counters = {
        "mpns": sum(len(d.variants) for d in identity.devices),
        "pins": sum(len(t.pins) for d in identity.devices for t in d.pin_tables),
        "parameters": sum(len(d.parameters) + sum(len(v.values) for v in d.variants) for d in identity.devices),
        "packages": len(identity.packages),
    }
    _detail(ctx, counters=identity_counters)
    _log(ctx, f"Bauteile: {', '.join(d.base_part_number for d in identity.devices) or 'keine'}; "
              f"Gehäuse: {', '.join(f'{c} ({n})' for c, n, _ in refs) or 'keine'} "
              f"({first.response.duration_s:.0f} s, {sum(r.cost_usd for r in first.runs):.3f} USD)", "success")

    # 4. pass 2: package geometry
    pages_label = plural(len(geometry_pages), "Seite", "Seiten")
    _step(ctx, 0.45, "geometry", f"Claude liest die Gehäusemaße ({pages_label}) …", pages_active=list(geometry_pages))
    _log(ctx, f"{run_label} liest die Gehäusemaße ({pages_label}) …")
    second = _run_pass(client, "geometry", pages=geometry_pages, path=path, total_pages=rec.page_count,
                       instruction=geometry_instruction(refs, page_count=len(geometry_pages),
                                                        total_pages=rec.page_count),
                       model=model, effort=pass_effort, fallbacks=settings.ai.use_fallbacks, runs=runs, infos=infos,
                       ctx=ctx, progress=_Progress(ctx, 0.45, 0.27, "Claude liest die Gehäusemaße",
                                                   base=identity_counters),
                       encrypted=analysed.encrypted)
    geometry = _parse_answer(parse_geometry, second.response, second.runs[-1])

    # 5. normalisation, checks and the optional verification with page renders
    def merged(ident: AiIdentity, geo: AiGeometry) -> ExtractionData:
        return normalize_extraction(ident, geo, pages=identity_pages, geometry_pages=geometry_pages,
                                    categories=cats, ws_root=ws.root)

    _step(ctx, 0.72, "check", "Ergebnis wird geprüft …", pages_active=[])
    data = merged(identity, geometry)
    counts = issue_summary(data.issues)
    _detail(ctx, counters=counters_of(data))
    _log(ctx, f"Antwort vollständig: {_describe(data)}", "success")
    _log(ctx, f"Prüfung: {counts['error']} Fehler, {counts['warning']} Warnungen, {counts['info']} Hinweise")

    # verification with high-resolution renders (per pass); never fatal, never loses data
    vision_used = False
    for done, codes in ((first, IDENTITY_ISSUES), (second, GEOMETRY_ISSUES)):
        issues = [i for i in data.issues if i.vision and i.code in codes and i.severity in ("error", "warning")]
        if not (options.vision == "on" or (options.vision == "auto" and issues)):
            continue
        start = 0.75 if done.kind == "identity" else 0.85
        _step(ctx, start, "check", "Kontrolle mit Seitenbildern …")
        try:
            checked = _verify(client, done, issues, data, infos, path, runs, ctx,
                              _Progress(ctx, start, 0.1, "Claude prüft die Seitenbilder", base=counters_of(data)))
        except DatasheetError as exc:  # budget, network, overload, unreadable page …
            _log(ctx, f"Kontrolle mit Seitenbildern nicht möglich: {exc} – das Ergebnis ohne Kontrolle wird verwendet.",
                 "warn")
            continue
        if checked is None:
            continue
        vision_used = True
        run = checked.runs[-1]
        try:
            _checked(checked.response, run)
            if checked.response.stop_reason == "max_tokens":
                run.error = "Die Kontrollantwort wurde abgeschnitten."
                raise ExtractionFailed(run.error)
            verified: AiIdentity | AiGeometry = (_parse_answer(parse_identity, checked.response, run)
                                                 if done.kind == "identity"
                                                 else _parse_answer(parse_geometry, checked.response, run))
            outcome = apply_verification(identity, geometry, data, verified, issues, codes, merged)
        except ExtractionFailed as exc:
            _log(ctx, f"Kontrolle nicht verwertbar ({exc}) – vorheriges Ergebnis wird verwendet.", "warn")
            continue
        if outcome is None:
            _log(ctx, "Die Kontrolle brachte keine Verbesserung – vorheriges Ergebnis wird verwendet.", "warn")
            continue
        identity, geometry, data, notes = outcome
        counts = issue_summary(data.issues)
        _detail(ctx, counters=counters_of(data))
        for note in notes:
            _log(ctx, note)
        _log(ctx, f"Nach der Kontrolle: {_describe(data)}; {counts['error']} Fehler, {counts['warning']} Warnungen",
             "success")

    # 6. save – into the library the job was started for, or kept in its folder when it is closed meanwhile
    _step(ctx, 0.96, "save", "Ergebnis wird gespeichert …", pages_active=[])
    title = None
    if data.devices and data.devices[0].description:
        title = f"{data.devices[0].base_part} – {data.devices[0].description}"
    now = store.now_iso()
    result = PendingResult(
        datasheet_id=rec.id, created=now, kind="extraction", runs=list(runs.items), extraction=data,
        raw={"identity": identity.model_dump(mode="json"), "geometry": geometry.model_dump(mode="json")},
        model=model, effort=pass_effort or "", extracted=now, selected_pages=list(selection.pages),
        selection_method=selection.method, identity_pages=list(identity_pages), geometry_pages=list(geometry_pages),
        manufacturer=data.manufacturer or None, mpns=data.mpns(), title=title,
    )
    saved, kept = _keep(ws, result)
    duration = time.perf_counter() - started
    cost = round(runs.budget.spent_usd, 6)
    if saved is not None:
        meta: DatasheetMeta = store.load_meta(saved)
        total = f"; insgesamt für dieses Datenblatt {meta.cost_usd:.3f} USD" if meta.cost_usd > cost + 1e-6 else ""
        _log(ctx, f"Ergebnis gespeichert. Kosten dieses Imports: {cost:.3f} USD ({len(runs.items)} Anfragen, "
                  f"{duration:.0f} s){total}", "success")
    else:
        _log(ctx, f"Die Bibliothek „{ws.root.name}“ ist nicht mehr geöffnet – das Ergebnis wurde in ihrem Ordner "
                  f"gesichert ({kept.name if kept else ''}) und erscheint, sobald sie wieder geöffnet wird. Kosten "
                  f"dieses Imports: {cost:.3f} USD.", "warn")
    message = outcome_message(data, cost, pending_library=None if saved is not None else ws.root.name)
    if ctx is not None:
        ctx.progress(1.0, message)
    summary = ExtractionSummary(
        datasheet_id=rec.id, model=model, served_model=second.response.model, effort=pass_effort or "",
        pages=list(selection.pages), identity_pages=list(identity_pages), geometry_pages=list(geometry_pages),
        selection_method=selection.method, devices=[d.base_part for d in data.devices], mpns=len(data.mpns()),
        packages=[p.label for p in data.packages], pins=sum(len(t.pins) for d in data.devices for t in d.pin_tables),
        issues=dict(issue_summary(data.issues)), vision=vision_used, cost_usd=cost, duration_s=round(duration, 1),
        model_label=run_label, stored="library" if saved is not None else "pending", message=message,
    )
    return summary.model_dump(mode="json")


def outcome_message(data: ExtractionData, cost_usd: float, *, pending_library: str | None = None) -> str:
    """"Analyse fertig: 14 Bestellvarianten, 13 Pins, 2 Gehäuse – 0,23 $" (+ where a kept result waits)."""
    pins = sum(len(t.pins) for d in data.devices for t in d.pin_tables)
    text = (f"Analyse fertig: {plural(len(data.mpns()), 'Bestellvariante', 'Bestellvarianten')}, "
            f"{plural(pins, 'Pin', 'Pins')}, {plural(len(data.packages), 'Gehäuse', 'Gehäuse')} – {labels.usd(cost_usd)}")
    if pending_library:
        text += f" – gesichert für die Bibliothek „{pending_library}“ (erscheint beim nächsten Öffnen)"
    return text


def _describe(data: ExtractionData) -> str:
    devices = len(data.devices)
    mpns = len(data.mpns())
    pins = sum(len(t.pins) for d in data.devices for t in d.pin_tables)
    dims = sum(len(p.dimensions) for p in data.packages)
    return (f"{data.manufacturer or 'Hersteller unbekannt'}, {devices} Bauteil{'e' if devices != 1 else ''}, "
            f"{mpns} Bestellnummern, {pins} Pins, {len(data.packages)} Gehäuse mit {dims} Maßen")


def store_edited_extraction(datasheet_id: str, data: ExtractionData, *, ws: Workspace | None = None) -> ExtractionData:
    """Save a user-corrected extraction: the same text hygiene as Claude's answers (no ``|``/control characters,
    overbar pin names, field values normalised), re-validated; the original answers of Claude stay in ``raw``."""
    from .normalize import sanitize_extraction

    ws = ws or current()
    store.get_record(datasheet_id)  # 404 before the work
    clean = sanitize_extraction(data, categories=db_categories.list_categories(with_counts=False), ws_root=ws.root)

    def change(rec: Any, meta: DatasheetMeta) -> dict[str, Any]:
        meta.extraction = clean
        meta.edited = True
        return {"manufacturer": clean.manufacturer or rec.manufacturer, "mpns": clean.mpns() or rec.mpns}

    store.update_meta(datasheet_id, change)
    return clean
