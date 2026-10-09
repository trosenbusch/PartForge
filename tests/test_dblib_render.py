"""DbLib rendering: golden text (exact lines and order), field-map rules, connection strings,
encoding, determinism and preservation of Altium's UI state."""
from __future__ import annotations

from pathlib import Path

import pytest

from partforge.altium import dblib
from partforge.altium.dblib import (
    DbLibError,
    DbLibPathError,
    DbLibUiState,
    build_dblib,
    connection_string,
    encode_dblib,
    field_map_for,
    mask_secrets,
    name_problem,
    odbc_connection_string,
    parse_connection_string,
    render_dblib,
    reserved_parameter,
    sqlite_path_problem,
)
from partforge.db.models import CategoryDef, FieldDef
from partforge.workspace import Workspace


def F(column: str, **kw) -> FieldDef:
    return FieldDef(column=column, label=kw.pop("label", column), **kw)


LINKS = dict(system=True, add_to_design=False)


def categories() -> list[CategoryDef]:
    resistors = CategoryDef(
        table="Resistors",
        label="Widerstände",
        sort_order=10,
        fields=[
            F("Part Number", required=True),
            F("Manufacturer"),
            F("Value"),
            F("Description"),
            F("Comment"),
            F("Library Ref", **LINKS),
            F("Library Path", kind="path", **LINKS),
            F("Footprint Ref", **LINKS),
            F("Footprint Path", kind="path", **LINKS),
            F("Footprint Ref 2", **LINKS),
            F("Footprint Path 2", kind="path", **LINKS),
            F("ComponentLink1URL", kind="url", system=True),
            F("Resistance", kind="quantity", unit="Ω", show_on_schematic=True),
            F("Notes", add_to_design=False),
        ],
    )
    capacitors = CategoryDef(
        table="Capacitors",
        label="Kondensatoren",
        sort_order=20,
        altium_enabled=False,
        fields=[F("Part Number"), F("Library Ref", **LINKS), F("Capacitance", show_on_schematic=True)],
    )
    connectors = CategoryDef(
        table="Connectors",
        label="Steckverbinder",
        sort_order=30,
        fields=[F("Library Ref", **LINKS), F("Part Number"), F("Footprint Ref 3", **LINKS), F("Pins", kind="int")],
    )
    return [resistors, capacitors, connectors]


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace.create(tmp_path / "Bibliothek", name="Golden")


