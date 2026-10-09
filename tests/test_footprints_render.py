"""SVG rendering of footprints."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from partforge.footprints import FootprintRequest, generate, render_svg
from partforge.footprints.render import THEMES
from partforge.geometry.model import Arc, FootprintSpec, Pad

NS = {"svg": "http://www.w3.org/2000/svg"}


def _layers(svg: str) -> dict[str, ET.Element]:
    root = ET.fromstring(svg)
    return {g.get("data-layer"): g for g in root.iter("{http://www.w3.org/2000/svg}g") if g.get("data-layer")}


@pytest.mark.parametrize(("family", "preset"), [
    ("chip", "R-0603"), ("gullwing", "SOIC-8"), ("nolead", "QFN-16-3x3-P0.5"), ("dip", "DIP-8"),
    ("radial", "D5x11-P2"), ("bga", "BGA-64-8x8-P0.8"),
])
@pytest.mark.parametrize("theme", ["dark", "light", "altium"])
def test_svg_is_well_formed_with_layer_groups(family, preset, theme):
    spec = generate(FootprintRequest(family=family, params={"preset": preset}))
    svg = render_svg(spec, theme=theme)
    root = ET.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.get("data-footprint") == spec.name
    assert root.find("svg:title", NS).text == spec.name
    layers = _layers(svg)
    assert {"courtyard", "assembly", "top_silk"} <= set(layers) or family == "bga"
    copper = layers.get("through") if family in ("dip", "radial") else layers.get("top_copper")
    shapes = [el for el in copper if el.tag.split("}")[1] in ("rect", "circle", "polygon")]
    assert len(shapes) >= len(spec.pads)
    texts = [el.text for el in copper if el.tag.endswith("text")]
    assert sorted(texts) == sorted(p.designator for p in spec.pads)
    assert THEMES[theme]["background"] in svg


def test_layer_filter_and_options():
    spec = generate(FootprintRequest(family="gullwing", params={"preset": "SOIC-8"}))
    svg = render_svg(spec, layers=["top_copper"], show_pad_numbers=False, grid=False, background=False,
                     width_px=300)
    layers = _layers(svg)
    assert set(layers) == {"top_copper"}
    root = ET.fromstring(svg)
    assert root.get("width") == "300"
    assert not [el for el in layers["top_copper"] if el.tag.endswith("text")]
    assert "pf-grid" not in svg


def test_texts_are_escaped_and_optional():
    spec = FootprintSpec(name='A<&>"B', pads=[Pad(designator="<1>", x=0, y=0, width=1, height=1)])
    svg = render_svg(spec, show_texts=True)
    root = ET.fromstring(svg)  # parses -> escaped correctly
    assert root.get("data-footprint") == 'A<&>"B'
    full = generate(FootprintRequest(family="chip", params={"preset": "R-0805"}))
    assert ".Designator" not in render_svg(full)
    assert ".Designator" in render_svg(full, show_texts=True)


def test_courtyard_is_dashed_and_paste_is_outline():
    spec = generate(FootprintRequest(family="nolead", params={"preset": "QFN-16-3x3-P0.5"}))
    layers = _layers(render_svg(spec))
    assert all(el.get("stroke-dasharray") for el in layers["courtyard"] if el.tag.endswith("line")
               and float(el.get("stroke-width")) < 0.1)
    assert all(el.get("fill") == "none" for el in layers["top_paste"])


def test_arcs_and_special_pad_shapes():
    spec = FootprintSpec(
        name="T",
        pads=[Pad(designator="1", x=0, y=0, width=1, height=1, shape="octagon"),
              Pad(designator="2", x=2, y=0, width=1.5, height=1, shape="oval", side="through", hole=0.6),
              Pad(designator="3", x=4, y=0, width=1, height=1, shape="rect", rotation=45),
              Pad(designator="4", x=6, y=0, width=1.6, height=1.0, side="through", hole=0.5, hole_length=1.0)],
        arcs=[Arc(layer="top_silk", cx=0, cy=2, r=1, start=0, end=90, width=0.1),
              Arc(layer="assembly", cx=0, cy=2, r=0.5, start=0, end=360, width=0.1)],
    )
    svg = render_svg(spec)
    ET.fromstring(svg)
    assert "<polygon" in svg and "rotate(-45" in svg and "<path d=\"M" in svg


def test_empty_footprint_renders():
    ET.fromstring(render_svg(FootprintSpec(name="leer")))
