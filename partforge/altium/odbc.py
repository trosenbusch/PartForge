"""ODBC connection test: read the library database exactly like Altium does.

Altium opens the DbLib's ``ConnectionString`` through MSDASQL and the **64-bit** ODBC
driver named in it (``SQLite3 ODBC Driver`` resp. ``PostgreSQL Unicode(x64)``). This test
uses pyodbc with the same driver and the same attributes
(:func:`partforge.altium.dblib.odbc_connection_string`) and runs the statement shapes
Altium uses (``SELECT * FROM [Table]`` per enabled category plus a key lookup), so a
problem shows up here before it shows up in Altium:

* driver missing / wrong bitness (Altium 18+ is 64-bit and needs 64-bit drivers),
* wrong or moved database path (``NoCreat=1`` makes the driver fail instead of creating
  an empty database), a DbLib that names the database under another file name (8.3
  alias: separate ``-wal``/``-shm``), a path the DbLib cannot carry (``;`` ``{`` ``}``
  ``"``, characters outside Windows-1252 – the test then does not connect at all, so no
  second spelling of the file is ever opened),
* SQLite not in WAL mode (in DELETE mode Altium's connection blocks every PartForge write),
* missing tables, missing ``Library Ref``/``Footprint Ref`` columns, ``VARCHAR(n)`` columns
  (Altium truncates their values to *n* characters), Unicode round trip.

The report is German; :func:`test_odbc` returns it as a JSON-able dict.
"""
from __future__ import annotations

import contextlib
import logging
import re
import sqlite3
import struct
import time
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..db.models import CategoryDef
from ..domain.text import plural
from ..jobs import JobContext
from ..workspace import Workspace
from .dblib import (
    POSTGRES_ODBC_DRIVER,
    SQLITE_ODBC_DRIVER,
    database_matches,
    mask_secrets,
    odbc_connection_string,
    parse_connection_string,
    read_dblib,
    same_database_file,
    same_path,
)

log = logging.getLogger(__name__)

__all__ = ["OdbcDriverStatus", "OdbcIssue", "OdbcReport", "OdbcTableResult", "driver_status", "run_odbc_test",
           "test_odbc"]

REQUIRED_COLUMNS = ("Part Number", "Library Ref", "Footprint Ref")
UNICODE_PROBE = "Ω µ ± äöü"
_SIZED_TYPE = re.compile(r"^\s*(?:N?VAR)?N?CHAR(?:ACTER)?(?:\s+VARYING)?\s*(?:\((\d+)\))?\s*$", re.IGNORECASE)


LogLevel = Literal["info", "warn", "error", "success"]
_ISSUE_LEVEL: dict[str, LogLevel] = {"error": "error", "warning": "warn", "info": "info"}


class OdbcIssue(BaseModel):
    severity: Literal["error", "warning", "info"]
    message: str


class OdbcTableResult(BaseModel):
    table: str
    label: str | None = None
    enabled: bool = True
    found: bool = False
    rows: int | None = None
    columns: int | None = None
    seconds: float | None = None
    lookup_seconds: float | None = None
    lookup_ok: bool | None = None
    truncated: bool = False  # stopped after max_rows
    missing_columns: list[str] = Field(default_factory=list)
    sized_columns: dict[str, int] = Field(default_factory=dict)  # VARCHAR(n): Altium truncates to n
    error: str | None = None
    ok: bool = False


class OdbcReport(BaseModel):
    ok: bool = False
    kind: Literal["sqlite", "postgres"] = "sqlite"
    driver: str = ""
    driver_installed: bool = False
    driver_version: str | None = None
    dbms_version: str | None = None
    python_bits: int = 64
    available_drivers: list[str] = Field(default_factory=list)
    connection_string: str = ""  # ODBC attributes, password masked
    database: str | None = None
    connected: bool = False
    connect_seconds: float | None = None
    tables: list[OdbcTableResult] = Field(default_factory=list)
    other_tables: list[str] = Field(default_factory=list)  # visible tables that are no categories
    journal_mode: str | None = None
    wal_ok: bool | None = None
    unicode_ok: bool | None = None
    total_seconds: float = 0.0
    issues: list[OdbcIssue] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)  # German report, one line per step
    summary: str = ""


