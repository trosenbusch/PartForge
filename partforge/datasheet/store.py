"""Datasheet storage: content-addressed PDFs in the workspace, records in ``pf_datasheets``, page renders.

* PDFs live in ``<workspace>/Datasheets/<ascii-name>_<sha8>.pdf``; the record id is ``sha256[:16]`` of the
  content, so the same PDF is stored once (re-uploads return the existing record).
* ``DatasheetRecord.extraction`` holds a :class:`~.models.DatasheetMeta` (text-layer analysis, source URL,
  extraction result, API runs and costs, commits).
* Page renders and the text layer are cached in the **local** app data folder (:func:`cache_root`:
  ``%LOCALAPPDATA%\\PartForge\\Cache\\datasheets\\<id>``, at most :data:`CACHE_LIMIT_BYTES`), not in the workspace (they
  can always be recreated) and never in the roaming profile (it would travel with every logon); the cache of older
  versions in ``%APPDATA%\\PartForge\\cache\\datasheets`` is removed once. :func:`read_texts` needs no database (jobs
  read the PDF before they hold the library for the short write).
* URL import downloads with httpx (http/https only, size limit, PDF signature check).
* **Metadata updates** are read-modify-write of one JSON document: every writer holds :func:`meta_lock` for the
  datasheet and re-reads the record inside it (:func:`update_meta`) – concurrent jobs (text-layer reading, analysis,
  commit) and kept results never overwrite each other's changes.
* **Results of a closed library** (library guard, ARCHITEKTUR §8.4): an analysis whose library was switched or
  closed meanwhile keeps its paid result as :class:`~.models.PendingResult` in that library's folder
  (``<Datasheets>/.pending/*.json``, :func:`save_pending`); :func:`apply_pending` merges such files into
  ``pf_datasheets`` when the library is open again (idempotent: a run that is already listed is not added twice).
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from platformdirs import user_cache_dir

from ..config import APP_NAME, app_data_dir
from ..db import registry
from ..db.models import DatasheetRecord
from ..domain.text import ascii_name, clean_free_text
from ..workspace import Workspace, current
from . import pdf as pdfio
from .errors import DatasheetError, DatasheetNotFound, InvalidPdf
from .models import META_FORMAT, PENDING_FORMAT, DatasheetMeta, PageInfo, PendingResult
from .pages import page_infos

log = logging.getLogger(__name__)

__all__ = [
    "MAX_PDF_BYTES",
    "ID_PATTERN",
    "PENDING_DIR",
    "add_runs",
    "analyze",
    "apply_pending",
    "apply_result",
    "cache_dir",
    "cache_root",
    "delete_datasheet",
    "download_pdf",
    "get_record",
    "ingest_bytes",
    "load_meta",
    "meta_lock",
    "page_png",
    "pdf_path",
    "pending_files",
    "read_texts",
    "save_meta",
    "save_pending",
    "update_meta",
]

MAX_PDF_BYTES = 64 * 1024 * 1024
ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
DPI_MIN, DPI_MAX, DPI_DEFAULT = 36, 300, 110
CACHE_LIMIT_BYTES = 512 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PartForge/1.0 (Datenblatt-Import)"
_ACCEPTED_TYPES = {
    "application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream", "application/download",
    "application/force-download", "application/x-download", "",
}

_ingest_lock = threading.Lock()
# read-modify-write of a datasheet's metadata (lock striping keeps the number of locks bounded)
_META_LOCKS = tuple(threading.RLock() for _ in range(32))
_render_count = 0
_render_lock = threading.Lock()
# one render per cached file at a time (lock striping keeps the number of locks bounded)
_TARGET_LOCKS = tuple(threading.Lock() for _ in range(32))
_REPLACE_ATTEMPTS = 20
_REPLACE_DELAY_S = 0.05


def now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- records and metadata


def check_id(datasheet_id: str) -> str:
    if not ID_PATTERN.match(datasheet_id or ""):
        raise DatasheetNotFound(datasheet_id)
    return datasheet_id


def get_record(datasheet_id: str) -> DatasheetRecord:
    rec = registry.get_datasheet(check_id(datasheet_id))
    if rec is None:
        raise DatasheetNotFound(datasheet_id)
    return rec


def load_meta(rec: DatasheetRecord) -> DatasheetMeta:
    raw = rec.extraction
    if isinstance(raw, dict) and raw.get("format") == META_FORMAT:
        try:
            return DatasheetMeta.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - damaged JSON must not block the datasheet
            log.warning("Metadaten von Datenblatt %s ungültig, werden neu angelegt: %s", rec.id, exc)
    return DatasheetMeta()


def save_meta(rec: DatasheetRecord, meta: DatasheetMeta, **updates: Any) -> DatasheetRecord:
    """Store ``meta`` (and record fields) – callers that read the metadata first hold :func:`meta_lock`."""
    data = rec.model_copy(update={**updates, "extraction": meta.model_dump(mode="json")})
    return registry.upsert_datasheet(data)


@contextmanager
def meta_lock(datasheet_id: str) -> Iterator[None]:
    """Serialise the read-modify-write of one datasheet's metadata (reentrant)."""
    with _META_LOCKS[hash(datasheet_id) % len(_META_LOCKS)]:
        yield


