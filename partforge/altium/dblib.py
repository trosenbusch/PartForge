"""Altium database library file (``PartForge.DbLib``): render, write, read, status.

Format reference: ``docs/entwicklung/recherche/dblib-format.md`` (INI sections, writer
key order and mode codes from WorkspaceManager.dll). VERIFIED in Altium 26.10
(``altium-verify-2.md`` §4/§6.2, ``altium-refresh.md``):

* SQLite: ``Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3
  ODBC Driver;Database=<ABSOLUTE path>;NoCreat=1;"`` plus ``LibraryDatabasePath=<absolute>``
  and ``DatabasePathRelative=0``. The ODBC driver resolves a relative database path against
  Altium's working directory, so the path is absolute and the file is rewritten when the
  library folder moves. ``LongNames=1`` breaks every lookup and is never written.
* The database path is written **exactly as PartForge opens the database** – never as an
  8.3 alias: SQLite derives the ``-wal``/``-shm`` names from the spelling it is given, so a
  second name for the same file would give Altium its own WAL index (stale data, SQLite's
  "multiple names" corruption hazard). A path that cannot travel through the DbLib
  unchanged (``;`` ``{`` ``}`` ``"``, control characters, characters outside Windows-1252)
  is refused with :class:`DbLibPathError` ("Ordner ohne Sonderzeichen").
* PostgreSQL: ``DRIVER={PostgreSQL Unicode(x64)}`` (``ws.settings.db.postgres_odbc``) with
  ``"`` as quote characters (``[Resistors]`` is a syntax error there).
* cp1252, CRLF, no BOM; ``[TableN]``/``[FieldMapN]`` numbered contiguously from 1.
* Every category table is listed (``Enabled`` = ``altium_enabled``); every other table or
  view of the database (``pf_*`` metadata) is listed with ``Enabled=False``. Table and
  column names Altium's INI/``Options=`` syntax cannot carry (``|``, ``[``, ``]``, ``"``,
  control characters, blanks at either end, characters outside Windows-1252) are left
  out with a German warning (status issue ``unsafe_name``) – free text never reaches the
  file unescaped.
* Field maps: the key ``Part Number`` (FieldType 0), the reserved bracket mappings
  (``[Library Ref]`` …) and every non-default mapping – ``VisibleOnAdd=True`` for
  ``show_on_schematic``, ``AddMode=1`` ("Do not add") for ``add_to_design=False``.
  Ordinary same-name parameters are implicit (Altium maps them automatically).
* Altium's UI state (``LastFocusedTable``, ``TopPanelCollapsed``, ``ViewMode``,
  ``BrowserOrder_*``) is taken over from an existing file and ignored when comparing.
* Placed parts reference the DbLib by **file name only**: ``ws.settings.dblib_file`` must
  stay stable, and only one installed DbLib may carry that name. Another installed DbLib
  of the same name is classified (:func:`classify_duplicate`) before PartForge offers to
  replace it: only an old copy of *this* library (same database) or a dead entry (file
  gone) may be replaced – never the DbLib of another library.

Public API::

    connection_string(ws) -> str; odbc_connection_string(ws) -> str
    render_dblib(ws, categories=None) -> str; write_dblib(ws) -> Path; ensure_dblib(ws) -> DbLibWriteResult
    dblib_bytes(ws, which="target"|"file") -> bytes                 (exact file bytes, for downloads)
    read_dblib(path) -> DbLibInfo; dblib_status(ws) -> dict; status_model(ws) -> DbLibStatus
    cached_install_state(path) / remember_install_state(state)       (Altium install cache)
    classify_duplicate(ws, path) / classify_install_state(ws, state)  (same-name DbLibs in Altium)
    DbLibAutoWriter                                                   (rewrite on schema change / open)
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, ValidationError

from .. import events
from ..config import app_data_dir, local_data_dir
from ..db.models import CategoryDef, FieldDef
from ..workspace import Workspace, current_or_none
from .bridge.core import DbLibInstallState

log = logging.getLogger(__name__)

__all__ = [
    "DBLIB_VERSION",
    "POSTGRES_ODBC_DRIVER",
    "REASON_TEXTS",
    "REGENERATE_REASONS",
    "REPLACEABLE_DUPLICATES",
    "SQLITE_ODBC_DRIVER",
    "DbLibAutoWriter",
    "DbLibBuild",
    "DbLibCause",
    "DbLibDuplicate",
    "DbLibError",
    "DbLibFieldMap",
    "DbLibInfo",
    "DbLibIssue",
    "DbLibPathError",
    "DbLibStatus",
    "DbLibTable",
    "DbLibUiState",
    "DbLibWriteResult",
    "RegenerateReason",
    "build_dblib",
    "cached_install_state",
    "cached_install_states",
    "classify_duplicate",
    "classify_install_state",
    "connection_string",
    "database_matches",
    "dblib_bytes",
    "dblib_cause",
    "dblib_status",
    "duplicate_advice",
    "duplicates_message",
    "encode_dblib",
    "ensure_dblib",
    "field_map_for",
    "forget_install_state",
    "mask_secrets",
    "name_problem",
    "odbc_connection_string",
    "parse_connection_string",
    "parse_dblib",
    "read_dblib",
    "remember_install_state",
    "render_dblib",
    "reserved_parameter",
    "same_database_file",
    "same_path",
    "sqlite_path_problem",
    "status_model",
    "write_dblib",
]

DBLIB_VERSION: Final = "1.1"
SQLITE_ODBC_DRIVER: Final = "SQLite3 ODBC Driver"
POSTGRES_ODBC_DRIVER: Final = "PostgreSQL Unicode(x64)"
PROVIDER: Final = "Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="
ENCODING: Final = "cp1252"
KEY_COLUMN: Final = "Part Number"
DEFAULT_COLUMN_TYPE: Final = "TEXT"  # Altium's own ALTER TABLE (Edit Supplier Links); VARCHAR(n) truncates

# Codes VERIFIED from WorkspaceManager.dll (dblib-format.md §3.1)
FIELD_TYPE_KEY: Final = 0
FIELD_TYPE_NORMAL: Final = 1
ADD_MODE_DEFAULT: Final = 0
ADD_MODE_DO_NOT_ADD: Final = 1
GLOBAL_ADD_MODE: Final = 3  # Add only if not blank in database
GLOBAL_REMOVE_MODE: Final = 1  # Do not remove
GLOBAL_UPDATE_MODE: Final = 2  # Update

#: ``[DatabaseLinks]`` keys in the order of Altium's writer (string table of AD 26).
LINK_KEYS: Final = (
    "ConnectionString",
    "AddMode",
    "RemoveMode",
    "UpdateMode",
    "ViewMode",
    "LeftQuote",
    "RightQuote",
    "QuoteTableNames",
    "UseTableSchemaName",
    "DefaultColumnType",
    "LibraryDatabaseType",
    "LibraryDatabasePath",
    "DatabasePathRelative",
    "TopPanelCollapsed",
    "LibrarySearchPath",
    "OrcadMultiValueDelimiter",
    "SearchSubDirectories",
    "SchemaName",
    "LastFocusedTable",
)
#: Altium's editor state in ``[DatabaseLinks]`` – preserved, ignored when comparing.
LINK_UI_KEYS: Final = frozenset({"LastFocusedTable", "TopPanelCollapsed", "ViewMode"})
#: Table Browser layout in ``[TableN]`` (``BrowserOrder_*``) – preserved, ignored when comparing.
TABLE_UI_PREFIX: Final = "BrowserOrder_"
TABLE_UI_ORDER: Final = ("BrowserOrder_Sorting", "BrowserOrder_Grouping", "BrowserOrder_Visible")
TABLE_KEYS: Final = ("SchemaName", "TableName", "Enabled", "UserWhere", "UserWhereText")

_RESERVED: Final = {
    "library ref": "[Library Ref]",
    "library path": "[Library Path]",
    "footprint ref": "[Footprint Ref]",
    "footprint path": "[Footprint Path]",
    "description": "[Description]",
}
_FOOTPRINT_N: Final = re.compile(r"^footprint (ref|path) ([1-9]\d*)$")
#: Characters a database path cannot carry through ``Extended Properties="…;Database=…;"``.
_UNSAFE_PATH_CHARS: Final = frozenset(';"{}')
#: Characters that break ``Options=…|…`` sub-keys or the ``[…]`` quoting of names.
_UNSAFE_NAME_CHARS: Final = frozenset('|[]"')
_CONTROL_CATEGORIES: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})

DuplicateKind = Literal["same_database", "other_database", "missing", "unreachable", "unreadable"]
#: Same-name DbLibs PartForge may uninstall on "Ersetzen": an old copy of this library
#: (same database) or a dead entry whose file is gone (the drive itself is reachable).
REPLACEABLE_DUPLICATES: Final = frozenset({"same_database", "missing"})


class DbLibError(RuntimeError):
    """The DbLib cannot be built or written (German message; API: 400)."""


class DbLibPathError(DbLibError):
    """The SQLite path cannot be written into the DbLib unchanged (special characters)."""


# --------------------------------------------------------------------------- models


class DbLibFieldMap(BaseModel):
    """One ``[FieldMapN]`` entry (``Options=FieldName=…|TableNameOnly=…|…``)."""

    table: str
    column: str
    field_type: int = FIELD_TYPE_NORMAL
    parameter_name: str = ""
    visible_on_add: bool = False
    add_mode: int = ADD_MODE_DEFAULT
    remove_mode: int = 0
    update_mode: int = 0
    extra: dict[str, str] = Field(default_factory=dict)  # unknown sub-keys (read only)

    def options(self) -> str:
        return (
            f"FieldName={self.table}.{self.column}|TableNameOnly={self.table}|FieldNameOnly={self.column}"
            f"|FieldType={self.field_type}|ParameterName={self.parameter_name}"
            f"|VisibleOnAdd={'True' if self.visible_on_add else 'False'}|AddMode={self.add_mode}"
            f"|RemoveMode={self.remove_mode}|UpdateMode={self.update_mode}"
        )

    def key(self) -> tuple[Any, ...]:
        return (
            self.table.casefold(),
            self.column.casefold(),
            self.field_type,
            self.parameter_name,
            self.visible_on_add,
            self.add_mode,
            self.remove_mode,
            self.update_mode,
        )


class DbLibTable(BaseModel):
    """One ``[TableN]`` entry."""

    name: str
    enabled: bool = False
    schema_name: str = ""
    user_where: int = 0
    user_where_text: str = ""
    ui_state: dict[str, str] = Field(default_factory=dict)  # BrowserOrder_* (Altium's grid layout)
    extra: dict[str, str] = Field(default_factory=dict)  # unknown keys (read only)


class DbLibInfo(BaseModel):
    """Parsed DbLib file (:func:`read_dblib`)."""

    path: str | None = None
    version: str = ""
    links: dict[str, str] = Field(default_factory=dict)  # [DatabaseLinks] in file order
    tables: list[DbLibTable] = Field(default_factory=list)
    field_maps: list[DbLibFieldMap] = Field(default_factory=list)
    connection_string: str = ""
    odbc: dict[str, str] = Field(default_factory=dict)  # Extended Properties (lower-case keys)
    database_path: str | None = None  # SQLite: Database= of the connection string
    encoding: str = ENCODING
    bom: bool = False
    line_endings: Literal["crlf", "lf", "mixed", "none"] = "crlf"
    warnings: list[str] = Field(default_factory=list)

    @property
    def enabled_tables(self) -> list[str]:
        return [t.name for t in self.tables if t.enabled]

    def table(self, name: str) -> DbLibTable | None:
        folded = name.casefold()
        return next((t for t in self.tables if t.name.casefold() == folded), None)


class DbLibUiState(BaseModel):
    """Altium's editor state of an existing DbLib, carried over into the regenerated file."""

    links: dict[str, str] = Field(default_factory=dict)  # LastFocusedTable / TopPanelCollapsed / ViewMode
    tables: dict[str, dict[str, str]] = Field(default_factory=dict)  # table (casefold) -> BrowserOrder_*

    @classmethod
    def from_info(cls, info: DbLibInfo) -> DbLibUiState:
        return cls(
            links={k: v for k, v in info.links.items() if k in LINK_UI_KEYS},
            tables={t.name.casefold(): dict(t.ui_state) for t in info.tables if t.ui_state},
        )


