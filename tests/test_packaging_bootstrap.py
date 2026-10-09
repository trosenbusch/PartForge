"""Source start: scripts/bootstrap.py and Start-PartForge.cmd (packaging findings PKG-03 and PKG-04).

* bootstrap: install stamp (pyproject.toml + constraints.txt), UI build stamp, German errors without traceback,
  pinned install, a start that dies right away is diagnosed instead of failing silently;
* Start-PartForge.cmd (real cmd.exe, ``slow``): German help without Python, with only the Microsoft Store
  placeholder or an old Python; an existing ``.venv`` with a prebuilt UI still goes through bootstrap.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
CMD = ROOT / "Start-PartForge.cmd"


def _load_bootstrap() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pf_scripts_bootstrap_test", ROOT / "scripts" / "bootstrap.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def bs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """bootstrap with every path redirected into ``tmp_path`` (never the real .venv or partforge/web)."""
    module = _load_bootstrap()
    root = tmp_path / "repo"
    (root / "frontend" / "src").mkdir(parents=True)
    (root / "partforge" / "web").mkdir(parents=True)
    (root / ".venv" / "Scripts").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (root / "constraints.txt").write_text("fastapi==1.0\n", encoding="utf-8")
    paths = {
        "ROOT": root, "VENV": root / ".venv", "PYTHON": root / ".venv/Scripts/python.exe",
        "PYTHONW": root / ".venv/Scripts/pythonw.exe", "PYPROJECT": root / "pyproject.toml",
        "CONSTRAINTS": root / "constraints.txt", "FRONTEND": root / "frontend",
        "WEB_INDEX": root / "partforge/web/index.html", "STAMP": root / ".venv/.partforge-installed",
        "FRONTEND_STAMP": root / ".venv/.partforge-frontend",
    }
    for name, value in paths.items():
        monkeypatch.setattr(module, name, value)
    return module


def _touch(path: Path, text: str = "x", mtime_ns: int | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


# --------------------------------------------------------------------------- install stamp (PKG-03)


def test_install_stamp_follows_pyproject_and_constraints(bs: ModuleType) -> None:
    assert bs.needs_install()  # no stamp: first start or interrupted setup
    bs.write_json(bs.STAMP, bs.install_stamp())
    assert not bs.needs_install()
    bs.PYPROJECT.write_text("[project]\nname = 'x'\ndependencies = ['tzdata']\n", encoding="utf-8")
    assert bs.needs_install()  # update with a new dependency
    bs.write_json(bs.STAMP, bs.install_stamp())
    bs.CONSTRAINTS.write_text("fastapi==2.0\n", encoding="utf-8")
    assert bs.needs_install()


def test_old_stamp_format_reinstalls(bs: ModuleType) -> None:
    bs.STAMP.write_text("ok", encoding="utf-8")  # stamp of the previous bootstrap
    assert bs.needs_install()


def test_install_is_pinned_and_checked(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """PKG-04: no "pip install --upgrade pip", constraints.txt applies; PKG-03: the stamp is written only after the
    environment imports the app."""
    commands: list[list[str]] = []
    monkeypatch.setattr(bs, "venv_runs", lambda: True)
    monkeypatch.setattr(bs, "run", lambda cmd, **kw: commands.append(cmd))
    monkeypatch.setattr(bs.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    probes: list[bool] = []
    monkeypatch.setattr(bs, "probe_environment", lambda: probes.append(True))
    assert bs.ensure_venv() is True
    assert len(commands) == 1
    command = commands[0]
    assert command[1:5] == ["-m", "pip", "install", "--disable-pip-version-check"]
    assert command[command.index("-c") + 1] == str(bs.CONSTRAINTS) and "--upgrade" not in command
    assert probes == [True] and not bs.needs_install()
    assert bs.ensure_venv() is False  # current stamp: nothing to do


def test_failed_probe_leaves_no_stamp(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bs, "venv_runs", lambda: True)
    monkeypatch.setattr(bs, "run", lambda cmd, **kw: None)
    monkeypatch.setattr(bs.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, "", "Traceback …\nModuleNotFoundError: No module named 'uvicorn'\n"))
    with pytest.raises(bs.BootstrapError, match="No module named 'uvicorn'") as info:
        bs.ensure_venv()
    assert ".venv löschen" in str(info.value)
    assert bs.needs_install()  # next start installs again


# --------------------------------------------------------------------------- German errors (PKG-04)


def test_failed_step_is_german_without_traceback(bs: ModuleType) -> None:
    with pytest.raises(bs.BootstrapError) as info:
        bs.run([sys.executable, "-c", "raise SystemExit(3)"], what="Die Installation der Python-Pakete",
               help_text=bs.PIP_HELP)
    message = str(info.value)
    assert "Die Installation der Python-Pakete ist fehlgeschlagen (Exit-Code 3)" in message
    assert "HTTPS_PROXY" in message and "PIP_INDEX_URL" in message and "Programmpaket" in message
    with pytest.raises(bs.BootstrapError, match="konnte nicht gestartet werden"):
        bs.run([str(bs.ROOT / "fehlt.exe")], what="npm ci", help_text=bs.NPM_HELP)


def test_main_reports_errors_without_traceback(bs: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                               capsys: pytest.CaptureFixture[str]) -> None:
    def fail() -> bool:
        raise bs.BootstrapError(f"Die Installation der Python-Pakete ist fehlgeschlagen (Exit-Code 1).\n{bs.PIP_HELP}")

    monkeypatch.setattr(bs, "ensure_venv", fail)
    monkeypatch.setattr(bs.os, "chdir", lambda path: None)
    assert bs.main([]) == 1
    err = capsys.readouterr().err
    assert "Internetverbindung" in err and "Traceback" not in err


def test_pause_survives_a_closed_console(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """NUL counts as a terminal on Windows: input() then raises EOFError – no traceback (found in the e2e run)."""

    class Console:
        def isatty(self) -> bool:
            return True

    def eof(prompt: str = "") -> str:
        raise EOFError

    monkeypatch.setattr(bs.sys, "stdin", Console())
    monkeypatch.setattr("builtins.input", eof)
    bs.pause("Weiter … ")


def test_unexpected_errors_are_reported_in_german(bs: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    def boom() -> bool:
        raise PermissionError(13, "Zugriff verweigert", "C:\\x\\.venv\\Lib")

    monkeypatch.setattr(bs.os, "chdir", lambda path: None)
    monkeypatch.setattr(bs, "running_instance", lambda: None)
    monkeypatch.setattr(bs, "ensure_venv", boom)
    assert bs.main([]) == 1
    err = capsys.readouterr().err
    assert "Unerwarteter Fehler beim Start (PermissionError" in err and "Traceback" not in err


def test_old_python_gets_the_download_hint(bs: ModuleType) -> None:
    with pytest.raises(bs.BootstrapError) as info:
        bs.check_python((3, 10, 4))
    message = str(info.value)
    assert "Python 3.11 oder neuer" in message and "3.10.4" in message
    assert "https://www.python.org/downloads/windows/" in message and "Programmpaket" in message
    bs.check_python((3, 13, 5))


# --------------------------------------------------------------------------- user interface (PKG-03)


def test_frontend_state(bs: ModuleType) -> None:
    src = _touch(bs.FRONTEND / "src" / "main.tsx", "a", mtime_ns=1_000_000_000)
    _touch(bs.FRONTEND / "package-lock.json", "{}", mtime_ns=1_000_000_000)
    assert bs.frontend_state() == "missing"
    _touch(bs.WEB_INDEX, "<html>", mtime_ns=2_000_000_000)
    assert bs.frontend_state() == "current"  # built after the last source change (e.g. npm run build by hand)
    assert json.loads(bs.FRONTEND_STAMP.read_text(encoding="utf-8"))["index_mtime_ns"] == 2_000_000_000
    _touch(src, "b", mtime_ns=1_000_000_000)  # changed sources with an old file time (e.g. unpacked zip)
    assert bs.frontend_state() == "stale"
    bs.FRONTEND_STAMP.unlink()
    _touch(src, "c", mtime_ns=3_000_000_000)  # changed sources, no stamp: newer than the build
    assert bs.frontend_state() == "stale"


def test_missing_ui_without_node_is_an_error(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bs, "find_npm", lambda: None)
    with pytest.raises(bs.BootstrapError, match="nodejs.org"):
        bs.ensure_frontend()


def test_stale_ui_without_node_is_reported_once(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _touch(bs.WEB_INDEX, "<html>", mtime_ns=1_000_000_000)
    _touch(bs.FRONTEND / "src" / "main.tsx", "a", mtime_ns=2_000_000_000)
    monkeypatch.setattr(bs, "find_npm", lambda: None)
    first = bs.ensure_frontend()
    assert len(first) == 1 and "älter als ihr Quellcode" in first[0]
    assert bs.ensure_frontend() == []  # same sources: not on every start


def test_stale_ui_is_rebuilt(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _touch(bs.WEB_INDEX, "<html>", mtime_ns=1_000_000_000)
    _touch(bs.FRONTEND / "src" / "main.tsx", "a", mtime_ns=2_000_000_000)
    _touch(bs.FRONTEND / "package-lock.json", "{}", mtime_ns=1_000_000_000)
    _touch(bs.FRONTEND / "node_modules" / ".package-lock.json", "{}", mtime_ns=1_500_000_000)
    monkeypatch.setattr(bs, "find_npm", lambda: "npm.cmd")
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kw: Any) -> None:
        commands.append(cmd)
        _touch(bs.WEB_INDEX, "<html>neu", mtime_ns=3_000_000_000)

    monkeypatch.setattr(bs, "run", fake_run)
    assert bs.ensure_frontend() == []
    assert commands == [["npm.cmd", "run", "build"]]  # node_modules current: no npm ci
    assert bs.frontend_state() == "current"


def test_ui_build_for_a_start_skips_the_api_type_check(bs: ModuleType) -> None:
    """The API-type check of ``npm run build`` guards development; a start builds with ``build:nocheck``."""
    assert bs.build_script() == "build"  # no package.json: the canonical script
    _touch(bs.FRONTEND / "package.json", json.dumps({"scripts": {"build": "x && y", "build:nocheck": "y"}}))
    assert bs.build_script() == "build:nocheck"
    real = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))["scripts"]
    assert "gen:api:check" not in real.get("build:nocheck", "")


def test_failed_rebuild_keeps_the_old_ui(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _touch(bs.WEB_INDEX, "<html>", mtime_ns=1_000_000_000)
    _touch(bs.FRONTEND / "src" / "main.tsx", "a", mtime_ns=2_000_000_000)
    monkeypatch.setattr(bs, "find_npm", lambda: "npm.cmd")

    def fail(cmd: list[str], **kw: Any) -> None:
        raise bs.BootstrapError(f"npm ci ist fehlgeschlagen (Exit-Code 1).\n{bs.NPM_HELP}")

    monkeypatch.setattr(bs, "run", fail)
    warnings = bs.ensure_frontend()
    assert len(warnings) == 1 and "bisherigen Oberfläche" in warnings[0]


# --------------------------------------------------------------------------- start (PKG-03)


class _Proc:
    def __init__(self, code: int | None) -> None:
        self.code = code

    def wait(self, timeout: float | None = None) -> int:
        if self.code is None:
            raise subprocess.TimeoutExpired("pythonw", timeout or 0)
        return self.code


def test_window_start_that_dies_is_diagnosed(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    """S5/S7 of PKG-03: pythonw without uvicorn exited silently – now the reason reaches the user."""
    bs.PYTHONW.write_bytes(b"")
    monkeypatch.setattr(bs.subprocess, "Popen", lambda *a, **k: _Proc(1))
    monkeypatch.setattr(bs.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, "", "Traceback (most recent call last):\n  …\nModuleNotFoundError: No module named 'uvicorn'\n"))
    with pytest.raises(bs.BootstrapError) as info:
        bs.launch([], watch_s=0.1)
    assert "No module named 'uvicorn'" in str(info.value) and ".venv löschen" in str(info.value)


def test_unimportable_environment_is_repaired_once(bs: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    """S5c: stamp current, but uvicorn removed by hand – the start reinstalls once instead of failing."""
    monkeypatch.setattr(bs.os, "chdir", lambda path: None)
    monkeypatch.setattr(bs, "running_instance", lambda: None)
    monkeypatch.setattr(bs, "ensure_frontend", list)
    installs: list[bool] = []
    monkeypatch.setattr(bs, "ensure_venv", lambda: installs.append(bs.STAMP.exists()) or False)
    bs.write_json(bs.STAMP, bs.install_stamp())
    attempts: list[int] = []

    def launch(args: list[str]) -> int:
        attempts.append(1)
        if len(attempts) == 1:
            raise bs.EnvironmentBroken("ModuleNotFoundError: No module named 'uvicorn'")
        return 0

    monkeypatch.setattr(bs, "launch", launch)
    assert bs.main([]) == 0
    assert installs == [True, False]  # second ensure_venv without stamp: reinstall
    assert "wird repariert" in capsys.readouterr().out


def test_environment_still_broken_after_repair_is_reported(bs: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                                           capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(bs.os, "chdir", lambda path: None)
    monkeypatch.setattr(bs, "running_instance", lambda: None)
    monkeypatch.setattr(bs, "ensure_frontend", list)
    monkeypatch.setattr(bs, "ensure_venv", lambda: False)

    def launch(args: list[str]) -> int:
        raise bs.EnvironmentBroken("ImportError: DLL load failed while importing win32api")

    monkeypatch.setattr(bs, "launch", launch)
    assert bs.main([]) == 1
    err = capsys.readouterr().err
    assert "DLL load failed" in err and ".venv löschen" in err and "Traceback" not in err


def test_window_start_failing_later_points_to_the_log(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    bs.PYTHONW.write_bytes(b"")
    monkeypatch.setattr(bs.subprocess, "Popen", lambda *a, **k: _Proc(2))
    monkeypatch.setattr(bs.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
    with pytest.raises(bs.BootstrapError, match="partforge.log"):
        bs.launch([], watch_s=0.1)


def test_running_window_returns_at_once(bs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    bs.PYTHONW.write_bytes(b"")
    started: list[list[str]] = []

    def popen(cmd: list[str], **kw: Any) -> _Proc:
        started.append(cmd)
        return _Proc(None)

    monkeypatch.setattr(bs.subprocess, "Popen", popen)
    assert bs.launch(["--workspace", "C:/Bib"], watch_s=0.1) == 0
    assert started == [[str(bs.PYTHONW), "-m", "partforge", "--workspace", "C:/Bib"]]


def test_running_instance_needs_a_live_python(bs: ModuleType, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTFORGE_HOME", str(tmp_path / "home"))
    instance = tmp_path / "home" / "instance.json"
    assert bs.running_instance() is None  # no instance.json
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        bs.write_json(instance, {"pid": child.pid, "port": 48765})
        assert bs.running_instance() == child.pid
        bs.write_json(instance, {"pid": os.getpid()})
        assert bs.running_instance() is None  # this process
    finally:
        child.kill()
        child.wait()
    bs.write_json(instance, {"pid": child.pid})
    assert bs.running_instance() is None  # ended (stale instance.json after a crash)


def test_no_setup_under_a_running_instance(bs: ModuleType, monkeypatch: pytest.MonkeyPatch,
                                           capsys: pytest.CaptureFixture[str]) -> None:
    """Packages and UI files are in use while PartForge runs: the start only brings the window to the front."""
    bs.PYTHON.write_bytes(b"")
    monkeypatch.setattr(bs, "running_instance", lambda: 4321)
    monkeypatch.setattr(bs.os, "chdir", lambda path: None)

    def must_not_run() -> None:
        raise AssertionError("setup under a running PartForge")

    monkeypatch.setattr(bs, "ensure_venv", must_not_run)
    monkeypatch.setattr(bs, "ensure_frontend", must_not_run)
    monkeypatch.setattr(bs, "launch", lambda args: 0)
    assert bs.main([]) == 0
    out = capsys.readouterr().out
    assert "läuft bereits (Prozess 4321)" in out and "erneut gestartet" in out  # no stamp yet: update pending


@pytest.mark.parametrize("arg", ["--server-only", "--dev", "--version"])
def test_console_modes_run_in_the_foreground(bs: ModuleType, monkeypatch: pytest.MonkeyPatch, arg: str) -> None:
    bs.PYTHONW.write_bytes(b"")
    calls: list[list[str]] = []
    monkeypatch.setattr(bs.subprocess, "call", lambda cmd, **kw: calls.append(cmd) or 0)
    assert bs.launch([arg]) == 0
    assert calls == [[str(bs.PYTHON), "-m", "partforge", arg]]


# --------------------------------------------------------------------------- Start-PartForge.cmd


def test_start_script_is_ascii_with_crlf() -> None:
    """cmd.exe reads batch files in the OEM code page: no umlauts; CRLF keeps goto/call labels reliable."""
    raw = CMD.read_bytes()
    assert all(b < 128 for b in raw)
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_start_script_routes_every_source_start_through_bootstrap() -> None:
    """PKG-03: no shortcut to pythonw when .venv and partforge\\web exist – bootstrap checks the environment."""
    text = CMD.read_text(encoding="ascii")
    assert "pythonw" not in text.lower()
    assert '"%PF_VENV_PY%" "%~dp0scripts\\bootstrap.py" %*' in text
    assert "py -3.13" in text  # the tested version first


STUB_SOURCE = r"""
using System;
public static class Program {
    public static int Main(string[] args) {
        Console.Error.WriteLine("Python was not found; run without arguments to install from the Microsoft Store, "
            + "or disable this shortcut from Settings > Apps > Advanced app settings > App execution aliases.");
        string code = Environment.GetEnvironmentVariable("PF_STUB_EXIT");
        return code == null ? 9009 : int.Parse(code);
    }
}
"""


@pytest.fixture(scope="module")
def python_stub(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ``python.exe`` like the Microsoft Store placeholder (exit code 9009, or ``PF_STUB_EXIT``)."""
    folder = tmp_path_factory.mktemp("stub")
    (folder / "stub.cs").write_text(STUB_SOURCE, encoding="utf-8")
    script = ("Add-Type -TypeDefinition (Get-Content -Raw 'stub.cs') -OutputAssembly 'python.exe' "
              "-OutputType ConsoleApplication")
    result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], cwd=folder,
                            capture_output=True, text=True, timeout=120, check=False)
    if not (folder / "python.exe").is_file():
        pytest.skip(f"Platzhalter-python.exe nicht kompilierbar: {result.stderr[:300]}")
    return folder


