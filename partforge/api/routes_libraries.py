"""API routes: symbol/footprint libraries (registry, files, sync, external libraries, health).

Everything that writes library files goes through :mod:`partforge.altium.sync` (registry +
batched writes, Altium safety checks). Long operations run as jobs and return
``{"job": snapshot}``; a single save/delete runs directly unless it may be slow (Altium
running, Altium backend, large library) – then the response carries the job instead of the
result (``{"record": null, "job": {...}}``).

A save that does not reach the library file is an error: 400 invalid, 409 conflict (pin-out,
external or foreign component of the same name, library open and modified in Altium), 503 no
library writer (the spec stays registered as ``pending`` and is written by the next sync). In
a background save the job fails with the same message.

Library guard: every job here (save, delete, sync, scan, layer header) holds the library it was
started for (:func:`partforge.jobs.library_hold`) – a library switch cancels it and waits until
it stopped, a job whose library was closed meanwhile does not run. Direct writes (save, delete,
external libraries) hold it as well: a switch waits for them, and a write that finds another
library open answers 409.

Saving (``PUT /libraries/symbols|footprints/{name}``): the answer names the target library
(``library``/``library_abs``, also for new names and background saves); ``?dry_run=true`` runs every
check without writing and reports what a save would do (target file, new or unchanged, pin-out
changes and usage). A changed pin-out without ``allow_pinout_change`` answers 409 with
``detail = {"code": "pinout_changed", "message", "changes", "usage"}``. An explicit target library
(``SymbolSaveIn.library`` / ``FootprintSaveIn.library``) must be an existing library of the right
kind below ``Symbols\\`` / ``Footprints\\`` or a new ``PF_<Name>.SchLib`` / ``PF_<Name>.PcbLib``
directly there (:func:`partforge.altium.sync.resolve_library_choice`, else 400); a name registered
in another library is refused with 409 (a save never moves a component). A custom name is recorded
in ``spec.generator["name"]`` (``Neu generieren`` reproduces it).

Thumbnails (``GET …/{name}/thumbnail.svg``): SVG with an ``ETag`` (content hash + theme); ``If-None-Match``
answers 304. ``Cache-Control: private, no-cache`` (always revalidate), or ``private, max-age=31536000,
immutable`` when ``?v=`` equals the entry's current ``content_hash`` (list/detail entries carry it: it
changes with every change of the geometry, the symbol style or the renderer – two saves within one
second never keep a stale image). Any other ``v`` (e.g. the older ``updated``) is accepted but only
revalidated.

Health (``GET /libraries/health``, cached per library state, ``?refresh=true`` checks again): file-level findings
with ``affected_parts``/``part_numbers`` (check ids in ARCHITEKTUR.md §8.4); ``POST /libraries/footprint-heights/repair``
(job) is the one-click fix of ``footprint_height_missing``, ``POST /libraries/restore-backup`` (job, ``{library}``) the one
of ``library_unreadable`` (the newest readable backup from ``Backups\\lib`` replaces the damaged file).
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from ..altium import layersets, stackup, sync
from ..altium.libwriter import WriterUnavailable
from ..db import registry
from ..db.models import FootprintRecord, SymbolRecord
from ..domain.text import plural
from ..geometry.model import Body3D, FootprintSpec, SymbolSpec
from ..jobs import JobContext, LibraryChanged, jobs, library_hold
from ..workspace import LayerMap, Workspace
from .deps import require_workspace

log = logging.getLogger(__name__)

router = APIRouter(tags=["libraries"])

Theme = Literal["altium", "dark", "light"]
Thumbnails = Literal["none", "svg"]


# --------------------------------------------------------------------------- models


class _EntryBase(BaseModel):
    name: str
    library: str
    library_abs: str | None = None
    source: str
    status: str
    status_message: str | None = None
    updated: str | None = None
    usage: int = 0
    has_spec: bool | None = Field(default=None, description="Geometrie gespeichert (None = nicht geladen)")
    content_hash: str | None = Field(
        default=None,
        description="Prüfwert des Vorschaubilds (Geometrie, Symbol-Hausstil, Darstellung) – als ?v= an "
                    "…/thumbnail.svg dauerhaft zwischenspeicherbar; None = keine Geometrie",
    )
    thumbnail_svg: str | None = None


class SymbolEntry(_EntryBase):
    pin_count: int = 0
    part_count: int = 1
    kind: str | None = None


class FootprintEntry(_EntryBase):
    family: str | None = None
    ipc_name: str | None = None
    pad_count: int = 0
    height: float | None = None
    step_file: str | None = None


class SymbolDetail(BaseModel):
    record: SymbolEntry
    spec: SymbolSpec | None = None
    svgs: list[str] = Field(default_factory=list, description="SVG je Teil (Teil 1 … n)")
    warnings: list[str] = Field(default_factory=list)
    file_exists: bool = False


class FootprintStepInfo(BaseModel):
    file: str
    path: str | None = None
    exists: bool = False


class FootprintStepModel(BaseModel):
    id: str = Field(description="Opaque model revision, bound to the active workspace and file contents")
    name: str
    url: str = Field(description="Authenticated relative URL of this STEP revision")
    rotation: tuple[float, float, float] = Field(description="X/Y/Z rotations in degrees")
    offset: tuple[float, float, float] = Field(description="X/Y/Z translation in millimetres")


class FootprintStepModels(BaseModel):
    models: list[FootprintStepModel] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FootprintDetail(BaseModel):
    record: FootprintEntry
    spec: FootprintSpec | None = None
    svg: str | None = None
    bodies: list[Body3D] = Field(default_factory=list, description="3D-Körper (Prismen) für die 3D-Vorschau")
    height: float | None = None
    step: FootprintStepInfo | None = None
    warnings: list[str] = Field(default_factory=list)
    file_exists: bool = False


_LIBRARY_HELP = (
    "Ziel-Bibliotheksdatei (relativ zum Bibliotheksordner, z. B. „{folder}\\PF_Beispiel{ext}“, oder nur der "
    "Dateiname): eine vorhandene {ext}-Bibliothek unter {folder}\\ oder eine neue „PF_<Name>{ext}“ direkt darin. "
    "Leer = automatisch (Kategorie/Familie); ein schon registrierter Name bleibt in seiner Bibliothek (sonst 409)."
)


class SymbolSaveIn(BaseModel):
    spec: SymbolSpec
    category: str | None = Field(default=None, description="Kategorietabelle (bestimmt die Bibliotheksgruppe neuer Symbole)")
    source: Literal["generated", "datasheet", "imported"] = "generated"
    allow_pinout_change: bool = Field(default=False, description="Geänderte Pinbelegung ausdrücklich übernehmen")
    background: bool | None = Field(default=None, description="Als Job ausführen (Standard: automatisch)")
    library: str | None = Field(default=None, description=_LIBRARY_HELP.format(folder="Symbols", ext=".SchLib"))


class FootprintSaveIn(BaseModel):
    spec: FootprintSpec
    source: Literal["generated", "datasheet", "imported"] = "generated"
    background: bool | None = None
    library: str | None = Field(default=None, description=_LIBRARY_HELP.format(folder="Footprints", ext=".PcbLib"))


class _SaveOutBase(BaseModel):
    library: str | None = Field(default=None, description="Ziel-Bibliotheksdatei (relativ zum Bibliotheksordner)")
    library_abs: str | None = Field(default=None, description="Ziel-Bibliotheksdatei (absolut)")
    new: bool = Field(default=False, description="Der Name war noch nicht registriert (neu in der Bibliothek)")
    dry_run: bool = Field(default=False, description="Probelauf: nichts wurde geschrieben")
    unchanged: bool = Field(
        default=False, description="Probelauf: entspricht dem gespeicherten Stand – es würde nichts geschrieben"
    )
    usage: int = Field(default=0, description="Bauteile, die den Namen verwenden")


class SymbolSaveOut(_SaveOutBase):
    """Either the saved record or – for a slow write – the job that saves it; with ``dry_run`` neither."""

    record: SymbolEntry | None = None
    job: dict[str, Any] | None = None
    changes: list[str] = Field(default_factory=list, description="Probelauf: Änderungen der Pinbelegung")
    needs_confirmation: bool = Field(
        default=False, description="Probelauf: die Pinbelegung ändert sich – Speichern verlangt allow_pinout_change"
    )


class FootprintSaveOut(_SaveOutBase):
    """Either the saved record or – for a slow write – the job that saves it; with ``dry_run`` neither."""

    record: FootprintEntry | None = None
    job: dict[str, Any] | None = None


class PinoutChangedDetail(BaseModel):
    """``detail`` of the 409 answer when a save would change the pin-out of a registered symbol."""

    code: Literal["pinout_changed"] = "pinout_changed"
    message: str
    changes: list[str] = Field(description="Änderungen (deutsch), z. B. „Pin 2: Name „TRIG“ → „TRIGGER““")
    usage: int = Field(description="Bauteile, die das Symbol verwenden")


class PinoutChangedOut(BaseModel):
    detail: PinoutChangedDetail


class LibraryDeleteResult(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    unregistered: list[str] = Field(default_factory=list, description="Nur aus PartForge entfernt (externe Bibliothek)")
    refused: dict[str, str] = Field(default_factory=dict)
    errors: dict[str, str] = Field(default_factory=dict)
    not_found: list[str] = Field(default_factory=list)
    libraries: list[str] = Field(default_factory=list)


class LibraryDeleteOut(BaseModel):
    result: LibraryDeleteResult | None = None
    job: dict[str, Any] | None = None


class ExternalComponent(BaseModel):
    name: str
    library: str
    kind: Literal["symbol", "footprint"]
    description: str | None = None
    pin_count: int | None = None
    part_count: int | None = None
    has_3d: bool | None = None
    registered: bool = False
    registered_source: str | None = None
    conflict: bool = Field(default=False, description="Name ist bereits anderweitig registriert")
    svg: str | None = None


class ExternalComponentsOut(BaseModel):
    library: sync.ExternalLibrary
    total: int
    offset: int
    components: list[ExternalComponent]


class ExternalRemoveOut(BaseModel):
    removed: str
    path: str
    registered_components: list[str] = Field(default_factory=list)


class LibraryScanIn(BaseModel):
    register_unknown: bool = Field(default=False, description="Unbekannte Bauteile als 'imported' registrieren")


class ExternalLibraryIn(BaseModel):
    path: str


class ExternalUseIn(BaseModel):
    name: str


class LibraryHealthOut(BaseModel):
    issues: list[sync.LibraryHealthIssue]
    counts: dict[str, int] = Field(description="Befunde je Schwere (alle, auch die nicht gelisteten)")
    summary: dict[str, int] = Field(default_factory=dict, description="Befunde je Prüfung (alle)")
    checked_parts: int
    truncated: bool = False
    affected_parts: int = Field(default=0, description="Bauteile mit mindestens einem Fehler oder einer Warnung")
    affected_part_numbers: list[str] = Field(
        default_factory=list, description="Teilenummern aller Bauteile mit Fehler oder Warnung (sortiert)"
    )


class HeightRepairIn(BaseModel):
    names: list[str] | None = Field(default=None, description="Nur diese Footprints (Standard: alle betroffenen)")


class LibraryRestoreIn(BaseModel):
    library: str = Field(description="Beschädigte Bibliotheksdatei, relativ zum Bibliotheksordner "
                                     "(LibraryHealthIssue.library des Befunds library_unreadable)")


class LayerStackParseIn(BaseModel):
    path: str


class LayerStackOut(BaseModel):
    stack: stackup.LayerStack
    notes: list[str] = Field(default_factory=list)
    layer_map: LayerMap | None = None
    suggested_layer_map: LayerMap
    issues: list[str] = Field(default_factory=list)
    patch_enabled: bool = True


class LayerSetParseIn(BaseModel):
    path: str = Field(description="Altium-Lagensatz-Datei (.layerset), absolut")


class LayerSetParseOut(BaseModel):
    file: str
    sets: list[layersets.LayerSetDef]


class LayerSetBuiltinIn(BaseModel):
    layers: LayerMap | None = Field(default=None, description="Lagenzuordnung (None = die gespeicherte)")
    current: bool = True


# --------------------------------------------------------------------------- helpers


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, sync.SyncError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, WriterUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, stackup.StackupError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


_svg_cache: dict[tuple[str, str, str | None, str], str] = {}
_svg_lock = threading.Lock()


def _cached_svg(kind: str, name: str, version: str | None, theme: str, render: Any) -> str | None:
    """Rendered SVG per (kind, name, content version, theme) – the version is the content hash, so a
    changed spec is never served from the cache (not even within the same second)."""
    key = (kind, name.casefold(), version, theme)
    with _svg_lock:
        cached = _svg_cache.get(key)
    if cached is not None:
        return cached
    try:
        svg = render()
    except Exception as exc:  # noqa: BLE001 - one broken spec must not break the list
        log.info("Vorschau von %s nicht darstellbar: %s", name, exc)
        return None
    with _svg_lock:
        if len(_svg_cache) > 4000:
            _svg_cache.clear()
        _svg_cache[key] = svg
    return svg


def _symbol_thumbnail(spec: SymbolSpec, theme: str) -> str:
    return sync.component_thumbnail(spec, theme)


def _footprint_thumbnail(spec: FootprintSpec, theme: str) -> str:
    return sync.component_thumbnail(spec, theme)


def _abs(ws: Workspace, stored: str | None) -> str | None:
    path = ws.abs(stored) if stored else None
    return str(path) if path is not None else None


_IMMUTABLE = "private, max-age=31536000, immutable"
_REVALIDATE = "private, no-cache"
_SVG_POLICY = "default-src 'none'; style-src 'unsafe-inline'; sandbox"


def _list_hashes(kind: Literal["symbol", "footprint"], records: list[Any], loaded: bool) -> dict[str, str | None]:
    """Thumbnail versions of a list: from the records' ``content_hash`` when their specs were read (K10: the spec
    text is never read twice), else one read of the texts (:func:`sync.content_hashes`)."""
    if loaded:
        salt = sync.thumbnail_salt(kind)
        return {r.name.casefold(): sync.thumbnail_hash(kind, getattr(r, "content_hash", None), salt=salt) for r in records}
    return sync.content_hashes(kind)


def _content_hash(kind: Literal["symbol", "footprint"], name: str) -> str | None:
    """Content hash of one entry (``name`` in its stored spelling), see :func:`sync.content_hashes`."""
    return sync.content_hashes(kind, name).get(name.casefold())


def _thumbnail_etag(content_hash: str, theme: str) -> str:
    """Strong ETag: content hash (geometry, render style, renderer version) plus theme."""
    return f'"{content_hash}.{theme}"'


def _etag_matches(header: str | None, etag: str) -> bool:
    """``If-None-Match`` matches (weak comparison, lists and ``*`` allowed)."""
    if not header:
        return False
    wanted = etag.strip('"')
    for raw in header.split(","):
        tag = raw.strip()
        if tag == "*" or tag.removeprefix("W/").strip('"') == wanted:
            return True
    return False


def _thumbnail_response(request: Request, kind: str, name: str, etag: str, theme: str, versioned: bool,
                        render: Callable[[], str]) -> Response:
    headers = {"ETag": etag, "Cache-Control": _IMMUTABLE if versioned else _REVALIDATE}
    if _etag_matches(request.headers.get("if-none-match"), etag):
        return Response(status_code=304, headers=headers)
    svg = _cached_svg(f"{kind}-thumbnail", name, etag, theme, render)
    if svg is None:
        label = "Symbol" if kind == "symbol" else "Footprint"
        raise HTTPException(status_code=404,
                            detail=f"Für {label} „{name}“ ist keine Vorschau möglich (Geometrie fehlerhaft).")
    return Response(content=svg, media_type="image/svg+xml",
                    headers={**headers, "Content-Security-Policy": _SVG_POLICY, "X-Content-Type-Options": "nosniff"})


def _target_library(ws: Workspace, spec: SymbolSpec | FootprintSpec, category: str | None = None,
                    library: str | None = None) -> tuple[str, str | None]:
    """(workspace-relative, absolute) library file a save of ``spec`` writes to."""
    rel = ws.rel(sync.planned_library(spec, category=category, library=library))
    return rel, _abs(ws, rel)


def _check_library_choice(spec: SymbolSpec | FootprintSpec, library: str | None) -> None:
    """400 for an invalid explicit target library, 409 if the name is registered in another one."""
    if library is None or not library.strip():
        return
    try:
        refusal = sync.library_choice_conflict(spec, library)
    except sync.SyncError as exc:
        raise _http(exc) from exc
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)


def _same_library(stored: str | None, rel: str) -> bool:
    return bool(stored) and str(stored).replace("/", "\\").casefold() == rel.replace("/", "\\").casefold()


def _symbol_entry(ws: Workspace, rec: SymbolRecord, theme: str | None = None, *, spec_loaded: bool = True,
                  content_hash: str | None | Literal[False] = False) -> SymbolEntry:
    """API entry of a record (``content_hash=False``: look it up; lists pass the hash they read)."""
    if content_hash is False:
        content_hash = _content_hash("symbol", rec.name)
    entry = SymbolEntry(
        name=rec.name,
        library=rec.library,
        library_abs=_abs(ws, rec.library),
        source=rec.source,
        status=rec.status,
        status_message=rec.status_message,
        updated=rec.updated,
        usage=rec.usage,
        has_spec=(rec.spec is not None) if spec_loaded else None,
        content_hash=content_hash,
        pin_count=rec.pin_count,
        part_count=rec.part_count,
        kind=rec.kind,
    )
    spec = rec.spec
    if theme is not None and spec is not None:
        entry.thumbnail_svg = _cached_svg("symbol", rec.name, content_hash, theme, lambda: _symbol_thumbnail(spec, theme))
    return entry


def _footprint_entry(
    ws: Workspace, rec: FootprintRecord, theme: str | None = None, *, spec_loaded: bool = True,
    content_hash: str | None | Literal[False] = False,
) -> FootprintEntry:
    """API entry of a record (``content_hash=False``: look it up; lists pass the hash they read)."""
    if content_hash is False:
        content_hash = _content_hash("footprint", rec.name)
    entry = FootprintEntry(
        name=rec.name,
        library=rec.library,
        library_abs=_abs(ws, rec.library),
        source=rec.source,
        status=rec.status,
        status_message=rec.status_message,
        updated=rec.updated,
        usage=rec.usage,
        has_spec=(rec.spec is not None) if spec_loaded else None,
        content_hash=content_hash,
        family=rec.family,
        ipc_name=rec.ipc_name,
        pad_count=rec.pad_count,
        height=rec.height,
        step_file=rec.step_file,
    )
    spec = rec.spec
    if theme is not None and spec is not None:
        entry.thumbnail_svg = _cached_svg(
            "footprint", rec.name, content_hash, theme, lambda: _footprint_thumbnail(spec, theme)
        )
    return entry


def _matches(rec: SymbolRecord | FootprintRecord, search: str | None) -> bool:
    if not search:
        return True
    needle = search.casefold()
    hay = [rec.name, rec.library, rec.status_message or ""]
    if isinstance(rec, FootprintRecord):
        hay += [rec.family or "", rec.ipc_name or ""]
    else:
        hay += [rec.kind or ""]
    return any(needle in str(h).casefold() for h in hay)


def _job_records(records: list[SymbolRecord] | list[FootprintRecord]) -> dict[str, Any]:
    return {"records": [r.model_dump(mode="json", exclude={"spec"}) for r in records]}


def _save_job(label: str, run: Callable[[JobContext], list[Any]]) -> Callable[[JobContext], dict[str, Any]]:
    """Job body of a background save with a specific final message (instead of the sync's generic one)."""

    def body(ctx: JobContext) -> dict[str, Any]:
        records = run(ctx)
        rec = records[0]
        message = f"{label} „{rec.name}“ gespeichert in {rec.library}" if rec.library else f"{label} „{rec.name}“ gespeichert"
        ctx.log(message, "success")
        ctx.progress(1.0, message)
        return _job_records(records)

    return body


def _delete_message(label: str, name: str, result: dict[str, Any]) -> tuple[str, Literal["success", "warn"]]:
    """Final message (and log level) of a background delete."""
    errors: dict[str, str] = result.get("errors") or {}
    refused: dict[str, str] = result.get("refused") or {}
    if errors:
        return f"{label} „{name}“ nicht gelöscht: {errors.get(name) or next(iter(errors.values()))}", "warn"
    if refused:
        return next(iter(refused.values())), "warn"
    if result.get("unregistered"):
        return f"{label} „{name}“ aus PartForge entfernt (die Bibliotheksdatei bleibt unverändert)", "success"
    if result.get("not_found"):
        return f"{label} „{name}“ ist nicht registriert", "warn"
    return f"{label} „{name}“ gelöscht", "success"


def _delete_job(label: str, name: str, run: Callable[[JobContext], dict[str, Any]]) -> Callable[[JobContext], dict[str, Any]]:
    def body(ctx: JobContext) -> dict[str, Any]:
        result = run(ctx)
        message, level = _delete_message(label, name, result)
        ctx.log(message, level)
        ctx.progress(1.0, message)
        return result

    return body


def _sync_message(summary: dict[str, Any]) -> str:
    """Final message of the job „Bibliotheken synchronisieren“."""
    if summary.get("skipped"):
        return "Nicht synchronisiert – kein Bibliotheks-Writer verfügbar (die Einträge bleiben vorgemerkt)"
    symbols: dict[str, Any] = summary.get("symbols") or {}
    footprints: dict[str, Any] = summary.get("footprints") or {}
    if not symbols.get("total") and not footprints.get("total"):
        return "Bibliotheken sind aktuell – nichts zu schreiben"

    written = [plural(int(symbols.get("ok") or 0), "Symbol", "Symbole"),
               plural(int(footprints.get("ok") or 0), "Footprint", "Footprints")]
    parts = [f"Synchronisiert: {' und '.join(written)}"]
    errors = int(symbols.get("error") or 0) + int(footprints.get("error") or 0)
    missing = int(symbols.get("missing") or 0) + int(footprints.get("missing") or 0)
    if errors:
        parts.append(plural(errors, "Fehler", "Fehler"))
    if missing:
        parts.append(f"{missing} nicht erzeugbar")
    return ", ".join(parts)


def _sync_job(ctx: JobContext) -> dict[str, Any]:
    summary = sync.sync_pending(ctx)
    ctx.progress(1.0, _sync_message(summary))
    return summary


def _held(root: Path, fn: Callable[[JobContext], Any]) -> Callable[[JobContext], Any]:
    """Job body that holds the library at ``root`` for its whole run (:func:`partforge.jobs.library_hold`)."""

    def run(ctx: JobContext) -> Any:
        with library_hold(ctx, root):
            return fn(ctx)

    return run


@contextmanager
def _direct_write(ws: Workspace) -> Iterator[None]:
    """A write in the request thread: a library switch waits for it; 409 if another library is open by now."""
    try:
        with library_hold(None, ws.root):
            yield
    except LibraryChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --------------------------------------------------------------------------- symbols


@router.get("/libraries/symbols", response_model=list[SymbolEntry])
def list_symbols(
    thumbnails: Thumbnails = Query("none", description="'svg' liefert eine Vorschau je Symbol"),
    theme: Theme = "dark",
    status: str | None = Query(None, description="ok, pending, missing oder error"),
    source: str | None = Query(None, description="generated, datasheet, imported oder external"),
    search: str | None = None,
    ws: Workspace = Depends(require_workspace),
) -> list[SymbolEntry]:
    """Registered symbols with status, usage count, ``content_hash`` (``?v=`` of the thumbnail) and
    (optionally) SVG thumbnails."""
    records = registry.list_symbols(
        status=status if status in ("ok", "pending", "missing", "error") else None,  # type: ignore[arg-type]
        source=source,
        with_spec=thumbnails == "svg",
    )
    chosen_theme = theme if thumbnails == "svg" else None
    loaded = thumbnails == "svg"
    hashes = _list_hashes("symbol", records, loaded)
    return [_symbol_entry(ws, rec, chosen_theme, spec_loaded=loaded, content_hash=hashes.get(rec.name.casefold()))
            for rec in records if _matches(rec, search)]


_V_HELP = (
    "Version: der content_hash des Eintrags – dann darf der Browser das Bild dauerhaft speichern (immutable); "
    "jeder andere Wert wird nur per ETag geprüft"
)
_THUMBNAIL_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {"content": {"image/svg+xml": {}}, "description": "SVG-Vorschau (mit ETag)"},
    304: {"description": "Unverändert (If-None-Match passt zum ETag)"},
    404: {"description": "Nicht registriert oder ohne Geometrie"},
}


