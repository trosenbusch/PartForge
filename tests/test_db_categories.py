"""Category and field DDL: create/update/delete, awkward column names, protection, callbacks."""
from __future__ import annotations

import sqlite3

import pytest

from partforge.db import audit, backup, categories, parts, views
from partforge.db.errors import CategoryNotFound, ConflictError, FieldNotFound, SchemaError
from partforge.db.models import CategoryDef, FieldDef, PartFilter, SavedView, SortSpec
from partforge.workspace import Workspace


def columns(ws: Workspace, table: str) -> list[str]:
    conn = sqlite3.connect(str(ws.sqlite_path))
    try:
        return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
    finally:
        conn.close()


def new_category(**kw) -> CategoryDef:
    data = {"table": "Sensors", "label": "Sensoren", "prefix": "U", "icon": "thermometer", "color": "#10B981",
            "description_template": "SENSOR {Sensor Type} {Package}", "comment_template": "{Manufacturer Part Number}",
            "value_field": "Manufacturer Part Number",
            "fields": [FieldDef(column="Sensor Type", label="Sensortyp", kind="enum", options=["Temperatur", "Druck"]),
                       FieldDef(column="Accuracy (typ)", label="Genauigkeit", kind="quantity", unit="%"),
                       FieldDef(column="Case/Package", label="Bauform (Altium-Parameter)")]}
    data.update(kw)
    return CategoryDef.model_validate(data)


def test_get_category_case_insensitive_and_missing(workspace: Workspace) -> None:
    assert categories.get_category("resistors").table == "Resistors"
    with pytest.raises(KeyError):
        categories.get_category("Gibt es nicht")
    with pytest.raises(CategoryNotFound, match="nicht gefunden"):
        categories.get_category("Gibt es nicht")


def test_create_category_with_awkward_columns(workspace: Workspace) -> None:
    cat = categories.create_category(new_category())
    assert cat.table == "Sensors" and not cat.builtin
    cols = columns(workspace, "Sensors")
    assert cols[0] == "Part Number"
    assert {"Accuracy (typ)", "Case/Package", "Sensor Type", "Library Ref", "PF Created"} <= set(cols)
    with pytest.raises(SchemaError, match="unzulässige Zeichen"):
        categories.create_category(new_category(table="Sensors Two", fields=[FieldDef(column="Accuracy (typ.)", label="x")]))
    assert columns(workspace, "Sensors Two") == []


def test_column_name_validation(workspace: Workspace) -> None:
    for bad in ("Accuracy (typ.)", "Rated [UL]", "Größe", "a=b", "x|y", "{x}", "Tab;le", " ", "PF Intern", "-x"):
        with pytest.raises(SchemaError):
            categories.validate_column_name(bad)
    assert categories.validate_column_name("  RDS(on)  max ") == "RDS(on) max"
    assert categories.validate_column_name("Case/Package") == "Case/Package"
    assert categories.validate_column_name("Supplier Part Number 2") == "Supplier Part Number 2"


def test_table_name_validation(workspace: Workspace) -> None:
    for bad in ("", "pf_secret", "sqlite_x", "Widerstände", "1abc", "a/b", "x" * 65):
        with pytest.raises(SchemaError):
            categories.validate_table_name(bad)
    with pytest.raises(ConflictError):
        categories.validate_table_name("resistors", existing=["Resistors"])
    assert categories.validate_table_name("  Power  Modules ") == "Power Modules"