def _copy_repo(tmp_path: Path) -> Path:
    """Minimal source tree in a folder with a space and an umlaut (as users unpack it)."""
    copy = tmp_path / "Part Forge Übung"
    (copy / "scripts").mkdir(parents=True)
    for name in ("Start-PartForge.cmd", "pyproject.toml", "constraints.txt", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, copy / name)
    shutil.copy2(ROOT / "scripts" / "bootstrap.py", copy / "scripts" / "bootstrap.py")
    (copy / "partforge" / "web").mkdir(parents=True)
    (copy / "partforge" / "__init__.py").write_text('__version__ = "0"\n', encoding="utf-8")
    (copy / "partforge" / "web" / "index.html").write_text("<html></html>", encoding="utf-8")
    return copy


def _run_cmd(copy: Path, *, path_dirs: list[Path], extra_env: dict[str, str] | None = None,
             timeout: float = 120) -> subprocess.CompletedProcess[str]:
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    keep = ("SystemRoot", "SystemDrive", "ComSpec", "PATHEXT", "TEMP", "TMP", "USERPROFILE", "APPDATA",
            "LOCALAPPDATA", "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "NUMBER_OF_PROCESSORS")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PATH"] = os.pathsep.join([*(str(p) for p in path_dirs), str(system32)])
    env["PYTHONIOENCODING"] = "utf-8"
    env["PARTFORGE_HOME"] = str(copy.parent / "home")
    env["PARTFORGE_NO_ALTIUM"] = "1"
    env.update(extra_env or {})
    return subprocess.run(["cmd.exe", "/d", "/c", str(copy / "Start-PartForge.cmd"), "--server-only"],
                          cwd=copy.parent, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=timeout, encoding="utf-8", errors="replace", check=False)


