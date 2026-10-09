"""Datasheet import API (routes_datasheets) with a fake Claude client (recorded answers, no network)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.config import load_settings
from partforge.datasheet import llm, store
from partforge.datasheet.llm import ReplayLlmClient
from partforge.db import parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.geometry.model import SymbolSpec

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
PDFS = DATA / "corpus" / "pdfs"
FAKE_KEY = "sk-ant-api-test-0000-NIEMALS-AUSGEBEN"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not PDFS.is_dir(), reason="Testdaten fehlen")


def fixture_calls(stem: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))["calls"]


def wait(client: TestClient, job: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Job {job['id']} läuft noch")


@pytest.fixture
def ai(monkeypatch, tmp_path):
    """AI settings under test control: no environment key, a temporary key file, fake client factory."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = load_settings()
    monkeypatch.setattr(settings.ai, "api_key_file", str(tmp_path / "kein-key.txt"))
    monkeypatch.setattr(settings.ai, "enabled", True)
    previous = llm.set_client_factory(None)
    calls: list[dict[str, Any]] = []

    def use(stem_or_calls: str | list[dict[str, Any]]) -> None:
        calls[:] = fixture_calls(stem_or_calls) if isinstance(stem_or_calls, str) else stem_or_calls
        llm.set_client_factory(lambda: ReplayLlmClient(list(calls)))

    def key() -> Path:
        path = tmp_path / "key.txt"
        path.write_text(FAKE_KEY, encoding="utf-8")
        monkeypatch.setattr(settings.ai, "api_key_file", str(path))
        return path

    yield type("Ai", (), {"use": staticmethod(use), "key": staticmethod(key), "settings": settings})
    llm.set_client_factory(previous)


@pytest.fixture
def fake_sync(monkeypatch):
    from partforge.altium import sync

    monkeypatch.setattr(sync, "ensure_symbols", lambda specs, **kw: [registry.upsert_symbol(SymbolRecord(
        name=s.name, library=r"Symbols\PF_Test.SchLib", source="datasheet", spec=s, status="ok")) for s in specs])
    monkeypatch.setattr(sync, "ensure_footprints", lambda specs, **kw: [registry.upsert_footprint(FootprintRecord(
        name=s.name, library=r"Footprints\PF_TEST.PcbLib", source="datasheet", spec=s, status="ok")) for s in specs])


def upload(client: TestClient, name: str = "opa656.pdf", **form: str):
    return client.post("/api/datasheets", files={"file": (name, (PDFS / name).read_bytes(), "application/pdf")},
                       data=form)


# --------------------------------------------------------------------------- upload, list, files


def test_upload_list_detail_file_and_pages(client, ai):
    response = upload(client)
    assert response.status_code == 201, response.text
    body = response.json()
    ds = body["datasheet"]
    assert not body["duplicate"] and body["warning"] is None and body["job"]["kind"] == "datasheet"
    assert ds["original_name"] == "opa656.pdf" and ds["page_count"] == 25 and ds["status"] == "neu"
    assert Path(ds["path"]).is_file() and ds["file"].startswith("Datasheets\\")
    job = wait(client, body["job"])
    assert job["status"] == "done", job["error"]
    assert job["result"] == {"datasheet_id": ds["id"], "page_count": 25}

    listed = client.get("/api/datasheets").json()
    assert [d["id"] for d in listed] == [ds["id"]] and listed[0]["status"] == "gelesen"
    detail = client.get(f"/api/datasheets/{ds['id']}").json()
    assert len(detail["pages"]) == 25 and detail["pages"][20]["quality"] == "empty"
    assert 21 not in detail["text_pages"] and detail["runs"] == []

    pdf = client.get(f"/api/datasheets/{ds['id']}/file")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:5] == b"%PDF-" and "inline" in pdf.headers["content-disposition"]
    png = client.get(f"/api/datasheets/{ds['id']}/pages/21.png", params={"dpi": 40})
    assert png.status_code == 200 and png.headers["content-type"] == "image/png" and png.content[:4] == b"\x89PNG"
    assert "max-age" in png.headers["cache-control"]
    assert client.get(f"/api/datasheets/{ds['id']}/pages/99.png").status_code == 400
    assert client.get(f"/api/datasheets/{ds['id']}/pages/1.png", params={"dpi": 9000}).status_code == 422

    again = upload(client)
    assert again.status_code == 200 and again.json()["duplicate"] and again.json()["job"] is None


