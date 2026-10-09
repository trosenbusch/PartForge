"""Per-PDF structural analysis for the PartForge datasheet corpus.

Usage: python -I analyze.py <pdf_dir> <work_dir>
Writes <work_dir>/<stem>/p###.txt (pypdf text) and p###.plumber.txt (pdfplumber text),
plus <work_dir>/analysis.json with page counts, extractability and keyword page hits.
Treats all PDFs as untrusted data (text extraction only, nothing executed).
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber
import pypdf

SECTIONS = {
    "ordering": [
        r"ORDERING\s+INFORMATION", r"ORDER\s+INFORMATION", r"ORDERING\s+GUIDE",
        r"PRODUCT\s+IDENTIFICATION\s+SYSTEM", r"PACKAGE\s+OPTION\s+ADDENDUM",
        r"HOW\s+TO\s+ORDER", r"ORDERABLE\s+DEVICE", r"PART\s+NUMBER(ING)?\s+(SYSTEM|INFORMATION|DESCRIPTION)",
        r"GLOBAL\s+PART\s+NUMBER", r"ORDERING\s+CODE", r"ORDER\s+CODE", r"PART\s+MARKING",
        r"ORDER(ING)?\s+OPTIONS", r"LEAD\s+FREE\s+FINISH",
    ],
    "pinout": [
        r"PIN\s+CONFIGURATION", r"PIN\s+FUNCTION", r"PIN\s+DESCRIPTION", r"PIN\s+ASSIGNMENT",
        r"TERMINAL\s+FUNCTIONS", r"PINOUT", r"PIN\s+NAME", r"PACKAGE/ORDER\s+INFORMATION",
        r"PIN\s+FUNCTION\s+TABLE", r"PIN\s+NO\.?", r"Pin\s+Number",
    ],
    "package_outline": [
        r"OUTLINE\s+DIMENSIONS", r"PACKAGE\s+DESCRIPTION", r"MECHANICAL\s+DATA",
        r"PACKAGE\s+DRAWING", r"PACKAGE\s+OUTLINE", r"PACKAGE\s+DIMENSIONS", r"PACKAGING\s+DIAGRAMS?",
        r"PACKAGE\s+MATERIALS", r"DIMENSIONS\s+IN\s+(MILLIMETERS|INCHES|mm)", r"Dimensions\s+in",
        r"Product\s+Dimensions", r"DIMENSIONS",
    ],
    "land_pattern": [
        r"LAND\s+PATTERN", r"RECOMMENDED\s+LAND", r"SOLDER\s+PAD", r"FOOTPRINT", r"PCB\s+LAYOUT",
        r"RECOMMENDED\s+PAD", r"PAD\s+LAYOUT", r"SOLDERING\s+FOOTPRINT", r"SUGGESTED\s+PAD",
        r"RECOMMENDED\s+(PCB|SOLDER|MOUNTING)", r"Recommended\s+Layout", r"LAND\s+DIMENSIONS",
        r"Land\s+Pattern", r"PAD\s+DIMENSIONS", r"EXAMPLE\s+BOARD\s+LAYOUT", r"STENCIL",
    ],
    "abs_max": [r"ABSOLUTE\s+MAXIMUM\s+RATINGS", r"MAXIMUM\s+RATINGS", r"Absolute\s+Maximum"],
}


def classify(text: str) -> dict:
    hits = {}
    for sec, pats in SECTIONS.items():
        found = []
        for p in pats:
            for m in re.finditer(p, text, flags=re.IGNORECASE):
                found.append(m.group(0))
        if found:
            hits[sec] = sorted(set(f.upper() for f in found))
    return hits


def main() -> None:
    pdf_dir = Path(sys.argv[1])
    work = Path(sys.argv[2])
    work.mkdir(parents=True, exist_ok=True)
    result = {}
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        out = work / pdf.stem
        out.mkdir(exist_ok=True)
        info = {"file": pdf.name, "bytes": pdf.stat().st_size}
        reader = pypdf.PdfReader(str(pdf))
        info["encrypted"] = bool(reader.is_encrypted)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception as exc:  # noqa: BLE001
                info["decrypt_error"] = repr(exc)
        info["pages"] = len(reader.pages)
        meta = reader.metadata or {}
        info["metadata"] = {k: str(v)[:200] for k, v in dict(meta).items()}
        pages = []
        with pdfplumber.open(str(pdf)) as plumb:
            for i, page in enumerate(reader.pages, start=1):
                try:
                    t1 = page.extract_text() or ""
                except Exception as exc:  # noqa: BLE001
                    t1 = ""
                    info.setdefault("pypdf_errors", []).append(f"p{i}: {exc!r}")
                try:
                    t2 = plumb.pages[i - 1].extract_text() or ""
                    n_img = len(plumb.pages[i - 1].images)
                    w = float(plumb.pages[i - 1].width)
                    h = float(plumb.pages[i - 1].height)
                except Exception as exc:  # noqa: BLE001
                    t2, n_img, w, h = "", -1, 0.0, 0.0
                    info.setdefault("plumber_errors", []).append(f"p{i}: {exc!r}")
                (out / f"p{i:03d}.txt").write_text(t1, encoding="utf-8")
                (out / f"p{i:03d}.plumber.txt").write_text(t2, encoding="utf-8")
                pages.append({
                    "page": i,
                    "chars_pypdf": len(t1.strip()),
                    "chars_plumber": len(t2.strip()),
                    "images": n_img,
                    "size_pt": [round(w, 1), round(h, 1)],
                    "hits": classify(t2 if len(t2) >= len(t1) else t1),
                })
        info["page_detail"] = pages
        n_text = sum(1 for p in pages if max(p["chars_pypdf"], p["chars_plumber"]) >= 200)
        info["pages_with_text_ge_200_chars"] = n_text
        info["text_extractable"] = n_text >= max(1, int(0.8 * len(pages)))
        for sec in SECTIONS:
            info[f"pages_{sec}"] = [p["page"] for p in pages if sec in p["hits"]]
        result[pdf.name] = info
        print(f"{pdf.name}: pages={info['pages']} text_pages={n_text} encrypted={info['encrypted']}")
        for sec in SECTIONS:
            print(f"   {sec:16s} {info['pages_' + sec]}")
    (work / "analysis.json").write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
