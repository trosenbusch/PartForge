"""Datasheet import: normalisation of Claude's answers and the plausibility checks (offline)."""
from __future__ import annotations

import json
from typing import Any

import pytest

from partforge.datasheet.models import DimValue, ExtractionData, LandPatternData, PackageData
from partforge.datasheet.normalize import (
    GEOMETRY_ISSUES,
    IDENTITY_ISSUES,
    is_exposed_pad_pin,
    map_electrical,
    match_category,
    merge_packages,
    normalize_extraction,
    overbar_name,
    resolve_family,
    validate_extraction,
)
from partforge.datasheet.schema import AiGeometry, AiIdentity, AiPackageRef, AiPin
from partforge.db.categories import builtin_templates

CATEGORIES = builtin_templates()
NA = -1


def pin(number: str, name: str, etype: str = "Input", **kw: Any) -> dict[str, Any]:
    return {"number": number, "name": name, "function": kw.pop("function", ""), "electrical_type": etype,
            "active_low": kw.pop("active_low", False), "no_connect": kw.pop("no_connect", False),
            "group": kw.pop("group", ""), "part": kw.pop("part", 1)}


def dim(symbol: str, lo: float = NA, nom: float = NA, hi: float = NA, unit: str = "mm", desc: str = "") -> dict:
    return {"symbol": symbol, "description": desc, "unit": unit, "min": lo, "nom": nom, "max": hi}


def land(**kw: Any) -> dict[str, Any]:
    base = {"present": False, "source_pages": [], "pad_shape": "unknown", "pad_width": NA, "pad_length": NA,
            "pitch": NA, "row_spacing": NA, "row_spacing_reference": "not_applicable", "thermal_pad_width": NA,
            "thermal_pad_length": NA, "solder_mask_expansion": NA, "notes": ""}
    base.update(kw)
    return base


SOIC_DIMS = [dim("D", 4.8, NA, 5.0), dim("E1", 3.8, NA, 4.0), dim("E", 5.8, NA, 6.2), dim("e", NA, 1.27, NA),
             dim("b", 0.31, NA, 0.51), dim("L", 0.4, NA, 1.27), dim("A", NA, NA, 1.75), dim("theta", 0, NA, 8, "deg")]


def package(code: str = "D", name: str = "SOIC-8", family: str = "gullwing", pins: int = 8, **kw: Any) -> dict:
    return {"package_code": code, "package_name": name, "family": family, "pin_count": pins,
            "mounting": kw.pop("mounting", "SMD"), "outline_reference": kw.pop("outline_reference", ""),
            "exposed_pad": kw.pop("exposed_pad", False), "exposed_pad_number": kw.pop("exposed_pad_number", ""),
            "source_pages": kw.pop("source_pages", [3]), "dimensions": kw.pop("dimensions", SOIC_DIMS),
            "land_pattern": kw.pop("land_pattern", land())}


def identity(*, devices: list[dict] | None = None, packages: list[dict] | None = None, **kw: Any) -> AiIdentity:
    soic_pins = [pin("1", "NC", "Passive", no_connect=True), pin("2", "-IN"), pin("3", "+IN"),
                 pin("4", "V−", "Power"), pin("5", "NC", "Passive"), pin("6", "OUT", "Output"),
                 pin("7", "V+", "Power"), pin("8", "N/C", "Passive")]
    device = {"base_part_number": "OPA656", "description": "Op amp | wideband", "category": "Amplifiers",
              "parameters": [{"column": "Amplifier Type", "value": "operationsverstärker", "page": 1},
                             {"column": "gbw", "value": "230 MHz", "page": 1},
                             {"column": "Channels", "value": "1", "page": NA},
                             {"column": "Unbekannt", "value": "x", "page": 1},
                             {"column": "Manufacturer", "value": "TI", "page": 1}],
              "variants": [{"mpn": "OPA656U", "package_code": "d", "temperature_range": "-40°C to 85°C",
                            "packaging": "Rails, 100", "status": "ACTIVE", "notes": "", "values": [], "page": 2},
                           {"mpn": "opa656u", "package_code": "D", "temperature_range": "", "packaging": "",
                            "status": "", "notes": "", "values": [], "page": 2}],
              "pin_tables": [{"package_code": "SOIC-8", "source_pages": [2], "pins": soic_pins}]}
    data = {"manufacturer": "Texas Instruments", "document_id": "SBOS196G", "document_title": "OPA656",
            "document_date": "2008", "devices": devices if devices is not None else [device],
            "packages": packages if packages is not None else [
                {"package_code": "D", "package_name": "SOIC-8", "pin_count": 8, "exposed_pad": False}],
            "warnings": kw.pop("warnings", ["Rails 100 vs 75"])}
    return AiIdentity.model_validate(data)


