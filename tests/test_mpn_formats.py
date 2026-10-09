"""Value codes inside part numbers: encode, decode, regex and round trips (partforge.domain.mpn.formats)."""
from __future__ import annotations

import re

import pytest

from partforge.domain.eseries import SERIES, values_in_range
from partforge.domain.mpn.formats import ValueCodeError, ValueFormat, decode_value, encode_value, value_regex

RKM4 = ValueFormat(style="rkm4")
RKM = ValueFormat(style="rkm")
EIA3 = ValueFormat(style="eia3")
EIA4 = ValueFormat(style="eia4")
PF = ValueFormat(style="eia3", scale=1e-12)
PF_KEMET = ValueFormat(style="eia3", scale=1e-12, small_multipliers={"9": -1, "8": -2})
UH = ValueFormat(style="eia3", scale=1e-6)
UNI3 = ValueFormat(style="uniohm4", digits=3)
UNI2 = ValueFormat(style="uniohm4", digits=2)


@pytest.mark.parametrize(("fmt", "value", "code"), [
    # Vishay CRCW / Stackpole RMCF: 4 characters, letter as decimal point
    (RKM4, 10e3, "10K0"), (RKM4, 4.7e3, "4K70"), (RKM4, 100, "100R"), (RKM4, 1e6, "1M00"), (RKM4, 562, "562R"),
    (RKM4, 97.6, "97R6"), (RKM4, 1, "1R00"), (RKM4, 0.1, "R100"), (RKM4, 10e6, "10M0"), (RKM4, 9.76e6, "9M76"),
    (RKM4, 4.7, "4R70"), (RKM4, 1e3, "1K00"), (RKM4, 0.047, "R047"),
    # YAGEO RC_L: shortest form (datasheet: 97R6, 9K76, 1M)
    (RKM, 10e3, "10K"), (RKM, 4.7e3, "4K7"), (RKM, 100, "100R"), (RKM, 1e6, "1M"), (RKM, 10.2e3, "10K2"),
    (RKM, 97.6, "97R6"), (RKM, 9760, "9K76"), (RKM, 1, "1R"), (RKM, 10, "10R"), (RKM, 0.47, "R47"),
    (RKM, 22e6, "22M"), (RKM, 100e3, "100K"),
    # 2 significant digits + multiplier (5 % resistors)
    (EIA3, 10e3, "103"), (EIA3, 4.7, "4R7"), (EIA3, 1, "1R0"), (EIA3, 0.47, "R47"), (EIA3, 10, "100"),
    (EIA3, 470e3, "474"), (EIA3, 22e6, "226"), (EIA3, 1e3, "102"), (EIA3, 2.2e3, "222"),
    # 3 significant digits + multiplier (1 % resistors)
    (EIA4, 10e3, "1002"), (EIA4, 100, "1000"), (EIA4, 10, "10R0"), (EIA4, 1, "1R00"), (EIA4, 47.5, "47R5"),
    (EIA4, 0.1, "R100"), (EIA4, 82.5e3, "8252"), (EIA4, 24.3, "24R3"), (EIA4, 1e6, "1004"), (EIA4, 100e3, "1003"),
    # capacitance in pF
    (PF, 100e-9, "104"), (PF, 1e-12, "1R0"), (PF, 1.5e-12, "1R5"), (PF, 10e-12, "100"), (PF, 10e-6, "106"),
    (PF_KEMET, 1e-12, "109"), (PF_KEMET, 0.5e-12, "508"), (PF_KEMET, 4.7e-12, "479"), (PF_KEMET, 47e-6, "476"),
    # inductance in µH (Bourns SRR)
    (UH, 1e-6, "1R0"), (UH, 10e-6, "100"), (UH, 100e-6, "101"), (UH, 1e-3, "102"), (UH, 2.4e-6, "2R4"),
    # UNI-ROYAL: 3 digits (<= 1 %) or 0 + 2 digits (5 %), J/K/L = 10^-1/-2/-3
    (UNI3, 10e3, "1002"), (UNI3, 10, "100J"), (UNI3, 4.7, "470K"), (UNI3, 158, "1580"), (UNI3, 160e3, "1603"),
    (UNI3, 0.22, "220L"), (UNI2, 10e3, "0103"), (UNI2, 10, "0100"), (UNI2, 4.7, "047J"), (UNI2, 1e6, "0105"),
])
def test_encode_decode_examples(fmt: ValueFormat, value: float, code: str) -> None:
    assert encode_value(value, fmt) == code
    assert decode_value(code, fmt) == pytest.approx(value, rel=1e-12)
    assert re.fullmatch(value_regex(fmt), code)


