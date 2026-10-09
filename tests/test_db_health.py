"""Data quality checks (health report)."""
from __future__ import annotations

import sqlite3
from typing import Any

from partforge.db import health, parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.workspace import Workspace


def res(pn: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "x", "Manufacturer Part Number": pn, "Resistance": "1k", "Tolerance": "1",
            "Power": "0.1", "Library Ref": "RES", "Footprint Ref": "RESC1608X55N", **kw}


def issues_of(report: dict[str, Any], check: str) -> list[dict[str, Any]]:
    return [i for i in report["issues"] if i["check"] == check]


def test_clean_library_has_no_problems(workspace: Workspace) -> None:
    report = health.health_report()
    assert report["total"] == 0 and report["issues"] == [] and not report["truncated"]
    assert report["counts"] == {"error": 0, "warning": 0, "info": 0}


def test_all_checks(workspace: Workspace) -> None:
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    lib.write_bytes(b"x")
    registry.upsert_symbol(SymbolRecord(name="RES", library=r"Symbols\PF_Passives.SchLib", status="ok"))
    registry.upsert_symbol(SymbolRecord(name="CAP", library=r"Symbols\PF_Passives.SchLib", status="ok"))
    registry.upsert_footprint(FootprintRecord(name="RESC1608X55N", library=r"Footprints\PF_CHIP.PcbLib", status="error",
                                              status_message="Rust-Writer fehlt"))
    registry.upsert_footprint(FootprintRecord(name="CAPC1608X87N", library=r"Footprints\PF_CHIP.PcbLib", status="pending"))
    registry.upsert_symbol(SymbolRecord(name="LOST", library=r"Symbols\x.SchLib", status="missing"))
    parts.create_part("Resistors", res("OK-1", ComponentLink1URL="https://example.com/r.pdf"))
    parts.create_part("Resistors", res("WARN-1", Tolerance="J", Technology="Kohle", **{"Library Ref": "UNKNOWN_SYM"}))
    parts.create_part("Resistors", {**res("GAP-1"), "Footprint Ref": None}, allow_incomplete=True)
    parts.create_part("Capacitors", {"Part Number": "C-DUP", "Manufacturer": "x", "Manufacturer Part Number": "ok-1",
                                     "Capacitance": "1n", "Voltage": "50", "Library Ref": "CAP",
                                     "Footprint Ref": "CAPC1608X87N", "Footprint Path": r"Footprints\PF_CHIP.PcbLib"})
    conn = sqlite3.connect(str(workspace.sqlite_path))  # edits made outside PartForge (e.g. Altium table browser)
    try:
        conn.execute('INSERT INTO "Capacitors" ("Part Number", "Manufacturer", "Manufacturer Part Number", "Capacitance", '
                     '"Voltage", "Description", "Library Ref", "Footprint Ref") '
                     "VALUES ('ok-1', 'x', 'Z', '100n', '50 V', 'd', 'CAP', 'CAPC1608X87N')")
        conn.commit()
    finally:
        conn.close()
    report = health.health_report()
    by_check = {k: v for k, v in report["summary"].items()}
    assert by_check["required"] == 1 and issues_of(report, "required")[0]["column"] == "Footprint Ref"
    assert issues_of(report, "required")[0]["severity"] == "error"
    dup_pn = issues_of(report, "duplicate_pn")
    assert len(dup_pn) == 1 and dup_pn[0]["severity"] == "error" and "OK-1" in dup_pn[0]["message"]
    dup_mpn = issues_of(report, "duplicate_mpn")
    assert {i["part_number"] for i in dup_mpn} == {"OK-1", "C-DUP"}
    value = issues_of(report, "value")
    assert [(i["part_number"], i["column"]) for i in value] == [("WARN-1", "Tolerance")]
    fmt = issues_of(report, "format")
    assert {(i["part_number"], i["column"]) for i in fmt} == {("ok-1", "Capacitance"), ("ok-1", "Voltage")}
    assert issues_of(report, "enum")[0]["part_number"] == "WARN-1" and issues_of(report, "enum")[0]["severity"] == "info"
    sym_missing = issues_of(report, "symbol_missing")
    assert [i["part_number"] for i in sym_missing] == ["WARN-1"]
    assert not issues_of(report, "footprint_missing")
    files = issues_of(report, "library_file_missing")
    assert {i["part_number"] for i in files} == {"OK-1", "WARN-1"}  # PF_CHIP.PcbLib does not exist; GAP-1 has no footprint
    assert all(i["column"] == "Footprint Path" for i in files)  # pending footprints (C-DUP) are skipped
    assert {i["part_number"] for i in issues_of(report, "datasheet_missing")} == {"WARN-1", "GAP-1", "C-DUP", "ok-1"}
    registry_issues = issues_of(report, "registry_error") + issues_of(report, "registry_missing")
    assert {i["message"].split("„")[1].split("“")[0] for i in registry_issues} == {"RESC1608X55N", "LOST"}
    assert report["issues"][0]["severity"] == "error"
    assert all(i["fix_hint"] for i in report["issues"])
    assert report["counts"]["error"] == 2 and report["total"] == sum(report["summary"].values())

    limited = health.health_report(max_per_check=1)
    assert limited["truncated"] and len(issues_of(limited, "datasheet_missing")) == 1
    assert limited["summary"] == report["summary"] and limited["counts"] == report["counts"]
    assert len(health.check_database()) == report["total"]


