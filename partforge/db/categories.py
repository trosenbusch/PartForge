"""Categories: one Altium-visible table per category plus field metadata (pf_categories/pf_fields).

Contract (ARCHITEKTUR.md §4)::

    list_categories() -> list[CategoryDef]; get_category(table) -> CategoryDef   # KeyError
    create_category(CategoryDef) / update_category(table, patch) / delete_category(table)
    add_field(table, FieldDef) / update_field(table, column, patch) / remove_field(table, column)
    on_schema_change(callback)

Every DDL runs in one write transaction together with the metadata update and an
audit entry; afterwards the registered schema-change callbacks run (e.g. "write the
DbLib again"). Schema changes made by other processes (Altium's *Edit Supplier Links*
adds ``Supplier n`` columns) are detected through SQLite's ``schema_version`` and
reconciled automatically.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import Column, MetaData, Table, Text, func, select, update
from sqlalchemy.exc import DBAPIError

from . import audit, core, schema
from .errors import CategoryNotFound, ConflictError, DatabaseBusy, DbError, FieldNotFound, SchemaError, is_lock_error
from .models import CategoryDef, FieldDef
from .schema import PROTECTED_COLUMNS, pf_categories, pf_mpn_templates, pf_saved_views
from .values import PART_NUMBER, template_columns, template_tokens

log = logging.getLogger(__name__)

__all__ = [
    "add_field",
    "builtin_templates",
    "create_category",
    "delete_category",
    "get_category",
    "invalidate_cache",
    "list_categories",
    "on_schema_change",
    "remove_field",
    "reorder_fields",
    "table_for",
    "update_category",
    "update_field",
    "validate_column_name",
    "validate_table_name",
]

_TABLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _\-]{0,63}$")
_PREFIX_RE = re.compile(r"^[A-Za-z]{1,8}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ICON_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,63}$")
_FORBIDDEN_COLUMN_CHARS = frozenset('[]"\'`|=.{}$:;\\')
_PLACEHOLDER_ANY = re.compile(r"\{([^{}:]+?)(?::[A-Za-z]+)?\}")

CATEGORY_PATCH_KEYS = frozenset(
    {
        "table",
        "label",
        "prefix",
        "icon",
        "color",
        "default_symbol",
        "value_field",
        "description_template",
        "comment_template",
        "sort_order",
        "altium_enabled",
    }
)
FIELD_PATCH_KEYS = frozenset(
    {
        "column",
        "label",
        "kind",
        "unit",
        "options",
        "required",
        "show_on_schematic",
        "add_to_design",
        "system",
        "grid_width",
        "help",
        "sort_order",
        "length",
    }
)
PROTECTED_PATCH_KEYS = frozenset({"label", "help", "grid_width", "sort_order", "required", "show_on_schematic", "length"})
_MARKER_CHECK_INTERVAL = 1.0  # seconds between checks for external schema changes
MAX_SOFT_LENGTH = 100_000  # upper bound of FieldDef.length (soft limit; 0 = unlimited)


# --------------------------------------------------------------------------- callbacks

_callbacks: list[Callable[[], None]] = []
_callbacks_lock = threading.Lock()


def on_schema_change(callback: Callable[[], None]) -> Callable[[], None]:
    """Register a callback that runs after every schema change (after commit).

    Returns a function that unregisters the callback. Registering the same callback
    twice has no effect. Exceptions in callbacks are logged, never propagated.
    """
    with _callbacks_lock:
        if callback not in _callbacks:
            _callbacks.append(callback)

    def unsubscribe() -> None:
        with _callbacks_lock:
            if callback in _callbacks:
                _callbacks.remove(callback)

    return unsubscribe


def notify_schema_change() -> None:
    """Run all schema-change callbacks (used after DDL, reconciliation and restores)."""
    with _callbacks_lock:
        callbacks = list(_callbacks)
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001 - one failing listener must not break the change
            log.exception("Schema-Callback %r fehlgeschlagen", callback)


# --------------------------------------------------------------------------- cache


class _Cache:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.cats: dict[str, CategoryDef] | None = None
        self.engine_id: int | None = None
        self.marker: int | None = None
        self.checked: float = 0.0
        self.tables: dict[tuple[Any, ...], Table] = {}


_cache = _Cache()


def invalidate_cache() -> None:
    """Forget cached metadata (after DDL, restore, open/close)."""
    with _cache.lock:
        _cache.cats = None
        _cache.marker = None
        _cache.engine_id = None
        _cache.checked = 0.0
        _cache.tables.clear()


def _reload() -> dict[str, CategoryDef]:
    """Load metadata into the cache (caller holds ``_cache.lock``, never the write lock order reversed)."""
    with core.read() as conn:
        cats = schema.load_categories(conn)
        marker = schema.schema_marker(conn)
    _cache.cats = cats
    _cache.marker = marker
    _cache.engine_id = id(core.get_engine())
    _cache.checked = time.monotonic()
    return cats


def _external_change() -> bool:
    """True if another process (or thread) changed the SQLite schema since the last load."""
    if core.get_state().kind != "sqlite" or core.in_write_transaction():
        return False
    now = time.monotonic()
    if now - _cache.checked < _MARKER_CHECK_INTERVAL:
        return False
    _cache.checked = now
    with core.read() as conn:
        marker = schema.schema_marker(conn)
    return marker != _cache.marker


def _categories() -> dict[str, CategoryDef]:
    """Cached metadata. Lock order: the write lock is never requested while holding
    ``_cache.lock`` (a writer thread may need the cache lock inside its transaction)."""
    state = core.get_state()
    with _cache.lock:
        cats = _cache.cats if _cache.engine_id == id(state.engine) else None
    if core.in_write_transaction():
        if cats is not None:
            return cats
        with core.read() as conn:  # joins the open transaction; may be uncommitted -> not cached
            return schema.load_categories(conn)
    reconciled = False
    if cats is not None:
        if not _external_change():
            return cats
        if core.in_read():
            # Reconciling needs a write transaction, which must not start inside an open read
            # (lock upgrade). Serve fresh metadata uncached so the change is detected again later.
            with core.read() as conn:
                return schema.load_categories(conn)
        with core.connect() as conn:
            reconciled = bool(schema.reconcile(conn))
    with _cache.lock:
        cats = _reload()
    if reconciled:
        notify_schema_change()
    return cats


def _resolve(cats: Mapping[str, CategoryDef], table: str) -> CategoryDef:
    if table in cats:
        return cats[table]
    folded = (table or "").casefold()
    for name, cat in cats.items():
        if name.casefold() == folded:
            return cat
    raise CategoryNotFound(table)


def table_for(cat: CategoryDef) -> Table:
    """SQLAlchemy Core table of a category (cached; identifiers always quoted; all columns TEXT)."""
    key = (cat.table, tuple(f.column for f in cat.fields))
    with _cache.lock:
        cached = _cache.tables.get(key)
        if cached is not None:
            return cached
        columns = [Column(f.column, Text(), primary_key=f.column == PART_NUMBER, quote=True) for f in cat.fields]
        table = Table(cat.table, MetaData(), *columns, quote=True)
        _cache.tables[key] = table
        return table


# --------------------------------------------------------------------------- queries


def list_categories(*, with_counts: bool = True) -> list[CategoryDef]:
    """All categories in display order; ``part_count`` filled when ``with_counts``."""
    cats = [c.model_copy(deep=True) for c in _categories().values()]
    if with_counts and cats:
        with core.read() as conn:
            for cat in cats:
                try:
                    cat.part_count = int(conn.execute(select(func.count()).select_from(table_for(cat))).scalar_one())
                except DBAPIError:
                    log.warning("Bauteile in %s konnten nicht gezählt werden", cat.table, exc_info=True)
                    cat.part_count = None
    return cats


def get_category(table: str) -> CategoryDef:
    """One category (table name case-insensitive). Raises :class:`KeyError` (CategoryNotFound)."""
    return _resolve(_categories(), table).model_copy(deep=True)


def builtin_templates() -> list[CategoryDef]:
    """Built-in category templates (also for categories that were deleted)."""
    return schema.builtin_templates()


# --------------------------------------------------------------------------- validation


def validate_table_name(name: str, *, existing: Iterable[str] = ()) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise SchemaError("Der Tabellenname darf nicht leer sein.")
    if not _TABLE_RE.match(cleaned):
        raise SchemaError(
            f"Ungültiger Tabellenname „{cleaned}“: erlaubt sind Buchstaben A–Z (ohne Umlaute), Ziffern, Leerzeichen, "
            "„-“ und „_“; der Name muss mit einem Buchstaben beginnen und darf höchstens 64 Zeichen lang sein."
        )
    if schema.is_metadata_table(cleaned):
        raise SchemaError("Tabellennamen, die mit „pf_“ oder „sqlite_“ beginnen, sind für PartForge reserviert.")
    folded = cleaned.casefold()
    if any(folded == e.casefold() for e in existing):
        raise ConflictError(f"Eine Tabelle „{cleaned}“ gibt es bereits in der Datenbank.")
    return cleaned


def validate_column_name(name: str, *, allow_reserved: bool = False) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise SchemaError("Der Spaltenname darf nicht leer sein.")
    if len(cleaned) > 64:
        raise SchemaError(f"Der Spaltenname „{cleaned}“ ist zu lang (höchstens 64 Zeichen).")
    if not cleaned.isascii() or not cleaned.isprintable():
        raise SchemaError(
            f"Der Spaltenname „{cleaned}“ enthält Umlaute oder Sonderzeichen. Spaltennamen werden zu Altium-Parametern "
            "und müssen ASCII sein (die deutsche Beschriftung kann frei gewählt werden)."
        )
    bad = sorted(set(cleaned) & _FORBIDDEN_COLUMN_CHARS)
    if bad:
        raise SchemaError(
            f"Der Spaltenname „{cleaned}“ enthält unzulässige Zeichen ({' '.join(bad)}). "
            "Nicht erlaubt sind [ ] \" ' ` | = . { } $ : ; und \\ (sie stören die DbLib bzw. Vorlagen)."
        )
    if not cleaned[0].isalnum():
        raise SchemaError(f"Der Spaltenname „{cleaned}“ muss mit einem Buchstaben oder einer Ziffer beginnen.")
    if not allow_reserved and cleaned.casefold().startswith("pf "):
        raise SchemaError("Spaltennamen, die mit „PF “ beginnen, sind für PartForge-Verwaltungsfelder reserviert.")
    return cleaned


def _validate_templates(cat: CategoryDef) -> None:
    columns = {f.column.casefold() for f in cat.fields}
    problems: list[str] = []
    for label, template in (("Beschreibungsvorlage", cat.description_template), ("Kommentarvorlage", cat.comment_template)):
        unknown = [c for c in template_columns(template or "") if c.casefold() not in columns]
        if unknown:
            problems.append(f"{label}: unbekannte Felder {', '.join('{' + u + '}' for u in unknown)}")
    if cat.value_field and cat.value_field.casefold() not in columns:
        problems.append(f"Wertfeld „{cat.value_field}“ existiert nicht")
    if problems:
        raise SchemaError("Vorlagen ungültig – " + "; ".join(problems) + ".")


def _validate_category_attrs(cat: CategoryDef) -> None:
    if not (cat.label or "").strip():
        raise SchemaError("Die Bezeichnung der Kategorie darf nicht leer sein.")
    if not _PREFIX_RE.match(cat.prefix or ""):
        raise SchemaError(f"Ungültiges Bezeichner-Präfix „{cat.prefix}“ (1–8 Buchstaben, z. B. R, C, U, FB).")
    if cat.color and not _COLOR_RE.match(cat.color):
        raise SchemaError(f"Ungültige Farbe „{cat.color}“ (Format #RRGGBB).")
    if cat.icon and not _ICON_RE.match(cat.icon):
        raise SchemaError(f"Ungültiger Symbolname „{cat.icon}“ (Lucide-Name, z. B. cpu).")


def _clean_field(field: FieldDef) -> FieldDef:
    f = field.model_copy(deep=True)
    f.label = (f.label or "").strip() or f.column
    if f.kind in ("quantity", "range"):
        f.unit = (f.unit or "").strip() or None
    else:
        f.unit = None
    if f.kind == "enum":
        seen: list[str] = []
        for option in f.options:
            text = " ".join(str(option).split())
            if text and text not in seen:
                seen.append(text)
        f.options = seen
    else:
        f.options = []
    if f.length is not None and not 0 <= int(f.length) <= MAX_SOFT_LENGTH:
        raise SchemaError(
            f"Feld „{f.column}“: Höchstlänge {f.length} ist ungültig (0 = unbegrenzt, sonst 1–{MAX_SOFT_LENGTH} Zeichen)."
        )
    if f.grid_width is not None and not 30 <= int(f.grid_width) <= 2000:
        raise SchemaError(f"Feld „{f.column}“: Spaltenbreite {f.grid_width} ist ungültig (30–2000).")
    f.protected = f.column in PROTECTED_COLUMNS
    return f


def _patch_dict(patch: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(patch, BaseModel):
        return patch.model_dump(exclude_unset=True)
    return dict(patch)


def _validated(model: type[CategoryDef] | type[FieldDef], data: dict[str, Any]) -> Any:
    """Validate patched data; pydantic errors become German :class:`SchemaError`s."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors())
        raise SchemaError(f"Ungültige Angaben – {problems}.") from exc


