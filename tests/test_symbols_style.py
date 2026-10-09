"""Style kit, text metrics, pin-map resolution and the spec validator."""

from __future__ import annotations

import pytest

from partforge.geometry.model import SymbolSpec, SymLine, SymPin, SymRect
from partforge.symbols import SymbolError, check_spec, spec_warnings
from partforge.symbols import text as txt
from partforge.symbols.pinmap import PinFunction, PinMapSpec, resolve_pinmap
from partforge.symbols.style import StyleKit
from partforge.symbols.util import check_name, check_prefix, natural_key
from partforge.workspace import SymbolStyle

# ---------------------------------------------------------------------------------- style


def test_style_kit_defaults_match_house_style() -> None:
    kit = StyleKit.from_style(SymbolStyle())
    assert (kit.grid, kit.ic_pin_length, kit.discrete_pin_length) == (100, 200, 100)
    assert kit.discrete.color == kit.discrete.fill == "#0000FF"
    assert (kit.ic_body.color, kit.ic_body.fill, kit.ic_body.width) == ("#800000", "#FFFFB0", "smallest")
    assert kit.as_dict()["resistor_style"] == "iec"


@pytest.mark.parametrize(
    ("grid", "expected"), [(100, 100), (50, 50), (20, 20), (10, 10), (30, 100), (200, 100), (0, 100)]
)
def test_grid_sanitised(grid: int, expected: int) -> None:
    assert StyleKit.from_style(SymbolStyle(grid=grid)).grid == expected


def test_pin_lengths_sanitised() -> None:
    kit = StyleKit.from_style(SymbolStyle(ic_pin_length=250, discrete_pin_length=55))
    assert kit.ic_pin_length == 200 or kit.ic_pin_length == 300  # multiple of the grid
    assert kit.ic_pin_length % kit.grid == 0
    assert kit.discrete_pin_length == 60
    tiny = StyleKit.from_style(SymbolStyle(ic_pin_length=0, discrete_pin_length=0))
    assert tiny.ic_pin_length == 100 and tiny.discrete_pin_length == 10
    huge = StyleKit.from_style(SymbolStyle(ic_pin_length=99999, discrete_pin_length=99999, font_size=500))
    assert huge.ic_pin_length == 1000 and huge.discrete_pin_length == 1000 and huge.font_size == 10


def test_invalid_colours_fall_back() -> None:
    kit = StyleKit.from_style(SymbolStyle(discrete_line_color="blau", ic_fill_color="ffffb0", pin_color="#12"))
    assert kit.discrete_line_color == "#0000FF"
    assert kit.ic_fill_color == "#FFFFB0"  # missing '#' accepted, upper-cased
    assert kit.pin_color == "#000000"


@pytest.mark.parametrize(
    ("x", "y", "orientation", "desired", "length"),
    [
        (-100, 0, "left", 100, 100),
        (-50, 0, "left", 100, 50),  # tie 50/150 -> shorter
        (-20, 0, "left", 100, 80),
        (20, 0, "right", 100, 80),
        (100, 140, "up", 100, 60),
        (100, -140, "down", 100, 60),
        (0, -40, "down", 100, 60),
        (-120, 0, "left", 100, 80),
        (-100, 0, "left", 250, 200),  # tie 200/300 -> shorter
        (0, 0, "left", 10, 100),  # at least one grid step when the attach point is on the grid
    ],
)
def test_fit_pin_length(x: int, y: int, orientation: str, desired: int, length: int) -> None:
    kit = StyleKit.from_style(SymbolStyle())
    got = kit.fit_pin_length(x, y, orientation, desired)  # type: ignore[arg-type]
    assert got == length
    tip = {"left": (x - got, y), "right": (x + got, y), "up": (x, y + got), "down": (x, y - got)}[orientation]
    assert tip[0] % 100 == 0 and tip[1] % 100 == 0


def test_fit_pin_length_rejects_off_raster() -> None:
    with pytest.raises(ValueError):
        StyleKit.from_style(SymbolStyle()).fit_pin_length(15, 0, "left")


def test_grid_helpers() -> None:
    kit = StyleKit.from_style(SymbolStyle())
    assert kit.ceil_grid(101) == 200 and kit.ceil_grid(100) == 100 and kit.floor_grid(199) == 100
    assert kit.on_grid(300) and not kit.on_grid(250)


# ---------------------------------------------------------------------------------- text
def test_metric_tables_complete() -> None:
    assert len(txt._TIMES_ASCII) == 95 and len(txt._HELVETICA_ASCII) == 95


def test_overbar_parsing() -> None:
    assert txt.parse_overbar("R\\E\\S\\E\\T\\") == [(c, True) for c in "RESET"]
    assert txt.display_text("C\\S\\/A") == "CS/A"
    assert txt.parse_overbar("C\\S\\/A")[2:] == [("/", False), ("A", False)]
    assert txt.display_text("\\X") == "X"
    assert txt.has_overbar("W\\R\\") and not txt.has_overbar("WR")
    assert txt.display_text("") == ""


