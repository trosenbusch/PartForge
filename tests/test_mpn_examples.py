"""Template examples (precomputed part number + segments for the template cards) and template facts."""
from __future__ import annotations

import copy

import pytest

from partforge.domain.mpn import (
    MpnError,
    MpnTemplate,
    compact,
    decode_mpn,
    encode_mpn,
    get_builtin,
    list_templates,
)
from partforge.domain.mpn.examples import mpn_segments, template_example, template_facts

TEMPLATES = list(list_templates())
IDS = [t.id for t in TEMPLATES]


@pytest.mark.parametrize("template", TEMPLATES, ids=IDS)
def test_every_builtin_template_has_a_valid_example(template: MpnTemplate) -> None:
    example = template_example(template)
    assert example is not None and example.valid and example.message is None, template.id
    assert compact("".join(s.text for s in example.segments)) == compact(example.mpn)
    assert all(s.text for s in example.segments)  # empty codes are left out
    decoded = decode_mpn(template, example.mpn)
    assert decoded is not None and decoded.valid and decoded.size == example.size, decoded
    assert example.value == pytest.approx(decoded.value)
    if template.kind == "pattern":
        assert encode_mpn(template, size=str(example.size), value=float(example.value or 0), codes=example.codes) == \
            example.mpn
    assert example.attrs.get("mpn") == example.mpn and example.attrs.get("size") == example.size


@pytest.mark.parametrize(("template_id", "mpn", "texts"), [
    ("vishay-crcw-e3", "CRCW060310K0FKEA", ["CRCW", "0603", "10K0", "F", "K", "EA"]),
    ("yageo-rc-l", "RC0603FR-0710KL", ["RC", "0603", "F", "R", "-", "07", "10K", "L"]),
    ("panasonic-erj-1pct", "ERJ-3EKF1002V", ["ERJ-", "3EK", "F", "1002", "V"]),
    ("uniohm-chip", "0603WAF1002T5E", ["0603", "WA", "F", "1002", "T", "5", "E"]),
    ("kemet-c-x7r", "C0603C104K5RACTU", ["C", "0603", "C", "104", "K", "5", "R", "AC", "TU"]),
    ("samsung-cl-x7r", "CL10B104KB8NNNC", ["CL", "10", "B", "104", "K", "B", "8", "NNN", "C"]),
    ("murata-grm-x7r", "GRM188R71H224KAC4D", ["GRM", "18", "8", "R7", "1H", "224", "K", "AC4", "D"]),  # in production
    ("bourns-srr1260", "SRR1260-100M", ["SRR", "1260", "-", "100", "M"]),
])
def test_known_examples(template_id: str, mpn: str, texts: list[str]) -> None:
    """Typical value (10 kΩ, 100 nF, 10 µH) in 0603 (else the middle size), capacitors at 50 V."""
    example = template_example(get_builtin(template_id))  # type: ignore[arg-type]
    assert example is not None and example.mpn == mpn
    assert [s.text for s in example.segments] == texts


def test_segment_meanings() -> None:
    example = template_example(get_builtin("kemet-c-x7r"))  # type: ignore[arg-type]
    assert example is not None
    by_name = {s.name: s for s in example.segments if s.name}
    size, value = by_name["size"], by_name["value"]
    assert size.kind == "size" and size.meaning == "0603 (1608)" and size.short == "Größe"
    assert value.kind == "value" and value.meaning == "100nF" and value.label == "Kapazität"
    assert by_name["voltage"].meaning == "50 V" and by_name["voltage"].short == "Spg."
    assert by_name["cspec"].label == "Verpackung (C-Spec)" and by_name["cspec"].short == "Verp."
    literals = [s for s in example.segments if s.kind == "literal"]
    assert literals and all(s.label == "fest" and s.name is None for s in literals)


def test_jumper_and_errors() -> None:
    vishay = get_builtin("vishay-crcw-e3")
    assert vishay is not None
    jumper = mpn_segments(vishay, size="0603", value=0.0, codes={"tolerance": "Z", "tcr": "0", "packaging": "EA"},
                          jumper=True)
    assert [s.text for s in jumper] == ["CRCW", "0603", "0000", "Z", "0", "EA"]
    assert jumper[2].label == "Brücke" and jumper[2].meaning == "0 Ω"
    with pytest.raises(MpnError, match="Baugröße"):
        mpn_segments(vishay, size="9999", value=1e3, codes={})
    with pytest.raises(MpnError, match="fehlt ein Code"):
        mpn_segments(vishay, size="0603", value=1e3, codes={"tolerance": "F"})


def test_examples_are_cached_and_copies_stay_independent() -> None:
    vishay = get_builtin("vishay-crcw-e3")
    assert vishay is not None
    first = template_example(vishay)
    assert template_example(vishay) is first  # built once per template object
    clone = vishay.model_copy(deep=True)  # regression: a cached example must not make deep copies recurse
    deep = copy.deepcopy(vishay)
    assert template_example(clone) == first and template_example(clone) is not first
    assert template_example(deep) == first
    changed = vishay.model_copy(update={"id": "andere"})
    assert template_example(changed) is not first


def test_custom_template_without_rules_and_unbuildable_examples() -> None:
    open_template = MpnTemplate.model_validate({
        "id": "offen", "manufacturer": "Haus", "series": "O", "category": "Resistors", "title": "Offen",
        "pattern": "O{size}-{value}",
        "variables": [{"name": "size", "label": "Baugröße", "options": [{"code": "0805", "value": "0805"}]},
                      {"name": "value", "label": "Wert", "format": {"style": "rkm"}}],
        "sizes": [{"size": "0805"}],
    })
    example = template_example(open_template)
    assert example is not None and example.mpn == "O0805-10K" and example.valid
    assert template_facts(open_template).mode == "open"
    no_value = open_template.model_copy(deep=True)
    no_value.rules = []
    no_value.sizes = []
    no_value.variables = [v for v in no_value.variables if v.name == "size"] + \
        [v.model_copy(update={"options": []}) for v in no_value.variables if v.name == "value"]
    no_value.variables[0].options = []
    assert template_example(no_value) is None  # no size to build an example with – never raises


def test_template_facts() -> None:
    facts = {t.id: template_facts(t) for t in TEMPLATES}
    assert facts["vishay-crcw-e3"].mode == "rules" and facts["vishay-crcw-e3"].value_range == [1.0, 10e6]
    assert facts["vishay-crcw-e3"].e_series == ["E24", "E96"] and facts["vishay-crcw-e3"].jumper
    assert facts["koa-rk73b"].e_series == ["E24"] and not facts["koa-rk73b"].jumper
    assert facts["kemet-c-x7r"].mode == "matrix" and facts["kemet-c-x7r"].value_range == [1e-11, 4.7e-05]
    assert facts["murata-grm-x7r"].mode == "catalog" and facts["murata-grm-x7r"].value_range == [1e-09, 4.7e-05]
    assert facts["bourns-srr1260"].value_range == [1e-06, 0.001]
