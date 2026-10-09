"""API routes: footprint generator (families, presets, preview with SVG, STEP export, SVG rendering).

The house style comes from the open workspace (``WorkspaceSettings.footprint``); without an open
workspace the default style is used, so the generator also works on the welcome screen. The diode
convention of the workspace (``SymbolStyle.diode_pin1``) is applied by the generator itself
(``partforge.footprints.generate``), so the API, the series assistant and the datasheet import agree.

Generator errors (preview, STEP) answer 400 with ``detail = {"message": <German text>, "params": [...]}``:
``params`` are the request parameters the error is about (``ParamError.params``, else the parameters whose
labels the message names; ``[]`` if none) – the UI marks these fields.
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..footprints import effective_style, error_params, family_info, generate, render_svg, step_text
from ..footprints import families as list_families
from ..footprints import presets as family_presets
from ..footprints import preview as make_preview
from ..footprints.models import FamilyInfo, FootprintPreview, FootprintRequest, Preset
from ..geometry.model import FootprintSpec
from ..workspace import FootprintStyle

log = logging.getLogger(__name__)

router = APIRouter(tags=["footprints"])


class FootprintPreviewOut(FootprintPreview):
    """Preview with a typed spec (for the generated TypeScript types)."""

    spec: FootprintSpec


class FootprintPreviewIn(FootprintRequest):
    """Generator request plus preview options."""

    with_svg: bool = Field(default=True, description="SVG mitliefern (false: svg = null, schneller)")


class GeneratorErrorDetail(BaseModel):
    """``detail`` of a 400 answer of the generator."""

    message: str = Field(description="Deutsche Fehlermeldung")
    params: list[str] = Field(default_factory=list, description="Betroffene Parameter (FootprintRequest.params)")


class GeneratorErrorOut(BaseModel):
    detail: GeneratorErrorDetail


_ERRORS: dict[int | str, dict[str, object]] = {
    400: {"model": GeneratorErrorOut, "description": "Ungültige Parameter (deutsche Meldung, betroffene Parameter)"},
}


class RenderIn(BaseModel):
    spec: FootprintSpec
    layers: list[str] | None = None
    theme: Literal["dark", "light", "altium"] = "dark"
    show_pad_numbers: bool = True
    show_texts: bool = False


class RenderOut(BaseModel):
    svg: str


def _style() -> FootprintStyle:
    """House style of the open workspace (a copy), defaults without workspace."""
    return effective_style(None)


def _bad_request(exc: ValueError, family: str | None = None) -> HTTPException:
    detail = GeneratorErrorDetail(message=str(exc), params=error_params(exc, family))
    return HTTPException(status_code=400, detail=detail.model_dump())


@router.get("/footprints/families", response_model=list[FamilyInfo])
def get_families() -> list[FamilyInfo]:
    """All generator families with parameter definitions and presets."""
    return list_families()


@router.get("/footprints/families/{family}", response_model=FamilyInfo)
def get_family(family: str) -> FamilyInfo:
    try:
        return family_info(family)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Gehäusefamilie „{family}“ nicht gefunden.") from exc


@router.get("/footprints/presets/{family}", response_model=list[Preset])
def get_presets(family: str) -> list[Preset]:
    try:
        return family_presets(family)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Gehäusefamilie „{family}“ nicht gefunden.") from exc


@router.post("/footprints/preview", response_model=FootprintPreviewOut, responses=_ERRORS)
def post_preview(body: FootprintPreviewIn) -> FootprintPreviewOut:
    """Generate a footprint without saving it: spec, calculation record, warnings, checks and SVG
    (``with_svg=false``: without SVG)."""
    # the generator distinguishes given and default fields (density): keep the fields the client sent
    req = FootprintRequest.model_validate(body.model_dump(exclude={"with_svg"}, exclude_unset=True))
    try:
        result = make_preview(req, _style(), svg=body.with_svg)
    except ValueError as exc:
        raise _bad_request(exc, req.family) from exc
    return FootprintPreviewOut.model_validate(result.model_dump())


@router.post(
    "/footprints/step",
    response_class=Response,
    responses={200: {"content": {"model/step": {}}, "description": "STEP-AP214-Datei der 3D-Körper"}, **_ERRORS},
)
def post_step(req: FootprintRequest) -> Response:
    """Generate the footprint and return its extruded 3D bodies as STEP file (download).

    3D bodies are always generated here, even if the house style switches them off for libraries.
    """
    style = _style().model_copy(update={"generate_3d": True})
    try:
        spec = generate(req.model_copy(update={"with_3d": True}), style)
        text = step_text(spec)
    except ValueError as exc:
        raise _bad_request(exc, req.family) from exc
    filename = f"{spec.name}.step"
    return Response(
        content=text.encode("ascii"),
        media_type="model/step",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/footprints/render", response_model=RenderOut)
def post_render(body: RenderIn) -> RenderOut:
    """SVG of an existing footprint spec (gallery thumbnails, imported footprints)."""
    return RenderOut(svg=render_svg(body.spec, layers=body.layers, theme=body.theme,
                                    show_pad_numbers=body.show_pad_numbers, show_texts=body.show_texts))
