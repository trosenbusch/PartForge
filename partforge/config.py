"""Application-wide settings (per Windows user), stored as JSON in %APPDATA%\\PartForge.

Workspace-specific settings (database, folders, layer mapping, house style)
live in the workspace folder itself, see :mod:`partforge.workspace`.

Folders (``PARTFORGE_HOME`` replaces both in tests and isolated runs):

* :func:`app_data_dir` – ``%APPDATA%\\PartForge`` (roaming): ``settings.json`` and ``secret\\`` (the
  DPAPI-encrypted Claude key) – what belongs to the Windows user on every PC.
* :func:`local_data_dir` – ``%LOCALAPPDATA%\\PartForge`` (this PC only, never roams): caches, the WebView2
  profile, logs (:func:`log_dir`), temporary files and uploads.

No developer paths ship as defaults: the Claude key comes from ``ANTHROPIC_API_KEY``, the DPAPI store or an
explicitly configured key file; the Rust writer from the configured path, ``PARTFORGE_RUST_WRITER``,
``%LOCALAPPDATA%\\Programs\\altium-designer-mcp\\`` or next to ``PartForge.exe``
(:func:`detect_rust_writer`). A configured writer path that does not exist is reported, never replaced
silently by another one.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
import threading
from pathlib import Path, PureWindowsPath
from typing import Literal

from platformdirs import user_data_dir, user_documents_dir
from pydantic import BaseModel, Field

log = logging.getLogger("partforge")

APP_NAME = "PartForge"
RUST_WRITER_EXE = "altium-designer-mcp.exe"

#: An API key file is never read beyond this size (QA sec finding 2: a configured key file must not be
#: used to exfiltrate arbitrary – possibly large – file contents to the Claude API).
KEY_FILE_MAX_BYTES = 4096
#: A key file's content is only used when it looks like an Anthropic key.
ANTHROPIC_KEY_PREFIX = "sk-ant-"

DEFAULT_LIBRARY_NAME = "PartForge-Bibliothek"


def app_data_dir() -> Path:
    """Roaming per-user folder: settings and the stored key (``PARTFORGE_HOME`` in isolated runs)."""
    override = os.environ.get("PARTFORGE_HOME")
    path = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False, roaming=True))
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_data_dir() -> Path:
    """Folder of this PC only (``%LOCALAPPDATA%\\PartForge``): caches, WebView2 profile, logs, temporary
    files – nothing that should roam with the Windows profile. ``PARTFORGE_HOME`` in isolated runs."""
    override = os.environ.get("PARTFORGE_HOME")
    path = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False, roaming=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    """Log files (``<local data>\\logs``)."""
    path = local_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_library_parent() -> Path:
    """Suggested parent folder of new libraries: ``<Dokumente>\\PartForge`` of the Windows user."""
    try:
        documents = Path(user_documents_dir())
    except Exception:  # noqa: BLE001 - unusual profile: the home folder
        documents = Path.home() / "Documents"
    return documents / APP_NAME


def detect_altium_exe() -> str | None:
    """Newest C:\\Program Files\\Altium\\AD*\\X2.EXE (highest version number)."""
    candidates = []
    for exe in glob.glob(r"C:\Program Files\Altium\AD*\X2.EXE"):
        m = re.search(r"AD(\d+)", exe)
        candidates.append((int(m.group(1)) if m else 0, exe))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def rust_writer_candidates() -> list[str]:
    """Where PartForge looks for ``altium-designer-mcp.exe`` when no path is configured (in this order):
    ``PARTFORGE_RUST_WRITER``, ``%LOCALAPPDATA%\\Programs\\altium-designer-mcp\\``, next to ``PartForge.exe``
    (also in a subfolder ``altium-designer-mcp``)."""
    out: list[str] = []
    env = os.environ.get("PARTFORGE_RUST_WRITER")
    if env:
        out.append(env)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        out.append(str(Path(local) / "Programs" / "altium-designer-mcp" / RUST_WRITER_EXE))
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        out += [str(exe_dir / RUST_WRITER_EXE), str(exe_dir / "altium-designer-mcp" / RUST_WRITER_EXE)]
    return out


def detect_rust_writer() -> str | None:
    """The first existing :func:`rust_writer_candidates` entry, else ``None``."""
    for candidate in rust_writer_candidates():
        if candidate and Path(candidate).is_file():
            return candidate
    return None


# --------------------------------------------------------------------------- path validation (QA sec finding 2)
# A stored executable or key path must never point at a network share (UNC) or a Windows device path: PartForge
# would otherwise run a program from, or read a file off, an attacker-controlled location. These checks guard both
# the API (PUT /api/settings, German 400) and the resolve-time use (a hand-edited settings.json is ignored, not
# executed – the Altium status reports why).


def is_unc_or_device_path(text: str) -> bool:
    """True for a UNC path (``\\\\server\\share``, ``//server/share``) or a Windows device/long-path
    form (``\\\\?\\…``, ``\\\\.\\…``, ``//?/…``) in any spelling of the slashes (Windows treats ``/`` and
    ``\\`` alike, so ``\\/server/share`` is a UNC path, too)."""
    t = (text or "").strip().replace("/", "\\")
    return t.startswith("\\\\")


_DRIVE_REMOTE = 4  # GetDriveTypeW: mapped network drive


def _is_network_drive(drive: str) -> bool:
    """Whether the drive letter ``drive`` (``"Z:"``) is a mapped network drive."""
    if os.name != "nt":  # pragma: no cover - Windows only application
        return False
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")) == _DRIVE_REMOTE
    except Exception:  # noqa: BLE001 - no answer: treat as local (UNC paths are refused anyway)
        return False


def _local_absolute_problem(text: str, what: str) -> str | None:
    """German reason why ``text`` is not an absolute path on a local drive letter (``None`` = fine):
    no UNC/device path in any spelling, no relative path, no mapped network drive."""
    if is_unc_or_device_path(text):
        return (f"{what} „{text}“ ist ein Netzwerk- oder Gerätepfad (UNC). Bitte eine Datei auf einem lokalen "
                "Laufwerk angeben (z. B. C:\\Programme\\…).")
    win = PureWindowsPath(text)
    drive = win.drive
    if not win.is_absolute() or not (len(drive) == 2 and drive[0].isalpha() and drive[1] == ":"):
        return f"{what} „{text}“ muss ein absoluter Pfad auf einem lokalen Laufwerk sein (z. B. C:\\…)."
    if _is_network_drive(drive):
        return f"{what} „{text}“ liegt auf einem Netzlaufwerk ({drive}). Bitte eine Datei auf einem lokalen Laufwerk angeben."
    return None


def executable_path_problem(path: str | None, *, require_name: str | None = None) -> str | None:
    """German reason why ``path`` is not a safe local executable (``None`` = fine).

    Required: a non-empty, absolute path on a local drive (no UNC, no device path, no network drive), an
    existing regular file with the ``.exe`` suffix. ``require_name`` (e.g. ``"X2.EXE"``) also fixes the name.
    """
    text = (path or "").strip()
    if not text:
        return "Bitte einen Pfad angeben."
    if (problem := _local_absolute_problem(text, "Der Pfad")) is not None:
        return problem
    win = PureWindowsPath(text)
    if win.suffix.lower() != ".exe":
        return f"Der Pfad „{text}“ muss auf eine ausführbare Datei (.exe) verweisen."
    if require_name is not None and win.name.upper() != require_name.upper():
        return f"Es wird die Datei „{require_name}“ erwartet, nicht „{win.name}“."
    if not Path(text).is_file():
        return f"Die Datei „{text}“ wurde nicht gefunden. Bitte den Pfad prüfen."
    return None


def key_file_path_problem(path: str | None) -> str | None:
    """German reason why ``path`` is not an acceptable API-key file location (``None`` = fine).

    Only an absolute path on a local drive is allowed (no UNC/device path, no network drive); the file's
    existence, size and content are checked when the key is actually read (:func:`read_api_key`,
    :func:`key_file_status`)."""
    text = (path or "").strip()
    if not text:
        return None
    return _local_absolute_problem(text, "Die Schlüsseldatei")


_ANTHROPIC_KEY_RE = re.compile(re.escape(ANTHROPIC_KEY_PREFIX) + r"[A-Za-z0-9_\-]{1,500}")


def looks_like_anthropic_key(text: str | None) -> bool:
    """Whether ``text`` is exactly one Anthropic API key (``sk-ant-`` and key characters, nothing else) –
    a file with other content is never taken for a key."""
    return bool(text) and _ANTHROPIC_KEY_RE.fullmatch(text.strip()) is not None


def _read_small_text(path: Path) -> str | None:
    """The text of ``path`` if it has at most :data:`KEY_FILE_MAX_BYTES` (read bounded, never more), else
    ``None``. Raises :class:`OSError` when the file cannot be read."""
    with open(path, "rb") as fh:
        data = fh.read(KEY_FILE_MAX_BYTES + 1)
    if len(data) > KEY_FILE_MAX_BYTES:
        return None
    return data.decode("utf-8", errors="replace").removeprefix("﻿")  # Notepad's UTF-8 BOM


class AISettings(BaseModel):
    """Claude API settings. Defaults follow docs/entwicklung/recherche/claude-api.md:
    Opus 5.5 at effort "low" extracted the reference datasheet 100 % correctly (~0.18 USD);
    Haiku 5.5 is the cheap model for page triage and cross-checks."""

    enabled: bool = True
    api_key_file: str | None = None  # optional plain-text key file (prefer the encrypted store)
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high"] = "low"
    fast_model: str = "claude-haiku-5-5"
    use_fallbacks: bool = True  # server-side fallback beta (server-side-fallback-2026-07-01)
    max_cost_per_import_usd: float = 2.0


class AltiumSettings(BaseModel):
    x2_path: str | None = None
    library_backend: Literal["auto", "rust", "altium"] = "auto"
    rust_writer_path: str | None = None
    rust_writer_timeout_s: float = 120.0
    script_timeout_s: float = 180.0
    bridge_exchange_dir: str | None = None  # None = %LOCALAPPDATA%\PartForge\bridge
    # After PartForge changed the database, make a running Altium re-read the DbLib
    # (closes Altium's hidden DbLib document, see recherche/altium-refresh.md).
    auto_refresh: bool = True
    # After rewriting SchLib/PcbLib files: reload them in Altium if they are open and unmodified.
    auto_reload_libraries: bool = True


class AppSettings(BaseModel):
    workspace: str | None = None
    recent_workspaces: list[str] = Field(default_factory=list)
    language: Literal["en", "de"] = "en"
    theme: Literal["dark", "light", "system"] = "dark"
    author: str = Field(default_factory=lambda: os.environ.get("USERNAME", "PartForge"))
    ai: AISettings = Field(default_factory=AISettings)
    altium: AltiumSettings = Field(default_factory=AltiumSettings)

    def resolved_altium_exe(self) -> str | None:
        """The configured ``X2.EXE`` if it passes validation (absolute, local, exists, named X2.EXE),
        else the auto-detected one. A hand-edited UNC/invalid path is ignored, never executed
        (:func:`executable_path_problem`; the Altium status reports it)."""
        configured = (self.altium.x2_path or "").strip()
        if configured and executable_path_problem(configured, require_name="X2.EXE") is None:
            return configured
        return detect_altium_exe()

    def resolved_rust_writer(self) -> str | None:
        """The configured writer if it passes validation; with a configured path that is missing or
        unsafe (UNC/device path, not an ``.exe``) ``None`` (the status reports it – never silently
        another writer); without a configured path :func:`detect_rust_writer`."""
        configured = (self.altium.rust_writer_path or "").strip()
        if configured:
            return configured if executable_path_problem(configured) is None else None
        return detect_rust_writer()

    def resolved_bridge_exchange_dir(self) -> Path | None:
        """The configured exchange folder of the Altium bridge (Altium runs the script project PartForge writes
        there) if it is an absolute local folder; ``None`` = the default folder. A hand-edited UNC/device path or
        network drive is ignored (logged) – Altium must never run scripts from a share (QA sec finding 2)."""
        configured = (self.altium.bridge_exchange_dir or "").strip()
        if not configured:
            return None
        problem = exchange_dir_problem(configured)
        if problem is not None:
            log.warning("Austauschverzeichnis der Altium-Brücke ignoriert: %s", problem)
            return None
        return Path(configured)


def exchange_dir_problem(path: str | None) -> str | None:
    """German reason why ``path`` is not an acceptable exchange folder of the Altium bridge (``None`` = fine
    or empty = default): only an absolute folder on a local drive."""
    text = (path or "").strip()
    if not text:
        return None
    return _local_absolute_problem(text, "Das Austauschverzeichnis")


_lock = threading.RLock()
_cached: AppSettings | None = None
_cached_stamp: tuple[str, int, int] | None = None  # (path, size, mtime_ns) of the settings file read last


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _stamp(path: Path) -> tuple[str, int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return str(path), st.st_size, st.st_mtime_ns


def load_settings(reload: bool = False) -> AppSettings:
    """The app settings (cached; read again when ``settings.json`` changed on disk, e.g. written by another
    PartForge process or edited by hand)."""
    global _cached, _cached_stamp
    with _lock:
        path = settings_path()
        stamp = _stamp(path)
        if _cached is not None and not reload and stamp == _cached_stamp:
            return _cached
        if path.is_file():
            try:
                _cached = AppSettings.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:  # corrupt file -> keep a copy and start fresh
                path.replace(path.with_suffix(".corrupt.json"))
                _cached = AppSettings()
                stamp = None
        else:
            _cached = AppSettings()
        _cached_stamp = stamp
        return _cached


def save_settings(settings: AppSettings) -> None:
    global _cached, _cached_stamp
    with _lock:
        path = settings_path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(settings.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        _cached = settings
        _cached_stamp = _stamp(path)


def remember_workspace(path: str) -> AppSettings:
    settings = load_settings()
    norm = str(Path(path).resolve())
    recent = [p for p in settings.recent_workspaces if Path(p).resolve() != Path(norm)]
    settings.workspace = norm
    settings.recent_workspaces = [norm, *recent][:12]
    save_settings(settings)
    return settings


def _secret_path() -> Path:
    return app_data_dir() / "secret" / "claude-api-key.dpapi"


def store_api_key(key: str | None) -> None:
    """Store the Claude API key encrypted for the current Windows user (DPAPI).
    ``None`` or an empty string removes the stored key."""
    path = _secret_path()
    if not key or not key.strip():
        path.unlink(missing_ok=True)
        return
    import win32crypt  # pywin32

    blob = win32crypt.CryptProtectData(key.strip().encode("utf-8"), "PartForge Claude API key", None, None, None, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(blob)
    tmp.replace(path)


def _read_stored_key() -> str | None:
    path = _secret_path()
    if not path.is_file():
        return None
    try:
        import win32crypt  # pywin32

        _desc, data = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)
        return data.decode("utf-8").strip() or None
    except Exception:  # noqa: BLE001 - corrupt or foreign blob: behave as "no key"
        return None


def _real_key_allowed() -> bool:
    """Isolated runs (PARTFORGE_HOME set: tests, test servers, smoke tests) never pick up the
    machine's ANTHROPIC_API_KEY by accident –
    so they cannot spend money unnoticed. Opt in with PARTFORGE_ALLOW_REAL_AI=1 (or
    PARTFORGE_TEST_AI=1 for the ``ai`` tests). PARTFORGE_NO_AI_KEY=1 disables every source."""
    if os.environ.get("PARTFORGE_NO_AI_KEY") == "1":
        return False
    if not os.environ.get("PARTFORGE_HOME"):
        return True
    return os.environ.get("PARTFORGE_ALLOW_REAL_AI") == "1" or os.environ.get("PARTFORGE_TEST_AI") == "1"


def _key_file(settings: AppSettings) -> Path | None:
    """The explicitly configured key file path if it is a local existing file;
    ``None`` otherwise. Does **not** read or validate the content – see :func:`_file_key`."""
    if not settings.ai.api_key_file:
        return None
    if key_file_path_problem(settings.ai.api_key_file) is not None:  # UNC/device path: never read it
        return None
    path = Path(settings.ai.api_key_file)
    return path if path.is_file() else None


def _file_key(settings: AppSettings) -> str | None:
    """The API key from the configured key file – only if the file is local, at most
    :data:`KEY_FILE_MAX_BYTES` and its content looks like an Anthropic key (``sk-ant-…``). Any other
    file content is never used or sent anywhere (QA sec finding 2)."""
    path = _key_file(settings)
    if path is None:
        return None
    try:
        text = _read_small_text(path)
    except OSError as exc:
        log.warning("Schlüsseldatei konnte nicht gelesen werden: %s", exc)
        return None
    if text is None:
        log.warning("Schlüsseldatei %s ist größer als %d Bytes – sie wird nicht verwendet.", path, KEY_FILE_MAX_BYTES)
        return None
    key = text.strip()
    return key if looks_like_anthropic_key(key) else None


def key_file_status(settings: AppSettings | None = None) -> str | None:
    """German note why a configured key file cannot provide a key (UNC/device path, not found, too big,
    no valid ``sk-ant-…`` key) – for the UI; ``None`` when no file is configured or it holds a valid key."""
    settings = settings or load_settings()
    raw = (settings.ai.api_key_file or "").strip()
    if not raw:
        return None
    problem = key_file_path_problem(raw)
    if problem is not None:
        return problem
    path = _key_file(settings)
    if path is None:
        return f"Die Schlüsseldatei „{raw}“ wurde nicht gefunden."
    try:
        text = _read_small_text(path)
    except OSError:
        return "Die Schlüsseldatei kann nicht gelesen werden."
    if text is None:
        return f"Die Schlüsseldatei ist größer als {KEY_FILE_MAX_BYTES // 1024} KB und wird nicht gelesen."
    if not looks_like_anthropic_key(text):
        return "Die Schlüsseldatei enthält keinen gültigen Claude-Schlüssel (erwartet wird „sk-ant-…“)."
    return None


def api_key_source(settings: AppSettings | None = None) -> str | None:
    """Where the key comes from: 'env', 'stored', 'file' or None (for the UI, never the key itself)."""
    if os.environ.get("PARTFORGE_NO_AI_KEY") == "1":
        return None
    if os.environ.get("ANTHROPIC_API_KEY", "").strip() and _real_key_allowed():
        return "env"
    if _read_stored_key():
        return "stored"
    if _file_key(settings or load_settings()) is not None:
        return "file"
    return None


def read_api_key(settings: AppSettings | None = None) -> str | None:
    """Return the Claude API key: environment, then DPAPI store, then key file. Never log it.

    A key file is only used when it is a small local file whose content looks like an Anthropic key
    (:func:`_file_key`) – PartForge never sends other file contents to the API."""
    if os.environ.get("PARTFORGE_NO_AI_KEY") == "1":
        return None
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env and env.strip() and _real_key_allowed():
        return env.strip()
    stored = _read_stored_key()
    if stored:
        return stored
    return _file_key(settings or load_settings())