@router.get("/libraries/symbols/{name:path}/thumbnail.svg", response_class=Response, responses=_THUMBNAIL_RESPONSES)
def symbol_thumbnail(
    name: str,
    request: Request,
    theme: Theme = "dark",
    v: str | None = Query(None, description=_V_HELP),
    ws: Workspace = Depends(require_workspace),
) -> Response:
    """Thumbnail of a registered symbol (part 1, without labels; ETag/If-None-Match → 304;
    ``v`` = the entry's ``content_hash`` → cacheable forever)."""
    rec = registry.get_symbol(name, with_usage=False)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Symbol „{name}“ ist nicht registriert.")
    spec = rec.spec
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Für Symbol „{rec.name}“ ist keine Geometrie gespeichert.")
    content_hash = _content_hash("symbol", rec.name) or ""
    return _thumbnail_response(request, "symbol", rec.name, _thumbnail_etag(content_hash, theme), theme,
                               bool(v) and v == content_hash, lambda: _symbol_thumbnail(spec, theme))


@router.get("/libraries/symbols/{name:path}", response_model=SymbolDetail)
def get_symbol(
    name: str,
    theme: Theme = "altium",
    svg: bool = Query(True, description="SVG je Teil mitliefern (false: svgs bleibt leer – schneller)"),
    ws: Workspace = Depends(require_workspace),
) -> SymbolDetail:
    """One symbol: record, geometry and one SVG per part."""
    from ..symbols import render_parts, spec_warnings

    rec = registry.get_symbol(name)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Symbol „{name}“ ist nicht registriert.")
    detail = SymbolDetail(record=_symbol_entry(ws, rec), spec=rec.spec)
    path = ws.abs(rec.library) if rec.library else None
    detail.file_exists = bool(path is not None and path.is_file())
    if rec.spec is not None:
        try:
            if svg:
                detail.svgs = render_parts(rec.spec, theme=theme)
            detail.warnings = spec_warnings(rec.spec, grid=ws.settings.symbol.grid)
        except Exception as exc:  # noqa: BLE001 - show the record even if the preview fails
            detail.warnings.append(f"Vorschau nicht möglich: {exc}")
    detail.warnings.extend(sync.component_warnings(rec))
    return detail


