"""Schema bootstrap, column types, pragmas, migrations and reconciliation with external changes."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from partforge import db
from partforge.db import categories, core, parts, schema
from partforge.db.errors import DatabaseNotOpen, SchemaError
from partforge.db.templates import CATEGORIES, COMMON_FIELDS
from partforge.workspace import Workspace, WorkspaceNotOpen, WorkspaceSettings, set_current

PF_TABLES = {"pf_meta", "pf_categories", "pf_fields", "pf_symbols", "pf_footprints", "pf_datasheets", "pf_audit",
             "pf_mpn_templates", "pf_saved_views"}


@contextmanager
def raw(ws: Workspace) -> Iterator[sqlite3.Connection]:
    """A separate connection, like Altium's ODBC driver (committed and closed on exit)."""
    conn = sqlite3.connect(str(ws.sqlite_path), timeout=5)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def table_info(ws: Workspace, table: str) -> list[tuple]:
    with raw(ws) as conn:
        return conn.execute(f'PRAGMA table_info("{table}")').fetchall()


def test_bootstrap_creates_metadata_and_builtin_categories(workspace: Workspace) -> None:
    with raw(workspace) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        version = conn.execute("SELECT value FROM pf_meta WHERE key='schema_version'").fetchone()[0]
    assert PF_TABLES <= tables
    assert "sqlite_sequence" not in tables  # no AUTOINCREMENT tables
    assert version == str(schema.SCHEMA_VERSION)
    cats = categories.list_categories()
    assert [c.table for c in cats] == [t.table for t in CATEGORIES]
    assert all(c.part_count == 0 for c in cats)
    assert {c.table for c in cats} <= tables
    res = categories.get_category("Resistors")
    common = [f.column for f in COMMON_FIELDS]
    assert [f.column for f in res.fields][: len(common)] == common
    assert [f.column for f in res.fields][len(common):] == ["Resistance", "Tolerance", "Power", "Voltage", "TCR", "Technology", "Size"]
    assert res.builtin and res.value_field == "Resistance"
    pn = res.field("Part Number")
    assert pn is not None and pn.protected and pn.common and pn.required


def test_category_column_types_are_text(workspace: Workspace) -> None:
    """ARCHITEKTUR §4 (VERIFIED in Altium 26.10): VARCHAR(n) is truncated at n in Altium, TEXT is not."""
    for cat in categories.list_categories(with_counts=False):
        info = table_info(workspace, cat.table)
        types = {row[1]: row[2] for row in info}
        assert info[0][1] == "Part Number" and info[0][5] == 1 and info[0][3] == 1  # first, PK, NOT NULL
        assert set(types.values()) == {"TEXT"}, (cat.table, types)
    fet = {row[1] for row in table_info(workspace, "Transistors FET")}
    assert {"RDS(on)", "VGS(th)", "Manufacturer Part Number"} <= fet
    long_text = "Langer Hinweis " * 40  # ~600 characters, more than the old VARCHAR(255)
    parts.create_part("Resistors", {"Part Number": "R-LONG", "Manufacturer": "YAGEO", "Manufacturer Part Number": "R-LONG",
                                    "Resistance": "1k", "Tolerance": "1", "Power": "0.1", "Library Ref": "RES",
                                    "Footprint Ref": "RESC1608X55N", "Supplier Part Number 1": long_text})
    with raw(workspace) as conn:
        stored = conn.execute('SELECT "Supplier Part Number 1" FROM "Resistors" WHERE "Part Number"=\'R-LONG\'').fetchone()[0]
    assert stored == long_text.strip()


def test_pragmas_index_and_sql_function(workspace: Workspace) -> None:
    with core.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar_one() == 5000
        assert conn.exec_driver_sql("SELECT pf_num('10kΩ', 'Ω')").scalar_one() == 10000
        assert conn.exec_driver_sql("SELECT pf_num('abc', 'Ω')").scalar_one() is None
        assert conn.exec_driver_sql("SELECT pf_num(NULL, '')").scalar_one() is None
    with raw(workspace) as conn:
        indexes = conn.execute("SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='Resistors'").fetchall()
    assert any("COLLATE NOCASE" in (sql or "") for _, sql in indexes)
    assert core.sql_functions_enabled()


