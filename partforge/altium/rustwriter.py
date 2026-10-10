"""Rust library writer backend (``altium-designer-mcp.exe``, MCP over stdio).

The GPL-3.0 tool is only ever spawned as a separate process (arm's-length use). PartForge
keeps one long-lived server per backend process (:func:`get_client`) with its own
generated configuration: ``allowed_paths`` = open workspace root + PartForge temp dir
(+ explicitly passed extra directories). Temp files, the generated configurations and the audit log live in
the local folder of this PC (:func:`partforge.config.local_data_dir`, :func:`partforge.config.log_dir`) – never in
the roaming profile; the audit log is capped (:data:`AUDIT_LOG_MAX_BYTES`, one older generation kept).

Facts this module relies on (``docs/entwicklung/recherche/rust-writer.md`` and
``altium-verify-rust.md``, VERIFIED unless noted):

* Every mutation rewrites the whole library (~10 ms per footprint) -> batch writes.
* ``write_schlib`` silently drops pins with float coordinates or int designators and
  silently replaces unknown enum values -> strict client-side validation
  (:func:`validate_symbol_payload`, :func:`validate_footprint_payload`) plus a check of
  the pin echo and of the component metadata after every write.
* Polygons/polylines read back as ``[[x, y]]`` but must be written as ``[{x, y}]``
  (:func:`fix_points`).
* No upsert: ``component_exists`` -> ``update_component`` / one ``append`` call.
* ``step_model`` with ``embed: false`` writes no model reference; with ``embed: true``
  the STEP body gets height 0 and the ``component_bodies`` of that footprint are
  dropped; ``update_component`` ignores ``step_model``. PartForge therefore embeds STEP
  data through temporary carrier footprints and writes its own STEP body with the real
  height plus the extruded bodies (:meth:`RustLibraryOps._embed_step_models`).
* Pin decorations above ordinal 6 are stored wrongly and ``text`` is written as
  RECORD=3 -> only the seven safe decorations and ``labels`` are used.
* Non-simple pad stacks lose shapes -> ``stack_mode`` is always ``simple``.
* Altium paints symbol records in file order and the writer emits pins first, so a
  filled body hides the pin names (altium-verify-2 §3.3) -> every symbol carries a
  ``primitive_order`` with the graphics first (an unknown token silently discards the
  whole order, so tokens are validated and the stored order is read back).
* Altium anchors single-line stroke text bottom-left and ignores the justification ->
  the location is compensated (:func:`stroke_text_anchor`) and the justification kept.
* PcbLib strings are stored as Latin-1 (``Ω`` becomes ``?``) -> transliterated.
* Strings are stored unescaped in ``|KEY=value|`` records: a ``|`` in a description or
  parameter truncates it or injects keys (even renames a footprint), control characters
  drop records -> rejected in every free-text field (:func:`free_text_issues`).
* Before each mutation the tool copies the old file to ``<lib>.<YYYYMMDD_HHMMSS>.bak``
  beside the library, with one-second stamps that overwrite each other within an
  operation, and a multi-call operation leaves intermediate states in the file (e.g. only
  the STEP carriers) -> PartForge runs every operation on a working copy
  ``<stem>.pfwork<hex8><suffix>`` beside the library and replaces the library in one
  ``os.replace`` only after every call and check succeeded (all or nothing, crash-safe: the
  library is never half written); the old file goes to ``<workspace>/Backups/lib/``, the
  writer's ``.bak`` files of the copy are deleted. Operations on one library are serialised
  across threads **and processes** (:func:`library_lock`, a byte-range lock in the hidden
  ``.partforge-lock`` of the library folder).
* Read-back only names an embedded STEP model -> the read methods extract it to a
  resolvable file (:meth:`RustLibraryOps._materialize_steps`).
* A full PcbLib write stores the writer's header template (Mech 2-7 typed, only Mech 1-7,
  13, 15 enabled) -> after every PcbLib mutation the mechanical layers of the header are
  set to the workspace stack (:func:`partforge.altium.stackup.patch_pcblib_layers`,
  switch: ``stackup.HEADER_PATCH_ENABLED``).
* The writer has no footprint height: it stores ``HEIGHT=0mil`` for every footprint and
  every mutation (append, update, delete - also of another footprint) resets **all**
  components to 0 -> the heights are read before each PcbLib mutation and set afterwards
  (the call's footprints from their spec, all others as they were;
  :mod:`partforge.altium.heights`, switch: ``heights.HEIGHT_PATCH_ENABLED``).
* Every mutation re-serialises **all** components of the file: untouched components saved by Altium lose
  Mechanical 17-32 (moved to 16), TrueType strings, embedded fonts and custom pin fonts -> the working copy is
  snapshot before the call and the components the call did not write are set back byte for byte afterwards
  (:mod:`partforge.altium.preserve`, :meth:`RustLibraryOps._restore_untouched`).
* The writer keeps a single font (Times New Roman 10) and drops the font table of a file it rewrites ->
  after every SchLib mutation the table from before the write is restored and the written symbols get the
  house fonts of the workspace (:func:`partforge.altium.schstyle.patch_written_symbols`).
* Designator/Comment positions: ``designator_x/designator_y`` and the position of the
  ``Comment`` parameter (written whenever ``comment_pos`` is set, value ``*`` for generic
  symbols); the designator justification cannot be stored (always bottom left). Pin
  decorations: only the inner/outer edge with the seven safe values.

Colours are Win32 ``COLORREF``/``TColor`` integers (``0x00BBGGRR``) in every Altium
record, including the 3D body colour.
"""
from __future__ import annotations

import atexit
import contextlib
import copy
import ctypes
import filecmp
import hashlib
import json
import logging
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, TypeGuard, cast, get_args

from .. import __version__
from ..config import load_settings, local_data_dir, log_dir
from ..geometry.model import (
    Arc,
    Body3D,
    ElectricalType,
    FootprintLink,
    FootprintSpec,
    FpText,
    LineWidth,
    Pad,
    PinDecoration,
    PinOrientation,
    Point,
    Region,
    StepModel,
    SymArc,
    SymbolSpec,
    SymEllipse,
    SymLine,
    SymPin,
    SymPolygon,
    SymRect,
    SymText,
    TextJustify,
    TextPos,
    Track,
)
from ..workspace import (
    FootprintStyle,
    LayerMap,
    SymbolStyle,
    Workspace,
    current_or_none,
)
from . import compound, heights, pcbrecords, preserve, schrecords, schstyle, stackup
from . import layers as L
from .bridge.protocol import transliterate
from .models import ComponentInfo, WriteResult

log = logging.getLogger(__name__)

__all__ = [
    "RustWriterError",
    "RustWriterUnavailable",
    "RustValidationError",
    "RustToolError",
    "RustTimeoutError",
    "RustProcessError",
    "RustMcpClient",
    "RustLibraryOps",
    "get_client",
    "shutdown_client",
    "rust_writer_version",
    "temp_dir",
    "audit_log_path",
    "symbol_to_rust",
    "rust_to_symbol",
    "footprint_to_rust",
    "rust_to_footprint",
    "step_body",
    "fix_points",
    "update_symbol_payload",
    "stroke_text_anchor",
    "stroke_text_reference",
    "latin1_text",
    "validate_component_name",
    "validate_library_path",
    "validate_symbol_payload",
    "validate_footprint_payload",
    "free_text_issues",
    "step_source",
    "step_cache_dir",
    "hex_to_bgr",
    "bgr_to_hex",
    "relocate_backups",
    "writer_backups",
    "library_backups",
    "prune_backups",
    "store_backup",
    "is_inside",
    "library_lock",
    "library_kind",
    "LibraryLock",
    "LibraryLocked",
    "file_access_message",
    "work_copy_files",
]

# --------------------------------------------------------------------------- constants

COMPONENT_NAME_RE: Final = re.compile(r"^[A-Za-z0-9_.\-+() ]{1,64}$")
MAX_NAME_LENGTH: Final = 64
PREFIX_RE: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,9}$")
PCB_COORD_LIMIT_MM: Final = 5000.0
SCH_COORD_LIMIT_UNITS: Final = 100_000.0
MAX_PART_COUNT: Final = 64
MAX_PIN_LENGTH_UNITS: Final = 1000

PAD_SHAPE_TO_RUST: Final[dict[str, str]] = {
    "rect": "rectangle",
    "roundrect": "rounded_rectangle",
    "circle": "round",
    "oval": "oval",
    "octagon": "octagonal",
}
RUST_PAD_SHAPES: Final = frozenset({"rectangle", "rounded_rectangle", "round", "circle", "oval", "octagonal"})
HOLE_SHAPES: Final = frozenset({"round", "square", "slot"})
EXPANSION_MODES: Final = frozenset({"none", "from_rule", "manual"})
PAD_LAYERS: Final = frozenset({L.TOP_LAYER, L.BOTTOM_LAYER, L.MULTI_LAYER})
TEXT_JUSTIFICATIONS: Final = frozenset(get_args(TextJustify))
PIN_ORIENTATIONS: Final = frozenset({"left", "right", "up", "down"})
RUST_ELECTRICAL_TYPES: Final = frozenset(
    {"input", "output", "bidirectional", "passive", "power", "open_collector", "open_emitter", "hi_z", "tristate"}
)
ELECTRICAL_TO_RUST: Final[dict[str, str]] = {
    "input": "input",
    "output": "output",
    "io": "bidirectional",
    "passive": "passive",
    "power": "power",
    "open_collector": "open_collector",
    "open_emitter": "open_emitter",
    "hiz": "hi_z",
}
RUST_TO_ELECTRICAL: Final[dict[str, str]] = {
    "input": "input",
    "output": "output",
    "bidirectional": "io",
    "passive": "passive",
    "power": "power",
    "open_collector": "open_collector",
    "open_emitter": "open_emitter",
    "hi_z": "hiz",
    "tristate": "hiz",
}
#: Pin decorations whose stored ordinals are correct (altium-verify-rust.md §3.1).
SAFE_PIN_DECORATIONS: Final = frozenset(
    {
        "none",
        "dot",
        "clock",
        "active_low_input",
        "analog_signal_in",
        "not_logic_connection",
        "right_left_signal_flow",
    }
)
PIN_DECORATION_KEYS: Final = ("symbol_inner_edge", "symbol_outer_edge", "symbol_inside", "symbol_outside")
#: SymPin field -> Rust pin key of the decorations the PartForge model represents.
PIN_EDGE_KEYS: Final[dict[str, str]] = {"inner_edge": "symbol_inner_edge", "outer_edge": "symbol_outer_edge"}
#: ``TTextJustification`` ordinals (parameter ``justification`` of the Rust writer).
JUSTIFY_ORDINALS: Final[dict[str, int]] = {
    "bottom_left": 0,
    "bottom_center": 1,
    "bottom_right": 2,
    "middle_left": 3,
    "middle_center": 4,
    "middle_right": 5,
    "top_left": 6,
    "top_center": 7,
    "top_right": 8,
}
JUSTIFY_NAMES: Final[dict[int, str]] = {v: k for k, v in JUSTIFY_ORDINALS.items()}
#: Writer defaults of the designator / Comment text positions (mil), see ``SymbolSpec``.
DEFAULT_DESIGNATOR_POS: Final = (-50, 50)
DEFAULT_COMMENT_POS: Final = (-50, -150)
LINE_WIDTHS: Final[dict[str, int]] = {"smallest": 0, "small": 1, "medium": 2, "large": 3}
LINE_WIDTH_NAMES: Final[dict[int, str]] = {v: k for k, v in LINE_WIDTHS.items()}
DEFAULT_BODY_COLOR: Final = 0x808080
#: Character advance of Altium's default stroke font relative to the text height
#: (measured in Altium 26.10: 11 characters at 0.4/0.8 mm span 161/323 mil).
STROKE_CHAR_ADVANCE: Final = 0.92
#: ``primitive_order`` token -> symbol key (an unknown token discards the whole order).
PRIMITIVE_KEYS: Final[dict[str, str]] = {
    "pin": "pins",
    "rectangle": "rectangles",
    "round_rect": "round_rects",
    "line": "lines",
    "polyline": "polylines",
    "polygon": "polygons",
    "arc": "arcs",
    "elliptical_arc": "elliptical_arcs",
    "ellipse": "ellipses",
    "label": "labels",
    "parameter": "parameters",
    "pie": "pies",
    "bezier": "beziers",
    "text_frame": "text_frames",
    "image": "images",
    "text": "text",
}
STEP_CARRIER_PREFIX: Final = "__PFSTEP_"
#: Key under which the read methods attach the raw records (:class:`pcbrecords.FootprintRecords`) to a read-back
#: footprint dict – only for :func:`rust_to_footprint`, never sent to the writer.
_RECORDS_KEY: Final = "__pf_records"
#: Storages the reader lists as components although they are none (Altium writes them into some PcbLibs).
PSEUDO_COMPONENTS: Final = frozenset({"extendedprimitiveinformation", "uniqueidprimitiveinformation"})


def is_listed_component(name: str) -> bool:
    """A name of ``list_components``/``read_*`` that is a real component (no STEP carrier, no storage)."""
    return not name.startswith(STEP_CARRIER_PREFIX) and name.casefold() not in PSEUDO_COMPONENTS
#: From this many updated components on, an upsert deletes and re-appends them in two
#: calls instead of one ``update_component`` (= full library rewrite) per component.
BATCH_UPDATE_THRESHOLD: Final = 3
SCHLIB_EXT: Final = ".schlib"
PCBLIB_EXT: Final = ".pcblib"

#: Tools that never modify a file (safe to retry after a crash).
READ_ONLY_TOOLS: Final = frozenset(
    {
        "read_pcblib",
        "read_schlib",
        "get_component",
        "list_components",
        "component_exists",
        "validate_library",
        "extract_style",
        "render_footprint",
        "render_symbol",
        "list_backups",
        "export_library",
        "compare_components",
        "diff_libraries",
        "search_components",
    }
)

_SYMBOL_KEYS: Final = frozenset(
    {
        "name",
        "description",
        "designator_prefix",
        "component_type",
        "designator_x",
        "designator_y",
        "part_count",
        "current_part_id",
        "part_id_locked",
        "display_mode_count",
        "parameters",
        "footprints",
        "pins",
        "rectangles",
        "round_rects",
        "lines",
        "polylines",
        "polygons",
        "arcs",
        "ellipses",
        "elliptical_arcs",
        "pies",
        "beziers",
        "labels",
        "text",
        "text_frames",
        "images",
        "source_library_name",
        "target_file_name",
        "designator_unique_id",
        # read-back keys accepted on a replay
        "designator",
        "primitive_order",
    }
)
_FOOTPRINT_KEYS: Final = frozenset(
    {
        "name",
        "description",
        "pads",
        "tracks",
        "arcs",
        "regions",
        "text",
        "vias",
        "fills",
        "step_model",
        "model_3d",
        "component_bodies",
        "guid",
        "primitive_order",
    }
)
_ROUNDTRIP_KEYS: Final = frozenset(
    {
        "unique_id",
        "identity_guid",
        "identity_guid_b",
        "net_index",
        "polygon_index",
        "component_index",
        "raw_tail",
        "raw_block",
        "raw_geometry",
        "param_key_order",
        "flags",
        "keepout_restrictions",
        "additional_parameters",
        "sub_poly_index",
        "union_index",
        "is_shape_based",
        "arc_resolution",
        "cavity_height",
    }
)
_PAD_KEYS: Final = _ROUNDTRIP_KEYS | frozenset(
    {
        "designator",
        "x",
        "y",
        "width",
        "height",
        "shape",
        "corner_radius_percent",
        "rotation",
        "layer",
        "hole_size",
        "hole_shape",
        "hole_slot_length",
        "hole_rotation",
        "hole_positive_tolerance",
        "hole_negative_tolerance",
        "is_plated",
        "paste_mask_expansion",
        "paste_mask_expansion_mode",
        "solder_mask_expansion",
        "solder_mask_expansion_mode",
        "solder_mask_expansion_from_hole_edge",
        "stack_mode",
        "per_layer_sizes",
        "per_layer_shapes",
        "per_layer_offsets",
        "per_layer_corner_radii",
        "power_plane_connect_style",
        "power_plane_clearance",
        "power_plane_relief_expansion",
        "relief_air_gap",
        "relief_conductor_width",
        "relief_entries",
        "jumper_id",
    }
)

# --------------------------------------------------------------------------- errors


class RustWriterError(RuntimeError):
    """Base class of all Rust-writer errors; ``str(exc)`` is a German UI message."""


class RustWriterUnavailable(RustWriterError):
    """The executable is missing or cannot be started."""


class RustValidationError(RustWriterError):
    """Client-side validation failed; nothing was sent to the writer."""

    def __init__(self, issues: Sequence[str]):
        self.issues = [str(i) for i in issues] or ["Unbekannter Validierungsfehler."]
        shown = self.issues[:25]
        text = "Ungültige Daten für die Bibliothek – es wurde nichts geschrieben:\n" + "\n".join(
            f"• {issue}" for issue in shown
        )
        if len(self.issues) > len(shown):
            text += f"\n• … und {len(self.issues) - len(shown)} weitere Probleme"
        super().__init__(text)


_ERROR_HINTS: Final[tuple[tuple[str, str], ...]] = (
    ("access denied", "Zugriff verweigert: Der Pfad liegt außerhalb der für den Bibliotheks-Writer freigegebenen Ordner."),
    ("already exists", "Das Bauteil existiert bereits in der Bibliothek."),
    (
        "failed to write file",
        "Die Bibliotheksdatei konnte nicht geschrieben werden (in Altium geöffnet oder schreibgeschützt?).",
    ),
    ("failed to read", "Die Bibliotheksdatei konnte nicht gelesen werden."),
    ("invalid ole structure", "Die Datei ist keine gültige Altium-Bibliothek."),
    ("rate limit exceeded", "Zu viele Schreibzugriffe in kurzer Zeit."),
    ("not found in library", "Das Bauteil wurde in der Bibliothek nicht gefunden."),
    ("does not exist or is inaccessible", "Der Zielordner der Bibliothek existiert nicht."),
    ("step file not found", "Die STEP-Datei wurde nicht gefunden."),
)


class RustToolError(RustWriterError):
    """The tool ran but reported ``isError`` (or ``status: error``)."""

    def __init__(self, tool: str, raw: str, details: Mapping[str, Any] | None = None):
        self.tool = tool
        self.raw = raw
        self.details = dict(details) if details else None
        message = raw
        if self.details:
            error = self.details.get("error") or self.details.get("message")
            extra = self.details.get("details")
            if isinstance(error, str) and error:
                message = error + (f" ({extra})" if isinstance(extra, str) and extra else "")
        self.message = message.strip() or "unbekannter Fehler"
        lower = self.message.lower()
        hint = next((text for key, text in _ERROR_HINTS if key in lower), "Der Bibliotheks-Writer meldet einen Fehler.")
        super().__init__(f"{hint} [{tool}: {self.message}]")

    @property
    def not_found(self) -> bool:
        return "not found" in self.message.lower()

    @property
    def rate_limited(self) -> bool:
        return "rate limit" in self.message.lower()


class RustTimeoutError(RustWriterError):
    """No answer within the request timeout (the process is killed and restarted)."""


class RustProcessError(RustWriterError):
    """The writer process crashed or violated the protocol."""


class _VerificationFailed(RustWriterError):
    """Internal: the check after writing found problems -> the operation is rolled back."""

    def __init__(self, errors: Mapping[str, str]):
        self.errors = dict(errors)
        super().__init__("; ".join(f"{name}: {message}" for name, message in list(self.errors.items())[:5]))


class _ProcessDied(Exception):
    def __init__(self, delivered: bool):
        super().__init__("process died")
        self.delivered = delivered


# --------------------------------------------------------------------------- paths


#: The writer's audit log is rotated (one older generation kept) when it grows beyond this at a writer start.
AUDIT_LOG_MAX_BYTES: Final = 5 * 1024 * 1024


def temp_dir() -> Path:
    """PartForge temp directory (inside the writer sandbox; local folder of this PC, never roaming)."""
    path = local_data_dir() / "tmp"
    path.mkdir(parents=True, exist_ok=True)
    return path


def audit_log_path() -> Path:
    """Audit log of the writer (JSON lines, appended by the writer; rotated at :data:`AUDIT_LOG_MAX_BYTES`)."""
    path = log_dir() / "rustwriter-audit.jsonl"
    try:
        if path.stat().st_size > AUDIT_LOG_MAX_BYTES:
            os.replace(path, path.with_name("rustwriter-audit.1.jsonl"))
    except OSError:
        pass  # missing (fine) or in use by another PartForge process: rotated at a later start
    return path


def _runtime_dir() -> Path:
    path = local_data_dir() / "rustwriter"
    path.mkdir(parents=True, exist_ok=True)
    return path


_CONFIG_NAME_RE: Final = re.compile(r"^config-(\d+)-[0-9a-f]+\.(?:json|tmp)$")


def _process_alive(pid: int) -> bool:
    """Whether a process with this id runs (``OpenProcess`` – never ``os.kill``, which terminates on Windows)."""
    if pid == os.getpid():
        return True
    if os.name != "nt":  # pragma: no cover
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = ctypes.c_ulong()
        if not k32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
            return True
        return code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(ctypes.c_void_p(handle))


def _prune_stale_configs(folder: Path) -> None:
    """Remove the generated configurations of processes that are gone (e.g. killed – they never cleaned up)."""
    for entry in folder.iterdir() if folder.is_dir() else []:
        match = _CONFIG_NAME_RE.match(entry.name)
        if match is None:
            continue
        with contextlib.suppress(OSError, ValueError):
            if not _process_alive(int(match.group(1))):
                entry.unlink()


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def is_inside(path: str | os.PathLike[str], directory: str | os.PathLike[str]) -> bool:
    """True if ``path`` equals or lies below ``directory`` (case-insensitive on Windows)."""
    p, d = _norm(path), _norm(directory)
    if p == d:
        return True
    try:
        return os.path.commonpath([p, d]) == d
    except ValueError:  # different drives
        return False


def _posix(path: str | os.PathLike[str]) -> str:
    return Path(os.path.abspath(os.fspath(path))).as_posix()


# --------------------------------------------------------------------------- result parsing


def _try_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def parse_tool_result(tool: str, result: Any) -> dict[str, Any]:
    """Defensively unpack an MCP ``CallToolResult`` into a dict (raises on errors)."""
    if not isinstance(result, dict):
        raise RustProcessError(f"Unerwartete Antwort des Bibliotheks-Writers auf {tool}: {type(result).__name__}")
    content = result.get("content")
    texts: list[str] = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                texts.append(item["text"])
    text = "\n".join(texts).strip()
    parsed = _try_json(text) if text else None
    if result.get("isError"):
        raise RustToolError(tool, text, parsed if isinstance(parsed, dict) else None)
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        parsed = structured
    if isinstance(parsed, dict):
        if parsed.get("status") == "error":
            raise RustToolError(tool, text, parsed)
        return parsed
    if parsed is None:
        return {"text": text}
    return {"data": parsed}


# --------------------------------------------------------------------------- client


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None
    closed: bool = False


