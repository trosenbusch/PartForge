"""Parts = rows of the category tables (Altium components).

Contract (ARCHITEKTUR.md §4)::

    query_parts(table, *, search=None, filters=None, sort=None, offset=0, limit=200) -> (rows, total)
    get_part(table, pn) -> dict | None; find_part(pn) -> (table, row) | None
    existing_part_numbers(pns) -> set[str]
    find_by_mpn(mpns) -> {mpn_key: [(table, part number, row)]}; mpn_key(mpn) -> str
    create_part(table, values, *, author=None) -> dict; update_part(table, pn, values, *, author=None) -> dict
    delete_parts(table, pns, *, author=None) -> int; bulk_update(table, pns, values, *, author=None) -> int
    restore_updates(table, audit_ids, *, author=None) -> dict   # undo of bulk_update/regenerate_texts
    upsert_parts(table, rows, *, mode="skip"|"update"|"error", author=None, ctx=None) -> UpsertResult
    plan_upsert(table, rows, *, mode, allow_incomplete=False, strict=False) -> list[RowPlan]   # dry run
    duplicate_part(table, pn, new_pn) -> dict; history(table, pn) -> list[dict]
    restore_parts(table, pns, *, author=None) -> dict      # deleted parts back from pf_audit
    matching_part_numbers(table, *, search=None, filters=None) -> list[str]   # selection by filter
    search_all(q, limit=20) -> list[dict]; stats() -> dict; render_templates(table, values) -> dict
    render_template_text(table, template, values) -> dict  # any template (settings preview)

Rules applied on every write:

* values are normalised per field kind (``10k`` -> ``10kΩ``, ``1`` -> ``±1%``), see :mod:`.values`;
  enum/quantity problems and over-long values are soft warnings (columns are TEXT),
  missing required fields are errors;
* ``Part Number`` is unique across **all** category tables, compared by :func:`pn_key` (case-insensitive
  for all of Unicode, NFKC, invisible format characters ignored – ``GRM188\u00adR71`` = ``grm188r71``,
  ``UNIQ-STRASSE`` = ``uniq-straße``); part numbers and MPNs are stored in NFC without format characters
  (:func:`partforge.domain.text.identity_text`);
  empty -> Manufacturer Part Number (scheme ``mpn``) or a generated internal number;
* fields that do not apply to the part are not required: a 0-Ω jumper has no tolerance, TCR, power
  rating or working voltage (:func:`partforge.db.values.not_applicable`) – by hand, imported or from a series;
* ``Value``/``Comment``/``Description`` are rendered from the category templates when
  empty – and re-rendered on updates as long as they still equal the generated text;
* ``Library Path``/``Footprint Path`` are filled from the registry when empty or when the
  reference changes; a registry path of the old reference is cleared when the new
  reference is unknown (Altium would otherwise search the wrong file);
* ``PF Created``/``PF Modified``/``PF Author`` bookkeeping and an audit entry per part;
* mass changes of more than :data:`AUTO_BACKUP_DELETE_THRESHOLD` parts (delete, bulk update, regenerated
  texts) take an automatic backup first; bulk updates and regenerated texts hand back the ids of their
  audit entries – :func:`restore_updates` sets the old values back (undo, with a conflict check);
* after every committed write :data:`partforge.events.PARTS_CHANGED` ``(table, inserted)``
  is emitted (``inserted`` = new part numbers exist), e.g. so a running Altium re-reads the DbLib.

Text search and text filters are case-insensitive for all of Unicode (``Ü``, ``Ω``):
on SQLite through the SQL function ``pf_fold`` (Python ``str.casefold``), elsewhere
through ``lower()``. The search box covers the columns people search by (:func:`search_columns`: not
the library paths, URLs, dates and ``PF Author``); a number without unit (``10k``, ``4k7``)
also matches the engineering value of the category's value field, a number with unit (``50V``,
``100nF``, ``1%``) the fields of that unit. One query returns the page and the number of hits. On SQLite
the search runs over an in-memory index per category (folded text of the search columns and the
engineering values, :class:`_SearchIndex`), built on the first search and rebuilt after any change of the
database (:func:`partforge.db.core.data_version`, the database file and its WAL).

Date fields (``PF Created``, ``PF Modified`` and every field of kind ``date``) compare as dates:
``before``/``after`` a day (or minute/second, if given) and ``between`` two of them (both inclusive,
one side may be open); ``eq``/``ne``/``in``/``lt``/``le``/``gt``/``ge`` with a date value compare by
day, too (``eq 2026-10-07`` = any time that day). Values: ``2026-10-07``, ``07.10.2026``,
``2026-10-07 21:30`` … ``between`` on quantity/int fields compares engineering values (inclusive).
"""
from __future__ import annotations

import datetime as _dt
import logging
import math
import os
import re
import threading
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import reduce
from typing import Any, Literal

from sqlalchemy import (
    Connection,
    ColumnElement,
    Table,
    and_,
    bindparam,
    case,
    delete,
    false,
    func,
    insert,
    literal,
    not_,
    or_,
    select,
    update,
)

from .. import events
from ..domain.text import identity_key, strip_format_chars
from ..domain.units import parse_quantity
from ..jobs import JobContext
from ..workspace import DEFAULT_PN_FORMAT
from . import audit, categories, core, registry
from .errors import DbError, DuplicatePartError, FieldNotFound, PartNotFound, PartValidationError
from .meta import get_meta, set_meta
from .models import CategoryDef, FieldDef, PartFilter, SortSpec, UpsertResult
from .values import (
    PART_NUMBER,
    canonical_unit,
    length_warning,
    normalize_cell,
    not_applicable,
    numeric_value,
    parse_date,
    parse_field_quantity,
    render_template,
    template_columns,
    to_text,
    units_compatible,
)

log = logging.getLogger(__name__)

__all__ = [
    "bulk_update",
    "create_part",
    "delete_parts",
    "distinct_values",
    "duplicate_part",
    "existing_part_numbers",
    "find_by_mpn",
    "find_part",
    "get_part",
    "history",
    "matching_part_numbers",
    "mpn_key",
    "plan_upsert",
    "pn_key",
    "query_parts",
    "regenerate_texts",
    "render_template_text",
    "render_templates",
    "restore_parts",
    "restore_updates",
    "search_all",
    "search_tokens",
    "set_library_path",
    "smart_fill",
    "stats",
    "update_part",
    "upsert_parts",
    "validate_part",
]

BOOKKEEPING = ("PF Created", "PF Modified", "PF Author")
AUTO_COLUMNS = ("Value", "Comment", "Description")  # render order (Comment may use Value)
LINKS = (
    ("Library Ref", "Library Path", "symbol"),
    ("Footprint Ref", "Footprint Path", "footprint"),
    ("Footprint Ref 2", "Footprint Path 2", "footprint"),
)
DEFAULT_STATUS = "Entwurf"
LINK_DESCRIPTION = "Datenblatt"
DATASHEET_COLUMN = "ComponentLink1URL"
AUTO_BACKUP_DELETE_THRESHOLD = 20
_CHUNK = 500
_MAX_WARNINGS = 1000
_NUMERIC_KINDS = ("quantity", "int")

_TOTAL_LABEL = "pf__total"  # window column of query_parts (number of hits)
_TOKEN_RE = re.compile(r'"([^"]+)"|(\S+)')
# ignored when comparing MPNs: whitespace, "-" and the Unicode dashes/minus signs of PDFs
_MPN_IGNORED = re.compile(r"[\s\-‐-―−﹘﹣－]+")


def pn_key(pn: str) -> str:
    """Comparison key of a part number: trimmed, NFKC, without invisible format characters, case-folded
    (:func:`partforge.domain.text.identity_key`; for ASCII the same as SQLite ``NOCASE``)."""
    return identity_key(str(pn))


def search_tokens(search: str | None) -> list[str]:
    """Split a search string into tokens; ``"quoted phrases"`` stay together."""
    if not search:
        return []
    return [(a or b).strip() for a, b in _TOKEN_RE.findall(search) if (a or b).strip()]


def _chunks(items: Sequence[Any], size: int = _CHUNK) -> Iterator[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _parts_changed(table: str | None, *, inserted: bool) -> None:
    """Announce committed row changes (:data:`events.PARTS_CHANGED`); listeners never raise."""
    events.emit(events.PARTS_CHANGED, table, inserted)


def _clean_row(mapping: Mapping[Any, Any]) -> dict[str, str | None]:
    return {str(k): (v if v is None or isinstance(v, str) else str(v)) for k, v in mapping.items()}


# --------------------------------------------------------------------------- per-category context


class _Ctx:
    """Everything an operation needs about one category (built once per call)."""

    def __init__(self, cat: CategoryDef) -> None:
        self.cat = cat
        self.table: Table = categories.table_for(cat)
        self.fields: dict[str, FieldDef] = {f.column: f for f in cat.fields}
        self.lookup: dict[str, FieldDef] = {f.column.casefold(): f for f in cat.fields}
        ws = core.current_workspace()
        self.ws_root = ws.root
        self.scheme = ws.settings.part_number_scheme
        self.pn_format = ws.settings.internal_pn_format or DEFAULT_PN_FORMAT
        self.templates: dict[str, str] = {
            "Value": f"{{{cat.value_field}}}" if cat.value_field else "",
            "Comment": cat.comment_template or "",
            "Description": cat.description_template or "",
        }
        self._libraries: dict[str, dict[str, str]] = {}
        self.pn_keys: set[str] | None = None  # all part number keys (loaded for internal numbering)

    def field(self, column: str) -> FieldDef:
        f = self.lookup.get((column or "").strip().casefold())
        if f is None:
            raise FieldNotFound(self.cat.table, column)
        return f

    def library_for(self, kind: str, name: str) -> str | None:
        if kind not in self._libraries:
            self._libraries[kind] = registry.symbol_library_map() if kind == "symbol" else registry.footprint_library_map()
        return self._libraries[kind].get(name.casefold())

    def render(self, column: str, row: Mapping[str, Any]) -> str:
        return render_template(self.templates.get(column, ""), row, self.fields)

    def label(self, column: str) -> str:
        """German label of a column (the column name for unknown columns)."""
        f = self.fields.get(column) or self.lookup.get(column.casefold())
        return f.label if f is not None else column

    @property
    def numeric_fields(self) -> list[FieldDef]:
        return [f for f in self.cat.fields if f.kind in _NUMERIC_KINDS]


@dataclass
class _Prepared:
    row: dict[str, str | None]
    provided: dict[str, str | None]
    warnings: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)  # labels of empty required fields (allow_incomplete)


