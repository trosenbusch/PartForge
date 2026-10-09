"""Claude API access for the datasheet import (the only module that talks to the Anthropic SDK).

* :class:`AnthropicLlmClient` streams every request (long outputs, no HTTP timeouts), uses the
  server-side fallback beta when requested (``fallbacks="default"``, header
  ``server-side-fallback-2026-07-01``) and maps SDK errors to German messages
  (:class:`~.errors.AiUnavailable` / :class:`~.errors.ExtractionFailed`). Connecting is limited to
  :data:`CONNECT_TIMEOUT_S`; reading a stream may take :attr:`LlmRequest.timeout_s` between two chunks.
* **Server-side fallback while streaming** (docs: refusals-and-fallback, "Streaming"): a decline before any output
  is seamless (the ``fallback`` block comes first); a decline in the middle keeps the partial output, marks the
  boundary with a ``fallback`` block and *the fallback model continues from the partial text*. The answer is
  therefore the concatenation of all text blocks (:attr:`LlmResponse.text`); the text after the last boundary
  (:attr:`LlmResponse.tail_text`) is only a second parse candidate. Echoing such a turn keeps the ``fallback``
  block in place and drops the thinking/tool blocks before it (:meth:`LlmResponse.assistant_content`).
* **Server tools** (datasheet search): :attr:`LlmRequest.tools` is sent as ``tools`` (e.g. the web search tool);
  every finished ``server_tool_use`` block is reported through ``on_tool(name, input)`` while streaming.
* :class:`ReplayLlmClient` replays recorded responses (``tests/data/ai_fixtures``) through the very same
  response handling – offline tests and demos run the complete pipeline without network access
  (``delay_s`` slows the stream down so that a UI can be watched).
* :class:`RecordingLlmClient` wraps a client and stores every response as a fixture.
* **Replay mode** (:mod:`.replay`): with ``PARTFORGE_AI_REPLAY_DIR`` (only together with ``PARTFORGE_HOME``)
  :func:`get_client` returns replay clients keyed by the datasheet's sha256 or the search query and never builds
  a network client.

Errors: :func:`map_sdk_error` turns SDK exceptions into German :class:`~.errors.AiUnavailable` (with a
machine-readable ``code``) or :class:`~.errors.ExtractionFailed` (API rejected the request).

**Cancelled requests are paid as well**: a job cancelled while a request streams raises :class:`RequestCancelled`
(a :class:`~partforge.jobs.JobCancelled`) whose ``partial`` estimates what that request cost until then
(:func:`partial_response`: the input as billed at the start of the answer, the output from the streamed characters,
the web searches already started) – callers record it like any other paid call.

The API key is read by :func:`get_client` (``partforge.config.read_api_key``) and handed to the SDK
only; it is never logged, returned, stored or sent to the frontend. Fixtures contain responses only.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..config import AppSettings, api_key_source, load_settings, read_api_key
from ..jobs import JobCancelled
from . import labels
from .costs import message_cost, usage_from_sdk
from .errors import AiUnavailable, ExtractionFailed
from .models import RunInfo, RunKind, Usage

log = logging.getLogger(__name__)

__all__ = [
    "CONNECT_TIMEOUT_S",
    "FALLBACK_BETA",
    "AnthropicLlmClient",
    "LlmClient",
    "LlmRequest",
    "LlmResponse",
    "RecordingLlmClient",
    "ReplayLlmClient",
    "RequestCancelled",
    "get_client",
    "http_timeout",
    "key_status",
    "message_to_dict",
    "partial_response",
    "set_client_factory",
    "supports_effort",
]

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FIXTURE_VERSION = 1
CONNECT_TIMEOUT_S = 10.0  # TCP/TLS connect (the SDK default is 5 s); reading a stream uses LlmRequest.timeout_s
READ_TIMEOUT_S = 600.0


@dataclass
class LlmRequest:
    kind: RunKind
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int
    system: str | None = None
    effort: str | None = None
    schema: dict[str, Any] | None = None  # JSON schema for output_config.format
    thinking: dict[str, Any] | None = None
    fallbacks: bool = False
    timeout_s: float = READ_TIMEOUT_S  # read/write timeout (between two stream chunks), connect: CONNECT_TIMEOUT_S
    max_retries: int | None = None  # None = the client's default (3)
    pages: list[int] = field(default_factory=list)  # real datasheet pages in this request (run info)
    tools: list[dict[str, Any]] | None = None  # server tools, e.g. [{"type": "web_search_20260318", ...}]

    def params(self) -> dict[str, Any]:
        """Keyword arguments for ``messages.stream`` (without betas/fallbacks)."""
        params: dict[str, Any] = {"model": self.model, "max_tokens": int(self.max_tokens), "messages": self.messages}
        if self.system:
            params["system"] = self.system
        output_config: dict[str, Any] = {}
        if self.effort:
            output_config["effort"] = self.effort
        if self.schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": self.schema}
        if output_config:
            params["output_config"] = output_config
        if self.thinking is not None:
            params["thinking"] = self.thinking
        if self.tools:
            params["tools"] = self.tools
        return params


_ECHO_AFTER_BOUNDARY = ("text", "thinking", "redacted_thinking", "fallback")


def _fallback_echo(block: Mapping[str, Any]) -> dict[str, Any]:
    """A ``fallback`` block as request param (``from`` is the API name; old dumps may carry ``from_``)."""
    out: dict[str, Any] = {"type": "fallback"}
    source = block.get("from", block.get("from_"))
    if source is not None:
        out["from"] = source
    if block.get("to") is not None:
        out["to"] = block["to"]
    if "trigger" in block:
        out["trigger"] = block["trigger"]
    return out


@dataclass
class LlmResponse:
    message: dict[str, Any]  # final message as plain JSON with API names (content blocks, usage, model …)
    text: str  # every text block in order: after a mid-stream fallback the continuation follows the partial text
    stop_reason: str | None
    model: str  # served model
    usage: Usage
    cost_usd: float
    request_id: str | None
    duration_s: float
    fallback: bool
    stop_details: dict[str, Any] | None = None
    tail_text: str = ""  # text blocks after the last fallback block (second parse candidate)

    def text_candidates(self) -> list[str]:
        """Texts to parse, best first: the whole answer, then (after a fallback) the text after the boundary."""
        out = [self.text]
        if self.fallback and self.tail_text and self.tail_text != self.text:
            out.append(self.tail_text)
        return out

    def run_info(self, request: LlmRequest, *, error: str | None = None) -> RunInfo:
        return RunInfo(
            kind=request.kind, model=request.model, served_model=self.model, effort=request.effort or "",
            pages=list(request.pages), request_id=self.request_id, usage=self.usage, cost_usd=round(self.cost_usd, 6),
            duration_s=round(self.duration_s, 2), stop_reason=self.stop_reason, fallback=self.fallback,
            ts=_dt.datetime.now().isoformat(timespec="seconds"), error=error,
        )

    def assistant_content(self) -> list[dict[str, Any]]:
        """Content of this answer for an appended follow-up turn (append-only history).

        After a mid-output fallback (docs: refusals-and-fallback, echoing fallback turns): the ``fallback`` blocks
        stay where they appeared; before the last one only text blocks are echoed (thinking, redacted thinking,
        tool and other model-internal blocks of a declined attempt are omitted); after it text and thinking blocks
        are echoed unchanged (their signatures bind them to the conversation). Empty text blocks are left out (the
        API rejects them); unknown block types after the boundary are dropped.
        """
        blocks = [b for b in self.message.get("content") or [] if isinstance(b, Mapping)]
        boundary = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1)
        out: list[dict[str, Any]] = []
        for index, block in enumerate(blocks):
            kind = block.get("type")
            if kind == "fallback":
                out.append(_fallback_echo(block))
            elif kind == "text":
                if block.get("text"):
                    out.append({"type": "text", "text": block["text"]})
            elif index < boundary:
                continue  # model-internal blocks of a declined attempt
            elif kind == "thinking":
                out.append({"type": "thinking", "thinking": block.get("thinking", ""),
                            "signature": block.get("signature", "")})
            elif kind == "redacted_thinking":
                out.append({"type": "redacted_thinking", "data": block.get("data", "")})
            elif kind not in _ECHO_AFTER_BOUNDARY:
                log.debug("Antwortblock „%s“ wird nicht zurückgesendet", kind)
        return out


#: Characters per output token for the estimate of a cancelled answer (German/JSON text: about 3.5–4; the lower value
#: errs on the expensive side).
CHARS_PER_OUTPUT_TOKEN = 3.5
#: ``RunInfo.error`` of the estimated part of a request that was cancelled while it ran.
CANCELLED_RUN_ERROR = "Abgebrochen – Kosten bis zum Abbruch geschätzt."


class RequestCancelled(JobCancelled):
    """The job was cancelled while a Claude request was running. ``partial`` = what the request produced and cost
    until then (:func:`partial_response`, an estimate) or ``None`` when its answer had not started yet."""

    def __init__(self, request: LlmRequest, partial: LlmResponse | None = None) -> None:
        super().__init__()
        self.request = request
        self.partial = partial


def partial_response(message: Any, request: LlmRequest, *, duration_s: float = 0.0,
                     request_id: str | None = None) -> LlmResponse | None:
    """Estimated answer of a request cancelled while streaming (``message`` = the accumulated message so far, e.g. the
    SDK's ``current_message_snapshot``; ``None`` = no answer yet → ``None``).

    The input is billed in full as soon as the answer starts (``usage`` of ``message_start``); the output is counted
    from the streamed text, thinking and tool inputs (:data:`CHARS_PER_OUTPUT_TOKEN`, at least what ``usage`` already
    reports); every started ``web_search`` counts as a paid search. The estimate is priced like a final answer."""
    if message is None:
        return None
    try:
        data = message_to_dict(message)
    except TypeError:
        return None
    chars = 0
    searches = 0
    for block in data.get("content") or []:
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind == "text":
            chars += len(str(block.get("text") or ""))
        elif kind == "thinking":
            chars += len(str(block.get("thinking") or ""))
        elif kind in ("server_tool_use", "tool_use"):
            chars += len(json.dumps(block.get("input") or {}, ensure_ascii=False))
            searches += block.get("name") == "web_search"
    usage = dict(data.get("usage") or {})
    usage.pop("iterations", None)  # per-model iterations are only final at the end of the answer
    usage["output_tokens"] = max(int(usage.get("output_tokens") or 0), math.ceil(chars / CHARS_PER_OUTPUT_TOKEN))
    tools = dict(usage.get("server_tool_use") or {})
    tools["web_search_requests"] = max(int(tools.get("web_search_requests") or 0), searches)
    usage["server_tool_use"] = tools
    data["usage"] = usage
    data["stop_reason"] = None
    return build_response(data, request, request_id=request_id, duration_s=duration_s)


TextCallback = Callable[[str], None]
FallbackCallback = Callable[[str], None]  # argument: the model that continues ("" if unknown)
ToolCallback = Callable[[str, dict[str, Any]], None]  # (server tool name, its input) once the call is complete
CancelCheck = Callable[[], bool]


class LlmClient(Protocol):
    def run(self, request: LlmRequest, *, on_text: TextCallback | None = None,
            on_fallback: FallbackCallback | None = None, cancelled: CancelCheck | None = None,
            on_tool: ToolCallback | None = None) -> LlmResponse: ...


# --------------------------------------------------------------------------- shared response handling


def message_to_dict(message: Any) -> dict[str, Any]:
    """Plain JSON form of an SDK message with the API's field names (``from`` of a fallback block, not the
    SDK's ``from_``), or a copy of a dict."""
    if isinstance(message, Mapping):
        return json.loads(json.dumps(dict(message), default=str))
    dump = getattr(message, "model_dump", None)
    if callable(dump):
        return dump(mode="json", by_alias=True, exclude_none=False)
    raise TypeError(f"Unerwarteter Antworttyp {type(message).__name__}")


def _texts(message: Mapping[str, Any]) -> tuple[str, str]:
    """(all text blocks, text blocks after the last fallback block)."""
    blocks = [b for b in message.get("content") or [] if isinstance(b, Mapping)]
    start = max((i for i, b in enumerate(blocks) if b.get("type") == "fallback"), default=-1) + 1
    whole = "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")
    tail = "".join(str(b.get("text") or "") for b in blocks[start:] if b.get("type") == "text")
    return whole, tail


