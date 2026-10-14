"""Altium library writer backend: lets the running Altium Designer build SchLib/PcbLib files.

The bridge always builds a complete **new** library file (PartForge writes to a fresh
path beside the target and replaces the target afterwards, with a backup in
``<workspace>/Backups/lib/``). Upserts and deletions therefore rebuild every component
of the library from a read-back of the existing file (Rust writer); without it only
libraries whose components are all replaced can be updated.

Safety rules:

* A rebuild must not silently lose data of components the caller did not touch. The
  read-back reports what the PartForge model cannot hold (pin decorations, vias, …)
  and :func:`~partforge.altium.bridge.spec.bridge_limitations` what the bridge cannot
  build (embedded STEP models, paste/mask settings). If an untouched component is
  affected, the operation is refused with :class:`AltiumWriterError` (recommendation:
  Rust backend) unless ``allow_degradation`` is set.
* The library is only replaced when Altium created **every** component; otherwise it
  stays unchanged and all components are reported in ``WriteResult.errors``.
* Read, merge and write happen under one :func:`~partforge.altium.rustwriter.library_lock`.
"""
from __future__ import annotations

import contextlib
import logging
import os
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol, cast

from ...geometry.model import FootprintSpec, SymbolSpec
from ...workspace import (
    FootprintStyle,
    LayerMap,
    SymbolStyle,
    Workspace,
    current_or_none,
)
from ..models import ComponentInfo, WriteResult
from ..rustwriter import (
    RustWriterError,
    is_inside,
    library_backup_dir,
    library_kind,
    library_lock,
    store_backup,
)
from .core import AltiumBridge, BridgeCommandError, BridgeError, BridgeWriteResult
from .spec import BridgeSpecError, bridge_limitations

log = logging.getLogger(__name__)

__all__ = ["AltiumDataLossError", "AltiumLibraryWriter", "AltiumWriterError", "LibraryReader"]

Spec = SymbolSpec | FootprintSpec


class AltiumWriterError(BridgeError):
    """The Altium backend cannot perform the requested change (German message)."""


class AltiumDataLossError(AltiumWriterError):
    """Rebuilding the library would lose data of untouched components (nothing was changed).

    ``losses`` maps component name -> German descriptions of what would be lost; the
    caller may retry with ``AltiumLibraryWriter.allow_degradation = True`` after the
    user has confirmed, or use the Rust backend.
    """

    def __init__(self, message: str, losses: Mapping[str, list[str]]):
        super().__init__(message)
        self.losses = {name: list(problems) for name, problems in losses.items()}


class LibraryReader(Protocol):
    """What the Altium backend needs to read existing libraries (:class:`RustLibraryOps`).

    ``read_all_detailed(library, extract_step=False)`` (optional) additionally returns
    per component the notes on what the read-back loses.
    """

    def read_all(self, library: Path) -> Sequence[Spec]: ...

    def list_components(self, library: Path) -> list[str]: ...

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None: ...

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None: ...

    def scan(self, library: Path) -> list[ComponentInfo]: ...


