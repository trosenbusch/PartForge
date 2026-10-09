"""Registry of the symbols, footprints and datasheets PartForge knows about.

``pf_symbols`` / ``pf_footprints`` map a ``Library Ref`` / ``Footprint Ref`` name to its
library file (workspace-relative), its geometry spec (JSON) and a sync status
(``ok|pending|missing|error``). Usage counts come from scanning ``Library Ref`` and
``Footprint Ref`` / ``Footprint Ref 2`` (… ``n``) of all category tables.

Specs are large (up to 160 KB of JSON, ~180 KB each as models): lists read them only when asked
(``with_spec``) and can be narrowed to ``names`` or one ``library`` in SQL; :func:`content_hashes`
gives the hash of every stored spec text without parsing any. Records read with their spec carry
``content_hash`` (sha256 of the stored spec text). Single reads (:func:`get_symbol`,
:func:`get_footprint`) complete the name record of specs saved by older versions
(``symbols.with_name_record`` / ``footprints.with_name_record``), so "Neu generieren" reproduces a
custom name for them as well.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterable
from typing import Any, Literal, cast

from pydantic import ValidationError
from sqlalchemy import Connection, delete, func, insert, select, update

from ..geometry.model import FootprintSpec, SymbolSpec
from . import categories, core
from .errors import NotFoundError
from .models import DatasheetRecord, FootprintRecord, RecordStatus, SymbolRecord
from .schema import now_iso, pf_datasheets, pf_footprints, pf_symbols

log = logging.getLogger(__name__)

__all__ = [
    "content_hashes",
    "delete_datasheet",
    "delete_footprint",
    "delete_symbol",
    "footprint_library_map",
    "footprint_usage",
    "get_datasheet",
    "get_footprint",
    "get_symbol",
    "list_datasheets",
    "list_footprints",
    "list_symbols",
    "set_footprint_status",
    "set_symbol_status",
    "symbol_library_map",
    "symbol_usage",
    "upsert_datasheet",
    "upsert_footprint",
    "upsert_footprints",
    "upsert_symbol",
    "upsert_symbols",
]

_FOOTPRINT_REF_RE = re.compile(r"^Footprint Ref( \d+)?$", re.IGNORECASE)
_STATUSES = ("ok", "pending", "missing", "error")


class RecordNotFound(NotFoundError):
    def __init__(self, kind: str, name: str) -> None:
        super().__init__(f"{kind} „{name}“ ist nicht registriert.")
        self.name = name


# --------------------------------------------------------------------------- usage


def _usage(column_matches: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    cats = categories.list_categories(with_counts=False)
    with core.read() as conn:
        for cat in cats:
            table = categories.table_for(cat)
            for column in table.columns:
                if not column_matches(column.name):
                    continue
                stmt = (
                    select(column, func.count())
                    .where(column.is_not(None), column != "")
                    .group_by(column)
                )
                for name, count in conn.execute(stmt):
                    counts[str(name)] = counts.get(str(name), 0) + int(count)
    return counts


def symbol_usage() -> dict[str, int]:
    """``{Library Ref: number of parts}`` over all category tables."""
    return _usage(lambda name: name.casefold() == "library ref")


def footprint_usage() -> dict[str, int]:
    """``{Footprint Ref: number of references}`` (``Footprint Ref`` and ``Footprint Ref n``)."""
    return _usage(lambda name: bool(_FOOTPRINT_REF_RE.match(name)))


def _ci_usage(counts: dict[str, int]) -> dict[str, int]:
    folded: dict[str, int] = {}
    for name, count in counts.items():
        key = name.casefold()
        folded[key] = folded.get(key, 0) + count
    return folded


# --------------------------------------------------------------------------- converters


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def spec_hash(raw: str | None) -> str | None:
    """sha256 (hex) of a stored spec text (``None`` without geometry)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None


def _raw_spec(row: Any) -> str | None:
    try:
        return row["spec"]
    except (KeyError, IndexError):  # light row without the spec column
        return None


