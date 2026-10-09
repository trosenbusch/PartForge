"""Playwright-Regressionsprüfungen der Runde „polish“ (kleine Befunde des Altium-Regressionslaufs).

Läuft gegen einen **isolierten** PartForge-Server mit einem **Altium im Speicher** (kein Altium!): ``serve`` startet
ihn in diesem Prozess – eigenes PARTFORGE_HOME, PARTFORGE_NO_ALTIUM=1, Token über PARTFORGE_TOKEN, das zu prüfende
Frontend über PARTFORGE_WEB_DIR. Die Altium-Brücke ist das Test-Double ``tests/test_refresh_support.FakeBridge``
(installieren/deinstallieren im Speicher); es löst Bauteile mit den Werten der Datenbank auf – den Verstärker LM358DR
mit veralteten Werten (ohne „Slew Rate“, alte Beschreibung) – und der Restart Manager meldet nach dem Deinstallieren
„Altium Designer“ als Halter der Datenbank. Test-Bibliotheken entstehen unter ``--workspace``. Jede Prüfung meldet
PASS/FAIL/SKIP; Exit-Code 1, wenn eine fehlschlägt.

    $env:PARTFORGE_HOME='…\\tests\\_tmp\\home-polish'; $env:PARTFORGE_NO_ALTIUM='1'; $env:PARTFORGE_TOKEN='polish'
    $env:PARTFORGE_WEB_DIR='…\\tests\\_tmp\\web-polish'; python tests/ui/polish_regressions.py serve --port 8903
    python tests/ui/polish_regressions.py --base http://127.0.0.1:8903 --token polish --workspace …\\tests\\_tmp\\ws-polish
    python tests/ui/polish_regressions.py … --only e2ereg1_submenu,stepper_1120 --shots …\\screens

Prüfungen: Untermenü „In Altium prüfen › Eine Kategorie“ mit Farbpunkt, Abstand und Namen „Widerstände, 2 Bauteile“
(E2EREG-1); „Aus Altium deinstallieren“ bei belegter Datenbank als gelber Hinweis mit vollem Text, Dock „Fertig mit
Hinweisen“ (E2EREG-2); „nicht installiert“ statt „noch nicht installiert“ samt Installieren (Wortlaut); Parameter und
Beschreibung im Ergebnis „In Altium geprüft“ mit aufklappbarer Liste (E2EREG-3); Stepper bei 1120 px ohne gekürzte
Schritte (Stepper); Erfolgsansicht „Neue Bibliothek“ ohne SQLite-ODBC-Treiber (ODBC).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = "http://127.0.0.1:8903"
TOKEN = "polish"
WS = ROOT / "tests" / "_tmp" / "ws-polish"
SHOTS: Path | None = None
#: Verstärker der Beispielbibliothek, den das Altium im Speicher mit veralteten Werten liefert
STALE_PART = "LM358DR"
STALE_PARAMETER = "Slew Rate"


# --------------------------------------------------------------------------- Server mit Altium im Speicher


def _fake_altium():
    """Das In-Memory-Altium der Testsuite, erweitert um ``resolve_db_components`` mit den Werten der Datenbank."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_refresh_support import FakeBridge

    from partforge.altium.bridge.core import DbComponentResolution
    from partforge.altium.dblib import ADD_MODE_DO_NOT_ADD, field_map_for
    from partforge.db import categories, parts, registry
    from partforge.workspace import current

    class FakeAltium(FakeBridge):
        def resolve_db_components(self, dblib, keys, *, timeout_s=None):
            self._call("resolve_db_components", dblib, tuple(keys))
            ws = current()
            out = []
            for table, key in keys:
                row = parts.get_part(table, key)
                if row is None:
                    out.append(DbComponentResolution(dblib=str(dblib), table=table, key=key, loaded=False))
                    continue
                cat = categories.get_category(table)
                params: dict[str, str] = {}
                for field in cat.fields:
                    mapping = field_map_for(cat.table, field)
                    if mapping is not None and (mapping.parameter_name.startswith("[")
                                                or mapping.add_mode == ADD_MODE_DO_NOT_ADD):
                        continue
                    if row.get(field.column) not in (None, ""):
                        params[field.column] = str(row[field.column])
                description = str(row.get("Description") or "")
                if key == STALE_PART:  # Altium hat noch den Stand vor dem Eintragen der Slew Rate
                    old = params.pop(STALE_PARAMETER, "")
                    description = " ".join(description.replace(old, "").split()) if old else description
                ref = str(row.get("Library Ref") or "")
                record = registry.get_symbol(ref) if ref else None
                footprints = [str(row[c]) for c in ("Footprint Ref", "Footprint Ref 2") if row.get(c)]
                out.append(DbComponentResolution(
                    dblib=str(dblib), table=table, key=key, loaded=True,
                    symbol_path=str(ws.abs(str(row.get("Library Path") or ""))), symbol_ref=ref, lib_reference=ref,
                    pin_count=record.pin_count if record is not None else None, footprints=footprints,
                    current_footprint=footprints[0] if footprints else None, parameters=params,
                    description=description, comment=params.get("Comment", ""), comment_visible=True,
                    visible_parameters=["Comment"], designator="U?", design_item_id=key))
            return out

    return FakeAltium()


