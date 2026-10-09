"""Parts: CRUD, normalisation, templates, uniqueness, audit/history and quantity-aware queries."""
from __future__ import annotations

from typing import Any

import pytest

from partforge.db import audit, backup, categories, core, parts, registry
from partforge.db.errors import DuplicatePartError, FieldNotFound, PartNotFound, PartValidationError
from partforge.db.models import FieldDef, FootprintRecord, PartFilter, SortSpec, SymbolRecord
from partforge.workspace import Workspace


def res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "YAGEO", "Manufacturer Part Number": pn, "Resistance": value,
            "Tolerance": "1", "Power": "0.1", "Size": "0603", "Technology": "Dickschicht",
            "Library Ref": "RES", "Footprint Ref": "RESC1608X55N", **kw}


def cap(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "Murata", "Manufacturer Part Number": pn, "Capacitance": value,
            "Voltage": "50", "Library Ref": "CAP", "Footprint Ref": "CAPC1608X87N", **kw}


@pytest.fixture
def resistors(workspace: Workspace) -> list[str]:
    data = [res("R-10K", "10k"), res("R-4K7", "4k7"), res("R-1K", "1k"), res("R-100", "100R"),
            res("R-1M", "1M", Size="0805"), res("R-VAR", "variabel", Notes="Trimmer")]
    out = []
    for row in data:
        out.append(parts.create_part("Resistors", row)["Part Number"])
    parts.create_part("Resistors", {**res("R-EMPTY", "1k"), "Resistance": None}, allow_incomplete=True)
    return out


def test_create_part_normalises_and_renders(workspace: Workspace) -> None:
    warnings: list[str] = []
    row = parts.create_part("Resistors", res("RC0603FR-074K7L", "4K7", Technology="dünnschicht", TCR="±50"),
                            author="Tester", warnings=warnings)
    assert row["Resistance"] == "4.7kΩ" and row["Tolerance"] == "±1%" and row["Power"] == "0.1W"
    assert row["Technology"] == "Dünnschicht" and row["TCR"] == "±50ppm/K"
    assert row["Value"] == "4.7kΩ" and row["Comment"] == "4k7"
    assert row["Description"] == "RES 0603 4.7kΩ ±1% 0.1W Dünnschicht"
    assert row["PF Status"] == "Entwurf" and row["PF Author"] == "Tester"
    assert row["PF Created"] == row["PF Modified"] and len(row["PF Created"] or "") == 19
    assert warnings == []
    stored = parts.get_part("Resistors", "RC0603FR-074K7L")
    assert stored == row
    entry = parts.history("Resistors", "RC0603FR-074K7L")[0]
    assert entry["action"] == "create" and entry["author"] == "Tester"
    assert entry["changes"]["Resistance"] == [None, "4.7kΩ"]
    assert "PF Modified" not in entry["changes"]


def test_create_part_validation(workspace: Workspace) -> None:
    with pytest.raises(PartValidationError) as err:
        parts.create_part("Resistors", {"Manufacturer": "YAGEO", "Manufacturer Part Number": "X1"})
    assert {"Resistance", "Tolerance", "Power", "Library Ref", "Footprint Ref"} <= set(err.value.errors)
    assert "Pflichtfeld" in str(err.value)
    with pytest.raises(PartValidationError) as err:
        parts.create_part("Resistors", {**res("X2", "1k"), "Farbe": "rot"})
    assert "Farbe" in err.value.errors
    parts.create_part("Resistors", {**res("X3", "1k"), "Farbe": None, "PF Author": "Hacker", "PF Created": "1999"})
    stored = parts.get_part("Resistors", "X3")
    assert stored and stored["PF Author"] != "Hacker" and stored["PF Created"] != "1999"
    # TEXT columns: over-long values are stored completely, with a soft warning (no truncation, no refusal)
    long_warnings: list[str] = []
    long_row = parts.create_part("Resistors", res("X4", "1k", Notes=None, Manufacturer="M" * 300), warnings=long_warnings)
    assert long_row["Manufacturer"] == "M" * 300
    assert any("Hersteller" in w and "300 Zeichen" in w for w in long_warnings)
    with pytest.raises(PartValidationError, match="unzulässige Zeichen"):
        parts.create_part("Resistors", res("X'5", "1k"))
    with pytest.raises(PartValidationError, match="Teilenummer fehlt"):
        parts.create_part("Resistors", {**res("", "1k"), "Manufacturer Part Number": None})
    warnings: list[str] = []
    draft = parts.create_part("Resistors", {"Part Number": "DRAFT-1", "Resistance": "1k", "Size": "9999"},
                              allow_incomplete=True, warnings=warnings)
    assert draft["Part Number"] == "DRAFT-1"
    assert any("Pflichtfeld" in w for w in warnings) and any("Auswahlliste" in w for w in warnings)


