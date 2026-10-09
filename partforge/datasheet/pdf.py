"""PDF input/output for the datasheet import: text layer, page subsets and page renders.

* Text (pypdf): per page, with glyph-ID detection (``/g27/g16…`` from pypdf, ``(cid:12)`` from
  pdfminer) and the ``chr(N + 29)`` decoding that restores e.g. Microchip package pages.
* Owner-password PDFs (encrypted, empty user password) are opened with ``decrypt("")``; subsets
  written for Claude are always unencrypted (the API rejects encrypted PDFs).
* Renders (pypdfium2): PDFium is **not thread-safe** – every PDFium call runs under
  :data:`PDFIUM_LOCK` (FastAPI serves page images from a thread pool, jobs render in parallel).

Nothing here touches the database or the workspace.
"""
from __future__ import annotations

import io
import logging
import math
import re
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..domain.text import clean_free_text
from .errors import InvalidPdf

log = logging.getLogger(__name__)

__all__ = [
    "PDFIUM_LOCK",
    "PageText",
    "PdfInfo",
    "decode_glyph_text",
    "glyph_ratio",
    "pdf_info",
    "read_page_texts",
    "render_page",
    "subset_pdf",
    "visual_tokens",
]

PDFIUM_LOCK = threading.RLock()
PDF_MAGIC = b"%PDF-"

# Vision limits of the high-resolution tier (claude-api.md §8): long edge <= 2576 px and
# ceil(w/28)*ceil(h/28) <= 4784 visual tokens; larger images are downscaled by the API anyway.
VISION_MAX_EDGE = 2576
VISION_MAX_TOKENS = 4784
# Renders for the UI: cap the bitmap size (A0 drawings at 300 dpi would need >100 MP).
UI_MAX_EDGE = 6000

_GLYPH_TOKEN = re.compile(r"/g\d{1,4}|\(cid:\d{1,5}\)")
_PYPDF_GLYPH = re.compile(r"/g(\d{1,4})")
_WS = re.compile(r"\s+")

_quiet_done = False


def _quiet_pypdf() -> None:
    """pypdf logs a warning per font it cannot fully parse (fontTools missing) – silence that noise once."""
    global _quiet_done
    if not _quiet_done:
        logging.getLogger("pypdf").setLevel(logging.ERROR)
        _quiet_done = True


# --------------------------------------------------------------------------- reading


def _damaged(exc: BaseException) -> InvalidPdf:
    return InvalidPdf(f"Die Datei ist kein lesbares PDF ({type(exc).__name__}). Bitte das Datenblatt erneut laden.")


def _reader(source: Path | bytes):  # -> pypdf.PdfReader (import kept local: pypdf is heavy)
    """pypdf reader (owner-password files decrypted). Every parser error of a damaged file – pypdf also raises
    AssertionError, AttributeError, IndexError, NotImplementedError … – becomes :class:`InvalidPdf`."""
    _quiet_pypdf()
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else str(source), strict=False)
        encrypted = bool(reader.is_encrypted)
        if encrypted:
            try:
                ok = reader.decrypt("")
            except Exception as exc:  # noqa: BLE001 - unsupported crypto, damaged file
                raise InvalidPdf(
                    "Das PDF ist verschlüsselt und lässt sich ohne Passwort nicht öffnen. "
                    "Bitte eine ungeschützte Fassung des Datenblatts verwenden."
                ) from exc
            if not ok:
                raise InvalidPdf(
                    "Das PDF ist mit einem Passwort geschützt. Bitte eine ungeschützte Fassung des Datenblatts verwenden."
                )
        if len(reader.pages) < 1:  # forces parsing of the page tree
            raise InvalidPdf("Die Datei ist kein lesbares PDF (keine Seiten). Bitte das Datenblatt erneut laden.")
    except InvalidPdf:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser error of a damaged file (see docstring)
        raise _damaged(exc) from exc
    return reader, encrypted


@dataclass
class PageText:
    page: int
    text: str  # usable text: whitespace-normalised, glyph pages decoded where possible
    chars: int  # non-whitespace characters of ``text``
    glyph: bool  # the text layer is glyph-ID encoded
    width_pt: float = 0.0
    height_pt: float = 0.0
    content_bytes: int = 0  # size of the decoded content stream (vector drawings: >30 kB, blank pages: <10 kB)
    images: int = 0  # XObjects on the page (scans are one big image)


