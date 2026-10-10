"""Exercise STEP previews in Chromium against a production build and an isolated server.

Build the frontend first, then run from the repository root::

    .venv/bin/python tests/ui/step_regressions.py --executable-path /usr/bin/chromium

The test owns its temporary home, libraries, port and server process. STEP files are real
AP214 solids, read by the shipped OpenCascade worker/WASM; no geometry or API is mocked.
It does not need Altium, a library writer, an AI key, or access to the user's library.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
MODEL_NAME = "Imported STEP sample"
PART_NUMBER = "STEP-PREVIEW-001"
TOKEN = "isolated-step-preview-test"


def seed_library(root: Path, *, alternate: bool = False) -> dict[str, Path | str]:
    """Store imported geometry with no generated bodies, and an unchanged generator case."""
    from partforge.db import close_database, open_database, parts, registry
    from partforge.db.models import FootprintRecord
    from partforge.footprints import FootprintRequest, generate, step_text
    from partforge.geometry.model import Body3D, FootprintSpec, Pad, Point, StepModel
    from partforge.workspace import Workspace, set_current

    ws = Workspace.create(root, name="STEP browser B" if alternate else "STEP browser A")
    open_database(ws)
    set_current(ws)
    try:
        bodies = [
            Body3D(name="Magenta housing", outline=[Point(x=x, y=y) for x, y in
                   [(-2.5, -1.5), (2.5, -1.5), (2.5, 1.5), (-2.5, 1.5)]],
                   z_bottom=0.35, z_top=2.3, color="#F04CC1"),
            Body3D(name="Cyan cap", outline=[Point(x=x, y=y) for x, y in
                   [(-1.2, -0.7), (1.2, -0.7), (1.2, 0.7), (-1.2, 0.7)]],
                   z_bottom=2.3, z_top=3.0, color="#42DDD6"),
        ]
        if alternate:
            bodies = [bodies[0].model_copy(update={"color": "#FFB326", "z_top": 4.0})]
        text = step_text(FootprintSpec(name="Vendor assembly", bodies=bodies))
        # A third-party model has no PartForge auto-generated-file digest.
        text = re.sub(r"pf:[a-f0-9]{16}", "vendor-assembly", text)
        valid = ws.models_dir / "vendor sample.step"
        valid.write_text(text, encoding="ascii")
        broken = ws.models_dir / "invalid geometry.step"
        broken.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n#1=THIS_IS_NOT_A_SOLID();\nENDSEC;\nEND-ISO-10303-21;\n", encoding="ascii")
        missing = ws.models_dir / "restored model.step"
        pads = [Pad(designator="1", x=-3, y=0, width=1, height=1.6),
                Pad(designator="2", x=3, y=0, width=1, height=1.6)]
        for name, path in [(MODEL_NAME, valid), ("Missing STEP sample", missing), ("Broken STEP sample", broken)]:
            spec = FootprintSpec(name=name, pads=pads, height=4.5, step=StepModel(
                file=ws.rel(path), rotation=(15, -10, 25), offset=(1.5, -0.75, 0.4),
            ))
            registry.upsert_footprint(FootprintRecord(name=name, source="imported", status="ok",
                library=r"Footprints\Vendor.PcbLib", spec=spec, step_file=ws.rel(path)))
        generated = generate(FootprintRequest(family="chip", params={"preset": "R-0603"}))
        registry.upsert_footprint(FootprintRecord(name=generated.name, source="generated", status="pending",
            library=r"Footprints\Generated.PcbLib", spec=generated))
        parts.create_part("Resistors", {"Part Number": PART_NUMBER, "Manufacturer": "Preview fixture",
            "Manufacturer Part Number": PART_NUMBER, "Resistance": "1k", "Tolerance": "1", "Power": "0.1",
            "Footprint Ref": MODEL_NAME}, allow_incomplete=True)
        return {"root": root, "valid": valid, "missing": missing, "broken": broken, "generated": generated.name}
    finally:
        close_database()
        set_current(None)


def main() -> int:
    from PIL import Image
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--executable-path", default=None)
    parser.add_argument("--channel", default=None)
    parser.add_argument("--shots", type=Path, default=None)
    args = parser.parse_args()
    assert (ROOT / "partforge/web/index.html").is_file(), "Build the production frontend first."
    if args.shots:
        args.shots.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="partforge-step-browser-") as temporary:
        temporary = Path(temporary)
        os.environ.update(PARTFORGE_HOME=str(temporary / "home"), PARTFORGE_NO_ALTIUM="1",
                          PARTFORGE_NO_AI_KEY="1", PARTFORGE_TOKEN=TOKEN)
        os.environ.pop("PARTFORGE_AI_REPLAY_DIR", None)
        first = seed_library(temporary / "library-a")
        second = seed_library(temporary / "library-b", alternate=True)
        log_path = args.shots / "server.log" if args.shots else temporary / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen([sys.executable, "-m", "partforge", "--server-only", "--port", "0"],
                cwd=ROOT, env=os.environ.copy(), stdout=log, stderr=subprocess.STDOUT)
            try:
                instance = temporary / "home" / "instance.json"
                deadline = time.monotonic() + 30
                while not instance.exists():
                    assert server.poll() is None, log_path.read_text(encoding="utf-8")
                    assert time.monotonic() < deadline, "Isolated server did not start."
                    time.sleep(0.1)
                base = json.loads(instance.read_text(encoding="utf-8"))["url"].rstrip("/")
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def api(method: str, path: str, body=None):
                    request = urllib.request.Request(base + path, method=method,
                        data=None if body is None else json.dumps(body).encode("utf-8"),
                        headers={"X-PartForge-Token": TOKEN, "Content-Type": "application/json"})
                    with opener.open(request, timeout=30) as response:
                        return json.load(response)

                while True:
                    try:
                        api("GET", "/api/health")
                        break
                    except urllib.error.URLError:
                        assert server.poll() is None, log_path.read_text(encoding="utf-8")
                        assert time.monotonic() < deadline, "Isolated server did not become ready."
                        time.sleep(0.1)

                # Both appear in the real workspace switcher; browser navigation later tests cache isolation.
                api("POST", "/api/workspace/open", {"path": str(second["root"])})
                api("POST", "/api/workspace/open", {"path": str(first["root"])})
                model_path = "/api/libraries/footprints/" + urllib.parse.quote(MODEL_NAME, safe="")
                manifest = api("GET", model_path + "/step-models")
                assert len(manifest["models"]) == 1, manifest
                assert manifest["models"][0]["rotation"] == [15, -10, 25], manifest
                assert manifest["models"][0]["offset"] == [1.5, -0.75, 0.4], manifest
                assert not api("GET", model_path + "?svg=false")["spec"]["bodies"]

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(headless=True, channel=args.channel,
                        executable_path=args.executable_path,
                        args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
                    context = browser.new_context(viewport={"width": 1440, "height": 1000},
                        extra_http_headers={"X-PartForge-Token": TOKEN}, accept_downloads=True)
                    # Headless Chrome cannot display the native save picker; exercise the browser download fallback.
                    context.add_init_script("Object.defineProperty(window, 'showSaveFilePicker', { value: undefined });")
                    external: list[str] = []

                    def local_only(route):
                        if route.request.url.startswith(base + "/"):
                            route.continue_()
                        else:
                            external.append(route.request.url)
                            route.abort()

                    context.route("http**://**", local_only)
                    page = context.new_page()
                    errors: list[str] = []
                    assets: set[str] = set()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    context.on("response", lambda response: assets.add(response.url) if response.ok else None)
                    expect.set_options(timeout=30_000)

                    def footprint(name: str, *, spa: bool = False):
                        url = base + "/footprints?ansicht=bibliothek&fp=" + urllib.parse.quote(name, safe="")
                        if spa:
                            page.evaluate("url => { history.pushState(null, '', url); dispatchEvent(new PopStateEvent('popstate')); }", url)
                        else:
                            page.goto(url)
                        dialog = page.get_by_role("dialog")
                        expect(dialog).to_be_visible()
                        dialog.get_by_role("tab", name="3D", exact=True).click()
                        return dialog

                    def rendered(scope, *, models: int = 1, pink: bool = True):
                        expect(scope.locator('[data-step-status="ready"]')).to_be_visible()
                        scene = scope.locator(f'[data-step-models="{models}"]')
                        expect(scene).to_be_visible()
                        expect(scene.locator(".opacity-100")).to_be_visible()
                        canvas = scene.locator("canvas")
                        assert canvas.evaluate("c => c.width > 100 && c.height > 100")
                        # Screenshot reads the final composed frame; readPixels may race a cleared drawing buffer.
                        pixels = Image.open(io.BytesIO(canvas.screenshot())).convert("RGB")
                        channels = pixels.tobytes()
                        count = sum(r > 100 and b > 70 and r > g * 1.5 and b > g * 1.35
                                    for r, g, b in zip(channels[0::3], channels[1::3], channels[2::3], strict=True))
                        if pink:
                            assert count > 75, f"STEP housing is not visible in the WebGL frame ({count} magenta pixels)."
                        else:
                            assert count == 0, f"Previous library's magenta housing leaked into the scene ({count} pixels)."
                        return scene

                    dialog = footprint(MODEL_NAME)
                    scene = rendered(dialog)
                    assert int(scene.get_attribute("data-step-meshes") or 0) >= 2, "Both coloured STEP solids must render."
                    if args.shots:
                        page.screenshot(path=str(args.shots / "imported-step-en.png"))

                    page.goto(base + "/bauteile/Resistors?pn=" + PART_NUMBER)
                    page.get_by_role("tab", name="3D", exact=True).click()
                    rendered(page)
                    if args.shots:
                        page.screenshot(path=str(args.shots / "part-step-en.png"))

                    # Reloading a broken file is a real worker parse failure, not an artificial API error.
                    dialog = footprint("Broken STEP sample")
                    expect(dialog.locator('[data-step-status="error"]')).to_be_visible()
                    expect(dialog.get_by_role("alert")).to_contain_text("The STEP file contains no displayable 3D geometry or is damaged.")
                    expect(dialog.get_by_role("button", name=re.compile("Retry|Try again", re.I))).to_be_visible()
                    assert dialog.locator('[data-step-models="1"]').count() == 0
                    dialog.locator("summary").filter(has_text="STEP files").click()
                    with page.expect_download() as download:
                        dialog.get_by_role("button", name="invalid geometry.step", exact=True).click()
                    assert Path(download.value.path()).read_bytes() == Path(first["broken"]).read_bytes()
                    Path(first["broken"]).write_bytes(Path(first["valid"]).read_bytes())
                    dialog.get_by_role("button", name=re.compile("Retry|Try again", re.I)).click()
                    rendered(dialog)

                    # Missing files show a localized explanation and can recover after a file is restored.
                    settings = api("GET", "/api/settings")["settings"]
                    api("PUT", "/api/settings", {**settings, "language": "de"})
                    dialog = footprint("Missing STEP sample")
                    expect(page.locator("html")).to_have_attribute("lang", "de")
                    expect(dialog.locator('[data-step-status="error"]')).to_be_visible()
                    expect(dialog.get_by_role("alert")).to_contain_text("Die Datei wurde nicht gefunden.")
                    expect(dialog.get_by_role("button", name=re.compile("Erneut|Wiederholen", re.I))).to_be_visible()
                    assert dialog.locator('[data-step-models="1"]').count() == 0
                    Path(first["missing"]).write_bytes(Path(first["valid"]).read_bytes())
                    dialog.get_by_role("button", name=re.compile("Erneut|Wiederholen", re.I)).click()
                    rendered(dialog)
                    if args.shots:
                        page.screenshot(path=str(args.shots / "restored-step-de.png"))

                    dialog = footprint(str(first["generated"]))
                    rendered(dialog, models=0, pink=False)
                    assert dialog.locator('[data-step-meshes="0"]').count() == 1

                    # Switch through the app without reloading: the same footprint name has different geometry.
                    page.keyboard.press("Escape")
                    page.get_by_role("button", name=re.compile("STEP browser A")).click()
                    page.get_by_role("menuitem", name=re.compile("STEP browser B")).click()
                    expect(page.get_by_role("button", name=re.compile("STEP browser B"))).to_be_visible()
                    page.locator('a[href="/footprints"]').first.click()
                    # History navigation keeps React and its caches alive; the model URL must be workspace-specific.
                    dialog = footprint(MODEL_NAME, spa=True)
                    rendered(dialog, pink=False)
                    other = api("GET", model_path + "/step-models")
                    assert other["models"][0]["url"] != manifest["models"][0]["url"]

                    assert any(".wasm" in url for url in assets), f"No locally served OpenCascade WASM requested: {assets}"
                    assert any("worker" in url.lower() for url in assets), "No worker bundle was loaded."
                    assert not external, f"Preview attempted external network requests: {external}"
                    assert not errors, "Browser errors: " + " | ".join(errors)
                    context.close()
                    browser.close()
                print("PASS real STEP/WASM/WebGL, vendor colours/placement, footprint and part previews, "
                      "download, malformed/missing-file retry, EN/DE, generated bodies, workspace isolation, offline assets")
                return 0
            finally:
                server.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    server.wait(timeout=10)
                if server.poll() is None:
                    server.kill()
                    server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
