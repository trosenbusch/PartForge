"""Series assistant preview: rows, statuses, values exactly like manual entries, footprints, symbol."""
from __future__ import annotations

import time
from typing import Any

import pytest

from partforge.db import parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.domain.series import SeriesError, SeriesRequest, preview
from partforge.workspace import Workspace


def req(**kw: Any) -> SeriesRequest:
    base: dict[str, Any] = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "tolerance": "1%", "e_series": "E24",
                            "range_min": "1", "range_max": "10M"}
    base.update(kw)
    return SeriesRequest.model_validate(base)


def manual(table: str, pn: str, **values: Any) -> dict[str, Any]:
    data = {"Part Number": pn, "Manufacturer": "Vishay", "Manufacturer Part Number": pn, "Resistance": "10k",
            "Tolerance": "1%", "Power": "0.1W", "Library Ref": "RES", "Footprint Ref": "RESC1608X50N", **values}
    if table == "Capacitors":
        data = {"Part Number": pn, "Manufacturer": "x", "Manufacturer Part Number": pn, "Capacitance": "1n",
                "Voltage": "50V", "Library Ref": "CAP", "Footprint Ref": "C"}
    return parts.create_part(table, data)


def test_e24_series_with_jumper(workspace: Workspace) -> None:
    result = preview(req(include_jumper=True))
    assert result.counts == {"total": 170, "new": 170, "exists": 0, "conflict": 0, "invalid": 0}
    assert result.table == "Resistors" and result.template["id"] == "vishay-crcw-e3"
    first, jumper = result.rows[0], result.rows[-1]
    assert first.mpn == first.part_number == "CRCW06031R00FKEA" and first.value == "1Ω"
    assert jumper.jumper and jumper.mpn == "CRCW06030000Z0EA" and jumper.values["Resistance"] == "0Ω"
    assert jumper.values.get("Tolerance") is None and jumper.values["Notes"].startswith("0-Ω-Brücke")
    row = next(r for r in result.rows if r.mpn == "CRCW060310K0FKEA")
    assert row.values["Resistance"] == "10kΩ" and row.values["Tolerance"] == "±1%" and row.values["TCR"] == "±100ppm/K"
    assert row.values["Operating Temperature"] == "-55°C … 155°C" and row.values["Height"] == "0.5mm"
    assert row.values["Value"] == "10kΩ" and row.values["Comment"] == "10k"
    assert row.values["Description"] == "RES 0603 10kΩ ±1% 0.1W Dickschicht"
    assert row.values["ComponentLink1Description"] == "Datenblatt"
    assert row.values["ComponentLink1URL"] == "https://www.vishay.com/docs/20035/dcrcwe3.pdf"
    assert row.values["Lifecycle"] == "Aktiv" and row.values["PF Status"] == "Entwurf"
    assert row.values["Library Ref"] == "Resistor" and row.values["Footprint Ref"] == "RESC1608X50N"
    assert row.footprint is not None and row.footprint.family == "chip" and not row.footprint.exists
    assert result.symbol is not None and result.symbol.name == "Resistor" and not result.symbol.exists
    assert [f.name for f in result.footprints_needed] == ["RESC1608X50N"]


def test_values_equal_manual_entry(workspace: Workspace) -> None:
    """The preview stores exactly what a manual entry of the same texts would store."""
    row = next(r for r in preview(req()).rows if r.mpn == "CRCW06034K70FKEA")
    typed = {"Part Number": "MANUAL-1", "Manufacturer": "Vishay", "Manufacturer Part Number": "MANUAL-1",
             "Resistance": "4k7", "Tolerance": "1 %", "Power": "1/10W", "Voltage": "75 V", "TCR": "±100ppm",
             "Technology": "Dickschicht", "Size": "0603", "Height": "0.5", "Operating Temperature": "-55 to 155",
             "Library Ref": "Resistor", "Footprint Ref": "RESC1608X50N"}
    stored = parts.create_part("Resistors", typed)
    for column in ("Resistance", "Tolerance", "Power", "Voltage", "TCR", "Technology", "Size", "Height",
                   "Operating Temperature", "Value", "Comment"):
        assert row.values[column] == stored[column], column
    assert row.values["Description"] == stored["Description"]


