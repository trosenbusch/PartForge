"""Opening a library: data migrations of partforge.db.lifecycle.

* schematic texts: only the Comment is visible on the schematic (house style, VERIFIED in
  Altium – altium-e2e.md §3.4/§6.1); older libraries are migrated once, user changes kept;
* default symbols: every way of opening converts the symbol names of older versions;
* moved library folder: absolute links into the old folder follow the library.
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import delete, select, update

from partforge import db, events
from partforge.db import audit, categories, core, lifecycle, meta, parts, registry, schema
from partforge.db.lifecycle import MIGRATION_AUTHOR, SCHEMATIC_TEXTS_MARKER, relocate_link
from partforge.db.models import CategoryDef, DatasheetRecord, FieldDef
from partforge.db.schema import pf_categories, pf_fields, pf_meta
from partforge.db.templates import CATEGORIES, LEGACY_COMMENT_TEMPLATES, LEGACY_VISIBLE_FIELDS, category_by_table
from partforge.workspace import Workspace, set_current

OLD_TEMPLATES = {"Capacitors": "{Capacitance:rkm}", "Inductors": "{Inductance}", "Ferrite Beads": "{Impedance}"}


def cap(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "Murata", "Manufacturer Part Number": pn, "Capacitance": value,
            "Voltage": "50V", "Library Ref": "Capacitor", "Footprint Ref": "CAPC1608X87N", **kw}


def res(pn: str, value: str, **kw: Any) -> dict[str, Any]:
    return {"Part Number": pn, "Manufacturer": "YAGEO", "Manufacturer Part Number": pn, "Resistance": value,
            "Tolerance": "1%", "Power": "0.1W", "Library Ref": "Resistor", "Footprint Ref": "RESC1608X50N", **kw}


@pytest.fixture
def closing() -> Iterator[None]:
    """Whatever library a test opened is closed afterwards."""
    try:
        yield
    finally:
        db.close_database()
        set_current(None)


def _open(ws: Workspace) -> Workspace:
    db.open_database(ws)
    set_current(ws)
    return ws


def _reopen(ws: Workspace) -> Workspace:
    db.close_database()
    return _open(Workspace.open(ws.root))


@pytest.fixture
def recorder() -> Iterator[dict[str, list[Any]]]:
    """Schema-change callbacks and PARTS_CHANGED events during the test."""
    calls: dict[str, list[Any]] = {"schema": [], "parts": []}
    unsubscribe_schema = categories.on_schema_change(lambda: calls["schema"].append(1))
    unsubscribe_parts = events.subscribe(events.PARTS_CHANGED, lambda *args: calls["parts"].append(args))
    try:
        yield calls
    finally:
        unsubscribe_schema()
        unsubscribe_parts()


def _make_legacy() -> None:
    """Turn the open library into one created by an older version: value fields visible,
    Comment hidden, old comment templates, migration marker missing."""
    with core.connect() as conn:
        conn.execute(update(pf_fields).where(pf_fields.c.column_name == "Comment").values(show_on_schematic=False))
        for table, columns in LEGACY_VISIBLE_FIELDS.items():
            conn.execute(update(pf_fields).where(pf_fields.c.table_name == table, pf_fields.c.column_name.in_(columns))
                         .values(show_on_schematic=True))
        for table, template in OLD_TEMPLATES.items():
            conn.execute(update(pf_categories).where(pf_categories.c.table_name == table)
                         .values(comment_template=template))
        conn.execute(delete(pf_meta).where(pf_meta.c.key == SCHEMATIC_TEXTS_MARKER))
    categories.invalidate_cache()


def _visible(table: str) -> set[str]:
    return {f.column for f in categories.get_category(table).fields if f.show_on_schematic}


# --------------------------------------------------------------------------- schematic texts


def test_new_library_shows_only_the_comment_on_the_schematic(workspace: Workspace) -> None:
    from partforge.altium.dblib import build_dblib

    for cat in categories.list_categories(with_counts=False):
        assert _visible(cat.table) == {"Comment"}, cat.table
    expected = {"Resistors": "{Resistance:rkm}", "Capacitors": "{Capacitance:rkm} {Voltage}",
                "Inductors": "{Inductance:rkm}", "Ferrite Beads": "{Impedance:rkm}@100MHz", "LEDs": "{Color}",
                "Oscillators": "{Frequency}", "Fuses": "{Current Rating}", "Diodes": "{Manufacturer Part Number}",
                "Amplifiers": "{Manufacturer Part Number}", "Integrated Circuits": "{Manufacturer Part Number}"}
    for table, template in expected.items():
        assert categories.get_category(table).comment_template == template, table
    assert meta.get_meta(SCHEMATIC_TEXTS_MARKER) == "1"  # a new library never needs the migration
    build = build_dblib(workspace)
    visible = {(m.table, m.column) for m in build.field_maps if m.visible_on_add and m.add_mode == 0}
    assert visible == {(t.name, "Comment") for t in build.tables if t.enabled}  # VisibleOnAdd only for Comment
    created = parts.create_part("Capacitors", cap("C-1", "4.7u", Voltage="6.3"))
    assert created["Comment"] == "4u7 6.3V" and created["Value"] == "4.7µF"
    inductor = parts.create_part("Inductors", {"Part Number": "L-1", "Manufacturer": "Bourns", "Inductance": "4.7u",
                                               "Library Ref": "Inductor", "Footprint Ref": "INDM"})
    assert inductor["Comment"] == "4u7"


def test_older_library_is_migrated_once(tmp_path: Path, closing: None,
                                        recorder: dict[str, list[Any]]) -> None:
    ws = _open(Workspace.create(tmp_path / "Alt"))
    _make_legacy()
    parts.create_part("Capacitors", cap("C-GEN", "100n"))  # Comment generated by the old template: "100n"
    parts.create_part("Capacitors", cap("C-HAND", "10u", Comment="Entkopplung"))
    parts.create_part("Capacitors", cap("C-EMPTY", "1u"))
    _raw_update("Capacitors", "C-EMPTY", Comment=None)  # emptied by another tool: generated text follows
    parts.create_part("Inductors", {"Part Number": "L-GEN", "Manufacturer": "Bourns", "Inductance": "10u",
                                    "Library Ref": "Inductor", "Footprint Ref": "INDM"})
    parts.create_part("Ferrite Beads", {"Part Number": "FB-GEN", "Manufacturer": "Murata", "Impedance": "220",
                                        "Library Ref": "Ferrite Bead", "Footprint Ref": "INDC1608X95N"})
    parts.create_part("Resistors", res("R-1", "4k7"))
    assert parts.get_part("Capacitors", "C-GEN")["Comment"] == "100n"  # type: ignore[index]
    assert parts.get_part("Inductors", "L-GEN")["Comment"] == "10µH"  # type: ignore[index]
    assert parts.get_part("Ferrite Beads", "FB-GEN")["Comment"] == "220Ω"  # type: ignore[index]
    assert _visible("Capacitors") == {"Capacitance", "Voltage"} and _visible("Amplifiers") == set()
    recorder["schema"].clear()
    recorder["parts"].clear()

    _reopen(ws)
    for cat in categories.list_categories(with_counts=False):
        assert _visible(cat.table) == {"Comment"}, cat.table
    for table in OLD_TEMPLATES:
        current = category_by_table(table)
        assert current is not None and categories.get_category(table).comment_template == current.comment_template
    assert parts.get_part("Capacitors", "C-GEN")["Comment"] == "100n 50V"  # type: ignore[index]
    assert parts.get_part("Capacitors", "C-EMPTY")["Comment"] == "1u 50V"  # type: ignore[index]
    assert parts.get_part("Capacitors", "C-HAND")["Comment"] == "Entkopplung"  # type: ignore[index]  (by hand)
    assert parts.get_part("Inductors", "L-GEN")["Comment"] == "10u"  # type: ignore[index]
    assert parts.get_part("Ferrite Beads", "FB-GEN")["Comment"] == "220R@100MHz"  # type: ignore[index]
    assert parts.get_part("Resistors", "R-1")["Comment"] == "4k7"  # type: ignore[index]  (template unchanged)
    migrated = parts.get_part("Capacitors", "C-GEN")
    assert migrated and migrated["PF Author"] == MIGRATION_AUTHOR
    entry = parts.history("Capacitors", "C-GEN")[0]
    assert entry["action"] == "bulk_update" and entry["author"] == MIGRATION_AUTHOR
    assert entry["changes"] == {"Comment": ["100n", "100n 50V"]}
    schema_entries = [e for e in audit.recent(100, actions=["schema"]) if e.changes.get("op") == "migrate_schematic_texts"]
    caps = next(e for e in schema_entries if e.table == "Capacitors")
    assert caps.changes["comment_template"] == ["{Capacitance:rkm}", "{Capacitance:rkm} {Voltage}"]
    assert caps.changes["show_on_schematic"] == {"Comment": [False, True], "Capacitance": [True, False],
                                                 "Voltage": [True, False]}
    assert caps.changes["parts"] == 2 and caps.author == MIGRATION_AUTHOR
    assert meta.get_meta(SCHEMATIC_TEXTS_MARKER) == "1"
    assert recorder["schema"] == [1]  # the DbLib is rewritten (VisibleOnAdd)
    assert recorder["parts"] == [(None, False)]  # three categories with changed Comments

    # once only: a Comment hidden again by the user stays hidden, nothing is announced again
    categories.update_field("Resistors", "Comment", {"show_on_schematic": False})
    recorder["schema"].clear()
    recorder["parts"].clear()
    _reopen(ws)
    assert _visible("Resistors") == set() and _visible("Capacitors") == {"Comment"}
    assert recorder == {"schema": [], "parts": []}


def test_migration_keeps_what_the_user_changed(tmp_path: Path, closing: None) -> None:
    ws = _open(Workspace.create(tmp_path / "Eigen"))
    _make_legacy()
    # explicit changes through PartForge (audit log), even where they equal an old default
    categories.update_field("Amplifiers", "Comment", {"show_on_schematic": True})
    categories.update_field("Amplifiers", "Comment", {"show_on_schematic": False})
    categories.update_field("LEDs", "Color", {"show_on_schematic": False})
    categories.update_field("LEDs", "Color", {"show_on_schematic": True})
    categories.update_category("Capacitors", {"comment_template": "{Capacitance}"})  # an old default, chosen
    categories.update_category("Inductors", {"comment_template": "{Inductance} {Current Rating}"})  # own template
    categories.update_field("Resistors", "Tolerance", {"show_on_schematic": True})  # not a field of the migration
    with core.connect() as conn:  # value field already hidden by the user (no audit entry): stays hidden
        conn.execute(update(pf_fields).where(pf_fields.c.table_name == "Oscillators",
                                             pf_fields.c.column_name == "Frequency").values(show_on_schematic=False))
    _reopen(ws)
    assert _visible("Amplifiers") == set()  # the user hid the Comment explicitly
    assert _visible("LEDs") == {"Comment", "Color"}
    assert _visible("Resistors") == {"Comment", "Tolerance"}
    assert _visible("Oscillators") == {"Comment"} and _visible("Capacitors") == {"Comment"}
    assert categories.get_category("Capacitors").comment_template == "{Capacitance}"
    assert categories.get_category("Inductors").comment_template == "{Inductance} {Current Rating}"
    assert categories.get_category("Ferrite Beads").comment_template == "{Impedance:rkm}@100MHz"


def test_template_is_kept_when_a_referenced_field_is_gone(tmp_path: Path, closing: None) -> None:
    ws = _open(Workspace.create(tmp_path / "OhneSpannung"))
    _make_legacy()
    with core.connect() as conn:  # e.g. "Voltage" renamed outside PartForge's field editor
        conn.execute(update(pf_fields).where(pf_fields.c.table_name == "Capacitors", pf_fields.c.column_name == "Voltage")
                     .values(column_name="Rated Voltage"))
        conn.exec_driver_sql('ALTER TABLE "Capacitors" RENAME COLUMN "Voltage" TO "Rated Voltage"')
    _reopen(ws)
    assert categories.get_category("Capacitors").comment_template == "{Capacitance:rkm}"
    assert categories.get_category("Inductors").comment_template == "{Inductance:rkm}"


def test_template_based_category_with_another_name_is_migrated(tmp_path: Path, closing: None) -> None:
    ws = _open(Workspace.create(tmp_path / "Vorlage"))
    template = next(c for c in categories.builtin_templates() if c.table == "Capacitors")
    categories.create_category(template.model_copy(update={"table": "Capacitors THT", "label": "Kondensatoren THT"}))
    _make_legacy()
    with core.connect() as conn:
        conn.execute(update(pf_fields).where(pf_fields.c.table_name == "Capacitors THT",
                                             pf_fields.c.column_name.in_(["Capacitance", "Voltage"]))
                     .values(show_on_schematic=True))
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Capacitors THT")
                     .values(comment_template="{Capacitance}"))
    categories.invalidate_cache()
    custom = categories.create_category(CategoryDef(
        table="Eigene", label="Eigene", prefix="X", comment_template="{Capacitance}",
        fields=[FieldDef(column="Capacitance", label="C", kind="quantity", unit="F", show_on_schematic=True)]))
    assert custom.field("Capacitance").show_on_schematic and not custom.builtin  # type: ignore[union-attr]
    _reopen(ws)
    tht = categories.get_category("Capacitors THT")
    assert _visible("Capacitors THT") == {"Comment"} and tht.comment_template == "{Capacitance:rkm} {Voltage}"
    assert _visible("Eigene") == {"Comment", "Capacitance"}  # a custom category keeps its own choice
    assert categories.get_category("Eigene").comment_template == "{Capacitance}"


def test_custom_category_with_a_built_in_name_keeps_its_fields(tmp_path: Path, closing: None) -> None:
    ws = _open(Workspace.create(tmp_path / "Eigen2"))
    categories.delete_category("LEDs", backup=False)
    categories.create_category(CategoryDef(
        table="LEDs", label="Meine LEDs", prefix="D", comment_template="{Color}",
        fields=[FieldDef(column="Color", label="Farbe", show_on_schematic=True)]))
    _make_legacy()
    _reopen(ws)
    assert not categories.get_category("LEDs").builtin
    assert _visible("LEDs") == {"Comment", "Color"}  # only the Comment follows the house style


def test_failing_data_migration_does_not_block_opening(tmp_path: Path, closing: None,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _open(Workspace.create(tmp_path / "Kaputt"))
    _make_legacy()
    with core.connect() as conn:
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Amplifiers").values(default_symbol="Op-Amp"))

    def broken(conn: Any, *_args: Any) -> None:  # writes first, then fails: the savepoint must undo the write
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Resistors").values(label="halb"))
        raise RuntimeError("Testfehler")

    monkeypatch.setattr(lifecycle, "_migrate_schematic_texts", broken)
    db.close_database()
    db.open_database(ws)  # opens anyway
    assert categories.get_category("Resistors").label == "Widerstände"
    assert meta.get_meta(SCHEMATIC_TEXTS_MARKER) is None and _visible("Capacitors") == {"Capacitance", "Voltage"}
    assert categories.get_category("Amplifiers").default_symbol == "opamp_dual"  # the other steps ran
    monkeypatch.undo()
    _reopen(ws)  # tried again at the next open
    assert _visible("Capacitors") == {"Comment"} and meta.get_meta(SCHEMATIC_TEXTS_MARKER) == "1"


# --------------------------------------------------------------------------- default symbols


def test_direct_open_migrates_legacy_default_symbols(tmp_path: Path, closing: None) -> None:
    ws = _open(Workspace.create(tmp_path / "Symbole"))
    with core.connect() as conn:
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Amplifiers").values(default_symbol="Op-Amp"))
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Diodes").values(default_symbol="Diode"))
    db.close_database()
    db.open_database(ws)  # not through the API
    assert categories.get_category("Amplifiers").default_symbol == "opamp_dual"
    assert categories.get_category("Diodes").default_symbol == "diode"
    with core.read() as conn:
        stored = dict(conn.execute(select(pf_categories.c.table_name, pf_categories.c.default_symbol)).all())
    assert stored["Amplifiers"] == "opamp_dual"
    db.close_database()
    db.open_database(ws)  # idempotent
    assert categories.get_category("Amplifiers").default_symbol == "opamp_dual"


# --------------------------------------------------------------------------- moved library folder


def test_relocate_link() -> None:
    old, new = r"C:\Libs\Bib", r"D:\Neu\Bibliothek"
    assert relocate_link(r"C:\Libs\Bib\Datasheets\x.pdf", old, new) == r"D:\Neu\Bibliothek\Datasheets\x.pdf"
    assert relocate_link(r"c:\libs\BIB\Datasheets\x.pdf", old, new) == r"D:\Neu\Bibliothek\Datasheets\x.pdf"
    assert relocate_link("C:/Libs/Bib/Datasheets/x.pdf", old, new) == "D:/Neu/Bibliothek/Datasheets/x.pdf"
    assert relocate_link("file:///C:/Libs/Bib/x.pdf", old, new) == "file:///D:/Neu/Bibliothek/x.pdf"
    assert relocate_link("FILE://C:/Libs/Bib/x.pdf", old + "\\", new + "\\") == "FILE://D:/Neu/Bibliothek/x.pdf"
    assert relocate_link(r"C:\Libs\Bib", old, new) == new
    assert relocate_link(r"C:\Libs\Bibliothek2\x.pdf", old, new) is None  # only a common prefix
    assert relocate_link(r"C:\Libs\Bi", old, new) is None
    assert relocate_link("https://example.com/C:/Libs/Bib/x.pdf", old, new) is None
    assert relocate_link(r"Datasheets\x.pdf", old, new) is None
    assert relocate_link("", old, new) is None and relocate_link("x", "", new) is None
    assert relocate_link(r"C:\x.pdf", "C:\\", r"D:\Bib") == r"D:\Bib\x.pdf"  # library at a drive root


def _raw_update(table: str, pn: str, **values: str) -> None:
    cat = categories.get_category(table)
    t = categories.table_for(cat)
    with core.connect() as conn:  # bypasses normalisation (written by an older version or another tool)
        conn.execute(update(t).where(t.c["Part Number"] == pn).values(**values))


def test_moved_library_moves_its_links(tmp_path: Path, closing: None,
                                       recorder: dict[str, list[Any]]) -> None:
    ws = _open(Workspace.create(tmp_path / "Alt" / "Bibliothek"))
    old = str(ws.root)
    assert meta.get_meta(meta.WORKSPACE_ROOT) == old  # remembered on the first open
    categories.add_field("Capacitors", FieldDef(column="Vendor URL", label="Herstellerseite", kind="url"))
    categories.add_field("Capacitors", FieldDef(column="ComponentLink2URL", label="Link 2"))  # plain text field
    parts.create_part("Resistors", res("R-BACK", "1k", ComponentLink1URL=old + r"\Datasheets\r.pdf"))
    shouting = old.replace("\\", "/").upper()  # other letter case and slash style
    parts.create_part("Resistors", res("R-SLASH", "2k", ComponentLink1URL=shouting + "/Datasheets/s.pdf"))
    parts.create_part("Resistors", res("R-FILE", "3k", ComponentLink1URL="file:///" + old.replace("\\", "/") + "/d/f.pdf"))
    parts.create_part("Resistors", res("R-WEB", "4k", ComponentLink1URL="https://www.yageo.com/r.pdf"))
    parts.create_part("Resistors", res("R-NEAR", "5k", ComponentLink1URL=old + r"2\x.pdf"))  # another folder
    parts.create_part("Resistors", res("R-REL", "6k", ComponentLink1URL=r"Datasheets\rel.pdf"))
    parts.create_part("Capacitors", cap("C-1", "100n", **{"Vendor URL": old + r"\Docs\c.html",
                                                          "ComponentLink2URL": old + r"\Docs\c2.pdf"}))
    _raw_update("Resistors", "R-BACK", **{"Library Path": old + r"\Symbols\PF_Passives.SchLib"})
    before = parts.get_part("Resistors", "R-WEB")
    db.close_database()
    set_current(None)
    target = tmp_path / "Neu" / "Ort"
    target.parent.mkdir()
    shutil.move(str(ws.root), str(target))
    recorder["parts"].clear()

    moved = _open(Workspace.open(target))
    new = str(moved.root)
    assert new != old and meta.get_meta(meta.WORKSPACE_ROOT) == new

    def link(pn: str, table: str = "Resistors", column: str = "ComponentLink1URL") -> str | None:
        row = parts.get_part(table, pn)
        assert row is not None
        return row[column]

    assert link("R-BACK") == new + r"\Datasheets\r.pdf"
    assert link("R-SLASH") == new.replace("\\", "/") + "/Datasheets/s.pdf"  # slash style kept
    assert link("R-FILE") == "file:///" + new.replace("\\", "/") + "/d/f.pdf"
    assert link("R-WEB") == "https://www.yageo.com/r.pdf" and link("R-NEAR") == old + r"2\x.pdf"
    assert link("R-REL") == r"Datasheets\rel.pdf"
    assert link("R-BACK", column="Library Path") == r"Symbols\PF_Passives.SchLib"  # path fields: relative
    assert link("C-1", "Capacitors", "Vendor URL") == new + r"\Docs\c.html"
    assert link("C-1", "Capacitors", "ComponentLink2URL") == new + r"\Docs\c2.pdf"
    assert parts.get_part("Resistors", "R-WEB") == before  # untouched rows keep their bookkeeping
    back = parts.get_part("Resistors", "R-BACK")
    assert back and back["PF Author"] == MIGRATION_AUTHOR
    entry = parts.history("Resistors", "R-BACK")[0]
    assert entry["action"] == "bulk_update" and entry["author"] == MIGRATION_AUTHOR
    assert entry["changes"]["ComponentLink1URL"] == [old + r"\Datasheets\r.pdf", new + r"\Datasheets\r.pdf"]
    assert entry["changes"]["Library Path"] == [old + r"\Symbols\PF_Passives.SchLib", r"Symbols\PF_Passives.SchLib"]
    assert recorder["parts"] == [(None, False)]  # one announcement for both categories

    recorder["parts"].clear()
    _reopen(moved)  # nothing left to move
    assert recorder["parts"] == [] and link("R-BACK") == new + r"\Datasheets\r.pdf"


def test_failed_relocation_is_retried(tmp_path: Path, closing: None, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = _open(Workspace.create(tmp_path / "A" / "Bib"))
    old = str(ws.root)
    parts.create_part("Resistors", res("R-1", "1k", ComponentLink1URL=old + r"\Datasheets\r.pdf"))
    db.close_database()
    target = tmp_path / "B"
    shutil.move(str(ws.root), str(target))

    def broken(*_args: Any) -> tuple[int, int]:
        raise RuntimeError("Testfehler")

    monkeypatch.setattr(lifecycle, "_move_links", broken)
    moved = _open(Workspace.open(target))
    assert meta.get_meta(meta.WORKSPACE_ROOT) == old  # not marked as done
    assert parts.get_part("Resistors", "R-1")["ComponentLink1URL"] == old + r"\Datasheets\r.pdf"  # type: ignore[index]
    monkeypatch.undo()
    _reopen(moved)
    assert meta.get_meta(meta.WORKSPACE_ROOT) == str(moved.root)
    row = parts.get_part("Resistors", "R-1")
    assert row and row["ComponentLink1URL"] == str(moved.root) + r"\Datasheets\r.pdf"


def _forget_root() -> None:
    """Like a library of an older version: the folder was never recorded."""
    with core.connect() as conn:
        conn.execute(delete(pf_meta).where(pf_meta.c.key == meta.WORKSPACE_ROOT))


def test_older_library_learns_its_former_folder_from_datasheet_links(tmp_path: Path, closing: None) -> None:
    """A library moved before PartForge recorded its folder: the datasheet import linked the stored PDF
    absolutely (<root>\\<pf_datasheets.file>), which tells the former folder."""
    ws = _open(Workspace.create(tmp_path / "Neu"))
    registry.upsert_datasheet(DatasheetRecord(id="e9e615f9aaaaaaaa", file=r"Datasheets\opa656_e9e615f9.pdf",
                                              original_name="opa656.pdf"))
    former = r"C:\Frueher\Bibliothek"
    parts.create_part("Resistors", res("R-DS", "1k", ComponentLink1URL=former + r"\Datasheets\opa656_e9e615f9.pdf"))
    parts.create_part("Resistors", res("R-DOC", "2k", ComponentLink1URL=former + r"\Docs\notiz.pdf"))  # same folder
    parts.create_part("Resistors", res("R-OTHER", "3k", ComponentLink1URL=r"C:\Woanders\x.pdf"))
    _forget_root()
    _reopen(ws)
    root = str(ws.root)
    assert parts.get_part("Resistors", "R-DS")["ComponentLink1URL"] == root + r"\Datasheets\opa656_e9e615f9.pdf"  # type: ignore[index]
    assert parts.get_part("Resistors", "R-DOC")["ComponentLink1URL"] == root + r"\Docs\notiz.pdf"  # type: ignore[index]
    assert parts.get_part("Resistors", "R-OTHER")["ComponentLink1URL"] == r"C:\Woanders\x.pdf"  # type: ignore[index]
    assert meta.get_meta(meta.WORKSPACE_ROOT) == root


def test_former_folder_is_not_guessed_when_ambiguous_or_current(tmp_path: Path, closing: None) -> None:
    ws = _open(Workspace.create(tmp_path / "Zweideutig"))
    registry.upsert_datasheet(DatasheetRecord(id="a" * 16, file=r"Datasheets\a_aaaaaaaa.pdf", original_name="a.pdf"))
    registry.upsert_datasheet(DatasheetRecord(id="b" * 16, file=r"Datasheets\b_bbbbbbbb.pdf", original_name="b.pdf"))
    root = str(ws.root)
    parts.create_part("Resistors", res("R-A", "1k", ComponentLink1URL=r"C:\Eins\Datasheets\a_aaaaaaaa.pdf"))
    parts.create_part("Resistors", res("R-B", "2k", ComponentLink1URL=r"D:\Zwei\Datasheets\b_bbbbbbbb.pdf"))
    parts.create_part("Resistors", res("R-HERE", "3k", ComponentLink1URL=root + r"\Datasheets\a_aaaaaaaa.pdf"))
    parts.create_part("Resistors", res("R-REL", "4k", ComponentLink1URL=r"Datasheets\b_bbbbbbbb.pdf"))
    _forget_root()
    _reopen(ws)  # two different former folders: nothing is guessed
    assert parts.get_part("Resistors", "R-A")["ComponentLink1URL"] == r"C:\Eins\Datasheets\a_aaaaaaaa.pdf"  # type: ignore[index]
    assert parts.get_part("Resistors", "R-B")["ComponentLink1URL"] == r"D:\Zwei\Datasheets\b_bbbbbbbb.pdf"  # type: ignore[index]
    assert meta.get_meta(meta.WORKSPACE_ROOT) == root  # recorded from now on
    parts.delete_parts("Resistors", ["R-A", "R-B"])
    _forget_root()
    _reopen(ws)  # only links into the current folder: nothing to move
    assert parts.get_part("Resistors", "R-HERE")["ComponentLink1URL"] == root + r"\Datasheets\a_aaaaaaaa.pdf"  # type: ignore[index]
    assert parts.get_part("Resistors", "R-HERE")["PF Author"] != MIGRATION_AUTHOR  # type: ignore[index]


def test_links_are_never_rewritten_for_postgres(workspace: Workspace) -> None:
    """A PostgreSQL database is shared by the library folders of several users."""
    parts.create_part("Resistors", res("R-1", "1k", ComponentLink1URL=r"C:\Anderer\Ordner\r.pdf"))
    meta.set_meta(meta.WORKSPACE_ROOT, r"C:\Anderer\Ordner")
    with core.connect() as conn:
        report = lifecycle.migrate_data(conn, workspace, kind="postgres")
    assert report.parts == 0 and meta.get_meta(meta.WORKSPACE_ROOT) == r"C:\Anderer\Ordner"
    assert parts.get_part("Resistors", "R-1")["ComponentLink1URL"] == r"C:\Anderer\Ordner\r.pdf"  # type: ignore[index]
    with core.connect() as conn:  # the same call for SQLite moves the link
        report = lifecycle.migrate_data(conn, workspace, kind="sqlite")
    assert report.parts == 1 and report.tables == {"Resistors"}
    assert parts.get_part("Resistors", "R-1")["ComponentLink1URL"] == str(workspace.root) + r"\r.pdf"  # type: ignore[index]


def test_same_folder_in_other_spelling_is_not_a_move(workspace: Workspace) -> None:
    root = str(workspace.root)
    parts.create_part("Resistors", res("R-1", "1k", ComponentLink1URL=root + r"\Datasheets\r.pdf"))
    meta.set_meta(meta.WORKSPACE_ROOT, root.upper().replace("\\", "/") + "/")
    db.close_database()
    db.open_database(workspace)
    assert meta.get_meta(meta.WORKSPACE_ROOT) == root  # spelling refreshed
    stored = parts.get_part("Resistors", "R-1")
    assert stored and stored["ComponentLink1URL"] == root + r"\Datasheets\r.pdf" and stored["PF Author"] != MIGRATION_AUTHOR


def test_audit_entries_of_the_migrations_are_valid(tmp_path: Path, closing: None) -> None:
    """The entries use the existing audit actions (the frontend knows exactly these)."""
    ws = _open(Workspace.create(tmp_path / "Audit"))
    _make_legacy()
    parts.create_part("Capacitors", cap("C-1", "100n"))
    _reopen(ws)
    with core.read() as conn:
        rows = conn.execute(select(schema.pf_audit.c.action, schema.pf_audit.c.changes)
                            .where(schema.pf_audit.c.author == MIGRATION_AUTHOR)).all()
    assert rows and {action for action, _ in rows} == {"schema", "bulk_update"}
    assert all(isinstance(json.loads(changes), dict) for _, changes in rows)


def test_legacy_defaults_describe_built_in_categories() -> None:
    tables = {t.table for t in CATEGORIES}
    assert set(LEGACY_COMMENT_TEMPLATES) <= tables and set(LEGACY_VISIBLE_FIELDS) <= tables
    for table, columns in LEGACY_VISIBLE_FIELDS.items():
        template = category_by_table(table)
        assert template is not None and {f.column for f in template.fields} >= set(columns), table
        assert not any(f.show_on_schematic for f in template.fields), table  # current default: hidden
    for table, old in LEGACY_COMMENT_TEMPLATES.items():
        assert category_by_table(table).comment_template not in old, table  # type: ignore[union-attr]
