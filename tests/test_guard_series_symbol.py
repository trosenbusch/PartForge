"""Series symbol guard: the fallback symbol of a series comes from ``templates.resolve_default_symbol``
(never a raw category default) – a pin-out is never guessed (ARCHITEKTUR §1.5/§9). TO-92 transistors and
dual transistors/MOSFETs make every row invalid with a German reason; nothing is written."""
from __future__ import annotations

from typing import Any

import pytest

from partforge.altium import sync
from partforge.db import registry, templates
from partforge.db.models import FootprintRecord, SymbolRecord
from partforge.domain.mpn import MpnTemplate, save_custom_template
from partforge.domain.series import NO_SAFE_SYMBOL, SeriesRequest, commit, preview
from partforge.workspace import Workspace


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    calls: dict[str, list[Any]] = {"symbols": [], "footprints": []}

    def ensure_symbols(specs, *, category=None, source="generated", ctx=None):
        calls["symbols"].extend(specs)
        return registry.upsert_symbols([SymbolRecord(name=s.name, library="Symbols\\PF.SchLib", spec=s, status="ok")
                                        for s in specs])

    def ensure_footprints(specs, *, source="generated", ctx=None):
        calls["footprints"].extend(specs)
        return registry.upsert_footprints([FootprintRecord(name=s.name, library="Footprints\\PF.PcbLib", spec=s,
                                                           status="ok") for s in specs])

    monkeypatch.setattr(sync, "ensure_symbols", ensure_symbols)
    monkeypatch.setattr(sync, "ensure_footprints", ensure_footprints)
    return calls


def template(category: str, family: str, fields: dict[str, str], *, params: dict[str, Any] | None = None,
             **extra: Any) -> MpnTemplate:
    data: dict[str, Any] = {
        "id": "guard-probe", "manufacturer": "Probe", "series": "GP", "category": category, "title": "Probe-Serie",
        "pattern": "GP{size}-{value}",
        "variables": [{"name": "size", "label": "Gehäuse", "options": [{"code": "P", "value": "PKG"}]},
                      {"name": "value", "label": "Spannung", "format": {"style": "rkm", "letters": {"V": 0}}}],
        "value_unit": "V",
        "sizes": [{"size": "PKG"}],
        "footprint": {"family": family, "params": params or {}},
        "fields": fields,
        **extra,
    }
    return save_custom_template(MpnTemplate.model_validate(data))


def request() -> SeriesRequest:
    return SeriesRequest.model_validate({"template_id": "guard-probe", "values": ["30V", "60V"]})


UNCERTAIN = {
    "TO-92 NPN": ("Transistors BJT", "to92", {"Package": "TO-92", "Polarity": "NPN"}, None),
    "Dual-MOSFET SO-8": ("Transistors FET", "gullwing", {"Package": "SOIC-8", "Channel": "Dual N"}, None),
    "Dual-MOSFET SOT-363": ("Transistors FET", "sot23", {"Package": "SOT-363", "Channel": "Dual N"}, {"pins": 6}),
    "Dual-NPN SOT-363": ("Transistors BJT", "sot23", {"Package": "SOT-363", "Polarity": "Dual NPN"}, {"pins": 6}),
}


@pytest.mark.parametrize("case", sorted(UNCERTAIN))
def test_uncertain_pinout_makes_every_row_invalid(case: str, workspace: Workspace,
                                                  written: dict[str, list[Any]]) -> None:
    category, family, fields, params = UNCERTAIN[case]
    template(category, family, fields, params=params)
    result = preview(request())
    assert result.symbol is None and NO_SAFE_SYMBOL in result.warnings
    assert [row.status for row in result.rows] == ["invalid", "invalid"]
    assert all(NO_SAFE_SYMBOL in row.messages and "Library Ref" not in row.values for row in result.rows)
    assert "nicht sicher bestimmbar" in NO_SAFE_SYMBOL  # German reason for the user
    summary = commit(None, request())
    assert summary["created"] == 0 and summary["invalid"] == 2 and summary["backup"] is None
    assert written == {"symbols": [], "footprints": []}  # nothing written


def test_template_kind_with_pin_map_is_not_forced_onto_a_dual_mosfet(workspace: Workspace,
                                                                     written: dict[str, list[Any]]) -> None:
    template("Transistors FET", "gullwing", {"Package": "SOIC-8", "Channel": "Dual N"}, symbol_kind="nmos")
    result = preview(request())
    assert result.symbol is None and all(NO_SAFE_SYMBOL in row.messages for row in result.rows)


def test_certain_standard_pinout_is_used(workspace: Workspace, written: dict[str, list[Any]]) -> None:
    """SOT-23 N-channel MOSFET: the standard pin-out (1 = G, 2 = S, 3 = D) follows from package + values."""
    template("Transistors FET", "sot23", {"Package": "SOT-23", "Channel": "N"})
    result = preview(request())
    assert result.symbol is not None and result.symbol.kind == "nmos"
    assert [row.status for row in result.rows] == ["new", "new"]
    assert commit(None, request())["created"] == 2
    pins = {pin.designator: pin.name for pin in written["symbols"][0].pins}
    assert pins == {"1": "G", "2": "S", "3": "D"}


def test_fallback_goes_through_resolve_default_symbol(workspace: Workspace, written: dict[str, list[Any]],
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: without a template symbol kind the series asks ``templates.resolve_default_symbol`` with the
    row values and the generated footprint – the category default kind alone never decides."""
    calls: list[tuple[str, dict[str, Any], Any]] = []
    original = templates.resolve_default_symbol

    def spy(category: Any, values: Any = None, style: Any = None, *, footprint: Any = None) -> Any:
        calls.append((category.table, dict(values or {}), footprint))
        return original(category, values, style, footprint=footprint)

    monkeypatch.setattr(templates, "resolve_default_symbol", spy)
    template("Transistors BJT", "to92", {"Package": "TO-92", "Polarity": "NPN"})
    assert all(row.status == "invalid" for row in preview(request()).rows)
    assert calls, "resolve_default_symbol wurde nicht gefragt"
    table, values, footprint = calls[0]
    assert table == "Transistors BJT" and values["Polarity"] == "NPN" and values["Package"] == "TO-92"
    assert footprint is not None and len(footprint.pads) == 3  # the generated TO-92 footprint
