"""Import: per-row result of the current mapping (dry run in the preview), strict mode and the
outcome of the import job."""
from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.db import parts as db_parts
from partforge.importers import spreadsheet

HEADER = "Teilenummer;Hersteller;MPN;Widerstand;Toleranz;Leistung;Symbol;Footprint;Beschreibung\r\n"


def line(pn: str, value: str, *, tol: str = "1%", power: str = "0,1W", mpn: str | None = None) -> str:
    return f"{pn};YAGEO;{mpn if mpn is not None else pn};{value};{tol};{power};RES;RESC1608X55N;Widerstand {pn}\r\n"


def upload(client: TestClient, text: str, **data: str) -> dict[str, Any]:
    files = {"file": ("liste.csv", text.encode("cp1252"), "text/csv")}
    r = client.post("/api/import/preview", files=files, data={"table": "Resistors", **data})
    assert r.status_code == 200, r.text
    return r.json()


def repreview(client: TestClient, prev: dict[str, Any], **body: Any) -> dict[str, Any]:
    r = client.post(f"/api/import/preview/{prev['token']}", json={"table": "Resistors", **body})
    assert r.status_code == 200, r.text
    return r.json()


def wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("Job wurde nicht fertig")


@pytest.fixture
def existing(client: TestClient) -> TestClient:
    values = {"Part Number": "R-OLD", "Manufacturer": "YAGEO", "Manufacturer Part Number": "R-OLD", "Resistance": "1k",
              "Tolerance": "1", "Power": "0.1", "Description": "alt", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}
    assert client.post("/api/parts/Resistors", json={"values": values}).status_code == 201
    cap = {"Part Number": "C-OTHER", "Manufacturer": "Murata", "Manufacturer Part Number": "C-OTHER",
           "Capacitance": "1n", "Voltage": "50", "Description": "x", "Library Ref": "CAP", "Footprint Ref": "CAPC1608X87N"}
    assert client.post("/api/parts/Capacitors", json={"values": cap}).status_code == 201
    return client


def test_upload_preview_reports_the_result_per_row(existing: TestClient) -> None:
    text = (HEADER + line("R-NEW", "10k") + line("R-OLD", "1k") + "\r\n" + line("C-OTHER", "1k")
            + line("R-NEW", "4k7") + line("R-BAD", "10k", tol="zehn"))
    prev = upload(existing, text)
    rows = prev["row_status"]
    assert [r["status"] for r in rows] == ["create", "skip", "reject", "reject", "create"]
    assert [r["row"] for r in rows] == [0, 1, 2, 3, 4]
    assert [r["line"] for r in rows] == [2, 3, 5, 6, 7]  # the empty sheet row 4 is skipped
    assert rows[1]["reasons"] and "übersprungen" in rows[1]["reasons"][0]
    assert rows[2]["conflict"] == {"table": "Capacitors", "part_number": "C-OTHER"} and "Capacitors" in rows[2]["reasons"][0]
    assert "doppelt" in rows[3]["reasons"][0] and "Zeile 1" in rows[3]["reasons"][0]
    assert any("Toleranz" in w for w in rows[4]["warnings"])  # unreadable value: only a warning by default
    check = prev["check"]
    assert check["counts"] == {"create": 2, "update": 0, "unchanged": 0, "skip": 1, "reject": 2}
    assert check["checked"] == check["total"] == 5 and check["truncated"] is False and check["mode"] == "skip"
    assert [s["status"] for s in prev["samples"]][:2] == ["neu", "vorhanden"]  # unchanged contract


def test_repreview_uses_the_current_mapping_mode_and_fixed_values(existing: TestClient) -> None:
    text = HEADER + line("R-NEW", "10k") + line("R-OLD", "2k2")
    prev = upload(existing, text)
    # mode update: the existing part would change (Resistance, Description)
    upd = repreview(existing, prev, mapping=prev["mapping"], mode="update")
    assert [r["status"] for r in upd["row_status"]] == ["create", "update"]
    assert set(upd["row_status"][1]["changed"]) >= {"Resistance", "Description"}
    assert upd["check"]["mode"] == "update"
    same = (HEADER + line("R-OLD", "1k")).replace("Widerstand R-OLD", "alt")
    unchanged = repreview(existing, upload(existing, same), mode="update")
    assert unchanged["row_status"][0]["status"] == "unchanged"
    err = repreview(existing, prev, mode="error")
    assert err["row_status"][1]["status"] == "reject"
    assert err["row_status"][1]["conflict"] == {"table": "Resistors", "part_number": "R-OLD"}
    # without the Resistance column: rejected – unless imported as draft, with the missing fields
    mapping = [{**m, "column": None} if m["column"] == "Resistance" else m for m in prev["mapping"]]
    draftless = repreview(existing, prev, mapping=mapping)
    first = draftless["row_status"][0]
    assert first["status"] == "reject" and first["errors"]["Resistance"] == "Pflichtfeld ist leer."
    assert first["reasons"] == ["Widerstand: Pflichtfeld ist leer."]
    assert next(m for m in draftless["mapping"] if m["header"] == "Widerstand")["column"] is None
    draft = repreview(existing, prev, mapping=mapping, allow_incomplete=True)
    assert draft["row_status"][0]["status"] == "create" and draft["row_status"][0]["missing"] == ["Widerstand"]
    # a fixed value fills the gap
    fixed = repreview(existing, prev, mapping=mapping, defaults={"Resistance": "47k"})
    assert fixed["row_status"][0]["status"] == "create"
    assert fixed["samples"][0]["values"]["Resistance"] == "47k"


