"""KEMET C-series X7R template against the corpus ground truth (availability matrix, 3342 cells)."""
from __future__ import annotations

import importlib.util
import json
from collections import defaultdict
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from partforge.domain.eseries import values_in_range
from partforge.domain.mpn import decode_mpn, encode_mpn, get_template, resolve
from partforge.domain.mpn.builtin.capacitors import kemet_thickness

CORPUS = Path(__file__).parent / "data" / "corpus"


@pytest.fixture(scope="module")
def groundtruth() -> dict[str, Any]:
    return json.loads((CORPUS / "groundtruth" / "kemet_C1002_X7R_series.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    data = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    return next(e for e in data["entries"] if e["file"].endswith("kemet_C1002_X7R_SMD.pdf"))["series"]


@pytest.fixture(scope="module")
def reference() -> ModuleType:
    spec = importlib.util.spec_from_file_location("corpus_mpn_decoders_kemet", CORPUS / "tools" / "mpn_decoders.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def kemet():
    return get_template("kemet-c-x7r")


def test_availability_equals_groundtruth(kemet, groundtruth: dict[str, Any]) -> None:
    ours = {(c.size, c.codes["voltage"], c.value, c.attrs["thickness_code"], "".join(c.tolerances))
            for c in kemet.availability}
    truth = {(a["case"], a["voltage_code"], a["cap_code"], a["thickness_code"], a["tolerances"].replace(",", ""))
             for a in groundtruth["availability"]}
    assert len(kemet.availability) == len(groundtruth["availability"]) == 3342
    assert ours == truth


def test_thickness_codes_equal_groundtruth(kemet, groundtruth: dict[str, Any]) -> None:
    table = kemet_thickness()
    assert len(table) == 70
    for code, t in groundtruth["thickness_codes"].items():
        case, nominal, tol, tape = table[code]
        assert (case, nominal, tol) == (t["case"], t["thickness_mm"], t["tol_mm"])
        assert tape == ("paper" if t["paper_7in"] else "embossed")
    for cell in kemet.availability:
        case, nominal, tol, _tape = table[cell.attrs["thickness_code"]]
        assert case == cell.size
        assert cell.attrs["height"] == f"{round(nominal + tol, 3):g}mm"


def test_summary_by_case_and_voltage(kemet, manifest: dict[str, Any]) -> None:
    volts = {"9": "6.3", "8": "10", "4": "16", "3": "25", "6": "35", "5": "50", "1": "100", "2": "200", "A": "250"}
    groups: dict[tuple[str, str], list[float]] = defaultdict(list)
    for cell in kemet.availability:
        groups[(cell.size, volts[cell.codes["voltage"]])].append(int(cell.value[:2]) * 10 ** int(cell.value[2]))
    summary = manifest["availability_summary_by_case_and_voltage"]
    assert {(case, v) for case, by_v in summary.items() for v in by_v} == set(groups)
    for case, by_v in summary.items():
        for v, expected in by_v.items():
            values = groups[(case, v)]
            assert (min(values), max(values), len(values)) == (expected["min_pF"], expected["max_pF"],
                                                               expected["count"]), (case, v)


@pytest.mark.parametrize(("mpn", "valid", "thickness"), [
    ("C1206C106M4RACTU", True, "EH"),
    ("C0603C104K5RACTU", True, "CJ"),
    ("C0402C104K3RACTU", True, "BB"),   # footnote 1: only K and M tolerance – K is fine
    ("C0805C106J8RACTU", False, "DH"),  # J not orderable (K/M only)
    ("C1210C476M8RACTU", True, "FS"),
    ("C0402C105K8RACTU", False, None),  # not in the table (0402 ends at 0.47 µF)
])
def test_decode_test_vectors(kemet, mpn: str, valid: bool, thickness: str | None) -> None:
    d = decode_mpn(kemet, mpn)
    assert d is not None
    assert d.valid is valid, d.messages
    assert d.mpn == mpn
    if thickness:
        assert d.attrs["thickness_code"] == thickness
    if not valid:
        assert d.messages


def test_not_orderable_messages(kemet) -> None:
    d = decode_mpn(kemet, "C0805C106J8RACTU")
    assert d is not None and "±5%" in d.messages[0] and "±10%" in d.messages[0]
    d = decode_mpn(kemet, "C0402C105K8RACTU")
    assert d is not None and "nicht lieferbar" in d.messages[0]


def test_reference_decoder_agrees_on_every_cell(kemet, reference: ModuleType, groundtruth: dict[str, Any]) -> None:
    avail = {(a["case"], a["voltage_code"], a["cap_code"]): a for a in groundtruth["availability"]}
    vrev = {v: k for k, v in reference.KEMET_V.items()}
    for cell in kemet.availability:
        for tol in "JKM":
            res = resolve(kemet, size=cell.size, value=int(cell.value[:2]) * 10 ** int(cell.value[2]) * 1e-12,
                          fixed={"tolerance": tol, "voltage": cell.codes["voltage"]})
            mpn = encode_mpn(kemet, size=cell.size, value=int(cell.value[:2]) * 10 ** int(cell.value[2]) * 1e-12,
                             codes=res.codes)
            ref = reference.kemet_decode(mpn)
            truth = avail[(ref["case"], vrev[ref["rated_V"]], ref["cap_code"])]
            orderable = ref["tolerance"] in truth["tolerances"].split(",")
            assert res.ok is orderable, mpn
            assert mpn.endswith("TU") and ref["cspec"] == "TU"


def test_cells_outside_the_matrix_are_rejected(kemet) -> None:
    """For every case/voltage: the next E24 value above the largest orderable value is not orderable."""
    by_group: dict[tuple[str, str], int] = defaultdict(int)
    for cell in kemet.availability:
        pf = int(cell.value[:2]) * 10 ** int(cell.value[2])
        key = (cell.size, cell.codes["voltage"])
        by_group[key] = max(by_group[key], pf)
    for (size, vcode), max_pf in by_group.items():
        above = values_in_range("E24", max_pf * 1.01, max_pf * 10)[0]
        res = resolve(kemet, size=size, value=above * 1e-12, fixed={"tolerance": "K", "voltage": vcode})
        assert not res.ok, (size, vcode, above)
        assert "nicht lieferbar" in res.messages[0]
    assert len(by_group) == 66  # case/voltage groups of Tables 1A-1C


def test_cspec_restrictions(kemet) -> None:
    assert decode_mpn(kemet, "C0603C104K5RAC7411").valid
    assert not decode_mpn(kemet, "C0805C104K5RAC7411").valid
    assert decode_mpn(kemet, "C0805C104K5RAC7210").valid
    bulk = decode_mpn(kemet, "C0603C104K5RAC")
    assert bulk is not None and bulk.valid and bulk.codes["cspec"] == ""


def test_fields(kemet) -> None:
    d = decode_mpn(kemet, "C0603C104K5RACTU")
    assert d is not None
    assert d.fields["Capacitance"] == "100nF" and d.fields["Voltage"] == "50V" and d.fields["Tolerance"] == "±10%"
    assert d.fields["Dielectric"] == "X7R" and d.fields["Type"] == "MLCC" and d.fields["Height"] == "0.95mm"


# --------------------------------------------------------------------------- laser marking (datasheet p. 20)

# "Laser marking option is not available on: EIA 0402 case size devices … X7R products in capacitance values"
# up to these limits (pF); 1805 is not listed
_NO_MARKING_UP_TO_PF = {"0603": 170, "0805": 150, "1206": 910, "1210": 2000, "1808": 3900, "1812": 6700,
                        "1825": 18000, "2220": 27000, "2225": 33000}


def test_markable_attribute_follows_the_datasheet_limits(kemet) -> None:
    counts = {"1": 0, "0": 0}
    for cell in kemet.availability:
        pf = int(cell.value[:2]) * 10 ** int(cell.value[2]) if cell.value[2] not in "89" else \
            int(cell.value[:2]) * {"9": 0.1, "8": 0.01}[cell.value[2]]
        limit = _NO_MARKING_UP_TO_PF.get(cell.size)
        expected = cell.size != "0402" and (limit is None or pf > limit)
        assert cell.attrs["markable"] == ("1" if expected else "0"), (cell.size, cell.value)
        counts[cell.attrs["markable"]] += 1
    assert counts["1"] > 0 and counts["0"] > 0


@pytest.mark.parametrize(("mpn", "valid", "hint"), [
    ("C0402C104K3RACTM", False, "gilt nicht für Baugröße 0402"),  # no marking on 0402
    ("C0603C101K5RACTM", False, "passend: TU"),  # 100 pF <= 170 pF
    ("C0603C181K5RACTM", True, None),
    ("C0603C151K5RAC7040", False, "passend: 7411"),  # the equivalent 13" reel, unmarked
    ("C0603C104K5RAC7040", True, None),
    ("C0805C101K5RAC7215", False, "passend: 7210"),  # 100 pF <= 150 pF
    ("C0805C104K5RAC7215", True, None),
    ("C1206C102K5RACTM", True, None),  # 1000 pF > 910 pF
    ("C1805C102K5RACTM", True, None),  # 1805: no limit listed
])
def test_marking_vectors(kemet, mpn: str, valid: bool, hint: str | None) -> None:
    """Regression: TM was allowed for 0402 and TM/7040/7215 for every capacitance."""
    d = decode_mpn(kemet, mpn)
    assert d is not None and d.valid is valid, d.messages
    if hint:
        assert any(hint in m for m in d.messages), d.messages
