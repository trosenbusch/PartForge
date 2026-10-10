"""Bibliotheksimport: symbols and footprints of existing Altium libraries into the open library.

Sources (:func:`scan`): a folder (searched recursively – e.g. the Celestial library with ~7 800 SchLib and
~2 150 PcbLib files), a single ``.SchLib``/``.PcbLib``, an integrated library ``.IntLib`` (its embedded
libraries – ``SchLib/<n>.schlib`` / ``PCBLib/<n>.pcblib`` = ``0x02`` + zlib of the whole file, VERIFIED – are
extracted into PartForge's import cache), a library package ``.LibPkg`` (its ``DocumentPath`` entries) or a
ZIP archive (a vendor download, an archived project – its library files are unpacked into the import cache:
:func:`extract_zip`, member paths sanitised, size bounded).
Database libraries (``.DbLib``) are listed with a note only: their part data live in a database
(Celestial: a cloud database, "Download from https://portal.altiumlibrary.com/").

:func:`run_import` (job ``libraries.import``, holds the library) copies the chosen files **unchanged** into
``Symbols\\Import\\<Ziel>\\…`` / ``Footprints\\Import\\<Ziel>\\…`` (relative paths of the source kept, so the
folder structure stays recognisable) and registers their components as ``imported`` (spec read back for
previews, pin/pad checks and usage). Copying whole files is lossless – fonts, pin texts, Mechanical 17–32,
embedded 3D models stay as Altium saved them; the house style is a separate, optional step
(:mod:`.housestyle`, ``convert``). Names: Altium finds symbols and footprints by name, PartForge registers
each name once – a component whose name is registered elsewhere (or appears twice in the source) is reported
and not registered; a file that holds nothing else is not copied.

:func:`parts_table` builds a table of registered symbols with their parameters and footprint links for the
spreadsheet import (``Bauteile anlegen``) – the import wizard then maps the columns to a category.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import io
import logging
import os
import re
import shutil
import threading
import time
import uuid
import zipfile
import zlib
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import SimpleNamespace
from typing import Any, Final, Literal

from pydantic import BaseModel, Field

from ..config import local_data_dir
from ..db import registry
from ..domain.text import plural
from ..jobs import JobContext
from ..workspace import Workspace, current
from . import compound
from .libwriter import library_file_kind
from .rustwriter import RustLibraryOps, RustWriterError, is_inside
from .sync import SyncError, _register_imported, _rel_key, _Session

log = logging.getLogger(__name__)

__all__ = [
    "ImportError_",
    "SourceFile",
    "SourceComponent",
    "ImportScan",
    "LibraryImportOptions",
    "extract_intlib",
    "extract_zip",
    "scan",
    "get_scan",
    "scan_for_target",
    "run_import",
    "import_message",
    "parts_table",
    "IMPORT_FOLDER",
]

#: Subfolder of ``Symbols\\`` / ``Footprints\\`` that receives imported libraries.
IMPORT_FOLDER: Final = "Import"
SCAN_TTL_S: Final = 6 * 3600
MAX_SCANS: Final = 8
_SAFE_SEGMENT_RE: Final = re.compile(r'[<>:"|?*\x00-\x1f]')
_LIBRARY_EXTENSIONS: Final = {".schlib": "schlib", ".pcblib": "pcblib"}
#: Uncompressed size of the library files of one ZIP archive / number of members (zip bombs, huge archives)
ZIP_MAX_BYTES: Final = 1 << 30
ZIP_MAX_MEMBERS: Final = 50_000


class ImportError_(SyncError):  # noqa: N801 - "ImportError" is a builtin
    """A source cannot be imported (German message, HTTP status)."""


# --------------------------------------------------------------------------- models


ComponentState = Literal["new", "imported", "taken", "duplicate"]


class SourceComponent(BaseModel):
    name: str
    description: str | None = None
    count: int | None = Field(default=None, description="Pins bzw. Pads")
    has_3d: bool | None = None
    state: ComponentState = "new"
    registered_library: str | None = Field(default=None, description="Wo der Name schon registriert ist")


class SourceFile(BaseModel):
    """One library of a source (``rel`` relative to the source root; IntLib members: ``<IntLib>/<n>.SchLib``)."""

    rel: str
    kind: Literal["schlib", "pcblib"]
    path: str = Field(description="Datei, die gelesen/kopiert wird (bei IntLib die entpackte Kopie)")
    size: int = 0
    components: list[SourceComponent] = Field(default_factory=list)
    problem: str | None = None
    target: str | None = Field(default=None, description="Ziel im Bibliotheksordner (relativ)")
    exists: Literal["no", "same", "different"] = "no"


class ImportScan(BaseModel):
    id: str
    source: str
    name: str = Field(description="Vorschlag für den Zielordner")
    created: str
    files: list[SourceFile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    symbols: int = 0
    footprints: int = 0
    new: int = 0
    taken: int = 0
    duplicates: int = 0
    imported: int = 0
    message: str = ""


class LibraryImportOptions(BaseModel):
    scan_id: str
    files: list[str] | None = Field(default=None, description="Gewählte Dateien (rel), None = alle")
    target: str | None = Field(default=None, description="Zielordner unter Symbols\\Import bzw. Footprints\\Import")
    replace: bool = Field(default=False, description="Geänderte, schon importierte Dateien überschreiben")
    extract_3d: bool = Field(default=False, description="Eingebettete 3D-Modelle für die Vorschau in 3D\\ ablegen")
    convert: bool = Field(default=False, description="Danach an den Hausstil angleichen (Stapelbearbeitung)")


# --------------------------------------------------------------------------- scan cache

_scans: dict[str, tuple[float, ImportScan]] = {}
_scans_lock = threading.Lock()


def _remember(scan_result: ImportScan) -> None:
    with _scans_lock:
        now = time.monotonic()
        for key in [k for k, (t, _s) in _scans.items() if now - t > SCAN_TTL_S]:
            _scans.pop(key, None)
        while len(_scans) >= MAX_SCANS:
            oldest = min(_scans, key=lambda k: _scans[k][0])
            _scans.pop(oldest, None)
        _scans[scan_result.id] = (now, scan_result)


def get_scan(scan_id: str) -> ImportScan:
    with _scans_lock:
        found = _scans.get(scan_id)
    if found is None:
        raise ImportError_("Die Quelle wurde nicht (mehr) eingelesen – bitte erneut „Einlesen“ wählen.", status=404)
    return found[1]


# --------------------------------------------------------------------------- source files


def _cache_dir() -> Path:
    folder = local_data_dir() / "import" / "libraries"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _prune_cache(max_age_s: float = 2 * 86400.0) -> None:
    cutoff = time.time() - max_age_s
    try:
        for entry in _cache_dir().iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
    except OSError:
        pass


def extract_intlib(path: Path) -> list[tuple[str, Path, str]]:
    """Unpack an IntLib into the import cache: ``[(member rel, file, kind)]`` (``<stem>.SchLib``,
    ``<stem>.PcbLib``, ``<stem>_2.PcbLib`` …). Raises :class:`ImportError_`."""
    try:
        tree = compound.read_tree_file(path)
    except Exception as exc:  # noqa: BLE001 - COM: not a compound file
        raise ImportError_(f"{path.name} ist keine lesbare integrierte Bibliothek ({exc}).", status=400) from exc
    digest = hashlib.sha1(f"{os.path.normcase(str(path))}|{path.stat().st_mtime_ns}".encode()).hexdigest()[:16]
    folder = _cache_dir() / digest
    folder.mkdir(parents=True, exist_ok=True)
    out: list[tuple[str, Path, str]] = []
    counters: Counter[str] = Counter()
    for key in sorted(tree):
        data = tree[key]
        if data is None:
            continue
        storage, _, member = key.partition("/")
        kind = {"schlib": "schlib", "pcblib": "pcblib"}.get(storage.casefold())
        if kind is None or not member:
            continue
        if not data or data[0] != 0x02:
            continue
        try:
            raw = zlib.decompress(data[1:])
        except zlib.error as exc:
            log.warning("IntLib %s: %s nicht entpackbar: %s", path, key, exc)
            continue
        if not raw.startswith(b"\xd0\xcf\x11\xe0"):
            continue
        counters[kind] += 1
        suffix = ".SchLib" if kind == "schlib" else ".PcbLib"
        stem = path.stem if counters[kind] == 1 else f"{path.stem}_{counters[kind]}"
        target = folder / f"{stem}{suffix}"
        if not target.is_file() or target.stat().st_size != len(raw):
            temp = target.with_suffix(target.suffix + ".tmp")
            temp.write_bytes(raw)
            os.replace(temp, target)
        out.append((str(PureWindowsPath(path.name, f"{stem}{suffix}")), target, kind))
    if not out:
        raise ImportError_(f"{path.name} enthält keine Symbol- oder Footprint-Bibliothek.", status=400)
    return out


def extract_zip(path: Path) -> list[tuple[str, Path, str]]:
    """Unpack the library files of a ZIP archive into the import cache: ``[(rel inside the archive, file,
    kind)]`` – ``.SchLib``/``.PcbLib`` as they are, IntLibs with their members (:func:`extract_intlib`).
    Member paths are sanitised (no drive, no ``..``, no reserved characters); at most :data:`ZIP_MAX_BYTES`
    uncompressed and :data:`ZIP_MAX_MEMBERS` members. Raises :class:`ImportError_`."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ImportError_(f"{path.name} ist kein lesbares ZIP-Archiv ({exc}).", status=400) from exc
    digest = hashlib.sha1(f"zip|{os.path.normcase(str(path))}|{path.stat().st_mtime_ns}".encode()).hexdigest()[:16]
    folder = _cache_dir() / digest
    out: list[tuple[str, Path, str]] = []
    taken: set[str] = set()  # casefolded targets: Windows paths ignore case
    total = 0
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > ZIP_MAX_MEMBERS:
            raise ImportError_(f"{path.name} enthält zu viele Dateien – bitte entpacken und den Ordner wählen.", status=400)
        for info in infos:
            parts = [
                _SAFE_SEGMENT_RE.sub("_", part).strip(" .")
                for part in PurePosixPath(info.filename.replace("\\", "/")).parts
                if part not in ("", ".", "..", "/") and not part.endswith(":")
            ]
            parts = [part for part in parts if part]
            if not parts:
                continue
            suffix = Path(parts[-1]).suffix.casefold()
            if suffix not in _LIBRARY_EXTENSIONS and suffix != ".intlib":
                continue
            total += info.file_size
            if total > ZIP_MAX_BYTES:
                raise ImportError_(f"{path.name}: die Bibliotheken im Archiv sind größer als "
                                   f"{ZIP_MAX_BYTES >> 20} MB – bitte entpacken und den Ordner wählen.", status=400)
            stem, extension = Path(parts[-1]).stem, Path(parts[-1]).suffix
            counter = 1
            while str(PureWindowsPath(*parts)).casefold() in taken:
                counter += 1
                parts[-1] = f"{stem}_{counter}{extension}"
            taken.add(str(PureWindowsPath(*parts)).casefold())
            target = folder.joinpath(*parts)
            if not is_inside(target, folder):
                continue
            if not target.is_file() or target.stat().st_size != info.file_size:
                _unzip_member(archive, info, target)
            if suffix == ".intlib":
                try:
                    members = extract_intlib(target)
                except ImportError_ as exc:
                    log.info("ZIP %s: %s", path, exc)
                    continue
                for member_rel, member, kind in members:
                    out.append((str(PureWindowsPath(*parts[:-1], member_rel)), member, kind))
            else:
                out.append((str(PureWindowsPath(*parts)), target, _LIBRARY_EXTENSIONS[suffix]))
    if not out:
        raise ImportError_(f"{path.name} enthält keine .SchLib, .PcbLib oder .IntLib.", status=400)
    return out


