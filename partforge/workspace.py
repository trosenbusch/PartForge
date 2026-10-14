"""A PartForge workspace ("Bibliotheksordner") is a self-contained, movable folder:

    <root>/
        partforge.json        workspace settings (this module)
        PartForge.sqlite      database (Altium reads it through ODBC)
        PartForge.DbLib       generated Altium database library file (relative paths)
        Symbols/              .SchLib files
        Footprints/           .PcbLib files
        3D/                   STEP models
        Datasheets/           PDF datasheets (content-addressed names)
        Backups/              automatic database backups
        Exports/              CSV/XLSX exports, reports

All paths stored in the database are relative to the workspace root and use
backslashes (Altium convention), see :meth:`Workspace.rel`.

One PartForge process per library: while a library is open, its process holds an exclusive lock on
``partforge.lock`` in the folder (:func:`lock_library`; the file names the holder: PC, user, process).
A second PartForge – a second window, a second Windows user, another PC on a shared folder – is refused
with :class:`LibraryLocked` (German message, API: HTTP 409) instead of writing the same database and
SchLib/PcbLib files concurrently. The operating system releases the lock when the process ends, also
after a crash.
"""
from __future__ import annotations

import datetime as _dt
import getpass
import json
import logging
import os
import socket
import string
import threading
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, Field

WORKSPACE_FILE = "partforge.json"
LOCK_FILE = "partforge.lock"
#: Default format of internal part numbers (``part_number_scheme = "internal"``).
DEFAULT_PN_FORMAT = "{prefix}-{counter:06d}"
_PN_FIELDS = frozenset({"prefix", "counter", "table"})

log = logging.getLogger(__name__)


class WorkspaceNotOpen(RuntimeError):
    """No workspace is open (API maps this to HTTP 409)."""


class LibraryLocked(RuntimeError):
    """The library folder is open in another PartForge process (German message; API: HTTP 409)."""

    def __init__(self, root: Path, holder: dict[str, object] | None) -> None:
        who = ""
        if holder:
            host, user, pid = holder.get("host"), holder.get("user"), holder.get("pid")
            since = str(holder.get("since") or "").replace("T", " ")
            parts = [f"Rechner {host}" if host else "", f"Benutzer {user}" if user else "",
                     f"Prozess {pid}" if pid else "", f"seit {since}" if since else ""]
            who = " (" + ", ".join(p for p in parts if p) + ")"
        super().__init__(
            f"Die Bibliothek „{root}“ ist bereits in einem anderen PartForge geöffnet{who}. Zwei PartForge auf "
            "derselben Bibliothek würden sich gegenseitig Datenbank und Bibliotheksdateien überschreiben – bitte "
            "das andere PartForge-Fenster verwenden oder die Bibliothek dort schließen.")
        self.root = root
        self.holder = holder


class DbSettings(BaseModel):
    kind: Literal["sqlite", "postgres"] = "sqlite"
    sqlite_file: str = "PartForge.sqlite"
    # SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@server:5432/parts
    postgres_url: str | None = None
    # ODBC attributes Altium uses for PostgreSQL, e.g.
    # "DRIVER={PostgreSQL Unicode(x64)};SERVER=srv;PORT=5432;DATABASE=parts;UID=altium;PWD=..."
    postgres_odbc: str | None = None
    # WAL is required: VERIFIED in Altium 26.10 that in DELETE mode Altium's ODBC connection
    # blocks every PartForge write for the whole Altium session. WAL must be set when the file
    # is created (before Altium connects). SQLite on network shares is therefore unsupported.
    journal_mode: Literal["wal", "delete"] = "wal"


class Folders(BaseModel):
    symbols: str = "Symbols"
    footprints: str = "Footprints"
    models: str = "3D"
    datasheets: str = "Datasheets"
    backups: str = "Backups"
    exports: str = "Exports"


class LayerMap(BaseModel):
    """Logical footprint layers -> Altium layer names (exact names as accepted by the
    library writers: "Top Overlay", "Mechanical 15", ...).

    Defaults follow the user's current standard mechanical layer stack
    (C:\\PartForge-Examples\\Altium_Templates\\Mechanical_Stackup_Standard\\mechanical_layer.stackup,
    Altium component layer pairs with layer types): Mech9 Top Assembly, Mech11 Top Designator,
    Mech13 Top 3D Body, Mech15 Top Courtyard, Mech17 Top Component Center, Mech19 Top Value,
    Mech21 Top Component Outline. (The older TR_* libraries used the IPC-wizard numbering.)
    Mech 2-7 must stay unused: the Rust writer declares them as typed assembly/courtyard/3D
    layers in every PcbLib header (VERIFIED).
    """

    silkscreen: str = "Top Overlay"
    assembly: str = "Mechanical 9"
    designator: str = "Mechanical 11"
    body3d: str = "Mechanical 13"
    courtyard: str = "Mechanical 15"
    component_center: str = "Mechanical 17"
    comment: str = "Mechanical 19"
    component_outline: str = "Mechanical 21"