def _symbol_from_row(row: Any, *, with_spec: bool, usage: dict[str, int] | None) -> SymbolRecord:
    spec: SymbolSpec | None = None
    raw = _raw_spec(row) if with_spec else None
    if raw:
        try:
            spec = SymbolSpec.model_validate_json(raw)
        except ValidationError:
            log.warning("Symbol %s: gespeicherte Geometrie ist ungültig und wird ignoriert", row["name"])
    status = cast(RecordStatus, row["status"] if row["status"] in _STATUSES else "pending")
    return SymbolRecord(
        name=row["name"],
        library=row["library"] or "",
        source=row["source"] or "generated",
        spec=spec,
        pin_count=int(row["pin_count"] or 0),
        part_count=int(row["part_count"] or 1),
        kind=row["kind"],
        status=status,
        status_message=row["status_message"],
        updated=row["updated"],
        usage=(usage or {}).get(str(row["name"]).casefold(), 0),
        content_hash=spec_hash(raw),
    )


def _footprint_from_row(row: Any, *, with_spec: bool, usage: dict[str, int] | None) -> FootprintRecord:
    spec: FootprintSpec | None = None
    raw = _raw_spec(row) if with_spec else None
    if raw:
        try:
            spec = FootprintSpec.model_validate_json(raw)
        except ValidationError:
            log.warning("Footprint %s: gespeicherte Geometrie ist ungültig und wird ignoriert", row["name"])
    status = cast(RecordStatus, row["status"] if row["status"] in _STATUSES else "pending")
    return FootprintRecord(
        name=row["name"],
        library=row["library"] or "",
        source=row["source"] or "generated",
        spec=spec,
        family=row["family"],
        ipc_name=row["ipc_name"],
        pad_count=int(row["pad_count"] or 0),
        height=row["height"],
        step_file=row["step_file"],
        status=status,
        status_message=row["status_message"],
        updated=row["updated"],
        usage=(usage or {}).get(str(row["name"]).casefold(), 0),
        content_hash=spec_hash(raw),
    )


def _datasheet_from_row(row: Any) -> DatasheetRecord:
    extraction = _load_json(row["extraction"], None)
    return DatasheetRecord(
        id=row["id"],
        file=row["file"],
        original_name=row["original_name"],
        title=row["title"],
        manufacturer=row["manufacturer"],
        mpns=[str(m) for m in _load_json(row["mpns"], [])],
        page_count=int(row["page_count"] or 0),
        text_pages=[int(p) for p in _load_json(row["text_pages"], [])],
        extraction=extraction if isinstance(extraction, dict) else None,
        created=row["created"],
    )


def _find_name(conn: Connection, table: Any, name: str) -> str | None:
    """Stored spelling of a name (exact match first, then case-insensitive)."""
    exact = conn.execute(select(table.c.name).where(table.c.name == name)).scalar_one_or_none()
    if exact is not None:
        return str(exact)
    folded = conn.execute(select(table.c.name).where(func.lower(table.c.name) == name.lower()).limit(1)).scalar_one_or_none()
    return str(folded) if folded is not None else None


# --------------------------------------------------------------------------- symbols


def _symbol_values(rec: SymbolRecord) -> dict[str, Any]:
    pin_count = rec.pin_count
    part_count = rec.part_count
    if rec.spec is not None:
        pin_count = pin_count or len(rec.spec.pins)
        part_count = rec.spec.part_count or part_count
    return {
        "library": rec.library or "",
        "source": rec.source,
        "spec": rec.spec.model_dump_json() if rec.spec is not None else None,
        "pin_count": int(pin_count or 0),
        "part_count": int(part_count or 1),
        "kind": rec.kind,
        "status": rec.status,
        "status_message": rec.status_message,
    }


def _list_statement(table: Any, *, with_spec: bool, status: Any, source: str | None, names: Iterable[str] | None,
                    library: str | None) -> Any:
    """SELECT of registry rows: without the spec column unless ``with_spec``; filters in SQL."""
    columns = list(table.c) if with_spec else [c for c in table.c if c.name != "spec"]
    stmt = select(*columns).order_by(table.c.name)
    if status is not None:
        wanted = [status] if isinstance(status, str) else list(status)
        stmt = stmt.where(table.c.status.in_(wanted))
    if source:
        stmt = stmt.where(table.c.source == source)
    if library is not None:
        stmt = stmt.where(func.lower(table.c.library) == library.replace("/", "\\").lower())
    if names is not None:
        stmt = stmt.where(func.lower(table.c.name).in_(sorted({n.lower() for n in names if n})))
    return stmt


