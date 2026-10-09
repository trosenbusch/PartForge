"""Integration: a new library with examples is consistent across db, symbols, footprints,
geometry and the library writers – without Altium and without the writer process.

* every registered spec passes the generator checks (symbols.check_spec,
  footprints.validate_footprint) and the writers' offline payload validation;
* every example part references registered symbols/footprints with their library paths;
* symbol pins and footprint pads agree (geometry.check_symbol_footprint), also in
  anode-first workspaces and at other densities;
* where the symbol mapping is certain, it suggests the same symbol as the examples use.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from partforge import db
from partforge import footprints as fp
from partforge import symbols as sy
from partforge.altium import libwriter
from partforge.altium.rustwriter import (
    footprint_to_rust,
    symbol_to_rust,
    validate_footprint_payload,
    validate_symbol_payload,
)
from partforge.db import categories, examples, parts, registry
from partforge.geometry.model import FootprintSpec, SymbolSpec, check_symbol_footprint
from partforge.workspace import Workspace, WorkspaceSettings, set_current

_BY_PN = {p.part_number: p for p in examples.EXAMPLE_PARTS}


def _open(root: Path, settings: WorkspaceSettings | None = None) -> Iterator[Workspace]:
    ws = Workspace.create(root, name="Integration", settings=settings)
    db.open_database(ws)
    set_current(ws)
    try:
        db.seed_examples(ws)
        yield ws
    finally:
        db.close_database()
        set_current(None)


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Workspace]:
    yield from _open(tmp_path / "Bibliothek")


@pytest.fixture
def seeded_anode(tmp_path: Path) -> Iterator[Workspace]:
    settings = WorkspaceSettings()
    settings.symbol.diode_pin1 = "anode"
    yield from _open(tmp_path / "Anode", settings)


def _all_parts() -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for cat in categories.list_categories(with_counts=False):
        rows, _ = parts.query_parts(cat.table, limit=None)
        out.extend((cat.table, row) for row in rows)
    return out


def _pad_problems(symbol: SymbolSpec, footprint: FootprintSpec, unused: tuple[str, ...]) -> list[str]:
    problems = check_symbol_footprint(symbol, footprint)
    allowed = f"Pads ohne Pin im Symbol: {', '.join(unused)}" if unused else None
    return [p for p in problems if p != allowed]


# --------------------------------------------------------------------------- registry specs


def test_registry_specs_are_valid_for_generators_and_writers(seeded: Workspace) -> None:
    style = seeded.settings
    symbols = registry.list_symbols()
    footprints = registry.list_footprints()
    assert len(symbols) == 15 and len(footprints) == 13
    for rec in symbols:
        assert rec.spec is not None and rec.status == "pending" and rec.source == "generated"
        assert rec.spec.name == rec.name
        assert sy.check_spec(rec.spec, grid=style.symbol.grid) == [], rec.name
        assert validate_symbol_payload(symbol_to_rust(rec.spec, style.symbol)) == [], rec.name
        assert rec.kind == (rec.spec.generator or {}).get("kind")
        assert rec.pin_count == len(rec.spec.pins) and rec.part_count == rec.spec.part_count
    for frec in footprints:
        spec = frec.spec
        assert spec is not None and frec.status == "pending" and spec.name == frec.name
        errors = [i for i in fp.validate_footprint(spec, style.footprint) if i.severity == "error"]
        assert errors == [], (frec.name, errors)
        assert validate_footprint_payload(footprint_to_rust(spec, style.layers, style.footprint)) == [], frec.name
        assert frec.pad_count == len(spec.pad_designators()) and frec.height == spec.height
        assert frec.family == spec.family and frec.ipc_name == spec.ipc_name


def test_registry_libraries_follow_the_libwriter_layout(seeded: Workspace) -> None:
    usage: dict[str, str] = {}
    for table, row in _all_parts():
        usage.setdefault(row["Library Ref"], table)
    for rec in registry.list_symbols():
        assert rec.spec is not None
        expected = libwriter.symbol_library_path(seeded, rec.spec, usage[rec.name])
        assert rec.library == seeded.rel(expected) and "\\" in rec.library and not Path(rec.library).is_absolute()
        assert seeded.abs(rec.library) == expected
    for frec in registry.list_footprints():
        assert frec.spec is not None
        expected = libwriter.footprint_library_path(seeded, frec.spec)
        assert frec.library == seeded.rel(expected) and frec.library.startswith("Footprints\\")


# --------------------------------------------------------------------------- parts


def test_every_example_part_references_registered_entries(seeded: Workspace) -> None:
    symbols = {r.name: r for r in registry.list_symbols()}
    footprints = {r.name: r for r in registry.list_footprints()}
    rows = _all_parts()
    assert {row["Part Number"] for _, row in rows} == set(_BY_PN)
    for table, row in rows:
        pn = row["Part Number"]
        assert table == _BY_PN[pn].table
        sym, foot = symbols.get(row["Library Ref"]), footprints.get(row["Footprint Ref"])
        assert sym is not None and foot is not None, pn
        assert row["Library Path"] == sym.library and row["Footprint Path"] == foot.library, pn
        assert row["Notes"] == examples.EXAMPLE_NOTE and row["PF Status"] == examples.EXAMPLE_STATUS
        assert row["Height"], pn


@pytest.mark.parametrize("fixture", ["seeded", "seeded_anode"])
def test_symbol_pins_match_footprint_pads(fixture: str, request: pytest.FixtureRequest) -> None:
    request.getfixturevalue(fixture)
    symbols = {r.name: r.spec for r in registry.list_symbols()}
    footprints = {r.name: r.spec for r in registry.list_footprints()}
    for _, row in _all_parts():
        part = _BY_PN[row["Part Number"]]
        symbol, footprint = symbols[row["Library Ref"]], footprints[row["Footprint Ref"]]
        assert symbol is not None and footprint is not None
        assert _pad_problems(symbol, footprint, part.unused_pads) == [], (part.part_number, symbol.name, footprint.name)


def test_anode_first_workspace_pairs_ak_symbols_with_reversed_footprints(seeded_anode: Workspace) -> None:
    diodes = {"MBR0520LT1G": ("Schottky Diode (AK)", "SOD3716X135RN"), "MMSZ5231B-7-F": ("Zener Diode (AK)", "SOD3716X135RN"),
              "150060RS75000": ("LED (AK)", "LEDC1608X80RN")}
    for pn, (symbol_name, footprint_name) in diodes.items():
        found = parts.find_part(pn)
        assert found is not None
        _, row = found
        assert (row["Library Ref"], row["Footprint Ref"]) == (symbol_name, footprint_name)
        symbol = registry.get_symbol(symbol_name)
        footprint = registry.get_footprint(footprint_name)
        assert symbol and symbol.spec and footprint and footprint.spec
        cathode_pin = next(p.designator for p in symbol.spec.pins if p.name == "K")
        cathode_pad = str((footprint.spec.generator or {})["params"]["cathode_pad"])
        assert cathode_pin == cathode_pad == "2"
    names = {r.name for r in registry.list_symbols()}
    assert not {"Diode", "Schottky Diode", "Zener Diode", "LED"} & names


@pytest.mark.parametrize("density", ["M", "L"])
def test_other_densities_give_consistent_names(tmp_path: Path, density: str) -> None:
    settings = WorkspaceSettings()
    settings.footprint.density = density  # type: ignore[assignment]
    content = examples.build_examples(Workspace.create(tmp_path / density, settings=settings))
    assert not content.skipped
    for name, rec in content.footprints.items():
        assert rec.spec is not None and rec.spec.density == density
        if not name.startswith("HDR"):  # IPC-7251 header names carry no density letter
            assert name.rsplit("_", 1)[0].endswith(density), name  # "_<tag>" follows the density letter
        errors = [i for i in fp.validate_footprint(rec.spec, settings.footprint) if i.severity == "error"]
        assert errors == [], (name, errors)


def test_examples_agree_with_the_symbol_mapping(seeded: Workspace) -> None:
    """Where :func:`partforge.symbols.suggest_symbol` is certain, it picks the example's symbol."""
    footprints = {r.name: r.spec for r in registry.list_footprints()}
    checked = 0
    for table, row in _all_parts():
        part = _BY_PN[row["Part Number"]]
        suggestion = sy.suggest_symbol(table, row, footprint=footprints[row["Footprint Ref"]], style=seeded.settings.symbol)
        if part.symbol.kind == "ic":  # LDOs have no standard symbol: the IC generator is used
            assert suggestion.request is None
            continue
        if suggestion.request is None:
            assert suggestion.kind == part.symbol.kind, (part.part_number, suggestion)
            continue
        checked += 1
        assert suggestion.name == row["Library Ref"], (part.part_number, suggestion.name, row["Library Ref"])
    assert checked >= 14


def test_examples_are_stored_in_canonical_form(seeded: Workspace) -> None:
    """Re-validating every stored example changes nothing and reports nothing."""
    for table, row in _all_parts():
        result = parts.validate_part(table, row, pn=row["Part Number"])
        assert result["errors"] == {} and result["warnings"] == [] and result["conflict"] is None, row["Part Number"]
        normalised = result["values"]
        changed = {k: (row[k], normalised[k]) for k in row if not k.startswith("PF ") and row[k] != normalised.get(k)}
        assert changed == {}, (row["Part Number"], changed)
