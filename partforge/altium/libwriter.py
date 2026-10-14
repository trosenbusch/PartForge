"""Library writers: common protocol, backend selection and the library file layout.

Two backends write Altium SchLib/PcbLib files:

* ``rust`` (default): :class:`RustLibraryWriter` on top of ``altium-designer-mcp.exe``
  (no running Altium needed, see :mod:`partforge.altium.rustwriter`).
* ``altium``: :class:`partforge.altium.bridge.writer.AltiumLibraryWriter`, which lets the
  running Altium Designer build the files through the PartForge DelphiScript bridge.

:func:`get_writer` honours ``settings.altium.library_backend`` (``auto`` = Rust writer if
the executable exists, else Altium if it is running). File layout (ARCHITEKTUR.md §3):
``grouped`` = ``Symbols/PF_<Gruppe>.SchLib`` and ``Footprints/PF_<FAMILIE>.PcbLib``,
``per_item`` = one file per symbol/footprint.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Final, Literal, Protocol, runtime_checkable

from .. import config
from ..config import AppSettings, load_settings
from ..geometry.model import FootprintSpec, SymbolSpec
from ..workspace import Workspace
from .models import BackendStatus, ComponentInfo, WriteResult
from .rustwriter import RustLibraryOps, rust_writer_version
from .texts import SETTINGS_ALTIUM, WRITER

log = logging.getLogger(__name__)

__all__ = [
    "LibraryWriter",
    "RustLibraryWriter",
    "WriterUnavailable",
    "SYMBOL_GROUPS",
    "PREFIX_GROUPS",
    "get_writer",
    "no_writer_message",
    "backend_status",
    "symbol_group",
    "symbol_library_path",
    "footprint_family",
    "footprint_library_path",
    "safe_file_stem",
    "LibraryKind",
    "library_file_kind",
    "is_temp_library_file",
    "workspace_library_files",
    "cached_component_names",
    "forget_component_names",
]


class WriterUnavailable(RuntimeError):
    """No library writer backend can be used (German message; API maps it to HTTP 503)."""


@runtime_checkable
class LibraryWriter(Protocol):
    """Contract of a library writer backend (ARCHITEKTUR.md §8.2)."""

    name: str

    def available(self) -> tuple[bool, str]: ...

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        """Upsert: create or replace the given symbols, keep all others."""
        ...

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        """Upsert: create or replace the given footprints, keep all others."""
        ...

    def write_library_full(
        self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]
    ) -> WriteResult:
        """Regenerate a PartForge-managed library with exactly ``specs``."""
        ...

    def delete_components(self, library: Path, names: list[str]) -> WriteResult: ...

    def list_components(self, library: Path) -> list[str]: ...

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None: ...

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None: ...

    def scan_library(self, library: Path) -> list[ComponentInfo]: ...


# --------------------------------------------------------------------------- Rust backend


class RustLibraryWriter:
    """:class:`LibraryWriter` backed by ``altium-designer-mcp.exe`` (default backend)."""

    name = "rust"

    def __init__(
        self,
        exe: str | os.PathLike[str] | None = None,
        *,
        workspace: Workspace | None = None,
        ops: RustLibraryOps | None = None,
    ):
        self._exe = os.fspath(exe) if exe else None
        self.ops = ops or RustLibraryOps(exe=self._exe, workspace=workspace)

    def _exe_path(self) -> str | None:
        if self._exe:
            return self._exe if Path(self._exe).is_file() else None
        return load_settings().resolved_rust_writer()

    def available(self) -> tuple[bool, str]:
        exe = self._exe_path()
        if not exe:
            return False, f"Der {WRITER} wurde nicht gefunden. Bitte den Pfad unter {SETTINGS_ALTIUM} eintragen."
        version = rust_writer_version(exe)
        return True, f"{WRITER} bereit{f' (Version {version})' if version else ''}."

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        return self.ops.upsert_symbols(library, symbols)

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        return self.ops.upsert_footprints(library, footprints)

    def write_library_full(
        self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]
    ) -> WriteResult:
        return self.ops.write_library_full(library, specs)

    def delete_components(self, library: Path, names: list[str]) -> WriteResult:
        return self.ops.delete_components(library, names)

    def list_components(self, library: Path) -> list[str]:
        return self.ops.list_components(library)

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None:
        return self.ops.read_symbol(library, name)

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None:
        return self.ops.read_footprint(library, name)

    def scan_library(self, library: Path) -> list[ComponentInfo]:
        return self.ops.scan(library)


# --------------------------------------------------------------------------- selection


def _altium_writer(settings: AppSettings, workspace: Workspace | None, rust_exe: str | None) -> LibraryWriter:
    from .bridge.core import AltiumBridge
    from .bridge.writer import AltiumLibraryWriter

    reader = RustLibraryOps(exe=rust_exe, workspace=workspace) if rust_exe else None
    return AltiumLibraryWriter(AltiumBridge.from_settings(settings), reader=reader, workspace=workspace)


def no_writer_message(altium_reason: str) -> str:
    """German message when neither the library writer nor Altium can write (remedy first, so a clipped
    toast keeps it; ``altium_reason`` = why Altium is not available, its final period is dropped)."""
    reason = altium_reason.strip().rstrip(".").strip() or "Altium Designer steht nicht zur Verfügung"
    return (
        f"Kein {WRITER} verfügbar – bitte den Pfad zum {WRITER} unter {SETTINGS_ALTIUM} eintragen oder Altium "
        f"Designer starten. Grund: Der {WRITER} wurde nicht gefunden; {reason}."
    )


def get_writer(settings: AppSettings | None = None, *, workspace: Workspace | None = None) -> LibraryWriter:
    """The configured writer (``auto``: Rust writer if present, else Altium if running).

    Raises :class:`WriterUnavailable` with a German explanation when nothing can write.
    """
    settings = settings or load_settings()
    mode = settings.altium.library_backend
    rust_exe = settings.resolved_rust_writer()
    if mode == "rust":
        if not rust_exe:
            raise WriterUnavailable(
                f"Der {WRITER} wurde nicht gefunden. Bitte den Pfad unter {SETTINGS_ALTIUM} eintragen oder dort "
                "„Über Altium“ wählen."
            )
        return RustLibraryWriter(rust_exe, workspace=workspace)
    if mode == "altium":
        writer = _altium_writer(settings, workspace, rust_exe)
        ok, message = writer.available()
        if not ok:
            raise WriterUnavailable(message)
        return writer
    if rust_exe:
        return RustLibraryWriter(rust_exe, workspace=workspace)
    writer = _altium_writer(settings, workspace, None)
    ok, message = writer.available()
    if ok:
        return writer
    raise WriterUnavailable(no_writer_message(message))


def backend_status(settings: AppSettings | None = None) -> list[BackendStatus]:
    """Status of both backends for the UI (cheap: no writer process, no Altium script)."""
    from .bridge.process import altium_backend_status

    settings = settings or load_settings()
    rust_exe = settings.resolved_rust_writer()
    if rust_exe:
        version = rust_writer_version(rust_exe)
        rust = BackendStatus(
            name="rust",
            available=True,
            message=f"{WRITER} bereit{f' (Version {version})' if version else ''}.",
            version=version,
            path=rust_exe,
        )
    else:
        configured = (settings.altium.rust_writer_path or "").strip()
        if not configured:
            message = f"{WRITER} nicht gefunden – Pfad unter {SETTINGS_ALTIUM} eintragen."
        elif not config.is_unc_or_device_path(configured) and not Path(configured).is_file():
            message = f"{WRITER} nicht gefunden: {configured} existiert nicht – Pfad unter {SETTINGS_ALTIUM} korrigieren."
        else:
            # a hand-edited UNC/device path, network drive or non-.exe file is ignored, never executed
            # (QA sec finding 2) – the status says why
            problem = config.executable_path_problem(configured)
            message = f"{WRITER} wird nicht verwendet: {problem} Pfad unter {SETTINGS_ALTIUM} korrigieren."
        rust = BackendStatus(name="rust", available=False, message=message, path=configured or None)
    return [rust, altium_backend_status(settings)]


# --------------------------------------------------------------------------- layout

#: Category table -> symbol library group (``Symbols/PF_<Gruppe>.SchLib``).
SYMBOL_GROUPS: Final[dict[str, str]] = {
    "Resistors": "Passives",
    "Capacitors": "Passives",
    "Inductors": "Passives",
    "Ferrite Beads": "Passives",
    "Diodes": "Diodes",
    "LEDs": "Diodes",
    "Transistors BJT": "Transistors",
    "Transistors FET": "Transistors",
    "Amplifiers": "Analog",
    "Power Linear": "Power",
    "Power Switchmode": "Power",
    "Data Converters": "ICs",
    "Integrated Circuits": "ICs",
    "Optocouplers": "ICs",
    "Connectors": "Connectors",
    "Electromechanical": "Electromechanical",
    "Fuses": "Protection",
    "Oscillators": "Oscillators",
    "Mechanical": "Mechanical",
}

#: Designator prefix -> group, used when no category is known.
PREFIX_GROUPS: Final[dict[str, str]] = {
    "R": "Passives",
    "C": "Passives",
    "L": "Passives",
    "FB": "Passives",
    "T": "Passives",
    "D": "Diodes",
    "LED": "Diodes",
    "Q": "Transistors",
    "U": "ICs",
    "IC": "ICs",
    "J": "Connectors",
    "P": "Connectors",
    "X": "Connectors",
    "CN": "Connectors",
    "F": "Protection",
    "Y": "Oscillators",
    "S": "Electromechanical",
    "SW": "Electromechanical",
    "K": "Electromechanical",
    "MH": "Mechanical",
    "M": "Mechanical",
}

_RESERVED_STEMS: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
)


def safe_file_stem(name: str) -> str:
    """File-system-safe stem for a component name (Windows reserved names avoided)."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(". ")
    if not stem:
        stem = "Bauteil"
    if stem.split(".")[0].upper() in _RESERVED_STEMS:
        stem = f"PF_{stem}"
    return stem


