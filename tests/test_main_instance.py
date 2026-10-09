"""Start-up (PKG-02): one PartForge per settings folder, the server port bound once, German errors."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from partforge import __main__ as main_mod

ROOT = Path(__file__).resolve().parents[1]


def _start(home: Path, *args: str) -> subprocess.Popen[bytes]:
    env = {**os.environ, "PARTFORGE_HOME": str(home), "PARTFORGE_NO_ALTIUM": "1", "PYTHONIOENCODING": "utf-8"}
    env.pop("PARTFORGE_ALLOW_REAL_AI", None)
    return subprocess.Popen([sys.executable, "-m", "partforge", "--server-only", *args], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _wait_health(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError("Server startet nicht")


def _free() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_second_start_with_the_same_settings_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    port = _free()
    first = _start(home, "--port", str(port))
    try:
        _wait_health(port)
        info = json.loads((home / "instance.json").read_text(encoding="utf-8"))
        assert info["port"] == port and info["pid"] > 0 and info["mode"] == "server"  # pid: the venv launcher starts a child
        second = _start(home, "--port", str(_free()))
        out, err = second.communicate(timeout=60)
        assert second.returncode == main_mod.EXIT_ALREADY_RUNNING
        assert "PartForge läuft bereits" in err.decode("utf-8") and str(port) in err.decode("utf-8")
        other_home = _start(tmp_path / "other", "--port", str(_free()))  # another settings folder may run
        try:
            time.sleep(0.5)
            assert other_home.poll() is None
        finally:
            other_home.kill()
            other_home.wait(20)
    finally:
        first.kill()
        first.wait(20)


def test_busy_explicit_port_is_a_german_error(tmp_path: Path) -> None:
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        port = int(blocker.getsockname()[1])
        proc = _start(tmp_path / "home", "--port", str(port))
        out, err = proc.communicate(timeout=60)
    assert proc.returncode == main_mod.EXIT_PORT_BUSY
    text = err.decode("utf-8")
    assert f"Port {port} ist belegt" in text and "läuft auf" not in out.decode("utf-8")


def test_bind_server_socket_falls_back_only_without_a_fixed_port() -> None:
    first = main_mod.bind_server_socket(0, fixed=False)
    try:
        taken = int(first.getsockname()[1])
        other = main_mod.bind_server_socket(taken, fixed=False)  # preferred port taken: a free one
        try:
            assert int(other.getsockname()[1]) != taken
        finally:
            other.close()
        with pytest.raises(main_mod.PortInUse, match="ist belegt"):
            main_mod.bind_server_socket(taken, fixed=True)
    finally:
        first.close()
