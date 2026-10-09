"""DbLib file handling: parser and round trip, ensure/write (reasons, UI state, atomic
write), status issues, Altium install cache and the automatic regeneration."""
from __future__ import annotations

import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from partforge import events
from partforge.altium import dblib
from partforge.altium.bridge.core import DbLibInstallState, InstalledDbLib
from partforge.altium.dblib import (
    DbLibAutoWriter,
    DbLibError,
    DbLibPathError,
    cached_install_state,
    cached_install_states,
    classify_duplicate,
    classify_install_state,
    dblib_status,
    duplicate_advice,
    duplicates_message,
    ensure_dblib,
    forget_install_state,
    parse_dblib,
    read_dblib,
    remember_install_state,
    render_dblib,
    same_database_file,
    same_path,
    status_model,
    write_dblib,
)
from partforge.db import categories, close_database, open_database
from partforge.db.models import FieldDef
from partforge.workspace import Workspace, set_current


def codes(ws: Workspace) -> set[str]:
    return {i.code for i in status_model(ws).issues}


def text_of(path: Path) -> str:
    """File text with the original line endings (read_text would translate CRLF)."""
    return path.read_bytes().decode("cp1252")


@pytest.fixture(autouse=True)
def clean_install_cache():
    path = dblib._cache_path()
    path.unlink(missing_ok=True)
    yield
    path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- parse / round trip


def test_round_trip(workspace):
    path = write_dblib(workspace)
    info = read_dblib(path)
    build = dblib.build_dblib(workspace)
    assert info.version == "1.1" and info.encoding == "cp1252" and not info.bom and info.line_endings == "crlf"
    assert info.database_path == str(workspace.sqlite_path)
    assert info.odbc["driver"] == "SQLite3 ODBC Driver" and info.odbc["nocreat"] == "1"
    assert [t.name for t in info.tables] == [t.name for t in build.tables]
    assert [(t.name, t.enabled, t.user_where_text) for t in info.tables] == [
        (t.name, t.enabled, t.user_where_text) for t in build.tables
    ]
    assert [m.key() for m in info.field_maps] == [m.key() for m in build.field_maps]
    assert list(info.links) == list(dblib.LINK_KEYS)
    assert info.warnings == [] and info.enabled_tables


def test_parser_tolerates_other_writers():
    text = (
        "[OutputDatabaseLinkFile]\nVersion = 1.1\n\n; Kommentar\n[DatabaseLinks]\n"
        'ConnectionString=Provider=MSDASQL.1;Extended Properties="Driver={SQLite3 ODBC Driver};Database=C:\\a=b.db;"\n'
        "LastFocusedTable=X\n"
        "[Table2]\nTableName=B\nEnabled=False\n[Table1]\nTableName=A\nEnabled=True\nUserWhere=1\nFoo=bar\n"
        "BrowserOrder_Visible=Part Number0=10\n[Table3]\nEnabled=True\n"
        "[FieldMap1]\nOptions=FieldName=A.Part Number|FieldType=0|ParameterName=Part Number|Neu=1\n"
        "[FieldMap2]\nOptions=FieldType=1\n"
        "verwaiste Zeile\n"
    )
    info = parse_dblib(text)
    assert info.version == "1.1" and info.line_endings == "lf"
    assert info.database_path == "C:\\a=b.db"
    assert [t.name for t in info.tables] == ["A", "B"]  # numbered order, nameless table dropped
    a = info.tables[0]
    assert a.enabled and a.user_where == 1 and a.extra == {"Foo": "bar"} and a.ui_state == {"BrowserOrder_Visible": "Part Number0=10"}
    assert info.field_maps[0].table == "A" and info.field_maps[0].column == "Part Number"
    assert info.field_maps[0].field_type == 0 and info.field_maps[0].extra == {"Neu": "1"}
    assert len(info.field_maps) == 1
    assert any("verwaiste" in w for w in info.warnings) and any("Table3" in w for w in info.warnings)