def _fallback_ran(message: Mapping[str, Any]) -> bool:
    if any(isinstance(b, Mapping) and b.get("type") == "fallback" for b in message.get("content") or []):
        return True
    usage = message.get("usage") or {}
    return any((it or {}).get("type") == "fallback_message" for it in usage.get("iterations") or [])


def build_response(message: Any, request: LlmRequest, *, request_id: str | None, duration_s: float) -> LlmResponse:
    data = message_to_dict(message)
    usage = usage_from_sdk(data.get("usage"))
    details = data.get("stop_details")
    whole, tail = _texts(data)
    return LlmResponse(
        message=data,
        text=whole,
        tail_text=tail,
        stop_reason=data.get("stop_reason"),
        model=str(data.get("model") or request.model),
        usage=usage,
        cost_usd=message_cost(data, request.model),
        request_id=request_id or data.get("_request_id"),
        duration_s=duration_s,
        fallback=_fallback_ran(data),
        stop_details=details if isinstance(details, dict) else None,
    )


def _short(text: str, limit: int = 300) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def map_sdk_error(exc: Exception, model: str) -> Exception:
    """German error for an Anthropic SDK exception (never contains the key).

    :class:`AiUnavailable` carries a machine-readable ``code`` (``key_rejected``, ``model_unavailable``,
    ``rate_limited``, ``network`` – also for an overloaded or disturbed service – or ``unknown``); a rejected request
    (HTTP 400) becomes :class:`ExtractionFailed` with ``api_status``/``api_message``."""
    import anthropic

    name = labels.model_label(model)
    if isinstance(exc, anthropic.AuthenticationError):
        return AiUnavailable("Der Claude-API-Schlüssel wurde abgelehnt (ungültig, abgelaufen oder gesperrt). "
                             "Bitte in den Einstellungen unter „KI“ einen gültigen Schlüssel hinterlegen.",
                             code="key_rejected")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AiUnavailable(f"Der API-Schlüssel hat keinen Zugriff auf das Modell {name} (HTTP 403). "
                             "Bitte in den Einstellungen ein anderes Modell wählen.", code="model_unavailable")
    if isinstance(exc, anthropic.NotFoundError):
        return AiUnavailable(f"Das Modell {name} ist bei der Claude-API nicht verfügbar (HTTP 404). "
                             "Bitte in den Einstellungen ein anderes Modell wählen.", code="model_unavailable")
    if isinstance(exc, anthropic.RateLimitError):
        return AiUnavailable("Das Anfragelimit der Claude-API ist erreicht (HTTP 429) – bitte in einer Minute erneut "
                             "versuchen.", code="rate_limited")
    if isinstance(exc, anthropic.BadRequestError):
        detail = _short(str(getattr(exc, "message", "") or exc))
        low = detail.lower()
        if "credit balance" in low:
            return AiUnavailable("Das Guthaben des Claude-API-Kontos reicht nicht aus – bitte in der Claude Console "
                                 "Guthaben aufladen.", code="unknown")
        if "web search" in low.replace("_", " ") and ("not enabled" in low or "disabled" in low):
            return AiUnavailable("Die Websuche ist für dieses Claude-API-Konto nicht freigeschaltet (Claude Console › "
                                 "Settings › Capabilities).", code="unknown")
        failed = ExtractionFailed(f"Die Claude-API hat die Anfrage abgelehnt: {detail}")
        failed.api_status, failed.api_message = 400, detail
        return failed
    if isinstance(exc, anthropic.APIStatusError):
        return AiUnavailable(f"Die Claude-API ist überlastet oder gestört (HTTP {exc.status_code}) – bitte später "
                             "erneut versuchen.", code="network")
    if isinstance(exc, anthropic.APITimeoutError):
        return AiUnavailable("Zeitüberschreitung bei der Claude-API – bitte erneut versuchen.", code="network")
    if isinstance(exc, anthropic.APIConnectionError):
        return AiUnavailable("Keine Verbindung zur Claude-API – bitte die Internetverbindung (Proxy, Firewall) prüfen.",
                             code="network")
    return exc


