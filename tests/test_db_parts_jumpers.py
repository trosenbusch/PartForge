"""0-Ω jumpers saved by hand or imported behave like series jumpers (K9): tolerance, TCR, power rating and
working voltage do not apply (``values.not_applicable``) – no required-field errors or warnings for them."""
from __future__ import annotations

import pytest

from partforge.db import categories, parts
from partforge.db.errors import PartValidationError
from partforge.workspace import Workspace

BASE = {"Manufacturer": "Vishay", "Description": "Brücke", "Library Ref": "Resistor", "Footprint Ref": "RESC1608X55N"}


def test_manual_jumper_needs_no_tolerance_or_power(workspace: Workspace) -> None:
    categories.update_field("Resistors", "TCR", {"required": True})
    categories.update_field("Resistors", "Voltage", {"required": True})
    warnings: list[str] = []
    part = parts.create_part("Resistors", {**BASE, "Part Number": "CRCW06030000Z0EA", "Resistance": "0R"},
                             warnings=warnings)
    assert part["Resistance"] == "0Ω" and part["Tolerance"] is None and part["Power"] is None
    assert not [w for w in warnings if "Pflichtfeld" in w]
    # a resistor with a value still needs them
    with pytest.raises(PartValidationError) as err:
        parts.create_part("Resistors", {**BASE, "Part Number": "R-1K", "Resistance": "1k"})
    assert {"Tolerance", "Power", "TCR", "Voltage"} <= set(err.value.errors)


def test_jumper_still_needs_the_fields_that_apply(workspace: Workspace) -> None:
    with pytest.raises(PartValidationError) as err:
        parts.create_part("Resistors", {**BASE, "Part Number": "J-1", "Resistance": "0", "Footprint Ref": None})
    assert set(err.value.errors) == {"Footprint Ref"}


def test_imported_and_updated_jumpers(workspace: Workspace) -> None:
    result = parts.upsert_parts("Resistors", [{**BASE, "Part Number": "J-IMP", "Resistance": "0Ω"}], strict=True)
    assert result.created == ["J-IMP"] and not result.errors and not result.warnings
    plans = parts.plan_upsert("Resistors", [{**BASE, "Part Number": "J-NEW", "Resistance": "0"}])
    assert plans[0].status == "create" and not plans[0].missing and not plans[0].warnings
    # turning a jumper into a real resistor makes the fields required again
    with pytest.raises(PartValidationError) as err:
        parts.update_part("Resistors", "J-IMP", {"Resistance": "10k"})
    assert {"Tolerance", "Power"} <= set(err.value.errors)
    # updating another field of a jumper never asks for them
    parts.update_part("Resistors", "J-IMP", {"Manufacturer": "Yageo"})


def test_validate_part_knows_jumpers(workspace: Workspace) -> None:
    out = parts.validate_part("Resistors", {**BASE, "Part Number": "J-VAL", "Resistance": "0R"})
    assert out["errors"] == {} and not [w for w in out["warnings"] if "Pflichtfeld" in w]