def _strip_placeholders(template: str, column: str) -> str:
    """Remove ``{column}`` from a template together with the text glued to it:
    ``"IC OPAMP {Channels}CH {GBW}"`` -> ``"IC OPAMP {GBW}"`` (a whitespace-separated
    token loses its literal text when its last placeholder goes)."""
    folded = column.casefold()

    def is_target(m: re.Match[str]) -> bool:
        return m.group(1).strip().casefold() == folded

    kept: list[str] = []
    for token in template_tokens(template or ""):
        matches = list(_PLACEHOLDER_ANY.finditer(token))
        if not any(is_target(m) for m in matches):
            kept.append(token)
            continue
        if all(is_target(m) for m in matches):
            continue  # nothing left in this token but literal decoration ("CH", "BIT", "POS")
        kept.append(_PLACEHOLDER_ANY.sub(lambda m: "" if is_target(m) else m.group(0), token))
    return " ".join(kept)


def _rename_placeholders(template: str, old: str, new: str) -> str:
    folded = old.casefold()

    def repl(m: re.Match[str]) -> str:
        if m.group(1).strip().casefold() != folded:
            return m.group(0)
        return m.group(0).replace(m.group(1), new, 1)

    return _PLACEHOLDER_ANY.sub(repl, template or "")


def _db_error(exc: DBAPIError, action: str) -> DbError:
    if is_lock_error(exc):
        return DatabaseBusy(
            f"{action} ist nicht möglich, weil ein anderes Programm die Datenbank gerade sperrt. "
            "Bitte in einigen Sekunden erneut versuchen."
        )
    detail = str(getattr(exc, "orig", exc)) or exc.__class__.__name__
    return SchemaError(f"{action} ist fehlgeschlagen: {detail}. Bitte prüfen, ob Altium oder ein anderes Programm die Tabelle sperrt.")


