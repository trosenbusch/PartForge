"""Library guard of the datasheet jobs (analysis, URL import): they hold their library only for the short database
phases, a library switch never waits for (or cancels) a paid Claude call, nothing is ever written into another
library – and a paid result whose library was closed meanwhile is kept in that library's folder and appears when it
is opened again."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from partforge.api import routes_system
from partforge.api.routes_system import WorkspaceCreateIn
from partforge.config import AppSettings, load_settings
from partforge.datasheet import llm, store
from partforge.datasheet.extract import ExtractOptions, run_extraction
from partforge.datasheet.llm import ReplayLlmClient
from partforge.datasheet.models import PendingResult, RunInfo
from partforge.db import registry
from partforge.jobs import JobManager, jobs, library_guard
from partforge.workspace import Workspace, current_or_none

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
PDFS = DATA / "corpus" / "pdfs"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not PDFS.is_dir(), reason="Testdaten fehlen")


def calls(stem: str = "opa656") -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))["calls"]


def wait(client, job_id: str, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job_id}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError("Job läuft noch")


class Gated(ReplayLlmClient):
    """Replay that blocks in the identity call (the "paid call in flight") until released."""

    def __init__(self, recorded: list[dict[str, Any]]) -> None:
        super().__init__(recorded)
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self, request, **kwargs):
        if request.kind == "identity":
            self.entered.set()
            assert self.release.wait(30), "nicht freigegeben"
        return super().run(request, **kwargs)


@pytest.fixture
def ai(monkeypatch):
    settings = load_settings()
    monkeypatch.setattr(settings.ai, "enabled", True)
    monkeypatch.setattr(settings.ai, "max_cost_per_import_usd", 2.0)
    monkeypatch.delenv("PARTFORGE_AI_REPLAY_DIR", raising=False)
    previous = llm.set_client_factory(None)
    yield settings
    llm.set_client_factory(previous)


def uploaded(client, name: str = "opa656.pdf") -> str:
    response = client.post("/api/datasheets", files={"file": (name, (PDFS / name).read_bytes(), "application/pdf")})
    assert response.status_code == 201, response.text
    body = response.json()
    if body["job"]:
        assert wait(client, body["job"]["id"])["status"] == "done"
    return body["datasheet"]["id"]


def pending(ws: Workspace) -> list[Path]:
    return store.pending_files(ws)


def test_switch_during_a_paid_analysis_keeps_the_result_for_the_old_library(client, workspace, tmp_path, ai):
    ds = uploaded(client)
    gated = Gated(calls())
    llm.set_client_factory(lambda: gated)
    job_id = client.post(f"/api/datasheets/{ds}/extract", json={"vision": "off"}).json()["job"]["id"]
    assert gated.entered.wait(30)
    assert library_guard.holders() == []  # nothing is held during the paid call
    started = time.monotonic()
    created = client.post("/api/workspace/create", json={"path": str(tmp_path / "B"), "with_examples": False,
                                                         "write_libraries": False})
    assert created.status_code == 200, created.text
    assert time.monotonic() - started < 10  # the switch does not wait for Claude
    job = jobs.get(job_id)
    assert job is not None and not job.cancel_requested  # ... and does not cancel the analysis
    gated.release.set()
    snap = wait(client, job_id)
    assert snap["status"] == "done", snap["error"]
    assert snap["result"]["stored"] == "pending" and "gesichert" in snap["message"]
    assert any(e["level"] == "warn" and "nicht mehr geöffnet" in e["text"] for e in snap["log"])
    # nothing went into library B
    assert client.get("/api/datasheets").json() == [] and registry.list_datasheets() == []
    files = pending(workspace)
    assert len(files) == 1 and files[0].parent == workspace.datasheets_dir / ".pending"
    kept = PendingResult.model_validate_json(files[0].read_text(encoding="utf-8"))
    assert kept.kind == "extraction" and [r.kind for r in kept.runs] == ["identity", "geometry"]
    # library A opened again: the result appears (event of the open route)
    reopened = client.post("/api/workspace/open", json={"path": str(workspace.root)})
    assert reopened.status_code == 200, reopened.text
    assert pending(workspace) == []
    detail = client.get(f"/api/datasheets/{ds}").json()
    assert detail["status"] == "analysiert" and detail["manufacturer"] == "Texas Instruments"
    assert [r["kind"] for r in detail["runs"]] == ["identity", "geometry"] and detail["cost_usd"] > 0
    assert detail["devices"] == ["OPA656"]


def test_costs_of_a_failure_after_a_switch_are_kept_as_well(client, workspace, tmp_path, ai):
    ds = uploaded(client)
    recorded = calls()
    refused = json.loads(json.dumps(recorded[1]))
    refused["message"]["content"], refused["message"]["stop_reason"] = [], "refusal"
    gated = Gated([recorded[0], refused])
    llm.set_client_factory(lambda: gated)
    job_id = client.post(f"/api/datasheets/{ds}/extract", json={"vision": "off"}).json()["job"]["id"]
    assert gated.entered.wait(30)
    routes_system.close_workspace()
    assert current_or_none() is None
    gated.release.set()
    snap = wait(client, job_id)
    assert snap["status"] == "failed" and "abgelehnt" in snap["error"]
    assert any("Kosten der Analyse wurden in ihrem Ordner gesichert" in e["text"] for e in snap["log"])
    assert len(pending(workspace)) == 1
    assert client.post("/api/workspace/open", json={"path": str(workspace.root)}).status_code == 200
    detail = client.get(f"/api/datasheets/{ds}").json()
    assert detail["status"] == "gelesen" and "abgelehnt" in detail["last_error"]
    assert [r["kind"] for r in detail["runs"]] == ["identity", "geometry"] and detail["cost_usd"] > 0


def test_a_queued_analysis_never_touches_the_next_library(workspace, tmp_path, ai):
    rec, _ = store.ingest_bytes((PDFS / "opa656.pdf").read_bytes(), "opa656.pdf", ws=workspace)
    client = ReplayLlmClient(calls())
    body = (lambda ctx: run_extraction(ctx, rec.id, ExtractOptions(vision="off"), ws=workspace, client=client,
                                       settings=AppSettings()))  # submitted while A is open ...
    routes_system.create_workspace(WorkspaceCreateIn(path=str(tmp_path / "B"), name="B", with_examples=False,
                                                     write_libraries=False))
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", body)  # ... and runs once B is open
    finally:
        manager.shutdown()
    assert job.status == "cancelled" and client.requests == []  # no paid call
    assert any(e["level"] == "warn" and "keine Kosten" in e["text"] for e in job.log)
    assert registry.list_datasheets() == [] and pending(workspace) == []


def test_url_import_switched_before_storing(client, workspace, tmp_path, ai, monkeypatch):
    data = (PDFS / "ADG736.pdf").read_bytes()

    def download_and_switch(url: str, **_kw: Any) -> tuple[bytes, str, str]:
        routes_system.create_workspace(WorkspaceCreateIn(path=str(tmp_path / "B"), name="B", with_examples=False,
                                                         write_libraries=False))
        return data, "ADG736.pdf", url

    monkeypatch.setattr(store, "download_pdf", download_and_switch)
    job_id = client.post("/api/datasheets/from-url", json={"url": "https://www.analog.com/ADG736.pdf"}).json()["job"]["id"]
    snap = wait(client, job_id)
    assert snap["status"] == "cancelled"
    assert any("nicht gespeichert" in e["text"] for e in snap["log"])
    assert registry.list_datasheets() == []  # not in B
    assert not list((tmp_path / "B" / "Datasheets").glob("*.pdf"))
    assert not list(workspace.datasheets_dir.glob("*.pdf"))  # and not in A either


def _run(kind: str, cost: float) -> RunInfo:
    return RunInfo(kind=kind, model="claude-opus-5-5", request_id=f"req_{kind}", cost_usd=cost,
                   ts="2026-10-08T12:00:00")


def test_kept_results_are_applied_once_and_orphans_stay(workspace):
    rec, _ = store.ingest_bytes((PDFS / "ADG736.pdf").read_bytes(), "ADG736.pdf", ws=workspace)
    result = PendingResult(datasheet_id=rec.id, created="2026-10-08T12:00:01", kind="failure",
                           runs=[_run("identity", 0.1)], last_error="Analyse abgebrochen.")
    store.save_pending(workspace, result)
    store.save_pending(workspace, result)  # e.g. a crash after merging, before the file was deleted
    store.save_pending(workspace, PendingResult(datasheet_id="0123456789abcdef", created="x", kind="failure"))
    broken = workspace.datasheets_dir / ".pending" / "0123456789abcdef_kaputt.json"
    broken.write_text("{kein json", encoding="utf-8")
    applied = store.apply_pending(workspace)
    assert applied == [rec.id, rec.id]
    meta = store.load_meta(store.get_record(rec.id))
    assert len(meta.runs) == 1 and meta.cost_usd == pytest.approx(0.1) and meta.last_error == "Analyse abgebrochen."
    assert [p.name for p in store.pending_files(workspace)] == [broken.name]  # unreadable: stays for the next try
    assert len(list((workspace.datasheets_dir / ".pending").glob("*.orphan"))) == 1


def test_a_newer_analysis_is_not_replaced_by_an_older_kept_one(workspace):
    rec, _ = store.ingest_bytes((PDFS / "ADG736.pdf").read_bytes(), "ADG736.pdf", ws=workspace)
    meta = store.load_meta(rec)
    meta.extracted, meta.model = "2026-10-08T15:00:00", "claude-opus-5-5"
    store.save_meta(rec, meta)
    from partforge.datasheet.models import ExtractionData

    old = PendingResult(datasheet_id=rec.id, created="2026-10-08T14:00:00", kind="extraction",
                        extracted="2026-10-08T14:00:00", extraction=ExtractionData(manufacturer="Alt"),
                        runs=[_run("identity", 0.2)], model="claude-sonnet-5-5")
    store.apply_result(store.get_record(rec.id), old, once=True)
    meta = store.load_meta(store.get_record(rec.id))
    assert meta.model == "claude-opus-5-5" and meta.extraction is None  # kept the newer state ...
    assert meta.cost_usd == pytest.approx(0.2)  # ... but the paid call counts


def test_concurrent_metadata_updates_are_not_lost(workspace, monkeypatch):
    """Regression: a reading job saved metadata it had loaded before another writer (a merged result, the cost of a
    search) stored its change – that change was lost. Every writer now re-reads under the datasheet's lock."""
    rec, _ = store.ingest_bytes((PDFS / "ADG736.pdf").read_bytes(), "ADG736.pdf", ws=workspace)
    original = store.read_texts

    def a_result_arrives_meanwhile(rec_, **kwargs):
        info = original(rec_, **kwargs)
        store.add_runs(store.get_record(rec_.id), [_run("find", 0.03)])  # another thread's write
        return info

    monkeypatch.setattr(store, "read_texts", a_result_arrives_meanwhile)
    store.analyze(rec, ws=workspace, force=True)  # loaded nothing before; saves under the lock
    meta = store.load_meta(store.get_record(rec.id))
    assert meta.pages and [r.kind for r in meta.runs] == ["find"] and meta.cost_usd == pytest.approx(0.03)
    store.delete_datasheet(rec.id, ws=workspace)
    from partforge.datasheet.errors import DatasheetNotFound

    with pytest.raises(DatasheetNotFound):  # a deleted datasheet is never re-created by a late writer
        store.add_runs(rec, [_run("identity", 0.1)])
    assert registry.get_datasheet(rec.id) is None