def geometry(*packages: dict, warnings: list[str] | None = None) -> AiGeometry:
    return AiGeometry.model_validate({"packages": list(packages) or [package()], "warnings": warnings or []})


# --------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(("name", "active_low", "expected"), [
    ("CS", True, "C\\S\\"),
    ("/RESET", True, "R\\E\\S\\E\\T\\"),
    ("~WR", True, "W\\R\\"),
    ("RESET#", True, "R\\E\\S\\E\\T\\"),
    ("TCLK_R/F\\", True, "TCLK_R/F\\"),
    ("C\\\\S\\", True, "C\\S\\"),
    ("\\CS", False, "CS"),
    ("CS", False, "CS"),
    ("OUT A", True, "O\\U\\T\\ A\\"),
    ("", True, ""),
])
def test_overbar_name(name, active_low, expected):
    assert overbar_name(name, active_low) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("Input", "input"), ("IO", "io"), ("output", "output"), ("OpenCollector", "open_collector"),
    ("Open_Drain", "open_collector"), ("HiZ", "hiz"), ("OpenEmitter", "open_emitter"), ("POWER", "power"),
    ("Passive", "passive"), ("bidirectional", "io"), ("???", "passive"), ("", "passive"),
])
def test_map_electrical(value, expected):
    assert map_electrical(value) == expected


@pytest.mark.parametrize(("number", "name", "function", "pin_count", "ep_number", "expected"), [
    ("EP", "GND", "", 8, "", True), ("PAD", "", "", None, "", True), ("EP1", "PGND", "", 16, "", True),
    ("9", "V-", "Exposed pad, connect to V-", 8, "", True),  # beyond the leads + described as exposed pad
    ("33", "GND", "Thermal pad", 32, "", True),
    ("17", "EPAD", "", None, "", True), ("17", "EP", "", 16, "", True), ("0", "GND", "Exposed die pad", 16, "", True),
    ("9", "GND", "", 8, "9", True),  # the package names its exposed-pad number
    # regressions: free text never turns a lead into the exposed pad
    ("5", "GND", "Ground. Connect to the thermal pad.", 16, "", False),
    ("3", "PGND", "Power ground, connect exposed pad to PGND", 16, "", False),
    ("7", "VOUT", "Output; solder to heat sink copper", 8, "", False),
    ("7", "VOUT", "Output; solder to heat sink copper", None, "", False),  # unknown package size
    ("33", "GND", "Thermal pad", None, "", False),
    ("5", "GND", "Ground", None, "", False), ("0", "GND", "", None, "", False), ("8", "PAD", "", 8, "", False),
])
def test_exposed_pad_detection(number, name, function, pin_count, ep_number, expected):
    assert is_exposed_pad_pin(number, name, function, pin_count=pin_count, ep_number=ep_number) is expected


def test_ground_pin_that_mentions_the_thermal_pad_stays_a_lead():
    """Reviewer case h3: VQFN-16 with GND (pin 5) 'connect to the thermal pad' and a separate EP row."""
    names = ["IN", "IN", "EN", "NC", "GND", "FB", "PG", "NC", "OUT", "OUT", "NC", "NC", "NC", "NC", "NC", "NC"]
    pins = [pin(str(i), n, "Power" if n in ("IN", "GND") else "Input",
                function="Ground. Connect to the thermal pad." if n == "GND" else "") for i, n in enumerate(names, 1)]
    pins.append(pin("EP", "PAD", "Power", function="Exposed thermal pad, connect to GND"))
    ident = identity(devices=[{"base_part_number": "TPSX123", "description": "LDO", "category": "Power Linear",
                               "parameters": [], "variants": [], "pin_tables": [
                                   {"package_code": "RGT", "source_pages": [], "pins": pins}]}],
                     packages=[{"package_code": "RGT", "package_name": "VQFN-16 3x3", "pin_count": 16,
                                "exposed_pad": True}])
    geo = geometry(package("RGT", "VQFN-16 3x3", "nolead", 16, exposed_pad=True, dimensions=[
        dim("D", 2.9, 3.0, 3.1), dim("E", 2.9, 3.0, 3.1), dim("e", NA, 0.5, NA), dim("b", 0.18, 0.24, 0.3),
        dim("L", 0.3, 0.4, 0.5), dim("D2", 1.6, 1.7, 1.8), dim("E2", 1.6, 1.7, 1.8)]))
    data = normalize_extraction(ident, geo, pages=[1], categories=CATEGORIES)
    flagged = [(p.number, p.name) for p in data.devices[0].pin_tables[0].pins if p.exposed_pad]
    assert flagged == [("EP", "PAD")]
    assert not [i for i in data.issues if i.severity == "error"]


