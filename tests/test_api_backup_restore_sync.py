"""Restoring a backup brings the registry back but not the SchLib/PcbLib files (INT-06): the restore starts a
job that compares the files with the restored registry and writes what is missing again."""
from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.altium import sync
from partforge.db import registry
from partforge.db.models import FootprintRecord


def _wait(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(400):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("Job endet nicht")


@pytest.fixture
def fake_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    """scan_workspace marks the restored footprint pending (it is missing from its file); sync_pending writes it."""
    calls: dict[str, list[Any]] = {"scan": [], "sync": []}

    def scan(ctx=None, *, register=False, writer=None, **kw):  # noqa: ANN001, ANN003, ANN202
        calls["scan"].append(kw)
        for rec in registry.list_footprints(with_spec=False, with_usage=False):
            if rec.status == "ok":
                registry.set_footprint_status(rec.name, "pending", "fehlt in der Datei")
        return {"files": 1, "updated": ["RESC3225X60N"], "unregistered": [], "registered": [], "conflicts": [],
                "external_missing": [], "changed_outside": []}

    def write(ctx=None):  # noqa: ANN001, ANN202
        calls["sync"].append(1)
        for rec in registry.list_footprints(status="pending", with_spec=False, with_usage=False):
            registry.set_footprint_status(rec.name, "ok")
        return {"symbols": {"total": 0, "ok": 0}, "footprints": {"total": 1, "ok": 1, "error": 0, "missing": 0},
                "libraries": [], "errors": [], "missing": []}

    monkeypatch.setattr(sync, "scan_workspace", scan)
    monkeypatch.setattr(sync, "sync_pending", write)
    return calls


def test_restore_starts_the_library_check_and_writes_missing_components(client: TestClient,
                                                                         fake_files: dict[str, list[Any]]) -> None:
    registry.upsert_footprint(FootprintRecord(name="RESC3225X60N", library=r"Footprints\PF_CHIP.PcbLib", status="ok"))
    made = client.post("/api/backups", json={"reason": "test"}).json()
    registry.delete_footprint("RESC3225X60N")  # deleted from file and registry after the backup
    r = client.post(f"/api/backups/{made['name']}/restore")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["job"]["kind"] == "libraries.scan"
    job = _wait(client, body["job"]["id"])
    assert job["status"] == "done", job
    assert fake_files["scan"] and fake_files["sync"]
    assert job["message"].startswith("Nach dem Wiederherstellen:")
    assert "1 Footprint" in job["message"]
    assert registry.get_footprint("RESC3225X60N", with_usage=False).status == "ok"  # type: ignore[union-attr]


def test_restore_rebases_the_manifests_taken_before_the_restore(client: TestClient, monkeypatch: pytest.MonkeyPatch,
                                                                 fake_files: dict[str, list[Any]]) -> None:
    """INT-06 (be-core x be-altium): the manifests are read *before* the backup replaces the database and handed to
    the scan with ``rebaseline`` – files PartForge wrote after the backup do not count as "außerhalb geändert"."""
    from partforge.db import backup

    order: list[str] = []
    snapshot = {"lib-manifest:Footprints/PF_CHIP.PcbLib": "{}"}
    monkeypatch.setattr(sync, "manifest_snapshot", lambda: order.append("snapshot") or dict(snapshot))
    real_restore = backup.restore_backup
    monkeypatch.setattr(backup, "restore_backup", lambda name: order.append("restore") or real_restore(name))
    made = client.post("/api/backups", json={"reason": "test"}).json()
    job = _wait(client, client.post(f"/api/backups/{made['name']}/restore").json()["job"]["id"])
    assert job["status"] == "done", job
    assert order == ["snapshot", "restore"]
    assert fake_files["scan"] == [{"rebaseline": True, "previous_manifests": snapshot}]


def test_restore_without_differences_writes_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(sync, "scan_workspace", lambda ctx=None, **kw: calls.append("scan") or {"files": 0})
    monkeypatch.setattr(sync, "sync_pending", lambda ctx=None: calls.append("sync") or {})
    made = client.post("/api/backups", json={"reason": "test"}).json()
    job = _wait(client, client.post(f"/api/backups/{made['name']}/restore").json()["job"]["id"])
    assert job["status"] == "done" and calls == ["scan"]


def test_restore_without_a_library_reader_explains_what_to_do(client: TestClient,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    from partforge.altium.libwriter import WriterUnavailable

    def no_reader(ctx=None, **kw):  # noqa: ANN001, ANN003, ANN202
        raise WriterUnavailable("Kein Bibliotheks-Writer verfügbar.")

    monkeypatch.setattr(sync, "scan_workspace", no_reader)
    made = client.post("/api/backups", json={"reason": "test"}).json()
    job = _wait(client, client.post(f"/api/backups/{made['name']}/restore").json()["job"]["id"])
    assert job["status"] == "done" and job["result"]["skipped"]
    assert "Bibliotheken prüfen" in job["message"]
