"""IC box-symbol generator: side assignment, grouping, ordering, body size, multi-part, splitting."""

from __future__ import annotations

from collections import Counter
from itertools import pairwise

import pytest

from partforge.geometry.model import SymbolSpec, SymPin, SymRect
from partforge.symbols import (
    SymbolError,
    SymbolRequest,
    auto_assign_sides,
    check_spec,
    example_request,
    generate,
    ic_symbol,
    is_regulator,
)
from partforge.symbols.ic import classify_pin
from partforge.symbols.models import IcPin
from partforge.symbols.style import StyleKit
from partforge.workspace import SymbolStyle

STYLE = SymbolStyle()
KIT = StyleKit.from_style(STYLE)
NAME_MARGIN = 50


def ip(designator: str, name: str = "", electrical: str = "passive", **kw: object) -> IcPin:
    return IcPin(designator=designator, name=name, electrical=electrical, **kw)  # type: ignore[arg-type]


def side_of(pins: list[IcPin], name: str) -> str | None:
    return next(p.side for p in pins if p.name == name)


def body(spec: SymbolSpec, part: int = 1) -> SymRect:
    return next(g for g in spec.graphics if isinstance(g, SymRect) and g.part == part)


def by_des(spec: SymbolSpec) -> dict[str, SymPin]:
    return {p.designator: p for p in spec.pins}


