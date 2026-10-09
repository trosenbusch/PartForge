"""chip_request / request_from_package (series assistant and datasheet AI entry points)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from partforge.footprints import FootprintRequest, chip_request, generate, preview, request_from_package
from partforge.footprints.packages import normalize_dims, resolve_package

CORPUS = Path(__file__).parent / "data" / "corpus" / "manifest.json"


@pytest.mark.parametrize(("kind", "size", "expected_size"), [
    ("R", "0603", "0603"), ("r", "1608M", "0603"), ("C", "2012", "0805"), ("L", "0402/1005", "0402"),
    ("FB", "R0603", "0603"), ("LED", "0805", "0805"), ("D", "1206", "1206"), ("C", "0603 metric", "0201"),
    ("R", "2512_6332", "2512"),
])
def test_chip_request(kind, size, expected_size):
    req = chip_request(kind, size)
    assert req.family == "chip"
    assert req.params == {"kind": kind.upper(), "size": expected_size}
    spec = generate(req)
    assert len(spec.pads) == 2


def test_chip_request_density_and_errors():
    assert chip_request("C", "0805", density="L").density == "L"
    with pytest.raises(ValueError, match="Bauteilart"):
        chip_request("X", "0603")
    with pytest.raises(ValueError, match="Baugröße"):
        chip_request("R", "9999")


def test_chip_request_matches_series_names():
    assert generate(chip_request("R", "0603")).ipc_name == "RESC1608X50N"
    assert generate(chip_request("C", "0805")).ipc_name == "CAPC2012X145N"
    assert generate(chip_request("L", "0603")).ipc_name.startswith("INDC1608X")


@pytest.mark.parametrize(("name", "family", "extra"), [
    ("SOIC-8", "gullwing", {"variant": "SOIC", "pins": 8}),
    ("TSSOP-16 (RU-16)", "gullwing", {"variant": "TSSOP", "pins": 16}),
    ("MSOP-10 (RM-10)", "gullwing", {"variant": "MSOP", "pins": 10}),
    ("VSSOP-8", "gullwing", {"variant": "MSOP", "pins": 8}),
    ("SSOP-28 (DB)", "gullwing", {"variant": "SSOP", "pins": 28}),
    ("VQFN-32 5x5 (RHB)", "nolead", {"variant": "QFN", "pins": 32}),
    ("DFN-8 3x3 (DD)", "nolead", {"variant": "DFN", "pins": 8}),
    ("LFCSP_WD-10 3x3", "nolead", {"variant": "DFN", "pins": 10}),
    ("LFCSP-16", "nolead", {"variant": "QFN", "pins": 16}),
    ("LQFP-64", "qfp", {"variant": "LQFP", "pins": 64}),
    ("SOT-23", "sot23", {"pins": "3"}),
    ("SOT-23-5", "sot23", {"pins": "5"}),
    ("SOT23-6", "sot23", {"pins": "6"}),
    ("SOT-363", "sc70", {"pins": "6"}),
    ("SC-70-5", "sc70", {"pins": "5"}),
    ("SOT-523", "sot523", {"pins": "3"}),
    ("SOT-89", "sot89", {}),
    ("SOT-223", "sot223", {}),
    ("TO-252", "dpak", {"variant": "DPAK"}),
    ("D2PAK", "dpak", {"variant": "D2PAK"}),
    ("SOD-123F", "sod", {"variant": "SOD-123F"}),
    ("SMB", "do214", {"variant": "SMB"}),
    ("DO-214AC", "do214", {"variant": "SMA"}),
    ("MiniMELF", "melf", {"size": "MiniMELF SOD-80"}),
    ("0805", "chip", {"size": "0805"}),
    ("C0603", "chip", {"size": "0603", "kind": "C"}),
    ("PDIP-14", "dip", {"pins": 14}),
    ("SMD-8 gull wing (option S)", "gullwing", {"variant": "SOP", "pins": 8}),
    ("TO-92", "to92", {}),
    ("TO-220", "to220", {}),
    ("FBGA-256", "bga", {}),
    ("gullwing", "gullwing", {}),
    ("tantal", "molded", {"kind": "CAPMP"}),  # alias implies its parameters
    ("do41", "axial", {"size": "DO-41"}),
    ("caprd", "radial", {"kind": "CAPRD"}),
    ("sc75", "sot523", {"pins": "3", "preset": "SC-75"}),
    ("SOT-416", "sot523", {"pins": "3", "preset": "SC-75"}),
])
def test_resolve_package(name, family, extra):
    assert resolve_package(name) == (family, extra)


def test_resolve_unknown_package():
    with pytest.raises(ValueError, match="keiner Footprint-Familie"):
        resolve_package("Flux-Kompensator")


def test_normalize_dims_key_conventions():
    dims, extras = normalize_dims({
        "e_pitch": {"min": None, "nom": 1.27, "max": None, "basic": True},
        "D_body_length": {"min": 4.8, "nom": None, "max": 5.0, "note": "excl. flash"},
        "D_E_body": [2.9, 3.1],
        "EP_D2_E2": {"min": 3.35, "nom": 3.45, "max": 3.55},
        "A_max": 1.75, "A1_min": 0.1, "A1_max": 0.25,
        "unlabeled_side_view": "0.80 MAX / 0.55 NOM",
        "terminal_center_span_per_side": {"nom": 3.5},
        "n": 8,
    })
    assert extras == {"n": 8}
    assert dims["e"].nom == 1.27
    assert (dims["D"].min, dims["D"].max) == (4.8, 5.0)  # first key wins
    assert dims["E"].min == 2.9
    assert dims["D2"].nom == dims["E2"].nom == 3.45
    assert dims["A"].max == 1.75
    assert (dims["A1"].min, dims["A1"].max) == (0.1, 0.25)
    assert "terminal" not in dims and "unlabeled" not in dims


def test_request_from_ai_dimension_list():
    dims = [
        {"symbol": "A", "description": "height", "unit": "mm", "min": -1, "nom": -1, "max": 1.75},
        {"symbol": "b", "description": "lead width", "unit": "mm", "min": 0.31, "nom": -1, "max": 0.51},
        {"symbol": "D", "description": "body length", "unit": "mm", "min": 4.8, "nom": -1, "max": 5.0},
        {"symbol": "E", "description": "overall width", "unit": "mm", "min": 5.8, "nom": -1, "max": 6.2},
        {"symbol": "E1", "description": "body width", "unit": "mm", "min": 3.8, "nom": -1, "max": 4.0},
        {"symbol": "e", "description": "pitch", "unit": "mm", "min": -1, "nom": 1.27, "max": -1},
        {"symbol": "L", "description": "foot", "unit": "mm", "min": 0.4, "nom": -1, "max": 1.27},
        {"symbol": "theta", "description": "angle", "unit": "deg", "min": 0, "nom": -1, "max": 8},
    ]
    req = request_from_package("SOIC-8", dims)
    assert req.family == "gullwing"
    assert req.params["pins"] == 8 and req.params["e"] == 1.27
    assert req.params["A"] == {"min": 1.75, "nom": 1.75, "max": 1.75}
    spec = generate(req)
    assert spec.ipc_name == "SOIC127P600X175-8N"
    assert spec.pads[0].width == pytest.approx(1.95)


def test_nexperia_letters_he_e():
    req = request_from_package("SOT-23", {"HE": [2.1, 2.5], "E": [1.2, 1.4], "D": [2.8, 3.0], "Lp": [0.15, 0.45],
                                          "bp": [0.38, 0.48], "A": [0.9, 1.1], "e": 0.95})
    assert req.params["E"] == {"min": 2.1, "nom": 2.3, "max": 2.5}
    assert req.params["E1"] == {"min": 1.2, "nom": 1.3, "max": 1.4}
    assert req.params["L"]["max"] == 0.45 and req.params["b"]["min"] == 0.38
    assert len(generate(req).pads) == 3


def test_qfp_jedec_d_d1_letters():
    req = request_from_package("LQFP-48", {"D": 9.0, "E": 9.0, "D1": 7.0, "E1": 7.0, "e": 0.5,
                                           "b": [0.17, 0.27], "L": [0.45, 0.75], "A": {"max": 1.6}})
    assert req.params["HE"]["nom"] == 9.0 and req.params["E"]["nom"] == 7.0
    spec = generate(req)
    assert spec.ipc_name == "QFP50P900X900X160-48N"
    assert spec.pads[0].x == pytest.approx(-4.1625)


def test_preset_fills_missing_dimensions():
    req = request_from_package("TSSOP-16", {"b": [0.19, 0.30]})
    assert req.params["variant"] == "TSSOP"
    assert req.params["E1"] == {"min": 4.3, "max": 4.5}  # from the TSSOP-16 preset
    assert len(generate(req).pads) == 16


def test_bga_matrix_from_d1_e1():
    req = request_from_package("bga", {"D": [6.9, 7.1], "E": [6.9, 7.1], "D1": 5.6, "E1": 5.6, "e": 0.8,
                                       "b": 0.4, "A": {"max": 1.2}, "A1": [0.25, 0.35]})
    assert (req.params["rows"], req.params["cols"]) == (8, 8)
    assert len(generate(req).pads) == 64


def test_dip_row_spacing_snaps_to_standard():
    req = request_from_package("DIP-8", {"E": [7.62, 8.26], "E1": [6.1, 7.11], "D": [9.0, 10.0]})
    assert req.params["eA"] == 7.62


def test_extra_params_density_name_and_land_pattern():
    lp = {"pad_width_mm": 0.6, "pad_length_mm": 1.05, "row_spacing_mm": 2.7}
    req = request_from_package("SOT-23-5", {}, density="L", name="OPA656 DBV", land_pattern=lp,
                               params={"manufacturer": "TI"})
    assert req.density == "L" and req.name == "OPA656 DBV" and req.land_pattern == lp
    assert req.params["manufacturer"] == "TI"
    pv = preview(req, svg=False)
    assert pv.spec.name == "OPA656 DBV"
    assert pv.spec.pads[0].x == pytest.approx(-1.35)


@pytest.mark.skipif(not CORPUS.is_file(), reason="Datenblatt-Korpus fehlt")
def test_datasheet_corpus_packages():
    manifest = json.loads(CORPUS.read_text(encoding="utf-8"))
    count = 0
    for entry in manifest["entries"]:
        for key, package in (entry.get("packages") or {}).items():
            dims = package.get("dims_mm")
            if not dims:
                continue
            req = request_from_package(key, dims, land_pattern=package.get("land_pattern"))
            pv = preview(req, svg=False)
            errors = [i.message for i in pv.issues if i.severity == "error"]
            assert not errors, (key, errors)
            count += 1
    assert count >= 14


@pytest.mark.skipif(not CORPUS.is_file(), reason="Datenblatt-Korpus fehlt")
def test_corpus_ti_land_patterns_are_used():
    manifest = json.loads(CORPUS.read_text(encoding="utf-8"))
    opa = next(e for e in manifest["entries"] if e["file"].endswith("opa656.pdf"))
    soic = opa["packages"]["SOIC-8"]
    pv = preview(request_from_package("SOIC-8", soic["dims_mm"], land_pattern=soic["land_pattern"]), svg=False)
    pad = pv.spec.pads[0]
    # TI 4211283-2/D: pads 0.60 × 2.00, row centre distance 4.80
    assert (pad.width, pad.height, pad.x) == (pytest.approx(2.0), pytest.approx(0.6), pytest.approx(-2.4))
    vqfn = next(e for e in manifest["entries"] if e["file"].endswith("sn65lv1023a.pdf"))["packages"]["VQFN-32 5x5 (RHB)"]
    pv = preview(request_from_package("VQFN-32", vqfn["dims_mm"], land_pattern=vqfn["land_pattern"]), svg=False)
    assert len(pv.spec.pads) == 33
    pad1 = pv.spec.pads[0]
    assert (pad1.width, pad1.height) == (pytest.approx(0.85), pytest.approx(0.28))
    assert pad1.x - pad1.width / 2 == pytest.approx(-2.9)  # outer span 5.8 mm


def test_request_model_roundtrip():
    req = request_from_package("SOIC-8", {"A": {"max": 1.75}})
    assert FootprintRequest.model_validate_json(req.model_dump_json()) == req
