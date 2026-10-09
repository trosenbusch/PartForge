"""Family aliases imply their package variant; workspace conventions (style, diode pin 1) in generate()."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from partforge.app import create_app
from partforge.footprints import FootprintRequest, chip_request, effective_style, generate, preview
from partforge.footprints.families import registry, resolve
from partforge.workspace import FootprintStyle, Workspace, set_current

ALIASES = [(fam.info.key, alias, dict(implied)) for fam in registry().values()
           for alias, implied in fam.alias_params.items()]


@pytest.mark.parametrize(("family", "alias", "implied"), ALIASES, ids=[a for _, a, _ in ALIASES])
def test_every_alias_generates_the_variant_it_implies(family, alias, implied):
    spec = generate(FootprintRequest(family=alias), FootprintStyle())
    assert spec.family == family and spec.generator["family"] == family
    params = spec.generator["params"]
    for key, value in implied.items():
        if key == "preset":
            continue
        assert str(params[key]).lower() == str(value).lower(), (alias, key)


@pytest.mark.parametrize(("alias", "check"), [
    ("smb", lambda s: s.ipc_name == "DIOM5336X250N" and "SMB" in s.description),
    ("smc", lambda s: s.ipc_name == "DIOM7959X250N"),
    ("d2pak", lambda s: "D2PAK" in s.description and s.ipc_name.startswith("TO254P")),
    ("to263", lambda s: "D2PAK" in s.description),
    ("sot363", lambda s: len(s.pads) == 6),
    ("sot353", lambda s: len(s.pads) == 5),
    ("sod323", lambda s: s.ipc_name == "SOD2513X110N"),
    ("sod523", lambda s: s.ipc_name.startswith("SODFL")),
    ("tssop", lambda s: s.ipc_name.startswith("SOP65P640X120")),
    ("msop", lambda s: s.ipc_name == "SOP65P490X110-8N"),
    ("tqfp", lambda s: s.ipc_name.endswith("X120-32N") and "TQFP" in s.description),
    ("son", lambda s: s.ipc_name.startswith("SON65P300X300")),
    ("caprd", lambda s: s.ipc_name.startswith("CAPRD")),
    ("micromelf", lambda s: s.ipc_name == "RESMELF2211N"),
    ("sod80", lambda s: s.ipc_name.startswith("DIOMELF")),
    ("to220ac", lambda s: len(s.pads) == 2),
    ("dip28", lambda s: len(s.pads) == 28),
    ("indm", lambda s: s.ipc_name.startswith("INDM")),
    ("capacitor", lambda s: s.ipc_name.startswith("CAPC1608")),
])
def test_alias_examples_from_the_review(alias, check):
    assert check(generate(FootprintRequest(family=alias), FootprintStyle()))


def test_dfn_alias_gives_a_two_row_layout():
    params = {"pins": 8, "e": 0.5, "E": [1.85, 2.15], "D": [1.85, 2.15], "L": [0.2, 0.5], "b": [0.18, 0.3],
              "E2": [0.75, 1.0], "D2": [1.45, 1.7], "A": [0.5, 0.6]}
    pv = preview(FootprintRequest(family="dfn", params=params), FootprintStyle(), svg=False)
    signal = [p for p in pv.spec.pads if not p.thermal]
    assert len(signal) == 8 and len(pv.spec.pads) == 9
    assert all(abs(p.y) < abs(p.x) for p in signal), "DFN: keine Pads oben/unten"
    assert pv.spec.ipc_name == "DFN200X200X60-9N"
    assert not [i for i in pv.issues if i.severity == "error"]


def test_tssop_alias_with_datasheet_dimensions():
    spec = generate(FootprintRequest(family="tssop", params={
        "pins": 16, "e": 0.65, "E": [6.2, 6.6], "E1": [4.3, 4.5], "D": [4.9, 5.1], "L": [0.45, 0.75],
        "b": [0.19, 0.3], "A": [0.8, 1.2]}), FootprintStyle())
    assert spec.ipc_name == "SOP65P640X120-16N"
    assert spec.generator["params"]["variant"] == "TSSOP"


def test_alias_base_preset_follows_the_requested_pin_count():
    spec = generate(FootprintRequest(family="tssop", params={"pins": 20}), FootprintStyle())
    assert spec.generator["preset"] == "TSSOP-20"
    assert len(spec.pads) == 20


def test_sc75_alias_uses_its_preset():
    spec = generate(FootprintRequest(family="sc75"), FootprintStyle())
    assert spec.generator["preset"] == "SC-75"
    assert spec.generator["params"]["E1"] == {"min": 0.7, "nom": 0.8, "max": 0.9}


def test_explicit_preset_conflicting_with_alias_warns():
    pv = preview(FootprintRequest(family="sot363", params={"preset": "SOT-323"}), FootprintStyle(), svg=False)
    assert len(pv.spec.pads) == 3  # the explicitly chosen preset wins …
    assert any("passt nicht zum Gehäuse" in w for w in pv.warnings)  # … but the user is told


def test_resolve_returns_independent_copies():
    _, implied = resolve("dfn")
    implied["variant"] = "QFN"
    assert resolve("dfn")[1]["variant"] == "DFN"
    assert resolve("nolead")[1] == {}
    with pytest.raises(ValueError, match="Unbekannte Gehäusefamilie"):
        resolve("flux")


# --------------------------------------------------------------------------- workspace conventions


@pytest.fixture
def anode_workspace(tmp_path: Path):
    ws = Workspace.create(tmp_path / "Bibliothek", name="Dioden-Test")
    ws.settings.symbol.diode_pin1 = "anode"
    set_current(ws)
    yield ws
    set_current(None)


def _cathode_bar_x(spec) -> float:
    bars = [t for t in spec.tracks if t.layer == "top_silk" and abs(t.x1 - t.x2) < 1e-9]
    assert len(bars) == 1
    return bars[0].x1


def test_generate_applies_the_workspace_diode_convention(anode_workspace):
    spec = generate(FootprintRequest(family="sod", params={"preset": "SOD-123"}))
    assert spec.generator["params"]["cathode_pad"] == "2"
    assert _cathode_bar_x(spec) > 0
    assert spec.name == spec.ipc_name == "SOD3716X135RN"  # IPC "reverse pin order" marker
    led = generate(chip_request("LED", "0603"))
    assert led.generator["params"]["cathode_pad"] == "2" and led.ipc_name.endswith("RN")
    res = generate(chip_request("R", "0603"))
    assert "cathode_pad" not in res.generator["params"] and res.name == "RESC1608X50N"


def test_explicit_cathode_pad_and_keyword_win(anode_workspace):
    spec = generate(FootprintRequest(family="sod", params={"preset": "SOD-123", "cathode_pad": "1"}))
    assert spec.generator["params"]["cathode_pad"] == "1" and spec.name == "SOD3716X135N"
    spec = generate(FootprintRequest(family="sod", params={"preset": "SOD-123"}), diode_pin1="cathode")
    assert spec.generator["params"]["cathode_pad"] == "1"


def test_without_workspace_ipc_convention_and_keyword():
    set_current(None)
    assert generate(FootprintRequest(family="do214", params={"preset": "SMA"})).name == "DIOM5226X240N"
    reverse = generate(FootprintRequest(family="do214", params={"preset": "SMA"}), diode_pin1="anode")
    assert reverse.name == "DIOM5226X240RN" and _cathode_bar_x(reverse) > 0
    with pytest.raises(ValueError, match="Dioden-Konvention"):
        generate(FootprintRequest(family="sod"), diode_pin1="kathode")  # type: ignore[arg-type]


def test_house_name_marks_reversed_diodes(anode_workspace):
    style = FootprintStyle(naming="house")
    assert generate(FootprintRequest(family="sod", params={"preset": "SOD-123"}), style).name == "SOD-123 AK"
    spec = generate(FootprintRequest(family="sod", params={"preset": "SOD-123"}, density="L"), style)
    assert spec.name == "SOD-123 AK RF"


def test_style_none_uses_the_workspace_style(anode_workspace):
    anode_workspace.settings.footprint.naming = "house"
    anode_workspace.settings.footprint.silk_width_small = 0.12
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    assert spec.name == "RES 0603_1608"
    assert {t.width for t in spec.tracks if t.layer == "top_silk"} == {0.12}
    assert effective_style().naming == "house"
    assert effective_style(FootprintStyle()).naming == "ipc"  # an explicit style wins


def test_api_uses_the_generator_convention(anode_workspace):
    token = "alias-test"
    with TestClient(create_app(token=token), headers={"X-PartForge-Token": token}) as client:
        r = client.post("/api/footprints/preview", json={"family": "dfn"})
        assert r.status_code == 200, r.text
        assert len(r.json()["spec"]["pads"]) == 9
        r = client.post("/api/footprints/preview", json={"family": "smb"})
        assert r.json()["spec"]["generator"]["params"]["cathode_pad"] == "2"
        assert r.json()["spec"]["name"] == "DIOM5336X250RN"