#: Where the drivers come from (shown with a missing driver).
SQLITE_DRIVER_DOWNLOAD = "http://www.ch-werner.de/sqliteodbc/"
POSTGRES_DRIVER_DOWNLOAD = "https://www.postgresql.org/ftp/odbc/releases/"
_DRIVER_CACHE_S = 60.0
_driver_cache: dict[str, tuple[float, list[str] | None]] = {}


class OdbcDriverStatus(BaseModel):
    """Is the 64-bit ODBC driver installed that the DbLib names (``GET /api/altium/status`` → ``odbc``)?

    Cheap: the driver list of the registry (``pyodbc.drivers()``, cached for a minute) – no connection."""

    kind: Literal["sqlite", "postgres"]
    driver: str = Field(description="Treibername in der DbLib, z. B. „SQLite3 ODBC Driver“")
    installed: bool | None = Field(description="None = nicht feststellbar")
    message: str = Field(description="Deutscher Satz mit Lösungshinweis")
    download: str | None = Field(default=None, description="Bezugsquelle des Treibers")


def _installed_drivers() -> list[str] | None:
    now = time.monotonic()
    cached = _driver_cache.get("drivers")
    if cached is not None and now - cached[0] < _DRIVER_CACHE_S:
        return cached[1]
    try:
        import pyodbc

        drivers: list[str] | None = sorted(pyodbc.drivers())
    except Exception as exc:  # noqa: BLE001 - pyodbc missing or the registry not readable
        log.info("ODBC-Treiberliste nicht lesbar: %s", exc)
        drivers = None
    _driver_cache["drivers"] = (now, drivers)
    return drivers


def driver_status(ws: Workspace) -> OdbcDriverStatus:
    """Whether the ODBC driver of the DbLib (``SQLite3 ODBC Driver`` / ``PostgreSQL Unicode(x64)``) is installed –
    without it Altium cannot read a single part (review finding F4)."""
    kind: Literal["sqlite", "postgres"] = "postgres" if ws.settings.db.kind == "postgres" else "sqlite"
    driver = SQLITE_ODBC_DRIVER if kind == "sqlite" else POSTGRES_ODBC_DRIVER
    download = SQLITE_DRIVER_DOWNLOAD if kind == "sqlite" else POSTGRES_DRIVER_DOWNLOAD
    try:
        driver = parse_connection_string(odbc_connection_string(ws))[1].get("driver") or driver
    except Exception as exc:  # noqa: BLE001 - e.g. PostgreSQL without ODBC settings: the DbLib status says why
        log.debug("ODBC-Verbindung der DbLib nicht bestimmbar: %s", exc)
    drivers = _installed_drivers()
    bits = struct.calcsize("P") * 8
    if drivers is None:
        return OdbcDriverStatus(kind=kind, driver=driver, installed=None, download=download,
                                message=f"Ob der ODBC-Treiber „{driver}“ installiert ist, lässt sich nicht feststellen – "
                                        "„ODBC testen“ prüft es.")
    if driver.casefold() in {d.casefold() for d in drivers}:
        return OdbcDriverStatus(kind=kind, driver=driver, installed=True,
                                message=f"ODBC-Treiber „{driver}“ ({bits} Bit) ist installiert.")
    which = "den 64-Bit-SQLite-ODBC-Treiber (sqliteodbc_w64, ch-werner.de)" if kind == "sqlite" else "den 64-Bit-Treiber psqlODBC"
    return OdbcDriverStatus(kind=kind, driver=driver, installed=False, download=download,
                            message=f"Der ODBC-Treiber „{driver}“ ({bits} Bit) ist nicht installiert – Altium kann die "
                                    f"Bauteile so nicht lesen. Bitte {which} installieren und danach „ODBC testen“.")


def _secs(value: float | None) -> str:
    return "–" if value is None else f"{value:.2f} s".replace(".", ",")


class _Report:
    """Collects issues and report lines (and mirrors them into the job log)."""

    def __init__(self, report: OdbcReport, ctx: JobContext | None):
        self.report = report
        self.ctx = ctx

    def line(self, text: str, level: LogLevel = "info") -> None:
        self.report.lines.append(text)
        if self.ctx is not None:
            self.ctx.log(text, level)

    def issue(self, severity: Literal["error", "warning", "info"], message: str) -> None:
        self.report.issues.append(OdbcIssue(severity=severity, message=message))
        self.line(message, _ISSUE_LEVEL[severity])

    def progress(self, fraction: float, message: str) -> None:
        if self.ctx is not None:
            self.ctx.check_cancelled()
            self.ctx.progress(fraction, message)


