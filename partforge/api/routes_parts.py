"""API routes: parts, global search, statistics, health check, import/export, backups, saved views.

Part numbers may contain ``/``, ``#``, ``,`` or spaces: item routes use ``{pn:path}``
(clients percent-encode the part number, e.g. ``LTC3128EUFD%23PBF``).

Bulk changes (``bulk-update``, ``DELETE``/``delete``) take either ``part_numbers`` or a selection by
``search``/``filters`` (same rules as ``/query``); ``POST /parts/{table}/count`` tells the client how
many parts a selection hits, and ``expected_count`` makes the change refuse (409 ``selection_changed``)
when the selection changed since. A selection without search and filters (= the whole category)
requires ``expected_count``. Deleting answers the deleted part numbers; ``POST /parts/{table}/restore``
brings them back from the change history (undo). Bulk updates and regenerated texts of more than 20 parts
take an automatic backup first and answer ``audit_ids``; ``POST /parts/{table}/restore-updates`` sets the
old values back (undo, parts changed again since are left alone).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from ..db import backup, categories, core, health, parts, views
from ..db.audit import resolve_author
from ..db.errors import FieldNotFound
from ..db.models import AuditEntry, BackupInfo, HealthIssue, PartFilter, SavedView, SearchHit, SortSpec
from ..domain.text import plural
from ..importers import spreadsheet
from ..jobs import LIBRARY_JOB_STOP_TIMEOUT_S, JobContext, LibraryBusy, LibraryChanged, jobs, library_hold, library_switch
from ..workspace import Workspace
from .deps import require_workspace
from .routes_categories import db_errors

log = logging.getLogger(__name__)

router = APIRouter(tags=["parts"], dependencies=[Depends(require_workspace)])

Row = dict[str, str | None]


# --------------------------------------------------------------------------- models


class PartsPage(BaseModel):
    rows: list[Row]
    total: int
    offset: int
    limit: int | None


class PartQueryIn(BaseModel):
    search: str | None = None
    filters: list[PartFilter] = Field(default_factory=list)
    sort: list[SortSpec] = Field(default_factory=list)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=200, ge=0, le=10000, description="0 = alle")


class PartWriteIn(BaseModel):
    values: dict[str, Any]
    allow_incomplete: bool = Field(default=False, description="Leere Pflichtfelder nur als Warnung melden (Entwurf)")


class PartWriteOut(BaseModel):
    part: Row
    warnings: list[str] = Field(default_factory=list)


class PartNumbersIn(BaseModel):
    part_numbers: list[str]


class PartSelectionIn(BaseModel):
    """Which parts: ``part_numbers`` – or (without them) every part matching ``search`` and ``filters``."""

    part_numbers: list[str] | None = Field(default=None, description="Teilenummern (sonst Auswahl über Suche/Filter)")
    search: str | None = Field(default=None, description="Suche wie bei /query (nur ohne part_numbers)")
    filters: list[PartFilter] = Field(default_factory=list, description="Filter wie bei /query (nur ohne part_numbers)")
    expected_count: int | None = Field(
        default=None, ge=0,
        description="Nur bei Auswahl über Suche/Filter: bestätigte Anzahl (aus /count) – weicht die Auswahl inzwischen "
                    "ab, antwortet die Aktion 409 „selection_changed“. Pflicht ohne Suche und Filter (= ganze Kategorie)",
    )


class DeletePartsOut(BaseModel):
    deleted: int
    backup: str | None = None
    part_numbers: list[str] = Field(default_factory=list,
                                    description="Gelöschte Teilenummern – Eingabe für POST /parts/{table}/restore")
    matched: int | None = Field(default=None, description="Teile der Auswahl (bei Auswahl über Suche/Filter)")


class PartsBulkUpdateIn(PartSelectionIn):
    values: dict[str, Any]


class PartsBulkUpdateOut(BaseModel):
    updated: int
    warnings: list[str] = Field(default_factory=list)
    matched: int | None = Field(default=None, description="Teile der Auswahl (bei Auswahl über Suche/Filter)")
    backup: str | None = Field(default=None, description="Automatische Sicherung vor der Änderung (mehr als 20 Bauteile)")
    audit_ids: list[int] = Field(default_factory=list,
                                 description="Einträge der Änderungshistorie – Eingabe für POST /parts/{table}/restore-updates")


class PartsRestoreUpdatesIn(BaseModel):
    audit_ids: list[int] = Field(description="audit_ids aus der Antwort der Massenänderung")


class PartsRestoreUpdatesOut(BaseModel):
    restored: list[str] = Field(default_factory=list, description="Zurückgesetzte Teilenummern")
    parts: list[Row] = Field(default_factory=list, description="Die zurückgesetzten Bauteile")
    conflicts: dict[str, str] = Field(default_factory=dict,
                                      description="Teilenummer -> warum nicht zurückgesetzt (seither geändert, gelöscht)")
    unchanged: list[str] = Field(default_factory=list, description="Schon auf dem alten Stand")
    not_found: list[int] = Field(default_factory=list, description="Unbekannte audit_ids")
    warnings: list[str] = Field(default_factory=list)


class PartsCountIn(BaseModel):
    search: str | None = None
    filters: list[PartFilter] = Field(default_factory=list)
    sample: int = Field(default=20, ge=0, le=500, description="So viele Teilenummern mitliefern")


class PartsCountOut(BaseModel):
    count: int = Field(description="Bauteile der Auswahl – als expected_count an die Massenaktion geben")
    total: int = Field(description="Bauteile der Kategorie")
    whole_category: bool = Field(description="Ohne Suche und Filter: die Aktion betrifft die ganze Kategorie")
    part_numbers: list[str] = Field(default_factory=list, description="Die ersten Teilenummern der Auswahl")


class SelectionChangedDetail(BaseModel):
    code: Literal["selection_changed"] = "selection_changed"
    message: str
    count: int
    expected: int


class SelectionChangedOut(BaseModel):
    detail: SelectionChangedDetail


class PartsRestoreOut(BaseModel):
    restored: list[str] = Field(default_factory=list, description="Wiederhergestellte Teilenummern")
    parts: list[Row] = Field(default_factory=list, description="Die wiederhergestellten Bauteile")
    conflicts: dict[str, str] = Field(default_factory=dict, description="Teilenummer inzwischen wieder vergeben")
    not_found: list[str] = Field(default_factory=list, description="Keine Löschung in der Änderungshistorie")
    warnings: list[str] = Field(default_factory=list)


class PartTemplateIn(BaseModel):
    template: str = Field(description="Vorlage, z. B. „RES {Size} {Resistance} {Tolerance}“")
    values: dict[str, Any] = Field(default_factory=dict, description="Feldwerte (werden wie beim Speichern normalisiert)")


class PartTemplateOut(BaseModel):
    text: str
    fields: list[str] = Field(default_factory=list, description="Verwendete Platzhalter")
    unknown: list[str] = Field(default_factory=list, description="Platzhalter ohne Feld in der Kategorie")


class PartDuplicateIn(BaseModel):
    new_part_number: str = ""


class PartValidateIn(BaseModel):
    values: dict[str, Any]
    part_number: str | None = Field(default=None, description="Bestehendes Bauteil (Änderung) oder leer (neu)")
    allow_incomplete: bool = False


class PartConflict(BaseModel):
    table: str
    part_number: str
    message: str


class PartValidateOut(BaseModel):
    values: Row
    warnings: list[str]
    errors: dict[str, str]
    conflict: PartConflict | None = None
    rendered: dict[str, str]


class PartSmartFillIn(BaseModel):
    text: str


class PartSmartFillOut(BaseModel):
    values: dict[str, str]
    unmatched: list[str]


class PartRenderIn(BaseModel):
    values: dict[str, Any]


class PartRegenerateIn(BaseModel):
    part_numbers: list[str] | None = None
    columns: list[str] = Field(default_factory=lambda: ["Value", "Comment", "Description"])


class RegenerateOut(BaseModel):
    updated: int
    backup: str | None = Field(default=None, description="Automatische Sicherung vor der Änderung (mehr als 20 Bauteile)")
    audit_ids: list[int] = Field(default_factory=list,
                                 description="Einträge der Änderungshistorie – Eingabe für POST /parts/{table}/restore-updates")


class PartDistinctValue(BaseModel):
    value: str
    count: int


class CategoryStat(BaseModel):
    table: str
    label: str
    icon: str | None = None
    color: str | None = None
    count: int
    missing_library_ref: int
    missing_footprint_ref: int
    missing_datasheet: int


class StatsMissing(BaseModel):
    library_ref: int
    footprint_ref: int
    datasheet: int


class RecentPart(BaseModel):
    table: str
    label: str
    color: str | None = None
    part_number: str | None = None
    description: str | None = None
    value: str | None = None
    modified: str | None = None
    author: str | None = None


class StatsRegistry(BaseModel):
    total: int
    by_status: dict[str, int]


class LibraryStatsOut(BaseModel):
    total_parts: int
    category_count: int
    categories: list[CategoryStat]
    missing: StatsMissing
    status_counts: dict[str, int]
    recent_parts: list[RecentPart]
    recent_changes: list[AuditEntry]
    symbols: StatsRegistry
    footprints: StatsRegistry
    datasheets: int


class HealthCheckStat(BaseModel):
    """One check of the data-level report – exact, even when its issues are cut at ``max_per_check``."""

    severity: str = Field(description="error | warning | info (die schwerste der Prüfung)")
    issues: int = Field(description="Befunde dieser Prüfung")
    affected_parts: int = Field(description="Betroffene Bauteile (jedes einmal)")
    part_numbers: list[str] = Field(default_factory=list, description="Die ersten 20 betroffenen Teilenummern")


class HealthReportOut(BaseModel):
    issues: list[HealthIssue]
    summary: dict[str, int]
    counts: dict[str, int]
    total: int
    truncated: bool
    checked_at: str
    checked_parts: int = Field(default=0, description="Geprüfte Bauteile")
    affected_parts: int = Field(default=0, description="Bauteile mit mindestens einem Fehler oder einer Warnung")
    affected_part_numbers: list[str] = Field(
        default_factory=list, description="Alle Bauteile mit Fehler oder Warnung, jedes genau einmal (exakte Quote)")
    checks: dict[str, HealthCheckStat] = Field(default_factory=dict, description="Exakte Zahlen je Prüfung")


class ImportSample(BaseModel):
    part_number: str | None = None
    status: str
    values: dict[str, str | None]


class ImportPreviewOut(BaseModel):
    """Upload/re-preview: file structure, mapping, samples and – with a category – the per-row dry run."""

    token: str
    file_name: str
    table: str | None = None
    sheets: list[str]
    sheet: str | None = None
    headers: list[str]
    header_row: int | None = None
    encoding: str | None = None
    delimiter: str | None = None
    row_count: int
    rows: list[list[str | None]]
    mapping: list[spreadsheet.MappingItem]
    samples: list[ImportSample]
    row_status: list[spreadsheet.ImportRowStatus] = Field(
        default_factory=list, description="Ergebnis je Zeile für die aktuelle Zuordnung (Probelauf, erste n Zeilen)"
    )
    check: spreadsheet.ImportCheck | None = Field(default=None, description="Zusammenfassung des Probelaufs")


class ImportRepreviewIn(BaseModel):
    table: str | None = None
    sheet: str | None = None
    header_row: int | Literal["auto"] | None = "auto"
    mapping: list[spreadsheet.MappingItem] | None = Field(
        default=None, description="Aktuelle Zuordnung (None = Vorschlag); bestimmt samples und row_status"
    )
    mode: Literal["skip", "update", "error"] = "skip"
    defaults: dict[str, Any] = Field(default_factory=dict, description="Feste Werte wie beim Import")
    allow_incomplete: bool = False
    strict: bool = False
    thousands: bool | None = Field(
        default=None, description="Zahlenformat der Quelle für „1,000“: None = mehrdeutig (Warnung), true = "
                                  "Tausendertrennzeichen, false = Dezimalkomma (wie ImportOptions.thousands)")
    check_rows: int = Field(default=spreadsheet.CHECK_ROWS_DEFAULT, ge=0, le=spreadsheet.CHECK_ROWS_MAX,
                            description="So viele Zeilen im Probelauf prüfen")


class ImportJobOut(BaseModel):
    job: dict[str, Any]


class PartExportIn(BaseModel):
    format: Literal["csv", "xlsx"] = "xlsx"
    part_numbers: list[str] | None = None
    columns: list[str] | None = None
    search: str | None = None
    filters: list[PartFilter] = Field(default_factory=list)
    sort: list[SortSpec] = Field(default_factory=list)
    delimiter: str = ";"
    excel_safe: bool = Field(
        default=True, description="CSV: Werte, die Excel als Formel ausführen würde (= + @ - am Anfang, außer Messwerten "
                                  "wie -55°C), mit ' schützen; false = alle Werte unverändert")


class PartExportFileOut(BaseModel):
    path: str
    rel_path: str
    file_name: str
    rows: int
    warnings: list[str] = Field(default_factory=list,
                                description="Hinweise, z. B. in der XLSX-Datei gekürzte Werte (> 32.767 Zeichen)")


class ExportJobOut(BaseModel):
    job: dict[str, Any] = Field(description="JobSnapshot; job.result = {path, rel_path, file_name, rows}")


class BackupCreateIn(BaseModel):
    reason: str = "manuell"


class BackupRestoreOut(BaseModel):
    ok: bool
    restored: str
    job: dict[str, Any] | None = Field(
        default=None, description="Job „Bibliotheken nach dem Wiederherstellen abgleichen“ (kind libraries.scan): "
                                  "prüft die SchLib/PcbLib gegen die wiederhergestellte Registrierung und schreibt "
                                  "fehlende Symbole/Footprints nach")


class SavedViewIn(BaseModel):
    name: str
    table: str | None = None
    search: str | None = None
    filters: list[PartFilter] = Field(default_factory=list)
    sort: list[SortSpec] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)


class SavedViewPatchIn(BaseModel):
    name: str | None = None
    table: str | None = None
    search: str | None = None
    filters: list[PartFilter] | None = None
    sort: list[SortSpec] | None = None
    columns: list[str] | None = None


class ViewDeletedOut(BaseModel):
    deleted: bool


# --------------------------------------------------------------------------- helpers


def _parse_filters(raw: str | None) -> list[PartFilter]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Der Filter ist kein gültiges JSON (Liste von {column, op, value}).") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Der Filter muss eine Liste von {column, op, value} sein.")
    with db_errors():
        return [PartFilter.model_validate(item) for item in data]


def _parse_sort(raw: str | None) -> list[SortSpec] | str | None:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("[") or text.startswith("{"):
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Die Sortierung ist kein gültiges JSON.") from exc
        items = data if isinstance(data, list) else [data]
        with db_errors():
            return [SortSpec.model_validate(item) for item in items]
    return text


def _query(table: str, search: str | None, filters: list[PartFilter], sort: Any, offset: int, limit: int) -> PartsPage:
    with db_errors():
        categories.get_category(table)  # unknown category -> 404
        try:
            rows, total = parts.query_parts(table, search=search, filters=filters, sort=sort, offset=offset,
                                            limit=limit or None)
        except FieldNotFound as exc:  # unknown column in a filter/sort parameter is a bad request
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PartsPage(rows=rows, total=total, offset=offset, limit=limit or None)


def _has_query(search: str | None, filters: list[PartFilter]) -> bool:
    return bool(filters) or bool(search and search.strip())


def _selection(table: str, sel: PartSelectionIn) -> tuple[list[str], int | None]:
    """(part numbers, matched count of a filter selection – None for explicit part numbers)."""
    if sel.part_numbers is not None:
        if _has_query(sel.search, sel.filters):
            raise HTTPException(status_code=400,
                                detail="Bitte entweder Teilenummern oder Suche/Filter angeben, nicht beides.")
        return sel.part_numbers, None
    with db_errors():
        categories.get_category(table)  # unknown category -> 404
        try:
            pns = parts.matching_part_numbers(table, search=sel.search, filters=sel.filters)
        except FieldNotFound as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not _has_query(sel.search, sel.filters) and sel.expected_count is None:
        raise HTTPException(
            status_code=400,
            detail=f"Ohne Suche und Filter betrifft die Aktion alle {len(pns)} Bauteile der Kategorie – bitte die Anzahl "
            "bestätigen (expected_count, siehe /count).",
        )
    if sel.expected_count is not None and sel.expected_count != len(pns):
        detail = SelectionChangedDetail(
            message=f"Die Auswahl umfasst inzwischen {len(pns)} statt {sel.expected_count} Bauteile – bitte erneut "
            "bestätigen.", count=len(pns), expected=sel.expected_count)
        raise HTTPException(status_code=409, detail=detail.model_dump())
    return pns, len(pns)


_SELECTION_RESPONSES: dict[int | str, dict[str, Any]] = {
    409: {"model": SelectionChangedOut, "description": "Die Auswahl hat sich seit /count geändert (selection_changed)"},
}


def _download(content: bytes, file_name: str, media_type: str) -> Response:
    disposition = f"attachment; filename=\"{file_name}\"; filename*=UTF-8''{quote(file_name)}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition,
                                                                      "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- parts


@router.get("/parts/{table}", response_model=PartsPage)
def list_parts(
    table: str,
    search: str | None = None,
    filters: str | None = Query(default=None, description='JSON: [{"column": "Resistance", "op": "gt", "value": "1k"}]'),
    sort: str | None = Query(default=None, description='"Resistance,-Tolerance" oder JSON [{"column": …, "desc": true}]'),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=0, le=10000, description="0 = alle"),
) -> PartsPage:
    """Search/filter/sort/page the parts of a category (quantity-aware: ``10k`` = ``10kΩ``)."""
    return _query(table, search, _parse_filters(filters), _parse_sort(sort), offset, limit)


@router.post("/parts/{table}/query", response_model=PartsPage)
def query_parts(table: str, body: PartQueryIn) -> PartsPage:
    """Same as ``GET /parts/{table}`` with the parameters in the body (long filter lists)."""
    return _query(table, body.search, body.filters, body.sort or None, body.offset, body.limit)


@router.post("/parts/{table}", response_model=PartWriteOut, status_code=201)
def create_part(table: str, body: PartWriteIn) -> PartWriteOut:
    warnings: list[str] = []
    with db_errors():
        part = parts.create_part(table, body.values, warnings=warnings, allow_incomplete=body.allow_incomplete)
    return PartWriteOut(part=part, warnings=warnings)


def _delete(table: str, sel: PartSelectionIn) -> DeletePartsOut:
    part_numbers, matched = _selection(table, sel)
    with db_errors():
        backup_name: str | None = None
        unique = list(dict.fromkeys(p for p in part_numbers if p))
        if len(unique) > parts.AUTO_BACKUP_DELETE_THRESHOLD:
            path = backup.auto_backup(f"vor_loeschen_{len(unique)}_bauteile")
            backup_name = path.name if path else None
        removed: list[str] = []
        deleted = parts.delete_parts(table, unique, backup=False, deleted=removed)
    return DeletePartsOut(deleted=deleted, backup=backup_name, part_numbers=removed, matched=matched)


@router.delete("/parts/{table}", response_model=DeletePartsOut, responses=_SELECTION_RESPONSES)
def delete_parts(table: str, body: PartSelectionIn) -> DeletePartsOut:
    """Delete parts (``{"part_numbers": [...]}`` or a selection ``{search, filters, expected_count}``;
    automatic backup above 20 parts). The answer lists the deleted part numbers for an undo
    (``POST /parts/{table}/restore``)."""
    return _delete(table, body)


@router.post("/parts/{table}/delete", response_model=DeletePartsOut, responses=_SELECTION_RESPONSES)
def delete_parts_post(table: str, body: PartSelectionIn) -> DeletePartsOut:
    """Alias of ``DELETE /parts/{table}`` for clients that cannot send a DELETE body."""
    return _delete(table, body)


@router.post("/parts/{table}/bulk-update", response_model=PartsBulkUpdateOut, responses=_SELECTION_RESPONSES)
def bulk_update(table: str, body: PartsBulkUpdateIn) -> PartsBulkUpdateOut:
    """Set the same values on many parts (``part_numbers`` or a selection by search/filters)."""
    part_numbers, matched = _selection(table, body)
    warnings: list[str] = []
    backups: list[str] = []
    audit_ids: list[int] = []
    with db_errors():
        count = parts.bulk_update(table, part_numbers, body.values, warnings=warnings, backups=backups,
                                  audit_ids=audit_ids)
    return PartsBulkUpdateOut(updated=count, warnings=warnings, matched=matched,
                              backup=backups[0] if backups else None, audit_ids=audit_ids)


@router.post("/parts/{table}/restore-updates", response_model=PartsRestoreUpdatesOut)
def restore_updates(table: str, body: PartsRestoreUpdatesIn) -> PartsRestoreUpdatesOut:
    """Undo of a bulk update or of regenerated texts: the old values come back from the change history
    (``audit_ids`` from the answer). Parts changed again since are left alone (``conflicts``)."""
    with db_errors():
        return PartsRestoreUpdatesOut(**parts.restore_updates(table, body.audit_ids))


@router.post("/parts/{table}/count", response_model=PartsCountOut)
def count_parts(table: str, body: PartsCountIn) -> PartsCountOut:
    """How many parts a selection (search + filters) hits – for the confirmation of a bulk change."""
    with db_errors():
        cat = categories.get_category(table)
        try:
            pns = parts.matching_part_numbers(cat.table, search=body.search, filters=body.filters)
        except FieldNotFound as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _, total = parts.query_parts(cat.table, limit=1)
    return PartsCountOut(count=len(pns), total=total, whole_category=not _has_query(body.search, body.filters),
                         part_numbers=pns[: body.sample])


@router.post("/parts/{table}/restore", response_model=PartsRestoreOut)
def restore_parts(table: str, body: PartNumbersIn) -> PartsRestoreOut:
    """Restore deleted parts from the change history (undo of a delete; part numbers from its answer)."""
    with db_errors():
        return PartsRestoreOut(**parts.restore_parts(table, body.part_numbers))


@router.post("/parts/{table}/validate", response_model=PartValidateOut)
def validate_part(table: str, body: PartValidateIn) -> PartValidateOut:
    """Dry run: normalised values, warnings, errors, conflicts and generated texts (nothing is saved)."""
    with db_errors():
        result = parts.validate_part(table, body.values, pn=body.part_number, allow_incomplete=body.allow_incomplete)
        rendered = parts.render_templates(table, result["values"])
    return PartValidateOut(**result, rendered=rendered)


@router.post("/parts/{table}/render-templates", response_model=dict[str, str])
def render_templates(table: str, body: PartRenderIn) -> dict[str, str]:
    with db_errors():
        return parts.render_templates(table, body.values)


@router.post("/parts/{table}/render-template", response_model=PartTemplateOut)
def render_template(table: str, body: PartTemplateIn) -> PartTemplateOut:
    """Preview of any template for these values (e.g. a description template being edited)."""
    with db_errors():
        return PartTemplateOut(**parts.render_template_text(table, body.template, body.values))


@router.post("/parts/{table}/smart-fill", response_model=PartSmartFillOut)
def smart_fill(table: str, body: PartSmartFillIn) -> PartSmartFillOut:
    """Interpret free text like ``10k 1% 0603 0.1W`` as field values."""
    with db_errors():
        return PartSmartFillOut(**parts.smart_fill(table, body.text))


@router.post("/parts/{table}/regenerate-texts", response_model=RegenerateOut)
def regenerate_texts(table: str, body: PartRegenerateIn) -> RegenerateOut:
    """Re-generate Value/Comment/Description from the templates (overwrites manual texts)."""
    backups: list[str] = []
    audit_ids: list[int] = []
    with db_errors():
        updated = parts.regenerate_texts(table, body.part_numbers, columns=body.columns, backups=backups,
                                         audit_ids=audit_ids)
    return RegenerateOut(updated=updated, backup=backups[0] if backups else None, audit_ids=audit_ids)


@router.get("/parts/{table}/{pn:path}/history", response_model=list[AuditEntry])
def part_history(table: str, pn: str) -> list[dict[str, Any]]:
    with db_errors():
        entries = parts.history(table, pn)
        if not entries and parts.get_part(table, pn) is None:
            raise HTTPException(status_code=404, detail=f"Bauteil „{pn}“ wurde in der Kategorie „{table}“ nicht gefunden.")
        return entries


@router.post("/parts/{table}/{pn:path}/duplicate", response_model=PartWriteOut, status_code=201)
def duplicate_part(table: str, pn: str, body: PartDuplicateIn) -> PartWriteOut:
    with db_errors():
        part = parts.duplicate_part(table, pn, body.new_part_number)
    return PartWriteOut(part=part)


@router.get("/parts/{table}/{pn:path}", response_model=Row)
def get_part(table: str, pn: str) -> Row:
    with db_errors():
        part = parts.get_part(table, pn)
    if part is None:
        raise HTTPException(status_code=404, detail=f"Bauteil „{pn}“ wurde in der Kategorie „{table}“ nicht gefunden.")
    return part


@router.patch("/parts/{table}/{pn:path}", response_model=PartWriteOut)
def update_part(table: str, pn: str, body: PartWriteIn) -> PartWriteOut:
    warnings: list[str] = []
    with db_errors():
        part = parts.update_part(table, pn, body.values, warnings=warnings)
    return PartWriteOut(part=part, warnings=warnings)


@router.get("/distinct/{table}", response_model=list[PartDistinctValue])
def distinct_values(
    table: str,
    column: str = Query(description="Spaltenname"),
    search: str | None = None,
    limit: int = Query(default=200, ge=1, le=5000),
) -> list[dict[str, Any]]:
    """Distinct values of a column with counts (filter dropdowns)."""
    with db_errors():
        return parts.distinct_values(table, column, search=search, limit=limit)


# --------------------------------------------------------------------------- search, stats, health


@router.get("/search", response_model=list[SearchHit])
def search(q: str = "", limit: int = Query(default=20, ge=1, le=200)) -> list[dict[str, Any]]:
    """Global quick search (command palette): part number, MPN, description, value."""
    with db_errors():
        return parts.search_all(q, limit=limit)


@router.get("/stats", response_model=LibraryStatsOut)
def stats() -> dict[str, Any]:
    with db_errors():
        return parts.stats()


@router.get("/health-check", response_model=HealthReportOut)
def health_check(max_per_check: int = Query(default=200, ge=1, le=100000)) -> dict[str, Any]:
    """Data quality report ("Bibliothek prüfen"). The scan of the database is cached until the database
    changes, so repeated requests (dashboard, Altium page) answer at once; the first one of a large library
    takes seconds – ``POST /health-check/job`` runs it as a job."""
    with db_errors():
        return health.health_report(max_per_check=max_per_check)


HEALTH_JOB_KIND = "health-check"  # only reads: no hold, ends "cancelled" when its library is switched


class HealthJobIn(BaseModel):
    max_per_check: int = Field(default=200, ge=1, le=100000, description="Befunde je Prüfung in issues")


class HealthJobOut(BaseModel):
    job: dict[str, Any] = Field(description="JobSnapshot; job.result = Bericht wie GET /health-check plus message")


def health_message(report: Mapping[str, Any]) -> str:
    """Final message of the data check: „Daten geprüft: 1.250 Bauteile – 2 Fehler, 14 Warnungen“."""
    counts = report.get("counts") or {}
    errors, warnings = int(counts.get("error") or 0), int(counts.get("warning") or 0)
    head = f"Daten geprüft: {plural(int(report.get('checked_parts') or 0), 'Bauteil', 'Bauteile')}"
    found = [plural(errors, "Fehler", "Fehler")] if errors else []
    if warnings:
        found.append(plural(warnings, "Warnung", "Warnungen"))
    return f"{head} – {', '.join(found)}" if found else f"{head} – keine Fehler oder Warnungen"


def _health_job(ctx: JobContext, library: Path, max_per_check: int) -> dict[str, Any]:
    """Job "Daten prüfen": the report of the library at ``library`` (never of a library opened meanwhile)."""
    from ..jobs import open_library

    ctx.progress(0.05, "Bauteile, Werte und Verweise werden geprüft …")
    ws = open_library(library)
    if ws is None:
        raise LibraryChanged(library)
    report = health.health_report(max_per_check=max_per_check)
    if open_library(library) is not ws:  # switched while checking: the report may describe another library
        raise LibraryChanged(library)
    message = health_message(report)
    ctx.progress(1.0, message)
    return {**report, "message": message}


@router.post("/health-check/job", response_model=HealthJobOut)
def health_check_job(body: HealthJobIn | None = None, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """``GET /health-check`` as a background job (large libraries): ``job.result`` is the same report plus
    ``message`` („Daten geprüft: 1.250 Bauteile – 2 Fehler, 14 Warnungen“)."""
    job = jobs.submit(HEALTH_JOB_KIND, "Daten prüfen", _health_job, ws.root, (body or HealthJobIn()).max_per_check)
    return {"job": job.snapshot()}


# --------------------------------------------------------------------------- import / export


def _preview_out(token: str, file_name: str, table: str | None, sheet: str | None,
                 header_row: int | Literal["auto"] | None, options: ImportRepreviewIn | None = None) -> ImportPreviewOut:
    path, _ = spreadsheet.upload_path(token)
    opts = options or ImportRepreviewIn()
    data = spreadsheet.preview(path, table=table, sheet=sheet, header_row=header_row, mapping=opts.mapping,
                               mode=opts.mode, defaults=opts.defaults, allow_incomplete=opts.allow_incomplete,
                               strict=opts.strict, check_limit=opts.check_rows, thousands=opts.thousands)
    return ImportPreviewOut(token=token, file_name=file_name, table=table, **data)


def _header_row(raw: str | int | None) -> int | Literal["auto"] | None:
    if raw is None or raw == "" or raw == "auto":
        return "auto"
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige Kopfzeile „{raw}“ (auto, 0 oder Zeilennummer).") from exc
    if value < 0:
        raise HTTPException(status_code=400, detail=f"Ungültige Kopfzeile „{raw}“ (auto, 0 oder Zeilennummer).")
    return value or None


@router.post("/import/preview", response_model=ImportPreviewOut)
def import_preview(
    file: UploadFile = File(...),
    table: str | None = Form(default=None),
    sheet: str | None = Form(default=None),
    header_row: str | None = Form(default="auto", description='"auto", Zeilennummer oder 0 (keine Kopfzeile)'),
) -> ImportPreviewOut:
    """Upload a CSV/XLSX/ODS file: sheets, headers, suggested mapping and sample rows."""
    content = file.file.read(spreadsheet.MAX_UPLOAD_BYTES + 1)
    name = file.filename or "import.csv"
    hr = _header_row(header_row)
    with db_errors():
        token = spreadsheet.store_upload(content, name)
        return _preview_out(token, name, table or None, sheet or None, hr)


@router.post("/import/preview/{token}", response_model=ImportPreviewOut)
def import_repreview(token: str, body: ImportRepreviewIn) -> ImportPreviewOut:
    """Preview an already uploaded file again (other sheet, header row or category) – with ``mapping``,
    ``mode``, ``defaults``, ``allow_incomplete`` and ``strict`` also the per-row result of the import."""
    with db_errors():
        _, name = spreadsheet.upload_path(token)
        return _preview_out(token, name, body.table, body.sheet, body.header_row, body)


IMPORT_JOB_KIND = "import"  # in partforge.jobs.LIBRARY_JOB_KINDS: holds its library
EXPORT_JOB_KIND = "export"  # only reads: no hold, ends "cancelled" when its library is switched


@router.post("/import/run", response_model=ImportJobOut)
def import_run(body: spreadsheet.ImportOptions, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Start the import as a background job (automatic backup first).

    The job holds the open library for its whole run (``partforge.jobs.library_hold``): opening,
    creating or closing a library cancels it (``cancel_reason = "library_switch"``) and waits until it
    stopped – a cancelled import imported nothing. It ends with ``job.message`` like „Import fertig:
    120 neu, 4 aktualisiert, 2 abgelehnt“; ``job.result`` carries ``outcome``, ``message`` and the counts."""
    with db_errors():
        _, name = spreadsheet.upload_path(body.token)
        cat = categories.get_category(body.table)
    options = body.model_copy(update={"table": cat.table, "author": resolve_author(body.author)})
    job = jobs.submit(IMPORT_JOB_KIND, f"Import „{name}“ → {cat.label}", spreadsheet.run_import, options,
                      library=ws.root)
    return {"job": job.snapshot()}


