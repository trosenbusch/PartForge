"""Consistency of all built-in templates: metadata, field mapping, round trips, footprints."""
from __future__ import annotations

import math

import pytest

from partforge.db.templates import COMMON_FIELDS, category_by_table
from partforge.domain.eseries import values_in_range
from partforge.domain.mpn import compile_template, decode_mpn, encode_mpn, resolve
from partforge.domain.mpn.builtin import BUILTIN_FACTORIES, builtin_templates
from partforge.domain.mpn.model import MpnTemplate

TEMPLATES = list(builtin_templates())
IDS = [t.id for t in TEMPLATES]


def test_registry_basics() -> None:
    assert len(IDS) == len(set(IDS)) == len(BUILTIN_FACTORIES) == 14
    assert builtin_templates() is builtin_templates()  # built once
    assert {t.id for t in TEMPLATES if not t.verified} == set()  # Murata GRM verified 2026-10-08


@pytest.mark.parametrize("template", TEMPLATES, ids=IDS)
def test_metadata_and_field_mapping(template: MpnTemplate) -> None:
    assert template.builtin and template.sources and template.datasheet_url
    assert template.description and template.title
    category = category_by_table(template.category)
    assert category is not None, template.category
    columns = {f.column for f in COMMON_FIELDS} | {f.column for f in category.fields}
    assert set(template.fields) <= columns, set(template.fields) - columns
    value_column = category.value_field
    assert template.fields.get(value_column or "") == "{value}"
    # every size has a spec and the size variable maps back to it
    ct = compile_template(template)
    for spec in template.sizes:
        if template.kind == "pattern":
            assert spec.size in ct.size_code


def _sample_values(template: MpnTemplate, size: str, tolerance: str, series: list[str]) -> list[float]:
    ct = compile_template(template)
    spans = [(lo, hi) for r in ct.rules if (not r.sizes or size in r.sizes) for lo, hi in r.ranges]
    low, high = min(lo for lo, _ in spans), max(hi for _, hi in spans)
    values = sorted({v for name in series for v in values_in_range(name, low, high)})
    return values[::5] + values[-1:]


@pytest.mark.parametrize("template", [t for t in TEMPLATES if t.rules], ids=[t.id for t in TEMPLATES if t.rules])
def test_rule_templates_round_trip(template: MpnTemplate) -> None:
    ct = compile_template(template)
    tolerances = [o for o in ct.variables["tolerance"].options if not o.attrs.get("jumper_only")]
    produced = 0
    for size in template.size_names():
        for option in tolerances:
            series = option.attrs.get("eseries", "E24").split("+")
            for value in _sample_values(template, size, option.code, series):
                res = resolve(template, size=size, value=value, fixed={"tolerance": option.code})
                if not res.ok:
                    continue
                mpn = encode_mpn(template, size=size, value=value, codes=res.codes)
                d = decode_mpn(template, mpn)
                assert d is not None and d.valid, (mpn, d.messages if d else None)
                assert d.size == size and math.isclose(d.value or 0, value, rel_tol=1e-9) and d.codes == res.codes
                assert d.mpn == mpn
                produced += 1
        if template.jumper is not None and (not template.jumper.sizes or size in template.jumper.sizes):
            res = resolve(template, size=size, value=0.0, fixed={}, jumper=True)
            assert res.ok, (size, res.messages)
            mpn = encode_mpn(template, size=size, value=0.0, codes=res.codes, jumper=True)
            d = decode_mpn(template, mpn)
            assert d is not None and d.valid and d.jumper, mpn
    assert produced > 50


@pytest.mark.parametrize("template", [t for t in TEMPLATES if t.availability],
                         ids=[t.id for t in TEMPLATES if t.availability])
def test_matrix_templates_round_trip_every_cell(template: MpnTemplate) -> None:
    ct = compile_template(template)
    for cell in template.availability:
        tolerance = cell.tolerances[0] if cell.tolerances else "K"
        value = ct.cell_value(cell)
        fixed = {"tolerance": tolerance, **{k: cell.codes[k] for k in template.availability_keys}}
        res = resolve(template, size=cell.size, value=value, fixed=fixed)
        assert res.ok, (cell, res.messages)
        mpn = encode_mpn(template, size=cell.size, value=value, codes=res.codes)
        d = decode_mpn(template, mpn)
        assert d is not None and d.valid and d.mpn == mpn and d.attrs["height"] == cell.attrs["height"], mpn


@pytest.mark.parametrize("template", [t for t in TEMPLATES if t.catalog], ids=[t.id for t in TEMPLATES if t.catalog])
def test_catalog_entries_decode(template: MpnTemplate) -> None:
    for entry in template.catalog:
        d = decode_mpn(template, entry.mpn)
        assert d is not None and d.valid and d.mpn == entry.mpn


@pytest.mark.parametrize("template", TEMPLATES, ids=IDS)
def test_footprints_can_be_generated_for_every_size(template: MpnTemplate) -> None:
    from partforge.domain.series import _footprint_for, _FootprintCache

    cache = _FootprintCache(density=None, height_mode="class")
    names = set()
    for size in template.size_names():
        spec = _footprint_for(template, size, {}, cache)
        assert spec.pads and len(spec.pads) == 2, (template.id, size)
        names.add(spec.name)
    assert names
