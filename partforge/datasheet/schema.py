"""Structured-output schemas Claude fills (``output_config.format``).

Rules learned in the research (docs/entwicklung/recherche/claude-api.md §4) and in this module's probes:

* **No nullable unions.** ``float | None`` in nested arrays made the compiled grammar "too large"
  (HTTP 400). Missing numbers use the sentinel ``-1`` (mapped to ``None`` in :mod:`.normalize`),
  missing strings ``""``, missing lists ``[]``.
* **Two passes.** One schema with devices, variants, pin tables *and* package geometry was rejected as
  "compiled grammar too large" even without any enum (VERIFIED 2026-10-08 with tiny probes on
  claude-haiku-5-5); the identity/pin part (:class:`AiIdentity`) and the geometry part
  (:class:`AiGeometry`) compile separately. The geometry pass gets the package list of the identity pass.
* Every field is required (Pydantic fields without defaults); required properties are generated in
  schema order (identity first, geometry last).
* Fields added later stay required in the schema; answers recorded before them (replay fixtures) are completed by
  a before-validator (``AiPackage.terminal_layout`` -> :data:`NO_LAYOUT`).
* No "reasoning" fields (they can trigger ``reasoning_extraction`` refusals).
* A schema is part of the cached prompt prefix: each one is built once per process and serialised
  deterministically (property order = generation order).
* **Enums are constrained, parsing is tolerant.** "Enum casing is not guaranteed" (research §4.2): the enum
  fields are ``str`` for validation with an ``enum`` JSON schema (``WithJsonSchema`` – the schema sent to the API
  is identical to a ``Literal``), so one differently cased value never rejects a paid answer;
  :mod:`.normalize` maps the strings to the canonical values.

Page numbers in answers are 1-based pages of the **attached** PDF (subset); the code maps them back.
"""
from __future__ import annotations

import copy
import functools
import hashlib
import json
from typing import Annotated, Any

from pydantic import BaseModel, Field, WithJsonSchema, model_validator

from .models import ROW_REFERENCES

__all__ = [
    "AiDevice",
    "AiDimension",
    "AiGeometry",
    "AiIdentity",
    "AiLandPattern",
    "AiPackage",
    "AiPackageRef",
    "AiParameter",
    "AiPin",
    "AiPinTable",
    "AiTerminalLayout",
    "AiVariant",
    "ELECTRICAL_TYPES",
    "MOUNTINGS",
    "NO_LAYOUT",
    "PAD_SHAPES",
    "PageVote",
    "TRIAGE_CATEGORIES",
    "Triage",
    "UNITS",
    "family_keys",
    "geometry_schema",
    "identity_schema",
    "schema_fingerprint",
    "triage_schema",
]


def _enum(values: tuple[str, ...]) -> WithJsonSchema:
    """JSON schema ``{"type": "string", "enum": values}`` for a ``str`` field (see module docstring)."""
    return WithJsonSchema({"type": "string", "enum": list(values)})


ELECTRICAL_TYPES = ("Input", "IO", "Output", "OpenCollector", "Passive", "HiZ", "OpenEmitter", "Power")
UNITS = ("mm", "deg")
PAD_SHAPES = ("rectangle", "rounded_rectangle", "oval", "circle", "other", "unknown")
MOUNTINGS = ("SMD", "THT")
TRIAGE_CATEGORIES = ("identity", "pinout", "ordering", "package_outline", "land_pattern", "electrical", "irrelevant")

AiElectricalType = Annotated[str, _enum(ELECTRICAL_TYPES)]
AiUnit = Annotated[str, _enum(UNITS)]
AiPadShape = Annotated[str, _enum(PAD_SHAPES)]
AiRowReference = Annotated[str, _enum(ROW_REFERENCES)]
AiMounting = Annotated[str, _enum(MOUNTINGS)]
TriageCategory = Annotated[str, _enum(TRIAGE_CATEGORIES)]

_NA = "-1 if the datasheet does not give this value."
_PAGES = "1-based page numbers of the attached PDF; [] if none."


# --------------------------------------------------------------------------- pass 1: identity and pins


class AiPin(BaseModel):
    number: str = Field(description="Pin/pad designator exactly as printed for THIS package, e.g. '1', 'A3'; "
                                    "the exposed/thermal pad as printed, else 'EP'.")
    name: str = Field(description="Short schematic pin name as printed, e.g. '-IN', 'VCC', 'OUT A'. Active-low "
                                  "names in Altium overbar syntax: a backslash after every overlined character, "
                                  "e.g. 'C\\S\\' for CS with overbar, 'TCLK_R/F\\' if only F is overlined.")
    function: str = Field(description="Pin function as written in the datasheet, short.")
    electrical_type: AiElectricalType = Field(description="Altium pin type: supply/ground/exposed pad -> Power, "
                                                          "NC -> Passive.")
    active_low: bool
    no_connect: bool
    group: str = Field(description="Functional group for the schematic symbol, e.g. 'Supply', 'SPI', "
                                   "'Channel A', 'Data inputs'; '' if none.")
    part: int = Field(description="Symbol part for multi-channel devices (channel A = 1, B = 2 ...); 0 for supply "
                                  "pins shared by all channels; 1 for single-channel devices.")


