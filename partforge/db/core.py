"""Engine state, connections and the process-wide write lock.

* One engine per open workspace (SQLite file or PostgreSQL via ``postgres_url``).
* SQLite is **always** in WAL mode (ARCHITEKTUR.md §4, VERIFIED in Altium 26.10: in
  DELETE mode Altium's ODBC connection blocks every PartForge write for the whole
  Altium session). WAL is set once when the file is created – or converted while no
  other program has the file open – by :func:`ensure_wal`; connections only *check*
  the mode and never switch it (switching needs exclusive access). The setting
  ``journal_mode="delete"`` is ignored. SQLite files on network drives are refused
  (WAL needs shared memory) – teams use PostgreSQL.
* ``busy_timeout=5000``, ``foreign_keys=ON``, ``synchronous=NORMAL``; PartForge emits
  ``BEGIN`` itself (``BEGIN IMMEDIATE`` for writes) so DDL is transactional and write
  transactions never fail half way with ``SQLITE_BUSY`` on lock upgrade.
* :func:`connect` = write transaction, serialised by a process-wide re-entrant lock.
  Nested calls in the same thread join the outer transaction (no self-deadlock).
* :func:`read` = read-only connection (consistent snapshot, no lock).
* "database is locked" (after the busy timeout) is raised as :class:`DatabaseBusy`
  with a German message (API: 409).
* SQL functions on SQLite connections: ``pf_num(text, unit)`` (engineering value of a
  stored quantity) and ``pf_fold(text)`` (Unicode case folding – SQLite's ``lower()``
  and ``LIKE`` only fold ASCII). Other dialects use ``lower()`` resp. the Python
  fallback in :mod:`.parts`. Nothing Altium-visible may depend on these functions.
"""
from __future__ import annotations

import ctypes
import logging
import os
import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError, DBAPIError, NoSuchModuleError

from ..workspace import Workspace
from .errors import DatabaseBusy, DatabaseNotOpen, DbError, is_lock_error
from .values import numeric_value

log = logging.getLogger(__name__)

DbKind = Literal["sqlite", "postgres"]

SQLITE_MAGIC = b"SQLite format 3\x00"


@dataclass
class DbState:
    ws: Workspace
    engine: Engine
    kind: DbKind
    journal_mode: str | None
    sql_functions: bool  # pf_num() usable inside SQL statements


_state: DbState | None = None
_state_lock = threading.RLock()
_write_lock = threading.RLock()
_local = threading.local()
# Bumped after every write transaction of this process and whenever the open database changes
# (:func:`data_version`: key of caches derived from the database, e.g. the data quality report).
_data_version = 0


# --------------------------------------------------------------------------- state


def get_state() -> DbState:
    with _state_lock:
        if _state is None:
            raise DatabaseNotOpen()
        return _state


def is_open() -> bool:
    with _state_lock:
        return _state is not None


def install_state(state: DbState | None) -> DbState | None:
    """Replace the global state; returns the previous one (caller disposes it)."""
    global _state
    with _state_lock:
        previous = _state
        _state = state
        _bump_data_version()
        return previous


def _bump_data_version() -> None:
    global _data_version
    with _state_lock:
        _data_version += 1


def data_version() -> int:
    """Changes after every write transaction of this process (committed or not) and whenever another
    database is opened or closed – the key of caches derived from the open database. Writes of other
    programs (Altium, a second process) are not seen."""
    with _state_lock:
        return _data_version


def get_engine() -> Engine:
    """The engine of the open workspace (raises :class:`DatabaseNotOpen`)."""
    return get_state().engine


def current_workspace() -> Workspace:
    return get_state().ws


def dialect_name() -> str:
    return get_state().engine.dialect.name


def sql_functions_enabled() -> bool:
    """True if ``pf_num()`` can be used in SQL (SQLite); else Python fallback."""
    return get_state().sql_functions


def write_lock() -> threading.RLock:
    """The process-wide write lock (held during every write transaction)."""
    return _write_lock