def _prepare(
    c: _Ctx,
    incoming: Mapping[str, Any],
    *,
    existing: Mapping[str, Any] | None,
    author: str,
    now: str,
    allow_incomplete: bool = False,
    pn_factory: Callable[[], str] | None = None,
    strict: bool = False,
    thousands: bool | None = None,
) -> _Prepared:
    """Normalise input, apply defaults/templates/bookkeeping and validate (no DB writes).

    ``strict``: values that cannot be read for their field (no number, wrong unit, no date, ambiguous
    comma …, :attr:`CellResult.unreadable`) are errors instead of warnings. ``thousands``: number format
    of the source for ambiguous comma groups (:func:`partforge.db.values.normalize_cell`)."""
    warnings: list[str] = []
    errors: dict[str, str] = {}
    missing: list[str] = []
    provided: dict[str, str | None] = {}
    for key, raw in incoming.items():
        name = str(key).strip()
        f = c.lookup.get(name.casefold())
        if f is None:
            if to_text(raw) is not None:
                errors[name] = "Dieses Feld gibt es in der Kategorie nicht."
            continue
        if f.column in BOOKKEEPING:
            continue
        res = normalize_cell(f, raw, ws_root=c.ws_root, thousands=thousands)
        if res.error:
            errors[f.column] = res.error
        if res.warning:
            if strict and res.unreadable and f.column not in errors:
                errors[f.column] = res.warning
            else:
                warnings.append(f"{f.label}: {res.warning}")
        provided[f.column] = res.value

    row: dict[str, str | None] = {col: (existing.get(col) if existing else None) for col in c.fields}
    row.update(provided)

    # Part number default on creation: MPN (scheme "mpn") or generated internal number.
    # (Emptying the part number of an existing part is a validation error, see below.)
    if existing is None and not row.get(PART_NUMBER) and PART_NUMBER not in errors:
        if c.scheme == "internal":
            if pn_factory is not None:
                row[PART_NUMBER] = pn_factory()
            # without a factory (dry run, validate_part) the number is assigned when saving
        elif row.get("Manufacturer Part Number"):
            candidate = normalize_cell(c.fields[PART_NUMBER], row["Manufacturer Part Number"])
            if candidate.error:
                errors[PART_NUMBER] = candidate.error
            else:
                row[PART_NUMBER] = candidate.value
    # Scheme "mpn": the part number *is* the manufacturer part number
    if (existing is None and c.scheme == "mpn" and "Manufacturer Part Number" in c.fields
            and not row.get("Manufacturer Part Number") and row.get(PART_NUMBER)):
        row["Manufacturer Part Number"] = row[PART_NUMBER]

    # Library/footprint paths from the registry
    for ref_col, path_col, kind in LINKS:
        if ref_col not in c.fields or path_col not in c.fields or provided.get(path_col):
            continue
        ref = row.get(ref_col)
        ref_changed = existing is None or (ref_col in provided and (existing.get(ref_col) or None) != ref)
        if not ref_changed and row.get(path_col):
            continue
        library = c.library_for(kind, ref) if ref else None
        if library:
            row[path_col] = library
        elif existing is not None and ref_changed and row.get(path_col):
            # The stored path was the registry library of the *old* reference: it does not hold
            # the new (unregistered) one. A user-managed path (external library) is kept.
            old_ref = existing.get(ref_col)
            old_library = c.library_for(kind, str(old_ref)) if old_ref else None
            if old_library and old_library.casefold() == str(row[path_col]).casefold():
                row[path_col] = None

    # Value / Comment / Description from the category templates
    for col in AUTO_COLUMNS:
        if col not in c.fields or not c.templates.get(col) or provided.get(col):
            continue
        if existing is None:
            if not row.get(col):
                row[col] = c.render(col, row) or None
            continue
        old_value = existing.get(col)
        if col in provided or not old_value or old_value == c.render(col, existing):
            row[col] = c.render(col, row) or None

    if "ComponentLink1Description" in c.fields and row.get(DATASHEET_COLUMN) and not row.get("ComponentLink1Description"):
        row["ComponentLink1Description"] = LINK_DESCRIPTION
    if existing is None and "PF Status" in c.fields and not row.get("PF Status"):
        row["PF Status"] = DEFAULT_STATUS

    # Required fields (on updates only those the caller touched). Fields that do not apply to the part
    # (0-Ω jumper: tolerance, TCR, power rating, working voltage – values.not_applicable) are never
    # required; an update that ends the exemption (jumper -> resistor) touches them.
    exempt = not_applicable(c.cat, row)
    was_exempt = not_applicable(c.cat, existing) if existing is not None else frozenset()
    for f in c.cat.fields:
        if not f.required or f.column in BOOKKEEPING or row.get(f.column) or f.column in errors:
            continue
        if f.column in exempt:
            continue
        if existing is not None and f.column not in provided and f.column not in was_exempt:
            continue
        if f.column == PART_NUMBER:
            errors[PART_NUMBER] = "Die Teilenummer fehlt (oder eine Hersteller-Teilenummer angeben)."
        elif allow_incomplete:
            warnings.append(f"{f.label}: Pflichtfeld ist leer.")
            missing.append(f.label)
        else:
            errors[f.column] = "Pflichtfeld ist leer."

    # Soft length limits of generated values (provided values were checked by normalize_cell;
    # the columns are TEXT, so nothing is truncated – long texts are only reported)
    for col, value in row.items():
        if not value or col in errors or col in provided or (existing is not None and value == existing.get(col)):
            continue
        too_long = length_warning(c.fields[col], value)
        if too_long:
            warnings.append(f"{c.fields[col].label}: {too_long}")

    if "PF Created" in c.fields:
        row["PF Created"] = (existing.get("PF Created") if existing else None) or now
    if "PF Modified" in c.fields:
        row["PF Modified"] = now
    if "PF Author" in c.fields:
        row["PF Author"] = author
    return _Prepared(row=row, provided=provided, warnings=warnings, errors=errors, missing=missing)


# --------------------------------------------------------------------------- lookups


def _ci_in(conn: Connection, column: Any, keys: Sequence[str]) -> ColumnElement[bool]:
    if conn.dialect.name == "sqlite":
        return column.collate("NOCASE").in_(list(keys))
    return func.lower(column).in_([k.lower() for k in keys])


def _ci_eq(conn: Connection, column: Any, value: str) -> ColumnElement[bool]:
    if conn.dialect.name == "sqlite":
        return column.collate("NOCASE") == value
    return func.lower(column) == value.lower()


def _unusual_spelling(conn: Connection, column: Any) -> ColumnElement[bool]:
    """Stored values with characters beyond printable ASCII or blanks at the edges – the only ones whose
    :func:`pn_key` can differ from their SQLite ``NOCASE`` spelling (non-ASCII case, NFD, format characters)."""
    edges = or_(column.like(" %"), column.like("% "))
    if conn.dialect.name == "sqlite":
        return or_(column.op("GLOB")("*[^ -~]*"), edges)
    if conn.dialect.name == "postgresql":
        return or_(column.op("~")("[^ -~]"), edges)
    return column.is_not(None)


def _stored_matches(conn: Connection, table: Table, keys: set[str]) -> list[str]:
    """Stored part numbers of ``table`` whose :func:`pn_key` is one of ``keys``: an indexed case-insensitive
    lookup of the ASCII keys plus one scan of the unusual spellings (:func:`_unusual_spelling`)."""
    column = table.c[PART_NUMBER]
    hits: list[str] = []
    ascii_keys = sorted(k for k in keys if k.isascii())
    for chunk in _chunks(ascii_keys):
        hits.extend(str(v) for (v,) in conn.execute(select(column).where(_ci_in(conn, column, chunk))))
    hits.extend(str(v) for (v,) in conn.execute(select(column).where(_unusual_spelling(conn, column))))
    return [v for v in dict.fromkeys(hits) if pn_key(v) in keys]


def _find_conflicts(
    conn: Connection,
    pns: Iterable[str],
    *,
    exclude: tuple[str, str] | None = None,
) -> dict[str, tuple[str, str]]:
    """``{pn_key: (table, stored part number)}`` for given part numbers that exist anywhere (compared by
    :func:`pn_key`: Unicode case, NFC/NFD and invisible characters never make a second part number)."""
    keys = {k for k in (pn_key(p) for p in pns if p and p.strip()) if k}
    found: dict[str, tuple[str, str]] = {}
    if not keys:
        return found
    for cat in categories.list_categories(with_counts=False):
        table = categories.table_for(cat)
        for stored in _stored_matches(conn, table, keys):
            if exclude and cat.table == exclude[0] and stored == exclude[1]:
                continue
            found.setdefault(pn_key(stored), (cat.table, stored))
    return found


def _fetch_row(conn: Connection, table: Table, pn: str) -> dict[str, str | None] | None:
    column = table.c[PART_NUMBER]
    row = conn.execute(select(table).where(column == pn)).mappings().first()
    if row is None and pn:
        row = conn.execute(select(table).where(_ci_eq(conn, column, pn.strip())).limit(1)).mappings().first()
    return _clean_row(row) if row is not None else None


def _fetch_rows(conn: Connection, table: Table, pns: Sequence[str]) -> dict[str, dict[str, str | None]]:
    """Rows by :func:`pn_key` (the same part number in any spelling – case, NFC/NFD, invisible characters)."""
    column = table.c[PART_NUMBER]
    keys = {k for k in (pn_key(p) for p in pns if p) if k}
    rows: dict[str, dict[str, str | None]] = {}
    stored = sorted(_stored_matches(conn, table, keys)) if keys else []
    for chunk in _chunks(stored):
        for row in conn.execute(select(table).where(column.in_(list(chunk)))).mappings():
            clean = _clean_row(row)
            rows.setdefault(pn_key(str(clean[PART_NUMBER])), clean)
    return rows


def get_part(table: str, pn: str) -> dict[str, str | None] | None:
    """One part (exact part number, else case-insensitive) or None."""
    cat = categories.get_category(table)
    with core.read() as conn:
        return _fetch_row(conn, categories.table_for(cat), pn)


def find_part(pn: str) -> tuple[str, dict[str, str | None]] | None:
    """``(table, row)`` of a part number in any category (exact match preferred)."""
    if not pn or not pn.strip():
        return None
    cats = categories.list_categories(with_counts=False)
    with core.read() as conn:
        for cat in cats:
            table = categories.table_for(cat)
            row = conn.execute(select(table).where(table.c[PART_NUMBER] == pn)).mappings().first()
            if row is not None:
                return cat.table, _clean_row(row)
        for cat in cats:
            table = categories.table_for(cat)
            row = conn.execute(select(table).where(_ci_eq(conn, table.c[PART_NUMBER], pn.strip())).limit(1)).mappings().first()
            if row is not None:
                return cat.table, _clean_row(row)
    return None


def existing_part_numbers(pns: Iterable[str]) -> set[str]:
    """The given part numbers that already exist in any category (case-insensitive)."""
    wanted = [p for p in pns if p and p.strip()]
    if not wanted:
        return set()
    with core.read() as conn:
        found = _find_conflicts(conn, wanted)
    return {p for p in wanted if pn_key(p) in found}


MpnHit = tuple[str, str, dict[str, str | None]]  # (table, stored part number, row)


def mpn_key(mpn: Any) -> str:
    """Comparison key of a manufacturer part number: Unicode-normalised (NFKC), without
    whitespace, dashes and invisible format characters (soft hyphen, zero-width space, BOM …),
    case-folded – ``"GRM188R71H104KA93D"``, ``"grm188r71h104ka93d "``, ``"GRM188\u00adR71H104KA93D"``
    and ``"MMSZ5231B-7-F"``/``"MMSZ5231B7F"`` compare equal. Empty input gives ``""``."""
    if mpn is None:
        return ""
    text = strip_format_chars(unicodedata.normalize("NFKC", str(mpn)))
    return _MPN_IGNORED.sub("", text).casefold()


def find_by_mpn(mpns: Iterable[str]) -> dict[str, list[MpnHit]]:
    """Existing parts of every category per manufacturer part number.

    Returns ``{mpn_key: [(table, part number, row), …]}`` for the keys that were found (look
    up with :func:`mpn_key`); hits in category order, then by part number. Compared with
    :func:`mpn_key` against ``Manufacturer Part Number`` – and against the part number for rows
    without one (scheme ``mpn``: the part number *is* the MPN). One scan of the key columns
    per category plus an indexed read of the hits, however many MPNs are asked for."""
    wanted = {key for key in (mpn_key(m) for m in mpns) if key}
    found: dict[str, list[MpnHit]] = {}
    if not wanted:
        return found
    cats = categories.list_categories(with_counts=False)
    with core.read() as conn:
        for cat in cats:
            table = categories.table_for(cat)
            pn_column = table.c[PART_NUMBER]
            mpn_field = cat.field("Manufacturer Part Number")
            columns = [pn_column] + ([table.c[mpn_field.column]] if mpn_field is not None else [])
            keys: dict[str, str] = {}  # stored part number -> matched key
            for row in conn.execute(select(*columns)):
                pn = row[0]
                mpn = row[1] if mpn_field is not None else None
                key = mpn_key(mpn if mpn is not None and str(mpn).strip() else pn)
                if key in wanted and pn is not None:
                    keys[str(pn)] = key
            if not keys:
                continue
            for chunk in _chunks(sorted(keys)):
                for raw in conn.execute(select(table).where(pn_column.in_(list(chunk)))).mappings():
                    clean = _clean_row(raw)
                    pn = str(clean[PART_NUMBER])
                    found.setdefault(keys[pn], []).append((cat.table, pn, clean))
    order = {cat.table: i for i, cat in enumerate(cats)}
    for hits in found.values():
        hits.sort(key=lambda hit: (order.get(hit[0], len(order)), hit[1].casefold(), hit[1]))
    return found


# --------------------------------------------------------------------------- internal part numbers


def _all_pn_keys(conn: Connection) -> set[str]:
    """Keys of every part number in every category table."""
    keys: set[str] = set()
    for cat in categories.list_categories(with_counts=False):
        table = categories.table_for(cat)
        keys.update(pn_key(str(value)) for (value,) in conn.execute(select(table.c[PART_NUMBER])))
    return keys


#: Generated numbers tried before :func:`_next_internal_pn` gives up (all taken – never an endless loop
#: inside the process-wide write transaction).
MAX_PN_TRIES = 10_000
_PN_SETTINGS_HINT = "Bitte das Format unter Einstellungen › Bibliothek › Teilenummern korrigieren."