IssueSeverity = Literal["error", "warning", "info"]


class DbLibIssue(BaseModel):
    code: str
    severity: IssueSeverity
    message: str


class DbLibBuild(BaseModel):
    """Result of :func:`build_dblib`: the file text and what it contains."""

    text: str
    tables: list[DbLibTable]
    field_maps: list[DbLibFieldMap]
    connection_string: str
    database: str  # absolute SQLite path or masked PostgreSQL target
    warnings: list[str] = Field(default_factory=list)  # German messages of ``issues``
    issues: list[DbLibIssue] = Field(default_factory=list)  # codes: unsafe_name, no_key, encoding
    skipped: list[str] = Field(default_factory=list)  # tables / "table.column" left out (unsafe names)


class DbLibStatus(BaseModel):
    """State of the workspace DbLib (``GET /api/altium/dblib``)."""

    path: str
    file_name: str
    exists: bool
    up_to_date: bool
    db_path_ok: bool
    db_kind: Literal["sqlite", "postgres"]
    database: str  # database the DbLib should point to
    dblib_database: str | None = None  # database the file on disk points to
    modified: float | None = None
    size: int | None = None
    tables: int = 0
    enabled_tables: list[str] = Field(default_factory=list)
    field_maps: int = 0
    installed_in_altium: bool | None = None  # None = unknown (cached, see install)
    install: DbLibInstallState | None = None
    issues: list[DbLibIssue] = Field(default_factory=list)


#: Why :func:`ensure_dblib` wrote (or did not write) the file – the detailed internal cause:
#: ``missing``; ``outdated`` (tables/field maps/link keys differ or the file is unreadable);
#: ``db_moved`` (the file points to another database: other SQLite file – also under an 8.3
#: alias – or another PostgreSQL server/database); ``settings`` (same database, other
#: connection – e.g. driver/attributes – or the database type switched in the settings);
#: ``format`` (same content, not cp1252/CRLF/without BOM); ``forced`` (only Altium's UI state
#: or the order differed, written because ``force``); ``unchanged`` (nothing written).
DbLibCause = Literal["missing", "outdated", "db_moved", "settings", "format", "forced", "unchanged"]
#: Stable reason id for the API (``POST /api/altium/dblib/regenerate``).
RegenerateReason = Literal["missing", "outdated", "wrong_database", "settings_changed", "forced", "up_to_date"]
REGENERATE_REASONS: Final[dict[str, RegenerateReason]] = {
    "missing": "missing",
    "outdated": "outdated",
    "format": "outdated",
    "db_moved": "wrong_database",
    "settings": "settings_changed",
    "forced": "forced",
    "unchanged": "up_to_date",
}
#: German explanation per internal cause (shown after "DbLib neu erzeugen").
REASON_TEXTS: Final[dict[str, str]] = {
    "missing": "Die DbLib fehlte und wurde neu angelegt.",
    "outdated": "Die DbLib war veraltet (Kategorien oder Felder geändert) und wurde neu geschrieben.",
    "format": "Die DbLib war nicht im Altium-Format (Windows-1252, CRLF, ohne BOM) gespeichert und wurde neu "
              "geschrieben.",
    "db_moved": "Die DbLib verwies auf eine andere Datenbank (Bibliotheksordner verschoben oder kopiert?) – sie "
                "verweist jetzt auf die Datenbank dieser Bibliothek.",
    "settings": "Die Datenbankeinstellungen der Bibliothek haben sich geändert – die DbLib verwendet jetzt die neue "
                "Verbindung.",
    "forced": "Die DbLib wurde neu geschrieben (inhaltlich unverändert).",
    "unchanged": "Die DbLib ist aktuell – nichts zu schreiben.",
}


class DbLibWriteResult(BaseModel):
    path: str
    written: bool
    reason: DbLibCause  # detailed cause (see DbLibCause)
    reason_id: RegenerateReason = "up_to_date"  # stable id for the API
    reason_text: str = ""  # German explanation
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def of(cls, path: str | os.PathLike[str], written: bool, reason: DbLibCause,
           warnings: Sequence[str] = ()) -> DbLibWriteResult:
        return cls(path=str(path), written=written, reason=reason, reason_id=REGENERATE_REASONS[reason],
                   reason_text=REASON_TEXTS[reason], warnings=list(warnings))


class DbLibDuplicate(BaseModel):
    """Another installed DbLib with the same file name, seen from this workspace."""

    path: str
    kind: DuplicateKind
    database: str | None = None  # where that DbLib points to (password masked)

    @property
    def replaceable(self) -> bool:
        return self.kind in REPLACEABLE_DUPLICATES


# --------------------------------------------------------------------------- helpers


def same_path(a: str | os.PathLike[str] | None, b: str | os.PathLike[str] | None) -> bool:
    """Spelling-independent path comparison (case, ``..``, 8.3 short names)."""
    if not a or not b:
        return False
    try:
        pa, pb = Path(os.path.abspath(str(a))), Path(os.path.abspath(str(b)))
    except (OSError, ValueError):
        return False
    if os.path.normcase(str(pa)) == os.path.normcase(str(pb)):
        return True
    try:
        return pa.exists() and pb.exists() and os.path.samefile(pa, pb)
    except OSError:
        return False


