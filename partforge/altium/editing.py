"""Edit a symbol or footprint in Altium Designer and take the saved version over ("In Altium bearbeiten").

Flow (ARCHITEKTUR.md §8.9)::

    start_editing(ctx, root, kind, name, bridge)   job "altium.edit": baseline of the library file, then the
                                                   bridge opens the SchLib/PcbLib in Altium and shows the
                                                   component (``edit_component``, Altium comes to the front)
    AltiumEditService (poller thread)              watches the files of the active sessions (size + mtime every
                                                   ~1.5 s); a changed file that stayed unchanged for
                                                   SETTLE_S starts the job "libraries.altium-edit"
    take_over(ctx, root, session_id)               job body: which components did the save change? read them
                                                   back, register them as ``source = "altium"``, set the manifest
    AltiumEditService.end(session_id)              stop watching (a save not taken over yet is taken over first)

**Baseline** (:class:`FileBaseline`, per library file): file state (size, mtime, SHA-256) and per component
the hash of its streams (``bytes``) and the :func:`edit_signature` of the read-back spec (``sig``).

**Which components changed** (:func:`classify`), saved file against the baseline:

* bytes unchanged → unchanged;
* written by PartForge since the baseline (the manifest is valid for the file and holds the fingerprint of
  the registry spec) → PartForge's own write, not an Altium edit;
* a component the user opened for editing (``targets``) whose bytes changed → edited – Altium may have
  changed content PartForge's model cannot show (a 3D model, a barcode text);
* any other component → edited only if its signature changed. Altium re-serialises every component of a
  file it saves (VERIFIED 2026-10-10, Altium 26.10: a plain save of a PartForge PcbLib changed the bytes of
  every footprint, sorted their primitives, swapped track end points, rounded coordinates to Altium's
  internal unit – 0.87 mm → 0.870001 mm – and turned the extruded bodies into 3D models the reader only
  reports as notes); :func:`edit_signature` ignores exactly that. It includes the footprint height stored in
  the PcbLib (``HEIGHT``): the reader derives ``spec.height`` from the 3D bodies, a height set in Altium only
  shows there (VERIFIED the same day; edited footprints also take their height from it);
* names new in the file → added (registered, unless the name is registered in another library: conflict);
  names gone → removed (status ``missing``; one new name at the same time is reported as a probable rename).

**Edited and added components** are registered from the file: spec read back (embedded STEP models extracted
into ``3D\\``), ``source = "altium"``, status ``ok`` (the status message lists what PartForge cannot show).
``spec.generator`` keeps the generator data of the former version without its geometry hashes – "Bearbeiten"
and "Neu generieren" stay possible after a confirmation and then overwrite the Altium version – plus
``altium_edit = {saved, previous_source}``. The library manifest is set to the saved file with the fingerprint
``None`` (owned, content unknown) for every component except PartForge's own writes: the sync never
regenerates this file as a whole (content PartForge cannot represent would be lost) and rewrites an
``altium`` component only when its spec is saved from PartForge again.

**Sessions** (:class:`EditSession`) are stored in the library (``pf_meta`` :data:`SESSIONS_KEY`) and survive a
restart – a file saved while PartForge was closed is taken over when the library opens again. One session per
library file (``targets`` = the components opened for editing). A session ends on request, after
:data:`MAX_IDLE_S` without a save, once Altium is no longer running (only while the file is unchanged), when
the file disappears or when no target is left in it.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from pydantic import BaseModel, Field, ValidationError

from .. import events
from ..db import meta as db_meta
from ..db import registry
from ..db.models import FootprintRecord, SymbolRecord
from ..domain.text import plural
from ..geometry.model import FootprintSpec, SymbolSpec, compat_text_dump
from ..jobs import Job, JobContext, JobManager, jobs, library_hold
from ..workspace import Workspace, current_or_none
from . import heights, preserve
from .libwriter import (
    LibraryWriter,
    RustLibraryWriter,
    WriterUnavailable,
    forget_component_names,
    library_file_kind,
)
from .rustwriter import RustLibraryOps, RustWriterError, is_inside
from .sync import (
    _clip,
    _file_state,
    _library_held,
    _load_manifest,
    _Manifest,
    _ops_for,
    _read_component,
    _records_by_names,
    _rel_key,
    _Session,
    _set_status,
    _stat,
    _store_manifest,
    _upsert_records,
    invalidate_health_cache,
    pinout_changes,
)
from .texts import WRITER

log = logging.getLogger(__name__)

__all__ = [
    "MAX_IDLE_S",
    "SESSIONS_KEY",
    "START_JOB_KIND",
    "TAKE_OVER_JOB_KIND",
    "AltiumEditService",
    "ComponentMark",
    "EditError",
    "EditResult",
    "EditSession",
    "EditSessionInfo",
    "FileBaseline",
    "byte_marks",
    "capture_baseline",
    "classify",
    "edit_signature",
    "get_edit_service",
    "set_edit_service",
    "start_editing",
    "start_service",
    "stop_service",
    "take_over",
]

Kind = Literal["symbol", "footprint"]

#: ``pf_meta`` key of the sessions of a library (JSON list of :class:`EditSession`).
SESSIONS_KEY: Final = "altium.edit.sessions"
START_JOB_KIND: Final = "altium.edit"
#: Job kind of a take-over: writes registry rows and the manifest, so it holds its library (jobs.LIBRARY_JOB_KINDS).
TAKE_OVER_JOB_KIND: Final = "libraries.altium-edit"
POLL_INTERVAL_S: Final = 1.5
#: A changed file must keep its size and time this long before it is read (Altium writes in several steps).
SETTLE_S: Final = 1.0
RETRY_S: Final = 15.0
#: Failed take-overs of one file version before the watcher waits for the next save.
MAX_ATTEMPTS: Final = 5
#: A session without a save for this long ends (the file is no longer watched).
MAX_IDLE_S: Final = 12 * 3600.0
ALTIUM_CHECK_S: Final = 10.0
#: Altium not running for this long (and the file unchanged): the sessions end.
ALTIUM_GONE_S: Final = 30.0
#: From this many changed components one batch read of the whole library is cheaper than single reads.
_READ_ALL_FROM: Final = 8
_PLACES: Final = 3  # signature precision: 1 µm (footprints, mm) / 0.001 mil (symbols)
_NAMES_IN_MESSAGE: Final = 4
_FOOTPRINT_SIG_EXCLUDE: Final = frozenset({"generator", "parameters", "family", "ipc_name", "density", "bodies", "step"})
_GENERATOR_HASHES: Final = ("geometry_hash", "land_hash")

NO_READER_MESSAGE: Final = (
    f"Zum Übernehmen von Änderungen aus Altium wird der {WRITER} benötigt (er liest die gespeicherte Bibliothek) – "
    "bitte unter Einstellungen › Allgemein › Altium Designer eintragen."
)


class EditError(RuntimeError):
    """A component cannot be edited in Altium (German message, HTTP status for the API)."""

    def __init__(self, message: str, *, status: int = 409):
        super().__init__(message)
        self.status = status


class _Retry(RuntimeError):
    """The library file is being written or is locked – the watcher tries again shortly."""


# --------------------------------------------------------------------------- models


class ComponentMark(BaseModel):
    name: str
    bytes: str = ""
    sig: str | None = None


class FileBaseline(BaseModel):
    """A library file as PartForge last took it over: file state and per component (casefolded name) its marks."""

    size: int = 0
    mtime_ns: int = 0
    sha256: str = ""
    components: dict[str, ComponentMark] = Field(default_factory=dict)

    def stat(self) -> tuple[int, int]:
        return self.size, self.mtime_ns


class EditResult(BaseModel):
    """The last take-over of a session."""

    time: str
    message: str
    edited: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class EditSession(BaseModel):
    id: str
    kind: Kind
    library: str  # workspace-relative path of the SchLib/PcbLib
    targets: list[str] = Field(default_factory=list)
    started: str
    last_activity: str
    baseline: FileBaseline
    last_result: EditResult | None = None


class EditSessionInfo(BaseModel):
    """A session as the UI sees it."""

    id: str
    kind: Kind
    library: str
    library_abs: str | None = None
    targets: list[str] = Field(default_factory=list)
    started: str
    last_activity: str
    state: Literal["watching", "saved", "checking", "error"] = Field(
        description="watching = Datei wie beim letzten Übernehmen, saved = in Altium gespeichert (wird gleich "
                    "übernommen), checking = Übernahme läuft, error = letzte Übernahme fehlgeschlagen")
    job_id: str | None = Field(default=None, description="laufender Übernahme-Job")
    last_result: EditResult | None = None
    error: str | None = None


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


# --------------------------------------------------------------------------- signature


def _num(value: float) -> float:
    rounded = round(value, _PLACES)
    return 0.0 if rounded == 0 else rounded


def _angle(value: float) -> float:
    return _num(value % 360.0) % 360.0


def _points(value: list[Any], *, closed: bool) -> list[list[float]]:
    """Canonical point sequence: closed outlines start at their smallest point in their smaller direction, open
    lines run in their smaller direction (Altium may store either)."""
    seq = [[_num(float(p.get("x", 0))), _num(float(p.get("y", 0)))] if isinstance(p, dict) else _canon(p)
           for p in value]
    if not closed or len(seq) < 3:
        return min(seq, list(reversed(seq))) if seq else seq
    if seq[0] == seq[-1]:
        seq = seq[:-1]
    candidates = []
    for ring in (seq, list(reversed(seq))):
        start = ring.index(min(ring))
        candidates.append(ring[start:] + ring[:start])
    return min(candidates)


def _normalise(data: dict[str, Any]) -> None:
    for key in ("rotation", "hole_rotation"):
        if isinstance(data.get(key), float | int) and not isinstance(data.get(key), bool):
            data[key] = _angle(float(data[key]))
    corners = ("x1", "y1", "x2", "y2")
    if all(isinstance(data.get(k), float | int) for k in corners):
        if data.get("kind") == "rect":
            data["x1"], data["x2"] = sorted((data["x1"], data["x2"]))
            data["y1"], data["y2"] = sorted((data["y1"], data["y2"]))
        elif (data["x2"], data["y2"]) < (data["x1"], data["y1"]):
            data["x1"], data["y1"], data["x2"], data["y2"] = data["x2"], data["y2"], data["x1"], data["y1"]
    start, end = data.get("start"), data.get("end")
    if isinstance(start, float | int) and isinstance(end, float | int) and not isinstance(start, bool):
        if _num((float(end) - float(start)) % 360.0) in (0.0, 360.0) and _num(float(end)) != _num(float(start)):
            data["start"], data["end"] = 0.0, 360.0  # full circle in any spelling
        else:
            data["start"], data["end"] = _angle(float(start)), _angle(float(end))


def _sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _canon(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        return _num(value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key == "points" and isinstance(item, list):
                out[key] = _points(item, closed=value.get("kind") != "line")
            else:
                out[key] = _canon(item)
        _normalise(out)
        return out
    if isinstance(value, list | tuple):
        return sorted((_canon(v) for v in value), key=_sort_key)
    return value


def edit_signature(spec: SymbolSpec | FootprintSpec, *, height: float | None = None) -> str:
    """What a user edit in Altium changes – and not what a plain save in Altium changes (see the module
    docstring): primitives in any order, track end points in either order, angles modulo 360°, polygons from any
    start point, coordinates rounded to 1 µm (mil: 0.001); footprints without 3D bodies and STEP reference.

    ``height``: the footprint height stored in the PcbLib (``HEIGHT`` parameter, :mod:`.heights`) – the reader
    derives ``spec.height`` from the 3D bodies, so a height changed in Altium shows only there (VERIFIED)."""
    if isinstance(spec, FootprintSpec):
        data = compat_text_dump(spec.model_dump(mode="json", exclude=set(_FOOTPRINT_SIG_EXCLUDE)))
        if height is not None:
            data["file_height"] = height
    else:
        data = spec.model_dump(mode="json", exclude={"generator"})
        for pin in data.get("pins") or []:
            pin.pop("group", None)
    return hashlib.sha256(_sort_key(_canon(data)).encode("utf-8")).hexdigest()[:24]


# --------------------------------------------------------------------------- reading a library


def byte_marks(path: Path, lib_kind: Literal["schlib", "pcblib"]) -> dict[str, str] | None:
    """``{casefolded component name: hash of its streams}``; ``None`` if the file cannot be read right now
    (being written, locked)."""
    tree = preserve.snapshot(path)
    if tree is None:
        return None
    out: dict[str, str] = {}
    for storage, name in preserve.component_storages(tree, lib_kind).items():
        digest = hashlib.sha256()
        prefix = f"{storage}/"
        for key in sorted(k for k in tree if k.startswith(prefix)):
            digest.update(key.encode("utf-8", "replace") + b"\0")
            digest.update(tree[key] or b"")
            digest.update(b"\0")
        out.setdefault(name, digest.hexdigest()[:24])
    return out


def _reader(writer: LibraryWriter) -> RustLibraryOps | None:
    reader = writer.ops if isinstance(writer, RustLibraryWriter) else getattr(writer, "reader", None)
    return reader if isinstance(reader, RustLibraryOps) else None


def file_heights(path: Path) -> dict[str, float]:
    """``{casefolded footprint name: height in mm}`` as stored in a PcbLib (empty if not readable)."""
    try:
        return {name.casefold(): value for name, value in heights.read_footprint_heights(path).items()}
    except heights.HeightError as exc:
        log.debug("Bauhöhen von %s nicht lesbar: %s", path, exc)
        return {}


def _signatures(reader: RustLibraryOps, path: Path, lib_kind: str, names: Mapping[str, str],
                keys: Sequence[str], stored: Mapping[str, float]) -> dict[str, str | None]:
    """:func:`edit_signature` of the components ``keys`` (casefolded) – ``None`` if one cannot be read.
    ``stored``: the footprint heights of the file (:func:`file_heights`)."""
    out: dict[str, str | None] = dict.fromkeys(keys)
    if not keys:
        return out
    if len(keys) >= _READ_ALL_FROM:
        for spec, _notes in reader.read_all_detailed(path, extract_step=False):
            key = spec.name.casefold()
            if key in out:
                out[key] = edit_signature(spec, height=stored.get(key))
        return out
    for key in keys:
        actual = names.get(key)
        if actual is None:
            continue
        spec: SymbolSpec | FootprintSpec | None
        if lib_kind == "schlib":
            spec = reader.read_symbol(path, actual)
        else:
            spec = reader.read_footprint(path, actual, extract_step=False)
        out[key] = edit_signature(spec, height=stored.get(key)) if spec is not None else None
    return out


@dataclass
class _Snapshot:
    """The library file now: state, actual names and the marks of every component."""

    state: tuple[int, int, str]
    names: dict[str, str]  # casefolded -> name in the file
    marks: dict[str, ComponentMark]
    heights: dict[str, float]  # casefolded footprint name -> height stored in the PcbLib (mm)


def _snapshot(writer: LibraryWriter, path: Path, previous: FileBaseline | None) -> _Snapshot:
    """Read the file once, consistently: raises :class:`_Retry` when it changed while it was read. Signatures
    are read only for components whose bytes differ from ``previous`` (all without one)."""
    reader = _reader(writer)
    if reader is None:
        raise EditError(NO_READER_MESSAGE, status=503)
    lib_kind = library_file_kind(path)
    if lib_kind not in ("schlib", "pcblib"):
        raise EditError(f"„{path.name}“ ist keine SchLib oder PcbLib.", status=400)
    state = _file_state(path)
    if state is None:
        raise _Retry(f"{path.name} ist gerade nicht lesbar.")
    marks = byte_marks(path, lib_kind)
    if marks is None:
        raise _Retry(f"{path.name} wird gerade geschrieben.")
    try:
        listed = reader.list_components(path)
    except (RustWriterError, OSError, RuntimeError) as exc:
        raise _Retry(f"{path.name} ist gerade nicht lesbar: {exc}") from exc
    names = {n.casefold(): n for n in listed}
    if marks and not names:
        raise _Retry(f"{path.name} ist gerade nicht lesbar.")
    old = previous.components if previous is not None else {}
    # a component without stream marks (unexpected storage layout) is compared by its signature alone
    unmarked = {k for k in names if k not in marks}
    changed = [k for k in names if k in unmarked or k not in old or old[k].bytes != marks[k]]
    stored = file_heights(path) if lib_kind == "pcblib" else {}
    try:
        sigs = _signatures(reader, path, lib_kind, names, changed, stored)
    except (RustWriterError, OSError, RuntimeError) as exc:
        raise _Retry(f"{path.name} ist gerade nicht lesbar: {exc}") from exc
    if _file_state(path) != state:
        raise _Retry(f"{path.name} wurde während des Lesens geändert.")
    out: dict[str, ComponentMark] = {}
    for key, name in names.items():
        sig = sigs[key] if key in sigs else old[key].sig
        stream = f"sig:{sig}" if key in unmarked else marks[key]
        out[key] = ComponentMark(name=name, bytes=stream, sig=sig)
    return _Snapshot(state=state, names=names, marks=out, heights=stored)


def capture_baseline(writer: LibraryWriter, path: Path, *, attempts: int = 3, pause_s: float = 0.5) -> FileBaseline:
    """The baseline of a library file (retried while the file is being written)."""
    for attempt in range(attempts):
        try:
            snap = _snapshot(writer, path, None)
        except _Retry as exc:
            if attempt + 1 >= attempts:
                raise EditError(f"{exc} Bitte in einigen Sekunden erneut versuchen.") from exc
            time.sleep(pause_s)
            continue
        return FileBaseline(size=snap.state[0], mtime_ns=snap.state[1], sha256=snap.state[2], components=snap.marks)
    raise AssertionError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------- classification


@dataclass
class Classification:
    edited: list[str] = field(default_factory=list)  # casefolded names
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    own: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)

    @property
    def taken(self) -> list[str]:
        return [*self.edited, *self.added]


def classify(
    baseline: FileBaseline,
    now: Mapping[str, ComponentMark],
    *,
    targets: Iterable[str],
    rel: str,
    manifest: _Manifest | None,
    records: Mapping[str, Any],
    fingerprint: Callable[[Any], str],
) -> Classification:
    """Sort the components of a saved file (module docstring). ``manifest``: only when it is valid for the file
    as it is now; ``records``: registry records with spec by casefolded name. Pure function."""
    wanted = {t.casefold() for t in targets}
    out = Classification()
    for key, mark in now.items():
        before = baseline.components.get(key)
        if before is not None and before.bytes == mark.bytes:
            continue
        rec = records.get(key)
        same_library = rec is not None and rec.source != "external" and _rel_key(rec.library) == _rel_key(rel)
        written = manifest.components.get(key) if manifest is not None else None
        if written is not None and same_library and rec.spec is not None and fingerprint(rec.spec) == written:
            out.own.append(key)
        elif rec is not None and not same_library:
            out.conflicts.append(key)  # registered in another library: never moved silently
        elif before is None:
            out.added.append(key)
        elif key in wanted or mark.sig is None or before.sig is None or mark.sig != before.sig:
            out.edited.append(key)
    out.removed = [key for key in baseline.components if key not in now]
    return out


# --------------------------------------------------------------------------- registry records


def _listed(lead: str, names: Sequence[str]) -> str:
    """``"<lead>: A, B."`` or ``"<lead>: A, B, C, D und 3 weitere."`` – names unquoted, so the sentence translates as a
    whole (``localizeMessage``) without touching them."""
    shown = ", ".join(names[:_NAMES_IN_MESSAGE])
    rest = len(names) - _NAMES_IN_MESSAGE
    return f"{lead}: {shown} und {rest} weitere." if rest > 0 else f"{lead}: {shown}."


def _marked_generator(spec: Any, rec: Any | None, saved: str) -> dict[str, Any]:
    """Generator data of the edited version: the former generator data (without the geometry hashes, which no
    longer describe the geometry) + ``altium_edit``."""
    old = dict(rec.spec.generator) if rec is not None and rec.spec is not None and rec.spec.generator else {}
    previous = rec.source if rec is not None else None
    if previous == "altium":
        previous = (old.get("altium_edit") or {}).get("previous_source")
    merged = {k: v for k, v in old.items() if k not in _GENERATOR_HASHES and k != "altium_edit"}
    merged.update({k: v for k, v in (spec.generator or {}).items() if k != "altium_edit"})
    merged["altium_edit"] = {"saved": saved, "previous_source": previous}
    return merged


def _edited_record(kind: Kind, rel: str, name: str, rec: Any | None, spec: Any, notes: Sequence[str],
                   saved: str, *, height: float | None = None) -> SymbolRecord | FootprintRecord:
    """The registry record of a component taken over from the file; ``height``: the footprint height stored in
    the PcbLib (wins over the height the reader derives from the 3D bodies)."""
    update: dict[str, Any] = {"name": name, "generator": _marked_generator(spec, rec, saved)}
    old_spec = rec.spec if rec is not None else None
    if isinstance(spec, FootprintSpec) and height:
        update["height"] = round(height, 4)
    if isinstance(spec, FootprintSpec) and isinstance(old_spec, FootprintSpec):
        for attr in ("family", "ipc_name", "density"):
            if not getattr(spec, attr) and getattr(old_spec, attr):
                update[attr] = getattr(old_spec, attr)
    spec = spec.model_copy(update=update)
    message = _clip("In Altium bearbeitet – die Vorschau zeigt nicht alles: " + " ".join(notes[:3])) if notes else None
    if kind == "symbol":
        return SymbolRecord(
            name=name, library=rel, source="altium", spec=spec, pin_count=len(spec.pins), part_count=spec.part_count,
            kind=rec.kind if rec is not None else None, status="ok", status_message=message,
        )
    return FootprintRecord(
        name=name, library=rel, source="altium", spec=spec,
        family=(rec.family if rec is not None and rec.family else None) or (spec.family or None),
        ipc_name=(rec.ipc_name if rec is not None and rec.ipc_name else None) or spec.ipc_name,
        pad_count=len(spec.pads), height=spec.height, step_file=spec.step.file if spec.step is not None else None,
        status="ok", status_message=message,
    )


def _change_hints(kind: Kind, rec: Any | None, spec: Any, usage: Mapping[str, int]) -> list[str]:
    """Pin-out (symbols) or pad (footprints) changes against the former version, with the usage."""
    if rec is None or rec.spec is None:
        return []
    used = usage.get(rec.name.casefold(), 0)
    users = f" {plural(used, 'Bauteil verwendet', 'Bauteile verwenden')} es – Pin/Pad-Zuordnung prüfen." if used else ""
    if kind == "symbol" and isinstance(spec, SymbolSpec) and isinstance(rec.spec, SymbolSpec):
        changes = pinout_changes(rec.spec, spec)
        if changes:
            return [f"„{rec.name}“: Pinbelegung in Altium geändert ({'; '.join(changes[:6])}).{users}"]
    if kind == "footprint" and isinstance(spec, FootprintSpec) and isinstance(rec.spec, FootprintSpec):
        have, now = set(rec.spec.pad_designators()), set(spec.pad_designators())
        if have != now:
            gone = ", ".join(sorted(have - now)[:8]) or "–"
            new = ", ".join(sorted(now - have)[:8]) or "–"
            return [f"„{rec.name}“: Pads in Altium geändert (entfernt: {gone}; neu: {new}).{users}"]
    return []


def _usage(kind: Kind) -> dict[str, int]:
    raw = registry.symbol_usage() if kind == "symbol" else registry.footprint_usage()
    folded: dict[str, int] = {}
    for name, count in raw.items():
        folded[name.casefold()] = folded.get(name.casefold(), 0) + count
    return folded


# --------------------------------------------------------------------------- session store


def _load_sessions() -> list[EditSession]:
    try:
        raw = db_meta.get_meta(SESSIONS_KEY)
    except Exception as exc:  # noqa: BLE001 - without stored sessions nothing is watched
        log.debug("Bearbeitungen in Altium nicht lesbar: %s", exc)
        return []
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except ValueError:
        return []
    out: list[EditSession] = []
    for item in items if isinstance(items, list) else []:
        with contextlib.suppress(ValidationError, TypeError):
            out.append(EditSession.model_validate(item))
    return out


def _store_sessions(sessions: Iterable[EditSession]) -> None:
    """Callers hold ``session.bound()`` (database write lock, library still open)."""
    items = [s.model_dump(mode="json") for s in sessions]
    db_meta.set_meta(SESSIONS_KEY, json.dumps(items, ensure_ascii=False, separators=(",", ":")) if items else None)


# --------------------------------------------------------------------------- service


@dataclass
class _Tracker:
    seen: tuple[int, int] | None = None  # last observed (size, mtime) that differs from the baseline
    since: float = 0.0
    job: Job | None = None
    attempts: int = 0
    retry_at: float = 0.0
    failed_stat: tuple[int, int] | None = None  # gave up on this file version (until it changes again)
    final: bool = False  # end the session after the running take-over
    error: str | None = None
    missing_polls: int = 0  # consecutive polls without the library file


def _default_altium_running() -> Callable[[], bool] | None:
    """The process check of the real program – none inside the automated test suite (refresh.live_altium_allowed)."""
    from .refresh import live_altium_allowed

    if not live_altium_allowed():
        return None
    from .bridge.process import X2_IMAGE, is_process_running

    return lambda: is_process_running(X2_IMAGE)


class AltiumEditService:
    """The active "In Altium bearbeiten" sessions of the open library and the watcher of their files."""

    def __init__(
        self,
        *,
        poll_interval_s: float = POLL_INTERVAL_S,
        settle_s: float = SETTLE_S,
        retry_s: float = RETRY_S,
        max_idle_s: float = MAX_IDLE_S,
        altium_running: Callable[[], bool] | None | Literal["default"] = "default",
        altium_check_s: float = ALTIUM_CHECK_S,
        altium_gone_s: float = ALTIUM_GONE_S,
        job_manager: JobManager | None = None,
        workspace_provider: Callable[[], Workspace | None] = current_or_none,
        clock: Callable[[], float] = time.monotonic,
    ):
        """``altium_running``: process check for ending sessions when Altium was closed (``None`` = never;
        the default is off inside the automated test suite)."""
        self.poll_interval_s = float(poll_interval_s)
        self.settle_s = float(settle_s)
        self.retry_s = float(retry_s)
        self.max_idle_s = float(max_idle_s)
        self._altium_running = _default_altium_running() if altium_running == "default" else altium_running
        self.altium_check_s = float(altium_check_s)
        self.altium_gone_s = float(altium_gone_s)
        self._jobs = job_manager or jobs
        self._workspace = workspace_provider
        self._clock = clock
        self._lock = threading.RLock()
        self._root: str | None = None  # library whose sessions are loaded (normalised)
        self._sessions: dict[str, EditSession] = {}
        self._trackers: dict[str, _Tracker] = {}
        self._idle_since: dict[str, float] = {}  # monotonic time of the last activity per session
        self._altium_checked = 0.0
        self._altium_missing_since: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._unsubscribers: list[Callable[[], None]] = []

    # -- lifecycle --------------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, *, thread: bool = True) -> None:
        """Subscribe to library switches, load the sessions of the open library and start the watcher thread."""
        with self._lock:
            if not self._unsubscribers:
                self._unsubscribers = [
                    events.subscribe(events.WORKSPACE_OPENED, self._on_opened),
                    events.subscribe(events.WORKSPACE_CLOSED, self._on_closed),
                ]
        ws = self._workspace()
        if ws is not None:
            self.load(ws)
        if thread and not self.running:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="partforge-altium-edit", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            unsubscribers, self._unsubscribers = self._unsubscribers, []
        for unsubscribe in unsubscribers:
            with contextlib.suppress(Exception):
                unsubscribe()
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _on_opened(self, ws: Workspace | None = None, *_args: Any, **_kwargs: Any) -> None:
        target = ws if isinstance(ws, Workspace) else self._workspace()
        if target is not None:
            self.load(target)

    def _on_closed(self, *_args: Any, **_kwargs: Any) -> None:
        with self._lock:
            self._root = None
            self._sessions.clear()
            self._trackers.clear()
            self._idle_since.clear()

    def load(self, ws: Workspace) -> list[EditSession]:
        """Load the stored sessions of ``ws`` (the open library)."""
        sessions = _load_sessions()
        now = self._clock()
        with self._lock:
            self._root = _norm(ws.root)
            self._sessions = {s.id: s for s in sessions}
            self._trackers = {s.id: _Tracker() for s in sessions}
            self._idle_since = {s.id: now - _age_s(s.last_activity) for s in sessions}
        if sessions:
            log.info("%s in Altium werden beobachtet", plural(len(sessions), "Bearbeitung", "Bearbeitungen"))
        return sessions

    def _run(self) -> None:
        while not self._stop.wait(self.poll_interval_s):
            try:
                self.poll()
            except Exception:  # noqa: BLE001 - the watcher must keep running
                log.exception("Beobachtung der in Altium bearbeiteten Bibliotheken fehlgeschlagen")

    # -- sessions -----------------------------------------------------------------------
    def _bound_to(self, ws: Workspace) -> bool:
        with self._lock:
            return self._root is not None and self._root == _norm(ws.root)

    def sessions(self) -> list[EditSession]:
        with self._lock:
            return [s.model_copy(deep=True) for s in self._sessions.values()]

    def session(self, session_id: str) -> EditSession | None:
        with self._lock:
            found = self._sessions.get(session_id)
            return found.model_copy(deep=True) if found is not None else None

    def session_for(self, rel: str) -> EditSession | None:
        with self._lock:
            found = next((s for s in self._sessions.values() if _rel_key(s.library) == _rel_key(rel)), None)
            return found.model_copy(deep=True) if found is not None else None

    def put(self, session: EditSession, sync_session: _Session) -> None:
        """Add or replace a session and store all of them (in the library of ``sync_session``)."""
        with sync_session.bound():
            with self._lock:
                if not self._bound_to(sync_session.ws):
                    self.load(sync_session.ws)
                self._sessions[session.id] = session.model_copy(deep=True)
                self._trackers.setdefault(session.id, _Tracker())
                self._idle_since[session.id] = self._clock()
                snapshot = list(self._sessions.values())
            _store_sessions(snapshot)

    def remove(self, session_id: str, sync_session: _Session) -> EditSession | None:
        with sync_session.bound():
            with self._lock:
                gone = self._sessions.pop(session_id, None)
                self._trackers.pop(session_id, None)
                self._idle_since.pop(session_id, None)
                snapshot = list(self._sessions.values())
            if gone is not None:
                _store_sessions(snapshot)
        return gone

    def info(self, ws: Workspace) -> list[EditSessionInfo]:
        out: list[EditSessionInfo] = []
        with self._lock:
            items = [(s.model_copy(deep=True), self._trackers.get(s.id)) for s in self._sessions.values()]
        for session, tracker in sorted(items, key=lambda item: item[0].started):
            path = ws.abs(session.library)
            job = tracker.job if tracker is not None else None
            running = job is not None and job.status in ("queued", "running")
            stat = _stat(path) if path is not None else None
            if running:
                state: Literal["watching", "saved", "checking", "error"] = "checking"
            elif tracker is not None and tracker.error:
                state = "error"
            elif stat != session.baseline.stat():
                state = "saved"
            else:
                state = "watching"
            out.append(EditSessionInfo(
                id=session.id, kind=session.kind, library=session.library,
                library_abs=str(path) if path is not None else None, targets=list(session.targets),
                started=session.started, last_activity=session.last_activity, state=state,
                job_id=job.id if running and job is not None else None, last_result=session.last_result,
                error=tracker.error if tracker is not None else None,
            ))
        return out

    # -- watcher ------------------------------------------------------------------------
    def _altium_gone(self, now: float) -> bool:
        check = self._altium_running
        if check is None:
            return False
        if now - self._altium_checked >= self.altium_check_s:
            self._altium_checked = now
            try:
                running = bool(check())
            except Exception:  # noqa: BLE001 - unknown counts as running
                running = True
            self._altium_missing_since = None if running else (self._altium_missing_since or now)
        return self._altium_missing_since is not None and now - self._altium_missing_since >= self.altium_gone_s

    def poll(self) -> list[Job]:
        """One round of the watcher (also called by tests): start a take-over for every settled change, end
        idle sessions. Returns the jobs it started."""
        now = self._clock()
        ws = self._workspace()
        with self._lock:
            if ws is None or not self._bound_to(ws) or not self._sessions:
                return []
            items = [(s.model_copy(deep=True), self._trackers.setdefault(s.id, _Tracker())) for s in self._sessions.values()]
        gone = self._altium_gone(now)
        started: list[Job] = []
        for session, tracker in items:
            path = ws.abs(session.library)
            stat = _stat(path) if path is not None else None
            with self._lock:
                job = tracker.job
                if job is not None:
                    if job.status in ("queued", "running"):
                        continue
                    tracker.job = None
                    self._after_job(tracker, job, stat, now)
            if stat is None and session.baseline.stat() is not None:
                # The library file is gone (deleted, or the sync removed its last component): nothing to watch.
                # After a second look, so that Altium replacing the file during a save is not taken for a deletion.
                tracker.missing_polls += 1
                if tracker.missing_polls >= 2:
                    self._end_quietly(ws, session.id, "Bibliotheksdatei nicht mehr vorhanden")
                continue
            tracker.missing_polls = 0
            if stat == session.baseline.stat():
                tracker.seen, tracker.failed_stat = None, None
                idle = now - self._idle_since.get(session.id, now)
                if gone:
                    self._end_quietly(ws, session.id, "Altium Designer wurde beendet")
                elif idle >= self.max_idle_s:
                    self._end_quietly(ws, session.id, "seit Längerem nicht mehr in Altium gespeichert")
                continue
            if stat != tracker.seen:
                tracker.seen, tracker.since = stat, now
                continue
            if now - tracker.since < self.settle_s or tracker.failed_stat == stat or now < tracker.retry_at:
                continue
            job = self.submit_take_over(ws, session.id, final=tracker.final, trigger="auto")
            if job is not None:
                started.append(job)
        return started

    def _after_job(self, tracker: _Tracker, job: Job, stat: tuple[int, int] | None, now: float) -> None:
        result = job.result if isinstance(job.result, dict) else {}
        if job.status == "failed":
            tracker.attempts += 1
            tracker.error = job.error or job.message
            tracker.retry_at = now + self.retry_s * tracker.attempts
            if tracker.attempts >= MAX_ATTEMPTS:
                tracker.failed_stat = stat
        elif job.status == "done" and result.get("retry"):
            tracker.retry_at = now + self.settle_s
        elif job.status == "done":
            tracker.attempts, tracker.error, tracker.retry_at = 0, None, 0.0
            tracker.final = False

    def submit_take_over(self, ws: Workspace, session_id: str, *, final: bool = False, trigger: str = "manual") -> Job | None:
        """Start the take-over job of a session (or return the one already running)."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            tracker = self._trackers.setdefault(session_id, _Tracker())
            tracker.final = tracker.final or final
            if tracker.job is not None and tracker.job.status in ("queued", "running"):
                return tracker.job
            name = Path(session.library.replace("\\", "/")).name
            job = self._jobs.submit(TAKE_OVER_JOB_KIND, f"Änderungen aus Altium übernehmen: {name}", take_over,
                                    str(ws.root), session_id, final=tracker.final, trigger=trigger, service=self)
            tracker.job = job
            tracker.seen = None
            return job

    def end(self, ws: Workspace, session_id: str) -> Job | None:
        """End a session: a save not taken over yet is taken over first (the job ends the session); otherwise it
        ends at once (``None``). :class:`KeyError` if there is no such session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise KeyError(session_id)
            tracker = self._trackers.setdefault(session_id, _Tracker())
            running = tracker.job if tracker.job is not None and tracker.job.status in ("queued", "running") else None
            if running is not None:
                tracker.final = True
                return running
        path = ws.abs(session.library)
        if path is not None and path.is_file() and _stat(path) != session.baseline.stat():
            return self.submit_take_over(ws, session_id, final=True, trigger="end")
        with library_hold(None, ws.root) as held:
            sync_session = _Session(held, None)
            self.remove(session_id, sync_session)
        log.info("Bearbeitung von %s in Altium beendet", session.library)
        return None

    def _end_quietly(self, ws: Workspace, session_id: str, reason: str) -> None:
        try:
            with library_hold(None, ws.root) as held:
                gone = self.remove(session_id, _Session(held, None))
        except Exception as exc:  # noqa: BLE001 - LibraryChanged, database errors: tried again in the next round
            log.debug("Bearbeitung %s nicht beendet: %s", session_id, exc)
            return
        if gone is not None:
            log.info("Bearbeitung von %s in Altium beendet (%s)", gone.library, reason)

    def note_activity(self, session_id: str) -> None:
        with self._lock:
            self._idle_since[session_id] = self._clock()

    def wait_idle(self, timeout_s: float = 10.0) -> bool:
        """Wait until no take-over job of this service runs (tests)."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self._lock:
                busy = any(t.job is not None and t.job.status in ("queued", "running") for t in self._trackers.values())
            if not busy:
                return True
            time.sleep(0.02)
        return False


