"""Regression tests of the October 2026 code review – data layer, API, settings, datasheet import, footprint
generators (the library-sync and Altium-bridge findings have their tests in ``test_sync_safety.py``,
``test_bridge_core.py``, ``test_altium_edit.py`` and ``test_library_temp_and_backups.py``)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import anthropic
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_datasheet_llm import ExtractionFailed, _status_error

from partforge import config
from partforge.api import routes_categories, routes_system
from partforge.db import backup, categories, mpn_templates, parts
from partforge.db.errors import DatabaseNotOpen
from partforge.datasheet import llm
from partforge.footprints import FootprintRequest, ParamError, generate, preview
from partforge.jobs import library_hold
from partforge.workspace import Workspace, set_current

ROOT = Path(__file__).resolve().parents[1]


def res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "Vishay", "Manufacturer Part Number": pn, "Resistance": value,
            "Tolerance": "1", "Power": "0.1", "Size": "0603", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N", **kw}


# --------------------------------------------------------------------------- spreadsheet import, scheme "internal"


def test_import_rows_without_part_number_find_their_part_by_mpn(workspace: Workspace) -> None:
    """A BOM or distributor export carries no internal numbers: re-importing it must update the parts instead of
    creating R-000003, R-000004 … with the same manufacturer part numbers."""
    workspace.settings.part_number_scheme = "internal"
    rows = [{**res("", "3k"), "Part Number": None, "Manufacturer Part Number": "X-3"},
            {**res("", "4k7"), "Part Number": None, "Manufacturer Part Number": "X-47"}]
    first = parts.upsert_parts("Resistors", rows)
    assert first.created == ["R-000001", "R-000002"]
    again = parts.upsert_parts("Resistors", [{**rows[0], "Resistance": "3k3"}, rows[1], rows[1]], mode="update")
    assert again.created == [] and again.updated == ["R-000001"] and again.unchanged == ["R-000002"]
    assert "R-000002" in again.errors and "doppelt" in again.errors["R-000002"]
    assert str(parts.get_part("Resistors", "R-000001")["Resistance"]).startswith("3.3k")  # type: ignore[index]
    assert not parts.get_part("Resistors", "R-000003")
    skipped = parts.upsert_parts("Resistors", rows, mode="skip")
    assert skipped.created == [] and skipped.skipped == ["R-000001", "R-000002"]
    # the dry run says the same (the file now carries the stored values)
    plan = parts.plan_upsert("Resistors", [{**rows[0], "Resistance": "3k3"}, rows[1]], mode="update")
    assert [p.status for p in plan] == ["unchanged", "unchanged"]
    assert [p.part_number for p in plan] == ["R-000001", "R-000002"]
    # two new rows of one manufacturer part number would become two parts: the second is rejected
    new = {**res("", "5k6"), "Part Number": None, "Manufacturer Part Number": "X-56"}
    third = parts.upsert_parts("Resistors", [new, {**new, "Resistance": "5k62"}])
    assert third.created == ["R-000003"] and "Hersteller-Teilenummer doppelt" in third.errors["Zeile 2"]


# --------------------------------------------------------------------------- backups


def test_backup_verification_handles_uri_characters_in_the_path(workspace: Workspace, tmp_path: Path) -> None:
    """The verification opens the backup as a SQLite URI: a folder "Projekt #12" must not truncate the path (and
    create a stray empty database at the truncated one)."""
    made = backup.backup_database("test")
    folder = tmp_path / "Projekt #12 (100%)"
    folder.mkdir()
    copy = folder / made.name
    shutil.copyfile(made, copy)
    backup._verify(copy)
    assert not (tmp_path / "Projekt ").exists() and sorted(p.name for p in folder.iterdir()) == [made.name]


# --------------------------------------------------------------------------- values


@pytest.mark.parametrize("raw", ["100", "±100", "100ppm/K", "±100ppm", "+/-100 ppm/K"])
def test_tcr_has_one_canonical_spelling(raw: str) -> None:
    """Temperature coefficients are relative values like tolerances: one spelling ("±100ppm/K") however the user
    typed it, so filters and distinct values do not show "100ppm/K" next to "±100ppm/K"."""
    from partforge.db.models import FieldDef
    from partforge.db.values import normalize_cell

    result = normalize_cell(FieldDef(column="TCR", label="TCR", kind="quantity", unit="ppm/K"), raw)
    assert result.error is None and result.value == "±100ppm/K"


# --------------------------------------------------------------------------- categories


def test_renaming_a_category_keeps_its_series_templates(workspace: Workspace) -> None:
    mpn_templates.save_mpn_template("meine-vorlage", "Meine Vorlage", {"pattern": "X{value}"}, category="Mechanical")
    categories.update_category("Mechanical", {"table": "Mechanics"})
    assert [t["key"] for t in mpn_templates.list_mpn_templates("Mechanics")] == ["meine-vorlage"]
    assert mpn_templates.list_mpn_templates("Mechanical") == []


# --------------------------------------------------------------------------- API


def test_health_never_carries_library_settings(client: TestClient, workspace: Workspace) -> None:
    """``/api/health`` needs no token: it must not hand the PostgreSQL connection string (with its password) to
    every local process."""
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["workspace"] == {"root": str(workspace.root), "name": workspace.settings.name}


def test_opening_a_library_with_an_invalid_partforge_json_is_a_clear_error(bare_client: TestClient, tmp_path: Path) -> None:
    ws = Workspace.create(tmp_path / "Kaputt", name="Kaputt")
    (ws.root / "partforge.json").write_text('{"name": "Kaputt", "part_number_scheme": "nope"}', encoding="utf-8")
    r = bare_client.post("/api/workspace/open", json={"path": str(ws.root)})
    assert r.status_code == 400, r.text
    assert "partforge.json" in r.json()["detail"] and "part_number_scheme" in r.json()["detail"]


def test_database_not_open_while_a_library_is_open_is_a_switch_notice(workspace: Workspace) -> None:
    """During a library switch or a backup restore a request meets a closed database: that must not read like
    "no library open" (the client would leave the library)."""
    with pytest.raises(HTTPException) as info, routes_categories.db_errors():
        raise DatabaseNotOpen()
    assert info.value.status_code == 409 and info.value.detail["code"] == "db_switching"  # type: ignore[index]
    set_current(None)
    try:
        with pytest.raises(HTTPException) as info, routes_categories.db_errors():
            raise DatabaseNotOpen()
        assert info.value.detail == "Es ist keine Bibliothek geöffnet."
    finally:
        set_current(workspace)


def test_a_refused_library_switch_keeps_the_running_job(bare_client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """Opening a library another PartForge holds is refused *before* the switch that would cancel the running jobs
    of the open library."""
    first = tmp_path / "Erste"
    r = bare_client.post("/api/workspace/create", json={"path": str(first), "name": "Erste", "with_examples": False})
    assert r.status_code == 200, r.text
    other = Workspace.create(tmp_path / "Andere", name="Andere")
    switches: list[str] = []
    real_switch = routes_system._library_switch

    @contextmanager
    def recording_switch():
        switches.append("entered")
        with real_switch():
            yield

    monkeypatch.setattr(routes_system, "_library_switch", recording_switch)
    blocker = subprocess.Popen(  # another PartForge holds the other library
        [sys.executable, "-c", textwrap.dedent("""
            import sys
            sys.path.insert(0, sys.argv[2])
            from partforge.workspace import lock_library
            lock_library(sys.argv[1])
            print("locked", flush=True)
            sys.stdin.readline()
        """), str(other.root), str(ROOT)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    holding, release = threading.Event(), threading.Event()

    def job() -> None:
        with library_hold(None, first):  # a running library job of the open library
            holding.set()
            release.wait(20)

    worker = threading.Thread(target=job, daemon=True)
    try:
        assert blocker.stdout is not None and blocker.stdout.readline().strip() == b"locked"
        worker.start()
        assert holding.wait(5)
        r = bare_client.post("/api/workspace/open", json={"path": str(other.root)})
        assert r.status_code == 409 and "anderen PartForge" in r.json()["detail"]
        assert switches == [] and worker.is_alive()  # the job was never cancelled
        assert bare_client.get("/api/workspace").json()["name"] == "Erste"
    finally:
        release.set()
        worker.join(5)
        if blocker.poll() is None:
            blocker.communicate(input=b"\n", timeout=10)
    bare_client.post("/api/workspace/close")


# --------------------------------------------------------------------------- settings


def test_settings_with_one_invalid_value_keep_the_rest(tmp_path: Path) -> None:
    """A single unknown value (an enum a newer version wrote, a typo in a hand-edited file) must not reset the
    library, the recent libraries and the Altium path."""
    path = config.settings_path()
    original = path.read_text(encoding="utf-8") if path.is_file() else None
    corrupt = path.with_suffix(".corrupt.json")
    data = {"workspace": str(tmp_path / "Lib"), "recent_workspaces": [str(tmp_path / "Lib")],
            "ai": {"effort": "max"}, "altium": {"x2_path": r"C:\Altium\X2.EXE"}}
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(data), encoding="utf-8")
        settings = config.load_settings(reload=True)
        assert settings.workspace == str(tmp_path / "Lib") and settings.recent_workspaces == [str(tmp_path / "Lib")]
        assert settings.altium.x2_path == r"C:\Altium\X2.EXE" and settings.ai.effort == "low"
        assert not corrupt.exists()
        path.write_text("{ kaputt", encoding="utf-8")
        assert config.load_settings(reload=True) == config.AppSettings() and corrupt.exists()
    finally:
        corrupt.unlink(missing_ok=True)
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(original, encoding="utf-8")
        config.load_settings(reload=True)


# --------------------------------------------------------------------------- datasheet import (Claude API errors)


def test_request_too_large_and_unprocessable_are_no_retry_hints() -> None:
    too_large = llm.map_sdk_error(_status_error(anthropic.RequestTooLargeError, 413), "claude-opus-5-5")
    assert isinstance(too_large, ExtractionFailed) and "weniger Seiten" in str(too_large)
    assert too_large.api_status == 413
    rejected = llm.map_sdk_error(_status_error(anthropic.UnprocessableEntityError, 422, "pages: too many"),
                                 "claude-opus-5-5")
    assert isinstance(rejected, ExtractionFailed) and "HTTP 422" in str(rejected) and "pages: too many" in rejected.api_message


# --------------------------------------------------------------------------- footprint generators


def test_manufacturer_pattern_says_that_the_tab_stays_ipc() -> None:
    """Vendor land patterns of SOT-223/DPAK cover the leads only: the tab is still calculated – said, not hidden."""
    sot = preview(FootprintRequest(family="sot223", land_pattern={"pad_width": 1.0, "pad_length": 2.0, "row_spacing": 6.4}),
                  svg=False)
    assert any("Kühlfahne" in w and "IPC-7351B" in w for w in sot.warnings)
    dpak = preview(FootprintRequest(family="dpak", land_pattern={"pad_width": 1.2, "pad_length": 2.3, "row_spacing": 7.6}),
                   svg=False)
    assert any("Kühlfahne" in w and "IPC-7351B" in w for w in dpak.warnings)
    assert not any("Kühlfahne" in w for w in preview(FootprintRequest(family="sot223"), svg=False).warnings)


def test_qfn_rows_too_long_for_the_body_get_a_specific_error() -> None:
    params = {"variant": "QFN", "pins": 48, "e": 0.5, "E": [6.7, 6.8], "D": [6.7, 6.8], "L": [0.395, 0.47],
              "b": [0.20, 0.31], "E2": 4.8, "D2": 4.8}
    with pytest.raises(ParamError, match="Eckpads"):
        generate(FootprintRequest(family="nolead", params=params))
    assert len(generate(FootprintRequest(family="nolead", params={"preset": "QFN-32-5x5-P0.5"})).pads) == 33
