"""Persistent costs of „Datenblatt suchen“: a small ledger in the app data folder.

A datasheet search needs no open library, and its job lives only in memory – so every search that made a paid Claude
call is recorded here when it ends (:func:`record`): done, failed, or cancelled (the cancelled request with its
estimated partial cost, :class:`partforge.datasheet.llm.RequestCancelled`). The URL import of a found link attaches the
costs of its search to the datasheet exactly once (:func:`claim` – also after a restart of PartForge or when the job
list no longer holds the job; ``attached_to`` = the datasheet).

File: ``<app data>/ai/search-costs.json`` (``%APPDATA%\\PartForge\\ai``, isolated runs: ``PARTFORGE_HOME``) – small
user data next to the settings, at most :data:`MAX_ENTRIES` searches (the oldest are dropped first). Writes are
atomic (temporary file + replace) and serialised within the process; an unreadable file is kept as
``search-costs.corrupt.json`` and the ledger starts empty.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from ..config import app_data_dir
from .models import RunInfo

log = logging.getLogger(__name__)

__all__ = ["LEDGER_FORMAT", "MAX_ENTRIES", "SearchCost", "claim", "entries", "get", "ledger_path", "record"]

LEDGER_FORMAT = "partforge-search-costs/1"
MAX_ENTRIES = 200
_REPLACE_ATTEMPTS = 20
_REPLACE_DELAY_S = 0.05

SearchStatus = Literal["done", "failed", "cancelled"]


class SearchCost(BaseModel):
    """The paid calls of one datasheet search."""

    job_id: str | None = None  # job „datasheet-find“ (None: run outside a job, e.g. the recording tool)
    query: str
    manufacturer: str | None = None
    status: SearchStatus
    created: str  # ISO timestamp of the end of the search
    runs: list[RunInfo] = Field(default_factory=list)
    cost_usd: float = 0.0  # sum of the runs
    message: str = ""  # outcome sentence or reason (German)
    attached_to: str | None = None  # datasheet the costs were added to (once)


class _Ledger(BaseModel):
    format: str = LEDGER_FORMAT
    searches: list[SearchCost] = Field(default_factory=list)


_lock = threading.RLock()


def ledger_path() -> Path:
    return app_data_dir() / "ai" / "search-costs.json"


def _load(path: Path) -> _Ledger:
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return _Ledger()
    except OSError as exc:
        log.warning("Kostenprotokoll der Datenblattsuche nicht lesbar (%s): %s", path, exc)
        return _Ledger()
    try:
        ledger = _Ledger.model_validate_json(raw)
        if ledger.format != LEDGER_FORMAT:
            raise ValueError(f"unbekanntes Format {ledger.format!r}")
        return ledger
    except (ValidationError, ValueError) as exc:
        log.warning("Kostenprotokoll der Datenblattsuche beschädigt (%s), wird neu angelegt: %s", path, exc)
        try:
            path.replace(path.with_name(path.stem + ".corrupt.json"))
        except OSError:
            pass
        return _Ledger()


def _save(path: Path, ledger: _Ledger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(ledger.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8")
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            tmp.replace(path)
            return
        except PermissionError:  # Windows: a reader (virus scanner, backup) holds the file for a moment
            if attempt == _REPLACE_ATTEMPTS - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(_REPLACE_DELAY_S)


def record(entry: SearchCost) -> SearchCost:
    """Store the costs of a finished search (an entry of the same job is replaced; ``attached_to`` stays)."""
    entry = entry.model_copy(update={
        "cost_usd": round(sum(run.cost_usd for run in entry.runs), 6),
        "created": entry.created or _dt.datetime.now().isoformat(timespec="seconds"),
    })
    path = ledger_path()
    with _lock:
        ledger = _load(path)
        previous = next((s for s in ledger.searches if entry.job_id and s.job_id == entry.job_id), None)
        if previous is not None:
            entry = entry.model_copy(update={"attached_to": entry.attached_to or previous.attached_to})
            ledger.searches = [s for s in ledger.searches if s is not previous]
        ledger.searches = [*ledger.searches, entry][-MAX_ENTRIES:]
        _save(path, ledger)
    log.info("Kosten der Datenblattsuche „%s“ gespeichert: %.4f USD (%d Anfrage(n), %s)", entry.query, entry.cost_usd,
             len(entry.runs), entry.status)
    return entry


def get(job_id: str) -> SearchCost | None:
    """The recorded search of the job ``job_id`` (``None`` = unknown)."""
    if not job_id:
        return None
    with _lock:
        return next((s for s in _load(ledger_path()).searches if s.job_id == job_id), None)


def entries() -> list[SearchCost]:
    """Every recorded search, oldest first."""
    with _lock:
        return list(_load(ledger_path()).searches)


def claim(job_id: str, datasheet_id: str) -> SearchCost | None:
    """Mark the finished search ``job_id`` as attached to ``datasheet_id`` – once: returns its entry when this call
    claimed it, ``None`` when it is unknown, did not finish (``failed``/``cancelled``: no link to import) or was
    attached already (to this or another datasheet)."""
    if not job_id:
        return None
    path = ledger_path()
    with _lock:
        ledger = _load(path)
        entry = next((s for s in ledger.searches if s.job_id == job_id), None)
        if entry is None or entry.status != "done" or entry.attached_to:
            return None
        claimed = entry.model_copy(update={"attached_to": datasheet_id})
        ledger.searches = [claimed if s is entry else s for s in ledger.searches]
        _save(path, ledger)
    return claimed
