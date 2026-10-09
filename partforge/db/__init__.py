"""Database layer of PartForge (SQLAlchemy 2 Core; SQLite or PostgreSQL).

Public contract (ARCHITEKTUR.md §4)::

    open_database(ws) -> None        create/migrate schema, seed built-in categories, bind engine
    close_database() -> None         dispose engine
    seed_examples(ws) -> dict        example parts/symbols/footprints for a new workspace (returns counts)
    get_engine() -> Engine           engine of the open workspace
    connect() -> ContextManager[Connection]   write transaction (process-wide write lock)
    read() -> ContextManager[Connection]      read-only connection / snapshot

Sub-modules: :mod:`.categories`, :mod:`.parts`, :mod:`.registry`, :mod:`.backup`,
:mod:`.health`, :mod:`.views`, :mod:`.mpn_templates`, :mod:`.values`, :mod:`.meta`
(``pf_meta`` key/value API: ``get_meta``/``set_meta``).
Opening runs the data migrations of :mod:`.lifecycle` (default symbols, schematic texts,
links of a moved library folder).
Importing this package has no side effects (no database access).
"""
from __future__ import annotations

from .core import connect, current_workspace, get_engine, is_open, read, write_lock
from .errors import (
    BackupError,
    CategoryNotFound,
    ConflictError,
    DatabaseBusy,
    DatabaseFailure,
    DatabaseNotOpen,
    DbError,
    DuplicatePartError,
    FieldNotFound,
    NotFoundError,
    PartNotFound,
    PartValidationError,
    SchemaError,
)
from .examples import seed_examples
from .lifecycle import close_database, open_database

__all__ = [
    "BackupError",
    "CategoryNotFound",
    "ConflictError",
    "DatabaseBusy",
    "DatabaseFailure",
    "DatabaseNotOpen",
    "DbError",
    "DuplicatePartError",
    "FieldNotFound",
    "NotFoundError",
    "PartNotFound",
    "PartValidationError",
    "SchemaError",
    "close_database",
    "connect",
    "current_workspace",
    "get_engine",
    "is_open",
    "open_database",
    "read",
    "seed_examples",
    "write_lock",
]
