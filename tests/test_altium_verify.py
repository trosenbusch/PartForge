"""partforge.altium.verify: sample of the Altium check (spread/first), selection, stored last result."""
from __future__ import annotations

import pytest

from partforge.altium import verify
from partforge.altium.verify import (
    VerifiedPart,
    VerifyError,
    VerifyRun,
    VerifySummary,
    sample_quotas,
    select_parts,
    spread_indices,
)
from partforge.db import meta, parts

# --------------------------------------------------------------------------- quotas / indices


@pytest.mark.parametrize(
    ("counts", "limit", "expected"),
    [
        ([30, 10], 8, [6, 2]),  # proportional
        ([100, 1, 1], 10, [8, 1, 1]),  # at least one per category, the rest proportional
        ([5, 0, 5], 4, [2, 0, 2]),  # empty categories get nothing
        ([3, 2], 10, [3, 2]),  # the limit covers everything
        ([1, 1, 1, 1], 2, [1, 1, 1, 1]),  # more categories than the limit: one each
        ([7, 7, 7], 10, [4, 3, 3]),  # ties go to the earlier category
        ([0, 0], 5, [0, 0]),
        ([], 5, []),
    ],
)
def test_sample_quotas(counts: list[int], limit: int, expected: list[int]):
    quotas = sample_quotas(counts, limit)
    assert quotas == expected
    assert all(0 <= q <= n for q, n in zip(quotas, counts, strict=True))
    assert sample_quotas(counts, limit) == quotas  # deterministic


def test_sample_quotas_hit_the_limit_and_keep_one_per_category():
    for counts in ([50, 3, 1, 200, 7], [1] * 3 + [500], [12, 12, 12, 12, 12]):
        for limit in (5, 6, 20, 37, 100):
            quotas = sample_quotas(counts, limit)
            nonempty = sum(1 for n in counts if n)
            assert sum(quotas) == max(min(limit, sum(counts)), nonempty), (counts, limit, quotas)
            assert all(q >= 1 for q, n in zip(quotas, counts, strict=True) if n)


@pytest.mark.parametrize(
    ("count", "quota", "expected"),
    [(10, 1, [5]), (10, 2, [2, 7]), (10, 5, [1, 3, 5, 7, 9]), (3, 3, [0, 1, 2]), (3, 5, [0, 1, 2]), (0, 2, [])],
)
def test_spread_indices(count: int, quota: int, expected: list[int]):
    indices = spread_indices(count, quota)
    assert indices == expected and len(set(indices)) == len(indices)


# --------------------------------------------------------------------------- selection


PART = {"Manufacturer": "YAGEO", "Resistance": "10k", "Tolerance": "1%", "Power": "0.1W", "Description": "RES",
        "Library Ref": "RES", "Footprint Ref": "RESC1608X55N"}
CAP = {"Manufacturer": "KEMET", "Capacitance": "100n", "Voltage": "50V", "Description": "CAP", "Library Ref": "CAP",
       "Footprint Ref": "CAPC1608X87N"}


def _fill(workspace) -> None:
    parts.upsert_parts("Resistors", [{"Part Number": f"R-{i:02d}", **PART} for i in range(30)])
    parts.upsert_parts("Capacitors", [{"Part Number": f"C-{i:02d}", **CAP} for i in range(10)])


def test_spread_sample_covers_every_category(workspace):
    _fill(workspace)
    selection = select_parts(limit=8)
    assert selection.scope == "sample" and selection.sample == "spread" and selection.limit == 8
    by_table: dict[str, list[str]] = {}
    for table, row in selection.parts:
        by_table.setdefault(table, []).append(str(row["Part Number"]))
    assert {t: len(p) for t, p in by_table.items()} == {"Resistors": 6, "Capacitors": 2}
    assert by_table["Capacitors"] == ["C-02", "C-07"]  # evenly spaced, not the first two
    assert by_table["Resistors"] == ["R-02", "R-07", "R-12", "R-17", "R-22", "R-27"]
    assert selection.total == 40 and selection.categories == 2 and selection.tables == []
    again = select_parts(limit=8)
    assert [r["Part Number"] for _, r in again.parts] == [r["Part Number"] for _, r in selection.parts]