def test_read_detects_bom_utf8_and_garbage(tmp_path: Path):
    good = "[OutputDatabaseLinkFile]\r\nVersion=1.1\r\n[DatabaseLinks]\r\nConnectionString=x\r\n"
    bom = tmp_path / "bom.DbLib"
    bom.write_bytes(b"\xef\xbb\xbf" + good.encode())
    info = read_dblib(bom)
    assert info.bom and info.encoding == "utf-8" and info.version == "1.1"
    utf8 = tmp_path / "utf8.DbLib"
    utf8.write_bytes((good + "LastFocusedTable=Widerstände\r\n").encode("utf-8"))
    assert read_dblib(utf8).encoding == "utf-8"
    ansi = tmp_path / "ansi.DbLib"
    ansi.write_bytes((good + "LastFocusedTable=Widerstände\r\n").encode("cp1252"))
    assert read_dblib(ansi).links["LastFocusedTable"] == "Widerstände"
    garbage = tmp_path / "garbage.DbLib"
    garbage.write_bytes(b"\x00\x01kein ini")
    with pytest.raises(DbLibError, match="keine gültige"):
        read_dblib(garbage)
    with pytest.raises(DbLibError, match="existiert nicht"):
        read_dblib(tmp_path / "fehlt.DbLib")


# --------------------------------------------------------------------------- ensure / write


def test_ensure_reasons(workspace):
    first = ensure_dblib(workspace)
    assert first.written and first.reason == "missing"
    stamp = workspace.dblib_path.stat().st_mtime_ns
    time.sleep(0.02)
    again = ensure_dblib(workspace)
    assert not again.written and again.reason == "unchanged"
    assert workspace.dblib_path.stat().st_mtime_ns == stamp

    categories.add_field("Resistors", FieldDef(column="Prueffeld", label="Prüffeld", show_on_schematic=True))
    outdated = ensure_dblib(workspace)
    assert outdated.written and outdated.reason == "outdated"
    assert "FieldNameOnly=Prueffeld" in text_of(workspace.dblib_path)

    raw = workspace.dblib_path.read_bytes().replace(str(workspace.sqlite_path).encode("cp1252"), rb"D:\Alt\PartForge.sqlite")
    workspace.dblib_path.write_bytes(raw)
    moved = ensure_dblib(workspace)
    assert moved.written and moved.reason == "db_moved"

    workspace.dblib_path.write_bytes(workspace.dblib_path.read_bytes().replace(b"\r\n", b"\n"))
    fmt = ensure_dblib(workspace)
    assert fmt.written and fmt.reason == "format"
    assert ensure_dblib(workspace, force=True).reason == "unchanged"  # identical bytes are never rewritten


def test_ensure_keeps_altium_ui_state(workspace):
    write_dblib(workspace)
    text = text_of(workspace.dblib_path)
    text = text.replace("TopPanelCollapsed=0", "TopPanelCollapsed=1").replace(
        "LastFocusedTable=Resistors", "LastFocusedTable=Capacitors"
    )
    text = text.replace(
        "TableName=Capacitors\r\nEnabled=True\r\nUserWhere=0\r\nUserWhereText=[Part Number] = '{Part Number}'\r\n",
        "TableName=Capacitors\r\nEnabled=True\r\nUserWhere=0\r\nUserWhereText=[Part Number] = '{Part Number}'\r\n"
        "BrowserOrder_Sorting=Capacitance0=1\r\n",
    )
    workspace.dblib_path.write_bytes(text.encode("cp1252"))
    assert ensure_dblib(workspace).reason == "unchanged"  # UI state only: nothing to do
    assert status_model(workspace).up_to_date

    categories.update_category("Inductors", {"altium_enabled": False})
    assert ensure_dblib(workspace).written
    new = text_of(workspace.dblib_path)
    assert "TopPanelCollapsed=1" in new and "LastFocusedTable=Capacitors" in new
    assert "BrowserOrder_Sorting=Capacitance0=1" in new
    assert "TableName=Inductors\r\nEnabled=False" in new


def test_invalid_file_name(workspace):
    workspace.settings.dblib_file = "Unterordner\\PartForge.DbLib"
    with pytest.raises(DbLibError, match="reiner Dateiname"):
        ensure_dblib(workspace)
    workspace.settings.dblib_file = "PartForge.txt"
    with pytest.raises(DbLibError, match=r"\.DbLib"):
        write_dblib(workspace)
    assert "file_name" in codes(workspace)
    workspace.settings.dblib_file = "Teile Ω.DbLib"  # the bridge cannot carry it (Latin-1 only)
    with pytest.raises(DbLibError, match="Umlaute"):
        ensure_dblib(workspace)
    workspace.settings.dblib_file = "Bauteile Übersicht.DbLib"
    assert ensure_dblib(workspace).written


