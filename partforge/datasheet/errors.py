"""Exceptions of the datasheet import (all messages are German and user-facing).

The API maps them to HTTP status codes (see :mod:`partforge.api.routes_datasheets`):

* :class:`DatasheetNotFound`  -> 404
* :class:`AiUnavailable`      -> 503 with ``detail = {"code": AiUnavailable.code, "message": …}`` (no key, AI
  disabled, key rejected, model not available, network, rate limit, service overloaded)
* :class:`BudgetExceeded`     -> 400 (the import would exceed ``AISettings.max_cost_per_import_usd``)
* every other :class:`DatasheetError` -> 400
"""
from __future__ import annotations

from typing import Literal

__all__ = [
    "AI_ERROR_CODES",
    "AiErrorCode",
    "AiUnavailable",
    "BudgetExceeded",
    "CommitRefused",
    "DatasheetError",
    "DatasheetNotFound",
    "ExtractionFailed",
    "InvalidPdf",
    "NoExtraction",
]

AiErrorCode = Literal["key_missing", "key_rejected", "model_unavailable", "network", "rate_limited", "ai_disabled",
                      "unknown"]
#: Machine-readable reasons of :class:`AiUnavailable` (``detail.code`` of the API, e.g. ``POST /api/ai/test``).
AI_ERROR_CODES: tuple[str, ...] = ("key_missing", "key_rejected", "model_unavailable", "network", "rate_limited",
                                   "ai_disabled", "unknown")


class DatasheetError(ValueError):
    """Base class: a business error with a German message (HTTP 400)."""


class DatasheetNotFound(DatasheetError):
    """Unknown datasheet id (HTTP 404)."""

    def __init__(self, datasheet_id: str) -> None:
        super().__init__(f"Datenblatt „{datasheet_id}“ nicht gefunden.")
        self.datasheet_id = datasheet_id


class InvalidPdf(DatasheetError):
    """The file is not a readable PDF (damaged, password protected, not a PDF at all)."""


class NoExtraction(DatasheetError):
    """A proposal was requested before the datasheet was analysed."""

    def __init__(self, datasheet_id: str) -> None:
        super().__init__(
            f"Für das Datenblatt „{datasheet_id}“ liegt noch keine KI-Analyse vor – bitte zuerst „Analysieren“ starten."
        )
        self.datasheet_id = datasheet_id


class AiUnavailable(DatasheetError):
    """The Claude API cannot be used right now (HTTP 503).

    ``code`` (one of :data:`AI_ERROR_CODES`) lets the UI show the right state without parsing the text:
    ``key_missing`` · ``key_rejected`` · ``model_unavailable`` · ``network`` (no connection, timeout, service
    overloaded or disturbed) · ``rate_limited`` · ``ai_disabled`` · ``unknown``."""

    def __init__(self, message: str, code: AiErrorCode | str = "unknown") -> None:
        super().__init__(message)
        self.code: str = code if code in AI_ERROR_CODES else "unknown"


class BudgetExceeded(DatasheetError):
    """The next API call would exceed the cost limit per import."""


class ExtractionFailed(DatasheetError):
    """Claude answered, but the answer is unusable (refusal, truncated, invalid JSON) – or the API rejected the
    request (``api_status``/``api_message`` keep the HTTP status and the API's text when known)."""

    api_status: int | None = None
    api_message: str = ""


class CommitRefused(DatasheetError):
    """The commit job refused to write anything (unconfirmed blockers, the proposal changed since the review).

    ``code``: ``unconfirmed_blockers`` | ``proposal_changed`` | ``invalid``; ``items``: the blocker texts that were
    not confirmed (``unconfirmed_blockers``)."""

    def __init__(self, message: str, *, code: str, items: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.items = list(items or [])