def test_match_category():
    assert match_category("Amplifiers", CATEGORIES).table == "Amplifiers"
    assert match_category("verstärker", CATEGORIES).table == "Amplifiers"
    assert match_category("Operational Amplifier", CATEGORIES).table == "Amplifiers"
    assert match_category("LDO", CATEGORIES).table == "Power Linear"
    assert match_category("", CATEGORIES, context="16-bit ADC").table == "Data Converters"
    assert match_category("Something", CATEGORIES).table == "Integrated Circuits"
    assert match_category("x", []) is None
    only_amps = [c for c in CATEGORIES if c.table == "Amplifiers"]
    assert match_category("EEPROM", only_amps) is None


def test_resolve_family_prefers_the_package_name():
    assert resolve_family("SOIC-8", "D", "qfp") == "gullwing"
    assert resolve_family("8-Lead Plastic Small Outline", "SN", "gullwing") == "gullwing"
    assert resolve_family("", "DFN-8", "other") == "nolead"
    assert resolve_family("Wunderbox", "WB", "other") is None
    assert resolve_family("Wunderbox", "WB", "Bga") == "bga"


# --------------------------------------------------------------------------- normalize


def test_normalize_identity_and_geometry():
    data = normalize_extraction(identity(), geometry(), pages=[1, 2, 17], geometry_pages=[21, 22, 23],
                                categories=CATEGORIES)
    assert data.manufacturer == "Texas Instruments" and data.document_id == "SBOS196G"
    assert data.warnings == ["Rails 100 vs 75"]
    device = data.devices[0]
    assert device.category == "Amplifiers" and device.description == "Op amp / wideband"
    params = {p.column: p for p in device.parameters}
    assert set(params) == {"Amplifier Type", "GBW", "Channels"}  # unknown and PartForge-owned fields dropped
    assert params["Amplifier Type"].value == "Operationsverstärker"
    assert params["GBW"].value == "230MHz" and params["GBW"].raw == "230 MHz" and params["GBW"].page == 1
    assert params["Channels"].page is None
    assert [v.mpn for v in device.variants] == ["OPA656U"]  # case-insensitive duplicate dropped
    variant = device.variants[0]
    assert variant.package == "D" and variant.pages == [2] and variant.temperature_range == "-40°C to 85°C"
    table = device.pin_tables[0]
    assert table.package == "D" and table.pages == [2]
    names = {p.number: p for p in table.pins}
    assert names["4"].name == "V-" and names["4"].electrical == "power"
    assert names["1"].no_connect and names["5"].no_connect and names["8"].no_connect
    pkg = data.packages[0]
    assert pkg.code == "D" and pkg.family == "gullwing" and pkg.pin_count == 8 and pkg.pages == [23]
    assert pkg.dim("e").nom == 1.27 and pkg.dim("D").nom is None and pkg.dim("D").value() == pytest.approx(4.9)
    assert pkg.dim("theta") is None  # angles are not mm dimensions
    assert data.issues == []
    assert data.mpns() == ["OPA656U"]


def test_page_mapping_drops_invalid_pages():
    ident = identity()
    ident.devices[0].pin_tables[0].source_pages = [0, 2, 9]
    data = normalize_extraction(ident, geometry(package(source_pages=[1, 2, 3])), pages=[1, 2, 17],
                                geometry_pages=[21, 23])
    assert data.devices[0].pin_tables[0].pages == [2]
    assert data.packages[0].pages == [21, 23]


