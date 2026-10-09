"""Key/value metadata of the library database (``pf_meta``) – the public API.

Other modules store small library-wide values here (counters, manifests, the folder the
library was last opened from) instead of using the schema internals::

    from partforge.db import meta
    meta.get_meta("pn_counter:R")                 # -> str | None (open database)
    meta.set_meta("pn_counter:R", "17")           # write transaction (joins an open one)
    meta.set_meta("pn_counter:R", None)           # removes the key
    meta.get_meta(KEY, conn=conn)                 # inside a caller's transaction

Keys are 1–64 characters (``pf_meta.key``). The keys of the schema bookkeeping
(:data:`RESERVED_KEYS`) are written only by :mod:`partforge.db.schema`; ``set_meta`` and
``delete_meta`` refuse them.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, delete, insert, select, update

from . import core
from .schema import pf_meta

__all__ = [
    "MAX_KEY_LENGTH",
    "RESERVED_KEYS",
    "WORKSPACE_ROOT",
    "delete_meta",
    "get_meta",
    "meta_items",
    "set_meta",
]

MAX_KEY_LENGTH = 64  # length of pf_meta.key
#: Written by :func:`partforge.db.schema.bootstrap` only.
RESERVED_KEYS: frozenset[str] = frozenset({"schema_version", "created", "app_version"})
#: Folder the library was last opened from (``str(Workspace.root)``, SQLite libraries only);
#: :func:`partforge.db.lifecycle.open_database` moves absolute links when it differs.
WORKSPACE_ROOT = "workspace_root"


def _check_key(key: str, *, write: bool) -> str:
    if not isinstance(key, str) or not key.strip() or len(key) > MAX_KEY_LENGTH:
        raise ValueError(f"Ungültiger Metadaten-Schlüssel „{key}“ (1–{MAX_KEY_LENGTH} Zeichen).")
    if write and key in RESERVED_KEYS:
        raise ValueError(f"Der Metadaten-Schlüssel „{key}“ wird von PartForge selbst verwaltet.")
    return key


@contextmanager
def _reading(conn: Connection | None) -> Iterator[Connection]:
    if conn is not None:
        yield conn
    else:
        with core.read() as own:
            yield own


@contextmanager
def _writing(conn: Connection | None) -> Iterator[Connection]:
    if conn is not None:
        yield conn
    else:
        with core.connect() as own:
            yield own


def get_meta(key: str, default: str | None = None, *, conn: Connection | None = None) -> str | None:
    """The stored value of ``key`` (``default`` if it is not set)."""
    _check_key(key, write=False)
    with _reading(conn) as c:
        value = c.execute(select(pf_meta.c.value).where(pf_meta.c.key == key)).scalar_one_or_none()
    return default if value is None else str(value)


def set_meta(key: str, value: str | None, *, conn: Connection | None = None) -> None:
    """Store ``value`` under ``key`` (``None`` removes the key)."""
    _check_key(key, write=True)
    if value is None:
        delete_meta(key, conn=conn)
        return
    with _writing(conn) as c:
        exists = c.execute(select(pf_meta.c.key).where(pf_meta.c.key == key)).first()
        if exists:
            c.execute(update(pf_meta).where(pf_meta.c.key == key).values(value=str(value)))
        else:
            c.execute(insert(pf_meta).values(key=key, value=str(value)))


def delete_meta(key: str, *, conn: Connection | None = None) -> bool:
    """Remove ``key``; True if it existed."""
    _check_key(key, write=True)
    with _writing(conn) as c:
        return bool(c.execute(delete(pf_meta).where(pf_meta.c.key == key)).rowcount)


def meta_items(prefix: str = "", *, conn: Connection | None = None) -> dict[str, str]:
    """All keys starting with ``prefix`` (case-sensitive) and their values."""
    with _reading(conn) as c:
        rows = c.execute(select(pf_meta.c.key, pf_meta.c.value).order_by(pf_meta.c.key)).all()
    return {str(k): str(v) for k, v in rows if str(k).startswith(prefix) and v is not None}
