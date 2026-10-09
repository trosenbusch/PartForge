"""Datasheet import -> the REAL library synchronisation (``partforge.altium.sync``).

The commit of a proposal goes through ``sync.ensure_symbols`` / ``sync.ensure_footprints`` with an in-memory
:class:`~partforge.altium.libwriter.LibraryWriter` (no Rust process, no Altium): registry status, library files,
pin-out protection and the part links are checked end to end. One test uses the real Rust writer
(marker ``rustwriter``). Altium is never touched (``sync.altium_bridge`` returns ``None``).
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from partforge.altium import libwriter, sync
from partforge.altium.models import ComponentInfo, WriteResult
from partforge.config import AppSettings
from partforge.datasheet import store
from partforge.datasheet.extract import ExtractOptions, run_extraction, store_edited_extraction
from partforge.datasheet.llm import ReplayLlmClient
from partforge.datasheet.models import ProposalChoices
from partforge.datasheet.proposal import build_proposal, commit_proposal
from partforge.db import parts, registry
from partforge.geometry.model import FootprintSpec, SymbolSpec
from partforge.workspace import Workspace

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
PDFS = DATA / "corpus" / "pdfs"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not PDFS.is_dir(), reason="Testdaten fehlen")

Spec = SymbolSpec | FootprintSpec


class MemoryWriter:
    """In-memory library writer (behaves like the Rust backend; leaves a placeholder file per library)."""

    name = "rust"

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Spec]] = {}

    @staticmethod
    def _key(library: Path) -> str:
        return os.path.normcase(os.path.abspath(library))

    def _store(self, library: Path, specs: Sequence[Spec], *, replace: bool) -> WriteResult:
        components = {} if replace else dict(self.files.get(self._key(library), {}))
        for spec in specs:
            components[spec.name] = spec
        self.files[self._key(library)] = components
        Path(library).parent.mkdir(parents=True, exist_ok=True)
        Path(library).write_bytes(f"PartForge-Test {len(components)}".encode())
        return WriteResult(library=str(library), backend="rust", written=[s.name for s in specs])

    def available(self) -> tuple[bool, str]:
        return True, "Test-Writer"

    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult:
        return self._store(library, symbols, replace=False)

    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult:
        return self._store(library, footprints, replace=False)

    def write_library_full(self, library: Path, specs: Sequence[Spec]) -> WriteResult:
        return self._store(library, list(specs), replace=True)

    def delete_components(self, library: Path, names: list[str]) -> WriteResult:
        components = self.files.get(self._key(library), {})
        return WriteResult(library=str(library), backend="rust",
                           deleted=[n for n in names if components.pop(n, None) is not None])

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
        return [ComponentInfo(name=n, library=str(library), kind=kind)  # type: ignore[arg-type]
                for n in self.list_components(library)]

    def symbol(self, ws: Workspace, name: str) -> SymbolSpec:
        rec = registry.get_symbol(name)
        assert rec is not None and rec.status == "ok", (name, rec)
        spec = self.read_symbol(ws.abs(rec.library), name)  # type: ignore[arg-type]
        assert spec is not None, f"{name} fehlt in {rec.library}"
        return spec


@pytest.fixture
def writer(monkeypatch) -> MemoryWriter:
    memory = MemoryWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *args, **kwargs: memory)
    monkeypatch.setattr(libwriter, "get_writer", lambda *args, **kwargs: memory)
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    yield memory
    libwriter.forget_component_names()


def extracted(workspace: Workspace, stem: str) -> str:
    fx = json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], ws=workspace)
    run_extraction(None, rec.id, ExtractOptions.model_validate(fx["options"]), ws=workspace,
                   client=ReplayLlmClient(fx["calls"]), settings=AppSettings())
    return rec.id


def _pin_names(spec: SymbolSpec) -> dict[str, str]:
    return {p.designator: p.name for p in spec.pins}


def test_commit_writes_libraries_through_the_real_sync(workspace, writer):
    ds = extracted(workspace, "25AA02E48")
    result = commit_proposal(None, ds, None, ws=workspace)
    assert sorted(result["created"]) == ["25AA02E48-I/SN", "25AA02E48T-I/OT", "25AA02E48T-I/SN"]
    assert result["errors"] == {} and sorted(result["symbols"]) == ["25AA02E48 SOIC-8", "25AA02E48 SOT-23-6"]
    assert len(result["footprints"]) == 2
    soic = writer.symbol(workspace, "25AA02E48 SOIC-8")
    assert _pin_names(soic)["1"] == "C\\S\\" and _pin_names(soic)["8"] == "VCC"
    for footprint in result["footprints"]:
        rec = registry.get_footprint(footprint)
        assert rec is not None and rec.status == "ok" and rec.source == "datasheet"
        assert footprint in writer.list_components(workspace.abs(rec.library))  # type: ignore[arg-type]
    row = parts.get_part("Integrated Circuits", "25AA02E48-I/SN")
    symbol_rec = registry.get_symbol(row["Library Ref"])
    footprint_rec = registry.get_footprint(row["Footprint Ref"])
    assert row["Library Path"] == symbol_rec.library and row["Footprint Path"] == footprint_rec.library
    # a second commit writes nothing and creates nothing
    again = commit_proposal(None, ds, None, ws=workspace)
    assert again["symbols"] == [] and again["footprints"] == [] and again["created"] == []
    assert sorted(again["skipped"]) == sorted(result["created"])


def _edit_pin(ds: str, package: str, number: str, name: str) -> None:
    data = store.load_meta(store.get_record(ds)).extraction
    pin = next(p for p in data.devices[0].pin_table(package).pins if p.number == number)
    pin.name = name
    store_edited_extraction(ds, data)


def test_a_changed_pinout_gets_a_new_symbol_unless_confirmed(workspace, writer):
    """Reviewer case h4b with the real sync: a corrected pin name must not be linked to the old symbol."""
    ds = extracted(workspace, "25AA02E48")
    commit_proposal(None, ds, None, ws=workspace)
    _edit_pin(ds, "SN", "8", "VDD")
    update = ProposalChoices(mode="update", overwrite_existing=True)
    proposal = build_proposal(ds, update, ws=workspace, svg=False)
    soic = next(s for s in proposal.symbols if s.package == "SN")
    assert soic.name == "25AA02E48 SOIC-8_2" and soic.taken_name == "25AA02E48 SOIC-8"
    result = commit_proposal(None, ds, update, ws=workspace)
    assert "25AA02E48 SOIC-8_2" in result["symbols"] and result["errors"] == {}
    assert _pin_names(writer.symbol(workspace, "25AA02E48 SOIC-8"))["8"] == "VCC"  # the old one is untouched
    assert _pin_names(writer.symbol(workspace, "25AA02E48 SOIC-8_2"))["8"] == "VDD"
    assert parts.get_part("Integrated Circuits", "25AA02E48-I/SN")["Library Ref"] == "25AA02E48 SOIC-8_2"

    # confirmed: the registered symbol of the generated name gets the new pin-out (all parts using it change)
    _edit_pin(ds, "SN", "1", "C\\S\\X")
    confirmed = ProposalChoices(mode="update", allow_pin_changes=True)
    proposal = build_proposal(ds, confirmed, ws=workspace, svg=False)
    soic = next(s for s in proposal.symbols if s.package == "SN")
    assert soic.name == "25AA02E48 SOIC-8" and soic.exists
    assert "Pin 8: Name „VCC“ → „VDD“" in soic.pin_changes and any(c.startswith("Pin 1:") for c in soic.pin_changes)
    result = commit_proposal(None, ds, confirmed, ws=workspace)
    assert result["symbols"] == ["25AA02E48 SOIC-8"] and result["errors"] == {}
    names = _pin_names(writer.symbol(workspace, "25AA02E48 SOIC-8"))
    assert names["1"] == "C\\S\\X" and names["8"] == "VDD"
    assert parts.get_part("Integrated Circuits", "25AA02E48-I/SN")["Library Ref"] == "25AA02E48 SOIC-8"


def test_parts_are_not_created_when_their_symbol_cannot_be_written(workspace, writer, monkeypatch):
    """The library is open and modified in Altium: sync refuses to write it, the parts wait."""
    ds = extracted(workspace, "opa656")

    def refusal(self, library: Path) -> str | None:
        return sync.ALTIUM_MODIFIED_MESSAGE if str(library).lower().endswith(".schlib") else None

    monkeypatch.setattr(sync._AltiumGuard, "refusal", refusal)  # noqa: SLF001 - simulates a modified document
    choice = ProposalChoices(variants=["OPA656U"])
    result = commit_proposal(None, ds, choice, ws=workspace)
    assert result["created"] == [] and "ungespeichert" in result["errors"]["OPA656U"]
    assert result["symbols"] == [] and len(result["footprints"]) == 1
    assert parts.get_part("Amplifiers", "OPA656U") is None
    # Altium saved the file: the next commit writes the pending symbol and creates the part
    monkeypatch.setattr(sync._AltiumGuard, "refusal", lambda self, library: None)  # noqa: SLF001
    proposal = build_proposal(ds, choice, ws=workspace, svg=False)
    assert proposal.symbols[0].status == "error"
    retry = commit_proposal(None, ds, choice, ws=workspace)
    assert retry["created"] == ["OPA656U"] and len(retry["symbols"]) == 1 and retry["footprints"] == []


@pytest.mark.rustwriter
def test_commit_with_the_real_rust_writer(workspace, monkeypatch):
    from partforge.altium.rustwriter import RustLibraryOps, shutdown_client

    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    try:
        ds = extracted(workspace, "opa656")
        result = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U", "OPA656N/250"]), ws=workspace)
        assert sorted(result["created"]) == ["OPA656N/250", "OPA656U"] and result["errors"] == {}, result
        ops = RustLibraryOps(workspace=workspace)
        for name in result["symbols"]:
            rec = registry.get_symbol(name)
            assert rec is not None and rec.status == "ok", (name, rec.status_message if rec else None)
            assert name in ops.list_components(workspace.abs(rec.library))  # type: ignore[arg-type]
        for name in result["footprints"]:
            rec = registry.get_footprint(name)
            assert rec is not None and rec.status == "ok", (name, rec.status_message if rec else None)
            assert name in ops.list_components(workspace.abs(rec.library))  # type: ignore[arg-type]
        row: dict[str, Any] = parts.get_part("Amplifiers", "OPA656U") or {}
        assert row.get("Library Path") and row.get("Footprint Path")
    finally:
        shutdown_client()
        libwriter.forget_component_names()
