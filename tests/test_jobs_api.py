"""Job endpoints: brief job lists (``GET /api/jobs?brief=true``, ``GET /api/jobs/events?brief=true``) and the full
snapshots of one job (``GET /api/jobs/{id}``, ``/api/jobs/{id}/events``), with ``detail`` and ``cancel_reason``."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.api import routes_system
from partforge.jobs import CANCEL_LIBRARY_SWITCH, JobContext, JobManager

BIG = {
    "outcome": "ok",
    "created": 900,
    "errors": {f"R-{i:04d}": "Teilenummer doppelt in den Daten." for i in range(40)},
    "missing": [{"kind": "symbol", "name": f"S{i}", "message": "nicht erzeugbar"} for i in range(8)],
    "created_part_numbers": [f"R-{i:04d}" for i in range(900)],
}


class FakeRequest:
    """Stands in for the Starlette request of an SSE endpoint: connected for ``rounds`` polls."""

    def __init__(self, rounds: int) -> None:
        self.rounds = rounds

    async def is_disconnected(self) -> bool:
        self.rounds -= 1
        return self.rounds < 0


def events(response: Any) -> list[dict[str, Any]]:
    """The ``data:`` payloads of a finished SSE response."""

    async def collect() -> list[str]:
        return [chunk async for chunk in response.body_iterator]

    chunks = asyncio.run(collect())
    return [json.loads(chunk[len("data: "):]) for chunk in chunks if chunk.startswith("data: ")]


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[JobManager]:
    """A fresh job manager behind the job endpoints (no jobs of other tests)."""
    mgr = JobManager(max_workers=1)
    monkeypatch.setattr(routes_system, "jobs", mgr)
    try:
        yield mgr
    finally:
        mgr.shutdown()


def big_job(ctx: JobContext) -> dict[str, Any]:
    ctx.log("900 Zeilen gelesen")
    ctx.detail(step="schreiben", rows=900)
    ctx.progress(1.0, "Import fertig: 900 neu")
    return BIG


def small_job(ctx: JobContext) -> dict[str, Any]:
    ctx.progress(1.0, "Export fertig: 2 Bauteile in Exports\\R.xlsx")
    return {"rows": 2, "path": "C:\\Lib\\Exports\\R.xlsx"}


def test_job_list_brief(bare_client: TestClient, manager: JobManager) -> None:
    big = manager.run_sync("import", "Import „a.csv“ → Widerstände", big_job)
    small = manager.run_sync("export", "Export Widerstände (XLSX)", small_job)
    listed = {j["id"]: j for j in bare_client.get("/api/jobs").json()}
    assert listed[big.id]["result"] == BIG and listed[big.id]["log"] == []  # unchanged without the parameter
    brief = {j["id"]: j for j in bare_client.get("/api/jobs", params={"brief": "true"}).json()}
    result = brief[big.id]["result"]
    assert result == {
        "outcome": "ok",
        "created": 900,
        "errors": {f"R-{i:04d}": "Teilenummer doppelt in den Daten." for i in range(5)},
        "errors_count": 40,
        "missing": BIG["missing"][:5],
        "missing_count": 8,
        "created_part_numbers_count": 900,
        "result_truncated": True,
    }
    assert brief[small.id]["result"] == {"rows": 2, "path": "C:\\Lib\\Exports\\R.xlsx"}  # small: unchanged
    assert brief[big.id]["detail"] == {"step": "schreiben", "rows": 900}
    assert brief[big.id]["message"] == "Import fertig: 900 neu" and brief[big.id]["cancel_reason"] is None
    assert [j["id"] for j in bare_client.get("/api/jobs", params={"brief": True, "kind": "export"}).json()] == [small.id]
    # one job: always the full result with log
    full = bare_client.get(f"/api/jobs/{big.id}").json()
    assert full["result"] == BIG and full["log"][0]["text"] == "900 Zeilen gelesen"
    assert full["detail"] == {"step": "schreiben", "rows": 900} and full["cancel_requested"] is False


def test_job_events_brief_and_full(manager: JobManager) -> None:
    big = manager.run_sync("import", "Import", big_job)
    manager.run_sync("export", "Export", small_job)
    payloads = {p["job"]["id"]: p for p in events(asyncio.run(routes_system.all_job_events(FakeRequest(1), brief=True)))}
    assert len(payloads) == 2
    brief = payloads[big.id]
    assert brief["job"]["result"]["result_truncated"] is True and brief["job"]["result"]["errors_count"] == 40
    assert brief["job"]["log"] == [] and [e["text"] for e in brief["new_log"]] == ["900 Zeilen gelesen"]
    assert brief["job"]["detail"] == {"step": "schreiben", "rows": 900}
    full = {p["job"]["id"]: p for p in events(asyncio.run(routes_system.all_job_events(FakeRequest(1), brief=False)))}
    assert full[big.id]["job"]["result"] == BIG
    single = events(asyncio.run(routes_system.job_events(big.id, FakeRequest(5))))
    assert len(single) == 1 and single[0]["result"] == BIG and single[0]["log"][0]["text"] == "900 Zeilen gelesen"
    assert single[0]["detail"] == {"step": "schreiben", "rows": 900}


def test_job_events_send_only_changes_with_detail_and_cancel_reason(manager: JobManager) -> None:
    def body(ctx: JobContext) -> None:
        ctx.detail(step="pins", pages=[3, 4])
        ctx.log("Seiten 3, 4")
        ctx.cancel(CANCEL_LIBRARY_SWITCH)
        ctx.check_cancelled()

    job = manager.run_sync("datasheet-commit", "Bauteil anlegen", body)
    sent = events(asyncio.run(routes_system.all_job_events(FakeRequest(3), brief=True)))
    assert len(sent) == 1  # unchanged jobs are not sent again
    snap = sent[0]["job"]
    assert snap["id"] == job.id and snap["status"] == "cancelled" and snap["cancel_reason"] == "library_switch"
    assert snap["cancel_requested"] is True and snap["detail"] == {"step": "pins", "pages": [3, 4]}
    assert snap["message"] == "Abgebrochen – die Bibliothek wurde gewechselt oder geschlossen"


def test_cancel_endpoint_leaves_the_reason_empty(bare_client: TestClient, manager: JobManager) -> None:
    started, release = threading.Event(), threading.Event()

    def body(ctx: JobContext) -> None:
        started.set()
        assert release.wait(10)
        ctx.check_cancelled()

    job = manager.submit("import", "Import", body)
    try:
        assert started.wait(10)
        assert bare_client.post(f"/api/jobs/{job.id}/cancel").json() == {"cancelled": True}
        snap = bare_client.get(f"/api/jobs/{job.id}").json()
        assert snap["status"] == "running" and snap["cancel_requested"] is True and snap["cancel_reason"] is None
    finally:
        release.set()
    deadline = time.monotonic() + 10
    while job.status == "running" and time.monotonic() < deadline:
        time.sleep(0.01)
    snap = bare_client.get(f"/api/jobs/{job.id}").json()
    assert snap["status"] == "cancelled" and snap["cancel_reason"] is None and snap["message"] == "Abgebrochen"
    assert bare_client.get("/api/jobs/gibtsnicht").status_code == 404