def same_database_file(value: str | os.PathLike[str] | None, path: str | os.PathLike[str] | None) -> bool:
    """True if ``value`` (``Database=`` of a DbLib) names the SQLite file ``path`` **under the
    same file name**. The folder may be spelled differently (``-wal``/``-shm`` still land
    beside the same file), the file name may not: SQLite derives the ``-wal``/``-shm`` names
    from it, so an 8.3 alias (``PARTFO~1.SQL``) gets a WAL index of its own."""
    if not value or not path:
        return False
    try:
        a, b = Path(os.path.abspath(str(value))), Path(os.path.abspath(str(path)))
    except (OSError, ValueError):
        return False
    if os.path.normcase(str(a)) == os.path.normcase(str(b)):
        return True
    return a.name.casefold() == b.name.casefold() and same_path(a.parent, b.parent)


def _encodable(text: str) -> bool:
    try:
        text.encode(ENCODING)
    except UnicodeEncodeError:
        return False
    return True


def _foreign_chars(text: str) -> list[str]:
    """Characters of ``text`` that Windows-1252 cannot represent."""
    return sorted({c for c in text if not _encodable(c)})


def _has_control(text: str) -> bool:
    return any(unicodedata.category(c) in _CONTROL_CATEGORIES for c in text)


def _shown(text: str, limit: int = 80) -> str:
    """Name for a German message: control characters made visible, long names shortened."""
    escapes = {"\r": "\\r", "\n": "\\n", "\t": "\\t"}
    out = "".join(
        escapes.get(c, f"\\u{ord(c):04x}") if unicodedata.category(c) in _CONTROL_CATEGORIES else c for c in text
    )
    return out if len(out) <= limit else out[: limit - 1] + "…"


def sqlite_path_problem(path: str | os.PathLike[str]) -> str | None:
    """Why ``path`` cannot be the ``Database=`` of a DbLib (German fragment), None if it can.

    Altium reads the DbLib as Windows-1252 and passes ``Database=`` through an OLE DB
    ``Extended Properties="…"`` value: ``;`` ends the attribute, ``{``/``}``/``"`` change
    the quoting – none of that is VERIFIED to survive, so such paths are refused."""
    text = str(path)
    if _has_control(text):
        return "Steuerzeichen"
    bad = sorted(set(text) & _UNSAFE_PATH_CHARS)
    if bad:
        return "die Zeichen " + " ".join(bad)
    foreign = _foreign_chars(text)
    if foreign:
        return "Zeichen außerhalb von Windows-1252 (" + " ".join(foreign) + ")"
    return None


def name_problem(name: str) -> str | None:
    """Why a table or column name cannot be written into the DbLib (German fragment), None if fine."""
    if not name or not name.strip():
        return "einen leeren Namen"
    if _has_control(name):
        return "Steuerzeichen (z. B. Zeilenumbrüche)"
    if name != name.strip():
        return "Leerzeichen am Anfang oder Ende"
    bad = sorted(set(name) & _UNSAFE_NAME_CHARS)
    if bad:
        return "die Zeichen " + " ".join(bad)
    foreign = _foreign_chars(name)
    if foreign:
        return "Zeichen außerhalb von Windows-1252 (" + " ".join(foreign) + ")"
    return None


def _odbc_value(value: str) -> str:
    """ODBC attribute value: braces when it contains ``;`` or braces (``}`` doubled)."""
    if any(c in value for c in ";{}") or value != value.strip():
        return "{" + value.replace("}", "}}") + "}"
    return value


def _sqlite_db_path(ws: Workspace) -> str:
    """Absolute database path as PartForge opens it (raises :class:`DbLibPathError`)."""
    text = os.path.abspath(ws.sqlite_path)
    problem = sqlite_path_problem(text)
    if problem:
        raise DbLibPathError(
            f"Der Datenbankpfad „{_shown(text, 200)}“ enthält {problem}. Altium kann die Datenbank über diesen Pfad "
            "nicht öffnen (ODBC-Verbindung in der DbLib, Windows-1252) – bitte die Bibliothek in einen Ordner ohne "
            "Sonderzeichen verschieben."
        )
    return text


def mask_secrets(text: str) -> str:
    """Connection string for display: passwords (``PWD=``, ``Password=``) hidden."""
    return re.sub(r"(?i)\b(pwd|password)\s*=\s*(\{(?:[^}]|\}\})*\}|[^;\"\r\n]*)", r"\1=***", text)


def _postgres_odbc(ws: Workspace) -> str:
    """ODBC attributes for PostgreSQL (``DRIVER={PostgreSQL Unicode(x64)};SERVER=…;``)."""
    db = ws.settings.db
    raw = (db.postgres_odbc or "").strip()
    if raw:
        attrs = raw if raw.endswith(";") else raw + ";"
        if not re.search(r"(?i)(^|;)\s*driver\s*=", attrs):
            attrs = f"DRIVER={{{POSTGRES_ODBC_DRIVER}}};" + attrs
        return attrs
    if not db.postgres_url:
        raise DbLibError(
            "Für PostgreSQL ist weder eine ODBC-Verbindung (Einstellungen › Bibliothek › Datenbank › ODBC für Altium) "
            "noch eine Verbindungs-URL eingetragen – die DbLib kann nicht erzeugt werden."
        )
    from sqlalchemy.engine import make_url

    try:
        url = make_url(db.postgres_url)
    except Exception as exc:  # invalid URL -> German message
        raise DbLibError(f"Die PostgreSQL-Verbindungs-URL ist ungültig: {exc}") from exc
    parts = [f"DRIVER={{{POSTGRES_ODBC_DRIVER}}}", f"SERVER={_odbc_value(url.host or 'localhost')}",
             f"PORT={url.port or 5432}", f"DATABASE={_odbc_value(url.database or '')}"]
    if url.username:
        parts.append(f"UID={_odbc_value(url.username)}")
    if url.password:
        parts.append(f"PWD={_odbc_value(str(url.password))}")
    return ";".join(parts) + ";"


def odbc_connection_string(ws: Workspace) -> str:
    """The ODBC part of the connection string (``Extended Properties``), also used by
    :func:`partforge.altium.odbc.test_odbc` to connect exactly like Altium.

    Raises :class:`DbLibPathError` for a SQLite path with special characters and
    :class:`DbLibError` for an unusable PostgreSQL configuration."""
    if ws.settings.db.kind == "postgres":
        attrs = _postgres_odbc(ws)
        if _has_control(attrs):  # a line break would inject lines into the INI file
            raise DbLibError(
                "Die ODBC-Verbindung für Altium enthält Steuerzeichen (z. B. Zeilenumbrüche) – bitte in den "
                "Bibliothekseinstellungen korrigieren."
            )
        return attrs
    return f"DRIVER={SQLITE_ODBC_DRIVER};Database={_sqlite_db_path(ws)};NoCreat=1;"


def connection_string(ws: Workspace) -> str:
    """``ConnectionString`` of the DbLib (MSDASQL around the ODBC attributes, VERIFIED)."""
    odbc = odbc_connection_string(ws).replace('"', '""')
    return f'{PROVIDER}"{odbc}"'


def _split_attributes(text: str) -> list[tuple[str, str]]:
    """``key=value;`` pairs; values may be quoted (``"…"``, ``'…'``) or braced (``{…}``)."""
    pairs: list[tuple[str, str]] = []
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in "; \t":
            i += 1
        if i >= n:
            break
        eq = text.find("=", i)
        if eq < 0:
            break
        key = text[i:eq].strip()
        i = eq + 1
        while i < n and text[i] in " \t":
            i += 1
        value_chars: list[str] = []
        if i < n and text[i] in "\"'":
            quote = text[i]
            i += 1
            while i < n:
                if text[i] == quote:
                    if i + 1 < n and text[i + 1] == quote:
                        value_chars.append(quote)
                        i += 2
                        continue
                    i += 1
                    break
                value_chars.append(text[i])
                i += 1
            while i < n and text[i] != ";":
                i += 1
        elif i < n and text[i] == "{":
            i += 1
            while i < n:
                if text[i] == "}":
                    if i + 1 < n and text[i + 1] == "}":
                        value_chars.append("}")
                        i += 2
                        continue
                    i += 1
                    break
                value_chars.append(text[i])
                i += 1
            while i < n and text[i] != ";":
                i += 1
        else:
            end = text.find(";", i)
            end = n if end < 0 else end
            value_chars.append(text[i:end].strip())
            i = end
        if key:
            pairs.append((key, "".join(value_chars)))
    return pairs