def _quote(kind: str, name: str) -> str:
    if kind == "postgres":
        return '"' + name.replace('"', '""') + '"'
    return "[" + name.replace("]", "]]") + "]"


def _driver_message(exc: BaseException) -> str:
    args: tuple[Any, ...] = tuple(getattr(exc, "args", ()) or ())
    text = str(args[1] if len(args) > 1 else exc).strip()
    text = re.sub(r"\s*\(\d+\)\s*\(SQL\w+\)\s*$", "", text)
    return text or exc.__class__.__name__


def _check_sqlite_file(ws: Workspace, out: _Report) -> None:
    from ..db.core import file_journal_mode, is_network_path

    path = ws.sqlite_path
    out.report.database = str(path)
    if is_network_path(path):
        out.issue("error", "Die SQLite-Datenbank liegt auf einem Netzlaufwerk – dort funktioniert der WAL-Modus nicht. "
                           "Für die gemeinsame Nutzung bitte PostgreSQL verwenden.")
    header = file_journal_mode(path)
    if header == "new":
        out.issue("error", f"Die Datenbankdatei „{path}“ existiert nicht.")
        return
    if header == "invalid":
        out.issue("error", f"„{path}“ ist keine SQLite-Datenbank.")
        return
    mode: str | None = None
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=2.0)
        try:
            row = conn.execute("PRAGMA journal_mode").fetchone()
            mode = str(row[0]).lower() if row else None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        log.debug("PRAGMA journal_mode nicht lesbar: %s", exc)
        mode = "wal" if header == "wal" else "delete"
    out.report.journal_mode = mode
    out.report.wal_ok = mode == "wal"
    if mode == "wal":
        out.line("Journalmodus: WAL – Altium und PartForge können gleichzeitig arbeiten.", "success")
    else:
        out.issue("error", f"Die Datenbank läuft im Journalmodus „{mode}“ statt WAL: solange Altium sie liest, kann "
                           "PartForge nicht speichern. Bitte Altium schließen und die Bibliothek erneut öffnen "
                           "(PartForge stellt sie dann auf WAL um).")


def _sized_columns(cursor: Any, table: str) -> dict[str, int]:
    """Columns declared ``VARCHAR(n)``/``CHAR(n)`` (Altium truncates values to n characters)."""
    sized: dict[str, int] = {}
    with contextlib.suppress(Exception):
        for col in cursor.columns(table=table):
            type_name = str(getattr(col, "type_name", "") or "")
            m = _SIZED_TYPE.match(type_name)
            if not m:
                continue
            size = int(m.group(1)) if m.group(1) else int(getattr(col, "column_size", 0) or 0)
            if 0 < size < 65535:
                sized[str(col.column_name)] = size
    return sized


def _test_table(conn: Any, kind: str, cat: CategoryDef, max_rows: int | None) -> OdbcTableResult:
    """``SELECT * FROM [Table]`` (Altium's statement) plus one key lookup."""
    result = OdbcTableResult(table=cat.table, label=cat.label, enabled=True, found=True)
    started = time.perf_counter()
    first_pn: str | None = None
    cursor = conn.cursor()
    try:
        cursor.execute(f"SELECT * FROM {_quote(kind, cat.table)}")
        names = [str(d[0]) for d in cursor.description or []]
        result.columns = len(names)
        folded = {n.casefold(): i for i, n in enumerate(names)}
        result.missing_columns = [c for c in REQUIRED_COLUMNS if c.casefold() not in folded]
        key_index = folded.get("part number")
        rows = 0
        while True:
            batch = cursor.fetchmany(500 if max_rows is None else max(1, min(500, max_rows - rows)))
            if not batch:
                break
            if first_pn is None and key_index is not None:
                first_pn = next((str(r[key_index]) for r in batch if r[key_index] not in (None, "")), None)
            rows += len(batch)
            if max_rows is not None and rows >= max_rows:
                result.truncated = cursor.fetchone() is not None
                break
        result.rows = rows
    except Exception as exc:  # noqa: BLE001 - every driver error is reported
        result.error = _driver_message(exc)
        return result
    finally:
        result.seconds = round(time.perf_counter() - started, 4)
        with contextlib.suppress(Exception):
            cursor.close()  # releases the statement (a partly read result keeps a read lock)
    if first_pn is not None:
        started = time.perf_counter()
        lookup = conn.cursor()
        try:
            lookup.execute(
                f"SELECT * FROM {_quote(kind, cat.table)} WHERE {_quote(kind, 'Part Number')} = ?", first_pn
            )
            result.lookup_ok = lookup.fetchone() is not None
        except Exception as exc:  # noqa: BLE001
            result.lookup_ok = False
            result.error = f"Schlüsselsuche fehlgeschlagen: {_driver_message(exc)}"
        finally:
            result.lookup_seconds = round(time.perf_counter() - started, 4)
            with contextlib.suppress(Exception):
                lookup.close()
    columns = conn.cursor()
    try:
        result.sized_columns = _sized_columns(columns, cat.table)
    finally:
        with contextlib.suppress(Exception):
            columns.close()
    result.ok = result.error is None and not result.missing_columns and result.lookup_ok is not False
    return result