class RustMcpClient:
    """Long-lived ``altium-designer-mcp.exe`` process speaking JSON-RPC 2.0 over stdio.

    Thread-safe: calls are serialised by a lock (the server is sequential anyway). The
    process is started lazily, restarted after a crash or timeout, and gets a freshly
    generated configuration whenever the allowed directories change.
    """

    PROTOCOL_VERSION: Final = "2024-11-05"

    def __init__(
        self,
        exe: str | os.PathLike[str],
        *,
        allowed_dirs: Iterable[str | os.PathLike[str]] = (),
        request_timeout: float = 120.0,
        startup_timeout: float = 15.0,
        extra_args: Sequence[str] = (),
        runtime_dir: Path | None = None,
        audit_log: Path | None = None,
        max_rate_limit_retries: int = 3,
    ):
        self.exe = os.fspath(exe)
        self._extra_args = [str(a) for a in extra_args]
        self._request_timeout = float(request_timeout)
        self._startup_timeout = float(startup_timeout)
        self._runtime_dir = runtime_dir
        self._audit_log = audit_log
        self._max_rate_retries = max(0, int(max_rate_limit_retries))
        self._allowed: list[Path] = self._normalize_dirs(allowed_dirs)
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, _Pending] = {}
        self._next_id = 1
        self._proc: subprocess.Popen[bytes] | None = None
        self._config_file: Path | None = None
        self._server_info: dict[str, Any] | None = None
        self._stderr_tail: deque[str] = deque(maxlen=200)
        self.restarts = 0

    # -- configuration --------------------------------------------------------------
    @staticmethod
    def _normalize_dirs(dirs: Iterable[str | os.PathLike[str]]) -> list[Path]:
        out: list[Path] = []
        seen: set[str] = set()
        for d in dirs:
            path = Path(os.path.abspath(os.fspath(d)))
            key = _norm(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
        return out

    @property
    def allowed_dirs(self) -> tuple[Path, ...]:
        return tuple(self._allowed)

    def covers(self, path: str | os.PathLike[str]) -> bool:
        return any(is_inside(path, d) for d in self._allowed)

    def ensure_allowed(self, dirs: Iterable[str | os.PathLike[str]], *, exact: bool = False) -> None:
        """Make sure ``dirs`` are inside the sandbox (restarts the process if needed).

        With ``exact`` the sandbox becomes exactly ``dirs`` (used when the workspace changes).
        """
        wanted = self._normalize_dirs(dirs)
        with self._lock:
            if exact:
                if {_norm(p) for p in wanted} == {_norm(p) for p in self._allowed}:
                    return
                new = wanted
            else:
                missing = [d for d in wanted if not self.covers(d)]
                if not missing:
                    return
                new = self._allowed + missing
            log.info("Bibliotheks-Writer: Sandbox-Ordner geändert -> %s", ", ".join(map(str, new)))
            self._allowed = new
            if self._proc is not None:
                self._kill(force=False)

    # -- lifecycle ------------------------------------------------------------------
    @property
    def running(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    @property
    def server_info(self) -> dict[str, Any] | None:
        return self._server_info

    @property
    def server_version(self) -> str | None:
        info = self._server_info or {}
        server = info.get("serverInfo") if isinstance(info, dict) else None
        version = server.get("version") if isinstance(server, dict) else None
        return version if isinstance(version, str) else None

    @property
    def stderr_tail(self) -> list[str]:
        return list(self._stderr_tail)

    def start(self) -> None:
        with self._lock:
            if not self.running:
                self._spawn()

    def close(self) -> None:
        with self._lock:
            self._kill(force=False)

    def __enter__(self) -> RustMcpClient:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _write_config(self) -> Path:
        runtime = self._runtime_dir or _runtime_dir()
        runtime.mkdir(parents=True, exist_ok=True)
        _prune_stale_configs(runtime)
        audit = self._audit_log or audit_log_path()
        audit.parent.mkdir(parents=True, exist_ok=True)
        allowed = [p for p in self._allowed if p.is_dir()]
        for p in self._allowed:
            if not p.is_dir():
                log.debug("Bibliotheks-Writer: Sandbox-Ordner existiert nicht und wird ausgelassen: %s", p)
        if not allowed:  # never hand the writer an empty sandbox list
            allowed = [temp_dir()]
        config = {
            "allowed_paths": [p.as_posix() for p in allowed],
            "logging": {"level": "warn", "audit_log_path": audit.as_posix()},
            "rate_limit": {"max_burst": 1000, "refill_per_sec": 200.0},
        }
        path = runtime / f"config-{os.getpid()}-{id(self):x}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def _spawn(self) -> None:
        self._config_file = self._write_config()
        args = [self.exe, *self._extra_args, str(self._config_file)]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                cwd=str(self._config_file.parent),
            )
        except OSError as exc:
            raise RustWriterUnavailable(f"Der Bibliotheks-Writer konnte nicht gestartet werden ({self.exe}): {exc}") from exc
        self._proc = proc
        threading.Thread(target=self._read_stdout, args=(proc,), name="rustwriter-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,), name="rustwriter-stderr", daemon=True).start()
        try:
            info = self._request(
                "initialize",
                {
                    "protocolVersion": self.PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "PartForge", "version": __version__},
                },
                self._startup_timeout,
            )
            self._notify("notifications/initialized")
        except (_ProcessDied, RustWriterError) as exc:
            self._kill(force=True)
            tail = " | ".join(list(self._stderr_tail)[-3:])
            raise RustWriterUnavailable(
                f"Der Bibliotheks-Writer startet nicht korrekt ({self.exe}). {tail}".strip()
            ) from exc
        self._server_info = info
        log.info(
            "Bibliotheks-Writer gestartet (pid %s, Version %s, Sandbox: %s)",
            proc.pid,
            self.server_version,
            ", ".join(p.as_posix() for p in self._allowed),
        )

    def _kill(self, *, force: bool) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if force:
                proc.kill()
            elif proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=0.5 if force else 5)
        except subprocess.TimeoutExpired:
            proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            with contextlib.suppress(OSError, ValueError):
                if stream:
                    stream.close()
        if self._config_file is not None:
            with contextlib.suppress(OSError):
                self._config_file.unlink()
            self._config_file = None

    # -- I/O threads ----------------------------------------------------------------
    def _read_stdout(self, proc: subprocess.Popen[bytes]) -> None:
        stream = proc.stdout
        try:
            if stream is not None:
                for raw in stream:
                    line = raw.strip()
                    if not line:
                        continue
                    msg = _try_json(line.decode("utf-8", errors="replace"))
                    if not isinstance(msg, dict):
                        log.debug("Bibliotheks-Writer: Nicht-JSON auf stdout: %r", line[:200])
                        continue
                    if "method" in msg:
                        if "id" in msg:  # server -> client request
                            reply: dict[str, Any] = {"jsonrpc": "2.0", "id": msg["id"]}
                            if msg.get("method") == "ping":
                                reply["result"] = {}
                            else:
                                reply["error"] = {"code": -32601, "message": "Method not found"}
                            with contextlib.suppress(OSError, ValueError):
                                self._send_to(proc, reply)
                        continue
                    rid = msg.get("id")
                    with self._pending_lock:
                        pending = self._pending.pop(rid, None) if isinstance(rid, int) else None
                    if pending is not None:
                        pending.response = msg
                        pending.event.set()
        except (OSError, ValueError):
            pass
        finally:
            with self._pending_lock:
                waiters = list(self._pending.values())
                self._pending.clear()
            for waiter in waiters:
                waiter.closed = True
                waiter.event.set()

    def _read_stderr(self, proc: subprocess.Popen[bytes]) -> None:
        stream = proc.stderr
        try:
            if stream is not None:
                for raw in stream:
                    text = raw.decode("utf-8", errors="replace").rstrip()
                    if text:
                        self._stderr_tail.append(text)
                        log.debug("Bibliotheks-Writer stderr: %s", text)
        except (OSError, ValueError):
            pass

    def _send_to(self, proc: subprocess.Popen[bytes], message: Mapping[str, Any]) -> None:
        data = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        stdin = proc.stdin
        if stdin is None:
            raise OSError("stdin closed")
        with self._write_lock:
            stdin.write(data)
            stdin.flush()

    def _notify(self, method: str, params: Mapping[str, Any] | None = None) -> None:
        proc = self._proc
        if proc is None:
            raise _ProcessDied(delivered=False)
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = dict(params)
        try:
            self._send_to(proc, message)
        except (OSError, ValueError) as exc:
            raise _ProcessDied(delivered=False) from exc

    def _request(self, method: str, params: Mapping[str, Any], timeout: float) -> dict[str, Any]:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            raise _ProcessDied(delivered=False)
        rid = self._next_id
        self._next_id += 1
        pending = _Pending()
        with self._pending_lock:
            self._pending[rid] = pending
        try:
            self._send_to(proc, {"jsonrpc": "2.0", "id": rid, "method": method, "params": dict(params)})
        except (OSError, ValueError) as exc:
            with self._pending_lock:
                self._pending.pop(rid, None)
            raise _ProcessDied(delivered=False) from exc
        if not pending.event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(rid, None)
            log.error("Bibliotheks-Writer: keine Antwort auf %s nach %.0f s – Prozess wird beendet", method, timeout)
            self._kill(force=True)
            raise RustTimeoutError(
                f"Der Bibliotheks-Writer hat nicht innerhalb von {timeout:.0f} s geantwortet ({method}). "
                "Der Prozess wurde beendet und wird beim nächsten Aufruf neu gestartet."
            )
        response = pending.response
        if pending.closed or response is None:
            raise _ProcessDied(delivered=True)
        if "error" in response:
            error = response.get("error") or {}
            text = error.get("message") if isinstance(error, dict) else str(error)
            raise RustProcessError(f"Protokollfehler des Bibliotheks-Writers bei {method}: {text}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RustProcessError(f"Ungültige Antwort des Bibliotheks-Writers bei {method}.")
        return result

    # -- public calls ---------------------------------------------------------------
    def call_tool(self, name: str, arguments: Mapping[str, Any], *, timeout: float | None = None) -> dict[str, Any]:
        """Call one tool and return its parsed JSON payload.

        Raises :class:`RustToolError` when the tool reports an error. Read-only tools are
        retried once after a crash; a rejected request (rate limit, undelivered) is
        retried for every tool.
        """
        crash_retries = 0
        rate_retries = 0
        while True:
            with self._lock:
                if not self.running:
                    if self._proc is not None:
                        self._kill(force=True)
                    if self._server_info is not None:
                        self.restarts += 1
                    self._spawn()
                started = time.perf_counter()
                try:
                    raw = self._request(
                        "tools/call",
                        {"name": name, "arguments": dict(arguments)},
                        timeout if timeout is not None else self._request_timeout,
                    )
                except _ProcessDied as exc:
                    self._kill(force=True)
                    retry = (not exc.delivered or name in READ_ONLY_TOOLS) and crash_retries < 1
                    tail = " | ".join(list(self._stderr_tail)[-3:])
                    if retry:
                        crash_retries += 1
                        log.warning("Bibliotheks-Writer abgestürzt bei %s – Neustart und Wiederholung. %s", name, tail)
                        continue
                    raise RustProcessError(
                        f"Der Bibliotheks-Writer wurde während '{name}' unerwartet beendet. {tail}".strip()
                    ) from exc
                log.debug("Bibliotheks-Writer %s: %.0f ms", name, (time.perf_counter() - started) * 1000)
            try:
                return parse_tool_result(name, raw)
            except RustToolError as exc:
                if exc.rate_limited and rate_retries < self._max_rate_retries:
                    rate_retries += 1
                    time.sleep(0.5 * rate_retries)
                    continue
                raise

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.running:
                self._spawn()
            tools: list[dict[str, Any]] = []
            cursor: str | None = None
            while True:
                result = self._request("tools/list", {"cursor": cursor} if cursor else {}, self._request_timeout)
                batch = result.get("tools")
                if isinstance(batch, list):
                    tools.extend(t for t in batch if isinstance(t, dict))
                cursor = result.get("nextCursor") if isinstance(result.get("nextCursor"), str) else None
                if not cursor:
                    return tools


# --------------------------------------------------------------------------- default client

_default_lock = threading.Lock()
_default_client: RustMcpClient | None = None
_atexit_registered = False
#: ``Library/Data`` of an empty PcbLib per writer executable (:meth:`RustLibraryOps.template_library_data`).
_template_headers: dict[str, bytes] = {}
_template_lock = threading.Lock()
_version_cache: dict[tuple[str, int], str | None] = {}


def default_allowed_dirs(extra_dirs: Iterable[str | os.PathLike[str]] = ()) -> list[Path]:
    """Sandbox for the shared client: open workspace root + temp dir + extra dirs."""
    dirs: list[Path] = []
    ws = current_or_none()
    if ws is not None:
        dirs.append(ws.root)
    dirs.append(temp_dir())
    dirs.extend(Path(os.path.abspath(os.fspath(d))) for d in extra_dirs)
    return dirs


def resolve_exe(exe: str | os.PathLike[str] | None = None) -> str | None:
    if exe:
        return os.fspath(exe) if Path(exe).is_file() else None
    return load_settings().resolved_rust_writer()


def get_client(
    *,
    exe: str | os.PathLike[str] | None = None,
    extra_dirs: Iterable[str | os.PathLike[str]] = (),
    allowed_dirs: Iterable[str | os.PathLike[str]] | None = None,
) -> RustMcpClient:
    """The process-wide writer client (created lazily, sandbox kept up to date).

    The sandbox becomes exactly ``allowed_dirs`` if given, else the open workspace root +
    :func:`temp_dir` + ``extra_dirs`` (the process restarts only when it changes).
    """
    global _default_client, _atexit_registered
    path = resolve_exe(exe)
    if not path:
        raise RustWriterUnavailable(
            "Der Bibliotheks-Writer wurde nicht gefunden. Bitte den Pfad unter Einstellungen › Allgemein › Altium "
            "Designer › Bibliotheks-Writer eintragen."
        )
    wanted = list(allowed_dirs) if allowed_dirs is not None else default_allowed_dirs(extra_dirs)
    with _default_lock:
        client = _default_client
        if client is None or _norm(client.exe) != _norm(path):
            if client is not None:
                client.close()
            client = RustMcpClient(path, allowed_dirs=wanted)
            _default_client = client
            if not _atexit_registered:
                atexit.register(shutdown_client)
                _atexit_registered = True
        else:
            client.ensure_allowed(wanted, exact=True)
    return client


def shutdown_client() -> None:
    """Stop the shared writer process (registered with ``atexit``)."""
    global _default_client
    with _default_lock:
        client, _default_client = _default_client, None
    if client is not None:
        with contextlib.suppress(Exception):
            client.close()


def rust_writer_version(exe: str | os.PathLike[str]) -> str | None:
    """Version of the executable (``--version``), cached per path and modification time."""
    path = Path(exe)
    try:
        key = (_norm(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    if key in _version_cache:
        return _version_cache[key]
    version: str | None = None
    try:
        proc = subprocess.run(
            [str(path), "--version"],
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
        text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
        m = re.search(r"(\d+\.\d+\.\d+\S*)", text)
        version = m.group(1) if m else (text or None)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Version des Bibliotheks-Writers nicht ermittelbar: %s", exc)
    _version_cache[key] = version
    return version


# --------------------------------------------------------------------------- numbers / colours


def _r(value: float, digits: int = 6) -> float:
    out = round(float(value), digits)
    return 0.0 if out == 0 else out


def _mu(mil: float) -> float:
    """mil -> schematic units (10 mil)."""
    return _r(float(mil) / 10.0, 5)


def _um(units: Any) -> float:
    """schematic units -> mil."""
    return _r(_num(units) * 10.0, 4)


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            parsed = float(value)
            if math.isfinite(parsed):
                return parsed
    return default


def _is_num(value: object) -> TypeGuard[float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


_HEX_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def hex_to_bgr(color: str) -> int:
    """``#RRGGBB`` -> Altium COLORREF integer ``0x00BBGGRR``."""
    m = _HEX_RE.match(color.strip()) if isinstance(color, str) else None
    if not m:
        raise ValueError(f"Ungültige Farbe {color!r} (erwartet #RRGGBB).")
    value = int(m.group(1), 16)
    r, g, b = (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF
    return (b << 16) | (g << 8) | r


def bgr_to_hex(value: Any) -> str:
    """Altium COLORREF integer -> ``#RRGGBB``."""
    number = int(_num(value)) & 0xFFFFFF
    r, g, b = number & 0xFF, (number >> 8) & 0xFF, (number >> 16) & 0xFF
    return f"#{r:02X}{g:02X}{b:02X}"


def _points(raw: Any) -> list[Point]:
    """Point list in either read format (``[[x, y]]``) or write format (``[{x, y}]``)."""
    out: list[Point] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            out.append(Point(x=_num(item.get("x")), y=_num(item.get("y"))))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append(Point(x=_num(item[0]), y=_num(item[1])))
    return out


def _pt(x: float, y: float, digits: int = 6) -> dict[str, float]:
    return {"x": _r(x, digits), "y": _r(y, digits)}


def _orientation(value: Any) -> PinOrientation:
    return cast(PinOrientation, value) if value in PIN_ORIENTATIONS else "right"


def _electrical(value: Any) -> ElectricalType:
    return cast(ElectricalType, RUST_TO_ELECTRICAL.get(str(value or "passive"), "passive"))


def _justify(value: Any) -> TextJustify:
    return cast(TextJustify, value) if value in TEXT_JUSTIFICATIONS else "bottom_left"


def latin1_text(text: str) -> str:
    """Text for PcbLib strings, which the writer stores as Latin-1 (``Ω`` -> ``Ohm``)."""
    if all(ord(ch) <= 0xFF for ch in text):
        return text
    return "".join(ch if ord(ch) <= 0xFF else transliterate(ch) for ch in text)


def _justify_offset(text: str, height: float, rotation: float, justify: str) -> tuple[float, float]:
    """Vector from the justification reference point to the bottom-left text anchor."""
    vertical, _, horizontal = justify.partition("_")
    fx = {"left": 0.0, "center": 0.5, "right": 1.0}.get(horizontal, 0.0)
    fy = {"bottom": 0.0, "middle": 0.5, "top": 1.0}.get(vertical, 0.0)
    dx = -fx * len(text) * STROKE_CHAR_ADVANCE * height
    dy = -fy * height
    angle = math.radians(rotation)
    return dx * math.cos(angle) - dy * math.sin(angle), dx * math.sin(angle) + dy * math.cos(angle)


def stroke_text_anchor(text: str, x: float, y: float, height: float, rotation: float, justify: str) -> tuple[float, float]:
    """Bottom-left location that makes single-line stroke text appear ``justify``-aligned at (x, y).

    Altium anchors stroke text bottom-left and ignores the stored justification
    (VERIFIED, altium-verify-2 §3.3); the width is estimated with
    :data:`STROKE_CHAR_ADVANCE` from the literal text (special strings such as
    ``.Designator`` are centred on their literal, like Altium's footprint wizard does).
    """
    dx, dy = _justify_offset(text, height, rotation, justify)
    return x + dx, y + dy


def stroke_text_reference(text: str, x: float, y: float, height: float, rotation: float, justify: str) -> tuple[float, float]:
    """Inverse of :func:`stroke_text_anchor` (justification point from the stored location)."""
    dx, dy = _justify_offset(text, height, rotation, justify)
    return x - dx, y - dy


#: TrueType text: Altium's text height is the font's cell (ascent + descent; Arial 1.117 em), the stored
#: location is the lower left corner of the drawn text (VERIFIED on Altium 26.10 files: ".Designator" in Arial
#: 0.8 mm = box 3.585 × 0.659 mm, ".Comment" 3.213 × 0.527 mm).
TRUETYPE_CELL_EM: Final = 1.117
TRUETYPE_DEFAULT_FONT: Final = "Arial"
_DESCENDERS: Final = frozenset("gjpqy(),;_[]{}|")


def truetype_text_box(text: str, height: float, font: str | None = None) -> tuple[float, float]:
    """Estimated extent (width, height in mm) of a single-line TrueType text as Altium draws it."""
    from ..symbols.text import advance_em

    em = height / TRUETYPE_CELL_EM
    width = advance_em(text, font or TRUETYPE_DEFAULT_FONT) * em * 0.98
    tall = 0.718 + (0.21 if any(ch in _DESCENDERS for ch in text) else 0.0)
    return width, tall * em


def _truetype_offset(box: tuple[float, float], rotation: float, justify: str) -> tuple[float, float]:
    vertical, _, horizontal = justify.partition("_")
    fx = {"left": 0.0, "center": 0.5, "right": 1.0}.get(horizontal, 0.0)
    fy = {"bottom": 0.0, "middle": 0.5, "top": 1.0}.get(vertical, 0.0)
    dx, dy = -fx * box[0], -fy * box[1]
    angle = math.radians(rotation)
    return dx * math.cos(angle) - dy * math.sin(angle), dx * math.sin(angle) + dy * math.cos(angle)


def _plausible_box(stored: tuple[float, float], estimate: tuple[float, float]) -> bool:
    """A stored text extent that agrees with the estimate within 30 % (Altium measured it)."""
    return all(e > 0 and 0.7 <= v / e <= 1.3 for v, e in zip(stored, estimate, strict=True))


def truetype_text_anchor(box: tuple[float, float], x: float, y: float, rotation: float, justify: str) -> tuple[float, float]:
    """Lower left location that shows a TrueType text of extent ``box`` ``justify``-aligned at (x, y)."""
    dx, dy = _truetype_offset(box, rotation, justify)
    return x + dx, y + dy


def truetype_text_reference(box: tuple[float, float], x: float, y: float, rotation: float, justify: str
                            ) -> tuple[float, float]:
    """Inverse of :func:`truetype_text_anchor`."""
    dx, dy = _truetype_offset(box, rotation, justify)
    return x - dx, y - dy


# --------------------------------------------------------------------------- validation


class _Issues:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, message: str) -> None:
        self.items.append(message)

    def extend(self, messages: Iterable[str]) -> None:
        self.items.extend(messages)

    def __bool__(self) -> bool:
        return bool(self.items)

    def raise_if_any(self) -> None:
        if self.items:
            raise RustValidationError(self.items)


def validate_component_name(name: object, what: str = "Bauteil") -> list[str]:
    """Issues for a symbol/footprint name (ASCII ``[A-Za-z0-9_.\\-+() ]``, max. 64 chars)."""
    if not isinstance(name, str) or not name:
        return [f"{what}: Name fehlt."]
    issues: list[str] = []
    if len(name) > MAX_NAME_LENGTH:
        issues.append(f"{what} {name!r}: Name ist länger als {MAX_NAME_LENGTH} Zeichen.")
    if not COMPONENT_NAME_RE.match(name[:MAX_NAME_LENGTH]):
        bad = sorted({c for c in name if not re.match(r"[A-Za-z0-9_.\-+() ]", c)})
        issues.append(
            f"{what} {name!r}: unzulässige Zeichen {' '.join(repr(c) for c in bad)} – erlaubt sind "
            "A–Z, a–z, 0–9, Leerzeichen und _ . - + ( )."
        )
    if name != name.strip():
        issues.append(f"{what} {name!r}: Name darf nicht mit Leerzeichen beginnen oder enden.")
    if name.startswith(STEP_CARRIER_PREFIX):
        issues.append(f"{what} {name!r}: Das Präfix {STEP_CARRIER_PREFIX} ist für PartForge reserviert.")
    return issues


_CONTROL_CHAR_RE: Final = re.compile(r"[\x00-\x1f\x7f]")


def _shown(text: str, limit: int = 40) -> str:
    """Short, escaped rendering of a user text for error messages."""
    return repr(text if len(text) <= limit else text[: limit - 1] + "…")


def free_text_issues(value: object, where: str, label: str) -> list[str]:
    """Issues for a free-text field that ends up inside an Altium library record.

    Altium stores descriptions, comments, parameters, labels and model links as
    ``|KEY=value|`` records without any escaping: a ``|`` cuts the text off or injects
    record keys (a footprint description ``x|PATTERN=EVIL`` renamed the footprint, a
    symbol description injected ``CompCount``/``LibRef`` keys into the FileHeader), and
    control characters break or drop records (VERIFIED with the Rust writer). Both are
    rejected for every free-text field, independent of the backend.
    """
    if not isinstance(value, str) or not value:
        return []
    issues: list[str] = []
    if "|" in value:
        issues.append(
            f"{where}: {label} {_shown(value)} enthält das Zeichen '|'. Es trennt in Altium-Bibliotheken die "
            "Datenfelder (der Text würde abgeschnitten oder verfälscht) – bitte entfernen oder z. B. durch '/' ersetzen."
        )
    if _CONTROL_CHAR_RE.search(value):
        issues.append(
            f"{where}: {label} {_shown(value)} enthält Steuerzeichen (Zeilenumbruch, Tabulator o. Ä.) – erlaubt ist "
            "nur einzeiliger Text."
        )
    return issues


def library_kind(path: str | os.PathLike[str]) -> Literal["schlib", "pcblib"]:
    suffix = Path(path).suffix.lower()
    if suffix == SCHLIB_EXT:
        return "schlib"
    if suffix == PCBLIB_EXT:
        return "pcblib"
    raise RustValidationError([f"Unbekannter Bibliothekstyp: {Path(path).name} (erwartet .SchLib oder .PcbLib)."])


def validate_library_path(
    path: str | os.PathLike[str],
    kind: Literal["schlib", "pcblib"],
    *,
    allowed_dirs: Sequence[str | os.PathLike[str]] | None = None,
) -> Path:
    """Absolute, correctly typed library path inside the sandbox (raises on violations)."""
    issues = _Issues()
    raw = Path(path)
    expected = SCHLIB_EXT if kind == "schlib" else PCBLIB_EXT
    label = "Symbol" if kind == "schlib" else "Footprint"
    if not raw.is_absolute():
        issues.add(f"Der Bibliothekspfad muss absolut sein: {path}")
    if raw.suffix.lower() != expected:
        issues.add(
            f"Falsche Dateiendung für eine {label}-Bibliothek: {raw.name} "
            f"(erwartet {'.SchLib' if kind == 'schlib' else '.PcbLib'})."
        )
    if allowed_dirs is not None and raw.is_absolute() and not any(is_inside(raw, d) for d in allowed_dirs):
        issues.add(
            f"Die Bibliothek {raw} liegt außerhalb der freigegebenen Ordner "
            "(Bibliotheksordner und PartForge-Temp). Bitte den Bibliotheksordner öffnen oder die Datei dorthin kopieren."
        )
    issues.raise_if_any()
    return Path(os.path.abspath(raw))


def _check_coord(issues: _Issues, where: str, key: str, value: object, limit: float) -> None:
    if not _is_num(value):
        issues.add(f"{where}: '{key}' muss eine Zahl sein (ist {value!r}).")
    elif abs(float(value)) > limit:  # type: ignore[arg-type]
        issues.add(f"{where}: '{key}' = {value} liegt außerhalb von ±{limit:g}.")


def _check_keys(issues: _Issues, where: str, data: Mapping[str, Any], allowed: frozenset[str]) -> None:
    unknown = sorted(k for k in data if k not in allowed)
    if unknown:
        issues.add(f"{where}: unbekannte Felder {', '.join(unknown)} (würden vom Bibliotheks-Writer ignoriert).")


def _check_point_list(issues: _Issues, where: str, points: object, minimum: int, limit: float) -> None:
    if not isinstance(points, list) or len(points) < minimum:
        issues.add(f"{where}: mindestens {minimum} Punkte erforderlich.")
        return
    for i, point in enumerate(points):
        if not isinstance(point, dict):
            issues.add(f"{where}: Punkt {i + 1} muss als {{x, y}} übergeben werden.")
            continue
        _check_coord(issues, where, f"x[{i + 1}]", point.get("x"), limit)
        _check_coord(issues, where, f"y[{i + 1}]", point.get("y"), limit)


def validate_symbol_payload(symbol: Mapping[str, Any]) -> list[str]:
    """Strict check of a ``write_schlib``/``update_component`` symbol (returns German issues)."""
    issues = _Issues()
    name = symbol.get("name")
    where = f"Symbol {name!r}"
    issues.extend(validate_component_name(name, "Symbol"))
    _check_keys(issues, where, symbol, _SYMBOL_KEYS)
    if symbol.get("text"):
        issues.add(f"{where}: Freitext muss als 'labels' übergeben werden ('text' wird als falscher Datensatz geschrieben).")
    prefix = symbol.get("designator_prefix")
    if prefix is not None and (not isinstance(prefix, str) or not PREFIX_RE.match(prefix)):
        issues.add(f"{where}: ungültiges Bezeichner-Präfix {prefix!r} (1–10 Zeichen, beginnt mit einem Buchstaben).")
    part_count = symbol.get("part_count", 1)
    if not _is_int(part_count) or not 1 <= part_count <= MAX_PART_COUNT:
        issues.add(f"{where}: Teileanzahl {part_count!r} ungültig (1–{MAX_PART_COUNT}).")
        part_count = MAX_PART_COUNT
    if not isinstance(symbol.get("description", ""), str):
        issues.add(f"{where}: Beschreibung muss Text sein.")
    issues.extend(free_text_issues(symbol.get("description"), where, "Beschreibung"))
    issues.extend(free_text_issues(symbol.get("designator"), where, "Bezeichner"))
    for key in ("designator_x", "designator_y"):
        if key in symbol:
            _check_coord(issues, where, key, symbol[key], SCH_COORD_LIMIT_UNITS)

    def check_part(w: str, value: object, allow_all: bool = True) -> None:
        low = 0 if allow_all else 1
        if not _is_int(value) or not low <= value <= part_count:  # type: ignore[operator]
            issues.add(f"{w}: Teil {value!r} existiert nicht (1–{part_count}, 0 = alle Teile).")

    pins = symbol.get("pins")
    if not isinstance(pins, list):
        issues.add(f"{where}: 'pins' muss eine Liste sein.")
        pins = []
    for i, pin in enumerate(pins):
        if not isinstance(pin, dict):
            issues.add(f"{where}: Pin {i + 1} ist kein Objekt.")
            continue
        designator = pin.get("designator")
        pw = f"{where}, Pin {designator if isinstance(designator, str) else i + 1}"
        if not isinstance(designator, str) or not designator.strip():
            issues.add(f"{pw}: Pin-Nummer muss ein nicht leerer Text sein (Zahlen werden sonst verworfen).")
        if not isinstance(pin.get("name"), str):
            issues.add(f"{pw}: Pin-Name muss Text sein.")
        if "description" in pin and not isinstance(pin["description"], str):
            issues.add(f"{pw}: Pin-Beschreibung muss Text sein.")
        issues.extend(free_text_issues(designator, pw, "Pin-Nummer"))
        issues.extend(free_text_issues(pin.get("name"), pw, "Pin-Name"))
        issues.extend(free_text_issues(pin.get("description"), pw, "Pin-Beschreibung"))
        for key in ("x", "y"):
            value = pin.get(key)
            if not _is_int(value):
                issues.add(f"{pw}: '{key}' muss eine ganze Zahl (Rastereinheiten) sein, nicht {value!r}.")
            elif abs(value) > SCH_COORD_LIMIT_UNITS:
                issues.add(f"{pw}: '{key}' = {value} außerhalb des zulässigen Bereichs.")
        length = pin.get("length")
        if not _is_int(length) or not 0 <= length <= MAX_PIN_LENGTH_UNITS:
            issues.add(f"{pw}: Pinlänge {length!r} ungültig (ganze Zahl 0–{MAX_PIN_LENGTH_UNITS}).")
        if pin.get("orientation") not in PIN_ORIENTATIONS:
            issues.add(f"{pw}: Ausrichtung {pin.get('orientation')!r} ungültig (left/right/up/down).")
        if pin.get("electrical_type", "passive") not in RUST_ELECTRICAL_TYPES:
            issues.add(f"{pw}: elektrischer Typ {pin.get('electrical_type')!r} unbekannt.")
        for key in PIN_DECORATION_KEYS:
            if key in pin and pin[key] not in SAFE_PIN_DECORATIONS:
                issues.add(
                    f"{pw}: Pin-Symbol {pin[key]!r} wird vom Bibliotheks-Writer falsch gespeichert – erlaubt: "
                    + ", ".join(sorted(SAFE_PIN_DECORATIONS))
                    + "."
                )
        for key in ("hidden", "show_name", "show_designator"):
            if key in pin and not isinstance(pin[key], bool):
                issues.add(f"{pw}: '{key}' muss true/false sein.")
        if "owner_part_id" in pin:
            check_part(pw, pin["owner_part_id"])
    for key, minimum, coord_keys in (
        ("rectangles", 0, ("x1", "y1", "x2", "y2")),
        ("round_rects", 0, ("x1", "y1", "x2", "y2", "corner_x_radius", "corner_y_radius")),
        ("lines", 0, ("x1", "y1", "x2", "y2")),
        ("arcs", 0, ("x", "y", "radius")),
        ("ellipses", 0, ("x", "y", "radius_x", "radius_y")),
        ("labels", 0, ("x", "y")),
        ("polylines", 2, ()),
        ("polygons", 3, ()),
    ):
        items = symbol.get(key, [])
        if not isinstance(items, list):
            issues.add(f"{where}: '{key}' muss eine Liste sein.")
            continue
        for i, item in enumerate(items):
            gw = f"{where}, {key}[{i + 1}]"
            if not isinstance(item, dict):
                issues.add(f"{gw}: kein Objekt.")
                continue
            for ck in coord_keys:
                _check_coord(issues, gw, ck, item.get(ck), SCH_COORD_LIMIT_UNITS)
            if minimum:
                _check_point_list(issues, gw, item.get("points"), minimum, SCH_COORD_LIMIT_UNITS)
            if "line_width" in item and (not _is_int(item["line_width"]) or not 0 <= item["line_width"] <= 3):
                issues.add(f"{gw}: Linienbreite {item['line_width']!r} ungültig (0–3).")
            for ck in ("color", "line_color", "fill_color"):
                if ck in item and (not _is_int(item[ck]) or not 0 <= item[ck] <= 0xFFFFFF):
                    issues.add(f"{gw}: Farbe '{ck}' muss eine ganze Zahl 0–0xFFFFFF sein.")
            if "owner_part_id" in item:
                check_part(gw, item["owner_part_id"])
            if key == "labels":
                if not isinstance(item.get("text"), str) or not item.get("text"):
                    issues.add(f"{gw}: Text fehlt.")
                issues.extend(free_text_issues(item.get("text"), gw, "Text"))
                if "justification" in item and item["justification"] not in TEXT_JUSTIFICATIONS:
                    issues.add(f"{gw}: Ausrichtung {item['justification']!r} ungültig.")
    for i, param in enumerate(symbol.get("parameters", []) or []):
        if not isinstance(param, dict) or not isinstance(param.get("name"), str) or not param["name"].strip():
            issues.add(f"{where}: Parameter {i + 1} ohne Namen.")
            continue
        if "value" in param and not isinstance(param["value"], str):
            issues.add(f"{where}: Parameter {param['name']!r}: Wert muss Text sein.")
        for key in ("x", "y"):
            if key in param:
                _check_coord(issues, f"{where}, Parameter {param['name']!r}", key, param[key], SCH_COORD_LIMIT_UNITS)
        if "justification" in param and (not _is_int(param["justification"]) or param["justification"] not in JUSTIFY_NAMES):
            issues.add(f"{where}: Parameter {param['name']!r}: Ausrichtung {param['justification']!r} ungültig (0–8).")
        issues.extend(free_text_issues(param["name"], where, "Parametername"))
        issues.extend(free_text_issues(param.get("value"), f"{where}, Parameter {param['name']!r}", "Wert"))
    for i, link in enumerate(symbol.get("footprints", []) or []):
        if not isinstance(link, dict):
            issues.add(f"{where}: Footprint-Verknüpfung {i + 1} ist kein Objekt.")
            continue
        lw = f"{where}: Footprint-Verknüpfung"
        issues.extend(validate_component_name(link.get("name"), lw))
        issues.extend(free_text_issues(link.get("library_path"), lw, "Bibliothekspfad"))
        issues.extend(free_text_issues(link.get("description"), lw, "Beschreibung"))
    order = symbol.get("primitive_order")
    if order is not None:
        if not isinstance(order, list) or any(token not in PRIMITIVE_KEYS for token in order):
            unknown = sorted({str(t) for t in order if t not in PRIMITIVE_KEYS}) if isinstance(order, list) else [repr(order)]
            issues.add(
                f"{where}: unbekannte Einträge in primitive_order ({', '.join(unknown)}) – der Bibliotheks-Writer würde die "
                "Zeichenreihenfolge stillschweigend verwerfen."
            )
        else:
            for token, key in PRIMITIVE_KEYS.items():
                expected = len(symbol.get(key) or [])
                if order.count(token) != expected:
                    issues.add(f"{where}: primitive_order nennt {order.count(token)}× '{token}', vorhanden sind {expected}.")
    return issues.items


def validate_footprint_payload(footprint: Mapping[str, Any]) -> list[str]:
    """Strict check of a ``write_pcblib``/``update_component`` footprint (German issues)."""
    issues = _Issues()
    name = footprint.get("name")
    where = f"Footprint {name!r}"
    issues.extend(validate_component_name(name, "Footprint"))
    _check_keys(issues, where, footprint, _FOOTPRINT_KEYS)
    if not isinstance(footprint.get("description", ""), str):
        issues.add(f"{where}: Beschreibung muss Text sein.")
    issues.extend(free_text_issues(footprint.get("description"), where, "Beschreibung"))
    limit = PCB_COORD_LIMIT_MM
    pads = footprint.get("pads", [])
    if not isinstance(pads, list):
        issues.add(f"{where}: 'pads' muss eine Liste sein.")
        pads = []
    for i, pad in enumerate(pads):
        if not isinstance(pad, dict):
            issues.add(f"{where}: Pad {i + 1} ist kein Objekt.")
            continue
        designator = pad.get("designator")
        pw = f"{where}, Pad {designator if isinstance(designator, str) else i + 1}"
        _check_keys(issues, pw, pad, _PAD_KEYS)
        if not isinstance(designator, str) or not designator.strip():
            issues.add(f"{pw}: Pad-Bezeichner muss ein nicht leerer Text sein.")
        issues.extend(free_text_issues(designator, pw, "Pad-Bezeichner"))
        for key in ("x", "y"):
            _check_coord(issues, pw, key, pad.get(key), limit)
        for key in ("width", "height"):
            value = pad.get(key)
            if not _is_num(value) or value <= 0:
                issues.add(f"{pw}: '{key}' muss größer als 0 sein (ist {value!r}).")
        shape = pad.get("shape")
        if shape not in RUST_PAD_SHAPES:
            issues.add(
                f"{pw}: Pad-Form {shape!r} fehlt oder ist ungültig – sie muss immer angegeben werden "
                "(rectangle, rounded_rectangle, round, oval, octagonal)."
            )
        if "corner_radius_percent" in pad:
            pct = pad["corner_radius_percent"]
            if not _is_int(pct) or not 0 <= pct <= 100:
                issues.add(f"{pw}: Eckenradius {pct!r} % ungültig (0–100).")
        layer = pad.get("layer")
        if layer not in PAD_LAYERS:
            issues.add(f"{pw}: Pad-Lage {layer!r} ungültig (Top Layer, Bottom Layer, Multi-Layer).")
        if "rotation" in pad and not _is_num(pad["rotation"]):
            issues.add(f"{pw}: Drehung muss eine Zahl sein.")
        if pad.get("stack_mode", "simple") != "simple":
            issues.add(f"{pw}: nur stack_mode 'simple' wird unterstützt (andere verlieren Pad-Formen).")
        hole = pad.get("hole_size")
        if hole is not None:
            if not _is_num(hole) or hole <= 0:
                issues.add(f"{pw}: Bohrdurchmesser {hole!r} ungültig.")
            if layer != L.MULTI_LAYER:
                issues.add(f"{pw}: Pads mit Bohrung müssen auf 'Multi-Layer' liegen.")
        hole_shape = pad.get("hole_shape", "round")
        if hole_shape not in HOLE_SHAPES:
            issues.add(f"{pw}: Bohrungsform {hole_shape!r} ungültig (round, square, slot).")
        if hole_shape == "slot":
            slot = pad.get("hole_slot_length")
            if not _is_num(slot) or not _is_num(hole) or slot < hole:
                issues.add(f"{pw}: Langloch-Länge {slot!r} muss mindestens dem Bohrdurchmesser entsprechen.")
        if "is_plated" in pad and not isinstance(pad["is_plated"], bool):
            issues.add(f"{pw}: 'is_plated' muss true/false sein.")
        for key in ("paste_mask_expansion_mode", "solder_mask_expansion_mode"):
            if key in pad and pad[key] not in EXPANSION_MODES:
                issues.add(f"{pw}: {key} {pad[key]!r} ungültig (none, from_rule, manual).")
        for key in ("paste_mask_expansion", "solder_mask_expansion"):
            if key in pad and (not _is_num(pad[key]) or abs(pad[key]) > 100):
                issues.add(f"{pw}: {key} {pad[key]!r} ungültig.")

    def check_layer(w: str, value: object) -> None:
        if not L.is_rust_layer(value):
            issues.add(f"{w}: Lage {value!r} wird vom Bibliotheks-Writer nicht akzeptiert.")

    for i, track in enumerate(footprint.get("tracks", []) or []):
        tw = f"{where}, Linie {i + 1}"
        if not isinstance(track, dict):
            issues.add(f"{tw}: kein Objekt.")
            continue
        for key in ("x1", "y1", "x2", "y2"):
            _check_coord(issues, tw, key, track.get(key), limit)
        if not _is_num(track.get("width")) or track["width"] <= 0:
            issues.add(f"{tw}: Linienbreite muss größer als 0 sein.")
        check_layer(tw, track.get("layer"))
    for i, arc in enumerate(footprint.get("arcs", []) or []):
        aw = f"{where}, Bogen {i + 1}"
        if not isinstance(arc, dict):
            issues.add(f"{aw}: kein Objekt.")
            continue
        for key in ("x", "y"):
            _check_coord(issues, aw, key, arc.get(key), limit)
        for key in ("radius", "width"):
            if not _is_num(arc.get(key)) or arc[key] <= 0:
                issues.add(f"{aw}: '{key}' muss größer als 0 sein.")
        for key in ("start_angle", "end_angle"):
            if not _is_num(arc.get(key)):
                issues.add(f"{aw}: '{key}' muss eine Zahl sein.")
        check_layer(aw, arc.get("layer"))
    for i, region in enumerate(footprint.get("regions", []) or []):
        rw = f"{where}, Fläche {i + 1}"
        if not isinstance(region, dict):
            issues.add(f"{rw}: kein Objekt.")
            continue
        _check_point_list(issues, rw, region.get("vertices"), 3, limit)
        check_layer(rw, region.get("layer"))
    for i, text in enumerate(footprint.get("text", []) or []):
        xw = f"{where}, Text {i + 1}"
        if not isinstance(text, dict):
            issues.add(f"{xw}: kein Objekt.")
            continue
        for key in ("x", "y"):
            _check_coord(issues, xw, key, text.get(key), limit)
        if not _is_num(text.get("height")) or text["height"] <= 0:
            issues.add(f"{xw}: Texthöhe muss größer als 0 sein.")
        if not isinstance(text.get("text"), str) or not text["text"]:
            issues.add(f"{xw}: Text fehlt.")
        issues.extend(free_text_issues(text.get("text"), xw, "Text"))
        if "justification" in text and text["justification"] not in TEXT_JUSTIFICATIONS:
            issues.add(f"{xw}: Ausrichtung {text['justification']!r} ungültig.")
        check_layer(xw, text.get("layer"))
    for i, body in enumerate(footprint.get("component_bodies", []) or []):
        bw = f"{where}, 3D-Körper {i + 1}"
        if not isinstance(body, dict):
            issues.add(f"{bw}: kein Objekt.")
            continue
        if not _is_num(body.get("overall_height")):
            issues.add(f"{bw}: Gesamthöhe fehlt.")
        if "standoff_height" in body and not _is_num(body["standoff_height"]):
            issues.add(f"{bw}: Abstandshöhe muss eine Zahl sein.")
        if "outline" in body:
            _check_point_list(issues, bw, body.get("outline"), 3, limit)
        if "layer" in body:
            check_layer(bw, body.get("layer"))
        issues.extend(free_text_issues(body.get("name"), bw, "Name"))
        issues.extend(free_text_issues(body.get("model_name"), bw, "Modellname"))
        color = body.get("body_color_3d")
        if color is not None and (not _is_int(color) or not 0 <= color <= 0xFFFFFF):
            issues.add(f"{bw}: Farbe muss eine ganze Zahl 0–0xFFFFFF sein.")
        opacity = body.get("body_opacity_3d")
        if opacity is not None and (not _is_num(opacity) or not 0 <= opacity <= 1):
            issues.add(f"{bw}: Deckkraft muss zwischen 0 und 1 liegen.")
    step = footprint.get("step_model")
    if step is not None:
        if not isinstance(step, dict) or step.get("embed") is not True:
            issues.add(f"{where}: STEP-Modelle müssen eingebettet werden (embed: true).")
        elif not isinstance(step.get("filepath"), str) or not Path(step["filepath"]).is_absolute():
            issues.add(f"{where}: STEP-Pfad muss absolut sein.")
    return issues.items


# --------------------------------------------------------------------------- symbols


def symbol_palette(spec: SymbolSpec, style: SymbolStyle | None = None) -> tuple[int, int]:
    """Default (line, fill) colours: IC palette for box symbols, discrete palette otherwise."""
    style = style or SymbolStyle()
    is_box = any(isinstance(g, SymRect) and g.filled for g in spec.graphics)
    if is_box:
        return hex_to_bgr(style.ic_line_color), hex_to_bgr(style.ic_fill_color)
    line = hex_to_bgr(style.discrete_line_color)
    return line, line


def _color(value: str | None, default: int, issues: _Issues, where: str) -> int:
    if value is None or value == "":
        return default
    try:
        return hex_to_bgr(value)
    except ValueError as exc:
        issues.add(f"{where}: {exc}")
        return default


def _check_text_pos(issues: _Issues, where: str, x: float, y: float) -> None:
    """Designator/Comment positions (mil) must lie inside the schematic coordinate range."""
    limit = SCH_COORD_LIMIT_UNITS * 10
    for label, value in (("x", x), ("y", y)):
        if not math.isfinite(float(value)) or abs(float(value)) > limit:
            issues.add(f"{where}: Position {label} = {value} mil liegt außerhalb von ±{limit:g} mil.")


def symbol_to_rust(
    spec: SymbolSpec,
    style: SymbolStyle | None = None,
    *,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Convert a :class:`SymbolSpec` (mil) into a ``write_schlib`` symbol (10-mil units).

    Pins become integer units (coordinates and lengths must lie on the 10-mil raster),
    free text becomes ``labels``; parameters are only written when given (``comment``
    other than ``*`` becomes the visible ``Comment`` parameter).
    """
    issues = _Issues()
    issues.extend(validate_component_name(spec.name, "Symbol"))
    style = style or SymbolStyle()
    line_default, fill_default = symbol_palette(spec, style)
    part_count = spec.part_count
    if not 1 <= part_count <= MAX_PART_COUNT:
        issues.add(f"Symbol {spec.name}: Teileanzahl {part_count} ungültig (1–{MAX_PART_COUNT}).")
    prefix = (spec.designator_prefix or "U").strip() or "U"
    if not PREFIX_RE.match(prefix):
        issues.add(f"Symbol {spec.name}: Bezeichner-Präfix {prefix!r} ungültig.")
    issues.extend(free_text_issues(spec.description, f"Symbol {spec.name}", "Beschreibung"))
    issues.extend(free_text_issues(spec.comment, f"Symbol {spec.name}", "Kommentar"))
    pins: list[dict[str, Any]] = []
    for pin in spec.pins:
        where = f"Symbol {spec.name}, Pin {pin.designator or '?'}"
        if not pin.designator or not pin.designator.strip():
            issues.add(f"Symbol {spec.name}: Pin ohne Pin-Nummer.")
        issues.extend(free_text_issues(pin.designator, where, "Pin-Nummer"))
        issues.extend(free_text_issues(pin.name, where, "Pin-Name"))
        issues.extend(free_text_issues(pin.description, where, "Pin-Beschreibung"))
        for label, value in (("x", pin.x), ("y", pin.y), ("Pinlänge", pin.length)):
            if value % 10:
                issues.add(f"{where}: {label} = {value} mil liegt nicht auf dem 10-mil-Raster.")
        if pin.length < 0:
            issues.add(f"{where}: negative Pinlänge.")
        if not 0 <= pin.part <= part_count:
            issues.add(f"{where}: Teil {pin.part} existiert nicht (1–{part_count}, 0 = alle Teile).")
        entry: dict[str, Any] = {
            "designator": str(pin.designator),
            "name": pin.name or "",
            "x": pin.x // 10,
            "y": pin.y // 10,
            "length": pin.length // 10,
            "orientation": pin.orientation,
            "electrical_type": ELECTRICAL_TO_RUST[pin.electrical],
            "owner_part_id": pin.part,
            "show_name": bool(pin.show_name),
            "show_designator": bool(pin.show_designator),
            "hidden": bool(pin.hidden),
        }
        if pin.description:
            entry["description"] = pin.description
        for field_name, key in PIN_EDGE_KEYS.items():
            decoration = getattr(pin, field_name)
            if decoration and decoration != "none":
                if decoration not in SAFE_PIN_DECORATIONS:
                    issues.add(f"{where}: Pin-Symbol {decoration!r} wird vom Bibliotheks-Writer falsch gespeichert.")
                entry[key] = decoration
        pins.append(entry)

    rectangles: list[dict[str, Any]] = []
    round_rects: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    polylines: list[dict[str, Any]] = []
    polygons: list[dict[str, Any]] = []
    arcs: list[dict[str, Any]] = []
    ellipses: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []
    order: list[str] = []  # z-order: graphics first, then pins and parameters (see module docs)
    for idx, g in enumerate(spec.graphics):
        where = f"Symbol {spec.name}, Grafik {idx + 1} ({g.kind})"
        if not 0 <= g.part <= part_count:
            issues.add(f"{where}: Teil {g.part} existiert nicht.")
        width = LINE_WIDTHS.get(g.line_width, 1)
        line_color = _color(g.color, line_default, issues, where)
        fill_color = _color(g.fill_color, fill_default, issues, where)
        if isinstance(g, SymRect):
            x1, x2 = sorted((g.x1, g.x2))
            y1, y2 = sorted((g.y1, g.y2))
            rect: dict[str, Any] = {
                "x1": _mu(x1),
                "y1": _mu(y1),
                "x2": _mu(x2),
                "y2": _mu(y2),
                "filled": bool(g.filled),
                "line_width": width,
                "line_color": line_color,
                "fill_color": fill_color,
                "owner_part_id": g.part,
            }
            if g.corner_radius and g.corner_radius > 0:
                rect["corner_x_radius"] = _mu(g.corner_radius)
                rect["corner_y_radius"] = _mu(g.corner_radius)
                round_rects.append(rect)
                order.append("round_rect")
            else:
                rectangles.append(rect)
                order.append("rectangle")
        elif isinstance(g, SymLine):
            if len(g.points) < 2:
                issues.add(f"{where}: eine Linie braucht mindestens 2 Punkte.")
            elif len(g.points) == 2:
                a, b = g.points
                lines.append(
                    {
                        "x1": _mu(a.x),
                        "y1": _mu(a.y),
                        "x2": _mu(b.x),
                        "y2": _mu(b.y),
                        "line_width": width,
                        "color": line_color,
                        "owner_part_id": g.part,
                    }
                )
                order.append("line")
            else:
                polylines.append(
                    {
                        "points": [_pt(_mu(p.x), _mu(p.y), 5) for p in g.points],
                        "line_width": width,
                        "color": line_color,
                        "owner_part_id": g.part,
                    }
                )
                order.append("polyline")
        elif isinstance(g, SymPolygon):
            if len(g.points) < 3:
                issues.add(f"{where}: ein Polygon braucht mindestens 3 Punkte.")
            polygons.append(
                {
                    "points": [_pt(_mu(p.x), _mu(p.y), 5) for p in g.points],
                    "filled": bool(g.filled),
                    "line_width": width,
                    "line_color": line_color,
                    "fill_color": fill_color,
                    "owner_part_id": g.part,
                }
            )
            order.append("polygon")
        elif isinstance(g, SymArc):
            if g.r <= 0:
                issues.add(f"{where}: Radius muss größer als 0 sein.")
            arc: dict[str, Any] = {
                "x": _mu(g.cx),
                "y": _mu(g.cy),
                "radius": _mu(g.r),
                "start_angle": _r(g.start, 4),
                "end_angle": _r(g.end, 4),
                "line_width": width,
                "color": line_color,
                "owner_part_id": g.part,
            }
            if g.fill_color:
                arc["fill_color"] = fill_color
            arcs.append(arc)
            order.append("arc")
        elif isinstance(g, SymEllipse):
            if g.rx <= 0 or g.ry <= 0:
                issues.add(f"{where}: Radien müssen größer als 0 sein.")
            ellipses.append(
                {
                    "x": _mu(g.cx),
                    "y": _mu(g.cy),
                    "radius_x": _mu(g.rx),
                    "radius_y": _mu(g.ry),
                    "filled": bool(g.filled),
                    "line_width": width,
                    "line_color": line_color,
                    "fill_color": fill_color,
                    "owner_part_id": g.part,
                }
            )
            order.append("ellipse")
        elif isinstance(g, SymText):
            if not g.text:
                issues.add(f"{where}: leerer Text.")
            issues.extend(free_text_issues(g.text, where, "Text"))
            if g.size != 10 and notes is not None:
                notes.append(
                    f"Symbol {spec.name}: Schriftgröße {g.size} pt wird nicht übernommen "
                    "(der Bibliotheks-Writer kennt nur Schrift 1 = Times New Roman 10)."
                )
            labels.append(
                {
                    "x": _mu(g.x),
                    "y": _mu(g.y),
                    "text": g.text,
                    "justification": g.justify,
                    "rotation": float(g.rotation),
                    "color": line_color,
                    "font_id": 1,
                    "owner_part_id": g.part,
                }
            )
            order.append("label")

    designator_xy: tuple[float, float] | None = None
    if spec.designator_pos is not None:
        pos = spec.designator_pos
        _check_text_pos(issues, f"Symbol {spec.name}, Bezeichner", pos.x, pos.y)
        designator_xy = (_mu(pos.x), _mu(pos.y))
        if pos.justify != "bottom_left" and notes is not None:
            notes.append(
                f"Symbol {spec.name}: Ausrichtung des Bezeichners ({pos.justify}) wird vom Bibliotheks-Writer nicht gespeichert "
                "(Altium verankert ihn unten links)."
            )
    parameters: list[dict[str, Any]] = []
    comment = (spec.comment or "").strip()
    if (comment and comment != "*") or spec.comment_pos is not None:
        cx, cy = (spec.comment_pos.x, spec.comment_pos.y) if spec.comment_pos is not None else DEFAULT_COMMENT_POS
        _check_text_pos(issues, f"Symbol {spec.name}, Kommentar", cx, cy)
        comment_param: dict[str, Any] = {
            "name": "Comment",
            "value": spec.comment if comment and comment != "*" else "*",
            "x": _mu(cx),
            "y": _mu(cy),
            "owner_part_id": -1,
        }
        if spec.comment_pos is not None and spec.comment_pos.justify != "bottom_left":
            comment_param["justification"] = JUSTIFY_ORDINALS[spec.comment_pos.justify]
        parameters.append(comment_param)
    for pname, pvalue in spec.parameters.items():
        if not isinstance(pname, str) or not pname.strip():
            issues.add(f"Symbol {spec.name}: Parameter ohne Namen.")
            continue
        issues.extend(free_text_issues(pname, f"Symbol {spec.name}", "Parametername"))
        issues.extend(free_text_issues(str(pvalue), f"Symbol {spec.name}, Parameter {pname!r}", "Wert"))
        if pname == "Comment" and parameters and parameters[0]["name"] == "Comment":
            if notes is not None:
                notes.append(f"Symbol {spec.name}: Parameter 'Comment' doppelt – der Kommentar des Symbols gilt.")
            continue
        parameters.append(
            {"name": pname, "value": str(pvalue), "hidden": True, "x": -5, "y": 15, "owner_part_id": -1}
        )
    links: list[dict[str, Any]] = []
    for link in spec.footprints:
        lw = f"Symbol {spec.name}: Footprint-Verknüpfung"
        issues.extend(validate_component_name(link.name, lw))
        issues.extend(free_text_issues(link.library_path, lw, "Bibliothekspfad"))
        issues.extend(free_text_issues(link.description, lw, "Beschreibung"))
        entry = {"name": link.name}
        if link.library_path:
            entry["library_path"] = link.library_path
        if link.description:
            entry["description"] = link.description
        links.append(entry)
    issues.raise_if_any()

    order += ["pin"] * len(pins)
    order += ["parameter"] * len(parameters)
    out: dict[str, Any] = {
        "name": spec.name,
        "description": spec.description or "",
        "designator_prefix": prefix,
        "part_count": part_count,
        "pins": pins,
        "primitive_order": order,
    }
    if designator_xy is not None:
        out["designator_x"], out["designator_y"] = designator_xy
    for key, items in (
        ("rectangles", rectangles),
        ("round_rects", round_rects),
        ("lines", lines),
        ("polylines", polylines),
        ("polygons", polygons),
        ("arcs", arcs),
        ("ellipses", ellipses),
        ("labels", labels),
        ("parameters", parameters),
        ("footprints", links),
    ):
        if items:
            out[key] = items
    return out


#: Symbol content the PartForge model cannot represent: key -> German label.
_UNSUPPORTED_SYMBOL_KEYS: Final[dict[str, str]] = {
    "pies": "Kreissektoren",
    "beziers": "Bézierkurven",
    "text_frames": "Textrahmen",
    "images": "Bilder",
}


def _main_display_mode(item: Mapping[str, Any]) -> bool:
    return int(_num(item.get("owner_part_display_mode"), 0)) == 0


def _decoration(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    return str(value).strip() if isinstance(value, str) and value.strip() else "none"


def _unsupported_decorations(pin: Mapping[str, Any]) -> list[str]:
    """Decorations of a read-back pin that the PartForge model cannot hold."""
    out = [key for key in ("symbol_inside", "symbol_outside") if _decoration(pin, key) != "none"]
    out += [key for key in PIN_EDGE_KEYS.values() if _decoration(pin, key) not in SAFE_PIN_DECORATIONS]
    return out


def _edge_decoration(pin: Mapping[str, Any], key: str) -> PinDecoration | None:
    value = _decoration(pin, key)
    return cast(PinDecoration, value) if value in SAFE_PIN_DECORATIONS and value != "none" else None


def _text_pos(x: Any, y: Any, justification: Any = None) -> TextPos | None:
    """Designator/Comment position (schematic units -> mil) from read-back values."""
    if not (_is_num(x) and _is_num(y)):
        return None
    justify: TextJustify = "bottom_left"
    if _is_int(justification) and justification in JUSTIFY_NAMES:
        justify = cast(TextJustify, JUSTIFY_NAMES[justification])
    elif isinstance(justification, str) and justification in TEXT_JUSTIFICATIONS:
        justify = cast(TextJustify, justification)
    return TextPos(x=round(float(x) * 10), y=round(float(y) * 10), justify=justify)


def _symbol_losses(data: Mapping[str, Any]) -> list[str]:
    """What a round trip through :class:`SymbolSpec` loses (German, for ``notes``)."""
    losses: list[str] = []
    pins = [p for p in data.get("pins") or [] if isinstance(p, dict)]
    decorated = [p for p in pins if _unsupported_decorations(p)]
    if decorated:
        losses.append(
            f"Pin-Symbole innerhalb/außerhalb der Pinlinie oder nicht unterstützte Kanten-Symbole an {len(decorated)} Pin(s)"
        )
    fractional = [
        p for p in pins if isinstance(p.get("frac"), dict) and any(_num(v) != 0 for v in p["frac"].values())
    ]
    if fractional:
        losses.append(f"Pin-Positionen außerhalb des 10-mil-Rasters an {len(fractional)} Pin(s)")
    if any(int(_num(p.get("colour"), 0)) != 0 for p in pins):
        losses.append("Pinfarben")
    modes = int(_num(data.get("display_mode_count"), 1))
    other_modes = any(
        isinstance(item, dict) and not _main_display_mode(item)
        for key in sorted(set(PRIMITIVE_KEYS.values()) - {"parameters"})
        for item in data.get(key) or []
    )
    if modes > 1 or other_modes:
        losses.append(f"alternative Darstellungen ({max(modes - 1, 1)}) – nur die Normaldarstellung wird übernommen")
    for key, label in _UNSUPPORTED_SYMBOL_KEYS.items():
        count = len([i for i in data.get(key) or [] if isinstance(i, dict)])
        if count:
            losses.append(f"{label} ({count})")
    elliptical = len([i for i in data.get("elliptical_arcs") or [] if isinstance(i, dict)])
    if elliptical:
        losses.append(f"elliptische Bögen ({elliptical}) werden zu Kreisbögen")
    styled = 0
    for key in ("rectangles", "round_rects", "lines", "polylines", "polygons"):
        for item in data.get(key) or []:
            if isinstance(item, dict) and (
                int(_num(item.get("line_style"), 0)) != 0
                or int(_num(item.get("start_line_shape"), 0)) != 0
                or int(_num(item.get("end_line_shape"), 0)) != 0
            ):
                styled += 1
    if styled:
        losses.append(f"Linienstile/Pfeilspitzen ({styled})")
    labels = [i for i in [*(data.get("labels") or []), *(data.get("text") or [])] if isinstance(i, dict)]
    if any(int(_num(i.get("font_id"), 1)) != 1 or i.get("is_mirrored") for i in labels):
        losses.append("Schriftarten/gespiegelte Texte")
    if any(i.get("is_hidden") for i in labels):
        losses.append("verborgene Texte werden sichtbar")
    visible = [
        p.get("name")
        for p in data.get("parameters") or []
        if isinstance(p, dict) and p.get("name") != "Comment" and p.get("hidden") is False
    ]
    if visible:
        losses.append(f"sichtbare Parameter ({', '.join(map(str, visible[:3]))}) werden verborgen")
    return losses


def rust_to_symbol(data: Mapping[str, Any], *, notes: list[str] | None = None) -> SymbolSpec:
    """Convert a ``read_schlib``/``get_component`` symbol into a :class:`SymbolSpec` (mil).

    Only the normal display mode is converted. Content the model cannot represent
    (pin decorations, alternate display modes, text frames, line styles, …) is reported
    in ``notes`` (one German line per symbol) because writing the spec back would lose it.
    """
    if notes is not None:
        losses = _symbol_losses(data)
        if losses:
            notes.append(f"Symbol {data.get('name', '')}: nicht übernommen: " + "; ".join(losses) + ".")
    part_count = int(_num(data.get("part_count"), 1)) or 1
    pins: list[SymPin] = []
    for raw in data.get("pins") or []:
        if not isinstance(raw, dict) or not _main_display_mode(raw):
            continue
        orientation = _orientation(raw.get("orientation"))
        pins.append(
            SymPin(
                designator=str(raw.get("designator", "")),
                name=str(raw.get("name", "")),
                x=round(_num(raw.get("x")) * 10),
                y=round(_num(raw.get("y")) * 10),
                orientation=orientation,
                length=round(_num(raw.get("length")) * 10),
                electrical=_electrical(raw.get("electrical_type")),
                part=int(_num(raw.get("owner_part_id"), 1)),
                show_name=bool(raw.get("show_name", True)),
                show_designator=bool(raw.get("show_designator", True)),
                hidden=bool(raw.get("hidden", False)),
                description=raw.get("description") or None,
                inner_edge=_edge_decoration(raw, "symbol_inner_edge"),
                outer_edge=_edge_decoration(raw, "symbol_outer_edge"),
            )
        )
    graphics: list[Any] = []

    def items(key: str) -> list[Mapping[str, Any]]:
        return [i for i in data.get(key) or [] if isinstance(i, dict) and _main_display_mode(i)]

    def width_of(item: Mapping[str, Any]) -> LineWidth:
        return cast(LineWidth, LINE_WIDTH_NAMES.get(int(_num(item.get("line_width"), 1)), "small"))

    def part_of(item: Mapping[str, Any]) -> int:
        return int(_num(item.get("owner_part_id"), 1))

    def color_of(item: Mapping[str, Any], key: str) -> str | None:
        return bgr_to_hex(item[key]) if key in item else None

    for key in ("rectangles", "round_rects"):
        for item in items(key):
            radius = max(_num(item.get("corner_x_radius")), _num(item.get("corner_y_radius")))
            graphics.append(
                SymRect(
                    x1=_um(item.get("x1")),
                    y1=_um(item.get("y1")),
                    x2=_um(item.get("x2")),
                    y2=_um(item.get("y2")),
                    filled=bool(item.get("filled", True)),
                    corner_radius=_um(radius) if key == "round_rects" else 0,
                    line_width=width_of(item),
                    color=color_of(item, "line_color"),
                    fill_color=color_of(item, "fill_color"),
                    part=part_of(item),
                )
            )
    for item in items("lines"):
        graphics.append(
            SymLine(
                points=[
                    Point(x=_um(item.get("x1")), y=_um(item.get("y1"))),
                    Point(x=_um(item.get("x2")), y=_um(item.get("y2"))),
                ],
                line_width=width_of(item),
                color=color_of(item, "color"),
                part=part_of(item),
            )
        )
    for item in items("polylines"):
        pts = [Point(x=_r(p.x * 10, 4), y=_r(p.y * 10, 4)) for p in _points(item.get("points") or item.get("vertices"))]
        if len(pts) >= 2:
            graphics.append(SymLine(points=pts, line_width=width_of(item), color=color_of(item, "color"), part=part_of(item)))
    for item in items("polygons"):
        pts = [Point(x=_r(p.x * 10, 4), y=_r(p.y * 10, 4)) for p in _points(item.get("points"))]
        if len(pts) >= 3:
            graphics.append(
                SymPolygon(
                    points=pts,
                    filled=bool(item.get("filled", True)),
                    line_width=width_of(item),
                    color=color_of(item, "line_color"),
                    fill_color=color_of(item, "fill_color"),
                    part=part_of(item),
                )
            )
    for key in ("arcs", "elliptical_arcs"):
        for item in items(key):
            graphics.append(
                SymArc(
                    cx=_um(item.get("x")),
                    cy=_um(item.get("y")),
                    r=_um(item.get("radius")),
                    start=_r(_num(item.get("start_angle")), 4),
                    end=_r(_num(item.get("end_angle"), 360.0), 4),
                    line_width=width_of(item),
                    color=color_of(item, "color"),
                    part=part_of(item),
                )
            )
    for item in items("ellipses"):
        graphics.append(
            SymEllipse(
                cx=_um(item.get("x")),
                cy=_um(item.get("y")),
                rx=_um(item.get("radius_x")),
                ry=_um(item.get("radius_y")),
                filled=bool(item.get("filled", False)),
                line_width=width_of(item),
                color=color_of(item, "line_color"),
                fill_color=color_of(item, "fill_color"),
                part=part_of(item),
            )
        )
    for key in ("labels", "text"):
        for item in items(key):
            if isinstance(item.get("text"), str) and item["text"]:
                rotation = round(_num(item.get("rotation")) / 90.0) % 4 * 90
                graphics.append(
                    SymText(
                        x=_um(item.get("x")),
                        y=_um(item.get("y")),
                        text=item["text"],
                        justify=_justify(item.get("justification")),
                        rotation=rotation,  # type: ignore[arg-type]
                        color=color_of(item, "color"),
                        part=part_of(item),
                    )
                )
    comment = "*"
    comment_pos: TextPos | None = None
    parameters: dict[str, str] = {}
    for item in data.get("parameters") or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        value = item.get("value", "*")
        value = value if isinstance(value, str) else str(value)
        if item["name"] == "Comment":
            comment = value
            comment_pos = _text_pos(item.get("x"), item.get("y"), item.get("justification"))
        else:
            parameters[item["name"]] = value
    links: list[FootprintLink] = []
    for item in data.get("footprints") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"]:
            links.append(
                FootprintLink(
                    name=item["name"],
                    library_path=item.get("library_path") or None,
                    description=item.get("description") or None,
                )
            )
    designator = str(data.get("designator") or data.get("designator_prefix") or "U")
    prefix = designator.rstrip("?").strip() or "U"
    return SymbolSpec(
        name=str(data.get("name", "")),
        description=str(data.get("description") or ""),
        designator_prefix=prefix,
        comment=comment,
        designator_pos=_text_pos(data.get("designator_x"), data.get("designator_y")),
        comment_pos=comment_pos,
        part_count=part_count,
        pins=pins,
        graphics=graphics,
        parameters=parameters,
        footprints=links,
    )


# --------------------------------------------------------------------------- footprints


def synthesize_body(spec: FootprintSpec) -> Body3D | None:
    """Extruded body from ``spec.height`` (assembly outline, else pad extent)."""
    if not spec.height or spec.height <= 0:
        return None
    x1, y1, x2, y2 = spec.bbox({"assembly"})
    if x2 - x1 <= 1e-6 or y2 - y1 <= 1e-6:
        x1, y1, x2, y2 = spec.bbox({"copper"})
    if x2 - x1 <= 1e-6 or y2 - y1 <= 1e-6:
        return None
    return Body3D(
        name="Body",
        outline=[Point(x=x1, y=y1), Point(x=x2, y=y1), Point(x=x2, y=y2), Point(x=x1, y=y2)],
        z_bottom=0.0,
        z_top=float(spec.height),
    )


def _pad_to_rust(fp_name: str, pad: Pad, style: FootprintStyle, issues: _Issues) -> dict[str, Any]:
    where = f"Footprint {fp_name}, Pad {pad.designator or '?'}"
    if not pad.designator or not pad.designator.strip():
        issues.add(f"Footprint {fp_name}: Pad ohne Bezeichner.")
    issues.extend(free_text_issues(pad.designator, where, "Pad-Bezeichner"))
    if pad.width <= 0 or pad.height <= 0:
        issues.add(f"{where}: Breite und Höhe müssen größer als 0 sein.")
    shape = PAD_SHAPE_TO_RUST[pad.shape]
    entry: dict[str, Any] = {
        "designator": str(pad.designator),
        "x": _r(pad.x),
        "y": _r(pad.y),
        "width": _r(pad.width),
        "height": _r(pad.height),
        "shape": shape,
        "rotation": _r(pad.rotation, 4),
        "layer": L.pad_layer(pad.side),
        "stack_mode": "simple",
    }
    if shape == "rounded_rectangle":
        pct = pad.corner_radius_pct if pad.corner_radius_pct is not None else style.pad_corner_radius_pct
        if not 0 <= pct <= 100:
            issues.add(f"{where}: Eckenradius {pct} % ungültig (0–100).")
        entry["corner_radius_percent"] = int(pct)
    if pad.side == "through":
        if not pad.hole or pad.hole <= 0:
            issues.add(f"{where}: Durchsteck-Pad ohne Bohrung.")
        else:
            entry["hole_size"] = _r(pad.hole)
            entry["is_plated"] = bool(pad.plated)
            if pad.hole_length is not None:
                if pad.hole_length > pad.hole + 1e-9:
                    entry["hole_shape"] = "slot"
                    entry["hole_slot_length"] = _r(pad.hole_length)
                    entry["hole_rotation"] = 90.0 if pad.height > pad.width else 0.0
                elif pad.hole_length < pad.hole - 1e-9:
                    issues.add(f"{where}: Langloch-Länge {pad.hole_length} mm ist kleiner als die Bohrung {pad.hole} mm.")
    elif pad.hole:
        issues.add(f"{where}: Bohrungen sind nur bei Durchsteck-Pads (side='through') möglich.")
    if pad.side in ("top", "bottom"):
        if not pad.paste:
            entry["paste_mask_expansion"] = -_r(max(pad.width, pad.height) / 2.0)
            entry["paste_mask_expansion_mode"] = "manual"
        elif pad.paste_expansion is not None:
            entry["paste_mask_expansion"] = _r(pad.paste_expansion)
            entry["paste_mask_expansion_mode"] = "manual"
    elif pad.paste_expansion is not None:
        entry["paste_mask_expansion"] = _r(pad.paste_expansion)
        entry["paste_mask_expansion_mode"] = "manual"
    if pad.mask_expansion is not None:
        entry["solder_mask_expansion"] = _r(pad.mask_expansion)
        entry["solder_mask_expansion_mode"] = "manual"
    return entry


def footprint_to_rust(
    spec: FootprintSpec,
    layer_map: LayerMap | None = None,
    style: FootprintStyle | None = None,
    *,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """Convert a :class:`FootprintSpec` (mm) into a ``write_pcblib`` footprint.

    The STEP model is *not* included here (it needs an embedded model id, see
    :func:`step_body`); a footprint with a STEP model but without extruded bodies gets a
    synthesized extruded body from ``spec.height``.
    """
    issues = _Issues()
    issues.extend(validate_component_name(spec.name, "Footprint"))
    issues.extend(free_text_issues(spec.description, f"Footprint {spec.name}", "Beschreibung"))
    style = style or FootprintStyle()
    layer_map = layer_map or LayerMap()

    def layer(logical: str, where: str) -> str:
        try:
            return L.logical_to_altium(logical, layer_map)
        except L.LayerError as exc:
            issues.add(f"{where}: {exc}")
            return L.TOP_OVERLAY

    pads = [_pad_to_rust(spec.name, pad, style, issues) for pad in spec.pads]
    tracks: list[dict[str, Any]] = []
    for i, t in enumerate(spec.tracks):
        where = f"Footprint {spec.name}, Linie {i + 1}"
        if t.width <= 0:
            issues.add(f"{where}: Linienbreite muss größer als 0 sein.")
        tracks.append(
            {
                "x1": _r(t.x1),
                "y1": _r(t.y1),
                "x2": _r(t.x2),
                "y2": _r(t.y2),
                "width": _r(t.width),
                "layer": layer(t.layer, where),
            }
        )
    arcs: list[dict[str, Any]] = []
    for i, a in enumerate(spec.arcs):
        where = f"Footprint {spec.name}, Bogen {i + 1}"
        if a.r <= 0 or a.width <= 0:
            issues.add(f"{where}: Radius und Linienbreite müssen größer als 0 sein.")
        arcs.append(
            {
                "x": _r(a.cx),
                "y": _r(a.cy),
                "radius": _r(a.r),
                "start_angle": _r(a.start, 4),
                "end_angle": _r(a.end, 4),
                "width": _r(a.width),
                "layer": layer(a.layer, where),
            }
        )
    regions: list[dict[str, Any]] = []
    for i, rg in enumerate(spec.regions):
        where = f"Footprint {spec.name}, Fläche {i + 1}"
        if len(rg.points) < 3:
            issues.add(f"{where}: eine Fläche braucht mindestens 3 Punkte.")
        regions.append({"layer": layer(rg.layer, where), "vertices": [_pt(p.x, p.y) for p in rg.points]})
    texts: list[dict[str, Any]] = []
    for i, tx in enumerate(spec.texts):
        where = f"Footprint {spec.name}, Text {i + 1}"
        if not tx.text:
            issues.add(f"{where}: leerer Text.")
        issues.extend(free_text_issues(tx.text, where, "Text"))
        if tx.height <= 0:
            issues.add(f"{where}: Texthöhe muss größer als 0 sein.")
        content = latin1_text(tx.text)
        if content != tx.text and notes is not None:
            notes.append(f"Footprint {spec.name}: Text {tx.text!r} als {content!r} gespeichert (PcbLib kennt nur Latin-1).")
        entry: dict[str, Any]
        if tx.font == "truetype":
            font_name = (tx.font_name or TRUETYPE_DEFAULT_FONT).strip() or TRUETYPE_DEFAULT_FONT
            issues.extend(free_text_issues(font_name, where, "Schriftart"))
            box = truetype_text_box(content, tx.height, font_name)
            ax, ay = truetype_text_anchor(box, tx.x, tx.y, tx.rotation, tx.justify)
            entry = {"kind": "true_type", "font_name": font_name}
        else:
            # Altium anchors stroke text bottom-left: store the compensated anchor, keep the justification
            ax, ay = stroke_text_anchor(content, tx.x, tx.y, tx.height, tx.rotation, tx.justify)
            entry = {}
        texts.append(
            {
                "x": _r(ax),
                "y": _r(ay),
                "text": content,
                "height": _r(tx.height),
                "layer": layer(tx.layer, where),
                "stroke_width": _r(tx.stroke),
                "rotation": _r(tx.rotation, 4),
                "justification": tx.justify,
                **entry,
            }
        )
    bodies_src = list(spec.bodies)
    if spec.step is not None and not bodies_src:
        synth = synthesize_body(spec)
        if synth is not None:
            bodies_src.append(synth)
            if notes is not None:
                notes.append(
                    f"Footprint {spec.name}: extrudierter 3D-Körper mit der Bauhöhe {spec.height:g} mm ergänzt "
                    "(zusätzlich zum STEP-Modell)."
                )
        elif notes is not None:
            notes.append(f"Footprint {spec.name}: Bauhöhe unbekannt – kein extrudierter 3D-Körper neben dem STEP-Modell.")
    body_layer = layer("body3d", f"Footprint {spec.name}, 3D-Körper")
    bodies: list[dict[str, Any]] = []
    for i, b in enumerate(bodies_src):
        where = f"Footprint {spec.name}, 3D-Körper {i + 1}"
        if len(b.outline) < 3:
            issues.add(f"{where}: Umriss braucht mindestens 3 Punkte.")
        if b.z_top <= b.z_bottom:
            issues.add(f"{where}: Oberkante ({b.z_top}) muss über der Unterkante ({b.z_bottom}) liegen.")
        if not 0 <= b.opacity <= 1:
            issues.add(f"{where}: Deckkraft muss zwischen 0 und 1 liegen.")
        issues.extend(free_text_issues(b.name, where, "Name"))
        bodies.append(
            {
                "overall_height": _r(b.z_top),
                "standoff_height": _r(b.z_bottom),
                "layer": body_layer,
                "outline": [_pt(p.x, p.y) for p in b.outline],
                "body_color_3d": _color(b.color, DEFAULT_BODY_COLOR, issues, where),
                "body_opacity_3d": _r(b.opacity, 4),
                "name": b.name or "Body",
            }
        )
    issues.raise_if_any()
    description = latin1_text(spec.description or "")
    if description != (spec.description or "") and notes is not None:
        notes.append(f"Footprint {spec.name}: Beschreibung in Latin-1 umgeschrieben ({description!r}).")
    out: dict[str, Any] = {"name": spec.name, "description": description, "pads": pads}
    for key, items in (
        ("tracks", tracks),
        ("arcs", arcs),
        ("regions", regions),
        ("text", texts),
        ("component_bodies", bodies),
    ):
        if items:
            out[key] = items
    return out


def step_body(
    spec: FootprintSpec,
    layer_map: LayerMap | None,
    model_id: str,
    model_name: str,
) -> dict[str, Any]:
    """Component body that references an embedded STEP model, with the real height."""
    if spec.step is None:
        raise ValueError("Footprint hat kein STEP-Modell")
    heights = [b.z_top for b in spec.bodies]
    height = spec.height if spec.height else (max(heights) if heights else 0.0)
    standoff = min((b.z_bottom for b in spec.bodies), default=0.0)
    if spec.bodies:
        xs = [p.x for b in spec.bodies for p in b.outline]
        ys = [p.y for b in spec.bodies for p in b.outline]
        x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    else:
        x1, y1, x2, y2 = spec.bbox({"copper"})
    rot = spec.step.rotation
    off = spec.step.offset
    return {
        "overall_height": _r(height),
        "standoff_height": _r(standoff),
        "layer": L.logical_to_altium("body3d", layer_map),
        "outline": [_pt(x1, y1), _pt(x2, y1), _pt(x2, y2), _pt(x1, y2)],
        "embedded": True,
        "model_id": model_id,
        "model_name": model_name,
        "rotation_x": _r(rot[0], 4),
        "rotation_y": _r(rot[1], 4),
        "rotation_z": _r(rot[2], 4),
        "model_2d_x": _r(off[0]),
        "model_2d_y": _r(off[1]),
        "z_offset": _r(off[2]),
        "body_color_3d": DEFAULT_BODY_COLOR,
        "body_opacity_3d": 1.0,
    }


def _pad_from_rust(raw: Mapping[str, Any]) -> Pad:
    width = _num(raw.get("width"), 0.0)
    height = _num(raw.get("height"), 0.0)
    token = str(raw.get("shape", "rounded_rectangle")).lower().replace("-", "_")
    if token in ("rectangle", "rectangular", "rect"):
        shape = "rect"
    elif token in ("rounded_rectangle", "roundrect"):
        shape = "roundrect"
    elif token in ("round", "circle", "oval"):
        shape = "circle" if abs(width - height) < 1e-6 else "oval"
    elif token in ("octagonal", "octagon"):
        shape = "octagon"
    else:
        shape = "rect"
    hole = _num(raw.get("hole_size"), 0.0)
    side = L.pad_side(str(raw.get("layer", L.TOP_LAYER)), has_hole=hole > 0)
    hole_length = None
    if raw.get("hole_shape") == "slot" and _num(raw.get("hole_slot_length")) > 0:
        hole_length = _r(_num(raw.get("hole_slot_length")))
    paste = True
    paste_expansion = None
    if raw.get("paste_mask_expansion_mode") == "manual" and _is_num(raw.get("paste_mask_expansion")):
        value = float(raw["paste_mask_expansion"])
        if side != "through" and value <= -(min(width, height) / 2.0) + 1e-4:
            paste = False
        else:
            paste_expansion = _r(value)
    mask_expansion = None
    if raw.get("solder_mask_expansion_mode") == "manual" and _is_num(raw.get("solder_mask_expansion")):
        mask_expansion = _r(float(raw["solder_mask_expansion"]))
    corner = None
    if shape == "roundrect" and _is_num(raw.get("corner_radius_percent")):
        corner = int(raw["corner_radius_percent"])
    return Pad(
        designator=str(raw.get("designator", "")),
        x=_r(_num(raw.get("x"))),
        y=_r(_num(raw.get("y"))),
        width=_r(width),
        height=_r(height),
        shape=shape,  # type: ignore[arg-type]
        rotation=_r(_num(raw.get("rotation")), 4),
        corner_radius_pct=corner,
        side=side,
        hole=_r(hole) if hole > 0 else None,
        hole_length=hole_length,
        plated=bool(raw.get("is_plated", True)),
        paste=paste,
        paste_expansion=paste_expansion,
        mask_expansion=mask_expansion,
    )


def _is_model_body(body: Mapping[str, Any]) -> bool:
    raw = body.get("model_name")
    name = raw if isinstance(raw, str) else ""
    return bool(body.get("embedded") or body.get("model_id") or name.strip())


def step_source(data: Mapping[str, Any]) -> tuple[str | None, str] | None:
    """Origin of the ``spec.step`` that :func:`rust_to_footprint` creates for a footprint.

    ``(model_id, model_name)`` of the first component body with a 3D model – ``model_id``
    is ``None`` when the model is not embedded in the library (a linked file) – or
    ``None`` if the footprint has no such body.
    """
    for body in data.get("component_bodies") or []:
        if isinstance(body, dict) and _is_model_body(body):
            raw_name = body.get("model_name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            raw_id = body.get("model_id")
            model_id = raw_id.strip() if isinstance(raw_id, str) else ""
            embedded = body.get("embedded") is not False and bool(model_id)
            return (model_id if embedded else None), (name or "model.step")
    return None


def rust_to_footprint(
    data: Mapping[str, Any],
    layer_map: LayerMap | None = None,
    *,
    notes: list[str] | None = None,
    records: pcbrecords.FootprintRecords | None = None,
) -> FootprintSpec:
    """Convert a ``read_pcblib``/``get_component`` footprint into a :class:`FootprintSpec`.

    Layers are mapped back through the workspace :class:`LayerMap` (Rust aliases such as
    ``Bottom Courtyard`` = Mechanical 5 included); primitives on unmapped layers are
    skipped. The first body with a 3D model becomes ``spec.step`` with the **model name**
    as ``file`` (this pure conversion cannot extract embedded data – the
    :class:`RustLibraryOps` read methods replace it with a resolvable path, see
    :func:`step_source`); extruded bodies become :class:`Body3D`. Everything a
    write-back would lose (vias, unmapped layers, pad stacks, cutouts, TrueType texts,
    further 3D models, …) is reported in ``notes``. ``records`` (:func:`pcbrecords.read_footprints`) give the
    text extents Altium measured, so TrueType texts keep their exact reference point.
    """
    name = str(data.get("name", ""))
    boxes: list[tuple[float, float]] = []
    raw_texts = [t for t in data.get("text") or [] if isinstance(t, dict)]
    if records is not None:
        record_texts = records.of_kind("text")
        if len(record_texts) == len(raw_texts):
            boxes = [prim.text_box for prim in record_texts]
    skipped: dict[str, int] = {}
    losses: list[str] = []

    def logical(layer_name: Any, prefer: Sequence[str] = ()) -> str | None:
        result = L.altium_to_logical(str(layer_name), layer_map, prefer=prefer)
        if result is None:
            skipped[str(layer_name)] = skipped.get(str(layer_name), 0) + 1
        return result

    raw_pads = [p for p in data.get("pads") or [] if isinstance(p, dict)]
    pads = [_pad_from_rust(p) for p in raw_pads]
    stacked = sum(1 for p in raw_pads if str(p.get("stack_mode") or "simple") != "simple")
    if stacked:
        losses.append(f"Pad-Stapel (Top/Mitte/Bottom) bei {stacked} Pad(s) werden vereinfacht")
    square = sum(1 for p in raw_pads if p.get("hole_shape") == "square")
    if square:
        losses.append(f"quadratische Bohrungen ({square}) werden rund")
    tracks: list[Track] = []
    for t in data.get("tracks") or []:
        if isinstance(t, dict) and (lay := logical(t.get("layer"))):
            tracks.append(
                Track(
                    layer=lay,  # type: ignore[arg-type]
                    x1=_r(_num(t.get("x1"))),
                    y1=_r(_num(t.get("y1"))),
                    x2=_r(_num(t.get("x2"))),
                    y2=_r(_num(t.get("y2"))),
                    width=_r(_num(t.get("width"))),
                )
            )
    arcs: list[Arc] = []
    for a in data.get("arcs") or []:
        if isinstance(a, dict) and (lay := logical(a.get("layer"))):
            arcs.append(
                Arc(
                    layer=lay,  # type: ignore[arg-type]
                    cx=_r(_num(a.get("x"))),
                    cy=_r(_num(a.get("y"))),
                    r=_r(_num(a.get("radius"))),
                    start=_r(_num(a.get("start_angle")), 4),
                    end=_r(_num(a.get("end_angle"), 360.0), 4),
                    width=_r(_num(a.get("width"))),
                )
            )
    regions: list[Region] = []
    cutouts = 0
    for rg in data.get("regions") or []:
        if not isinstance(rg, dict):
            continue
        if str(rg.get("kind", "copper")).lower() not in ("copper", "0"):
            cutouts += 1  # board/polygon cutouts are not filled areas
            continue
        if lay := logical(rg.get("layer")):
            pts = [Point(x=_r(p.x), y=_r(p.y)) for p in _points(rg.get("vertices"))]
            if len(pts) >= 3:
                regions.append(Region(layer=lay, points=pts))  # type: ignore[arg-type]
    if cutouts:
        losses.append(f"Aussparungen ({cutouts})")
    for fill in data.get("fills") or []:
        if isinstance(fill, dict) and (lay := logical(fill.get("layer", L.TOP_LAYER))):
            x1, y1, x2, y2 = (_num(fill.get(k)) for k in ("x1", "y1", "x2", "y2"))
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            angle = math.radians(_num(fill.get("rotation")))
            corners = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            pts = []
            for x, y in corners:
                dx, dy = x - cx, y - cy
                pts.append(
                    Point(
                        x=_r(cx + dx * math.cos(angle) - dy * math.sin(angle)),
                        y=_r(cy + dx * math.sin(angle) + dy * math.cos(angle)),
                    )
                )
            regions.append(Region(layer=lay, points=pts))  # type: ignore[arg-type]
    if data.get("vias") and notes is not None:
        notes.append(f"Footprint {name}: {len(data['vias'])} Durchkontaktierung(en) werden nicht übernommen.")
    texts: list[FpText] = []
    special_texts = 0
    for index, tx in enumerate(raw_texts):
        if not isinstance(tx.get("text"), str):
            continue
        kind = str(tx.get("kind") or "stroke")
        if kind not in ("stroke", "true_type"):
            special_texts += 1
        content = tx["text"]
        prefer = ("designator",) if content == ".Designator" else ("comment",) if content == ".Comment" else ()
        lay = logical(tx.get("layer"), prefer)
        if not lay:
            continue
        justify = _justify(tx.get("justification"))
        height = _num(tx.get("height"), 1.0)
        rotation = _num(tx.get("rotation"))
        x, y = _num(tx.get("x")), _num(tx.get("y"))
        font_name: str | None = None
        if kind == "true_type":  # stored location: lower left corner of the measured text box
            font_name = str(tx.get("font_name") or TRUETYPE_DEFAULT_FONT)
            box = truetype_text_box(content, height, font_name)
            stored = boxes[index] if index < len(boxes) else (0.0, 0.0)
            if _plausible_box(stored, box):  # measured by Altium (the Rust writer stores its own estimate)
                box = stored
            x, y = truetype_text_reference(box, x, y, rotation, justify)
        elif kind == "stroke":  # stored location is the bottom-left anchor
            x, y = stroke_text_reference(content, x, y, height, rotation, justify)
        texts.append(
            FpText(
                layer=lay,  # type: ignore[arg-type]
                x=_r(x),
                y=_r(y),
                text=content,
                height=_r(height),
                stroke=_r(_num(tx.get("stroke_width"), 0.1016)),
                rotation=_r(rotation, 4),
                justify=justify,
                font="truetype" if kind == "true_type" else "stroke",
                font_name=font_name,
            )
        )
    if special_texts:
        losses.append(f"Barcode-Texte ({special_texts}) werden als Strichschrift übernommen")
    bodies: list[Body3D] = []
    step: StepModel | None = None
    heights: list[float] = []
    extra_models = 0
    for body in data.get("component_bodies") or []:
        if not isinstance(body, dict):
            continue
        overall = _num(body.get("overall_height"))
        standoff = _num(body.get("standoff_height"))
        if overall > 0:
            heights.append(overall)
        raw_model = body.get("model_name")
        model_name = raw_model if isinstance(raw_model, str) else ""
        if _is_model_body(body):
            if step is not None:
                extra_models += 1
            else:
                step = StepModel(
                    file=model_name.strip() or "model.step",
                    rotation=(
                        _r(_num(body.get("rotation_x")), 4),
                        _r(_num(body.get("rotation_y")), 4),
                        _r(_num(body.get("rotation_z")), 4),
                    ),
                    offset=(
                        _r(_num(body.get("model_2d_x"))),
                        _r(_num(body.get("model_2d_y"))),
                        _r(_num(body.get("z_offset"))),
                    ),
                )
            continue
        outline = [Point(x=_r(p.x), y=_r(p.y)) for p in _points(body.get("outline"))]
        if len(outline) < 3:
            continue
        bodies.append(
            Body3D(
                name=(str(body.get("name") or "").strip() or "Body"),
                outline=outline,
                z_bottom=_r(standoff),
                z_top=_r(overall),
                color=bgr_to_hex(body.get("body_color_3d", DEFAULT_BODY_COLOR)),
                opacity=_r(min(1.0, max(0.0, _num(body.get("body_opacity_3d"), 1.0))), 4),
            )
        )
    if extra_models:
        losses.append(f"weitere 3D-Modelle ({extra_models})")
    model_3d = data.get("model_3d")
    if step is None and isinstance(model_3d, dict):
        path = model_3d.get("filepath")
        if isinstance(path, str) and path.strip():
            step = StepModel(file=path.strip())
    if skipped and notes is not None:
        notes.append(
            f"Footprint {name}: Elemente auf nicht zugeordneten Lagen ausgelassen: "
            + ", ".join(f"{k} ({v})" for k, v in sorted(skipped.items()))
        )
    if losses and notes is not None:
        notes.append(f"Footprint {name}: nicht übernommen: " + "; ".join(losses) + ".")
    return FootprintSpec(
        name=name,
        description=str(data.get("description") or ""),
        height=_r(max(heights)) if heights else None,
        pads=pads,
        tracks=tracks,
        arcs=arcs,
        regions=regions,
        texts=texts,
        bodies=bodies,
        step=step,
    )


def fix_points(component: Mapping[str, Any]) -> dict[str, Any]:
    """Copy of a read-back component with every point list in write format ``[{x, y}]``.

    Fixes the silent loss of polygons/polylines on a symbol read-modify-write and the
    ``[[x, y]]`` outlines of component bodies.
    """
    out = copy.deepcopy(dict(component))

    def convert(points: Any) -> Any:
        if not isinstance(points, list):
            return points
        return [{"x": p[0], "y": p[1]} if isinstance(p, (list, tuple)) and len(p) >= 2 else p for p in points]

    for key in ("polygons", "polylines"):
        for prim in out.get(key) or []:
            if isinstance(prim, dict) and "points" in prim:
                prim["points"] = convert(prim["points"])
    for body in out.get("component_bodies") or []:
        if isinstance(body, dict) and "outline" in body:
            body["outline"] = convert(body["outline"])
    for region in out.get("regions") or []:
        if isinstance(region, dict) and "vertices" in region:
            region["vertices"] = convert(region["vertices"])
    return out


def update_symbol_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Symbol payload for ``update_component``.

    ``update_component`` ignores ``designator_prefix`` and drops the designator unless
    the read-format key ``designator`` (``"R?"``) is given (VERIFIED 2026-10-07); point
    lists are converted to the write format as well.
    """
    out = fix_points(payload)
    prefix = out.get("designator_prefix")
    if isinstance(prefix, str) and prefix and "designator" not in out:
        out["designator"] = f"{prefix}?"
    return out


# --------------------------------------------------------------------------- backups

_BAK_TS_RE: Final = re.compile(r"^\d{8}_\d{6}$")


def writer_backups(library: Path) -> list[Path]:
    """``<lib>.<YYYYMMDD_HHMMSS>.bak`` files the writer created beside ``library``."""
    folder = library.parent
    if not folder.is_dir():
        return []
    prefix = library.name.lower() + "."
    found: list[Path] = []
    for entry in folder.iterdir():
        lower = entry.name.lower()
        if not entry.is_file() or not lower.startswith(prefix) or not lower.endswith(".bak"):
            continue
        stamp = entry.name[len(library.name) + 1 : -4]
        if _BAK_TS_RE.match(stamp):
            found.append(entry)
    return sorted(found)


def library_backups(library: Path, folder: Path) -> list[Path]:
    """Every ``<lib>.*.bak`` backup of ``library`` in ``folder`` (oldest first)."""
    if not folder.is_dir():
        return []
    prefix = library.name.lower() + "."
    found = [
        entry
        for entry in folder.iterdir()
        if entry.is_file() and entry.name.lower().startswith(prefix) and entry.name.lower().endswith(".bak")
    ]

    def age(entry: Path) -> tuple[float, str]:
        try:
            return entry.stat().st_mtime, entry.name
        except OSError:
            return 0.0, entry.name

    return sorted(found, key=age)


def prune_backups(library: Path, folder: Path, keep: int) -> None:
    """Delete all but the ``keep`` newest backups of ``library`` in ``folder``."""
    if keep <= 0:
        return
    for old in library_backups(library, folder)[:-keep]:
        with contextlib.suppress(OSError):
            old.unlink()


def store_backup(source: Path, library: Path, folder: Path, *, keep: int = 20, move: bool = False) -> Path:
    """Store ``source`` – the content of ``library`` before an operation – as a backup.

    The file is named ``<lib>.<YYYYMMDD_HHMMSS_mmm>.bak`` (millisecond stamp, never
    overwritten) and gets the current time as modification time; only the ``keep``
    newest backups of the library are kept in ``folder``.
    """
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    dest = folder / f"{library.name}.{stamp}.bak"
    counter = 1
    while dest.exists():
        dest = folder / f"{library.name}.{stamp}_{counter}.bak"
        counter += 1
    if move:
        shutil.move(str(source), str(dest))
    else:
        shutil.copyfile(source, dest)
    os.utime(dest)
    prune_backups(library, folder, keep)
    return dest


def relocate_backups(
    library: Path,
    target_dir: Path,
    *,
    keep: int = 20,
    only: Iterable[Path] | None = None,
) -> list[Path]:
    """Move the writer's ``.bak`` files of ``library`` (or just ``only``) to ``target_dir``.

    Only for backups that hold a real earlier state (e.g. left by a writer run outside
    PartForge); :class:`RustLibraryOps` deletes the ``.bak`` files written *during* its
    own multi-call operations and keeps its snapshot of the pre-operation state instead.
    """
    moved: list[Path] = []
    backups = writer_backups(library)
    if only is not None:
        wanted = {_norm(path) for path in only}
        backups = [bak for bak in backups if _norm(bak) in wanted]
    if not backups:
        return moved
    target_dir.mkdir(parents=True, exist_ok=True)
    for bak in backups:
        dest = target_dir / bak.name
        counter = 1
        while dest.exists():
            dest = target_dir / f"{bak.stem}.{counter}{bak.suffix}"
            counter += 1
        try:
            shutil.move(str(bak), str(dest))
            moved.append(dest)
        except OSError as exc:
            log.warning("Sicherung %s konnte nicht verschoben werden: %s", bak, exc)
    prune_backups(library, target_dir, keep)
    return moved


#: Working copies (``<stem>.pfwork<hex8><suffix>``) older than this are leftovers of a crashed process.
WORK_COPY_MAX_AGE_S: Final = 3600.0
#: Tag of the working copy of a library mutation (see :class:`_LibraryTransaction`).
WORK_TAG: Final = "pfwork"


def _file_state(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _same_content(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size and filecmp.cmp(a, b, shallow=False)
    except OSError:
        return False


def result_library(result: WriteResult) -> str:
    """File name of the library a result is about (for warnings written during a working-copy operation)."""
    return Path(result.library).name


def file_access_message(library: Path, exc: OSError, *, action: str = "geschrieben") -> str:
    """German message for an OS error on a library file – outcome first (a clipped toast keeps it), no
    Python repr of the path, no English OS text for the common cases."""
    name = library.name
    if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32, 33):
        return (
            f"{name} wurde nicht {action} – die Bibliothek ist unverändert: Die Datei ist von einem anderen Programm "
            "geöffnet oder schreibgeschützt (z. B. in Altium mit ungespeicherten Änderungen). Datei schließen und "
            "erneut versuchen."
        )
    if isinstance(exc, FileNotFoundError):
        return f"{name} wurde nicht {action} – die Datei oder ihr Ordner wurde nicht gefunden."
    detail = (exc.strerror or "").strip() or type(exc).__name__
    return f"{name} wurde nicht {action} – die Bibliothek ist unverändert ({detail})."


class LibraryLocked(RustWriterError):
    """Another PartForge process writes the library and did not finish in time (German message)."""


#: How long a library mutation waits for another process (PartForge window) that writes the same file.
LIBRARY_LOCK_TIMEOUT_S: Final = 300.0
#: Hidden lock file in every library folder (one byte-range lock per library file, see :class:`LibraryLock`).
LOCK_FILE_NAME: Final = ".partforge-lock"
_LOCKFILE_EXCLUSIVE_LOCK: Final = 0x2
_LOCKFILE_FAIL_IMMEDIATELY: Final = 0x1


class _OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", ctypes.c_uint32),
        ("OffsetHigh", ctypes.c_uint32),
        ("hEvent", ctypes.c_void_p),
    ]


def _kernel32() -> Any:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LockFileEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                               ctypes.POINTER(_OVERLAPPED)]
    k32.LockFileEx.restype = ctypes.c_int
    k32.UnlockFileEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
                                 ctypes.POINTER(_OVERLAPPED)]
    k32.UnlockFileEx.restype = ctypes.c_int
    k32.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    k32.SetFileAttributesW.restype = ctypes.c_int
    return k32


class _ProcessLock:
    """Exclusive lock of one library file between processes: a byte-range lock (``LockFileEx``) at an offset
    derived from the file name in the hidden lock file of the library's folder. Works across processes and
    machines (SMB shares); the operating system releases it when the process ends – also after a crash."""

    def __init__(self, library: Path):
        self.library = library
        self._fd: int | None = None
        self._overlapped: _OVERLAPPED | None = None

    def _offset(self) -> int:
        return int(hashlib.sha1(self.library.name.casefold().encode("utf-8")).hexdigest()[:12], 16)

    def acquire(self, timeout: float) -> bool:
        """``True`` when held (or when no lock file can be used – then only the process lock applies);
        ``False`` after ``timeout`` seconds."""
        if os.name != "nt":  # pragma: no cover - PartForge runs on Windows
            return True
        import msvcrt

        folder = self.library.parent
        lock_file = folder / LOCK_FILE_NAME
        try:
            folder.mkdir(parents=True, exist_ok=True)
            new = not lock_file.exists()
            fd = os.open(lock_file, os.O_RDWR | os.O_CREAT | os.O_BINARY | os.O_NOINHERIT)
        except OSError as exc:
            log.warning("Sperrdatei %s nicht nutzbar (%s) – nur prozessinterne Sperre", lock_file, exc)
            return True
        k32 = _kernel32()
        if new:
            k32.SetFileAttributesW(str(lock_file), 0x2)  # FILE_ATTRIBUTE_HIDDEN
        handle = msvcrt.get_osfhandle(fd)
        offset = self._offset()
        overlapped = _OVERLAPPED(0, 0, offset & 0xFFFFFFFF, offset >> 32, None)
        deadline = time.monotonic() + max(0.0, timeout)
        waited = False
        while True:
            if k32.LockFileEx(handle, _LOCKFILE_EXCLUSIVE_LOCK | _LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0,
                              ctypes.byref(overlapped)):
                self._fd, self._overlapped = fd, overlapped
                if waited:
                    log.info("Bibliothek %s: Sperre nach Wartezeit erhalten", self.library)
                return True
            error = ctypes.get_last_error()
            if error not in (33, 158):  # ERROR_LOCK_VIOLATION, ERROR_NOT_LOCKED: another holder
                log.warning("Sperre für %s nicht setzbar (Fehler %s) – nur prozessinterne Sperre", self.library, error)
                os.close(fd)
                return True
            if time.monotonic() >= deadline:
                os.close(fd)
                return False
            if not waited:
                waited = True
                log.info("Bibliothek %s wird von einem anderen Prozess geschrieben – warte", self.library)
            time.sleep(0.05)

    def release(self) -> None:
        fd, overlapped = self._fd, self._overlapped
        self._fd, self._overlapped = None, None
        if fd is None or overlapped is None:
            return
        import msvcrt

        try:
            _kernel32().UnlockFileEx(msvcrt.get_osfhandle(fd), 0, 1, 0, ctypes.byref(overlapped))
        finally:
            os.close(fd)


class LibraryLock:
    """Reentrant lock of one library file for multi-call operations (``with library_lock(path): …``).

    Serialises the threads of this process (``RLock``) **and** other processes – a second PartForge window, a
    tool on the same library or another machine on a shared folder (:class:`_ProcessLock`). The process-wide
    part is taken by the outermost acquisition of a thread and released with it. Waits at most
    :data:`LIBRARY_LOCK_TIMEOUT_S` for another process, then raises :class:`LibraryLocked`."""

    def __init__(self, library: Path):
        self.library = library
        self._rlock = threading.RLock()
        self._depth = 0
        self._process: _ProcessLock | None = None

    def acquire(self, timeout: float | None = None) -> None:
        self._rlock.acquire()
        if self._depth == 0:
            process = _ProcessLock(self.library)
            try:
                held = process.acquire(LIBRARY_LOCK_TIMEOUT_S if timeout is None else timeout)
            except BaseException:
                self._rlock.release()
                raise
            if not held:
                self._rlock.release()
                raise LibraryLocked(
                    f"{self.library.name} wurde nicht geschrieben – die Bibliothek ist unverändert: Ein anderes "
                    "PartForge-Fenster (oder ein anderer Rechner) schreibt gerade in diese Datei. Bitte später erneut "
                    "versuchen."
                )
            self._process = process
        self._depth += 1

    def release(self) -> None:
        self._depth -= 1
        if self._depth == 0 and self._process is not None:
            process, self._process = self._process, None
            try:
                process.release()
            except OSError as exc:  # the OS releases it with the handle anyway
                log.warning("Sperre für %s nicht freigegeben: %s", self.library, exc)
        self._rlock.release()

    def __enter__(self) -> LibraryLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


_library_locks: dict[str, LibraryLock] = {}
_library_locks_guard = threading.Lock()


def library_lock(path: Path) -> LibraryLock:
    """The lock serialising multi-call operations on one library file – within this process and against
    other processes (:class:`LibraryLock`). Keyed by the real path: two spellings of one file (junction, mapped
    drive) share the lock – a second one would wait for this process's own file lock."""
    try:
        key = _norm(os.path.realpath(os.fspath(path)))
    except (OSError, ValueError):
        key = _norm(path)
    with _library_locks_guard:
        lock = _library_locks.get(key)
        if lock is None:
            lock = _library_locks[key] = LibraryLock(Path(os.path.abspath(os.fspath(path))))
        return lock


def work_copy_files(library: Path) -> list[Path]:
    """Working copies of ``library`` (``<stem>.pfwork<hex8><suffix>``) and the writer's ``.bak`` files of them."""
    folder = library.parent
    if not folder.is_dir():
        return []
    prefix = f"{library.stem}.{WORK_TAG}".lower()
    return sorted(p for p in folder.iterdir() if p.is_file() and p.name.lower().startswith(prefix))


class _LibraryTransaction:
    """One atomic library mutation (any number of writer calls) on a **working copy** with a correct backup.

    * Enter (under :func:`library_lock`): leftovers of a crashed operation on this library are removed; the
      library is copied to ``<stem>.pfwork<hex8><suffix>`` beside it (``target``) – every writer call and
      every check of the operation works on that copy; the library itself stays untouched.
    * Exception: the working copy is discarded – the library is unchanged (``restored`` stays True); the
      exception propagates.
    * Exit: the copy replaces the library in **one** ``os.replace`` (a crash at any point leaves either the
      old or the new complete file – never a half-written one); before that the old file is stored as
      ``<lib>.<YYYYMMDD_HHMMSS_mmm>.bak`` (the true state before the operation) when it changed. The backup
      folder is ``<workspace>/Backups/lib``, or the library's own folder outside the workspace. The writer's
      ``.bak`` files of the copy are deleted; older ``.bak`` files of the library (writer used outside
      PartForge) are moved to the backup folder.
    """

    def __init__(self, library: Path, backup_dir: Path | None, keep: int, result: WriteResult):
        self.library = library
        self.backup_dir = backup_dir
        self.keep = keep
        self.result = result
        self.existed = False
        self.target = library.with_name(f"{library.stem}.{WORK_TAG}{uuid.uuid4().hex[:8]}{library.suffix}")
        self.restored = True
        self.backup: Path | None = None
        self._baks_before: dict[str, tuple[int, int] | None] = {}

    def __enter__(self) -> _LibraryTransaction:
        for leftover in work_copy_files(self.library):  # we hold the library lock: nobody else works on it
            with contextlib.suppress(OSError):
                leftover.unlink()
                log.warning("Übrig gebliebene Arbeitskopie %s entfernt", leftover.name)
        self._baks_before = {_norm(bak): _file_state(bak) for bak in writer_backups(self.library)}
        self.existed = self.library.exists()
        if self.existed:
            try:
                shutil.copyfile(self.library, self.target)
            except OSError as exc:
                self._discard()
                raise RustWriterError(file_access_message(self.library, exc)) from exc
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object) -> None:
        if exc_type is not None:
            self._discard()
            return
        try:
            self._commit()
        except OSError as error:
            self._discard()
            raise RustWriterError(file_access_message(self.library, error)) from error

    def _discard(self) -> None:
        """Remove the working copy and the writer's ``.bak`` files of it (the library is untouched)."""
        for path in [self.target, *writer_backups(self.target)]:
            with contextlib.suppress(OSError):
                path.unlink()

    def _commit(self) -> None:
        if not self.target.exists():  # nothing was written
            self._discard()
            return
        for bak in writer_backups(self.target):  # intermediate states of the operation
            with contextlib.suppress(OSError):
                bak.unlink()
        folder = self.backup_dir or self.library.parent
        changed = not (self.existed and _same_content(self.library, self.target))
        if changed and self.existed:
            try:
                self.backup = store_backup(self.library, self.library, folder, keep=self.keep)
            except OSError as exc:
                log.warning("Sicherung von %s unvollständig: %s", self.library, exc)
                self.result.warnings.append(
                    f"Die Sicherung der Bibliothek {self.library.name} ist unvollständig ({exc.strerror or exc})."
                )
        if changed:
            try:
                os.replace(self.target, self.library)
            except OSError:
                if self.backup is not None:  # nothing changed: no backup of this attempt
                    with contextlib.suppress(OSError):
                        self.backup.unlink()
                    self.backup = None
                raise
        else:
            self._discard()
        self._settle_writer_backups()

    def _settle_writer_backups(self) -> None:
        """Older ``.bak`` files the writer left beside the library (runs outside PartForge) go to the backup
        folder; ones that appeared during the operation are removed."""
        try:
            for bak in writer_backups(self.library):
                key = _norm(bak)
                if key in self._baks_before and self._baks_before[key] == _file_state(bak):
                    if self.backup_dir is not None:
                        relocate_backups(self.library, self.backup_dir, keep=self.keep, only=[bak])
                    continue
                bak.unlink()
        except OSError as exc:
            log.warning("Sicherungen von %s nicht aufgeräumt: %s", self.library, exc)


# --------------------------------------------------------------------------- STEP cache

_UNSAFE_FILE_CHARS: Final = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
STEP_CACHE_MAX_AGE_S: Final = 30 * 86400.0
_step_cache_lock = threading.Lock()


def step_cache_dir() -> Path:
    """Cache of STEP models extracted from libraries (inside the writer sandbox)."""
    path = temp_dir() / "step-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prune_step_cache(max_age_s: float = STEP_CACHE_MAX_AGE_S) -> None:
    root = temp_dir() / "step-cache"
    now = time.time()
    for entry in root.iterdir() if root.is_dir() else []:
        with contextlib.suppress(OSError):
            if entry.is_dir() and now - entry.stat().st_mtime > max_age_s:
                shutil.rmtree(entry, ignore_errors=True)


def _model_folder(model_id: str) -> str:
    token = re.sub(r"[^0-9A-Za-z]", "", model_id)[:40]
    return token or hashlib.sha1(model_id.encode("utf-8")).hexdigest()[:16]


def _step_file_name(name: str) -> str:
    """File-system-safe ``.step``/``.stp`` file name for an embedded model name."""
    base = _UNSAFE_FILE_CHARS.sub("_", name.replace("\\", "/").rsplit("/", 1)[-1]).strip().rstrip(". ")
    if not base:
        base = "model.step"
    if Path(base).suffix.lower() not in (".step", ".stp"):
        base += ".step"
    return base


def _find_identical_file(folder: Path, data: bytes) -> Path | None:
    """A ``.step``/``.stp`` file below ``folder`` with exactly ``data`` as content."""
    if not folder.is_dir():
        return None
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() not in (".step", ".stp"):
            continue
        with contextlib.suppress(OSError):
            if path.is_file() and path.stat().st_size == len(data) and path.read_bytes() == data:
                return path
    return None


def _place_step(extracted: Path, model_name: str, workspace: Workspace | None) -> str:
    """``StepModel.file`` for an extracted model (see :meth:`RustLibraryOps._materialize_steps`)."""
    if workspace is None:
        return str(extracted)
    data = extracted.read_bytes()
    models = workspace.models_dir
    name = _step_file_name(model_name)
    target = models / name
    if not (target.is_file() and target.read_bytes() == data):
        match = _find_identical_file(models, data)
        if match is not None:
            target = match
        else:
            if target.exists():  # another model with the same name: content-hash suffix
                stem, suffix = Path(name).stem, Path(name).suffix
                target = models / f"{stem}_{hashlib.sha256(data).hexdigest()[:8]}{suffix}"
            if not (target.is_file() and target.read_bytes() == data):
                models.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, target)
                log.info("Eingebettetes STEP-Modell nach %s übernommen", target)
    try:
        return target.resolve().relative_to(workspace.root).as_posix()
    except ValueError:
        return str(target)


# --------------------------------------------------------------------------- operations


class RustLibraryOps:
    """Library operations on top of :class:`RustMcpClient` (upsert, full write, read, delete).

    ``workspace``/``layer_map``/styles default to the currently open workspace. The
    sandbox always contains the workspace root and :func:`temp_dir`; libraries outside it
    are rejected for writing and read through a temporary copy.

    Write operations (all serialised per library file):

    1. strict validation of every payload (:class:`RustValidationError`, nothing sent);
    2. upsert: ``component_exists``; new components in **one** append call, existing ones
       via ``update_component`` (keeps their position) or – from
       :data:`BATCH_UPDATE_THRESHOLD` updates on – one delete plus the same append call;
       STEP models are embedded through temporary carrier footprints;
    3. verification: names and pin echo of the response, stored ``primitive_order``,
       component metadata (pin/pad/primitive counts), validation issues and
       ``silk_over_pad`` warnings (-> ``WriteResult.warnings``);
    4. all or nothing: every call works on a working copy (:class:`_LibraryTransaction`); a
       writer error or a failed verification discards it – the library is untouched – and
       every component of the call is reported in ``WriteResult.errors``;
    5. backup: after a successful change the old file – the true state before the
       operation – is stored as ``<workspace>/Backups/lib/<lib>.<YYYYMMDD_HHMMSS_mmm>.bak``
       and the copy replaces the library in one ``os.replace``.

    Reading converts to the PartForge model; embedded STEP models are extracted to a
    resolvable file (workspace ``3D`` folder or PartForge's cache) so that a read
    footprint can be written back.
    """

    def __init__(
        self,
        *,
        client: RustMcpClient | None = None,
        exe: str | os.PathLike[str] | None = None,
        workspace: Workspace | None = None,
        layer_map: LayerMap | None = None,
        symbol_style: SymbolStyle | None = None,
        footprint_style: FootprintStyle | None = None,
        extra_dirs: Sequence[str | os.PathLike[str]] = (),
        backup_keep: int = 20,
        layer_stack: stackup.LayerStack | None = None,
    ):
        self._client_override = client
        self._exe = exe
        self._workspace = workspace
        self._layer_map = layer_map
        self._symbol_style = symbol_style
        self._footprint_style = footprint_style
        self._extra_dirs = [Path(os.path.abspath(os.fspath(d))) for d in extra_dirs]
        self._backup_keep = backup_keep
        self._layer_stack = layer_stack

    # -- context --------------------------------------------------------------------
    @property
    def workspace(self) -> Workspace | None:
        return self._workspace or current_or_none()

    def layer_map(self) -> LayerMap:
        if self._layer_map is not None:
            return self._layer_map
        ws = self.workspace
        return ws.settings.layers if ws else LayerMap()

    def symbol_style(self) -> SymbolStyle:
        if self._symbol_style is not None:
            return self._symbol_style
        ws = self.workspace
        return ws.settings.symbol if ws else SymbolStyle()

    def footprint_style(self) -> FootprintStyle:
        if self._footprint_style is not None:
            return self._footprint_style
        ws = self.workspace
        return ws.settings.footprint if ws else FootprintStyle()

    def layer_stack(self) -> tuple[stackup.LayerStack, list[str]]:
        """Mechanical layer stack written into every PcbLib header (with German notes).

        The workspace stack (``layer_stackup`` file or the built-in standard), with every
        layer the LayerMap writes to enabled (:func:`stackup.effective_stack`).
        """
        notes: list[str] = []
        if self._layer_stack is not None:
            stack = self._layer_stack
        else:
            stack, notes = stackup.workspace_stack(self.workspace)
        return stackup.effective_stack(stack, self.layer_map()), notes

    def allowed_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        ws = self.workspace
        if ws is not None:
            dirs.append(ws.root)
        dirs.append(temp_dir())
        dirs.extend(self._extra_dirs)
        return dirs

    def client(self) -> RustMcpClient:
        if self._client_override is not None:
            self._client_override.ensure_allowed(self.allowed_dirs())
            return self._client_override
        return get_client(exe=self._exe, allowed_dirs=self.allowed_dirs())

    def backups_dir(self, library: Path) -> Path | None:
        ws = self.workspace
        if ws is not None and is_inside(library, ws.root):
            return ws.backups_dir / "lib"
        return None

    # -- helpers --------------------------------------------------------------------
    def _check_library(self, library: str | os.PathLike[str], kind: Literal["schlib", "pcblib"]) -> Path:
        return validate_library_path(library, kind, allowed_dirs=self.allowed_dirs())

    def _readable(self, library: Path) -> Path:
        """Path the writer may read: the library itself or a temp copy outside the sandbox."""
        if any(is_inside(library, d) for d in self.allowed_dirs()):
            return library
        stat = library.stat()
        key = hashlib.sha1(f"{_norm(library)}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:16]
        target = temp_dir() / "read" / key / library.name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(library, target)
            self._prune_read_copies()
        return target

    @staticmethod
    def _prune_read_copies(max_age_s: float = 86400.0) -> None:
        root = temp_dir() / "read"
        now = time.time()
        for entry in root.iterdir() if root.is_dir() else []:
            with contextlib.suppress(OSError):
                if entry.is_dir() and now - entry.stat().st_mtime > max_age_s:
                    shutil.rmtree(entry, ignore_errors=True)

    def _resolve_step(self, step: StepModel) -> Path:
        raw = Path(step.file.replace("\\", "/"))
        if raw.is_absolute():
            path = raw
        else:
            ws = self.workspace
            if ws is None:
                raise RustValidationError(
                    [f"STEP-Datei {step.file!r} ist relativ angegeben, aber es ist kein Bibliotheksordner geöffnet."]
                )
            path = ws.root / raw
        if path.suffix.lower() not in (".step", ".stp"):
            raise RustValidationError([f"STEP-Datei {path.name}: erwartet .step oder .stp."])
        if not path.is_file():
            raise RustValidationError([f"STEP-Datei nicht gefunden: {path}"])
        path = Path(os.path.abspath(path))
        if any(is_inside(path, d) for d in self.allowed_dirs()):
            return path
        stat = path.stat()
        key = hashlib.sha1(f"{_norm(path)}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:16]
        target = temp_dir() / "step" / key / path.name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        return target

    def _transaction(self, library: Path, result: WriteResult) -> _LibraryTransaction:
        return _LibraryTransaction(library, self.backups_dir(library), self._backup_keep, result)

    @staticmethod
    def _rollback_note(tx: _LibraryTransaction) -> str:
        if tx.restored:
            return "Der Vorgang wurde zurückgesetzt – die Bibliothek ist unverändert."
        return "ACHTUNG: Die Bibliothek konnte nicht zurückgesetzt werden (siehe Hinweise)."

    @staticmethod
    def _raise_if_failed(result: WriteResult) -> None:
        """Turn problems found after writing into a rollback of the whole call."""
        if result.errors:
            raise _VerificationFailed(result.errors)

    def _fail(
        self,
        result: WriteResult,
        names: Sequence[str],
        tx: _LibraryTransaction,
        exc: RustWriterError,
        *,
        verb: str = "geschrieben",
    ) -> None:
        """Report a rolled-back operation: no component of the call was changed."""
        note = "" if "unverändert" in str(exc) else self._rollback_note(tx)
        result.written = []
        result.deleted = []
        if isinstance(exc, _VerificationFailed):
            log.error("Prüfung nach dem Schreiben in %s fehlgeschlagen: %s", tx.library, exc)
            failed = ", ".join(sorted(exc.errors))
            errors = {
                name: (
                    f"{exc.errors[name]} {note}"
                    if name in exc.errors
                    else f"Nicht {verb}, weil der Vorgang bei {failed} fehlgeschlagen ist. {note}"
                )
                for name in names
            }
            for name, message in exc.errors.items():
                errors.setdefault(name, f"{message} {note}")
            result.errors = errors
        else:
            log.error("Vorgang in %s fehlgeschlagen: %s", tx.library, exc)
            text = f"{exc} {note}".strip()
            result.errors = {name: text for name in names} or {tx.library.name: text}

    @staticmethod
    def _locked(result: WriteResult, names: Sequence[str], exc: LibraryLocked, *, verb: str = "geschrieben") -> None:
        """Another process holds the library: nothing of the call was changed."""
        result.written = []
        result.deleted = []
        text = str(exc) if verb == "geschrieben" else str(exc).replace("wurde nicht geschrieben", f"wurde nicht {verb}")
        result.errors = {name: text for name in names} or {Path(result.library).name: text}

    @staticmethod
    def _check_unique(names: Sequence[str]) -> None:
        seen: set[str] = set()
        dupes: list[str] = []
        for name in names:
            if name in seen and name not in dupes:
                dupes.append(name)
            seen.add(name)
        if dupes:
            raise RustValidationError([f"Name mehrfach in derselben Anfrage: {n}" for n in dupes])

    @staticmethod
    def _existing(client: RustMcpClient, library: Path, names: Sequence[str]) -> set[str]:
        if not library.exists() or not names:
            return set()
        resp = client.call_tool("component_exists", {"filepath": _posix(library), "component_names": list(names)})
        found: set[str] = set()
        for item in resp.get("results") or []:
            if isinstance(item, dict) and item.get("exists") is True and isinstance(item.get("name"), str):
                found.add(item["name"])
        return found

    @staticmethod
    def _metadata(client: RustMcpClient, library: Path) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        offset = 0
        while True:
            resp = client.call_tool(
                "list_components", {"filepath": _posix(library), "include_metadata": True, "offset": offset}
            )
            items = [c for c in resp.get("components") or [] if isinstance(c, dict) and isinstance(c.get("name"), str)]
            for item in items:
                out[item["name"]] = item
            if not resp.get("has_more") or not items:
                return out
            offset += len(items)

    @staticmethod
    def _collect_messages(resp: Mapping[str, Any], names: set[str], result: WriteResult) -> None:
        validation = resp.get("validation")
        if isinstance(validation, dict):
            for issue in validation.get("issues") or []:
                if not isinstance(issue, dict) or issue.get("component") not in names:
                    continue
                severity = "Fehler" if issue.get("severity") == "error" else "Hinweis"
                text = issue.get("issue") or issue.get("message") or ""
                result.warnings.append(f"{issue['component']}: Bibliotheksprüfung ({severity}): {text}")
        for warning in resp.get("warnings") or []:
            if isinstance(warning, dict):
                fp = warning.get("footprint")
                if fp not in names:
                    continue
                if warning.get("type") == "silk_over_pad":
                    result.warnings.append(
                        f"{fp}: Bestückungsdruck ({warning.get('layer', L.TOP_OVERLAY)}) überlappt Pad "
                        f"{warning.get('pad', '?')} – Abstand zum Pad prüfen."
                    )
                else:
                    result.warnings.append(f"{fp}: {warning.get('message') or warning.get('type') or warning}")
            elif isinstance(warning, str) and warning:
                result.warnings.append(warning)

    @staticmethod
    def _finish(result: WriteResult, started: float) -> WriteResult:
        result.warnings = list(dict.fromkeys(result.warnings))
        result.duration_s = round(time.perf_counter() - started, 3)
        return result

    # -- symbols --------------------------------------------------------------------
    def _symbol_payloads(self, specs: Sequence[SymbolSpec], notes: list[str]) -> list[dict[str, Any]]:
        self._check_unique([s.name for s in specs])
        issues = _Issues()
        payloads: list[dict[str, Any]] = []
        style = self.symbol_style()
        for spec in specs:
            try:
                payload = symbol_to_rust(spec, style, notes=notes)
            except RustValidationError as exc:
                issues.extend(exc.issues)
                continue
            issues.extend(validate_symbol_payload(payload))
            payloads.append(payload)
        issues.raise_if_any()
        return payloads

    def _verify_symbol_write(self, resp: Mapping[str, Any], payloads: Sequence[dict[str, Any]], result: WriteResult) -> None:
        names = set(resp.get("symbol_names") or [])
        geometry = {g.get("name"): g for g in resp.get("geometry") or [] if isinstance(g, dict)}
        for payload in payloads:
            name = payload["name"]
            if name not in names:
                result.errors[name] = "Symbol fehlt in der Antwort des Bibliotheks-Writers (nicht geschrieben)."
                continue
            echo = geometry.get(name)
            if echo is not None:
                count = len(echo.get("pins") or [])
                if count != len(payload["pins"]):
                    result.errors[name] = (
                        f"Pins wurden vom Bibliotheks-Writer verworfen: {len(payload['pins'])} gesendet, {count} geschrieben."
                    )
        self._collect_messages(resp, {p["name"] for p in payloads}, result)

    @staticmethod
    def _read_orders(client: RustMcpClient, library: Path) -> dict[str, list[str]]:
        orders: dict[str, list[str]] = {}
        offset = 0
        while True:
            resp = client.call_tool("read_schlib", {"filepath": _posix(library), "offset": offset})
            batch = [s for s in resp.get("symbols") or [] if isinstance(s, dict)]
            for symbol in batch:
                order = symbol.get("primitive_order")
                if isinstance(symbol.get("name"), str) and isinstance(order, list):
                    orders[symbol["name"]] = [str(t) for t in order]
            if not resp.get("has_more") or not batch:
                return orders
            offset += len(batch)

    def _verify_symbol_order(
        self, client: RustMcpClient, library: Path, payloads: Sequence[dict[str, Any]], result: WriteResult
    ) -> None:
        """The stored record order must equal the requested ``primitive_order`` (graphics first)."""
        wanted = {p["name"]: p["primitive_order"] for p in payloads if p.get("primitive_order")}
        if not wanted:
            return
        stored = self._read_orders(client, library)
        for payload in payloads:
            name = payload["name"]
            if name not in wanted or name in result.errors or stored.get(name) == wanted[name]:
                continue
            filled = any(
                item.get("filled", key != "ellipses")
                for key in ("rectangles", "round_rects", "polygons", "ellipses")
                for item in payload.get(key) or []
            )
            message = (
                "Die Zeichenreihenfolge wurde nicht übernommen – Pin-Namen können von der Körperfüllung verdeckt sein."
            )
            if filled:
                result.errors[name] = message
            else:
                result.warnings.append(f"{name}: {message}")

    def _verify_symbol_metadata(
        self, client: RustMcpClient, library: Path, payloads: Sequence[dict[str, Any]], result: WriteResult
    ) -> None:
        meta = self._metadata(client, library)
        for payload in payloads:
            name = payload["name"]
            if name in result.errors:
                continue
            item = meta.get(name)
            if item is None:
                result.errors[name] = "Symbol ist nach dem Schreiben nicht in der Bibliothek."
                continue
            pins = item.get("pin_count")
            if _is_int(pins) and pins != len(payload["pins"]):
                result.errors[name] = f"Nach dem Schreiben {pins} statt {len(payload['pins'])} Pins gelesen."
                continue
            parts = item.get("part_count")
            if _is_int(parts) and parts != payload.get("part_count", 1):
                result.errors[name] = f"Nach dem Schreiben {parts} statt {payload.get('part_count', 1)} Teile gelesen."
                continue
            expected = f"{payload.get('designator_prefix', 'U')}?"
            designator = item.get("designator")
            if isinstance(designator, str) and designator != expected:
                result.errors[name] = f"Bezeichner nach dem Schreiben {designator!r} statt {expected!r}."
                continue
            result.written.append(name)

    def upsert_symbols(self, library: str | os.PathLike[str], specs: Sequence[SymbolSpec]) -> WriteResult:
        """Create or replace the given symbols; other symbols of the library stay untouched.

        All or nothing: if one symbol fails (writer error or check after writing), the
        library is restored and every symbol of the call is reported in ``errors``.
        """
        started = time.perf_counter()
        lib = self._check_library(library, "schlib")
        notes: list[str] = []
        payloads = self._symbol_payloads(list(specs), notes)
        result = WriteResult(library=str(lib), backend="rust", warnings=notes)
        if not payloads:
            return self._finish(result, started)
        names = [p["name"] for p in payloads]
        try:
            with library_lock(lib):
                client = self.client()
                lib.parent.mkdir(parents=True, exist_ok=True)
                tx = self._transaction(lib, result)
                try:
                    with tx:
                        work = tx.target  # every call works on the copy; the library is replaced at the end
                        before_tree = preserve.snapshot(work)
                        existing = self._existing(client, work, names)
                        new = [p for p in payloads if p["name"] not in existing]
                        updates = [p for p in payloads if p["name"] in existing]
                        if len(updates) >= BATCH_UPDATE_THRESHOLD:
                            self._delete_for_reappend(client, work, updates)
                            new, updates = updates + new, []
                        if new:
                            resp = client.call_tool(
                                "write_schlib", {"filepath": _posix(work), "append": work.exists(), "symbols": new}
                            )
                            self._verify_symbol_write(resp, new, result)
                        for payload in updates:
                            resp = client.call_tool(
                                "update_component",
                                {"filepath": _posix(work), "component_name": payload["name"],
                                 "symbol": update_symbol_payload(payload)},
                            )
                            self._collect_messages(resp, {payload["name"]}, result)
                        self._verify_symbol_order(client, work, payloads, result)
                        self._verify_symbol_metadata(client, work, payloads, result)
                        self._raise_if_failed(result)
                        self._finish_schlib(client, work, result, names, before_tree)
                except RustValidationError:
                    raise
                except RustWriterError as exc:
                    self._fail(result, names, tx, exc)
        except LibraryLocked as exc:
            self._locked(result, names, exc)
        return self._finish(result, started)

    def _restore_untouched(
        self,
        client: RustMcpClient,
        work: Path,
        before_tree: Mapping[str, bytes | None] | None,
        written: Sequence[str],
        kind: Literal["schlib", "pcblib"],
        result: WriteResult,
    ) -> None:
        """Set every component the call did not write back to its bytes from before the call (the writer
        re-serialises all of them, :mod:`partforge.altium.preserve`). Checked like every patch; a failure only
        leaves the writer's version and a warning."""
        if not before_tree or not work.is_file():
            return
        try:
            after = compound.read_tree_file(work)
            streams, skipped = preserve.restore_plan(before_tree, after, written, kind)
        except Exception as exc:  # noqa: BLE001 - never fail a write
            log.warning("Unberührte Bauteile in %s nicht prüfbar: %s", work, exc)
            return
        library = result_library(result)
        for name in skipped:
            result.warnings.append(
                f"{library}: {name} wurde vom Bibliotheks-Writer neu gespeichert (sein 3D-Modell fehlt in der neuen "
                "Fassung) – Inhalte, die der Writer nicht kennt, können dabei verloren gegangen sein."
            )
        if not streams:
            return
        try:
            expected = self._component_names(client, work)

            def verify(copy: Path) -> None:
                if self._component_names(client, copy) != expected:
                    raise RustWriterError("Der Rust-Reader liest die Bibliothek nach dem Wiederherstellen anders.")

            compound.replace_streams(work, streams, verify=verify, tag="pfkeep", create=True)
        except Exception as exc:  # noqa: BLE001 - COM, OS and verify errors: the writer's version stays
            log.warning("Unberührte Bauteile in %s nicht wiederhergestellt: %s", work, exc, exc_info=True)
            result.warnings.append(
                f"{library}: Unveränderte Bauteile konnten nicht byte-genau erhalten werden ({exc}) – der "
                "Bibliotheks-Writer hat sie neu gespeichert."
            )
            return
        log.info("%s: %d Datenströme unberührter Bauteile wiederhergestellt", library, len(streams))

    def _finish_schlib(
        self,
        client: RustMcpClient,
        work: Path,
        result: WriteResult,
        names: Sequence[str],
        before_tree: Mapping[str, bytes | None] | None,
    ) -> None:
        """After a SchLib mutation: the symbols the call did not write are set back to their bytes from before
        (:meth:`_restore_untouched`), the font table from before the write is restored and the written symbols
        get the house fonts (:func:`schstyle.patch_written_symbols`); a patched copy the Rust reader does not
        list identically is rejected – neither step ever fails a write."""
        if not work.is_file():
            return
        fonts_before: list[Any] | None = None
        header = before_tree.get("FileHeader") if before_tree else None
        if header:
            try:
                fonts_before = schrecords.parse_header(header).fonts()
            except schrecords.SchRecordError:
                fonts_before = None
        self._restore_untouched(client, work, before_tree, names, "schlib", result)
        try:
            expected = self._component_names(client, work)

            def verify(copy: Path) -> None:
                if self._component_names(client, copy) != expected:
                    raise RustWriterError("Der Rust-Reader liest die Bibliothek nach dem Setzen der Schriften anders.")

            warnings = schstyle.patch_written_symbols(work, names, self.symbol_style(), before=fonts_before,
                                                      verify=verify)
        except Exception as exc:  # noqa: BLE001 - the fonts must never fail a library write
            log.warning("Schriften in %s nicht gesetzt: %s", work, exc)
            warnings = [f"{work.name}: Schriften nicht gesetzt ({exc})."]
        result.warnings.extend(self._named(warnings, work, result))

    # -- footprints -----------------------------------------------------------------
    def _footprint_payloads(
        self, specs: Sequence[FootprintSpec], notes: list[str]
    ) -> tuple[list[dict[str, Any]], dict[str, Path]]:
        self._check_unique([s.name for s in specs])
        issues = _Issues()
        payloads: list[dict[str, Any]] = []
        steps: dict[str, Path] = {}
        layer_map = self.layer_map()
        style = self.footprint_style()
        for spec in specs:
            try:
                payload = footprint_to_rust(spec, layer_map, style, notes=notes)
                if spec.step is not None:
                    steps[spec.name] = self._resolve_step(spec.step)
            except RustValidationError as exc:
                issues.extend(exc.issues)
                continue
            issues.extend(validate_footprint_payload(payload))
            payloads.append(payload)
        issues.raise_if_any()
        return payloads, steps

    def _verify_footprint_write(
        self, resp: Mapping[str, Any], payloads: Sequence[dict[str, Any]], result: WriteResult
    ) -> None:
        names = set(resp.get("footprint_names") or [])
        bodies = {b.get("name"): b for b in resp.get("bodies") or [] if isinstance(b, dict)}
        for payload in payloads:
            name = payload["name"]
            if name not in names:
                result.errors[name] = "Footprint fehlt in der Antwort des Bibliotheks-Writers (nicht geschrieben)."
                continue
            echo = bodies.get(name)
            if payload.get("component_bodies") and isinstance(echo, dict) and echo.get("source") == "none":
                result.errors[name] = "3D-Körper wurden vom Bibliotheks-Writer nicht übernommen."
        self._collect_messages(resp, {p["name"] for p in payloads}, result)

    def _verify_footprint_metadata(
        self, client: RustMcpClient, library: Path, payloads: Sequence[dict[str, Any]], result: WriteResult
    ) -> list[str]:
        """Check pads, primitives and 3D of the written footprints; returns every component name of the
        library in file order (STEP carriers included) – the listing the later checks reuse."""
        meta = self._metadata(client, library)
        for payload in payloads:
            name = payload["name"]
            if name in result.errors:
                continue
            item = meta.get(name)
            if item is None:
                result.errors[name] = "Footprint ist nach dem Schreiben nicht in der Bibliothek."
                continue
            problems: list[str] = []
            for key, label, expected in (
                ("pad_count", "Pads", len(payload.get("pads") or [])),
                ("track_count", "Linien", len(payload.get("tracks") or [])),
                ("arc_count", "Bögen", len(payload.get("arcs") or [])),
                ("region_count", "Flächen", len(payload.get("regions") or [])),
                ("text_count", "Texte", len(payload.get("text") or []) or 1),
            ):
                value = item.get(key)
                if _is_int(value) and value != expected:
                    problems.append(f"{value} statt {expected} {label}")
            has_3d = item.get("has_3d_model")
            if isinstance(has_3d, bool) and has_3d != bool(payload.get("component_bodies")):
                problems.append("3D-Modell fehlt" if not has_3d else "unerwartetes 3D-Modell")
            if problems:
                result.errors[name] = "Nach dem Schreiben gelesen: " + ", ".join(problems) + "."
            else:
                result.written.append(name)
        return list(meta)

    def _embed_step_models(
        self,
        client: RustMcpClient,
        library: Path,
        specs_by_name: Mapping[str, FootprintSpec],
        steps: Mapping[str, Path],
        *,
        create: bool,
    ) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """Embed every distinct STEP file through a temporary carrier footprint.

        Returns the STEP component body per footprint name (referencing the embedded
        model id, real height) and the carrier names to delete afterwards.
        """
        carriers: dict[str, str] = {}  # normalized step path -> carrier name
        paths: dict[str, Path] = {}
        token = uuid.uuid4().hex[:8].upper()
        for name in steps:
            key = _norm(steps[name])
            if key not in carriers:
                carriers[key] = f"{STEP_CARRIER_PREFIX}{token}_{len(carriers)}"
                paths[key] = steps[name]
        count_before = 0
        if not create and library.exists():
            listing = client.call_tool("list_components", {"filepath": _posix(library)})
            count_before = int(_num(listing.get("total_count"), 0))
        carrier_payloads = [
            {
                "name": carrier,
                "description": "PartForge STEP carrier (temporary)",
                "pads": [],
                "step_model": {"filepath": _posix(paths[key]), "embed": True},
            }
            for key, carrier in carriers.items()
        ]
        resp = client.call_tool(
            "write_pcblib",
            {"filepath": _posix(library), "append": not create and library.exists(), "footprints": carrier_payloads},
        )
        written = set(resp.get("footprint_names") or [])
        missing = [c for c in carriers.values() if c not in written]
        if missing:
            raise RustProcessError(f"STEP-Modelle konnten nicht eingebettet werden ({', '.join(missing)}).")
        wanted = set(carriers.values())
        read = client.call_tool(
            "read_pcblib", {"filepath": _posix(library), "offset": count_before, "limit": len(carrier_payloads)}
        )
        found = {fp.get("name"): fp for fp in read.get("footprints") or [] if isinstance(fp, dict)}
        if not wanted.issubset(found):
            read = client.call_tool("read_pcblib", {"filepath": _posix(library)})
            found = {fp.get("name"): fp for fp in read.get("footprints") or [] if isinstance(fp, dict)}
        models: dict[str, tuple[str, str]] = {}
        for key, carrier in carriers.items():
            footprint = found.get(carrier) or {}
            body = next(
                (
                    b
                    for b in footprint.get("component_bodies") or []
                    if isinstance(b, dict) and isinstance(b.get("model_id"), str) and b["model_id"]
                ),
                None,
            )
            if body is None:
                raise RustProcessError(f"Eingebettetes STEP-Modell von {paths[key].name} nicht gefunden.")
            models[key] = (body["model_id"], str(body.get("model_name") or paths[key].name))
        layer_map = self.layer_map()
        bodies: dict[str, dict[str, Any]] = {}
        for name, path in steps.items():
            model_id, model_name = models[_norm(path)]
            bodies[name] = step_body(specs_by_name[name], layer_map, model_id, model_name)
        return bodies, list(carriers.values())

    @staticmethod
    def _delete_carriers(client: RustMcpClient, library: Path, carriers: Sequence[str]) -> None:
        """Remove the temporary STEP carrier footprints (a leftover fails the whole call)."""
        if not carriers:
            return
        resp = client.call_tool("delete_component", {"filepath": _posix(library), "component_names": list(carriers)})
        states = {r.get("name"): r.get("status") for r in resp.get("results") or [] if isinstance(r, dict)}
        leftovers = [c for c in carriers if states.get(c) != "deleted"]
        if leftovers:
            raise RustProcessError(f"Temporäre STEP-Träger konnten nicht entfernt werden: {', '.join(leftovers)}")

    @staticmethod
    def _delete_for_reappend(client: RustMcpClient, library: Path, payloads: Sequence[dict[str, Any]]) -> None:
        """Remove components that are re-appended in the same operation (batched update)."""
        names = [p["name"] for p in payloads]
        resp = client.call_tool("delete_component", {"filepath": _posix(library), "component_names": names})
        states = {r.get("name"): r.get("status") for r in resp.get("results") or [] if isinstance(r, dict)}
        failed = [n for n in names if states.get(n) != "deleted"]
        if failed:
            raise RustProcessError(f"Bauteile konnten für die Aktualisierung nicht ersetzt werden: {', '.join(failed)}")

    @staticmethod
    def _component_names(client: RustMcpClient, library: Path) -> list[str]:
        names: list[str] = []
        offset = 0
        while True:
            resp = client.call_tool("list_components", {"filepath": _posix(library), "offset": offset})
            batch = [c for c in resp.get("components") or [] if isinstance(c, str)]
            names.extend(batch)
            if not resp.get("has_more") or not batch:
                return names
            offset += len(batch)

    def _finish_pcblib(
        self,
        client: RustMcpClient,
        work: Path,
        result: WriteResult,
        before: Mapping[str, float],
        specs: Sequence[FootprintSpec],
        names: Sequence[str],
    ) -> None:
        """After a PcbLib mutation: workspace layer stack into the header (:func:`stackup.patch_pcblib_layers`)
        and every footprint's height (:func:`heights.patch_footprint_heights` – the call's footprints from their
        spec, all others as they were), then **one** check that the Rust reader still lists ``names`` (the
        listing taken after writing). Each patch checks its own bytes; a patched copy the reader does not list
        identically is dropped with a warning – the patches never fail the write."""
        if not work.is_file():
            return
        header_on = stackup.header_patch_enabled()
        heights_on = heights.height_patch_enabled()
        if not header_on and not heights_on:
            return
        unpatched = work.with_name(f"{self._library_stem(work)}.{WORK_TAG}{uuid.uuid4().hex[:8]}{work.suffix}")
        try:
            shutil.copyfile(work, unpatched)
        except OSError as exc:
            log.warning("Kopie vor den Patches von %s nicht möglich: %s", work, exc)
            unpatched = None  # type: ignore[assignment]
        try:
            state = _file_state(work)
            if header_on:
                try:
                    stack, notes = self.layer_stack()
                    result.warnings.extend(notes)
                    result.warnings.extend(self._named(stackup.patch_pcblib_layers(work, stack), work, result))
                except Exception as exc:  # noqa: BLE001 - the layer header must never fail a library write
                    log.warning("Lagen-Kopf von %s nicht angepasst: %s", work, exc)
                    result.warnings.append(f"{result_library(result)}: Lagen-Kopf nicht an den Lagenaufbau angepasst ({exc}).")
            if heights_on:
                wanted = dict(before)
                for spec in specs:
                    height = heights.footprint_height(spec)
                    if height is not None:
                        wanted[spec.name] = height
                if any(height > 0 for height in wanted.values()):
                    try:
                        result.warnings.extend(self._named(heights.patch_footprint_heights(work, wanted), work, result))
                    except Exception as exc:  # noqa: BLE001 - the heights must never fail a library write
                        log.warning("Bauhöhen von %s nicht gesetzt: %s", work, exc)
                        result.warnings.append(f"{result_library(result)}: Bauhöhen nicht gesetzt ({exc}).")
            if _file_state(work) == state or unpatched is None:
                return
            found = self._component_names(client, work)
            if found != list(names):
                log.warning("Rust-Reader liest %s nach den Patches anders (%d statt %d Bauteile) – Patches verworfen",
                            work, len(found), len(names))
                os.replace(unpatched, work)
                unpatched = None  # type: ignore[assignment]
                result.warnings.append(
                    f"{result_library(result)}: Lagen-Kopf nicht angepasst und Bauhöhen nicht gesetzt – der "
                    f"Bibliotheks-Writer liest die angepasste Datei anders ({len(found)} statt {len(names)} Footprints)."
                )
        finally:
            if unpatched is not None:
                with contextlib.suppress(OSError):
                    unpatched.unlink()

    @staticmethod
    def _library_stem(work: Path) -> str:
        """Stem of the library a working copy belongs to (``PF_CHIP.pfwork1a2b3c4d`` -> ``PF_CHIP``)."""
        stem = work.stem
        marker = f".{WORK_TAG}"
        return stem[: stem.rfind(marker)] if marker in stem else stem

    @staticmethod
    def _named(warnings: Sequence[str], work: Path, result: WriteResult) -> list[str]:
        """Patch warnings name the library, not its working copy."""
        return [w.replace(work.name, result_library(result)) for w in warnings]

    @staticmethod
    def _heights_before(library: Path, result: WriteResult) -> dict[str, float]:
        """Footprint heights before a PcbLib mutation (the Rust writer resets all of them to 0).

        A file of unexpected structure only gives a warning; if the heights cannot be read at all (COM or
        program error, e.g. an incomplete installation) the write is refused – it would silently reset
        every height to 0."""
        if not heights.height_patch_enabled() or not library.is_file():
            return {}
        try:
            return heights.read_footprint_heights(library)
        except heights.HeightError as exc:
            if getattr(exc, "unreadable", False):
                raise RustWriterError(
                    f"{library.name} wurde nicht geschrieben – die Bibliothek ist unverändert: Die Bauhöhen der "
                    f"Footprints sind nicht lesbar ({exc}); ein Schreiben würde alle Höhen auf 0 setzen."
                ) from exc
            log.warning("Bauhöhen von %s vor dem Schreiben nicht lesbar: %s", library, exc)
            result.warnings.append(
                f"Bauhöhen vor dem Schreiben nicht lesbar ({exc}) – vorhandene Bauhöhen werden nicht wiederhergestellt."
            )
            return {}

    def _remove_leftover_carriers(self, client: RustMcpClient, work: Path, names: Sequence[str],
                                  own: Sequence[str]) -> list[str]:
        """Delete ``__PFSTEP_*`` carriers a crashed operation of an older version left in the file; returns
        the names after it."""
        leftovers = [n for n in names if n.startswith(STEP_CARRIER_PREFIX) and n not in own]
        if not leftovers:
            return list(names)
        self._delete_carriers(client, work, leftovers)
        log.warning("%d übrig gebliebene STEP-Träger aus %s entfernt", len(leftovers), work)
        return [n for n in names if n not in leftovers]

    @staticmethod
    def _remove_orphaned_models(client: RustMcpClient, library: Path) -> None:
        """Drop embedded STEP data no footprint references any more (after updates)."""
        check = client.call_tool("repair_library", {"filepath": _posix(library), "dry_run": True})
        raw = check.get("repairs")
        repairs: dict[str, Any] = raw if isinstance(raw, dict) else {}
        if int(_num(repairs.get("orphaned_models_removed"), 0)) > 0:
            client.call_tool("repair_library", {"filepath": _posix(library), "dry_run": False})

    def upsert_footprints(self, library: str | os.PathLike[str], specs: Sequence[FootprintSpec]) -> WriteResult:
        """Create or replace the given footprints; other footprints stay untouched.

        All or nothing, like :meth:`upsert_symbols`.
        """
        started = time.perf_counter()
        lib = self._check_library(library, "pcblib")
        spec_list = list(specs)
        notes: list[str] = []
        payloads, steps = self._footprint_payloads(spec_list, notes)
        result = WriteResult(library=str(lib), backend="rust", warnings=notes)
        if not payloads:
            return self._finish(result, started)
        names = [p["name"] for p in payloads]
        by_name = {s.name: s for s in spec_list}
        try:
            with library_lock(lib):
                client = self.client()
                lib.parent.mkdir(parents=True, exist_ok=True)
                tx = self._transaction(lib, result)
                try:
                    with tx:
                        work = tx.target  # every call works on the copy; the library is replaced at the end
                        before = self._heights_before(work, result)
                        before_tree = preserve.snapshot(work)
                        existing = self._existing(client, work, names)
                        carriers: list[str] = []
                        if steps:
                            step_bodies, carriers = self._embed_step_models(client, work, by_name, steps, create=False)
                            for payload in payloads:
                                if payload["name"] in step_bodies:
                                    payload["component_bodies"] = [
                                        step_bodies[payload["name"]],
                                        *payload.get("component_bodies", []),
                                    ]
                        new = [p for p in payloads if p["name"] not in existing]
                        updates = [p for p in payloads if p["name"] in existing]
                        batched = len(updates) >= BATCH_UPDATE_THRESHOLD
                        if batched:
                            self._delete_for_reappend(client, work, updates)
                            new, updates = updates + new, []
                        if new:
                            resp = client.call_tool(
                                "write_pcblib", {"filepath": _posix(work), "append": work.exists(), "footprints": new}
                            )
                            self._verify_footprint_write(resp, new, result)
                        for payload in updates:
                            resp = client.call_tool(
                                "update_component",
                                {"filepath": _posix(work), "component_name": payload["name"],
                                 "footprint": fix_points(payload)},
                            )
                            self._collect_messages(resp, {payload["name"]}, result)
                        if carriers:  # deleting the carriers also drops orphaned models
                            self._delete_carriers(client, work, carriers)
                        elif updates:  # a replaced footprint may have left its STEP data behind
                            self._remove_orphaned_models(client, work)
                        # (batched updates: delete_component already dropped the orphaned models)
                        listed = self._verify_footprint_metadata(client, work, payloads, result)
                        self._raise_if_failed(result)
                        listed = self._remove_leftover_carriers(client, work, listed, carriers)
                        self._restore_untouched(client, work, before_tree, names, "pcblib", result)
                        self._finish_pcblib(client, work, result, before, spec_list, listed)
                except RustValidationError:
                    raise
                except RustWriterError as exc:
                    self._fail(result, names, tx, exc)
        except LibraryLocked as exc:
            self._locked(result, names, exc)
        return self._finish(result, started)

    # -- full rewrite ---------------------------------------------------------------
    def write_library_full(
        self,
        library: str | os.PathLike[str],
        specs: Sequence[SymbolSpec] | Sequence[FootprintSpec],
    ) -> WriteResult:
        """Regenerate a PartForge-managed library with exactly ``specs`` (``append: false``).

        Without STEP models this is a single writer call; footprints with STEP models need
        three calls (carrier embedding, footprints, carrier removal). All or nothing: on
        any error the previous library is restored.
        """
        started = time.perf_counter()
        kind = library_kind(library)
        spec_list: list[SymbolSpec | FootprintSpec] = list(specs)
        expected = SymbolSpec if kind == "schlib" else FootprintSpec
        wrong = [type(s).__name__ for s in spec_list if not isinstance(s, expected)]
        if wrong:
            raise RustValidationError(
                [f"Die Bibliothek {Path(library).name} erwartet {expected.__name__}, erhalten: {', '.join(sorted(set(wrong)))}."]
            )
        lib = self._check_library(library, kind)
        notes: list[str] = []
        result = WriteResult(library=str(lib), backend="rust", warnings=notes)
        if kind == "schlib":
            payloads = self._symbol_payloads(spec_list, notes)  # type: ignore[arg-type]
            steps: dict[str, Path] = {}
        else:
            payloads, steps = self._footprint_payloads(spec_list, notes)  # type: ignore[arg-type]
        names = [p["name"] for p in payloads]
        by_name = {s.name: s for s in spec_list}
        try:
            with library_lock(lib):
                client = self.client()
                lib.parent.mkdir(parents=True, exist_ok=True)
                tx = self._transaction(lib, result)
                try:
                    with tx:
                        # every call works on the copy: a crash never leaves a half-built library (INT-02)
                        work = tx.target
                        before = self._heights_before(work, result) if kind == "pcblib" else {}
                        before_tree = preserve.snapshot(work) if kind == "schlib" else None
                        listed: list[str] = []
                        if kind == "schlib":
                            resp = client.call_tool(
                                "write_schlib", {"filepath": _posix(work), "append": False, "symbols": payloads}
                            )
                            self._verify_symbol_write(resp, payloads, result)
                            self._verify_symbol_order(client, work, payloads, result)
                            self._verify_symbol_metadata(client, work, payloads, result)
                        elif not steps:
                            resp = client.call_tool(
                                "write_pcblib", {"filepath": _posix(work), "append": False, "footprints": payloads}
                            )
                            self._verify_footprint_write(resp, payloads, result)
                            listed = self._verify_footprint_metadata(client, work, payloads, result)
                        else:
                            step_bodies, carriers = self._embed_step_models(
                                client, work, by_name, steps, create=True  # type: ignore[arg-type]
                            )
                            for payload in payloads:
                                if payload["name"] in step_bodies:
                                    payload["component_bodies"] = [
                                        step_bodies[payload["name"]],
                                        *payload.get("component_bodies", []),
                                    ]
                            if payloads:
                                resp = client.call_tool(
                                    "write_pcblib", {"filepath": _posix(work), "append": True, "footprints": payloads}
                                )
                                self._verify_footprint_write(resp, payloads, result)
                            self._delete_carriers(client, work, carriers)
                            listed = self._verify_footprint_metadata(client, work, payloads, result)
                        self._raise_if_failed(result)
                        if kind == "pcblib":
                            footprints = [s for s in spec_list if isinstance(s, FootprintSpec)]
                            self._finish_pcblib(client, work, result, before, footprints, listed)
                        else:
                            self._finish_schlib(client, work, result, names, before_tree)
                except RustValidationError:
                    raise
                except RustWriterError as exc:
                    self._fail(result, names, tx, exc)
        except LibraryLocked as exc:
            self._locked(result, names, exc)
        return self._finish(result, started)

    # -- delete ---------------------------------------------------------------------
    def delete_components(self, library: str | os.PathLike[str], names: Sequence[str]) -> WriteResult:
        """Delete components by name (missing names are reported as warnings).

        All or nothing: if the writer cannot delete one of them, nothing is deleted.
        """
        started = time.perf_counter()
        kind = library_kind(library)
        lib = self._check_library(library, kind)
        result = WriteResult(library=str(lib), backend="rust")
        wanted = list(dict.fromkeys(n for n in names if isinstance(n, str) and n))
        if not wanted:
            return self._finish(result, started)
        if not lib.exists():
            result.warnings.append(f"Bibliothek {lib.name} existiert nicht – nichts zu löschen.")
            return self._finish(result, started)
        missing: list[str] = []
        try:
            with library_lock(lib):
                client = self.client()
                tx = self._transaction(lib, result)
                try:
                    with tx:
                        work = tx.target  # the library is replaced at the end
                        before = self._heights_before(work, result) if kind == "pcblib" else {}
                        before_tree = preserve.snapshot(work)
                        resp = client.call_tool(
                            "delete_component", {"filepath": _posix(work), "component_names": wanted}
                        )
                        states = {r.get("name"): r for r in resp.get("results") or [] if isinstance(r, dict)}
                        failures: dict[str, str] = {}
                        for name in wanted:
                            state = states.get(name, {})
                            status = state.get("status")
                            if status == "deleted":
                                result.deleted.append(name)
                            elif status == "not_found":
                                missing.append(name)
                                result.warnings.append(f"{name}: nicht in der Bibliothek vorhanden.")
                            else:
                                failures[name] = str(state.get("error") or state.get("message") or "Löschen fehlgeschlagen.")
                        if failures:
                            raise _VerificationFailed(failures)
                        if kind == "pcblib" and result.deleted:
                            self._restore_untouched(client, work, before_tree, result.deleted, "pcblib", result)
                            self._finish_pcblib(client, work, result, before, [], self._component_names(client, work))
                        elif kind == "schlib" and result.deleted:
                            self._finish_schlib(client, work, result, [], before_tree)
                except RustValidationError:
                    raise
                except RustWriterError as exc:
                    self._fail(result, [n for n in wanted if n not in missing], tx, exc, verb="gelöscht")
        except LibraryLocked as exc:
            self._locked(result, [n for n in wanted if n not in missing], exc, verb="gelöscht")
        return self._finish(result, started)

    # -- read -----------------------------------------------------------------------
    def list_components(self, library: str | os.PathLike[str]) -> list[str]:
        """Component names in file order (temporary STEP carriers excluded)."""
        lib = Path(os.path.abspath(os.fspath(library)))
        library_kind(lib)
        if not lib.is_file():
            raise RustWriterError(f"Bibliothek nicht gefunden: {lib}")
        client = self.client()
        path = self._readable(lib)
        names: list[str] = []
        offset = 0
        while True:
            resp = client.call_tool("list_components", {"filepath": _posix(path), "offset": offset})
            batch = [c for c in resp.get("components") or [] if isinstance(c, str)]
            names.extend(batch)
            if not resp.get("has_more") or not batch:
                break
            offset += len(batch)
        return [n for n in names if is_listed_component(n)]

    def backup_readable(self, backup: str | os.PathLike[str], library: str | os.PathLike[str]) -> bool:
        """Whether the reader can list ``backup`` – a ``<lib>.<stamp>.bak`` copy of ``library`` (checked through a
        temporary copy with the library's extension in the sandbox)."""
        source = Path(backup)
        suffix = Path(library).suffix
        if suffix.lower() not in (SCHLIB_EXT, PCBLIB_EXT) or not source.is_file():
            return False
        folder = temp_dir() / "check"
        probe = folder / f"{uuid.uuid4().hex[:12]}{suffix}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, probe)
            self.list_components(probe)
            return True
        except (RustWriterError, OSError) as exc:
            log.info("Sicherung %s nicht lesbar: %s", source, exc)
            return False
        finally:
            with contextlib.suppress(OSError):
                probe.unlink()

    def scan(self, library: str | os.PathLike[str]) -> list[ComponentInfo]:
        """Components with metadata (works for any SchLib/PcbLib, also outside the workspace)."""
        lib = Path(os.path.abspath(os.fspath(library)))
        kind = library_kind(lib)
        if not lib.is_file():
            raise RustWriterError(f"Bibliothek nicht gefunden: {lib}")
        client = self.client()
        meta = self._metadata(client, self._readable(lib))
        out: list[ComponentInfo] = []
        for name, item in meta.items():
            if not is_listed_component(name):
                continue
            description = item.get("description") if isinstance(item.get("description"), str) else None
            if kind == "schlib":
                out.append(
                    ComponentInfo(
                        name=name,
                        library=str(lib),
                        kind="symbol",
                        description=description,
                        pin_count=item.get("pin_count") if _is_int(item.get("pin_count")) else None,
                        part_count=item.get("part_count") if _is_int(item.get("part_count")) else None,
                    )
                )
            else:
                out.append(
                    ComponentInfo(
                        name=name,
                        library=str(lib),
                        kind="footprint",
                        description=description,
                        pin_count=item.get("pad_count") if _is_int(item.get("pad_count")) else None,
                        has_3d=item.get("has_3d_model") if isinstance(item.get("has_3d_model"), bool) else None,
                    )
                )
        return out

    def _get_component(self, library: str | os.PathLike[str], name: str, kind: str) -> dict[str, Any] | None:
        lib = Path(os.path.abspath(os.fspath(library)))
        if library_kind(lib) != kind:
            raise RustValidationError([f"{lib.name} ist keine {'Symbol' if kind == 'schlib' else 'Footprint'}-Bibliothek."])
        if not lib.is_file():
            return None
        client = self.client()
        try:
            resp = client.call_tool("get_component", {"filepath": _posix(self._readable(lib)), "component_name": name})
        except RustToolError as exc:
            if exc.not_found:
                return None
            raise
        component = resp.get("component")
        if not isinstance(component, dict):
            return None
        if kind == "pcblib":
            found = self._correct_layers(lib, [component])
            records = found.get(str(component.get("name", "")).casefold())
            if records is not None:
                component[_RECORDS_KEY] = records
        return component

    @staticmethod
    def _correct_layers(library: Path, components: Sequence[dict[str, Any]]
                        ) -> dict[str, pcbrecords.FootprintRecords]:
        """True layers of read footprints: primitives Altium saved on Mechanical 17–32 read as "Mechanical 16"
        (:func:`pcbrecords.correct_layers`). Returns the records by casefolded name (text extents for
        :func:`rust_to_footprint`). Best effort – without the records the reader's layers stay."""
        if not components:
            return {}
        try:
            records = pcbrecords.read_footprints(library)
        except Exception as exc:  # noqa: BLE001 - COM errors on damaged files: keep what the reader says
            log.debug("Primitive von %s nicht direkt lesbar: %s", library, exc)
            return {}
        out: dict[str, pcbrecords.FootprintRecords] = {}
        for component in components:
            key = str(component.get("name", "")).casefold()
            found = records.get(key)
            if found is not None:
                out[key] = found[1]
                fixed = pcbrecords.correct_layers(component, found[1])
                if fixed:
                    log.debug("%s: %d Primitive auf ihrer echten Lage (Mechanical 17-32) gelesen", component.get("name"), fixed)
        return out

    def read_symbol(
        self, library: str | os.PathLike[str], name: str, *, notes: list[str] | None = None
    ) -> SymbolSpec | None:
        """One symbol in the PartForge model (``notes``: what a write-back would lose)."""
        data = self._get_component(library, name, "schlib")
        return rust_to_symbol(data, notes=notes) if data is not None else None

    def read_footprint(
        self,
        library: str | os.PathLike[str],
        name: str,
        *,
        notes: list[str] | None = None,
        extract_step: bool = True,
    ) -> FootprintSpec | None:
        """One footprint in the PartForge model.

        With ``extract_step`` an embedded STEP model is extracted so that ``spec.step.file``
        is resolvable (see :meth:`_materialize_steps`); ``notes`` collects what a
        write-back would lose.
        """
        data = self._get_component(library, name, "pcblib")
        if data is None:
            return None
        spec = rust_to_footprint(data, self.layer_map(), notes=notes, records=data.get(_RECORDS_KEY))
        if extract_step:
            self._materialize_steps(Path(os.path.abspath(os.fspath(library))), [(data, spec, notes)])
        return spec

    def _read_raw(self, library: Path, kind: Literal["schlib", "pcblib"]) -> list[dict[str, Any]]:
        client = self.client()
        tool = "read_schlib" if kind == "schlib" else "read_pcblib"
        key = "symbols" if kind == "schlib" else "footprints"
        items: list[dict[str, Any]] = []
        offset = 0
        while True:
            resp = client.call_tool(tool, {"filepath": _posix(self._readable(library)), "offset": offset})
            batch = [c for c in resp.get(key) or [] if isinstance(c, dict)]
            items.extend(batch)
            if not resp.get("has_more") or not batch:
                break
            offset += len(batch)
        items = [c for c in items if is_listed_component(str(c.get("name", "")))]
        if kind == "pcblib":
            found = self._correct_layers(library, items)
            for item in items:
                records = found.get(str(item.get("name", "")).casefold())
                if records is not None:
                    item[_RECORDS_KEY] = records
        return items

    def read_all_detailed(
        self, library: str | os.PathLike[str], *, extract_step: bool = True
    ) -> list[tuple[SymbolSpec | FootprintSpec, list[str]]]:
        """Every component converted to the PartForge model, each with the German notes on
        what the conversion loses (empty list = loss-free round trip)."""
        lib = Path(os.path.abspath(os.fspath(library)))
        kind = library_kind(lib)
        if not lib.is_file():
            return []
        items = self._read_raw(lib, kind)
        if kind == "schlib":
            symbols: list[tuple[SymbolSpec | FootprintSpec, list[str]]] = []
            for raw in items:
                notes: list[str] = []
                symbols.append((rust_to_symbol(raw, notes=notes), notes))
            return symbols
        layer_map = self.layer_map()
        triples: list[tuple[Mapping[str, Any], FootprintSpec, list[str]]] = []
        for raw in items:
            notes = []
            triples.append((raw, rust_to_footprint(raw, layer_map, notes=notes, records=raw.get(_RECORDS_KEY)), notes))
        if extract_step:
            self._materialize_steps(lib, triples)
        return [(spec, notes) for _, spec, notes in triples]

    def read_all(
        self, library: str | os.PathLike[str], *, extract_step: bool = True
    ) -> list[SymbolSpec] | list[FootprintSpec]:
        """Every component of a library converted to the PartForge model."""
        return [spec for spec, _ in self.read_all_detailed(library, extract_step=extract_step)]  # type: ignore[return-value]

    # -- embedded STEP models on read -------------------------------------------------
    def _materialize_steps(
        self,
        library: Path,
        items: Sequence[tuple[Mapping[str, Any], FootprintSpec, list[str] | None]],
    ) -> None:
        """Give every read-back ``spec.step`` a file that a later write can embed again.

        :func:`rust_to_footprint` only knows the embedded model's *name*. The model data is
        extracted (one writer call per library version, cached) and placed

        * for a library inside the open workspace: into the workspace ``3D`` folder – an
          identical file anywhere in that folder is reused, a different file with the same
          name gets a content-hash suffix – with a workspace-relative ``file``;
        * otherwise: PartForge's STEP cache, with an absolute ``file`` (callers importing
          such a footprint copy the file into their workspace).

        Models that cannot be extracted (damaged or merely linked) are dropped from the
        spec with a note.
        """
        pending: list[tuple[FootprintSpec, str, str, list[str] | None]] = []
        for data, spec, notes in items:
            if spec.step is None:
                continue
            source = step_source(data)
            if source is None:  # linked model file (``model_3d``)
                if not self._step_file_exists(spec.step.file):
                    self._drop_step(spec, notes, f"Das verknüpfte STEP-Modell {spec.step.file!r} wurde nicht gefunden.")
                continue
            model_id, model_name = source
            if model_id is None:
                self._drop_step(spec, notes, f"Das STEP-Modell {model_name!r} ist nicht eingebettet, nur verknüpft.")
                continue
            pending.append((spec, model_id, model_name, notes))
        if not pending:
            return
        files = self._extract_models(library, {model_id: name for _, model_id, name, _ in pending})
        ws = self.workspace
        target = ws if ws is not None and is_inside(library, ws.root) else None
        placed: dict[str, str] = {}
        for spec, model_id, model_name, notes in pending:
            extracted = files.get(model_id)
            if extracted is None:
                self._drop_step(spec, notes, f"Das eingebettete STEP-Modell {model_name!r} ist nicht lesbar.")
                continue
            if model_id not in placed:
                try:
                    placed[model_id] = _place_step(extracted, model_name, target)
                except OSError as exc:  # 3D folder not writable: the cached copy still works
                    log.warning("STEP-Modell %s nicht in den 3D-Ordner übernommen: %s", model_name, exc)
                    placed[model_id] = str(extracted)
            if spec.step is not None:
                spec.step = spec.step.model_copy(update={"file": placed[model_id]})

    def _step_file_exists(self, file: str) -> bool:
        raw = Path(file.replace("\\", "/"))
        if raw.is_absolute():
            return raw.is_file()
        ws = self.workspace
        return ws is not None and (ws.root / raw).is_file()

    @staticmethod
    def _drop_step(spec: FootprintSpec, notes: list[str] | None, reason: str) -> None:
        message = f"Footprint {spec.name}: {reason} Es wird nicht übernommen."
        log.warning("%s", message)
        if notes is not None:
            notes.append(message)
        spec.step = None

    def _extract_models(self, library: Path, wanted: Mapping[str, str]) -> dict[str, Path]:
        """Extract embedded models (id -> name) into the STEP cache; returns id -> file.

        The cache is keyed by library path, modification time and size (one extraction per
        library version); files appear atomically, extraction is serialised process-wide.
        """
        stat = library.stat()
        key = hashlib.sha1(f"{_norm(library)}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()[:16]
        folder = step_cache_dir() / key
        with _step_cache_lock:
            found: dict[str, Path] = {}
            missing: dict[str, str] = {}
            for model_id, name in wanted.items():
                cached = folder / _model_folder(model_id) / _step_file_name(name)
                if cached.is_file():
                    found[model_id] = cached
                else:
                    missing[model_id] = name
            if not missing:
                with contextlib.suppress(OSError):
                    os.utime(folder)  # in use: keep it out of the pruning
                return found
            client = self.client()
            readable = _posix(self._readable(library))
            batch = folder / f"batch-{uuid.uuid4().hex[:8]}"
            try:
                folder.mkdir(parents=True, exist_ok=True)  # the writer only creates the last level
                if len(missing) == 1:
                    ((model_id, name),) = missing.items()
                    batch.mkdir()
                    part = batch / _step_file_name(name)
                    client.call_tool(
                        "extract_step_model",
                        {"filepath": readable, "mode": "auto", "model": model_id, "output_path": _posix(part)},
                    )
                    extracted = {model_id: part} if part.is_file() else {}
                else:
                    resp = client.call_tool(
                        "extract_step_model", {"filepath": readable, "mode": "extract_all", "output_path": _posix(batch)}
                    )
                    extracted = {
                        item["id"]: Path(item["output_path"])
                        for item in resp.get("extracted") or []
                        if isinstance(item, dict)
                        and isinstance(item.get("id"), str)
                        and item["id"] in missing
                        and isinstance(item.get("output_path"), str)
                    }
                for model_id, source in extracted.items():
                    if source.is_file():
                        cached = folder / _model_folder(model_id) / _step_file_name(missing[model_id])
                        cached.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(source, cached)
                        found[model_id] = cached
            except RustToolError as exc:
                log.warning("Eingebettete STEP-Modelle aus %s nicht lesbar: %s", library, exc)
            except OSError as exc:
                log.warning("STEP-Modelle aus %s konnten nicht zwischengespeichert werden: %s", library, exc)
            finally:
                shutil.rmtree(batch, ignore_errors=True)
            _prune_step_cache()
        return found

    def template_library_data(self) -> bytes:
        """``Library/Data`` of an empty PcbLib written by the Rust writer: a complete, modern header (every
        mechanical layer in all representations) – the template for renewing the header of libraries saved by
        older Altium versions (:func:`stackup.renew_library_data`). Cached per writer executable."""
        client = self.client()
        key = _norm(client.exe)
        with _template_lock:
            cached = _template_headers.get(key)
            if cached is not None:
                return cached
            folder = temp_dir() / "template"
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"header_{uuid.uuid4().hex[:8]}.PcbLib"
            try:
                client.call_tool("write_pcblib", {"filepath": _posix(target), "append": False, "footprints": []})
                data = stackup.read_library_data(target)
            finally:
                for leftover in [target, *folder.glob(f"{target.name}.*")]:
                    with contextlib.suppress(OSError):
                        leftover.unlink()
            _template_headers[key] = data
            return data

    def validate_library(self, library: str | os.PathLike[str]) -> dict[str, Any]:
        """Raw ``validate_library`` report of the writer."""
        lib = Path(os.path.abspath(os.fspath(library)))
        library_kind(lib)
        if not lib.is_file():
            raise RustWriterError(f"Bibliothek nicht gefunden: {lib}")
        return self.client().call_tool("validate_library", {"filepath": _posix(self._readable(lib))})


def iter_chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    """Split ``items`` into chunks of ``size`` (helper for callers batching very large writes)."""
    for start in range(0, len(items), max(1, size)):
        yield items[start : start + size]