def golden_sqlite(db: str) -> list[str]:
    def opt(table: str, column: str, ftype: int, param: str, visible: bool = False, add: int = 0) -> str:
        return (f"Options=FieldName={table}.{column}|TableNameOnly={table}|FieldNameOnly={column}|FieldType={ftype}"
                f"|ParameterName={param}|VisibleOnAdd={visible}|AddMode={add}|RemoveMode=0|UpdateMode=0")

    return [
        "[OutputDatabaseLinkFile]",
        "Version=1.1",
        "[DatabaseLinks]",
        f'ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3 ODBC '
        f'Driver;Database={db};NoCreat=1;"',
        "AddMode=3",
        "RemoveMode=1",
        "UpdateMode=2",
        "ViewMode=0",
        "LeftQuote=[",
        "RightQuote=]",
        "QuoteTableNames=1",
        "UseTableSchemaName=0",
        "DefaultColumnType=TEXT",
        "LibraryDatabaseType=",
        f"LibraryDatabasePath={db}",
        "DatabasePathRelative=0",
        "TopPanelCollapsed=0",
        "LibrarySearchPath=",
        "OrcadMultiValueDelimiter=,",
        "SearchSubDirectories=0",
        "SchemaName=",
        "LastFocusedTable=Resistors",
        "[Table1]",
        "SchemaName=",
        "TableName=Resistors",
        "Enabled=True",
        "UserWhere=0",
        "UserWhereText=[Part Number] = '{Part Number}'",
        "[Table2]",
        "SchemaName=",
        "TableName=Capacitors",
        "Enabled=False",
        "UserWhere=0",
        "UserWhereText=[Part Number] = '{Part Number}'",
        "[Table3]",
        "SchemaName=",
        "TableName=Connectors",
        "Enabled=True",
        "UserWhere=0",
        "UserWhereText=[Part Number] = '{Part Number}'",
        "[Table4]",
        "SchemaName=",
        "TableName=pf_categories",
        "Enabled=False",
        "UserWhere=0",
        "UserWhereText=",
        "[Table5]",
        "SchemaName=",
        "TableName=pf_meta",
        "Enabled=False",
        "UserWhere=0",
        "UserWhereText=",
        "[FieldMap1]",
        opt("Resistors", "Part Number", 0, "Part Number"),
        "[FieldMap2]",
        opt("Resistors", "Description", 1, "[Description]"),
        "[FieldMap3]",
        opt("Resistors", "Library Ref", 1, "[Library Ref]"),
        "[FieldMap4]",
        opt("Resistors", "Library Path", 1, "[Library Path]"),
        "[FieldMap5]",
        opt("Resistors", "Footprint Ref", 1, "[Footprint Ref]"),
        "[FieldMap6]",
        opt("Resistors", "Footprint Path", 1, "[Footprint Path]"),
        "[FieldMap7]",
        opt("Resistors", "Footprint Ref 2", 1, "[Footprint Ref 2]"),
        "[FieldMap8]",
        opt("Resistors", "Footprint Path 2", 1, "[Footprint Path 2]"),
        "[FieldMap9]",
        opt("Resistors", "Resistance", 1, "Resistance", visible=True),
        "[FieldMap10]",
        opt("Resistors", "Notes", 1, "Notes", add=1),
        "[FieldMap11]",
        opt("Connectors", "Part Number", 0, "Part Number"),
        "[FieldMap12]",
        opt("Connectors", "Library Ref", 1, "[Library Ref]"),
        "[FieldMap13]",
        opt("Connectors", "Footprint Ref 3", 1, "[Footprint Ref 3]"),
    ]


def test_golden_sqlite_dblib(ws: Workspace):
    db = str(ws.sqlite_path)
    build = build_dblib(ws, categories(), other_tables=["pf_categories", "pf_meta"], ui_state=DbLibUiState())
    assert build.text.split("\r\n")[:-1] == golden_sqlite(db)
    assert build.text.endswith("\r\n") and "\n" not in build.text.replace("\r\n", "")
    assert build.warnings == []
    assert build.database == db
    assert [t.name for t in build.tables if t.enabled] == ["Resistors", "Connectors"]
    assert len(build.field_maps) == 13


def test_golden_postgres_dblib(ws: Workspace):
    ws.settings.db.kind = "postgres"
    ws.settings.db.postgres_odbc = "DRIVER={PostgreSQL Unicode(x64)};SERVER=db.local;PORT=5432;DATABASE=parts;UID=altium;PWD=geheim"
    text = build_dblib(ws, categories()[:1], other_tables=[], ui_state=DbLibUiState()).text
    lines = text.split("\r\n")
    assert lines[3] == (
        'ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER={PostgreSQL '
        'Unicode(x64)};SERVER=db.local;PORT=5432;DATABASE=parts;UID=altium;PWD=geheim;"'
    )
    assert 'LeftQuote="' in lines and 'RightQuote="' in lines
    assert "LibraryDatabasePath=" in lines and "DatabasePathRelative=0" in lines
    assert "UserWhereText=\"Part Number\" = '{Part Number}'" in lines
    assert "[" not in "".join(line for line in lines if line.startswith("UserWhereText"))


