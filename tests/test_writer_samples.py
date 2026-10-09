"""Sample symbols/footprints (house style) shared by the library-writer tests.

Imported by the other ``test_writer_*`` modules; the few tests here only check that the
samples themselves are consistent with the geometry contract.
"""
from __future__ import annotations

from itertools import pairwise
from pathlib import Path

from partforge.geometry.model import (
    Arc,
    Body3D,
    FootprintLink,
    FootprintSpec,
    FpText,
    Pad,
    Point,
    Region,
    StepModel,
    SymArc,
    SymbolSpec,
    SymEllipse,
    SymLine,
    SymPin,
    SymPolygon,
    SymRect,
    SymText,
    Track,
    check_symbol_footprint,
)

STEP_TEXT = (
    "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('PartForge test box'),'2;1');\n"
    "FILE_NAME('box','2026-10-07T00:00:00',(''),(''),'PartForge','','');\n"
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
)


def rect_points(x1: float, y1: float, x2: float, y2: float) -> list[Point]:
    return [Point(x=x1, y=y1), Point(x=x2, y=y1), Point(x=x2, y=y2), Point(x=x1, y=y2)]


def rect_tracks(layer: str, x1: float, y1: float, x2: float, y2: float, width: float) -> list[Track]:
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    return [
        Track(layer=layer, x1=a[0], y1=a[1], x2=b[0], y2=b[1], width=width)  # type: ignore[arg-type]
        for a, b in pairwise(pts)
    ]


# --------------------------------------------------------------------------- symbols


def resistor_symbol(name: str = "PF_RES") -> SymbolSpec:
    return SymbolSpec(
        name=name,
        description="Widerstand, generisch (IEC)",
        designator_prefix="R",
        comment="=Value",
        pins=[
            SymPin(designator="1", name="1", x=-100, y=0, orientation="left", length=100, show_name=False, show_designator=False),
            SymPin(designator="2", name="2", x=100, y=0, orientation="right", length=100, show_name=False, show_designator=False),
        ],
        graphics=[SymRect(x1=-100, y1=-40, x2=100, y2=40, filled=False, line_width="small")],
    )


def ic8_symbol(name: str = "NE555DR") -> SymbolSpec:
    left = [("2", "TRIG", "input"), ("6", "THR", "input"), ("5", "CV", "input"), ("4", "R\\E\\S\\E\\T\\", "input")]
    right = [("8", "VCC", "power"), ("7", "DIS", "open_collector"), ("3", "OUT", "output"), ("1", "GND", "power")]
    pins = [
        SymPin(designator=d, name=n, electrical=e, x=0, y=-100 - 100 * i, orientation="left", length=200)  # type: ignore[arg-type]
        for i, (d, n, e) in enumerate(left)
    ]
    pins += [
        SymPin(designator=d, name=n, electrical=e, x=800, y=-100 - 100 * i, orientation="right", length=200)  # type: ignore[arg-type]
        for i, (d, n, e) in enumerate(right)
    ]
    return SymbolSpec(
        name=name,
        description="Precision timer, SOIC-8",
        designator_prefix="U",
        comment="NE555DR",
        pins=pins,
        graphics=[SymRect(x1=0, y1=0, x2=800, y2=-500, filled=True, line_width="smallest")],
        parameters={"Manufacturer": "Texas Instruments"},
        footprints=[FootprintLink(name="SOIC127P600X175-8N", description="SOIC-8")],
    )


def opamp_symbol(name: str = "LM358_DUAL") -> SymbolSpec:
    pins: list[SymPin] = []
    graphics: list = []
    for part, (inm, inp, out) in ((1, ("2", "3", "1")), (2, ("6", "5", "7"))):
        pins += [
            SymPin(designator=inm, name="-", x=-200, y=100, orientation="left", length=200, electrical="input", part=part),
            SymPin(designator=inp, name="+", x=-200, y=-100, orientation="left", length=200, electrical="input", part=part),
            SymPin(designator=out, name="OUT", x=200, y=0, orientation="right", length=200, electrical="output", part=part, show_name=False),
        ]
        graphics.append(
            SymPolygon(points=[Point(x=-200, y=200), Point(x=-200, y=-200), Point(x=200, y=0)], filled=False, part=part)
        )
        graphics.append(SymText(x=-150, y=150, text="A" if part == 1 else "B", part=part, justify="middle_center"))
    pins += [
        SymPin(designator="8", name="V+", x=0, y=100, orientation="up", length=200, electrical="power", part=3),
        SymPin(designator="4", name="V-", x=0, y=-100, orientation="down", length=200, electrical="power", part=3),
    ]
    graphics += [
        SymRect(x1=-100, y1=-100, x2=100, y2=100, filled=False, part=3),
        SymLine(points=[Point(x=-50, y=0), Point(x=0, y=50), Point(x=50, y=0)], part=3, line_width="medium"),
        SymArc(cx=0, cy=0, r=30, start=0, end=180, part=3),
        SymEllipse(cx=0, cy=-50, rx=20, ry=10, part=3),
    ]
    return SymbolSpec(
        name=name,
        description="Dual op-amp (A, B, power)",
        designator_prefix="U",
        comment="LM358",
        part_count=3,
        pins=pins,
        graphics=graphics,
    )