def test_upload_rejects_non_pdfs_and_bad_options(client, ai):
    bad = client.post("/api/datasheets", files={"file": ("x.pdf", b"GIF89a", "application/pdf")})
    assert bad.status_code == 400 and "kein PDF" in bad.json()["detail"]
    options = upload(client, extract="true", options="{kaputt")
    assert options.status_code == 400 and "Analyse-Optionen" in options.json()["detail"]
    assert client.get("/api/datasheets").json() == []


def test_upload_with_extraction(client, ai):
    ai.use("opa656")
    body = upload(client, extract="true", options=json.dumps({"vision": "off"})).json()
    assert body["warning"] is None and "analysieren" in body["job"]["title"]
    job = wait(client, body["job"])
    assert job["status"] == "done", job["error"]
    summary = job["result"]["extraction"]
    assert summary["devices"] == ["OPA656"] and summary["mpns"] == 14 and summary["pins"] == 13
    assert any("Hersteller erkannt: Texas Instruments" in entry["text"] for entry in job["log"])
    ds = client.get(f"/api/datasheets/{body['datasheet']['id']}").json()
    assert ds["status"] == "analysiert" and ds["manufacturer"] == "Texas Instruments" and ds["cost_usd"] > 0
    assert ds["devices"] == ["OPA656"] and [r["kind"] for r in ds["runs"]] == ["identity", "geometry"]


def test_upload_with_extraction_but_without_key(client, ai):
    body = upload(client, extract="true").json()
    assert "nicht analysiert" in body["warning"] and "Schlüssel" in body["warning"]
    job = wait(client, body["job"])
    assert job["status"] == "done" and "extraction" not in job["result"]


def test_from_url(client, ai, monkeypatch):
    data = (PDFS / "ADG736.pdf").read_bytes()
    seen: list[str] = []

    def fake_download(url, **kwargs):
        seen.append(url)
        return data, "ADG736.pdf", "https://www.analog.com/media/ADG736.pdf"

    monkeypatch.setattr(store, "download_pdf", fake_download)
    response = client.post("/api/datasheets/from-url", json={"url": "https://www.analog.com/ADG736"})
    assert response.status_code == 200
    job = wait(client, response.json()["job"])
    assert job["status"] == "done", job["error"]
    assert seen == ["https://www.analog.com/ADG736"] and not job["result"]["duplicate"]
    detail = client.get(f"/api/datasheets/{job['result']['datasheet_id']}").json()
    assert detail["source_url"] == "https://www.analog.com/media/ADG736.pdf" and detail["page_count"] == 12
    assert client.post("/api/datasheets/from-url", json={"url": "ftp://x/y.pdf"}).status_code == 400
    no_key = client.post("/api/datasheets/from-url", json={"url": "https://x.example/y.pdf", "extract": True})
    assert no_key.status_code == 503


# --------------------------------------------------------------------------- extraction, proposal, commit


def _extracted(client: TestClient, ai, stem: str = "opa656") -> str:
    name = {"opa656": "opa656.pdf", "LTC6244": "LTC6244.pdf", "25AA02E48": "25AA02E48.pdf"}[stem]
    ds = upload(client, name).json()["datasheet"]["id"]
    ai.use(stem)
    started = client.post(f"/api/datasheets/{ds}/extract", json={"vision": "off"})
    assert started.status_code == 200, started.text
    job = wait(client, started.json()["job"])
    assert job["status"] == "done", job["error"]
    return ds


