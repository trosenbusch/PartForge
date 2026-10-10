"""API routes: Stapelbearbeitung (align symbols and footprints with the house style) and "Hausstil aus Beispiel".

``POST /housestyle/check {selection, rules}`` (job ``housestyle.check``, reads only) reports what the
conversion would change (``ConformReport``: per component the changes, per footprint library the detected
roles of its layers and whether its header deviates). ``POST /housestyle/apply`` (job ``libraries.conform``,
holds the library) converts – losslessly on the records, with backups in ``Backups\\lib``, Altium checks and the
registry updated. ``GET /housestyle/undo`` names the last conversion that can be undone, ``POST
/housestyle/undo`` (job ``libraries.conform``) restores the libraries that are unchanged since. ``GET/PUT
/housestyle/rules`` keep the last rules of the library (``pf_meta``). ``POST /housestyle/learn {paths}``
proposes house-style settings from reference libraries (nothing is saved).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..altium import conform as C
from ..altium import housestyle as H
from ..altium import learnstyle, sync
from ..db import meta as db_meta
from ..jobs import JobContext, jobs, library_hold
from ..workspace import Workspace
from .deps import require_workspace

log = logging.getLogger(__name__)

router = APIRouter(tags=["housestyle"])

CHECK_JOB_KIND = "housestyle.check"  # reads only
APPLY_JOB_KIND = "libraries.conform"  # in partforge.jobs.LIBRARY_JOB_KINDS: holds its library


class ConformIn(BaseModel):
    selection: H.ConformSelection = Field(default_factory=H.ConformSelection)
    rules: C.ConformRules = Field(default_factory=C.ConformRules)


class UndoInfo(BaseModel):
    created: str | None = None
    libraries: list[str] = Field(default_factory=list)
    file: str


class LearnIn(BaseModel):
    paths: list[str] = Field(description="Beispielbibliotheken (.SchLib, .PcbLib, .IntLib, .zip) oder Ordner")


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, sync.SyncError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/housestyle/rules", response_model=C.ConformRules)
def get_rules(ws: Workspace = Depends(require_workspace)) -> C.ConformRules:
    """The rules last used in this library (else the defaults)."""
    return H.saved_rules()


@router.put("/housestyle/rules", response_model=C.ConformRules)
def put_rules(body: C.ConformRules, ws: Workspace = Depends(require_workspace)) -> C.ConformRules:
    with library_hold(None, ws.root):
        db_meta.set_meta(H.RULES_META_KEY, body.model_dump_json())
    return body


@router.post("/housestyle/check")
def start_check(body: ConformIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """What the conversion would change (job; ``job.result`` = ``ConformReport``)."""

    def run(ctx: JobContext) -> dict[str, Any]:
        return H.check(body.selection, body.rules, ctx=ctx).model_dump(mode="json")

    job = jobs.submit(CHECK_JOB_KIND, "Hausstil prüfen", run)
    return {"job": job.snapshot()}


@router.post("/housestyle/apply")
def start_apply(body: ConformIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Convert the selection to the house style (job ``libraries.conform``; ``job.result``: ``components``,
    ``libraries``, ``skipped``, ``errors``, ``report``, ``undo``, ``message``)."""
    root = ws.root

    def run(ctx: JobContext) -> dict[str, Any]:
        with library_hold(ctx, root):
            H.remember_rules(body.rules)
            return H.apply(body.selection, body.rules, ctx=ctx)

    job = jobs.submit(APPLY_JOB_KIND, "Hausstil anwenden", run)
    return {"job": job.snapshot()}


@router.get("/housestyle/undo", response_model=UndoInfo | None)
def get_undo(ws: Workspace = Depends(require_workspace)) -> UndoInfo | None:
    info = H.undo_info()
    return UndoInfo.model_validate(info) if info else None


@router.post("/housestyle/undo")
def start_undo(ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Undo the last conversion (job ``libraries.conform``)."""
    if H.undo_info() is None:
        raise HTTPException(status_code=404, detail="Es gibt keine Stapelbearbeitung, die sich rückgängig machen ließe.")
    root = ws.root

    def run(ctx: JobContext) -> dict[str, Any]:
        with library_hold(ctx, root):
            return H.undo_last(ctx=ctx)

    job = jobs.submit(APPLY_JOB_KIND, "Stapelbearbeitung rückgängig machen", run)
    return {"job": job.snapshot()}


@router.post("/housestyle/learn", response_model=learnstyle.StyleProposal)
def learn(body: LearnIn, ws: Workspace = Depends(require_workspace)) -> learnstyle.StyleProposal:
    """House-style settings derived from reference libraries (proposal only – the settings page saves them)."""
    if not body.paths:
        raise HTTPException(status_code=400, detail="Bitte mindestens eine Beispielbibliothek angeben.")
    try:
        return learnstyle.learn(body.paths, ws.settings)
    except sync.SyncError as exc:
        raise _http(exc) from exc