def serve(port: int) -> int:
    """API-Server in diesem Prozess: Altium „läuft“ (im Speicher), nach dem Deinstallieren hält „Altium Designer“ die
    Datenbank (Restart Manager simuliert). Nichts erreicht ein echtes Altium."""
    assert os.environ.get("PARTFORGE_HOME"), "PARTFORGE_HOME muss gesetzt sein (isolierte Einstellungen)"
    assert os.environ.get("PARTFORGE_NO_ALTIUM") == "1", "PARTFORGE_NO_ALTIUM=1 muss gesetzt sein"
    sys.path.insert(0, str(ROOT))
    from partforge.altium import holders, refresh

    fake = _fake_altium()
    refresh.default_bridge = lambda settings=None: fake  # routes_altium.get_bridge → das Altium im Speicher
    refresh.set_refresh_service(refresh.AltiumRefreshService(
        bridge_factory=lambda: fake, session_provider=lambda: None, probe_install_state=True))
    holders.file_holders = lambda paths: [holders.FileHolder(pid=81348, name="Altium Designer")]
    from partforge.__main__ import main as partforge_main

    return partforge_main(["--server-only", "--port", str(port)])


# --------------------------------------------------------------------------- API-Helfer


def api(method: str, path: str, body=None, timeout=180):
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


def library(name: str, *, fresh=False) -> dict:
    """Bibliothek ``WS/<name>`` öffnen bzw. mit Beispielen und geschriebenen Bibliotheksdateien anlegen."""
    root = WS / name
    if fresh and root.exists():
        api("POST", "/api/workspace/close")
        shutil.rmtree(root)
    if (root / "partforge.json").exists():
        return api("POST", "/api/workspace/open", {"path": str(root)})
    info = api("POST", "/api/workspace/create", {"path": str(root), "name": name, "with_examples": True,
                                                 "write_libraries": True})
    if info.get("job"):
        wait_job(info["job"]["id"])
    return info


def installed(state: bool) -> None:
    """DbLib im Altium im Speicher installieren bzw. deinstallieren (wie die Knöpfe, über die API) – nach dem
    tatsächlichen Stand („Installationsstatus prüfen“): der gemerkte Stand übersteht einen Neustart des Servers, das
    Altium im Speicher nicht."""
    now = wait_job(api("POST", "/api/altium/install-state")["job"]["id"])["result"]["state"]["installed"]
    if bool(now) != state:
        wait_job(api("POST", f"/api/altium/{'install' if state else 'uninstall'}")["job"]["id"])


@contextmanager
def browser(width=1440, height=900):
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


def goto(page, path: str, wait: str | None = None) -> None:
    page.goto(BASE + path)
    page.get_by_role("navigation", name="Bereiche").wait_for(timeout=20_000)
    if wait:
        page.wait_for_selector(wait, timeout=20_000)


def palette(page, query: str) -> None:
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


def toast_items(page) -> list[dict]:
    return page.eval_on_selector_all(
        "[data-sonner-toast]",
        "els => els.map(e => ({type: e.getAttribute('data-type'), text: e.innerText.replace(/\\s+/g, ' ').trim()}))")


class Fail(AssertionError):
    pass


class Skip(Exception):
    pass


def check(cond: bool, message: str) -> None:
    if not cond:
        raise Fail(message)