def _visible_tables(cursor: Any) -> list[str]:
    names: list[str] = []
    for row in cursor.tables():
        kind = str(getattr(row, "table_type", "") or "").upper()
        if kind in ("TABLE", "VIEW"):
            names.append(str(row.table_name))
    return names


def _unicode_ok(conn: Any, kind: str) -> bool | None:
    sql = "SELECT CAST(? AS TEXT)" if kind == "postgres" else "SELECT ?"
    try:
        cursor = conn.cursor()
        cursor.execute(sql, UNICODE_PROBE)
        row = cursor.fetchone()
        cursor.close()
    except Exception as exc:  # noqa: BLE001 - optional check
        log.debug("Unicode-Prüfung nicht möglich: %s", exc)
        return None
    return bool(row) and row[0] == UNICODE_PROBE


def _compare_with_dblib(ws: Workspace, out: _Report, odbc: str) -> None:
    path = ws.dblib_path
    if not path.is_file():
        out.issue("warning", f"Die DbLib „{ws.settings.dblib_file}“ fehlt – Altium kennt die Datenbank noch nicht "
                             "(„DbLib neu erzeugen“).")
        return
    try:
        info = read_dblib(path)
    except Exception as exc:  # noqa: BLE001
        out.issue("warning", f"Die DbLib kann nicht gelesen werden: {exc}")
        return
    _outer, expected = parse_connection_string(odbc)
    if ws.settings.db.kind == "postgres":
        same = {k: v for k, v in info.odbc.items() if k != "pwd"} == {k: v for k, v in expected.items() if k != "pwd"}
    else:
        same = same_database_file(info.database_path, ws.sqlite_path)
        if not same and same_path(info.database_path, ws.sqlite_path):
            out.issue("error", f"Die DbLib verweist unter einem anderen Dateinamen („{info.database_path}“, z. B. "
                               "8.3-Kurzname) auf die Datenbank – SQLite führt dann für Altium eigene WAL-Dateien. "
                               "Bitte „DbLib neu erzeugen“ wählen.")
            return
    if not same:
        out.issue("error", "Die DbLib verwendet eine andere Datenbankverbindung als die Bibliothek (Ordner verschoben?). "
                           "Bitte „DbLib neu erzeugen“ wählen.")