@pytest.mark.slow
def test_cmd_without_python_prints_german_help(tmp_path: Path) -> None:
    result = _run_cmd(_copy_repo(tmp_path), path_dirs=[])
    assert result.returncode == 1
    out = result.stdout
    assert "Python 3.11 oder neuer wurde nicht gefunden" in out
    assert "https://www.python.org/downloads/windows/" in out and "Add python.exe to PATH" in out
    assert "Programmpaket" in out


@pytest.mark.slow
def test_cmd_skips_the_store_placeholder(tmp_path: Path, python_stub: Path) -> None:
    """S2 of PKG-04: the App Execution Alias (exit 9009) is no Python – German help instead of its English text."""
    result = _run_cmd(_copy_repo(tmp_path), path_dirs=[python_stub])
    assert result.returncode == 1
    assert "Python 3.11 oder neuer wurde nicht gefunden" in result.stdout
    assert "https://www.python.org/downloads/windows/" in result.stdout


@pytest.mark.slow
def test_cmd_names_a_too_old_python(tmp_path: Path, python_stub: Path) -> None:
    """S3 of PKG-04: only Python 3.10 – the check exits 1 – says so and gives the download hint."""
    result = _run_cmd(_copy_repo(tmp_path), path_dirs=[python_stub], extra_env={"PF_STUB_EXIT": "1"})
    assert result.returncode == 1
    assert "zu alte Python-Version" in result.stdout and "https://www.python.org/downloads/windows/" in result.stdout


@pytest.mark.slow
def test_cmd_with_incomplete_venv_and_prebuilt_ui_goes_through_bootstrap(tmp_path: Path) -> None:
    """S4/S5 of PKG-03: .venv without packages (interrupted setup) plus a prebuilt UI used to start pythonw
    silently and die. Now bootstrap reinstalls – offline that fails with a German message and exit code 1."""
    copy = _copy_repo(tmp_path)
    base_python = Path(sys.base_prefix) / "python.exe"
    subprocess.run([str(base_python), "-m", "venv", "--without-pip", str(copy / ".venv")], check=True, timeout=300)
    offline = {"PIP_INDEX_URL": "http://127.0.0.1:9/simple/", "PIP_RETRIES": "0", "PIP_TIMEOUT": "2",
               "PIP_NO_CACHE_DIR": "1", "PIP_CONFIG_FILE": os.devnull, "PIP_FIND_LINKS": ""}
    result = _run_cmd(copy, path_dirs=[], extra_env=offline, timeout=600)
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "Die Installation der Python-Pakete ist fehlgeschlagen" in output
    assert "HTTPS_PROXY" in output and "Programmpaket" in output
    assert "Traceback" not in output
    assert not (copy / ".venv" / ".partforge-installed").exists()