@router.put(
    "/libraries/symbols/{name:path}",
    response_model=SymbolSaveOut,
    responses={409: {"model": PinoutChangedOut,
                     "description": "Pinbelegung geändert (strukturiert, code „pinout_changed“); andere Konflikte "
                                    "(externe Bibliothek, fremdes Bauteil, Altium) mit detail als Text"}},
)
def save_symbol(
    name: str,
    body: SymbolSaveIn,
    dry_run: bool = Query(False, description="Nur prüfen: nichts schreiben, Ziel und Änderungen melden"),
    ws: Workspace = Depends(require_workspace),
) -> SymbolSaveOut:
    """Save a symbol from the editor: register it and write it to its library (``dry_run``: only check)."""
    spec = body.spec
    if spec.name.casefold() != name.casefold():
        raise HTTPException(
            status_code=400,
            detail=f"Der Name im Pfad („{name}“) und im Symbol („{spec.name}“) stimmen nicht überein – Umbenennen wird "
            "nicht unterstützt; bitte als neues Symbol speichern.",
        )
    existing = registry.get_symbol(spec.name)
    if existing is not None and existing.source == "external":
        raise HTTPException(status_code=409, detail=f"Symbol „{existing.name}“ gehört zu einer externen Bibliothek und ist schreibgeschützt.")
    problems = sync.validate_spec(spec)
    if problems:
        raise HTTPException(status_code=400, detail="Das Symbol kann nicht gespeichert werden: " + " ".join(problems[:8]))
    _check_library_choice(spec, body.library)
    changes = sync.pinout_changes(existing.spec, spec) if existing is not None and existing.spec is not None else []
    usage = existing.usage if existing is not None else 0
    if changes and not body.allow_pinout_change and not dry_run:
        assert existing is not None
        users = plural(usage, "Bauteil verwendet", "Bauteile verwenden")
        message = (
            f"Die Pinbelegung von „{existing.name}“ ändert sich ({'; '.join(changes[:6])}); {users} das Symbol. "
            "Bitte bestätigen (allow_pinout_change) oder als neues Symbol speichern."
        )
        raise HTTPException(status_code=409,
                            detail=PinoutChangedDetail(message=message, changes=changes, usage=usage).model_dump())
    conflict = sync.foreign_conflict(spec, category=body.category, library=body.library)
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)
    library, library_abs = _target_library(ws, spec, body.category, body.library)
    target = {"library": library, "library_abs": library_abs, "new": existing is None, "usage": usage}
    if dry_run:
        unchanged = bool(
            existing is not None and existing.status == "ok" and existing.spec is not None
            and existing.source != "altium"  # an Altium version is always replaced (sync rule 3)
            and sync.symbol_fingerprint(existing.spec) == sync.symbol_fingerprint(spec)
            and _same_library(existing.library, library) and library_abs and Path(library_abs).is_file()
        )
        return SymbolSaveOut(dry_run=True, unchanged=unchanged, changes=changes,
                             needs_confirmation=bool(changes) and not body.allow_pinout_change, **target)
    background = (body.background if body.background is not None
                  else sync.write_is_slow(spec, category=body.category, library=body.library))

    def run(ctx: JobContext | None) -> list[SymbolRecord]:
        return sync.ensure_symbols(
            [spec], category=body.category, source=body.source, ctx=ctx, allow_pin_changes=body.allow_pinout_change,
            strict=True, library=body.library,
        )

    if background:
        job = jobs.submit("libraries.save", f"Symbol {spec.name} speichern", _held(ws.root, _save_job("Symbol", run)))
        return SymbolSaveOut(job=job.snapshot(), **target)
    try:
        with _direct_write(ws):
            records = run(None)
    except (sync.SyncError, WriterUnavailable, ValueError) as exc:
        raise _http(exc) from exc
    record = _symbol_entry(ws, records[0])
    return SymbolSaveOut(record=record, **{**target, "library": record.library, "library_abs": record.library_abs})