def test_text_width_estimates() -> None:
    w_times = txt.text_width("VDD", font="Times New Roman", size=10)
    assert w_times == pytest.approx((722 * 3) / 1000 * 100)
    assert txt.text_width("R\\E\\S\\E\\T\\") == txt.text_width("RESET")
    assert txt.text_width("MMMM") > txt.text_width("iiii")
    assert txt.text_width("VDD", font="Arial") == pytest.approx((667 + 722 + 722) / 1000 * 100)
    assert txt.text_width("VDD", size=20) == pytest.approx(2 * w_times)
    assert txt.text_width("µΩ") > 0 and txt.text_width("€") == pytest.approx(50)
    assert txt.font_family("Segoe UI") == "helvetica" and txt.font_family("Times New Roman") == "times"
    assert txt.cap_height(size=10) == pytest.approx(66.2)


# ---------------------------------------------------------------------------------- pin maps
SPEC = PinMapSpec(
    functions=(PinFunction("G", "G", "G"), PinFunction("D", "D", "D"), PinFunction("S", "S", "S")),
    presets={"GSD": {"G": ("1",), "S": ("2",), "D": ("3",)}, "GDS": {"G": ("1",), "D": ("2",), "S": ("3",)}},
    default="GSD",
)


@pytest.mark.parametrize(
    ("value", "key", "default"),
    [
        (None, "GSD", True),
        ("", "GSD", True),
        ("auto", "GSD", True),
        ("gsd", "GSD", True),
        ("GDS", "GDS", False),
        ("SSSGDDDD", "SSSGDDDD", False),
        ({"G": "1", "S": 2, "D": "3"}, "GSD", True),
        ({"g": "4", "d": "5,6,7,8", "s": ["1", "2", "3"]}, "SSSGDDDD", False),
        ("GxDS", "GxDS", False),
        ({"G": "A1", "D": "B2", "S": "C3"}, None, False),
    ],
)
def test_resolve_pinmap(value: object, key: str | None, default: bool) -> None:
    pm = resolve_pinmap(SPEC, value, what="FET")
    assert pm.is_default is default
    if key is None:
        assert pm.key.startswith("M") and len(pm.key) == 7  # hashed custom map
    else:
        assert pm.key == key
    assert set(pm.pins) == {"G", "D", "S"}


def test_resolve_pinmap_label_and_default_override() -> None:
    pm = resolve_pinmap(SPEC, None, what="FET", default="GDS")
    assert pm.key == "GDS" and pm.is_default and pm.label == "1=G, 2=D, 3=S"
    assert not pm.is_canonical  # a style-dependent default is not the canonical map


def test_resolve_pinmap_canonical_flag() -> None:
    assert resolve_pinmap(SPEC, None, what="FET").is_canonical
    assert resolve_pinmap(SPEC, "GSD", what="FET", default="GDS").is_canonical
    assert resolve_pinmap(SPEC, {"G": "1", "S": "2", "D": "3"}, what="FET", default="GDS").is_canonical
    assert not resolve_pinmap(SPEC, "GDS", what="FET").is_canonical


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("GQS", "unbekanntes Zeichen"),
        ("GD", "unvollständig"),
        ({"G": "1", "D": "1", "S": "2"}, "doppelt"),
        ({"G": "1", "D": "2", "S": "3", "B": "4"}, "unbekannte Pinfunktion"),
        ({"G": "", "D": "2", "S": "3"}, "keine Pin-Nummer"),
        ({"G": "1 1", "D": "2", "S": "3"}, "doppelt"),
        ({"G": "x/y", "D": "2", "S": "3"}, "ungültige Pin-Nummer"),
        (42, "Text oder Objekt"),
    ],
)
def test_resolve_pinmap_errors(value: object, message: str) -> None:
    with pytest.raises(SymbolError, match=message):
        resolve_pinmap(SPEC, value, what="FET")


def test_shared_codes_assigned_in_order() -> None:
    spec = PinMapSpec(
        functions=(
            PinFunction("+", "+", "+"),
            PinFunction("AC1", "~", "A"),
            PinFunction("AC2", "~", "A"),
            PinFunction("-", "-", "-"),
        ),
        presets={"+AA-": {"+": ("1",), "AC1": ("2",), "AC2": ("3",), "-": ("4",)}},
        default="+AA-",
    )
    pm = resolve_pinmap(spec, "A+-A", what="Brücke")
    assert pm.pins["AC1"] == ("1",) and pm.pins["AC2"] == ("4",)
    with pytest.raises(SymbolError, match="zu oft"):
        resolve_pinmap(spec, "AAA+-", what="Brücke")


def test_non_code_pinmap_requires_preset_or_object() -> None:
    spec = PinMapSpec(
        functions=(PinFunction("IN", "IN"), PinFunction("OUT", "OUT")),
        presets={"STD": {"IN": ("1",), "OUT": ("2",)}},
        default="STD",
    )
    with pytest.raises(SymbolError, match="unbekannte Pinbelegung"):
        resolve_pinmap(spec, "IO", what="X")
    assert resolve_pinmap(spec, {"IN": "2", "OUT": "1"}, what="X").key.startswith("M")


