"""Datasheet import: Claude client layer (offline) – request parameters, streaming, server-side fallbacks, error
mapping, replay/recording of fixtures, client factory, costs and the structured-output schemas."""
from __future__ import annotations

import json
import math
import threading
import time
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from partforge.config import AppSettings
from partforge.datasheet import costs, llm, schema
from partforge.datasheet.errors import AiUnavailable, BudgetExceeded, ExtractionFailed
from partforge.datasheet.models import Usage
from partforge.jobs import JobCancelled

FAKE_KEY = "sk-ant-test-0000-geheim"


def _message(text: str = '{"ok": true}', *, stop: str = "end_turn", model: str = "claude-opus-5-5",
             content: list[dict[str, Any]] | None = None, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": content if content is not None else [{"type": "text", "text": text}],
            "stop_reason": stop, "stop_sequence": None,
            "usage": usage or {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 1000,
                               "cache_read_input_tokens": 0}}


def _request(**kw: Any) -> llm.LlmRequest:
    base: dict[str, Any] = {"kind": "identity", "model": "claude-opus-5-5", "max_tokens": 1000,
                            "messages": [{"role": "user", "content": "x"}]}
    base.update(kw)
    return llm.LlmRequest(**base)


# --------------------------------------------------------------------------- fake SDK


class _FakeStream:
    def __init__(self, events: list[Any], final: Any, request_id: str = "req_test") -> None:
        self._events, self._final, self.request_id = events, final, request_id

    def __iter__(self):
        return iter(self._events)

    def get_final_message(self) -> Any:
        return self._final


class _FakeManager:
    def __init__(self, stream: _FakeStream, error: Exception | None = None) -> None:
        self._stream, self._error = stream, error

    def __enter__(self) -> _FakeStream:
        if self._error is not None:
            raise self._error
        return self._stream

    def __exit__(self, *exc: Any) -> None:
        return None


class _FakeMessages:
    def __init__(self, owner: _FakeSdk) -> None:
        self._owner = owner

    def stream(self, **kwargs: Any) -> _FakeManager:
        self._owner.calls.append(kwargs)
        return _FakeManager(self._owner.stream, self._owner.error)


class _FakeSdk:
    def __init__(self, events: list[Any], final: Any, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stream = _FakeStream(events, final)
        self.error = error
        self.messages = _FakeMessages(self)
        self.beta = SimpleNamespace(messages=_FakeMessages(self))
        self.options: list[dict[str, Any]] = []

    def with_options(self, **options: Any) -> _FakeSdk:
        self.options.append(options)
        return self


def _delta(text: str) -> Any:
    return SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text))


def _start(block_type: str, **fields: Any) -> Any:
    return SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type=block_type, **fields))


_FALLBACK = {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-5"},
             "trigger": {"type": "refusal", "category": "cyber"}}
