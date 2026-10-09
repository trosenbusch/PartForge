"""Standard symbols: every kind x parameter variant yields a writer-valid, house-style spec."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterator

import pytest

from partforge.geometry.model import SymArc, SymbolSpec, SymEllipse, SymLine, SymPin, SymPolygon, SymRect, SymText
from partforge.symbols import SymbolError, SymbolRequest, check_spec, generate, kinds
from partforge.symbols.models import IcPin
from partforge.symbols.standard import kind_defs
from partforge.workspace import SymbolStyle

GRID = 100
STANDARD = [d.key for d in kind_defs()]
DISCRETE_HIDDEN = {
    "resistor",
    "potentiometer",
    "trimmer",
    "capacitor",
    "capacitor_polarized",
    "inductor",
    "ferrite_bead",
    "crystal_2",
    "crystal_4",
    "fuse",
    "ptc",
    "varistor",
    "diode",
    "zener",
    "schottky",
    "tvs_uni",
    "tvs_bi",
    "led",
    "photodiode",
    "bridge_rectifier",
    "npn",
    "pnp",
    "nmos",
    "pmos",
    "test_point",
    "mounting_hole",
    "switch_2",
    "buzzer",
    "battery",
}


def _variants() -> Iterator[SymbolRequest]:
    for kd in kind_defs():
        yield SymbolRequest(kind=kd.key)
        for p in kd.params:
            if p.kind == "enum":
                for option in p.options:
                    yield SymbolRequest(kind=kd.key, params={p.name: option})
            elif p.kind == "bool":
                yield SymbolRequest(kind=kd.key, params={p.name: not p.default})
            elif p.kind == "int":
                for value in sorted({p.minimum, p.default, p.maximum} - {None}):
                    params: dict[str, object] = {p.name: value}
                    if kd.key == "connector" and value > 100:
                        params["rows"] = "2"  # at most 100 pins per row
                    yield SymbolRequest(kind=kd.key, params=params)


VARIANTS = list(_variants())


def pins_by_designator(spec: SymbolSpec) -> dict[str, SymPin]:
    return {p.designator: p for p in spec.pins}


def assert_house_valid(spec: SymbolSpec, grid: int = GRID) -> None:
    assert check_spec(spec, grid=grid) == []
    for p in spec.pins:
        tx, ty = p.tip()
        assert isinstance(p.x, int) and isinstance(p.y, int) and isinstance(p.length, int)
        assert p.x % 10 == 0 and p.y % 10 == 0 and p.length % 10 == 0, p
        assert p.length > 0
        assert tx % grid == 0 and ty % grid == 0, f"tip of pin {p.designator} off grid: {(tx, ty)}"
        # the pin row (perpendicular coordinate) lies on the grid
        row = p.y if p.orientation in ("left", "right") else p.x
        assert row % grid == 0
    for g in spec.graphics:
        assert g.color and g.color.startswith("#"), g
        coords: list[float] = []
        if isinstance(g, SymRect):
            coords = [g.x1, g.y1, g.x2, g.y2]
            if g.filled:
                assert g.fill_color
        elif isinstance(g, (SymLine, SymPolygon)):
            coords = [c for pt in g.points for c in (pt.x, pt.y)]
            if isinstance(g, SymPolygon) and g.filled:
                assert g.fill_color
        elif isinstance(g, SymArc):
            coords = [g.cx, g.cy, g.r]
            assert g.r > 0
        elif isinstance(g, SymEllipse):
            coords = [g.cx, g.cy, g.rx, g.ry]
        elif isinstance(g, SymText):
            coords = [g.x, g.y]
            assert g.text and g.text.isascii()
        for c in coords:
            assert abs(c * 2 - round(c * 2)) < 1e-6 and round(c * 2) % 10 == 0, f"{g.kind} not on 5 mil raster: {c}"
    x1, y1, x2, y2 = spec.bbox()
    assert x2 > x1 and y2 > y1
    assert max(abs(x1), abs(y1), abs(x2), abs(y2)) < 20_000
    # designators unique per part (part 0 pins count in every part)
    for part in range(1, spec.part_count + 1):
        des = [p.designator for p in spec.pins if p.part in (0, part)]
        assert len(des) == len(set(des)), f"duplicate designators in part {part}: {des}"
        assert any(g.part in (0, part) for g in spec.graphics) or any(p.part in (0, part) for p in spec.pins)
    assert spec.name.isascii() and len(spec.name) <= 64
    assert spec.description.isascii()
    gen = spec.generator or {}
    assert gen.get("kind") and gen.get("version") == 1
    assert "text_positions" in gen
    json.dumps(gen)  # serialisable
    # contract fields for the writers carry the same house-style positions
    positions = gen["text_positions"]
    assert spec.designator_pos is not None and spec.designator_pos.model_dump() == positions["designator"]
    assert spec.comment_pos is not None and spec.comment_pos.model_dump() == positions["comment"]


@pytest.mark.parametrize("req", VARIANTS, ids=lambda r: f"{r.kind}-{json.dumps(r.params, sort_keys=True)}")
def test_every_variant_is_valid(req: SymbolRequest) -> None:
    spec = generate(req, SymbolStyle())
    assert_house_valid(spec)
    again = generate(req, SymbolStyle())
    assert again.model_dump() == spec.model_dump()  # deterministic


@pytest.mark.parametrize("kind", STANDARD)
@pytest.mark.parametrize(
    "style",
    [
        SymbolStyle(resistor_style="ansi"),
        SymbolStyle(diode_pin1="anode"),
        SymbolStyle(grid=50, discrete_pin_length=50),
        SymbolStyle(discrete_pin_length=200, ic_pin_length=300),
        SymbolStyle(grid=20),
    ],
    ids=["ansi", "anode", "grid50", "long", "grid20"],
)
def test_kinds_valid_for_house_style_variants(kind: str, style: SymbolStyle) -> None:
    spec = generate(SymbolRequest(kind=kind), style)
    assert_house_valid(spec, grid=style.grid)


def test_default_names_unique_and_fixed() -> None:
    names: dict[str, list[str]] = defaultdict(list)
    for info in kinds():
        if info.key == "ic":
            continue
        spec = generate(SymbolRequest(kind=info.key), SymbolStyle())
        assert spec.name == info.default_name
        names[spec.name].append(info.key)
    assert all(len(v) == 1 for v in names.values()), names


def test_variant_names_are_distinct_per_geometry() -> None:
    seen: dict[str, str] = {}
    for req in VARIANTS:
        spec = generate(req, SymbolStyle())
        key = json.dumps(
            {"pins": [p.model_dump() for p in spec.pins], "g": [g.model_dump() for g in spec.graphics]}, sort_keys=True
        )
        if spec.name in seen:
            assert seen[spec.name] == key, f"name {spec.name} used for different geometries"
        seen[spec.name] = key


def test_category_default_symbols_exist() -> None:
    """``CategoryDef.default_symbol`` of every built-in category is a symbol *kind key* of
    :func:`partforge.symbols.kinds` (``resistor``), never a symbol name (``Resistor``)."""
    from partforge.db.templates import CATEGORIES

    keys = {info.key for info in kinds()}
    defaults = {cat.table: cat.default_symbol for cat in CATEGORIES if cat.default_symbol}
    assert defaults, "keine Kategorie mit Standardsymbol"
    unknown = {table: kind for table, kind in defaults.items() if kind not in keys}
    assert not unknown, unknown


@pytest.mark.parametrize("kind", sorted(DISCRETE_HIDDEN))
def test_discretes_hide_pin_names_and_numbers(kind: str) -> None:
    spec = generate(SymbolRequest(kind=kind), SymbolStyle())
    assert spec.pins or kind == "fiducial"
    for p in spec.pins:
        assert not p.show_name and not p.show_designator
    style = SymbolStyle()
    line_colors = {g.color for g in spec.graphics}
    assert line_colors <= {style.discrete_line_color}


@pytest.mark.parametrize(
    "kind",
    [
        "resistor",
        "capacitor",
        "inductor",
        "ferrite_bead",
        "fuse",
        "ptc",
        "varistor",
        "crystal_2",
        "switch_2",
        "battery",
        "tvs_bi",
    ],
)
def test_two_terminal_pin1_left(kind: str) -> None:
    spec = generate(SymbolRequest(kind=kind), SymbolStyle())
    pins = pins_by_designator(spec)
    assert set(pins) == {"1", "2"}
    assert pins["1"].orientation == "left" and pins["2"].orientation == "right"
    assert pins["1"].tip()[0] == -pins["2"].tip()[0]  # symmetric about the origin
    assert pins["1"].tip()[1] == 0


def test_resistor_house_geometry_iec_and_ansi() -> None:
    iec = generate(SymbolRequest(kind="resistor"), SymbolStyle())
    rect = next(g for g in iec.graphics if isinstance(g, SymRect))
    assert (rect.x1, rect.y1, rect.x2, rect.y2) == (-100, -40, 100, 40)  # house: 20 x 8 units
    assert not rect.filled
    pins = pins_by_designator(iec)
    assert (pins["1"].x, pins["1"].length, pins["1"].tip()) == (-100, 100, (-200, 0))
    ansi = generate(SymbolRequest(kind="resistor"), SymbolStyle(resistor_style="ansi"))
    assert not any(isinstance(g, SymRect) for g in ansi.graphics)
    zigzag = next(g for g in ansi.graphics if isinstance(g, SymLine))
    assert len(zigzag.points) == 7
    assert ansi.name == "Resistor"
    assert ansi.generator["text_positions"]["designator"] == {"x": -50, "y": 50, "justify": "bottom_left"}


def test_house_text_positions_for_small_passives() -> None:
    spec = generate(SymbolRequest(kind="resistor"), SymbolStyle())
    pos = spec.generator["text_positions"]
    assert (pos["designator"]["x"], pos["designator"]["y"]) == (-50, 50)
    assert (pos["comment"]["x"], pos["comment"]["y"]) == (-50, -150)


@pytest.mark.parametrize("kind", ["diode", "zener", "schottky", "tvs_uni", "led", "photodiode"])
def test_diode_pin1_follows_style(kind: str) -> None:
    cathode_spec = generate(SymbolRequest(kind=kind), SymbolStyle(diode_pin1="cathode"))
    cathode = pins_by_designator(cathode_spec)
    assert cathode["1"].name == "K" and cathode["2"].name == "A"
    assert "(" not in cathode_spec.name  # canonical IPC map -> plain name
    anode = generate(SymbolRequest(kind=kind), SymbolStyle(diode_pin1="anode"))
    assert pins_by_designator(anode)["1"].name == "A"
    # the anode-first default is a different pinout, so it must have a different name
    assert anode.name == f"{cathode_spec.name} (AK)"
    explicit = generate(SymbolRequest(kind=kind, params={"pinmap": "AK"}), SymbolStyle(diode_pin1="cathode"))
    assert explicit.name == anode.name
    assert [p.model_dump() for p in explicit.pins] == [p.model_dump() for p in anode.pins]
    canonical = generate(SymbolRequest(kind=kind, params={"pinmap": "KA"}), SymbolStyle(diode_pin1="anode"))
    assert canonical.name == cathode_spec.name  # explicit KA in an anode-first workspace keeps the plain name
    # anode always left, cathode always right (graphic orientation independent of numbering)
    for spec in (cathode, pins_by_designator(anode)):
        a = next(p for p in spec.values() if p.name == "A")
        k = next(p for p in spec.values() if p.name == "K")
        assert a.orientation == "left" and k.orientation == "right"


_STYLE_VARIANTS = [
    SymbolStyle(),
    SymbolStyle(diode_pin1="anode"),
    SymbolStyle(resistor_style="ansi"),
    SymbolStyle(grid=50, discrete_pin_length=50),
    SymbolStyle(grid=20),
    SymbolStyle(discrete_pin_length=200, ic_pin_length=300),
]


def test_same_name_means_same_pinout_across_styles() -> None:
    """A symbol name must never stand for two pin-to-function maps (sync updates symbols by name)."""
    seen: dict[str, tuple[frozenset[tuple[str, str, int]], str]] = {}
    for style in _STYLE_VARIANTS:
        for req in VARIANTS:
            spec = generate(req, style)
            pinout = frozenset((p.designator, p.name, p.part) for p in spec.pins)
            where = f"{req.kind} {req.params} {style.model_dump(exclude_defaults=True)}"
            if spec.name in seen:
                assert seen[spec.name][0] == pinout, f"{spec.name!r}: {where} vs {seen[spec.name][1]}"
            else:
                seen[spec.name] = (pinout, where)


def test_diode_names_with_style_change_regression() -> None:
    """Review finding: 'Diode' was 1=K,2=A in one workspace and 1=A,2=K in another."""
    for kind, base in (("diode", "Diode"), ("led", "LED"), ("zener", "Zener Diode")):
        specs = {
            style.diode_pin1: generate(SymbolRequest(kind=kind), style)
            for style in (SymbolStyle(diode_pin1="cathode"), SymbolStyle(diode_pin1="anode"))
        }
        assert specs["cathode"].name == base
        assert specs["anode"].name == f"{base} (AK)"
        assert {p.designator: p.name for p in specs["cathode"].pins} == {"1": "K", "2": "A"}
        assert {p.designator: p.name for p in specs["anode"].pins} == {"1": "A", "2": "K"}


def test_diode_sot23_pinmap() -> None:
    spec = generate(SymbolRequest(kind="zener", params={"pinmap": "AxK"}), SymbolStyle())
    pins = pins_by_designator(spec)
    assert set(pins) == {"1", "3"} and pins["1"].name == "A" and pins["3"].name == "K"
    assert spec.name == "Zener Diode (AxK)"


def test_polarized_capacitor_pin1_plus() -> None:
    spec = generate(SymbolRequest(kind="capacitor_polarized"), SymbolStyle())
    pins = pins_by_designator(spec)
    assert pins["1"].name == "+" and pins["1"].orientation == "left"
    flipped = generate(SymbolRequest(kind="capacitor_polarized", params={"pinmap": "-+"}), SymbolStyle())
    fp = pins_by_designator(flipped)
    assert fp["1"].name == "-" and fp["1"].orientation == "left"
    assert flipped.name == "Capacitor Polarized (-+)"
    ansi = generate(SymbolRequest(kind="capacitor_polarized"), SymbolStyle(resistor_style="ansi"))
    assert any(isinstance(g, SymArc) for g in ansi.graphics)


@pytest.mark.parametrize(
    ("pinmap", "expected"),
    [
        ("BEC", {"1": "B", "2": "E", "3": "C"}),
        ("EBC", {"1": "E", "2": "B", "3": "C"}),
        ("CBE", {"1": "C", "2": "B", "3": "E"}),
        ("BCEC", {"1": "B", "2": "C", "3": "E", "4": "C"}),
        ("bce", {"1": "B", "2": "C", "3": "E"}),
        ({"B": "2", "C": ["1", "4"], "E": "3"}, {"1": "C", "2": "B", "3": "E", "4": "C"}),
    ],
)
@pytest.mark.parametrize("kind", ["npn", "pnp"])
def test_bjt_pin_maps(kind: str, pinmap: object, expected: dict[str, str]) -> None:
    spec = generate(SymbolRequest(kind=kind, params={"pinmap": pinmap}), SymbolStyle())
    pins = pins_by_designator(spec)
    assert {d: p.name for d, p in pins.items()} == expected
    # stacked pins of one function share the location
    by_name: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for p in spec.pins:
        by_name[p.name].add((p.x, p.y))
    assert all(len(v) == 1 for v in by_name.values())
    if pinmap in ("BEC",):
        assert spec.name == kind.upper()
    else:
        assert spec.name.startswith(kind.upper() + " (")


def test_bjt_default_is_sot23() -> None:
    pins = pins_by_designator(generate(SymbolRequest(kind="npn"), SymbolStyle()))
    assert (pins["1"].name, pins["2"].name, pins["3"].name) == ("B", "E", "C")
    assert pins["1"].orientation == "left" and pins["3"].orientation == "up" and pins["2"].orientation == "down"


@pytest.mark.parametrize("kind", ["nmos", "pmos"])
def test_mosfet_pin_maps_and_body_diode(kind: str) -> None:
    default = generate(SymbolRequest(kind=kind), SymbolStyle())
    pins = pins_by_designator(default)
    assert (pins["1"].name, pins["2"].name, pins["3"].name) == ("G", "S", "D")
    so8 = generate(SymbolRequest(kind=kind, params={"pinmap": "SSSGDDDD"}), SymbolStyle())
    p8 = pins_by_designator(so8)
    assert sorted(p8, key=int) == [str(i) for i in range(1, 9)]
    assert {(p8[d].x, p8[d].y) for d in ("1", "2", "3")} == {(p8["1"].x, p8["1"].y)}
    assert {(p8[d].x, p8[d].y) for d in ("5", "6", "7", "8")} == {(p8["5"].x, p8["5"].y)}
    assert so8.name == f"{kind.upper()} (SSSGDDDD)"
    no_diode = generate(SymbolRequest(kind=kind, params={"body_diode": False}), SymbolStyle())
    assert len(no_diode.graphics) < len(default.graphics)
    assert no_diode.name == f"{kind.upper()} No-Diode"
    dpak = pins_by_designator(generate(SymbolRequest(kind=kind, params={"pinmap": "GDSD"}), SymbolStyle()))
    assert dpak["2"].name == dpak["4"].name == "D"


@pytest.mark.parametrize(
    ("pinmap", "drain", "name"),
    [
        ("SSSGDDDDD", {"5", "6", "7", "8", "9"}, "NMOS (SSSGDDDDD)"),
        ("SSSGDDDD+EP", {"5", "6", "7", "8", "EP"}, "NMOS (SSSGDDDD+EP)"),
        ({"S": "1,2,3", "G": "4", "D": ["5", "6", "7", "8", "9"]}, {"5", "6", "7", "8", "9"}, "NMOS (SSSGDDDDD)"),
        ("DDGSDD", {"1", "2", "5", "6"}, "NMOS (DDGSDD)"),
    ],
)
def test_mosfet_exposed_pad_and_six_pin_presets(pinmap: object, drain: set[str], name: str) -> None:
    spec = generate(SymbolRequest(kind="nmos", params={"pinmap": pinmap}), SymbolStyle())
    assert_house_valid(spec)
    assert {p.designator for p in spec.pins if p.name == "D"} == drain
    assert len({(p.x, p.y) for p in spec.pins if p.name == "D"}) == 1  # stacked drain pins
    assert spec.name == name


def test_mosfet_to92_presets() -> None:
    sgd = pins_by_designator(generate(SymbolRequest(kind="nmos", params={"pinmap": "SGD"}), SymbolStyle()))
    dgs = pins_by_designator(generate(SymbolRequest(kind="nmos", params={"pinmap": "DGS"}), SymbolStyle()))
    assert (sgd["1"].name, sgd["2"].name, sgd["3"].name) == ("S", "G", "D")  # 2N7000
    assert (dgs["1"].name, dgs["2"].name, dgs["3"].name) == ("D", "G", "S")  # BS170


def test_kind_pinmap_and_tab_function_helpers() -> None:
    from partforge.symbols.standard import is_diode_kind, kind_pinmap, tab_function

    nmos = kind_pinmap("nmos")
    assert nmos is not None and nmos.default == "GSD"
    assert kind_pinmap("resistor") is None
    assert kind_pinmap("comparator", {"channels": "1"}) is not None
    assert kind_pinmap("comparator", {"channels": "2"}) is None
    no_base = kind_pinmap("optocoupler_6", {"base": False})
    with_base = kind_pinmap("optocoupler_6", {"base": "ja"})
    assert no_base is not None and no_base.default == "AKxECx"
    assert with_base is not None and with_base.default == "AKxECB"
    assert (tab_function("nmos"), tab_function("pnp"), tab_function("diode")) == ("D", "C", None)
    assert is_diode_kind("led") and not is_diode_kind("tvs_bi")


def test_pinmap_errors() -> None:
    with pytest.raises(SymbolError, match="unbekanntes Zeichen"):
        generate(SymbolRequest(kind="npn", params={"pinmap": "BQC"}), SymbolStyle())
    with pytest.raises(SymbolError, match="unvollständig"):
        generate(SymbolRequest(kind="npn", params={"pinmap": "BxC"}), SymbolStyle())
    with pytest.raises(SymbolError, match="doppelt"):
        generate(SymbolRequest(kind="npn", params={"pinmap": {"B": "1", "C": "1", "E": "2"}}), SymbolStyle())
    with pytest.raises(SymbolError, match="unbekannte Pinfunktion"):
        generate(SymbolRequest(kind="nmos", params={"pinmap": {"X": "1"}}), SymbolStyle())
    with pytest.raises(SymbolError, match="Pinbelegung"):
        generate(SymbolRequest(kind="relay_spdt", params={"pinmap": "ABC"}), SymbolStyle())


def test_crystal_and_oscillator_pins() -> None:
    xtal = pins_by_designator(generate(SymbolRequest(kind="crystal_4"), SymbolStyle()))
    assert xtal["1"].name == "XTAL1" and xtal["3"].name == "XTAL2"
    assert xtal["2"].name == xtal["4"].name == "GND"
    assert xtal["2"].orientation == xtal["4"].orientation == "down"
    osc = generate(SymbolRequest(kind="oscillator"), SymbolStyle())
    pins = pins_by_designator(osc)
    assert [pins[d].name for d in "1234"] == ["OE", "GND", "OUT", "VDD"]
    assert osc.designator_prefix == "Y" and osc.name == "Oscillator"
    assert all(p.show_name and p.show_designator for p in osc.pins)
    st = generate(SymbolRequest(kind="oscillator", params={"pin1": "ST"}), SymbolStyle())
    assert pins_by_designator(st)["1"].name == "S\\T\\"
    assert st.name == "Oscillator ST"
    rect = next(g for g in osc.graphics if isinstance(g, SymRect))
    assert rect.filled and rect.color == "#800000" and rect.fill_color == "#FFFFB0"


def test_opamp_single_pinouts() -> None:
    sot = pins_by_designator(generate(SymbolRequest(kind="opamp"), SymbolStyle()))
    assert {d: p.name for d, p in sot.items()} == {"1": "OUT", "2": "V-", "3": "+IN", "4": "-IN", "5": "V+"}
    assert sot["4"].y == 100 and sot["3"].y == -100  # inverting input on top (house)
    assert sot["1"].electrical == "output" and sot["5"].electrical == "power" and sot["3"].electrical == "input"
    assert all(p.show_designator and not p.show_name for p in sot.values())
    soic = pins_by_designator(generate(SymbolRequest(kind="opamp", params={"pinmap": "SOIC8"}), SymbolStyle()))
    assert set(soic) == {"2", "3", "4", "6", "7"}
    assert soic["6"].name == "OUT" and soic["7"].name == "V+"


def _parts(spec: SymbolSpec) -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = defaultdict(dict)
    for p in spec.pins:
        out[p.part][p.designator] = p.name
    return dict(out)


def test_opamp_dual_multi_part_like_lm358() -> None:
    spec = generate(SymbolRequest(kind="opamp_dual"), SymbolStyle())
    assert spec.part_count == 3
    parts = _parts(spec)
    assert parts[1] == {"1": "OUT", "2": "-IN", "3": "+IN"}
    assert parts[2] == {"7": "OUT", "6": "-IN", "5": "+IN"}
    assert parts[3] == {"8": "V+", "4": "V-"}
    a = {p.name: (p.x, p.y) for p in spec.pins if p.part == 1}
    b = {p.name: (p.x, p.y) for p in spec.pins if p.part == 2}
    assert a == b  # identical amplifier geometry per part
    for part in (1, 2, 3):
        assert any(g.part == part for g in spec.graphics)


def test_opamp_quad_and_comparator_variants() -> None:
    quad = generate(SymbolRequest(kind="opamp_quad"), SymbolStyle())
    assert quad.part_count == 5 and _parts(quad)[5] == {"4": "V+", "11": "V-"}
    assert _parts(quad)[4] == {"14": "OUT", "13": "-IN", "12": "+IN"}
    comp = generate(SymbolRequest(kind="comparator", params={"channels": 4, "output": "open_drain"}), SymbolStyle())
    assert comp.name == "Comparator Quad OD" and comp.part_count == 5
    parts = _parts(comp)
    assert parts[1] == {"2": "OUT", "4": "-IN", "5": "+IN"}  # LM339
    assert parts[5] == {"3": "V+", "12": "V-"}
    assert all(p.electrical == "open_collector" for p in comp.pins if p.name == "OUT")
    dual = generate(SymbolRequest(kind="comparator", params={"channels": "2"}), SymbolStyle())
    assert dual.name == "Comparator Dual" and dual.part_count == 3
    single = generate(
        SymbolRequest(kind="comparator", params={"output": "open_drain", "pinmap": "SOIC8"}), SymbolStyle()
    )
    assert single.name == "Comparator OD (SOIC8)" and single.part_count == 1
    with pytest.raises(SymbolError, match="einkanalig"):
        generate(SymbolRequest(kind="comparator", params={"channels": "2", "pinmap": "SOIC8"}), SymbolStyle())


def test_optocouplers() -> None:
    four = pins_by_designator(generate(SymbolRequest(kind="optocoupler_4"), SymbolStyle()))
    assert {d: p.name for d, p in four.items()} == {"1": "A", "2": "K", "3": "E", "4": "C"}
    six = pins_by_designator(generate(SymbolRequest(kind="optocoupler_6"), SymbolStyle()))
    assert {d: p.name for d, p in six.items()} == {"1": "A", "2": "K", "4": "E", "5": "C", "6": "B"}
    nobase = generate(SymbolRequest(kind="optocoupler_6", params={"base": False}), SymbolStyle())
    assert set(pins_by_designator(nobase)) == {"1", "2", "4", "5"}
    assert nobase.name == "Optocoupler 6-Pin No-Base"


def test_bridge_rectifier_codes() -> None:
    spec = generate(SymbolRequest(kind="bridge_rectifier"), SymbolStyle())
    pins = pins_by_designator(spec)
    assert {d: p.name for d, p in pins.items()} == {"1": "+", "2": "~", "3": "~", "4": "-"}
    assert pins["1"].orientation == "up" and pins["4"].orientation == "down"
    alt = generate(SymbolRequest(kind="bridge_rectifier", params={"pinmap": "~~+-"}), SymbolStyle())
    assert alt.name == "Bridge Rectifier (AA+-)"
    assert pins_by_designator(alt)["3"].name == "+"


@pytest.mark.parametrize(
    ("pins", "rows", "numbering", "left", "right"),
    [
        (5, "1", "odd_even", ["1", "2", "3", "4", "5"], []),
        (10, "2", "odd_even", ["1", "3", "5", "7", "9"], ["2", "4", "6", "8", "10"]),
        (10, "2", "row", ["1", "2", "3", "4", "5"], ["6", "7", "8", "9", "10"]),
        (10, "2", "dip", ["1", "2", "3", "4", "5"], ["10", "9", "8", "7", "6"]),
    ],
)
def test_connector_numbering(pins: int, rows: str, numbering: str, left: list[str], right: list[str]) -> None:
    spec = generate(
        SymbolRequest(kind="connector", params={"pins": pins, "rows": rows, "numbering": numbering}), SymbolStyle()
    )
    lefts = [p.designator for p in sorted((p for p in spec.pins if p.orientation == "left"), key=lambda p: -p.y)]
    rights = [p.designator for p in sorted((p for p in spec.pins if p.orientation == "right"), key=lambda p: -p.y)]
    assert lefts == left and rights == right
    if right:  # rows aligned
        assert sorted(p.y for p in spec.pins if p.orientation == "left") == sorted(
            p.y for p in spec.pins if p.orientation == "right"
        )
    assert all(p.show_designator and not p.show_name for p in spec.pins)
    assert all(p.length == 200 for p in spec.pins)
    per_row = pins // int(rows)
    assert spec.name.startswith(f"Connector {rows}x{per_row:02d}")
    rect = next(g for g in spec.graphics if isinstance(g, SymRect))
    assert (rect.x1, rect.y2) == (0, 0)  # top-left corner at the origin


@pytest.mark.parametrize("grid", [10, 20, 50, 100])
def test_connector_pitch_is_100_mil_for_every_grid(grid: int) -> None:
    """Review finding: the connector pitch followed the snap grid (20 mil rows with grid 20)."""
    for params in ({"pins": 4}, {"pins": 10, "rows": "2"}):
        spec = generate(SymbolRequest(kind="connector", params=params), SymbolStyle(grid=grid))
        assert check_spec(spec, grid=grid) == []
        rows = sorted({p.y for p in spec.pins}, reverse=True)
        assert rows[0] == -100 and all(a - b == 100 for a, b in zip(rows, rows[1:], strict=False))
        rect = next(g for g in spec.graphics if isinstance(g, SymRect))
        assert rect.x2 % 100 == 0 and rect.y1 % 100 == 0 and rect.y1 == rows[-1] - 100


def test_connector_custom_names_and_errors() -> None:
    req = SymbolRequest(
        kind="connector",
        params={"pins": 4},
        pins=[IcPin(designator="1", name="VBUS"), IcPin(designator="4", name="GND")],
    )
    spec = generate(req, SymbolStyle())
    pins = pins_by_designator(spec)
    assert pins["1"].name == "VBUS" and pins["2"].name == "2"
    assert all(p.show_name for p in spec.pins)
    assert spec.name.startswith("Connector 1x04 (N")
    named = generate(req.model_copy(update={"name": "USB-A Buchse"}), SymbolStyle())
    assert named.name == "USB-A Buchse"
    with pytest.raises(SymbolError, match="gerade Anzahl"):
        generate(SymbolRequest(kind="connector", params={"pins": 7, "rows": "2"}), SymbolStyle())
    with pytest.raises(SymbolError, match="gibt es"):
        generate(
            SymbolRequest(kind="connector", params={"pins": 2}, pins=[IcPin(designator="9", name="X")]), SymbolStyle()
        )
    with pytest.raises(SymbolError, match="zwischen 1 und 200"):
        generate(SymbolRequest(kind="connector", params={"pins": 0}), SymbolStyle())
    with pytest.raises(SymbolError, match="höchstens 100 Pole je Reihe"):
        generate(SymbolRequest(kind="connector", params={"pins": 101}), SymbolStyle())


def test_relay_pushbutton_and_mechanics() -> None:
    relay = pins_by_designator(generate(SymbolRequest(kind="relay_spdt"), SymbolStyle()))
    assert {d: p.name for d, p in relay.items()} == {"1": "A1", "2": "A2", "3": "COM", "4": "NC", "5": "NO"}
    custom = generate(
        SymbolRequest(
            kind="relay_spdt", params={"pinmap": {"A1": "1", "A2": "16", "COM": "11", "NC": "12", "NO": "14"}}
        ),
        SymbolStyle(),
    )
    assert set(pins_by_designator(custom)) == {"1", "16", "11", "12", "14"}
    assert custom.name.startswith("Relay SPDT (M")
    push = pins_by_designator(generate(SymbolRequest(kind="pushbutton_4", params={"pinmap": "LRLR"}), SymbolStyle()))
    assert push["1"].orientation == push["3"].orientation == "left"
    assert push["2"].orientation == push["4"].orientation == "right"
    hole = generate(SymbolRequest(kind="mounting_hole"), SymbolStyle())
    assert [p.designator for p in hole.pins] == ["1"]
    npth = generate(SymbolRequest(kind="mounting_hole", params={"plated": "nein"}), SymbolStyle())
    assert npth.pins == [] and npth.name == "Mounting Hole NPTH"
    assert generate(SymbolRequest(kind="fiducial"), SymbolStyle()).pins == []
    tp = generate(SymbolRequest(kind="test_point"), SymbolStyle())
    assert tp.designator_prefix == "TP" and len(tp.pins) == 1


@pytest.mark.parametrize("cells", [1, 2, 3, 4])
def test_battery_cells(cells: int) -> None:
    spec = generate(SymbolRequest(kind="battery", params={"cells": cells}), SymbolStyle())
    assert_house_valid(spec)
    pins = pins_by_designator(spec)
    assert pins["1"].name == "+" and pins["1"].orientation == "left"
    assert spec.name == ("Battery" if cells == 1 else f"Battery {cells}-Cell")


def test_inductor_core_names() -> None:
    names = {
        core: generate(SymbolRequest(kind="inductor", params={"core": core}), SymbolStyle()).name
        for core in ("none", "iron", "ferrite")
    }
    assert names == {"none": "Inductor", "iron": "Inductor Iron Core", "ferrite": "Inductor Ferrite Core"}


def test_request_overrides_and_validation() -> None:
    spec = generate(
        SymbolRequest(kind="resistor", name="R_SHUNT", description="Shunt", designator_prefix="RS"), SymbolStyle()
    )
    assert (spec.name, spec.description, spec.designator_prefix) == ("R_SHUNT", "Shunt", "RS")
    with pytest.raises(SymbolError, match="Unbekannter Symboltyp"):
        generate(SymbolRequest(kind="flux_capacitor"), SymbolStyle())
    with pytest.raises(SymbolError, match="unbekannte Parameter"):
        generate(SymbolRequest(kind="resistor", params={"colour": "red"}), SymbolStyle())
    with pytest.raises(SymbolError, match="ungültiger Wert"):
        generate(SymbolRequest(kind="inductor", params={"core": "air"}), SymbolStyle())
    with pytest.raises(SymbolError, match="ganze Zahl"):
        generate(SymbolRequest(kind="battery", params={"cells": "zwei"}), SymbolStyle())
    with pytest.raises(SymbolError, match="Ja/Nein"):
        generate(SymbolRequest(kind="npn", params={"circle": "vielleicht"}), SymbolStyle())
    with pytest.raises(SymbolError, match="unzulässige Zeichen"):
        generate(SymbolRequest(kind="resistor", name="R/1"), SymbolStyle())
    with pytest.raises(SymbolError, match="länger als 64"):
        generate(SymbolRequest(kind="resistor", name="R" * 65), SymbolStyle())
    with pytest.raises(SymbolError, match="Präfix"):
        generate(SymbolRequest(kind="resistor", designator_prefix="1R"), SymbolStyle())
    with pytest.raises(SymbolError, match="Pinliste"):
        generate(SymbolRequest(kind="resistor", pins=[IcPin(designator="1")]), SymbolStyle())
    assert generate(SymbolRequest(kind="npn", params={"circle": "ja"}), SymbolStyle()).name == "NPN Circle"


def test_style_values_are_applied() -> None:
    style = SymbolStyle(discrete_line_color="#123456", ic_line_color="#654321", ic_fill_color="#ABCDEF")
    res = generate(SymbolRequest(kind="resistor"), style)
    assert {g.color for g in res.graphics} == {"#123456"}
    conn = generate(SymbolRequest(kind="connector"), style)
    body = next(g for g in conn.graphics if isinstance(g, SymRect))
    assert (body.color, body.fill_color, body.line_width) == ("#654321", "#ABCDEF", "smallest")
    long = generate(SymbolRequest(kind="resistor"), SymbolStyle(discrete_pin_length=200))
    assert {p.length for p in long.pins} == {200}
    ic_len = generate(SymbolRequest(kind="opamp"), SymbolStyle(ic_pin_length=300))
    assert {p.length for p in ic_len.pins} == {300}
    bad = generate(SymbolRequest(kind="resistor"), SymbolStyle(grid=30, discrete_line_color="blue"))
    assert_house_valid(bad)  # unsupported grid -> 100 mil, invalid colour -> house blue
    assert {g.color for g in bad.graphics} == {"#0000FF"}


def test_style_from_open_workspace(tmp_path) -> None:
    from partforge.workspace import Workspace, WorkspaceSettings, current_or_none, set_current

    previous = current_or_none()
    settings = WorkspaceSettings()
    settings.symbol.resistor_style = "ansi"
    ws = Workspace.create(tmp_path / "Lib", settings=settings)
    set_current(ws)
    try:
        spec = generate(SymbolRequest(kind="resistor"))  # style=None -> workspace style
        assert not any(isinstance(g, SymRect) for g in spec.graphics)
    finally:
        set_current(previous)
    if previous is None:  # no workspace open -> defaults (IEC rectangle)
        spec = generate(SymbolRequest(kind="resistor"))
        assert any(isinstance(g, SymRect) for g in spec.graphics)