_NO_EFFORT = ("claude-3", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-sonnet-4-0", "claude-sonnet-4-2",
              "claude-opus-4-0", "claude-opus-4-1", "claude-opus-4-2")


def supports_effort(model: str) -> bool:
    """``output_config.effort`` is rejected by Claude Sonnet 4.5 / Haiku 4.5 and older models (Opus 4.5 and every
    newer model accept it)."""
    return not any(str(model or "").startswith(prefix) for prefix in _NO_EFFORT)


# --------------------------------------------------------------------------- real client


def http_timeout(read_s: float) -> Any:
    """SDK timeout: :data:`CONNECT_TIMEOUT_S` to connect, ``read_s`` for reading/writing (between stream chunks)."""
    import anthropic

    return anthropic.Timeout(read_s, connect=min(CONNECT_TIMEOUT_S, read_s))


def _fallback_target(block: Any) -> str:
    target = getattr(block, "to", None)
    if isinstance(target, Mapping):
        return str(target.get("model") or "")
    return str(getattr(target, "model", "") or "")


class AnthropicLlmClient:
    """Streaming client on the official SDK. ``sdk_client`` may be injected (tests)."""

    def __init__(self, api_key: str | None = None, *, sdk_client: Any = None, max_retries: int = 3,
                 timeout_s: float = READ_TIMEOUT_S) -> None:
        if sdk_client is None:
            import anthropic

            if not api_key:
                raise AiUnavailable("Kein Claude-API-Schlüssel hinterlegt.")
            sdk_client = anthropic.Anthropic(api_key=api_key, max_retries=max_retries, timeout=http_timeout(timeout_s))
        self._sdk = sdk_client

    def __repr__(self) -> str:  # never show the SDK client (it holds the key)
        return "AnthropicLlmClient()"

    @staticmethod
    def _partial(stream: Any, request: LlmRequest, started: float) -> LlmResponse | None:
        """Estimate of the answer streamed so far (``None`` before the first event)."""
        try:
            snapshot = stream.current_message_snapshot
        except Exception:  # noqa: BLE001 - no event yet (the SDK asserts) or an unexpected stream object
            return None
        try:
            return partial_response(snapshot, request, duration_s=time.perf_counter() - started,
                                    request_id=getattr(stream, "request_id", None))
        except Exception:  # noqa: BLE001 - the estimate must never hide the cancellation
            log.exception("Kosten der abgebrochenen Claude-Anfrage (%s) nicht abschätzbar", request.kind)
            return None

    def _client(self, request: LlmRequest) -> Any:
        if request.max_retries is None:
            return self._sdk
        with_options = getattr(self._sdk, "with_options", None)
        return with_options(max_retries=request.max_retries) if callable(with_options) else self._sdk

    def run(self, request: LlmRequest, *, on_text: TextCallback | None = None,
            on_fallback: FallbackCallback | None = None, cancelled: CancelCheck | None = None,
            on_tool: ToolCallback | None = None) -> LlmResponse:
        params = request.params()
        started = time.perf_counter()
        try:
            sdk = self._client(request)
            timeout = http_timeout(request.timeout_s)
            if request.fallbacks:
                manager = sdk.beta.messages.stream(**params, betas=[FALLBACK_BETA], fallbacks="default",
                                                   timeout=timeout)
            else:
                manager = sdk.messages.stream(**params, timeout=timeout)
            with manager as stream:
                for event in stream:
                    if cancelled is not None and cancelled():
                        raise RequestCancelled(request, self._partial(stream, request, started))
                    kind = getattr(event, "type", "")
                    if kind == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", "") == "fallback" and on_fallback is not None:
                            # the text received so far stays valid: the fallback model continues from it
                            on_fallback(_fallback_target(block))
                    elif kind == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if getattr(delta, "type", "") == "text_delta" and on_text is not None:
                            on_text(getattr(delta, "text", ""))
                    elif kind == "content_block_stop" and on_tool is not None:
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", "") == "server_tool_use":
                            data = getattr(block, "input", None)
                            on_tool(str(getattr(block, "name", "") or ""),
                                    dict(data) if isinstance(data, Mapping) else {})
                final = stream.get_final_message()
                request_id = getattr(stream, "request_id", None)
        except JobCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - mapped to German errors, everything else re-raised
            mapped = map_sdk_error(exc, request.model)
            if mapped is exc:
                raise
            log.warning("Claude-Anfrage (%s, %s) fehlgeschlagen: %s (request_id=%s)", request.kind, request.model,
                        type(exc).__name__, getattr(exc, "request_id", None))
            raise mapped from exc
        response = build_response(final, request, request_id=request_id, duration_s=time.perf_counter() - started)
        log.info("Claude %s: %s -> %s, %s, %d Token Eingabe (+%d Cache-Schreiben, %d Cache-Lesen), %d Ausgabe, "
                 "%.4f USD, %.1f s, request_id=%s", request.kind, request.model, response.model, response.stop_reason,
                 response.usage.input_tokens, response.usage.cache_write_tokens, response.usage.cache_read_tokens,
                 response.usage.output_tokens, response.cost_usd, response.duration_s, response.request_id)
        return response


