"""Change history (``pf_audit``): who changed which part/column when."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import Connection, func, insert, or_, select

from ..domain.text import identity_key
from .core import read
from .models import AuditAction, AuditEntry
from .schema import pf_audit
from .values import PART_NUMBER

log = logging.getLogger(__name__)

# Bookkeeping columns are not part of change diffs (they change with every write).
DIFF_IGNORE = frozenset({"PF Modified", "PF Author"})


def now_text() -> str:
    """Timestamp for the Altium-visible bookkeeping columns (``2026-10-07 21:30:00``)."""
    return _dt.datetime.now().isoformat(sep=" ", timespec="seconds")


def resolve_author(author: str | None) -> str:
    """Explicit author, else the configured author name, else the Windows user."""
    if author and author.strip():
        return author.strip()[:255]
    try:
        from ..config import load_settings

        configured = load_settings().author
        if configured and configured.strip():
            return configured.strip()[:255]
    except Exception:  # noqa: BLE001 - settings are optional here
        log.debug("Einstellungen nicht lesbar, Autor aus Umgebung", exc_info=True)
    return os.environ.get("USERNAME") or os.environ.get("USER") or "PartForge"


def diff(old: Mapping[str, Any] | None, new: Mapping[str, Any] | None, *, ignore: Iterable[str] = DIFF_IGNORE) -> dict[str, list[Any]]:
    """Per-column changes ``{column: [old, new]}`` (empty strings count as None)."""
    old = old or {}
    new = new or {}
    skip = set(ignore)
    changes: dict[str, list[Any]] = {}
    for column in list(dict.fromkeys([*old.keys(), *new.keys()])):
        if column in skip:
            continue
        a = old.get(column) or None
        b = new.get(column) or None
        if a != b:
            changes[column] = [a, b]
    return changes


def entry_row(
    action: AuditAction,
    table: str | None,
    part_number: str | None,
    changes: Mapping[str, Any],
    author: str,
    ts: str | None = None,
) -> dict[str, Any]:
    return {
        "ts": ts or _dt.datetime.now().isoformat(timespec="seconds"),
        "author": author,
        "action": action,
        "table_name": table,
        "part_number": part_number,
        "changes": json.dumps(changes, ensure_ascii=False, default=str),
    }


def record(
    conn: Connection,
    action: AuditAction,
    table: str | None,
    part_number: str | None,
    changes: Mapping[str, Any],
    author: str,
) -> None:
    conn.execute(insert(pf_audit).values(**entry_row(action, table, part_number, changes, author)))


def record_many(conn: Connection, rows: list[dict[str, Any]], *, returning: bool = False) -> list[int]:
    """Insert entries (one statement); ``returning``: their ids in the order of ``rows`` (undo handles)."""
    if not rows:
        return []
    if not returning:
        conn.execute(insert(pf_audit), rows)
        return []
    result = conn.execute(insert(pf_audit).returning(pf_audit.c.id, sort_by_parameter_order=True), rows)
    return [int(i) for i in result.scalars().all()]


def entries_by_id(conn: Connection, ids: Iterable[int]) -> dict[int, AuditEntry]:
    """The entries with these ids (unknown ids are missing from the result)."""
    wanted = sorted({int(i) for i in ids})
    found: dict[int, AuditEntry] = {}
    for i in range(0, len(wanted), 500):
        for row in conn.execute(select(pf_audit).where(pf_audit.c.id.in_(wanted[i:i + 500]))).mappings():
            entry = _to_entry(row)
            found[entry.id] = entry
    return found


def _to_entry(row: Mapping[Any, Any]) -> AuditEntry:
    try:
        changes = json.loads(row["changes"]) if row["changes"] else {}
    except (TypeError, ValueError):
        changes = {"_raw": row["changes"]}
    return AuditEntry(
        id=int(row["id"]),
        ts=str(row["ts"]),
        author=row["author"],
        action=row["action"],
        table=row["table_name"],
        part_number=row["part_number"],
        changes=changes if isinstance(changes, dict) else {"_value": changes},
    )


def history(table: str, part_number: str, *, limit: int = 500) -> list[AuditEntry]:
    """Entries of one part, newest first; follows renames of the part number."""
    names = {part_number}
    entries: dict[int, AuditEntry] = {}
    with read() as conn:
        frontier = [part_number]
        while frontier and len(names) < 50:
            rows = conn.execute(
                select(pf_audit)
                .where(pf_audit.c.table_name == table, pf_audit.c.part_number.in_(frontier))
                .order_by(pf_audit.c.id.desc())
                .limit(limit)
            ).mappings()
            frontier = []
            for row in rows:
                entry = _to_entry(row)
                entries[entry.id] = entry
                rename = entry.changes.get(PART_NUMBER)
                if entry.action == "update" and isinstance(rename, list) and len(rename) == 2:
                    old_name = rename[0]
                    if old_name and old_name not in names:
                        names.add(old_name)
                        frontier.append(old_name)
    return sorted(entries.values(), key=lambda e: e.id, reverse=True)[:limit]


def _pn_key(pn: str) -> str:
    """Same key as ``partforge.db.parts.pn_key`` (:func:`partforge.domain.text.identity_key`)."""
    return identity_key(pn)


def last_deletions(conn: Connection, table: str, part_numbers: Iterable[str]) -> dict[str, AuditEntry]:
    """The newest ``delete`` entry per part number of ``table`` – keyed like ``parts.pn_key`` (exact
    spelling first, then ASCII case-insensitive)."""
    wanted = list(dict.fromkeys(p.strip() for p in part_numbers if p and p.strip()))
    found: dict[str, AuditEntry] = {}

    def keep(rows: Iterable[Mapping[Any, Any]]) -> None:
        for row in rows:
            entry = _to_entry(row)
            key = _pn_key(entry.part_number or "")
            if key and (key not in found or found[key].id < entry.id):
                found[key] = entry

    base = select(pf_audit).where(pf_audit.c.table_name == table, pf_audit.c.action == "delete")
    for i in range(0, len(wanted), 500):
        keep(conn.execute(base.where(pf_audit.c.part_number.in_(wanted[i:i + 500]))).mappings())
    rest = [_pn_key(p) for p in wanted if _pn_key(p) not in found]
    for i in range(0, len(rest), 500):
        keep(conn.execute(base.where(func.lower(pf_audit.c.part_number).in_(rest[i:i + 500]))).mappings())
    return found


def recent(limit: int = 20, *, table: str | None = None, actions: Iterable[str] | None = None) -> list[AuditEntry]:
    """Newest entries (dashboard timeline)."""
    stmt = select(pf_audit).order_by(pf_audit.c.id.desc()).limit(limit)
    if table:
        stmt = stmt.where(pf_audit.c.table_name == table)
    if actions:
        stmt = stmt.where(or_(*[pf_audit.c.action == a for a in actions]))
    with read() as conn:
        return [_to_entry(row) for row in conn.execute(stmt).mappings()]