def _unzip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path) -> None:
    """Copy one member (never more bytes than its header announces; the CRC is checked by ``zipfile``)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.name}.{uuid.uuid4().hex[:8]}.part")
    written = 0
    try:
        with archive.open(info) as src, open(temp, "wb") as dst:
            while chunk := src.read(1 << 20):
                written += len(chunk)
                if written > info.file_size:
                    raise ImportError_(f"{info.filename}: Größe stimmt nicht mit dem Archiv überein.", status=400)
                dst.write(chunk)
        os.replace(temp, target)
    except (OSError, zipfile.BadZipFile, zlib.error) as exc:
        raise ImportError_(f"{info.filename} nicht entpackbar: {exc}", status=400) from exc
    finally:
        temp.unlink(missing_ok=True)


def _libpkg_documents(path: Path) -> list[Path]:
    """Library documents of a LibPkg (``DocumentPath=`` relative to the package)."""
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise ImportError_(f"{path.name} ist nicht lesbar: {exc}", status=400) from exc
    out: list[Path] = []
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().casefold() == "documentpath" and value.strip():
            doc = (path.parent / PureWindowsPath(value.strip()).as_posix()).resolve()
            if library_file_kind(doc) is not None and doc.is_file():
                out.append(doc)
    return out


def _dblib_note(path: Path) -> str | None:
    try:
        head = path.read_bytes()[:4000].decode("cp1252", "replace")
    except OSError:
        return None
    m = re.search(r"^ConnectionString=(.*)$", head, re.MULTILINE)
    connection = m.group(1).strip() if m else ""
    hint = f" (Verbindung: „{connection[:80]}“)" if connection and "=" not in connection[:40] else ""
    return (f"{path.name}: Datenbankbibliothek{hint} – ihre Bauteildaten liegen in der Datenbank und werden nicht "
            "übernommen; importiert werden die Symbole und Footprints der Bibliotheksdateien.")


def _source_files(source: Path) -> tuple[list[tuple[str, Path, str]], list[str]]:
    """``[(rel, file, kind)]`` of a source and German notes."""
    notes: list[str] = []
    if source.is_file():
        suffix = source.suffix.casefold()
        if suffix in _LIBRARY_EXTENSIONS:
            return [(source.name, source, _LIBRARY_EXTENSIONS[suffix])], notes
        if suffix == ".intlib":
            return extract_intlib(source), notes
        if suffix == ".zip":
            return extract_zip(source), notes
        if suffix == ".libpkg":
            docs = _libpkg_documents(source)
            if not docs:
                raise ImportError_(f"{source.name} nennt keine vorhandenen SchLib-/PcbLib-Dateien.", status=400)
            return [(_rel_to(doc, source.parent), doc, _LIBRARY_EXTENSIONS[doc.suffix.casefold()]) for doc in docs], notes
        if suffix == ".dblib":
            note = _dblib_note(source)
            raise ImportError_((note or source.name) + " Bitte den Ordner mit den Bibliotheksdateien wählen.", status=400)
        raise ImportError_(f"{source.name}: bitte einen Ordner, eine .SchLib, .PcbLib, .IntLib, .LibPkg oder .zip "
                           "wählen.", status=400)
    out: list[tuple[str, Path, str]] = []
    for root, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.casefold() not in ("history", "__previews"))
        for name in sorted(files, key=str.casefold):
            file = Path(root) / name
            suffix = file.suffix.casefold()
            if suffix in _LIBRARY_EXTENSIONS:
                out.append((_rel_to(file, source), file, _LIBRARY_EXTENSIONS[suffix]))
            elif suffix == ".intlib":
                try:
                    for member_rel, member, kind in extract_intlib(file):
                        out.append((_rel_to(file.parent, source, member_rel), member, kind))
                except ImportError_ as exc:
                    notes.append(str(exc))
            elif suffix == ".dblib":
                note = _dblib_note(file)
                if note:
                    notes.append(note)
    return out, notes


def _rel_to(path: Path, root: Path, tail: str | None = None) -> str:
    try:
        rel = str(PureWindowsPath(os.path.relpath(path, root)))
    except ValueError:
        rel = path.name
    if rel == ".":
        rel = ""
    if tail:
        rel = str(PureWindowsPath(rel) / PureWindowsPath(tail)) if rel else tail
    return rel


def safe_folder_name(name: str) -> str:
    """A folder name for the import target (letters, digits, ``_ - . ( )`` and blanks; at most 60 chars)."""
    text = _SAFE_SEGMENT_RE.sub("_", name or "").replace("\\", "_").replace("/", "_").strip(" .")
    text = re.sub(r"\s+", " ", text)[:60].strip(" .")
    return text or "Import"


def _source_segment(name: str, *, limit: int) -> str:
    """A folder or file name of the source inside the import target: like :func:`safe_folder_name`, but a library
    file keeps its extension and a name longer than ``limit`` is cut with a short hash of the full name appended –
    two long names of one source never end up in the same target."""
    suffix = PureWindowsPath(name).suffix
    if suffix.casefold() not in (".schlib", ".pcblib", ".intlib"):
        suffix = ""
    stem = name[: len(name) - len(suffix)] if suffix else name
    text = _SAFE_SEGMENT_RE.sub("_", stem).replace("\\", "_").replace("/", "_").strip(" .")
    text = re.sub(r"\s+", " ", text)
    if len(text) > limit:
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        text = f"{text[: limit - 9].rstrip(' .')}_{digest}"
    return (text or "Import") + suffix


def _target_rel(ws: Workspace, folder: str, rel: str, kind: str) -> str:
    base = Path(ws.settings.folders.symbols if kind == "schlib" else ws.settings.folders.footprints)
    names = [p for p in PureWindowsPath(rel).parts if p not in (".", "..") and not p.endswith(("\\", "/", ":"))]
    parts = [_source_segment(p, limit=100 if i == len(names) - 1 else 60) for i, p in enumerate(names)]
    if not parts:
        parts = ["Bibliothek.SchLib" if kind == "schlib" else "Bibliothek.PcbLib"]
    # an IntLib member is "<x.IntLib>/<stem>.SchLib": the member name alone (the IntLib's folder is kept)
    parts = [p for p in parts if not p.casefold().endswith(".intlib")] or parts[-1:]
    return str(PureWindowsPath(base) / IMPORT_FOLDER / safe_folder_name(folder) / PureWindowsPath(*parts))


def _sha(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


# --------------------------------------------------------------------------- scan


def _ops(session: _Session) -> RustLibraryOps:
    from .libwriter import RustLibraryWriter

    writer = session.writer()
    reader = writer.ops if isinstance(writer, RustLibraryWriter) else getattr(writer, "reader", None)
    if not isinstance(reader, RustLibraryOps):
        raise ImportError_("Zum Einlesen von Bibliotheken wird der Bibliotheks-Writer benötigt (Einstellungen › "
                           "Allgemein › Altium Designer).", status=503)
    return reader


def scan(source: str, *, ctx: JobContext | None = None) -> ImportScan:
    """Read every library of a source (names, descriptions, pin/pad counts, 3D) and compare the names with the
    registry. The result is kept for :func:`run_import` (``id``)."""
    raw = str(source or "").strip().strip('"')
    if not raw:
        raise ImportError_("Bitte einen Ordner oder eine Bibliotheksdatei angeben.", status=400)
    path = Path(raw)
    if not path.is_absolute():
        raise ImportError_(f"Der Pfad muss absolut sein: {raw}", status=400)
    if not path.exists():
        raise ImportError_(f"{path} wurde nicht gefunden.", status=404)
    ws = current()
    if is_inside(path, ws.root):
        raise ImportError_("Die Quelle liegt im Bibliotheksordner selbst – „Bibliotheken prüfen“ übernimmt solche "
                           "Dateien.", status=400)
    _prune_cache()
    session = _Session(ws, ctx)
    try:
        ops = _ops(session)
        files, notes = _source_files(path)
        name = safe_folder_name(path.stem if path.is_file() else path.name)
        result = ImportScan(id=uuid.uuid4().hex[:12], source=str(path), name=name,
                            created=_dt.datetime.now().isoformat(timespec="seconds"), notes=notes)
        for index, (rel, file, kind) in enumerate(files):
            session.check_cancelled()
            if index % 25 == 0:
                session.progress(index / max(1, len(files)), f"{index} von {len(files)} Bibliotheken gelesen …")
            entry = SourceFile(rel=rel, kind=kind, path=str(file), size=file.stat().st_size if file.is_file() else 0)
            try:
                infos = ops.scan(file)
            except (RustWriterError, OSError) as exc:
                entry.problem = f"Nicht lesbar: {str(exc).strip() or type(exc).__name__}"
                result.files.append(entry)
                continue
            entry.components = [SourceComponent(name=info.name, description=info.description, count=info.pin_count,
                                                has_3d=info.has_3d) for info in infos]
            result.files.append(entry)
        session.progress(0.95, "Namen werden mit der Bibliothek verglichen …")
        _classify(result, ws, name)
        _remember(result)
        session.progress(1.0, result.message)
        return result
    finally:
        session.finish()


def _classify(result: ImportScan, ws: Workspace, folder: str, *, check_files: bool = True) -> None:
    """Targets, ``exists`` and the name states of a scan for the target folder ``folder`` (in place; counts and
    message too). A name registered elsewhere is ``taken``, one imported from the same target ``imported``, a
    second one in the source ``duplicate`` (the first file in scan order keeps it). ``check_files=False`` keeps
    ``exists`` as it is (no hashing)."""
    symbols = {r.name.casefold(): r for r in registry.list_symbols(with_spec=False, with_usage=False)}
    footprints = {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)}
    seen: dict[tuple[str, str], str] = {}
    result.symbols = result.footprints = result.new = result.taken = result.duplicates = result.imported = 0
    for entry in result.files:
        target = _target_rel(ws, folder, entry.rel, entry.kind)
        entry.target = target
        if check_files:
            entry.exists = "no"
            target_abs = ws.abs(target)
            if target_abs is not None and target_abs.is_file():
                entry.exists = "same" if _sha(target_abs) == _source_sha(Path(entry.path)) else "different"
        known = symbols if entry.kind == "schlib" else footprints
        for comp in entry.components:
            comp.state, comp.registered_library = "new", None
            key = (entry.kind, comp.name.casefold())
            registered = known.get(comp.name.casefold())
            if registered is not None:
                same_file = registered.source == "imported" and _rel_key(registered.library) == _rel_key(target)
                comp.state = "imported" if same_file else "taken"
                comp.registered_library = registered.library
            elif key in seen:
                comp.state = "duplicate"
                comp.registered_library = seen[key]
            else:
                seen[key] = entry.rel
            if entry.kind == "schlib":
                result.symbols += 1
            else:
                result.footprints += 1
            result.new += comp.state == "new"
            result.taken += comp.state == "taken"
            result.duplicates += comp.state == "duplicate"
            result.imported += comp.state == "imported"
    result.message = scan_message(result)


_source_shas: dict[tuple[str, int, int], str | None] = {}


def _source_sha(path: Path) -> str | None:
    """SHA-256 of a source file, remembered by (path, size, mtime) – a retargeted scan compares again."""
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (os.path.normcase(str(path)), stat.st_size, stat.st_mtime_ns)
    if key not in _source_shas:
        if len(_source_shas) > 50_000:
            _source_shas.clear()
        _source_shas[key] = _sha(path)
    return _source_shas[key]


def scan_for_target(scan_id: str, target: str | None) -> ImportScan:
    """The scan as it would import into ``target`` (folder name under ``Symbols\\Import`` / ``Footprints\\Import``;
    empty = the proposal of the scan): targets, ``exists`` and name states for that folder, from the names read
    during the scan and the registry as it is now (no file is read again)."""
    stored = get_scan(scan_id)
    if not target or not target.strip():
        return stored
    folder = safe_folder_name(target)
    result = stored.model_copy(deep=True)
    _classify(result, current(), folder)
    return result


def _after_import(result: ImportScan, ws: Workspace, folder: str, imported: set[str], converted: Sequence[str]) -> None:
    """Bring the stored scan up to date after an import into its proposed folder (the page shows it again): the
    imported files exist (``same`` – ``different`` once the house style changed them), the names are classified
    against the registry as it is now. No file is hashed again."""
    if folder.casefold() != result.name.casefold():
        return
    changed = {_rel_key(rel) for rel in converted}
    try:
        for entry in result.files:
            if entry.rel in imported:
                entry.exists = "different" if _rel_key(entry.target) in changed else "same"
        _classify(result, ws, folder, check_files=False)
    except Exception as exc:  # noqa: BLE001 - the scan is a convenience; the import itself is done
        log.info("Scan nach dem Import nicht aktualisiert: %s", exc)


def scan_message(result: ImportScan) -> str:
    files = len(result.files)
    text = (f"{plural(files, 'Bibliothek', 'Bibliotheken')} gelesen: {plural(result.symbols, 'Symbol', 'Symbole')}, "
            f"{plural(result.footprints, 'Footprint', 'Footprints')}")
    extra = []
    if result.imported:
        extra.append(f"{result.imported} schon importiert")
    if result.taken:
        extra.append(f"{plural(result.taken, 'Name', 'Namen')} schon vergeben")
    if result.duplicates:
        extra.append(f"{result.duplicates} doppelt")
    return text + (f" ({', '.join(extra)})" if extra else "") + "."


# --------------------------------------------------------------------------- import


def import_message(out: Mapping[str, Any]) -> str:
    symbols, footprints = int(out.get("symbols") or 0), int(out.get("footprints") or 0)
    copied, unchanged = int(out.get("copied") or 0), int(out.get("unchanged") or 0)
    extra = []
    if not symbols and not footprints:
        text = "Bibliotheksimport: nichts übernommen"
        if unchanged:
            extra.append(f"{plural(unchanged, 'Datei', 'Dateien')} unverändert")
    else:
        text = (f"Bibliotheksimport fertig: {plural(symbols, 'Symbol', 'Symbole')} und "
                f"{plural(footprints, 'Footprint', 'Footprints')} aus {plural(copied + unchanged, 'Datei', 'Dateien')}")
        if unchanged:
            extra.append(f"davon {unchanged} unverändert" if copied else
                         ("unverändert" if unchanged == 1 else "alle unverändert"))
    if out.get("conflicts"):
        extra.append(f"{plural(len(out['conflicts']), 'Name', 'Namen')} nicht übernommen")
    if out.get("removed"):
        extra.append(f"{plural(len(out['removed']), 'nicht mehr enthaltener Name', 'nicht mehr enthaltene Namen')} "
                     "abgemeldet")
    if out.get("errors"):
        extra.append(plural(len(out["errors"]), "Fehler", "Fehler"))
    text += (f" ({', '.join(extra)})" if extra else "") + "."
    conversion = out.get("conversion")
    if isinstance(conversion, Mapping) and conversion.get("message"):
        text += " " + str(conversion["message"])
    return text


def run_import(options: LibraryImportOptions, *, ctx: JobContext | None = None) -> dict[str, Any]:
    """Copy the chosen files of a scan into the library folder and register their components (see the module
    docstring). Result: ``copied``, ``unchanged``, ``symbols``, ``footprints``, ``libraries`` (rel),
    ``conflicts`` ``[{kind, name, library, registered_library, reason}]``, ``skipped`` ``[{rel, reason}]``,
    ``errors``, ``conversion`` (with ``convert``), ``message``."""
    scan_result = get_scan(options.scan_id)
    ws = current()
    session = _Session(ws, ctx, watch=True)
    out: dict[str, Any] = {"copied": 0, "unchanged": 0, "symbols": 0, "footprints": 0, "libraries": [],
                           "conflicts": [], "skipped": [], "errors": [], "removed": [], "conversion": None,
                           "message": ""}
    wanted = {_rel_key(r) for r in options.files} if options.files is not None else None
    folder = safe_folder_name(options.target or scan_result.name)
    try:
        session.ensure_current()
        _ops(session)  # a reader is needed for the registration
        files = [f for f in scan_result.files if wanted is None or _rel_key(f.rel) in wanted]
        registered_names = {
            "schlib": {r.name.casefold(): r for r in registry.list_symbols(with_spec=False, with_usage=False)},
            "pcblib": {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)},
        }
        claimed: dict[tuple[str, str], str] = {}
        imported_rels: set[str] = set()  # source files now in the library (copied or unchanged)
        for index, entry in enumerate(files):
            session.check_cancelled()
            session.progress(index / max(1, len(files)), f"{entry.rel} …")
            if entry.problem:
                out["skipped"].append({"rel": entry.rel, "reason": entry.problem})
                continue
            source = Path(entry.path)
            if not source.is_file():
                out["skipped"].append({"rel": entry.rel, "reason": "Datei nicht mehr vorhanden."})
                continue
            target_rel = _target_rel(ws, folder, entry.rel, entry.kind)
            target = ws.abs(target_rel)
            assert target is not None
            names: list[str] = []
            for comp in entry.components:
                key = (entry.kind, comp.name.casefold())
                # first: a name an earlier file of this import took (registered by now, but a duplicate of the source)
                if key in claimed and claimed[key] != target_rel:
                    out["conflicts"].append({"kind": "symbol" if entry.kind == "schlib" else "footprint",
                                             "name": comp.name, "library": target_rel,
                                             "registered_library": claimed[key], "reason": "Name doppelt in der Quelle"})
                    continue
                registered = registered_names[entry.kind].get(comp.name.casefold())
                if registered is not None and not (
                    registered.source == "imported" and _rel_key(registered.library) == _rel_key(target_rel)
                ):
                    out["conflicts"].append({"kind": "symbol" if entry.kind == "schlib" else "footprint",
                                             "name": comp.name, "library": target_rel,
                                             "registered_library": registered.library,
                                             "reason": "Name schon registriert"})
                    continue
                names.append(comp.name)
            if not names:
                out["skipped"].append({"rel": entry.rel, "reason": "Keine übernehmbaren Namen (alle schon vergeben)."})
                continue
            state = "no"
            if target.is_file():
                state = "same" if _sha(target) == _sha(source) else "different"
            if state == "different" and not options.replace:
                out["skipped"].append({"rel": entry.rel, "reason": "Schon importiert und seither geändert – nicht "
                                                                    "überschrieben."})
                continue
            if library_file_kind(target) != entry.kind:  # pragma: no cover - _target_rel keeps the extension
                out["errors"].append({"rel": entry.rel, "message": f"Ziel {target_rel} hat keine Bibliotheksendung."})
                continue
            if state != "same":
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temp = target.with_name(f"{target.stem}.pfimport{uuid.uuid4().hex[:8]}{target.suffix}")
                    shutil.copyfile(source, temp)
                    os.replace(temp, target)
                except OSError as exc:
                    out["errors"].append({"rel": entry.rel, "message": f"Nicht kopiert: {exc}"})
                    continue
                out["copied"] += 1
            else:
                out["unchanged"] += 1
            if state == "different":
                # the new version decides: imported components of this file it no longer holds are unregistered
                # (otherwise "missing in its file" would make the next sync write the old one back)
                present = {c.name.casefold() for c in entry.components}
                for rec in list(registered_names[entry.kind].values()):
                    if (rec.source == "imported" and _rel_key(rec.library) == _rel_key(target_rel)
                            and rec.name.casefold() not in present):
                        with session.bound():
                            gone = (registry.delete_symbol(rec.name) if entry.kind == "schlib"
                                    else registry.delete_footprint(rec.name))
                        if gone:
                            out["removed"].append({"kind": "symbol" if entry.kind == "schlib" else "footprint",
                                                   "name": rec.name, "library": target_rel})
                            registered_names[entry.kind].pop(rec.name.casefold(), None)
            for name in names:
                claimed[(entry.kind, name.casefold())] = target_rel
            registered = _register_imported(session, target, names, extract_step=options.extract_3d, quiet=True)
            if entry.kind == "schlib":
                out["symbols"] += len(registered)
            else:
                out["footprints"] += len(registered)
            for rec in registered:
                registered_names[entry.kind][rec["name"].casefold()] = SimpleNamespace(  # type: ignore[assignment]
                    name=rec["name"], source="imported", library=rec["library"])
            out["libraries"].append(ws.rel(target))
            imported_rels.add(entry.rel)
            session.written.append(str(target))
        if options.convert and out["libraries"]:
            from . import housestyle as H

            session.log("Angleichen an den Hausstil (Regeln der letzten Stapelbearbeitung) …")
            selection = H.ConformSelection(sources=["imported"], libraries=list(out["libraries"]))
            conversion = H.apply(selection, H.saved_rules(), ctx=ctx)
            out["conversion"] = {k: conversion.get(k) for k in ("components", "libraries", "skipped", "errors",
                                                                 "undo", "message")}
        _after_import(scan_result, ws, folder, imported_rels, (out["conversion"] or {}).get("libraries") or [])
        out["message"] = import_message(out)
        session.progress(1.0, out["message"])
    finally:
        session.finish()
    return out


# --------------------------------------------------------------------------- parts table


_FORMULA_RE: Final = re.compile(r"^=")
#: Fixed columns of the parts table (a symbol parameter of the same name never overwrites them)
_HEAD: Final = ("Part Number", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path", "Footprint Ref 2",
                "Footprint Path 2", "Comment", "Description")
_FIXED_COLUMNS: Final = {c.casefold(): c for c in _HEAD}
_PART_NUMBER_PARAMS: Final = ("Manufacturer Part Number", "Part Number", "MPN", "Manufacturer Part No")


def parts_table(*, libraries: Sequence[str] | None = None, names: Sequence[str] | None = None) -> tuple[bytes, int]:
    """CSV (UTF-8 with BOM, ``;``) of registered symbols with their parameters and footprint links – input for
    the spreadsheet import (``Bauteile anlegen``). Returns (data, rows)."""
    ws = current()
    lib_keys = {_rel_key(lib) for lib in libraries} if libraries else None
    name_keys = {n.casefold() for n in names} if names else None
    symbols = [
        rec for rec in registry.list_symbols(with_usage=False)
        if rec.spec is not None and rec.source != "external"
        and (lib_keys is None or _rel_key(rec.library) in lib_keys)
        and (name_keys is None or rec.name.casefold() in name_keys)
    ]
    footprints = {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)}
    rows: list[dict[str, str]] = []
    params: list[str] = []
    for rec in symbols:
        spec = rec.spec
        assert spec is not None
        row: dict[str, str] = {"Library Ref": rec.name, "Library Path": rec.library}
        links = [link for link in spec.footprints if link.name]
        for index, link in enumerate(links[:2], start=1):
            suffix = "" if index == 1 else f" {index}"
            row[f"Footprint Ref{suffix}"] = link.name
            found = footprints.get(link.name.casefold())
            if found is not None and found.library:
                row[f"Footprint Path{suffix}"] = found.library
        if spec.description:
            row["Description"] = spec.description
        if spec.comment and spec.comment != "*" and not _FORMULA_RE.match(spec.comment):
            row["Comment"] = spec.comment
        values: dict[str, str] = {}
        for key, value in spec.parameters.items():
            if not key or value is None or _FORMULA_RE.match(str(value)) or str(value).strip() in ("", "*"):
                continue
            values[key] = str(value)
            if key.casefold() in _FIXED_COLUMNS:  # e.g. a parameter "Description": only where the column is empty
                fixed = _FIXED_COLUMNS[key.casefold()]
                if fixed in ("Comment", "Description") and fixed not in row:
                    row[fixed] = str(value)
                continue
            row[key] = str(value)
            if key not in params:
                params.append(key)
        by_key = {k.casefold(): v for k, v in values.items()}
        part_number = (next((by_key[p.casefold()] for p in _PART_NUMBER_PARAMS if by_key.get(p.casefold())), None)
                       or row.get("Comment") or rec.name)
        row["Part Number"] = part_number
        rows.append(row)
    if not rows:
        raise ImportError_("Keine Symbole mit Geometrie in der Auswahl – bitte zuerst importieren.", status=400)
    columns = [c for c in _HEAD if any(c in r for r in rows)] + params
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_safe(row.get(c, "")) for c in columns])
    return ("﻿" + buffer.getvalue()).encode("utf-8"), len(rows)


def _csv_safe(value: str) -> str:
    """Values Excel would run as a formula get the import's ``'`` guard (removed again on import)."""
    from ..importers.spreadsheet import needs_excel_guard

    return "'" + value if needs_excel_guard(value) else value
