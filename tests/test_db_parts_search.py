"""Parts search (perf-search-scan): in-memory index on SQLite, one query for page and total, numeric tokens
only where they belong – with the same results as before and as the Python fallback."""
from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from partforge.db import core, parts
from partforge.workspace import Workspace


def _res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "Yageo", "Resistance": value, "Tolerance": "1", "Power": "0.1",
            "Size": "0603", **kw}


@pytest.fixture
def many(workspace: Workspace) -> list[str]:
    rows = [_res(f"R-{i:04d}", f"{(i % 50) + 1}k") for i in range(400)]
    rows.append(_res("R-MILLI", "100m", Power="0.25"))
    return parts.upsert_parts("Resistors", rows, allow_incomplete=True).created


def _pns(**kw: Any) -> list[str]:
    return [str(r["Part Number"]) for r in parts.query_parts("Resistors", **kw)[0]]


def test_pages_and_totals_come_from_one_query(many: list[str]) -> None:
    rows, total = parts.query_parts("Resistors", search="10k", limit=3)
    assert total == 8 and len(rows) == 3  # 10k at i % 50 == 9
    rows2, total2 = parts.query_parts("Resistors", search="10k", offset=6, limit=3)
    assert total2 == 8 and len(rows2) == 2
    assert parts.query_parts("Resistors", search="10k", offset=50, limit=3) == ([], 8)
    assert parts.query_parts("Resistors", search="10k 0603", sort="-Part Number", limit=2)[1] == 8
    filtered = parts.query_parts("Resistors", search="10k", filters=[{"column": "Size", "op": "eq", "value": "0805"}])
    assert filtered == ([], 0)
    _, everything = parts.query_parts("Resistors", limit=5)
    assert everything == 401


def test_unitless_numbers_match_the_value_field_only(many: list[str]) -> None:
    assert _pns(search="100m") == ["R-MILLI"]  # 100 mΩ – not every part with 0.1 W
    assert len(_pns(search="100mW", limit=None)) == 400  # with unit: the power rating
    assert _pns(search="250mW") == ["R-MILLI"]
    assert set(_pns(search="0R1", limit=None)) == {"R-MILLI"}


def test_index_follows_every_change(many: list[str]) -> None:
    assert _pns(search="NEU-1") == []
    parts.create_part("Resistors", _res("NEU-1", "22k"), allow_incomplete=True)
    assert _pns(search="NEU-1") == ["NEU-1"]
    parts.update_part("Resistors", "NEU-1", {"Description": "Spezialwiderstand"})
    assert _pns(search="spezialwiderstand") == ["NEU-1"]
    parts.delete_parts("Resistors", ["NEU-1"])
    assert _pns(search="NEU-1") == []


def test_index_sees_writes_of_other_programs(many: list[str], workspace: Workspace) -> None:
    assert _pns(search="altium-edit") == []
    conn = sqlite3.connect(str(workspace.sqlite_path))  # e.g. Altium's table browser
    try:
        conn.execute("UPDATE \"Resistors\" SET \"Description\" = 'altium-edit' WHERE \"Part Number\" = 'R-0001'")
        conn.commit()
    finally:
        conn.close()
    assert _pns(search="altium-edit") == ["R-0001"]


def test_bulk_selection_matches_the_grid(many: list[str]) -> None:
    for kw in ({"search": "10k"}, {"search": "10k", "filters": [{"column": "Size", "op": "eq", "value": "0603"}]},
               {"search": "yageo 1k"}, {"search": "nichts"}):
        assert parts.matching_part_numbers("Resistors", **kw) == sorted(
            _pns(**kw, limit=None), key=lambda pn: (pn.casefold(), pn))


def test_library_paths_and_dates_are_not_searched(workspace: Workspace) -> None:
    parts.create_part("Resistors", _res("R-PATH", "1k", **{"Library Path": r"Symbols\PF_Spezial.SchLib"}),
                      allow_incomplete=True)
    assert _pns(search="PF_Spezial") == []
    assert _pns(filters=[{"column": "Library Path", "op": "contains", "value": "PF_Spezial"}]) == ["R-PATH"]
    assert "Library Path" not in parts.search_columns(parts.categories.get_category("Resistors"))


def test_python_fallback_gives_the_same_hits(many: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    queries = [{"search": "10k"}, {"search": "100m"}, {"search": "100mW"}, {"search": "yageo 7k"}]
    sqlite_results = [sorted(_pns(**q, limit=None)) for q in queries]
    monkeypatch.setattr(core.get_state(), "sql_functions", False)
    assert [sorted(_pns(**q, limit=None)) for q in queries] == sqlite_results