def run_odbc_test(
    ws: Workspace,
    *,
    ctx: JobContext | None = None,
    categories: Sequence[CategoryDef] | None = None,
    max_rows: int | None = None,
) -> OdbcReport:
    """Run the ODBC test (see module docstring) and return the report model."""
    started = time.perf_counter()
    kind: Literal["sqlite", "postgres"] = "postgres" if ws.settings.db.kind == "postgres" else "sqlite"
    report = OdbcReport(kind=kind, python_bits=struct.calcsize("P") * 8)
    out = _Report(report, ctx)
    out.progress(0.02, "ODBC-Treiber werden geprüft …")
    try:
        odbc = odbc_connection_string(ws)
    except Exception as exc:  # noqa: BLE001 - e.g. PostgreSQL without ODBC settings
        out.issue("error", str(exc))
        return _finish(out, started)
    _outer, attrs = parse_connection_string(odbc)
    report.driver = attrs.get("driver", SQLITE_ODBC_DRIVER if kind == "sqlite" else POSTGRES_ODBC_DRIVER)
    report.connection_string = mask_secrets(odbc)
    if kind == "postgres":
        report.database = mask_secrets(f"{attrs.get('server', '')}:{attrs.get('port', '')}/{attrs.get('database', '')}")
    try:
        import pyodbc
    except ImportError:
        out.issue("error", "Das Python-Paket pyodbc fehlt – der ODBC-Test ist nicht möglich.")
        return _finish(out, started)
    try:
        report.available_drivers = sorted(pyodbc.drivers())
    except Exception as exc:  # noqa: BLE001
        out.issue("error", f"Die ODBC-Treiberliste ist nicht lesbar: {_driver_message(exc)}")
        return _finish(out, started)
    report.driver_installed = report.driver.casefold() in {d.casefold() for d in report.available_drivers}
    if report.python_bits != 64:
        out.issue("warning", f"PartForge läuft als {report.python_bits}-Bit-Prozess – ob der 64-Bit-Treiber für Altium "
                             "installiert ist, lässt sich so nicht prüfen.")
    if report.driver_installed:
        out.line(f"ODBC-Treiber „{report.driver}“ ({report.python_bits} Bit) ist installiert.", "success")
    else:
        hint = ("Bitte den 64-Bit-SQLite-ODBC-Treiber (sqliteodbc_w64, ch-werner.de) installieren."
                if kind == "sqlite" else "Bitte den 64-Bit-Treiber psqlODBC installieren.")
        out.issue("error", f"Der {report.python_bits}-Bit-ODBC-Treiber „{report.driver}“ ist nicht installiert – Altium "
                           f"kann die Datenbank nicht lesen. {hint}")
        return _finish(out, started)

    if kind == "sqlite":
        out.progress(0.08, "Datenbankdatei wird geprüft …")
        _check_sqlite_file(ws, out)
        if report.journal_mode is None and any(i.severity == "error" for i in report.issues):
            return _finish(out, started)
    _compare_with_dblib(ws, out, odbc)

    out.progress(0.12, "Verbindung wird aufgebaut …")
    t0 = time.perf_counter()
    try:
        conn = pyodbc.connect(odbc, autocommit=True, timeout=15)
    except Exception as exc:  # noqa: BLE001 - driver message is shown to the user
        report.connect_seconds = round(time.perf_counter() - t0, 4)
        out.issue("error", f"Verbindung über ODBC fehlgeschlagen: {_driver_message(exc)}")
        return _finish(out, started)
    report.connected = True
    report.connect_seconds = round(time.perf_counter() - t0, 4)
    try:
        with contextlib.suppress(Exception):
            report.driver_version = str(conn.getinfo(pyodbc.SQL_DRIVER_VER))
        with contextlib.suppress(Exception):
            report.dbms_version = str(conn.getinfo(pyodbc.SQL_DBMS_VER))
        version = f" (Treiber {report.driver_version}, Datenbank {report.dbms_version})" if report.driver_version else ""
        out.line(f"Verbindung hergestellt in {_secs(report.connect_seconds)}{version}.", "success")
        _test_tables(ws, conn, kind, out, categories, max_rows)
        report.unicode_ok = _unicode_ok(conn, kind)
        if report.unicode_ok is False:
            out.issue("warning", "Sonderzeichen (Ω, µ, ±, Umlaute) kommen über ODBC nicht unverändert an – bitte die "
                                 "Treiberoptionen prüfen (kein NoWCHAR).")
        elif report.unicode_ok:
            out.line("Sonderzeichen (Ω, µ, ±, Umlaute) kommen unverändert an.", "success")
    finally:
        with contextlib.suppress(Exception):
            conn.close()
    return _finish(out, started)