def _age_s(iso: str) -> float:
    try:
        return max(0.0, (_dt.datetime.now() - _dt.datetime.fromisoformat(iso)).total_seconds())
    except ValueError:
        return 0.0


# --------------------------------------------------------------------------- jobs


def _editable(ws: Workspace, kind: Kind, name: str) -> tuple[Any, Path]:
    """The registered component and its library file – or :class:`EditError` saying why it cannot be edited."""
    label = "Symbol" if kind == "symbol" else "Footprint"
    rec = registry.get_symbol(name, with_usage=False) if kind == "symbol" else registry.get_footprint(name, with_usage=False)
    if rec is None:
        raise EditError(f"{label} „{name}“ ist nicht registriert.", status=404)
    if rec.source == "external":
        raise EditError(f"{label} „{rec.name}“ gehört zu einer externen Bibliothek – PartForge übernimmt dort keine "
                        "Änderungen. Bitte die Bibliothek selbst in Altium öffnen.")
    path = ws.abs(rec.library) if rec.library else None
    if path is None or not is_inside(path, ws.root):
        raise EditError(f"{label} „{rec.name}“ hat keine Bibliotheksdatei im Bibliotheksordner.")
    if not path.is_file():
        raise EditError(f"Die Bibliotheksdatei {rec.library} wurde nicht gefunden – bitte zuerst „Synchronisieren“.")
    if rec.status in ("pending", "error", "missing"):
        raise EditError(f"{label} „{rec.name}“ ist noch nicht in {path.name} geschrieben – bitte zuerst "
                        "„Synchronisieren“.")
    expected = "schlib" if kind == "symbol" else "pcblib"
    if library_file_kind(path) != expected:
        raise EditError(f"„{path.name}“ ist keine {'SchLib' if kind == 'symbol' else 'PcbLib'}.", status=400)
    return rec, path


