"""SVG rendering of symbol specs (themes, parts, overbars, escaping)."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from partforge.geometry.model import SymbolSpec, SymPin, SymRect, SymText
from partforge.symbols import SymbolError, SymbolRequest, example_request, generate, kinds, render_parts, render_svg
from partforge.symbols.models import IcPin
from partforge.workspace import SymbolStyle

NS = {"svg": "http://www.w3.org/2000/svg"}
STYLE = SymbolStyle()


def parse(svg: str) -> ET.Element:
    root = ET.fromstring(svg)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    return root


def view_box(root: ET.Element) -> tuple[float, float, float, float]:
    x, y, w, h = (float(v) for v in root.attrib["viewBox"].split())
    return x, y, w, h


@pytest.mark.parametrize("theme", ["altium", "dark", "light"])
@pytest.mark.parametrize("kind", [k.key for k in kinds()])
def test_every_kind_renders_well_formed_svg(kind: str, theme: str) -> None:
    spec = generate(example_request(kind), STYLE)
    for part, svg in enumerate(render_parts(spec, theme=theme, style=STYLE), start=1):
        root = parse(svg)
        x, y, w, h = view_box(root)
        assert w > 0 and h > 0 and w < 30_000 and h < 30_000
        assert root.attrib["data-part"] == str(part)
        assert root.find("svg:title", NS).text == spec.name
        # every visible pin of the part is drawn
        pins = root.findall(".//svg:line[@class='pin']", NS)
        expected = [p for p in spec.pins if p.part in (0, part) and not p.hidden]
        assert len(pins) == len(expected)
        # the viewBox contains every pin end
        for p in expected:
            for px, py in ((p.x, p.y), p.tip()):
                assert x <= px <= x + w and y <= -py <= y + h


def test_altium_theme_uses_house_colours_and_white_sheet() -> None:
    svg = render_svg(generate(SymbolRequest(kind="diode"), STYLE), theme="altium", style=STYLE)
    root = parse(svg)
    background = root.find("svg:rect", NS)
    assert background is not None and background.attrib["fill"] == "#FFFFFF"
    assert "#0000FF" in svg  # discrete blue
    dark = render_svg(generate(SymbolRequest(kind="diode"), STYLE), theme="dark", style=STYLE)
    assert "#0000FF" not in dark and "#E8EBF2" in dark
    assert parse(dark).find("svg:rect", NS) is None  # transparent background


def test_ic_body_fill_per_theme() -> None:
    spec = generate(SymbolRequest(kind="connector", params={"pins": 3}), STYLE)
    assert 'fill="#FFFFB0"' in render_svg(spec, theme="altium", style=STYLE)
    dark = render_svg(spec, theme="dark", style=STYLE)
    assert 'fill="#FF8A3D"' in dark and 'fill-opacity="0.14"' in dark
    light = render_svg(spec, theme="light", style=STYLE)
    assert 'fill="#E8681A"' in light


def test_overbar_rendering() -> None:
    pins = [
        IcPin(designator="1", name="R\\E\\S\\E\\T\\", electrical="input"),
        IcPin(designator="2", name="C\\S\\/A", electrical="input"),
        IcPin(designator="3", name="OUT", electrical="output"),
    ]
    spec = generate(SymbolRequest(kind="ic", name="OVR", pins=pins), STYLE)
    svg = render_svg(spec, style=STYLE)
    root = parse(svg)
    bars = root.findall(".//svg:line[@class='overbar']", NS)
    assert len(bars) == 2  # one run for RESET, one for CS
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert "RESET" in texts and "CS/A" in texts and "OUT" in texts
    assert not any("\\" in (t or "") for t in texts)
    stretched = [t for t in root.iter("{http://www.w3.org/2000/svg}text") if t.text == "RESET"]
    assert stretched[0].attrib.get("textLength")
    lengths = sorted(float(b.attrib["x2"]) - float(b.attrib["x1"]) for b in bars)
    assert lengths[0] < lengths[1]  # "CS" bar shorter than "RESET" bar


def test_part_selection_and_errors() -> None:
    spec = generate(SymbolRequest(kind="opamp_dual"), STYLE)
    svgs = render_parts(spec, style=STYLE)
    assert len(svgs) == 3
    power = parse(svgs[2])
    assert len(power.findall(".//svg:line[@class='pin']", NS)) == 2
    assert "U?C" in svgs[2] and "U?A" in svgs[0]
    with pytest.raises(SymbolError, match="Teil 4"):
        render_svg(spec, part=4)
    with pytest.raises(SymbolError, match="Farbschema"):
        render_svg(spec, theme="neon")
    with pytest.raises(SymbolError, match="Maßstab"):
        render_svg(spec, scale=0)


def test_labels_and_hidden_pins() -> None:
    pins = [
        IcPin(designator="1", name="A", electrical="input"),
        IcPin(designator="2", name="VCC", electrical="power", hidden=True),
    ]
    spec = generate(SymbolRequest(kind="ic", name="HID", pins=pins), STYLE)
    plain = parse(render_svg(spec, labels=False, style=STYLE))
    assert plain.find(".//svg:g[@class='label-designator']", NS) is None
    assert len(plain.findall(".//svg:line[@class='pin']", NS)) == 1
    full = parse(render_svg(spec, show_hidden=True, style=STYLE))
    assert full.find(".//svg:g[@class='label-designator']", NS) is not None
    assert len(full.findall(".//svg:line[@class='pin']", NS)) == 2


def test_text_is_escaped_and_free_text_rendered() -> None:
    spec = SymbolSpec(
        name="ESC",
        designator_prefix="U",
        comment="<&>",
        pins=[SymPin(designator="1", name="A&B<C>", x=0, y=-100, orientation="left")],
        graphics=[SymRect(x1=0, y1=-200, x2=400, y2=0), SymText(x=100, y=-150, text="x<y", justify="middle_center")],
    )
    svg = render_svg(spec, style=STYLE)
    root = parse(svg)
    texts = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text")]
    assert "A&B<C>" in texts and "<&>" in texts and "x<y" in texts


def test_empty_spec_and_arcs() -> None:
    empty = parse(render_svg(SymbolSpec(name="EMPTY"), style=STYLE))
    assert view_box(empty)[2] > 0
    inductor = render_svg(generate(SymbolRequest(kind="inductor"), STYLE), style=STYLE)
    assert inductor.count("<path") == 4  # four half-circle arcs
    hole = render_svg(generate(SymbolRequest(kind="mounting_hole"), STYLE), style=STYLE)
    assert hole.count("<ellipse") == 2


def test_render_tolerates_foreign_text_positions() -> None:
    spec = generate(SymbolRequest(kind="resistor"), STYLE)
    for positions in ([1, 2], "x", {"designator": [0], "comment": {"x": "a", "y": 1}},
                      {"designator": {"x": 0, "y": 0, "justify": "foo_bar"}},
                      {"designator": {"x": float("inf"), "y": 0}}):
        broken = spec.model_copy(update={"generator": {**(spec.generator or {}), "text_positions": positions}})
        root = parse(render_svg(broken, style=STYLE))
        assert root.find(".//svg:g[@class='label-designator']", NS) is not None
    no_generator = spec.model_copy(update={"generator": None})
    parse(render_svg(no_generator, style=STYLE))


def test_render_prefers_contract_text_positions() -> None:
    from partforge.geometry.model import TextPos

    spec = generate(SymbolRequest(kind="resistor"), STYLE)
    moved = spec.model_copy(update={"designator_pos": TextPos(x=700, y=900), "comment_pos": None})
    root = parse(render_svg(moved, style=STYLE))
    designator = root.find(".//svg:g[@class='label-designator']", NS)
    comment = root.find(".//svg:g[@class='label-comment']", NS)
    assert designator is not None and designator.attrib["transform"].startswith("translate(700 -900)")
    assert comment is not None and comment.attrib["transform"].startswith("translate(-50 150)")  # generator


def test_render_rejects_broken_geometry() -> None:
    spec = generate(SymbolRequest(kind="resistor"), STYLE)
    with pytest.raises(SymbolError, match="Teileanzahl"):
        render_parts(spec.model_copy(update={"part_count": 20000}), style=STYLE)
    with pytest.raises(SymbolError, match="Teileanzahl"):
        render_svg(spec.model_copy(update={"part_count": 65}), style=STYLE)
    for value in (float("nan"), float("inf"), 5e6):
        broken = spec.model_copy(deep=True)
        rect = next(g for g in broken.graphics if isinstance(g, SymRect))
        rect.x1 = value
        with pytest.raises(SymbolError, match="Koordinaten"):
            render_svg(broken, style=STYLE)
    far_pin = spec.model_copy(deep=True)
    far_pin.pins[0].x = 2_000_000
    with pytest.raises(SymbolError, match="Koordinaten"):
        render_svg(far_pin, style=STYLE)


def test_scale_controls_pixel_size() -> None:
    spec = generate(SymbolRequest(kind="resistor"), STYLE)
    small = parse(render_svg(spec, scale=0.1, style=STYLE))
    big = parse(render_svg(spec, scale=0.5, style=STYLE))
    assert float(big.attrib["width"]) == pytest.approx(5 * float(small.attrib["width"]))


# --------------------------------------------------------------------------- thumbnails


def test_thumbnail_mode_sans_font_and_non_scaling_strokes() -> None:
    from partforge.symbols import render_thumbnail
    from partforge.symbols.render import THUMBNAIL_FONT, THUMBNAIL_STROKE_PX

    spec = generate(SymbolRequest(kind="opamp_dual"))
    normal = render_svg(spec, labels=False, scale=0.15)
    thumb = render_thumbnail(spec, theme="dark")
    assert "Times" in normal and "vector-effect" not in normal
    assert f'font-family="{THUMBNAIL_FONT}"' in thumb and "Times" not in thumb
    assert "pf-symbol-thumbnail" in thumb and "label-designator" not in thumb
    widths = set(re.findall(r'stroke-width="([^"]+)"', thumb))
    assert widths == {f"{THUMBNAIL_STROKE_PX:g}"}
    assert thumb.count('vector-effect="non-scaling-stroke"') == thumb.count("stroke-width=")
    # geometry and size are the same as the normal rendering
    assert re.search(r'viewBox="[^"]+"', thumb).group(0) == re.search(r'viewBox="[^"]+"', normal).group(0)


def test_thumbnail_overbars_keep_constant_width() -> None:
    from partforge.symbols import ic_symbol, render_thumbnail

    spec = ic_symbol("RST_TEST", [IcPin(designator="1", name="R\\E\\S\\E\\T\\", electrical="input"),
                                  IcPin(designator="2", name="GND", electrical="power")])
    thumb = render_thumbnail(spec)
    assert 'class="overbar"' in thumb
    bar = re.search(r'<line class="overbar"[^>]*/>', thumb).group(0)
    assert 'vector-effect="non-scaling-stroke"' in bar