def _next_internal_pn(conn: Connection, c: _Ctx) -> str:
    """Next free internal part number (counter in pf_meta, collisions skipped).

    The format is checked first (:func:`partforge.workspace.pn_format_problem`) and every candidate is
    normalised like a typed part number; after :data:`MAX_PN_TRIES` taken numbers a German
    :class:`DbError` explains it – the search never blocks the database."""
    from ..workspace import pn_format_problem

    fmt = c.pn_format or DEFAULT_PN_FORMAT
    problem = pn_format_problem(fmt)
    if problem is not None:
        raise DbError(f"Interne Teilenummer nicht erzeugt: {problem} {_PN_SETTINGS_HINT}")
    if c.pn_keys is None:
        c.pn_keys = _all_pn_keys(conn)
    prefix = c.cat.prefix or "P"
    key = f"pn_counter:{prefix}"
    raw = get_meta(key, conn=conn)
    counter = int(raw) if raw and raw.isdigit() else 0
    field = c.fields.get(PART_NUMBER) or FieldDef(column=PART_NUMBER, label="Teilenummer")
    for _ in range(MAX_PN_TRIES):
        counter += 1
        try:
            candidate = fmt.format(prefix=prefix, counter=counter, table=c.cat.table)
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise DbError(f"Interne Teilenummer nicht erzeugt: Das Format „{fmt}“ lässt sich nicht anwenden. "
                          f"{_PN_SETTINGS_HINT}") from exc
        res = normalize_cell(field, candidate)
        if res.error or res.value != candidate:  # e.g. the table name brings a character a part number cannot have
            raise DbError(f"Interne Teilenummer nicht erzeugt: „{candidate}“ ist keine gültige Teilenummer "
                          f"({res.error or 'Leerzeichen oder unsichtbare Zeichen'}). {_PN_SETTINGS_HINT}")
        if pn_key(candidate) not in c.pn_keys:
            break
    else:
        raise DbError(f"Interne Teilenummer nicht erzeugt: Die nächsten {MAX_PN_TRIES:,} Nummern im Format „{fmt}“ "
                      "sind alle vergeben.".replace(",", ".") + f" {_PN_SETTINGS_HINT}")
    c.pn_keys.add(pn_key(candidate))
    set_meta(key, str(counter), conn=conn)
    return candidate


# --------------------------------------------------------------------------- create / update / delete


def create_part(
    table: str,
    values: Mapping[str, Any],
    *,
    author: str | None = None,
    warnings: list[str] | None = None,
    allow_incomplete: bool = False,
) -> dict[str, str | None]:
    """Create a part. Raises :class:`PartValidationError` or :class:`DuplicatePartError`.

    Soft warnings (enum value not in list, unparsable quantity …) are appended to
    ``warnings`` if a list is passed.
    """
    cat = categories.get_category(table)
    c = _Ctx(cat)
    who = audit.resolve_author(author)
    now = audit.now_text()
    with core.connect() as conn:
        prepared = _prepare(c, values, existing=None, author=who, now=now, allow_incomplete=allow_incomplete,
                            pn_factory=lambda: _next_internal_pn(conn, c))
        if prepared.errors:
            raise PartValidationError(prepared.errors)
        pn = str(prepared.row[PART_NUMBER])
        conflict = _find_conflicts(conn, [pn]).get(pn_key(pn))
        if conflict:
            raise DuplicatePartError(pn, conflict[0], conflict[1])
        conn.execute(insert(c.table).values(prepared.row))
        audit.record(conn, "create", cat.table, pn, audit.diff(None, prepared.row), who)
    if warnings is not None:
        warnings.extend(prepared.warnings)
    log.debug("Bauteil %s in %s angelegt", pn, cat.table)
    _parts_changed(cat.table, inserted=True)
    return dict(prepared.row)


def update_part(
    table: str,
    pn: str,
    values: Mapping[str, Any],
    *,
    author: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, str | None]:
    """Change the given columns of a part (``{"Part Number": new}`` renames it).
    Raises :class:`KeyError` (PartNotFound), :class:`PartValidationError`, :class:`DuplicatePartError`."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    who = audit.resolve_author(author)
    now = audit.now_text()
    with core.connect() as conn:
        existing = _fetch_row(conn, c.table, pn)
        if existing is None:
            raise PartNotFound(cat.table, pn)
        prepared = _prepare(c, values, existing=existing, author=who, now=now)
        if prepared.errors:
            raise PartValidationError(prepared.errors)
        old_pn = str(existing[PART_NUMBER])
        new_pn = str(prepared.row[PART_NUMBER])
        if new_pn != old_pn:
            conflict = _find_conflicts(conn, [new_pn], exclude=(cat.table, old_pn)).get(pn_key(new_pn))
            if conflict:
                raise DuplicatePartError(new_pn, conflict[0], conflict[1])
        changes = audit.diff(existing, prepared.row)
        if changes:
            conn.execute(update(c.table).where(c.table.c[PART_NUMBER] == old_pn).values(prepared.row))
            audit.record(conn, "update", cat.table, new_pn, changes, who)
    if warnings is not None:
        warnings.extend(prepared.warnings)
    if changes:
        _parts_changed(cat.table, inserted=new_pn != old_pn)  # a renamed part is a new key for Altium
    return dict(prepared.row) if changes else existing


def delete_parts(
    table: str,
    pns: Iterable[str],
    *,
    author: str | None = None,
    backup: bool = True,
    deleted: list[str] | None = None,
) -> int:
    """Delete parts (automatic backup before deleting more than 20). Returns the number deleted;
    ``deleted`` (a list) receives their stored part numbers – the input of :func:`restore_parts`."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    wanted = list(dict.fromkeys(p for p in pns if p and str(p).strip()))
    if not wanted:
        return 0
    if backup and len(wanted) > AUTO_BACKUP_DELETE_THRESHOLD:
        from . import backup as _backup

        _backup.auto_backup(f"vor_loeschen_{len(wanted)}_bauteile")
    who = audit.resolve_author(author)
    with core.connect() as conn:
        rows = _fetch_rows(conn, c.table, wanted)
        stored = [str(r[PART_NUMBER]) for r in rows.values()]
        column = c.table.c[PART_NUMBER]
        for chunk in _chunks(stored):
            conn.execute(delete(c.table).where(column.in_(list(chunk))))
        audit.record_many(
            conn, [audit.entry_row("delete", cat.table, str(r[PART_NUMBER]), audit.diff(r, None, ignore=()), who) for r in rows.values()]
        )
    if deleted is not None:
        deleted.extend(stored)
    log.info("%d Bauteile aus %s gelöscht", len(stored), cat.table)
    if stored:
        _parts_changed(cat.table, inserted=False)
    return len(stored)


def _update_many(conn: Connection, c: _Ctx, items: list[tuple[str, dict[str, str | None]]]) -> None:
    """executemany UPDATE of full rows: items = [(stored part number, new row)]."""
    if not items:
        return
    columns = list(c.fields)
    stmt = (
        update(c.table)
        .where(c.table.c[PART_NUMBER] == bindparam("pf__pk"))
        .values({col: bindparam(f"pf__v{i}") for i, col in enumerate(columns)})
    )
    for chunk in _chunks(items):
        conn.execute(stmt, [{"pf__pk": pk, **{f"pf__v{i}": row.get(col) for i, col in enumerate(columns)}} for pk, row in chunk])


def _mass_change_backup(count: int, enabled: bool, backups: list[str] | None) -> None:
    """Automatic backup before a mass change of more than :data:`AUTO_BACKUP_DELETE_THRESHOLD` parts (the
    file name goes into ``backups``)."""
    if not enabled or count <= AUTO_BACKUP_DELETE_THRESHOLD:
        return
    from . import backup as _backup

    path = _backup.auto_backup(f"vor_massenaenderung_{count}_bauteile")
    if path is not None and backups is not None:
        backups.append(path.name)


def bulk_update(
    table: str,
    pns: Iterable[str],
    values: Mapping[str, Any],
    *,
    author: str | None = None,
    warnings: list[str] | None = None,
    backup: bool = True,
    backups: list[str] | None = None,
    audit_ids: list[int] | None = None,
) -> int:
    """Set the same values on many parts (all or nothing). Returns the number of changed parts.

    More than :data:`AUTO_BACKUP_DELETE_THRESHOLD` parts: automatic backup first (``backup=False`` skips it;
    ``backups`` receives the file name). ``audit_ids`` receives the ids of the audit entries – the input of
    :func:`restore_updates` (undo)."""
    for key, raw in values.items():
        if str(key).strip().casefold() == PART_NUMBER.casefold() and to_text(raw) is not None:
            raise PartValidationError({PART_NUMBER: "Die Teilenummer kann nicht per Massenbearbeitung geändert werden."})
    cat = categories.get_category(table)
    c = _Ctx(cat)
    wanted = list(dict.fromkeys(p for p in pns if p and str(p).strip()))
    if not wanted or not values:
        return 0
    _mass_change_backup(len(wanted), backup, backups)
    who = audit.resolve_author(author)
    now = audit.now_text()
    collected: list[str] = []
    with core.connect() as conn:
        rows = _fetch_rows(conn, c.table, wanted)
        items: list[tuple[str, dict[str, str | None]]] = []
        audit_rows: list[dict[str, Any]] = []
        errors: dict[str, str] = {}
        for existing in rows.values():
            prepared = _prepare(c, values, existing=existing, author=who, now=now)
            pk = str(existing[PART_NUMBER])
            for col, msg in prepared.errors.items():
                if len(errors) < 50:
                    errors[f"{pk} – {col}"] = msg
            collected.extend(f"{pk}: {w}" for w in prepared.warnings[:5])
            changes = audit.diff(existing, prepared.row)
            if changes:
                items.append((pk, prepared.row))
                audit_rows.append(audit.entry_row("bulk_update", cat.table, pk, changes, who))
        if errors:
            raise PartValidationError(errors, "Massenbearbeitung abgebrochen – " + "; ".join(f"{k}: {v}" for k, v in list(errors.items())[:10]))
        _update_many(conn, c, items)
        ids = audit.record_many(conn, audit_rows, returning=audit_ids is not None)
    if audit_ids is not None:
        audit_ids.extend(ids)
    if warnings is not None:
        warnings.extend(collected[:_MAX_WARNINGS])
    if items:
        _parts_changed(cat.table, inserted=False)
    return len(items)


def _row_part_number(c: _Ctx, incoming: Mapping[str, Any]) -> str | None:
    """Part number of an input row without full normalisation (PN, else MPN for scheme mpn)."""
    values = {str(k).strip().casefold(): v for k, v in incoming.items()}
    pn = to_text(values.get(PART_NUMBER.casefold()))
    if pn:
        return pn
    if c.scheme == "mpn":
        return to_text(values.get("manufacturer part number"))
    return None


def _row_mpn(incoming: Mapping[str, Any]) -> str | None:
    values = {str(k).strip().casefold(): v for k, v in incoming.items()}
    return to_text(values.get("manufacturer part number"))


def _part_numbers_by_mpn(conn: Connection, c: _Ctx) -> dict[str, str]:
    """``{mpn_key: stored part number}`` of the category (the first part per key). Rows of an import without a
    part number – scheme ``internal``: a BOM or distributor export carries only manufacturer part numbers – find
    the part they update through it instead of creating a second part with the next internal number."""
    mpn_field = c.cat.field("Manufacturer Part Number")
    if mpn_field is None:
        return {}
    out: dict[str, str] = {}
    for pn, mpn in conn.execute(select(c.table.c[PART_NUMBER], c.table.c[mpn_field.column])):
        key = mpn_key(mpn)
        if key and pn is not None:
            out.setdefault(key, str(pn))
    return out


def _progress(ctx: JobContext | None, fraction: float, message: str) -> None:
    if ctx is not None:
        ctx.progress(fraction, message)


RowStatus = Literal["create", "update", "unchanged", "skip", "reject"]


@dataclass
class RowPlan:
    """What :func:`upsert_parts` does – or would do (:func:`plan_upsert`) – with one input row.

    ``label`` is the key of ``UpsertResult.errors`` (the row's part number, else ``"Zeile n"``),
    ``message`` the error text there; ``reasons`` explain a rejected or skipped row in German (field
    errors with the field label), ``errors`` are the field errors by column, ``missing`` the labels of
    empty required fields imported as draft, ``changed`` the columns an update changes and
    ``conflict`` the ``(table, part number)`` of the part that blocks the row's part number.
    ``part_number`` is ``None`` only in a dry run for a generated internal number.
    """

    index: int
    label: str
    status: RowStatus
    part_number: str | None = None
    message: str = ""
    errors: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    conflict: tuple[str, str] | None = None
    row: dict[str, str | None] | None = None  # prepared row (create, update)
    stored: str | None = None  # stored part number of the existing part (update, unchanged, skip)
    changes: dict[str, list[Any]] = field(default_factory=dict)  # audit diff (create, update)


#: Note of a dry-run row whose internal part number is generated when importing.
PN_ASSIGNED_ON_IMPORT = "Teilenummer: wird beim Import automatisch vergeben."


def _rejected(index: int, label: str, message: str, *, conflict: tuple[str, str] | None = None) -> RowPlan:
    return RowPlan(index, label, "reject", message=message, reasons=[message], conflict=conflict)