def open_verify_submenu(page):
    """„In Altium prüfen“ › „Eine Kategorie“ öffnen – das Untermenü (role=menu)."""
    page.get_by_role("group", name="In Altium").get_by_role("button", name=re.compile(r"In Altium prüfen")).click()
    menu = page.get_by_role("menu")
    menu.first.wait_for(timeout=10_000)
    trigger = menu.first.get_by_role("menuitem", name="Eine Kategorie")
    trigger.hover()
    page.wait_for_timeout(250)
    trigger.press("ArrowRight")
    page.wait_for_timeout(500)
    return page.get_by_role("menu").last


# --------------------------------------------------------------------------- Prüfungen


def e2ereg1_submenu(page) -> str:
    """E2EREG-1: Untermenü „Eine Kategorie“ – Farbpunkt sichtbar, Name und Anzahl getrennt, Name „Widerstände, 2 Bauteile“."""
    library("Polish")
    installed(True)
    goto(page, "/altium", wait="#altium-headline")
    sub = open_verify_submenu(page)
    items = sub.get_by_role("menuitem")
    check(items.count() >= 10, f"nur {items.count()} Kategorien im Untermenü")
    shot(page, "e2ereg1_submenu")
    sub.get_by_role("menuitem").first.screenshot(path=str(SHOTS / "e2ereg1_item_closeup.png")) if SHOTS else None
    layout = items.evaluate_all("""(els) => els.map((el) => {
        const kids = [...el.children]
        const dot = kids[0].getBoundingClientRect()
        const label = kids[1].querySelector('.truncate')
        const lr = label.getBoundingClientRect()
        const count = kids[2] ? kids[2].getBoundingClientRect() : null
        return {dot: [Math.round(dot.width), Math.round(dot.height)], gap: count ? Math.round(count.left - lr.right) : null,
                cut: label.scrollWidth > label.clientWidth + 1, text: label.textContent, count: kids[2]?.textContent ?? null}
    })""")
    problems = [f"{x['text']}: Punkt {x['dot']}" for x in layout if x["dot"][0] < 7 or x["dot"][1] < 7]
    problems += [f"{x['text']}: Abstand {x['gap']} px" for x in layout if x["gap"] is None or x["gap"] < 6]
    problems += [f"{x['text']}: gekürzt" for x in layout if x["cut"]]
    check(not problems, "; ".join(problems[:6]))
    resistors = sub.get_by_role("menuitem", name=re.compile(r"^Widerstände, \d+ Bauteile?$"))
    check(resistors.count() == 1, "kein Eintrag mit dem Namen „Widerstände, n Bauteile“")
    names = items.evaluate_all("els => els.map((e) => e.getAttribute('aria-label'))")
    check(all(n and re.fullmatch(r"[^,]+, \d+ Bauteile?", n) for n in names), f"Namen: {names}")
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    return f"{len(layout)} Einträge, z. B. „{names[0]}“, Punkt {layout[0]['dot']} px, Abstand {layout[0]['gap']} px"


