"""Database schema: PartForge metadata tables, category table DDL, migrations, reconciliation.

Metadata tables (prefix ``pf_``, disabled in the DbLib):
``pf_meta`` (schema version), ``pf_categories``, ``pf_fields``, ``pf_symbols``,
``pf_footprints``, ``pf_datasheets``, ``pf_audit``, ``pf_mpn_templates``, ``pf_saved_views``.

Category tables (Altium-visible): ``"Part Number" TEXT NOT NULL PRIMARY KEY`` and ``TEXT``
for every other column (ARCHITEKTUR.md §4, VERIFIED in Altium 26.10: ``VARCHAR(n)``
values are truncated to ``n`` characters in Altium, ``TEXT`` is not; ``REAL``/``NUMERIC``
would be shown with a decimal comma). All values are pre-formatted text; length limits
are soft validation in PartForge only. Identifiers are always quoted (names like
``RDS(on)`` or ``Manufacturer Part Number``).

Schema versions (``pf_meta.schema_version``): 1 = initial schema (VARCHAR category
columns), 2 = category columns converted to TEXT (:func:`convert_to_text`).

Nothing in an Altium-visible table may depend on PartForge's SQL functions: the
SQLite ODBC driver used by Altium (SQLite 3.43) only knows built-in functions.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Connection,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    delete,
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy.engine.interfaces import ReflectedColumn
from sqlalchemy.exc import DBAPIError

from .. import __version__
from .errors import SchemaError
from .models import CategoryDef, FieldDef
from .templates import CATEGORIES, COMMON_FIELDS, CategoryTemplate, FieldTemplate, category_by_table
from .values import PART_NUMBER

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2
PF_PREFIX = "pf_"
COLUMN_TYPE = "TEXT"  # every Altium-visible column (see module docstring)
_TMP_TABLE = "pf_tmp_rebuild"

# Columns that must keep their exact name and cannot be removed.
PROTECTED_COLUMNS: frozenset[str] = frozenset(
    {
        PART_NUMBER,
        "Library Ref",
        "Library Path",
        "Footprint Ref",
        "Footprint Path",
        "Footprint Ref 2",
        "Footprint Path 2",
        "PF Created",
        "PF Modified",
        "PF Author",
    }
)

metadata = MetaData()

pf_meta = Table(
    "pf_meta",
    metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text),
)

pf_categories = Table(
    "pf_categories",
    metadata,
    Column("table_name", String(255), primary_key=True),
    Column("label", String(255), nullable=False),
    Column("prefix", String(32), nullable=False, default="U"),
    Column("icon", String(64)),
    Column("color", String(32)),
    Column("default_symbol", String(255)),
    Column("value_field", String(255)),
    Column("description_template", Text),
    Column("comment_template", Text),
    Column("sort_order", Integer, nullable=False, default=0),
    Column("altium_enabled", Boolean, nullable=False, default=True),
    Column("builtin", Boolean, nullable=False, default=False),
    Column("created", String(32)),
    Column("modified", String(32)),
)

pf_fields = Table(
    "pf_fields",
    metadata,
    Column(
        "table_name",
        String(255),
        ForeignKey("pf_categories.table_name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    ),
    Column("column_name", String(255), primary_key=True),
    Column("label", String(255), nullable=False),
    Column("kind", String(16), nullable=False, default="text"),
    Column("unit", String(32)),
    Column("options", Text),  # JSON list
    Column("required", Boolean, nullable=False, default=False),
    Column("show_on_schematic", Boolean, nullable=False, default=False),
    Column("add_to_design", Boolean, nullable=False, default=True),
    Column("system", Boolean, nullable=False, default=False),
    Column("common", Boolean, nullable=False, default=False),
    Column("grid_width", Integer),
    Column("help", Text),
    Column("sort_order", Integer, nullable=False, default=0),
    Column("length", Integer),
)

pf_symbols = Table(
    "pf_symbols",
    metadata,
    Column("name", String(255), primary_key=True),
    Column("library", String(1000), nullable=False, default=""),
    Column("source", String(32), nullable=False, default="generated"),
    Column("spec", Text),  # SymbolSpec JSON
    Column("pin_count", Integer, nullable=False, default=0),
    Column("part_count", Integer, nullable=False, default=1),
    Column("kind", String(64)),
    Column("status", String(16), nullable=False, default="pending"),
    Column("status_message", Text),
    Column("created", String(32)),
    Column("updated", String(32)),
)

pf_footprints = Table(
    "pf_footprints",
    metadata,
    Column("name", String(255), primary_key=True),
    Column("library", String(1000), nullable=False, default=""),
    Column("source", String(32), nullable=False, default="generated"),
    Column("spec", Text),  # FootprintSpec JSON
    Column("family", String(64)),
    Column("ipc_name", String(255)),
    Column("pad_count", Integer, nullable=False, default=0),
    Column("height", Float),
    Column("step_file", String(1000)),
    Column("status", String(16), nullable=False, default="pending"),
    Column("status_message", Text),
    Column("created", String(32)),
    Column("updated", String(32)),
)

pf_datasheets = Table(
    "pf_datasheets",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("file", String(1000), nullable=False),
    Column("original_name", String(1000), nullable=False),
    Column("title", String(1000)),
    Column("manufacturer", String(255)),
    Column("mpns", Text),  # JSON list
    Column("page_count", Integer, nullable=False, default=0),
    Column("text_pages", Text),  # JSON list
    Column("extraction", Text),  # JSON object
    Column("created", String(32)),
)

pf_audit = Table(
    "pf_audit",
    metadata,
    Column("id", Integer, primary_key=True),  # no AUTOINCREMENT -> no sqlite_sequence table
    Column("ts", String(32), nullable=False),
    Column("author", String(255)),
    Column("action", String(16), nullable=False),
    Column("table_name", String(255)),
    Column("part_number", String(255)),
    Column("changes", Text),  # JSON {column: [old, new]}
)
Index("ix_pf_audit_part", pf_audit.c.table_name, pf_audit.c.part_number)
Index("ix_pf_audit_ts", pf_audit.c.ts)

pf_mpn_templates = Table(
    "pf_mpn_templates",
    metadata,
    Column("key", String(128), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("category", String(255)),
    Column("data", Text, nullable=False),  # JSON
    Column("created", String(32)),
    Column("modified", String(32)),
)

pf_saved_views = Table(
    "pf_saved_views",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("table_name", String(255)),
    Column("config", Text, nullable=False),  # JSON: search, filters, sort, columns
    Column("author", String(255)),
    Column("created", String(32)),
    Column("modified", String(32)),
)


# --------------------------------------------------------------------------- helpers


def now_iso() -> str:
    """Timestamp for metadata tables (``2026-10-07T21:30:00``)."""
    return _dt.datetime.now().isoformat(timespec="seconds")


def quote(conn: Connection, name: str) -> str:
    """Always-quoted identifier for the connection's dialect."""
    return conn.dialect.identifier_preparer.quote_identifier(name)


