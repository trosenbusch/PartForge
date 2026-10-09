"""Vendor letter conventions in request_from_package (review findings: pitch e/e1, chip T, tantalum S/A,
SOD span, shared presets, assumed values)."""
from __future__ import annotations

import pytest

from partforge.footprints import FootprintRequest, generate, presets, preview, request_from_package
from partforge.footprints.families import get_family
from partforge.footprints.packages import dimension_descriptions
from partforge.workspace import FootprintStyle

STYLE = FootprintStyle()


def _pin_ys(spec, designators=("1", "2", "3")) -> list[float]:
    pads = {p.designator: p for p in spec.pads}
    return [pads[d].y for d in designators]


# --------------------------------------------------------------------------- pitch e / e1 (Nexperia)

NEXPERIA = [  # ipc-footprints.md §3.8/§3.9: e = outer leads, e1 = pitch
    ("SOT-23", {"HE": [2.1, 2.5], "E": [1.2, 1.4], "D": [2.8, 3.0], "Lp": [0.15, 0.45], "bp": [0.38, 0.48],
                "A": [0.9, 1.1], "e": 1.9, "e1": 0.95}, 0.95, "SOT95P230X110-3N"),
    ("SOT-323", {"HE": [2.0, 2.2], "E": [1.15, 1.35], "D": [1.8, 2.2], "Lp": [0.15, 0.45], "bp": [0.3, 0.4],
                 "A": [0.8, 1.1], "e": 1.3, "e1": 0.65}, 0.65, "SOT65P210X110-3N"),
    ("SOT-89", {"HE": [3.75, 4.25], "E": [2.4, 2.6], "D": [4.4, 4.6], "Lp": [0.8, 1.2], "bp": [0.35, 0.48],
                "bp2": [0.40, 0.53], "bp3": [1.4, 1.8], "A": [1.4, 1.6], "e": 3.0, "e1": 1.5}, 1.5, "SOT89N"),
    ("SOT-223", {"HE": [6.7, 7.3], "E": [3.3, 3.7], "D": [6.3, 6.7], "Lp": [0.7, 1.1], "bp": [0.6, 0.8],
                 "b1": [2.9, 3.1], "A": [1.5, 1.8], "A1": [0.01, 0.1], "e": 4.6, "e1": 2.3}, 2.3,
     "SOT230P700X180-4N"),
]


@pytest.mark.parametrize(("package", "dims", "pitch", "ipc_name"), NEXPERIA, ids=[n[0] for n in NEXPERIA])
def test_nexperia_e_and_e1(package, dims, pitch, ipc_name):
    req = request_from_package(package, dims)
    assert req.params["e"] == pitch
    pv = preview(req, STYLE, svg=False)
    assert pv.spec.ipc_name == ipc_name
    assert _pin_ys(pv.spec, ("1", "3"))[0] == pytest.approx(pitch)
    assert not [i for i in pv.issues if i.severity == "error"]
    body = req.params["D"]["max"]
    assert all(abs(p.y) + p.height / 2 < body / 2 + 0.3 for p in pv.spec.pads if p.designator in ("1", "3"))


def test_swapped_e_and_e1_letters():
    req = request_from_package("SOT-23", {"e": 0.95, "e1": 1.9})  # Diodes Inc.: e pitch, e1 outer leads
    assert req.params["e"] == 0.95


def test_lone_outer_distance_is_halved_with_a_note():
    dims = {"HE": [2.1, 2.5], "E": [1.2, 1.4], "D": [2.8, 3.0], "Lp": [0.15, 0.45], "bp": [0.38, 0.48], "e": 1.9}
    req = request_from_package("SOT-23", dims)
    assert req.params["e"] == 0.95
    assert req.notes and "äußeren Anschlüsse" in req.notes[0]
    pv = preview(req, STYLE, svg=False)
    assert any("äußeren Anschlüsse" in w for w in pv.warnings)


def test_descriptions_name_the_pitch():
    dims = [
        {"symbol": "e", "description": "distance between outer leads", "unit": "mm", "min": -1, "nom": 3.0, "max": -1},
        {"symbol": "e1", "description": "lead pitch", "unit": "mm", "min": -1, "nom": 1.5, "max": -1},
    ]
    assert request_from_package("SOT-89", dims).params["e"] == 1.5
    outer_only = [{"symbol": "e", "description": "pin 1 to pin 3", "unit": "mm", "min": -1, "nom": 3.0, "max": -1}]
    assert request_from_package("SOT-89", outer_only).params["e"] == 1.5


@pytest.mark.parametrize(("family", "params"), [
    ("sot23", {"preset": "SOT-23-3", "e": 1.9}),
    ("sc70", {"preset": "SOT-363", "e": 1.3}),
    ("sot89", {"preset": "SOT-89-3", "e": 3.0}),
    ("sot223", {"preset": "SOT-223", "e": 4.6}),
    ("dpak", {"preset": "DPAK-3", "e": 4.57}),
])
def test_pin_row_longer_than_body_is_rejected(family, params):
    with pytest.raises(ValueError, match="länger als der Körper"):
        generate(FootprintRequest(family=family, params=params), STYLE)


