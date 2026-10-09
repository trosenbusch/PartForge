"""Shared infrastructure of the package-family generators.

Every family module exposes ``FAMILIES: list[FamilyDef]``. A family's ``build(ctx)`` reads its
parameters through ``ctx.p``, computes the land pattern via :mod:`..ipc7351`, draws everything
with a :class:`~..builder.FootprintBuilder` and returns ``ctx.finish(...)``.
"""
from __future__ import annotations

import copy
import math
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from ...geometry.model import FootprintSpec, Pad
from ...workspace import FootprintStyle
from .. import identity
from .. import ipc7351 as ipc
from .. import naming
from ..builder import DIODE_BAND, TIN, FootprintBuilder
from ..geom import XY, Rect, r6
from ..geom import pad_bbox as pad_box
from ..geom import rect_inflate as geom_inflate
from ..ipc7351 import Density, LandCalc, RoundingMode, fmt_mm
from ..models import FamilyInfo, FootprintRequest, ParamSpec, Tol
from ..naming import ascii_name, ascii_text
from ..params import MAX_DIMENSION, ParamError, Params, nom

# Where a parameter value came from (GenContext.sources): the request itself, an explicitly chosen
# preset, the preset an alias family name implies, a datasheet gap filled from a typical package
# (FootprintRequest.assumed), the workspace convention, or the ParamSpec default (not listed).
ParamSource = Literal["explicit", "preset", "alias", "assumed", "workspace", "default"]

# --------------------------------------------------------------------------- parameter specs


def p_tol(name: str, label: str, *, default: Any = None, help: str | None = None, group: str = "Körper",
          minimum: float | None = None, maximum: float | None = None) -> ParamSpec:
    return ParamSpec(name=name, label=label, kind="tol", unit="mm", default=default, help=help, group=group,
                     minimum=minimum, maximum=maximum)


def p_float(name: str, label: str, *, default: float | None = None, unit: str | None = "mm",
            help: str | None = None, group: str = "Körper", minimum: float | None = None,
            maximum: float | None = None) -> ParamSpec:
    return ParamSpec(name=name, label=label, kind="float", unit=unit, default=default, help=help, group=group,
                     minimum=minimum, maximum=maximum)


def p_int(name: str, label: str, *, default: int | None = None, help: str | None = None,
          group: str = "Anschlüsse", minimum: float | None = None, maximum: float | None = None) -> ParamSpec:
    return ParamSpec(name=name, label=label, kind="int", unit=None, default=default, help=help, group=group,
                     minimum=minimum, maximum=maximum)


def p_enum(name: str, label: str, options: Sequence[str], *, default: str | None = None,
           help: str | None = None, group: str = "Optionen", unit: str | None = None) -> ParamSpec:
    return ParamSpec(name=name, label=label, kind="enum", unit=unit, options=list(options), default=default,
                     help=help, group=group)


def p_bool(name: str, label: str, *, default: bool = False, help: str | None = None,
           group: str = "Optionen") -> ParamSpec:
    return ParamSpec(name=name, label=label, kind="bool", unit=None, default=default, help=help, group=group)


def p_text(name: str, label: str, *, default: str = "", help: str | None = None,
           group: str = "Optionen") -> ParamSpec:
    return ParamSpec(name=name, label=label, kind="text", unit=None, default=default, help=help, group=group)


ADV = "Erweitert"

COMMON_SMD: list[ParamSpec] = [
    p_float("fab_tolerance", "Fertigungstoleranz F", minimum=0.0, maximum=0.5, group=ADV,
            help="Leiterplatten-Fertigungstoleranz (gesamt). Leer = Hausstil (Standard 0,10 mm)."),
    p_float("placement_tolerance", "Bestückungstoleranz P", minimum=0.0, maximum=0.5, group=ADV,
            help="Platzierungstoleranz des Bestückers (gesamt). Leer = Hausstil (Standard 0,05 mm)."),
    p_enum("rounding", "Rundung", ["kicad", "ipc"], group=ADV,
           help="kicad: Z/G/X auf 0,05 mm (0,02 mm bei Chips < 0603); ipc: auf 0,01 mm. Leer = Hausstil."),
    p_float("min_copper_gap", "Min. Kupferabstand", default=ipc.DEFAULT_MIN_COPPER_GAP, minimum=0.05,
            maximum=1.0, group=ADV,
            help="Mindestabstand zwischen benachbarten Pads; zu breite oder zu nahe Pads werden begrenzt."),
    p_float("courtyard_excess", "Courtyard-Zugabe", minimum=0.0, maximum=5.0, group=ADV,
            help="Leer = IPC-Wert der Dichte (z. B. 0,25 mm bei Nominal)."),
    p_float("courtyard_grid", "Courtyard-Raster", default=ipc.DEFAULT_COURTYARD_GRID, minimum=0.01,
            maximum=0.5, group=ADV, help="Courtyard wird nach außen auf dieses Raster gerundet (Hausstil 0,05 mm)."),
]

