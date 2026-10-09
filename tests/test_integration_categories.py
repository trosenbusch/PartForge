"""Integration: category default symbols are symbol kinds of partforge.symbols, resolved at
runtime in the house style (db.templates <-> symbols), plus the legacy data migration."""
from __future__ import annotations

import pytest
from sqlalchemy import select, update

from partforge import symbols as sy
from partforge.db import categories, core
from partforge.db.schema import pf_categories
from partforge.db.templates import (
    CATEGORIES,
    LEGACY_DEFAULT_SYMBOLS,
    DefaultSymbol,
    category_by_table,
    default_symbol_kind,
    migrate_default_symbols,
    resolve_default_symbol,
)
from partforge.workspace import SymbolStyle, Workspace

KIND_KEYS = {info.key for info in sy.kinds()}
CATHODE = SymbolStyle()
ANODE = SymbolStyle(diode_pin1="anode")


def test_template_defaults_are_standard_kind_keys() -> None:
    defaults = {c.table: c.default_symbol for c in CATEGORIES if c.default_symbol}
    assert defaults == {
        "Resistors": "resistor", "Capacitors": "capacitor", "Inductors": "inductor", "Ferrite Beads": "ferrite_bead",
        "Diodes": "diode", "LEDs": "led", "Transistors BJT": "npn", "Transistors FET": "nmos",
        "Amplifiers": "opamp_dual", "Oscillators": "crystal_2", "Connectors": "connector", "Fuses": "fuse",
        "Mechanical": "mounting_hole",
    }
    assert set(defaults.values()) <= KIND_KEYS - {"ic"}
    for table, kind in defaults.items():  # the symbol suits the category it is the default of
        info = next(i for i in sy.kinds() if i.key == kind)
        assert table in info.categories, (table, kind, info.categories)


@pytest.mark.parametrize("template", [c for c in CATEGORIES if c.default_symbol], ids=lambda c: c.table)
@pytest.mark.parametrize("style", [CATHODE, ANODE], ids=["cathode", "anode"])
def test_every_template_default_resolves(template, style: SymbolStyle) -> None:  # type: ignore[no-untyped-def]
    resolved = resolve_default_symbol(template, style=style)
    assert isinstance(resolved, DefaultSymbol)
    assert resolved.source == "category" and resolved.kind == template.default_symbol
    assert resolved.name == sy.generate(sy.SymbolRequest(kind=template.default_symbol), style).name
    assert sy.check_spec(resolved.spec) == []


def test_diode_default_names_follow_the_house_style() -> None:
    expected = {"Diodes": ("Diode", "Diode (AK)"), "LEDs": ("LED", "LED (AK)"), "Resistors": ("Resistor", "Resistor"),
                "Amplifiers": ("Op-Amp Dual", "Op-Amp Dual"), "Oscillators": ("Crystal", "Crystal")}
    for table, (cathode_name, anode_name) in expected.items():
        assert resolve_default_symbol(table, style=CATHODE).name == cathode_name  # type: ignore[union-attr]
        assert resolve_default_symbol(table, style=ANODE).name == anode_name  # type: ignore[union-attr]


def test_categories_without_default_resolve_to_none() -> None:
    for table in ("Integrated Circuits", "Power Linear", "Power Switchmode", "Data Converters", "Optocouplers",
                  "Electromechanical", "Unbekannte Tabelle"):
        assert resolve_default_symbol(table) is None, table


def test_every_category_of_an_open_library_resolves(workspace: Workspace) -> None:
    for cat in categories.list_categories(with_counts=False):
        resolved = resolve_default_symbol(cat, style=workspace.settings.symbol)
        template = category_by_table(cat.table)
        assert cat.default_symbol == (template.default_symbol if template else None)
        if cat.default_symbol:
            assert resolved is not None and resolved.kind == cat.default_symbol, cat.table
        else:
            assert resolved is None, cat.table


def test_values_decide_only_when_the_pinout_is_certain() -> None:
    pnp = resolve_default_symbol("Transistors BJT", {"Polarity": "PNP", "Package": "SOT-23"})
    assert pnp is not None and pnp.source == "values" and pnp.kind == "pnp" and pnp.name == "PNP"
    # TO-92 transistors have several pinouts: never fall back to the SOT-23 default "NPN"
    assert resolve_default_symbol("Transistors BJT", {"Polarity": "NPN", "Package": "TO-92"}) is None
    # a dual MOSFET has no standard symbol
    assert resolve_default_symbol("Transistors FET", {"Channel": "Dual N", "Package": "SO-8"}) is None
    polarized = resolve_default_symbol("Capacitors", {"Polarized": "Ja"})
    assert polarized is not None and polarized.name == "Capacitor Polarized"
    sot23 = resolve_default_symbol("Diodes", {"Diode Type": "Schottky", "Package": "SOT-23"}, style=ANODE)
    assert sot23 is not None and sot23.name == "Schottky Diode (AxK)"
    # the footprint pads are checked when given
    assert resolve_default_symbol("Diodes", {"Diode Type": "Schottky"}, footprint=["1", "2", "3"]) is None
    # empty values = no values
    assert resolve_default_symbol("Diodes", {"Package": "", "Notes": None}, style=ANODE).name == "Diode (AK)"  # type: ignore[union-attr]


