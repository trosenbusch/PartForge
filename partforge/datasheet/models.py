"""Data models of the datasheet import (normalised extraction, stored metadata, proposals).

Three layers:

* :mod:`.schema` – the compact structured-output schema Claude fills (sentinel ``-1`` instead of
  ``null``, English enum spellings, page numbers of the *attached* PDF subset).
* this module – the **normalised** extraction (``None`` for missing values, PartForge electrical
  types, Altium overbar pin names, real datasheet page numbers) plus the metadata PartForge stores
  in ``DatasheetRecord.extraction`` (:class:`DatasheetMeta`) and the proposal/commit models.
* :mod:`partforge.api.routes_datasheets` – request/response wrappers.

All user-facing texts (issues, warnings) are German; identifiers are English.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..geometry.model import ElectricalType, FootprintSpec, SymbolSpec

META_FORMAT = "partforge-datasheet/1"

PageQuality = Literal["ok", "empty", "glyph"]
"""Text layer of a page: ``ok`` usable, ``empty`` no text (vector drawing or scan), ``glyph`` glyph-ID encoded
garbage (``/g27/g16`` …, readable only as an image)."""

RowReference = Literal["center_to_center", "inner_edges", "outer_edges", "pad_center_to_component_center",
                       "not_applicable", "unclear"]
"""What the row-spacing dimension of a manufacturer land pattern connects. ``pad_center_to_component_center`` is
half the centre distance (e.g. KEMET ``C``: centre of the component to the centre of a pad)."""
ROW_REFERENCES: tuple[str, ...] = ("center_to_center", "inner_edges", "outer_edges", "pad_center_to_component_center",
                                   "not_applicable", "unclear")
Severity = Literal["error", "warning", "info"]
RunKind = Literal["triage", "identity", "geometry", "verify_identity", "verify_geometry", "test", "find"]


# --------------------------------------------------------------------------- PDF analysis


class PageInfo(BaseModel):
    """Text-layer analysis of one PDF page (1-based ``page``)."""

    page: int
    chars: int = 0  # non-whitespace characters of the usable text (decoded for glyph pages)
    quality: PageQuality = "ok"
    width_pt: float = 0.0
    height_pt: float = 0.0
    categories: list[str] = Field(
        default_factory=list,
        description="Keyword hits: pins, ordering, package, land_pattern, noise, toc, drawing",
    )


# --------------------------------------------------------------------------- normalised extraction


class DimValue(BaseModel):
    """One package dimension (mm, angles in degrees); ``None`` = not given in the datasheet."""

    symbol: str = ""
    description: str = ""
    unit: Literal["mm", "deg"] = "mm"
    min: float | None = None
    nom: float | None = None
    max: float | None = None

    def value(self) -> float | None:
        """Nominal value (nom, else the middle of min/max, else the single limit)."""
        if self.nom is not None:
            return self.nom
        if self.min is not None and self.max is not None:
            return (self.min + self.max) / 2
        return self.min if self.min is not None else self.max


class LandPatternData(BaseModel):
    """Manufacturer-recommended land pattern (only from a drawing in the datasheet)."""

    present: bool = False
    pages: list[int] = Field(default_factory=list)
    pad_shape: str = "unknown"
    pad_width: float | None = None  # across the lead (parallel to the pad row)
    pad_length: float | None = None  # along the lead
    pitch: float | None = None
    row_spacing: float | None = None
    row_spacing_reference: RowReference = "unclear"
    thermal_pad_width: float | None = None
    thermal_pad_length: float | None = None
    solder_mask_expansion: float | None = None
    notes: str = ""

    def complete(self) -> bool:
        return self.present and None not in (self.pad_width, self.pad_length, self.row_spacing)

    def center_distance(self) -> float | None:
        """Distance between the pad centre lines of the two rows (mm), derived from the reference;
        ``unclear``/``not_applicable`` are taken as centre-to-centre (as the footprint generator does)."""
        if self.row_spacing is None:
            return None
        ref = self.row_spacing_reference
        if ref == "inner_edges":
            return self.row_spacing + self.pad_length if self.pad_length is not None else None
        if ref == "outer_edges":
            return self.row_spacing - self.pad_length if self.pad_length is not None else None
        if ref == "pad_center_to_component_center":
            return 2 * self.row_spacing
        return self.row_spacing

    def to_override(self) -> dict[str, Any] | None:
        """Land-pattern dict for :func:`partforge.footprints.request_from_package` (``None`` if incomplete).

        The generator knows centre/inner/outer references; a half distance (pad centre to component centre)
        is converted to the centre-to-centre distance."""
        if not self.complete():
            return None
        spacing, reference = self.row_spacing, str(self.row_spacing_reference)
        if reference == "pad_center_to_component_center" and spacing is not None:
            spacing, reference = round(2 * spacing, 6), "center_to_center"
        out: dict[str, Any] = {
            "pad_width_mm": self.pad_width,
            "pad_length_mm": self.pad_length,
            "row_spacing_mm": spacing,
            "row_spacing_reference": reference,
        }
        if self.thermal_pad_width and self.thermal_pad_length:
            out["thermal_pad_mm"] = [self.thermal_pad_width, self.thermal_pad_length]
        return out


class PackageData(BaseModel):
    code: str  # unique key within the extraction (manufacturer code, e.g. "D", "DBV"; else the name)
    name: str = ""  # common name, e.g. "SOIC-8"
    family: str | None = None  # footprint family key (partforge.footprints), None = unknown
    family_raw: str = ""  # family as answered by Claude
    pin_count: int | None = None  # leads/terminals without the exposed pad
    mounting: Literal["SMD", "THT"] | None = None
    outline_reference: str = ""
    exposed_pad: bool = False
    exposed_pad_number: str = ""  # EP designator if the datasheet numbers it
    pages: list[int] = Field(default_factory=list)  # outline drawing pages (real page numbers)
    dimensions: list[DimValue] = Field(default_factory=list)
    land_pattern: LandPatternData = Field(default_factory=LandPatternData)

    def dim(self, *symbols: str) -> DimValue | None:
        """First dimension with one of the symbols (case-sensitive JEDEC letters, mm only)."""
        for symbol in symbols:
            for d in self.dimensions:
                if d.symbol == symbol and d.unit == "mm" and d.value() is not None:
                    return d
        return None

    @property
    def label(self) -> str:
        """``SOIC-8 (D)``; the code is omitted when the name already contains it as a word (``DFN-8 (DD)``)."""
        if self.name and self.code:
            tokens = {t.casefold() for t in re.split(r"[^A-Za-z0-9]+", self.name) if t}
            if self.code.casefold() not in tokens and self.code.casefold() != self.name.casefold():
                return f"{self.name} ({self.code})"
        return self.name or self.code


class PinData(BaseModel):
    number: str
    name: str = ""  # Altium overbar syntax for active-low characters (R\E\S\E\T\)
    function: str = ""
    electrical: ElectricalType = "passive"
    active_low: bool = False
    no_connect: bool = False
    exposed_pad: bool = False
    group: str = ""
    part: int = 1  # 1..n for multi-channel devices, 0 = shared (supply)


class PinTableData(BaseModel):
    package: str  # PackageData.code
    pages: list[int] = Field(default_factory=list)
    pins: list[PinData] = Field(default_factory=list)


class ParameterData(BaseModel):
    column: str  # field (column) of the device's category
    value: str  # normalised text (partforge.db.values.normalize_cell)
    raw: str = ""  # as answered by Claude
    page: int | None = None
    warning: str | None = None


class VariantData(BaseModel):
    mpn: str
    package: str = ""  # PackageData.code
    temperature_range: str = ""
    packaging: str = ""
    status: str = ""
    notes: str = ""
    values: list[ParameterData] = Field(default_factory=list)  # values that differ per part number
    pages: list[int] = Field(default_factory=list)


class DeviceData(BaseModel):
    base_part: str
    description: str = ""
    category: str | None = None  # category table of the open workspace (validated)
    category_raw: str = ""
    parameters: list[ParameterData] = Field(default_factory=list)
    variants: list[VariantData] = Field(default_factory=list)
    pin_tables: list[PinTableData] = Field(default_factory=list)

    def pin_table(self, package: str) -> PinTableData | None:
        return next((t for t in self.pin_tables if t.package == package), None)


class Issue(BaseModel):
    """Result of an automatic plausibility check."""

    severity: Severity
    code: str  # pin_count, pin_duplicate, dim_order, dims_missing, pitch_mismatch, unknown_family, ...
    message: str  # German
    device: str | None = None
    package: str | None = None
    vision: bool = False  # True: a high-resolution re-check of the drawings may fix it


class ExtractionData(BaseModel):
    manufacturer: str = ""
    document_id: str = ""
    title: str = ""
    date: str = ""
    devices: list[DeviceData] = Field(default_factory=list)
    packages: list[PackageData] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # ambiguities reported by Claude (as answered)
    issues: list[Issue] = Field(default_factory=list)  # PartForge plausibility checks (German)

    def package(self, code: str) -> PackageData | None:
        wanted = code.strip().casefold()
        return next((p for p in self.packages if p.code.casefold() == wanted), None)

    def device(self, base_part: str | None) -> DeviceData | None:
        if not self.devices:
            return None
        if not base_part:
            return self.devices[0]
        wanted = base_part.strip().casefold()
        return next((d for d in self.devices if d.base_part.casefold() == wanted), None)

    def mpns(self) -> list[str]:
        out: list[str] = []
        for device in self.devices:
            for variant in device.variants:
                if variant.mpn and variant.mpn not in out:
                    out.append(variant.mpn)
        return out


# --------------------------------------------------------------------------- API runs and stored metadata


class Usage(BaseModel):
    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0


class RunInfo(BaseModel):
    """One Claude API call of an import (for cost display and auditing)."""

    kind: RunKind
    model: str  # requested model
    served_model: str = ""  # model that answered (differs after a server-side fallback)
    effort: str = ""
    pages: list[int] = Field(default_factory=list)  # real page numbers sent (PDF subset or renders)
    request_id: str | None = None
    usage: Usage = Field(default_factory=Usage)
    cost_usd: float = 0.0
    duration_s: float = 0.0
    stop_reason: str | None = None
    fallback: bool = False
    ts: str = ""
    error: str | None = None  # German reason when the answer of this (paid) call could not be used


class CommitInfo(BaseModel):
    ts: str
    table: str
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    symbols: list[str] = Field(default_factory=list)
    footprints: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)  # MPN / part number -> German reason (not created)
    warnings: list[str] = Field(default_factory=list)


class DatasheetMeta(BaseModel):
    """Everything PartForge stores in ``DatasheetRecord.extraction`` (JSON)."""

    format: str = META_FORMAT
    source_url: str | None = None
    size_bytes: int = 0
    encrypted: bool = False
    analyzed: str | None = None  # ISO timestamp of the text-layer analysis
    pages: list[PageInfo] = Field(default_factory=list)
    selected_pages: list[int] = Field(default_factory=list)
    selection_method: str = ""
    identity_pages: list[int] = Field(default_factory=list)  # pages sent to the identity/pin pass
    geometry_pages: list[int] = Field(default_factory=list)  # pages sent to the package geometry pass
    extraction: ExtractionData | None = None
    raw: dict[str, Any] | None = None  # last valid answers of Claude (schema form): {"identity": …, "geometry": …}
    model: str = ""
    effort: str = ""
    extracted: str | None = None  # ISO timestamp of the last extraction
    edited: bool = False  # the user changed the extraction (PUT /extraction)
    runs: list[RunInfo] = Field(default_factory=list)  # every paid call, also those of failed analyses
    cost_usd: float = 0.0  # sum over all runs of this datasheet
    last_error: str | None = None  # German reason of the last failed analysis (cleared by a successful one)
    committed: list[CommitInfo] = Field(default_factory=list)


PENDING_FORMAT = "partforge-datasheet-result/1"


class PendingResult(BaseModel):
    """A (paid) analysis result whose library was closed when it was finished – kept as JSON in that library's folder
    (``Datasheets/.pending``) and merged into its ``pf_datasheets`` record when the library is opened again."""

    format: str = PENDING_FORMAT
    datasheet_id: str
    created: str
    kind: Literal["extraction", "failure"]
    runs: list[RunInfo] = Field(default_factory=list)  # paid calls of that analysis
    # kind "extraction": the stored result (as run_extraction saves it)
    extraction: ExtractionData | None = None
    raw: dict[str, Any] | None = None
    model: str = ""
    effort: str = ""
    extracted: str | None = None
    selected_pages: list[int] = Field(default_factory=list)
    selection_method: str = ""
    identity_pages: list[int] = Field(default_factory=list)
    geometry_pages: list[int] = Field(default_factory=list)
    manufacturer: str | None = None
    mpns: list[str] = Field(default_factory=list)
    title: str | None = None
    # kind "failure": the reason
    last_error: str | None = None


# --------------------------------------------------------------------------- proposal


class PackageChoice(BaseModel):
    footprint: Literal["ipc", "manufacturer", "existing"] = "ipc"
    existing: str | None = None  # footprint name from the registry (footprint="existing")
    density: Literal["M", "N", "L"] | None = None  # None = house style
    name: str | None = None  # override of the generated footprint name


class SymbolChoice(BaseModel):
    mode: Literal["auto", "standard", "ic", "existing"] = "auto"
    existing: str | None = None  # symbol name from the registry (mode="existing")
    parts: int | Literal["auto"] | None = None  # IC symbols: None = parts as in the pin table / auto for big ICs
    name: str | None = None  # override of the symbol name (IC symbols)


class ProposalChoices(BaseModel):
    """User decisions for :func:`partforge.datasheet.proposal.build_proposal` (all optional)."""

    device: str | None = None  # base part of a multi-device datasheet (default: first device)
    category: str | None = None  # category table (default: Claude's guess)
    variants: list[str] | None = None  # MPNs to create (default: all variants of the device)
    values: dict[str, str] = Field(default_factory=dict)  # column overrides for all variants
    variant_values: dict[str, dict[str, str]] = Field(default_factory=dict)  # MPN -> column overrides
    packages: dict[str, PackageChoice] = Field(default_factory=dict)  # package code -> footprint choice
    symbol: SymbolChoice = Field(default_factory=SymbolChoice)
    symbols: dict[str, SymbolChoice] = Field(default_factory=dict)  # package code -> symbol choice
    mode: Literal["skip", "update"] = "skip"  # existing part numbers: keep (skip) or update
    overwrite_existing: bool = False  # re-write symbols/footprints that already exist in the registry
    link: Literal["auto", "url", "file"] = "auto"  # datasheet link: manufacturer URL if known, else the PDF
    # The problems of PartProposal.blockers the user confirmed: the blocker texts exactly as the proposal listed them
    # (whitespace does not matter). ``True`` = every blocker (deprecated, kept for older clients).
    accept_issues: bool | list[str] = False
    # Registered symbols that may get the new pin-out (all parts using them change): ``True`` = every symbol of the
    # proposal, a list = these symbol names (the generated name, i.e. SymbolProposal.taken_name of a renamed symbol).
    # Any other symbol whose name is registered with another pin-out gets a free name instead.
    allow_pin_changes: bool | list[str] = False
    # Commit only: PartProposal.fingerprint of the proposal the user reviewed – the commit refuses (nothing written)
    # when the rebuilt proposal differs. Ignored by the proposal itself.
    expected_fingerprint: str | None = None

    def accepts(self, blocker: str) -> bool:
        """Whether the user confirmed this blocker text."""
        if self.accept_issues is True:
            return True
        if not self.accept_issues:
            return False
        wanted = _norm(blocker)
        return any(_norm(text) == wanted for text in self.accept_issues)

    def allows_pin_change(self, symbol: str | None) -> bool:
        """Whether the registered symbol ``symbol`` may get a new pin-out."""
        if self.allow_pin_changes is True:
            return True
        if not self.allow_pin_changes or not symbol:
            return False
        wanted = symbol.strip().casefold()
        return any(str(name).strip().casefold() == wanted for name in self.allow_pin_changes)


def _norm(text: str) -> str:
    return " ".join(str(text).split())


class FootprintAlternative(BaseModel):
    mode: Literal["ipc", "manufacturer"]
    name: str
    svg: str | None = None
    warnings: list[str] = Field(default_factory=list)
    valid: bool = True


class FootprintProposal(BaseModel):
    package: str  # package code
    package_label: str = ""
    family: str | None = None
    mode: Literal["ipc", "manufacturer", "existing"] = "ipc"
    name: str | None = None
    ipc_name: str | None = None
    pad_count: int = 0
    exists: bool = False  # a footprint with this name is already registered
    status: str | None = None  # registry status of that footprint (ok, pending, error, missing)
    valid: bool = False  # can be written (no error-level check failed)
    spec: FootprintSpec | None = None
    svg: str | None = None
    request: dict[str, Any] | None = None  # FootprintRequest (JSON) for "edit in the generator"
    warnings: list[str] = Field(default_factory=list)
    alternatives: list[FootprintAlternative] = Field(default_factory=list)


class PinoutChange(BaseModel):
    """One pin that differs between the symbol registered under a name and the proposed symbol
    (:attr:`SymbolProposal.taken_changes`). Names in Altium overbar syntax (``C\\S\\``) – the UI draws the overbars
    itself. ``None`` on one side: the pin does not exist there (added or removed pin; for a registered symbol without
    geometry – e.g. from an external library – the registered side is unknown and stays ``None`` for every pin)."""

    pin: str  # pin designator
    old_name: str | None = None  # registered symbol
    new_name: str | None = None  # proposed symbol
    old_type: ElectricalType | None = None
    new_type: ElectricalType | None = None
    old_part: int | None = None  # part of a multi-part symbol (0 = every part)
    new_part: int | None = None


class BlockerTarget(BaseModel):
    """What one of :attr:`PartProposal.blockers` concerns, for highlighting in the preview without parsing its text:
    the package and the symbol pins without pad (``pins``) or the footprint pads without pin (``pads``)."""

    blocker: str  # the blocker text exactly as in PartProposal.blockers
    package: str | None = None  # PackageData.code (None = the device or the whole datasheet)
    pins: list[str] = Field(default_factory=list)  # symbol pin designators without pad in the footprint
    pads: list[str] = Field(default_factory=list)  # footprint pad designators without pin in the symbol


class SymbolProposal(BaseModel):
    package: str  # package code whose pin table built the symbol ("" = no pin table)
    packages: list[str] = Field(default_factory=list)  # all package codes that share this symbol
    source: Literal["standard", "ic", "existing"] = "ic"
    name: str | None = None
    kind: str | None = None  # standard kind (opamp, optocoupler_4, ...) or "ic"
    exists: bool = False  # a symbol with this name (and this pin-out, see pin_changes) is already registered
    status: str | None = None  # registry status of that symbol (ok, pending, error, missing)
    valid: bool = False
    pin_count: int = 0
    part_count: int = 1
    spec: SymbolSpec | None = None
    svg: str | None = None
    request: dict[str, Any] | None = None  # SymbolRequest (JSON)
    warnings: list[str] = Field(default_factory=list)
    # Differences to the registered symbol of the same name (German sentences, pin names readable without overbar
    # syntax); non-empty only when the user allowed the pin-out change (``ProposalChoices.allow_pin_changes``) – the
    # commit then rewrites it.
    pin_changes: list[str] = Field(default_factory=list)
    taken_name: str | None = None  # generated name that was occupied by a symbol with another pin-out
    # Pin-out differences between this symbol and the registered symbol of the generated name (``taken_name`` when it
    # was renamed, else ``name``), one entry per differing pin (added, removed, other name, type or part) – set
    # whenever that symbol exists with another pin-out (renamed, pin-out change allowed, or a typed name that is
    # taken); [] = no such conflict.
    taken_changes: list[PinoutChange] = Field(default_factory=list)
    usage: int = 0  # parts that use the registered symbol of that name (``taken_name`` or ``name``); 0 = none/new


class VariantProposal(BaseModel):
    mpn: str
    part_number: str | None = None
    package: str = ""
    footprint: str | None = None
    symbol: str | None = None
    status: Literal["new", "exists", "conflict"] = "new"  # exists: same part number or manufacturer part number
    existing_table: str | None = None
    values: dict[str, str] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)  # field -> German reason (the row cannot be saved)
    warnings: list[str] = Field(default_factory=list)


class CostSummary(BaseModel):
    usd: float = 0.0
    runs: int = 0
    budget_usd: float = 0.0


class PartProposal(BaseModel):
    datasheet_id: str
    device: str
    devices: list[str] = Field(default_factory=list)  # all devices of the datasheet (for the selection)
    manufacturer: str = ""
    category: str | None = None
    category_label: str | None = None
    variants: list[VariantProposal] = Field(default_factory=list)
    symbols: list[SymbolProposal] = Field(default_factory=list)
    footprints: list[FootprintProposal] = Field(default_factory=list)
    datasheet_link: str | None = None
    warnings: list[str] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    # Problems that stop "Bauteil anlegen" until the user confirms them (ProposalChoices.accept_issues):
    # error-level checks of the chosen device/packages and pins without pads / pads without pins.
    blockers: list[str] = Field(default_factory=list)
    # One entry per blocker (same order and text as ``blockers``): the package, symbol pins and footprint pads it
    # concerns (empty lists for checks of the whole device).
    blocker_targets: list[BlockerTarget] = Field(default_factory=list)
    unconfirmed_blockers: list[str] = Field(default_factory=list)  # blockers not (yet) in accept_issues
    ready: bool = False  # everything needed for "Bauteil anlegen" is valid (blockers confirmed)
    cost: CostSummary = Field(default_factory=CostSummary)
    # Stable hash (16 hex) of the choices (without accept_issues/expected_fingerprint), the blockers and the plan
    # (names, write decisions, rows): the commit compares it with ProposalChoices.expected_fingerprint.
    fingerprint: str = ""