def test_part_number_defaults_to_mpn(workspace: Workspace) -> None:
    row = parts.create_part("Capacitors", {**cap("", "100n"), "Part Number": None,
                                           "Manufacturer Part Number": "GRM188R71H104KA93D"})
    assert row["Part Number"] == "GRM188R71H104KA93D"
    # scheme "mpn": an empty MPN takes the part number on creation
    row = parts.create_part("Capacitors", {**cap("GRM188R71H103KA01D", "10n"), "Manufacturer Part Number": None})
    assert row["Manufacturer Part Number"] == "GRM188R71H103KA01D"
    workspace.settings.part_number_scheme = "internal"
    with pytest.raises(PartValidationError, match="Manufacturer Part Number"):
        parts.create_part("Capacitors", {**cap("INT-1", "1n"), "Manufacturer Part Number": None})


def test_part_number_unique_across_tables(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("ABC-1", "1k"))
    with pytest.raises(DuplicatePartError, match="Resistors") as err:
        parts.create_part("Capacitors", cap("abc-1", "1n"))
    assert err.value.existing_table == "Resistors" and err.value.existing_part_number == "ABC-1"
    with pytest.raises(DuplicatePartError):
        parts.create_part("Resistors", res("ABC-1", "2k"))
    assert parts.existing_part_numbers(["abc-1", "ABC-2", ""]) == {"abc-1"}
    assert parts.find_part("abc-1") == ("Resistors", parts.get_part("Resistors", "ABC-1"))
    assert parts.find_part("nichts") is None and parts.find_part(" ") is None