# --------------------------------------------------------------------------- category DDL


def _schema_audit(conn: Any, table: str, changes: dict[str, Any], author: str) -> None:
    audit.record(conn, "schema", table, None, changes, author)


def _finish_schema_change() -> None:
    invalidate_cache()
    if not core.in_write_transaction():
        notify_schema_change()


def create_category(cat: CategoryDef, *, author: str | None = None) -> CategoryDef:
    """Create a category table. ``COMMON_FIELDS`` are always added first; further
    fields of ``cat.fields`` are appended in order (common columns given there are ignored)."""
    who = audit.resolve_author(author)
    with core.connect() as conn:
        existing = schema.physical_tables(conn) + schema.physical_views(conn)
        name = validate_table_name(cat.table, existing=existing)
        fields = schema.common_fields()
        known = {f.column.casefold() for f in fields}
        for extra in cat.fields:
            column = validate_column_name(extra.column, allow_reserved=extra.column.casefold() in known)
            if column.casefold() in known:
                continue
            f = _clean_field(extra.model_copy(update={"column": column}))
            f.common = False
            f.sort_order = len(fields)
            fields.append(f)
            known.add(column.casefold())
        current = schema.load_categories(conn)
        new_cat = cat.model_copy(
            update={
                "table": name,
                "label": " ".join((cat.label or "").split()) or name,
                "prefix": (cat.prefix or "U").strip().upper(),
                "fields": fields,
                "part_count": None,
                "builtin": bool(cat.builtin),
                "sort_order": cat.sort_order or (max((c.sort_order for c in current.values()), default=0) + 10),
            }
        )
        _validate_category_attrs(new_cat)
        _validate_templates(new_cat)
        try:
            schema.create_category_table(conn, name, fields)
        except DBAPIError as exc:
            raise _db_error(exc, f"Anlegen der Tabelle „{name}“") from exc
        schema.insert_category_row(conn, new_cat)
        schema.save_fields(conn, name, fields)
        _schema_audit(conn, name, {"op": "create_category", "label": new_cat.label,
                                   "fields": [f.column for f in fields]}, who)
    log.info("Kategorie %s angelegt (%d Felder)", name, len(fields))
    _finish_schema_change()
    return get_category(name)


