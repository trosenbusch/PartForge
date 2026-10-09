"""Exceptions of the database layer.

All messages are German (they are shown to the user unchanged); the API layer maps
the exception classes to HTTP status codes (see ``partforge.api.routes_categories.db_errors``).
"""
from __future__ import annotations

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
    "is_lock_error",
]

from ..workspace import WorkspaceNotOpen


class DatabaseNotOpen(WorkspaceNotOpen):
    """No database is open (API: 409, like "no workspace open")."""

    def __init__(self, message: str = "Es ist keine Bibliothek geöffnet.") -> None:
        super().__init__(message)


class DbError(Exception):
    """Base class of business errors raised by :mod:`partforge.db`."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class NotFoundError(DbError, KeyError):
    """A category, field, part or record does not exist (API: 404).

    Subclasses :class:`KeyError` because the module contract documents ``KeyError``
    (e.g. ``get_category``); ``__str__`` returns the German message instead of a repr.
    """

    def __str__(self) -> str:
        return self.message


class CategoryNotFound(NotFoundError):
    def __init__(self, table: str) -> None:
        super().__init__(f"Kategorie „{table}“ nicht gefunden.")
        self.table = table


class FieldNotFound(NotFoundError):
    def __init__(self, table: str, column: str) -> None:
        super().__init__(f"Feld „{column}“ gibt es in der Kategorie „{table}“ nicht.")
        self.table = table
        self.column = column


class PartNotFound(NotFoundError):
    def __init__(self, table: str, part_number: str) -> None:
        super().__init__(f"Bauteil „{part_number}“ wurde in der Kategorie „{table}“ nicht gefunden.")
        self.table = table
        self.part_number = part_number


class SchemaError(DbError, ValueError):
    """Invalid schema change (bad names, protected fields, ...) (API: 400)."""


class ConflictError(DbError, ValueError):
    """The change conflicts with existing data (API: 409)."""


class DuplicatePartError(ConflictError):
    """A part number already exists (in any category table)."""

    def __init__(self, part_number: str, existing_table: str, existing_part_number: str | None = None) -> None:
        shown = existing_part_number or part_number
        if existing_part_number and existing_part_number != part_number:
            text = (
                f"Die Teilenummer „{part_number}“ ist bereits als „{shown}“ in der Kategorie „{existing_table}“ "
                "vergeben (Groß-/Kleinschreibung wird nicht unterschieden). Bitte eine andere Teilenummer wählen."
            )
        else:
            text = (
                f"Die Teilenummer „{part_number}“ existiert bereits in der Kategorie „{existing_table}“. "
                "Teilenummern müssen in der ganzen Bibliothek eindeutig sein (Altium sucht über alle Tabellen)."
            )
        super().__init__(text)
        self.part_number = part_number
        self.existing_table = existing_table
        self.existing_part_number = shown


class PartValidationError(DbError, ValueError):
    """Values of a part are invalid (API: 400 with per-column messages)."""

    def __init__(self, errors: dict[str, str], message: str | None = None) -> None:
        self.errors = dict(errors)
        if message is None:
            parts = [f"{col}: {msg}" for col, msg in self.errors.items()]
            message = "Die Eingaben sind unvollständig oder ungültig – " + "; ".join(parts)
        super().__init__(message)


class BackupError(DbError, RuntimeError):
    """Backup or restore failed (API: 400/500 depending on the cause)."""


class DatabaseBusy(DbError):
    """The database is locked by another connection or process (API: 409, retry later).

    Raised instead of SQLAlchemy's ``OperationalError("database is locked")`` once the
    busy timeout (5 s) has expired – e.g. while another program writes a long transaction.
    """

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "Die Bibliothek ist gerade gesperrt, weil ein anderes Programm (oder ein laufender Import bzw. eine "
            "Sicherung) in die Datenbank schreibt. Bitte in einigen Sekunden erneut versuchen."
        )


class DatabaseFailure(DbError):
    """Unexpected low-level database error with a German explanation (API: 500)."""


# SQLite: SQLITE_BUSY / SQLITE_LOCKED; PostgreSQL: lock_timeout / NOWAIT
LOCK_MESSAGES = (
    "database is locked",
    "database table is locked",
    "database schema is locked",
    "lock timeout",
    "could not obtain lock",
)


def is_lock_error(exc: BaseException) -> bool:
    """True if a DBAPI/SQLAlchemy exception means "locked by another connection".

    Only the driver message is inspected (``exc.orig``), never the SQL statement text."""
    text = str(getattr(exc, "orig", None) or exc).lower()
    return any(marker in text for marker in LOCK_MESSAGES)