def _pn_index_name(table: str) -> str:
    digest = hashlib.sha1(table.casefold().encode("utf-8")).hexdigest()[:12]
    return f"ix_pn_{digest}"


def is_metadata_table(name: str) -> bool:
    low = name.lower()
    return low.startswith(PF_PREFIX) or low.startswith("sqlite_")


_UNSAFE_NAME_CHARS = frozenset('|[]"')


def unsafe_name_reason(name: str) -> str | None:
    """Why a foreign table/column name cannot become a category/field, or ``None``.

    The names end up in the DbLib (cp1252 INI file, ``[Table]``/``[Field]`` quoting, ``|``
    separated options) and as Altium parameter names: ``| [ ] "``, control characters,
    blanks at the start or end and characters outside Windows-1252 would break or silently
    change them."""
    if not name:
        return "leerer Name"
    if name != name.strip():
        return "Leerzeichen am Anfang oder Ende"
    bad = sorted(set(name) & _UNSAFE_NAME_CHARS)
    if bad:
        return f"unzulässige Zeichen {' '.join(bad)}"
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        return "Steuerzeichen"
    try:
        name.encode("cp1252")
    except UnicodeEncodeError:
        return "Zeichen außerhalb von Windows-1252 (Altium-DbLib)"
    return None


def _skip_unsafe(kind: str, name: str, where: str = "") -> bool:
    """Log and return True if a foreign table/column name must not be adopted."""
    reason = unsafe_name_reason(name)
    if reason is None:
        return False
    log.warning("%s %r%s wird nicht übernommen (%s) – bitte in der Datenbank umbenennen.", kind, name, where, reason)
    return True


