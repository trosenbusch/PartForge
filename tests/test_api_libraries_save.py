"""API: editor saves (target library, dry run, structured pin-out conflict), thumbnails with ETag,
``svg=false`` details and the final messages of the library jobs (in-memory writer, no Altium)."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote

import pytest
from test_sync_support import FakeWriter, make_part
from test_writer_samples import ic8_symbol, resistor_symbol

from partforge.altium import libwriter, sync
from partforge.db import registry
from partforge.db.models import SymbolRecord
from partforge.footprints import FootprintRequest
from partforge.footprints import generate as generate_footprint
from partforge.symbols import SymbolRequest
from partforge.symbols import generate as generate_symbol


@pytest.fixture(autouse=True)
def writer(monkeypatch) -> FakeWriter:
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()
    fake = FakeWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: fake)
    return fake


def url(kind: str, name: str, suffix: str = "") -> str:
    return f"/api/libraries/{kind}/{quote(name)}{suffix}"


def body(spec, **extra) -> dict:
    return {"spec": spec.model_dump(mode="json"), **extra}


def wait_job(client, job: dict, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Job {job['id']} nicht fertig")


# --------------------------------------------------------------------------- target library, dry run


def test_new_symbol_reports_its_target_library(client, workspace, writer):
    spec = generate_symbol(SymbolRequest(kind="opamp_dual"))
    expected_abs = str(workspace.symbols_dir / "PF_Analog.SchLib")
    dry = client.put(url("symbols", spec.name), params={"dry_run": True}, json=body(spec, category="Amplifiers"))
    assert dry.status_code == 200, dry.text
    out = dry.json()
    assert out["dry_run"] is True and out["new"] is True and out["unchanged"] is False
    assert out["record"] is None and out["job"] is None
    assert out["library"] == "Symbols\\PF_Analog.SchLib" and out["library_abs"] == expected_abs
    assert registry.get_symbol(spec.name) is None and writer.calls == []  # nothing registered or written
    saved = client.put(url("symbols", spec.name), json=body(spec, category="Amplifiers", background=False)).json()
    assert saved["new"] is True and saved["dry_run"] is False
    assert saved["library"] == "Symbols\\PF_Analog.SchLib" and saved["library_abs"] == expected_abs
    assert saved["record"]["library"] == saved["library"]
    again = client.put(url("symbols", spec.name), params={"dry_run": True}, json=body(spec)).json()
    assert again["new"] is False and again["unchanged"] is True and again["changes"] == []


def test_background_save_names_target_and_ends_with_a_specific_message(client, workspace):
    spec = resistor_symbol("R_BG")
    resp = client.put(url("symbols", "R_BG"), json=body(spec, category="Resistors", background=True))
    out = resp.json()
    assert resp.status_code == 200 and out["record"] is None and out["job"]["kind"] == "libraries.save"
    assert out["library"] == "Symbols\\PF_Passives.SchLib" and out["new"] is True
    snap = wait_job(client, out["job"])
    assert snap["status"] == "done", snap
    assert snap["message"] == "Symbol „R_BG“ gespeichert in Symbols\\PF_Passives.SchLib"
    assert "fertig" not in snap["message"]
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    resp = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": True})
    snap = wait_job(client, resp.json()["job"])
    assert snap["status"] == "done", snap
    assert snap["message"] == f"Footprint „{fp.name}“ gespeichert in Footprints\\PF_CHIP.PcbLib"
    assert resp.json()["library"] == "Footprints\\PF_CHIP.PcbLib"


def test_dry_run_reports_pinout_changes_instead_of_409(client, workspace):
    spec = ic8_symbol("TIMER")
    spec.footprints = []
    assert client.put(url("symbols", "TIMER"), json=body(spec, background=False)).status_code == 200
    make_part("Resistors", "R-T1", Library_Ref="TIMER")
    changed = spec.model_copy(deep=True)
    changed.pins[0].name = "TRIGGER"
    dry = client.put(url("symbols", "TIMER"), params={"dry_run": True}, json=body(changed)).json()
    assert dry["dry_run"] is True and dry["needs_confirmation"] is True and dry["unchanged"] is False
    assert dry["changes"] == ["Pin 2: Name „TRIG“ → „TRIGGER“"] and dry["usage"] == 1
    assert dry["library"] == "Symbols\\PF_ICs.SchLib"
    confirmed = client.put(url("symbols", "TIMER"), params={"dry_run": True},
                           json=body(changed, allow_pinout_change=True)).json()
    assert confirmed["needs_confirmation"] is False and confirmed["changes"] == dry["changes"]
    stored = registry.get_symbol("TIMER")
    assert stored is not None and stored.spec is not None and stored.spec.pins[0].name == "TRIG"  # untouched
    real = client.put(url("symbols", "TIMER"), json=body(changed, background=False))
    assert real.status_code == 409
    detail = real.json()["detail"]
    assert detail == {"code": "pinout_changed", "message": detail["message"], "changes": dry["changes"], "usage": 1}
    assert detail["message"].startswith("Die Pinbelegung von „TIMER“ ändert sich (Pin 2: Name „TRIG“ → „TRIGGER“); 1 ")


def test_dry_run_keeps_the_other_checks(client, workspace, writer, tmp_path: Path):
    spec = resistor_symbol("R_DRY")
    assert client.put(url("symbols", "OTHER"), params={"dry_run": True}, json=body(spec)).status_code == 400
    bad = resistor_symbol("R_DRY")
    bad.pins[0].x = -105
    assert client.put(url("symbols", "R_DRY"), params={"dry_run": True}, json=body(bad)).status_code == 400
    writer.put(workspace.symbols_dir / "PF_Passives.SchLib", [resistor_symbol("R_USER")])
    foreign = client.put(url("symbols", "R_USER"), params={"dry_run": True}, json=body(resistor_symbol("R_USER")))
    assert foreign.status_code == 409 and "nicht von PartForge erzeugt" in foreign.json()["detail"]
    registry.upsert_symbol(SymbolRecord(name="EXT", library=str(tmp_path / "e.SchLib"), source="external", status="ok"))
    ext = client.put(url("symbols", "EXT"), params={"dry_run": True}, json=body(resistor_symbol("EXT")))
    assert ext.status_code == 409 and "externen Bibliothek" in ext.json()["detail"]


def test_footprint_dry_run(client, workspace, writer):
    fp = generate_footprint(FootprintRequest(family="sot23", params={"preset": "SOT-23-5"}))
    dry = client.put(url("footprints", fp.name), params={"dry_run": True}, json={"spec": fp.model_dump(mode="json")})
    out = dry.json()
    assert dry.status_code == 200 and out["dry_run"] and out["new"] and not out["unchanged"]
    assert out["library"] == "Footprints\\PF_SOT23.PcbLib" and registry.get_footprint(fp.name) is None
    assert writer.calls == []
    saved = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": False})
    assert saved.status_code == 200 and saved.json()["library"] == "Footprints\\PF_SOT23.PcbLib"
    # the save added the STEP reference: the same request is still "unchanged"
    again = client.put(url("footprints", fp.name), params={"dry_run": True}, json={"spec": fp.model_dump(mode="json")})
    assert again.json()["unchanged"] is True and again.json()["new"] is False
    moved = fp.model_copy(update={"description": "geändert"})
    assert client.put(url("footprints", fp.name), params={"dry_run": True},
                      json={"spec": moved.model_dump(mode="json")}).json()["unchanged"] is False


# --------------------------------------------------------------------------- thumbnails


def test_symbol_thumbnail_etag_and_304(client, workspace):
    spec = resistor_symbol("R_THUMB")
    registry.upsert_symbol(SymbolRecord(name="R_THUMB", library="Symbols\\PF_Passives.SchLib", spec=spec))
    first = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"))
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("image/svg+xml")
    assert first.text.startswith("<svg") and 'vector-effect="non-scaling-stroke"' in first.text
    assert "sans-serif" in first.text and "Times" not in first.text
    etag = first.headers["etag"]
    assert etag.startswith('"') and first.headers["cache-control"] == "private, no-cache"
    cached = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"), headers={"If-None-Match": etag})
    assert cached.status_code == 304 and cached.content == b"" and cached.headers["etag"] == etag
    weak = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"), headers={"If-None-Match": f'"x", W/{etag}'})
    assert weak.status_code == 304
    other_theme = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"), params={"theme": "light"},
                             headers={"If-None-Match": etag})
    assert other_theme.status_code == 200 and other_theme.headers["etag"] != etag
    content_hash = client.get(url("symbols", "R_THUMB")).json()["record"]["content_hash"]
    assert content_hash and etag == f'"{content_hash}.dark"'
    versioned = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"), params={"v": content_hash})
    assert "immutable" in versioned.headers["cache-control"] and versioned.headers["etag"] == etag
    # any other version (e.g. the older ``updated``) is only revalidated – it may name a stale image
    stale = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"), params={"v": "2026-10-08 12:00:00"})
    assert stale.headers["cache-control"] == "private, no-cache" and stale.headers["etag"] == etag
    # changed geometry -> new ETag, the old one no longer matches
    changed = spec.model_copy(update={"description": "neu"})
    changed.pins[0].name = "X"
    registry.upsert_symbol(SymbolRecord(name="R_THUMB", library="Symbols\\PF_Passives.SchLib", spec=changed))
    fresh = client.get(url("symbols", "R_THUMB", "/thumbnail.svg"), headers={"If-None-Match": etag})
    assert fresh.status_code == 200 and fresh.headers["etag"] != etag


def test_thumbnail_follows_the_symbol_style(client, workspace):
    spec = resistor_symbol("R_STYLE")
    registry.upsert_symbol(SymbolRecord(name="R_STYLE", library="Symbols\\PF_Passives.SchLib", spec=spec))
    before = client.get(url("symbols", "R_STYLE", "/thumbnail.svg")).headers["etag"]
    workspace.settings.symbol.pin_color = "#123456"
    after = client.get(url("symbols", "R_STYLE", "/thumbnail.svg"), headers={"If-None-Match": before})
    assert after.status_code == 200 and after.headers["etag"] != before


def test_footprint_thumbnail_etag_and_errors(client, workspace):
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    registry.upsert_footprint(sync_record(fp))
    first = client.get(url("footprints", fp.name, "/thumbnail.svg"))
    assert first.status_code == 200 and first.text.startswith("<svg")
    assert client.get(url("footprints", fp.name, "/thumbnail.svg"),
                      headers={"If-None-Match": first.headers["etag"]}).status_code == 304
    assert client.get(url("footprints", "NOPE", "/thumbnail.svg")).status_code == 404
    assert client.get(url("symbols", "NOPE", "/thumbnail.svg")).status_code == 404
    registry.upsert_symbol(SymbolRecord(name="NO_GEOMETRY", library="Symbols\\PF_Passives.SchLib"))
    missing = client.get(url("symbols", "NO_GEOMETRY", "/thumbnail.svg"))
    assert missing.status_code == 404 and "keine Geometrie" in missing.json()["detail"]
    # the detail route still answers for the names (thumbnail routes come first)
    assert client.get(url("footprints", fp.name)).json()["record"]["name"] == fp.name


def sync_record(fp):
    from partforge.db.models import FootprintRecord

    return FootprintRecord(name=fp.name, library="Footprints\\PF_CHIP.PcbLib", spec=fp, family="chip")


def test_details_without_svg(client, workspace):
    spec = generate_symbol(SymbolRequest(kind="opamp_dual"))
    registry.upsert_symbol(SymbolRecord(name=spec.name, library="Symbols\\PF_Analog.SchLib", spec=spec))
    full = client.get(url("symbols", spec.name)).json()
    assert len(full["svgs"]) == spec.part_count
    lean = client.get(url("symbols", spec.name), params={"svg": False}).json()
    assert lean["svgs"] == [] and lean["spec"]["name"] == spec.name
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    registry.upsert_footprint(sync_record(fp))
    assert client.get(url("footprints", fp.name)).json()["svg"].startswith("<svg")
    lean_fp = client.get(url("footprints", fp.name), params={"svg": False}).json()
    assert lean_fp["svg"] is None and lean_fp["bodies"]


def test_list_thumbnails_use_the_thumbnail_style(client, workspace):
    spec = resistor_symbol("R_LIST")
    registry.upsert_symbol(SymbolRecord(name="R_LIST", library="Symbols\\PF_Passives.SchLib", spec=spec))
    listing = client.get("/api/libraries/symbols", params={"thumbnails": "svg"}).json()
    svg = next(e for e in listing if e["name"] == "R_LIST")["thumbnail_svg"]
    assert 'vector-effect="non-scaling-stroke"' in svg and "sans-serif" in svg


# --------------------------------------------------------------------------- job messages


def test_sync_and_delete_jobs_end_with_specific_messages(client, workspace):
    spec = resistor_symbol("R_SYNC")
    registry.upsert_symbol(SymbolRecord(name="R_SYNC", library="Symbols\\PF_Passives.SchLib", spec=spec))
    snap = wait_job(client, client.post("/api/libraries/sync").json()["job"])
    assert snap["status"] == "done", snap
    assert snap["message"] == "Synchronisiert: 1 Symbol und 0 Footprints", snap["message"]
    snap = wait_job(client, client.post("/api/libraries/sync").json()["job"])
    assert snap["message"] == "Bibliotheken sind aktuell – nichts zu schreiben"
    resp = client.delete(url("symbols", "R_SYNC"), params={"background": True})
    snap = wait_job(client, resp.json()["job"])
    assert snap["status"] == "done" and snap["message"] == "Symbol „R_SYNC“ gelöscht"


# --------------------------------------------------------------------------- content hash (R2)


def test_content_hash_changes_with_every_save_within_one_second(client, workspace):
    """Regression: the thumbnail URL used ``?v=<updated>`` (seconds) – two saves within one second kept the old
    image. The content hash changes with the geometry, the list's inline thumbnails follow it as well."""
    spec = resistor_symbol("R_FAST")
    registry.upsert_symbol(SymbolRecord(name="R_FAST", library="Symbols\\PF_Passives.SchLib", spec=spec))
    first = client.get("/api/libraries/symbols", params={"thumbnails": "svg"}).json()
    entry = next(e for e in first if e["name"] == "R_FAST")
    plain = next(e for e in client.get("/api/libraries/symbols").json() if e["name"] == "R_FAST")
    assert entry["content_hash"] and plain["content_hash"] == entry["content_hash"]  # also without geometry loaded
    detail = client.get(url("symbols", "R_FAST")).json()["record"]
    assert detail["content_hash"] == entry["content_hash"]
    changed = spec.model_copy(deep=True)
    changed.pins[0].name = "NEU"
    registry.upsert_symbol(SymbolRecord(name="R_FAST", library="Symbols\\PF_Passives.SchLib", spec=changed))
    second = client.get("/api/libraries/symbols", params={"thumbnails": "svg"}).json()
    again = next(e for e in second if e["name"] == "R_FAST")
    assert again["content_hash"] != entry["content_hash"]
    old = client.get(url("symbols", "R_FAST", "/thumbnail.svg"), params={"v": entry["content_hash"]})
    assert old.headers["cache-control"] == "private, no-cache"  # the old version is not cached forever
    new = client.get(url("symbols", "R_FAST", "/thumbnail.svg"), params={"v": again["content_hash"]})
    assert "immutable" in new.headers["cache-control"]
    # same geometry, other status: same hash (the thumbnail does not show the status)
    registry.set_symbol_status("R_FAST", "error", "x")
    assert client.get(url("symbols", "R_FAST")).json()["record"]["content_hash"] == again["content_hash"]
    # footprints the same way; an entry without geometry has none
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    registry.upsert_footprint(sync_record(fp))
    listed = client.get("/api/libraries/footprints").json()
    assert listed[0]["content_hash"] and listed[0]["content_hash"] == client.get(
        url("footprints", fp.name)).json()["record"]["content_hash"]
    registry.upsert_symbol(SymbolRecord(name="NO_SPEC", library="Symbols\\PF_Passives.SchLib"))
    no_spec = next(e for e in client.get("/api/libraries/symbols").json() if e["name"] == "NO_SPEC")
    assert no_spec["content_hash"] is None


