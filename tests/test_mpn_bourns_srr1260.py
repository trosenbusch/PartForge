"""Bourns SRR1260 catalog template against the corpus ground truth (all 38 rows of bourns_SRR1260.pdf)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from partforge.domain.mpn import decode_mpn, encode_mpn, get_template
from partforge.domain.units import parse_quantity

CORPUS = Path(__file__).parent / "data" / "corpus"


@pytest.fixture(scope="module")
def parts() -> list[dict[str, Any]]:
    data = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return next(e for e in data["entries"] if e["file"].endswith("bourns_SRR1260.pdf"))["series"]["parts"]


@pytest.fixture(scope="module")
def srr():
    return get_template("bourns-srr1260")


def _number(text: str, unit: str) -> float:
    q = parse_quantity(text, unit)
    assert q is not None, text
    return q.value


def test_catalog_has_all_38_rows(srr, parts: list[dict[str, Any]]) -> None:
    assert len(parts) == 38
    assert [e.mpn for e in srr.catalog] == [p["mpn"] for p in parts]


def test_every_row_decodes_to_the_datasheet_values(srr, parts: list[dict[str, Any]]) -> None:
    tolerance_codes = {30: "Y", 20: "M", 10: "K"}
    for p in parts:
        d = decode_mpn(srr, p["mpn"])
        assert d is not None and d.valid, p["mpn"]
        assert d.size == "SRR1260"
        assert d.value == pytest.approx(p["L_uH"] * 1e-6, rel=1e-9)
        assert d.codes["tolerance"] == tolerance_codes[p["tol_pct"]]
        assert d.fields["Tolerance"] == f"±{p['tol_pct']}%"
        assert _number(d.fields["Current Rating"], "A") == pytest.approx(p["Irms_max_A"])
        assert _number(d.fields["Saturation Current"], "A") == pytest.approx(p["Isat_typ_A"])
        assert _number(d.fields["DCR"], "Ω") == pytest.approx(p["RDC_max_mohm"] / 1000)
        assert _number(d.fields["SRF"], "Hz") == pytest.approx(p["SRF_typ_MHz"] * 1e6)
        assert d.fields["Shielding"] == "geschirmt" and d.fields["Height"] == "6.5mm"


def test_mpn_rule_round_trip(srr, parts: list[dict[str, Any]]) -> None:
    """The derived code rule (R = decimal point, 2 digits + zeros in µH, Y/M/K) holds for all rows."""
    tolerance_codes = {30: "Y", 20: "M", 10: "K"}
    for p in parts:
        mpn = encode_mpn(srr, size="SRR1260", value=p["L_uH"] * 1e-6,
                         codes={"tolerance": tolerance_codes[p["tol_pct"]]})
        assert mpn == p["mpn"]


def test_pattern_match_outside_the_catalog(srr) -> None:
    d = decode_mpn(srr, "SRR1260-330K")  # follows the pattern, but 33 µH is only listed with M
    assert d is not None and not d.valid and "Katalog" in d.messages[0]
    assert decode_mpn(srr, "srr1260-100m") is not None  # case-insensitive
    assert decode_mpn(srr, "SRR1260-100X") is None
    assert decode_mpn(srr, "SRR6038-100M") is None


def test_footprint_hint_uses_the_recommended_layout(srr) -> None:
    hint = srr.size_spec("SRR1260").footprint
    assert hint is not None and hint.family == "molded" and hint.kind == "INDM"
    assert hint.land_pattern == {"pad_length": 2.9, "pad_width": 5.4, "row_spacing": 9.7,
                                 "row_spacing_reference": "center"}
