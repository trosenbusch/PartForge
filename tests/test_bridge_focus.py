"""Focus guard of the Altium bridge: Altium must not stay in front of the user's window after a launch."""
from __future__ import annotations

import os
import threading
import time

import pytest

from partforge.altium.bridge import focus
from partforge.altium.bridge.focus import keep_foreground

USER_WINDOW, ALTIUM_WINDOW, OTHER_WINDOW = 100, 200, 300
ALTIUM_PID, OTHER_PID = 4242, 5151


class FakeApi:
    """Scripted Win32 layer: ``steal_after`` polls Altium takes the focus (``steals`` times)."""

    def __init__(self, *, before: int = USER_WINDOW, before_pid: int = 777, steal_after: int = 2, steals: int = 1,
                 switch_to_other: bool = False, user_input_after_restore: bool = False, usable: bool = True):
        self.window = before
        self.before_pid = before_pid
        self.steal_after = steal_after
        self.steals_left = steals
        self.switch_to_other = switch_to_other
        self.user_input_after_restore = user_input_after_restore
        self.is_usable = usable
        self.polls = 0
        self.activated: list[int] = []
        self.locks: list[bool] = []
        self.input_tick = 1
        self.lock_ok = True
        self._mutex = threading.Lock()

    def foreground(self) -> int:
        with self._mutex:
            self.polls += 1
            if self.polls >= self.steal_after and self.steals_left > 0 and self.window != ALTIUM_WINDOW:
                self.steals_left -= 1
                self.window = OTHER_WINDOW if self.switch_to_other else ALTIUM_WINDOW
                if self.activated and self.user_input_after_restore:
                    self.input_tick += 1  # this time the user clicked Altium
            return self.window

    def process_id(self, hwnd: int) -> int:
        return {USER_WINDOW: self.before_pid, ALTIUM_WINDOW: ALTIUM_PID, OTHER_WINDOW: OTHER_PID}[hwnd]

    def image_name(self, pid: int) -> str:
        return {ALTIUM_PID: "X2.EXE", OTHER_PID: "OUTLOOK.EXE"}.get(pid, "PartForge.exe")

    def usable(self, hwnd: int) -> bool:
        return self.is_usable

    def activate(self, hwnd: int) -> bool:
        with self._mutex:
            self.activated.append(hwnd)
            self.window = hwnd
            return True

    def lock(self, locked: bool) -> bool:
        self.locks.append(locked)
        return self.lock_ok

    def last_input(self) -> int:
        return self.input_tick


def _run(api: FakeApi, grace_s: float = 0.4) -> None:
    with keep_foreground(api, grace_s=grace_s, poll_s=0.005):
        pass
    _wait_for_watchers()


def _wait_for_watchers(timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(t.name == "partforge-altium-focus" and t.is_alive() for t in threading.enumerate()):
            return
        time.sleep(0.01)
    raise AssertionError("focus watcher did not stop")


def test_altium_taking_the_focus_is_undone():
    api = FakeApi(steal_after=3)
    _run(api)
    assert api.activated == [USER_WINDOW]
    assert api.window == USER_WINDOW


def test_the_body_is_not_delayed_by_the_watcher():
    api = FakeApi(steal_after=10_000)  # Altium never comes to the front
    started = time.monotonic()
    with keep_foreground(api, grace_s=2.0, poll_s=0.01):
        pass
    assert time.monotonic() - started < 0.2
    focus._current = -1  # stop the watcher early (a newer guard would do the same)
    _wait_for_watchers()
    assert api.activated == []


def test_nothing_happens_when_altium_was_in_front_already():
    api = FakeApi(before=ALTIUM_WINDOW, steal_after=1)
    _run(api)
    assert api.activated == [] and api.locks == []
    assert not any(t.name == "partforge-altium-focus" for t in threading.enumerate())


def test_a_switch_to_another_program_is_left_alone():
    api = FakeApi(steal_after=2, switch_to_other=True)
    _run(api)
    assert api.activated == []
    assert api.window == OTHER_WINDOW


def test_a_second_switch_after_user_input_is_deliberate():
    api = FakeApi(steal_after=2, steals=2, user_input_after_restore=True)
    _run(api)
    assert api.activated == [USER_WINDOW]  # restored once, the second switch is the user's own
    assert api.window == ALTIUM_WINDOW


def test_repeated_stealing_without_input_is_undone_again():
    api = FakeApi(steal_after=2, steals=3)
    _run(api)
    assert api.activated == [USER_WINDOW] * 3


def test_previous_window_gone_is_not_activated():
    api = FakeApi(steal_after=2, usable=False)
    _run(api)
    assert api.activated == []


def test_own_window_locks_and_unlocks_foreground_changes():
    api = FakeApi(before_pid=os.getpid(), steal_after=10_000)
    _run(api, grace_s=0.1)
    assert api.locks == [True, False]


def test_foreign_window_does_not_lock():
    api = FakeApi(before_pid=999_999, steal_after=10_000)
    _run(api, grace_s=0.1)
    assert api.locks == []


def test_newer_guard_replaces_the_older_watcher_and_keeps_the_lock():
    first = FakeApi(before_pid=os.getpid(), steal_after=10_000)
    second = FakeApi(before_pid=os.getpid(), steal_after=10_000)
    with keep_foreground(first, grace_s=5.0, poll_s=0.005):
        pass
    with keep_foreground(second, grace_s=0.1, poll_s=0.005):
        pass
    _wait_for_watchers()
    assert first.locks == [True]  # the newer guard holds the lock now: the old watcher does not unlock
    assert second.locks == [True, False]


def test_guard_errors_never_reach_the_caller():
    class Broken(FakeApi):
        def foreground(self) -> int:
            raise OSError("user32 kaputt")

    ran = []
    with keep_foreground(Broken(), grace_s=0.1, poll_s=0.005):
        ran.append(True)
    assert ran == [True]


def test_switched_off_by_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARTFORGE_ALTIUM_KEEP_FOCUS", "0")
    monkeypatch.setattr(focus, "_default_api", lambda: pytest.fail("Win32 must not be used when switched off"))
    with keep_foreground():
        pass


def test_bridge_uses_the_guard_only_for_the_real_launcher(tmp_path, monkeypatch: pytest.MonkeyPatch):
    from partforge.altium.bridge import core

    used = []

    class Spy:
        def __enter__(self):
            used.append(True)

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(core, "keep_foreground", lambda: Spy())
    bridge = core.AltiumBridge(exchange_dir=tmp_path, x2_path="C:/X2.EXE", launcher=lambda cmd: None,
                               process_check=lambda: True, start_timeout_s=0.05, timeout_s=0.1)
    with pytest.raises(core.BridgeWedgedError):
        bridge.execute("ping")
    assert used == []  # a test launcher never starts X2.EXE, so no guard
