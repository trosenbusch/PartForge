"""Series commit through the REAL library sync and the Rust writer (marker ``rustwriter``; Altium is never
touched – ``sync.altium_bridge`` is disabled): symbol, footprints with STEP models, parts linked to the
written files, and an update that rewrites nothing."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from partforge.altium import libwriter, sync
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.db import parts, registry
from partforge.domain.series import SeriesRequest, commit, preview
from partforge.jobs import JobManager
from partforge.workspace import Workspace

pytestmark = pytest.mark.rustwriter


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture(autouse=True)
def _no_altium(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()


def _digests(ws: Workspace) -> dict[str, str]:
    files = [*ws.symbols_dir.glob("*.SchLib"), *ws.footprints_dir.glob("*.PcbLib")]
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def _check_written(ws: Workspace, table: str, pn: str) -> None:
    ops = RustLibraryOps(workspace=ws)
    part = parts.get_part(table, pn)
    assert part is not None, pn
    symbol = registry.get_symbol(str(part["Library Ref"]))
    footprint = registry.get_footprint(str(part["Footprint Ref"]))
    assert symbol is not None and symbol.status == "ok", symbol
    assert footprint is not None and footprint.status == "ok", footprint
    assert part["Library Path"] == symbol.library and part["Footprint Path"] == footprint.library
    symbol_lib, footprint_lib = ws.abs(symbol.library), ws.abs(footprint.library)
    assert isinstance(symbol_lib, Path) and isinstance(footprint_lib, Path)
    assert symbol.name in ops.list_components(symbol_lib)
    assert footprint.name in ops.list_components(footprint_lib)
    if footprint.step_file:
        assert (ws.root / footprint.step_file.replace("\\", "/")).is_file()


def test_series_with_the_real_sync(workspace: Workspace) -> None:
    capacitors = SeriesRequest(template_id="kemet-c-x7r", sizes=["0603", "0805"], voltages=["50V"], e_series="E6",
                               range_min="1n", range_max="1u")
    resistors = SeriesRequest(template_id="vishay-crcw-e3", sizes=["0603"], tolerance="1%", values=["1k", "10k"],
                              include_jumper=True)
    manager = JobManager(max_workers=1)
    try:
        caps = manager.run_sync("series", "Serie", commit, capacitors, "skip")
        res = manager.run_sync("series", "Serie", commit, resistors, "skip")
    finally:
        manager.shutdown()
    assert caps.status == "done" and res.status == "done", (caps.error, res.error)
    planned = preview(capacitors)
    assert caps.result["created"] == planned.counts["exists"] > 10 and caps.result["errors"] == 0
    assert not caps.result["pending"] and caps.result["symbol"] == "Capacitor"
    assert len(caps.result["footprints_created"]) >= 2  # thickness classes of 0603 and 0805
    assert res.result["created"] == 3 and res.result["errors"] == 0
    _check_written(workspace, "Capacitors", "C0603C104K5RACTU")
    _check_written(workspace, "Capacitors", "C0805C105K5RACTU")
    _check_written(workspace, "Resistors", "CRCW060310K0FKEA")
    _check_written(workspace, "Resistors", "CRCW06030000Z0EA")
    health = sync.library_health()
    assert [i for i in health["issues"] if i.severity == "error"] == []

    before = _digests(workspace)
    again = commit(None, capacitors, mode="update")
    assert again["created"] == 0 and again["errors"] == 0 and again["updated"] == 0
    assert _digests(workspace) == before  # unchanged symbol and footprints are not written again
