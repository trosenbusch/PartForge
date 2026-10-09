"""Datasheet import: the extraction pipeline, replayed offline from REAL recorded Claude responses
(tests/data/ai_fixtures, recorded 2026-10-08 with claude-opus-5-5 at effort low) plus synthetic edge cases."""
from __future__ import annotations

import base64
import copy
import io
import json
from pathlib import Path
from typing import Any

import pytest

from partforge.config import AppSettings
from partforge.datasheet import extract, llm, store
from partforge.datasheet.errors import AiUnavailable, BudgetExceeded, ExtractionFailed
from partforge.datasheet.extract import ExtractOptions, run_extraction, store_edited_extraction
from partforge.datasheet.llm import ReplayLlmClient
from partforge.datasheet.prompts import SYSTEM_PROMPT
from partforge.jobs import Job, JobCancelled, JobContext, JobManager
from partforge.workspace import Workspace

DATA = Path(__file__).parent / "data"
FIXTURES = DATA / "ai_fixtures"
PDFS = DATA / "corpus" / "pdfs"
STEMS = ["opa656", "LTC6244", "25AA02E48", "sn65lv1023a"]

pytestmark = pytest.mark.skipif(not FIXTURES.is_dir() or not PDFS.is_dir(), reason="Testdaten fehlen")


