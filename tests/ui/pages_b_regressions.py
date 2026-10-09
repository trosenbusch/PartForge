"""Playwright-Regressionsprüfungen der Seiten Serien, Import, Altium, Übersicht, Willkommen und UI-Kit (Review-Runde
„fix:fe-pages-b“).

Läuft gegen einen **isolierten** PartForge-Server (eigenes PARTFORGE_HOME, PARTFORGE_NO_ALTIUM=1, Token über
PARTFORGE_TOKEN, KI im Wiedergabemodus PARTFORGE_AI_REPLAY_DIR=tests/data/ai_fixtures) mit dem zu prüfenden
Frontend-Build (PARTFORGE_WEB_DIR). Legt seine Test-Bibliotheken unter ``--workspace`` an. Jede Prüfung meldet
PASS/FAIL/SKIP; Exit-Code 1, wenn eine fehlschlägt.

    # Server (eigenes Fenster); --variant simuliert einen Rechner ohne Writer bzw. ohne SQLite-ODBC-Treiber
    $env:PARTFORGE_HOME='…\\tests\\_tmp\\home-x'; $env:PARTFORGE_NO_ALTIUM='1'; $env:PARTFORGE_TOKEN='t'
    $env:PARTFORGE_AI_REPLAY_DIR='…\\tests\\data\\ai_fixtures'; $env:PARTFORGE_WEB_DIR='…\\tests\\_tmp\\web-x'
    python tests/ui/pages_b_regressions.py serve --port 8875 [--variant normal|nowriter|noodbc]

    python tests/ui/pages_b_regressions.py --base http://127.0.0.1:8875 --token t --workspace …\\tests\\_tmp\\ws-x
    python tests/ui/pages_b_regressions.py … --only int04_locked,f9_template_names

Prüfungen (Review-Befund in Klammern) – ``normal``: Vorlagenkarten mit Hersteller (F9), Wiederherstellen aus „Letzte
Änderungen“ + Metazeilen (F5, K6), Gesundheitskarte bei fehlenden Bibliotheksdateien (F2 d, F10), Prüfbericht nur nach
relevanten Jobs (perf-health-dashboard), Bestellnummern nie gekürzt + formatierte Parameter (F8, F10), abgeschnittene
Texte bei 1120 px (K6), Pinbelegung mit Überstrich + strukturiertes Problemziel (K3), Prüfumfang „Alle …“ und
Aktualisierung ohne DbLib (F6, F11), Kosten mit zwei Nachkommastellen (F10), Serie mit gesperrter PcbLib (INT-04/F1),
Bibliothekswechsel während einer Serie (F1), Jobs anderer Bibliotheken nicht im Seitenfortschritt (K2); ``nowriter``: gangbarer Weg ohne Writer (F2), Serie mit ausstehenden
Einträgen (F1 ux); ``noodbc``: fehlender ODBC-Treiber (F4).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8875"
TOKEN = "fepb-token"
WS = ROOT / "tests" / "_tmp" / "ws-fix-fe-pages-b"
LTC6244 = ROOT / "tests" / "data" / "corpus" / "pdfs" / "LTC6244.pdf"
SHOTS: Path | None = None


# --------------------------------------------------------------------------- Server (simulierte Rechnerzustände)


def serve(port: int, variant: str) -> int:
    """Den API-Server in diesem Prozess starten – `nowriter`: kein Bibliotheks-Writer gefunden, `noodbc`:
    pyodbc.drivers() ohne „SQLite3 ODBC Driver“. Nichts wird installiert oder entfernt."""
    assert os.environ.get("PARTFORGE_HOME"), "PARTFORGE_HOME muss gesetzt sein (isolierte Einstellungen)"
    sys.path.insert(0, str(ROOT))
    if variant == "noodbc":
        import pyodbc

        drivers = pyodbc.drivers
        pyodbc.drivers = lambda: [d for d in drivers() if "sqlite" not in d.lower()]
    if variant == "nowriter":
        from partforge import config

        config.detect_rust_writer = lambda: None
    from partforge.__main__ import main as partforge_main

    return partforge_main(["--server-only", "--port", str(port)])


# --------------------------------------------------------------------------- API-Helfer


def api(method: str, path: str, body=None, timeout=180, *, files: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {"X-PartForge-Token": TOKEN}
    if files is not None:  # multipart (Datenblatt hochladen)
        boundary = "pfboundary7d1"
        parts = []
        for name, (filename, content, ctype) in files.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                         f"Content-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        for name, value in (body or {}).items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw and "json" in resp.headers.get("content-type", "") else raw
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        raise RuntimeError(f"{method} {path} → {exc.code}: {exc.read().decode('utf-8', 'replace')}") from None


def wait_job(job_id: str, timeout=180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = api("GET", f"/api/jobs/{job_id}")
        if job and job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.3)
    raise TimeoutError(job_id)


def library(name: str, *, examples=True, write=False, fresh=False) -> dict:
    """Bibliothek ``WS/<name>`` öffnen bzw. (neu) anlegen; `write` = mit dem Job „Bibliotheken schreiben“."""
    root = WS / name
    if fresh and root.exists():
        api("POST", "/api/workspace/close")
        shutil.rmtree(root)
    if (root / "partforge.json").exists():
        return api("POST", "/api/workspace/open", {"path": str(root)})
    info = api("POST", "/api/workspace/create", {"path": str(root), "name": name, "with_examples": examples,
                                                 "write_libraries": write})
    if info.get("job"):
        wait_job(info["job"]["id"])
    return info


def analyzed_ltc6244() -> str:
    """LTC6244.pdf in der offenen Bibliothek, analysiert (Wiedergabemodus) – die Datenblatt-ID."""
    ds_id = hashlib.sha256(LTC6244.read_bytes()).hexdigest()[:16]
    known = api("GET", f"/api/datasheets/{ds_id}")
    if known and known.get("has_extraction"):
        return ds_id
    out = api("POST", "/api/datasheets", {"extract": "true"},
              files={"file": (LTC6244.name, LTC6244.read_bytes(), "application/pdf")})
    if out.get("job"):
        wait_job(out["job"]["id"])
    return ds_id


def writer_ready() -> bool:
    return any(b["available"] for b in api("GET", "/api/altium/status")["backends"])


WIDE_MONO_JS = ("document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style');"
                " s.textContent = '.mono { letter-spacing: 0.06em !important }'; document.head.appendChild(s) })")


@contextmanager
def browser(width=1440, height=900, theme="dark"):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": width, "height": height}, locale="de-DE", reduced_motion="reduce")
        ctx.add_cookies([{"name": "pf-theme", "value": theme, "url": BASE}])
        page = ctx.new_page()
        try:
            yield page
        finally:
            try:
                page.unroute_all(behavior="ignoreErrors")
            except Exception:  # noqa: BLE001 - Seite schon zu
                pass
            ctx.close()
            b.close()


def goto(page, path: str, wait: str = "main#main") -> None:
    page.goto(BASE + path)
    page.wait_for_selector(wait, timeout=30_000)
    page.wait_for_timeout(600)


def shot(page, name: str) -> None:
    if SHOTS:
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def card(page, title: str):
    return page.locator("[class*=rounded-card]", has=page.get_by_role("heading", name=title)).first


def seed_series(page, template: str, settings: dict) -> None:
    """Gemerkte Auswahl des Serien-Assistenten vorbelegen (localStorage `pf-serien`, einmal je Kontext)."""
    state = {"state": {"category": "Resistors", "templateId": template, "lastTemplate": {"Resistors": template},
                       "recent": [template], "mode": "skip", "settings": {template: {
                           "valueMode": "range", "addE24": False, "valuesText": "", "tolerance": None, "tcr": None,
                           "voltages": [], "packaging": None, "includeJumper": False, "density": None,
                           "footprintHeight": "class", **settings}}}, "version": 1}
    page.context.add_init_script(
        f"if (!sessionStorage.getItem('seeded')) {{ localStorage.setItem('pf-serien', {json.dumps(json.dumps(state))});"
        " sessionStorage.setItem('seeded', '1') }")


def commit_series(page, template: str) -> None:
    goto(page, f"/serien?vorlage={template}")
    page.get_by_role("button", name="Weiter: Vorschau").click(timeout=90_000)
    page.get_by_role("button", name="Weiter: Erzeugen").click(timeout=120_000)
    page.get_by_role("button", name="Serie erzeugen").click(timeout=60_000)


class Fail(AssertionError):
    pass


class Skip(Exception):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise Fail(message)


@contextmanager
def locked(path: Path, seconds: float = 120):
    """Datei exklusiv sperren (CreateFileW ohne Freigabe – wie eine in einem anderen Programm geöffnete Bibliothek)."""
    script = ("import ctypes,sys,time\nfrom ctypes import wintypes as w\nk=ctypes.WinDLL('kernel32',use_last_error=True)\n"
              "k.CreateFileW.restype=w.HANDLE\nk.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]\n"
              "h=k.CreateFileW(sys.argv[1],0x80000000,0,None,3,0,None)\nprint('ok' if h!=w.HANDLE(-1).value else 'fail',flush=True)\n"
              "time.sleep(float(sys.argv[2]))")
    proc = subprocess.Popen([sys.executable, "-c", script, str(path), str(seconds)], stdout=subprocess.PIPE, text=True)
    try:
        check(proc.stdout.readline().strip() == "ok", f"{path.name} ließ sich nicht sperren")
        yield proc
    finally:
        proc.kill()
        proc.wait(10)


CLIPPED_JS = """(root) => [...(root ?? document).querySelectorAll('*')]
    .filter((el) => el.children.length === 0 && el.textContent.trim() && getComputedStyle(el).textOverflow === 'ellipsis'
        && el.scrollWidth > el.clientWidth + 1 && !el.closest('[title]'))
    .map((el) => el.textContent.trim())"""


# --------------------------------------------------------------------------- Prüfungen: normal


def f9_template_names(page) -> str:
    """Vorlagenkarten (role=radio) heißen „Hersteller Serie“, nicht nur „RC_L“."""
    library("LibA", write=True)
    goto(page, "/serien?kategorie=Resistors")
    page.wait_for_selector('[role="radio"][aria-checked]', timeout=30_000)
    page.wait_for_timeout(800)
    names = page.evaluate("""() => [...[...document.querySelectorAll('[role=radiogroup]')].pop().querySelectorAll('[role=radio]')]
        .map((el) => (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean)
            .map((id) => document.getElementById(id)?.textContent?.trim() ?? '').join(' '))""")
    check(len(names) > 3, "keine Vorlagenkarten")
    bare = [n for n in names if len(n.split()) < 2]
    check(not bare, f"Namen ohne Hersteller: {bare}")
    return f"{len(names)} Karten, z. B. „{names[0]}“"


def f5_restore(page) -> str:
    """Gelöschtes Bauteil aus „Letzte Änderungen“ wiederherstellen; Metazeilen bei 1120 px nicht abgeschnitten (K6)."""
    library("LibA", write=True)
    pn = api("GET", "/api/parts/Resistors?limit=1")["rows"][0]["Part Number"]
    api("POST", "/api/parts/Resistors/delete", {"part_numbers": [pn]})
    page.set_viewport_size({"width": 1120, "height": 720})
    goto(page, "/")
    page.wait_for_selector("text=Letzte Änderungen", timeout=30_000)
    page.wait_for_timeout(1500)
    page.evaluate("document.getElementById('main').scrollTo(0, 99999)")
    entry = page.locator("li", has_text=pn).first
    button = entry.get_by_role("button", name="Wiederherstellen")
    check(button.count() == 1, "kein „Wiederherstellen“ am gelöschten Eintrag")
    cut = card(page, "Letzte Änderungen").evaluate(CLIPPED_JS)
    check(not cut, f"abgeschnitten: {cut}")
    shot(page, "f5-recent-1120")
    button.click()
    page.wait_for_timeout(2500)
    check(api("GET", f"/api/parts/Resistors/{pn}") is not None, "Bauteil nicht wiederhergestellt")
    check(page.locator("li", has_text="wiederhergestellt").count() > 0, "kein Eintrag „wiederhergestellt“")
    return f"{pn} wiederhergestellt"


def f2d_health_missing_files(page) -> str:
    """Ohne geschriebene Bibliotheksdateien: kein „100 %“/„Keine Fehler“, Probleme-Kachel zählt die Dateien."""
    library("LibC", write=False)
    goto(page, "/")
    page.wait_for_selector("text=Bibliotheksgesundheit", timeout=30_000)
    page.wait_for_timeout(4000)
    text = card(page, "Bibliotheksgesundheit").inner_text()
    shot(page, "f2d-health-missing-files")
    check("Keine Fehler oder Warnungen" not in text and "Keine Befunde" not in text, "„Keine Fehler“ trotz fehlender Dateien")
    check("Bibliotheksdateien fehlen" in text, "fehlende Bibliotheksdateien nicht genannt")
    check("100\n%" not in text, "100 % trotz fehlender Dateien")
    shares = page.evaluate("""() => [...document.querySelectorAll('.sr-only')].map((e) => e.textContent).filter((t) => / Bauteile, /.test(t))""")
    check(not [s for s in shares if s.endswith(" 0 %")], "Kategorieanteil „0 %“")
    return "Gesundheit nennt die fehlenden Dateien"


def perf_health(page) -> str:
    """Prüfbericht lädt nicht nach einem Export/Seitenwechsel neu, wohl aber nach „Synchronisieren“."""
    library("LibD", write=False, fresh=True)
    calls: list[str] = []
    page.on("request", lambda r: calls.append(r.url) if ("/api/health-check" in r.url or "/api/libraries/health" in r.url) else None)
    goto(page, "/")
    page.wait_for_selector("text=Bibliotheksgesundheit", timeout=30_000)
    page.wait_for_timeout(4000)
    first = len(calls)
    check(first == 2, f"{first} Prüfungen beim Öffnen")
    job = api("POST", "/api/export/Capacitors/job", {"format": "xlsx"})["job"]
    wait_job(job["id"])
    page.wait_for_timeout(3500)
    page.get_by_role("link", name="Bauteile").first.click()
    page.wait_for_timeout(1500)
    page.get_by_role("link", name="Übersicht").first.click()
    page.wait_for_selector("text=Bibliotheksgesundheit", timeout=30_000)
    page.wait_for_timeout(2500)
    check(len(calls) == first, f"{len(calls) - first} Prüfungen nach Export/Seitenwechsel")
    if not writer_ready():
        return "Export und Seitenwechsel ohne Prüfung (Synchronisieren übersprungen: kein Writer)"
    page.get_by_role("button", name="Bibliotheksdateien synchronisieren").first.click()
    end = time.time() + 90
    while time.time() < end:
        jobs = [j for j in api("GET", "/api/jobs?brief=true") if j["kind"] == "libraries.sync"]
        if jobs and all(j["status"] in ("done", "failed", "cancelled") for j in jobs):
            break
        time.sleep(0.5)
    page.wait_for_timeout(5000)
    check(len(calls) - first >= 2, "keine neue Prüfung nach dem Synchronisieren")
    check("fehlen" not in card(page, "Bibliotheksgesundheit").inner_text(), "Karte nach dem Synchronisieren nicht aktuell")
    return "nur nach Synchronisieren neu geprüft"


def f8_f10_import_review(page) -> str:
    """Prüfansicht 1120 px: Bestellnummern nie gekürzt (auch mit breiterer Schrift), Parameter formatiert."""
    library("LibA", write=True)
    ds = analyzed_ltc6244()
    # Monospace 6 % breiter – wie eine andere Schrift/Skalierung (im Befund fehlten der Bestellnummer 9 px)
    page.context.add_init_script(WIDE_MONO_JS)
    found = []
    for preview in range(260, 540, 24):
        page.set_viewport_size({"width": 1120, "height": 720})
        goto(page, f"/import?ds={ds}", wait="#sec-varianten")
        page.evaluate(f"localStorage.setItem('pf-split:import.vorschau', '{preview}')")
        page.reload()
        page.wait_for_selector("#sec-varianten", timeout=60_000)
        page.wait_for_timeout(400)
        cut = page.evaluate("""() => [...document.querySelectorAll('#sec-varianten tbody td span.mono')]
            .filter((el) => el.scrollWidth > el.clientWidth + 1).map((el) => el.textContent)""")
        if cut:
            found.append((preview, cut[:3]))
    check(not found, f"Bestellnummern gekürzt: {found[:3]}")
    page.evaluate("document.querySelector('#sec-parameter')?.scrollIntoView({block: 'start'})")
    values = page.evaluate("""() => [...document.querySelectorAll('#sec-parameter input')]
        .filter((el) => /^param-(GBW|Supply-Voltage|Input-Offset)$/.test(el.id)).map((el) => el.value)""")
    raw = [v for v in values if "." in v or re.search(r"\d[A-Za-zµ°]", v)]
    check(values and not raw, f"Parameter roh: {raw or values}")
    shot(page, "f10-parameters")
    return f"Parameter {values}"


def k6_truncation(page) -> str:
    """1120 px: KI-Karte, Serien-Kategoriekarten (gleich hohe Kennzahlen), UI-Kit ohne stumm gekürzte Texte."""
    library("LibA", write=True)
    page.set_viewport_size({"width": 1120, "height": 720})
    goto(page, "/import", wait="#ai-card-title")
    check(not page.locator("[aria-labelledby=ai-card-title]").first.evaluate(CLIPPED_JS), "KI-Karte gekürzt")
    goto(page, "/serien?schritt=kategorie")
    page.wait_for_selector("text=Welche Bauteile sollen entstehen?", timeout=30_000)
    heights = page.evaluate("""() => [...document.querySelectorAll('[role=radiogroup] > button')].map((b) => {
        const s = b.querySelector('span.mt-auto'); return s ? Math.round(s.getBoundingClientRect().height) : null })""")
    check(len(set(h for h in heights if h)) == 1, f"Kennzahlen ungleich hoch: {heights}")
    goto(page, "/ui-kit")
    page.wait_for_timeout(1200)
    cut = [c for c in page.evaluate(CLIPPED_JS.replace("(root ?? document)", "document"), None) if c not in ("Kategorie", "Vorschau")]
    check(not cut, f"UI-Kit gekürzt: {cut[:6]}")
    return "nichts gekürzt (Stepper-Beschriftungen: components/ui/Stepper)"


def k3_pinout(page) -> str:
    """Pin-Unterschiede mit echtem Überstrich (strukturiertes `taken_changes`), Hervorhebung aus `blocker_targets`."""
    library("LibA", write=True)
    ds = analyzed_ltc6244()
    blocker = "DFN-8 3×3 (DD): Belegung prüfen – Pin 9 (Exposed Pad) hat im Symbol keinen Anschluss"

    def patch(route) -> None:
        resp = route.fetch()
        data = resp.json()
        sym = data["symbols"][0]
        sym["taken_name"] = sym.get("name")
        sym["taken_changes"] = [
            {"pin": "1", "old_name": "C\\S\\", "new_name": "OUT A", "old_type": "input", "new_type": "output"},
            {"pin": "5", "old_name": "R\\E\\S\\E\\T\\", "new_name": "+IN B"},
        ]
        sym["usage"] = 3
        sym["name"] = f"{sym.get('name')}_1"
        data["blockers"] = [blocker]
        data["blocker_targets"] = [{"blocker": blocker, "package": data["footprints"][0]["package"], "pins": ["9"], "pads": []}]
        route.fulfill(response=resp, body=json.dumps(data), headers={**resp.headers, "content-type": "application/json"})

    page.route("**/api/datasheets/*/proposal**", patch)
    goto(page, f"/import?ds={ds}", wait="#sec-pruefen")
    page.wait_for_timeout(1200)
    sec = page.locator("#sec-pruefen")
    text = sec.inner_text()
    shot(page, "k3-pinout")
    check("\\" not in text, "rohe Überstrich-Syntax sichtbar")
    check(sec.evaluate("(s) => s.querySelectorAll('ul[aria-label^=\"Unterschiede\"] span.border-t').length") >= 2, "kein Überstrich")
    check("Typ Eingang → Ausgang" in text, "Typwechsel fehlt")
    check(sec.get_by_role("button", name="Zu den Pins").count() == 1, "kein „Zu den Pins“ trotz strukturiertem Ziel")
    return "Überstriche und Ziel aus blocker_targets"


def f6_f11_altium(page) -> str:
    """„Alle 19 Bauteile“ prüft alle (all: true); eine Aktualisierung ohne installierte DbLib zählt nicht als „aktualisiert“."""
    library("LibC", write=False)
    bodies: list[dict] = []

    def status(route) -> None:
        resp = route.fetch()
        data = resp.json()
        data.update(altium_running=True, altium_exe=data.get("altium_exe") or r"C:\X2.EXE", version=data.get("version") or "26.10")
        if data.get("dblib"):
            data["dblib"]["installed_in_altium"] = True
        data["refresh"].update(last_refresh=time.time() - 120, last_error=None, running=False, pending=False,
                               last_result={"file_name": "PartForge.DbLib", "matched": [], "closed": []})
        route.fulfill(response=resp, body=json.dumps(data), headers={**resp.headers, "content-type": "application/json"})

    def verify(route) -> None:
        bodies.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "Test: Altium simuliert."}))

    page.route("**/api/altium/status**", status)
    page.route("**/api/altium/verify", verify)
    goto(page, "/altium", wait="#altium-headline")
    page.wait_for_timeout(1200)
    hero = page.locator("section[aria-labelledby=altium-headline]").first
    check("aktualisiert vor" not in hero.inner_text(), "„aktualisiert vor …“ nach einer wirkungslosen Aktualisierung")
    hero.get_by_role("button", name="In Altium prüfen").first.click()
    page.get_by_role("menuitem", name="Alle 19 Bauteile").first.click()
    page.wait_for_timeout(1000)
    check(bodies and bodies[-1].get("all") is True, f"Prüfauftrag {bodies}")
    goto(page, "/")
    page.wait_for_selector("text=Altium und DbLib", timeout=30_000)
    page.wait_for_timeout(1200)
    check("vor 2 Min" not in card(page, "Altium und DbLib").inner_text(), "Übersicht zählt die wirkungslose Aktualisierung")
    return "all: true · keine Zeit für eine wirkungslose Aktualisierung"


def f10_search_costs(page) -> str:
    """Datenblattsuche (Wiedergabe OPA656): Kosten überall mit zwei Nachkommastellen."""
    library("LibA", write=True)
    page.set_viewport_size({"width": 1120, "height": 720})
    goto(page, "/import", wait="#ai-card-title")
    page.get_by_role("searchbox").first.fill("OPA656")
    page.get_by_role("button", name="Suchen", exact=True).click()
    page.wait_for_selector("[aria-label^='Suchergebnisse']:not([aria-busy])", timeout=90_000)
    page.wait_for_timeout(800)
    amounts = re.findall(r"(?:<[ \u00a0])?\d+,\d+[ \u00a0]\$", page.locator("main").inner_text())
    odd = sorted({a for a in amounts if not re.fullmatch(r"(?:<[ \u00a0])?\d+,\d{2}[ \u00a0]\$", a)})
    check(amounts and not odd, f"Beträge {sorted(set(amounts))}")
    return ", ".join(sorted(set(amounts)))


def int04_locked(page) -> str:
    """Serie mit gesperrter PF_CHIP.PcbLib: Warnung/Fehler mit dem Footprint außerhalb des Protokolls, Wiederholen nach
    dem Entsperren legt die Bauteile an."""
    if not writer_ready():
        raise Skip("kein Bibliotheks-Writer")
    library("LibE", write=True, fresh=True)
    seed_series(page, "vishay-crcw-e3", {"sizes": ["2512"], "series": "E24", "rangeMin": 10, "rangeMax": 100})
    with locked(WS / "LibE" / "Footprints" / "PF_CHIP.PcbLib") as lock:
        commit_series(page, "vishay-crcw-e3")
        page.wait_for_selector("section[aria-label='Ergebnis']", timeout=120_000)
        page.wait_for_timeout(1500)
        text = page.locator("section[aria-label='Ergebnis']").inner_text().split("Protokoll")[0]
        shot(page, "int04-locked")
        check("RESC6332X70N" in text, "Footprint nicht außerhalb des Protokolls genannt")
        check("nicht in die Bibliotheksdateien geschrieben" in text, "kein Hinweis „nicht geschrieben“")
        check("Serie angelegt" not in text, "Erfolg gemeldet")
        lock.kill()
        lock.wait(10)
        page.get_by_role("button", name="Serie erneut erzeugen").click()
        page.wait_for_function("() => [...document.querySelectorAll('section[aria-label=Ergebnis] h2')].some((h) => /Serie angelegt/.test(h.textContent))",
                               timeout=120_000)
    return "Fehler sichtbar, Wiederholen legt die Serie an"


def f1_switch(page) -> str:
    """Bibliothekswechsel während einer Serie: Rückfrage und Meldung „abgebrochen“."""
    library("LibB", write=False)
    library("LibF", examples=False, fresh=True)
    seed_series(page, "yageo-rc-l", {"sizes": ["0201", "0402", "0603", "0805", "1206", "1210", "1218", "2010"],
                                     "series": "auto", "addE24": True, "rangeMin": None, "rangeMax": None})
    commit_series(page, "yageo-rc-l")
    page.wait_for_selector("text=Serie wird erzeugt", timeout=30_000)
    page.wait_for_timeout(500)
    page.locator("aside").get_by_role("button", name=re.compile(r"Lib ?F")).first.click()
    page.get_by_role("menuitem", name=re.compile(r"Lib ?B")).first.click()
    confirm = page.get_by_role("button", name="Trotzdem wechseln")
    if confirm.is_visible(timeout=2000):
        confirm.click()
    page.wait_for_timeout(2500)
    seen = " ".join(page.locator("[data-sonner-toast]").all_inner_texts())
    check("abgebrochen" in seen.lower(), f"keine Abbruchmeldung (Toasts: {seen[:200]!r})")
    return "Abbruch gemeldet"


def _fake_jobs(page, jobs: list[dict]) -> None:
    """Jobliste aus der Prüfung statt vom Backend (Live-Strom aus → die Seiten pollen)."""
    page.route("**/api/jobs/events*", lambda route: route.abort())
    page.route("**/api/jobs?*", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(jobs)))
    page.route("**/api/jobs/k2*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(next(j for j in jobs if route.request.url.split("?")[0].endswith(j["id"])))))


def _job(id_: str, kind: str, library_root: str, **extra) -> dict:
    now = time.time()
    return {"id": id_, "kind": kind, "title": extra.pop("title", f"Test {kind}"), "status": "running", "progress": 0.4,
            "message": extra.pop("message", "Altium prüft Bauteile …"), "log": [], "result": None, "error": None,
            "detail": {}, "created": now - 5, "started": now - 5, "finished": None, "version": 2, "library": library_root, **extra}


def k2_foreign_jobs(page) -> str:
    """Jobs einer anderen Bibliothek erscheinen nicht im Fortschritt der Seiten (Altium-Prüfung, Serien-Sperre)."""
    info = library("LibA", write=True)
    other = str(WS / "Andere Bibliothek")
    _fake_jobs(page, [_job("k2verify", "altium.verify", other, title="Bibliothek in Altium prüfen (Andere)"),
                      _job("k2series", "series", other, title="Serie Fremd")])
    goto(page, "/altium?bereich=altium", wait="#altium-headline")
    page.wait_for_timeout(1500)
    panel = page.get_by_role("tabpanel")  # nur der Bereich „In Altium geprüft“ – das Job-Dock listet alle Jobs
    check(panel.get_by_text("Altium prüft Bauteile …").count() == 0, "Fortschritt einer fremden Prüfung auf der Altium-Seite")
    goto(page, "/serien?schritt=kategorie")
    page.wait_for_timeout(800)
    check(page.get_by_text("„Fremd“ wird gerade erzeugt").count() == 0, "fremde Serie sperrt den Assistenten")
    # Gegenprobe: derselbe Job in der offenen Bibliothek erscheint
    page.unroute_all(behavior="ignoreErrors")
    _fake_jobs(page, [_job("k2verify", "altium.verify", info["root"], title="Bibliothek in Altium prüfen")])
    goto(page, "/altium?bereich=altium", wait="#altium-headline")
    page.wait_for_timeout(1500)
    check(page.get_by_role("tabpanel").get_by_text("Altium prüft Bauteile …").count() > 0, "Fortschritt der eigenen Prüfung fehlt")
    return "fremde Jobs ausgeblendet, eigene gezeigt"


# --------------------------------------------------------------------------- Prüfungen: ohne Writer / ohne ODBC-Treiber


def f2_nowriter(page) -> str:
    """Ohne Bibliotheks-Writer: „Bibliotheks-Writer einrichten“ statt „Synchronisieren“, Gesundheit nie „Keine Fehler“."""
    if writer_ready():
        raise Skip("Server hat einen Writer (serve --variant nowriter)")
    library("LibG", write=True, fresh=True)
    goto(page, "/")
    page.wait_for_selector("text=Bibliotheksgesundheit", timeout=30_000)
    page.wait_for_timeout(4000)
    health = card(page, "Bibliotheksgesundheit").inner_text()
    check("Keine Fehler oder Warnungen" not in health, "Gesundheit „Keine Fehler“")
    check("Bibliotheks-Writer einrichten" in health, "Gesundheit ohne „Bibliotheks-Writer einrichten“")
    goto(page, "/altium", wait="#altium-headline")
    page.wait_for_timeout(1200)
    hero = page.locator("section[aria-labelledby=altium-headline]").first
    check("„Synchronisieren“ schreibt sie neu" not in hero.inner_text(), "empfiehlt „Synchronisieren“")
    primary = hero.get_by_role("button", name="Bibliotheks-Writer einrichten")
    check(primary.count() > 0, "Primäraktion nicht „Bibliotheks-Writer einrichten“")
    shot(page, "f2-altium-nowriter")
    page.get_by_role("tab", name="Bibliotheksdateien").click()
    page.get_by_role("button", name="Synchronisieren").first.click()
    page.wait_for_timeout(1200)
    check("Bibliotheks-Writer" in " ".join(page.locator("[data-sonner-toast]").all_inner_texts()), "Synchronisieren ohne Writer-Hinweis")
    page.get_by_role("tab", name="Prüfbericht").click()
    primary.first.click()
    page.wait_for_timeout(1200)
    check("/einstellungen" in page.url, "führt nicht zu den Einstellungen")
    return "Weg zum Writer statt Synchronisieren"


def f1ux_series_nowriter(page) -> str:
    """Serie ohne Writer: „… Bibliotheksdateien ausstehend“, ausstehende Einträge außerhalb des Protokolls."""
    if writer_ready():
        raise Skip("Server hat einen Writer (serve --variant nowriter)")
    library("LibH", write=True, fresh=True)
    seed_series(page, "vishay-crcw-e3", {"sizes": ["2512"], "series": "E24", "rangeMin": 10, "rangeMax": 100})
    commit_series(page, "vishay-crcw-e3")
    page.wait_for_selector("section[aria-label='Ergebnis']", timeout=120_000)
    page.wait_for_timeout(1500)
    text = page.locator("section[aria-label='Ergebnis']").inner_text().split("Protokoll")[0]
    shot(page, "f1ux-series-nowriter")
    check("ausstehend" in text and "RESC6332X70N" in text, "ausstehende Einträge nicht genannt")
    check("Bibliotheks-Writer einrichten" in text, "kein „Bibliotheks-Writer einrichten“")
    return "ausstehend gemeldet"


def f4_odbc(page) -> str:
    """Ohne SQLite-ODBC-Treiber: Übersicht/Altium nennen ihn (Download, „ODBC testen“), Dialog ohne falsches Häkchen."""
    library("LibA", write=True)
    odbc = api("GET", "/api/altium/status").get("odbc") or {}
    if odbc.get("installed") is not False:
        raise Skip("Treiber vorhanden (serve --variant noodbc)")
    goto(page, "/")
    page.wait_for_selector("text=Altium und DbLib", timeout=30_000)
    page.wait_for_timeout(2000)
    text = card(page, "Altium und DbLib").inner_text()
    check("Alles bereit" not in text and "ODBC" in text, "Übersicht ohne ODBC-Hinweis")
    goto(page, "/altium", wait="#altium-headline")
    page.wait_for_timeout(1200)
    hero = page.locator("section[aria-labelledby=altium-headline]").first
    check("ODBC-Treiber" in hero.inner_text() and "Bereit für Altium" not in hero.inner_text(), "Altium-Seite ohne ODBC-Hinweis")
    check(hero.get_by_role("link", name="herunterladen").count() > 0, "kein Download-Verweis")
    hero.get_by_role("button", name="ODBC-Verbindung testen").first.click()
    page.wait_for_selector("text=Altium kann die Datenbank", timeout=60_000)
    page.wait_for_timeout(600)
    dialog = page.get_by_role("dialog")
    row = dialog.evaluate("""(d) => { const dt = [...d.querySelectorAll('dt')].find((e) => e.textContent.trim() === 'Gelesen')
        return dt ? Boolean(dt.nextElementSibling.querySelector('.text-success-text')) : null }""")
    check(row is False, "Häkchen bei „Gelesen“ ohne Verbindung")
    check(dialog.inner_text().count("ist nicht installiert") == 1, "Fehler doppelt")
    shot(page, "f4-odbc-dialog")
    return "Treiber gemeldet"


CHECKS: dict[str, Callable] = {f.__name__: f for f in (
    f9_template_names, f5_restore, f2d_health_missing_files, perf_health, f8_f10_import_review, k6_truncation, k3_pinout,
    f6_f11_altium, f10_search_costs, int04_locked, f1_switch, k2_foreign_jobs, f2_nowriter, f1ux_series_nowriter, f4_odbc,
)}


def main(argv: list[str] | None = None) -> int:
    global BASE, TOKEN, WS, SHOTS
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        sp = argparse.ArgumentParser(prog="pages_b_regressions.py serve")
        sp.add_argument("--port", type=int, default=8875)
        sp.add_argument("--variant", choices=["normal", "nowriter", "noodbc"], default="normal")
        a = sp.parse_args(argv[1:])
        return serve(a.port, a.variant)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--token", default=TOKEN)
    parser.add_argument("--workspace", default=str(WS), help="Ordner für die Test-Bibliotheken (unter tests/_tmp)")
    parser.add_argument("--shots", default=None, help="Ordner für Bildschirmfotos")
    parser.add_argument("--only", default="", help="Komma-Liste der Prüfungen")
    args = parser.parse_args(argv)
    BASE, TOKEN, WS = args.base.rstrip("/"), args.token, Path(args.workspace)
    if args.shots:
        SHOTS = Path(args.shots)
        SHOTS.mkdir(parents=True, exist_ok=True)
    WS.mkdir(parents=True, exist_ok=True)
    names = [n for n in args.only.split(",") if n] or list(CHECKS)
    failed = 0
    for name in names:
        try:
            with browser() as page:
                summary = CHECKS[name](page)
            print(f"PASS {name}: {summary}", flush=True)
        except Skip as exc:
            print(f"SKIP {name}: {exc}", flush=True)
        except Exception as exc:  # noqa: BLE001 - jede Prüfung einzeln melden
            failed += 1
            print(f"FAIL {name}: {exc}", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.exit(main())
