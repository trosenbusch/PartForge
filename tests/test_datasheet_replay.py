"""Official replay mode (PARTFORGE_AI_REPLAY_DIR + PARTFORGE_HOME): recorded Claude answers keyed by the datasheet's
sha256 or the search query, replayed PDF checks and downloads – never a network call, clear German messages for
everything that was not recorded, AI status "replay"."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import pytest
from pdf_support import synthetic_pdf

from partforge.config import load_settings
from partforge.datasheet import find, llm, replay, store
from partforge.datasheet.errors import AiUnavailable, DatasheetError
from partforge.datasheet.llm import LlmRequest, ReplayLlmClient

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
OPA656_PDF = synthetic_pdf([f"Synthetic replay input page {p}" for p in range(1, 6)])
OPA656_SHA = hashlib.sha256(OPA656_PDF).hexdigest()
OPA656_ID = OPA656_SHA[:16]
TI_PDF = "https://www.ti.com/lit/ds/symlink/opa656.pdf"

pytestmark = pytest.mark.skipif(not (FIXTURES / "find" / "opa656.json").is_file(), reason="Testdaten fehlen")


def forbidden(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("Netzwerkzugriff im Testmodus")


@pytest.fixture
def replay_mode(monkeypatch, tmp_path):
    """Pair recorded responses with synthetic PDFs; every network path remains a tripwire."""
    folder = tmp_path / "replay"
    (folder / "find").mkdir(parents=True)
    (folder / "opa656.pdf").write_bytes(OPA656_PDF)
    analysis = json.loads((FIXTURES / "opa656.json").read_text(encoding="utf-8"))
    analysis["sha256"] = OPA656_SHA
    (folder / "opa656.json").write_text(json.dumps(analysis), encoding="utf-8")
    search = json.loads((FIXTURES / "find" / "opa656.json").read_text(encoding="utf-8"))
    search["downloads"] = {url: "../opa656.pdf" for url in search["downloads"]}
    (folder / "find" / "opa656.json").write_text(json.dumps(search), encoding="utf-8")
    monkeypatch.setenv("PARTFORGE_AI_REPLAY_DIR", str(folder))
    monkeypatch.delenv("PARTFORGE_AI_REPLAY_SPEED", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = load_settings()
    monkeypatch.setattr(settings.ai, "enabled", True)
    monkeypatch.setattr(settings.ai, "max_cost_per_import_usd", 2.0)
    monkeypatch.setattr(llm, "AnthropicLlmClient", forbidden)
    monkeypatch.setattr(find, "probe_pdf", forbidden)
    monkeypatch.setattr(store, "download_pdf", forbidden)
    previous = llm.set_client_factory(None)  # the replay mode is a branch of the real factory
    yield settings
    llm.set_client_factory(previous)


def wait(client, job: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError("Job läuft noch")


def test_only_honoured_with_partforge_home(monkeypatch):
    monkeypatch.setenv("PARTFORGE_AI_REPLAY_DIR", str(FIXTURES))
    assert replay.active() and replay.replay_dir() == FIXTURES
    monkeypatch.delenv("PARTFORGE_HOME")
    assert not replay.active()  # the user's real program never replays
    monkeypatch.setenv("PARTFORGE_HOME", "  ")
    assert not replay.active()


def test_clients_are_keyed_by_content_hash_and_query(replay_mode):
    analysis = llm.get_client(datasheet_id=OPA656_ID)
    assert isinstance(analysis, ReplayLlmClient) and analysis.remaining == ["identity", "geometry"]
    with pytest.raises(AiUnavailable, match="Testmodus.*keine aufgezeichnete Analyse") as info:
        llm.get_client(datasheet_id="0123456789abcdef")
    assert "0123456789abcdef" in str(info.value)
    search = llm.get_client(search="  opa656 ")  # normalised query
    assert isinstance(search, ReplayLlmClient) and search.remaining == ["find"]
    with pytest.raises(AiUnavailable, match="Suche „LM358“"):
        llm.get_client(search="LM358")
    probe = llm.get_client().run(LlmRequest(kind="test", model="claude-haiku-5-5", max_tokens=10, messages=[]))
    assert probe.text == "OK" and probe.cost_usd == 0
    assert llm.key_status() == (True, "replay")
    assert replay.search_key(" OPA656  ") == "opa656"


def test_ai_switched_off_wins_over_the_replay(replay_mode):
    replay_mode.ai.enabled = False
    with pytest.raises(AiUnavailable) as info:
        llm.get_client(datasheet_id=OPA656_ID)
    assert info.value.code == "ai_disabled"


@pytest.mark.parametrize(("value", "expected"), [("0.25", 0.25), ("0,5", 0.5), ("abc", 0.0), ("-1", 0.0), ("99", 10.0)])
def test_replay_speed(replay_mode, monkeypatch, value, expected):
    monkeypatch.setenv("PARTFORGE_AI_REPLAY_SPEED", value)
    assert replay.speed() == expected
    assert llm.get_client(datasheet_id=OPA656_ID)._delay == expected  # noqa: SLF001 - configuration check


def test_recorded_probes_and_downloads(replay_mode):
    assert replay.probe(TI_PDF)["is_pdf"] and replay.probe("https://www.ti.com/product/OPA656/")["is_pdf"] is False
    assert replay.probe("https://example.com/x.pdf") is None
    data, name, url = replay.download(TI_PDF)
    assert data == OPA656_PDF and name == "opa656.pdf" and url == TI_PDF
    with pytest.raises(DatasheetError, match="Testmodus.*keine Datei hinterlegt"):
        replay.download("https://www.example.com/x.pdf")
    unchecked = find._default_probe("https://example.com/unbekannt.pdf")  # noqa: SLF001
    assert not unchecked.is_pdf and "Testmodus" in unchecked.message


def test_fixture_index_ignores_broken_files(tmp_path):
    (tmp_path / "find").mkdir()
    (tmp_path / "kaputt.json").write_text("{kein json", encoding="utf-8")
    (tmp_path / "ohne_hash.json").write_text(json.dumps({"calls": []}), encoding="utf-8")
    (tmp_path / "find" / "leer.json").write_text(json.dumps({"calls": []}), encoding="utf-8")
    sha = "ab" * 32
    (tmp_path / "gut.json").write_text(json.dumps({"sha256": sha, "calls": [{"kind": "identity"}]}), encoding="utf-8")
    index = replay.fixtures(tmp_path)
    assert list(index.datasheets) == [sha[:16]] and index.searches == {}
    assert index.analysis_calls(sha[:16]) == [{"kind": "identity"}] and index.analysis_calls("0" * 16) is None
    assert replay.fixtures(tmp_path / "fehlt").datasheets == {}


def test_search_import_and_analysis_offline(client, replay_mode):
    """The full offline demo flow: status, connection test, search, synthetic PDF import and response replay."""
    status = client.get("/api/ai/status").json()
    assert status["key_configured"] and status["key_source"] == "replay"
    test = client.post("/api/ai/test")
    assert test.status_code == 200 and test.json()["ok"] and test.json()["cost_usd"] == 0
    found = wait(client, client.post("/api/datasheets/find", json={"query": "OPA656",
                                                                   "manufacturer": "Texas Instruments"}).json()["job"])
    assert found["status"] == "done", found["error"]
    best = found["result"]["candidates"][0]
    assert best["url"] == TI_PDF and best["is_pdf"] and best["source"] == "hersteller"
    started = client.post("/api/datasheets/from-url", json={"url": best["url"], "extract": True,
                                                            "options": {"vision": "off"},
                                                            "search_job_id": found["id"]})
    job = wait(client, started.json()["job"])
    assert job["status"] == "done", job["error"]
    assert job["result"]["datasheet_id"] == OPA656_ID and job["result"]["extraction"]["mpns"] == 14
    assert job["detail"]["datasheet_id"] == OPA656_ID and job["detail"]["steps"][0] == "download"
    detail = client.get(f"/api/datasheets/{OPA656_ID}").json()
    assert detail["status"] == "analysiert" and detail["source_url"] == TI_PDF
    assert [r["kind"] for r in detail["runs"]] == ["find", "identity", "geometry"]


def test_what_was_not_recorded_fails_clearly(client, replay_mode):
    unknown = wait(client, client.post("/api/datasheets/from-url", json={"url": "https://www.example.com/x.pdf"})
                   .json()["job"])
    assert unknown["status"] == "failed" and "Testmodus" in unknown["error"]
    upload = client.post("/api/datasheets", files={"file": ("unrecorded.pdf", synthetic_pdf(["No recording for this input"]),
                                                            "application/pdf")}, data={"extract": "true"})
    body = upload.json()
    assert upload.status_code == 201 and "Testmodus" in body["warning"] and "keine aufgezeichnete Analyse" in \
        body["warning"]
    assert wait(client, body["job"])["status"] == "done"  # the text layer is read anyway
    refused = client.post(f"/api/datasheets/{body['datasheet']['id']}/extract")
    assert refused.status_code == 503 and "Testmodus" in refused.json()["detail"]["message"]
    no_search = client.post("/api/datasheets/find", json={"query": "LM358"})
    assert no_search.status_code == 503 and "Testmodus" in no_search.json()["detail"]["message"]


def test_slow_replay_can_be_watched_and_cancelled(client, replay_mode, monkeypatch):
    monkeypatch.setenv("PARTFORGE_AI_REPLAY_SPEED", "0.2")
    data = OPA656_PDF
    upload = client.post("/api/datasheets", files={"file": ("opa656.pdf", data, "application/pdf")})
    wait(client, upload.json()["job"])
    started = client.post(f"/api/datasheets/{OPA656_ID}/extract", json={"vision": "off"}).json()["job"]
    deadline = time.time() + 30
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{started['id']}").json()
        if snap["detail"].get("step") == "identity":
            break
        time.sleep(0.05)
    assert snap["status"] == "running" and snap["detail"]["step"] == "identity"
    assert client.post(f"/api/jobs/{started['id']}/cancel").status_code == 200
    job = wait(client, started)
    assert job["status"] == "cancelled"