def test_create_category_full(workspace: Workspace) -> None:
    cat = categories.create_category(new_category(fields=[
        FieldDef(column="Sensor Type", label="Sensortyp", kind="enum", options=["Temperatur", "Druck", "Druck"]),
        FieldDef(column="Accuracy (typ)", label="Genauigkeit", kind="quantity", unit="%"),
        FieldDef(column="Case/Package", label="Bauform (Altium)", unit="mm"),  # unit dropped for text
        FieldDef(column="Library Ref", label="ignoriert (Standardfeld)"),
    ]))
    names = [f.column for f in cat.fields]
    assert names[:3] == ["Part Number", "Manufacturer", "Manufacturer Part Number"]
    assert names[-3:] == ["Sensor Type", "Accuracy (typ)", "Case/Package"]
    assert names.count("Library Ref") == 1 and cat.field("Library Ref").label == "Symbol"  # type: ignore[union-attr]
    assert cat.field("Sensor Type").options == ["Temperatur", "Druck"]  # type: ignore[union-attr]
    assert cat.field("Case/Package").unit is None  # type: ignore[union-attr]
    cols = columns(workspace, "Sensors")
    assert {"Accuracy (typ)", "Case/Package", "Sensor Type"} <= set(cols)
    created = parts.create_part("Sensors", {"Manufacturer": "TI", "Manufacturer Part Number": "TMP117AIDRVR",
                                           "Sensor Type": "temperatur", "Accuracy (typ)": "0.1", "Case/Package": "WSON-6",
                                           "Library Ref": "TMP117", "Footprint Ref": "SON65P200X200X80-7N"})
    assert created["Sensor Type"] == "Temperatur" and created["Accuracy (typ)"] == "±0.1%"
    assert created["Description"] == "SENSOR Temperatur" and created["Comment"] == "TMP117AIDRVR"
    assert created["Value"] == "TMP117AIDRVR"
    entries = audit.recent(5, table="Sensors", actions=["schema"])
    assert entries and entries[0].changes["op"] == "create_category"


def test_create_category_errors(workspace: Workspace) -> None:
    with pytest.raises(ConflictError):
        categories.create_category(new_category(table="Resistors"))
    with pytest.raises(SchemaError, match="unbekannte Felder"):
        categories.create_category(new_category(description_template="X {Nope}"))
    with pytest.raises(SchemaError, match="Wertfeld"):
        categories.create_category(new_category(value_field="Nope"))
    with pytest.raises(SchemaError, match="Präfix"):
        categories.create_category(new_category(prefix="U1"))
    with pytest.raises(SchemaError, match="Farbe"):
        categories.create_category(new_category(color="green"))
    with pytest.raises(SchemaError):
        categories.create_category(new_category(fields=[FieldDef(column="Bad.Name", label="x")]))
    assert "Sensors" not in {c.table for c in categories.list_categories(with_counts=False)}
    assert columns(workspace, "Sensors") == []  # the failed transactions left no table behind


def test_update_category(workspace: Workspace) -> None:
    cat = categories.update_category("Resistors", {"label": " Widerstände SMD ", "icon": "zap", "color": "#123456",
                                                   "comment_template": "{Resistance:si}", "prefix": "r"})
    assert cat.label == "Widerstände SMD" and cat.icon == "zap" and cat.prefix == "R"
    with pytest.raises(SchemaError, match="unbekannte Felder"):
        categories.update_category("Resistors", {"description_template": "{Gibtsnicht}"})
    with pytest.raises(SchemaError, match="Unbekannte Eigenschaften"):
        categories.update_category("Resistors", {"foo": 1})
    with pytest.raises(SchemaError, match="Felder"):
        categories.update_category("Resistors", {"fields": []})
    with pytest.raises(SchemaError, match="Ungültige Angaben"):
        categories.update_category("Resistors", {"sort_order": "viel"})
    unchanged = categories.update_category("Resistors", {"label": "Widerstände SMD"})
    assert unchanged.label == "Widerstände SMD"
    assert categories.update_category("Resistors", {"altium_enabled": False}).altium_enabled is False


def test_rename_table_only_when_empty(workspace: Workspace) -> None:
    views.create_view(SavedView(name="Alle", table="Mechanical"))
    renamed = categories.update_category("Mechanical", {"table": "Mechanics"})
    assert renamed.table == "Mechanics"
    assert columns(workspace, "Mechanics") and not columns(workspace, "Mechanical")
    assert renamed.fields and renamed.field("Mechanical Type") is not None
    assert views.list_views("Mechanics")[0].table == "Mechanics"
    parts.create_part("Mechanics", {"Part Number": "MH-1", "Manufacturer": "x", "Manufacturer Part Number": "MH-1",
                                    "Mechanical Type": "Fiducial", "Library Ref": "FID", "Footprint Ref": "FID1"})
    with pytest.raises(ConflictError, match="nicht umbenannt"):
        categories.update_category("Mechanics", {"table": "Mechanical"})