def test_active_low_pins_and_parts():
    pins = [pin("1", "CS", active_low=True), pin("2", "WP\\", active_low=False), pin("3", "VSS", "Power", part=0),
            pin("4", "OUT A", "Output", part=1), pin("5", "OUT B", "Output", part=2), pin("6", "X", part=99)]
    ident = identity(devices=[{"base_part_number": "X1", "description": "", "category": "Integrated Circuits",
                               "parameters": [], "variants": [], "pin_tables": [
                                   {"package_code": "D", "source_pages": [], "pins": pins}]}],
                     packages=[{"package_code": "D", "package_name": "SOIC-8", "pin_count": 6, "exposed_pad": False}])
    data = normalize_extraction(ident, geometry(package(pins=6)), pages=[1])
    got = {p.number: p for p in data.devices[0].pin_tables[0].pins}
    assert got["1"].name == "C\\S\\" and got["1"].active_low
    assert got["2"].name == "WP\\" and got["2"].active_low
    assert [got[n].part for n in "3456"] == [0, 1, 2, 1]


def test_exposed_pad_pin_and_package_number():
    ident = identity(devices=[{"base_part_number": "LTC6244", "description": "", "category": "Amplifiers",
                               "parameters": [], "variants": [], "pin_tables": [
                                   {"package_code": "DD", "source_pages": [],
                                    "pins": [pin(str(i), f"P{i}") for i in range(1, 9)] + [pin("9", "V-", "Power")]}]}],
                     packages=[{"package_code": "DD", "package_name": "DFN-8 3x3", "pin_count": 8, "exposed_pad": True}])
    geo = geometry(package("DD", "DFN-8 3x3", "nolead", 8, exposed_pad=True, exposed_pad_number="9", dimensions=[
        dim("D", 2.9, 3.0, 3.1), dim("E", 2.9, 3.0, 3.1), dim("e", NA, 0.5, NA), dim("b", 0.2, 0.25, 0.3),
        dim("L", 0.3, 0.4, 0.5), dim("D2", 2.28, 2.38, 2.48), dim("E2", 1.55, 1.65, 1.75)]))
    data = normalize_extraction(ident, geo, pages=[2], categories=CATEGORIES)
    pins = data.devices[0].pin_tables[0].pins
    assert pins[-1].exposed_pad and not any(p.exposed_pad for p in pins[:-1])
    assert [i.code for i in data.issues] == ["no_variants"]  # EP pin 9 + 8 leads: consistent


def test_multi_device_and_duplicate_base_parts():
    dev = {"base_part_number": "SER", "description": "", "category": "Integrated Circuits", "parameters": [],
           "variants": [], "pin_tables": []}
    ident = identity(devices=[dev, dict(dev), {**dev, "base_part_number": ""}])
    data = normalize_extraction(ident, geometry(), pages=[1])
    assert [d.base_part for d in data.devices] == ["SER", "SER (2)", "Bauteil 3"]


# --------------------------------------------------------------------------- merge


def _pkg(code: str, name: str, pins: int | None, **kw: Any) -> PackageData:
    return PackageData(code=code, name=name, pin_count=pins, **kw)


def test_merge_packages_by_code_name_and_pin_count():
    refs = [AiPackageRef(package_code="D", package_name="SOIC-8", pin_count=8, exposed_pad=False),
            AiPackageRef(package_code="DBV", package_name="SOT-23-5", pin_count=5, exposed_pad=False),
            AiPackageRef(package_code="RHB", package_name="VQFN-32", pin_count=32, exposed_pad=False),
            AiPackageRef(package_code="X", package_name="Mystery-6", pin_count=6, exposed_pad=True)]
    drawn = [_pkg("SOT-23-5", "SOT-23-5", 5, family="sot23"), _pkg("d", "SOIC", 8, family="gullwing"),
             _pkg("32-QFN", "QFN", 32, family="nolead", exposed_pad=True), _pkg("Z", "Extra-14", 14)]
    merged, notes = merge_packages(refs, drawn)
    by_code = {p.code: p for p in merged}
    assert list(by_code) == ["D", "DBV", "RHB", "X", "Z"]
    assert by_code["D"].family == "gullwing" and by_code["DBV"].family == "sot23"
    assert by_code["RHB"].exposed_pad and by_code["RHB"].family == "nolead"  # matched by the pin count
    assert by_code["X"].exposed_pad and by_code["X"].dimensions == [] and by_code["X"].pin_count == 6
    assert notes == []
    merged, notes = merge_packages([AiPackageRef(package_code="D", package_name="SOIC-8", pin_count=8,
                                                 exposed_pad=False)], [_pkg("D", "SOIC-8", 14)])
    assert merged[0].pin_count == 8 and "laut Gehäusezeichnung 14" in notes[0]


