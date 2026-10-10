"""Shared data models of the database layer (contract between modules).

Owned by the db-core module; other modules import these models but must not
change them without updating docs/entwicklung/ARCHITEKTUR.md.

Additions after the initial contract are backward compatible (new optional fields,
new models only).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..geometry.model import FootprintSpec, SymbolSpec
from .templates import FieldKind


class FieldDef(BaseModel):
    """A column of a category table (== Altium parameter) plus PartForge metadata."""

    column: str
    label: str
    kind: FieldKind = "text"
    unit: str | None = None
    options: list[str] = Field(default_factory=list)
    required: bool = False
    show_on_schematic: bool = False
    add_to_design: bool = True
    system: bool = False
    common: bool = False  # part of COMMON_FIELDS (present in every category)
    grid_width: int | None = None
    help: str | None = None
    sort_order: int = 0
    # Soft length limit in characters (columns are TEXT – Altium truncates VARCHAR(n), VERIFIED):
    # None = default (255, Description 1000, Notes 4000, ComponentLink1URL / url fields 2000),
    # 0 = no limit. Longer values are stored but produce a warning.
    length: int | None = None
    # Protected fields (Part Number, Altium link fields, bookkeeping) cannot be removed or renamed.
    protected: bool = False


class CategoryDef(BaseModel):
    table: str
    label: str
    prefix: str = "U"
    icon: str = "box"
    color: str = "#94A3B8"
    default_symbol: str | None = None
    value_field: str | None = None
    description_template: str = "{Manufacturer Part Number}"
    comment_template: str = "{Value}"
    sort_order: int = 0
    altium_enabled: bool = True
    fields: list[FieldDef] = Field(default_factory=list)  # COMMON_FIELDS first, then category fields
    part_count: int | None = None  # filled by list_categories()
    builtin: bool = False  # created from a built-in template (partforge.db.templates)

    def field(self, column: str) -> FieldDef | None:
        """The field with this column name (case-insensitive) or None."""
        wanted = column.casefold()
        return next((f for f in self.fields if f.column.casefold() == wanted), None)

    @property
    def columns(self) -> list[str]:
        return [f.column for f in self.fields]


class UpsertResult(BaseModel):
    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    errors: dict[str, str] = Field(default_factory=dict)  # part number -> message
    warnings: dict[str, list[str]] = Field(default_factory=dict)  # part number -> soft validation warnings
    unchanged: list[str] = Field(default_factory=list)  # mode="update": existing rows without differences


#: ``altium`` = edited and saved in Altium Designer ("In Altium bearbeiten", altium/editing.py): the library file
#: holds the authoritative version, the spec is its read-back.
RecordSource = Literal["generated", "datasheet", "imported", "external", "altium"]
RecordStatus = Literal["ok", "pending", "missing", "error"]


class SymbolRecord(BaseModel):
    name: str  # == Library Ref
    library: str  # workspace-relative path of the .SchLib (backslashes)
    source: RecordSource = "generated"
    spec: SymbolSpec | None = None
    pin_count: int = 0
    part_count: int = 1
    kind: str | None = None  # generator kind (resistor, capacitor, ic, ...)
    status: RecordStatus = "pending"
    status_message: str | None = None
    updated: str | None = None
    usage: int = 0  # number of parts referencing it (filled on list)
    # sha256 (hex) of the stored spec text – set whenever the record is read with its spec (None: no geometry
    # or a light list without specs; registry.content_hashes() gives it for lists)
    content_hash: str | None = None


class FootprintRecord(BaseModel):
    name: str  # == Footprint Ref
    library: str  # workspace-relative path of the .PcbLib
    source: RecordSource = "generated"
    spec: FootprintSpec | None = None
    family: str | None = None
    ipc_name: str | None = None
    pad_count: int = 0
    height: float | None = None
    step_file: str | None = None  # workspace-relative
    status: RecordStatus = "pending"
    status_message: str | None = None
    updated: str | None = None
    usage: int = 0
    content_hash: str | None = None  # sha256 (hex) of the stored spec text, see SymbolRecord.content_hash


class DatasheetRecord(BaseModel):
    id: str  # sha256[:16] of the PDF
    file: str  # workspace-relative path
    original_name: str
    title: str | None = None
    manufacturer: str | None = None
    mpns: list[str] = Field(default_factory=list)
    page_count: int = 0
    text_pages: list[int] = Field(default_factory=list)  # 1-based pages with a usable text layer
    extraction: dict[str, Any] | None = None
    created: str | None = None


AuditAction = Literal["create", "update", "delete", "bulk_update", "import", "schema", "restore"]


class AuditEntry(BaseModel):
    id: int
    ts: str
    author: str | None
    action: AuditAction
    table: str | None
    part_number: str | None
    changes: dict[str, Any] = Field(default_factory=dict)  # column -> [old, new]


# --------------------------------------------------------------------------- queries

FilterOp = Literal[
    "eq", "ne", "lt", "le", "gt", "ge", "contains", "startswith", "in", "empty", "notempty",
    "before", "after", "between",
]


class PartFilter(BaseModel):
    """One column condition of :func:`partforge.db.parts.query_parts`.

    ``lt/le/gt/ge/eq/ne/in`` compare parsed engineering values on quantity/int fields
    ("10k" == "10kΩ") and dates on date fields (``PF Created``, ``PF Modified``: by day,
    ``eq 2026-10-07`` = any time that day); text comparisons are case-insensitive.
    ``before``/``after`` (date fields) take one date, ``between`` takes ``[from, to]`` (both
    inclusive, one side may be empty) on date and quantity/int fields.
    """

    column: str
    op: FilterOp = "eq"
    value: Any = None


class SortSpec(BaseModel):
    column: str
    desc: bool = False


class SavedView(BaseModel):
    """A stored grid view (search, filters, sort and visible columns) – pf_saved_views."""

    id: int | None = None
    name: str
    table: str | None = None  # None = valid for every category
    search: str | None = None
    filters: list[PartFilter] = Field(default_factory=list)
    sort: list[SortSpec] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)  # visible columns in order (empty = default)
    created: str | None = None
    modified: str | None = None
    author: str | None = None


class SearchHit(BaseModel):
    """Result of the global quick search (command palette)."""

    table: str
    label: str
    color: str | None = None
    icon: str | None = None
    part_number: str
    manufacturer: str | None = None
    mpn: str | None = None
    description: str | None = None
    value: str | None = None
    score: float = 0.0


# --------------------------------------------------------------------------- health & backups

IssueSeverity = Literal["error", "warning", "info"]


class HealthIssue(BaseModel):
    severity: IssueSeverity
    check: str  # machine key of the check, e.g. "required", "duplicate_mpn"
    table: str | None = None
    part_number: str | None = None
    column: str | None = None
    message: str
    fix_hint: str | None = None


class BackupInfo(BaseModel):
    name: str  # file name inside Backups/
    path: str  # absolute path
    rel_path: str  # workspace-relative path
    size: int
    created: str  # ISO timestamp (from the file name, fallback mtime)
    reason: str
