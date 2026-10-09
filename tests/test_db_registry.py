"""Registry of symbols, footprints and datasheets (pf_symbols / pf_footprints / pf_datasheets)."""
from __future__ import annotations

import pytest

from partforge.db import parts, registry
from partforge.db.models import DatasheetRecord, FootprintRecord, SymbolRecord
from partforge.geometry.model import FootprintSpec, Pad, SymbolSpec, SymPin, SymRect
from partforge.workspace import Workspace


def symbol_spec(name: str = "OPAMP_DUAL") -> SymbolSpec:
    return SymbolSpec(
        name=name,
        designator_prefix="U",
        part_count=3,
        pins=[SymPin(designator="1", name="OUT", x=400, y=0, orientation="right", part=1),
              SymPin(designator="2", name="IN-", x=0, y=100, orientation="left", part=1),
              SymPin(designator="8", name="V+", x=200, y=100, orientation="up", part=0)],
        graphics=[SymRect(x1=0, y1=-200, x2=400, y2=200)],
    )


def footprint_spec(name: str = "SOIC127P600X175-8N") -> FootprintSpec:
    return FootprintSpec(
        name=name, family="soic", ipc_name=name, height=1.75,
        pads=[Pad(designator=str(i), x=-2.475 if i <= 4 else 2.475, y=1.905 - ((i - 1) % 4) * 1.27, width=1.95, height=0.6)
              for i in range(1, 9)],
    )


def test_symbol_crud_and_status(workspace: Workspace) -> None:
    rec = registry.upsert_symbol(SymbolRecord(name="OPAMP_DUAL", library=r"Symbols\PF_ICs.SchLib", spec=symbol_spec(),
                                              kind="opamp_dual"))
    assert rec.pin_count == 3 and rec.part_count == 3 and rec.status == "pending" and rec.updated
    assert rec.spec is not None and rec.spec.pins[0].name == "OUT"
    again = registry.get_symbol("opamp_dual")
    assert again is not None and again.name == "OPAMP_DUAL" and again.spec == rec.spec
    ok = registry.set_symbol_status("OPAMP_DUAL", "ok")
    assert ok.status == "ok" and ok.status_message is None
    err = registry.set_symbol_status("opamp_dual", "error", "Datei gesperrt")
    assert err.status == "error" and err.status_message == "Datei gesperrt"
    with pytest.raises(KeyError):
        registry.set_symbol_status("NOPE", "ok")
    with pytest.raises(ValueError):
        registry.set_symbol_status("OPAMP_DUAL", "kaputt")  # type: ignore[arg-type]
    # upsert keeps the stored spelling and replaces the data
    updated = registry.upsert_symbol(SymbolRecord(name="opamp_dual", library=r"Symbols\Other.SchLib", status="ok"))
    assert updated.name == "OPAMP_DUAL" and updated.library == r"Symbols\Other.SchLib" and updated.spec is None
    assert [s.name for s in registry.list_symbols()] == ["OPAMP_DUAL"]
    assert registry.list_symbols(status="pending") == []
    assert registry.list_symbols(status=["ok", "error"])[0].name == "OPAMP_DUAL"
    assert registry.delete_symbol("Opamp_Dual") is True and registry.delete_symbol("OPAMP_DUAL") is False
    assert registry.get_symbol("OPAMP_DUAL") is None


def test_footprint_crud(workspace: Workspace) -> None:
    rec = registry.upsert_footprint(FootprintRecord(name="SOIC127P600X175-8N", library=r"Footprints\PF_SOIC.PcbLib",
                                                    spec=footprint_spec()))
    assert rec.pad_count == 8 and rec.family == "soic" and rec.height == 1.75 and rec.ipc_name == "SOIC127P600X175-8N"
    assert rec.spec is not None and rec.spec.pad_designators() == [str(i) for i in range(1, 9)]
    listed = registry.list_footprints(with_spec=False)
    assert listed[0].spec is None and listed[0].pad_count == 8
    assert registry.list_footprints(family="soic")[0].name == "SOIC127P600X175-8N"
    assert registry.list_footprints(family="qfn") == []
    assert registry.set_footprint_status("soic127p600x175-8n", "missing", "nicht in Datei").status == "missing"
    batch = registry.upsert_footprints([FootprintRecord(name="A", library="x"), FootprintRecord(name="B", library="y")])
    assert {f.name for f in batch} == {"A", "B"}
    assert registry.footprint_library_map()["a"] == "x"
    assert registry.delete_footprint("A") and not registry.delete_footprint("A")
    with pytest.raises(KeyError):
        registry.set_footprint_status("A", "ok")