def test_first_sample_all_and_named(workspace):
    _fill(workspace)
    first = select_parts(limit=8, sample="first")
    assert first.sample == "first" and {t for t, _ in first.parts} == {"Resistors"}  # category order
    assert [r["Part Number"] for _, r in first.parts] == [f"R-{i:02d}" for i in range(8)]
    everything = select_parts(all_parts=True, limit=3)
    assert everything.scope == "all" and everything.sample is None and len(everything.parts) == 40
    limited = select_parts(tables=["capacitors"], limit=3)
    assert limited.tables == ["Capacitors"] and [t for t, _ in limited.parts] == ["Capacitors"] * 3
    named = select_parts(part_numbers=["C-03", " R-01 ", "C-03"], limit=1)
    assert named.scope == "part_numbers" and [r["Part Number"] for _, r in named.parts] == ["C-03", "R-01"]
    with pytest.raises(VerifyError, match="nicht gefunden: GIBT-ES-NICHT"):
        select_parts(part_numbers=["GIBT-ES-NICHT"])
    with pytest.raises(VerifyError, match="gibtsnicht"):
        select_parts(tables=["Gibtsnicht"])


# --------------------------------------------------------------------------- last result


def _run(**summary) -> VerifyRun:
    return VerifyRun(scope="sample", sample="spread", limit=20, started="2026-10-08T10:00:00",
                     finished="2026-10-08T10:00:05", summary=VerifySummary(message="1 Bauteil geprüft", **summary),
                     results=[VerifiedPart(table="Resistors", part_number="R-1", status="ok")])


def test_last_result_round_trip(workspace):
    assert verify.load_last() is None
    verify.save_last(_run(checked=1, ok=1))
    loaded = verify.load_last()
    assert loaded is not None and loaded.summary.checked == 1 and loaded.results[0].part_number == "R-1"
    assert meta.get_meta(verify.LAST_RESULT_KEY) is not None
    meta.set_meta(verify.LAST_RESULT_KEY, "{kaputt")
    assert verify.load_last() is None  # unreadable: as if there were none


# --------------------------------------------------------------------------- parameters (E2EREG-3)


@pytest.mark.parametrize(
    ("altium", "database"),
    [
        ("10k\u2126", "10k\u03a9"),  # OHM SIGN = GREEK CAPITAL OMEGA
        ("4.7\u03bcF", "4.7\u00b5F"),  # GREEK MU = MICRO SIGN
        ("+/-1%", "±1%"),
        ("+ / -250µV", "±250µV"),
        ("1\u00a0µF  50V ", "1 µF 50V"),  # no-break space, double blank, trailing blank
        ("GRM188\u00adR71", "GRM188R71"),  # soft hyphen (format character)
        ("-40\u2103 … 85°C", "-40°C ... 85°C"),
        (None, "   "),  # blank = absent
    ],
)
def test_comparable_text_equal_spellings(altium, database):
    assert verify.comparable_text(altium) == verify.comparable_text(database)


@pytest.mark.parametrize(("a", "b"), [("smd", "SMD"), ("10kΩ", "10kO"), ("1%", "±1%"), ("290V/µs", "")])
def test_comparable_text_real_differences(a, b):
    assert verify.comparable_text(a) != verify.comparable_text(b)