def test_unique_codes_for_duplicates():
    refs = [AiPackageRef(package_code="D", package_name="SOIC-8", pin_count=8, exposed_pad=False),
            AiPackageRef(package_code="D", package_name="SOIC-14", pin_count=14, exposed_pad=False)]
    merged, _ = merge_packages(refs, [])
    assert [p.code for p in merged] == ["D", "D-2"]


# --------------------------------------------------------------------------- validation


def _issues(data: ExtractionData) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for issue in validate_extraction(data):
        out.setdefault(issue.code, []).append(issue.message)
    return out


def test_pin_count_and_duplicates_are_errors():
    ident = identity()
    pins = ident.devices[0].pin_tables[0].pins
    ident.devices[0].pin_tables[0].pins = [*pins[:6], pins[0]]  # 7 pins for 8 leads, pin 1 twice
    data = normalize_extraction(ident, geometry(), pages=[1, 2])
    issues = _issues(data)
    assert "pin_count" in issues and "pin_duplicate" in issues
    assert all(i.vision for i in data.issues if i.code in ("pin_count", "pin_duplicate"))
    assert {"pin_count", "pin_duplicate"} <= IDENTITY_ISSUES


def test_dimension_checks():
    dims = [dim("D", 5.0, NA, 4.8), dim("E1", 3.8, 5.0, 4.0), dim("E", 5.8, NA, 6.2), dim("e", NA, 1.27, NA),
            dim("b", 1.3, NA, 1.4), dim("L", -0.4, NA, 1.27), dim("A", NA, NA, 0.1), dim("A1", 0.1, NA, 0.25)]
    data = normalize_extraction(identity(), geometry(package(dimensions=dims)), pages=[1])
    issues = _issues(data)
    assert {"dim_order", "dim_negative", "lead_width", "height"} <= set(issues)
    assert len(issues["dim_order"]) == 2
    assert {"dim_order", "dim_negative", "lead_width"} <= GEOMETRY_ISSUES


def test_missing_dimensions_and_family():
    data = normalize_extraction(identity(), geometry(package(dimensions=[dim("e", NA, 1.27, NA)])), pages=[1])
    assert "Gehäusemaße fehlen: b, L, D, E" in _issues(data)["dims_missing"][0]
    unknown = normalize_extraction(identity(packages=[{"package_code": "W", "package_name": "Wunderbox",
                                                       "pin_count": 8, "exposed_pad": False}]),
                                   geometry(package("W", "Wunderbox", "other", dimensions=[])), pages=[1])
    issues = _issues(unknown)
    assert "unknown_family" in issues and "dims_missing" in issues


def test_inch_values_are_detected():
    dims = [dim("D", 0.189, NA, 0.197), dim("E", 0.228, NA, 0.244), dim("e", NA, 0.05, NA), dim("b", 0.012, NA, 0.02),
            dim("L", 0.016, NA, 0.05)]
    data = normalize_extraction(identity(), geometry(package(dimensions=dims)), pages=[1])
    assert "inch_values" in _issues(data)


def test_land_pattern_checks():
    incomplete = land(present=True, pad_width=0.6, pitch=1.0, row_spacing=4.8, row_spacing_reference="unclear")
    data = normalize_extraction(identity(), geometry(package(land_pattern=incomplete)), pages=[1])
    issues = _issues(data)
    assert {"land_pattern_incomplete", "pitch_mismatch", "row_reference"} <= set(issues)


