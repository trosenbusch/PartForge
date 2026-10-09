"""Built-in category labels use "und" instead of "&" (and read complete: "Optokoppler und Optoelektronik",
K5); older libraries are migrated when opened (only labels that still equal an old built-in text and were
never renamed by the user)."""
from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from sqlalchemy import select, update

from partforge import db
from partforge.db import categories, core, lifecycle, templates
from partforge.db.schema import pf_audit, pf_categories
from partforge.workspace import Workspace, set_current

NEW = {
    "Power Linear": "Linearregler und Referenzen",
    "Optocouplers": "Optokoppler und Optoelektronik",
    "Oscillators": "Quarze und Oszillatoren",
    "Fuses": "Sicherungen und Schutz",
}
#: every label an older version gave the category (oldest first)
OLD = {
    "Power Linear": ("Linearregler & Referenzen",),
    "Optocouplers": ("Optokoppler & Opto", "Optokoppler und Opto"),
    "Oscillators": ("Quarze & Oszillatoren",),
    "Fuses": ("Sicherungen & Schutz",),
}


@pytest.fixture
def library(tmp_path) -> Iterator[Workspace]:
    ws = Workspace.create(tmp_path / "Bibliothek", name="Labels")
    db.open_database(ws)
    set_current(ws)
    try:
        yield ws
    finally:
        db.close_database()
        set_current(None)


def _reopen(ws: Workspace) -> Workspace:
    db.close_database()
    again = Workspace.open(ws.root)
    db.open_database(again)
    set_current(again)
    return again


def _set_label(table: str, label: str) -> None:
    with core.connect() as conn:
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == table).values(label=label))
    categories.invalidate_cache()


def _label_audits() -> list[dict]:
    with core.read() as conn:
        rows = conn.execute(select(pf_audit.c.table_name, pf_audit.c.changes, pf_audit.c.author)
                            .where(pf_audit.c.action == "schema")).all()
    out = []
    for table, raw, author in rows:
        changes = json.loads(raw)
        if changes.get("op") == "migrate_category_label":
            out.append({"table": table, "label": changes["label"], "author": author})
    return out


def test_builtin_labels_use_und():
    labels = {t.table: t.label for t in templates.CATEGORIES}
    assert all("&" not in label for label in labels.values())
    for table, label in NEW.items():
        assert labels[table] == label
        assert templates.LEGACY_CATEGORY_LABELS[table] == OLD[table]


def test_new_library_gets_the_new_labels(library):
    assert {t: categories.get_category(t).label for t in NEW} == NEW


@pytest.mark.parametrize("generation", [0, -1])
def test_old_labels_are_migrated_once(library, generation):
    for table in NEW:
        _set_label(table, OLD[table][generation])
    ws = _reopen(library)
    assert {t: categories.get_category(t).label for t in NEW} == NEW
    audits = _label_audits()
    assert sorted(a["table"] for a in audits) == sorted(NEW)
    assert all(a["author"] == lifecycle.MIGRATION_AUTHOR for a in audits)
    fuses = next(a for a in audits if a["table"] == "Fuses")
    assert fuses["label"] == ["Sicherungen & Schutz", "Sicherungen und Schutz"]
    _reopen(ws)  # idempotent: nothing left to do, no new audit entries
    assert len(_label_audits()) == len(NEW)


def test_user_labels_are_kept(library):
    _set_label("Fuses", "Sicherungen")  # the user's own label
    _set_label("Oscillators", "Quarze & Oszillatoren (alt)")  # not the old built-in text
    ws = _reopen(library)
    assert categories.get_category("Fuses").label == "Sicherungen"
    assert categories.get_category("Oscillators").label == "Quarze & Oszillatoren (alt)"
    # explicitly renamed to the old spelling through PartForge: never migrated back
    categories.update_category("Optocouplers", {"label": "Optokoppler & Opto"})
    _reopen(ws)
    assert categories.get_category("Optocouplers").label == "Optokoppler & Opto"
    assert _label_audits() == []


def test_migration_function_is_idempotent_in_one_transaction(library):
    _set_label("Power Linear", "Linearregler & Referenzen")
    with core.connect() as conn:
        first = templates.migrate_category_labels(conn)
        second = templates.migrate_category_labels(conn)
    categories.invalidate_cache()
    assert first == ["Bezeichnung der Kategorie „Power Linear“: „Linearregler & Referenzen“ → "
                     "„Linearregler und Referenzen“."]
    assert second == []
    assert categories.get_category("Power Linear").label == "Linearregler und Referenzen"
