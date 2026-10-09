"""Footprint names are unique per land pattern (identity.py): plain names for standard packages,
stable ``_<TAG>`` suffixes for custom/datasheet dimensions, geometry hashes for library writers."""
from __future__ import annotations

from collections import defaultdict

import pytest

from partforge.footprints import FootprintRequest, chip_request, families, generate, request_from_package
from partforge.footprints import identity
from partforge.footprints import naming as nm
from partforge.footprints.families import get_family
from partforge.footprints.families.chip import TABLES
from partforge.workspace import FootprintStyle

IPC = FootprintStyle()
HOUSE = FootprintStyle(naming="house")
SOIC_A = {"L": [0.4, 1.27], "b": [0.31, 0.51]}  # = SOIC-8 preset values
SOIC_B = {"L": [0.6, 0.9], "b": [0.35, 0.45]}  # another vendor's drawing


@pytest.mark.parametrize("style", [IPC, HOUSE, FootprintStyle(rounding="ipc")], ids=["ipc", "house", "fine"])
def test_names_never_shared_by_different_land_patterns(style):
    """Invariant over every preset × density: one name -> one land pattern."""
    by_name: dict[str, set[str]] = defaultdict(set)
    tagged = set()
    for info in families():
        for preset in info.presets:
            for density in "MNL":
                spec = generate(FootprintRequest(family=info.key, params={"preset": preset.key}, density=density),
                                style)
                if spec.generator["name_tag"]:
                    tagged.add((info.key, preset.key))
                by_name[spec.name].add(spec.generator["land_hash"])
    # presets keep plain names, except a preset whose name an earlier preset already uses for another land
    assert tagged == ({("sot523", "SC-75")} if style.naming == "ipc" else set())
    clashes = {name: hashes for name, hashes in by_name.items() if len(hashes) > 1}
    assert not clashes


def test_datasheet_dimensions_get_a_tag_and_identical_input_the_same_name():
    a = generate(request_from_package("SOIC-8", SOIC_A), IPC)
    b = generate(request_from_package("SOIC-8", SOIC_B), IPC)
    b2 = generate(request_from_package("SOIC-8", dict(SOIC_B)), IPC)
    assert a.name == "SOIC127P600X175-8N" and a.generator["standard"]
    assert b.name == "SOIC127P600X175-8N_F130"  # tag values are part of the contract: they name library parts
    assert b.ipc_name == a.ipc_name == "SOIC127P600X175-8N"  # the IPC attribute stays official
    assert b2.name == b.name and b2.generator["land_hash"] == b.generator["land_hash"]
    assert a.generator["land_hash"] != b.generator["land_hash"]
    assert a.pads[0].width != b.pads[0].width


def test_tag_does_not_depend_on_the_house_style():
    req = request_from_package("SOIC-8", SOIC_B)
    tags = {generate(req, style).generator["name_tag"]
            for style in (IPC, HOUSE, FootprintStyle(rounding="ipc"), FootprintStyle(pad_corner_radius_pct=25))}
    assert tags == {"F130"}
    assert generate(req, HOUSE).name == "SOIC-8 3.9x4.9MM_F130"


def test_bga_densities_have_distinct_names():
    names = {generate(FootprintRequest(family="bga", params={"preset": "BGA-64-8x8-P0.8"}, density=d), IPC).name
             for d in "MNL"}
    assert len(names) == 3


def test_three_d_only_parameters_do_not_create_new_names():
    base = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}), IPC)
    thick = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8", "c": [0.17, 0.25],
                                                                 "A1": [0.1, 0.2]}), IPC)
    assert thick.name == base.name
    assert thick.generator["land_hash"] == base.generator["land_hash"]
    assert thick.generator["geometry_hash"] != base.generator["geometry_hash"]  # the 3D leads differ
    # the height only enters as its maximum: same maximum -> same name, other maximum -> other name
    same_max = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8", "A": {"max": 1.75}}), IPC)
    assert same_max.name == base.name
    lower = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8", "A": [1.0, 1.5]}), IPC)
    # another maximum height changes the name; it still gets a tag because a preset with this height field
    # but another land could exist (LQFP-32 vs TQFP-32 differ only in the height field of the IPC name)
    assert lower.name.startswith("SOIC127P600X150-8N_")


def test_land_relevant_overrides_create_tags():
    plain = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}), IPC)
    assert plain.name == "RESC1608X50N"
    for extra in ({"fab_tolerance": 0.2}, {"rounding": "ipc"}, {"courtyard_excess": 0.5}, {"min_copper_gap": 0.2},
                  {"T": [0.2, 0.4]}):
        spec = generate(FootprintRequest(family="chip", params={"preset": "R-0603", **extra}), IPC)
        assert spec.name.startswith("RESC1608X50N_"), extra
    # values equal to the house style or the IPC default keep the plain name
    for extra in ({"fab_tolerance": 0.1}, {"placement_tolerance": 0.05}, {"rounding": "kicad"},
                  {"courtyard_excess": 0.25}, {"min_copper_gap": 0.15}, {"manufacturer": "Vishay"}):
        assert generate(FootprintRequest(family="chip", params={"preset": "R-0603", **extra}), IPC).name == \
            "RESC1608X50N", extra