def update_category(table: str, patch: Mapping[str, Any] | BaseModel, *, author: str | None = None) -> CategoryDef:
    """Change category attributes (label, icon, colour, prefix, templates, value field,
    sort order, Altium visibility). Renaming the table is only allowed while it is empty."""
    values = _patch_dict(patch)
    unknown = set(values) - CATEGORY_PATCH_KEYS
    if "fields" in unknown:
        raise SchemaError("Felder bitte über „Feld hinzufügen/ändern/entfernen“ bearbeiten.")
    if unknown:
        raise SchemaError(f"Unbekannte Eigenschaften: {', '.join(sorted(unknown))}.")
    who = audit.resolve_author(author)
    with core.connect() as conn:
        cats = schema.load_categories(conn)
        current = _resolve(cats, table)
        new_name = current.table
        if "table" in values and values["table"] and " ".join(str(values["table"]).split()) != current.table:
            others = [t for t in schema.physical_tables(conn) + schema.physical_views(conn) if t.casefold() != current.table.casefold()]
            new_name = validate_table_name(str(values["table"]), existing=others)
            count = conn.execute(select(func.count()).select_from(table_for(current))).scalar_one()
            if count:
                raise ConflictError(
                    f"Die Tabelle „{current.table}“ enthält {count} Bauteile und kann nicht umbenannt werden – Altium "
                    "speichert den Tabellennamen in platzierten Bauteilen. Bitte stattdessen die Bezeichnung ändern."
                )
        updates = {k: v for k, v in values.items() if k != "table"}
        if "label" in updates:
            updates["label"] = " ".join(str(updates["label"] or "").split())
        if "prefix" in updates and updates["prefix"]:
            updates["prefix"] = str(updates["prefix"]).strip().upper()
        if "value_field" in updates and updates["value_field"]:
            match = current.field(str(updates["value_field"]))
            updates["value_field"] = match.column if match else updates["value_field"]
        candidate: CategoryDef = _validated(CategoryDef, {**current.model_dump(), **updates, "table": new_name})
        _validate_category_attrs(candidate)
        _validate_templates(candidate)
        changes = {k: [getattr(current, k), getattr(candidate, k)] for k in updates if getattr(current, k) != getattr(candidate, k)}
        if new_name != current.table:
            try:
                schema.rename_table(conn, current.table, new_name)
            except DBAPIError as exc:
                raise _db_error(exc, f"Umbenennen der Tabelle „{current.table}“") from exc
            conn.execute(update(pf_saved_views).where(pf_saved_views.c.table_name == current.table).values(table_name=new_name))
            # the user's series templates of the category follow the new name (else they vanish from its wizard)
            conn.execute(update(pf_mpn_templates).where(pf_mpn_templates.c.category == current.table).values(category=new_name))
            changes["table"] = [current.table, new_name]
        if not changes:
            return get_category(current.table)
        schema.update_category_row(conn, current.table, candidate)
        _schema_audit(conn, new_name, {"op": "update_category", **changes}, who)
    _finish_schema_change()
    return get_category(new_name)