def test_content_hash_follows_the_symbol_style(client, workspace):
    spec = resistor_symbol("R_HSTYLE")
    registry.upsert_symbol(SymbolRecord(name="R_HSTYLE", library="Symbols\\PF_Passives.SchLib", spec=spec))
    before = client.get(url("symbols", "R_HSTYLE")).json()["record"]["content_hash"]
    workspace.settings.symbol.pin_color = "#123456"
    assert client.get(url("symbols", "R_HSTYLE")).json()["record"]["content_hash"] != before


def test_saves_answer_the_content_hash(client, workspace, writer):
    spec = resistor_symbol("R_SAVED")
    saved = client.put(url("symbols", "R_SAVED"), json=body(spec, background=False)).json()
    assert saved["record"]["content_hash"] == client.get(url("symbols", "R_SAVED")).json()["record"]["content_hash"]


# --------------------------------------------------------------------------- custom names (R1)


def test_custom_footprint_name_is_recorded_for_regeneration(client, workspace, writer):
    from partforge.footprints import preview

    custom = generate_footprint(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, name="MY_SOIC8"))
    assert custom.generator["name"] == "MY_SOIC8"
    resp = client.put(url("footprints", "MY_SOIC8"), json={"spec": custom.model_dump(mode="json"), "background": False})
    assert resp.status_code == 200, resp.text
    stored = registry.get_footprint("MY_SOIC8")
    assert stored is not None and stored.spec is not None and stored.spec.generator["name"] == "MY_SOIC8"
    # "Neu generieren": the stored request plus generator.name gives the same footprint under the same name
    gen = stored.spec.generator
    again = preview(FootprintRequest(family=gen["family"], params=gen["params"], density=gen["density"],
                                     name=gen["name"]), svg=False).spec
    assert again.name == "MY_SOIC8" and again.generator["geometry_hash"] == gen["geometry_hash"]
    # a spec renamed by the client (generator from the plain request) gets the name recorded on save
    plain = generate_footprint(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}))
    assert "name" not in plain.generator
    renamed = plain.model_copy(update={"name": "MY_SOIC8_B"})
    client.put(url("footprints", "MY_SOIC8_B"), json={"spec": renamed.model_dump(mode="json"), "background": False})
    assert registry.get_footprint("MY_SOIC8_B").spec.generator["name"] == "MY_SOIC8_B"  # type: ignore[union-attr]
    # a generated name is not recorded (it follows the naming scheme of the house style)
    client.put(url("footprints", plain.name), json={"spec": plain.model_dump(mode="json"), "background": False})
    assert "name" not in registry.get_footprint(plain.name).spec.generator  # type: ignore[union-attr]