def name_boxes(spec: SymbolSpec, part: int = 1) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Approximate boxes (x1, y1, x2, y2) of the pin names inside the body."""
    cap = KIT.cap_height
    out = []
    for p in spec.pins:
        if p.hidden or p.part not in (0, part) or not p.name:
            continue
        w = KIT.text_width(p.name)
        if p.orientation == "left":
            box = (p.x + NAME_MARGIN, p.y - cap / 2, p.x + NAME_MARGIN + w, p.y + cap / 2)
        elif p.orientation == "right":
            box = (p.x - NAME_MARGIN - w, p.y - cap / 2, p.x - NAME_MARGIN, p.y + cap / 2)
        elif p.orientation == "up":
            box = (p.x - cap / 2, p.y - NAME_MARGIN - w, p.x + cap / 2, p.y - NAME_MARGIN)
        else:
            box = (p.x - cap / 2, p.y + NAME_MARGIN, p.x + cap / 2, p.y + NAME_MARGIN + w)
        out.append((p.designator, box))
    return out


def assert_no_name_overlap(spec: SymbolSpec, part: int = 1) -> None:
    boxes = name_boxes(spec, part)
    rect = body(spec, part)
    for i, (d1, a) in enumerate(boxes):
        assert rect.x1 <= a[0] and a[2] <= rect.x2 and rect.y1 <= a[1] and a[3] <= rect.y2, f"name {d1} outside body"
        for d2, b in boxes[i + 1 :]:
            overlap = a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
            assert not overlap, f"pin names {d1} and {d2} overlap"


def assert_ic_layout(spec: SymbolSpec) -> None:
    assert check_spec(spec) == []
    positions = (spec.generator or {})["text_positions"]
    assert spec.designator_pos is not None and spec.designator_pos.model_dump() == positions["designator"]
    assert spec.comment_pos is not None and spec.comment_pos.model_dump() == positions["comment"]
    assert spec.designator_pos.y > 0 > spec.comment_pos.y  # above / below the body
    for part in range(1, spec.part_count + 1):
        rect = body(spec, part)
        assert (rect.x1, rect.y2) == (0, 0), "top-left body corner at the origin"
        assert rect.filled and rect.color == "#800000" and rect.fill_color == "#FFFFB0"
        assert rect.line_width == "smallest"
        assert rect.x2 % 100 == 0 and rect.y1 % 100 == 0
        for p in spec.pins:
            if p.hidden or p.part not in (0, part):
                continue
            assert p.length == 200
            assert p.show_name and p.show_designator
            if p.orientation == "left":
                assert p.x == 0 and rect.y1 < p.y < 0
            elif p.orientation == "right":
                assert p.x == rect.x2 and rect.y1 < p.y < 0
            elif p.orientation == "up":
                assert p.y == 0 and 0 < p.x < rect.x2
            else:
                assert p.y == rect.y1 and 0 < p.x < rect.x2
        assert_no_name_overlap(spec, part)


# ---------------------------------------------------------------------------------- roles
@pytest.mark.parametrize(
    ("name", "electrical", "role"),
    [
        ("VDD", "power", "supply"),
        ("AVDD", "passive", "supply"),
        ("VIN", "power", "supply"),
        ("VCCIO", "power", "supply"),
        ("V+", "power", "supply"),
        ("VBAT", "passive", "supply"),
        ("+5V", "power", "supply"),
        ("GND", "power", "ground"),
        ("AGND", "passive", "ground"),
        ("PGND2", "power", "ground"),
        ("VSS", "power", "ground"),
        ("VSSA", "power", "ground"),
        ("V-", "power", "ground"),
        ("VEE", "power", "ground"),
        ("NC", "passive", "nc"),
        ("N/C", "passive", "nc"),
        ("DNC", "passive", "nc"),
        ("NC3", "passive", "nc"),
        ("EP", "passive", "ep"),
        ("PAD", "passive", "ep"),
        ("Heat Sink", "passive", "ep"),
        ("SW", "power", "switch"),
        ("LX", "passive", "switch"),
        ("BST", "passive", "switch"),
        ("SW2", "output", "switch"),
        ("VOUT", "power", "output"),
        ("OUT", "passive", "output"),
        ("FB", "passive", "output"),
        ("MISO", "io", "output"),
        ("INT", "io", "output"),
        ("P\\G\\", "passive", "output"),
        ("TXD", "io", "output"),
        ("EN", "passive", "input"),
        ("C\\S\\", "io", "input"),
        ("SDA", "io", "input"),
        ("SCL", "io", "input"),
        ("R\\E\\S\\E\\T\\", "passive", "input"),
        ("BOOT0", "input", "input"),
        ("A0", "io", "input"),
        ("PA0", "io", "free"),
        ("GPIO5", "io", "free"),
        ("X", "passive", "free"),
        ("DIS", "open_collector", "output"),
        ("TRIG", "input", "input"),
    ],
)
def test_classify_pin(name: str, electrical: str, role: str) -> None:
    assert classify_pin(ip("1", name, electrical)) == role


@pytest.mark.parametrize(
    ("name", "role"),
    [
        ("FB", "output"),
        ("VFB", "output"),
        ("FB2", "output"),
        ("COMP", "output"),
        ("BST", "switch"),
        ("BST1", "switch"),
        ("SW", "switch"),
        ("SW2", "switch"),
        ("LX", "switch"),
        ("CBOOT", "switch"),
    ],
)
def test_regulator_names_win_over_input_type(name: str, role: str) -> None:
    """Review finding: FB/BST/SW typed 'input' (datasheet import) landed on the left side."""
    assert classify_pin(ip("1", name, "input")) == role
    assert classify_pin(ip("1", name, "input"), regulator=True) == role


@pytest.mark.parametrize(
    ("name", "regulator_role"),
    [
        ("SS", "output"),
        ("SS/TRK", "output"),
        ("RT", "output"),
        ("PG", "output"),
        ("ILIM", "output"),
        ("VOS", "output"),
        ("BOOT", "switch"),
        ("CB", "switch"),
        ("BOOT1", "switch"),
    ],
)
def test_ambiguous_regulator_names_need_context(name: str, regulator_role: str) -> None:
    # SS = SPI slave select, BOOT = MCU boot pin ... outside a regulator they stay inputs
    assert classify_pin(ip("1", name, "input")) == "input"
    assert classify_pin(ip("1", name, "input"), regulator=True) == regulator_role


def test_mcu_boot_pins_are_not_switch_nodes() -> None:
    assert classify_pin(ip("1", "BOOT0", "input")) == "input"
    assert classify_pin(ip("1", "BOOT0", "io")) == "free"  # was "switch" (top edge) before
    assert classify_pin(ip("1", "BOOT0", "io"), regulator=True) == "switch"


def test_is_regulator() -> None:
    assert is_regulator([ip("1", "VIN", "power"), ip("2", "SW", "power")])
    assert is_regulator([ip("1", "FB", "input")])
    assert not is_regulator([ip("1", "SS", "input"), ip("2", "SCK", "input"), ip("3", "MISO", "output")])
    assert not is_regulator([])


def test_buck_regulator_with_input_typed_control_pins() -> None:
    """Review repro r02: house style puts FB/SS/PG right, SW/BST on top, VIN/EN left."""
    pins = [
        ip("1", "VIN", "power"),
        ip("2", "EN", "input"),
        ip("3", "FB", "input"),
        ip("4", "SW", "power"),
        ip("5", "BST", "input"),
        ip("6", "PG", "open_collector"),
        ip("7", "GND", "power"),
        ip("8", "SS", "input"),
    ]
    sides = {p.name: p.side for p in auto_assign_sides(pins)}
    assert sides == {
        "VIN": "left",
        "EN": "left",
        "FB": "right",
        "SW": "top",
        "BST": "top",
        "PG": "right",
        "GND": "bottom",
        "SS": "right",
    }
    spec = ic_symbol("BUCK", pins, style=STYLE)
    assert_ic_layout(spec)
    orient = {p.name: p.orientation for p in spec.pins}
    assert orient["FB"] == "right" and orient["SS"] == "right" and orient["BST"] == "up"


def test_spi_slave_select_stays_left() -> None:
    pins = [ip("1", "VDD", "power"), ip("2", "SS", "input"), ip("3", "SCK", "input"), ip("4", "MISO", "output")]
    sides = {p.name: p.side for p in auto_assign_sides(pins)}
    assert sides["SS"] == "left" and sides["MISO"] == "right"
    assert auto_assign_sides(pins, regulator=True)[1].side == "right"  # explicit context wins


def test_example_ic_has_feedback_on_the_right() -> None:
    spec = generate(example_request("ic"), STYLE)
    orient = {p.name: p.orientation for p in spec.pins}
    assert orient == {"VIN": "left", "EN": "left", "FB": "right", "PG": "right", "SW": "up", "GND": "down"}


def test_auto_assign_sides_house_conventions() -> None:
    pins = [
        ip("1", "VIN", "power"),
        ip("2", "GND", "power"),
        ip("3", "EN", "input"),
        ip("4", "FB"),
        ip("5", "SW", "output"),
        ip("6", "BST"),
        ip("7", "PG", "open_collector"),
        ip("8", "NC"),
        ip("9", "EP"),
        ip("10", "SDA", "io"),
        ip("11", "MISO", "io"),
        ip("12", "X", "passive", side="top"),
    ]
    out = auto_assign_sides(pins)
    assert [p.designator for p in out] == [p.designator for p in pins]  # order kept
    sides = {p.name: p.side for p in out}
    assert sides == {
        "VIN": "left",
        "GND": "bottom",
        "EN": "left",
        "FB": "right",
        "SW": "top",
        "BST": "top",
        "PG": "right",
        "NC": "bottom",
        "EP": "bottom",
        "SDA": "left",
        "MISO": "right",
        "X": "top",
    }
    assert all(p.side is None for p in pins if p.name != "X")  # inputs not mutated


def test_auto_assign_balances_free_pins_and_keeps_buses() -> None:
    pins = [ip(str(i + 1), f"PA{i}", "io") for i in range(8)] + [ip(str(i + 9), f"PB{i}", "io") for i in range(8)]
    out = auto_assign_sides(pins)
    pa = {p.side for p in out if p.name.startswith("PA")}
    pb = {p.side for p in out if p.name.startswith("PB")}
    assert len(pa) == 1 and len(pb) == 1 and pa != pb  # each bus on one side, balanced
    counts = Counter(p.side for p in out)
    assert counts["left"] == counts["right"] == 8


def test_auto_assign_groups_stay_together() -> None:
    pins = [
        ip("1", "SCLK", "input", group="SPI"),
        ip("2", "MOSI", "input", group="SPI"),
        ip("3", "MISO", "output", group="SPI"),
        ip("4", "CS", "input", group="SPI"),
        ip("5", "VDD", "power", group="Power"),
        ip("6", "GND", "power", group="Power", side="right"),
    ]
    out = auto_assign_sides(pins)
    assert {p.side for p in out if p.group == "SPI"} == {"left"}  # majority input -> left
    assert {p.side for p in out if p.group == "Power"} == {"right"}  # explicit side of a member wins


# ---------------------------------------------------------------------------------- layout
def ne555() -> list[IcPin]:
    return [
        ip("1", "GND", "power"),
        ip("2", "TRIG", "input"),
        ip("3", "OUT", "output"),
        ip("4", "R\\E\\S\\E\\T\\", "input"),
        ip("5", "CV", "input"),
        ip("6", "THR", "input"),
        ip("7", "DIS", "open_collector"),
        ip("8", "VCC", "power"),
    ]


def test_ne555_layout_house_style() -> None:
    spec = ic_symbol("NE555DR", ne555(), style=STYLE)
    assert_ic_layout(spec)
    pins = by_des(spec)
    assert pins["4"].name == "R\\E\\S\\E\\T\\"  # overbar syntax kept verbatim
    assert pins["8"].orientation == "left" and pins["8"].y == -100  # supply first, one grid below the top
    assert pins["1"].orientation == "down"
    left = sorted((p for p in spec.pins if p.orientation == "left"), key=lambda p: -p.y)
    assert [p.name for p in left] == ["VCC", "CV", "R\\E\\S\\E\\T\\", "THR", "TRIG"]
    assert left[1].y == left[0].y - 200  # one empty grid row between supply and input groups
    rect = body(spec)
    assert min(p.y for p in spec.pins if p.orientation in ("left", "right")) == rect.y1 + 100  # 100 above bottom
    assert spec.designator_prefix == "U" and spec.part_count == 1


@pytest.mark.parametrize("count", [8, 16, 48, 100])
def test_generic_ics_of_various_sizes(count: int) -> None:
    pins = [ip("1", "VDD", "power"), ip("2", "GND", "power")]
    pins += [ip(str(i), f"IO{i - 2}", "io") for i in range(3, count + 1)]
    spec = ic_symbol(f"IC{count}", pins, style=STYLE)
    assert_ic_layout(spec)
    assert len(spec.pins) == count
    assert len({p.designator for p in spec.pins}) == count
    sides = Counter(p.orientation for p in spec.pins)
    assert abs(sides["left"] - 1 - sides["right"]) <= 2  # IO bus balanced (VDD extra on the left)


def test_body_width_follows_names_and_grid() -> None:
    short = ic_symbol("S", [ip("1", "A", "input"), ip("2", "Y", "output")], style=STYLE)
    long = ic_symbol(
        "L", [ip("1", "VERY_LONG_INPUT_NAME", "input"), ip("2", "ANOTHER_LONG_OUTPUT", "output")], style=STYLE
    )
    w_short, w_long = body(short).x2, body(long).x2
    assert w_short == 400  # minimum body width
    need = 2 * NAME_MARGIN + KIT.text_width("VERY_LONG_INPUT_NAME") + KIT.text_width("ANOTHER_LONG_OUTPUT") + 100
    assert w_long >= need and w_long - need < 100 and w_long % 100 == 0


def test_grouping_gaps_and_natural_order() -> None:
    pins = [ip(str(i + 1), f"D{n}", "io", group="Daten") for i, n in enumerate([10, 2, 0, 1, 11, 3])]
    pins += [ip("20", "AD1", "input", group="Adresse"), ip("21", "AD0", "input", group="Adresse")]
    spec = ic_symbol("BUS", pins, style=STYLE)
    assert_ic_layout(spec)
    sides = {p.side for p in auto_assign_sides(pins) if p.group == "Daten"}
    assert len(sides) == 1
    data = sorted((p for p in spec.pins if p.name.startswith("D")), key=lambda p: -p.y)
    assert [p.name for p in data] == ["D0", "D1", "D2", "D3", "D10", "D11"]
    assert all(a.y - b.y == 100 for a, b in pairwise(data))
    addr = sorted((p for p in spec.pins if p.name.startswith("AD")), key=lambda p: -p.y)
    assert [p.name for p in addr] == ["AD0", "AD1"]
    if addr[0].orientation == data[0].orientation:  # same side: one empty row between the groups
        ys = sorted({p.y for p in spec.pins if p.orientation == data[0].orientation}, reverse=True)
        gaps = [a - b for a, b in pairwise(ys)]
        assert gaps.count(200) == 1 and set(gaps) <= {100, 200}
    for p in spec.pins:
        assert p.group in ("Daten", "Adresse")


def test_order_modes() -> None:
    pins = [ip("3", "B", "input"), ip("1", "C", "input"), ip("2", "A", "input")]
    by_name = ic_symbol("X", pins, style=STYLE)
    by_designator = ic_symbol("X", pins, style=STYLE, order="designator")
    as_given = ic_symbol("X", pins, style=STYLE, order="input")

    def seq(spec: SymbolSpec) -> list[str]:
        return [p.name for p in sorted(spec.pins, key=lambda p: -p.y)]

    assert seq(by_name) == ["A", "B", "C"]
    assert seq(by_designator) == ["C", "A", "B"]
    assert seq(as_given) == ["B", "C", "A"]
    with pytest.raises(SymbolError, match="Sortierung"):
        ic_symbol("X", pins, style=STYLE, order="random")  # type: ignore[arg-type]


def test_top_and_bottom_pins_do_not_collide_with_side_names() -> None:
    pins = [
        ip("1", "PVIN", "power"),
        ip("2", "AVIN", "power"),
        ip("3", "ENABLE_LONG_NAME", "input"),
        ip("4", "SW1", "power"),
        ip("5", "SW2", "power"),
        ip("6", "BST1"),
        ip("7", "BST2"),
        ip("8", "VOUT_SENSE_LONG", "output"),
        ip("9", "FB"),
        ip("10", "PGND"),
        ip("11", "AGND"),
        ip("12", "SGND"),
        ip("13", "NC"),
        ip("14", "EP"),
    ]
    spec = ic_symbol("BUCK", pins, style=STYLE)
    assert_ic_layout(spec)
    tops = [p for p in spec.pins if p.orientation == "up"]
    assert {p.name for p in tops} == {"SW1", "SW2", "BST1", "BST2"}
    assert len({p.x for p in tops}) == 4 and all(p.x % 100 == 0 for p in tops)


def test_hidden_pins() -> None:
    pins = [*ne555(), ip("9", "VCC2", "power", hidden=True)]
    spec = ic_symbol("HID", pins, style=STYLE)
    assert check_spec(spec) == []
    hidden = by_des(spec)["9"]
    assert hidden.hidden and hidden.x % 10 == 0 and hidden.tip()[0] % 100 == 0
    visible_rows = {p.y for p in spec.pins if not p.hidden and p.orientation == "left"}
    reference = ic_symbol("REF", ne555(), style=STYLE)
    assert body(spec).y1 == body(reference).y1  # hidden pins take no space
    assert visible_rows == {p.y for p in reference.pins if p.orientation == "left"}


def test_multi_part_with_shared_power_pins() -> None:
    pins = [ip("14", "VCC", "power", part=0), ip("7", "GND", "power", part=0)]
    for g, (a, b, y) in enumerate([(1, 2, 3), (4, 5, 6), (9, 10, 8), (12, 13, 11)], start=1):
        pins += [
            ip(str(a), f"{g}A", "input", part=g),
            ip(str(b), f"{g}B", "input", part=g),
            ip(str(y), f"{g}Y", "output", part=g),
        ]
    spec = ic_symbol("74HC00", pins, style=STYLE)
    assert spec.part_count == 4
    assert_ic_layout(spec)
    shared = [p for p in spec.pins if p.part == 0]
    assert {p.designator for p in shared} == {"14", "7"}
    for part in range(2, 5):  # same body size for every part
        assert body(spec, part).model_dump(exclude={"part"}) == body(spec, 1).model_dump(exclude={"part"})
    a = sorted((p.name[1:], p.x, p.y) for p in spec.pins if p.part == 1)
    for part in range(2, 5):
        assert sorted((p.name[1:], p.x, p.y) for p in spec.pins if p.part == part) == a


def test_multi_part_errors() -> None:
    with pytest.raises(SymbolError, match="Teil 2 hat keine Pins"):
        ic_symbol("GAP", [ip("1", "A", "input", part=1), ip("2", "B", "input", part=3)], style=STYLE)
    with pytest.raises(SymbolError, match="bereits Teilen"):
        ic_symbol("X", [ip("1", "A", part=2), ip("2", "B", part=1)], parts=2, style=STYLE)


def mcu(count: int) -> list[IcPin]:
    pins: list[IcPin] = []
    d = 1
    for _ in range(6):
        pins += [ip(str(d), "VDD", "power"), ip(str(d + 1), "VSS", "power")]
        d += 2
    pins += [ip(str(d), "NRST", "input"), ip(str(d + 1), "BOOT0", "input")]
    d += 2
    port = 0
    while d <= count:
        pins.append(ip(str(d), f"P{'ABCDEFGHIJ'[port // 16]}{port % 16}", "io"))
        d += 1
        port += 1
    return pins


def test_auto_split_large_ic() -> None:
    pins = mcu(144)
    single = ic_symbol("MCU", pins, style=STYLE)
    assert single.part_count == 1
    spec = ic_symbol("MCU", pins, parts="auto", style=STYLE)
    assert spec.part_count >= 3
    assert_ic_layout(spec)
    for part in range(1, spec.part_count + 1):
        sides = Counter(p.orientation for p in spec.pins if p.part == part)
        assert max(sides.values()) <= 40
    last = spec.part_count
    power = {p.name for p in spec.pins if p.part == last}
    assert power == {"VDD", "VSS"}
    assert sorted(p.designator for p in spec.pins) == sorted(p.designator for p in pins)
    small = ic_symbol("SMALL", ne555(), parts="auto", style=STYLE)
    assert small.part_count == 1  # nothing to split


@pytest.mark.parametrize("target", [2, 3, 5])
def test_split_into_requested_parts(target: int) -> None:
    spec = ic_symbol("MCU", mcu(100), parts=target, style=STYLE)
    assert 2 <= spec.part_count <= target
    assert_ic_layout(spec)


def fpga() -> list[IcPin]:
    """Review repro r05: 120 GND, 60 VCCIO (4 banks) and 300 IO pins."""
    pins = [ip(f"G{i}", "GND", "power") for i in range(120)]
    pins += [ip(f"V{i}", f"VCCIO{i % 4}", "power") for i in range(60)]
    pins += [ip(f"IO{i}", f"IO_L{i}", "io") for i in range(300)]
    return pins


def sides_per_part(spec: SymbolSpec) -> dict[int, Counter[str]]:
    return {
        part: Counter(p.orientation for p in spec.pins if p.part in (0, part) and not p.hidden)
        for part in range(1, spec.part_count + 1)
    }


@pytest.mark.parametrize("capacity", [10, 40])
def test_auto_split_respects_capacity_for_power_pins(capacity: int) -> None:
    """Review finding: all supplies/grounds went into one unlimited power part (120 bottom pins)."""
    pins = fpga()
    spec = ic_symbol("FPGA", pins, parts="auto", max_pins_per_side=capacity, style=STYLE)
    assert check_spec(spec) == []
    assert sorted(p.designator for p in spec.pins) == sorted(p.designator for p in pins)
    per_part = sides_per_part(spec)
    for part, counts in per_part.items():
        assert max(counts.values()) <= capacity, (part, dict(counts))
    power_parts = [part for part in per_part if {p.name for p in spec.pins if p.part == part} <= {
        "GND", "VCCIO0", "VCCIO1", "VCCIO2", "VCCIO3"}]
    assert len(power_parts) >= 2 and power_parts == list(range(power_parts[0], spec.part_count + 1))
    for part in power_parts:  # supplies left, grounds on the bottom edge first
        supplies = [p for p in spec.pins if p.part == part and p.name.startswith("VCC")]
        grounds = [p for p in spec.pins if p.part == part and p.name == "GND"]
        assert all(p.orientation == "left" for p in supplies)
        assert grounds and {p.orientation for p in grounds} <= {"down", "right"}
        assert any(p.orientation == "down" for p in grounds)


def test_auto_split_rebalances_signal_pins_and_sizes_parts_individually() -> None:
    """Review finding: parts 4/5 had pins on one side only and every part used the widest body."""
    spec = ic_symbol("FPGA", fpga(), parts="auto", style=STYLE)
    assert_ic_layout(spec)
    per_part = sides_per_part(spec)
    signal_parts = [part for part in per_part if any(p.name.startswith("IO_") for p in spec.pins if p.part == part)]
    for part in signal_parts:
        counts = per_part[part]
        assert counts["left"] and counts["right"], (part, dict(counts))
        assert abs(counts["left"] - counts["right"]) <= 1
    sizes = spec.generator["layout"]["sizes"]
    assert len(sizes) == spec.part_count
    for part, (width, height) in enumerate(sizes, start=1):
        rect = body(spec, part)
        assert (rect.x2, -rect.y1) == (width, height)
    assert len({tuple(size) for size in sizes}) > 1  # power parts differ from signal parts
    assert spec.generator["layout"]["width"] == max(w for w, _ in sizes)
    assert spec.generator["layout"]["height"] == max(h for _, h in sizes)
    comment_y = spec.generator["text_positions"]["comment"]["y"]
    assert comment_y < -max(h for _, h in sizes)  # Comment below the tallest part


def test_auto_split_with_many_grounds_on_a_small_ic() -> None:
    pins = [ip(str(i), "GND", "power") for i in range(1, 101)]
    pins += [ip("101", "VDD", "power"), ip("102", "A", "input"), ip("103", "Y", "output")]
    spec = ic_symbol("GNDS", pins, parts="auto", max_pins_per_side=20, style=STYLE)
    assert check_spec(spec) == []
    for counts in sides_per_part(spec).values():
        assert max(counts.values()) <= 20
    assert {p.name for p in spec.pins if p.part == 1} == {"A", "Y"}  # signal part first


def test_requested_part_count_includes_power_parts() -> None:
    spec = ic_symbol("FPGA", fpga(), parts=4, style=STYLE)
    assert spec.part_count == 4
    assert check_spec(spec) == []
    names_last = {p.name for p in spec.pins if p.part == 4}
    assert names_last <= {"GND", "VCCIO0", "VCCIO1", "VCCIO2", "VCCIO3"}


def test_generate_ic_request() -> None:
    req = SymbolRequest(kind="ic", name="NE555DR", description="Timer", pins=ne555(), params={"order": "designator"})
    spec = generate(req, STYLE)
    assert spec.name == "NE555DR" and spec.description == "Timer"
    assert spec.generator["kind"] == "ic" and spec.generator["request"]["name"] == "NE555DR"
    assert "text_positions" in spec.generator and spec.generator["layout"]["parts"] == 1
    auto = generate(SymbolRequest(kind="ic", pins=mcu(144), params={"parts": "auto"}), STYLE)
    assert auto.part_count > 1 and auto.name == "IC 144-Pin"
    assert generate(SymbolRequest(kind="ic", pins=mcu(100), params={"parts": "3"}), STYLE).part_count <= 3
    with pytest.raises(SymbolError, match="Pinliste ist leer"):
        generate(SymbolRequest(kind="ic", name="X"), STYLE)
    with pytest.raises(SymbolError, match="unbekannte Parameter"):
        generate(SymbolRequest(kind="ic", name="X", pins=ne555(), params={"foo": 1}), STYLE)
    with pytest.raises(SymbolError, match="Teileangabe"):
        generate(SymbolRequest(kind="ic", name="X", pins=ne555(), params={"parts": "viele"}), STYLE)


def test_ic_validation_errors() -> None:
    with pytest.raises(SymbolError, match="Pins benötigt"):
        ic_symbol("X", [], style=STYLE)
    with pytest.raises(SymbolError, match="doppelt"):
        ic_symbol("X", [ip("1", "A"), ip("1", "B")], style=STYLE)
    with pytest.raises(SymbolError, match="keine Pin-Nummer"):
        ic_symbol("X", [ip("", "A")], style=STYLE)
    with pytest.raises(SymbolError, match="Leerzeichen"):
        ic_symbol("X", [ip(" 1", "A")], style=STYLE)
    with pytest.raises(SymbolError, match="unzulässige Zeichen"):
        ic_symbol("LM358/NOPB", ne555(), style=STYLE)
    with pytest.raises(SymbolError, match="Teileanzahl"):
        ic_symbol("X", ne555(), parts=0, style=STYLE)
    with pytest.raises(SymbolError, match="Präfix"):
        ic_symbol("X", ne555(), designator_prefix="", style=STYLE)


def test_ic_respects_grid_and_pin_length_style() -> None:
    style = SymbolStyle(grid=50, ic_pin_length=250)
    spec = ic_symbol("NE555", ne555(), style=style)
    assert check_spec(spec, grid=50) == []
    assert {p.length for p in spec.pins} == {250}  # tips on the 50 mil snap grid
    left = sorted((p.y for p in spec.pins if p.orientation == "left"), reverse=True)
    assert left[0] == -100  # the pin pitch stays 100 mil (house), the grid only snaps the tips


@pytest.mark.parametrize("grid", [10, 20, 50, 100])
def test_pin_pitch_is_100_mil_for_every_grid(grid: int) -> None:
    """Review finding: IC rows were 20/50 mil apart with grid 20/50 (names overlapped)."""
    pins = [ip(str(i + 1), f"IN{i}", "input") for i in range(4)] + [ip("9", "SW", "power"), ip("10", "BST")]
    pins += [ip("11", "OUT", "output"), ip("12", "GND", "power"), ip("13", "AGND", "power")]
    spec = ic_symbol("X", pins, style=SymbolStyle(grid=grid))
    assert check_spec(spec, grid=grid) == []
    rows = sorted({p.y for p in spec.pins if p.orientation == "left"}, reverse=True)
    assert rows == [-100, -200, -300, -400]
    for edge in ("up", "down"):
        cols = [p.x for p in spec.pins if p.orientation == edge]
        assert cols and all(x % 100 == 0 for x in cols) and len(set(cols)) == len(cols)
    rect = body(spec)
    assert rect.x2 % 100 == 0 and rect.y1 % 100 == 0
    assert_no_name_overlap(spec)


def test_ic_style_none_uses_defaults() -> None:
    spec = ic_symbol("NE555", ne555())
    assert {p.length for p in spec.pins} == {200}
