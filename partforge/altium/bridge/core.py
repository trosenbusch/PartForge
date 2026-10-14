"""DelphiScript bridge to a running Altium Designer (PartForge's own script project).

Mechanics (``recherche/bridge-study.md``, ``altium-live.md``):

* PartForge writes ``request.txt`` (+ an optional spec file) into its **own** exchange
  directory (default ``%LOCALAPPDATA%\\PartForge\\bridge``, never altium-mcp's
  ``C:\\Users\\Public\\altium_mcp``) and starts
  ``"<X2.EXE>" -RScriptingSystem:RunScript(ProjectName="<prj>"|ProcName="PartForgeBridge>Run")``
  through ``subprocess`` (no shell). The running Altium instance executes the script.
* The script flushes a step log (``log_<id>.txt``) after every step and writes
  ``response_<id>.txt`` whose last line is ``END|<id>``.
* No log after ``start_timeout_s`` -> the script never started (a previous script is
  paused in the debugger, a compile error, or Altium is busy); log without response
  after ``timeout_s`` -> the script died -> :class:`BridgeWedgedError` with the recovery
  hint ("Skript anhalten" on the Altium page = :meth:`AltiumBridge.stop_script`, which
  dispatches Altium's ``EditScript:Stop`` process and verifies with a ping). PartForge
  never closes or touches dialogs of any process.
* Altium writes the response and log files with ``TStringList.SaveToFile``: ANSI code
  page, or UTF-8 with a byte-order mark when Windows runs with the "Beta: Use Unicode
  UTF-8" code page (found by altium-mcp, issue #20) – :func:`_read_altium_text`.
* A cross-process lock file serialises PartForge instances; the script project is
  generated from the templates in ``scripts/`` with the exchange path baked in.
* Altium activates its main window when a RunScript command arrives; :func:`.focus.keep_foreground`
  keeps the user's window in front during the launch (foreground lock / restore).
"""
from __future__ import annotations

import codecs
import contextlib
import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from ...config import AppSettings, load_settings, local_data_dir
from ...geometry.model import FootprintSpec, SymbolSpec
from ...workspace import FootprintStyle, LayerMap, SymbolStyle
from ..models import BackendStatus
from .focus import allow_altium_foreground, bring_altium_to_front, keep_foreground
from .process import X2_IMAGE, file_version, is_process_running
from .protocol import BridgeResponse, parse_response, render_request
from .spec import RenderedSpec, render_pcblib_spec, render_schlib_spec

log = logging.getLogger(__name__)

__all__ = [
    "AltiumBridge",
    "BridgeError",
    "AltiumNotRunning",
    "BridgeBusyError",
    "BridgeWedgedError",
    "BridgeCommandError",
    "BridgeWriteResult",
    "ComponentFocus",
    "DbComponentResolution",
    "DbLibInstallState",
    "DbLibRefreshResult",
    "DocumentState",
    "InstalledDbLib",
    "RECOVERY_HINT",
    "STOP_PROCESS",
    "ScriptStopResult",
    "SCRIPTS_DIR",
    "default_exchange_dir",
    "canonical_path",
    "altium_safe_path",
    "parse_db_parameters",
    "parse_db_resolutions",
    "RESOLVE_BATCH_SIZE",
]

SCRIPTS_DIR: Final = Path(__file__).parent / "scripts"
SCRIPT_UNITS: Final = ("PFUtils.pas", "PFLibraries.pas", "PFSchLib.pas", "PFPcbLib.pas", "PartForgeBridge.pas")
PROJECT_FILE: Final = "PartForgeBridge.PrjScr"
UNIT_NAME: Final = "PartForgeBridge"
EXCHANGE_PLACEHOLDER: Final = "@@PF_EXCHANGE_DIR@@"
#: Keys per ``resolve_db_components`` script run (``PF_MAX_RESOLVE`` in PFUtils.pas is the hard limit).
RESOLVE_BATCH_SIZE: Final = 50

RECOVERY_HINT: Final = (
    "Bitte auf der Altium-Seite „Skript anhalten“ wählen (oder in Altium Designer das angehaltene Skript über "
    "Run › Stop beenden – Strg+F3 wirkt nur, solange der Skript-Editor das aktive Dokument ist) und offene "
    "Altium-Meldungen selbst schließen; danach erneut versuchen. PartForge schließt niemals Dialoge."
)
#: Altium's "Stop Debugging" process. ``X2.EXE -REditScript:Stop`` hands it to the running instance through the
#: same command-line channel that starts the bridge script – no window focus, no keystrokes (altium-mcp,
#: dev/unwedge.py: Strg+F3 only reaches the debugger while the script editor is the active document).
STOP_PROCESS: Final = "EditScript:Stop"
_NO_X2: Final = (
    "Altium Designer (X2.EXE) wurde nicht gefunden – Pfad unter Einstellungen › Allgemein › Altium Designer eintragen."
)


class BridgeError(RuntimeError):
    """Base class of bridge errors (German message)."""


class AltiumNotRunning(BridgeError):
    """Altium Designer (X2.EXE) is not running."""


class BridgeBusyError(BridgeError):
    """Another PartForge process uses the bridge right now."""


class BridgeCommandError(BridgeError):
    """The script ran but reported an error."""

    def __init__(self, command: str, detail: str):
        self.command = command
        self.detail = detail
        super().__init__(f"Altium-Brücke: Befehl '{command}' fehlgeschlagen: {detail}")