def field_from_template(tpl: FieldTemplate, *, common: bool, sort_order: int) -> FieldDef:
    return FieldDef(
        column=tpl.column,
        label=tpl.label,
        kind=tpl.kind,
        unit=tpl.unit,
        options=list(tpl.options),
        required=tpl.required,
        show_on_schematic=tpl.show_on_schematic,
        add_to_design=tpl.add_to_design,
        system=tpl.system,
        common=common,
        grid_width=tpl.grid_width,
        help=tpl.help,
        sort_order=sort_order,
        protected=tpl.column in PROTECTED_COLUMNS,
    )


def common_fields() -> list[FieldDef]:
    return [field_from_template(t, common=True, sort_order=i) for i, t in enumerate(COMMON_FIELDS)]


def category_from_template(tpl: CategoryTemplate, sort_order: int = 0) -> CategoryDef:
    fields = common_fields()
    known = {f.column.casefold() for f in fields}
    for t in tpl.fields:
        if t.column.casefold() in known:
            continue
        fields.append(field_from_template(t, common=False, sort_order=len(fields)))
        known.add(t.column.casefold())
    return CategoryDef(
        table=tpl.table,
        label=tpl.label,
        prefix=tpl.prefix,
        icon=tpl.icon,
        color=tpl.color,
        default_symbol=tpl.default_symbol,
        value_field=tpl.value_field,
        description_template=tpl.description_template,
        comment_template=tpl.comment_template,
        sort_order=sort_order,
        altium_enabled=True,
        fields=fields,
        builtin=True,
    )


def builtin_templates() -> list[CategoryDef]:
    """The built-in category templates (for "Neue Kategorie aus Vorlage")."""
    return [category_from_template(t, sort_order=i * 10) for i, t in enumerate(CATEGORIES)]


# --------------------------------------------------------------------------- DDL


def physical_tables(conn: Connection) -> list[str]:
    return list(inspect(conn).get_table_names())


def physical_views(conn: Connection) -> list[str]:
    return list(inspect(conn).get_view_names())


def physical_columns(conn: Connection, table: str) -> list[ReflectedColumn]:
    return list(inspect(conn).get_columns(table))


def _column_sql(conn: Connection, field: FieldDef) -> str:
    q = quote(conn, field.column)
    if field.column == PART_NUMBER:
        return f"{q} {COLUMN_TYPE} NOT NULL PRIMARY KEY"
    return f"{q} {COLUMN_TYPE}"


def create_pn_index(conn: Connection, table: str) -> None:
    name = quote(conn, _pn_index_name(table))
    if conn.dialect.name == "sqlite":
        conn.exec_driver_sql(
            f"CREATE INDEX IF NOT EXISTS {name} ON {quote(conn, table)} ({quote(conn, PART_NUMBER)} COLLATE NOCASE)"
        )
    else:
        conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {name} ON {quote(conn, table)} (lower({quote(conn, PART_NUMBER)}))")


def drop_pn_index(conn: Connection, table: str) -> None:
    conn.exec_driver_sql(f"DROP INDEX IF EXISTS {quote(conn, _pn_index_name(table))}")


def create_category_table(conn: Connection, table: str, fields: list[FieldDef]) -> None:
    ordered = sorted(fields, key=lambda f: (f.column != PART_NUMBER, f.sort_order))
    if not ordered or ordered[0].column != PART_NUMBER:
        raise SchemaError(f"Kategorie „{table}“: Das Feld „{PART_NUMBER}“ fehlt.")
    cols = ",\n  ".join(_column_sql(conn, f) for f in ordered)
    conn.exec_driver_sql(f"CREATE TABLE {quote(conn, table)} (\n  {cols}\n)")
    create_pn_index(conn, table)


def add_column(conn: Connection, table: str, field: FieldDef) -> None:
    conn.exec_driver_sql(f"ALTER TABLE {quote(conn, table)} ADD COLUMN {quote(conn, field.column)} {COLUMN_TYPE}")


def rename_column(conn: Connection, table: str, old: str, new: str) -> None:
    conn.exec_driver_sql(f"ALTER TABLE {quote(conn, table)} RENAME COLUMN {quote(conn, old)} TO {quote(conn, new)}")


