"""Live tests against the Claude API (marker ``ai``; run with PARTFORGE_TEST_AI=1).

* ``/api/ai/test``: one tiny request with the fast model (< 0.001 USD).
* full extraction of opa656.pdf with the default settings (claude-opus-5-5, effort low; about 0.25 USD) and
  its accuracy against the corpus ground truth.

The key comes from the normal configuration (environment, DPAPI store or key file) and is never printed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from partforge.config import load_settings
from partforge.datasheet import llm, store
from partforge.datasheet.evaluate import compare, manifest_entry
from partforge.datasheet.extract import ExtractOptions, run_extraction

pytestmark = pytest.mark.ai

DATA = Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def real_client():
    previous = llm.set_client_factory(None)
    yield
    llm.set_client_factory(previous)


def test_live_ai_test_endpoint(bare_client):
    response = bare_client.post("/api/ai/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] and body["latency_ms"] > 0 and body["cost_usd"] < 0.01
    assert "sk-ant" not in response.text


def test_live_extraction_of_the_reference_datasheet(workspace):
    settings = load_settings()
    rec, _ = store.ingest_bytes((DATA / "corpus" / "pdfs" / "opa656.pdf").read_bytes(), "opa656.pdf", ws=workspace)
    started = time.perf_counter()
    result = run_extraction(None, rec.id, ExtractOptions(), ws=workspace, settings=settings)
    assert time.perf_counter() - started < 300
    assert result["cost_usd"] < settings.ai.max_cost_per_import_usd
    meta = store.load_meta(store.get_record(rec.id))
    manifest = json.loads((DATA / "corpus" / "manifest.json").read_text(encoding="utf-8"))
    report = compare(meta.extraction, manifest_entry(manifest, "opa656.pdf"))
    assert report.mpns.ratio == 1.0, report.mpns.misses
    assert report.pins.ratio == 1.0, report.pins.misses
    assert report.dimensions.ratio >= 0.95, report.dimensions.misses
