"""One PartForge process per library folder (INT-01, PKG-02): ``partforge.lock`` refuses a second process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from partforge.workspace import (
    LOCK_FILE,
    LibraryLocked,
    Workspace,
    holds_library_lock,
    library_lock_holder,
    lock_library,
    unlock_library,
)

ROOT = Path(__file__).resolve().parents[1]
_CHILD = textwrap.dedent("""
    import json, sys
    sys.path.insert(0, sys.argv[2])
    from partforge.workspace import LibraryLocked, lock_library
    try:
        lock_library(sys.argv[1])
        print(json.dumps({"locked": True}))
    except LibraryLocked as exc:
        print(json.dumps({"locked": False, "message": str(exc)}))
""")


def _other_process(root: Path) -> dict[str, object]:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run([sys.executable, "-c", _CHILD, str(root), str(ROOT)], capture_output=True, env=env,
                         timeout=60, check=True)
    return json.loads(out.stdout.decode("utf-8").strip().splitlines()[-1])


def test_second_process_is_refused_until_released(tmp_path: Path) -> None:
    root = tmp_path / "lib"
    root.mkdir()
    assert lock_library(root) is True and lock_library(root) is False  # re-entrant in one process
    try:
        assert holds_library_lock(root)
        holder = library_lock_holder(root)
        assert holder is not None and holder["pid"] == os.getpid()
        other = _other_process(root)
        assert other["locked"] is False
        assert "bereits in einem anderen PartForge geöffnet" in str(other["message"])
        assert f"Prozess {os.getpid()}" in str(other["message"])
    finally:
        unlock_library(root)
    assert not holds_library_lock(root)
    assert _other_process(root)["locked"] is True  # released: the other process may open it (and exits)


@pytest.mark.parametrize("release_mode", ["unlock", "exit"], ids=["explicit-unlock", "process-exit"])
def test_api_open_refuses_a_library_held_by_another_process(
    bare_client: TestClient, tmp_path: Path, release_mode: str,
) -> None:
    ws = Workspace.create(tmp_path / "geteilt", name="Geteilt")
    blocker = subprocess.Popen(  # another PartForge holds the library
        [sys.executable, "-c", textwrap.dedent("""
            import json, os, sys
            sys.path.insert(0, sys.argv[2])
            from partforge.workspace import library_lock_holder, lock_library, unlock_library
            lock_library(sys.argv[1])
            holder = library_lock_holder(sys.argv[1])
            assert holder["pid"] == os.getpid()
            print(json.dumps(holder), flush=True)
            if sys.stdin.readline().strip() == "unlock":
                unlock_library(sys.argv[1])
                print("released", flush=True)
            else:
                os._exit(0)  # no explicit unlock: Windows must release the dead owner's byte lock
        """), str(ws.root), str(ROOT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    try:
        assert blocker.stdout is not None
        holder = json.loads(blocker.stdout.readline().decode("utf-8"))
        assert holder == library_lock_holder(ws.root)
        r = bare_client.post("/api/workspace/open", json={"path": str(ws.root)})
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert "bereits in einem anderen PartForge geöffnet" in detail
        assert f"„{ws.root}“" in detail
        for field, label in (("host", "Rechner"), ("user", "Benutzer"), ("pid", "Prozess")):
            assert holder[field] and f"{label} {holder[field]}" in detail
        assert bare_client.get("/api/workspace").json() is None  # nothing opened
        assert not holds_library_lock(ws.root)
        # A Windows venv python.exe can be a redirector: Popen.pid is not necessarily the lock owner's PID.
        # Tell the actual interpreter to release/exit instead of killing only the redirector process.
        out, _ = blocker.communicate(input=f"{release_mode}\n".encode(), timeout=10)
        assert blocker.returncode == 0
        assert out.strip() == (b"released" if release_mode == "unlock" else b"")
    finally:
        if blocker.poll() is None:
            blocker.communicate(input=b"exit\n", timeout=10)
    r = bare_client.post("/api/workspace/open", json={"path": str(ws.root)})
    assert r.status_code == 200, r.text
    assert holds_library_lock(ws.root) and (ws.root / LOCK_FILE).is_file()
    assert bare_client.post("/api/workspace/close").status_code == 200
    assert not holds_library_lock(ws.root)


def test_switching_libraries_releases_the_previous_lock(bare_client: TestClient, tmp_path: Path) -> None:
    a = Workspace.create(tmp_path / "a", name="A")
    b = Workspace.create(tmp_path / "b", name="B")
    assert bare_client.post("/api/workspace/open", json={"path": str(a.root)}).status_code == 200
    assert holds_library_lock(a.root)
    assert bare_client.post("/api/workspace/open", json={"path": str(b.root)}).status_code == 200
    assert holds_library_lock(b.root) and not holds_library_lock(a.root)
    bare_client.post("/api/workspace/close")


def test_lock_error_is_a_runtime_error_with_german_text(tmp_path: Path) -> None:
    exc = LibraryLocked(tmp_path, {"host": "PC1", "user": "anna", "pid": 4711, "since": "2026-10-08T10:00:00"})
    assert "Rechner PC1, Benutzer anna, Prozess 4711, seit 2026-10-08 10:00:00" in str(exc)
    with pytest.raises(RuntimeError):
        raise exc
