"""Series symbol: never a guessed pin-out (ARCHITEKTUR §1.5/§9) – template symbol kind with pin map,
symbol mapping from values/footprint, category default only without pin map, fixed Library Ref."""
from __future__ import annotations

from typing import Any

import pytest

from partforge.altium import sync
from partforge.db import categories, parts, registry
from partforge.db.models import CategoryDef, FieldDef, FootprintRecord, SymbolRecord
from partforge.domain.mpn import MpnTemplate, save_custom_template
from partforge.domain.series import NO_SAFE_SYMBOL, SeriesRequest, commit, preview
from partforge.workspace import Workspace


@pytest.fixture
def fake_sync(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"symbols": [], "footprints": []}

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None):
        calls["symbols"].append(list(specs))
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF.SchLib", spec=s, status="ok")
                                        for s in specs])

    def ensure_footprints(specs, *, source="generated", ctx=None):
        calls["footprints"].append(list(specs))
        return registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF.PcbLib", spec=s,
                                                           status="ok") for s in specs])

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    return calls


def transistor_template(category: str = "Transistors BJT", family: str = "sot23", **overrides: Any) -> MpnTemplate:
    data: dict[str, Any] = {
        "id": "test-sot", "manufacturer": "Probe", "series": "PX", "category": category, "title": "Probe-Serie",
        "pattern": "PX{size}-{value}",
        "variables": [{"name": "size", "label": "Gehäuse", "options": [{"code": "S", "value": "SOT-23"}]},
                      {"name": "value", "label": "Spannung", "format": {"style": "rkm", "letters": {"V": 0}}}],
        "value_unit": "V",
        "sizes": [{"size": "SOT-23"}],
        "footprint": {"family": family, "params": {}},
        "fields": {"Package": "{size}"},
    }
    data.update(overrides)
    return save_custom_template(MpnTemplate.model_validate(data))


def request(**kw: Any) -> SeriesRequest:
    return SeriesRequest.model_validate({"template_id": "test-sot", "values": ["45V", "80V"], **kw})


@pytest.mark.parametrize("category", ["Transistors BJT", "Transistors FET"])
def test_unknown_pinout_is_never_guessed(workspace: Workspace, fake_sync: dict[str, list[Any]],
                                         category: str) -> None:
    """Regression: the category default (npn/nmos) used to be generated with its default pin map."""
    transistor_template(category)
    result = preview(request())
    assert result.symbol is None and NO_SAFE_SYMBOL in result.warnings
    assert [r.status for r in result.rows] == ["invalid", "invalid"]
    assert all(NO_SAFE_SYMBOL in r.messages for r in result.rows)
    assert all("Library Ref" not in r.values for r in result.rows)
    summary = commit(None, request())
    assert summary["created"] == 0 and summary["invalid"] == 2
    assert fake_sync["symbols"] == [] and fake_sync["footprints"] == []  # nothing written, no backup needed
    assert summary["backup"] is None


def test_pinout_from_values_and_footprint(workspace: Workspace, fake_sync: dict[str, list[Any]]) -> None:
    """With the polarity known, SOT-23 has a standard pin-out (1 = B, 2 = E, 3 = C) – that is no guess."""
    transistor_template(fields={"Package": "{size}", "Polarity": "NPN"})
    result = preview(request())
    assert result.symbol is not None and result.symbol.kind == "npn"
    assert [r.status for r in result.rows] == ["new", "new"]
    summary = commit(None, request())
    assert summary["created"] == 2
    spec = fake_sync["symbols"][0][0]
    pins = {p.designator: p.name for p in spec.pins}
    assert pins == {"1": "B", "2": "E", "3": "C"}


def test_template_symbol_kind_needs_a_certain_pin_map(workspace: Workspace,
                                                      fake_sync: dict[str, list[Any]]) -> None:
    transistor_template(family="to92", sizes=[{"size": "SOT-23"}], symbol_kind="npn",
                        fields={"Package": "TO-92", "Polarity": "NPN"})
    result = preview(request())
    assert result.symbol is None and all(r.status == "invalid" for r in result.rows)
    assert NO_SAFE_SYMBOL in result.rows[0].messages  # TO-92: EBC, CBE, ECB or BCE – not derivable
    transistor_template(family="to92", symbol_kind="npn", symbol_params={"pinmap": "EBC"},
                        fields={"Package": "TO-92", "Polarity": "NPN"})
    chosen = preview(request())
    assert chosen.symbol is not None and [r.status for r in chosen.rows] == ["new", "new"]
    commit(None, request())
    pins = {p.designator: p.name for p in fake_sync["symbols"][0][0].pins}
    assert pins == {"1": "E", "2": "B", "3": "C"}


