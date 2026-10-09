"""Format of internal part numbers (INT-08): checked when saved and opened, every generated number checked.

A format without ``{counter}`` used to hang every database write (endless search for a free number inside
the process-wide write transaction); literal characters produced part numbers that manual entry forbids
(``R'1``, ``R|002``) or that carry blanks at the edges.
"""
from __future__ import annotations

import json
import threading

import pytest

from partforge.db import parts
from partforge.db.errors import DbError
from partforge.workspace import DEFAULT_PN_FORMAT, Workspace, pn_format_problem


@pytest.mark.parametrize("fmt", ["{prefix}-{counter:06d}", "{prefix}{counter:04d}-{table}", "{table}/{counter}",
                                 "PF-{counter:05d}", "{prefix}_{counter:03d}", "{counter}"])
def test_valid_formats(fmt: str) -> None:
    assert pn_format_problem(fmt) is None


@pytest.mark.parametrize(("fmt", "words"), [
    ("{prefix}-FIX", "{counter}"),
    ("{prefix}-{counter}-{counter}", "genau einmal"),
    ("", "leer"),
    ("{prefix}'{counter}", "unzulässige Zeichen"),
    ("{prefix}|{counter:03d}", "unzulässige Zeichen"),
    ("{prefix}{{{counter}}}", "unzulässige Zeichen"),
    ("{prefix} {counter} ", "Leerzeichen"),
    ("{prefix}\t{counter}", "Leerzeichen"),
    ("{prefix:>4}-{counter}", "Leerzeichen"),
    ("{prefix}-{nummer}", "Platzhalter"),
    ("{prefix}-{0}-{counter}", "Platzhalter"),
    ("{prefix}-{counter", "Klammer"),
    ("{prefix}-{counter:s}", "nicht anwenden"),
])
def test_invalid_formats(fmt: str, words: str) -> None:
    problem = pn_format_problem(fmt)
    assert problem is not None and words.lower() in problem.lower(), problem


def test_api_refuses_invalid_format(client) -> None:  # noqa: ANN001 - fixture
    settings = client.get("/api/workspace").json()["settings"]
    settings["part_number_scheme"] = "internal"
    settings["internal_pn_format"] = "{prefix}-FIX"
    r = client.put("/api/workspace/settings", json=settings)
    assert r.status_code == 400 and "{counter}" in r.json()["detail"]
    settings["internal_pn_format"] = "{prefix}'{counter}"
    assert client.put("/api/workspace/settings", json=settings).status_code == 400
    settings["internal_pn_format"] = "{prefix}{counter:04d}"
    assert client.put("/api/workspace/settings", json=settings).status_code == 200


def test_open_replaces_a_hand_edited_invalid_format(tmp_path) -> None:  # noqa: ANN001 - fixture
    ws = Workspace.create(tmp_path / "lib")
    cfg = ws.root / "partforge.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["internal_pn_format"] = "{prefix}-FIX"
    cfg.write_text(json.dumps(data), encoding="utf-8")
    opened = Workspace.open(ws.root)
    assert opened.settings.internal_pn_format == DEFAULT_PN_FORMAT
    assert opened.pn_format_warning and "{counter}" in opened.pn_format_warning
    assert opened.info()["warnings"] == [opened.pn_format_warning]
    assert json.loads(cfg.read_text(encoding="utf-8"))["internal_pn_format"] == "{prefix}-FIX"  # file untouched


def test_generation_never_hangs_and_never_writes_forbidden_numbers(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    workspace.settings.internal_pn_format = "{prefix}-FIX"  # bypassing the checks (e.g. set in code)
    errors: list[BaseException] = []

    def create() -> None:
        try:
            parts.create_part("Resistors", {"Manufacturer": "QA", "Resistance": "1k"}, allow_incomplete=True)
        except BaseException as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    worker = threading.Thread(target=create, daemon=True)
    worker.start()
    worker.join(10)
    assert not worker.is_alive(), "Teilenummernvergabe hängt"
    assert errors and isinstance(errors[0], DbError) and "{counter}" in str(errors[0])
    # an unrelated write still works (the write lock is free)
    parts.create_part("Capacitors", {"Part Number": "OTHER-1", "Capacitance": "1n"}, allow_incomplete=True)
    workspace.settings.internal_pn_format = "{prefix}'{counter}"
    with pytest.raises(DbError):
        parts.create_part("Resistors", {"Manufacturer": "QA", "Resistance": "1k"}, allow_incomplete=True)
    assert parts.get_part("Resistors", "R'1") is None


def test_generation_skips_taken_numbers_within_bounds(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    parts.create_part("Resistors", {"Part Number": "R-000001", "Resistance": "1k"}, allow_incomplete=True)
    parts.create_part("Resistors", {"Part Number": "r-000002", "Resistance": "1k"}, allow_incomplete=True)
    made = parts.create_part("Resistors", {"Manufacturer": "QA", "Resistance": "1k"}, allow_incomplete=True)
    assert made["Part Number"] == "R-000003"
