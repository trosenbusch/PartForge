"""Template registry: built-in templates, user templates in pf_mpn_templates, decode over all templates."""
from __future__ import annotations

from typing import Any

import pytest

from partforge.db import mpn_templates
from partforge.domain.mpn import (
    MpnTemplate,
    TemplateError,
    TemplateNotFound,
    decode_any,
    delete_custom_template,
    get_template,
    list_custom_templates,
    list_templates,
    save_custom_template,
)
from partforge.workspace import Workspace


def custom(template_id: str = "my-res", **overrides: Any) -> MpnTemplate:
    data: dict[str, Any] = {
        "id": template_id, "manufacturer": "Hausmarke", "series": "HR", "category": "Resistors",
        "title": "Hauswiderstände", "pattern": "HR{size}-{value}{tolerance}",
        "variables": [
            {"name": "size", "label": "Baugröße", "options": [{"code": "0603", "value": "0603"}]},
            {"name": "value", "label": "Wert", "format": {"style": "rkm"}},
            {"name": "tolerance", "label": "Toleranz", "options": [{"code": "F", "value": "±1%", "default": True}]},
        ],
        "sizes": [{"size": "0603", "attrs": {"power": "0.1W"}}],
        "fields": {"Resistance": "{value}", "Tolerance": "{tolerance}", "Power": "{power}"},
    }
    data.update(overrides)
    return MpnTemplate.model_validate(data)


def test_builtins_without_library() -> None:
    from partforge.workspace import set_current

    set_current(None)
    all_templates = list_templates()
    assert len(all_templates) == 14 and all(t.builtin for t in all_templates)
    assert {t.id for t in list_templates("capacitors")} == {"kemet-c-x7r", "yageo-cc-x7r", "samsung-cl-x7r",
                                                            "murata-grm-x7r"}
    assert list_custom_templates() == []
    with pytest.raises(TemplateNotFound) as info:
        get_template("gibt-es-nicht")
    assert "nicht gefunden" in str(info.value)


def test_custom_template_lifecycle(workspace: Workspace) -> None:
    saved = save_custom_template(custom())
    assert not saved.builtin
    assert [t.id for t in list_custom_templates()] == ["my-res"]
    assert [t.id for t in list_custom_templates("Resistors")] == ["my-res"]
    assert list_custom_templates("Capacitors") == []
    loaded = get_template("my-res")
    assert loaded.title == "Hauswiderstände" and not loaded.builtin
    assert "my-res" in {t.id for t in list_templates("Resistors")}
    best = decode_any("HR0603-4K7F")[0]
    assert best.template_id == "my-res" and best.value == 4.7e3 and best.valid
    save_custom_template(custom(title="Neu"))
    assert get_template("my-res").title == "Neu"
    assert delete_custom_template("my-res") is True
    assert delete_custom_template("my-res") is False
    with pytest.raises(TemplateNotFound):
        get_template("my-res")


def test_custom_template_rules(workspace: Workspace) -> None:
    with pytest.raises(TemplateError, match="eingebauten"):
        save_custom_template(custom("vishay-crcw-e3"))
    with pytest.raises(TemplateError, match="Eingebaute"):
        delete_custom_template("vishay-crcw-e3")


def test_broken_stored_template_is_skipped(workspace: Workspace) -> None:
    mpn_templates.save_mpn_template("kaputt", "Kaputt", {"manufacturer": "x"}, category="Resistors")
    save_custom_template(custom())
    assert [t.id for t in list_custom_templates()] == ["my-res"]
    with pytest.raises(TemplateError, match="ungültig"):
        get_template("kaputt")


def test_decode_any_prefers_valid_matches() -> None:
    matches = decode_any("CRCW0603562RFKEA")
    assert matches and matches[0].template_id == "vishay-crcw-e3" and matches[0].valid
    assert decode_any("NIX-123") == []
    invalid = decode_any("CRCW06034K99JNEA")
    assert invalid and not invalid[0].valid


@pytest.mark.parametrize(("template_id", "message"), [
    ("Vishay-CRCW-E3", r"eingebauten Vorlage \(vishay-crcw-e3\)"),  # differs only in letter case
    ("custom", "reserviert"),  # /series/templates/custom is a route
    ("Test", "reserviert"),
])
def test_custom_ids_that_would_shadow_others(workspace: Workspace, template_id: str, message: str) -> None:
    with pytest.raises(TemplateError, match=message):
        save_custom_template(custom(template_id))


def test_uncompilable_template_is_not_stored(workspace: Workspace) -> None:
    from partforge.domain.mpn import MpnError

    broken = custom("broken-cells", availability=[{"size": "0603", "value": "XYZ", "codes": {"tolerance": "F"}}],
                    availability_keys=["tolerance"])
    with pytest.raises(MpnError, match="Matrixzelle"):
        save_custom_template(broken)
    assert list_custom_templates() == []


def test_custom_category_filter_ignores_letter_case(workspace: Workspace) -> None:
    save_custom_template(custom())
    assert [t.id for t in list_custom_templates("resistors")] == ["my-res"]
    assert [t.id for t in list_custom_templates("RESISTORS")] == ["my-res"]


def test_broken_user_template_does_not_break_decoding(caplog: pytest.LogCaptureFixture,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    import logging

    import partforge.domain.mpn.registry as registry_module

    original = registry_module.decode_mpn

    def decode(template: MpnTemplate, mpn: str) -> Any:
        if template.id == "bad-one":
            raise ValueError("Matrixzelle kaputt")
        return original(template, mpn)

    monkeypatch.setattr(registry_module, "decode_mpn", decode)
    caplog.set_level(logging.WARNING)
    matches = decode_any("HR0603-4K7F", [custom("bad-one"), custom()])
    assert [m.template_id for m in matches] == ["my-res"]
    warning = next(r for r in caplog.records if "bad-one" in r.getMessage())
    assert warning.levelno == logging.WARNING and warning.exc_info is None  # no stack trace for a known problem