# --------------------------------------------------------------------------- footprints


def house_texts() -> list[FpText]:
    return [
        FpText(layer="designator", x=0, y=0, text=".Designator", height=1.0, stroke=0.15),
        FpText(layer="comment", x=0, y=0, text=".Comment", height=1.0, stroke=0.15),
    ]


def chip_0603(name: str = "RESC1608X55N") -> FootprintSpec:
    tracks = [
        Track(layer="top_silk", x1=-0.75, y1=0.7, x2=0.75, y2=0.7, width=0.15),
        Track(layer="top_silk", x1=-0.75, y1=-0.7, x2=0.75, y2=-0.7, width=0.15),
        *rect_tracks("courtyard", -1.5, -0.75, 1.5, 0.75, 0.05),
        Track(layer="courtyard", x1=-0.5, y1=0, x2=0.5, y2=0, width=0.1),
        Track(layer="courtyard", x1=0, y1=-0.5, x2=0, y2=0.5, width=0.1),
        *rect_tracks("assembly", -0.8, -0.4, 0.8, 0.4, 0.1),
        Track(layer="component_center", x1=-0.475, y1=0, x2=0.475, y2=0, width=0.1),
        Track(layer="component_center", x1=0, y1=-0.475, x2=0, y2=0.475, width=0.1),
        *rect_tracks("component_outline", -0.8, -0.4, 0.8, 0.4, 0.1),
    ]
    return FootprintSpec(
        name=name,
        description="Chip Resistor, 2-Leads, Body 1.60x0.80mm, IPC Medium Density",
        family="chip",
        height=0.55,
        pads=[
            Pad(designator="1", x=-0.8, y=0, width=0.9, height=0.95, shape="roundrect", corner_radius_pct=50),
            Pad(designator="2", x=0.8, y=0, width=0.9, height=0.95, shape="roundrect", corner_radius_pct=50),
        ],
        tracks=tracks,
        texts=house_texts(),
        bodies=[Body3D(name="Body", outline=rect_points(-0.8, -0.4, 0.8, 0.4), z_top=0.55, color="#808080")],
    )


def soic8(name: str = "SOIC127P600X175-8N") -> FootprintSpec:
    pads = []
    for i in range(4):
        y = 1.905 - 1.27 * i
        pads.append(Pad(designator=str(i + 1), x=-2.475, y=y, width=1.95, height=0.6, shape="rect" if i == 0 else "oval"))
    for i in range(4):
        y = -1.905 + 1.27 * i
        pads.append(Pad(designator=str(i + 5), x=2.475, y=y, width=1.95, height=0.6, shape="oval"))
    return FootprintSpec(
        name=name,
        description="SOIC, 8-Leads, Body 4.90x3.90mm, Pitch 1.27mm, IPC Medium Density",
        family="soic",
        height=1.75,
        pads=pads,
        tracks=[
            Track(layer="top_silk", x1=-1.95, y1=2.55, x2=1.95, y2=2.55, width=0.2),
            Track(layer="top_silk", x1=-1.95, y1=-2.55, x2=1.95, y2=-2.55, width=0.2),
            *rect_tracks("courtyard", -3.7, -2.7, 3.7, 2.7, 0.05),
            *rect_tracks("assembly", -1.95, -2.45, 1.95, 2.45, 0.1),
        ],
        arcs=[
            Arc(layer="top_silk", cx=-3.45, cy=2.55, r=0.125, width=0.25),
            Arc(layer="assembly", cx=-1.45, cy=1.95, r=0.25, start=0, end=360, width=0.1),
        ],
        texts=house_texts(),
        bodies=[Body3D(outline=rect_points(-1.95, -2.45, 1.95, 2.45), z_bottom=0.1, z_top=1.75, color="#2B2B2B")],
    )