class LayerSetSettings(BaseModel):
    """Own layer set (Altium *View Configuration › Layer Sets*) written into every PcbLib header.

    ``mode``: ``none`` (only Altium's built-in sets), ``builtin`` (built from the LayerMap – copper, paste,
    overlay, solder, drill and every mechanical layer PartForge draws on; name ``Component Layers`` unless
    ``name`` is set) or ``file`` (``name``/``layers``/… read from a ``.layerset`` file; ``file`` is only the
    origin, the definition is stored here so the library folder stays self-contained). ``current``: the set is
    active when the library is opened in Altium. See :mod:`partforge.altium.layersets`.
    """

    mode: Literal["none", "builtin", "file"] = "none"
    file: str | None = None
    name: str | None = None
    layers: list[str] = Field(default_factory=list)
    active_layer: str | None = None
    current: bool = True
    locked: bool = False
    flip_board: bool = False


class FootprintStyle(BaseModel):
    density: Literal["M", "N", "L"] = "N"
    naming: Literal["ipc", "house"] = "ipc"
    rounding: Literal["kicad", "ipc"] = "kicad"  # kicad: Z/G/X to 0.05 mm (0.02 < 0603); ipc: 0.01 mm
    fab_tolerance: float = 0.10  # F (mm)
    placement_tolerance: float = 0.05  # P (mm)
    silk_width: float = 0.20  # mm, ICs / connectors
    silk_width_small: float = 0.15  # mm, chip passives
    silk_pad_clearance: float = 0.2  # mm
    pin1_dot_radius: float = 0.125  # mm (arc radius, drawn with 2x radius width)
    assembly_width: float = 0.1  # mm
    courtyard_width: float = 0.05  # mm
    courtyard_grid: float = 0.05  # mm, courtyard rectangle rounded outward to this grid
    min_copper_gap: float = 0.15  # mm, minimum gap between lands (clamps pad size vs pitch)
    center_cross: bool = True  # 0.1 mm cross ±0.5 mm at the origin on the component_center layer
    text_height: float = 1.0  # mm (.Designator / .Comment on mechanical layers)
    # Font of .Designator/.Comment: Altium stroke font or a TrueType font (e.g. Arial, as Altium's IPC wizard)
    text_font: Literal["stroke", "truetype"] = "stroke"
    text_font_name: str = "Arial"
    pad_corner_radius_pct: int = 50  # Altium corner-radius % (50 % = r of 25 % of the shorter side)
    exposed_pad_designator: Literal["next", "EP"] = "next"  # EP numbered N+1 (datasheet style) or "EP"
    generate_3d: bool = True


class SymbolStyle(BaseModel):
    """Schematic symbol house style (units: mil). Colours as #RRGGBB."""

    grid: int = 100
    ic_pin_length: int = 200
    discrete_pin_length: int = 100
    ic_line_color: str = "#800000"
    ic_fill_color: str = "#FFFFB0"
    discrete_line_color: str = "#0000FF"
    pin_color: str = "#000000"
    line_width: Literal["smallest", "small", "medium", "large"] = "small"
    font: str = "Times New Roman"  # house font: designator, Comment, parameters, free texts (font table of the SchLib)
    font_size: int = 10
    # Pin names and numbers: the house font as Altium "custom font" of every pin, or the sheet's system font
    pin_font: Literal["house", "system"] = "house"
    diode_pin1: Literal["cathode", "anode"] = "cathode"  # IPC: cathode = 1 (house libraries used anode = 1)
    resistor_style: Literal["iec", "ansi"] = "iec"


