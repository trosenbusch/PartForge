"""Public key/value API of pf_meta (partforge.db.meta)."""
from __future__ import annotations

import pytest

from partforge import db
from partforge.db import core, meta, parts
from partforge.db.errors import DatabaseNotOpen
from partforge.workspace import Workspace


def test_get_set_delete_and_items(workspace: Workspace) -> None:
    assert meta.get_meta("test:a") is None and meta.get_meta("test:a", "standard") == "standard"
    meta.set_meta("test:a", "1")
    meta.set_meta("test:b", "zwei")
    meta.set_meta("test:a", "eins")  # update
    assert meta.get_meta("test:a") == "eins"
    assert meta.meta_items("test:") == {"test:a": "eins", "test:b": "zwei"}
    assert meta.get_meta("schema_version") == "2" and meta.get_meta(meta.WORKSPACE_ROOT) == str(workspace.root)
    assert meta.delete_meta("test:a") is True and meta.delete_meta("test:a") is False
    meta.set_meta("test:b", None)  # None removes the key
    assert meta.meta_items("test:") == {}


def test_joins_the_callers_transaction(workspace: Workspace) -> None:
    with pytest.raises(RuntimeError):
        with core.connect() as conn:
            meta.set_meta("test:tx", "1", conn=conn)
            assert meta.get_meta("test:tx", conn=conn) == "1"
            assert meta.get_meta("test:tx") == "1"  # same thread: the open write transaction is used
            raise RuntimeError("Abbruch")
    assert meta.get_meta("test:tx") is None  # rolled back together with the caller's transaction


def test_keys_are_checked(workspace: Workspace) -> None:
    for bad in ("", "   ", "x" * (meta.MAX_KEY_LENGTH + 1)):
        with pytest.raises(ValueError, match="Metadaten-Schlüssel"):
            meta.get_meta(bad)
    for reserved in sorted(meta.RESERVED_KEYS):
        with pytest.raises(ValueError, match="verwaltet"):
            meta.set_meta(reserved, "99")
        with pytest.raises(ValueError, match="verwaltet"):
            meta.delete_meta(reserved)
    assert meta.get_meta("schema_version") == "2"  # unchanged
    meta.set_meta("x" * meta.MAX_KEY_LENGTH, "ok")


def test_requires_an_open_database(workspace: Workspace) -> None:
    db.close_database()
    with pytest.raises(DatabaseNotOpen):
        meta.get_meta("test:a")


def test_internal_part_number_counter_uses_the_public_api(workspace: Workspace) -> None:
    workspace.settings.part_number_scheme = "internal"
    created = parts.create_part("Resistors", {"Manufacturer": "YAGEO", "Manufacturer Part Number": "RC0603FR-071KL",
                                              "Resistance": "1k", "Tolerance": "1", "Power": "0.1",
                                              "Library Ref": "Resistor", "Footprint Ref": "RESC1608X50N"})
    assert created["Part Number"] == "R-000001" and meta.get_meta("pn_counter:R") == "1"