@router.delete("/libraries/symbols/{name:path}", response_model=LibraryDeleteOut)
def delete_symbol(
    name: str,
    force: bool = Query(False, description="Auch löschen, wenn Bauteile das Symbol verwenden"),
    background: bool | None = None,
    ws: Workspace = Depends(require_workspace),
) -> LibraryDeleteOut:
    """Delete a symbol from its library and the registry (refused while parts use it)."""
    rec = registry.get_symbol(name)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Symbol „{name}“ ist nicht registriert.")
    return _delete("symbol", rec, force, background, ws)


# --------------------------------------------------------------------------- footprints


@router.get("/libraries/footprints", response_model=list[FootprintEntry])
def list_footprints(
    thumbnails: Thumbnails = Query("none", description="'svg' liefert eine Vorschau je Footprint"),
    theme: Theme = "dark",
    status: str | None = Query(None, description="ok, pending, missing oder error"),
    source: str | None = None,
    family: str | None = None,
    search: str | None = None,
    ws: Workspace = Depends(require_workspace),
) -> list[FootprintEntry]:
    """Registered footprints with status, usage count, ``content_hash`` (``?v=`` of the thumbnail)
    and (optionally) SVG thumbnails."""
    records = registry.list_footprints(
        status=status if status in ("ok", "pending", "missing", "error") else None,  # type: ignore[arg-type]
        source=source,
        family=family,
        with_spec=thumbnails == "svg",
    )
    chosen_theme = theme if thumbnails == "svg" else None
    loaded = thumbnails == "svg"
    hashes = _list_hashes("footprint", records, loaded)
    return [_footprint_entry(ws, rec, chosen_theme, spec_loaded=loaded, content_hash=hashes.get(rec.name.casefold()))
            for rec in records if _matches(rec, search)]


