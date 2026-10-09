"""API: /api/series/* (templates, user templates, test, preview, commit job, decode)."""
from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from partforge.altium import sync
from partforge.db import parts, registry
from partforge.db.models import FootprintRecord, SymbolRecord


def wait_for_job(client: TestClient, job_id: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError("Job wurde nicht fertig")


def custom_template(template_id: str = "haus-r", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": template_id, "manufacturer": "Hausmarke", "series": "HR", "category": "Resistors",
        "title": "Hauswiderstände", "pattern": "HR{size}-{value}{tolerance}",
        "variables": [
            {"name": "size", "label": "Baugröße", "options": [{"code": "0603", "value": "0603"}]},
            {"name": "value", "label": "Wert", "format": {"style": "rkm"}},
            {"name": "tolerance", "label": "Toleranz", "options": [{"code": "F", "value": "±1%", "default": True},
                                                                   {"code": "J", "value": "±5%"}]},
        ],
        "sizes": [{"size": "0603", "attrs": {"power": "0.1W"}}],
        "rules": [{"when": {"tolerance": ["F"]}, "ranges": [["10", "1M"]], "series": ["E24", "E96"]}],
        "fields": {"Resistance": "{value}", "Tolerance": "{tolerance}", "Power": "{power}"},
    }
    data.update(overrides)
    return data


@pytest.fixture
def fake_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    def ensure_symbols(specs, *, category=None, source="generated", ctx=None):
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF_Passives.SchLib", spec=s,
                                                     status="ok") for s in specs])

    def ensure_footprints(specs, *, source="generated", ctx=None):
        return registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF_CHIP.PcbLib", spec=s,
                                                           status="ok") for s in specs])

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)


def test_template_list_and_detail(client: TestClient) -> None:
    listing = client.get("/api/series/templates")
    assert listing.status_code == 200
    ids = {t["id"] for t in listing.json()}
    assert {"vishay-crcw-e3", "kemet-c-x7r", "bourns-srr1260"} <= ids and len(ids) == 14
    caps = client.get("/api/series/templates", params={"category": "Capacitors"}).json()
    assert {t["category"] for t in caps} == {"Capacitors"} and len(caps) == 4
    kemet = client.get("/api/series/templates/kemet-c-x7r").json()
    assert kemet["availability_count"] == 3342 and kemet["availability"] == []  # matrix only with full=true
    full = client.get("/api/series/templates/kemet-c-x7r", params={"full": True}).json()
    assert len(full["availability"]) == 3342
    vishay = client.get("/api/series/templates/vishay-crcw-e3").json()
    assert vishay["pattern"] == "CRCW{size}{value}{tolerance}{tcr}{packaging}" and vishay["verified"]
    missing = client.get("/api/series/templates/gibt-es-nicht")
    assert missing.status_code == 404 and "nicht gefunden" in missing.json()["detail"]