def drop_column(conn: Connection, table: str, column: str) -> None:
    conn.exec_driver_sql(f"ALTER TABLE {quote(conn, table)} DROP COLUMN {quote(conn, column)}")


def drop_table(conn: Connection, table: str) -> None:
    drop_pn_index(conn, table)
    conn.exec_driver_sql(f"DROP TABLE {quote(conn, table)}")


def rename_table(conn: Connection, old: str, new: str) -> None:
    """Rename a table; a change of letter case only (``Mechanical`` -> ``MECHANICAL``)
    goes through a temporary name because SQLite compares table names case-insensitively."""
    drop_pn_index(conn, old)
    if old != new and old.casefold() == new.casefold():
        tmp = f"{PF_PREFIX}tmp_rename"
        conn.exec_driver_sql(f"ALTER TABLE {quote(conn, old)} RENAME TO {quote(conn, tmp)}")
        old = tmp
    conn.exec_driver_sql(f"ALTER TABLE {quote(conn, old)} RENAME TO {quote(conn, new)}")
    create_pn_index(conn, new)


# --------------------------------------------------------------------------- TEXT conversion (schema 2)

# Column types that store text and may be converted to TEXT without changing the meaning
_TEXTLIKE_TYPE = re.compile(
    r"^\s*(?:(?:national\s+)?(?:n?varchar2?|varying\s+character|character\s+varying|n?char|nchar|character|"
    r"native\s+character|text|clob|string))?\s*(?:\(\s*\d+\s*\))?\s*$",
    re.IGNORECASE,
)
_SIZED_TYPE = re.compile(r"\(\s*\d+\s*\)")
# Table-level features a rebuild would lose -> such tables are left alone
_CONSTRAINT_WORDS = re.compile(
    r"\b(?:CHECK|DEFAULT|REFERENCES|UNIQUE|COLLATE|GENERATED|CONSTRAINT|AUTOINCREMENT|AS|STRICT)\b|WITHOUT\s+ROWID",
    re.IGNORECASE,
)
_QUOTED_SQL = re.compile(r'"(?:[^"]|"")*"|\[[^\]]*\]|`(?:[^`]|``)*`|\'(?:[^\']|\'\')*\'')


def _sized_columns(conn: Connection, table: str) -> list[str]:
    """Columns declared with a length (``VARCHAR(n)``, ``CHAR(n)`` …)."""
    out: list[str] = []
    for col in physical_columns(conn, table):
        if getattr(col["type"], "length", None):
            out.append(str(col["name"]))
    return out


def _sqlite_rebuild_as_text(conn: Connection, table: str) -> bool:
    info = conn.exec_driver_sql(f"PRAGMA table_info({quote(conn, table)})").fetchall()
    # (cid, name, type, notnull, dflt_value, pk)
    if not any(_SIZED_TYPE.search(str(r[2] or "")) for r in info):
        return False
    reasons: list[str] = []
    if not all(_TEXTLIKE_TYPE.match(str(r[2] or "")) for r in info):
        reasons.append("Spalten mit Zahlen- oder Sondertypen")
    if any(r[4] is not None for r in info):
        reasons.append("Standardwerte")
    pk_columns = [str(r[1]) for r in sorted(info, key=lambda r: r[5]) if r[5]]
    if len(pk_columns) != 1 or pk_columns[0].casefold() != PART_NUMBER.casefold():
        reasons.append("Primärschlüssel ist nicht „Part Number“")
    create_sql = conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).scalar_one_or_none() or ""
    body = _QUOTED_SQL.sub(" ", create_sql)
    body = body[body.find("(") + 1:] if "(" in body else body
    if _CONSTRAINT_WORDS.search(body):
        reasons.append("Einschränkungen (CHECK/UNIQUE/DEFAULT …)")
    triggers = conn.exec_driver_sql(
        "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)
    ).scalar_one()
    if triggers:
        reasons.append("Trigger")
    if reasons:
        log.info("Tabelle %s bleibt bei VARCHAR (%s) – Altium kürzt dort lange Werte", table, ", ".join(reasons))
        return False
    indexes = [str(sql) for (sql,) in conn.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,)
    )]
    names = ", ".join(quote(conn, str(r[1])) for r in info)
    definitions = []
    for _cid, name, _type, notnull, _default, pk in info:
        definition = f"{quote(conn, str(name))} {COLUMN_TYPE}"
        if notnull:
            definition += " NOT NULL"
        if pk:
            definition += " PRIMARY KEY"
        definitions.append(definition)
    tmp = quote(conn, _TMP_TABLE)
    # No ALTER TABLE ... RENAME: views referencing the table stay valid (same name, same columns).
    conn.exec_driver_sql(f"DROP TABLE IF EXISTS {tmp}")
    conn.exec_driver_sql(f"CREATE TABLE {tmp} AS SELECT * FROM {quote(conn, table)}")
    conn.exec_driver_sql(f"DROP TABLE {quote(conn, table)}")
    conn.exec_driver_sql(f"CREATE TABLE {quote(conn, table)} (\n  " + ",\n  ".join(definitions) + "\n)")
    conn.exec_driver_sql(f"INSERT INTO {quote(conn, table)} ({names}) SELECT {names} FROM {tmp}")
    conn.exec_driver_sql(f"DROP TABLE {tmp}")
    for sql in indexes:
        conn.exec_driver_sql(sql)
    return True