def test_extract_extraction_and_edits(client, ai):
    ds = upload(client).json()["datasheet"]["id"]
    assert client.get(f"/api/datasheets/{ds}/extraction").status_code == 404
    assert client.post(f"/api/datasheets/{ds}/extract").status_code == 503  # no key, no factory
    ds = _extracted(client, ai)
    out = client.get(f"/api/datasheets/{ds}/extraction").json()
    assert out["model"] == "claude-opus-5-5" and out["effort"] == "low" and not out["edited"]
    assert out["selected_pages"] == [1, 2, 17, 18, 21, 22, 23, 24] and out["budget_usd"] > 0
    extraction = out["extraction"]
    assert extraction["manufacturer"] == "Texas Instruments" and len(extraction["packages"]) == 2
    extraction["devices"][0]["description"] = "Breitband-OPV"
    saved = client.put(f"/api/datasheets/{ds}/extraction", json=extraction)
    assert saved.status_code == 200 and saved.json()["edited"]
    assert client.get(f"/api/datasheets/{ds}/extraction").json()["extraction"]["devices"][0]["description"] == \
        "Breitband-OPV"
    assert client.put(f"/api/datasheets/{ds}/extraction", json={"devices": "x"}).status_code == 422


def test_proposal_and_commit(client, ai, fake_sync):
    ds = _extracted(client, ai)
    assert client.post(f"/api/datasheets/{ds}/commit").status_code == 200  # job accepted
    proposal = client.post(f"/api/datasheets/{ds}/proposal", json={"variants": ["OPA656U"]})
    assert proposal.status_code == 200, proposal.text
    data = proposal.json()
    assert data["ready"] and data["category"] == "Amplifiers" and len(data["variants"]) == 1
    assert data["symbols"][0]["svg"].lstrip().startswith("<svg") and data["footprints"][0]["svg"]
    assert data["variants"][0]["values"]["Footprint Ref"].startswith("SOIC127P600X175-8N")
    lean = client.post(f"/api/datasheets/{ds}/proposal", params={"svg": "false"}, json={"variants": ["OPA656U"]})
    assert lean.json()["symbols"][0]["svg"] is None
    committed = client.post(f"/api/datasheets/{ds}/commit", json={"variants": ["OPA656U", "OPA656UB"]})
    job = wait(client, committed.json()["job"])
    assert job["status"] == "done", job["error"]
    assert job["kind"] == "datasheet-commit"
    assert {"OPA656U", "OPA656UB"} <= set(parts.existing_part_numbers(["OPA656U", "OPA656UB"]))
    detail = client.get(f"/api/datasheets/{ds}").json()
    assert detail["status"] == "übernommen" and detail["committed"][-1]["table"] == "Amplifiers"
    bad = client.post(f"/api/datasheets/{ds}/proposal", json={"device": "LM358"})
    assert bad.status_code == 400 and "nicht enthalten" in bad.json()["detail"]


def test_errors_and_delete(client, ai):
    assert client.get("/api/datasheets/0123456789abcdef").status_code == 404
    assert client.get("/api/datasheets/..%5C..%5Cx").status_code == 404
    ds = upload(client, "ADG736.pdf").json()["datasheet"]["id"]
    assert client.post(f"/api/datasheets/{ds}/proposal").status_code == 404  # not analysed yet
    assert client.post(f"/api/datasheets/{ds}/commit").status_code == 404
    path = Path(client.get(f"/api/datasheets/{ds}").json()["path"])
    deleted = client.delete(f"/api/datasheets/{ds}")
    assert deleted.status_code == 200 and deleted.json()["file_deleted"] and not path.exists()
    assert client.delete(f"/api/datasheets/{ds}").status_code == 404


def test_datasheets_need_a_workspace(bare_client):
    assert bare_client.get("/api/datasheets").status_code == 409
    response = bare_client.post("/api/datasheets", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})
    assert response.status_code == 409


# --------------------------------------------------------------------------- AI status / test


