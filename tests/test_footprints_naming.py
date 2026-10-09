"""Footprint naming: IPC-7351B (official 2010 IPC/Mentor naming PDF), IPC-7251 draft, house names."""
from __future__ import annotations

import pytest

from partforge.footprints import FootprintRequest, generate
from partforge.footprints import naming as nm
from partforge.workspace import FootprintStyle


@pytest.mark.parametrize(("name", "expected"), [
    # examples printed in the official naming convention PDF
    (nm.ipc_pitch_span("SOT", 2.30, 7.00, 1.80, 4, "N"), "SOT230P700X180-4N"),  # SOT-223
    (nm.ipc_pitch_span("TO", 2.28, 9.70, 2.38, 3, "N"), "TO228P970X238-3N"),  # generic DPAK
    (nm.ipc_sod("SOD", 3.70, 1.70, 1.35, "N"), "SOD3717X135N"),  # JEDEC SOD-123
    # format strings of the PDF applied to standard packages
    (nm.ipc_pitch_span("SOIC", 1.27, 6.00, 1.75, 8, "N"), "SOIC127P600X175-8N"),
    (nm.ipc_pitch_span("SOP", 0.65, 6.40, 1.20, 16, "N"), "SOP65P640X120-16N"),
    (nm.ipc_pitch_span("SOT", 0.95, 2.80, 1.45, 5, "N"), "SOT95P280X145-5N"),
    (nm.ipc_qfp(0.5, 9.0, 9.0, 1.6, 48, "N"), "QFP50P900X900X160-48N"),
    (nm.ipc_qfn("QFN", 0.5, 3.0, 3.0, 1.0, 17, "N"), "QFN50P300X300X100-17N"),
    (nm.ipc_chip("RESC", 1.6, 0.8, 0.55, "N"), "RESC1608X55N"),
    (nm.ipc_chip("CAPC", 2.0, 1.25, 1.45, "N", metric_code="2012"), "CAPC2012X145N"),
    (nm.ipc_chip("CAPMP", 3.2, 1.6, 1.8, "N"), "CAPMP3216X180N"),
    (nm.ipc_chip("RESC", 0.4, 0.2, 0.15, "L"), "RESC0402X15L"),
    (nm.ipc_melf("RESMELF", 3.5, 1.4, "M"), "RESMELF3514M"),
    (nm.ipc_bga(256, True, 1.0, 16, 16, 17.0, 17.0, 2.0), "BGA256C100P16X16_1700X1700X200"),
    (nm.ipc_dfn(2.0, 2.0, 0.6, 9, "N"), "DFN200X200X60-9N"),
    # IPC-7251 draft (through hole)
    (nm.ipc_dip(7.62, 0.56, 2.54, 9.58, 5.33, 8, "B"), "DIP762W56P254L958H533Q8B"),
    (nm.ipc_axial("RESAD", 10.16, 0.65, 6.30, 2.50, "B"), "RESAD1016W65L630D250B"),
    (nm.ipc_radial("CAPPRD", 2.0, 0.55, 5.0, 11.0, "B"), "CAPPRD200W55D500H1100B"),
    (nm.ipc_header(10, 0.64, 2.54, 1, 10, 25.40, 2.54, 8.54, "B"), "HDRV10W64P254_1X10_2540X254X854B"),
])
def test_ipc_name_examples(name, expected):
    assert name == expected


@pytest.mark.parametrize(("value", "f2", "f1"), [
    (6.0, "600", "60"), (0.95, "95", "10"), (1.27, "127", "13"), (0.05, "5", "01"), (15.245, "1525", "152"),
    (0.8, "80", "08"), (1.35, "135", "14"),
])
def test_number_codes(value, f2, f1):
    assert nm.f2(value) == f2
    assert nm.f1(value) == f1


@pytest.mark.parametrize(("family", "preset", "expected"), [
    ("sot223", "SOT-223", "SOT230P700X180-4N"),
    ("gullwing", "SOIC-8", "SOIC127P600X175-8N"),
    ("gullwing", "TSSOP-16", "SOP65P640X120-16N"),
    ("gullwing", "MSOP-8", "SOP65P490X110-8N"),
    ("sot23", "SOT-23-5", "SOT95P280X145-5N"),
    ("qfp", "LQFP-48-7x7-P0.5", "QFP50P900X900X160-48N"),
    ("nolead", "QFN-16-3x3-P0.5", "QFN50P300X300X80-17N"),
    ("molded", "Tantal-A", "CAPMP3216X180N"),
    ("chip", "C-0805", "CAPC2012X145N"),
    ("chip", "R-0603", "RESC1608X50N"),
    ("chip", "C-0603", "CAPC1608X87N"),
    ("pin_header", "1x10-P2.54", "HDRV10W64P254_1X10_2540X254X854B"),
    ("dip", "DIP-8", "DIP762W56P254L959H533Q8B"),
    ("bga", "BGA-256-16x16-P1", "BGA256C100P16X16_1700X1700X200"),
])
def test_generated_ipc_names(family, preset, expected):
    spec = generate(FootprintRequest(family=family, params={"preset": preset}))
    assert spec.ipc_name == expected
    assert spec.name == expected  # default naming = ipc


