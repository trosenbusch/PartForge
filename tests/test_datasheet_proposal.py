"""Datasheet import: part proposal (symbols, footprints, rows) and commit, built from REAL recorded Claude answers.

``partforge.altium.sync`` (written by another module) is replaced by a fake that only registers the records.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from partforge import events
from partforge.config import AppSettings
from partforge.datasheet import store
from partforge.datasheet.errors import CommitRefused, DatasheetError, NoExtraction
from partforge.datasheet.extract import ExtractOptions, run_extraction
from partforge.datasheet.llm import ReplayLlmClient
from partforge.datasheet.models import PackageChoice, ProposalChoices, SymbolChoice
from partforge.datasheet.proposal import build_proposal, commit_proposal, pin_pad_warnings, readable_pin_name
from partforge.db import parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.geometry.model import FootprintSpec, Pad, SymbolSpec, SymPin
from partforge.jobs import JobManager
from partforge.workspace import Workspace

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
PDFS = DATA / "corpus" / "pdfs"

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not PDFS.is_dir(), reason="Testdaten fehlen")


def extracted(workspace: Workspace, stem: str, *, source_url: str | None = None) -> str:
    fx = json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], source_url=source_url, ws=workspace)
    run_extraction(None, rec.id, ExtractOptions.model_validate(fx["options"]), ws=workspace,
                   client=ReplayLlmClient(fx["calls"]), settings=AppSettings())
    return rec.id


@pytest.fixture
def fake_sync(monkeypatch) -> dict[str, list[Any]]:
    from partforge.altium import sync

    calls: dict[str, list[Any]] = {"symbols": [], "footprints": [], "allow_pin_changes": []}

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None, allow_pin_changes=False):
        calls["symbols"].append(([s.name for s in specs], category, source))
        calls["allow_pin_changes"].append(allow_pin_changes)
        return [registry.upsert_symbol(SymbolRecord(name=s.name, library=r"Symbols\PF_Test.SchLib", source=source,
                                                    spec=s, status="ok")) for s in specs]

    def ensure_footprints(specs, *, source="generated", ctx=None):
        calls["footprints"].append(([s.name for s in specs], source))
        return [registry.upsert_footprint(FootprintRecord(name=s.name, library=r"Footprints\PF_TEST.PcbLib",
                                                          source=source, spec=s, status="ok")) for s in specs]

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    return calls


# --------------------------------------------------------------------------- proposals


def test_opa656_proposal(workspace):
    ds = extracted(workspace, "opa656")
    proposal = build_proposal(ds, ws=workspace)
    assert proposal.ready and proposal.category == "Amplifiers" and proposal.category_label == "Verstärker"
    assert proposal.device == "OPA656" and proposal.devices == ["OPA656"] and proposal.manufacturer == "Texas Instruments"
    assert proposal.cost.usd > 0 and proposal.cost.runs == 2 and proposal.cost.budget_usd > 0
    symbols = {s.package: s for s in proposal.symbols}
    assert set(symbols) == {"D", "DBV"}
    assert all(s.source == "standard" and s.kind == "opamp" and s.valid for s in symbols.values())
    assert symbols["D"].name != symbols["DBV"].name
    assert all(s.svg and s.svg.lstrip().startswith("<svg") for s in symbols.values())
    footprints = {f.package: f for f in proposal.footprints}
    soic, sot = footprints["D"], footprints["DBV"]
    assert soic.valid and soic.name.startswith("SOIC127P600X175-8N") and soic.pad_count == 8
    assert soic.family == "gullwing" and soic.mode == "ipc" and soic.svg and soic.request["family"] == "gullwing"
    assert soic.warnings == []  # NC pads 1, 5, 8 need no symbol pins
    # F2: ... and are recorded with the symbol, so the library check applies the same rule
    assert symbols["D"].spec.generator["nc_pads"] == ["1", "5", "8"]
    assert "nc_pads" not in symbols["DBV"].spec.generator  # SOT-23-5: every pad has a pin
    assert [a.mode for a in soic.alternatives] == ["manufacturer"] and soic.alternatives[0].valid
    assert sot.valid and sot.name.startswith("SOT95P280X145-5N") and sot.pad_count == 5
    assert len(proposal.variants) == 14
    item = next(v for v in proposal.variants if v.mpn == "OPA656U")
    path = workspace.abs(store.get_record(ds).file)
    assert item.status == "new" and item.part_number == "OPA656U" and item.warnings == []
    assert item.symbol == symbols["D"].name and item.footprint == soic.name
    values = item.values
    assert values["Manufacturer"] == "Texas Instruments" and values["Manufacturer Part Number"] == "OPA656U"
    assert values["Package"] == "SOIC-8" and values["Mounting"] == "SMD" and values["Height"] == "1.75mm"
    assert values["Operating Temperature"] == "-40°C … 85°C" and values["Lifecycle"] == "Aktiv"
    assert values["Amplifier Type"] == "Operationsverstärker" and values["Channels"] == "1"
    assert values["Description"] == "IC OPAMP 1CH 230MHz SOIC-8" and values["Comment"] == "OPA656U"
    assert values["ComponentLink1Description"] == "Datenblatt" and values["ComponentLink1URL"] == str(path)
    assert proposal.datasheet_link == str(path)
    sot_item = next(v for v in proposal.variants if v.mpn == "OPA656N/250")
    assert sot_item.footprint == sot.name and sot_item.values["Package"] == "SOT-23-5"


def test_proposal_without_svg_and_with_source_url(workspace):
    ds = extracted(workspace, "opa656", source_url="https://www.ti.com/lit/ds/symlink/opa656.pdf")
    proposal = build_proposal(ds, ws=workspace, svg=False)
    assert all(s.svg is None for s in proposal.symbols) and all(f.svg is None for f in proposal.footprints)
    assert proposal.datasheet_link == "https://www.ti.com/lit/ds/symlink/opa656.pdf"
    local = build_proposal(ds, ProposalChoices(link="file"), ws=workspace, svg=False)
    assert local.datasheet_link.endswith(".pdf") and local.datasheet_link != proposal.datasheet_link


def test_choices(workspace):
    ds = extracted(workspace, "opa656")
    choices = ProposalChoices(
        variants=["opa656u", "OPA656N/250", "GIBTSNICHT"],
        values={"Description": "Mein OPV", "Rail-to-Rail": "Nein", "Unbekannt": "x"},
        variant_values={"OPA656U": {"Notes": "Musterteil"}},
        packages={"D": PackageChoice(footprint="manufacturer"), "DBV": PackageChoice(density="L")},
        symbol=SymbolChoice(mode="ic"),
    )
    proposal = build_proposal(ds, choices, ws=workspace, svg=False)
    assert [v.mpn for v in proposal.variants] == ["OPA656U", "OPA656N/250"]
    assert "GIBTSNICHT" in proposal.warnings[0].upper()
    first = proposal.variants[0]
    assert first.values["Description"] == "Mein OPV" and first.values["Notes"] == "Musterteil"
    assert first.values["Rail-to-Rail"] == "Nein" and "Unbekannt" not in first.values
    footprints = {f.package: f for f in proposal.footprints}
    assert footprints["D"].mode == "manufacturer" and footprints["D"].alternatives[0].mode == "ipc"
    assert footprints["D"].spec.pads[0].width == pytest.approx(2.0)  # TI land pattern 0.60 x 2.00
    assert footprints["DBV"].name.endswith("L") or "L_" in footprints["DBV"].name
    assert {s.source for s in proposal.symbols} == {"ic"}
    assert {s.name for s in proposal.symbols} == {"OPA656 SOIC-8", "OPA656 SOT-23-5"}
    ic = next(s for s in proposal.symbols if s.package == "D")
    assert ic.pin_count == 8 and ic.spec.designator_prefix == "U"
    other_category = build_proposal(ds, ProposalChoices(category="Integrated Circuits"), ws=workspace, svg=False)
    assert other_category.category == "Integrated Circuits" and {s.source for s in other_category.symbols} == {"ic"}


def test_existing_symbol_and_footprint(workspace):
    ds = extracted(workspace, "opa656")
    fp = FootprintSpec(name="TI_SOIC8_HAUS", pads=[Pad(designator=str(i), x=i, y=0, width=0.5, height=1.5)
                                                  for i in range(1, 9)])
    registry.upsert_footprint(FootprintRecord(name=fp.name, library=r"Footprints\X.PcbLib", spec=fp, pad_count=8))
    sym = SymbolSpec(name="OPV_HAUS", pins=[SymPin(designator=str(i), x=0, y=-100 * i, orientation="left")
                                            for i in (2, 3, 4, 6, 7)])
    registry.upsert_symbol(SymbolRecord(name=sym.name, library=r"Symbols\X.SchLib", spec=sym, pin_count=5))
    choices = ProposalChoices(variants=["OPA656U"], packages={"D": PackageChoice(footprint="existing",
                                                                                 existing="TI_SOIC8_HAUS")},
                              symbol=SymbolChoice(mode="existing", existing="OPV_HAUS"))
    proposal = build_proposal(ds, choices, ws=workspace, svg=True)
    assert proposal.ready
    assert proposal.footprints[0].mode == "existing" and proposal.footprints[0].exists and proposal.footprints[0].svg
    assert proposal.symbols[0].source == "existing" and proposal.symbols[0].name == "OPV_HAUS"
    assert proposal.variants[0].footprint == "TI_SOIC8_HAUS" and proposal.variants[0].symbol == "OPV_HAUS"
    missing = build_proposal(ds, ProposalChoices(variants=["OPA656U"], symbol=SymbolChoice(mode="existing",
                                                                                          existing="FEHLT")),
                             ws=workspace, svg=False)
    assert not missing.ready and "FEHLT" in missing.symbols[0].warnings[0]


def test_ltc6244_shares_the_standard_dual_opamp_symbol(workspace):
    ds = extracted(workspace, "LTC6244")
    proposal = build_proposal(ds, ws=workspace, svg=False)
    assert proposal.devices == ["LTC6244", "LTC6244HV"] and proposal.ready
    assert len(proposal.symbols) == 1
    symbol = proposal.symbols[0]
    assert symbol.kind == "opamp_dual" and symbol.packages == ["DD", "MS8"] and symbol.part_count >= 2
    dd = next(f for f in proposal.footprints if f.package == "DD")
    assert dd.pad_count == 9 and any(p.thermal and p.designator == "9" for p in dd.spec.pads)
    assert any("Exposed Pad 9" in w for w in dd.warnings)
    c_grade = next(v for v in proposal.variants if v.mpn == "LTC6244CDD#PBF")
    assert c_grade.values["Operating Temperature"] == "0°C … 70°C" and c_grade.values["Channels"] == "2"
    hv = build_proposal(ds, ProposalChoices(device="LTC6244HV"), ws=workspace, svg=False)
    assert hv.device == "LTC6244HV" and all(v.mpn.startswith("LTC6244HV") for v in hv.variants)


def test_25aa02e48_ic_symbols_with_overbars(workspace):
    ds = extracted(workspace, "25AA02E48")
    proposal = build_proposal(ds, ws=workspace, svg=False)
    assert proposal.category == "Integrated Circuits" and proposal.ready
    assert {s.name for s in proposal.symbols} == {"25AA02E48 SOIC-8", "25AA02E48 SOT-23-6"}
    soic = next(s for s in proposal.symbols if s.package == "SN")
    names = {p.designator: p.name for p in soic.spec.pins}
    assert names["1"] == "C\\S\\" and names["7"] == "H\\O\\L\\D\\" and names["8"] == "VCC"
    item = next(v for v in proposal.variants if v.mpn == "25AA02E48T-I/OT")
    assert item.values["Function"] == "Speicher" and item.values["Package"] == "SOT-23-6"


@pytest.mark.parametrize(("style", "designator"), [("next", "33"), ("EP", "EP")])
def test_sn65_exposed_pad_follows_the_house_style(workspace, style, designator):
    workspace.settings.footprint.exposed_pad_designator = style
    ds = extracted(workspace, "sn65lv1023a")
    proposal = build_proposal(ds, ProposalChoices(device="SN65LV1224B"), ws=workspace, svg=False)
    assert proposal.ready and len(proposal.variants) == 8
    rhb_symbol = next(s for s in proposal.symbols if s.package == "RHB")
    rhb_fp = next(f for f in proposal.footprints if f.package == "RHB")
    assert rhb_fp.pad_count == 33 and [p.designator for p in rhb_fp.spec.pads if p.thermal] == [designator]
    assert designator in {p.designator for p in rhb_symbol.spec.pins}
    assert pin_pad_warnings(rhb_symbol.spec, rhb_fp.spec, set()) == []


def test_status_exists_and_conflict(workspace):
    ds = extracted(workspace, "opa656")
    base = {"Manufacturer": "TI", "Description": "x", "Library Ref": "X", "Footprint Ref": "Y"}
    parts.create_part("Amplifiers", {**base, "Part Number": "OPA656U"}, allow_incomplete=True)
    parts.create_part("Integrated Circuits", {**base, "Part Number": "OPA656UB", "Function": "Sonstiges"},
                      allow_incomplete=True)
    proposal = build_proposal(ds, ProposalChoices(variants=["OPA656U", "OPA656UB"]), ws=workspace, svg=False)
    status = {v.mpn: (v.status, v.existing_table) for v in proposal.variants}
    assert status == {"OPA656U": ("exists", "Amplifiers"), "OPA656UB": ("conflict", "Integrated Circuits")}
    assert not proposal.ready
    only_existing = build_proposal(ds, ProposalChoices(variants=["OPA656U"]), ws=workspace, svg=False)
    assert only_existing.ready


def test_proposal_errors(workspace):
    rec, _ = store.ingest_bytes((PDFS / "ADG736.pdf").read_bytes(), "ADG736.pdf", ws=workspace)
    with pytest.raises(NoExtraction):
        build_proposal(rec.id, ws=workspace)
    ds = extracted(workspace, "opa656")
    with pytest.raises(DatasheetError, match="nicht enthalten"):
        build_proposal(ds, ProposalChoices(device="LM358"), ws=workspace)
    unknown = build_proposal(ds, ProposalChoices(category="Gibtsnicht"), ws=workspace, svg=False)
    assert not unknown.ready and "Gibtsnicht" in unknown.warnings[0]
    none_selected = build_proposal(ds, ProposalChoices(variants=[]), ws=workspace, svg=False)
    assert none_selected.variants == [] and not none_selected.ready


# --------------------------------------------------------------------------- commit


def test_commit_creates_symbols_footprints_and_parts(workspace, fake_sync):
    ds = extracted(workspace, "opa656")
    emitted: list[tuple] = []
    unsubscribe = events.subscribe(events.PARTS_CHANGED, lambda *a: emitted.append(a))
    try:
        result = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U", "OPA656N/250"]), ws=workspace,
                                 author="Tester")
    finally:
        unsubscribe()
    assert sorted(result["created"]) == ["OPA656N/250", "OPA656U"] and result["errors"] == {}
    assert len(result["symbols"]) == 2 and len(result["footprints"]) == 2 and result["warnings"] == []
    soic_symbol = registry.get_symbol(parts.get_part("Amplifiers", "OPA656U")["Library Ref"])
    assert soic_symbol.spec.generator["nc_pads"] == ["1", "5", "8"]  # F2: what sync.library_health reads
    from partforge.altium import sync

    health = sync.library_health()  # F2: the library check applies the rule of this proposal
    assert not [i.message for i in health["issues"] if i.check == "pin_pad_mismatch"]
    assert fake_sync["symbols"][0][1:] == ("Amplifiers", "datasheet")
    assert fake_sync["footprints"][0][1] == "datasheet"
    assert emitted == [("Amplifiers", True)]  # once, by upsert_parts – the commit adds no second event
    row = parts.get_part("Amplifiers", "OPA656U")
    assert row is not None
    assert row["Library Path"] == r"Symbols\PF_Test.SchLib" and row["Footprint Path"] == r"Footprints\PF_TEST.PcbLib"
    assert row["ComponentLink1Description"] == "Datenblatt" and row["ComponentLink1URL"].endswith(".pdf")
    assert row["PF Author"] == "Tester" and row["Description"] == "IC OPAMP 1CH 230MHz SOIC-8"
    rec = store.get_record(ds)
    meta = store.load_meta(rec)
    assert meta.committed[-1].table == "Amplifiers" and sorted(meta.committed[-1].created) == sorted(result["created"])
    assert "OPA656U" in rec.mpns

    again = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U"]), ws=workspace)
    assert again["skipped"] == ["OPA656U"] and again["symbols"] == [] and again["footprints"] == []
    parts.update_part("Amplifiers", "OPA656U", {"PF Status": "Freigegeben"})
    proposal = build_proposal(ds, ProposalChoices(variants=["OPA656U"]), ws=workspace, svg=False)
    assert not {"PF Status", "PF Created", "PF Modified", "PF Author"} & set(proposal.variants[0].values)
    updated = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U"], mode="update", overwrite_existing=True,
                                                        values={"Notes": "geprüft"}), ws=workspace)
    assert updated["updated"] == ["OPA656U"] and len(updated["symbols"]) == 1 and len(updated["footprints"]) == 1
    row = parts.get_part("Amplifiers", "OPA656U")
    assert row["Notes"] == "geprüft" and row["PF Status"] == "Freigegeben"  # the release status is kept


def test_commit_reports_sync_errors_and_blocks_invalid_proposals(workspace, fake_sync, monkeypatch):
    from partforge.altium import sync

    ds = extracted(workspace, "opa656")
    original = sync.ensure_footprints

    def failing(specs, *, source="generated", ctx=None):
        """The SOIC footprint cannot be written (e.g. open and modified in Altium), the SOT-23 one can."""
        soic = [s for s in specs if s.name.startswith("SOIC")]
        others = original([s for s in specs if s not in soic], source=source, ctx=ctx)
        return [FootprintRecord(name=s.name, library="x", status="error", status_message="Datei gesperrt")
                for s in soic] + others

    monkeypatch.setattr(sync, "ensure_footprints", failing)
    result = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U", "OPA656N/250"]), ws=workspace)
    # a part whose footprint was not written is not created (it would link to nothing)
    assert result["created"] == ["OPA656N/250"] and "Datei gesperrt" in result["errors"]["OPA656U"]
    assert any("Datei gesperrt" in w for w in result["warnings"])
    assert parts.get_part("Amplifiers", "OPA656U") is None
    assert all(not name.startswith("SOIC") for name in result["footprints"])
    meta = store.load_meta(store.get_record(ds))
    assert "OPA656U" in meta.committed[-1].errors and meta.committed[-1].created == ["OPA656N/250"]
    with pytest.raises(DatasheetError, match="Kategorie"):
        commit_proposal(None, ds, ProposalChoices(category="Gibtsnicht"), ws=workspace)
    with pytest.raises(DatasheetError, match="FEHLT"):
        commit_proposal(None, ds, ProposalChoices(symbol=SymbolChoice(mode="existing", existing="FEHLT")),
                        ws=workspace)


def test_commit_as_job_logs_steps(workspace, fake_sync):
    ds = extracted(workspace, "25AA02E48")
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet-commit", "Anlegen", commit_proposal, ds, None, ws=workspace)
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    assert len(job.result["created"]) == 3
    texts = [entry["text"] for entry in job.log]
    assert any("Footprint(s) werden angelegt" in t for t in texts)
    assert any("Symbol(e) werden angelegt" in t for t in texts)
    assert any(t.startswith("3 neu") for t in texts)


def _message(data: dict[str, Any]) -> dict[str, Any]:
    return {"id": "msg_x", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(data)}], "stop_reason": "end_turn",
            "usage": {"input_tokens": 100, "cache_creation_input_tokens": 5000, "output_tokens": 800}}


def test_passive_series_with_values_per_part_number(workspace, fake_sync):
    """Synthetic Vishay-like answer: resistance per MPN, chip footprint from L/W/H/T, standard resistor symbol."""
    def variant(mpn: str, value: str) -> dict[str, Any]:
        return {"mpn": mpn, "package_code": "0603", "temperature_range": "", "packaging": "Tape, 5000",
                "status": "", "notes": "", "values": [{"column": "Resistance", "value": value, "page": 2}], "page": 2}

    identity = {
        "manufacturer": "Vishay", "document_id": "20035", "document_title": "D/CRCW e3", "document_date": "2026",
        "devices": [{"base_part_number": "CRCW0603", "description": "Thick film chip resistor", "category": "Resistors",
                     "parameters": [{"column": "Tolerance", "value": "1%", "page": 1},
                                    {"column": "Power", "value": "0.1W", "page": 1},
                                    {"column": "TCR", "value": "100ppm/K", "page": 1},
                                    {"column": "Size", "value": "0603", "page": 1},
                                    {"column": "Operating Temperature", "value": "-55°C to 155°C", "page": 1}],
                     "variants": [variant("CRCW0603100RFKEA", "100Ω"), variant("CRCW060310K0FKEA", "10kΩ"),
                                  variant("CRCW06034K70FKEA", "4k7")],
                     "pin_tables": [{"package_code": "0603", "source_pages": [], "pins": [
                         {"number": n, "name": n, "function": "", "electrical_type": "Passive", "active_low": False,
                          "no_connect": False, "group": "", "part": 1} for n in ("1", "2")]}]}],
        "packages": [{"package_code": "0603", "package_name": "0603", "pin_count": 2, "exposed_pad": False}],
        "warnings": [],
    }
    geometry = {"packages": [{
        "package_code": "0603", "package_name": "0603", "family": "chip", "pin_count": 2, "mounting": "SMD",
        "outline_reference": "", "exposed_pad": False, "exposed_pad_number": "", "source_pages": [3],
        "dimensions": [
            {"symbol": "L", "description": "length", "unit": "mm", "min": 1.5, "nom": 1.55, "max": 1.65},
            {"symbol": "W", "description": "width", "unit": "mm", "min": 0.75, "nom": 0.85, "max": 0.95},
            {"symbol": "H", "description": "height", "unit": "mm", "min": 0.4, "nom": 0.45, "max": 0.5},
            {"symbol": "T1", "description": "top terminal length", "unit": "mm", "min": 0.2, "nom": 0.3, "max": 0.4}],
        "land_pattern": {"present": True, "source_pages": [3], "pad_shape": "rectangle", "pad_width": 1.0,
                         "pad_length": 0.75, "pitch": -1, "row_spacing": 0.75, "row_spacing_reference": "inner_edges",
                         "thermal_pad_width": -1, "thermal_pad_length": -1, "solder_mask_expansion": -1,
                         "notes": ""}}], "warnings": []}
    rec, _ = store.ingest_bytes((PDFS / "vishay_dcrcwe3.pdf").read_bytes(), "vishay_dcrcwe3.pdf", ws=workspace)
    run_extraction(None, rec.id, ExtractOptions(triage="off"), ws=workspace, settings=AppSettings(),
                   client=ReplayLlmClient([{"kind": "identity", "message": _message(identity)},
                                           {"kind": "geometry", "message": _message(geometry)}]))
    proposal = build_proposal(rec.id, ws=workspace, svg=False)
    assert proposal.ready and proposal.category == "Resistors", proposal.warnings
    assert [s.kind for s in proposal.symbols] == ["resistor"] and proposal.symbols[0].source == "standard"
    footprint = proposal.footprints[0]
    assert footprint.family == "chip" and footprint.pad_count == 2 and footprint.valid
    assert footprint.alternatives and footprint.alternatives[0].mode == "manufacturer"
    values = {v.mpn: v.values for v in proposal.variants}
    assert values["CRCW060310K0FKEA"]["Resistance"] == "10kΩ"
    assert values["CRCW06034K70FKEA"]["Resistance"] == "4.7kΩ"
    assert values["CRCW0603100RFKEA"]["Resistance"] == "100Ω"
    assert values["CRCW0603100RFKEA"]["Tolerance"] == "±1%" and values["CRCW0603100RFKEA"]["Size"] == "0603"
    assert values["CRCW0603100RFKEA"]["Operating Temperature"] == "-55°C … 155°C"
    assert values["CRCW0603100RFKEA"]["Notes"] == "Verpackung: Tape, 5000"
    result = commit_proposal(None, rec.id, None, ws=workspace)
    assert len(result["created"]) == 3
    assert parts.get_part("Resistors", "CRCW060310K0FKEA")["Resistance"] == "10kΩ"


def test_pin_pad_warnings():
    fp = FootprintSpec(name="F", pads=[Pad(designator=d, x=0, y=0, width=1, height=1, thermal=d == "9")
                                       for d in ("1", "2", "3", "9")])
    sym = SymbolSpec(name="S", pins=[SymPin(designator=d, x=0, y=0, orientation="left") for d in ("1", "4")])
    assert pin_pad_warnings(sym, fp, {"3"}) == [
        "Pins ohne Pad im Footprint: 4", "Pads ohne Pin im Symbol: 2",
        "Exposed Pad 9 ohne Pin im Symbol – auf der Leiterplatte laut Datenblatt anschließen."]


# --------------------------------------------------------------------------- review regressions


def _answer(call: dict[str, Any]) -> dict[str, Any]:
    return json.loads("".join(b.get("text", "") for b in call["message"]["content"] if b["type"] == "text"))


def _without_supply_pins(workspace: Workspace) -> str:
    """25AA02E48 whose SOIC pin table lost VSS (4) and VCC (8) – also in the verification answer."""
    fx = json.loads((FIXTURES / "25AA02E48.json").read_text(encoding="utf-8"))
    identity = _answer(fx["calls"][1])
    soic = next(t for t in identity["devices"][0]["pin_tables"] if t["package_code"] == "SN")
    soic["pins"] = [p for p in soic["pins"] if p["number"] not in ("4", "8")]
    calls = [fx["calls"][0], {**fx["calls"][1], "message": _message(identity)}, fx["calls"][2],
             {**fx["calls"][1], "kind": "verify_identity", "message": _message(identity)}]
    rec, _ = store.ingest_bytes((PDFS / fx["pdf"]).read_bytes(), fx["pdf"], ws=workspace)
    run_extraction(None, rec.id, ExtractOptions.model_validate(fx["options"]), ws=workspace,
                   client=ReplayLlmClient(calls), settings=AppSettings())
    return rec.id


def test_error_issues_and_pin_pad_mismatches_block_until_confirmed(workspace, fake_sync):
    """Reviewer case h9: a symbol without VCC/VSS must not be committed silently."""
    ds = _without_supply_pins(workspace)
    choice = ProposalChoices(variants=["25AA02E48-I/SN"])
    proposal = build_proposal(ds, choice, ws=workspace, svg=False)
    assert not proposal.ready
    assert any("6 Pins in der Pintabelle" in b for b in proposal.blockers)
    assert any(b.endswith("Pads ohne Pin im Symbol: 4, 8") for b in proposal.blockers)
    # K3: what each blocker concerns, structured (the UI highlights it without parsing the text)
    assert [t.blocker for t in proposal.blocker_targets] == proposal.blockers
    pads = next(t for t in proposal.blocker_targets if t.blocker.endswith("Pads ohne Pin im Symbol: 4, 8"))
    assert (pads.package, pads.pins, pads.pads) == ("SN", [], ["4", "8"])
    count = next(t for t in proposal.blocker_targets if "6 Pins in der Pintabelle" in t.blocker)
    assert count.pins == [] and count.pads == [] and count.package == "SN"
    with pytest.raises(DatasheetError, match="bestätigen"):
        commit_proposal(None, ds, choice, ws=workspace)
    assert fake_sync["symbols"] == [] and parts.get_part("Integrated Circuits", "25AA02E48-I/SN") is None
    # the SOT-23-6 variant is not affected by the SOIC table
    sot = build_proposal(ds, ProposalChoices(variants=["25AA02E48T-I/OT"]), ws=workspace, svg=False)
    assert sot.blockers == [] and sot.ready
    confirmed = ProposalChoices(variants=["25AA02E48-I/SN"], accept_issues=True)
    assert build_proposal(ds, confirmed, ws=workspace, svg=False).ready
    result = commit_proposal(None, ds, confirmed, ws=workspace)
    assert result["created"] == ["25AA02E48-I/SN"]
    assert any(w.startswith("Bestätigt:") and "Pads ohne Pin" in w for w in result["warnings"])


def _pin(number: str, name: str, etype: str, function: str = "") -> dict[str, Any]:
    return {"number": number, "name": name, "function": function, "electrical_type": etype, "active_low": False,
            "no_connect": name == "NC", "group": "", "part": 1}


def test_ground_pin_that_mentions_the_thermal_pad(workspace, fake_sync):
    """Reviewer case h3: 'GND: connect to the thermal pad' is a lead; the EP row is the exposed pad."""
    names = ["IN", "IN", "EN", "NC", "GND", "FB", "PG", "NC", "OUT", "OUT", "NC", "NC", "NC", "NC", "NC", "NC"]
    types = {"GND": "Power", "IN": "Power", "OUT": "Output", "EN": "Input", "FB": "Input", "PG": "OpenCollector",
             "NC": "Passive"}
    pins = [_pin(str(i), n, types[n], "Ground. Connect to the thermal pad." if n == "GND" else "")
            for i, n in enumerate(names, 1)]
    pins.append(_pin("EP", "PAD", "Power", "Exposed thermal pad, connect to GND"))
    identity = {"manufacturer": "Texas Instruments", "document_id": "X", "document_title": "LDO", "document_date": "",
                "devices": [{"base_part_number": "TPSX123", "description": "LDO regulator", "category": "Power Linear",
                             "parameters": [], "variants": [{"mpn": "TPSX123RGTR", "package_code": "RGT",
                                                             "temperature_range": "", "packaging": "", "status": "",
                                                             "notes": "", "values": [], "page": 1}],
                             "pin_tables": [{"package_code": "RGT", "source_pages": [1], "pins": pins}]}],
                "packages": [{"package_code": "RGT", "package_name": "VQFN-16 3x3", "pin_count": 16,
                              "exposed_pad": True}], "warnings": []}
    dims = [("D", 2.9, 3.0, 3.1), ("E", 2.9, 3.0, 3.1), ("e", -1, 0.5, -1), ("b", 0.18, 0.24, 0.3),
            ("L", 0.3, 0.4, 0.5), ("A", 0.8, 0.9, 1.0), ("D2", 1.6, 1.7, 1.8), ("E2", 1.6, 1.7, 1.8)]
    geometry = {"packages": [{
        "package_code": "RGT", "package_name": "VQFN-16 3x3", "family": "nolead", "pin_count": 16, "mounting": "SMD",
        "outline_reference": "", "exposed_pad": True, "exposed_pad_number": "", "source_pages": [1],
        "dimensions": [{"symbol": s, "description": s, "unit": "mm", "min": a, "nom": b, "max": c}
                       for s, a, b, c in dims],
        "land_pattern": {"present": False, "source_pages": [], "pad_shape": "unknown", "pad_width": -1,
                         "pad_length": -1, "pitch": -1, "row_spacing": -1, "row_spacing_reference": "not_applicable",
                         "thermal_pad_width": -1, "thermal_pad_length": -1, "solder_mask_expansion": -1,
                         "notes": ""}}], "warnings": []}
    rec, _ = store.ingest_bytes((PDFS / "ADG736.pdf").read_bytes(), "ldo.pdf", ws=workspace)
    client = ReplayLlmClient([{"kind": "identity", "message": _message(identity)},
                              {"kind": "geometry", "message": _message(geometry)}])
    run_extraction(None, rec.id, ExtractOptions(triage="off"), ws=workspace, client=client, settings=AppSettings())
    assert [r.kind for r in client.requests] == ["identity", "geometry"]  # no verification turn needed
    proposal = build_proposal(rec.id, ProposalChoices(symbol=SymbolChoice(mode="ic")), ws=workspace, svg=False)
    pins_by_number = {p.designator: p.name for p in proposal.symbols[0].spec.pins}
    assert pins_by_number["5"] == "GND" and pins_by_number["17"] == "EP"
    assert proposal.blockers == [] and proposal.ready
    assert not any("ohne Pin" in w or "ohne Pad" in w for w in proposal.footprints[0].warnings)


def _registered_symbol(name: str, pins: list[tuple[str, str]]) -> SymbolRecord:
    spec = SymbolSpec(name=name, pins=[SymPin(designator=d, name=n, x=0, y=-100 * i, orientation="left")
                                       for i, (d, n) in enumerate(pins)])
    return registry.upsert_symbol(SymbolRecord(name=name, library=r"Symbols\Alt.SchLib", spec=spec,
                                               pin_count=len(pins), status="ok"))


def test_a_symbol_name_with_another_pinout_is_never_linked_silently(workspace, fake_sync):
    """Reviewer case h4: the generated name is registered with another pin-out."""
    ds = extracted(workspace, "25AA02E48")
    # all variants: two pin-outs -> names with the package; "… SOIC-8" belongs to another symbol
    _registered_symbol("25AA02E48 SOIC-8", [("1", "A"), ("2", "B"), ("3", "C")])
    both = build_proposal(ds, None, ws=workspace, svg=False)
    names = {s.package: (s.name, s.taken_name, s.exists) for s in both.symbols}
    assert names["SN"] == ("25AA02E48 SOIC-8_2", "25AA02E48 SOIC-8", False)
    assert names["OT"] == ("25AA02E48 SOT-23-6", None, False) and both.ready

    # one variant: the base name "25AA02E48" is taken, "25AA02E48 SOIC-8" as well -> "25AA02E48_2"
    _registered_symbol("25AA02E48", [("1", "A"), ("2", "B")])
    proposal = build_proposal(ds, ProposalChoices(variants=["25AA02E48-I/SN"]), ws=workspace, svg=False)
    symbol = proposal.symbols[0]
    assert symbol.name == "25AA02E48_2" and symbol.taken_name == "25AA02E48" and not symbol.exists
    assert "bereits mit anderer Pinbelegung" in symbol.warnings[0] and proposal.ready
    assert proposal.variants[0].symbol == "25AA02E48_2" and symbol.pin_changes == []
    result = commit_proposal(None, ds, ProposalChoices(variants=["25AA02E48-I/SN"]), ws=workspace)
    assert result["symbols"] == ["25AA02E48_2"] and fake_sync["allow_pin_changes"] == [False]
    assert parts.get_part("Integrated Circuits", "25AA02E48-I/SN")["Library Ref"] == "25AA02E48_2"
    assert [p.name for p in registry.get_symbol("25AA02E48").spec.pins] == ["A", "B"]  # untouched

    # the user confirms the new pin-out for the registered name
    allowed = ProposalChoices(variants=["25AA02E48T-I/SN"], allow_pin_changes=True)
    proposal = build_proposal(ds, allowed, ws=workspace, svg=False)
    symbol = proposal.symbols[0]
    assert symbol.name == "25AA02E48" and symbol.exists and symbol.pin_changes
    assert any("Pins hinzugefügt" in c for c in symbol.pin_changes) and "neue Pinbelegung" in symbol.warnings[-1]
    result = commit_proposal(None, ds, allowed, ws=workspace)
    assert result["symbols"] == ["25AA02E48"] and fake_sync["allow_pin_changes"][-1] is True
    assert len(registry.get_symbol("25AA02E48").spec.pins) == 8

    # a name typed by the user is not changed: invalid until the pin-out change is confirmed
    _registered_symbol("MEIN SYMBOL", [("1", "A")])
    typed = ProposalChoices(variants=["25AA02E48T-I/OT"], symbol=SymbolChoice(mode="ic", name="MEIN SYMBOL"))
    proposal = build_proposal(ds, typed, ws=workspace, svg=False)
    assert not proposal.symbols[0].valid and not proposal.ready
    assert "anderen Namen" in proposal.symbols[0].warnings[-1]
    with pytest.raises(DatasheetError, match="anderer Pinbelegung"):
        commit_proposal(None, ds, typed, ws=workspace)


def test_a_registered_symbol_with_the_same_pinout_is_reused(workspace, fake_sync):
    ds = extracted(workspace, "25AA02E48")
    first = build_proposal(ds, ProposalChoices(variants=["25AA02E48-I/SN"]), ws=workspace, svg=False)
    spec = first.symbols[0].spec
    assert spec is not None
    registry.upsert_symbol(SymbolRecord(name=spec.name, library=r"Symbols\Alt.SchLib", spec=spec, status="ok"))
    again = build_proposal(ds, ProposalChoices(variants=["25AA02E48-I/SN"]), ws=workspace, svg=False)
    assert again.symbols[0].name == spec.name and again.symbols[0].exists and again.symbols[0].status == "ok"
    result = commit_proposal(None, ds, ProposalChoices(variants=["25AA02E48-I/SN"]), ws=workspace)
    assert result["symbols"] == [] and result["created"] == ["25AA02E48-I/SN"]
    # a registered entry whose last write failed is written again
    registry.upsert_symbol(SymbolRecord(name=spec.name, library=r"Symbols\Alt.SchLib", spec=spec, status="error"))
    retry = commit_proposal(None, ds, ProposalChoices(variants=["25AA02E48T-I/SN"]), ws=workspace)
    assert retry["symbols"] == [spec.name]


def test_internal_part_numbers_find_existing_parts_by_mpn(workspace, fake_sync):
    """Reviewer case h2: with internal part numbers a second commit must not duplicate the parts."""
    workspace.settings.part_number_scheme = "internal"
    ds = extracted(workspace, "opa656")
    choice = ProposalChoices(variants=["OPA656U"])
    first = commit_proposal(None, ds, choice, ws=workspace)
    assert len(first["created"]) == 1 and first["created"][0] != "OPA656U"
    pn = first["created"][0]
    proposal = build_proposal(ds, choice, ws=workspace, svg=False)
    item = proposal.variants[0]
    assert item.status == "exists" and item.part_number == pn and item.values["Part Number"] == pn
    again = commit_proposal(None, ds, choice, ws=workspace)
    assert again["created"] == [] and again["skipped"] == [pn]
    updated = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U"], mode="update",
                                                        values={"Notes": "geprüft"}), ws=workspace)
    assert updated["updated"] == [pn] and parts.get_part("Amplifiers", pn)["Notes"] == "geprüft"
    rows, _total = parts.query_parts("Amplifiers", limit=None)
    assert [r["Part Number"] for r in rows if r["Manufacturer Part Number"] == "OPA656U"] == [pn]


def test_mpn_lookup_across_categories_and_part_numbers(workspace, fake_sync):
    ds = extracted(workspace, "opa656")
    base = {"Manufacturer": "Anderer Hersteller", "Description": "x", "Library Ref": "X", "Footprint Ref": "Y"}
    parts.create_part("Amplifiers", {**base, "Part Number": "OPV-0001", "Manufacturer Part Number": "OPA656U"},
                      allow_incomplete=True)
    parts.create_part("Integrated Circuits", {**base, "Part Number": "IC-0001", "Function": "Sonstiges",
                                              "Manufacturer Part Number": "OPA656UB"}, allow_incomplete=True)
    proposal = build_proposal(ds, ProposalChoices(variants=["OPA656U", "OPA656UB"]), ws=workspace, svg=False)
    found = {v.mpn: v for v in proposal.variants}
    assert (found["OPA656U"].status, found["OPA656U"].part_number) == ("exists", "OPV-0001")
    assert any("Anderer Hersteller" in w for w in found["OPA656U"].warnings)
    assert (found["OPA656UB"].status, found["OPA656UB"].existing_table) == ("conflict", "Integrated Circuits")
    result = commit_proposal(None, ds, ProposalChoices(variants=["OPA656U"]), ws=workspace)
    assert result["skipped"] == ["OPV-0001"] and parts.get_part("Amplifiers", "OPA656U") is None


def test_writer_problems_make_symbols_and_footprints_invalid(workspace, fake_sync, monkeypatch):
    from partforge.altium import sync

    ds = extracted(workspace, "opa656")
    monkeypatch.setattr(sync, "validate_spec", lambda spec: [f"{spec.name}: Pin-Name enthält „|“."])
    proposal = build_proposal(ds, ProposalChoices(variants=["OPA656U"]), ws=workspace, svg=False)
    assert not proposal.ready
    assert not proposal.symbols[0].valid and "enthält „|“" in proposal.symbols[0].warnings[-1]
    assert not proposal.footprints[0].valid
    with pytest.raises(DatasheetError, match="enthält"):
        commit_proposal(None, ds, ProposalChoices(variants=["OPA656U"]), ws=workspace)
    assert fake_sync["symbols"] == [] and fake_sync["footprints"] == []


def test_registered_footprint_with_other_pads_is_what_gets_checked(workspace, fake_sync):
    ds = extracted(workspace, "opa656")
    choice = ProposalChoices(variants=["OPA656U"])
    name = build_proposal(ds, choice, ws=workspace, svg=False).footprints[0].name
    assert name
    stale = FootprintSpec(name=name, pads=[Pad(designator=str(i), x=i, y=0, width=0.5, height=1.5)
                                           for i in range(1, 7)])
    registry.upsert_footprint(FootprintRecord(name=name, library=r"Footprints\Alt.PcbLib", spec=stale, pad_count=6,
                                              status="ok"))
    proposal = build_proposal(ds, choice, ws=workspace, svg=False)
    footprint = proposal.footprints[0]
    assert footprint.exists and any("anderen Pads registriert" in w for w in footprint.warnings)
    assert any("Pins ohne Pad im Footprint: 7" in b for b in proposal.blockers) and not proposal.ready
    missing = next(t for t in proposal.blocker_targets if "Pins ohne Pad im Footprint: 7" in t.blocker)
    assert (missing.package, missing.pins, missing.pads) == ("D", ["7", "8"], [])  # IC symbol: pins 7, 8
    rewrite = build_proposal(ds, ProposalChoices(variants=["OPA656U"], overwrite_existing=True), ws=workspace,
                             svg=False)
    assert rewrite.blockers == [] and rewrite.ready


# --------------------------------------------------------------------------- confirmed blockers and the fingerprint


def test_blockers_are_confirmed_one_by_one(workspace, fake_sync):
    ds = _without_supply_pins(workspace)
    choice = ProposalChoices(variants=["25AA02E48-I/SN"])
    proposal = build_proposal(ds, choice, ws=workspace, svg=False)
    blockers = proposal.blockers
    assert len(blockers) == 2 and proposal.unconfirmed_blockers == blockers and not proposal.ready
    partly = build_proposal(ds, choice.model_copy(update={"accept_issues": blockers[:1]}), ws=workspace, svg=False)
    assert partly.unconfirmed_blockers == blockers[1:] and not partly.ready
    spaced = [f"  {b.replace(' ', '  ')} " for b in blockers]  # whitespace does not matter
    confirmed = build_proposal(ds, choice.model_copy(update={"accept_issues": spaced}), ws=workspace, svg=False)
    assert confirmed.unconfirmed_blockers == [] and confirmed.ready
    assert confirmed.fingerprint == proposal.fingerprint == partly.fingerprint  # confirming changes no plan
    with pytest.raises(CommitRefused) as info:
        commit_proposal(None, ds, choice.model_copy(update={"accept_issues": blockers[:1]}), ws=workspace)
    assert info.value.code == "unconfirmed_blockers" and info.value.items == blockers[1:]
    assert blockers[1] in str(info.value) and "bestätigen" in str(info.value) and "nichts geschrieben" in str(info.value)
    assert fake_sync["symbols"] == [] and fake_sync["footprints"] == []
    result = commit_proposal(None, ds, choice.model_copy(update={"accept_issues": blockers}), ws=workspace)
    assert result["created"] == ["25AA02E48-I/SN"] and result["message"].startswith("Angelegt: 1 Bauteil")


def test_a_refused_commit_names_the_blockers_in_its_job_detail(workspace, fake_sync):
    ds = _without_supply_pins(workspace)
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet-commit", "Anlegen", commit_proposal, ds,
                               ProposalChoices(variants=["25AA02E48-I/SN"], accept_issues=[]), ws=workspace)
    finally:
        manager.shutdown()
    assert job.status == "failed" and job.error_type == "CommitRefused" and job.message == job.error
    assert job.detail["code"] == "unconfirmed_blockers" and len(job.detail["unconfirmed_blockers"]) == 2
    assert job.detail["step"] == "check" and "fingerprint" in job.detail
    assert fake_sync["symbols"] == [] and parts.get_part("Integrated Circuits", "25AA02E48-I/SN") is None


def test_the_commit_refuses_a_plan_that_changed_since_the_review(workspace, fake_sync):
    ds = extracted(workspace, "opa656")
    choice = ProposalChoices(variants=["OPA656U", "OPA656N/250"])
    reviewed = build_proposal(ds, choice, ws=workspace)  # with previews, as the UI shows it
    assert len(reviewed.fingerprint) == 16
    assert build_proposal(ds, choice, ws=workspace, svg=False).fingerprint == reviewed.fingerprint
    reordered = ProposalChoices(variants=["OPA656N/250", "opa656u"])
    assert build_proposal(ds, reordered, ws=workspace, svg=False).fingerprint == reviewed.fingerprint
    for changed in (ProposalChoices(variants=["OPA656U"]), choice.model_copy(update={"mode": "update"}),
                    choice.model_copy(update={"values": {"Notes": "x"}}),
                    choice.model_copy(update={"packages": {"D": PackageChoice(footprint="manufacturer")}})):
        assert build_proposal(ds, changed, ws=workspace, svg=False).fingerprint != reviewed.fingerprint
    base = {"Manufacturer": "TI", "Description": "x", "Library Ref": "X", "Footprint Ref": "Y"}
    parts.create_part("Amplifiers", {**base, "Part Number": "OPA656U"}, allow_incomplete=True)  # meanwhile
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet-commit", "Anlegen", commit_proposal, ds,
                               choice.model_copy(update={"expected_fingerprint": reviewed.fingerprint}), ws=workspace)
    finally:
        manager.shutdown()
    assert job.status == "failed" and "geändert" in job.error and "nichts geschrieben" in job.error
    assert job.detail["code"] == "proposal_changed" and job.detail["expected_fingerprint"] == reviewed.fingerprint
    assert job.detail["fingerprint"] != reviewed.fingerprint
    assert fake_sync["symbols"] == [] and fake_sync["footprints"] == []
    assert parts.get_part("Amplifiers", "OPA656N/250") is None
    current = build_proposal(ds, choice, ws=workspace, svg=False)
    result = commit_proposal(None, ds, choice.model_copy(update={"expected_fingerprint": current.fingerprint}),
                             ws=workspace)
    assert result["created"] == ["OPA656N/250"] and result["skipped"] == ["OPA656U"]
    assert result["fingerprint"] == current.fingerprint


def test_pin_changes_per_symbol_and_the_usage_of_a_taken_name(workspace, fake_sync):
    ds = extracted(workspace, "25AA02E48")
    _registered_symbol("25AA02E48 SOIC-8", [("1", "A"), ("2", "B")])
    _registered_symbol("25AA02E48 SOT-23-6", [("1", "A")])
    base = {"Manufacturer": "X", "Description": "x", "Footprint Ref": "Y", "Function": "Sonstiges"}
    for pn in ("ALT-1", "ALT-2"):
        parts.create_part("Integrated Circuits", {**base, "Part Number": pn, "Library Ref": "25AA02E48 SOIC-8"},
                          allow_incomplete=True)
    renamed = build_proposal(ds, None, ws=workspace, svg=False)
    soic = next(s for s in renamed.symbols if s.package == "SN")
    sot = next(s for s in renamed.symbols if s.package == "OT")
    assert soic.taken_name == "25AA02E48 SOIC-8" and soic.usage == 2 and soic.pin_changes == []
    # structured differences per pin (no parsing of warning texts): pins 3 … 8 are new, 1 and 2 got other names
    added = [c.pin for c in soic.taken_changes if c.old_name is None]
    assert added == ["3", "4", "5", "6", "7", "8"] and all(c.new_name for c in soic.taken_changes)
    first = soic.taken_changes[0]
    assert (first.pin, first.old_name, first.new_name, first.old_type, first.new_type) == (
        "1", "A", "C\\S\\", "passive", "input")
    assert sot.taken_name == "25AA02E48 SOT-23-6" and sot.usage == 0 and sot.taken_changes
    choice = ProposalChoices(allow_pin_changes=["25aa02e48 soic-8"])  # only this one, case-insensitive
    proposal = build_proposal(ds, choice, ws=workspace, svg=False)
    soic = next(s for s in proposal.symbols if s.package == "SN")
    sot = next(s for s in proposal.symbols if s.package == "OT")
    assert soic.name == "25AA02E48 SOIC-8" and soic.taken_name is None and soic.usage == 2
    assert soic.pin_changes and soic.taken_changes and soic.taken_changes[0].pin == "1"
    assert soic.pin_changes[0] == "Pins hinzugefügt: 3, 4, 5, 6, 7, 8"
    assert "2 Bauteile verwenden es" in soic.warnings[-1]
    assert sot.name != "25AA02E48 SOT-23-6" and sot.taken_name == "25AA02E48 SOT-23-6" and sot.pin_changes == []
    result = commit_proposal(None, ds, choice, ws=workspace)
    assert fake_sync["allow_pin_changes"] == [False, True]  # one call per decision
    assert [names for names, *_ in fake_sync["symbols"]] == [[sot.name], ["25AA02E48 SOIC-8"]]
    assert sorted(result["symbols"]) == sorted([sot.name, "25AA02E48 SOIC-8"])
    assert len(registry.get_symbol("25AA02E48 SOIC-8").spec.pins) == 8
    assert [p.name for p in registry.get_symbol("25AA02E48 SOT-23-6").spec.pins] == ["A"]  # untouched
    reused = build_proposal(ds, None, ws=workspace, svg=False)  # same name, same pin-out now: reused
    soic = next(s for s in reused.symbols if s.package == "SN")
    soic_parts = sum(1 for v in reused.variants if v.symbol == soic.name)  # created by the commit
    assert soic.exists and soic.taken_changes == [] and soic.taken_name is None and soic.usage == 2 + soic_parts == 4


def test_pinout_differences_are_structured_per_pin_and_readable(workspace, fake_sync):
    """K3: ``taken_changes`` lists each differing pin {pin, old/new name, type, part} – names in Altium overbar syntax
    for the UI's pin-name renderer; the warning texts show real overlines, never the raw backslash syntax."""
    ds = extracted(workspace, "25AA02E48")
    choice = ProposalChoices(variants=["25AA02E48-I/SN"])
    generated = build_proposal(ds, choice, ws=workspace, svg=False).symbols[0].spec
    new_pins = {p.designator: p for p in generated.pins}
    assert new_pins["1"].name == "C\\S\\" and new_pins["7"].name == "H\\O\\L\\D\\"
    plain = {"1": "CS", "7": "HOLD"}
    old_pins = [p.model_copy(update={"name": plain.get(p.designator, p.name),
                                     "electrical": "io" if p.designator == "2" else p.electrical})
                for p in generated.pins if p.designator != "8"]
    old_pins.append(new_pins["5"].model_copy(update={"designator": "9", "name": "EXTRA"}))
    registry.upsert_symbol(SymbolRecord(name=generated.name, library=r"Symbols\Alt.SchLib", status="ok",
                                        spec=generated.model_copy(update={"pins": old_pins}), pin_count=len(old_pins)))
    symbol = build_proposal(ds, choice, ws=workspace, svg=False).symbols[0]
    assert symbol.taken_name == generated.name and symbol.name != generated.name
    changes = {c.pin: c for c in symbol.taken_changes}
    assert list(changes) == ["1", "2", "7", "8", "9"]  # natural order, only the pins that differ
    assert changes["1"].model_dump() == {"pin": "1", "old_name": "CS", "new_name": "C\\S\\",
                                         "old_type": new_pins["1"].electrical, "new_type": new_pins["1"].electrical,
                                         "old_part": 1, "new_part": 1}
    assert (changes["2"].old_name, changes["2"].new_name) == (new_pins["2"].name,) * 2  # type only
    assert (changes["2"].old_type, changes["2"].new_type) == ("io", new_pins["2"].electrical)
    assert changes["8"].old_name is None and changes["8"].new_name == new_pins["8"].name  # added
    assert changes["9"].new_name is None and changes["9"].old_name == "EXTRA"  # removed
    assert changes["9"].old_type == new_pins["5"].electrical and changes["9"].new_type is None
    warning = symbol.warnings[0]
    assert "bereits mit anderer Pinbelegung" in warning and "\\" not in warning
    assert "Pin 1: Name „CS“ → „C\u0305S\u0305“" in warning and "Pins entfernt: 9" in warning
    assert "Pins hinzugefügt: 8" in warning
    # the same structure when the user allows the new pin-out for the registered symbol
    allowed = build_proposal(ds, choice.model_copy(update={"allow_pin_changes": [generated.name]}), ws=workspace,
                             svg=False).symbols[0]
    assert allowed.name == generated.name and allowed.taken_changes == symbol.taken_changes
    assert allowed.pin_changes and not any("\\" in c for c in allowed.pin_changes)
    assert readable_pin_name("TCLK_R/F\\") == "TCLK_R/F\u0305" and readable_pin_name("VCC") == "VCC"


