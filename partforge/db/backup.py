"""Database backups (SQLite online backup API) in ``<Bibliothek>/Backups``.

* File names: ``PartForge_YYYYMMDD-HHMMSS_<reason>.sqlite``; the newest 30 are kept.
* Backups are consistent snapshots even while Altium reads the database (WAL).
* Restore copies the backup *into* the live database file with the backup API instead
  of replacing the file: Windows refuses to replace a file that Altium's ODBC driver
  keeps open, while page-level copying works and Altium sees the restored content
  after a refresh. The engine is disposed before and re-opened (migrations) after.
* A backup is checked **before** anything is overwritten (readable, PartForge database,
  schema not newer than this PartForge). If the restored database still cannot be
  opened, the safety copy written just before is copied back and re-opened, so the
  library never ends up closed.
* Restore and the backup list also work while the database is closed (e.g. after a
  failed open), using the current workspace.
* After a successful restore the schema-change callbacks run (the DbLib is rewritten) and
  :data:`partforge.events.PARTS_CHANGED` ``(None, True)`` is emitted (a running Altium
  re-reads the DbLib including its component index).
* Automatic backups run before destructive operations (delete category, remove a
  field, delete or bulk-change more than 20 parts, imports that write, series, restores).
* Disk use: an automatic backup of a database that has not changed since the newest backup is
  not written again (the newest one is returned; the database file and its WAL are compared with
  the state recorded at that backup, ``Backups/.letzte_sicherung.json``). Besides the count limit
  (:data:`KEEP`) the automatic backups (reason ``vor_…``) share a size budget of
  ``max(MIN_BUDGET_BYTES, BUDGET_FACTOR × database size)``; the oldest go first, the newest
  :data:`KEEP_MIN` always stay, manual backups never count.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import os
import re
import shutil
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

from .. import events
from .. import workspace as _workspace
from ..workspace import Workspace
from . import core
from .errors import BackupError, NotFoundError, is_lock_error
from .schema import SCHEMA_VERSION

log = logging.getLogger(__name__)

__all__ = ["KEEP", "auto_backup", "backup_database", "list_backups", "restore_backup"]

KEEP = 30
#: Size budget of the automatic backups: at most max(MIN_BUDGET_BYTES, BUDGET_FACTOR × database size).
MIN_BUDGET_BYTES = 1024**3
BUDGET_FACTOR = 10
#: Automatic backups that always stay, whatever their size.
KEEP_MIN = 3
_STAMP_FILE = ".letzte_sicherung.json"  # state of the database at the newest backup (dedupe)
_AUTO_PREFIX = "vor_"
_NAME_RE = re.compile(r"^PartForge_(\d{8})-(\d{6})_([A-Za-z0-9_\-]+)\.sqlite$")
_TRANSLIT = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
_POSTGRES_MESSAGE = (
    "Sicherungen werden für PostgreSQL vom Datenbankserver erstellt (z. B. pg_dump). "
    "PartForge sichert nur SQLite-Bibliotheken."
)


class BackupNotFound(NotFoundError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Sicherung „{name}“ nicht gefunden.")
        self.name = name


def sanitize_reason(reason: str | None) -> str:
    """ASCII-only, file-name safe reason (``"vor Löschen"`` -> ``"vor_Loeschen"``)."""
    text = "".join(_TRANSLIT.get(ch, ch) for ch in (reason or "").strip())
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9_\-]+", "_", text).strip("_-")
    text = re.sub(r"_+", "_", text)
    return text[:40] or "manuell"


def _workspace_for_backups() -> Workspace:
    """Workspace of the open database, else the current workspace (database closed)."""
    if core.is_open():
        return core.current_workspace()
    return _workspace.current()  # raises WorkspaceNotOpen (API: 409) if there is none


def _sqlite_workspace() -> Workspace:
    ws = _workspace_for_backups()
    if ws.settings.db.kind != "sqlite":
        raise BackupError(_POSTGRES_MESSAGE)
    return ws


def _copy_database(source: Path, target: Path) -> None:
    """Consistent copy with the SQLite backup API; the copy uses rollback journal mode."""
    src = sqlite3.connect(str(source), timeout=10)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
        finally:
            dst.close()
    finally:
        src.close()


def _info(path: Path, ws_root: Path) -> dict[str, Any]:
    match = _NAME_RE.match(path.name)
    created: str
    reason = "unbekannt"
    if match:
        stamp = _dt.datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
        created = stamp.isoformat(timespec="seconds")
        reason = match.group(3)
    else:  # pragma: no cover - list_backups only returns matching names
        created = _dt.datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    try:
        rel = str(path.resolve().relative_to(ws_root.resolve())).replace("/", "\\")
    except ValueError:  # pragma: no cover - Backups folder outside the workspace
        rel = str(path)
    return {
        "name": path.name,
        "path": str(path),
        "rel_path": rel,
        "size": path.stat().st_size,
        "created": created,
        "reason": reason,
    }


def _prune(folder: Path, keep: int = KEEP, *, db_size: int | None = None) -> list[str]:
    """Keep the newest ``keep`` backups; with ``db_size`` also the size budget of the automatic ones."""
    files = sorted((p for p in folder.iterdir() if p.is_file() and _NAME_RE.match(p.name)), key=lambda p: p.name, reverse=True)
    doomed = list(files[keep:])
    if db_size is not None:
        budget = max(MIN_BUDGET_BYTES, BUDGET_FACTOR * db_size)
        used = 0
        automatic = [p for p in files[:keep] if (m := _NAME_RE.match(p.name)) and m.group(3).startswith(_AUTO_PREFIX)]
        for index, path in enumerate(automatic):
            try:
                used += path.stat().st_size
            except OSError:
                continue
            if index >= KEEP_MIN and used > budget:
                doomed.append(path)
    removed: list[str] = []
    for old in doomed:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            log.warning("Alte Sicherung %s konnte nicht gelöscht werden", old, exc_info=True)
    if removed:
        log.info("Alte Sicherungen entfernt: %s", ", ".join(removed))
    return removed


def _file_stamp(path: Path) -> list[int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns]


def _db_stamp(ws: Workspace) -> dict[str, Any]:
    """State of the database file and its WAL (every commit of any program changes one of them)."""
    db = ws.sqlite_path
    return {"db": _file_stamp(db), "wal": _file_stamp(db.with_name(db.name + "-wal"))}


def _read_stamp(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / _STAMP_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_stamp(folder: Path, name: str, stamp: dict[str, Any]) -> None:
    try:
        (folder / _STAMP_FILE).write_text(json.dumps({"name": name, "stamp": stamp}), encoding="utf-8")
    except OSError:
        log.debug("Stand der Sicherung nicht gespeichert", exc_info=True)


def _target_path(folder: Path, reason: str) -> Path:
    label = sanitize_reason(reason)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"PartForge_{stamp}_{label}.sqlite"
    counter = 2
    while target.exists():
        target = folder / f"PartForge_{stamp}_{label}-{counter}.sqlite"
        counter += 1
    return target


def _write_backup(ws: Workspace, reason: str, *, prune: bool) -> Path:
    folder = ws.backups_dir
    folder.mkdir(parents=True, exist_ok=True)
    target = _target_path(folder, reason)
    tmp = target.with_name(target.name + ".tmp")
    with core.write_lock():
        stamp = _db_stamp(ws)  # before copying: a write meanwhile makes the next comparison differ
        try:
            _copy_database(ws.sqlite_path, tmp)
            os.replace(tmp, target)
        except (sqlite3.Error, OSError) as exc:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise BackupError(f"Die Sicherung konnte nicht geschrieben werden: {exc}") from exc
        _write_stamp(folder, target.name, stamp)
    if prune:
        _prune(folder, db_size=(stamp["db"] or [0])[0])
    log.info("Datenbank gesichert: %s", target)
    return target


def backup_database(reason: str = "manuell", *, prune: bool = True) -> Path:
    """Write a backup of the open SQLite database; returns its path.

    Only the newest :data:`KEEP` backups are kept (``prune=False`` skips the cleanup)."""
    state = core.get_state()
    if state.kind != "sqlite":
        raise BackupError(_POSTGRES_MESSAGE)
    return _write_backup(state.ws, reason, prune=prune)


def auto_backup(reason: str) -> Path | None:
    """Backup before a destructive operation (no-op for PostgreSQL).

    If the database has not changed since the newest backup (file and WAL as recorded then), that backup
    is returned instead of writing an identical one."""
    state = core.get_state()
    if state.kind != "sqlite":
        log.info("Automatische Sicherung übersprungen (PostgreSQL): %s", reason)
        return None
    folder = state.ws.backups_dir
    last = _read_stamp(folder) if folder.is_dir() else None
    if last and isinstance(last.get("name"), str) and _NAME_RE.match(last["name"]):
        with core.write_lock():
            unchanged = last.get("stamp") == _db_stamp(state.ws) and (folder / last["name"]).is_file()
        if unchanged:
            log.info("Automatische Sicherung (%s) übersprungen – die Datenbank ist seit %s unverändert",
                     reason, last["name"])
            return folder / last["name"]
    return backup_database(reason)


def list_backups() -> list[dict[str, Any]]:
    """Backups in the Backups folder, newest first (``name, path, rel_path, size, created, reason``).

    Works while the database is closed (current workspace)."""
    ws = _workspace_for_backups()
    folder = ws.backups_dir
    if not folder.is_dir():
        return []
    files = sorted((p for p in folder.iterdir() if p.is_file() and _NAME_RE.match(p.name)), key=lambda p: p.name, reverse=True)
    return [_info(p, ws.root) for p in files]


def _resolve_backup(ws: Workspace, name: str) -> Path:
    if not name or Path(name).name != name or not _NAME_RE.match(name):
        raise BackupNotFound(name)
    path = ws.backups_dir / name
    if not path.is_file():
        raise BackupNotFound(name)
    return path


def _verify(path: Path) -> None:
    """Refuse unreadable files, foreign databases and backups of a newer PartForge."""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            raw_version = None
            if "pf_meta" in tables:
                row = conn.execute("SELECT value FROM pf_meta WHERE key='schema_version'").fetchone()
                raw_version = row[0] if row else None
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise BackupError(f"Die Sicherung „{path.name}“ ist keine lesbare SQLite-Datenbank: {exc}") from exc
    if not check or str(check[0]).lower() != "ok":
        raise BackupError(f"Die Sicherung „{path.name}“ ist beschädigt ({check[0] if check else 'keine Antwort'}).")
    if "pf_categories" not in tables:
        raise BackupError(f"„{path.name}“ ist keine PartForge-Datenbank (Tabelle pf_categories fehlt).")
    version = int(raw_version) if raw_version is not None and str(raw_version).isdigit() else 0
    if version > SCHEMA_VERSION:
        raise BackupError(
            f"Die Sicherung „{path.name}“ stammt aus einer neueren PartForge-Version (Schema {version}, unterstützt "
            f"{SCHEMA_VERSION}) und kann hier nicht wiederhergestellt werden. Bitte PartForge aktualisieren."
        )


def _remove_journal_files(db_path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        with contextlib.suppress(FileNotFoundError):
            db_path.with_name(db_path.name + suffix).unlink()


def _copy_into(source: Path, live: Path) -> None:
    """Copy ``source`` into the live database file.

    Normally page by page with the backup API (works while Altium has the file open; the
    live file keeps its WAL mode). If the live file is damaged (no SQLite database), it is
    replaced byte by byte instead – the reopen converts it to WAL again."""
    if core.file_journal_mode(live) == "invalid":
        _remove_journal_files(live)
        shutil.copyfile(source, live)
        return
    src = sqlite3.connect(str(source), timeout=10)
    try:
        dst = sqlite3.connect(str(live), timeout=10)
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.DatabaseError as exc:
        if isinstance(exc, sqlite3.OperationalError) and is_lock_error(exc):
            raise
        log.warning("Seitenweises Wiederherstellen nicht möglich (%s) – Datei wird ersetzt", exc)
        _remove_journal_files(live)
        shutil.copyfile(source, live)
    finally:
        src.close()


def _safety_copy(ws: Workspace) -> Path:
    """Copy of the current state before a restore (byte copy if the live file is unreadable)."""
    try:
        return _write_backup(ws, "vor_wiederherstellung", prune=False)  # never prune the backup being restored
    except BackupError:
        if not ws.sqlite_path.is_file():
            raise
        target = _target_path(ws.backups_dir, "vor_wiederherstellung_roh")
        try:
            shutil.copyfile(ws.sqlite_path, target)
        except OSError as exc:
            raise BackupError(f"Der aktuelle Stand konnte vor dem Wiederherstellen nicht gesichert werden: {exc}") from exc
        log.warning("Aktueller Stand nicht lesbar – Rohkopie angelegt: %s", target)
        return target


def restore_backup(name: str) -> None:
    """Replace the content of the library database with a backup.

    A safety backup of the current state is written first. If the restored database
    cannot be opened, the previous state is copied back, re-opened and a German
    :class:`BackupError` explains what happened."""
    ws = _sqlite_workspace()
    path = _resolve_backup(ws, name)
    _verify(path)
    from . import categories, lifecycle

    with core.write_lock():
        safety = _safety_copy(ws)
        lifecycle.close_database()
        try:
            _copy_into(path, ws.sqlite_path)
        except (sqlite3.Error, OSError) as exc:
            _reopen_after_failure(ws)
            raise BackupError(
                f"Wiederherstellen fehlgeschlagen ({exc}). Der bisherige Stand ist unverändert; zusätzlich gesichert als "
                f"„{safety.name}“."
            ) from exc
        try:
            lifecycle.open_database(ws)
        except Exception as exc:  # noqa: BLE001 - any failure: bring the previous state back
            log.error("Wiederhergestellte Datenbank lässt sich nicht öffnen: %s", exc)
            try:
                _copy_into(safety, ws.sqlite_path)
                lifecycle.open_database(ws)
            except Exception as again:  # noqa: BLE001
                log.exception("Vorheriger Stand konnte nicht zurückgeholt werden")
                raise BackupError(
                    f"Die Sicherung „{name}“ ließ sich nicht öffnen ({exc}), und der vorherige Stand konnte nicht "
                    f"automatisch zurückgeholt werden ({again}). Er liegt als „{safety.name}“ im Ordner Backups – bitte "
                    "diese Sicherung wiederherstellen."
                ) from exc
            raise BackupError(
                f"Die Sicherung „{name}“ ließ sich nicht öffnen ({exc}). Der vorherige Stand wurde wiederhergestellt "
                f"(zusätzlich gesichert als „{safety.name}“)."
            ) from exc
    _prune(ws.backups_dir, db_size=(_file_stamp(ws.sqlite_path) or [0])[0])
    log.info("Sicherung %s wiederhergestellt (vorheriger Stand: %s)", name, safety.name)
    categories.notify_schema_change()
    # every row may differ (and keys may be new to Altium's component index): announce it like
    # any other write, so a running Altium re-reads the DbLib including its index
    events.emit(events.PARTS_CHANGED, None, True)


def _reopen_after_failure(ws: Workspace) -> None:
    try:
        from .lifecycle import open_database

        open_database(ws)
    except Exception:  # noqa: BLE001 - the original error is more important
        log.exception("Datenbank konnte nach fehlgeschlagenem Wiederherstellen nicht geöffnet werden")
