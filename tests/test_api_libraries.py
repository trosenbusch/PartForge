"""API: /api/libraries/* (registry views, editor save/delete, sync/scan jobs, files, health,
external libraries, layer stack)."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote

import pytest
from test_sync_support import make_part, synthetic_pcblib
from test_writer_samples import ic8_symbol, resistor_symbol

from partforge.altium import libwriter, stackup, sync
from partforge.altium.rustwriter import RustLibraryOps, shutdown_client
from partforge.db import registry
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.footprints import FootprintRequest
from partforge.footprints import generate as generate_footprint
from partforge.symbols import SymbolRequest
from partforge.symbols import generate as generate_symbol

rust = pytest.mark.rustwriter


@pytest.fixture(scope="module", autouse=True)
def _stop_writer_after_module():
    yield
    shutdown_client()


@pytest.fixture(autouse=True)
def _no_altium(monkeypatch):
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    libwriter.forget_component_names()


def wait_job(client, job: dict, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = client.get(f"/api/jobs/{job['id']}").json()
        if snap["status"] in ("done", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError(f"Job {job['id']} nicht fertig")


def _symbol_body(spec, **extra) -> dict:
    return {"spec": spec.model_dump(mode="json"), **extra}


def url(kind: str, name: str, suffix: str = "") -> str:
    return f"/api/libraries/{kind}/{quote(name)}{suffix}"


# --------------------------------------------------------------------------- without library


def test_endpoints_need_an_open_library(bare_client):
    for path in ("/api/libraries/symbols", "/api/libraries/files", "/api/libraries/health", "/api/libraries/external"):
        assert bare_client.get(path).status_code == 409, path
    assert bare_client.post("/api/libraries/sync").status_code == 409


# --------------------------------------------------------------------------- symbols


@rust
def test_save_list_and_get_symbol(client, workspace):
    spec = generate_symbol(SymbolRequest(kind="opamp_dual"))
    resp = client.put(url("symbols", spec.name), json=_symbol_body(spec, category="Amplifiers"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job"] is None
    record = body["record"]
    assert record["status"] == "ok" and record["library"] == "Symbols\\PF_Analog.SchLib"
    assert record["library_abs"] == str(workspace.symbols_dir / "PF_Analog.SchLib")
    listing = client.get("/api/libraries/symbols", params={"thumbnails": "svg"}).json()
    assert [e["name"] for e in listing] == ["Op-Amp Dual"]
    assert listing[0]["thumbnail_svg"].startswith("<svg") and listing[0]["part_count"] == spec.part_count
    plain = client.get("/api/libraries/symbols").json()
    assert plain[0]["thumbnail_svg"] is None and plain[0]["has_spec"] is None  # list without geometry
    assert listing[0]["has_spec"] is True
    detail = client.get(url("symbols", spec.name)).json()
    assert detail["record"]["usage"] == 0 and detail["file_exists"] is True
    assert len(detail["svgs"]) == spec.part_count and detail["spec"]["name"] == "Op-Amp Dual"
    assert client.get("/api/libraries/symbols", params={"search": "analog"}).json()[0]["name"] == "Op-Amp Dual"
    assert client.get("/api/libraries/symbols", params={"search": "xyz"}).json() == []
    assert client.get("/api/libraries/symbols", params={"status": "error"}).json() == []


def test_get_unknown_symbol_and_footprint(client):
    assert client.get(url("symbols", "Gibt es nicht")).status_code == 404
    assert client.get(url("footprints", "NOPE")).status_code == 404
    assert client.get(url("footprints", "NOPE", "/step")).status_code == 404
    assert client.delete(url("symbols", "NOPE")).status_code == 404


def test_save_symbol_validation(client):
    spec = resistor_symbol("R_TEST")
    resp = client.put(url("symbols", "OTHER"), json=_symbol_body(spec))
    assert resp.status_code == 400 and "Umbenennen" in resp.json()["detail"]
    bad = resistor_symbol("R_TEST")
    bad.pins[0].x = -105
    resp = client.put(url("symbols", "R_TEST"), json=_symbol_body(bad))
    assert resp.status_code == 400 and "10-mil-Raster" in resp.json()["detail"]
    assert registry.get_symbol("R_TEST") is None


def test_save_symbol_refuses_pinout_change_and_external(client, tmp_path: Path):
    spec = ic8_symbol("TIMER")
    spec.footprints = []
    registry.upsert_symbol(SymbolRecord(name="TIMER", library="Symbols\\PF_ICs.SchLib", spec=spec, status="ok"))
    changed = spec.model_copy(deep=True)
    changed.pins[0].name = "TRIGGER"
    resp = client.put(url("symbols", "TIMER"), json=_symbol_body(changed))
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "pinout_changed" and detail["usage"] == 0
    assert detail["changes"] == ["Pin 2: Name „TRIG“ → „TRIGGER“"]
    assert "Pin 2: Name „TRIG“ → „TRIGGER“" in detail["message"] and "allow_pinout_change" in detail["message"]
    registry.upsert_symbol(SymbolRecord(name="EXT", library=str(tmp_path / "e.SchLib"), source="external", status="ok"))
    resp = client.put(url("symbols", "EXT"), json=_symbol_body(resistor_symbol("EXT")))
    assert resp.status_code == 409 and "externen Bibliothek" in resp.json()["detail"]


@rust
def test_confirmed_pinout_change_and_background_save(client, workspace):
    spec = ic8_symbol("TIMER")
    spec.footprints = []
    assert client.put(url("symbols", "TIMER"), json=_symbol_body(spec)).json()["record"]["status"] == "ok"
    changed = spec.model_copy(deep=True)
    changed.pins[0].name = "TRIGGER"
    resp = client.put(url("symbols", "TIMER"), json=_symbol_body(changed, allow_pinout_change=True, background=True))
    body = resp.json()
    assert resp.status_code == 200 and body["record"] is None and body["job"]["kind"] == "libraries.save"
    snap = wait_job(client, body["job"])
    assert snap["status"] == "done", snap
    assert snap["result"]["records"][0]["status"] == "ok"
    stored = registry.get_symbol("TIMER")
    assert stored is not None and stored.spec is not None and stored.spec.pins[0].name == "TRIGGER"


@rust
def test_delete_symbol(client, workspace):
    spec = generate_symbol(SymbolRequest(kind="resistor"))
    client.put(url("symbols", spec.name), json=_symbol_body(spec))
    make_part("Resistors", "R-1", Library_Ref="Resistor")
    resp = client.delete(url("symbols", "Resistor"))
    assert resp.status_code == 409 and "1 Bauteil" in resp.json()["detail"]
    resp = client.delete(url("symbols", "Resistor"), params={"force": True})
    assert resp.status_code == 200 and resp.json()["result"]["deleted"] == ["Resistor"]
    assert registry.get_symbol("Resistor") is None
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    assert RustLibraryOps(workspace=workspace).list_components(lib) == []


def _fake_writer(monkeypatch):
    from test_sync_support import FakeWriter

    writer = FakeWriter()
    monkeypatch.setattr(sync, "get_writer", lambda *a, **k: writer)
    return writer


def test_failed_saves_are_http_errors(client, workspace, monkeypatch):
    """Review finding: a save that did not reach the library answered 200."""
    from test_sync_support import FakeBridge

    def unavailable(*_a, **_k):
        raise libwriter.WriterUnavailable("Kein Bibliotheks-Writer verfügbar.")

    monkeypatch.setattr(sync, "get_writer", unavailable)
    resp = client.put(url("symbols", "R_NOWRITER"), json=_symbol_body(resistor_symbol("R_NOWRITER"), background=False))
    assert resp.status_code == 503 and "nächsten Synchronisieren" in resp.json()["detail"]
    assert registry.get_symbol("R_NOWRITER").status == "pending"  # type: ignore[union-attr]  # nothing lost
    writer = _fake_writer(monkeypatch)
    spec = resistor_symbol("R_ALT")
    assert client.put(url("symbols", "R_ALT"), json=_symbol_body(spec, background=False)).status_code == 200
    monkeypatch.setattr(sync, "altium_bridge", lambda: FakeBridge(open_=True, modified=True))
    changed = spec.model_copy(update={"description": "neu"})
    resp = client.put(url("symbols", "R_ALT"), json=_symbol_body(changed, background=False))
    assert resp.status_code == 409 and sync.ALTIUM_MODIFIED_MESSAGE in resp.json()["detail"]
    monkeypatch.setattr(sync, "altium_bridge", lambda: None)
    fp = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    from partforge.altium.rustwriter import RustTimeoutError

    writer.fail = RustTimeoutError("Der Rust-Writer antwortet nicht.")
    resp = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": False})
    assert resp.status_code == 503 and "antwortet nicht" in resp.json()["detail"]
    # in the background the job fails with the same message
    resp = client.put(url("footprints", fp.name), json={"spec": fp.model_dump(mode="json"), "background": True})
    snap = wait_job(client, resp.json()["job"])
    assert snap["status"] == "failed" and "antwortet nicht" in (snap["error"] or "")


def test_save_refuses_a_foreign_component_of_the_same_name(client, workspace, monkeypatch):
    writer = _fake_writer(monkeypatch)
    lib = workspace.symbols_dir / "PF_Passives.SchLib"
    writer.put(lib, [resistor_symbol("R_USER")])  # drawn by the user, not registered
    resp = client.put(url("symbols", "R_USER"), json=_symbol_body(resistor_symbol("R_USER"), background=False))
    assert resp.status_code == 409 and "nicht von PartForge erzeugt" in resp.json()["detail"]
    assert registry.get_symbol("R_USER") is None and writer.writes() == []


@rust
def test_detail_warns_about_content_a_save_would_lose(client, workspace):
    from partforge.altium.rustwriter import _posix, footprint_to_rust
    from partforge.footprints import chip_request

    lib = workspace.footprints_dir / "PF_CHIP.PcbLib"
    spec = generate_footprint(chip_request("C", "0805")).model_copy(update={"name": "VENDOR_C0805", "bodies": []})
    payload = footprint_to_rust(spec, workspace.settings.layers, workspace.settings.footprint)
    payload["tracks"].append({"x1": -1.0, "y1": -1.0, "x2": 1.0, "y2": 1.0, "width": 0.1, "layer": "Mechanical 5"})
    RustLibraryOps(workspace=workspace).client().call_tool(
        "write_pcblib", {"filepath": _posix(lib), "append": False, "footprints": [payload]}
    )
    snap = wait_job(client, client.post("/api/libraries/scan", json={"register_unknown": True}).json()["job"])
    assert snap["status"] == "done" and snap["result"]["registered"][0]["name"] == "VENDOR_C0805"
    detail = client.get(url("footprints", "VENDOR_C0805")).json()
    assert any("verloren" in w for w in detail["warnings"]), detail["warnings"]


# --------------------------------------------------------------------------- footprints


@rust
def test_save_footprint_detail_and_step_download(client, workspace):
    spec = generate_footprint(FootprintRequest(family="sot23", params={"preset": "SOT-23-5"}))
    resp = client.put(url("footprints", spec.name), json={"spec": spec.model_dump(mode="json")})
    assert resp.status_code == 200, resp.text
    record = resp.json()["record"]
    assert record["status"] == "ok" and record["step_file"] == f"3D\\{spec.name}.step"
    assert record["family"] == "sot23" and record["pad_count"] == 5
    detail = client.get(url("footprints", spec.name)).json()
    assert detail["svg"].startswith("<svg") and detail["bodies"] and detail["height"] == spec.height
    assert detail["step"]["exists"] is True and detail["file_exists"] is True
    step = client.get(url("footprints", spec.name, "/step"))
    assert step.status_code == 200 and step.headers["content-type"].startswith("model/step")
    assert step.content.startswith(b"ISO-10303-21;")
    listing = client.get("/api/libraries/footprints", params={"thumbnails": "svg", "family": "sot23"}).json()
    assert listing[0]["name"] == spec.name and listing[0]["thumbnail_svg"].startswith("<svg")


def test_step_download_generated_from_bodies(client):
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    registry.upsert_footprint(FootprintRecord(name=spec.name, library="Footprints\\PF_CHIP.PcbLib", spec=spec, status="pending"))
    step = client.get(url("footprints", spec.name, "/step"))
    assert step.status_code == 200 and b"PartForge 3D model of" in step.content
    flat = spec.model_copy(update={"name": "FLAT", "bodies": []})
    registry.upsert_footprint(FootprintRecord(name="FLAT", library="Footprints\\PF_CHIP.PcbLib", spec=flat))
    resp = client.get(url("footprints", "FLAT", "/step"))
    assert resp.status_code == 404 and "kein 3D-Modell" in resp.json()["detail"]


def test_footprint_names_with_special_characters(client):
    name = "SOIC-8 3.9x4.9MM (EP+)"
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"})).model_copy(update={"name": name})
    registry.upsert_footprint(FootprintRecord(name=name, library="Footprints\\PF_X.PcbLib", spec=spec))
    detail = client.get(url("footprints", name))
    assert detail.status_code == 200 and detail.json()["record"]["name"] == name
    assert client.get(url("footprints", name, "/step")).status_code == 200


def test_save_footprint_validation(client):
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    bad = spec.model_copy(update={"description": "a|b"})
    resp = client.put(url("footprints", spec.name), json={"spec": bad.model_dump(mode="json")})
    assert resp.status_code == 400 and "'|'" in resp.json()["detail"]
    resp = client.put(url("footprints", "ANDERS"), json={"spec": spec.model_dump(mode="json")})
    assert resp.status_code == 400


@rust
def test_delete_footprint_and_refusal(client, workspace):
    spec = generate_footprint(FootprintRequest(family="chip", params={"preset": "C-0603"}))
    client.put(url("footprints", spec.name), json={"spec": spec.model_dump(mode="json")})
    make_part("Capacitors", "C-1", Footprint_Ref=spec.name)
    assert client.delete(url("footprints", spec.name)).status_code == 409
    resp = client.delete(url("footprints", spec.name), params={"force": "true"})
    assert resp.status_code == 200 and resp.json()["result"]["deleted"] == [spec.name]


# --------------------------------------------------------------------------- sync, files, scan, health


@rust
def test_sync_job_files_scan_and_health(client, workspace):
    registry.upsert_symbol(SymbolRecord(name="Resistor", library="Symbols\\PF_Passives.SchLib", kind="resistor"))
    registry.upsert_footprint(
        FootprintRecord(name="RESC1608X50N", library="Footprints\\PF_CHIP.PcbLib", family="chip", ipc_name="RESC1608X50N")
    )
    make_part("Resistors", "R-1", Library_Ref="Resistor", Footprint_Ref="RESC1608X50N")
    job = client.post("/api/libraries/sync").json()["job"]
    snap = wait_job(client, job)
    assert snap["status"] == "done", snap
    assert snap["result"]["symbols"]["ok"] == 1 and snap["result"]["footprints"]["ok"] == 1
    files = client.get("/api/libraries/files").json()
    assert {f["rel"] for f in files} == {"Symbols\\PF_Passives.SchLib", "Footprints\\PF_CHIP.PcbLib"}
    assert all(f["managed"] and f["in_sync"] and f["components"] == 1 for f in files)
    assert next(f for f in files if f["kind"] == "pcblib")["layers_ok"] is True
    assert client.get("/api/libraries/files", params={"layers": False}).json()[0]["layers_ok"] is None
    ops = RustLibraryOps(workspace=workspace)
    assert ops.upsert_symbols(workspace.symbols_dir / "PF_Passives.SchLib", [resistor_symbol("HAND")]).ok
    libwriter.forget_component_names()
    snap = wait_job(client, client.post("/api/libraries/scan", json={"register_unknown": True}).json()["job"])
    assert snap["status"] == "done" and snap["result"]["registered"][0]["name"] == "HAND"
    snap = wait_job(client, client.post("/api/libraries/scan").json()["job"])  # body optional
    assert snap["status"] == "done"
    health = client.get("/api/libraries/health").json()
    assert health["checked_parts"] == 1 and health["counts"]["error"] == 0
    assert isinstance(health["issues"], list)


def test_health_reports_missing_component(client, workspace):
    registry.upsert_symbol(SymbolRecord(name="LOST", library="Symbols\\PF_Lost.SchLib", status="ok"))
    health = client.get("/api/libraries/health").json()
    issue = next(i for i in health["issues"] if "LOST" in i["message"])
    assert issue["severity"] == "error" and issue["check"] == "library_file_missing" and issue["fix_hint"]


# --------------------------------------------------------------------------- external libraries


@rust
def test_external_library_endpoints(client, workspace, tmp_path: Path):
    scratch = workspace.root / "Exports" / "Vendor.SchLib"
    assert RustLibraryOps(workspace=workspace).write_library_full(scratch, [resistor_symbol("VENDOR_R")]).ok
    ext = tmp_path / "Vendor.SchLib"
    ext.write_bytes(scratch.read_bytes())
    scratch.unlink()
    resp = client.post("/api/libraries/external", json={"path": str(ext)})
    assert resp.status_code == 200, resp.text
    lib = resp.json()
    assert lib["kind"] == "schlib" and lib["exists"] is True
    assert [e["id"] for e in client.get("/api/libraries/external").json()] == [lib["id"]]
    comps = client.get(f"/api/libraries/external/{lib['id']}/components", params={"previews": True}).json()
    assert comps["total"] == 1 and comps["components"][0]["name"] == "VENDOR_R"
    assert comps["components"][0]["svg"].startswith("<svg") and comps["components"][0]["registered"] is False
    used = client.post(f"/api/libraries/external/{lib['id']}/use", json={"name": "VENDOR_R"})
    assert used.status_code == 200 and used.json()["source"] == "external" and used.json()["library"] == str(ext)
    assert client.get("/api/libraries/symbols", params={"source": "external"}).json()[0]["name"] == "VENDOR_R"
    assert client.post(f"/api/libraries/external/{lib['id']}/use", json={"name": "NOPE"}).status_code == 404
    removed = client.delete(f"/api/libraries/external/{lib['id']}").json()
    assert removed["registered_components"] == ["VENDOR_R"]
    assert client.get("/api/libraries/external").json() == []
    assert client.delete(f"/api/libraries/external/{lib['id']}").status_code == 404


def test_external_library_errors(client, tmp_path: Path):
    resp = client.post("/api/libraries/external", json={"path": str(tmp_path / "fehlt.SchLib")})
    assert resp.status_code == 404
    resp = client.post("/api/libraries/external", json={"path": "relativ.PcbLib"})
    assert resp.status_code == 400 and "absolut" in resp.json()["detail"]
    assert client.get("/api/libraries/external/0123456789ab/components").status_code == 404


# --------------------------------------------------------------------------- layer stack


def test_layer_stack_endpoints(client, workspace, tmp_path: Path):
    data = client.get("/api/libraries/layer-stack").json()
    assert data["stack"]["source"] == "builtin" and data["patch_enabled"] is True
    assert data["stack"]["layers"]["9"]["kind"] == "AssemblyTop"
    assert data["suggested_layer_map"] == data["layer_map"] and data["issues"] == []
    file = tmp_path / "eigen.stackup"
    file.write_text(
        "STACKUPVERSION=1|LAYER_V8_19NAME=Montage|LAYER_V8_19LAYERID=16908293|LAYER_V8_19MECHENABLED=TRUE"
        "|LAYER_V8_19MECHKIND=AssemblyTop",
        encoding="ascii",
    )
    parsed = client.post("/api/libraries/layer-stack/parse", json={"path": str(file)}).json()
    assert parsed["stack"]["layers"]["5"]["name"] == "Montage"
    assert parsed["suggested_layer_map"]["assembly"] == "Mechanical 5"
    bad = client.post("/api/libraries/layer-stack/parse", json={"path": str(tmp_path / "x.stackup")})
    assert bad.status_code == 400 and "nicht gefunden" in bad.json()["detail"]


def test_layer_stack_apply_job(client, workspace):
    path = synthetic_pcblib(workspace.footprints_dir / "PF_OLD.PcbLib")
    snap = wait_job(client, client.post("/api/libraries/layer-stack/apply").json()["job"])
    assert snap["status"] == "done" and snap["result"]["patched"] == [str(path)]
    eff = stackup.effective_stack(stackup.default_stack(), workspace.settings.layers)
    assert stackup.pcblib_layer_problems(path, eff) == []