def update_meta(datasheet_id: str, change: Callable[[DatasheetRecord, DatasheetMeta], dict[str, Any] | None]
                ) -> DatasheetRecord:
    """Re-read the record under :func:`meta_lock`, let ``change(record, meta)`` modify the metadata (it may return
    record fields to update) and store it."""
    with meta_lock(datasheet_id):
        rec = get_record(datasheet_id)
        meta = load_meta(rec)
        updates = change(rec, meta) or {}
        return save_meta(rec, meta, **updates)


def pdf_path(rec: DatasheetRecord, ws: Workspace | None = None) -> Path:
    ws = ws or current()
    path = ws.abs(rec.file)
    if path is None or not path.is_file():
        raise DatasheetError(f"Die PDF-Datei des Datenblatts fehlt ({rec.file}). Bitte das Datenblatt erneut laden.")
    return path


# --------------------------------------------------------------------------- ingest


def _file_name(original: str, sha: str) -> str:
    stem = Path(original or "Datenblatt").stem
    safe = ascii_name(stem, max_len=60, fallback="Datenblatt").replace(" ", "_")
    return f"{safe}_{sha[:8]}.pdf"


def ingest_bytes(data: bytes, filename: str, *, source_url: str | None = None,
                 ws: Workspace | None = None) -> tuple[DatasheetRecord, bool]:
    """Store a PDF content-addressed and register it. Returns (record, duplicate)."""
    if not data:
        raise InvalidPdf("Die Datei ist leer.")
    if len(data) > MAX_PDF_BYTES:
        raise InvalidPdf(f"Die Datei ist zu groß ({len(data) / 1e6:.0f} MB, höchstens {MAX_PDF_BYTES // 2**20} MB).")
    if not data[:1024].lstrip().startswith(pdfio.PDF_MAGIC) and pdfio.PDF_MAGIC not in data[:1024]:
        raise InvalidPdf("Die Datei ist kein PDF (Signatur %PDF fehlt).")
    info = pdfio.pdf_info(data)  # raises InvalidPdf for unreadable / password protected files
    ws = ws or current()
    sha = hashlib.sha256(data).hexdigest()
    datasheet_id = sha[:16]
    base_name = Path(str(filename or "Datenblatt.pdf").replace("\\", "/")).name
    original = clean_free_text(base_name, max_len=200).replace("/", "-") or "Datenblatt.pdf"
    with _ingest_lock:
        existing = registry.get_datasheet(datasheet_id)
        if existing is not None:
            path = ws.abs(existing.file)
            if path is None or not path.is_file():  # file was removed: restore it
                target = ws.datasheets_dir / _file_name(existing.original_name, sha)
                _write_atomic(target, data)
                existing = registry.upsert_datasheet(existing.model_copy(update={"file": ws.rel(target)}))
            if source_url:
                with meta_lock(datasheet_id):
                    existing = registry.get_datasheet(datasheet_id) or existing
                    meta = load_meta(existing)
                    if not meta.source_url:
                        meta.source_url = source_url
                        existing = save_meta(existing, meta)
            return existing, True
        target = ws.datasheets_dir / _file_name(original, sha)
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() != sha:
            target = ws.datasheets_dir / f"{target.stem}_{sha[8:16]}.pdf"
        if not target.is_file():
            _write_atomic(target, data)
        meta = DatasheetMeta(source_url=source_url, size_bytes=len(data), encrypted=info.encrypted)
        rec = DatasheetRecord(
            id=datasheet_id, file=ws.rel(target), original_name=original, title=info.title,
            page_count=info.page_count, extraction=meta.model_dump(mode="json"),
        )
        rec = registry.upsert_datasheet(rec)
    log.info("Datenblatt %s gespeichert: %s (%d Seiten)", datasheet_id, target.name, info.page_count)
    return rec, False


