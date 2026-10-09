"""Structured progress (job.detail), German outcome sentences and friendly model names of the datasheet jobs, and
the cost estimate before an analysis (no Claude call)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest

from partforge.config import AppSettings, load_settings
from partforge.datasheet import costs, labels, llm, store
from partforge.datasheet.estimate import estimate
from partforge.datasheet.extract import EXTRACTION_STEPS, ExtractOptions, run_extraction
from partforge.datasheet.llm import ReplayLlmClient
from partforge.db import registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.jobs import JobContext, JobManager

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
PDFS = DATA / "corpus" / "pdfs"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not PDFS.is_dir(), reason="Testdaten fehlen")


def fixture(stem: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))


def wait(client, job: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError("Job läuft noch")


@pytest.fixture
def details(monkeypatch) -> list[dict[str, Any]]:
    """Every JobContext.detail call in order."""
    seen: list[dict[str, Any]] = []
    original = JobContext.detail

    def spy(self: JobContext, **fields: Any) -> None:
        seen.append(dict(fields))
        original(self, **fields)

    monkeypatch.setattr(JobContext, "detail", spy)
    return seen


@pytest.fixture
def ai(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PARTFORGE_AI_REPLAY_DIR", raising=False)
    settings = load_settings()
    monkeypatch.setattr(settings.ai, "api_key_file", str(tmp_path / "kein-key.txt"))
    monkeypatch.setattr(settings.ai, "enabled", True)
    monkeypatch.setattr(settings.ai, "max_cost_per_import_usd", 2.0)
    previous = llm.set_client_factory(None)
    yield settings
    llm.set_client_factory(previous)


# --------------------------------------------------------------------------- extraction job


def test_extraction_reports_steps_pages_counters_costs_and_outcome(workspace, details):
    fx = fixture("opa656")
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], ws=workspace)
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id, ExtractOptions(vision="off"),
                               ws=workspace, client=ReplayLlmClient(fx["calls"], chunk=300), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    steps = [d["step"] for d in details if "step" in d]
    assert [s for i, s in enumerate(steps) if i == 0 or steps[i - 1] != s] == list(EXTRACTION_STEPS)
    assert all(d.get("step_label") for d in details if "step" in d)
    identity = next(d for d in details if d.get("step") == "identity")
    geometry = next(d for d in details if d.get("step") == "geometry")
    assert identity["pages_active"] == [1, 2, 17, 18] and geometry["pages_active"] == [17, 21, 22, 23, 24]
    live = [d["counters"] for d in details if "counters" in d]
    assert len(live) >= 3 and live[0]["mpns"] < 14  # streamed while Claude answers
    costs_seen = [d["cost_usd"] for d in details if "cost_usd" in d]
    assert costs_seen == sorted(costs_seen) and costs_seen[0] == 0 and costs_seen[-1] > 0.2
    final = job.detail
    assert final["datasheet_id"] == rec.id and final["steps"] == list(EXTRACTION_STEPS) and final["step"] == "save"
    assert final["pages_total"] == 25 and final["pages_selected"] == [1, 2, 17, 18, 21, 22, 23, 24]
    assert final["pages_active"] == [] and final["budget_usd"] == 2.0
    assert final["counters"]["mpns"] == 14 and final["counters"]["pins"] == 13 and final["counters"]["packages"] == 2
    assert final["counters"]["parameters"] > 0 and final["counters"]["dimensions"] > 0
    assert final["cost_usd"] == pytest.approx(job.result["cost_usd"], abs=1e-4)
    assert final["model_label"] == "Claude Opus 5.5 · Gründlichkeit niedrig" == job.result["model_label"]
    assert job.message == "Analyse fertig: 14 Bestellvarianten, 13 Pins, 2 Gehäuse – 0,23 $" == job.result["message"]
    texts = [e["text"] for e in job.log]
    reading = "Claude Opus 5.5 · Gründlichkeit niedrig liest Bauteile und Pins (4 Seiten)"
    assert any(t.startswith(reading) for t in texts)
    assert not any("claude-opus-5-5" in t for t in texts)  # friendly names only
    assert any(t.startswith("Ergebnis gespeichert. Kosten dieses Imports") for t in texts)  # German log lines stay
    assert not any("Aufwand" in t for t in [*texts, job.message, final["model_label"]])  # K4: one term


def test_the_effort_is_called_gruendlichkeit_everywhere(workspace):
    """K4: „Gründlichkeit“ (as in Einstellungen › KI) – also for a model that takes no effort level."""
    fx = fixture("opa656")
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], ws=workspace)
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id,
                               ExtractOptions(vision="off", model="claude-haiku-4-5"), ws=workspace,
                               client=ReplayLlmClient(fx["calls"]), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    texts = [e["text"] for e in job.log]
    assert "Das Modell Claude Haiku 4.5 lässt keine Gründlichkeit wählen – Anfrage mit der Standardeinstellung " \
           "des Modells." in texts
    assert job.detail["model_label"] == "Claude Haiku 4.5"  # no level: just the model
    assert not any("Aufwand" in t for t in [*texts, job.message])
    assert ExtractOptions.model_json_schema()["properties"]["effort"]["description"].startswith("Gründlichkeit")
    assert labels.run_label("claude-sonnet-5-5", "medium") == "Claude Sonnet 5.5 · Gründlichkeit mittel"
    assert labels.run_label("claude-opus-5-5", "high") == "Claude Opus 5.5 · Gründlichkeit hoch"


def test_failed_analysis_outcome(workspace):
    fx = fixture("opa656")
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], ws=workspace)
    refused = json.loads(json.dumps(fx["calls"][1]))
    refused["message"]["content"], refused["message"]["stop_reason"] = [], "refusal"
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id, ExtractOptions(vision="off"),
                               ws=workspace, client=ReplayLlmClient([fx["calls"][0], refused]), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "failed" and job.error_type == "ExtractionFailed"
    assert job.message == job.error and "abgelehnt" in job.message  # the outcome of a failed job is its error
    assert any(e["text"].startswith("Bisherige Kosten dieses Imports gespeichert") for e in job.log)
    assert job.detail["cost_usd"] > 0 and job.detail["step"] == "geometry"


def test_read_and_url_jobs_report_their_outcome(client, ai, monkeypatch, details):
    upload = client.post("/api/datasheets", files={"file": ("opa656.pdf", (PDFS / "opa656.pdf").read_bytes(),
                                                            "application/pdf")})
    read = wait(client, upload.json()["job"])
    assert read["message"] == "Datenblatt gelesen: 25 Seiten, davon 4 ohne Textebene"
    assert read["detail"]["steps"] == ["read"] and read["detail"]["pages_total"] == 25
    assert read["result"] == {"datasheet_id": upload.json()["datasheet"]["id"], "page_count": 25}
    data = (PDFS / "ADG736.pdf").read_bytes()
    monkeypatch.setattr(store, "download_pdf", lambda url, **kw: (data, "ADG736.pdf", url))
    details.clear()
    job = wait(client, client.post("/api/datasheets/from-url", json={"url": "https://www.analog.com/x.pdf"})
               .json()["job"])
    assert job["status"] == "done" and job["message"] == "Heruntergeladen: ADG736.pdf (12 Seiten)"
    assert job["detail"]["steps"] == ["download", "read"]
    ids = [d["datasheet_id"] for d in details if "datasheet_id" in d]
    assert ids and ids[0] == job["result"]["datasheet_id"]  # set as soon as the PDF is stored
    first_read = next(i for i, d in enumerate(details) if d.get("step") == "read")
    assert next(i for i, d in enumerate(details) if "datasheet_id" in d) < first_read
    again = wait(client, client.post("/api/datasheets/from-url", json={"url": "https://www.analog.com/x.pdf"})
                 .json()["job"])
    assert again["message"] == "Bereits vorhanden: ADG736.pdf (12 Seiten)" and again["result"]["duplicate"]


def test_commit_job_reports_steps_and_outcome(client, ai, monkeypatch):
    from partforge.altium import sync

    monkeypatch.setattr(sync, "ensure_symbols", lambda specs, **kw: [registry.upsert_symbol(SymbolRecord(
        name=s.name, library=r"Symbols\PF_Test.SchLib", source="datasheet", spec=s, status="ok")) for s in specs])
    monkeypatch.setattr(sync, "ensure_footprints", lambda specs, **kw: [registry.upsert_footprint(FootprintRecord(
        name=s.name, library=r"Footprints\PF_TEST.PcbLib", source="datasheet", spec=s, status="ok")) for s in specs])
    fx = fixture("opa656")
    ds = client.post("/api/datasheets", files={"file": ("opa656.pdf", (PDFS / "opa656.pdf").read_bytes(),
                                                        "application/pdf")}).json()["datasheet"]["id"]
    llm.set_client_factory(lambda: ReplayLlmClient(fx["calls"]))
    assert wait(client, client.post(f"/api/datasheets/{ds}/extract", json={"vision": "off"}).json()["job"])[
        "status"] == "done"
    job = wait(client, client.post(f"/api/datasheets/{ds}/commit", json={"variants": ["OPA656U", "OPA656N/250"]})
               .json()["job"])
    assert job["status"] == "done", job["error"]
    assert job["message"] == "Angelegt: 2 Bauteile, 2 Symbole, 2 Footprints" == job["result"]["message"]
    assert job["detail"]["steps"] == ["check", "footprints", "symbols", "parts", "save"]
    assert job["detail"]["step"] == "save" and job["detail"]["fingerprint"] == job["result"]["fingerprint"]
    again = wait(client, client.post(f"/api/datasheets/{ds}/commit", json={"variants": ["OPA656U"]}).json()["job"])
    assert again["message"] == "Keine Bauteile angelegt (1 übersprungen)"


# --------------------------------------------------------------------------- labels


@pytest.mark.parametrize(("model", "label"), [
    ("claude-opus-5-5", "Claude Opus 5.5"), ("claude-haiku-5-5", "Claude Haiku 5.5"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"), ("claude-fable-5-1", "Claude Fable 5.1"),
    ("claude-opus-5", "Claude Opus 5"), ("claude-haiku-4-5-20251001", "Claude Haiku 4.5"),
    ("claude-sonnet-4-20250514", "Claude Sonnet 4"), ("claude-3-7-sonnet-latest", "Claude 3.7 Sonnet"),
    ("mein-modell", "mein-modell"), ("", "Claude"), (None, "Claude"),
])
def test_model_labels(model, label):
    assert labels.model_label(model) == label


def test_effort_run_and_money_labels():
    assert [labels.effort_label(e) for e in ("low", "medium", "high", "xhigh", "max", None, "turbo")] == [
        "niedrig", "mittel", "hoch", "sehr hoch", "maximal", "Standard", "turbo"]
    assert labels.run_label("claude-opus-5-5", "low") == "Claude Opus 5.5 · Gründlichkeit niedrig"
    assert labels.run_label("claude-haiku-4-5", None) == "Claude Haiku 4.5"
    assert [labels.usd(v) for v in (0.2294, 0.21, 0.0574, 0.0004, 0, 1234.5, None)] == [
        "0,23 $", "0,21 $", "0,057 $", "0,000 $", "0,00 $", "1.234,50 $", "0,00 $"]


# --------------------------------------------------------------------------- cost estimate


def test_estimate_endpoint_uses_the_page_analysis_and_never_calls_claude(client, ai):
    def no_call() -> Any:
        raise AssertionError("Die Schätzung darf Claude nicht aufrufen")

    llm.set_client_factory(no_call)
    upload = client.post("/api/datasheets", files={"file": ("opa656.pdf", (PDFS / "opa656.pdf").read_bytes(),
                                                            "application/pdf")})
    ds = upload.json()["datasheet"]["id"]
    wait(client, upload.json()["job"])
    response = client.post(f"/api/datasheets/{ds}/estimate")
    assert response.status_code == 200, response.text
    est = response.json()
    assert est["pages"] == [1, 2, 17, 18, 21, 22, 23, 24] and est["selection_method"] == "heuristic"
    assert est["identity_pages"] == [1, 2, 17, 18] and est["geometry_pages"] == [17, 21, 22, 23, 24]
    assert est["drawing_pages"] == [21, 22, 23, 24] and est["pages_total"] == 25 and not est["triage"]
    expected = costs.estimate_import("claude-opus-5-5", identity=(4, 0), geometry=(1, 4))
    assert est["est_input_tokens"] == expected.input_tokens == costs.estimate_pdf_tokens(5, 4) + costs.PROMPT_OVERHEAD_TOKENS
    assert est["est_cost_usd_low"] == expected.low_usd and est["est_cost_usd_high"] == expected.high_usd
    recorded = sum(c["cost_usd"] for c in fixture("opa656")["calls"])  # 0.229 USD measured
    assert est["est_cost_usd_low"] <= recorded * 1.1 and recorded <= est["est_cost_usd_high"]
    assert est["model_label"] == "Claude Opus 5.5 · Gründlichkeit niedrig" and est["model"] == "claude-opus-5-5"
    assert est["effort"] == "low" and est["budget_usd"] == 2.0 and not est["exceeds_budget"]
    manual = client.post(f"/api/datasheets/{ds}/estimate", json={"pages": [1, 2, 99]}).json()
    assert manual["pages"] == [1, 2] and manual["identity_pages"] == manual["geometry_pages"] == [1, 2]
    assert manual["selection_method"] == "manual" and manual["est_cost_usd_low"] < est["est_cost_usd_low"]
    cheap = client.post(f"/api/datasheets/{ds}/estimate", json={"model": "claude-haiku-5-5"}).json()
    assert cheap["est_cost_usd_high"] < est["est_cost_usd_low"] and cheap["model_label"] == \
        "Claude Haiku 5.5 · Gründlichkeit niedrig"
    no_vision = client.post(f"/api/datasheets/{ds}/estimate", json={"vision": "off"}).json()
    assert no_vision["est_cost_usd_high"] < est["est_cost_usd_high"]
    tight = client.post(f"/api/datasheets/{ds}/estimate", json={"max_cost_usd": 0.1}).json()
    assert tight["exceeds_budget"] and tight["budget_usd"] == 0.1
    assert client.post(f"/api/datasheets/{ds}/estimate", json={"pages": [0]}).status_code == 422
    assert client.post("/api/datasheets/0123456789abcdef/estimate").status_code == 404


def test_estimate_reads_an_unread_datasheet_first(workspace, ai):
    rec, _ = store.ingest_bytes((PDFS / "25AA02E48.pdf").read_bytes(), "25AA02E48.pdf", ws=workspace)
    assert not store.load_meta(rec).pages
    from fastapi.testclient import TestClient

    from partforge.app import create_app

    with TestClient(create_app(token="t"), headers={"X-PartForge-Token": "t"}) as c:
        est = c.post(f"/api/datasheets/{rec.id}/estimate", json={"triage": "on"}).json()
    assert est["pages_total"] == 26 and est["triage"]  # the page triage with the fast model is included
    assert store.load_meta(store.get_record(rec.id)).pages  # the page analysis is stored
    without = estimate(store.get_record(rec.id), store.load_meta(store.get_record(rec.id)).pages,
                       ExtractOptions(triage="off"))
    assert not without.triage and est["est_input_tokens"] > without.est_input_tokens


@pytest.mark.parametrize("stem", ["opa656", "LTC6244", "25AA02E48", "sn65lv1023a"])
def test_estimates_bracket_the_recorded_costs(workspace, stem):
    fx = fixture(stem)
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], ws=workspace)
    rec, _ = store.analyze(rec, ws=workspace)
    est = estimate(rec, store.load_meta(rec).pages, ExtractOptions.model_validate(fx["options"]),
                   settings=AppSettings())
    recorded = sum(c["cost_usd"] for c in fx["calls"])
    assert est.est_cost_usd_low * 0.75 <= recorded <= est.est_cost_usd_high, (est, recorded)