def test_exposed_pad_mismatch_and_info():
    ident = identity()
    ident.devices[0].pin_tables[0].pins.append(AiPin.model_validate(pin("EP", "GND", "Power")))
    data = normalize_extraction(ident, geometry(), pages=[1])
    assert "exposed_pad" in _issues(data)
    ep_pkg = package(exposed_pad=True, dimensions=SOIC_DIMS + [dim("D2", NA, 2.0, NA), dim("E2", NA, 2.0, NA)])
    data = normalize_extraction(identity(), geometry(ep_pkg), pages=[1])
    infos = [i for i in data.issues if i.code == "exposed_pad_pin"]
    assert infos and infos[0].severity == "info" and not infos[0].vision


def test_structural_issues():
    empty = ExtractionData()
    assert set(_issues(empty)) == {"no_device"}
    ident = identity()
    ident.devices[0].variants = []
    ident.devices[0].pin_tables[0].package_code = "QQ"
    ident.devices[0].category = "nichts davon"
    data = normalize_extraction(ident, geometry(), pages=[1], categories=[c for c in CATEGORIES
                                                                         if c.table == "Amplifiers"])
    issues = _issues(data)
    assert {"no_variants", "pin_table_package"} <= set(issues)
    variant_ident = identity()
    variant_ident.devices[0].variants[0].package_code = "ZZ"
    assert "variant_package" in _issues(normalize_extraction(variant_ident, geometry(), pages=[1]))
    no_cat = normalize_extraction(identity(), geometry(), pages=[1], categories=[])
    assert "category" in _issues(no_cat)


def test_enum_answers_in_any_casing_and_other_units():
    """Enum casing is not guaranteed (research §4.2): every spelling maps to the canonical value."""
    land_pattern = land(present=True, pad_shape="Rounded Rectangle", pad_width=0.6, pad_length=2.0, pitch=1.27,
                        row_spacing=4.8, row_spacing_reference="Center_to_center")
    dims = [dim("D", 0.189, NA, 0.197, unit="inch"), dim("E", 5.8, NA, 6.2, unit="MM"), dim("e", NA, 50, NA, unit="mil"),
            dim("b", 0.31, NA, 0.51, unit="millimetres"), dim("L", 0.4, NA, 1.27), dim("theta", 0, NA, 8, unit="Degrees"),
            dim("X", 1, 2, 3, unit="furlong")]
    ident = identity()
    ident.devices[0].pin_tables[0].pins[1].electrical_type = "input"
    ident.devices[0].pin_tables[0].pins[5].electrical_type = "open drain"
    data = normalize_extraction(ident, geometry(package(mounting="smt", dimensions=dims, land_pattern=land_pattern)),
                                pages=[1])
    pkg = data.packages[0]
    assert pkg.mounting == "SMD" and pkg.land_pattern.pad_shape == "rounded_rectangle"
    assert pkg.land_pattern.row_spacing_reference == "center_to_center"
    assert pkg.dim("D").min == pytest.approx(4.8006) and pkg.dim("D").max == pytest.approx(5.0038)
    assert pkg.dim("e").nom == pytest.approx(1.27) and pkg.dim("b").max == 0.51
    assert pkg.dim("theta") is None and any(d.symbol == "theta" and d.unit == "deg" for d in pkg.dimensions)
    assert not any(d.symbol == "X" for d in pkg.dimensions)
    assert any("unbekannter Einheit „furlong“" in w for w in data.warnings)
    pins = {p.number: p for p in data.devices[0].pin_tables[0].pins}
    assert pins["2"].electrical == "input" and pins["6"].electrical == "open_collector"
    odd = normalize_extraction(identity(), geometry(package(mounting="press-fit", land_pattern=land(
        present=True, pad_shape="Hexagon", row_spacing_reference="whatever"))), pages=[1])
    assert odd.packages[0].mounting is None and odd.packages[0].land_pattern.pad_shape == "other"
    assert odd.packages[0].land_pattern.row_spacing_reference == "unclear"


