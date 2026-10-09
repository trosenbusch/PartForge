"""Cost estimate of an analysis before it runs – no Claude call (``POST /api/datasheets/{id}/estimate``).

The same page selection as :func:`.extract.run_extraction` (user pages or the heuristic; whether the page triage
would run), split into the two passes, the measured tokens per text/drawing page
(:func:`.costs.estimate_pdf_tokens`) and the model's prices (:func:`.costs.estimate_import`): a low estimate
(typical answers) and a high one (long answers plus a verification turn with page renders).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..config import AppSettings, load_settings
from ..db.models import DatasheetRecord
from . import labels
from .costs import estimate_import
from .extract import HARD_BUDGET_CAP, ExtractOptions, split_pages
from .llm import supports_effort
from .models import PageInfo
from .pages import needs_triage, select_pages

__all__ = ["CostEstimate", "estimate"]


class CostEstimate(BaseModel):
    datasheet_id: str
    pages: list[int] = Field(description="Seiten, die Claude bekäme (Auswahl oder Vorgabe)")
    pages_total: int = 0
    selection_method: str = ""  # heuristic | all | manual | scan | empty
    identity_pages: list[int] = Field(default_factory=list)
    geometry_pages: list[int] = Field(default_factory=list)
    drawing_pages: list[int] = Field(default_factory=list)  # selected pages without usable text layer (read as images)
    triage: bool = False  # the page triage with the fast model would run (included in the estimate)
    est_input_tokens: int = 0
    est_cost_usd_low: float = 0.0
    est_cost_usd_high: float = 0.0
    model: str = ""
    effort: str = ""  # "" = the model takes no effort level
    model_label: str = ""  # "Claude Opus 5.5 · Gründlichkeit niedrig"
    budget_usd: float = 0.0
    exceeds_budget: bool = False  # even the low estimate is above the cost limit


def _split(pages: list[int], drawings: set[int]) -> tuple[int, int]:
    drawn = sum(1 for p in pages if p in drawings)
    return len(pages) - drawn, drawn


def estimate(rec: DatasheetRecord, infos: list[PageInfo], options: ExtractOptions | None = None, *,
             settings: AppSettings | None = None) -> CostEstimate:
    """Estimate the analysis of ``rec`` (``infos`` = its page analysis) with ``options`` (model, effort, pages, …)."""
    options = options or ExtractOptions()
    settings = settings or load_settings()
    model = options.model or settings.ai.model.strip()
    effort = (options.effort or settings.ai.effort) if supports_effort(model) else None
    selection = select_pages(infos, max_pages=options.max_pages, forced=options.pages)
    triage = not options.pages and (options.triage == "on" or (options.triage == "auto"
                                                               and needs_triage(infos, selection)))
    identity, geometry = split_pages(selection, rec.page_count) if selection.pages else ([], [])
    drawings = {i.page for i in infos if i.quality != "ok"}
    budget = min(options.max_cost_usd or settings.ai.max_cost_per_import_usd, HARD_BUDGET_CAP)
    out = CostEstimate(
        datasheet_id=rec.id, pages=list(selection.pages), pages_total=len(infos) or rec.page_count,
        selection_method=selection.method, identity_pages=list(identity), geometry_pages=list(geometry),
        drawing_pages=[p for p in selection.pages if p in drawings], triage=bool(triage), model=model,
        effort=effort or "", model_label=labels.run_label(model, effort), budget_usd=round(budget, 4),
    )
    if not selection.pages:
        return out
    est = estimate_import(model, identity=_split(identity, drawings), geometry=_split(geometry, drawings),
                          triage_pages=len(infos) if triage else 0, fast_model=settings.ai.fast_model,
                          verification=options.vision != "off")
    out.est_input_tokens = est.input_tokens
    out.est_cost_usd_low, out.est_cost_usd_high = est.low_usd, est.high_usd
    out.exceeds_budget = est.low_usd > budget
    return out