def test_jumpers_do_not_need_tolerance_tcr_power_or_voltage(workspace: Workspace) -> None:
    """A 0-Ω jumper is rated by its maximum resistance and rated current (datasheets: Vishay "Jumper, Imax",
    Panasonic "For Jumper", UNI-ROYAL "Rated Current of Jumper"): tolerance, TCR, power and voltage do not
    apply – not even when the user made them required."""
    from partforge.db import categories

    categories.update_field("Resistors", "TCR", {"required": True})
    categories.update_field("Resistors", "Voltage", {"required": True})
    jumper = {**res("JUMPER-0603", Resistance="0", Notes="0-Ω-Brücke (Jumper) ≤ 20 mΩ, Nennstrom 2A"),
              "Tolerance": None, "Power": None}
    parts.create_part("Resistors", jumper, allow_incomplete=True)
    parts.create_part("Resistors", {**res("ZERO-R", Resistance="0R"), "Tolerance": None, "Power": None},
                      allow_incomplete=True)
    report = health.health_report()
    assert not issues_of(report, "required"), issues_of(report, "required")
    # a resistor with a value still needs them
    parts.create_part("Resistors", {**res("R-1K"), "Tolerance": None}, allow_incomplete=True)
    required = issues_of(health.health_report(), "required")
    assert {(i["part_number"], i["column"]) for i in required} == {
        ("R-1K", "Tolerance"), ("R-1K", "TCR"), ("R-1K", "Voltage")}


def test_jumper_still_needs_the_fields_that_apply(workspace: Workspace) -> None:
    parts.create_part("Resistors", {**res("JUMPER-X", Resistance="0Ω"), "Tolerance": None, "Power": None,
                                    "Footprint Ref": None}, allow_incomplete=True)
    required = issues_of(health.health_report(), "required")
    assert [(i["part_number"], i["column"]) for i in required] == [("JUMPER-X", "Footprint Ref")]


def test_asymmetric_tcr_band_is_a_valid_value(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("R-0201-4R7", Resistance="4.7", TCR="-100~+350ppm/℃"))
    stored = parts.get_part("Resistors", "R-0201-4R7")
    assert stored is not None and stored["TCR"] == "-100 … +350ppm/K"
    conn = sqlite3.connect(str(workspace.sqlite_path))  # a band typed elsewhere (Altium table browser, import)
    try:
        conn.execute('UPDATE "Resistors" SET "TCR" = \'+350/-100 ppm/K\' WHERE "Part Number" = \'R-0201-4R7\'')
        conn.commit()
    finally:
        conn.close()
    report = health.health_report()
    assert not issues_of(report, "value")
    fmt = issues_of(report, "format")
    assert [(i["column"], i["severity"]) for i in fmt] == [("TCR", "info")]
    assert "-100 … +350ppm/K" in fmt[0]["message"]