def test_half_row_spacing_and_overlapping_land_patterns():
    """KEMET Table 3, 0603 level B: C 0.80 = component centre to pad centre (half the centre distance)."""
    half = LandPatternData(present=True, pad_width=1.0, pad_length=0.95, row_spacing=0.8,
                           row_spacing_reference="pad_center_to_component_center")
    assert half.center_distance() == pytest.approx(1.6)
    assert half.to_override() == {"pad_width_mm": 1.0, "pad_length_mm": 0.95, "row_spacing_mm": 1.6,
                                  "row_spacing_reference": "center_to_center"}
    chip_dims = [dim("L", 1.45, 1.6, 1.75), dim("W", 0.65, 0.8, 0.95)]
    chip_ref = [{"package_code": "0603", "package_name": "0603", "pin_count": 2, "exposed_pad": False}]
    for reference, expected in (("unclear", {"row_reference", "land_pattern_overlap"}),
                                ("center_to_center", {"land_pattern_overlap"}),
                                ("pad_center_to_component_center", {"row_reference_half"})):
        lp = land(present=True, pad_width=1.0, pad_length=0.95, row_spacing=0.8, row_spacing_reference=reference)
        data = normalize_extraction(identity(packages=chip_ref),
                                    geometry(package("0603", "0603", "chip", 2, dimensions=chip_dims, land_pattern=lp)),
                                    pages=[1])
        codes = {i.code for i in data.issues if i.package == "0603"}
        assert expected <= codes and ("land_pattern_overlap" in codes) == ("land_pattern_overlap" in expected), reference
    assert "land_pattern_overlap" in GEOMETRY_ISSUES
    from partforge.footprints import preview, request_from_package

    request = request_from_package("chip", chip_dims, land_pattern=half.to_override())
    pads = sorted(preview(request, svg=False).spec.pads, key=lambda p: p.x)
    assert pads[1].x - pads[0].x == pytest.approx(1.6, abs=0.01)


def _edited() -> ExtractionData:
    return normalize_extraction(identity(), geometry(), pages=[1, 2], categories=CATEGORIES)


def test_sanitize_extraction_cleans_user_edits():
    """Reviewer case h11: user edits get the same text hygiene as Claude's answers."""
    from partforge.datasheet.models import ParameterData, PinData
    from partforge.datasheet.normalize import sanitize_extraction

    data = _edited()
    table = data.devices[0].pin_tables[0]
    table.pins[1].name = "SO|DATA=1\x07"
    table.pins[1].function = "Serial out |X=Y\r\n"
    table.pins[2] = table.pins[2].model_copy(update={"name": "RESET#", "active_low": True})
    table.pins.append(PinData(number="EP ", name="GND", function="Exposed pad"))
    data.devices[0].description = "EEPROM | evil\r\nline"
    data.devices[0].category = "Gibt es nicht"
    data.devices[0].parameters.append(ParameterData(column="gbw", value="1 GHz|"))
    data.devices[0].parameters.append(ParameterData(column="Eigenes Feld", value="x\ty"))
    data.devices[0].variants[0].mpn = "OPA656U|X"
    data.packages[0].name = "SOIC-8\x00"
    data.manufacturer = "Texas | Instruments"
    clean = sanitize_extraction(data, categories=CATEGORIES)
    pins = clean.devices[0].pin_tables[0].pins
    assert pins[1].name == "SO/DATA=1" and pins[1].function == "Serial out /X=Y"
    assert pins[2].name == "R\\E\\S\\E\\T\\" and pins[2].active_low
    assert pins[-1].number == "EP" and pins[-1].exposed_pad
    device = clean.devices[0]
    assert device.description == "EEPROM / evil line" and device.category is None
    assert {p.column: p.value for p in device.parameters}["Eigenes Feld"] == "x y"
    assert clean.manufacturer == "Texas / Instruments" and clean.packages[0].name == "SOIC-8"
    assert device.variants[0].mpn == "OPA656U/X"
    assert any(i.code == "category" for i in clean.issues)

    def texts(model: Any) -> list[str]:
        out: list[str] = []
        if isinstance(model, str):
            out.append(model)
        elif isinstance(model, dict):
            for v in model.values():
                out.extend(texts(v))
        elif isinstance(model, list):
            for v in model:
                out.extend(texts(v))
        return out

    assert not [t for t in texts(clean.model_dump()) if "|" in t or any(ord(ch) < 32 for ch in t)]
    amplifiers = sanitize_extraction(_edited(), categories=CATEGORIES)
    assert amplifiers.devices[0].category == "Amplifiers"
    params = {p.column: p for p in amplifiers.devices[0].parameters}
    assert params["GBW"].value == "230MHz"