@dataclass
class PdfInfo:
    page_count: int
    encrypted: bool
    title: str | None
    pages: list[PageText] = field(default_factory=list)


def glyph_ratio(text: str) -> float:
    """Share of the non-whitespace characters that belong to glyph-ID tokens (``/g27``, ``(cid:12)``)."""
    compact = _WS.sub("", text)
    if not compact:
        return 0.0
    glyph_chars = sum(len(m) for m in _GLYPH_TOKEN.findall(compact))
    return glyph_chars / len(compact)


def decode_glyph_text(text: str) -> str:
    """Try the ``chr(N + 29)`` decoding of pypdf ``/gNN`` tokens (VERIFIED on Microchip package pages).

    Returns the decoded text only when it looks like natural text (mostly letters, digits and
    spaces), else the input unchanged.
    """
    if "/g" not in text:
        return text
    decoded = _PYPDF_GLYPH.sub(lambda m: chr(int(m.group(1)) + 29) if 0 <= int(m.group(1)) + 29 < 0x250 else " ", text)
    sample = _WS.sub(" ", decoded).strip()
    if not sample:
        return text
    plain = sum(1 for ch in sample if ch.isascii() and (ch.isalnum() or ch in " .,:;()-/%[]"))
    return decoded if plain / len(sample) >= 0.75 else text


def _page_size(page) -> tuple[float, float]:
    try:
        box = page.mediabox
        w, h = float(box.width), float(box.height)
        if int(page.get("/Rotate", 0) or 0) % 180:
            w, h = h, w
        return round(abs(w), 1), round(abs(h), 1)
    except Exception:  # noqa: BLE001 - broken boxes: unknown size
        return 0.0, 0.0


def _content_stats(page) -> tuple[int, int]:
    """(decoded content-stream bytes, number of XObjects) – cheap signals for drawings and scans."""
    size = images = 0
    try:
        contents = page.get_contents()
        if contents is not None:
            size = len(contents.get_data())
    except Exception:  # noqa: BLE001 - undecodable streams count as empty
        size = 0
    try:
        resources = page.get("/Resources")
        if resources is not None:
            xobjects = resources.get_object().get("/XObject")
            if xobjects is not None:
                images = len(xobjects.get_object())
    except Exception:  # noqa: BLE001
        images = 0
    return size, images