def convert_to_text(conn: Connection, table: str) -> bool:
    """Make every ``VARCHAR(n)``/``CHAR(n)`` column of a category table ``TEXT``
    (Altium truncates sized columns). Returns True if the table was changed.

    SQLite cannot change column types, so the table is rebuilt (data, indexes and
    NOT NULL flags are kept; views stay valid). Tables with features a rebuild would
    lose (constraints, defaults, triggers, non-text columns) are left unchanged. The
    conversion runs in a savepoint: a failure keeps the table as it was."""
    try:
        with conn.begin_nested():
            if conn.dialect.name == "sqlite":
                changed = _sqlite_rebuild_as_text(conn, table)
            else:
                sized = _sized_columns(conn, table)
                for column in sized:
                    conn.exec_driver_sql(
                        f"ALTER TABLE {quote(conn, table)} ALTER COLUMN {quote(conn, column)} TYPE {COLUMN_TYPE}"
                    )
                changed = bool(sized)
    except DBAPIError:
        log.warning("Spaltentypen von %s konnten nicht auf TEXT umgestellt werden", table, exc_info=True)
        return False
    if changed:
        log.info("Spalten der Tabelle %s auf TEXT umgestellt", table)
    return changed


# --------------------------------------------------------------------------- pf_categories / pf_fields


def _category_values(cat: CategoryDef) -> dict[str, Any]:
    return {
        "label": cat.label,
        "prefix": cat.prefix,
        "icon": cat.icon,
        "color": cat.color,
        "default_symbol": cat.default_symbol,
        "value_field": cat.value_field,
        "description_template": cat.description_template,
        "comment_template": cat.comment_template,
        "sort_order": cat.sort_order,
        "altium_enabled": cat.altium_enabled,
        "builtin": cat.builtin,
    }


def insert_category_row(conn: Connection, cat: CategoryDef) -> None:
    now = now_iso()
    conn.execute(insert(pf_categories).values(table_name=cat.table, created=now, modified=now, **_category_values(cat)))


def update_category_row(conn: Connection, table: str, cat: CategoryDef) -> None:
    conn.execute(
        update(pf_categories)
        .where(pf_categories.c.table_name == table)
        .values(table_name=cat.table, modified=now_iso(), **_category_values(cat))
    )


def _field_values(table: str, f: FieldDef) -> dict[str, Any]:
    return {
        "table_name": table,
        "column_name": f.column,
        "label": f.label or f.column,
        "kind": f.kind,
        "unit": f.unit,
        "options": json.dumps(list(f.options), ensure_ascii=False) if f.options else None,
        "required": f.required,
        "show_on_schematic": f.show_on_schematic,
        "add_to_design": f.add_to_design,
        "system": f.system,
        "common": f.common,
        "grid_width": f.grid_width,
        "help": f.help,
        "sort_order": f.sort_order,
        "length": f.length,
    }


def save_fields(conn: Connection, table: str, fields: Iterable[FieldDef]) -> None:
    """Replace all pf_fields rows of a category (sort order = list order, Part Number first)."""
    ordered = sorted(fields, key=lambda f: (f.column != PART_NUMBER, f.sort_order))
    conn.execute(delete(pf_fields).where(pf_fields.c.table_name == table))
    rows = []
    for i, f in enumerate(ordered):
        f.sort_order = i
        rows.append(_field_values(table, f))
    if rows:
        conn.execute(insert(pf_fields), rows)