class WorkspaceSettings(BaseModel):
    version: int = 1
    name: str = "PartForge-Bibliothek"
    created: str = Field(default_factory=lambda: _dt.datetime.now().isoformat(timespec="seconds"))
    db: DbSettings = Field(default_factory=DbSettings)
    folders: Folders = Field(default_factory=Folders)
    dblib_file: str = "PartForge.DbLib"
    library_layout: Literal["grouped", "per_item"] = "grouped"
    part_number_scheme: Literal["mpn", "internal"] = "mpn"
    # Python format with {prefix}, {counter} (exactly once) and {table}; checked by pn_format_problem()
    internal_pn_format: str = DEFAULT_PN_FORMAT
    layers: LayerMap = Field(default_factory=LayerMap)
    # Optional Altium .stackup file whose mechanical layer names/types are written into the
    # header of every PcbLib PartForge writes (None = built-in standard matching LayerMap).
    layer_stackup: str | None = None
    # Own layer set of every PcbLib PartForge writes (Altium View Configuration › Layer Sets)
    layer_set: LayerSetSettings = Field(default_factory=LayerSetSettings)
    footprint: FootprintStyle = Field(default_factory=FootprintStyle)
    symbol: SymbolStyle = Field(default_factory=SymbolStyle)


def pn_format_problem(fmt: str | None) -> str | None:
    """German problem of a format for internal part numbers, ``None`` if it is usable.

    Allowed: the placeholders ``{prefix}``, ``{table}`` and **exactly one** ``{counter}`` (with an integer
    format such as ``{counter:06d}``), literal text and ``{{``/``}}``. Every number it generates must be a
    valid part number as typed by hand: no ``' { } |``, control or invisible characters and no blanks at
    the edges – checked on samples, which must differ for different counters."""
    text = fmt if isinstance(fmt, str) else ""
    example = "z. B. {prefix}-{counter:06d}"
    if not text.strip():
        return f"Das Format der internen Teilenummern darf nicht leer sein ({example})."
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError:
        return f"Im Format „{text}“ ist eine geschweifte Klammer nicht geschlossen ({example}; Klammern als Text: {{{{ }}}})."
    counters = 0
    for _literal, name, spec, conversion in parsed:
        if name is None:
            continue
        if name not in _PN_FIELDS:
            shown = "{" + name + "}" if name else "{}"
            return (f"Unbekannter Platzhalter „{shown}“ im Format „{text}“ – erlaubt sind {{prefix}}, {{counter}} und "
                    "{table}.")
        if conversion or (spec and "{" in spec):
            return f"Der Platzhalter „{{{name}}}“ im Format „{text}“ wird so nicht unterstützt ({example})."
        counters += name == "counter"
    if counters != 1:
        return (f"Das Format „{text}“ muss genau einmal {{counter}} enthalten – sonst entstünde immer dieselbe "
                f"Teilenummer ({example}).")
    from .db.values import PART_NUMBER, normalize_cell  # runtime import: the db package imports this module
    from .db.models import FieldDef

    field = FieldDef(column=PART_NUMBER, label="Teilenummer")
    samples: list[str] = []
    for prefix, counter, table in (("R", 1, "Resistors"), ("R", 2, "Resistors"), ("C", 42, "Ferrite Beads"),
                                   ("U", 999999, "ICs")):
        try:
            candidate = text.format(prefix=prefix, counter=counter, table=table)
        except (KeyError, IndexError, ValueError, TypeError):
            return (f"Das Format „{text}“ lässt sich nicht anwenden – eine Formatangabe passt nicht zu ihrem "
                    f"Platzhalter (Zähler sind Zahlen, z. B. {{counter:06d}}; Präfix und Tabelle Text).")
        res = normalize_cell(field, candidate)
        if res.error:
            return f"Das Format „{text}“ erzeugt „{candidate}“: {res.error}"
        if res.value != candidate:
            return (f"Das Format „{text}“ erzeugt „{candidate}“ – Teilenummern dürfen keine Leerzeichen am Anfang oder "
                    "Ende, keine doppelten Leerzeichen, Tabulatoren oder unsichtbaren Zeichen enthalten.")
        samples.append(candidate)
    if len(set(samples)) != len(samples):
        return f"Im Format „{text}“ ändert der Zähler die Teilenummer nicht ({example})."
    return None


def long_path_name(path: str) -> str:
    """The absolute ``path`` with every existing component spelled as on disk (case, long instead of 8.3 names)
    – without resolving junctions, symbolic links or mapped drives: each component is looked up with
    ``FindFirstFileW`` (which reports a junction under its own name). Components that do not exist yet are
    appended as given; outside Windows the path is returned unchanged."""
    if os.name != "nt":
        return path
    import ctypes
    from ctypes import wintypes

    class WIN32_FIND_DATAW(ctypes.Structure):  # noqa: N801 - Windows structure name
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("dwReserved0", wintypes.DWORD),
            ("dwReserved1", wintypes.DWORD),
            ("cFileName", ctypes.c_wchar * 260),
            ("cAlternateFileName", ctypes.c_wchar * 14),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.FindFirstFileW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(WIN32_FIND_DATAW)]
    kernel32.FindFirstFileW.restype = wintypes.HANDLE
    kernel32.FindClose.argtypes = [wintypes.HANDLE]
    kernel32.FindClose.restype = wintypes.BOOL
    invalid = wintypes.HANDLE(-1).value

    drive, rest = os.path.splitdrive(path.replace("/", "\\"))
    if len(drive) == 2 and drive[1] == ":":
        drive = drive.upper()
    out = drive + "\\"
    exists = True
    for part in (p for p in rest.split("\\") if p):
        if exists and part not in (".", ".."):
            data = WIN32_FIND_DATAW()
            handle = kernel32.FindFirstFileW(os.path.join(out, part), ctypes.byref(data))
            if handle and handle != invalid:
                kernel32.FindClose(handle)
                part = data.cFileName or part
            else:
                exists = False
        out = os.path.join(out, part)
    return out


