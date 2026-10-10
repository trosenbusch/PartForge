"""Keep the user's window in front while PartForge hands a script to Altium (Windows only).

Starting ``X2.EXE -RScriptingSystem:RunScript(...)`` makes the running Altium instance activate its main
window. PartForge talks to Altium in the background (automatic refresh after edits, verify batches,
installs), so Altium must not jump in front of the user's work - keystrokes meant for another program
would land in Altium. :func:`keep_foreground` guards one bridge call:

1. If PartForge itself is the foreground process (the desktop window), it locks foreground changes
   (``LockSetForegroundWindow``) for the first seconds after the launch, so Altium cannot take the focus.
2. A watcher thread polls the foreground window during those seconds. If Altium took the focus anyway
   (e.g. PartForge was not in front and another program was), the window that was active before the
   call is activated again at once - provided it still exists and is visible. If Altium comes to the
   front again after that and the user clicked or typed in between, the user switched on purpose: the
   watcher stops.

Only the first seconds after the launch are guarded (Altium activates itself when the command arrives);
a newer guard replaces an older one. The watcher never delays the bridge call. Set
``PARTFORGE_ALTIUM_KEEP_FOCUS=0`` to switch the guard off.

The opposite case – the user wants to work in Altium ("In Altium bearbeiten") – uses
:func:`allow_altium_foreground` before the launch (Windows lets another process take the foreground only
when the foreground process allows it) and :func:`bring_altium_to_front` afterwards (best effort: restores a
minimised main window and activates it).
"""
from __future__ import annotations

import contextlib
import itertools
import logging
import os
import sys
import threading
import time
from collections.abc import Iterator
from typing import Protocol

log = logging.getLogger("partforge.altium.focus")

#: Seconds after the launch during which a focus change to Altium is undone.
GRACE_S = 6.0
#: Poll interval of the watcher (short: keystrokes typed into Altium in between are the risk).
POLL_S = 0.03
ALTIUM_IMAGE = "x2.exe"

__all__ = ["keep_foreground", "allow_altium_foreground", "bring_altium_to_front", "WindowApi", "GRACE_S", "POLL_S"]


class WindowApi(Protocol):
    """The few Win32 calls the guard needs (replaced by a fake in tests)."""

    def foreground(self) -> int: ...
    def process_id(self, hwnd: int) -> int: ...
    def image_name(self, pid: int) -> str: ...
    def usable(self, hwnd: int) -> bool: ...
    def activate(self, hwnd: int) -> bool: ...
    def lock(self, locked: bool) -> bool: ...
    def last_input(self) -> int: ...