def test_postgres_connection_variants(ws: Workspace):
    ws.settings.db.kind = "postgres"
    ws.settings.db.postgres_odbc = "SERVER=srv;DATABASE=parts"
    assert odbc_connection_string(ws) == "DRIVER={PostgreSQL Unicode(x64)};SERVER=srv;DATABASE=parts;"
    ws.settings.db.postgres_odbc = None
    ws.settings.db.postgres_url = "postgresql+psycopg://altium:p;w@db.local:5433/parts"
    assert odbc_connection_string(ws) == (
        "DRIVER={PostgreSQL Unicode(x64)};SERVER=db.local;PORT=5433;DATABASE=parts;UID=altium;PWD={p;w};"
    )
    assert 'PWD={p;w};"' in connection_string(ws)
    ws.settings.db.postgres_url = None
    with pytest.raises(DbLibError, match="ODBC"):
        connection_string(ws)


def test_sqlite_connection_string_is_the_verified_one(ws: Workspace):
    text = connection_string(ws)
    assert text == (
        'Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3 ODBC Driver;'
        f'Database={ws.sqlite_path};NoCreat=1;"'
    )
    assert "LongNames" not in text and Path(str(ws.sqlite_path)).is_absolute()


@pytest.mark.parametrize("folder", ["Bib;Alt", "Bib{x}", "Bib Ω Test", "Bib}y"])
def test_database_path_with_special_characters_is_refused(tmp_path: Path, folder: str):
    """Never an 8.3 alias (own -wal/-shm for Altium), never a path the DbLib cannot carry."""
    ws = Workspace.create(tmp_path / folder)
    with pytest.raises(DbLibPathError, match="Ordner ohne Sonderzeichen") as exc:
        connection_string(ws)
    assert folder in str(exc.value) and "~" not in str(exc.value)
    with pytest.raises(DbLibPathError):
        odbc_connection_string(ws)
    with pytest.raises(DbLibPathError):
        build_dblib(ws, categories(), other_tables=[], ui_state=DbLibUiState())
    assert not ws.dblib_path.exists()


def test_database_file_name_with_special_characters_is_refused(ws: Workspace):
    ws.settings.db.sqlite_file = "Ω-Daten.sqlite"
    with pytest.raises(DbLibPathError, match="Windows-1252"):
        connection_string(ws)


@pytest.mark.parametrize(
    ("path", "problem"),
    [
        (r"C:\Bib\PartForge.sqlite", None),
        (r"C:\Bibliothek Ä Ö Ü ß €\PartForge.sqlite", None),  # cp1252 is fine
        (r"C:\Bib=1\it's\PartForge.sqlite", None),
        (r"C:\Bib;Alt\PartForge.sqlite", "die Zeichen ;"),
        (r'C:\Bib"\PartForge.sqlite', 'die Zeichen "'),
        (r"C:\Bib{1}\PartForge.sqlite", "die Zeichen { }"),
        ("C:\\Bib\nNeu\\PartForge.sqlite", "Steuerzeichen"),
        (r"C:\Bib Ω\PartForge.sqlite", "Zeichen außerhalb von Windows-1252 (Ω)"),
    ],
)
def test_sqlite_path_problem(path: str, problem: str | None):
    assert sqlite_path_problem(path) == problem


def test_postgres_connection_with_line_break_is_refused(ws: Workspace):
    ws.settings.db.kind = "postgres"
    ws.settings.db.postgres_odbc = "SERVER=srv;DATABASE=parts\r\n[Table1]\r\nTableName=Hijack"
    with pytest.raises(DbLibError, match="Steuerzeichen"):
        connection_string(ws)
    with pytest.raises(DbLibError, match="Steuerzeichen"):
        build_dblib(ws, categories()[:1], other_tables=[], ui_state=DbLibUiState())


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("Resistors", None),
        ("Bauteile Übersicht", None),
        ("pf_meta", None),
        ("Bad|Name", "die Zeichen |"),
        ("Evil\r\n[Table1]", "Steuerzeichen (z. B. Zeilenumbrüche)"),
        ("Tab\there", "Steuerzeichen (z. B. Zeilenumbrüche)"),
        ("[Bracket]", "die Zeichen [ ]"),
        ('Quote"d', 'die Zeichen "'),
        (" Leading", "Leerzeichen am Anfang oder Ende"),
        ("Trailing ", "Leerzeichen am Anfang oder Ende"),
        ("   ", "einen leeren Namen"),
        ("Tabelle 電", "Zeichen außerhalb von Windows-1252 (電)"),
        ("Zero\u200bWidth", "Steuerzeichen (z. B. Zeilenumbrüche)"),
    ],
)
def test_name_problem(name: str, problem: str | None):
    assert name_problem(name) == problem


