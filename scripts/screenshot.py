"""Take screenshots of PartForge pages with headless Chrome or Edge (Playwright).

    python scripts/screenshot.py --url http://127.0.0.1:8765 --token dev --out docs/screenshots \
        --pages /,/bauteile,/serien --themes dark,light

The token is injected as `partforge-token` meta value by the backend; for the dev server
(`python -m partforge --dev`) it is "dev". Pages are hash or path routes of the SPA, optionally
with a query string (`/altium?bereich=dateien` -> `altium_bereich-dateien-dark.png`).
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def _file_name(route: str) -> str:
    """Screenshot file stem for a route: path parts joined by '_', query 'a=b' as 'a-b' (Windows-safe)."""
    path, _, query = route.replace("#", "").partition("?")
    name = path.strip("/").replace("/", "_") or "start"
    if query:
        name += "_" + query.replace("=", "-").replace("&", "_")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "start"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--out", default="docs/screenshots")
    parser.add_argument("--pages", default="/")
    parser.add_argument("--themes", default="dark")
    parser.add_argument("--width", type=int, default=1480)
    parser.add_argument("--height", type=int, default=940)
    parser.add_argument("--wait", type=float, default=1.2, help="Sekunden nach dem Laden warten (Animationen)")
    parser.add_argument("--full-page", action="store_true")
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = None
        for channel in ("chrome", "msedge"):
            try:
                browser = p.chromium.launch(channel=channel, headless=True)
                break
            except Exception:  # noqa: BLE001, S112 - try the next installed browser
                continue
        if browser is None:
            raise SystemExit("Weder Chrome noch Edge gefunden (Playwright-Kanal 'chrome'/'msedge').")
        for theme in [t.strip() for t in args.themes.split(",") if t.strip()]:
            context = browser.new_context(viewport={"width": args.width, "height": args.height}, device_scale_factor=1)
            context.add_init_script(f"try {{ localStorage.setItem('pf-theme', '{theme}') }} catch (e) {{}}")
            page = context.new_page()
            errors: list[str] = []
            page.on("console", lambda msg, errors=errors: errors.append(msg.text) if msg.type == "error" else None)
            page.on("pageerror", lambda exc, errors=errors: errors.append(str(exc)))
            for route in [r.strip() for r in args.pages.split(",") if r.strip()]:
                page.goto(args.url.rstrip("/") + route, wait_until="networkidle")
                time.sleep(args.wait)
                name = _file_name(route)
                target = out / f"{name}-{theme}.png"
                page.screenshot(path=str(target), full_page=args.full_page)
                print(f"{target}  ({len(errors)} Konsolenfehler)")
                for e in errors:
                    print("   console:", e[:300])
                errors.clear()
            context.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