class BridgeWedgedError(BridgeError):
    """The script did not start or did not finish (paused in the debugger / blocked)."""

    def __init__(self, kind: Literal["never_started", "did_not_finish"], *, last_step: str | None = None, seconds: float):
        self.kind = kind
        self.last_step = last_step
        self.seconds = seconds
        if kind == "never_started":
            text = (
                f"Altium hat das PartForge-Skript innerhalb von {seconds:.0f} s nicht gestartet. Vermutlich hängt "
                "ein vorheriges Skript im Debugger, ein Dialog ist offen oder Altium ist beschäftigt. "
            )
        else:
            step = f" (letzter Schritt: {last_step})" if last_step else ""
            text = (
                f"Das PartForge-Skript in Altium wurde gestartet, aber nicht innerhalb von {seconds:.0f} s "
                f"beendet{step}. Es hängt vermutlich im Debugger. "
            )
        super().__init__(text + RECOVERY_HINT)


class BridgeWriteResult(BaseModel):
    """Result of ``write_schlib`` / ``write_pcblib`` on the Altium side."""

    path: str
    written: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created: int = 0
    duration_s: float = 0.0


class ScriptStopResult(BaseModel):
    """Outcome of :meth:`AltiumBridge.stop_script` ("Skript anhalten")."""

    dispatched: bool = False  # EditScript:Stop was handed to the running Altium
    recovered: bool = False  # the verifying ping succeeded: Altium runs PartForge scripts again
    version: str | None = None  # Altium version reported by the ping
    message: str = ""  # German outcome sentence
    detail: str | None = None  # the ping's error when not recovered


class DocumentState(BaseModel):
    """Whether Altium has a document open and whether it has unsaved changes."""

    path: str
    open: bool = False
    modified: bool = False


class ComponentFocus(BaseModel):
    """Outcome of ``edit_component``: the library is shown in Altium, ``found`` = the component is the
    current one of its library editor (``current`` = what Altium shows now)."""

    path: str
    name: str
    was_open: bool = False
    found: bool = False
    current: str = ""
    modified: bool = False


class DbComponentResolution(BaseModel):
    """How Altium resolves one DbLib record (symbol, footprints, parameters)."""

    dblib: str
    table: str
    key: str
    loaded: bool = False
    symbol_path: str = ""
    symbol_ref: str = ""
    lib_reference: str = ""
    pin_count: int | None = None
    footprints: list[str] = Field(default_factory=list)
    current_footprint: str | None = None
    parameters: dict[str, str] = Field(default_factory=dict)
    designator: str = ""
    comment: str = ""
    # the Comment of the loaded part is shown on the schematic (None = not reported)
    comment_visible: bool | None = None
    # parameters Altium shows on the schematic (not hidden; Comment included), in Altium's order
    visible_parameters: list[str] = Field(default_factory=list)
    description: str = ""
    design_item_id: str = ""
    temporarily_installed: bool = False
    # after a temporary installation: Altium's hidden DbLib document (and its database
    # connection) was closed again before the uninstall (None = DbLib was installed)
    released: bool | None = None


class InstalledDbLib(BaseModel):
    """An installed Altium library whose file name equals the PartForge DbLib's file name."""

    index: int  # position in Altium's installed list (0 = first; the first one wins on name clashes)
    path: str
    same_file: bool = False  # this entry is the DbLib that was asked about
    document_open: bool = False  # Altium holds the (hidden) DbLib server document
    document_shown: bool = False  # open in an editor tab (never closed by PartForge)
    document_modified: bool = False  # unsaved edits in Altium (never closed by PartForge)


class DbLibInstallState(BaseModel):
    """Is the DbLib installed in Altium, and which installed libraries share its file name?

    Placed parts reference a DbLib by **file name only**; with several installed DbLibs of
    the same name Altium resolves to the first installed one (VERIFIED, altium-refresh.md §0.5).
    """

    path: str  # the DbLib that was asked about
    file_name: str
    installed: bool = False  # exactly this file is installed
    position: int | None = None  # index of this file in the installed list
    same_name: list[InstalledDbLib] = Field(default_factory=list)  # every installed library with this file name
    duplicates: list[str] = Field(default_factory=list)  # other files with the same name (conflict)
    first_match: str | None = None  # the library Altium resolves the file name to
    resolves_to_this: bool = False  # first_match is this file
    installed_count: int = 0
    checked: float = Field(default_factory=time.time)
    # duplicate path -> what it is ("same_database", "other_database", "missing", "unreachable",
    # "unreadable"); filled by partforge.altium.dblib.classify_install_state (the bridge cannot know)
    duplicate_kinds: dict[str, str] = Field(default_factory=dict)


class DbLibRefreshResult(BaseModel):
    """Result of :meth:`AltiumBridge.refresh_dblib` (verified procedure, altium-refresh.md §7)."""

    file_name: str
    rebuild_index: bool = False
    matched: list[str] = Field(default_factory=list)  # installed DbLibs with this file name
    closed: list[str] = Field(default_factory=list)  # hidden DbLib documents closed (both passes)
    not_open: list[str] = Field(default_factory=list)
    skipped: dict[str, str] = Field(default_factory=dict)  # path -> "shown" | "modified" | "other_kind"
    refreshed_index: bool = False  # IntegratedLibrary:RefreshInstalledLibraries ran
    refresh_ms: int | None = None
    duration_s: float = 0.0

    @property
    def installed(self) -> bool:
        return bool(self.matched)


def dblib_file_name(value: str | os.PathLike[str]) -> str:
    """File name of a DbLib (``PartForge.DbLib``) as the bridge compares it.

    Raises :class:`BridgeError` for names the ASCII exchange cannot carry unchanged
    (characters above U+00FF would be transliterated and never match).
    """
    name = Path(str(value)).name.strip()
    if not name or not name.lower().endswith(".dblib"):
        raise BridgeError(f"„{value}“ ist kein DbLib-Dateiname (erwartet z. B. PartForge.DbLib).")
    if any(ord(c) > 0xFF or ord(c) < 0x20 for c in name):
        raise BridgeError(
            f"Der DbLib-Dateiname „{name}“ enthält Zeichen, die die Altium-Brücke nicht übertragen kann. Bitte einen "
            "Namen ohne Sonderzeichen verwenden."
        )
    return name


