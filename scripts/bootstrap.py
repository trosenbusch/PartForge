"""Source start of PartForge – Start-PartForge.cmd runs it on every start.

* **Python environment** ``.venv`` (Python >= 3.11): created if missing or no longer runnable; PartForge and its
  dependencies are (re)installed – pinned by ``constraints.txt`` (the tested versions) – whenever the install
  stamp ``.venv\\.partforge-installed`` differs from the hash of ``pyproject.toml`` + ``constraints.txt``
  (first start, interrupted setup, update with new dependencies). After an install the environment must import
  ``partforge.app``.
* **User interface** ``partforge/web``: built with npm when missing or older than its sources (stamp
  ``.venv\\.partforge-frontend`` = hash of the frontend inputs plus the build it belongs to; a build made outside
  this script counts as current when it is newer than every input). Without Node.js a stale UI is reported once.
* **Start**: the desktop window via ``pythonw`` (detached; a start that ends within a few seconds is diagnosed and
  reported, never silent – if the environment cannot import PartForge, e.g. a package was removed by hand, it is
  reinstalled once), ``--server-only``/``--dev``/``--help``/``--version`` in this console. While a PartForge
  with the same settings runs (``instance.json`` of ``partforge.__main__`` with a live process) nothing is
  installed or rebuilt – the files are in use; the start just brings its window to the front.

Fast when nothing changed (two hashes, no network). Every failure ends with a German explanation and exit code 1
(Start-PartForge.cmd then waits for a key) – never with a Python traceback.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PYTHON = VENV / "Scripts" / "python.exe"
PYTHONW = VENV / "Scripts" / "pythonw.exe"
PYPROJECT = ROOT / "pyproject.toml"
CONSTRAINTS = ROOT / "constraints.txt"
FRONTEND = ROOT / "frontend"
WEB_INDEX = ROOT / "partforge" / "web" / "index.html"
STAMP = VENV / ".partforge-installed"
FRONTEND_STAMP = VENV / ".partforge-frontend"
STAMP_FORMAT = 2
MIN_PYTHON = (3, 11)
#: Inputs of the frontend build (``frontend/…``): folders are hashed recursively.
FRONTEND_INPUTS = ("src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts",
                   "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "openapi.json")
#: Arguments that run PartForge in this console (output visible) instead of the detached window process.
FOREGROUND_ARGS = frozenset({"--server-only", "--dev", "--help", "-h", "--version"})
#: Seconds the window process is watched: an early exit (missing module, broken environment) is reported.
START_WATCH_S = 4.0

PYTHON_DOWNLOAD = (
    "Python 3.13 von https://www.python.org/downloads/windows/ installieren und im Installer "
    "„Add python.exe to PATH“ ankreuzen – oder das fertige Programmpaket (PartForge.exe) verwenden, das weder "
    "Python noch Node.js braucht."
)
PIP_HELP = (
    "Die Python-Pakete konnten nicht installiert werden. Bitte die Internetverbindung prüfen; hinter einem Proxy "
    "die Umgebungsvariable HTTPS_PROXY (z. B. http://proxy:8080) bzw. für einen eigenen Paketspiegel PIP_INDEX_URL "
    "setzen und Start-PartForge.cmd erneut ausführen. Ohne Internet: das fertige Programmpaket (PartForge.exe) "
    "verwenden."
)
NPM_HELP = (
    "Die Benutzeroberfläche konnte nicht gebaut werden (npm, siehe Meldung oben). Bitte die Internetverbindung "
    "prüfen (beim ersten Bau lädt npm die Pakete) oder das fertige Programmpaket (PartForge.exe) verwenden."
)
BROKEN_ENV_HELP = (
    "Die Python-Umgebung ist unvollständig. Bitte den Ordner .venv löschen und Start-PartForge.cmd erneut "
    "ausführen (die Einrichtung dauert dann einige Minuten)."
)
UNEXPECTED_HELP = (
    "Bitte Start-PartForge.cmd erneut ausführen. Hilft das nicht: den Ordner .venv löschen und erneut starten – "
    "oder das fertige Programmpaket (PartForge.exe) verwenden."
)


class BootstrapError(Exception):
    """Start not possible – German message for the user."""


class EnvironmentBroken(BootstrapError):
    """PartForge ended because the environment cannot import it (``detail``: the last line of the error)."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"PartForge hat sich direkt nach dem Start beendet: {detail}\n{BROKEN_ENV_HELP}")
        self.detail = detail