def test_custom_categories_use_their_default_even_with_values(workspace: Workspace) -> None:
    from partforge.db.models import CategoryDef

    cat = categories.create_category(CategoryDef(table="Sensoren", label="Sensoren", default_symbol="connector"))
    resolved = resolve_default_symbol(cat, {"Manufacturer": "Bosch"})
    assert resolved is not None and resolved.source == "category" and resolved.name == "Connector 1x02"


def test_default_symbol_kind_accepts_keys_and_legacy_names() -> None:
    assert default_symbol_kind("resistor") == "resistor"
    assert default_symbol_kind(" RESISTOR ") == "resistor"
    assert default_symbol_kind("Ferrite Bead") == "ferrite_bead"
    assert default_symbol_kind("Op-Amp") == "opamp"  # a name of a standard symbol
    assert default_symbol_kind("Op-Amp", "Amplifiers") == "opamp_dual"  # legacy built-in default
    assert default_symbol_kind("Crystal", "Oscillators") == "crystal_2"
    assert default_symbol_kind("Crystal 4-Pin") == "crystal_4"
    for unknown in ("Diode (AK)", "ic", "IC", "RES", "", "   ", None):
        assert default_symbol_kind(unknown) is None, unknown
    for table, legacy in LEGACY_DEFAULT_SYMBOLS.items():
        template = category_by_table(table)
        assert template is not None and default_symbol_kind(legacy, table) == template.default_symbol


def _stored_defaults() -> dict[str, str | None]:
    with core.read() as conn:
        return {t: d for t, d in conn.execute(select(pf_categories.c.table_name, pf_categories.c.default_symbol))}


def test_migration_of_legacy_default_symbols_is_idempotent(workspace: Workspace) -> None:
    with core.connect() as conn:
        for table, legacy in LEGACY_DEFAULT_SYMBOLS.items():
            conn.execute(update(pf_categories).where(pf_categories.c.table_name == table).values(default_symbol=legacy))
        conn.execute(update(pf_categories).where(pf_categories.c.table_name == "Optocouplers")
                     .values(default_symbol="Mein Symbol"))  # unknown values are kept
    with core.connect() as conn:
        notes = migrate_default_symbols(conn)
    assert len(notes) == len(LEGACY_DEFAULT_SYMBOLS) and all("Symboltyp" in n for n in notes)
    stored = _stored_defaults()
    for table in LEGACY_DEFAULT_SYMBOLS:
        assert stored[table] == category_by_table(table).default_symbol  # type: ignore[union-attr]
    assert stored["Optocouplers"] == "Mein Symbol" and stored["Integrated Circuits"] is None
    with core.connect() as conn:
        assert migrate_default_symbols(conn) == []
    categories.invalidate_cache()
    assert categories.get_category("Amplifiers").default_symbol == "opamp_dual"
    assert resolve_default_symbol(categories.get_category("Optocouplers")) is None


def test_opening_an_older_library_migrates_its_default_symbols(bare_client, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Libraries created by older versions store symbol names; opening them converts them once."""
    from partforge.db.templates import ensure_default_symbol_kinds

    root = tmp_path / "Alt"
    created = bare_client.post("/api/workspace/create", json={"path": str(root), "with_examples": False})
    assert created.status_code == 200, created.text
    try:
        with core.connect() as conn:
            for table, legacy in LEGACY_DEFAULT_SYMBOLS.items():
                conn.execute(update(pf_categories).where(pf_categories.c.table_name == table)
                             .values(default_symbol=legacy))
        assert bare_client.post("/api/workspace/close").status_code == 200
        reopened = bare_client.post("/api/workspace/open", json={"path": str(root)})
        assert reopened.status_code == 200, reopened.text
        stored = _stored_defaults()
        for table in LEGACY_DEFAULT_SYMBOLS:
            assert stored[table] == category_by_table(table).default_symbol, table  # type: ignore[union-attr]
        listed = {c["table"]: c["default_symbol"] for c in bare_client.get("/api/categories").json()}
        assert listed["Amplifiers"] == "opamp_dual" and listed["Oscillators"] == "crystal_2"
        assert ensure_default_symbol_kinds() == []  # nothing left to do
    finally:
        bare_client.post("/api/workspace/close")
