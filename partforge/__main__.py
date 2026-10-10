"""Start PartForge: local API server plus desktop window (pywebview / WebView2).

    python -m partforge                 # Desktop-Fenster
    python -m partforge --browser       # im Standardbrowser öffnen
    python -m partforge --server-only   # nur API-Server (z. B. für Tests/Entwicklung)
    python -m partforge --dev           # fester Port 8765 und Token "dev" (für Vite-Dev-Server)

One instance per Windows user and settings folder (named mutex ``Local\\PartForge-<hash>``): a second
start brings the running window to the front (or opens its address) and ends – it never runs a second
server on the same library and settings. Each library is additionally locked by the process that has it
open (``partforge.lock``, :func:`partforge.workspace.lock_library`), which also covers other users and PCs.

The server socket is bound once (preferred port 48765 – a stable origin keeps browser storage such as
theme and layout –, else a free one) and handed to uvicorn, so the port cannot be taken in between; an
explicit ``--port`` that is in use ends with a localized message (exit code 2).

Logs: ``%LOCALAPPDATA%\\PartForge\\logs\\partforge.log`` (rotating, 5 × 2 MB); WebView2 profile:
``%LOCALAPPDATA%\\PartForge\\webview`` (moved there from the roaming folder of older versions).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import logging
import logging.handlers
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from . import __version__
from .app import create_app, http_protocol
from .config import app_data_dir, load_settings, local_data_dir, log_dir
from .desktop import DesktopApi, native_text, webview_localization
from .logsafe import RedactTokenFilter

PREFERRED_PORT = 48765  # stable origin -> browser storage (theme, layout) survives restarts
DEV_PORT = 8765
LOG_BYTES = 2 * 1024 * 1024
LOG_BACKUPS = 4  # partforge.log + 4 older files = 5 × 2 MB
INSTANCE_FILE = "instance.json"
WINDOW_TITLE = "PartForge"
EXIT_ALREADY_RUNNING = 1
EXIT_PORT_BUSY = 2

log = logging.getLogger("partforge")
_mutex: Any = None  # keeps the single-instance mutex alive for the whole process


class PortInUse(RuntimeError):
    """The requested port is taken (localized message)."""


# --------------------------------------------------------------------------- single instance


def _instance_key() -> str:
    return hashlib.sha1(os.path.normcase(str(app_data_dir().resolve())).encode("utf-8")).hexdigest()[:16]


def _acquire_instance() -> bool:
    """Take the single-instance mutex; ``False`` if another PartForge with the same settings folder runs."""
    global _mutex
    try:
        import win32api
        import win32event
        import winerror
    except ImportError:  # pragma: no cover - not on Windows: no guard
        return True
    handle = win32event.CreateMutex(None, False, f"Local\\PartForge-{_instance_key()}")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        with contextlib.suppress(Exception):
            win32api.CloseHandle(handle)
        return False
    _mutex = handle
    return True


def _instance_path() -> Path:
    return local_data_dir() / INSTANCE_FILE


def _write_instance(port: int, mode: str) -> None:
    info = {"pid": os.getpid(), "port": port, "url": f"http://127.0.0.1:{port}/", "mode": mode,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": __version__}
    with contextlib.suppress(OSError):
        _instance_path().write_text(json.dumps(info), encoding="utf-8")


def _remove_instance() -> None:
    try:
        info = json.loads(_instance_path().read_text(encoding="utf-8"))
        if info.get("pid") == os.getpid():
            _instance_path().unlink()
    except (OSError, ValueError):
        pass


def _running_instance() -> dict[str, Any]:
    try:
        info = json.loads(_instance_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return info if isinstance(info, dict) else {}


def _focus_window(pid: int | None) -> bool:
    """Bring the PartForge window of process ``pid`` to the front (restored if minimised)."""
    if not pid:
        return False
    try:
        import win32con
        import win32gui
        import win32process
    except ImportError:  # pragma: no cover
        return False
    found: list[int] = []

    def visit(hwnd: int, _extra: Any) -> bool:
        if (win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == pid
                and win32gui.GetWindowText(hwnd).startswith(WINDOW_TITLE)):
            found.append(hwnd)
        return True

    with contextlib.suppress(Exception):
        win32gui.EnumWindows(visit, None)
    if not found:
        return False
    hwnd = found[0]
    with contextlib.suppress(Exception):
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    return True


def _message_box(text: str) -> None:
    with contextlib.suppress(Exception):
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, WINDOW_TITLE, 0x40)  # MB_ICONINFORMATION


def _already_running(args: argparse.Namespace) -> int:
    """A second start: hand over to the running PartForge and end."""
    info = _running_instance()
    url = info.get("url")
    pid = info.get("pid")
    where = native_text(" (process {pid}, {url})", " (Prozess {pid}, {url})").format(pid=pid, url=url) if pid and url else ""
    text = native_text(
        "PartForge is already running{where}. A second PartForge with the same settings will not start — "
        "two programs would overwrite each other's library and settings.",
        "PartForge läuft bereits{where}. Es wird kein zweites PartForge mit denselben Einstellungen gestartet – "
        "zwei Programme würden sich gegenseitig Bibliothek und Einstellungen überschreiben.",
    ).format(where=where)
    log.warning(text)
    if args.server_only or args.dev:
        print(text, file=sys.stderr, flush=True)
        return EXIT_ALREADY_RUNNING
    if _focus_window(pid if isinstance(pid, int) else None):
        return 0
    if url and isinstance(url, str):  # the running instance has no window (browser or server mode)
        webbrowser.open(url)
        return 0
    _message_box(text)
    return 0


# --------------------------------------------------------------------------- server socket


def _new_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: no other process may bind the port as well
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    return sock


def bind_server_socket(port: int | None, *, fixed: bool) -> socket.socket:
    """Bound socket on 127.0.0.1: ``port`` (``fixed``: :class:`PortInUse` if taken, else a free port)."""
    if port:
        sock = _new_socket()
        try:
            sock.bind(("127.0.0.1", port))
            return sock
        except OSError as exc:
            sock.close()
            if fixed:
                raise PortInUse(
                    native_text(
                        "Port {port} is in use (another program, such as PartForge, may already be running there). "
                        "Choose another port with --port or stop the other program.",
                        "Port {port} ist belegt (vermutlich läuft dort schon ein Programm, z. B. ein anderes PartForge). "
                        "Bitte einen anderen Port mit --port angeben oder das andere Programm beenden.",
                    ).format(port=port)
                ) from exc
    sock = _new_socket()
    sock.bind(("127.0.0.1", 0))
    return sock


def _free_port(preferred: int | None = None) -> int:
    """A free port (``preferred`` if it is free) – kept for scripts; :func:`bind_server_socket` keeps it bound."""
    sock = bind_server_socket(preferred, fixed=False)
    try:
        return int(sock.getsockname()[1])
    finally:
        sock.close()


# --------------------------------------------------------------------------- start-up helpers


def _reopen_workspace(path: str | None) -> None:
    """Open the given or last used library folder (errors are logged, never fatal)."""
    from .api.routes_system import activate_workspace
    from .workspace import Workspace

    if not path or not Workspace.is_workspace(path):
        return
    try:
        activate_workspace(Workspace.open(path))
        log.info(native_text("Library opened: %s", "Bibliothek geöffnet: %s"), path)
    except Exception as exc:  # noqa: BLE001 - start without a library instead of crashing
        detail = getattr(exc, "detail", None)
        if detail:  # e.g. HTTP 409: open in another PartForge
            log.warning(native_text("Library not opened (%s): %s", "Bibliothek nicht geöffnet (%s): %s"), path, detail)
        else:
            log.exception(native_text("Could not open library: %s", "Bibliothek konnte nicht geöffnet werden: %s"), path)


def _configure_logging(verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        log_dir() / "partforge.log", maxBytes=LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    # Never let the session token (travelling as ?token= for EventSource/images/downloads, logged with the
    # request URL by uvicorn's access log) reach a log file or the console (QA sec finding 4).
    redact = RedactTokenFilter()
    for handler in handlers:
        handler.addFilter(redact)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _ensure_std_streams() -> None:
    """Windowed builds (pythonw, PyInstaller --windowed) have no stdout/stderr, but libraries
    such as uvicorn call ``sys.stdout.isatty()``. Route missing streams into a log file (kept small:
    started anew when it grew beyond 2 MB)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    path = log_dir() / "partforge-console.log"
    with contextlib.suppress(OSError):
        if path.stat().st_size > LOG_BYTES:
            path.replace(path.with_suffix(".log.1"))
    stream = open(path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _webview_storage() -> Path:
    """WebView2 profile in the local folder; older versions kept it in the roaming folder – moved once."""
    target = local_data_dir() / "webview"
    legacy = app_data_dir() / "webview"
    if not target.exists() and legacy.is_dir() and legacy.resolve() != target.resolve():
        try:
            shutil.move(str(legacy), str(target))
            log.info(native_text("WebView profile moved: %s -> %s", "WebView-Profil verschoben: %s -> %s"), legacy, target)
        except OSError:
            log.warning(native_text("Could not move WebView profile — keeping it in %s",
                                    "WebView-Profil konnte nicht verschoben werden – es bleibt in %s"), legacy, exc_info=True)
            return legacy
    target.mkdir(parents=True, exist_ok=True)
    return target


def server_config(app: Any, port: int, *, verbose: bool = False) -> uvicorn.Config:
    """uvicorn configuration of the real server: 127.0.0.1 only, the host-checking HTTP protocol
    (:func:`partforge.app.http_protocol`) and ``log_config=None`` – uvicorn logs through our root logger
    (``partforge.log``, token redacted) instead of its own console handlers, which do not exist in the
    windowed program."""
    return uvicorn.Config(app, host="127.0.0.1", port=port, http=http_protocol(), log_config=None,
                          log_level="info" if verbose else "warning")


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="partforge", description=native_text(
        "PartForge — Altium database libraries", "PartForge – Altium-Datenbankbibliotheken"))
    parser.add_argument("--browser", action="store_true", help=native_text(
        "open in the default browser instead of the desktop window", "im Standardbrowser statt im Desktop-Fenster öffnen"))
    parser.add_argument("--server-only", action="store_true", help=native_text("start only the API server", "nur den API-Server starten"))
    parser.add_argument("--dev", action="store_true", help=native_text(
        "development mode: port 8765, token 'dev'", "Entwicklungsmodus: Port 8765, Token 'dev'"))
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--workspace", help=native_text("open a library folder", "Bibliotheksordner öffnen"))
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"PartForge {__version__}")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    _ensure_std_streams()
    if not _acquire_instance():
        return _already_running(args)
    settings = load_settings()

    token = "dev" if args.dev else os.environ.get("PARTFORGE_TOKEN")
    try:
        if args.port:
            sock = bind_server_socket(args.port, fixed=True)
        elif args.dev:
            sock = bind_server_socket(DEV_PORT, fixed=True)
        else:
            sock = bind_server_socket(PREFERRED_PORT, fixed=False)
    except PortInUse as exc:
        log.error("%s", exc)
        print(str(exc), file=sys.stderr, flush=True)
        if not (args.server_only or args.dev):
            _message_box(str(exc))
        return EXIT_PORT_BUSY
    port = int(sock.getsockname()[1])
    mode = "server" if args.server_only or args.dev else ("browser" if args.browser else "desktop")
    _write_instance(port, mode)
    # allowed_hosts=frozenset(): loopback names only – the real program never reads the test hook
    # PARTFORGE_TEST_HOSTS (that one exists for Starlette's TestClient in tests/conftest.py)
    app = create_app(token=token, allowed_hosts=frozenset())
    _reopen_workspace(args.workspace or settings.workspace)
    server = uvicorn.Server(server_config(app, port, verbose=args.verbose))
    url = f"http://127.0.0.1:{port}/"
    try:
        return _serve(args, app, server, sock, url, settings)
    finally:
        _remove_instance()