# --------------------------------------------------------------------------- connections


def in_write_transaction() -> bool:
    return getattr(_local, "conn", None) is not None


@contextmanager
def connect() -> Iterator[Connection]:
    """Write transaction (commit on success, rollback on exception).

    Serialised by the process-wide write lock; nested use in the same thread
    joins the outer transaction. A lock held by another process (after the 5 s busy
    timeout) raises :class:`DatabaseBusy`.
    """
    active: Connection | None = getattr(_local, "conn", None)
    if active is not None:
        yield active
        return
    with _write_lock:
        engine = get_engine()
        try:
            with engine.connect() as conn:
                conn.execution_options(pf_write=True)
                with conn.begin():
                    _local.conn = conn
                    try:
                        yield conn
                    finally:
                        _local.conn = None
        except DBAPIError as exc:
            if is_lock_error(exc):
                log.warning("Datenbank gesperrt: %s", getattr(exc, "orig", exc))
                raise DatabaseBusy() from exc
            raise
        finally:
            _bump_data_version()


@contextmanager
def read() -> Iterator[Connection]:
    """Read connection with a consistent snapshot (rolled back on exit).

    Inside a write transaction of the same thread the write connection is reused,
    so uncommitted changes are visible.
    """
    active: Connection | None = getattr(_local, "conn", None)
    if active is not None:
        yield active
        return
    _local.read_depth = getattr(_local, "read_depth", 0) + 1
    try:
        with get_engine().connect() as conn:
            yield conn
    except DBAPIError as exc:
        if is_lock_error(exc):
            raise DatabaseBusy() from exc
        raise
    finally:
        _local.read_depth -= 1


def in_read() -> bool:
    return getattr(_local, "read_depth", 0) > 0


# --------------------------------------------------------------------------- SQL functions


def _pf_num(text: Any, unit: Any) -> float | None:
    if text is None:
        return None
    try:
        return numeric_value(str(text), str(unit) if unit else None)
    except Exception:  # noqa: BLE001 - a SQL function must never raise
        return None


# Hit sets of running searches (``pf_hit(id, part number)``, see partforge.db.parts): id -> set of part numbers
_hit_sets: dict[int, frozenset[str]] = {}
_hit_lock = threading.Lock()
_hit_counter = 0


def register_hits(hits: frozenset[str]) -> int:
    """Make ``hits`` available to the SQL function ``pf_hit(id, value)`` (until :func:`release_hits`)."""
    global _hit_counter
    with _hit_lock:
        _hit_counter += 1
        _hit_sets[_hit_counter] = hits
        return _hit_counter


def release_hits(hit_id: int) -> None:
    with _hit_lock:
        _hit_sets.pop(hit_id, None)


def _pf_hit(hit_id: Any, value: Any) -> int:
    """1 if ``value`` is in the registered hit set ``hit_id`` (SQL function of the search index)."""
    hits = _hit_sets.get(hit_id)
    return 1 if hits is not None and value in hits else 0


def _pf_fold(text: Any) -> str | None:
    """Unicode case folding for case-insensitive search (``Ü`` -> ``ü``, ``Ω`` -> ``ω``, ``ß`` -> ``ss``)."""
    if text is None:
        return None
    try:
        return str(text).casefold()
    except Exception:  # noqa: BLE001 - a SQL function must never raise
        return None


# --------------------------------------------------------------------------- SQLite file handling

DRIVE_REMOTE = 4


def is_network_path(path: Path) -> bool:
    """True for UNC paths and mapped network drives (WAL does not work there)."""
    text = str(path)
    if text.startswith("\\\\") or text.startswith("//"):
        return True
    if os.name != "nt":  # pragma: no cover - Windows only application
        return False
    drive, _ = os.path.splitdrive(str(Path(text).absolute()))
    if not drive or not drive.endswith(":"):
        return False
    try:
        windll = getattr(ctypes, "windll", None)
        if windll is None:  # pragma: no cover
            return False
        return int(windll.kernel32.GetDriveTypeW(f"{drive}\\")) == DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return False


