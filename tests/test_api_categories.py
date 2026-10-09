"""API: /categories, /category-templates, /field-kinds."""
from __future__ import annotations

from urllib.parse import quote

from fastapi.testclient import TestClient

from partforge.db.templates import CATEGORIES


def test_list_get_templates_and_kinds(client: TestClient) -> None:
    r = client.get("/api/categories")
    assert r.status_code == 200
    data = r.json()
    assert [c["table"] for c in data] == [t.table for t in CATEGORIES]
    assert all(c["part_count"] == 0 for c in data)
    assert data[0]["fields"][0]["column"] == "Part Number" and data[0]["fields"][0]["protected"] is True
    assert all(c["part_count"] is None for c in client.get("/api/categories", params={"counts": False}).json())
    one = client.get(f"/api/categories/{quote('Transistors BJT')}")
    assert one.status_code == 200 and one.json()["label"] == "Bipolartransistoren" and one.json()["part_count"] == 0
    missing = client.get("/api/categories/Gibtsnicht")
    assert missing.status_code == 404 and "nicht gefunden" in missing.json()["detail"]
    templates = client.get("/api/category-templates").json()
    assert {t["table"] for t in templates} >= {"Resistors", "Mechanical"}
    kinds = client.get("/api/field-kinds").json()
    assert {k["kind"] for k in kinds} == {"text", "quantity", "range", "enum", "bool", "int", "url", "path", "date"}


def test_create_category(client: TestClient) -> None:
    body = {"table": "Sensors", "label": "Sensoren", "prefix": "u", "icon": "thermometer", "color": "#10B981",
            "description_template": "SENSOR {Sensor Type}", "value_field": "Manufacturer Part Number",
            "comment_template": "{Manufacturer Part Number}",
            "fields": [{"column": "Sensor Type", "label": "Typ", "kind": "enum", "options": ["Temperatur", "Druck"]},
                       {"column": "Accuracy (typ)", "label": "Genauigkeit", "kind": "quantity", "unit": "%"}]}
    r = client.post("/api/categories", json=body)
    assert r.status_code == 201, r.text
    cat = r.json()
    assert cat["prefix"] == "U" and cat["fields"][-1]["column"] == "Accuracy (typ)" and cat["builtin"] is False
    assert client.post("/api/categories", json=body).status_code == 409
    bad = client.post("/api/categories", json={**body, "table": "Sensöre"})
    assert bad.status_code == 400 and "Tabellenname" in bad.json()["detail"]
    bad_template = client.post("/api/categories", json={**body, "table": "Sensors2", "description_template": "{Nope}"})
    assert bad_template.status_code == 400 and "unbekannte Felder" in bad_template.json()["detail"]
    assert client.post("/api/categories", json={"label": "ohne Tabelle"}).status_code == 422


def test_create_category_from_template(client: TestClient) -> None:
    r = client.post("/api/categories", json={"table": "Resistors THT", "label": "Widerstände (bedrahtet)", "template": "resistors",
                                             "fields": [{"column": "Lead Spacing", "label": "Rastermaß", "kind": "quantity", "unit": "mm"}]})
    assert r.status_code == 201, r.text
    cat = r.json()
    columns = [f["column"] for f in cat["fields"]]
    assert "Resistance" in columns and columns[-1] == "Lead Spacing" and cat["value_field"] == "Resistance"
    assert cat["comment_template"] == "{Resistance:rkm}" and cat["prefix"] == "R" and cat["builtin"] is True
    assert client.post("/api/categories", json={"table": "X", "template": "Gibtsnicht"}).status_code == 404


