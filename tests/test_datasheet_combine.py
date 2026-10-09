"""Datasheet import: saving only the symbols or only the footprints, package drawings without device and packages
taken over from another datasheet (``partforge.datasheet.combine``).

Modelled on a real case: the TI LM25190-Q1 datasheet names its package (RGY, VQFN-19 3.5×4.5) without a dimensioned
drawing, the separate TI document ``qfnd819.pdf`` has the drawing of RGY0019B (pins 1/19 and 10/11 on the short sides,
one empty position on the right side, exposed pad 20) but no device. ``partforge.altium.sync`` is replaced by a fake
that only registers the records.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.datasheet import store
from partforge.datasheet.combine import merge_package, package_sources, package_targets, unmerge_package
from partforge.datasheet.errors import CommitRefused, DatasheetError
from partforge.datasheet.extract import store_edited_extraction
from partforge.datasheet.models import (
    DeviceData,
    DimValue,
    ExtractionData,
    LandPatternData,
    PackageData,
    ParameterData,
    PinData,
    PinTableData,
    ProposalChoices,
    TerminalLayout,
    VariantData,
)
from partforge.datasheet.normalize import validate_extraction
from partforge.datasheet.proposal import build_proposal, commit_proposal
from partforge.db import parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.workspace import Workspace

PDFS = Path(__file__).parent / "data" / "corpus" / "pdfs"

pytestmark = pytest.mark.skipif(not PDFS.is_dir(), reason="Testdaten fehlen")

RGY_LAYOUT = TerminalLayout(pins_x=2, pins_y=8, pitch_x=1.5, pin1="top", missing=[14])
NAMES = ["ISET", "RT", "COMP", "FB", "AGND", "IMON", "VCC", "PGND", "LO", "VIN", "HO", "SW", "CBOOT", "BIAS", "PGOOD",
         "SYNC", "EN", "ISNS+", "VOUT"]


def _dim(symbol: str, lo: float | None = None, nom: float | None = None, hi: float | None = None) -> DimValue:
    return DimValue(symbol=symbol, min=lo, nom=nom, max=hi)


def device_extraction() -> ExtractionData:
    """LM25190-Q1 as analysed: pin table and part number, the RGY package without a dimensioned drawing."""
    pins = [PinData(number=str(n), name=name, electrical="passive") for n, name in enumerate(NAMES, start=1)]
    pins.append(PinData(number="EP", name="EP", electrical="power", exposed_pad=True))
    rgy = PackageData(code="RGY", name="VQFN-19 3.5x4.5", family="nolead", pin_count=19, mounting="SMD",
                      exposed_pad=True, pages=[49],
                      dimensions=[_dim("D", nom=3.5), _dim("E", nom=4.5), _dim("e", nom=0.5), _dim("A", hi=1.0)])
    device = DeviceData(base_part="LM25190-Q1", description="42V synchronous buck controller",
                        category="Integrated Circuits", parameters=[ParameterData(column="Function", value="Treiber")],
                        pin_tables=[PinTableData(package="RGY", pages=[4], pins=pins)],
                        variants=[VariantData(mpn="LM25190QRGYRQ1", package="RGY", pages=[45])])
    data = ExtractionData(manufacturer="Texas Instruments", title="LM25190-Q1", devices=[device], packages=[rgy])
    data.issues = validate_extraction(data)
    return data


def drawing_package(*, layout: TerminalLayout | None = RGY_LAYOUT) -> PackageData:
    """RGY0019B as drawn in qfnd819.pdf (pages 1–2)."""
    land = LandPatternData(present=True, pages=[2], pad_shape="rounded_rectangle", pad_width=0.25, pad_length=0.6,
                           pitch=0.5, row_spacing=3.3, row_spacing_reference="center_to_center",
                           thermal_pad_width=1.7, thermal_pad_length=2.3)
    return PackageData(
        code="RGY0019B", name="VQFN-19 3.5x4.5", family="nolead", pin_count=19, mounting="SMD", exposed_pad=True,
        exposed_pad_number="20", pages=[1], land_pattern=land, layout=layout,
        dimensions=[_dim("A", 0.8, None, 1.0), _dim("A1", 0.0, None, 0.05), _dim("D", 4.4, None, 4.6),
                    _dim("E", 3.4, None, 3.6), _dim("b", 0.2, None, 0.3), _dim("L", 0.3, None, 0.5),
                    _dim("e", nom=0.5), _dim("D2", 2.2, 2.3, 2.4), _dim("E2", 1.6, 1.7, 1.8)])


def drawing_extraction(*, layout: TerminalLayout | None = RGY_LAYOUT) -> ExtractionData:
    data = ExtractionData(manufacturer="Texas Instruments", document_id="4230037/A", title="RGY0019B VQFN",
                          packages=[drawing_package(layout=layout)])
    data.issues = validate_extraction(data)
    return data


def stored(workspace: Workspace, pdf: str, data: ExtractionData) -> str:
    """A datasheet record with this extraction (as if Claude had analysed the PDF)."""
    rec, _ = store.ingest_bytes((PDFS / pdf).read_bytes(), pdf, ws=workspace)

    def put(_rec: Any, meta: Any) -> None:
        meta.extraction, meta.model, meta.extracted = data, "claude-opus-5-5", store.now_iso()

    store.update_meta(rec.id, put)
    return rec.id


@pytest.fixture
def fake_sync(monkeypatch) -> dict[str, list[Any]]:
    from partforge.altium import sync

    calls: dict[str, list[Any]] = {"symbols": [], "footprints": []}

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None, allow_pin_changes=False):
        calls["symbols"].append([s.name for s in specs])
        return [registry.upsert_symbol(SymbolRecord(name=s.name, library=r"Symbols\PF_ICs.SchLib", source=source,
                                                    spec=s, status="ok")) for s in specs]

    def ensure_footprints(specs, *, source="generated", ctx=None):
        calls["footprints"].append([s.name for s in specs])
        return [registry.upsert_footprint(FootprintRecord(name=s.name, library=r"Footprints\PF_NOLEAD.PcbLib",
                                                          source=source, spec=s, status="ok")) for s in specs]

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    return calls


@pytest.fixture
def pair(workspace) -> tuple[str, str]:
    """(device datasheet, package drawing) of the open test library."""
    return stored(workspace, "AD7983.pdf", device_extraction()), stored(workspace, "ADG736.pdf", drawing_extraction())


# --------------------------------------------------------------------------- package drawings without device


def test_a_package_drawing_without_device_is_no_error():
    data = drawing_extraction()
    assert [(i.code, i.severity, i.vision) for i in data.issues] == [("package_only", "info", False)]
    empty = ExtractionData(packages=[PackageData(code="X")])  # no device and nothing drawn: still an error
    checks = {i.code: i.severity for i in validate_extraction(empty)}
    assert checks["no_device"] == "error" and "package_only" not in checks


def test_a_package_drawing_proposes_only_its_footprint(workspace, pair, fake_sync):
    _device, drawing = pair
    proposal = build_proposal(drawing, ws=workspace, svg=False)
    assert proposal.package_only and proposal.device == "" and not proposal.symbols and not proposal.variants
    assert [f.package for f in proposal.footprints] == ["RGY0019B"]
    footprint = proposal.footprints[0]
    assert footprint.valid and footprint.pad_count == 20 and footprint.name.startswith("QFN50P350X450X100-20N")
    assert not proposal.ready and proposal.ready_footprints and not proposal.ready_symbols
    with pytest.raises(CommitRefused, match="nur Gehäuse"):
        commit_proposal(None, drawing, ProposalChoices(), ws=workspace)
    result = commit_proposal(None, drawing, ProposalChoices(scope="footprints", expected_fingerprint=proposal.fingerprint),
                             ws=workspace)
    assert result["message"] == "Gespeichert: 1 Footprint" and result["footprints"] == [footprint.name]
    assert result["libraries"] == [r"Footprints\PF_NOLEAD.PcbLib"] and fake_sync["symbols"] == []
    meta = store.load_meta(store.get_record(drawing))
    assert [(c.scope, c.footprints, c.created) for c in meta.committed] == [("footprints", [footprint.name], [])]
    again = build_proposal(drawing, ws=workspace, svg=False)
    assert again.footprints[0].exists and not again.ready_footprints  # saved: nothing left to write
    with pytest.raises(CommitRefused, match="Nichts zu speichern"):
        commit_proposal(None, drawing, ProposalChoices(scope="footprints"), ws=workspace)


def test_the_terminal_layout_reaches_the_generator(workspace):
    plain = stored(workspace, "ADG736.pdf", drawing_extraction(layout=None))
    footprint = build_proposal(plain, ws=workspace, svg=False).footprints[0]
    assert not footprint.valid and any("durch 4 teilbar" in w for w in footprint.warnings)
    data = store.load_meta(store.get_record(plain)).extraction
    data.packages[0].layout = TerminalLayout(pins_x=2, pins_y=8, pitch_x=1.5, pin1="top", missing=[14, 14, 0])
    clean = store_edited_extraction(plain, data, ws=workspace)
    assert clean.packages[0].layout == RGY_LAYOUT  # duplicates and impossible positions dropped
    spec = build_proposal(plain, ws=workspace, svg=False).footprints[0].spec
    pads = {p.designator: p for p in spec.pads}
    assert (pads["1"].x, pads["19"].x) == (-0.75, 0.75) and pads["1"].y > 2 and pads["20"].thermal
    assert [pads[str(n)].y for n in (12, 13, 14)] == [-1.75, -1.25, -0.25]  # position -0.75 stays empty
    data.packages[0].layout = TerminalLayout()
    assert store_edited_extraction(plain, data, ws=workspace).packages[0].layout is None  # nothing left: no layout


def test_a_rectangular_manufacturer_land_pattern_needs_the_spacing_of_the_end_rows(workspace, pair):
    _device, drawing = pair
    choices = ProposalChoices(packages={"RGY0019B": {"footprint": "manufacturer"}})
    footprint = build_proposal(drawing, choices, ws=workspace, svg=False).footprints[0]
    assert not footprint.valid and any("oben/unten fehlt der eigene Reihenabstand" in w for w in footprint.warnings)
    data = store.load_meta(store.get_record(drawing)).extraction
    data.packages[0].land_pattern.row_spacing_y = 4.3
    store_edited_extraction(drawing, data, ws=workspace)
    footprint = build_proposal(drawing, choices, ws=workspace, svg=False).footprints[0]
    pads = {p.designator: p for p in footprint.spec.pads}
    assert footprint.valid and footprint.mode == "manufacturer"
    assert (pads["1"].y, pads["10"].y, pads["2"].x, pads["1"].height) == (2.15, -2.15, -1.65, 0.6)


# --------------------------------------------------------------------------- only the symbols / only the footprints


def test_only_the_symbol_of_a_device_without_drawing(workspace, pair, fake_sync):
    device, _drawing = pair
    proposal = build_proposal(device, ws=workspace, svg=False)
    assert not proposal.ready and not proposal.footprints[0].valid  # no b, L, D2/E2: no footprint
    assert proposal.ready_symbols and not proposal.ready_footprints
    symbol = proposal.symbols[0]
    assert symbol.valid and symbol.name == "LM25190-Q1" and "20" in {p.designator for p in symbol.spec.pins}
    with pytest.raises(CommitRefused, match="Footprints können so nicht gespeichert werden"):
        commit_proposal(None, device, ProposalChoices(scope="footprints"), ws=workspace)
    result = commit_proposal(None, device, ProposalChoices(scope="symbols", expected_fingerprint=proposal.fingerprint),
                             ws=workspace)
    assert result["message"] == "Gespeichert: 1 Symbol" and result["created"] == [] and result["scope"] == "symbols"
    assert fake_sync == {"symbols": [["LM25190-Q1"]], "footprints": []}
    assert parts.get_part("Integrated Circuits", "LM25190QRGYRQ1") is None  # no part, only the SchLib


def test_scope_is_not_part_of_the_fingerprint(workspace, pair):
    device, _drawing = pair
    proposal = build_proposal(device, ws=workspace, svg=False)
    for scope in ("symbols", "footprints"):
        assert build_proposal(device, ProposalChoices(scope=scope), ws=workspace, svg=False).fingerprint == \
            proposal.fingerprint


def test_blockers_stop_only_the_scopes_they_concern(workspace, fake_sync):
    data = device_extraction()
    data.devices[0].pin_tables[0].pins.pop(0)  # 18 pins for 19 terminals: the symbol and the drawing disagree
    device = stored(workspace, "AD7983.pdf", data)
    store_edited_extraction(device, data, ws=workspace)  # recheck: pin_count (error)
    proposal = build_proposal(device, ws=workspace, svg=False)
    count = next(t for t in proposal.blocker_targets if "18 Pins in der Pintabelle" in t.blocker)
    assert count.scopes == ["part", "symbols", "footprints"]
    assert not proposal.ready_symbols
    with pytest.raises(CommitRefused, match="bestätigen") as refused:
        commit_proposal(None, device, ProposalChoices(scope="symbols"), ws=workspace)
    assert refused.value.code == "unconfirmed_blockers" and fake_sync["symbols"] == []
    confirmed = ProposalChoices(scope="symbols", accept_issues=[count.blocker])
    assert build_proposal(device, confirmed, ws=workspace, svg=False).ready_symbols
    result = commit_proposal(None, device, confirmed, ws=workspace)
    assert result["symbols"] == ["LM25190-Q1"] and result["warnings"] == [f"Bestätigt: {count.blocker}"]


# --------------------------------------------------------------------------- package from another datasheet


def test_package_sources_rank_the_matching_drawing_first(workspace, pair):
    device, drawing = pair
    other = drawing_extraction()
    other.packages[0] = other.packages[0].model_copy(update={"code": "RHL0016A", "name": "VQFN-16", "pin_count": 16})
    stored(workspace, "AD5235.pdf", other)
    sources = package_sources(device, "RGY")
    best, worse = sources[0], sources[1]
    assert (best.datasheet_id, best.package) == (drawing, "RGY0019B")
    assert best.score > worse.score and best.package_only and best.land_pattern and best.dimensions == 9
    assert "gleiche Anschlusszahl (19)" in best.matches and "Gehäusecode passt (RGY → RGY0019B)" in best.matches
    assert worse.problems == ["16 statt 19 Anschlüsse"]
    assert all(s.datasheet_id != device for s in sources)
    with pytest.raises(DatasheetError, match="nicht beschrieben"):
        package_sources(device, "XYZ")


def test_package_targets_find_the_device_whose_dimensions_are_missing(workspace, pair):
    device, drawing = pair
    complete = device_extraction()
    complete.devices[0].base_part = "OTHER-1"
    complete.packages[0] = drawing_package().model_copy(update={"code": "RGY", "layout": None})
    complete.issues = validate_extraction(complete)
    other = stored(workspace, "AD5235.pdf", complete)
    targets = package_targets(drawing, "RGY0019B")
    assert [(t.datasheet_id, t.package) for t in targets] == [(device, "RGY"), (other, "RGY")]
    best = targets[0]
    assert best.devices == ["LM25190-Q1"] and best.dims_missing and best.dimensions == 4
    assert "Maße fehlen dort" in best.matches and "gleiche Anschlusszahl (19)" in best.matches
    assert not targets[1].dims_missing and targets[1].score < best.score
    merge_package(device, "RGY", drawing, "RGY0019B", ws=workspace)
    assert [t.datasheet_id for t in package_targets(drawing, "RGY0019B")] == [other]  # took this drawing over already
    with pytest.raises(DatasheetError, match="stammen selbst aus"):
        package_targets(device, "RGY")  # a merged package passes its drawing on only from the original document
    bare = drawing_extraction()
    bare.packages[0] = PackageData(code="RGY0019B", name="VQFN-19")
    with pytest.raises(DatasheetError, match="keine Maße"):
        package_targets(stored(workspace, "LTC6244.pdf", bare), "RGY0019B")


def test_merging_the_drawing_completes_the_part(workspace, pair, fake_sync):
    device, drawing = pair
    result = merge_package(device, "RGY", drawing, "RGY0019B", ws=workspace)
    assert result.notes == [("Aus „ADG736.pdf“ übernommen (VQFN-19 3.5x4.5 (RGY0019B)): 9 Maße, Herstellerempfehlung, "
                             "Exposed Pad 20.")]
    pkg = result.extraction.package("RGY")
    assert (pkg.code, pkg.name, pkg.exposed_pad_number, pkg.layout) == ("RGY", "VQFN-19 3.5x4.5", "20", RGY_LAYOUT)
    assert len(pkg.dimensions) == 9 and pkg.land_pattern.complete() and pkg.pages == [1]
    assert (pkg.origin.datasheet_id, pkg.origin.package, pkg.origin.file) == (drawing, "RGY0019B", "ADG736.pdf")
    assert pkg.origin.replaced is not None and len(pkg.origin.replaced.dimensions) == 4
    assert not any(i.code == "dims_missing" for i in result.extraction.issues)
    meta = store.load_meta(store.get_record(device))
    assert meta.edited and meta.extraction.package("RGY").origin is not None
    proposal = build_proposal(device, ws=workspace, svg=False)
    assert proposal.ready and proposal.blockers == []
    footprint, symbol = proposal.footprints[0], proposal.symbols[0]
    assert footprint.valid and footprint.pad_count == 20
    assert "20" in {p.designator for p in symbol.spec.pins}  # the exposed pad pin gets the drawing's pad 20
    variant = proposal.variants[0]
    assert (variant.footprint, variant.values.get("Height"), variant.values.get("Package")) == (
        footprint.name, "1mm", "VQFN-19 3.5x4.5")
    result = commit_proposal(None, device, ProposalChoices(expected_fingerprint=proposal.fingerprint), ws=workspace)
    assert result["created"] == ["LM25190QRGYRQ1"] and result["footprints"] == [footprint.name]
    assert parts.get_part("Integrated Circuits", "LM25190QRGYRQ1")["Footprint Ref"] == footprint.name


def test_the_footprint_saved_from_the_drawing_is_reused_after_merging(workspace, pair, fake_sync):
    device, drawing = pair
    commit_proposal(None, drawing, ProposalChoices(scope="footprints"), ws=workspace)
    commit_proposal(None, device, ProposalChoices(scope="symbols"), ws=workspace)
    merge_package(device, "RGY", drawing, "RGY0019B", ws=workspace)
    proposal = build_proposal(device, ws=workspace, svg=False)
    assert proposal.ready and proposal.footprints[0].exists and proposal.symbols[0].exists
    result = commit_proposal(None, device, ProposalChoices(), ws=workspace)
    assert result["created"] == ["LM25190QRGYRQ1"] and result["symbols"] == [] and result["footprints"] == []
    assert len(fake_sync["footprints"]) == 1 and len(fake_sync["symbols"]) == 1  # each written once


def test_unmerge_restores_the_package_before_the_first_takeover(workspace, pair):
    device, drawing = pair
    before = store.load_meta(store.get_record(device)).extraction.package("RGY")
    merge_package(device, "RGY", drawing, "RGY0019B", ws=workspace)
    merge_package(device, "RGY", drawing, "RGY0019B", ws=workspace)  # twice: the original stays the one to restore
    restored = unmerge_package(device, "RGY", ws=workspace).package("RGY")
    assert restored.origin is None and restored.dimensions == before.dimensions and restored.layout is None
    with pytest.raises(DatasheetError, match="nicht aus einem anderen Datenblatt"):
        unmerge_package(device, "RGY", ws=workspace)


def test_merge_refusals(workspace, pair):
    device, drawing = pair
    with pytest.raises(DatasheetError, match="anderes Datenblatt"):
        merge_package(device, "RGY", device, "RGY", ws=workspace)
    with pytest.raises(DatasheetError, match="nicht beschrieben"):
        merge_package(device, "RGY", drawing, "QQQ", ws=workspace)
    with pytest.raises(DatasheetError, match="keine Maße"):  # the device's own RGY drawing is only nominal: skip it
        bare = drawing_extraction()
        bare.packages[0] = PackageData(code="RGY0019B", name="VQFN-19")
        merge_package(device, "RGY", stored(workspace, "AD5235.pdf", bare), "RGY0019B", ws=workspace)
    merge_package(device, "RGY", drawing, "RGY0019B", ws=workspace)
    third = stored(workspace, "LTC6244.pdf", device_extraction())
    with pytest.raises(DatasheetError, match="stammen selbst aus"):
        merge_package(third, "RGY", device, "RGY", ws=workspace)


# --------------------------------------------------------------------------- API


def _wait(client: TestClient, job: dict[str, Any], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Job {job['id']} läuft noch")


def test_api_merge_and_save_separately(client, workspace, fake_sync):
    device = stored(workspace, "AD7983.pdf", device_extraction())
    drawing = stored(workspace, "ADG736.pdf", drawing_extraction())
    listed = {d["id"]: d for d in client.get("/api/datasheets").json()}
    assert listed[drawing]["package_only"] and not listed[device]["package_only"]
    sources = client.get(f"/api/datasheets/{device}/package-sources", params={"package": "RGY"}).json()
    assert [(s["datasheet_id"], s["package"]) for s in sources] == [(drawing, "RGY0019B")]
    assert client.get(f"/api/datasheets/{device}/package-sources", params={"package": "XYZ"}).status_code == 400
    targets = client.get(f"/api/datasheets/{drawing}/package-targets", params={"package": "RGY0019B"}).json()
    assert [(t["datasheet_id"], t["package"], t["dims_missing"]) for t in targets] == [(device, "RGY", True)]

    job = client.post(f"/api/datasheets/{device}/commit", json={"scope": "symbols"}).json()["job"]
    assert job["title"] == "Symbol aus „AD7983.pdf“ speichern"
    done = _wait(client, job)
    assert done["status"] == "done" and done["message"] == "Gespeichert: 1 Symbol", done["error"]
    assert done["result"]["scope"] == "symbols" and done["detail"]["steps"] == ["check", "symbols", "save"]
    shown = client.get(f"/api/datasheets/{device}").json()
    assert shown["status"] == "analysiert" and shown["saved_symbols"] == ["LM25190-Q1"]
    assert shown["committed"][0]["scope"] == "symbols"

    merged = client.post(f"/api/datasheets/{device}/merge-package",
                         json={"package": "RGY", "source_id": drawing, "source_package": "RGY0019B"})
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["edited"] and body["notes"][0].startswith("Aus „ADG736.pdf“ übernommen")
    package = next(p for p in body["extraction"]["packages"] if p["code"] == "RGY")
    assert package["origin"]["datasheet_id"] == drawing and package["layout"]["missing"] == [14]
    assert client.get(f"/api/datasheets/{device}").json()["merged_from"] == ["ADG736.pdf"]
    proposal = client.post(f"/api/datasheets/{device}/proposal", params={"svg": "false"}, json={}).json()
    assert proposal["ready"] and not proposal["ready_symbols"] and proposal["ready_footprints"]
    done = _wait(client, client.post(f"/api/datasheets/{device}/commit",
                                     json={"expected_fingerprint": proposal["fingerprint"]}).json()["job"])
    assert done["status"] == "done" and done["message"] == "Angelegt: 1 Bauteil, 1 Footprint", done["error"]
    assert client.get(f"/api/datasheets/{device}").json()["status"] == "übernommen"

    restored = client.post(f"/api/datasheets/{device}/unmerge-package", json={"package": "RGY"})
    assert restored.status_code == 200 and next(p for p in restored.json()["extraction"]["packages"]
                                                if p["code"] == "RGY")["origin"] is None
    again = client.post(f"/api/datasheets/{device}/unmerge-package", json={"package": "RGY"})
    assert again.status_code == 400 and "nicht aus einem anderen Datenblatt" in again.json()["detail"]
    refused = client.post(f"/api/datasheets/{device}/merge-package",
                          json={"package": "RGY", "source_id": "0" * 16, "source_package": "RGY0019B"})
    assert refused.status_code == 404

    done = _wait(client, client.post(f"/api/datasheets/{drawing}/commit", json={"scope": "footprints"}).json()["job"])
    assert done["status"] == "failed" and "Nichts zu speichern" in done["error"]  # saved with the part already
