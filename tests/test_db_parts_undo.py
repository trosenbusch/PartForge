"""Mass changes (bulk update, regenerated texts) take an automatic backup and can be undone (INT-11)."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.db import backup, parts
from partforge.workspace import Workspace


def _make(n: int) -> list[str]:
    rows = [{"Part Number": f"R-{i:03d}", "Manufacturer": "Yageo", "Resistance": "1k", "Description": f"D{i}"}
            for i in range(n)]
    return parts.upsert_parts("Resistors", rows, allow_incomplete=True).created


def test_bulk_update_backs_up_and_undo_restores_the_old_values(workspace: Workspace) -> None:
    pns = _make(parts.AUTO_BACKUP_DELETE_THRESHOLD + 5)
    before = len(backup.list_backups())
    ids: list[int] = []
    changed = parts.bulk_update("Resistors", pns, {"Manufacturer": "OOPS"}, audit_ids=ids)
    assert changed == len(pns) and len(ids) == len(pns)
    backups = backup.list_backups()
    assert len(backups) == before + 1 and backups[0]["reason"].startswith("vor_massenaenderung")
    parts.update_part("Resistors", "R-001", {"Manufacturer": "Murata"})  # changed again meanwhile
    out = parts.restore_updates("Resistors", ids)
    assert len(out["restored"]) == len(pns) - 1
    assert "R-001" in out["conflicts"] and "Hersteller" in out["conflicts"]["R-001"]
    assert parts.get_part("Resistors", "R-000")["Manufacturer"] == "Yageo"  # type: ignore[index]
    assert parts.get_part("Resistors", "R-001")["Manufacturer"] == "Murata"  # type: ignore[index]
    history = parts.history("Resistors", "R-000")
    assert history[0]["action"] == "restore" and history[0]["changes"]["Manufacturer"] == ["OOPS", "Yageo"]
    again = parts.restore_updates("Resistors", ids)  # undoing twice changes nothing
    assert again["restored"] == [] and len(again["unchanged"]) == len(pns) - 1


def test_small_bulk_update_needs_no_backup(workspace: Workspace) -> None:
    pns = _make(3)
    before = len(backup.list_backups())
    parts.bulk_update("Resistors", pns, {"Manufacturer": "X"})
    assert len(backup.list_backups()) == before


def test_regenerate_texts_backs_up_and_can_be_undone(workspace: Workspace) -> None:
    pns = _make(parts.AUTO_BACKUP_DELETE_THRESHOLD + 1)
    parts.update_part("Resistors", "R-000", {"Description": "Handtext"})
    before = len(backup.list_backups())
    ids: list[int] = []
    changed = parts.regenerate_texts("Resistors", None, columns=["Description"], audit_ids=ids)
    assert changed == len(pns) and len(backup.list_backups()) == before + 1
    assert parts.get_part("Resistors", "R-000")["Description"] != "Handtext"  # type: ignore[index]
    parts.restore_updates("Resistors", ids)
    assert parts.get_part("Resistors", "R-000")["Description"] == "Handtext"  # type: ignore[index]


def test_restore_updates_refuses_foreign_entries(workspace: Workspace) -> None:
    _make(1)
    ids: list[int] = []
    parts.bulk_update("Resistors", ["R-000"], {"Manufacturer": "X"}, audit_ids=ids)
    with pytest.raises(ValueError):
        parts.restore_updates("Capacitors", ids)  # entries of another category
    out = parts.restore_updates("Resistors", [999_999])
    assert out["not_found"] == [999_999]


def _post(client: TestClient, path: str, body: dict[str, Any]) -> dict[str, Any]:
    r = client.post(path, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_api_bulk_update_returns_backup_and_undo_handle(client: TestClient) -> None:
    pns = _make(parts.AUTO_BACKUP_DELETE_THRESHOLD + 1)
    out = _post(client, "/api/parts/Resistors/bulk-update", {"values": {"Manufacturer": "OOPS"},
                                                             "expected_count": len(pns), "filters": []})
    assert out["updated"] == len(pns) and out["backup"] and len(out["audit_ids"]) == len(pns)
    undo = _post(client, "/api/parts/Resistors/restore-updates", {"audit_ids": out["audit_ids"]})
    assert len(undo["restored"]) == len(pns) and undo["conflicts"] == {}
    assert client.get("/api/parts/Resistors/R-005").json()["Manufacturer"] == "Yageo"
    regen = _post(client, "/api/parts/Resistors/regenerate-texts", {"columns": ["Description"]})
    assert regen["updated"] == len(pns) and regen["backup"] and len(regen["audit_ids"]) == len(pns)