def parse_connection_string(text: str) -> tuple[dict[str, str], dict[str, str]]:
    """``(OLE DB attributes, ODBC attributes)`` of a DbLib connection string; keys lower-case."""
    outer = {k.lower(): v for k, v in _split_attributes(text or "")}
    inner_text = outer.get("extended properties", "")
    inner = {k.lower(): v for k, v in _split_attributes(inner_text)} if inner_text else {}
    if not inner and "driver" in outer:  # plain ODBC string without MSDASQL
        inner = dict(outer)
    return outer, inner


def reserved_parameter(column: str) -> str | None:
    """Reserved Altium design parameter of a column (``Library Ref`` -> ``[Library Ref]``)."""
    folded = " ".join(column.split()).casefold()
    if folded in _RESERVED:
        return _RESERVED[folded]
    m = _FOOTPRINT_N.match(folded)
    if m and int(m.group(2)) >= 2:  # Footprint Ref 2, 3, … (n starts at 2, never 1)
        return f"[Footprint {m.group(1).title()} {int(m.group(2))}]"
    return None


def field_map_for(table: str, field: FieldDef) -> DbLibFieldMap | None:
    """Field map of one column, or None when Altium's implicit default applies
    (parameter of the same name, not visible, added according to the global mode)."""
    column = field.column
    if column.casefold() == KEY_COLUMN.casefold():
        return DbLibFieldMap(table=table, column=column, field_type=FIELD_TYPE_KEY, parameter_name=column)
    reserved = reserved_parameter(column)
    if reserved:
        # attribute/model mappings have no update options in Altium (dblib-format.md §5)
        return DbLibFieldMap(table=table, column=column, parameter_name=reserved)
    visible = bool(field.show_on_schematic)
    add_mode = ADD_MODE_DEFAULT if field.add_to_design else ADD_MODE_DO_NOT_ADD
    if not visible and add_mode == ADD_MODE_DEFAULT:
        return None
    return DbLibFieldMap(table=table, column=column, parameter_name=column, visible_on_add=visible, add_mode=add_mode)


def _quotes(ws: Workspace) -> tuple[str, str]:
    return ('"', '"') if ws.settings.db.kind == "postgres" else ("[", "]")


def _key_where(ws: Workspace) -> str:
    left, right = _quotes(ws)
    return f"{left}{KEY_COLUMN}{right} = '{{{KEY_COLUMN}}}'"


def _validate_file_name(name: str) -> str:
    if not name or name != Path(name).name or any(c in name for c in '\\/:*?"<>|'):
        raise DbLibError(
            f"Ungültiger DbLib-Dateiname „{_shown(name)}“: erwartet wird ein reiner Dateiname wie „PartForge.DbLib“ "
            "(ohne Ordner)."
        )
    if not name.lower().endswith(".dblib"):
        raise DbLibError(f"Der DbLib-Dateiname „{_shown(name)}“ muss auf „.DbLib“ enden.")
    if _has_control(name) or any(ord(c) > 0xFF for c in name):
        raise DbLibError(
            f"Der DbLib-Dateiname „{_shown(name)}“ enthält Zeichen, die Altium nicht zuverlässig verarbeitet – bitte "
            "nur Buchstaben (auch Umlaute), Ziffern, Leerzeichen, „-“ und „_“ verwenden."
        )
    return name


def _issue(issues: list[DbLibIssue], code: str, severity: IssueSeverity, message: str) -> None:
    if not any(i.code == code and i.message == message for i in issues):
        issues.append(DbLibIssue(code=code, severity=severity, message=message))


# --------------------------------------------------------------------------- database facts


def database_matches(ws: Workspace) -> bool:
    """True if the open database belongs to ``ws`` (its categories describe this DbLib)."""
    from ..db import core

    if not core.is_open():
        return False
    try:
        return same_path(core.current_workspace().root, ws.root)
    except Exception:  # noqa: BLE001 - closed concurrently
        return False


def _require_database(ws: Workspace) -> None:
    if not database_matches(ws):
        raise DbLibError(
            "Die Datenbank dieser Bibliothek ist nicht geöffnet – die DbLib kann nicht aus den Kategorien erzeugt werden."
        )


def _load_categories() -> list[CategoryDef]:
    from ..db import categories

    cats = categories.list_categories(with_counts=False)
    return sorted(cats, key=lambda c: (c.sort_order, c.label, c.table))


def _other_tables(ws: Workspace, category_names: set[str]) -> list[str]:
    """Physical tables and views that are not categories (pf_* metadata, foreign tables)."""
    from ..db import core, schema

    if not database_matches(ws):
        return []
    with core.read() as conn:
        names = schema.physical_tables(conn) + schema.physical_views(conn)
    seen: set[str] = set()
    out: list[str] = []
    for name in sorted(names, key=lambda n: (n.casefold(), n)):
        folded = name.casefold()
        if folded in category_names or folded in seen or folded.startswith("sqlite_"):
            continue
        seen.add(folded)
        out.append(name)
    return out


# --------------------------------------------------------------------------- render


def _existing_ui_state(path: Path) -> DbLibUiState:
    if not path.is_file():
        return DbLibUiState()
    try:
        return DbLibUiState.from_info(read_dblib(path))
    except (OSError, DbLibError):
        log.debug("UI-Zustand der vorhandenen DbLib %s nicht lesbar", path, exc_info=True)
        return DbLibUiState()


def _safe_categories(cats: Iterable[CategoryDef], issues: list[DbLibIssue], seen: set[str],
                     skipped: list[str]) -> list[CategoryDef]:
    """Categories in order without duplicates and without names the DbLib cannot carry."""
    out: list[CategoryDef] = []
    for cat in cats:
        folded = cat.table.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        problem = name_problem(cat.table)
        if problem:
            skipped.append(cat.table)
            _issue(issues, "unsafe_name", "error" if cat.altium_enabled else "warning",
                   f"Kategorie „{_shown(cat.table)}“ wird nicht in die DbLib geschrieben – der Tabellenname enthält "
                   f"{problem}. Altium kann ihre Bauteile so nicht verwenden; bitte die Tabelle umbenennen.")
            continue
        out.append(cat)
    return out


def _safe_other_tables(names: Iterable[str], issues: list[DbLibIssue], seen: set[str],
                       skipped: list[str]) -> list[str]:
    out: list[str] = []
    for name in names:
        folded = name.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        problem = name_problem(name)
        if problem:
            skipped.append(name)
            _issue(issues, "unsafe_name", "warning",
                   f"Tabelle „{_shown(name)}“ wird in der DbLib übersprungen – der Name enthält {problem}.")
            continue
        out.append(name)
    return out


def _field_maps(cat: CategoryDef, issues: list[DbLibIssue], skipped: list[str]) -> list[DbLibFieldMap]:
    maps: list[DbLibFieldMap] = []
    for field in cat.fields:
        field_map = field_map_for(cat.table, field)
        if field_map is None:
            continue
        problem = name_problem(field.column)
        if problem:
            skipped.append(f"{cat.table}.{field.column}")
            _issue(issues, "unsafe_name", "warning",
                   f"Feld „{_shown(field.column)}“ der Kategorie „{cat.table}“ wird in der DbLib übersprungen – der "
                   f"Spaltenname enthält {problem}. Bitte die Spalte umbenennen.")
            continue
        maps.append(field_map)
    maps.sort(key=lambda m: m.field_type != FIELD_TYPE_KEY)  # stable: key first, then field order
    if not any(m.field_type == FIELD_TYPE_KEY for m in maps):
        _issue(issues, "no_key", "warning",
               f"Kategorie „{cat.table}“ hat keine Spalte „{KEY_COLUMN}“ – Altium kann sie nicht nutzen.")
    return maps