def start_editing(ctx: JobContext, root: str, kind: Kind, name: str, bridge: Any, *,
                  service: AltiumEditService | None = None) -> dict[str, Any]:
    """Job ``altium.edit``: record the baseline (or continue the session of this file), then open the library in
    Altium and show the component there."""
    service = service or get_edit_service()
    with library_hold(ctx, root) as ws:
        session = _Session(ws, ctx, watch=True)
        try:
            ctx.progress(0.05, f"„{name}“ wird für die Bearbeitung in Altium vorbereitet …")
            rec, path = _editable(ws, kind, name)
            rel = ws.rel(path)
            writer = session.writer()
            if _reader(writer) is None:
                raise EditError(NO_READER_MESSAGE, status=503)
            existing = service.session_for(rel)
            created = existing is None
            if existing is not None and _stat(path) != existing.baseline.stat():
                ctx.log(f"{path.name} wurde seit dem letzten Übernehmen gespeichert – Änderungen werden zuerst "
                        "übernommen.", "info")
                _take_over(session, service, existing.id, final=False, trigger="start")
                existing = service.session_for(rel)
                created = existing is None
            if existing is None:
                ctx.progress(0.2, f"Stand von {path.name} wird festgehalten …")
                stamp = _now()
                edit = EditSession(id=uuid.uuid4().hex[:12], kind=kind, library=rel, targets=[rec.name], started=stamp,
                                   last_activity=stamp, baseline=capture_baseline(writer, path))
                session.check_cancelled()  # reading the library is the slow step
            else:
                edit = existing
                if rec.name.casefold() not in {t.casefold() for t in edit.targets}:
                    edit.targets.append(rec.name)
                edit.last_activity = _now()
            if rec.name.casefold() not in edit.baseline.components:
                raise EditError(f"„{rec.name}“ ist nicht in {path.name} enthalten – bitte zuerst „Synchronisieren“.")
            session.check_cancelled()
            service.put(edit, session)
            ctx.progress(0.6, f"{path.name} wird in Altium geöffnet …")
            try:
                focus = bridge.edit_component(path, rec.name, "SCHLIB" if kind == "symbol" else "PCBLIB")
            except BaseException:
                if created:
                    with contextlib.suppress(Exception):
                        service.remove(edit.id, session)
                raise
            if focus.found:
                message = (f"„{rec.name}“ ist in Altium geöffnet – nach dem Speichern dort übernimmt PartForge die "
                           "Änderungen automatisch.")
            else:
                message = (f"{path.name} ist in Altium geöffnet, „{rec.name}“ wurde dort aber nicht gefunden – "
                           "bitte im Bibliotheksfenster auswählen. Gespeicherte Änderungen übernimmt PartForge automatisch.")
                ctx.log(message, "warn")
            if focus.modified:
                ctx.log(f"{path.name} hat in Altium ungespeicherte Änderungen – PartForge übernimmt sie, sobald sie "
                        "gespeichert sind.", "info")
            ctx.log(message, "success" if focus.found else "warn")
            ctx.progress(1.0, message)
            return {
                "message": message, "kind": kind, "name": rec.name, "library": rel, "library_abs": str(path),
                "session": edit.id, "found": focus.found, "was_open": focus.was_open, "modified": focus.modified,
                "continued": not created,
            }
        finally:
            session.finish()


