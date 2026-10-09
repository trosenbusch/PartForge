"""Backups (online backup API), pruning and restore."""
from __future__ import annotations

import os
import re
import sqlite3
import time

import pytest

from partforge import db, events
from partforge.db import backup, categories, core, lifecycle, parts, schema
from partforge.db.errors import BackupError, NotFoundError
from partforge.workspace import Workspace, WorkspaceNotOpen, set_current


def part(pn: str) -> dict[str, str]:
    return {"Part Number": pn, "Manufacturer": "x", "Manufacturer Part Number": pn, "Resistance": "1k", "Tolerance": "1",
            "Power": "0.1", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}


def test_backup_naming_and_listing(workspace: Workspace) -> None:
    path = backup.backup_database("Vor Löschen der Widerstände!")
    assert re.fullmatch(r"PartForge_\d{8}-\d{6}_Vor_Loeschen_der_Widerstaende\.sqlite", path.name)
    assert path.parent == workspace.backups_dir
    second = backup.backup_database("Vor Löschen der Widerstände!")
    assert second != path and second.is_file() and path.is_file()
    same_second = second.name[10:25] == path.name[10:25]
    assert second.name.endswith("-2.sqlite") if same_second else not second.name.endswith("-2.sqlite")
    info = backup.list_backups()[0]
    assert info["name"] in (path.name, second.name)
    assert info["rel_path"].startswith("Backups\\") and info["size"] > 0 and info["reason"].startswith("Vor_Loeschen")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", info["created"])
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("SELECT count(*) FROM pf_categories").fetchone()[0] == len(categories.list_categories())
    finally:
        conn.close()
    assert backup.sanitize_reason("") == "manuell" and backup.sanitize_reason("ä/ö\\ü:*?") == "ae_oe_ue"


def test_prune_keeps_newest_30_and_ignores_other_files(workspace: Workspace) -> None:
    folder = workspace.backups_dir
    (folder / "lib").mkdir()
    (folder / "notizen.txt").write_text("bleibt", encoding="utf-8")
    for day in range(1, 32):  # 31 old backups + 1 even older + the new one = 33 > KEEP (30)
        (folder / f"PartForge_202001{day:02d}-120000_alt.sqlite").write_bytes(b"x")
    (folder / "PartForge_20191231-235959_aelter.sqlite").write_bytes(b"x")
    backup.backup_database("neu")
    names = [b["name"] for b in backup.list_backups()]
    assert len(names) == backup.KEEP
    assert names[0].endswith("_neu.sqlite") and "PartForge_20191231-235959_aelter.sqlite" not in names
    assert "PartForge_20200102-120000_alt.sqlite" not in names and "PartForge_20200131-120000_alt.sqlite" in names
    assert (folder / "notizen.txt").is_file() and (folder / "lib").is_dir()


def test_restore_roundtrip_with_external_reader(workspace: Workspace) -> None:
    parts.create_part("Resistors", part("KEEP-1"))
    snapshot = backup.backup_database("stand_1")
    parts.delete_parts("Resistors", ["KEEP-1"])
    parts.create_part("Resistors", part("LATER-1"))
    calls: list[int] = []
    changed: list[tuple[object, ...]] = []
    unsubscribe = categories.on_schema_change(lambda: calls.append(1))
    unsubscribe_parts = events.subscribe(events.PARTS_CHANGED, lambda *args: changed.append(args))
    altium = sqlite3.connect(str(workspace.sqlite_path))  # an open reader like Altium's ODBC connection
    try:
        assert altium.execute('SELECT count(*) FROM "Resistors"').fetchone()[0] == 1
        time.sleep(1.1)  # distinct timestamp for the safety backup
        backup.restore_backup(snapshot.name)
        assert altium.execute('SELECT "Part Number" FROM "Resistors"').fetchall() == [("KEEP-1",)]
    finally:
        altium.close()
        unsubscribe()
        unsubscribe_parts()
    assert parts.get_part("Resistors", "KEEP-1") is not None and parts.get_part("Resistors", "LATER-1") is None
    assert calls == [1]
    assert changed == [(None, True)]  # Altium re-reads the DbLib including its component index
    assert any(b["reason"] == "vor_wiederherstellung" for b in backup.list_backups())
    parts.create_part("Resistors", part("AFTER-1"))  # the database is usable again
    with core.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"


def test_restore_errors(workspace: Workspace) -> None:
    for bad in ("../PartForge.sqlite", "nichts.sqlite", "PartForge_20200101-000000_fehlt.sqlite", ""):
        with pytest.raises(NotFoundError):
            backup.restore_backup(bad)
    corrupt = workspace.backups_dir / "PartForge_20200101-000000_kaputt.sqlite"
    corrupt.write_bytes(b"kein sqlite" * 50)
    with pytest.raises(BackupError, match="SQLite"):
        backup.restore_backup(corrupt.name)
    foreign = workspace.backups_dir / "PartForge_20200101-000001_fremd.sqlite"
    conn = sqlite3.connect(str(foreign))
    try:
        conn.execute("CREATE TABLE x (a)")
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(BackupError, match="keine PartForge-Datenbank"):
        backup.restore_backup(foreign.name)
    assert core.is_open()


def _set_schema_version(path, version: int) -> None:  # noqa: ANN001 - Path
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("UPDATE pf_meta SET value=? WHERE key='schema_version'", (str(version),))
        conn.commit()
    finally:
        conn.close()


