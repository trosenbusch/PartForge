"""Data-level report: exact numbers per check (K12) and the cached database scan (perf-health-dashboard)."""
from __future__ import annotations

import sqlite3
import time
from typing import Any

from partforge.db import core, health, parts, registry
from partforge.db.models import FootprintRecord
from partforge.workspace import Workspace


def _make(n: int) -> None:
    rows = [{"Part Number": f"R-{i:03d}", "Manufacturer": "x", "Manufacturer Part Number": f"R-{i:03d}",
             "Resistance": "1k", "Tolerance": None, "Power": "0.1"} for i in range(n)]
    parts.upsert_parts("Resistors", rows, allow_incomplete=True)


def test_exact_counts_per_check_when_issues_are_cut(workspace: Workspace) -> None:
    _make(30)
    report = health.health_report(max_per_check=5)
    assert report["truncated"]
    assert report["checked_parts"] == 30
    required = report["checks"]["required"]
    # Tolerance, Library Ref and Footprint Ref are empty: 3 issues per part, 30 parts
    assert required["severity"] == "error" and required["issues"] == 90 and required["affected_parts"] == 30
    assert required["part_numbers"] == sorted(f"R-{i:03d}" for i in range(30))[: health.CHECK_SAMPLE_SIZE]
    assert len([i for i in report["issues"] if i["check"] == "required"]) == 5
    assert report["affected_parts"] == 30 and len(report["affected_part_numbers"]) == 30
    info_only = report["checks"]["datasheet_missing"]
    assert info_only["severity"] == "info" and info_only["affected_parts"] == 30


def test_api_returns_the_exact_numbers(client) -> None:  # noqa: ANN001 - fixture
    _make(3)
    body = client.get("/api/health-check", params={"max_per_check": 1}).json()
    assert body["checked_parts"] == 3 and body["affected_parts"] == 3
    assert body["checks"]["required"]["affected_parts"] == 3 and body["checks"]["required"]["issues"] == 9


def _issues(report: dict[str, Any], check: str) -> list[dict[str, Any]]:
    return [i for i in report["issues"] if i["check"] == check]


def test_scan_is_cached_until_the_database_changes(workspace: Workspace, monkeypatch) -> None:  # noqa: ANN001
    _make(2)
    calls: list[int] = []
    real = health._scan_database

    def counting(root):  # noqa: ANN001, ANN202
        calls.append(1)
        return real(root)

    monkeypatch.setattr(health, "_scan_database", counting)
    health.clear_cache()
    first = health.health_report()
    second = health.health_report(max_per_check=1)
    assert len(calls) == 1 and second["summary"] == first["summary"]
    parts.update_part("Resistors", "R-000", {"Tolerance": "1"})  # a write of PartForge
    third = health.health_report()
    assert len(calls) == 2 and third["checks"]["required"]["issues"] == first["checks"]["required"]["issues"] - 1
    registry.upsert_footprint(FootprintRecord(name="X", library=r"Footprints\X.PcbLib", status="error",
                                              status_message="kaputt"))
    assert _issues(health.health_report(), "registry_error") and len(calls) == 3
    time.sleep(0.05)
    conn = sqlite3.connect(str(workspace.sqlite_path))  # a write of another program (Altium table browser)
    try:
        conn.execute("UPDATE \"Resistors\" SET \"Tolerance\" = '5' WHERE \"Part Number\" = 'R-001'")
        conn.commit()
    finally:
        conn.close()
    fourth = health.health_report()
    assert len(calls) == 4 and fourth["checks"]["required"]["issues"] == third["checks"]["required"]["issues"] - 1


def test_library_files_are_checked_on_every_request(workspace: Workspace) -> None:
    registry.upsert_footprint(FootprintRecord(name="RESC1608X55N", library=r"Footprints\PF_CHIP.PcbLib", status="ok"))
    parts.create_part("Resistors", {"Part Number": "R-F", "Footprint Ref": "RESC1608X55N"}, allow_incomplete=True)
    health.clear_cache()
    assert len(_issues(health.health_report(), "library_file_missing")) == 1
    (workspace.footprints_dir / "PF_CHIP.PcbLib").write_bytes(b"x")  # created outside PartForge
    assert not _issues(health.health_report(), "library_file_missing")
    assert core.data_version() > 0


def test_health_check_as_job(client) -> None:  # noqa: ANN001 - fixture
    _make(2)
    started = client.post("/api/health-check/job", json={"max_per_check": 1}).json()["job"]
    assert started["kind"] == "health-check"
    for _ in range(200):
        job = client.get(f"/api/jobs/{started['id']}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert job["status"] == "done", job
    assert job["result"]["checked_parts"] == 2 and job["result"]["checks"]["required"]["affected_parts"] == 2
    assert job["message"].startswith("Daten geprüft: 2 Bauteile – ") and "Fehler" in job["message"]