def test_delete_category_makes_backup(workspace: Workspace) -> None:
    parts.create_part("Fuses", {"Part Number": "F1", "Manufacturer": "x", "Manufacturer Part Number": "F1",
                                "Protection Type": "Sicherung", "Library Ref": "FUSE", "Footprint Ref": "FUSC1608X55N"})
    name = categories.delete_category("Fuses")
    assert name and name.startswith("PartForge_") and "vor_loeschen_Fuses" in name
    assert any(b["name"] == name for b in backup.list_backups())
    assert not columns(workspace, "Fuses")
    with pytest.raises(KeyError):
        categories.get_category("Fuses")
    assert categories.delete_category("Mechanical", backup=False) is None


def test_add_update_remove_field(workspace: Workspace) -> None:
    cat = categories.add_field("Resistors", FieldDef(column="Pulse Load", label="Impulsbelastbarkeit", kind="quantity", unit="W"))
    assert cat.fields[-1].column == "Pulse Load"
    assert "Pulse Load" in columns(workspace, "Resistors")
    with pytest.raises(ConflictError):
        categories.add_field("Resistors", FieldDef(column="pulse load", label="x"))
    with pytest.raises(SchemaError):
        categories.add_field("Resistors", FieldDef(column="Pulse.Load", label="x"))
    with pytest.raises(SchemaError, match="Höchstlänge"):
        categories.add_field("Resistors", FieldDef(column="Long", label="x", length=-1))
    with pytest.raises(SchemaError, match="Höchstlänge"):
        categories.add_field("Resistors", FieldDef(column="Long", label="x", length=categories.MAX_SOFT_LENGTH + 1))
    long_field = categories.add_field("Resistors", FieldDef(column="Long Text", label="Langtext", length=2000))
    assert long_field.field("Long Text").length == 2000  # type: ignore[union-attr]
    conn = sqlite3.connect(str(workspace.sqlite_path))
    try:
        types = {r[1]: r[2] for r in conn.execute('PRAGMA table_info("Resistors")')}
    finally:
        conn.close()
    # TEXT regardless of the soft limit (Altium truncates VARCHAR(n) – ARCHITEKTUR §4)
    assert types["Long Text"] == "TEXT" and types["Pulse Load"] == "TEXT"

    upd = categories.update_field("Resistors", "pulse load", {"label": "Pulslast", "kind": "quantity", "unit": "W",
                                                              "show_on_schematic": True})
    f = upd.field("Pulse Load")
    assert f is not None and f.label == "Pulslast" and f.show_on_schematic
    # the length is a soft limit and can be changed (0 = unlimited, None = default)
    assert categories.update_field("Resistors", "Pulse Load", {"length": 100}).field("Pulse Load").length == 100  # type: ignore[union-attr]
    assert categories.update_field("Resistors", "Pulse Load", {"length": 0}).field("Pulse Load").length == 0  # type: ignore[union-attr]
    assert categories.update_field("Resistors", "Pulse Load", {"length": None}).field("Pulse Load").length is None  # type: ignore[union-attr]
    assert categories.update_field("Resistors", "Library Ref", {"length": 64}).field("Library Ref").length == 64  # type: ignore[union-attr]
    with pytest.raises(SchemaError, match="Unbekannte Feldeigenschaften"):
        categories.update_field("Resistors", "Pulse Load", {"common": True})
    with pytest.raises(FieldNotFound):
        categories.update_field("Resistors", "Nope", {"label": "x"})

    removed = categories.remove_field("Resistors", "Pulse Load")
    assert removed.field("Pulse Load") is None
    assert "Pulse Load" not in columns(workspace, "Resistors")
    assert any("vor_feld_entfernen_Resistors" in b["name"] for b in backup.list_backups())