COMMON_THT: list[ParamSpec] = [
    p_float("drill", "Bohrung (fest)", minimum=0.1, maximum=10.0, group=ADV,
            help="Leer = nach IPC-2222 aus dem Anschlussdurchmesser berechnet."),
    p_float("pad_diameter", "Paddurchmesser (fest)", minimum=0.2, maximum=15.0, group=ADV,
            help="Leer = Bohrung + Restring + Fertigungszugabe nach IPC-2221."),
    p_float("min_copper_gap", "Min. Kupferabstand", default=ipc.DEFAULT_MIN_COPPER_GAP, minimum=0.05,
            maximum=1.0, group=ADV),
    p_float("courtyard_excess", "Courtyard-Zugabe", minimum=0.0, maximum=5.0, group=ADV,
            help="Leer = 0,50 / 0,25 / 0,10 mm für M / N / L."),
    p_float("courtyard_grid", "Courtyard-Raster", default=ipc.DEFAULT_COURTYARD_GRID, minimum=0.01,
            maximum=0.5, group=ADV),
]

NAMING_PARAMS: list[ParamSpec] = [
    p_text("manufacturer", "Hersteller (Hausname)", group="Name",
           help="Optionales Präfix für Hausnamen, z. B. „TI“ → „TI SOIC-8 3.9x4.9MM“."),
    p_text("package_code", "Gehäusecode (Hausname)", group="Name",
           help="Optionaler Herstellercode als Suffix, z. B. „PW“ oder „DBV“."),
]

EP_DESIGNATOR_HELP = "Bezeichner des Exposed Pads: Hausstil (n+1 oder „EP“)."


# --------------------------------------------------------------------------- land pattern override


@dataclass
class LandOverride:
    pad_width: float
    pad_length: float
    row_spacing: float
    reference: Literal["center", "inner", "outer"]
    row_spacing_y: float | None = None
    ep_width: float | None = None
    ep_length: float | None = None