def say(text: str) -> None:
    print(text, flush=True)


# --------------------------------------------------------------------------- helpers


def run(cmd: list[str], *, what: str, help_text: str, cwd: Path | None = None) -> None:
    """Run a setup step; a failure becomes a :class:`BootstrapError` with ``help_text`` (no traceback)."""
    say("» " + " ".join(cmd))
    try:
        code = subprocess.call(cmd, cwd=cwd)
    except OSError as exc:
        raise BootstrapError(f"{what} konnte nicht gestartet werden ({exc}).\n{help_text}") from None
    if code != 0:
        raise BootstrapError(f"{what} ist fehlgeschlagen (Exit-Code {code}).\n{help_text}")


def file_hash(*paths: Path) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"<fehlt>")
        digest.update(b"\0")
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- Python environment


def check_python(version: tuple[int, ...] = tuple(sys.version_info[:3])) -> None:
    if tuple(version[:2]) < MIN_PYTHON:
        found = ".".join(str(n) for n in version)
        raise BootstrapError(f"PartForge benötigt Python 3.11 oder neuer (gefunden: Python {found}).\n{PYTHON_DOWNLOAD}")


def venv_runs() -> bool:
    if not PYTHON.is_file():
        return False
    if Path(sys.prefix).resolve() == VENV.resolve():
        return True  # this script runs in it
    try:
        probe = subprocess.run([str(PYTHON), "-c", "import sys"], capture_output=True, timeout=60, check=False)
        return probe.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def install_stamp() -> dict:
    """What the installed environment must match: pyproject.toml and constraints.txt (content hash)."""
    return {"format": STAMP_FORMAT, "inputs": file_hash(PYPROJECT, CONSTRAINTS)}


def needs_install() -> bool:
    return read_json(STAMP) != install_stamp()


def ensure_venv() -> bool:
    """Create/repair ``.venv`` and install PartForge when needed; ``True`` if something was installed."""
    if not venv_runs():
        if Path(sys.prefix).resolve() == VENV.resolve():
            raise BootstrapError(BROKEN_ENV_HELP)  # cannot rebuild the environment this script runs in
        fresh = not PYTHON.exists()
        say("Richte die Python-Umgebung ein (einmalig, einige Minuten) …" if fresh
            else "Die Python-Umgebung (.venv) startet nicht mehr – sie wird neu eingerichtet …")
        try:
            venv.EnvBuilder(with_pip=True, clear=not fresh).create(VENV)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise BootstrapError(f"Die Python-Umgebung .venv konnte nicht angelegt werden ({exc}).\n"
                                 f"{BROKEN_ENV_HELP}") from None
    if not needs_install():
        return False
    say("Installiere PartForge und die benötigten Python-Pakete (bei Updates erneut) …")
    STAMP.unlink(missing_ok=True)
    if subprocess.run([str(PYTHON), "-m", "pip", "--version"], capture_output=True, check=False).returncode != 0:
        run([str(PYTHON), "-m", "ensurepip", "--upgrade"], what="Die Einrichtung von pip", help_text=BROKEN_ENV_HELP)
    command = [str(PYTHON), "-m", "pip", "install", "--disable-pip-version-check", "-e", str(ROOT)]
    if CONSTRAINTS.is_file():
        command += ["-c", str(CONSTRAINTS)]
    run(command, what="Die Installation der Python-Pakete", help_text=PIP_HELP, cwd=ROOT)
    probe_environment()
    write_json(STAMP, install_stamp())
    return True