# --------------------------------------------------------------------------- chip parts: T = thickness?


def test_kemet_letters_t_is_thickness_b_is_band():
    req = request_from_package("C1210", {"L": [3.0, 3.4], "W": [2.3, 2.7], "T": [0.68, 0.88], "B": [0.25, 0.75]})
    assert req.params["T"] == {"min": 0.25, "nom": 0.5, "max": 0.75}
    assert req.params["H"] == {"min": 0.68, "nom": 0.78, "max": 0.88}
    spec = generate(req, STYLE)
    assert spec.ipc_name == "CAPC3225X88N"
    pad1 = spec.pads[0]
    assert (pad1.width, pad1.x) == (pytest.approx(1.15), pytest.approx(-1.475))  # land from B, not from T
    # the C0603 variant of the same lettering used to fail with "Anschlusslänge T ist zu groß"
    small = generate(request_from_package("C0603", {"L": [1.45, 1.75], "W": [0.65, 0.95], "T": [0.73, 0.87],
                                                     "B": [0.2, 0.5]}), STYLE)
    assert small.ipc_name == "CAPC1608X87N"


def test_murata_letters_with_descriptions():
    dims = [
        {"symbol": "L", "description": "length", "unit": "mm", "min": 1.5, "nom": -1, "max": 1.7},
        {"symbol": "W", "description": "width", "unit": "mm", "min": 0.7, "nom": -1, "max": 0.9},
        {"symbol": "T", "description": "thickness", "unit": "mm", "min": 0.7, "nom": -1, "max": 0.9},
        {"symbol": "e", "description": "external electrode", "unit": "mm", "min": 0.2, "nom": -1, "max": 0.5},
    ]
    req = request_from_package("C0603", dims)
    assert req.params["T"]["max"] == 0.5 and req.params["H"]["max"] == 0.9


def test_vishay_resistor_letters():
    req = request_from_package("R0603", {"L": [1.5, 1.65], "W": [0.75, 0.95], "H": [0.4, 0.5], "T1": [0.1, 0.5],
                                         "T2": [0.1, 0.5]})
    assert req.params["T"] == {"min": 0.1, "nom": 0.3, "max": 0.5} and req.params["H"]["max"] == 0.5
    assert generate(req, STYLE).name == "RESC1608X50N"  # exactly the Vishay preset


@pytest.mark.parametrize(("dims", "role"), [
    ({"L": [1.45, 1.75], "W": [0.65, 0.95], "T": [0.7, 0.9]}, "H"),  # 2·T >= L: cannot be a terminal
    ({"L": [3.0, 3.4], "W": [1.4, 1.8], "H": [0.5, 0.6], "T": [0.25, 0.75]}, "T"),  # L/W/H/T notation
    ({"L": [3.0, 3.4], "W": [2.3, 2.7], "T": [0.68, 0.88]}, "H"),  # closer to an MLCC thickness than a band
    ({"T_thickness": [0.7, 0.9], "L": [1.45, 1.75], "W": [0.65, 0.95], "B_band": [0.2, 0.5]}, "H"),
])
def test_lone_t_is_resolved_by_plausibility(dims, role):
    req = request_from_package("C1210" if dims["L"][0] == 3.0 else "C0603", dims)
    t = dims.get("T") or dims.get("T_thickness")
    assert req.params[role]["min"] == t[0]


def test_tantalum_avx_and_kemet_letters():
    avx = request_from_package("tantal", {"L": [3.0, 3.4], "W": [1.4, 1.8], "H": [1.4, 1.8], "W1": [1.1, 1.3],
                                          "A": [0.5, 1.0], "S": [1.1, 1.3]})
    assert avx.params["F"]["min"] == 1.1 and avx.params["S"] == {"min": 0.5, "nom": 0.75, "max": 1.0}
    assert avx.params["H"]["max"] == 1.8
    kemet = request_from_package("tantal", {"L": [3.0, 3.4], "W": [1.4, 1.8], "H": [1.4, 1.8], "F": [1.1, 1.3],
                                            "S": [0.5, 1.0], "A": 1.2})
    assert kemet.params["S"] == {"min": 0.5, "nom": 0.75, "max": 1.0} and kemet.params["H"]["max"] == 1.8
    assert generate(kemet, STYLE).name == "CAPMP3216X180N"  # KEMET T491 case A = preset


# --------------------------------------------------------------------------- SOD / DO-214 span


def test_sod_with_diodes_letters_h_is_the_span():
    req = request_from_package("SOD-123", {"D": [2.55, 2.85], "E": [1.4, 1.7], "H": [3.55, 3.85], "L": [0.25, 0.4],
                                           "b": [0.52, 0.62], "A": [1.0, 1.35]})
    assert req.params["HE"]["min"] == 3.55 and req.params["E"]["max"] == 1.7
    pv = preview(req, STYLE, svg=False)
    assert pv.spec.pads[1].x == pytest.approx(1.675) and not pv.warnings
    assert pv.spec.name == "SOD3716X135N"  # = Diodes SOD-123 preset