def e2ereg2_uninstall(page) -> str:
    """E2EREG-2: Deinstallieren, während Altium die Datenbank hält – gelber Toast mit vollem Hinweis, Dock-Zeile
    „Fertig mit Hinweisen“."""
    library("Polish")
    installed(True)
    goto(page, "/altium", wait="#altium-headline")
    page.wait_for_timeout(800)
    page.get_by_role("group", name="In Altium").get_by_role("button", name="Aus Altium deinstallieren").click()
    dialog = page.get_by_role("alertdialog")
    dialog.wait_for(timeout=10_000)
    dialog.get_by_role("button", name="Deinstallieren").click()
    hint = "Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen (sonst Altium neu starten)."
    toast = None
    for _ in range(60):
        toast = next((t for t in toast_items(page) if "deinstall" in t["text"].lower() and "Ordner" in t["text"]), None)
        if toast:
            break
        page.wait_for_timeout(250)
    shot(page, "e2ereg2_toast")
    check(toast is not None, f"kein Toast zum Deinstallieren ({toast_items(page)})")
    check(toast["type"] == "warning", f"Toast ist „{toast['type']}“, kein Hinweis")
    check(hint in toast["text"], f"Hinweis unvollständig: {toast['text']!r}")
    check("Die DbLib wurde in Altium deinstalliert." in toast["text"], "Toast sagt nicht, dass deinstalliert wurde")
    page.locator("div.fixed.bottom-5.right-5 > button[aria-expanded]").click()
    panel = page.get_by_role("region", name="Hintergrundjobs")
    panel.wait_for(timeout=5000)
    page.wait_for_timeout(400)
    ring = panel.get_by_role("progressbar", name=re.compile(r"^DbLib in Altium deinstallieren: "))
    label = ring.first.get_attribute("aria-label") if ring.count() else None
    shot(page, "e2ereg2_dock")
    check(label is not None and label.endswith("Fertig mit Hinweisen"), f"Dock-Status: {label!r}")
    row_text = panel.inner_text()
    check("Ordner erst in etwa einer Minute verschiebbar" in row_text, "Dock-Zeile ohne Hinweis")
    page.keyboard.press("Escape")
    # nach dem Neuladen (ohne die Rückmeldeoptionen dieser Sitzung): `outcome: 'partial'` des Ergebnisses genügt
    goto(page, "/altium", wait="#altium-headline")
    page.wait_for_timeout(1200)
    palette(page, "Hintergrundjobs anzeigen")  # die Pille ist nach dem Neuladen ausgeblendet (keine laufenden Jobs)
    page.keyboard.press("Enter")
    panel = page.get_by_role("region", name="Hintergrundjobs")
    panel.wait_for(timeout=5000)
    page.wait_for_timeout(400)
    ring = panel.get_by_role("progressbar", name=re.compile(r"^DbLib in Altium deinstallieren: "))
    label = ring.first.get_attribute("aria-label") if ring.count() else None
    shot(page, "e2ereg2_dock_after_reload")
    check(label is not None and label.endswith("Fertig mit Hinweisen"), f"Dock nach dem Neuladen: {label!r}")
    page.keyboard.press("Escape")
    return "gelber Toast mit vollem Text, Dock „Fertig mit Hinweisen“ (auch nach dem Neuladen)"


def wording_not_installed(page) -> str:
    """„Die DbLib ist in Altium nicht installiert“ (nicht „noch nicht“) – Altium-Seite und Übersicht, mit Installieren."""
    library("Polish")
    installed(False)
    goto(page, "/altium", wait="#altium-headline")
    page.wait_for_timeout(1500)
    hero = page.locator("section[aria-labelledby=altium-headline]").first
    title = page.locator("#altium-headline").inner_text()
    check(title == "Die DbLib ist in Altium nicht installiert", f"Altium-Seite: {title!r}")
    check(hero.get_by_role("button", name="In Altium installieren").count() >= 1, "kein „In Altium installieren“ im Kopf")
    shot(page, "wording_altium")
    goto(page, "/")
    page.wait_for_selector("text=Altium und DbLib", timeout=20_000)
    page.wait_for_timeout(1500)
    card = page.locator("h2", has_text="Altium und DbLib").locator("xpath=ancestor::*[contains(@class,'rounded-card')][1]")
    text = card.inner_text()
    card.scroll_into_view_if_needed()
    shot(page, "wording_uebersicht")
    check("Die DbLib ist in Altium nicht installiert" in text, f"Übersicht: {text[:120]!r}")
    check(card.get_by_role("button", name="In Altium installieren").count() == 1, "Übersicht ohne „In Altium installieren“")
    body = page.locator("body").inner_text()
    check("noch nicht installiert" not in body, "„noch nicht installiert“ steht noch auf der Übersicht")
    return "Altium-Seite und Übersicht: „nicht installiert“ + Installieren"


