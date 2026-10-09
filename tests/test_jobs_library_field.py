"""Job snapshots name the library they were started for (K2): a page can ignore jobs of another library."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from partforge.jobs import JobManager
from partforge.workspace import Workspace, set_current


def test_snapshot_names_the_library_open_at_submit(workspace: Workspace) -> None:
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("x", "Test", lambda ctx: None)
        assert job.snapshot()["library"] == str(workspace.root)
        assert job.snapshot()["library_name"] == "Testbibliothek"
        assert job.snapshot(with_log=False, brief=True)["library"] == str(workspace.root)
        set_current(None)
        try:
            closed = manager.run_sync("x", "Ohne Bibliothek", lambda ctx: None)
        finally:
            set_current(workspace)
        assert closed.snapshot()["library"] is None and closed.snapshot()["library_name"] is None
        assert job.snapshot()["library"] == str(workspace.root)  # unchanged after a switch
    finally:
        manager.shutdown()


def test_api_job_lists_carry_the_library(client: TestClient, workspace: Workspace, tmp_path: Path) -> None:
    started = client.post("/api/export/Resistors/job", json={"format": "csv"}).json()["job"]
    assert started["library"] == str(workspace.root) and started["library_name"] == "Testbibliothek"
    listed = client.get("/api/jobs", params={"brief": True}).json()
    assert any(j["id"] == started["id"] and j["library"] == str(workspace.root) for j in listed)