def _same_file(altium_path: str, wanted: Path) -> bool:
    """True if the path Altium reports is the same file as ``wanted`` (spelling-independent)."""
    try:
        target = canonical_path(wanted)
        reported = Path(os.path.abspath(altium_path))
    except (OSError, ValueError):
        return False
    if os.path.normcase(str(reported)) == os.path.normcase(str(target)):
        return True
    try:
        return reported.exists() and target.exists() and os.path.samefile(reported, target)
    except OSError:
        return False


def default_exchange_dir() -> Path:
    """``%LOCALAPPDATA%\\PartForge\\bridge`` (fallback: ``<local data>/bridge``)."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "PartForge" / "bridge"
    return local_data_dir() / "bridge"


def parse_db_parameters(raw: str) -> tuple[dict[str, str], list[str]]:
    """Parse Altium's ``ParameterName0=…|ParameterValue0=…|ModelName0=…`` string."""
    names: dict[str, str] = {}
    values: dict[str, str] = {}
    models: dict[str, str] = {}
    for part in raw.split("|"):
        key, sep, value = part.partition("=")
        if not sep:
            continue
        for prefix, target in (("ParameterName", names), ("ParameterValue", values), ("ModelName", models)):
            if key.startswith(prefix) and key[len(prefix) :].isdigit():
                target[key[len(prefix) :]] = value
    params = {names[i]: values.get(i, "") for i in sorted(names, key=int)}
    footprints = [models[i] for i in sorted(models, key=int)]
    return params, footprints


_RES_FIELDS: Final = 10  # loaded … comment_hidden of a ROW|res|<index>|… line (PFResolveOne)


def parse_db_resolutions(
    resp: BridgeResponse, dblib: str, keys: Sequence[tuple[str, str]]
) -> list[DbComponentResolution]:
    """Per-key results of ``resolve_db_components`` (every row carries the key's index).

    Raises :class:`BridgeCommandError` if the script did not report every key – a partial
    answer is never mistaken for "not found".
    """
    grouped: dict[str, dict[int, list[list[str]]]] = {}
    for name in ("res", "raw", "models", "parameters"):
        by_index: dict[int, list[list[str]]] = {}
        for row in resp.rows.get(name, []):
            if row and row[0].isdigit():
                by_index.setdefault(int(row[0]), []).append(row[1:])
        grouped[name] = by_index
    count = resp.value("count")
    if count != str(len(keys)):
        raise BridgeCommandError(
            "resolve_db_components", f"unvollständige Antwort ({count or 0} von {len(keys)} Bauteilen)"
        )
    temporarily = resp.flag("temporarily_installed")
    released = resp.flag("released") if "released" in resp.values else None
    out: list[DbComponentResolution] = []
    for index, (table, key) in enumerate(keys):
        rows = grouped["res"].get(index) or []
        if len(rows) != 1 or len(rows[0]) < _RES_FIELDS:
            raise BridgeCommandError("resolve_db_components", f"keine Antwort für {table}/{key}")
        (loaded, pins, symbol_path, symbol_ref, lib_reference, design_item_id, description, designator, comment,
         comment_hidden) = rows[0][:_RES_FIELDS]
        raw_rows = grouped["raw"].get(index) or [[""]]
        params_raw, footprints_raw = parse_db_parameters(raw_rows[0][0] if raw_rows[0] else "")
        param_rows = [row for row in grouped["parameters"].get(index, []) if len(row) >= 2]
        parameters = {row[0]: row[1] for row in param_rows} or params_raw
        models = [row for row in grouped["models"].get(index, []) if len(row) >= 2 and row[0].upper() == "PCBLIB"]
        footprints = [row[1] for row in models] or footprints_raw
        first = footprints[0] if footprints else None
        current = next((row[1] for row in models if len(row) >= 3 and row[2] == "1"), first)
        out.append(
            DbComponentResolution(
                dblib=dblib,
                table=table,
                key=key,
                loaded=loaded == "1",
                symbol_path=symbol_path,
                symbol_ref=symbol_ref,
                lib_reference=lib_reference,
                pin_count=int(pins) if pins.isdigit() else None,
                footprints=footprints,
                current_footprint=current,
                parameters=parameters,
                designator=designator,
                comment=comment,
                comment_visible=None if comment_hidden not in ("0", "1") else comment_hidden == "0",
                visible_parameters=[row[0] for row in param_rows if len(row) >= 3 and row[2] == "0"],
                description=description,
                design_item_id=design_item_id,
                temporarily_installed=temporarily,
                released=released,
            )
        )
    return out


def _read_altium_text(path: Path) -> str:
    """Text of a file the bridge script wrote with ``TStringList.SaveToFile``.

    Altium writes the ANSI code page – or UTF-8 **with a byte-order mark** when Windows runs with the
    "Beta: Use Unicode UTF-8" code page (VERIFIED by altium-mcp, issue #20). Decoded like Altium's own
    ``LoadFromFile``: UTF-8 after a mark, otherwise cp1252 (the responses are ASCII by construction;
    the step log may carry paths)."""
    data = path.read_bytes()
    if data.startswith(codecs.BOM_UTF8):
        return data[len(codecs.BOM_UTF8):].decode("utf-8", errors="replace")
    return data.decode("cp1252", errors="replace")


def _short_path(path: Path) -> str:
    """8.3 short path (ASCII) of an existing path on Windows, else the path itself."""
    if os.name != "nt":
        return str(path)
    import ctypes
    from ctypes import wintypes

    get_short = ctypes.windll.kernel32.GetShortPathNameW  # type: ignore[attr-defined]
    get_short.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    get_short.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(1024)
    length = get_short(str(path), buffer, 1024)
    return buffer.value if 0 < length < 1024 else str(path)


