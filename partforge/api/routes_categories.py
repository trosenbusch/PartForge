"""API routes: categories (one Altium table per category) and their fields."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import DBAPIError

from ..db import categories, parts
from ..db.errors import (
    BackupError,
    ConflictError,
    DatabaseBusy,
    DatabaseFailure,
    DatabaseNotOpen,
    DbError,
    NotFoundError,
    PartValidationError,
    SchemaError,
    is_lock_error,
)
from ..workspace import WorkspaceNotOpen
from ..db.models import CategoryDef, FieldDef
from ..db.templates import FieldKind
from .deps import require_workspace

log = logging.getLogger(__name__)

router = APIRouter(tags=["categories"], dependencies=[Depends(require_workspace)])


# --------------------------------------------------------------------------- error mapping


@contextmanager
def db_errors() -> Iterator[None]:
    """Map database-layer exceptions to HTTP errors with German messages.

    404 not found · 409 conflict / no library open / database locked by another program ·
    400 business or validation error · 500 unexpected database error (German text).
    """
    try:
        yield
    except HTTPException:
        raise
    except (DatabaseNotOpen, WorkspaceNotOpen) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ConflictError, DatabaseBusy) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PartValidationError as exc:
        raise HTTPException(status_code=400, detail={"message": str(exc), "errors": exc.errors}) from exc
    except DatabaseFailure as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except (SchemaError, BackupError, DbError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DBAPIError as exc:  # anything the db layer did not translate
        if is_lock_error(exc):
            raise HTTPException(status_code=409, detail=str(DatabaseBusy())) from exc
        log.exception("Unerwarteter Datenbankfehler")
        detail = str(getattr(exc, "orig", exc)) or exc.__class__.__name__
        raise HTTPException(
            status_code=500,
            detail=f"Unerwarteter Datenbankfehler: {detail}. Bitte erneut versuchen; bleibt der Fehler, die Bibliothek "
            "prüfen (Bibliothek › Prüfen) oder eine Sicherung wiederherstellen.",
        ) from exc
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise HTTPException(status_code=400, detail=f"Ungültige Angaben – {problems}") from exc
    except ValueError as exc:  # SpreadsheetError and other German ValueErrors of the db layer
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --------------------------------------------------------------------------- models


class CategoryCreateIn(BaseModel):
    table: str = Field(description="Tabellenname = Altium-Bibliotheksname (ASCII, z. B. „Resistors“)")
    label: str | None = None
    prefix: str | None = None
    icon: str | None = None
    color: str | None = None
    default_symbol: str | None = None
    value_field: str | None = None
    description_template: str | None = None
    comment_template: str | None = None
    altium_enabled: bool = True
    fields: list[FieldDef] = Field(default_factory=list, description="Zusätzliche Felder (Standardfelder kommen automatisch)")
    template: str | None = Field(default=None, description="Eingebaute Vorlage, deren Felder/Vorlagen übernommen werden")


class CategoryPatchIn(BaseModel):
    table: str | None = None
    label: str | None = None
    prefix: str | None = None
    icon: str | None = None
    color: str | None = None
    default_symbol: str | None = None
    value_field: str | None = None
    description_template: str | None = None
    comment_template: str | None = None
    sort_order: int | None = None
    altium_enabled: bool | None = None


class FieldPatchIn(BaseModel):
    column: str | None = Field(default=None, description="Neuer Spaltenname (benennt die Spalte um)")
    label: str | None = None
    kind: FieldKind | None = None
    unit: str | None = None
    options: list[str] | None = None
    required: bool | None = None
    show_on_schematic: bool | None = None
    add_to_design: bool | None = None
    system: bool | None = None
    grid_width: int | None = None
    help: str | None = None
    sort_order: int | None = None
    length: int | None = None


class FieldReorderIn(BaseModel):
    columns: list[str]


class DeleteCategoryOut(BaseModel):
    deleted: bool
    table: str
    backup: str | None = None


class FieldKindInfo(BaseModel):
    kind: FieldKind
    label: str


FIELD_KINDS: list[FieldKindInfo] = [
    FieldKindInfo(kind="text", label="Text"),
    FieldKindInfo(kind="quantity", label="Messwert mit Einheit"),
    FieldKindInfo(kind="range", label="Bereich (von … bis)"),
    FieldKindInfo(kind="enum", label="Auswahlliste"),
    FieldKindInfo(kind="bool", label="Ja/Nein"),
    FieldKindInfo(kind="int", label="Ganzzahl"),
    FieldKindInfo(kind="url", label="Link/URL"),
    FieldKindInfo(kind="path", label="Dateipfad"),
    FieldKindInfo(kind="date", label="Datum"),
]


def _patch(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True)


# --------------------------------------------------------------------------- routes


@router.get("/categories", response_model=list[CategoryDef])
def list_categories(counts: bool = True) -> list[CategoryDef]:
    """All categories with their fields (``part_count`` filled unless ``counts=false``)."""
    with db_errors():
        return categories.list_categories(with_counts=counts)


@router.get("/category-templates", response_model=list[CategoryDef])
def category_templates() -> list[CategoryDef]:
    """Built-in category templates (for "Neue Kategorie aus Vorlage")."""
    return categories.builtin_templates()


@router.get("/field-kinds", response_model=list[FieldKindInfo])
def field_kinds() -> list[FieldKindInfo]:
    return FIELD_KINDS


@router.get("/categories/{table}", response_model=CategoryDef)
def get_category(table: str) -> CategoryDef:
    with db_errors():
        cat = categories.get_category(table)
        _, cat.part_count = parts.query_parts(cat.table, limit=1)
        return cat


@router.post("/categories", response_model=CategoryDef, status_code=201)
def create_category(body: CategoryCreateIn) -> CategoryDef:
    with db_errors():
        base: CategoryDef | None = None
        if body.template:
            base = next((t for t in categories.builtin_templates() if t.table.casefold() == body.template.casefold()), None)
            if base is None:
                raise HTTPException(status_code=404, detail=f"Vorlage „{body.template}“ nicht gefunden.")
        data: dict[str, Any] = base.model_dump() if base else {}
        data.update({k: v for k, v in body.model_dump(exclude={"template", "fields"}).items() if v is not None})
        data["fields"] = [*(base.fields if base else []), *body.fields]
        data["builtin"] = base is not None
        data.setdefault("label", body.table)
        cat = CategoryDef.model_validate(data)
        return categories.create_category(cat)


@router.patch("/categories/{table}", response_model=CategoryDef)
def update_category(table: str, body: CategoryPatchIn) -> CategoryDef:
    with db_errors():
        return categories.update_category(table, _patch(body))


@router.delete("/categories/{table}", response_model=DeleteCategoryOut)
def delete_category(table: str) -> DeleteCategoryOut:
    """Drop the category table (an automatic backup is written first)."""
    with db_errors():
        cat = categories.get_category(table)
        backup_name = categories.delete_category(cat.table)
        return DeleteCategoryOut(deleted=True, table=cat.table, backup=backup_name)


@router.post("/categories/{table}/fields", response_model=CategoryDef, status_code=201)
def add_field(table: str, body: FieldDef) -> CategoryDef:
    with db_errors():
        return categories.add_field(table, body)


@router.post("/categories/{table}/fields/reorder", response_model=CategoryDef)
def reorder_fields(table: str, body: FieldReorderIn) -> CategoryDef:
    with db_errors():
        return categories.reorder_fields(table, body.columns)


@router.patch("/categories/{table}/fields/{column:path}", response_model=CategoryDef)
def update_field(table: str, column: str, body: FieldPatchIn) -> CategoryDef:
    with db_errors():
        return categories.update_field(table, column, _patch(body))


@router.delete("/categories/{table}/fields/{column:path}", response_model=CategoryDef)
def remove_field(table: str, column: str) -> CategoryDef:
    """Drop a column (automatic backup first); refused for protected fields."""
    with db_errors():
        return categories.remove_field(table, column)