def _row_to_field(row: Any) -> FieldDef:
    options: list[str] = []
    if row["options"]:
        try:
            parsed = json.loads(row["options"])
            if isinstance(parsed, list):
                options = [str(o) for o in parsed]
        except (TypeError, ValueError):
            log.warning("Ungültige Optionsliste für Feld %s.%s", row["table_name"], row["column_name"])
    return FieldDef(
        column=row["column_name"],
        label=row["label"] or row["column_name"],
        kind=row["kind"] or "text",
        unit=row["unit"],
        options=options,
        required=bool(row["required"]),
        show_on_schematic=bool(row["show_on_schematic"]),
        add_to_design=bool(row["add_to_design"]),
        system=bool(row["system"]),
        common=bool(row["common"]),
        grid_width=row["grid_width"],
        help=row["help"],
        sort_order=int(row["sort_order"] or 0),
        length=row["length"],
        protected=row["column_name"] in PROTECTED_COLUMNS,
    )


def load_categories(conn: Connection) -> dict[str, CategoryDef]:
    """All registered categories (ordered by sort_order, label), keyed by table name."""
    field_rows = conn.execute(
        select(pf_fields).order_by(pf_fields.c.table_name, pf_fields.c.sort_order, pf_fields.c.column_name)
    ).mappings()
    by_table: dict[str, list[FieldDef]] = {}
    for row in field_rows:
        try:
            by_table.setdefault(row["table_name"], []).append(_row_to_field(row))
        except ValueError:
            log.warning("Feld %s.%s übersprungen (ungültige Metadaten)", row["table_name"], row["column_name"])
    cats: dict[str, CategoryDef] = {}
    rows = conn.execute(select(pf_categories).order_by(pf_categories.c.sort_order, pf_categories.c.label)).mappings()
    for row in rows:
        fields = sorted(by_table.get(row["table_name"], []), key=lambda f: (f.column != PART_NUMBER, f.sort_order))
        cats[row["table_name"]] = CategoryDef(
            table=row["table_name"],
            label=row["label"],
            prefix=row["prefix"] or "U",
            icon=row["icon"] or "box",
            color=row["color"] or "#94A3B8",
            default_symbol=row["default_symbol"],
            value_field=row["value_field"],
            description_template=row["description_template"] or "",
            comment_template=row["comment_template"] or "",
            sort_order=int(row["sort_order"] or 0),
            altium_enabled=bool(row["altium_enabled"]),
            builtin=bool(row["builtin"]),
            fields=fields,
        )
    return cats


# --------------------------------------------------------------------------- meta


def get_meta(conn: Connection, key: str) -> str | None:
    """Schema bookkeeping only (bootstrap, migrations) – other modules use :mod:`partforge.db.meta`."""
    return conn.execute(select(pf_meta.c.value).where(pf_meta.c.key == key)).scalar_one_or_none()


def set_meta(conn: Connection, key: str, value: str) -> None:
    """Schema bookkeeping only (bootstrap, migrations) – other modules use :mod:`partforge.db.meta`."""
    exists = conn.execute(select(pf_meta.c.key).where(pf_meta.c.key == key)).first()
    if exists:
        conn.execute(update(pf_meta).where(pf_meta.c.key == key).values(value=value))
    else:
        conn.execute(insert(pf_meta).values(key=key, value=value))


def schema_marker(conn: Connection) -> int | None:
    """SQLite's ``PRAGMA schema_version`` (changes with every DDL of any process)."""
    if conn.dialect.name != "sqlite":
        return None
    return int(conn.exec_driver_sql("PRAGMA schema_version").scalar_one())


# --------------------------------------------------------------------------- adoption / reconciliation