class Workspace:
    def __init__(self, root: Path, settings: WorkspaceSettings):
        self.root = Path(root).resolve()
        #: The folder as the user opened it – drive letters, junctions and symbolic links kept, only the spelling of
        #: existing components normalised (:func:`long_path_name`). ``root`` resolves those for the comparisons inside
        #: PartForge; paths handed to Altium use this spelling (``partforge.altium.bridge.core.canonical_path``), because
        #: Altium compares document paths literally and the user opens documents through the drive they see.
        self.opened_as = Path(long_path_name(os.path.abspath(os.fspath(root))))
        self.settings = settings
        #: German notes about this library for the user (DbLib path or name problems …, shown by the API)
        self.warnings: list[str] = []
        #: German note when the internal part number format of partforge.json could not be used (default applies)
        self.pn_format_warning: str | None = None

    # -- construction -----------------------------------------------------------------
    @classmethod
    def is_workspace(cls, root: str | Path) -> bool:
        return (Path(root) / WORKSPACE_FILE).is_file()

    @classmethod
    def open(cls, root: str | Path) -> Workspace:
        root = Path(root)
        cfg = root / WORKSPACE_FILE
        if not cfg.is_file():
            raise FileNotFoundError(f"Kein PartForge-Bibliotheksordner: {root}")
        settings = WorkspaceSettings.model_validate_json(cfg.read_text(encoding="utf-8"))
        ws = cls(root, settings)
        problem = pn_format_problem(settings.internal_pn_format)
        if problem is not None:  # e.g. hand-edited partforge.json: never hang or write forbidden numbers
            settings.internal_pn_format = DEFAULT_PN_FORMAT
            note = (f"{problem} Bis zur Korrektur (Einstellungen › Bibliothek › Teilenummern) gilt das Standardformat "
                    f"{DEFAULT_PN_FORMAT}.")
            ws.pn_format_warning = note
            log.warning("%s: %s", cfg, note)
        ws.ensure_folders()
        return ws

    @classmethod
    def create(cls, root: str | Path, name: str | None = None, settings: WorkspaceSettings | None = None) -> Workspace:
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        if (root / WORKSPACE_FILE).exists():
            raise FileExistsError(f"Ordner enthält bereits eine PartForge-Bibliothek: {root}")
        settings = settings or WorkspaceSettings()
        if name:
            settings.name = name
        ws = cls(root, settings)
        ws.ensure_folders()
        ws.save()
        return ws

    def save(self) -> None:
        cfg = self.root / WORKSPACE_FILE
        tmp = cfg.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.settings.model_dump(mode="json"), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(cfg)

    def ensure_folders(self) -> None:
        for folder in self.settings.folders.model_dump().values():
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    # -- paths ------------------------------------------------------------------------
    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @property
    def sqlite_path(self) -> Path:
        return self.root / self.settings.db.sqlite_file

    @property
    def dblib_path(self) -> Path:
        return self.root / self.settings.dblib_file

    @property
    def symbols_dir(self) -> Path:
        return self.root / self.settings.folders.symbols

    @property
    def footprints_dir(self) -> Path:
        return self.root / self.settings.folders.footprints

    @property
    def models_dir(self) -> Path:
        return self.root / self.settings.folders.models

    @property
    def datasheets_dir(self) -> Path:
        return self.root / self.settings.folders.datasheets

    @property
    def backups_dir(self) -> Path:
        return self.root / self.settings.folders.backups

    @property
    def exports_dir(self) -> Path:
        return self.root / self.settings.folders.exports

    def rel(self, path: str | Path) -> str:
        """Workspace-relative path with backslashes (as stored in the database)."""
        p = Path(path)
        if not p.is_absolute():
            return str(PureWindowsPath(p))
        try:
            return str(PureWindowsPath(p.resolve().relative_to(self.root)))
        except ValueError:
            return str(PureWindowsPath(p))

    def abs(self, stored: str | None) -> Path | None:
        """Resolve a path stored in the database (relative or absolute)."""
        if not stored:
            return None
        p = Path(str(stored).replace("\\", "/"))
        return p if p.is_absolute() else (self.root / p)

    def info(self) -> dict:
        return {
            "root": str(self.root),
            "name": self.settings.name,
            "db_kind": self.settings.db.kind,
            "sqlite_path": str(self.sqlite_path),
            "dblib_path": str(self.dblib_path),
            "settings": self.settings.model_dump(mode="json"),
            "warnings": [*self.warnings, *([self.pn_format_warning] if self.pn_format_warning else [])],
        }


