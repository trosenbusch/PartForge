"""Datasheet import: PDF text layer, glyph decoding, subsets, renders and page selection (offline).

Page-selection quality is measured against the ground truth of the corpus manifest (sections ordering, pinout,
package outline and land pattern): recall must stay at 100 %, precision above 85 %.
"""
from __future__ import annotations

import io
import json
import threading
from pathlib import Path

import pytest

from partforge.datasheet import pdf as pdfio
from partforge.datasheet.errors import InvalidPdf
from partforge.datasheet.extract import split_pages
from partforge.datasheet.models import PageInfo
from partforge.datasheet.pages import (
    MANUAL_PAGE_LIMIT,
    PageSelection,
    classify_text,
    needs_triage,
    page_infos,
    select_pages,
    to_real_pages,
    triage_digest,
)

CORPUS = Path(__file__).parent / "data" / "corpus"
PDFS = CORPUS / "pdfs"
SECTIONS = ("ordering", "pinout", "package_outline", "land_pattern")

pytestmark = pytest.mark.skipif(not (CORPUS / "manifest.json").is_file(), reason="Datenblatt-Korpus fehlt")


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus_texts(manifest) -> dict[str, pdfio.PdfInfo]:
    return {Path(e["file"]).name: pdfio.read_page_texts(CORPUS / e["file"]) for e in manifest["entries"]}


def _blank_pdf(pages: int = 2, *, password: str | None = None) -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if password:
        writer.encrypt(user_password=password, owner_password=password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- text layer


def test_page_counts_and_encryption_match_the_manifest(manifest, corpus_texts):
    for entry in manifest["entries"]:
        info = corpus_texts[Path(entry["file"]).name]
        assert info.page_count == entry["pages"], entry["file"]
        assert info.encrypted == entry["encrypted"], entry["file"]
        assert len(info.pages) == entry["pages"]


def test_pages_without_text_layer_are_detected(manifest, corpus_texts):
    for entry in manifest["entries"]:
        infos = page_infos(corpus_texts[Path(entry["file"]).name].pages)
        empty = [p.page for p in infos if p.quality == "empty"]
        for page in entry["pages_without_text_layer"]:
            assert page in empty, (entry["file"], page)
            assert "drawing" in infos[page - 1].categories


def test_glyph_coded_pages_are_flagged_and_decoded(corpus_texts):
    pages = corpus_texts["25AA02E48.pdf"].pages
    assert [p.page for p in pages if p.glyph] == [16, 17, 18]
    assert "Plastic Small Outline" in pages[15].text  # chr(N + 29) decoding of /gNN tokens
    assert "1.27" in pages[15].text
    infos = page_infos(pages)
    assert infos[15].quality == "glyph" and "glyph" in infos[15].categories


def test_glyph_helpers():
    assert pdfio.glyph_ratio("") == 0.0
    assert pdfio.glyph_ratio("/g27/g16/g47") == 1.0
    assert pdfio.glyph_ratio("(cid:3)(cid:4) abc") > 0.7
    assert pdfio.glyph_ratio("Pin Configuration") == 0.0
    assert pdfio.decode_glyph_text("/g54/g50/g44/g38") == "SOIC"
    garbage = "/g1/g2/g3/g4/g5"  # decodes to control characters: kept as is
    assert pdfio.decode_glyph_text(garbage) == garbage
    assert pdfio.decode_glyph_text("plain text") == "plain text"


def test_content_size_separates_drawings_from_blank_pages(corpus_texts):
    opa = corpus_texts["opa656.pdf"].pages
    assert all(opa[p - 1].content_bytes > 100_000 for p in (21, 22, 23, 24))
    ad = corpus_texts["AD5235.pdf"].pages
    assert ad[30].content_bytes < 10_000  # page 31 "NOTES"
    assert "drawing" not in page_infos(ad)[30].categories


def test_pdf_info_and_invalid_input(tmp_path):
    info = pdfio.pdf_info(_blank_pdf(3))
    assert info.page_count == 3 and not info.encrypted
    with pytest.raises(InvalidPdf, match="kein lesbares PDF"):
        pdfio.pdf_info(b"%PDF-1.4 garbage")
    with pytest.raises(InvalidPdf, match="Passwort"):
        pdfio.pdf_info(_blank_pdf(1, password="geheim"))
    owner_only = pdfio.pdf_info((PDFS / "25AA02E48.pdf").read_bytes())
    assert owner_only.encrypted and owner_only.page_count == 26


# --------------------------------------------------------------------------- subsets and renders


def test_subset_is_unencrypted_and_ordered():
    from pypdf import PdfReader

    data = pdfio.subset_pdf(PDFS / "25AA02E48.pdf", [16, 1, 19])
    reader = PdfReader(io.BytesIO(data))
    assert not reader.is_encrypted
    assert len(reader.pages) == 3
    assert "25AA02E48" in (reader.pages[1].extract_text() or "")
    with pytest.raises(InvalidPdf, match="Seite 99"):
        pdfio.subset_pdf(PDFS / "25AA02E48.pdf", [99])


def test_render_sizes_and_vision_limits():
    png, size = pdfio.render_page(PDFS / "opa656.pdf", 21, dpi=72)
    assert png.startswith(b"\x89PNG") and size == (612, 792)
    png, size = pdfio.render_page(PDFS / "opa656.pdf", 21, dpi=200, mode="gray", max_edge=pdfio.VISION_MAX_EDGE,
                                  max_visual_tokens=pdfio.VISION_MAX_TOKENS)
    assert max(size) <= pdfio.VISION_MAX_EDGE
    assert pdfio.visual_tokens(size) <= pdfio.VISION_MAX_TOKENS
    _png, capped = pdfio.render_page(PDFS / "opa656.pdf", 1, dpi=300, max_edge=1000)
    assert max(capped) <= 1000
    with pytest.raises(InvalidPdf, match="Seite 26"):
        pdfio.render_page(PDFS / "opa656.pdf", 26)
    with pytest.raises(ValueError):
        pdfio.render_page(PDFS / "opa656.pdf", 1, dpi=0)
    with pytest.raises(InvalidPdf):
        pdfio.render_page(b"not a pdf", 1)


def test_renders_are_thread_safe():
    errors: list[Exception] = []

    def work(page: int) -> None:
        try:
            png, _ = pdfio.render_page(PDFS / "LTC6244.pdf", page, dpi=40)
            assert png.startswith(b"\x89PNG")
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(p,)) for p in range(1, 13)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize(("text", "expected", "absent"), [
    ("PIN CONFIGURATION AND FUNCTIONS", {"pins"}, set()),
    ("The pinout of the device is shown below", set(), {"pins"}),
    ("PINOUT", {"pins"}, set()),
    ("ORDERING INFORMATION", {"ordering"}, set()),
    ("PART NUMBER AND PRODUCT DESCRIPTION", {"ordering"}, set()),
    ("Dimensions – Millimeters (Inches)", {"package"}, set()),
    ("RECOMMENDED SOLDER PAD PITCH AND DIMENSIONS", {"land_pattern"}, set()),
    ("TAPE AND REEL INFORMATION Package Drawing", {"reel", "package"}, set()),
    ("IMPORTANT NOTICE Texas Instruments", {"noise"}, set()),
    ("RELATED PARTS PART NUMBER DESCRIPTION", {"noise", "ordering"}, set()),
    ("PACKAGE OPTION ADDENDUM Orderable Device", {"orderable", "ordering"}, set()),
])
def test_classify_text(text, expected, absent):
    cats = set(classify_text(text, page=5, page_count=20, chars=len(text), glyph=False))
    assert expected <= cats
    assert not (absent & cats)