def _plan_upsert(
    conn: Connection,
    c: _Ctx,
    items: Sequence[Mapping[str, Any]],
    *,
    mode: Literal["skip", "update", "error"],
    who: str,
    now: str,
    allow_incomplete: bool,
    strict: bool,
    pn_factory: Callable[[], str] | None,
    ctx: JobContext | None = None,
    thousands: bool | None = None,
) -> list[RowPlan]:
    """The outcome of every input row (shared by the import and its dry run; writes nothing itself –
    only ``pn_factory`` may reserve internal part numbers)."""
    total = len(items)
    pns = [_row_part_number(c, row) for row in items]
    mpn_keys: list[str | None] = [None] * total  # of the rows without a part number (scheme internal)
    if c.scheme == "internal" and any(p is None for p in pns):
        by_mpn = _part_numbers_by_mpn(conn, c)
        for i, (row, pn) in enumerate(zip(items, pns)):
            if pn is None:
                mkey = mpn_key(_row_mpn(row))
                if mkey:
                    mpn_keys[i] = mkey
                    if mkey in by_mpn:  # the part exists: this row updates (or skips) it
                        pns[i] = by_mpn[mkey]
    existing = _fetch_rows(conn, c.table, [p for p in pns if p])
    others = {
        key: hit
        for key, hit in _find_conflicts(conn, [p for p in pns if p]).items()
        if hit[0].casefold() != c.cat.table.casefold()
    }
    if pn_factory is not None and c.scheme == "internal" and any(p is None for p in pns):
        # generated numbers must avoid existing ones *and* explicit numbers later in this batch
        c.pn_keys = _all_pn_keys(conn) | {pn_key(p) for p in pns if p}
    plans: list[RowPlan] = []
    seen: dict[str, int] = {}
    seen_mpn: dict[str, int] = {}
    for i, (incoming, raw_pn) in enumerate(zip(items, pns)):
        if ctx is not None and i % 200 == 0:
            ctx.check_cancelled()
            _progress(ctx, 0.8 * i / max(total, 1), f"Zeile {i + 1} von {total} …")
        label = raw_pn or f"Zeile {i + 1}"
        key = pn_key(raw_pn) if raw_pn else None
        if key is None and mpn_keys[i]:  # two new rows of one manufacturer part number would become two parts
            if mpn_keys[i] in seen_mpn:
                plans.append(_rejected(i, label, f"Hersteller-Teilenummer doppelt in den Daten (auch in Zeile "
                                                 f"{seen_mpn[mpn_keys[i]] + 1})."))
                continue
            seen_mpn[mpn_keys[i]] = i
        if key is not None:
            if key in seen:
                plans.append(_rejected(i, label, f"Teilenummer doppelt in den Daten (auch in Zeile {seen[key] + 1})."))
                continue
            seen[key] = i
            if key in others:
                other_table, other_pn = others[key]
                plans.append(_rejected(i, label, str(DuplicatePartError(str(raw_pn), other_table, other_pn)),
                                       conflict=(other_table, other_pn)))
                continue
        current = existing.get(key) if key is not None else None
        stored = str(current[PART_NUMBER]) if current is not None else None
        pending_pn = False
        if current is not None:
            if mode == "skip":
                plans.append(RowPlan(i, label, "skip", part_number=stored, stored=stored,
                                     reasons=[f"Die Teilenummer „{stored}“ gibt es bereits – die Zeile wird übersprungen."]))
                continue
            if mode == "error":
                plans.append(_rejected(i, label, f"Die Teilenummer existiert bereits in „{c.cat.table}“.",
                                       conflict=(c.cat.table, str(stored))))
                continue
            # empty cells never erase data; the stored spelling of the part number is kept
            non_empty = {k: v for k, v in incoming.items()
                         if to_text(v) is not None and str(k).strip().casefold() != PART_NUMBER.casefold()}
            prepared = _prepare(c, non_empty, existing=current, author=who, now=now, strict=strict,
                                thousands=thousands)
        else:
            prepared = _prepare(c, incoming, existing=None, author=who, now=now, allow_incomplete=allow_incomplete,
                                pn_factory=pn_factory, strict=strict, thousands=thousands)
            if pn_factory is None and c.scheme == "internal" and not prepared.row.get(PART_NUMBER):
                prepared.errors.pop(PART_NUMBER, None)  # dry run: the number is assigned when importing
                pending_pn = True
        if prepared.errors:
            plans.append(RowPlan(
                i, label, "reject", message="; ".join(f"{k}: {v}" for k, v in prepared.errors.items()),
                errors=dict(prepared.errors), reasons=[f"{c.label(k)}: {v}" for k, v in prepared.errors.items()],
                warnings=prepared.warnings, missing=prepared.missing,
            ))
            continue
        final_pn = prepared.row.get(PART_NUMBER)
        if current is None:
            if key is None and final_pn:  # generated internal number
                seen[pn_key(str(final_pn))] = i
            warnings = [PN_ASSIGNED_ON_IMPORT, *prepared.warnings] if pending_pn else prepared.warnings
            plans.append(RowPlan(i, label, "create", part_number=str(final_pn) if final_pn else None,
                                 warnings=warnings, missing=prepared.missing, row=prepared.row,
                                 changes=audit.diff(None, prepared.row)))
            continue
        changes = audit.diff(current, prepared.row)
        status: RowStatus = "update" if changes else "unchanged"
        plans.append(RowPlan(i, label, status, part_number=stored, stored=stored, warnings=prepared.warnings,
                             changed=list(changes), row=prepared.row if changes else None, changes=changes))
    return plans


def upsert_parts(
    table: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    mode: Literal["skip", "update", "error"] = "skip",
    author: str | None = None,
    ctx: JobContext | None = None,
    allow_incomplete: bool = False,
    strict: bool = False,
    thousands: bool | None = None,
    before_write: Callable[[], None] | None = None,
) -> UpsertResult:
    """Insert many parts at once (series generator, spreadsheet import).

    ``mode`` decides what happens with part numbers that already exist in this table:
    ``skip`` (default), ``update`` (non-empty incoming values overwrite) or ``error``.
    Part numbers existing in *another* category are always errors. Invalid rows are
    reported in ``UpsertResult.errors`` and skipped; everything else is written in one
    transaction (a cancelled job rolls back completely). ``strict``: unreadable values
    (no number, wrong unit, no date, ambiguous comma …) make the row invalid instead of a warning.
    ``thousands``: number format of the source for ambiguous comma groups ("1,000µF"; ``None`` =
    unknown: warning, :func:`partforge.db.values.normalize_cell`). ``before_write`` runs after the rows
    were checked and only if something will be written (e.g. the automatic backup of an import).
    :func:`plan_upsert` answers the same per row without writing.
    """
    if mode not in ("skip", "update", "error"):
        raise ValueError(f"Ungültiger Modus „{mode}“ (skip, update oder error).")
    cat = categories.get_category(table)
    c = _Ctx(cat)
    items = list(rows)
    total = len(items)
    result = UpsertResult()
    who = audit.resolve_author(author)
    now = audit.now_text()
    _progress(ctx, 0.0, f"{total} Zeilen werden geprüft …")
    with core.connect() as conn:
        plans = _plan_upsert(conn, c, items, mode=mode, who=who, now=now, allow_incomplete=allow_incomplete,
                             strict=strict, pn_factory=lambda: _next_internal_pn(conn, c), ctx=ctx,
                             thousands=thousands)
        inserts: list[dict[str, str | None]] = []
        updates: list[tuple[str, dict[str, str | None]]] = []
        audit_rows: list[dict[str, Any]] = []
        warning_count = 0
        for plan in plans:
            if plan.status == "reject":
                result.errors[plan.label] = plan.message
                continue
            if plan.status == "skip":
                result.skipped.append(str(plan.stored))
                continue
            final_pn = str(plan.part_number)
            if plan.warnings and warning_count < _MAX_WARNINGS:
                result.warnings[final_pn] = plan.warnings
                warning_count += 1
            if plan.status == "create":
                assert plan.row is not None
                inserts.append(plan.row)
                result.created.append(final_pn)
                audit_rows.append(audit.entry_row("import", cat.table, final_pn, plan.changes, who))
            elif plan.status == "unchanged":
                result.unchanged.append(str(plan.stored))
            else:
                assert plan.row is not None and plan.stored is not None
                updates.append((plan.stored, plan.row))
                result.updated.append(plan.stored)
                audit_rows.append(audit.entry_row("import", cat.table, plan.stored, plan.changes, who))
        writes = len(inserts) + len(updates)
        if writes and before_write is not None:
            before_write()
        done = 0
        for chunk in _chunks(inserts):
            if ctx is not None:
                ctx.check_cancelled()
            conn.execute(insert(c.table), list(chunk))
            done += len(chunk)
            _progress(ctx, 0.8 + 0.15 * done / max(writes, 1), f"{done} von {writes} Bauteilen gespeichert …")
        if updates:
            if ctx is not None:
                ctx.check_cancelled()
            _update_many(conn, c, updates)
        audit.record_many(conn, audit_rows)
        _progress(ctx, 0.98, "Änderungen werden übernommen …")
    log.info(
        "Import in %s: %d neu, %d aktualisiert, %d übersprungen, %d Fehler",
        cat.table, len(result.created), len(result.updated), len(result.skipped), len(result.errors),
    )
    _progress(ctx, 1.0, f"{len(result.created)} neu, {len(result.updated)} aktualisiert")
    if result.created or result.updated:
        _parts_changed(cat.table, inserted=bool(result.created))
    return result


def plan_upsert(
    table: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    mode: Literal["skip", "update", "error"] = "skip",
    allow_incomplete: bool = False,
    strict: bool = False,
    thousands: bool | None = None,
) -> list[RowPlan]:
    """Dry run of :func:`upsert_parts`: the outcome of every row (create, update, unchanged, skip or
    reject with reasons) – nothing is written, internal part numbers are not reserved."""
    if mode not in ("skip", "update", "error"):
        raise ValueError(f"Ungültiger Modus „{mode}“ (skip, update oder error).")
    cat = categories.get_category(table)
    c = _Ctx(cat)
    with core.read() as conn:
        return _plan_upsert(conn, c, list(rows), mode=mode, who=audit.resolve_author(None), now=audit.now_text(),
                            allow_incomplete=allow_incomplete, strict=strict, pn_factory=None, thousands=thousands)


def duplicate_part(table: str, pn: str, new_pn: str, *, author: str | None = None) -> dict[str, str | None]:
    """Copy a part under a new part number (status back to "Entwurf")."""
    source = get_part(table, pn)
    if source is None:
        raise PartNotFound(table, pn)
    values = {k: v for k, v in source.items() if k not in BOOKKEEPING and k != "PF Status"}
    values[PART_NUMBER] = new_pn
    return create_part(table, values, author=author, allow_incomplete=True)


def history(table: str, pn: str) -> list[dict[str, Any]]:
    """Audit entries of a part (newest first, follows renames)."""
    cat = categories.get_category(table)
    row = get_part(cat.table, pn)
    stored = str(row[PART_NUMBER]) if row else pn
    return [e.model_dump() for e in audit.history(cat.table, stored)]