# --------------------------------------------------------------------------- recorded responses


@dataclass
class RecordedCall:
    kind: str
    message: dict[str, Any]
    model: str = ""
    effort: str = ""
    pages: list[int] = field(default_factory=list)
    request_id: str | None = None
    duration_s: float = 0.0


def load_fixture(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ReplayLlmClient:
    """Replays recorded responses: each :meth:`run` takes the next recorded call of the same kind.

    ``requests`` keeps every request (tests assert on models, effort, pages, cache control …). ``delay_s`` (seconds per
    streamed chunk; three times that before the first chunk, twice per server tool call) makes the replay look like a
    live answer for UI tests and demos; the waits stop at once when the job is cancelled.
    """

    def __init__(self, calls: Sequence[RecordedCall | Mapping[str, Any]] | Path | str, *, chunk: int = 700,
                 delay_s: float = 0.0) -> None:
        items: Sequence[RecordedCall | Mapping[str, Any]]
        items = load_fixture(Path(calls)).get("calls", []) if isinstance(calls, (str, Path)) else calls
        self._calls: list[RecordedCall] = [
            c if isinstance(c, RecordedCall) else RecordedCall(
                kind=str(c.get("kind")), message=dict(c.get("message") or {}), model=str(c.get("model") or ""),
                effort=str(c.get("effort") or ""), pages=[int(p) for p in c.get("pages") or []],
                request_id=c.get("request_id"), duration_s=float(c.get("duration_s") or 0.0))
            for c in items
        ]
        self._chunk = max(1, chunk)
        self._delay = max(0.0, float(delay_s or 0.0))
        self._lock = threading.Lock()
        self.requests: list[LlmRequest] = []

    @property
    def remaining(self) -> list[str]:
        return [c.kind for c in self._calls]

    def _pause(self, factor: float, cancelled: CancelCheck | None) -> None:
        """Wait ``factor`` x ``delay_s`` (in small steps, so a cancelled job stops at once)."""
        end = time.monotonic() + self._delay * factor
        while True:
            if cancelled is not None and cancelled():
                raise JobCancelled()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(0.05, left))

    def run(self, request: LlmRequest, *, on_text: TextCallback | None = None,
            on_fallback: FallbackCallback | None = None, cancelled: CancelCheck | None = None,
            on_tool: ToolCallback | None = None) -> LlmResponse:
        with self._lock:
            self.requests.append(request)
            index = next((i for i, c in enumerate(self._calls) if c.kind == request.kind), None)
            if index is None:
                raise ExtractionFailed(f"Keine aufgezeichnete Antwort für „{request.kind}“ vorhanden (Testdaten).")
            call = self._calls.pop(index)
        streamed: list[dict[str, Any]] = []  # what the "API" sent so far (for the cost of a cancelled answer)
        try:
            self._stream(call, streamed, on_text, on_fallback, cancelled, on_tool)
        except RequestCancelled:
            raise
        except JobCancelled:
            usage = call.message.get("usage") or {}
            started = {k: usage.get(k) for k in ("input_tokens", "cache_creation_input_tokens",
                                                 "cache_read_input_tokens") if k in usage}
            message = {**call.message, "content": streamed, "usage": started}
            raise RequestCancelled(request, partial_response(message, request, request_id=call.request_id)) from None
        return build_response(call.message, request, request_id=call.request_id, duration_s=call.duration_s)

    def _stream(self, call: RecordedCall, streamed: list[dict[str, Any]], on_text: TextCallback | None,
                on_fallback: FallbackCallback | None, cancelled: CancelCheck | None,
                on_tool: ToolCallback | None) -> None:
        """Replay the blocks of ``call`` in order, like the real client streams them (``streamed`` = sent so far)."""
        if self._delay:
            self._pause(3, cancelled)  # "time to first token"
        for block in call.message.get("content") or []:  # streamed in order, like the real client
            if not isinstance(block, Mapping):
                continue
            kind = block.get("type")
            if kind == "fallback":
                streamed.append(dict(block))
                if on_fallback is not None:
                    target = block.get("to")
                    on_fallback(str(target.get("model") or "") if isinstance(target, Mapping) else "")
                continue
            if kind == "server_tool_use":
                if self._delay:
                    self._pause(2, cancelled)
                streamed.append(dict(block))
                if on_tool is not None:
                    data = block.get("input")
                    on_tool(str(block.get("name") or ""), dict(data) if isinstance(data, Mapping) else {})
                continue
            if kind != "text":
                streamed.append(dict(block))
                continue
            text = str(block.get("text") or "")
            sent = {**block, "text": ""}
            streamed.append(sent)
            for start in range(0, len(text), self._chunk):
                if cancelled is not None and cancelled():
                    raise JobCancelled()
                if self._delay:
                    self._pause(1, cancelled)
                sent["text"] = text[:start + self._chunk]
                if on_text is not None:
                    on_text(text[start:start + self._chunk])
        if cancelled is not None and cancelled():
            raise JobCancelled()