def test_sanitize_keeps_invalid_values_with_a_reason():
    from partforge.datasheet.models import ParameterData
    from partforge.datasheet.normalize import sanitize_extraction

    data = _edited()
    data.devices[0].parameters = [p for p in data.devices[0].parameters if p.column != "Channels"]
    data.devices[0].parameters.append(ParameterData(column="channels", value="zwei"))
    clean = sanitize_extraction(data, categories=CATEGORIES)
    channels = next(p for p in clean.devices[0].parameters if p.column == "Channels")
    assert channels.value == "zwei" and "keine ganze Zahl" in (channels.warning or "")


def _capacitor(values: dict[str, str], variant_values: dict[str, str]) -> AiIdentity:
    """A KEMET-style capacitor answer with English number formatting (datasheet p. 20: „2,000 pF“, „3,900 pF“)."""
    device = {"base_part_number": "C1206C", "description": "MLCC X7R", "category": "Capacitors",
              "parameters": [{"column": c, "value": v, "page": 1} for c, v in values.items()],
              "variants": [{"mpn": "C1206C392K5RAC", "package_code": "1206", "temperature_range": "",
                            "packaging": "", "status": "", "notes": "", "page": 1,
                            "values": [{"column": c, "value": v, "page": 1} for c, v in variant_values.items()]}],
              "pin_tables": []}
    return identity(devices=[device], packages=[{"package_code": "1206", "package_name": "1206", "pin_count": 2,
                                                 "exposed_pad": False}])


def test_thousands_separators_of_a_datasheet_are_read_as_thousands():
    """INT-03: „3,900 pF“ in an (English) datasheet is 3900 pF – never 3.9 pF; the reading is a visible hint."""
    ident = _capacitor({"Voltage": "1,000V", "Tolerance": "±10%"}, {"Capacitance": "3,900 pF"})
    data = normalize_extraction(ident, geometry(package(code="1206", name="1206", family="chip", pins=2,
                                                        dimensions=[])), pages=[1], categories=CATEGORIES)
    device = data.devices[0]
    params = {p.column: p for p in device.parameters}
    assert params["Voltage"].value == "1kV" and params["Voltage"].raw == "1,000V"
    assert "Tausendertrennzeichen" in params["Voltage"].warning and params["Tolerance"].warning is None
    capacitance = device.variants[0].values[0]
    assert capacitance.value == "3.9nF" and "Tausendertrennzeichen" in capacitance.warning
    # unambiguous commas are read as always: German decimal comma, several groups, a leading zero
    ident = _capacitor({"Voltage": "6,3V"}, {"Capacitance": "1,000,000 pF"})
    data = normalize_extraction(ident, geometry(package(code="1206", name="1206", family="chip", pins=2,
                                                        dimensions=[])), pages=[1], categories=CATEGORIES)
    assert data.devices[0].parameters[0].value == "6.3V" and data.devices[0].parameters[0].warning is None
    assert data.devices[0].variants[0].values[0].value == "1µF"
    # Claude is asked for numbers without thousands separators
    from partforge.datasheet.schema import AiParameter, identity_schema

    assert "without thousands separators" in (AiParameter.model_fields["value"].description or "")
    assert "without thousands separators" in json.dumps(identity_schema())


def test_dim_value_and_land_pattern_helpers():
    assert DimValue(min=1.0, max=3.0).value() == 2.0
    assert DimValue(max=1.75).value() == 1.75
    assert DimValue().value() is None
    lp = LandPatternData(present=True, pad_width=0.6, pad_length=2.0, row_spacing=4.8,
                         row_spacing_reference="center_to_center", thermal_pad_width=2.0, thermal_pad_length=3.0)
    assert lp.to_override() == {"pad_width_mm": 0.6, "pad_length_mm": 2.0, "row_spacing_mm": 4.8,
                                "row_spacing_reference": "center_to_center", "thermal_pad_mm": [2.0, 3.0]}
    assert LandPatternData(present=True, pad_width=0.6).to_override() is None
    assert PackageData(code="D", name="SOIC-8").label == "SOIC-8 (D)"
    assert PackageData(code="DD", name="DFN-8 3x3 DD").label == "DFN-8 3x3 DD"
    assert PackageData(code="OT", name="SOT-23-6").label == "SOT-23-6 (OT)"
    assert PackageData(code="SOIC-8", name="soic-8").label == "soic-8"