def restore_parts(table: str, pns: Iterable[str], *, author: str | None = None) -> dict[str, Any]:
    """Bring deleted parts back from their latest ``delete`` entry in the change history (undo of
    :func:`delete_parts`; the entry holds every value of the deleted row).

    The row is inserted as it was (values are not re-normalised, ``PF Created`` kept; ``PF Modified``/
    ``PF Author`` = now/``author``) with a ``restore`` audit entry. Values of fields removed from the
    category since are dropped (warning). Returns ``{restored, parts, conflicts, not_found, warnings}``:
    ``conflicts`` = part numbers taken again meanwhile (any category), ``not_found`` = no deletion
    recorded. One transaction for all parts."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    wanted: dict[str, str] = {}
    for raw in pns:
        text = str(raw).strip() if raw is not None else ""
        if text:
            wanted.setdefault(pn_key(text), text)
    out: dict[str, Any] = {"restored": [], "parts": [], "conflicts": {}, "not_found": [], "warnings": []}
    if not wanted:
        return out
    who = audit.resolve_author(author)
    now = audit.now_text()
    with core.connect() as conn:
        entries = audit.last_deletions(conn, cat.table, list(wanted.values()))
        taken = _find_conflicts(conn, [e.part_number or "" for e in entries.values()])
        inserts: list[dict[str, str | None]] = []
        audit_rows: list[dict[str, Any]] = []
        for key, pn in wanted.items():
            entry = entries.get(key)
            if entry is None or not entry.part_number:
                out["not_found"].append(pn)
                continue
            stored = entry.part_number
            hit = taken.get(pn_key(stored))
            if hit is not None:
                out["conflicts"][pn] = (f"Die Teilenummer „{hit[1]}“ ist inzwischen wieder vergeben (Kategorie "
                                        f"„{hit[0]}“) – das gelöschte Bauteil wird nicht wiederhergestellt.")
                continue
            row, dropped = _deleted_row(c, entry.changes, stored, author=who, now=now)
            if dropped:
                out["warnings"].append(f"{stored}: Werte entfernter Felder verworfen ({', '.join(dropped)}).")
            inserts.append(row)
            audit_rows.append(audit.entry_row("restore", cat.table, stored, audit.diff(None, row), who))
            out["restored"].append(stored)
            out["parts"].append(dict(row))
        for chunk in _chunks(inserts):
            conn.execute(insert(c.table), list(chunk))
        audit.record_many(conn, audit_rows)
    if inserts:
        log.info("%d gelöschte Bauteile in %s wiederhergestellt", len(inserts), cat.table)
        _parts_changed(cat.table, inserted=True)
    return out


def _deleted_row(c: _Ctx, changes: Mapping[str, Any], stored: str, *, author: str,
                 now: str) -> tuple[dict[str, str | None], list[str]]:
    """Row of a ``delete`` audit entry (``{column: [old, None]}``) for the current category fields."""
    values: dict[str, str | None] = {}
    dropped: list[str] = []
    for column, change in changes.items():
        old = change[0] if isinstance(change, list) and len(change) == 2 else None
        f = c.lookup.get(str(column).casefold())
        if f is None:
            if to_text(old) is not None:
                dropped.append(str(column))
            continue
        values[f.column] = None if old is None else str(old)
    row: dict[str, str | None] = {col: values.get(col) for col in c.fields}
    row[PART_NUMBER] = stored
    if "PF Created" in c.fields and not row.get("PF Created"):
        row["PF Created"] = now
    if "PF Modified" in c.fields:
        row["PF Modified"] = now
    if "PF Author" in c.fields:
        row["PF Author"] = author
    return row, dropped


def regenerate_texts(
    table: str,
    pns: Iterable[str] | None = None,
    *,
    columns: Sequence[str] = AUTO_COLUMNS,
    author: str | None = None,
    backup: bool = True,
    backups: list[str] | None = None,
    audit_ids: list[int] | None = None,
) -> int:
    """Re-render Value/Comment/Description from the templates (e.g. after a template
    change), overwriting manual texts. Returns the number of changed parts.

    Backup and undo like :func:`bulk_update` (``backup``, ``backups``, ``audit_ids``)."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    wanted = [col for col in AUTO_COLUMNS if col in columns and col in c.fields and c.templates.get(col)]
    if not wanted:
        return 0
    selected = list(dict.fromkeys(p for p in pns if p and str(p).strip())) if pns is not None else None
    if selected is None:
        with core.read() as conn:
            count = int(conn.execute(select(func.count()).select_from(c.table)).scalar_one())
    else:
        count = len(selected)
    _mass_change_backup(count, backup, backups)
    who = audit.resolve_author(author)
    now = audit.now_text()
    with core.connect() as conn:
        if selected is None:
            rows = [_clean_row(r) for r in conn.execute(select(c.table)).mappings()]
        else:
            rows = list(_fetch_rows(conn, c.table, selected).values())
        items: list[tuple[str, dict[str, str | None]]] = []
        audit_rows: list[dict[str, Any]] = []
        for existing in rows:
            row = dict(existing)
            for col in wanted:
                row[col] = c.render(col, row) or None
            changes = audit.diff(existing, row)
            if not changes:
                continue
            if "PF Modified" in c.fields:
                row["PF Modified"] = now
            if "PF Author" in c.fields:
                row["PF Author"] = who
            pk = str(existing[PART_NUMBER])
            items.append((pk, row))
            audit_rows.append(audit.entry_row("bulk_update", cat.table, pk, changes, who))
        _update_many(conn, c, items)
        ids = audit.record_many(conn, audit_rows, returning=audit_ids is not None)
    if audit_ids is not None:
        audit_ids.extend(ids)
    if items:
        _parts_changed(cat.table, inserted=False)
    return len(items)


#: Audit actions :func:`restore_updates` can take back (mass changes; also single edits of these parts).
UNDOABLE_ACTIONS = frozenset({"bulk_update", "update"})


def restore_updates(table: str, audit_ids: Iterable[int], *, author: str | None = None) -> dict[str, Any]:
    """Undo of :func:`bulk_update` / :func:`regenerate_texts`: set the old values of the given audit entries
    back (``audit_ids`` from the answer of the mass change).

    Per part all or nothing: a part whose value was changed again since (the current value is neither
    the new nor the old one) or that no longer exists is left alone (``conflicts``); a part whose values are
    already back is ``unchanged``. Part number changes are not taken back. One transaction, an audit entry
    ``restore`` per part. Returns ``{restored, parts, conflicts, unchanged, not_found, warnings}``
    (``not_found`` = unknown audit ids). Entries of another category or other actions: :class:`ValueError`."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    wanted = sorted({int(i) for i in audit_ids})
    out: dict[str, Any] = {"restored": [], "parts": [], "conflicts": {}, "unchanged": [], "not_found": [],
                           "warnings": []}
    if not wanted:
        return out
    who = audit.resolve_author(author)
    now = audit.now_text()
    with core.connect() as conn:
        entries = audit.entries_by_id(conn, wanted)
        out["not_found"] = [i for i in wanted if i not in entries]
        foreign = [e for e in entries.values() if (e.table or "").casefold() != cat.table.casefold()]
        if foreign:
            raise ValueError(f"Die Änderung {foreign[0].id} gehört zur Kategorie „{foreign[0].table}“, nicht zu "
                             f"„{cat.table}“ – nichts zurückgesetzt.")
        other = [e for e in entries.values() if e.action not in UNDOABLE_ACTIONS]
        if other:
            raise ValueError(f"Die Änderung {other[0].id} ({other[0].action}) lässt sich so nicht zurücknehmen – nur "
                             "Massen- und Einzeländerungen; nichts zurückgesetzt.")
        by_part: dict[str, list[Any]] = {}
        for entry in entries.values():
            if entry.part_number:
                by_part.setdefault(pn_key(entry.part_number), []).append(entry)
        rows = _fetch_rows(conn, c.table, [e[0].part_number for e in by_part.values()])
        items: list[tuple[str, dict[str, str | None]]] = []
        audit_rows: list[dict[str, Any]] = []
        for key, part_entries in by_part.items():
            label = str(part_entries[0].part_number)
            current = rows.get(key)
            if current is None:
                out["conflicts"][label] = "Das Bauteil gibt es nicht mehr (gelöscht oder umbenannt) – nicht zurückgesetzt."
                continue
            row = dict(current)
            changed_since: list[str] = []
            for entry in sorted(part_entries, key=lambda e: e.id, reverse=True):  # newest first: chain back
                for column, change in entry.changes.items():
                    if column in audit.DIFF_IGNORE or column.casefold() == PART_NUMBER.casefold():
                        continue
                    if not (isinstance(change, list) and len(change) == 2):
                        continue
                    f = c.lookup.get(str(column).casefold())
                    if f is None:
                        out["warnings"].append(f"{label}: Feld „{column}“ gibt es nicht mehr – nicht zurückgesetzt.")
                        continue
                    old, new = (None if v in (None, "") else str(v) for v in change)
                    value = row.get(f.column) or None
                    if value == new:
                        row[f.column] = old
                    elif value != old:
                        changed_since.append(f.label)
            if changed_since:
                out["conflicts"][label] = (f"Seit der Änderung erneut geändert ({', '.join(dict.fromkeys(changed_since))})"
                                           " – nicht zurückgesetzt.")
                continue
            changes = audit.diff(current, row)
            if not changes:
                out["unchanged"].append(str(current[PART_NUMBER]))
                continue
            if "PF Modified" in c.fields:
                row["PF Modified"] = now
            if "PF Author" in c.fields:
                row["PF Author"] = who
            pk = str(current[PART_NUMBER])
            items.append((pk, row))
            audit_rows.append(audit.entry_row("restore", cat.table, pk, changes, who))
            out["restored"].append(pk)
            out["parts"].append(dict(row))
        _update_many(conn, c, items)
        audit.record_many(conn, audit_rows)
    if items:
        log.info("%d Bauteile in %s zurückgesetzt (Rückgängig)", len(items), cat.table)
        _parts_changed(cat.table, inserted=False)
    return out


def set_library_path(
    kind: Literal["symbol", "footprint"],
    name: str,
    library: str,
    *,
    author: str | None = None,
) -> int:
    """Point every part that references symbol/footprint ``name`` (case-insensitive) to
    ``library`` – across all categories (``Library Path`` resp. ``Footprint Path [n]``).
    Used by the library sync when a symbol/footprint lives in another file. Returns the
    number of changed parts."""
    if not name or not name.strip():
        return 0
    pairs = (("Library Ref", "Library Path"),) if kind == "symbol" else None
    who = audit.resolve_author(author)
    now = audit.now_text()
    stored_path = normalize_cell(FieldDef(column="Library Path", label="", kind="path"), library,
                                 ws_root=core.current_workspace().root).value
    changed = 0
    cats = categories.list_categories(with_counts=False)
    with core.connect() as conn:
        for cat in cats:
            c = _Ctx(cat)
            links = pairs or tuple(
                (ref, ref.replace("Ref", "Path")) for ref in c.fields
                if re.fullmatch(r"Footprint Ref( \d+)?", ref) and ref.replace("Ref", "Path") in c.fields
            )
            originals: dict[str, dict[str, str | None]] = {}
            rows: dict[str, dict[str, str | None]] = {}
            for ref_col, path_col in links:
                if ref_col not in c.fields or path_col not in c.fields:
                    continue
                stmt = select(c.table).where(_ci_eq(conn, c.table.c[ref_col], name.strip()),
                                             or_(c.table.c[path_col].is_(None), c.table.c[path_col] != stored_path))
                for raw in conn.execute(stmt).mappings():
                    existing = _clean_row(raw)
                    pk = str(existing[PART_NUMBER])
                    originals.setdefault(pk, existing)
                    row = rows.setdefault(pk, dict(existing))  # one part may match several Ref columns
                    row[path_col] = stored_path
                    if "PF Modified" in c.fields:
                        row["PF Modified"] = now
                    if "PF Author" in c.fields:
                        row["PF Author"] = who
            _update_many(conn, c, list(rows.items()))
            audit.record_many(conn, [audit.entry_row("bulk_update", cat.table, pk, audit.diff(originals[pk], row), who)
                                     for pk, row in rows.items()])
            changed += len(rows)
    if changed:
        _parts_changed(None, inserted=False)
    return changed


# --------------------------------------------------------------------------- templates / validation preview


def render_templates(table: str, values: Mapping[str, Any]) -> dict[str, str]:
    """Value/Comment/Description as the templates would generate them for these values."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    row: dict[str, Any] = {col: None for col in c.fields}
    for key, raw in values.items():
        f = c.lookup.get(str(key).strip().casefold())
        if f is not None:
            row[f.column] = normalize_cell(f, raw, ws_root=c.ws_root).value
    out: dict[str, str] = {}
    for col in AUTO_COLUMNS:
        rendered = c.render(col, row)
        out[col] = rendered
        if not row.get(col):
            row[col] = rendered or None
    return out


def render_template_text(table: str, template: str, values: Mapping[str, Any]) -> dict[str, Any]:
    """Any template (e.g. one being edited in the category settings) rendered for these values.

    Values are normalised as on saving; empty Value/Comment/Description are generated from the
    category templates first (like :func:`render_templates`), so ``{Value}`` works. Returns ``{text,
    fields, unknown}``: the referenced columns and those the category does not have."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    row: dict[str, Any] = {col: None for col in c.fields}
    for key, raw in values.items():
        f = c.lookup.get(str(key).strip().casefold())
        if f is not None:
            row[f.column] = normalize_cell(f, raw, ws_root=c.ws_root).value
    for col in AUTO_COLUMNS:
        if col in c.fields and not row.get(col):
            row[col] = c.render(col, row) or None
    referenced = template_columns(template or "")
    unknown = [name for name in referenced if c.lookup.get(name.casefold()) is None]
    return {"text": render_template(template or "", row, c.fields), "fields": referenced, "unknown": unknown}


def validate_part(
    table: str,
    values: Mapping[str, Any],
    *,
    pn: str | None = None,
    allow_incomplete: bool = False,
) -> dict[str, Any]:
    """Dry run of create (``pn`` None) or update (``pn`` = existing part): normalised
    values, warnings, errors and a part-number conflict – nothing is written."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    who = audit.resolve_author(None)
    now = audit.now_text()
    conflict: dict[str, str] | None = None
    with core.read() as conn:
        existing = _fetch_row(conn, c.table, pn) if pn else None
        if pn and existing is None:
            raise PartNotFound(cat.table, pn)
        prepared = _prepare(c, values, existing=existing, author=who, now=now, allow_incomplete=allow_incomplete)
        new_pn = prepared.row.get(PART_NUMBER)
        if not new_pn and c.scheme == "internal" and existing is None:
            prepared.errors.pop(PART_NUMBER, None)
            prepared.warnings.append("Teilenummer: wird beim Speichern automatisch vergeben.")
        elif new_pn:
            exclude = (cat.table, str(existing[PART_NUMBER])) if existing else None
            hit = _find_conflicts(conn, [str(new_pn)], exclude=exclude).get(pn_key(str(new_pn)))
            if hit:
                conflict = {"table": hit[0], "part_number": hit[1], "message": str(DuplicatePartError(str(new_pn), *hit))}
    return {"values": prepared.row, "warnings": prepared.warnings, "errors": prepared.errors, "conflict": conflict}


