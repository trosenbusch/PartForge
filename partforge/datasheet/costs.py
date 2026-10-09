"""Token prices and cost tracking for the datasheet import.

Prices: USD per million tokens, Claude API list prices of 2026-10-07 (research report
docs/entwicklung/recherche/claude-api.md §2.1). Cache writes: 5-minute TTL = 1.25 x input (Opus 5.5:
5.00), 1-hour TTL = 2 x input; cache reads as listed. Claude Haiku 5.5 bills 5x above 100k prompt
tokens. Unknown models are priced like Claude Opus 5 (conservative for the budget guard). Server tools:
web search 10 USD per 1,000 searches (``usage.server_tool_use.web_search_requests``) on top of the tokens.

The budget guard (:class:`Budget`) keeps one import below ``AISettings.max_cost_per_import_usd``:
before each call it checks the estimated input cost and caps ``max_tokens`` so that even a maximal
answer stays within the remaining budget.

:func:`estimate_import` estimates an analysis before it runs (``POST /datasheets/{id}/estimate``): the
measured tokens per text/drawing page (:func:`estimate_pdf_tokens`) for both passes, priced as cache writes,
plus a typical (low) or generous (high: long answers, verification turn with page renders) output.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import BudgetExceeded
from .models import Usage

__all__ = [
    "PRICES",
    "WEB_SEARCH_USD",
    "Budget",
    "ImportEstimate",
    "ModelPrice",
    "estimate_import",
    "estimate_pdf_tokens",
    "price_for",
    "search_input_tokens",
    "server_tool_cost",
    "usage_cost",
    "usage_from_sdk",
]

#: Price of one web search (10 USD per 1,000 searches, plus the tokens of the results).
WEB_SEARCH_USD = 10.0 / 1000


@dataclass(frozen=True)
class ModelPrice:
    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float
    long_context_threshold: int | None = None  # prompt tokens above which ``long`` applies
    long: tuple[float, float, float, float, float] | None = None  # same order as the fields above


PRICES: dict[str, ModelPrice] = {
    "claude-opus-5-5": ModelPrice(4.00, 5.00, 8.00, 0.20, 20.00),
    "claude-sonnet-5-5": ModelPrice(2.00, 2.50, 4.00, 0.20, 10.00),
    "claude-haiku-5-5": ModelPrice(0.10, 0.125, 0.20, 0.01, 0.50,
                                   long_context_threshold=100_000, long=(0.50, 0.625, 1.00, 0.05, 2.50)),
    "claude-fable-5-1": ModelPrice(10.00, 12.50, 20.00, 0.25, 50.00),
    "claude-fable-5": ModelPrice(10.00, 12.50, 20.00, 1.00, 50.00),
    "claude-opus-5": ModelPrice(5.00, 6.25, 10.00, 0.50, 25.00),
    "claude-opus-4-8": ModelPrice(5.00, 6.25, 10.00, 0.50, 25.00),
    "claude-opus-4-7": ModelPrice(5.00, 6.25, 10.00, 0.50, 25.00),
    "claude-opus-4-6": ModelPrice(5.00, 6.25, 10.00, 0.50, 25.00),
    "claude-sonnet-5": ModelPrice(2.00, 2.50, 4.00, 0.20, 10.00),
    "claude-sonnet-4-6": ModelPrice(3.00, 3.75, 6.00, 0.30, 15.00),
    "claude-haiku-4-5": ModelPrice(1.00, 1.25, 2.00, 0.10, 5.00),
}
_FALLBACK_PRICE = PRICES["claude-opus-5"]


def price_for(model: str | None) -> ModelPrice:
    """Price of a model id (date-suffixed ids map to their base id)."""
    if not model:
        return _FALLBACK_PRICE
    if model in PRICES:
        return PRICES[model]
    base = model.rsplit("-", 1)[0] if model[-8:].isdigit() else model
    return PRICES.get(base, _FALLBACK_PRICE)


def _rates(price: ModelPrice, prompt_tokens: int) -> tuple[float, float, float, float, float]:
    if price.long is not None and price.long_context_threshold is not None and prompt_tokens > price.long_context_threshold:
        return price.long
    return price.input, price.cache_write_5m, price.cache_write_1h, price.cache_read, price.output


def usage_cost(model: str | None, usage: Usage | Mapping[str, Any], *, cache_write_1h_tokens: int = 0) -> float:
    """USD cost of one response."""
    u = usage if isinstance(usage, Usage) else Usage.model_validate(dict(usage))
    prompt = u.input_tokens + u.cache_write_tokens + u.cache_read_tokens
    inp, w5, w1h, read, out = _rates(price_for(model), prompt)
    write_5m = max(0, u.cache_write_tokens - cache_write_1h_tokens)
    total = (u.input_tokens * inp + write_5m * w5 + cache_write_1h_tokens * w1h + u.cache_read_tokens * read
             + u.output_tokens * out)
    return total / 1_000_000


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def usage_from_sdk(usage: Any) -> Usage:
    """:class:`Usage` from an SDK usage object (or dict); missing fields count as 0."""
    if usage is None:
        return Usage()
    get = usage.get if isinstance(usage, Mapping) else lambda key, default=None: getattr(usage, key, default)
    details = get("output_tokens_details", None)
    thinking = 0
    if details is not None:
        thinking = _int(details.get("thinking_tokens") if isinstance(details, Mapping)
                        else getattr(details, "thinking_tokens", 0))
    return Usage(
        input_tokens=_int(get("input_tokens", 0)),
        cache_write_tokens=_int(get("cache_creation_input_tokens", 0)),
        cache_read_tokens=_int(get("cache_read_input_tokens", 0)),
        output_tokens=_int(get("output_tokens", 0)),
        thinking_tokens=thinking,
    )


def server_tool_cost(usage: Any) -> float:
    """Fees of server tools in a usage object/dict (web search: :data:`WEB_SEARCH_USD` per search)."""
    if usage is None:
        return 0.0
    tools = usage.get("server_tool_use") if isinstance(usage, Mapping) else getattr(usage, "server_tool_use", None)
    if tools is None:
        return 0.0
    searches = tools.get("web_search_requests") if isinstance(tools, Mapping) else getattr(
        tools, "web_search_requests", 0)
    return _int(searches) * WEB_SEARCH_USD


def message_cost(message: Any, requested_model: str) -> float:
    """Cost of a final message (tokens and server-tool fees); after a server-side fallback the per-iteration usage
    is priced per model."""
    usage = getattr(message, "usage", None) if not isinstance(message, Mapping) else message.get("usage")
    fees = server_tool_cost(usage)
    iterations = (usage.get("iterations") if isinstance(usage, Mapping) else getattr(usage, "iterations", None)) \
        if usage is not None else None
    if iterations:
        total = 0.0
        for item in iterations:
            model = item.get("model") if isinstance(item, Mapping) else getattr(item, "model", None)
            total += usage_cost(model or requested_model, usage_from_sdk(item))
        if total > 0:
            return total + fees
    served = message.get("model") if isinstance(message, Mapping) else getattr(message, "model", None)
    return usage_cost(served or requested_model, usage_from_sdk(usage)) + fees


# --------------------------------------------------------------------------- estimates and the budget guard

PROMPT_OVERHEAD_TOKENS = 7_000  # system prompt + output schema + instruction with category catalogue
TOKENS_PER_TEXT_PAGE = 2_700  # measured: 2,699 for a text page (incl. the page image)
TOKENS_PER_DRAWING_PAGE = 1_700  # measured: 1,588 for a page without text layer


def estimate_pdf_tokens(text_pages: int, drawing_pages: int) -> int:
    return PROMPT_OVERHEAD_TOKENS + text_pages * TOKENS_PER_TEXT_PAGE + drawing_pages * TOKENS_PER_DRAWING_PAGE


@dataclass
class Budget:
    """Cost limit of one import; ``spent`` grows with every finished call."""

    limit_usd: float
    spent_usd: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, self.limit_usd - self.spent_usd)

    def add(self, cost: float) -> None:
        self.spent_usd += max(0.0, float(cost))

    def max_tokens_for(self, model: str, *, input_tokens: int, wanted: int, minimum: int = 2_000,
                       cache_write: bool = True, what: str = "Die Analyse") -> int:
        """``max_tokens`` that keeps the call within the remaining budget (raises :class:`BudgetExceeded`)."""
        inp, w5, _w1h, _read, out = _rates(price_for(model), input_tokens)
        input_cost = input_tokens * (w5 if cache_write else inp) / 1_000_000
        left = self.remaining - input_cost
        affordable = math.floor(left / out * 1_000_000) if out > 0 else wanted
        if affordable < minimum:
            raise BudgetExceeded(
                f"{what} würde das Kostenlimit von {self.limit_usd:.2f} USD je Import überschreiten "
                f"(bisher {self.spent_usd:.3f} USD, geschätzt mindestens {input_cost + minimum * out / 1e6:.3f} USD "
                "für den nächsten Schritt). Bitte weniger Seiten wählen oder das Limit in den Einstellungen erhöhen."
            )
        return int(min(wanted, affordable))


# --------------------------------------------------------------------------- cost estimate of an analysis

#: Output tokens per pass (identity, geometry) – typical answers of the recorded corpus (1,450–2,400 tokens)
#: for the low estimate, long pin tables / many variants (sn65lv1023a: 10,600) for the high one.
OUTPUT_LOW = (1_500, 1_200)
OUTPUT_HIGH = (12_000, 4_000)
#: One verification turn with the maximum number of 200-dpi renders (6 x 4,784 visual tokens) and its answer.
VERIFY_IMAGE_TOKENS = 6 * 4_784
VERIFY_OUTPUT = 4_000
#: Page triage with the fast model: prompt, digest per page (500 characters ~ 180 tokens), answer.
TRIAGE_PROMPT_TOKENS = 1_500
TRIAGE_TOKENS_PER_PAGE = 180
TRIAGE_OUTPUT = 600


@dataclass(frozen=True)
class ImportEstimate:
    """Estimated input tokens and cost range (USD) of one analysis."""

    input_tokens: int
    low_usd: float
    high_usd: float


def estimate_import(model: str, *, identity: tuple[int, int], geometry: tuple[int, int], triage_pages: int = 0,
                    fast_model: str | None = None, verification: bool = True) -> ImportEstimate:
    """Estimate an analysis from the pages of both passes (``(text pages, drawing pages)`` each).

    Low: both passes with typical answers (+ the page triage when it will run). High: long answers plus one
    verification turn with page renders (unless ``verification`` is off). Inputs are priced as 5-minute cache writes
    (the PDF subsets are cached)."""
    identity_tokens = estimate_pdf_tokens(*identity)
    geometry_tokens = estimate_pdf_tokens(*geometry)
    _inp, write, _w1h, read, out = _rates(price_for(model), max(identity_tokens, geometry_tokens))
    base = (identity_tokens + geometry_tokens) * write
    triage_tokens = TRIAGE_PROMPT_TOKENS + TRIAGE_TOKENS_PER_PAGE * triage_pages if triage_pages else 0
    triage = 0.0
    if triage_tokens:
        t_inp, _t_w5, _t_w1h, _t_read, t_out = _rates(price_for(fast_model or model), triage_tokens)
        triage = triage_tokens * t_inp + TRIAGE_OUTPUT * t_out
    low = base + sum(OUTPUT_LOW) * out + triage
    verify = (VERIFY_IMAGE_TOKENS * write + max(identity_tokens, geometry_tokens) * read + VERIFY_OUTPUT * out
              if verification else 0.0)
    high = base + sum(OUTPUT_HIGH) * out + verify + triage
    return ImportEstimate(input_tokens=identity_tokens + geometry_tokens + triage_tokens,
                          low_usd=round(low / 1_000_000, 4), high_usd=round(high / 1_000_000, 4))


#: Datasheet search (web search tool): prompt with tool definition and schema, tokens of one search's results
#: (conservative: no caching assumed – every server-side iteration re-reads the context).
SEARCH_PROMPT_TOKENS = 2_000
TOKENS_PER_SEARCH = 8_000


def search_input_tokens(searches: int) -> int:
    """Worst-case input tokens of a search turn with ``searches`` web searches (one model iteration per search plus
    the final answer, each reading everything before it)."""
    n = max(0, int(searches))
    return (n + 1) * SEARCH_PROMPT_TOKENS + TOKENS_PER_SEARCH * n * (n + 1) // 2