def header_tht(name: str = "HDR_1X03_P2.54_SLOT") -> FootprintSpec:
    return FootprintSpec(
        name=name,
        description="Stiftleiste 1x03, 2,54 mm, mit Langloch und Befestigungsbohrung",
        family="pin_header",
        height=8.5,
        pads=[
            Pad(designator="1", x=-2.54, y=0, width=1.7, height=1.7, shape="rect", side="through", hole=1.0),
            Pad(designator="2", x=0, y=0, width=1.7, height=1.7, shape="circle", side="through", hole=1.0),
            Pad(designator="3", x=2.54, y=0, width=1.7, height=3.0, shape="oval", side="through", hole=1.0, hole_length=2.2),
            Pad(designator="MH", x=0, y=4.0, width=3.2, height=3.2, shape="circle", side="through", hole=3.2, plated=False),
        ],
        tracks=[*rect_tracks("top_silk", -3.9, -1.9, 3.9, 1.9, 0.2), *rect_tracks("courtyard", -4.1, -2.1, 4.1, 5.9, 0.05)],
        texts=house_texts(),
        bodies=[Body3D(outline=rect_points(-3.81, -1.27, 3.81, 1.27), z_bottom=0, z_top=8.5, color="#202020")],
    )


def qfn16(name: str = "QFN50P300X300X80-17N") -> FootprintSpec:
    pads: list[Pad] = []
    pitch = 0.5
    for i in range(4):
        pads.append(Pad(designator=str(i + 1), x=-1.45, y=0.75 - i * pitch, width=0.8, height=0.25, corner_radius_pct=25))
        pads.append(Pad(designator=str(i + 5), x=-0.75 + i * pitch, y=-1.45, width=0.8, height=0.25, rotation=90, corner_radius_pct=25))
        pads.append(Pad(designator=str(i + 9), x=1.45, y=-0.75 + i * pitch, width=0.8, height=0.25, corner_radius_pct=25))
        pads.append(Pad(designator=str(i + 13), x=0.75 - i * pitch, y=1.45, width=0.8, height=0.25, rotation=90, corner_radius_pct=25))
    pads.sort(key=lambda p: int(p.designator))
    pads.append(
        Pad(designator="17", x=0, y=0, width=1.7, height=1.7, shape="rect", paste=False, mask_expansion=0.05, thermal=True)
    )
    regions = [
        Region(layer="top_paste", points=rect_points(x, y, x + 0.6, y + 0.6))
        for x, y in ((-0.725, -0.725), (0.125, -0.725), (-0.725, 0.125), (0.125, 0.125))
    ]
    return FootprintSpec(
        name=name,
        description="QFN, 16-Leads, Body 3.00x3.00mm, Pitch 0.50mm, Thermal Pad 1.70x1.70mm",
        family="qfn",
        height=0.8,
        pads=pads,
        regions=regions,
        tracks=[*rect_tracks("courtyard", -2.1, -2.1, 2.1, 2.1, 0.05), *rect_tracks("assembly", -1.5, -1.5, 1.5, 1.5, 0.1)],
        texts=house_texts(),
        bodies=[Body3D(outline=rect_points(-1.5, -1.5, 1.5, 1.5), z_top=0.8)],
    )


def chip_with_step(step_file: str, name: str = "CAPC2012X125N") -> FootprintSpec:
    spec = chip_0603(name)
    spec.description = "Chip Capacitor 0805 with embedded STEP"
    spec.height = 1.25
    spec.bodies = [Body3D(name="Body", outline=rect_points(-1.0, -0.625, 1.0, 0.625), z_top=1.25, color="#C0A060")]
    spec.step = StepModel(file=step_file, rotation=(0.0, 0.0, 90.0), offset=(0.0, 0.0, 0.1))
    return spec


def write_step(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(STEP_TEXT, encoding="ascii")
    return path


# --------------------------------------------------------------------------- sanity


def test_samples_are_consistent():
    assert check_symbol_footprint(ic8_symbol(), soic8()) == []
    assert len(qfn16().pads) == 17
    assert opamp_symbol().bbox(3) != (0.0, 0.0, 0.0, 0.0)
    for spec in (chip_0603(), soic8(), header_tht(), qfn16()):
        assert spec.pad_designators()