def test_reopen_is_idempotent_and_keeps_data(workspace: Workspace) -> None:
    parts.create_part("Resistors", {"Manufacturer": "YAGEO", "Manufacturer Part Number": "RC0603FR-0710KL",
                                    "Resistance": "10k", "Tolerance": "1", "Power": "0.1",
                                    "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"})
    before = categories.list_categories()
    db.close_database()
    db.open_database(workspace)
    after = categories.list_categories()
    assert [c.model_dump() for c in after] == [c.model_dump() for c in before]
    assert parts.get_part("Resistors", "RC0603FR-0710KL") is not None
    with raw(workspace) as conn:
        assert conn.execute("SELECT count(*) FROM pf_categories").fetchone()[0] == len(CATEGORIES)


def test_deleted_builtin_category_is_not_recreated(workspace: Workspace) -> None:
    categories.delete_category("Mechanical")
    db.close_database()
    db.open_database(workspace)
    assert "Mechanical" not in {c.table for c in categories.list_categories(with_counts=False)}


def test_external_column_and_table_are_adopted_while_open(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    categories.get_category("Resistors")  # fill the cache
    notified: list[int] = []
    unsubscribe = categories.on_schema_change(lambda: notified.append(1))
    monkeypatch.setattr(categories, "_MARKER_CHECK_INTERVAL", 0.0)
    try:
        with raw(workspace) as conn:  # what Altium's "Edit Supplier Links" does
            conn.execute('ALTER TABLE "Resistors" ADD "Supplier 3" VARCHAR(255)')
            conn.execute('CREATE TABLE "Custom Parts" ("Part Number" VARCHAR(255) PRIMARY KEY, "Library Ref" VARCHAR(255), "Foo" VARCHAR(64))')
            conn.execute('CREATE TABLE "Helper" (x INTEGER)')
        res = categories.get_category("Resistors")
        assert res.field("Supplier 3") is not None
        assert res.field("Supplier 3").length == 255  # type: ignore[union-attr]  (stays VARCHAR: soft limit = size)
        custom = categories.get_category("Custom Parts")
        assert [f.column for f in custom.fields] == ["Part Number", "Library Ref", "Foo"]
        assert custom.field("Foo").length == 0  # type: ignore[union-attr]  (converted to TEXT: no limit)
        assert {row[2] for row in table_info(workspace, "Custom Parts")} == {"TEXT"}
        assert custom.field("Library Ref").system  # type: ignore[union-attr]  (metadata from COMMON_FIELDS)
        assert "Helper" not in {c.table for c in categories.list_categories(with_counts=False)}
        assert notified
    finally:
        unsubscribe()


def test_external_change_seen_inside_read_is_reconciled_later(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    categories.get_category("Resistors")
    monkeypatch.setattr(categories, "_MARKER_CHECK_INTERVAL", 0.0)
    with raw(workspace) as conn:
        conn.execute('ALTER TABLE "Resistors" ADD "Supplier 4" VARCHAR(255)')
    with core.read():
        inside = categories.get_category("Resistors")  # no write transaction possible here
        assert inside.field("Supplier 4") is None
    after = categories.get_category("Resistors")  # outside the read: reconciled now
    assert after.field("Supplier 4") is not None
    with raw(workspace) as conn:
        assert conn.execute("SELECT count(*) FROM pf_fields WHERE column_name='Supplier 4'").fetchone()[0] == 1


def test_reconcile_repairs_missing_column_and_table(workspace: Workspace) -> None:
    db.close_database()
    with raw(workspace) as conn:
        conn.execute('ALTER TABLE "Resistors" DROP COLUMN "TCR"')
        conn.execute('DROP TABLE "Mechanical"')
    db.open_database(workspace)
    assert "TCR" in {row[1] for row in table_info(workspace, "Resistors")}
    assert table_info(workspace, "Mechanical")


def test_existing_database_without_metadata_is_adopted(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Fremd", name="Fremd")
    with raw(ws) as conn:
        conn.execute('CREATE TABLE "Resistors" ("Part Number" VARCHAR(64) PRIMARY KEY, "Library Ref" VARCHAR(255), '
                     '"Resistance" VARCHAR(32), "Extra" TEXT)')
        conn.execute("INSERT INTO \"Resistors\" VALUES ('R-1', 'RES', '10k', 'x')")
        conn.execute('CREATE TABLE "Misc" ("Part Number" VARCHAR(255) PRIMARY KEY, "Value" VARCHAR(255))')
    db.open_database(ws)
    set_current(ws)
    try:
        res = categories.get_category("Resistors")
        assert [f.column for f in res.fields] == ["Part Number", "Library Ref", "Resistance", "Extra"]
        assert res.field("Resistance").kind == "quantity"  # type: ignore[union-attr]  (template metadata)
        assert res.field("Part Number").length is None  # type: ignore[union-attr]  (TEXT now: default soft limit)
        assert res.field("Extra").length == 0  # type: ignore[union-attr]  (unknown TEXT column: no invented limit)
        assert {row[2] for row in table_info(ws, "Resistors")} == {"TEXT"}
        assert categories.get_category("Misc").label == "Misc"
        assert len(categories.list_categories(with_counts=False)) == len(CATEGORIES) + 1
        assert parts.get_part("Resistors", "R-1")["Resistance"] == "10k"  # type: ignore[index]
        long_value = "x" * 300
        warnings: list[str] = []
        parts.update_part("Resistors", "R-1", {"Extra": long_value}, warnings=warnings)
        assert parts.get_part("Resistors", "R-1")["Extra"] == long_value and not warnings  # type: ignore[index]
    finally:
        db.close_database()
        set_current(None)


def test_adopted_table_with_differently_cased_key_column(tmp_path: Path) -> None:
    """Regression: "PART NUMBER" got stored as field name and broke every part write (KeyError)."""
    ws = Workspace.create(tmp_path / "Legacy", name="Legacy")
    db.open_database(ws)
    set_current(ws)
    db.close_database()
    with raw(ws) as conn:
        conn.execute('CREATE TABLE "Legacy" ("PART NUMBER" VARCHAR(64) PRIMARY KEY, "library ref" VARCHAR(255), "Value" VARCHAR(64))')
        conn.execute("INSERT INTO \"Legacy\" VALUES ('L-1', 'RES', '1k')")
    db.open_database(ws)
    try:
        legacy = categories.get_category("Legacy")
        assert [f.column for f in legacy.fields] == ["Part Number", "Library Ref", "Value"]
        assert [row[1] for row in table_info(ws, "Legacy")] == ["Part Number", "Library Ref", "Value"]
        rows, total = parts.query_parts("Legacy")
        assert total == 1 and rows[0]["Part Number"] == "L-1"
        assert parts.get_part("Legacy", "l-1") is not None
        created = parts.create_part("Resistors", {"Part Number": "R-9", "Manufacturer": "x", "Manufacturer Part Number": "R-9",
                                                  "Resistance": "1k", "Tolerance": "1", "Power": "0.1",
                                                  "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"})
        assert created["Part Number"] == "R-9"
        with pytest.raises(db.DuplicatePartError):
            parts.create_part("Resistors", {"Part Number": "L-1", "Manufacturer": "x", "Resistance": "1k",
                                            "Tolerance": "1", "Power": "0.1", "Library Ref": "RES",
                                            "Footprint Ref": "RESC1608X55N"})
        with raw(ws) as conn:  # foreign SQL with the old spelling keeps working (SQLite identifiers are case-insensitive)
            assert conn.execute('SELECT "PART NUMBER" FROM "Legacy"').fetchall() == [("L-1",)]
        # an external rename of a standard column is reverted to the canonical spelling
        db.close_database()
        with raw(ws) as conn:
            conn.execute('ALTER TABLE "Resistors" RENAME COLUMN "Library Ref" TO "LIBRARY REF"')
        db.open_database(ws)
        assert "Library Ref" in [row[1] for row in table_info(ws, "Resistors")]
        assert categories.get_category("Resistors").field("Library Ref").column == "Library Ref"  # type: ignore[union-attr]
    finally:
        db.close_database()
        set_current(None)


def _make_v1_database(ws: Workspace) -> None:
    """Turn a freshly created library into what schema 1 produced: VARCHAR(n) category columns."""
    with raw(ws) as conn:
        for (table,) in conn.execute("SELECT table_name FROM pf_categories").fetchall():
            info = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            defs = []
            for _cid, name, _type, _nn, _d, pk in info:
                size = {"Description": 1000, "Notes": 4000, "ComponentLink1URL": 2000}.get(name, 255)
                defs.append(f'"{name}" VARCHAR({size})' + (" NOT NULL PRIMARY KEY" if pk else ""))
            conn.execute(f'DROP TABLE "{table}"')
            conn.execute(f'CREATE TABLE "{table}" ({", ".join(defs)})')
        conn.execute("UPDATE pf_meta SET value='1' WHERE key='schema_version'")


def test_migration_v1_varchar_tables_become_text(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Alt", name="Alt")
    db.open_database(ws)
    db.close_database()
    _make_v1_database(ws)
    long_desc = "D" * 600
    with raw(ws) as conn:
        conn.execute('INSERT INTO "Resistors" ("Part Number", "Description", "Resistance") VALUES (?, ?, ?)',
                     ("R-OLD", long_desc, "10kΩ"))
        conn.execute('CREATE INDEX "ix_custom_res" ON "Resistors" ("Resistance")')
        conn.execute('CREATE VIEW "Resistors_View" AS SELECT "Part Number", "Resistance" FROM "Resistors"')
        # a table with a CHECK constraint cannot be rebuilt without losing it -> stays VARCHAR (no failure)
        conn.execute('DROP TABLE "Fuses"')
        conn.execute('CREATE TABLE "Fuses" ("Part Number" VARCHAR(255) NOT NULL PRIMARY KEY, '
                     '"Library Ref" VARCHAR(255) CHECK (length("Library Ref") < 100))')
        assert table_info(ws, "Resistors")[0][2] == "VARCHAR(255)"
    db.open_database(ws)
    set_current(ws)
    try:
        with raw(ws) as conn:
            assert conn.execute("SELECT value FROM pf_meta WHERE key='schema_version'").fetchone()[0] == "2"
            assert conn.execute('SELECT * FROM "Resistors_View"').fetchall() == [("R-OLD", "10kΩ")]
            index_names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='Resistors'")}
            leftovers = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'pf_tmp%'")]
        assert "ix_custom_res" in index_names and any(n.startswith("ix_pn_") for n in index_names)
        assert not leftovers
        for cat in categories.list_categories(with_counts=False):
            types = {row[2] for row in table_info(ws, cat.table)}
            if cat.table == "Fuses":
                assert "VARCHAR(255)" in types
            else:
                assert types == {"TEXT"}, (cat.table, types)
        info = table_info(ws, "Resistors")
        assert info[0][1] == "Part Number" and info[0][3] == 1 and info[0][5] == 1
        assert parts.get_part("Resistors", "R-OLD")["Description"] == long_desc  # type: ignore[index]
        assert parts.query_parts("Resistors", search="10k")[1] == 1
        assert categories.get_category("Fuses").field("Library Ref") is not None
        db.close_database()
        db.open_database(ws)  # idempotent: nothing left to convert
        assert {row[2] for row in table_info(ws, "Resistors")} == {"TEXT"}
    finally:
        db.close_database()
        set_current(None)


def test_newer_schema_version_is_refused(workspace: Workspace) -> None:
    db.close_database()
    with raw(workspace) as conn:
        conn.execute("UPDATE pf_meta SET value='99' WHERE key='schema_version'")
    with pytest.raises(SchemaError, match="neueren PartForge-Version"):
        db.open_database(workspace)
    assert not db.is_open()
    with raw(workspace) as conn:
        conn.execute(f"UPDATE pf_meta SET value='{schema.SCHEMA_VERSION}' WHERE key='schema_version'")
    db.open_database(workspace)


def test_failed_open_keeps_previous_database_open(workspace: Workspace, tmp_path: Path) -> None:
    """Regression: opening a broken library B closed library A (UI showed A, every request answered 409)."""
    parts.create_part("Resistors", {"Part Number": "R-A", "Manufacturer": "x", "Manufacturer Part Number": "R-A",
                                    "Resistance": "1k", "Tolerance": "1", "Power": "0.1", "Library Ref": "RES",
                                    "Footprint Ref": "RESC1608X55N"})
    broken = Workspace.create(tmp_path / "Kaputt", name="Kaputt")
    broken.sqlite_path.write_bytes(b"not a database" * 100)
    with pytest.raises(db.DbError, match="konnte nicht geöffnet werden"):
        db.open_database(broken)
    assert db.is_open() and core.current_workspace().root == workspace.root
    assert parts.get_part("Resistors", "R-A") is not None
    newer = Workspace.create(tmp_path / "Neuer", name="Neuer")
    db.open_database(newer)  # a different, valid library replaces A completely
    assert core.current_workspace().root == newer.root and parts.get_part("Resistors", "R-A") is None
    db.close_database()
    with raw(newer) as conn:
        conn.execute("UPDATE pf_meta SET value='99' WHERE key='schema_version'")
    db.open_database(workspace)
    with pytest.raises(SchemaError):
        db.open_database(newer)
    assert core.current_workspace().root == workspace.root and parts.get_part("Resistors", "R-A") is not None


def test_not_open_raises_workspace_not_open(workspace: Workspace) -> None:
    db.close_database()
    with pytest.raises(DatabaseNotOpen):
        categories.list_categories()
    with pytest.raises(WorkspaceNotOpen):
        db.get_engine()
    db.close_database()  # closing twice is fine


def test_invalid_database_file_gives_german_error(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Kaputt", name="Kaputt")
    ws.sqlite_path.write_bytes(b"this is not a database" * 100)
    with pytest.raises(db.DbError, match="konnte nicht geöffnet werden"):
        db.open_database(ws)
    assert not db.is_open()


def _header_mode(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:100]
    return header[18], header[19]


def test_new_database_is_created_in_wal_mode(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Neu", name="Neu")
    assert core.file_journal_mode(ws.sqlite_path) == "new"
    db.open_database(ws)
    try:
        assert _header_mode(ws.sqlite_path) == (2, 2)  # persisted in the file before Altium can connect
        assert core.file_journal_mode(ws.sqlite_path) == "wal"
        with sqlite3.connect(str(ws.sqlite_path)) as other:  # every other connection (Altium) gets WAL too
            assert other.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        db.close_database()


def test_delete_journal_setting_is_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """ARCHITEKTUR §4: SQLite always runs in WAL (in DELETE mode Altium blocks every write)."""
    settings = WorkspaceSettings()
    settings.db.journal_mode = "delete"
    ws = Workspace.create(tmp_path / "Lokal", settings=settings)
    with caplog.at_level("WARNING", logger="partforge.db.core"):
        db.open_database(ws)
    try:
        with core.read() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar_one().lower() == "wal"
        assert any("ignoriert" in r.getMessage() for r in caplog.records)
    finally:
        db.close_database()


def test_existing_wal_database_with_reader_and_delete_setting(tmp_path: Path) -> None:
    """Regression: re-issuing PRAGMA journal_mode=DELETE on connect failed ("database is locked")
    while another program (Altium) had a read transaction open."""
    ws = Workspace.create(tmp_path / "Lesend", name="Lesend")
    db.open_database(ws)
    set_current(ws)
    db.close_database()
    reader = sqlite3.connect(str(ws.sqlite_path), isolation_level=None)
    try:
        reader.execute("BEGIN")
        reader.execute('SELECT count(*) FROM "Resistors"').fetchone()
        ws.settings.db.journal_mode = "delete"
        db.open_database(ws)
        parts.create_part("Capacitors", {"Part Number": "C-1", "Manufacturer": "x", "Manufacturer Part Number": "C-1",
                                         "Capacitance": "100n", "Voltage": "50", "Library Ref": "CAP",
                                         "Footprint Ref": "CAPC1608X87N"})
        assert _header_mode(ws.sqlite_path) == (2, 2)
        reader.execute("ROLLBACK")
    finally:
        reader.close()
        db.close_database()
        set_current(None)


def test_rollback_journal_database_is_converted_once(tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Alt", name="Alt")
    db.open_database(ws)
    db.close_database()
    conn = sqlite3.connect(str(ws.sqlite_path), isolation_level=None)
    try:
        assert conn.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
    finally:
        conn.close()
    assert core.file_journal_mode(ws.sqlite_path) == "rollback"
    assert core.ensure_wal(ws.sqlite_path) == "converted"
    assert core.ensure_wal(ws.sqlite_path) == "unchanged"
    assert _header_mode(ws.sqlite_path) == (2, 2)


def test_rollback_journal_database_held_by_other_program(tmp_path: Path) -> None:
    """A DELETE-mode file kept open by Altium cannot be converted: clear German message, nothing opened."""
    ws = Workspace.create(tmp_path / "Gesperrt", name="Gesperrt")
    db.open_database(ws)
    db.close_database()
    altium = sqlite3.connect(str(ws.sqlite_path), isolation_level=None)
    try:
        assert altium.execute("PRAGMA journal_mode=DELETE").fetchone()[0] == "delete"
        altium.execute("BEGIN")
        altium.execute("SELECT count(*) FROM pf_meta").fetchone()  # shared lock like Altium's ODBC session
        with pytest.raises(db.DbError, match="WAL-Modus") as err:
            db.open_database(ws)
        assert "Altium" in str(err.value)
        assert not db.is_open()
    finally:
        altium.close()
    db.open_database(ws)  # once the other program is gone, the file is converted
    try:
        assert _header_mode(ws.sqlite_path) == (2, 2)
    finally:
        db.close_database()


def test_network_path_detection_and_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert core.is_network_path(Path(r"\\server\share\lib\PartForge.sqlite"))
    assert not core.is_network_path(tmp_path / "PartForge.sqlite")
    ws = Workspace.create(tmp_path / "Netz", name="Netz")
    monkeypatch.setattr(core, "is_network_path", lambda path: True)
    with pytest.raises(db.DbError, match="Netzlaufwerk") as err:
        db.open_database(ws)
    assert "PostgreSQL" in str(err.value)
    assert not ws.sqlite_path.exists()  # nothing was created on the share


def test_invalid_header_is_left_to_the_open_error(tmp_path: Path) -> None:
    path = tmp_path / "x.sqlite"
    path.write_bytes(b"kurz")
    assert core.file_journal_mode(path) == "invalid"
    assert core.ensure_wal(path) == "unchanged"
    path.write_bytes(b"")
    assert core.file_journal_mode(path) == "new"
    assert core.file_journal_mode(tmp_path / "fehlt.sqlite") == "new"


def test_postgres_configuration_errors_are_german_and_hide_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = WorkspaceSettings()
    settings.db.kind = "postgres"
    ws = Workspace.create(tmp_path / "PG", settings=settings)
    with pytest.raises(db.DbError, match="keine Verbindungs-URL"):
        db.open_database(ws)
    settings.db.postgres_url = "postgresql+nichtvorhanden://admin:GeheimesPasswort@db.example:5432/parts"
    with pytest.raises(db.DbError, match="unbekannten Datenbanktreiber") as err:
        db.open_database(ws)
    assert "GeheimesPasswort" not in str(err.value) and "***" in str(err.value)
    settings.db.postgres_url = "das ist keine url"
    with pytest.raises(db.DbError, match="ungültig"):
        db.open_database(ws)

    def missing_driver(*_args: object, **_kwargs: object) -> None:
        raise ModuleNotFoundError("No module named 'psycopg'", name="psycopg")

    settings.db.postgres_url = "postgresql+psycopg://admin:GeheimesPasswort@db.example:5432/parts"
    monkeypatch.setattr(core, "create_engine", missing_driver)
    with pytest.raises(db.DbError, match="psycopg") as err:
        db.open_database(ws)
    assert "GeheimesPasswort" not in str(err.value) and "fehlt der Datenbanktreiber" in str(err.value)
    assert not db.is_open()
    assert core.mask_url("postgresql://u:pw@h/db") == "postgresql://u:***@h/db"
    assert core.mask_url("::kaputt://u:pw@h") .count("pw") == 0
    assert core.mask_url(None) == ""
    assert core.describe_target(ws) == "postgresql+psycopg://admin:***@db.example:5432/parts"


def test_nested_connect_joins_and_rollback(workspace: Workspace) -> None:
    from sqlalchemy import text

    with db.connect() as outer:
        with db.connect() as inner:
            assert inner is outer
            inner.execute(text("INSERT INTO pf_meta (key, value) VALUES ('nested', '1')"))
        with db.read() as reader:
            assert reader is outer  # sees uncommitted data of the own transaction
            assert reader.execute(text("SELECT value FROM pf_meta WHERE key='nested'")).scalar_one() == "1"
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute(text("INSERT INTO pf_meta (key, value) VALUES ('rolled', '1')"))
            raise RuntimeError("abbrechen")
    with db.read() as conn:
        assert conn.execute(text("SELECT count(*) FROM pf_meta WHERE key='rolled'")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM pf_meta WHERE key='nested'")).scalar_one() == 1


def test_concurrent_writers_are_serialised(workspace: Workspace) -> None:
    import threading

    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            for i in range(10):
                parts.create_part("Capacitors", {
                    "Part Number": f"C-{n}-{i}", "Manufacturer": "Test", "Manufacturer Part Number": f"C-{n}-{i}",
                    "Capacitance": "100n", "Voltage": "50", "Library Ref": "CAP", "Footprint Ref": "CAPC1608X87N",
                })
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert parts.query_parts("Capacitors", limit=1)[1] == 40


# --------------------------------------------------------------------------- names the DbLib cannot carry


def test_unsafe_name_reason() -> None:
    for good in ("Supplier 3", "Gehäuse Größe", "Preis €", "RDS(on)", "µ-Wert", "a"):
        assert schema.unsafe_name_reason(good) is None, good
    for bad in ("Bad|Col", "Rated [UL]", "Rated]", 'Zoll"', "Line\nBreak", "Tab\tX", "Nul\x00", " Lead", "Trail ",
                "Widerstand Ω", "Pfeil →", "Emoji 🙂", ""):
        assert schema.unsafe_name_reason(bad), bad


def test_foreign_tables_and_columns_with_unsafe_names_are_not_adopted(workspace: Workspace,
                                                                       caplog: pytest.LogCaptureFixture) -> None:
    """Regression: foreign names with | [ ] " control characters, blanks at the edges or characters
    outside Windows-1252 became fields/categories and broke the DbLib (cp1252 INI with | options)."""
    unsafe_columns = ["Bad|Col", "Rated [UL]", 'Zoll"', "Line\nBreak", " Lead", "Trail ", "Widerstand Ω"]
    db.close_database()
    with raw(workspace) as conn:
        for column in unsafe_columns:
            quoted = column.replace('"', '""')
            conn.execute(f'ALTER TABLE "Resistors" ADD COLUMN "{quoted}" TEXT')
        conn.execute('ALTER TABLE "Resistors" ADD COLUMN "Supplier 3" TEXT')  # a normal foreign column
        conn.execute('CREATE TABLE "Bad|Table" ("Part Number" TEXT PRIMARY KEY, "Value" TEXT)')
        conn.execute('CREATE TABLE "Ohm Ω" ("Part Number" TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE " Leer" ("Part Number" TEXT PRIMARY KEY)')
        conn.execute('CREATE TABLE "Fremd" ("Part Number" TEXT PRIMARY KEY, "Ok Feld" TEXT, "Schlecht]" TEXT, '
                     '"Nicht ☃" TEXT)')
        conn.execute("INSERT INTO \"Fremd\" VALUES ('F-1', 'a', 'b', 'c')")
    with caplog.at_level("WARNING", logger="partforge.db.schema"):
        db.open_database(workspace)
    columns = {f.column for f in categories.get_category("Resistors").fields}
    assert "Supplier 3" in columns and not columns & set(unsafe_columns)
    tables = {c.table for c in categories.list_categories(with_counts=False)}
    assert "Fremd" in tables and not tables & {"Bad|Table", "Ohm Ω", " Leer"}
    assert [f.column for f in categories.get_category("Fremd").fields] == ["Part Number", "Ok Feld"]
    rows, total = parts.query_parts("Fremd")
    assert total == 1 and rows[0]["Ok Feld"] == "a"
    assert "Bad|Table" in caplog.text and "Widerstand Ω" in caplog.text and "nicht übernommen" in caplog.text
    from partforge.altium.dblib import build_dblib

    build = build_dblib(workspace)  # the DbLib stays writable (cp1252, no | in names)
    assert not any("|" in m.column or "]" in m.column for m in build.field_maps)
    build.text.encode("cp1252")
    # still skipped at the next open (and while the library is open), nothing is registered twice
    db.close_database()
    db.open_database(workspace)
    assert {f.column for f in categories.get_category("Resistors").fields} == columns