def _fetch(stmt: Any) -> list[Any]:
    with core.read() as conn:
        return list(conn.execute(stmt).mappings())


def content_hashes(kind: Literal["symbol", "footprint"], names: Iterable[str] | None = None) -> dict[str, str | None]:
    """``{casefolded name: sha256 of the stored spec text}`` (``None`` = no geometry) – reads the texts, never
    parses them (cheap for long lists). ``names`` narrows it."""
    table = pf_symbols if kind == "symbol" else pf_footprints
    stmt = select(table.c.name, table.c.spec)
    if names is not None:
        stmt = stmt.where(func.lower(table.c.name).in_(sorted({n.lower() for n in names if n})))
    with core.read() as conn:
        return {str(n).casefold(): spec_hash(raw) for n, raw in conn.execute(stmt)}


def _with_name_record(rec: Any) -> Any:
    """Complete the name record of a spec saved by an older version (no ``default_name`` resp. ``names``)."""
    spec = rec.spec
    gen = getattr(spec, "generator", None) if spec is not None else None
    if not isinstance(gen, dict) or not gen:
        return rec
    try:
        if isinstance(spec, SymbolSpec):
            if "default_name" in gen:
                return rec
            from ..symbols import with_name_record as symbol_name_record

            updated = symbol_name_record(spec)
        else:
            if "names" in gen:
                return rec
            from ..footprints import with_name_record as footprint_name_record

            updated = footprint_name_record(spec)
    except Exception:  # noqa: BLE001 - never fail a read for this
        log.debug("Namensvermerk von %s nicht ergänzt", rec.name, exc_info=True)
        return rec
    return rec if updated is spec else rec.model_copy(update={"spec": updated})


def _upsert(conn: Connection, table: Any, name: str, values: dict[str, Any]) -> str:
    stored = _find_name(conn, table, name)
    now = now_iso()
    if stored is None:
        conn.execute(insert(table).values(name=name, created=now, updated=now, **values))
        return name
    conn.execute(update(table).where(table.c.name == stored).values(updated=now, **values))
    return stored


def list_symbols(
    *,
    status: RecordStatus | Iterable[RecordStatus] | None = None,
    source: str | None = None,
    with_spec: bool = True,
    with_usage: bool = True,
    names: Iterable[str] | None = None,
    library: str | None = None,
) -> list[SymbolRecord]:
    """Registered symbols (optionally filtered), sorted by name; ``usage`` filled (``with_usage``).

    ``with_spec=False`` reads no spec text at all (light list, ``content_hash`` stays ``None``); ``names``
    (case-insensitive) and ``library`` (workspace-relative path, case-insensitive) filter in SQL."""
    stmt = _list_statement(pf_symbols, with_spec=with_spec, status=status, source=source, names=names, library=library)
    rows = _fetch(stmt)
    usage = _ci_usage(symbol_usage()) if with_usage else None
    return [_symbol_from_row(r, with_spec=with_spec, usage=usage) for r in rows]


def get_symbol(name: str, *, with_usage: bool = True) -> SymbolRecord | None:
    """The symbol registered under this name (case-insensitive) or None (``with_usage=False``: ``usage``
    stays 0 – no scan of the category tables, e.g. for thumbnails). The spec of an older version gets its
    name record (``symbols.with_name_record``)."""
    with core.read() as conn:
        stored = _find_name(conn, pf_symbols, name)
        if stored is None:
            return None
        row = conn.execute(select(pf_symbols).where(pf_symbols.c.name == stored)).mappings().one()
    usage = _ci_usage(symbol_usage()) if with_usage else None
    return _with_name_record(_symbol_from_row(row, with_spec=True, usage=usage))


def upsert_symbol(rec: SymbolRecord) -> SymbolRecord:
    """Insert or update a symbol record (``updated`` is set automatically)."""
    with core.connect() as conn:
        stored = _upsert(conn, pf_symbols, rec.name, _symbol_values(rec))
    result = get_symbol(stored)
    assert result is not None
    return result


def upsert_symbols(records: Iterable[SymbolRecord]) -> list[SymbolRecord]:
    """Batch variant of :func:`upsert_symbol` (one transaction)."""
    names: list[str] = []
    with core.connect() as conn:
        for rec in records:
            names.append(_upsert(conn, pf_symbols, rec.name, _symbol_values(rec)))
    return list_symbols(names=names) if names else []  # only these – never every spec of the registry