def _category():
    from partforge.db.models import CategoryDef, FieldDef

    return CategoryDef(table="Amplifiers", label="Verstärker", fields=[
        FieldDef(column="Part Number", label="Teilenummer"),
        FieldDef(column="Description", label="Beschreibung"),
        FieldDef(column="Comment", label="Kommentar", show_on_schematic=True),
        FieldDef(column="Library Ref", label="Symbol", add_to_design=False),
        FieldDef(column="Footprint Ref 2", label="Footprint 2"),  # reserved mapping even when "added"
        FieldDef(column="Notes", label="Notizen", add_to_design=False),
        FieldDef(column="GBW", label="GBW", kind="quantity", unit="Hz"),
        FieldDef(column="Slew Rate", label="Slew-Rate"),
        FieldDef(column="Rail-to-Rail", label="Rail-to-Rail"),
    ])


def test_compare_parameters_checks_the_design_fields_only():
    row = {"Part Number": "OPA656U", "Description": "IC OPAMP 230MHz", "Comment": "OPA656U", "Library Ref": "Op-Amp",
           "Footprint Ref 2": "SOIC8", "Notes": "intern", "GBW": "230MHz", "slew rate": "290V/µs", "Rail-to-Rail": None}
    params = {"Part Number": "OPA656U", "comment": "OPA656U", "GBW": "230 MHz", "Rail-to-Rail": "Ausgang",
              "Notes": "intern", "Library Ref": "Op-Amp", "Supplier": ""}
    result = verify.compare_parameters(_category(), row, params, "IC OPAMP 230MHz")
    assert result.checked == 6  # Part Number, Description, Comment, GBW, Slew Rate, Rail-to-Rail
    assert [(d.parameter, d.database, d.altium) for d in result.diffs] == [
        ("GBW", "230MHz", "230 MHz"),  # a blank more is a different text
        ("Slew Rate", "290V/µs", None),  # column names are compared case-insensitively
        ("Rail-to-Rail", None, "Ausgang"),
    ]
    assert result.extra == ["Notes", "Library Ref"]  # returned by Altium but no design parameter; blank ones dropped
    same = verify.compare_parameters(_category(), row, {**params, "GBW": "230MHz", "Slew Rate": "290V/µs",
                                                        "Rail-to-Rail": " "}, "IC OPAMP 230MHz")
    assert same.diffs == []
    other = verify.compare_parameters(_category(), row, params, "IC OPAMP 1CH")
    assert [d.parameter for d in other.diffs] == ["GBW", "Slew Rate", "Rail-to-Rail", "Description"]  # Description last
    assert other.diffs[-1].altium == "IC OPAMP 1CH" and other.diffs[-1].database == "IC OPAMP 230MHz"


def test_parameter_messages():
    from partforge.altium.verify import ParameterDiff, parameter_message

    assert parameter_message(ParameterDiff(parameter="Slew Rate", database="290V/µs")) == (
        "Altium liefert für „Slew Rate“ keinen Wert – in der Datenbank steht „290V/µs“.")
    assert parameter_message(ParameterDiff(parameter="Rail-to-Rail", altium="Ausgang")) == (
        "Altium liefert für „Rail-to-Rail“ „Ausgang“ – in der Datenbank ist das Feld leer.")
    assert parameter_message(ParameterDiff(parameter="GBW", database="230MHz", altium="200MHz")) == (
        "Altium liefert für „GBW“ „200MHz“ – in der Datenbank steht „230MHz“.")
    long = parameter_message(ParameterDiff(parameter="Description", database="x" * 300, altium="y"))
    assert "„" + "x" * 79 + "…“" in long and len(long) < 160  # the full value stays in the result


def test_results_of_older_versions_still_load(workspace):
    """A stored result from before the parameter comparison (no description/parameters) stays readable."""
    old = _run(checked=1, ok=1).model_dump(mode="json")
    for key in ("description", "parameters", "parameters_checked", "parameter_diffs", "extra_parameters"):
        old["results"][0].pop(key)
    import json

    meta.set_meta(verify.LAST_RESULT_KEY, json.dumps(old))
    loaded = verify.load_last()
    assert loaded is not None and loaded.results[0].parameters == {} and loaded.results[0].parameter_diffs == []
    assert loaded.results[0].parameters_checked == 0