def canonical_path(path: str | os.PathLike[str]) -> Path:
    """One canonical spelling per file (absolute, resolved, real case) – Altium compares
    document paths literally and opens a second hidden instance for another spelling
    (VERIFIED, altium-verify-2 §1)."""
    return Path(os.path.abspath(Path(path).resolve()))


def altium_safe_path(path: str | os.PathLike[str]) -> str:
    """Canonical path string Altium can receive through the ASCII exchange files.

    Latin-1 characters are fine (escaped and decoded with ``Chr``); other characters
    are avoided by using the 8.3 short name of the existing parent folder.
    """
    canonical = canonical_path(path)
    text = str(canonical)
    if all(ord(c) <= 0xFF for c in text):
        return text
    parent = _short_path(canonical.parent)
    candidate = str(Path(parent) / canonical.name)
    if all(ord(c) <= 0xFF for c in candidate):
        return candidate
    raise BridgeError(
        f"Der Pfad {path} enthält Zeichen, die die Altium-Brücke nicht übertragen kann. Bitte einen Ordner "
        "ohne Sonderzeichen verwenden."
    )


class _FileLock:
    """Cross-process exclusive lock on a lock file (released automatically on process exit)."""

    def __init__(self, path: Path, timeout_s: float):
        self.path = path
        self.timeout_s = timeout_s
        self._handle: Any = None

    def __enter__(self) -> _FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")  # closed in __exit__
        deadline = time.monotonic() + self.timeout_s
        while True:
            try:
                self._lock(handle)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise BridgeBusyError(
                        "Die Altium-Brücke wird gerade von einem anderen PartForge-Vorgang verwendet. Bitte später "
                        "erneut versuchen."
                    ) from None
                time.sleep(0.2)
        self._handle = handle
        return self

    @staticmethod
    def _lock(handle: Any) -> None:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - PartForge runs on Windows
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, *exc: object) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                with contextlib.suppress(OSError):
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


_launched: list[subprocess.Popen[bytes]] = []
_launched_lock = threading.Lock()