def test_classify_toc_and_drawing_flags():
    toc = "TABLE OF CONTENTS Features ........ 1 Pin Configurations ........ 6 Outline Dimensions ........ 24"
    assert "toc" in classify_text(toc, page=2, page_count=24, chars=200, glyph=False)
    many = " ".join(f"Section {i} .......... {i}" for i in range(6))
    assert "toc" in classify_text(many, page=2, page_count=24, chars=300, glyph=False)
    assert "drawing" in classify_text("", page=20, page_count=25, chars=0, glyph=False, content_bytes=200_000)
    assert "drawing" not in classify_text("", page=20, page_count=25, chars=0, glyph=False, content_bytes=900)
    assert "drawing" in classify_text("", page=20, page_count=25, chars=0, glyph=False, images=1)  # scan
    assert "drawing" not in classify_text("", page=1, page_count=25, chars=0, glyph=False, content_bytes=200_000)
    assert "drawing" in classify_text("x", page=16, page_count=26, chars=4000, glyph=True)


# --------------------------------------------------------------------------- selection metrics (corpus)


def test_page_selection_precision_and_recall(manifest, corpus_texts):
    tp = fp = fn = 0
    per_section = {s: [0, 0] for s in SECTIONS}
    for entry in manifest["entries"]:
        selection = select_pages(page_infos(corpus_texts[Path(entry["file"]).name].pages))
        relevant = {1}.union(*(set(entry["sections"].get(s, [])) for s in SECTIONS))
        chosen = set(selection.pages)
        assert len(chosen) <= 12
        assert 1 in chosen
        tp += len(chosen & relevant)
        fp += len(chosen - relevant)
        fn += len(relevant - chosen)
        for section in SECTIONS:
            pages = set(entry["sections"].get(section, []))
            per_section[section][0] += len(pages & chosen)
            per_section[section][1] += len(pages)
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    assert recall >= 0.99, (precision, recall)
    assert precision >= 0.85, (precision, recall)
    for section, (hit, total) in per_section.items():
        assert hit == total, section


