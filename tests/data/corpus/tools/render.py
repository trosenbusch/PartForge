"""Render PDF pages (optionally a cropped region) to PNG with pypdfium2.

Usage: python -I render.py <pdf> <pages e.g. 1,3-5> <out_dir> [dpi=110] [crop=x0,y0,x1,y1 as 0..1 fractions of the page]
Output files: <out_dir>/<stem>_p<N>[_crop].png
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium


def parse_pages(spec: str) -> list[int]:
    pages: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            pages.extend(range(int(a), int(b) + 1))
        else:
            pages.append(int(part))
    return pages


def main() -> None:
    pdf_path = Path(sys.argv[1])
    pages = parse_pages(sys.argv[2])
    out = Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    dpi = float(sys.argv[4]) if len(sys.argv) > 4 else 110.0
    crop = [float(v) for v in sys.argv[5].split(",")] if len(sys.argv) > 5 else None
    pdf = pdfium.PdfDocument(str(pdf_path))
    for n in pages:
        page = pdf[n - 1]
        img = page.render(scale=dpi / 72.0).to_pil()
        suffix = ""
        if crop:
            w, h = img.size
            img = img.crop((int(crop[0] * w), int(crop[1] * h), int(crop[2] * w), int(crop[3] * h)))
            suffix = "_crop"
        target = out / f"{pdf_path.stem}_p{n}{suffix}.png"
        img.save(target)
        print(target, img.size)


if __name__ == "__main__":
    main()
