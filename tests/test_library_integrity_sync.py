"""Damaged libraries and lost components at the sync level (review findings INT-05, INT-06), real Rust writer.

* INT-05: an unreadable SchLib/PcbLib is an error of the file-level check (``library_unreadable`` with the affected
  parts and – when a readable backup exists – the one-click restore), ``library_files``/``scan_workspace`` name it,
  and ``restore_library_backup`` puts the newest readable backup back and rewrites the components.
* INT-06: ``ok`` entries that are missing from their file (restored database, lost write) are written by
  ``sync_pending``; ``scan_workspace(rebaseline=True)`` takes a file that only "changed outside" because the manifests
  were restored back as PartForge's own.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from test_sync_support import make_part
from test_writer_samples import chip_0603

from partforge.altium import libwriter, sync
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.db import meta, registry

pytestmark = pytest.mark.rustwriter

LIB = "Footprints\\PF_CHIP.PcbLib"


@pytest.fixture(autouse=True)
def _real_writer(monkeypatch):
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    sync.invalidate_health_cache()
    yield
    shutdown_client()


def _wait_job(client, job: dict, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError("Job nicht fertig")


def _library_with_backup(workspace) -> Path:
    for name in ("R1", "R2"):
        assert sync.ensure_footprints([chip_0603(name)])[0].status == "ok"
    path = workspace.footprints_dir / "PF_CHIP.PcbLib"
    assert list((workspace.backups_dir / "lib").glob("PF_CHIP.PcbLib.*.bak"))  # the second write backed up the first
    return path


def test_unreadable_library_is_an_error_with_a_restore(client, workspace):
    path = _library_with_backup(workspace)
    for pn, ref in (("R-1", "R1"), ("R-2", "R2")):
        make_part("Resistors", pn, Footprint_Ref=ref, Footprint_Path=LIB)
    clean = client.get("/api/libraries/health").json()
    assert not [i for i in clean["issues"] if i["check"] == sync.UNREADABLE_CHECK]
    path.write_bytes(b"\xd0\xcf\x11\xe0 kaputt" * 1000)  # e.g. torn by a second process (INT-01)
    libwriter.forget_component_names()
    report = client.get("/api/libraries/health").json()
    issue = next(i for i in report["issues"] if i["check"] == sync.UNREADABLE_CHECK)
    assert issue["severity"] == "error" and issue["library"] == LIB and issue["fix_action"] == sync.RESTORE_BACKUP_ACTION
    assert issue["affected_parts"] == 2 and issue["part_numbers"] == ["R-1", "R-2"]
    assert "nicht lesbar" in issue["message"] and "(2 registrierte Footprints)" in issue["message"]
    assert ".." not in issue["message"]
    assert report["counts"]["error"] >= 1  # the old check counted 0 errors for a corrupt file
    files = client.get("/api/libraries/files", params={"layers": False}).json()
    info = next(f for f in files if f["rel"] == LIB)
    assert info["unreadable"] is True and "nicht lesbar" in info["message"]
    scan = _wait_job(client, client.post("/api/libraries/scan").json()["job"])
    assert scan["result"]["unreadable"][0]["library"] == LIB and "nicht lesbar" in scan["message"]
    restored = _wait_job(client, client.post("/api/libraries/restore-backup", json={"library": LIB}).json()["job"])
    assert restored["status"] == "done", restored.get("error")
    result = restored["result"]
    assert result["library"] == LIB and result["backup"].startswith("PF_CHIP.PcbLib.") and result["damaged"].endswith(".defekt")
    assert sorted(result["rewritten"]) == ["R1", "R2"] and result["errors"] == []
    assert RustLibraryOps(workspace=workspace).list_components(path) == ["R1", "R2"]
    assert (workspace.backups_dir / "lib" / result["damaged"]).is_file()
    after = client.get("/api/libraries/health").json()
    assert not [i for i in after["issues"] if i["check"] in (sync.UNREADABLE_CHECK, "component_missing")]
    again = client.post("/api/libraries/restore-backup", json={"library": LIB}).json()["job"]
    assert _wait_job(client, again)["status"] == "failed"  # readable now: nothing to restore


def test_sync_pending_rewrites_ok_entries_missing_from_their_file(workspace):
    """INT-06: the registry says ``ok``, the file lost the component – „Synchronisieren“ answered „aktuell“."""
    path = _library_with_backup(workspace)
    ops = RustLibraryOps(workspace=workspace)
    assert ops.delete_components(path, ["R1"]).deleted == ["R1"]  # behind PartForge's back
    libwriter.forget_component_names()
    assert registry.get_footprint("R1").status == "ok"  # type: ignore[union-attr]
    summary = sync.sync_pending()
    assert summary["footprints"]["total"] == 1 and summary["footprints"]["ok"] == 1, summary
    assert ops.list_components(path) == ["R2", "R1"] or sorted(ops.list_components(path)) == ["R1", "R2"]
    assert sync.sync_pending()["footprints"]["total"] == 0  # nothing left


def test_rebaseline_after_restored_manifests(workspace):
    """INT-06: restoring a database backup restores the manifests – PartForge's own file then counts as
    „außerhalb geändert“; the scan after the restore takes it back."""
    _library_with_backup(workspace)
    snapshot = sync.manifest_snapshot()
    old = dict(snapshot)
    assert sync.ensure_footprints([chip_0603("R3")])[0].status == "ok"  # the file moves on
    for key, value in old.items():  # like a restored backup: the old manifests are back
        meta.set_meta(key, value)
    previous = {k: v for k, v in snapshot.items()}  # (here the manifests before the "restore" are the old ones too)
    scan = sync.scan_workspace()
    assert scan["changed_outside"] == [LIB]
    rebased = sync.scan_workspace(rebaseline=True, previous_manifests=previous)
    assert rebased["changed_outside"] == [] and rebased["rebaselined"] == [LIB]
    info = next(i for i in sync.library_files(check_layers=False) if i.rel == LIB)
    assert info.external_changes is False and info.in_sync