def build_dblib(
    ws: Workspace,
    categories: Sequence[CategoryDef] | None = None,
    *,
    other_tables: Sequence[str] | None = None,
    ui_state: DbLibUiState | None = None,
) -> DbLibBuild:
    """Build the DbLib for ``ws`` (deterministic for equal inputs).

    ``categories`` defaults to the categories of the open database, ``other_tables`` to
    its non-category tables and views, ``ui_state`` to the editor state of the existing file.
    Raises :class:`DbLibPathError` / :class:`DbLibError` when no valid file can be written.
    """
    issues: list[DbLibIssue] = []
    skipped: list[str] = []
    if categories is None:
        _require_database(ws)
    conn_string = connection_string(ws)  # first: a path Altium cannot use stops everything
    cats = list(categories) if categories is not None else _load_categories()
    seen: set[str] = set()
    unique = _safe_categories(cats, issues, seen, skipped)
    extras = list(other_tables) if other_tables is not None else _other_tables(ws, set(seen))
    extras = _safe_other_tables(extras, issues, seen, skipped)
    state = ui_state if ui_state is not None else _existing_ui_state(ws.dblib_path)

    sqlite = ws.settings.db.kind != "postgres"
    database = _sqlite_db_path(ws) if sqlite else mask_secrets(odbc_connection_string(ws))
    left, right = _quotes(ws)

    tables: list[DbLibTable] = []
    maps: list[DbLibFieldMap] = []
    for cat in unique:
        ui = state.tables.get(cat.table.casefold(), {})
        tables.append(DbLibTable(name=cat.table, enabled=bool(cat.altium_enabled),
                                 user_where_text=_key_where(ws), ui_state=dict(ui)))
        if cat.altium_enabled:
            maps.extend(_field_maps(cat, issues, skipped))
    for name in extras:
        ui = state.tables.get(name.casefold(), {})
        tables.append(DbLibTable(name=name, enabled=False, ui_state=dict(ui)))

    names = {t.name.casefold(): t.name for t in tables}
    enabled = [t.name for t in tables if t.enabled]
    focused = state.links.get("LastFocusedTable", "")
    focused = names.get(focused.casefold(), "") if focused else ""
    if not focused:
        focused = enabled[0] if enabled else (tables[0].name if tables else "")
    top_panel = state.links.get("TopPanelCollapsed", "0")
    view_mode = state.links.get("ViewMode", "0")
    links = {
        "ConnectionString": conn_string,
        "AddMode": str(GLOBAL_ADD_MODE),
        "RemoveMode": str(GLOBAL_REMOVE_MODE),
        "UpdateMode": str(GLOBAL_UPDATE_MODE),
        "ViewMode": view_mode if view_mode in ("0", "1") else "0",
        "LeftQuote": left,
        "RightQuote": right,
        "QuoteTableNames": "1",
        "UseTableSchemaName": "0",
        "DefaultColumnType": DEFAULT_COLUMN_TYPE,
        "LibraryDatabaseType": "",
        "LibraryDatabasePath": database if sqlite else "",
        "DatabasePathRelative": "0",
        "TopPanelCollapsed": top_panel if top_panel in ("0", "1") else "0",
        "LibrarySearchPath": "",
        "OrcadMultiValueDelimiter": ",",
        "SearchSubDirectories": "0",
        "SchemaName": "",
        "LastFocusedTable": focused,
    }

    lines = ["[OutputDatabaseLinkFile]", f"Version={DBLIB_VERSION}", "[DatabaseLinks]"]
    lines += [f"{key}={links[key]}" for key in LINK_KEYS]
    for i, table in enumerate(tables, start=1):
        lines += [
            f"[Table{i}]",
            f"SchemaName={table.schema_name}",
            f"TableName={table.name}",
            f"Enabled={'True' if table.enabled else 'False'}",
            f"UserWhere={table.user_where}",
            f"UserWhereText={table.user_where_text}",
        ]
        ordered: list[str] = [k for k in TABLE_UI_ORDER if k in table.ui_state]
        ordered += sorted(k for k in table.ui_state if k not in TABLE_UI_ORDER)
        lines += [f"{key}={table.ui_state[key]}" for key in ordered]
    for i, field_map in enumerate(maps, start=1):
        lines += [f"[FieldMap{i}]", f"Options={field_map.options()}"]
    text = "\r\n".join(lines) + "\r\n"

    bad = _foreign_chars(text)
    if bad:  # names are filtered above: what is left comes from the connection or Altium's UI state
        _issue(issues, "encoding", "warning",
               "Die DbLib enthält Zeichen, die Altium (Windows-1252) nicht darstellen kann und die als „?“ gespeichert "
               f"werden: {' '.join(bad)}. Bitte die Verbindungsangaben ohne diese Zeichen eintragen.")
    return DbLibBuild(text=text, tables=tables, field_maps=maps, connection_string=conn_string, database=database,
                      warnings=[i.message for i in issues], issues=issues, skipped=skipped)


def render_dblib(ws: Workspace, categories: Sequence[CategoryDef] | None = None) -> str:
    """DbLib text for ``ws`` (CRLF line endings; Altium's UI state of an existing file kept)."""
    return build_dblib(ws, categories).text


def encode_dblib(text: str) -> bytes:
    """File bytes: cp1252 (characters it cannot represent become ``?``), no BOM."""
    return text.encode(ENCODING, errors="replace")


# --------------------------------------------------------------------------- read


def _decode(raw: bytes) -> tuple[str, str, bool]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8", True
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace"), "utf-16", True
    if not raw.isascii():
        try:
            return raw.decode("utf-8"), "utf-8", False  # valid multi-byte UTF-8: not written by Altium
        except UnicodeDecodeError:
            pass
    return raw.decode(ENCODING, errors="replace"), ENCODING, False


def _line_endings(text: str) -> Literal["crlf", "lf", "mixed", "none"]:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and not lf:
        return "crlf"
    if lf and not crlf:
        return "lf"
    return "mixed" if crlf else "none"


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "yes")


def _parse_options(table_hint: str, raw: str) -> DbLibFieldMap | None:
    values: dict[str, str] = {}
    for part in raw.split("|"):
        key, sep, value = part.partition("=")
        if sep:
            values[key.strip()] = value
    table = values.pop("TableNameOnly", "")
    column = values.pop("FieldNameOnly", "")
    field_name = values.pop("FieldName", "")
    if (not table or not column) and "." in field_name:
        t, _, c = field_name.partition(".")
        table, column = table or t, column or c
    if not table:
        table = table_hint
    if not column:
        return None
    return DbLibFieldMap(
        table=table,
        column=column,
        field_type=_int(values.pop("FieldType", None), FIELD_TYPE_NORMAL),
        parameter_name=values.pop("ParameterName", ""),
        visible_on_add=_bool(values.pop("VisibleOnAdd", None)),
        add_mode=_int(values.pop("AddMode", None)),
        remove_mode=_int(values.pop("RemoveMode", None)),
        update_mode=_int(values.pop("UpdateMode", None)),
        extra=values,
    )


def parse_dblib(text: str, *, path: str | None = None) -> DbLibInfo:
    """Parse DbLib text (INI: ``[Section]`` and ``Key=Value`` lines, values to the line end)."""
    sections: list[tuple[str, dict[str, str]]] = []
    current: dict[str, str] | None = None
    warnings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = {}
            sections.append((stripped[1:-1].strip(), current))
            continue
        key, sep, value = line.partition("=")
        if not sep or current is None:
            warnings.append(f"Zeile {number} wird ignoriert: {stripped[:80]}")
            continue
        current[key.strip()] = value.strip()
    info = DbLibInfo(path=path, line_endings=_line_endings(text), warnings=warnings)
    tables: list[tuple[int, DbLibTable]] = []
    maps: list[tuple[int, DbLibFieldMap]] = []
    for name, values in sections:
        lowered = name.lower()
        if lowered == "outputdatabaselinkfile":
            info.version = values.get("Version", "")
        elif lowered == "databaselinks":
            info.links = dict(values)
        elif lowered.startswith("table") and lowered[5:].isdigit():
            data = dict(values)
            ui = {k: data.pop(k) for k in list(data) if k.startswith(TABLE_UI_PREFIX)}
            table = DbLibTable(
                name=data.pop("TableName", ""),
                enabled=_bool(data.pop("Enabled", None)),
                schema_name=data.pop("SchemaName", ""),
                user_where=_int(data.pop("UserWhere", None)),
                user_where_text=data.pop("UserWhereText", ""),
                ui_state=ui,
                extra=data,
            )
            if table.name:
                tables.append((int(lowered[5:]), table))
            else:
                info.warnings.append(f"Abschnitt [{name}] ohne TableName wird ignoriert.")
        elif lowered.startswith("fieldmap") and lowered[8:].isdigit():
            field_map = _parse_options("", values.get("Options", ""))
            if field_map is not None:
                maps.append((int(lowered[8:]), field_map))
            else:
                info.warnings.append(f"Abschnitt [{name}] ohne Feldnamen wird ignoriert.")
    info.tables = [t for _, t in sorted(tables, key=lambda item: item[0])]
    info.field_maps = [m for _, m in sorted(maps, key=lambda item: item[0])]
    info.connection_string = info.links.get("ConnectionString", "")
    _outer, odbc = parse_connection_string(info.connection_string)
    info.odbc = odbc
    # SQLite (and other file databases): Database= is a path; PostgreSQL: a database name
    info.database_path = None if "postgres" in odbc.get("driver", "").lower() else odbc.get("database")
    return info