def e2ereg3_parameters(page) -> str:
    """E2EREG-3: „In Altium prüfen“ vergleicht Parameter und Beschreibung – Warnung je Abweichung, Comment und
    Beschreibung im Ergebnis, Parameterliste aufklappbar."""
    library("Polish")
    installed(True)
    goto(page, "/altium", wait="#altium-headline")
    sub = open_verify_submenu(page)
    sub.get_by_role("menuitem", name=re.compile(r"^Verstärker, \d+ Bauteile?$")).click()
    page.wait_for_timeout(500)
    deadline = time.time() + 60
    job = None
    while time.time() < deadline:
        job = next((j for j in api("GET", "/api/jobs") if j["kind"] == "altium.verify"), None)
        if job and job["status"] in ("done", "failed", "cancelled"):
            break
        page.wait_for_timeout(400)
    check(job is not None and job["status"] == "done", f"Prüfung nicht fertig: {job and job['status']}")
    page.wait_for_timeout(1500)
    panel = page.get_by_role("tabpanel", name=re.compile(r"^In Altium geprüft"))
    panel.wait_for(timeout=10_000)
    text = panel.inner_text()
    wanted = f"Altium liefert für „{STALE_PARAMETER}“ keinen Wert – in der Datenbank steht „0.3V/µs“."
    check(wanted in text, f"keine Warnung „{wanted}“")
    check("Comment" in text and "Beschreibung" in text, "Comment/Beschreibung fehlen im Ergebnis")
    toggle = panel.get_by_role("button", name=re.compile(r"\d+ Parameter · 1 weicht ab"))
    check(toggle.count() == 1, "kein Knopf „… Parameter · 1 weicht ab“")
    check(toggle.get_attribute("aria-expanded") == "false", "Parameterliste schon offen")
    toggle.click()
    page.wait_for_timeout(300)
    check(toggle.get_attribute("aria-expanded") == "true", "aria-expanded bleibt false")
    table = panel.get_by_role("table", name=f"Parameter von {STALE_PART} in Altium, verglichen mit der Datenbank")
    check(table.count() == 1, "keine Parametertabelle")
    row = table.get_by_role("row", name=re.compile(STALE_PARAMETER))
    row_text = row.first.inner_text().replace("\n", " ") if row.count() else ""
    check("fehlt" in row_text and "0.3V/µs" in row_text, f"Zeile „{STALE_PARAMETER}“: {row_text!r}")
    check(table.get_by_text("gleich").count() >= 5, "zu wenige gleiche Parameter")
    row.first.scroll_into_view_if_needed()
    shot(page, "e2ereg3_parameters")
    # die andere Verstärker-Zeile: alles wie in der Datenbank
    panel.get_by_role("radio", name=re.compile(r"^Alle")).click()
    page.wait_for_timeout(400)
    check(panel.get_by_role("button", name=re.compile(r"\d+ Parameter · wie in der Datenbank")).count() >= 1,
          "kein Bauteil „wie in der Datenbank“")
    shot(page, "e2ereg3_all")
    return "Warnung je Abweichung, Comment/Beschreibung, aufklappbare Parameterliste"


def stepper_1120(page) -> str:
    """Stepper: bei 1120 px (kompakt), 1280 px und 1440 px keine gekürzte Schrittbezeichnung – die Linien schrumpfen
    zuerst (bis 16 px)."""
    library("Polish")
    results = []
    for width in (1120, 1280, 1440):
        page.set_viewport_size({"width": width, "height": 860})
        goto(page, "/serien", wait="ol[aria-label=Fortschritt]")
        page.wait_for_timeout(700)
        data = page.locator("ol[aria-label=Fortschritt]").first.evaluate("""(ol) => ({
            labels: [...ol.querySelectorAll('li .truncate')].map((s) => ({text: s.textContent, cut: s.scrollWidth > s.clientWidth + 1})),
            lines: [...ol.querySelectorAll('li > div[aria-hidden]')].map((d) => Math.round(d.getBoundingClientRect().width)),
        })""")
        shot(page, f"stepper_{width}")
        cut = [x["text"] for x in data["labels"] if x["cut"]]
        check(not cut, f"{width} px: gekürzt {cut}")
        check(min(data["lines"]) >= 16, f"{width} px: Linie kürzer als 16 px ({data['lines']})")
        results.append(f"{width}: Linien {data['lines']}")
    page.set_viewport_size({"width": 1440, "height": 900})
    return "; ".join(results)


