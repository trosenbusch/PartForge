"""Bulk upsert (series generator / import path): modes, errors, performance, jobs."""
from __future__ import annotations

import time
from typing import Any

import pytest

from partforge.db import parts
from partforge.jobs import JobCancelled, JobManager
from partforge.workspace import Workspace


def res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "Vishay", "Manufacturer Part Number": pn, "Resistance": value,
            "Tolerance": "1", "Power": "0.1", "Size": "0603", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N", **kw}


def test_modes_and_row_errors(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("U-1", "1k"))
    parts.create_part("Capacitors", {"Part Number": "OTHER-1", "Manufacturer": "x", "Manufacturer Part Number": "OTHER-1",
                                     "Capacitance": "1n", "Voltage": "50", "Library Ref": "CAP", "Footprint Ref": "C"})
    rows = [
        res("U-1", "1k"),            # exists -> skipped
        res("U-2", "2k"),            # new
        res("u-2", "2k2"),           # duplicate within the data
        res("other-1", "3k"),        # exists in another category
        res("U-3", "", Tolerance="J"),  # missing required value
        {**res("U-4", "4k7"), "Size": "9999"},  # enum warning only
        {**res("U-5", "5k"), "Unbekannt": "x"},  # unknown column
    ]
    result = parts.upsert_parts("Resistors", rows, mode="skip", author="Serie")
    assert result.created == ["U-2", "U-4"]
    assert result.skipped == ["U-1"]
    assert set(result.errors) == {"u-2", "other-1", "U-3", "U-5"}
    assert "doppelt" in result.errors["u-2"] and "Capacitors" in result.errors["other-1"]
    assert "Pflichtfeld" in result.errors["U-3"] and "Unbekannt" in result.errors["U-5"]
    assert any("Auswahlliste" in w for w in result.warnings["U-4"])
    assert parts.history("Resistors", "U-2")[0]["action"] == "import"
    assert parts.get_part("Resistors", "U-2")["PF Author"] == "Serie"  # type: ignore[index]

    error_mode = parts.upsert_parts("Resistors", [res("U-1", "1k"), res("U-6", "6k")], mode="error")
    assert error_mode.created == ["U-6"] and "existiert bereits" in error_mode.errors["U-1"]

    updated = parts.upsert_parts("Resistors", [
        {"Part Number": "u-1", "Tolerance": "5", "Resistance": ""},  # empty cells never erase data
        res("U-2", "2k"),  # identical -> unchanged
    ], mode="update")
    assert updated.updated == ["U-1"] and updated.unchanged == ["U-2"]
    row = parts.get_part("Resistors", "U-1")
    assert row and row["Tolerance"] == "±5%" and row["Resistance"] == "1kΩ"
    assert row["Description"] == "RES 0603 1kΩ ±5% 0.1W"
    with pytest.raises(ValueError, match="Modus"):
        parts.upsert_parts("Resistors", [], mode="replace")  # type: ignore[arg-type]
    empty = parts.upsert_parts("Resistors", [])
    assert empty.created == [] and empty.errors == {}


def test_rows_without_part_number(workspace: Workspace) -> None:
    result = parts.upsert_parts("Resistors", [{**res("", "1k"), "Part Number": None, "Manufacturer Part Number": "MPN-1"},
                                              {**res("", "2k"), "Part Number": None, "Manufacturer Part Number": None}])
    assert result.created == ["MPN-1"]
    assert "Zeile 2" in result.errors
    workspace.settings.part_number_scheme = "internal"
    internal = parts.upsert_parts("Resistors", [{**res("", "3k"), "Part Number": None, "Manufacturer Part Number": "X-3"},
                                                {**res("", "4k"), "Part Number": None, "Manufacturer Part Number": "X-4"}])
    assert internal.created == ["R-000001", "R-000002"]


def test_internal_numbers_avoid_explicit_numbers_in_batch(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    rows = [{**res("", "1k"), "Part Number": None, "Manufacturer Part Number": "A"},
            {**res("R-000001", "2k"), "Manufacturer Part Number": "B"}]  # explicit number the generator would pick
    result = parts.upsert_parts("Resistors", rows)
    assert not result.errors and sorted(result.created) == ["R-000001", "R-000002"]
    assert parts.get_part("Resistors", "R-000002")["Manufacturer Part Number"] == "A"  # type: ignore[index]
    start = time.perf_counter()
    many = parts.upsert_parts("Resistors", [{**res("", f"{i + 1}k"), "Part Number": None, "Manufacturer Part Number": f"M{i}"}
                                            for i in range(2000)])
    assert len(many.created) == 2000 and many.created[-1] == "R-002002"
    assert time.perf_counter() - start < 5.0


def test_update_keeps_stored_part_number_spelling(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("Case-1", "1k"))
    result = parts.upsert_parts("Resistors", [{"Part Number": "CASE-1", "Tolerance": "5"}], mode="update")
    assert result.updated == ["Case-1"]
    assert parts.get_part("Resistors", "Case-1")["Part Number"] == "Case-1"  # type: ignore[index]


def test_allow_incomplete(workspace: Workspace) -> None:
    rows = [{"Part Number": "INC-1", "Manufacturer": "x", "Manufacturer Part Number": "INC-1", "Resistance": "1k"}]
    assert parts.upsert_parts("Resistors", rows).errors
    result = parts.upsert_parts("Resistors", rows, allow_incomplete=True)
    assert result.created == ["INC-1"] and any("Pflichtfeld" in w for w in result.warnings["INC-1"])


def test_upsert_5000_rows_is_fast(workspace: Workspace) -> None:
    rows = [res(f"CRCW0603{i:05d}FKEA", f"{(i % 960) + 10}R{i % 10}", TCR="100") for i in range(5000)]
    start = time.perf_counter()
    result = parts.upsert_parts("Resistors", rows, mode="skip")
    elapsed = time.perf_counter() - start
    assert len(result.created) == 5000 and not result.errors
    assert elapsed < 5.0, f"5000 Zeilen dauerten {elapsed:.2f} s"
    assert parts.query_parts("Resistors", limit=1)[1] == 5000
    start = time.perf_counter()
    again = parts.upsert_parts("Resistors", rows, mode="update")
    assert len(again.unchanged) == 5000 and time.perf_counter() - start < 5.0
    start = time.perf_counter()
    rows_page, total = parts.query_parts("Resistors", search="100R", sort="-Resistance", limit=50)
    assert total > 0 and time.perf_counter() - start < 2.0
    assert rows_page[0]["Resistance"]


def test_upsert_as_job_with_progress_and_cancel(workspace: Workspace) -> None:
    manager = JobManager(max_workers=1)
    rows = [res(f"J-{i}", f"{i + 1}k") for i in range(300)]
    job = manager.run_sync("series", "Serie", lambda ctx: parts.upsert_parts("Resistors", rows, ctx=ctx).model_dump())
    assert job.status == "done" and len(job.result["created"]) == 300 and job.progress == 1.0

    class CancellingContext:
        def __init__(self) -> None:
            self.calls = 0

        def progress(self, fraction: float | None = None, message: str | None = None) -> None:
            pass

        def check_cancelled(self) -> None:
            self.calls += 1
            if self.calls > 1:
                raise JobCancelled()

    more = [res(f"K-{i}", f"{i + 1}k") for i in range(600)]
    with pytest.raises(JobCancelled):
        parts.upsert_parts("Resistors", more, ctx=CancellingContext())  # type: ignore[arg-type]
    assert parts.existing_part_numbers(["K-0", "K-599"]) == set()  # rolled back completely