def read_page_texts(
    source: Path | bytes,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> PdfInfo:
    """Text layer of every page (see :class:`PageText`). Raises :class:`InvalidPdf`."""
    reader, encrypted = _reader(source)
    title = None
    try:
        meta = reader.metadata
        if meta is not None and meta.title:
            title = clean_free_text(str(meta.title), max_len=200) or None
    except Exception:  # noqa: BLE001 - broken metadata is irrelevant
        title = None
    pages: list[PageText] = []
    total = len(reader.pages)
    for index in range(total):
        if progress is not None:
            progress(index, total)
        try:
            page = reader.pages[index]
        except Exception as exc:  # noqa: BLE001 - damaged page object
            raise _damaged(exc) from exc
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one broken content stream must not stop the import
            log.debug("Text von Seite %d nicht lesbar: %s", index + 1, exc)
            raw = ""
        glyph = glyph_ratio(raw) > 0.3
        text = decode_glyph_text(raw) if glyph else raw
        text = _WS.sub(" ", text.replace("\x00", " ")).strip()
        width, height = _page_size(page)
        content_bytes, images = _content_stats(page)
        pages.append(PageText(page=index + 1, text=text, chars=len(_WS.sub("", text)), glyph=glyph,
                              width_pt=width, height_pt=height, content_bytes=content_bytes, images=images))
    return PdfInfo(page_count=total, encrypted=encrypted, title=title, pages=pages)


def pdf_info(source: Path | bytes) -> PdfInfo:
    """Page count, encryption and title without reading the text layer (fast)."""
    reader, encrypted = _reader(source)
    title = None
    try:
        meta = reader.metadata
        if meta is not None and meta.title:
            title = clean_free_text(str(meta.title), max_len=200) or None
    except Exception:  # noqa: BLE001
        title = None
    return PdfInfo(page_count=len(reader.pages), encrypted=encrypted, title=title)


# --------------------------------------------------------------------------- subsets


def subset_pdf(source: Path | bytes, pages: Sequence[int]) -> bytes:
    """A new, unencrypted PDF with the given 1-based pages (in the given order)."""
    reader, _ = _reader(source)
    from pypdf import PdfWriter

    total = len(reader.pages)
    writer = PdfWriter()
    for number in pages:
        if not 1 <= number <= total:
            raise InvalidPdf(f"Seite {number} gibt es im Datenblatt nicht (1–{total}).")
        try:
            writer.add_page(reader.pages[number - 1])
        except Exception as exc:  # noqa: BLE001 - damaged page object
            raise _damaged(exc) from exc
    buf = io.BytesIO()
    try:
        writer.write(buf)
    except Exception as exc:  # noqa: BLE001 - pypdf write errors on damaged objects
        raise InvalidPdf(f"Die ausgewählten Seiten lassen sich nicht als PDF speichern ({type(exc).__name__}).") from exc
    return buf.getvalue()


# --------------------------------------------------------------------------- renders


def visual_tokens(size: tuple[int, int]) -> int:
    """Visual tokens of an image on the high-resolution tier: ceil(w/28) * ceil(h/28)."""
    w, h = size
    return math.ceil(w / 28) * math.ceil(h / 28)


def render_page(
    source: Path | bytes,
    page: int,
    *,
    dpi: float = 110,
    mode: Literal["color", "gray"] = "color",
    max_edge: int = UI_MAX_EDGE,
    max_visual_tokens: int | None = None,
) -> tuple[bytes, tuple[int, int]]:
    """Render one 1-based page to PNG; returns (png bytes, (width, height)).

    ``max_edge`` caps the longest side (scale reduced before rendering), ``max_visual_tokens``
    additionally shrinks the image to the vision budget (renders for Claude).
    """
    import pypdfium2 as pdfium
    from PIL import Image

    if dpi <= 0:
        raise ValueError("Die Auflösung muss größer als 0 sein.")
    with PDFIUM_LOCK:
        try:
            doc = pdfium.PdfDocument(source if isinstance(source, (bytes, bytearray)) else str(source))
        except Exception as exc:  # noqa: BLE001 - pdfium raises PdfiumError for damaged/encrypted files
            raise InvalidPdf(f"Das PDF lässt sich nicht darstellen ({type(exc).__name__}).") from exc
        try:
            total = len(doc)
            if not 1 <= page <= total:
                raise InvalidPdf(f"Seite {page} gibt es im Datenblatt nicht (1–{total}).")
            try:
                pdf_page = doc[page - 1]
            except Exception as exc:  # noqa: BLE001 - damaged page object
                raise InvalidPdf(f"Seite {page} lässt sich nicht darstellen ({type(exc).__name__}).") from exc
            try:
                width_pt, height_pt = pdf_page.get_size()
                scale = dpi / 72.0
                longest = max(width_pt, height_pt) * scale
                if longest > max_edge:
                    scale *= max_edge / longest
                bitmap = pdf_page.render(scale=scale, grayscale=(mode == "gray"))
                image = bitmap.to_pil()
            except Exception as exc:  # noqa: BLE001 - damaged content, zero-size page
                raise InvalidPdf(f"Seite {page} lässt sich nicht darstellen ({type(exc).__name__}).") from exc
            finally:
                pdf_page.close()
        finally:
            doc.close()
    if max_visual_tokens is not None:
        w, h = image.size
        factor = 1.0
        while visual_tokens((max(1, int(w * factor)), max(1, int(h * factor)))) > max_visual_tokens:
            factor *= 0.98
        if factor < 1.0:
            image = image.resize((max(1, int(w * factor)), max(1, int(h * factor))), Image.Resampling.LANCZOS)
    if mode == "gray":
        image = image.convert("L")
    elif image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=mode == "gray")
    return buf.getvalue(), image.size