def read_dblib(path: str | os.PathLike[str]) -> DbLibInfo:
    """Read and parse a DbLib file (cp1252; UTF-8 with BOM is tolerated and reported)."""
    p = Path(path)
    try:
        raw = p.read_bytes()
    except FileNotFoundError as exc:
        raise DbLibError(f"Die DbLib „{p}“ existiert nicht.") from exc
    text, encoding, bom = _decode(raw)
    info = parse_dblib(text, path=str(p))
    info.encoding = encoding
    info.bom = bom
    if not info.version and not info.links:
        raise DbLibError(f"„{p.name}“ ist keine gültige Altium-DbLib (Abschnitt [DatabaseLinks] fehlt).")
    return info


# --------------------------------------------------------------------------- compare / write


def _semantic(info: DbLibInfo) -> tuple[Any, ...]:
    """Content that matters to Altium (UI state, order and unknown keys ignored)."""
    links = tuple((k, info.links.get(k, "")) for k in LINK_KEYS if k not in LINK_UI_KEYS)
    tables = tuple(sorted(
        (t.name.casefold(), t.enabled, t.user_where, t.user_where_text, t.schema_name) for t in info.tables
    ))
    maps = tuple(sorted(m.key() for m in info.field_maps))
    return info.version, links, tables, maps


def _canonical_format(info: DbLibInfo) -> bool:
    return info.encoding == ENCODING and not info.bom and info.line_endings == "crlf"


_write_lock = threading.RLock()


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via temp file + rename; falls back to in-place writing if the target is held."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_bytes(data)
        for attempt in range(8):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        try:
            with open(path, "wb") as fh:  # target open without FILE_SHARE_DELETE: overwrite in place
                fh.write(data)
        except OSError as exc:
            raise DbLibError(
                f"Die DbLib „{path}“ kann nicht geschrieben werden ({exc.strerror or exc}). Bitte prüfen, ob die Datei "
                "schreibgeschützt ist oder von einem anderen Programm gesperrt wird."
            ) from exc
    except OSError as exc:
        raise DbLibError(f"Die DbLib „{path}“ kann nicht geschrieben werden: {exc}") from exc
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def _connection_cause(ws: Workspace, current: DbLibInfo) -> DbLibCause:
    """``db_moved`` if the file points to another database, ``settings`` if it uses this
    library's database through another connection (or the database type was switched)."""
    file_postgres = "postgres" in current.odbc.get("driver", "").lower()
    if file_postgres != (ws.settings.db.kind == "postgres"):
        return "settings"
    if not file_postgres:
        return "settings" if same_database_file(current.database_path, ws.sqlite_path) else "db_moved"
    return "settings" if _points_to_workspace(ws, current) else "db_moved"


def dblib_cause(ws: Workspace, current: DbLibInfo | None, expected: DbLibInfo) -> DbLibCause | None:
    """Why the file ``current`` must be rewritten to become ``expected`` (``None`` = it need not;
    Altium's UI state and the order of entries do not count)."""
    if current is None:
        return "outdated"
    if current.connection_string != expected.connection_string:
        return _connection_cause(ws, current)
    if _semantic(current) != _semantic(expected):
        return "outdated"
    if not _canonical_format(current):
        return "format"
    return None


def ensure_dblib(ws: Workspace, *, force: bool = False) -> DbLibWriteResult:
    """Write the DbLib when it is missing, outdated, points to another database, uses another
    connection or is not in Altium's format; ``force`` writes the canonical file in every case.

    Never rewrites a file whose content already matches (Altium's UI state is kept). The result
    names the detailed cause (``reason``), the stable API id (``reason_id``) and a German
    ``reason_text``; with ``force`` the cause stays the real one and is ``forced`` only when
    nothing but Altium's UI state or the order differed. Raises :class:`DbLibPathError`
    (database path with special characters – nothing is written, an existing file stays as it
    is) or :class:`DbLibError`.
    """
    with _write_lock:
        path = ws.dblib_path
        _validate_file_name(ws.settings.dblib_file)
        build = build_dblib(ws)
        data = encode_dblib(build.text)
        reason: DbLibCause
        if not path.is_file():
            reason = "missing"
        else:
            try:
                current_bytes = path.read_bytes()
            except OSError as exc:
                raise DbLibError(f"Die DbLib „{path}“ kann nicht gelesen werden: {exc}") from exc
            if current_bytes == data:
                return DbLibWriteResult.of(path, False, "unchanged", build.warnings)
            try:
                current = read_dblib(path)
            except DbLibError:
                current = None
            cause = dblib_cause(ws, current, parse_dblib(build.text))
            if cause is None and not force:
                return DbLibWriteResult.of(path, False, "unchanged", build.warnings)
            reason = cause or "forced"
        _atomic_write(path, data)
        log.info("DbLib geschrieben (%s): %s", reason, path)
        for warning in build.warnings:
            log.warning("DbLib %s: %s", path.name, warning)
        return DbLibWriteResult.of(path, True, reason, build.warnings)


def dblib_bytes(ws: Workspace, which: Literal["target", "file"] = "target") -> bytes:
    """Exact bytes of the DbLib: ``target`` = what :func:`ensure_dblib` writes now (cp1252,
    CRLF, Altium's UI state of the current file kept), ``file`` = the file on disk.

    Unlike the preview, connection passwords are **not** masked (Altium needs them in the
    file). Raises :class:`DbLibError` if the file does not exist (``file``) or the target
    cannot be built."""
    if which == "file":
        path = ws.dblib_path
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise DbLibError(
                f"Die DbLib „{ws.settings.dblib_file}“ existiert noch nicht – „DbLib neu erzeugen“ legt sie an."
            ) from exc
        except OSError as exc:
            raise DbLibError(f"Die DbLib „{path}“ kann nicht gelesen werden: {exc}") from exc
    return encode_dblib(build_dblib(ws).text)


def write_dblib(ws: Workspace) -> Path:
    """Write the DbLib of ``ws`` (canonical content; unchanged files are not touched)."""
    return Path(ensure_dblib(ws, force=True).path)


# --------------------------------------------------------------------------- Altium install cache

_CACHE_FILE: Final = "altium_dblib_installs.json"
_cache_lock = threading.RLock()


def _cache_path() -> Path:
    """Install states seen in this PC's Altium: local folder (never roaming); an older roaming copy moves along."""
    path = local_data_dir() / _CACHE_FILE
    legacy = app_data_dir() / _CACHE_FILE
    if legacy != path and legacy.is_file() and not path.exists():
        with contextlib.suppress(OSError):
            os.replace(legacy, path)
    return path


def _cache_key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _load_cache() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_cache(data: Mapping[str, Any]) -> None:
    path = _cache_path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        log.warning("Altium-Installationsstatus konnte nicht gespeichert werden", exc_info=True)


def cached_install_state(dblib: str | os.PathLike[str]) -> DbLibInstallState | None:
    """Last known Altium install state of this DbLib path (None = never checked)."""
    with _cache_lock:
        raw = _load_cache().get(_cache_key(dblib))
    if not isinstance(raw, dict):
        return None
    try:
        return DbLibInstallState.model_validate(raw)
    except ValidationError:
        return None


def cached_install_states() -> list[DbLibInstallState]:
    with _cache_lock:
        data = _load_cache()
    out: list[DbLibInstallState] = []
    for raw in data.values():
        with contextlib.suppress(ValidationError, TypeError):
            out.append(DbLibInstallState.model_validate(raw))
    return out


def remember_install_state(state: DbLibInstallState, *, dblib: str | os.PathLike[str] | None = None) -> None:
    """Store an install state (key: ``dblib`` or ``state.path``)."""
    with _cache_lock:
        data = _load_cache()
        data[_cache_key(dblib or state.path)] = state.model_dump(mode="json")
        _save_cache(data)


def forget_install_state(dblib: str | os.PathLike[str]) -> None:
    with _cache_lock:
        data = _load_cache()
        if data.pop(_cache_key(dblib), None) is not None:
            _save_cache(data)


# --------------------------------------------------------------------------- same-name DbLibs


def _postgres_key(attrs: Mapping[str, str]) -> tuple[str, str, str]:
    return (attrs.get("server", "").strip().casefold(), (attrs.get("port", "") or "5432").strip(),
            attrs.get("database", "").strip().casefold())


def _points_to_workspace(ws: Workspace, info: DbLibInfo) -> bool:
    """True if a DbLib file uses the database of ``ws`` (SQLite file / PostgreSQL server+database)."""
    is_postgres = "postgres" in info.odbc.get("driver", "").lower()
    if ws.settings.db.kind == "postgres":
        if not is_postgres:
            return False
        try:
            _outer, ours = parse_connection_string(odbc_connection_string(ws))
        except DbLibError:
            return False
        return _postgres_key(info.odbc) == _postgres_key(ours)
    return not is_postgres and bool(info.database_path) and same_path(info.database_path, ws.sqlite_path)


