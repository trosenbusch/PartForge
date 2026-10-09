"""Opening and closing the database of a workspace.

:func:`open_database` builds and validates the new engine (WAL, schema migration,
reconciliation, data migrations) **before** it replaces the currently open database: if
the new library cannot be opened, the previous one stays open and usable.

Data migrations run on every open, in the open transaction, each in its own savepoint – a
failing data migration is logged and tried again at the next open; the library still opens:

* **Default symbols**: symbol names of older versions become symbol kind keys
  (:func:`partforge.db.templates.migrate_default_symbols`).
* **Category labels**: built-in labels of older versions ("Quarze & Oszillatoren") get the current
  spelling ("Quarze und Oszillatoren") – only where the label still equals the old built-in text and
  the user never renamed it (:func:`partforge.db.templates.migrate_category_labels`).
* **Schematic texts** (once per library, ``pf_meta`` marker
  :data:`SCHEMATIC_TEXTS_MARKER`): ``Comment`` becomes visible on the schematic, the value
  fields older versions showed (:data:`~partforge.db.templates.LEGACY_VISIBLE_FIELDS`) are
  hidden, comment templates of older versions
  (:data:`~partforge.db.templates.LEGACY_COMMENT_TEMPLATES`) are replaced by the current
  template and the parts whose Comment is still the generated text get the new one. A field
  or template the user changed (other value, or an explicit change in ``pf_audit``) is kept.
* **Moved library** (SQLite): ``pf_meta`` :data:`partforge.db.meta.WORKSPACE_ROOT` remembers
  the folder the library was opened from. Opened from another folder, every absolute link
  into the old folder (``ComponentLink<n>URL`` and every url/path field; letter case and
  slash style do not matter) is moved to the new folder – path fields become
  workspace-relative –, with an audit entry per part. A library of an older version (no
  folder recorded yet) gets its former folder from its datasheet links, if unambiguous: the
  datasheet import links the stored PDF absolutely (``<root>\\<pf_datasheets.file>``).
  PostgreSQL databases are shared by the library folders of several users and are never
  rewritten.

Afterwards the schema-change callbacks run when categories/fields changed (the DbLib is
rewritten) and :data:`partforge.events.PARTS_CHANGED` is emitted when rows changed.
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, select, update
from sqlalchemy.exc import DBAPIError

from .. import events
from ..workspace import Workspace
from . import audit, categories, core, meta, schema, templates
from .errors import DatabaseBusy, DbError, is_lock_error
from .models import CategoryDef, FieldDef
from .values import PART_NUMBER, normalize_cell, render_template, template_columns

log = logging.getLogger(__name__)

__all__ = [
    "MIGRATION_AUTHOR",
    "SCHEMATIC_TEXTS_MARKER",
    "OpenReport",
    "close_database",
    "migrate_data",
    "open_database",
    "relocate_link",
]

#: Author of the audit entries and bookkeeping written by the data migrations.
MIGRATION_AUTHOR = "PartForge"
#: ``pf_meta`` key set once the schematic-text migration ran for a library.
SCHEMATIC_TEXTS_MARKER = "migration_schematic_texts"
COMMENT = "Comment"
_LINK_URL = re.compile(r"^ComponentLink\d+URL$", re.IGNORECASE)
_FILE_URL = re.compile(r"^file:/*", re.IGNORECASE)
_ABSOLUTE = re.compile(r"^(?:[A-Za-z]:|\\\\|//)")  # drive or UNC path
_SEPARATORS = "\\/"


def _open_error(ws: Workspace, exc: DBAPIError) -> DbError:
    target = core.describe_target(ws)
    detail = str(getattr(exc, "orig", exc)).strip() or exc.__class__.__name__
    if ws.settings.db.postgres_url:
        detail = detail.replace(ws.settings.db.postgres_url, core.mask_url(ws.settings.db.postgres_url))
    if is_lock_error(exc):
        return DatabaseBusy(
            f"Die Datenbank „{target}“ konnte nicht geöffnet werden, weil ein anderes Programm sie gerade sperrt "
            "(z. B. ein laufender Schreibvorgang). Bitte in einigen Sekunden erneut versuchen."
        )
    return DbError(f"Die Datenbank „{target}“ konnte nicht geöffnet werden: {detail}")


def open_database(ws: Workspace) -> None:
    """Bind the workspace database: create/migrate the schema, seed the built-in
    categories on first use, reconcile metadata with the physical tables and run the
    data migrations (module docstring).

    On failure (corrupt file, newer schema, lock, missing driver …) the previously
    open database – if any – stays open; the new engine is discarded."""
    with core.write_lock():
        state = core.create_engine_for(ws)
        try:
            with state.engine.connect() as conn:
                conn.execution_options(pf_write=True)
                with conn.begin():
                    version = schema.bootstrap(conn)
                    notes = schema.reconcile(conn)
                    report = migrate_data(conn, ws, kind=state.kind)
        except DBAPIError as exc:
            state.engine.dispose()
            raise _open_error(ws, exc) from exc
        except BaseException:
            state.engine.dispose()
            raise
        previous = core.install_state(state)
        categories.invalidate_cache()
    if previous is not None and previous.engine is not state.engine:
        core.dispose_state(previous)
    log.info(
        "Datenbank geöffnet: %s (%s, Schema %s%s%s)",
        core.describe_target(ws),
        state.journal_mode or state.kind,
        version,
        f", {len(notes)} Abgleich-Änderungen" if notes else "",
        f", {len(report.notes)} Datenmigrationen" if report.notes else "",
    )
    _announce(report)


def close_database() -> None:
    """Dispose the engine (no-op if nothing is open)."""
    with core.write_lock():
        previous = core.install_state(None)
        categories.invalidate_cache()
    if previous is not None:
        core.dispose_state(previous)
        log.info("Datenbank geschlossen: %s", previous.ws.root)


# --------------------------------------------------------------------------- data migrations


@dataclass
class OpenReport:
    """What the data migrations of one open changed."""

    notes: list[str] = field(default_factory=list)  # German, also logged
    schema_changed: bool = False  # fields/categories changed: the DbLib must be rewritten
    tables: set[str] = field(default_factory=set)  # category tables with changed rows
    parts: int = 0  # changed rows

    def merge(self, other: OpenReport) -> None:
        self.notes += other.notes
        self.schema_changed = self.schema_changed or other.schema_changed
        self.tables |= other.tables
        self.parts += other.parts


Step = Callable[[Connection, Workspace, str, OpenReport], None]


def migrate_data(conn: Connection, ws: Workspace, *, kind: str) -> OpenReport:
    """Run the data migrations inside the caller's open transaction (module docstring).

    Each step runs in a savepoint: a failing step is rolled back and logged, the others and
    the open itself go on (the step is tried again at the next open)."""
    report = OpenReport()
    steps: tuple[tuple[str, Step], ...] = (
        ("Standardsymbole der Kategorien", _migrate_default_symbols),
        ("Bezeichnungen der Kategorien", _migrate_category_labels),
        ("Schaltplan-Texte", _migrate_schematic_texts),
        ("Verweise des Bibliotheksordners", _relocate_links),
    )
    for label, step in steps:
        partial = OpenReport()
        try:
            with conn.begin_nested():
                step(conn, ws, kind, partial)
        except Exception:  # noqa: BLE001 - the library must still open; retried at the next open
            log.exception("Datenmigration „%s“ für %s fehlgeschlagen – wird beim nächsten Öffnen erneut versucht",
                          label, ws.root)
            continue
        report.merge(partial)
    return report


def _announce(report: OpenReport) -> None:
    """Notify listeners after the open (outside the write lock)."""
    if report.schema_changed:
        categories.notify_schema_change()  # e.g. the DbLib auto-writer: new VisibleOnAdd flags
    if report.parts:
        table = next(iter(report.tables)) if len(report.tables) == 1 else None
        events.emit(events.PARTS_CHANGED, table, False)


def _migrate_default_symbols(conn: Connection, _ws: Workspace, _kind: str, report: OpenReport) -> None:
    report.notes += templates.migrate_default_symbols(conn)


def _migrate_category_labels(conn: Connection, _ws: Workspace, _kind: str, report: OpenReport) -> None:
    # labels are PartForge metadata (not in the DbLib): no schema change for Altium
    report.notes += templates.migrate_category_labels(conn, author=MIGRATION_AUTHOR)


# --- schematic texts ------------------------------------------------------------------------


@dataclass
class _Explicit:
    """Changes the user made through PartForge (from ``pf_audit``) – never migrated."""

    visibility: set[tuple[str, str]] = field(default_factory=set)  # (table, column), casefolded
    comment_templates: set[str] = field(default_factory=set)  # tables, casefolded


def _explicit_changes(conn: Connection) -> _Explicit:
    explicit = _Explicit()
    rows = conn.execute(select(schema.pf_audit.c.table_name, schema.pf_audit.c.changes)
                        .where(schema.pf_audit.c.action == "schema"))
    for table, raw in rows:
        try:
            changes = json.loads(raw or "{}")
        except (TypeError, ValueError):
            continue
        if not table or not isinstance(changes, dict):
            continue
        folded = str(table).casefold()
        op = changes.get("op")
        if op == "update_field" and "show_on_schematic" in changes:
            names: list[Any] = [changes.get("field")]
            if isinstance(changes.get("column"), list):
                names += changes["column"]
            explicit.visibility.update((folded, n.casefold()) for n in names if isinstance(n, str))
        elif op == "update_category" and "comment_template" in changes:
            explicit.comment_templates.add(folded)
    return explicit


def _visibility_updates(cat: CategoryDef, template: templates.CategoryTemplate | None,
                        explicit: _Explicit) -> list[tuple[FieldDef, bool]]:
    """``(field, new show_on_schematic)`` for the fields still at the defaults of older versions."""
    legacy = {c.casefold() for c in templates.LEGACY_VISIBLE_FIELDS.get(template.table, ())} if template else set()
    out: list[tuple[FieldDef, bool]] = []
    for f in cat.fields:
        folded = f.column.casefold()
        if (cat.table.casefold(), folded) in explicit.visibility:
            continue
        if folded == COMMENT.casefold() and not f.show_on_schematic:
            out.append((f, True))
        elif folded in legacy and f.show_on_schematic:
            out.append((f, False))
    return out


def _comment_template_update(cat: CategoryDef, template: templates.CategoryTemplate | None,
                             explicit: _Explicit) -> str | None:
    """The current comment template for a category still using one of an older version."""
    if template is None or cat.table.casefold() in explicit.comment_templates or cat.field(COMMENT) is None:
        return None
    if (cat.comment_template or "") not in templates.LEGACY_COMMENT_TEMPLATES.get(template.table, ()):
        return None
    new = template.comment_template
    if new == cat.comment_template or any(cat.field(c) is None for c in template_columns(new)):
        return None  # a referenced field was removed or renamed: keep the template
    return new


def _bookkeeping(cat: CategoryDef, now: str) -> dict[str, str]:
    values = {"PF Modified": now, "PF Author": MIGRATION_AUTHOR}
    return {f.column: values[f.column] for f in cat.fields if f.column in values}


def _rerender_comments(conn: Connection, cat: CategoryDef, old_template: str, new_template: str) -> int:
    """Re-render the Comments that still show the text of ``old_template`` (rule of
    :func:`partforge.db.parts.update_part`: empty or equal to the generated text)."""
    table = categories.table_for(cat)
    fields = {f.column: f for f in cat.fields}
    column = cat.field(COMMENT).column  # type: ignore[union-attr]  (checked by the caller)
    now = audit.now_text()
    bookkeeping = _bookkeeping(cat, now)
    items: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for raw in conn.execute(select(table)).mappings():
        row = {str(k): v for k, v in raw.items()}
        current = row.get(column)
        if current and current != render_template(old_template, row, fields):
            continue  # written by hand: kept
        new = render_template(new_template, row, fields) or None
        if new == (current or None):
            continue
        pk = str(row[PART_NUMBER])
        items.append({"pf__pk": pk, "pf__comment": new, **{f"pf__b{i}": v for i, v in enumerate(bookkeeping.values())}})
        audit_rows.append(audit.entry_row("bulk_update", cat.table, pk, {column: [current or None, new]},
                                          MIGRATION_AUTHOR))
    if items:
        values: dict[str, Any] = {column: bindparam("pf__comment")}
        values.update({col: bindparam(f"pf__b{i}") for i, col in enumerate(bookkeeping)})
        stmt = update(table).where(table.c[PART_NUMBER] == bindparam("pf__pk")).values(values)
        conn.execute(stmt, items)
        audit.record_many(conn, audit_rows)
    return len(items)


def _migrate_schematic_texts(conn: Connection, _ws: Workspace, _kind: str, report: OpenReport) -> None:
    if meta.get_meta(SCHEMATIC_TEXTS_MARKER, conn=conn) is not None:
        return
    explicit = _explicit_changes(conn)
    for cat in schema.load_categories(conn).values():
        # value fields and comment templates only of categories made from a built-in template
        template = templates.template_for(cat.table, cat.columns, builtin=True) if cat.builtin else None
        changes: dict[str, Any] = {}
        details: list[str] = []
        visibility = _visibility_updates(cat, template, explicit)
        for f, visible in visibility:
            conn.execute(update(schema.pf_fields)
                         .where(schema.pf_fields.c.table_name == cat.table, schema.pf_fields.c.column_name == f.column)
                         .values(show_on_schematic=visible))
        if visibility:
            changes["show_on_schematic"] = {f.column: [not visible, visible] for f, visible in visibility}
            shown = [f.column for f, visible in visibility if visible]
            hidden = [f.column for f, visible in visibility if not visible]
            if shown:
                details.append(f"im Schaltplan sichtbar: {', '.join(shown)}")
            if hidden:
                details.append(f"ausgeblendet: {', '.join(hidden)}")
        new_template = _comment_template_update(cat, template, explicit)
        if new_template is not None:
            conn.execute(update(schema.pf_categories).where(schema.pf_categories.c.table_name == cat.table)
                         .values(comment_template=new_template, modified=schema.now_iso()))
            changes["comment_template"] = [cat.comment_template, new_template]
            count = _rerender_comments(conn, cat, cat.comment_template, new_template)
            details.append(f"Kommentarvorlage „{cat.comment_template}“ → „{new_template}“"
                           + (f" ({count} Bauteile angepasst)" if count else ""))
            if count:
                changes["parts"] = count
                report.tables.add(cat.table)
                report.parts += count
        if changes:
            audit.record(conn, "schema", cat.table, None, {"op": "migrate_schematic_texts", **changes}, MIGRATION_AUTHOR)
            note = f"Kategorie „{cat.table}“: {'; '.join(details)}."
            report.notes.append(note)
            report.schema_changed = True
            log.info("Datenmigration: %s", note)
    meta.set_meta(SCHEMATIC_TEXTS_MARKER, "1", conn=conn)


# --- moved library folder -------------------------------------------------------------------


def _strip_separators(path: str) -> str:
    return path.rstrip(_SEPARATORS)


def _folder_key(path: str) -> str:
    return _strip_separators(path.strip().replace("/", "\\")).casefold()


def relocate_link(value: str, old_root: str, new_root: str) -> str | None:
    """``value`` moved from the folder ``old_root`` to ``new_root``, or ``None`` when it does
    not point into ``old_root``.

    Letter case and slash style do not matter (``C:/Libs/Bib/x.pdf`` is inside
    ``C:\\Libs\\Bib``); the value keeps its slash style and a ``file:`` URL prefix. Percent-encoded
    ``file:`` URLs are not recognised."""
    if not value or not old_root or not new_root:
        return None
    match = _FILE_URL.match(value)
    prefix = match.group(0) if match else ""
    rest = value[len(prefix):]
    old = _strip_separators(old_root.strip())
    if not old or len(rest) < len(old):
        return None
    head, tail = rest[: len(old)], rest[len(old):]
    if head.replace("/", "\\").casefold() != old.replace("/", "\\").casefold():
        return None
    if tail and tail[0] not in _SEPARATORS:
        return None  # "C:\Libs\Bibliothek2" is not inside "C:\Libs\Bib"
    used = [ch for ch in head + tail[:1] if ch in _SEPARATORS]
    separator = used[0] if used else "\\"
    new = _strip_separators(new_root.strip()).replace("\\", separator).replace("/", separator)
    return prefix + new + tail


def _inside(path: Path, root: Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(root)
    except (OSError, ValueError):
        return False


def _link_fields(cat: CategoryDef) -> list[FieldDef]:
    return [f for f in cat.fields if f.kind in ("url", "path") or _LINK_URL.match(f.column)]


def _move_links(conn: Connection, old_root: str, ws: Workspace, report: OpenReport) -> tuple[int, int]:
    """Rewrite the links into ``old_root``; returns (values, parts) changed."""
    new_root = str(ws.root)
    now = audit.now_text()
    values_changed = 0
    parts_changed = 0
    for cat in schema.load_categories(conn).values():
        link_fields = _link_fields(cat)
        if not link_fields:
            continue
        table = categories.table_for(cat)
        bookkeeping = _bookkeeping(cat, now)
        audit_rows: list[dict[str, Any]] = []
        columns = [table.c[PART_NUMBER], *(table.c[f.column] for f in link_fields)]
        for row in conn.execute(select(*columns)).all():
            changes: dict[str, list[Any]] = {}
            for f, value in zip(link_fields, row[1:]):
                if not isinstance(value, str) or not value:
                    continue
                moved = relocate_link(value, old_root, new_root)
                if moved is None:
                    continue
                if f.kind == "path":  # canonical form of path fields: workspace-relative
                    moved = normalize_cell(f, moved, ws_root=ws.root).value or moved
                if moved != value:
                    changes[f.column] = [value, moved]
            if not changes:
                continue
            pk = str(row[0])
            conn.execute(update(table).where(table.c[PART_NUMBER] == row[0])
                         .values({**{col: new for col, (_old, new) in changes.items()}, **bookkeeping}))
            audit_rows.append(audit.entry_row("bulk_update", cat.table, pk, changes, MIGRATION_AUTHOR))
            values_changed += len(changes)
        if audit_rows:
            audit.record_many(conn, audit_rows)
            parts_changed += len(audit_rows)
            report.tables.add(cat.table)
    report.parts += parts_changed
    return values_changed, parts_changed


def _datasheet_prefix(value: str, files: set[str]) -> str | None:
    """The absolute folder in front of a stored datasheet's workspace-relative path in a link
    (``C:\\Alt\\Bib\\Datasheets\\x_1234abcd.pdf`` -> ``C:\\Alt\\Bib``), or ``None``."""
    match = _FILE_URL.match(value)
    rest = value[len(match.group(0)):] if match else value
    normalized = rest.replace("/", "\\")
    folded = normalized.casefold()
    for i, ch in enumerate(normalized):
        if ch == "\\" and folded[i + 1:] in files:
            prefix = rest[:i]
            return prefix if _ABSOLUTE.match(prefix) else None
    return None


def _inferred_root(conn: Connection, current: str) -> str | None:
    """Former folder of a library that has no stored root yet (created before PartForge kept
    it), from its datasheet links: the datasheet import links the stored PDF absolutely
    (``<root>\\<pf_datasheets.file>``). Only an unambiguous folder other than ``current`` counts."""
    files = {str(f).replace("/", "\\").lstrip("\\").casefold()
             for (f,) in conn.execute(select(schema.pf_datasheets.c.file)) if f}
    if not files:
        return None
    found: dict[str, str] = {}
    for cat in schema.load_categories(conn).values():
        columns = [f.column for f in cat.fields if f.kind == "url" or _LINK_URL.match(f.column)]
        if not columns:
            continue
        table = categories.table_for(cat)
        for row in conn.execute(select(*(table.c[c] for c in columns))):
            for value in row:
                prefix = _datasheet_prefix(value, files) if isinstance(value, str) and value else None
                if prefix is not None:
                    found.setdefault(_folder_key(prefix), prefix)
    found.pop(_folder_key(current), None)
    if len(found) > 1:
        log.warning("Datenblatt-Verweise zeigen in mehrere frühere Bibliotheksordner (%s) – sie werden nicht "
                    "automatisch angepasst.", ", ".join(sorted(found.values())))
        return None
    return next(iter(found.values()), None)


def _relocate_links(conn: Connection, ws: Workspace, kind: str, report: OpenReport) -> None:
    if kind != "sqlite" or not _inside(ws.sqlite_path, ws.root):
        return  # PostgreSQL: one database for the library folders of several users
    current = str(ws.root)
    stored = meta.get_meta(meta.WORKSPACE_ROOT, conn=conn)
    old = (stored or "").strip()
    if not old:  # library of an older version: the folder was never recorded
        old = _inferred_root(conn, current) or ""
        if old:
            log.info("Früherer Bibliotheksordner aus den Datenblatt-Verweisen erkannt: „%s“", old)
    if old and _folder_key(old) != _folder_key(current):
        values, count = _move_links(conn, old, ws, report)
        if count:
            note = (f"Bibliotheksordner verschoben („{old}“ → „{current}“): {values} Verweise in {count} "
                    "Bauteilen angepasst.")
        else:
            note = f"Bibliotheksordner verschoben („{old}“ → „{current}“): keine absoluten Verweise anzupassen."
        report.notes.append(note)
        log.info(note)
    if stored != current:
        meta.set_meta(meta.WORKSPACE_ROOT, current, conn=conn)
