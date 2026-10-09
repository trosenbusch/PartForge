"""Template model validation and engine behaviour with small hand-written templates."""
from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from partforge.domain.mpn import (
    MpnError,
    MpnTemplate,
    compact,
    compile_template,
    decode_mpn,
    encode_mpn,
    find_option,
    in_series,
    parse_pattern,
    parse_series,
    render_fields,
    resolve,
    series_of_value,
)


def make(**overrides: Any) -> MpnTemplate:
    data: dict[str, Any] = {
        "id": "test-rc",
        "manufacturer": "Test",
        "series": "TR",
        "category": "Resistors",
        "title": "Test-Serie",
        "pattern": "TR{size}{tolerance}-{value}{packaging}",
        "variables": [
            {"name": "size", "label": "Baugröße",
             "options": [{"code": "06", "value": "0603"}, {"code": "08", "value": "0805"}]},
            {"name": "tolerance", "label": "Toleranz", "options": [
                {"code": "F", "value": "±1%", "default": True}, {"code": "J", "value": "±5%"}]},
            {"name": "value", "label": "Widerstand", "format": {"style": "eia4"},
             "format_overrides": [{"when": {"tolerance": ["J"]}, "format": {"style": "eia3"}}]},
            {"name": "packaging", "label": "Verpackung", "options": [
                {"code": "P", "requires": {"tape": ["paper"]}, "default": True},
                {"code": "B", "requires": {"tape": ["blister"]}, "default": True},
                {"code": "X", "sizes": ["0805"]}],
             "defaults": {}},
        ],
        "sizes": [{"size": "0603", "attrs": {"power": "0.1W", "tape": "paper"}},
                  {"size": "0805", "attrs": {"power": "0.125W", "tape": "blister"}}],
        "rules": [
            {"when": {"tolerance": ["F"]}, "ranges": [["10", "1M"]], "series": ["E24", "E96"],
             "attrs": {"tcr": "±100ppm/K"}},
            {"when": {"tolerance": ["J"]}, "ranges": [["1", "10M"]], "series": ["E24"], "attrs": {"tcr": "±200ppm/K"}},
        ],
        "fields": {"Resistance": "{value}", "Tolerance": "{tolerance}", "TCR": "{tcr}", "Power": "{power}",
                   "Notes": "{missing} ok"},
    }
    data.update(overrides)
    return MpnTemplate.model_validate(data)


def test_encode_decode_with_format_override_and_requires() -> None:
    t = make()
    res = resolve(t, size="0603", value=10e3, fixed={"tolerance": "F"})
    assert res.ok and res.codes == {"tolerance": "F", "packaging": "P"} and res.attrs["tcr"] == "±100ppm/K"
    assert encode_mpn(t, size="0603", value=10e3, codes=res.codes) == "TR06F-1002P"
    res = resolve(t, size="0805", value=4.7e3, fixed={"tolerance": "J"})
    assert res.codes["packaging"] == "B"  # requires tape=blister (size attribute)
    mpn = encode_mpn(t, size="0805", value=4.7e3, codes=res.codes)
    assert mpn == "TR08J-472B"
    d = decode_mpn(t, mpn)
    assert d is not None and d.valid and d.value == 4.7e3 and d.fields["TCR"] == "±200ppm/K"
    assert decode_mpn(t, "tr08j472b") is not None  # compact, case-insensitive
    wrong = decode_mpn(t, "TR06F-1002B")
    assert wrong is not None and not wrong.valid and "passend: P" in wrong.messages[0]
    size_only = decode_mpn(t, "TR06F-1002X")
    assert size_only is not None and not size_only.valid and "0603" in size_only.messages[0]


def test_rules_and_explanations() -> None:
    t = make()
    assert not resolve(t, size="0603", value=4.7, fixed={"tolerance": "F"}).ok
    res = resolve(t, size="0603", value=4.99e3, fixed={"tolerance": "J"})
    assert not res.ok and "E24" in res.messages[0]
    res = resolve(t, size="0603", value=22e6, fixed={"tolerance": "J"})
    assert not res.ok and "außerhalb" in res.messages[0]
    with pytest.raises(MpnError):
        encode_mpn(t, size="0603", value=4.99e3, codes={"tolerance": "J", "packaging": "P"})