class RecordingLlmClient:
    """Wraps a client and appends every answer to a fixture file (responses only, never the key or the PDF)."""

    def __init__(self, inner: LlmClient, path: Path, *, meta: Mapping[str, Any] | None = None) -> None:
        self._inner = inner
        self.path = Path(path)
        self._meta = dict(meta or {})
        self._lock = threading.Lock()

    def run(self, request: LlmRequest, *, on_text: TextCallback | None = None,
            on_fallback: FallbackCallback | None = None, cancelled: CancelCheck | None = None,
            on_tool: ToolCallback | None = None) -> LlmResponse:
        response = self._inner.run(request, on_text=on_text, on_fallback=on_fallback, cancelled=cancelled,
                                   on_tool=on_tool)
        with self._lock:
            data: dict[str, Any] = {"fixture_version": FIXTURE_VERSION, **self._meta, "calls": []}
            if self.path.is_file():
                data = load_fixture(self.path)
            data.setdefault("calls", []).append({
                "kind": request.kind, "model": request.model, "effort": request.effort or "", "pages": request.pages,
                "request_id": response.request_id, "duration_s": round(response.duration_s, 2),
                "cost_usd": round(response.cost_usd, 6),
                "recorded": _dt.datetime.now().isoformat(timespec="seconds"), "message": response.message,
            })
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        return response