def test_a_registered_symbol_without_geometry_lists_the_new_pins(workspace, fake_sync):
    """K3: a registered symbol without geometry (external library): only its pin count is known."""
    ds = extracted(workspace, "25AA02E48")
    choice = ProposalChoices(variants=["25AA02E48-I/SN"])
    name = build_proposal(ds, choice, ws=workspace, svg=False).symbols[0].name
    registry.upsert_symbol(SymbolRecord(name=name, library=r"Symbols\Ext.SchLib", source="external", pin_count=6,
                                        status="ok"))
    symbol = build_proposal(ds, choice, ws=workspace, svg=False).symbols[0]
    assert symbol.taken_name == name and len(symbol.taken_changes) == 8
    assert all(c.old_name is None and c.old_type is None and c.new_name for c in symbol.taken_changes)
    assert "6 statt 8 Pins" in symbol.warnings[0]


def test_existing_parts_are_found_by_a_normalised_mpn(workspace, fake_sync):
    ds = extracted(workspace, "opa656")
    base = {"Manufacturer": "Texas Instruments", "Description": "x", "Library Ref": "X", "Footprint Ref": "Y"}
    parts.create_part("Amplifiers", {**base, "Part Number": "OPV-0002", "Manufacturer Part Number": "opa-656 u"},
                      allow_incomplete=True)
    item = build_proposal(ds, ProposalChoices(variants=["OPA656U"]), ws=workspace, svg=False).variants[0]
    assert item.status == "exists" and item.part_number == "OPV-0002" and item.warnings == []