def import_probe() -> subprocess.CompletedProcess[str]:
    """``import partforge.app, partforge.__main__`` in the environment (what the window process imports first)."""
    return subprocess.run([str(PYTHON), "-c", "import partforge.app, partforge.__main__"], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def probe_environment() -> None:
    """The installed environment must import the app (catches incomplete installs before the silent pythonw)."""
    probe = import_probe()
    if probe.returncode != 0:
        detail = probe.stderr.strip().splitlines()[-1:] or ["?"]
        raise BootstrapError(f"PartForge lässt sich nicht laden: {detail[0]}\n{BROKEN_ENV_HELP}")


# --------------------------------------------------------------------------- user interface


def frontend_files() -> list[Path]:
    files: list[Path] = []
    for name in FRONTEND_INPUTS:
        path = FRONTEND / name
        if path.is_dir():
            files += sorted(p for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            files.append(path)
    return files


def frontend_hash() -> str:
    digest = hashlib.sha256()
    for path in frontend_files():
        digest.update(path.relative_to(FRONTEND).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def frontend_state() -> str:
    """``missing`` (no build), ``stale`` (sources changed since the build) or ``current``."""
    if not WEB_INDEX.is_file():
        return "missing"
    inputs = frontend_hash()
    stamp = read_json(FRONTEND_STAMP)
    built = WEB_INDEX.stat().st_mtime_ns
    if stamp.get("index_mtime_ns") == built:  # the build this script stamped
        return "current" if stamp.get("inputs") == inputs else "stale"
    # built elsewhere (npm run build by hand, prebuilt copy): current if newer than every input
    newest = max((p.stat().st_mtime_ns for p in frontend_files()), default=0)
    if newest <= built:
        write_json(FRONTEND_STAMP, {"inputs": inputs, "index_mtime_ns": built})
        return "current"
    return "stale"


def find_npm() -> str | None:
    return shutil.which("npm")


def build_script() -> str:
    """npm script that builds the UI for a start: ``build:nocheck`` (TypeScript + Vite) when the project has it –
    the API-type check of ``build`` guards development and must not keep a user on an old UI –, else ``build``."""
    scripts = read_json(FRONTEND / "package.json").get("scripts")
    return "build:nocheck" if isinstance(scripts, dict) and "build:nocheck" in scripts else "build"


def ensure_frontend() -> list[str]:
    """Build the UI when missing or stale; returns German warnings (a stale UI that cannot be rebuilt)."""
    state = frontend_state()
    if state == "current":
        return []
    npm = find_npm()
    if npm is None:
        if state == "missing":
            raise BootstrapError(
                "Die Benutzeroberfläche ist nicht gebaut und Node.js wurde nicht gefunden.\n"
                "Bitte Node.js (LTS) von https://nodejs.org installieren und Start-PartForge.cmd erneut ausführen – "
                "oder das fertige Programmpaket (PartForge.exe) verwenden."
            )
        return _stale_warning_once(
            "Die Benutzeroberfläche ist älter als ihr Quellcode, und Node.js wurde nicht gefunden – PartForge "
            "startet mit der alten Oberfläche, die zu dieser Version nicht passen muss. Bitte Node.js (LTS) von "
            "https://nodejs.org installieren; beim nächsten Start wird die Oberfläche neu gebaut."
        )
    say("Baue die Benutzeroberfläche " + ("(einmalig) …" if state == "missing" else "neu (Quellcode geändert) …"))
    lock = FRONTEND / "package-lock.json"
    installed = FRONTEND / "node_modules" / ".package-lock.json"
    try:
        if not installed.is_file() or (lock.is_file() and installed.stat().st_mtime_ns < lock.stat().st_mtime_ns):
            run([npm, "ci"], what="npm ci", help_text=NPM_HELP, cwd=FRONTEND)
        run([npm, "run", build_script()], what="Der Bau der Oberfläche", help_text=NPM_HELP, cwd=FRONTEND)
    except BootstrapError as exc:
        if not WEB_INDEX.is_file():
            raise
        return [f"{exc}\nPartForge startet mit der bisherigen Oberfläche."]
    if not WEB_INDEX.is_file():
        raise BootstrapError(f"Nach dem Bau fehlt {WEB_INDEX}.\n{NPM_HELP}")
    write_json(FRONTEND_STAMP, {"inputs": frontend_hash(), "index_mtime_ns": WEB_INDEX.stat().st_mtime_ns})
    return []


def _stale_warning_once(text: str) -> list[str]:
    """The stale-UI warning, shown once per source state (not on every start)."""
    stamp = read_json(FRONTEND_STAMP)
    inputs = frontend_hash()
    if stamp.get("warned") == inputs:
        return []
    stamp["warned"] = inputs
    write_json(FRONTEND_STAMP, stamp)
    return [text]


# --------------------------------------------------------------------------- start


def local_data_dir() -> Path:
    """PartForge's folder of this PC (``partforge.config.local_data_dir``): PARTFORGE_HOME or %LOCALAPPDATA%."""
    home = os.environ.get("PARTFORGE_HOME")
    if home:
        return Path(home)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "PartForge"


def running_instance() -> int | None:
    """PID of a PartForge that already runs with these settings (``instance.json`` of ``partforge.__main__``)."""
    pid = read_json(local_data_dir() / "instance.json").get("pid")
    if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
        return None
    return pid if process_alive(pid) else None


def process_alive(pid: int) -> bool:
    """True if ``pid`` is a running python(w).exe/PartForge.exe (never signals the process)."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return False
        size = wintypes.DWORD(1024)
        name = ctypes.create_unicode_buffer(1024)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(size)):
            return False
        return Path(name.value).name.lower() in ("python.exe", "pythonw.exe", "partforge.exe")
    finally:
        kernel32.CloseHandle(handle)


def launch(args: list[str], *, watch_s: float = START_WATCH_S) -> int:
    """Start PartForge; :class:`EnvironmentBroken` if it ended because it cannot be imported."""
    if FOREGROUND_ARGS.intersection(args) or not PYTHONW.is_file():
        code = subprocess.call([str(PYTHON), "-m", "partforge", *args], cwd=ROOT)
        if code in (0, 130, 3221225786):  # 0xC000013A: console closed / Strg+C
            return code
        raise_if_unimportable()
        say(f"\nPartForge wurde mit Fehler beendet (Exit-Code {code}) – siehe Meldung oben.")
        return code
    say("PartForge wird gestartet …")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen([str(PYTHONW), "-m", "partforge", *args], cwd=ROOT, creationflags=flags,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        code = proc.wait(timeout=watch_s)
    except subprocess.TimeoutExpired:
        return 0  # still running: the window is opening
    if code == 0:
        return 0  # e.g. a second start that brought the running window to the front
    raise_if_unimportable()
    raise BootstrapError(
        f"PartForge hat sich direkt nach dem Start beendet (Exit-Code {code}). Details stehen im Protokoll "
        "%LOCALAPPDATA%\\PartForge\\logs\\partforge.log. Zum Ansehen der Meldungen "
        "„Start-PartForge.cmd --server-only“ in einer Eingabeaufforderung ausführen."
    )


def raise_if_unimportable() -> None:
    """:class:`EnvironmentBroken` with the import error if the environment cannot load PartForge."""
    probe = import_probe()
    if probe.returncode != 0:
        lines = [line for line in probe.stderr.strip().splitlines() if line.strip()]
        raise EnvironmentBroken(lines[-1] if lines else f"Importfehler (Exit-Code {probe.returncode})")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    os.chdir(ROOT)
    try:
        check_python()
        pid = running_instance() if PYTHON.is_file() else None
        if pid is not None:
            # never reinstall packages or rebuild the UI under a running PartForge (files in use)
            say(f"PartForge läuft bereits (Prozess {pid}) – das Fenster wird in den Vordergrund geholt.")
            if needs_install() or frontend_state() != "current":
                say("Hinweis: Python-Pakete oder Oberfläche haben sich geändert – sie werden eingerichtet, sobald "
                    "PartForge beendet und erneut gestartet wird.")
            return launch(args)
        ensure_venv()
        warnings = ensure_frontend()
        for warning in warnings:
            say(f"\nHinweis: {warning}")
        if warnings:
            pause("\nWeiter mit der Eingabetaste … ")
        try:
            return launch(args)
        except EnvironmentBroken as exc:  # e.g. a package removed by hand although the stamp is current: repair once
            say(f"\nPartForge ließ sich nicht laden ({exc.detail}) – die Python-Umgebung wird repariert …")
            STAMP.unlink(missing_ok=True)
            ensure_venv()
            return launch(args)
    except BootstrapError as exc:
        print(f"\n{exc}", file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("\nAbgebrochen.", file=sys.stderr, flush=True)
        return 1
    except Exception as exc:  # noqa: BLE001 - the user gets a German sentence, never a traceback
        print(f"\nUnerwarteter Fehler beim Start ({type(exc).__name__}: {exc}).\n{UNEXPECTED_HELP}",
              file=sys.stderr, flush=True)
        return 1


def pause(prompt: str) -> None:
    """Wait for Enter in an interactive console (NUL counts as a terminal on Windows: EOF ends the wait)."""
    if sys.stdin is None or not sys.stdin.isatty():
        return
    try:
        input(prompt)
    except (EOFError, OSError):
        say("")


if __name__ == "__main__":
    raise SystemExit(main())