def _target_lock(target: Path) -> threading.Lock:
    return _TARGET_LOCKS[hash(os.path.normcase(str(target))) % len(_TARGET_LOCKS)]


def _write_atomic(target: Path, data: bytes) -> None:
    """Write via a temp file of this thread and rename it into place.

    On Windows the rename fails while another thread still reads the target (page images are served from a thread
    pool): it is retried briefly; if the target exists afterwards it is kept (every file written here is derived from
    content-addressed data, so an existing one has the same content)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_bytes(data)
    try:
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                tmp.replace(target)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    if target.is_file():
                        log.debug("%s wird gerade gelesen – vorhandene Datei bleibt", target)
                        return
                    raise
                time.sleep(_REPLACE_DELAY_S)
    finally:
        tmp.unlink(missing_ok=True)


TEXT_CACHE_VERSION = 1


def _text_cache(datasheet_id: str) -> Path:
    return cache_dir(datasheet_id) / f"text-v{TEXT_CACHE_VERSION}.json"


def _load_texts(datasheet_id: str, page_count: int) -> pdfio.PdfInfo | None:
    """Cached text layer (app data, keyed by the content hash); ``None`` when missing or unusable."""
    path = _text_cache(datasheet_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = [pdfio.PageText(**p) for p in data["pages"]]
        info = pdfio.PdfInfo(page_count=int(data["page_count"]), encrypted=bool(data["encrypted"]),
                             title=data.get("title"), pages=pages)
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return info if info.page_count == len(pages) and (not page_count or info.page_count == page_count) else None


def _save_texts(datasheet_id: str, info: pdfio.PdfInfo) -> None:
    data = {"page_count": info.page_count, "encrypted": info.encrypted, "title": info.title,
            "pages": [dataclasses.asdict(p) for p in info.pages]}
    try:
        _write_atomic(_text_cache(datasheet_id), json.dumps(data, ensure_ascii=False).encode("utf-8"))
    except OSError as exc:  # the cache is an optimisation only
        log.debug("Textcache für %s nicht geschrieben: %s", datasheet_id, exc)


def read_texts(rec: DatasheetRecord, *, ws: Workspace | None = None, force: bool = False,
               progress: Callable[[int, int], None] | None = None) -> pdfio.PdfInfo:
    """Text layer of every page – from the cache in the app data folder (keyed by the content hash) or read from the
    PDF and cached. Touches no database: jobs call it before they hold the library for the short write."""
    info = None if force else _load_texts(rec.id, rec.page_count)
    if info is None:
        info = pdfio.read_page_texts(pdf_path(rec, ws), progress=progress)
        _save_texts(rec.id, info)
    return info


def analyze(rec: DatasheetRecord, *, ws: Workspace | None = None, force: bool = False,
            progress: Callable[[int, int], None] | None = None) -> tuple[DatasheetRecord, list[pdfio.PageText]]:
    """Text-layer analysis (page quality and keyword categories); stored in the record metadata.

    The page texts are cached in the app data folder (the PDF is content-addressed, so the cache never goes
    stale). Returns the updated record and the page texts (for the page triage)."""
    path = pdf_path(rec, ws)
    info = read_texts(rec, ws=ws, force=force, progress=progress)
    with meta_lock(rec.id):
        rec = get_record(rec.id)  # the current state (another job may have written meanwhile; deleted: 404)
        meta = load_meta(rec)
        if force or not meta.pages or len(meta.pages) != info.page_count:
            meta.pages = page_infos(info.pages)
            meta.analyzed = now_iso()
            meta.encrypted = info.encrypted
            meta.size_bytes = meta.size_bytes or path.stat().st_size
            rec = save_meta(rec, meta, page_count=info.page_count,
                            text_pages=[p.page for p in meta.pages if p.quality == "ok"],
                            title=rec.title or info.title)
    return rec, info.pages


def page_list(rec: DatasheetRecord) -> list[PageInfo]:
    return load_meta(rec).pages


# --------------------------------------------------------------------------- URL import


def _filename_from(response: Any, url: str) -> str:
    disposition = response.headers.get("content-disposition", "") if response is not None else ""
    m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", disposition)
    if m:
        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition)
    if m:
        return m.group(1).strip()
    path = urlparse(str(getattr(response, "url", "") or url)).path
    name = unquote(path.rsplit("/", 1)[-1]) if path else ""
    return name or "Datenblatt.pdf"


def download_pdf(url: str, *, max_bytes: int = MAX_PDF_BYTES, timeout_s: float = 60.0,
                 transport: Any = None, cancelled: Callable[[], bool] | None = None) -> tuple[bytes, str, str]:
    """Download a PDF (http/https). Returns (bytes, file name, final URL). German errors."""
    import httpx

    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise DatasheetError("Bitte eine vollständige Web-Adresse angeben (http:// oder https://).")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.5"}
    data = bytearray()
    try:
        with httpx.Client(follow_redirects=True, max_redirects=5, timeout=httpx.Timeout(timeout_s, connect=15.0),
                          headers=headers, transport=transport) as client, client.stream("GET", url.strip()) as response:
            if response.status_code >= 400:
                raise DatasheetError(f"Download fehlgeschlagen: Der Server antwortet mit HTTP {response.status_code}.")
            ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if ctype not in _ACCEPTED_TYPES and not ctype.endswith("/pdf"):
                if ctype.startswith("text/") or "html" in ctype:
                    raise DatasheetError("Die Adresse liefert eine Webseite statt eines PDFs – bitte den direkten "
                                         "Link auf die PDF-Datei verwenden.")
                raise DatasheetError(f"Die Adresse liefert keinen PDF-Inhalt (Typ „{ctype}“).")
            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise DatasheetError(f"Das PDF ist zu groß ({int(length) / 1e6:.0f} MB, höchstens "
                                     f"{max_bytes // 2**20} MB).")
            for chunk in response.iter_bytes():
                if cancelled is not None and cancelled():
                    from ..jobs import JobCancelled

                    raise JobCancelled()
                data += chunk
                if len(data) > max_bytes:
                    raise DatasheetError(f"Das PDF ist zu groß (mehr als {max_bytes // 2**20} MB).")
            name = _filename_from(response, url)
            final_url = str(response.url)
    except DatasheetError:
        raise
    except httpx.TimeoutException as exc:
        raise DatasheetError("Zeitüberschreitung beim Download des Datenblatts – bitte später erneut versuchen.") from exc
    except httpx.HTTPError as exc:
        raise DatasheetError(
            f"Download fehlgeschlagen ({type(exc).__name__}) – Adresse und Internetverbindung prüfen.") from exc
    body = bytes(data)
    if pdfio.PDF_MAGIC not in body[:1024]:
        raise DatasheetError("Die heruntergeladene Datei ist kein PDF.")
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    return body, name, final_url


# --------------------------------------------------------------------------- renders


_legacy_lock = threading.Lock()
_legacy_checked: set[str] = set()


def cache_root() -> Path:
    """Folder of the datasheet caches (page renders, text layers – always recreatable).

    ``%LOCALAPPDATA%\\PartForge\\Cache\\datasheets`` (``platformdirs.user_cache_dir``): never the roaming profile,
    which would carry up to :data:`CACHE_LIMIT_BYTES` of renders at every logon and logoff. Isolated runs
    (``PARTFORGE_HOME``: tests, test servers) keep everything in their folder: ``<home>\\cache\\datasheets``. The
    cache of older versions in the roaming folder is removed once per process (in the background)."""
    override = os.environ.get("PARTFORGE_HOME")
    base = Path(override) / "cache" if override else Path(user_cache_dir(APP_NAME, appauthor=False))
    root = base / "datasheets"
    _forget_legacy_cache(app_data_dir() / "cache" / "datasheets", root)
    return root


def _forget_legacy_cache(legacy: Path, current: Path) -> None:
    """Remove the render cache of older versions (``%APPDATA%\\PartForge\\cache\\datasheets``, roaming) once – in a
    background thread, it may hold many files; never the current cache."""
    key = os.path.normcase(os.path.abspath(legacy))
    with _legacy_lock:
        if key in _legacy_checked:
            return
        _legacy_checked.add(key)
    if key == os.path.normcase(os.path.abspath(current)) or not legacy.is_dir():
        return

    def remove() -> None:
        shutil.rmtree(legacy, ignore_errors=True)
        try:
            legacy.parent.rmdir()  # the old "cache" folder, if nothing else is in it
        except OSError:
            pass
        log.info("Alter Datenblatt-Cache im servergespeicherten Profil entfernt: %s", legacy)

    threading.Thread(target=remove, name="partforge-old-cache", daemon=True).start()


def cache_dir(datasheet_id: str) -> Path:
    return cache_root() / check_id(datasheet_id)


def clamp_dpi(dpi: float | int | None) -> int:
    if dpi is None:
        return DPI_DEFAULT
    return int(max(DPI_MIN, min(DPI_MAX, round(float(dpi)))))


def page_png(rec: DatasheetRecord, page: int, dpi: float | int | None = None, *, ws: Workspace | None = None) -> Path:
    """Cached PNG of a page (colour, for the UI)."""
    if page < 1 or (rec.page_count and page > rec.page_count):
        raise DatasheetError(f"Seite {page} gibt es im Datenblatt nicht (1–{rec.page_count}).")
    resolution = clamp_dpi(dpi)
    folder = cache_dir(rec.id)
    target = folder / f"p{page:03d}_{resolution}.png"
    if _cached(target):
        return target
    with _target_lock(target):  # parallel requests for the same page render it once
        if _cached(target):
            return target
        png, _size = pdfio.render_page(pdf_path(rec, ws), page, dpi=resolution)
        folder.mkdir(parents=True, exist_ok=True)
        _write_atomic(target, png)
    _maybe_prune()
    return target


def _cached(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:  # removed concurrently (cache pruning)
        return False


def _maybe_prune() -> None:
    global _render_count
    with _render_lock:
        _render_count += 1
        due = _render_count % 100 == 0
    if due:
        prune_cache()


def prune_cache(limit_bytes: int = CACHE_LIMIT_BYTES) -> int:
    """Delete the oldest cached renders above ``limit_bytes``; returns the number of removed files."""
    root = cache_root()
    if not root.is_dir():
        return 0
    files = [(p.stat().st_mtime, p.stat().st_size, p) for p in root.rglob("*.png") if p.is_file()]
    total = sum(size for _, size, _ in files)
    removed = 0
    for _mtime, size, path in sorted(files):
        if total <= limit_bytes:
            break
        try:
            path.unlink()
            total -= size
            removed += 1
        except OSError:
            continue
    return removed


# --------------------------------------------------------------------------- delete


def _referencing_parts(file_name: str) -> int:
    """Number of parts whose datasheet link points at this PDF (by file name)."""
    from ..db import categories, parts
    from ..db.models import PartFilter

    count = 0
    for cat in categories.list_categories(with_counts=False):
        if cat.field("ComponentLink1URL") is None:
            continue
        try:
            _rows, total = parts.query_parts(
                cat.table, filters=[PartFilter(column="ComponentLink1URL", op="contains", value=file_name)], limit=1)
        except Exception:  # noqa: BLE001 - a broken category must not block the deletion check
            continue
        count += int(total)
    return count


def delete_datasheet(datasheet_id: str, *, delete_file: bool = True, ws: Workspace | None = None) -> dict[str, Any]:
    """Remove the record and the cached renders; the PDF is deleted unless parts link to it."""
    rec = get_record(datasheet_id)
    ws = ws or current()
    path = ws.abs(rec.file)
    file_deleted = False
    kept_reason = None
    if delete_file and path is not None and path.is_file():
        in_use = _referencing_parts(path.name)
        inside = ws.datasheets_dir.resolve() in path.resolve().parents
        if in_use:
            kept_reason = f"PDF bleibt erhalten: {in_use} Bauteil(e) verlinken es."
        elif not inside:
            kept_reason = "PDF liegt außerhalb des Datenblatt-Ordners und bleibt erhalten."
        else:
            try:
                path.unlink()
                file_deleted = True
            except OSError as exc:
                kept_reason = f"PDF konnte nicht gelöscht werden ({exc.strerror or exc})."
    registry.delete_datasheet(rec.id)
    shutil.rmtree(cache_dir(rec.id), ignore_errors=True)
    log.info("Datenblatt %s gelöscht (Datei gelöscht: %s)", rec.id, file_deleted)
    return {"id": rec.id, "file_deleted": file_deleted, "message": kept_reason}


# --------------------------------------------------------------------------- results of a closed library

PENDING_DIR = ".pending"
_PENDING_NAME = re.compile(r"^[0-9a-f]{16}_[0-9A-Za-z_.-]+\.json$")


def _pending_dir(ws: Workspace) -> Path:
    return ws.datasheets_dir / PENDING_DIR


def save_pending(ws: Workspace, result: PendingResult) -> Path:
    """Keep ``result`` in the folder of the library ``ws`` (whether it is open or not); returns the file."""
    check_id(result.datasheet_id)
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    target = _pending_dir(ws) / f"{result.datasheet_id}_{stamp}.json"
    _write_atomic(target, result.model_dump_json(indent=1).encode("utf-8"))
    log.info("Ergebnis für Datenblatt %s in %s gesichert (Bibliothek nicht geöffnet)", result.datasheet_id, target)
    return target


def pending_files(ws: Workspace) -> list[Path]:
    """Kept results of the library ``ws`` (oldest first)."""
    folder = _pending_dir(ws)
    try:
        return sorted(p for p in folder.iterdir() if p.is_file() and _PENDING_NAME.match(p.name))
    except OSError:  # no folder: nothing kept
        return []


def add_runs(rec: DatasheetRecord, runs: list[Any]) -> DatasheetRecord:
    """Add paid calls made for this datasheet elsewhere (e.g. the datasheet search that found it) – a run that is
    already listed (all fields equal) is not added twice."""
    with meta_lock(rec.id):
        rec = get_record(rec.id)
        meta = load_meta(rec)
        new = [run for run in runs if run not in meta.runs]
        if not new:
            return rec
        meta.runs = [*meta.runs, *new]
        meta.cost_usd = round(sum(run.cost_usd for run in meta.runs), 6)
        return save_meta(rec, meta)


def apply_result(rec: DatasheetRecord, result: PendingResult, *, once: bool = False) -> DatasheetRecord:
    """Merge a result into the record of the open library: its paid calls, the extraction (unless the record has a
    newer one) or the reason of the failure. ``once`` (kept files): a run that is already listed with all fields
    equal is not added again – applying the same file twice (e.g. after a crash) never counts its costs twice."""
    with meta_lock(rec.id):
        rec = get_record(rec.id)  # the current state (another job may have written meanwhile; deleted: 404)
        return _apply_result(rec, load_meta(rec), result, once)


def _apply_result(rec: DatasheetRecord, meta: DatasheetMeta, result: PendingResult, once: bool) -> DatasheetRecord:
    runs = [run for run in result.runs if run not in meta.runs] if once else list(result.runs)
    meta.runs = [*meta.runs, *runs]
    meta.cost_usd = round(sum(run.cost_usd for run in meta.runs), 6)
    updates: dict[str, Any] = {}
    newer = not meta.extracted or (result.extracted or result.created) >= meta.extracted
    if result.kind == "extraction" and result.extraction is not None and newer:
        meta.extraction = result.extraction
        meta.raw = result.raw
        meta.model, meta.effort, meta.extracted = result.model, result.effort, result.extracted
        meta.selected_pages, meta.selection_method = list(result.selected_pages), result.selection_method
        meta.identity_pages, meta.geometry_pages = list(result.identity_pages), list(result.geometry_pages)
        meta.edited = False
        meta.last_error = None
        updates = {"manufacturer": result.manufacturer or rec.manufacturer, "mpns": result.mpns or rec.mpns,
                   "title": result.title or rec.title}
    elif result.kind == "failure" and newer:
        meta.last_error = result.last_error
    return save_meta(rec, meta, **updates)


def apply_pending(ws: Workspace) -> list[str]:
    """Merge every kept result of the library ``ws`` into its records (the caller holds that library, which must be the
    open one). Returns the datasheet ids; a result whose datasheet was deleted meanwhile is renamed to ``*.orphan``;
    an unreadable file stays for the next attempt."""
    applied: list[str] = []
    for path in pending_files(ws):
        try:
            result = PendingResult.model_validate_json(path.read_text(encoding="utf-8"))
            if result.format != PENDING_FORMAT:
                raise ValueError(f"unbekanntes Format {result.format!r}")
        except (OSError, ValueError) as exc:
            log.warning("Gesichertes Datenblatt-Ergebnis %s nicht lesbar: %s", path, exc)
            continue
        rec = registry.get_datasheet(result.datasheet_id)
        if rec is None:
            log.warning("Datenblatt %s gibt es nicht mehr – gesichertes Ergebnis %s bleibt als .orphan liegen",
                        result.datasheet_id, path.name)
            path.replace(path.with_suffix(".orphan"))
            continue
        apply_result(rec, result, once=True)
        path.unlink(missing_ok=True)
        applied.append(result.datasheet_id)
        log.info("Gesichertes Ergebnis für Datenblatt %s übernommen (%s)", result.datasheet_id, path.name)
    return applied
