"""FamilyInfo extensions (aliases, supports_land_pattern) and parameter names of generator errors."""
from __future__ import annotations

import pytest

from partforge.footprints import (
    FootprintRequest,
    ParamError,
    error_params,
    families,
    family_info,
    generate,
    preview,
    supports_land_pattern,
)
from partforge.footprints.families import alias_names, registry, resolve
from partforge.footprints.params import Params, parse_tol
from partforge.footprints.models import ParamSpec
from partforge.workspace import FootprintStyle

STYLE = FootprintStyle()


def test_aliases_resolve_to_their_family():
    for info in families():
        assert info.key not in info.aliases
        for alias in info.aliases:
            assert resolve(alias)[0].info.key == info.key, alias


def test_alias_list_contains_aliases_and_alias_params_in_declaration_order():
    fam = registry()["sot23"]
    assert alias_names("sot23") == tuple(a for a in (*fam.aliases, *fam.alias_params) if a != "sot23")
    assert family_info("sot363").aliases == list(alias_names("sc70"))


def test_family_info_copies_are_independent():
    first = family_info("chip")
    first.aliases.append("kaputt")
    assert "kaputt" not in family_info("chip").aliases
    assert "kaputt" not in registry()["chip"].info.aliases  # module-level definition untouched


@pytest.mark.parametrize("key", list(registry()))
def test_land_pattern_flag_matches_the_generator(key):
    """supports_land_pattern == the generator really uses a manufacturer pattern for this family."""
    fam = registry()[key]
    params = {"preset": fam.info.presets[0].key} if fam.info.presets else {}
    ipc = preview(FootprintRequest(family=key, params=params), STYLE, svg=False).calc.get("lands") or []
    # the family's own IPC land as "manufacturer" pattern: valid geometry for every family
    lp = ({"pad_width": ipc[0]["x"], "pad_length": ipc[0]["pad_length"], "row_spacing": 2 * ipc[0]["pad_center"]}
          if ipc else {"pad_width": 0.4, "pad_length": 0.6, "row_spacing": 1.6})
    pv = preview(FootprintRequest(family=key, params=params, land_pattern=lp), STYLE, svg=False)
    used = any(land["source"] == "manufacturer" for land in pv.calc.get("lands", []))
    unsupported_note = any("nicht unterstützt" in w for w in pv.warnings)
    assert supports_land_pattern(key) is used
    assert unsupported_note is not used


def test_param_errors_name_their_parameter():
    specs = [ParamSpec(name="E1", label="Körperbreite E1"), ParamSpec(name="pins", label="Anschlüsse", kind="int")]
    p = Params({"E1": "abc", "pins": "x"}, specs)
    with pytest.raises(ParamError) as info:
        p.tol("E1")
    assert info.value.params == ("E1",) and "Körperbreite E1" in str(info.value)
    with pytest.raises(ParamError) as info:
        p.int("pins")
    assert info.value.params == ("pins",)
    with pytest.raises(ParamError) as info:
        Params({}, specs).tol("E1")  # missing
    assert info.value.params == ("E1",)
    with pytest.raises(ParamError) as info:
        parse_tol("abc", "Maß")  # module function: no parameter name known
    assert info.value.params == ()


def test_error_params_falls_back_to_labels():
    with pytest.raises(ValueError) as info:
        generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8", "E1": [6.5, 6.6]}), STYLE)
    assert not isinstance(info.value, ParamError) or not info.value.params
    assert error_params(info.value, "gullwing") == ["E1", "E"]
    assert error_params(info.value, "gibtsnicht") == []
    assert error_params(info.value) == []
    with pytest.raises(ParamError) as named:
        generate(FootprintRequest(family="qfp", params={"pins": 30}), STYLE)
    assert error_params(named.value, "qfp") == ["pins"]