# --------------------------------------------------------------------------- database path spelling


@contextmanager
def opened(root: Path) -> Iterator[Workspace]:
    ws = Workspace.create(root)
    open_database(ws)
    set_current(ws)
    try:
        yield ws
    finally:
        close_database()
        set_current(None)


def test_library_in_folder_with_special_characters(tmp_path: Path):
    """No DbLib that names the database under a second spelling (8.3 alias) – a clear error instead."""
    with opened(tmp_path / "Bib;Alt") as ws:
        with pytest.raises(DbLibPathError, match="Ordner ohne Sonderzeichen"):
            ensure_dblib(ws)
        assert not ws.dblib_path.exists()
        writer = DbLibAutoWriter()
        assert writer.ensure(ws) is None and "Sonderzeichen" in (writer.last_error or "")
        status = status_model(ws)
        found = {i.code: i for i in status.issues}
        assert found["db_path_chars"].severity == "error" and ";" in found["db_path_chars"].message
        assert "build" not in found and not status.db_path_ok and status.database == str(ws.sqlite_path)
        from partforge.altium import odbc

        report = odbc.run_odbc_test(ws)
        assert not report.connected and not report.ok and "Sonderzeichen" in report.summary
    assert [p.name for p in (tmp_path / "Bib;Alt").iterdir() if "~" in p.name] == []  # no alias -wal/-shm


def _short_name(path: Path) -> str | None:
    import ctypes
    from ctypes import wintypes

    get_short = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(1024)
    length = get_short(str(path), buffer, 1024)
    short = buffer.value if 0 < length < 1024 else None
    return short if short and Path(short).name.casefold() != path.name.casefold() else None


@pytest.mark.parametrize("alias_kind", ["hardlink", "short_name"])
def test_dblib_naming_the_database_under_another_file_name(workspace, alias_kind: str):
    write_dblib(workspace)
    if alias_kind == "hardlink":
        alias = str(workspace.root / "Alias.sqlite")
        try:
            os.link(workspace.sqlite_path, alias)
        except OSError:
            pytest.skip("Dateisystem ohne Hardlinks")
    else:
        short = _short_name(workspace.sqlite_path)
        if short is None:
            pytest.skip("8.3-Kurznamen auf diesem Laufwerk abgeschaltet")
        alias = short
    raw = workspace.dblib_path.read_bytes().replace(str(workspace.sqlite_path).encode("cp1252"), alias.encode("cp1252"))
    workspace.dblib_path.write_bytes(raw)
    status = status_model(workspace)
    assert not status.db_path_ok and status.dblib_database == alias
    issue = next(i for i in status.issues if i.code == "db_path")
    assert "anderen Dateinamen" in issue.message and "WAL" in issue.message
    result = ensure_dblib(workspace)
    assert result.written and result.reason == "db_moved"
    assert status_model(workspace).db_path_ok and read_dblib(workspace.dblib_path).database_path == str(workspace.sqlite_path)


def test_same_database_file(tmp_path: Path):
    db = tmp_path / "Bib" / "PartForge.sqlite"
    db.parent.mkdir()
    db.write_bytes(b"x")
    assert same_database_file(str(db), db) and same_database_file(str(db).upper(), db)
    assert same_database_file(str(tmp_path / "Bib" / ".." / "Bib" / "PartForge.sqlite"), db)
    assert not same_database_file(str(tmp_path / "Bib" / "Andere.sqlite"), db)
    assert not same_database_file(None, db) and not same_database_file("", db)
    link = tmp_path / "Bib" / "Alias.sqlite"
    os.link(db, link)
    assert same_path(link, db) and not same_database_file(link, db)  # same file, other name: own -wal/-shm
    _winapi = pytest.importorskip("_winapi")
    junction = tmp_path / "Abzweig"
    _winapi.CreateJunction(str(db.parent), str(junction))
    assert same_database_file(junction / "PartForge.sqlite", db)  # folder alias: -wal/-shm beside the same file


