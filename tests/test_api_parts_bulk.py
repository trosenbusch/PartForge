"""API: template preview, selections by filter (count, bulk update, delete), undo of a delete from the
change history, and date-aware filters (PF Created / PF Modified)."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from partforge.db import audit, categories, core
from partforge.db import parts as db_parts

TABLE = "Resistors"


def res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "YAGEO", "Manufacturer Part Number": pn, "Resistance": value,
            "Tolerance": "1", "Power": "0.1", "Size": "0603", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N", **kw}


def url(pn: str, suffix: str = "") -> str:
    return f"/api/parts/{TABLE}/{quote(pn, safe='')}{suffix}"


def set_bookkeeping(pn: str, **values: str) -> None:
    """Set PF Created/PF Modified directly (the API never accepts bookkeeping values)."""
    table = categories.table_for(categories.get_category(TABLE))
    columns = {k.replace("_", " "): v for k, v in values.items()}
    with core.connect() as conn:
        conn.execute(update(table).where(table.c["Part Number"] == pn).values(columns))


@pytest.fixture
def filled(client: TestClient) -> TestClient:
    for pn, value, size in (("R-10K", "10k", "0603"), ("R-4K7", "4k7", "0603"), ("R-1K", "1k", "0402"),
                            ("R-100", "100R", "0805")):
        r = client.post(f"/api/parts/{TABLE}", json={"values": res(pn, value, Size=size)})
        assert r.status_code == 201, r.text
    set_bookkeeping("R-10K", PF_Created="2026-01-15 08:00:00", PF_Modified="2026-03-01 12:00:00")
    set_bookkeeping("R-4K7", PF_Created="2026-02-01 00:00:00", PF_Modified="2026-03-01 23:59:59")
    set_bookkeeping("R-1K", PF_Created="2026-02-01 17:30:00", PF_Modified="2026-03-02 00:00:00")
    set_bookkeeping("R-100", PF_Created="2026-02-28T09:15:00", PF_Modified="2026-10-07")
    return client


def pns_for(client: TestClient, *filters: dict[str, Any], search: str | None = None) -> list[str]:
    body = {"filters": list(filters), "search": search, "limit": 0, "sort": [{"column": "Part Number"}]}
    r = client.post(f"/api/parts/{TABLE}/query", json=body)
    assert r.status_code == 200, r.text
    return [row["Part Number"] for row in r.json()["rows"]]


# --------------------------------------------------------------------------- template preview


def test_render_any_template(filled: TestClient) -> None:
    r = filled.post(f"/api/parts/{TABLE}/render-template",
                    json={"template": "R {Size} {Resistance:rkm} {Tolerance} ({Value}) {Gibtsnicht}",
                          "values": {"Resistance": "4k7", "Size": "0402", "Tolerance": "5"}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["text"] == "R 0402 4k7 ±5% (4.7kΩ)"  # value normalised, Value generated, empty token dropped
    assert out["fields"] == ["Size", "Resistance", "Tolerance", "Value", "Gibtsnicht"]
    assert out["unknown"] == ["Gibtsnicht"]
    empty = filled.post(f"/api/parts/{TABLE}/render-template", json={"template": "", "values": {}}).json()
    assert empty == {"text": "", "fields": [], "unknown": []}
    assert filled.post("/api/parts/Gibtsnicht/render-template", json={"template": "{Value}"}).status_code == 404


# --------------------------------------------------------------------------- selections


def test_count_and_bulk_update_by_filter(filled: TestClient) -> None:
    flt = [{"column": "Size", "op": "eq", "value": "0603"}]
    count = filled.post(f"/api/parts/{TABLE}/count", json={"filters": flt}).json()
    assert count == {"count": 2, "total": 4, "whole_category": False, "part_numbers": ["R-10K", "R-4K7"]}
    r = filled.post(f"/api/parts/{TABLE}/bulk-update",
                    json={"filters": flt, "expected_count": 2, "values": {"Tolerance": "5"}})
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == 2 and r.json()["matched"] == 2
    assert {pn: filled.get(url(pn)).json()["Tolerance"] for pn in ("R-10K", "R-4K7", "R-1K")} == {
        "R-10K": "±5%", "R-4K7": "±5%", "R-1K": "±1%"}
    # search instead of filters, without expected_count
    r = filled.post(f"/api/parts/{TABLE}/bulk-update", json={"search": "R-100", "values": {"Notes": "geprüft"}})
    body = r.json()
    assert {k: body[k] for k in ("updated", "warnings", "matched", "backup")} == {
        "updated": 1, "warnings": [], "matched": 1, "backup": None}  # 1 part: no automatic backup
    assert len(body["audit_ids"]) == 1  # undo handle (POST /parts/{table}/restore-updates)
    # explicit part numbers keep working (matched stays None)
    r = filled.post(f"/api/parts/{TABLE}/bulk-update", json={"part_numbers": ["R-1K"], "values": {"Notes": "x"}})
    assert r.json()["updated"] == 1 and r.json()["matched"] is None


def test_selection_safety(filled: TestClient) -> None:
    flt = [{"column": "Size", "op": "eq", "value": "0603"}]
    stale = filled.post(f"/api/parts/{TABLE}/bulk-update",
                        json={"filters": flt, "expected_count": 3, "values": {"Notes": "x"}})
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "selection_changed" and detail["count"] == 2 and detail["expected"] == 3
    assert "2 statt 3" in detail["message"]
    whole = filled.post(f"/api/parts/{TABLE}/bulk-update", json={"values": {"Notes": "x"}})
    assert whole.status_code == 400 and "alle 4 Bauteile" in whole.json()["detail"]
    confirmed = filled.post(f"/api/parts/{TABLE}/bulk-update", json={"values": {"Notes": "x"}, "expected_count": 4})
    assert confirmed.json()["updated"] == 4
    assert filled.post(f"/api/parts/{TABLE}/count", json={}).json()["whole_category"] is True
    both = filled.post(f"/api/parts/{TABLE}/bulk-update",
                       json={"part_numbers": ["R-1K"], "filters": flt, "values": {"Notes": "y"}})
    assert both.status_code == 400 and "nicht beides" in both.json()["detail"]
    bad = filled.post(f"/api/parts/{TABLE}/count", json={"filters": [{"column": "Nope", "op": "eq", "value": 1}]})
    assert bad.status_code == 400
    assert filled.post("/api/parts/Gibtsnicht/count", json={}).status_code == 404
    # nothing was changed by the refused requests
    assert all(filled.get(url(pn)).json()["Notes"] == "x" for pn in ("R-10K", "R-4K7", "R-1K", "R-100"))


def test_delete_by_filter_and_undo(filled: TestClient) -> None:
    before = {pn: filled.get(url(pn)).json() for pn in ("R-10K", "R-4K7")}
    flt = [{"column": "Size", "op": "eq", "value": "0603"}]
    r = filled.request("DELETE", f"/api/parts/{TABLE}", json={"filters": flt, "expected_count": 2})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["deleted"] == 2 and out["matched"] == 2 and sorted(out["part_numbers"]) == ["R-10K", "R-4K7"]
    assert filled.get(url("R-10K")).status_code == 404
    undo = filled.post(f"/api/parts/{TABLE}/restore", json={"part_numbers": out["part_numbers"] + ["NIE-DA"]})
    assert undo.status_code == 200, undo.text
    restored = undo.json()
    assert sorted(restored["restored"]) == ["R-10K", "R-4K7"] and restored["not_found"] == ["NIE-DA"]
    assert restored["conflicts"] == {} and len(restored["parts"]) == 2
    for pn, old in before.items():
        now = filled.get(url(pn)).json()
        assert {k: v for k, v in now.items() if k not in ("PF Modified", "PF Author")} == {
            k: v for k, v in old.items() if k not in ("PF Modified", "PF Author")}
    history = filled.get(url("R-10K", "/history")).json()
    assert [e["action"] for e in history][:2] == ["restore", "delete"]
    # a second undo: the parts exist again
    again = filled.post(f"/api/parts/{TABLE}/restore", json={"part_numbers": ["R-10K"]}).json()
    assert again["restored"] == [] and "wieder vergeben" in again["conflicts"]["R-10K"]


def test_restore_refuses_a_part_number_taken_meanwhile(filled: TestClient) -> None:
    filled.request("DELETE", f"/api/parts/{TABLE}", json={"part_numbers": ["R-1K"]})
    cap = {"Part Number": "R-1K", "Manufacturer": "Murata", "Manufacturer Part Number": "R-1K", "Capacitance": "1n",
           "Voltage": "50", "Library Ref": "CAP", "Footprint Ref": "CAPC1608X87N"}
    assert filled.post("/api/parts/Capacitors", json={"values": cap}).status_code == 201
    out = filled.post(f"/api/parts/{TABLE}/restore", json={"part_numbers": ["r-1k"]}).json()
    assert out["restored"] == [] and "Capacitors" in out["conflicts"]["r-1k"]


def test_restore_after_field_removal_and_latest_deletion(filled: TestClient) -> None:
    filled.patch(url("R-100"), json={"values": {"Notes": "erste"}})
    filled.request("DELETE", f"/api/parts/{TABLE}", json={"part_numbers": ["R-100"]})
    filled.post(f"/api/parts/{TABLE}/restore", json={"part_numbers": ["R-100"]})
    filled.patch(url("R-100"), json={"values": {"Notes": "zweite"}})
    filled.request("DELETE", f"/api/parts/{TABLE}", json={"part_numbers": ["R-100"]})
    categories.remove_field(TABLE, "TCR")  # the deleted row has no TCR: nothing dropped
    out = db_parts.restore_parts(TABLE, ["R-100"])
    assert out["restored"] == ["R-100"] and out["warnings"] == []
    assert db_parts.get_part(TABLE, "R-100")["Notes"] == "zweite"  # the newest deletion wins


def test_restore_reports_values_of_removed_fields(filled: TestClient) -> None:
    filled.patch(url("R-4K7"), json={"values": {"TCR": "100"}})
    filled.request("DELETE", f"/api/parts/{TABLE}", json={"part_numbers": ["R-4K7"]})
    categories.remove_field(TABLE, "TCR")
    out = filled.post(f"/api/parts/{TABLE}/restore", json={"part_numbers": ["R-4K7"]}).json()
    assert out["restored"] == ["R-4K7"] and "TCR" in out["warnings"][0]


def test_delete_answers_part_numbers_for_undo_with_explicit_list(filled: TestClient) -> None:
    r = filled.post(f"/api/parts/{TABLE}/delete", json={"part_numbers": ["r-100", "nope"]})
    assert r.json()["part_numbers"] == ["R-100"] and r.json()["deleted"] == 1  # stored spelling
    assert audit.history(TABLE, "R-100")[0].action == "delete"


# --------------------------------------------------------------------------- date filters


@pytest.mark.parametrize(("flt", "expected"), [
    ({"column": "PF Created", "op": "before", "value": "2026-02-01"}, ["R-10K"]),
    ({"column": "PF Created", "op": "after", "value": "2026-02-01"}, ["R-100"]),
    ({"column": "PF Created", "op": "between", "value": ["2026-02-01", "2026-02-28"]}, ["R-100", "R-1K", "R-4K7"]),
    ({"column": "PF Created", "op": "between", "value": ["01.02.2026", None]}, ["R-100", "R-1K", "R-4K7"]),
    ({"column": "PF Created", "op": "between", "value": {"to": "2026-02-01"}}, ["R-10K", "R-1K", "R-4K7"]),
    ({"column": "PF Created", "op": "eq", "value": "2026-02-01"}, ["R-1K", "R-4K7"]),
    ({"column": "PF Created", "op": "ne", "value": "2026-02-01"}, ["R-100", "R-10K"]),
    ({"column": "PF Created", "op": "before", "value": "2026-02-01 17:30"}, ["R-10K", "R-4K7"]),
    ({"column": "PF Created", "op": "after", "value": "2026-02-01 17:29"}, ["R-100", "R-1K"]),
    ({"column": "PF Modified", "op": "eq", "value": "01.03.2026"}, ["R-10K", "R-4K7"]),
    ({"column": "PF Modified", "op": "le", "value": "2026-03-01"}, ["R-10K", "R-4K7"]),
    ({"column": "PF Modified", "op": "lt", "value": "2026-03-02"}, ["R-10K", "R-4K7"]),
    ({"column": "PF Modified", "op": "ge", "value": "2026-03-02"}, ["R-100", "R-1K"]),
    ({"column": "PF Modified", "op": "gt", "value": "2026-03-02"}, ["R-100"]),
    ({"column": "PF Modified", "op": "after", "value": "2026-10-06"}, ["R-100"]),  # plain date cell
    ({"column": "PF Modified", "op": "in", "value": ["2026-03-02", "2026-10-07"]}, ["R-100", "R-1K"]),
    ({"column": "Resistance", "op": "between", "value": ["1k", "10k"]}, ["R-10K", "R-1K", "R-4K7"]),
    ({"column": "Resistance", "op": "between", "value": [None, "1k"]}, ["R-100", "R-1K"]),
])
def test_date_aware_filters(filled: TestClient, flt: dict[str, Any], expected: list[str]) -> None:
    assert pns_for(filled, flt) == expected


def test_date_filters_in_the_python_fallback(filled: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgreSQL path (no SQL functions): the Python predicates give the same answers."""
    cases = [
        ({"column": "PF Created", "op": "between", "value": ["2026-02-01", "2026-02-28"]}, ["R-100", "R-1K", "R-4K7"]),
        ({"column": "PF Modified", "op": "eq", "value": "2026-03-01"}, ["R-10K", "R-4K7"]),
        ({"column": "PF Created", "op": "after", "value": "2026-02-01 17:29"}, ["R-100", "R-1K"]),
        ({"column": "Resistance", "op": "between", "value": ["1k", "10k"]}, ["R-10K", "R-1K", "R-4K7"]),
    ]
    sql = [pns_for(filled, flt) for flt, _ in cases]
    monkeypatch.setattr(core, "sql_functions_enabled", lambda: False)
    assert [pns_for(filled, flt) for flt, _ in cases] == sql == [expected for _, expected in cases]
    assert db_parts.matching_part_numbers(TABLE, filters=[cases[0][0]]) == ["R-100", "R-1K", "R-4K7"]