def test_backup_of_newer_partforge_is_refused_before_overwriting(workspace: Workspace) -> None:
    """Regression: restoring a backup with a newer schema overwrote the live file and left the library closed."""
    parts.create_part("Resistors", part("CURRENT-1"))
    newer = backup.backup_database("vom_kollegen")
    _set_schema_version(newer, schema.SCHEMA_VERSION + 1)
    parts.create_part("Resistors", part("CURRENT-2"))
    before = {b["name"] for b in backup.list_backups()}
    with pytest.raises(BackupError, match="neueren PartForge-Version"):
        backup.restore_backup(newer.name)
    assert core.is_open()
    assert parts.get_part("Resistors", "CURRENT-2") is not None  # nothing was overwritten
    assert {b["name"] for b in backup.list_backups()} == before  # no safety copy needed either


def test_restore_rolls_back_when_the_restored_database_cannot_be_opened(
    workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    parts.create_part("Resistors", part("OLD-1"))
    snapshot = backup.backup_database("alt")
    parts.create_part("Resistors", part("NEW-1"))
    real_open = lifecycle.open_database
    calls: list[int] = []

    def flaky_open(ws: Workspace) -> None:
        calls.append(1)
        if len(calls) == 1:
            raise db.DbError("simulierter Fehler beim Öffnen")
        real_open(ws)

    monkeypatch.setattr(lifecycle, "open_database", flaky_open)
    changed: list[tuple[object, ...]] = []
    unsubscribe = events.subscribe(events.PARTS_CHANGED, lambda *args: changed.append(args))
    time.sleep(1.1)  # distinct timestamp for the safety backup
    try:
        with pytest.raises(BackupError, match="vorherige Stand wurde wiederhergestellt"):
            backup.restore_backup(snapshot.name)
    finally:
        unsubscribe()
    assert changed == []  # nothing was restored: nothing to announce
    assert len(calls) == 2 and core.is_open()
    assert parts.get_part("Resistors", "NEW-1") is not None  # the state before the restore is back
    assert any(b["reason"] == "vor_wiederherstellung" for b in backup.list_backups())
    parts.create_part("Resistors", part("AFTER-1"))  # and usable


def test_restore_and_list_while_database_is_closed(workspace: Workspace) -> None:
    """Backups stay usable when the database is closed (e.g. after a failed open)."""
    parts.create_part("Resistors", part("KEEP-2"))
    snapshot = backup.backup_database("stand")
    parts.create_part("Resistors", part("LATER-2"))
    db.close_database()
    assert [b["name"] for b in backup.list_backups()] == [snapshot.name]
    backup.restore_backup(snapshot.name)
    assert core.is_open()
    assert parts.get_part("Resistors", "KEEP-2") is not None and parts.get_part("Resistors", "LATER-2") is None


def test_restore_replaces_a_damaged_live_file(workspace: Workspace) -> None:
    parts.create_part("Resistors", part("SAFE-1"))
    snapshot = backup.backup_database("gut")
    db.close_database()
    workspace.sqlite_path.write_bytes(b"kaputt" * 1000)
    with pytest.raises(db.DbError):
        db.open_database(workspace)
    backup.restore_backup(snapshot.name)
    assert core.is_open() and parts.get_part("Resistors", "SAFE-1") is not None
    assert core.file_journal_mode(workspace.sqlite_path) == "wal"
    raw_copies = [b for b in backup.list_backups() if b["reason"] == "vor_wiederherstellung_roh"]
    assert raw_copies and raw_copies[0]["size"] == 6000  # the damaged file was kept for manual recovery


def test_backups_without_workspace_raise_workspace_not_open(workspace: Workspace) -> None:
    db.close_database()
    set_current(None)
    with pytest.raises(WorkspaceNotOpen):
        backup.list_backups()
    with pytest.raises(WorkspaceNotOpen):
        backup.restore_backup("PartForge_20200101-000000_x.sqlite")
    set_current(workspace)


def test_postgres_backups_are_refused(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core.get_state(), "kind", "postgres")
    with pytest.raises(BackupError, match="PostgreSQL"):
        backup.backup_database()
    assert backup.auto_backup("egal") is None
    monkeypatch.setattr(workspace.settings.db, "kind", "postgres")
    with pytest.raises(BackupError, match="PostgreSQL"):
        backup.restore_backup("PartForge_20200101-000000_x.sqlite")


def test_backup_failure_leaves_no_temp_file(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(source: object, target: object) -> None:
        open(str(target), "wb").close()  # noqa: SIM115 - simulate a partially written file
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(backup, "_copy_database", boom)
    with pytest.raises(BackupError, match="nicht geschrieben"):
        backup.backup_database("fehler")
    assert not [f for f in os.listdir(workspace.backups_dir) if f.endswith(".tmp")]


def test_restoring_a_backup_from_before_a_move_moves_its_links(workspace: Workspace) -> None:
    """A backup keeps the folder it was written in (pf_meta workspace_root); restored after the
    library moved, its absolute links follow the library like at every open."""
    from partforge.db import meta

    parts.create_part("Resistors", {**part("LINK-1"), "ComponentLink1URL": str(workspace.root) + r"\Datasheets\a.pdf"})
    snapshot = backup.backup_database("vor_umzug")
    conn = sqlite3.connect(str(snapshot))  # as if written before the library was moved here
    try:
        conn.execute("UPDATE pf_meta SET value=? WHERE key='workspace_root'", (r"C:\Frueher\Bibliothek",))
        conn.execute('UPDATE "Resistors" SET "ComponentLink1URL"=? WHERE "Part Number"=?',
                     (r"C:\Frueher\Bibliothek\Datasheets\a.pdf", "LINK-1"))
        conn.commit()
    finally:
        conn.close()
    time.sleep(1.1)  # distinct timestamp for the safety backup
    backup.restore_backup(snapshot.name)
    assert parts.get_part("Resistors", "LINK-1")["ComponentLink1URL"] == str(workspace.root) + r"\Datasheets\a.pdf"  # type: ignore[index]
    assert meta.get_meta(meta.WORKSPACE_ROOT) == str(workspace.root)
