"""User-defined series/MPN templates (``pf_mpn_templates``).

The series module owns the template *format*; this module only stores it as JSON
under a stable key (e.g. ``"yageo-rc-custom"``).
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from sqlalchemy import delete, insert, select, update

from . import core
from .errors import SchemaError
from .schema import now_iso, pf_mpn_templates

__all__ = ["delete_mpn_template", "get_mpn_template", "list_mpn_templates", "save_mpn_template"]

_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")


def _to_dict(row: Mapping[Any, Any]) -> dict[str, Any]:
    try:
        data = json.loads(row["data"] or "{}")
    except ValueError:
        data = {}
    return {
        "key": row["key"],
        "name": row["name"],
        "category": row["category"],
        "data": data,
        "created": row["created"],
        "modified": row["modified"],
    }


def list_mpn_templates(category: str | None = None) -> list[dict[str, Any]]:
    stmt = select(pf_mpn_templates).order_by(pf_mpn_templates.c.name)
    if category:
        stmt = stmt.where(pf_mpn_templates.c.category == category)
    with core.read() as conn:
        return [_to_dict(r) for r in conn.execute(stmt).mappings()]


def get_mpn_template(key: str) -> dict[str, Any] | None:
    with core.read() as conn:
        row = conn.execute(select(pf_mpn_templates).where(pf_mpn_templates.c.key == key)).mappings().first()
    return _to_dict(row) if row else None


def save_mpn_template(key: str, name: str, data: Mapping[str, Any], *, category: str | None = None) -> dict[str, Any]:
    """Insert or replace a template."""
    if not _KEY_RE.match(key or ""):
        raise SchemaError(f"Ungültiger Vorlagenschlüssel „{key}“ (Buchstaben, Ziffern, . _ -).")
    label = " ".join((name or "").split())
    if not label:
        raise SchemaError("Die Vorlage braucht einen Namen.")
    payload = json.dumps(dict(data), ensure_ascii=False, default=str)
    now = now_iso()
    with core.connect() as conn:
        exists = conn.execute(select(pf_mpn_templates.c.key).where(pf_mpn_templates.c.key == key)).first()
        if exists:
            conn.execute(update(pf_mpn_templates).where(pf_mpn_templates.c.key == key)
                         .values(name=label, category=category, data=payload, modified=now))
        else:
            conn.execute(insert(pf_mpn_templates).values(key=key, name=label, category=category, data=payload,
                                                         created=now, modified=now))
    result = get_mpn_template(key)
    assert result is not None
    return result


def delete_mpn_template(key: str) -> bool:
    with core.connect() as conn:
        result = conn.execute(delete(pf_mpn_templates).where(pf_mpn_templates.c.key == key))
    return bool(result.rowcount)
