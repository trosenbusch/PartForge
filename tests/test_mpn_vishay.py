"""Vishay CRCW e3 template against the corpus ground truth (vishay_dcrcwe3.pdf, manifest.json)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from partforge.domain.eseries import values_in_range
from partforge.domain.mpn import decode_mpn, encode_mpn, get_template, in_series, resolve

CORPUS = Path(__file__).parent / "data" / "corpus"
SIZES = ["0402", "0603", "0805", "1206", "1210", "1218", "2010", "2512"]


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    data = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return next(e for e in data["entries"] if e["file"].endswith("vishay_dcrcwe3.pdf"))["series"]


@pytest.fixture(scope="module")
def reference() -> ModuleType:
    """The reference decoder/encoder of the corpus (tests/data/corpus/tools/mpn_decoders.py)."""
    spec = importlib.util.spec_from_file_location("corpus_mpn_decoders", CORPUS / "tools" / "mpn_decoders.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def crcw():
    return get_template("vishay-crcw-e3")


def test_datasheet_examples(crcw) -> None:
    d = decode_mpn(crcw, "CRCW0603562RFKEA")
    assert d is not None and d.valid, d
    assert (d.size, d.value, d.codes) == ("0603", 562.0, {"tolerance": "F", "tcr": "K", "packaging": "EA"})
    assert d.fields["Resistance"] == "562Ω" and d.fields["Tolerance"] == "±1%" and d.fields["TCR"] == "±100ppm/K"
    jumper = decode_mpn(crcw, "CRCW06030000Z0EA")
    assert jumper is not None and jumper.valid and jumper.jumper and jumper.value == 0.0
    assert "Tolerance" not in jumper.fields and "TCR" not in jumper.fields and "Power" not in jumper.fields
    assert jumper.fields["Notes"] == "0-Ω-Brücke (Jumper) ≤ 20 mΩ, Nennstrom 2A"  # Imax. = 2.0 A (p. 2)


def test_decode_test_vectors(crcw, manifest: dict[str, Any]) -> None:
    tol = {"±1 %": "±1%", "±5 %": "±5%"}
    tcr = {"±100 ppm/K": "±100ppm/K", "±200 ppm/K": "±200ppm/K"}
    vectors = manifest["decode_test_vectors_DERIVED"]
    assert len(vectors) == 4
    for mpn, expected in vectors.items():
        d = decode_mpn(crcw, mpn)
        assert d is not None and d.valid, (mpn, d)
        assert d.size == expected["size"] and d.value == pytest.approx(expected["R_ohm"])
        assert d.attrs["tolerance"] == tol[expected["tol"]] and d.attrs["tcr"] == tcr[expected["tcr"]]
        assert d.codes["packaging"] == expected["pack"][:2]
        assert d.mpn == mpn


def test_reference_encoder_examples(crcw, reference: ModuleType) -> None:
    cases = [("0603", 562, "F", "K", "EA"), ("0603", 10e3, "F", "K", "EA"), ("0805", 4.7e3, "J", "N", "EA"),
             ("0402", 1e6, "F", "K", "ED"), ("1206", 4.7, "F", "N", "EA"), ("2512", 97.6, "F", "K", "EG"),
             ("0603", 9.76e6, "F", "K", "EA")]
    for size, ohm, tol, tcr, pack in cases:
        ours = encode_mpn(crcw, size=size, value=ohm, codes={"tolerance": tol, "tcr": tcr, "packaging": pack})
        assert ours == reference.crcw_encode(size, ohm, tol, tcr, pack)
    assert encode_mpn(crcw, size="0603", value=0, codes={"tolerance": "Z", "tcr": "0", "packaging": "EA"},
                      jumper=True) == reference.crcw_encode("0603", 0, "Z", "0", "EA") == "CRCW06030000Z0EA"


def _generate(crcw, size: str, tolerance: str, series: list[str], low: float, high: float,
              tcr: str | None = None) -> list[tuple[float, dict[str, str]]]:
    fixed = {"tolerance": tolerance, **({"tcr": tcr} if tcr else {})}
    out = []
    for value in sorted({v for name in series for v in values_in_range(name, low, high)}):
        res = resolve(crcw, size=size, value=value, fixed=fixed)
        if res.ok:
            out.append((value, res.codes))
    return out


def test_value_counts_from_corpus(crcw, manifest: dict[str, Any]) -> None:
    counts = manifest["value_counts_DERIVED"]
    assert len(_generate(crcw, "0603", "J", ["E24"], 1, 10e6)) == counts["E24 1Ω..10MΩ"] == 169
    assert len(_generate(crcw, "0603", "F", ["E24", "E96"], 1, 10e6)) == counts["E24∪E96 1Ω..10MΩ"] == 799
    assert len(_generate(crcw, "1218", "J", ["E24"], 1, 10e6)) == counts["E24 1Ω..2.2MΩ (1218)"] == 153
    assert len(_generate(crcw, "1218", "F", ["E24", "E96"], 1, 10e6)) == counts["E24∪E96 1Ω..2.2MΩ (1218)"] == 721


def test_all_generated_mpns_match_the_reference_codec(crcw, reference: ModuleType) -> None:
    """Every generated part of every size round-trips through the independent corpus decoder."""
    checked = 0
    for size in SIZES:
        for tol, series in (("F", ["E24", "E96"]), ("J", ["E24"])):
            for value, codes in _generate(crcw, size, tol, series, 1, 10e6):
                mpn = encode_mpn(crcw, size=size, value=value, codes=codes)
                ref = reference.crcw_decode(mpn)
                assert ref["size"] == size and ref["ohm"] == pytest.approx(value), mpn
                assert ref["tolerance"] == {"F": "±1 %", "J": "±5 %"}[tol]
                assert reference.crcw_encode(size, value, codes["tolerance"], codes["tcr"], codes["packaging"]) == mpn
                checked += 1
    assert checked == 7 * (799 + 169) + (721 + 153)


def test_tcr_rules(crcw) -> None:
    # 1 %: ±100 ppm/K everywhere, ±200 ppm/K only 1 Ω … 9.76 Ω; 5 % only ±200 ppm/K
    assert len(_generate(crcw, "0805", "F", ["E24", "E96"], 1, 10e6, tcr="N")) == len(
        [v for v in values_in_range("E96", 1, 9.76)] + [v for v in values_in_range("E24", 1, 9.76)
                                                        if not in_series(v, ["E96"])])
    assert not _generate(crcw, "0805", "J", ["E24"], 1, 10e6, tcr="K")
    res = resolve(crcw, size="0603", value=4.7, fixed={"tolerance": "F"})
    assert res.ok and res.codes["tcr"] == "K"  # preferred TCR when not chosen
    res = resolve(crcw, size="0603", value=4.7e3, fixed={"tolerance": "J"})
    assert res.ok and res.codes["tcr"] == "N"  # 5 % exists only with ±200 ppm/K


def test_ratings_per_size(crcw, manifest: dict[str, Any]) -> None:
    standard = manifest["ratings_standard_mode_p2"]
    for rating in manifest["ratings"]:
        size = rating["size"]
        attrs = crcw.size_spec(size).attrs
        power = standard[size]["P70_W"] if size in standard else rating["P70_W"]
        voltage = standard[size]["Umax_V"] if size in standard else rating["Umax_V"]
        assert float(attrs["power"].rstrip("W")) == pytest.approx(power), size
        assert float(attrs["voltage"].rstrip("V")) == pytest.approx(voltage), size
    jumper = next(r for r in manifest["value_rules_p2"] if "jumper" in r)["Imax_A"]
    for size, amps in jumper.items():
        assert float(crcw.size_spec(size).attrs["jumper_current"].rstrip("A")) == pytest.approx(amps)


def test_packaging_codes_per_size(crcw, manifest: dict[str, Any]) -> None:
    for size, entries in manifest["packaging"].items():
        allowed = {e["code"] for e in entries}
        for code in ["EA", "EC", "ED", "EE", "EF", "EG", "EH", "EI", "EK"]:
            mpn = f"CRCW{size}10K0FK{code}"
            d = decode_mpn(crcw, mpn)
            assert d is not None
            assert d.valid == (code in allowed), (mpn, d.messages)
        default = resolve(crcw, size=size, value=10e3, fixed={"tolerance": "F"}).codes["packaging"]
        assert default in allowed


def test_out_of_range_and_series(crcw) -> None:
    assert not decode_mpn(crcw, "CRCW121822M0FKEK").valid  # 1218 ends at 2.2 MΩ
    d = decode_mpn(crcw, "CRCW06034K99JNEA")
    assert d is not None and not d.valid and "E24" in d.messages[0]
    assert decode_mpn(crcw, "CRCW0603562RFKXX") is None
    assert decode_mpn(crcw, "RC0603FR-0710KL") is None
