# PartForge – Architektur & Modulverträge

Verbindlich für alle Implementierungsarbeiten. Bei Details gilt der Code (Docstrings der genannten Module);
dieses Dokument beschreibt Aufbau, Verträge und Regeln. Recherche-Grundlagen (mit VERIFIED/UNVERIFIED-Kennzeichnung)
liegen in `docs/entwicklung/recherche/`:

| Bericht | Inhalt |
| --- | --- |
| `dblib-format.md` | DbLib-INI-Format, Codes, Connection Strings, SQLite-/PostgreSQL-Eigenheiten |
| `altium-live.md` | Live-Tests in Altium 26.10: SQLite-DbLib, DelphiScript zum Erzeugen/Speichern von SchLib/PcbLib |
| `altium-verify-2.md` | Altium-Prüfung der Rust-Bibliotheken, Unicode, Pfade, Sperrverhalten, Lagen-Header |
| `altium-verify-rust.md` | Dateiebene: Formatfehler des Rust-Writers und Workarounds |
| `altium-refresh.md` | Wie ein laufendes Altium Datenbankänderungen sieht (versteckte DbLib-Dokumente, Index-Refresh) |
| `rust-writer.md` | Rust-Writer `altium-designer-mcp.exe`: Protokoll, exakte JSON-Schemas, Fallstricke, Performance |
| `bridge-study.md` | altium-mcp-Brücke (MIT): Start-Kommando, Spec-Formate, Risiken |
| `user-lib-style.md` | Hausstil der TR_*-Bibliotheken (Lagen, Linien, Farben, Namen, Parameter) |
| `ipc-footprints.md` | IPC-7351B-Gleichungen, J-Tabellen, Gehäusemaße, Namensregeln, THT-, EP-, 3D-Regeln |
| `claude-api.md` | Claude-API: Modelle, PDF-Eingabe, Structured Outputs, Caching, Kosten, getesteter Code |
| `datasheet-corpus.md` | Testkorpus (11 PDFs) mit Sollwerten; liegt unter `tests/data/corpus/` |

Altium-Version auf diesem Rechner: **26.10.1** (Ordnername `C:\Program Files\Altium\AD22` ist irreführend).
Das Frontend (React, Designsystem „Forge“) beschreibt `FRONTEND.md`.

## 1. Leitprinzipien

1. **Einfach bedienbar, ohne DB-Vorteile zu verlieren**: Benutzer arbeiten mit Kategorien, Bauteilen, Symbolen,
   Footprints – SQL, DbLib-Interna und Dateiformate erledigt PartForge. Trotzdem bleibt alles eine echte
   relationale Datenbank (Abfragen, Massenänderungen, Historie, Backups, Mehrbenutzer über PostgreSQL).
2. **Altium-nativ**: Ergebnis ist eine Standard-DbLib + SchLib/PcbLib, die ohne PartForge in Altium funktioniert.
3. **Offline-first**: KI ist optional. Alles außer der Datenblatt-Analyse funktioniert ohne Internet.
4. **Sicher gegenüber der laufenden Altium-Sitzung**: niemals Benutzer-Dokumente anfassen, keine fremden Dialoge
   schließen, nur geprüfte Skriptvorlagen, Timeouts, klare Wiederherstellungshinweise.
5. **Korrektheit vor Bequemlichkeit**: Footprints nach IPC-7351B mit Testvektoren; jede Generierung prüfbar;
   eine Pinbelegung wird nie geraten.

## 2. Laufzeit

```text
pywebview (WebView2, js_api) ──HTTP──> FastAPI (127.0.0.1:48765, Sitzungstoken)
                                          │
   ┌───────────────┬─────────────┬────────┼──────────┬────────────────────┬──────────────┬──────────────┐
 db/ (SQLAlchemy  footprints/   symbols/  geometry/  altium/ (DbLib, ODBC,  datasheet/     domain/ (units,
 Core, SQLite/    IPC-7351B     Hausstil  Vertrag    Writer, Sync,          Claude-API     text, E-Reihen,
 PostgreSQL)                                         Refresh, Brücke)                      MPN/Serien)
                                                        │
                       altium-designer-mcp.exe (stdio, MCP)   X2.EXE -RScriptingSystem:RunScript (DelphiScript)
```

* `python -m partforge` (`__main__.py`): Desktop-Fenster (pywebview/WebView2) mit `js_api=DesktopApi`,
  stabiler Port **48765** (belegt → Zufallsport), damit Browser-Speicher (Theme, Layout) Neustarts übersteht;
  `--browser`, `--server-only`, `--dev` (Port 8765, Token `dev` für den Vite-Dev-Server), `--workspace <Ordner>`,
  `--verbose`. Der Server-Socket wird einmal gebunden und an uvicorn übergeben (`server.run(sockets=[…])`, unter
  Windows `SO_EXCLUSIVEADDRUSE`); ein belegtes `--port` endet mit deutscher Meldung und Exit-Code 2.
  **Eine Instanz je Einstellungsordner**: Mutex `Local\PartForge-<Hash von app_data_dir>`; ein zweiter Start holt
  das laufende Fenster nach vorn (sonst öffnet er dessen Adresse aus `<local data>\instance.json`) und endet,
  `--server-only`/`--dev` mit Meldung und Exit-Code 1. Log: `%LOCALAPPDATA%\PartForge\logs\partforge.log`
  (rotierend 5 × 2 MB); WebView-Speicher: `%LOCALAPPDATA%\PartForge\webview` (aus dem Roaming-Ordner älterer
  Versionen einmal verschoben). Beim Start wird die zuletzt geöffnete Bibliothek wieder geöffnet (Fehler, z. B.
  „in einem anderen PartForge geöffnet“, werden nur protokolliert).
* `partforge/desktop.py` – `DesktopApi` für `window.pywebview.api` (Frontend `src/lib/native.ts`):
  `pick_folder(initial)`, `pick_file(initial, filters)`, `open_path(path)`. `open_path` startet nie Programme:
  Ordner im Explorer, bekannte Dokumenttypen mit der zugeordneten Anwendung, alles andere nur markiert im Explorer.
* `partforge/app.py`: `create_app(token, *, allowed_hosts=None)`; eine Sicherheits-Middleware vor allen Routen
  (Reihenfolge: Host → fremde Website → Token; danach an **jede** Antwort das Rahmenverbot), Router-Module
  `partforge/api/routes_<name>.py` exportieren `router` (Liste `ROUTER_MODULES`); SPA-Auslieferung mit eingebettetem
  Token und Theme (`<meta name="partforge-token|partforge-theme">`) – nur für eigene Navigationen
  (`navigation_may_carry_token`). Die Sicherheit (§2.1) gilt für **jede** Anfrage, auch für `/` (die den Token trägt)
  und statische Dateien.
* `partforge/jobs.py`: Hintergrundjobs. `jobs.submit(kind, title, fn, *args)` ruft `fn(ctx, *args)` im
  Thread-Pool; `ctx.progress(f, msg)`, `ctx.log(text, level)`, `ctx.detail(**felder)` (strukturierter Fortschritt,
  in `job.detail` gemischt; `None` entfernt einen Schlüssel), `ctx.check_cancelled()`; `jobs.run_sync(…)` für
  Tests/CLI. SSE: `/api/jobs/events` (alle Jobs, nur Änderungen und neue Logzeilen) und `/api/jobs/{id}/events`.
  **Alles, was > ~1 s dauern kann, läuft als Job**; der Endpunkt gibt `{"job": snapshot}` zurück.
  `jobs.cancel(id, reason=…)` merkt den Grund (`Job.cancel_reason`, der erste gewinnt). Dazu die
  **Bibliothekssperre** `library_hold`/`library_switch` (§8.4). Snapshot, Schlussmeldung, Fehlertexte und die
  Kurzform für Joblisten: „Jobs“ unter API-Konventionen.
* `partforge/events.py`: kleiner In-Process-Ereignisbus ohne Importzyklen (`subscribe(event, handler)` →
  Abmeldefunktion, `emit`, `clear`). Handler laufen synchron im auslösenden Thread, Ausnahmen werden nur
  protokolliert. Ereignisse: `WORKSPACE_OPENED (ws)`, `WORKSPACE_CLOSED ()`, `SCHEMA_CHANGED ()`,
  `PARTS_CHANGED (table, inserted)`, `LIBRARIES_WRITTEN (paths)`.