def _step_path(ws: Workspace, rec: FootprintRecord) -> Path | None:
    """The registered STEP file as the preview and the download find it (also a link next to the source
    library or a copy in the 3D folder); ``None`` if it does not exist."""
    from ..altium.step_preview import saved_model_path

    return saved_model_path(ws, rec)


@router.get("/libraries/footprints/{name:path}/step-models", response_model=FootprintStepModels)
def footprint_step_models(name: str, response: Response, ws: Workspace = Depends(require_workspace)) -> FootprintStepModels:
    """Read all STEP references, lazily extracting embedded data into the private cache.

    Import-time extraction is not required. Original library bytes and registry records
    are preserved. Generated STEP copies of existing prisms are omitted from the preview.
    """
    from ..altium.step_preview import remember_models, resolve_models

    with _direct_write(ws):
        rec = registry.get_footprint(name, with_usage=False)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Footprint „{name}“ ist nicht registriert.")
        models, warnings = resolve_models(ws, rec)
        remember_models(ws, rec, models)
        response.headers["Cache-Control"] = "private, no-cache"
        return FootprintStepModels(models=[FootprintStepModel(
            id=model.id, name=model.name,
            url=f"/api/libraries/footprints/{quote(rec.name, safe='')}/step-models/{model.id}",
            rotation=model.rotation, offset=model.offset,
        ) for model in models], warnings=warnings)