def delete_symbol(name: str) -> bool:
    """Remove a symbol from the registry (the SchLib file is not touched)."""
    with core.connect() as conn:
        stored = _find_name(conn, pf_symbols, name)
        if stored is None:
            return False
        conn.execute(delete(pf_symbols).where(pf_symbols.c.name == stored))
    return True


def set_symbol_status(name: str, status: RecordStatus, message: str | None = None) -> SymbolRecord:
    """Set the sync status; raises :class:`KeyError` if the symbol is not registered."""
    if status not in _STATUSES:
        raise ValueError(f"Ungültiger Status „{status}“.")
    with core.connect() as conn:
        stored = _find_name(conn, pf_symbols, name)
        if stored is None:
            raise RecordNotFound("Symbol", name)
        conn.execute(
            update(pf_symbols).where(pf_symbols.c.name == stored).values(status=status, status_message=message, updated=now_iso())
        )
    result = get_symbol(stored)
    assert result is not None
    return result


def symbol_library_map() -> dict[str, str]:
    """``{name.casefold(): library}`` of all symbols with a library (auto-fill of Library Path)."""
    with core.read() as conn:
        rows = conn.execute(select(pf_symbols.c.name, pf_symbols.c.library)).all()
    return {str(n).casefold(): str(lib) for n, lib in rows if lib}


# --------------------------------------------------------------------------- footprints


def _footprint_values(rec: FootprintRecord) -> dict[str, Any]:
    family, ipc_name, pad_count, height = rec.family, rec.ipc_name, rec.pad_count, rec.height
    if rec.spec is not None:
        family = family or rec.spec.family or None
        ipc_name = ipc_name or rec.spec.ipc_name
        pad_count = pad_count or len(rec.spec.pads)
        height = height if height is not None else rec.spec.height
    return {
        "library": rec.library or "",
        "source": rec.source,
        "spec": rec.spec.model_dump_json() if rec.spec is not None else None,
        "family": family,
        "ipc_name": ipc_name,
        "pad_count": int(pad_count or 0),
        "height": height,
        "step_file": rec.step_file,
        "status": rec.status,
        "status_message": rec.status_message,
    }


def list_footprints(
    *,
    status: RecordStatus | Iterable[RecordStatus] | None = None,
    source: str | None = None,
    family: str | None = None,
    with_spec: bool = True,
    with_usage: bool = True,
    names: Iterable[str] | None = None,
    library: str | None = None,
) -> list[FootprintRecord]:
    """Registered footprints (optionally filtered), sorted by name; ``usage`` filled (``with_usage``).

    ``with_spec``, ``names`` and ``library`` as in :func:`list_symbols`."""
    stmt = _list_statement(pf_footprints, with_spec=with_spec, status=status, source=source, names=names,
                           library=library)
    if family:
        stmt = stmt.where(pf_footprints.c.family == family)
    rows = _fetch(stmt)
    usage = _ci_usage(footprint_usage()) if with_usage else None
    return [_footprint_from_row(r, with_spec=with_spec, usage=usage) for r in rows]


def get_footprint(name: str, *, with_usage: bool = True) -> FootprintRecord | None:
    """The footprint registered under this name (case-insensitive) or None (``with_usage=False``: ``usage``
    stays 0 – no scan of the category tables). The spec of an older version gets its name record
    (``footprints.with_name_record``)."""
    with core.read() as conn:
        stored = _find_name(conn, pf_footprints, name)
        if stored is None:
            return None
        row = conn.execute(select(pf_footprints).where(pf_footprints.c.name == stored)).mappings().one()
    usage = _ci_usage(footprint_usage()) if with_usage else None
    return _with_name_record(_footprint_from_row(row, with_spec=True, usage=usage))


def upsert_footprint(rec: FootprintRecord) -> FootprintRecord:
    """Insert or update a footprint record (``updated`` is set automatically)."""
    with core.connect() as conn:
        stored = _upsert(conn, pf_footprints, rec.name, _footprint_values(rec))
    result = get_footprint(stored)
    assert result is not None
    return result