def test_date_filter_errors_are_400(filled: TestClient) -> None:
    def status(flt: dict[str, Any]) -> tuple[int, str]:
        r = filled.get(f"/api/parts/{TABLE}", params={"filters": json.dumps([flt])})
        return r.status_code, str(r.json().get("detail"))

    code, text = status({"column": "PF Created", "op": "before", "value": "gestern"})
    assert code == 400 and "kein gültiges Datum" in text
    code, text = status({"column": "Notes", "op": "after", "value": "2026-01-01"})
    assert code == 400 and "nur für Datumsfelder" in text
    code, text = status({"column": "PF Created", "op": "between", "value": "2026-01-01"})
    assert code == 400 and "zwei Werte" in text
    code, text = status({"column": "PF Created", "op": "between", "value": [None, ""]})
    assert code == 400 and "fehlen beide" in text
    code, text = status({"column": "Resistance", "op": "between", "value": ["abc", "1k"]})
    assert code == 400 and "kein Wert" in text
    # a non-date value on a date field keeps the text comparison (no error)
    assert status({"column": "PF Created", "op": "eq", "value": "unbekannt"})[0] == 200


def test_date_filter_in_saved_view_and_count(filled: TestClient) -> None:
    flt = {"column": "PF Modified", "op": "before", "value": "2026-03-02"}
    view = filled.post("/api/views", json={"name": "Alt", "table": TABLE, "filters": [flt]})
    assert view.status_code == 201 and view.json()["filters"][0]["op"] == "before"
    count = filled.post(f"/api/parts/{TABLE}/count", json={"filters": [flt]}).json()
    assert count["count"] == 2 and count["part_numbers"] == ["R-10K", "R-4K7"]
