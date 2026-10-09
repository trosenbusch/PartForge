"""REST API of the footprint generator (partforge/api/routes_footprints.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from partforge.app import create_app
from partforge.workspace import Workspace, set_current

TOKEN = "footprint-test-token"


@pytest.fixture
def api():
    set_current(None)
    with TestClient(create_app(token=TOKEN), headers={"X-PartForge-Token": TOKEN}) as client:
        yield client
    set_current(None)


@pytest.fixture
def fp_workspace(tmp_path: Path):
    """An open workspace with non-default footprint/symbol style (no database needed for these routes)."""
    ws = Workspace.create(tmp_path / "Bibliothek", name="Footprint-Test")
    ws.settings.footprint.naming = "house"
    ws.settings.symbol.diode_pin1 = "anode"
    set_current(ws)
    yield ws
    set_current(None)


def test_requires_token():
    client = TestClient(create_app(token=TOKEN))
    assert client.get("/api/footprints/families").status_code == 401


def test_families(api):
    r = api.get("/api/footprints/families")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 21
    chip = data[0]
    assert chip["key"] == "chip" and chip["label"] and chip["params"] and chip["presets"]
    kinds = {p["kind"] for f in data for p in f["params"]}
    assert kinds <= {"tol", "float", "int", "bool", "enum", "text"}


def test_single_family_and_presets(api):
    assert api.get("/api/footprints/families/soic").json()["key"] == "gullwing"  # alias
    r = api.get("/api/footprints/presets/gullwing")
    assert r.status_code == 200
    assert any(p["key"] == "SOIC-8" for p in r.json())
    r = api.get("/api/footprints/presets/gibtsnicht")
    assert r.status_code == 404
    assert "nicht gefunden" in r.json()["detail"]
    assert api.get("/api/footprints/families/gibtsnicht").status_code == 404


def test_preview(api):
    r = api.post("/api/footprints/preview", json={"family": "gullwing", "params": {"preset": "SOIC-8"}})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["spec"]["name"] == "SOIC127P600X175-8N"
    assert len(data["spec"]["pads"]) == 8
    assert data["svg"].startswith("<svg")
    land = data["calc"]["lands"][0]
    assert land["table"] == "3-2" and land["pad_length"] == pytest.approx(1.95)
    assert data["calc"]["courtyard"]["excess"] == 0.25
    assert data["warnings"] == [] and data["issues"] == []


def test_preview_with_clamp_warning(api):
    r = api.post("/api/footprints/preview", json={"family": "sot523", "params": {"preset": "SOT-523"},
                                                   "density": "M"})
    assert r.status_code == 200
    assert any("Mindestabstand" in w for w in r.json()["warnings"])


@pytest.mark.parametrize(("body", "message", "params"), [
    ({"family": "gullwing", "params": {"pins": 7}}, "gerade", ["pins"]),
    ({"family": "unbekannt"}, "Unbekannte Gehäusefamilie", []),
    ({"family": "chip", "params": {"preset": "R-9999"}}, "Unbekannte Vorlage", ["preset"]),
    ({"family": "do214", "params": {"A": 1e300}}, "unplausibel groß", ["A"]),
    ({"family": "gullwing", "params": {"pins": "acht"}}, "keine ganze Zahl", ["pins"]),
    ({"family": "nolead", "params": {"variant": "XYZ"}}, "nicht zulässig", ["variant"]),
    ({"family": "gullwing", "params": {"preset": "SOIC-8", "E1": [6.5, 6.6]}}, "Körperbreite E1", ["E1", "E"]),
])
def test_preview_errors_are_400_with_german_detail(api, body, message, params):
    """400 detail = {message, params}: the German text (unchanged) plus the parameters to mark in the UI."""
    r = api.post("/api/footprints/preview", json=body)
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert set(detail) == {"message", "params"}
    assert message in detail["message"]
    assert detail["params"] == params


def test_error_message_text_is_unchanged(api):
    """The structured detail carries exactly the generator's message (frontend: ApiError.message)."""
    from partforge.footprints import FootprintRequest, generate

    with pytest.raises(ValueError) as info:
        generate(FootprintRequest(family="gullwing", params={"pins": 7}))
    r = api.post("/api/footprints/preview", json={"family": "gullwing", "params": {"pins": 7}})
    assert r.json()["detail"]["message"] == str(info.value)
    r = api.post("/api/footprints/step", json={"family": "gullwing", "params": {"pins": 7}})
    assert r.status_code == 400 and r.json()["detail"] == {"message": str(info.value), "params": ["pins"]}


def test_preview_without_svg(api):
    r = api.post("/api/footprints/preview", json={"family": "gullwing", "params": {"preset": "SOIC-8"},
                                                   "with_svg": False})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["svg"] is None and data["spec"]["name"] == "SOIC127P600X175-8N" and data["calc"]["lands"]
    assert api.post("/api/footprints/preview", json={"family": "chip", "params": {"preset": "R-0603"}}).json()["svg"]


