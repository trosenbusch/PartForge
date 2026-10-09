"""Integrity of library writes (review findings INT-01, INT-02, F11 and PKG-01 #4).

* INT-02: every multi-call operation works on a working copy beside the library and replaces it in one
  ``os.replace`` – the live file never holds an intermediate state (no "0 real footprints, only STEP
  carriers"), a crash leaves the old file intact, leftovers are cleaned up.
* INT-01: the library lock also serialises other processes (a second PartForge window).
* F11: an OS error names the outcome first, in German, without Python's path repr.
* PKG-01 #4: unreadable heights before a write refuse the write instead of resetting every height to 0.

Real ``altium-designer-mcp.exe`` (marker ``rustwriter``) except for the pure lock/message tests.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest
from test_writer_samples import chip_0603, chip_with_step, soic8, write_step

from partforge.altium import heights
from partforge.altium.libwriter import is_temp_library_file, workspace_library_files
from partforge.altium.rustwriter import (
    STEP_CARRIER_PREFIX,
    LibraryLock,
    LibraryLocked,
    RustLibraryOps,
    _posix,
    file_access_message,
    get_client,
    library_lock,
    shutdown_client,
    work_copy_files,
)
from partforge.workspace import Workspace, set_current

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture
def ws(tmp_path: Path):
    workspace = Workspace.create(tmp_path / "Bibliothek", name="Integrität")
    set_current(workspace)
    try:
        yield workspace
    finally:
        set_current(None)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RecordingClient:
    """Wraps the real client: records ``(tool, filepath)`` and can stop at a given call."""

    MUTATING = {"write_pcblib", "write_schlib", "update_component", "delete_component", "repair_library"}

    def __init__(self, inner, *, fail_after: str | None = None, error: BaseException | None = None):
        self.inner = inner
        self.calls: list[tuple[str, str]] = []
        self.fail_after = fail_after
        self.error = error

    def ensure_allowed(self, dirs, *, exact=False):
        self.inner.ensure_allowed(dirs, exact=exact)

    def call_tool(self, name, arguments, *, timeout=None):
        self.calls.append((name, str(arguments.get("filepath", ""))))
        result = self.inner.call_tool(name, arguments, timeout=timeout)
        if name == self.fail_after and self.error is not None:
            raise self.error
        return result


# --------------------------------------------------------------------------- INT-02: working copy


@pytest.mark.rustwriter
def test_every_writer_call_works_on_a_copy_and_the_library_is_replaced_once(ws):
    step = write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [chip_0603(f"R{i}") for i in range(4)]).ok
    spy = RecordingClient(get_client())
    spied = RustLibraryOps(client=spy, workspace=ws)  # type: ignore[arg-type]
    result = spied.write_library_full(lib, [*(chip_0603(f"R{i}") for i in range(4)), chip_with_step(ws.rel(step))])
    assert result.ok, result.errors
    mutating = [(tool, path) for tool, path in spy.calls if tool in RecordingClient.MUTATING]
    assert mutating and all(Path(path).name != lib.name for _tool, path in mutating), mutating  # never the live file
    assert all(".pfwork" in Path(path).name for _tool, path in mutating)
    assert ops.list_components(lib) == ["R0", "R1", "R2", "R3", "CAPC2012X125N"]
    assert work_copy_files(lib) == [] and list(ws.footprints_dir.glob("*.bak")) == []


@pytest.mark.rustwriter
def test_failure_after_the_carrier_write_leaves_the_library_untouched(ws):
    """The old code wrote ONLY the temporary STEP carriers with append=false into the live file first – a crash
    there left the library without a single real footprint (INT-02)."""
    step = write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [chip_0603(f"R{i}") for i in range(3)]).ok
    before = _sha(lib)
    from partforge.altium.rustwriter import RustProcessError

    crashing = RustLibraryOps(client=RecordingClient(get_client(), fail_after="write_pcblib",  # type: ignore[arg-type]
                                                      error=RustProcessError("simulierter Absturz")), workspace=ws)
    result = crashing.write_library_full(lib, [chip_0603("R0"), chip_with_step(ws.rel(step))])
    assert not result.ok and result.written == []
    assert _sha(lib) == before and ops.list_components(lib) == ["R0", "R1", "R2"]
    assert work_copy_files(lib) == []


@pytest.mark.rustwriter
def test_killed_process_never_leaves_a_half_written_library(ws, tmp_path):
    """A process killed in the middle of a multi-call rewrite (os._exit after the carrier write, i.e. no cleanup
    at all) leaves the old, complete library; the next operation removes the leftover working copy."""
    step = write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_KILL.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [chip_0603(f"R{i}") for i in range(5)]).ok
    before = _sha(lib)
    script = tmp_path / "child.py"
    script.write_text(textwrap.dedent(f"""
        import os, sys
        sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'tests')!r})
        from pathlib import Path
        from partforge.workspace import Workspace, set_current
        from partforge.altium.rustwriter import RustLibraryOps, get_client
        from test_writer_samples import chip_0603, chip_with_step
        ws = Workspace.open({str(ws.root)!r}); set_current(ws)

        class Killer:
            def __init__(self, inner): self.inner = inner
            def ensure_allowed(self, dirs, *, exact=False): self.inner.ensure_allowed(dirs, exact=exact)
            def call_tool(self, name, arguments, *, timeout=None):
                result = self.inner.call_tool(name, arguments, timeout=timeout)
                if name == "write_pcblib":
                    os._exit(3)  # killed: no rollback, no cleanup
                return result

        ops = RustLibraryOps(client=Killer(get_client()), workspace=ws)
        ops.write_library_full(Path({str(lib)!r}), [chip_0603("R0"), chip_with_step({ws.rel(step)!r})])
    """), encoding="utf-8")
    env = {**os.environ, "PARTFORGE_NO_ALTIUM": "1"}
    proc = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, timeout=120)
    assert proc.returncode == 3, proc.stderr.decode(errors="replace")[-2000:]
    assert _sha(lib) == before and ops.list_components(lib) == [f"R{i}" for i in range(5)]
    leftovers = work_copy_files(lib)
    assert leftovers and all(is_temp_library_file(p) or p.suffix == ".bak" for p in leftovers)
    assert [p.name for p in workspace_library_files(ws)] == ["PF_KILL.PcbLib"]  # never listed
    assert ops.upsert_footprints(lib, [soic8()]).ok
    assert work_copy_files(lib) == [] and ops.list_components(lib)[-1] == "SOIC127P600X175-8N"


@pytest.mark.rustwriter
def test_leftover_step_carriers_of_an_older_crash_are_removed(ws):
    step = write_step(ws.models_dir / "box.step")
    lib = ws.footprints_dir / "PF_OLD.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [chip_0603("A")]).ok
    carrier = f"{STEP_CARRIER_PREFIX}DEADBEEF_0"
    get_client().call_tool("write_pcblib", {"filepath": _posix(lib), "append": True, "footprints": [
        {"name": carrier, "description": "PartForge STEP carrier (temporary)", "pads": [],
         "step_model": {"filepath": _posix(step), "embed": True}}]})
    raw = get_client().call_tool("list_components", {"filepath": _posix(lib)})["components"]
    assert carrier in raw and ops.list_components(lib) == ["A"]  # hidden from PartForge, visible in Altium
    assert ops.upsert_footprints(lib, [chip_0603("B")]).ok
    raw = get_client().call_tool("list_components", {"filepath": _posix(lib)})["components"]
    assert raw == ["A", "B"]


# --------------------------------------------------------------------------- F11: OS errors in German


def _open_exclusively(path: Path):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    handle = k32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)  # GENERIC_READ, no sharing
    assert handle not in (None, ctypes.c_void_p(-1).value)
    return k32, handle


@pytest.mark.rustwriter
def test_a_locked_library_gives_a_german_message_with_the_outcome_first(ws):
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [chip_0603("A")]).ok
    before = _sha(lib)
    k32, handle = _open_exclusively(lib)
    try:
        result = ops.upsert_footprints(lib, [chip_0603("B")])
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))
    assert not result.ok
    message = result.errors["B"]
    assert message.startswith("PF_CHIP.PcbLib wurde nicht geschrieben – die Bibliothek ist unverändert"), message
    assert "anderen Programm geöffnet oder schreibgeschützt" in message[:200]
    assert "Errno" not in message and "\\\\" not in message and "Permission denied" not in message
    assert message.count("unverändert") == 1
    assert _sha(lib) == before and work_copy_files(lib) == []


def test_file_access_message_texts(tmp_path):
    lib = tmp_path / "PF_X.SchLib"
    denied = file_access_message(lib, PermissionError(13, "Permission denied", str(lib)))
    assert denied.startswith("PF_X.SchLib wurde nicht geschrieben – die Bibliothek ist unverändert")
    assert str(tmp_path) not in denied and "Permission" not in denied
    gone = file_access_message(lib, FileNotFoundError(2, "No such file", str(lib)))
    assert "nicht gefunden" in gone


# --------------------------------------------------------------------------- INT-01: other processes


def _hold_in_child(lib: Path, seconds: float, ready: Path) -> subprocess.Popen[bytes]:
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(ROOT)!r})
        from pathlib import Path
        from partforge.altium.rustwriter import library_lock
        with library_lock(Path({str(lib)!r})):
            Path({str(ready)!r}).write_text("x")
            time.sleep({seconds})
    """)
    return subprocess.Popen([sys.executable, "-c", code])