def test_adopted_tables_with_unsafe_names_stay_out_of_the_dblib(workspace):
    import sqlite3

    close_database()
    conn = sqlite3.connect(workspace.sqlite_path)
    conn.execute('CREATE TABLE "Bad|Name" ("Part Number" TEXT PRIMARY KEY, "Library Ref" TEXT)')
    conn.execute('CREATE TABLE "Evil\r\n[Table1]\r\nTableName=Hijack" ("Part Number" TEXT PRIMARY KEY)')
    conn.commit()
    conn.close()
    open_database(workspace)
    set_current(workspace)
    result = ensure_dblib(workspace)
    text = text_of(workspace.dblib_path)
    assert result.written and "Hijack" not in text and "Bad|Name" not in text and "Evil" not in text
    info = read_dblib(workspace.dblib_path)
    assert info.warnings == [] and not any(t.name.startswith(("Bad", "Evil", "Hijack")) for t in info.tables)
    assert sum(1 for w in result.warnings if "Bad|Name" in w or "Evil\\r\\n" in w) == 2
    status = status_model(workspace)
    assert status.up_to_date and "unsafe_name" in {i.code for i in status.issues}


def test_atomic_write_falls_back_when_rename_is_blocked(workspace, monkeypatch):
    write_dblib(workspace)

    def blocked(src, dst):
        raise PermissionError(13, "Zugriff verweigert")

    monkeypatch.setattr(dblib.os, "replace", blocked)
    monkeypatch.setattr(dblib.time, "sleep", lambda s: None)
    categories.update_category("Fuses", {"altium_enabled": False})
    assert ensure_dblib(workspace).written
    assert "TableName=Fuses\r\nEnabled=False" in text_of(workspace.dblib_path)
    assert not [p for p in workspace.root.iterdir() if p.name.endswith(".tmp")]

    real_open = open

    def no_write(path, mode="r", *args, **kwargs):
        if "w" in mode and str(path) == str(workspace.dblib_path):
            raise PermissionError(13, "gesperrt")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", no_write)
    categories.update_category("Fuses", {"altium_enabled": True})
    with pytest.raises(DbLibError, match="kann nicht geschrieben werden"):
        ensure_dblib(workspace)


# --------------------------------------------------------------------------- status


def test_status_missing_then_ok(workspace):
    status = status_model(workspace)
    assert not status.exists and not status.up_to_date and not status.db_path_ok
    assert "missing" in {i.code for i in status.issues}
    assert status.file_name == "PartForge.DbLib" and status.db_kind == "sqlite"
    assert status.installed_in_altium is None and status.install is None
    write_dblib(workspace)
    status = status_model(workspace)
    assert status.exists and status.up_to_date and status.db_path_ok
    assert status.issues == []
    assert status.tables > status.field_maps // 100 and status.enabled_tables[0] == "Resistors"
    assert status.dblib_database == str(workspace.sqlite_path) and status.size and status.modified
    as_dict = dblib_status(workspace)
    assert as_dict["up_to_date"] is True and as_dict["issues"] == [] and as_dict["path"] == str(workspace.dblib_path)


def test_status_outdated_moved_and_format(workspace):
    write_dblib(workspace)
    categories.add_field("Diodes", FieldDef(column="Vf", label="Vf", show_on_schematic=True))
    assert "outdated" in codes(workspace) and not status_model(workspace).up_to_date
    write_dblib(workspace)
    raw = workspace.dblib_path.read_bytes().replace(str(workspace.sqlite_path).encode("cp1252"), rb"E:\Weg\PartForge.sqlite")
    workspace.dblib_path.write_bytes(raw)
    status = status_model(workspace)
    assert not status.db_path_ok and status.dblib_database == r"E:\Weg\PartForge.sqlite"
    assert "db_path" in {i.code for i in status.issues} and "outdated" not in {i.code for i in status.issues}
    write_dblib(workspace)
    workspace.dblib_path.write_bytes(b"\xef\xbb\xbf" + workspace.dblib_path.read_bytes())
    assert codes(workspace) == {"format"}


def test_status_other_dblibs_network_and_wal(workspace, monkeypatch):
    write_dblib(workspace)
    (workspace.root / "Alt.DbLib").write_text("x")
    assert "other_dblibs" in codes(workspace)
    monkeypatch.setattr("partforge.db.core.is_network_path", lambda path: True)
    monkeypatch.setattr("partforge.db.core.file_journal_mode", lambda path: "rollback")
    found = codes(workspace)
    assert {"network", "wal"} <= found