_ITERATIONS = {"input_tokens": 10, "output_tokens": 30, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
               "iterations": [
                   {"type": "message", "model": "claude-opus-5-5", "input_tokens": 10, "output_tokens": 10,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                   {"type": "fallback_message", "model": "claude-opus-5", "input_tokens": 10, "output_tokens": 20,
                    "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}]}


# --------------------------------------------------------------------------- request parameters


def test_request_params():
    req = _request(system="sys", effort="low", schema={"type": "object"}, thinking={"type": "disabled"})
    params = req.params()
    assert params["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    assert params["system"] == "sys" and params["thinking"] == {"type": "disabled"} and params["max_tokens"] == 1000
    bare = _request().params()
    assert "output_config" not in bare and "system" not in bare and "thinking" not in bare


def test_streaming_with_server_side_fallbacks():
    final = anthropic.types.beta.BetaMessage.model_validate(_message('{"a": 1}'))
    sdk = _FakeSdk([_start("text"), _delta('{"a"'), _delta(": 1}")], final)
    client = llm.AnthropicLlmClient(sdk_client=sdk)
    texts: list[str] = []
    response = client.run(_request(fallbacks=True, effort="low"), on_text=texts.append)
    assert texts == ['{"a"', ": 1}"]
    call = sdk.calls[0]
    assert call["betas"] == [llm.FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["output_config"] == {"effort": "low"}
    timeout = call["timeout"]  # short connect, long read (between two stream chunks)
    assert isinstance(timeout, httpx2.Timeout)
    assert timeout.connect == llm.CONNECT_TIMEOUT_S and timeout.read == 600.0
    assert sdk.options == []  # the client's retries unless the request sets its own
    assert response.text == '{"a": 1}' and response.request_id == "req_test"
    assert response.stop_reason == "end_turn" and response.model == "claude-opus-5-5" and not response.fallback
    assert response.cost_usd == pytest.approx((100 * 4 + 1000 * 5 + 50 * 20) / 1e6)
    assert repr(client) == "AnthropicLlmClient()"


def test_request_timeouts_and_retries():
    sdk = _FakeSdk([], _message())
    llm.AnthropicLlmClient(sdk_client=sdk).run(_request(timeout_s=30.0, max_retries=1))
    assert sdk.options == [{"max_retries": 1}]
    assert sdk.calls[0]["timeout"].connect == llm.CONNECT_TIMEOUT_S and sdk.calls[0]["timeout"].read == 30.0
    real = llm.AnthropicLlmClient("sk-ant-fake-not-a-key")._sdk  # noqa: SLF001 - configuration check only
    assert real.timeout.connect == llm.CONNECT_TIMEOUT_S and real.timeout.read == 600.0 and real.max_retries == 3


def test_without_fallbacks_the_plain_endpoint_is_used():
    sdk = _FakeSdk([], _message())
    llm.AnthropicLlmClient(sdk_client=sdk).run(_request(fallbacks=False))
    assert "betas" not in sdk.calls[0] and "fallbacks" not in sdk.calls[0]


def test_mid_stream_fallback_continues_the_partial_text():
    """Docs (refusals-and-fallback, Streaming): the fallback model continues from the partial output."""
    content = [{"type": "text", "text": '{"a": 1, "b'}, _FALLBACK,
               {"type": "thinking", "thinking": "", "signature": "sig"},
               {"type": "text", "text": '": 2}'}]
    final = anthropic.types.beta.BetaMessage.model_validate(
        _message(content=content, usage=_ITERATIONS, model="claude-opus-5"))
    switched: list[str] = []
    texts: list[str] = []
    sdk = _FakeSdk([_delta('{"a": 1, "b'), _start("fallback", to=SimpleNamespace(model="claude-opus-5")),
                    _delta('": 2}')], final)
    response = llm.AnthropicLlmClient(sdk_client=sdk).run(_request(fallbacks=True), on_text=texts.append,
                                                          on_fallback=switched.append)
    assert switched == ["claude-opus-5"] and "".join(texts) == '{"a": 1, "b": 2}'
    assert response.text == '{"a": 1, "b": 2}' and json.loads(response.text) == {"a": 1, "b": 2}
    assert response.tail_text == '": 2}' and response.text_candidates() == ['{"a": 1, "b": 2}', '": 2}']
    assert response.fallback and response.model == "claude-opus-5"
    assert response.cost_usd == pytest.approx((10 * 4 + 10 * 20 + 10 * 5 + 20 * 25) / 1e6)
    # the stored message keeps the API names; the echo keeps the fallback block where it appeared
    assert response.message["content"][1]["from"] == {"model": "claude-opus-5-5"}
    assert response.assistant_content() == [
        {"type": "text", "text": '{"a": 1, "b'},
        {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-5"},
         "trigger": {"type": "refusal", "category": "cyber"}},
        {"type": "thinking", "thinking": "", "signature": "sig"},
        {"type": "text", "text": '": 2}'}]


def test_fallback_before_any_output_and_the_restart_variant():
    pre = llm.build_response(_message(content=[_FALLBACK, {"type": "text", "text": '{"c": 3}'}], usage=_ITERATIONS),
                             _request(), request_id=None, duration_s=0.0)
    assert pre.fallback and pre.text == pre.tail_text == '{"c": 3}' and pre.text_candidates() == ['{"c": 3}']
    assert pre.assistant_content()[0]["type"] == "fallback"
    # should a fallback model ever restart instead of continuing, the text after the boundary is the second candidate
    restart = llm.build_response(_message(content=[{"type": "text", "text": '{"par'}, _FALLBACK,
                                                   {"type": "text", "text": '{"d": 4}'}]),
                                 _request(), request_id=None, duration_s=0.0)
    assert restart.text_candidates() == ['{"par{"d": 4}', '{"d": 4}']


def test_echo_drops_thinking_before_the_fallback_boundary():
    content = [{"type": "thinking", "thinking": "x", "signature": "s1"}, {"type": "text", "text": "a"},
               {"type": "tool_use", "id": "t1", "name": "x", "input": {}}, {"type": "fallback"},
               {"type": "redacted_thinking", "data": "zz"}, {"type": "text", "text": ""}, {"type": "text", "text": "b"},
               {"type": "unknown_block"}]
    response = llm.build_response(_message(content=content), _request(), request_id=None, duration_s=0.0)
    assert response.assistant_content() == [{"type": "text", "text": "a"}, {"type": "fallback"},
                                            {"type": "redacted_thinking", "data": "zz"}, {"type": "text", "text": "b"}]
    legacy = llm.build_response(_message(content=[{"type": "fallback", "from_": {"model": "x"}, "to": {"model": "y"}}]),
                                _request(), request_id=None, duration_s=0.0)
    assert legacy.assistant_content() == [{"type": "fallback", "from": {"model": "x"}, "to": {"model": "y"}}]


def test_message_to_dict_uses_the_api_field_names():
    final = anthropic.types.beta.BetaMessage.model_validate(_message(content=[_FALLBACK, {"type": "text", "text": "x"}]))
    data = llm.message_to_dict(final)
    assert data["content"][0]["from"] == {"model": "claude-opus-5-5"} and "from_" not in data["content"][0]


@pytest.mark.parametrize(("model", "expected"), [
    ("claude-opus-5-5", True), ("claude-haiku-5-5", True), ("claude-sonnet-4-6", True), ("claude-opus-4-5", True),
    ("claude-haiku-4-5", False), ("claude-sonnet-4-5", False), ("claude-opus-4-1", False),
    ("claude-sonnet-4-20250514", False), ("claude-3-7-sonnet-latest", False),
])
def test_supports_effort(model, expected):
    assert llm.supports_effort(model) is expected


def test_replay_reports_fallback_boundaries():
    replay = llm.ReplayLlmClient([{"kind": "identity", "message": _message(
        content=[{"type": "text", "text": '{"a": 1, "b'}, _FALLBACK, {"type": "text", "text": '": 2}'}],
        usage=_ITERATIONS)}])
    switched: list[str] = []
    chunks: list[str] = []
    response = replay.run(_request(), on_text=chunks.append, on_fallback=switched.append)
    assert switched == ["claude-opus-5"] and "".join(chunks) == '{"a": 1, "b": 2}' and response.fallback


def test_cancellation_during_streaming():
    sdk = _FakeSdk([_delta("a"), _delta("b")], _message())
    with pytest.raises(JobCancelled):
        llm.AnthropicLlmClient(sdk_client=sdk).run(_request(), cancelled=lambda: True)


class _SnapshotStream(_FakeStream):
    """A stream that has seen ``message_start`` and some text (the SDK's ``current_message_snapshot``)."""

    current_message_snapshot = _message(
        content=[{"type": "thinking", "thinking": "t" * 70, "signature": "s"}, {"type": "text", "text": "x" * 280}],
        usage={"input_tokens": 9000, "output_tokens": 1, "cache_creation_input_tokens": 2000,
               "cache_read_input_tokens": 0})


def test_a_cancelled_request_reports_what_it_cost_so_far():
    """K15: the cost of a request cancelled while streaming is estimated (input as billed at the start, output from
    the streamed characters) and travels with the cancellation."""
    sdk = _FakeSdk([], _message())
    sdk.stream = _SnapshotStream([_delta("a")], _message())
    with pytest.raises(llm.RequestCancelled) as info:
        llm.AnthropicLlmClient(sdk_client=sdk).run(_request(), cancelled=lambda: True)
    assert isinstance(info.value, JobCancelled) and info.value.request.kind == "identity"
    partial = info.value.partial
    assert partial is not None and partial.request_id == "req_test" and partial.stop_reason is None
    usage = partial.usage
    assert (usage.input_tokens, usage.cache_write_tokens, usage.output_tokens) == (9000, 2000, 100)
    assert partial.cost_usd == pytest.approx((9000 * 4 + 2000 * 5 + 100 * 20) / 1e6)
    run = partial.run_info(info.value.request, error=llm.CANCELLED_RUN_ERROR)
    assert run.cost_usd == pytest.approx(partial.cost_usd) and run.error.startswith("Abgebrochen")
    # cancelled before the first event: nothing is known, nothing is estimated
    with pytest.raises(llm.RequestCancelled) as info:
        llm.AnthropicLlmClient(sdk_client=_FakeSdk([_delta("a")], _message())).run(_request(), cancelled=lambda: True)
    assert info.value.partial is None


def test_replay_cancellation_estimates_the_streamed_part():
    """K15: the replay client estimates a cancelled answer like the real one – searches already started count."""
    content = [{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "OPA656"}},
               {"type": "web_search_tool_result", "tool_use_id": "s1", "content": []},
               {"type": "text", "text": "y" * 700}]
    message = _message(content=content, usage={"input_tokens": 9000, "output_tokens": 600,
                                               "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                                               "server_tool_use": {"web_search_requests": 1}})
    chunks: list[str] = []
    client = llm.ReplayLlmClient([{"kind": "find", "message": message}], chunk=350)
    with pytest.raises(llm.RequestCancelled) as info:
        client.run(_request(kind="find"), on_text=chunks.append, cancelled=lambda: len(chunks) >= 1)
    partial = info.value.partial
    output = math.ceil((350 + len(json.dumps({"query": "OPA656"}))) / llm.CHARS_PER_OUTPUT_TOKEN)
    assert partial.usage.input_tokens == 9000 and partial.usage.output_tokens == output < 600
    assert partial.cost_usd == pytest.approx(9000 * 4e-6 + output * 20e-6 + 0.01)  # + one web search
    finished = llm.ReplayLlmClient([{"kind": "find", "message": message}]).run(_request(kind="find"))
    assert finished.cost_usd > partial.cost_usd


def _status_error(cls: type, status: int, message: str = "nope") -> Exception:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx2.Response(status, request=request), body=None)


@pytest.mark.parametrize(("error", "expected", "text"), [
    (_status_error(anthropic.AuthenticationError, 401), AiUnavailable, "Schlüssel wurde abgelehnt"),
    (_status_error(anthropic.PermissionDeniedError, 403), AiUnavailable, "keinen Zugriff"),
    (_status_error(anthropic.NotFoundError, 404), AiUnavailable, "nicht verfügbar"),
    (_status_error(anthropic.RateLimitError, 429), AiUnavailable, "Anfragelimit"),
    (_status_error(anthropic.BadRequestError, 400, "The compiled grammar is too large"), ExtractionFailed,
     "compiled grammar"),
    (_status_error(anthropic.InternalServerError, 529), AiUnavailable, "HTTP 529"),
    (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com")), AiUnavailable,
     "Zeitüberschreitung"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), AiUnavailable,
     "Keine Verbindung"),
])
def test_sdk_errors_are_mapped_to_german_messages(error, expected, text):
    sdk = _FakeSdk([], _message(), error=error)
    with pytest.raises(expected, match=text) as info:
        llm.AnthropicLlmClient(sdk_client=sdk).run(_request())
    assert FAKE_KEY not in str(info.value)


def test_unrelated_errors_propagate():
    sdk = _FakeSdk([], _message(), error=KeyError("intern"))
    with pytest.raises(KeyError):
        llm.AnthropicLlmClient(sdk_client=sdk).run(_request())


def test_real_client_requires_a_key():
    with pytest.raises(AiUnavailable):
        llm.AnthropicLlmClient(None)


# --------------------------------------------------------------------------- replay / recording


def test_replay_matches_calls_by_kind_and_streams_chunks():
    replay = llm.ReplayLlmClient([{"kind": "geometry", "message": _message('{"g": 1}')},
                                  {"kind": "identity", "message": _message('{"i": 1}')}], chunk=3)
    chunks: list[str] = []
    first = replay.run(_request(kind="identity"), on_text=chunks.append)
    assert first.text == '{"i": 1}' and "".join(chunks) == '{"i": 1}' and len(chunks) == 3
    assert replay.remaining == ["geometry"]
    assert replay.run(_request(kind="geometry")).text == '{"g": 1}'
    with pytest.raises(ExtractionFailed, match="identity"):
        replay.run(_request(kind="identity"))
    assert [r.kind for r in replay.requests] == ["identity", "geometry", "identity"]
    with pytest.raises(JobCancelled):
        llm.ReplayLlmClient([{"kind": "identity", "message": _message()}]).run(_request(), cancelled=lambda: True)


def test_recording_writes_responses_only(tmp_path):
    target = tmp_path / "fixture.json"
    inner = llm.ReplayLlmClient([{"kind": "identity", "message": _message('{"x": 1}')},
                                 {"kind": "geometry", "message": _message('{"y": 2}')}])
    recorder = llm.RecordingLlmClient(inner, target, meta={"pdf": "a.pdf"})
    big_pdf = "JVBERi0xLjQ" * 50
    recorder.run(_request(kind="identity", pages=[1, 2],
                          messages=[{"role": "user", "content": [{"type": "document", "source": {"data": big_pdf}}]}]))
    recorder.run(_request(kind="geometry", pages=[5]))
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["pdf"] == "a.pdf" and data["fixture_version"] == 1
    assert [c["kind"] for c in data["calls"]] == ["identity", "geometry"]
    assert data["calls"][0]["pages"] == [1, 2] and data["calls"][0]["cost_usd"] > 0
    text = target.read_text(encoding="utf-8")
    assert big_pdf not in text and "sk-ant" not in text
    replay = llm.ReplayLlmClient(target)
    assert replay.remaining == ["identity", "geometry"]
    assert replay.run(_request(kind="geometry")).text == '{"y": 2}'


# --------------------------------------------------------------------------- client factory


@pytest.mark.windows
def test_get_client_respects_settings_and_never_exposes_the_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = AppSettings()
    settings.ai.api_key_file = str(tmp_path / "missing.txt")
    previous = llm.set_client_factory(None)
    try:
        with pytest.raises(AiUnavailable, match="Kein Claude-API-Schlüssel"):
            llm.get_client(settings)
        key_file = tmp_path / "key.txt"
        key_file.write_text(FAKE_KEY + "\n", encoding="utf-8")
        settings.ai.api_key_file = str(key_file)
        client = llm.get_client(settings)
        assert isinstance(client, llm.AnthropicLlmClient)
        assert FAKE_KEY not in repr(client) and FAKE_KEY not in str(vars(client).keys())
        settings.ai.enabled = False
        with pytest.raises(AiUnavailable, match="ausgeschaltet"):
            llm.get_client(settings)
        settings.ai.enabled = True
        fake = llm.ReplayLlmClient([])
        llm.set_client_factory(lambda: fake)
        assert llm.get_client(settings) is fake
    finally:
        llm.set_client_factory(previous)


# --------------------------------------------------------------------------- costs and budget


def test_usage_cost_and_price_tiers():
    usage = Usage(input_tokens=1_000_000, cache_write_tokens=1_000_000, cache_read_tokens=1_000_000,
                  output_tokens=1_000_000)
    assert costs.usage_cost("claude-opus-5-5", usage) == pytest.approx(4 + 5 + 0.2 + 20)
    small = Usage(input_tokens=50_000, output_tokens=1_000)
    assert costs.usage_cost("claude-haiku-5-5", small) == pytest.approx(50_000 * 0.10 / 1e6 + 1_000 * 0.5 / 1e6)
    large = Usage(input_tokens=150_000, output_tokens=1_000)
    assert costs.usage_cost("claude-haiku-5-5", large) == pytest.approx(150_000 * 0.5 / 1e6 + 1_000 * 2.5 / 1e6)
    assert costs.usage_cost("claude-opus-5-5", usage, cache_write_1h_tokens=1_000_000) == pytest.approx(4 + 8 + 0.2 + 20)
    assert costs.price_for("claude-haiku-4-5-20251001") is costs.PRICES["claude-haiku-4-5"]
    assert costs.price_for("unbekannt") == costs.PRICES["claude-opus-5"]
    assert costs.price_for(None) == costs.PRICES["claude-opus-5"]
    assert costs.usage_cost("claude-opus-5-5", {"input_tokens": 1000}) == pytest.approx(0.004)


def test_usage_from_sdk_objects_and_dicts():
    sdk_usage = SimpleNamespace(input_tokens=5, cache_creation_input_tokens=None, cache_read_input_tokens=7,
                                output_tokens=9, output_tokens_details=SimpleNamespace(thinking_tokens=3))
    assert costs.usage_from_sdk(sdk_usage) == Usage(input_tokens=5, cache_read_tokens=7, output_tokens=9,
                                                    thinking_tokens=3)
    assert costs.usage_from_sdk({"input_tokens": "4", "output_tokens_details": {"thinking_tokens": 2}}) == \
        Usage(input_tokens=4, thinking_tokens=2)
    assert costs.usage_from_sdk(None) == Usage()


def test_budget_caps_max_tokens_and_raises():
    budget = costs.Budget(limit_usd=0.10)
    assert budget.max_tokens_for("claude-opus-5-5", input_tokens=10_000, wanted=32_000) == 2_500
    budget.add(0.06)
    assert budget.remaining == pytest.approx(0.04)
    with pytest.raises(BudgetExceeded, match="Kostenlimit von 0.10 USD"):
        budget.max_tokens_for("claude-opus-5-5", input_tokens=10_000, wanted=32_000)
    budget.add(-5)  # negative costs are ignored
    assert budget.spent_usd == pytest.approx(0.06)
    rich = costs.Budget(limit_usd=10)
    assert rich.max_tokens_for("claude-opus-5-5", input_tokens=10_000, wanted=32_000) == 32_000
    assert costs.estimate_pdf_tokens(2, 1) == 7_000 + 2 * 2_700 + 1_700


# --------------------------------------------------------------------------- schemas


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


@pytest.mark.parametrize("build", [schema.identity_schema, schema.geometry_schema, schema.triage_schema])
def test_schemas_have_no_unions_and_every_field_is_required(build):
    data = build()
    text = json.dumps(data)
    assert "anyOf" not in text and '"null"' not in text and "oneOf" not in text
    for node in _walk(data):
        if node.get("type") == "object" and "properties" in node:
            assert node.get("additionalProperties") is False
            assert set(node["required"]) == set(node["properties"])


def test_schema_is_stable_and_family_enum_matches_the_generator():
    from partforge.footprints import families

    assert schema.identity_schema() == schema.identity_schema()
    assert schema.identity_schema() is not schema.identity_schema()
    geometry = json.dumps(schema.geometry_schema())
    keys = [f.key for f in families()]
    assert schema.family_keys() == [*keys, "other"]
    enum = next(n["properties"]["family"]["enum"] for n in _walk(schema.geometry_schema())
                if "properties" in n and "family" in n["properties"])
    assert enum == [*keys, "other"]
    assert '"package_code"' in geometry and '"devices"' not in geometry
    identity_props = schema.identity_schema()["properties"]
    assert list(identity_props) == ["manufacturer", "document_id", "document_title", "document_date", "devices",
                                    "packages", "warnings"]
    assert len(schema.schema_fingerprint()) == 12


def _property(data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(n["properties"][name] for n in _walk(data) if "properties" in n and name in n["properties"])


def test_enum_fields_are_constrained_in_the_schema_but_parsed_tolerantly():
    """Research §4.2: enum casing is not guaranteed – the API gets the enum, the parser accepts any casing."""
    identity, geometry = schema.identity_schema(), schema.geometry_schema()
    electrical = _property(identity, "electrical_type")
    assert electrical["type"] == "string" and electrical["enum"] == list(schema.ELECTRICAL_TYPES)
    assert "Altium pin type" in electrical["description"]
    assert _property(geometry, "unit")["enum"] == ["mm", "deg"]
    assert _property(geometry, "mounting")["enum"] == ["SMD", "THT"]
    assert _property(geometry, "pad_shape")["enum"] == list(schema.PAD_SHAPES)
    reference = _property(geometry, "row_spacing_reference")
    assert "pad_center_to_component_center" in reference["enum"] and "half" in reference["description"]
    triage = _property(schema.triage_schema(), "categories")
    assert triage["items"]["enum"] == list(schema.TRIAGE_CATEGORIES)
    pin = schema.AiPin.model_validate({"number": "1", "name": "IN", "function": "", "electrical_type": "input",
                                       "active_low": False, "no_connect": False, "group": "", "part": 1})
    assert pin.electrical_type == "input"
    vote = schema.PageVote.model_validate({"page": 3, "categories": ["Pinout", "LAND_PATTERN"]})
    assert vote.categories == ["Pinout", "LAND_PATTERN"]


# --------------------------------------------------------------------------- server tools, error codes, replay delay


def _stop(block_type: str, **fields: Any) -> Any:
    return SimpleNamespace(type="content_block_stop", content_block=SimpleNamespace(type=block_type, **fields))


def test_server_tools_are_sent_and_reported():
    tool = {"type": "web_search_20260318", "name": "web_search", "max_uses": 3, "allowed_callers": ["direct"]}
    req = _request(kind="find", tools=[tool], schema={"type": "object"}, effort="low")
    assert req.params()["tools"] == [tool] and "tools" not in _request().params()
    content = [{"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "OPA656"}},
               {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": []},
               {"type": "text", "text": '{"candidates": [], "note": ""}'}]
    final = anthropic.types.Message.model_validate(_message(content=content, usage={
        "input_tokens": 1000, "output_tokens": 100,
        "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0}}))
    sdk = _FakeSdk([_start("server_tool_use"), _stop("server_tool_use", name="web_search", input={"query": "OPA656"}),
                    _stop("text"), _delta('{"candidates"')], final)
    tools: list[tuple[str, dict[str, Any]]] = []
    response = llm.AnthropicLlmClient(sdk_client=sdk).run(req, on_tool=lambda n, i: tools.append((n, i)))
    assert tools == [("web_search", {"query": "OPA656"})]
    call = sdk.calls[0]
    assert call["tools"] == [tool] and "betas" not in call  # no fallback beta without request.fallbacks
    assert call["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": {"type": "object"}}}
    # tokens plus 10 USD per 1,000 searches
    assert response.cost_usd == pytest.approx((1000 * 4 + 100 * 20) / 1e6 + 2 * 0.01)
    assert response.message["content"][0]["type"] == "server_tool_use"


def test_web_search_fees_in_costs():
    assert costs.server_tool_cost({"server_tool_use": {"web_search_requests": 3}}) == pytest.approx(0.03)
    assert costs.server_tool_cost({"server_tool_use": None}) == 0 and costs.server_tool_cost(None) == 0
    message = _message(usage={"input_tokens": 0, "output_tokens": 0, "server_tool_use": {"web_search_requests": 1}})
    assert costs.message_cost(message, "claude-opus-5-5") == pytest.approx(0.01)
    assert costs.search_input_tokens(0) == costs.SEARCH_PROMPT_TOKENS
    assert costs.search_input_tokens(2) == 3 * costs.SEARCH_PROMPT_TOKENS + 3 * costs.TOKENS_PER_SEARCH


@pytest.mark.parametrize(("error", "code"), [
    (_status_error(anthropic.AuthenticationError, 401), "key_rejected"),
    (_status_error(anthropic.PermissionDeniedError, 403), "model_unavailable"),
    (_status_error(anthropic.NotFoundError, 404), "model_unavailable"),
    (_status_error(anthropic.RateLimitError, 429), "rate_limited"),
    (_status_error(anthropic.InternalServerError, 529), "network"),
    (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://api.anthropic.com")), "network"),
    (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), "network"),
    (_status_error(anthropic.BadRequestError, 400, "Your credit balance is too low"), "unknown"),
])
def test_unavailable_errors_carry_a_code(error, code):
    mapped = llm.map_sdk_error(error, "claude-opus-5-5")
    assert isinstance(mapped, AiUnavailable) and mapped.code == code
    if code == "model_unavailable":
        assert "Claude Opus 5.5" in str(mapped)  # friendly model name


def test_rejected_requests_keep_the_api_status():
    mapped = llm.map_sdk_error(_status_error(anthropic.BadRequestError, 400, "output_config.format: not supported"),
                               "claude-opus-5-5")
    assert isinstance(mapped, ExtractionFailed) and mapped.api_status == 400
    assert "output_config.format" in mapped.api_message
    disabled = llm.map_sdk_error(_status_error(anthropic.BadRequestError, 400, "web search is not enabled for this "
                                                                              "organization"), "claude-opus-5-5")
    assert isinstance(disabled, AiUnavailable) and "Websuche" in str(disabled)


def test_get_client_codes(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PARTFORGE_AI_REPLAY_DIR", raising=False)
    settings = AppSettings()
    settings.ai.api_key_file = str(tmp_path / "missing.txt")
    previous = llm.set_client_factory(None)
    try:
        with pytest.raises(AiUnavailable) as info:
            llm.get_client(settings)
        assert info.value.code == "key_missing"
        assert llm.key_status(settings) == (False, None)
        settings.ai.enabled = False
        with pytest.raises(AiUnavailable) as info:
            llm.get_client(settings)
        assert info.value.code == "ai_disabled"
    finally:
        llm.set_client_factory(previous)


def test_replay_streams_tool_calls_and_waits_between_chunks():
    content = [{"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "x"}},
               {"type": "text", "text": "abcdefghij"}]
    replay = llm.ReplayLlmClient([{"kind": "find", "message": _message(content=content)}], chunk=5, delay_s=0.02)
    tools: list[str] = []
    chunks: list[str] = []
    started = time.perf_counter()
    replay.run(_request(kind="find"), on_text=chunks.append, on_tool=lambda name, data: tools.append(data["query"]))
    elapsed = time.perf_counter() - started
    assert tools == ["x"] and chunks == ["abcde", "fghij"]
    assert elapsed >= (3 + 2 + 2) * 0.02 * 0.9  # first token, tool call, two chunks
    slow = llm.ReplayLlmClient([{"kind": "identity", "message": _message("x" * 50)}], chunk=5, delay_s=5.0)
    flag = {"stop": False}
    started = time.perf_counter()
    with pytest.raises(JobCancelled):
        threading.Timer(0.1, lambda: flag.update(stop=True)).start()
        slow.run(_request(), cancelled=lambda: flag["stop"])
    assert time.perf_counter() - started < 2.0  # the wait stops at once when the job is cancelled