def upsert_footprints(records: Iterable[FootprintRecord]) -> list[FootprintRecord]:
    """Batch variant of :func:`upsert_footprint` (one transaction)."""
    names: list[str] = []
    with core.connect() as conn:
        for rec in records:
            names.append(_upsert(conn, pf_footprints, rec.name, _footprint_values(rec)))
    return list_footprints(names=names) if names else []  # only these – never every spec of the registry


def delete_footprint(name: str) -> bool:
    """Remove a footprint from the registry (the PcbLib file is not touched)."""
    with core.connect() as conn:
        stored = _find_name(conn, pf_footprints, name)
        if stored is None:
            return False
        conn.execute(delete(pf_footprints).where(pf_footprints.c.name == stored))
    return True


def set_footprint_status(name: str, status: RecordStatus, message: str | None = None) -> FootprintRecord:
    """Set the sync status; raises :class:`KeyError` if the footprint is not registered."""
    if status not in _STATUSES:
        raise ValueError(f"Ungültiger Status „{status}“.")
    with core.connect() as conn:
        stored = _find_name(conn, pf_footprints, name)
        if stored is None:
            raise RecordNotFound("Footprint", name)
        conn.execute(
            update(pf_footprints)
            .where(pf_footprints.c.name == stored)
            .values(status=status, status_message=message, updated=now_iso())
        )
    result = get_footprint(stored)
    assert result is not None
    return result


def footprint_library_map() -> dict[str, str]:
    """``{name.casefold(): library}`` of all footprints with a library (auto-fill of Footprint Path)."""
    with core.read() as conn:
        rows = conn.execute(select(pf_footprints.c.name, pf_footprints.c.library)).all()
    return {str(n).casefold(): str(lib) for n, lib in rows if lib}


# --------------------------------------------------------------------------- datasheets


def list_datasheets() -> list[DatasheetRecord]:
    with core.read() as conn:
        rows = list(conn.execute(select(pf_datasheets).order_by(pf_datasheets.c.created.desc(), pf_datasheets.c.id)).mappings())
    return [_datasheet_from_row(r) for r in rows]


def get_datasheet(datasheet_id: str) -> DatasheetRecord | None:
    with core.read() as conn:
        row = conn.execute(select(pf_datasheets).where(pf_datasheets.c.id == datasheet_id)).mappings().first()
    return _datasheet_from_row(row) if row else None


def upsert_datasheet(rec: DatasheetRecord) -> DatasheetRecord:
    """Insert or update a datasheet record (``created`` is kept from the first insert)."""
    values = {
        "file": rec.file,
        "original_name": rec.original_name,
        "title": rec.title,
        "manufacturer": rec.manufacturer,
        "mpns": json.dumps(list(rec.mpns), ensure_ascii=False),
        "page_count": int(rec.page_count or 0),
        "text_pages": json.dumps([int(p) for p in rec.text_pages]),
        "extraction": json.dumps(rec.extraction, ensure_ascii=False, default=str) if rec.extraction is not None else None,
    }
    with core.connect() as conn:
        exists = conn.execute(select(pf_datasheets.c.id).where(pf_datasheets.c.id == rec.id)).first()
        if exists:
            conn.execute(update(pf_datasheets).where(pf_datasheets.c.id == rec.id).values(**values))
        else:
            conn.execute(insert(pf_datasheets).values(id=rec.id, created=rec.created or now_iso(), **values))
    result = get_datasheet(rec.id)
    assert result is not None
    return result


def delete_datasheet(datasheet_id: str) -> bool:
    """Remove a datasheet record (the PDF file is not touched)."""
    with core.connect() as conn:
        result = conn.execute(delete(pf_datasheets).where(pf_datasheets.c.id == datasheet_id))
    return bool(result.rowcount)


def counts() -> dict[str, Any]:
    """Registry statistics for the dashboard."""
    out: dict[str, Any] = {}
    with core.read() as conn:
        for key, table in (("symbols", pf_symbols), ("footprints", pf_footprints)):
            by_status = {s: 0 for s in _STATUSES}
            for status, count in conn.execute(select(table.c.status, func.count()).group_by(table.c.status)):
                by_status[str(status)] = by_status.get(str(status), 0) + int(count)
            out[key] = {"total": sum(by_status.values()), "by_status": by_status}
        out["datasheets"] = int(conn.execute(select(func.count()).select_from(pf_datasheets)).scalar_one())
    return out
