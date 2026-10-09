"""Integration: seeded example content goes through the real library synchronisation
(db.examples -> altium.sync -> LibraryWriter protocol) with an in-memory writer – no Rust
writer process and no Altium.

The recording writer implements :class:`partforge.altium.libwriter.LibraryWriter`; it keeps
the written specs per library file and leaves a placeholder file behind, so the registry,
the parts and the health check can be compared with what a real backend would receive.
"""
from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from partforge import db, events
from partforge.altium import libwriter, sync
from partforge.altium.models import ComponentInfo, WriteResult
from partforge.altium.rustwriter import (
    footprint_to_rust,
    symbol_to_rust,
    validate_footprint_payload,
    validate_symbol_payload,
)
from partforge.db import categories, health, parts, registry
from partforge.geometry.model import FootprintSpec, SymbolSpec
from partforge.workspace import Workspace, set_current

Spec = SymbolSpec | FootprintSpec


class RecordingWriter:
    """In-memory :class:`~partforge.altium.libwriter.LibraryWriter` (behaves like the Rust backend)."""

    name = "rust"

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Spec]] = {}
        self.calls: list[tuple[str, str, list[str]]] = []

    @staticmethod
    def _key(library: Path) -> str:
        return os.path.normcase(os.path.abspath(library))

    def _store(self, op: str, library: Path, specs: Sequence[Spec], *, replace: bool) -> WriteResult:
        key = self._key(library)
        components = {} if replace else dict(self.files.get(key, {}))
        for spec in specs:
            components[spec.name] = spec
        self.files[key] = components
        self.calls.append((op, str(library), [s.name for s in specs]))
        Path(library).parent.mkdir(parents=True, exist_ok=True)
        Path(library).write_bytes(f"PartForge-Test {len(components)}".encode())  # file exists and changes
        return WriteResult(library=str(library), backend="rust", written=[s.name for s in specs])

    def available(self) -> tuple[bool, str]:
        return True, "Test-Writer"

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        return self._store("symbols", library, symbols, replace=False)

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        return self._store("footprints", library, footprints, replace=False)

    def write_library_full(self, library: Path, specs: Sequence[SymbolSpec] | Sequence[FootprintSpec]) -> WriteResult:
        return self._store("full", library, list(specs), replace=True)

    def delete_components(self, library: Path, names: list[str]) -> WriteResult:
        components = self.files.get(self._key(library), {})
        deleted = [n for n in names if components.pop(n, None) is not None]
        return WriteResult(library=str(library), backend="rust", deleted=deleted)

    def list_components(self, library: Path) -> list[str]:
        return list(self.files.get(self._key(library), {}))

    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None:
        spec = self.files.get(self._key(library), {}).get(name)
        return spec if isinstance(spec, SymbolSpec) else None

    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None:
        spec = self.files.get(self._key(library), {}).get(name)
        return spec if isinstance(spec, FootprintSpec) else None

    def scan_library(self, library: Path) -> list[ComponentInfo]:
        kind = "symbol" if str(library).lower().endswith(".schlib") else "footprint"
        return [ComponentInfo(name=n, library=str(library), kind=kind) for n in self.list_components(library)]  # type: ignore[arg-type]


@pytest.fixture
def writer(monkeypatch: pytest.MonkeyPatch) -> RecordingWriter:
    recording = RecordingWriter()
    monkeypatch.setattr(libwriter, "get_writer", lambda *args, **kwargs: recording)
    if hasattr(sync, "get_writer"):
        monkeypatch.setattr(sync, "get_writer", lambda *args, **kwargs: recording)
    libwriter.forget_component_names()
    return recording


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Workspace]:
    ws = Workspace.create(tmp_path / "Bibliothek", name="Sync")
    db.open_database(ws)
    set_current(ws)
    try:
        db.seed_examples(ws)
        yield ws
    finally:
        db.close_database()
        set_current(None)
        libwriter.forget_component_names()


def _rel_files(ws: Workspace, writer: RecordingWriter) -> dict[str, set[str]]:
    return {ws.rel(Path(key)).casefold(): set(components) for key, components in writer.files.items()}