def test_rename_field_updates_templates_and_views(workspace: Workspace) -> None:
    categories.add_field("Resistors", FieldDef(column="Series", label="Serie"))
    categories.update_category("Resistors", {"description_template": "RES {Series} {Resistance:rkm}"})
    view = views.create_view(SavedView(name="Serie", table="Resistors", columns=["Part Number", "Series"],
                                       filters=[PartFilter(column="Series", op="eq", value="RC")],
                                       sort=[SortSpec(column="Series")]))
    global_view = views.create_view(SavedView(name="Global", columns=["Series"]))  # other categories may have "Series"
    parts.create_part("Resistors", {"Manufacturer": "YAGEO", "Manufacturer Part Number": "RC0603FR-0710KL", "Series": "RC",
                                    "Resistance": "10k", "Tolerance": "1", "Power": "0.1", "Library Ref": "RES",
                                    "Footprint Ref": "RESC1608X55N"})
    cat = categories.update_field("Resistors", "Series", {"column": "Product Series"})
    assert cat.field("Product Series") is not None and cat.field("Series") is None
    assert cat.description_template == "RES {Product Series} {Resistance:rkm}"
    assert parts.get_part("Resistors", "RC0603FR-0710KL")["Product Series"] == "RC"  # type: ignore[index]
    renamed_view = views.get_view(view.id or 0)
    assert renamed_view.columns == ["Part Number", "Product Series"]
    assert renamed_view.filters[0].column == "Product Series" and renamed_view.sort[0].column == "Product Series"
    assert views.get_view(global_view.id or 0).columns == ["Series"]
    with pytest.raises(ConflictError):
        categories.update_field("Resistors", "Product Series", {"column": "Resistance"})
    # removing the field strips it from templates and views
    cat = categories.remove_field("Resistors", "Product Series", backup=False)
    assert cat.description_template == "RES {Resistance:rkm}"
    assert views.get_view(view.id or 0).columns == ["Part Number"]


def test_protected_fields(workspace: Workspace) -> None:
    for column in ("Part Number", "Library Ref", "Footprint Ref", "Footprint Path 2", "PF Created"):
        with pytest.raises(SchemaError):
            categories.remove_field("Resistors", column)
    with pytest.raises(SchemaError, match="umbenannt"):
        categories.update_field("Resistors", "Library Ref", {"column": "Symbol"})
    with pytest.raises(SchemaError, match="umbenannt"):
        categories.update_field("Resistors", "Manufacturer", {"column": "Maker"})  # common fields keep their names
    with pytest.raises(SchemaError, match="geschützten"):
        categories.update_field("Resistors", "Library Ref", {"kind": "enum"})
    with pytest.raises(SchemaError, match="Pflichtfeld"):
        categories.update_field("Resistors", "Part Number", {"required": False})
    cat = categories.update_field("Resistors", "Library Ref", {"label": "Schaltplansymbol", "grid_width": 200})
    assert cat.field("Library Ref").label == "Schaltplansymbol"  # type: ignore[union-attr]
    # a common but unprotected field can be removed
    cat = categories.remove_field("Resistors", "RoHS", backup=False)
    assert cat.field("RoHS") is None


def test_value_field_removed_with_field(workspace: Workspace) -> None:
    cat = categories.remove_field("Oscillators", "Frequency", backup=False)
    assert cat.value_field is None and cat.comment_template == ""
    assert "{Frequency}" not in cat.description_template
    assert "{Frequency Tolerance}" in cat.description_template  # other placeholders stay


def test_removing_field_drops_glued_template_text(workspace: Workspace) -> None:
    """Regression: "{Channels}CH" must not leave an orphaned "CH" in the description."""
    cat = categories.remove_field("Amplifiers", "Channels", backup=False)
    assert cat.description_template == "IC OPAMP {GBW} {Slew Rate} {Package}"
    cat = categories.remove_field("Data Converters", "Resolution", backup=False)
    assert "BIT" not in cat.description_template and "{Sample Rate}" in cat.description_template
    row = parts.create_part("Amplifiers", {"Part Number": "OPA1", "Manufacturer": "TI", "GBW": "1MHz", "Package": "SOIC-8",
                                           "Library Ref": "OPAMP", "Footprint Ref": "SOIC127P600X175-8N"})
    assert row["Description"] == "IC OPAMP 1MHz SOIC-8"
    # a token with another placeholder keeps that placeholder (and its own decoration)
    categories.add_field("Amplifiers", FieldDef(column="Vmin", label="Vmin", kind="quantity", unit="V"))
    categories.add_field("Amplifiers", FieldDef(column="Vmax", label="Vmax", kind="quantity", unit="V"))
    categories.update_category("Amplifiers", {"description_template": "OPAMP {Vmin}..{Vmax} {Manufacturer Part Number}"})
    cat = categories.remove_field("Amplifiers", "Vmin", backup=False)
    assert cat.description_template == "OPAMP ..{Vmax} {Manufacturer Part Number}"
    assert categories._strip_placeholders("A {x}B {Manufacturer Part Number}", "x") == "A {Manufacturer Part Number}"
    assert categories._strip_placeholders("", "x") == ""


