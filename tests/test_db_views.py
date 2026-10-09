"""Saved grid views and the MPN template store."""
from __future__ import annotations

import pytest

from partforge.db import mpn_templates, views
from partforge.db.errors import NotFoundError, SchemaError
from partforge.db.models import PartFilter, SavedView, SortSpec
from partforge.workspace import Workspace


def test_saved_views_crud(workspace: Workspace) -> None:
    view = views.create_view(SavedView(name="  10k  Widerstände ", table="resistors", search="10k",
                                       filters=[PartFilter(column="tolerance", op="le", value="1%")],
                                       sort=[SortSpec(column="resistance", desc=True)], columns=["part number", "Resistance"]),
                             author="Tester")
    assert view.id and view.name == "10k Widerstände" and view.table == "Resistors" and view.author == "Tester"
    assert view.filters[0].column == "Tolerance" and view.sort[0].column == "Resistance"
    assert view.columns == ["Part Number", "Resistance"] and view.created and view.modified
    global_view = views.create_view(SavedView(name="Alle Entwürfe", filters=[PartFilter(column="PF Status", op="eq", value="Entwurf")]))
    assert global_view.table is None
    assert [v.name for v in views.list_views("Resistors")] == ["10k Widerstände", "Alle Entwürfe"]
    assert [v.name for v in views.list_views("Capacitors")] == ["Alle Entwürfe"]
    assert len(views.list_views()) == 2
    updated = views.update_view(view.id or 0, {"name": "Neu", "search": "  "})
    assert updated.name == "Neu" and updated.search is None and updated.filters == view.filters
    with pytest.raises(SchemaError, match="Unbekannte Felder"):
        views.update_view(view.id or 0, {"columns": ["Gibtsnicht"]})
    with pytest.raises(SchemaError, match="Unbekannte Eigenschaften"):
        views.update_view(view.id or 0, {"id": 5})
    with pytest.raises(SchemaError, match="Namen"):
        views.create_view(SavedView(name=" "))
    with pytest.raises(KeyError):
        views.create_view(SavedView(name="x", table="Gibtsnicht"))
    assert views.delete_view(view.id or 0) and not views.delete_view(view.id or 0)
    with pytest.raises(NotFoundError):
        views.get_view(view.id or 0)


def test_mpn_templates(workspace: Workspace) -> None:
    saved = mpn_templates.save_mpn_template("yageo-rc-eigen", "Yageo RC (eigene)", {"pattern": "RC{size}FR-07{value}L", "sizes": ["0603"]},
                                            category="Resistors")
    assert saved["data"]["sizes"] == ["0603"] and saved["created"] == saved["modified"]
    again = mpn_templates.save_mpn_template("yageo-rc-eigen", "Yageo RC", {"pattern": "x"})
    assert again["name"] == "Yageo RC" and again["category"] is None and again["created"] == saved["created"]
    assert [t["key"] for t in mpn_templates.list_mpn_templates()] == ["yageo-rc-eigen"]
    assert mpn_templates.list_mpn_templates(category="Capacitors") == []
    assert mpn_templates.get_mpn_template("nope") is None
    with pytest.raises(SchemaError):
        mpn_templates.save_mpn_template("bad key!", "x", {})
    with pytest.raises(SchemaError):
        mpn_templates.save_mpn_template("ok", " ", {})
    assert mpn_templates.delete_mpn_template("yageo-rc-eigen") and not mpn_templates.delete_mpn_template("yageo-rc-eigen")