@router.get(
    "/libraries/footprints/{name:path}/step-models/{model_id}", response_class=Response,
    responses={200: {"content": {"model/step": {}}, "description": "STEP model at the requested revision"}},
)
def footprint_step_model(name: str, model_id: str, ws: Workspace = Depends(require_workspace)) -> Response:
    """Serve only a currently registered model; no caller-supplied file paths are accepted.

    The manifest's resolution is reused while record, library and model file are unchanged;
    otherwise (e.g. after a restart) the models are resolved again.
    """
    from ..altium.step_preview import cached_model, remember_models, resolve_models

    with _direct_write(ws):
        if len(model_id) != 64 or any(char not in "0123456789abcdef" for char in model_id):
            raise HTTPException(status_code=404, detail="Das STEP-Modell wurde nicht gefunden.")
        rec = registry.get_footprint(name, with_usage=False)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Footprint „{name}“ ist nicht registriert.")
        model = cached_model(ws, rec, model_id)
        if model is None:
            models, _ = resolve_models(ws, rec)
            remember_models(ws, rec, models)
            model = next((item for item in models if item.id == model_id), None)
        if model is None:
            raise HTTPException(status_code=404, detail="Das STEP-Modell wurde geändert oder ist nicht mehr verfügbar. Bitte die Vorschau neu laden.")
        try:
            data = model.read()
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="Das STEP-Modell wurde geändert oder ist nicht mehr verfügbar. Bitte die Vorschau neu laden.") from exc
        return Response(content=data, media_type="model/step", headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(model.name, safe='')}",
            "Cache-Control": "private, max-age=31536000, immutable",
            "ETag": f'"{model.id}"',
            "X-Content-Type-Options": "nosniff",
        })


@router.get(
    "/libraries/footprints/{name:path}/step",
    response_class=Response,
    responses={200: {"content": {"model/step": {}}, "description": "STEP-Modell des Footprints"}},
)
def download_step(name: str, ws: Workspace = Depends(require_workspace)) -> Response:
    """The footprint's STEP model (its model file, also one embedded in the source library, or generated
    from its 3D bodies). Unlike the preview, any file size is served."""
    from ..altium.step_preview import resolve_models

    with _direct_write(ws):
        rec = registry.get_footprint(name)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"Footprint „{name}“ ist nicht registriert.")
        models, warnings = resolve_models(ws, rec, limits=False)
        if models:
            return FileResponse(models[0].path, media_type="model/step", filename=models[0].name)
        if rec.spec is not None and rec.spec.bodies:
            from ..footprints import step_text

            try:
                text = step_text(rec.spec)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return Response(
                content=text.encode("ascii"),
                media_type="model/step",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(rec.name + '.step', safe='')}"},
            )
        # a referenced model that cannot be served says why (missing link, no STEP data …)
        raise HTTPException(status_code=404, detail=warnings[0] if warnings else f"Footprint „{rec.name}“ hat kein 3D-Modell.")


@router.get("/libraries/footprints/{name:path}/thumbnail.svg", response_class=Response, responses=_THUMBNAIL_RESPONSES)
def footprint_thumbnail(
    name: str,
    request: Request,
    theme: Theme = "dark",
    v: str | None = Query(None, description=_V_HELP),
    ws: Workspace = Depends(require_workspace),
) -> Response:
    """Thumbnail of a registered footprint (without grid and pad numbers; ETag/If-None-Match → 304;
    ``v`` = the entry's ``content_hash`` → cacheable forever)."""
    rec = registry.get_footprint(name, with_usage=False)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Footprint „{name}“ ist nicht registriert.")
    spec = rec.spec
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Für Footprint „{rec.name}“ ist keine Geometrie gespeichert.")
    content_hash = _content_hash("footprint", rec.name) or ""
    return _thumbnail_response(request, "footprint", rec.name, _thumbnail_etag(content_hash, theme), theme,
                               bool(v) and v == content_hash, lambda: _footprint_thumbnail(spec, theme))


@router.get("/libraries/footprints/{name:path}", response_model=FootprintDetail)
def get_footprint(
    name: str,
    theme: Theme = "dark",
    svg: bool = Query(True, description="SVG mitliefern (false: svg = null – schneller)"),
    ws: Workspace = Depends(require_workspace),
) -> FootprintDetail:
    """One footprint: record, geometry, SVG and the 3D data (bodies, height, STEP model)."""
    from ..footprints import render_svg

    rec = registry.get_footprint(name)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Footprint „{name}“ ist nicht registriert.")
    detail = FootprintDetail(record=_footprint_entry(ws, rec), spec=rec.spec)
    path = ws.abs(rec.library) if rec.library else None
    detail.file_exists = bool(path is not None and path.is_file())
    if rec.spec is not None:
        detail.bodies = list(rec.spec.bodies)
        detail.height = rec.spec.height
        try:
            if svg:
                detail.svg = render_svg(rec.spec, theme=theme)
        except Exception as exc:  # noqa: BLE001 - show the record even if the preview fails
            detail.warnings.append(f"Vorschau nicht möglich: {exc}")
    detail.warnings.extend(sync.component_warnings(rec))
    step = _step_path(ws, rec)
    file = rec.spec.step.file if rec.spec is not None and rec.spec.step is not None else rec.step_file
    if file:
        detail.step = FootprintStepInfo(file=file, path=str(step or ws.abs(file)), exists=step is not None)
    return detail