def test_ai_status_never_returns_the_key(bare_client, ai):
    status = bare_client.get("/api/ai/status").json()
    # the configured key file does not exist yet: a German note, never the key
    assert status.pop("key_file_problem")
    assert status == {"enabled": True, "key_configured": False, "key_source": None, "model": "claude-opus-5-5",
                      "effort": "low", "fast_model": ai.settings.ai.fast_model, "use_fallbacks": True,
                      "max_cost_per_import_usd": ai.settings.ai.max_cost_per_import_usd,
                      "model_label": "Claude Opus 5.5", "fast_model_label": "Claude Haiku 5.5"}
    ai.key()
    response = bare_client.get("/api/ai/status")
    assert response.json()["key_configured"] and response.json()["key_source"] == "file"
    assert response.json()["key_file_problem"] is None  # a valid sk-ant key file: no problem
    assert FAKE_KEY not in response.text
    assert FAKE_KEY not in bare_client.get("/api/settings").text


def test_ai_test_endpoint(bare_client, ai):
    unavailable = bare_client.post("/api/ai/test")
    assert unavailable.status_code == 503
    detail = unavailable.json()["detail"]  # machine-readable code + German text
    assert detail["code"] == "key_missing" and "Schlüssel" in detail["message"]
    reply = {"id": "msg_t", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
             "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn",
             "usage": {"input_tokens": 16, "output_tokens": 4}}
    replay = ReplayLlmClient([{"kind": "test", "message": reply, "request_id": "req_test"}])
    llm.set_client_factory(lambda: replay)
    response = bare_client.post("/api/ai/test")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] and body["reply"] == "OK" and body["model"] == "claude-haiku-5-5"
    assert body["model_label"] == "Claude Haiku 5.5"
    assert body["request_id"] == "req_test" and body["cost_usd"] == pytest.approx(16 * 0.1e-6 + 4 * 0.5e-6, abs=1e-6)
    request = replay.requests[0]  # answers within about a minute even without network
    assert request.timeout_s == 30.0 and request.max_retries == 1
    ai.settings.ai.enabled = False
    disabled = bare_client.post("/api/ai/test")
    assert disabled.status_code == 503
    assert disabled.json()["detail"]["code"] == "ai_disabled" and "ausgeschaltet" in disabled.json()["detail"]["message"]


# --------------------------------------------------------------------------- review regressions


def test_damaged_pdf_upload_is_a_german_400(client, ai, monkeypatch):
    """Reviewer case h13: pypdf crashes on damaged files must not become HTTP 500."""
    import pypdf

    def crash(*args, **kwargs):
        raise AssertionError

    monkeypatch.setattr(pypdf, "PdfReader", crash)
    response = upload(client, "ADG736.pdf")
    assert response.status_code == 400 and "kein lesbares PDF" in response.json()["detail"]


def test_edited_extraction_is_cleaned_and_blockers_need_a_confirmation(client, ai, fake_sync):
    ds = _extracted(client, ai, "25AA02E48")
    extraction = client.get(f"/api/datasheets/{ds}/extraction").json()["extraction"]
    soic = next(t for t in extraction["devices"][0]["pin_tables"] if t["package"] == "SN")
    soic["pins"] = [p for p in soic["pins"] if p["number"] not in ("4", "8")]  # VSS and VCC deleted by mistake
    soic["pins"][1]["name"] = "SO|X\x07"
    saved = client.put(f"/api/datasheets/{ds}/extraction", json=extraction)
    assert saved.status_code == 200, saved.text
    pins = next(t for t in saved.json()["extraction"]["devices"][0]["pin_tables"] if t["package"] == "SN")["pins"]
    assert pins[1]["name"] == "SO/X"
    choice = {"variants": ["25AA02E48-I/SN"]}
    proposal = client.post(f"/api/datasheets/{ds}/proposal", params={"svg": "false"}, json=choice).json()
    assert not proposal["ready"] and any("Pads ohne Pin im Symbol: 4, 8" in b for b in proposal["blockers"])
    # K3: the JSON contract of the structured blocker targets (same order and text as the blockers)
    assert [t["blocker"] for t in proposal["blocker_targets"]] == proposal["blockers"]
    pads = next(t for t in proposal["blocker_targets"] if "Pads ohne Pin im Symbol: 4, 8" in t["blocker"])
    # pins without pads concern the pairing: they block "Bauteil anlegen", not "Nur Symbol/Footprint speichern"
    assert pads == {"blocker": pads["blocker"], "package": "SN", "pins": [], "pads": ["4", "8"], "scopes": ["part"]}
    refused = wait(client, client.post(f"/api/datasheets/{ds}/commit", json=choice).json()["job"])
    assert refused["status"] == "failed" and "bestätigen" in refused["error"]
    confirmed = {**choice, "accept_issues": True}
    assert client.post(f"/api/datasheets/{ds}/proposal", params={"svg": "false"}, json=confirmed).json()["ready"]
    done = wait(client, client.post(f"/api/datasheets/{ds}/commit", json=confirmed).json()["job"])
    assert done["status"] == "done", done["error"]
    assert done["result"]["created"] == ["25AA02E48-I/SN"]