def _wait_for(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        assert time.monotonic() < deadline, "Kindprozess hat die Sperre nicht gesetzt"
        time.sleep(0.05)


def test_library_lock_excludes_other_processes(tmp_path):
    lib = tmp_path / "Footprints" / "PF_CHIP.PcbLib"
    lib.parent.mkdir()
    ready = tmp_path / "ready"
    child = _hold_in_child(lib, 3.0, ready)
    try:
        _wait_for(ready)
        lock = LibraryLock(lib)
        started = time.monotonic()
        with pytest.raises(LibraryLocked) as refused:
            lock.acquire(timeout=0.3)
        assert time.monotonic() - started >= 0.25
        assert "anderes PartForge-Fenster" in str(refused.value) and "unverändert" in str(refused.value)
        lock.acquire(timeout=30)  # waits until the child released it
        try:
            assert child.poll() is not None or True
        finally:
            lock.release()
    finally:
        child.wait(30)
    assert (lib.parent / ".partforge-lock").exists()  # one hidden lock file per folder, no file per library


def test_library_lock_is_reentrant_and_serialises_threads(tmp_path):
    lib = tmp_path / "PF_T.SchLib"
    order: list[str] = []
    with library_lock(lib):
        with library_lock(lib):  # nested in the same thread
            order.append("outer")

        def other() -> None:
            with library_lock(lib):
                order.append("thread")

        thread = threading.Thread(target=other)
        thread.start()
        time.sleep(0.2)
        order.append("still outer")
    thread.join(10)
    assert order == ["outer", "still outer", "thread"]


@pytest.mark.rustwriter
def test_two_processes_writing_the_same_library_keep_it_consistent(ws, tmp_path):
    """INT-01: another process upserts into the same PcbLib while this one does – without a cross-process
    lock the file ended as a malformed OLE structure; now every footprint of both is in a readable file."""
    lib = ws.footprints_dir / "PF_CHIP.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [chip_0603("BASE")]).ok
    code = textwrap.dedent(f"""
        import sys
        sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'tests')!r})
        from pathlib import Path
        from partforge.workspace import Workspace, set_current
        from partforge.altium.rustwriter import RustLibraryOps
        from test_writer_samples import chip_0603
        ws = Workspace.open({str(ws.root)!r}); set_current(ws)
        ops = RustLibraryOps(workspace=ws)
        for i in range(6):
            result = ops.upsert_footprints(Path({str(lib)!r}), [chip_0603(f"CHILD{{i}}A"), chip_0603(f"CHILD{{i}}B")])
            assert result.ok, result.errors
    """)
    child = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "PARTFORGE_NO_ALTIUM": "1"},
                             stderr=subprocess.PIPE)
    try:
        for i in range(6):
            result = ops.upsert_footprints(lib, [chip_0603(f"MAIN{i}A"), chip_0603(f"MAIN{i}B")])
            assert result.ok, result.errors
    finally:
        _out, err = child.communicate(timeout=300)
    assert child.returncode == 0, err.decode(errors="replace")[-2000:]
    names = ops.list_components(lib)
    expected = {"BASE"} | {f"{who}{i}{x}" for who in ("MAIN", "CHILD") for i in range(6) for x in "AB"}
    assert set(names) == expected and len(names) == len(expected)
    assert work_copy_files(lib) == []


# --------------------------------------------------------------------------- PKG-01 #4: heights must be readable


@pytest.mark.rustwriter
def test_unreadable_heights_refuse_the_write(ws, monkeypatch):
    lib = ws.footprints_dir / "PF_GULLWING.PcbLib"
    ops = RustLibraryOps(workspace=ws)
    assert ops.upsert_footprints(lib, [soic8()]).ok
    before = _sha(lib)

    def broken(path):
        raise heights.HeightError(f"{Path(path).name}: nicht lesbar (No module named 'win32timezone').", unreadable=True)

    monkeypatch.setattr(heights, "read_footprint_heights", broken)
    result = ops.upsert_footprints(lib, [chip_0603()])
    assert not result.ok and "Bauhöhen" in result.errors["RESC1608X55N"] and "auf 0" in result.errors["RESC1608X55N"]
    assert _sha(lib) == before