def test_unsafe_category_and_column_names_are_left_out(ws: Workspace):
    good = categories()[0]
    pipe = CategoryDef(table="Bad|Name", label="Kaputt", fields=[F("Part Number"), F("Library Ref", **LINKS)])
    injected = CategoryDef(table="Evil\r\n[Table1]\r\nTableName=Hijack", label="Böse", altium_enabled=False,
                           fields=[F("Part Number")])
    columns = CategoryDef(table="Columns", label="Spalten", fields=[
        F("Part Number"), F("Library Ref", **LINKS), F("Bad|Col", show_on_schematic=True),
        F("Line\nBreak", add_to_design=False), F("Fine", show_on_schematic=True),
    ])
    build = build_dblib(ws, [good, pipe, injected, columns],
                        other_tables=["pf_meta", "View]x", "Ok View"], ui_state=DbLibUiState())
    info = dblib.parse_dblib(build.text)
    assert [t.name for t in info.tables] == ["Resistors", "Columns", "pf_meta", "Ok View"]
    assert {m.column for m in info.field_maps if m.table == "Columns"} == {"Part Number", "Library Ref", "Fine"}
    assert "Hijack" not in build.text and "Bad|" not in build.text and "View]x" not in build.text
    assert info.warnings == []  # nothing injected
    assert build.skipped == ["Bad|Name", "Evil\r\n[Table1]\r\nTableName=Hijack", "View]x", "Columns.Bad|Col",
                             "Columns.Line\nBreak"]
    by_message = {i.message: i for i in build.issues}
    assert all(i.code == "unsafe_name" for i in build.issues)
    pipe_issue = next(i for m, i in by_message.items() if "Bad|Name" in m)
    assert pipe_issue.severity == "error" and "umbenennen" in pipe_issue.message  # enabled category: lost for Altium
    evil = next(i for m, i in by_message.items() if "Evil" in m)
    assert evil.severity == "warning" and "\\r\\n" in evil.message and "\r" not in evil.message
    assert any("Bad|Col" in w and "Columns" in w for w in build.warnings)
    assert all(line.count("|") == 8 for line in build.text.split("\r\n") if line.startswith("Options="))


def test_field_map_rules():
    assert field_map_for("T", F("Part Number")).field_type == 0  # type: ignore[union-attr]
    assert field_map_for("T", F("Value")) is None  # same-name parameter: Altium default
    assert field_map_for("T", F("Footprint Ref 1")) is None  # n starts at 2 (dblib-format.md §7)
    visible = field_map_for("T", F("Capacitance", show_on_schematic=True))
    assert visible is not None and visible.visible_on_add and visible.add_mode == 0
    hidden = field_map_for("T", F("PF Status", add_to_design=False, show_on_schematic=True))
    assert hidden is not None and hidden.add_mode == 1 and hidden.visible_on_add
    reserved = field_map_for("T", F("Footprint Path 12", add_to_design=False, show_on_schematic=True))
    assert reserved is not None and reserved.parameter_name == "[Footprint Path 12]"
    assert reserved.add_mode == 0 and not reserved.visible_on_add  # Altium ignores modes for bracket mappings
    assert reserved_parameter("library ref") == "[Library Ref]"
    assert reserved_parameter("Description") == "[Description]"
    assert reserved_parameter("Footprint  Ref 2") == "[Footprint Ref 2]"
    assert reserved_parameter("Comment") is None