def test_repreview_limits_the_dry_run_and_validates_the_mapping(existing: TestClient) -> None:
    text = HEADER + "".join(line(f"R-{i:03d}", "1k") for i in range(30))
    prev = upload(existing, text)
    limited = repreview(existing, prev, check_rows=10)
    assert len(limited["row_status"]) == 10
    assert limited["check"]["checked"] == 10 and limited["check"]["total"] == 30 and limited["check"]["truncated"]
    twice = [{**m, "column": "Resistance"} if m["header"] in ("Widerstand", "Toleranz") else m for m in prev["mapping"]]
    r = existing.post(f"/api/import/preview/{prev['token']}", json={"table": "Resistors", "mapping": twice})
    assert r.status_code == 400 and "mehreren Spalten" in r.json()["detail"]
    nothing = [{**m, "column": None} for m in prev["mapping"]]
    empty = repreview(existing, prev, mapping=nothing)
    assert empty["row_status"] == [] and empty["check"] is None and empty["samples"] == []


def test_strict_mode_rejects_unreadable_values(existing: TestClient) -> None:
    text = HEADER + line("R-OK", "10k") + line("R-TOL", "10k", tol="zehn") + line("R-W", "2,2V")
    prev = upload(existing, text)
    lax = repreview(existing, prev, mapping=prev["mapping"])
    assert [r["status"] for r in lax["row_status"]] == ["create", "create", "create"]
    strict = repreview(existing, prev, mapping=prev["mapping"], strict=True)
    assert [r["status"] for r in strict["row_status"]] == ["create", "reject", "reject"]
    assert "zehn" in strict["row_status"][1]["errors"]["Tolerance"]
    assert "Einheit" in strict["row_status"][2]["errors"]["Resistance"]
    assert strict["check"]["strict"] is True
    run = existing.post("/api/import/run", json={"token": prev["token"], "table": "Resistors", "mapping": prev["mapping"],
                                                 "strict": True})
    job = wait_for_job(existing, run.json()["job"]["id"])
    assert job["status"] == "done", job
    result = job["result"]
    assert result["created"] == 1 and result["error_count"] == 2 and result["outcome"] == "partial"
    assert result["strict"] is True and set(result["errors"]) == {"R-TOL", "R-W"}
    assert job["message"] == result["message"] == "Import fertig: 1 neu, 2 abgelehnt"
    assert db_parts.get_part("Resistors", "R-TOL") is None


def test_job_outcome_ok_and_failed(existing: TestClient) -> None:
    ok = upload(existing, HEADER + line("R-A", "1k"))
    job = wait_for_job(existing, existing.post("/api/import/run", json={
        "token": ok["token"], "table": "Resistors", "mapping": ok["mapping"]}).json()["job"]["id"])
    assert job["result"]["outcome"] == "ok" and job["result"]["error_count"] == 0
    assert job["message"] == "Import fertig: 1 neu"
    bad = upload(existing, HEADER + line("C-OTHER", "1k"))
    job = wait_for_job(existing, existing.post("/api/import/run", json={
        "token": bad["token"], "table": "Resistors", "mapping": bad["mapping"]}).json()["job"]["id"])
    assert job["status"] == "done" and job["result"]["outcome"] == "failed" and job["result"]["error_count"] == 1
    assert job["message"] == "Import fehlgeschlagen – nichts übernommen: 1 abgelehnt"


def test_outcome_rule() -> None:
    assert spreadsheet.import_outcome(0, 0) == "ok"
    assert spreadsheet.import_outcome(0, 5) == "ok"
    assert spreadsheet.import_outcome(2, 5) == "partial"
    assert spreadsheet.import_outcome(2, 0) == "failed"


def test_dry_run_with_internal_part_numbers(existing: TestClient, workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    text = "Hersteller;MPN;Widerstand;Toleranz;Leistung;Symbol;Footprint;Beschreibung\r\nYAGEO;RC1;1k;1%;0,1W;RES;RESC;x\r\n"
    prev = upload(existing, text)
    row = prev["row_status"][0]
    assert row["status"] == "create" and row["part_number"] is None
    assert row["warnings"][0] == db_parts.PN_ASSIGNED_ON_IMPORT
    # nothing was reserved: the import still gets the first number
    plan = db_parts.plan_upsert("Resistors", [{"Manufacturer": "YAGEO", "Manufacturer Part Number": "RC2",
                                               "Resistance": "2k", "Tolerance": "1", "Power": "0.1",
                                               "Description": "y", "Library Ref": "RES", "Footprint Ref": "RESC"}])
    assert plan[0].status == "create" and plan[0].part_number is None
    created = db_parts.upsert_parts("Resistors", [{"Manufacturer": "YAGEO", "Manufacturer Part Number": "RC3",
                                                   "Resistance": "3k", "Tolerance": "1", "Power": "0.1",
                                                   "Description": "z", "Library Ref": "RES", "Footprint Ref": "RESC"}])
    assert created.created == ["R-000001"]