def _number(value: Any) -> float | None:
    """Positive number from a plain value, a numeric string or a ``{min, nom, max}`` dict."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Mapping):
        nom_v = _number(value.get("nom"))
        if nom_v is not None:
            return nom_v
        lo, hi = _number(value.get("min")), _number(value.get("max"))
        if lo is not None and hi is not None:
            return (lo + hi) / 2
        return lo if lo is not None else hi
    try:
        v = float(str(value).replace(",", "."))
    except ValueError:
        return None
    return v if math.isfinite(v) and 0 < v <= MAX_DIMENSION else None


def _first_number(data: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        v = _number(data.get(key))
        if v is not None:
            return v
    return None


def parse_land_override(data: Mapping[str, Any] | None) -> tuple[LandOverride | None, list[str]]:
    """Normalise a manufacturer land pattern (PartForge keys, datasheet-AI ``LandPattern`` keys or the
    corpus keys ``outer_span_mm``/``inner_span_mm``/``row_center_distance_mm_DERIVED``/``thermal_pad_mm``)."""
    if not data:
        return None, []
    if data.get("present_in_datasheet") is False:
        return None, []
    width = _first_number(data, "pad_width", "pad_width_mm", "X")
    length = _first_number(data, "pad_length", "pad_length_mm", "Y")
    spacing = _first_number(data, "row_spacing", "row_spacing_mm", "C")
    ref_raw = str(data.get("row_spacing_reference") or data.get("reference") or "center_to_center").lower()
    if spacing is None:
        center = _first_number(data, "row_center_distance", "row_center_distance_mm",
                               "row_center_distance_mm_DERIVED")
        if center is not None:
            spacing, ref_raw = center, "center_to_center"
    z = _first_number(data, "Z", "outer_span", "outer_span_mm")
    g = _first_number(data, "G", "inner_span", "inner_span_mm")
    thermal = data.get("thermal_pad_mm") or data.get("thermal_pad")
    ep_w = ep_l = None
    if isinstance(thermal, (list, tuple)) and len(thermal) == 2:
        ep_w, ep_l = _number(thermal[0]), _number(thermal[1])
    reference: Literal["center", "inner", "outer"] = "center"
    warnings: list[str] = []
    if spacing is None and z is not None and g is not None:
        spacing, reference = z, "outer"
        length = length or (z - g) / 2
    elif ref_raw.startswith("inner") or ref_raw in ("g", "gap"):
        reference = "inner"
    elif ref_raw.startswith("outer") or ref_raw in ("z",):
        reference = "outer"
    elif not (ref_raw.startswith("center") or ref_raw in ("c", "")):
        warnings.append("Bezug des Reihenabstands der Herstellerempfehlung unklar – Mitte-zu-Mitte angenommen.")
    if width is None or length is None or spacing is None:
        warnings.append("Herstellerempfehlung unvollständig (Padbreite, Padlänge, Reihenabstand) – "
                        "IPC-7351B-Berechnung wird verwendet.")
        return None, warnings
    return LandOverride(
        pad_width=width, pad_length=length, row_spacing=spacing, reference=reference,
        row_spacing_y=_first_number(data, "row_spacing_y", "row_spacing_y_mm"),
        ep_width=ep_w or _first_number(data, "ep_width", "thermal_pad_width", "ep_width_mm"),
        ep_length=ep_l or _first_number(data, "ep_length", "thermal_pad_length", "ep_length_mm"),
    ), warnings


# --------------------------------------------------------------------------- context


@dataclass
class GenContext:
    req: FootprintRequest
    style: FootprintStyle
    info: FamilyInfo
    p: Params
    density: Density
    F: float
    P: float
    rounding: RoundingMode
    min_gap: float
    cy_grid: float
    cy_excess: float | None
    with_3d: bool
    override: LandOverride | None = None
    preset: str | None = None
    family: FamilyDef | None = None
    sources: dict[str, ParamSource] = field(default_factory=dict)
    preset_labels: dict[str, str] = field(default_factory=dict)  # preset key -> label (for messages)
    # additional "standard" parameter sets besides the presets (e.g. chip size tables), see identity.py
    references: list[dict[str, Any]] = field(default_factory=list)
    # presets whose plain name (per naming scheme) an earlier preset with another land already uses
    alternates: Mapping[str, frozenset[str]] = field(default_factory=dict)
    probe: bool = False  # identity probe: plain names only, no standard check
    warnings: list[str] = field(default_factory=list)
    lands: list[LandCalc] = field(default_factory=list)
    calc: dict[str, Any] = field(default_factory=dict)
    extra_calc: dict[str, Any] = field(default_factory=dict)
    override_used: bool = False

    def builder(self, *, small_silk: bool = False) -> FootprintBuilder:
        width = self.style.silk_width_small if small_silk else self.style.silk_width
        return FootprintBuilder(self.style, silk_width=width)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def source(self, name: str) -> ParamSource:
        """Origin of a parameter value (``"default"`` if neither request nor preset set it)."""
        if not self.p.given(name):
            return "default"
        return self.sources.get(name, "explicit")

    def any_explicit(self, *names: str) -> bool:
        return any(self.p.given(n) and self.sources.get(n, "explicit") == "explicit" for n in names)

    def origin_text(self, name: str) -> str | None:
        """German phrase for a value that the datasheet/request did not give itself (None otherwise)."""
        src = self.source(name)
        if src == "default":
            return "Standardwert"
        if src in ("alias", "assumed", "preset"):
            label = self.preset_labels.get(self.preset or "", self.preset or "")
            return f"Vorlage „{label}“" if label else "Vorlage"
        return None

    def check_exposed_pad(self, has_ep: bool, ep_w: float, ep_l: float, *, body: Sequence[str] = ("E", "D"),
                          e2: str = "E2", d2: str = "D2") -> None:
        """Warn when the exposed pad was not given together with the other package dimensions
        (taken from a preset, a typical package or the default) or only one EP side was given."""
        if not has_ep:
            return
        origin = self.origin_text(e2)
        explicit_body = self.any_explicit(*body, "L", "b", "pins", "e")
        if origin is not None and (self.source(e2) == "assumed" or explicit_body):
            self.warn(f"Exposed Pad nicht angegeben: {fmt_mm(ep_w)} × {fmt_mm(ep_l)} mm aus {origin} übernommen – "
                      f"bitte mit dem Datenblatt prüfen ({e2} = 0 erzeugt den Footprint ohne Exposed Pad).")
        elif self.source(e2) != "default" and not self.p.given(d2):
            self.warn(f"Exposed Pad: {d2} fehlt – quadratisches Pad ({d2} = {e2} = {fmt_mm(ep_w)} mm) angenommen.")

    def cathode_pad(self) -> str:
        return self.p.enum("cathode_pad", "1")

    # -- land calculation ------------------------------------------------------------
    def ipc_land(
        self,
        L: Tol,  # noqa: N803
        T: Tol,  # noqa: N803
        W: Tol,  # noqa: N803
        table: str,
        *,
        S: Tol | None = None,  # noqa: N803
        axis: Literal["x", "y"] = "x",
        label: str = "",
        base: float | None = None,
        allow_override: bool = True,
    ) -> LandCalc:
        """IPC land of a row group, or the manufacturer pattern if one was supplied."""
        if allow_override and self.override is not None:
            ov = self.override
            spacing = ov.row_spacing if axis == "x" or ov.row_spacing_y is None else ov.row_spacing_y
            calc = ipc.manual_land(pad_length=ov.pad_length, pad_width=ov.pad_width, row_spacing=spacing,
                                   reference=ov.reference, density=self.density, axis=axis, label=label)
            self.override_used = True
        else:
            calc = ipc.land(L, T, W, table=table, density=self.density, F=self.F, P=self.P,
                            rounding=self.rounding, S=S, base=base, axis=axis, label=label)
        self.lands.append(calc)
        return calc

    def finalize_land(self, calc: LandCalc, *, pitch: float | None = None, ep: float = 0.0,
                      what: str = "Anschlusspads") -> LandCalc:
        """Clamps (EP clearance, minimum gap, width vs. pitch) and sanity check."""
        if calc.source == "manufacturer":
            if pitch and calc.x > pitch - self.min_gap + 1e-9:
                self.warn(f"Herstellerempfehlung: Padbreite {fmt_mm(calc.x)} mm lässt bei {fmt_mm(pitch)} mm "
                          f"Raster weniger als {fmt_mm(self.min_gap)} mm Kupferabstand.")
            if calc.g < self.min_gap - 1e-9:
                self.warn(f"Herstellerempfehlung: Innenabstand G = {fmt_mm(calc.g)} mm ist sehr klein.")
            ipc.check_land(calc, what)
            return calc
        for msg in ipc.clamp_exposed_pad(calc, ep):
            self.warn(msg)
        for msg in ipc.clamp_min_gap(calc, self.min_gap):
            self.warn(msg)
        if pitch:
            for msg in ipc.clamp_pad_width(calc, pitch, self.min_gap):
                self.warn(msg)
        ipc.check_land(calc, what)
        return calc

    # -- EP / tht helpers ------------------------------------------------------------------
    def ep_designator(self, pins: int) -> str:
        return "EP" if self.style.exposed_pad_designator == "EP" else str(pins + 1)

    def tht_land(self, lead_size: float, pitch: float, *, what: str = "Anschlüsse",
                 axis: Literal["x", "y"] = "x") -> ThtLand:
        return tht_land(self, lead_size, pitch, what=what, axis=axis)

    # -- result ----------------------------------------------------------------------------
    def finish(
        self,
        b: FootprintBuilder,
        *,
        ipc_name: str,
        house_name: str,
        description: str,
        package: str,
        height: float | None,
        courtyard_table: str | None = None,
        courtyard_kind: Literal["smd", "bga", "tht"] = "smd",
        extra_courtyard: Sequence[Rect] = (),
        component_ref: Rect | None = None,
    ) -> FootprintSpec:
        default_excess = ipc.courtyard_excess(courtyard_table, self.density, kind=courtyard_kind)
        excess = self.cy_excess if self.cy_excess is not None else default_excess
        cy = b.make_courtyard(excess, self.cy_grid, extra=extra_courtyard)
        b.component_marks(component_ref)
        text_h = b.add_texts()
        h = height if height is not None else b.max_height()
        if not self.with_3d:
            b.bodies.clear()
        for note in b.notes:
            self.warn(note)
        if self.p.resolved.get("cathode_pad") == "2":  # diode marked at pad 2: own name (IPC "reverse")
            ipc_name = naming.ipc_reverse(ipc_name)
            house_name = naming.house_reverse(house_name, self.density)
        standard = None if self.probe else self.standard_key(default_excess)
        tag = None if standard is not None or self.probe else identity.name_tag(
            self.info, self.density, self.p.resolved,
            free=self.family.free_params if self.family else frozenset(),
            max_only=self.family.max_only if self.family else frozenset(),
            land_pattern=self.override if self.override_used else None)
        # the names the generator gives these parameters (both schemes): any other name is a custom one
        generated = {"ipc": naming.with_tag(ipc_name, tag), "house": naming.with_tag(house_name, tag)}
        if self.req.name:
            name = ascii_name(self.req.name)
            if not name:
                raise ValueError("Der angegebene Footprint-Name enthält keine gültigen Zeichen.")
        else:
            name = generated["ipc"] if self.style.naming == "ipc" else generated["house"]
        parameters = {
            "IPC-Name": ipc_name,
            "Gehaeuse": ascii_text(package),
            "Dichte": f"{self.density} ({ipc.DENSITY_WIZARD_TEXT[self.density]})",
        }
        if h is not None:
            parameters["Hoehe"] = f"{h:.2f}mm"
        generator: dict[str, Any] = {
            "family": self.info.key,
            "params": copy.deepcopy(self.p.resolved),
            "density": self.density,
            "rounding": self.rounding,
            "version": 2,
            "standard": standard is not None,
            "name_tag": tag,
            "names": generated,
        }
        if name.casefold() not in {n.casefold() for n in generated.values()}:
            generator["name"] = name  # custom name ("MY_SOIC8"): "Neu generieren" passes it as FootprintRequest.name
        if self.preset:
            generator["preset"] = self.preset
        if self.req.land_pattern:
            generator["land_pattern"] = copy.deepcopy(self.req.land_pattern)
        spec = b.spec(
            name=name,
            description=self.req.description or ascii_text(description),
            family=self.info.key,
            ipc_name=ipc_name,
            density=self.density,
            height=None if h is None else r6(h),
            parameters=parameters,
            generator=generator,
        )
        assert spec.generator is not None
        spec.generator["land_hash"] = identity.land_hash(spec)
        spec.generator["geometry_hash"] = identity.geometry_hash(spec)
        self.calc = {
            "family": self.info.key,
            "package": package,
            "standard": "Herstellerempfehlung" if self.override_used else (
                self.lands[0].standard if self.lands else ("IPC-2222/2221" if courtyard_kind == "tht" else "IPC-7351B")),
            "density": self.density,
            "density_label": ipc.DENSITY_LABELS[self.density],
            "F": self.F,
            "P": self.P,
            "rounding": {"mode": self.rounding,
                         "base": sorted({land.round_base for land in self.lands}) if self.lands else []},
            "lands": [land.model_dump() for land in self.lands],
            "courtyard": {
                "excess": excess, "grid": self.cy_grid,
                "x1": cy[0], "y1": cy[1], "x2": cy[2], "y2": cy[3],
                "width": r6(cy[2] - cy[0]), "height": r6(cy[3] - cy[1]),
            },
            "pad_count": len(spec.pads),
            "height": spec.height,
            "text_height": text_h,
            "ipc_name": ipc_name,
            "house_name": house_name,
            "names": {"ipc": ipc_name, "house": house_name, "tag": tag,
                      "standard": standard if standard is None or not standard.startswith("#") else "Standardmaße"},
            **self.extra_calc,
        }
        return spec

    def standard_key(self, default_excess: float) -> str | None:
        """Preset (or family reference set) the request equals; ``None`` = custom dimensions."""
        if self.override_used:
            return None
        style_values = {
            "fab_tolerance": self.style.fab_tolerance,
            "placement_tolerance": self.style.placement_tolerance,
            "rounding": self.style.rounding,
            "courtyard_excess": default_excess,
        }
        key = identity.matching_preset(
            self.info, self.p.resolved,
            free=self.family.free_params if self.family else frozenset(),
            max_only=self.family.max_only if self.family else frozenset(),
            style_values=style_values, references=self.references, prefer=self.preset)
        if key is not None and key in self.alternates.get(self.style.naming, frozenset()):
            return None  # an earlier preset already owns this plain name with another land pattern
        return key


@dataclass(frozen=True)
class FamilyDef:
    """A generator family.

    ``aliases`` are additional names of the family; ``alias_params`` maps an alias to the parameters
    it implies (``"smb": {"variant": "SMB"}``); ``"preset"`` names the preset that supplies the other
    values (``"sc75": {"preset": "SC-75"}``, ``"*"`` = best match for the alias and the request's
    pins/pitch), see :func:`partforge.footprints.families.resolve`. ``free_params`` change neither the
    land pattern nor the names (3D-only values such as lead thickness) and ``max_only`` parameters only
    enter the footprint as their maximum (package height); both matter for the standard check in
    ``identity``.
    """

    info: FamilyInfo
    build: Callable[[GenContext], FootprintSpec]
    aliases: tuple[str, ...] = ()
    alias_params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    free_params: frozenset[str] = frozenset()
    max_only: frozenset[str] = frozenset()


# --------------------------------------------------------------------------- THT land


@dataclass(frozen=True)
class ThtLand:
    hole: float
    width: float
    height: float
    shape: Literal["circle", "oval"]
    diameter: float  # unclamped IPC diameter


def tht_land(ctx: GenContext, lead_size: float, pitch: float, *, what: str = "Anschlüsse",
             axis: Literal["x", "y"] = "x") -> ThtLand:
    """Hole and land per IPC-2222/2221; the land is narrowed to an oval if the pitch is too small.

    ``axis`` is the direction in which the neighbouring pads follow at ``pitch`` (``"x"``: rows along X
    such as axial, radial, TO-92, TO-220; ``"y"``: columns along Y such as DIP). The oval is narrow along
    that axis and long across it.
    """
    drill = ctx.p.float_opt("drill")
    hole = drill if drill is not None else ipc.tht_hole(lead_size, ctx.density)
    if drill is not None and drill < lead_size + 0.05:
        ctx.warn(f"{what}: Bohrung {fmt_mm(drill)} mm ist kaum größer als der Anschluss ({fmt_mm(lead_size)} mm "
                 "Diagonale) – Bestückung kann schwierig werden.")
    pad_override = ctx.p.float_opt("pad_diameter")
    d = pad_override if pad_override is not None else ipc.tht_pad(hole, ctx.density)
    if d <= hole + 2 * ipc.THT_ANNULAR_RING_MIN - 1e-9:
        raise ValueError(f"{what}: Pad {fmt_mm(d)} mm ist für die Bohrung {fmt_mm(hole)} mm zu klein "
                         f"(Restring < {fmt_mm(ipc.THT_ANNULAR_RING_MIN)} mm).")
    limit = ipc.round_down(pitch - ctx.min_gap, 0.01) if pitch > 0 else d
    if d <= limit + 1e-9:
        result = ThtLand(hole=hole, width=d, height=d, shape="circle", diameter=d)
    else:
        narrow = limit
        if narrow < hole + 2 * ipc.THT_ANNULAR_RING_MIN - 1e-9:
            raise ValueError(f"{what}: Raster {fmt_mm(pitch)} mm ist für Bohrung {fmt_mm(hole)} mm zu klein.")
        long_side = max(d, ipc.round_up(narrow * 1.4, 0.05))
        ctx.warn(f"{what}: Pad {fmt_mm(d)} mm passt nicht ins Raster {fmt_mm(pitch)} mm – ovales Pad "
                 f"{fmt_mm(narrow)} mm (in Rasterrichtung) × {fmt_mm(long_side)} mm verwendet.")
        if axis == "x":
            result = ThtLand(hole=hole, width=narrow, height=long_side, shape="oval", diameter=d)
        else:
            result = ThtLand(hole=hole, width=long_side, height=narrow, shape="oval", diameter=d)
    ctx.extra_calc.setdefault("tht", []).append({
        "what": what, "lead_size": r6(lead_size), "hole": hole, "pad": d, "pad_width": result.width,
        "pad_height": result.height, "shape": result.shape, "level": ipc.THT_LEVEL[ctx.density],
        "hole_allowance": ipc.THT_HOLE_ALLOWANCE[ipc.THT_LEVEL[ctx.density]],
        "fab_allowance": ipc.THT_FAB_ALLOWANCE[ipc.THT_LEVEL[ctx.density]], "pitch": pitch, "pitch_axis": axis,
    })
    return result


def check_row_fits_body(ctx: GenContext, *, pitch: float, positions: int, lead_width: Tol, body: Tol,
                        package: str, body_symbol: str = "D", hint: str = "") -> None:
    """Raise if a row of ``positions`` leads at ``pitch`` is clearly longer than the body.

    Typical cause: the datasheet's ``e`` is the distance between the outer leads (Nexperia/NXP) and
    the pitch is ``e1``.
    """
    span = (positions - 1) * pitch + nom(lead_width)
    if span > body.max + 0.1:
        raise ValueError(
            f"{package}: die Anschlussreihe ({positions} Anschlüsse im Raster {fmt_mm(pitch)} mm, "
            f"{fmt_mm(span)} mm) ist länger als der Körper ({body_symbol} max. {fmt_mm(body.max)} mm). "
            + (hint or "Bitte Raster und Körpermaße prüfen."))


# --------------------------------------------------------------------------- layout blocks


def row_positions(count: int, pitch: float) -> list[float]:
    """Coordinates of ``count`` pads centred on 0, first one at the positive end."""
    return [r6(((count - 1) / 2 - i) * pitch) for i in range(count)]


def dual_row(b: FootprintBuilder, land: LandCalc, per_side: int, pitch: float, *, start: int = 1,
             omit: Collection[int] = ()) -> list[Pad]:
    """Two rows along Y: left column top→bottom, right column bottom→top (pin 1 upper left).

    ``omit``: positions without terminal (1-based, counted as if every position had one); the pins are numbered
    consecutively over the remaining positions."""
    c = land.pad_center
    ys = row_positions(per_side, pitch)
    slots = [(-c, y) for y in ys] + [(c, y) for y in reversed(ys)]
    pads: list[Pad] = []
    for index, (x, y) in enumerate(slots, start=1):
        if index not in omit:
            pads.append(b.smd_pad(str(start + len(pads)), x, y, land.pad_length, land.x))
    return pads


def quad(b: FootprintBuilder, land_x: LandCalc, land_y: LandCalc, per_x: int, per_y: int, pitch: float, *,
         pitch_x: float | None = None, first: Literal["left", "top"] = "left",
         omit: Collection[int] = ()) -> list[Pad]:
    """Four sides, counter-clockwise from pin 1 at the top of the left side.

    ``land_x``: rows on the left/right sides (pads extend along X), ``per_y`` pads each at ``pitch``;
    ``land_y``: rows on the bottom/top sides (pads extend along Y), ``per_x`` pads each at ``pitch_x`` (default
    ``pitch``). ``first="top"``: pin 1 at the left end of the top side instead (e.g. TI RGY); the other positions
    keep their counter-clockwise order. ``omit``: positions without terminal (1-based, counted from pin 1 as if every
    position had one); the pins are numbered consecutively over the remaining positions.
    """
    ys = row_positions(per_y, pitch)
    xs = row_positions(per_x, pitch_x or pitch)
    cx, cy = land_x.pad_center, land_y.pad_center
    slots: list[tuple[float, float, bool]] = []  # (x, y, on the left/right side)
    slots += [(-cx, y, True) for y in ys]  # left, top -> bottom
    slots += [(x, -cy, False) for x in reversed(xs)]  # bottom, left -> right
    slots += [(cx, y, True) for y in reversed(ys)]  # right, bottom -> top
    slots += [(x, cy, False) for x in xs]  # top, right -> left
    if first == "top" and per_x:
        slots = slots[-1:] + slots[:-1]  # the left end of the top side comes first
    pads: list[Pad] = []
    for index, (x, y, left_right) in enumerate(slots, start=1):
        if index in omit:
            continue
        designator = str(len(pads) + 1)
        if left_right:
            pads.append(b.smd_pad(designator, x, y, land_x.pad_length, land_x.x))
        else:
            pads.append(b.smd_pad(designator, x, y, land_y.x, land_y.pad_length))
    return pads


def missing_positions(ctx: GenContext, positions: int | None = None) -> list[int]:
    """Positions without terminal from the text parameter ``missing`` („14“, „5, 6“), sorted; with ``positions`` (the
    number of positions of a fully populated package) each one is checked to exist."""
    text = ctx.p.text("missing")
    found: set[int] = set()
    for token in re.split(r"[,;\s]+", text):
        if not token:
            continue
        if not token.isdigit() or int(token) < 1:
            raise ParamError(f"Fehlende Anschlüsse: „{token}“ ist keine Positionsnummer (z. B. „14“ oder „5, 6“).",
                             params=("missing",))
        found.add(int(token))
    out = sorted(found)
    if positions is not None:
        beyond = [n for n in out if n > positions]
        if beyond:
            raise ParamError(f"Fehlende Anschlüsse: Position {beyond[0]} gibt es nicht – das Gehäuse hat {positions} "
                             "Positionen.", params=("missing",))
    return out


def dot_above(b: FootprintBuilder, pad: Pad) -> XY:
    return (pad.x, pad.y + pad.height / 2 + b.style.silk_pad_clearance + b.dot_radius())


def dot_left(b: FootprintBuilder, pad: Pad) -> XY:
    return (pad.x - pad.width / 2 - b.style.silk_pad_clearance - b.dot_radius(), pad.y)


def dot_corner(b: FootprintBuilder, body: Rect, gap: float = 0.1) -> XY:
    """Outside the top-left body corner (diagonal)."""
    off = b.silk_width / 2 + gap + b.dot_radius()
    return (body[0] - off, body[3] + off)


def ic_silk(b: FootprintBuilder, body: Rect, candidates: Sequence[XY], *, push: XY = (-0.7071, 0.7071),
            rows: Literal["lr", "quad"] = "lr") -> None:
    """IC silkscreen plus the pin-1 dot.

    ``quad``: body outline outside the body, clipped at the pads (→ corner brackets).
    ``lr`` (pads left/right): top and bottom lines over the body width, pushed outward until they
    clear the pads; the vertical body edges remain as clipped stubs between the pads.
    """
    w = b.silk_width
    if rows == "quad":
        b.silk_outline_outside(body, min_len=w)  # short corner brackets are fine
    else:
        x1, y1, x2, y2 = geom_inflate(body, w / 2)
        clear = b.style.silk_pad_clearance + w / 2
        top, bottom = y2, y1
        for pad in b.pads:
            px1, py1, px2, py2 = pad_box(pad)
            if px2 + clear > x1 and px1 - clear < x2:  # pad overlaps the line in X
                top = max(top, py2 + clear) if pad.y >= 0 else top
                bottom = min(bottom, py1 - clear) if pad.y <= 0 else bottom
        b.silk_line((x1, top), (x2, top))
        b.silk_line((x1, bottom), (x2, bottom))
        b.silk_line((x1, bottom), (x1, top))
        b.silk_line((x2, bottom), (x2, top))
    b.pin1_dot(candidates, push=push)


def two_terminal(
    b: FootprintBuilder,
    land: LandCalc,
    *,
    body_length: float,
    body_width: float,
    mark_pad: str | None = None,
) -> tuple[Pad, Pad]:
    """Pads 1 (left) / 2 (right), house silkscreen (two lines along the body, bracket on the
    marked side for polarised parts), assembly outline with polarity line."""
    c = land.pad_center
    p1 = b.smd_pad("1", -c, 0.0, land.pad_length, land.x)
    p2 = b.smd_pad("2", c, 0.0, land.pad_length, land.x)
    body = b.body((-body_length / 2, -body_width / 2, body_length / 2, body_width / 2))
    w = b.silk_width
    clear = b.style.silk_pad_clearance
    ys = max(body_width / 2 + w / 2, land.x / 2 + clear + w / 2)
    xe = max(body_length / 2 - w / 2, 0.1)
    if mark_pad in ("1", "2"):
        s = -1.0 if mark_pad == "1" else 1.0
        pad_outer = c + land.pad_length / 2
        xb = max(pad_outer + clear + w / 2, body_length / 2 + w / 2)
        b.silk_line((s * xb, ys), (-s * xe, ys))
        b.silk_line((s * xb, -ys), (-s * xe, -ys))
        b.silk_line((s * xb, ys), (s * xb, -ys), min_len=0.0)
        band = s * (body_length / 2 - max(0.1, min(0.5, 0.2 * body_length)))
        b.line("assembly", (band, -body_width / 2), (band, body_width / 2), b.style.assembly_width)
    elif 2 * xe >= 4 * w:  # tiny parts (01005/0201): no silkscreen, the stubs would be pointless
        b.silk_line((-xe, ys), (xe, ys))
        b.silk_line((-xe, -ys), (xe, -ys))
    b.assembly_rect(body)
    return p1, p2


def split_body_3d(
    b: FootprintBuilder,
    *,
    length: float,
    width: float,
    z0: float,
    z1: float,
    color: str,
    band_side: str | None = None,
    band_color: str = DIODE_BAND,
    band_fraction: float = 0.18,
    name: str = "Body",
) -> None:
    """Body box, optionally split into a coloured polarity band at the marked end."""
    x1, x2 = -length / 2, length / 2
    if band_side in ("1", "2"):
        bw = max(0.05, band_fraction * length)
        if band_side == "1":
            b.box(f"{name} band", (x1, -width / 2, x1 + bw, width / 2), z0, z1, band_color)
            x1 += bw
        else:
            b.box(f"{name} band", (x2 - bw, -width / 2, x2, width / 2), z0, z1, band_color)
            x2 -= bw
    b.box(name, (x1, -width / 2, x2, width / 2), z0, z1, color)


def terminals_3d(b: FootprintBuilder, *, length: float, width: float, t: float, z1: float,
                 color: str = TIN) -> None:
    """Two metallised end terminals of a chip part (x from the body ends inward by ``t``)."""
    b.box("Terminal 1", (-length / 2, -width / 2, -length / 2 + t, width / 2), 0.0, z1, color)
    b.box("Terminal 2", (length / 2 - t, -width / 2, length / 2, width / 2), 0.0, z1, color)


def describe(family_word: str, pins: int, body_length: float, body_width: float, density: str, *,
             pitch: float | None = None, thermal: tuple[float, float] | None = None,
             extra: str | None = None) -> str:
    """IPC-wizard style English description."""
    parts = [family_word, f"{pins}-Leads", f"Body {_d2(body_length)}x{_d2(body_width)}mm"]
    if pitch:
        parts.append(f"Pitch {_d2(pitch)}mm")
    if thermal:
        parts.append(f"Thermal Pad {_d2(thermal[0])}x{_d2(thermal[1])}mm")
    if extra:
        parts.append(extra)
    parts.append(ipc.DENSITY_WIZARD_TEXT[density])
    return ", ".join(parts)


def ep_size(ctx: GenContext, E2: Tol | None, D2: Tol | None) -> tuple[float, float]:  # noqa: N803
    """Exposed-pad land (x, y): package nominal, or the manufacturer pattern's thermal pad (oriented like
    the package EP, because land-pattern tables often list the two sides in arbitrary order)."""
    w = nom(E2) if E2 is not None else 0.0
    h = nom(D2) if D2 is not None else w
    ov = ctx.override
    if ov is not None and ov.ep_width and ov.ep_length:
        ow, oh = ov.ep_width, ov.ep_length
        if (w - h) * (ow - oh) < 0:
            ow, oh = oh, ow
        return ow, oh
    return w, h


def differs_from(base: Mapping[str, Any], values: Mapping[str, Tol]) -> bool:
    """True if any toleranced value deviates from the (min, max) pair stored in ``base``."""
    for key, t in values.items():
        ref = base.get(key)
        if ref is None:
            continue
        lo, hi = ref
        if abs(t.min - lo) > 1e-6 or abs(t.max - hi) > 1e-6:
            return True
    return False


def _d2(value: float) -> str:
    """Two decimals, rounded half-up (1.575 -> "1.58")."""
    return str(Decimal(repr(round(float(value), 6))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def height_of(A: Tol) -> float:  # noqa: N803
    """Package height used for names and 3D: the maximum value."""
    return A.max


def nominal(t: Tol) -> float:
    return nom(t)