def fixture(stem: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{stem}.json").read_text(encoding="utf-8"))


def answer(call: dict[str, Any]) -> dict[str, Any]:
    return json.loads("".join(b.get("text", "") for b in call["message"]["content"] if b["type"] == "text"))


def with_answer(call: dict[str, Any], data: dict[str, Any] | str, *, kind: str | None = None,
                stop: str = "end_turn", **message: Any) -> dict[str, Any]:
    out = copy.deepcopy(call)
    text = data if isinstance(data, str) else json.dumps(data)
    out["message"]["content"] = [{"type": "text", "text": text}]
    out["message"]["stop_reason"] = stop
    out["message"].update(message)
    if kind:
        out["kind"] = kind
    return out


def ingest(workspace: Workspace, pdf: str):
    rec, _ = store.ingest_bytes((PDFS / pdf).read_bytes(), pdf, ws=workspace)
    return rec


def replay(workspace: Workspace, stem: str, calls: list[dict[str, Any]] | None = None,
           options: ExtractOptions | None = None, settings: AppSettings | None = None, ctx: JobContext | None = None):
    fx = fixture(stem)
    rec = ingest(workspace, fx["pdf"])
    client = ReplayLlmClient(calls if calls is not None else fx["calls"])
    opts = options or ExtractOptions.model_validate(fx["options"])
    result = run_extraction(ctx, rec.id, opts, ws=workspace, client=client, settings=settings or AppSettings())
    return rec, result, client


def _pdf_pages(request) -> int:
    from pypdf import PdfReader

    block = request.messages[0]["content"][0]
    return len(PdfReader(io.BytesIO(base64.standard_b64decode(block["source"]["data"]))).pages)


# --------------------------------------------------------------------------- recorded fixtures


@pytest.mark.parametrize("stem", STEMS)
def test_recorded_fixture_replays_with_the_same_page_selection(workspace, stem):
    fx = fixture(stem)
    assert "sk-ant" not in json.dumps(fx)
    _rec, result, client = replay(workspace, stem)
    assert client.remaining == []
    recorded = {c["kind"]: c["pages"] for c in fx["calls"]}
    assert result["identity_pages"] == recorded["identity"]
    assert result["geometry_pages"] == recorded["geometry"]
    assert result["issues"]["error"] == 0
    assert result["cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in fx["calls"]), abs=1e-4)


def test_opa656_pipeline_requests_and_stored_result(workspace):
    rec, result, client = replay(workspace, "opa656")
    assert result["devices"] == ["OPA656"] and result["mpns"] == 14 and result["pins"] == 13
    assert result["packages"] == ["SOIC-8 (D)", "SOT-23-5 (DBV)"]
    assert not result["vision"] and result["selection_method"] == "heuristic"
    identity_req, geometry_req = client.requests
    assert identity_req.kind == "identity" and identity_req.model == "claude-opus-5-5"
    assert identity_req.effort == "low" and identity_req.fallbacks and identity_req.max_tokens == 32_000
    assert identity_req.system == SYSTEM_PROMPT
    doc = identity_req.messages[0]["content"][0]
    assert doc["type"] == "document" and doc["cache_control"] == {"type": "ephemeral"}
    assert doc["source"]["media_type"] == "application/pdf"
    assert _pdf_pages(identity_req) == 4 and _pdf_pages(geometry_req) == 5
    assert "Category tables:" in identity_req.messages[0]["content"][1]["text"]
    assert "- Amplifiers (Verstärker):" in identity_req.messages[0]["content"][1]["text"]
    assert "- D: SOIC-8, 8 pins" in geometry_req.messages[0]["content"][1]["text"]
    assert "devices" in json.dumps(identity_req.schema) and "dimensions" in json.dumps(geometry_req.schema)

    stored = store.get_record(rec.id)
    assert stored.manufacturer == "Texas Instruments" and "OPA656U/2K5" in stored.mpns
    assert stored.title and stored.title.startswith("OPA656 – ")
    meta = store.load_meta(stored)
    assert meta.extraction is not None and meta.model == "claude-opus-5-5" and meta.effort == "low"
    assert meta.identity_pages == [1, 2, 17, 18] and meta.selected_pages == [1, 2, 17, 18, 21, 22, 23, 24]
    assert [r.kind for r in meta.runs] == ["identity", "geometry"]
    assert all(r.request_id and r.request_id.startswith("req_") for r in meta.runs)
    assert meta.cost_usd == pytest.approx(result["cost_usd"], abs=1e-6)
    assert set(meta.raw) == {"identity", "geometry"}
    soic = meta.extraction.package("D")
    assert soic is not None and soic.pages == [23] and soic.land_pattern.pages == [24]
    assert soic.land_pattern.row_spacing == 4.8 and soic.land_pattern.row_spacing_reference == "center_to_center"
    assert meta.extraction.package("DBV").pages == [21]


def test_vision_pass_appends_renders_to_the_geometry_conversation(workspace):
    _rec, result, client = replay(workspace, "sn65lv1023a")
    assert result["vision"] and result["devices"] == ["SN65LV1023A", "SN65LV1224B"] and result["pins"] == 120
    verify = client.requests[-1]
    assert verify.kind == "verify_geometry" and verify.model == "claude-opus-5-5"
    first, echoed, follow = verify.messages
    assert first == client.requests[1].messages[0]  # append-only history: the cached PDF prefix is unchanged
    assert echoed["role"] == "assistant" and echoed["content"][0]["type"] == "text"
    images = [b for b in follow["content"] if b["type"] == "image"]
    assert 1 <= len(images) <= extract.MAX_VISION_IMAGES
    assert follow["content"][-2]["cache_control"] == {"type": "ephemeral"}
    labels = [b["text"] for b in follow["content"] if b["type"] == "text"]
    assert labels[0].startswith("Render of attached-PDF page ")
    assert "Gehäusemaße fehlen" in labels[-1]  # the German issue texts are handed over
    assert verify.pages[0] == 29  # the affected DB family drawing first
    meta = store.load_meta(store.get_record(result["datasheet_id"]))
    db = meta.extraction.package("DB")
    assert db is not None and db.dim("D").min == 9.9 and db.dim("D").max == 10.5
    assert [r.kind for r in meta.runs] == ["identity", "geometry", "verify_geometry"]


def test_triage_uses_the_fast_model(workspace):
    _rec, result, client = replay(workspace, "25AA02E48")
    triage = client.requests[0]
    assert triage.kind == "triage" and triage.model == "claude-haiku-5-5" and triage.effort == "low"
    assert not triage.fallbacks and "[page 16]" in triage.messages[0]["content"]
    assert result["selection_method"] == "heuristic+triage"


def test_job_log_and_progress(workspace):
    fx = fixture("opa656")
    rec = ingest(workspace, fx["pdf"])
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id, ExtractOptions(), ws=workspace,
                               client=ReplayLlmClient(fx["calls"]), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    texts = [entry["text"] for entry in job.log]
    assert any(t.startswith("Seitenauswahl: 1, 2, 17, 18, 21–24") for t in texts)
    assert "Hersteller erkannt: Texas Instruments" in texts
    assert any(t.startswith("Ergebnis gespeichert. Kosten dieses Imports") for t in texts)
    assert job.result["datasheet_id"] == rec.id and job.progress == 1.0


# --------------------------------------------------------------------------- options, budget, AI settings


def test_budget_guard_stops_before_any_call(workspace):
    with pytest.raises(BudgetExceeded, match="Kostenlimit von 0.05 USD"):
        replay(workspace, "opa656", options=ExtractOptions(max_cost_usd=0.05))


def test_budget_guard_skips_the_vision_pass(workspace, monkeypatch):
    original = extract.Budget.max_tokens_for

    def guarded(self, model, *, input_tokens, wanted, minimum=2000, cache_write=True, what="Die Analyse"):
        if what == "Die Kontrolle mit Seitenbildern":
            raise BudgetExceeded("zu teuer")
        return original(self, model, input_tokens=input_tokens, wanted=wanted, minimum=minimum,
                        cache_write=cache_write, what=what)

    monkeypatch.setattr(extract.Budget, "max_tokens_for", guarded)
    _rec, result, client = replay(workspace, "sn65lv1023a")
    assert not result["vision"] and client.remaining == ["verify_geometry"]
    assert result["issues"]["warning"] >= 1  # DB body length still missing


def test_ai_disabled(workspace):
    settings = AppSettings()
    settings.ai.enabled = False
    with pytest.raises(AiUnavailable, match="ausgeschaltet"):
        replay(workspace, "opa656", settings=settings)


def test_model_effort_and_manual_pages(workspace):
    fx = fixture("opa656")
    opts = ExtractOptions(model="claude-sonnet-5-5", effort="medium", pages=[1, 2, 21, 24], vision="off")
    _rec, result, client = replay(workspace, "opa656", fx["calls"], options=opts)
    assert result["selection_method"] == "manual"
    assert result["identity_pages"] == result["geometry_pages"] == [1, 2, 21, 24]
    assert {r.model for r in client.requests} == {"claude-sonnet-5-5"}
    assert {r.effort for r in client.requests} == {"medium"}


def test_encrypted_pdfs_are_always_sent_unencrypted(workspace):
    from pypdf import PdfReader

    fx = fixture("25AA02E48")
    calls = [c for c in fx["calls"] if c["kind"] in ("identity", "geometry")]
    every_page = ExtractOptions(pages=list(range(1, 27)), max_pages=40, vision="off")
    _rec, result, client = replay(workspace, "25AA02E48", calls, options=every_page)
    assert result["identity_pages"] == list(range(1, 27))
    for request in client.requests:
        data = base64.standard_b64decode(request.messages[0]["content"][0]["source"]["data"])
        reader = PdfReader(io.BytesIO(data))
        assert not reader.is_encrypted and len(reader.pages) == 26


def test_forced_vision_runs_both_verification_turns(workspace):
    fx = fixture("opa656")
    calls = [*fx["calls"], with_answer(fx["calls"][0], answer(fx["calls"][0]), kind="verify_identity"),
             with_answer(fx["calls"][1], answer(fx["calls"][1]), kind="verify_geometry")]
    _rec, result, client = replay(workspace, "opa656", calls, options=ExtractOptions(vision="on"))
    assert result["vision"] and client.remaining == []
    assert [r.kind for r in client.requests] == ["identity", "geometry", "verify_identity", "verify_geometry"]
    assert client.requests[2].pages == [2]  # the pin table page of the identity pass


def test_vision_off_keeps_the_issues(workspace):
    _rec, result, client = replay(workspace, "sn65lv1023a", options=ExtractOptions(vision="off"))
    assert not result["vision"] and client.remaining == ["verify_geometry"]
    assert result["issues"]["warning"] >= 1


def test_a_worse_verification_is_discarded(workspace):
    fx = fixture("opa656")
    identity = answer(fx["calls"][0])
    broken = copy.deepcopy(identity)
    broken["devices"][0]["pin_tables"][0]["pins"] = broken["devices"][0]["pin_tables"][0]["pins"][:6]  # 6 of 8
    worse = copy.deepcopy(identity)
    worse["devices"][0]["pin_tables"][0]["pins"] = worse["devices"][0]["pin_tables"][0]["pins"][:3]
    worse["devices"][0]["pin_tables"][1]["pins"] = worse["devices"][0]["pin_tables"][1]["pins"][:2]
    calls = [with_answer(fx["calls"][0], broken), fx["calls"][1],
             with_answer(fx["calls"][0], worse, kind="verify_identity")]
    rec, result, client = replay(workspace, "opa656", calls)
    assert result["vision"] and client.remaining == []
    meta = store.load_meta(store.get_record(rec.id))
    assert len(meta.extraction.devices[0].pin_table("D").pins) == 6  # the first answer was kept
    assert len(meta.raw["identity"]["devices"][0]["pin_tables"][0]["pins"]) == 6
    assert [i.code for i in meta.extraction.issues if i.severity == "error"] == ["pin_count"]


def test_an_unusable_verification_keeps_the_first_answer(workspace):
    fx = fixture("opa656")
    identity = answer(fx["calls"][0])
    identity["devices"][0]["pin_tables"][0]["pins"] = identity["devices"][0]["pin_tables"][0]["pins"][:7]
    calls = [with_answer(fx["calls"][0], identity), fx["calls"][1],
             with_answer(fx["calls"][0], "{kaputt", kind="verify_identity")]
    _rec, result, _client = replay(workspace, "opa656", calls)
    assert result["vision"] and result["issues"]["error"] == 1


# --------------------------------------------------------------------------- failures


def test_refusal_is_reported(workspace):
    fx = fixture("opa656")
    refused = with_answer(fx["calls"][0], "", stop="refusal", stop_details={"type": "refusal", "category": "cyber",
                                                                              "explanation": None})
    with pytest.raises(ExtractionFailed, match="abgelehnt.*cyber"):
        replay(workspace, "opa656", [refused, fx["calls"][1]])


def test_truncated_answer_is_retried_once_with_more_tokens(workspace):
    fx = fixture("opa656")
    truncated = with_answer(fx["calls"][0], '{"manufacturer": "Tex', stop="max_tokens")
    _rec, result, client = replay(workspace, "opa656", [truncated, *fx["calls"]])
    assert [r.kind for r in client.requests] == ["identity", "identity", "geometry"]
    assert client.requests[1].max_tokens == extract.MAX_TOKENS_RETRY
    assert result["pins"] == 13
    with pytest.raises(ExtractionFailed, match="abgeschnitten"):
        replay(workspace, "opa656", [truncated, truncated, fx["calls"][1]])


def test_invalid_json_and_incomplete_stops(workspace):
    fx = fixture("opa656")
    with pytest.raises(ExtractionFailed, match="passt nicht zum erwarteten Format"):
        replay(workspace, "opa656", [with_answer(fx["calls"][0], '{"manufacturer": 5}'), fx["calls"][1]])
    with pytest.raises(ExtractionFailed, match="unvollständig"):
        replay(workspace, "opa656", [with_answer(fx["calls"][0], "{}", stop="pause_turn"), fx["calls"][1]])


def test_cancellation_before_the_first_call(workspace):
    """A cancelled job stops before any paid call (the library switch is tested in test_datasheet_guard.py)."""
    fx = fixture("opa656")
    rec = ingest(workspace, fx["pdf"])
    ctx = JobContext(JobManager(max_workers=1), Job(id="x", kind="datasheet", title="t"))
    ctx.job.cancel_requested = True
    client = ReplayLlmClient(fx["calls"])
    with pytest.raises(JobCancelled):
        run_extraction(ctx, rec.id, ws=workspace, client=client, settings=AppSettings())
    assert client.requests == []
    assert store.load_meta(store.get_record(rec.id)).last_error == "Analyse abgebrochen."


def test_store_edited_extraction(workspace):
    rec, _result, _client = replay(workspace, "opa656")
    data = store.load_meta(store.get_record(rec.id)).extraction
    assert data is not None
    table = data.devices[0].pin_table("D")
    table.pins[1].name = "IN-"
    table.pins = table.pins[:7]
    saved = store_edited_extraction(rec.id, data)
    assert any(i.code == "pin_count" for i in saved.issues)
    meta = store.load_meta(store.get_record(rec.id))
    assert meta.edited and meta.extraction.devices[0].pin_table("D").pins[1].name == "IN-"
    assert len(meta.raw["identity"]["devices"][0]["pin_tables"][0]["pins"]) == 8  # Claude's answer is kept


def test_edited_extraction_gets_the_text_hygiene(workspace):
    """Reviewer case h11: '|' and control characters of user edits never reach a symbol."""
    from partforge.datasheet.models import ProposalChoices, SymbolChoice
    from partforge.datasheet.proposal import build_proposal

    rec, _result, _client = replay(workspace, "25AA02E48")
    data = store.load_meta(store.get_record(rec.id)).extraction
    table = data.devices[0].pin_table("SN")
    table.pins[1].name = "SO|DATA=1\x07"
    table.pins[1].function = "Serial out |X=Y"
    data.devices[0].description = "EEPROM | evil\r\nline"
    saved = store_edited_extraction(rec.id, data)
    assert saved.devices[0].pin_table("SN").pins[1].name == "SO/DATA=1"
    proposal = build_proposal(rec.id, ProposalChoices(variants=["25AA02E48-I/SN"], symbol=SymbolChoice(mode="ic")),
                              ws=workspace, svg=False)
    pin = next(p for p in proposal.symbols[0].spec.pins if p.designator == "2")
    assert pin.name == "SO/DATA=1" and "|" not in (pin.description or "")
    assert proposal.symbols[0].spec.description == "EEPROM / evil line" and proposal.symbols[0].valid


# --------------------------------------------------------------------------- review regressions


def test_a_verification_that_drops_data_cannot_lose_it(workspace):
    """Reviewer case h10: the corrected answer leaves out a device and most variants."""
    fx = fixture("LTC6244")
    ident = answer(fx["calls"][0])
    broken = copy.deepcopy(ident)
    hv = broken["devices"][1]
    hv["pin_tables"][0]["pins"] = hv["pin_tables"][0]["pins"][:7]  # one pin missing in an LTC6244HV table
    lossy = copy.deepcopy(ident)
    lossy["devices"] = lossy["devices"][:1]
    lossy["devices"][0]["variants"] = lossy["devices"][0]["variants"][:2]
    calls = [with_answer(fx["calls"][0], broken), fx["calls"][1],
             with_answer(fx["calls"][0], lossy, kind="verify_identity")]
    rec, result, client = replay(workspace, "LTC6244", calls)
    assert client.remaining == [] and result["vision"]
    assert result["devices"] == ["LTC6244", "LTC6244HV"] and result["mpns"] == 22
    meta = store.load_meta(store.get_record(rec.id))
    assert len(meta.extraction.mpns()) == 22 and [r.kind for r in meta.runs][-1] == "verify_identity"


def test_a_verification_replaces_only_the_items_it_improves(workspace):
    fx = fixture("opa656")
    ident = answer(fx["calls"][0])
    broken = copy.deepcopy(ident)
    broken["devices"][0]["pin_tables"][0]["pins"] = broken["devices"][0]["pin_tables"][0]["pins"][:6]  # SOIC 6 of 8
    corrected = copy.deepcopy(ident)  # SOIC table complete again, but the SOT-23 table lost pins
    corrected["devices"][0]["pin_tables"][1]["pins"] = corrected["devices"][0]["pin_tables"][1]["pins"][:2]
    corrected["devices"][0]["variants"] = corrected["devices"][0]["variants"][:1]
    calls = [with_answer(fx["calls"][0], broken), fx["calls"][1],
             with_answer(fx["calls"][0], corrected, kind="verify_identity")]
    rec, result, _client = replay(workspace, "opa656", calls)
    assert result["issues"]["error"] == 0 and result["mpns"] == 14
    data = store.load_meta(store.get_record(rec.id)).extraction
    assert len(data.devices[0].pin_table("D").pins) == 8 and len(data.devices[0].pin_table("DBV").pins) == 5


def test_costs_and_reason_of_a_failed_analysis_are_kept(workspace):
    """Reviewer case h5: a refusal in the geometry pass after a paid identity pass."""
    fx = fixture("opa656")
    refused = with_answer(fx["calls"][1], "", stop="refusal",
                          stop_details={"type": "refusal", "category": "cyber", "explanation": None})
    rec = ingest(workspace, fx["pdf"])
    with pytest.raises(ExtractionFailed, match="abgelehnt"):
        run_extraction(None, rec.id, ExtractOptions(vision="off"), ws=workspace,
                       client=ReplayLlmClient([fx["calls"][0], refused]), settings=AppSettings())
    meta = store.load_meta(store.get_record(rec.id))
    assert [r.kind for r in meta.runs] == ["identity", "geometry"] and meta.extraction is None
    assert meta.runs[0].error is None and "abgelehnt" in (meta.runs[1].error or "")
    assert meta.cost_usd == pytest.approx(fx["calls"][0]["cost_usd"] + meta.runs[1].cost_usd, abs=1e-6)
    assert meta.cost_usd > fx["calls"][0]["cost_usd"] and "abgelehnt" in (meta.last_error or "")
    # unusable JSON is recorded on its run, too
    with pytest.raises(ExtractionFailed, match="passt nicht"):
        run_extraction(None, rec.id, ExtractOptions(vision="off"), ws=workspace,
                       client=ReplayLlmClient([with_answer(fx["calls"][0], "{kaputt")]), settings=AppSettings())
    meta = store.load_meta(store.get_record(rec.id))
    assert len(meta.runs) == 3 and "passt nicht" in (meta.runs[2].error or "")
    # a successful analysis adds its costs and clears the reason
    result = run_extraction(None, rec.id, ExtractOptions(vision="off"), ws=workspace,
                            client=ReplayLlmClient(fx["calls"]), settings=AppSettings())
    meta = store.load_meta(store.get_record(rec.id))
    assert meta.last_error is None and len(meta.runs) == 5 and meta.extraction is not None
    assert meta.cost_usd == pytest.approx(sum(r.cost_usd for r in meta.runs), abs=1e-6)
    assert meta.cost_usd > result["cost_usd"]


def test_costs_are_kept_when_the_analysis_is_cancelled(workspace):
    fx = fixture("opa656")
    rec = ingest(workspace, fx["pdf"])

    class CancelInGeometry(ReplayLlmClient):
        def run(self, request, **kwargs):
            if request.kind == "geometry":
                raise JobCancelled()
            return super().run(request, **kwargs)

    with pytest.raises(JobCancelled):
        run_extraction(None, rec.id, ExtractOptions(vision="off"), ws=workspace,
                       client=CancelInGeometry(fx["calls"]), settings=AppSettings())
    meta = store.load_meta(store.get_record(rec.id))
    assert [r.kind for r in meta.runs] == ["identity"] and meta.last_error == "Analyse abgebrochen."
    assert meta.cost_usd == pytest.approx(fx["calls"][0]["cost_usd"], abs=1e-6)


def test_the_request_running_at_the_cancellation_is_paid_as_well(workspace):
    """The request that streams when the analysis is cancelled is recorded with its estimated cost (K15: the same rule
    as for the datasheet search)."""
    fx = fixture("opa656")
    rec = ingest(workspace, fx["pdf"])

    class CancelWhileGeometryStreams(ReplayLlmClient):
        def run(self, request, *, cancelled=None, on_text=None, **kwargs):
            if request.kind != "geometry":
                return super().run(request, cancelled=cancelled, on_text=on_text, **kwargs)
            seen: list[str] = []
            return super().run(request, cancelled=lambda: len(seen) >= 2, on_text=seen.append, **kwargs)

    with pytest.raises(JobCancelled):
        run_extraction(None, rec.id, ExtractOptions(vision="off"), ws=workspace,
                       client=CancelWhileGeometryStreams(fx["calls"], chunk=200), settings=AppSettings())
    meta = store.load_meta(store.get_record(rec.id))
    assert [r.kind for r in meta.runs] == ["identity", "geometry"] and meta.last_error == "Analyse abgebrochen."
    partial = meta.runs[1]
    assert partial.error == llm.CANCELLED_RUN_ERROR and partial.usage.input_tokens > 0
    assert 0 < partial.cost_usd < fx["calls"][1]["cost_usd"]  # the input and 400 streamed characters
    assert meta.cost_usd == pytest.approx(fx["calls"][0]["cost_usd"] + partial.cost_usd, abs=1e-6)


def test_a_failing_verification_keeps_the_result(workspace):
    """Reviewer case h6: a network error in the optional verification turn."""
    fx = fixture("sn65lv1023a")

    class FlakyVerification(ReplayLlmClient):
        def run(self, request, **kwargs):
            if request.kind.startswith("verify"):
                raise AiUnavailable("Keine Verbindung zur Claude-API – bitte die Internetverbindung prüfen.")
            return super().run(request, **kwargs)

    rec = ingest(workspace, fx["pdf"])
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id, ExtractOptions(), ws=workspace,
                               client=FlakyVerification(fx["calls"]), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    assert not job.result["vision"] and job.result["devices"] == ["SN65LV1023A", "SN65LV1224B"]
    assert any("Kontrolle mit Seitenbildern nicht möglich" in e["text"] for e in job.log)
    meta = store.load_meta(store.get_record(rec.id))
    assert meta.extraction is not None and [r.kind for r in meta.runs] == ["identity", "geometry"]


def test_enum_answers_in_another_casing_are_accepted(workspace):
    """Reviewer case h12: one differently cased enum value must not reject a paid answer."""
    fx = fixture("opa656")
    ident, geo = answer(fx["calls"][0]), answer(fx["calls"][1])
    ident["devices"][0]["pin_tables"][0]["pins"][1]["electrical_type"] = "input"
    geo["packages"][0]["mounting"] = "smd"
    geo["packages"][0]["land_pattern"]["row_spacing_reference"] = "Center_to_center"
    geo["packages"][0]["dimensions"][0]["unit"] = "MM"
    _rec, result, _client = replay(workspace, "opa656", [with_answer(fx["calls"][0], ident),
                                                         with_answer(fx["calls"][1], geo)],
                                   options=ExtractOptions(vision="off"))
    meta = store.load_meta(store.get_record(result["datasheet_id"]))
    soic = meta.extraction.package("D")
    assert soic.mounting == "SMD" and soic.land_pattern.row_spacing_reference == "center_to_center"
    assert meta.extraction.devices[0].pin_table("D").pins[1].electrical == "input"


def test_parse_errors_are_german(workspace):
    fx = fixture("opa656")
    with pytest.raises(ExtractionFailed, match=r"\(manufacturer: Text erwartet und 6 weitere Abweichung\(en\)\)"):
        replay(workspace, "opa656", [with_answer(fx["calls"][0], '{"manufacturer": 5}'), fx["calls"][1]])
    with pytest.raises(ExtractionFailed, match="JSON unvollständig"):
        replay(workspace, "opa656", [with_answer(fx["calls"][0], '{"manufacturer": "TI"'), fx["calls"][1]])


def test_effort_only_for_models_that_accept_it_and_model_validation(workspace):
    """Reviewer case h7."""
    fx = fixture("opa656")
    _rec, result, client = replay(workspace, "opa656", fx["calls"],
                                  options=ExtractOptions(model="claude-haiku-4-5", vision="off"))
    assert {r.effort for r in client.requests} == {None} and result["effort"] == ""
    assert "output_config" not in client.requests[0].params() or \
        "effort" not in client.requests[0].params()["output_config"]
    assert ExtractOptions(model="   ").model is None and ExtractOptions(model=" claude-opus-5-5 ").model == \
        "claude-opus-5-5"
    _rec, _result, blank = replay(workspace, "opa656", fx["calls"], options=ExtractOptions(model=" ", vision="off"))
    assert {r.model for r in blank.requests} == {"claude-opus-5-5"}
    with pytest.raises(ValueError, match="Modellbezeichnung"):
        ExtractOptions(model="claude opus; rm -rf")
    with pytest.raises(ValueError, match="beginnen bei 1"):
        ExtractOptions(pages=[0, 1])


def test_user_pages_are_not_cut_to_the_heuristic_limit(workspace):
    """Reviewer case h14: 20 pages chosen by the user are sent completely (the limit is 40)."""
    fx = fixture("opa656")
    rec = ingest(workspace, fx["pdf"])
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id,
                               ExtractOptions(pages=[*range(1, 21), 99], vision="off"), ws=workspace,
                               client=ReplayLlmClient(fx["calls"]), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    assert job.result["pages"] == list(range(1, 21)) and job.result["identity_pages"] == list(range(1, 21))
    assert any("Seiten 99 nicht übernommen" in e["text"] for e in job.log)


def test_mid_stream_fallback_through_the_pipeline(workspace):
    """Reviewer case h1: the fallback model continues the partial answer."""
    fx = fixture("opa656")
    text = json.dumps(answer(fx["calls"][0]))
    call = copy.deepcopy(fx["calls"][0])
    call["message"]["content"] = [
        {"type": "text", "text": text[:1200]},
        {"type": "fallback", "from": {"model": "claude-opus-5-5"}, "to": {"model": "claude-opus-4-8"},
         "trigger": {"type": "refusal", "category": "cyber"}},
        {"type": "text", "text": text[1200:]}]
    call["message"]["model"] = "claude-opus-4-8"
    rec = ingest(workspace, fx["pdf"])
    manager = JobManager(max_workers=1)
    try:
        job = manager.run_sync("datasheet", "Analyse", run_extraction, rec.id, ExtractOptions(vision="off"),
                               ws=workspace, client=ReplayLlmClient([call, fx["calls"][1]]), settings=AppSettings())
    finally:
        manager.shutdown()
    assert job.status == "done", job.error
    assert job.result["mpns"] == 14 and job.result["pins"] == 13
    assert any("Server-Fallback auf Claude Opus 4.8" in e["text"] for e in job.log)  # friendly model name
    meta = store.load_meta(store.get_record(rec.id))
    assert meta.runs[0].fallback and meta.runs[0].served_model == "claude-opus-4-8" and meta.runs[0].error is None