_lock = threading.RLock()
_current: Workspace | None = None

# ---- library lock (one PartForge process per library folder)

_LOCK_OFFSET = 1 << 30  # the locked byte lies far behind the holder info, which stays readable for others
_locks_guard = threading.Lock()
_held: dict[str, int] = {}  # normcase(root) -> file descriptor of the locked partforge.lock


def _lock_key(root: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(root)))


def _lock_byte(fd: int, lock: bool) -> bool:
    """Lock/unlock the lock byte of ``fd`` (non-blocking); ``False`` if another process holds it."""
    try:
        import msvcrt
    except ImportError:  # pragma: no cover - PartForge runs on Windows; elsewhere: advisory lock
        import fcntl

        try:
            fcntl.lockf(fd, (fcntl.LOCK_EX | fcntl.LOCK_NB) if lock else fcntl.LOCK_UN, 1, _LOCK_OFFSET)
        except OSError:
            return False
        return True
    os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK if lock else msvcrt.LK_UNLCK, 1)
    except OSError:
        return False
    return True


def library_lock_holder(root: str | os.PathLike[str]) -> dict[str, object] | None:
    """Who holds (or last held) the lock of the library at ``root`` (``host``, ``user``, ``pid``, ``since``)."""
    try:
        with open(Path(root) / LOCK_FILE, encoding="utf-8") as fh:
            data = json.loads(fh.read(4096) or "{}")
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lock_library(root: str | os.PathLike[str]) -> bool:
    """Lock the library folder ``root`` for this process. ``True`` if newly locked, ``False`` if this
    process holds it already; :class:`LibraryLocked` if another process (or PC) holds it."""
    key = _lock_key(root)
    with _locks_guard:
        if key in _held:
            return False
        path = Path(root) / LOCK_FILE
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOINHERIT", 0))
        try:
            if not _lock_byte(fd, True):
                raise LibraryLocked(Path(root), library_lock_holder(root))
            info = {"host": socket.gethostname(), "user": getpass.getuser(), "pid": os.getpid(),
                    "since": _dt.datetime.now().isoformat(timespec="seconds")}
            data = json.dumps(info).encode("utf-8")
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, data)
            os.ftruncate(fd, len(data))
        except BaseException:
            os.close(fd)
            raise
        _held[key] = fd
        return True


def unlock_library(root: str | os.PathLike[str]) -> None:
    """Release the lock of ``root`` held by this process (no-op if it holds none)."""
    with _locks_guard:
        fd = _held.pop(_lock_key(root), None)
    if fd is None:
        return
    try:
        _lock_byte(fd, False)
    finally:
        os.close(fd)


def holds_library_lock(root: str | os.PathLike[str]) -> bool:
    with _locks_guard:
        return _lock_key(root) in _held


def current() -> Workspace:
    """The open workspace; raises :class:`WorkspaceNotOpen` if none is open."""
    with _lock:
        if _current is None:
            raise WorkspaceNotOpen("Es ist keine Bibliothek geöffnet.")
        return _current


def current_or_none() -> Workspace | None:
    with _lock:
        return _current


def set_current(ws: Workspace | None) -> None:
    global _current
    with _lock:
        _current = ws


def same_folder(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    """Whether two paths name the same library folder (absolute, Windows rules: case-insensitive, ``/`` = ``\\``)."""
    return os.path.normcase(os.path.abspath(os.fspath(a))) == os.path.normcase(os.path.abspath(os.fspath(b)))


def current_for(root: str | os.PathLike[str]) -> Workspace | None:
    """The open workspace if it is the library folder ``root``, else ``None`` (library guard,
    :func:`partforge.jobs.library_hold`: a job only writes into the library it was started for)."""
    with _lock:
        ws = _current
    return ws if ws is not None and same_folder(ws.root, root) else None