def _unit_candidates(fields: Sequence[FieldDef], unit: str, found: Mapping[str, str]) -> list[FieldDef]:
    """Open quantity/range fields for a value typed with ``unit``: fields with exactly that
    unit first, then fields whose unit accepts it (:func:`units_compatible`: "±100ppm" fills
    a TCR field in ppm/K); category order within each group."""
    open_fields = [f for f in fields if f.kind in ("quantity", "range") and f.unit and f.column not in found]
    wanted = canonical_unit(unit)
    exact = [f for f in open_fields if canonical_unit(f.unit) == wanted]
    taken = {f.column for f in exact}
    return exact + [f for f in open_fields if f.column not in taken and units_compatible(unit, f.unit)]


def smart_fill(table: str, text: str) -> dict[str, Any]:
    """Interpret free text like ``"10k 1% 0603 0.1W ±100ppm"`` as field values of a category.

    Tokens become enum options, values of the field with the typed unit (exact unit first,
    then a compatible one: ``ppm`` fills ``ppm/K`` and vice versa) or – without a unit – of
    the category's value field. Unassigned tokens are returned in ``unmatched``."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    found: dict[str, str] = {}
    unmatched: list[str] = []
    category_first = sorted(cat.fields, key=lambda f: (f.common, f.sort_order))
    value_field = c.lookup.get((cat.value_field or "").casefold())
    for token in search_tokens(text):
        assigned = False
        for f in category_first:
            if f.kind == "enum" and f.column not in found:
                res = normalize_cell(f, token)
                if res.warning is None and res.value is not None:
                    found[f.column] = res.value
                    assigned = True
                    break
        if assigned:
            continue
        q = parse_quantity(token) if any(ch.isdigit() for ch in token) else None
        if q is not None:
            if q.unit:
                candidates = _unit_candidates(category_first, q.unit, found)
            elif value_field is not None and value_field.kind == "quantity" and value_field.column not in found:
                candidates = [value_field]
            else:
                candidates = []
            for f in candidates:
                res = normalize_cell(f, token)
                if res.warning is None and res.value is not None:
                    found[f.column] = res.value
                    assigned = True
                    break
        if not assigned:
            unmatched.append(token)
    return {"values": found, "unmatched": unmatched}


# --------------------------------------------------------------------------- query


def _coerce_filter(item: PartFilter | Mapping[str, Any]) -> PartFilter:
    return item if isinstance(item, PartFilter) else PartFilter.model_validate(dict(item))


def _coerce_sort(sort: str | Sequence[SortSpec | Mapping[str, Any] | str] | None) -> list[SortSpec]:
    if not sort:
        return []
    items: list[SortSpec | Mapping[str, Any] | str]
    items = [s.strip() for s in sort.split(",") if s.strip()] if isinstance(sort, str) else list(sort)
    specs: list[SortSpec] = []
    for item in items:
        if isinstance(item, SortSpec):
            specs.append(item)
        elif isinstance(item, str):
            desc = item.startswith("-")
            name = item[1:] if desc or item.startswith("+") else item
            if ":" in name and name.rsplit(":", 1)[1].lower() in ("asc", "desc"):
                name, direction = name.rsplit(":", 1)
                desc = direction.lower() == "desc"
            specs.append(SortSpec(column=name.strip(), desc=desc))
        else:
            specs.append(SortSpec.model_validate(dict(item)))
    return specs


def _filter_values(flt: PartFilter) -> list[str]:
    raw = flt.value
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        values = [to_text(v) for v in raw]
    else:
        values = [to_text(raw)]
    return [v for v in values if v is not None]


def _token_number(token: str, f: FieldDef) -> float | None:
    if not any(ch.isdigit() for ch in token):
        return None
    q = parse_field_quantity(token, f.unit)
    if q is None or not units_compatible(q.unit, f.unit):
        return None
    return q.value


def _num(column: Any, f: FieldDef) -> ColumnElement[Any]:
    return func.pf_num(column, literal(f.unit or ""))


def _num_equals(column: Any, f: FieldDef, value: float) -> ColumnElement[bool]:
    number = _num(column, f)
    return and_(number.is_not(None), func.abs(number - value) <= abs(value) * 1e-9)


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _unicode_fold() -> bool:
    """True if the SQL function ``pf_fold`` (Unicode case folding) exists (SQLite)."""
    return core.dialect_name() == "sqlite"


def _sql_fold(expr: Any) -> ColumnElement[Any]:
    """Case-folded SQL expression for case-insensitive comparisons.

    SQLite's ``lower()``/``LIKE`` only fold ASCII (``Ü``, ``Ω`` would never match), so
    SQLite uses ``pf_fold`` (``str.casefold``); other dialects use ``lower()``."""
    return func.pf_fold(expr) if _unicode_fold() else func.lower(expr)


def _fold(text: str) -> str:
    """Python counterpart of :func:`_sql_fold` (same folding on both sides)."""
    return text.casefold() if _unicode_fold() else text.lower()


# --- date and range filters ---------------------------------------------------------------

_DATE_OPS = frozenset({"before", "after", "between"})
_OP_TEXT = {"before": "vor", "after": "nach", "between": "zwischen"}
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}")
#: A date range ``[lower, upper)`` as comparison texts (``None`` = open side).
DateRange = tuple[str | None, str | None]


def _bound_text(moment: _dt.datetime) -> str:
    """Comparison text of a range bound: midnight as plain date – ``"2026-10-07"`` sorts before every
    stored time of that day (``"2026-10-07 00:00:00"``) and equal to a stored plain date."""
    if moment.time() == _dt.time():
        return moment.date().isoformat()
    return moment.isoformat(sep=" ", timespec="seconds")


def _date_span(text: str) -> DateRange | None:
    """``[start, end)`` of a date input: the whole day, minute or second it names."""
    parsed = parse_date(text)
    if parsed is None:
        return None
    moment, precision = parsed
    if precision == "day":
        start = _dt.datetime.combine(moment.date(), _dt.time())
        step = _dt.timedelta(days=1)
    elif precision == "minute":
        start, step = moment.replace(second=0, microsecond=0), _dt.timedelta(minutes=1)
    else:
        start, step = moment.replace(microsecond=0), _dt.timedelta(seconds=1)
    return _bound_text(start), _bound_text(start + step)


def _required_span(text: str, f: FieldDef) -> DateRange:
    span = _date_span(text)
    if span is None:
        raise ValueError(f"„{text}“ ist kein gültiges Datum für „{f.label}“ (z. B. 2026-10-07 oder 07.10.2026).")
    return span


def _between_values(flt: PartFilter) -> tuple[str | None, str | None]:
    """(from, to) of a ``between`` filter: ``[from, to]`` or ``{"from": …, "to": …}`` (one side may be empty)."""
    raw = flt.value
    if isinstance(raw, Mapping):
        lo, hi = raw.get("from", raw.get("min")), raw.get("to", raw.get("max"))
    elif isinstance(raw, (list, tuple)) and len(raw) == 2:
        lo, hi = raw
    else:
        raise ValueError(f"„zwischen“ bei „{flt.column}“ erwartet zwei Werte [von, bis] (eine Seite darf leer sein).")
    lo_text, hi_text = to_text(lo), to_text(hi)
    if lo_text is None and hi_text is None:
        raise ValueError(f"Für „zwischen“ bei „{flt.column}“ fehlen beide Werte.")
    return lo_text, hi_text


def _date_filter(f: FieldDef, op: str, flt: PartFilter, values: list[str]) -> tuple[list[DateRange], bool] | None:
    """``(ranges, negate)`` of a date comparison (rows in any range match), or ``None`` when the filter
    is no date comparison (text/number semantics; e.g. ``eq`` with a value that is no date)."""
    if op in _DATE_OPS:
        if f.kind != "date":
            if op == "between" and f.kind in _NUMERIC_KINDS:
                return None
            raise ValueError(f"„{_OP_TEXT[op]}“ gibt es nur für Datumsfelder"
                             f"{' und Zahlenfelder' if op == 'between' else ''} – „{f.label}“ ist keines.")
        if op == "between":
            lo, hi = _between_values(flt)
            lower = _required_span(lo, f)[0] if lo is not None else None
            upper = _required_span(hi, f)[1] if hi is not None else None
            return [(lower, upper)], False
        if not values:
            raise ValueError(f"Für „{_OP_TEXT[op]}“ bei „{f.column}“ fehlt ein Datum.")
        start, end = _required_span(values[0], f)
        return ([(None, start)] if op == "before" else [(end, None)]), False
    if f.kind != "date" or op not in ("eq", "ne", "in", "lt", "le", "gt", "ge") or not values:
        return None
    spans = [_date_span(v) for v in values]
    if any(span is None for span in spans):
        return None
    ranges = [span for span in spans if span is not None]
    if op in ("eq", "ne", "in"):
        return ranges, op == "ne"
    start, end = ranges[0]
    return {"lt": [(None, start)], "le": [(None, end)], "gt": [(end, None)], "ge": [(start, None)]}[op], False


def _sql_date(column: Any, ranges: list[DateRange], negate: bool) -> ColumnElement[bool]:
    cell = func.replace(column, "T", " ")  # "2026-10-07T21:30:00" compares like "2026-10-07 21:30:00"
    parts: list[ColumnElement[bool]] = []
    for lower, upper in ranges:
        terms: list[ColumnElement[bool]] = [column.is_not(None), column.like("____-__-__%")]
        if lower is not None:
            terms.append(cell >= lower)
        if upper is not None:
            terms.append(cell < upper)
        parts.append(and_(*terms))
    expr = or_(*parts)
    return not_(expr) if negate else expr


def _py_date(col: str, ranges: list[DateRange], negate: bool) -> Callable[[Mapping[str, Any]], bool]:
    def match(row: Mapping[str, Any]) -> bool:
        raw = row.get(col)
        text = str(raw).replace("T", " ") if raw not in (None, "") else ""
        hit = bool(_ISO_DAY.match(text)) and any(
            (lower is None or text >= lower) and (upper is None or text < upper) for lower, upper in ranges)
        return not hit if negate else hit

    return match


def _number_bounds(f: FieldDef, flt: PartFilter) -> tuple[float | None, float | None]:
    lo, hi = _between_values(flt)
    bounds: list[float | None] = []
    for text in (lo, hi):
        if text is None:
            bounds.append(None)
            continue
        number = _token_number(text, f)
        if number is None:
            raise ValueError(f"„{text}“ ist kein Wert für „{f.label}“ (Einheit {f.unit or '-'}).")
        bounds.append(number)
    return bounds[0], bounds[1]


def _sql_condition(c: _Ctx, flt: PartFilter, *, numeric_ok: bool) -> ColumnElement[bool] | None:
    """SQL for one filter; None if it needs pf_num() but SQL functions are unavailable."""
    f = c.field(flt.column)
    column = c.table.c[f.column]
    op = flt.op
    values = _filter_values(flt)
    if op in ("eq", "ne") and not values:
        op = "empty" if op == "eq" else "notempty"
    dates = _date_filter(f, op, flt, values)
    if dates is not None:
        return _sql_date(column, *dates)
    if op == "between":  # quantity/int fields (dates are handled above)
        lo, hi = _number_bounds(f, flt)
        if not numeric_ok:
            return None
        number = _num(column, f)
        terms = [number.is_not(None)]
        if lo is not None:
            terms.append(number >= lo)
        if hi is not None:
            terms.append(number <= hi)
        return and_(column.is_not(None), column != "", *terms)
    if op == "empty":
        return or_(column.is_(None), column == "")
    if op == "notempty":
        return and_(column.is_not(None), column != "")
    numeric = f.kind in _NUMERIC_KINDS
    numbers = [_token_number(v, f) if numeric else None for v in values]
    if numeric and any(n is not None for n in numbers) and op in ("eq", "ne", "in", "lt", "le", "gt", "ge") and not numeric_ok:
        return None
    if op in ("eq", "ne", "in"):
        parts: list[ColumnElement[bool]] = []
        for text, number in zip(values, numbers):
            text_eq = and_(column.is_not(None), _sql_fold(column) == _fold(text))
            parts.append(or_(_num_equals(column, f, number), text_eq) if number is not None else text_eq)
        expr = or_(*parts) if parts else false()
        return not_(expr) if op == "ne" else expr
    if op in ("lt", "le", "gt", "ge"):
        if not values:
            raise ValueError(f"Für den Vergleich „{op}“ bei „{f.column}“ fehlt ein Wert.")
        number = numbers[0] if numbers else None
        target: Any = _num(column, f) if number is not None else _sql_fold(column)
        bound: Any = number if number is not None else _fold(values[0])
        compare = {"lt": target < bound, "le": target <= bound, "gt": target > bound, "ge": target >= bound}[op]
        return and_(column.is_not(None), column != "", compare)
    if op == "contains":
        return and_(*[_sql_fold(column).like(f"%{_like(_fold(v))}%", escape="\\") for v in values]) if values else None
    if op == "startswith":
        return or_(*[_sql_fold(column).like(f"{_like(_fold(v))}%", escape="\\") for v in values]) if values else None
    raise ValueError(f"Unbekannter Filteroperator „{op}“.")


#: Columns the search box never looks at: where the part's files are, links and bookkeeping – the same text
#: in every part ("Symbols\PF_Passives.SchLib", "2026-10-08 …") would make most searches hit everything; the
#: column filters still reach them.
SEARCH_EXCLUDED_COLUMNS = frozenset({"Library Path", "PF Created", "PF Modified", "PF Author"})
_NOT_SEARCHED_KINDS = frozenset({"url", "path", "date"})


def search_columns(cat: CategoryDef) -> list[str]:
    """Columns of ``cat`` the search box covers (all except library paths, URLs, dates and ``PF Author``)."""
    return [f.column for f in cat.fields
            if f.column not in SEARCH_EXCLUDED_COLUMNS and f.kind not in _NOT_SEARCHED_KINDS
            and not re.fullmatch(r"Footprint Path( \d+)?", f.column)]


def _search_blob(c: _Ctx) -> ColumnElement[Any]:
    parts: list[ColumnElement[Any]] = [func.coalesce(c.table.c[col], "") for col in search_columns(c.cat)]
    joined = reduce(lambda a, b: a + " " + b, parts)
    return _sql_fold(joined)


def _token_targets(c: _Ctx, token: str) -> list[tuple[FieldDef, float]]:
    """Numeric fields a search token compares with: a number without unit (``10k``, ``4k7``, ``0603``) only
    the category's value field, a number with unit (``50V``, ``100nF``, ``1%``) the fields of that unit."""
    if not any(ch.isdigit() for ch in token):
        return []
    q = parse_quantity(token)
    if q is None:
        return []
    if not q.unit:
        f = c.lookup.get((c.cat.value_field or "").casefold())
        if f is None or f.kind not in _NUMERIC_KINDS:
            return []
        n = _token_number(token, f)
        return [(f, n)] if n is not None else []
    return [(f, n) for f in c.numeric_fields
            if f.unit and units_compatible(q.unit, f.unit) and (n := _token_number(token, f)) is not None]


