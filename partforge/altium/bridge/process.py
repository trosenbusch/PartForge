"""Read-only checks of the local Altium Designer installation (no window/dialog access).

Only process names and file version resources are read; PartForge never sends messages
to Altium windows and never closes dialogs of any process.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from ...config import AppSettings
from ..models import BackendStatus

log = logging.getLogger(__name__)

__all__ = ["is_process_running", "file_version", "altium_backend_status", "X2_IMAGE"]

X2_IMAGE = "X2.EXE"
_version_cache: dict[tuple[str, int], str | None] = {}


def is_process_running(image: str = X2_IMAGE) -> bool:
    """True if a process with this executable name runs (Windows Toolhelp snapshot).

    ``PARTFORGE_NO_ALTIUM=1`` makes PartForge treat Altium as not running (development and
    UI test servers must never start scripts in the user's Altium session)."""
    if os.name != "nt" or os.environ.get("PARTFORGE_NO_ALTIUM") == "1":
        return False
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    invalid = wintypes.HANDLE(-1).value
    if not snapshot or snapshot == invalid:
        log.debug("Prozessliste nicht verfügbar (Fehler %s)", ctypes.get_last_error())
        return False
    wanted = image.lower()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == wanted:
                return True
            ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snapshot)


def file_version(path: str | os.PathLike[str]) -> str | None:
    """File version resource (e.g. ``26.10.1.5``), cached per path and modification time."""
    p = Path(path)
    try:
        key = (os.path.normcase(str(p.resolve())), p.stat().st_mtime_ns)
    except OSError:
        return None
    if key in _version_cache:
        return _version_cache[key]
    version: str | None = None
    try:
        import win32api  # type: ignore[import-untyped]

        info = win32api.GetFileVersionInfo(str(p), "\\")
        ms, ls = info["FileVersionMS"], info["FileVersionLS"]
        version = f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception as exc:  # noqa: BLE001 - pywin32 missing or no version resource
        log.debug("Dateiversion von %s nicht lesbar: %s", p, exc)
    _version_cache[key] = version
    return version


def altium_backend_status(settings: AppSettings) -> BackendStatus:
    """Status of the Altium backend: X2.EXE found, version, running.

    A hand-edited ``x2_path`` that is a UNC/device path or otherwise invalid is ignored (never executed,
    QA sec finding 2); the message says so (falling back to the auto-detected Altium if there is one)."""
    from ...config import executable_path_problem

    configured = (settings.altium.x2_path or "").strip()
    configured_problem = executable_path_problem(configured, require_name="X2.EXE") if configured else None
    prefix = f"Eingetragener Altium-Pfad ignoriert ({configured_problem}) " if configured_problem else ""
    x2 = settings.resolved_altium_exe()
    if not x2:
        suffix = ("– Pfad korrigieren." if configured_problem
                  else "Altium Designer (X2.EXE) wurde nicht gefunden – Pfad unter Einstellungen › Allgemein › "
                       "Altium Designer eintragen.")
        return BackendStatus(name="altium", available=False, message=f"{prefix}{suffix}".strip())
    version = file_version(x2)
    label = f"Altium Designer {version}" if version else "Altium Designer"
    if not is_process_running(X2_IMAGE):
        return BackendStatus(
            name="altium",
            available=False,
            message=f"{prefix}Altium Designer ist nicht gestartet.".strip() if prefix else "Altium Designer ist nicht gestartet.",
            version=version,
            path=x2,
        )
    return BackendStatus(name="altium", available=True, message=f"{prefix}{label} läuft.".strip(), version=version, path=x2)
