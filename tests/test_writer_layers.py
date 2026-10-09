"""Layer mapping between logical footprint layers, the Rust writer and the bridge."""
from __future__ import annotations

import pytest

from partforge.altium import layers as L
from partforge.workspace import LayerMap


def test_default_house_layer_map_to_rust_names():
    table = L.layer_map_table()
    assert table == {
        "top_copper": "Top Layer",
        "bottom_copper": "Bottom Layer",
        "top_silk": "Top Overlay",
        "bottom_silk": "Bottom Overlay",
        "top_paste": "Top Paste",
        "bottom_paste": "Bottom Paste",
        "top_mask": "Top Solder",
        "bottom_mask": "Bottom Solder",
        "courtyard": "Mechanical 15",
        "assembly": "Mechanical 9",
        "body3d": "Mechanical 13",
        "designator": "Mechanical 11",
        "comment": "Mechanical 19",
        "component_center": "Mechanical 17",
        "component_outline": "Mechanical 21",
        "keepout": "Keep-Out Layer",
    }
    assert all(L.is_rust_layer(name) for name in table.values())
    # Mech 2-7 carry the writer's typed aliases and stay unused by the default map
    assert not {f"Mechanical {n}" for n in range(2, 8)} & set(table.values())


#: Layer map of the older TR_* libraries (IPC-wizard numbering, uses the alias layers 5 and 7).
TR_LAYER_MAP = LayerMap(
    assembly="Mechanical 5",
    comment="Mechanical 7",
    designator="Mechanical 9",
    component_outline="Mechanical 19",
)


@pytest.mark.parametrize(
    ("spelling", "canonical"),
    [
        ("Mechanical 15", "Mechanical 15"),
        ("Mechanical15", "Mechanical 15"),
        ("mech 15", "Mechanical 15"),
        ("M15", "Mechanical 15"),
        ("Mechanical Layer 9", "Mechanical 9"),
        ("Top Courtyard", "Mechanical 4"),
        ("bottom courtyard", "Mechanical 5"),
        ("Top 3D Body", "Mechanical 6"),
        ("Multi Layer", "Multi-Layer"),
        ("MultiLayer", "Multi-Layer"),
        ("Top Solder Mask", "Top Solder"),
        ("Keep Out Layer", "Keep-Out Layer"),
        ("  Top   Overlay ", "Top Overlay"),
        ("Mid-Layer 3", "Mid-Layer 3"),
        ("Internal Plane 2", "Internal Plane 2"),
    ],
)
def test_normalize_layer_name(spelling, canonical):
    assert L.normalize_layer_name(spelling) == canonical


@pytest.mark.parametrize("bad", ["", "Mechanical 33", "Mechanical 0", "Courtyard", "Top", "Assembly", "Mid-Layer 31"])
def test_normalize_rejects_unknown_layers_with_german_message(bad):
    with pytest.raises(L.LayerError) as exc:
        L.normalize_layer_name(bad)
    assert "lage" in str(exc.value).lower()


def test_is_rust_layer_is_exact():
    assert L.is_rust_layer("Top Assembly")
    assert L.is_rust_layer("Mechanical 32")
    assert not L.is_rust_layer("Mechanical 33")
    assert not L.is_rust_layer("Mechanical 05")
    assert not L.is_rust_layer("TOP OVERLAY")
    assert not L.is_rust_layer("MultiLayer")
    assert not L.is_rust_layer(None)


def test_reverse_mapping_of_the_default_layer_map():
    assert L.altium_to_logical("Mechanical 9") == "assembly"
    assert L.altium_to_logical("Mechanical 11") == "designator"
    assert L.altium_to_logical("Mechanical 15") == "courtyard"
    assert L.altium_to_logical("Mechanical 17") == "component_center"
    assert L.altium_to_logical("Mechanical 19") == "comment"
    assert L.altium_to_logical("Mechanical 21") == "component_outline"
    assert L.altium_to_logical("Top Overlay") == "top_silk"
    assert L.altium_to_logical("Keep-Out Layer") == "keepout"
    assert L.altium_to_logical("Bottom Courtyard") is None  # Mechanical 5 is unused by default
    assert L.altium_to_logical("Mechanical 1") is None
    assert L.altium_to_logical("Nonsense") is None


def test_reverse_mapping_resolves_rust_aliases_to_house_layers():
    # The writer reads Mechanical 2..7 back as its aliases (TR_* libraries use Mechanical 5/7).
    assert L.altium_to_logical("Bottom Courtyard", TR_LAYER_MAP) == "assembly"
    assert L.altium_to_logical("Bottom 3D Body", TR_LAYER_MAP) == "comment"
    assert L.altium_to_logical("Mechanical 9", TR_LAYER_MAP) == "designator"
    assert L.altium_to_logical("Mechanical 19", TR_LAYER_MAP) == "component_outline"


def test_reverse_mapping_with_alias_based_layer_map_and_preference():
    layer_map = LayerMap(assembly="Top Assembly", courtyard="Top Courtyard", designator="Top Assembly")
    assert L.logical_to_altium("assembly", layer_map) == "Mechanical 2"
    assert L.altium_to_logical("Top Assembly", layer_map) == "assembly"
    assert L.altium_to_logical("Top Assembly", layer_map, prefer=("designator",)) == "designator"
    assert L.altium_to_logical("Top Courtyard", layer_map) == "courtyard"


def test_invalid_layer_map_entry_raises_with_settings_hint():
    with pytest.raises(L.LayerError) as exc:
        L.logical_to_altium("courtyard", LayerMap(courtyard="Mechanical 40"))
    assert "Einstellungen" in str(exc.value)


def test_pad_layers_and_sides():
    assert L.pad_layer("top") == "Top Layer"
    assert L.pad_layer("bottom") == "Bottom Layer"
    assert L.pad_layer("through") == "Multi-Layer"
    assert L.pad_side("Bottom Layer") == "bottom"
    assert L.pad_side("Multi-Layer") == "through"
    assert L.pad_side("Top Layer", has_hole=True) == "through"
    assert L.pad_side("garbage") == "top"
    with pytest.raises(L.LayerError):
        L.pad_layer("inner")  # type: ignore[arg-type]


def test_bridge_layer_tokens():
    assert L.bridge_layer_token("Top Layer") == "L1"
    assert L.bridge_layer_token("Bottom Layer") == "L32"
    assert L.bridge_layer_token("Multi-Layer") == "L74"
    assert L.bridge_layer_token("Top Overlay") == "L33"
    assert L.bridge_layer_token("Top Solder") == "L37"
    assert L.bridge_layer_token("Keep-Out Layer") == "L56"
    assert L.bridge_layer_token("Mechanical 15") == "M15"
    assert L.bridge_layer_token("Top Courtyard") == "M4"
    assert L.bridge_layer_token("Mechanical 19") == "M19"
    with pytest.raises(L.LayerError):
        L.bridge_layer_token("Mid-Layer 1")


def test_mechanical_helpers():
    assert L.mechanical_name(7) == "Mechanical 7"
    assert L.mechanical_number("Bottom 3D Body") == 7
    assert L.mechanical_number("Top Overlay") is None
    with pytest.raises(L.LayerError):
        L.mechanical_name(0)