def file_journal_mode(path: Path) -> Literal["new", "wal", "rollback", "invalid"]:
    """Journal mode recorded in the SQLite file header (bytes 18/19: 2 = WAL), without
    opening a connection. ``new`` = missing or empty file, ``invalid`` = no SQLite file."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(100)
    except FileNotFoundError:
        return "new"
    if not header:
        return "new"
    if len(header) < 100 or not header.startswith(SQLITE_MAGIC):
        return "invalid"
    return "wal" if header[18] == 2 and header[19] == 2 else "rollback"


def _not_wal_message(path: Path) -> str:
    return (
        f"Die Bibliothek „{path}“ ist noch nicht im WAL-Modus und wird gerade von einem anderen Programm benutzt "
        "(vermutlich Altium über die DbLib). PartForge muss die Datenbank einmalig umstellen, damit Altium und "
        "PartForge gleichzeitig arbeiten können: bitte Altium schließen (bzw. die DbLib dort deinstallieren und "
        "Altium neu starten) und die Bibliothek danach erneut öffnen."
    )


def ensure_wal(path: Path) -> Literal["created", "converted", "unchanged"]:
    """Put the SQLite file into WAL mode – on creation or (once) for an older file.

    Never touches a file that is already in WAL mode. Converting needs exclusive
    access; if another program holds the file, a German :class:`DbError` explains
    what to do (in DELETE mode Altium would block every write anyway)."""
    mode = file_journal_mode(path)
    if mode in ("wal", "invalid"):
        return "unchanged"  # "invalid": opening reports the problem with the usual message
    try:
        conn = sqlite3.connect(str(path), timeout=2.0, isolation_level=None)
    except sqlite3.Error as exc:
        raise DbError(f"Die Datenbank „{path}“ konnte nicht geöffnet werden: {exc}") from exc
    try:
        try:
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        except sqlite3.OperationalError as exc:
            if is_lock_error(exc):
                raise DbError(_not_wal_message(path)) from exc
            raise DbError(f"Die Datenbank „{path}“ konnte nicht auf den WAL-Modus umgestellt werden: {exc}") from exc
        except sqlite3.DatabaseError as exc:
            raise DbError(f"Die Datenbank „{path}“ konnte nicht geöffnet werden: {exc}") from exc
    finally:
        conn.close()
    if not row or str(row[0]).lower() != "wal":
        raise DbError(_not_wal_message(path))
    if mode == "new":
        log.info("Neue SQLite-Datenbank im WAL-Modus angelegt: %s", path)
        return "created"
    log.info("SQLite-Datenbank auf WAL-Modus umgestellt: %s", path)
    return "converted"


def _sqlite_engine(path: Path) -> Engine:
    url = URL.create("sqlite", database=str(path))
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 5.0})
    warned: list[bool] = []

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:
        dbapi_conn.isolation_level = None  # PartForge emits BEGIN itself (see _on_begin)
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA foreign_keys=ON")
            row = cur.execute("PRAGMA journal_mode").fetchone()  # check only - switching needs exclusive access
            wal = bool(row) and str(row[0]).lower() == "wal"
            if not wal and not warned:
                warned.append(True)
                log.warning("SQLite-Datenbank %s läuft im Journalmodus %s statt WAL", path, row[0] if row else "?")
            cur.execute("PRAGMA synchronous=NORMAL" if wal else "PRAGMA synchronous=FULL")
        finally:
            cur.close()
        dbapi_conn.create_function("pf_num", 2, _pf_num, deterministic=True)
        dbapi_conn.create_function("pf_fold", 1, _pf_fold, deterministic=True)
        dbapi_conn.create_function("pf_hit", 2, _pf_hit)

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection) -> None:
        conn.exec_driver_sql("BEGIN IMMEDIATE" if conn.get_execution_options().get("pf_write") else "BEGIN")

    return engine


# --------------------------------------------------------------------------- engines


_URL_CREDENTIALS = re.compile(r"(://[^:/@]*:)[^@]*(@)")


def mask_url(url: str | None) -> str:
    """Connection URL for messages and logs, with the password hidden."""
    if not url:
        return ""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 - unparsable URL: mask by pattern
        return _URL_CREDENTIALS.sub(r"\1***\2", url)


def describe_target(ws: Workspace) -> str:
    """Human-readable database location (SQLite path or PostgreSQL URL without password)."""
    if ws.settings.db.kind == "postgres":
        return mask_url(ws.settings.db.postgres_url) or "PostgreSQL"
    return str(ws.sqlite_path)


def _postgres_engine(url: str) -> Engine:
    masked = mask_url(url)
    try:
        return create_engine(url, pool_pre_ping=True)
    except ModuleNotFoundError as exc:
        raise DbError(
            f"Für die PostgreSQL-Verbindung „{masked}“ fehlt der Datenbanktreiber „{exc.name}“. Bitte den Treiber "
            "installieren (z. B. pip install \"psycopg[binary]\") oder die Verbindungs-URL anpassen."
        ) from exc
    except NoSuchModuleError as exc:
        raise DbError(
            f"Die Verbindungs-URL „{masked}“ nennt einen unbekannten Datenbanktreiber. Erwartet wird z. B. "
            "postgresql+psycopg://benutzer:passwort@server:5432/datenbank."
        ) from exc
    except (ArgumentError, ValueError) as exc:
        raise DbError(
            f"Die Verbindungs-URL „{masked}“ ist ungültig. Format: "
            "postgresql+psycopg://benutzer:passwort@server:5432/datenbank."
        ) from exc


def create_engine_for(ws: Workspace) -> DbState:
    """Create (but do not install) the engine for a workspace.

    SQLite: refuses network drives and makes sure the file is in WAL mode first."""
    db = ws.settings.db
    if db.kind == "postgres":
        if not db.postgres_url:
            raise DbError(
                "Für PostgreSQL ist keine Verbindungs-URL eingetragen (Einstellungen › Bibliothek › Datenbank)."
            )
        engine = _postgres_engine(db.postgres_url)
        return DbState(ws=ws, engine=engine, kind="postgres", journal_mode=None, sql_functions=False)
    path = ws.sqlite_path
    if is_network_path(path):
        raise DbError(
            f"Die Bibliothek „{path}“ liegt auf einem Netzlaufwerk. SQLite-Bibliotheken werden dort nicht unterstützt "
            "(der für Altium nötige WAL-Modus funktioniert auf Netzlaufwerken nicht). Bitte die Bibliothek auf ein "
            "lokales Laufwerk legen oder für die gemeinsame Nutzung PostgreSQL verwenden."
        )
    if db.journal_mode != "wal":
        log.warning(
            "Einstellung journal_mode=%s wird ignoriert: SQLite-Bibliotheken laufen immer im WAL-Modus "
            "(im DELETE-Modus blockiert Altium jeden Schreibzugriff).", db.journal_mode,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    ensure_wal(path)
    engine = _sqlite_engine(path)
    return DbState(ws=ws, engine=engine, kind="sqlite", journal_mode="wal", sql_functions=True)


def dispose_state(state: DbState | None) -> None:
    """Dispose an engine (checkpoint the WAL first so the file is self-contained)."""
    if state is None:
        return
    if state.kind == "sqlite":
        try:
            raw = state.engine.raw_connection()  # autocommit DBAPI connection (no BEGIN)
            try:
                cur = raw.cursor()
                cur.execute("PRAGMA wal_checkpoint(PASSIVE)")
                cur.close()
            finally:
                raw.close()
        except Exception:  # noqa: BLE001 - best effort
            log.debug("WAL-Checkpoint beim Schließen fehlgeschlagen", exc_info=True)
    state.engine.dispose()