@router.put("/libraries/footprints/{name:path}", response_model=FootprintSaveOut)
def save_footprint(
    name: str,
    body: FootprintSaveIn,
    dry_run: bool = Query(False, description="Nur prüfen: nichts schreiben, Ziel melden"),
    ws: Workspace = Depends(require_workspace),
) -> FootprintSaveOut:
    """Save a footprint from the editor: register it and write it to its library (``dry_run``: only check)."""
    spec = body.spec
    if spec.name.casefold() != name.casefold():
        raise HTTPException(
            status_code=400,
            detail=f"Der Name im Pfad („{name}“) und im Footprint („{spec.name}“) stimmen nicht überein – Umbenennen wird "
            "nicht unterstützt; bitte als neuen Footprint speichern.",
        )
    existing = registry.get_footprint(spec.name)
    if existing is not None and existing.source == "external":
        raise HTTPException(status_code=409, detail=f"Footprint „{existing.name}“ gehört zu einer externen Bibliothek und ist schreibgeschützt.")
    problems = sync.validate_spec(spec)
    if problems:
        raise HTTPException(status_code=400, detail="Der Footprint kann nicht gespeichert werden: " + " ".join(problems[:8]))
    _check_library_choice(spec, body.library)
    conflict = sync.foreign_conflict(spec, library=body.library)
    if conflict:
        raise HTTPException(status_code=409, detail=conflict)
    library, library_abs = _target_library(ws, spec, library=body.library)
    target = {"library": library, "library_abs": library_abs, "new": existing is None,
              "usage": existing.usage if existing is not None else 0}
    if dry_run:
        return FootprintSaveOut(dry_run=True, unchanged=_footprint_unchanged(existing, spec, library, library_abs), **target)
    background = body.background if body.background is not None else sync.write_is_slow(spec, library=body.library)

    def run(ctx: JobContext | None) -> list[FootprintRecord]:
        return sync.ensure_footprints([spec], source=body.source, ctx=ctx, strict=True, library=body.library)

    if background:
        job = jobs.submit("libraries.save", f"Footprint {spec.name} speichern",
                          _held(ws.root, _save_job("Footprint", run)))
        return FootprintSaveOut(job=job.snapshot(), **target)
    try:
        with _direct_write(ws):
            records = run(None)
    except (sync.SyncError, WriterUnavailable, ValueError) as exc:
        raise _http(exc) from exc
    record = _footprint_entry(ws, records[0])
    return FootprintSaveOut(record=record, **{**target, "library": record.library, "library_abs": record.library_abs})


def _footprint_unchanged(existing: FootprintRecord | None, spec: FootprintSpec, library: str,
                         library_abs: str | None) -> bool:
    """Dry run: the save would write nothing (same geometry in the same, existing file). The STEP reference
    the save adds to footprints with 3D bodies is taken from the registered spec (best effort)."""
    if existing is None or existing.status != "ok" or existing.spec is None or not _same_library(existing.library, library):
        return False
    if existing.source == "altium":  # edited in Altium: a save from PartForge always replaces it (sync rule 3)
        return False
    if not library_abs or not Path(library_abs).is_file():
        return False
    candidate = spec
    if spec.bodies and spec.step is None and existing.spec.step is not None:
        candidate = spec.model_copy(update={"step": existing.spec.step})
    return sync.footprint_fingerprint(existing.spec) == sync.footprint_fingerprint(candidate)


@router.delete("/libraries/footprints/{name:path}", response_model=LibraryDeleteOut)
def delete_footprint(
    name: str,
    force: bool = Query(False, description="Auch löschen, wenn Bauteile den Footprint verwenden"),
    background: bool | None = None,
    ws: Workspace = Depends(require_workspace),
) -> LibraryDeleteOut:
    """Delete a footprint from its library and the registry (refused while parts use it)."""
    rec = registry.get_footprint(name)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"Footprint „{name}“ ist nicht registriert.")
    return _delete("footprint", rec, force, background, ws)


def _delete(kind: Literal["symbol", "footprint"], rec: SymbolRecord | FootprintRecord, force: bool,
            background: bool | None, ws: Workspace) -> LibraryDeleteOut:
    label = "Symbol" if kind == "symbol" else "Footprint"
    if rec.usage and not force:
        raise HTTPException(
            status_code=409,
            detail=f"{label} „{rec.name}“ wird von {plural(rec.usage, 'Bauteil', 'Bauteilen')} verwendet und wird daher "
            "nicht gelöscht "
            "(mit force=true trotzdem löschen).",
        )
    delete = sync.delete_symbols if kind == "symbol" else sync.delete_footprints
    slow = background if background is not None else (rec.source != "external" and sync.altium_bridge() is not None)
    if slow:
        run = _delete_job(label, rec.name, lambda ctx: delete([rec.name], force=force, ctx=ctx))
        job = jobs.submit("libraries.delete", f"{label} {rec.name} löschen", _held(ws.root, run))
        return LibraryDeleteOut(job=job.snapshot())
    try:
        with _direct_write(ws):
            result = LibraryDeleteResult.model_validate(delete([rec.name], force=force))
    except (sync.SyncError, WriterUnavailable) as exc:
        raise _http(exc) from exc
    if result.errors:
        raise HTTPException(status_code=409, detail=next(iter(result.errors.values())))
    return LibraryDeleteOut(result=result)


# --------------------------------------------------------------------------- sync, files, scan


