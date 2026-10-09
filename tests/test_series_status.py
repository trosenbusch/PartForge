"""Series preview statuses against existing parts (part number and manufacturer part number in every
category) and the checks db.parts applies on saving (required fields, part-number characters)."""
from __future__ import annotations

from typing import Any

import pytest

from partforge.db import categories, parts
from partforge.domain.mpn import MpnTemplate, get_template, save_custom_template
from partforge.domain.series import SeriesError, SeriesRequest, _Normalizer, preview
from partforge.workspace import Workspace

PN = "CRCW060310K0FKEA"


def req(**kw: Any) -> SeriesRequest:
    base: dict[str, Any] = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "tolerance": "1%", "values": ["10k"]}
    base.update(kw)
    return SeriesRequest.model_validate(base)


def resistor(pn: str, mpn: str, **values: Any) -> None:
    parts.create_part("Resistors", {"Part Number": pn, "Manufacturer": "Vishay", "Manufacturer Part Number": mpn,
                                    "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Library Ref": "Resistor",
                                    "Footprint Ref": "RESC1608X50N", **values})


def test_same_mpn_under_another_part_number_exists(workspace: Workspace) -> None:
    """Regression: an MPN stored under another part number was reported "new" (duplicate MPN on commit)."""
    resistor("R-10K-0603", PN)
    row = preview(req()).rows[0]
    assert row.status == "exists" and row.part_number == "R-10K-0603" and row.values["Part Number"] == "R-10K-0603"
    assert "Vorhanden als „R-10K-0603“ (gleiche Hersteller-Teilenummer)." in row.messages


def test_mpn_is_compared_without_hyphens_and_letter_case(workspace: Workspace) -> None:
    resistor("R-1", "erj3ekf1002v")
    row = preview(SeriesRequest(template_id="panasonic-erj-1pct", sizes=["0603"], values=["10k"])).rows[0]
    assert row.mpn == "ERJ-3EKF1002V" and row.status == "exists" and row.part_number == "R-1"


def test_mpn_in_another_category_is_a_conflict(workspace: Workspace) -> None:
    parts.create_part("Capacitors", {"Part Number": "C-1", "Manufacturer": "x", "Manufacturer Part Number": PN,
                                     "Capacitance": "1n", "Voltage": "50V", "Library Ref": "CAP", "Footprint Ref": "C"})
    row = preview(req()).rows[0]
    assert row.status == "conflict"
    assert "Die Hersteller-Teilenummer ist bereits als „C-1“ in „Capacitors“ vergeben." in row.messages


def test_part_number_used_with_another_mpn(workspace: Workspace) -> None:
    resistor(PN, "ANDERE-MPN")
    row = preview(req()).rows[0]
    assert row.status == "conflict" and "„ANDERE-MPN“" in row.messages[0]
    parts.create_part("Capacitors", {"Part Number": "CRCW060322K0FKEA", "Manufacturer": "x",
                                     "Manufacturer Part Number": "x", "Capacitance": "1n", "Voltage": "50V",
                                     "Library Ref": "CAP", "Footprint Ref": "C"})
    other = preview(req(values=["22k"])).rows[0]
    assert other.status == "conflict" and "anderen Kategorie" in other.messages[0]


def test_part_with_empty_mpn_counts_as_the_same_part(workspace: Workspace) -> None:
    resistor(PN, "")
    row = preview(req()).rows[0]
    assert row.status == "exists" and row.part_number == PN