@router.get("/export/{table}")
def export_download(
    table: str,
    format: Literal["csv", "xlsx"] = "xlsx",  # noqa: A002 - public query parameter name
    pns: list[str] | None = Query(default=None, description="Teilenummern (mehrfach); leer = alle"),
    columns: list[str] | None = Query(default=None, description="Spalten (mehrfach); leer = alle"),
    search: str | None = None,
    filters: str | None = None,
    sort: str | None = None,
    delimiter: str = ";",
    excel_safe: bool = Query(
        default=True, description="CSV: Werte, die Excel als Formel ausführen würde (= + @ - am Anfang, außer Messwerten "
                                  "wie -55°C), mit ' schützen; false = alle Werte unverändert"),
) -> Response:
    """Download a category as XLSX or CSV (``;``, UTF-8 with BOM)."""
    with db_errors():
        result = spreadsheet.render_export(table, fmt=format, pns=pns, columns=columns, search=search,
                                           filters=_parse_filters(filters), sort=_parse_sort(sort), delimiter=delimiter,
                                           excel_safe=excel_safe)
    response = _download(result.content, result.file_name, result.media_type)
    if result.truncated:  # XLSX cells over Excel's limit were cut (the warning text is in the job/folder export)
        response.headers["X-PartForge-Truncated-Cells"] = str(result.truncated)
    return response


