"""API routes: "In Altium bearbeiten" – edit a symbol or footprint in Altium Designer, PartForge takes the save over.

::

    POST /altium/edit                        job "altium.edit" ({kind, name}): baseline of the library file, then the
                                             library opens in Altium with the component shown (Altium comes to the
                                             front); 404 not registered, 409 external / not written yet / file
                                             missing, 503 Altium not running, no X2.EXE or no library writer
    GET  /altium/edit/sessions               the libraries of the open library that are being edited in Altium
    POST /altium/edit/sessions/{id}/check    job "libraries.altium-edit": take over what was saved now
    POST /altium/edit/sessions/{id}/end      stop watching – a save not taken over yet is taken over first
                                             ({ended: false, job}); otherwise {ended: true, job: null}

The take-over runs on its own a moment after the library was saved in Altium (the watcher of
:class:`partforge.altium.editing.AltiumEditService`, started by this router's lifespan); its job ends with a German
sentence naming the components taken over (``result.quiet`` = nothing to report, e.g. only PartForge wrote the file).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..altium import editing
from ..altium.bridge.core import AltiumBridge
from ..altium.editing import AltiumEditService, EditError, EditSessionInfo
from ..altium.libwriter import WriterUnavailable, get_writer
from ..jobs import jobs
from ..workspace import Workspace
from .deps import require_workspace
from .routes_altium import AltiumJobOut, _require_altium, altium_errors, get_bridge


@asynccontextmanager
async def _lifespan(_app: Any) -> AsyncIterator[None]:
    editing.start_service()
    try:
        yield
    finally:
        editing.stop_service()


router = APIRouter(tags=["altium"], lifespan=_lifespan)


class EditIn(BaseModel):
    kind: Literal["symbol", "footprint"]
    name: str = Field(min_length=1, max_length=200)


class EditEndOut(BaseModel):
    ended: bool = Field(description="Beendet (true) – oder erst nach der Übernahme im Job (false)")
    job: dict[str, Any] | None = Field(default=None, description="JobSnapshot der abschließenden Übernahme")
    message: str


def get_edit_service() -> AltiumEditService:
    """The process-wide edit service (overridden in tests)."""
    return editing.get_edit_service()


def _http(exc: EditError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


def _session_or_404(service: AltiumEditService, session_id: str) -> editing.EditSession:
    session = service.session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Diese Bearbeitung in Altium ist bereits beendet.")
    return session


@router.post("/altium/edit", response_model=AltiumJobOut)
def edit_in_altium(
    body: EditIn,
    ws: Workspace = Depends(require_workspace),
    bridge: AltiumBridge = Depends(get_bridge),
    service: AltiumEditService = Depends(get_edit_service),
) -> AltiumJobOut:
    """Job: open the library of a symbol/footprint in Altium and show it there; PartForge takes every save over."""
    with altium_errors():
        try:
            rec, path = editing._editable(ws, body.kind, body.name)
        except EditError as exc:
            raise _http(exc) from exc
        try:
            writer = get_writer(workspace=ws)
        except WriterUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        if editing._reader(writer) is None:
            raise HTTPException(status_code=503, detail=editing.NO_READER_MESSAGE)
    _require_altium(bridge)
    title = f"„{rec.name}“ in Altium bearbeiten"
    job = jobs.submit(editing.START_JOB_KIND, title, editing.start_editing, str(ws.root), body.kind, rec.name, bridge,
                      service=service)
    return AltiumJobOut(job=job.snapshot())


@router.get("/altium/edit/sessions", response_model=list[EditSessionInfo])
def edit_sessions(
    ws: Workspace = Depends(require_workspace),
    service: AltiumEditService = Depends(get_edit_service),
) -> list[EditSessionInfo]:
    """The libraries of the open library that are being edited in Altium (watched for saves)."""
    return service.info(ws)


@router.post("/altium/edit/sessions/{session_id}/check", response_model=AltiumJobOut)
def check_edit_session(
    session_id: str,
    ws: Workspace = Depends(require_workspace),
    service: AltiumEditService = Depends(get_edit_service),
) -> AltiumJobOut:
    """Job: take over what was saved in Altium now (the watcher does it on its own a moment after a save)."""
    _session_or_404(service, session_id)
    job = service.submit_take_over(ws, session_id, trigger="manual")
    if job is None:
        raise HTTPException(status_code=404, detail="Diese Bearbeitung in Altium ist bereits beendet.")
    return AltiumJobOut(job=job.snapshot())


@router.post("/altium/edit/sessions/{session_id}/end", response_model=EditEndOut)
def end_edit_session(
    session_id: str,
    ws: Workspace = Depends(require_workspace),
    service: AltiumEditService = Depends(get_edit_service),
) -> EditEndOut:
    """Stop watching the library; a save that was not taken over yet is taken over first (job)."""
    session = _session_or_404(service, session_id)
    with altium_errors():
        try:
            job = service.end(ws, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Diese Bearbeitung in Altium ist bereits beendet.") from exc
    name = session.library.replace("\\", "/").rsplit("/", 1)[-1]
    if job is not None:
        return EditEndOut(ended=False, job=job.snapshot(),
                          message=f"Die Änderungen in {name} werden übernommen, danach endet die Bearbeitung.")
    return EditEndOut(ended=True, message=f"Bearbeitung von {name} in Altium beendet.")


__all__ = ["EditEndOut", "EditIn", "get_edit_service", "router"]