def delete_category(table: str, *, author: str | None = None, backup: bool = True) -> str | None:
    """Drop a category table (after an automatic backup). Returns the backup file name."""
    cat = get_category(table)
    backup_name: str | None = None
    if backup:
        from . import backup as _backup

        path = _backup.auto_backup(f"vor_loeschen_{cat.table}")
        backup_name = path.name if path else None
    who = audit.resolve_author(author)
    with core.connect() as conn:
        count = conn.execute(select(func.count()).select_from(table_for(cat))).scalar_one()
        try:
            schema.drop_table(conn, cat.table)
        except DBAPIError as exc:
            raise _db_error(exc, f"Löschen der Tabelle „{cat.table}“") from exc
        conn.execute(pf_categories.delete().where(pf_categories.c.table_name == cat.table))
        conn.execute(pf_saved_views.delete().where(pf_saved_views.c.table_name == cat.table))
        _schema_audit(conn, cat.table, {"op": "delete_category", "label": cat.label, "parts": int(count),
                                        "backup": backup_name}, who)
    log.info("Kategorie %s gelöscht (%d Bauteile, Sicherung %s)", cat.table, count, backup_name)
    _finish_schema_change()
    return backup_name


# --------------------------------------------------------------------------- field DDL


def add_field(table: str, field: FieldDef, *, author: str | None = None) -> CategoryDef:
    """Add a column (``TEXT``) to a category table; it is appended at the end."""
    who = audit.resolve_author(author)
    with core.connect() as conn:
        cat = _resolve(schema.load_categories(conn), table)
        column = validate_column_name(field.column)
        if cat.field(column) is not None:
            raise ConflictError(f"Das Feld „{column}“ gibt es in „{cat.table}“ bereits.")
        f = _clean_field(field.model_copy(update={"column": column}))
        f.common = False
        f.sort_order = len(cat.fields)
        try:
            schema.add_column(conn, cat.table, f)
        except DBAPIError as exc:
            raise _db_error(exc, f"Hinzufügen der Spalte „{column}“") from exc
        schema.save_fields(conn, cat.table, [*cat.fields, f])
        _schema_audit(conn, cat.table, {"op": "add_field", "column": column, "kind": f.kind, "unit": f.unit}, who)
    _finish_schema_change()
    return get_category(cat.table)