def test_failed_analysis_shows_reason_and_costs(client, ai):
    ds = upload(client).json()["datasheet"]["id"]
    calls = fixture_calls("opa656")
    refused = json.loads(json.dumps(calls[1]))
    refused["message"]["content"] = []
    refused["message"]["stop_reason"] = "refusal"
    ai.use([calls[0], refused])
    job = wait(client, client.post(f"/api/datasheets/{ds}/extract", json={"vision": "off"}).json()["job"])
    assert job["status"] == "failed" and "abgelehnt" in job["error"]
    assert any("Bisherige Kosten dieses Imports gespeichert" in e["text"] for e in job["log"])
    detail = client.get(f"/api/datasheets/{ds}").json()
    assert detail["status"] == "gelesen" and "abgelehnt" in detail["last_error"] and detail["cost_usd"] > 0
    assert [r["kind"] for r in detail["runs"]] == ["identity", "geometry"] and detail["runs"][1]["error"]


# --------------------------------------------------------------------------- contracts of this round


def test_ai_errors_carry_a_code_on_every_endpoint(client, ai):
    from partforge.datasheet.errors import AiUnavailable, ExtractionFailed

    ds = upload(client, "ADG736.pdf").json()["datasheet"]["id"]
    refused = client.post(f"/api/datasheets/{ds}/extract")
    assert refused.status_code == 503 and refused.json()["detail"]["code"] == "key_missing"
    no_key = client.post("/api/datasheets/from-url", json={"url": "https://x.example/y.pdf", "extract": True})
    assert no_key.status_code == 503 and "Schlüssel" in no_key.json()["detail"]["message"]

    class Failing:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        def run(self, request, **kwargs):
            raise self.exc

    for exc, status, code in ((AiUnavailable("Schlüssel abgelehnt", code="key_rejected"), 503, "key_rejected"),
                              (AiUnavailable("Limit", code="rate_limited"), 503, "rate_limited"),
                              (AiUnavailable("Keine Verbindung", code="network"), 503, "network"),
                              (ExtractionFailed("Die Claude-API hat die Anfrage abgelehnt: x"), 400, "unknown")):
        llm.set_client_factory(lambda exc=exc: Failing(exc))
        response = client.post("/api/ai/test")
        assert response.status_code == status and response.json()["detail"] == {"code": code, "message": str(exc)}