@pytest.mark.parametrize(("fmt", "series", "low", "high"), [
    (RKM4, ["E24", "E96", "E192"], 0.1, 99.9e6),
    (RKM, ["E24", "E96", "E192"], 0.1, 99.9e6),
    (EIA4, ["E24", "E96", "E192"], 0.1, 9.99e9),
    (EIA3, ["E3", "E6", "E12", "E24"], 0.1, 91e9),
    (PF_KEMET, ["E24"], 0.5e-12, 100e-6),
    (UNI3, ["E24", "E96"], 0.001, 976e6),
    (UNI2, ["E24"], 0.001, 91e6),
])
def test_round_trip_over_series(fmt: ValueFormat, series: list[str], low: float, high: float) -> None:
    pattern = re.compile(value_regex(fmt))
    for name in series:
        for value in values_in_range(name, low, high):
            code = encode_value(value, fmt)
            assert pattern.fullmatch(code), (value, code)
            assert decode_value(code, fmt) == pytest.approx(value, rel=1e-12), (value, code)


@pytest.mark.parametrize(("fmt", "value"), [
    (EIA3, 4.99e3),  # 3 significant digits do not fit into a 2-digit code
    (RKM4, 1.234e3),
    (UNI2, 4.99e3),
    (EIA4, 0.047),  # below the R-notation range
    (EIA3, 1e12),  # multiplier > 9
    (RKM4, 1e13),  # beyond the largest letter
])
def test_not_representable(fmt: ValueFormat, value: float) -> None:
    with pytest.raises(ValueCodeError):
        encode_value(value, fmt)


@pytest.mark.parametrize("value", [0, -1, float("nan")])
def test_non_positive_values_rejected(value: float) -> None:
    with pytest.raises(ValueCodeError):
        encode_value(value, RKM4)


@pytest.mark.parametrize(("fmt", "code"), [
    (RKM4, "10K"), (RKM4, "1K000"), (RKM, "K"), (RKM, "10X"), (EIA4, "10R"), (EIA4, "1R0R"), (EIA3, "1000"),
    (EIA3, "A04"), (UNI3, "100X"), (UNI2, "1003"), (RKM4, ""),
])
def test_invalid_codes(fmt: ValueFormat, code: str) -> None:
    with pytest.raises(ValueCodeError):
        decode_value(code, fmt)


def test_decode_is_case_insensitive_and_strips() -> None:
    assert decode_value(" 10k0 ", RKM4) == 10e3
    assert decode_value("4k7", RKM) == 4.7e3


def test_format_validation() -> None:
    with pytest.raises(ValueError):
        ValueFormat(style="uniohm4", digits=4)
    with pytest.raises(ValueError):
        ValueFormat(style="eia3", small_multipliers={"X": -1})
    assert ValueFormat(style="eia3").significant() == 2
    assert ValueFormat(style="eia4").significant() == 3
    assert ValueFormat(style="uniohm4", digits=2).significant() == 2


def test_series_tables_are_complete() -> None:
    assert len(SERIES["E24"]) == 24 and len(SERIES["E96"]) == 96


@pytest.mark.parametrize(("letters", "message"), [
    ({}, "braucht Buchstaben"),
    ({"KK": 3}, "genau ein Buchstabe"),
    ({"1": 3}, "genau ein Buchstabe"),
    ({"Ä": 3}, "genau ein Buchstabe"),
    ({"": 0}, "genau ein Buchstabe"),
    ({"K": 3, "k": 3}, "doppelt"),
    ({"R": 0, "K": 0}, "denselben Zehnerexponenten"),
    ({"K": 99}, "außerhalb"),
])
def test_rkm_letters_are_validated(letters: dict[str, int], message: str) -> None:
    """Regression: user templates with letters {} or {"KK": 3} were stored and failed later with HTTP 500."""
    for style in ("rkm", "rkm4"):
        with pytest.raises(ValueError, match=message):
            ValueFormat(style=style, letters=letters)  # type: ignore[arg-type]


def test_rkm_letters_are_stored_upper_case() -> None:
    fmt = ValueFormat(style="rkm", letters={"r": 0, " k ": 3})
    assert fmt.letters == {"R": 0, "K": 3}
    assert encode_value(4.7e3, fmt) == "4K7" and decode_value("4k7", fmt) == 4.7e3
    assert re.fullmatch(value_regex(fmt), "4K7")
    pf = ValueFormat(style="rkm", scale=1e-12, letters={"P": 0, "N": 3, "U": 6})  # 4N7 = 4.7 nF
    assert encode_value(4.7e-9, pf) == "4N7" and decode_value("4N7", pf) == pytest.approx(4.7e-9)


def test_letters_of_other_styles_are_not_used() -> None:
    assert ValueFormat(style="eia3", letters={}).significant() == 2


def test_small_multiplier_exponents_are_limited() -> None:
    with pytest.raises(ValueError, match="außerhalb"):
        ValueFormat(style="eia3", small_multipliers={"9": -30})


@pytest.mark.parametrize(("fmt", "value", "shown"), [(RKM, 1.234e6, "1234000"), (EIA3, 4.99e3, "4990"),
                                                       (RKM4, 1.2345e3, "1234.5")])
def test_not_representable_messages_show_plain_numbers(fmt: ValueFormat, value: float, shown: str) -> None:
    with pytest.raises(ValueCodeError, match=f"Der Wert {re.escape(shown)} lässt sich"):
        encode_value(value, fmt)