class AiPinTable(BaseModel):
    package_code: str = Field(description="package_code of the package this pin table belongs to.")
    source_pages: list[int] = Field(description=_PAGES)
    pins: list[AiPin] = Field(description="Complete pin table for this package incl. NC pins and the exposed pad, "
                                          "ordered by pin number.")


class AiParameter(BaseModel):
    column: str = Field(description="Exactly one of the field names listed for the chosen category.")
    value: str = Field(description="Value with unit as printed, typ value unless only min/max exist, "
                                   "e.g. '230MHz', '290V/µs', '-40°C to 85°C'; numbers without thousands separators "
                                   "('2000pF', not '2,000pF'); enum fields: one listed option.")
    page: int = Field(description="1-based page of the attached PDF; -1 if unknown.")


class AiVariant(BaseModel):
    mpn: str = Field(description="Complete orderable manufacturer part number, e.g. 'OPA656U/2K5'.")
    package_code: str
    temperature_range: str = Field(description="e.g. '-40°C to 85°C'; '' if not stated.")
    packaging: str = Field(description="Transport media and quantity, e.g. 'Tape and Reel, 2500'; ''.")
    status: str = Field(description="Lifecycle status if stated (ACTIVE, PREVIEW, NRND, OBSOLETE ...); ''.")
    notes: str = Field(description="Grade, options, marking or other ordering notes; ''.")
    values: list[AiParameter] = Field(description="Field values that differ between the part numbers of this "
                                                  "device (e.g. resistance or inductance per part number); [] if none.")
    page: int = Field(description="1-based page of the attached PDF; -1 if unknown.")


class AiDevice(BaseModel):
    base_part_number: str = Field(description="Base part number without ordering suffixes, e.g. 'OPA656'.")
    description: str = Field(description="Short component description, max. 80 characters.")
    category: str = Field(description="Exactly one of the category table names listed in the instructions.")
    parameters: list[AiParameter] = Field(description="Values for the fields of the chosen category.")
    variants: list[AiVariant] = Field(description="All orderable part numbers of this device.")
    pin_tables: list[AiPinTable] = Field(description="One complete pin table per package of this device.")


class AiPackageRef(BaseModel):
    package_code: str = Field(description="Manufacturer package designator, e.g. 'D', 'DBV', 'SN', 'RM-10'; else the "
                                          "package name. Unique; used by variants and pin tables.")
    package_name: str = Field(description="Common name with pin count, e.g. 'SOIC-8', 'SOT-23-5', 'VQFN-32 5x5'.")
    pin_count: int = Field(description="Number of leads/terminals WITHOUT the exposed pad.")
    exposed_pad: bool


class AiIdentity(BaseModel):
    manufacturer: str
    document_id: str = Field(description="Literature number / document id, e.g. 'SBOS196G'; ''.")
    document_title: str
    document_date: str
    devices: list[AiDevice] = Field(description="One entry per distinct device of the datasheet.")
    packages: list[AiPackageRef] = Field(description="Every package used by the devices.")
    warnings: list[str] = Field(description="Ambiguities, conflicts between pages, values that could not be read.")


# --------------------------------------------------------------------------- pass 2: package geometry


class AiDimension(BaseModel):
    symbol: str = Field(description="Dimension letter as printed (JEDEC style: A, A1, b, c, D, D2, E, E1, E2, e, L, "
                                    "theta ...); '' if none.")
    description: str = Field(description="What is measured, e.g. 'body length', 'overall width incl. leads', "
                                         "'lead pitch (basic)', 'exposed pad width'.")
    unit: AiUnit
    min: float = Field(description=_NA)
    nom: float = Field(description=_NA)
    max: float = Field(description=_NA)


class AiLandPattern(BaseModel):
    present: bool = Field(description="True only if the PDF shows a recommended land pattern / example board "
                                      "layout for this package.")
    source_pages: list[int] = Field(description=_PAGES)
    pad_shape: AiPadShape
    pad_width: float = Field(description="Pad size parallel to the pad row (across the lead), mm. " + _NA)
    pad_length: float = Field(description="Pad size along the lead (perpendicular to the row), mm. " + _NA)
    pitch: float = Field(description="Centre distance of adjacent pads, mm. " + _NA)
    row_spacing: float = Field(description="Distance between the opposing pad rows as dimensioned, mm. " + _NA)
    row_spacing_reference: AiRowReference = Field(
        description="Features the row_spacing dimension connects: pad centre lines (center_to_center), inner or outer "
                    "pad edges, or the centre of one pad to the centre of the component (half the centre distance, "
                    "pad_center_to_component_center).")
    thermal_pad_width: float = Field(description="Exposed/thermal pad land, mm. " + _NA)
    thermal_pad_length: float = Field(description="Exposed/thermal pad land, mm. " + _NA)
    solder_mask_expansion: float = Field(description="Solder mask opening per side, mm. " + _NA)
    notes: str