def test_update_and_delete_category(client: TestClient) -> None:
    r = client.patch("/api/categories/Resistors", json={"label": "Widerstände SMD", "altium_enabled": False})
    assert r.status_code == 200 and r.json()["label"] == "Widerstände SMD" and r.json()["altium_enabled"] is False
    assert client.patch("/api/categories/Resistors", json={"color": "rot"}).status_code == 400
    assert client.patch("/api/categories/Gibtsnicht", json={"label": "x"}).status_code == 404
    renamed = client.patch("/api/categories/Mechanical", json={"table": "Mechanics"})
    assert renamed.status_code == 200 and renamed.json()["table"] == "Mechanics"
    d = client.delete("/api/categories/Mechanics")
    assert d.status_code == 200 and d.json()["deleted"] is True and d.json()["backup"].startswith("PartForge_")
    assert client.get("/api/categories/Mechanics").status_code == 404
    assert client.delete("/api/categories/Mechanics").status_code == 404


def test_field_endpoints(client: TestClient) -> None:
    r = client.post("/api/categories/Resistors/fields", json={"column": "Case/Package", "label": "Bauform"})
    assert r.status_code == 201 and r.json()["fields"][-1]["column"] == "Case/Package"
    assert client.post("/api/categories/Resistors/fields", json={"column": "case/package", "label": "x"}).status_code == 409
    assert client.post("/api/categories/Resistors/fields", json={"column": "Rated [UL]", "label": "x"}).status_code == 400
    assert client.post("/api/categories/Resistors/fields", json={"column": "x", "label": "x", "kind": "farbe"}).status_code == 422
    # column names with "/" work as path parameters
    r = client.patch("/api/categories/Resistors/fields/Case/Package", json={"column": "Case Package", "label": "Gehäuse (Altium)"})
    assert r.status_code == 200, r.text
    assert any(f["column"] == "Case Package" and f["label"] == "Gehäuse (Altium)" for f in r.json()["fields"])
    assert client.patch("/api/categories/Resistors/fields/Gibtsnicht", json={"label": "x"}).status_code == 404
    assert client.patch("/api/categories/Resistors/fields/Library Ref", json={"column": "Symbol"}).status_code == 400
    order = client.post("/api/categories/Resistors/fields/reorder", json={"columns": ["Case Package", "Resistance"]})
    assert order.status_code == 200 and [f["column"] for f in order.json()["fields"]][:3] == ["Part Number", "Case Package", "Resistance"]
    assert client.post("/api/categories/Resistors/fields/reorder", json={"columns": ["Nope"]}).status_code == 404
    removed = client.delete("/api/categories/Resistors/fields/Case Package")
    assert removed.status_code == 200 and all(f["column"] != "Case Package" for f in removed.json()["fields"])
    protected = client.delete("/api/categories/Resistors/fields/Part Number")
    assert protected.status_code == 400 and "Altium" in protected.json()["detail"]


def test_requires_open_library(bare_client: TestClient) -> None:
    for method, url in (("get", "/api/categories"), ("get", "/api/categories/Resistors"), ("delete", "/api/categories/Resistors"),
                        ("get", "/api/category-templates")):
        r = getattr(bare_client, method)(url)
        assert r.status_code == 409 and "keine Bibliothek" in r.json()["detail"]


def test_only_the_comment_is_shown_on_the_schematic(client: TestClient) -> None:
    """Regression (altium-e2e.md §6.1, VERIFIED): the Comment was hidden on placed parts while the value
    fields were visible – the house style shows only the Comment, which carries the value."""
    for source in (client.get("/api/categories").json(), client.get("/api/category-templates").json()):
        for cat in source:
            visible = [f["column"] for f in cat["fields"] if f["show_on_schematic"]]
            assert visible == ["Comment"], (cat["table"], visible)
    templates = {c["table"]: c["comment_template"] for c in client.get("/api/categories").json()}
    assert templates["Capacitors"] == "{Capacitance:rkm} {Voltage}" and templates["Inductors"] == "{Inductance:rkm}"
    assert templates["Resistors"] == "{Resistance:rkm}" and templates["Fuses"] == "{Current Rating}"
    created = client.post("/api/categories", json={"table": "Sensors", "label": "Sensoren", "fields": [
        {"column": "Sensor Type", "label": "Typ"}]})
    assert created.status_code == 201, created.text
    assert [f["column"] for f in created.json()["fields"] if f["show_on_schematic"]] == ["Comment"]