def take_over(ctx: JobContext, root: str, session_id: str, *, final: bool = False, trigger: str = "manual",
              service: AltiumEditService | None = None) -> dict[str, Any]:
    """Job ``libraries.altium-edit``: take over what was saved in Altium (see the module docstring). ``final``:
    the session ends afterwards."""
    service = service or get_edit_service()
    with library_hold(ctx, root) as ws:
        session = _Session(ws, ctx, watch=True)
        try:
            return _take_over(session, service, session_id, final=final, trigger=trigger)
        finally:
            session.finish()


def _take_over(session: _Session, service: AltiumEditService, session_id: str, *, final: bool,
               trigger: str) -> dict[str, Any]:
    ws, ctx = session.ws, session.ctx
    edit = service.session(session_id)
    base: dict[str, Any] = {"session": session_id, "trigger": trigger, "edited": [], "added": [], "removed": [],
                            "conflicts": [], "warnings": [], "ended": False, "retry": False, "quiet": False}
    if edit is None:
        message = "Die Bearbeitung in Altium ist bereits beendet."
        session.progress(1.0, message)
        return {**base, "message": message, "quiet": True, "ended": True}
    ops = _ops_for(edit.kind)
    path = ws.abs(edit.library)
    base.update(kind=edit.kind, library=edit.library)
    if path is None or not path.is_file():
        service.remove(session_id, session)
        message = f"{edit.library} wurde nicht gefunden – die Bearbeitung in Altium ist beendet."
        session.log(message, "warn")
        session.progress(1.0, message)
        return {**base, "message": message, "ended": True}
    session.progress(0.1, f"{path.name} wird gelesen …")
    writer = session.writer()
    with _library_held(path) as refusal:
        if refusal:
            message = f"{path.name} wird gerade von PartForge geschrieben – die Übernahme folgt gleich."
            session.progress(1.0, message)
            return {**base, "message": message, "retry": True, "quiet": True}
        state = _file_state(path)
        if state is not None and state[0] == edit.baseline.size and state[2] == edit.baseline.sha256:
            if state[1] != edit.baseline.mtime_ns:
                edit.baseline.mtime_ns = state[1]
                service.put(edit, session)
            return _finish(session, service, edit, base, final=final, message=f"{path.name} ist unverändert.",
                           quiet=True)
        try:
            snap = _snapshot(writer, path, edit.baseline)
        except _Retry as exc:
            message = f"{exc} Die Übernahme folgt gleich."
            session.progress(1.0, message)
            return {**base, "message": message, "retry": True, "quiet": True}
        rel = edit.library
        manifest = _load_manifest(rel)
        valid = manifest is not None and manifest.matches(path)
        keys = list(dict.fromkeys([*snap.marks, *edit.baseline.components]))
        records = _records_by_names(edit.kind, [snap.names.get(k) or edit.baseline.components[k].name for k in keys])
        found = classify(edit.baseline, snap.marks, targets=edit.targets, rel=rel, manifest=manifest if valid else None,
                         records=records, fingerprint=ops.fingerprint)
        session.check_cancelled()
        saved = _now()
        usage = _usage(edit.kind) if found.edited and any(records.get(k) is not None for k in found.edited) else {}
        new_records: list[Any] = []
        unreadable: list[str] = []
        for index, key in enumerate(found.taken):
            session.progress(0.3 + 0.5 * index / max(1, len(found.taken)), f"„{snap.names[key]}“ wird übernommen …")
            notes: list[str] = []
            try:
                spec = _read_component(writer, path, snap.names[key], extract_step=True, notes=notes)
            except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
                session.log(f"„{snap.names[key]}“ aus {path.name} nicht lesbar: {exc}", "warn")
                spec = None
            if spec is None:
                unreadable.append(snap.names[key])
                continue
            rec = records.get(key)
            name = rec.name if rec is not None else snap.names[key]
            for hint in _change_hints(edit.kind, rec, spec, usage):
                base["warnings"].append(hint)
                session.log(hint, "warn")
            new_records.append(_edited_record(edit.kind, rel, name, rec, spec, notes, saved,
                                              height=snap.heights.get(key)))
        # gone from the file: reported for registered components of this file only (PartForge deleting one of
        # its own components is no Altium edit)
        gone = [k for k in found.removed if records.get(k) is not None and records[k].source != "external"
                and _rel_key(records[k].library) == _rel_key(rel)]
        removed_names = [records[k].name for k in gone]
        added_names = [snap.names[k] for k in found.added]
        renamed = removed_names[0] if len(gone) == 1 and len(found.added) == 1 else None
        with session.bound():
            if new_records:
                _upsert_records(ops, new_records)
            for key in gone:
                rec = records[key]
                if renamed is not None:
                    message = (f"Fehlt nach dem Speichern in Altium in {rel} – vermutlich in „{added_names[0]}“ "
                               f"umbenannt; Bauteile verweisen weiter auf „{rec.name}“.")
                else:
                    message = f"Fehlt nach dem Speichern in Altium in {rel} (gelöscht oder umbenannt)."
                _set_status(edit.kind, rec.name, "missing", message)
            if manifest is not None:
                own = set(found.own)
                taken = {r.name.casefold() for r in new_records}
                components: dict[str, str | None] = {}
                for key in snap.marks:
                    if key in own:
                        components[key] = manifest.components.get(key)
                    elif key in manifest.components or key in taken:
                        components[key] = None
                _store_manifest(rel, _Manifest(rel=rel, size=snap.state[0], mtime_ns=snap.state[1],
                                               sha256=snap.state[2], components=components))
        forget_component_names(path)
        invalidate_health_cache()
        conflicts = [snap.names[k] for k in found.conflicts]
        for name in conflicts:
            rec = records.get(name.casefold())
            where = rec.library if rec is not None else "einer anderen Bibliothek"
            hint = f"„{name}“ wurde nicht übernommen – der Name ist schon in {where} registriert."
            base["warnings"].append(hint)
            session.log(hint, "warn")
        for name in unreadable:
            base["warnings"].append(f"„{name}“ ist in {path.name} nicht lesbar und wurde nicht übernommen.")
        # the new baseline: the file as taken over now
        edit.baseline = FileBaseline(size=snap.state[0], mtime_ns=snap.state[1], sha256=snap.state[2],
                                     components=snap.marks)
        targets: list[str] = []
        for target in edit.targets:
            key = target.casefold()
            if key in snap.marks:
                targets.append(snap.names[key])
            elif renamed is not None and renamed.casefold() == key:
                targets.append(added_names[0])
        edit.targets = list(dict.fromkeys(targets))
        edited = [r.name for r in new_records if r.name.casefold() in set(found.edited)]
        added = [r.name for r in new_records if r.name.casefold() in set(found.added)]
        lines: list[str] = []
        if edited or added:
            lines.append(_listed("Aus Altium übernommen", [*edited, *added]))
        if renamed is not None:
            lines.append(f"„{renamed}“ wurde in Altium vermutlich in „{added_names[0]}“ umbenannt – Bauteile verweisen "
                         f"weiter auf „{renamed}“.")
        elif removed_names:
            lines.append(_listed(f"Nach dem Speichern in Altium fehlt in {path.name}", removed_names))
        if conflicts:
            lines.append(_listed("Nicht übernommen (Name schon woanders registriert)", conflicts))
        quiet = not lines
        if quiet:
            lines.append(f"Keine Änderung aus Altium in {path.name} – nur PartForge hat die Datei geschrieben."
                         if found.own else f"{path.name} wurde in Altium ohne inhaltliche Änderung gespeichert.")
        if edited or added or removed_names:
            edit.last_activity = saved
            service.note_activity(session_id)
            edit.last_result = EditResult(time=saved, message=lines[0], edited=edited, added=added,
                                          removed=removed_names)
        base.update(edited=edited, added=added, removed=removed_names, conflicts=conflicts, renamed=renamed,
                    own=[snap.names[k] for k in found.own])
        if not edit.targets and not final:
            lines.append(f"In {path.name} ist kein in Altium geöffnetes Bauteil mehr – die Bearbeitung ist beendet.")
            final = True
        return _finish(session, service, edit, base, final=final, message="\n".join(lines), quiet=quiet)


