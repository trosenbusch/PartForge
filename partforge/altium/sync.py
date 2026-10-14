"""Library synchronisation: registry (pf_symbols / pf_footprints) <-> SchLib/PcbLib files.

Contract (ARCHITEKTUR.md §8.4, binding signatures)::

    ensure_symbols(specs, *, category=None, source="generated", ctx=None, library=None) -> list[SymbolRecord]
    ensure_footprints(specs, *, source="generated", ctx=None, library=None) -> list[FootprintRecord]
    sync_pending(ctx=None) -> dict
    scan_library(path) -> list[ComponentInfo]
    resolve_library_choice(kind, raw) -> Path        # explicit target library of a save (SyncError 400)
    library_health() -> dict                         # file-level checks (LibraryHealthIssue)
    footprint_height_problems() / repair_footprint_heights(names=None, ctx=None)

How ``ensure_*`` writes (one batch per library file, under the process-wide library lock):

1. **Registry is the desired state.** Every spec is registered (``pf_symbols`` /
   ``pf_footprints``); the status tells whether the file matches (``ok``), the write is still
   to be done (``pending`` – e.g. no library writer available) or failed (``error``);
   :func:`sync_pending` retries ``pending`` and ``error``.
2. **Target file.** Existing records keep their library (inside the workspace); new ones go
   to :func:`~partforge.altium.libwriter.symbol_library_path` /
   :func:`~partforge.altium.libwriter.footprint_library_path`. Parts referencing a symbol or
   footprint whose file changed are updated through :func:`partforge.db.parts.set_library_path`.
3. **Skip unchanged.** A spec whose fingerprint (:func:`symbol_fingerprint`,
   :func:`footprint_fingerprint` – the footprint fingerprint covers the generator's
   ``geometry_hash``/``land_hash`` content plus the description) equals the registered one,
   with status ``ok`` and present in its file, is not written again.
4. **Pin-out protection.** A different pin-out (``{designator: (pin name, part)}``) for an
   existing symbol name is refused with a German message (``allow_pin_changes=True`` after the
   user confirmed); nothing is written or registered in that case.
   An ``altium`` component (edited in Altium, :mod:`partforge.altium.editing`) is never skipped as unchanged:
   saving it from PartForge replaces the Altium version on purpose, even with the same geometry.
5. **Never overwrite what PartForge does not own.** A component of the same name that is
   already in the target file but was neither written by PartForge nor taken over into the
   registry is *adopted* (registered from the file as ``imported``, not written). A symbol
   whose pin-out differs is refused instead (``sync_pending``: reported as ``error``).
6. **Library manifest.** After every write PartForge records per library file (``pf_meta``)
   the file state and, per component, the fingerprint it wrote. A library is regenerated in
   ONE ``write_library_full`` call only with the Rust writer, only while the file is
   unchanged since PartForge's last write, and only if PartForge wrote every component in it
   from its registry spec – so neither lossy read-backs of imported components nor edits saved
   in Altium are ever lost. Otherwise only the changed components are upserted (the Altium
   backend always upserts: its upsert carries the data-loss guard).
7. **3D.** Footprints with extruded bodies get a STEP file ``<ws>/3D/<name>.step`` (embedded
   by the writer; regenerated whenever the bodies change); ``FootprintRecord.step_file``
   points to it. Vendor models are never overwritten.
8. **Altium.** If Altium runs, a library that is open *and modified* there is not written
   ("In Altium geöffnet und ungespeichert – bitte speichern oder schließen"); an open,
   unmodified one is reloaded afterwards (``settings.altium.auto_reload_libraries``).
   :data:`events.LIBRARIES_WRITTEN` is emitted with the written files.
9. **Bound to its library.** Every registry/parts write checks – under the database write
   lock – that the library the operation started in is still the open one; after a switch
   (or ``WORKSPACE_CLOSED``/``WORKSPACE_OPENED``) the operation stops (``JobCancelled`` in a
   job, else :class:`SyncError` 409) and never writes into the other library's database.

External libraries (``partforge-external.json`` in the workspace) are registered read-only:
PartForge lists and previews their components and registers single components with
``source="external"`` (absolute library path) – it never writes them.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import functools
import hashlib
import itertools
import json
import logging
import os
import re
import shutil
import threading
import time
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Final, Literal, NoReturn, cast

from pydantic import BaseModel, Field, ValidationError

from .. import events
from ..config import load_settings
from ..db import core as db_core
from ..db import meta as db_meta
from ..db import registry
from ..db.models import FootprintRecord, HealthIssue, RecordSource, RecordStatus, SymbolRecord
from ..domain.text import plural
from ..geometry.model import FootprintSpec, StepModel, SymbolSpec, compat_text_dump
from ..jobs import CANCEL_LIBRARY_SWITCH, JobCancelled, JobContext
from ..workspace import SymbolStyle, Workspace, current, current_or_none
from . import heights, stackup
from .libwriter import (
    LibraryKind,
    LibraryWriter,
    RustLibraryWriter,
    WriterUnavailable,
    cached_component_names,
    footprint_library_path,
    forget_component_names,
    get_writer,
    is_temp_library_file,
    library_file_kind,
    safe_file_stem,
    symbol_library_path,
    workspace_library_files,
)
from .models import ComponentInfo, WriteResult
from .texts import WRITER
from .rustwriter import (
    LibraryLocked,
    file_access_message,
    RustLibraryOps,
    RustProcessError,
    RustTimeoutError,
    RustValidationError,
    RustWriterError,
    RustWriterUnavailable,
    footprint_to_rust,
    is_inside,
    library_backup_dir,
    library_backups,
    library_lock,
    symbol_to_rust,
    validate_footprint_payload,
    validate_symbol_payload,
)

log = logging.getLogger(__name__)

__all__ = [
    "ALTIUM_MODIFIED_MESSAGE",
    "HEALTH_CHECK_ALIASES",
    "HEIGHT_CHECK",
    "LIBRARY_SWITCHED_MESSAGE",
    "NEW_LIBRARY_STEM",
    "REPAIR_HEIGHTS_ACTION",
    "HeightProblem",
    "LibraryHealthIssue",
    "THUMBNAIL_VERSION",
    "SyncError",
    "SyncFailed",
    "component_thumbnail",
    "content_hashes",
    "thumbnail_hash",
    "thumbnail_salt",
    "footprint_height_problems",
    "layers_message",
    "library_choice_conflict",
    "library_move_refusal",
    "repair_footprint_heights",
    "restore_library_backup",
    "manifest_snapshot",
    "invalidate_health_cache",
    "resolve_library_choice",
    "scan_message",
    "ensure_symbols",
    "ensure_footprints",
    "sync_pending",
    "scan_library",
    "symbol_fingerprint",
    "footprint_fingerprint",
    "pinout",
    "pinout_changes",
    "validate_spec",
    "planned_library",
    "write_is_slow",
    "foreign_conflict",
    "component_warnings",
    "delete_symbols",
    "delete_footprints",
    "LibraryFileInfo",
    "library_files",
    "scan_workspace",
    "library_health",
    "apply_layer_stack",
    "ExternalLibrary",
    "list_external_libraries",
    "get_external_library",
    "add_external_library",
    "remove_external_library",
    "external_components",
    "use_external_component",
    "altium_bridge",
]

ALTIUM_MODIFIED_MESSAGE = "In Altium geöffnet und ungespeichert – bitte speichern oder schließen"
#: Altium runs, but whether it holds a library open and modified cannot be read (script paused in the debugger,
#: bridge busy, protocol error): nothing is written, an open modified library could be overwritten (§1.4).
ALTIUM_UNKNOWN_MESSAGE = (
    "Der Zustand in Altium konnte nicht geprüft werden ({reason}) – nicht geschrieben, solange Altium Designer läuft. "
    "Auf der Altium-Seite „Skript anhalten“ wählen oder Altium beenden und erneut versuchen"
)
#: Age after which prefetched Altium document states are asked for again before the next write: during a batch over
#: hundreds of files the user may open one of them in Altium.
PREFETCH_TTL_S = 45.0
LIBRARY_SWITCHED_MESSAGE = (
    "Die Bibliothek wurde während des Vorgangs gewechselt oder geschlossen – abgebrochen. Nicht geschriebene Symbole "
    "und Footprints bleiben in ihrer Bibliothek vorgemerkt und werden beim nächsten Synchronisieren geschrieben."
)
EXTERNAL_FILE = "partforge-external.json"
_PARTFORGE_STEP_MARK = "PartForge 3D model of"
_STEP_OWNER_RE: Final = re.compile(r"FILE_DESCRIPTION\(\('PartForge 3D model of ((?:[^']|'')*)'\)")
_MAX_STATUS_MESSAGE = 900
_MANIFEST_PREFIX: Final = "pf_lib:"

Spec = SymbolSpec | FootprintSpec
Record = SymbolRecord | FootprintRecord
Kind = Literal["symbol", "footprint"]
ConflictMode = Literal["refuse", "record"]


class SyncError(RuntimeError):
    """A library operation cannot be performed (German message; ``status`` = HTTP code)."""

    def __init__(self, message: str, *, status: int = 400):
        super().__init__(message)
        self.status = status


class SyncFailed(SyncError):
    """``ensure_*(…, strict=True)``: at least one component was not written.

    The registry is updated as usual (``records`` = the answer ``ensure_*`` would have
    returned); ``status`` is the HTTP code of the first failure (409 conflict / Altium,
    503 no writer, 400 otherwise).
    """

    def __init__(self, message: str, *, status: int, records: Sequence[Any]):
        super().__init__(message, status=status)
        self.records = list(records)


# --------------------------------------------------------------------------- fingerprints


def _digest(data: Any) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def symbol_fingerprint(spec: SymbolSpec) -> str:
    """Hash over everything a symbol writes into a SchLib (not the generator metadata)."""
    data = spec.model_dump(mode="json", exclude={"generator"})
    for pin in data.get("pins") or []:
        pin.pop("group", None)  # PartForge-only grouping, not stored in the library
    return _digest(data)


def footprint_fingerprint(spec: FootprintSpec) -> str:
    """Hash over everything a footprint writes into a PcbLib.

    Equivalent to comparing the generator's ``geometry_hash`` (all geometry: pads, lands,
    courtyard, texts, bodies, height, STEP reference) plus name and description – but also
    valid for edited or imported footprints whose generator data is stale or missing.
    """
    data = compat_text_dump(spec.model_dump(mode="json", exclude={"generator", "parameters", "family", "ipc_name",
                                                                  "density"}))
    return _digest(data)


def pinout(spec: SymbolSpec) -> dict[str, tuple[str, int]]:
    """``{pin designator: (pin name, part)}`` of a symbol."""
    return {pin.designator: (pin.name, pin.part) for pin in spec.pins}


def pinout_changes(old: SymbolSpec, new: SymbolSpec) -> list[str]:
    """German description of every pin-out difference (empty = same pin-out)."""
    a, b = pinout(old), pinout(new)
    changes: list[str] = []
    removed = sorted(set(a) - set(b), key=_natural)
    added = sorted(set(b) - set(a), key=_natural)
    if removed:
        changes.append(f"Pins entfernt: {', '.join(removed[:8])}{' …' if len(removed) > 8 else ''}")
    if added:
        changes.append(f"Pins hinzugefügt: {', '.join(added[:8])}{' …' if len(added) > 8 else ''}")
    for designator in sorted(set(a) & set(b), key=_natural):
        (old_name, old_part), (new_name, new_part) = a[designator], b[designator]
        if old_name != new_name:
            changes.append(f"Pin {designator}: Name „{old_name}“ → „{new_name}“")
        if old_part != new_part:
            changes.append(f"Pin {designator}: Teil {old_part} → {new_part}")
    return changes


def _natural(text: str) -> tuple[Any, ...]:
    return tuple(int(t) if t.isdigit() else t.casefold() for t in re.split(r"(\d+)", text))


def _same_path(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(a))) == os.path.normcase(os.path.abspath(os.fspath(b)))


# --------------------------------------------------------------------------- Altium access


def _altium_checks_allowed() -> bool:
    """Never touch a running Altium from the automated test suite (module builders must not
    start Altium scripts) unless the live tests are enabled explicitly."""
    return "PYTEST_CURRENT_TEST" not in os.environ or os.environ.get("PARTFORGE_TEST_ALTIUM") == "1"


def altium_bridge() -> Any | None:
    """The DelphiScript bridge if Altium Designer runs (document check/reload), else ``None``.

    Cheap when Altium is not running (process list only, no script).
    """
    if not _altium_checks_allowed():
        return None
    from .bridge.core import AltiumBridge

    settings = load_settings()
    bridge = AltiumBridge.from_settings(settings, exchange_dir=settings.resolved_bridge_exchange_dir())
    if not bridge.x2_path or not bridge.is_running():
        return None
    return bridge


class _AltiumGuard:
    """Per-operation access to Altium: refuse writing modified documents, reload open ones."""

    def __init__(self) -> None:
        self._bridge: Any = None
        self._resolved = False
        self.states: dict[str, Any] = {}
        self._prefetched: set[str] = set()
        self._prefetch_list: list[Path] = []
        self._prefetched_at = 0.0
        #: Altium runs but its document states cannot be read: every write is refused with this reason
        self.blocked: str | None = None
        self.notes: list[str] = []

    def _get(self) -> Any | None:
        if not self._resolved:
            self._resolved = True
            try:
                self._bridge = globals()["altium_bridge"]()
            except Exception as exc:  # noqa: BLE001 - a broken Altium setup must not block writing
                log.warning("Altium-Prüfung nicht möglich: %s", exc)
                self._bridge = None
        return self._bridge

    def _fail(self, exc: BaseException) -> None:
        """A document check failed (script paused in the debugger, bridge busy, protocol error). While Altium
        runs nothing may be written – an open, modified library could be overwritten; without Altium nothing
        can be open and writing goes on."""
        running = False
        try:
            running = self._bridge is not None and bool(self._bridge.is_running())
        except Exception:  # noqa: BLE001 - unknown counts as not running: the write proceeds as before
            running = False
        if running:
            log.warning("Dokumentstatus in Altium nicht ermittelbar – Schreiben verweigert: %s", exc)
            self.blocked = ALTIUM_UNKNOWN_MESSAGE.format(reason=str(exc).strip().rstrip(".") or type(exc).__name__)
        else:
            log.warning("Dokumentstatus in Altium nicht ermittelbar (Altium läuft nicht): %s", exc)
            self._bridge = None

    def prefetch(self, libraries: Sequence[Path]) -> None:
        """Ask Altium once for the state of many libraries (bridge ``document_states``, one script run per 200
        files); :meth:`refusal` then answers from it instead of one script run per library – and asks again
        after :data:`PREFETCH_TTL_S`."""
        existing = [p for p in libraries if p.exists()]
        bridge = self._get() if existing and not self.blocked else None
        if bridge is None:
            return
        from .bridge.core import AltiumNotRunning

        try:
            states = bridge.document_states(existing)
        except AltiumNotRunning:
            self._bridge = None
            return
        except Exception as exc:  # noqa: BLE001 - bridge, protocol and OS errors
            self._fail(exc)
            return
        self.states.update(states)
        self._prefetched.update(states)
        self._prefetch_list = existing
        self._prefetched_at = time.monotonic()

    def refusal(self, library: Path) -> str | None:
        """Why ``library`` must not be written now: :data:`ALTIUM_MODIFIED_MESSAGE` if Altium has it open with
        unsaved changes, :data:`ALTIUM_UNKNOWN_MESSAGE` if that cannot be read while Altium runs; ``None`` = go."""
        if not library.exists():
            return None
        if self.blocked:
            return self.blocked
        key = os.path.normcase(str(library))
        if key in self._prefetched and time.monotonic() - self._prefetched_at > PREFETCH_TTL_S:
            # a long batch: the user may have opened one of the files in Altium meanwhile – one script run
            self._prefetched.clear()
            self.prefetch(self._prefetch_list)
            if self.blocked:
                return self.blocked
        if key in self._prefetched:
            state = self.states.get(key)
            return ALTIUM_MODIFIED_MESSAGE if getattr(state, "open", False) and getattr(state, "modified", False) else None
        bridge = self._get()
        if bridge is None:
            return None
        from .bridge.core import AltiumNotRunning

        try:
            state = bridge.document_state(library)
        except AltiumNotRunning:
            self._bridge = None
            return None
        except Exception as exc:  # noqa: BLE001 - bridge, protocol and OS errors
            self._fail(exc)
            return self.blocked
        self.states[os.path.normcase(str(library))] = state
        if getattr(state, "open", False) and getattr(state, "modified", False):
            return ALTIUM_MODIFIED_MESSAGE
        return None

    def reload(self, library: Path) -> str | None:
        """Reload a library Altium had open (unmodified) before it was rewritten."""
        state = self.states.get(os.path.normcase(str(library)))
        if state is None or not getattr(state, "open", False):
            return None
        if not load_settings().altium.auto_reload_libraries:
            return f"{library.name} ist in Altium geöffnet – bitte dort schließen und neu öffnen, um die Änderungen zu sehen."
        bridge = self._get()
        if bridge is None:
            return None
        try:
            outcome = bridge.refresh_document(library)
        except Exception as exc:  # noqa: BLE001 - the library is written; only the reload failed
            log.warning("%s konnte in Altium nicht neu geladen werden: %s", library, exc)
            return f"{library.name} konnte in Altium nicht neu geladen werden ({exc}) – bitte dort schließen und neu öffnen."
        if outcome == "modified":
            return f"{library.name} wurde in Altium inzwischen geändert und nicht neu geladen – {ALTIUM_MODIFIED_MESSAGE}."
        if outcome in ("reloaded", "closed"):
            return f"{library.name} in Altium neu geladen."
        return None


# --------------------------------------------------------------------------- library manifest


class _Manifest(BaseModel):
    """What PartForge last wrote into one library file (``pf_meta``, key per library).

    ``components`` maps the casefolded component name to the fingerprint PartForge wrote, or
    ``None`` if PartForge owns the component (wrote it at some point or is writing it) but its
    current content is not known to equal a registry spec. The fingerprints are only valid
    while the file still has the recorded content (size and SHA-256; mtime for information).
    """

    rel: str
    size: int = 0
    mtime_ns: int = 0
    sha256: str = ""
    components: dict[str, str | None] = Field(default_factory=dict)

    def matches(self, path: Path) -> bool:
        """The file is unchanged since PartForge recorded it.

        Compared by content (SHA-256) whenever the size matches: a modification time alone is
        not reliable (coarse timestamps, copies, rollbacks that restore the same content)."""
        stat = _stat(path)
        if stat is None or stat[0] != self.size:
            return False
        if not self.sha256:
            return stat[1] == self.mtime_ns
        return _sha256(path) == self.sha256


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _sha256(path: Path) -> str | None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def _file_state(path: Path) -> tuple[int, int, str] | None:
    stat = _stat(path)
    digest = _sha256(path) if stat is not None else None
    if stat is None or digest is None:
        return None
    return stat[0], stat[1], digest


def _manifest_key(rel: str) -> str:
    return _MANIFEST_PREFIX + hashlib.sha1(_rel_key(rel).encode("utf-8")).hexdigest()


def _load_manifest(rel: str) -> _Manifest | None:
    """The stored manifest of a library (``None`` if unknown – callers are then careful)."""
    try:
        raw = db_meta.get_meta(_manifest_key(rel))
    except Exception as exc:  # noqa: BLE001 - without a manifest the sync only gets more careful
        log.debug("Bibliotheksstand von %s nicht lesbar: %s", rel, exc)
        return None
    if not raw:
        return None
    try:
        manifest = _Manifest.model_validate_json(raw)
    except (ValidationError, ValueError):
        return None
    return manifest if _rel_key(manifest.rel) == _rel_key(rel) else None


def _store_manifest(rel: str, manifest: _Manifest | None) -> None:
    """Store (or with ``None`` remove) a library manifest (``pf_meta`` via :mod:`partforge.db.meta`).
    Callers hold ``session.bound()``."""
    try:
        db_meta.set_meta(_manifest_key(rel), None if manifest is None else manifest.model_dump_json())
    except Exception as exc:  # noqa: BLE001 - a stale manifest only makes the next write more careful
        log.warning("Bibliotheksstand von %s nicht gespeichert: %s", rel, exc)


def _with_intent(rel: str, library: Path, manifest: _Manifest | None, names: Iterable[str]) -> _Manifest | None:
    """``manifest`` plus the names PartForge is about to write (ownership survives failures
    and aborts); ``None`` if nothing is new. The recorded file state stays as it is."""
    keys = [n.casefold() for n in names]
    if manifest is not None and all(k in manifest.components for k in keys):
        return None
    if manifest is None:
        state = _file_state(library) if library.is_file() else None
        size, mtime_ns, digest = state if state is not None else (0, 0, "")
        intent = _Manifest(rel=rel, size=size, mtime_ns=mtime_ns, sha256=digest)
    else:
        intent = manifest.model_copy(deep=True)
    for key in keys:
        intent.components.setdefault(key, None)
    return intent


def _final_manifest(
    rel: str,
    library: Path,
    before: _Manifest | None,
    before_valid: bool,
    names_after: Iterable[str] | None,
    written: Mapping[str, str],
) -> _Manifest | None:
    """Manifest after PartForge changed ``library``: written components with their
    fingerprint, untouched ones keep theirs only if the file was unchanged before (else
    ``None``: owned, content unknown); components PartForge never owned stay unlisted."""
    state = _file_state(library)
    if state is None:
        return None
    keys = [n.casefold() for n in names_after] if names_after is not None else list(written)
    components: dict[str, str | None] = {}
    for key in keys:
        if key in written:
            components[key] = written[key]
        elif before is not None and key in before.components:
            components[key] = before.components[key] if before_valid else None
    for key, fingerprint in written.items():
        components.setdefault(key, fingerprint)
    return _Manifest(rel=rel, size=state[0], mtime_ns=state[1], sha256=state[2], components=components)


def _owned(name: str, existing: Any | None, rel: str, manifest: _Manifest | None) -> bool:
    """PartForge may overwrite this component in ``rel``: it wrote it (manifest) or the
    registry holds it as ``ok`` with geometry for exactly this library (written by an older
    PartForge version or taken over from the file)."""
    if manifest is not None and name.casefold() in manifest.components:
        return True
    return (
        existing is not None
        and existing.spec is not None
        and existing.status == "ok"
        and existing.source != "external"
        and _rel_key(existing.library) == _rel_key(rel)
    )


# --------------------------------------------------------------------------- session


def _workspace_is_open(ws: Workspace) -> bool:
    """``ws`` is the open workspace *and* its database is the open database."""
    try:
        if not db_core.is_open() or not _same_path(db_core.current_workspace().root, ws.root):
            return False
    except Exception:  # noqa: BLE001 - closed concurrently
        return False
    now = current_or_none()
    return now is not None and _same_path(now.root, ws.root)


class _Session:
    """State of one library operation (workspace, writer, Altium guard, job context).

    ``watch=True`` (mutating operations) subscribes to ``WORKSPACE_CLOSED``/``OPENED``;
    :meth:`bound` guards every registry/parts write (see the module docstring, rule 9).
    """

    def __init__(
        self, ws: Workspace, ctx: JobContext | None, writer: LibraryWriter | None = None, *, watch: bool = False
    ):
        self.ws = ws
        self.ctx = ctx
        self._writer = writer
        self._writer_error: str | None = None
        self.altium = _AltiumGuard()
        self.written: list[str] = []
        self._usage: dict[Kind, dict[str, int]] = {}
        self._counts: dict[Kind, dict[str, int]] = {}
        self._external: set[str] | None = None
        self._switched = False
        self._abort_logged = False
        self._unsubscribe: list[Callable[[], None]] = []
        if watch:
            self._unsubscribe = [
                events.subscribe(events.WORKSPACE_CLOSED, self._on_switch),
                events.subscribe(events.WORKSPACE_OPENED, self._on_switch),
            ]

    # -- writer ---------------------------------------------------------------------
    def writer(self) -> LibraryWriter:
        if self._writer is None:
            if self._writer_error is not None:
                raise WriterUnavailable(self._writer_error)
            try:
                self._writer = get_writer(workspace=self.ws)
            except WriterUnavailable as exc:
                self._writer_error = str(exc)
                raise
        return self._writer

    def is_rust(self) -> bool:
        try:
            return self.writer().name == "rust"
        except WriterUnavailable:
            return False

    def names_in(self, library: Path) -> list[str] | None:
        """Component names of an existing library (``None`` = cannot be listed cheaply)."""
        return self.list_names(library)[0]

    def list_names(self, library: Path) -> tuple[list[str] | None, str | None]:
        """Component names of a library and why they are unknown: ``(names, None)`` (``[]`` if the file does
        not exist), ``(None, German reason)`` if the file cannot be read (damaged), ``(None, None)`` if no
        writer can list it (none available, Altium backend without reader, writer process not usable)."""
        if not library.exists():
            return [], None
        try:
            return cached_component_names(self.writer(), library), None
        except (WriterUnavailable, RustWriterUnavailable, RustTimeoutError) as exc:
            log.info("Bibliothek %s nicht auflistbar: %s", library, exc)
            return None, None
        except (RustWriterError, OSError, RuntimeError) as exc:
            log.warning("Bibliothek %s nicht lesbar: %s", library, exc)
            return None, (str(exc).strip().rstrip(".") or type(exc).__name__)

    # -- library binding --------------------------------------------------------------
    def _on_switch(self, *_args: Any, **_kwargs: Any) -> None:
        self._switched = True

    def _abort(self) -> NoReturn:
        """Stop: the library this operation started in is no longer the open one.

        In a job the reason is recorded (``cancel_reason = "library_switch"`` – the UI explains why
        it stopped; a user's earlier cancel keeps its reason) and the German text becomes the job's
        final message. Nothing is logged into the job here: the library guard (or the job body)
        announces the switch once."""
        if self.ctx is not None:
            cancel = getattr(self.ctx, "cancel", None)
            if callable(cancel):
                cancel(CANCEL_LIBRARY_SWITCH)
            raise JobCancelled(LIBRARY_SWITCHED_MESSAGE)
        if not self._abort_logged:
            self._abort_logged = True
            log.warning("%s", LIBRARY_SWITCHED_MESSAGE)
        raise SyncError(LIBRARY_SWITCHED_MESSAGE, status=409)

    def ensure_current(self) -> None:
        """Abort if the library this operation started in is no longer the open one."""
        if self._switched or not _workspace_is_open(self.ws):
            self._switched = True
            self._abort()

    @contextmanager
    def bound(self) -> Iterator[None]:
        """Registry/parts writes of this operation: holds the database write lock (a library
        switch swaps the database under the same lock) and checks the open library first."""
        with db_core.write_lock():
            self.ensure_current()
            yield

    # -- job context ----------------------------------------------------------------
    def log(self, text: str, level: Literal["info", "warn", "error", "success"] = "info") -> None:
        getattr(log, {"info": "info", "warn": "warning", "error": "error", "success": "info"}[level])("%s", text)
        if self.ctx is not None:
            self.ctx.log(text, level)

    def progress(self, fraction: float, message: str) -> None:
        if self.ctx is not None:
            self.ctx.progress(fraction, message)

    def check_cancelled(self) -> None:
        if self.ctx is not None:
            self.ctx.check_cancelled()
        self.ensure_current()

    # -- registry helpers -----------------------------------------------------------
    def usage(self, kind: Kind) -> dict[str, int]:
        if kind not in self._usage:
            raw = registry.symbol_usage() if kind == "symbol" else registry.footprint_usage()
            folded: dict[str, int] = {}
            for name, count in raw.items():
                folded[name.casefold()] = folded.get(name.casefold(), 0) + count
            self._usage[kind] = folded
        return self._usage[kind]

    def rel(self, path: Path) -> str:
        return self.ws.rel(path)

    def library_counts(self, ops: _KindOps) -> dict[str, int]:
        """``{_rel_key(library): registered components}`` of one kind (lean registry read, once per operation)."""
        if ops.kind not in self._counts:
            counts: dict[str, int] = {}
            for reg in _registry_rows(ops.kind).values():
                if reg.library and reg.source != "external":
                    key = _rel_key(reg.library)
                    counts[key] = counts.get(key, 0) + 1
            self._counts[ops.kind] = counts
        return self._counts[ops.kind]

    def external_paths(self) -> set[str]:
        """Normalised paths of the registered external libraries (never written)."""
        if self._external is None:
            self._external = {os.path.normcase(lib.path) for lib in _load_external(self.ws)}
        return self._external

    def finish(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []
        for note in self.altium.notes:
            self.log(note, "warn")
        self.altium.notes.clear()
        if self.written and not self._switched:
            events.emit(events.LIBRARIES_WRITTEN, list(dict.fromkeys(self.written)))
        self.written = []


@contextmanager
def _library_held(library: Path) -> Iterator[str | None]:
    """Hold :func:`library_lock` of ``library`` (threads of this process and other processes). Yields
    ``None`` while held, or – nothing held – the German refusal when another process (a second PartForge
    window) keeps writing the file (:class:`~partforge.altium.rustwriter.LibraryLocked`)."""
    lock = library_lock(library)
    try:
        lock.acquire()
    except LibraryLocked as exc:
        yield str(exc)
        return
    try:
        yield None
    finally:
        lock.release()


@functools.lru_cache(maxsize=8192)
def _rel_key(path: str | None) -> str:
    """Comparison key of a stored library path (backslashes, normalised, casefolded; memoised – the
    checks compare the paths of thousands of parts)."""
    return str(PureWindowsPath(str(path or "").replace("/", "\\"))).casefold()


# --------------------------------------------------------------------------- kind adapters


@dataclass(frozen=True)
class _KindOps:
    kind: Kind
    label: str
    label_plural: str
    lib_kind: LibraryKind
    list_records: Callable[[], list[Any]]
    upsert: Callable[[Iterable[Any]], list[Any]]
    fingerprint: Callable[[Any], str]
    write: Callable[[LibraryWriter, Path, list[Any]], WriteResult]
    target: Callable[[Workspace, Any, str | None], Path]
    name_record: Callable[[Any], Any]  # spec with generator["name"] set for a custom name

    def count(self, n: int) -> str:
        """"1 Symbol", "3 Footprints" (German count phrase)."""
        return plural(n, self.label, self.label_plural)


def _list_symbol_records() -> list[SymbolRecord]:
    return registry.list_symbols(with_usage=False)


def _list_footprint_records() -> list[FootprintRecord]:
    return registry.list_footprints(with_usage=False)


def _records_by_names(kind: Kind, names: Iterable[str]) -> dict[str, Any]:
    """``{casefolded name: record with spec}`` of the registered names among ``names`` – filtered in SQL
    (``registry.list_*(names=…)``); the specs of all other entries are never parsed (a registry of 1,000
    components is ~200 MB as models)."""
    wanted = list(dict.fromkeys(n.casefold() for n in names if n))
    if not wanted:
        return {}
    list_records = registry.list_symbols if kind == "symbol" else registry.list_footprints
    out: dict[str, Any] = {}
    for start in range(0, len(wanted), 500):
        for rec in list_records(names=wanted[start:start + 500], with_usage=False):
            out.setdefault(rec.name.casefold(), rec)
    return out


def _load_library_records(ops: _KindOps, records: dict[str, Any], rel: str) -> None:
    """Add every record registered in the library file ``rel`` to ``records`` (with spec, on demand)."""
    key = _rel_key(rel)
    names = [r.name for r in _registry_rows(ops.kind).values() if _rel_key(r.library) == key]
    missing = [n for n in names if n.casefold() not in records]
    if missing:
        records.update(_records_by_names(ops.kind, missing))


def _symbol_name_record(spec: SymbolSpec) -> SymbolSpec:
    from ..symbols import with_name_record

    return with_name_record(spec)


def _footprint_name_record(spec: FootprintSpec) -> FootprintSpec:
    from ..footprints import with_name_record

    return with_name_record(spec)


SYMBOLS = _KindOps(
    kind="symbol",
    label="Symbol",
    label_plural="Symbole",
    lib_kind="schlib",
    list_records=_list_symbol_records,
    upsert=registry.upsert_symbols,
    fingerprint=symbol_fingerprint,
    write=lambda writer, lib, specs: writer.write_symbols(lib, specs),
    target=lambda ws, spec, category: symbol_library_path(ws, spec, category),
    name_record=_symbol_name_record,
)
FOOTPRINTS = _KindOps(
    kind="footprint",
    label="Footprint",
    label_plural="Footprints",
    lib_kind="pcblib",
    list_records=_list_footprint_records,
    upsert=registry.upsert_footprints,
    fingerprint=footprint_fingerprint,
    write=lambda writer, lib, specs: writer.write_footprints(lib, specs),
    target=lambda ws, spec, _category: footprint_library_path(ws, spec),
    name_record=_footprint_name_record,
)


def _ops_for(kind: Kind) -> _KindOps:
    return SYMBOLS if kind == "symbol" else FOOTPRINTS


# --------------------------------------------------------------------------- validation


def _spec_problems(session: _Session, spec: Spec) -> list[str]:
    """Client-side validation of one spec (backend independent, German messages)."""
    ws = session.ws
    try:
        if isinstance(spec, SymbolSpec):
            payload = symbol_to_rust(spec, ws.settings.symbol)
            return validate_symbol_payload(payload)
        payload = footprint_to_rust(spec, ws.settings.layers, ws.settings.footprint)
        problems = validate_footprint_payload(payload)
    except RustValidationError as exc:
        return list(exc.issues)
    if spec.step is not None:
        path = _resolve_model_path(ws, spec.step.file)
        if path is None or not path.is_file():
            problems.append(f"Footprint {spec.name}: STEP-Datei {spec.step.file} wurde nicht gefunden.")
        elif path.suffix.lower() not in (".step", ".stp"):
            problems.append(f"Footprint {spec.name}: STEP-Datei {path.name} hat keine Endung .step/.stp.")
    return problems


def _resolve_model_path(ws: Workspace, file: str | None) -> Path | None:
    if not file:
        return None
    raw = Path(str(file).replace("\\", "/"))
    return raw if raw.is_absolute() else ws.root / raw


# --------------------------------------------------------------------------- explicit target library

#: Name of a new library chosen in the editor: ``PF_<Name>`` (letters, digits, ``_``, ``-``).
NEW_LIBRARY_STEM: Final = re.compile(r"^PF_[A-Za-z0-9][A-Za-z0-9_\-]{0,59}$")


def resolve_library_choice(kind: Kind, raw: str, *, ws: Workspace | None = None) -> Path:
    """Validate an explicit target library of a save (``SymbolSaveIn.library`` /
    ``FootprintSaveIn.library``) and return its absolute path.

    Accepted: an **existing library of the workspace of the right kind** – any ``.SchLib`` below
    ``Symbols\\`` resp. ``.PcbLib`` below ``Footprints\\`` (the files PartForge manages; external
    libraries and the writers' temporary files are never targets) – or the name of a **new**
    library ``PF_<Name>.SchLib`` / ``PF_<Name>.PcbLib`` directly in that folder (``<Name>``:
    letters, digits, ``_``, ``-``, at most 60 characters). Given as a path relative to the library
    folder (``Symbols\\PF_Analog.SchLib``), as a bare file name (then in the kind's folder) or
    absolute inside the library folder. Anything else raises :class:`SyncError` (400) with the
    rule in German.
    """
    ws = ws or current()
    ext = ".SchLib" if kind == "symbol" else ".PcbLib"
    lib_kind: LibraryKind = "schlib" if kind == "symbol" else "pcblib"
    folder = Path(os.path.abspath(ws.symbols_dir if kind == "symbol" else ws.footprints_dir))
    folder_rel = ws.rel(folder)
    rule = (f"Erlaubt ist eine vorhandene {ext}-Bibliothek im Ordner {folder_rel} oder eine neue "
            f"„PF_<Name>{ext}“ direkt darin (Name aus Buchstaben, Ziffern, „_“ und „-“).")
    text = str(raw or "").strip().strip('"').replace("/", "\\")
    if not text:
        raise SyncError(f"Bitte eine Zielbibliothek angeben. {rule}")
    pure = PureWindowsPath(text)
    if pure.is_absolute() or pure.drive:
        candidate = Path(text)
    elif len(pure.parts) == 1:
        candidate = folder / pure.name
    else:
        candidate = ws.root / Path(*pure.parts)
    candidate = Path(os.path.abspath(candidate))
    if library_file_kind(candidate) != lib_kind:
        raise SyncError(f"„{pure.name}“ ist keine {ext}-Bibliothek. {rule}")
    if not is_inside(candidate, folder):
        raise SyncError(f"„{text}“ liegt nicht im Ordner {folder_rel} der Bibliothek. {rule}")
    existing = {os.path.normcase(str(p)): p for p in workspace_library_files(ws) if library_file_kind(p) == lib_kind}
    found = existing.get(os.path.normcase(str(candidate)))
    if found is not None:
        return Path(os.path.abspath(found))
    if candidate.exists():
        raise SyncError(f"„{pure.name}“ ist keine von PartForge verwaltete Bibliothek. {rule}")
    if os.path.normcase(str(candidate.parent)) != os.path.normcase(str(folder)) or not NEW_LIBRARY_STEM.match(
        candidate.stem
    ):
        raise SyncError(f"„{text}“ ist keine vorhandene Bibliothek und kein gültiger Name für eine neue. {rule}")
    return folder / f"{candidate.stem}{ext}"


# --------------------------------------------------------------------------- STEP files


def _step_owner(text: str | None) -> str | None:
    """Footprint name in the ``PartForge 3D model of …`` mark of a STEP text (``None`` = no
    PartForge model, e.g. a vendor file)."""
    if not text:
        return None
    match = _STEP_OWNER_RE.search(text[:4000])
    return match.group(1).replace("''", "'") if match else None


def _ensure_step_file(ws: Workspace, spec: FootprintSpec) -> tuple[FootprintSpec, str | None]:
    """Give a footprint with extruded bodies its STEP file ``<ws>/3D/<name>.step``.

    Returns the (possibly updated) spec and a German note. A PartForge model of this
    footprint inside ``3D`` is derived data: it is (re)written whenever the bodies changed or
    the file went missing. A file PartForge did not write (vendor model) is never touched –
    a new model then goes to ``<name>_PF.step``; a referenced vendor model or the model of
    another footprint is kept as it is.
    """
    if not spec.bodies:
        return spec, None
    from ..footprints import step_text, write_step
    from ..footprints.step import file_digest, step_digest

    if spec.step is not None:
        path = _resolve_model_path(ws, spec.step.file)
        if path is None or not is_inside(path, ws.models_dir):
            return spec, None  # vendor model or a cached copy outside the 3D folder
        target = path
    else:
        target = ws.models_dir / f"{safe_file_stem(spec.name)}.step"
    if file_digest(_read_head(target)) == step_digest(spec):  # the model of exactly these bodies: nothing to generate
        if spec.step is None:
            spec = spec.model_copy(update={"step": StepModel(file=ws.rel(target))})
        return spec, None
    try:
        text = step_text(spec)
    except ValueError as exc:
        return spec, f"Footprint {spec.name}: kein STEP-Modell ({exc})."
    own = _step_owner(text)
    current_text = _read_text(target) if target.is_file() else None
    if current_text is not None and current_text != text:
        owner = _step_owner(current_text)
        if spec.step is not None and owner != own:
            return spec, None  # referenced vendor model or another footprint's model: keep it
        if spec.step is None and owner is None:  # vendor file of the same name
            target = target.with_name(f"{target.stem}_PF{target.suffix}")
        elif spec.step is None and owner != own:  # another footprint's model (file name collision)
            digest = hashlib.sha1(spec.name.encode("utf-8")).hexdigest()[:8]
            target = target.with_name(f"{target.stem}_{digest}{target.suffix}")
        if spec.step is None and target.is_file():
            other = _read_text(target)
            if other != text and _step_owner(other) != own:
                digest = hashlib.sha1(spec.name.encode("utf-8")).hexdigest()[:8]
                target = target.with_name(f"{safe_file_stem(spec.name)}_PF_{digest}{target.suffix}")
    try:
        if _read_text(target) != text:
            write_step(spec, target)  # atomic (temp file + rename)
            log.info("STEP-Modell %s geschrieben", target)
    except (OSError, ValueError) as exc:
        reason = str(exc)
        if isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in (5, 32, 33):
            reason = "die Datei ist von einem anderen Programm geöffnet oder schreibgeschützt"
        elif isinstance(exc, OSError):
            reason = (exc.strerror or "").strip() or type(exc).__name__
        return spec, f"Footprint {spec.name}: STEP-Datei {target} konnte nicht geschrieben werden ({reason})."
    if spec.step is None:
        spec = spec.model_copy(update={"step": StepModel(file=ws.rel(target))})
    return spec, None


def _read_head(path: Path, size: int = 4096) -> str | None:
    """The first ``size`` characters of a STEP file (header with the PartForge digest), ``None`` if unreadable."""
    try:
        with path.open("r", encoding="ascii", errors="replace") as handle:
            return handle.read(size)
    except OSError:
        return None


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None


# --------------------------------------------------------------------------- items


@dataclass(eq=False)  # identity objects (deduplicated by reference)
class _Item:
    name: str
    spec: Any
    source: RecordSource
    existing: Any | None
    library: Path
    rel: str
    changed: bool = True
    status: RecordStatus = "pending"
    message: str | None = None
    transient: bool = False  # refused: nothing written, nothing registered
    adopted: bool = False  # taken over from the file: registered, not written
    conflict: bool = False  # sync_pending: not written, registry entry marked "error"
    http_status: int | None = None  # failure category for API callers (strict mode)
    notes: list[str] = field(default_factory=list)


def _clip(text: str | None) -> str | None:
    if not text:
        return None
    return text if len(text) <= _MAX_STATUS_MESSAGE else text[: _MAX_STATUS_MESSAGE - 1] + "…"


def _make_record(ops: _KindOps, item: _Item, status: RecordStatus, message: str | None) -> Any:
    spec = item.spec
    if ops.kind == "symbol":
        kind = None
        if isinstance(spec.generator, dict) and isinstance(spec.generator.get("kind"), str):
            kind = spec.generator["kind"]
        if kind is None and item.existing is not None:
            kind = item.existing.kind
        return SymbolRecord(
            name=item.name,
            library=item.rel,
            source=item.source,
            spec=spec,
            pin_count=len(spec.pins),
            part_count=spec.part_count,
            kind=kind,
            status=status,
            status_message=_clip(message),
        )
    return FootprintRecord(
        name=item.name,
        library=item.rel,
        source=item.source,
        spec=spec,
        family=spec.family or (item.existing.family if item.existing is not None else None),
        ipc_name=spec.ipc_name,
        pad_count=len(spec.pads),
        height=spec.height,
        step_file=spec.step.file if spec.step is not None else None,
        status=status,
        status_message=_clip(message),
    )


def _transient_record(ops: _KindOps, item: _Item) -> Any:
    if item.existing is not None:
        return item.existing.model_copy(update={"status": "error", "status_message": _clip(item.message)})
    return _make_record(ops, item, "error", item.message)


def _refuse(item: _Item, message: str, *, status: int, conflicts: ConflictMode = "refuse") -> None:
    """Do not write ``item``: transient refusal, or (``record``) an error on its registry entry."""
    item.changed = False
    item.status, item.message, item.http_status = "error", message, status
    if conflicts == "record" and item.existing is not None:
        item.conflict = True
    else:
        item.transient = True


# --------------------------------------------------------------------------- core


def _target_library(session: _Session, ops: _KindOps, spec: Any, existing: Any | None, category: str | None,
                    chosen: Path | None = None) -> Path:
    """Library file of ``spec``: a registered entry keeps its library (inside the workspace),
    a new one goes to ``chosen`` (explicit target) or the layout default."""
    ws = session.ws
    external = session.external_paths()
    if existing is not None and existing.library:
        path = ws.abs(existing.library)
        if path is not None and is_inside(path, ws.root) and os.path.normcase(str(path)) not in external:
            return Path(os.path.abspath(path))
    if chosen is not None:
        return Path(os.path.abspath(chosen))
    return _overflow_target(session, ops, Path(os.path.abspath(ops.target(ws, spec, category))))


#: A grouped library file takes no further new component once it holds this many registered components or this
#: many bytes: the writer rewrites the whole file on every change (cost ~ file size; a 9 MB PcbLib took 7–15 s per
#: save). Registered names stay in their file; new ones go to ``<stem>_2``, ``<stem>_3`` …
MAX_LIBRARY_COMPONENTS: Final = 60
MAX_LIBRARY_BYTES: Final = 2 * 1024 * 1024


def _overflow_target(session: _Session, ops: _KindOps, base: Path) -> Path:
    """The layout default for a **new** component: ``base`` (``PF_CHIP.PcbLib``) – or, once it is full
    (:data:`MAX_LIBRARY_COMPONENTS`, :data:`MAX_LIBRARY_BYTES`), the first of ``PF_CHIP_2.PcbLib``,
    ``PF_CHIP_3.PcbLib`` … that is not (layout ``grouped`` only)."""
    if session.ws.settings.library_layout != "grouped":
        return base
    counts = session.library_counts(ops)
    candidate = base
    for number in range(1, 1000):
        candidate = base if number == 1 else base.with_name(f"{base.stem}_{number}{base.suffix}")
        size = _stat(candidate)
        full = (size is not None and size[0] >= MAX_LIBRARY_BYTES) or counts.get(
            _rel_key(session.rel(candidate)), 0) >= MAX_LIBRARY_COMPONENTS
        if not full:
            return candidate
    return candidate


def library_move_refusal(label: str, name: str, current_rel: str, chosen_rel: str) -> str:
    """German refusal when a save names another library than the one a registered entry is in."""
    return (
        f"{label} „{name}“ ist bereits in {current_rel} gespeichert – ein Verschieben in eine andere Bibliothek "
        f"({chosen_rel}) ist nicht möglich. Bitte ohne Zielbibliothek speichern oder unter neuem Namen anlegen."
    )


def _name_recorded(ops: _KindOps, spec: Any) -> Any:
    """``spec`` with the custom-name record of its generator data (never fails a save)."""
    try:
        return ops.name_record(spec)
    except Exception as exc:  # noqa: BLE001 - the record is a convenience for "Neu generieren"
        log.warning("Namensangabe von %s nicht aktualisiert: %s", spec.name, exc)
        return spec


def _prepare_items(
    session: _Session,
    ops: _KindOps,
    specs: Sequence[Any],
    sources: Mapping[str, RecordSource],
    category: str | None,
    allow_pin_changes: bool,
    records: dict[str, Any],
    *,
    chosen: Path | None = None,
    force: bool = False,
) -> tuple[list[_Item], list[_Item]]:
    """Items to process (one per name) and, per input spec, the item that answers it.

    ``chosen``: explicit target library (validated by :func:`resolve_library_choice`) – a
    registered entry in another library is refused (409). ``force``: write even unchanged
    specs (e.g. to give footprints their height in the PcbLib)."""
    items: list[_Item] = []
    order: list[_Item] = []
    seen: dict[str, _Item] = {}
    for spec in specs:
        key = spec.name.casefold()
        source = sources.get(key, "generated")
        existing = records.get(key)
        if key in seen:
            first = seen[key]
            if first.transient or ops.fingerprint(first.spec) == ops.fingerprint(spec):
                order.append(first)  # identical repetition: same answer
            else:
                order.append(_Item(name=spec.name, spec=spec, source=source, existing=existing,
                                   library=first.library, rel=first.rel, transient=True, status="error",
                                   http_status=400,
                                   message=f"{ops.label} „{spec.name}“ ist in der Anfrage mehrfach mit unterschiedlichem "
                                   "Inhalt enthalten – nur der erste wird übernommen."))
            continue
        if existing is not None and existing.source == "external":
            library = Path(existing.library)
            item = _Item(name=spec.name, spec=spec, source=source, existing=existing, library=library,
                         rel=existing.library, transient=True, status="error", http_status=409,
                         message=f"{ops.label} „{spec.name}“ gehört zu einer externen Bibliothek ({existing.library}) und "
                         "wird von PartForge nicht geschrieben. Bitte einen anderen Namen wählen.")
            items.append(item)
            order.append(item)
            seen[key] = item
            continue
        if ops.kind == "footprint":
            spec, note = _ensure_step_file(session.ws, spec)
        else:
            note = None
        library = _target_library(session, ops, spec, existing, category, chosen)
        item = _Item(name=existing.name if existing is not None else spec.name, spec=spec, source=source,
                     existing=existing, library=library, rel=session.rel(library))
        if item.name != spec.name:  # registry spelling wins (names are case-insensitive)
            item.spec = spec.model_copy(update={"name": item.name})
        item.spec = _name_recorded(ops, item.spec)
        if note:
            item.notes.append(note)
        seen[key] = item
        items.append(item)
        order.append(item)
        if chosen is not None and not _same_path(library, chosen):
            item.transient, item.status, item.http_status = True, "error", 409
            item.message = library_move_refusal(ops.label, item.name, item.rel, session.rel(chosen))
            continue
        problems = _spec_problems(session, item.spec)
        if problems:
            item.transient, item.status, item.http_status = True, "error", 400
            item.message = f"{ops.label} „{item.name}“ ist ungültig: " + " ".join(problems[:6])
            continue
        if ops.kind == "symbol" and existing is not None and existing.spec is not None and not allow_pin_changes:
            changes = pinout_changes(existing.spec, item.spec)
            if changes:
                used = session.usage("symbol").get(key, 0)
                item.transient, item.status, item.http_status = True, "error", 409
                item.message = (
                    f"Symbol „{item.name}“ existiert bereits mit anderer Pinbelegung ({'; '.join(changes[:6])}). "
                    + (f"{plural(used, 'Bauteil verwendet', 'Bauteile verwenden')} es. " if used else "")
                    + "Die Änderung wird nicht stillschweigend übernommen – bitte einen neuen Symbolnamen wählen oder die "
                    "neue Pinbelegung ausdrücklich bestätigen."
                )
                continue
        if existing is None and chosen is None:  # the bound of a grouped file also holds within one batch
            counts = session.library_counts(ops)
            counts[_rel_key(item.rel)] = counts.get(_rel_key(item.rel), 0) + 1
        if (
            not force
            and existing is not None
            and existing.status == "ok"
            and existing.spec is not None
            and _rel_key(existing.library) == _rel_key(item.rel)
            and existing.source != "altium"
            and ops.fingerprint(existing.spec) == ops.fingerprint(item.spec)
            and item.library.is_file()
        ):
            item.changed = False
    return items, order


def _group(items: Iterable[_Item]) -> dict[str, list[_Item]]:
    groups: dict[str, list[_Item]] = {}
    for item in items:
        if not item.transient:
            groups.setdefault(os.path.normcase(str(item.library)), []).append(item)
    return groups


def _registry_for_library(records: Mapping[str, Any], rel: str) -> list[Any]:
    key = _rel_key(rel)
    return [r for r in records.values() if r.source != "external" and _rel_key(r.library) == key]


def _full_specs(
    session: _Session,
    library_records: list[Any],
    items: list[_Item],
    file_names: list[str],
    manifest: _Manifest | None,
) -> tuple[list[Any], list[tuple[Any, Any]]] | None:
    """Specs for a regeneration of the whole library, or ``None`` if that could lose data.

    Every component in the file must have been written by PartForge (``manifest``, valid
    for the current file) from a registered spec; components of the file PartForge does not
    know exactly (imported, adopted, edited elsewhere) force an upsert. Order: components in
    file order, then registered components missing in the file, then the new ones. Returns
    the specs and, for every registered (not requested) component written by it,
    ``(record, spec)`` – the spec may have got a STEP model.
    """
    by_name = {r.name.casefold(): r for r in library_records}
    new = {i.name.casefold(): i for i in items}
    specs: list[Any] = []
    included: set[str] = set()
    extra: list[Any] = []
    for name in file_names:
        key = name.casefold()
        if key in included:
            continue
        if key in new:
            specs.append(new[key].spec)
        else:
            rec = by_name.get(key)
            if rec is None or rec.spec is None:
                return None  # a component PartForge cannot regenerate -> upsert
            if manifest is None or manifest.components.get(key) is None:
                return None  # not (exactly) written by PartForge: a regeneration could lose content
            specs.append(rec.spec)
            extra.append(rec)
        included.add(key)
    for key, rec in by_name.items():
        if key in included or key in new or rec.spec is None:
            continue
        specs.append(rec.spec)
        extra.append(rec)
        included.add(key)
    for key, item in new.items():
        if key not in included:
            specs.append(item.spec)
            included.add(key)
    for index, spec in enumerate(specs):
        if spec.name.casefold() in new:
            continue
        if isinstance(spec, FootprintSpec):  # regenerate a PartForge STEP model that went missing or is stale
            specs[index] = spec = _ensure_step_file(session.ws, spec)[0]
        problems = _spec_problems(session, spec)
        if problems:
            session.log(
                f"{session.rel(Path(items[0].library))}: wird nur ergänzt, nicht neu erzeugt – {spec.name} ist ungültig "
                f"({problems[0]})",
                "warn",
            )
            return None
    by_spec_name = {spec.name.casefold(): spec for spec in specs}
    return specs, [(rec, by_spec_name[rec.name.casefold()]) for rec in extra]


def _component_notes(result: WriteResult, name: str) -> list[str]:
    prefix = f"{name}:".casefold()
    return [w for w in result.warnings if w.casefold().startswith(prefix)][:3]


def _failure_status(exc: BaseException) -> int:
    """HTTP code of a writer failure (409 conflict, 503 service unavailable, 400 otherwise)."""
    from .bridge.core import BridgeError

    if isinstance(exc, (WriterUnavailable, RustWriterUnavailable, RustTimeoutError, RustProcessError)):
        return 503
    if isinstance(exc, BridgeError):
        from .bridge.writer import AltiumDataLossError

        return 409 if isinstance(exc, AltiumDataLossError) else 503
    if isinstance(exc, PermissionError):
        return 409
    return 400


def _read_component(
    writer: LibraryWriter,
    library: Path,
    name: str,
    *,
    extract_step: bool = False,
    notes: list[str] | None = None,
) -> Spec | None:
    """One component in the PartForge model. ``extract_step`` (workspace libraries) places an
    embedded STEP model in the workspace ``3D`` folder so the spec can be written again;
    ``notes`` collects what a write-back would lose (Rust reader only)."""
    reader = writer.ops if isinstance(writer, RustLibraryWriter) else getattr(writer, "reader", None)
    if library_file_kind(library) == "schlib":
        if isinstance(reader, RustLibraryOps):
            return reader.read_symbol(library, name, notes=notes)
        return writer.read_symbol(library, name)
    if isinstance(reader, RustLibraryOps):
        return reader.read_footprint(library, name, notes=notes, extract_step=extract_step)
    return writer.read_footprint(library, name)


def _resolve_foreign(
    session: _Session,
    ops: _KindOps,
    library: Path,
    item: _Item,
    actual: str,
    *,
    allow_pin_changes: bool,
    conflicts: ConflictMode,
) -> None:
    """A component named like ``item`` is in the file, but PartForge does not own it:
    adopt it (register the file's version) – a symbol with another pin-out is refused, an
    explicitly confirmed pin-out change overwrites it."""
    where = session.rel(library)
    if ops.kind == "symbol" and allow_pin_changes:
        item.notes.append(f"Das vorhandene Symbol in {where} wurde nach Bestätigung ersetzt.")
        return
    notes: list[str] = []
    try:
        foreign = _read_component(session.writer(), library, actual, extract_step=True, notes=notes)
    except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
        log.warning("%s aus %s nicht lesbar: %s", actual, library, exc)
        foreign = None
    if foreign is None:
        _refuse(item, f"{ops.label} „{item.name}“ ist in {where} bereits vorhanden, aber nicht lesbar – es wird nicht "
                "überschrieben.", status=409, conflicts=conflicts)
        return
    if isinstance(foreign, SymbolSpec) and isinstance(item.spec, SymbolSpec):
        changes = pinout_changes(foreign, item.spec)
        if changes:
            _refuse(
                item,
                f"Symbol „{item.name}“ ist in {where} bereits mit anderer Pinbelegung vorhanden ({'; '.join(changes[:6])}) "
                "und wurde nicht von PartForge erzeugt – es wird nicht überschrieben. Bitte einen anderen Namen wählen oder "
                "die neue Pinbelegung ausdrücklich bestätigen.",
                status=409,
                conflicts=conflicts,
            )
            return
    hints: list[str] = []
    if isinstance(foreign, FootprintSpec) and isinstance(item.spec, FootprintSpec):
        have, want = foreign.pad_designators(), item.spec.pad_designators()
        if set(have) != set(want):
            hints.append(f"Achtung: Pads weichen vom angeforderten Footprint ab ({len(have)} statt {len(want)} Pads).")
    if notes:
        hints.append("Beim Speichern aus PartForge ginge verloren: " + " ".join(notes[:3]))
    if foreign.name != item.name:
        foreign = foreign.model_copy(update={"name": item.name})
    item.adopted, item.changed = True, False
    item.spec = foreign
    item.source = "imported"
    item.status = "ok"
    item.message = " ".join(
        [f"In {where} bereits vorhanden (nicht von PartForge erzeugt) – übernommen, nicht überschrieben.", *hints]
    )


def _write_library(
    session: _Session,
    ops: _KindOps,
    library: Path,
    items: list[_Item],
    records: dict[str, Any],
    persist: list[Any],
    *,
    allow_pin_changes: bool,
    conflicts: ConflictMode,
) -> _Manifest | None:
    """Write the changed items of one library (all or nothing) and plan registry updates.

    Returns the library manifest to store together with ``persist`` (``None`` = unchanged).
    """
    rel = items[0].rel
    file_names, list_problem = session.list_names(library)
    unknown = [n for n in file_names or [] if n.casefold() not in records]
    if unknown:  # (registered meanwhile, or simply not loaded yet)
        records.update(_records_by_names(ops.kind, unknown))
    present = {n.casefold(): n for n in file_names} if file_names is not None else None
    exists = library.is_file()
    manifest = _load_manifest(rel) if exists else None
    state_ok = manifest is not None and manifest.matches(library)
    for item in items:
        if not item.changed and present is not None and item.name.casefold() not in present:
            item.changed = True  # registered as ok, but not in the file
    if present:
        for item in items:
            key = item.name.casefold()
            if item.changed and not item.transient and key in present and not _owned(item.name, item.existing, rel, manifest):
                _resolve_foreign(session, ops, library, item, present[key], allow_pin_changes=allow_pin_changes,
                                 conflicts=conflicts)
    for item in items:
        if item.transient:
            session.log(item.message or f"{item.name}: abgelehnt", "error")
        elif item.adopted:
            persist.append(_make_record(ops, item, "ok", item.message))
            session.log(f"{item.name}: {item.message}", "info")
        elif item.conflict:
            persist.append(item.existing.model_copy(update={"status": "error", "status_message": _clip(item.message)}))
            session.log(item.message or item.name, "error")
        elif not item.changed:
            item.status = "ok"
            if item.existing is not None and (
                item.existing.source != item.source
                or (item.existing.spec is not None and item.existing.spec.model_dump() != item.spec.model_dump())
            ):
                persist.append(_make_record(ops, item, "ok", item.existing.status_message))
    changed = [i for i in items if i.changed and not (i.transient or i.adopted or i.conflict)]
    if not changed:
        return None
    if exists and file_names is None and (list_problem is not None or session.is_rust()):
        # The file exists but could not be listed (damaged, or the writer timed out / was busy): the ownership
        # check above did not run, and the writer's upsert would replace a foreign component of the same name.
        # Never write blindly – the change stays pending (the next sync lists the file again), and no ownership
        # intent is recorded for it.
        reason = list_problem or "der Bibliotheks-Writer konnte sie gerade nicht lesen"
        message = (
            f"{library.name} konnte nicht gelesen werden ({reason}) – nicht geschrieben, damit kein fremdes Bauteil "
            "gleichen Namens überschrieben wird. Die Änderung ist gespeichert und wird beim nächsten Synchronisieren "
            "geschrieben."
        )
        for item in changed:
            item.status, item.message, item.http_status = "pending", message, 503
            persist.append(_make_record(ops, item, "pending", message))
        session.log(f"{library.name}: nicht geschrieben – nicht lesbar ({reason})", "warn")
        return None
    intent = _with_intent(rel, library, manifest, [i.name for i in changed])
    if intent is not None:  # ownership is recorded before the file changes (survives failures and aborts)
        with session.bound():
            _store_manifest(rel, intent)
    refusal = session.altium.refusal(library)
    if refusal:
        for item in changed:
            item.status, item.message, item.http_status = "error", f"{library.name}: {refusal}.", 409
            persist.append(_make_record(ops, item, "error", item.message))
        session.log(f"{library.name}: {refusal} – nicht geschrieben.", "warn")
        return None
    if exists and manifest is not None and not state_ok:
        session.log(
            f"{library.name} wurde außerhalb von PartForge geändert – nur die geänderten Bauteile werden geschrieben, alle "
            "anderen bleiben unverändert.",
            "warn",
        )
    if not exists or (state_ok and file_names is not None and session.is_rust()):
        _load_library_records(ops, records, rel)  # a regeneration writes every registered component of the file
    library_records = _registry_for_library(records, rel)
    full: tuple[list[Any], list[tuple[Any, Any]]] | None = None
    if not exists:
        full = _full_specs(session, library_records, changed, [], None) or ([i.spec for i in changed], [])
    elif state_ok and file_names is not None and session.is_rust():
        full = _full_specs(session, library_records, changed, file_names, manifest)
    try:
        writer = session.writer()
        if full is not None:
            result = writer.write_library_full(library, full[0])
        else:
            result = ops.write(writer, library, [i.spec for i in changed])
    except (WriterUnavailable, RustWriterUnavailable) as exc:
        message = f"{exc} Die Änderung ist gespeichert und wird beim nächsten Synchronisieren geschrieben."
        for item in changed:
            item.status, item.message, item.http_status = "pending", message, 503
            persist.append(_make_record(ops, item, "pending", message))
        session.log(f"{library.name}: nicht geschrieben – {exc}", "warn")
        return None
    except (RustWriterError, RustValidationError, OSError, ValueError, RuntimeError) as exc:
        message = str(exc)
        status = _failure_status(exc)
        for item in changed:
            item.status, item.message, item.http_status = "error", message, status
            persist.append(_make_record(ops, item, "error", message))
        session.log(f"{library.name}: nicht geschrieben – {message}", "error")
        return None
    finally:
        forget_component_names(library)
    for warning in result.warnings:
        session.log(f"{library.name}: {warning}", "warn")
    written = {n.casefold() for n in result.written}
    for item in changed:
        key = item.name.casefold()
        if key in written and item.name not in result.errors:
            notes = [*item.notes, *_component_notes(result, item.name)]
            item.status, item.message = "ok", ("Hinweis: " + " ".join(notes)) if notes else None
            persist.append(_make_record(ops, item, "ok", item.message))
        else:
            item.message = result.errors.get(item.name) or next(iter(result.errors.values()), None) or (
                f"{ops.label} wurde nicht in {library.name} geschrieben."
            )
            # a file another program keeps open or another PartForge process writes is a conflict, not invalid data
            locked = any(text in item.message for text in ("anderen Programm geöffnet", "anderes PartForge-Fenster"))
            item.status, item.http_status = "error", 409 if locked else 400
            persist.append(_make_record(ops, item, "error", item.message))
    if result.errors:
        session.log(f"{library.name}: {len(result.errors)} Fehler beim Schreiben", "error")
    if full is not None and not result.errors:
        for rec, spec in full[1]:  # registered components regenerated by the full write
            if rec.name.casefold() not in written or (rec.status == "ok" and spec is rec.spec):
                continue
            update: dict[str, Any] = {"spec": spec, "status": "ok", "status_message": None}
            if isinstance(spec, FootprintSpec) and spec.step is not None:
                update["step_file"] = spec.step.file
            persist.append(rec.model_copy(update=update))
    if not result.written:
        return None
    _patch_layers_after_write(session, library)
    session.written.append(str(library))
    note = session.altium.reload(library)
    if note:
        session.log(note, "info")
    session.log(f"{library.name}: {ops.count(len(result.written))} geschrieben", "success")
    names_after: list[str] | None
    if full is not None and not result.errors:
        fingerprints = {s.name.casefold(): ops.fingerprint(s) for s in full[0]}
        names_after = [s.name for s in full[0]]
    else:
        ok_items = [i for i in changed if i.status == "ok"]
        fingerprints = {i.name.casefold(): ops.fingerprint(i.spec) for i in ok_items}
        if file_names is None or result.errors:
            names_after = None
        else:
            known = {n.casefold() for n in file_names}
            names_after = [*file_names, *[i.name for i in ok_items if i.name.casefold() not in known]]
    return _final_manifest(rel, library, manifest, state_ok, names_after, fingerprints)


def _patch_layers_after_write(session: _Session, library: Path) -> None:
    """PcbLibs built by the Altium backend get the workspace layer stack as well (the Rust
    writer applies it itself, see :meth:`RustLibraryOps._apply_layer_header`)."""
    if library_file_kind(library) != "pcblib" or not stackup.header_patch_enabled():
        return
    try:
        if session.writer().name == "rust":
            return
    except WriterUnavailable:
        return
    base, notes = stackup.workspace_stack(session.ws)
    for warning in [*notes, *stackup.patch_pcblib_layers(library, stackup.effective_stack(base, session.ws.settings.layers))]:
        session.log(warning, "warn")


def _relink_parts(session: _Session, ops: _KindOps, items: Iterable[_Item]) -> None:
    from ..db import parts

    usage = session.usage(ops.kind)
    for item in items:
        if item.transient or item.conflict or item.status != "ok":
            continue
        old = item.existing.library if item.existing is not None else None
        if old is not None and _rel_key(old) == _rel_key(item.rel):
            continue
        if not usage.get(item.name.casefold()):
            continue
        try:
            with session.bound():
                changed = parts.set_library_path(ops.kind, item.name, item.rel)
        except (JobCancelled, SyncError):
            raise
        except Exception as exc:  # noqa: BLE001 - registry and file are fine; report the link problem
            session.log(f"Pfade der Bauteile für {item.name} nicht angepasst: {exc}", "warn")
            continue
        if changed:
            moved = plural(changed, "Bauteil zeigt", "Bauteile zeigen")
            session.log(f"{moved} jetzt auf {item.rel} ({item.name})", "info")


@dataclass
class _EnsureResult:
    records: list[Any]
    items: list[_Item]  # the item answering each input spec (same order as ``records``)

    def failures(self) -> list[_Item]:
        return [i for i in dict.fromkeys(self.items) if i.status != "ok"]


def _ensure(
    session: _Session,
    ops: _KindOps,
    specs: Sequence[Any],
    *,
    sources: Mapping[str, RecordSource],
    category: str | None = None,
    allow_pin_changes: bool = False,
    conflicts: ConflictMode = "refuse",
    progress: tuple[float, float] = (0.0, 1.0),
    chosen: Path | None = None,
    force: bool = False,
) -> _EnsureResult:
    session.ensure_current()
    records = _records_by_names(ops.kind, [spec.name for spec in specs])
    items, order = _prepare_items(session, ops, specs, sources, category, allow_pin_changes, records,
                                  chosen=chosen, force=force)
    for item in dict.fromkeys(order):
        if item.transient:
            session.log(item.message or f"{item.name}: abgelehnt", "error")
    groups = _group(items)
    start, end = progress
    for index, (_key, group) in enumerate(sorted(groups.items())):
        session.check_cancelled()
        library = group[0].library
        session.progress(start + (end - start) * index / max(1, len(groups)), f"{library.name} …")
        persist: list[Any] = []
        with _library_held(library) as busy:
            if busy:  # another process writes this file: nothing written, the entries stay pending
                for item in group:
                    if item.transient or not item.changed:
                        item.status = "ok" if not item.transient else item.status
                        continue
                    item.status, item.message, item.http_status = "pending", busy, 409
                    persist.append(_make_record(ops, item, "pending", busy))
                session.log(busy, "warn")
                manifest = None
            else:
                manifest = _write_library(session, ops, library, group, records, persist,
                                          allow_pin_changes=allow_pin_changes, conflicts=conflicts)
            if persist or manifest is not None:
                with session.bound():
                    if persist:
                        stored = _upsert_records(ops, persist)
                        records.update({r.name.casefold(): r for r in stored})
                    if manifest is not None:
                        _store_manifest(group[0].rel, manifest)
        _relink_parts(session, ops, group)
    session.progress(end, _ensure_message(ops, items))
    usage = session.usage(ops.kind) if any(not i.transient for i in items) else {}
    out: list[Any] = []
    for item in order:
        if item.transient:
            out.append(_transient_record(ops, item))
            continue
        rec = records.get(item.name.casefold())
        if rec is None:  # pragma: no cover - every non-transient item is registered above
            rec = _make_record(ops, item, item.status, item.message)
        out.append(rec.model_copy(update={"usage": usage.get(item.name.casefold(), 0)}))
    return _EnsureResult(records=out, items=list(order))


def _ensure_message(ops: _KindOps, items: Sequence[_Item]) -> str:
    """Progress message after one kind: "Symbole geschrieben: 3", "Footprints geschrieben: 5 (2 unverändert,
    1 mit Fehler)"."""
    unique = list(dict.fromkeys(items))
    written = sum(1 for i in unique if i.changed and i.status == "ok" and not (i.transient or i.adopted or i.conflict))
    unchanged = sum(1 for i in unique if not i.changed and i.status == "ok" and not (i.adopted or i.conflict))
    adopted = sum(1 for i in unique if i.adopted)
    pending = sum(1 for i in unique if i.status == "pending")
    failed = sum(1 for i in unique if i.status not in ("ok", "pending"))
    extra = [f"{unchanged} unverändert"] if unchanged else []
    if adopted:
        extra.append(f"{adopted} aus der Datei übernommen")
    if pending:
        extra.append(f"{pending} vorgemerkt")
    if failed:
        extra.append(f"{failed} mit {'Fehler' if failed == 1 else 'Fehlern'}")
    return f"{ops.label_plural} geschrieben: {written}" + (f" ({', '.join(extra)})" if extra else "")


def _sources(specs: Sequence[Any], source: str) -> dict[str, RecordSource]:
    if source not in ("generated", "datasheet", "imported"):
        raise ValueError(
            f"Ungültige Herkunft „{source}“ – externe Bauteile werden über die externen Bibliotheken registriert, "
            "nicht geschrieben."
        )
    return {spec.name.casefold(): cast(RecordSource, source) for spec in specs}


def _failure_error(ops: _KindOps, result: _EnsureResult) -> SyncFailed | None:
    failures = result.failures()
    if not failures:
        return None
    first = failures[0]
    message = first.message or f"{ops.label} „{first.name}“ wurde nicht geschrieben."
    if len(failures) > 1:
        message += f" (und {len(failures) - 1} weitere)"
    return SyncFailed(message, status=first.http_status or 400, records=result.records)


#: From this many components in the target library a single save runs as a job.
SLOW_LIBRARY_COMPONENTS = 60
#: ... for footprints (cheaper per component) and from this many embedded STEP models.
SLOW_LIBRARY_FOOTPRINTS = 120
SLOW_LIBRARY_STEP_MODELS = 10


def validate_spec(spec: Spec) -> list[str]:
    """German problems that would prevent writing ``spec`` (empty = writable; a STEP model
    for extruded bodies is created by ``ensure_footprints`` itself)."""
    return _spec_problems(_Session(current(), None), spec)


def _kind_of(spec: Spec) -> Kind:
    return "symbol" if isinstance(spec, SymbolSpec) else "footprint"


def _choice(spec: Spec, library: str | os.PathLike[str] | None, ws: Workspace) -> Path | None:
    """Validated explicit target library of ``spec`` (``None`` = layout default)."""
    if library is None or not str(library).strip():
        return None
    return resolve_library_choice(_kind_of(spec), str(library), ws=ws)


def planned_library(spec: Spec, *, category: str | None = None, library: str | os.PathLike[str] | None = None) -> Path:
    """The library file ``ensure_*`` would write ``spec`` to (``library``: explicit target,
    validated by :func:`resolve_library_choice` – :class:`SyncError` 400)."""
    ws = current()
    session = _Session(ws, None)
    chosen = _choice(spec, library, ws)
    if isinstance(spec, SymbolSpec):
        existing: Any = registry.get_symbol(spec.name)
        return _target_library(session, SYMBOLS, spec, existing, category, chosen)
    existing = registry.get_footprint(spec.name)
    return _target_library(session, FOOTPRINTS, spec, existing, None, chosen)


def library_choice_conflict(spec: Spec, library: str | os.PathLike[str] | None) -> str | None:
    """German refusal (HTTP 409) if ``spec`` is registered in another library than the explicit
    target ``library`` (a save never moves a component between files); ``None`` otherwise."""
    ws = current()
    chosen = _choice(spec, library, ws)
    if chosen is None:
        return None
    ops = SYMBOLS if isinstance(spec, SymbolSpec) else FOOTPRINTS
    existing: Any = registry.get_symbol(spec.name) if ops.kind == "symbol" else registry.get_footprint(spec.name)
    if existing is None or existing.source == "external":
        return None
    session = _Session(ws, None)
    target = _target_library(session, ops, spec, existing, None, chosen)
    if _same_path(target, chosen):
        return None
    return library_move_refusal(ops.label, existing.name, session.rel(target), session.rel(chosen))


def write_is_slow(spec: Spec, *, category: str | None = None, library: str | os.PathLike[str] | None = None) -> bool:
    """Whether writing ``spec`` may take more than about a second (then the API uses a job):
    Altium backend, Altium running (document checks through scripts), a large library or a
    PcbLib with many embedded STEP models (the Rust writer re-embeds them on every write)."""
    settings = load_settings()
    if settings.altium.library_backend == "altium" or not settings.resolved_rust_writer():
        return True
    if globals()["altium_bridge"]() is not None:
        return True
    target = planned_library(spec, category=category, library=library)
    session = _Session(current(), None)
    names = session.names_in(target)
    if names is None:
        return True
    if isinstance(spec, SymbolSpec):
        return len(names) > SLOW_LIBRARY_COMPONENTS
    if len(names) > SLOW_LIBRARY_FOOTPRINTS:
        return True
    key = _rel_key(session.rel(target))
    models = sum(
        1 for r in registry.list_footprints(with_spec=False, with_usage=False) if r.step_file and _rel_key(r.library) == key
    )
    return models + (1 if spec.bodies or spec.step is not None else 0) > SLOW_LIBRARY_STEP_MODELS


def foreign_conflict(spec: Spec, *, category: str | None = None, writer: LibraryWriter | None = None,
                     library: str | os.PathLike[str] | None = None) -> str | None:
    """German message if the target library already contains a component of this name that
    PartForge does not own (``ensure_*`` would adopt it instead of writing ``spec``) – the
    editor refuses such a save; ``None`` otherwise."""
    ws = current()
    session = _Session(ws, None, writer)
    ops = SYMBOLS if isinstance(spec, SymbolSpec) else FOOTPRINTS
    existing: Any = registry.get_symbol(spec.name) if ops.kind == "symbol" else registry.get_footprint(spec.name)
    if existing is not None and existing.source == "external":
        return None  # refused separately (external libraries are read-only)
    target = _target_library(session, ops, spec, existing, category, _choice(spec, library, ws))
    names = session.names_in(target)
    actual = next((n for n in names or [] if n.casefold() == spec.name.casefold()), None)
    if actual is None:
        return None
    rel = session.rel(target)
    if _owned(actual, existing, rel, _load_manifest(rel)):
        return None
    return (
        f"{ops.label} „{actual}“ ist in {rel} bereits vorhanden, wurde aber nicht von PartForge erzeugt. PartForge "
        "überschreibt es nicht – bitte einen anderen Namen wählen oder das vorhandene Bauteil übernehmen "
        "(„Bibliotheken prüfen“ bzw. „Synchronisieren“) und danach bearbeiten."
    )


def ensure_symbols(
    specs: list[SymbolSpec],
    *,
    category: str | None = None,
    source: str = "generated",
    ctx: JobContext | None = None,
    allow_pin_changes: bool = False,
    writer: LibraryWriter | None = None,
    strict: bool = False,
    library: str | os.PathLike[str] | None = None,
) -> list[SymbolRecord]:
    """Register the symbols in pf_symbols and write them (batched per library file)
    with the configured writer. Existing symbols with identical geometry are left
    untouched; changed ones are updated. Returns the records (status ok/pending/error).

    A different pin-out for an existing symbol name is refused (status ``error``, nothing
    written or registered) unless ``allow_pin_changes``; ``writer`` overrides the configured
    backend (tests, tools); ``strict`` raises :class:`SyncFailed` if a symbol was not written;
    ``library`` is an explicit target library for new symbols (:func:`resolve_library_choice`;
    an invalid one raises :class:`SyncError` 400, a symbol registered in another library is
    refused with 409). A custom name is recorded in ``spec.generator`` (``name``).
    """
    session = _Session(current(), ctx, writer, watch=True)
    try:
        chosen = _choice(specs[0], library, session.ws) if specs else None
        result = _ensure(
            session, SYMBOLS, list(specs), sources=_sources(specs, source), category=category,
            allow_pin_changes=allow_pin_changes, chosen=chosen,
        )
    finally:
        session.finish()
    failure = _failure_error(SYMBOLS, result) if strict else None
    if failure is not None:
        raise failure
    return result.records


def ensure_footprints(
    specs: list[FootprintSpec],
    *,
    source: str = "generated",
    ctx: JobContext | None = None,
    writer: LibraryWriter | None = None,
    strict: bool = False,
    library: str | os.PathLike[str] | None = None,
) -> list[FootprintRecord]:
    """Register the footprints in pf_footprints and write them (batched per library).

    Footprints with extruded 3D bodies get a STEP file in the workspace ``3D`` folder that
    the writer embeds; ``writer`` overrides the configured backend (tests, tools); ``strict``
    raises :class:`SyncFailed` if a footprint was not written; ``library``: explicit target
    library (see :func:`ensure_symbols`). A custom name is recorded in ``spec.generator``.
    """
    session = _Session(current(), ctx, writer, watch=True)
    try:
        chosen = _choice(specs[0], library, session.ws) if specs else None
        result = _ensure(session, FOOTPRINTS, list(specs), sources=_sources(specs, source), chosen=chosen)
    finally:
        session.finish()
    failure = _failure_error(FOOTPRINTS, result) if strict else None
    if failure is not None:
        raise failure
    return result.records


# --------------------------------------------------------------------------- pending / hints

#: Symbol kind spellings found in older registry entries -> generator kind.
SYMBOL_KIND_ALIASES: dict[str, str] = {
    "diode_schottky": "schottky",
    "diode_zener": "zener",
    "diode_tvs": "tvs_uni",
    "tvs": "tvs_uni",
    "res": "resistor",
    "cap": "capacitor",
    "ind": "inductor",
    "ferrite": "ferrite_bead",
    "transistor_npn": "npn",
    "transistor_pnp": "pnp",
    "mosfet_n": "nmos",
    "mosfet_p": "pmos",
    "crystal": "crystal_2",
}

#: Upper bound of generator variants tried to find the request behind a symbol name.
MAX_HINT_VARIANTS = 128

_CHIP_NAME_RE = re.compile(r"^(RES|CAP|IND|DIO|LED)C(\d{4})X(\d{2,3})([MNL])?$", re.IGNORECASE)
_CHIP_PREFIX_KINDS: dict[str, tuple[str, ...]] = {
    "RES": ("R",),
    "CAP": ("C",),
    "IND": ("L", "FB"),
    "DIO": ("D",),
    "LED": ("LED",),
}
_NAME_SUFFIX_RE = re.compile(r"\(([^()]{1,24})\)\s*$")
_CONNECTOR_NAME_RE = re.compile(r"^Connector\s+(\d{1,2})x(\d{1,3})\b", re.IGNORECASE)
_CELLS_RE = re.compile(r"\b(\d{1,2})-Cell\b", re.IGNORECASE)


def _resolve_symbol_kind(rec: SymbolRecord) -> str | None:
    from ..symbols import kinds

    infos = kinds()
    keys = {info.key for info in infos}
    for raw in (rec.kind, rec.name):
        if not raw:
            continue
        token = str(raw).strip().casefold().replace("-", "_").replace(" ", "_")
        for candidate in (token, SYMBOL_KIND_ALIASES.get(token), token.removeprefix("diode_")):
            if candidate and candidate in keys:
                return candidate
        for info in infos:
            if info.default_name.casefold() == str(raw).strip().casefold():
                return info.key
    return None


def _hint_requests(kind: str, name: str) -> list[Any]:
    """Generator requests that may produce a symbol called ``name`` (defaults first): every
    combination of the kind's choices, the pin map of a ``(…)`` suffix, connector size and
    battery cells from the name."""
    from ..symbols import SymbolRequest, kinds

    info = next((k for k in kinds() if k.key == kind), None)
    params = list(info.params) if info is not None else []
    names = {p.name for p in params}
    fixed: dict[str, Any] = {}
    match = _CONNECTOR_NAME_RE.match(name.strip())
    if match and {"rows", "pins"} <= names:
        rows, per_row = int(match.group(1)), int(match.group(2))
        fixed.update(rows=str(rows), pins=rows * per_row)
    match = _CELLS_RE.search(name)
    if match and "cells" in names:
        fixed["cells"] = int(match.group(1))
    suffix = _NAME_SUFFIX_RE.search(name)
    axes: list[tuple[str, list[Any]]] = []
    for param in params:
        if param.name in fixed:
            axes.append((param.name, [fixed[param.name]]))
        elif param.kind == "enum" and param.options:
            default = param.default if param.default in param.options else param.options[0]
            values: list[Any] = [default]
            if param.name == "pinmap" and suffix:
                values.append(suffix.group(1).strip())
            values += [o for o in param.options if o not in values]
            axes.append((param.name, values))
        elif param.kind == "bool":
            default_flag = bool(param.default)
            axes.append((param.name, [default_flag, not default_flag]))
    requests: list[Any] = []
    for combo in itertools.islice(itertools.product(*(values for _, values in axes)), MAX_HINT_VARIANTS):
        requests.append(SymbolRequest(kind=kind, params={axes[i][0]: value for i, value in enumerate(combo)}))
    return requests or [SymbolRequest(kind=kind)]


def _hint_styles(style: SymbolStyle, kind: str) -> list[SymbolStyle]:
    """The workspace style, plus the opposite diode numbering for diode kinds (a name without
    suffix always means the canonical numbering, whatever the house style says)."""
    from ..symbols.standard import is_diode_kind

    styles = [style]
    if is_diode_kind(kind):
        flipped = "anode" if style.diode_pin1 == "cathode" else "cathode"
        styles.append(style.model_copy(update={"diode_pin1": flipped}))
    return styles


def _hint_counts_match(rec: SymbolRecord, spec: SymbolSpec) -> bool:
    if rec.pin_count and len(spec.pins) != rec.pin_count:
        return False
    return not (rec.part_count and rec.part_count > 1 and spec.part_count != rec.part_count)


def _symbol_from_hints(ws: Workspace, rec: SymbolRecord) -> tuple[SymbolSpec | None, str | None]:
    """Generate a spec-less symbol entry from its kind – never renaming a generated symbol
    whose pin-out depends on the name (``Diode`` is always cathode = pin 1, ``Diode (AK)``
    anode = pin 1). A custom name (``Widerstand``) is only accepted for kinds whose pin-out
    is the same in every variant; otherwise the entry stays ``missing``."""
    from ..symbols import SymbolError, generate

    kind = _resolve_symbol_kind(rec)
    if kind is None:
        return None, (
            f"Symbol „{rec.name}“ kann nicht erzeugt werden: Symboltyp „{rec.kind or '–'}“ ist unbekannt. Bitte im "
            "Symbol-Generator erzeugen oder aus einer Bibliothek übernehmen."
        )
    if kind == "ic":
        return None, (
            f"Symbol „{rec.name}“ ist ein IC-Symbol und braucht eine Pinliste – bitte über den Datenblatt-Import oder "
            "den Symbol-Generator anlegen."
        )
    wanted = rec.name.strip().casefold()
    first: SymbolSpec | None = None
    pinouts: list[dict[str, tuple[str, int]]] = []
    for request in _hint_requests(kind, rec.name):
        for style in _hint_styles(ws.settings.symbol, kind):
            try:
                spec = generate(request, style)
            except (SymbolError, ValueError):
                continue
            if not _hint_counts_match(rec, spec):
                continue
            if spec.name.casefold() == wanted:
                return (spec if spec.name == rec.name else spec.model_copy(update={"name": rec.name})), None
            if first is None:
                first = spec
            layout = pinout(spec)
            if layout not in pinouts:
                pinouts.append(layout)
    if first is not None and len(pinouts) == 1:
        return first.model_copy(update={"name": rec.name}), None  # pin-out independent of every choice
    return None, (
        f"Symbol „{rec.name}“: Pinbelegung aus den gespeicherten Angaben (Typ {kind}) nicht eindeutig erzeugbar – bitte "
        "im Symbol-Generator anlegen oder aus einer Bibliothek übernehmen."
    )


def _footprint_requests(ws: Workspace, rec: FootprintRecord) -> list[Any]:
    from ..footprints import FootprintRequest, chip_request, presets
    from ..footprints.families.chip import normalize_size

    density = ws.settings.footprint.density
    requests: list[Any] = []
    for name in dict.fromkeys(n for n in (rec.ipc_name, rec.name) if n):
        m = _CHIP_NAME_RE.match(name)
        if m and (rec.family in (None, "", "chip")):
            try:
                size = normalize_size(m.group(2) + "M")
            except ValueError:
                continue
            chip_density = (m.group(4) or density).upper()
            for kind in _CHIP_PREFIX_KINDS[m.group(1).upper()]:
                base = chip_request(kind, size, density=chip_density)
                requests.append(base)
                requests.append(base.model_copy(update={"params": {**base.params, "H": int(m.group(3)) / 100}}))
    if rec.family:
        try:
            family_presets = presets(rec.family)
        except ValueError:
            family_presets = []
        for chosen in dict.fromkeys((density, "N", "M", "L")):
            for preset in family_presets:
                requests.append(FootprintRequest(family=rec.family, params={"preset": preset.key}, density=chosen))
    return requests


def _footprint_from_hints(ws: Workspace, rec: FootprintRecord) -> tuple[FootprintSpec | None, str | None]:
    """Generate a spec-less footprint entry: only a generator result whose name or IPC name
    equals the entry (the IPC name encodes the geometry) with the registered pad count."""
    from ..footprints import generate

    wanted = {n.casefold() for n in (rec.name, rec.ipc_name) if n}
    for request in _footprint_requests(ws, rec):
        try:
            spec = generate(request, ws.settings.footprint)
        except ValueError:
            continue
        names = {spec.name.casefold(), (spec.ipc_name or "").casefold()}
        if not names & wanted:
            continue
        if rec.pad_count and len(spec.pads) != rec.pad_count:
            continue
        if spec.name != rec.name:
            spec = spec.model_copy(update={"name": rec.name})
        return spec, None
    return None, (
        f"Footprint „{rec.name}“ kann aus den gespeicherten Angaben (Familie {rec.family or '–'}) nicht erzeugt werden – "
        "bitte mit dem Footprint-Generator anlegen oder aus einer Bibliothek übernehmen."
    )


def _spec_from_hints(ws: Workspace, rec: Any) -> tuple[Any | None, str | None]:
    if isinstance(rec, SymbolRecord):
        return _symbol_from_hints(ws, rec)
    return _footprint_from_hints(ws, rec)


def _adoption_message(library: Path, notes: Sequence[str]) -> str:
    message = f"Aus der vorhandenen Bibliothek {library.name} übernommen."
    if notes:
        message += " Beim Speichern aus PartForge ginge verloren: " + " ".join(notes[:3])
    return message


def _adopt_existing(session: _Session, ops: _KindOps, rec: Any) -> bool:
    """A pending entry without geometry whose component already exists in its library file
    takes the geometry from the file (status ``ok``, ``imported``) – a generated one never
    overwrites it."""
    path = session.ws.abs(rec.library) if rec.library else None
    if path is None or not path.is_file() or not is_inside(path, session.ws.root):
        return False
    names = session.names_in(path)
    actual = next((n for n in names or [] if n.casefold() == rec.name.casefold()), None)
    if actual is None:
        return False
    notes: list[str] = []
    try:
        spec = _read_component(session.writer(), path, actual, extract_step=True, notes=notes)
    except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
        session.log(f"{rec.name} aus {path.name} nicht lesbar: {exc}", "warn")
        spec = None
    message = _adoption_message(path, notes)
    update: dict[str, Any] = {"spec": spec, "status": "ok", "status_message": _clip(message), "source": "imported"}
    if isinstance(spec, SymbolSpec):
        update["pin_count"] = len(spec.pins)
        update["part_count"] = spec.part_count
    elif isinstance(spec, FootprintSpec):
        update["pad_count"] = len(spec.pads)
        update["height"] = spec.height
        update["step_file"] = spec.step.file if spec.step is not None else None
    with session.bound():
        if ops.kind == "symbol":
            registry.upsert_symbol(rec.model_copy(update=update))
        else:
            registry.upsert_footprint(rec.model_copy(update=update))
    session.log(f"{rec.name}: {message}", "info")
    return True


def sync_pending(ctx: JobContext | None = None) -> dict:
    """Write every registry entry whose status is 'pending' or 'error'.

    Entries without geometry are generated from their hints first (symbol kind; footprint
    family + IPC name); if that is impossible they get status ``missing`` with the reason.
    A component of the same name that already exists in the library file is adopted, never
    overwritten (a symbol with another pin-out is reported as ``error``). Without a usable
    library writer nothing changes: the summary carries ``skipped`` and ``reason`` and the
    entries stay ``pending``. Returns ``{symbols, footprints, libraries, errors, missing}``.
    """
    ws = current()
    session = _Session(ws, ctx, watch=True)
    summary: dict[str, Any] = {"symbols": {}, "footprints": {}, "libraries": [], "errors": [], "missing": []}
    try:
        session.ensure_current()
        work = {ops.kind: _pending_work(session, ops) for ops in (SYMBOLS, FOOTPRINTS)}
        if any(work.values()):
            try:
                session.writer()
            except WriterUnavailable as exc:
                reason = (
                    f"{exc} Ausstehende Symbole und Footprints bleiben vorgemerkt und werden beim nächsten Synchronisieren "
                    "geschrieben."
                )
                session.log(reason, "warn")
                for ops in (SYMBOLS, FOOTPRINTS):
                    key = "symbols" if ops.kind == "symbol" else "footprints"
                    summary[key] = {"total": len(work[ops.kind]), "ok": 0, "error": 0, "missing": 0, "adopted": 0}
                summary.update(skipped=True, reason=reason)
                return summary
        for ops, span in ((SYMBOLS, (0.0, 0.5)), (FOOTPRINTS, (0.5, 1.0))):
            regs = work[ops.kind]
            key = "symbols" if ops.kind == "symbol" else "footprints"
            totals = {"total": len(regs), "ok": 0, "error": 0, "missing": 0, "adopted": 0}
            session.progress(span[0], f"{ops.count(len(regs))} zu schreiben")
            groups: dict[str, list[_Reg]] = {}
            for reg in regs:  # one library file at a time: only its specs are in memory (perf-memory-registry)
                groups.setdefault(_rel_key(reg.library), []).append(reg)
            ordered = sorted(groups.items())
            width = (span[1] - span[0]) / max(1, len(ordered))
            for index, (_key, group) in enumerate(ordered):
                records = _records_by_names(ops.kind, [reg.name for reg in group])
                specs: list[Any] = []
                sources: dict[str, RecordSource] = {}
                for reg in group:
                    session.check_cancelled()
                    rec = records.get(reg.name.casefold())
                    if rec is None:
                        totals["total"] -= 1  # unregistered meanwhile
                        continue
                    if rec.spec is not None:
                        spec, reason = rec.spec, None
                    elif _adopt_existing(session, ops, rec):
                        totals["ok"] += 1
                        totals["adopted"] += 1
                        continue
                    else:
                        spec, reason = _spec_from_hints(ws, rec)
                    if spec is None:
                        totals["missing"] += 1
                        with session.bound():
                            _set_status(ops.kind, rec.name, "missing", reason)
                        summary["missing"].append({"kind": ops.kind, "name": rec.name, "message": reason})
                        session.log(reason or rec.name, "warn")
                        continue
                    specs.append(spec)
                    sources[spec.name.casefold()] = rec.source
                del records
                if not specs:
                    continue
                low = span[0] + width * index
                result = _ensure(session, ops, specs, sources=sources, conflicts="record", progress=(low, low + width))
                for record in result.records:
                    if record.status != "ok":
                        summary["errors"].append({"kind": ops.kind, "name": record.name,
                                                  "message": record.status_message})
                totals["ok"] += sum(1 for r in result.records if r.status == "ok")
                totals["error"] += sum(1 for r in result.records if r.status != "ok")
                totals["adopted"] += sum(1 for item in dict.fromkeys(result.items) if item.adopted)
                del specs, result
            summary[key] = totals
        summary["libraries"] = list(dict.fromkeys(session.written))
        summary["relinked"] = _relink_mismatched_parts(session)
    finally:
        session.finish()
    return summary


#: Status message of an imported component that vanished from its file (removed or renamed outside PartForge).
_IMPORTED_GONE: Final = (
    "Fehlt in {library} – außerhalb von PartForge entfernt oder umbenannt; wird nicht aus der Lesekopie neu "
    "geschrieben (bei Bedarf die Datei erneut importieren)."
)


def _pending_work(session: _Session, ops: _KindOps) -> list[_Reg]:
    """The entries :func:`sync_pending` writes (without their specs): status ``pending``/``error`` – and ``ok``
    entries that are missing from their (readable) library file or whose file is gone, e.g. after a restored
    database backup or a write lost in a crash (INT-06). Imported components are never written from their
    read-back spec: one that vanished from its file becomes ``missing`` instead."""
    regs = _registry_rows(ops.kind)
    records = [r for r in regs.values() if r.status in ("pending", "error") and r.source != "external"]
    by_file: dict[str, list[_Reg]] = {}
    for reg in regs.values():
        if reg.status == "ok" and reg.source != "external" and reg.has_spec and reg.library:
            by_file.setdefault(_rel_key(reg.library), []).append(reg)
    lost: list[_Reg] = []
    for regs in by_file.values():
        path = session.ws.abs(regs[0].library)
        if path is None or not is_inside(path, session.ws.root) or os.path.normcase(str(path)) in session.external_paths():
            continue
        if path.is_file():
            names, _problem = session.list_names(path)
            if names is None:
                continue  # unreadable or no writer to list it: never written blindly (the health check reports it)
            present = {n.casefold() for n in names}
        else:
            present = set()
        lost.extend(reg for reg in regs if reg.name.casefold() not in present)
    for reg in lost:
        if reg.source == "imported":
            # The file is the source of truth of an imported component; its registry spec is only a (lossy)
            # read-back. A copy the user removed in Altium is therefore not resurrected from it – it is reported
            # as missing (re-importing the file brings it back).
            message = _IMPORTED_GONE.format(library=reg.library)
            with session.bound():
                _set_status(ops.kind, reg.name, "missing", message)
            session.log(f"{ops.label} „{reg.name}“ {message[0].lower()}{message[1:]}", "warn")
            continue
        records.append(reg)
        session.log(f"{ops.label} „{reg.name}“ fehlt in {reg.library} – wird neu geschrieben.", "warn")
    return [r for r in records if r.source != "imported"]


def _relink_mismatched_parts(session: _Session) -> int:
    """Point parts whose Library/Footprint Path disagrees with the registry to the registered
    file (only components that are ``ok``, i.e. present in that file). Returns the number of
    changed parts."""
    from ..db import parts

    session.ensure_current()
    registered: dict[Kind, dict[str, Any]] = {
        "symbol": {r.name.casefold(): r for r in registry.list_symbols(with_spec=False, with_usage=False)},
        "footprint": {r.name.casefold(): r for r in registry.list_footprints(with_spec=False, with_usage=False)},
    }
    wrong: dict[tuple[Kind, str], Any] = {}
    for _table, _pn, links in _iter_part_links():
        for _ref_col, _path_col, kind, ref, stored in links:
            rec = registered[kind].get(ref.casefold()) if ref else None
            if rec is None or rec.status != "ok" or not rec.library:
                continue
            if _rel_key(stored) != _rel_key(rec.library):
                wrong[(kind, rec.name.casefold())] = rec
    changed = 0
    for (kind, _key), rec in wrong.items():
        try:
            with session.bound():
                changed += parts.set_library_path(kind, rec.name, rec.library)
        except (JobCancelled, SyncError):
            raise
        except Exception as exc:  # noqa: BLE001 - one bad link must not stop the others
            session.log(f"Pfade der Bauteile für {rec.name} nicht angepasst: {exc}", "warn")
    if changed:
        aligned = plural(changed, "Bauteil", "Bauteile")
        session.log(f"{aligned} auf die eingetragene Bibliotheksdatei ausgerichtet", "info")
    return changed


def _set_status(kind: Kind, name: str, status: RecordStatus, message: str | None) -> None:
    """Set the registry status (like ``registry.set_*_status`` – without reading the record and every part's usage
    back, which the sync never needs)."""
    from sqlalchemy import func, update

    from ..db.schema import now_iso, pf_footprints, pf_symbols

    table = pf_symbols if kind == "symbol" else pf_footprints
    values = {"status": status, "status_message": _clip(message), "updated": now_iso()}
    with db_core.connect() as conn:
        if conn.execute(update(table).where(table.c.name == name).values(**values)).rowcount:
            return
        if not conn.execute(update(table).where(func.lower(table.c.name) == name.lower()).values(**values)).rowcount:
            raise SyncError(f"„{name}“ ist nicht registriert.", status=404)


def _upsert_records(ops: _KindOps, records: Sequence[Any]) -> list[Any]:
    """``registry.upsert_symbols``/``upsert_footprints`` – but read back only the written records (the registry
    function lists every record with its spec and every part's usage after each batch)."""
    upsert = getattr(registry, "_upsert", None)
    values = getattr(registry, "_symbol_values" if ops.kind == "symbol" else "_footprint_values", None)
    if upsert is None or values is None:  # pragma: no cover - registry internals changed: the public API
        return ops.upsert(records)
    from ..db.schema import pf_footprints, pf_symbols

    table = pf_symbols if ops.kind == "symbol" else pf_footprints
    names: list[str] = []
    with db_core.connect() as conn:
        for rec in records:
            names.append(upsert(conn, table, rec.name, values(rec)))
    found = _records_by_names(ops.kind, names)
    return [found[n.casefold()] for n in dict.fromkeys(names) if n.casefold() in found]


# --------------------------------------------------------------------------- scan


def scan_library(path: Path) -> list[ComponentInfo]:
    """List the components of any SchLib/PcbLib (also external libraries)."""
    library = Path(os.path.abspath(os.fspath(path)))
    if library_file_kind(library) is None:
        raise SyncError(f"{library.name} ist keine Altium-Bibliothek (.SchLib oder .PcbLib).")
    if not library.is_file():
        raise SyncError(f"Bibliothek nicht gefunden: {library}", status=404)
    try:
        writer = get_writer(workspace=current_or_none())
        return writer.scan_library(library)
    except WriterUnavailable as exc:
        raise SyncError(str(exc), status=503) from exc
    except (RustWriterError, OSError, RuntimeError) as exc:
        raise SyncError(f"Die Bibliothek {library.name} kann nicht gelesen werden: {exc}") from exc


# --------------------------------------------------------------------------- delete


def _delete(kind: Kind, names: Sequence[str], *, force: bool, ctx: JobContext | None, writer: LibraryWriter | None) -> dict:
    ops = _ops_for(kind)
    session = _Session(current(), ctx, writer, watch=True)
    out: dict[str, Any] = {"deleted": [], "unregistered": [], "refused": {}, "errors": {}, "not_found": [], "libraries": []}
    try:
        session.ensure_current()
        usage = session.usage(kind)
        by_library: dict[str, list[Any]] = {}
        for name in dict.fromkeys(names):
            rec = registry.get_symbol(name) if kind == "symbol" else registry.get_footprint(name)
            if rec is None:
                out["not_found"].append(name)
                continue
            used = usage.get(rec.name.casefold(), 0)
            if used and not force:
                out["refused"][rec.name] = (
                    f"{ops.label} „{rec.name}“ wird von {plural(used, 'Bauteil', 'Bauteilen')} verwendet und wird daher "
                    "nicht gelöscht."
                )
                continue
            path = session.ws.abs(rec.library) if rec.library else None
            if (
                rec.source == "external"
                or path is None
                or not path.exists()
                or not is_inside(path, session.ws.root)
                or os.path.normcase(str(path)) in session.external_paths()
            ):
                with session.bound():
                    _unregister(kind, rec.name)
                out["unregistered"].append(rec.name)
                continue
            by_library.setdefault(str(path), []).append(rec)
        for library_text, recs in by_library.items():
            session.check_cancelled()
            library = Path(library_text)
            names_here = [r.name for r in recs]
            rel = session.rel(library)
            with _library_held(library) as busy:
                if busy:
                    for name in names_here:
                        out["errors"][name] = busy
                    continue
                refusal = session.altium.refusal(library)
                if refusal:
                    for name in names_here:
                        out["errors"][name] = f"{library.name}: {refusal}."
                    continue
                before_names = session.names_in(library)
                manifest = _load_manifest(rel)
                state_ok = manifest is not None and manifest.matches(library)
                try:
                    result = session.writer().delete_components(library, names_here)
                except (WriterUnavailable, RustWriterError, OSError, RuntimeError, ValueError) as exc:
                    for name in names_here:
                        out["errors"][name] = str(exc)
                    continue
                finally:
                    forget_component_names(library)
                gone = {n.casefold() for n in result.deleted} | {
                    w.split(":", 1)[0].casefold() for w in result.warnings if "nicht in der Bibliothek" in w
                }
                final: _Manifest | None = None
                if result.deleted and library.exists():
                    _patch_layers_after_write(session, library)
                    deleted = {n.casefold() for n in result.deleted}
                    remaining = [n for n in before_names if n.casefold() not in deleted] if before_names is not None else None
                    final = _final_manifest(rel, library, manifest, state_ok, remaining, {})
                with session.bound():
                    for rec in recs:
                        if rec.name in result.errors:
                            out["errors"][rec.name] = result.errors[rec.name]
                        elif rec.name.casefold() in gone:
                            _unregister(kind, rec.name)
                            out["deleted"].append(rec.name)
                            if isinstance(rec, FootprintRecord):
                                _remove_orphaned_step(session, rec)
                    if result.deleted:
                        _store_manifest(rel, final)
                if result.deleted:
                    session.written.append(str(library))
                    out["libraries"].append(str(library))
                    note = session.altium.reload(library)
                    if note:
                        session.log(note)
    finally:
        session.finish()
    return out


def _remove_orphaned_step(session: _Session, rec: FootprintRecord) -> None:
    """Delete the PartForge STEP model of a deleted footprint if nothing else uses it."""
    path = _resolve_model_path(session.ws, rec.step_file)
    if path is None or not path.is_file() or not is_inside(path, session.ws.models_dir):
        return
    if _PARTFORGE_STEP_MARK not in (_read_text(path) or "")[:600]:
        return  # a vendor model is never deleted
    key = os.path.normcase(str(path))
    for other in registry.list_footprints(with_spec=False, with_usage=False):
        other_path = _resolve_model_path(session.ws, other.step_file)
        if other_path is not None and os.path.normcase(str(other_path)) == key:
            return
    try:
        path.unlink()
        session.log(f"STEP-Modell {path.name} entfernt (wurde nur von {rec.name} verwendet).")
    except OSError as exc:
        session.log(f"STEP-Modell {path.name} konnte nicht entfernt werden: {exc}", "warn")


def _unregister(kind: Kind, name: str) -> None:
    if kind == "symbol":
        registry.delete_symbol(name)
    else:
        registry.delete_footprint(name)


def delete_symbols(
    names: Sequence[str], *, force: bool = False, ctx: JobContext | None = None, writer: LibraryWriter | None = None
) -> dict:
    """Delete symbols from their library and the registry (refused while parts use them,
    unless ``force``). External symbols are only unregistered – their file is never written."""
    return _delete("symbol", names, force=force, ctx=ctx, writer=writer)


def delete_footprints(
    names: Sequence[str], *, force: bool = False, ctx: JobContext | None = None, writer: LibraryWriter | None = None
) -> dict:
    """Delete footprints from their library and the registry (see :func:`delete_symbols`)."""
    return _delete("footprint", names, force=force, ctx=ctx, writer=writer)


# --------------------------------------------------------------------------- library files


class LibraryFileInfo(BaseModel):
    path: str
    rel: str
    kind: Literal["schlib", "pcblib"]
    exists: bool = True
    components: int | None = None  # None = not readable
    size: int | None = None
    modified: str | None = None
    registered: int = 0
    managed: bool = Field(
        default=False,
        description="PartForge hat jedes Bauteil der Datei selbst geschrieben und erzeugt sie als Ganzes neu",
    )
    in_sync: bool = False  # every component registered, none missing, all ok, no changes outside PartForge
    external_changes: bool = Field(
        default=False, description="Seit dem letzten Schreiben durch PartForge außerhalb geändert (z. B. in Altium)"
    )
    missing: list[str] = Field(default_factory=list)  # registered, but not in the file
    unregistered: list[str] = Field(default_factory=list)  # in the file, not registered
    pending: int = 0
    errors: int = 0
    layers_ok: bool | None = None  # PcbLib header matches the workspace layer stack
    unreadable: bool = Field(default=False, description="Datei vorhanden, aber nicht lesbar (vermutlich beschädigt)")
    message: str | None = None


def _combined(symbols: Sequence[SymbolRecord], footprints: Sequence[FootprintRecord]) -> list[Record]:
    out: list[Record] = [*symbols, *footprints]
    return out


def _all_records() -> tuple[list[SymbolRecord], list[FootprintRecord]]:
    return (
        registry.list_symbols(with_spec=False, with_usage=False),
        registry.list_footprints(with_spec=False, with_usage=False),
    )


def library_files(*, check_layers: bool = True, writer: LibraryWriter | None = None) -> list[LibraryFileInfo]:
    """Every library file of the workspace (plus files registered but missing)."""
    ws = current()
    session = _Session(ws, None, writer)
    symbols, footprints = _all_records()
    by_library: dict[str, list[Any]] = {}
    for rec in _combined(symbols, footprints):
        if rec.source == "external" or not rec.library:
            continue
        by_library.setdefault(_rel_key(rec.library), []).append(rec)
    paths: dict[str, Path] = {_rel_key(ws.rel(p)): p for p in workspace_library_files(ws)}
    for key, recs in by_library.items():
        if key not in paths:
            path = ws.abs(recs[0].library)
            if path is not None and library_file_kind(path) is not None and not is_temp_library_file(path):
                paths[key] = Path(os.path.abspath(path))
    stack: stackup.LayerStack | None = None
    if check_layers:
        stack = stackup.effective_stack(stackup.workspace_stack(ws)[0], ws.settings.layers)
    out: list[LibraryFileInfo] = []
    for key, path in sorted(paths.items()):
        kind = library_file_kind(path)
        assert kind is not None
        recs = [r for r in by_library.get(key, []) if (kind == "schlib") == isinstance(r, SymbolRecord)]
        info = LibraryFileInfo(path=str(path), rel=ws.rel(path), kind=kind, exists=path.is_file(), registered=len(recs))
        info.pending = sum(1 for r in recs if r.status == "pending")
        info.errors = sum(1 for r in recs if r.status in ("error", "missing"))
        registered = {r.name.casefold() for r in recs}
        if info.exists:
            stat = path.stat()
            info.size = stat.st_size
            info.modified = _dt.datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
            manifest = _load_manifest(info.rel)
            state_ok = manifest is not None and manifest.matches(path)
            info.external_changes = manifest is not None and not state_ok
            names, problem = session.list_names(path)
            if names is None and problem:
                info.unreadable = True
                info.message = f"Datei nicht lesbar – vermutlich beschädigt: {problem}."
            elif names is None:
                info.message = "Inhalt nicht prüfbar – kein Bibliotheks-Writer verfügbar."
            else:
                info.components = len(names)
                present = {n.casefold() for n in names}
                info.missing = sorted((r.name for r in recs if r.name.casefold() not in present), key=_natural)
                info.unregistered = sorted((n for n in names if n.casefold() not in registered), key=_natural)
                info.managed = (
                    state_ok
                    and manifest is not None
                    and not info.unregistered
                    and all(manifest.components.get(n.casefold()) is not None for n in names)
                )
                info.in_sync = (
                    not info.unregistered
                    and not info.missing
                    and all(r.status == "ok" for r in recs)
                    and not info.external_changes
                )
            if info.external_changes and not info.unreadable:
                info.message = "Seit dem letzten Schreiben durch PartForge außerhalb geändert (z. B. in Altium gespeichert)."
            if kind == "pcblib" and stack is not None:
                info.layers_ok = not stackup.pcblib_layer_problems(path, stack)
        else:
            info.missing = sorted((r.name for r in recs), key=_natural)
            info.message = "Datei fehlt – „Synchronisieren“ schreibt sie neu."
        out.append(info)
    return out


def manifest_snapshot() -> dict[str, str]:
    """The stored library manifests (``pf_meta`` text per key) – taken **before** a database backup is restored
    and passed to :func:`scan_workspace` (``previous_manifests``), they describe the files as they are."""
    return db_meta.meta_items(_MANIFEST_PREFIX)


def scan_workspace(ctx: JobContext | None = None, *, register: bool = False, writer: LibraryWriter | None = None,
                   rebaseline: bool = False, previous_manifests: Mapping[str, str] | None = None) -> dict:
    """Compare library files and registry; update statuses (and optionally register unknown
    components as ``imported``).

    Registered components that are missing in their file become ``pending`` (the next sync
    writes them again); ``missing``/``pending`` ones found in their file become ``ok``.
    External components are checked against their library (``missing`` if gone). Libraries
    changed outside PartForge since its last write are listed in ``changed_outside``, files that
    exist but cannot be read (damaged) in ``unreadable``.

    ``rebaseline`` (after a restored database backup, INT-06): a file "changed outside" whose components
    all match the registry by name becomes PartForge's own again – its manifest is set to the file as it
    is. With ``previous_manifests`` (:func:`manifest_snapshot` taken before the restore) a component keeps
    a known content only where the file is unchanged since that manifest and the restored registry spec
    is what PartForge wrote; every other own component is marked ``pending`` (the registry is the target
    state) – without it, their content counts as unknown (PartForge then only replaces them).
    """
    ws = current()
    session = _Session(ws, ctx, writer, watch=True)
    result: dict[str, Any] = {
        "files": 0, "updated": [], "unregistered": [], "registered": [], "conflicts": [], "external_missing": [],
        "changed_outside": [], "unreadable": [], "rebaselined": [],
    }
    try:
        session.ensure_current()
        files = library_files(check_layers=False, writer=writer)
        result["files"] = len(files)
        result["unreadable"] = [{"library": info.rel, "message": info.message} for info in files if info.unreadable]
        for entry in result["unreadable"]:
            session.log(f"{entry['library']}: {entry['message']} Altium und PartForge können die Bauteile darin nicht "
                        "verwenden – in der Bibliotheksprüfung „Aus Sicherung wiederherstellen“ wählen (wenn es eine "
                        "lesbare Sicherung gibt) oder die Datei entfernen; „Synchronisieren“ schreibt die Bauteile von "
                        "PartForge dann neu.", "error")
        result["changed_outside"] = [info.rel for info in files if info.external_changes and not info.unreadable]
        if rebaseline:
            done = _rebaseline(session, files, previous_manifests, result)
            result["changed_outside"] = [rel for rel in result["changed_outside"] if rel not in done]
        for rel in result["changed_outside"]:
            session.log(f"{rel} wurde außerhalb von PartForge geändert – PartForge schreibt dort nur noch die "
                        "geänderten Bauteile und lässt alle anderen unverändert.", "warn")
        symbols, footprints = _all_records()
        state: dict[str, Any] = {}
        for index, info in enumerate(files):
            session.check_cancelled()
            session.progress(index / max(1, len(files)), info.rel)
            if info.components is None and info.exists:
                continue
            kind: Kind = "symbol" if info.kind == "schlib" else "footprint"
            recs = [r for r in (symbols if kind == "symbol" else footprints)
                    if r.source != "external" and _rel_key(r.library) == _rel_key(info.rel)]
            missing = {n.casefold() for n in info.missing}
            for rec in recs:
                if rec.name.casefold() in missing:
                    if rec.source == "imported":
                        if rec.status != "missing":  # the file decides: never rewritten from the read-back
                            message = _IMPORTED_GONE.format(library=info.rel)
                            with session.bound():
                                _set_status(kind, rec.name, "missing", message)
                            result["updated"].append({"kind": kind, "name": rec.name, "status": "missing",
                                                      "message": message})
                    elif rec.status == "ok":
                        message = f"Fehlt in {info.rel} – wird beim Synchronisieren neu geschrieben."
                        with session.bound():
                            _set_status(kind, rec.name, "pending", message)
                        result["updated"].append({"kind": kind, "name": rec.name, "status": "pending", "message": message})
                elif rec.status == "missing":
                    with session.bound():
                        _set_status(kind, rec.name, "ok", None)
                    result["updated"].append({"kind": kind, "name": rec.name, "status": "ok", "message": None})
            known = {r.name.casefold(): r for r in (symbols if kind == "symbol" else footprints)}
            for name in info.unregistered:
                other = known.get(name.casefold())
                if other is not None:  # the name belongs to another library: never move it silently
                    result["conflicts"].append({
                        "kind": kind, "name": name, "library": info.rel, "registered_library": other.library,
                        "message": f"„{name}“ ist auch in {info.rel} enthalten, registriert ist es aber in "
                        f"{other.library or 'keiner Bibliothek'}.",
                    })
                    continue
                result["unregistered"].append({"kind": kind, "name": name, "library": info.rel})
                if register:
                    state.setdefault(info.path, []).append(name)
        for library_text, names in state.items():
            session.check_cancelled()
            registered = _register_imported(session, Path(library_text), names)
            result["registered"].extend(registered)
        for rec in _combined(symbols, footprints):
            if rec.source != "external":
                continue
            kind = "symbol" if isinstance(rec, SymbolRecord) else "footprint"
            path = ws.abs(rec.library)
            names = session.names_in(path) if path is not None and path.is_file() else []
            present = names is not None and rec.name.casefold() in {n.casefold() for n in names}
            if not present and rec.status != "missing":
                message = f"Nicht mehr in der externen Bibliothek {rec.library} vorhanden."
                with session.bound():
                    _set_status(kind, rec.name, "missing", message)
                result["external_missing"].append({"kind": kind, "name": rec.name, "message": message})
            elif present and rec.status == "missing":
                with session.bound():
                    _set_status(kind, rec.name, "ok", None)
                result["updated"].append({"kind": kind, "name": rec.name, "status": "ok", "message": None})
        session.progress(1.0, scan_message(result))
    finally:
        session.finish()
    return result


def _rebaseline(session: _Session, files: Sequence[LibraryFileInfo], previous: Mapping[str, str] | None,
                result: dict[str, Any]) -> set[str]:
    """See :func:`scan_workspace` (``rebaseline``); returns the rels of the re-based files."""
    done: set[str] = set()
    for info in files:
        if not info.external_changes or info.unreadable or info.unregistered or info.missing or not info.exists:
            continue
        session.check_cancelled()
        path = Path(info.path)
        state = _file_state(path)
        current_manifest = _load_manifest(info.rel)
        if state is None or current_manifest is None:
            continue
        kind: Kind = "symbol" if info.kind == "schlib" else "footprint"
        ops = _ops_for(kind)
        before: _Manifest | None = None
        raw = (previous or {}).get(_manifest_key(info.rel))
        if raw:
            with contextlib.suppress(ValidationError, ValueError):
                candidate = _Manifest.model_validate_json(raw)
                before = candidate if candidate.matches(path) else None
        names, _problem = session.list_names(path)
        components: dict[str, str | None] = {}
        stale: list[str] = []
        records = _records_by_names(kind, names or [])
        for name in names or []:
            key = name.casefold()
            if key not in current_manifest.components and (before is None or key not in before.components):
                continue  # never PartForge's own
            known = before.components.get(key) if before is not None else None
            rec = records.get(key)
            wanted = ops.fingerprint(rec.spec) if rec is not None and rec.spec is not None else None
            if known is not None and wanted == known:
                components[key] = known  # the file holds exactly the restored registry spec
            else:
                components[key] = None
                if before is not None and rec is not None and rec.spec is not None and rec.status == "ok" \
                        and rec.source in _OWN_SOURCES:
                    stale.append(rec.name)
        with session.bound():
            _store_manifest(info.rel, _Manifest(rel=info.rel, size=state[0], mtime_ns=state[1], sha256=state[2],
                                                components=components))
            for name in stale:
                message = "Nach dem Wiederherstellen der Datenbank neu zu schreiben (die Datei hat einen anderen Stand)."
                _set_status(kind, name, "pending", message)
                result["updated"].append({"kind": kind, "name": name, "status": "pending", "message": message})
        done.add(info.rel)
        result["rebaselined"].append(info.rel)
        session.log(f"{info.rel}: Bibliotheksstand übernommen – die Datei gilt wieder als von PartForge geschrieben"
                    + (f"; {plural(len(stale), 'Bauteil wird', 'Bauteile werden')} neu geschrieben." if stale else "."))
    return done


def scan_message(result: Mapping[str, Any]) -> str:
    """Outcome of "Bibliotheken prüfen" as one German sentence (job message)."""
    files = plural(int(result.get("files") or 0), "Datei", "Dateien")
    parts: list[str] = []
    unreadable = len(result.get("unreadable") or [])
    if unreadable:
        parts.append(plural(unreadable, "Datei nicht lesbar (beschädigt?)", "Dateien nicht lesbar (beschädigt?)"))
    updated = len(result.get("updated") or [])
    if updated:
        parts.append(plural(updated, "Eintrag aktualisiert", "Einträge aktualisiert"))
    registered = len(result.get("registered") or [])
    unknown = len(result.get("unregistered") or [])
    if registered:
        parts.append(plural(registered, "Bauteil übernommen", "Bauteile übernommen"))
    elif unknown:
        parts.append(plural(unknown, "unbekanntes Bauteil", "unbekannte Bauteile"))
    conflicts = len(result.get("conflicts") or [])
    if conflicts:
        parts.append(plural(conflicts, "Namenskonflikt", "Namenskonflikte"))
    gone = len(result.get("external_missing") or [])
    if gone:
        parts.append(plural(gone, "externes Bauteil fehlt", "externe Bauteile fehlen"))
    outside = len(result.get("changed_outside") or [])
    if outside:
        parts.append(plural(outside, "Datei außerhalb geändert", "Dateien außerhalb geändert"))
    if not parts:
        return f"Bibliotheken geprüft: {files}, alles stimmt mit der Registrierung überein."
    return f"Bibliotheken geprüft: {files} – " + ", ".join(parts) + "."


def _register_imported(
    session: _Session, library: Path, names: Sequence[str], *, extract_step: bool = True, quiet: bool = False
) -> list[dict[str, str]]:
    """Register components found in a workspace library as ``imported`` (spec read back).

    The read-back notes (content the PartForge model cannot hold) go into the status
    message; such components are never regenerated from their spec (library manifest).
    ``extract_step``: embedded 3D models are extracted into ``3D\\`` (the library import leaves that optional –
    thousands of vendor models would be copied twice); ``quiet``: notes only in the status, not in the job log."""
    kind = library_file_kind(library)
    out: list[dict[str, str]] = []
    rel = session.rel(library)
    symbols: list[SymbolRecord] = []
    footprints: list[FootprintRecord] = []
    for name in names:
        notes: list[str] = []
        try:
            spec = _read_component(session.writer(), library, name, extract_step=extract_step, notes=notes)
        except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
            session.log(f"{name} aus {library.name} nicht lesbar: {exc}", "warn")
            spec = None
        message = _clip(_adoption_message(library, notes)) if notes else None
        if notes and not quiet:
            session.log(f"{name}: {message}", "warn")
        if kind == "schlib":
            sym = cast(SymbolSpec | None, spec)
            symbols.append(SymbolRecord(name=name, library=rel, source="imported", spec=sym,
                                        pin_count=len(sym.pins) if sym else 0, part_count=sym.part_count if sym else 1,
                                        status="ok", status_message=message))
        else:
            fp = cast(FootprintSpec | None, spec)
            footprints.append(FootprintRecord(name=name, library=rel, source="imported", spec=fp,
                                              family=(fp.family or None) if fp else None, pad_count=len(fp.pads) if fp else 0,
                                              height=fp.height if fp else None,
                                              step_file=fp.step.file if fp and fp.step else None, status="ok",
                                              status_message=message))
        out.append({"kind": "symbol" if kind == "schlib" else "footprint", "name": name, "library": rel})
    with session.bound():
        if symbols:
            registry.upsert_symbols(symbols)
        if footprints:
            registry.upsert_footprints(footprints)
    return out


# --------------------------------------------------------------------------- editor hints


def component_warnings(rec: Record, *, writer: LibraryWriter | None = None) -> list[str]:
    """German hints for the editor of a registered component: its library was changed
    outside PartForge, and what saving it from PartForge would lose (read-back of a
    component PartForge did not write itself – unmapped layers, decorations, …)."""
    if rec.source == "external" or not rec.library:
        return []
    ws = current()
    path = ws.abs(rec.library)
    if path is None or not path.is_file() or not is_inside(path, ws.root):
        return []
    rel = ws.rel(path)
    manifest = _load_manifest(rel)
    state_ok = manifest is not None and manifest.matches(path)
    out: list[str] = []
    if manifest is not None and not state_ok:
        out.append(
            f"{path.name} wurde außerhalb von PartForge geändert – die hier gezeigte Fassung kann von der Datei abweichen. "
            "Speichern ersetzt das Bauteil in der Datei (die vorherige Fassung bleibt in Backups\\lib)."
        )
    if state_ok and manifest is not None and manifest.components.get(rec.name.casefold()) is not None:
        return out  # PartForge wrote exactly this component
    session = _Session(ws, None, writer)
    try:
        active = session.writer()
        reader = active.ops if isinstance(active, RustLibraryWriter) else getattr(active, "reader", None)
        if not isinstance(reader, RustLibraryOps):
            return out
        notes: list[str] = []
        if isinstance(rec, SymbolRecord):
            found: Any = reader.read_symbol(path, rec.name, notes=notes)
        else:
            found = reader.read_footprint(path, rec.name, notes=notes, extract_step=False)
    except Exception as exc:  # noqa: BLE001 - only a hint: the detail view works without it
        log.info("Bauteil %s in %s nicht prüfbar: %s", rec.name, path, exc)
        return out
    if found is not None and notes:
        out.append("Beim Speichern aus PartForge ginge Inhalt aus der Bibliotheksdatei verloren: " + " ".join(notes[:5]))
    return out


# --------------------------------------------------------------------------- health

#: Check ids of :func:`library_health` replaced by the data-level ids of the same meaning (the old
#: ids stay available as ``LibraryHealthIssue.aliases`` for now).
HEALTH_CHECK_ALIASES: Final[dict[str, str]] = {
    "symbol_error": "registry_error",
    "footprint_error": "registry_error",
    "symbol_missing": "registry_missing",
    "footprint_missing": "registry_missing",
}
#: Part numbers listed per finding (``LibraryHealthIssue.part_numbers``).
HEALTH_PART_NUMBERS: Final = 20
#: Footprint whose PcbLib stores the height 0 although the spec has one.
HEIGHT_CHECK: Final = "footprint_height_missing"
#: ``LibraryHealthIssue.fix_action`` of :data:`HEIGHT_CHECK` – ``POST /api/libraries/footprint-heights/repair``.
REPAIR_HEIGHTS_ACTION: Final = "repair_footprint_heights"
#: A SchLib/PcbLib that exists but cannot be read (damaged) – error per file.
UNREADABLE_CHECK: Final = "library_unreadable"
#: ``LibraryHealthIssue.fix_action`` of :data:`UNREADABLE_CHECK` when a readable backup exists –
#: ``POST /api/libraries/restore-backup`` with ``{"library": <LibraryHealthIssue.library>}``.
RESTORE_BACKUP_ACTION: Final = "restore_library_backup"
_SEVERITY_ORDER: Final[dict[str, int]] = {"error": 0, "warning": 1, "info": 2}
#: Footprint sources whose spec PartForge wrote itself (an imported read-back is never rewritten for a height).
_OWN_SOURCES: Final = frozenset({"generated", "datasheet"})
#: A cached file-level report is computed again at the latest after this many seconds.
HEALTH_CACHE_TTL_S: Final = 600.0


class LibraryHealthIssue(HealthIssue):
    """A finding of the file-level check (``GET /api/libraries/health``).

    ``affected_parts`` / ``part_numbers``: the parts the finding concerns – a finding about one
    part: 1 and its part number; a finding about a component, a library file or a symbol/
    footprint pair: every part that uses it (part numbers sorted, at most
    :data:`HEALTH_PART_NUMBERS`)."""

    kind: Literal["symbol", "footprint"] | None = Field(default=None, description="Symbol oder Footprint")
    component: str | None = Field(default=None, description="Name des Symbols/Footprints (Library Ref/Footprint Ref)")
    library: str | None = Field(default=None, description="Bibliotheksdatei (relativ zum Bibliotheksordner)")
    affected_parts: int = Field(default=0, description="Anzahl der betroffenen Bauteile")
    part_numbers: list[str] = Field(
        default_factory=list, description="Teilenummern der betroffenen Bauteile (sortiert, höchstens 20)"
    )
    aliases: list[str] = Field(default_factory=list, description="Frühere Kennungen dieser Prüfung (Übergang)")
    fix_action: str | None = Field(
        default=None,
        description="Ein-Klick-Korrektur des Backends: repair_footprint_heights = POST /api/libraries/footprint-heights/"
                    "repair, restore_library_backup = POST /api/libraries/restore-backup {library}",
    )


@dataclass
class _Finding:
    issue: LibraryHealthIssue
    parts: set[str]  # every affected part number (the issue lists the first ones)


#: One link of a part: ``(ref column, path column, kind, ref, stored path)`` (ref/path stripped).
_Link = tuple[str, str, Kind, str, str]


@dataclass
class _PartRefs:
    """Which parts use which symbol/footprint name and which library file (one pass over the parts)."""

    symbols: dict[str, set[str]] = field(default_factory=dict)  # casefolded Library Ref -> part numbers
    footprints: dict[str, set[str]] = field(default_factory=dict)  # casefolded Footprint Ref (n) -> part numbers
    files: dict[str, set[str]] = field(default_factory=dict)  # _rel_key(stored path) -> part numbers
    spelling: dict[str, str] = field(default_factory=dict)  # _rel_key(stored path) -> first stored spelling

    def add_links(self, pn: str, links: Sequence[_Link]) -> None:
        if not pn:
            return
        for _ref_col, _path_col, kind, ref, stored in links:
            if ref:
                (self.symbols if kind == "symbol" else self.footprints).setdefault(ref.casefold(), set()).add(pn)
            if stored:
                key = _rel_key(stored)
                self.files.setdefault(key, set()).add(pn)
                self.spelling.setdefault(key, stored)

    def of(self, kind: Kind, name: str) -> set[str]:
        return set((self.symbols if kind == "symbol" else self.footprints).get(name.casefold(), ()))


def _pn_sort(pns: Iterable[str]) -> list[str]:
    return sorted(pns, key=_natural)


@dataclass(frozen=True)
class HeightProblem:
    """A footprint whose PcbLib stores the height 0 although its spec has one."""

    name: str
    rel: str  # library file, workspace-relative
    height: float  # mm, from the spec (heights.footprint_height)
    repairable: bool  # False: the library was changed outside PartForge since its last write


def _storable_height(height: float | None) -> bool:
    try:
        return height is not None and heights.mm_to_coord(height) > 0
    except heights.HeightError:  # not storable (e.g. > 5 m): the writer cannot set it either
        return False


def _lean_height_candidates(footprints: Mapping[str, _Reg] | None = None) -> list[tuple[str, str, float]]:
    """``(name, library, height in mm)`` of PartForge's own footprints (``generated``/``datasheet``, ``ok``, with
    geometry) with a storable height – read from the stored spec text without building pydantic models."""
    regs = footprints if footprints is not None else _registry_rows("footprint")
    own = [r for r in regs.values()
           if r.source in _OWN_SOURCES and r.status == "ok" and r.has_spec and library_file_kind(r.library) == "pcblib"]
    docs = _spec_documents("footprint", [r.name for r in own])
    out: list[tuple[str, str, float]] = []
    for rec in own:
        doc = docs.get(rec.name.casefold())
        if doc is None:
            continue
        bodies = [b for b in doc.get("bodies") or [] if isinstance(b, dict)]
        want = heights.height_of(doc.get("height"), [b.get("z_top") for b in bodies])
        if _storable_height(want):
            out.append((rec.name, rec.library, cast(float, want)))
    return out


def _height_problems(ws: Workspace, candidates: Iterable[tuple[str, str, float]]) -> list[HeightProblem]:
    """Height problems of the candidate footprints (each existing workspace PcbLib is read once)."""
    by_file: dict[str, tuple[Path, list[tuple[str, float]]]] = {}
    for name, library, want in candidates:
        path = ws.abs(library)
        if path is None or library_file_kind(path) != "pcblib" or not is_inside(path, ws.root) or not path.is_file():
            continue
        by_file.setdefault(os.path.normcase(str(path)), (Path(path), []))[1].append((name, want))
    out: list[HeightProblem] = []
    for path, items in by_file.values():
        try:
            stored = {name.casefold(): mm for name, mm in heights.read_footprint_heights(path).items()}
        except heights.HeightError as exc:
            log.info("Bauhöhen von %s nicht prüfbar: %s", path, exc)
            continue
        rel = ws.rel(path)
        manifest = _load_manifest(rel)
        repairable = manifest is None or manifest.matches(path)
        for name, want in items:
            have = stored.get(name.casefold())
            if have is not None and heights.mm_to_coord(have) == 0:
                out.append(HeightProblem(name=name, rel=rel, height=want, repairable=repairable))
    return sorted(out, key=lambda p: (_rel_key(p.rel), _natural(p.name)))


def footprint_height_problems(
    records: Iterable[FootprintRecord] | None = None, *, ws: Workspace | None = None
) -> list[HeightProblem]:
    """Footprints whose PcbLib says height 0 although the spec has a height (libraries written
    before the PcbLib height patch, see :mod:`partforge.altium.heights`).

    Checked: PartForge's own footprints (``generated``/``datasheet``, status ``ok``, with
    geometry) in an existing workspace PcbLib; files whose heights cannot be read are skipped.
    ``repairable`` is False where the library was changed outside PartForge since its last
    write (rewriting the footprint from the registry could lose those changes). Without
    ``records`` the registry is read lean (spec text, no models)."""
    if not heights.height_patch_enabled():
        return []
    ws = ws or current()
    if records is None:
        return _height_problems(ws, _lean_height_candidates())
    candidates: list[tuple[str, str, float]] = []
    for rec in records:
        if rec.source not in _OWN_SOURCES or rec.status != "ok" or rec.spec is None or not rec.library:
            continue
        want = heights.footprint_height(rec.spec)
        if _storable_height(want):
            candidates.append((rec.name, rec.library, cast(float, want)))
    return _height_problems(ws, candidates)


def _mm(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


# -- lean reads: only the columns the checks need (no specs as pydantic objects, no sorting) -----------------


@dataclass(frozen=True)
class _Reg:
    """A registry entry without its geometry (``has_spec``: a spec is stored)."""

    kind: Kind
    name: str
    library: str
    source: str
    status: RecordStatus
    status_message: str | None
    has_spec: bool
    symbol_kind: str | None = None  # pf_symbols.kind


def _registry_rows(kind: Kind) -> dict[str, _Reg]:
    """``{casefolded name: _Reg}`` of every registered symbol or footprint (spec text not read)."""
    from sqlalchemy import select

    from ..db.schema import pf_footprints, pf_symbols

    table = pf_symbols if kind == "symbol" else pf_footprints
    columns = [table.c.name, table.c.library, table.c.source, table.c.status, table.c.status_message,
               table.c.spec.is_not(None).label("has_spec")]
    if kind == "symbol":
        columns.append(table.c.kind)
    with db_core.read() as conn:
        rows = conn.execute(select(*columns)).all()
    out: dict[str, _Reg] = {}
    for row in rows:
        status = row[3] if row[3] in ("ok", "pending", "missing", "error") else "pending"
        rec = _Reg(kind=kind, name=str(row[0]), library=str(row[1] or ""), source=str(row[2] or "generated"),
                   status=cast(RecordStatus, status), status_message=row[4], has_spec=bool(row[5]),
                   symbol_kind=(str(row[6]) if kind == "symbol" and row[6] else None))
        out.setdefault(rec.name.casefold(), rec)
    return out


def _spec_documents(kind: Kind, names: Iterable[str], *, where: Any = None) -> dict[str, dict[str, Any]]:
    """``{casefolded name: spec as JSON dict}`` of the given stored names (``json``, not pydantic – the checks
    read a few keys of possibly large specs). ``where``: extra SQL condition instead of ``names``."""
    from sqlalchemy import select

    from ..db.schema import pf_footprints, pf_symbols

    table = pf_symbols if kind == "symbol" else pf_footprints
    wanted = list(dict.fromkeys(names))
    statements = []
    if where is not None:
        statements.append(select(table.c.name, table.c.spec).where(table.c.spec.is_not(None), where))
    for start in range(0, len(wanted), 500):
        chunk = wanted[start:start + 500]
        statements.append(select(table.c.name, table.c.spec).where(table.c.name.in_(chunk), table.c.spec.is_not(None)))
    out: dict[str, dict[str, Any]] = {}
    with db_core.read() as conn:
        for stmt in statements:
            for name, raw in conn.execute(stmt):
                try:
                    data = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                if isinstance(data, dict):
                    out[str(name).casefold()] = data
    return out


def _link_columns(columns: Sequence[str]) -> list[tuple[str, str, Kind]]:
    """``(ref column, path column, kind)`` of the symbol and every footprint link among ``columns``."""
    present = set(columns)
    out: list[tuple[str, str, Kind]] = []
    if "Library Ref" in present:
        out.append(("Library Ref", "Library Path", "symbol"))
    out += [(col, col.replace("Ref", "Path"), "footprint") for col in columns if _FOOTPRINT_REF_RE.match(col)]
    return out


def _iter_part_links() -> Iterator[tuple[str, str, list[_Link]]]:
    """``(table, part number, links)`` of every part – only the link columns are read (no sorting, no
    conversion of the other columns)."""
    from sqlalchemy import select

    from ..db import categories

    for cat in categories.list_categories(with_counts=False):
        table = categories.table_for(cat)
        columns = [c.name for c in table.columns]
        if "Part Number" not in columns:
            continue
        links = _link_columns(columns)
        if not links:
            continue
        wanted = ["Part Number", *dict.fromkeys(c for ref, path, _ in links for c in (ref, path) if c in columns)]
        index = {name: i for i, name in enumerate(wanted)}
        with db_core.read() as conn:
            rows = conn.execute(select(*[table.c[c] for c in wanted])).all()
        for row in rows:
            pn = str(row[0] or "")
            out: list[_Link] = []
            for ref_col, path_col, kind in links:
                ref = str(row[index[ref_col]] or "").strip()
                stored = str(row[index[path_col]] or "").strip() if path_col in index else ""
                out.append((ref_col, path_col, kind, ref, stored))
            yield cat.table, pn, out


class _Paths:
    """Memo of what the checks ask about a stored library path – each distinct path is resolved, tested
    and listed once (thousands of parts share a few dozen paths)."""

    def __init__(self, session: _Session):
        self.session = session
        self.ws = session.ws
        self._abs: dict[str, Path | None] = {}
        self._file: dict[str, bool] = {}
        self._names: dict[str, tuple[set[str] | None, str | None]] = {}
        self._rel: dict[str, str] = {}

    def abs(self, stored: str) -> Path | None:
        if stored not in self._abs:
            self._abs[stored] = self.ws.abs(stored)
        return self._abs[stored]

    def is_file(self, path: Path) -> bool:
        key = os.path.normcase(str(path))
        if key not in self._file:
            self._file[key] = path.is_file()
        return self._file[key]

    def names(self, path: Path) -> tuple[set[str] | None, str | None]:
        """``(casefolded component names, None)``, ``(None, German reason)`` if the file cannot be read, or
        ``(None, None)`` if it cannot be listed without a writer (or does not exist)."""
        key = os.path.normcase(str(path))
        if key not in self._names:
            if not self.is_file(path):
                self._names[key] = (None, None)
            else:
                names, problem = self.session.list_names(path)
                self._names[key] = ({n.casefold() for n in names} if names is not None else None, problem)
        return self._names[key]

    def rel(self, path: Path) -> str:
        key = os.path.normcase(str(path))
        if key not in self._rel:
            self._rel[key] = self.ws.rel(path)
        return self._rel[key]


def _readable_backup(session: _Session, library: Path) -> Path | None:
    """The newest backup of ``library`` in ``Backups\\lib`` that the Rust reader can list, else ``None``."""
    try:
        writer = session.writer()
    except WriterUnavailable:
        return None
    ops = writer.ops if isinstance(writer, RustLibraryWriter) else getattr(writer, "reader", None)
    if not isinstance(ops, RustLibraryOps):
        return None
    for backup in reversed(library_backups(library, library_backup_dir(session.ws, library))):
        if ops.backup_readable(backup, library):
            return backup
    return None


def library_health(*, writer: LibraryWriter | None = None, max_issues: int = 500, refresh: bool = False) -> dict[str, Any]:
    """File-level checks: registered components exist in their files, parts reference
    symbols/footprints that exist in the referenced file, pins match pads, libraries changed
    outside PartForge, unreadable library files, footprint heights written into the PcbLib.

    Returns ``{issues: [LibraryHealthIssue], counts, summary, checked_parts, truncated,
    affected_parts, affected_part_numbers}``: ``issues`` sorted by severity and check (at most
    ``max_issues``), ``counts`` (per severity) and ``summary`` (per check) over **all** findings,
    ``affected_parts``/``affected_part_numbers`` = every part with an error or warning of this
    check. Check ids: see ARCHITEKTUR.md §8.4 (the database-level checks – required fields,
    duplicates … – live in :mod:`partforge.db.health`).

    The findings are cached per library state (:func:`_health_state`: registry, parts, library files,
    manifests, settings, events of this process) – a repeated request is answered without a new check;
    ``refresh`` checks again in any case.
    """
    ws = current()
    if writer is not None:  # a writer of the caller (tests, tools): never cached
        findings, checked = _health_findings(ws, writer)
        return _health_report(findings, checked, max_issues)
    with _health_compute_lock:  # two pages asking at once: the second one gets the first one's report
        state = _health_state(ws)
        findings: list[_Finding] | None = None
        checked = 0
        if state is not None and not refresh:
            with _health_cache_lock:
                cached = _health_cache.get("report")
                if cached is not None and cached[0] == state and time.monotonic() - cached[1] < HEALTH_CACHE_TTL_S:
                    findings, checked = cached[2], cached[3]
        if findings is None:
            findings, checked = _health_findings(ws, None)
            if state is not None:
                with _health_cache_lock:
                    _health_cache["report"] = (state, time.monotonic(), findings, checked)
    return _health_report(findings, checked, max_issues)


def _health_report(findings: Sequence[_Finding], checked: int, max_issues: int) -> dict[str, Any]:
    counts = {s: sum(1 for f in findings if f.issue.severity == s) for s in ("error", "warning", "info")}
    summary: dict[str, int] = {}
    for finding in findings:
        summary[finding.issue.check] = summary.get(finding.issue.check, 0) + 1
    affected: set[str] = set()
    for finding in findings:
        if finding.issue.severity != "info":
            affected |= finding.parts
    return {
        "issues": [f.issue.model_copy(deep=True) for f in findings[: max(0, max_issues)]],
        "counts": counts,
        "summary": dict(sorted(summary.items())),
        "checked_parts": checked,
        "truncated": len(findings) > max_issues,
        "affected_parts": len(affected),
        "affected_part_numbers": _pn_sort(affected),
    }


def _health_findings(ws: Workspace, writer: LibraryWriter | None) -> tuple[list[_Finding], int]:
    """Every finding of the file-level check (sorted) and the number of checked parts."""
    session = _Session(ws, None, writer)
    paths = _Paths(session)
    findings: list[_Finding] = []
    manifests_checked: set[str] = set()
    unreadable_reported: set[str] = set()
    try:
        session.writer()
        no_writer: str | None = None
    except WriterUnavailable as exc:  # pending entries then never get their file
        no_writer = str(exc)

    def add(severity: Literal["error", "warning", "info"], check: str, message: str, *, fix: str | None = None,
            table: str | None = None, part: str | None = None, column: str | None = None,
            kind: Kind | None = None, component: str | None = None, library: str | None = None,
            parts: Iterable[str] = (), aliases: Sequence[str] = (), fix_action: str | None = None) -> None:
        affected = set(parts) | ({part} if part else set())
        issue = LibraryHealthIssue(
            severity=severity, check=check, table=table, part_number=part, column=column, message=message,
            fix_hint=fix, kind=kind, component=component, library=library, affected_parts=len(affected),
            part_numbers=_pn_sort(affected)[:HEALTH_PART_NUMBERS], aliases=list(aliases), fix_action=fix_action,
        )
        findings.append(_Finding(issue, affected))

    symbols = _registry_rows("symbol")
    footprints = _registry_rows("footprint")
    refs = _PartRefs()
    checked = 0
    pairs: dict[tuple[str, str], list[tuple[str, str]]] = {}
    part_findings: list[tuple[str, str, str, Kind, str, str, str, str, str]] = []
    for table, pn, links in _iter_part_links():
        checked += 1
        refs.add_links(pn, links)
        _check_part_links(paths, table, pn, links, symbols, footprints, part_findings, pairs)
    by_library: dict[str, list[_Reg]] = {}
    for rec in [*symbols.values(), *footprints.values()]:
        if rec.library:
            by_library.setdefault(_rel_key(rec.library), []).append(rec)

    def users_of_file(rel: str) -> set[str]:
        users = set(refs.files.get(_rel_key(rel), ()))
        for rec in by_library.get(_rel_key(rel), ()):
            users |= refs.of(rec.kind, rec.name)
        return users

    def report_unreadable(path: Path, problem: str) -> None:
        rel = paths.rel(path)
        if _rel_key(rel) in unreadable_reported:
            return
        unreadable_reported.add(_rel_key(rel))
        registered = len(by_library.get(_rel_key(rel), ()))
        inside = is_inside(path, ws.root)
        backup = _readable_backup(session, path) if inside else None
        schlib = library_file_kind(path) == "schlib"
        what = ""
        if registered:
            what = f" ({plural(registered, 'registriertes Symbol', 'registrierte Symbole')})" if schlib else (
                f" ({plural(registered, 'registrierter Footprint', 'registrierte Footprints')})")
        own = "Symbole" if schlib else "Footprints"
        if backup is not None:
            fix = (f"„Aus Sicherung wiederherstellen“ setzt die Datei auf die neueste lesbare Sicherung aus Backups\\lib "
                   f"zurück ({backup.name}) und schreibt die {own} von PartForge neu.")
        elif inside:
            fix = ("Keine lesbare Sicherung in Backups\\lib – die Datei in Altium prüfen oder entfernen; danach schreibt "
                   f"„Synchronisieren“ die {own} von PartForge neu.")
        else:
            fix = "Die Datei in Altium prüfen oder die externe Bibliothek ersetzen."
        add("error", UNREADABLE_CHECK,
            f"{rel} ist nicht lesbar – vermutlich beschädigt{what}: {problem.rstrip('. ')}. Altium und PartForge können "
            f"die {'Symbole' if schlib else 'Footprints'} darin nicht verwenden.",
            fix=fix, kind="symbol" if schlib else "footprint", library=rel,
            parts=users_of_file(rel), fix_action=RESTORE_BACKUP_ACTION if backup is not None else None)

    for table, pn, column, kind, ref, stored, check, message, fix in part_findings:
        severity: Literal["error", "warning"] = "warning" if check == "path_empty" else "error"
        add(severity, check, message, fix=fix, table=table, part=pn, column=column, kind=kind, component=ref,
            library=stored or None)

    def check_outside(path: Path) -> None:
        rel = paths.rel(path)
        if _rel_key(rel) in manifests_checked:
            return
        manifests_checked.add(_rel_key(rel))
        manifest = _load_manifest(rel)
        if manifest is not None and not manifest.matches(path):
            add("info", "library_changed_outside", f"{rel} wurde außerhalb von PartForge geändert (z. B. in Altium).",
                fix="„Bibliotheken prüfen“ ausführen; PartForge schreibt dort nur noch geänderte Bauteile.",
                library=rel, parts=users_of_file(rel))

    for records in (symbols, footprints):
        for rec in records.values():
            label = "Symbol" if rec.kind == "symbol" else "Footprint"
            users = refs.of(rec.kind, rec.name)
            where = {"kind": rec.kind, "component": rec.name, "library": rec.library or None, "parts": users}
            path = paths.abs(rec.library) if rec.library else None
            if path is None:
                add("warning", "library_unassigned", f"{label} „{rec.name}“ ist keiner Bibliotheksdatei zugeordnet.",
                    fix="„Synchronisieren“ schreibt es in die Standardbibliothek.", **where)
                continue
            if not paths.is_file(path):
                if rec.status != "pending":
                    add("error", "library_file_missing", f"{label} „{rec.name}“: Datei {rec.library} fehlt.",
                        fix="Pfad der externen Bibliothek prüfen." if rec.source == "external"
                        else "„Bibliotheken prüfen“ und danach „Synchronisieren“ ausführen.", **where)
                elif no_writer is not None and rec.source != "external":
                    add("error", "library_file_missing",
                        f"{label} „{rec.name}“: Datei {rec.library} fehlt – sie wurde noch nicht geschrieben, und kein "
                        f"{WRITER} steht zur Verfügung.", fix=no_writer, **where)
                continue
            present, problem = paths.names(path)
            if present is None and problem:
                report_unreadable(path, problem)  # (a damaged file is not also "changed outside")
            elif rec.source != "external" and is_inside(path, ws.root):
                check_outside(path)
            status_alias = [f"registry_{rec.status}", f"{rec.kind}_{rec.status}"] if rec.status in ("error", "missing") else []
            if present is not None and rec.name.casefold() not in present and rec.status != "pending":
                # one finding per cause (K1): the error; a registry status that explains it travels along
                message = f"{label} „{rec.name}“ fehlt in {rec.library}."
                fix = "„Bibliotheken prüfen“ und danach „Synchronisieren“ ausführen."
                if rec.status == "missing":
                    message += f" {rec.status_message}" if rec.status_message else " Es ist nicht erzeugbar."
                    fix = (f"Im {'Symbol' if rec.kind == 'symbol' else 'Footprint'}-Generator anlegen oder aus einer "
                           "Bibliothek übernehmen.")
                elif rec.status == "error":
                    message += f" Letzter Schreibversuch: {rec.status_message or 'fehlgeschlagen'}"
                    fix = "Ursache beheben und „Synchronisieren“ ausführen."
                add("error", "component_missing", message, fix=fix, aliases=status_alias, **where)
            elif rec.status in ("error", "missing"):
                add("warning", f"registry_{rec.status}", f"{label} „{rec.name}“: {rec.status_message or rec.status}",
                    fix="Ursache beheben und „Synchronisieren“ ausführen.", aliases=status_alias[1:], **where)
    for path, problem in _unreadable_part_files(paths, refs):  # also files no registered component lives in
        report_unreadable(path, problem)
    height_problems = _height_problems(ws, _lean_height_candidates(footprints)) if heights.height_patch_enabled() else []
    for problem in height_problems:
        fix = (
            "„Footprint-Höhen nachtragen“ schreibt die betroffenen Footprints neu – mit ihrer Höhe."
            if problem.repairable
            else f"{problem.rel} wurde außerhalb von PartForge geändert – die Höhe bitte in Altium eintragen "
            "(Footprint-Eigenschaften, Height) oder die Datei erst wieder von PartForge schreiben lassen."
        )
        add("warning", HEIGHT_CHECK,
            f"Footprint-Höhe fehlt in der PcbLib: „{problem.name}“ hat in {problem.rel} die Höhe 0 statt "
            f"{_mm(problem.height)} mm.",
            fix=fix, kind="footprint", component=problem.name, library=problem.rel,
            parts=refs.of("footprint", problem.name), fix_action=REPAIR_HEIGHTS_ACTION if problem.repairable else None)
    _check_pairs(symbols, footprints, pairs, add)
    session.finish()
    findings.sort(key=lambda f: (_SEVERITY_ORDER[f.issue.severity], f.issue.check, _natural(f.issue.component or ""),
                                 f.issue.table or "", _natural(f.issue.part_number or "")))
    return findings, checked


def _unreadable_part_files(paths: _Paths, refs: _PartRefs) -> list[tuple[Path, str]]:
    """Library files that parts reference and that exist but cannot be read (also unregistered ones)."""
    out: list[tuple[Path, str]] = []
    for stored in refs.spelling.values():
        path = paths.abs(stored)
        if path is None or not paths.is_file(path) or library_file_kind(path) is None:
            continue
        names, problem = paths.names(path)
        if names is None and problem:
            out.append((path, problem))
    return out


def _check_pairs(symbols: Mapping[str, _Reg], footprints: Mapping[str, _Reg],
                 pairs: Mapping[tuple[str, str], list[tuple[str, str]]], add: Callable[..., None]) -> None:
    """``pin_pad_mismatch`` per symbol/footprint pair the parts use – the rule of the datasheet proposal
    (:func:`partforge.geometry.model.pin_pad_check`): NC pads recorded with the symbol, ``x`` pads of a
    letter-code pin map and unused pads of amplifiers/oscillators are no mismatch; an exposed pad without pin
    is a hint (``info``)."""
    from ..geometry.model import pin_pad_gaps
    from ..symbols.mapping import free_pads, unused_pads_ok

    usable = {(s, f): users for (s, f), users in pairs.items()
              if s in symbols and f in footprints and symbols[s].has_spec and footprints[f].has_spec}
    if not usable:
        return
    sym_docs = _spec_documents("symbol", {symbols[s].name for s, _ in usable})
    fp_docs = _spec_documents("footprint", {footprints[f].name for _, f in usable})
    for (sym_key, fp_key), users in usable.items():
        sym, fp = symbols[sym_key], footprints[fp_key]
        sym_doc, fp_doc = sym_docs.get(sym_key), fp_docs.get(fp_key)
        if sym_doc is None or fp_doc is None:
            continue
        pins = {str(p.get("designator")) for p in sym_doc.get("pins") or [] if isinstance(p, dict)}
        pads = [p for p in fp_doc.get("pads") or [] if isinstance(p, dict) and p.get("designator")]
        generator = sym_doc.get("generator") if isinstance(sym_doc.get("generator"), dict) else {}
        problems, hints = pin_pad_gaps(
            pins, {str(p["designator"]) for p in pads}, {str(p["designator"]) for p in pads if p.get("thermal")},
            free_pads=free_pads(generator), unused_ok=unused_pads_ok(generator, sym.symbol_kind),
        )
        if not problems and not hints:
            continue
        table, pn = min(users, key=lambda u: (_natural(u[1]), u[0]))
        more = f" (und {plural(len(users) - 1, 'weiteres Bauteil', 'weitere Bauteile')})" if len(users) > 1 else ""
        add("warning" if problems else "info", "pin_pad_mismatch",
            f"Symbol „{sym.name}“ / Footprint „{fp.name}“: {' '.join(problems or hints)}{more}",
            table=table, part=pn, column="Footprint Ref", kind="footprint", component=fp.name,
            library=fp.library or None, parts=[p for _, p in users],
            fix="Pinbelegung von Symbol und Footprint angleichen oder einen passenden Footprint wählen." if problems
            else "Das Exposed Pad auf der Leiterplatte laut Datenblatt anschließen (z. B. an GND).")


_FOOTPRINT_REF_RE = re.compile(r"^Footprint Ref( \d+)?$")


def _check_part_links(
    paths: _Paths,
    table: str,
    pn: str,
    links: Sequence[_Link],
    symbols: Mapping[str, _Reg],
    footprints: Mapping[str, _Reg],
    out: list[tuple[str, str, str, Kind, str, str, str, str, str]],
    pairs: dict[tuple[str, str], list[tuple[str, str]]],
) -> None:
    """Part-level checks of one part (``path_empty``, ``library_file_missing``, ``component_not_in_file``):
    appends ``(table, pn, column, kind, ref, stored, check, message, fix)``."""
    sym_ref = next((ref for _rc, _pc, kind, ref, _s in links if kind == "symbol"), "")
    for _ref_col, path_col, kind, ref, stored in links:
        if not ref:
            continue
        if kind == "footprint" and sym_ref:  # pin/pad check, independent of the paths
            pairs.setdefault((sym_ref.casefold(), ref.casefold()), []).append((table, pn))
        rec = (symbols if kind == "symbol" else footprints).get(ref.casefold())
        label = "Symbol" if kind == "symbol" else "Footprint"
        if not stored:
            if rec is None:
                continue  # db health reports unregistered references
            out.append((table, pn, path_col, kind, ref, stored, "path_empty",
                        f"{label} „{ref}“: {path_col} ist leer (Altium findet es dann nicht).",
                        "„Synchronisieren“ trägt den Pfad ein."))
            continue
        path = paths.abs(stored)
        if path is None:
            continue
        if rec is not None and rec.status == "pending" and _rel_key(rec.library) == _rel_key(stored):
            continue  # the next sync creates it there
        if not paths.is_file(path):
            out.append((table, pn, path_col, kind, ref, stored, "library_file_missing",
                        f"{label} „{ref}“: Bibliothek {stored} existiert nicht.",
                        "Pfad korrigieren oder „Synchronisieren“ ausführen."))
            continue
        present, _problem = paths.names(path)
        if present is not None and ref.casefold() not in present:
            hint = "Pfad korrigieren oder „Synchronisieren“ ausführen."
            if rec is not None and rec.library and _rel_key(rec.library) != _rel_key(stored):
                hint = f"{label} liegt in {rec.library} – Pfad anpassen („Synchronisieren“ auf der Altium-Seite gleicht ihn an)."
            out.append((table, pn, path_col, kind, ref, stored, "component_not_in_file",
                        f"{label} „{ref}“ ist nicht in {stored} enthalten.", hint))


# -- cache key of the report -----------------------------------------------------------------------------

_health_cache_lock = threading.Lock()
_health_compute_lock = threading.Lock()
_health_cache: dict[str, tuple[Any, float, list[_Finding], int]] = {}
_health_epoch = itertools.count()
_health_epoch_value = 0
_HEALTH_EVENTS: Final = (events.PARTS_CHANGED, events.SCHEMA_CHANGED, events.LIBRARIES_WRITTEN,
                         events.WORKSPACE_OPENED, events.WORKSPACE_CLOSED)


def _bump_health_epoch(*_args: Any, **_kwargs: Any) -> None:
    global _health_epoch_value
    _health_epoch_value = next(_health_epoch)


def invalidate_health_cache() -> None:
    """Forget the cached file-level report (the next :func:`library_health` checks again)."""
    with _health_cache_lock:
        _health_cache.clear()
    _bump_health_epoch()


def _health_state(ws: Workspace) -> tuple[Any, ...] | None:
    """Everything the file-level report depends on, cheaply (no spec parsing, no library listing):
    events of this process, a checksum of the registry rows (spec text included), count and newest
    modification of every category table (changes by other processes), the library files (size, mtime),
    the manifests, the writer and the switches. ``None`` = do not cache."""
    for event in _HEALTH_EVENTS:  # idempotent: survives events.clear() in tests
        events.subscribe(event, _bump_health_epoch)
    try:
        from sqlalchemy import func, select

        from ..db import categories
        from ..db.schema import pf_footprints, pf_symbols

        digest = 0
        with db_core.read() as conn:
            for table in (pf_symbols, pf_footprints):
                stmt = select(table.c.name, table.c.library, table.c.source, table.c.status, table.c.status_message,
                              table.c.updated, table.c.spec)
                for row in conn.execute(stmt):
                    digest = zlib.crc32(repr(tuple(row[:6])).encode("utf-8"), digest)
                    digest = zlib.crc32((row[6] or "").encode("utf-8"), digest)
            parts: list[tuple[str, int, str | None]] = []
            for cat in categories.list_categories(with_counts=False):
                table = categories.table_for(cat)
                cols = [table.c[c.name] for c in table.columns if c.name == "PF Modified"]
                stmt = select(func.count(), *[func.max(c) for c in cols]).select_from(table)
                row = conn.execute(stmt).one()
                parts.append((cat.table, int(row[0]), str(row[1]) if len(row) > 1 else None))
        files = []
        for path in workspace_library_files(ws):
            stat = _stat(path)
            files.append((os.path.normcase(str(path)), stat))
        manifests = db_meta.meta_items(_MANIFEST_PREFIX)
        external = _stat(_external_file(ws))
        settings = load_settings()
        try:
            get_writer(workspace=ws)
            writer_ok = True
        except WriterUnavailable:
            writer_ok = False
        return (
            os.path.normcase(str(ws.root)), id(db_core.get_state()), _health_epoch_value, digest, tuple(parts),
            tuple(files), zlib.crc32(json.dumps(manifests, sort_keys=True).encode("utf-8")), external,
            settings.resolved_rust_writer(), settings.altium.library_backend, heights.height_patch_enabled(), writer_ok,
        )
    except Exception as exc:  # noqa: BLE001 - without a key the report is simply computed again
        log.debug("Stand der Bibliotheksprüfung nicht ermittelbar: %s", exc)
        return None


# --------------------------------------------------------------------------- restore a damaged library


def _workspace_library(ws: Workspace, library: str) -> Path:
    """An existing SchLib/PcbLib of the workspace (``Symbols\…`` / ``Footprints\…``) by its stored path."""
    path = ws.abs(str(library or "").strip())
    if path is None or library_file_kind(path) is None:
        raise SyncError(f"„{library}“ ist keine Altium-Bibliothek (.SchLib oder .PcbLib).")
    path = Path(os.path.abspath(path))
    known = {os.path.normcase(str(p)) for p in workspace_library_files(ws)}
    if os.path.normcase(str(path)) not in known:
        raise SyncError(f"„{library}“ ist keine Bibliotheksdatei dieser Bibliothek.", status=404)
    return path


def restore_library_backup(library: str, *, ctx: JobContext | None = None, writer: LibraryWriter | None = None
                           ) -> dict[str, Any]:
    """Replace a damaged (unreadable) workspace library by its newest readable backup from ``Backups/lib``
    (finding ``library_unreadable``, fix action ``restore_library_backup``).

    The damaged file is kept as ``Backups/lib/<lib>.<stamp>.defekt``. The manifest is re-based on the restored
    file (PartForge's components in it stay its own, their content counts as unknown); every registered component
    of the file is then written again from the registry where it is missing from the backup or PartForge generated
    it (the backup may be older than the registry) – imported components found in the backup stay as they are.
    Returns ``{library, backup, damaged, components, rewritten, errors, message}``."""
    ws = current()
    session = _Session(ws, ctx, writer, watch=True)
    out: dict[str, Any] = {"library": None, "backup": None, "damaged": None, "components": 0, "rewritten": [],
                           "errors": [], "message": ""}
    try:
        session.ensure_current()
        path = _workspace_library(ws, library)
        rel = session.rel(path)
        out["library"] = rel
        session.progress(0.05, f"{path.name}: lesbare Sicherung wird gesucht …")
        with _library_held(path) as busy:
            if busy:
                raise SyncError(busy, status=409)
            forget_component_names(path)
            names, problem = session.list_names(path)
            if names is not None:
                raise SyncError(f"{rel} ist lesbar – es gibt nichts wiederherzustellen.", status=409)
            if problem is None:
                raise SyncError(f"Ob {rel} lesbar ist, lässt sich ohne Bibliotheks-Writer nicht prüfen.", status=503)
            backup = _readable_backup(session, path)
            if backup is None:
                raise SyncError(f"Für {rel} gibt es in Backups\\lib keine lesbare Sicherung.", status=404)
            refusal = session.altium.refusal(path)
            if refusal:
                raise SyncError(f"{path.name}: {refusal}.", status=409)
            folder = ws.backups_dir / "lib"
            folder.mkdir(parents=True, exist_ok=True)
            damaged = folder / f"{path.name}.{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.defekt"
            work = path.with_name(f"{path.stem}.pfwork{hashlib.sha1(os.urandom(8)).hexdigest()[:8]}{path.suffix}")
            try:
                shutil.copyfile(path, damaged)
                shutil.copyfile(backup, work)
                os.replace(work, path)
            except OSError as exc:
                with contextlib.suppress(OSError):
                    work.unlink()
                raise SyncError(file_access_message(path, exc, action="wiederhergestellt"), status=409) from exc
            forget_component_names(path)
            out["backup"], out["damaged"] = backup.name, damaged.name
            restored = session.names_in(path) or []
            out["components"] = len(restored)
            present = {n.casefold() for n in restored}
            previous = _load_manifest(rel)
            state = _file_state(path)
            kind: Kind = "symbol" if library_file_kind(path) == "schlib" else "footprint"
            ops = _ops_for(kind)
            records: dict[str, Any] = {}
            _load_library_records(ops, records, rel)
            todo = [r for r in records.values() if r.source != "external" and r.spec is not None
                    and (r.name.casefold() not in present or r.source in _OWN_SOURCES)]
            with session.bound():
                if state is not None:
                    owned = {n.casefold(): None for n in restored
                             if (previous is not None and n.casefold() in previous.components) or n.casefold() in records}
                    _store_manifest(rel, _Manifest(rel=rel, size=state[0], mtime_ns=state[1], sha256=state[2],
                                                   components=owned))
                for rec in todo:
                    _set_status(kind, rec.name, "pending", "Aus der Sicherung wiederhergestellt – wird neu geschrieben.")
            session.written.append(str(path))
            session.log(f"{rel} aus der Sicherung {backup.name} wiederhergestellt ({plural(len(restored), 'Bauteil', 'Bauteile')}); "
                        f"die beschädigte Datei liegt unter Backups\\lib\\{damaged.name}.", "success")
            if todo:
                session.progress(0.4, f"{plural(len(todo), 'Bauteil wird', 'Bauteile werden')} neu geschrieben …")
                result = _ensure(session, ops, [r.spec for r in todo], sources={r.name.casefold(): r.source for r in todo},
                                 conflicts="record", progress=(0.4, 0.95), force=True)
                for rec in result.records:
                    (out["rewritten"] if rec.status == "ok" else out["errors"]).append(
                        rec.name if rec.status == "ok" else {"name": rec.name, "message": rec.status_message})
        out["message"] = _restore_message(out)
        session.progress(1.0, out["message"])
    finally:
        session.finish()
    return out


def _restore_message(out: Mapping[str, Any]) -> str:
    text = f"{out['library']} aus der Sicherung wiederhergestellt ({plural(int(out['components']), 'Bauteil', 'Bauteile')})"
    rewritten, errors = len(out.get("rewritten") or []), len(out.get("errors") or [])
    if rewritten:
        text += f", {plural(rewritten, 'Bauteil', 'Bauteile')} neu geschrieben"
    if errors:
        text += f", {errors} mit {'Fehler' if errors == 1 else 'Fehlern'} (bleiben vorgemerkt)"
    return text + "."


# --------------------------------------------------------------------------- footprint heights


def _heights_message(out: Mapping[str, Any]) -> str:
    rewritten = len(out.get("rewritten") or [])
    libraries = len(out.get("libraries") or [])
    skipped = len(out.get("skipped") or [])
    errors = len(out.get("errors") or [])
    remaining = len(out.get("remaining") or [])
    if not out.get("checked"):
        return "Alle Footprint-Höhen sind in den PcbLibs eingetragen – nichts zu tun."
    parts: list[str] = []
    if rewritten:
        where = f" in {plural(libraries, 'Bibliothek', 'Bibliotheken')}" if libraries else ""
        parts.append(f"Footprint-Höhen nachgetragen: {plural(rewritten, 'Footprint', 'Footprints')}{where}")
    else:
        parts.append("Keine Footprint-Höhe nachgetragen")
    if skipped:
        parts.append(f"{skipped} übersprungen (Bibliothek außerhalb von PartForge geändert)")
    if errors:
        parts.append(f"{errors} mit {'Fehler' if errors == 1 else 'Fehlern'}")
    if remaining:
        parts.append(f"bei {plural(remaining, 'Footprint', 'Footprints')} fehlt die Höhe weiterhin")
    return ", ".join(parts) + "."


def repair_footprint_heights(
    names: Sequence[str] | None = None, *, ctx: JobContext | None = None, writer: LibraryWriter | None = None
) -> dict[str, Any]:
    """Give footprints their height in the PcbLib (health finding ``footprint_height_missing``).

    The affected footprints (:func:`footprint_height_problems`, optionally only ``names``) are
    written again through the normal sync path – forced although their spec is unchanged; the
    library writer sets each footprint's height from its spec (Rust writer: the height patch of
    :mod:`partforge.altium.heights`). Libraries changed outside PartForge since its last write
    are skipped (``skipped``) – a rewrite could lose those changes. Returns ``{checked,
    rewritten, skipped: [{name, library, message}], errors: [{name, message}], remaining,
    libraries, message}``.
    """
    ws = current()
    session = _Session(ws, ctx, writer, watch=True)
    out: dict[str, Any] = {"checked": 0, "rewritten": [], "skipped": [], "errors": [], "remaining": [],
                           "libraries": [], "message": ""}
    try:
        session.ensure_current()
        session.progress(0.02, "Footprint-Höhen werden geprüft …")
        problems = footprint_height_problems(ws=ws)  # lean: spec texts of PartForge's own footprints only
        if names is not None:
            wanted = {n.casefold() for n in names}
            problems = [p for p in problems if p.name.casefold() in wanted]
        out["checked"] = len(problems)
        for problem in problems:
            if not problem.repairable:
                message = (f"{problem.rel} wurde außerhalb von PartForge geändert – „{problem.name}“ wird nicht neu "
                           "geschrieben. Die Höhe bitte in Altium eintragen.")
                out["skipped"].append({"name": problem.name, "library": problem.rel, "message": message})
                session.log(message, "warn")
        todo = [p for p in problems if p.repairable]
        records = _records_by_names("footprint", [p.name for p in todo])
        todo = [p for p in todo if p.name.casefold() in records and records[p.name.casefold()].spec is not None]
        if todo:
            specs = [records[p.name.casefold()].spec for p in todo]
            sources = {p.name.casefold(): records[p.name.casefold()].source for p in todo}
            result = _ensure(session, FOOTPRINTS, specs, sources=sources, force=True, progress=(0.05, 0.95))
            for rec in result.records:
                if rec.status == "ok":
                    out["rewritten"].append(rec.name)
                else:
                    out["errors"].append({"name": rec.name, "message": rec.status_message})
            out["libraries"] = list(dict.fromkeys(session.written))
            fresh = _records_by_names("footprint", [p.name for p in todo])
            again = [fresh[p.name.casefold()] for p in todo if p.name.casefold() in fresh]
            out["remaining"] = [p.name for p in footprint_height_problems(again, ws=ws)]
        out["message"] = _heights_message(out)
        session.log(out["message"], "warn" if out["errors"] or out["remaining"] else "success")
        session.progress(1.0, out["message"])
    finally:
        session.finish()
    return out


# --------------------------------------------------------------------------- layer stack


def apply_layer_stack(ctx: JobContext | None = None) -> dict:
    """Write the workspace layer stack into the header of every workspace PcbLib."""
    ws = current()
    session = _Session(ws, ctx, watch=True)
    out: dict[str, Any] = {"patched": [], "unchanged": [], "warnings": [], "skipped": []}
    try:
        session.ensure_current()
        base, notes = stackup.workspace_stack(ws)
        out["warnings"].extend(notes)
        stack = stackup.effective_stack(base, ws.settings.layers)
        if not stackup.header_patch_enabled():
            out["warnings"].append("Das Anpassen der Lagen-Köpfe ist abgeschaltet.")
            session.progress(1.0, "Das Anpassen der Lagen-Köpfe ist abgeschaltet – nichts geändert.")
            return out
        ops: RustLibraryOps | None = None
        try:
            writer = session.writer()
            if isinstance(writer, RustLibraryWriter):
                ops = writer.ops
        except WriterUnavailable:
            ops = None
        files = [p for p in workspace_library_files(ws) if library_file_kind(p) == "pcblib"]
        for index, path in enumerate(files):
            session.check_cancelled()
            session.progress(index / max(1, len(files)), path.name)
            if not stackup.pcblib_layer_problems(path, stack):
                out["unchanged"].append(str(path))
                continue
            rel = session.rel(path)
            with _library_held(path) as busy:
                if busy:
                    out["skipped"].append({"path": str(path), "message": busy})
                    continue
                refusal = session.altium.refusal(path)
                if refusal:
                    out["skipped"].append({"path": str(path), "message": refusal})
                    continue
                manifest = _load_manifest(rel)
                state_ok = manifest is not None and manifest.matches(path)
                names = session.names_in(path)
                verify = None
                if ops is not None:
                    expected = ops.list_components(path)

                    def verify(copy_path: Path, expected: list[str] = expected) -> None:
                        assert ops is not None
                        if ops.list_components(copy_path) != expected:
                            raise RustWriterError("Der Rust-Reader liest die angepasste Bibliothek nicht identisch.")

                warnings = stackup.patch_pcblib_layers(path, stack, verify=verify)
                forget_component_names(path)
                if not warnings and manifest is not None:
                    final = _final_manifest(rel, path, manifest, state_ok, names, {})
                    with session.bound():
                        _store_manifest(rel, final)
            if warnings:
                out["warnings"].extend(warnings)
                out["skipped"].append({"path": str(path), "message": warnings[0]})
            else:
                out["patched"].append(str(path))
                session.written.append(str(path))
                note = session.altium.reload(path)
                if note:
                    session.log(note)
        session.progress(1.0, layers_message(out))
    finally:
        session.finish()
    return out


def layers_message(out: Mapping[str, Any]) -> str:
    """Outcome of "Lagen der Footprint-Bibliotheken anpassen" (job message)."""
    patched, unchanged, skipped = (len(out.get(k) or []) for k in ("patched", "unchanged", "skipped"))
    if not patched and not skipped:
        if not unchanged:
            return "Keine Footprint-Bibliothek vorhanden – nichts anzupassen."
        return f"Lagen-Köpfe sind aktuell ({plural(unchanged, 'Footprint-Bibliothek', 'Footprint-Bibliotheken')})."
    text = f"Lagen-Kopf angepasst: {plural(patched, 'Footprint-Bibliothek', 'Footprint-Bibliotheken')}"
    extra = [f"{unchanged} unverändert"] if unchanged else []
    if skipped:
        extra.append(f"{skipped} übersprungen")
    return text + (f" ({', '.join(extra)})" if extra else "") + "."


# --------------------------------------------------------------------------- external libraries


class ExternalLibrary(BaseModel):
    """A SchLib/PcbLib outside PartForge's control, registered read-only."""

    id: str
    path: str  # absolute
    kind: Literal["schlib", "pcblib"]
    name: str
    added: str
    exists: bool = True
    registered: int = 0  # components registered from this library (source="external")


_external_lock = threading.RLock()


def _external_file(ws: Workspace) -> Path:
    return ws.root / EXTERNAL_FILE


def _external_id(path: str) -> str:
    return hashlib.sha1(os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:12]


def _load_external(ws: Workspace) -> list[ExternalLibrary]:
    file = _external_file(ws)
    if not file.is_file():
        return []
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("%s nicht lesbar: %s", file, exc)
        return []
    items = raw.get("libraries") if isinstance(raw, dict) else None
    out: list[ExternalLibrary] = []
    for item in items or []:
        try:
            out.append(ExternalLibrary.model_validate(item))
        except ValueError:
            continue
    return out


def _save_external(ws: Workspace, libraries: Sequence[ExternalLibrary]) -> None:
    file = _external_file(ws)
    data = {"version": 1, "libraries": [lib.model_dump(include={"id", "path", "kind", "name", "added"}) for lib in libraries]}
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, file)


def list_external_libraries() -> list[ExternalLibrary]:
    """Registered external libraries (``exists`` and ``registered`` filled)."""
    ws = current()
    with _external_lock:
        libraries = _load_external(ws)
    symbols, footprints = _all_records()
    out: list[ExternalLibrary] = []
    for lib in libraries:
        key = os.path.normcase(lib.path)
        count = sum(
            1 for r in _combined(symbols, footprints)
            if r.source == "external" and r.library and os.path.normcase(str(ws.abs(r.library) or "")) == key
        )
        out.append(lib.model_copy(update={"exists": Path(lib.path).is_file(), "registered": count}))
    return out


def get_external_library(library_id: str) -> ExternalLibrary:
    for lib in list_external_libraries():
        if lib.id == library_id:
            return lib
    raise SyncError("Externe Bibliothek nicht gefunden.", status=404)


def add_external_library(path: str) -> ExternalLibrary:
    """Register an existing SchLib/PcbLib read-only (it is checked to be readable)."""
    ws = current()
    raw = str(path or "").strip().strip('"')
    if not raw:
        raise SyncError("Bitte den Pfad einer .SchLib- oder .PcbLib-Datei angeben.")
    file = Path(raw)
    if not file.is_absolute():
        raise SyncError(f"Der Pfad muss absolut sein: {raw}")
    file = Path(os.path.abspath(file))
    kind = library_file_kind(file)
    if kind is None:
        raise SyncError(f"{file.name} ist keine Altium-Bibliothek (.SchLib oder .PcbLib).")
    if not file.is_file():
        raise SyncError(f"Die Datei {file} wurde nicht gefunden.", status=404)
    if is_inside(file, ws.symbols_dir) or is_inside(file, ws.footprints_dir):
        raise SyncError(
            f"{file.name} liegt in einem Bibliotheksordner von PartForge – solche Dateien werden von PartForge verwaltet "
            "(„Bibliotheken prüfen“ übernimmt ihre Bauteile)."
        )
    scan_library(file)  # readable?
    with _external_lock:
        libraries = _load_external(ws)
        library_id = _external_id(str(file))
        for lib in libraries:
            if lib.id == library_id:
                return lib.model_copy(update={"exists": True})
        entry = ExternalLibrary(
            id=library_id, path=str(file), kind=kind, name=file.name,
            added=_dt.datetime.now().isoformat(timespec="seconds"),
        )
        _save_external(ws, [*libraries, entry])
    log.info("Externe Bibliothek registriert: %s", file)
    return entry


def remove_external_library(library_id: str) -> dict:
    """Unregister an external library (registered components stay usable)."""
    ws = current()
    with _external_lock:
        libraries = _load_external(ws)
        remaining = [lib for lib in libraries if lib.id != library_id]
        if len(remaining) == len(libraries):
            raise SyncError("Externe Bibliothek nicht gefunden.", status=404)
        removed = next(lib for lib in libraries if lib.id == library_id)
        _save_external(ws, remaining)
    symbols, footprints = _all_records()
    key = os.path.normcase(removed.path)
    still = [r.name for r in _combined(symbols, footprints)
             if r.source == "external" and os.path.normcase(str(ws.abs(r.library) or "")) == key]
    return {"removed": removed.id, "path": removed.path, "registered_components": still}


def external_components(
    library_id: str,
    *,
    previews: bool = False,
    search: str | None = None,
    offset: int = 0,
    limit: int = 100,
    theme: str = "dark",
    writer: LibraryWriter | None = None,
) -> dict[str, Any]:
    """Components of an external library (names, metadata, optional SVG previews)."""
    library = get_external_library(library_id)
    path = Path(library.path)
    if not path.is_file():
        raise SyncError(f"Die externe Bibliothek {library.path} existiert nicht mehr.", status=404)
    infos = scan_library(path)
    if search:
        needle = search.casefold()
        infos = [i for i in infos if needle in i.name.casefold() or needle in (i.description or "").casefold()]
    total = len(infos)
    page = infos[max(0, offset) : max(0, offset) + max(1, min(limit, 500))]
    symbols, footprints = _all_records()
    registered = {r.name.casefold(): r for r in _combined(symbols, footprints)}
    ws = current()
    session = _Session(ws, None, writer)
    rows: list[dict[str, Any]] = []
    for info in page:
        rec = registered.get(info.name.casefold())
        row: dict[str, Any] = {
            **info.model_dump(),
            "registered": rec is not None,
            "registered_source": rec.source if rec is not None else None,
            "conflict": rec is not None and (
                rec.source != "external" or os.path.normcase(str(ws.abs(rec.library) or "")) != os.path.normcase(str(path))
            ),
            "svg": None,
        }
        if previews:
            row["svg"] = _preview_svg(session, path, info.name, theme)
        rows.append(row)
    session.finish()
    return {"library": library.model_dump(), "total": total, "offset": offset, "components": rows}


#: Part of every thumbnail ETag and content hash: bump when :func:`component_thumbnail` draws differently
#: (images cached by the browser become stale).
THUMBNAIL_VERSION: Final = "3"


def thumbnail_salt(kind: Kind) -> str:
    """What a thumbnail depends on besides the spec: :data:`THUMBNAIL_VERSION` and, for symbols, the house style of
    the open workspace."""
    extra: Any = None
    if kind == "symbol":
        from ..symbols.style import resolve_style

        extra = resolve_style(None).model_dump(mode="json")
    return json.dumps({"v": THUMBNAIL_VERSION, "kind": kind, "extra": extra}, sort_keys=True, separators=(",", ":"))


def thumbnail_hash(kind: Kind, spec_hash: str | None, *, salt: str | None = None) -> str | None:
    """Thumbnail version (``content_hash`` of the API entries) from the registry's ``content_hash`` – the sha256 of
    the stored spec text that every record read with its spec carries (``None`` = no geometry)."""
    if not spec_hash:
        return None
    return hashlib.sha256(f"{salt if salt is not None else thumbnail_salt(kind)}\n{spec_hash}".encode()).hexdigest()[:20]


def content_hashes(kind: Kind, name: str | None = None) -> dict[str, str | None]:
    """``{casefolded name: content hash}`` of the registered symbols/footprints (or only of ``name``) – the version
    of their thumbnail (:func:`component_thumbnail`).

    Covers the stored spec text (:func:`partforge.db.registry.content_hashes` – read, never parsed), for symbols
    the house style of the open workspace, and :data:`THUMBNAIL_VERSION`: it changes exactly when the thumbnail may
    change (not with the status). ``None`` = no geometry stored. A list that read the specs anyway converts the
    records' ``content_hash`` with :func:`thumbnail_hash` instead (no second read)."""
    raw = registry.content_hashes(kind, [name] if name is not None else None)
    salt = thumbnail_salt(kind)
    return {key: thumbnail_hash(kind, value, salt=salt) for key, value in raw.items()}


def component_thumbnail(spec: Spec, theme: str = "dark") -> str:
    """Thumbnail SVG of a symbol or footprint – the same look everywhere (registry lists,
    ``…/thumbnail.svg``, external libraries): symbols via :func:`partforge.symbols.render_thumbnail`
    (part 1, no labels, sans-serif, constant stroke), footprints 160 px without grid and pad numbers."""
    chosen = theme if theme in ("altium", "dark", "light") else "dark"
    if isinstance(spec, SymbolSpec):
        from ..symbols import render_thumbnail

        return render_thumbnail(spec, theme=chosen)
    from ..footprints import render_svg as render_footprint

    return render_footprint(spec, theme=cast(Any, chosen), width_px=160, grid=False, show_pad_numbers=False)


def _preview_svg(session: _Session, library: Path, name: str, theme: str) -> str | None:
    try:
        spec = _read_component(session.writer(), library, name)
    except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
        log.info("Vorschau von %s nicht möglich: %s", name, exc)
        return None
    if spec is None:
        return None
    try:
        return component_thumbnail(spec, theme)
    except Exception as exc:  # noqa: BLE001 - a foreign component must not break the listing
        log.info("Vorschau von %s nicht darstellbar: %s", name, exc)
        return None


def use_external_component(library_id: str, name: str, *, writer: LibraryWriter | None = None) -> Record:
    """Register one component of an external library (``source="external"``, absolute path).

    Parts can then reference it with ``Library Ref``/``Footprint Ref`` = ``name`` and the
    absolute library path; PartForge never writes the external file.
    """
    ws = current()
    library = get_external_library(library_id)
    path = Path(library.path)
    if not path.is_file():
        raise SyncError(f"Die externe Bibliothek {library.path} existiert nicht mehr.", status=404)
    session = _Session(ws, None, writer)
    try:
        names = session.names_in(path)
    finally:
        session.finish()
    if names is None:
        names = [i.name for i in scan_library(path)]
    actual = next((n for n in names if n.casefold() == name.strip().casefold()), None)
    if actual is None:
        raise SyncError(f"„{name}“ ist nicht in {library.name} enthalten.", status=404)
    kind: Kind = "symbol" if library.kind == "schlib" else "footprint"
    existing = registry.get_symbol(actual) if kind == "symbol" else registry.get_footprint(actual)
    if existing is not None:
        same = existing.source == "external" and os.path.normcase(str(ws.abs(existing.library) or "")) == os.path.normcase(
            str(path)
        )
        if same:
            return existing
        raise SyncError(
            f"Der Name „{actual}“ ist bereits als {'Symbol' if kind == 'symbol' else 'Footprint'} registriert "
            f"({existing.library or 'ohne Bibliothek'}). Altium unterscheidet Bauteile nur über den Namen – bitte das "
            "vorhandene verwenden.",
            status=409,
        )
    try:
        spec = _read_component(session.writer(), path, actual)
    except (WriterUnavailable, RustWriterError, RuntimeError, OSError) as exc:
        log.info("%s aus %s nicht lesbar (nur Name registriert): %s", actual, path, exc)
        spec = None
    stored_path = ws.rel(path)
    with session.bound():
        if kind == "symbol":
            sym = cast(SymbolSpec | None, spec)
            return registry.upsert_symbol(
                SymbolRecord(name=actual, library=stored_path, source="external", spec=sym,
                             pin_count=len(sym.pins) if sym else 0, part_count=sym.part_count if sym else 1, status="ok")
            )
        fp = cast(FootprintSpec | None, spec)
        return registry.upsert_footprint(
            FootprintRecord(name=actual, library=stored_path, source="external", spec=fp,
                            family=(fp.family or None) if fp else None, pad_count=len(fp.pads) if fp else 0,
                            height=fp.height if fp else None, status="ok")
        )
