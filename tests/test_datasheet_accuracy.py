"""Datasheet import: accuracy of the recorded Claude answers against the corpus ground truth.

The recorded answers (tests/data/ai_fixtures, claude-opus-5-5 at effort low, 2026-10-08) are normalised exactly as
the pipeline does and scored with :func:`partforge.datasheet.evaluate.compare` against
tests/data/corpus/manifest.json. The report is written to tests/_tmp/datasheet_accuracy.json.

Measured when recording: every MPN, every pin (incl. partial overbars such as TCLK_R/F\\), every outline dimension;
land patterns 27 of 28 values (LTC MS8: the inner span is printed as a range 3.20–3.45, Claude used 3.20).
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from partforge.datasheet.evaluate import AccuracyReport, compare, manifest_entry
from partforge.datasheet.extract import apply_verification, parse_geometry, parse_identity
from partforge.datasheet.models import ExtractionData
from partforge.datasheet.normalize import GEOMETRY_ISSUES, IDENTITY_ISSUES, normalize_extraction
from partforge.datasheet.schema import AiGeometry, AiIdentity
from partforge.db.categories import builtin_templates

log = logging.getLogger(__name__)

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
MANIFEST = DATA / "corpus" / "manifest.json"
REPORT = Path(__file__).parent / "_tmp" / "datasheet_accuracy.json"
STEMS = ["opa656", "LTC6244", "25AA02E48", "sn65lv1023a"]

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not MANIFEST.is_file(), reason="Testdaten fehlen")


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _text(call: dict[str, Any]) -> str:
    return "".join(b.get("text", "") for b in call["message"]["content"] if b["type"] == "text")


def recorded_extraction(stem: str) -> tuple[ExtractionData, dict[str, Any]]:
    """Normalise the recorded answers exactly like the pipeline (a verification answer is merged into its pass with
    :func:`partforge.datasheet.extract.apply_verification`)."""
    fx = json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))
    calls = {call["kind"]: call for call in fx["calls"]}
    identity, geometry = parse_identity(_text(calls["identity"])), parse_geometry(_text(calls["geometry"]))

    def normalised(ident: AiIdentity, geo: AiGeometry) -> ExtractionData:
        return normalize_extraction(ident, geo, pages=calls["identity"]["pages"],
                                    geometry_pages=calls["geometry"]["pages"], categories=builtin_templates())

    data = normalised(identity, geometry)
    for kind, codes in (("identity", IDENTITY_ISSUES), ("geometry", GEOMETRY_ISSUES)):
        call = calls.get(f"verify_{kind}")
        if call is None:
            continue
        issues = [i for i in data.issues if i.vision and i.code in codes and i.severity in ("error", "warning")]
        verified = parse_identity(_text(call)) if kind == "identity" else parse_geometry(_text(call))
        outcome = apply_verification(identity, geometry, data, verified, issues, codes, normalised)
        if outcome is not None:
            identity, geometry, data, _notes = outcome
    return data, fx


@pytest.fixture(scope="module")
def reports(manifest) -> dict[str, AccuracyReport]:
    out: dict[str, AccuracyReport] = {}
    for stem in STEMS:
        data, fx = recorded_extraction(stem)
        out[stem] = compare(data, manifest_entry(manifest, fx["pdf"]))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({stem: {**r.model_dump(mode="json"), "summary": r.summary()}
                                  for stem, r in out.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in out.values():
        log.info(r.summary())
    return out


@pytest.mark.parametrize("stem", STEMS)
def test_mpns_pins_and_dimensions_match_the_ground_truth(reports, stem):
    report = reports[stem]
    assert report.mpns.ratio == 1.0, report.mpns.misses
    assert report.pins.ratio == 1.0, report.pins.misses
    assert report.pin_types.ratio >= 0.95, report.pin_types.misses
    assert report.dimensions.ratio == 1.0, report.dimensions.misses
    assert report.unmatched_packages == []
    assert report.extra_mpns == []


def test_land_patterns(reports):
    matched = sum(r.land_patterns.matched for r in reports.values())
    total = sum(r.land_patterns.total for r in reports.values())
    assert total >= 25
    assert matched / total >= 0.95, [m for r in reports.values() for m in r.land_patterns.misses]


def test_totals_and_report_file(reports):
    assert sum(r.pins.total for r in reports.values()) == 13 + 17 + 14 + 120
    assert sum(r.mpns.total for r in reports.values()) == 8 + 22 + 3 + 16
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    assert set(data) == set(STEMS) and data["opa656"]["summary"].startswith("pdfs/opa656.pdf: MPNs 8/8")


def test_overbars_and_exposed_pads_survive_normalisation():
    data, _ = recorded_extraction("25AA02E48")
    soic = {p.number: p for p in data.devices[0].pin_table("SN").pins}
    assert (soic["1"].name, soic["3"].name, soic["7"].name) == ("C\\S\\", "W\\P\\", "H\\O\\L\\D\\")
    assert soic["1"].active_low and not soic["2"].active_low
    sn65, _ = recorded_extraction("sn65lv1023a")
    ser = {p.number: p for p in sn65.devices[0].pin_table("DB").pins}
    assert ser["13"].name == "TCLK_R/F\\" and ser["24"].name == "P\\W\\R\\D\\N\\"
    rhb = sn65.package("RHB")
    assert rhb is not None and rhb.exposed_pad and rhb.dim("D2").nom == 3.45
    ltc, _ = recorded_extraction("LTC6244")
    dd = ltc.devices[0].pin_table("DD")
    assert dd is not None and [p.exposed_pad for p in dd.pins] == [False] * 8 + [True]
    assert {p.part for p in dd.pins} == {0, 1, 2}


# --------------------------------------------------------------------------- the scorer itself


def test_compare_reports_misses(manifest):
    data, fx = recorded_extraction("opa656")
    bad = copy.deepcopy(data)
    bad.devices[0].variants = bad.devices[0].variants[1:]
    pins = bad.devices[0].pin_table("D").pins
    pins[1].name = "IN+"
    pins[3].electrical = "passive"
    soic = bad.package("D")
    assert soic is not None
    soic.dim("e").nom = 1.0
    soic.land_pattern.row_spacing = 4.0
    report = compare(bad, manifest_entry(manifest, fx["pdf"]))
    assert report.mpns.matched == report.mpns.total - 1 and "MPN OPA656U fehlt" in report.mpns.misses
    assert any("Pin 2" in m for m in report.pins.misses)
    assert any("Pin 4" in m for m in report.pin_types.misses)
    assert any("e.nom" in m for m in report.dimensions.misses)
    assert any("Reihenabstand" in m for m in report.land_patterns.misses)
    empty = compare(ExtractionData(), manifest_entry(manifest, fx["pdf"]))
    assert empty.pins.matched == 0 and set(empty.unmatched_packages) == {"SOIC-8", "SOT-23-5"}
    with pytest.raises(KeyError):
        manifest_entry(manifest, "fehlt.pdf")