def _group_token(text: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return token or "Misc"


def symbol_group(category: str | None, spec: SymbolSpec | None = None) -> str:
    """Library group of a symbol: category mapping, else designator prefix, else ``Misc``."""
    if category:
        group = SYMBOL_GROUPS.get(category)
        if group:
            return group
        return _group_token(category)
    if spec is not None:
        prefix = (spec.designator_prefix or "").strip().upper()
        if prefix in PREFIX_GROUPS:
            return PREFIX_GROUPS[prefix]
        letters = re.match(r"[A-Z]+", prefix)
        if letters and letters.group(0) in PREFIX_GROUPS:
            return PREFIX_GROUPS[letters.group(0)]
    return "Misc"


def symbol_library_path(ws: Workspace, spec: SymbolSpec, category: str | None = None) -> Path:
    """Target SchLib of a symbol (``grouped``: ``Symbols/PF_<Gruppe>.SchLib``)."""
    if ws.settings.library_layout == "per_item":
        return ws.symbols_dir / f"{safe_file_stem(spec.name)}.SchLib"
    return ws.symbols_dir / f"PF_{symbol_group(category, spec)}.SchLib"


def footprint_family(spec: FootprintSpec) -> str:
    """Upper-case family token of a footprint (``chip`` -> ``CHIP``; unknown -> ``MISC``)."""
    token = re.sub(r"[^A-Za-z0-9]+", "_", spec.family or "").strip("_").upper()
    return token or "MISC"


def footprint_library_path(ws: Workspace, spec: FootprintSpec) -> Path:
    """Target PcbLib of a footprint (``grouped``: ``Footprints/PF_<FAMILIE>.PcbLib``)."""
    if ws.settings.library_layout == "per_item":
        return ws.footprints_dir / f"{safe_file_stem(spec.name)}.PcbLib"
    return ws.footprints_dir / f"PF_{footprint_family(spec)}.PcbLib"


# --------------------------------------------------------------------------- library files

LibraryKind = Literal["schlib", "pcblib"]

#: Temporary files of the writers beside a library, ``<stem>.pf<tag><hex8>.<ext>`` (bridge rebuild ``pf``, header
#: patch ``pfhdr``, height patch ``pfhgt``, Rust-writer working copy ``pfwork``, house style ``pfstd``/``pfundo``,
#: library import ``pfimport``, font patch ``pffont``, stream restore ``pfkeep``; Rust ``<lib>.<ext>.tmp``); never
#: listed – a crash leaves them behind and they must not surface as libraries (or be chosen as a save target).
_TEMP_NAME_RE: Final = re.compile(r"\.pf[a-z]*[0-9a-f]{8}\.(?:schlib|pcblib)$", re.IGNORECASE)


def library_file_kind(path: str | os.PathLike[str]) -> LibraryKind | None:
    """``schlib``/``pcblib`` from the extension (case-insensitive), else ``None``."""
    suffix = Path(path).suffix.lower()
    if suffix == ".schlib":
        return "schlib"
    if suffix == ".pcblib":
        return "pcblib"
    return None


def is_temp_library_file(path: str | os.PathLike[str]) -> bool:
    """True for the writers' temporary files (working copies, bridge rebuilds, patch and import copies)."""
    return bool(_TEMP_NAME_RE.search(Path(path).name))


def workspace_library_files(ws: Workspace) -> list[Path]:
    """Every SchLib below ``Symbols/`` and PcbLib below ``Footprints/`` (sorted, no temp files)."""
    found: dict[str, Path] = {}
    for folder, kind in ((ws.symbols_dir, "schlib"), (ws.footprints_dir, "pcblib")):
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and library_file_kind(path) == kind and not is_temp_library_file(path):
                found.setdefault(os.path.normcase(str(path)), path)
    return sorted(found.values(), key=lambda p: (library_file_kind(p) or "", str(p).lower()))


_names_cache: dict[str, tuple[tuple[int, int], list[str]]] = {}
_names_lock = threading.Lock()


def _file_key(path: Path) -> tuple[str, tuple[int, int]] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return os.path.normcase(os.path.abspath(path)), (stat.st_mtime_ns, stat.st_size)


def cached_component_names(writer: LibraryWriter, library: Path) -> list[str] | None:
    """Component names of ``library`` (cached per file version), ``None`` if unknown.

    Uses the writer's reader (the Rust writer or the Altium backend's Rust reader); an
    Altium backend without reader returns ``None`` instead of running a script. Raises the
    reader's errors for unreadable files.
    """
    key = _file_key(library)
    if key is None:
        return []
    with _names_lock:
        cached = _names_cache.get(key[0])
        if cached is not None and cached[0] == key[1]:
            return list(cached[1])
    if writer.name != "rust" and getattr(writer, "reader", None) is None:
        return None
    names = list(writer.list_components(library))
    with _names_lock:
        if len(_names_cache) > 512:
            _names_cache.clear()
        _names_cache[key[0]] = (key[1], names)
    return list(names)


def forget_component_names(library: Path | None = None) -> None:
    """Drop cached component listings (one library or all)."""
    with _names_lock:
        if library is None:
            _names_cache.clear()
        else:
            _names_cache.pop(os.path.normcase(os.path.abspath(library)), None)