* `partforge/config.py`: App-Einstellungen `%APPDATA%\PartForge\settings.json` (Tests: `PARTFORGE_HOME`).
  Ordner: `app_data_dir()` = `%APPDATA%\PartForge` (Roaming: `settings.json`, `secret\`), `local_data_dir()` =
  `%LOCALAPPDATA%\PartForge` (nur dieser PC: Caches, `webview\`, `logs\` = `log_dir()`, `tmp\`, `import\`,
  `instance.json`); mit `PARTFORGE_HOME` beide dieser Ordner. `load_settings()` liest `settings.json` neu, sobald
  sich die Datei geändert hat (Größe/Änderungszeit – z. B. von einem anderen Prozess geschrieben).
  **Keine Entwickler-Pfade als Standard**: `AISettings.api_key_file` ist `None`; der Rust-Writer kommt aus
  `rust_writer_path` – ein eingetragener, aber fehlender Pfad ergibt `None` (die Statusanzeige nennt ihn), nie
  stillschweigend einen anderen Writer – sonst aus `config.detect_rust_writer()`: `PARTFORGE_RUST_WRITER`,
  `%LOCALAPPDATA%\Programs\altium-designer-mcp\`, neben `PartForge.exe` (auch Unterordner `altium-designer-mcp`),
  nur aus dem Quellbaum zusätzlich `config.DEV_RUST_WRITER`. `default_library_parent()` = `<Dokumente>\PartForge`.
  `AppSettings`: `workspace`, `recent_workspaces`, `theme`, `author`, `ai` (`AISettings`: `enabled`,
  `api_key_file`, `model`, `effort`, `fast_model`, `use_fallbacks`, `max_cost_per_import_usd`) und `altium`
  (`AltiumSettings`: `x2_path`, `library_backend` = `auto|rust|altium`, `rust_writer_path`,
  `rust_writer_timeout_s`, `script_timeout_s`, `bridge_exchange_dir` (None = `%LOCALAPPDATA%\PartForge\bridge`),
  `auto_refresh` (Altium nach DB-Änderungen aktualisieren), `auto_reload_libraries` (geschriebene, in Altium
  offene und unveränderte SchLib/PcbLib neu laden)). Claude-Schlüssel: `store_api_key()` legt ihn
  **DPAPI-verschlüsselt** für den Windows-Benutzer ab; `read_api_key()` sucht `ANTHROPIC_API_KEY` → DPAPI-Ablage →
  Schlüsseldatei; `api_key_source()` meldet nur die Quelle. Der Schlüssel geht nie an das Frontend.
* `partforge/workspace.py`: Bibliotheksordner + `WorkspaceSettings` (§3). `workspace.current()` liefert den
  offenen Workspace (`WorkspaceNotOpen` → HTTP 409 über `api/deps.require_workspace`). **Bibliothekssperre über
  Prozesse**: solange eine Bibliothek offen ist, hält ihr Prozess eine exklusive Sperre auf `partforge.lock` im
  Ordner (`lock_library`/`unlock_library`, `msvcrt.locking` auf ein Byte weit hinter dem Inhalt; der Inhalt nennt
  Rechner, Benutzer, Prozess und Zeit, `library_lock_holder`). Ein zweites PartForge (Fenster, Benutzer, Rechner
  über eine Freigabe) wird beim Öffnen mit `LibraryLocked` abgewiesen (HTTP 409 „… bereits in einem anderen
  PartForge geöffnet (Rechner X, Benutzer Y, Prozess Z, seit …)“); das Betriebssystem gibt die Sperre beim
  Prozessende frei, auch nach einem Absturz. `Workspace.warnings` = deutsche Hinweise zur Bibliothek (z. B.
  Datenbankpfad, den die DbLib nicht tragen kann; gleichnamige DbLib) und `Workspace.pn_format_warning` (ein
  ungültiges `internal_pn_format` in einer von Hand geänderten `partforge.json`: es gilt dann der Standard) –
  beide in `info()["warnings"]`.

### 2.1 Sicherheit (lokaler Server im Browser)

PartForge ist ein lokaler HTTP-Server auf `127.0.0.1`, den ein Browser (WebView2 bzw. `--browser`) bedient. Host-,
Cross-Site- und Token-Prüfung laufen in der Middleware `security_guard` (`partforge/app.py`) **vor** jeder Route – API,
SSE, statische Dateien und die SPA-`index.html`, die den Token trägt; dieselbe Middleware hängt an **jede** Antwort das
Rahmenverbot, die SPA-Auslieferung (`render_index`) prüft zusätzlich, woher die Navigation kommt.

* **Host-Validierung (gegen DNS-Rebinding).** Jede Anfrage muss einen Loopback-`Host` tragen: `127.0.0.1`,
  `localhost` oder `[::1]` (beliebiger Port, Vergleich ohne Groß-/Kleinschreibung; ein abschließender Punkt
  `localhost.`, ein fehlender/leerer Host und alles andere werden abgelehnt). Ein fremder Host wird mit **HTTP 421**
  und kurzem deutschem Text beantwortet – **ohne** Token. Damit läuft ein DNS-Rebinding-Angriff ins Leere: Die
  Angreiferseite (deren Name auf 127.0.0.1 zeigt) ist für den Browser zwar same-origin und darf `/` lesen, aber ihre
  Anfragen tragen den Angreifer-`Host` und werden abgewiesen, bevor der Token je ausgeliefert wird. **Absolut-Form**
  eines Request-Ziels (`GET http://host/ HTTP/1.1`): dort zählt der Host im Ziel (RFC 9112 §3.2.2). Der echte Server
  (`__main__.server_config`) nutzt dafür `app.http_protocol()` – uvicorns httptools-Protokoll, das die Authority
  eines solchen Ziels in den `Host`-Kopf übernimmt (httptools allein behielte nur den Pfad); bei h11 prüft die
  Middleware den absoluten `raw_path` selbst. Die erlaubte Menge ist nur für Tests konfigurierbar
  (`create_app(allowed_hosts=…)` bzw. die von `tests/conftest.py` gesetzte Umgebungsvariable `PARTFORGE_TEST_HOSTS`;
  Starlettes `TestClient` sendet `Host: testserver`) – das ausgelieferte Programm übergibt `allowed_hosts=frozenset()`
  (`__main__.main`), liest die Variable also nie und akzeptiert **nur** Loopback.
* **Schutz vor fremden Websites (CSRF, Defense-in-depth).** Eine schreibende Anfrage (POST/PUT/PATCH/DELETE) mit
  einem `Origin` fremden Hosts (oder `Origin: null`) bzw. `Sec-Fetch-Site: cross-site` wird mit **HTTP 403**
  abgelehnt. Same-origin-Anfragen der SPA (Loopback-`Origin`) und Anfragen ohne `Origin` (Nicht-Browser-Clients)
  funktionieren weiter.
* **SPA mit Token nur für eigene Navigationen.** Eine fremde Website kann `http://127.0.0.1:<port>/…` per Link,
  `location.href`, Weiterleitung oder (unsichtbarem) iframe aufrufen – Host 127.0.0.1 ist gültig, die Seite liefe mit
  dem Token und könnte ohne Klick Aktionen auslösen. `render_index` bettet den Token deshalb nur ein, wenn
  `Sec-Fetch-Site` fehlt, `none` (Adresszeile, Lesezeichen, Programmfenster beim Start, `webbrowser.open` bei
  `--browser`) oder `same-origin` (Neuladen, Links der App) ist **und** `Sec-Fetch-Dest` fehlt oder `document` ist
  (`app.navigation_may_carry_token`; gemessen: WebView2 sendet beim Start `none`, beim Neuladen/Links `same-origin`).
  Sonst – `cross-site`, `same-site` (z. B. ein anderer lokaler Server auf einem anderen Port), `iframe`, `object`,
  `embed`, `fetch` – antwortet der Server mit **HTTP 403** und einer kurzen deutschen Seite („PartForge wurde von einer
  anderen Website aufgerufen“, Link „PartForge öffnen“ auf `/`) **ohne Token und ohne die Query**; der Klick auf den
  Link ist same-origin und öffnet die Übersicht. Ohne diese Kopfzeilen (Nicht-Browser-Clients, sehr alte Browser)
  gilt die Anfrage als eigene.
* **Kein Einbetten (Clickjacking).** Die Middleware setzt an **jede** Antwort – auch an 401/403/421 –
  `X-Frame-Options: DENY` und `Content-Security-Policy: frame-ancestors 'none'` (`app.deny_framing`; eine eigene CSP
  einer Route, z. B. die Sandbox-Policy der SVG-Vorschauen, wird um `frame-ancestors 'none'` ergänzt).
* **Keine Aktionen aus der Adresse (Frontend, Defense-in-depth).** Adressparameter dürfen nur anzeigen, vorbelegen
  oder fokussieren, nie schreibende Aktionen auslösen. Die Aktionen der Altium-Seite (DbLib neu erzeugen,
  Synchronisieren, Prüfen, In Altium installieren/aktualisieren, ODBC-Test, Vorschau) übergeben Shell-Befehle,
  Übersicht, Job-Toasts und Ergebnisansichten als **Router-State** (`navigate('/altium', { state:
  altiumActionState('sync') })`, `frontend/src/app/navigation.ts`), den nur PartForge selbst setzen kann; die Seite
  führt ihn einmal aus und löscht ihn (Neuladen/Zurück wiederholen nichts). Ein `?aktion=` in der Adresse (frühere
  Form – auch aus einem Link in einer Mail, der mit `Sec-Fetch-Site: none` ankäme) wird ignoriert und entfernt.
* **Sitzungstoken.** `/api` (außer `/api/health`) verlangt den prozessweiten Token im Header `X-PartForge-Token`
  oder als `?token=`. **Token im Query nur, wo der Browser keinen Header senden kann:** EventSource
  (`/api/jobs/events` in `api/system.ts`, `/api/jobs/{id}/events` in `api/jobs.ts`) und Seitenbilder der
  Datenblätter (`<img>`, `datasheets.datasheetPageUrl`). Das Frontend baut solche URLs ausschließlich über
  `client.apiUrl` (`frontend/src/api/client.ts`); `partsApi.exportUrl` baut die Export-Adresse nur zum Prüfen ihrer
  Länge, **ohne** Token (`apiUrl(…, false)`). Alle übrigen Aufrufe – auch Downloads (Export, DbLib) und das Öffnen
  der Datenblatt-PDF im Browser (`openPdf.ts`: im Programmfenster der PDF-Betrachter des Systems, im Browser Blob
  per Header laden und als Objekt-URL in einem neuen Tab öffnen) – gehen über den Header, damit der Token nie in
  Adresszeile, Verlauf oder Protokoll steht.
* **Token nie im Protokoll.** Ein Logging-Filter (`partforge/logsafe.RedactTokenFilter`, an die Log-Handler in
  `__main__._configure_logging` gehängt) ersetzt `token=…` in jeder geloggten URL durch `token=<redigiert>` – auch
  im uvicorn-Zugriffsprotokoll (`log_config=None` → Wurzel-Logger → `partforge.log` und Konsole), das bei
  `--verbose` die volle Request-URL schreibt, und in Tracebacks (`exc_text`) eines Protokolleintrags.
* **Ausführbare Pfade und Schlüsseldatei validiert (gegen Code-/Dateiabfluss).** `PUT /api/settings` prüft
  `altium.rust_writer_path` und `altium.x2_path` (absolut, lokales Laufwerk – kein verbundenes Netzlaufwerk –,
  **kein** UNC-/Gerätepfad in jeder Schreibweise – zwei führende Backslashes, `//host/share`, gemischt `\/host`,
  Langpfad-UNC `\\?\UNC\…`, `\\?\…`, `\\.\…` –, vorhandene reguläre `.exe`-Datei; `x2_path` muss `X2.EXE` heißen)
  sowie `ai.api_key_file` und `altium.bridge_exchange_dir` (absoluter Pfad auf einem lokalen Laufwerk; Altium führt
  das Skriptprojekt im Austauschverzeichnis aus, `AppSettings.resolved_bridge_exchange_dir` ignoriert einen von Hand
  eingetragenen UNC-Ordner und nimmt den Standardordner) – sonst deutsche **400**-Fehler
  (`routes_system._settings_security_problems`). Dieselben Prüfungen greifen zur Laufzeit
  (`config.executable_path_problem`): eine von Hand in `settings.json` eingetragene UNC-/ungültige Datei wird
  **ignoriert, nie ausgeführt** (`AppSettings.resolved_rust_writer`/`resolved_altium_exe` liefern dann `None` bzw.
  den automatisch gefundenen Pfad; `GET /api/altium/status` nennt den Grund im Backend-Status, z. B. „… wird nicht
  verwendet: … ist ein Netzwerk- oder Gerätepfad (UNC)“). Die Schlüsseldatei wird nur gelesen, wenn sie lokal liegt
  und höchstens 4 KB hat (begrenzt gelesen, `KEY_FILE_MAX_BYTES`), und nur verwendet, wenn ihr Inhalt genau ein
  Anthropic-Schlüssel ist (`sk-ant-` + Schlüsselzeichen, `config.looks_like_anthropic_key`, `config._file_key`);
  andere Dateiinhalte gehen nie an die API. `GET /api/settings` und `/api/ai/status` melden über
  `ai_key_file_problem`/`key_file_problem`, wenn eine konfigurierte Schlüsseldatei keinen gültigen Schlüssel liefert
  („… enthält keinen gültigen Claude-Schlüssel“). Die alte Standard-Schlüsseldatei (`config.LEGACY_KEY_FILE`) gilt
  unverändert: sie wird nur gelesen, wenn sie eingetragen ist, und nie in isolierten Läufen (`PARTFORGE_HOME`).
* **CSV/XLSX-Export (Formel-Injektion).** Jeder CSV-Export ist standardmäßig Excel-sicher (`excel_safe=True` in
  `spreadsheet.render_export`, `GET /api/export/{table}`, `POST /api/export/{table}` und dem Export-Job; das Frontend
  sendet `excel_safe=true`): ein Wert (auch ein Spaltenname), den Excel als Formel ausführen würde (`= + @`, Tab, CR,
  `-` außer reinen Messwerten wie `-55°C`), bekommt ein `'` vorangestellt. Der Tabellen-Import entfernt genau dieses
  eine `'` wieder (`spreadsheet._unguard`; ein Wert, der selbst mit `'=` … beginnt, bekommt beim Export ein weiteres),
  der Rundweg ist verlustfrei (`-40..+125`, `=see table`, `+85C`, `@1kHz`). XLSX schreibt solche Werte und alle
  Spaltennamen mit erzwungenem Zelltyp Text (`data_type = "s"`) – openpyxl machte aus `=…` sonst eine Formel.

### API-Konventionen

* JSON, Pydantic-Modelle für Request/Response (OpenAPI → TypeScript-Typen `frontend/src/api/schema.d.ts`),
  Präfix `/api`.
* Fehler: `HTTPException(status, detail="Deutscher Text mit Lösungshinweis")`. 404 nicht gefunden, 409 Konflikt /
  keine Bibliothek offen / Datenbank gesperrt, 422 Validierung (FastAPI), 400 fachlicher Fehler, 503 externer
  Dienst nicht verfügbar (Altium läuft nicht, Skript hängt, kein Writer, kein KI-Schlüssel).
  Strukturierte `detail`-Objekte (immer mit dem deutschen Text in `message`): Footprint-Generator 400
  `{message, params}` (betroffene Parameter), Symbol speichern 409 `{code: "pinout_changed", message, changes,
  usage}`, Bauteil-Validierung 400 `{message, errors}`, Massenaktion 409 `{code: "selection_changed", message,
  count, expected}`, Claude nicht verfügbar 503 `{code, message}` (alle Datenblatt-/KI-Endpunkte; `code` =
  `key_missing|key_rejected|model_unavailable|network|rate_limited|ai_disabled|unknown`; `POST /api/ai/test`
  meldet eine abgelehnte Anfrage als 400 `{code: "unknown", message}`).
* Lange Operationen: `POST …` → `{"job": JobSnapshot}`; das Ergebnis steht in `job.result`.
* **Jobs** (`partforge/jobs.py`, Endpunkte in `routes_system`):
  * Snapshot: `id`, `kind`, `title`, `status` (`queued|running|done|failed|cancelled`), `progress` (0…1),
    `message`, `log` (`[{ts, level, text}]`, in Listen leer), `result`, `error`, `error_type`, `detail`,
    `cancel_reason`, `cancel_requested`, `created`, `started`, `finished`, `version` (steigt bei jeder Änderung),
    `library` / `library_name` (Ordner und Name der Bibliothek, die beim Start des Jobs offen war, sonst `null` –
    Seiten mit eigener Fortschrittsanzeige ignorieren Jobs einer anderen Bibliothek, das Job-Dock nennt sie).
  * **Schlussmeldung**: Jeder Job endet mit einem deutschen Satz über sein Ergebnis in `message` und setzt ihn
    selbst (`ctx.progress(1.0, …)`), z. B. „Symbol „X“ gespeichert in Symbols\PF_Analog.SchLib“, „Import fertig:
    120 neu, 4 aktualisiert, 2 abgelehnt“, „Export fertig: 4 Bauteile in Exports\…“, „Bibliotheken geschrieben:
    15 Symbole und 13 Footprints“. Sicherheitsnetz in `JobManager._run`: endet ein Job `done`, während `message`
    leer oder noch ein Fortschrittstext ist (endet auf „…“ oder „...“, `jobs.is_progress_text`), wird daraus der
    Text `result.message` bzw. `result.summary` (falls vorhanden und selbst kein Fortschrittstext), sonst
    „Abgeschlossen“. `cancelled`: der Text der `JobCancelled`-Ausnahme, falls sie einen hat (nicht bei
    `LibraryChanged`), sonst „Abgebrochen – die Bibliothek wurde gewechselt oder geschlossen“
    (`cancel_reason = "library_switch"`) bzw. „Abgebrochen“. `failed`: `message` = `error`.
  * `error`: deutscher Text ohne Python-Klassennamen (`jobs.error_text`: PartForges eigene Ausnahmen sowie
    `ValueError`/`RuntimeError`/`OSError` mit Text unverändert, alles andere „Interner Fehler (KeyError): …“);
    `error_type` = Klassenname; das Log enthält den Text und den Traceback.
  * `cancel_reason`: `"library_switch"` = Bibliothek gewechselt oder geschlossen (ein Wechsel hat den Job
    abgebrochen, oder er endete mit `LibraryChanged`, weil seine Bibliothek nicht mehr offen war), `null` = vom
    Benutzer (`POST /api/jobs/{id}/cancel`) bzw. nicht abgebrochen. `cancel_requested`: Abbruch angefordert (der
    Job läuft bis zu seinem nächsten Prüfpunkt weiter).
  * `detail`: strukturierter Fortschritt für die Oberfläche (`ctx.detail(step="pins", cost_usd=0.12)`), auch
    nach dem Ende im Snapshot.
  * **Kurzform für Joblisten**: `GET /api/jobs?brief=true` und `GET /api/jobs/events?brief=true` ersetzen ein
    Ergebnis, dessen kompaktes JSON (UTF-8) größer als 8 KB (8192 Bytes) ist, durch `jobs.brief_result`: alle
    skalaren Felder der obersten Ebene (Zahlen, Wahrheitswerte und `null` unverändert, Texte bis 200 Zeichen
    unverändert, längere auf 200 Zeichen gekürzt, das letzte ist „…“); für jedes Listen-/Objektfeld seine Länge
    als `<name>_count` (ein gleichnamiges Feld des Ergebnisses hat Vorrang) – das Feld selbst entfällt, außer
    `errors`, `warnings` und `missing`, die ihre ersten 5 Einträge behalten (Objekt: die ersten 5 Paare);
    sonstige Werte entfallen; dazu `"result_truncated": true`. Ein großes Ergebnis, das kein Objekt ist, wird
    `{"result_count": n, "result_truncated": true}` (Liste) bzw. `{"result_truncated": true}`. Kleinere
    Ergebnisse und der übrige Snapshot bleiben unverändert, ohne den Parameter ändert sich nichts.
    `GET /api/jobs/{id}` und `/api/jobs/{id}/events` liefern immer das volle Ergebnis. Eine Kurzform trägt
    dieselbe `version` wie der volle Snapshot – sie darf einen vollen Snapshot desselben Jobs nicht ersetzen.
* Vorschaubilder registrierter Symbole/Footprints: `GET /api/libraries/{symbols|footprints}/{name}/thumbnail.svg`
  mit `ETag` (`"<content_hash>.<theme>"`) und `If-None-Match` → 304. Listen-, Detail- und Speicher-Einträge tragen
  `content_hash` (Hash über den gespeicherten Spec-Text, beim Symbol den Hausstil und `THUMBNAIL_VERSION`; `null` =
  keine Geometrie): `?v=<content_hash>` erlaubt dauerhaftes Zwischenspeichern (`immutable`), jeder andere `v` (z. B.
  das ältere `updated`) wird nur per ETag geprüft – zwei Speicherungen in derselben Sekunde liefern so nie ein altes
  Bild. Alle Vorschaubilder (Registry, Thumbnail-Endpunkt, externe Bibliotheken) zeichnet
  `sync.component_thumbnail` (Symbole über `symbols.render_thumbnail`).
* Pfade in Antworten: absolut **und** workspace-relativ, wo sinnvoll.
* Neue Bibliothek: `POST /api/workspace/create` (`path` absolut, `name`, `settings`, `with_examples`,
  `write_libraries`) → Workspace-Info + `examples` (Anzahl angelegter Bauteile/Symbole/Footprints),
  `examples_error`, `job` (Job „Bibliotheken schreiben“, §8.4) und `warnings` (z. B. eine gleichnamige DbLib:
  Altium findet Bauteile nur über den DbLib-Dateinamen). Vorab abgelehnt, ohne dass etwas entsteht:
  Ordner-/Dateinamen außerhalb des Bibliotheksordners (400, ebenso bei `PUT /api/workspace/settings`), ein
  ungültiges `internal_pn_format` (400, ebenso bei `PUT /api/workspace/settings`), eine vorhandene Bibliothek
  (409), SQLite auf einem Netzlaufwerk (400) und ein Datenbankpfad, den die DbLib nicht tragen kann
  (`dblib.sqlite_path_problem`: Zeichen außerhalb Windows-1252, `;`, `{ } "` – 400; beim Öffnen einer solchen
  älteren Bibliothek ein Eintrag in `warnings`). Lässt sich die neue Bibliothek nicht öffnen, entfernt PartForge
  die dabei angelegten Ordner und Dateien wieder; ein Fehler beim Anlegen der Beispiele lässt sie offen und nutzbar.
* Vorschlag für eine neue Bibliothek: `GET /api/workspace/defaults?name=` → `{parent, name, path, dblib_file,
  dblib_taken}`: `<Dokumente>\PartForge\<Name>` (ein Ordner, den es noch nicht gibt; „Name 2“ …), ein DbLib-Dateiname,
  der dem Namen folgt und mit keiner bekannten DbLib kollidiert (`Name-2.DbLib` …), und die bekannten DbLibs
  (`[{file_name, path, installed, library}]`: laut letzter Altium-Prüfung installiert bzw. der zuletzt benutzten
  Bibliotheken).
* Öffnen (`POST /api/workspace/open`) und Anlegen sperren die Bibliothek für diesen Prozess (`partforge.lock`,
  §2 `workspace.py`): in einem anderen PartForge offen → 409; Wechseln und Schließen geben die Sperre der vorigen
  Bibliothek frei.

## 3. Bibliotheksordner (Workspace)

```text
<Bibliothek>/
  partforge.json   PartForge.sqlite   <Name>.DbLib   partforge.lock (solange offen)
  Symbols/   Footprints/   3D/   Datasheets/   Backups/ (+ Backups/lib/)   Exports/
```

* `WorkspaceSettings`: `name`, `db` (`kind` sqlite|postgres, `sqlite_file`, `postgres_url`, `postgres_odbc`,
  `journal_mode` – wird ignoriert, SQLite läuft immer im WAL-Modus), `folders`, `dblib_file`, `library_layout`
  (`grouped`|`per_item`), `part_number_scheme` (`mpn`|`internal`), `internal_pn_format` (Python-Format mit
  `{prefix}`, `{table}` und **genau einem** `{counter}`; jede erzeugte Nummer muss eine gültige Teilenummer sein –
  `workspace.pn_format_problem`, geprüft beim Speichern und Öffnen), `layers` (`LayerMap`),
  `layer_stackup`, `layer_set` (`LayerSetSettings`), `footprint` (`FootprintStyle`), `symbol` (`SymbolStyle`).
* In der DB gespeicherte Pfade (`Library Path`, `Footprint Path`, Registry) sind **relativ zum DbLib-Ordner**
  (= Workspace-Wurzel) mit Backslash, z. B. `Symbols\PF_Passives.SchLib` (`Workspace.rel()`/`abs()`; Altium löst
  relativ zum DbLib-Ordner auf – VERIFIED).
* Der Ordner ist in sich geschlossen: `folders.*` und `db.sqlite_file` liegen darin, `dblib_file` ist ein reiner
  `*.DbLib`-Dateiname in der Wurzel. Absolute Pfade, Laufwerke, `..` und reservierte Windows-Namen lehnt die API
  ab (`routes_system.settings_path_problems`).
* Der ODBC-Datenbankpfad in der DbLib ist **absolut** (ein relativer Pfad hängt vom Arbeitsverzeichnis
  Altiums ab); PartForge schreibt die DbLib neu, wenn sich der Ordner verschoben hat.
* **Lagen:** `LayerMap` bildet die logischen Footprint-Lagen auf den Standard-Lagenstapel des Benutzers ab
  (`Mechanical_Stackup_Standard\mechanical_layer.stackup`): Bestückung Mech 9, Designator Mech 11, 3D-Körper
  Mech 13, Courtyard Mech 15, Bauteilmitte Mech 17, Wert/Comment Mech 19, Bauteilumriss Mech 21, Bestückungsdruck
  `Top Overlay`. Mech 2–7 bleiben frei (der Rust-Writer deklariert sie typisiert). `layer_stackup` = optionale
  `.stackup`-Datei, deren mechanische Lagennamen/-typen in den Header jeder geschriebenen PcbLib übernommen
  werden (`altium/stackup.py`); `None` = eingebauter Standard passend zu `LayerMap`.
* **Lagensatz** (`layer_set`, `altium/layersets.py`): eigener Altium-Lagensatz („View Configuration › Layer Sets“),
  den der Writer in den Kopf jeder PcbLib schreibt (§8.3). `mode`: `none` (Standard – nur Altiums eingebaute Sätze),
  `builtin` (aus der `LayerMap`: Kupfer, Paste, Lötstopp, Bestückungsdruck, Bohrlagen, Multi-Layer und jede
  Mechanik-Lage der Zuordnung; Name „Component Layers“ oder `name`) oder `file` (Name, Lagenkürzel wie
  `TopOverlay`/`Mechanical9`, aktive Lage und Optionen aus einer Altium-`.layerset`-Datei – die Definition steht in
  den Einstellungen, `file` ist nur die Herkunft, der Ordner bleibt in sich geschlossen). `current`: beim Öffnen in
  Altium aktiv (die anderen Sätze verlieren dann `ISCURRENT`). Für die Standard-`LayerMap` ist `builtin` lagengleich
  mit dem `Component.layerset` des Benutzers (VERIFIED). Eine unbrauchbare Definition schreibt keinen Satz und
  erscheint als Hinweis (`layersets.workspace_layer_set`). API: `POST /api/libraries/layer-set/parse {path}` →
  `{file, sets}`, `POST /api/libraries/layer-set/builtin {layers?, current}` → `LayerSetDef` (Vorschau).
* `FootprintStyle`: Dichte M/N/L, Namensschema `ipc`|`house`, Rundung `kicad`|`ipc`, Fertigungs-/Platzier-
  toleranz, Linienbreiten, Pin-1-Punkt, Courtyard-Raster, Mindestabstand Kupfer, Zentrumskreuz (zusätzliches
  Kreuz im Courtyard), Texthöhe, Textschrift `text_font` (`stroke` Standard | `truetype`) mit `text_font_name`
  (Standard Arial) für `.Designator`/`.Comment`, Eckenradius, Bezeichner des Exposed Pads (`next`|`EP`), 3D an/aus.
  `SymbolStyle`: Raster, Pinlängen, Farben, Linienbreite, Hausschrift `font`/`font_size` (Bezeichner, Comment,
  Parameter, freie Texte – in die Schrifttabelle der SchLib eingetragen, `altium/schstyle.py`), `pin_font`
  (`house` Standard: Pinnamen/-nummern in der Hausschrift als Altium-„Custom Font“ jedes Pins | `system`: Schrift
  des Schaltplanblatts), `diode_pin1` (`cathode` = IPC, Standard | `anode`), `resistor_style` (`iec`|`ansi`).
* Bibliotheksdateien (`altium/libwriter.py`): Layout `grouped` (Standard) – Symbole je Kategorie-Gruppe
  `Symbols/PF_<Gruppe>.SchLib` (Passives, Diodes, Transistors, Analog, Power, ICs, Connectors,
  Electromechanical, Protection, Oscillators, Mechanical; ohne Kategorie nach Bezeichner-Präfix), Footprints je
  Generatorfamilie `Footprints/PF_<FAMILIE>.PcbLib` (`PF_CHIP`, `PF_SOD`, `PF_SOT23`, `PF_GULLWING`, …);
  Layout `per_item`: eine Datei pro Symbol/Footprint. Dateien klein halten: jede Änderung schreibt die ganze Datei –
  im Layout `grouped` nimmt eine Datei ab `sync.MAX_LIBRARY_COMPONENTS` = 60 registrierten Bauteilen oder
  `MAX_LIBRARY_BYTES` = 2 MB keine **neuen** mehr auf, sie kommen nach `PF_<Gruppe>_2`, `_3` … (erste nicht volle;
  `sync._target_library`; die Anzahl gilt auch innerhalb eines Aufrufs mit vielen neuen Bauteilen); registrierte
  Namen bleiben in ihrer Datei.
* Namen von Symbolen/Footprints: **nur ASCII** `[A-Za-z0-9_.\-+() ]`, ≤ 64 Zeichen, ohne Leerzeichen am Rand
  (`domain.text.ascii_name`, geprüft von `symbols.check_spec`, `footprints.validate_footprint` und den Writern).

## 4. Datenbank (`partforge/db`)

* **Kern** (`core.py`): SQLAlchemy 2 **Core** (Tabellen sind dynamisch), eine Engine pro Workspace (SQLite-Datei
  oder PostgreSQL über `postgres_url`). SQLite **immer im WAL-Modus**, gesetzt beim Anlegen der Datei bzw.
  umgestellt, solange kein anderes Programm sie offen hat (VERIFIED: im DELETE-Modus blockiert Altiums Verbindung
  jeden Schreibzugriff für die ganze Altium-Sitzung). SQLite auf Netzlaufwerken wird abgelehnt (WAL braucht
  Shared Memory) → Teams nutzen PostgreSQL. `busy_timeout=5000`, `foreign_keys=ON`, `synchronous=NORMAL`,
  Schreibtransaktionen mit `BEGIN IMMEDIATE`, serialisiert über einen prozessweiten, reentranten Lock
  (`connect()`); `read()` = Lese-Snapshot. „database is locked“ → `DatabaseBusy` (deutsch, HTTP 409).
  SQL-Funktionen `pf_num()`/`pf_fold()` nur für PartForge-Abfragen – nichts Altium-Sichtbares hängt davon ab.
* **Öffnen** (`lifecycle.open_database`): baut und prüft die neue Engine (WAL, Schema-Migration, Abgleich,
  Datenmigrationen), bevor sie die offene ersetzt – schlägt das Öffnen fehl, bleibt die bisherige Bibliothek offen.
  Datenmigrationen laufen bei **jedem** Öffnungsweg in derselben Transaktion, jede in einem Savepoint (schlägt eine
  fehl, wird sie protokolliert und beim nächsten Öffnen wiederholt – die Bibliothek öffnet trotzdem):
  Standardsymbole (`templates.migrate_default_symbols`); Kategorie-Bezeichnungen älterer Versionen mit „&“ →
  „und“ bzw. auf die vollständige Bezeichnung („Optokoppler und Opto“ → „Optokoppler und Optoelektronik“;
  `templates.migrate_category_labels`, `LEGACY_CATEGORY_LABELS`: nur wenn die Bezeichnung noch genau einer
  alten eingebauten entspricht und der Benutzer sie nie selbst geändert hat, Audit `migrate_category_label`);
  Schaltplan-Texte (einmal je Bibliothek, Marker
  `pf_meta.migration_schematic_texts`: Comment sichtbar, die früher sichtbaren Wertfelder
  `templates.LEGACY_VISIBLE_FIELDS` ausgeblendet, alte Kommentarvorlagen `LEGACY_COMMENT_TEMPLATES` ersetzt und
  generierte Comments der Bauteile neu erzeugt – vom Benutzer geänderte Felder/Vorlagen, auch laut `pf_audit`,
  bleiben); **verschobener Bibliotheksordner** (nur SQLite): `pf_meta.workspace_root` merkt sich den Ordner; wird
  die Bibliothek aus einem anderen Ordner geöffnet, zeigen absolute Verweise in den alten Ordner
  (`ComponentLink<n>URL` und alle url/path-Felder; Groß-/Kleinschreibung und Schrägstrich egal, `file:`-Präfix
  bleibt) danach in den neuen, path-Felder relativ; ein Audit-Eintrag je Bauteil (Autor „PartForge“) und eine
  Logzeile. Ohne gespeicherten Ordner (Bibliothek einer älteren Version) wird der frühere Ordner aus den
  Datenblatt-Verweisen erkannt (`<Ordner>\<pf_datasheets.file>`), wenn er eindeutig ist. PostgreSQL-Datenbanken
  teilen sich mehrere Bibliotheksordner und werden nie umgeschrieben. Danach:
  `categories.notify_schema_change()` bei geänderten Feldern/Vorlagen (DbLib wird neu geschrieben) und
  `events.PARTS_CHANGED` bei geänderten Bauteilen.
* **Kategorietabellen** (Altium-sichtbar): eine Tabelle je Kategorie, Name = Altium-Bibliotheksname
  (z. B. `Resistors`), Spalten = Felder aus `db/templates.py` (`COMMON_FIELDS` + Kategoriefelder).
  * Spaltentyp **TEXT** für alles (VERIFIED: Altium schneidet `VARCHAR(n)` auf n Zeichen ab; REAL/NUMERIC
    erscheinen mit Dezimalkomma). Werte sind vorformatierter Text; Längen nur weiche Warnungen (`FieldDef.length`).
  * `Part Number` ist Primärschlüssel und **über alle Kategorietabellen eindeutig**, verglichen mit
    `parts.pn_key` (= `domain.text.identity_key`: NFKC, ohne unsichtbare Formatzeichen der Unicode-Kategorie Cf –
    weiches Trennzeichen, Leerzeichen ohne Breite, BOM, Richtungszeichen –, Groß-/Kleinschreibung für ganz Unicode:
    „GRM188\u00adR71“ = „grm188r71“, „UNIQ-STRASSE“ = „uniq-straße“, NFD = NFC). Teilenummer und
    Hersteller-Teilenummer (`values.IDENTITY_COLUMNS`) werden in NFC ohne diese Zeichen gespeichert
    (`identity_text`; entfernte Zeichen → Warnung); `mpn_key` ignoriert sie ebenso. Dieselben Schlüssel gelten beim
    Anlegen, Umbenennen, Import und in der Prüfung (`duplicate_pn`, `duplicate_mpn`).
  * Schema-Versionen (`pf_meta.schema_version`): 1 = Ursprung (VARCHAR), **2 = alle Spalten TEXT** (Migration
    `convert_to_text`). Beim Öffnen gleicht `schema.reconcile` Metadaten und Tabellen ab: fehlende Tabellen/Spalten
    werden angelegt, fremde Spalten (z. B. `Supplier 2` aus Altiums *Edit Supplier Links*) als Felder übernommen,
    unregistrierte Tabellen mit `Part Number` als Kategorie adoptiert; Schemaänderungen anderer Prozesse werden über
    SQLite `schema_version` erkannt. Fremde Tabellen/Spalten, deren Namen die DbLib nicht tragen kann (`| [ ] "`,
    Steuerzeichen, Leerzeichen am Rand, Zeichen außerhalb Windows-1252), werden nie übernommen (Warnung im Log,
    `schema.unsafe_name_reason`).
* **Metadaten-Tabellen** (Präfix `pf_`, in der DbLib deaktiviert): `pf_meta`, `pf_categories`, `pf_fields`,
  `pf_symbols`, `pf_footprints`, `pf_datasheets`, `pf_audit` (Änderungshistorie), `pf_mpn_templates` (eigene
  Serienvorlagen), `pf_saved_views` (gespeicherte Ansichten). `pf_meta` lesen/schreiben andere Module nur über
  `db.meta` (`get_meta`, `set_meta`, `delete_meta`, `meta_items`), nicht über `schema`-Interna.
* **Werte** (`values.py`): Felder haben `kind` (text, quantity, enum, bool, int, url, path, date, range) und
  `unit`. `normalize_cell` parst, validiert und formatiert; gespeichert wird der kanonische Text, Probleme sind
  deutsche Warnungen (nur `Part Number` mit `' { } |` oder Steuerzeichen ist ein Fehler). **Kommas**: ein
  Dezimalkomma („2,2µF“, „0,100“) wird gelesen; eine einzelne Dreiergruppe („1,000µF“, „10,000pF“, „32,768 Hz“) ist
  mehrdeutig (englisch 1000 µF, deutsch 1,0 µF) – `normalize_cell(…, thousands=None)` (Handeingabe, unbekannte
  Quelle) speichert sie unverändert mit der Warnung „… ist mehrdeutig: Komma als Tausendertrennzeichen (1mF) oder
  als Dezimalkomma (1µF)?“ und `unreadable` (der strikte Import lehnt ab), `thousands=True` (englische Quelle, z. B.
  Datenblatt) liest Tausender und vermerkt es in `CellResult.note` (+ Log), `thousands=False` liest ein Dezimalkomma;
  mehrere Gruppen („1,000,000“) oder ein Dezimalpunkt dahinter („1,000.5“) sind immer Tausender. Formatierung und
  Parsing laufen **ausschließlich über `domain/units.py`** (§4.1) – Handeingabe, Serien, Import und Datenblatt
  ergeben denselben Text. Feldregeln obendrauf: die Feldeinheit gilt, relative Toleranzen (`%`, `ppm`) mit `±`,
  `ppm`/`ppm/K` werden gegenseitig akzeptiert, unbekannte Einheiten als Suffix („5lm“). Gespeicherter Text ändert
  sich beim erneuten Normalisieren nie (Formular, Import, Massenänderung). Ob eine Eingabe zu einem Feld passt,
  entscheidet `values.units_compatible` – nicht die Gleichheit von `canonical_unit` (`ppm` ≠ `ppm/K`).
  **Asymmetrische Bänder** relativer Felder (`%`, `ppm`, `ppm/K`, `values.RELATIVE_UNITS`) sind Werte:
  „-100~+350ppm/℃“, „+350/-100 ppm/K“, „-20 % … +80 %“ werden zu „-100 … +350ppm/K“ bzw. „-20 … +80%“ (beide
  Grenzen mit Vorzeichen, Einheit einmal; symmetrisch → „±100ppm/K“; `parse_field_band`, `format_band`);
  `numeric_value` eines Bands ist der Betrag des schlechtesten Falls (350 – Filter/Sortierung).
  **0-Ω-Brücken**: `values.is_jumper(value_field, row)` (Wertfeld in Ω, Wert genau 0) und
  `values.not_applicable(cat, row) -> frozenset[Spalte]`: für eine Brücke gelten die Mengenfelder in `%`, `ppm`,
  `ppm/K`, `W`, `V` (`JUMPER_EXEMPT_UNITS`: Toleranz, TK, Leistung, Spannung) nicht – die Datenblätter bewerten eine
  Brücke mit Maximalwiderstand und Nennstrom (Vishay „Jumper, Imax“, Panasonic „For Jumper: Rated current“,
  UNI-ROYAL „Rated Current of Jumper“, YAGEO/Bourns „Rated Current“). Pflichtfeld-Prüfungen (Prüfen, Serien) lassen
  diese Spalten aus – auch `db.parts` beim Speichern von Hand, Import und Serie (`_prepare`; eine Änderung, die die
  Ausnahme beendet – Brücke wird Widerstand –, prüft die Felder wieder).
* **Texte**: `Value`/`Comment`/`Description` entstehen aus Kategorievorlagen, solange sie leer sind bzw. noch dem
  generierten Text entsprechen (`"RES {Size} {Resistance} {Tolerance} {Power} {Technology}"`; Formatangaben
  `si`, `rkm` (`4k7`, `100n`, `6V3`), `nounit`, `upper`, `lower`; leere Platzhalter-Token entfallen).
  Hauskonvention: **Comment = Wert** (`4k7`, `100n 50V`, `10u`, `180R@100MHz`, `Rot`, `32.768kHz`, `1A`) bzw. MPN
  bei Halbleitern/ICs; Value = Wert. **Nur `Comment` ist im Schaltplan sichtbar** (`show_on_schematic` =
  DbLib `VisibleOnAdd`, VERIFIED `altium-e2e.md` §3.4) – die Wertfelder sind ausgeblendet, die Kommentarvorlage
  trägt den wesentlichen Wert (Kondensatoren mit Spannung: `"{Capacitance:rkm} {Voltage}"`).
* **Standardsymbol einer Kategorie**: `CategoryDef.default_symbol` ist ein **Symboltyp-Schlüssel** von
  `partforge.symbols` (`resistor`, `diode`, `opamp_dual`, `crystal_2`, `connector` …), nie ein Symbolname – Namen
  hängen vom Hausstil ab („Diode (AK)“ in Workspaces mit Anode an Pin 1). `templates.resolve_default_symbol(
  category, values=None, style=None, *, footprint=None)` erzeugt das Symbol zur Laufzeit: ohne Werte (oder bei
  eigenen Kategorien) aus dem Standardtyp, mit Werten nur über `symbols.standard_symbol_for` (Pinbelegung sicher),
  sonst `None` – der Standardtyp rät nie eine Pinbelegung. `templates.migrate_default_symbols(conn)` wandelt
  Symbolnamen älterer Versionen („Resistor“, „Op-Amp“) idempotent in Typschlüssel um – bei jedem Öffnungsweg
  (`lifecycle.open_database`); `templates.ensure_default_symbol_kinds()` prüft das auf der offenen Datenbank
  lesend und schreibt nur bei Bedarf (`routes_system`, `seed_examples`); `default_symbol_kind` versteht die alten
  Namen ohnehin.
* **Aktualisierung in Altium**: Nach Schreibvorgängen sorgt `altium/refresh.py` (§8.2) dafür, dass ein laufendes
  Altium die Änderungen sieht. Platzierte Bauteile referenzieren die DbLib **nur über den Dateinamen** → den beim
  Anlegen gewählten DbLib-Dateinamen (`dblib_file`, standardmäßig `<Name>.DbLib`) stabil halten, nur eine installierte
  DbLib mit diesem Namen. ODBC-Option `LongNames=1` bricht alle Lookups – nie verwenden.

### 4.1 Einheiten (`partforge/domain/units.py`) – der eine Formatierungspfad

```python
parse_quantity(text, default_unit=None, *, thousands=None) -> Quantity | None   # "4k7", "2,2µF", "1/16W", "6V3"
resolve_commas(text, thousands=None) -> str | None   # Kommas aufgelöst; None = mehrdeutige Dreiergruppe ("1,000µF")
ambiguous_thousands(text) -> bool
format_quantity(value, unit="", *, digits=6, space=False, prefixes=True, plus_minus=False) -> str
format_rkm(value, unit="Ω", *, upper=True, digits=3, ohm_letter="R") -> str      # 4K7/4k7, R47, 100n, 6V3
format_power(watts, *, style="decimal"|"fraction") -> str                         # 0.25W, 62.5mW, 1/16W
exact_digits(value) -> int; significant_digits(value, digits); normalize_unit(unit); parse_range(text)
```

Regeln: SI-Vorsätze f…T; nie Vorsätze für `NO_PREFIX_UNITS` (%, ppm, ppm/K, °C, °, dB, mm, nm, mil, K, in);
Leistung ab 0,1 W ohne Vorsatz („0.25W“), darunter „62.5mW“; `ppm` (Verhältnis, z. B. Frequenztoleranz) und
`ppm/K` (Temperaturkoeffizient) sind verschiedene Einheiten; `digits=None` = exakt (3…9 Stellen) – so speichert
`db.values` („14.31818MHz“ bleibt exakt); nicht-endliche Zahlen („1e999“) sind keine Werte. Beim Parsen ist ein
Suffix gleich der Feldeinheit nie ein Vorsatz („6500K“ und „6500k“ im Kelvin-Feld = 6500 K, Kilokelvin nur als
„6.5kK“; „10K“ im Ohm-Feld = 10 kΩ).
`format_rkm` schreibt Einheiten ohne Vorsatz mit Dezimalpunkt („0.5%“, „12.5°C“, „1.5Hz“) – lesbar wie jede Eingabe.
Kommas: Dezimalkomma ja; eine einzelne Dreiergruppe nach einer Ziffer ≠ 0 ist mehrdeutig – `thousands=None`
(Standard) liefert `None` statt zu raten, `True` liest Tausender (englische Quelle), `False` ein Dezimalkomma.
`domain/text.py`: `clean_free_text` (kein `|`, keine Steuerzeichen), `ascii_name`, `latin1_text` (§8.3),
`FORMAT_CHARS` (alle Cf-Zeichen, als Escapes im Quelltext), `strip_format_chars`, `identity_text` (NFC, ohne
Formatzeichen), `identity_key` (NFKC, ohne Formatzeichen, casefold).

### 4.2 Vertrag (Python)

```python
# partforge/db/__init__.py
open_database(ws) -> None; close_database() -> None; seed_examples(ws) -> dict    # {"parts", "symbols", "footprints"}
get_engine() -> Engine; connect() -> ContextManager[Connection]   # Schreibtransaktion
read() -> ContextManager[Connection]; is_open() -> bool; current_workspace() -> Workspace
# partforge/db/categories.py
list_categories(*, with_counts=True) -> list[CategoryDef]; get_category(table) -> CategoryDef   # CategoryNotFound
create_category(CategoryDef) / update_category(table, patch) / delete_category(table, *, backup=True)
add_field(table, FieldDef) / update_field(table, column, patch) / remove_field(table, column)
reorder_fields(table, columns)
builtin_templates() -> list[CategoryDef]; on_schema_change(callback) -> unsubscribe; invalidate_cache()
# partforge/db/parts.py
query_parts(table, *, search=None, filters=None, sort=None, offset=0, limit=200) -> tuple[list[dict], int]
get_part(table, pn) -> dict | None; find_part(pn) -> tuple[str, dict] | None; existing_part_numbers(pns) -> set[str]
find_by_mpn(mpns) -> dict[mpn_key, list[(table, part_number, row)]]   # alle Kategorien, ein Scan je Kategorie
mpn_key(mpn) -> str                                   # NFKC, ohne Leerzeichen/Bindestriche, casefold („-7-F“ = „7F“)
create_part(table, values, *, author=None) -> dict; update_part(table, pn, values, *, author=None) -> dict
delete_parts(table, pns, *, author=None, deleted=None) -> int
bulk_update(table, pns, values, *, author=None, backup=True, backups=None, audit_ids=None) -> int
regenerate_texts(table, pns=None, *, columns, author=None, backup=True, backups=None, audit_ids=None) -> int
    # > 20 Bauteile: automatische Sicherung („vor_massenaenderung_<n>_bauteile“, Name in backups); audit_ids
    # erhält die Einträge der Änderungshistorie – Eingabe von restore_updates
restore_parts(table, pns, *, author=None) -> dict        # Rückgängig: aus dem letzten „delete“ in pf_audit
restore_updates(table, audit_ids, *, author=None) -> dict   # Rückgängig einer Massen-/Textänderung: alte Werte
    # zurück, je Bauteil ganz oder gar nicht (seither erneut geändert → conflicts); {restored, parts, conflicts,
    # unchanged, not_found, warnings}; Audit „restore“; fremde Kategorie/Aktion → ValueError
matching_part_numbers(table, *, search=None, filters=None) -> list[str]   # Auswahl für Massenaktionen
upsert_parts(table, rows, *, mode="skip"|"update"|"error", author=None, ctx=None, strict=False, thousands=None,
             before_write=None) -> UpsertResult   # before_write: nach der Prüfung, nur wenn geschrieben wird
plan_upsert(table, rows, *, mode, allow_incomplete=False, strict=False, thousands=None) -> list[RowPlan]
duplicate_part(table, pn, new_pn) -> dict; history(table, pn) -> list[dict]; validate_part(table, values, *, pn=None)
search_all(q, limit=20); stats(); render_templates(table, values); regenerate_texts(…); smart_fill(table, text)
render_template_text(table, template, values) -> {text, fields, unknown}   # beliebige Vorlage
distinct_values(table, column); set_library_path(kind, name, library) -> int
search_columns(cat) -> list[str]   # Suchfeld: alle Spalten außer Library/Footprint Path, URLs, Datumsfeldern, PF Author
    # Suche: Token UND-verknüpft; Text in den Suchspalten (casefold) oder Zahl: ohne Einheit ("10k", "4k7") nur das
    # Wertfeld der Kategorie, mit Einheit ("50V", "100nF", "1%") die Felder dieser Einheit. SQLite: Index im
    # Speicher je Kategorie (gefalteter Text + Zahlenwerte; neu gebaut nach jeder Änderung – core.data_version,
    # Datenbankdatei und WAL), Filter/Sortierung in SQL über pf_hit(id, Teilenummer); Seite und Gesamtzahl in einer
    # Abfrage (count(*) OVER ()). PostgreSQL: Python-Fallback mit denselben Regeln
    # smart_fill: Feld mit genau der Einheit zuerst, dann units_compatible („±100ppm“ → TCR in ppm/K)
    # Filter auf Datumsfeldern (PF Created/PF Modified, kind „date“): before/after/between und eq/lt/… je Tag;
    # between auch für quantity/int; strict: nicht lesbare Werte (CellResult.unreadable) sind Fehler
# partforge/db/meta.py   (pf_meta; conn=… nutzt die Transaktion des Aufrufers)
get_meta(key, default=None, *, conn=None) -> str | None; set_meta(key, value | None, *, conn=None)
delete_meta(key, *, conn=None) -> bool; meta_items(prefix="") -> dict; WORKSPACE_ROOT   # schema_version … gesperrt
# partforge/db/lifecycle.py
migrate_data(conn, ws, *, kind) -> OpenReport; relocate_link(value, old_root, new_root) -> str | None
# partforge/db/registry.py   (Symbole/Footprints/Datenblätter, die PartForge kennt)
list_symbols(*, status=None, source=None, with_spec=True, with_usage=True, names=None, library=None)
get_symbol(name, *, with_usage=True) / upsert_symbol(rec) / upsert_symbols(recs)   # Batch liefert nur seine Records
content_hashes(kind, names=None) -> {name.casefold(): sha256 des Spec-Texts | None}   # liest, parst keine Specs
delete_symbol(name) / set_symbol_status(name, status, message) / symbol_usage() / symbol_library_map()
list_footprints(…, family=None, with_spec, with_usage, names, library) / get_footprint(name, *, with_usage=True)
upsert_footprint(rec) / upsert_footprints(recs) / delete_footprint(name)
set_footprint_status(…) / footprint_usage() / footprint_library_map(); counts()
list_datasheets() / get_datasheet(id) / upsert_datasheet(rec) / delete_datasheet(id)
# partforge/db/backup.py, health.py, views.py, mpn_templates.py, audit.py
backup_database(reason) -> Path; list_backups(); restore_backup(name); auto_backup(…)   # neueste 30 bleiben
health_report(*, max_per_check=200) -> dict; check_database() -> list[dict]; health.clear_cache()
# partforge/db/core.py
data_version() -> int   # ändert sich nach jeder Schreibtransaktion dieses Prozesses und beim Öffnen/Schließen
# partforge/db/values.py
normalize_cell(field, raw, *, ws_root=None, thousands=None) -> CellResult; numeric_value(text, unit) -> float | None
    # CellResult: value, warning, error, unreadable, note (z. B. „mit Komma als Tausendertrennzeichen gelesen“)
parse_field_band(text, unit) -> (lo, hi) | None; format_band(lo, hi, unit) -> str   # "-100 … +350ppm/K"
is_jumper(value_field, row) -> bool; not_applicable(cat, row) -> frozenset[str]      # 0-Ω-Brücke
list_views() / create_view() / update_view() / delete_view(); list_mpn_templates() / save_mpn_template() …
# partforge/db/templates.py, examples.py
CATEGORIES; COMMON_FIELDS; resolve_default_symbol(…); default_symbol_kind(value, table=None)
migrate_default_symbols(conn) -> list[str]                            # idempotente Datenmigration
migrate_category_labels(conn, *, author="PartForge") -> list[str]     # „&“-Bezeichnungen → „und“ (idempotent)
ensure_default_symbol_kinds() -> list[str]                            # dieselbe, nur wenn nötig (offene DB)
build_examples(ws, *, tables=None) -> ExampleContent                  # rein, ohne Datenbank
```

* `SymbolRecord`: `name`, `library` (rel. Pfad), `source` (`generated|datasheet|imported|external`), `spec`
  (`SymbolSpec|None`), `pin_count`, `part_count`, `kind`, `status` (`ok|pending|missing|error`), `status_message`,
  `updated`, `usage`, `content_hash` (sha256 des gespeicherten Spec-Texts; gesetzt, wenn der Record mit Spec
  gelesen wurde – leichte Listen ohne Spec: `None`, dafür `registry.content_hashes`). `get_symbol`/`get_footprint`
  ergänzen bei Specs älterer Versionen den Namensvermerk (`with_name_record`, nur beim Lesen).
  `FootprintRecord`: analog + `family`, `ipc_name`, `pad_count`, `height`, `step_file`.
  `DatasheetRecord`: `id` (sha256[:16]), `file`, `original_name`, `title`, `manufacturer`, `mpns`, `page_count`,
  `text_pages`, `extraction`, `created`.
* **Sicherungen** (`backup.py`): SQLite-Online-Backup nach `Backups/PartForge_<Zeit>_<Grund>.sqlite`, automatisch
  vor destruktiven Aktionen (Kategorie/Feld löschen, > 20 Bauteile löschen oder per Massenänderung/Texte neu
  erzeugen ändern, ein Import, der etwas schreibt – erst nach der Prüfung der Zeilen –, Serie, Wiederherstellen).
  Eine automatische Sicherung einer seit der neuesten Sicherung unveränderten Datenbank wird nicht erneut
  geschrieben (Stand von Datei und WAL in `Backups/.letzte_sicherung.json`; `auto_backup` liefert dann die
  vorhandene). Neben den neuesten 30 gilt für die automatischen (`vor_…`) ein Größenbudget von
  `max(1 GiB, 10 × Datenbankgröße)` – die ältesten gehen zuerst, die neuesten 3 bleiben, manuelle zählen nie.
  Wiederherstellen kopiert seitenweise **in** die offene Datei (Windows erlaubt kein Ersetzen, solange Altium sie
  offen hat) und prüft die Sicherung vorher; danach laufen die Datenmigrationen des Öffnens (auch Verweise einer
  vor dem Umzug geschriebenen Sicherung), die Schema-Callbacks und `events.PARTS_CHANGED (None, True)`. Die
  SchLib/PcbLib-Dateien gehören nicht zur Sicherung: `POST /api/backups/{name}/restore` startet danach den Job
  „Bibliotheken nach dem Wiederherstellen abgleichen“ (Art `libraries.scan`, hält die Bibliothek, Antwort `job`):
  `sync.scan_workspace(rebaseline=True, previous_manifests=…)` mit den **vor** dem Wiederherstellen gelesenen
  Manifesten (`sync.manifest_snapshot()`) – nach der Sicherung von PartForge geschriebene Dateien bleiben PartForges
  eigene (nicht „außerhalb geändert“), Bauteile mit anderem Stand als die Registrierung werden `pending`, in der
  Datei fehlende ebenso – und, wenn etwas aussteht, `sync.sync_pending`: die wiederhergestellte Registrierung ist der
  Sollzustand.
* **Prüfen** (`health.py`): Pflichtfelder, doppelte Teilenummern/MPNs (`pn_key`/`mpn_key`), nicht kanonische Werte,
  unsichtbare Zeichen in Teilenummer/MPN (`format`, Warnung), Auswahllisten, nicht registrierte oder fehlerhafte
  Symbole/Footprints, fehlende Bibliotheksdateien, fehlende Datenblätter. Bericht: `issues` (höchstens
  `max_per_check` je Prüfung), `summary`, `counts`, `total`, `truncated`, `checked_at` und – exakt, auch wenn
  gekürzt – `checked_parts`, `affected_parts`/`affected_part_numbers` (jedes Bauteil mit Fehler oder Warnung genau
  einmal) und `checks` (je Prüfung `severity`, `issues`, `affected_parts`, die ersten 20 `part_numbers`). Werte
  werden je Bericht nur einmal je (Feld, Wert) normalisiert, kanonische Datumstexte ohne `strptime`; der Scan der
  Datenbank bleibt gespeichert, bis sie sich ändert (`core.data_version`, Datenbankdatei und WAL – auch Altium),
  nur die Existenz der Bibliotheksdateien wird bei jeder Anfrage neu geprüft. `POST /api/health-check/job` (Job
  `health-check`, liest nur; nach einem Wechsel `cancelled`) liefert denselben Bericht + `message` („Daten geprüft:
  1.250 Bauteile – 2 Fehler, 14 Warnungen“).
  Felder, die für ein Bauteil nicht gelten (0-Ω-Brücke: `values.not_applicable`), sind keine fehlenden Pflichtfelder;
  TK-Bänder wie „-100 … +350ppm/K“ sind gültige Werte. Regression: eine frische Serie jeder eingebauten Vorlage
  (alle Baugrößen, kurzer Wertebereich, Brücke wo vorhanden) ergibt 0 Fehler und 0 Warnungen
  (`tests/test_series_quality.py`).
* **Import/Export** (`importers/spreadsheet.py`): CSV/XLSX/ODS mit Vorschau, Spaltenzuordnung (rapidfuzz) und
  Einheiten aus Kopfzeilen; Import als Job über `upsert_parts`; Export CSV (UTF-8 mit BOM, `;`) oder XLSX.
  CSV-Export schützt standardmäßig (`excel_safe=true`, API, Ordner-Export und Job) Werte, die Excel als Formel
  ausführen würde – `= + @`, Tab, CR und `-` außer reinen Messwerten wie „-55°C“, „-40 … 85°C“ – mit `'` (der
  Import entfernt es wieder); `excel_safe=false` schreibt alles unverändert. Lange Texte: CSV-Felder bis 2 GiB
  (`csv.field_size_limit`), nicht lesbares CSV → 400; XLSX kürzt Zellen auf 32.767 Zeichen – der Export meldet sie
  (`ExportFile.warnings`, Job-/Ordner-Ergebnis `warnings`, Schlussmeldung, Download-Header
  `X-PartForge-Truncated-Cells`), die Vorschau warnt bei Zellen mit genau 32.767 Zeichen, und ein Import im Modus
  `update` überschreibt damit nie einen längeren gespeicherten Text, der so beginnt. Import-Option `thousands`
  (`ImportOptions`, Vorschau): Zahlenformat der Quelle für „1,000“ (`null` = mehrdeutig → Warnung, `true`
  Tausender, `false` Dezimalkomma). Hochgeladene Dateien liegen 24 h in `<local data>\import`. Der Export-Job meldet
  Fortschritt je 500 Zeilen und lässt sich dabei abbrechen.
  Die Vorschau enthält einen Probelauf je Zeile für die aktuelle Zuordnung, den Modus und die festen Werte
  (`check_rows` → `parts.plan_upsert`: `create|update|unchanged|skip|reject` mit Gründen, Zeile der Datei);
  `strict` lehnt Zeilen mit nicht lesbaren Werten ab; das Job-Ergebnis trägt `error_count`, `outcome`
  (`ok` | `partial` = trotz Fehlern etwas übernommen | `failed`) und `message` (= Schlussmeldung des Jobs,
  `import_message`: „Import fertig: 120 neu, 4 aktualisiert, 2 abgelehnt“ bei `ok`/`partial`, „Import
  fehlgeschlagen – nichts übernommen: 2 abgelehnt“ bei `failed`; Anzahlen über `domain.text.plural`, Nullen
  entfallen). Das Job-Log nennt Zeilen, Datei, Kategorie und Modus („2 Zeilen aus „liste.csv“ → Widerstände
  (Modus: vorhandene überspringen|aktualisieren|ablehnen)“), die Sicherung und die ersten 50 abgelehnten Zeilen.
  Der Import-Job (`import`) hält seine Bibliothek (`run_import(…, library=root)`, §8.4); die Bauteile entstehen
  in einer Transaktion – ein abgebrochener Import hat nichts übernommen. Der Export-Job (`export`, `POST
  /api/export/{table}/job`, Schlussmeldung „Export fertig: 4 Bauteile in Exports\…“) liest nur und hält nichts:
  `export_to_file(…, library=root)` liest, solange seine Bibliothek offen ist, und schreibt die Datei nur, wenn sie
  danach noch offen ist, in ihren `Exports`-Ordner – nach einem Wechsel endet er `cancelled` (`LibraryChanged`,
  `cancel_reason = "library_switch"`) ohne Datei.
* **Beispielinhalte** (`examples.py`): 19 echte Bauteile in 13 Kategorien. Symbole über `partforge.symbols`
  (Typen; der LDO als IC-Symbol aus der Pinliste), Footprints über `partforge.footprints` im Hausstil des
  Workspaces (Diodenkonvention und Namensschema inklusive), registriert mit Geometrie und Status `pending` in den
  Dateien von `libwriter.symbol_library_path`/`footprint_library_path`; die Bauteile verweisen auf diese Namen und
  Pfade. Teilenummern folgen `part_number_scheme` (`internal`: erzeugte Nummern, ein Beispiel wird an seiner MPN
  wiedererkannt). Vorhandene Bauteile, Symbole und Footprints bleiben unverändert.

## 5. Geometrie (`partforge/geometry/model.py`)

Gemeinsamer Vertrag aller Erzeuger und Verbraucher (Generatoren, Datenblatt-KI, Bibliotheksleser, Writer,
SVG-/3D-Vorschau, STEP); das Frontend spiegelt ihn über OpenAPI.

* Symbole in **mil**, +Y oben. `SymPin.x/y` = körperseitiges Ende, `orientation` zeigt nach außen; Pins auf dem
  10-mil-Raster, Pinspitzen auf dem Symbolraster (100 mil). Mehrteilige Symbole: `part_count`, `SymPin.part`
  (0 = in allen Teilen). `SymPin.inner_edge`/`outer_edge` = Pin-Dekorationen (nur die sieben, die der Rust-Writer
  korrekt speichert). `SymbolSpec.designator_pos`/`comment_pos` (`TextPos`) = Lage von Bezeichner und Kommentar.
  Low-aktive Namen in Altiums Überstrich-Syntax (`R\E\S\E\T\`).
* Footprints in **mm**, Ursprung = Gehäusemitte, Drehung gegen den Uhrzeigersinn, logische Lagen (`FpLayer`:
  Kupfer, Bestückungsdruck, Paste, Maske, courtyard, assembly, body3d, designator, comment, component_center,
  component_outline, keepout) – die Abbildung auf Altium-Lagen macht der Writer über `LayerMap`. `Pad`: Form,
  Eckenradius %, Seite (top/bottom/through), Bohrung, Langloch (`hole_length`, `hole_rotation`), Paste/Maske,
  `thermal` (EP).
* 3D: `Body3D` = extrudiertes Prisma (Umriss + z-Bereich + Farbe); optional `StepModel` (Datei, Drehung, Versatz).
  Registrierte Footprints können zusätzlich mehrere originale STEP-Körper aus einer PcbLib darstellen:
  `altium.step_preview.resolve_models` liefert Dateiversion, Modellname, Drehung und Versatz je Körper,
  ohne die editierbare Spec oder die PcbLib zu verändern. `GET /api/libraries/footprints/{name}/step-models`
  liefert das Modellverzeichnis mit Hinweisen; `…/step-models/{model_id}` liefert die STEP-Bytes. Beide Routen
  halten den Workspace während des Zugriffs. Modell-IDs binden Bibliothek, Footprint, Inhalt und Platzierung;
  der Client kann keine beliebigen Dateipfade anfordern. Eingebettete Modelle werden bei Bedarf über den
  vorhandenen Extraktionscache gelesen; gespeicherte STEP-Dateien funktionieren auch ohne Writer.
  Die Dateiabrufe einer Vorschau verwenden die Auflösung ihres Modellverzeichnisses wieder
  (`remember_models`/`cached_model`), solange Datensatz, PcbLib und Modelldatei unverändert sind – sonst wird neu
  aufgelöst. Die Vorschau begrenzt Größe (64 MB je Modell, 128 MB gesamt) und Anzahl (128); der Download
  `…/step` (`resolve_models(limits=False)`) liefert jede Modelldatei unabhängig von der Größe.
  Automatisch aus `Body3D` erzeugte STEP-Dateien werden nicht zusätzlich über dieselben Prismen gezeichnet.
  Beim Import wird `MODEL.2D.ROTATION` in die Z-Drehung der `StepModel` eingerechnet (der Writer schreibt keine
  2D-Drehung), damit ein neu geschriebener Footprint sein Modell gleich ausrichtet.
  Die Tessellierung erfolgt offline im Frontend-Web-Worker mit `occt-import-js`, siehe `FRONTEND.md`.
* Texte: `FpText.font` (`stroke` | `truetype`) und `font_name` (TrueType-Schrift). Die Standardwerte zählen nicht
  zum Fingerabdruck und zur Identität (`geometry.model.compat_text_dump`) – ältere Footprints gelten dadurch nicht
  als geändert.
* `check_symbol_footprint(symbol, footprint)` meldet Pins ohne Pad und Pads ohne Pin (streng).
  `pin_pad_check(symbol, footprint, *, free_pads=(), unused_ok=False) -> (problems, hints)` (Mengenform
  `pin_pad_gaps(pins, pads, thermal, …)`) ist die eine Regel von Datenblatt-Vorschlag, Symbolvorschlag und
  Dateiprüfung: Pins ohne Pad sind ein Problem; Pads ohne Pin auch – außer `free_pads` (absichtlich frei: NC-Pins
  des Datenblatts, `x` einer Buchstaben-Pinbelegung), Exposed/Thermal-Pads und bei `unused_ok` (OPV, Komparator,
  Oszillator: NC/Offset-Pads normal) jedes; ein Exposed Pad ohne Pin ist nur ein Hinweis. Die Symbolseite liefern
  `symbols.free_pads(spec_or_generator)` (`generator["nc_pads"]` – vom Datenblatt-Import vermerkt – und die
  `x`-Stellen von `generator["pinmap"]["key"]`) und `symbols.unused_pads_ok(spec_or_generator, kind)`
  (`symbols.UNUSED_PADS_OK`).

## 6. Footprint-Generator (`partforge/footprints`)

```python
families() -> list[FamilyInfo]; family_info(key) -> FamilyInfo; presets(key) -> list[Preset]
    # FamilyInfo.aliases (weitere Namen, die auf die Familie auflösen), supports_land_pattern (per Probe bestimmt)
generate(req, style=None, *, diode_pin1=None) -> FootprintSpec        # ValueError (deutsch) bei Fehlern
error_params(exc, family=None) -> list[str]   # ParamError.params, sonst Parameter, deren Bezeichnung die Meldung nennt
preview(req, style=None, *, svg=True, diode_pin1=None) -> FootprintPreview
    # FootprintPreview: spec (FootprintSpec), calc, warnings, issues, svg
chip_request(kind: "R"|"C"|"L"|"FB"|"D"|"LED", size, *, density=None) -> FootprintRequest   # Serien
request_from_package(family, dims, *, density=None, land_pattern=None, name=None, params=None)   # Datenblatt-KI
validate_footprint(spec, style=None) -> list[CheckIssue]; render_svg(spec, …) -> str
write_step(spec, path) -> Path; step_text(spec) -> str                # AP214 aus den Body3D-Prismen
effective_style(style=None) -> FootprintStyle
```

* Rechenprotokoll: `calc.lands[].table_title` ist die deutsche Bezeichnung der J-Tabelle (englischer Titel in
  `table_title_en`), bei Herstellerempfehlung „Herstellerempfehlung (Land Pattern)“.

* IPC-7351B (Gleichungen, J-Tabellen, Rundung aus `ipc-footprints.md`, Referenzimplementierung
  `recherche/ipc-work/ipc7351b_ref.py` mit KiCad-Testvektoren), Dichte M/N/L, Hausstil aus `FootprintStyle`.
* **21 Familien**: `chip`, `molded` (Tantal CAPMP, INDM, FUSM, DIOM), `melf`, `sod`, `do214` (SMA/SMB/SMC),
  `sot23` (3/5/6), `sc70`, `sot523`, `sot89`, `sot223`, `dpak` (DPAK/D2PAK), `gullwing` (SOIC/SSOP/TSSOP/MSOP/QSOP),
  `qfp`, `nolead` (QFN/DFN/SON mit EP und Pastenfenstern), `bga`, `dip`, `axial`, `radial`, `to92`, `to220`,
  `pin_header` (1×N/2×N). `req.family` darf ein **Alias** sein, der Variante bzw. Vorlage mitbringt (`dfn`, `smb`,
  `sot363`, `tantal`, `resistor`, `stiftleiste` …).
* `style=None` = Hausstil des offenen Workspaces (ohne Workspace: Standard).
* **Diodenkonvention**: ohne `cathode_pad` folgt Pad 1 `SymbolStyle.diode_pin1` (`cathode` = IPC; `anode` →
  Kathode an Pad 2, Namen mit IPC-Umkehrzeichen `R`: `SOD3716X135RN`, `LEDC1608X80RN`); `diode_pin1=` übersteuert.
* **Namen eindeutig je Land Pattern**: IPC- oder Hausnamen (`RESC1608X50N`, `SOIC127P600X175-8N`); entspricht die
  Anfrage einer Vorlage (Standardmaße), bleibt der reine Name, sonst wird `_<TAG>` angehängt (4 Hex-Zeichen eines
  Hashs der landrelevanten Parameter, unabhängig vom Hausstil): `INDM125125X650N_6E43`. `spec.generator` enthält
  Parameter, `land_hash` und `geometry_hash` (Writer erkennen geänderte Geometrie hinter gleichem Namen).
* **Eigene Namen** („MY_SOIC8“ statt `SOIC127P600X175-8N`): `spec.generator.names` = `{ipc, house}` (die Namen,
  die der Generator diesen Parametern gibt, mit `_<TAG>`); `spec.generator.name` steht **nur** bei einem eigenen
  Namen (`FootprintRequest.name`, der keiner davon ist). „Neu generieren“ gibt `generator.name` als
  `FootprintRequest.name` zurück und reproduziert so den Namen; ein erzeugter Name folgt dagegen dem Namensschema
  des Hausstils. `with_name_record(spec)` hält `generator.name` beim Speichern richtig (auch für Specs, die der
  Client umbenannt hat, und für ältere Specs ohne `names` – dann über eine erneute Berechnung, `generated_names`).
* Herstellerempfehlung (`land_pattern`) übersteuert die IPC-Berechnung, wo die Familie das unterstützt.
  `row_spacing_y_mm` = eigener Reihenabstand der oberen/unteren Reihe (QFN/QFP); ein **rechteckiger** QFN (D ≠ E) mit
  Herstellerempfehlung ohne ihn wird abgelehnt (`ParamError`) – ein Abstand passt nie zu beiden Reihen.
* **Unregelmäßige QFN/DFN** (`nolead`, z. B. TI RGY0019B, VQFN-19 3,5×4,5): `pins_x`/`pins_y` = Positionen je Seite
  (fehlende mitgezählt), `e_x` = Raster der oberen/unteren Reihe (Standard `e`), `pin1` = `left` (oben auf der
  linken Seite, JEDEC) | `top` (linkes Ende der oberen Seite), `missing` = Positionen ohne Anschluss („14“, „5, 6“;
  gezählt ab Pin 1 gegen den Uhrzeigersinn, als wären alle bestückt; die Pins werden über die übrigen Positionen
  durchnummeriert, DFN/SON nur `missing`). Nicht angegeben, bleiben die Parameter außerhalb von `generator.params` –
  vorhandene Footprints behalten Namen und Geometrie. `base.quad`/`dual_row` setzen das um (`missing_positions`).
* `generate` liefert nie einen Footprint mit Fehlern der Plausibilitätsprüfung (überlappende Pads,
  Bestückungsdruck auf Kupfer, Courtyard …); `preview` zeigt sie an.
* Noch keine Familie für Quarze und Chip-Sicherungen: die Beispiele nutzen das IPC-Chip-Land ihrer Gehäuse mit
  explizitem Namen – IPC-Stil `XTAL3215X90N`/`FUSC3216X60N` (auch als `ipc_name`), mit Hausnamen
  `XTAL 1.5x3.2MM`/`FUSE 1206_3216`.

## 7. Symbol-Generator (`partforge/symbols`)

```python
kinds() -> list[SymbolKindInfo]                          # 40 Standardtypen + "ic"
generate(req: SymbolRequest, style=None) -> SymbolSpec   # SymbolError (ValueError, deutsch)
ic_symbol(name, pins: list[IcPin], *, parts=None, style=None, …) -> SymbolSpec
auto_assign_sides(pins, *, regulator=None) -> list[IcPin]
standard_symbol_for(category_table, values, *, pins=None, footprint=None, style=None) -> SymbolRequest | None
suggest_symbol(category_table, values, *, pins=None, footprint=None, style=None) -> SymbolSuggestion
render_svg(spec, *, theme="altium", part=None, …, thumbnail=False) -> str; render_parts(spec, …) -> list[str]
render_thumbnail(spec, *, theme="dark", style=None) -> str   # Vorschau: serifenlose Schrift, konstante Linienbreite
check_spec(spec, *, grid=100) -> list[str]; spec_warnings(spec, *, grid=100); example_request(kind)
```

* **Standardtypen**: Passive (Widerstand, Poti, Trimmer, Kondensator, gepolt, Induktivität, Ferrit, Quarz 2/4,
  Sicherung, PTC, Varistor), Halbleiter (Diode, Z-, Schottky-, TVS-Dioden, LED, Fotodiode, Brückengleichrichter,
  NPN/PNP, NMOS/PMOS, Optokoppler 4/6), ICs (OPV einfach/zweifach/vierfach, Komparator, Oszillator), Verbinder
  (Steckverbinder 1×N/2×N, Testpunkt), Sonstige (Befestigungsloch, Passermarke, Schalter, Taster, Relais, Summer,
  Batterie). `kind="ic"`: Kastensymbol aus einer Pinliste (Versorgung links oben, Masse/NC/EP unten, Eingänge
  links, Ausgänge und FB/COMP/PG rechts, SW/BST oben; Gruppen; automatische Teilung großer ICs).
* **Hausstil**: Diskrete blau, Pin-Namen/-Nummern verborgen; ICs in Altium-Standardfarben, Pins 200 mil, Raster
  100 mil; Grafik vor den Pins (`primitive_order`); Symbole für die DbLib sind **generisch** (keine Parameter,
  keine Footprint-Links – das liefert die DB).
* **Namensregel**: Der Name ist je Typ + Pinbelegung fest („Resistor“, „Op-Amp Dual“, „Connector 1x04“). Ein Name
  ohne Zusatz bedeutet immer die kanonische Belegung (Diode: Pin 1 = Kathode), abweichende Belegungen tragen den
  Code als Zusatz („Diode (AK)“, „NPN (EBC)“, „Schottky Diode (AxK)“) – ein Name ändert nie seine Bedeutung,
  wenn der Hausstil wechselt.
* **Pinbelegungen** (`params["pinmap"]`): Vorlagen als Buchstabencode je Pad (`KA`/`AK`/`AxK`, `BEC`/`EBC`/`BCEC`,
  `GSD`/`SSSGDDDD`/`DDGSDD`, `SOT23-5`/`SOIC8` …), eigene Codes oder ein Objekt; Fahne/Exposed Pad wird Drain bzw.
  Kollektor. Standard der Dioden folgt `SymbolStyle.diode_pin1`.
* **Vorschlag** (`suggest_symbol`): Gehäuse aus `Package`/`Footprint Ref` (auch IPC-Namen), Pinliste oder
  Footprint-Pads. Ein fertiger `request` nur, wenn die Belegung sicher ist; sonst `kind` + `needs_pinmap` +
  `pinmap_options` (z. B. TO-92-Transistoren) – nie geraten.
* `spec.generator` = `{kind, version, params, request, style, pinmap?, text_positions, default_name, name?}`
  (+ `layout` bei ICs) für die Neugenerierung. `default_name` = Name der Anfrage ohne eigenen Namen („Op-Amp Dual“,
  „IC 8-Pin“); `name` nur bei einem **eigenen** Namen („MY_OPAMP“) – dann steht er auch in `request.name`, die
  Neugenerierung aus `request` reproduziert ihn. `with_name_record(spec)` hält beides beim Speichern richtig (ältere
  Specs: `generated_name` erzeugt die Anfrage ohne Namen erneut).

## 8. Altium-Anbindung (`partforge/altium`)

### 8.1 DbLib und ODBC (`dblib.py`, `odbc.py`)

```python
connection_string(ws) -> str; odbc_connection_string(ws) -> str
render_dblib(ws, categories=None) -> str; write_dblib(ws) -> Path; ensure_dblib(ws, *, force=False) -> DbLibWriteResult
dblib_bytes(ws, which="target"|"file") -> bytes     # exakte Dateibytes (Download)
read_dblib(path) -> DbLibInfo; dblib_status(ws) -> dict; status_model(ws) -> DbLibStatus
test_odbc(ws) -> dict          # liest die Datenbank wie Altium: pyodbc, 64-bit-Treiber, gleiche Attribute
DbLibAutoWriter                # schreibt die DbLib bei Schemaänderung / beim Öffnen neu
```

* **Neu schreiben** (`ensure_dblib`, `DbLibWriteResult`): `reason` = genaue Ursache (`missing`, `outdated` –
  Tabellen/Feldzuordnungen/Verbindungsschlüssel anders oder Datei unlesbar –, `db_moved` – andere Datenbank: andere
  SQLite-Datei, auch unter 8.3-Kurznamen, oder anderer PostgreSQL-Server/-Datenbank –, `settings` – dieselbe
  Datenbank über eine andere Verbindung bzw. Datenbanktyp in den Einstellungen gewechselt –, `format` – nicht
  cp1252/CRLF/ohne BOM –, `forced`, `unchanged`), dazu `reason_id` (stabile API-Kennung) und `reason_text`
  (deutsch). `force` schreibt jede abweichende Datei, behält aber die echte Ursache; `forced` nur, wenn sich bloß
  Altiums UI-Zustand oder die Reihenfolge unterscheiden. Identische Bytes werden nie geschrieben.
  `POST /api/altium/dblib/regenerate` → `{written, reason, reason_text, path, warnings, status}` mit `reason` ∈
  `missing | outdated (auch format) | wrong_database (db_moved) | settings_changed | forced | up_to_date`.
* **Vorschau und Download** `GET /api/altium/dblib/preview`: JSON `{path, file_name, text, current, up_to_date,
  warnings}` mit maskierten Passwörtern; `?raw=true` liefert stattdessen die Datei – die **exakten Bytes**
  (cp1252, CRLF, unmaskiert, da Altium das Passwort braucht) von `?which=target` (Standard: was PartForge jetzt
  schreiben würde, Altiums UI-Zustand übernommen) oder `?which=file` (die Datei auf der Platte; 404, wenn es sie noch
  nicht gibt), `Content-Type: text/plain; charset=windows-1252`, `Content-Disposition: attachment;
  filename="PartForge.DbLib"` (Dateiname der DbLib, Umlaute als `filename*=UTF-8''…`).
* **ODBC-Test** (`odbc.test_odbc`, Job `altium.odbc_test`): Bericht `OdbcReport`; der Job endet mit
  `summary` („ODBC-Verbindung in Ordnung: 13 Tabellen, 1 Bauteil gelesen in 0,42 s (2 Hinweise).“).
* **ODBC-Treiber im Status** (`odbc.driver_status(ws)` → `GET /api/altium/status` `odbc`): `OdbcDriverStatus{kind,
  driver, installed, message, download}` – ob der Treiber, den die DbLib nennt, installiert ist (Treiberliste
  `pyodbc.drivers()`, eine Minute zwischengespeichert, keine Verbindung); `installed = null` = nicht feststellbar.
  Ohne Treiber liest Altium kein einziges Bauteil – die Oberfläche sagt dann nie „Alles bereit“.

* SQLite (VERIFIED): `Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3 ODBC
  Driver;Database=<ABS>;NoCreat=1;"` + `LibraryDatabasePath=<ABS>`, `DatabasePathRelative=0`. PostgreSQL:
  `DRIVER={PostgreSQL Unicode(x64)}` aus `db.postgres_odbc`, Anführungszeichen `"`.
* Codes (VERIFIED aus WorkspaceManager.dll): FieldType 0 = Lookup Key, 1 = Normal; AddMode 0 = Default, 1 = Do not
  add, 2 = Add, 3 = Add only if not blank; global AddMode=3, RemoveMode=1, UpdateMode=2. Reservierte Parameter in
  eckigen Klammern (`[Library Ref]`, `[Library Path]`, `[Footprint Ref]`, `[Footprint Path]`, `[Footprint Ref 2]`,
  `[Footprint Path 2]`, `[Description]`); `VisibleOnAdd` aus `show_on_schematic`, `AddMode=1` für
  `add_to_design=False`. Jede Kategorietabelle gelistet (`Enabled` = `altium_enabled`), `pf_*` deaktiviert.
* Datei: cp1252, CRLF, kein BOM; Altiums UI-Zustand aus einer vorhandenen Datei wird übernommen.

### 8.2 Aktualisierung in Altium (`refresh.py`, VERIFIED `recherche/altium-refresh.md`)

Altium öffnet eine installierte DbLib als verstecktes Server-Dokument, dessen ODBC-Verbindung einen
SQLite-Snapshot festhält. `AltiumRefreshService` hört auf `PARTS_CHANGED` und Schemaänderungen, entprellt (~2 s)
und startet bei `auto_refresh`, laufendem Altium und installierter DbLib den Job `altium.refresh`
(`AltiumBridge.refresh_dblib`: Dokument schließen, nur wenn unverändert und nicht angezeigt, ~0,4 s – geänderte und
gelöschte Zeilen sind danach sichtbar). Nach **Einfügungen** und nach **Strukturänderungen** (Tabellen,
`altium_enabled`, Spalten neu/umbenannt/entfernt, neu geschriebene DbLib, wiederhergestellte Sicherung) zusätzlich
der Index-Neuaufbau `IntegratedLibrary:RefreshInstalledLibraries` (~3 s): nur er leert Altiums „nicht
gefunden“-Cache und lädt die Spaltenliste neu, die Altium je Tabelle cacht (VERIFIED, `altium-e2e.md` §5.1). Rein
kosmetische Änderungen (Bezeichnung, Farbe, Feldreihenfolge …) lösen nichts aus. `refresh_now` = „In Altium
aktualisieren“. Nach einem Fehler kein automatisches Wiederholen (außer wenn die Brücke nur belegt war); die
nächste Änderung oder die manuelle Aktion versucht es erneut. Start/Stopp über die Lifespan des Altium-Routers.

* **Nur die eigene DbLib**: `refresh_dblib` erkennt DbLibs nur am **Dateinamen**. Der Job ruft es deshalb nur auf,
  wenn **diese** DbLib installiert ist – laut Zwischenspeicher aus der laufenden Altium-Sitzung, sonst nach der
  lesenden Prüfung `install_state` (Ergebnis wird gespeichert). Ist sie nicht installiert, wird nichts angefasst
  (auch keine gleichnamige DbLib einer anderen Bibliothek); Schlussmeldung „Die DbLib … ist in Altium nicht
  installiert – nichts zu aktualisieren“ bzw. „Diese DbLib ist in Altium nicht installiert – eine gleichnamige DbLib
  einer anderen Bibliothek ist installiert (…); sie wurde nicht angefasst.“
* **Ergebnis** des Jobs: `message, trigger (auto|manual), rebuild_index, installed` (= diese DbLib erreicht),
  `quiet` (automatischer Lauf ohne Installation – die Oberfläche zeigt dafür **keine** Meldung), `result`.
  `RefreshStatus.last_refresh`/`refresh_count` zählen nur Läufe, die diese DbLib erreicht haben.
* **Gelöschte Bauteile**: Nach einem bloßen Schließen lädt Altium für einen gelöschten Schlüssel weiter das alte
  Symbol aus seinem Zwischenspeicher. Gab es seit der letzten Aktualisierung Löschungen (`pf_audit`, Aktion
  `delete`), baut der Job auch den Bauteilindex neu auf.

### 8.3 Bibliotheks-Writer (`libwriter.py`, `rustwriter.py`, `bridge/writer.py`)

```python
class LibraryWriter(Protocol):
    name: str                                                       # "rust" | "altium"
    def available(self) -> tuple[bool, str]: ...
    def write_symbols(self, library: Path, symbols: list[SymbolSpec]) -> WriteResult: ...        # Upsert
    def write_footprints(self, library: Path, footprints: list[FootprintSpec]) -> WriteResult: ...
    def write_library_full(self, library: Path, specs) -> WriteResult: ...   # Datei mit genau diesen Bauteilen
    def delete_components(self, library: Path, names: list[str]) -> WriteResult: ...
    def list_components(self, library: Path) -> list[str]: ...
    def read_symbol(self, library: Path, name: str) -> SymbolSpec | None: ...
    def read_footprint(self, library: Path, name: str) -> FootprintSpec | None: ...
    def scan_library(self, library: Path) -> list[ComponentInfo]: ...
get_writer(settings=None, *, workspace=None) -> LibraryWriter
    # auto: Rust-Writer, sonst laufendes Altium; sonst WriterUnavailable (deutsch, HTTP 503)
backend_status() -> list[BackendStatus]
symbol_library_path(ws, spec, category=None) -> Path; footprint_library_path(ws, spec) -> Path
```

* **Rust-Backend (Standard)**: ein langlebiger Prozess `altium-designer-mcp.exe` (GPL, nur als eigener Prozess)
  mit eigener Konfiguration (`allowed_paths` = Workspace-Wurzel + Temp), Timeout `rust_writer_timeout_s`.
  Strikte Client-Validierung vor dem Senden (Pin-Koordinaten auf 10 mil, Designatoren als Text, Enum-Whitelist,
  Pad-`shape` explizit, nur `stack_mode simple`, nur die sicheren Pin-Dekorationen, Freitext als `labels`),
  `primitive_order` mit allen Grafiken **vor** den Pins (VERIFIED), Abgleich der Antwort (Namen, Pin-Echo,
  Metadaten). STEP wird über Träger-Footprints eingebettet; zusätzlich ein extrudierter Körper mit echter Höhe.
* **Atomar und absturzsicher**: Jede Schreiboperation (alle Aufrufe samt Prüfung, Lagen-Kopf und Bauhöhen) arbeitet
  auf einer **Arbeitskopie** `<stem>.pfwork<hex8>.<ext>` neben der Bibliothek (`libwriter.is_temp_library_file`,
  nie gelistet); erst wenn alles gelungen ist, ersetzt sie die Bibliothek mit **einem** `os.replace` – die Datei hat
  nie einen Zwischenstand (z. B. nur STEP-Träger), ein Absturz lässt die alte, vollständige Datei zurück. Bei einem
  Fehler wird die Kopie verworfen und jede Komponente des Aufrufs in `WriteResult.errors` gemeldet. Nach Erfolg liegt
  der alte Stand als `Backups/lib/<lib>.<JJJJMMTT_hhmmss_mmm>.bak` (die neuesten 20 je Datei); die `.bak`-Dateien
  des Writers werden gelöscht, Überbleibsel eines Absturzes (Arbeitskopien, `__PFSTEP_*`-Träger) beim nächsten
  Schreiben entfernt. Ein Betriebssystemfehler (Datei gesperrt) ergibt „PF_CHIP.PcbLib wurde nicht geschrieben – die
  Bibliothek ist unverändert: Die Datei ist von einem anderen Programm geöffnet …“ (`rustwriter.file_access_message`).
* **Wortwahl** (`altium/texts.py`): in Benutzertexten heißt das Programm immer „Bibliotheks-Writer“ (der Name
  `altium-designer-mcp.exe` nur in Hilfetexten), Einstellungsorte mit „›“ wie in der Oberfläche:
  `SETTINGS_ALTIUM` = „Einstellungen › Allgemein › Altium Designer“ (`/einstellungen#altium`), `SETTINGS_WRITER`,
  `SETTINGS_LAYERS` = „Einstellungen › Hausstil › Lagen“ (`/einstellungen/hausstil?ansicht=lagen`). Ohne Writer und
  ohne Altium nennt `libwriter.no_writer_message` die Abhilfe zuerst (übersteht das Kürzen eines Toasts).
* **`library_lock(path)`** (`LibraryLock`) serialisiert Operationen je Datei zwischen Threads **und Prozessen**
  (zweites PartForge-Fenster, anderer Rechner auf einem freigegebenen Ordner): Byte-Bereichssperre (`LockFileEx`) in
  der versteckten Datei `.partforge-lock` des Bibliotheksordners, vom Betriebssystem auch nach einem Absturz
  freigegeben. Wartet höchstens `LIBRARY_LOCK_TIMEOUT_S` = 300 s, dann `LibraryLocked` („… ein anderes
  PartForge-Fenster schreibt gerade in diese Datei“; im Sync: Eintrag bleibt `pending`, HTTP 409).
* **Bauhöhen vor dem Schreiben nicht lesbar** (COM-/Programmfehler, z. B. fehlendes `win32timezone` im Paket):
  der Schreibvorgang wird abgelehnt – er würde alle Höhen auf 0 setzen; ein bloß unerwarteter Aufbau bleibt eine
  Warnung. Der Writer-Prozess, seine Konfigurationen und das Audit-Log (`rustwriter-audit.jsonl`, ab 5 MB rotiert)
  liegen im lokalen Ordner (`config.local_data_dir`/`log_dir`), Konfigurationen beendeter Prozesse werden entfernt.
* **Freitext-Regeln** (VERIFIED): Altium speichert Texte unmaskiert in `|KEY=value|`-Datensätzen – ein `|` schneidet
  ab oder schleust Schlüssel ein, Steuerzeichen zerstören Datensätze. Beide Writer lehnen das in jedem Freitextfeld
  ab (`rustwriter.free_text_issues`); Erzeuger bereinigen vorher mit `domain.text.clean_free_text`. Namen nur ASCII
  (`ascii_name`), PcbLib-Texte Latin-1 (`latin1_text`: Ω → „Ohm“).
* **Altium-Backend** (`bridge/writer.py`, `AltiumLibraryWriter`): Altium baut immer eine **neue** Datei, die die
  alte (nach Sicherung) ersetzt – nur wenn Altium **alle** Bauteile erzeugt hat. Unveränderte Bauteile werden aus
  der vorhandenen Datei gelesen (Rust-Reader); verlöre der Neuaufbau Daten (Pin-Dekorationen, eingebettete STEP …),
  wird mit `AltiumDataLossError` (`losses` je Bauteil) abgebrochen, es sei denn `allow_degradation` nach
  Bestätigung.
* **Lagen** (`layers.py`): logische Lage → Altium-Lagenname über `LayerMap` (Rust-Namen, Brücken-IDs).
  `stackup.py` liest `.stackup`-Dateien, schlägt `LayerMap`s vor und patcht den Lagen-Header jeder geschriebenen
  PcbLib auf den Workspace-Stapel (nur die Header-Werte; abschaltbar mit `PARTFORGE_LAYER_PATCH=0`): Name,
  Aktiv-Flag und Typ von **Mech 1–32** in allen drei Header-Darstellungen (V9-Cache, V8, Legacy bzw. `LAYERV7_`
  für Mech 17–32), die Lagenpaare (`MECHPAIR`) und die Lagen-Sets „&All Layers“/„&Mechanical Layers“ (aktive
  mechanische Lagen; in „&All Layers“ Mech 1–16 vor, Mech 17–32 nach `DrillDrawing`). VERIFIED (`altium-e2e.md`
  §3.2): Altium zeigt alle 32 Lagen mit Namen und Typ und behält Paare und Sets auch beim eigenen Speichern.
  Dazu der **eigene Lagensatz** (`LayerStack.layer_set`, §3): ein gleichnamiger Satz wird aktualisiert, sonst mit
  `LAYERSETSCOUNT+1` angehängt (`LAYERSET<n>NAME/LAYERS/ACTIVELAYER.7/ISCURRENT/ISLOCKED/FLIPBOARD`);
  `pcblib_layer_problems` meldet einen fehlenden oder abweichenden Satz. Köpfe, die sich nicht patchen lassen (ältere
  oder in Altium gespeicherte PcbLibs), ersetzt `stackup.renew_library_data` durch den Kopf einer frischen, leeren
  Rust-PcbLib (`rustwriter.template_library_data`, zwischengespeichert) mit dem Workspace-Stapel – Dateiname und
  Rest des Streams bleiben; `LayerKindMapping` wird dabei auf die leere Form (20 Byte) gesetzt.
* **Bauhöhe (PcbLib-HEIGHT-Patch, `heights.py`)**: Altium speichert die Footprint-Eigenschaft *Height* je Bauteil
  in `<Storage>/Parameters` (`|PATTERN=<Name>|HEIGHT=21.6535mil|…`) und im Inhaltsverzeichnis
  `Library/ComponentParamsTOC/Data` (`Name=…|Pad Count=…|Height=21.6535|…`, CRLF je Bauteil); Wert = Höhe in Altiums
  interner Einheit (1/10000 mil, gerundet) als mil mit höchstens vier Nachkommastellen (VERIFIED: 0,55 mm →
  `21.6535`, 1,75 mm → `68.8976`). Der Rust-Writer kennt kein Höhenfeld: er schreibt `HEIGHT=0mil` und setzt bei
  **jeder** Änderung (anfügen, ersetzen, löschen – auch anderer Footprints) alle Bauteile auf 0 zurück. Darum liest
  `RustLibraryOps` vor jeder PcbLib-Änderung die Höhen (`read_footprint_heights`) und setzt danach jedes Bauteil
  (`patch_footprint_heights`): die Footprints des Aufrufs auf `footprint_height(spec)` (`spec.height`, sonst
  Oberkante des höchsten 3D-Körpers), alle anderen auf ihre bisherige Höhe (auch in Altium gesetzte). Ablauf wie
  beim Lagen-Header: Streams planen und selbst prüfen, in eine Kopie schreiben (Structured Storage, transacted),
  die neu gelesene Kopie darf sich nur in den geplanten Streams unterscheiden, der Rust-Reader muss sie gleich lesen
  (`verify`), dann atomar ersetzen (`compound.replace_streams`). Jede unerwartete Struktur lässt die Datei
  unverändert und liefert nur eine deutsche Warnung – der Patch lässt nie einen Schreibvorgang scheitern;
  idempotent. Abschaltbar: `heights.HEIGHT_PATCH_ENABLED` bzw. `PARTFORGE_HEIGHT_PATCH=0`. Ältere, vor dem Patch
  geschriebene PcbLibs meldet die Dateiprüfung (`footprint_height_missing`, §8.4) samt Ein-Klick-Korrektur.
* **Unberührte Bauteile bleiben byte-gleich** (`preserve.py`, VERIFIED 2026-10-09 mit der Referenzbibliothek des
  Benutzers): Jede Änderung durch `altium-designer-mcp.exe` serialisiert **alle** Bauteile der Datei aus seinem
  eigenen Modell neu – in einer von Altium gespeicherten PcbLib verlören die nicht geschriebenen Footprints
  Mechanical 17–32 (landen auf Mechanical 16), ihre `WideStrings` (TrueType-Texte) und die eingebetteten Schriften
  (`Library/EmbeddedFonts`), in einer SchLib die nicht geschriebenen Symbole ihre `PinTextData` (Pinschriften) und
  die Bezeichnerschrift. `RustLibraryOps` hält darum vor jedem Aufruf den Stand der Arbeitskopie fest
  (`preserve.snapshot`) und setzt danach jeden Stream der Bauteile, die der Aufruf **nicht** geschrieben hat, auf die
  alten Bytes zurück (`preserve.restore_plan`) – samt der Bibliotheks-Streams, die zu ihnen gehören
  (`Library/EmbeddedFonts`, `Library/PadViaLibrary/Data`, `Storage` einer SchLib). Ein Footprint, dessen vorher
  eingebettetes 3D-Modell nach dem Schreiben fehlt, behält die Fassung des Writers (verknüpfte Modelle sind kein
  Hindernis). Geschrieben wird wie beim Höhen-Patch über `compound.replace_streams` in die geprüfte Kopie.
* **Hausschrift in SchLibs** (`schstyle.py`): Nach jedem Symbol-Schreiben setzt `patch_written_symbols` die
  Hausschrift: die Schrifttabelle behält jeden vorhandenen Eintrag, Hausschrift und ihre unterstrichene Variante
  (Hyperlink-Parameter) werden angehängt (`plan_font_table`); `FontID` der Texte (RECORD 4, 28, 34, 41, 209) der
  geschriebenen Symbole zeigt darauf, Pinnamen/-nummern bekommen sie als `PinTextData` (`pin_font = "house"`). Ist
  die Hausschrift die Systemschrift (Times New Roman 10), ändert sich nichts.
* **TrueType-Texte**: `rust_to_footprint` liest TrueType-Texte mit Schriftname (`FpText.font`, `font_name`); der
  Bezugspunkt kommt aus der gespeicherten Textbox, wenn sie plausibel ist (±30 % der Schätzung), sonst aus der
  Schätzung (`truetype_text_box`: Höhe = Zelle 1,117 em, Breite nach Zeichenbreiten); `footprint_to_rust` schreibt
  `kind: "true_type"` mit kompensiertem Anker. Barcode-Texte bleiben ein gemeldeter Verlust.
* **Mechanical 17–32 beim Lesen** (`pcbrecords.correct_layers`): Altium speichert diese Lagen mit dem V6-Byte 72
  („Mechanical 16“) plus V7-ID; der Rust-Reader meldet sie als Mechanical 16. Beim Lesen eines Footprints korrigiert
  PartForge die Lagen aus den Datensätzen (je Art und Reihenfolge, nur bei gleicher Anzahl).
* Altium sperrt geöffnete PcbLib/SchLib nicht und bemerkt externe Änderungen nicht: Die Synchronisierung schreibt
  keine in Altium geöffnete **und geänderte** Datei und lädt geöffnete, unveränderte danach neu
  (`auto_reload_libraries`).

### 8.4 Synchronisierung (`sync.py`)

```python
ensure_symbols(specs, *, category=None, source="generated", ctx=None, allow_pin_changes=False,
               strict=False, library=None) -> list[SymbolRecord]
ensure_footprints(specs, *, source="generated", ctx=None, strict=False, library=None) -> list[FootprintRecord]
sync_pending(ctx=None) -> dict          # {symbols, footprints, libraries, errors, missing, relinked}
scan_workspace(ctx=None, *, register=False, rebaseline=False, previous_manifests=None) -> dict   # „Bibliotheken prüfen“
manifest_snapshot() -> dict[str, str]  # Manifeste vor dem Wiederherstellen einer Datenbanksicherung
library_files(*, check_layers=True) -> list[LibraryFileInfo]; scan_library(path) -> list[ComponentInfo]
resolve_library_choice(kind, raw) -> Path; library_choice_conflict(spec, library) -> str | None
library_health(*, max_issues=500, refresh=False) -> dict   # Dateiprüfung, LibraryHealthIssue (zwischengespeichert)
restore_library_backup(library, *, ctx=None) -> dict       # beschädigte Datei aus Backups\lib wiederherstellen
footprint_height_problems() -> list[HeightProblem]; repair_footprint_heights(names=None, *, ctx=None) -> dict
component_thumbnail(spec, theme="dark") -> str        # das eine Vorschaubild (Registry, extern, Thumbnail-Endpunkt)
```

* Die Registry ist der Sollzustand: registrieren, je Bibliotheksdatei **ein** Schreibaufruf (unter `library_lock`),
  unveränderte Specs (Fingerabdruck) überspringen, geänderte Pinbelegung eines vorhandenen Namens nur nach
  Bestätigung (`allow_pin_changes`), Footprints mit 3D-Körpern bekommen `3D/<Name>.step`, Teilepfade folgen
  verschobenen Symbolen/Footprints (`parts.set_library_path`). Danach `events.LIBRARIES_WRITTEN`. Fortschritt je
  Art: „Symbole geschrieben: 3 (2 unverändert, 1 mit Fehler)“, „Footprints geschrieben: 5“.
* **Eigene Namen**: jeder geschriebene Spec läuft durch `symbols.with_name_record` bzw.
  `footprints.with_name_record` (§6, §7) – `spec.generator.name` vermerkt einen eigenen Namen, „Neu generieren“
  reproduziert ihn. Geändert wird dabei nur die Registry (der Fingerabdruck enthält `generator` nicht).
* **Zielbibliothek** (`library=`, Editor: `SymbolSaveIn.library` / `FootprintSaveIn.library`), geprüft von
  `resolve_library_choice` (sonst `SyncError` 400 mit der Regel): eine **vorhandene** Bibliothek der richtigen Art
  im Ordner `Symbols\` bzw. `Footprints\` (jede Datei, die `workspace_library_files` findet – externe Bibliotheken
  und Zwischendateien der Writer nie) oder eine **neue** `PF_<Name>.SchLib` / `PF_<Name>.PcbLib` direkt in diesem
  Ordner (`<Name>`: Buchstaben, Ziffern, `_`, `-`, höchstens 60 Zeichen; `NEW_LIBRARY_STEM`). Angabe relativ zum
  Bibliotheksordner (`Symbols\PF_Analog.SchLib`, `/` erlaubt), als reiner Dateiname (dann im Ordner der Art) oder
  absolut im Bibliotheksordner. Sie gilt für neue Namen; ein schon registrierter Name bleibt in seiner Datei – eine
  andere Zielbibliothek lehnt der Editor mit 409 ab (`library_choice_conflict`, im Sync als Ablehnung des
  Eintrags): Speichern verschiebt nie ein Bauteil zwischen Dateien.
* **Manifest** (`pf_meta` über `db.meta`, je Bibliotheksdatei): Dateizustand (Größe, SHA-256) nach PartForges
  letztem Schreiben und je Bauteil der geschriebene Fingerabdruck; neue Namen werden **vor** dem Schreiben als
  PartForge-eigen vermerkt
  (übersteht Fehler und Abbrüche). Eine vorhandene Datei wird nur dann komplett neu erzeugt (`write_library_full`),
  wenn der Rust-Writer schreibt, sie seit PartForges letztem Schreiben unverändert ist und PartForge jedes Bauteil
  darin aus seiner Registry geschrieben hat; sonst werden nur die geänderten Bauteile eingefügt/ersetzt (das
  Altium-Backend immer) – in Altium gespeicherte Änderungen und verlustbehaftet lesbare Fremdbauteile gehen so nie
  verloren.
* **Übernehmen statt überschreiben**: PartForge überschreibt nur eigene Bauteile (im Manifest oder als `ok` mit
  Geometrie für genau diese Datei registriert). Ein fremdes Bauteil gleichen Namens in der Zieldatei wird aus der
  Datei gelesen und als `imported` registriert; ein Symbol mit anderer Pinbelegung wird abgelehnt (außer nach
  bestätigter Pinänderung), ein nicht lesbares nie überschrieben. `sync_pending` übernimmt so auch ausstehende
  Einträge ohne Geometrie aus ihrer Datei; der Editor lehnt das Speichern unter fremdem Namen vorab ab
  (`foreign_conflict`, 409).
* **Strikter Modus** (`strict=True`, Editor-Speichern): ein nicht geschriebenes Bauteil wirft `SyncFailed` mit dem
  HTTP-Code der ersten Ablehnung – 400 ungültig (Spec, gleicher Name mit anderem Inhalt in einer Anfrage,
  Writer-Fehler), 409 Konflikt (Pinbelegung, externes oder fremdes Bauteil, Datei in Altium geöffnet und geändert,
  Datei gesperrt, `AltiumDataLossError`), 503 kein Writer (Eintrag bleibt `pending`), Rust-Timeout/-Prozessfehler,
  Brückenfehler. Ohne `strict` stehen Status und Meldung im Record.
* `sync_pending` schreibt alle Einträge mit Status `pending`/`error` – und `ok`-Einträge, die in ihrer (lesbaren)
  Datei fehlen oder deren Datei fehlt (wiederhergestellte Datenbank, verlorener Schreibvorgang); Einträge ohne
  Geometrie werden aus ihren Hinweisen (Typ, Familie + IPC-Name) erzeugt oder als `missing` markiert. Es arbeitet
  Datei für Datei (nur deren Specs im Speicher); Registry-Listen ohne Specs, Specs nur der betroffenen Namen bzw.
  Dateien (`registry.list_*(names=…)`). Externe Bibliotheken werden nur gelesen. Eine unlesbare Datei wird nie
  blind beschrieben.
* **Prüfen** (`scan_workspace`): registrierte, in der Datei fehlende Bauteile werden `pending` (die nächste
  Synchronisierung schreibt sie), gefundene `missing`/`pending` werden `ok`, unbekannte auf Wunsch als `imported`
  registriert (`register_unknown`), in einer anderen Datei registrierte Namen als `conflicts` gemeldet, verschwundene
  externe Bauteile `missing`. `changed_outside` listet die Dateien, die seit PartForges letztem Schreiben außerhalb
  geändert wurden (Manifest ≠ Datei, z. B. in Altium gespeichert; `LibraryFileInfo.external_changes`, auch in
  `GET /api/libraries/files`) – dort schreibt PartForge nur noch die geänderten Bauteile. `unreadable` listet
  vorhandene, aber unlesbare (beschädigte) Dateien (`LibraryFileInfo.unreadable`). `rebaseline=True` (nach dem
  Wiederherstellen einer Datenbanksicherung: die Manifeste sind die alten): eine „außerhalb geänderte“ Datei, deren
  Bauteile namentlich zur Registry passen, gilt wieder als PartForges; mit `previous_manifests`
  (`manifest_snapshot()` **vor** dem Wiederherstellen) behalten Bauteile einen bekannten Inhalt nur, wenn die Datei
  seither unverändert ist und der wiederhergestellte Spec dem Geschriebenen entspricht – andere eigene Bauteile werden
  `pending` (Registry = Sollzustand); ohne sie gilt ihr Inhalt als unbekannt (`rebaselined` im Ergebnis).
  Schlussmeldung (`scan_message`): „Bibliotheken geprüft: 4 Dateien – 1 Datei nicht lesbar (beschädigt?),
  2 Einträge aktualisiert, 1 unbekanntes Bauteil.“ bzw. „…, alles stimmt mit der Registrierung überein.“;
  Lagen-Job (`layers_message`): „Lagen-Kopf angepasst: 2 Footprint-Bibliotheken (1 unverändert).“
* **Beschädigte Datei wiederherstellen** (`restore_library_backup`, Job `libraries.sync` „Bibliothek aus Sicherung
  wiederherstellen“, `POST /api/libraries/restore-backup {library}`): nur für eine unlesbare Workspace-Datei – die
  neueste vom Rust-Reader lesbare `Backups\lib\<lib>.*.bak` ersetzt sie (die beschädigte bleibt als
  `Backups\lib\<lib>.<Zeit>.defekt`), das Manifest wird auf die Datei gesetzt (eigene Bauteile, Inhalt unbekannt) und
  jedes registrierte eigene Bauteil wird aus der Registry neu geschrieben (eine Sicherung kann älter sein).
  Ergebnis `{library, backup, damaged, components, rewritten, errors, message}`; 409 wenn die Datei lesbar ist, 404
  ohne lesbare Sicherung.
* **Prüfungen und ihre Kennungen** (`check`; die Oberfläche führt beide Berichte zusammen):
  * **Datenebene** `GET /api/health-check` (`db/health.py`, Modul von be-series; je Befund ein Bauteil, außer
    `registry_*`): `required` (Pflichtfeld leer), `enum` (Wert nicht in der Auswahlliste), `value` (nicht lesbar),
    `format` (nicht im Standardformat; Warnung bei unsichtbaren Zeichen in Teilenummer/MPN), `duplicate_pn`,
    `duplicate_mpn`, `symbol_missing` / `footprint_missing`
    (**nicht registriert**), `library_file_missing` (der eingetragene Library/Footprint Path existiert nicht),
    `datasheet_missing`, `registry_error` (Eintrag mit Status `error`), `registry_missing` (Status `missing`).
    Exakte Zahlen trotz `max_per_check`: `checked_parts`, `affected_parts`, `affected_part_numbers` (wie auf der
    Dateiebene) und `checks[<Prüfung>] = {severity, issues, affected_parts, part_numbers}` (§4 „Prüfen“).
  * **Dateiebene** `GET /api/libraries/health` (`sync.library_health`): je Bauteil (`part_number` gesetzt)
    `path_empty` (Pfad leer, Eintrag registriert), `library_file_missing` (eingetragene Datei fehlt),
    `component_not_in_file` (Symbol/Footprint nicht in der eingetragenen Datei); je Symbol/Footprint bzw. Datei
    (`part_number` leer) `library_unassigned`, `library_file_missing` (registrierte Datei fehlt; bei `pending` nur,
    wenn kein Bibliotheks-Writer verfügbar ist – dann entsteht sie nie, `fix_hint` = der Grund),
    `component_missing` (registriert, fehlt in seiner Datei), `registry_error` / `registry_missing` (Status – dieselbe
    Bedeutung wie auf der Datenebene), `library_changed_outside` (Datei außerhalb geändert, `info`),
    `footprint_height_missing` (PcbLib hat Höhe 0, der Spec eine Höhe; `fix_action = "repair_footprint_heights"`);
    `library_unreadable` (Datei vorhanden, aber nicht lesbar – beschädigt; Fehler je Datei mit allen Bauteilen, die
    sie eintragen oder ihre registrierten Bauteile verwenden; `fix_action = "restore_library_backup"`, wenn eine
    lesbare Sicherung existiert); `pin_pad_mismatch` (Symbol/Footprint-Paar, `part_number` = erstes Bauteil; Regel
    `geometry.pin_pad_check` (§5): NC-Pads des Symbols, `x`-Pads und unbenutzte Pads von OPV/Komparator/Oszillator
    sind kein Befund, ein Exposed Pad ohne Pin nur `info`).
  * **Ein Befund je Ursache**: fehlt ein Eintrag mit Status `missing`/`error` in seiner Datei, gibt es nur
    `component_missing` (Fehler, mit der Statusmeldung); `registry_missing`/`registry_error` (und die alten
    Kennungen) stehen dann in `aliases`.
  * **Zwischenspeicher**: der Bericht gilt, solange sich nichts ändert, wovon er abhängt (Ereignisse dieses Prozesses,
    Prüfsumme der Registry samt Spec-Texten, Anzahl und jüngste Änderung je Kategorietabelle, Größe/Zeit der
    Bibliotheksdateien, Manifeste, Writer, Schalter; höchstens 10 min) – eine Wiederholung antwortet sofort;
    `GET /api/libraries/health?refresh=true` prüft neu. Die Prüfung liest nur die Verweisspalten der Bauteile, jede
    Bibliotheksdatei einmal und Specs nur der benutzten Paare (als JSON, ohne Modelle).
  * **Umbenannt** (gleiche Kennung, andere Bedeutung als auf der Datenebene): Dateiebene `symbol_error` /
    `footprint_error` → `registry_error`, `symbol_missing` / `footprint_missing` (Status `missing`) → `registry_missing`;
    die alten Kennungen stehen vorerst in `aliases` (`sync.HEALTH_CHECK_ALIASES`). `symbol_missing` /
    `footprint_missing` heißen damit nur noch „nicht registriert“ (Datenebene).
  * `LibraryHealthIssue` (= `HealthIssue` + `kind`, `component`, `library`, `affected_parts`, `part_numbers` –
    sortiert, höchstens 20 –, `aliases`, `fix_action`): ein Befund zu einem Bauteil nennt 1 und dessen Nummer, einer
    zu Symbol/Footprint, Datei oder Paar alle Bauteile, die es verwenden. Antwort: `issues` (nach Schwere und
    Prüfung, höchstens `max_issues`), `counts` (je Schwere) und `summary` (je Prüfung) über **alle** Befunde,
    `checked_parts`, `truncated`, `affected_parts` / `affected_part_numbers` (jedes Bauteil mit Fehler oder Warnung
    genau einmal – für eine exakte Quote).
* **Footprint-Höhen** (`footprint_height_problems`): PartForge-eigene Footprints (`generated`/`datasheet`, `ok`, mit
  Geometrie) einer vorhandenen Workspace-PcbLib, deren Datei die Höhe 0 trägt, obwohl `heights.footprint_height(spec)`
  eine Höhe liefert (vor dem HEIGHT-Patch geschrieben, §8.3). Die Änderungserkennung schreibt sie **nicht** neu (der
  Spec ist unverändert). `repair_footprint_heights` (Job `libraries.sync` „Footprint-Höhen nachtragen“,
  `POST /api/libraries/footprint-heights/repair` mit optional `{names}`) schreibt sie über den normalen Weg neu
  (`_ensure(force=True)`: Sperre, Altium-Prüfung, Manifest, Sicherung, Neu laden); der Writer setzt die Höhe aus dem
  Spec. Dateien, die seit PartForges letztem Schreiben außerhalb geändert wurden, werden übersprungen (`skipped`,
  der Befund hat dann keine `fix_action`). Ergebnis `{checked, rewritten, skipped, errors, remaining, libraries,
  message}`, Schlussmeldung „Footprint-Höhen nachgetragen: 2 Footprints in 1 Bibliothek.“
* **Neue Bibliothek**: `POST /api/workspace/create` mit `with_examples` legt die Beispiele an
  (`db.seed_examples`) und startet den Job „Bibliotheken schreiben“ (`routes_system.start_library_sync` →
  `sync.sync_pending`). Vorher prüft der Job, ob ein Writer bereitsteht (`libwriter.get_writer` + `available()`);
  ohne Writer oder wenn die Bibliothek inzwischen geschlossen ist, endet er `done` mit einer Warnung
  (`{"skipped": true, "reason": …}`) und alle Einträge bleiben `pending`. Schlussmeldung
  (`routes_system.libraries_written_message`): „Bibliotheken geschrieben: 15 Symbole und 13 Footprints[, 1 Fehler,
  1 Eintrag nicht erzeugbar]“, „Bibliotheken sind aktuell – nichts zu schreiben“ bzw. „Bibliotheken nicht
  geschrieben – kein Bibliotheks-Writer verfügbar | die Bibliothek ist nicht mehr geöffnet; Symbole und
  Footprints bleiben ausstehend“. Verschwindet die Datenbank während des Schreibens (an der Sperre vorbei), endet
  er `cancelled` mit `cancel_reason = "library_switch"`.
* **Bibliothekssperre** (`jobs.library_hold`/`jobs.library_switch`): Die Datenbankfunktionen arbeiten immer auf der
  gerade geöffneten Bibliothek. Jeder Job, der Bauteile, Registry oder Bibliotheksdateien schreibt
  (`jobs.LIBRARY_JOB_KINDS`: `libraries` = „Bibliotheken schreiben“, `libraries.sync|scan|save|delete|layers`,
  `libraries.import` = Bibliotheksimport (§8.7), `libraries.conform` = Stapelbearbeitung und ihr Rückgängigmachen
  (§8.8), `series`, `datasheet-commit`, `import` = Tabellenimport), hält die Bibliothek, für die er gestartet wurde, seine
  ganze Laufzeit: `with library_hold(ctx, root) as ws`.
  Direkte Schreibzugriffe im Request (Editor speichern/löschen, externe Bibliotheken, Datenblatt hochladen,
  korrigieren, löschen) halten sie mit `ctx=None`. Halten ist geteilt (mehrere Jobs gleichzeitig; verschachtelt im
  selben Thread frei). Öffnen, Anlegen und Schließen (`routes_system`) laufen exklusiv unter `library_switch`:
  laufende Halter-Jobs werden abgebrochen (`cancel_reason = CANCEL_LIBRARY_SWITCH`; sie stoppen am nächsten
  `check_cancelled`, z. B. nach der gerade geschriebenen Bibliotheksdatei), direkte Schreibzugriffe abgewartet – erst
  dann wird die Datenbank getauscht. Stoppen sie nicht binnen `LIBRARY_JOB_STOP_TIMEOUT_S` = 20 s: `LibraryBusy` →
  HTTP 409 „Die Bibliothek wird gerade geschrieben (Job „…“) … bitte in einigen Sekunden erneut versuchen“, der
  Abbruch bleibt angefordert. Neue Halter warten, solange ein Wechsel wartet oder läuft, und prüfen dann, ob ihre
  Bibliothek (Workspace **und** Datenbank, `jobs.open_library`) noch offen ist – sonst `LibraryChanged` (ein
  `JobCancelled`; im Request HTTP 409). Ein Job schreibt also nie in eine später geöffnete Bibliothek; wartende Jobs
  werden nicht abgebrochen (scheitert der Wechsel, laufen sie weiter). Abgebrochene Jobs enden `cancelled` mit einer
  Warnung; Geschriebenes bleibt in der alten Bibliothek (`ok`), der Rest `pending`; `cancel_reason` im Snapshot
  erklärt der Oberfläche den Abbruch (API-Konventionen „Jobs“). Die Datenblatt-Jobs (`datasheet`: Lesen, Analyse,
  URL-Import) halten ihre Bibliothek nur für die kurzen Datenbankphasen mit `library_hold(None, root)` (Eintrag und
  Seitenanalyse lesen, PDF speichern, Ergebnis speichern) – ein Wechsel wartet nur darauf und bricht nie eine
  bezahlte Claude-Anfrage ab; ist ihre Bibliothek beim Speichern nicht mehr offen, bleibt das bezahlte Ergebnis im
  Ordner dieser Bibliothek (§10 „Bibliothekssperre“). Nur lesende Jobs halten nichts
  (ein Wechsel wartet nicht auf sie), müssen aber sauber enden: der Export (`export`) endet nach einem Wechsel
  `cancelled` ohne Datei, nie mit Bauteilen oder im Ordner einer anderen Bibliothek (§4 Import/Export).

### 8.5 Brücke zu Altium (`bridge/`)

Eigenes Austauschverzeichnis (`bridge_exchange_dir`, Standard `%LOCALAPPDATA%\PartForge\bridge`), eigenes,
aus Vorlagen erzeugtes Skriptprojekt, Daten über Spec-Dateien, Start über
`"<X2.EXE>" -RScriptingSystem:RunScript(ProjectName=…|ProcName="PartForgeBridge>Run")`, Schritt-Log und Timeout
`script_timeout_s`. Hängt ein Skript, meldet `BridgeWedgedError` „In Altium Strg+F3 drücken“. PartForge schließt
**niemals** Dialoge anderer Prozesse. Funktionen: Status, DbLib installieren/deinstallieren/Installationszustand,
DbLib aktualisieren, Dokument öffnen/Zustand/neu laden, Zustand vieler Dokumente in einem Lauf
(`document_states`: je Pfad geöffnet/geändert, höchstens 200 Pfade je Skriptlauf – Import und Stapelbearbeitung
fragen damit alle Zieldateien vorab ab, `_AltiumGuard.prefetch`), DB-Bauteil auflösen (Prüfung), SchLib/PcbLib
schreiben.
`refresh_document` (Neuladen nach dem Schreiben) lädt nur unveränderte Dokumente neu; ein verborgen geöffnetes
bleibt verborgen (kein neuer Editor-Tab). `resolve_db_component` installiert eine nicht installierte DbLib nur
vorübergehend und gibt danach ihr verstecktes Dokument samt Datenbankverbindung wieder frei
(`DbComponentResolution.released`). Beides VERIFIED (`altium-e2e.md` §5.2, §5.3).

**Fensterfokus** (`bridge/focus.py`): Altium holt sein Hauptfenster nach vorn, sobald ein RunScript-Befehl
ankommt – bei automatischer Aktualisierung nach jeder Änderung landeten sonst Tastendrücke des Benutzers in Altium.
`keep_foreground()` umschließt den Start (nur mit dem echten Launcher): Ist PartForge selbst im Vordergrund, sperrt
es Vordergrundwechsel (`LockSetForegroundWindow`) für die ersten `GRACE_S` = 6 s; ein Wächter-Thread prüft in
dieser Zeit alle 30 ms das Vordergrundfenster und aktiviert das vorher aktive Fenster sofort wieder, wenn Altium
(`X2.EXE`) den Fokus übernommen hat (sofern es noch existiert und sichtbar ist). Wechselt der Benutzer selbst zu
einem anderen Programm oder nach einer Wiederherstellung per Klick/Taste wieder zu Altium, hört der Wächter auf; ein
neuerer Start ersetzt den älteren Wächter. Der Aufruf wird nie verzögert, Fehler des Wächters erreichen ihn nicht.
Abschaltbar mit `PARTFORGE_ALTIUM_KEEP_FOCUS=0`.

**Prüfung in Altium** (`POST /api/altium/verify`, Job `altium.verify`; Auswahl, Modelle und gespeichertes Ergebnis in
`altium/verify.py`, Ablauf in `routes_altium`):

* **Auswahl** (`verify.select_parts`): `part_numbers` (genau diese, `scope = "part_numbers"`), `all` (alle Bauteile
  der für Altium aktivierten Kategorien, `"all"`) oder eine Stichprobe von `limit` Bauteilen (`"sample"`), jeweils
  optional auf `tables` beschränkt. `sample = "spread"` (Standard): deterministisch über alle Kategorien verteilt,
  anteilig zu ihrer Größe (größter Rest), mindestens ein Bauteil je nicht leerer Kategorie (bei mehr Kategorien als
  `limit` also eines je Kategorie), innerhalb der Kategorie gleichmäßig verteilt (Mitte gleich großer Abschnitte der
  nach Teilenummer sortierten Liste; `sample_quotas`, `spread_indices`); `"first"`: die ersten Bauteile in
  Kategorie-Reihenfolge. Umfasst eine Stichprobe jedes Bauteil der Auswahl (`limit` ≥ Anzahl), ist sie `"all"`
  (Ergebnis „alle Bauteile“, nicht „Stichprobe“). Der Jobtitel nennt Umfang und Kategorien
  (`routes_altium.verify_title`): „Bibliothek in Altium prüfen (Stichprobe: Widerstände)“, „… (alle Bauteile)“,
  „… (2 Bauteile)“.
* **Stapelweise Auflösung**: Vorher schreibt der Job die DbLib bei Bedarf (`ensure_dblib`), prüft gleichnamige
  Installationen (eine andere zuerst installierte DbLib macht die Prüfung wertlos → Fehler) und installiert eine
  nicht installierte DbLib vorübergehend (danach Dokument freigeben und deinstallieren, auch nach Abbruch); eine
  installierte wird aktualisiert (`refresh_dblib`, nach neu geschriebener DbLib mit Index-Neuaufbau).
  `AltiumBridge.resolve_db_components` löst **`RESOLVE_BATCH_SIZE` = 50 Bauteile je Skriptlauf** auf (Skriptstart
  ≈ 1,3 s, Abfrage wenige ms; `PF_MAX_RESOLVE` in `PFUtils.pas` ist die harte Grenze), Ergebnisse in der Reihenfolge
  der Schlüssel; ein unbekannter Schlüssel ist kein Fehler (`loaded = false`). Scheitert ein Lauf
  (`BridgeCommandError`), bekommen nur die Bauteile dieses Stapels den Fehler; abgebrochen wird zwischen zwei Läufen.
  Footprint-Bibliotheken liest der Rust-Reader (jede Datei einmal), nur ersatzweise Altium (`list_components`).
* **Ergebnis** (`job.result`): `message, checked, ok, warnings, errors, total, categories, temporarily_installed,
  duration_s, altium_runs, resolve_s` (= `VerifySummary`), `scope, sample, limit, tables, started, finished` und
  `parts` (`VerifiedPart`: Symbol gefunden, Pinzahl, jede Footprint-Verknüpfung – zugeordnet, Datei vorhanden,
  enthalten –, Comment und sichtbare Parameter, `description`, `parameters` (was Altium liefert, Name → Wert),
  `parameters_checked`, `parameter_diffs` `[{parameter, database, altium}]`, `extra_parameters`, Meldungen).
  **Parameterwerte** (`verify.compare_parameters`, E2EREG-3): verglichen werden die Felder, die die DbLib als
  gleichnamige Parameter zum Design hinzufügt (nicht `[Library Ref]` …, nicht `add_to_design=False`), und die
  Beschreibung (`[Description]`) – normalisiert (`verify.comparable_text`: NFKC – Mikrozeichen U+00B5 = μ U+03BC, Ohmzeichen U+2126 = Ω U+03A9 –,
  `+/-` = ±, ohne Formatzeichen, Leerraum zusammengefasst; ein leerer Wert gilt als fehlend, `AddMode=3` fügt ihn nicht hinzu). Jede
  Abweichung ist eine Warnung („Altium liefert für „Slew Rate“ keinen Wert – in der Datenbank steht „290V/µs“.“), die
  Beschreibung zuletzt; liefert Altium gar keine Parameter (kein Datensatz, älteres Brückenskript), bleibt der
  Vergleich aus (`parameters_checked = 0`). Schlussmeldung „20 Bauteile in Altium geprüft:
  18 in Ordnung, 1 mit Hinweisen, 1 mit Fehlern.“ „Symbol gefunden“ heißt: Altium lädt den **Datensatz** – lädt es
  nur ein zwischengespeichertes Symbol ohne SchLib-Verweis und ohne Parameter (gelöschter Schlüssel vor dem
  Index-Neuaufbau), ist das der Fehler „Datensatz … in Altium nicht gefunden“.
* **Deinstallieren** (`POST /api/altium/uninstall`): nach dem Deinstallieren fragt der Job den Restart Manager
  (`altium/holders.py`, nur lesend), ob ein Programm die SQLite-Datenbank (`-wal`/`-shm`) noch offen hält – Altium tut
  das oft noch etwa eine Minute, manchmal bis zum Neustart; solange lässt sich der Bibliotheksordner nicht
  verschieben. Ergebnis `database_released` (`null` = nicht feststellbar bzw. PostgreSQL), `database_holders`
  `[{pid, name}]`, `database_hint` (was zu tun ist, sonst `null`) und `outcome` (`partial`, solange ein Programm die
  Datenbank hält – Joblisten zeigen „Fertig mit Hinweisen“); die Schlussmeldung nennt zuerst, was zu tun ist, und
  passt ungekürzt in einen Toast (≤ 200 Zeichen, E2EREG-2): „Die DbLib wurde in Altium deinstalliert. Ordner erst in
  etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen (sonst Altium neu starten).“ bzw. „… Ordner
  erst nach dem Schließen von … verschiebbar – …“ (anderes Programm). Die Altium-Seite meldet den Job dann als Hinweis
  (`warnWhen` = `uninstallWarning`, voller Text).
* **Letztes Ergebnis**: Jede abgeschlossene Prüfung wird in der Bibliothek gespeichert, für die sie gestartet wurde
  (`pf_meta` `altium.verify.last` über `db.meta`, geschrieben unter `library_hold`; nach einem Bibliothekswechsel
  nicht), abgebrochene und gescheiterte nicht. `GET /api/altium/verify/last` → `VerifyRun {scope, sample, limit,
  tables, started, finished, summary: VerifySummary, results: [VerifiedPart]}` oder `null` – übersteht Neustarts.
* Alle Altium-Jobs (`install-state`, `install`, `uninstall`, `refresh`, `verify`, `open`, `odbc-test`) enden mit
  einem deutschen Ergebnissatz in `job.message`.
Nur der Altium-E2E-Agent nutzt ein laufendes Altium; die Synchronisierung greift während `pytest` nicht auf
Altium zu (außer mit `PARTFORGE_TEST_ALTIUM=1`).

### 8.6 Datensätze lesen und ändern (`pcbrecords.py`, `schrecords.py`)

Was der Rust-Writer nicht darstellen kann (TrueType-Texte mit Textbox, Mechanical 17–32, Schrifttabellen,
Pinschriften) oder beim Neuschreiben verlöre, ändert PartForge **auf Datensatzebene**: Datensätze werden geteilt,
nur die betroffenen Felder gesetzt und alles andere byte-gleich zurückgeschrieben (Hin- und Rückweg ohne Änderung
ist byte-identisch, `tests/test_pcbrecords.py`, `test_schrecords.py`). Geschrieben wird immer über
`compound.replace_streams` (geprüfte Kopie: jeder nicht geplante Stream byte-gleich, der Rust-Reader muss dieselben
Bauteile listen; `create=True` legt fehlende Streams/Storages an), dann atomar ersetzt.

* **PcbLib** (`<Footprint>/Data`): u32-Länge + Pascal-Name, dann Datensätze (Typbyte + Blöcke mit u32-Länge: Arc 1,
  Pad 6, Via 1, Track 1, Text 2, Fill 1, Region 1, Body 1 Block). Koordinaten i32 in 1/10000 mil. Offsets im
  Eigenschaftsblock (VERIFIED mit Altium 26.10): Track x1/y1/x2/y2/Breite @13/17/21/25/29, V7-ID @41; Arc
  Mitte/Radius @13/17/21, Winkel (double) @25/33, Breite @41, V7 @52; Fill V7 @42; Text Position @13/17 (linke untere
  Ecke der Textbox), Höhe @21, Strichschrift @25, Drehung (double) @27, Spiegeln @35, Strichbreite @36,
  isComment/isDesignator @40/41, Schriftart @43 (0 Strich, 1 TrueType, 2 Barcode), fett/kursiv @44/45, Schriftname
  UTF-16 @46–109, `WideStrings`-Index @115, Textbox Breite/Höhe @124/128, V7 @226; Region/Body: Eigenschaftstext
  (u32 @18, Text @22) mit `V7_LAYER=`; Pad (Block 4): Mitte @13/17, Größe oben @21/25, Bohrung @45, Drehung @52.
* **Lagen**: Mechanical n ≤ 16 = V6-Byte 56 + n, Mechanical 17–32 = Byte 72 + V7-ID `0x01020000 + n` (Altium); der
  Rust-Writer schreibt 186–201 + V7. `layer_of` bevorzugt die V7-ID bzw. das `V7_LAYER`-Kürzel, `set_layer` setzt
  alle Darstellungen, die der Datensatz hat; Pads und Vias verschiebt PartForge nie.
* **Seitenströme** beim Einfügen (`insert_primitives`): neue Datensätze kommen hinter den letzten ihrer Art;
  `<fp>/Header` (Anzahl), `PrimitiveGuids/Data` (24-Byte-Einträge: Art, Index, GUID; Art 85 = Bauteil) und
  `UniqueIDPrimitiveInformation/Data` (`|PRIMITIVEINDEX=n|`) werden umnummeriert. Neue Tracks und Texte entstehen
  aus Vorlagen eines in Altium 26.10 gespeicherten Footprints (Track 49 Byte, TrueType-Text 252 Byte) oder aus einem
  vorhandenen Datensatz desselben Footprints.
* **SchLib**: `FileHeader` mit Schrifttabelle (`FontIdCount`, `Size<i>`, `FontName<i>`, `Bold<i>` …;
  `FileHeader.fonts`/`set_fonts` behalten Position und Reihenfolge der übrigen Schlüssel); `<Bauteil>/Data` =
  Datensätze (u32: Flags << 24 | Länge; Text `|KEY=VALUE|…` + NUL; binär = Pin RECORD 2: Teil @5, Darstellungsmodus
  @7, Beschreibung (Pascal) @12, danach Formaltyp, elektrischer Typ, Flags (Richtung Bits 0–1, 0x04 versteckt, 0x08
  Name, 0x10 Bezeichner), Länge i16 in 10-mil-Einheiten, x/y i16, Farbe u32, Name, Bezeichner – `PinView`).
  `PinTextData`: Kopf `|HEADER=PinTextData|Weight=n` und je Pin ein 0xD0-Datensatz (nullbasierter Pin-Index als
  Name, zlib-Daten aus zwei Teilen – Name und Bezeichner: Flags 0x01 eigene Position, 0x02 relativ zum Bauteil, 0x0C
  Drehung, 0x10 eigene Schrift; i32 Abstand; i16 Schrift-ID + u32 Farbe).

### 8.7 Bibliotheksimport (`libimport.py`, `routes_libimport.py`)

Übernimmt Symbole und Footprints vorhandener Altium-Bibliotheken in den Bibliotheksordner – **verlustfrei als ganze
Dateien**; der Hausstil ist ein eigener, optionaler Schritt (§8.8).

* **Quellen** (`scan`, Job `library-import.scan`, liest nur): ein Ordner (rekursiv, z. B. die Celestial-Bibliothek
  mit ≈ 7 800 SchLib- und ≈ 2 150 PcbLib-Dateien), eine `.SchLib`/`.PcbLib`, eine `.IntLib` (die eingebetteten
  Bibliotheken `SchLib/<n>.schlib` / `PCBLib/<n>.pcblib` = `0x02` + zlib der ganzen Datei – VERIFIED – werden in den
  Import-Zwischenspeicher entpackt, `extract_intlib`), ein `.LibPkg` (seine `DocumentPath`-Einträge) oder ein
  `.zip` (`extract_zip`: nur Bibliotheksdateien, Pfade bereinigt – kein Laufwerk, kein `..`, keine reservierten
  Zeichen –, höchstens `ZIP_MAX_BYTES` = 1 GB entpackt und `ZIP_MAX_MEMBERS` = 50 000 Einträge; Einträge, die sich
  nur in der Schreibweise unterscheiden, erhalten eigene Namen (`_2` …); IntLibs darin werden ebenfalls entpackt). `.DbLib` wird nur mit Hinweis gelistet (ihre Bauteildaten liegen in einer Datenbank).
  Der Zwischenspeicher liegt im lokalen Datenordner (`import\libraries`, nach zwei Tagen aufgeräumt).
* **Scan** (`ImportScan`, `GET /api/library-import/scans/{id}`, sechs Stunden gültig, höchstens acht): je Datei
  `rel`, Art, Größe, `problem` (nicht lesbar), geplantes Ziel `target` und `exists` (`no` | `same` – gleiche Datei
  schon importiert | `different` – geänderte Fassung vorhanden), je Bauteil Name, Beschreibung, Pin-/Padzahl,
  3D-Körper und Zustand: `new`, `imported` (schon aus derselben Datei importiert), `taken` (Name woanders
  registriert – Altium findet Symbole/Footprints nur über den Namen; `registered_library`) oder `duplicate` (Name
  mehrfach in der Quelle). `job.result` ist die Kurzform (`ScanSummary`: Zähler, `notes`, `message`).
* **Import** (`run_import`, `POST /api/library-import/run`, Job `libraries.import`, hält die Bibliothek):
  `LibraryImportOptions {scan_id, files (rel, None = alle), target (Zielordner, Standard = Vorschlag des Scans,
  `safe_folder_name`), replace, extract_3d, convert}`. Die gewählten Dateien werden **unverändert** nach
  `Symbols\Import\<Ziel>\…` bzw. `Footprints\Import\<Ziel>\…` kopiert (relative Struktur der Quelle, ohne
  IntLib-Segment und `..`; Namen bereinigt, Ordner über 60 und Dateinamen über 100 Zeichen gekürzt mit Kurz-Hash –
  die Endung bleibt, zwei lange Namen landen nie in derselben Datei) und ihre Bauteile als `imported` registriert
  (Spec zurückgelesen für Vorschau, Prüfungen, Verwendung). Ein woanders registrierter oder in der Quelle doppelter Name wird gemeldet (`conflicts`) und nicht
  registriert (zuerst geprüft: doppelt in der Quelle, dann woanders registriert); eine Datei ohne übernehmbare Namen
  nicht kopiert; eine geänderte, schon importierte Datei nur mit `replace` – importierte Bauteile dieser Datei, die
  die neue Fassung nicht mehr enthält, werden dann abgemeldet (`removed`; sonst schriebe die nächste
  Synchronisierung sie zurück). `extract_3d` legt eingebettete STEP-Modelle vorab in `3D\` ab (Standard `false`).
  Unabhängig davon liest die 3D-Vorschau benötigte Modelle aus der kopierten PcbLib bei Bedarf (§5), auch für
  frühere Importe ohne Extraktion. `convert` gleicht danach die importierten
  Dateien an den Hausstil an (Regeln der letzten Stapelbearbeitung, `housestyle.saved_rules`). Ergebnis `copied,
  unchanged, symbols, footprints, libraries, conflicts, skipped, errors, removed, conversion, message`.
* **Vorschau** `GET /api/library-import/preview?scan_id&rel&name&theme` (SVG, vor dem Import, über den Rust-Reader).
* **Bauteile anlegen** (`parts_table`, `POST /api/library-import/parts-table {libraries?, names?}` → `{token,
  file_name, rows}`): CSV (`;`, UTF-8 mit BOM, Formel-Schutz) der registrierten Symbole mit `Part Number` (MPN-
  Parameter, sonst Comment, sonst Name), `Library Ref/Path`, `Footprint Ref/Path` (bis zu zwei), `Comment`,
  `Description` und allen Parametern (ein gleichnamiger Parameter überschreibt keine feste Spalte, füllt aber eine
  leere `Comment`/`Description`) – als Upload des Tabellenimports (§4); der Import-Assistent setzt bei der
  Spaltenzuordnung fort (eine Kategorie je Lauf).

### 8.8 Stapelbearbeitung (`conform.py`, `housestyle.py`) und Hausstil aus Beispiel (`learnstyle.py`)

Gleicht registrierte Symbole und Footprints (Standard: alle importierten; nie externe) an den Hausstil an –
verlustfrei auf Datensatzebene (§8.6): was eine Regel nicht betrifft, behält seine Bytes; Namen ändern sich nie.

* **Regeln** (`ConformRules`, jede abschaltbar; `conform.py` plant rein funktional je Bauteil):
  Symbole – `fonts` (Schrifttabelle, `FontID` der Texte, Pinschriften wie §8.3), `pin_length` (Pins von
  Box-Symbolen – Rechteck, Pins auf seinen Kanten – erhalten `ic_pin_length`; das Ende am Körper bleibt),
  `prefix` (Bezeichner-Präfix nach `prefix_map`, Standard `IC` → `U`), `colors` (Rahmen, Füllung, Pinfarbe von
  Box-Symbolen; Standard aus). Footprints – `layers` (jedes Primitiv auf die Lage seiner Rolle in der `LayerMap`),
  `widths` (Bestückung/Umriss 0,1, Courtyard 0,05, Kreuze 0,1 mm laut Stil; Bestückungsdruck nur mit
  `silk_width`), `texts` (`.Designator`/`.Comment` in Hausschrift und -höhe, Mittelpunkt bleibt; kleine Bauteile
  kleiner wie im Generator), `add_texts` (fehlende ergänzen), `add_center` (fehlendes Bauteilmitte-Kreuz ergänzen),
  `header` (Lagenaufbau und Lagensatz im Kopf, §8.3 – gepatcht oder erneuert).
* **Rollen der Quell-Lagen** je Bibliothek (`infer_layer_roles`, im Bericht mit Grund): von Hand
  (`FootprintRules.roles[<Bibliothek>][<Lage>]`), Lagentyp im Kopf (`MECHKIND`; ein Typ ohne Rolle im Hausstil –
  FabNotes, AssemblyNotes, Dimensions, jede Bottom-Lage … – heißt „unverändert“, Name und Inhalt werden dann nicht
  mehr gefragt; kennt der Lagenaufbau des Hausstils denselben Typ auf einer anderen Lage, wandert sie dorthin –
  `LayerRole.target`, z. B. „Top Dimensions“ Mech 11 → Mech 23 –, sonst nennt `LayerRole.note` eine Überschneidung
  mit einer Rollen-Lage des Hausstils), Lagenname (nie bei Notizen, Bemaßung, Board … – „Fab Notes“ ist keine Fertigungszeichnung), Inhalt
  (Mehrheit der Footprints: der äußere Umriss, der die Pads umschließt, ist der Courtyard, der innere die
  Bestückungszeichnung), sonst „unverändert“. Unabhängig von der Lage: 3D-Körper die 3D-Lage, ein Kreuz durch den
  Ursprung die Bauteilmitte (`center_crosses`: ein zweites Kreuz auf dem Courtyard ist das Courtyard-Kreuz des Stils
  `center_cross`; ein einzelnes Kreuz auf dem Courtyard gilt nur dann als Bauteilmitte, wenn der Hausstil kein
  Courtyard-Kreuz zeichnet; Kreuze auf Lagen, die die Bibliothek als etwas ohne Hausstil-Rolle ausweist – etwa
  „Bottom Component Center“ –, bleiben), `.Designator`/`.Comment` Bezeichner/Wert – hat die Bibliothek eine eigene
  Bezeichner- bzw. Wert-Lage, bleiben zusätzliche auf anderen ausgewiesenen Lagen (Bestückungszeichnung, Fab Notes)
  bei deren Rolle. In Hausschrift und -höhe kommen nur `.Designator`/`.Comment` in ihrer Rolle; Linien und freie
  Texte auf einer Bezeichner-/Wert-Lage wandern nur mit. Lässt sich ein einzelnes Bauteil nicht planen, meldet der
  Bericht es („Nicht angepasst: …“) und die übrigen der Datei werden trotzdem angepasst.
* **Prüfen** (`check`, `POST /api/housestyle/check {selection, rules}`, Job `housestyle.check`, liest nur) →
  `ConformReport`: `checked`, `affected`, `summary` (Regel → Anzahl Bauteile; `header` → Anzahl Bibliotheken), je
  Bibliothek `roles`, `header`
  (Abweichungen des Kopfs), `fonts` (Schrifttabelle danach), `refusal` (würde übersprungen, z. B. in Altium geöffnet
  und geändert), `problem`; je Bauteil mit Änderungen/Problemen `changes [{rule, message}]` (höchstens 5 000,
  `truncated`).
* **Anwenden** (`apply`, `POST /api/housestyle/apply`, Job `libraries.conform`, hält die Bibliothek): Altium-Zustand
  aller Zieldateien vorab (`document_states`), je Datei unter `library_lock`: in Altium geöffnet **und** geändert →
  übersprungen; Sicherung nach `Backups\lib`; neue Streams per `replace_streams(create=True, verify=Rust-Liste)`;
  geöffnete, unveränderte Dateien werden in Altium neu geladen. Danach folgt die Registry: eigene Bauteile
  (`generated`, `datasheet`) bekommen dieselbe Änderung im Spec (`symbol_spec_after`/`footprint_spec_after`, ihre
  Generatordaten bleiben), importierte werden neu gelesen; das Manifest markiert die Bauteile als PartForges mit
  unbekanntem Inhalt (spätere Schreibvorgänge ersetzen nur einzelne Bauteile). Die Regeln werden gemerkt
  (`pf_meta` `housestyle.rules`, `GET/PUT /api/housestyle/rules`). Ergebnis `components, libraries, skipped,
  errors, undo, report, message`.
* **Rückgängig** (`undo_last`, `GET /api/housestyle/undo` → `{created, libraries, file}` | `null`,
  `POST /api/housestyle/undo`, Job `libraries.conform`): der Undo-Datensatz
  `Backups\lib\stapelbearbeitung_<Zeit>_<hex>.json` (`pf_meta` `housestyle.last`) nennt Sicherungen und alte
  Registry-Einträge; wiederhergestellt werden nur Dateien, die seit der Stapelbearbeitung unverändert sind. Ein
  abgebrochenes Anwenden (Benutzer, Bibliothekswechsel) hinterlässt den Datensatz für alles bis dahin Geschriebene
  (der Eintrag entsteht direkt nach dem Schreiben einer Datei); ein teilweises Rückgängigmachen trägt die Registry
  der zurückgesetzten Dateien immer nach und behält im Datensatz nur, was sich später noch zurücksetzen lässt
  (gesperrt, in Altium geöffnet und geändert, nicht erreicht) – ist nichts mehr übrig, wird kein Rückgängig mehr
  angeboten.
* **Hausstil aus Beispiel** (`learnstyle.learn`, `POST /api/housestyle/learn {paths}` → `StyleProposal`, nichts wird
  gespeichert): liest Referenzbibliotheken (`.SchLib`, `.PcbLib`, `.IntLib`, `.zip`, Ordner) mit den Datensatz-Codecs
  und schlägt Hausschrift und -größe, Pinschrift, Pinlängen (Box-Symbole/andere), Farben, Lagen jeder Rolle,
  Linienbreiten, Textschrift und -höhe, Pin-1-Punkt und Courtyard-Kreuz vor – je Vorschlag mit Beleg und
  `differs`; `symbol`/`footprint`/`layers` sind vollständige, geprüfte Einstellungen. Die Einstellungsseite übernimmt
  die gewählten Vorschläge in den Entwurf.

## 9. Serien-Assistent (`partforge/domain/mpn`)

MPN-Vorlagen (Hersteller-Serien): Muster mit Platzhaltern (`CRCW{size}{value}{tolerance}{tcr}{packaging}`),
Codetabellen, Wertformate, Größenattribute und Gültigkeit als Regeln (Wertebereiche + E-Reihen je Baugröße),
Verfügbarkeitsmatrix (MLCC) oder Katalog; `resolve`/`encode_mpn`/`decode_mpn` (`engine.py`). Vorschau und
Erzeugen als Job (`domain/series.py`): Bauteile über `db.parts.upsert_parts` (Werte über `domain.units`, also
identisch zur Handeingabe), Footprints über `footprints.chip_request` + `sync.ensure_footprints`, Symbol über
`sync.ensure_symbols`. Eigene Vorlagen in `pf_mpn_templates`. Grundwahrheit im Korpus: Vishay CRCW, KEMET
C0G/X7R-Matrix, Bourns SRR1260.

* **Symbol – nie geraten**: der Symboltyp der Vorlage (Typen mit Pinbelegung brauchen `symbol_params["pinmap"]`
  oder eine aus Werten/Footprint sicher ableitbare Belegung), sonst `templates.resolve_default_symbol(Kategorie,
  Zeilenwerte, footprint=…)`; der Kategorie-Standardtyp allein gilt nur bei eigenen Kategorien und nur ohne
  Pinbelegung. Ohne sicheres Symbol (TO-92-Transistor, Doppel-MOSFET/-Transistor, IC …) sind alle Zeilen `invalid`
  („Symbol nicht sicher bestimmbar …“) und nichts wird geschrieben; ein festes `Library Ref` in `field_overrides`
  verwendet ein registriertes Symbol.
* **Status je Zeile**: `new`; `exists` = gleiche Teilenummer oder gleiche Hersteller-Teilenummer unter anderer
  Teilenummer in derselben Kategorie; `conflict` = Teilenummer bzw. MPN in einer anderen Kategorie oder für ein
  anderes Bauteil vergeben; `invalid`. MPNs werden über alle Kategorien in Kompaktform verglichen
  (`domain.mpn.compact`: ohne Leerzeichen/Bindestriche, Großbuchstaben – `ERJ-3EKF1002V` = `ERJ3EKF1002V`).
* **Modus** `skip` (vorhandene auslassen) oder `update`: aktualisiert vorhandene Bauteile, lässt aber `PF Status`
  immer und einen abweichenden Lebenszyklus, Datenblatt-Link, Symbol oder Footprint stehen – außer sie sind
  ausdrücklich angegeben (`field_overrides`, `datasheet_url`) bzw. `replace_links`; ein Lebenszyklus der Vorlage
  (z. B. NRND) ersetzt nur den Standard „Aktiv“. Generierte Texte erneuert `db.parts`, solange sie noch dem
  generierten Text entsprechen.
* Der Commit-Job (`routes_series.commit_job`) hält die Bibliothek, für die er gestartet wurde (§8.4); `series.commit`
  prüft zusätzlich vor jedem Schreiben selbst, ob sie noch offen ist.
* **Pflichtfelder** prüft die Vorschau wie `db.parts` beim Speichern, ohne die Felder, die für die Zeile nicht
  gelten (`values.not_applicable`). **0-Ω-Brücken** speichern 0 Ω und in `Notes` Maximalwiderstand und Nennstrom
  der Baugröße („0-Ω-Brücke (Jumper) ≤ 20 mΩ, Nennstrom 2A“, Größenattribut `jumper_current`); Toleranz, TK,
  Leistung und Spannung bleiben leer (Datenblätter bewerten Brücken nur mit Rmax und Nennstrom, §4). Andere leere
  Pflichtfelder machen auch eine Brückenzeile `invalid`.
* **Nicht geschriebene Symbole/Footprints** (Datei gesperrt, in Altium geöffnet und geändert, kein Writer): nie
  „angelegt“ gemeldet. `SeriesCommitResult.library_problems` = `[LibraryProblem{kind: symbol|footprint, name,
  library, status: error|pending|missing, message, parts}]`; `footprints_created`/`symbol_created` zählen nur in die
  Datei Geschriebenes. Status `error`: die Zeilen mit diesem Symbol/Footprint werden **nicht** geschrieben (wie bei
  der Datenblatt-Übernahme) und zählen als `errors` („Nicht angelegt – Footprint „X“ konnte nicht geschrieben werden:
  …“ in `error_details`), dazu ein deutscher Satz in `warnings`; Status `pending` (kein Writer): die Bauteile entstehen,
  ein Satz in `pending` nennt „Bibliotheksdateien synchronisieren“. Die Schlussmeldung nennt sie („…, 1 Footprint
  nicht geschrieben“ bzw. „…, 1 Symbol ausstehend“).
* **Job-Fortschritt** (`series.commit`): jede Phase ist eine Logzeile („Serie wird berechnet …“, „Serie berechnet:
  1.260 Zeilen – 1.248 neu, 12 vorhanden.“, „Symbol „Resistor“ wird angelegt …“ bzw. „… wird geprüft …“ (schon
  registriert), „3 Footprints werden angelegt (5 vorhanden) …“ bzw. „8 vorhandene Footprints werden geprüft …“ –
  „angelegt“ zählt nur noch nicht registrierte –, „Sicherung wird angelegt …“, „1.248 Bauteile werden gespeichert …“)
  und `job.detail` =
  `SeriesCommitDetail{phase: plan|symbol|footprints|backup|parts|done, done, total}` (Zähler der Footprints bzw.
  Bauteile, nie rückwärts). Abschluss in `job.message` und `result.message`: „Serie erzeugt: 1.248 neu,
  12 aktualisiert, 0 übersprungen, 6 Footprints neu“ (+ „2 unverändert“, „1 Fehler“, „(nicht geschrieben:
  3 ungültig, 1 Konflikt)“ wenn vorhanden; Zahlen mit Tausenderpunkt, `text.plural`); ohne schreibbare Zeilen
  „Serie: nichts zu schreiben – 12 bereits vorhanden.“. Ergebnis `job.result` = `SeriesCommitResult` (pydantic,
  in OpenAPI über `POST /api/series/commit` → `SeriesJobOut.job: SeriesJobSnapshot{result, detail}`).
* **Vorschau** (`SeriesPreview`): zusätzlich `skipped_by_size {Baugröße: Anzahl}`, `skipped_total`,
  `skipped_reason` (deutsch, z. B. „Laut Datenblatt nur in anderen Toleranzen lieferbar“) für Werte der gewählten
  Reihe/des Bereichs, die keine Zeile ergeben. `FootprintRef.plain_name`/`name_reason`: trägt ein Footprint-Name
  eine Eindeutigkeitskennung (`CAPC1608X90N_4328`), sagt `name_reason` warum (Bauteilhöhe ohne passende
  Standard-Höhenklasse, Höhe „Exakt“, Gehäusemaße laut Datenblatt, Herstellerempfehlung als Land Pattern) – je
  Footprint einmal in `footprints`/`footprints_needed`; die Zeilen tragen nur `plain_name`.
* **Katalog-Einträge** dürfen eigene Attribute `datasheet_url` (Link je Bauteil, sonst der der Vorlage; ein
  angefragter `datasheet_url` gewinnt), `lifecycle` und `row_note` (Hinweis der Zeile) tragen. Ein Katalog mit
  Muster liest auch die Verpackungsvariante eines Katalogtyps als gültig (`…KA93J` zu `…KA93D`, Gurtart muss passen).
* **Vorlagen-Karten** (`GET /api/series/templates`, `domain/mpn/examples.py`): je Vorlage `example`
  (`TemplateExampleOut`: Beispiel-Teilenummer für 10 kΩ/100 nF/10 µH in 0603 bzw. der mittleren Baugröße,
  Kondensatoren bevorzugt 50 V, Kataloge bevorzugt Typen in Produktion, `segments` [{text, kind
  literal|size|value|code, name, label, short, meaning}],
  `description`, `valid`/`message`/`missing_fields` aus der Pflichtfeldprüfung gegen die Kategorie der offenen
  Bibliothek bzw. ohne Bibliothek gegen die eingebaute), `mode` (rules|matrix|catalog|open), `value_range`,
  `e_series`, `jumper`, `sources`. Das Beispiel wird je Vorlagenobjekt einmal berechnet (eingebaute: einmal).
* **Vorlagentest** (`POST /api/series/templates/test`): je Beispiel zusätzlich `missing_fields`, `not_applicable`,
  `values` (wie die Serie speichern würde, `series.sample_check`) und in der Antwort `category_checked`/`category_note`.
* **Murata GRM X7R** (Katalog, 28 Typen 0402 … 1210) ist geprüft: Teilenummernschlüssel aus Murata „Part
  Numbering“ (pim.murata.com), jeder Typ gegen die Murata-Produktdatenbank (Stand 08.10.2026: Maße, Kapazität,
  Spannung, Verpackung, Lieferstatus; „To be discontinued“ → Lebenszyklus „Abgekündigt“ mit Nachfolger). Alle
  eingebauten Vorlagen sind damit `verified`.

## 10. Datenblatt-Import (`partforge/datasheet`)

PDF speichern (`Datasheets/<Name>_<sha8>.pdf` + `pf_datasheets`), Textebene prüfen, Seiten rendern
(pypdfium2), relevante Seiten wählen, Claude-Extraktion (Standard `claude-opus-5-5`, `effort: low`, Structured
Output, PDF-Teilmenge als Dokument mit `cache_control`, Prüfung mit 200-dpi-Bildern), Normalisierung, Vorschlag
(Kategorie, Werte je Variante, Symbol, Footprints je Gehäuse über `request_from_package`, Warnungen), Übernahme
als Job (Symbole/Footprints über `altium.sync`, Bauteile über `upsert_parts`). Kostenanzeige je Import; der
Claude-Client ist für Tests austauschbar (`set_client_factory`) und im Wiedergabemodus durch Aufzeichnungen ersetzt
(`replay.py`, §11). Pakete laden pypdf/pypdfium2/Anthropic-SDK erst bei Bedarf. Module: `store` (PDFs, Records,
Renders, gesicherte Ergebnisse), `pdf`, `pages` (Seitenauswahl), `llm` (einziger SDK-Zugang), `replay`, `costs`,
`schema`/`prompts`, `extract` (Analyse-Job), `normalize`/`merge`/`evaluate`, `proposal` (Vorschlag/Übernahme),
`combine` (Gehäuse aus einem anderen Datenblatt), `estimate` (Kostenschätzung), `find` (Datenblatt suchen), `search_costs` (Kosten der Suchen), `labels` (Modellnamen,
Gründlichkeit, Beträge). Seitenbilder und Textebenen liegen im lokalen App-Cache (`store.cache_root`:
`%LOCALAPPDATA%\PartForge\Cache\datasheets\<id>`, höchstens 512 MB; mit `PARTFORGE_HOME` dort unter
`cache\datasheets`) – nie im servergespeicherten Profil; der Cache älterer Versionen unter
`%APPDATA%\PartForge\cache\datasheets` wird einmal entfernt.

* **Kosten**: jede bezahlte Claude-Anfrage wird sofort als `RunInfo` gespeichert, auch wenn ihre Antwort unbrauchbar
  war (`RunInfo.error` = deutscher Grund, z. B. „Antwort abgeschnitten“) oder die Analyse scheitert bzw. abgebrochen
  wird (`DatasheetMeta.last_error`); `cost_usd` summiert alle Anfragen des Datenblatts. Auch die Anfrage, die beim
  Abbrechen gerade läuft, ist bezahlt: beide Clients melden sie als `llm.RequestCancelled` (ein `JobCancelled`) mit
  `partial` = geschätzte Kosten bis zum Abbruch (`llm.partial_response`: Eingabe wie zu Beginn der Antwort berechnet,
  Ausgabe aus den gestreamten Zeichen, jede begonnene Websuche) – gespeichert mit `RunInfo.error` =
  `llm.CANCELLED_RUN_ERROR` („Abgebrochen – Kosten bis zum Abbruch geschätzt.“).
* **Werte aus dem Datenblatt** (`normalize.normalize_parameters`): Datenblätter sind englisch formatiert – eine
  Kommagruppe („2,000 pF“, „32,768 Hz“) ist ein Tausendertrennzeichen (`values.normalize_cell(thousands=True)`, nie
  das deutsche Dezimalkomma); die Lesart steht als Hinweis in `ParameterData.warning` („„2,000 pF“ mit Komma als
  Tausendertrennzeichen gelesen: 2nF.“) und im Log. Das Schema bittet Claude um Zahlen ohne Tausendertrennzeichen.
  Vom Benutzer korrigierte Werte (`PUT …/extraction`) gelten als Handeingabe (`thousands=None`: mehrdeutig → Warnung).
* **Metadaten** (`DatasheetMeta` im Record): jede Änderung ist Lesen-Ändern-Schreiben unter der Sperre des
  Datenblatts (`store.meta_lock`/`store.update_meta`, Record wird darin neu gelesen) – gleichzeitige Jobs (Lesen,
  Analyse, Übernahme, gesicherte Ergebnisse, Suchkosten) überschreiben sich nie; ein gelöschtes Datenblatt legt kein
  später Schreibender neu an.
* **Land Pattern**: eine Herstellerempfehlung (`LandPatternData`) nur aus einer Zeichnung im Datenblatt, mit dem
  Bezug des Reihenabstands (`row_spacing_reference`: Mitte–Mitte, Innen- oder Außenkanten, Bauteilmitte–Padmitte =
  halber Abstand, wird verdoppelt; `unclear` = Mitte–Mitte mit Hinweis). `to_override()` übergibt sie an
  `request_from_package(land_pattern=…)`; unvollständig → Warnung und IPC-Berechnung.
* **Vorschlag** (`build_proposal`, schreibt nichts): Fehler-Prüfungen des gewählten Bauteils/Gehäuses und Pins ohne
  Pad bzw. Pads ohne Pin sind `PartProposal.blockers` – `ready` und die Übernahme erst, wenn der Benutzer **jeden**
  bestätigt: `ProposalChoices.accept_issues` = Liste der bestätigten Blocker-Texte (Leerraum egal; `true` = alle,
  veraltet); offene stehen in `PartProposal.unconfirmed_blockers`. Ein erzeugtes Symbol, dessen Name schon mit
  anderer Pinbelegung registriert ist, bekommt einen freien Namen (`taken_name`), außer der Benutzer bestätigt die
  neue Belegung für dieses Symbol (`allow_pin_changes` = `true` oder Liste der Symbolnamen → `pin_changes`, die
  Übernahme ruft `sync.ensure_symbols(allow_pin_changes=True)` nur für diese Symbole; alle Bauteile mit dem Symbol
  ändern sich). `SymbolProposal.taken_changes` = Pinbelegungs-Unterschiede zum registrierten Symbol des erzeugten
  Namens, strukturiert je Pin (`PinoutChange {pin, old_name, new_name, old_type, new_type, old_part, new_part}`, Namen
  in Überstrich-Syntax – die Oberfläche zeichnet sie; `null` auf einer Seite = Pin dort nicht vorhanden bzw. bei einem
  registrierten Symbol ohne Geometrie unbekannt; leer = kein Konflikt), `usage` = Bauteile, die es verwenden – die
  Oberfläche liest keine Warnungstexte. Warnungen und `pin_changes` nennen Pinnamen lesbar (Überstrich als U+0305,
  `proposal.readable_pin_name`: „C̅S̅“, nie „C\S\“). `PartProposal.blocker_targets` = je Blocker (gleiche Reihenfolge
  und Text wie `blockers`) `BlockerTarget {blocker, package, pins, pads}`: Gehäusecode, Symbol-Pins ohne Pad bzw.
  Footprint-Pads ohne Pin (leer bei Prüfungen des ganzen Bauteils) – zum Hervorheben ohne Textauswertung. Pads, die
  das Datenblatt als NC kennzeichnet und für die ein erzeugtes Symbol keinen Pin hat, stehen in
  `SymbolSpec.generator["nc_pads"]` (natürliche Reihenfolge; nur wenn vorhanden) – die Dateiprüfung
  (`sync.library_health`, `pin_pad_mismatch`) wendet damit dieselbe Regel an wie der Vorschlag. Vorhandene Bauteile findet
  der Vorschlag über `parts.find_by_mpn` (alle Kategorien, MPN ohne Leerzeichen/Bindestriche, Groß-/Kleinschreibung
  egal). `PartProposal.fingerprint` (16 Hex-Zeichen) = Hash über Auswahl (ohne `accept_issues`/
  `expected_fingerprint`), Blocker und Plan (Namen, Schreibentscheidungen, Pinänderungen, Geometrie-Hash, Zeilen mit
  Werten, Datenblatt-Link; ohne SVG).
* **Übernahme** (`commit_proposal`, Job `datasheet-commit`): hält die Bibliothek (§8.4), baut den Vorschlag neu und
  schreibt fehlende Symbole/Footprints und die Bauteile; Bauteile, deren Symbol oder Footprint nicht geschrieben
  wurde, werden nicht angelegt (`errors`). Sie verweigert (Job `failed`, `CommitRefused`, nichts geschrieben), wenn
  Blocker nicht bestätigt sind (`detail.code = "unconfirmed_blockers"`, `detail.unconfirmed_blockers`, die Meldung
  nennt sie) oder der neu gebaute Vorschlag nicht dem geprüften entspricht (`ProposalChoices.expected_fingerprint` ≠
  `fingerprint`: `detail.code = "proposal_changed"`, `detail.fingerprint`, `detail.expected_fingerprint`); bei
  anderen Problemen `CommitRefused` mit `code = "invalid"`. Schritte `detail.step` =
  `check|footprints|symbols|parts|save`, Ergebnis + `fingerprint` und `message` („Angelegt: 3 Bauteile, 1 Symbol,
  2 Footprints“).
* **Nur Symbole / nur Footprints** („Einzeln speichern“): `ProposalChoices.scope` = `part` (Standard) | `symbols` |
  `footprints` – zählt wie `accept_issues` nicht zum Fingerabdruck (ein geprüfter Vorschlag gilt für jeden Umfang).
  Die Übernahme schreibt dann nur diese in ihre SchLib/PcbLib, legt keine Bauteile an und braucht nur diesen Umfang:
  `PartProposal.ready_symbols`/`ready_footprints` = alle Symbole bzw. Footprints gültig, mindestens einer zu schreiben
  (sonst `CommitRefused` „Nichts zu speichern …“), kein unbestätigter Blocker dieses Umfangs.
  `BlockerTarget.scopes` sagt je Blocker, was er sperrt: immer `part`; Pintabellen-Prüfungen (`IDENTITY_ISSUES`) auch
  `symbols`, Zeichnungsprüfungen (`GEOMETRY_ISSUES`) auch `footprints`, `pin_count` und unbekannte Fehler beides, Pins
  ohne Pad nur `part`. Schritte `check|symbols|save` bzw. `check|footprints|save`, `detail.scope`; Ergebnis mit
  `scope`, `libraries` (geschriebene Dateien) und `message` „Gespeichert: 1 Symbol“; `CommitInfo.scope`. Ein Datenblatt
  ist „übernommen“ erst nach einer Übernahme mit Bauteilen (eine Gehäusezeichnung: nach dem Speichern ihrer
  Footprints); `DatasheetOut.saved_symbols`/`saved_footprints` nennen die einzeln gespeicherten.
* **Gehäusezeichnung ohne Bauteil** (z. B. TIs eigenes PDF „RGY0019B“): Ohne Bauteil, aber mit Zeichnung
  (`PackageData.has_geometry`: ein Maß oder eine Herstellerempfehlung) meldet die Prüfung nur `package_only` (info) –
  nie `no_device` (Fehler mit Nachkontrolle; dabei hatte Claude ein Platzhalter-Bauteil erfunden). Die
  Identitätsanweisung verlangt dafür eine leere Bauteilliste. Der Vorschlag hat `package_only`, `device = ""` und je
  gezeichnetem Gehäuse einen Footprint; „Bauteil anlegen“ lehnt ab, „Footprint speichern“ (`scope = footprints`) geht.
  `DatasheetOut.package_only` kennzeichnet sie in der Liste.
* **Gehäuse aus anderem Datenblatt** (`combine.py`; `GET …/{id}/package-sources?package=` → `PackageSource[]`,
  `GET …/{id}/package-targets?package=` → `PackageTarget[]`, `POST …/{id}/merge-package {package, source_id,
  source_package}` → `MergeOut` = `ExtractionOut` + `notes`, `POST …/{id}/unmerge-package {package}`): übernimmt
  Familie, Anschlusszahl, Montage, Outline, Exposed Pad (Flag und Nummer), Zeichnungsseiten, Maße, Herstellerempfehlung
  und Anschlussanordnung in ein Gehäuse des Bauteil-Datenblatts; Code und Name bleiben (Varianten und Pintabellen
  verweisen darauf). `PackageData.origin` (`PackageOrigin`: Datenblatt, Gehäuse, Dateiname, Titel, Zeitpunkt,
  `replaced` = das Gehäuse vor der ersten Übernahme als `PackageBase` – keine rekursiven Schemas) – seine Seiten sind
  Seiten des **anderen** PDFs (die Oberfläche zeigt sie dort, nicht in der PDF-Spalte). Gespeichert wie eine Korrektur
  (`store_edited_extraction` unter `meta_lock` des Ziels, `edited`); eine neue Analyse ersetzt sie. Ein übernommenes
  Gehäuse ist nie selbst Quelle. Kandidaten nach Passung (gleiche Anschlusszahl, Code-Präfix `RGY` → `RGY0019B`,
  Name, Familie, Exposed Pad, Hersteller, Gehäusezeichnung bzw. fehlende Maße) mit deutschen `matches`/`problems`.
* **Anschlussanordnung** (`PackageData.layout` = `TerminalLayout {pins_x, pins_y, pitch_x, pin1, missing}`, in der
  Prüfansicht eingetragen): `proposal._family_params` gibt sie als `pins_x`/`pins_y`/`e_x`/`pin1`/`missing` an den
  Generator (§6), soweit die Familie sie kennt. `LandPatternData.row_spacing_y` = Reihenabstand oben/unten der
  Herstellerempfehlung (`row_spacing_y_mm`).
* **Fortschritt** (`job.detail` der Jobs `datasheet`): `step` (stabile Kennungen `download` (URL-Import), `read`,
  `select_pages`, `identity`, `geometry`, `check`, `save`), `step_label` (deutsch), `steps` (Schritte dieses Jobs),
  `datasheet_id` (beim URL-Import, sobald das PDF gespeichert ist), `pages_total`, `pages_selected`, `pages_active`
  (Seiten der laufenden Anfrage bzw. der Kontrolle mit Seitenbildern), `counters` (`mpns`, `pins`, `parameters`,
  `packages`, `dimensions`; live aus der gestreamten Antwort), `cost_usd` (laufend), `budget_usd`, `model_label`
  („Claude Opus 5.5 · Gründlichkeit niedrig“, `labels.run_label`). Die deutschen Logzeilen bleiben; Meldungen nennen
  Modelle nur mit Namen (`labels.model_label`) und die Stufe als „Gründlichkeit“ (niedrig/mittel/hoch – derselbe
  Begriff wie in Einstellungen › KI; nie „Aufwand“).
  Schlussmeldungen: „Analyse fertig: 14 Bestellvarianten, 13 Pins, 2 Gehäuse – 0,23 $“ (Beträge `labels.usd`),
  „Datenblatt gelesen: 25 Seiten, davon 4 ohne Textebene“, „Heruntergeladen: X.pdf (12 Seiten)“ bzw. „Bereits
  vorhanden: …“; Ergebnis der Analyse zusätzlich `model_label`, `stored` (`library|pending`), `message`.
* **Kostenschätzung** (`POST /api/datasheets/{id}/estimate`, Körper wie `/extract`: `pages`, `model`, `effort`,
  `triage`, `vision`, `max_cost_usd` …; `estimate.estimate`, keine Claude-Anfrage): dieselbe Seitenauswahl wie die
  Analyse (ohne Triage-Ergebnis), Aufteilung auf beide Durchgänge, `costs.estimate_pdf_tokens` je
  Text-/Zeichnungsseite, Eingaben als Cache-Schreiben bepreist → `pages`, `pages_total`, `selection_method`,
  `identity_pages`, `geometry_pages`, `drawing_pages`, `triage`, `est_input_tokens`, `est_cost_usd_low`,
  `est_cost_usd_high`, `model`, `effort`, `model_label`, `budget_usd`, `exceeds_budget`; „low“ = typische Antworten,
  „high“ = lange Antworten + eine Kontrolle mit Seitenbildern (mit `vision: "off"` ohne). Ein noch nicht gelesenes
  Datenblatt wird vorher gelesen.
* **Bibliothekssperre** (§8.4): Lesen, Analyse und URL-Import halten ihre Bibliothek nur kurz
  (`library_hold(None, root)`): Eintrag lesen, Seitenanalyse/Kategorien (die Textebene wird vorher ohne Sperre
  gelesen und im App-Cache abgelegt), PDF speichern, Ergebnis speichern. Ist die Bibliothek beim Start schon
  gewechselt, endet der Job `cancelled` ohne bezahlte Anfrage. Ist sie beim Speichern nicht mehr offen, landet das
  Ergebnis (bzw. die Kosten einer gescheiterten Analyse) als `PendingResult` in
  `<Datasheets>/.pending/<id>_<Zeit>.json` ihres Ordners (`store.save_pending`); beim nächsten Öffnen dieser
  Bibliothek (Lifespan des Datasheet-Routers: Ereignis `WORKSPACE_OPENED` und die beim Start offene Bibliothek;
  zusätzlich `GET /api/datasheets`) übernimmt `store.apply_pending` sie – einmalig (gleiche Anfragen werden nicht
  doppelt gezählt), eine neuere Analyse bleibt; zu gelöschten Datenblättern bleibt die Datei als `*.orphan`. In eine
  andere Bibliothek wird nie geschrieben.
* **Datenblatt suchen** (`POST /api/datasheets/find` `{query, manufacturer?, model?}` → Job `datasheet-find`,
  `find.run_find`, braucht keine offene Bibliothek; 503 `{code, message}` ohne KI, 400 bei zu kleinem Kostenlimit):
  eine Claude-Anfrage (`settings.ai.model`, Gründlichkeit `low`) mit dem neuesten Websuch-Werkzeug des SDK
  (`web_search_20260318`, `allowed_callers: ["direct"]`, höchstens 3 Suchen) und Structured Output (VERIFIED
  2026-10-08: zusammen mit der Websuche angenommen, ohne Zitat-Blöcke; lehnt die API das je ab, folgt einmal dieselbe
  Anfrage ohne Format, der Prompt verlangt dasselbe JSON); `pause_turn` wird fortgesetzt (höchstens 3-mal, Inhalt
  unverändert zurück). Kosten: Token + 10 $ je 1.000 Suchen (`costs.server_tool_cost`), Grenze
  `min(max_cost_per_import_usd, 0,50 $)` über `max_uses`/`max_tokens`. Kandidaten (höchstens 5): Domain-Einordnung
  `hersteller|distributor|andere` (Herstellerseiten bevorzugt), PDF-Prüfung je Link mit kleinem Range-GET
  (`find.probe_pdf`: nur http/https, Timeouts, höchstens 16 KB, keine Loopback-/privaten/Link-Local-/reservierten
  Adressen – auch nicht nach Weiterleitungen oder als verbundene Gegenstelle, außer hinter einem Proxy der
  Umgebung; nicht auflösbare Hosts werden nicht kontaktiert; gesperrte Links fallen weg). Findet Claude kein
  Hersteller-PDF, prüft PartForge die stabile Datenblattadresse bekannter Hersteller (`find.DATASHEET_PATTERNS`,
  z. B. `ti.com/lit/ds/symlink/{teil}.pdf`) und bietet sie nur an, wenn dort ein PDF liegt (`derived: true`).
  Ergebnis: `query`, `manufacturer`, `candidates` (je `url`, `title`, `manufacturer`, `part_numbers`, `source`,
  `is_pdf`, `size_bytes`, `note`, `check`, `final_url`, `in_search_results`, `derived`), `cost_usd`, `searches`,
  `note`, `model`, `model_label`, `structured`, `runs`, `message` (Reihenfolge der Kandidaten: PDFs zuerst, darin
  Hersteller vor Distributor vor anderen). Der Benutzer wählt einen
  Kandidaten → normaler URL-Import; mit `search_job_id` rechnet er die Suchkosten einmalig dem Datenblatt zu
  (`attached_to` im Suchergebnis). **Suchkosten gehen nie verloren**: jede Suche mit bezahlten Anfragen – fertig,
  gescheitert oder abgebrochen (die laufende Anfrage mit ihren geschätzten Kosten) – steht mit ihrer Job-ID im
  Kostenprotokoll `search_costs` (`<App-Daten>\ai\search-costs.json`, d. h. `%APPDATA%\PartForge\ai`, höchstens
  200 Suchen: `job_id`, `query`, `manufacturer`, `status` `done|failed|cancelled`, `created`, `runs`, `cost_usd`,
  `message`, `attached_to`); eine gescheiterte oder abgebrochene Suche meldet ihre Kosten in `detail.cost_usd` und
  im Log, eine abgebrochene endet mit „Suche abgebrochen – bisherige Kosten 0,046 $ gespeichert.“. Der URL-Import
  rechnet die Kosten über das Protokoll zu (`search_costs.claim`: einmal, nur `done`) – auch nach einem Neustart oder
  wenn die Jobliste den Job nicht mehr kennt.
* **KI-Status/Test**: `GET /api/ai/status` → `key_configured`, `key_source` (`env|stored|file|replay|null`,
  `llm.key_status`), `model_label`, `fast_model_label`; `POST /api/ai/test` → `model_label`, Fehler als
  `{code, message}` (`AiUnavailable.code`: `map_sdk_error` – 401 `key_rejected`, 403/404 `model_unavailable`, 429
  `rate_limited`, Zeitüberschreitung/keine Verbindung/5xx/529 `network`; `get_client` ohne Schlüssel `key_missing`,
  KI aus `ai_disabled`).

## 11. Tests

* `pytest` (`tests/conftest.py`): isoliertes `PARTFORGE_HOME`, Fixtures `workspace`, `client`, `bare_client`;
  Marker `altium` (`PARTFORGE_TEST_ALTIUM=1`), `rustwriter` (Standard: an, wenn die EXE existiert), `ai`
  (`PARTFORGE_TEST_AI=1`), `slow`, `library_job`.
* Jedes Modul bringt eigene Tests mit (`tests/test_<modul>_*.py`); modulübergreifende Abläufe ohne Altium in
  `tests/test_integration_*.py` (Beispielinhalte gegen Generatoren, Writer-Validierung und Pin/Pad-Prüfung,
  Standardsymbole der Kategorien und ihre Migration beim Öffnen, ein Formatierungspfad für Werte mit
  Idempotenz-Fuzzing, Bibliothek anlegen + Job, Bibliothekswechsel während des Schreibens, Synchronisierung mit
  einem Writer im Speicher und mit dem echten Rust-Writer, typisierte Verträge).
* Kein Hintergrund-Writer in Tests: ein autouse-Fixture ersetzt `routes_system.start_library_sync` durch einen
  sofort beendeten Job (`done`, `{"skipped": true, …}`; die Beispiele bleiben `pending`), außer der Test trägt den
  Marker `library_job` (alle Tests in `test_integration_workspace.py`, die den Job selbst prüfen). Tests, die über
  die API eine Bibliothek mit Beispielen anlegen, senden trotzdem `"write_libraries": false`, wenn sie keinen Job
  brauchen.
* Bibliothekssperre: `tests/test_jobs_library_guard.py` (Semantik) und `tests/test_guard_*.py` (jede Job-Art der
  API hält ihre Bibliothek, Wechsel brechen ab und warten, 409, nie in eine andere Bibliothek; Serien-Symbol nie
  geraten; Import zurückgerollt, Export ohne Sperre sauber beendet).
* Integrität der Bibliotheksdateien: `tests/test_rustwriter_integrity.py` (Arbeitskopie, getöteter Prozess, zwei
  Prozesse auf einer Datei, gesperrte Datei, übrig gebliebene STEP-Träger), `tests/test_library_integrity_sync.py`
  (beschädigte Datei: Befund, Prüfen, Wiederherstellen; fehlende `ok`-Einträge; Manifeste nach einer
  Datenbanksicherung), `tests/test_compound_cleanup.py` (keine Patch-Kopien nach COM-Fehlern, fehlendes
  `win32timezone`).
* Jobs: `tests/test_jobs_snapshots.py` (Kurzform großer Ergebnisse, `detail`, `cancel_reason`, Schlussmeldungen
  und Sicherheitsnetz, Fehlertexte), `tests/test_jobs_api.py` (Joblisten und SSE mit/ohne `brief`),
  `tests/test_system_libraries_job.py` (Schlussmeldungen von „Bibliotheken schreiben“).
* Sicherheit (§2.1): `tests/test_api_security.py` (Host-Prüfung inkl. 421 ohne Token, Cross-Site-403, SPA-Token nur
  für eigene Navigationen – `cross-site`/`same-site`/iframe → 403-Seite ohne Token und Query –, Rahmenverbot an jeder
  Antwort, Pfad- und Schlüsseldatei-Prüfung, Token-Schwärzung; live: echter uvicorn-Server mit Absolut-Form-Zielen für
  httptools und h11, `python -m partforge --server-only --verbose` ohne Token in `partforge.log` und Konsole),
  `tests/test_api_export_safety.py` (CSV-Schutz, verlustfreier Rundweg, XLSX-Text); Frontend
  `frontend/tests/altium.unit.test.mjs` (Aktionen der Altium-Seite nur als Router-State, kein `?aktion=` im Code).
  `tests/conftest.py` setzt `PARTFORGE_TEST_HOSTS=testserver` für den `TestClient`, entfernt ein aus der Shell geerbtes
  `PARTFORGE_AI_REPLAY_DIR` (Tests des Wiedergabemodus setzen es selbst) und stellt `settings.json` nach jedem Test
  wieder her (autouse `_restore_app_settings`).
* Live-Tests (`altium`) teilen ein festes Austauschverzeichnis `tests/_tmp/altium-live/exchange` (ein Skriptprojekt
  für alle Läufe statt eines je Test, nie das Verzeichnis des Benutzers).
* **Wiedergabemodus für Tests und Demos** (`partforge/datasheet/replay.py`): `PARTFORGE_AI_REPLAY_DIR=<Ordner>`
  (z. B. `tests/data/ai_fixtures`) – **nur zusammen mit `PARTFORGE_HOME`**, im echten Programm des Benutzers nie –
  lässt `llm.get_client` aufgezeichnete Antworten statt der Claude-API liefern, ohne jeden Netzzugriff: Analysen
  über die Aufzeichnung, deren `sha256[:16]` die Datenblatt-ID ist (`<Ordner>/*.json`), Datenblattsuchen über
  `<Ordner>/find/*.json` (Schlüssel: normalisierte Suchanfrage, `replay.search_key`) samt ihrer PDF-Prüfungen
  (`probes`) und der beim Import zu liefernden Dateien (`downloads`: URL → Datei relativ zur Aufzeichnung; andere
  Adressen werden im Testmodus nicht heruntergeladen). Fehlt eine Aufzeichnung, gibt es eine klare deutsche Meldung
  („Testmodus (PARTFORGE_AI_REPLAY_DIR): Für dieses Datenblatt … keine aufgezeichnete Analyse“, 503 bzw. Job-Fehler),
  nie eine echte Anfrage. `PARTFORGE_AI_REPLAY_SPEED` = Sekunden je gestreamtem Abschnitt (Standard 0; dreifach vor
  dem ersten, Abbruch wirkt sofort), damit UI-Tests die Analyse verfolgen können. `/api/ai/status` meldet
  `key_configured: true`, `key_source: "replay"`, `GET /api/settings` ebenso (`ai_key_configured`, `ai_key_source`;
  beide über `llm.key_status`); `/api/ai/test` antwortet „OK“ (0 $). Ein Testfactory-Client
  (`set_client_factory`) hat Vorrang. Beispiel (Umgebung): `PARTFORGE_HOME=…\tests\_tmp\home-ui`,
  `PARTFORGE_NO_ALTIUM=1`, `PARTFORGE_AI_REPLAY_DIR=…\tests\data\ai_fixtures`, `PARTFORGE_AI_REPLAY_SPEED=0.3`,
  dann `python -m partforge --server-only`.
* Aufzeichnungen: `llm.RecordingLlmClient` (nur Antworten, nie Schlüssel oder PDF); eine Datenblattsuche zeichnet
  `python -m partforge.datasheet.find --record <Suche> --manufacturer <Hersteller> --out <Datei>` auf (eine echte,
  bezahlte Anfrage – in isolierten Läufen nur mit `PARTFORGE_ALLOW_REAL_AI=1`; verschlüsselte Suchinhalte werden
  entfernt), `--refresh-probes <Datei>` erneuert nur die PDF-Prüfungen (keine Claude-Anfrage). Vorhanden:
  `tests/data/ai_fixtures/find/opa656.json` (OPA656, Texas Instruments, 2026-10-08, 0,09 $).
* Datenblatt-Tests: `tests/test_datasheet_find.py` (Suche, PDF-Prüfung mit `httpx.MockTransport` und falschem DNS),
  `test_datasheet_replay.py`, `test_datasheet_guard.py` (Wechsel während einer bezahlten Analyse, gesicherte
  Ergebnisse), `test_datasheet_progress.py` (`detail`, Schlussmeldungen, Namen, Kostenschätzung).
* Tests schreiben nur unter `tmp_path` oder `tests/_tmp`; nie Benutzerdaten unter `C:\PartForge-Examples\Altium_Libs` oder
  die echten Einstellungen. Netzwerk nur in Tests mit Marker `ai`.

## 12. Code-Stil

Python 3.13, `from __future__ import annotations`, vollständige Typannotationen, Pydantic v2, `logging` statt
`print`, deutsche Benutzertexte, englische Bezeichner/Kommentare, kleine Funktionen, keine Seiteneffekte beim
Import (schwere Abhängigkeiten und Generatoren werden in Funktionen importiert). Freitext für Altium immer über
`domain.text` bereinigen, Werte immer über `domain.units` formatieren.

Zeilenenden: alle Textdateien LF (`.gitattributes`: `* text=auto eol=lf`, Binärtypen `binary`), nur `*.cmd`/`*.bat`
CRLF (`Start-PartForge.cmd`). Generatoren schreiben LF auch unter Windows (`write_text(…, newline="\n")`, z. B.
`frontend/scripts/export_openapi.py`, `scripts/update_constraints.py`). Was Altium liest, schreibt PartForge selbst
mit CRLF – DbLib (cp1252/CRLF), Spezifikationen der Brücke und die Brückenskripte (`bridge.core.ensure_scripts`
schreibt die LF-Vorlagen aus `altium/bridge/scripts/` mit CRLF ins Austauschverzeichnis).

## 13. Programmpaket und Quellstart (`scripts/`)

* **Paketbau** `scripts/build.py` (braucht `pip install -e .[build]`: PyInstaller, python-markdown): Frontend (`npm run build`, außer mit
  `--no-frontend`), Versionsressource aus `partforge.__version__` (`version_file_text`: Datei- und Produktversion
  `1.0.0.0`, Produktname, Beschreibung, Firma, Copyright aus `LICENSE`), PyInstaller onedir/windowed mit
  `HIDDEN_IMPORTS` – u. a. `win32timezone`: pywintypes wandelt die FILETIMEs von `IStorage.EnumElements`
  (`altium/compound.py`) über einen C-Import in Datumswerte, den PyInstaller nicht sieht; ohne ihn scheitern im
  Paket alle PcbLib-Lagen- und Bauhöhen-Patches –, `--collect-submodules`/`--collect-data partforge` (keine
  `.py`-Quellen im Paket), `EXCLUDE_MODULES` (pytest, Pygments, setuptools, pdfminer, pdfplumber) und
  `PYTHONPATH=<Repo>` für PyInstallers Unterprozesse. Ins Paket kommen außerdem `README.md` (=
  `docs/handbuch/README.md`, das Handbuch ohne Repo-Links; sein Link `BEDIENUNG.md` zeigt im Paket auf
  `Handbuch/Bedienung.html`), `LICENSE`, `THIRD_PARTY_NOTICES.md`, `CHANGELOG.md`, `Start-PartForge.cmd`,
  `THIRD_PARTY_LICENSES.txt` und die **Bedienungsanleitung** `Handbuch/Bedienung.html` mit `Handbuch/bilder/`
  (`build.write_manual`: `docs/handbuch/BEDIENUNG.md` mit python-markdown – Extra `build` – als eigenständige
  HTML-Seite ohne externe Ressourcen, hell/dunkel nach Systemeinstellung, Überschriften-Anker wie bei GitHub
  (`#1-überblick`), Bilder als verlinkte Abbildungen mit Bildunterschrift; nur die gezeigten Bilder werden kopiert,
  ein fehlendes Bild oder ein toter Verweis lässt den Bau scheitern). Optional signiert (`--sign`, `--cert-sha1`,
  `PARTFORGE_SIGN_CERT_SHA1`, `PARTFORGE_SIGN_PFX` + `PARTFORGE_SIGN_PFX_PASSWORD`; signtool, SHA-256,
  RFC-3161-Zeitstempel, danach `signtool verify /pa`); zuletzt der Smoke-Test – jeder Fehler lässt den Bau
  scheitern (Exit-Code 1). Weitere Optionen: `--distpath`, `--workpath`, `--smoke-dir`, `--rust-writer`,
  `--no-smoke`.
* **Lizenzliste** `scripts/third_party.py`: Python = jede Distribution mit Dateien in `PYZ-00.toc`, `PKG-00.toc`
  oder `COLLECT-00.toc` (über ihr `RECORD` zugeordnet) mit ihren `License-File`-Texten und Hinweisen vendorter
  Teile; eine mitgelieferte Datei ohne Paket oder ein Paket ohne Lizenztext lässt den Bau scheitern
  (Ersatztexte: `scripts/licenses/` und `FALLBACK`). Dazu CPython (`LICENSE.txt` und „Licenses and
  Acknowledgements for Incorporated Software“ aus der installierten Doku) und das WebView2-SDK. Oberfläche = alle
  Nicht-dev-Pakete aus `frontend/package-lock.json` (Obermenge des Bundles) mit Lizenzdateien, verschachtelten
  Vendor-Lizenzen bzw. dem SPDX-Standardtext, dazu die Laufzeithilfen von Vite und Rolldown.
* **Smoke-Test** `scripts/smoke_test.py [Paketordner]` (auch einzeln aufrufbar) prüft den Paketinhalt (Oberfläche,
  Lizenzdateien, Versionsressource, Pflichtmodule im eingebetteten PYZ einschließlich `win32timezone` und aller
  Router, keine Entwicklungsmodule, keine `.py`-Quellen) und startet `PartForge.exe --server-only` isoliert
  (`PARTFORGE_HOME`, `APPDATA`, `LOCALAPPDATA` temporär, `PARTFORGE_NO_ALTIUM=1`, Claude nur im Wiedergabemodus):
  Oberfläche mit Token, Bibliothek mit Beispielen und Job „Bibliotheken schreiben“ ohne Warnung (mit Rust-Writer),
  PcbLib-Lagenkopf gleich dem Lagenaufbau, Bauhöhen > 0, keine Patch-Kopien `<stem>.pf…<hex8>.PcbLib`,
  Datenblatt-Analyse in der Wiedergabe (wenn der Korpus vorhanden ist), Protokolle ohne Traceback,
  `No module named` oder ERROR. Ergebnis: `SmokeResult` (`failures`, `notes`, `passed`).
* **Quellstart**: `Start-PartForge.cmd` startet im Programmpaket `PartForge.exe`, sonst bei **jedem** Start
  `scripts/bootstrap.py`. Die cmd ist reines ASCII mit CRLF und prüft jeden Interpreter vor der Benutzung
  (`py -3.13`, `py -3`, dann jedes `python` im PATH; Exit-Code 0 = ab 3.11, 1 = zu alt, sonst kein echtes Python,
  z. B. der Store-Platzhalter mit 9009). bootstrap: `.venv` anlegen bzw. neu anlegen, wenn sie nicht mehr startet;
  `pip install -e . -c constraints.txt`, sobald `.venv\.partforge-installed` nicht zum Hash von `pyproject.toml`
  und `constraints.txt` passt, danach Importprobe `partforge.app` (erst dann wird gestempelt); Oberfläche bauen
  (`npm ci` bei neuerer `package-lock.json`, dann `npm run build:nocheck` – die API-Typprüfung von `build` ist ein
  Entwicklungs-Wächter), wenn `partforge/web` fehlt oder `.venv\.partforge-frontend` (Hash der Frontend-Eingaben
  und mtime der gestempelten `index.html`) nicht passt – ohne Stempel gilt ein Build als aktuell, der neuer als
  jede Eingabe ist; scheitert der Bau, startet PartForge mit der alten Oberfläche und einem Hinweis; ohne Node.js
  bei veralteter Oberfläche ein einmaliger Hinweis. Start: Fenster über `pythonw` (abgekoppelt, 4 s beobachtet;
  ein vorzeitiges Ende wird mit Importprobe diagnostiziert – fehlt ein Paket, wird die Umgebung einmal neu
  installiert, sonst gemeldet), `--server-only`, `--dev`, `--help`, `--version` im Konsolenfenster. Läuft schon ein PartForge mit denselben Einstellungen
  (`instance.json` in `local_data_dir()` mit lebender PID, von `partforge.__main__`), wird nichts installiert oder
  gebaut. Fehler: `BootstrapError` mit deutschem Text und Lösungsweg, Exit-Code 1, nie ein Traceback.
* `constraints.txt`: die getesteten Versionen aus `.venv` (nach Paket-Updates `scripts/update_constraints.py`).
* Tests: `tests/test_packaging_build.py`, `tests/test_packaging_bootstrap.py` (mit echten `cmd.exe`-Szenarien,
  Marker `slow`), `tests/test_packaging_docs.py`.