# ---------------------------------------------------------------------------------- util / validate
def test_natural_key_and_name_checks() -> None:
    assert sorted(["PA10", "PA2", "PA1", "PB0"], key=natural_key) == ["PA1", "PA2", "PA10", "PB0"]
    assert sorted(["10", "9", "A1", "1"], key=natural_key) == ["1", "9", "10", "A1"]
    assert check_name("Op-Amp (SOIC8)") == "Op-Amp (SOIC8)"
    for bad in ("", " R", "R ", "R/1", "Ω", "__PFSTEP_X", "R" * 65):
        with pytest.raises(SymbolError):
            check_name(bad)
    assert check_prefix("FB") == "FB"
    for bad in ("", "1R", "R-1", "ABCDEFGHIJK"):
        with pytest.raises(SymbolError):
            check_prefix(bad)


def _spec(**kw: object) -> SymbolSpec:
    base = {
        "name": "T",
        "pins": [
            SymPin(designator="1", x=-100, y=0, orientation="left", length=100),
            SymPin(designator="2", x=100, y=0, orientation="right", length=100),
        ],
        "graphics": [SymRect(x1=-100, y1=-40, x2=100, y2=40, color="#0000FF")],
    }
    base.update(kw)
    return SymbolSpec(**base)  # type: ignore[arg-type]


def test_check_spec_accepts_valid_and_reports_problems() -> None:
    assert check_spec(_spec()) == []
    problems = check_spec(
        _spec(
            name="bad/name",
            designator_prefix="9",
            part_count=2,
            pins=[
                SymPin(designator="1", x=-105, y=0, orientation="left", length=100),
                SymPin(designator="1", x=100, y=0, orientation="right", length=100),
                SymPin(designator="", x=0, y=50, orientation="up", length=50, part=3),
            ],
            graphics=[SymLine(points=[{"x": 0, "y": 0}, {"x": 1, "y": 1}], color="blue", part=5)],
        )
    )
    text = "\n".join(problems)
    for fragment in (
        "Symbolname",
        "Präfix",
        "10-mil-Raster",
        "doppelt",
        "Teil 3 existiert nicht",
        "Pin-Nummer fehlt",
        "kein #RRGGBB",
        "Grafik 1 (line): Teil 5",
        "100-mil-Raster",
    ):
        assert fragment in text, fragment


def test_check_spec_part_rules() -> None:
    shared = _spec(
        part_count=2,
        pins=[
            SymPin(designator="1", x=-100, y=0, orientation="left", length=100, part=0),
            SymPin(designator="2", x=100, y=0, orientation="right", length=100, part=1),
        ],
    )
    assert check_spec(shared) == []
    empty_part = _spec(
        part_count=3,
        pins=[SymPin(designator="1", x=-100, y=0, orientation="left", length=100, part=1)],
        graphics=[SymRect(x1=-100, y1=-40, x2=100, y2=40, part=1)],
    )
    assert any("leer" in p for p in check_spec(empty_part))
    dup_shared = _spec(
        part_count=2,
        pins=[
            SymPin(designator="1", x=-100, y=0, orientation="left", length=100, part=0),
            SymPin(designator="1", x=100, y=0, orientation="right", length=100, part=2),
        ],
    )
    assert any("Teil 2: Pin-Nummern doppelt" in p for p in check_spec(dup_shared))
    far = _spec(pins=[SymPin(designator="1", x=-60000, y=0, orientation="left", length=100)])
    assert any("±50000" in p for p in check_spec(far))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1e9])
def test_check_spec_reports_broken_graphic_coordinates(value: float) -> None:
    line = SymLine(points=[{"x": 0, "y": value}, {"x": 1, "y": 1}])
    spec = _spec(graphics=[SymRect(x1=value, y1=-40, x2=100, y2=40), line])
    problems = check_spec(spec)
    assert any("Grafik 1 (rect): Koordinaten ungültig" in p for p in problems)
    assert any("Grafik 2 (line): Koordinaten ungültig" in p for p in problems)


def test_spec_warnings_soft_hints() -> None:
    spec = _spec(
        description="Shunt 10 mΩ",  # Ω is outside Latin-1 (µ, ä … are not: Altium reads them intact, review F7)
        pins=[
            SymPin(designator="1", name="IN µ", x=-100, y=0, orientation="left", length=100),
            SymPin(designator="2", name="VCC", x=100, y=0, orientation="right", length=100, hidden=True),
        ],
    )
    warnings = spec_warnings(spec)
    assert any("Sonderzeichen (IN µ)" in w for w in warnings)
    assert any("Beschreibung" in w and "Ω" in w for w in warnings)
    assert any("Verborgene Pins (2)" in w for w in warnings)
    assert spec_warnings(_spec()) == []
    assert not [w for w in spec_warnings(_spec(description="Widerstand µ, 2 Kanäle")) if "Beschreibung" in w]
