"""Render the PartForge logo (frontend/public/favicon.svg) to partforge/assets/app.ico.

Uses headless Chrome (Playwright) to rasterise the SVG and Pillow to pack the ICO,
so no Qt or Cairo is needed.
"""
from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "frontend" / "public" / "favicon.svg"
OUT_DIR = ROOT / "partforge" / "assets"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def render_png(svg_markup: str, size: int = 256) -> bytes:
    html = (
        "<!doctype html><html><body style='margin:0;background:transparent'>"
        f"<div style='width:{size}px;height:{size}px'>{svg_markup}</div>"
        "<style>svg{width:100%;height:100%;display:block}</style></body></html>"
    )
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "msedge"):
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:  # noqa: BLE001, S112 - try the next installed browser
                continue
        if browser is None:
            raise SystemExit("Chrome oder Edge wird zum Rendern des Symbols benötigt.")
        page = browser.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        page.set_content(html)
        png = page.locator("div").screenshot(omit_background=True)
        browser.close()
    return png


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = render_png(SVG.read_text(encoding="utf-8"), 256)
    (OUT_DIR / "app.png").write_bytes(png)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    image.save(OUT_DIR / "app.ico", sizes=[(s, s) for s in SIZES])
    print(OUT_DIR / "app.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
