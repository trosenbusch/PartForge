"""Data quality of generated series (regression for "123 Probleme" after a fresh UniOhm series).

Every built-in template – all sizes, a short value range, the 0-Ω jumper where the template offers
one – is written into a fresh test library (no writer: symbols/footprints stay "pending") and the
data-level health check (db.health) must report 0 errors and 0 warnings: jumpers have no tolerance,
TCR, power or voltage (db.values.not_applicable), asymmetric TCR bands like "-100 … +350ppm/K" are
valid values, and every stored value is canonical.
"""
from __future__ import annotations

from typing import Any

import pytest

from partforge.altium import sync
from partforge.db import health, parts
from partforge.domain.mpn import MpnTemplate, compile_template, format_value, list_templates
from partforge.domain.series import SeriesRequest, commit, preview
from partforge.domain.units import parse_value
from partforge.workspace import Workspace

BUILTIN_IDS = [t.id for t in list_templates()]
# short ranges: 9.1 … 11 Ω covers the low-ohm bands with asymmetric TCR (UniOhm/YAGEO 0201, Panasonic 5 %,
# Bourns "/") and the first values of series that start at 10 Ω
RANGES = {"Ω": ("9.1", "11"), "F": ("82n", "120n"), "H": ("10u", "22u")}


@pytest.fixture
def no_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """No library writer: the series registers symbol and footprints as "pending" (the real fallback)."""
    def not_available(*_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError

    monkeypatch.setattr(sync, "ensure_symbols", not_available)
    monkeypatch.setattr(sync, "ensure_footprints", not_available)


def _template(template_id: str) -> MpnTemplate:
    return next(t for t in list_templates() if t.id == template_id)


def _requests(template: MpnTemplate) -> list[SeriesRequest]:
    """Requests that cover every size of the template: the short range (rules: every size has values in
    it), the whole catalog, and for matrix sizes without a cell in the range one orderable cell value."""
    if template.kind == "catalog":
        return [SeriesRequest(template_id=template.id)]
    low, high = RANGES[template.value_unit]
    requests = [SeriesRequest(template_id=template.id, range_min=low, range_max=high,
                              include_jumper=template.jumper is not None)]
    if template.availability:
        ct = compile_template(template)
        tolerance = next(o.code for o in ct.variables["tolerance"].options if o.default)
        lo, hi = (parse_value(v, template.value_unit) or 0.0 for v in (low, high))
        for size in template.size_names():
            cells = ct.cells_by_size.get(size, [])
            if any(lo <= ct.cell_value(c) <= hi for c in cells):
                continue
            usable = [c for c in cells if not c.tolerances or tolerance in c.tolerances]
            cell = usable[len(usable) // 2]
            voltage = ct.variables["voltage"].option(cell.codes["voltage"])
            requests.append(SeriesRequest(template_id=template.id, sizes=[size],
                                          values=[format_value(ct.cell_value(cell), template.value_unit)],
                                          voltages=[voltage.value or voltage.code] if voltage else []))
    return requests


def test_every_builtin_template_is_covered() -> None:
    assert len(BUILTIN_IDS) == 14 and {t.value_unit for t in list_templates()} <= set(RANGES)


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
def test_fresh_series_passes_the_health_check(workspace: Workspace, no_writer: None, template_id: str) -> None:
    template = _template(template_id)
    sizes: set[str] = set()
    for request in _requests(template):
        planned = preview(request)
        assert planned.counts["new"] > 0, planned.warnings
        assert planned.counts["invalid"] == 0, [r.messages for r in planned.rows if r.status == "invalid"][:3]
        summary = commit(None, request)
        assert summary["created"] == planned.counts["new"] and summary["errors"] == 0, summary["error_details"]
        sizes.update(r.size for r in planned.rows)
        if template.jumper is not None and request.include_jumper:  # the jumper rows are part of the check
            jumpers = [r for r in planned.rows if r.jumper]
            assert jumpers and all(r.status == "new" for r in jumpers)
            stored = parts.get_part(template.category, str(jumpers[0].part_number))
            assert stored is not None and stored["Resistance"] == "0Ω" and stored["Tolerance"] is None
            assert stored["Notes"].startswith("0-Ω-Brücke (Jumper)") and "Nennstrom" in stored["Notes"]
            # no "Pflichtfeld ist leer" for the exempt fields (1218 outside the Size options is the only note)
            assert not [w for notes in summary["part_warnings"].values() for w in notes if "Pflichtfeld" in w]
    assert sizes == set(template.size_names())  # all sizes
    report = health.health_report(max_per_check=None)
    problems = [i for i in report["issues"] if i["severity"] in ("error", "warning")]
    assert report["counts"]["error"] == 0 and report["counts"]["warning"] == 0, problems[:5]
    # every stored value is canonical and every required field filled (only the Size option list may
    # lack a size such as 1218/1805 – an "enum" info)
    assert not [i for i in report["issues"] if i["check"] in ("required", "value", "format")]


def test_uniohm_asymmetric_tcr_is_stored_canonical(workspace: Workspace, no_writer: None) -> None:
    summary = commit(None, SeriesRequest(template_id="uniohm-chip", sizes=["0201"], values=["4.7", "47"],
                                         tolerance="5%"))
    assert summary["created"] == 2
    low = parts.get_part("Resistors", "0201WMJ047JTEE")
    high = parts.get_part("Resistors", "0201WMJ0470TEE")
    assert low is not None and low["TCR"] == "-100 … +350ppm/K"  # datasheet: 1≤R≤10: -100~+350 ppm/℃
    assert high is not None and high["TCR"] == "±200ppm/K"
    assert health.health_report()["counts"] == {"error": 0, "warning": 0, "info": 0}
    # filtering/sorting reads the band with its worst case
    found, total = parts.query_parts("Resistors", filters=[{"column": "TCR", "op": "gt", "value": "300"}])
    assert total == 1 and found[0]["Part Number"] == "0201WMJ047JTEE"