def test_render_is_deterministic_and_deduplicated(ws: Workspace):
    cats = categories()
    first = build_dblib(ws, [*cats, cats[0]], other_tables=["pf_meta", "pf_meta", "resistors"], ui_state=DbLibUiState())
    second = build_dblib(ws, cats, other_tables=["pf_meta"], ui_state=DbLibUiState())
    assert first.text == second.text
    assert sum(1 for t in first.tables if t.name.casefold() == "resistors") == 1


def test_key_column_comes_first_and_every_table_is_numbered(ws: Workspace):
    text = build_dblib(ws, categories(), other_tables=[], ui_state=DbLibUiState()).text
    sections = [line for line in text.split("\r\n") if line.startswith("[")]
    tables = [s for s in sections if s.startswith("[Table")]
    maps = [s for s in sections if s.startswith("[FieldMap")]
    assert tables == [f"[Table{i}]" for i in range(1, 4)]
    assert maps == [f"[FieldMap{i}]" for i in range(1, len(maps) + 1)]
    connectors = [line for line in text.split("\r\n") if "TableNameOnly=Connectors" in line]
    assert "FieldType=0" in connectors[0]


def test_no_enabled_table_and_missing_key(ws: Workspace):
    cats = [CategoryDef(table="Misc", label="Sonstiges", fields=[F("Library Ref", **LINKS)])]
    build = build_dblib(ws, cats, other_tables=[], ui_state=DbLibUiState())
    assert any("Part Number" in w for w in build.warnings)
    disabled = [c.model_copy(update={"altium_enabled": False}) for c in categories()]
    text = build_dblib(ws, disabled, other_tables=[], ui_state=DbLibUiState()).text
    assert "LastFocusedTable=Resistors" in text and "[FieldMap" not in text


def test_non_cp1252_names_are_left_out_with_german_warning(ws: Workspace):
    build = build_dblib(ws, categories()[:1], other_tables=["Tabelle 電"], ui_state=DbLibUiState())
    assert any("Windows-1252" in w and "電" in w for w in build.warnings)
    assert build.skipped == ["Tabelle 電"] and b"Tabelle" not in encode_dblib(build.text)  # never written as "?"
    umlaut = build_dblib(ws, categories()[:1], other_tables=["Bauteile Übersicht"], ui_state=DbLibUiState())
    assert umlaut.warnings == [] and b"\xdcbersicht" in encode_dblib(umlaut.text)  # cp1252, no UTF-8


def test_non_cp1252_connection_text_gives_encoding_warning(ws: Workspace):
    ws.settings.db.kind = "postgres"
    ws.settings.db.postgres_odbc = "SERVER=srv;DATABASE=parts;PWD=Ωmega"
    build = build_dblib(ws, categories()[:1], other_tables=[], ui_state=DbLibUiState())
    assert [i.code for i in build.issues] == ["encoding"] and "Ω" in build.warnings[0]


def test_encoding_bytes(ws: Workspace):
    data = encode_dblib(build_dblib(ws, categories(), other_tables=[], ui_state=DbLibUiState()).text)
    assert not data.startswith(b"\xef\xbb\xbf") and data.startswith(b"[OutputDatabaseLinkFile]\r\n")
    assert data.endswith(b"\r\n") and b"\n" not in data.replace(b"\r\n", b"")