def test_custom_symbol_name_is_recorded_for_regeneration(client, workspace, writer):
    plain = generate_symbol(SymbolRequest(kind="opamp_dual"))
    assert plain.generator["default_name"] == plain.name and "name" not in plain.generator
    renamed = plain.model_copy(update={"name": "MY_OPAMP"})
    resp = client.put(url("symbols", "MY_OPAMP"), json=body(renamed, category="Amplifiers", background=False))
    assert resp.status_code == 200, resp.text
    gen = registry.get_symbol("MY_OPAMP").spec.generator  # type: ignore[union-attr]
    assert gen["name"] == "MY_OPAMP" and gen["request"]["name"] == "MY_OPAMP"
    regenerated = generate_symbol(SymbolRequest.model_validate(gen["request"]))
    assert regenerated.name == "MY_OPAMP" and regenerated.generator["name"] == "MY_OPAMP"
    client.put(url("symbols", plain.name), json=body(plain, category="Amplifiers", background=False))
    stored = registry.get_symbol(plain.name).spec.generator  # type: ignore[union-attr]
    assert "name" not in stored and "name" not in stored["request"]


# --------------------------------------------------------------------------- explicit target library (R7)


def test_explicit_target_library(client, workspace, writer):
    spec = resistor_symbol("R_LIB")
    dry = client.put(url("symbols", "R_LIB"), params={"dry_run": True},
                     json=body(spec, library="PF_Eigene.SchLib")).json()
    assert dry["library"] == "Symbols\\PF_Eigene.SchLib" and dry["new"] is True
    saved = client.put(url("symbols", "R_LIB"), json=body(spec, library="Symbols/PF_Eigene.SchLib", background=False))
    assert saved.status_code == 200, saved.text
    assert saved.json()["record"]["library"] == "Symbols\\PF_Eigene.SchLib"
    assert (workspace.symbols_dir / "PF_Eigene.SchLib").is_file()
    # an existing library of the workspace (any name) is a valid target, also absolute
    other = resistor_symbol("R_LIB2")
    target = str(workspace.symbols_dir / "PF_Eigene.SchLib")
    assert client.put(url("symbols", "R_LIB2"), json=body(other, library=target, background=False)).json()[
        "record"]["library"] == "Symbols\\PF_Eigene.SchLib"
    # the same library again: fine; another one: a save never moves a registered symbol
    assert client.put(url("symbols", "R_LIB"), json=body(spec, library="PF_Eigene.SchLib", background=False)
                      ).status_code == 200
    moved = client.put(url("symbols", "R_LIB"), json=body(spec, library="PF_Andere.SchLib", background=False))
    assert moved.status_code == 409 and "Verschieben" in moved.json()["detail"]
    assert client.put(url("symbols", "R_LIB"), params={"dry_run": True},
                      json=body(spec, library="PF_Andere.SchLib")).status_code == 409