def test_render_fields_skips_incomplete_templates() -> None:
    assert render_fields({"A": "{x} {y}", "B": "{x}", "C": "fix", "D": "{z}"}, {"x": "1", "y": "", "z": " "}) == \
        {"B": "1", "C": "fix"}
    d = decode_mpn(make(), "TR06F-1002P")
    assert d is not None and "Notes" not in d.fields


@pytest.mark.parametrize(("change", "message"), [
    ({"pattern": "TR{size}{tolerance}-{value}{packaging}{unknown}"}, "ohne Definition"),
    ({"pattern": "TR{size}{tolerance}{packaging}"}, "{value}"),
    ({"pattern": "TR{size}{tolerance}{value}{value}{packaging}"}, "nur einmal"),
    ({"pattern": "TR{size}{tolerance}{value}"}, "nicht verwendet"),
    ({"pattern": "TR{Size}{tolerance}{value}{packaging}"}, "Platzhalter"),
    ({"pattern": None}, "Muster"),
    ({"id": "bad id!"}, "Vorlagen-ID"),
    ({"title": "  "}, "leer"),
    ({"kind": "catalog", "catalog": []}, "Katalogeintrag"),
    ({"rules": [{"when": {"color": ["R"]}}]}, "unbekannte Variable"),
    ({"rules": [{"when": {"tolerance": ["Q"]}}]}, "unbekannten Code"),
    ({"sizes": [{"size": "1206"}]}, "ohne Code"),
    ({"fields": {"Resistance": "{Value}"}}, "Platzhalter"),
    ({"availability_keys": ["voltage"]}, "Matrix-Schlüssel"),
])
def test_validation_errors(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as info:
        make(**change)
    assert message in str(info.value)


def test_variable_validation() -> None:
    base = make().model_dump()
    variables = base["variables"]
    variables[1]["options"].append({"code": "F", "value": "±1%"})
    with pytest.raises(ValidationError, match="doppelt"):
        make(variables=variables)
    with pytest.raises(ValidationError, match="Werteformat"):
        make(variables=[*make().model_dump()["variables"][:2],
                        {"name": "value", "label": "W"}, make().model_dump()["variables"][3]])
    with pytest.raises(ValidationError, match="Variablenname"):
        make(variables=[{"name": "Size", "label": "x", "options": [{"code": "06"}]}])
    bad_default = make().model_dump()["variables"]
    bad_default[3]["defaults"] = {"0603": "Z"}
    with pytest.raises(ValidationError, match="Vorauswahl"):
        make(variables=bad_default)


def test_find_option() -> None:
    t = make()
    tol = compile_template(t).variables["tolerance"]
    assert find_option(tol, "F").code == "F"  # type: ignore[union-attr]
    assert find_option(tol, "1%").code == "F"  # type: ignore[union-attr]
    assert find_option(tol, "± 5 %").code == "J"  # type: ignore[union-attr]
    assert find_option(tol, "2%") is None
    assert find_option(tol, "") is None and find_option(tol, None) is None


def test_encode_errors() -> None:
    t = make()
    with pytest.raises(MpnError, match="Baugröße"):
        encode_mpn(t, size="1206", value=1e3, codes={"tolerance": "F", "packaging": "P"})
    with pytest.raises(MpnError, match="fehlt"):
        encode_mpn(t, size="0603", value=1e3, codes={"tolerance": "F"})
    with pytest.raises(MpnError, match="kein gültiger Code"):
        encode_mpn(t, size="0603", value=1e3, codes={"tolerance": "Q", "packaging": "P"})
    with pytest.raises(MpnError, match="Brücke"):
        encode_mpn(t, size="0603", value=0, codes={"tolerance": "F", "packaging": "P"}, jumper=True)
    assert decode_mpn(t, "") is None and decode_mpn(t, "XX06F-1002P") is None


def test_helpers() -> None:
    assert compact(" erj-3ekf 1002v ") == "ERJ3EKF1002V"
    assert parse_series("E24+E96") == ["E24", "E96"] and parse_series(["24", "e96"]) == ["E24", "E96"]
    with pytest.raises(MpnError):
        parse_series("E25")
    assert in_series(4.7e3, ["E24"]) and not in_series(4.75e3, ["E24"]) and in_series(4.75e3, ["E96"])
    assert in_series(1e6, ["E3"]) and not in_series(0, ["E24"])
    assert series_of_value(4.7) == "E3" and series_of_value(4.99) == "E96" and series_of_value(4.123) is None
    assert [s.variable for s in parse_pattern("A{x}B{y}") if s.variable] == ["x", "y"]
    with pytest.raises(ValueError):
        parse_pattern("A{x")


def test_compiled_template_is_cached() -> None:
    t = make()
    assert compile_template(t) is compile_template(t)
    assert compile_template(t.model_copy(deep=True)) is not compile_template(t)
    assert "_compiled" not in t.model_dump()


# --------------------------------------------------------------------------- characters, cross references


@pytest.mark.parametrize(("change", "message"), [
    ({"pattern": "TR'{size}{tolerance}-{value}{packaging}"}, "Das Muster enthält unzulässige Zeichen (')"),
    ({"pattern": "TR|{size}{tolerance}-{value}{packaging}"}, "Das Muster enthält unzulässige Zeichen (|)"),
    ({"pattern": "TR\t{size}{tolerance}-{value}{packaging}"}, r"unzulässige Zeichen ('\t')"),
    ({"jumper": {"value_code": "0'R"}}, "Wertcode der Brücke"),
    ({"jumper": {"value_code": " "}}, "darf nicht leer sein"),
    ({"kind": "catalog", "catalog": [{"mpn": "TR|1", "size": "0603", "value": "1k"}]}, "Teilenummer „TR|1“"),
    ({"rules": [{"when": {"tolerance": ["F"]}, "series": ["E25"]}]}, "Unbekannte E-Reihe"),
    ({"jumper": {"value_code": "0R", "codes": {"color": "R"}}}, "Brücke: unbekannte Variable"),
    ({"jumper": {"value_code": "0R", "codes": {"tolerance": "Z"}}}, "Brücke: „Z“ ist kein Code"),
    ({"jumper": {"value_code": "0R", "codes": {"tolerance": "J"}, "allowed": {"packaging": ["P"]}}},
     "ohne festen Code"),
    ({"symbol_params": {"pinmap": "KA"}}, "Symboltyp"),
    ({"availability": [{"size": "0603", "value": "1002", "codes": {"color": "R"}}]}, "unbekannte Variable"),
    ({"availability": [{"size": "0603", "value": "1002", "codes": {"tolerance": "Q"}}]}, "kein Code"),
])
def test_model_refuses_broken_data(change: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as info:
        make(**change)
    assert message in str(info.value)


def test_option_codes_refuse_part_number_characters() -> None:
    variables = make().model_dump()["variables"]
    variables[1]["options"].append({"code": "A'B", "value": "±2%"})
    with pytest.raises(ValidationError, match="unzulässige Zeichen"):
        make(variables=variables)


def test_series_names_are_normalised() -> None:
    t = make(rules=[{"when": {"tolerance": ["F"]}, "ranges": [["10", "1M"]], "series": ["e24", "96", "E24"]}])
    assert t.rules[0].series == ["E24", "E96"]


def test_compile_checks_matrix_and_catalog_values() -> None:
    bad_cell = make(availability=[{"size": "0603", "value": "1X2", "codes": {"tolerance": "F"}}],
                    availability_keys=["tolerance"])
    with pytest.raises(MpnError, match="Matrixzelle 0603 „1X2“"):
        compile_template(bad_cell)
    bad_catalog = make(kind="catalog", catalog=[{"mpn": "TR06F-1002P", "size": "0603", "value": "zehn"}])
    with pytest.raises(MpnError, match="Katalogeintrag TR06F-1002P"):
        compile_template(bad_catalog)


def test_jumper_with_alternative_codes() -> None:
    t = make(jumper={"value_code": "0R", "codes": {"tolerance": "J", "packaging": "P"}, "allowed": {"packaging": ["X"]}})
    res = resolve(t, size="0805", value=0.0, fixed={"packaging": "X"}, jumper=True)
    assert res.ok and res.codes["packaging"] == "X"  # an allowed alternative is kept
    res = resolve(t, size="0805", value=0.0, fixed={"packaging": "B"}, jumper=True)
    assert res.codes["packaging"] == "P" and any("Brücken gibt es nicht" in m for m in res.messages)
    assert decode_mpn(t, "TR08J-0RX").valid  # type: ignore[union-attr]
    wrong = decode_mpn(t, "TR08J-0RB")
    assert wrong is not None and not wrong.valid and "P / X" in wrong.messages[0]
