"""REST endpoints of the symbol generator (/api/symbols/...)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from partforge.symbols import SymbolRequest, generate


def test_kinds(bare_client) -> None:
    r = bare_client.get("/api/symbols/kinds")
    assert r.status_code == 200
    data = r.json()
    keys = [k["key"] for k in data]
    assert "resistor" in keys and "ic" in keys and len(keys) == len(set(keys)) >= 40
    resistor = next(k for k in data if k["key"] == "resistor")
    assert resistor["label"] == "Widerstand" and resistor["default_name"] == "Resistor"
    assert resistor["prefix"] == "R" and resistor["thumbnail_svg"] is None
    npn = next(k for k in data if k["key"] == "npn")
    pinmap = next(p for p in npn["params"] if p["name"] == "pinmap")
    assert pinmap["allow_custom"] and "EBC" in pinmap["options"] and pinmap["option_labels"]["BEC"].startswith("SOT-23")


def test_kinds_with_thumbnails(bare_client) -> None:
    r = bare_client.get("/api/symbols/kinds", params={"thumbnails": True, "theme": "light"})
    assert r.status_code == 200
    for kind in r.json():
        assert kind["thumbnail_svg"], kind["key"]
        ET.fromstring(kind["thumbnail_svg"])


def test_preview_standard_symbol(bare_client) -> None:
    r = bare_client.post("/api/symbols/preview", json={"kind": "npn", "params": {"pinmap": "EBC"}})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["spec"]["name"] == "NPN (EBC)"
    assert data["part"] == 1 and data["svgs"] == [data["svg"]]
    assert data["warnings"] == []
    ET.fromstring(data["svg"])
    pins = {p["designator"]: p["name"] for p in data["spec"]["pins"]}
    assert pins == {"1": "E", "2": "B", "3": "C"}


def test_preview_multi_part_and_theme(bare_client) -> None:
    r = bare_client.post(
        "/api/symbols/preview", json={"kind": "opamp_quad"}, params={"theme": "dark", "part": 5, "labels": False}
    )
    assert r.status_code == 200
    data = r.json()
    assert data["part"] == 5 and len(data["svgs"]) == 5
    assert 'data-part="5"' in data["svg"] and "pf-symbol-dark" in data["svg"]
    r = bare_client.post("/api/symbols/preview", json={"kind": "opamp_quad"}, params={"part": 9})
    assert r.status_code == 400 and "Teil 9" in r.json()["detail"]


def test_preview_ic_from_pins(bare_client) -> None:
    body = {
        "kind": "ic",
        "name": "TPS62130",
        "pins": [
            {"designator": "1", "name": "SW", "electrical": "power"},
            {"designator": "2", "name": "PG", "electrical": "open_collector"},
            {"designator": "3", "name": "FB", "electrical": "input"},
            {"designator": "4", "name": "AGND", "electrical": "power"},
            {"designator": "5", "name": "EN", "electrical": "input"},
            {"designator": "6", "name": "PVIN", "electrical": "power"},
            {"designator": "7", "name": "VOS", "electrical": "input", "hidden": True},
            {"designator": "17", "name": "EP", "electrical": "passive"},
        ],
    }
    r = bare_client.post("/api/symbols/preview", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    sides = {p["name"]: p["orientation"] for p in data["spec"]["pins"] if not p["hidden"]}
    assert sides["SW"] == "up" and sides["AGND"] == "down" and sides["PVIN"] == "left"
    assert any("Verborgene Pins" in w for w in data["warnings"])


def test_preview_errors(bare_client) -> None:
    r = bare_client.post("/api/symbols/preview", json={"kind": "warp_core"})
    assert r.status_code == 400 and "Unbekannter Symboltyp" in r.json()["detail"]
    r = bare_client.post("/api/symbols/preview", json={"kind": "connector", "params": {"pins": 5, "rows": "2"}})
    assert r.status_code == 400 and "gerade Anzahl" in r.json()["detail"]
    r = bare_client.post("/api/symbols/preview", json={"params": {}})
    assert r.status_code == 422  # kind missing
    r = bare_client.post("/api/symbols/preview", json={"kind": "resistor"}, params={"theme": "neon"})
    assert r.status_code == 422
    r = bare_client.post("/api/symbols/preview", json={"kind": "ic", "name": "X", "pins": []})
    assert r.status_code == 400 and "Pinliste" in r.json()["detail"]


def test_render_endpoint(bare_client) -> None:
    spec = generate(SymbolRequest(kind="opamp_dual"))
    r = bare_client.post("/api/symbols/render", json={"spec": spec.model_dump(mode="json"), "part": 2})
    assert r.status_code == 200, r.text
    data = r.json()
    assert len(data["svgs"]) == 3 and 'data-part="2"' in data["svg"] and data["warnings"] == []
    broken = spec.model_dump(mode="json")
    broken["pins"][0]["x"] = 15
    r = bare_client.post("/api/symbols/render", json={"spec": broken})
    assert r.status_code == 200 and any("10-mil-Raster" in w for w in r.json()["warnings"])
    r = bare_client.post("/api/symbols/render", json={"spec": spec.model_dump(mode="json"), "part": 7})
    assert r.status_code == 400


def test_auto_sides_endpoint(bare_client) -> None:
    pins = [
        {"designator": "1", "name": "VDD", "electrical": "power"},
        {"designator": "2", "name": "OUT", "electrical": "output", "side": "left"},
        {"designator": "3", "name": "GND"},
    ]
    r = bare_client.post("/api/symbols/auto-sides", json={"pins": pins})
    assert r.status_code == 200
    sides = {p["name"]: p["side"] for p in r.json()["pins"]}
    assert sides == {"VDD": "left", "OUT": "left", "GND": "bottom"}  # explicit side kept
    r = bare_client.post("/api/symbols/auto-sides", json={"pins": pins, "overwrite": True})
    assert {p["name"]: p["side"] for p in r.json()["pins"]}["OUT"] == "right"
    assert bare_client.post("/api/symbols/auto-sides", json={"pins": [{"name": "X"}]}).status_code == 422


@pytest.mark.parametrize(
    ("table", "values", "name"),
    [
        ("Capacitors", {"Polarized": "Ja"}, "Capacitor Polarized"),
        ("Transistors FET", {"Channel": "N", "Package": "SO-8"}, "NMOS (SSSGDDDD)"),
        ("Connectors", {"Pins": 10, "Rows": 2}, "Connector 2x05"),
    ],
)
def test_standard_for_match(bare_client, table: str, values: dict, name: str) -> None:
    r = bare_client.get("/api/symbols/standard-for", params={"table": table, "values": json.dumps(values)})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == name and data["request"]["kind"] and data["kind_label"]


def test_standard_for_no_match_and_errors(bare_client) -> None:
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Integrated Circuits"})
    assert r.status_code == 200
    data = r.json()
    assert data["request"] is None and data["name"] is None and data["kind"] is None
    assert data["needs_pinmap"] is False and data["pinmap_options"] == [] and data["messages"] == []
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Resistors", "values": "{kaputt"})
    assert r.status_code == 400 and "kein gültiges JSON" in r.json()["detail"]
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Resistors", "values": "[1, 2]"})
    assert r.status_code == 400 and "JSON-Objekt" in r.json()["detail"]
    assert bare_client.get("/api/symbols/standard-for").status_code == 422
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Resistors", "values": ""})
    assert r.status_code == 200 and r.json()["name"] == "Resistor"


def test_standard_for_ambiguous_package_asks_for_pin_map(bare_client) -> None:
    """Review finding: TO-92 transistors silently got the SOT-23 pin map."""
    values = {"Polarity": "NPN", "Package": "TO-92", "Manufacturer Part Number": "2N3904"}
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Transistors BJT", "values": json.dumps(values)})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["request"] is None and data["kind"] == "npn" and data["kind_label"] == "NPN-Transistor"
    assert data["needs_pinmap"] and {"EBC", "CBE"} <= set(data["pinmap_options"])
    assert data["package"] == "TO-92" and data["messages"]


def test_standard_for_with_pin_table_and_pads(bare_client) -> None:
    values = json.dumps({"Polarity": "NPN", "Package": "TO-92"})
    pins = json.dumps([{"designator": d, "name": n} for d, n in (("1", "E"), ("2", "B"), ("3", "C"))])
    params = {"table": "Transistors BJT", "values": values, "pins": pins}
    r = bare_client.get("/api/symbols/standard-for", params=params)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "NPN (EBC)" and data["source"] == "pins" and data["request"]["params"]["pinmap"] == "EBC"
    r = bare_client.get(
        "/api/symbols/standard-for",
        params={
            "table": "Transistors FET",
            "values": json.dumps({"Channel": "N", "Package": "DPAK"}),
            "pads": "1,2,3,4",
        },
    )
    assert r.status_code == 200 and r.json()["name"] == "NMOS (GDSD)"
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Transistors BJT", "pins": "{kaputt"})
    assert r.status_code == 400 and "pins" in r.json()["detail"]
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Transistors BJT", "pins": '{"a": 1}'})
    assert r.status_code == 400 and "JSON-Array" in r.json()["detail"]
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Transistors BJT", "pins": '[{"name": "B"}]'})
    assert r.status_code == 400 and "ungültige Pins" in r.json()["detail"]


def test_standard_for_post_body(bare_client) -> None:
    body = {
        "table": "Amplifiers",
        "values": {"Channels": 1, "Package": "SOT-23-5"},
        "pins": [
            {"designator": "1", "name": "+IN"},
            {"designator": "2", "name": "V-"},
            {"designator": "3", "name": "-IN"},
            {"designator": "4", "name": "OUT"},
            {"designator": "5", "name": "V+"},
        ],
    }
    r = bare_client.post("/api/symbols/standard-for", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Op-Amp (SOT23-5U)" and data["request"]["params"]["pinmap"] == "SOT23-5U"
    body["pins"] = []
    data = bare_client.post("/api/symbols/standard-for", json=body).json()
    assert data["request"] is None and data["needs_pinmap"] and data["kind"] == "opamp"
    assert bare_client.post("/api/symbols/standard-for", json={"values": {}}).status_code == 422


def test_standard_for_connector_beyond_row_limit_is_no_match(bare_client) -> None:
    """Review repro r06: 120 pins in one row answered 400 instead of 'no match'."""
    r = bare_client.get("/api/symbols/standard-for", params={"table": "Connectors", "values": '{"Pins": 120}'})
    assert r.status_code == 200 and r.json()["request"] is None and r.json()["messages"]
    params = {"table": "Connectors", "values": '{"Pins": 120, "Rows": 2}'}
    r = bare_client.get("/api/symbols/standard-for", params=params)
    assert r.status_code == 200 and r.json()["name"] == "Connector 2x60"


def test_render_endpoint_rejects_broken_specs(bare_client) -> None:
    """Review repro r06: list text_positions (500), 20000 parts (13 MB), NaN coordinates (200)."""
    spec = generate(SymbolRequest(kind="resistor")).model_dump(mode="json")
    spec["generator"]["text_positions"] = [1, 2]
    r = bare_client.post("/api/symbols/render", json={"spec": spec})
    assert r.status_code == 200 and "label-designator" in r.json()["svg"]
    spec["generator"]["text_positions"] = {"designator": {"x": 0, "y": 0, "justify": "foo_bar"}, "comment": 5}
    assert bare_client.post("/api/symbols/render", json={"spec": spec}).status_code == 200
    many = generate(SymbolRequest(kind="resistor")).model_dump(mode="json")
    many["part_count"] = 20000
    r = bare_client.post("/api/symbols/render", json={"spec": many})
    assert r.status_code == 400 and "Teileanzahl" in r.json()["detail"]
    nan = generate(SymbolRequest(kind="resistor")).model_dump(mode="json")
    nan["graphics"][0]["x1"] = float("nan")
    r = bare_client.post(
        "/api/symbols/render", content=json.dumps({"spec": nan}), headers={"content-type": "application/json"}
    )
    assert r.status_code == 400 and "Koordinaten" in r.json()["detail"]


@pytest.mark.parametrize(("parts", "status"), [(2.0, 200), ("2", 200), ("2,0", 200), (2.5, 400), (True, 400)])
def test_preview_ic_parts_number_formats(bare_client, parts: object, status: int) -> None:
    pins = [{"designator": str(i), "name": f"IO{i}", "electrical": "io"} for i in range(1, 9)]
    pins += [{"designator": "9", "name": "VDD", "electrical": "power"}, {"designator": "10", "name": "GND"}]
    body = {"kind": "ic", "name": "X", "pins": pins, "params": {"parts": parts}}
    r = bare_client.post("/api/symbols/preview", json=body)
    assert r.status_code == status, r.text
    if status == 200:
        assert r.json()["spec"]["part_count"] == 2


def test_endpoints_use_workspace_style(bare_client, tmp_path) -> None:
    from partforge.workspace import Workspace, WorkspaceSettings, set_current

    settings = WorkspaceSettings()
    settings.symbol.resistor_style = "ansi"
    settings.symbol.diode_pin1 = "anode"
    ws = Workspace.create(tmp_path / "Lib", settings=settings)
    set_current(ws)
    try:
        r = bare_client.post("/api/symbols/preview", json={"kind": "resistor"})
        kinds = {g["kind"] for g in r.json()["spec"]["graphics"]}
        assert kinds == {"line"}  # ANSI zigzag
        r = bare_client.post("/api/symbols/preview", json={"kind": "diode"})
        assert {p["designator"]: p["name"] for p in r.json()["spec"]["pins"]}["1"] == "A"
        assert r.json()["spec"]["name"] == "Diode (AK)"  # anode-first is never called plain "Diode"
        r = bare_client.get("/api/symbols/standard-for", params={"table": "Diodes", "values": "{}"})
        assert r.json()["name"] == "Diode (AK)"
        defaults = {k["key"]: k["default_name"] for k in bare_client.get("/api/symbols/kinds").json()}
        assert defaults["diode"] == "Diode (AK)" and defaults["led"] == "LED (AK)"
        assert defaults["resistor"] == "Resistor" and defaults["tvs_bi"] == "TVS Diode Bidirectional"
    finally:
        set_current(None)


def test_token_required(bare_client) -> None:
    from fastapi.testclient import TestClient

    from partforge.app import create_app

    anonymous = TestClient(create_app(token="secret"))
    assert anonymous.get("/api/symbols/kinds").status_code == 401


# --------------------------------------------------------------------------- svg=false, thumbnails, labels


def test_preview_without_svg(bare_client) -> None:
    r = bare_client.post("/api/symbols/preview", json={"kind": "opamp_quad"}, params={"svg": False, "part": 3})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["svg"] is None and data["svgs"] == [] and data["part"] == 3
    assert data["spec"]["name"] == "Op-Amp Quad" and data["spec"]["part_count"] == 5
    # an impossible part is still a 400, with or without SVG
    for svg in (True, False):
        r = bare_client.post("/api/symbols/preview", json={"kind": "opamp_quad"}, params={"svg": svg, "part": 9})
        assert r.status_code == 400 and "Teil 9" in r.json()["detail"]


def test_kind_thumbnails_use_sans_font_and_constant_strokes(bare_client) -> None:
    data = bare_client.get("/api/symbols/kinds", params={"thumbnails": True}).json()
    for kind in data:
        svg = kind["thumbnail_svg"]
        root = ET.fromstring(svg)
        assert "sans-serif" in root.get("font-family", ""), kind["key"]
        stroked = [el for el in root.iter() if el.get("stroke") not in (None, "none")]
        assert stroked, kind["key"]
        assert all(el.get("vector-effect") == "non-scaling-stroke" for el in stroked), kind["key"]
        assert {el.get("stroke-width") for el in stroked} == {"1.25"}, kind["key"]


def test_diode_pinmap_option_refers_to_naming_rules(bare_client) -> None:
    data = bare_client.get("/api/symbols/kinds").json()
    for key in ("diode", "zener", "schottky", "led"):
        kind = next(k for k in data if k["key"] == key)
        pinmap = next(p for p in kind["params"] if p["name"] == "pinmap")
        assert "Namensregeln" in pinmap["option_labels"]["auto"], key
        assert "Namensregeln" in (pinmap["help"] or ""), key
        assert "Diode Pin 1" not in pinmap["option_labels"]["auto"]