class _Win32Api:
    """ctypes implementation of :class:`WindowApi`."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class LastInputInfo(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self._ctypes = ctypes
        self._wintypes = wintypes
        self._last_input_info = LastInputInfo
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        u, k = self.user32, self.kernel32
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        for name in ("IsWindow", "IsWindowVisible", "IsIconic", "IsHungAppWindow", "SetForegroundWindow", "BringWindowToTop"):
            getattr(u, name).argtypes = [wintypes.HWND]
            getattr(u, name).restype = wintypes.BOOL
        u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        u.AttachThreadInput.restype = wintypes.BOOL
        u.LockSetForegroundWindow.argtypes = [wintypes.UINT]
        u.LockSetForegroundWindow.restype = wintypes.BOOL
        u.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInputInfo)]
        u.GetLastInputInfo.restype = wintypes.BOOL
        k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k.OpenProcess.restype = wintypes.HANDLE
        k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]
        k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.GetCurrentThreadId.restype = wintypes.DWORD
        u.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        u.AllowSetForegroundWindow.restype = wintypes.BOOL
        u.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        u.GetWindow.restype = wintypes.HWND
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        u.GetWindowTextLengthW.restype = ctypes.c_int
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.ShowWindow.restype = wintypes.BOOL
        self._enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        u.EnumWindows.argtypes = [self._enum_proc, wintypes.LPARAM]
        u.EnumWindows.restype = wintypes.BOOL

    def foreground(self) -> int:
        return int(self.user32.GetForegroundWindow() or 0)

    def process_id(self, hwnd: int) -> int:
        pid = self._wintypes.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid))
        return int(pid.value)

    def image_name(self, pid: int) -> str:
        process_query_limited_information = 0x1000
        handle = self.kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ""
        try:
            size = self._wintypes.DWORD(1024)
            buffer = self._ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, self._ctypes.byref(size)):
                return ""
            return os.path.basename(buffer.value)
        finally:
            self.kernel32.CloseHandle(handle)

    def usable(self, hwnd: int) -> bool:
        u = self.user32
        return bool(hwnd) and bool(u.IsWindow(hwnd)) and bool(u.IsWindowVisible(hwnd)) and not u.IsIconic(hwnd)

    def activate(self, hwnd: int) -> bool:
        """Activate ``hwnd`` from a background process: attach to the input of the current foreground
        thread for the call (the usual way around the foreground lock), then detach again."""
        u = self.user32
        current = self.kernel32.GetCurrentThreadId()
        foreground = u.GetForegroundWindow()
        if foreground and u.IsHungAppWindow(foreground):
            return False  # never attach to a hanging Altium
        target_thread = u.GetWindowThreadProcessId(foreground, None) if foreground else 0
        attached = bool(target_thread and target_thread != current and u.AttachThreadInput(current, target_thread, True))
        try:
            u.BringWindowToTop(hwnd)
            return bool(u.SetForegroundWindow(hwnd))
        finally:
            if attached:
                u.AttachThreadInput(current, target_thread, False)

    def lock(self, locked: bool) -> bool:
        lsfw_lock, lsfw_unlock = 1, 2
        return bool(self.user32.LockSetForegroundWindow(lsfw_lock if locked else lsfw_unlock))

    def last_input(self) -> int:
        info = self._last_input_info()
        info.cbSize = self._ctypes.sizeof(info)
        return int(info.dwTime) if self.user32.GetLastInputInfo(self._ctypes.byref(info)) else 0

    def allow_foreground(self) -> bool:
        """Let any process take the foreground once (only effective while this process is in front)."""
        asfw_any = 0xFFFFFFFF
        return bool(self.user32.AllowSetForegroundWindow(asfw_any))

    def altium_window(self) -> int:
        """Altium's main window: the visible, unowned top-level window of ``X2.EXE`` with the longest title
        (0 if there is none)."""
        u = self.user32
        gw_owner = 4
        found: list[tuple[int, int]] = []

        def visit(hwnd: int, _param: int) -> bool:
            if hwnd and u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, gw_owner):
                length = int(u.GetWindowTextLengthW(hwnd))
                if length and self.image_name(self.process_id(hwnd)).casefold() == ALTIUM_IMAGE:
                    found.append((length, int(hwnd)))
            return True

        u.EnumWindows(self._enum_proc(visit), 0)
        return max(found)[1] if found else 0

    def restore(self, hwnd: int) -> None:
        sw_restore = 9
        if self.user32.IsIconic(hwnd):
            self.user32.ShowWindow(hwnd, sw_restore)


_api: WindowApi | None = None
_state_lock = threading.Lock()
_generation = itertools.count(1)
_current = 0  # generation of the newest guard; older watchers stop
_locked_by = 0  # generation that holds LockSetForegroundWindow (0 = none)


def _default_api() -> WindowApi | None:
    global _api
    if sys.platform != "win32":
        return None
    with _state_lock:
        if _api is None:
            try:
                _api = _Win32Api()
            except (OSError, AttributeError) as exc:  # pragma: no cover - no user32 (very unusual)
                log.warning("Fensterfokus-Schutz nicht verfügbar: %s", exc)
                return None
        return _api


def _enabled() -> bool:
    return os.environ.get("PARTFORGE_ALTIUM_KEEP_FOCUS", "1") != "0"


@contextlib.contextmanager
def keep_foreground(api: WindowApi | None = None, *, grace_s: float = GRACE_S, poll_s: float = POLL_S) -> Iterator[None]:
    """Guard one bridge call against Altium taking the focus (see the module docstring). Starts the
    watcher before the body runs and returns immediately afterwards; never raises because of the guard."""
    api = api or (_default_api() if _enabled() else None)
    if api is not None:
        with contextlib.suppress(Exception):  # the guard must never break a bridge call
            _start(api, grace_s, poll_s)
    yield


def allow_altium_foreground(api: WindowApi | None = None) -> bool:
    """Before a launch the user asked for: allow Altium to come to the front (never raises)."""
    api = api or _default_api()
    allow = getattr(api, "allow_foreground", None)
    if allow is None:
        return False
    try:
        return bool(allow())
    except Exception as exc:  # noqa: BLE001 - only a convenience
        log.debug("Vordergrundwechsel nicht freigegeben: %s", exc)
        return False


def bring_altium_to_front(api: WindowApi | None = None) -> bool:
    """Activate Altium's main window (restored if minimised); ``False`` if it is not found or Windows refused.
    Never raises – the bridge call it follows has succeeded."""
    global _current
    api = api or _default_api()
    window = getattr(api, "altium_window", None)
    if api is None or window is None:
        return False
    try:
        hwnd = int(window())
        if not hwnd:
            return False
        with _state_lock:
            _current = next(_generation)  # an older keep_foreground watcher must not undo this
        restore = getattr(api, "restore", None)
        if restore is not None:
            restore(hwnd)
        return bool(api.activate(hwnd))
    except Exception as exc:  # noqa: BLE001 - only a convenience
        log.debug("Altium nicht nach vorn geholt: %s", exc)
        return False


def _start(api: WindowApi, grace_s: float, poll_s: float) -> None:
    global _current, _locked_by
    before = api.foreground()
    if not before:
        return
    before_pid = api.process_id(before)
    if not before_pid or api.image_name(before_pid).casefold() == ALTIUM_IMAGE:
        return  # Altium is in front already - nothing to protect
    with _state_lock:
        generation = next(_generation)
        _current = generation
        if before_pid == os.getpid() and api.lock(True):
            _locked_by = generation
    threading.Thread(
        target=_watch, args=(api, before, generation, grace_s, poll_s), name="partforge-altium-focus", daemon=True
    ).start()


def _watch(api: WindowApi, before: int, generation: int, grace_s: float, poll_s: float) -> None:
    deadline = time.monotonic() + grace_s
    restored_at_input: int | None = None
    try:
        while time.monotonic() < deadline and _current == generation:
            current = api.foreground()
            if current and current != before:
                pid = api.process_id(current)
                if api.image_name(pid).casefold() != ALTIUM_IMAGE:
                    return  # the user switched to another program: not ours to undo
                if restored_at_input is not None and api.last_input() != restored_at_input:
                    return  # Altium again after the user clicked or typed: switched on purpose
                if not api.usable(before):
                    return
                if api.activate(before):
                    restored_at_input = api.last_input()
                    log.info("Altium hat den Fokus übernommen – vorheriges Fenster wiederhergestellt.")
            time.sleep(poll_s)
    except Exception as exc:  # noqa: BLE001 - the watcher must never kill anything
        log.debug("Fensterfokus-Prüfung fehlgeschlagen: %s", exc)
    finally:
        _release(api, generation)


def _release(api: WindowApi, generation: int) -> None:
    global _locked_by
    with _state_lock:
        if _locked_by != generation:
            return
        _locked_by = 0
    with contextlib.suppress(Exception):
        api.lock(False)