# --------------------------------------------------------------------------- factory

_factory_lock = threading.Lock()
_factory: Callable[[], LlmClient] | None = None


def set_client_factory(factory: Callable[[], LlmClient] | None) -> Callable[[], LlmClient] | None:
    """Replace the client factory (tests, replay mode); returns the previous one. ``None`` = default."""
    global _factory
    with _factory_lock:
        previous, _factory = _factory, factory
    return previous


def ai_enabled_or_raise(settings: AppSettings | None = None) -> AppSettings:
    settings = settings or load_settings()
    if not settings.ai.enabled:
        raise AiUnavailable("Die KI-Funktionen sind in den Einstellungen ausgeschaltet (Einstellungen › KI).",
                            code="ai_disabled")
    return settings


def get_client(settings: AppSettings | None = None, *, datasheet_id: str | None = None,
               search: str | None = None) -> LlmClient:
    """The configured client (raises :class:`AiUnavailable` when AI is off or no key is configured).

    Order: AI switched off → :class:`AiUnavailable` (``ai_disabled``); a factory of :func:`set_client_factory`
    (tests); the replay mode (:mod:`.replay`, ``datasheet_id`` = the datasheet the requests are for, ``search`` = the
    query of a datasheet search – a missing recording raises :class:`AiUnavailable`, never a network client); the
    real client with the configured key (``key_missing`` without one)."""
    settings = ai_enabled_or_raise(settings)
    with _factory_lock:
        factory = _factory
    if factory is not None:
        return factory()
    from . import replay

    if replay.active():
        return replay.client(settings, datasheet_id=datasheet_id, search=search)
    key = read_api_key(settings)
    if not key:
        raise AiUnavailable("Kein Claude-API-Schlüssel hinterlegt. Bitte in den Einstellungen unter „KI“ einen Schlüssel "
                            "eintragen (oder die Umgebungsvariable ANTHROPIC_API_KEY setzen).", code="key_missing")
    return AnthropicLlmClient(key)


def key_status(settings: AppSettings | None = None) -> tuple[bool, str | None]:
    """``(key configured, source)`` for the UI – source ``env`` | ``stored`` | ``file`` | ``replay`` | None (never the
    key itself). The replay mode counts as configured."""
    from . import replay

    if replay.active():
        return True, "replay"
    settings = settings or load_settings()
    return bool(read_api_key(settings)), api_key_source(settings)
