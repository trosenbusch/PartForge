"""Soft hints of :func:`partforge.symbols.spec_warnings` (review finding F7)."""
from __future__ import annotations

from partforge.symbols import IcPin, ic_symbol, spec_warnings

_HINT = "Altium zeigt sie im SchLib eventuell falsch an"


def _ic(description: str):
    pins = [IcPin(designator="1", name="IN"), IcPin(designator="2", name="OUT"), IcPin(designator="3", name="GND")]
    return ic_symbol("E2E_COMP", pins).model_copy(update={"description": description})


def test_latin1_umlauts_in_description_give_no_hint() -> None:
    """Altium 26.10 reads a SchLib description with ä/ö/ü intact (VERIFIED) – no false warning."""
    for text in ("E2E Doppelkomparator, 2 Kanäle", "Größe 5 µm, ±0,5 °C", "Spannungsregler für Außenbereich"):
        assert not [w for w in spec_warnings(_ic(text)) if _HINT in w], text


def test_characters_outside_latin1_keep_the_hint() -> None:
    warnings = [w for w in spec_warnings(_ic("Shunt 10 mΩ, ≤ 5 V")) if _HINT in w]
    assert len(warnings) == 1
    assert "Latin-1" in warnings[0] and "Ω" in warnings[0] and "≤" in warnings[0]


def test_ascii_description_gives_no_hint() -> None:
    assert not [w for w in spec_warnings(_ic("Dual comparator")) if _HINT in w]