def test_sync_pending_writes_every_example(seeded: Workspace, writer: RecordingWriter) -> None:
    written_events: list[list[str]] = []
    unsubscribe = events.subscribe(events.LIBRARIES_WRITTEN, written_events.append)
    try:
        summary = sync.sync_pending()
    finally:
        unsubscribe()
    assert summary["errors"] == [] and summary["missing"] == [], summary
    assert summary["symbols"]["ok"] == 15 and summary["footprints"]["ok"] == 13, summary
    symbols, footprints = registry.list_symbols(), registry.list_footprints()
    assert {r.status for r in symbols} == {"ok"} and {r.status for r in footprints} == {"ok"}

    # every component landed in the library file the registry (and the parts) point to
    files = _rel_files(seeded, writer)
    entries: list[tuple[str, str]] = [(r.name, r.library) for r in symbols] + [(r.name, r.library) for r in footprints]
    for name, library in entries:
        assert name in files[library.casefold()], (name, library)
    assert files[r"symbols\pf_passives.schlib"] == {"Resistor", "Capacitor", "Inductor", "Ferrite Bead"}
    assert files[r"footprints\pf_sot23.pcblib"] == {"SOT95P237X112-3N", "SOT95P280X145-5N"}
    assert sum(len(names) for names in files.values()) == 28

    # the writer received valid payloads only
    for components in writer.files.values():
        for spec in components.values():
            if isinstance(spec, SymbolSpec):
                assert validate_symbol_payload(symbol_to_rust(spec, seeded.settings.symbol)) == []
            else:
                payload = footprint_to_rust(spec, seeded.settings.layers, seeded.settings.footprint)
                assert validate_footprint_payload(payload) == []

    # parts still reference the written libraries, the library is healthy
    for cat in categories.list_categories(with_counts=False):
        rows, _ = parts.query_parts(cat.table, limit=None)
        for row in rows:
            assert seeded.abs(row["Library Path"]).is_file() and seeded.abs(row["Footprint Path"]).is_file()  # type: ignore[union-attr]
    report = health.health_report()
    assert report["counts"]["error"] == 0 and report["counts"]["warning"] == 0, report["issues"][:5]
    assert written_events and {os.path.normcase(p) for p in written_events[-1]} == set(writer.files)

    # a second run has nothing to do
    calls = len(writer.calls)
    again = sync.sync_pending()
    assert again["errors"] == [] and len(writer.calls) == calls


def test_library_job_writes_through_the_real_sync(seeded: Workspace, writer: RecordingWriter) -> None:
    from partforge.api import routes_system
    from partforge.jobs import JobManager

    job = JobManager(max_workers=1).run_sync(routes_system.LIBRARY_SYNC_JOB_KIND, routes_system.LIBRARY_SYNC_JOB_TITLE,
                                             routes_system._write_libraries, seeded.root)
    assert job.status == "done", job.error
    result: dict[str, Any] = job.result
    assert result["errors"] == [] and result["symbols"]["ok"] == 15 and result["footprints"]["ok"] == 13
    assert registry.counts()["symbols"]["by_status"]["ok"] == 15


@pytest.mark.rustwriter
def test_real_rust_writer_accepts_every_example(seeded: Workspace) -> None:
    """End to end with ``altium-designer-mcp.exe`` (no Altium: the sync never touches Altium under pytest)."""
    from partforge.altium.libwriter import RustLibraryWriter
    from partforge.config import detect_rust_writer

    summary = sync.sync_pending()
    assert summary["errors"] == [] and summary["missing"] == [], summary
    assert summary["symbols"]["ok"] == 15 and summary["footprints"]["ok"] == 13, summary
    reader = RustLibraryWriter(detect_rust_writer(), workspace=seeded)
    expected: dict[str, set[str]] = {}
    entries = [(r.name, r.library, r.status, r.status_message) for r in registry.list_symbols()]
    entries += [(r.name, r.library, r.status, r.status_message) for r in registry.list_footprints()]
    for name, library, status, message in entries:
        assert status == "ok", (name, message)
        expected.setdefault(library, set()).add(name)
    for library, names in expected.items():
        path = seeded.abs(library)
        assert path is not None and path.is_file(), library
        assert set(reader.list_components(path)) == names, library
    dual = registry.get_symbol("Op-Amp Dual")
    assert dual and dual.spec
    stored = reader.read_symbol(seeded.abs(dual.library), "Op-Amp Dual")  # type: ignore[arg-type]
    assert stored is not None and stored.part_count == 3
    assert sorted(p.designator for p in stored.pins) == sorted(p.designator for p in dual.spec.pins)
    inductor = registry.get_footprint("INDM125125X650N_6E43")
    assert inductor and inductor.spec
    footprint = reader.read_footprint(seeded.abs(inductor.library), inductor.name)  # type: ignore[arg-type]
    assert footprint is not None and footprint.pad_designators() == ["1", "2"]
    report = health.health_report()
    assert report["counts"]["error"] == 0 and report["counts"]["warning"] == 0, report["issues"][:5]