def _anchor_reachable(path: Path) -> bool:
    try:
        return bool(path.anchor) and Path(path.anchor).exists()
    except OSError:
        return False


def classify_duplicate(ws: Workspace, path: str | os.PathLike[str]) -> DbLibDuplicate:
    """What another installed DbLib with the file name of ``ws``'s DbLib is.

    Reads that file (call it from a job: it may sit on a slow or offline network drive):

    * ``same_database`` – it uses this library's database (old folder or a copy),
    * ``other_database`` – it belongs to another library (never uninstalled by PartForge),
    * ``missing`` – the file is gone but its drive is there (dead entry in Altium),
    * ``unreachable`` – drive or share not reachable (could be another library),
    * ``unreadable`` – exists but is no readable DbLib.
    """
    text = str(path)
    p = Path(text)
    try:
        exists = p.is_file()
    except OSError:
        exists = False
    if not exists:
        return DbLibDuplicate(path=text, kind="missing" if _anchor_reachable(p) else "unreachable")
    try:
        info = read_dblib(p)
    except (DbLibError, OSError):
        return DbLibDuplicate(path=text, kind="unreadable")
    database: str | None = info.database_path
    if "postgres" in info.odbc.get("driver", "").lower():
        database = mask_secrets(f"{info.odbc.get('server', '')}/{info.odbc.get('database', '')}")
    kind: DuplicateKind = "same_database" if _points_to_workspace(ws, info) else "other_database"
    return DbLibDuplicate(path=text, kind=kind, database=database)


def classify_install_state(ws: Workspace, state: DbLibInstallState) -> tuple[DbLibInstallState, list[DbLibDuplicate]]:
    """``state`` with ``duplicate_kinds`` filled in, plus the classified duplicates."""
    found = [classify_duplicate(ws, path) for path in state.duplicates]
    kinds = {d.path: d.kind for d in found}
    return state.model_copy(update={"duplicate_kinds": kinds}), found


_KIND_TEXT: Final[dict[str, str]] = {
    "same_database": "verweist auf die Datenbank dieser Bibliothek",
    "missing": "Datei existiert nicht mehr",
    "unreachable": "Ordner bzw. Laufwerk nicht erreichbar",
    "unreadable": "keine lesbare DbLib",
}


def _describe_duplicate(path: str, kind: str | None, database: str | None = None) -> str:
    if kind == "other_database":
        detail = f"verweist auf die Datenbank {database}" if database else "gehört zu einer anderen Datenbank"
    else:
        detail = _KIND_TEXT.get(kind or "", "")
    return f"{path} ({detail})" if detail else path


def duplicate_advice(file_name: str, kinds: Iterable[str | None]) -> str:
    """What to do about same-name DbLibs of the given kinds (German, one or two sentences)."""
    known = list(kinds)
    several = len(known) > 1
    if known and all(k in REPLACEABLE_DUPLICATES for k in known):
        if several:
            return ("Sie gehören zu dieser Bibliothek (alter Ordner) oder existieren nicht mehr – „In Altium "
                    "installieren“ mit „Ersetzen“ ersetzt die alten Installationen.")
        return ("Sie gehört zu dieser Bibliothek (alter Ordner) oder existiert nicht mehr – „In Altium installieren“ "
                "mit „Ersetzen“ ersetzt die alte Installation.")
    if any(k == "other_database" for k in known):
        head = "Mindestens eine davon gehört" if several else "Sie gehört"
        return (f"{head} zu einer anderen Bibliothek. Platzierte Bauteile finden ihre DbLib nur über den Dateinamen "
                f"„{file_name}“ – PartForge ersetzt sie deshalb nicht. Bitte dieser Bibliothek einen eigenen "
                "DbLib-Dateinamen geben (Bibliothekseinstellungen) und die DbLib neu erzeugen und installieren.")
    verb = "gehören" if several else "gehört"
    return (f"Ob {'sie' if not several else 'diese'} zu dieser Bibliothek {verb}, ließ sich nicht prüfen. Platzierte "
            f"Bauteile finden ihre DbLib nur über den Dateinamen „{file_name}“ – bitte „Installationsstatus prüfen“ "
            "wählen, die andere DbLib in Altium selbst deinstallieren oder dieser Bibliothek einen eigenen "
            "DbLib-Dateinamen geben.")


def duplicates_message(state: DbLibInstallState, duplicates: Sequence[DbLibDuplicate] | None = None) -> str:
    """German description of the same-name DbLibs of ``state`` (with advice)."""
    by_path = {d.path: d for d in duplicates or []}
    described = []
    kinds: list[str | None] = []
    for path in state.duplicates:
        found = by_path.get(path)
        kind = found.kind if found is not None else state.duplicate_kinds.get(path)
        kinds.append(kind)
        described.append(_describe_duplicate(path, kind, found.database if found is not None else None))
    listing = "; ".join(described)
    several = len(state.duplicates) > 1
    if state.installed:
        head = (f"Neben dieser DbLib {'sind' if several else 'ist'} in Altium {'weitere DbLibs' if several else 'eine weitere DbLib'} "
                f"mit dem Dateinamen „{state.file_name}“ installiert: {listing}.")
        if not state.resolves_to_this and state.first_match:
            head += f" Altium verwendet derzeit „{state.first_match}“ (zuerst installiert)."
    else:
        head = (f"Diese DbLib ist in Altium nicht installiert, aber {'andere DbLibs' if several else 'eine andere DbLib'} "
                f"mit demselben Dateinamen „{state.file_name}“: {listing}.")
    return f"{head} {duplicate_advice(state.file_name, kinds)}"


# --------------------------------------------------------------------------- status


def _install_issues(ws: Workspace, issues: list[DbLibIssue]) -> DbLibInstallState | None:
    state = cached_install_state(ws.dblib_path)
    if state is None:
        others = [s for s in cached_install_states()
                  if s.installed and s.file_name.casefold() == ws.settings.dblib_file.casefold()
                  and not same_path(s.path, ws.dblib_path)]
        if others:
            _issue(issues, "moved_install", "warning",
                   f"Laut letzter Prüfung ist in Altium eine DbLib „{ws.settings.dblib_file}“ aus einem anderen Ordner "
                   f"installiert ({others[0].path}). Gehört sie zu dieser Bibliothek (Ordner verschoben), bitte „In "
                   "Altium installieren“ mit „Ersetzen“ wählen; gehört sie zu einer anderen Bibliothek, bitte dieser "
                   "Bibliothek einen eigenen DbLib-Dateinamen geben.")
        return None
    if state.duplicates:
        _issue(issues, "duplicates", "error", duplicates_message(state))
    if not state.installed:
        _issue(issues, "not_installed", "info", "Die DbLib ist in Altium nicht installiert.")
    shown = [e.path for e in state.same_name if e.same_file and e.document_shown]
    if shown:
        _issue(issues, "open_in_editor", "warning",
               "Die DbLib ist in Altium in einem Editor-Tab geöffnet. Solange er offen ist, kann PartForge Altium nicht "
               "aktualisieren – bitte den Tab schließen.")
    return state


