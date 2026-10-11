"""ODBC test against real temporary SQLite databases through the installed 64-bit
"SQLite3 ODBC Driver" (the driver Altium uses). Skipped where the driver is missing."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from partforge.altium import dblib, odbc
from partforge.altium.dblib import write_dblib
from partforge.db import parts, seed_examples
from partforge.db.models import CategoryDef, FieldDef
from partforge.jobs import jobs
from partforge.workspace import Workspace

pyodbc = pytest.importorskip("pyodbc")
requires_driver = pytest.mark.skipif(
    dblib.SQLITE_ODBC_DRIVER not in pyodbc.drivers(), reason="64-Bit-SQLite3-ODBC-Treiber nicht installiert"
)


def F(column: str, **kw) -> FieldDef:
    return FieldDef(column=column, label=column, **kw)


def raw_database(path: Path, *, wal: bool = True, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def raw_ws(tmp_path: Path) -> Workspace:
    """Workspace whose database is a hand-made SQLite file (no PartForge engine)."""
    ws = Workspace.create(tmp_path / "Roh", name="Roh")
    raw_database(
        ws.sqlite_path,
        sql="""
        CREATE TABLE "Parts" ("Part Number" TEXT PRIMARY KEY, "Library Ref" VARCHAR(255), "Footprint Ref" TEXT,
                              "Description" VARCHAR(40), "Value" TEXT);
        INSERT INTO "Parts" VALUES ('P-1', 'RES', 'RESC1608X55N', 'Widerstand 10 kΩ ±1 %', '10 kΩ');
        INSERT INTO "Parts" VALUES ('P-2', 'CAP', 'CAPC1608X87N', 'Kondensator 4,7 µF', '4µ7');
        CREATE TABLE "NoFootprint" ("Part Number" TEXT PRIMARY KEY, "Library Ref" TEXT);
        CREATE TABLE "pf_meta" ("key" TEXT PRIMARY KEY, "value" TEXT);
        """,
    )
    return ws


PARTS = CategoryDef(table="Parts", label="Teile", fields=[F("Part Number"), F("Library Ref"), F("Footprint Ref")])


@requires_driver
def test_odbc_report_for_partforge_library(workspace):
    seed_examples(workspace)
    write_dblib(workspace)
    report = odbc.run_odbc_test(workspace)
    assert report.ok, report.issues
    assert report.connected and report.driver == "SQLite3 ODBC Driver" and report.driver_installed
    assert report.python_bits == 64 and report.driver_version and report.dbms_version
    assert report.journal_mode == "wal" and report.wal_ok and report.unicode_ok
    assert "NoCreat=1" in report.connection_string and str(workspace.sqlite_path) in report.connection_string
    tested = {t.table: t for t in report.tables}
    _rows, total = parts.query_parts("Resistors", limit=1)
    assert tested["Resistors"].rows == total > 0 and tested["Resistors"].lookup_ok
    assert all(t.ok for t in report.tables) and all(t.sized_columns == {} for t in report.tables)  # TEXT columns only
    assert "pf_meta" in report.other_tables and "Resistors" not in report.other_tables
    assert report.summary.startswith("ODBC-Verbindung in Ordnung") and report.lines[-1] == report.summary
    assert any("WAL" in line for line in report.lines)


@requires_driver
def test_disabled_category_is_not_queried(workspace):
    from partforge.db import categories

    categories.update_category("Capacitors", {"altium_enabled": False})
    report = odbc.run_odbc_test(workspace)
    caps = next(t for t in report.tables if t.table == "Capacitors")
    assert caps.enabled is False and caps.found and caps.rows is None


@requires_driver
def test_sized_and_missing_columns(raw_ws: Workspace):
    cats = [PARTS, CategoryDef(table="NoFootprint", label="Ohne", fields=[F("Part Number")])]
    report = odbc.run_odbc_test(raw_ws, categories=cats)
    result = {t.table: t for t in report.tables}
    assert result["Parts"].rows == 2 and result["Parts"].lookup_ok
    assert result["Parts"].sized_columns == {"Library Ref": 255, "Description": 40}
    assert result["NoFootprint"].missing_columns == ["Footprint Ref"] and not result["NoFootprint"].ok
    messages = " ".join(i.message for i in report.issues)
    assert "Altium kürzt" in messages and "Description (40)" in messages and "Footprint Ref" in messages
    assert not report.ok and report.summary.startswith("ODBC-Test fehlgeschlagen")


@requires_driver
def test_missing_table_and_max_rows(raw_ws: Workspace):
    ghost = CategoryDef(table="Ghost", label="Geist", fields=[F("Part Number")])
    report = odbc.run_odbc_test(raw_ws, categories=[PARTS, ghost], max_rows=1)
    result = {t.table: t for t in report.tables}
    assert result["Ghost"].found is False and "nicht sichtbar" in (result["Ghost"].error or "")
    assert result["Parts"].rows == 1 and result["Parts"].truncated
    assert any("Ghost" in i.message and i.severity == "error" for i in report.issues)


@requires_driver
def test_delete_journal_mode_is_an_error(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Delete")
    raw_database(ws.sqlite_path, wal=False, sql='CREATE TABLE "Parts" ("Part Number" TEXT PRIMARY KEY, '
                                                '"Library Ref" TEXT, "Footprint Ref" TEXT);')
    report = odbc.run_odbc_test(ws, categories=[PARTS])
    assert report.journal_mode == "delete" and report.wal_ok is False
    assert report.connected and not report.ok
    assert any("WAL" in i.message and i.severity == "error" for i in report.issues)


def test_missing_database_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # This checks the missing-file guard, independently of the driver's registration on this machine.
    monkeypatch.setattr(pyodbc, "drivers", lambda: [dblib.SQLITE_ODBC_DRIVER])

    def unexpected_connection(*_args, **_kwargs):
        pytest.fail("A missing SQLite file must be reported before attempting an ODBC connection.")

    monkeypatch.setattr(pyodbc, "connect", unexpected_connection)
    ws = Workspace.create(tmp_path / "Ohne")
    report = odbc.run_odbc_test(ws, categories=[PARTS])
    assert report.driver_installed and not report.connected and not report.ok
    assert report.connect_seconds is None and not ws.sqlite_path.exists()
    assert any("existiert nicht" in i.message for i in report.issues)


@requires_driver
def test_connect_failure_reports_driver_message(raw_ws: Workspace, monkeypatch):
    monkeypatch.setattr(
        odbc, "odbc_connection_string",
        lambda ws: "DRIVER=SQLite3 ODBC Driver;Database=C:\\gibt\\es\\nicht\\x.sqlite;NoCreat=1;",
    )
    report = odbc.run_odbc_test(raw_ws, categories=[PARTS])
    assert not report.connected and report.connect_seconds is not None
    assert any(i.message.startswith("Verbindung über ODBC fehlgeschlagen") for i in report.issues)
    assert not Path("C:\\gibt\\es\\nicht\\x.sqlite").exists()  # NoCreat=1: no empty database created


def test_missing_driver_and_bitness(raw_ws: Workspace, monkeypatch):
    monkeypatch.setattr(pyodbc, "drivers", lambda: ["SQL Server"])
    monkeypatch.setattr(odbc.struct, "calcsize", lambda fmt: 4)
    report = odbc.run_odbc_test(raw_ws, categories=[PARTS])
    assert report.python_bits == 32 and not report.driver_installed and not report.connected
    messages = [i.message for i in report.issues]
    assert any("32-Bit" in m for m in messages)
    assert any("nicht installiert" in m and "sqliteodbc" in m for m in messages)


@requires_driver
def test_dblib_pointing_elsewhere_is_reported(workspace):
    write_dblib(workspace)
    raw = workspace.dblib_path.read_bytes().replace(str(workspace.sqlite_path).encode("cp1252"), rb"Q:\Alt.sqlite")
    workspace.dblib_path.write_bytes(raw)
    report = odbc.run_odbc_test(workspace)
    assert any("andere Datenbankverbindung" in i.message for i in report.issues) and not report.ok


@requires_driver
def test_dblib_naming_the_database_under_another_file_name_is_reported(workspace):
    """An alias (8.3 name, hard link) of the database file gives Altium its own -wal/-shm."""
    write_dblib(workspace)
    alias = workspace.root / "Alias.sqlite"
    try:
        os.link(workspace.sqlite_path, alias)
    except OSError:
        pytest.skip("Dateisystem ohne Hardlinks")
    raw = workspace.dblib_path.read_bytes().replace(str(workspace.sqlite_path).encode("cp1252"),
                                                    str(alias).encode("cp1252"))
    workspace.dblib_path.write_bytes(raw)
    report = odbc.run_odbc_test(workspace)
    assert not report.ok and any("anderen Dateinamen" in i.message for i in report.issues)
    assert str(workspace.sqlite_path) in report.connection_string  # the test itself uses PartForge's spelling
    assert not (workspace.root / "Alias.sqlite-wal").exists()


def test_library_path_with_special_characters_is_not_opened(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Bib;Alt")
    raw_database(ws.sqlite_path, sql='CREATE TABLE "Parts" ("Part Number" TEXT PRIMARY KEY);')
    report = odbc.run_odbc_test(ws, categories=[PARTS])
    assert not report.connected and report.connection_string == ""
    assert report.summary.startswith("ODBC-Test fehlgeschlagen") and "Ordner ohne Sonderzeichen" in report.summary
    assert sorted(p.name for p in ws.root.iterdir() if p.is_file()) == ["PartForge.sqlite", "partforge.json"]


@requires_driver
def test_missing_dblib_is_a_warning_only(workspace):
    report = odbc.run_odbc_test(workspace)
    assert report.ok and any("DbLib" in i.message and i.severity == "warning" for i in report.issues)


def test_postgres_without_configuration(tmp_path: Path):
    ws = Workspace.create(tmp_path / "PG")
    ws.settings.db.kind = "postgres"
    report = odbc.test_odbc(ws, categories=[PARTS])
    assert report["ok"] is False and report["kind"] == "postgres"
    assert "ODBC" in report["issues"][0]["message"]


@requires_driver
def test_job_logs_every_step(raw_ws: Workspace):
    job = jobs.run_sync("altium.odbc_test", "ODBC", lambda ctx: odbc.test_odbc(raw_ws, ctx=ctx, categories=[PARTS]))
    assert job.status == "done" and job.result["ok"] is True
    texts = [entry["text"] for entry in job.log]
    assert texts[-1] == job.result["summary"] and any("Parts" in t for t in texts)


@requires_driver
def test_job_ends_with_the_summary_and_counts_properly(raw_ws: Workspace):
    """The job's final message is the German summary; „1 Tabelle“, „1 Bauteil“ (singular), „1+ Bauteile“."""
    job = jobs.run_sync("altium.odbc_test", "ODBC",
                        lambda ctx: odbc.test_odbc(raw_ws, ctx=ctx, categories=[PARTS], max_rows=1))
    assert job.status == "done" and job.message == job.result["summary"]
    assert job.message.startswith("ODBC-Verbindung in Ordnung: 1 Tabelle, 1 Bauteil gelesen in ")
    assert any(entry["text"].startswith("„Parts“: 1+ Bauteile, 5 Spalten in ") for entry in job.log)
    failed = jobs.run_sync("altium.odbc_test", "ODBC", lambda ctx: odbc.test_odbc(
        Workspace.create(raw_ws.root.parent / "Leer"), ctx=ctx, categories=[PARTS]))
    assert failed.message.startswith("ODBC-Test fehlgeschlagen: ") and failed.message == failed.result["summary"]


def test_test_odbc_is_not_collected_by_pytest():
    assert getattr(odbc.test_odbc, "__test__", True) is False