def _test_tables(
    ws: Workspace,
    conn: Any,
    kind: str,
    out: _Report,
    categories: Sequence[CategoryDef] | None,
    max_rows: int | None,
) -> None:
    report = out.report
    if categories is None:
        if not database_matches(ws):
            out.issue("warning", "Die Datenbank der Bibliothek ist nicht geöffnet – die Tabellen wurden nicht geprüft.")
            return
        from ..db import categories as db_categories

        cats = db_categories.list_categories(with_counts=False)
    else:
        cats = list(categories)
    try:
        cursor = conn.cursor()
        try:
            visible = _visible_tables(cursor)
        finally:
            with contextlib.suppress(Exception):
                cursor.close()
    except Exception as exc:  # noqa: BLE001
        out.issue("error", f"Die Tabellenliste ist über ODBC nicht lesbar: {_driver_message(exc)}")
        return
    visible_folded = {v.casefold() for v in visible}
    category_names = {c.table.casefold() for c in cats}
    report.other_tables = sorted((v for v in visible if v.casefold() not in category_names), key=str.casefold)
    out.line(f"{plural(len(visible), 'Tabelle/Sicht', 'Tabellen/Sichten')} über ODBC sichtbar.")
    enabled = [c for c in cats if c.altium_enabled]
    for i, cat in enumerate(cats):
        out.progress(0.15 + 0.8 * i / max(len(cats), 1), f"Tabelle „{cat.table}“ wird gelesen …")
        if cat.table.casefold() not in visible_folded:
            result = OdbcTableResult(table=cat.table, label=cat.label, enabled=cat.altium_enabled, found=False,
                                     error="Tabelle über ODBC nicht sichtbar")
            report.tables.append(result)
            out.issue("error" if cat.altium_enabled else "warning",
                      f"Tabelle „{cat.table}“ ist über ODBC nicht sichtbar.")
            continue
        if not cat.altium_enabled:
            report.tables.append(OdbcTableResult(table=cat.table, label=cat.label, enabled=False, found=True, ok=True))
            continue
        result = _test_table(conn, kind, cat, max_rows)
        report.tables.append(result)
        if result.error:
            out.issue("error", f"Tabelle „{cat.table}“: {result.error}")
            continue
        if result.truncated:  # stopped after max_rows: "100+ Bauteile"
            rows = plural(result.rows or 0, "Bauteile", "Bauteile").replace(" ", "+ ", 1)
        else:
            rows = plural(result.rows or 0, "Bauteil", "Bauteile")
        lookup = f", Schlüsselsuche {_secs(result.lookup_seconds)}" if result.lookup_seconds is not None else ""
        columns = plural(result.columns or 0, "Spalte", "Spalten")
        out.line(f"„{cat.table}“: {rows}, {columns} in {_secs(result.seconds)}{lookup}.",
                 "success" if result.ok else "warn")
        if result.missing_columns:
            out.issue("error", f"Tabelle „{cat.table}“: Spalten fehlen: {', '.join(result.missing_columns)}.")
        if result.lookup_ok is False:
            out.issue("error", f"Tabelle „{cat.table}“: die Suche nach der Teilenummer findet das Bauteil nicht.")
        if result.sized_columns:
            details = ", ".join(f"{name} ({size})" for name, size in sorted(result.sized_columns.items()))
            out.issue("warning", f"Tabelle „{cat.table}“: Spalten mit fester Länge – Altium kürzt längere Werte: "
                                 f"{details}.")
    if not enabled:
        out.issue("warning", "Keine Kategorie ist für Altium aktiviert.")


def _finish(out: _Report, started: float) -> OdbcReport:
    report = out.report
    report.total_seconds = round(time.perf_counter() - started, 4)
    errors = [i for i in report.issues if i.severity == "error"]
    warnings = [i for i in report.issues if i.severity == "warning"]
    report.ok = report.connected and not errors
    tested = [t for t in report.tables if t.enabled and t.found]
    parts = sum(t.rows or 0 for t in tested)
    if report.ok:
        report.summary = (
            f"ODBC-Verbindung in Ordnung: {plural(len(tested), 'Tabelle', 'Tabellen')}, "
            f"{plural(parts, 'Bauteil', 'Bauteile')} gelesen in {_secs(report.total_seconds)}"
            + (f" ({plural(len(warnings), 'Hinweis', 'Hinweise')})." if warnings else ".")
        )
    elif errors:
        report.summary = f"ODBC-Test fehlgeschlagen: {errors[0].message}"
    else:
        report.summary = "ODBC-Test nicht vollständig."
    out.line(report.summary, "success" if report.ok else "error")
    if out.ctx is not None:  # the job ends with the outcome (job.message)
        out.ctx.progress(1.0, report.summary)
    return report


def test_odbc(
    ws: Workspace,
    *,
    ctx: JobContext | None = None,
    categories: Sequence[CategoryDef] | None = None,
    max_rows: int | None = None,
) -> dict[str, Any]:
    """Connect to the library database like Altium and return a German report (dict)."""
    return run_odbc_test(ws, ctx=ctx, categories=categories, max_rows=max_rows).model_dump(mode="json")


test_odbc.__test__ = False  # type: ignore[attr-defined]  # not a pytest test despite the name
