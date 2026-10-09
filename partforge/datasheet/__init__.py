"""Datasheet import with Claude (ARCHITEKTUR.md §10).

Public API::

    # storage (partforge.datasheet.store)
    ingest_bytes(data, filename, *, source_url=None, ws=None) -> (DatasheetRecord, duplicate)
    download_pdf(url, *, max_bytes=..., transport=None) -> (bytes, file name, final URL)
    read_texts(rec, *, ws=None) -> PdfInfo                                    # text layer, cached, no database
    analyze(rec, *, ws=None, force=False) -> (DatasheetRecord, page texts)    # text layer: ok/empty/glyph
    page_png(rec, page, dpi=None) -> Path                                     # cached render (36–300 dpi)
    delete_datasheet(datasheet_id, *, delete_file=True) -> dict
    save_pending(ws, PendingResult) / apply_pending(ws) -> ids                # results of a closed library

    # extraction (partforge.datasheet.extract) – job function; paid calls are stored even when it fails
    run_extraction(ctx, datasheet_id, options: ExtractOptions | None, *, ws=None, client=None) -> dict
        # holds the library only for its short database phases; a result whose library was closed meanwhile is
        # kept in that library's folder; job.detail: step, step_label, pages_*, counters, cost_usd, model_label
    store_edited_extraction(datasheet_id, data, *, ws=None) -> ExtractionData   # user edits, same text hygiene

    # cost estimate (partforge.datasheet.estimate) – no Claude call
    estimate(rec, pages, options) -> CostEstimate      # pages, est_input_tokens, est_cost_usd_low/high, model_label

    # proposal / commit (partforge.datasheet.proposal)
    build_proposal(datasheet_id, choices: ProposalChoices | None) -> PartProposal   # .blockers, .ready, .fingerprint
    commit_proposal(ctx, datasheet_id, choices, *, ws=None, author=None) -> dict   # job function
        # refuses unconfirmed blockers (choices.accept_issues = confirmed texts) and a changed plan
        # (choices.expected_fingerprint); a changed pin-out of a registered symbol only with
        # choices.allow_pin_changes (True or symbol names; else a free symbol name); parts whose symbol/footprint
        # was not written are not created (result["errors"])

    # datasheet search (partforge.datasheet.find) – job function "datasheet-find"
    run_find(ctx, FindRequest(query, manufacturer)) -> dict   # FindResult: checked candidates, cost
    # its paid calls (also of failed/cancelled searches) persist in the ledger (partforge.datasheet.search_costs)
    search_costs.record(SearchCost) / get(job_id) / claim(job_id, datasheet_id) -> SearchCost | None

    # Claude client (partforge.datasheet.llm, partforge.datasheet.replay)
    get_client(settings=None, *, datasheet_id=None, search=None) -> LlmClient; set_client_factory(factory)
    key_status(settings) -> (configured, source)               # source "replay" in the replay mode
    # PARTFORGE_AI_REPLAY_DIR (+ PARTFORGE_HOME): recorded answers instead of the API, never a network call

Data flow: PDF -> ``Datasheets/<name>_<sha8>.pdf`` + ``pf_datasheets`` record -> text-layer analysis ->
page selection -> Claude (PDF subset, structured output, optional verification with 200 dpi renders, merged per
item without losing data) -> normalised :class:`~.models.ExtractionData` (stored in the record) ->
:class:`~.models.PartProposal` -> symbols/footprints via ``partforge.altium.sync`` + rows via
``partforge.db.parts.upsert_parts``.

Importing this package has no side effects (pypdf, pypdfium2 and the Anthropic SDK load lazily).
"""
from __future__ import annotations

from .errors import (
    AiUnavailable,
    BudgetExceeded,
    CommitRefused,
    DatasheetError,
    DatasheetNotFound,
    ExtractionFailed,
    InvalidPdf,
    NoExtraction,
)
from .extract import ExtractOptions, run_extraction, store_edited_extraction
from .llm import LlmClient, LlmRequest, LlmResponse, ReplayLlmClient, get_client, key_status, set_client_factory
from .models import (
    DatasheetMeta,
    ExtractionData,
    FootprintProposal,
    PageInfo,
    PartProposal,
    PendingResult,
    ProposalChoices,
    SymbolProposal,
    VariantProposal,
)
from .proposal import build_proposal, commit_proposal
from .store import analyze, apply_pending, delete_datasheet, download_pdf, ingest_bytes, page_png, read_texts, save_pending

__all__ = [
    "AiUnavailable",
    "BudgetExceeded",
    "CommitRefused",
    "DatasheetError",
    "DatasheetMeta",
    "DatasheetNotFound",
    "ExtractOptions",
    "ExtractionData",
    "ExtractionFailed",
    "FootprintProposal",
    "InvalidPdf",
    "LlmClient",
    "LlmRequest",
    "LlmResponse",
    "NoExtraction",
    "PageInfo",
    "PartProposal",
    "PendingResult",
    "ProposalChoices",
    "ReplayLlmClient",
    "SymbolProposal",
    "VariantProposal",
    "analyze",
    "apply_pending",
    "build_proposal",
    "commit_proposal",
    "delete_datasheet",
    "download_pdf",
    "get_client",
    "ingest_bytes",
    "key_status",
    "page_png",
    "read_texts",
    "run_extraction",
    "save_pending",
    "set_client_factory",
    "store_edited_extraction",
]