def _export_into_folder(table: str, body: PartExportIn) -> PartExportFileOut:
    warnings: list[str] = []
    path, count = spreadsheet.export_to_file(
        table, fmt=body.format, pns=body.part_numbers, columns=body.columns, search=body.search,
        filters=body.filters, sort=body.sort or None, delimiter=body.delimiter, excel_safe=body.excel_safe,
        warnings=warnings,
    )
    return PartExportFileOut(path=str(path), rel_path=core.current_workspace().rel(path), file_name=path.name,
                             rows=count, warnings=warnings)


@router.post("/export/{table}", response_model=PartExportFileOut)
def export_to_folder(table: str, body: PartExportIn) -> PartExportFileOut:
    """Write the export into the library's ``Exports`` folder (small exports; large ones: ``/export/{table}/job``)."""
    with db_errors():
        return _export_into_folder(table, body)


EXPORT_CANCELLED_NOTE = "Die Bibliothek wurde gewechselt oder geschlossen – Export abgebrochen, es wurde keine Datei geschrieben."


def _export_job(ctx: JobContext, table: str, body: PartExportIn, library: Path) -> dict[str, Any]:
    """Job "Export …": read the parts of the library at ``library`` and write the file into its ``Exports``
    folder. Holds nothing (it only reads); if the library is switched or closed meanwhile it ends
    ``cancelled`` (``LibraryChanged``) without writing a file – never with another library's parts."""
    ctx.progress(0.05, "Bauteile werden gelesen …")
    warnings: list[str] = []

    def written(done: int, total: int) -> None:  # a large XLSX takes seconds: progress and cancel points
        ctx.check_cancelled()
        ctx.progress(0.1 + 0.85 * done / max(total, 1), f"{plural(done, 'Bauteil', 'Bauteile')} von "
                                                         f"{plural(total, 'Bauteil', 'Bauteilen', with_count=True)} geschrieben …")

    try:
        path, count = spreadsheet.export_to_file(
            table, fmt=body.format, pns=body.part_numbers, columns=body.columns, search=body.search,
            filters=body.filters, sort=body.sort or None, delimiter=body.delimiter, excel_safe=body.excel_safe,
            library=library, warnings=warnings, progress=written,
        )
    except LibraryChanged:
        ctx.log(EXPORT_CANCELLED_NOTE, "warn")
        raise
    try:
        rel_path = os.path.relpath(path, library)  # "Exports\\Resistors_….xlsx" like Workspace.rel
    except ValueError:  # another drive (an explicit folder)
        rel_path = str(path)
    message = f"Export fertig: {plural(count, 'Bauteil', 'Bauteile')} in {rel_path}"
    for warning in warnings:
        ctx.log(warning, "warn")
    if warnings:
        message += " – Werte gekürzt (Excel-Grenze), Details im Protokoll"
    ctx.log(message, "success" if not warnings else "warn")
    ctx.progress(1.0, message)
    return PartExportFileOut(path=str(path), rel_path=rel_path, file_name=path.name, rows=count,
                             warnings=warnings).model_dump()