def _sql_token(c: _Ctx, token: str, *, numeric_ok: bool) -> ColumnElement[bool] | None:
    text_match = _search_blob(c).like(f"%{_like(_fold(token))}%", escape="\\")
    numeric = _token_targets(c, token)
    if not numeric:
        return text_match
    if not numeric_ok:
        return None
    return or_(text_match, *[_num_equals(c.table.c[f.column], f, n) for f, n in numeric])


def _sql_order(c: _Ctx, specs: Sequence[SortSpec]) -> list[Any]:
    clauses: list[Any] = []
    for spec in specs:
        f = c.field(spec.column)
        column = c.table.c[f.column]
        if f.kind in _NUMERIC_KINDS:
            number = _num(column, f)
            clauses += [number.is_(None), number.desc() if spec.desc else number.asc()]
        empty = case((or_(column.is_(None), column == ""), 1), else_=0)
        clauses += [empty, _sql_fold(column).desc() if spec.desc else _sql_fold(column).asc()]
    clauses += [_sql_fold(c.table.c[PART_NUMBER]).asc(), c.table.c[PART_NUMBER].asc()]
    return clauses


def _py_condition(c: _Ctx, flt: PartFilter) -> Callable[[Mapping[str, Any]], bool]:
    f = c.field(flt.column)
    col = f.column
    op = flt.op
    values = _filter_values(flt)
    if op in ("eq", "ne") and not values:
        op = "empty" if op == "eq" else "notempty"
    dates = _date_filter(f, op, flt, values)
    if dates is not None:
        return _py_date(col, *dates)
    if op == "between":
        lo, hi = _number_bounds(f, flt)

        def within(row: Mapping[str, Any]) -> bool:
            value = numeric_value(row.get(col), f.unit) if row.get(col) not in (None, "") else None
            return value is not None and (lo is None or value >= lo) and (hi is None or value <= hi)

        return within
    numeric = f.kind in _NUMERIC_KINDS
    numbers = [_token_number(v, f) if numeric else None for v in values]
    fold = _fold

    def is_empty(row: Mapping[str, Any]) -> bool:
        return row.get(col) in (None, "")

    def equals(row: Mapping[str, Any], text: str, number: float | None) -> bool:
        cell = row.get(col)
        if cell is None:
            return False
        if number is not None:
            value = numeric_value(cell, f.unit)
            if value is not None and math.isclose(value, number, rel_tol=1e-9, abs_tol=0.0):
                return True
        return fold(str(cell)) == fold(text)

    if op == "empty":
        return is_empty
    if op == "notempty":
        return lambda row: not is_empty(row)
    if op in ("eq", "in"):
        return lambda row: any(equals(row, t, n) for t, n in zip(values, numbers))
    if op == "ne":
        return lambda row: not any(equals(row, t, n) for t, n in zip(values, numbers))
    if op in ("lt", "le", "gt", "ge"):
        if not values:
            raise ValueError(f"Für den Vergleich „{op}“ bei „{f.column}“ fehlt ein Wert.")
        number = numbers[0] if numbers else None
        compare = {"lt": lambda a, b: a < b, "le": lambda a, b: a <= b, "gt": lambda a, b: a > b, "ge": lambda a, b: a >= b}[op]

        def ordered(row: Mapping[str, Any]) -> bool:
            cell = row.get(col)
            if cell in (None, ""):
                return False
            if number is not None:
                value = numeric_value(cell, f.unit)
                return value is not None and compare(value, number)
            return compare(fold(str(cell)), fold(values[0]))

        return ordered
    if op == "contains":
        return lambda row: all(fold(v) in fold(str(row.get(col) or "")) for v in values)
    if op == "startswith":
        return lambda row: any(fold(str(row.get(col) or "")).startswith(fold(v)) for v in values)
    raise ValueError(f"Unbekannter Filteroperator „{op}“.")


def _py_token(c: _Ctx, token: str) -> Callable[[Mapping[str, Any]], bool]:
    fold = _fold
    needle = fold(token)
    numeric = _token_targets(c, token)
    columns = search_columns(c.cat)

    def match(row: Mapping[str, Any]) -> bool:
        blob = fold(" ".join(str(row.get(col) or "") for col in columns))
        if needle in blob:
            return True
        for f, n in numeric:
            value = numeric_value(row.get(f.column), f.unit)
            if value is not None and math.isclose(value, n, rel_tol=1e-9, abs_tol=0.0):
                return True
        return False

    return match


def _py_sort(c: _Ctx, rows: list[dict[str, Any]], specs: Sequence[SortSpec]) -> None:
    """Stable multi-key sort equivalent to :func:`_sql_order` (empties last in both directions)."""
    fold = _fold
    for spec in [*reversed(specs)]:
        f = c.field(spec.column)
        col = f.column
        numeric = f.kind in _NUMERIC_KINDS

        def key(row: Mapping[str, Any], *, _col: str = col, _f: FieldDef = f, _desc: bool = spec.desc,
                _numeric: bool = numeric) -> tuple[Any, ...]:
            cell = row.get(_col)
            empty = cell in (None, "")
            text = fold(str(cell or ""))
            primary = (not empty) if _desc else empty
            if _numeric:
                number = numeric_value(cell, _f.unit) if not empty else None
                has_number = number is not None
                return (primary, has_number if _desc else not has_number, number if has_number else 0.0, text)
            return (primary, text)

        rows.sort(key=key, reverse=spec.desc)


# --------------------------------------------------------------------------- search index (SQLite)

_INDEX_TABLES = 4  # categories whose index is kept (least recently used dropped)


@dataclass
class _SearchIndex:
    """Folded search text and engineering values of every part of one category (one database state)."""

    key: tuple[Any, ...]
    pns: list[str]
    blobs: list[str]
    numbers: dict[str, list[float | None]]  # column -> engineering value per part (filled when first needed)
    raw: dict[str, list[Any]]  # column -> stored text per part (numeric fields)

    def values(self, f: FieldDef) -> list[float | None]:
        cached = self.numbers.get(f.column)
        if cached is None:
            cached = [numeric_value(str(v), f.unit) if v not in (None, "") else None for v in self.raw[f.column]]
            self.numbers[f.column] = cached
        return cached


_index_lock = threading.Lock()
_index_build_lock = threading.Lock()
_indexes: dict[str, _SearchIndex] = {}


def _db_file_stamp(path: Any) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def _index_key(c: _Ctx) -> tuple[Any, ...]:
    ws = core.current_workspace()
    db = ws.sqlite_path
    signature = tuple((f.column, f.kind, f.unit) for f in c.cat.fields)
    return (str(ws.root), id(core.get_engine()), core.data_version(), _db_file_stamp(db),
            _db_file_stamp(db.with_name(db.name + "-wal")), signature, c.cat.value_field)


def _search_index(c: _Ctx) -> _SearchIndex:
    with _index_build_lock:  # concurrent first searches (grid page + count) build the index once
        key = _index_key(c)  # before reading: a write meanwhile makes the next search rebuild
        with _index_lock:
            index = _indexes.get(c.cat.table)
            if index is not None and index.key == key:
                _indexes[c.cat.table] = _indexes.pop(c.cat.table)  # most recently used last
                return index
        return _build_index(c, key)


def _build_index(c: _Ctx, key: tuple[Any, ...]) -> _SearchIndex:
    columns = search_columns(c.cat)
    numeric = [f.column for f in c.numeric_fields]
    wanted = list(dict.fromkeys([PART_NUMBER, *columns, *numeric]))
    with core.read() as conn:
        rows = conn.execute(select(*[c.table.c[col] for col in wanted])).all()
    position = {col: i for i, col in enumerate(wanted)}
    text_at = [position[col] for col in columns]
    index = _SearchIndex(
        key=key,
        pns=[str(r[0]) for r in rows],
        blobs=[" ".join(str(r[i]) if r[i] is not None else "" for i in text_at).casefold() for r in rows],
        numbers={},
        raw={col: [r[position[col]] for r in rows] for col in numeric},
    )
    with _index_lock:
        _indexes[c.cat.table] = index
        while len(_indexes) > _INDEX_TABLES:
            _indexes.pop(next(iter(_indexes)))
    return index


def _index_hits(c: _Ctx, tokens: Sequence[str]) -> frozenset[str]:
    """Part numbers matching every token (same rules as :func:`_sql_token`), from the search index."""
    index = _search_index(c)
    selected = range(len(index.pns))
    for token in tokens:
        needle = token.casefold()
        targets = [(index.values(f), n) for f, n in _token_targets(c, token)]
        selected = [i for i in selected if needle in index.blobs[i] or any(
            (v := values[i]) is not None and abs(v - n) <= abs(n) * 1e-9 for values, n in targets)]
    return frozenset(index.pns[i] for i in selected)


def clear_search_index() -> None:
    """Forget the search indexes (tests)."""
    with _index_lock:
        _indexes.clear()


def query_parts(
    table: str,
    *,
    search: str | None = None,
    filters: Sequence[PartFilter | Mapping[str, Any]] | None = None,
    sort: str | Sequence[SortSpec | Mapping[str, Any] | str] | None = None,
    offset: int = 0,
    limit: int | None = 200,
) -> tuple[list[dict[str, str | None]], int]:
    """Search, filter, sort and page the parts of a category. Returns ``(rows, total)``.

    * ``search``: tokens are ANDed; each token matches any column (case-insensitive)
      or – on quantity/int fields – the engineering value (``10k`` finds ``10kΩ``).
    * ``filters``: :class:`PartFilter` items (``lt/gt`` on quantity fields compare values).
    * ``sort``: ``"Resistance,-Tolerance"`` or :class:`SortSpec` items (quantity-aware,
      empty values last); ``Part Number`` is the final tie breaker.
    """
    cat = categories.get_category(table)
    c = _Ctx(cat)
    conditions = [_coerce_filter(x) for x in (filters or [])]
    for cond in conditions:
        c.field(cond.column)
    specs = _coerce_sort(sort)
    for spec in specs:
        c.field(spec.column)
    tokens = search_tokens(search)
    offset = max(0, int(offset or 0))
    page_size = None if limit is None or int(limit) <= 0 else int(limit)
    if core.sql_functions_enabled():
        return _sql_query(c, conditions, tokens, specs, offset, page_size)
    # Python fallback (PostgreSQL): push text-only predicates down, evaluate the rest here
    pushed = _sql_where(c, conditions, tokens, numeric_ok=False)
    stmt = select(c.table)
    if pushed:
        stmt = stmt.where(and_(*pushed))
    with core.read() as conn:
        candidates = [_clean_row(r) for r in conn.execute(stmt).mappings()]
    predicates = [_py_condition(c, x) for x in conditions] + [_py_token(c, t) for t in tokens]
    matched = [r for r in candidates if all(p(r) for p in predicates)]
    _py_sort(c, matched, [*specs, SortSpec(column=PART_NUMBER)])
    total = len(matched)
    end = offset + page_size if page_size is not None else None
    return matched[offset:end], total


