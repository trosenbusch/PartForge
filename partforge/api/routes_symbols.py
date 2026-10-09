"""API routes: schematic symbol generator (kinds, live preview, IC side assignment, lookups).

All endpoints work without an open library; with an open library its house style
(``WorkspaceSettings.symbol``) is used. Generation is fast (milliseconds), so no jobs.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from ..geometry.model import SymbolSpec
from ..symbols import (
    SymbolError,
    auto_assign_sides,
    example_request,
    generate,
    kinds,
    render_parts,
    render_svg,
    render_thumbnail,
    spec_warnings,
    suggest_symbol,
)
from ..symbols.models import IcPin, SuggestionSource, SymbolKindInfo, SymbolRequest
from ..symbols.standard import is_diode_kind
from ..symbols.style import StyleKit
from ..workspace import SymbolStyle, current_or_none

log = logging.getLogger(__name__)

router = APIRouter(tags=["symbols"])

Theme = Literal["altium", "dark", "light"]


def _style() -> SymbolStyle:
    ws = current_or_none()
    return ws.settings.symbol if ws is not None else SymbolStyle()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- models
class SymbolPreview(BaseModel):
    spec: SymbolSpec
    svg: str | None = Field(default=None, description="SVG des gewählten Teils (None bei svg=false)")
    svgs: list[str] = Field(default_factory=list, description="SVG je Teil (Teil 1 … n; leer bei svg=false)")
    part: int = 1
    warnings: list[str] = Field(default_factory=list)


class SymbolRenderRequest(BaseModel):
    spec: SymbolSpec
    theme: Theme = "altium"
    part: int | None = Field(default=None, ge=1)
    labels: bool = True


class SymbolRenderResult(BaseModel):
    svg: str
    svgs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AutoSidesRequest(BaseModel):
    pins: list[IcPin]
    overwrite: bool = Field(default=False, description="Auch bereits gesetzte Seiten neu bestimmen")


class AutoSidesResult(BaseModel):
    pins: list[IcPin]


class StandardSymbolMatch(BaseModel):
    request: SymbolRequest | None = None  # ready to generate; None = no safe suggestion
    name: str | None = None  # resulting symbol name in the current house style
    kind_label: str | None = None
    kind: str | None = Field(default=None, description="Passender Symboltyp, auch wenn die Pinbelegung noch fehlt")
    needs_pinmap: bool = Field(default=False, description="Symboltyp passt, Pinbelegung muss gewählt werden")
    pinmap_options: list[str] = Field(default_factory=list, description="In Frage kommende Pinbelegungen")
    alternatives: list[str] = Field(default_factory=list, description="Weitere mögliche Symboltypen")
    package: str | None = Field(default=None, description="Erkanntes Gehäuse")
    source: SuggestionSource | None = Field(default=None, description="Herkunft der Pinbelegung")
    messages: list[str] = Field(default_factory=list, description="Hinweise")


class StandardForRequest(BaseModel):
    table: str = Field(min_length=1, description="Kategorietabelle, z. B. Resistors")
    values: dict[str, Any] = Field(default_factory=dict, description="Feldwerte des Bauteils")
    pins: list[IcPin] = Field(default_factory=list, description="Pinliste (z. B. aus dem Datenblatt)")
    pads: list[str] = Field(default_factory=list, description="Pad-Nummern des Footprints")


# --------------------------------------------------------------------------- endpoints
@router.get("/symbols/kinds", response_model=list[SymbolKindInfo])
def symbol_kinds(
    thumbnails: bool = Query(False, description="SVG-Vorschau je Symboltyp mitliefern"),
    theme: Theme = "dark",
) -> list[SymbolKindInfo]:
    infos = kinds()
    style = _style()
    if style.diode_pin1 != "cathode":  # anode-first workspace: "Diode (AK)" instead of "Diode"
        for info in infos:
            if is_diode_kind(info.key):
                info.default_name = generate(SymbolRequest(kind=info.key), style).name
    if thumbnails:
        for info in infos:
            try:
                spec = generate(example_request(info.key), style)
                info.thumbnail_svg = render_thumbnail(spec, theme=theme, style=style)
            except SymbolError:  # pragma: no cover - every kind has a valid example
                log.exception("Vorschau für Symboltyp %s fehlgeschlagen", info.key)
    return infos


@router.post("/symbols/preview", response_model=SymbolPreview)
def symbol_preview(
    req: SymbolRequest,
    theme: Theme = "altium",
    part: int | None = Query(None, ge=1, description="Teil für 'svg' (Standard 1)"),
    labels: bool = Query(True, description="Bezeichner und Kommentar zeichnen"),
    svg: bool = Query(True, description="SVG mitliefern (false: nur spec und Hinweise – schneller)"),
) -> SymbolPreview:
    style = _style()
    chosen = part or 1
    try:
        spec = generate(req, style)
        if chosen > max(1, spec.part_count):
            raise SymbolError(f"Teil {chosen} gibt es nicht; das Symbol hat {max(1, spec.part_count)} Teil(e).")
        if svg:
            image: str | None = render_svg(spec, theme=theme, part=chosen, labels=labels, style=style)
            svgs = render_parts(spec, theme=theme, labels=labels, style=style) if spec.part_count > 1 else [image]
        else:
            image, svgs = None, []
    except SymbolError as exc:
        raise _bad_request(exc) from exc
    warnings = spec_warnings(spec, grid=StyleKit.from_style(style).grid)
    return SymbolPreview(spec=spec, svg=image, svgs=[s for s in svgs if s is not None], part=chosen, warnings=warnings)


@router.post("/symbols/render", response_model=SymbolRenderResult)
def symbol_render(body: SymbolRenderRequest) -> SymbolRenderResult:
    """SVG for any symbol spec (registry entries, datasheet import, imported libraries)."""
    style = _style()
    try:
        svg = render_svg(body.spec, theme=body.theme, part=body.part, labels=body.labels, style=style)
        svgs = (
            render_parts(body.spec, theme=body.theme, labels=body.labels, style=style)
            if body.spec.part_count > 1
            else [svg]
        )
    except SymbolError as exc:
        raise _bad_request(exc) from exc
    return SymbolRenderResult(
        svg=svg, svgs=svgs, warnings=spec_warnings(body.spec, grid=StyleKit.from_style(style).grid)
    )


@router.post("/symbols/auto-sides", response_model=AutoSidesResult)
def symbol_auto_sides(body: AutoSidesRequest) -> AutoSidesResult:
    pins = [p.model_copy(update={"side": None}) for p in body.pins] if body.overwrite else body.pins
    return AutoSidesResult(pins=auto_assign_sides(pins))


def _standard_match(table: str, values: dict[str, Any], pins: list[IcPin], pads: list[str]) -> StandardSymbolMatch:
    suggestion = suggest_symbol(table, values, pins=pins or None, footprint=pads or None, style=_style())
    label = next((k.label for k in kinds() if k.key == suggestion.kind), None) if suggestion.kind else None
    return StandardSymbolMatch(
        request=suggestion.request,
        name=suggestion.name,
        kind_label=label,
        kind=suggestion.kind,
        needs_pinmap=suggestion.needs_pinmap,
        pinmap_options=suggestion.pinmap_options,
        alternatives=suggestion.alternatives,
        package=suggestion.package,
        source=suggestion.source,
        messages=suggestion.messages,
    )


def _json_query(raw: str, name: str, example: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Parameter '{name}' ist kein gültiges JSON ({exc.msg}). Erwartet wird z. B. {example}.",
        ) from exc


@router.get("/symbols/standard-for", response_model=StandardSymbolMatch)
def symbol_standard_for(
    table: str = Query(..., min_length=1, description="Kategorietabelle, z. B. Resistors"),
    values: str = Query("{}", description="Feldwerte des Bauteils als JSON-Objekt"),
    pins: str | None = Query(None, description='Pinliste als JSON-Array, z. B. [{"designator": "1", "name": "G"}]'),
    pads: str | None = Query(None, description="Pad-Nummern des Footprints, kommagetrennt (z. B. 1,2,3,4)"),
) -> StandardSymbolMatch:
    data = _json_query(values, "values", '{"Polarized": "Ja"}') if values.strip() else {}
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=400, detail="Parameter 'values' muss ein JSON-Objekt sein, z. B. {\"Pins\": 4}."
        )
    pin_rows: list[IcPin] = []
    if pins and pins.strip():
        raw_pins = _json_query(pins, "pins", '[{"designator": "1", "name": "G"}]')
        if not isinstance(raw_pins, list):
            raise HTTPException(status_code=400, detail="Parameter 'pins' muss ein JSON-Array sein.")
        try:
            pin_rows = [IcPin.model_validate(p) for p in raw_pins]
        except ValidationError as exc:
            raise HTTPException(
                status_code=400, detail=f"Parameter 'pins' enthält ungültige Pins ({exc.error_count()} Fehler)."
            ) from exc
    pad_list = [p.strip() for p in (pads or "").split(",") if p.strip()]
    return _standard_match(table, data, pin_rows, pad_list)


@router.post("/symbols/standard-for", response_model=StandardSymbolMatch)
def symbol_standard_for_body(body: StandardForRequest) -> StandardSymbolMatch:
    """Like GET, with the field values, pin table and pads in the request body."""
    return _standard_match(body.table, body.values, body.pins, body.pads)
