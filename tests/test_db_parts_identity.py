"""Part Number / MPN identity: invisible and look-alike characters never bypass uniqueness (INT-07).

Soft hyphens, zero-width spaces, a BOM or bidi overrides (Unicode category Cf) come along when MPNs are
copied from web pages and PDFs; NFD umlauts and non-ASCII case (``ß``/``SS``, ``Ä``/``ä``) look identical
in the grid. Stored values are NFC without format characters; comparisons use ``pn_key`` / ``mpn_key``
(NFKC, format characters removed, case-folded) everywhere – create, update, import, health check.
"""
from __future__ import annotations

import sys
import unicodedata

import pytest

from partforge.db import health, parts
from partforge.db.errors import DuplicatePartError
from partforge.db.models import FieldDef
from partforge.db.values import normalize_cell
from partforge.domain.text import FORMAT_CHARS, identity_key, identity_text
from partforge.workspace import Workspace

BASE = "GRM188R71H104KA93D"
VARIANTS = {
    "soft hyphen": "GRM188­R71H104KA93D",
    "zero-width space": "GRM188R71H104KA93D​",
    "BOM": "﻿GRM188R71H104KA93D",
    "word joiner": "GRM188⁠R71H104KA93D",
    "RTL override": "GRM188‮R71H104KA93D",
    "fullwidth": "ＧＲＭ188R71H104KA93D",
}


def test_format_char_class_covers_every_cf_code_point() -> None:
    missing = [hex(c) for c in range(sys.maxunicode + 1)
               if unicodedata.category(chr(c)) == "Cf" and not FORMAT_CHARS.fullmatch(chr(c))]
    assert missing == []
    assert FORMAT_CHARS.search("GRM188R71H104KA93D-Ω ä ß") is None


def test_identity_text_and_key() -> None:
    assert identity_text("UNIQ-Ä-2") == "UNIQ-Ä-2"  # NFD -> NFC
    assert identity_text(" GRM188­R71H104KA93D​ ") == BASE
    for variant in VARIANTS.values():
        assert identity_key(variant) == BASE.lower()
    assert identity_key("UNIQ-STRASSE") == identity_key("uniq-straße")
    assert identity_key("UNIQ-Ä-2") == identity_key("uniq-ä-2")
    assert parts.pn_key(" Abc ") == "abc"  # ASCII stays ASCII-lower-cased and trimmed


@pytest.mark.parametrize("column", ["Part Number", "Manufacturer Part Number"])
def test_normalize_removes_invisible_characters(column: str) -> None:
    f = FieldDef(column=column, label=column)
    res = normalize_cell(f, "GRM188­R71H104KA93D​")
    assert res.value == BASE
    assert res.warning is not None and "unsichtbare" in res.warning.lower()
    assert normalize_cell(f, "UNIQ-Ä-2").value == "UNIQ-Ä-2"
    assert normalize_cell(f, BASE).warning is None
    # free text keeps its characters (only the identity fields are cleaned)
    assert normalize_cell(FieldDef(column="Description", label="D"), "a­b").value == "a­b"


def test_mpn_key_ignores_format_characters() -> None:
    for variant in VARIANTS.values():
        assert parts.mpn_key(variant) == parts.mpn_key(BASE)


@pytest.mark.parametrize("label", list(VARIANTS))
def test_invisible_variants_are_duplicates(workspace: Workspace, label: str) -> None:
    parts.create_part("Capacitors", {"Part Number": BASE}, allow_incomplete=True)
    with pytest.raises(DuplicatePartError):
        parts.create_part("Capacitors", {"Part Number": VARIANTS[label]}, allow_incomplete=True)
    with pytest.raises(DuplicatePartError):  # across categories, too
        parts.create_part("Resistors", {"Part Number": VARIANTS[label]}, allow_incomplete=True)


@pytest.mark.parametrize(("first", "second"), [
    ("UNIQ-Ä-2", "UNIQ-Ä-2"),  # NFC vs NFD
    ("UNIQ-Ä-2", "uniq-ä-2"),  # non-ASCII case
    ("UNIQ-STRASSE", "uniq-straße"),
    ("uniq-straße", "UNIQ-STRASSE"),
])
def test_unicode_case_and_normal_forms_are_duplicates(workspace: Workspace, first: str, second: str) -> None:
    parts.create_part("Resistors", {"Part Number": first}, allow_incomplete=True)
    with pytest.raises(DuplicatePartError):
        parts.create_part("Capacitors", {"Part Number": second}, allow_incomplete=True)


def test_rename_and_import_use_the_same_key(workspace: Workspace) -> None:
    parts.create_part("Resistors", {"Part Number": "UNIQ-STRASSE"}, allow_incomplete=True)
    parts.create_part("Resistors", {"Part Number": "OTHER-1"}, allow_incomplete=True)
    with pytest.raises(DuplicatePartError):
        parts.update_part("Resistors", "OTHER-1", {"Part Number": "uniq-straße"})
    plans = parts.plan_upsert("Capacitors", [{"Part Number": "uniq-straße"}], allow_incomplete=True)
    assert plans[0].status == "reject" and plans[0].conflict == ("Resistors", "UNIQ-STRASSE")
    # same category, mode update: the import finds the existing part instead of creating a twin
    same = parts.plan_upsert("Resistors", [{"Part Number": "uniq-straße", "Manufacturer": "X"}], mode="update",
                             allow_incomplete=True)
    assert same[0].status == "update" and same[0].stored == "UNIQ-STRASSE"
    result = parts.upsert_parts("Resistors", [{"Part Number": "GRM­X-1"}, {"Part Number": "grmx-1​"}],
                                allow_incomplete=True)
    assert result.created == ["GRMX-1"] and len(result.errors) == 1  # the twin in the same batch is refused


def test_api_refuses_invisible_twin(client) -> None:  # noqa: ANN001 - fixture
    r = client.post("/api/parts/Capacitors", json={"values": {"Part Number": BASE}, "allow_incomplete": True})
    assert r.status_code == 201
    r = client.post("/api/parts/Capacitors", json={"values": {"Part Number": VARIANTS["soft hyphen"]},
                                                   "allow_incomplete": True})
    assert r.status_code == 409, r.text


def test_health_check_finds_legacy_twins(workspace: Workspace) -> None:
    """Rows written before this rule (or by other programs) are reported as duplicates."""
    from sqlalchemy import insert

    from partforge.db import categories, core

    parts.create_part("Capacitors", {"Part Number": BASE, "Manufacturer Part Number": BASE}, allow_incomplete=True)
    table = categories.table_for(categories.get_category("Capacitors"))
    with core.connect() as conn:  # bypasses normalisation like Altium/foreign SQL would
        conn.execute(insert(table).values({"Part Number": VARIANTS["soft hyphen"],
                                           "Manufacturer Part Number": VARIANTS["zero-width space"]}))
        conn.execute(insert(table).values({"Part Number": "UNIQ-Ä-2"}))
        conn.execute(insert(table).values({"Part Number": "uniq-ä-2"}))
    report = health.health_report(max_per_check=None)
    dup_pn = [i for i in report["issues"] if i["check"] == "duplicate_pn"]
    dup_mpn = [i for i in report["issues"] if i["check"] == "duplicate_mpn"]
    assert len(dup_pn) == 2 and len(dup_mpn) == 2
    invisible = [i for i in report["issues"] if i["check"] == "format" and i["column"] in ("Part Number",
                                                                                          "Manufacturer Part Number")]
    assert {i["column"] for i in invisible} == {"Part Number", "Manufacturer Part Number"}