def test_preview_endpoint(client: TestClient) -> None:
    body = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "tolerance": "1%", "e_series": "E24",
            "range_min": "1", "range_max": "10M", "include_jumper": True}
    r = client.post("/api/series/preview", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["counts"]["new"] == 170 and data["symbol"]["name"] == "Resistor"
    assert data["rows"][0]["values"]["Description"].startswith("RES 0603")
    assert data["footprints_needed"][0]["name"] == "RESC1608X50N"
    bad = client.post("/api/series/preview", json={**body, "tolerance": "3%"})
    assert bad.status_code == 400 and "Toleranz" in bad.json()["detail"]
    unknown = client.post("/api/series/preview", json={**body, "template_id": "nope"})
    assert unknown.status_code == 404
    invalid = client.post("/api/series/preview", json={**body, "footprint_height": "riesig"})
    assert invalid.status_code == 422


def test_commit_job(client: TestClient, fake_sync: None) -> None:
    body = {"template_id": "vishay-crcw-e3", "sizes": ["0603"], "tolerance": "1%", "values": ["10k", "4.7k"],
            "mode": "skip"}
    r = client.post("/api/series/commit", json=body)
    assert r.status_code == 200, r.text
    job = wait_for_job(client, r.json()["job"]["id"])
    assert job["status"] == "done", job
    assert job["result"]["created"] == 2 and job["kind"] == "series"
    assert parts.get_part("Resistors", "CRCW060310K0FKEA") is not None
    again = wait_for_job(client, client.post("/api/series/commit", json=body).json()["job"]["id"])
    assert again["result"]["skipped"] == 2
    assert client.post("/api/series/commit", json={**body, "template_id": "nope"}).status_code == 404
    bad = client.post("/api/series/commit", json={**body, "tolerance": "3%"})
    assert bad.status_code == 400 and "Toleranz" in bad.json()["detail"]  # validated before the job starts
    assert client.post("/api/series/commit", json={**body, "mode": "merge"}).status_code == 422


def test_decode_endpoint(client: TestClient) -> None:
    r = client.post("/api/series/decode", json={"mpn": "CRCW0603562RFKEA"})
    assert r.status_code == 200
    data = r.json()
    assert data["best"]["template_id"] == "vishay-crcw-e3" and data["best"]["valid"]
    assert data["best"]["fields"]["Resistance"] == "562Ω"
    one = client.post("/api/series/decode", json={"mpn": "C0805C106J8RACTU", "template_id": "kemet-c-x7r"}).json()
    assert len(one["matches"]) == 1 and not one["best"]["valid"] and one["best"]["messages"]
    none = client.post("/api/series/decode", json={"mpn": "XYZ-123"}).json()
    assert none["best"] is None and none["matches"] == []
    assert client.post("/api/series/decode", json={"mpn": ""}).status_code == 422


def test_custom_template_crud(client: TestClient) -> None:
    created = client.post("/api/series/templates/custom", json=custom_template())
    assert created.status_code == 200, created.text
    assert created.json()["builtin"] is False
    assert client.post("/api/series/templates/custom", json=custom_template()).status_code == 409
    assert client.post("/api/series/templates/custom", json=custom_template("vishay-crcw-e3")).status_code == 409
    listing = client.get("/api/series/templates/custom").json()
    assert [t["id"] for t in listing] == ["haus-r"]
    assert "haus-r" in {t["id"] for t in client.get("/api/series/templates").json()}
    updated = client.put("/api/series/templates/custom/haus-r", json=custom_template(title="Neu"))
    assert updated.status_code == 200 and updated.json()["title"] == "Neu"
    assert client.get("/api/series/templates/haus-r").json()["title"] == "Neu"
    assert client.put("/api/series/templates/custom/vishay-crcw-e3",
                      json=custom_template("vishay-crcw-e3")).status_code == 400
    assert client.put("/api/series/templates/custom/unbekannt", json=custom_template("unbekannt")).status_code == 404
    assert client.put("/api/series/templates/custom/haus-r", json=custom_template("anders")).status_code == 400
    preview = client.post("/api/series/preview", json={"template_id": "haus-r", "values": ["4.7k", "1"]}).json()
    assert [r["mpn"] for r in preview["rows"]] == ["HR0603-4K7F", "HR0603-1RF"]
    assert [r["status"] for r in preview["rows"]] == ["new", "invalid"]
    assert client.delete("/api/series/templates/custom/haus-r").json() == {"deleted": True}
    assert client.delete("/api/series/templates/custom/haus-r").status_code == 404
    broken = client.post("/api/series/templates/custom", json=custom_template(pattern="HR{size}{unbekannt}"))
    assert broken.status_code == 422 and "ohne Definition" in broken.text


def test_template_test_endpoint(client: TestClient) -> None:
    body = {
        "template": custom_template(),
        "samples": [{"size": "0603", "value": "4k7"}, {"size": "0603", "value": "10k", "codes": {"tolerance": "5%"}},
                    {"size": "0603", "value": "1", "codes": {"tolerance": "F"}},
                    {"size": "0603", "value": "1k", "codes": {"tolerance": "Q"}}],
        "mpns": ["HR0603-10KF", "XX"],
    }
    r = client.post("/api/series/templates/test", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    first, second, third, fourth = data["samples"]
    assert first["mpn"] == "HR0603-4K7F" and first["valid"] and first["roundtrip"]
    assert second["mpn"] == "HR0603-10KJ" and not second["valid"] and second["roundtrip"]  # no rule for J
    assert third["mpn"] == "HR0603-1RF" and not third["valid"]  # below 10 Ω
    assert fourth["mpn"] is None and "Q" in fourth["messages"][0]
    assert data["decoded"][0]["value"] == 10000 and data["decoded"][1] is None
    assert data["regex"].startswith("^HR")


def test_without_library(bare_client: TestClient) -> None:
    assert len(bare_client.get("/api/series/templates").json()) == 14
    assert bare_client.post("/api/series/decode", json={"mpn": "RC0603FR-0710KL"}).json()["best"]["valid"]
    r = bare_client.post("/api/series/preview", json={"template_id": "vishay-crcw-e3", "values": ["10k"]})
    assert r.status_code == 409
    assert bare_client.get("/api/series/templates/custom").status_code == 409


def with_letters(letters: dict[str, int], template_id: str = "haus-letters") -> dict[str, Any]:
    data = custom_template(template_id)
    data["variables"][1]["format"] = {"style": "rkm", "letters": letters}
    return data


@pytest.mark.parametrize("letters", [{}, {"KK": 3}, {"7": 3}, {"R": 0, "K": 0}])
def test_malformed_value_formats_are_refused(client: TestClient, letters: dict[str, int]) -> None:
    """Regression: letters {} was stored, letters {"KK": 3} gave HTTP 500 in the template test."""
    created = client.post("/api/series/templates/custom", json=with_letters(letters))
    assert created.status_code == 422 and "Werteformat" in created.text
    tested = client.post("/api/series/templates/test", json={"template": with_letters(letters),
                                                            "samples": [{"size": "0603", "value": "4k7"}]})
    assert tested.status_code == 422
    assert client.get("/api/series/templates/custom").json() == []


def test_template_test_with_unreadable_part_numbers(client: TestClient) -> None:
    body = {"template": custom_template(), "samples": [{"size": "0603", "value": "4k7"}],
            "mpns": ["HR0603-4K7F", "HR0603-1234KF", "HR0603-4K70F", "XX"]}
    r = client.post("/api/series/templates/test", json=body)
    assert r.status_code == 200, r.text
    first, unwritable, spelling, foreign = r.json()["decoded"]
    assert first["valid"] and foreign is None
    assert not unwritable["valid"] and "Schreibweise" in unwritable["messages"][0]
    assert not spelling["valid"] and spelling["mpn"] == "HR0603-4K7F"


def test_decode_reports_other_spellings(client: TestClient) -> None:
    r = client.post("/api/series/decode", json={"mpn": "CRCW0603K100FKEA"})
    best = r.json()["best"]
    assert r.status_code == 200 and not best["valid"] and best["mpn"] == "CRCW0603100RFKEA"
    one = client.post("/api/series/decode", json={"mpn": "RC0603FR-071234KL", "template_id": "yageo-rc-l"})
    assert one.status_code == 200 and not one.json()["best"]["valid"]


def test_template_ids_and_category_filter(client: TestClient) -> None:
    assert client.post("/api/series/templates/custom", json=custom_template("Vishay-CRCW-E3")).status_code == 409
    reserved = client.post("/api/series/templates/custom", json=custom_template("custom"))
    assert reserved.status_code == 400 and "reserviert" in reserved.json()["detail"]
    assert client.post("/api/series/templates/custom", json=custom_template("haus-r")).status_code == 200
    assert client.post("/api/series/templates/custom", json=custom_template("HAUS-R")).status_code == 409
    listed = client.get("/api/series/templates/custom", params={"category": "resistors"}).json()
    assert [t["id"] for t in listed] == ["haus-r"]


def test_engine_failures_are_400_not_500(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from partforge.api import routes_series

    def broken(_mpn: str) -> Any:
        raise IndexError("list index out of range")

    monkeypatch.setattr(routes_series, "decode_any", broken)
    r = client.post("/api/series/decode", json={"mpn": "X-1"})
    assert r.status_code == 400 and "Vorlage ist fehlerhaft" in r.json()["detail"]


def test_commit_job_is_bound_to_the_open_library(client: TestClient, workspace, monkeypatch: pytest.MonkeyPatch
                                                 ) -> None:
    from partforge.api import routes_series

    seen: dict[str, Any] = {}

    class FakeJob:
        def snapshot(self) -> dict[str, Any]:
            from partforge.jobs import Job

            return Job(id="x", kind="series", title="Serie").snapshot()  # the typed response needs a full snapshot

    def submit(kind: str, title: str, fn: Any, *args: Any, **kwargs: Any) -> FakeJob:
        seen.update(kind=kind, args=args, kwargs=kwargs)
        return FakeJob()

    monkeypatch.setattr(routes_series.jobs, "submit", submit)
    r = client.post("/api/series/commit", json={"template_id": "vishay-crcw-e3", "sizes": ["0603"],
                                                "values": ["10k"], "mode": "update"})
    assert r.status_code == 200 and r.json()["job"]["id"] == "x"
    assert seen["kind"] == "series" and seen["args"][1] == "update"
    assert seen["kwargs"]["library"] == workspace.root


# --------------------------------------------------------------------------- template cards, test, preview details


def test_template_list_carries_examples_and_facts(client: TestClient) -> None:
    """Template cards need no extra requests: example part number with segments, facts and sources."""
    from partforge.domain.mpn import compact

    listing = {t["id"]: t for t in client.get("/api/series/templates").json()}
    assert len(listing) == 14
    for template_id, t in listing.items():
        example = t["example"]
        assert example is not None and example["valid"], (template_id, example)
        assert compact("".join(s["text"] for s in example["segments"])) == compact(example["mpn"]), template_id
        assert example["description"] and not example["missing_fields"], template_id
        assert t["sources"] and t["mode"] in ("rules", "matrix", "catalog")
    vishay = listing["vishay-crcw-e3"]
    ex = vishay["example"]
    assert ex["mpn"] == "CRCW060310K0FKEA" and ex["size"] == "0603" and ex["value"] == 10000.0
    assert [s["text"] for s in ex["segments"]] == ["CRCW", "0603", "10K0", "F", "K", "EA"]
    assert [s["kind"] for s in ex["segments"]] == ["literal", "size", "value", "code", "code", "code"]
    tolerance = ex["segments"][3]
    assert tolerance == {"text": "F", "kind": "code", "name": "tolerance", "label": "Toleranz", "short": "Tol.",
                         "meaning": "±1 %"}
    assert ex["segments"][2]["meaning"] == "10kΩ" and ex["description"] == "RES 0603 10kΩ ±1% 0.1W Dickschicht"
    assert vishay["mode"] == "rules" and vishay["value_range"] == [1.0, 10e6] and vishay["e_series"] == ["E24", "E96"]
    assert vishay["jumper"] and vishay["sources"][0]["url"].endswith("dcrcwe3.pdf")
    kemet = listing["kemet-c-x7r"]
    assert kemet["mode"] == "matrix" and kemet["example"]["mpn"] == "C0603C104K5RACTU" and not kemet["jumper"]
    murata = listing["murata-grm-x7r"]
    assert murata["mode"] == "catalog" and murata["verified"] and murata["part_count"] == 28
    # the example prefers a part in production (GRM188R71H104KA93D is "To be discontinued")
    assert [s["text"] for s in murata["example"]["segments"]] == ["GRM", "18", "8", "R7", "1H", "224", "K", "AC4",
                                                                   "D"]


def test_template_example_reports_missing_required_fields(client: TestClient) -> None:
    template = custom_template("haus-ohne-p", fields={"Resistance": "{value}", "Tolerance": "{tolerance}"})
    assert client.post("/api/series/templates/custom", json=template).status_code == 200
    card = next(t for t in client.get("/api/series/templates").json() if t["id"] == "haus-ohne-p")
    example = card["example"]
    assert example["mpn"] == "HR0603-10KF" and not example["valid"]
    assert example["missing_fields"] == [{"column": "Power", "label": "Leistung"}]
    assert "Leistung" in example["message"] and "nicht anlegen" in example["message"]


def test_template_examples_without_library(bare_client: TestClient) -> None:
    listing = bare_client.get("/api/series/templates").json()
    assert len(listing) == 14 and all(t["example"] and t["example"]["valid"] for t in listing)  # built-in categories
    assert next(t for t in listing if t["id"] == "yageo-rc-l")["example"]["description"].startswith("RES 0603 10kΩ")


def test_template_test_runs_the_required_field_check(client: TestClient) -> None:
    body = {"template": custom_template(fields={"Resistance": "{value}", "Tolerance": "{tolerance}"}),
            "samples": [{"size": "0603", "value": "4k7"}]}
    data = client.post("/api/series/templates/test", json=body).json()
    assert data["category_checked"] and data["category_note"] is None
    sample = data["samples"][0]
    assert sample["valid"] and sample["missing_fields"] == [{"column": "Power", "label": "Leistung"}]
    assert any("Leistung" in m and "nicht anlegen" in m for m in sample["messages"])
    assert sample["values"]["Resistance"] == "4.7kΩ" and sample["values"]["Description"] == "RES 4.7kΩ ±1%"
    complete = client.post("/api/series/templates/test", json={**body, "template": custom_template()}).json()
    assert complete["samples"][0]["missing_fields"] == [] and complete["samples"][0]["values"]["Power"] == "0.1W"
    # 0-Ω jumper sample: tolerance, TCR, power and voltage do not apply
    vishay = client.get("/api/series/templates/vishay-crcw-e3", params={"full": True}).json()
    vishay.update(id="vishay-kopie", builtin=False)
    jumper = client.post("/api/series/templates/test", json={"template": vishay,
                                                             "samples": [{"size": "0603", "value": "0"}]}).json()
    j = jumper["samples"][0]
    assert j["mpn"] == "CRCW06030000Z0EA" and j["valid"] and j["missing_fields"] == []
    assert set(j["not_applicable"]) == {"Tolerance", "Power", "Voltage", "TCR"}
    other = custom_template(category="Gibt Es Nicht")
    unknown = client.post("/api/series/templates/test", json={**body, "template": other}).json()
    assert not unknown["category_checked"] and "Gibt Es Nicht" in unknown["category_note"]
    assert unknown["samples"][0]["mpn"] == "HR0603-4K7F" and unknown["samples"][0]["missing_fields"] == []


def test_template_test_without_library_uses_the_builtin_category(bare_client: TestClient) -> None:
    body = {"template": custom_template(fields={"Resistance": "{value}"}), "samples": [{"size": "0603", "value": "1k"}]}
    data = bare_client.post("/api/series/templates/test", json=body).json()
    assert data["category_checked"]
    assert {f["column"] for f in data["samples"][0]["missing_fields"]} == {"Tolerance", "Power"}


def test_preview_reports_skipped_values_per_size(client: TestClient) -> None:
    body = {"template_id": "kemet-c-x7r", "sizes": ["0603"], "range_min": "1u", "range_max": "10u",
            "tolerance": "5%"}
    data = client.post("/api/series/preview", json=body).json()
    assert data["skipped_by_size"] == {"0603": 4} and data["skipped_total"] == 4
    assert data["skipped_reason"] == "Laut Datenblatt nur in anderen Toleranzen lieferbar"
    rules = client.post("/api/series/preview", json={"template_id": "panasonic-erj-1pct", "sizes": ["0402", "0603"],
                                                     "range_min": "1", "range_max": "12", "e_series": "E24"}).json()
    assert rules["skipped_by_size"] == {"0402": 24, "0603": 24} and rules["skipped_total"] == 48  # 1 … 9.1 Ω
    assert rules["skipped_reason"].startswith("Laut Datenblatt mit dieser Auswahl nicht lieferbar")
    plain = client.post("/api/series/preview", json={"template_id": "vishay-crcw-e3", "values": ["10k"]}).json()
    assert plain["skipped_by_size"] == {} and plain["skipped_total"] == 0 and plain["skipped_reason"] is None


def test_preview_explains_footprint_name_tags(client: TestClient) -> None:
    kemet = client.post("/api/series/preview", json={"template_id": "kemet-c-x7r", "sizes": ["0603"],
                                                     "values": ["100n", "10n"]}).json()
    refs = {f["name"]: f for f in kemet["footprints"]}
    tagged = refs["CAPC1608X90N_4328"]
    assert tagged["plain_name"] == "CAPC1608X90N" and "„_4328“" in tagged["name_reason"]
    assert "Bauteilhöhe laut Datenblatt 0,8 ± 0,1 mm" in tagged["name_reason"] and "0,87 mm" in tagged["name_reason"]
    assert refs["CAPC1608X87N"]["name_reason"] is None and refs["CAPC1608X87N"]["plain_name"] is None
    row = next(r for r in kemet["rows"] if r["footprint"]["name"] == "CAPC1608X90N_4328")
    assert row["footprint"]["plain_name"] == "CAPC1608X90N" and row["footprint"]["name_reason"] is None  # once only
    exact = client.post("/api/series/preview", json={"template_id": "kemet-c-x7r", "sizes": ["0805"],
                                                     "values": ["100n"], "footprint_height": "exact"}).json()
    tagged_exact = [f for f in exact["footprints"] if f["plain_name"]]
    assert tagged_exact and all("Höhe „Exakt“" in f["name_reason"] for f in tagged_exact)
    vishay = client.post("/api/series/preview", json={"template_id": "vishay-crcw-e3", "sizes": ["1218"],
                                                      "values": ["10k"]}).json()
    assert "Gehäusemaße laut Datenblatt" in vishay["footprints"][0]["name_reason"]
    srr = client.post("/api/series/preview", json={"template_id": "bourns-srr1260", "values": ["10u"]}).json()
    assert "Herstellerempfehlung" in srr["footprints"][0]["name_reason"]


def test_catalog_rows_carry_their_own_link_and_lifecycle(client: TestClient) -> None:
    data = client.post("/api/series/preview", json={"template_id": "murata-grm-x7r", "sizes": ["0603"]}).json()
    rows = {r["mpn"]: r for r in data["rows"]}
    old = rows["GRM188R71H104KA93D"]
    assert old["values"]["Lifecycle"] == "Abgekündigt" and "GRM155R71H104KE14" in " ".join(old["messages"])
    murata_page = "https://pim.murata.com/en-us/pim/details/?partNum=GRM188R71H104KA93%23"
    assert old["values"]["ComponentLink1URL"] == murata_page
    assert rows["GRM188R71H224KAC4D"]["values"]["Lifecycle"] == "Aktiv"
    fixed = client.post("/api/series/preview", json={"template_id": "murata-grm-x7r", "sizes": ["0603"],
                                                     "datasheet_url": "https://example.com/grm.pdf"}).json()
    assert {r["values"]["ComponentLink1URL"] for r in fixed["rows"]} == {"https://example.com/grm.pdf"}


def test_openapi_types_the_series_job_and_new_fields(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    job = schemas["SeriesJobOut"]["properties"]["job"]
    refs = [job.get("$ref"), *(x.get("$ref") for x in job.get("allOf", []))]
    assert "#/components/schemas/SeriesJobSnapshot" in refs
    snapshot = schemas["SeriesJobSnapshot"]["properties"]
    assert {"$ref": "#/components/schemas/SeriesCommitResult"} in snapshot["result"]["anyOf"]
    result = schemas["SeriesCommitResult"]["properties"]
    assert {"created", "updated", "skipped", "footprints_created", "part_warnings", "message"} <= set(result)
    assert set(schemas["SeriesCommitDetail"]["properties"]) == {"phase", "done", "total"}
    assert {"skipped_by_size", "skipped_total", "skipped_reason"} <= set(schemas["SeriesPreview"]["properties"])
    assert {"plain_name", "name_reason"} <= set(schemas["FootprintRef"]["properties"])
    assert {"example", "mode", "value_range", "e_series", "jumper", "sources"} <= set(
        schemas["TemplateSummary"]["properties"])
    assert {"segments", "valid", "missing_fields", "description"} <= set(schemas["TemplateExampleOut"]["properties"])
    assert {"missing_fields", "not_applicable", "values"} <= set(schemas["TemplateSampleResult"]["properties"])
    assert {"category_checked", "category_note"} <= set(schemas["TemplateTestOut"]["properties"])


def test_commit_job_result_is_typed(client: TestClient, fake_sync: None) -> None:
    from partforge.domain.series import SeriesCommitResult

    r = client.post("/api/series/commit", json={"template_id": "vishay-crcw-e3", "sizes": ["0603"],
                                                "values": ["10k", "4.7k"], "include_jumper": True})
    assert r.status_code == 200 and r.json()["job"]["kind"] == "series"
    job = wait_for_job(client, r.json()["job"]["id"])
    result = SeriesCommitResult.model_validate(job["result"])
    assert result.created == 3 and result.message == job["message"]
    assert job["message"] == "Serie erzeugt: 3 neu, 0 aktualisiert, 0 übersprungen, 1 Footprint neu"
    assert job["detail"] == {"phase": "done", "done": 3, "total": 3}
    assert any(e["text"] == "Sicherung wird angelegt …" for e in job["log"])