@router.post("/export/{table}/job", response_model=ExportJobOut)
def export_to_folder_job(table: str, body: PartExportIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Like ``POST /export/{table}``, as a background job (large categories take seconds as XLSX).

    Ends with ``job.message`` like „Export fertig: 4 Bauteile in Exports\\Resistors_….xlsx“. Only reads: a
    library switch does not wait for it; the job then ends ``cancelled`` (``cancel_reason =
    "library_switch"``) without writing a file."""
    with db_errors():
        cat = categories.get_category(table)
        unknown = [name for name in body.columns or [] if cat.field(name) is None]
        if unknown:  # fail fast instead of a failed job
            raise HTTPException(status_code=400, detail=f"Das Feld „{unknown[0]}“ gibt es in der Kategorie „{cat.label}“ nicht.")
    job = jobs.submit(EXPORT_JOB_KIND, f"Export {cat.label} ({body.format.upper()})", _export_job, cat.table, body,
                      ws.root)
    return {"job": job.snapshot()}


# --------------------------------------------------------------------------- backups


@router.get("/backups", response_model=list[BackupInfo])
def list_backups() -> list[dict[str, Any]]:
    with db_errors():
        return backup.list_backups()


@router.post("/backups", response_model=BackupInfo, status_code=201)
def create_backup(body: BackupCreateIn | None = None) -> dict[str, Any]:
    with db_errors():
        path = backup.backup_database((body.reason if body else None) or "manuell")
        return next(b for b in backup.list_backups() if b["name"] == path.name)


RESTORE_SYNC_JOB_KIND = "libraries.scan"  # in partforge.jobs.LIBRARY_JOB_KINDS: holds its library
RESTORE_SYNC_JOB_TITLE = "Bibliotheken nach dem Wiederherstellen abgleichen"


def _sync_after_restore(ctx: JobContext, root: Path, previous_manifests: dict[str, str] | None = None) -> dict[str, Any]:
    """Job after a restored backup: the database (registry, parts, manifests) is back at the old state, the
    SchLib/PcbLib files are not. Compare them (``sync.scan_workspace``: registered components missing from
    their file become ``pending``, ``changed_outside`` is recomputed) and write what is pending again
    (``sync.sync_pending`` – the registry is the target state). Without a library writer the entries stay
    ``pending`` and the message says so.

    The scan re-bases the manifests (``rebaseline``): a file PartForge wrote after the backup only looks
    "außerhalb geändert" because the restored manifests describe the older file. ``previous_manifests``
    (``sync.manifest_snapshot()`` taken before the restore) tells which components still hold the restored
    registry spec – the others become ``pending`` and are written back to the restored state."""
    from ..altium import sync
    from ..altium.libwriter import WriterUnavailable
    from ..db import registry
    from .routes_system import libraries_written_message

    with library_hold(ctx, root):
        ctx.progress(0.0, "Bibliotheksdateien werden mit der wiederhergestellten Datenbank verglichen …")
        try:
            scan = sync.scan_workspace(ctx, rebaseline=True, previous_manifests=previous_manifests)
        except (WriterUnavailable, sync.SyncError) as exc:  # no reader for SchLib/PcbLib: nothing compared
            reason = (f"Bibliotheksdateien nach dem Wiederherstellen nicht geprüft: {exc} Bitte danach im Bereich "
                      "Altium „Bibliotheken prüfen“ und „Synchronisieren“ ausführen.")
            ctx.log(reason, "warn")
            ctx.progress(1.0, reason)
            return {"skipped": True, "reason": reason, "message": reason}
        scanned = sync.scan_message(scan)
        ctx.check_cancelled()
        counts = registry.counts()
        waiting = sum(int(counts[k]["by_status"].get(s, 0)) for k in ("symbols", "footprints") for s in ("pending", "error"))
        result: dict[str, Any] = {"scan": scan, "sync": None}
        if not waiting:
            message = f"Nach dem Wiederherstellen: {scanned}"
        else:
            ctx.log(f"{plural(waiting, 'Eintrag wird', 'Einträge werden')} wieder in die Bibliotheksdateien geschrieben.")
            summary = sync.sync_pending(ctx)
            result["sync"] = summary
            message = f"Nach dem Wiederherstellen: {scanned} {libraries_written_message(summary)}."
        ctx.log(message, "success" if not waiting or not (result["sync"] or {}).get("skipped") else "warn")
        ctx.progress(1.0, message)
        result["message"] = message
        return result


def start_sync_after_restore(ws: Workspace, previous_manifests: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Start :func:`_sync_after_restore` for ``ws`` (SQLite libraries); returns the job snapshot."""
    try:
        job = jobs.submit(RESTORE_SYNC_JOB_KIND, RESTORE_SYNC_JOB_TITLE, _sync_after_restore, ws.root,
                          previous_manifests)
    except Exception:  # noqa: BLE001 - the restore itself succeeded; the user can still sync by hand
        log.exception("Abgleich nach dem Wiederherstellen konnte nicht gestartet werden")
        return None
    return job.snapshot()


def _manifest_snapshot() -> dict[str, str] | None:
    """The library manifests as they are before a restore (``sync.manifest_snapshot``); ``None`` if unreadable."""
    from ..altium import sync

    try:
        return sync.manifest_snapshot()
    except Exception:  # noqa: BLE001 - only refines the check after the restore
        log.warning("Bibliotheksstand vor dem Wiederherstellen nicht lesbar", exc_info=True)
        return None


@router.post("/backups/{name}/restore", response_model=BackupRestoreOut)
def restore_backup(name: str, ws: Workspace = Depends(require_workspace)) -> BackupRestoreOut:
    """Restore a backup (the current state is backed up first). The library files are not part of a backup:
    the job ``job`` then compares them with the restored registry and writes what is missing (INT-06) – with the
    manifests taken before the restore, so files PartForge wrote after the backup stay its own."""
    previous_manifests = _manifest_snapshot()
    # like opening a library: the running library jobs stop first and nothing reads the database while it is
    # swapped (a request in that moment answers 409 "wird gerade gewechselt", not "keine Bibliothek geöffnet")
    try:
        with library_switch(timeout=LIBRARY_JOB_STOP_TIMEOUT_S), db_errors():
            backup.restore_backup(name)
    except LibraryBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BackupRestoreOut(ok=True, restored=name, job=start_sync_after_restore(ws, previous_manifests))


# --------------------------------------------------------------------------- saved views


@router.get("/views", response_model=list[SavedView])
def list_views(table: str | None = None) -> list[SavedView]:
    with db_errors():
        return views.list_views(table)


@router.post("/views", response_model=SavedView, status_code=201)
def create_view(body: SavedViewIn) -> SavedView:
    with db_errors():
        return views.create_view(SavedView(**body.model_dump()))


@router.get("/views/{view_id}", response_model=SavedView)
def get_view(view_id: int) -> SavedView:
    with db_errors():
        return views.get_view(view_id)


@router.patch("/views/{view_id}", response_model=SavedView)
def update_view(view_id: int, body: SavedViewPatchIn) -> SavedView:
    with db_errors():
        return views.update_view(view_id, body.model_dump(exclude_unset=True))


@router.delete("/views/{view_id}", response_model=ViewDeletedOut)
def delete_view(view_id: int) -> ViewDeletedOut:
    with db_errors():
        if not views.delete_view(view_id):
            raise HTTPException(status_code=404, detail=f"Gespeicherte Ansicht {view_id} nicht gefunden.")
    return ViewDeletedOut(deleted=True)
