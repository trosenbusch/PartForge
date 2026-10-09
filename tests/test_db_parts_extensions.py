"""db layer: unreadable values (strict import), date parsing, the upsert planner (dry run == import)
and the helpers behind selections and undo."""
from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from partforge.db import parts
from partforge.db.models import FieldDef
from partforge.db.values import normalize_cell, parse_date

TABLE = "Resistors"


def res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "YAGEO", "Manufacturer Part Number": pn, "Resistance": value,
            "Tolerance": "1", "Power": "0.1", "Description": f"R {pn}", "Library Ref": "RES",
            "Footprint Ref": "RESC1608X55N", **kw}


@pytest.mark.parametrize(("field", "raw", "unreadable"), [
    (FieldDef(column="R", label="R", kind="quantity", unit="Ω"), "abc", True),
    (FieldDef(column="R", label="R", kind="quantity", unit="Ω"), "2,2V", True),  # wrong unit
    (FieldDef(column="R", label="R", kind="quantity", unit="Ω"), "4k7", False),
    (FieldDef(column="C", label="C", kind="quantity", unit="F"), "100", False),  # read (100F) with a prefix hint
    (FieldDef(column="T", label="T", kind="range", unit="°C"), "warm", True),
    (FieldDef(column="N", label="N", kind="int"), "2.5", True),
    (FieldDef(column="B", label="B", kind="bool"), "vielleicht", True),
    (FieldDef(column="D", label="D", kind="date"), "gestern", True),
    (FieldDef(column="D", label="D", kind="date"), "07.10.2026", False),
    (FieldDef(column="E", label="E", kind="enum", options=["SMD", "THT"]), "Press-Fit", False),  # free text allowed
    (FieldDef(column="U", label="U", kind="url"), "keine adresse", False),
])
def test_unreadable_flag(field: FieldDef, raw: str, unreadable: bool) -> None:
    res_ = normalize_cell(field, raw)
    assert res_.unreadable is unreadable
    if unreadable:
        assert res_.warning and res_.value == raw  # stored as typed, with a German warning


def test_parse_date_precision() -> None:
    assert parse_date("2026-10-07") == (dt.datetime(2026, 10, 7), "day")
    assert parse_date("07.10.2026 21:30") == (dt.datetime(2026, 10, 7, 21, 30), "minute")
    assert parse_date("2026-10-07T21:30:05") == (dt.datetime(2026, 10, 7, 21, 30, 5), "second")
    assert parse_date("2026-10-07T21:30:05+02:00") == (dt.datetime(2026, 10, 7, 21, 30, 5), "second")
    assert parse_date("7.10.26") == (dt.datetime(2026, 10, 7), "day")
    assert parse_date("gestern") is None and parse_date("") is None and parse_date(None) is None


def test_date_normalisation_is_unchanged() -> None:
    f = FieldDef(column="D", label="D", kind="date")
    assert normalize_cell(f, "07.10.2026").value == "2026-10-07"
    assert normalize_cell(f, "07.10.2026 21:30").value == "2026-10-07 21:30:00"
    assert normalize_cell(f, "2026-10-07T21:30:00").value == "2026-10-07 21:30:00"


def test_plan_matches_the_import(workspace) -> None:
    parts.create_part(TABLE, res("R-OLD", "1k"))
    parts.create_part("Capacitors", {"Part Number": "C-1", "Manufacturer": "M", "Manufacturer Part Number": "C-1",
                                     "Capacitance": "1n", "Voltage": "50", "Description": "c", "Library Ref": "CAP",
                                     "Footprint Ref": "CAPC"})
    rows = [res("R-NEW", "10k"), res("R-OLD", "2k2"), res("C-1", "1k"), res("R-NEW", "1k"),
            res("R-BAD", "10k", Tolerance="zehn"), {"Manufacturer": "YAGEO"}, res("R-OLD2", "1k")]
    for strict in (False, True):
        plans = parts.plan_upsert(TABLE, rows, mode="update", strict=strict)
        statuses = [p.status for p in plans]
        expected = ["create", "update", "reject", "reject", "reject" if strict else "create", "reject", "create"]
        assert statuses == expected, (strict, statuses)
    plans = parts.plan_upsert(TABLE, rows, mode="update")
    assert parts.get_part(TABLE, "R-NEW") is None  # the dry run wrote nothing
    result = parts.upsert_parts(TABLE, rows, mode="update")
    by_status: dict[str, list[str]] = {}
    for plan in plans:
        by_status.setdefault(plan.status, []).append(plan.label if plan.status == "reject" else str(plan.part_number))
    assert result.created == by_status["create"] and result.updated == by_status["update"]
    assert set(result.errors) == set(by_status["reject"])
    assert all(result.errors[p.label] == p.message for p in plans if p.status == "reject")
    second = parts.plan_upsert(TABLE, rows[:2], mode="update")
    assert [p.status for p in second] == ["unchanged", "unchanged"]
    assert [p.status for p in parts.plan_upsert(TABLE, rows[:2], mode="skip")] == ["skip", "skip"]


def test_plan_reports_field_errors_with_labels(workspace) -> None:
    plan = parts.plan_upsert(TABLE, [{"Part Number": "R-X", "Manufacturer": "Y"}])[0]
    assert plan.status == "reject" and "Resistance" in plan.errors
    assert "Widerstand: Pflichtfeld ist leer." in plan.reasons
    draft = parts.plan_upsert(TABLE, [{"Part Number": "R-X", "Manufacturer": "Y"}], allow_incomplete=True)[0]
    assert draft.status == "create" and "Widerstand" in draft.missing


def test_strict_upsert(workspace) -> None:
    result = parts.upsert_parts(TABLE, [res("R-S", "10k", Power="viel")], strict=True)
    assert result.created == [] and "Power" in result.errors["R-S"]
    lax = parts.upsert_parts(TABLE, [res("R-S", "10k", Power="viel")])
    assert lax.created == ["R-S"] and any("viel" in w for w in lax.warnings["R-S"])


def test_delete_collects_stored_part_numbers_and_restore(workspace) -> None:
    parts.create_part(TABLE, res("R-Del", "1k"))
    removed: list[str] = []
    assert parts.delete_parts(TABLE, ["r-del", "gibts-nicht"], deleted=removed) == 1
    assert removed == ["R-Del"]
    out = parts.restore_parts(TABLE, ["R-DEL"])  # any letter case
    assert out["restored"] == ["R-Del"] and out["parts"][0]["Resistance"] == "1kΩ"
    assert parts.get_part(TABLE, "R-Del")["Part Number"] == "R-Del"
    assert parts.restore_parts(TABLE, []) == {"restored": [], "parts": [], "conflicts": {}, "not_found": [],
                                               "warnings": []}


def test_matching_part_numbers_equals_query(workspace) -> None:
    for pn, value in (("R-1", "1k"), ("R-2", "2k2"), ("R-3", "10k")):
        parts.create_part(TABLE, res(pn, value))
    flt = [{"column": "Resistance", "op": "ge", "value": "2k"}]
    rows, total = parts.query_parts(TABLE, filters=flt, limit=None)
    assert parts.matching_part_numbers(TABLE, filters=flt) == sorted(r["Part Number"] for r in rows) == ["R-2", "R-3"]
    assert parts.matching_part_numbers(TABLE, search="R-1") == ["R-1"]
    assert parts.matching_part_numbers(TABLE) == ["R-1", "R-2", "R-3"]