def _sql_query(c: _Ctx, conditions: Sequence[PartFilter], tokens: Sequence[str], specs: Sequence[SortSpec],
               offset: int, page_size: int | None) -> tuple[list[dict[str, str | None]], int]:
    """SQLite: search through the index, filters and sort in SQL – one statement for page and total."""
    pn_column = c.table.c[PART_NUMBER]
    where = _sql_where(c, conditions, [], numeric_ok=True)
    hit_id: int | None = None
    if tokens:
        hits = _index_hits(c, tokens)
        if not hits:
            return [], 0
        if not where and not specs:  # default order: sort the hits here, read only the page
            ordered = sorted(hits, key=lambda pn: (pn.casefold(), pn))
            page = ordered[offset: offset + page_size if page_size is not None else None]
            if not page:
                return [], len(ordered)
            with core.read() as conn:
                found: dict[str, dict[str, str | None]] = {}
                for chunk in _chunks(page):
                    for r in conn.execute(select(c.table).where(pn_column.in_(list(chunk)))).mappings():
                        clean = _clean_row(r)
                        found[str(clean[PART_NUMBER])] = clean
            return [found[pn] for pn in page if pn in found], len(ordered)
        hit_id = core.register_hits(hits)
        where.append(func.pf_hit(literal(hit_id), pn_column) == 1)
    try:
        if not where:  # whole category: counting the table is cheaper than a window over every row
            stmt = select(c.table).order_by(*_sql_order(c, specs)).offset(offset)
            if page_size is not None:
                stmt = stmt.limit(page_size)
            with core.read() as conn:
                total = int(conn.execute(select(func.count()).select_from(c.table)).scalar_one())
                rows = [_clean_row(r) for r in conn.execute(stmt).mappings()]
            return rows, total
        # one scan: the page and – as window function over all hits – their number
        stmt = select(c.table, func.count().over().label(_TOTAL_LABEL)).where(and_(*where))
        stmt = stmt.order_by(*_sql_order(c, specs)).offset(offset)
        if page_size is not None:
            stmt = stmt.limit(page_size)
        with core.read() as conn:
            raw = conn.execute(stmt).mappings().all()
            if raw:
                total = int(raw[0][_TOTAL_LABEL])
            elif offset:  # a page behind the last hit: count separately
                total = int(conn.execute(select(func.count()).select_from(c.table).where(and_(*where))).scalar_one())
            else:
                total = 0
        return [_clean_row({k: v for k, v in r.items() if k != _TOTAL_LABEL}) for r in raw], total
    finally:
        if hit_id is not None:
            core.release_hits(hit_id)


def _sql_where(c: _Ctx, conditions: Sequence[PartFilter], tokens: Sequence[str], *,
               numeric_ok: bool) -> list[ColumnElement[bool]]:
    where = [e for e in (_sql_condition(c, x, numeric_ok=numeric_ok) for x in conditions) if e is not None]
    where += [e for e in (_sql_token(c, t, numeric_ok=numeric_ok) for t in tokens) if e is not None]
    return where


def matching_part_numbers(
    table: str,
    *,
    search: str | None = None,
    filters: Sequence[PartFilter | Mapping[str, Any]] | None = None,
) -> list[str]:
    """Stored part numbers of all parts matching ``search`` and ``filters`` – exactly the rows
    :func:`query_parts` returns (bulk changes by filter), sorted by part number."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    conditions = [_coerce_filter(x) for x in (filters or [])]
    for cond in conditions:
        c.field(cond.column)
    tokens = search_tokens(search)
    if not core.sql_functions_enabled():
        rows, _ = query_parts(table, search=search, filters=conditions, limit=None)
        return [str(r[PART_NUMBER]) for r in rows]
    pn = c.table.c[PART_NUMBER]
    hits = _index_hits(c, tokens) if tokens else None  # the search index of query_parts: the same hits
    if hits is not None and not conditions:
        return sorted(hits, key=lambda value: (value.casefold(), value))
    if hits is not None and not hits:
        return []
    stmt = select(pn)
    where = _sql_where(c, conditions, [], numeric_ok=True)
    hit_id = core.register_hits(hits) if hits is not None else None
    if hit_id is not None:
        where.append(func.pf_hit(literal(hit_id), pn) == 1)
    if where:
        stmt = stmt.where(and_(*where))
    stmt = stmt.order_by(_sql_fold(pn).asc(), pn.asc())
    try:
        with core.read() as conn:
            return [str(value) for (value,) in conn.execute(stmt)]
    finally:
        if hit_id is not None:
            core.release_hits(hit_id)


def distinct_values(table: str, column: str, *, search: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Distinct values of a column with counts (filter dropdowns, suggestions)."""
    cat = categories.get_category(table)
    c = _Ctx(cat)
    f = c.field(column)
    col = c.table.c[f.column]
    stmt = select(col, func.count()).where(col.is_not(None), col != "").group_by(col)
    if search:
        stmt = stmt.where(_sql_fold(col).like(f"%{_like(_fold(search))}%", escape="\\"))
    with core.read() as conn:
        rows = [(str(v), int(n)) for v, n in conn.execute(stmt)]
    if f.kind in _NUMERIC_KINDS:
        rows.sort(key=lambda item: (numeric_value(item[0], f.unit) is None, numeric_value(item[0], f.unit) or 0.0, item[0]))
    else:
        rows.sort(key=lambda item: (-item[1], item[0].casefold()))
    return [{"value": v, "count": n} for v, n in rows[: max(1, limit)]]


# --------------------------------------------------------------------------- global search & statistics


_QUICK_COLUMNS = (PART_NUMBER, "Manufacturer Part Number", "Description", "Value", "Comment", "Manufacturer")


def _score(token_keys: list[str], q_key: str, hit: Mapping[str, Any]) -> float:
    fold = _fold
    pn = fold(str(hit.get(PART_NUMBER) or ""))
    mpn = fold(str(hit.get("Manufacturer Part Number") or ""))
    if pn == q_key or mpn == q_key:
        return 100.0
    if pn.startswith(q_key) or mpn.startswith(q_key):
        return 90.0 - min(len(pn) - len(q_key), 20) * 0.1
    score = 40.0
    for token in token_keys:
        if token in pn or token in mpn:
            score += 10.0
        elif token in fold(str(hit.get("Value") or "")) or token in fold(str(hit.get("Comment") or "")):
            score += 6.0
        elif token in fold(str(hit.get("Description") or "")):
            score += 3.0
    return score


def _relevance(table: Table, q_key: str) -> ColumnElement[Any]:
    """SQL rank: 0 = exact part number/MPN, 1 = prefix match, 2 = other match. Ordering by
    it before the per-category LIMIT keeps exact hits even among many similar parts."""
    keys = [table.c[col] for col in (PART_NUMBER, "Manufacturer Part Number") if col in table.c]
    exact = or_(*[_sql_fold(col) == q_key for col in keys])
    prefix = or_(*[_sql_fold(col).like(f"{_like(q_key)}%", escape="\\") for col in keys])
    return case((exact, 0), (prefix, 1), else_=2)


def search_all(q: str, limit: int = 20) -> list[dict[str, Any]]:
    """Global quick search over all categories (part number, MPN, description, value).

    Exact part number/MPN matches come first, then prefix matches (shortest first), then
    other matches by score."""
    tokens = search_tokens(q)
    if not tokens:
        return []
    token_keys = [_fold(t) for t in tokens]
    q_key = _fold(" ".join(tokens))
    numeric_ok = core.sql_functions_enabled()
    hits: list[dict[str, Any]] = []
    cats = categories.list_categories(with_counts=False)
    with core.read() as conn:
        for cat in cats:
            table = categories.table_for(cat)
            columns = [table.c[col] for col in _QUICK_COLUMNS if col in table.c]
            pieces: list[ColumnElement[Any]] = [func.coalesce(col, "") for col in columns]
            blob = _sql_fold(reduce(lambda a, b: a + " " + b, pieces))
            value_field = cat.field(cat.value_field) if cat.value_field else None
            where: list[ColumnElement[bool]] = []
            for token in tokens:
                text_match = blob.like(f"%{_like(_fold(token))}%", escape="\\")
                number = _token_number(token, value_field) if (value_field and value_field.kind == "quantity") else None
                if number is not None and numeric_ok and value_field is not None:
                    where.append(or_(text_match, _num_equals(table.c[value_field.column], value_field, number)))
                else:
                    where.append(text_match)
            pn_column = table.c[PART_NUMBER]
            stmt = (
                select(*columns)
                .where(and_(*where))
                .order_by(_relevance(table, q_key), func.length(pn_column), pn_column)
                .limit(max(limit, 1) * 3)
            )
            for row in conn.execute(stmt).mappings():
                clean = _clean_row(row)
                hits.append(
                    {
                        "table": cat.table,
                        "label": cat.label,
                        "color": cat.color,
                        "icon": cat.icon,
                        "part_number": clean.get(PART_NUMBER) or "",
                        "manufacturer": clean.get("Manufacturer"),
                        "mpn": clean.get("Manufacturer Part Number"),
                        "description": clean.get("Description"),
                        "value": clean.get("Value") or clean.get("Comment"),
                        "score": _score(token_keys, q_key, clean),
                    }
                )
    hits.sort(key=lambda h: (-h["score"], len(h["part_number"]), h["part_number"].lower()))
    return hits[: max(limit, 0)]


def stats(*, recent: int = 10) -> dict[str, Any]:
    """Dashboard numbers: parts per category, missing links/datasheets, recent changes."""
    cats = categories.list_categories(with_counts=False)
    per_category: list[dict[str, Any]] = []
    totals = {"parts": 0, "missing_library_ref": 0, "missing_footprint_ref": 0, "missing_datasheet": 0}
    status_counts: dict[str, int] = {}
    recent_parts: list[dict[str, Any]] = []
    with core.read() as conn:
        for cat in cats:
            table = categories.table_for(cat)

            def missing(col: str, _t: Table = table) -> Any:
                if col not in _t.c:
                    return literal(0)
                column = _t.c[col]
                return func.coalesce(func.sum(case((or_(column.is_(None), column == ""), 1), else_=0)), 0)

            row = conn.execute(
                select(func.count(), missing("Library Ref"), missing("Footprint Ref"), missing(DATASHEET_COLUMN)).select_from(table)
            ).one()
            count, no_lib, no_fp, no_ds = (int(v or 0) for v in row)
            per_category.append(
                {
                    "table": cat.table,
                    "label": cat.label,
                    "icon": cat.icon,
                    "color": cat.color,
                    "count": count,
                    "missing_library_ref": no_lib,
                    "missing_footprint_ref": no_fp,
                    "missing_datasheet": no_ds,
                }
            )
            totals["parts"] += count
            totals["missing_library_ref"] += no_lib
            totals["missing_footprint_ref"] += no_fp
            totals["missing_datasheet"] += no_ds
            if "PF Status" in table.c:
                for status, n in conn.execute(select(table.c["PF Status"], func.count()).group_by(table.c["PF Status"])):
                    key = str(status) if status else "Ohne Status"
                    status_counts[key] = status_counts.get(key, 0) + int(n)
            if "PF Modified" in table.c and count:
                cols = [table.c[col] for col in (PART_NUMBER, "Description", "Value", "PF Modified", "PF Author") if col in table.c]
                stmt = select(*cols).where(table.c["PF Modified"].is_not(None)).order_by(table.c["PF Modified"].desc()).limit(recent)
                for item in conn.execute(stmt).mappings():
                    clean = _clean_row(item)
                    recent_parts.append(
                        {
                            "table": cat.table,
                            "label": cat.label,
                            "color": cat.color,
                            "part_number": clean.get(PART_NUMBER),
                            "description": clean.get("Description"),
                            "value": clean.get("Value"),
                            "modified": clean.get("PF Modified"),
                            "author": clean.get("PF Author"),
                        }
                    )
    recent_parts.sort(key=lambda p: str(p.get("modified") or ""), reverse=True)
    reg = registry.counts()
    return {
        "total_parts": totals["parts"],
        "category_count": len(cats),
        "categories": per_category,
        "missing": {
            "library_ref": totals["missing_library_ref"],
            "footprint_ref": totals["missing_footprint_ref"],
            "datasheet": totals["missing_datasheet"],
        },
        "status_counts": status_counts,
        "recent_parts": recent_parts[:recent],
        "recent_changes": [e.model_dump() for e in audit.recent(15)],
        "symbols": reg["symbols"],
        "footprints": reg["footprints"],
        "datasheets": reg["datasheets"],
    }