def test_ui_state_is_preserved(ws: Workspace):
    state = DbLibUiState(
        links={"LastFocusedTable": "connectors", "TopPanelCollapsed": "1", "ViewMode": "1"},
        tables={
            "resistors": {
                "BrowserOrder_Visible": "Part Number0=134|Value0=80",
                "BrowserOrder_Sorting": "Value0=1",
                "BrowserOrder_Zoom": "2",
            },
            "gone": {"BrowserOrder_Sorting": "x"},
        },
    )
    lines = build_dblib(ws, categories(), other_tables=[], ui_state=state).text.split("\r\n")
    assert "LastFocusedTable=Connectors" in lines  # canonical spelling of an existing table
    assert "TopPanelCollapsed=1" in lines and "ViewMode=1" in lines
    i = lines.index("TableName=Resistors")
    assert lines[i + 4 : i + 7] == [
        "BrowserOrder_Sorting=Value0=1",
        "BrowserOrder_Visible=Part Number0=134|Value0=80",
        "BrowserOrder_Zoom=2",
    ]
    assert not any("BrowserOrder_Sorting=x" in line for line in lines)


def test_invalid_ui_state_falls_back(ws: Workspace):
    state = DbLibUiState(links={"LastFocusedTable": "Entfernt", "TopPanelCollapsed": "ja", "ViewMode": "7"})
    lines = build_dblib(ws, categories(), other_tables=[], ui_state=state).text.split("\r\n")
    assert "LastFocusedTable=Resistors" in lines and "TopPanelCollapsed=0" in lines and "ViewMode=0" in lines


def test_render_from_open_database(workspace):
    from partforge.db import categories as db_categories

    text = render_dblib(workspace)
    names = [line.split("=", 1)[1] for line in text.split("\r\n") if line.startswith("TableName=")]
    cats = db_categories.list_categories(with_counts=False)
    assert names[: len(cats)] == [c.table for c in sorted(cats, key=lambda c: (c.sort_order, c.label, c.table))]
    assert {n for n in names[len(cats):]} >= {"pf_meta", "pf_categories", "pf_fields", "pf_symbols", "pf_audit"}
    enabled = [line for line in text.split("\r\n") if line == "Enabled=True"]
    assert len(enabled) == len(cats)
    for cat in cats:
        assert f"FieldName={cat.table}.Library Ref|TableNameOnly={cat.table}|FieldNameOnly=Library Ref|FieldType=1|ParameterName=[Library Ref]" in text
    assert render_dblib(workspace) == text


def test_render_follows_category_changes(workspace):
    from partforge.db import categories as db_categories

    db_categories.update_category("Capacitors", {"altium_enabled": False})
    db_categories.add_field("Resistors", FieldDef(column="Gehaeuse Code", label="Code", show_on_schematic=True))
    text = render_dblib(workspace)
    lines = text.split("\r\n")
    assert lines[lines.index("TableName=Capacitors") + 1] == "Enabled=False"
    assert "TableNameOnly=Capacitors" not in text
    assert "FieldNameOnly=Gehaeuse Code|FieldType=1|ParameterName=Gehaeuse Code|VisibleOnAdd=True" in text


def test_render_without_open_database_fails(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Leer")
    with pytest.raises(DbLibError, match="nicht geöffnet"):
        render_dblib(ws)


def test_parse_connection_string_and_masking():
    outer, inner = parse_connection_string(
        'Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER={PostgreSQL Unicode(x64)};'
        'SERVER=s;PWD={a;b}};c};UID=""x"";"'
    )
    assert outer["provider"] == "MSDASQL.1"
    assert inner["driver"] == "PostgreSQL Unicode(x64)" and inner["pwd"] == "a;b};c"
    assert inner["uid"] == "x"  # outer "" -> inner quoted value
    _, plain = parse_connection_string("Driver={SQLite3 ODBC Driver};Database=C:\\x.sqlite")
    assert plain["database"] == "C:\\x.sqlite"
    assert parse_connection_string("") == ({}, {})
    assert mask_secrets("SERVER=s;PWD={a;b};UID=u") == "SERVER=s;PWD=***;UID=u"
    assert mask_secrets("Password=geheim;x=1") == "Password=***;x=1"