def test_e24_e96_counts(workspace: Workspace) -> None:
    assert preview(req(e_series="E24+E96")).counts["new"] == 799
    assert preview(req(tolerance="5%", e_series=None)).counts["new"] == 169
    by_default = preview(req(e_series=None))  # 1 %: datasheet series E24 + E96
    assert by_default.counts["new"] == 799


def test_statuses_with_existing_parts(workspace: Workspace) -> None:
    manual("Resistors", "CRCW060310K0FKEA")
    manual("Resistors", "CRCW06031K00FKEA", **{"Manufacturer Part Number": "OTHER-MPN"})
    manual("Capacitors", "CRCW06034K70FKEA")
    result = preview(req(values=["10k", "1k", "4.7k", "2.2k", "4.99k"], e_series=None, tolerance="5%"))
    by_value = {r.value: r for r in result.rows}
    assert by_value["10kΩ"].status == "new"  # 5 % part number differs (CRCW060310K0JNEA)
    result = preview(req(values=["10k", "1k", "4.7k", "2.2k", "4.99k"]))
    by_value = {r.value: r for r in result.rows}
    assert by_value["10kΩ"].status == "exists" and by_value["10kΩ"].part_number == "CRCW060310K0FKEA"
    assert by_value["1kΩ"].status == "conflict" and "vergeben" in by_value["1kΩ"].messages[0]
    assert by_value["4.7kΩ"].status == "conflict"
    assert by_value["2.2kΩ"].status == "new"
    assert by_value["4.99kΩ"].status == "new"  # 1 %: E96 value is fine
    invalid = preview(req(values=["4.99k", "22M"], tolerance="5%"))
    assert [r.status for r in invalid.rows] == ["invalid", "invalid"]
    assert "E24" in invalid.rows[0].messages[0] and "außerhalb" in invalid.rows[1].messages[0]
    assert result.counts == {"total": 5, "new": 2, "exists": 1, "conflict": 2, "invalid": 0}


def test_case_insensitive_existing_part_number(workspace: Workspace) -> None:
    manual("Resistors", "crcw060310k0fkea", **{"Manufacturer Part Number": "crcw060310k0fkea"})
    row = preview(req(values=["10k"])).rows[0]
    assert row.status == "exists" and row.part_number == "crcw060310k0fkea"


@pytest.mark.parametrize(("change", "message"), [
    ({"sizes": ["0201"]}, "Baugröße"),
    ({"tolerance": "2%"}, "möglich"),
    ({"tolerance": "Z"}, "Brücke"),
    ({"tcr": "±50ppm/K"}, "Temperaturkoeffizient"),
    ({"range_min": "zehn"}, "kein gültiger Wert"),
    ({"range_min": "10M", "range_max": "1"}, "obere Grenze"),
    ({"e_series": "E25"}, "E-Reihe"),
    ({"values": ["10uF"]}, "kein gültiger Wert"),
    ({"voltages": ["50V"]}, "Spannungsauswahl"),
    ({"dielectrics": ["X7R"]}, "Dielektrikum"),
    ({"packaging": "ZZ"}, "Verpackung"),
    ({"sizes": ["0603", "0402", "0805"], "e_series": "E24+E96", "max_rows": 1000}, "höchstens 1000"),
    ({"part_number_scheme": "internal"}, "Interne Teilenummern"),
])
def test_request_errors(workspace: Workspace, change: dict[str, Any], message: str) -> None:
    with pytest.raises(SeriesError) as info:
        preview(req(**change))
    assert message in str(info.value)


def test_unknown_template(workspace: Workspace) -> None:
    from partforge.domain.mpn import TemplateNotFound

    with pytest.raises(TemplateNotFound):
        preview(req(template_id="nope"))


def test_size_aliases(workspace: Workspace) -> None:
    assert preview(req(sizes=["1608"], values=["10k"])).rows[0].size == "0603"  # metric code
    koa = preview(SeriesRequest(template_id="koa-rk73h", sizes=["1J"], values=["10k"]))
    assert koa.rows[0].size == "0603" and koa.rows[0].mpn == "RK73H1JTTD1002F"


