"""Value normalisation, canonical formatting, RKM codes and description templates."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from partforge.db.models import FieldDef
from partforge.db.values import (
    JUMPER_EXEMPT_UNITS,
    canonical_unit,
    format_band,
    is_jumper,
    not_applicable,
    parse_field_band,
    format_field_quantity,
    length_limit,
    length_warning,
    format_rkm_value,
    normalize_cell,
    numeric_value,
    parse_field_quantity,
    parse_field_range,
    render_template,
    template_columns,
    template_tokens,
    to_text,
    units_compatible,
)


def fd(column: str, kind: str = "quantity", unit: str | None = None, **kw) -> FieldDef:
    return FieldDef(column=column, label=column, kind=kind, unit=unit, **kw)


@pytest.mark.parametrize(
    ("unit", "raw", "expected"),
    [
        ("Ω", "10k", "10kΩ"),
        ("Ω", "4K7", "4.7kΩ"),
        ("Ω", "4k7", "4.7kΩ"),
        ("Ω", "0R", "0Ω"),
        ("Ω", "R47", "470mΩ"),
        ("Ω", "10 kOhm", "10kΩ"),
        ("Ω", "1Meg", "1MΩ"),
        ("Ω", "47mΩ", "47mΩ"),
        ("Ω", "999.999k", "999.999kΩ"),
        ("%", "1", "±1%"),
        ("%", "±0.5 %", "±0.5%"),
        ("%", "0,1", "±0.1%"),
        ("W", "1/16W", "62.5mW"),
        ("W", "0.1", "0.1W"),
        ("W", "1/4", "0.25W"),
        ("W", "2.5W", "2.5W"),
        ("F", "100n", "100nF"),
        ("F", "0.1µF", "100nF"),
        ("F", "4u7", "4.7µF"),
        ("F", "2,2µF", "2.2µF"),
        ("F", "1e-07", "100nF"),
        ("V", "6V3", "6.3V"),
        ("V", "50", "50V"),
        ("mm", "1.75mm", "1.75mm"),
        ("mm", "1,2", "1.2mm"),
        ("Hz", "32.768kHz", "32.768kHz"),
        ("Hz", "14.31818 MHz", "14.31818MHz"),
        ("ppm", "20", "±20ppm"),
        ("ppm/K", "±100ppm/K", "±100ppm/K"),
        ("ppm/K", "-750", "-750ppm/K"),
        ("C", "12nC", "12nC"),
        ("°", "120°", "120°"),
        ("nm", "625", "625nm"),
        ("cd", "120mcd", "120mcd"),
        ("A", "200mA", "200mA"),
        ("H", "2.2uH", "2.2µH"),
    ],
)
def test_quantity_normalisation(unit: str, raw: str, expected: str) -> None:
    result = normalize_cell(fd("X", unit=unit), raw)
    assert result.warning is None and result.error is None
    assert result.value == expected


def test_normalisation_is_idempotent() -> None:
    for unit, raw in [("Ω", "4k7"), ("%", "1"), ("W", "1/16"), ("F", "100n"), ("Hz", "32.768k"), ("ppm", "20")]:
        f = fd("X", unit=unit)
        once = normalize_cell(f, raw).value
        assert normalize_cell(f, once).value == once


def test_quantity_problems_are_warnings_and_keep_text() -> None:
    bad = normalize_cell(fd("Tolerance", unit="%"), "J")
    assert bad.value == "J" and bad.warning and bad.error is None
    mismatch = normalize_cell(fd("Tolerance", unit="%"), "±0.25pF")
    assert mismatch.value == "±0.25pF" and "Einheit" in (mismatch.warning or "")
    wrong_unit = normalize_cell(fd("Resistance", unit="Ω"), "10kHz")
    assert wrong_unit.value == "10kHz" and wrong_unit.warning
    # a plain "100" for a capacitance/inductance is stored as 100F/100H but flagged (prefix forgotten?)
    farad = normalize_cell(fd("Capacitance", unit="F"), "100")
    assert farad.value == "100F" and farad.warning and "100p" in farad.warning
    assert normalize_cell(fd("Inductance", unit="H"), "10").warning
    assert normalize_cell(fd("Capacitance", unit="F"), "100n").warning is None
    assert normalize_cell(fd("Capacitance", unit="F"), "1F").warning is None  # explicit unit: a supercap
    assert normalize_cell(fd("Capacitance", unit="F"), 1e-07).warning is None  # spreadsheet number in farad
    assert normalize_cell(fd("Resistance", unit="Ω"), "100").warning is None  # ohms are often written plain


def test_quantity_without_field_unit_keeps_parsed_unit() -> None:
    assert normalize_cell(fd("X"), "10k").value == "10k"
    assert normalize_cell(fd("X"), "5V").value == "5V"


def test_ranges() -> None:
    temp = fd("Operating Temperature", "range", "°C")
    assert normalize_cell(temp, "-55 to +155").value == "-55°C … 155°C"
    assert normalize_cell(temp, "-40°C ... 85°C").value == "-40°C … 85°C"
    supply = fd("Supply Voltage", "range", "V")
    assert normalize_cell(supply, "1.8V - 5.5V").value == "1.8V … 5.5V"
    assert normalize_cell(supply, "±15V").value == "±15V"
    # symmetric supplies keep their ± (it doubles the span) – never silently "2.8V … 5.25V"
    hv = normalize_cell(supply, "2.8V to ±5.25V")
    assert (hv.value, hv.warning, hv.unreadable) == ("2.8V … ±5.25V", None, False)
    assert normalize_cell(supply, "±2.25V to ±18V").value == "±2.25V … ±18V"
    assert parse_field_range("2.8V to ±5.25V", "V") is None
    assert normalize_cell(supply, "irgendwas").warning
    assert parse_field_range("1mm … 2mm", "mm") == (1.0, 2.0)
    assert parse_field_range("1 … 2 … 3", "mm") is None


def test_int_bool_enum_date_url_path(tmp_path: Path) -> None:
    assert normalize_cell(fd("Ch", "int"), "2.0").value == "2"
    assert normalize_cell(fd("Ch", "int"), 3).value == "3"
    assert normalize_cell(fd("Ch", "int"), "2x10").warning
    assert normalize_cell(fd("B", "bool"), "yes").value == "Ja"
    assert normalize_cell(fd("B", "bool"), "0").value == "Nein"
    assert normalize_cell(fd("B", "bool"), True).value == "Ja"
    assert normalize_cell(fd("B", "bool"), "vielleicht").warning
    size = fd("Size", "enum", options=["0402", "0603"])
    assert normalize_cell(size, "603").value == "0603"  # spreadsheet number lost the leading zero
    mount = fd("Mounting", "enum", options=["SMD", "THT"])
    assert normalize_cell(mount, "smd").value == "SMD"
    other = normalize_cell(mount, "Press-fit")
    assert other.value == "Press-fit" and "Auswahlliste" in (other.warning or "")
    date = fd("D", "date")
    assert normalize_cell(date, "07.10.2026").value == "2026-10-07"
    assert normalize_cell(date, dt.datetime(2026, 10, 7, 12, 30)).value == "2026-10-07 12:30:00"
    assert normalize_cell(date, "2026-10-07T08:00:00").value == "2026-10-07 08:00:00"
    assert normalize_cell(date, "morgen").warning
    url = fd("U", "url")
    assert normalize_cell(url, "www.ti.com/lm358.pdf").value == "https://www.ti.com/lm358.pdf"
    assert normalize_cell(url, "ti.com/lit/ds/symlink/lm358.pdf").value == "https://ti.com/lit/ds/symlink/lm358.pdf"
    assert normalize_cell(url, "Datasheets/x.pdf").value == "Datasheets/x.pdf"
    assert normalize_cell(url, r"C:\Daten\x.pdf").warning is None
    assert normalize_cell(url, "kein link").warning
    path = fd("Library Path", "path")
    assert normalize_cell(path, "Symbols/PF_Passives.SchLib").value == r"Symbols\PF_Passives.SchLib"
    inside = tmp_path / "Symbols" / "A.SchLib"
    assert normalize_cell(path, str(inside), ws_root=tmp_path).value == r"Symbols\A.SchLib"
    outside = normalize_cell(path, r"D:\fremd\B.SchLib", ws_root=tmp_path)
    assert outside.value == r"D:\fremd\B.SchLib" and outside.warning


def test_text_cleanup_and_soft_length_limits() -> None:
    assert to_text("  a \t b  ") == "a b"
    assert to_text("a\x07b\x00 ") == "ab" and to_text("\x1b") is None  # invisible control characters vanish
    assert to_text("x\ny", multiline=True) == "x\ny"
    assert to_text("") is None and to_text(None) is None and to_text(float("nan")) is None
    assert to_text(10.0) == "10" and to_text(1e-07) == "0.0000001" and to_text(0.1) == "0.1"
    notes = fd("Notes", "text")
    assert normalize_cell(notes, "Zeile 1\r\n  Zeile 2 ").value == "Zeile 1\nZeile 2"
    assert length_limit(fd("Description", "text")) == 1000
    assert length_limit(fd("Notes", "text")) == 4000
    assert length_limit(fd("ComponentLink1URL", "url")) == 2000
    assert length_limit(fd("Other URL", "url")) == 2000
    assert length_limit(fd("X", "text")) == 255
    assert length_limit(fd("X", "text", length=40)) == 40
    assert length_limit(fd("X", "text", length=0)) is None  # 0 = unlimited
    # columns are TEXT (Altium truncates VARCHAR): over-long values are kept with a warning
    too_long = normalize_cell(fd("X", "text"), "x" * 256)
    assert too_long.error is None and too_long.value == "x" * 256
    assert too_long.warning and "256 Zeichen" in too_long.warning and "255" in too_long.warning
    assert normalize_cell(fd("X", "text", length=0), "x" * 50_000).warning is None
    assert length_warning(fd("X", "text", length=3), "abcd") and length_warning(fd("X", "text", length=3), "abc") is None
    # a quantity warning and a length warning are combined
    both = normalize_cell(fd("X", unit="Ω", length=3), "unbekannt")
    assert both.warning and "kein gültiger Wert" in both.warning and "empfohlen" in both.warning


def test_unicode_minus_signs() -> None:
    """U+2212 (from PDFs/Word) and dashes used as a sign are numbers, not text."""
    assert normalize_cell(fd("V", unit="V"), "−5V").value == "-5V"
    assert normalize_cell(fd("V", unit="V"), "−5V").warning is None
    temp = fd("Operating Temperature", "range", "°C")
    assert normalize_cell(temp, "−40 … 125").value == "-40°C … 125°C"
    assert normalize_cell(temp, "−55–155").value == "-55°C … 155°C"  # en dash as separator
    assert normalize_cell(fd("N", "int"), "−3").value == "-3"
    assert numeric_value("−10mV", "V") == pytest.approx(-0.01)
    assert template_tokens("IC {Manufacturer Part Number} {Channels}CH") == ["IC", "{Manufacturer Part Number}", "{Channels}CH"]


def test_part_number_characters() -> None:
    pn = fd("Part Number", "text")
    assert normalize_cell(pn, "MF-GSMF300/36X-2").error is None
    assert normalize_cell(pn, "LTC3128EUFD#PBF").error is None
    assert normalize_cell(pn, "2N7002,215").error is None
    for bad in ("LM358'X", "A{B}", "A|B"):
        assert normalize_cell(pn, bad).error


def test_units_and_numbers() -> None:
    assert canonical_unit("ppm") == "ppm" and canonical_unit("ohm") == "Ω" and canonical_unit(None) == ""
    assert units_compatible("", "Ω") and units_compatible("ppm/K", "ppm") and not units_compatible("Hz", "Ω")
    assert numeric_value("10kΩ", "Ω") == 10000
    assert numeric_value("±1%", "%") == 1
    assert numeric_value("1.75mm", "mm") == 1.75
    assert numeric_value("62.5mW", "W") == pytest.approx(0.0625)
    assert numeric_value("abc", "Ω") is None and numeric_value(None, "Ω") is None
    assert numeric_value("10kHz", "Ω") is None
    assert parse_field_quantity("", "Ω") is None
    assert format_field_quantity(0, "Ω") == "0Ω"
    assert format_field_quantity(1e-12, "F") == "1pF"
    assert format_field_quantity(1, "%", plus_minus=True) == "±1%"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(4700, "Ω", "4k7"), (10000, "Ω", "10k"), (100, "Ω", "100R"), (0, "Ω", "0R"), (4.7, "Ω", "4R7"),
     (0.47, "Ω", "R47"), (0.047, "Ω", "R047"), (2.2e6, "Ω", "2M2"), (4990, "Ω", "4k99"),
     (1e-7, "F", "100n"), (2.2e-6, "F", "2u2"), (4.7e-9, "F", "4n7"), (6.3, "V", "6V3"), (10, "V", "10V")],
)
def test_rkm(value: float, unit: str, expected: str) -> None:
    assert format_rkm_value(value, unit) == expected


def test_templates() -> None:
    fields = {
        "Resistance": fd("Resistance", unit="Ω"),
        "Tolerance": fd("Tolerance", unit="%"),
        "Power": fd("Power", unit="W"),
        "Channels": fd("Channels", "int"),
        "Manufacturer Part Number": fd("Manufacturer Part Number", "text"),
        "RDS(on)": fd("RDS(on)", unit="Ω"),
    }
    values = {"Size": "0603", "Resistance": "10kΩ", "Tolerance": "±1%", "Power": "0.1W"}
    assert render_template("RES {Size} {Resistance} {Tolerance} {Power} {Technology}", values, fields) == "RES 0603 10kΩ ±1% 0.1W"
    assert render_template("{Resistance:rkm}", {"Resistance": "4.7kΩ"}, fields) == "4k7"
    assert render_template("{Resistance:nounit}", {"Resistance": "4.7kΩ"}, fields) == "4.7k"
    assert render_template("{Resistance:si}", {"Resistance": "4K7"}, fields) == "4.7kΩ"
    assert render_template("{Manufacturer Part Number:lower}", {"Manufacturer Part Number": "LM358DR"}, fields) == "lm358dr"
    assert render_template("{Manufacturer Part Number:unknown}", {"Manufacturer Part Number": "X"}, fields) == "X"
    # empty placeholders drop their whole token, whitespace collapses
    assert render_template("IC OPAMP {Channels}CH  {GBW} {Package}", {"Package": "SOIC-8"}, fields) == "IC OPAMP SOIC-8"
    assert render_template("IC {Channels}CH", {"Channels": "2"}, fields) == "IC 2CH"
    # placeholders with spaces/parentheses, case-insensitive lookup
    assert render_template("{manufacturer part number} {RDS(on)}", {"Manufacturer Part Number": "X", "RDS(on)": "5Ω"}, fields) == "X 5Ω"
    # dangling separators at the ends are removed
    assert render_template("- {A} , {B} -", {"A": "x"}, fields) == "x"
    assert render_template("{A}, {B}", {"A": "x", "B": "y"}, fields) == "x, y"
    assert render_template("", values, fields) == "" and render_template(None, values, fields) == ""
    assert render_template("{A}", {"A": "-55°C … 155°C"}, {}) == "-55°C … 155°C"
    assert template_columns("{A} {B:rkm} {A}") == ["A", "B"]


# --------------------------------------------------------------------------- asymmetric bands, 0-Ω jumpers


@pytest.mark.parametrize(
    ("unit", "raw", "expected"),
    [
        ("ppm/K", "-100 … +350ppm/K", "-100 … +350ppm/K"),  # UNI-ROYAL 0201, YAGEO RC_L 0201 (1 … 10 Ω)
        ("ppm/K", "-100~﹢350 ppm/℃", "-100 … +350ppm/K"),  # datasheet spelling (small plus, ℃)
        ("ppm/K", "+350/-100ppm/K", "-100 … +350ppm/K"),
        ("ppm/K", "-100 to +350", "-100 … +350ppm/K"),
        ("ppm/K", "−200 … +600 ppm/°C", "-200 … +600ppm/K"),  # Unicode minus
        ("ppm/K", "-400 ... +150 ppm", "-400 … +150ppm/K"),  # ppm accepted for a TCR field
        ("ppm/K", "-100 … +100ppm/K", "±100ppm/K"),  # symmetric band
        ("ppm/K", "100 … 200", "+100 … +200ppm/K"),
        ("%", "+80/-20%", "-20 … +80%"),  # Y5V/Z5U capacitance tolerance
        ("%", "-20 % … +80 %", "-20 … +80%"),
        ("%", "-0.5…+1%", "-0.5 … +1%"),
        ("ppm", "-10 … +20ppm", "-10 … +20ppm"),
    ],
)
def test_asymmetric_bands_of_relative_fields(unit: str, raw: str, expected: str) -> None:
    f = fd("X", unit=unit)
    result = normalize_cell(f, raw)
    assert result.warning is None and not result.unreadable and result.value == expected
    assert normalize_cell(f, result.value).value == expected  # idempotent


def test_band_parsing_rules() -> None:
    assert parse_field_band("-100 … +350ppm/K", "ppm/K") == (-100.0, 350.0)
    assert parse_field_band("+350/-100 ppm/K", "ppm/K") == (-100.0, 350.0)
    assert parse_field_band("-55 … 155", "°C") is None  # only relative units (ranges have their own kind)
    assert parse_field_band("-100 … +350V", "ppm/K") is None  # wrong unit
    assert parse_field_band("5 … 5", "%") is None  # not a band
    assert parse_field_band("1 … 2 … 3", "%") is None
    assert parse_field_band("±100ppm/K", "ppm/K") is None  # a single value
    assert format_band(-100, 350, "ppm/K") == "-100 … +350ppm/K" and format_band(-20, 20, "%") == "±20%"
    assert format_band(0, 80, "%") == "0 … +80%"
    bad = normalize_cell(fd("TCR", unit="ppm/K"), "5 … 5")
    assert bad.warning and bad.unreadable and bad.value == "5 … 5"
    for_range = normalize_cell(fd("Operating Temperature", "range", "°C"), "-55 … +155")
    assert for_range.value == "-55°C … 155°C"  # range fields are unchanged


def test_band_numeric_value_is_the_worst_case() -> None:
    assert numeric_value("-100 … +350ppm/K", "ppm/K") == 350.0
    assert numeric_value("-400 … +150ppm/K", "ppm/K") == 400.0
    assert numeric_value("±100ppm/K", "ppm/K") == 100.0
    assert numeric_value("-20 … +80%", "%") == 80.0
    assert numeric_value("-100 … +350ppm/K", "V") is None


def test_jumper_rule() -> None:
    from partforge.db.models import CategoryDef

    fields = [fd("Part Number", "text"), fd("Resistance", unit="Ω"), fd("Tolerance", unit="%"),
              fd("Power", unit="W"), fd("Voltage", unit="V"), fd("TCR", unit="ppm/K"), fd("Size", "text"),
              fd("Height", unit="mm")]
    cat = CategoryDef(table="Resistors", label="Widerstände", prefix="R", value_field="Resistance", fields=fields)
    resistance = cat.field("Resistance")
    for zero in ("0", "0Ω", "0R", "0 Ohm", "0mΩ"):
        assert is_jumper(resistance, {"Resistance": zero}), zero
    for other in ("10k", "R47", "", None, "Brücke", "0V"):
        assert not is_jumper(resistance, {"Resistance": other}), other
    assert not_applicable(cat, {"resistance": "0Ω"}) == {"Tolerance", "Power", "Voltage", "TCR"}
    assert not_applicable(cat, {"Resistance": "10k"}) == frozenset()
    caps = CategoryDef(table="Capacitors", label="Kondensatoren", prefix="C", value_field="Capacitance",
                       fields=[fd("Capacitance", unit="F"), fd("Tolerance", unit="%")])
    assert not_applicable(caps, {"Capacitance": "0"}) == frozenset()  # only resistances have jumpers
    assert JUMPER_EXEMPT_UNITS == {"%", "ppm", "ppm/K", "W", "V"}
