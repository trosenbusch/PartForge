"""Live tests against a running Altium Designer (marker ``altium``; PARTFORGE_TEST_ALTIUM=1).

Only the Altium E2E run executes them. They use a DbLib with a **unique file name** in
``tmp_path`` (never ``PartForge.DbLib`` – placed parts resolve DbLibs by file name), close
its hidden server document and uninstall it again in every case; no user document is
touched.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from partforge.altium import refresh
from partforge.altium.dblib import (
    cached_install_state,
    remember_install_state,
    write_dblib,
)
from partforge.altium.refresh import AltiumRefreshService
from partforge.config import AltiumSettings, AppSettings
from partforge.db import parts

pytestmark = pytest.mark.altium

PART = {"Manufacturer": "YAGEO", "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Description": "RES live",
        "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}
#: Same stable exchange directory as test_bridge_live.py (one script project in Altium for
#: every live run; never the exchange directory of the user's own PartForge).
LIVE_EXCHANGE = Path(__file__).parent / "_tmp" / "altium-live" / "exchange"


@pytest.fixture
def live(workspace):
    workspace.settings.dblib_file = f"PF_Live_{uuid.uuid4().hex[:8]}.DbLib"
    workspace.save()
    parts.create_part("Resistors", {"Part Number": "PF-LIVE-1", **PART})
    write_dblib(workspace)
    bridge = refresh.default_bridge(AppSettings(altium=AltiumSettings(bridge_exchange_dir=str(LIVE_EXCHANGE))))
    try:
        yield workspace, bridge
    finally:
        try:  # release the database first: UninstallLibrary leaves the hidden document open
            bridge.refresh_dblib(workspace.settings.dblib_file, rebuild_index=False)
        finally:
            bridge.uninstall_library(workspace.dblib_path)


def test_install_state_and_refresh_make_new_rows_visible(live):
    ws, bridge = live
    assert bridge.install_state(ws.dblib_path).installed is False
    bridge.install_library(ws.dblib_path)
    state = bridge.install_state(ws.dblib_path)
    assert state.installed and state.resolves_to_this and state.duplicates == []
    first = bridge.resolve_db_component(ws.dblib_path, "Resistors", "PF-LIVE-1")
    assert first.parameters.get("Part Number") == "PF-LIVE-1"

    parts.create_part("Resistors", {"Part Number": "PF-LIVE-2", **PART})
    parts.update_part("Resistors", "PF-LIVE-1", {"Notes": "geändert"})
    result = bridge.refresh_dblib(ws.settings.dblib_file, rebuild_index=True)
    assert result.installed and result.refreshed_index and not result.skipped
    second = bridge.resolve_db_component(ws.dblib_path, "Resistors", "PF-LIVE-2")
    assert second.parameters.get("Part Number") == "PF-LIVE-2"
    assert bridge.install_state(ws.dblib_path).same_name[0].document_open is False


def test_refresh_without_installation_touches_nothing(live):
    ws, bridge = live
    result = bridge.refresh_dblib(ws.settings.dblib_file, rebuild_index=True)
    assert result.matched == [] and not result.refreshed_index and result.closed == []


def test_close_then_uninstall_releases_the_database(live):
    """The order used by the uninstall job: UninstallLibrary alone leaves the hidden DbLib
    document (and its database connection) open (altium-refresh.md §3.3)."""
    ws, bridge = live
    bridge.install_library(ws.dblib_path)
    assert bridge.document_state(ws.dblib_path).open  # InstallLibrary opens the hidden document
    released = bridge.refresh_dblib(ws.settings.dblib_file, rebuild_index=False)
    assert released.closed and not released.skipped
    bridge.uninstall_library(ws.dblib_path)
    assert not bridge.install_state(ws.dblib_path).installed
    assert not bridge.document_state(ws.dblib_path).open  # no connection left on the database


def _wait_for_refresh(service: AltiumRefreshService, count: int, timeout_s: float = 120) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status = service.status()
        assert status.last_error is None, status.last_error
        if status.refresh_count >= count and not status.pending and not status.running:
            return
        time.sleep(0.5)
    raise AssertionError(f"keine Altium-Aktualisierung nach {timeout_s} s: {service.status()}")


def test_new_column_is_visible_after_the_automatic_refresh(live):
    """Altium caches the column list of every DbLib table: closing the hidden document shows
    new rows but not a new column; only the index rebuild the service runs for structure
    changes does (VERIFIED, altium-e2e.md)."""
    from partforge.db import categories
    from partforge.db.models import FieldDef

    ws, bridge = live
    bridge.install_library(ws.dblib_path)
    remember_install_state(bridge.install_state(ws.dblib_path), dblib=ws.dblib_path)
    before = bridge.resolve_db_component(ws.dblib_path, "Resistors", "PF-LIVE-1")  # Altium caches the columns
    assert before.parameters.get("Part Number") == "PF-LIVE-1" and "E2E Spalte" not in before.parameters
    service = AltiumRefreshService(debounce_s=0.5, bridge_factory=lambda: bridge)
    service.start()
    try:
        categories.add_field("Resistors", FieldDef(column="E2E Spalte", label="E2E Spalte"))
        parts.update_part("Resistors", "PF-LIVE-1", {"E2E Spalte": "sichtbar"})
        _wait_for_refresh(service, 1)
    finally:
        service.stop()
        service.wait_idle(120)
    after = bridge.resolve_db_component(ws.dblib_path, "Resistors", "PF-LIVE-1")
    assert after.parameters.get("E2E Spalte") == "sichtbar"  # close only: the column stays invisible
    assert service.status().last_result["rebuild_index"] is True


def test_automatic_refresh_after_a_write(live):
    ws, bridge = live
    bridge.install_library(ws.dblib_path)
    remember_install_state(bridge.install_state(ws.dblib_path), dblib=ws.dblib_path)
    service = AltiumRefreshService(debounce_s=0.5, bridge_factory=lambda: bridge)
    service.start()
    try:
        parts.create_part("Resistors", {"Part Number": "PF-LIVE-3", **PART})
        deadline = time.monotonic() + 120
        while service.status().refresh_count == 0 and time.monotonic() < deadline:
            assert service.status().last_error is None, service.status().last_error
            time.sleep(0.5)
        assert service.status().refresh_count == 1
        assert service.status().last_result["rebuild_index"] is True
    finally:
        service.stop()
        service.wait_idle(120)
    state = cached_install_state(ws.dblib_path)
    assert state is not None and state.installed
    found = bridge.resolve_db_component(ws.dblib_path, "Resistors", "PF-LIVE-3")
    assert found.parameters.get("Part Number") == "PF-LIVE-3"
