"""Shared geometry contract for schematic symbols and PCB footprints.

This module is the single source of truth that every producer (symbol/footprint
generators, datasheet AI, library readers) and every consumer (library writers for
Altium/Rust backend, SVG previews, three.js preview, STEP export) agrees on.
The frontend mirrors it in ``frontend/src/lib/geometry.ts`` (generated from OpenAPI).

Conventions
-----------
Symbols (``SymbolSpec``):
    * Unit **mil** (1/1000 inch), +X right, +Y up, origin = component origin.
    * Pins (attach end, length, tip) on the 10 mil raster with tips on the symbol grid
      (default 100 mil); graphics on a 5 mil raster (house inductor arcs use ±25/±75 mil).
    * ``SymPin.x/y`` is the **body-attach (inner) end** of the pin; ``orientation`` is the
      direction the pin points **outward** ("left" -> connection tip at x - length).
      This matches Altium's pin model and the altium-designer-mcp writer.
    * Active-low names use Altium's backslash-after-character overbar syntax (R\\E\\S\\E\\T\\).
    * Multi-part symbols: ``part_count`` > 1; ``SymPin.part`` = 1..n, 0 = shown in all parts
      (shared power pins). Graphics carry ``part`` the same way.

Footprints (``FootprintSpec``):
    * Unit **mm**, +X right, +Y up (top view), origin = package centroid (IPC-7351).
    * Logical layers (``FpLayer``) are mapped to Altium layers by the workspace
      ``LayerMap`` (e.g. courtyard -> Mechanical15) inside the library writers.
    * Rotation in degrees counter-clockwise.

3D bodies are simple extruded prisms (outline polygon + z range) which every backend
can represent (Altium extruded 3D bodies, STEP export, three.js preview).
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- common


class Point(BaseModel):
    x: float
    y: float


class FootprintLink(BaseModel):
    """Footprint model link stored in a symbol (Altium 'implementation')."""

    name: str
    library_path: str | None = None  # workspace-relative or absolute .PcbLib; None = search path
    description: str | None = None


# --------------------------------------------------------------------------- symbols

ElectricalType = Literal["input", "output", "io", "passive", "power", "open_collector", "open_emitter", "hiz"]
PinOrientation = Literal["left", "right", "up", "down"]
# Pin decorations that the Rust writer stores with correct Altium ordinals (VERIFIED in Altium).
PinDecoration = Literal[
    "none", "dot", "clock", "active_low_input", "analog_signal_in", "not_logic_connection", "right_left_signal_flow",
]
TextJustify = Literal[
    "bottom_left", "bottom_center", "bottom_right",
    "middle_left", "middle_center", "middle_right",
    "top_left", "top_center", "top_right",
]
LineWidth = Literal["smallest", "small", "medium", "large"]


class SymPin(BaseModel):
    designator: str
    name: str = ""
    x: int
    y: int
    orientation: PinOrientation
    length: int = 200
    electrical: ElectricalType = "passive"
    part: int = 1
    show_name: bool = True
    show_designator: bool = True
    hidden: bool = False
    description: str | None = None
    group: str | None = Field(default=None, description="Funktionsgruppe (nur PartForge, z. B. 'Versorgung')")
    inner_edge: PinDecoration | None = None  # e.g. "clock" (inside the body edge)
    outer_edge: PinDecoration | None = None  # e.g. "dot" (inversion bubble outside the body edge)

    def tip(self) -> tuple[int, int]:
        dx, dy = {"left": (-1, 0), "right": (1, 0), "up": (0, 1), "down": (0, -1)}[self.orientation]
        return self.x + dx * self.length, self.y + dy * self.length


class _SymGraphicBase(BaseModel):
    part: int = 1
    line_width: LineWidth = "small"
    color: str | None = None  # None = house style
    fill_color: str | None = None


class SymRect(_SymGraphicBase):
    kind: Literal["rect"] = "rect"
    x1: float
    y1: float
    x2: float
    y2: float
    filled: bool = True
    corner_radius: float = 0


class SymLine(_SymGraphicBase):
    kind: Literal["line"] = "line"
    points: list[Point]


class SymPolygon(_SymGraphicBase):
    kind: Literal["polygon"] = "polygon"
    points: list[Point]
    filled: bool = True


class SymArc(_SymGraphicBase):
    kind: Literal["arc"] = "arc"
    cx: float
    cy: float
    r: float
    start: float = 0  # degrees, CCW from +X
    end: float = 360


class SymEllipse(_SymGraphicBase):
    kind: Literal["ellipse"] = "ellipse"
    cx: float
    cy: float
    rx: float
    ry: float
    filled: bool = False


class SymText(_SymGraphicBase):
    kind: Literal["text"] = "text"
    x: float
    y: float
    text: str
    size: int = 10  # font size in pt (Altium default 10)
    justify: TextJustify = "bottom_left"
    rotation: Literal[0, 90, 180, 270] = 0


SymGraphic = Annotated[SymRect | SymLine | SymPolygon | SymArc | SymEllipse | SymText, Field(discriminator="kind")]


class TextPos(BaseModel):
    """Placement of the designator / comment text of a symbol (mil, anchor per justify)."""

    x: int
    y: int
    justify: TextJustify = "bottom_left"


class SymbolSpec(BaseModel):
    name: str  # == Altium "Library Ref"
    description: str = ""
    designator_prefix: str = "U"
    comment: str = "*"
    designator_pos: TextPos | None = None  # None = writer default (-50, 50)
    comment_pos: TextPos | None = None  # None = writer default (-50, -150)
    part_count: int = 1
    pins: list[SymPin] = Field(default_factory=list)
    graphics: list[SymGraphic] = Field(default_factory=list)
    parameters: dict[str, str] = Field(default_factory=dict)
    footprints: list[FootprintLink] = Field(default_factory=list)
    generator: dict | None = Field(default=None, description="Erzeugungsparameter für Neugenerierung")

    def bbox(self, part: int | None = None) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for p in self.pins:
            if part is not None and p.part not in (0, part):
                continue
            tx, ty = p.tip()
            xs += [p.x, tx]
            ys += [p.y, ty]
        for g in self.graphics:
            if part is not None and g.part not in (0, part):
                continue
            if isinstance(g, SymRect):
                xs += [g.x1, g.x2]
                ys += [g.y1, g.y2]
            elif isinstance(g, (SymLine, SymPolygon)):
                xs += [pt.x for pt in g.points]
                ys += [pt.y for pt in g.points]
            elif isinstance(g, SymArc):
                xs += [g.cx - g.r, g.cx + g.r]
                ys += [g.cy - g.r, g.cy + g.r]
            elif isinstance(g, SymEllipse):
                xs += [g.cx - g.rx, g.cx + g.rx]
                ys += [g.cy - g.ry, g.cy + g.ry]
            elif isinstance(g, SymText):
                xs.append(g.x)
                ys.append(g.y)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- footprints

FpLayer = Literal[
    "top_copper", "bottom_copper",
    "top_silk", "bottom_silk",
    "top_paste", "bottom_paste",
    "top_mask", "bottom_mask",
    "courtyard", "assembly", "body3d", "designator", "comment",
    "component_center", "component_outline", "keepout",
]
"""Logical layers. Mapping to Altium layer names (workspace ``LayerMap``):
top_copper -> "Top Layer", bottom_copper -> "Bottom Layer", top_silk -> LayerMap.silkscreen,
bottom_silk -> "Bottom Overlay", top_paste -> "Top Paste", top_mask -> "Top Solder",
courtyard/assembly/body3d/designator/comment/component_center/component_outline -> LayerMap.<name>,
keepout -> "Keep-Out Layer". Through-hole pads use "Multi-Layer"."""
PadShape = Literal["rect", "roundrect", "circle", "oval", "octagon"]


class Pad(BaseModel):
    designator: str
    x: float
    y: float
    width: float  # size along X before rotation
    height: float  # size along Y before rotation
    shape: PadShape = "roundrect"
    rotation: float = 0
    corner_radius_pct: int | None = None  # roundrect only, Altium % of half the shorter side; None = house style (50)
    side: Literal["top", "bottom", "through"] = "top"
    hole: float | None = None  # drill diameter (through pads)
    hole_length: float | None = None  # slot length (>= hole) for slotted holes
    hole_rotation: float | None = None  # slot direction in degrees (None = along the pad's longer side)
    plated: bool = True
    paste: bool = True  # paste aperture for SMD pads
    paste_expansion: float | None = None  # None = rule default
    mask_expansion: float | None = None  # None = rule default
    thermal: bool = False  # exposed / thermal pad (EP)


class Track(BaseModel):
    layer: FpLayer
    x1: float
    y1: float
    x2: float
    y2: float
    width: float


class Arc(BaseModel):
    layer: FpLayer
    cx: float
    cy: float
    r: float
    start: float = 0  # degrees CCW from +X
    end: float = 360
    width: float


class Region(BaseModel):
    """Filled polygon (copper/paste windows, courtyard area, keepout ...)."""

    layer: FpLayer
    points: list[Point]


class FpText(BaseModel):
    layer: FpLayer
    x: float
    y: float
    text: str  # ".Designator", ".Comment" or literal text
    height: float = 1.0
    stroke: float = 0.15
    rotation: float = 0
    justify: TextJustify = "middle_center"


class Body3D(BaseModel):
    """Extruded prism: outline in the XY plane from z_bottom (standoff) to z_top."""

    name: str = "Body"
    outline: list[Point]
    z_bottom: float = 0.0
    z_top: float
    color: str = "#2B2B2B"
    opacity: float = 1.0


class StepModel(BaseModel):
    # workspace-relative path (e.g. "3D\\SOIC8.step"), or an absolute path (e.g. a model
    # extracted from a library outside the workspace into the STEP cache)
    file: str
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)


class FootprintSpec(BaseModel):
    name: str  # == Altium "Footprint Ref"
    description: str = ""
    family: str = ""  # generator family key, e.g. "chip", "sot23", "soic", "qfn"
    ipc_name: str | None = None
    density: Literal["M", "N", "L"] | None = None
    height: float | None = None  # max component height in mm
    pads: list[Pad] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)
    arcs: list[Arc] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    texts: list[FpText] = Field(default_factory=list)
    bodies: list[Body3D] = Field(default_factory=list)
    step: StepModel | None = None
    parameters: dict[str, str] = Field(default_factory=dict)
    generator: dict | None = Field(default=None, description="Erzeugungsparameter für Neugenerierung")

    def pad_designators(self) -> list[str]:
        seen: list[str] = []
        for p in self.pads:
            if p.designator and p.designator not in seen:
                seen.append(p.designator)
        return seen

    def bbox(self, layers: set[str] | None = None) -> tuple[float, float, float, float]:
        xs: list[float] = []
        ys: list[float] = []
        for p in self.pads:
            if layers is not None and "copper" not in layers:
                continue
            r = math.radians(p.rotation)
            hw, hh = p.width / 2, p.height / 2
            ex = abs(hw * math.cos(r)) + abs(hh * math.sin(r))
            ey = abs(hw * math.sin(r)) + abs(hh * math.cos(r))
            xs += [p.x - ex, p.x + ex]
            ys += [p.y - ey, p.y + ey]
        for t in self.tracks:
            if layers is None or t.layer in layers:
                xs += [t.x1, t.x2]
                ys += [t.y1, t.y2]
        for a in self.arcs:
            if layers is None or a.layer in layers:
                xs += [a.cx - a.r, a.cx + a.r]
                ys += [a.cy - a.r, a.cy + a.r]
        for rg in self.regions:
            if layers is None or rg.layer in layers:
                xs += [pt.x for pt in rg.points]
                ys += [pt.y for pt in rg.points]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


# --------------------------------------------------------------------------- previews


class PreviewBundle(BaseModel):
    """What the UI needs to show a part: symbol + footprint (+ derived checks)."""

    symbol: SymbolSpec | None = None
    footprint: FootprintSpec | None = None
    warnings: list[str] = Field(default_factory=list)


def check_symbol_footprint(symbol: SymbolSpec, footprint: FootprintSpec) -> list[str]:
    """Strict consistency check: pins without pad and pads without pin (every gap is reported)."""
    pads = set(footprint.pad_designators())
    pins = {p.designator for p in symbol.pins}
    warnings = []
    missing = sorted(pins - pads, key=_natural_key)
    if missing:
        warnings.append(f"Pins ohne Pad im Footprint: {', '.join(missing)}")
    unused = sorted(pads - pins, key=_natural_key)
    if unused:
        warnings.append(f"Pads ohne Pin im Symbol: {', '.join(unused)}")
    return warnings


def pin_pad_check(
    symbol: SymbolSpec,
    footprint: FootprintSpec,
    *,
    free_pads: Iterable[str] = (),
    unused_ok: bool = False,
) -> tuple[list[str], list[str]]:
    """Pin/pad consistency of a symbol/footprint pair with the expected gaps: ``(problems, hints)``.

    The rule of the datasheet proposal and the symbol suggestion (``symbols.mapping``):

    * a pin without pad is always a problem;
    * a pad without pin is a problem – except ``free_pads`` (pads left free on purpose: NC pins of the
      datasheet, ``x`` in a letter-code pin map), exposed/thermal pads and, with ``unused_ok``
      (amplifiers, comparators, oscillators – NC and offset pads are normal), any other pad;
    * an exposed/thermal pad without pin is only a hint: connect it as the datasheet says.
    """
    return pin_pad_gaps(
        {p.designator for p in symbol.pins},
        set(footprint.pad_designators()),
        {p.designator for p in footprint.pads if p.thermal},
        free_pads=free_pads,
        unused_ok=unused_ok,
    )


def pin_pad_gaps(
    pins: Iterable[str],
    pads: Iterable[str],
    thermal: Iterable[str] = (),
    *,
    free_pads: Iterable[str] = (),
    unused_ok: bool = False,
) -> tuple[list[str], list[str]]:
    """:func:`pin_pad_check` on designator sets: symbol pins, footprint pads, exposed/thermal pads."""
    pin_set, pad_set, thermal_set = set(pins), {p for p in pads if p}, set(thermal)
    problems: list[str] = []
    missing = sorted(pin_set - pad_set, key=_natural_key)
    if missing:
        problems.append(f"Pins ohne Pad im Footprint: {', '.join(missing)}")
    unused = sorted(pad_set - pin_set - set(free_pads) - thermal_set, key=_natural_key)
    if unused and not unused_ok:
        problems.append(f"Pads ohne Pin im Symbol: {', '.join(unused)}")
    hints: list[str] = []
    open_ep = sorted((thermal_set & pad_set) - pin_set, key=_natural_key)
    if open_ep:
        hints.append(f"Exposed Pad {', '.join(open_ep)} ohne Pin im Symbol – auf der Leiterplatte laut Datenblatt "
                     "anschließen.")
    return problems, hints


def _natural_key(s: str) -> tuple:
    import re

    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s))