def _canonical_spelling(conn: Connection, table: str, known: dict[str, FieldDef]) -> list[str]:
    """Rename physical columns whose name differs from a known field only in letter case
    (``PART NUMBER`` -> ``Part Number``): PartForge, the DbLib and the other modules use
    the canonical names. SQLite matches identifiers case-insensitively, so foreign SQL
    using the old spelling keeps working. Returns German notes."""
    notes: list[str] = []
    columns = [str(c["name"]) for c in physical_columns(conn, table)]
    present = set(columns)
    for name in columns:
        base = known.get(name.casefold())
        if base is None or name == base.column or base.column in present:
            continue
        rename_column(conn, table, name, base.column)
        present.discard(name)
        present.add(base.column)
        notes.append(f"Spalte „{name}“ in „{table}“ in „{base.column}“ umbenannt (einheitliche Schreibweise).")
    return notes


def adopt_table(conn: Connection, table: str, *, sort_order: int) -> CategoryDef:
    """Register an existing table (created outside PartForge) as a category.

    Known columns get their canonical spelling, sized text columns become TEXT where
    that is safe (:func:`convert_to_text`). Soft length limits: the declared size for
    columns that stay ``VARCHAR(n)`` (Altium truncates there), else the defaults of known
    fields and no limit (``0``) for unknown columns. Columns with names the DbLib cannot
    carry (:func:`unsafe_name_reason`) are not registered (logged)."""
    template = category_by_table(table)
    known: dict[str, FieldDef] = {}
    if template is not None:
        for f in category_from_template(template).fields:
            known[f.column.casefold()] = f
    else:
        for f in common_fields():
            known[f.column.casefold()] = f
    for note in _canonical_spelling(conn, table, known):
        log.info(note)
    convert_to_text(conn, table)
    fields: list[FieldDef] = []
    for i, col in enumerate(physical_columns(conn, table)):
        name = str(col["name"])
        if _skip_unsafe("Spalte", name, f" in „{table}“"):
            continue
        declared = getattr(col["type"], "length", None) or None
        base = known.get(name.casefold())
        if base is not None:
            fields.append(base.model_copy(update={"column": name, "sort_order": i, "length": declared or base.length}))
        else:
            fields.append(FieldDef(column=name, label=name, sort_order=i, length=declared or 0,
                                   protected=name in PROTECTED_COLUMNS))
    if template is not None:
        cat = category_from_template(template, sort_order=sort_order).model_copy(update={"fields": fields, "table": table})
    else:
        cat = CategoryDef(table=table, label=table, sort_order=sort_order, fields=fields, builtin=False,
                          description_template="{Manufacturer Part Number}", comment_template="{Value}")
    insert_category_row(conn, cat)
    save_fields(conn, cat.table, cat.fields)
    create_pn_index(conn, table)
    return cat


def _seed_builtin_categories(conn: Connection) -> None:
    existing = {t.casefold(): t for t in physical_tables(conn)}
    for i, tpl in enumerate(CATEGORIES):
        if tpl.table.casefold() in existing:
            actual = existing[tpl.table.casefold()]
            columns = {str(c["name"]).casefold() for c in physical_columns(conn, actual)}
            if PART_NUMBER.casefold() not in columns:
                log.warning("Tabelle %s ohne Spalte „Part Number“ – Kategorie %s wird nicht angelegt", actual, tpl.table)
                continue
            adopt_table(conn, actual, sort_order=i * 10)
            log.info("Vorhandene Tabelle %s als Kategorie übernommen", tpl.table)
            continue
        cat = category_from_template(tpl, sort_order=i * 10)
        create_category_table(conn, cat.table, cat.fields)
        insert_category_row(conn, cat)
        save_fields(conn, cat.table, cat.fields)


