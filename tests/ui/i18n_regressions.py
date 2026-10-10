"""Check language selection against an isolated PartForge server and a production frontend build.

Start the server with a fresh PARTFORGE_HOME, PARTFORGE_NO_ALTIUM=1, PARTFORGE_NO_AI_KEY=1,
PARTFORGE_TOKEN and PARTFORGE_WEB_DIR pointing to the build, then run::

    python tests/ui/i18n_regressions.py --base http://127.0.0.1:8878 --token i18n-test

Uses Playwright Chromium by default; --channel chrome selects installed Google Chrome.
The test creates a temporary library without examples/writer jobs, restores settings and the previously
open library, and removes its own temporary files. No Altium or AI service is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import urllib.request


def main() -> int:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8878")
    parser.add_argument("--token", default="i18n-test")
    parser.add_argument("--channel", default=None, help="Optional installed browser channel, e.g. chrome")
    parser.add_argument("--executable-path", default=None, help="Optional Chromium executable, e.g. /usr/bin/chromium")
    parser.add_argument("--shots", type=Path, default=None)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(method: str, path: str, body=None):
        request = urllib.request.Request(
            base + path,
            data=None if body is None else json.dumps(body).encode("utf-8"),
            method=method,
            headers={"X-PartForge-Token": args.token, "Content-Type": "application/json"},
        )
        with opener.open(request, timeout=30) as response:
            return json.load(response)

    original = api("GET", "/api/settings")["settings"]
    assert original["language"] == "en", "Use a fresh isolated PARTFORGE_HOME: the default must be English."
    previous_workspace = api("GET", "/api/workspace")
    temporary = Path(tempfile.mkdtemp(prefix="partforge-i18n-"))
    user_name = "Eigene Bibliothek – Prüfung Ω"
    try:
        api("POST", "/api/workspace/create", {
            "path": str(temporary / "library"), "name": user_name,
            "with_examples": False, "write_libraries": False,
        })
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, channel=args.channel, executable_path=args.executable_path)
            # Browser/OS locale deliberately differs from the new application default.
            context = browser.new_context(
                viewport={"width": 1440, "height": 1000}, locale="de-DE",
                extra_http_headers={"X-PartForge-Token": args.token},
            )
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            expect.set_options(timeout=15_000)

            def settings(language: str) -> None:
                page.goto(base + "/einstellungen")
                expect(page.locator("html")).to_have_attribute("lang", language)
                expect(page.get_by_role("heading", name="General" if language == "en" else "Allgemein", exact=True)).to_be_visible()

            def choose_language(current: str, target: str) -> None:
                page.get_by_role("combobox", name="Language" if current == "en" else "Sprache", exact=True).click()
                page.get_by_role("option", name="Deutsch" if target == "de" else "English", exact=True).click()

            def assert_routes(language: str) -> None:
                # Click real app navigation: the shell remains mounted during all route changes.
                routes = [
                    ("/serien", "Series wizard", "Serien-Assistent"),
                    ("/symbole", "Symbol generator", "Symbol-Generator"),
                    ("/bibliotheksimport", "Library import", "Bibliotheksimport"),
                    ("/einstellungen", "General", "Allgemein"),
                ]
                for path, english, german in routes:
                    page.locator(f'a[href="{path}"]').first.click()
                    expect(page.get_by_role("heading", name=english if language == "en" else german, exact=True)).to_be_visible()
                    expect(page.locator("html")).to_have_attribute("lang", language)
                author = page.get_by_role("textbox", name="Author" if language == "en" else "Autor", exact=True)
                expect(author).to_have_value(original["author"])
                assert api("GET", "/api/workspace")["name"] == user_name

            settings("en")
            expect(page.get_by_role("combobox", name="Language", exact=True)).to_contain_text("English")
            assert_routes("en")

            # A draft must not change the saved language; discarding must be reversible.
            choose_language("en", "de")
            expect(page.locator("html")).to_have_attribute("lang", "en")
            assert api("GET", "/api/settings")["settings"]["language"] == "en"
            page.get_by_role("button", name="Discard", exact=True).click()
            expect(page.get_by_role("combobox", name="Language", exact=True)).to_contain_text("English")

            choose_language("en", "de")
            with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith("/api/settings")) as saved:
                page.get_by_role("button", name="Save", exact=True).click()
            assert saved.value.ok, saved.value.text()
            assert saved.value.json()["settings"]["language"] == "de"
            expect(page.locator("html")).to_have_attribute("lang", "de")
            expect(page.get_by_role("heading", name="Allgemein", exact=True)).to_be_visible()
            expect(page.locator("[data-sonner-toast]").filter(has_text="Einstellungen gespeichert").last).to_be_visible()
            assert_routes("de")
            page.reload()
            expect(page.locator("html")).to_have_attribute("lang", "de")
            expect(page.get_by_role("combobox", name="Sprache", exact=True)).to_contain_text("Deutsch")
            if args.shots:
                args.shots.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(args.shots / "settings-german.png"))

            # A new browser context has no cached preference: the server's persisted setting must win.
            fresh = browser.new_context(extra_http_headers={"X-PartForge-Token": args.token}, locale="en-US")
            other = fresh.new_page()
            other.goto(base + "/einstellungen")
            expect(other.locator("html")).to_have_attribute("lang", "de")
            expect(other.get_by_role("combobox", name="Sprache", exact=True)).to_contain_text("Deutsch")
            fresh.close()

            choose_language("de", "en")
            with page.expect_response(lambda response: response.request.method == "PUT" and response.url.endswith("/api/settings")):
                page.get_by_role("button", name="Speichern", exact=True).click()
            expect(page.locator("html")).to_have_attribute("lang", "en")
            expect(page.locator("[data-sonner-toast]").filter(has_text="Settings saved").last).to_be_visible()
            assert_routes("en")
            page.reload()
            expect(page.locator("html")).to_have_attribute("lang", "en")
            expect(page.get_by_role("combobox", name="Language", exact=True)).to_contain_text("English")
            assert api("GET", "/api/settings")["settings"]["language"] == "en"
            if args.shots:
                page.screenshot(path=str(args.shots / "settings-english.png"))
            assert not errors, "Browser errors: " + " | ".join(errors)
            context.close()
            browser.close()
        print("PASS English default, draft/discard, saved switching, route labels, localized feedback, reload, new browser context, unchanged user data")
        return 0
    finally:
        api("POST", "/api/workspace/close")
        if previous_workspace:
            api("POST", "/api/workspace/open", {"path": previous_workspace["root"]})
        api("PUT", "/api/settings", original)
        shutil.rmtree(temporary, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