def test_internal_part_number_scheme(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    first = parts.create_part("Resistors", {**res("", "1k"), "Part Number": None, "Manufacturer Part Number": "M-1"})
    assert first["Part Number"] == "R-000001"
    parts.create_part("Resistors", res("R-000002", "2k"))  # manual number in the generator's range
    second = parts.create_part("Resistors", {**res("", "3k"), "Part Number": None, "Manufacturer Part Number": "M-3"})
    assert second["Part Number"] == "R-000003"
    workspace.settings.internal_pn_format = "{prefix}{counter:04d}-{table}"
    third = parts.create_part("Capacitors", {**cap("", "1n"), "Part Number": None, "Manufacturer Part Number": "M-C"})
    assert third["Part Number"] == "C0001-Capacitors"


def test_update_rerenders_generated_texts_but_keeps_manual(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("R1", "10k"))
    row = parts.update_part("Resistors", "R1", {"Resistance": "22k"})
    assert row["Description"] == "RES 0603 22kΩ ±1% 0.1W Dickschicht" and row["Comment"] == "22k" and row["Value"] == "22kΩ"
    row = parts.update_part("Resistors", "R1", {"Description": "Mein Text"})
    assert row["Description"] == "Mein Text"
    row = parts.update_part("Resistors", "R1", {"Resistance": "47k"})
    assert row["Description"] == "Mein Text" and row["Comment"] == "47k"
    row = parts.update_part("Resistors", "R1", {"Description": ""})
    assert row["Description"] == "RES 0603 47kΩ ±1% 0.1W Dickschicht"


def test_update_rename_history_and_errors(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("OLD-1", "1k"))
    parts.create_part("Capacitors", cap("TAKEN-1", "1n"))
    parts.update_part("Resistors", "OLD-1", {"Tolerance": "5"})
    row = parts.update_part("Resistors", "old-1", {"Part Number": "NEW-1"})
    assert row["Part Number"] == "NEW-1" and parts.get_part("Resistors", "OLD-1") is None
    entries = parts.history("Resistors", "NEW-1")
    assert [e["action"] for e in entries] == ["update", "update", "create"]
    assert entries[0]["changes"]["Part Number"] == ["OLD-1", "NEW-1"]
    with pytest.raises(DuplicatePartError):
        parts.update_part("Resistors", "NEW-1", {"Part Number": "taken-1"})
    assert parts.update_part("Resistors", "NEW-1", {"Part Number": "new-1"})["Part Number"] == "new-1"  # case only
    with pytest.raises(PartNotFound):
        parts.update_part("Resistors", "GIBTS-NICHT", {"Tolerance": "1"})
    with pytest.raises(KeyError):
        parts.update_part("Resistors", "GIBTS-NICHT", {"Tolerance": "1"})


def test_update_without_change_writes_nothing(workspace: Workspace) -> None:
    created = parts.create_part("Resistors", res("SAME-1", "1k"))
    again = parts.update_part("Resistors", "SAME-1", {"Resistance": "1000", "Tolerance": "±1 %"})
    assert again["PF Modified"] == created["PF Modified"]
    assert len(parts.history("Resistors", "SAME-1")) == 1


def test_emptying_part_number_on_update_is_an_error(workspace: Workspace) -> None:
    parts.create_part("Resistors", {**res("PN-1", "1k"), "Manufacturer Part Number": "MPN-OTHER"})
    with pytest.raises(PartValidationError, match="Teilenummer fehlt"):
        parts.update_part("Resistors", "PN-1", {"Part Number": ""})
    assert parts.get_part("Resistors", "PN-1") is not None and parts.get_part("Resistors", "MPN-OTHER") is None


def test_update_required_fields(workspace: Workspace) -> None:
    parts.create_part("Resistors", {**res("GAP-1", "1k"), "Footprint Ref": None}, allow_incomplete=True)
    assert parts.update_part("Resistors", "GAP-1", {"Tolerance": "5"})["Tolerance"] == "±5%"  # untouched gap is ok
    with pytest.raises(PartValidationError, match="Pflichtfeld"):
        parts.update_part("Resistors", "GAP-1", {"Resistance": ""})


def test_library_paths_come_from_registry(workspace: Workspace) -> None:
    registry.upsert_symbol(SymbolRecord(name="RES", library=r"Symbols\PF_Passives.SchLib"))
    registry.upsert_symbol(SymbolRecord(name="RES_US", library=r"Symbols\PF_US.SchLib"))
    row = parts.create_part("Resistors", res("LP-1", "1k"))
    assert row["Library Path"] == r"Symbols\PF_Passives.SchLib" and row["Footprint Path"] is None
    row = parts.update_part("Resistors", "LP-1", {"Library Ref": "res_us"})
    assert row["Library Path"] == r"Symbols\PF_US.SchLib"
    row = parts.update_part("Resistors", "LP-1", {"Library Ref": "RES", "Library Path": "Symbols/Eigen.SchLib"})
    assert row["Library Path"] == r"Symbols\Eigen.SchLib"


def test_set_library_path_across_categories(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("SP-1", "1k", **{"Footprint Ref 2": "resc1608x55n"}))
    parts.create_part("Resistors", res("SP-2", "2k", **{"Footprint Path": r"Footprints\PF_CHIP.PcbLib"}))
    parts.create_part("Capacitors", cap("SP-3", "1n", **{"Footprint Ref": "RESC1608X55N"}))
    assert parts.set_library_path("footprint", "RESC1608X55N", "Footprints/PF_CHIP.PcbLib") == 2
    one = parts.get_part("Resistors", "SP-1")
    assert one and one["Footprint Path"] == one["Footprint Path 2"] == r"Footprints\PF_CHIP.PcbLib"
    assert parts.get_part("Capacitors", "SP-3")["Footprint Path"] == r"Footprints\PF_CHIP.PcbLib"  # type: ignore[index]
    assert parts.history("Resistors", "SP-1")[0]["action"] == "bulk_update"
    assert parts.set_library_path("footprint", "RESC1608X55N", r"Footprints\PF_CHIP.PcbLib") == 0  # nothing left to do
    assert parts.set_library_path("symbol", "res", r"Symbols\PF_Passives.SchLib") == 2
    assert parts.get_part("Resistors", "SP-2")["Library Path"] == r"Symbols\PF_Passives.SchLib"  # type: ignore[index]
    assert parts.set_library_path("symbol", " ", "x") == 0


def test_delete_parts_audit_and_backup_threshold(workspace: Workspace) -> None:
    for i in range(25):
        parts.create_part("Resistors", res(f"D-{i:02d}", f"{i + 1}k"))
    before = len(backup.list_backups())
    assert parts.delete_parts("Resistors", ["D-00", "d-01", "nope"]) == 2
    assert len(backup.list_backups()) == before
    assert parts.delete_parts("Resistors", [f"D-{i:02d}" for i in range(2, 23)]) == 21
    assert len(backup.list_backups()) == before + 1
    assert parts.query_parts("Resistors")[1] == 2
    deleted = parts.history("Resistors", "D-00")[0]
    assert deleted["action"] == "delete" and deleted["changes"]["Resistance"] == ["1kΩ", None]
    assert parts.delete_parts("Resistors", []) == 0


def test_bulk_update(workspace: Workspace) -> None:
    for pn, value in (("B1", "1k"), ("B2", "2k"), ("B3", "3k")):
        parts.create_part("Resistors", res(pn, value))
    warnings: list[str] = []
    assert parts.bulk_update("Resistors", ["B1", "b2", "B3", "missing"], {"Tolerance": "5", "Technology": "Spezial"},
                             warnings=warnings) == 3
    assert all(parts.get_part("Resistors", pn)["Tolerance"] == "±5%" for pn in ("B1", "B2", "B3"))  # type: ignore[index]
    assert parts.get_part("Resistors", "B2")["Description"] == "RES 0603 2kΩ ±5% 0.1W Spezial"  # type: ignore[index]
    assert any("Auswahlliste" in w for w in warnings)
    assert parts.bulk_update("Resistors", ["B1"], {"Tolerance": "5"}) == 0  # nothing changed
    with pytest.raises(PartValidationError, match="Massenbearbeitung"):
        parts.bulk_update("Resistors", ["B1"], {"Part Number": "X"})
    with pytest.raises(PartValidationError, match="Massenbearbeitung abgebrochen"):
        parts.bulk_update("Resistors", ["B1", "B2"], {"Resistance": ""})
    assert parts.get_part("Resistors", "B1")["Resistance"] == "1kΩ"  # type: ignore[index]
    assert parts.history("Resistors", "B1")[0]["action"] == "bulk_update"


def test_duplicate_part(workspace: Workspace) -> None:
    parts.create_part("Resistors", {**res("ORIG", "1k"), "PF Status": "Freigegeben"})
    copy = parts.duplicate_part("Resistors", "ORIG", "COPY")
    assert copy["Part Number"] == "COPY" and copy["Resistance"] == "1kΩ" and copy["PF Status"] == "Entwurf"
    assert copy["Manufacturer Part Number"] == "ORIG"
    with pytest.raises(DuplicatePartError):
        parts.duplicate_part("Resistors", "ORIG", "copy")
    with pytest.raises(PartNotFound):
        parts.duplicate_part("Resistors", "NOPE", "X")


QUERIES: list[dict[str, Any]] = [
    {"search": "10k"},
    {"search": "4.7k"},
    {"search": "0603 4k7"},
    {"search": "yageo"},
    {"search": '"RES 0603"'},
    {"filters": [PartFilter(column="Resistance", op="gt", value="1k")]},
    {"filters": [PartFilter(column="Resistance", op="le", value="1000")]},
    {"filters": [PartFilter(column="Resistance", op="eq", value="10000")]},
    {"filters": [PartFilter(column="Resistance", op="ne", value="10k")]},
    {"filters": [PartFilter(column="Resistance", op="in", value=["1k", "10k", "variabel"])]},
    {"filters": [PartFilter(column="Part Number", op="contains", value="-1")]},
    {"filters": [PartFilter(column="Part Number", op="startswith", value="r-1")]},
    {"filters": [PartFilter(column="Notes", op="empty")]},
    {"filters": [PartFilter(column="Notes", op="notempty")]},
    {"filters": [PartFilter(column="Size", op="eq", value="0805")]},
    {"filters": [PartFilter(column="Size", op="ne", value="")]},
    {"filters": [PartFilter(column="Manufacturer", op="lt", value="z")]},
    {"sort": "Resistance"},
    {"sort": "-Resistance"},
    {"sort": [SortSpec(column="Size", desc=True), SortSpec(column="Resistance")]},
    {"sort": "Notes"},
    {"sort": "Resistance:desc", "offset": 2, "limit": 3},
]


def test_query_search_filters_and_sort(resistors: list[str]) -> None:
    def pns(**kw: Any) -> list[str]:
        rows, _ = parts.query_parts("Resistors", **kw)
        return [r["Part Number"] for r in rows]  # type: ignore[misc]

    assert pns(search="10k") == ["R-10K"]
    assert pns(search="4.7k") == ["R-4K7"]
    assert pns(search="4k7") == ["R-4K7"]
    assert pns(search="0603 4k7") == ["R-4K7"]
    assert pns(search="1M") == ["R-1M"]
    assert pns(search="trimmer") == ["R-VAR"]
    assert set(pns(search="YAGEO")) == {*resistors, "R-EMPTY"}
    assert pns(filters=[PartFilter(column="Resistance", op="gt", value="1k")], sort="Resistance") == ["R-4K7", "R-10K", "R-1M"]
    assert pns(filters=[{"column": "resistance", "op": "le", "value": "1000"}], sort="Resistance") == ["R-100", "R-1K"]
    assert pns(filters=[PartFilter(column="Resistance", op="eq", value="10000")]) == ["R-10K"]
    assert "R-EMPTY" in pns(filters=[PartFilter(column="Resistance", op="ne", value="10k")])
    assert set(pns(filters=[PartFilter(column="Resistance", op="in", value=["1k", "10k", "variabel"])])) == {"R-1K", "R-10K", "R-VAR"}
    assert pns(filters=[PartFilter(column="Notes", op="notempty")]) == ["R-VAR"]
    assert pns(filters=[PartFilter(column="Size", op="eq", value="0805")]) == ["R-1M"]
    assert pns(filters=[PartFilter(column="Part Number", op="startswith", value="r-1")], sort="Part Number") == ["R-100", "R-10K", "R-1K", "R-1M"]
    # quantity-aware sort, unparsable then empty values last in both directions
    assert pns(sort="Resistance") == ["R-100", "R-1K", "R-4K7", "R-10K", "R-1M", "R-VAR", "R-EMPTY"]
    assert pns(sort="-Resistance") == ["R-1M", "R-10K", "R-4K7", "R-1K", "R-100", "R-VAR", "R-EMPTY"]
    rows, total = parts.query_parts("Resistors", sort="Resistance", offset=2, limit=2)
    assert total == 7 and [r["Part Number"] for r in rows] == ["R-4K7", "R-10K"]
    rows, total = parts.query_parts("Resistors", limit=None)
    assert total == len(rows) == 7
    with pytest.raises(FieldNotFound):
        parts.query_parts("Resistors", filters=[PartFilter(column="Nope", op="eq", value="x")])
    with pytest.raises(FieldNotFound):
        parts.query_parts("Resistors", sort="Nope")
    with pytest.raises(ValueError, match="fehlt ein Wert"):
        parts.query_parts("Resistors", filters=[PartFilter(column="Resistance", op="gt")])


def test_python_fallback_matches_sql(resistors: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    sql_results = [parts.query_parts("Resistors", **q) for q in QUERIES]
    monkeypatch.setattr(core.get_state(), "sql_functions", False)
    assert not core.sql_functions_enabled()
    py_results = [parts.query_parts("Resistors", **q) for q in QUERIES]
    for query, sql, py in zip(QUERIES, sql_results, py_results):
        assert [r["Part Number"] for r in py[0]] == [r["Part Number"] for r in sql[0]], query
        assert py[1] == sql[1], query


def test_search_all(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("RC0603FR-074K7L", "4k7"))
    parts.create_part("Resistors", res("RC0603FR-0747KL", "47k"))
    parts.create_part("Capacitors", cap("GRM188R71H104KA93D", "100n"))
    hits = parts.search_all("RC0603FR-074K7L")
    assert hits[0]["part_number"] == "RC0603FR-074K7L" and hits[0]["score"] == 100.0
    assert hits[0]["label"] == "Widerstände" and hits[0]["table"] == "Resistors"
    assert [h["part_number"] for h in parts.search_all("4.7k")] == ["RC0603FR-074K7L"]
    assert [h["part_number"] for h in parts.search_all("100n")] == ["GRM188R71H104KA93D"]
    assert len(parts.search_all("rc0603", limit=1)) == 1
    assert parts.search_all("") == [] and parts.search_all("zzz") == []


def test_stats(resistors: list[str]) -> None:
    parts.create_part("Capacitors", {**cap("C-1", "1n"), "ComponentLink1URL": "www.murata.com/x.pdf"})
    stats = parts.stats()
    assert stats["total_parts"] == 8 and stats["category_count"] == len(categories.list_categories(with_counts=False))
    res_stat = next(c for c in stats["categories"] if c["table"] == "Resistors")
    assert res_stat["count"] == 7 and res_stat["missing_datasheet"] == 7
    assert stats["missing"]["datasheet"] == 7 and stats["missing"]["library_ref"] == 0
    assert stats["status_counts"]["Entwurf"] == 8
    assert stats["recent_parts"] and stats["recent_parts"][0]["modified"]
    assert stats["recent_changes"][0]["action"] == "create"
    assert stats["symbols"]["total"] == 0 and stats["datasheets"] == 0


def test_render_validate_smart_fill_distinct_regenerate(resistors: list[str]) -> None:
    assert parts.render_templates("Resistors", {"resistance": "4k7", "Tolerance": "1", "Size": "0603", "Power": "1/16"}) == {
        "Value": "4.7kΩ", "Comment": "4k7", "Description": "RES 0603 4.7kΩ ±1% 62.5mW"}
    check = parts.validate_part("Resistors", res("R-10K", "10k"))
    assert check["conflict"]["table"] == "Resistors" and not check["errors"]
    check = parts.validate_part("Resistors", {"Resistance": "abc"}, pn="R-1K")
    assert check["values"]["Resistance"] == "abc" and check["warnings"] and check["conflict"] is None
    with pytest.raises(PartNotFound):
        parts.validate_part("Resistors", {}, pn="NOPE")
    fill = parts.smart_fill("Resistors", "10k 1% 0603 0.1W 75V YAGEO")
    assert fill["values"] == {"Resistance": "10kΩ", "Tolerance": "±1%", "Size": "0603", "Power": "0.1W", "Voltage": "75V"}
    assert fill["unmatched"] == ["YAGEO"]
    assert parts.smart_fill("Capacitors", "100n 50V X7R 0603")["values"] == {
        "Capacitance": "100nF", "Voltage": "50V", "Dielectric": "X7R", "Size": "0603"}
    sizes = parts.distinct_values("Resistors", "size")
    assert sizes[0] == {"value": "0603", "count": 6} and {"value": "0805", "count": 1} in sizes
    values = [d["value"] for d in parts.distinct_values("Resistors", "Resistance")]
    assert values == ["100Ω", "1kΩ", "4.7kΩ", "10kΩ", "1MΩ", "variabel"]
    categories.update_category("Resistors", {"description_template": "WIDERSTAND {Resistance}"})
    parts.update_part("Resistors", "R-1K", {"Description": "manuell"})
    assert parts.regenerate_texts("Resistors", ["R-1K", "R-10K"]) == 2
    assert parts.get_part("Resistors", "R-1K")["Description"] == "WIDERSTAND 1kΩ"  # type: ignore[index]
    assert parts.regenerate_texts("Resistors") == 5  # remaining parts (incl. the one without resistance)
    assert parts.regenerate_texts("Resistors", columns=["Notes"]) == 0


def test_new_field_kinds_in_custom_category(workspace: Workspace) -> None:
    categories.add_field("Connectors", FieldDef(column="Mating Cycles", label="Steckzyklen", kind="int"))
    categories.add_field("Connectors", FieldDef(column="Sealed", label="Abgedichtet", kind="bool"))
    row = parts.create_part("Connectors", {"Part Number": "J-1", "Manufacturer": "Würth Elektronik",
                                           "Manufacturer Part Number": "61300211121", "Connector Type": "Stiftleiste",
                                           "Pins": "2", "Pitch": "2.54", "Mating Cycles": "500", "Sealed": "nein",
                                           "Library Ref": "CONN_1X2", "Footprint Ref": "HDR1X2"})
    assert row["Pitch"] == "2.54mm" and row["Sealed"] == "Nein" and row["Mating Cycles"] == "500"
    assert row["Description"] == "CONN Stiftleiste 2POS 2.54mm"
    rows, total = parts.query_parts("Connectors", filters=[PartFilter(column="Mating Cycles", op="ge", value="100")])
    assert total == 1


def test_unicode_search_and_text_filters(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: SQLite's lower()/LIKE only fold ASCII – Ü, Ö, Ω never matched (not even exact case)."""
    parts.create_part("Resistors", res("R-A", "10k", Notes="Übertemperatur geprüft", Technology="Dünnschicht"))
    parts.create_part("Resistors", res("R-B", "4k7", Notes="ÖLFEST"))
    parts.create_part("Resistors", res("R-C", "1k", Notes="Straße"))

    def pns(**kw: Any) -> list[str]:
        return sorted(r["Part Number"] for r in parts.query_parts("Resistors", **kw)[0])  # type: ignore[misc]

    queries: list[dict[str, Any]] = [
        {"search": "übertemperatur"}, {"search": "Übertemperatur"}, {"search": "ÜBERTEMPERATUR"},
        {"search": "ÖLFEST"}, {"search": "ölfest"}, {"search": "kΩ"}, {"search": "KΩ"}, {"search": "Ω 4k7"},
        {"search": "STRASSE"}, {"search": "dünnschicht"},
        {"filters": [PartFilter(column="Notes", op="contains", value="übertemperatur")]},
        {"filters": [PartFilter(column="Notes", op="startswith", value="öl")]},
        {"filters": [PartFilter(column="Notes", op="eq", value="ölfest")]},
        {"filters": [PartFilter(column="Notes", op="ne", value="ölfest")]},
        {"filters": [PartFilter(column="Technology", op="eq", value="DÜNNSCHICHT")]},
        {"filters": [PartFilter(column="Notes", op="gt", value="öz")]},
        {"sort": "Notes"}, {"sort": "-Notes"},
    ]
    expected = [["R-A"], ["R-A"], ["R-A"], ["R-B"], ["R-B"], ["R-A", "R-B", "R-C"], ["R-A", "R-B", "R-C"], ["R-B"],
                ["R-C"], ["R-A"], ["R-A"], ["R-B"], ["R-B"], ["R-A", "R-C"], ["R-A"], ["R-A"],
                ["R-A", "R-B", "R-C"], ["R-A", "R-B", "R-C"]]
    sql = [pns(**q) for q in queries]
    assert sql == expected
    order = [r["Part Number"] for r in parts.query_parts("Resistors", sort="Notes")[0]]
    assert order == ["R-C", "R-B", "R-A"]  # casefolded: "straße" < "ölfest" < "übertemperatur" (code points)
    assert [d["value"] for d in parts.distinct_values("Resistors", "Notes", search="ÜBER")] == ["Übertemperatur geprüft"]
    # the quick search covers part number, MPN, description, value, comment and manufacturer
    assert [h["part_number"] for h in parts.search_all("DÜNNSCHICHT")] == ["R-A"]
    assert {h["part_number"] for h in parts.search_all("4.7KΩ")} == {"R-B"}
    # the Python fallback (PostgreSQL path) gives identical results on SQLite
    monkeypatch.setattr(core.get_state(), "sql_functions", False)
    assert [pns(**q) for q in queries] == expected
    assert [r["Part Number"] for r in parts.query_parts("Resistors", sort="Notes")[0]] == order


def test_search_all_keeps_exact_match_among_many_similar(workspace: Workspace) -> None:
    """Regression: the per-category LIMIT cut the exact hit "BAT54" off behind 80 "BAT54-VARxxx"."""
    diode = {"Manufacturer": "Nexperia", "Library Ref": "DIODE_SCHOTTKY", "Footprint Ref": "SOT95P237X112-3N",
             "Diode Type": "Schottky"}
    rows = [{**diode, "Part Number": f"BAT54-VAR{i:03d}", "Manufacturer Part Number": f"BAT54-VAR{i:03d}"} for i in range(80)]
    rows.append({**diode, "Part Number": "BAT54", "Manufacturer Part Number": "BAT54"})
    assert len(parts.upsert_parts("Diodes", rows).created) == 81
    hits = parts.search_all("bat54", limit=20)
    assert hits[0]["part_number"] == "BAT54" and hits[0]["score"] == 100.0 and len(hits) == 20
    assert all(h["part_number"].startswith("BAT54") for h in hits)
    assert parts.search_all("BAT54-VAR07", limit=5)[0]["part_number"] == "BAT54-VAR070"  # prefix: shortest first


def test_library_path_follows_reference_changes(workspace: Workspace) -> None:
    """Regression: a new, unregistered reference kept the registry path of the old one."""
    registry.upsert_symbol(SymbolRecord(name="RES", library=r"Symbols\PF_Passives.SchLib"))
    registry.upsert_footprint(FootprintRecord(name="RESC1608X55N", library=r"Footprints\PF_CHIP.PcbLib"))
    registry.upsert_footprint(FootprintRecord(name="RESC2012X70N", library=r"Footprints\PF_CHIP_0805.PcbLib"))
    row = parts.create_part("Resistors", res("PATH-1", "1k"))
    assert row["Library Path"] == r"Symbols\PF_Passives.SchLib" and row["Footprint Path"] == r"Footprints\PF_CHIP.PcbLib"
    row = parts.update_part("Resistors", "PATH-1", {"Footprint Ref": "RESC2012X70N"})  # registered: its library
    assert row["Footprint Path"] == r"Footprints\PF_CHIP_0805.PcbLib"
    row = parts.update_part("Resistors", "PATH-1", {"Footprint Ref": "RESC3216X70N", "Library Ref": "RES_NEU"})
    assert row["Footprint Path"] is None and row["Library Path"] is None  # unknown: the old path would be wrong
    # a user-managed path (external library) stays when the reference changes
    row = parts.update_part("Resistors", "PATH-1", {"Library Ref": "TR_RES", "Library Path": r"Extern\TR_Passiv.SchLib"})
    assert row["Library Path"] == r"Extern\TR_Passiv.SchLib"
    row = parts.update_part("Resistors", "PATH-1", {"Library Ref": "TR_RES_2"})
    assert row["Library Path"] == r"Extern\TR_Passiv.SchLib"
    # removing the reference removes a registry path, too
    parts.update_part("Resistors", "PATH-1", {"Library Ref": "RES"})
    row = parts.update_part("Resistors", "PATH-1", {"Footprint Ref 2": "RESC1608X55N"})
    assert row["Footprint Path 2"] == r"Footprints\PF_CHIP.PcbLib"
    row = parts.update_part("Resistors", "PATH-1", {"Footprint Ref 2": None})
    assert row["Footprint Path 2"] is None and row["Library Path"] == r"Symbols\PF_Passives.SchLib"


def test_validate_with_internal_scheme_does_not_use_the_mpn(workspace: Workspace) -> None:
    """Regression: the dry run showed the MPN as part number (and a false conflict), create assigned R-000001."""
    parts.create_part("Resistors", res("MPN-X", "1k"))
    workspace.settings.part_number_scheme = "internal"
    check = parts.validate_part("Resistors", {**res("", "2k"), "Part Number": None, "Manufacturer Part Number": "MPN-X"})
    assert check["values"]["Part Number"] is None and check["conflict"] is None and not check["errors"]
    assert any("automatisch vergeben" in w for w in check["warnings"])
    created = parts.create_part("Resistors", {**res("", "2k"), "Part Number": None, "Manufacturer Part Number": "MPN-X"})
    assert created["Part Number"] == "R-000001"


def test_long_generated_texts_are_warnings(workspace: Workspace) -> None:
    categories.update_field("Resistors", "Description", {"length": 20})
    warnings: list[str] = []
    row = parts.create_part("Resistors", res("LONG-1", "1k"), warnings=warnings)
    assert row["Description"] == "RES 0603 1kΩ ±1% 0.1W Dickschicht"  # generated, longer than 20: stored completely
    assert any(w.startswith("Beschreibung") and "empfohlen sind höchstens 20" in w for w in warnings)


def test_audit_recent_and_resolve_author(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    parts.create_part("Resistors", res("A-1", "1k"))
    assert audit.recent(1)[0].part_number == "A-1"
    assert audit.resolve_author("  Jemand ") == "Jemand"
    assert audit.resolve_author(None)  # configured author or Windows user
    assert audit.diff({"a": "", "b": "1"}, {"a": None, "b": "2", "PF Modified": "x"}) == {"b": ["1", "2"]}


# --------------------------------------------------------------------------- find_by_mpn


def test_mpn_key_compacts_and_casefolds() -> None:
    assert parts.mpn_key(" GRM188R71H104KA93D ") == parts.mpn_key("grm188r71h104ka93d") == "grm188r71h104ka93d"
    assert parts.mpn_key("MMSZ5231B-7-F") == parts.mpn_key("MMSZ5231B7F") == parts.mpn_key("mmsz5231b‐7–f")
    assert parts.mpn_key("RC0603FR -07 10KL") == "rc0603fr0710kl"
    assert parts.mpn_key("ＬＭ３５８") == "lm358"  # full-width characters from PDFs (NFKC)
    assert parts.mpn_key("2N7002,215") != parts.mpn_key("2N7002215")  # only blanks and dashes are ignored
    assert parts.mpn_key(None) == "" and parts.mpn_key("  - ") == ""


def test_find_by_mpn_across_categories(workspace: Workspace) -> None:
    parts.create_part("Resistors", res("RC0603FR-0710KL", "10k"))
    parts.create_part("Resistors", res("R-INTERN-1", "4k7", **{"Manufacturer Part Number": "RC0603FR-074K7L"}))
    parts.create_part("Capacitors", cap("GRM188R71H104KA93D", "100n"))
    parts.create_part("Capacitors", cap("C-INTERN-1", "100n", **{"Manufacturer Part Number": "grm188r71h104ka93d"}))
    parts.create_part("Diodes", {"Part Number": "MMSZ5231B-7-F", "Manufacturer": "Diodes", "Library Ref": "Zener Diode",
                                 "Footprint Ref": "SOD3716X135N"})
    with core.connect() as conn:  # a row without MPN (written by another tool): its part number counts
        conn.exec_driver_sql('INSERT INTO "LEDs" ("Part Number", "Color") VALUES (?, ?)', ("150060RS75000", "Rot"))
    categories.invalidate_cache()

    hits = parts.find_by_mpn(["rc0603fr-0710kl", "RC0603FR074K7L", "GRM188R71H104KA93D ", "MMSZ5231B7F",
                              "150060-RS75000", "NOPE-1", "", "   "])
    assert set(hits) == {parts.mpn_key(m) for m in ("RC0603FR-0710KL", "RC0603FR-074K7L", "GRM188R71H104KA93D",
                                                    "MMSZ5231B-7-F", "150060RS75000")}
    assert [(t, pn) for t, pn, _row in hits[parts.mpn_key("RC0603FR-0710KL")]] == [("Resistors", "RC0603FR-0710KL")]
    internal = hits[parts.mpn_key("RC0603FR-074K7L")]
    assert [(t, pn) for t, pn, _row in internal] == [("Resistors", "R-INTERN-1")]
    assert internal[0][2]["Resistance"] == "4.7kΩ" and internal[0][2]["Manufacturer Part Number"] == "RC0603FR-074K7L"
    caps = hits[parts.mpn_key("GRM188R71H104KA93D")]  # two parts with the same MPN: both, sorted by part number
    assert [pn for _t, pn, _row in caps] == ["C-INTERN-1", "GRM188R71H104KA93D"]
    assert [t for t, _pn, _row in hits[parts.mpn_key("MMSZ5231B-7-F")]] == ["Diodes"]
    assert hits[parts.mpn_key("150060RS75000")][0][:2] == ("LEDs", "150060RS75000")
    assert parts.find_by_mpn([]) == {} and parts.find_by_mpn(["", None]) == {}  # type: ignore[list-item]


def test_find_by_mpn_reads_each_category_once(workspace: Workspace, monkeypatch: pytest.MonkeyPatch) -> None:
    """One scan per category, however many MPNs are asked for (not one query per MPN)."""
    for i in range(30):
        parts.create_part("Resistors", res(f"R-{i:03d}", "1k", **{"Manufacturer Part Number": f"MPN-{i:03d}"}))
    statements: list[str] = []
    from sqlalchemy import event

    engine = core.get_engine()

    def count(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        if statement.lstrip().upper().startswith("SELECT") and "pf_" not in statement:
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        hits = parts.find_by_mpn([f"mpn-{i:03d}" for i in range(30)] + [f"OTHER-{i}" for i in range(500)])
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(hits) == 30
    tables = len(categories.list_categories(with_counts=False))
    assert len(statements) <= tables + 1  # one scan per category + one indexed read of the hits
