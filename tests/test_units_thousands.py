"""Thousands separators vs. the German decimal comma (INT-03).

"1,000µF" is 1000 µF in an English datasheet but 1 µF with three decimals in German – a value
must never be read silently as the wrong one. Exactly one comma group of three digits ("1,000",
"10,000pF", "2,200 uF") is ambiguous: manual entry gets a German warning and the value counts as
unreadable (the strict import refuses it); an English source (datasheet, ``thousands=True``) reads
it as thousands. Unambiguous spellings keep working: "2,2µF" / "0,100" (decimal comma), "1,000,000"
and "1,000.5" (thousands).
"""
from __future__ import annotations

import pytest

from partforge.db.models import FieldDef
from partforge.db.values import normalize_cell, numeric_value, parse_field_quantity, parse_field_range
from partforge.domain.units import ambiguous_thousands, parse_quantity, resolve_commas


def fd(column: str, kind: str = "quantity", unit: str | None = None) -> FieldDef:
    return FieldDef(column=column, label=column, kind=kind, unit=unit)


CAP = fd("Capacitance", unit="F")
RES = fd("Resistance", unit="Ω")
VOLT = fd("Voltage", unit="V")
FREQ = fd("Frequency", unit="Hz")
PINS = fd("Pins", kind="int")


@pytest.mark.parametrize("text", ["1,000µF", "10,000pF", "2,200 uF", "1,000Ω", "10,000 ohm", "1,000V", "32,768 Hz",
                                  "3,900 pF", "-1,000V", "4,700k"])
def test_single_three_digit_group_is_ambiguous(text: str) -> None:
    assert ambiguous_thousands(text)
    assert parse_quantity(text) is None  # never silently 1 µF / 10 pF / 32.768 Hz
    assert resolve_commas(text.replace(" ", "")) is None


@pytest.mark.parametrize(
    ("text", "unit", "expected"),
    [
        ("2,2µF", "F", 2.2e-6),  # German decimal comma (not three digits)
        ("4,7k", "Ω", 4700.0),
        ("1,50V", "V", 1.5),
        ("0,100", "%", 0.1),  # a leading 0 is never a thousands group
        ("±0,005%", "%", 0.005),
        ("1,000,000Ω", "Ω", 1e6),  # two groups: thousands, unambiguous
        ("1,000.5Hz", "Hz", 1000.5),  # thousands + decimal point: unambiguous
        ("1000µF", "F", 1e-3),
    ],
)
def test_unambiguous_commas(text: str, unit: str, expected: float) -> None:
    assert not ambiguous_thousands(text)
    q = parse_quantity(text, unit)
    assert q is not None and q.value == pytest.approx(expected)


def test_context_decides_the_ambiguous_group() -> None:
    english = parse_quantity("1,000µF", thousands=True)
    german = parse_quantity("1,000µF", thousands=False)
    assert english is not None and english.value == pytest.approx(1e-3) and english.unit == "F"
    assert german is not None and german.value == pytest.approx(1e-6)
    assert parse_quantity("32,768 Hz", thousands=True).value == pytest.approx(32768)  # type: ignore[union-attr]
    # the decimal comma of other numbers is unaffected by the context
    assert parse_quantity("2,2µF", thousands=True).value == pytest.approx(2.2e-6)  # type: ignore[union-attr]


@pytest.mark.parametrize(("field", "raw"), [(CAP, "1,000µF"), (CAP, "10,000pF"), (CAP, "2,200 uF"), (RES, "1,000Ω"),
                                            (RES, "10,000 ohm"), (VOLT, "1,000V"), (FREQ, "32,768 Hz")])
def test_manual_entry_warns_and_is_unreadable(field: FieldDef, raw: str) -> None:
    res = normalize_cell(field, raw)
    assert res.value == raw  # stored as typed – never as the wrong number
    assert res.error is None
    assert res.unreadable  # the strict import rejects the row
    assert res.warning is not None and "mehrdeutig" in res.warning
    assert "Tausendertrennzeichen" in res.warning and "Dezimalkomma" in res.warning