def _rename_in_views(conn: Any, table: str, old: str, new: str | None) -> None:
    """Rename (``new``) or drop (``None``) a column in the saved views of this category.
    Global views are left alone – their columns may belong to other categories."""
    rows = conn.execute(
        select(pf_saved_views.c.id, pf_saved_views.c.config).where(pf_saved_views.c.table_name == table)
    ).all()
    for view_id, raw in rows:
        try:
            config = json.loads(raw or "{}")
        except ValueError:
            continue
        changed = False
        columns = [c for c in config.get("columns", []) if isinstance(c, str)]
        new_columns = [new if c == old else c for c in columns if not (c == old and new is None)]
        if new_columns != columns:
            config["columns"] = new_columns
            changed = True
        for key in ("filters", "sort"):
            items = [i for i in config.get(key, []) if isinstance(i, dict)]
            kept = []
            for item in items:
                if item.get("column") == old:
                    changed = True
                    if new is None:
                        continue
                    item = {**item, "column": new}
                kept.append(item)
            config[key] = kept
        if changed:
            conn.execute(update(pf_saved_views).where(pf_saved_views.c.id == view_id).values(config=json.dumps(config, ensure_ascii=False)))


def update_field(table: str, column: str, patch: Mapping[str, Any] | BaseModel, *, author: str | None = None) -> CategoryDef:
    """Change field metadata; ``{"column": "New Name"}`` renames the column (ALTER TABLE RENAME COLUMN)."""
    values = _patch_dict(patch)
    unknown = set(values) - FIELD_PATCH_KEYS
    if unknown:
        raise SchemaError(f"Unbekannte Feldeigenschaften: {', '.join(sorted(unknown))}.")
    who = audit.resolve_author(author)
    renamed_to: str | None = None
    with core.connect() as conn:
        cat = _resolve(schema.load_categories(conn), table)
        current = cat.field(column)
        if current is None:
            raise FieldNotFound(cat.table, column)
        new_column = current.column
        if "column" in values and values["column"] is not None:
            requested = " ".join(str(values["column"]).split())
            if requested != current.column:
                if current.protected or current.common:
                    raise SchemaError(
                        f"Das Feld „{current.column}“ ist ein Standardfeld (Altium-Verknüpfung bzw. Verwaltung) und kann "
                        "nicht umbenannt werden."
                    )
                new_column = validate_column_name(requested)
                clash = cat.field(new_column)
                if clash is not None and clash is not current:
                    raise ConflictError(f"Das Feld „{new_column}“ gibt es in „{cat.table}“ bereits.")
        if current.protected:
            forbidden = {k for k in values if k not in PROTECTED_PATCH_KEYS and k != "column"}
            changed_forbidden = {k for k in forbidden if values[k] != getattr(current, k)}
            if changed_forbidden:
                raise SchemaError(
                    f"Beim geschützten Feld „{current.column}“ können nur Beschriftung, Hilfetext, Breite, Reihenfolge "
                    "und Pflichtfeld geändert werden."
                )
            if current.column == PART_NUMBER and values.get("required") is False:
                raise SchemaError("Die Teilenummer ist immer ein Pflichtfeld.")
        # "length" is a soft limit (columns are TEXT) and may change at any time; None = default
        updates = {k: v for k, v in values.items() if k != "column"}
        updated = _clean_field(_validated(FieldDef, {**current.model_dump(), **updates, "column": new_column}))
        updated.common = current.common
        changes = {k: [getattr(current, k), getattr(updated, k)] for k in updates if getattr(current, k) != getattr(updated, k)}
        if new_column != current.column:
            try:
                schema.rename_column(conn, cat.table, current.column, new_column)
            except DBAPIError as exc:
                raise _db_error(exc, f"Umbenennen der Spalte „{current.column}“") from exc
            changes["column"] = [current.column, new_column]
            renamed_to = new_column
            new_cat = cat.model_copy(
                update={
                    "description_template": _rename_placeholders(cat.description_template, current.column, new_column),
                    "comment_template": _rename_placeholders(cat.comment_template, current.column, new_column),
                    "value_field": new_column if (cat.value_field or "").casefold() == current.column.casefold() else cat.value_field,
                }
            )
            schema.update_category_row(conn, cat.table, new_cat)
            _rename_in_views(conn, cat.table, current.column, new_column)
        if not changes:
            return get_category(cat.table)
        fields = [updated if f.column == current.column else f for f in cat.fields]
        schema.save_fields(conn, cat.table, fields)
        _schema_audit(conn, cat.table, {"op": "update_field", "field": current.column, **changes}, who)
    if renamed_to:
        log.info("Spalte %s.%s umbenannt in %s", cat.table, current.column, renamed_to)
    _finish_schema_change()
    return get_category(cat.table)