def reconcile(conn: Connection) -> list[str]:
    """Align pf_categories/pf_fields with the physical schema. Returns German change notes.

    * registered category without table -> table re-created from its fields
    * field without column -> column added; column without field -> field registered
      (e.g. ``Supplier 2`` added by Altium's *Edit Supplier Links*)
    * column spelled differently (letter case) -> standard/built-in fields get their
      canonical spelling back, custom fields follow the physical spelling
    * unregistered table with a ``Part Number`` column -> adopted as category
    * foreign tables and columns whose names the DbLib cannot carry (``| [ ] "``, control
      characters, blanks at the start/end, characters outside Windows-1252) are never
      adopted – they are logged and skipped (:func:`unsafe_name_reason`)
    """
    notes: list[str] = []
    cats = load_categories(conn)
    tables = {t.casefold(): t for t in physical_tables(conn)}
    for cat in cats.values():
        actual = tables.get(cat.table.casefold())
        if actual is None:
            create_category_table(conn, cat.table, cat.fields)
            notes.append(f"Tabelle „{cat.table}“ fehlte und wurde neu angelegt.")
            continue
        physical = physical_columns(conn, actual)
        columns = [str(c["name"]) for c in physical]
        declared = {str(c["name"]).casefold(): getattr(c["type"], "length", None) or None for c in physical}
        by_fold = {c.casefold(): c for c in columns}
        changed = False
        fields = list(cat.fields)
        for f in fields:
            real = by_fold.get(f.column.casefold())
            if real is None:
                add_column(conn, actual, f)
                notes.append(f"Spalte „{f.column}“ in „{cat.table}“ ergänzt.")
            elif real != f.column:
                if f.common or f.protected or cat.builtin:
                    rename_column(conn, actual, real, f.column)
                    columns[columns.index(real)] = f.column
                    notes.append(f"Spalte „{real}“ in „{cat.table}“ in „{f.column}“ umbenannt (einheitliche Schreibweise).")
                else:
                    f.column = real
                    changed = True
        known = {f.column.casefold() for f in fields}
        for col in columns:
            if col.casefold() not in known:
                if _skip_unsafe("Spalte", col, f" in „{cat.table}“"):
                    continue
                # external column (e.g. "Supplier 3" from Altium): soft limit = declared size, else none
                fields.append(FieldDef(column=col, label=col, sort_order=len(fields) + 1000,
                                       length=declared.get(col.casefold()) or 0, protected=col in PROTECTED_COLUMNS))
                notes.append(f"Neue Spalte „{col}“ in „{cat.table}“ als Feld übernommen.")
                changed = True
        if changed:
            save_fields(conn, cat.table, fields)
        create_pn_index(conn, actual)
    registered = {c.casefold() for c in cats}
    next_order = (max((c.sort_order for c in cats.values()), default=0) // 10 + 1) * 10
    for fold, name in sorted(tables.items()):
        if fold in registered or is_metadata_table(name):
            continue
        columns = [str(c["name"]) for c in physical_columns(conn, name)]
        if PART_NUMBER.casefold() not in {c.casefold() for c in columns}:
            log.info("Tabelle %s ohne Spalte „Part Number“ wird ignoriert", name)
            continue
        if _skip_unsafe("Tabelle", name):
            continue
        adopt_table(conn, name, sort_order=next_order)
        next_order += 10
        notes.append(f"Tabelle „{name}“ als Kategorie übernommen.")
    for note in notes:
        log.info("Schema-Abgleich: %s", note)
    return notes


def bootstrap(conn: Connection) -> int:
    """Create/migrate the schema (idempotent). Returns the schema version."""
    metadata.create_all(conn, checkfirst=True)
    raw = get_meta(conn, "schema_version")
    version = int(raw) if raw and raw.isdigit() else 0
    if version > SCHEMA_VERSION:
        raise SchemaError(
            f"Die Datenbank stammt aus einer neueren PartForge-Version (Schema {version}, unterstützt {SCHEMA_VERSION}). "
            "Bitte PartForge aktualisieren."
        )
    if version == 0:  # new database: created directly in the current schema
        _seed_builtin_categories(conn)
        set_meta(conn, "created", now_iso())
        version = SCHEMA_VERSION
        set_meta(conn, "schema_version", str(version))
    for target in range(version + 1, SCHEMA_VERSION + 1):
        migration = MIGRATIONS[target]
        log.info("Datenbank-Migration auf Schema %s", target)
        migration(conn)
        set_meta(conn, "schema_version", str(target))
        version = target
    set_meta(conn, "app_version", __version__)
    return version


def _migrate_v2_text_columns(conn: Connection) -> None:
    """Schema 2: category columns ``TEXT`` instead of ``VARCHAR(n)`` (Altium truncates
    VARCHAR values – VERIFIED). Existing soft limits (``pf_fields.length``) are kept."""
    tables = {t.casefold(): t for t in physical_tables(conn)}
    for cat in load_categories(conn).values():
        actual = tables.get(cat.table.casefold())
        if actual is not None:
            convert_to_text(conn, actual)


# Version -> migration function (version 1 is the initial schema created by bootstrap).
MIGRATIONS: dict[int, Callable[[Connection], None]] = {2: _migrate_v2_text_columns}
