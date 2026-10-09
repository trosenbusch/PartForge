"""Page classification and selection: which datasheet pages Claude gets to see.

Sending only the relevant pages cut the tokens by ~77 % on the reference datasheet and removes
noise (characteristic curves, legal notices). The heuristic (keywords of the text layer plus
"no usable text layer" = vector drawing / scan) was measured against the ground truth of the test
corpus (``tests/data/corpus/manifest.json``, see ``tests/test_datasheet_pages.py``):

* page 1 is always sent (identity, features, often the pinout),
* pages with pin, ordering, package-outline or land-pattern keywords score,
* pages without a usable text layer after the first pages score as drawings (TI mechanical pages are
  pure vector graphics, Microchip package pages are glyph-ID encoded),
* tables of contents (dot leaders) and noise sections (typical characteristics, revision history,
  tape and reel, legal notices) are demoted,
* small datasheets (<= ``ALL_PAGES_LIMIT`` pages) are sent completely.

The optional LLM triage (:func:`triage_digest`, fast model) supplements the heuristic for scans and
when the keywords find too little. Claude reports page numbers of the *attached subset*; the
selection keeps the mapping to the real datasheet pages (:func:`to_real_pages`).
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from .models import PageInfo, PageQuality
from .pdf import PageText

__all__ = [
    "ALL_PAGES_LIMIT",
    "CATEGORY_PATTERNS",
    "DEFAULT_MAX_PAGES",
    "MANUAL_PAGE_LIMIT",
    "PageSelection",
    "classify_text",
    "needs_triage",
    "page_infos",
    "select_pages",
    "to_real_pages",
    "triage_digest",
]

DEFAULT_MAX_PAGES = 12
MANUAL_PAGE_LIMIT = 40  # pages the user selected explicitly (the cost limit still applies)
ALL_PAGES_LIMIT = 6  # datasheets up to this size are sent completely
DRAWING_MAX_CHARS = 350  # fewer usable characters: probably a drawing (only header/footer text)
DRAWING_MIN_CONTENT = 30_000  # bytes of vector content: TI/Microchip drawings 0.2-0.9 MB, blank "NOTES" pages <10 kB

CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    "pins": re.compile(
        r"pin\s*(?:configurations?|functions?|descriptions?|assignments?|names?\b|no\.|#)|pin\s+out\b|"
        r"\b(?-i:PIN-?OUTS?|Pin-?outs?)\b|terminal\s+(?:functions|configuration)|pin\s+function\s+table|"
        r"package/order\s+information|pin\s+configuration\s+and\s+function|connection\s+diagrams?\s+\(?top\s+view|"
        r"\bschematics\b",
        re.I,
    ),
    "ordering": re.compile(
        r"ordering\s+(?:information|guide|code|options?)|order(?:ing)?\s+(?:code|number|information)|orderable\s+device|"
        r"product\s+identification\s+system|package\s+option\s+addendum|how\s+to\s+order|"
        r"part\s+number(?:ing)?\s+(?:system|information|description|guide)|global\s+part\s+number|"
        r"part\s+number\s+and\s+product\s+description|device\s+selection\s+table|part\s+numbering",
        re.I,
    ),
    "package": re.compile(
        r"mechanical\s+(?:data|drawings?|information|dimensions)|package\s+(?:outlines?|dimensions|drawings?|information|"
        r"description)|outline\s+dimensions|case\s+outline|physical\s+dimensions|product\s+dimensions|"
        r"dimensions\s*(?:in|[–—-])\s*(?:millimet(?:er|re)s|inches|mm)|packaging\s+outline|\bBSC\b",
        re.I,
    ),
    "land_pattern": re.compile(
        r"land\s+pattern|recommended\s+(?:footprint|land|pad\s+layout|solder\s+pad|mounting\s+pad|"
        r"soldering\s+footprint)|example\s+board\s+layout|solder\s+pad\s+(?:layout|dimensions)|mounting\s+pad|"
        r"pcb\s+footprint|suggested\s+pad|soldering\s+footprint|land\s+dimensions|stencil\s+(?:design|opening)",
        re.I,
    ),
}
# Pages that are almost never useful (legal notice, curves, revision history): demoted strongly.
_NOISE = re.compile(
    r"important\s+notice|revision\s+history|typical\s+(?:performance\s+)?characteristics|"
    r"customer\s+support|sales\s+(?:and|&)\s+support|related\s+(?:parts|products)",
    re.I,
)
# Packing-material pages (tape and reel, carrier tape): their "package drawing" columns are no outlines.
_REEL = re.compile(r"tape\s+and\s+reel|reel\s+dimensions|all\s+dimensions\s+are\s+nominal|carrier\s+tape", re.I)
_TOC = re.compile(r"table\s+of\s+contents", re.I)
_DOT_LEADER = re.compile(r"(?:\.\s*){6,}\s*\d{1,3}\b")
_ORDERABLE = re.compile(r"orderable\s+device|package\s+option\s+addendum|product\s+identification", re.I)

# scores per category; the land pattern and outline pages are the hardest to find otherwise
_WEIGHTS = {"pins": 3.0, "ordering": 2.5, "package": 2.5, "land_pattern": 3.0, "drawing": 2.0}


def classify_text(text: str, *, page: int, page_count: int, chars: int, glyph: bool,
                  content_bytes: int = 0, images: int = 0) -> list[str]:
    """Keyword categories of one page (pins, ordering, package, land_pattern) plus the flags
    ``drawing`` (vector drawing/scan without usable text), ``glyph``, ``toc``, ``noise``, ``reel``, ``orderable``."""
    cats = [name for name, rx in CATEGORY_PATTERNS.items() if rx.search(text)]
    flags: list[str] = []
    leaders = len(_DOT_LEADER.findall(text))
    if leaders >= 4 or (_TOC.search(text) and leaders >= 2):
        flags.append("toc")
    if _NOISE.search(text):
        flags.append("noise")
    if _REEL.search(text):
        flags.append("reel")
    if _ORDERABLE.search(text):
        flags.append("orderable")  # TI package option addendum etc.: ordering data despite "tape and reel"
    if glyph:
        flags.append("glyph")
    sparse = chars < DRAWING_MAX_CHARS and (content_bytes >= DRAWING_MIN_CONTENT or (images > 0 and chars < 50))
    if (glyph or sparse) and page > min(2, page_count):
        flags.append("drawing")
    return cats + flags


def page_infos(texts: Sequence[PageText]) -> list[PageInfo]:
    """Page analysis (quality + categories) from the text layer."""
    count = len(texts)
    out: list[PageInfo] = []
    for t in texts:
        quality: PageQuality = "glyph" if t.glyph else ("empty" if t.chars < 50 else "ok")
        out.append(PageInfo(
            page=t.page, chars=t.chars, quality=quality, width_pt=t.width_pt, height_pt=t.height_pt,
            categories=classify_text(t.text, page=t.page, page_count=count, chars=t.chars, glyph=t.glyph,
                                     content_bytes=t.content_bytes, images=t.images),
        ))
    return out


@dataclass
class PageSelection:
    pages: list[int]  # sorted real page numbers
    reasons: dict[int, list[str]] = field(default_factory=dict)
    method: str = "heuristic"  # heuristic | all | manual | heuristic+triage | scan
    scores: dict[int, float] = field(default_factory=dict)
    dropped: list[int] = field(default_factory=list)  # user pages not taken (not in the PDF, above the limit)

    def subset_page(self, real_page: int) -> int | None:
        """1-based page number in the attached subset."""
        try:
            return self.pages.index(real_page) + 1
        except ValueError:
            return None


def _score(info: PageInfo, page_count: int) -> tuple[float, list[str]]:
    cats = set(info.categories)
    if "toc" in cats:
        return 0.0, ["toc"]  # tables of contents name every section (ADI p2/p3)
    reasons: list[str] = [c for c in ("pins", "ordering", "package", "land_pattern") if c in cats]
    if "reel" in cats and "package" in reasons and "orderable" not in cats:
        reasons.remove("package")  # "Package Drawing" column of tape-and-reel tables
    score = sum(_WEIGHTS[c] for c in reasons)
    if "drawing" in cats and info.page > min(2, page_count):
        drawing = _WEIGHTS["drawing"]
        if not reasons and info.page <= 0.4 * page_count and "glyph" not in cats:
            drawing *= 0.4  # figure-only pages early in the document: timing diagrams, block diagrams
        elif info.quality == "empty" and info.page > page_count / 2:
            drawing += 1.0  # vector-only pages at the back: mechanical drawings
        score += drawing
        reasons.append("drawing")
    if "noise" in cats:
        score *= 0.2
        reasons.append("noise")
    elif "reel" in cats and "orderable" not in cats and "ordering" not in reasons:
        score *= 0.35
        reasons.append("reel")
    if info.page == 2 and score > 0:
        score += 0.5  # pinout and ordering tables are often on page 2
    return score, reasons


def select_pages(
    infos: Sequence[PageInfo],
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    forced: Iterable[int] | None = None,
    extra: Mapping[int, list[str]] | None = None,
) -> PageSelection:
    """Choose the pages for the extraction.

    ``forced``: user-selected pages (used as they are, up to :data:`MANUAL_PAGE_LIMIT` – the user chose them, so
    ``max_pages`` does not cut them; pages that are not in the PDF or above the limit are listed in ``dropped``).
    ``extra``: pages proposed by the LLM triage (page -> categories); they are merged with the heuristic.
    """
    count = len(infos)
    max_pages = max(1, int(max_pages))
    if count == 0:
        return PageSelection(pages=[], method="empty")
    if forced:
        wanted = sorted({int(p) for p in forced})
        valid = [p for p in wanted if 1 <= p <= count]
        pages = valid[:MANUAL_PAGE_LIMIT]
        dropped = sorted(set(wanted) - set(pages))
        return PageSelection(pages=pages, reasons={p: ["manuell"] for p in pages}, method="manual", dropped=dropped)
    if count <= min(ALL_PAGES_LIMIT, max_pages):
        pages = list(range(1, count + 1))
        return PageSelection(pages=pages, reasons={p: ["alle Seiten"] for p in pages}, method="all")
    text_pages = [i for i in infos if i.quality == "ok"]
    if len(text_pages) < max(1, count // 5):  # (almost) no text layer: scanned datasheet
        head = min(4, max_pages)
        tail = max_pages - head
        pages = sorted(set(range(1, head + 1)) | set(range(max(head + 1, count - tail + 1), count + 1)))
        return PageSelection(pages=pages[:max_pages], reasons={p: ["Scan"] for p in pages}, method="scan")

    scores: dict[int, float] = {}
    reasons: dict[int, list[str]] = {}
    for info in infos:
        score, why = _score(info, count)
        if score > 0:
            scores[info.page] = score
            reasons[info.page] = why
    for page, cats in (extra or {}).items():
        if 1 <= page <= count:
            scores[page] = scores.get(page, 0.0) + 2.0 + 0.5 * len(cats)
            reasons.setdefault(page, []).extend(f"triage:{c}" for c in cats)
    scores[1] = max(scores.get(1, 0.0), 100.0)  # always: identity, features, often the pinout
    reasons.setdefault(1, []).insert(0, "first page")
    ranked = sorted(scores, key=lambda p: (-scores[p], p))
    chosen = [p for p in ranked if scores[p] >= 1.0][:max_pages]
    method = "heuristic+triage" if extra else "heuristic"
    return PageSelection(pages=sorted(chosen), reasons={p: reasons.get(p, []) for p in chosen}, method=method,
                         scores={p: round(scores[p], 2) for p in chosen})


def relevant_count(selection: PageSelection) -> int:
    """Pages chosen for content reasons (not only "first page")."""
    return sum(1 for p, why in selection.reasons.items() if p != 1 or len(why) > 1)


def needs_triage(infos: Sequence[PageInfo], selection: PageSelection) -> bool:
    """Ask the fast model as well? (few keyword hits, long datasheets)."""
    if selection.method in ("manual", "all", "scan", "empty"):
        return False
    content = [p for p in selection.pages if p != 1]
    has_package = any("package" in selection.reasons.get(p, []) or "drawing" in selection.reasons.get(p, [])
                      for p in content)
    return len(content) < 2 or not has_package or len(infos) > 60


def triage_digest(texts: Sequence[PageText], *, chars_per_page: int = 500) -> str:
    """Compact per-page digest for the LLM triage (first characters of each page's text layer)."""
    lines = []
    for t in texts:
        flags = []
        if t.glyph:
            flags.append("GLYPH-ENCODED TEXT, probably a package drawing")
        elif t.chars < 50:
            flags.append("NO TEXT LAYER, probably a drawing or scan")
        elif t.chars < DRAWING_MAX_CHARS:
            flags.append("LITTLE TEXT, maybe a drawing")
        head = f"[page {t.page}] chars={t.chars}" + (f" ({'; '.join(flags)})" if flags else "")
        lines.append(f"{head}: {t.text[:chars_per_page]}")
    return "\n".join(lines)


def to_real_pages(subset_pages: Iterable[int], selection_pages: Sequence[int]) -> list[int]:
    """Map 1-based page numbers of the attached subset back to real datasheet pages (invalid ones dropped)."""
    out: list[int] = []
    for p in subset_pages:
        try:
            index = int(p)
        except (TypeError, ValueError):
            continue
        if 1 <= index <= len(selection_pages):
            real = selection_pages[index - 1]
            if real not in out:
                out.append(real)
    return out