class AiTerminalLayout(BaseModel):
    pin1_side_positions: int = Field(description="Packages with terminals on four sides (QFN, QFP ...): terminal "
                                                  "positions on the side with pin 1, empty positions included; -1 for "
                                                  "packages with terminals on fewer than four sides.")
    adjacent_side_positions: int = Field(description="Terminal positions on each of the two sides next to the pin-1 "
                                                     "side, counted the same way; -1 as above.")
    pin1_side_dimension: str = Field(description="Symbol of the body dimension measured along the side with pin 1, as "
                                                 "used in dimensions (e.g. 'D'); '' if unclear.")
    pin1_last_on_side: bool = Field(description="True only if pin 1 is the last position of its side and pin 2 is on "
                                                "the next side (e.g. TI RGY); false if pin 2 follows on the same side.")
    pin1_side_pitch: float = Field(description="Terminal pitch on the pin-1 side, mm, only if it differs from e; "
                                               "else -1.")
    adjacent_side_pitch: float = Field(description="Terminal pitch on the adjacent sides, mm, only if it differs from "
                                                   "e; else -1.")
    missing_positions: list[int] = Field(description="Positions without terminal, numbered from pin 1 like the pins "
                                                     "as if every position had one; [] if none.")


NO_LAYOUT: dict[str, Any] = {
    "pin1_side_positions": -1, "adjacent_side_positions": -1, "pin1_side_dimension": "", "pin1_last_on_side": False,
    "pin1_side_pitch": -1, "adjacent_side_pitch": -1, "missing_positions": [],
}


class AiPackage(BaseModel):
    package_code: str = Field(description="The package code from the instructions (or the manufacturer designator).")
    package_name: str = Field(description="Common name with pin count, e.g. 'SOIC-8', 'SOT-23-5', 'VQFN-32 5x5'.")
    family: str = Field(description="Footprint family key from the list (see enum).")
    pin_count: int = Field(description="Number of leads/terminals WITHOUT the exposed pad.")
    mounting: AiMounting
    outline_reference: str = Field(description="JEDEC/EIAJ outline reference if stated, e.g. 'MS-012 AA'; ''.")
    exposed_pad: bool
    exposed_pad_number: str = Field(description="Pin number of the exposed pad if the datasheet gives one, else ''.")
    source_pages: list[int] = Field(description="Pages with the package outline drawing. " + _PAGES)
    dimensions: list[AiDimension] = Field(description="All outline dimensions in mm (use the mm values of "
                                                      "'inch (mm)' drawings).")
    land_pattern: AiLandPattern
    terminal_layout: AiTerminalLayout

    @model_validator(mode="before")
    @classmethod
    def _older_answers(cls, data: Any) -> Any:
        """Answers recorded before the terminal layout was asked for: no layout (the schema still requires it)."""
        if isinstance(data, dict) and "terminal_layout" not in data:
            return {**data, "terminal_layout": dict(NO_LAYOUT)}
        return data


class AiGeometry(BaseModel):
    packages: list[AiPackage] = Field(description="One entry per requested package.")
    warnings: list[str] = Field(description="Ambiguities, conflicts between pages, values that could not be read.")


# --------------------------------------------------------------------------- page triage


class PageVote(BaseModel):
    page: int
    categories: list[TriageCategory]


class Triage(BaseModel):
    pages: list[PageVote]


# --------------------------------------------------------------------------- schema dicts


def family_keys() -> list[str]:
    """Footprint family keys (UI order) plus ``other`` – the enum of ``AiPackage.family``."""
    from ..footprints.families import registry

    return [*registry().keys(), "other"]


def _transform(model: type[BaseModel]) -> dict[str, Any]:
    import anthropic

    return anthropic.transform_schema(model)


def _set_family_enum(schema: dict[str, Any], keys: list[str]) -> None:
    """Restrict ``AiPackage.family`` to the footprint family keys (found wherever transform_schema put it)."""
    def visit(node: Any) -> None:
        if isinstance(node, dict):
            props = node.get("properties")
            if isinstance(props, dict) and "family" in props and "package_code" in props:
                props["family"] = {**props["family"], "enum": list(keys)}
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)


@functools.cache
def _schema_json(name: str) -> str:
    if name == "identity":
        schema = _transform(AiIdentity)
    elif name == "geometry":
        schema = _transform(AiGeometry)
        _set_family_enum(schema, family_keys())
    elif name == "triage":
        schema = _transform(Triage)
    else:
        raise KeyError(name)
    return json.dumps(schema, ensure_ascii=False)  # keep property order: it is the generation order


def identity_schema() -> dict[str, Any]:
    """JSON schema of :class:`AiIdentity` (byte-stable per process; a fresh copy per call)."""
    return copy.deepcopy(json.loads(_schema_json("identity")))


def geometry_schema() -> dict[str, Any]:
    """JSON schema of :class:`AiGeometry` (family enum = footprint family keys)."""
    return copy.deepcopy(json.loads(_schema_json("geometry")))


def triage_schema() -> dict[str, Any]:
    return copy.deepcopy(json.loads(_schema_json("triage")))


def schema_fingerprint() -> str:
    """Short hash of both extraction schemas (stored with fixtures and runs)."""
    text = _schema_json("identity") + _schema_json("geometry")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