def test_status_without_open_database(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Zu")
    status = status_model(ws)
    assert "build" in {i.code for i in status.issues} and not status.up_to_date


def test_status_reports_cached_install_state(workspace):
    write_dblib(workspace)
    other = r"D:\Alt\PartForge.DbLib"
    state = DbLibInstallState(
        path=str(workspace.dblib_path),
        file_name="PartForge.DbLib",
        installed=True,
        position=4,
        same_name=[
            InstalledDbLib(index=2, path=other),
            InstalledDbLib(index=4, path=str(workspace.dblib_path), same_file=True, document_open=True, document_shown=True),
        ],
        duplicates=[other],
        first_match=other,
        resolves_to_this=False,
    )
    remember_install_state(state, dblib=workspace.dblib_path)
    status = status_model(workspace)
    assert status.installed_in_altium is True and status.install is not None
    found = {i.code: i for i in status.issues}
    assert found["duplicates"].severity == "error" and other in found["duplicates"].message
    assert "open_in_editor" in found
    remember_install_state(state.model_copy(update={"installed": False, "duplicates": [], "same_name": []}),
                           dblib=workspace.dblib_path)
    assert status_model(workspace).installed_in_altium is False
    assert "not_installed" in codes(workspace)


def test_status_hints_at_installation_from_old_folder(workspace, tmp_path: Path):
    write_dblib(workspace)
    old = tmp_path / "Alt" / "PartForge.DbLib"
    remember_install_state(DbLibInstallState(path=str(old), file_name="PartForge.DbLib", installed=True), dblib=old)
    issue = next(i for i in status_model(workspace).issues if i.code == "moved_install")
    assert str(old) in issue.message and status_model(workspace).installed_in_altium is None
    # no promise: it may as well be the DbLib of another library with the default file name
    assert "anderen Bibliothek" in issue.message and "eigenen DbLib-Dateinamen" in issue.message


# --------------------------------------------------------------------------- same-name DbLibs


def _missing_drive() -> str:
    for letter in "ZYXWVUTSRQPONMLKJIHG":
        if not Path(f"{letter}:\\").exists():
            return f"{letter}:\\"
    pytest.skip("kein freier Laufwerksbuchstabe")


def _dblib_text(odbc: str) -> bytes:
    return (
        "[OutputDatabaseLinkFile]\r\nVersion=1.1\r\n[DatabaseLinks]\r\n"
        f'ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="{odbc}"\r\n'
    ).encode("cp1252")


def test_classify_duplicate_sqlite(workspace, tmp_path: Path):
    write_dblib(workspace)
    old = tmp_path / "Alt" / "PartForge.DbLib"
    old.parent.mkdir()
    old.write_bytes(workspace.dblib_path.read_bytes())  # old folder / copy: same database
    same = classify_duplicate(workspace, old)
    assert same.kind == "same_database" and same.replaceable and same.database == str(workspace.sqlite_path)
    foreign_ws = Workspace.create(tmp_path / "Andere Bibliothek")
    foreign = foreign_ws.dblib_path
    foreign.write_bytes(_dblib_text(f"DRIVER=SQLite3 ODBC Driver;Database={foreign_ws.sqlite_path};NoCreat=1;"))
    other = classify_duplicate(workspace, foreign)
    assert other.kind == "other_database" and not other.replaceable and other.database == str(foreign_ws.sqlite_path)
    gone = classify_duplicate(workspace, tmp_path / "Verschoben" / "PartForge.DbLib")
    assert gone.kind == "missing" and gone.replaceable  # drive there, file gone: dead entry
    offline = classify_duplicate(workspace, _missing_drive() + "Team\\PartForge.DbLib")
    assert offline.kind == "unreachable" and not offline.replaceable  # could be another library
    broken = tmp_path / "Kaputt" / "PartForge.DbLib"
    broken.parent.mkdir()
    broken.write_bytes(b"\x00kein ini")
    assert classify_duplicate(workspace, broken).kind == "unreadable"
    pg = tmp_path / "PG" / "PartForge.DbLib"
    pg.parent.mkdir()
    pg.write_bytes(_dblib_text("DRIVER={PostgreSQL Unicode(x64)};SERVER=db;DATABASE=parts;PWD=geheim;"))
    remote = classify_duplicate(workspace, pg)
    assert remote.kind == "other_database" and remote.database == "db/parts"


def test_classify_duplicate_postgres(tmp_path: Path):
    ws = Workspace.create(tmp_path / "PG")
    ws.settings.db.kind = "postgres"
    ws.settings.db.postgres_odbc = "SERVER=db.local;PORT=5432;DATABASE=parts;UID=altium;PWD=geheim"
    same = tmp_path / "A" / "PartForge.DbLib"
    same.parent.mkdir()
    same.write_bytes(_dblib_text("DRIVER={PostgreSQL Unicode(x64)};SERVER=DB.local;DATABASE=Parts;UID=lesen;PWD=x;"))
    found = classify_duplicate(ws, same)
    assert found.kind == "same_database" and "geheim" not in (found.database or "") and "x;" not in (found.database or "")
    other = tmp_path / "B" / "PartForge.DbLib"
    other.parent.mkdir()
    other.write_bytes(_dblib_text("DRIVER={PostgreSQL Unicode(x64)};SERVER=db.local;PORT=5433;DATABASE=parts;"))
    assert classify_duplicate(ws, other).kind == "other_database"  # another server instance
    lite = tmp_path / "C" / "PartForge.DbLib"
    lite.parent.mkdir()
    lite.write_bytes(_dblib_text(f"DRIVER=SQLite3 ODBC Driver;Database={tmp_path / 'x.sqlite'};NoCreat=1;"))
    assert classify_duplicate(ws, lite).kind == "other_database"


def test_duplicate_messages_follow_the_classification(workspace, tmp_path: Path):
    write_dblib(workspace)
    old = tmp_path / "Alt" / "PartForge.DbLib"
    old.parent.mkdir()
    old.write_bytes(workspace.dblib_path.read_bytes())
    dead = tmp_path / "Weg" / "PartForge.DbLib"
    state = DbLibInstallState(path=str(workspace.dblib_path), file_name="PartForge.DbLib", installed=False,
                              duplicates=[str(old), str(dead)], first_match=str(old))
    classified, duplicates = classify_install_state(workspace, state)
    assert classified.duplicate_kinds == {str(old): "same_database", str(dead): "missing"}
    assert state.duplicate_kinds == {}  # the original is not modified
    message = duplicates_message(classified, duplicates)
    assert "nicht installiert, aber andere DbLibs" in message and "Ersetzen" in message
    assert "Datenbank dieser Bibliothek" in message and "existiert nicht mehr" in message
    remember_install_state(classified, dblib=workspace.dblib_path)
    issue = next(i for i in status_model(workspace).issues if i.code == "duplicates")
    assert issue.message == duplicates_message(classified)  # status: cached kinds, no file access
    assert "Ersetzen" in issue.message and issue.severity == "error"

    foreign_ws = Workspace.create(tmp_path / "Andere")
    foreign_ws.dblib_path.write_bytes(
        _dblib_text(f"DRIVER=SQLite3 ODBC Driver;Database={foreign_ws.sqlite_path};NoCreat=1;"))
    mine = InstalledDbLib(index=1, path=str(workspace.dblib_path), same_file=True)
    state = DbLibInstallState(path=str(workspace.dblib_path), file_name="PartForge.DbLib", installed=True,
                              duplicates=[str(foreign_ws.dblib_path)], first_match=str(foreign_ws.dblib_path),
                              same_name=[InstalledDbLib(index=0, path=str(foreign_ws.dblib_path)), mine])
    classified, duplicates = classify_install_state(workspace, state)
    message = duplicates_message(classified, duplicates)
    assert message.startswith("Neben dieser DbLib ist in Altium eine weitere DbLib")
    assert "anderen Bibliothek" in message and "ersetzt sie deshalb nicht" in message
    assert "Altium verwendet derzeit" in message and str(foreign_ws.sqlite_path) in message
    unknown = duplicates_message(state)  # never classified
    assert "ließ sich nicht prüfen" in unknown


def test_duplicate_advice_grammar():
    assert duplicate_advice("X.DbLib", ["same_database"]).startswith("Sie gehört zu dieser Bibliothek")
    assert duplicate_advice("X.DbLib", ["missing", "same_database"]).startswith("Sie gehören")
    assert duplicate_advice("X.DbLib", ["missing", "other_database"]).startswith("Mindestens eine davon")
    assert duplicate_advice("X.DbLib", ["unreachable", "unreadable"]).startswith("Ob diese")
    assert "X.DbLib" in duplicate_advice("X.DbLib", [None])


# --------------------------------------------------------------------------- install cache


def test_install_cache(tmp_path: Path):
    lib = tmp_path / "Bib" / "PartForge.DbLib"
    assert cached_install_state(lib) is None
    remember_install_state(DbLibInstallState(path=str(lib), file_name="PartForge.DbLib", installed=True))
    assert cached_install_state(Path(str(lib).upper())).installed  # type: ignore[union-attr]
    assert [s.path for s in cached_install_states()] == [str(lib)]
    forget_install_state(lib)
    assert cached_install_state(lib) is None
    dblib._cache_path().write_text("{kaputt", encoding="utf-8")
    assert cached_install_state(lib) is None and cached_install_states() == []
    dblib._cache_path().write_text('{"x": {"installed": "vielleicht"}}', encoding="utf-8")
    assert cached_install_states() == []


# --------------------------------------------------------------------------- automatic regeneration


def test_auto_writer_rewrites_after_schema_change(workspace):
    written: list[str] = []
    writer = DbLibAutoWriter(on_written=lambda ws, result: written.append(result.reason))
    writer.start()
    writer.start()  # idempotent
    try:
        categories.add_field("Resistors", FieldDef(column="Prozess", label="Prozess", show_on_schematic=True))
        assert workspace.dblib_path.is_file()
        assert "FieldNameOnly=Prozess" in text_of(workspace.dblib_path)
        assert written == ["missing"]
        events.emit(events.SCHEMA_CHANGED)  # nothing changed -> no rewrite
        assert written == ["missing"] and writer.last_result is not None and not writer.last_result.written
    finally:
        writer.stop()
    categories.add_field("Resistors", FieldDef(column="Nachher", label="Nachher"))
    assert written == ["missing"] and not writer.running


def test_auto_writer_on_workspace_opened(workspace):
    writer = DbLibAutoWriter()
    writer.start()
    try:
        write_dblib(workspace)
        raw = workspace.dblib_path.read_bytes().replace(
            str(workspace.sqlite_path).encode("cp1252"), rb"X:\Verschoben\PartForge.sqlite"
        )
        workspace.dblib_path.write_bytes(raw)
        events.emit(events.WORKSPACE_OPENED, workspace)
        assert status_model(workspace).db_path_ok
        assert writer.last_result is not None and writer.last_result.reason == "db_moved"
    finally:
        writer.stop()


def test_auto_writer_never_raises_and_skips_foreign_workspaces(workspace, tmp_path: Path):
    other = Workspace.create(tmp_path / "Andere")
    writer = DbLibAutoWriter(workspace_provider=lambda: other)
    assert writer.ensure(other) is None  # the open database belongs to another library
    assert not other.dblib_path.exists()
    workspace.settings.dblib_file = "kaputt.txt"
    writer = DbLibAutoWriter(workspace_provider=lambda: workspace,
                             on_written=lambda ws, result: (_ for _ in ()).throw(RuntimeError("Folgefehler")))
    assert writer.ensure(workspace, reason="Test") is None
    assert writer.last_error and ".DbLib" in writer.last_error
    workspace.settings.dblib_file = "PartForge.DbLib"
    result = writer.ensure(workspace)  # on_written fails: logged, result still returned
    assert result is not None and result.written


def test_auto_writer_ignores_reentrant_notifications(workspace):
    calls: list[str] = []
    writer = DbLibAutoWriter()

    def nested(ws, result):
        calls.append("outer")
        assert writer.ensure(ws) is None  # re-entrant call from the same thread is ignored

    writer = DbLibAutoWriter(on_written=nested)
    writer.ensure(workspace)
    assert calls == ["outer"]


def test_render_ignores_existing_corrupt_file(workspace):
    workspace.dblib_path.write_bytes(b"\x00kaputt")
    text = render_dblib(workspace)
    assert "LastFocusedTable=Resistors" in text
    result = ensure_dblib(workspace)
    assert result.written and result.reason == "outdated"
    assert os.path.getsize(workspace.dblib_path) > 1000