@router.post("/libraries/sync")
def sync_libraries(ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Write every pending/failed symbol and footprint (job)."""
    job = jobs.submit("libraries.sync", "Bibliotheken synchronisieren", _held(ws.root, _sync_job))
    return {"job": job.snapshot()}


@router.get("/libraries/files", response_model=list[sync.LibraryFileInfo])
def library_files(
    layers: bool = Query(True, description="Lagen-Kopf der PcbLibs prüfen"),
    ws: Workspace = Depends(require_workspace),
) -> list[sync.LibraryFileInfo]:
    """Every library file: kind, components, size, date, managed by PartForge, in sync."""
    try:
        return sync.library_files(check_layers=layers)
    except (sync.SyncError, WriterUnavailable) as exc:
        raise _http(exc) from exc


@router.post("/libraries/scan")
def scan_libraries(body: LibraryScanIn | None = None, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Compare library files and registry, update the statuses (job)."""
    register = bool(body and body.register_unknown)
    job = jobs.submit("libraries.scan", "Bibliotheken prüfen",
                      _held(ws.root, lambda ctx: sync.scan_workspace(ctx, register=register)))
    return {"job": job.snapshot()}


@router.get("/libraries/health", response_model=LibraryHealthOut)
def library_health(
    refresh: bool = Query(False, description="Neu prüfen statt den zwischengespeicherten Bericht zu liefern"),
    ws: Workspace = Depends(require_workspace),
) -> LibraryHealthOut:
    """File-level checks: components exist in their files, part references resolve, pins match pads,
    unreadable library files, footprint heights are in the PcbLib. Every finding names the affected parts
    (``affected_parts``, ``part_numbers``); ``affected_part_numbers`` lists all of them. The report is cached
    per library state (registry, parts, files) – repeat requests are instant; ``refresh=true`` checks again."""
    try:
        report = sync.library_health(refresh=refresh)
    except (sync.SyncError, WriterUnavailable) as exc:
        raise _http(exc) from exc
    return LibraryHealthOut(**report)


@router.post("/libraries/restore-backup")
def restore_library_backup(body: LibraryRestoreIn, ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Job „Bibliothek aus Sicherung wiederherstellen“ (kind ``libraries.sync``): replace a damaged library file by its
    newest readable backup from ``Backups\\lib`` (fix action ``restore_library_backup`` of ``library_unreadable``) and
    write its components again from the registry. ``job.result``: ``library, backup, damaged, components, rewritten,
    errors, message``."""
    job = jobs.submit("libraries.sync", "Bibliothek aus Sicherung wiederherstellen",
                      _held(ws.root, lambda ctx: sync.restore_library_backup(body.library, ctx=ctx)))
    return {"job": job.snapshot()}


@router.post("/libraries/footprint-heights/repair")
def repair_footprint_heights(body: HeightRepairIn | None = None, ws: Workspace = Depends(require_workspace)
                             ) -> dict[str, Any]:
    """Job „Footprint-Höhen nachtragen“ (kind ``libraries.sync``): rewrite the footprints whose PcbLib
    lacks their height (finding ``footprint_height_missing``) through the normal sync path.
    ``job.result``: ``checked, rewritten, skipped, errors, remaining, libraries, message``."""
    names = list(body.names) if body is not None and body.names is not None else None
    job = jobs.submit("libraries.sync", "Footprint-Höhen nachtragen",
                      _held(ws.root, lambda ctx: sync.repair_footprint_heights(names, ctx=ctx)))
    return {"job": job.snapshot()}


# --------------------------------------------------------------------------- external libraries


@router.get("/libraries/external", response_model=list[sync.ExternalLibrary])
def list_external(ws: Workspace = Depends(require_workspace)) -> list[sync.ExternalLibrary]:
    return sync.list_external_libraries()


@router.post("/libraries/external", response_model=sync.ExternalLibrary)
def add_external(body: ExternalLibraryIn, ws: Workspace = Depends(require_workspace)) -> sync.ExternalLibrary:
    """Register an existing SchLib/PcbLib read-only (PartForge never writes it)."""
    try:
        with _direct_write(ws):
            return sync.add_external_library(body.path)
    except (sync.SyncError, WriterUnavailable) as exc:
        raise _http(exc) from exc


@router.delete("/libraries/external/{library_id}", response_model=ExternalRemoveOut)
def remove_external(library_id: str, ws: Workspace = Depends(require_workspace)) -> ExternalRemoveOut:
    """Unregister an external library (components registered from it stay usable)."""
    try:
        with _direct_write(ws):
            return ExternalRemoveOut.model_validate(sync.remove_external_library(library_id))
    except sync.SyncError as exc:
        raise _http(exc) from exc


@router.get("/libraries/external/{library_id}/components", response_model=ExternalComponentsOut)
def external_components(
    library_id: str,
    previews: bool = Query(False, description="SVG-Vorschau je Bauteil"),
    search: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    theme: Theme = "dark",
    ws: Workspace = Depends(require_workspace),
) -> ExternalComponentsOut:
    """Components of an external library (names, metadata, optional previews)."""
    try:
        page = sync.external_components(
            library_id, previews=previews, search=search, offset=offset, limit=limit, theme=theme
        )
    except (sync.SyncError, WriterUnavailable) as exc:
        raise _http(exc) from exc
    return ExternalComponentsOut.model_validate(page)


@router.post("/libraries/external/{library_id}/use", response_model=SymbolEntry | FootprintEntry)
def use_external(library_id: str, body: ExternalUseIn, ws: Workspace = Depends(require_workspace)) -> SymbolEntry | FootprintEntry:
    """Register one component of an external library so parts can reference it."""
    try:
        with _direct_write(ws):
            rec = sync.use_external_component(library_id, body.name)
    except (sync.SyncError, WriterUnavailable) as exc:
        raise _http(exc) from exc
    if isinstance(rec, SymbolRecord):
        return _symbol_entry(ws, rec)
    return _footprint_entry(ws, rec)


# --------------------------------------------------------------------------- layer stack


def _layer_stack_out(stack: stackup.LayerStack, ws: Workspace | None, notes: list[str]) -> LayerStackOut:
    layer_map = ws.settings.layers if ws is not None else None
    return LayerStackOut(
        stack=stack,
        notes=notes,
        layer_map=layer_map,
        suggested_layer_map=stackup.suggest_layer_map(stack, layer_map),
        issues=stackup.layer_map_issues(stack, layer_map) if layer_map is not None else [],
        patch_enabled=stackup.header_patch_enabled(),
    )


@router.get("/libraries/layer-stack", response_model=LayerStackOut)
def get_layer_stack(ws: Workspace = Depends(require_workspace)) -> LayerStackOut:
    """Mechanical layer stack of the workspace (file or built-in standard) and LayerMap hints."""
    stack, notes = stackup.workspace_stack(ws)
    return _layer_stack_out(stack, ws, notes)


@router.post("/libraries/layer-stack/parse", response_model=LayerStackOut)
def parse_layer_stack(body: LayerStackParseIn, ws: Workspace = Depends(require_workspace)) -> LayerStackOut:
    """Read an Altium .stackup file (preview before it is set in the workspace settings)."""
    try:
        stack = stackup.parse_stackup(body.path)
    except stackup.StackupError as exc:
        raise _http(exc) from exc
    return _layer_stack_out(stack, ws, [])


@router.post("/libraries/layer-set/parse", response_model=LayerSetParseOut)
def parse_layer_set(body: LayerSetParseIn, ws: Workspace = Depends(require_workspace)) -> LayerSetParseOut:
    """Read an Altium ``.layerset`` file (the user layer sets it contains) – to choose one for the settings."""
    path = body.path.strip().strip('"')
    if not path or not Path(path).is_absolute():
        raise HTTPException(status_code=400, detail="Bitte den absoluten Pfad einer .layerset-Datei angeben.")
    try:
        return LayerSetParseOut(file=path, sets=layersets.parse_layerset_file(path))
    except layersets.LayerSetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/libraries/layer-set/builtin", response_model=layersets.LayerSetDef)
def builtin_layer_set(body: LayerSetBuiltinIn, ws: Workspace = Depends(require_workspace)) -> layersets.LayerSetDef:
    """The layer set built from a layer map (copper, paste, overlay, solder, drill, keep-out and the mechanical
    layers PartForge draws on) – for the standard map exactly Altium's "Component Layers" of the user."""
    return layersets.builtin_layer_set(body.layers or ws.settings.layers, current=body.current)


@router.post("/libraries/layer-stack/apply")
def apply_layer_stack(ws: Workspace = Depends(require_workspace)) -> dict[str, Any]:
    """Write the workspace layer stack into the header of every PcbLib (job)."""
    job = jobs.submit("libraries.layers", "Lagen der Footprint-Bibliotheken anpassen",
                      _held(ws.root, sync.apply_layer_stack))
    return {"job": job.snapshot()}