def _default_launcher(command_line: str) -> None:
    """Start the helper X2.EXE process that hands the RunScript command to Altium."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(  # command line is built from validated paths only
        command_line,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )
    with _launched_lock:
        _launched[:] = [p for p in _launched if p.poll() is None]
        _launched.append(proc)


class AltiumBridge:
    """Client of the PartForge DelphiScript bridge (one command per script run)."""

    def __init__(
        self,
        *,
        exchange_dir: Path | None = None,
        x2_path: str | None = None,
        timeout_s: float = 180.0,
        start_timeout_s: float = 45.0,
        poll_interval_s: float = 0.25,
        lock_timeout_s: float = 600.0,
        launcher: Callable[[str], None] | None = None,
        process_check: Callable[[], bool] | None = None,
        process_check_interval_s: float = 2.0,
        keep_logs: int = 30,
    ):
        self.exchange_dir = Path(exchange_dir) if exchange_dir else default_exchange_dir()
        self.x2_path = x2_path
        self.timeout_s = float(timeout_s)
        self.start_timeout_s = float(start_timeout_s)
        self.poll_interval_s = float(poll_interval_s)
        self.lock_timeout_s = float(lock_timeout_s)
        self._launcher = launcher or _default_launcher
        self._process_check = process_check or (lambda: is_process_running(X2_IMAGE))
        self.process_check_interval_s = float(process_check_interval_s)
        self._keep_logs = keep_logs
        self._local_lock = threading.RLock()

    @classmethod
    def from_settings(cls, settings: AppSettings | None = None, **kwargs: Any) -> AltiumBridge:
        settings = settings or load_settings()
        return cls(x2_path=settings.resolved_altium_exe(), timeout_s=settings.altium.script_timeout_s, **kwargs)

    # -- status ---------------------------------------------------------------------
    def is_running(self) -> bool:
        try:
            return bool(self._process_check())
        except Exception as exc:  # noqa: BLE001 - a failing check must not break the UI
            log.warning("Altium-Prozessprüfung fehlgeschlagen: %s", exc)
            return False

    def status(self) -> BackendStatus:
        if not self.x2_path:
            return BackendStatus(name="altium", available=False, message=_NO_X2)
        version = file_version(self.x2_path)
        if not self.is_running():
            return BackendStatus(
                name="altium", available=False, message="Altium Designer ist nicht gestartet.", version=version, path=self.x2_path
            )
        label = f"Altium Designer {version}" if version else "Altium Designer"
        return BackendStatus(name="altium", available=True, message=f"{label} läuft.", version=version, path=self.x2_path)

    # -- script project ---------------------------------------------------------------
    @property
    def script_dir(self) -> Path:
        return self.exchange_dir / "script"

    @property
    def project_path(self) -> Path:
        return self.script_dir / PROJECT_FILE

    def _pascal_exchange_dir(self) -> str:
        self.exchange_dir.mkdir(parents=True, exist_ok=True)
        text = str(self.exchange_dir.resolve())
        if not text.isascii():
            text = _short_path(self.exchange_dir.resolve())
        if not text.isascii():
            raise BridgeError(
                f"Das Austauschverzeichnis {self.exchange_dir} enthält Sonderzeichen; bitte ein Verzeichnis ohne "
                "Umlaute konfigurieren."
            )
        if not text.endswith("\\"):
            text += "\\"
        return text.replace("'", "''")

    def ensure_scripts(self) -> Path:
        """Deploy the script project into the exchange directory (only rewritten if changed)."""
        exchange = self._pascal_exchange_dir()
        self.script_dir.mkdir(parents=True, exist_ok=True)
        for name in (*SCRIPT_UNITS, PROJECT_FILE, "THIRD_PARTY_NOTICES.txt"):
            source = SCRIPTS_DIR / name
            text = source.read_text(encoding="ascii").replace(EXCHANGE_PLACEHOLDER, exchange)
            data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii")
            target = self.script_dir / name
            if not target.exists() or target.read_bytes() != data:
                tmp = target.with_suffix(target.suffix + ".tmp")
                tmp.write_bytes(data)
                tmp.replace(target)
        return self.project_path

    def command_line(self, project: Path | None = None) -> str:
        """``"<X2.EXE>" -RScriptingSystem:RunScript(ProjectName="<prj>"|ProcName="PartForgeBridge>Run")``."""
        if not self.x2_path:
            raise BridgeError(_NO_X2)
        prj = project or self.project_path
        return f'"{self.x2_path}" -RScriptingSystem:RunScript(ProjectName="{prj}"|ProcName="{UNIT_NAME}>Run")'

    def stop_command_line(self) -> str:
        """``"<X2.EXE>" -REditScript:Stop`` – Altium's "Stop Debugging" process for the running instance."""
        if not self.x2_path:
            raise BridgeError(_NO_X2)
        return f'"{self.x2_path}" -R{STOP_PROCESS}'

    def stop_script(self, *, verify_timeout_s: float = 20.0, settle_s: float = 1.5) -> ScriptStopResult:
        """"Skript anhalten": stop a script paused in Altium's debugger – the usual cause of a wedge – and
        prove that the executor runs PartForge scripts again.

        Dispatches :data:`STOP_PROCESS` through the command line (no window focus, no keystrokes: Strg+F3
        reaches the debugger only while the script editor is the active document), waits ``settle_s`` for
        Altium to act on it and verifies with a ``ping`` (start deadline ``verify_timeout_s``) – a successful
        ping also clears :attr:`last_wedge`. It stops **any** paused script, also one the user is debugging,
        so it runs only on the user's request. Not recovered (a modal Altium message, a compile error,
        Altium busy) is reported, never guessed.
        """
        if not self.is_running():
            raise AltiumNotRunning("Altium Designer ist nicht gestartet. Bitte Altium starten und erneut versuchen.")
        command_line = self.stop_command_line()
        log.info("Altium-Brücke: Skript anhalten (%s)", STOP_PROCESS)
        try:
            # Altium may activate its window when the command arrives (see execute)
            real = self._launcher is _default_launcher
            with keep_foreground() if real else contextlib.nullcontext():
                self._launcher(command_line)
        except OSError as exc:
            raise BridgeError(f"Altium Designer konnte nicht angesprochen werden ({self.x2_path}): {exc}") from exc
        time.sleep(settle_s)
        try:
            version = self.execute("ping", timeout_s=verify_timeout_s).value("version")
        except BridgeWedgedError as exc:
            log.warning("Altium-Brücke: Skript anhalten hat nicht geholfen (%s)", exc.kind)
            return ScriptStopResult(
                dispatched=True,
                recovered=False,
                message="Das Skript konnte nicht beendet werden – Altium führt weiterhin keine PartForge-Skripte aus. "
                        "Bitte offene Altium-Meldungen schließen oder Altium Designer neu starten.",
                detail=str(exc),
            )
        return ScriptStopResult(
            dispatched=True,
            recovered=True,
            version=version or None,
            message="Das angehaltene Skript wurde beendet – Altium führt PartForge-Skripte wieder aus.",
        )

    # -- exchange -------------------------------------------------------------------
    def _paths(self, request_id: str) -> dict[str, Path]:
        d = self.exchange_dir
        return {
            "request": d / "request.txt",
            "response": d / f"response_{request_id}.txt",
            "log": d / f"log_{request_id}.txt",
            "spec": d / f"spec_{request_id}.txt",
        }

    def _last_log_line(self, path: Path) -> str | None:
        with contextlib.suppress(OSError):
            lines = [line.strip() for line in _read_altium_text(path).splitlines() if line.strip()]
            if lines:
                parts = lines[-1].split(" ", 1)
                return parts[1] if len(parts) == 2 and parts[0].isdigit() else lines[-1]
        return None

    def _wait(self, request_id: str, timeout_s: float) -> BridgeResponse:
        paths = self._paths(request_id)
        started = time.monotonic()
        start_deadline = started + min(self.start_timeout_s, timeout_s)
        deadline = started + timeout_s
        next_process_check = started + self.process_check_interval_s
        while True:
            if paths["response"].exists():
                try:
                    text = _read_altium_text(paths["response"])
                except OSError:
                    text = ""
                parsed = parse_response(text, request_id) if text else None
                if parsed is not None:
                    return parsed
            now = time.monotonic()
            log_exists = paths["log"].exists()
            if not log_exists and now >= start_deadline:
                self._mark_wedged(request_id, "never_started")
                raise BridgeWedgedError("never_started", seconds=now - started)
            if now >= deadline:
                last = self._last_log_line(paths["log"]) if log_exists else None
                self._mark_wedged(request_id, "did_not_finish", last)
                raise BridgeWedgedError(
                    "did_not_finish" if log_exists else "never_started", last_step=last, seconds=now - started
                )
            if now >= next_process_check:
                next_process_check = now + self.process_check_interval_s
                if not self.is_running():
                    raise AltiumNotRunning("Altium Designer wurde während des Vorgangs beendet.")
            time.sleep(self.poll_interval_s)

    def _mark_wedged(self, request_id: str, kind: str, last_step: str | None = None) -> None:
        state = {"request_id": request_id, "kind": kind, "last_step": last_step, "time": time.time()}
        with contextlib.suppress(OSError):
            (self.exchange_dir / "wedged.json").write_text(json.dumps(state), encoding="utf-8")
        log.error("Altium-Brücke hängt (%s, Anfrage %s, letzter Schritt: %s)", kind, request_id, last_step)

    @property
    def last_wedge(self) -> dict[str, Any] | None:
        """Information about the last detected wedge (cleared by the next successful call)."""
        path = self.exchange_dir / "wedged.json"
        with contextlib.suppress(OSError, json.JSONDecodeError):
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        return None

    def _cleanup(self, request_id: str, *, keep_log: bool) -> None:
        paths = self._paths(request_id)
        for key in ("response", "spec") + (() if keep_log else ("log",)):
            with contextlib.suppress(OSError):
                paths[key].unlink()
        with contextlib.suppress(OSError):
            paths["request"].unlink()
        logs = sorted(self.exchange_dir.glob("log_*.txt"), key=lambda p: p.stat().st_mtime)
        for old in logs[: max(0, len(logs) - self._keep_logs)]:
            with contextlib.suppress(OSError):
                old.unlink()

    def execute(
        self,
        command: str,
        args: Mapping[str, str] | None = None,
        *,
        spec: RenderedSpec | None = None,
        timeout_s: float | None = None,
        foreground: bool = False,
    ) -> BridgeResponse:
        """Run one bridge command in Altium and return the parsed response.

        ``foreground``: the user asked to work in Altium ("In Altium bearbeiten") – Altium may take the focus
        (no :func:`~.focus.keep_foreground` guard) and its main window is brought to the front afterwards."""
        if not self.is_running():
            raise AltiumNotRunning("Altium Designer ist nicht gestartet. Bitte Altium starten und erneut versuchen.")
        if not self.x2_path:
            raise BridgeError(_NO_X2)
        arguments = dict(args or {})
        timeout = float(timeout_s if timeout_s is not None else self.timeout_s)
        self.exchange_dir.mkdir(parents=True, exist_ok=True)
        with self._local_lock, _FileLock(self.exchange_dir / "bridge.lock", self.lock_timeout_s):
            command_line = self.command_line(self.ensure_scripts())
            request_id = uuid.uuid4().hex[:12]
            paths = self._paths(request_id)
            if spec is not None:
                paths["spec"].write_bytes(spec.text.encode("ascii"))
                arguments["spec"] = altium_safe_path(paths["spec"])
            request = render_request(request_id, command, arguments)
            tmp = paths["request"].with_suffix(".tmp")
            tmp.write_bytes(request.encode("ascii"))
            tmp.replace(paths["request"])
            log.info("Altium-Brücke: %s (Anfrage %s)", command, request_id)
            started = time.perf_counter()
            ok = False
            try:
                try:
                    # Altium activates its window when the command arrives: keep the user's window in front
                    # (only for the real launcher - test launchers never start X2.EXE) - unless the user wants
                    # to work in Altium now: then Altium may come to the front.
                    real = self._launcher is _default_launcher
                    if foreground and real:
                        allow_altium_foreground()
                    guard = keep_foreground() if real and not foreground else contextlib.nullcontext()
                    with guard:
                        self._launcher(command_line)
                except OSError as exc:
                    raise BridgeError(f"Altium Designer konnte nicht angesprochen werden ({self.x2_path}): {exc}") from exc
                response = self._wait(request_id, timeout)
                ok = response.ok
                if ok and foreground and self._launcher is _default_launcher:
                    bring_altium_to_front()
            finally:
                self._cleanup(request_id, keep_log=not ok)
            with contextlib.suppress(OSError):
                (self.exchange_dir / "wedged.json").unlink()
            log.info("Altium-Brücke: %s fertig in %.1f s", command, time.perf_counter() - started)
        if not response.ok:
            raise BridgeCommandError(command, response.error or "unbekannter Fehler")
        return response

    # -- own documents ----------------------------------------------------------------
    def _own_documents_file(self) -> Path:
        return self.exchange_dir / "own_documents.json"

    def _own_documents(self) -> list[str]:
        with contextlib.suppress(OSError, json.JSONDecodeError):
            data = json.loads(self._own_documents_file().read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(p) for p in data]
        return []

    def _remember_document(self, path: str) -> None:
        docs = self._own_documents()
        if path not in docs:
            docs.append(path)
            self.exchange_dir.mkdir(parents=True, exist_ok=True)
            self._own_documents_file().write_text(json.dumps(docs, indent=1), encoding="utf-8")

    # -- commands -------------------------------------------------------------------
    def ping(self) -> str:
        """Altium version string (also proves that the script executor works)."""
        return self.execute("ping", timeout_s=min(self.timeout_s, 60.0)).value("version")

    def installed_libraries(self) -> list[str]:
        return self.execute("installed_libraries").items.get("libraries", [])

    def install_library(self, path: Path) -> bool:
        resp = self.execute("install_library", {"path": altium_safe_path(Path(path))})
        return resp.flag("installed")

    def uninstall_library(self, path: Path) -> bool:
        resp = self.execute("uninstall_library", {"path": altium_safe_path(Path(path))})
        return not resp.flag("installed")

    def open_document(self, path: Path, kind: str | None = None) -> bool:
        """Open (or focus) a document in Altium; returns True if it was already open."""
        p = Path(path)
        doc_kind = kind or _document_kind(p)
        safe = altium_safe_path(p)
        resp = self.execute("open_document", {"path": safe, "kind": doc_kind})
        was_open = resp.flag("was_open")
        if not was_open:
            self._remember_document(safe)
        return was_open

    def edit_component(self, path: Path, name: str, kind: str | None = None) -> ComponentFocus:
        """Open (or focus) a SchLib/PcbLib and show the component ``name`` in its library editor
        ("In Altium bearbeiten"). The document is never modified, saved or closed – the user edits and
        saves it in Altium. Unlike :meth:`open_document` the library is not remembered as PartForge's
        own document: :meth:`close_own_documents` must never close it while the user works in it."""
        p = Path(path)
        doc_kind = kind or _document_kind(p)
        if doc_kind not in ("SCHLIB", "PCBLIB"):
            raise BridgeError(f"„{p.name}“ ist keine SchLib oder PcbLib.")
        safe = altium_safe_path(p)
        resp = self.execute("edit_component", {"path": safe, "kind": doc_kind, "name": name}, foreground=True)
        return ComponentFocus(
            path=safe,
            name=name,
            was_open=resp.flag("was_open"),
            found=resp.flag("found"),
            current=resp.value("current", "") or "",
            modified=resp.flag("modified"),
        )

    def document_state(self, path: Path) -> DocumentState:
        """Open/modified state of a document in Altium (e.g. before rewriting a library)."""
        safe = altium_safe_path(Path(path))
        resp = self.execute("document_state", {"path": safe})
        return DocumentState(path=safe, open=resp.flag("open"), modified=resp.flag("modified"))

    #: Paths per ``document_states`` run (one script start for many libraries).
    DOCUMENT_STATES_BATCH = 200

    def document_states(self, paths: Sequence[Path]) -> dict[str, DocumentState]:
        """Open/modified state of many documents (one script run per :data:`DOCUMENT_STATES_BATCH` paths);
        keyed by ``os.path.normcase`` of the path."""
        out: dict[str, DocumentState] = {}
        items = [Path(p) for p in paths]
        for start in range(0, len(items), self.DOCUMENT_STATES_BATCH):
            chunk = items[start : start + self.DOCUMENT_STATES_BATCH]
            safe = [altium_safe_path(p) for p in chunk]
            args: dict[str, str] = {"count": str(len(safe))}
            for i, path in enumerate(safe):
                args[f"path{i}"] = path
            resp = self.execute("document_states", args)
            for i, (original, path) in enumerate(zip(chunk, safe, strict=True)):
                state = DocumentState(path=path, open=resp.flag(f"open{i}"), modified=resp.flag(f"modified{i}"))
                out[os.path.normcase(str(original))] = state
        return out

    def refresh_document(self, path: Path, kind: str | None = None) -> Literal["not_open", "modified", "reloaded", "closed"]:
        """Make Altium show a library rewritten outside Altium (close + reopen if unmodified).

        Altium keeps no handle on open libraries and does not notice outside changes
        (VERIFIED, altium-verify-2 §5.1). A modified document is left alone (``"modified"``):
        saving it in Altium would overwrite PartForge's change. A document Altium holds open
        without showing it (opened by Altium itself or another script) is reopened hidden –
        no editor tab appears that the user did not have (VERIFIED, altium-e2e.md).
        """
        p = Path(path)
        resp = self.execute("refresh_document", {"path": altium_safe_path(p), "kind": kind or _document_kind(p)})
        state = resp.value("state", "not_open")
        if state not in ("not_open", "modified", "reloaded", "closed"):
            raise BridgeCommandError("refresh_document", f"unerwarteter Zustand {state!r}")
        return state  # type: ignore[return-value]

    def close_own_documents(self) -> dict[str, list[str]]:
        """Close the (unmodified) documents PartForge opened; modified ones stay open."""
        docs = self._own_documents()
        if not docs:
            return {"closed": [], "modified": [], "not_open": []}
        args: dict[str, str] = {"count": str(len(docs))}
        for i, doc in enumerate(docs):
            args[f"path{i}"] = doc
        resp = self.execute("close_own_documents", args)
        result = {key: resp.items.get(key, []) for key in ("closed", "modified", "not_open")}
        remaining = [d for d in docs if d in result["modified"]]
        with contextlib.suppress(OSError):
            self._own_documents_file().write_text(json.dumps(remaining, indent=1), encoding="utf-8")
        return result

    def list_components(self, path: Path) -> list[str]:
        p = Path(path)
        resp = self.execute(
            "list_components", {"path": altium_safe_path(p), "kind": _document_kind(p)}
        )
        return [row[0] for row in resp.rows.get("components", []) if row]

    def resolve_db_component(self, dblib: Path, table: str, key: str) -> DbComponentResolution:
        """Resolve a DbLib record through Altium (symbol path/name, pins, footprints, parameters)."""
        return self.resolve_db_components(dblib, [(table, key)])[0]

    def resolve_db_components(
        self, dblib: Path, keys: Sequence[tuple[str, str]], *, timeout_s: float | None = None
    ) -> list[DbComponentResolution]:
        """Resolve DbLib records ``(table, key)`` through Altium, :data:`RESOLVE_BATCH_SIZE` per
        script run, exactly like :meth:`resolve_db_component` – results in the order of ``keys``.

        A script start costs about 1.3 s, a lookup a few milliseconds (altium-e2e.md, Welle 3).
        A DbLib that is not installed is installed for each run only and released again.
        """
        wanted = [(str(table), str(key)) for table, key in keys]
        safe = altium_safe_path(Path(dblib))
        out: list[DbComponentResolution] = []
        for start in range(0, len(wanted), RESOLVE_BATCH_SIZE):
            chunk = wanted[start : start + RESOLVE_BATCH_SIZE]
            args: dict[str, str] = {"dblib": safe, "count": str(len(chunk))}
            for index, (table, key) in enumerate(chunk):
                args[f"table{index}"] = table
                args[f"key{index}"] = key
            resp = self.execute("resolve_db_components", args, timeout_s=timeout_s)
            out.extend(parse_db_resolutions(resp, str(dblib), chunk))
        return out

    # -- DbLib refresh / install state (altium-refresh.md) -------------------------------
    def install_state(self, dblib_path: str | os.PathLike[str]) -> DbLibInstallState:
        """Is this DbLib installed, and which installed libraries share its file name?

        Read-only: lists Altium's installed libraries and the state of their (hidden)
        server documents; nothing is opened, closed or installed.
        """
        target = Path(dblib_path)
        file_name = dblib_file_name(target)
        safe = altium_safe_path(target)
        resp = self.execute("dblib_install_state", {"path": safe, "file_name": file_name})
        entries: list[InstalledDbLib] = []
        for row in resp.rows.get("same_name", []):
            if len(row) < 6:
                continue
            index, path, _exact, is_open, shown, modified = row[:6]
            entries.append(
                InstalledDbLib(
                    index=int(index) if index.isdigit() else len(entries),
                    path=path,
                    same_file=_same_file(path, target),
                    document_open=is_open == "1",
                    document_shown=shown == "1",
                    document_modified=modified == "1",
                )
            )
        entries.sort(key=lambda e: e.index)
        mine = [e for e in entries if e.same_file]
        count = resp.value("installed_count")
        return DbLibInstallState(
            path=safe,
            file_name=file_name,
            installed=bool(mine),
            position=mine[0].index if mine else None,
            same_name=entries,
            duplicates=[e.path for e in entries if not e.same_file],
            first_match=entries[0].path if entries else None,
            resolves_to_this=bool(entries) and entries[0].same_file,
            installed_count=int(count) if count.isdigit() else 0,
        )

    def refresh_dblib(
        self, file_name: str | os.PathLike[str], rebuild_index: bool = False, *, timeout_s: float | None = None
    ) -> DbLibRefreshResult:
        """Make the running Altium re-read the PartForge database (VERIFIED procedure).

        Altium keeps the installed DbLib open as a hidden server document whose ODBC
        connection pins a SQLite snapshot; closing it makes every later lookup fresh.
        ``rebuild_index`` additionally runs ``IntegratedLibrary:RefreshInstalledLibraries``
        (clears Altium's "not found" cache after inserts; reloads **all** installed
        libraries, ~3 s) and closes the reopened document again. Only documents of
        installed libraries with exactly this **file name** are touched, and never one
        that is shown in an editor or has unsaved edits (altium-refresh.md §7.4).
        """
        name = dblib_file_name(file_name)
        started = time.perf_counter()
        resp = self.execute(
            "refresh_dblib", {"file_name": name, "rebuild": "1" if rebuild_index else "0"}, timeout_s=timeout_s
        )
        result = DbLibRefreshResult(file_name=name, rebuild_index=bool(rebuild_index))
        result.matched = list(dict.fromkeys(resp.items.get("matched", [])))
        for row in resp.rows.get("docs", []):
            if len(row) < 3:
                continue
            path, state = row[1], row[2]
            if state == "closed":
                if path not in result.closed:
                    result.closed.append(path)
            elif state == "not_open":
                if path not in result.not_open and path not in result.closed:
                    result.not_open.append(path)
            elif state in ("shown", "modified", "other_kind"):
                result.skipped[path] = state
        result.not_open = [p for p in result.not_open if p not in result.closed]
        result.refreshed_index = resp.flag("refreshed")
        refresh_ms = resp.value("refresh_ms")
        result.refresh_ms = int(refresh_ms) if refresh_ms.isdigit() else None
        result.duration_s = round(time.perf_counter() - started, 3)
        return result

    def _write_library(self, command: str, target: Path, spec: RenderedSpec, keep_open: bool) -> BridgeWriteResult:
        if target.exists():
            raise BridgeError(f"Die Zieldatei existiert bereits: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        resp = self.execute(
            command,
            {"path": altium_safe_path(target), "keep_open": "1" if keep_open else "0"},
            spec=spec,
        )
        if keep_open:
            self._remember_document(altium_safe_path(target))
        written = resp.items.get("written", [])
        missing = [n for n in spec.names if n not in written]
        warnings = [*spec.warnings, *resp.warnings]
        if missing:
            warnings.append(f"In Altium nicht erzeugt: {', '.join(missing)}")
        created = resp.value("created")
        return BridgeWriteResult(
            path=str(target),
            written=written,
            warnings=warnings,
            created=int(created) if created.isdigit() else len(written),
            duration_s=round(time.perf_counter() - started, 3),
        )

    def write_schlib(
        self,
        target: Path,
        symbols: Sequence[SymbolSpec],
        *,
        style: SymbolStyle | None = None,
        keep_open: bool = False,
    ) -> BridgeWriteResult:
        """Build a **new** SchLib at ``target`` (must not exist) from ``symbols``."""
        spec = render_schlib_spec(symbols, style=style)
        return self._write_library("write_schlib", Path(target), spec, keep_open)

    def write_pcblib(
        self,
        target: Path,
        footprints: Sequence[FootprintSpec],
        *,
        layer_map: LayerMap | None = None,
        style: FootprintStyle | None = None,
        keep_open: bool = False,
    ) -> BridgeWriteResult:
        """Build a **new** PcbLib at ``target`` (must not exist) from ``footprints``."""
        spec = render_pcblib_spec(footprints, layer_map=layer_map, style=style)
        return self._write_library("write_pcblib", Path(target), spec, keep_open)


def _document_kind(path: Path) -> str:
    """Altium document kind from the extension (VERIFIED kinds, altium-live.md §1)."""
    kinds = {
        ".schlib": "SCHLIB",
        ".pcblib": "PCBLIB",
        ".dblib": "DATABASELIB",
        ".schdoc": "SCH",
        ".pcbdoc": "PCB",
        ".intlib": "IntLibrary",
        ".dblink": "DATABASELINK",
    }
    kind = kinds.get(path.suffix.lower())
    if kind is None:
        raise BridgeError(f"Unbekannter Altium-Dokumenttyp: {path.name}")
    return kind