def test_manufacturer_land_pattern_gets_a_tag():
    lp = {"pad_width_mm": 0.6, "pad_length_mm": 2.0, "row_spacing_mm": 4.8}
    spec = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}, land_pattern=lp), IPC)
    assert spec.name.startswith("SOIC127P600X175-8N_") and spec.ipc_name == "SOIC127P600X175-8N"


def test_series_and_standard_heights_keep_plain_names():
    for kind, table in TABLES.items():
        for size in table:
            spec = generate(chip_request(kind, size), IPC)
            assert spec.generator["standard"], (kind, size)
            assert "_" not in spec.name, (kind, size)
    # MLCC thickness variant from a datasheet (KEMET 1210, thickness code FB 0.78 ± 0.10)
    req = request_from_package("C1210", {"L": [3.0, 3.4], "W": [2.3, 2.7], "T": [0.68, 0.88], "B": [0.25, 0.75]})
    assert generate(req, IPC).name == "CAPC3225X88N"


def test_pin_headers_of_any_size_are_standard():
    spec = generate(FootprintRequest(family="pin_header", params={"rows": "1", "pins_per_row": 7}), IPC)
    assert spec.name == "HDRV7W64P254_1X7_1778X254X854B"
    custom = generate(FootprintRequest(family="pin_header", params={"rows": "1", "pins_per_row": 7, "post": 0.5}),
                      IPC)
    assert custom.name.startswith("HDRV7W50P254_1X7_") and custom.generator["name_tag"]


def test_regeneration_keeps_custom_names():
    spec = generate(request_from_package("SOIC-8", SOIC_B), IPC)
    g = spec.generator
    again = generate(FootprintRequest(family=g["family"], params=g["params"], density=g["density"]), IPC)
    assert again.name == spec.name and again.pads == spec.pads


def test_generator_record_has_hashes():
    spec = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5"}), IPC)
    g = spec.generator
    assert len(g["land_hash"]) == len(g["geometry_hash"]) == identity.HASH_LENGTH
    assert g["land_hash"] == identity.land_hash(spec) and g["geometry_hash"] == identity.geometry_hash(spec)
    assert g["version"] == 2 and g["standard"] is True and g["name_tag"] is None


def test_tag_survives_long_names():
    req = FootprintRequest(family="gullwing", params={"preset": "SOIC-8", **SOIC_B,
                                                      "manufacturer": "A very long manufacturer name GmbH & Co"})
    spec = generate(req, HOUSE)
    assert spec.name.endswith("_" + spec.generator["name_tag"]) and len(spec.name) <= nm.MAX_NAME_LENGTH
    assert not nm.name_problems(spec.name)
    assert nm.with_tag("X" * 80, "ABCD") == "X" * 59 + "_ABCD"
    assert nm.with_tag("RESC1608X50N", None) == "RESC1608X50N"


def test_reverse_markers():
    assert nm.ipc_reverse("SOD3716X135N") == "SOD3716X135RN"
    assert nm.ipc_reverse("DIOAD1016W86L464D236B") == "DIOAD1016W86L464D236RB"
    assert nm.house_reverse("SOD-123 RF", "L") == "SOD-123 AK RF"
    assert nm.house_reverse("SOD-123", "N") == "SOD-123 AK"


def test_matching_preset_rules():
    info = get_family("gullwing").info
    resolved = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-14"}), IPC).generator["params"]
    assert identity.matching_preset(info, resolved) == "SOIC-14"
    assert identity.matching_preset(info, {**resolved, "L": {"min": 0.5, "max": 1.0}}) is None
    free = identity.matching_preset(info, {**resolved, "c": {"min": 0.2, "max": 0.3}}, free=frozenset({"c"}))
    assert free == "SOIC-14"
    styled = {**resolved, "rounding": "ipc"}
    assert identity.matching_preset(info, styled) is None
    assert identity.matching_preset(info, styled, style_values={"rounding": "ipc"}) == "SOIC-14"
    assert identity.matching_preset(info, {**resolved, "pins": 99}, references=[{**resolved, "pins": 99}]) == "#0"


def test_alternate_presets_with_colliding_ipc_names_keep_a_tag():
    # SOT-523 (Diodes) and SC-75 (Nexperia SOT416) share SOT50P160X90-3 but differ in the foot length
    first = generate(FootprintRequest(family="sot523", params={"preset": "SOT-523"}, density="L"), IPC)
    second = generate(FootprintRequest(family="sot523", params={"preset": "SC-75"}, density="L"), IPC)
    assert first.name == first.ipc_name == second.ipc_name == "SOT50P160X90-3L"
    assert second.name.startswith("SOT50P160X90-3L_")
    assert first.pads != second.pads
    # house names already differ (custom body suffix), so both keep them
    assert generate(FootprintRequest(family="sot523", params={"preset": "SC-75"}), HOUSE).name ==         "SOT-523 0.8x1.6MM"