def _serve(args: argparse.Namespace, app: Any, server: uvicorn.Server, sock: socket.socket, url: str,
           settings: Any) -> int:
    if args.server_only or args.dev:
        token_label = app.state.token if args.dev else native_text("hidden", "versteckt")
        print(native_text("PartForge API is running at {url} (token: {token})",
                          "PartForge API läuft auf {url} (Token: {token})").format(url=url, token=token_label), flush=True)
        server.run(sockets=[sock])
        return 0

    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, name="partforge-server", daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        text = native_text("The PartForge server did not start ({url}). See {log} for details.",
                           "Der PartForge-Server ist nicht gestartet ({url}). Details stehen in {log}.").format(
                               url=url, log=log_dir() / "partforge.log")
        log.error(text)
        _message_box(text)
        server.should_exit = True
        return 3

    if args.browser:
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        server.should_exit = True
        return 0

    import webview

    localization = webview_localization(settings.language)
    webview.create_window(
        WINDOW_TITLE,
        url,
        js_api=DesktopApi(),
        width=1480,
        height=940,
        min_size=(1120, 720),
        background_color="#090B10" if settings.theme != "light" else "#F5F6FA",
        text_select=True,
        localization=localization,
    )
    storage = _webview_storage()
    webview.settings["ALLOW_DOWNLOADS"] = True  # browser-style downloads (exports) in WebView2
    icon = Path(__file__).parent / "assets" / "app.ico"
    webview.start(private_mode=False, storage_path=str(storage), icon=str(icon) if icon.is_file() else None,
                  localization=localization)
    server.should_exit = True
    thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
