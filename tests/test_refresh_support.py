"""Test doubles for the Altium refresh/DbLib tests (no Altium needed).

* :class:`FakeBridge` – duck-typed :class:`~partforge.altium.bridge.core.AltiumBridge`
  with an in-memory list of installed libraries and hidden DbLib documents.
* :class:`FakeAltiumScript` – plays the Pascal side of the real bridge exchange
  (reads ``request.txt``, writes the step log and ``response_<id>.txt``).
* helpers to wait for jobs.

Imported by the other ``test_refresh_*``, ``test_dblib_*`` and ``test_api_altium*`` modules
(like ``test_writer_samples``); the few tests below check the doubles themselves.
"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from partforge.altium.bridge.core import (
    AltiumBridge,
    AltiumNotRunning,
    BridgeCommandError,
    DbComponentResolution,
    DbLibInstallState,
    DbLibRefreshResult,
    InstalledDbLib,
    dblib_file_name,
)
from partforge.altium.bridge.protocol import escape_field, unescape_field
from partforge.altium.dblib import same_path
from partforge.jobs import Job, jobs

X2 = r"C:\Program Files\Altium\AD22\X2.EXE"


class FakeBridge:
    """In-memory stand-in for :class:`AltiumBridge` (same method signatures)."""

    def __init__(
        self,
        *,
        running: bool = True,
        x2_path: str | None = X2,
        installed: list[str] | None = None,
        wedge: dict[str, Any] | None = None,
    ):
        self.running = running
        self.x2_path = x2_path
        self.last_wedge = wedge
        self.installed: list[str] = [str(p) for p in installed or []]
        self.hidden_open: set[str] = set()  # installed DbLibs whose hidden document is open
        self.shown: set[str] = set()
        self.modified: set[str] = set()
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail: dict[str, BaseException] = {}
        self.delay_s = 0.0
        self.resolutions: dict[tuple[str, str], DbComponentResolution] = {}
        self.components: dict[str, list[str]] = {}  # library path (normcase) -> component names
        self.opened: list[str] = []
        self.lock = threading.Lock()

    # -- helpers ---------------------------------------------------------------------
    def _call(self, name: str, *args: Any) -> None:
        with self.lock:
            self.calls.append((name, args))
        if self.delay_s:
            time.sleep(self.delay_s)
        error = self.fail.get(name)
        if error is not None:
            raise error
        if not self.running:
            raise AltiumNotRunning("Altium Designer ist nicht gestartet. Bitte Altium starten und erneut versuchen.")

    def names(self) -> list[str]:
        with self.lock:
            return [c[0] for c in self.calls]

    def is_running(self) -> bool:
        return self.running

    # -- bridge API ----------------------------------------------------------------------
    def install_state(self, dblib_path: Any) -> DbLibInstallState:
        self._call("install_state", dblib_path)
        target = Path(dblib_path)
        name = dblib_file_name(target)
        entries = [
            InstalledDbLib(
                index=i,
                path=p,
                same_file=same_path(p, target),
                document_open=p in self.hidden_open or p in self.shown,
                document_shown=p in self.shown,
                document_modified=p in self.modified,
            )
            for i, p in enumerate(self.installed)
            if Path(p).name.casefold() == name.casefold()
        ]
        mine = [e for e in entries if e.same_file]
        return DbLibInstallState(
            path=str(target),
            file_name=name,
            installed=bool(mine),
            position=mine[0].index if mine else None,
            same_name=entries,
            duplicates=[e.path for e in entries if not e.same_file],
            first_match=entries[0].path if entries else None,
            resolves_to_this=bool(entries) and entries[0].same_file,
            installed_count=len(self.installed),
        )

    def refresh_dblib(self, file_name: Any, rebuild_index: bool = False, *, timeout_s: float | None = None) -> DbLibRefreshResult:
        self._call("refresh_dblib", file_name, rebuild_index)
        name = dblib_file_name(file_name)
        result = DbLibRefreshResult(file_name=name, rebuild_index=rebuild_index)
        matched = [p for p in self.installed if Path(p).name.casefold() == name.casefold()]
        result.matched = matched
        passes = 2 if rebuild_index and matched else 1
        for pass_no in range(passes):
            if pass_no == 1:
                self.hidden_open.update(self.installed)  # RefreshInstalledLibraries reopens every DbLib
                result.refreshed_index = True
                result.refresh_ms = 2500
            for path in matched:
                if path in self.modified:
                    result.skipped[path] = "modified"
                elif path in self.shown:
                    result.skipped[path] = "shown"
                elif path in self.hidden_open:
                    self.hidden_open.discard(path)
                    if path not in result.closed:
                        result.closed.append(path)
                elif path not in result.closed and path not in result.not_open:
                    result.not_open.append(path)
        result.not_open = [p for p in result.not_open if p not in result.closed]
        return result

    def install_library(self, path: Any) -> bool:
        self._call("install_library", path)
        text = str(Path(path))
        if not any(same_path(p, text) for p in self.installed):
            self.installed.append(text)
            self.hidden_open.add(text)  # InstallLibrary opens the hidden document (VERIFIED)
        return True

    def uninstall_library(self, path: Any) -> bool:
        self._call("uninstall_library", path)
        self.installed = [p for p in self.installed if not same_path(p, path)]
        return True  # like Altium: the hidden document stays open

    def resolve_db_component(self, dblib: Any, table: str, key: str) -> DbComponentResolution:
        self._call("resolve_db_component", dblib, table, key)
        found = self.resolutions.get((table, key))
        if found is not None:
            return found
        raise BridgeCommandError("resolve_db_component", f"unbekannt: {table}/{key}")

    def open_document(self, path: Any, kind: str | None = None) -> bool:
        self._call("open_document", path)
        text = str(path)
        was_open = text in self.opened
        self.opened.append(text)
        return was_open

    def edit_component(self, path: Any, name: str, kind: str | None = None) -> Any:
        from partforge.altium.bridge.core import ComponentFocus

        self._call("edit_component", path, name, kind)
        text = str(path)
        was_open = text in self.opened
        self.opened.append(text)
        found = name.casefold() in {n.casefold() for n in self.components.get(os.path.normcase(text), [name])}
        return ComponentFocus(path=text, name=name, was_open=was_open, found=found, current=name if found else "",
                              modified=text in self.modified)

    def set_components(self, library: Path, names: list[str]) -> None:
        self.components[os.path.normcase(str(library))] = list(names)

    def list_components(self, path: Any) -> list[str]:
        self._call("list_components", path)
        names = self.components.get(os.path.normcase(str(path)))
        if names is None:
            raise BridgeCommandError("list_components", f"PCB library not available: {path}")
        return list(names)


Handler = Callable[[str, dict[str, str]], list[str]]


class FakeAltiumScript:
    """Launcher replacement for the real :class:`AltiumBridge`: answers like the Pascal side."""

    def __init__(self, exchange: Path, handler: Handler):
        self.exchange = exchange
        self.handler = handler
        self.requests: list[tuple[str, dict[str, str]]] = []
        self.errors: list[BaseException] = []

    def __call__(self, command_line: str) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _write(self, path: Path, lines: list[str]) -> None:
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))

    def _run(self) -> None:
        try:
            time.sleep(0.02)
            rid = command = ""
            args: dict[str, str] = {}
            for line in (self.exchange / "request.txt").read_text(encoding="ascii").splitlines():
                tag, _, rest = line.partition("|")
                if tag == "ID":
                    rid = rest
                elif tag == "COMMAND":
                    command = rest
                elif tag == "ARG":
                    key, _, value = rest.partition("|")
                    args[key] = unescape_field(value)
            self.requests.append((command, args))
            self._write(self.exchange / f"log_{rid}.txt", ["1 started", f"2 command {command}"])
            try:
                body = self.handler(command, args)
                status = ["STATUS|OK"]
            except Exception as exc:  # noqa: BLE001 - becomes an ERROR response
                body, status = [], ["STATUS|ERROR", "ERROR|" + escape_field(str(exc))]
            self._write(self.exchange / f"response_{rid}.txt", ["PFRES|1", f"ID|{rid}", *status, *body, f"END|{rid}"])
        except BaseException as exc:  # noqa: BLE001 - surfaced by the tests
            self.errors.append(exc)


def script_bridge(tmp_path: Path, handler: Handler) -> tuple[AltiumBridge, FakeAltiumScript]:
    """A real :class:`AltiumBridge` whose script runs are answered by ``handler``."""
    exchange = tmp_path / "exchange"
    fake = FakeAltiumScript(exchange, handler)
    bridge = AltiumBridge(
        exchange_dir=exchange,
        x2_path=X2,
        timeout_s=5.0,
        start_timeout_s=2.0,
        poll_interval_s=0.02,
        lock_timeout_s=5.0,
        launcher=fake,
        process_check=lambda: True,
        process_check_interval_s=0.1,
    )
    return bridge, fake


def wait_job(job_or_id: Job | str, timeout_s: float = 15.0) -> dict[str, Any]:
    """Wait for a job (object or id) to finish and return its snapshot."""
    job_id = job_or_id if isinstance(job_or_id, str) else job_or_id.id
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = jobs.get(job_id)
        if job is not None and job.status in ("done", "failed", "cancelled"):
            return job.snapshot()
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} wurde nicht fertig")


def wait_for(predicate: Callable[[], bool], timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# --------------------------------------------------------------------------- self-tests


def test_fake_bridge_models_verified_altium_behaviour(tmp_path):
    lib = tmp_path / "PartForge.DbLib"
    bridge = FakeBridge()
    assert bridge.install_state(lib).installed is False
    bridge.install_library(lib)
    assert bridge.install_state(lib).installed is True
    first = bridge.refresh_dblib("PartForge.DbLib")
    assert first.closed == [str(lib)] and first.installed
    again = bridge.refresh_dblib("PartForge.DbLib", rebuild_index=True)
    assert again.refreshed_index and again.closed == [str(lib)]  # reopened by the refresh, closed again
    bridge.uninstall_library(lib)
    assert bridge.refresh_dblib("PartForge.DbLib").matched == []


def test_fake_bridge_failures_and_not_running(tmp_path):
    bridge = FakeBridge(running=False)
    with pytest.raises(AltiumNotRunning):
        bridge.refresh_dblib("PartForge.DbLib")
    bridge = FakeBridge()
    bridge.fail["install_state"] = BridgeCommandError("dblib_install_state", "kaputt")
    with pytest.raises(BridgeCommandError):
        bridge.install_state(tmp_path / "PartForge.DbLib")
    assert bridge.names() == ["install_state"]


def test_script_bridge_roundtrip(tmp_path):
    bridge, fake = script_bridge(tmp_path, lambda command, args: ["KV|version|26.10.1.5"])
    assert bridge.ping() == "26.10.1.5"
    assert fake.requests == [("ping", {})] and not fake.errors