def odbc_created(page) -> str:
    """„Neue Bibliothek“ ohne SQLite-ODBC-Treiber: die Erfolgsansicht sagt, dass Altium ihn braucht (Download, ODBC-Test)."""
    info = library("Polish")

    def no_driver(route):
        resp = route.fetch()
        data = resp.json()
        data["odbc"] = {"kind": "sqlite", "driver": "SQLite3 ODBC Driver", "installed": False,
                        "message": "Der ODBC-Treiber „SQLite3 ODBC Driver“ (64 Bit) ist nicht installiert …",
                        "download": "http://www.ch-werner.de/sqliteodbc/"}
        route.fulfill(response=resp, body=json.dumps(data))

    # die Erfolgsansicht erscheint mit dem Job „Bibliotheken schreiben“ (Beispielinhalte) – hier schon fertig
    now = time.time()
    job = {"id": "polish-odbc-write", "kind": "libraries", "title": "Bibliotheken schreiben", "status": "done",
           "progress": 1, "message": "Bibliotheken geschrieben: 15 Symbole und 13 Footprints", "log": [],
           "result": {"symbols": {"ok": 15}, "footprints": {"ok": 13}, "libraries": [f"L{i}" for i in range(14)]},
           "error": None, "created": now, "started": now, "finished": now, "version": 3}
    created = {**info, "name": "Ohne ODBC", "examples": {"parts": 19, "symbols": 15, "footprints": 13},
               "examples_error": None, "job": job, "warnings": []}
    sent: list[str] = []
    page.route("**/api/altium/status", no_driver)
    page.route("**/api/workspace/create", lambda route: (sent.append(route.request.post_data or ""),
                                                         fulfill_json(route, created)))
    page.route("**/api/jobs/polish-odbc-write**", lambda route: fulfill_json(route, job))
    goto(page, "/")
    palette(page, "Neue Bibliothek anlegen")
    page.keyboard.press("Enter")
    dlg = page.get_by_role("dialog", name="Neue Bibliothek anlegen")
    dlg.wait_for(timeout=10_000)
    dlg.get_by_label("Ordner").fill(str(WS / "OhneOdbc"))  # nie der Vorschlag unter „Dokumente“
    dlg.get_by_role("button", name="Bibliothek anlegen").click()
    done = page.get_by_role("dialog", name="Bibliothek „Ohne ODBC“ angelegt")
    done.wait_for(timeout=10_000)
    page.wait_for_timeout(800)
    shot(page, "odbc_created")
    check(len(sent) == 1 and "OhneOdbc" in sent[0], "Anlegen nicht abgefangen")
    text = done.inner_text()
    check("Altium braucht noch den ODBC-Treiber „SQLite3 ODBC Driver“" in text, f"kein ODBC-Hinweis: {text[:200]!r}")
    link = done.get_by_role("link", name=re.compile(r"SQLite-ODBC-Treiber herunterladen \(ch-werner\.de\)"))
    check(link.count() == 1 and link.get_attribute("href") == "http://www.ch-werner.de/sqliteodbc/", "kein Download-Verweis")
    check(link.get_attribute("target") == "_blank", "Download öffnet nicht im Browser")
    test = done.get_by_role("button", name="ODBC testen")
    check(test.count() == 1, "kein „ODBC testen“")
    test.click()
    page.wait_for_timeout(1500)
    check("/altium" in page.url, f"„ODBC testen“ führt nach {page.url}")
    return "Hinweis mit Download (ch-werner.de) und „ODBC testen“ → Altium-Seite"


CHECKS: dict[str, Callable] = {f.__name__: f for f in (
    e2ereg1_submenu, e2ereg2_uninstall, wording_not_installed, e2ereg3_parameters, stepper_1120, odbc_created,
)}


def main(argv: list[str] | None = None) -> int:
    global BASE, TOKEN, WS, SHOTS
    for stream in (sys.stdout, sys.stderr):  # Konsole/Pipe: Umlaute und Pfeile lesbar ausgeben
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "serve":
        sp = argparse.ArgumentParser(prog="polish_regressions.py serve")
        sp.add_argument("--port", type=int, default=8903)
        return serve(sp.parse_args(argv[1:]).port)
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
    wanted = [n for n in args.only.split(",") if n] or list(CHECKS)
    failed = 0
    for name in wanted:
        with browser() as page:
            try:
                note = CHECKS[name](page)
            except Skip as exc:
                print(f"SKIP {name}: {exc}")
            except Fail as exc:
                failed += 1
                print(f"FAIL {name}: {exc}")
            except Exception as exc:  # noqa: BLE001 - Prüfung abgebrochen
                failed += 1
                print(f"FAIL {name}: {exc.__class__.__name__}: {exc}")
            else:
                print(f"PASS {name}: {note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