def test_sod_e_is_the_span_only_when_longer_than_the_body():
    req = request_from_package("SOD-323", {"D": [1.6, 1.8], "E": [2.3, 2.7], "E1": [1.15, 1.35]})
    assert req.params["HE"]["min"] == 2.3 and req.params["E"]["min"] == 1.15
    req = request_from_package("SOD-323", {"D": [1.6, 1.8], "E": [1.15, 1.35]})
    assert req.params["E"]["min"] == 1.15 and req.params["HE"]["min"] == 2.3  # span from the preset
    assert "HE" in req.assumed


@pytest.mark.parametrize(("family", "params"), [
    ("sod", {"preset": "SOD-123", "HE": [1.4, 1.7]}),
    ("do214", {"preset": "SMA", "E": [2.29, 2.92], "T": [0.3, 0.5]}),
])
def test_lead_span_shorter_than_body_is_rejected(family, params):
    with pytest.raises(ValueError, match="größer als die Körperlänge"):
        generate(FootprintRequest(family=family, params=params), STYLE)


def test_do214_span_from_description():
    dims = [
        {"symbol": "A", "description": "overall length incl. leads", "unit": "mm", "min": 4.8, "nom": -1, "max": 5.59},
        {"symbol": "D", "description": "body length", "unit": "mm", "min": 4.0, "nom": -1, "max": 4.6},
    ]
    assert request_from_package("SMA", dims).params["E"]["max"] == 5.59


# --------------------------------------------------------------------------- shared presets, assumed values


def test_request_does_not_share_preset_dicts():
    req = request_from_package("SOIC-8", {"b": [0.31, 0.51]})
    req.params["E"]["min"] = 99.0
    req.params["E1"]["max"] = 99.0
    assert next(p for p in presets("gullwing") if p.key == "SOIC-8").params["E"] == {"min": 5.8, "max": 6.2}
    assert get_family("gullwing").info.presets[0].params["E1"] == {"min": 3.8, "max": 4.0}
    spec = generate(request_from_package("SOIC-8", {}), STYLE)
    spec.generator["params"]["E"]["min"] = 77.0
    assert get_family("gullwing").info.presets[0].params["E"] == {"min": 5.8, "max": 6.2}


def test_generator_record_does_not_share_request_dicts():
    req = FootprintRequest(family="gullwing", params={"preset": "SOIC-8", "L": {"min": 0.5, "max": 1.0}},
                           land_pattern={"pad_width": {"nom": 0.6}, "pad_length": 2.0, "row_spacing": 4.8})
    spec = generate(req, STYLE)
    req.params["L"]["min"] = 0.1
    req.land_pattern["pad_width"]["nom"] = 9.0  # type: ignore[index]
    assert spec.generator["params"]["L"]["min"] == 0.5
    assert spec.generator["land_pattern"]["pad_width"]["nom"] == 0.6


def test_assumed_values_are_reported():
    req = request_from_package("SOIC-8", {"b": [0.31, 0.51], "L": [0.4, 1.27]})
    assert req.assumed_from == "SOIC-8"
    assert "E" in req.assumed and "b" not in req.assumed and "pins" not in req.assumed
    pv = preview(req, STYLE, svg=False)
    note = next(w for w in pv.warnings if w.startswith("Nicht im Datenblatt angegeben"))
    assert "Gesamtbreite E" in note and "Anschlussdicke" not in note  # 3D-only values are not listed
    # explicit requests (no datasheet mapping) carry no such note
    assert not preview(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}), STYLE, svg=False).warnings


def test_assumed_part_kind_is_reported():
    req = request_from_package("0603", {"L": [1.45, 1.75], "W": [0.65, 0.95]})
    assert "kind" in req.assumed
    pv = preview(req, STYLE, svg=False)
    assert any("Bauteilart" in w for w in pv.warnings if w.startswith("Nicht im Datenblatt angegeben"))
    named = request_from_package("C0603", {"L": [1.45, 1.75], "W": [0.65, 0.95]})
    assert "kind" not in named.assumed


def test_missing_exposed_pad_from_datasheet_is_reported():
    req = request_from_package("VQFN-32", {"E": [4.9, 5.1], "L": [0.3, 0.5], "b": [0.18, 0.3], "e": 0.5})
    assert {"E2", "D2"} <= set(req.assumed)
    pv = preview(req, STYLE, svg=False)
    assert any(w.startswith("Exposed Pad nicht angegeben") and "E2 = 0" in w for w in pv.warnings)
    without = preview(request_from_package("VQFN-32", {"E": [4.9, 5.1], "L": [0.3, 0.5], "b": [0.18, 0.3],
                                                       "e": 0.5, "E2": 0}), STYLE, svg=False)
    assert len(without.spec.pads) == 32 and not any("Exposed Pad" in w for w in without.warnings)


def test_dimension_descriptions():
    assert dimension_descriptions({"T_thickness": 0.8, "B_band_width": [0.2, 0.5], "e": {"nom": 1.27,
                                                                                         "description": "pitch"}}) \
        == {"T": "thickness", "B": "band width", "e": "pitch"}
    assert dimension_descriptions([{"symbol": "e1", "description": "Pitch"}]) == {"e1": "pitch"}
    assert dimension_descriptions(None) == {}