class AltiumLibraryWriter:
    """:class:`~partforge.altium.libwriter.LibraryWriter` through the DelphiScript bridge."""

    name = "altium"

    def __init__(
        self,
        bridge: AltiumBridge | None = None,
        *,
        reader: LibraryReader | None = None,
        workspace: Workspace | None = None,
        backup_keep: int = 20,
        allow_degradation: bool = False,
    ):
        self.bridge = bridge or AltiumBridge.from_settings()
        self.reader = reader
        self._workspace = workspace
        self._backup_keep = backup_keep
        self.allow_degradation = allow_degradation

    # -- context --------------------------------------------------------------------
    @property
    def workspace(self) -> Workspace | None:
        return self._workspace or current_or_none()

    def _layer_map(self) -> LayerMap:
        ws = self.workspace
        return ws.settings.layers if ws else LayerMap()

    def _symbol_style(self) -> SymbolStyle:
        ws = self.workspace
        return ws.settings.symbol if ws else SymbolStyle()

    def _footprint_style(self) -> FootprintStyle:
        ws = self.workspace
        return ws.settings.footprint if ws else FootprintStyle()

    def available(self) -> tuple[bool, str]:
        status = self.bridge.status()
        return status.available, status.message

    # -- helpers --------------------------------------------------------------------
    @staticmethod
    def _absolute(library: str | os.PathLike[str]) -> Path:
        path = Path(library)
        if not path.is_absolute():
            raise AltiumWriterError(f"Der Bibliothekspfad muss absolut sein: {library}")
        return Path(os.path.abspath(path))

    def _backups_dir(self, library: Path) -> Path:
        """``<workspace>/Backups/lib`` (:func:`library_backup_dir`), or the library's own folder outside a workspace."""
        ws = self.workspace
        if ws is not None and is_inside(library, ws.root):
            return library_backup_dir(ws, library)
        return library.parent

    def _backup(self, library: Path) -> Path | None:
        """Store the current library as ``<lib>.<YYYYMMDD_HHMMSS_mmm>.bak`` before replacing it."""
        if not library.exists():
            return None
        return store_backup(library, library, self._backups_dir(library), keep=self._backup_keep)

    @staticmethod
    def _read_existing(reader: LibraryReader, library: Path) -> list[tuple[Spec, list[str]]]:
        """Existing components with the notes on what their read-back loses."""
        detailed = getattr(reader, "read_all_detailed", None)
        if callable(detailed):
            return [(spec, list(notes)) for spec, notes in detailed(library, extract_step=False)]
        return [(spec, []) for spec in reader.read_all(library)]

    @staticmethod
    def _loss_message(library: Path, losses: Mapping[str, list[str]]) -> str:
        shown = [f"{name} ({'; '.join(problems)})" for name, problems in list(losses.items())[:5]]
        more = f" und {len(losses) - 5} weitere" if len(losses) > 5 else ""
        return (
            f"Das Altium-Backend müsste die Bibliothek {library.name} vollständig neu aufbauen und würde dabei Daten "
            f"unveränderter Bauteile verlieren: {', '.join(shown)}{more}. Bitte für diese Bibliothek den Bibliotheks-Writer "
            "verwenden (Einstellungen › Allgemein › Altium Designer › Bibliotheks-Writer). Es wurde nichts geändert."
        )

    def _existing(self, library: Path, keep_out: set[str]) -> tuple[list[Spec], list[str]]:
        """Components to rebuild unchanged (all except ``keep_out``) plus loss warnings.

        Raises :class:`AltiumDataLossError` if rebuilding them would lose data (unless
        ``allow_degradation``; then the losses become warnings) and
        :class:`AltiumWriterError` if they cannot be read at all.
        """
        if not library.exists():
            return [], []
        if self.reader is None:
            names = self.bridge.list_components(library)
            others = [n for n in names if n not in keep_out]
            if others:
                raise AltiumWriterError(
                    f"Die Bibliothek {library.name} enthält weitere Bauteile ({', '.join(others[:5])}"
                    f"{' …' if len(others) > 5 else ''}). Ohne Bibliotheks-Writer kann das Altium-Backend sie nicht übernehmen – "
                    "bitte den Bibliotheks-Writer einrichten oder die Bibliothek vollständig neu erzeugen."
                )
            return [], []
        try:
            items = self._read_existing(self.reader, library)
        except RustWriterError as exc:
            raise AltiumWriterError(
                f"Die vorhandenen Bauteile von {library.name} konnten nicht gelesen werden – es wurde nichts geändert. ({exc})"
            ) from exc
        losses: dict[str, list[str]] = {}
        for spec, notes in items:
            if spec.name in keep_out:
                continue
            problems = [*notes, *bridge_limitations(spec)]
            if problems:
                losses[spec.name] = problems
        warnings: list[str] = []
        if losses:
            if not self.allow_degradation:
                raise AltiumDataLossError(self._loss_message(library, losses), losses)
            warnings = [
                f"{name}: beim Neuaufbau durch Altium nicht übernommen: {'; '.join(problems)}"
                for name, problems in losses.items()
            ]
            log.warning("Altium-Backend baut %s mit Datenverlust neu auf: %s", library, ", ".join(losses))
        return [spec for spec, _ in items], warnings

    # -- writing --------------------------------------------------------------------
    def write_library_full(
        self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]
    ) -> WriteResult:
        """Build the library with exactly ``specs`` and replace the old file (backup first).

        The old file is only replaced if Altium created every component; otherwise it is
        kept and every component is reported in ``errors``.
        """
        started = time.perf_counter()
        lib = self._absolute(library)
        kind = library_kind(lib)
        spec_list: list[Spec] = list(specs)
        expected = SymbolSpec if kind == "schlib" else FootprintSpec
        if any(not isinstance(s, expected) for s in spec_list):
            raise AltiumWriterError(f"Die Bibliothek {lib.name} erwartet ausschließlich {expected.__name__}-Objekte.")
        result = WriteResult(library=str(lib), backend="altium")
        names = [s.name for s in spec_list]
        if not spec_list:
            raise AltiumWriterError("Das Altium-Backend kann keine leere Bibliothek schreiben.")
        tmp = lib.with_name(f"{lib.stem}.pf{uuid.uuid4().hex[:8]}{lib.suffix}")
        with library_lock(lib):
            try:
                built: BridgeWriteResult
                if kind == "schlib":
                    built = self.bridge.write_schlib(tmp, cast(list[SymbolSpec], spec_list), style=self._symbol_style())
                else:
                    built = self.bridge.write_pcblib(
                        tmp,
                        cast(list[FootprintSpec], spec_list),
                        layer_map=self._layer_map(),
                        style=self._footprint_style(),
                    )
                result.warnings.extend(built.warnings)
                if not tmp.exists():
                    raise BridgeCommandError("write", "Altium hat die Bibliothek nicht gespeichert.")
                created = set(built.written)
                missing = [n for n in names if n not in created]
                if missing:
                    listed = ", ".join(missing[:10]) + (" …" if len(missing) > 10 else "")
                    log.error("Altium-Backend: %s unvollständig erzeugt, fehlend: %s", lib, listed)
                    result.errors = {
                        name: (
                            "Von Altium nicht erzeugt – die Bibliothek bleibt unverändert."
                            if name in missing
                            else f"Nicht geschrieben: Altium hat nicht alle Bauteile erzeugt (fehlend: {listed}) – "
                            "die Bibliothek bleibt unverändert."
                        )
                        for name in names
                    }
                else:
                    self._backup(lib)
                    try:
                        os.replace(tmp, lib)
                    except PermissionError as exc:
                        raise AltiumWriterError(
                            f"Die Bibliothek {lib.name} ist gesperrt (in Altium geöffnet?) und konnte nicht ersetzt werden."
                        ) from exc
                    result.written = list(names)
            except BridgeSpecError:
                raise
            except (BridgeCommandError, AltiumWriterError, OSError) as exc:
                log.error("Altium-Backend: %s konnte nicht geschrieben werden: %s", lib, exc)
                result.written = []
                result.errors = {name: str(exc) for name in names}
            finally:
                with contextlib.suppress(OSError):
                    if tmp.exists():
                        tmp.unlink()
        result.duration_s = round(time.perf_counter() - started, 3)
        return result

    def _upsert(self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]) -> WriteResult:
        started = time.perf_counter()
        lib = self._absolute(library)
        library_kind(lib)
        new_specs: list[Spec] = list(specs)
        if not new_specs:
            return WriteResult(library=str(lib), backend="altium")
        by_name = {s.name: s for s in new_specs}
        with library_lock(lib):  # read, merge and write as one step (RLock: nested lock is fine)
            existing, loss_warnings = self._existing(lib, set(by_name))
            merged: list[Spec] = []
            seen: set[str] = set()
            for old in existing:
                merged.append(by_name.get(old.name, old))
                seen.add(old.name)
            merged.extend(s for s in new_specs if s.name not in seen)
            result = self.write_library_full(lib, merged)  # type: ignore[arg-type]
        result.warnings = [*loss_warnings, *result.warnings]
        # the untouched components were rebuilt too: their errors stay in the result
        result.written = [n for n in result.written if n in by_name]
        result.duration_s = round(time.perf_counter() - started, 3)
        return result

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        if library_kind(library) != "schlib":
            raise AltiumWriterError(f"{Path(library).name} ist keine Symbolbibliothek (.SchLib).")
        return self._upsert(library, symbols)

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        if library_kind(library) != "pcblib":
            raise AltiumWriterError(f"{Path(library).name} ist keine Footprint-Bibliothek (.PcbLib).")
        return self._upsert(library, footprints)

    def delete_components(self, library: Path, names: list[str]) -> WriteResult:
        started = time.perf_counter()
        lib = self._absolute(library)
        library_kind(lib)
        result = WriteResult(library=str(lib), backend="altium")
        wanted = set(names)
        if not lib.exists() or not wanted:
            return result
        if self.reader is None:
            raise AltiumWriterError(
                "Bauteile können mit dem Altium-Backend nur gelöscht werden, wenn der Bibliotheks-Writer zum Lesen verfügbar ist."
            )
        with library_lock(lib):
            existing, loss_warnings = self._existing(lib, wanted)
            remaining = [s for s in existing if s.name not in wanted]
            deleted = [s.name for s in existing if s.name in wanted]
            result.warnings.extend(loss_warnings)
            for name in sorted(wanted - set(deleted)):
                result.warnings.append(f"{name}: nicht in der Bibliothek vorhanden.")
            if not deleted:
                return result
            if not remaining:
                try:
                    self._backup(lib)
                    lib.unlink()
                except OSError as exc:
                    log.error("Altium-Backend: %s konnte nicht entfernt werden: %s", lib, exc)
                    result.errors = {
                        name: f"Nicht gelöscht: Die Bibliothek {lib.name} konnte nicht entfernt werden ({exc})."
                        for name in deleted
                    }
                else:
                    result.deleted = deleted
                    result.warnings.append(
                        f"Die Bibliothek {lib.name} war danach leer und wurde entfernt (Sicherung angelegt)."
                    )
            else:
                written = self.write_library_full(lib, remaining)  # type: ignore[arg-type]
                result.warnings.extend(written.warnings)
                if written.errors:
                    reason = next(iter(written.errors.values()))
                    result.errors = {name: f"Nicht gelöscht: {reason}" for name in deleted}
                    result.errors.update(written.errors)
                else:
                    result.deleted = deleted
        result.duration_s = round(time.perf_counter() - started, 3)
        return result

    # -- reading --------------------------------------------------------------------
    def list_components(self, library: Path) -> list[str]:
        lib = self._absolute(library)
        if self.reader is not None:
            return self.reader.list_components(lib)
        return self.bridge.list_components(lib)

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None:
        if self.reader is None:
            log.warning("Symbol %s kann ohne Bibliotheks-Writer nicht gelesen werden", name)
            return None
        try:
            return self.reader.read_symbol(library, name)
        except RustWriterError as exc:
            log.warning("Symbol %s konnte nicht gelesen werden: %s", name, exc)
            return None

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None:
        if self.reader is None:
            log.warning("Footprint %s kann ohne Bibliotheks-Writer nicht gelesen werden", name)
            return None
        try:
            return self.reader.read_footprint(library, name)
        except RustWriterError as exc:
            log.warning("Footprint %s konnte nicht gelesen werden: %s", name, exc)
            return None

    def scan_library(self, library: Path) -> list[ComponentInfo]:
        lib = self._absolute(library)
        if self.reader is not None:
            return self.reader.scan(lib)
        kind: Literal["symbol", "footprint"] = "symbol" if library_kind(lib) == "schlib" else "footprint"
        return [ComponentInfo(name=n, library=str(lib), kind=kind) for n in self.bridge.list_components(lib)]