def test_unknown_symbol_kind(workspace: Workspace) -> None:
    transistor_template(symbol_kind="gibt_es_nicht", fields={"Package": "{size}", "Polarity": "NPN"})
    result = preview(request())
    assert result.symbol is None and any("unbekannt" in w for w in result.warnings)
    assert all(r.status == "invalid" for r in result.rows)


def _custom_category(default_symbol: str | None) -> None:
    categories.create_category(CategoryDef(
        table="Spezial", label="Spezialteile", prefix="SP", default_symbol=default_symbol,
        fields=[FieldDef(column="Rating", label="Nennwert", kind="text")]))


@pytest.mark.parametrize(("default_symbol", "valid"), [("diode", False), ("resistor", True), (None, False)])
def test_custom_category_default_only_without_pin_map(workspace: Workspace, fake_sync: dict[str, list[Any]],
                                                      default_symbol: str | None, valid: bool) -> None:
    _custom_category(default_symbol)
    transistor_template(category="Spezial", family="sod", fields={"Rating": "{value}", "Package": "{size}"})
    result = preview(request())
    assert all((r.status == "new") is valid for r in result.rows), [r.messages for r in result.rows]
    if valid:
        assert result.symbol is not None and result.symbol.kind == "resistor"
    else:
        assert result.symbol is None and NO_SAFE_SYMBOL in result.warnings


def test_fixed_library_ref_needs_no_generated_symbol(workspace: Workspace,
                                                     fake_sync: dict[str, list[Any]]) -> None:
    registry.upsert_symbol(SymbolRecord(name="NPN_BCE_HAUS", library="Symbols\\Haus.SchLib", status="ok"))
    transistor_template()
    result = preview(request(field_overrides={"Library Ref": "NPN_BCE_HAUS", "Polarity": "NPN"}))
    assert result.symbol is not None and result.symbol.name == "NPN_BCE_HAUS" and result.symbol.exists
    assert [r.status for r in result.rows] == ["new", "new"]
    summary = commit(None, request(field_overrides={"Library Ref": "NPN_BCE_HAUS", "Polarity": "NPN"}))
    assert summary["created"] == 2 and fake_sync["symbols"] == []
    stored = parts.get_part("Transistors BJT", "PXS-45V")
    assert stored is not None and stored["Library Ref"] == "NPN_BCE_HAUS"
    assert stored["Library Path"] == "Symbols\\Haus.SchLib"  # from the registry (db.parts)
    unknown = preview(request(field_overrides={"Library Ref": "UNBEKANNT", "Polarity": "NPN"}))
    assert any("UNBEKANNT" in w and "nicht registriert" in w for w in unknown.warnings)


def test_integrated_circuit_template_is_refused_before_writing(workspace: Workspace,
                                                               fake_sync: dict[str, list[Any]]) -> None:
    """Regression: the preview said "new" for rows that commit then rejected after writing symbol/footprints."""
    save_custom_template(MpnTemplate.model_validate({
        "id": "probe-ic", "manufacturer": "Probe", "series": "IC", "category": "Integrated Circuits",
        "title": "Probe IC", "pattern": "IC{size}-{value}",
        "variables": [{"name": "size", "label": "Gehäuse", "options": [{"code": "0603", "value": "0603"}]},
                      {"name": "value", "label": "Wert", "format": {"style": "rkm"}}],
        "sizes": [{"size": "0603"}],
        "footprint": {"family": "chip", "kind": "R"},
    }))
    req = SeriesRequest(template_id="probe-ic", values=["10k", "22k"])
    result = preview(req)
    assert result.counts["invalid"] == 2 and result.counts["new"] == 0
    summary = commit(None, req)
    assert summary["created"] == 0 and fake_sync["symbols"] == [] and fake_sync["footprints"] == []
