"""Decoding accepts only the manufacturer's spelling as valid; sizes are resolved by name, code, label or
metric code – never by numeric similarity (partforge.domain.mpn.engine)."""
from __future__ import annotations

import logging
from typing import Any

import pytest

from partforge.domain.mpn import (
    MpnError,
    MpnTemplate,
    decode_any,
    decode_mpn,
    get_template,
    resolve_size,
)


@pytest.mark.parametrize(("template_id", "typed", "canonical", "code"), [
    ("vishay-crcw-e3", "CRCW0603K100FKEA", "CRCW0603100RFKEA", "K100"),
    ("vishay-crcw-e3", "CRCW060304K7FKEA", "CRCW06034K70FKEA", "04K7"),
    ("vishay-crcw-e3", "CRCW06030K10FKEA", "CRCW0603100RFKEA", "0K10"),
    ("panasonic-erj-1pct", "ERJ-3EKF0472V", "ERJ-3EKF4701V", "0472"),
    ("yageo-rc-l", "RC0603FR-074K70L", "RC0603FR-074K7L", "4K70"),
    ("yageo-rc-l", "RC0603FR-0704K7L", "RC0603FR-074K7L", "04K7"),
    ("koa-rk73h", "RK73H1JTTD0472F", "RK73H1JTTD4701F", "0472"),
    ("kemet-c-x7r", "C0603C1R0K5RACTU", "C0603C109K5RACTU", "1R0"),  # KEMET writes 1.0 pF as 109
])
def test_other_spellings_are_never_valid(template_id: str, typed: str, canonical: str, code: str) -> None:
    """Regression: CRCW0603K100FKEA decoded as a valid (orderable) part number."""
    d = decode_mpn(get_template(template_id), typed)
    assert d is not None and not d.valid
    assert d.mpn == canonical
    assert d.messages[0] == f"Wertcode „{code}“ ist nicht die Schreibweise des Herstellers (richtig: {canonical})."
    right = decode_mpn(get_template(template_id), canonical)
    assert right is not None and right.mpn == canonical and right.value == d.value


@pytest.mark.parametrize(("template_id", "typed", "canonical"), [
    ("panasonic-erj-1pct", "erj3ekf4701v", "ERJ-3EKF4701V"),  # compact form, any case: still the same spelling
    ("bourns-cr", "CR0603FX1002ELF", "CR0603-FX-1002ELF"),
    ("yageo-rc-l", " rc0603fr-0710kl ", "RC0603FR-0710KL"),
])
def test_compact_forms_stay_valid(template_id: str, typed: str, canonical: str) -> None:
    d = decode_mpn(get_template(template_id), typed)
    assert d is not None and d.valid and d.mpn == canonical


def test_value_the_series_cannot_write(caplog: pytest.LogCaptureFixture) -> None:
    """Regression: the decoder raised MpnError (API 400, stack trace in decode_any) for 4-digit RKM codes."""
    caplog.set_level(logging.WARNING)
    d = decode_mpn(get_template("yageo-rc-l"), "RC0603FR-071234KL")
    assert d is not None and not d.valid and d.mpn == "RC0603FR-071234KL" and d.value == pytest.approx(1.234e6)
    assert d.messages[0].startswith("Wertcode „1234K“ ist nicht die Schreibweise des Herstellers")
    matches = decode_any("RC0603FR-071234KL")
    assert [m.template_id for m in matches] == ["yageo-rc-l"] and not matches[0].valid
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_decode_any_ranks_canonical_spelling_first() -> None:
    assert decode_any("CRCW0603100RFKEA")[0].valid
    assert not decode_any("CRCW0603K100FKEA")[0].valid


# --------------------------------------------------------------------------- sizes


@pytest.mark.parametrize(("template_id", "typed", "size"), [
    ("samsung-cl-x7r", "1005", "0402"),
    ("samsung-cl-x7r", "1608", "0603"),
    ("samsung-cl-x7r", "1608M", "0603"),
    ("samsung-cl-x7r", "0603 metrisch", "0201"),
    ("samsung-cl-x7r", "0402m", "01005"),
    ("samsung-cl-x7r", "0603", "0603"),
    ("samsung-cl-x7r", "01005", "01005"),
    ("samsung-cl-x7r", "10", "0603"),  # size code of the part number
    ("vishay-crcw-e3", "R0603", "0603"),  # alias of the footprint generator
    ("vishay-crcw-e3", "0603/1608", "0603"),
    ("vishay-crcw-e3", "0603 (1608)", "0603"),  # label
    ("koa-rk73h", "1J", "0603"),
    ("koa-rk73h", "w3a", "2512"),
    ("bourns-srr1260", "1260", "SRR1260"),
    ("bourns-srr1260", "srr1260", "SRR1260"),
])
def test_resolve_size(template_id: str, typed: str, size: str) -> None:
    assert resolve_size(get_template(template_id), typed) == size


@pytest.mark.parametrize("typed", ["402", "603", "0.603", "1e3", "", "  ", "0201"])
def test_unknown_sizes(typed: str) -> None:
    with pytest.raises(MpnError, match="Baugröße"):
        resolve_size(get_template("kemet-c-x7r"), typed)


def test_ambiguous_size() -> None:
    data: dict[str, Any] = {
        "id": "t-amb", "manufacturer": "T", "series": "T", "category": "Resistors", "title": "T",
        "pattern": "T{size}{value}",
        "variables": [{"name": "size", "label": "Baugröße", "options": [{"code": "A", "value": "A1"},
                                                                         {"code": "B", "value": "B1"}]},
                      {"name": "value", "label": "Wert", "format": {"style": "eia3"}}],
        "sizes": [{"size": "A1", "attrs": {"metric": "1608"}}, {"size": "B1", "attrs": {"metric": "1608"}}],
    }
    template = MpnTemplate.model_validate(data)
    assert resolve_size(template, "b") == "B1"
    with pytest.raises(MpnError, match="mehrdeutig"):
        resolve_size(template, "1608")
