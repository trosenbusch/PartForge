"""Playwright-Regressionsprüfungen der Shell (Review-Runde „fix:fe-shell“).

Läuft gegen einen **isolierten** PartForge-Server (eigenes PARTFORGE_HOME, PARTFORGE_NO_ALTIUM=1, Token über
PARTFORGE_TOKEN) mit dem zu prüfenden Frontend-Build (PARTFORGE_WEB_DIR). Legt seine Test-Bibliotheken unter
``--workspace`` an. Jede Prüfung meldet PASS/FAIL; Exit-Code 1, wenn eine fehlschlägt.

    $env:PARTFORGE_HOME='…\\tests\\_tmp\\home-x'; $env:PARTFORGE_NO_ALTIUM='1'; $env:PARTFORGE_TOKEN='t'
    $env:PARTFORGE_WEB_DIR='…\\tests\\_tmp\\web-x'; python -m partforge --server-only --port 8873
    python tests/ui/shell_regressions.py --base http://127.0.0.1:8873 --token t --workspace …\\tests\\_tmp\\ws-x
    python tests/ui/shell_regressions.py … --only f1_switch,k7_palette      # einzelne Prüfungen

Prüfungen (Review-Befund in Klammern): Bibliothekswechsel während einer Serie (F1), Job-Dock verdeckt die
Altium-Aktionen nicht (F8), DbLib-Name neuer Bibliotheken (F10), neutrale Vorgaben in den Bibliotheks-Dialogen (F6),
Erfolgsansicht ohne Writer (F2), Systemstatus führt zum Writer-Feld (F2), Altium-Status nach dem Speichern (F7),
Befehl „Datenblatt suchen …“ und Rangfolge (K7), Regler-ARIA ohne Exponent, Fokusring der Reiter, Verlaufstokens
(K13), Kategoriebaum ohne stumm abgeschnittene Namen (F8 UX), Bibliotheksname fremder Jobs im Dock (K2), kein
Neuladen der Bibliotheksprüfung nach einem Export (perf-health-dashboard).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

BASE = "http://127.0.0.1:8873"
TOKEN = "fixshell"
WS = Path(__file__).resolve().parents[1] / "_tmp" / "ws-fix-fe-shell"
SHOTS: Path | None = None


# --------------------------------------------------------------------------- API-Helfer


def api(method: str, path: str, body=None, timeout=120):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("X-PartForge-Token", TOKEN)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw and "json" in resp.headers.get("content-type", "") else raw
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {path} → {exc.code}: {exc.read().decode('utf-8', 'replace')}") from None


def wait_job(job_id: str, timeout=180) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        job = api("GET", f"/api/jobs/{job_id}")
        if job["status"] in ("done", "failed", "cancelled"):
            return job
        time.sleep(0.25)
    raise TimeoutError(job_id)


def library(name: str, *, examples=True, fresh=False) -> dict:
    """Bibliothek ``WS/<name>`` öffnen bzw. (neu) anlegen – ohne den Schreib-Job (schnell, ohne Writer)."""
    root = WS / name
    if fresh and root.exists():
        api("POST", "/api/workspace/close")
        shutil.rmtree(root)
    if (root / "partforge.json").exists():
        return api("POST", "/api/workspace/open", {"path": str(root)})
    return api("POST", "/api/workspace/create", {"path": str(root), "name": name, "with_examples": examples,
                                                 "write_libraries": False})


@contextmanager
def browser(width=1480, height=940):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": width, "height": height}, locale="de-DE")
        ctx.add_init_script("try{localStorage.setItem('pf-theme','dark')}catch(e){}")
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


def shot(page, name: str) -> None:
    if SHOTS:
        page.screenshot(path=str(SHOTS / f"{name}.png"))


def toasts(page) -> list[str]:
    return page.eval_on_selector_all("[data-sonner-toast]", "els => els.map(e => e.innerText.replace(/\\s+/g, ' ').trim())")


def dock_pill(page):
    """Die Pille des Job-Docks (unten rechts, aria-expanded)"""
    return page.locator("div.fixed.bottom-5.right-5 > button[aria-expanded]")


def palette(page, query: str) -> None:
    """Befehlspalette öffnen (Strg+K, sobald die Shell bereit ist) und `query` eintippen."""
    page.get_by_role("navigation", name="Bereiche").wait_for(timeout=15_000)
    box = page.get_by_role("combobox", name="Befehlspalette")
    for _ in range(10):
        page.keyboard.press("Control+k")
        try:
            box.wait_for(timeout=1000)
            break
        except Exception:  # noqa: BLE001 - Kürzel noch nicht angemeldet: erneut
            continue
    box.fill(query)
    page.wait_for_timeout(400)


def fulfill_json(route, data, status=200) -> None:
    route.fulfill(status=status, content_type="application/json", body=json.dumps(data))


class Fail(AssertionError):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise Fail(message)


# --------------------------------------------------------------------------- Prüfungen


def f1_switch(page) -> str:
    """Bibliothekswechsel während einer laufenden Serie: Rückfrage vorher, Abbruch-Meldung und gelbe Pille danach."""
    library("SwitchB", examples=False)
    library("SwitchA", examples=True, fresh=True)

    # Reihenfolge wie im E2E-Lauf erzwingen: der abgebrochene Job kommt per SSE an, bevor „Öffnen“ antwortet
    def slow_open(route):
        resp = route.fetch()
        page.wait_for_timeout(2500)
        route.fulfill(response=resp)

    page.route("**/api/workspace/open", slow_open)
    page.goto(BASE + "/serien?vorlage=yageo-rc-l")
    page.get_by_role("button", name="Weiter: Vorschau").click()
    page.get_by_role("button", name="Weiter: Erzeugen").click(timeout=60_000)
    page.get_by_role("button", name="Serie erzeugen", exact=True).click()
    page.wait_for_timeout(800)
    page.get_by_role("button", name="Bibliothek wechseln, aktuell: SwitchA").click()
    page.get_by_role("menuitem", name="SwitchB").click()
    problems: list[str] = []
    dialog = page.get_by_role("alertdialog")
    try:
        dialog.wait_for(timeout=2500)
    except Exception:  # noqa: BLE001 - ältere Fassung: keine Rückfrage, der Wechsel läuft sofort
        problems.append("keine Rückfrage vor dem Abbruch der laufenden Serie")
    else:
        text = dialog.inner_text()
        if "läuft noch und wird abgebrochen" not in text:
            problems.append(f"Rückfrage ohne Hinweis auf den Job: {text!r}")
        shot(page, "f1_confirm")
        dialog.get_by_role("button", name="Trotzdem wechseln").click()
    page.wait_for_timeout(4500)
    shown = toasts(page)
    shot(page, "f1_after_switch")
    if not any("gewechselt" in t and "abgebrochen" in t for t in shown):
        problems.append(f"keine Abbruch-Meldung (Toasts: {shown})")
    pill = dock_pill(page)
    if not (pill.count() == 1 and "Hinweisen" in pill.inner_text()):
        problems.append("keine Pille mit dem Abbruch")
    job = next(j for j in api("GET", "/api/jobs") if j["kind"] == "series")
    check(job["status"] == "cancelled" and job.get("cancel_reason") == "library_switch",
          f"Serie nicht durch den Wechsel abgebrochen ({job['status']}) – Prüfung ungültig")
    check(not problems, "; ".join(problems))
    return "Rückfrage, Toast und Pille „Erledigt mit Hinweisen“"


def f8_dock(page) -> str:
    """Ein auf der Altium-Seite gestarteter Job öffnet das Panel nicht – „⋯ Weitere Altium-Aktionen“ bleibt bedienbar."""
    library("DockLib", examples=True)
    for _ in range(6):  # frühere Jobs der Sitzung füllen das Panel (wie im E2E-Lauf)
        wait_job(api("POST", "/api/libraries/scan", {"register_unknown": False})["job"]["id"])
    # Aktionen kommen nur noch als Router-State (nie aus ?aktion= der Adresse): Befehl der Altium-Seite ausführen
    page.goto(BASE + "/altium")
    palette(page, "Bibliotheksdateien synchronisieren")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    panel = page.get_by_role("region", name="Hintergrundjobs")
    shot(page, "f8_altium_after_sync")
    check(panel.count() == 0, "Panel des Job-Docks hat sich von selbst geöffnet")
    page.get_by_role("button", name="Weitere Altium-Aktionen").click(timeout=3000)
    check(page.get_by_role("menuitem").count() > 0, "Menü „Weitere Altium-Aktionen“ öffnet nicht")
    page.keyboard.press("Escape")
    return "Panel zu, Aktion bedienbar"


def _open_create_dialog(page):
    palette(page, "Neue Bibliothek anlegen")
    page.keyboard.press("Enter")
    dlg = page.get_by_role("dialog", name="Neue Bibliothek anlegen")
    dlg.wait_for()
    return dlg


def f10_dblib_name(page) -> str:
    """„Neue Bibliothek anlegen“ schlägt einen eigenen DbLib-Namen vor und warnt bei Gleichnamigkeit."""
    library("DockLib", examples=True)  # offen, DbLib „PartForge.DbLib“
    bodies: list[dict] = []

    def capture(route):
        if route.request.method == "POST":
            bodies.append(json.loads(route.request.post_data or "{}"))
            fulfill_json(route, {"detail": "Testabbruch – nichts angelegt."}, status=400)
        else:
            route.continue_()

    page.route("**/api/workspace/create", capture)
    page.goto(BASE + "/")
    dlg = _open_create_dialog(page)
    dlg.get_by_label("Name").fill("Zweite Bibliothek")
    dblib = dlg.get_by_label("DbLib-Datei")
    check(dblib.count() == 1, "der Dialog bietet keinen DbLib-Namen an (jede neue Bibliothek hieße „PartForge.DbLib“)")
    page.wait_for_timeout(900)  # Vorschlag des Backends zum Namen (GET /api/workspace/defaults, entprellt)
    proposed = dblib.input_value()
    check(proposed.replace("_", " ").startswith("Zweite Bibliothek"), f"DbLib-Vorschlag folgt nicht dem Namen: {proposed!r}")
    dlg.get_by_label("Ordner").fill(str(WS / "Zweite"))
    dblib.fill("PartForge")
    page.wait_for_timeout(200)
    check(dlg.get_by_text("Gleichnamige DbLib").count() == 1, "keine Warnung bei gleichem DbLib-Namen")
    shot(page, "f10_same_name")
    dblib.fill(proposed)
    dlg.get_by_role("button", name="Bibliothek anlegen").click()
    page.wait_for_timeout(800)
    check(len(bodies) == 1, "kein Anlegen gesendet")
    sent = (bodies[0].get("settings") or {}).get("dblib_file")
    check(sent == f"{proposed}.DbLib", f"gesendeter DbLib-Name: {sent!r}")
    return f"Vorschlag „{proposed}.DbLib“ gesendet, Warnung bei „PartForge.DbLib“"


def f6_defaults(page) -> str:
    """Keine Pfade des Entwicklerrechners: neutraler Ordner-Vorschlag, „Öffnen“ ohne Ordner sendet nichts."""
    library("DockLib", examples=True)
    opened: list[str] = []
    page.route("**/api/workspace/recent", lambda route: fulfill_json(route, []))
    page.route("**/api/workspace/open", lambda route: (opened.append(route.request.post_data or ""), route.abort()))
    page.goto(BASE + "/")
    dlg = _open_create_dialog(page)
    folder = dlg.get_by_label("Ordner").input_value()
    check("Altium_Libs" not in folder and "C:\\Projekte" not in folder, f"Ordner-Vorgabe: {folder!r}")
    dlg.get_by_label("Ordner").fill("")
    dlg.get_by_role("button", name="Bibliothek anlegen").click()
    page.wait_for_timeout(300)
    error = dlg.get_by_role("alert").first.inner_text()
    check("Altium_Libs" not in error and "Bibliotheken" in error, f"Beispiel im Hinweis: {error!r}")
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    palette(page, "Bibliothek öffnen")
    page.keyboard.press("Enter")
    dlg = page.get_by_role("dialog", name="Bibliothek öffnen")
    dlg.wait_for()
    dlg.get_by_role("button", name="Öffnen", exact=True).click()
    page.wait_for_timeout(600)
    check(not opened, f"„Öffnen“ ohne Ordner hat {opened} gesendet")
    check(dlg.get_by_text("Bitte den Ordner einer Bibliothek angeben").count() == 1, "kein Hinweis auf den fehlenden Ordner")
    shot(page, "f6_open_empty")
    return f"Ordner-Vorgabe {folder or '(leer)'}, leeres Öffnen gesperrt"


LONG_REASON = (
    "Kein Bibliotheks-Writer verfügbar – bitte den Pfad zum Bibliotheks-Writer unter Einstellungen › Allgemein › "
    "Altium Designer eintragen oder Altium Designer starten. Grund: Der Bibliotheks-Writer wurde nicht gefunden; "
    "Altium Designer ist nicht gestartet. Nicht geschriebene Symbole und Footprints bleiben „ausstehend“ und werden "
    "beim nächsten Synchronisieren geschrieben."
)


def f2_created_writer(page) -> str:
    """Erfolgsansicht „Neue Bibliothek“ ohne Writer: voller Grund und „Bibliotheks-Writer einrichten“."""
    info = library("DockLib", examples=True)
    job = {
        "id": "fakewrite1", "kind": "libraries", "title": "Bibliotheken schreiben", "status": "done", "progress": 1,
        "message": "Bibliotheken nicht geschrieben – kein Bibliotheks-Writer verfügbar; Symbole und Footprints bleiben ausstehend",
        "log": [], "result": {"skipped": True, "reason": LONG_REASON}, "error": None, "created": time.time(),
        "started": time.time(), "finished": time.time(), "version": 5,
    }
    created = {**info, "name": "Ohne Writer", "examples": {"parts": 19, "symbols": 15, "footprints": 13},
               "examples_error": None, "job": job}
    page.route("**/api/workspace/create", lambda route: fulfill_json(route, created))
    page.route("**/api/jobs/fakewrite1", lambda route: fulfill_json(route, job))
    page.goto(BASE + "/")
    dlg = _open_create_dialog(page)
    dlg.get_by_label("Ordner").fill(str(WS / "OhneWriter"))
    dlg.get_by_role("button", name="Bibliothek anlegen").click()
    # nach dem Anlegen heißt der Dialog wie die Erfolgsansicht
    done = page.get_by_role("dialog", name="Bibliothek „Ohne Writer“ angelegt")
    status = done.get_by_role("status")
    status.wait_for(timeout=5000)
    text = status.inner_text()
    shot(page, "f2_created_no_writer")
    check("beim nächsten Synchronisieren geschrieben." in text, f"Grund gekürzt: {text!r}")
    check(" …" not in text.split("\n")[0], "Grund mit „…“ abgeschnitten")
    setup = done.get_by_role("button", name="Bibliotheks-Writer einrichten")
    check(setup.count() == 1, "kein Knopf „Bibliotheks-Writer einrichten“")
    setup.click()
    page.wait_for_timeout(600)
    check(page.url.endswith("/einstellungen#altium"), f"Ziel: {page.url}")
    return "voller Text, Knopf führt zu /einstellungen#altium"


def f2_status_link(page) -> str:
    """Seitenleiste: „Altium – kein Writer“ führt zum Writer-Feld der Einstellungen."""
    library("DockLib", examples=True)

    def no_writer(route):
        resp = route.fetch()
        data = resp.json()
        data["altium_running"] = False
        data["altium_exe"] = data.get("altium_exe") or "C:\\Programme\\Altium\\AD26\\X2.EXE"
        for b in data.get("backends", []):
            if b.get("name") == "rust":
                b["available"] = False
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/api/altium/status", no_writer)
    page.goto(BASE + "/bauteile")
    page.wait_for_timeout(1500)
    item = page.locator("aside button", has_text="Altium").last
    label = item.inner_text().replace("\n", " ")
    item.click()
    page.wait_for_timeout(500)
    check(page.url.endswith("/einstellungen#altium"), f"Statuszeile „{label}“ führt zu {page.url}")
    return f"„{label}“ → /einstellungen#altium"


def f7_status_after_save(page) -> str:
    """Nach dem Speichern der Einstellungen lädt der Altium-/Writer-Status sofort neu (nicht erst nach 15 s)."""
    library("DockLib", examples=True)
    events: list[tuple[str, float]] = []
    page.on("request", lambda r: events.append(("status", time.time())) if r.url.endswith("/api/altium/status") else None)
    page.on("requestfinished", lambda r: events.append(("saved", time.time())) if r.method == "PUT" and r.url.endswith("/api/settings") else None)
    page.goto(BASE + "/einstellungen")
    page.wait_for_timeout(2000)
    author = page.get_by_placeholder("Ihr Name")
    old = author.input_value()
    author.fill(f"{old} x" if old else "Prüfer")
    page.keyboard.press("Control+s")
    page.wait_for_timeout(1500)
    saved = [t for k, t in events if k == "saved"]
    check(bool(saved), "Speichern nicht ausgelöst")
    after = [t for k, t in events if k == "status" and t >= saved[0] - 0.2]
    # Name zurücksetzen
    author.fill(old)
    page.keyboard.press("Control+s")
    page.wait_for_timeout(800)
    check(bool(after) and after[0] - saved[0] < 1.4, f"Status nach dem Speichern nicht neu geladen ({after})")
    return f"Status {after[0] - saved[0]:.2f} s nach dem Speichern"


def k7_palette(page) -> str:
    """„Datenblatt suchen …“ global (→ /import?suche=1), gesperrt ohne KI; „Serie“ ohne Zufallstreffer."""
    library("DockLib", examples=True)
    page.goto(BASE + "/bauteile")
    page.wait_for_timeout(1200)
    palette(page, "Serie")
    names = page.get_by_role("option").all_inner_texts()
    check(not any("Bibliotheksordner im Explorer zeigen" in n for n in names), f"Zufallstreffer für „Serie“: {names}")
    page.keyboard.press("Escape")
    palette(page, "Datenblatt suchen")
    option = page.get_by_role("option", name="Datenblatt suchen …")
    check(option.count() >= 1, "Befehl „Datenblatt suchen …“ fehlt außerhalb von /import")
    page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    check("/import?suche=1" in page.url, f"Ziel: {page.url}")

    def ai_off(route):
        if route.request.method != "GET":
            route.continue_()
            return
        resp = route.fetch()
        data = resp.json()
        data["settings"]["ai"]["enabled"] = False
        route.fulfill(response=resp, body=json.dumps(data))

    page.route("**/api/settings", ai_off)
    page.goto(BASE + "/bauteile")
    page.wait_for_timeout(1200)
    palette(page, "Datenblatt suchen")
    option = page.get_by_role("option").filter(has_text="Datenblatt suchen")
    check(option.count() >= 1 and option.first.get_attribute("aria-disabled") == "true", "ohne KI nicht gesperrt")
    check("ausgeschaltet" in option.first.inner_text(), "Grund der Sperre fehlt")
    shot(page, "k7_palette_ai_off")
    return "global, gesperrt ohne KI, Rangfolge ohne Zufallstreffer"


def k13_slider_aria(page) -> str:
    """Regler schreiben ARIA-Werte als Dezimalzahl, nie „1e-12“ (Schutz vor Rückfall – der Serien-Assistent rechnet
    seine Werte inzwischen selbst in eine Untereinheit um; die Formatierung prüft der Unit-Test `plainNumber`)."""
    library("DockLib", examples=True)
    page.goto(BASE + "/serien?vorlage=kemet-c-x7r")
    page.wait_for_timeout(2500)
    values = page.eval_on_selector_all(
        "[role=slider]",
        "els => els.map(e => [e.getAttribute('aria-valuemin'), e.getAttribute('aria-valuenow'), e.getAttribute('aria-valuemax')])",
    )
    check(bool(values), "kein Regler gefunden")
    bad = [v for v in values if any(x is not None and "e" in x.lower() for x in v)]
    check(not bad, f"Exponent in ARIA-Werten: {bad}")
    return f"{len(values)} Regler, z. B. {values[0]}"


def k13_tabs_focus(page) -> str:
    """Fokusring des Reiterinhalts liegt unter dem Inhalt (kein Umriss über den ersten 2 px)."""
    library("DockLib", examples=True)
    page.goto(BASE + "/einstellungen/hausstil")
    page.wait_for_timeout(1500)
    page.get_by_role("tab", selected=True).first.focus()
    page.keyboard.press("Tab")
    style = page.evaluate(
        "() => { const el = document.activeElement; const s = getComputedStyle(el);"
        " return { role: el.getAttribute('role'), offset: s.outlineOffset, outline: s.outlineColor, shadow: s.boxShadow } }"
    )
    check(style["role"] == "tabpanel", f"Fokus nicht auf dem Reiterinhalt: {style}")
    check(style["offset"] != "-2px" and "inset" in style["shadow"], f"Fokusring überdeckt den Inhalt: {style}")
    return f"box-shadow {style['shadow']}"


def k13_gradient_tokens(page) -> str:
    """Spinner und Fortschrittsring nehmen ihre Verlaufsfarben aus den Tokens (keine Hex-Stopps)."""
    library("DockLib", examples=True)
    page.goto(BASE + "/ui-kit")
    page.wait_for_timeout(2500)
    stops = page.eval_on_selector_all(
        "[role=progressbar] linearGradient stop, svg.animate-spin linearGradient stop",
        "els => els.map(e => e.getAttribute('stop-color') || e.getAttribute('style') || '')",
    )
    check(bool(stops), "keine Verlaufsstopps gefunden")
    hexed = [s for s in stops if "#" in s]
    check(not hexed, f"Hex-Stopps: {hexed[:4]}")
    return f"{len(stops)} Stopps über var(--pf-…)"


def f8_category_tree(page) -> str:
    """Kategoriebaum bei 1120 × 720: kein Name ist abgeschnitten, ohne dass der volle Name als Tooltip dasteht."""
    library("DockLib", examples=True)
    page.set_viewport_size({"width": 1120, "height": 720})
    page.goto(BASE + "/bauteile")
    page.wait_for_timeout(2000)
    rows = page.eval_on_selector_all(
        "[role=treeitem] span",
        "els => els.filter(e => e.children.length === 0 || e.querySelector('mark')).map(e => ({ text: e.textContent,"
        " clipped: e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1,"
        " title: e.getAttribute('title') || e.closest('[title]')?.getAttribute('title') || null }))",
    )
    check(bool(rows), "Kategoriebaum leer")
    silent = [r["text"] for r in rows if r["clipped"] and not r["title"]]
    shot(page, "f8_category_tree_1120")
    check(not silent, f"abgeschnitten ohne Tooltip: {silent}")
    return f"{len(rows)} Einträge, {sum(r['clipped'] for r in rows)} gekürzt (mit Tooltip)"


def _fake_jobs(page, jobs_by_phase: Callable[[], list[dict]]) -> None:
    """Jobliste aus der Prüfung statt vom Backend (Live-Strom aus → das Dock pollt)."""
    page.route("**/api/jobs/events*", lambda route: route.abort())
    page.route("**/api/jobs?*", lambda route: fulfill_json(route, jobs_by_phase()))


def _job(id_: str, kind: str, status: str, **extra) -> dict:
    now = time.time()
    return {"id": id_, "kind": kind, "title": extra.pop("title", f"Test {kind}"), "status": status,
            "progress": 1 if status != "running" else 0.4, "message": extra.pop("message", "läuft …"), "log": [],
            "result": extra.pop("result", None), "error": None, "created": now - 5, "started": now - 5,
            "finished": None if status == "running" else now, "version": 2 if status == "running" else 9, **extra}


def k2_dock_library(page) -> str:
    """Das Job-Dock nennt die Bibliothek eines Jobs, der nicht zur geöffneten gehört."""
    library("DockLib", examples=True)
    other = str(WS / "Andere Bibliothek")
    _fake_jobs(page, lambda: [_job("k2a", "altium.verify", "running", title="In Altium prüfen", library=other)])
    page.goto(BASE + "/bauteile")
    page.wait_for_timeout(1500)
    palette(page, "Hintergrundjobs anzeigen")
    page.keyboard.press("Enter")
    panel = page.get_by_role("region", name="Hintergrundjobs")
    panel.wait_for(timeout=3000)
    shot(page, "k2_dock_library")
    check(panel.get_by_text("Andere Bibliothek").count() >= 1, "Bibliotheksname fehlt im Dock")
    return "Name der fremden Bibliothek im Panel"


def perf_health(page) -> str:
    """Nach einem Export laden Übersicht/Prüfbericht die teuren Bibliotheksprüfungen nicht neu, nach einer Serie schon."""
    library("DockLib", examples=True)
    phase = {"kind": "export", "status": "running"}
    _fake_jobs(page, lambda: [_job("perf-" + phase["kind"], phase["kind"], phase["status"],
                                   message="Export fertig" if phase["status"] == "done" else "läuft …",
                                   result={"rows": 1} if phase["status"] == "done" else None)])
    page.route("**/api/jobs/perf-*", lambda route: fulfill_json(
        route, _job(route.request.url.rsplit("/", 1)[-1], phase["kind"], phase["status"], result={"rows": 1})))
    hits: list[str] = []
    page.on("request", lambda r: hits.append(r.url) if ("/api/libraries/health" in r.url or "/api/health-check" in r.url) else None)
    page.goto(BASE + "/")
    page.wait_for_timeout(5000)  # erste Prüfung + Job „läuft“ gesehen
    hits.clear()
    phase["status"] = "done"
    page.wait_for_timeout(4000)
    after_export = len(hits)
    # Gegenprobe: eine Serie (schreibt Bauteile) lädt neu
    phase.update(kind="series", status="running")
    page.wait_for_timeout(2500)
    hits.clear()
    phase["status"] = "done"
    page.wait_for_timeout(4000)
    after_series = len(hits)
    check(after_export == 0, f"nach dem Export {after_export} Prüfungen neu geladen")
    check(after_series > 0, "nach der Serie nichts neu geladen (Gegenprobe)")
    return f"Export: 0, Serie: {after_series} Neuladungen"


CHECKS: dict[str, Callable] = {
    "f1_switch": f1_switch,
    "f8_dock": f8_dock,
    "f10_dblib_name": f10_dblib_name,
    "f6_defaults": f6_defaults,
    "f2_created_writer": f2_created_writer,
    "f2_status_link": f2_status_link,
    "f7_status_after_save": f7_status_after_save,
    "k7_palette": k7_palette,
    "k13_slider_aria": k13_slider_aria,
    "k13_tabs_focus": k13_tabs_focus,
    "k13_gradient_tokens": k13_gradient_tokens,
    "f8_category_tree": f8_category_tree,
    "k2_dock_library": k2_dock_library,
    "perf_health": perf_health,
}


def main(argv: list[str] | None = None) -> int:
    global BASE, TOKEN, WS, SHOTS
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--token", default=TOKEN)
    parser.add_argument("--workspace", default=str(WS), help="Ordner für die Test-Bibliotheken (unter tests/_tmp)")
    parser.add_argument("--shots", default=None, help="Ordner für Bildschirmfotos")
    parser.add_argument("--only", default="", help="Komma-Liste der Prüfungen")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):  # Windows-Konsole (cp1252): „→“, „›“ in den Meldungen
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    BASE, TOKEN, WS = args.base.rstrip("/"), args.token, Path(args.workspace)
    WS.mkdir(parents=True, exist_ok=True)
    if args.shots:
        SHOTS = Path(args.shots)
        SHOTS.mkdir(parents=True, exist_ok=True)
    selected = [n for n in (args.only.split(",") if args.only else CHECKS) if n]
    failed = 0
    for name in selected:
        fn = CHECKS[name]
        started = time.time()
        try:
            with browser() as page:
                detail = fn(page)
            print(f"PASS {name:24} {time.time() - started:5.1f}s  {detail}")
        except Fail as exc:
            failed += 1
            print(f"FAIL {name:24} {time.time() - started:5.1f}s  {exc}")
        except Exception as exc:  # noqa: BLE001 - Prüfung abgestürzt
            failed += 1
            first = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            print(f"FAIL {name:24} {time.time() - started:5.1f}s  {type(exc).__name__}: {first}")
    print(f"{len(selected) - failed}/{len(selected)} bestanden")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
