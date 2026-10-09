"""Registry reads without loading every spec (perf-memory-registry) and the content hash / name record (K10)."""
from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select, update

from partforge.db import core, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.db.schema import pf_footprints, pf_symbols
from partforge.geometry.model import FootprintSpec, Pad, SymbolSpec, SymPin
from partforge.workspace import Workspace


def _symbol(name: str) -> SymbolSpec:
    return SymbolSpec(name=name, designator_prefix="R",
                      pins=[SymPin(designator="1", name="1", x=0, y=0, orientation="left"),
                            SymPin(designator="2", name="2", x=100, y=0, orientation="right")])


def _footprint(name: str) -> FootprintSpec:
    return FootprintSpec(name=name, family="chip", pads=[Pad(designator="1", x=-0.8, y=0, width=0.9, height=0.95),
                                                        Pad(designator="2", x=0.8, y=0, width=0.9, height=0.95)])


@pytest.fixture
def filled(workspace: Workspace) -> None:
    registry.upsert_symbols([SymbolRecord(name=f"SYM_{i}", library=r"Symbols\PF_A.SchLib" if i % 2 else
                                          r"Symbols\PF_B.SchLib", spec=_symbol(f"SYM_{i}")) for i in range(6)])
    registry.upsert_footprints([FootprintRecord(name=f"FP_{i}", library=r"Footprints\PF_CHIP.PcbLib",
                                                spec=_footprint(f"FP_{i}")) for i in range(4)])


def test_content_hash_is_the_hash_of_the_stored_spec_text(filled: None) -> None:
    with core.read() as conn:
        raw = conn.execute(select(pf_symbols.c.spec).where(pf_symbols.c.name == "SYM_1")).scalar_one()
    expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert registry.get_symbol("SYM_1").content_hash == expected  # type: ignore[union-attr]
    assert registry.list_symbols(names=["sym_1"])[0].content_hash == expected
    assert registry.content_hashes("symbol")["sym_1"] == expected
    assert registry.content_hashes("footprint", names=["FP_0"]).keys() == {"fp_0"}
    registry.upsert_symbol(SymbolRecord(name="NO_SPEC", library=r"Symbols\PF_A.SchLib"))
    assert registry.content_hashes("symbol")["no_spec"] is None


def test_light_lists_read_no_spec_and_filters_run_in_sql(filled: None) -> None:
    light = registry.list_symbols(with_spec=False, with_usage=False)
    assert len(light) == 6 and all(r.spec is None and r.content_hash is None for r in light)
    assert [r.name for r in registry.list_symbols(library=r"symbols\pf_a.schlib")] == ["SYM_1", "SYM_3", "SYM_5"]
    assert [r.name for r in registry.list_symbols(library="Symbols/PF_B.SchLib", with_spec=False)] == [
        "SYM_0", "SYM_2", "SYM_4"]
    assert [r.name for r in registry.list_footprints(names=["fp_1", "FP_3", "nope"])] == ["FP_1", "FP_3"]


def test_batch_upsert_returns_only_its_records(filled: None, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []
    real = registry.list_footprints

    def spy(**kwargs):  # noqa: ANN003, ANN202
        seen.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(registry, "list_footprints", spy)
    out = registry.upsert_footprints([FootprintRecord(name="FP_NEW", library=r"Footprints\PF_CHIP.PcbLib",
                                                      spec=_footprint("FP_NEW"))])
    assert [r.name for r in out] == ["FP_NEW"]
    assert seen and all(call.get("names") for call in seen)  # never a list of the whole registry


def test_older_specs_get_their_name_record_when_read(workspace: Workspace) -> None:
    from partforge.symbols import SymbolRequest, generate

    spec = generate(SymbolRequest(kind="resistor"))
    custom = spec.model_copy(update={"name": "MEIN_WIDERSTAND"})
    registry.upsert_symbol(SymbolRecord(name="MEIN_WIDERSTAND", library=r"Symbols\PF_Passives.SchLib", spec=custom))
    old_generator = {k: v for k, v in (custom.generator or {}).items() if k not in ("default_name", "name")}
    with core.connect() as conn:  # as an older version stored it: no name record
        stored = custom.model_copy(update={"generator": old_generator}).model_dump_json()
        conn.execute(update(pf_symbols).where(pf_symbols.c.name == "MEIN_WIDERSTAND").values(spec=stored))
    rec = registry.get_symbol("MEIN_WIDERSTAND")
    assert rec is not None and rec.spec is not None
    assert rec.spec.generator["name"] == "MEIN_WIDERSTAND" and rec.spec.generator["default_name"] == "Resistor"


def test_footprint_tables_have_no_spec_in_light_rows(filled: None) -> None:
    with core.read() as conn:
        assert conn.execute(select(pf_footprints.c.name)).all()
    assert all(r.spec is None for r in registry.list_footprints(with_spec=False, with_usage=False))
