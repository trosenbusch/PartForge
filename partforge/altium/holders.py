"""Which processes hold a file open – Windows Restart Manager (``rstrtmgr.dll``), read-only.

After "Aus Altium deinstallieren" Altium keeps the SQLite database (``PartForge.sqlite`` and its
``-wal``/``-shm`` files) open for about a minute, sometimes until it is restarted (review finding F3):
the library folder cannot be moved or renamed meanwhile. :func:`file_holders` lets the uninstall job
tell the user instead of leaving them with "Zugriff verweigert" in Explorer.

The Restart Manager only lists processes (it never closes or restarts anything here).
"""
from __future__ import annotations

import ctypes
import logging
import os
from collections.abc import Iterable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Final

log = logging.getLogger(__name__)

__all__ = ["FileHolder", "file_holders", "database_files"]

_CCH_RM_SESSION_KEY: Final = 32
_CCH_RM_MAX_APP_NAME: Final = 255
_CCH_RM_MAX_SVC_NAME: Final = 63
_ERROR_MORE_DATA: Final = 234


class _RmUniqueProcess(ctypes.Structure):
    _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME)]


class _RmProcessInfo(ctypes.Structure):
    _fields_ = [
        ("Process", _RmUniqueProcess),
        ("strAppName", ctypes.c_wchar * (_CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", ctypes.c_wchar * (_CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", ctypes.c_int),
        ("AppStatus", wintypes.ULONG),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


@dataclass(frozen=True)
class FileHolder:
    """A process that has one of the files open."""

    pid: int
    name: str  # application name as the Restart Manager reports it (e.g. "Altium Designer")


def database_files(sqlite_path: str | os.PathLike[str]) -> list[Path]:
    """The SQLite database and its WAL/shared-memory files (those that exist)."""
    base = Path(sqlite_path)
    return [p for p in (base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")) if p.exists()]


def file_holders(paths: Iterable[str | os.PathLike[str]]) -> list[FileHolder] | None:
    """Processes (other than this one) holding any of ``paths`` open; ``None`` if it cannot be determined."""
    files = [str(Path(p)) for p in paths]
    if os.name != "nt" or not files:
        return [] if files == [] else None
    try:
        rm = ctypes.WinDLL("rstrtmgr", use_last_error=True)
    except OSError:  # pragma: no cover - Restart Manager exists since Windows Vista
        return None
    session = wintypes.DWORD()
    key = ctypes.create_unicode_buffer(_CCH_RM_SESSION_KEY + 1)
    if rm.RmStartSession(ctypes.byref(session), 0, key) != 0:
        return None
    try:
        array = (ctypes.c_wchar_p * len(files))(*files)
        if rm.RmRegisterResources(session, len(files), array, 0, None, 0, None) != 0:
            return None
        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reason = wintypes.DWORD()
        status = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reason))
        if status == 0:
            return []
        if status != _ERROR_MORE_DATA:
            return None
        infos = (_RmProcessInfo * max(1, needed.value))()
        count = wintypes.UINT(needed.value)
        status = rm.RmGetList(session, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reason))
        if status != 0:
            return None
        own = os.getpid()
        out: list[FileHolder] = []
        for info in infos[: count.value]:
            pid = int(info.Process.dwProcessId)
            if pid != own and all(h.pid != pid for h in out):
                out.append(FileHolder(pid=pid, name=info.strAppName or f"Prozess {pid}"))
        return out
    except Exception as exc:  # noqa: BLE001 - only a hint for the user
        log.debug("Restart Manager nicht nutzbar: %s", exc)
        return None
    finally:
        rm.RmEndSession(session)