def _finish(session: _Session, service: AltiumEditService, edit: EditSession, base: dict[str, Any], *,
            final: bool, message: str, quiet: bool) -> dict[str, Any]:
    if final:
        service.remove(edit.id, session)
        base["ended"] = True
        if quiet:
            message = f"Bearbeitung von {Path(edit.library.replace(chr(92), '/')).name} in Altium beendet."
            quiet = False
    else:
        service.put(edit, session)
    level: Literal["info", "success", "warn"] = "info" if quiet else ("warn" if base["warnings"] else "success")
    for line in message.split("\n"):
        session.log(line, level)
    session.progress(1.0, message)
    return {**base, "message": message, "quiet": quiet}


# --------------------------------------------------------------------------- process-wide service

_service_lock = threading.Lock()
_service: AltiumEditService | None = None
_users = 0


def get_edit_service() -> AltiumEditService:
    """The process-wide service (created on first use, not started)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = AltiumEditService()
        return _service


def set_edit_service(service: AltiumEditService | None) -> AltiumEditService | None:
    """Replace the process-wide service (tests); returns the previous one (not stopped)."""
    global _service
    with _service_lock:
        previous, _service = _service, service
    return previous


def start_service() -> None:
    """Start the watcher (reference counted; the API router's lifespan)."""
    global _users
    with _service_lock:
        _users += 1
        if _users > 1:
            return
    get_edit_service().start()


def stop_service() -> None:
    global _users
    with _service_lock:
        _users = max(0, _users - 1)
        if _users:
            return
        service = _service
    if service is not None:
        service.stop()