def test_usage_counts_scan_all_tables(workspace: Workspace) -> None:
    registry.upsert_symbols([SymbolRecord(name="RES", library="s"), SymbolRecord(name="CAP", library="s")])
    registry.upsert_footprint(FootprintRecord(name="RESC1608X55N", library="f"))
    base = {"Manufacturer": "x", "Tolerance": "1", "Power": "0.1", "Library Ref": "RES"}
    parts.create_part("Resistors", {**base, "Part Number": "R1", "Manufacturer Part Number": "R1", "Resistance": "1k",
                                    "Footprint Ref": "RESC1608X55N", "Footprint Ref 2": "RESC1608X55L"})
    parts.create_part("Resistors", {**base, "Part Number": "R2", "Manufacturer Part Number": "R2", "Resistance": "2k",
                                    "Footprint Ref": "resc1608x55n"})
    parts.create_part("Capacitors", {"Part Number": "C1", "Manufacturer": "x", "Manufacturer Part Number": "C1",
                                     "Capacitance": "1n", "Voltage": "50", "Library Ref": "CAP", "Footprint Ref": "CAPC1608X87N"})
    assert registry.symbol_usage() == {"RES": 2, "CAP": 1}
    usage = registry.footprint_usage()
    assert usage == {"RESC1608X55N": 1, "resc1608x55n": 1, "RESC1608X55L": 1, "CAPC1608X87N": 1}
    symbols = {s.name: s.usage for s in registry.list_symbols()}
    assert symbols == {"CAP": 1, "RES": 2}
    assert registry.get_footprint("RESC1608X55N").usage == 2  # type: ignore[union-attr]  (case-insensitive)
    assert registry.list_symbols(with_usage=False)[0].usage == 0
    assert registry.counts()["symbols"]["by_status"]["pending"] == 2


def test_datasheets(workspace: Workspace) -> None:
    rec = DatasheetRecord(id="0123456789abcdef", file=r"Datasheets\0123456789abcdef.pdf", original_name="lm358.pdf",
                          title="LMx58 Op Amps", manufacturer="Texas Instruments", mpns=["LM358DR", "LM358PWR"],
                          page_count=42, text_pages=[1, 2, 3], extraction={"variants": [{"mpn": "LM358DR"}], "cost": 0.12})
    stored = registry.upsert_datasheet(rec)
    assert stored.created and stored.mpns == ["LM358DR", "LM358PWR"] and stored.extraction == rec.extraction
    again = registry.upsert_datasheet(rec.model_copy(update={"title": "Neu", "extraction": None}))
    assert again.title == "Neu" and again.extraction is None and again.created == stored.created
    assert [d.id for d in registry.list_datasheets()] == ["0123456789abcdef"]
    assert registry.get_datasheet("nope") is None
    assert registry.counts()["datasheets"] == 1
    assert registry.delete_datasheet("0123456789abcdef") and not registry.delete_datasheet("0123456789abcdef")


def test_invalid_stored_spec_is_ignored(workspace: Workspace) -> None:
    from sqlalchemy import update

    from partforge.db import core
    from partforge.db.schema import pf_symbols

    registry.upsert_symbol(SymbolRecord(name="BROKEN", library="x", spec=symbol_spec("BROKEN")))
    with core.connect() as conn:
        conn.execute(update(pf_symbols).where(pf_symbols.c.name == "BROKEN").values(spec='{"name": 5}', status="weird"))
    rec = registry.get_symbol("BROKEN")
    assert rec is not None and rec.spec is None and rec.status == "pending"
