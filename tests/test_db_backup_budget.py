"""Automatic backups (perf-backup-disk): no duplicate of an unchanged database, no backup for an import that
writes nothing, a size budget on top of the count limit."""
from __future__ import annotations

from pathlib import Path

from partforge.db import backup, parts
from partforge.importers import spreadsheet as ss
from partforge.importers.spreadsheet import ImportOptions
from partforge.workspace import Workspace


def _names() -> list[str]:
    return [b["name"] for b in backup.list_backups()]


def test_unchanged_database_is_not_backed_up_twice(workspace: Workspace) -> None:
    parts.create_part("Resistors", {"Part Number": "R-1", "Resistance": "1k"}, allow_incomplete=True)
    first = backup.auto_backup("vor_import")
    again = backup.auto_backup("vor_import")
    assert first is not None and again == first and _names() == [first.name]
    parts.create_part("Resistors", {"Part Number": "R-2", "Resistance": "2k"}, allow_incomplete=True)
    third = backup.auto_backup("vor_import")
    assert third is not None and third != first and len(_names()) == 2
    manual = backup.backup_database("manuell")  # a manual backup is always written
    assert manual.name in _names() and len(_names()) == 3


def _upload(content: str, name: str) -> str:
    return ss.store_upload(content.encode("utf-8"), name)


def test_import_that_writes_nothing_takes_no_backup(workspace: Workspace) -> None:
    parts.create_part("Resistors", {"Part Number": "R-EXIST", "Resistance": "1k"}, allow_incomplete=True)
    token = _upload("Part Number;Resistance\nR-EXIST;2k\n", "same.csv")
    path, _ = ss.upload_path(token)
    prev = ss.preview(path, table="Resistors")
    before = _names()
    for _ in range(3):  # mode "error": every row is refused – nothing changes, no backup
        result = ss.run_import(None, ImportOptions(token=token, table="Resistors", mapping=prev["mapping"], mode="error",
                                                   allow_incomplete=True))
        assert result["created"] == 0 and result["error_count"] == 1 and result["backup"] is None
    assert _names() == before
    token = _upload("Part Number;Resistance\nR-NEW;3k\n", "new.csv")
    path, _ = ss.upload_path(token)
    prev = ss.preview(path, table="Resistors")
    result = ss.run_import(None, ImportOptions(token=token, table="Resistors", mapping=prev["mapping"],
                                               allow_incomplete=True))
    assert result["created"] == 1 and result["backup"] in _names()


def test_size_budget_removes_the_oldest_automatic_backups(workspace: Workspace, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(backup, "MIN_BUDGET_BYTES", 0)
    monkeypatch.setattr(backup, "BUDGET_FACTOR", 2)  # at most 2 × the database size of automatic backups
    monkeypatch.setattr(backup, "KEEP_MIN", 1)
    names = []
    for i in range(6):
        parts.create_part("Resistors", {"Part Number": f"R-{i}", "Resistance": "1k"}, allow_incomplete=True)
        made = backup.auto_backup(f"vor_test_{i}")
        assert made is not None
        names.append(made.name)
    manual = backup.backup_database("manuell")
    left = _names()
    assert manual.name in left  # manual backups are never removed by the budget
    automatic = [n for n in left if "vor_test" in n]
    assert names[-1] in automatic and len(automatic) < 6
    size = workspace.sqlite_path.stat().st_size
    total = sum(Path(b["path"]).stat().st_size for b in backup.list_backups() if "vor_test" in b["name"])
    assert total <= 2 * size + max(Path(b["path"]).stat().st_size for b in backup.list_backups())