@pytest.mark.parametrize(("density", "suffix"), [("M", "M"), ("N", "N"), ("L", "L")])
def test_density_suffix(density, suffix):
    spec = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, density=density))
    assert spec.ipc_name.endswith(suffix)
    assert spec.density == density


def test_bga_nominal_keeps_official_name_other_densities_get_a_suffix():
    # official IPC BGA names have no density suffix, but M/L lands and courtyards differ -> unique names
    names = {d: generate(FootprintRequest(family="bga", params={"preset": "BGA-64-8x8-P0.8"}, density=d)).ipc_name
             for d in "MNL"}
    assert names == {"N": "BGA64C80P8X8_700X700X120", "M": "BGA64C80P8X8_700X700X120M",
                     "L": "BGA64C80P8X8_700X700X120L"}


HOUSE = FootprintStyle(naming="house")


@pytest.mark.parametrize(("family", "params", "density", "expected"), [
    ("chip", {"preset": "R-0603"}, "N", "RES 0603_1608"),
    ("chip", {"preset": "R-0603"}, "L", "RES 0603_1608 RF"),
    ("chip", {"preset": "R-2512"}, "N", "RES 2512_6432"),
    ("chip", {"preset": "C-1210-1.25"}, "N", "CAP 1210_3225 - 1.25MM"),
    ("chip", {"preset": "C-1210"}, "N", "CAP 1210_3225"),
    ("chip", {"preset": "FB-0603"}, "N", "FER 0603_1608"),
    ("molded", {"preset": "Tantal-D"}, "N", "CAP POL 2917_7343"),
    ("gullwing", {"preset": "SOIC-8"}, "N", "SOIC-8 3.9x4.9MM"),
    ("gullwing", {"preset": "TSSOP-14", "manufacturer": "TI", "package_code": "PW"}, "N", "TI TSSOP-14 4.4x5MM PW"),
    ("sot23", {"preset": "SOT-23-3"}, "N", "SOT-23-3"),
    ("sot23", {"preset": "SOT-23-3", "manufacturer": "ON SEMI"}, "N", "ON SEMI SOT-23-3"),
    ("nolead", {"preset": "QFN-16-3x3-P0.5"}, "N", "QFN-16 3x3MM EP1.75x1.75"),
    ("do214", {"preset": "SMA"}, "N", "DO-214AC SMA"),
    ("pin_header", {"preset": "2x05-P2.54"}, "N", "HEADER 2x05 P2.54"),
])
def test_house_names(family, params, density, expected):
    spec = generate(FootprintRequest(family=family, params=params, density=density), HOUSE)
    assert spec.name == expected
    assert not nm.name_problems(spec.name)


def test_name_override_is_sanitised():
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}, name="Mein/Widerstand: 10µ Ω*"))
    assert spec.name == "Mein-Widerstand- 10u Rx"
    assert spec.ipc_name == "RESC1608X50N"


def test_name_override_without_valid_characters_raises():
    with pytest.raises(ValueError, match="keine gültigen Zeichen"):
        generate(FootprintRequest(family="chip", params={"preset": "R-0603"}, name="???"))


def test_ascii_name_rules():
    assert nm.ascii_name("Größe ×2 <x>") == "Groesse x2 x"
    assert nm.ascii_name("a" * 80) == "a" * 64
    assert nm.ascii_name("  A   B  ") == "A B"
    for ch in '/\\:*?"<>|':
        assert ch not in nm.ascii_name(f"A{ch}B")


def test_name_problems():
    assert nm.name_problems("RES 0603_1608") == []
    assert nm.name_problems("")
    assert any("64" in p for p in nm.name_problems("x" * 65))
    assert any("unzulässige" in p for p in nm.name_problems("A/B"))


def test_ascii_text_transliteration():
    assert nm.ascii_text("Gehäuse Ø5 × 11 mm, 10 kΩ ±1 %") == "Gehaeuse D5 x 11 mm, 10 kOhm +-1 %"


def test_descriptions_follow_ipc_wizard_wording():
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}))
    assert spec.description == "Chip Resistor, 2-Leads, Body 1.60x0.80mm, IPC Medium Density"
    spec = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, density="L"))
    assert spec.description == "SOIC, 8-Leads, Body 4.90x3.90mm, Pitch 1.27mm, IPC High Density"
    spec = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5"}, density="M"))
    assert spec.description == ("QFN, 16-Leads, Body 3.00x3.00mm, Pitch 0.50mm, Thermal Pad 1.75x1.75mm, "
                                "IPC Low Density")
    for fam, preset in (("molded", "Tantal-A"), ("radial", "D5x11-P2"), ("bga", "BGA-64-8x8-P0.8")):
        text = generate(FootprintRequest(family=fam, params={"preset": preset})).description
        assert text.isascii()


def test_description_override():
    spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}, description="Mein Text"))
    assert spec.description == "Mein Text"