def test_case_only_table_rename(workspace: Workspace) -> None:
    """Regression: SQLite compares table names case-insensitively; renaming only the case works."""
    views.create_view(SavedView(name="Alle", table="Mechanical"))
    cat = categories.update_category("Mechanical", {"table": "MECHANICAL"})
    assert cat.table == "MECHANICAL" and len(cat.fields) > 10
    assert "MECHANICAL" in {c.table for c in categories.list_categories(with_counts=False)}
    assert columns(workspace, "MECHANICAL")[0] == "Part Number"
    assert views.list_views("MECHANICAL")[0].table == "MECHANICAL"
    conn = sqlite3.connect(str(workspace.sqlite_path))
    try:
        names = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        indexes = [r[0] for r in conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='MECHANICAL'")]
    finally:
        conn.close()
    assert "MECHANICAL" in names and "Mechanical" not in names and not [n for n in names if n.startswith("pf_tmp")]
    assert any("COLLATE NOCASE" in (sql or "") for sql in indexes)
    parts.create_part("MECHANICAL", {"Part Number": "MH-2", "Manufacturer": "x", "Manufacturer Part Number": "MH-2",
                                     "Mechanical Type": "Fiducial", "Library Ref": "FID", "Footprint Ref": "FID1"})


def test_reorder_fields(workspace: Workspace) -> None:
    cat = categories.reorder_fields("Resistors", ["Resistance", "tolerance", "Part Number", "Power"])
    names = [f.column for f in cat.fields]
    assert names[:4] == ["Part Number", "Resistance", "Tolerance", "Power"]
    assert len(names) == len(set(names)) == len(categories.get_category("Resistors").fields)
    with pytest.raises(FieldNotFound):
        categories.reorder_fields("Resistors", ["Nope"])
    same = categories.reorder_fields("Resistors", names[1:3])
    assert [f.column for f in same.fields] == names


def test_schema_change_callbacks(workspace: Workspace) -> None:
    calls: list[str] = []

    def good() -> None:
        calls.append("good")

    def bad() -> None:
        raise RuntimeError("kaputt")

    unsubscribe_good = categories.on_schema_change(good)
    categories.on_schema_change(good)  # registering twice has no effect
    unsubscribe_bad = categories.on_schema_change(bad)
    try:
        categories.add_field("Resistors", FieldDef(column="Extra 1", label="Extra"))
        categories.update_field("Resistors", "Extra 1", {"label": "Extra!"})
        categories.reorder_fields("Resistors", ["Extra 1"])
        categories.remove_field("Resistors", "Extra 1", backup=False)
        categories.update_category("Resistors", {"label": "R"})
        categories.create_category(new_category())
        categories.delete_category("Sensors", backup=False)
        assert calls == ["good"] * 7
    finally:
        unsubscribe_good()
        unsubscribe_bad()
    categories.update_category("Resistors", {"label": "Widerstände"})
    assert calls == ["good"] * 7


def test_builtin_templates_available(workspace: Workspace) -> None:
    templates = categories.builtin_templates()
    assert {t.table for t in templates} >= {"Resistors", "Capacitors", "Amplifiers"}
    assert all(t.fields[0].column == "Part Number" for t in templates)


def test_list_categories_counts(workspace: Workspace) -> None:
    parts.create_part("LEDs", {"Part Number": "L1", "Manufacturer": "x", "Manufacturer Part Number": "L1", "Color": "Rot",
                               "Library Ref": "LED", "Footprint Ref": "LEDC1608X70N"})
    counts = {c.table: c.part_count for c in categories.list_categories()}
    assert counts["LEDs"] == 1 and counts["Resistors"] == 0
    assert all(c.part_count is None for c in categories.list_categories(with_counts=False))
