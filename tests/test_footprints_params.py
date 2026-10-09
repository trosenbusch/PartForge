"""Parameter parsing (partforge.footprints.params)."""
from __future__ import annotations

import pytest

from partforge.footprints.models import ParamSpec, Tol
from partforge.footprints.params import ParamError, Params, parse_tol, tol_to_json


@pytest.mark.parametrize(("value", "expected"), [
    (1.27, (1.27, 1.27, 1.27)),
    (2, (2.0, 2.0, 2.0)),
    ("0,5", (0.5, 0.5, 0.5)),
    ("1.0..1.2", (1.0, 1.1, 1.2)),
    ("1,0 - 1,2", (1.0, 1.1, 1.2)),
    ("6.0±0.2", (5.8, 6.0, 6.2)),
    ("6.0 +/- 0.2 mm", (5.8, 6.0, 6.2)),
    ({"min": 0.31, "max": 0.51}, (0.31, 0.41, 0.51)),
    ({"min": 0.31, "nom": 0.4, "max": 0.51}, (0.31, 0.4, 0.51)),
    ({"min": -1, "nom": 1.27, "max": -1}, (1.27, 1.27, 1.27)),  # datasheet-AI sentinels
    ({"min": None, "nom": None, "max": 1.75}, (1.75, 1.75, 1.75)),
    ({"min": 0.1, "nom": None, "max": None}, (0.1, 0.1, 0.1)),
    ({"nom": 3.0, "max": 3.1}, (2.9, 3.0, 3.1)),
    ({"min": 2.9, "nom": 3.0}, (2.9, 3.0, 3.1)),
    ({"min": 0.5, "max": 0.3}, (0.3, 0.4, 0.5)),  # swapped
    ([0.4, 1.27], (0.4, 0.835, 1.27)),
    ([0.4, 0.6, 0.8], (0.4, 0.6, 0.8)),
    ({"typ": 2.0}, (2.0, 2.0, 2.0)),
])
def test_parse_tol_forms(value, expected):
    t = parse_tol(value)
    assert (t.min, t.nom, t.max) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", {"min": None, "max": None}, {"min": -1, "nom": -1, "max": -1}])
def test_parse_tol_missing(value):
    assert parse_tol(value) is None


@pytest.mark.parametrize(("value", "message"), [
    ("abc", "keine gültige Zahl"),
    (True, "Zahl erwartet"),
    ([1, 2, 3, 4], "1 bis 3 Werten"),
    ({"min": 1.0, "nom": 2.0, "max": 1.5}, "Nennwert"),
    (object(), "ungültige Maßangabe"),
    (float("inf"), "endlich"),
])
def test_parse_tol_errors(value, message):
    with pytest.raises(ParamError, match=message):
        parse_tol(value, "Testmaß")


def test_tol_passthrough_and_json():
    t = Tol(min=1, max=2)
    assert parse_tol(t) is t
    assert tol_to_json(t) == {"min": 1.0, "nom": 1.5, "max": 2.0}


SPECS = [
    ParamSpec(name="L", label="Länge", kind="tol", default={"min": 1, "max": 2}),
    ParamSpec(name="pins", label="Pins", kind="int", default=8, minimum=2, maximum=10),
    ParamSpec(name="e", label="Raster", kind="float", minimum=0.3),
    ParamSpec(name="variant", label="Typ", kind="enum", options=["SOIC", "SSOP"], default="SOIC"),
    ParamSpec(name="flag", label="Schalter", kind="bool", default=False),
    ParamSpec(name="name", label="Name", kind="text"),
    ParamSpec(name="offset", label="Versatz", kind="tol", minimum=-1.0),
]


def test_params_defaults_and_resolved_record():
    p = Params({"pins": "6", "variant": "ssop", "flag": "ja"}, SPECS)
    assert p.tol("L") == Tol(min=1, max=2)
    assert p.int("pins") == 6
    assert p.enum("variant") == "SSOP"
    assert p.bool("flag") is True
    assert p.text("name") == ""
    assert p.float_opt("e") is None
    assert p.resolved == {"L": {"min": 1.0, "nom": 1.5, "max": 2.0}, "pins": 6, "variant": "SSOP", "flag": True}
    assert p.given("pins") and not p.given("L")


def test_params_errors_are_german():
    with pytest.raises(ParamError, match="Maximum 10"):
        Params({"pins": 12}, SPECS).int("pins")
    with pytest.raises(ParamError, match="ganze Zahl"):
        Params({"pins": 2.5}, SPECS).int("pins")
    with pytest.raises(ParamError, match="nicht zulässig"):
        Params({"variant": "QFN"}, SPECS).enum("variant")
    with pytest.raises(ParamError, match="Ja/Nein"):
        Params({"flag": "vielleicht"}, SPECS).bool("flag")
    with pytest.raises(ParamError, match="fehlt"):
        Params({}, SPECS).float("e")
    with pytest.raises(ParamError, match="Minimum"):
        Params({"e": 0.1}, SPECS).float("e")
    with pytest.raises(ParamError, match="negative"):
        Params({"L": [-1, 1]}, SPECS).tol("L")


def test_signed_tolerance_with_explicit_minimum():
    p = Params({"offset": [-0.5, 0.5]}, SPECS)
    assert p.tol("offset").min == -0.5
    with pytest.raises(ParamError, match="Minimum"):
        Params({"offset": [-2, 0.5]}, SPECS).tol("offset")


def test_given_handles_empty_dicts_and_strings():
    p = Params({"L": {"min": None, "max": None}, "name": "  "}, SPECS)
    assert not p.given("L") and not p.given("name")