def test_tcr_and_packaging_choices(workspace: Workspace) -> None:
    n = preview(req(tcr="±200ppm/K", e_series="E24+E96"))
    assert {r.mpn[-4:-2] for r in n.rows} == {"FN"} and max(r.values["Resistance"] for r in n.rows if r.value)
    assert all(parts_value(r) <= 9.76 for r in n.rows)
    koa = preview(SeriesRequest(template_id="koa-rk73h", sizes=["0805"], tcr="±200ppm/K", range_min="1",
                                range_max="10M"))
    assert koa.rows and all(r.values["TCR"] == "±200ppm/K" for r in koa.rows)
    packed = preview(req(sizes=["0603", "0402"], packaging="EC", values=["10k"]))
    assert {r.mpn for r in packed.rows} == {"CRCW060310K0FKEC", "CRCW040210K0FKED"}
    assert any("EC" in w and "0402" in w for w in packed.warnings)


def parts_value(row: Any) -> float:
    from partforge.domain.units import parse_value

    value = parse_value(row.values["Resistance"], "Ω")
    assert value is not None
    return value


def test_skipped_values_are_reported(workspace: Workspace) -> None:
    result = preview(req(tolerance="5%", e_series="E24+E96"))
    assert result.counts["new"] == 169
    assert any("ausgelassen" in w for w in result.warnings)


def test_matrix_template_and_footprint_heights(workspace: Workspace) -> None:
    base = {"template_id": "kemet-c-x7r", "sizes": ["0603"], "voltages": ["50V"], "e_series": "E6"}
    result = preview(SeriesRequest.model_validate(base))
    values = {r.value for r in result.rows}
    assert "100nF" in values and "1µF" not in values  # 0603 / 50 V ends at 220 nF
    assert all(r.status == "new" for r in result.rows)
    assert all(r.values["Voltage"] == "50V" and r.values["Dielectric"] == "X7R" for r in result.rows)
    row = next(r for r in result.rows if r.value == "100nF")
    assert row.mpn == "C0603C104K5RACTU" and row.values["Height"] == "0.95mm"
    classes = {r.footprint.name for r in result.rows if r.footprint}
    standard = preview(SeriesRequest.model_validate({**base, "footprint_height": "standard"}))
    exact = preview(SeriesRequest.model_validate({**base, "footprint_height": "exact"}))
    assert {r.footprint.name for r in standard.rows if r.footprint} == {"CAPC1608X87N"}
    assert "CAPC1608X87N" in classes and len(classes) >= 2
    assert len({r.footprint.name for r in exact.rows if r.footprint}) >= len(classes)


def test_matrix_explicit_values_and_tolerance(workspace: Workspace) -> None:
    result = preview(SeriesRequest(template_id="kemet-c-x7r", sizes=["0402"], voltages=["25V"],
                                   values=["100n", "1u"], tolerance="5%"))
    by_value = {r.value: r for r in result.rows}
    assert by_value["100nF"].status == "invalid" and "±5%" in by_value["100nF"].messages[0]  # K/M only
    assert by_value["1µF"].status == "invalid"
    ok = preview(SeriesRequest(template_id="kemet-c-x7r", sizes=["0402"], voltages=["25V"], values=["100n"]))
    assert ok.rows[0].status == "new" and ok.rows[0].mpn == "C0402C104K3RACTU"


def test_matrix_skips_cells_of_other_tolerances(workspace: Workspace) -> None:
    result = preview(SeriesRequest(template_id="samsung-cl-x7r", sizes=["0805"]))
    assert result.counts["new"] > 0
    assert any("nur in anderen Toleranzen" in w for w in result.warnings)


def test_validate_without_rows(workspace: Workspace) -> None:
    from partforge.domain.series import validate

    validate(req())
    with pytest.raises(SeriesError, match="Toleranz"):
        validate(req(tolerance="7%"))


