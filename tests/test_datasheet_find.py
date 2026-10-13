"""„Datenblatt suchen“ (partforge.datasheet.find): web search request, answer parsing, structured-output fallback,
pause_turn, budget, domain classification, the PDF check (ranged GET with SSRF guard) and the API job – all offline
(replayed answers, httpx.MockTransport, fake DNS)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pdf_support import synthetic_pdf

from partforge.config import AppSettings, load_settings
from partforge.datasheet import find, labels, llm, search_costs, store
from partforge.datasheet.errors import BudgetExceeded, ExtractionFailed
from partforge.datasheet.find import FindRequest, ProbeResult, run_find
from partforge.datasheet.llm import ReplayLlmClient
from partforge.datasheet.models import RunInfo
from partforge.jobs import JobManager

DATA = Path(__file__).parent / "data"
FIND_FIXTURES = DATA / "ai_fixtures" / "find"

TI_PDF = "https://www.ti.com/lit/ds/symlink/opa656.pdf"
TI_PAGE = "https://www.ti.com/product/OPA656"
MOUSER = "https://www.mouser.com/datasheet/2/405/opa656-1234.pdf"
ARCHIVE = "https://www.alldatasheet.com/datasheet-pdf/pdf/opa656.html"


def answer(*candidates: dict[str, Any], note: str = "") -> dict[str, Any]:
    return {"candidates": list(candidates), "note": note}


def cand(url: str, source: str = "manufacturer", *, pdf: bool = True, title: str = "OPA656 datasheet",
         note: str = "") -> dict[str, Any]:
    return {"url": url, "title": title, "manufacturer": "Texas Instruments", "part_numbers": ["OPA656"],
            "source": source, "is_pdf_link": pdf, "note": note}


def message(data: dict[str, Any] | str, *, queries: tuple[str, ...] = ("OPA656 datasheet pdf",),
            results: tuple[tuple[str, str], ...] = ((TI_PDF, "OPA656 data sheet | TI.com"), (MOUSER, "Mouser")),
            stop: str = "end_turn", searches: int | None = None, prose: str = "") -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    for index, query in enumerate(queries):
        content.append({"type": "server_tool_use", "id": f"srvtoolu_{index}", "name": "web_search",
                        "input": {"query": query}, "caller": {"type": "direct"}})
        content.append({"type": "web_search_tool_result", "tool_use_id": f"srvtoolu_{index}", "caller": None,
                        "content": [{"type": "web_search_result", "url": url, "title": title,
                                     "encrypted_content": "Eq…", "page_age": None} for url, title in results]})
    if stop != "pause_turn":
        text = data if isinstance(data, str) else json.dumps(data)
        content.append({"type": "text", "text": prose + text, "citations": None})
    return {"id": "msg_find", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
            "stop_reason": stop, "stop_details": None,
            "usage": {"input_tokens": 9000, "output_tokens": 600, "cache_creation_input_tokens": 0,
                      "cache_read_input_tokens": 0,
                      "server_tool_use": {"web_search_requests": len(queries) if searches is None else searches}}}


def call(msg: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "find", "message": msg, "request_id": "req_find"}


def probe_table(**overrides: ProbeResult):
    """Fake PDF check: PDFs for *.pdf, a webpage otherwise; ``overrides`` per URL."""
    seen: list[str] = []
    table = {TI_PDF: ProbeResult(is_pdf=True, size_bytes=853_689, status=206),
             MOUSER: ProbeResult(is_pdf=True, size_bytes=900_000, status=206)}
    table.update({k.replace("__", "/"): v for k, v in overrides.items()})

    def check(url: str) -> ProbeResult:
        seen.append(url)
        if url in table:
            return table[url]
        return ProbeResult(message="Webseite statt PDF", status=200, content_type="text/html")

    check.seen = seen  # type: ignore[attr-defined]
    return check


@pytest.fixture
def settings() -> AppSettings:
    return AppSettings()


# --------------------------------------------------------------------------- the search job


def test_search_request_candidates_and_costs(settings):
    client = ReplayLlmClient([call(message(answer(cand(MOUSER, "distributor"), cand(TI_PAGE, pdf=False),
                                                  cand(TI_PDF), cand(ARCHIVE, "other", pdf=False))))])
    check = probe_table()
    result = run_find(None, FindRequest(query="  OPA656 ", manufacturer="Texas Instruments"), settings=settings,
                      client=client, probe=check)
    request = client.requests[0]
    assert request.kind == "find" and request.model == "claude-opus-5-5" and request.effort == "low"
    assert not request.fallbacks and request.schema is not None and request.schema["required"] == ["candidates", "note"]
    tool = request.tools[0]
    assert tool == {"type": "web_search_20260318", "name": "web_search", "max_uses": 3, "allowed_callers": ["direct"]}
    params = request.params()
    assert params["tools"] == [tool] and params["output_config"]["format"]["type"] == "json_schema"
    prompt = request.messages[0]["content"]
    assert "Datasheet wanted for: OPA656" in prompt and "Manufacturer: Texas Instruments" in prompt
    assert "only this JSON object" in prompt and "never construct" in request.system.lower()
    urls = [c["url"] for c in result["candidates"]]
    # PDFs first (manufacturer before distributor), then the rest; every candidate was checked
    assert urls == [TI_PDF, MOUSER, TI_PAGE, ARCHIVE] and sorted(check.seen) == sorted(urls)
    ti = result["candidates"][0]
    assert ti["source"] == "hersteller" and ti["is_pdf"] and ti["size_bytes"] == 853_689 and ti["in_search_results"]
    assert result["candidates"][1]["source"] == "distributor" and result["candidates"][3]["source"] == "andere"
    assert result["candidates"][2]["check"] == "Webseite statt PDF" and not result["candidates"][2]["in_search_results"]
    assert result["searches"] == ["OPA656 datasheet pdf"] and result["structured"]
    # tokens (Opus 5.5: 4 $/MTok in, 20 $/MTok out) plus 10 $ per 1,000 searches
    assert result["cost_usd"] == pytest.approx(9000 * 4e-6 + 600 * 20e-6 + 0.01, abs=1e-6)
    assert result["model_label"] == "Claude Opus 5.5 · Gründlichkeit niedrig"
    assert result["message"] == "Gefunden: 4 Kandidaten, davon 2 PDFs – 0,058 $"  # below 0.10 $: three decimals
    assert result["runs"][0]["kind"] == "find" and result["runs"][0]["cost_usd"] == pytest.approx(result["cost_usd"])


def test_job_progress_details_and_log(settings):
    client = ReplayLlmClient([call(message(answer(cand(TI_PDF)), queries=("OPA656", "OPA656 datasheet ti.com")))])
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet-find", "Suche", run_find, FindRequest(query="OPA656"), settings=settings,
                               client=client, probe=probe_table())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    detail = job.detail
    assert detail["steps"] == ["search", "check"] and detail["step"] == "check"
    assert detail["searches"] == 2 and detail["queries"] == ["OPA656", "OPA656 datasheet ti.com"]
    assert detail["candidates"] == 1 and detail["cost_usd"] == pytest.approx(job.result["cost_usd"], abs=1e-4)
    assert detail["model_label"] == "Claude Opus 5.5 · Gründlichkeit niedrig" and detail["budget_usd"] == 0.5
    texts = [entry["text"] for entry in job.log]
    assert "Suche: „OPA656 datasheet ti.com“" in texts
    assert job.message.startswith("Gefunden: 1 Kandidat, davon 1 PDF – ")
    assert "claude-opus-5-5" not in job.message and not any("claude-opus" in t for t in texts)


def test_nothing_found_and_blocked_links(settings):
    evil = "http://intranet.example.com/datasheet.pdf"
    client = ReplayLlmClient([call(message(answer(cand(evil)), results=()))])
    check = probe_table(**{evil.replace("/", "__"): ProbeResult(message="Adresse nicht erlaubt (Adresse im lokalen "
                                                                        "Netz)", blocked=True)})
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet-find", "Suche", run_find, FindRequest(query="XYZ123"), settings=settings,
                               client=client, probe=check)
    finally:
        manager.shutdown()
    assert job.status == "done" and job.result["candidates"] == []
    assert job.message.startswith("Kein Datenblatt gefunden – ")
    assert any("Link verworfen" in e["text"] and "lokalen Netz" in e["text"] for e in job.log)


def test_structured_output_rejected_falls_back_to_the_json_instruction(settings):
    """Should the API refuse output_config.format together with the web search (citations), the search repeats once
    without it – the rejected request costs nothing – and the JSON is found in the text."""

    class RejectsFormat(ReplayLlmClient):
        def run(self, request, **kwargs):
            if request.schema is not None:
                self.requests.append(request)
                error = ExtractionFailed("Die Claude-API hat die Anfrage abgelehnt: citations are not supported "
                                         "with output_config.format")
                error.api_status, error.api_message = 400, "citations are not supported with output_config.format"
                raise error
            return super().run(request, **kwargs)

    client = RejectsFormat([call(message(answer(cand(TI_PDF)), prose="Hier ist das Ergebnis:\n```json\n"))])
    result = run_find(None, FindRequest(query="OPA656"), settings=settings, client=client, probe=probe_table())
    assert [r.schema is not None for r in client.requests] == [True, False]
    assert not result["structured"] and [c["url"] for c in result["candidates"]] == [TI_PDF]
    assert len(result["runs"]) == 1  # only the answered request is paid

    class AlwaysRejected(ReplayLlmClient):
        def run(self, request, **kwargs):
            self.requests.append(request)
            error = ExtractionFailed("Die Claude-API hat die Anfrage abgelehnt: max_uses: invalid")
            error.api_status, error.api_message = 400, "tools.0.max_uses: invalid"
            raise error

    rejected = AlwaysRejected([])
    with pytest.raises(ExtractionFailed, match="abgelehnt"):
        run_find(None, FindRequest(query="OPA656"), settings=settings, client=rejected, probe=probe_table())
    assert len(rejected.requests) == 1  # no retry for other rejections


def test_pause_turn_is_continued_with_the_content_echoed(settings):
    paused = message({}, queries=("OPA656",), stop="pause_turn")
    final = message(answer(cand(TI_PDF)), queries=("OPA656 ti.com",))
    client = ReplayLlmClient([call(paused), call(final)])
    result = run_find(None, FindRequest(query="OPA656"), settings=settings, client=client, probe=probe_table())
    first, second = client.requests
    assert len(first.messages) == 1 and [m["role"] for m in second.messages] == ["user", "assistant"]
    echoed = second.messages[1]["content"]
    assert [b["type"] for b in echoed] == ["server_tool_use", "web_search_tool_result"]
    assert "caller" not in echoed[1]  # empty fields are not echoed
    assert echoed[1]["content"][0]["encrypted_content"] == "Eq…"  # everything else unchanged
    assert result["searches"] == ["OPA656", "OPA656 ti.com"] and len(result["runs"]) == 2
    assert result["cost_usd"] == pytest.approx(2 * (9000 * 4e-6 + 600 * 20e-6 + 0.01), abs=1e-6)


@pytest.mark.parametrize(("stop", "text"), [("refusal", "abgelehnt"), ("max_tokens", "abgeschnitten")])
def test_unusable_answers(settings, stop, text):
    client = ReplayLlmClient([call(message(answer(), stop=stop))])
    with pytest.raises(ExtractionFailed, match=text):
        run_find(None, FindRequest(query="OPA656"), settings=settings, client=client, probe=probe_table())
    garbage = ReplayLlmClient([call(message("Leider nichts gefunden."))])
    with pytest.raises(ExtractionFailed, match="keine lesbare Kandidatenliste"):
        run_find(None, FindRequest(query="OPA656"), settings=settings, client=garbage, probe=probe_table())


def test_budget_caps_searches_and_tokens(settings):
    searches, tokens = find.plan(settings, FindRequest(query="x"))
    assert (searches, tokens) == (3, find.FIND_MAX_TOKENS)
    settings.ai.max_cost_per_import_usd = 0.12
    searches, tokens = find.plan(settings, FindRequest(query="x"))
    assert searches < 3 and find.FIND_MIN_TOKENS <= tokens <= find.FIND_MAX_TOKENS
    settings.ai.max_cost_per_import_usd = 0.02
    with pytest.raises(BudgetExceeded, match="Kostenlimit von 0.02 USD"):
        find.plan(settings, FindRequest(query="x"))
    settings.ai.max_cost_per_import_usd = 2.0
    assert find.plan(settings, FindRequest(query="x"), budget_usd=10)[0] == 3  # never more than FIND_MAX_COST_USD


def test_ai_switched_off(settings):
    settings.ai.enabled = False
    from partforge.datasheet.errors import AiUnavailable

    with pytest.raises(AiUnavailable) as info:
        run_find(None, FindRequest(query="OPA656"), settings=settings, client=ReplayLlmClient([]))
    assert info.value.code == "ai_disabled"


def test_request_validation():
    assert FindRequest(query=" OPA656\x07 ", manufacturer="  ").model_dump() == {
        "query": "OPA656", "manufacturer": None, "model": None}
    with pytest.raises(ValueError, match="Teilenummer"):
        FindRequest(query=" \x07 ")
    with pytest.raises(ValueError, match="Modellbezeichnung"):
        FindRequest(query="x", model="claude; rm")


@pytest.mark.parametrize(("url", "manufacturer", "claude", "expected"), [
    ("https://www.ti.com/lit/ds/symlink/opa656.pdf", "Texas Instruments", "other", "hersteller"),
    ("https://www.analog.com/media/en/LTC6244.pdf", None, "other", "hersteller"),
    ("https://ww1.microchip.com/downloads/25AA02E48.pdf", "Microchip Technology", "manufacturer", "hersteller"),
    ("https://www.mouser.de/datasheet/2/x.pdf", "Texas Instruments", "manufacturer", "distributor"),
    ("https://www.alldatasheet.com/x.html", None, "manufacturer", "andere"),
    ("https://www.unbekannt-hersteller.example/ds.pdf", None, "manufacturer", "hersteller"),
    ("https://files.example.org/ds.pdf", None, "distributor", "distributor"),
    ("https://files.example.org/ds.pdf", None, "other", "andere"),
    ("https://evilti.com/opa656.pdf", "Texas Instruments", "other", "andere"),
])
def test_classify_source(url, manufacturer, claude, expected):
    assert find.classify_source(url, manufacturer, claude) == expected


# --------------------------------------------------------------------------- PDF check (ranged GET)


def public(host: str, port: int) -> list[str]:
    return {"internal.example.com": ["10.1.2.3"], "rebind.example.com": ["93.184.216.34", "127.0.0.1"]}.get(
        host, ["93.184.216.34"])


def transport(handler):
    return httpx.MockTransport(handler)


def test_probe_reads_only_the_first_bytes_of_a_pdf():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(206, content=b"%PDF-1.7\n" + b"0" * 30_000,
                              headers={"content-type": "application/pdf", "content-range": "bytes 0-16383/853689"})

    result = find.probe_pdf(TI_PDF, transport=transport(handler), resolve=public)
    assert result.is_pdf and result.size_bytes == 853_689 and result.status == 206 and result.message is None
    assert seen[0].headers["range"] == f"bytes=0-{find.PROBE_BYTES - 1}"
    assert seen[0].headers["user-agent"].startswith("Mozilla/5.0") and result.final_url is None


@pytest.mark.parametrize(("response", "message"), [
    (httpx.Response(200, text="<html>…</html>", headers={"content-type": "text/html"}), "Webseite statt PDF"),
    (httpx.Response(200, content=b"PK\x03\x04", headers={"content-type": "application/zip"}), "Kein PDF"),
    (httpx.Response(403, text="nope"), "HTTP 403 (Zugriff verweigert"),
    (httpx.Response(404, text="weg"), "HTTP 404"),
    (httpx.Response(200, content=b"%PDF-1.4", headers={"content-length": str(200 * 2**20)}), "zu groß"),
])
def test_probe_reports_why_it_is_no_usable_pdf(response, message):
    result = find.probe_pdf("https://www.example.com/x.pdf", transport=transport(lambda r: response), resolve=public)
    assert message in (result.message or "") and not result.blocked
    assert result.is_pdf == (b"%PDF" in response.content)


def test_probe_follows_redirects_but_never_into_the_local_network():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/go":
            return httpx.Response(302, headers={"location": "https://cdn.example.com/files/a.pdf"})
        if request.url.path == "/evil":
            return httpx.Response(301, headers={"location": "http://127.0.0.1:8080/admin"})
        if request.url.path == "/evil2":
            return httpx.Response(307, headers={"location": "https://internal.example.com/x.pdf"})
        if request.url.path == "/loop":
            return httpx.Response(302, headers={"location": "/loop"})
        return httpx.Response(200, content=b"%PDF-1.5 x", headers={"content-type": "application/pdf"})

    ok = find.probe_pdf("https://www.example.com/go", transport=transport(handler), resolve=public)
    assert ok.is_pdf and ok.final_url == "https://cdn.example.com/files/a.pdf"
    evil = find.probe_pdf("https://www.example.com/evil", transport=transport(handler), resolve=public)
    assert evil.blocked and not evil.is_pdf and "eigenen Rechners" in evil.message
    evil2 = find.probe_pdf("https://www.example.com/evil2", transport=transport(handler), resolve=public)
    assert evil2.blocked and "lokalen Netz" in evil2.message
    loop = find.probe_pdf("https://www.example.com/loop", transport=transport(handler), resolve=public)
    assert not loop.is_pdf and "Weiterleitungen" in loop.message


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x.pdf", "http://[::1]/x.pdf", "http://10.0.0.7/x.pdf", "http://192.168.1.10/x.pdf",
    "http://169.254.169.254/latest/meta-data", "http://[fe80::1]/x.pdf", "http://0.0.0.0/x.pdf",
    "http://[::ffff:127.0.0.1]/x.pdf", "http://100.64.0.1/x.pdf", "http://localhost/x.pdf", "http://fileserver/x.pdf",
    "http://nas.local/x.pdf", "https://internal.example.com/x.pdf", "https://rebind.example.com/x.pdf",
    "ftp://example.com/x.pdf", "file:///C:/x.pdf", "https://user:pw@example.com/x.pdf",
])
def test_probe_refuses_non_public_addresses(url):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must never be reached
        raise AssertionError(f"verbotene Anfrage an {request.url}")

    result = find.probe_pdf(url, transport=transport(handler), resolve=public)
    assert result.blocked and not result.is_pdf and result.message


def test_probe_network_problems_are_not_blocking():
    def unknown(host: str, port: int) -> list[str]:
        raise OSError("getaddrinfo failed")

    result = find.probe_pdf("https://www.gibt-es-nicht.example/x.pdf", resolve=unknown)
    assert not result.blocked and result.message == "Adresse Server nicht gefunden"

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("langsam", request=request)

    assert find.probe_pdf(TI_PDF, transport=transport(slow), resolve=public).message == \
        "Zeitüberschreitung bei der Prüfung"

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("kein Netz", request=request)

    assert "nicht erreichbar" in (find.probe_pdf(TI_PDF, transport=transport(broken), resolve=public).message or "")


@pytest.mark.windows
def test_probe_checks_the_connected_peer(monkeypatch):
    """DNS rebinding: the address actually connected must be public as well."""
    monkeypatch.setattr(find, "_peer", lambda response: "127.0.0.1")
    result = find.probe_pdf(TI_PDF, transport=transport(lambda r: httpx.Response(200, content=b"%PDF-1.4")),
                            resolve=public)
    assert result.blocked and not result.is_pdf


def test_the_peer_check_trusts_an_environment_proxy(monkeypatch):
    """Behind a proxy the connected peer is the proxy (often a private address) – only the server is checked."""
    for name in ("NO_PROXY", "no_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:8080")
    monkeypatch.setattr(find, "_peer", lambda response: "10.0.0.1")
    pdf = transport(lambda r: httpx.Response(200, content=b"%PDF-1.4"))
    assert find.probe_pdf(TI_PDF, transport=pdf, resolve=public).is_pdf
    monkeypatch.setenv("NO_PROXY", "ti.com")  # not proxied: the peer must be public
    assert find.probe_pdf(TI_PDF, transport=pdf, resolve=public).blocked
    assert find.probe_pdf("https://internal.example.com/x.pdf", transport=pdf, resolve=public).blocked


@pytest.mark.parametrize(("address", "problem"), [
    ("8.8.8.8", None), ("2606:4700:4700::1111", None), ("127.0.0.1", "eigenen Rechners"), ("::1", "eigenen Rechners"),
    ("10.1.1.1", "lokalen Netz"), ("172.16.5.4", "lokalen Netz"), ("fd00::1", "lokalen Netz"),
    ("169.254.1.1", "Link-Local"), ("fe80::1%eth0", "Link-Local"), ("224.0.0.1", "öffentliche"),
    ("0.0.0.0", "lokalen Netz"), ("::ffff:192.168.0.1", "lokalen Netz"), ("kaputt", "ungültige"),
])
def test_address_problem(address, problem):
    result = find.address_problem(address)
    assert (result is None) if problem is None else (problem in (result or ""))


# --------------------------------------------------------------------------- answer parsing


def test_parse_answer_prefers_the_text_after_the_last_tool_block():
    msg = message(answer(cand(TI_PDF)), prose="")
    msg["content"].insert(0, {"type": "text", "text": "Ich suche nach dem Datenblatt."})
    assert find.parse_answer(msg).candidates[0].url == TI_PDF
    wrapped = message(f"Ergebnis:\n```json\n{json.dumps(answer(cand(MOUSER)))}\n```\nViel Erfolg.")
    assert find.parse_answer(wrapped).candidates[0].url == MOUSER
    split = message("")
    text = json.dumps(answer(cand(TI_PDF)))
    split["content"][-1:] = [{"type": "text", "text": text[:40]}, {"type": "text", "text": text[40:]}]
    assert find.parse_answer(split).candidates[0].url == TI_PDF  # citations split the text into blocks


# --------------------------------------------------------------------------- API


@pytest.fixture
def ai(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PARTFORGE_AI_REPLAY_DIR", raising=False)
    current = load_settings()
    monkeypatch.setattr(current.ai, "api_key_file", str(tmp_path / "kein-key.txt"))
    monkeypatch.setattr(current.ai, "enabled", True)
    monkeypatch.setattr(current.ai, "max_cost_per_import_usd", 2.0)
    previous = llm.set_client_factory(None)
    monkeypatch.setattr(find, "_default_probe", probe_table())
    yield current.ai
    llm.set_client_factory(previous)


def wait(client, job: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError("Job läuft noch")


def test_api_find_needs_no_library_and_reports_503_with_a_code(bare_client, ai):
    unavailable = bare_client.post("/api/datasheets/find", json={"query": "OPA656"})
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "key_missing" and "Schlüssel" in unavailable.json()["detail"][
        "message"]
    assert bare_client.post("/api/datasheets/find", json={"query": " "}).status_code == 422
    llm.set_client_factory(lambda: ReplayLlmClient([call(message(answer(cand(TI_PDF))))]))
    started = bare_client.post("/api/datasheets/find", json={"query": "OPA656", "manufacturer": "Texas Instruments"})
    assert started.status_code == 200, started.text
    job = wait(bare_client, started.json()["job"])
    assert job["kind"] == "datasheet-find" and job["status"] == "done", job["error"]
    assert job["title"] == "Datenblatt suchen: OPA656 (Texas Instruments)"
    assert job["result"]["candidates"][0]["url"] == TI_PDF and job["message"].startswith("Gefunden: 1 Kandidat")
    ai.max_cost_per_import_usd = 0.01
    too_cheap = bare_client.post("/api/datasheets/find", json={"query": "OPA656"})
    assert too_cheap.status_code == 400 and "Kostenlimit" in too_cheap.json()["detail"]
    ai.enabled = False
    off = bare_client.post("/api/datasheets/find", json={"query": "OPA656"})
    assert off.status_code == 503 and off.json()["detail"]["code"] == "ai_disabled"


def test_api_import_of_a_found_link_carries_the_search_costs(client, ai, monkeypatch):
    llm.set_client_factory(lambda: ReplayLlmClient([call(message(answer(cand(TI_PDF))))]))
    found = wait(client, client.post("/api/datasheets/find", json={"query": "OPA656"}).json()["job"])
    search_cost = found["result"]["cost_usd"]
    data = synthetic_pdf(["Synthetic download for search-cost tracking"])
    monkeypatch.setattr(store, "download_pdf", lambda url, **kw: (data, "opa656.pdf", url))
    body = {"url": TI_PDF, "search_job_id": found["id"]}
    imported = wait(client, client.post("/api/datasheets/from-url", json=body).json()["job"])
    assert imported["status"] == "done", imported["error"]
    detail = client.get(f"/api/datasheets/{imported['result']['datasheet_id']}").json()
    assert [r["kind"] for r in detail["runs"]] == ["find"] and detail["cost_usd"] == pytest.approx(search_cost)
    assert any("Kosten der Datenblattsuche" in e["text"] for e in imported["log"])
    again = wait(client, client.post("/api/datasheets/from-url", json=body).json()["job"])
    assert again["status"] == "done"
    detail = client.get(f"/api/datasheets/{imported['result']['datasheet_id']}").json()
    assert len(detail["runs"]) == 1  # a search is attached once


# --------------------------------------------------------------------------- K15: costs of cancelled/failed searches


class _CancelAfterFirstSearch(ReplayLlmClient):
    """The user cancels as soon as Claude ran its first web search (while the answer still streams)."""

    def run(self, request, *, cancelled=None, on_tool=None, **kwargs):
        stop = {"now": False}

        def tool(name: str, data: dict[str, Any]) -> None:
            stop["now"] = True
            if on_tool is not None:
                on_tool(name, data)

        return super().run(request, cancelled=lambda: stop["now"], on_tool=tool, **kwargs)


def _run_job(fn, *args, **kwargs):
    manager = JobManager(max_workers=1)
    try:
        return manager.run_sync("datasheet-find", "Suche", fn, *args, **kwargs)
    finally:
        manager.shutdown()


def test_a_cancelled_search_keeps_the_cost_of_the_running_request(settings):
    """K15: cancelled while Claude answers – the input, the streamed output and the started search are paid; the job
    shows and the ledger keeps them."""
    client = _CancelAfterFirstSearch([call(message(answer(cand(TI_PDF))))], chunk=50)
    job = _run_job(run_find, FindRequest(query="OPA656"), settings=settings, client=client, probe=probe_table())
    assert job.status == "cancelled"
    entry = search_costs.get(job.id)
    assert entry is not None and entry.status == "cancelled" and entry.query == "OPA656" and len(entry.runs) == 1
    run = entry.runs[0]
    assert run.kind == "find" and run.error == llm.CANCELLED_RUN_ERROR and run.usage.input_tokens == 9000
    assert run.usage.output_tokens < 600  # only what was streamed
    assert run.cost_usd == pytest.approx(9000 * 4e-6 + run.usage.output_tokens * 20e-6 + 0.01)  # + the search
    assert entry.cost_usd == pytest.approx(run.cost_usd) and entry.attached_to is None
    assert job.detail["cost_usd"] == pytest.approx(run.cost_usd, abs=1e-4)  # shown at the cancelled search
    assert job.message == f"Suche abgebrochen – bisherige Kosten {labels.usd(run.cost_usd)} gespeichert."
    assert any(e["text"].startswith("Bisherige Kosten der Suche gespeichert") for e in job.log)
    assert search_costs.claim(job.id, "0123456789abcdef") is None  # nothing to import from a cancelled search


def test_a_failed_search_keeps_its_costs(settings):
    refused = message(answer(), stop="refusal")
    job = _run_job(run_find, FindRequest(query="OPA656"), settings=settings, client=ReplayLlmClient([call(refused)]),
                   probe=probe_table())
    assert job.status == "failed" and "abgelehnt" in job.error
    entry = search_costs.get(job.id)
    assert entry is not None and entry.status == "failed" and "abgelehnt" in entry.message
    assert [r.error for r in entry.runs] == ["Claude hat die Suche abgelehnt."] and entry.cost_usd > 0.04
    assert job.detail["cost_usd"] == pytest.approx(entry.cost_usd, abs=1e-4)


def test_a_finished_search_is_in_the_ledger(settings):
    job = _run_job(run_find, FindRequest(query="OPA656", manufacturer="Texas Instruments"), settings=settings,
                   client=ReplayLlmClient([call(message(answer(cand(TI_PDF))))]), probe=probe_table())
    assert job.status == "done", job.error
    entry = search_costs.get(job.id)
    assert entry.status == "done" and entry.manufacturer == "Texas Instruments" and entry.message == job.message
    assert entry.cost_usd == pytest.approx(job.result["cost_usd"]) and len(entry.runs) == 1


def test_the_search_cost_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("PARTFORGE_HOME", str(tmp_path))
    run = RunInfo(kind="find", model="claude-opus-5-5", cost_usd=0.05)
    first = search_costs.record(search_costs.SearchCost(job_id="a1", query="X", status="done", created="", runs=[run]))
    assert first.cost_usd == 0.05 and first.created and search_costs.ledger_path().parent == tmp_path / "ai"
    assert search_costs.claim("a1", "ds1") is not None and search_costs.get("a1").attached_to == "ds1"
    assert search_costs.claim("a1", "ds2") is None  # attached once
    search_costs.record(first.model_copy(update={"message": "neu"}))  # the same job again: replaced, still attached
    assert [s.attached_to for s in search_costs.entries()] == ["ds1"]
    for i in range(search_costs.MAX_ENTRIES + 5):
        search_costs.record(search_costs.SearchCost(job_id=f"j{i}", query="Y", status="failed", created="", runs=[run]))
    kept = search_costs.entries()
    assert len(kept) == search_costs.MAX_ENTRIES and kept[-1].job_id == f"j{search_costs.MAX_ENTRIES + 4}"
    search_costs.ledger_path().write_text("{kaputt", encoding="utf-8")
    assert search_costs.entries() == [] and (tmp_path / "ai" / "search-costs.corrupt.json").is_file()
    search_costs.ledger_path().write_bytes(b"\xff\xfe\x00kaputt")  # not even UTF-8
    assert search_costs.entries() == [] and search_costs.get("a1") is None


def test_api_search_costs_survive_a_restart(client, ai, monkeypatch):
    """K15: the in-memory job list is gone (restart, or the job was pruned) – the import still gets the costs, once."""
    from partforge.api import routes_datasheets
    from partforge.jobs import jobs as real_jobs

    llm.set_client_factory(lambda: ReplayLlmClient([call(message(answer(cand(TI_PDF))))]))
    found = wait(client, client.post("/api/datasheets/find", json={"query": "OPA656"}).json()["job"])
    assert found["status"] == "done", found["error"]

    class Restarted:
        """The job manager of a new process: it knows no earlier jobs."""

        def get(self, job_id: str) -> None:
            return None

        def __getattr__(self, name: str) -> Any:
            return getattr(real_jobs, name)

    monkeypatch.setattr(routes_datasheets, "jobs", Restarted())
    data = synthetic_pdf(["Synthetic download for persisted search costs"])
    monkeypatch.setattr(store, "download_pdf", lambda url, **kw: (data, "opa656.pdf", url))
    body = {"url": TI_PDF, "search_job_id": found["id"]}
    imported = wait(client, client.post("/api/datasheets/from-url", json=body).json()["job"])
    assert imported["status"] == "done", imported["error"]
    ds = imported["result"]["datasheet_id"]
    detail = client.get(f"/api/datasheets/{ds}").json()
    assert [r["kind"] for r in detail["runs"]] == ["find"] and detail["cost_usd"] == pytest.approx(
        found["result"]["cost_usd"])
    assert search_costs.get(found["id"]).attached_to == ds
    again = wait(client, client.post("/api/datasheets/from-url", json=body).json()["job"])
    assert again["status"] == "done" and len(client.get(f"/api/datasheets/{ds}").json()["runs"]) == 1


def test_api_an_unusable_ledger_never_stops_the_import(client, ai, monkeypatch):
    """The costs then come from the finished job (as before the ledger) – the import itself always runs."""
    llm.set_client_factory(lambda: ReplayLlmClient([call(message(answer(cand(TI_PDF))))]))
    found = wait(client, client.post("/api/datasheets/find", json={"query": "OPA656"}).json()["job"])

    def broken(*args: Any, **kwargs: Any) -> None:
        raise PermissionError("gesperrt")

    monkeypatch.setattr(search_costs, "claim", broken)
    data = synthetic_pdf(["Synthetic download with an unusable cost ledger"])
    monkeypatch.setattr(store, "download_pdf", lambda url, **kw: (data, "opa656.pdf", url))
    imported = wait(client, client.post("/api/datasheets/from-url",
                                        json={"url": TI_PDF, "search_job_id": found["id"]}).json()["job"])
    assert imported["status"] == "done", imported["error"]
    detail = client.get(f"/api/datasheets/{imported['result']['datasheet_id']}").json()
    assert [r["kind"] for r in detail["runs"]] == ["find"]


# --------------------------------------------------------------------------- recording tool and the fixture


def test_record_fixture_strips_encrypted_blobs_and_keeps_the_checks(tmp_path, monkeypatch):
    """The recording tool (used once with a real key) – here with a stand-in for the SDK client."""
    recorded = message(answer(cand(TI_PDF)))

    class FakeAnthropic(ReplayLlmClient):
        def __init__(self, key: str, **_kw: Any) -> None:
            assert key == "sk-test-recording"
            super().__init__([call(recorded)])

    import partforge.config as config

    monkeypatch.setattr(config, "read_api_key", lambda settings=None: "sk-test-recording")
    monkeypatch.setattr(llm, "AnthropicLlmClient", FakeAnthropic)
    monkeypatch.setattr(find, "probe_pdf", lambda url: ProbeResult(is_pdf=True, size_bytes=123, status=206))
    target = tmp_path / "find" / "opa656.json"
    result = find.record_fixture("OPA656", "Texas Instruments", target, settings=AppSettings(),
                                 downloads={TI_PDF: "../../corpus/pdfs/opa656.pdf"})
    fixture = json.loads(target.read_text(encoding="utf-8"))
    assert fixture["kind"] == "find" and fixture["query"] == "OPA656" and fixture["tool"] == "web_search_20260318"
    assert fixture["probes"][TI_PDF]["is_pdf"] and fixture["downloads"] == {TI_PDF: "../../corpus/pdfs/opa656.pdf"}
    text = target.read_text(encoding="utf-8")
    assert "Eq…" not in text and "<entfernt>" in text and "sk-test" not in text
    assert fixture["result"]["candidates"][0]["url"] == TI_PDF and "runs" not in fixture["result"]
    assert result["cost_usd"] > 0 and not list(target.parent.glob("*.tmp.json"))


@pytest.mark.skipif(not (FIND_FIXTURES / "opa656.json").is_file(), reason="Aufzeichnung fehlt")
def test_recorded_search_replays(settings):
    """The one real search (OPA656, Texas Instruments) replays through the pipeline with its recorded checks."""
    fixture = json.loads((FIND_FIXTURES / "opa656.json").read_text(encoding="utf-8"))
    assert fixture["query"] == "OPA656" and "sk-ant" not in json.dumps(fixture)
    recorded = {url: ProbeResult.from_json(p) for url, p in fixture["probes"].items()}
    client = ReplayLlmClient(fixture["calls"])
    result = run_find(None, FindRequest(query="OPA656", manufacturer="Texas Instruments"), settings=settings,
                      client=client, probe=lambda url: recorded.get(url, ProbeResult(message="nicht aufgezeichnet")))
    assert client.remaining == []
    best = result["candidates"][0]
    assert best["is_pdf"] and best["source"] == "hersteller" and "ti.com" in best["url"]
    assert result["cost_usd"] == pytest.approx(sum(c["message"] and llm.build_response(
        c["message"], client.requests[0], request_id=None, duration_s=0).cost_usd for c in fixture["calls"]), abs=1e-6)
    assert result["cost_usd"] <= find.FIND_MAX_COST_USD


# --------------------------------------------------------------------------- manufacturer addresses


def test_manufacturer_address_is_offered_only_when_it_is_a_pdf(settings):
    """Claude found only the product page: the stable TI address is checked and offered because it is a PDF."""
    def search() -> ReplayLlmClient:
        return ReplayLlmClient([call(message(answer(cand(TI_PAGE, pdf=False), cand(MOUSER, "distributor"))))])

    check = probe_table()
    result = run_find(None, FindRequest(query="OPA656", manufacturer="Texas Instruments"), settings=settings,
                      client=search(), probe=check)
    first = result["candidates"][0]
    assert first["url"] == TI_PDF and first["derived"] and first["source"] == "hersteller"
    assert first["is_pdf"] and not first["in_search_results"] and "Dateimuster" in first["note"]
    assert [c["url"] for c in result["candidates"]] == [TI_PDF, MOUSER, TI_PAGE]
    missing = probe_table(**{TI_PDF.replace("/", "__"): ProbeResult(status=404, message="HTTP 404")})
    result = run_find(None, FindRequest(query="OPA656", manufacturer="Texas Instruments"), settings=settings,
                      client=search(), probe=missing)
    assert TI_PDF in missing.seen and TI_PDF not in [c["url"] for c in result["candidates"]]
    official = probe_table()
    run_find(None, FindRequest(query="OPA656"), settings=settings,
             client=ReplayLlmClient([call(message(answer(cand(TI_PDF))))]), probe=official)
    assert official.seen == [TI_PDF]  # Claude found the manufacturer PDF: nothing derived


@pytest.mark.parametrize(("manufacturer", "parts", "expected"), [
    ("Texas Instruments", ["OPA656U/2K5", "OPA656", "opa656"], ["https://www.ti.com/lit/ds/symlink/opa656.pdf"]),
    ("TI", ["LM358", "LM358A", "LM358B"], ["https://www.ti.com/lit/ds/symlink/lm358.pdf",
                                           "https://www.ti.com/lit/ds/symlink/lm358a.pdf"]),
    ("STMicroelectronics", ["STM32F103C8"], ["https://www.st.com/resource/en/datasheet/stm32f103c8.pdf"]),
    ("NXP Semiconductors", ["pca9555"], ["https://www.nxp.com/docs/en/data-sheet/PCA9555.pdf"]),
    ("ON Semiconductor", ["MC7805"], ["https://www.onsemi.com/pdf/datasheet/mc7805-d.pdf"]),
    ("Vishay", ["CRCW0603"], []),
    (None, ["OPA656"], []),
    ("Texas Instruments", ["OPA 656", "../etc", ""], []),
])
def test_derived_links(manufacturer, parts, expected):
    assert find.derived_links(manufacturer, parts) == expected


def test_older_models_get_the_basic_search_tool():
    assert find.search_tool("claude-opus-5-5", 3) == {"type": "web_search_20260318", "name": "web_search",
                                                      "max_uses": 3, "allowed_callers": ["direct"]}
    assert find.search_tool("claude-haiku-4-5-20251001", 2) == {"type": "web_search_20250305", "name": "web_search",
                                                                "max_uses": 2}
    assert find.search_tool("claude-sonnet-4-6", 1)["type"] == "web_search_20260318"