def test_warning_names_both_readings() -> None:
    warning = normalize_cell(CAP, "1,000µF").warning or ""
    assert "1mF" in warning and "1µF" in warning


@pytest.mark.parametrize(
    ("field", "raw", "expected"),
    [(CAP, "2,000 pF", "2nF"), (CAP, "3,900 pF", "3.9nF"), (CAP, "6,700 pF", "6.7nF"), (FREQ, "32,768 Hz", "32.768kHz"),
     (RES, "10,000 ohm", "10kΩ")],
)
def test_english_source_reads_thousands_with_a_note(field: FieldDef, raw: str, expected: str) -> None:
    res = normalize_cell(field, raw, thousands=True)
    assert res.value == expected and res.warning is None and not res.unreadable
    assert res.note is not None and "Tausendertrennzeichen" in res.note


def test_german_source_reads_the_decimal_comma() -> None:
    res = normalize_cell(CAP, "1,000µF", thousands=False)
    assert res.value == "1µF" and res.warning is None and res.note is None


def test_unambiguous_values_have_no_note() -> None:
    assert normalize_cell(CAP, "2,2µF").value == "2.2µF"
    assert normalize_cell(CAP, "2,2µF", thousands=True).note is None
    assert normalize_cell(RES, "1,000,000Ω").value == "1MΩ"


def test_int_fields_follow_the_same_rule() -> None:
    res = normalize_cell(PINS, "1,000")
    assert res.unreadable and res.value == "1,000" and "mehrdeutig" in (res.warning or "")
    assert normalize_cell(PINS, "1,000", thousands=True).value == "1000"
    assert normalize_cell(PINS, "1,000,000").value == "1000000"
    assert normalize_cell(PINS, "2,0").value == "2"
    assert normalize_cell(PINS, "1,5").unreadable


def test_ranges_and_numeric_values() -> None:
    temp = fd("Operating Temperature", kind="range", unit="°C")
    assert parse_field_range("-1,000 … 2,000", "°C") is None
    res = normalize_cell(temp, "-1,000 … 2,000")
    assert res.unreadable and "mehrdeutig" in (res.warning or "")
    assert normalize_cell(temp, "-40 … 125").value == "-40°C … 125°C"
    # stored canonical values never contain commas; a stored ambiguous text has no number
    assert numeric_value("1,000µF", "F") is None
    assert parse_field_quantity("1,000µF", "F", thousands=True) is not None


def test_strict_import_rejects_ambiguous_values(workspace) -> None:  # noqa: ANN001 - fixture
    from partforge.db import parts

    plans = parts.plan_upsert("Capacitors", [{"Part Number": "AMB-1", "Capacitance": "1,000µF"}], strict=True)
    assert plans[0].status == "reject" and "mehrdeutig" in plans[0].message
    lenient = parts.plan_upsert("Capacitors", [{"Part Number": "AMB-1", "Capacitance": "1,000µF"}],
                                allow_incomplete=True)
    assert lenient[0].status == "create" and any("mehrdeutig" in w for w in lenient[0].warnings)
    english = parts.plan_upsert("Capacitors", [{"Part Number": "AMB-1", "Capacitance": "1,000µF"}],
                                allow_incomplete=True, thousands=True)
    assert english[0].row is not None and english[0].row["Capacitance"] == "1mF"


def test_api_create_keeps_the_ambiguous_text(client) -> None:  # noqa: ANN001 - fixture
    r = client.post("/api/parts/Capacitors", json={"values": {"Part Number": "AMB-API-1", "Capacitance": "1,000µF"},
                                                   "allow_incomplete": True})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["part"]["Capacitance"] == "1,000µF"  # not "1µF"
    assert any("mehrdeutig" in w for w in body["warnings"])