def status_model(ws: Workspace) -> DbLibStatus:
    """Status of the workspace DbLib (no Altium access; the install state is cached)."""
    issues: list[DbLibIssue] = []
    path = ws.dblib_path
    kind: Literal["sqlite", "postgres"] = "postgres" if ws.settings.db.kind == "postgres" else "sqlite"
    try:
        _validate_file_name(ws.settings.dblib_file)
    except DbLibError as exc:
        _issue(issues, "file_name", "error", str(exc))
    database = str(Path(os.path.abspath(ws.sqlite_path))) if kind == "sqlite" else ""
    build: DbLibBuild | None = None
    try:
        if not database_matches(ws):
            raise DbLibError("Die Datenbank der Bibliothek ist nicht geöffnet – der Soll-Stand der DbLib ist unbekannt.")
        build = build_dblib(ws)
        database = build.database
        for build_issue in build.issues:
            _issue(issues, build_issue.code, build_issue.severity, build_issue.message)
    except DbLibPathError as exc:
        _issue(issues, "db_path_chars", "error", str(exc))
    except DbLibError as exc:
        _issue(issues, "build", "error", str(exc))
    except Exception as exc:  # the status must always answer (logged)
        log.exception("Soll-Stand der DbLib konnte nicht berechnet werden")
        _issue(issues, "build", "error", f"Der Soll-Stand der DbLib konnte nicht berechnet werden: {exc}")

    exists = path.is_file()
    info: DbLibInfo | None = None
    modified: float | None = None
    size: int | None = None
    if exists:
        with contextlib.suppress(OSError):
            stat = path.stat()
            modified, size = stat.st_mtime, stat.st_size
        try:
            info = read_dblib(path)
        except (DbLibError, OSError) as exc:
            _issue(issues, "unreadable", "error", f"Die DbLib kann nicht gelesen werden: {exc}")
    else:
        _issue(issues, "missing", "error",
               f"Die DbLib „{ws.settings.dblib_file}“ fehlt – bitte „DbLib neu erzeugen“ wählen.")

    up_to_date = False
    db_path_ok = False
    dblib_database: str | None = None
    if info is not None:
        if kind == "sqlite":
            dblib_database = info.database_path
            db_path_ok = same_database_file(dblib_database, ws.sqlite_path)
            if not db_path_ok:
                if dblib_database and same_path(dblib_database, ws.sqlite_path):
                    _issue(issues, "db_path", "error",
                           f"Die DbLib verweist unter einem anderen Dateinamen („{dblib_database}“, z. B. 8.3-Kurzname) "
                           "auf die Datenbank – SQLite führt dann für Altium eigene WAL-Dateien und Altium sieht "
                           "PartForges Änderungen nicht zuverlässig. Bitte „DbLib neu erzeugen“ wählen.")
                else:
                    _issue(issues, "db_path", "error",
                           f"Die DbLib verweist auf die Datenbank „{dblib_database or '?'}“ statt auf „{database}“ "
                           "(Bibliothek verschoben?). Bitte „DbLib neu erzeugen“ wählen.")
        else:
            dblib_database = mask_secrets(info.odbc.get("server", "") + "/" + info.odbc.get("database", ""))
            db_path_ok = build is not None and info.connection_string == build.connection_string
            if build is not None and not db_path_ok:
                _issue(issues, "db_path", "error",
                       "Die DbLib verwendet eine andere PostgreSQL-Verbindung als die Bibliothek. Bitte „DbLib neu "
                       "erzeugen“ wählen.")
        if build is not None:
            same_content = _semantic(info) == _semantic(parse_dblib(build.text))
            up_to_date = same_content and _canonical_format(info)
            if not up_to_date and db_path_ok:
                if same_content:
                    _issue(issues, "format", "warning",
                           "Die DbLib ist nicht im Altium-Format (Windows-1252, CRLF, ohne BOM) gespeichert.")
                else:
                    _issue(issues, "outdated", "warning",
                           "Die DbLib ist veraltet (Kategorien oder Felder wurden geändert). Bitte „DbLib neu erzeugen“ "
                           "wählen.")
        if not info.enabled_tables:
            _issue(issues, "no_enabled_tables", "warning",
                   "In der DbLib ist keine Tabelle für Altium aktiviert – Altium zeigt keine Bauteile an.")
        for warning in info.warnings:
            _issue(issues, "parse", "warning", warning)

    if kind == "sqlite":
        from ..db.core import file_journal_mode, is_network_path

        if is_network_path(ws.sqlite_path):
            _issue(issues, "network", "error",
                   "Die SQLite-Datenbank liegt auf einem Netzlaufwerk – Altium und PartForge können dort nicht "
                   "gleichzeitig arbeiten (WAL). Für Teams bitte PostgreSQL verwenden.")
        mode = file_journal_mode(ws.sqlite_path)
        if mode == "new":
            _issue(issues, "db_missing", "error", f"Die Datenbankdatei „{ws.sqlite_path}“ fehlt.")
        elif mode == "rollback":
            _issue(issues, "wal", "error",
                   "Die Datenbank ist nicht im WAL-Modus – solange Altium sie liest, kann PartForge nicht speichern. "
                   "Bitte Altium schließen und die Bibliothek erneut öffnen (PartForge stellt sie dann um).")
    if build is not None:
        for table in build.tables:
            if table.enabled and not any(
                m.table == table.name and m.parameter_name == "[Library Ref]" for m in build.field_maps
            ):
                _issue(issues, "library_ref", "error",
                       f"Tabelle „{table.name}“ hat keine Spalte „Library Ref“ – Altium kann daraus keine Bauteile "
                       "platzieren.")
    others = sorted(
        p.name for p in ws.root.glob("*")
        if p.is_file() and p.suffix.lower() == ".dblib" and p.name.casefold() != ws.settings.dblib_file.casefold()
    )
    if others:
        _issue(issues, "other_dblibs", "info",
               f"Weitere DbLib-Dateien im Bibliotheksordner: {', '.join(others)}. Altium-Bauteile verweisen nur über "
               f"den Dateinamen auf „{ws.settings.dblib_file}“.")
    install = _install_issues(ws, issues)
    tables = build.tables if build is not None else (info.tables if info else [])
    return DbLibStatus(
        path=str(path),
        file_name=ws.settings.dblib_file,
        exists=exists,
        up_to_date=up_to_date,
        db_path_ok=db_path_ok,
        db_kind=kind,
        database=database,
        dblib_database=dblib_database,
        modified=modified,
        size=size,
        tables=len(tables),
        enabled_tables=[t.name for t in tables if t.enabled],
        field_maps=len(build.field_maps) if build is not None else (len(info.field_maps) if info else 0),
        installed_in_altium=install.installed if install is not None else None,
        install=install,
        issues=issues,
    )


def dblib_status(ws: Workspace) -> dict[str, Any]:
    """``{path, exists, up_to_date, db_path_ok, issues[], installed_in_altium, file_name, …}``."""
    return status_model(ws).model_dump(mode="json")


# --------------------------------------------------------------------------- automatic regeneration


class DbLibAutoWriter:
    """Keeps the DbLib in sync: rewrites it after schema changes (categories/fields) and
    when a workspace is opened (missing, outdated, or the library folder moved).

    Handlers run in the thread that caused the change; they never raise (errors are
    logged) and need no Altium. ``on_written(ws, result)`` runs after an actual rewrite
    (the refresh service uses it to make a running Altium re-read the file).
    """

    def __init__(
        self,
        *,
        workspace_provider: Callable[[], Workspace | None] = current_or_none,
        on_written: Callable[[Workspace, DbLibWriteResult], None] | None = None,
    ):
        self._workspace = workspace_provider
        self._on_written = on_written
        self._unsubscribers: list[Callable[[], None]] = []
        self._local = threading.local()
        self._lock = threading.Lock()
        self.last_result: DbLibWriteResult | None = None
        self.last_error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._unsubscribers)

    def start(self) -> None:
        from ..db import categories

        with self._lock:
            if self._unsubscribers:
                return
            self._unsubscribers = [
                categories.on_schema_change(self._on_schema_change),
                events.subscribe(events.SCHEMA_CHANGED, self._on_schema_change),
                events.subscribe(events.WORKSPACE_OPENED, self._on_workspace_opened),
            ]

    def stop(self) -> None:
        with self._lock:
            unsubscribers, self._unsubscribers = self._unsubscribers, []
        for unsubscribe in unsubscribers:
            with contextlib.suppress(Exception):
                unsubscribe()

    def _on_schema_change(self, *_args: Any, **_kwargs: Any) -> None:
        ws = self._workspace()
        if ws is not None:
            self.ensure(ws, reason="Schemaänderung")

    def _on_workspace_opened(self, ws: Workspace | None = None, *_args: Any, **_kwargs: Any) -> None:
        target = ws if isinstance(ws, Workspace) else self._workspace()
        if target is not None:
            self.ensure(target, reason="Bibliothek geöffnet")

    def ensure(self, ws: Workspace, *, reason: str = "") -> DbLibWriteResult | None:
        """Rewrite the DbLib if needed; None if it could not be checked (logged)."""
        if getattr(self._local, "busy", False):  # re-entrant schema notification
            return None
        if not database_matches(ws):  # its categories would describe another library
            return None
        self._local.busy = True
        try:
            result = ensure_dblib(ws)
        except Exception as exc:  # noqa: BLE001 - events must never break the change that caused them
            self.last_error = str(exc)
            log.warning("DbLib konnte nicht aktualisiert werden (%s): %s", reason or "automatisch", exc)
            return None
        finally:
            self._local.busy = False
        self.last_result = result
        self.last_error = None
        if result.written:
            log.info("DbLib nach %s neu geschrieben (%s)", reason or "Änderung", result.reason)
            if self._on_written is not None:
                try:
                    self._on_written(ws, result)
                except Exception:  # logged
                    log.exception("Nachbearbeitung nach dem Schreiben der DbLib fehlgeschlagen")
        return result
