"""Saved grid views (``pf_saved_views``): name + search, filters, sort and visible columns."""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, insert, or_, select, update

from . import audit, categories, core
from .errors import NotFoundError, SchemaError
from .models import SavedView
from .schema import now_iso, pf_saved_views

log = logging.getLogger(__name__)

__all__ = ["create_view", "delete_view", "get_view", "list_views", "update_view"]

_PATCH_KEYS = frozenset({"name", "table", "search", "filters", "sort", "columns"})


class ViewNotFound(NotFoundError):
    def __init__(self, view_id: int) -> None:
        super().__init__(f"Gespeicherte Ansicht {view_id} nicht gefunden.")
        self.view_id = view_id


def _to_view(row: Mapping[Any, Any]) -> SavedView:
    try:
        config = json.loads(row["config"] or "{}")
    except ValueError:
        config = {}
    try:
        return SavedView(
            id=int(row["id"]),
            name=row["name"],
            table=row["table_name"],
            search=config.get("search"),
            filters=config.get("filters") or [],
            sort=config.get("sort") or [],
            columns=config.get("columns") or [],
            created=row["created"],
            modified=row["modified"],
            author=row["author"],
        )
    except ValidationError:
        log.warning("Gespeicherte Ansicht %s hat eine ungültige Konfiguration", row["id"])
        return SavedView(id=int(row["id"]), name=row["name"], table=row["table_name"], created=row["created"],
                         modified=row["modified"], author=row["author"])


def _validate(view: SavedView) -> SavedView:
    name = " ".join((view.name or "").split())
    if not name:
        raise SchemaError("Die Ansicht braucht einen Namen.")
    if len(name) > 255:
        raise SchemaError("Der Name der Ansicht ist zu lang (höchstens 255 Zeichen).")
    table = view.table
    if table:
        cat = categories.get_category(table)
        table = cat.table
        unknown = [c for c in [*(f.column for f in view.filters), *(s.column for s in view.sort), *view.columns]
                   if cat.field(c) is None]
        if unknown:
            raise SchemaError(f"Unbekannte Felder in der Ansicht: {', '.join(dict.fromkeys(unknown))}.")
        view = view.model_copy(update={
            "filters": [f.model_copy(update={"column": cat.field(f.column).column}) for f in view.filters],  # type: ignore[union-attr]
            "sort": [s.model_copy(update={"column": cat.field(s.column).column}) for s in view.sort],  # type: ignore[union-attr]
            "columns": [cat.field(c).column for c in view.columns],  # type: ignore[union-attr]
        })
    return view.model_copy(update={"name": name, "table": table or None, "search": (view.search or "").strip() or None})


def _config(view: SavedView) -> str:
    return json.dumps(
        {
            "search": view.search,
            "filters": [f.model_dump() for f in view.filters],
            "sort": [s.model_dump() for s in view.sort],
            "columns": list(view.columns),
        },
        ensure_ascii=False,
        default=str,
    )


def list_views(table: str | None = None) -> list[SavedView]:
    """Views of a category plus the global ones (``table=None`` -> all views)."""
    stmt = select(pf_saved_views).order_by(pf_saved_views.c.name, pf_saved_views.c.id)
    if table:
        canonical = categories.get_category(table).table
        stmt = stmt.where(or_(pf_saved_views.c.table_name == canonical, pf_saved_views.c.table_name.is_(None)))
    with core.read() as conn:
        return [_to_view(row) for row in conn.execute(stmt).mappings()]


def get_view(view_id: int) -> SavedView:
    with core.read() as conn:
        row = conn.execute(select(pf_saved_views).where(pf_saved_views.c.id == view_id)).mappings().first()
    if row is None:
        raise ViewNotFound(view_id)
    return _to_view(row)


def create_view(view: SavedView, *, author: str | None = None) -> SavedView:
    clean = _validate(view)
    now = now_iso()
    with core.connect() as conn:
        result = conn.execute(
            insert(pf_saved_views).values(name=clean.name, table_name=clean.table, config=_config(clean),
                                          author=audit.resolve_author(author), created=now, modified=now)
        )
        key = result.inserted_primary_key
        if key is None:  # pragma: no cover - every supported dialect returns the key
            raise RuntimeError("Die neue Ansicht hat keine ID erhalten.")
        new_id = int(key[0])
    return get_view(new_id)


def update_view(view_id: int, patch: Mapping[str, Any] | BaseModel) -> SavedView:
    values = patch.model_dump(exclude_unset=True) if isinstance(patch, BaseModel) else dict(patch)
    unknown = set(values) - _PATCH_KEYS
    if unknown:
        raise SchemaError(f"Unbekannte Eigenschaften der Ansicht: {', '.join(sorted(unknown))}.")
    current = get_view(view_id)
    try:
        merged = SavedView.model_validate({**current.model_dump(), **values})
    except ValidationError as exc:
        raise SchemaError(f"Ungültige Ansicht: {exc.errors()[0]['msg']}") from exc
    clean = _validate(merged)
    with core.connect() as conn:
        conn.execute(
            update(pf_saved_views)
            .where(pf_saved_views.c.id == view_id)
            .values(name=clean.name, table_name=clean.table, config=_config(clean), modified=now_iso())
        )
    return get_view(view_id)


def delete_view(view_id: int) -> bool:
    with core.connect() as conn:
        result = conn.execute(delete(pf_saved_views).where(pf_saved_views.c.id == view_id))
    return bool(result.rowcount)