@pytest.mark.parametrize("library", [
    "Eigene.SchLib",  # a new library must be called PF_<Name>
    "PF_Eigene.PcbLib",  # wrong kind
    "PF_Eigene",  # no extension
    "..\\PF_Eigene.SchLib",  # outside the symbols folder
    "Footprints\\PF_X.SchLib",  # wrong folder
    "Symbols\\Unter\\PF_Neu.SchLib",  # new libraries only directly in the folder
    "PF_Ä.SchLib",  # not ASCII
    "PF_.SchLib",
    "   ",
])
def test_invalid_target_libraries_are_refused(client, workspace, writer, library):
    resp = client.put(url("symbols", "R_BAD"), json=body(resistor_symbol("R_BAD"), library=library, background=False))
    if library.strip():
        assert resp.status_code == 400, resp.text
        assert "PF_<Name>.SchLib" in resp.json()["detail"]
    else:
        assert resp.status_code == 200  # blank = automatic
    assert writer.writes() == [] or library.strip() == ""


def test_target_library_for_footprints(client, workspace, writer):
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    resp = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": False,
                                                        "library": "PF_Meine.PcbLib"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["record"]["library"] == "Footprints\\PF_Meine.PcbLib"
    bad = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": False,
                                                       "library": "PF_Meine.SchLib"})
    assert bad.status_code == 400 and "PF_<Name>.PcbLib" in bad.json()["detail"]
    moved = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": False,
                                                         "library": "PF_CHIP.PcbLib"})
    assert moved.status_code == 409


def test_existing_unmanaged_file_is_not_a_target(client, workspace, writer, tmp_path: Path):
    (workspace.root / "Exports").mkdir(exist_ok=True)
    stray = workspace.root / "Exports" / "PF_Fremd.SchLib"
    stray.write_bytes(b"x")
    resp = client.put(url("symbols", "R_STRAY"), json=body(resistor_symbol("R_STRAY"), library=str(stray),
                                                           background=False))
    assert resp.status_code == 400
