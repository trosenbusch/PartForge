import math

import pytest

from partforge.domain import eseries
from partforge.domain.units import format_power, format_quantity, format_rkm, parse_quantity, parse_range, parse_value


@pytest.mark.parametrize(
    ("text", "unit", "expected", "expected_unit"),
    [
        ("10k", "Ω", 10_000, "Ω"),
        ("10 kΩ", None, 10_000, "Ω"),
        ("10kOhm", None, 10_000, "Ω"),
        ("4k7", "Ω", 4_700, "Ω"),
        ("4K7", "Ω", 4_700, "Ω"),
        ("4R7", None, 4.7, "Ω"),
        ("R47", None, 0.47, "Ω"),
        ("0R", None, 0.0, "Ω"),
        ("100R", None, 100.0, "Ω"),
        ("1M5", "Ω", 1.5e6, "Ω"),
        ("1Meg", "Ω", 1e6, "Ω"),
        ("33mΩ", None, 0.033, "Ω"),
        ("2u2", "F", 2.2e-6, "F"),
        ("2,2µF", None, 2.2e-6, "F"),
        ("100nF", None, 1e-7, "F"),
        ("0.1 uF", None, 1e-7, "F"),
        ("4n7", "F", 4.7e-9, "F"),
        ("10µH", None, 1e-5, "H"),
        ("1/16W", None, 0.0625, "W"),
        ("0.063 W", None, 0.063, "W"),
        ("±1 %", None, 1.0, "%"),
        ("100ppm/K", None, 100.0, "ppm/K"),
        ("50V", None, 50.0, "V"),
        ("1.5A", None, 1.5, "A"),
        ("12MHz", None, 12e6, "Hz"),
        ("32.768kHz", None, 32768.0, "Hz"),
    ],
)
def test_parse_quantity(text, unit, expected, expected_unit):
    q = parse_quantity(text, unit)
    assert q is not None, text
    assert math.isclose(q.value, expected, rel_tol=1e-9, abs_tol=1e-15), (text, q)
    assert q.unit == expected_unit, (text, q)


@pytest.mark.parametrize("text", ["", "abc", "k", "1/0W", None])
def test_parse_invalid(text):
    assert parse_quantity(text) is None


def test_parse_value_numbers():
    assert parse_value(4.7) == 4.7
    assert parse_value("1e3", "Ω") == 1000.0


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (4700, "Ω", "4.7kΩ"),
        (10_000, "Ω", "10kΩ"),
        (1e6, "Ω", "1MΩ"),
        (0, "Ω", "0Ω"),
        (1e-7, "F", "100nF"),
        (2.2e-6, "F", "2.2µF"),
        (4.7e-12, "F", "4.7pF"),
        (0.0625, "W", "62.5mW"),
        (10_200, "Ω", "10.2kΩ"),
        (999_999, "Ω", "999.999kΩ"),
        (32768, "Hz", "32.768kHz"),
        (14_318_180, "Hz", "14.3182MHz"),
        (0.5, "%", "0.5%"),
        (1.75, "mm", "1.75mm"),
        (100, "ppm/K", "100ppm/K"),
    ],
)
def test_format_quantity(value, unit, expected):
    assert format_quantity(value, unit) == expected


def test_format_quantity_digits_and_space():
    assert format_quantity(32768, "Hz", digits=3) == "32.8kHz"
    assert format_quantity(999_999, "Ω", digits=3) == "1MΩ"
    assert format_quantity(4700, "Ω", space=True) == "4.7 kΩ"


@pytest.mark.parametrize(
    ("text", "unit", "expected", "expected_unit"),
    [
        ("1.75mm", "mm", 1.75, "mm"),
        ("120°", None, 120.0, "°"),
        ("12nC", None, 12e-9, "C"),
        ("6V3", None, 6.3, "V"),
        ("2A5", None, 2.5, "A"),
        ("125C", "°C", 125.0, "°C"),
        ("290V/µs", None, 290.0, "V/µs"),
        ("660nm", None, 660.0, "nm"),
    ],
)
def test_parse_extended_units(text, unit, expected, expected_unit):
    q = parse_quantity(text, unit)
    assert q is not None, text
    assert math.isclose(q.value, expected, rel_tol=1e-9), (text, q)
    assert q.unit == expected_unit, (text, q)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(4700, "4K7"), (100, "100R"), (4.7, "4R7"), (0.47, "R47"), (0.047, "R047"), (0, "0R"), (2.2e6, "2M2"), (10_200, "10K2"), (1e6, "1M"), (1020, "1K02")],
)
def test_format_rkm(value, expected):
    assert format_rkm(value) == expected


def test_format_power():
    assert format_power(0.0625, style="fraction") == "1/16W"
    assert format_power(0.1) == "0.1W"
    assert format_power(0.25) == "0.25W"
    assert format_power(0.05) == "50mW"


def test_parse_range():
    assert parse_range("-55°C to +155°C") == (-55.0, 155.0)
    assert parse_range("-40 ... 125 °C") == (-40.0, 125.0)
    lo, hi = parse_range("1Ω - 10MΩ")
    assert lo == 1.0 and hi == 1e7


def test_series_lengths_and_nesting():
    for name, n in [("E3", 3), ("E6", 6), ("E12", 12), ("E24", 24), ("E48", 48), ("E96", 96), ("E192", 192)]:
        values = eseries.SERIES[name]
        assert len(values) == n, name
        assert values == sorted(values), name
    assert eseries.SERIES["E48"] == eseries.SERIES["E96"][::2]
    assert eseries.SERIES["E96"] == eseries.SERIES["E192"][::2]
    assert eseries.SERIES["E6"] == eseries.SERIES["E12"][::2]
    assert eseries.SERIES["E12"] == eseries.SERIES["E24"][::2]


def test_values_in_range():
    vals = eseries.values_in_range("E12", 1.0, 10_000_000)
    assert vals[0] == 1.0 and vals[-1] == 10_000_000
    assert 4700 in vals and 4_700_000 in vals
    assert len(vals) == 12 * 7 + 1
    e96 = eseries.values_in_range("E96", 10, 1e6)
    assert 10_200 in e96 and 1e6 in e96 and len(e96) == 96 * 5 + 1


def test_nearest_and_series_of():
    assert eseries.nearest("E12", 5000) == 4700
    assert eseries.series_of(4700) == "E3"
    assert eseries.series_of(6800) == "E6"
    assert eseries.series_of(8200) == "E12"
    assert eseries.series_of(10_200) == "E96"
    assert eseries.series_of(1234) is None