def remove_field(table: str, column: str, *, author: str | None = None, backup: bool = True) -> CategoryDef:
    """Drop a column (after an automatic backup). Refused for protected fields
    (Part Number, Altium link fields, bookkeeping)."""
    cat = get_category(table)
    field = cat.field(column)
    if field is None:
        raise FieldNotFound(cat.table, column)
    if field.protected:
        raise SchemaError(
            f"Das Feld „{field.column}“ wird für die Altium-Verknüpfung bzw. die Verwaltung benötigt und kann nicht "
            "entfernt werden."
        )
    if backup:
        from . import backup as _backup

        _backup.auto_backup(f"vor_feld_entfernen_{cat.table}")
    who = audit.resolve_author(author)
    with core.connect() as conn:
        cat = _resolve(schema.load_categories(conn), table)
        field = cat.field(column)
        if field is None:
            raise FieldNotFound(cat.table, column)
        filled = conn.execute(
            select(func.count()).select_from(table_for(cat)).where(
                table_for(cat).c[field.column].is_not(None), table_for(cat).c[field.column] != ""
            )
        ).scalar_one()
        try:
            schema.drop_column(conn, cat.table, field.column)
        except DBAPIError as exc:
            raise _db_error(exc, f"Entfernen der Spalte „{field.column}“") from exc
        schema.save_fields(conn, cat.table, [f for f in cat.fields if f.column != field.column])
        new_cat = cat.model_copy(
            update={
                "description_template": _strip_placeholders(cat.description_template, field.column),
                "comment_template": _strip_placeholders(cat.comment_template, field.column),
                "value_field": None if (cat.value_field or "").casefold() == field.column.casefold() else cat.value_field,
            }
        )
        schema.update_category_row(conn, cat.table, new_cat)
        _rename_in_views(conn, cat.table, field.column, None)
        _schema_audit(conn, cat.table, {"op": "remove_field", "column": field.column, "filled_values": int(filled)}, who)
    _finish_schema_change()
    return get_category(cat.table)


def reorder_fields(table: str, columns: list[str], *, author: str | None = None) -> CategoryDef:
    """Set the display order (grid, forms, DbLib). Unlisted fields keep their relative
    order after the listed ones; ``Part Number`` always stays first."""
    who = audit.resolve_author(author)
    with core.connect() as conn:
        cat = _resolve(schema.load_categories(conn), table)
        ordered: list[FieldDef] = []
        seen: set[str] = set()
        for name in columns:
            f = cat.field(name)
            if f is None:
                raise FieldNotFound(cat.table, name)
            if f.column not in seen:
                ordered.append(f)
                seen.add(f.column)
        ordered += [f for f in cat.fields if f.column not in seen]
        ordered.sort(key=lambda f: f.column != PART_NUMBER)  # stable: Part Number first
        if [f.column for f in ordered] == [f.column for f in cat.fields]:
            return get_category(cat.table)
        for i, f in enumerate(ordered):
            f.sort_order = i
        schema.save_fields(conn, cat.table, ordered)
        _schema_audit(conn, cat.table, {"op": "reorder_fields", "order": [f.column for f in ordered]}, who)
    _finish_schema_change()
    return get_category(cat.table)