def test_proposal_contract_and_a_commit_against_a_changed_plan(client, ai, fake_sync):
    ds = _extracted(client, ai)
    proposal = client.post(f"/api/datasheets/{ds}/proposal", params={"svg": "false"},
                           json={"variants": ["OPA656U"]}).json()
    assert len(proposal["fingerprint"]) == 16 and proposal["unconfirmed_blockers"] == []
    assert all("taken_changes" in s and "usage" in s for s in proposal["symbols"])
    assert proposal["blocker_targets"] == []
    assert proposal["symbols"][0]["spec"]["generator"]["nc_pads"] == ["1", "5", "8"]  # F2
    # K3: pin-out differences to a registered symbol of the generated name are structured per pin (JSON contract)
    generated = SymbolSpec.model_validate(proposal["symbols"][0]["spec"])
    renamed = [p.model_copy(update={"name": "I\\N\\-"}) if p.designator == "2" else p for p in generated.pins]
    registry.upsert_symbol(SymbolRecord(name=generated.name, library=r"Symbols\Alt.SchLib", status="ok",
                                        spec=generated.model_copy(update={"pins": renamed})))
    taken = client.post(f"/api/datasheets/{ds}/proposal", params={"svg": "false"},
                        json={"variants": ["OPA656U"]}).json()["symbols"][0]
    assert taken["taken_name"] == generated.name and taken["taken_changes"] == [
        {"pin": "2", "old_name": "I\\N\\-", "new_name": next(p.name for p in generated.pins if p.designator == "2"),
         "old_type": "input", "new_type": "input", "old_part": 1, "new_part": 1}]
    registry.delete_symbol(generated.name)
    detail = client.get(f"/api/datasheets/{ds}").json()
    assert detail["model"] == "claude-opus-5-5" and detail["model_label"] == "Claude Opus 5.5"
    stale = {"variants": ["OPA656U"], "expected_fingerprint": "0" * 16}
    job = wait(client, client.post(f"/api/datasheets/{ds}/commit", json=stale).json()["job"])
    assert job["status"] == "failed" and job["detail"]["code"] == "proposal_changed"
    assert parts.get_part("Amplifiers", "OPA656U") is None
    fresh = {"variants": ["OPA656U"], "expected_fingerprint": proposal["fingerprint"]}
    job = wait(client, client.post(f"/api/datasheets/{ds}/commit", json=fresh).json()["job"])
    assert job["status"] == "done" and job["result"]["created"] == ["OPA656U"]
    legacy = client.post(f"/api/datasheets/{ds}/proposal", params={"svg": "false"},
                         json={"variants": ["OPA656U"], "accept_issues": True, "allow_pin_changes": ["X"]})
    assert legacy.status_code == 200  # True (deprecated) and lists are accepted
    assert client.post(f"/api/datasheets/{ds}/proposal", json={"accept_issues": "ja"}).status_code == 422


def test_listing_merges_results_kept_while_the_library_was_closed(client, ai, workspace):
    from partforge.datasheet.models import PendingResult, RunInfo

    ds = upload(client, "ADG736.pdf").json()["datasheet"]["id"]
    run = RunInfo(kind="identity", model="claude-opus-5-5", request_id="req_x", cost_usd=0.12, ts="2026-10-08T10:00:00")
    store.save_pending(workspace, PendingResult(datasheet_id=ds, created="2026-10-08T10:00:01", kind="failure",
                                                runs=[run], last_error="Analyse abgebrochen."))
    listed = client.get("/api/datasheets").json()
    assert listed[0]["cost_usd"] == pytest.approx(0.12) and listed[0]["last_error"] == "Analyse abgebrochen."
    assert store.pending_files(workspace) == []


def test_results_kept_for_the_library_open_at_start_are_merged(workspace, ai):
    """The launcher opens the last library before the server starts: the router lifespan merges its kept results."""
    from fastapi.testclient import TestClient

    from partforge.app import create_app
    from partforge.datasheet.models import PendingResult, RunInfo

    rec, _ = store.ingest_bytes((PDFS / "ADG736.pdf").read_bytes(), "ADG736.pdf", ws=workspace)
    run = RunInfo(kind="identity", model="claude-opus-5-5", request_id="req_y", cost_usd=0.05, ts="2026-10-08T11:00:00")
    store.save_pending(workspace, PendingResult(datasheet_id=rec.id, created="2026-10-08T11:00:01", kind="failure",
                                                runs=[run], last_error="x"))
    with TestClient(create_app(token="t"), headers={"X-PartForge-Token": "t"}):
        assert store.pending_files(workspace) == []
    assert store.load_meta(store.get_record(rec.id)).cost_usd == pytest.approx(0.05)