def test_yageo_and_samsung_previews(workspace: Workspace) -> None:
    yageo = preview(SeriesRequest(template_id="yageo-cc-x7r", sizes=["0805"], voltages=["16V"]))
    assert {r.mpn[7] for r in yageo.rows} == {"R", "K"}  # paper and blister tape by thickness
    samsung = preview(SeriesRequest(template_id="samsung-cl-x7r", sizes=["0805"], voltages=["50V"], values=["100n"]))
    assert {r.mpn for r in samsung.rows} == {"CL21B104KBCNNNC", "CL21B104KBFNNNE"}
    assert all(any("nicht geprüft" in m for m in r.messages) for r in samsung.rows)
    with pytest.raises(SeriesError, match="Dielektrikum"):
        preview(SeriesRequest(template_id="kemet-c-x7r", sizes=["0603"], dielectrics=["C0G"]))
    with pytest.raises(SeriesError, match="Nennspannung"):
        preview(SeriesRequest(template_id="kemet-c-x7r", sizes=["0603"], voltages=["42V"]))


def test_catalog_template(workspace: Workspace) -> None:
    result = preview(SeriesRequest(template_id="bourns-srr1260", range_min="10u", range_max="100u"))
    assert [r.mpn for r in result.rows][:3] == ["SRR1260-100M", "SRR1260-120M", "SRR1260-150M"]
    assert len(result.rows) == 13 and result.table == "Inductors"
    assert result.rows[0].values["Saturation Current"] == "5.5A" and result.rows[0].values["Shielding"] == "geschirmt"
    assert result.symbol is not None and result.symbol.name == "Inductor"
    assert result.rows[0].footprint is not None and result.rows[0].footprint.family == "molded"
    missing = preview(SeriesRequest(template_id="bourns-srr1260", values=["10u", "11u"]))
    assert len(missing.rows) == 1 and any("11u" in w for w in missing.warnings)
    tol = preview(SeriesRequest(template_id="bourns-srr1260", tolerance="10%"))
    assert len(tol.rows) == 12 and all(r.mpn.endswith("K") for r in tol.rows)


def test_existing_footprint_and_symbol_are_reported(workspace: Workspace) -> None:
    registry.upsert_footprint(FootprintRecord(name="RESC1608X50N", library="Footprints\\PF_CHIP.PcbLib",
                                              family="chip", status="ok"))
    registry.upsert_symbol(SymbolRecord(name="Resistor", library="Symbols\\PF_Passives.SchLib", status="ok"))
    result = preview(req(values=["10k"]))
    assert result.footprints_needed == [] and result.footprints[0].exists
    assert result.footprints[0].library == "Footprints\\PF_CHIP.PcbLib" and result.footprints[0].status == "ok"
    assert result.symbol is not None and result.symbol.exists and result.symbol.status == "ok"
    assert result.symbol.library == "Symbols\\PF_Passives.SchLib"


def test_field_overrides_are_cleaned(workspace: Workspace) -> None:
    result = preview(req(values=["10k"], field_overrides={"Notes": "Serie A|B\n", "Supplier 1": "Mouser",
                                                         "Gibt es nicht": "x"},
                         datasheet_url="https://example.com/crcw.pdf"))
    row = result.rows[0]
    assert row.values["Notes"] == "Serie A/B" and row.values["Supplier 1"] == "Mouser"
    assert row.values["ComponentLink1URL"] == "https://example.com/crcw.pdf"
    assert any("Gibt es nicht" in w for w in result.warnings)


def test_internal_part_numbers(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    parts.create_part("Resistors", {"Manufacturer": "Vishay", "Manufacturer Part Number": "CRCW060310K0FKEA",
                                    "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Library Ref": "RES",
                                    "Footprint Ref": "RESC1608X50N"})
    result = preview(req(values=["10k", "4.7k"]))
    by_value = {r.value: r for r in result.rows}
    assert by_value["10kΩ"].status == "exists" and by_value["10kΩ"].part_number.startswith("R-")
    assert by_value["4.7kΩ"].status == "new" and by_value["4.7kΩ"].part_number is None


def test_performance_2000_rows(workspace: Workspace) -> None:
    request = req(sizes=["0603", "0402", "0805"], e_series="E24+E96")
    preview(req(values=["10k"]))  # warm-up: template build, footprint generation
    started = time.perf_counter()
    result = preview(request)
    elapsed = time.perf_counter() - started
    assert result.counts["new"] == 3 * 799
    assert elapsed < 2.0, f"Vorschau zu langsam: {elapsed:.2f} s"
