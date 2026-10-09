"""Shared FastAPI dependencies and error helpers."""
from __future__ import annotations

from fastapi import HTTPException

from ..workspace import Workspace, WorkspaceNotOpen, current


def require_workspace() -> Workspace:
    """Dependency: the open workspace or HTTP 409 (frontend then shows the library picker)."""
    try:
        return current()
    except WorkspaceNotOpen as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} nicht gefunden")


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail=message)