def test_preview_keeps_the_style_density_when_none_is_sent(api, fp_workspace):
    """with_svg must not turn the default density into an explicit one (the house style density wins)."""
    fp_workspace.settings.footprint.density = "L"
    r = api.post("/api/footprints/preview", json={"family": "chip", "params": {"preset": "R-0603"}, "with_svg": False})
    assert r.json()["spec"]["generator"]["density"] == "L"
    r = api.post("/api/footprints/preview", json={"family": "chip", "params": {"preset": "R-0603"}, "density": "M"})
    assert r.json()["spec"]["generator"]["density"] == "M"


def test_j_table_titles_are_german(api):
    land = api.post("/api/footprints/preview", json={"family": "gullwing", "params": {"preset": "SOIC-8"}}
                    ).json()["calc"]["lands"][0]
    assert land["table_key"] == "gullwing" and land["table_title"] == "Gull-Wing-/L-Anschlüsse, Raster > 0,625 mm"
    assert land["table_title_en"].startswith("Flat ribbon L and gull-wing leads")
    manual = api.post("/api/footprints/preview", json={
        "family": "gullwing", "params": {"preset": "SOIC-8"},
        "land_pattern": {"pad_width": 0.6, "pad_length": 1.5, "row_spacing": 5.4}}).json()["calc"]["lands"][0]
    assert manual["table_key"] == "manufacturer" and manual["table_title"] == "Herstellerempfehlung (Land Pattern)"


def test_families_carry_aliases_and_land_pattern_flag(api):
    data = {f["key"]: f for f in api.get("/api/footprints/families").json()}
    assert "soic" in data["gullwing"]["aliases"] and "tssop" in data["gullwing"]["aliases"]
    assert {"dfn", "qfn", "lfcsp"} <= set(data["nolead"]["aliases"])
    assert "sot363" in data["sc70"]["aliases"] and "sc75" in data["sot523"]["aliases"]
    assert all(f["key"] not in f["aliases"] for f in data.values())
    supported = {k for k, f in data.items() if f["supports_land_pattern"]}
    assert supported == set(data) - {"bga", "dip", "axial", "radial", "to92", "to220", "pin_header"}
    single = api.get("/api/footprints/families/soic").json()
    assert single["key"] == "gullwing" and single["supports_land_pattern"] is True and "soic" in single["aliases"]


def test_preview_validation_error_is_422(api):
    assert api.post("/api/footprints/preview", json={"family": "chip", "density": "X"}).status_code == 422


def test_step_download(api):
    r = api.post("/api/footprints/step", json={"family": "chip", "params": {"preset": "C-0805"}})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("model/step")
    assert r.headers["content-disposition"] == 'attachment; filename="CAPC2012X145N.step"'
    text = r.content.decode("ascii")
    assert text.startswith("ISO-10303-21;") and text.endswith("END-ISO-10303-21;\n")
    assert text.count("MANIFOLD_SOLID_BREP") == 3  # two terminals + body
    # with_3d=false in the request is ignored for the STEP export
    r = api.post("/api/footprints/step", json={"family": "chip", "params": {"preset": "C-0805"}, "with_3d": False})
    assert r.status_code == 200


def test_step_error(api):
    r = api.post("/api/footprints/step", json={"family": "gullwing", "params": {"pins": 7}})
    assert r.status_code == 400 and r.json()["detail"]["params"] == ["pins"]


def test_render_endpoint(api):
    spec = api.post("/api/footprints/preview", json={"family": "chip", "params": {"preset": "R-0603"}}).json()["spec"]
    r = api.post("/api/footprints/render", json={"spec": spec, "layers": ["top_copper"], "theme": "altium"})
    assert r.status_code == 200
    svg = r.json()["svg"]
    assert 'data-layer="top_copper"' in svg and 'data-layer="top_silk"' not in svg


def test_workspace_style_is_applied(api, fp_workspace):
    r = api.post("/api/footprints/preview", json={"family": "chip", "params": {"preset": "R-0603"}})
    assert r.json()["spec"]["name"] == "RES 0603_1608"  # house naming from the workspace
    # symbol style "anode = pin 1" -> the footprint marks the cathode at pad 2
    r = api.post("/api/footprints/preview", json={"family": "sod", "params": {"preset": "SOD-123"}})
    spec = r.json()["spec"]
    assert spec["generator"]["params"]["cathode_pad"] == "2"
    bars = [t for t in spec["tracks"] if t["layer"] == "top_silk" and abs(t["x1"] - t["x2"]) < 1e-9]
    assert bars and bars[0]["x1"] > 0
    # explicit request value wins
    r = api.post("/api/footprints/preview", json={"family": "sod", "params": {"preset": "SOD-123",
                                                                             "cathode_pad": "1"}})
    assert r.json()["spec"]["generator"]["params"]["cathode_pad"] == "1"


def test_step_even_if_3d_is_disabled_in_workspace(api, fp_workspace):
    fp_workspace.settings.footprint.generate_3d = False
    r = api.post("/api/footprints/preview", json={"family": "chip", "params": {"preset": "R-0603"}})
    assert r.json()["spec"]["bodies"] == []
    r = api.post("/api/footprints/step", json={"family": "chip", "params": {"preset": "R-0603"}})
    assert r.status_code == 200
    assert 'filename="RES 0603_1608.step"' in r.headers["content-disposition"]