def test_reference_selection_for_opa656(corpus_texts):
    selection = select_pages(page_infos(corpus_texts["opa656.pdf"].pages))
    assert selection.pages == [1, 2, 17, 18, 21, 22, 23, 24]
    assert selection.method == "heuristic"
    assert "drawing" in selection.reasons[21]
    identity, geometry = split_pages(selection)
    assert identity == [1, 2, 17, 18]
    assert set(geometry) >= {21, 22, 23, 24} and 1 not in geometry


def test_no_triage_needed_for_well_structured_datasheets(corpus_texts):
    for name in ("opa656.pdf", "LTC6244.pdf", "25AA02E48.pdf", "sn65lv1023a.pdf", "AD7983.pdf"):
        infos = page_infos(corpus_texts[name].pages)
        assert not needs_triage(infos, select_pages(infos)), name


def _infos(count: int, *, quality: str = "ok", categories: dict[int, list[str]] | None = None) -> list[PageInfo]:
    return [PageInfo(page=i, chars=0 if quality == "empty" else 2000, quality=quality,  # type: ignore[arg-type]
                     categories=(categories or {}).get(i, [])) for i in range(1, count + 1)]


def test_selection_modes():
    assert select_pages([]).method == "empty"
    small = select_pages(_infos(5))
    assert small.method == "all" and small.pages == [1, 2, 3, 4, 5]
    manual = select_pages(_infos(30), forced=[30, 3, 3, 99, 0], max_pages=12)
    assert manual.method == "manual" and manual.pages == [3, 30] and manual.dropped == [0, 99]
    chosen = select_pages(_infos(30), forced=range(1, 21), max_pages=12)  # the user's pages are not cut to 12
    assert chosen.pages == list(range(1, 21)) and chosen.dropped == []
    many = select_pages(_infos(60), forced=range(1, 46))
    assert many.pages == list(range(1, MANUAL_PAGE_LIMIT + 1)) and many.dropped == list(range(41, 46))
    scan = select_pages(_infos(40, quality="empty"), max_pages=10)
    assert scan.method == "scan"
    assert scan.pages == [1, 2, 3, 4, 35, 36, 37, 38, 39, 40]
    capped = select_pages(_infos(40, categories={i: ["pins", "package"] for i in range(2, 40)}), max_pages=5)
    assert len(capped.pages) == 5 and 1 in capped.pages


def test_triage_pages_are_merged():
    infos = _infos(30, categories={2: ["pins"]})
    base = select_pages(infos)
    assert base.pages == [1, 2]
    assert needs_triage(infos, base)
    merged = select_pages(infos, extra={25: ["package_outline"], 26: ["land_pattern"], 99: ["pinout"]})
    assert merged.method == "heuristic+triage"
    assert merged.pages == [1, 2, 25, 26]
    assert merged.reasons[25] == ["triage:package_outline"]
    identity, geometry = split_pages(merged)
    assert identity == [1, 2] and geometry == [25, 26]


def test_split_pages_fallbacks():
    only_first = PageSelection(pages=[1], reasons={1: ["first page"]})
    assert split_pages(only_first) == ([1], [1])
    drawings = PageSelection(pages=[1, 4, 20], reasons={1: ["first page"], 4: ["drawing"], 20: ["drawing"]})
    assert split_pages(drawings, page_count=24) == ([1, 4], [4, 20])  # early drawing: maybe a pinout
    assert split_pages(drawings) == ([1], [4, 20])
    complete = PageSelection(pages=[1, 2, 3], reasons={}, method="all")
    assert split_pages(complete) == ([1, 2, 3], [1, 2, 3])


def test_subset_page_mapping():
    selection = PageSelection(pages=[1, 2, 17, 21])
    assert to_real_pages([1, 3, 4, 4, 5, 0, -1, "2", "x"], selection.pages) == [1, 17, 21, 2]  # type: ignore[list-item]
    assert selection.subset_page(17) == 3
    assert selection.subset_page(5) is None


def test_triage_digest_flags_drawings(corpus_texts):
    digest = triage_digest(corpus_texts["opa656.pdf"].pages, chars_per_page=80)
    lines = digest.splitlines()
    assert len(lines) == 25
    assert lines[20].startswith("[page 21] chars=0 (NO TEXT LAYER")
    glyph = triage_digest(corpus_texts["25AA02E48.pdf"].pages)
    assert "GLYPH-ENCODED" in glyph.splitlines()[15]
