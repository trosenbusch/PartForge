"""Prompt texts of the datasheet import (English: the extraction quality was verified with English prompts).

``SYSTEM_PROMPT`` is byte-stable (part of the cached prefix together with the output schema) and shared by
both passes (identity/pins and package geometry); every variable part (category catalogue, package list,
issues to re-check) goes into the user turn **after** the cached document block.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..db.models import CategoryDef, FieldDef

__all__ = [
    "SYSTEM_PROMPT",
    "TEST_PROMPT",
    "TRIAGE_SYSTEM",
    "category_catalogue",
    "geometry_instruction",
    "identity_instruction",
    "triage_instruction",
    "verification_instruction",
]

SYSTEM_PROMPT = """\
You extract component data from electronic-component datasheets for an Altium Designer database library \
(PartForge). The output is used to generate database records, schematic symbols and IPC-7351B footprints \
automatically, so precision matters more than completeness.

Rules:
- Use only information visible in the supplied pages (text, tables, drawings). Never fill gaps from general \
knowledge of similar parts; use -1 for numbers, "" for strings and [] for lists instead, and add a warning.
- A datasheet may describe several devices (for example a serializer and a deserializer, or single and dual \
versions): one entry in devices per distinct device, each with its own orderable part numbers and pin tables.
- Orderable part numbers: list every complete orderable part number exactly as printed (including packing \
suffixes such as /2K5, #TRPBF, -REEL7, T-I/SN). Do not invent combinations that are not printed.
- Pin tables are per package: pin numbers usually differ between packages. List every pin of every package, \
including NC pins and the exposed/thermal pad. Use the short pin names of the pinout drawing or table.
- Active-low signals (overbar, trailing #, leading / or n in the drawing): set active_low and write the name in \
Altium overbar syntax with a backslash after each overlined character, e.g. C\\S\\ or R\\E\\S\\E\\T\\.
- Pin electrical types follow Altium: supply, ground and exposed/thermal pads -> Power; signal inputs -> Input; \
outputs -> Output; bidirectional -> IO; open-drain/open-collector outputs -> OpenCollector; NC and pins of \
passive parts -> Passive (set no_connect for NC). For multi-channel devices give each channel its own part \
number (channel A = 1, B = 2 ...) and shared supply pins part 0.
- Dimensions: report millimetres. If a drawing shows "inch (mm)" or "mm [inch]" pairs, use the millimetre values. \
Map stacked values to max (upper) and min (lower) as drawn; put nominal, typical and basic (BSC) values into nom. \
Angles use unit "deg". Keep the dimension letters of the drawing and describe what each one measures.
- Exposed pads: set exposed_pad and give the exposed pad dimensions as their own dimensions (usually D2/E2).
- Land patterns: take pad size, pitch and row spacing only from a recommended land pattern / example board \
layout drawing. State in row_spacing_reference which features the row-spacing dimension connects (pad centre \
lines, inner pad edges, outer pad edges, or the centre of one pad to the centre of the component, which is half \
the centre distance as in some passive-component tables). Do not compute a land pattern yourself.
- Page numbers you report are 1-based page numbers of the attached PDF.
- Record every ambiguity or conflict (for example between the ordering table and the package addendum) in \
warnings.
"""

TRIAGE_SYSTEM = (
    "You classify the pages of an electronic-component datasheet. Pages without a text layer or with "
    "glyph-encoded text near the end of a datasheet are usually package drawings or land patterns."
)

TEST_PROMPT = "Reply with exactly: OK"

_MAX_OPTIONS = 14
NL = "\n"


def _field_line(field: FieldDef) -> str:
    kind = field.kind
    parts: list[str] = []
    if kind == "enum" and field.options:
        options = " | ".join(field.options[:_MAX_OPTIONS])
        parts.append(f"one of: {options}")
    elif kind in ("quantity", "range"):
        unit = field.unit or ""
        parts.append(f"{'range' if kind == 'range' else 'value'}{f' in {unit}' if unit else ''}")
    elif kind == "int":
        parts.append("integer")
    elif kind == "bool":
        parts.append("Ja/Nein")
    hint = f" ({'; '.join(parts)})" if parts else ""
    return f"{field.column}{hint}"


def _user_fields(category: CategoryDef) -> list[FieldDef]:
    """Fields Claude should fill: category-specific, non-system (common fields are filled by PartForge)."""
    return [f for f in category.fields if not f.system and not f.common]


def category_catalogue(categories: Iterable[CategoryDef]) -> str:
    """Category tables of the open library with the fields Claude may fill."""
    lines = []
    for cat in categories:
        fields = "; ".join(_field_line(f) for f in _user_fields(cat))
        lines.append(f"- {cat.table} ({cat.label}): {fields or 'no specific fields'}")
    return NL.join(lines)


def _subset_text(page_count: int, total_pages: int) -> str:
    if page_count < total_pages:
        return f"The attached PDF contains {page_count} selected pages of a {total_pages}-page datasheet."
    return f"The attached PDF is the complete {total_pages}-page datasheet."


def identity_instruction(categories: Sequence[CategoryDef], *, page_count: int, total_pages: int) -> str:
    """User text of the identity pass (after the cached document block)."""
    return NL.join([
        _subset_text(page_count, total_pages),
        "",
        "Extract the part record: manufacturer and document, every device with its orderable part numbers, its "
        "field values and one complete pin table per package, and the list of packages (code, name, pin count "
        "without exposed pad, exposed pad yes/no). Package dimensions are extracted in a separate step.",
        "If the pages describe no device at all (for example a separate package outline or land-pattern document), "
        "return an empty devices list and only the packages – never a placeholder device.",
        "",
        "For each device choose the best matching category table of this library and give values for its fields "
        "(use the exact field name as column; for fields with options use one of the listed options exactly; skip "
        "fields the pages do not state). Also give 'Operating Temperature' if stated.",
        "Category tables:",
        category_catalogue(categories),
    ])


def geometry_instruction(packages: Sequence[tuple[str, str, int]], *, page_count: int, total_pages: int) -> str:
    """User text of the geometry pass; ``packages`` = (code, name, pin count) found by the identity pass."""
    lines = [_subset_text(page_count, total_pages), ""]
    if packages:
        lines.append("Report the outline dimensions and the recommended land pattern for exactly these packages, "
                     "using these package codes:")
        lines += [f"- {code}: {name}" + (f", {pins} pins" if pins > 0 else "") for code, name, pins in packages]
        lines.append("For family drawings with a table of pin-count variants use the row of the given pin count. If a "
                     "package is not drawn in the attached pages, list it with empty dimensions and a land pattern "
                     "with present=false.")
    else:
        lines.append("Report the outline dimensions and the recommended land pattern of every package drawn in "
                     "these pages.")
    return NL.join(lines)


def verification_instruction(issues: Sequence[str], images: Sequence[int]) -> str:
    """Follow-up turn with high-resolution renders (``images`` = attached-PDF pages of the renders)."""
    pages = ", ".join(str(p) for p in images)
    listed = [f"- {text}" for text in issues] or ["- (no specific problems found)"]
    return NL.join([
        f"The images above are high-resolution renders of attached-PDF pages {pages}. Automatic checks of your "
        "answer found these problems:",
        *listed,
        "",
        "Verify your answer against the renders and correct it (pin tables, dimensions, land-pattern values). Return "
        "the complete corrected answer (same schema, page numbers of the attached PDF) and list each correction in "
        "warnings.",
    ])


def triage_instruction(digest: str) -> str:
    return NL.join([
        "Below is the start of each page's text layer of a component datasheet. Classify every page with the "
        "categories it contains (identity = title/features/description, pinout = pin drawing or pin table, "
        "ordering = orderable part numbers or part-number system, package_outline = mechanical drawing with "
        "dimensions, land_pattern = recommended PCB footprint, electrical = specification tables, irrelevant = "
        "everything else).",
        "",
        digest,
    ])