def test_internal_scheme_finds_parts_by_mpn_in_every_category(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    parts.create_part("Capacitors", {"Manufacturer": "x", "Manufacturer Part Number": "CRCW060322K0FKEA",
                                     "Capacitance": "1n", "Voltage": "50V", "Library Ref": "CAP", "Footprint Ref": "C"})
    resistor("R-000001", PN)
    rows = {r.value: r for r in preview(req(values=["10k", "22k", "47k"])).rows}
    assert rows["10kΩ"].status == "exists" and rows["10kΩ"].part_number == "R-000001"
    assert rows["10kΩ"].messages == []
    assert rows["22kΩ"].status == "conflict" and "Capacitors" in rows["22kΩ"].messages[0]
    assert rows["47kΩ"].status == "new" and rows["47kΩ"].part_number is None
    assert "Part Number" not in rows["47kΩ"].values


def test_many_existing_parts_are_looked_up_in_one_scan(workspace: Workspace) -> None:
    request = req(tolerance="5%", e_series="E24", values=[], range_min="1", range_max="10M")
    workspace.settings.part_number_scheme = "internal"
    created = preview(request)
    batch = [{"Manufacturer": "Vishay", "Manufacturer Part Number": r.mpn, "Resistance": r.values["Resistance"],
              "Tolerance": "5%", "Power": "0.1W", "Library Ref": "Resistor", "Footprint Ref": "RESC1608X50N"}
             for r in created.rows]
    assert parts.upsert_parts("Resistors", batch).created
    again = preview(request)
    assert again.counts["exists"] == len(batch) == 169


# --------------------------------------------------------------------------- what db.parts would refuse


def test_required_fields_are_checked_in_the_preview(workspace: Workspace) -> None:
    """Regression: rows without a required value were "new" and failed only in the commit job."""
    save_custom_template(MpnTemplate.model_validate({
        "id": "haus-ohne-p", "manufacturer": "Haus", "series": "H", "category": "Resistors", "title": "Ohne Leistung",
        "pattern": "H{size}-{value}",
        "variables": [{"name": "size", "label": "Baugröße", "options": [{"code": "0603", "value": "0603"}]},
                      {"name": "value", "label": "Wert", "format": {"style": "rkm"}}],
        "sizes": [{"size": "0603"}],
        "fields": {"Resistance": "{value}", "Tolerance": "±1%"},
    }))
    result = preview(SeriesRequest(template_id="haus-ohne-p", values=["10k"]))
    assert result.counts == {"total": 1, "new": 0, "exists": 0, "conflict": 0, "invalid": 1}
    assert "Leistung: Pflichtfeld ist leer." in result.rows[0].messages
    with_power = preview(SeriesRequest(template_id="haus-ohne-p", values=["10k"],
                                       field_overrides={"Power": "0.1W"}))
    assert with_power.rows[0].status == "new"


def test_jumpers_may_leave_tolerance_and_power_empty(workspace: Workspace) -> None:
    """Tolerance, TCR, power and voltage do not apply to a 0-Ω jumper (db.values.not_applicable): the row is
    complete without them – no "Pflichtfeld ist leer" note; the rated current is in the notes."""
    jumper = preview(req(values=[], include_jumper=True, range_min="10k", range_max="10k")).rows[-1]
    assert jumper.jumper and jumper.status == "new"
    assert not any("Pflichtfeld" in m for m in jumper.messages), jumper.messages
    assert jumper.values.get("Tolerance") is None and jumper.values.get("Power") is None
    assert jumper.values["Notes"] == "0-Ω-Brücke (Jumper) ≤ 20 mΩ, Nennstrom 2A"


def test_jumper_rows_still_need_the_fields_that_apply(workspace: Workspace) -> None:
    """Only the jumper-exempt fields may stay empty: a required field the template leaves empty makes
    the jumper row invalid like any other row."""
    categories.update_field("Resistors", "Technology", {"required": True})
    custom = get_template("vishay-crcw-e3").model_copy(deep=True)
    custom.id = "vishay-ohne-technik"
    custom.builtin = False
    custom.attrs = {k: v for k, v in custom.attrs.items() if k != "technology"}
    save_custom_template(custom)
    rows = preview(SeriesRequest(template_id="vishay-ohne-technik", sizes=["0603"], values=["10k"],
                                 include_jumper=True)).rows
    assert [r.status for r in rows] == ["invalid", "invalid"]
    assert all("Technologie: Pflichtfeld ist leer." in r.messages for r in rows)
    assert not any("Toleranz" in m or "Leistung" in m for m in rows[1].messages)


def test_part_number_errors_are_reported_like_db_parts(workspace: Workspace) -> None:
    normalizer = _Normalizer(categories.get_category("Resistors"), workspace.root)
    values, unknown, errors = normalizer.row({"Part Number": "AB'C|D", "Resistance": "10k", "Gibt es nicht": "x"})
    assert values["Resistance"] == "10kΩ" and unknown == ["Gibt es nicht"]
    assert len(errors) == 1 and errors[0].startswith("Teilenummer: Die Teilenummer enthält unzulässige Zeichen")


@pytest.mark.parametrize("column", ["Part Number", "manufacturer part number"])
def test_part_numbers_cannot_be_fixed(workspace: Workspace, column: str) -> None:
    with pytest.raises(SeriesError, match="kommt aus der Vorlage"):
        preview(req(field_overrides={column: "X"}))


# --------------------------------------------------------------------------- sizes and packaging


@pytest.mark.parametrize(("template_id", "typed", "size"), [
    ("samsung-cl-x7r", "1005", "0402"),  # metric 1005 is EIA 0402 – not the 01005 size
    ("samsung-cl-x7r", "1608", "0603"),
    ("samsung-cl-x7r", "0603M", "0201"),
    ("samsung-cl-x7r", "0603", "0603"),  # imperial wins without the metric suffix (footprint convention)
    ("samsung-cl-x7r", "01005", "01005"),
    ("vishay-crcw-e3", "1005", "0402"),
])
def test_sizes_are_never_matched_numerically(workspace: Workspace, template_id: str, typed: str, size: str) -> None:
    """Regression: "1005" was resolved numerically to the 01005 size of Samsung CL."""
    result = preview(SeriesRequest(template_id=template_id, sizes=[typed], max_rows=5000))
    assert result.rows and {r.size for r in result.rows} == {size}


@pytest.mark.parametrize("typed", ["402", "603", "0.603", "1e3"])
def test_size_spellings_without_a_meaning_are_refused(workspace: Workspace, typed: str) -> None:
    with pytest.raises(SeriesError, match="gibt es in der Serie"):
        preview(req(sizes=[typed]))


def test_marked_reel_falls_back_to_the_unmarked_reel_of_the_same_size(workspace: Workspace) -> None:
    """KEMET p. 20: no laser marking for small capacitance values – TM becomes TU, 7215 becomes 7210."""
    result = preview(SeriesRequest(template_id="kemet-c-x7r", sizes=["0603", "0805", "0402"], voltages=["50V"],
                                   values=["100p", "100n"], packaging="TM"))
    by = {(r.size, r.value): r for r in result.rows}
    assert by[("0603", "100nF")].mpn == "C0603C104K5RACTM" and by[("0603", "100nF")].status == "new"
    small = by[("0603", "100pF")]
    assert small.mpn == "C0603C101K5RACTU" and small.status == "new"
    assert any("„TM“ gibt es für dieses Bauteil nicht – „TU“ verwendet" in m for m in small.messages)
    assert by[("0402", "100nF")].mpn == "C0402C104K5RACTU"  # 0402: TM does not exist at all
    assert any("TM" in w and "0402" in w for w in result.warnings)
    assert any("passt nicht zu 2 Bauteilen" in w for w in result.warnings)
    reel13 = preview(SeriesRequest(template_id="kemet-c-x7r", sizes=["0805"], voltages=["50V"],
                                   values=["100p", "100n"], packaging="7215"))
    assert {r.mpn for r in reel13.rows} == {"C0805C101K5RAC7210", "C0805C104K5RAC7215"}


def test_thick_parts_keep_the_requested_reel_size(workspace: Workspace) -> None:
    """YAGEO CC: 13" paper (P) for a part on blister tape becomes 13" blister (F), not the 7" default."""
    result = preview(SeriesRequest(template_id="yageo-cc-x7r", sizes=["0805"], voltages=["16V"],
                                   values=["100n", "10u"], packaging="P"))
    assert {r.mpn for r in result.rows} == {"CC0805KPX7R7BB104", "CC0805KFX7R7BB106"}
