"""Request/description models of the footprint generator (contract).

Dimensions with tolerances are given as ``Tol`` (min/nom/max in mm). Generators
accept either a ``Tol`` dict ``{"min":..,"max":..}`` (nom optional) or a plain
number (treated as min = nom = max).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..geometry.model import FootprintSpec


class Tol(BaseModel):
    min: float
    max: float
    nom: float | None = None

    @model_validator(mode="after")
    def _order(self) -> Tol:
        if self.max < self.min:
            self.min, self.max = self.max, self.min
        if self.nom is None:
            self.nom = (self.min + self.max) / 2
        return self

    @classmethod
    def of(cls, value: Any) -> Tol:
        if isinstance(value, Tol):
            return value
        if isinstance(value, (int, float)):
            return cls(min=float(value), max=float(value), nom=float(value))
        if isinstance(value, dict):
            return cls.model_validate(value)
        if isinstance(value, (list, tuple)) and len(value) in (2, 3):
            if len(value) == 2:
                return cls(min=float(value[0]), max=float(value[1]))
            return cls(min=float(value[0]), nom=float(value[1]), max=float(value[2]))
        raise ValueError(f"Ungültige Toleranzangabe: {value!r}")

    @property
    def tol(self) -> float:
        return self.max - self.min


ParamKind = Literal["tol", "float", "int", "bool", "enum", "text"]


class ParamSpec(BaseModel):
    name: str  # key in FootprintRequest.params (e.g. "L", "W", "T", "pitch", "pins")
    label: str  # German UI label
    kind: ParamKind = "tol"
    unit: str | None = "mm"
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    options: list[str] = Field(default_factory=list)
    help: str | None = None
    group: str | None = None  # UI grouping ("Körper", "Anschlüsse", "Optionen")


class Preset(BaseModel):
    key: str  # e.g. "0603" or "SOIC-8"
    label: str
    params: dict[str, Any]
    source: str | None = None  # data source note (JEDEC MS-012AA, Vishay CRCW, ...)


class FamilyInfo(BaseModel):
    key: str  # "chip", "soic", "qfn", ...
    label: str  # German UI label
    group: str  # "Chip-Bauteile", "ICs (Gull-Wing)", "ICs (No-Lead)", "Diskrete", "Bedrahtet", ...
    description: str = ""
    params: list[ParamSpec] = Field(default_factory=list)
    presets: list[Preset] = Field(default_factory=list)
    ipc_table: str | None = None  # J-value table used (e.g. "3-5")
    # --- extensions (backward compatible; filled by partforge.footprints.families()/family_info()) ---
    aliases: list[str] = Field(
        default_factory=list,
        description="Weitere Namen, unter denen die Familie gefunden wird (FootprintRequest.family), z. B. "
                    "„soic“, „dfn“, „sot363“ – ohne den Schlüssel selbst",
    )
    supports_land_pattern: bool = Field(
        default=False,
        description="Die Familie übernimmt eine Herstellerempfehlung (FootprintRequest.land_pattern) statt der "
                    "IPC-7351B-Berechnung",
    )


class FootprintRequest(BaseModel):
    family: str  # family key, alias ("dfn", "smb", "sot363" …: the alias also implies variant/pins) or package
    params: dict[str, Any] = Field(default_factory=dict)
    density: Literal["M", "N", "L"] = "N"
    name: str | None = None  # override generated name
    description: str | None = None
    land_pattern: dict[str, Any] | None = Field(
        default=None,
        description="Optional manufacturer land pattern (pad size/positions) that overrides the IPC calculation",
    )
    with_3d: bool = True
    # --- extensions (backward compatible) ---
    assumed: list[str] = Field(
        default_factory=list,
        description="Parameters that were not given by the datasheet but filled from a typical package "
                    "(see assumed_from); the generator warns about them",
    )
    assumed_from: str | None = Field(default=None, description="Preset key that supplied the assumed values")
    notes: list[str] = Field(
        default_factory=list,
        description="German notes from the datasheet mapping (e.g. how a letter was interpreted); "
                    "reported as warnings by generate()/preview()",
    )


IssueSeverity = Literal["error", "warning", "info"]


class CheckIssue(BaseModel):
    """Result of a footprint plausibility check (see ``partforge.footprints.validate``)."""

    severity: IssueSeverity
    code: str  # machine-readable, e.g. "silk_over_pad", "pad_clearance", "courtyard"
    message: str  # German user-facing text


class FootprintPreview(BaseModel):
    """Generator output for the UI: the spec plus calculation details."""

    spec: FootprintSpec  # geometry contract (partforge.geometry.model has no partforge imports: no cycle)
    calc: dict[str, Any] = Field(default_factory=dict)  # Zmax, Gmin, Xmax, J values, rounding, courtyard ...
    warnings: list[str] = Field(default_factory=list)
    # --- extensions (backward compatible) ---
    issues: list[CheckIssue] = Field(default_factory=list)  # structured validation results
    svg: str | None = None  # rendered preview (partforge.footprints.render.render_svg)
