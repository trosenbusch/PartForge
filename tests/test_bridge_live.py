"""Live tests against a running Altium Designer (marker ``altium``; PARTFORGE_TEST_ALTIUM=1).

They only create files under ``tmp_path``, close every document they opened and never
touch user documents. Optional DbLib check: PARTFORGE_TEST_DBLIB="<DbLib>|<table>|<key>".

All live tests share **one stable exchange directory** (:data:`LIVE_EXCHANGE`): every
exchange directory is a script project of its own that Altium keeps loaded in its
Projects panel after the first run. A fresh ``tmp_path`` per test would leave one project
per test behind, pointing at folders pytest deletes later.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_writer_samples import (
    chip_0603,
    header_tht,
    ic8_symbol,
    opamp_symbol,
    resistor_symbol,
    soic8,
)

from partforge.altium.bridge import AltiumBridge, AltiumLibraryWriter

pytestmark = pytest.mark.altium

#: Exchange directory (and script project) of every live test run.
LIVE_EXCHANGE = Path(__file__).parent / "_tmp" / "altium-live" / "exchange"


@pytest.fixture
def bridge() -> AltiumBridge:
    return AltiumBridge.from_settings(exchange_dir=LIVE_EXCHANGE)


def test_ping(bridge):
    version = bridge.ping()
    assert version and version[0].isdigit()


def test_installed_libraries(bridge):
    libraries = bridge.installed_libraries()
    assert isinstance(libraries, list)


def test_write_and_list_libraries(bridge, tmp_path):
    sch = tmp_path / "PF_Live.SchLib"
    result = bridge.write_schlib(sch, [resistor_symbol(), ic8_symbol(), opamp_symbol()])
    assert sch.is_file() and result.written == ["PF_RES", "NE555DR", "LM358_DUAL"]
    pcb = tmp_path / "PF_Live.PcbLib"
    result = bridge.write_pcblib(pcb, [chip_0603(), soic8(), header_tht()])
    assert pcb.is_file() and len(result.written) == 3
    assert sorted(bridge.list_components(sch)) == sorted(["PF_RES", "NE555DR", "LM358_DUAL"])
    bridge.close_own_documents()


def _drawing_order(raw: dict) -> list[tuple[str, int]]:
    """``(kind, owner part)`` of every primitive of a Rust-read component in file order
    (parameters left out). ``primitive_order`` lists the kinds; the per-kind lists
    (``pins``, ``polygons`` …) are in file order and carry ``owner_part_id``."""
    cursor: dict[str, int] = {}
    order: list[tuple[str, int]] = []
    for token in raw["primitive_order"]:
        if token == "parameter":
            continue
        items = raw.get(f"{token}s") or []
        index = cursor.get(token, 0)
        cursor[token] = index + 1
        part = int(items[index].get("owner_part_id") or 0) if index < len(items) else 0
        order.append((token, part))
    return order


@pytest.mark.rustwriter
def test_bridge_symbols_store_graphics_before_pins(bridge, tmp_path):
    """Altium paints records in file order: the filled IC body must come before the pins
    (otherwise it hides the pin names, altium-verify-2 §3.3). Checked with the Rust reader.

    VERIFIED in Altium 26.10 (altium-e2e.md): when Altium saves a multi-part symbol it
    regroups the records by part (LM358_DUAL: part 2, part 3, then part 1), so the order
    only holds **per part** – which is all that matters, because Altium draws one part at
    a time (records of part 0 belong to every part)."""
    from partforge.altium.rustwriter import RustLibraryOps, _posix, shutdown_client

    sch = tmp_path / "PF_Order.SchLib"
    bridge.write_schlib(sch, [ic8_symbol(), opamp_symbol()])
    ops = RustLibraryOps(extra_dirs=[tmp_path])
    try:
        client = ops.client()
        for name, graphics in (("NE555DR", 1), ("LM358_DUAL", len(opamp_symbol().graphics))):
            raw = client.call_tool("get_component", {"filepath": _posix(sch), "component_name": name})["component"]
            order = _drawing_order(raw)
            drawn = [(i, part) for i, (kind, part) in enumerate(order) if kind != "pin"]
            pins = [(i, part) for i, (kind, part) in enumerate(order) if kind == "pin"]
            assert len(drawn) == graphics, order
            hidden = [(g, p) for g, g_part in drawn for p, p_part in pins
                      if g > p and (g_part == p_part or g_part <= 0 or p_part <= 0)]
            assert not hidden, order  # a graphic after a pin of the same part would cover its name
    finally:
        shutdown_client()


def test_altium_writer_full_cycle(bridge, tmp_path):
    writer = AltiumLibraryWriter(bridge)
    lib = tmp_path / "PF_Cycle.PcbLib"
    assert writer.write_library_full(lib, [chip_0603()]).ok
    assert writer.write_library_full(lib, [chip_0603(), soic8()]).ok
    assert lib.is_file()


def _test_dblib() -> tuple[Path, str, str]:
    spec = os.environ.get("PARTFORGE_TEST_DBLIB")
    if not spec:
        pytest.skip("PARTFORGE_TEST_DBLIB nicht gesetzt")
    dblib, table, key = spec.split("|")
    return Path(dblib), table, key


def test_resolve_db_component(bridge):
    dblib, table, key = _test_dblib()
    result = bridge.resolve_db_component(dblib, table, key)
    assert result.symbol_ref and result.symbol_path
    assert result.loaded and result.comment and result.comment_visible is not None


def test_resolve_db_components_in_several_runs(bridge):
    """More keys than one script run takes (RESOLVE_BATCH_SIZE): every key is resolved exactly
    like the single lookup, in request order; an unknown key is "not loaded", not an error."""
    from partforge.altium.bridge.core import RESOLVE_BATCH_SIZE

    dblib, table, key = _test_dblib()
    single = bridge.resolve_db_component(dblib, table, key)
    keys = [(table, key)] * (RESOLVE_BATCH_SIZE + 5)
    keys[RESOLVE_BATCH_SIZE] = (table, "PF-GIBT-ES-NICHT-4711")
    results = bridge.resolve_db_components(dblib, keys)
    assert [(r.table, r.key) for r in results] == keys
    missing = results[RESOLVE_BATCH_SIZE]
    assert not missing.loaded and missing.footprints == [] and missing.pin_count is None
    for result in results[:RESOLVE_BATCH_SIZE] + results[RESOLVE_BATCH_SIZE + 1 :]:
        assert result.model_dump(exclude={"temporarily_installed", "released"}) == single.model_dump(
            exclude={"temporarily_installed", "released"}
        )
