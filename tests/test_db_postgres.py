"""PostgreSQL backend (same Core code, Python fallback for quantity queries).

Runs only when ``PARTFORGE_TEST_PG`` holds a SQLAlchemy URL of an empty test database,
e.g. ``postgresql+psycopg://partforge:secret@127.0.0.1:5432/partforge_test``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

PG_URL = os.environ.get("PARTFORGE_TEST_PG")

pytestmark = pytest.mark.skipif(not PG_URL, reason="PostgreSQL-Test deaktiviert (PARTFORGE_TEST_PG=<URL>)")


def test_postgres_roundtrip(tmp_path: Path) -> None:
    from sqlalchemy import create_engine, inspect, text

    from partforge import db
    from partforge.db import categories, core, health, parts
    from partforge.db.models import FieldDef, PartFilter
    from partforge.workspace import Workspace, WorkspaceSettings, set_current

    engine = create_engine(str(PG_URL))
    with engine.begin() as conn:  # start from an empty schema
        for name in inspect(conn).get_table_names():
            conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))
    engine.dispose()
    settings = WorkspaceSettings()
    settings.db.kind = "postgres"
    settings.db.postgres_url = PG_URL
    ws = Workspace.create(tmp_path / "PG", settings=settings)
    db.open_database(ws)
    set_current(ws)
    try:
        assert not core.sql_functions_enabled()
        assert len(categories.list_categories()) > 10
        categories.add_field("Transistors FET", FieldDef(column="QG(tot) max", label="Qg max", kind="quantity", unit="C"))
        for pn, value in (("R-1", "1k"), ("R-2", "4k7"), ("R-3", "10k")):
            parts.create_part("Resistors", {"Part Number": pn, "Manufacturer": "x", "Manufacturer Part Number": pn,
                                            "Resistance": value, "Tolerance": "1", "Power": "0.1", "Library Ref": "RES",
                                            "Footprint Ref": "RESC1608X55N"})
        rows, total = parts.query_parts("Resistors", filters=[PartFilter(column="Resistance", op="gt", value="2k")],
                                        sort="-Resistance")
        assert total == 2 and [r["Part Number"] for r in rows] == ["R-3", "R-2"]
        assert [r["Part Number"] for r in parts.query_parts("Resistors", search="4.7k")[0]] == ["R-2"]
        assert parts.existing_part_numbers(["r-1"]) == {"r-1"}
        assert parts.search_all("R-3")[0]["part_number"] == "R-3"
        assert health.health_report()["counts"]["error"] == 0
        db.close_database()
        db.open_database(ws)  # idempotent
        assert parts.get_part("Resistors", "R-1") is not None
    finally:
        db.close_database()
        set_current(None)
