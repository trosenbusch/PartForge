# Altium E2E final: the user journeys through the real PartForge UI with a live Altium 26.10

Agent: E2E-live agent (exclusive use of the running Altium) · 2026-10-08, 19:30–20:45
Altium: `C:\Program Files\Altium\AD22\X2.EXE` **26.10.1.5** · PartForge 1.0.0 (production build in `partforge/web`, not rebuilt)
· Rust writer `altium-designer-mcp.exe` 0.1.0 · SQLite3 ODBC driver (64 bit) · installed Chrome (channel `chrome`) via
Playwright 1.63 (headless, 1480×940).

Every journey was driven **through the UI like a user** (clicks, typing, a real `DataTransfer` drop) and then cross-checked
in Altium: PartForge's own "In Altium prüfen" (batch resolve through the bridge), PartForge's bridge used read-only from a
script (`kit\bridge_resolve.py`, exact Unicode), and read-only altium-mcp sandbox scripts (lookups by DbLib **file name**
as placed parts do, hidden PcbLib/SchLib read-backs, one placement on a hidden scratch sheet).

Statements are tagged **[VERIFIED]** (observed in this run) or **[UNVERIFIED]** (inference or not testable here).

---

## 0. TL;DR

| Journey | Result | Key evidence |
| --- | --- | --- |
| J1 First run | **PASS** | `/willkommen` → „Neue Bibliothek anlegen“ (examples) → „Bibliotheken schreiben“ 15 symbols + 13 footprints in 14 files (job 3.6 s, UI 5.3 s) → Übersicht 100 %, 0 errors, 0 warnings |
| J2 Altium page | **PASS** | Altium läuft 26.10.1.5, Rust-Writer 0.1.0 aktiv, DbLib „Aktuell“ · install 4.5 s · „Alle 19 Bauteile“ **19/19 ok** in 8.0 s (1 Altium run, lookups 3.4 s) |
| J3 Serien-Assistent | **PASS** | YAGEO RC_L, 0402+0603, E24 1k…100k + 2 jumpers: 100 rows (97 new, 3 exist), commit 2.3 s; automatic refresh with index rebuild done 7.6 s after the commit; 2 keys asked for **before** they existed resolve afterwards; „Widerstände“ **101/101 ok**; health 0 errors |
| J4 Datenblatt-Import | **PASS** | PDF dropped on the window → analysis (replay) 7.0 s → review: **both pin tables equal the PDF's pin configuration (p. 2) pin by pin**, 0 blockers → 14 parts, 1 symbol, 1 footprint (3.8 s) → „Verstärker“ **16/16 ok**; Altium reads OPA656U pin 6 = OUT |
| J5 Datenblatt suchen | **PASS** | replay: 4 candidates (3 PDFs, TI first) → „Laden und analysieren“ → URL import „Bereits vorhanden“ → review of the existing analysis |
| J6 Bauteile | **PASS** (1 low finding) | inline edit Description + Value → Altium shows both (by file name); delete → Altium loses the record → „Rückgängig“ → resolves again; filter Baugröße 0402 → 50 parts „Lieferant 1 = Mouser“ → visible in Altium |
| J7 Footprint generator | **PASS** | custom QFN-24 4×4 e 0.5 → `QFN50P400X400X100-25N_5842` → new part → Altium: **25 pads, 26 3D bodies, Height 1.000 mm** |
| J8 Symbol generator | **PASS** | pin list 16 pins, „Anzahl 2“ → `E2E_DUAL16` (2 parts) + SOIC-16 → new part → verify ok; Altium SchLib: parts = 2, pins = 16 |
| J9 Placement | **PASS** | hidden scratch SchDoc: R1 and U1 placed, **Comment and Designator visible, all other parameters hidden**, footprints current; closed without saving, focus and Free Documents unchanged |
| J10 Robustness | **FAIL** (partly passed) | switch during a series job: cancelled correctly, but **the UI shows no cancel message** (F1); close/reopen ok; **moving library A failed – Altium kept its database open after the uninstall** (F3); the move works with library B (DbLib relocated, re-installed, 4/4 ok) |

**Findings** (§4): F1 (medium) no feedback after a library switch cancelled a job · F2 (medium) health warning
`pin_pad_mismatch` for every datasheet IC with NC pins · F3 (medium) Altium keeps the SQLite file open after
„deinstallieren“ – ≈ 60–90 s always, library A > 23 min – PartForge gives no hint, the folder cannot be moved · F4
(low/medium) a refresh of a not installed library acts on another library's installation of the same file name and
reports success · F5–F12 (low): stale component after delete, verify labels, false umlaut warning, job dock covers the
action bar, ambiguous template-card names, second library always collides on „PartForge.DbLib“, first-run toast noise,
wording „nicht lesbar“.

**Altium afterwards:** installed libraries, projects, document counts, focused project and Free Documents are
**identical to the baseline** (28/28 lines). One residue that only an Altium restart removes: X2.EXE still holds
`tests\_tmp\ws-e2e-live\PartForge.sqlite` (F3).

---

## 1. Setup and isolation

| Item | Value |
| --- | --- |
| Server | `python -m partforge --server-only --port 8851` with `PARTFORGE_HOME=tests/_tmp/home-e2e-live`, `PARTFORGE_AI_REPLAY_DIR=tests/data/ai_fixtures`, `PARTFORGE_AI_REPLAY_SPEED=0.15` (so the analysis view can be watched), `PARTFORGE_TOKEN` (random, for the evidence API calls); **without** `PARTFORGE_NO_ALTIUM`; `PARTFORGE_ALLOW_REAL_AI` never set |
| UI | the production build served by that server (`partforge/web`, untouched); Playwright Chrome headless, 1480×940, `de-DE` |
| Libraries | A = `tests\_tmp\ws-e2e-live` („E2E Live“, J1–J10), B = `tests\_tmp\ws-e2e-live-b` („E2E Live B“, J10), B moved to `tests\_tmp\ws-e2e-live-moved\E2E Live B verschoben` |
| Bridge | PartForge's default exchange directory `%LOCALAPPDATA%\PartForge\bridge` – its script project was already loaded in Altium at the baseline, so no project was added to the user's Projects panel |
| Not touched | `%APPDATA%\PartForge` (no settings file written there), `C:\PartForge-Examples\libraries`, any key file, git |

Evidence (session scratchpad `…\scratchpad\qa\e2e-live\`): `evidence\001…074_*.json` (API snapshots and job results in
run order), `altium-logs\00…99_*` (Altium read-backs), `altium-scripts\*.pas`, `kit\*.py` (Playwright journeys `j1…j10`,
`pfkit.py`, `uikit.py`, `bridge_resolve.py`, `whoholds.py` – Restart-Manager lock probe, `poll_holders.py`),
`logs\server.log`, `logs\run.log`, `logs\console_*.log`. Screenshots: `docs/screenshots/e2e-live/J<n>_<NN>_*.png` (131).

---

## 2. Altium safety log [VERIFIED]

| Item | Value |
| --- | --- |
| Baseline 19:31 (`altium-logs\00_baseline.txt`) | 20 installed IntLibs, **no DbLib**; projects Free Documents (0), `1355.PrjPcb` (31), `Sandbox.PrjScr` (1), `%LOCALAPPDATA%\PartForge\bridge\script\PartForgeBridge.PrjScr` (5); focused `1355.PrjPcb` |
| Final 20:40 (`altium-logs\99_final_state.txt`, written by Altium itself) | **identical to the baseline** (28/28 lines, compared by script) |
| Sandbox scripts | 19, all `timeout_seconds=5`, all finished inside the window, `dialogs_dismissed=0` in every run, ASCII only, no indexing of interface string properties, `get_screenshot` never used |
| PartForge bridge | 111 commands of the server (44 `dblib_install_state`, 34 `refresh_dblib`, 9 install, 9 uninstall, 9 `resolve_db_components`, 6 `document_state`) + 11 read-only resolves of `kit\bridge_resolve.py`; no wedge, no failure, no warning in the server log |
| Documents | opened hidden and closed again by my scripts: `PF_NOLEAD.PcbLib`, `PF_ICs.SchLib`, two scratch sheets `qa\e2e-live\place\E2E_Live_Place*.SchDoc` (empty sheet saved first so it can be addressed by path, placement discarded with `Modified := False`); PartForge itself opened no document (`own_documents.json` never created) |
| Focus | checked before and after the placements: `1355.PrjPcb` stayed focused, Free Documents 0 → 0 |
| Libraries | A, B and moved B installed/uninstalled through PartForge only; at the end none of them is installed |
| Residue | X2.EXE still holds `tests\_tmp\ws-e2e-live\PartForge.sqlite` (+ `-wal`, `-shm`) – since the uninstall at 20:21, still at 20:44 (F3). Harmless for Altium; the folder can be deleted after the next Altium restart |
| Other PartForge servers | another agent's server (port 8862) started during the run; every check here used the library folders above |

---

## 3. Journeys

### J1 First run – PASS [VERIFIED]

Screenshots `J1_01…07`. `/` redirects to `/willkommen`; „Neue Bibliothek anlegen“ opens the dialog with the default
folder `C:\PartForge-Examples\libraries\PartForge` (the folder follows the name until it is touched: „E2E Live“ →
`…\Altium_Libs\E2E_Live`); the isolated folder was typed into „Ordner“, „Beispielinhalte anlegen“ was on.

* „Bibliothek anlegen“ → success view after 1.85 s; „Bibliotheken schreiben“ (job 3.57 s) ends with „15 Symbole und
  13 Footprints in 14 Bibliotheksdateien geschrieben.“ (5.3 s after the click, `J1_05`). 19 parts, 15 symbols,
  13 footprints, 8 SchLib + 6 PcbLib, layer header and heights patched on every PcbLib (server log).
* Übersicht (`J1_06`): 19 Bauteile, 19 Kategorien (13 mit Bauteilen), 15 Symbole „alle in Dateien“, 13 Footprints,
  **Probleme 0** („nur 10 Hinweise“ = no datasheet link on 10 examples), health ring **100 %**, DbLib „Aktuell“ (19
  Tabellen · 266 Felder), Altium „Läuft · 26.10.1.5 / DbLib nicht installiert“.
* The automatic refresh after the first DbLib write pops a toast „Altium aktualisieren (inkl. Bauteilindex) – In Altium
  ist keine DbLib … installiert – nichts zu aktualisieren“ (F11).

### J2 Altium page – PASS [VERIFIED]

Screenshots `J2_01…08`, evidence `014…019`, `altium-logs\02_*`.

* Status (`J2_01`): „ALTIUM LÄUFT – Die DbLib ist noch nicht installiert“; DbLib „Aktuell“; Bibliotheksdateien
  „Synchron · Rust-Writer 0.1.0 aktiv · Altium 26.10.1.5“.
* „In Altium installieren“ → „Die DbLib ist in Altium installiert.“ (job 4.48 s, UI 5.4 s) → hero „ALLES VERBUNDEN –
  Altium sieht den aktuellen Stand“.
* „In Altium prüfen“ offers „Alle 19 Bauteile – aus 13 Kategorien · etwa 5 s“ → **19 Bauteile in Altium geprüft:
  19 in Ordnung** (job 7.95 s, 1 Altium run, lookups 3.35 s). Every part: symbol found, pins = registry, footprint
  assigned / library found / in library, Comment visible and the only visible parameter:

| Table | Parts | Symbol | Pins | Footprint | Comment |
| --- | --- | --- | --- | --- | --- |
| Resistors | RC0603FR-07100RL, -0710KL, -071KL, -074K7L | Resistor | 2 | RESC1608X50N | 100R / 10k / 1k / 4k7 |
| Capacitors | GRM188R71H104KA93D, GRM21BR61E106KA73L | Capacitor | 2 | CAPC1608X87N / CAPC2012X145N | 100n 50V / 10u 25V |
| Inductors · Ferrite · LEDs | SRR1260-100M · BLM18PG221SN1D · 150060RS75000 | Inductor · Ferrite Bead · LED | 2 | INDM125125X650N_6E43 · INDC1608X95N · LEDC1608X80N | 10u · 220R@100MHz · Rot |
| Diodes | MBR0520LT1G, MMSZ5231B-7-F | Schottky / Zener Diode | 2 | SOD3716X135N | MPN |
| BJT · FET | MMBT3904LT1G · 2N7002,215 | NPN · NMOS | 3 | SOT95P237X112-3N | MPN |
| Amplifiers | LM358DR · TLV9001IDBVR | Op-Amp Dual · Op-Amp | 8 · 5 | SOIC127P600X175-8N · SOT95P280X145-5N | MPN |
| Power Linear · Oscillators · Connectors · Fuses | AP2112K-3.3TRG1 · ABS07-32.768KHZ-T · 61300411121 · 0466001.NR | AP2112K · Crystal · Connector 1x04 · Fuse | 5 · 2 · 4 · 2 | SOT95P280X145-5N · XTAL3215X90N · HDRV4W64P254_1X4_1016X254X854B · FUSC3216X60N | MPN · 32.768kHz · MPN · 1A |

* Cross-check by **file name** (`02_J2_crosscheck_by_filename.txt`): the DbLib is installed (index 20 of 21);
  RC0603FR-074K7L, LM358DR, 61300411121 have parameters, are in the component index and load with the expected symbol,
  pin count, SchLib path and current PCBLIB model.
* Label inconsistencies of the result (F6): the choice „Alle 19 Bauteile“ is reported as „Stichprobe über 13 Kategorien“.

### J3 Serien-Assistent – PASS [VERIFIED]

Screenshots `J3_01…17`, evidence `020…029`, `altium-logs\03_*`, `04_*`.

* Kategorie „Widerstände“ (a card click advances by itself) → „YAGEO RC_L“ (verified template) → Bauformen „Keine“, then
  0402 + 0603 → E-Reihe E24 → Von „1k“, Bis „100k“ → „0-Ω-Brücken mit anlegen“ on → live counter **100 Bauteile = 2
  Bauformen × 49 Werte + 2 Brücken**, check „97 neu, 3 vorhanden, 0 Konflikte, 0 ungültig, 1 Footprint wird erzeugt“
  (`J3_05`). The UI preview equals an independent API preview of the same request (`020`).
* Vorschau (`J3_07`): 100 rows; Erzeugen → „Serie erzeugen“ → **„Serie erzeugt: 97 neu, 0 aktualisiert,
  3 übersprungen, 1 Footprint neu“** (job 2.27 s, backup `PartForge_20261008-194158_vor_serie.sqlite`), success view
  „Altium Designer wird aktualisiert – die neuen Bauteile erscheinen gleich im Bauteilbrowser“ (`J3_11`).
* **Without any user action** `altium.refresh` started 2.0 s after the commit and finished 7.6 s after it (index rebuild
  3.6 s): „Altium liest die Bibliotheksdatenbank neu ein – Änderungen sind jetzt sichtbar.“
* Negative cache: before the commit `RC0402FR-0747KL` and `RC0603FR-0722KL` were looked up by file name – no
  parameters, NOT in the index (`03_*`). After the automatic refresh both are found; a spread sample of 8 new parts
  (0402/0603 low, mid, high, both jumpers) has parameters, is in the index and loads with „Resistor“, 2 pins, Comment
  `47k`/`22k`/`1k`/`100k`/`0R`/`1k1` visible and the right footprint (`RESC1005X40N` for 0402, `RESC1608X50N` for 0603)
  (`04_*`).
* „In Altium prüfen → Eine Kategorie → Widerstände“: **101 Bauteile geprüft: 101 in Ordnung** (15.7 s, 3 Altium runs).
* Prüfbericht / Übersicht: **0 Fehler, 0 Warnungen**, 10 Hinweise (missing datasheet links of the examples).

### J4 Datenblatt-Import (replay) – PASS [VERIFIED]

Screenshots `J4_01…19`, evidence `030…037`, `altium-logs\05_*`.

* `opa656.pdf` (`tests/data/corpus`, sha256 = fixture `opa656.json`) was dragged onto the **Übersicht** with a real
  `DataTransfer` (`dragenter`/`dragover`/`drop` on the window): overlay „Datenblatt loslassen zum Analysieren“
  (`J4_02`) → analysis view with steps, page mosaic and cost (`J4_03/04`) → „Analyse fertig: 14 Bestellvarianten,
  13 Pins, 2 Gehäuse – 0,23 $“ (recorded cost, replay = no request; job 7.0 s).
* **Pin tables vs. PDF.** The PDF's pin configuration (page 2, rendered and read) and the review tables:

| Package | Pin | PDF p. 2 | Review (UI) | Altium after commit |
| --- | --- | --- | --- | --- |
| SOIC-8 (D) | 1 · 2 · 3 · 4 | NC · Inverting Input · Noninverting Input · −VS | NC · −IN (Eingang) · +IN (Eingang) · −VS (Versorgung) | – · −IN Input · +IN Input · V− Power |
| SOIC-8 (D) | 5 · 6 · 7 · 8 | NC · **Output** · +VS · NC | NC · **OUT (Ausgang)** · +VS (Versorgung) · NC | – · **OUT Output** · V+ Power · – |
| SOT-23-5 (DBV) | 1 · 2 · 3 · 4 · 5 | Output · −VS · Noninverting · Inverting · +VS | OUT · −VS · +IN · −IN · +VS | OUT · V− · +IN · −IN · V+ |

**No mismatch** in either package. NC pins 1/5/8 have no symbol pin („Pads ohne Pin im Symbol (nicht verbunden): 1,
5, 8“ as a hint).

* Blockers: **none** – no „Vor dem Anlegen“ checklist, commit bar „Bereit zum Anlegen“ (nothing to confirm).
* „14 Bauteile anlegen“ → **„Angelegt: 14 Bauteile, 1 Symbol, 1 Footprint“** (3.8 s): new symbol `Op-Amp (SOIC8)`,
  new footprint `SOT95P280X145-5N_02CB` (datasheet dimensions differ from the template), `SOIC127P600X175-8N` and the
  symbol `Op-Amp` reused. Automatic refresh with rebuild done 9.2 s after the commit. The parts appear in
  „Verstärker“ (`J4_16`).
* „In Altium prüfen → Verstärker“: **16/16 in Ordnung** (7.6 s). Altium read-back (`05_*`): OPA656U → `Op-Amp (SOIC8)`,
  5 pins, PCBLIB `SOIC127P600X175-8N`; OPA656N/250 → `Op-Amp`, 5 pins, PCBLIB `SOT95P280X145-5N_02CB`.
* After this import the file-level health has a **warning** for the 8 SOIC parts (F2).

### J5 „Datenblatt suchen“ (replay) – PASS [VERIFIED]

Screenshots `J5_01…06`, evidence `038…040`. „OPA656“ + „Texas Instruments“ → „Gefunden: 4 Kandidaten, davon 3 PDFs –
0,090 $“ (recorded search, 1.1 s): TI datasheet (Hersteller, derived pattern, „Empfohlen“), Mouser (Distributor),
kontest.ru (Andere Quelle), TI product page („Webseite statt PDF“, no load button). „Laden und analysieren“ on the TI PDF
→ URL import with the fixture's download → „Bereits vorhanden: opa656.pdf (25 Seiten)“ (0.03 s) → the existing review
opens with the toast „„opa656.pdf“ ist bereits analysiert – Das vorhandene Ergebnis wird geöffnet“, the datasheet link
can now be the manufacturer URL, the search cost is added to the datasheet (0,32 $). No download mock was needed.

### J6 Bauteile – PASS [VERIFIED] (F5)

Screenshots `J6_01…20`, evidence `041…047`, `altium-logs\06…11_*`.

* **Inline edit** of `RC0603FR-074K7L`: Beschreibung → „RES 0603 4k7 1% E2E-Live geaendert“, Wert (column shown via
  „Spalten“) → „4k7 E2E“ (double click, type, Enter). Each save triggered the automatic close-only refresh ≈ 2 s later.
  Altium by file name (`08_*`) and through the bridge (`07_*`): `Description=RES 0603 4k7 1% E2E-Live geaendert`,
  `Value=4k7 E2E` (before: `RES 0603 4.7kΩ ±1% 0.1W Dickschicht`, `4.7kΩ`). Comment unchanged `4k7`.
* **Delete + Rückgängig** of `RC0402FR-071K1L`: row checkbox → „Löschen“ → confirm → toast „„RC0402FR-071K1L“ gelöscht“
  with „Rückgängig“ (10 s, hovering pauses it) → API 404 → automatic refresh (close only) → Altium: no parameters, no
  footprint (but see F5) → „Rückgängig“ → „„RC0402FR-071K1L“ wiederhergestellt“ → refresh with index rebuild → Altium
  resolves it again with `RESC1005X40N`, Comment `1k1`. History: import → delete → restore.
* **Bulk change via filter**: Filter „Baugröße = 0402“ → „50 von 101“ → select all → „Bearbeiten“ → „Lieferant 1 =
  Mouser“ → „50 Bauteile ändern“ → toast „50 Bauteile geändert“; API: 50 parts with Supplier 1 = Mouser. Altium:
  `RC0402FR-0747KL` and the jumper `RC0402JR-070RL` carry `Supplier 1 = Mouser`, the 0603 part does not.

### J7 Footprint generator QFN-24 – PASS [VERIFIED]

Screenshots `J7_01…14`, evidence `048…054`, `altium-logs\12_*`.

* Gehäusefamilie „QFN / DFN / SON“ (not a template) → Anzahl Anschlüsse 24, Raster 0,5, Körper X/Y 3,95…4,05,
  Bauhöhe 0,80…1,00, Exposed Pad 2,55…2,75, b 0,18…0,30, L 0,30…0,50 → `QFN50P400X400X100-25N_5842` („Eigene Maße“,
  IPC-Basis `QFN50P400X400X100-25N`), 25 pads, pad 0,825 × 0,25 mm, EP 2,65 × 2,65 mm, courtyard 5,20 × 5,20 mm,
  Höhe max. 1,00 mm, 3D view (`J7_03`, `J7_05`) → „In Bibliothek speichern“ → „Footprint … gespeichert in
  Footprints\PF_NOLEAD.PcbLib“, registry: status ok, 25 pads, height 1.0, `3D\QFN50P400X400X100-25N_5842.step`.
* Matching symbol from a pasted pin list (24 pins + EP 25, `I\N\T\` and `R\E\S\E\T\` with overbar) →
  `E2E_IOEXP24` in `Symbols\PF_ICs.SchLib`; new part `E2E-IOEXP24-QFN` (Kategorie ICs) with symbol and footprint picked
  in „Neues Bauteil“ (`J7_11/12`).
* Altium: „In Altium prüfen → ICs“ 1/1 ok (25 pins = 25 expected, footprint assigned/in library). PcbLib read-back
  (opened hidden, closed): **pads = 25, component bodies = 26** (embedded STEP + package + 24 terminals), body heights
  393 700 (1/10 000 mil) = **1.000 mm**, footprint **Height = 393 701 = 1.000 mm**.

### J8 Symbol generator (16 pins, 2 parts) – PASS [VERIFIED] (F7)

Screenshots `J8_01…09`, evidence `055…059`, `altium-logs\13_*`.

* New IC symbol (command palette „Neues IC-Symbol“), name `E2E_DUAL16`, pin list pasted (16 rows, `F\L\T\1/2` with
  overbar), Teile „Anzahl 2“ → part A = 12 signal pins, part B = VCC, GND, GND2, VCC2 („Versorgung und Masse kommen in
  eigene Teile“), saved to `PF_ICs.SchLib` (pin_count 16, part_count 2). SOIC-16 from the generator template →
  `SOIC127P600X175-16N` in `PF_GULLWING.PcbLib`. New part `E2E-DUAL16-SOIC`.
* Altium: „In Altium prüfen → ICs“ 2/2 ok (16/16 pins). SchLib read-back: `E2E_DUAL16` parts = 2, pins = 16, pins
  5/6/11/12 in part 2, the rest in part 1; the description „E2E Doppelkomparator, 2 Kanäle“ (30 characters, contains
  `ä` = Chr(228)) is intact – the generator's warning about it was a false alarm (F7).

### J9 Placement on a scratch sheet – PASS [VERIFIED]

`altium-scripts\09_place_on_scratch_schdoc.pas`, `altium-logs\14_J9_place_readback.txt`. Same calls as the verified
wave-3 script, plus focus checks. A hidden free SchDoc was created, saved empty to the QA scratch folder, two parts were
placed from the installed DbLib, read back and the sheet closed without saving the placement:

* **R1 = RC0603FR-074K7L**: DbLib `PartForge.DbLib` (file name only), table Resistors, `Resistor`, 2 pins, **Designator
  visible, Comment `4k7` visible**, 17 parameters hidden (incl. the J6 edits `Value=4k7 E2E`, description
  „RES 0603 4k7 1% E2E-Live geaendert“), `RESC1608X50N` current.
* **U1 = OPA656U**: `Op-Amp (SOIC8)`, 5 pins, Designator and **Comment `OPA656U` visible**, all other parameters hidden
  (Manufacturer, Package, Height 1.75mm, GBW 230MHz, ComponentLink1URL = the library's PDF …), `SOIC127P600X175-8N`
  current.
* Focus `1355.PrjPcb` before/after, Free Documents 0 → 0, sheet and DbLib document not open afterwards.

### J10 Robustness – FAIL (partly passed)

Screenshots `J10_01…29`, evidence `060…070`, `logs\run.log`, `logs\poll_holders_A.log`.

* **Second library, same DbLib name** (`J10_04`): a new library B (switcher „Neue Bibliothek …“, no examples) shows on
  its Altium page „GLEICHNAMIGE DBLIB – Altium kennt mehrere DbLibs mit diesem Namen“ with A's path; nothing is
  replaced [VERIFIED]. B's first automatic refresh, however, acted on A's installation (F4).
* **(a) Library switch while a job runs**: a 3 899-part RC_L series (5 sizes, Reihe laut Datenblatt) was started in A;
  0.8 s later the user switched to B via the switcher. Server side correct: the series job ended **`cancelled`,
  „Abgebrochen – die Bibliothek wurde gewechselt oder geschlossen“, `cancel_reason = library_switch`**, the switch took
  2.8 s, A still has 101 resistors (the 3 footprints written before the cancel stay, as documented), B has 0 parts.
  **UI: no cancel message anywhere** – only „„E2E Live B“ geöffnet“, no job pill, no dock entry at 1 s / 6 s / 12 s,
  the wizard silently shows step 1 of library B (`J10_09`, reproduced in `J10_13…15`) → F1.
* **(b) Close and reopen**: „Bibliothek schließen“ → `/willkommen`; „E2E Live“ from „Zuletzt verwendet“ reopens in
  0.23 s with all 132 parts (`J10_16/17`) [VERIFIED].
* **(c) Move the folder**: A was uninstalled through the UI („Die DbLib wurde in Altium deinstalliert.“, 5.4 s) and
  closed in PartForge; renaming the folder failed with **WinError 5 „Zugriff verweigert“** – the Restart Manager shows
  **X2.EXE (pid 81348) holding `PartForge.sqlite`, `-wal`, `-shm`** although no DbLib is installed and no server document
  refers to the folder. Reinstall + „Index neu aufbauen“ + uninstall did not release it; still held at 20:44 (F3).
  The move was then done with library B (installed, verified, placed from and uninstalled before – released by Altium
  ≈ 70 s after its uninstall): moved to `ws-e2e-live-moved\E2E Live B verschoben`, „Bibliothek öffnen“ with the new path
  (0.35 s) → log „Bibliotheksordner verschoben (…): 1 Verweise in 1 Bauteilen angepasst.“, DbLib rewritten
  (`Database=` and `LibraryDatabasePath=` = new path), OPA656U's datasheet link points into the new folder (audit
  `bulk_update` by PartForge), „Zuletzt verwendet“ marks the old path „nicht gefunden“ → „In Altium installieren“ →
  **4/4 in Ordnung**; the bridge resolves symbol paths and the datasheet link inside the moved folder
  (`altium-logs\15_*`) [VERIFIED].

---

## 4. Findings

### F1 (medium) A library switch silently cancels a running job – the UI never shows the cancel message

* Evidence: `J10_09`, `J10_13…15`, evidence `063`, `065`: job `series` → `cancelled`, message „Abgebrochen – die
  Bibliothek wurde gewechselt oder geschlossen“, `cancel_reason = library_switch`; the UI shows only „„E2E Live B“
  geöffnet“. The user is neither warned before the switch nor told afterwards that 3 899 parts were not created.
* Cause [inference]: the series wizard tracks its job inline (`trackJob(job, {dock: false, toast: false})`);
  `useInlineJob`'s cleanup hands the job to the dock only if it is **not** finished yet – after a switch it is already
  `cancelled` when the step unmounts, so nobody reports it. Other inline jobs (Bibliotheken schreiben, Datenblatt-Übernahme)
  probably share the gap.
* Files: `frontend/src/api/jobs.ts` (`useInlineJob`), `frontend/src/pages/serien/SerienPage.tsx`,
  `frontend/src/app/shell/Sidebar.tsx` (switch without a hint about running library jobs).
* Fix: when a job ends with `cancel_reason = "library_switch"` always toast it (job title + message) regardless of the
  inline flag; optionally ask before switching while library jobs run.

### F2 (medium) Health check warns about NC pads of every datasheet IC

* Evidence: after J4 `GET /api/libraries/health` → warning `pin_pad_mismatch` „Symbol „Op-Amp (SOIC8)“ / Footprint
  „SOIC127P600X175-8N“: Pads ohne Pin im Symbol: 1, 5, 8 (und 7 weitere Bauteile)“; the same in library B after one
  import (`J10_29`: Prüfbericht 1). The import itself called these pads „nicht verbunden“ and allowed them.
* Cause: `datasheet/proposal._pin_pad_check` accepts NC and thermal pads (`nc_pins`, `thermal`); `sync.library_health`
  uses `geometry.check_symbol_footprint`, which flags every pad without a pin. The symbol spec does not record which
  pads are NC (generator `pinmap` SOIC8 only lists the 5 pins).
* Files: `partforge/altium/sync.py` (≈ l. 2801–2812), `partforge/geometry/model.py` (`check_symbol_footprint`),
  `partforge/datasheet/proposal.py`, `partforge/symbols/mapping.py` (`_UNUSED_PADS_OK`).
* Fix: store NC pads with the symbol (e.g. `generator.nc_pads`) or apply the same rule as the proposal/mapping (kinds in
  `_UNUSED_PADS_OK`, thermal pads → hint) in the health check.

### F3 (medium) After „Aus Altium deinstallieren“ Altium keeps the database open – the folder cannot be moved

* Evidence (`logs\run.log`, `poll_holders_A.log`, Restart Manager via `kit\whoholds.py`):

| Library / sequence before the uninstall | Uninstall | Altium released the SQLite file |
| --- | --- | --- |
| A: J1–J9 (install 19:35 … placement, probes) | 20:21:30 (and again 20:25:37) | **not by 20:44 (> 23 min)** |
| B: install → uninstall | 20:26:34 | ≈ 75–90 s later |
| B: install → verify → uninstall | 20:28:59 | ≈ 75–90 s |
| B: install → lookups by file name, placement parameters, load → uninstall | 20:31:18 | ≈ 60–75 s |
| B: install → placement on a scratch sheet → uninstall | 20:33:13 | ≈ 60–75 s |
| moved B: install → lookups of a missing key → uninstall | 20:40:46 | ≈ 75–90 s |
| moved B: install → load → delete → stale load → restore → uninstall | 20:42:56 | ≈ 60–75 s |

The uninstall job says „Altium gibt die Datenbank frei …“ and ends with „Die DbLib wurde in Altium deinstalliert.“;
a user who then moves the folder (README: „Ein verschiebbarer Ordner“) gets „Zugriff verweigert“. The ≈ 1 min delay
looks like ODBC/OLE DB connection pooling [inference]; why A stays locked is not isolated (none of the six variants
reproduces it; possibly a consumer in the user's Altium UI such as the Components panel [UNVERIFIED]).

* Files: `partforge/api/routes_altium.py` (`_uninstall_job`), `partforge/altium/bridge/scripts/PFLibraries.pas`.
* Fix: after the uninstall probe the lock (the Restart-Manager call of `whoholds.py` needs no admin rights) and say e.g.
  „Altium gibt die Datenbank in etwa einer Minute frei“ or, if it stays held, „Altium hält die Datenbank noch offen – zum
  Verschieben Altium neu starten“; mention it in README „Fehlerbehebung“.

### F4 (low/medium) A refresh of a library that is not installed rebuilds another library's installation and reports success

* Evidence (`evidence\071_J10_b_refresh_touches_a.json`, job 20:17:46): library B (not installed) wrote its
  DbLib; its automatic `altium.refresh` matched A's installed `…\ws-e2e-live\PartForge.DbLib` (same file name), closed A's
  hidden document, rebuilt Altium's index (3.5 s) and ended **„Altium liest die Bibliotheksdatenbank neu ein – Änderungen
  sind jetzt sichtbar.“, `installed: true`** – only a log line warns about the other DbLib.
* Files: `partforge/altium/refresh.py` (`describe_refresh`, `_run` – `installed` from `DbLibRefreshResult.installed =
  bool(matched)`), `partforge/altium/bridge/core.py`.
* Fix: when no matched entry is this DbLib, do not rebuild/close (or only for the file-name semantics) and end with a
  warning „Diese DbLib ist nicht installiert – eine gleichnamige DbLib einer anderen Bibliothek ist installiert“.

### F5 (low) After a delete Altium still loads the old symbol for the deleted key

* Evidence (`altium-logs\09_J6_after_delete_*`, `11_probe_*`, `16_exp3_after_delete.json`, reproduced in A and B): after
  the automatic close-only refresh the deleted record has no parameters, is not in the index and has no SchLib ref, but
  `LoadComponentFromDatabaseLibrary` still returns `Resistor`, 2 pins, „Generic resistor“, no footprint; only an index
  rebuild clears it. Verify sets `symbol_found = res.loaded` and would report such a stale component as „Symbol
  gefunden“ (the missing footprint is then the only error shown).
* Files: `partforge/altium/refresh.py` (deletes → `rebuild=False`), `partforge/api/routes_altium.py` (`_check_part`).
* Fix: treat `loaded` with empty `symbol_ref`/parameters as „Datensatz in Altium nicht gefunden“; consider a rebuild
  after deletes (cost ≈ 3–4 s).

### F6 (low) Verify labels contradict the user's choice

* „Alle 19 Bauteile“ (shown when the sample covers everything) sends `kind: sample` → result header „Stichprobe über
  13 Kategorien“ (`J2_06`, `J10_29`). „Eine Kategorie → Widerstände/Verstärker/ICs“ → job title „Bibliothek in Altium
  prüfen **(alle Bauteile)**“ (job dock, toasts) although one category was checked.
* Files: `partforge/api/routes_altium.py` l. 792 (`title` uses `request.all` and ignores `tables`),
  `frontend/src/pages/altium/StatusHero.tsx` (`VerifyMenu`), `frontend/src/pages/altium/VerifyPanel.tsx`.

### F7 (low) False warning for umlauts in IC descriptions

* „Die Beschreibung enthält Sonderzeichen; Altium zeigt sie im SchLib eventuell falsch an.“ for „… 2 Kanäle“
  (`J8_03`); Altium 26.10 reads the SchLib description with `ä` intact (`13_*`). Rule `not description.isascii()`.
* File: `partforge/symbols/validate.py` l. 116 – warn only for characters outside Latin-1 (or not at all).

### F8 (low) The job dock covers the Altium action bar

* After an Altium job the dock opens and intercepts clicks on „⋯ Weitere Altium-Aktionen“ at 1480×940 (Playwright:
  „Hintergrundjobs … intercepts pointer events“, `J10_21`); it has to be minimised first.
* Files: `frontend/src/api/jobs.ts` (`trackJob` `openDock` default), `frontend/src/app/shell/JobDock.tsx`.

### F9 (low, a11y) Series template cards are named only by the series code

* The radio names are „RC_L“, „CR“, „D/CRCW e3“ … without the manufacturer (`aria-labelledby` → title only).
* File: `frontend/src/pages/serien/steps/TemplateCard.tsx`.

### F10 (low) Every new library gets „PartForge.DbLib“

* A second library immediately shows „Gleichnamige DbLib in Altium installiert“ (Fehler) while the first one is
  installed; the create dialog neither offers a DbLib file name nor warns. Fix: propose a unique name in
  „Neue Bibliothek anlegen“ when a PartForge.DbLib of another library is installed.
* Files: `frontend/src/app/shell/LibraryDialogs.tsx`, `partforge/api/routes_system.py` (workspace create).

### F11 (low) First-run noise

* Right after creating a library (DbLib not installed) a toast „Altium aktualisieren (inkl. Bauteilindex) – … nichts zu
  aktualisieren“ appears (`J1_05`); after the install the hero says „zuletzt aktualisiert vor 2 Min.“ – that refresh did
  nothing. Files: `partforge/altium/refresh.py`, `frontend/src/pages/altium/model.ts`.

### F12 (low) „nicht lesbar“ for a value outside a selection list

* „Neues Bauteil“, Funktion „I/O“: the field says „nicht in der Auswahlliste“, the footer „1 Wert ist nicht lesbar –
  erneut Strg+Enter legt trotzdem an“ (`J7_12`). File: `frontend/src/pages/bauteile/dialogs/NewPartDialog.tsx`.

---

## 5. Timings [VERIFIED]

| Operation | Time |
| --- | --- |
| New library with examples: response / „Bibliotheken schreiben“ job / visible result | 1.85 s / 3.57 s / 5.3 s |
| Install (job / until the UI shows it) | 4.5 s / 5.4 s; uninstall 5.4 s |
| Verify 19 examples (1 run) · 101 resistors (3 runs) · 16 amplifiers · 4 parts (moved, installed) | 8.0 s · 15.7 s · 7.6 s · 4.9 s |
| Series commit 97 parts + 1 footprint | 2.3 s |
| Automatic refresh after inserts (start / done after the write) | ≈ 2 s / 7.6 s (series), 9.2 s (datasheet), 7.2 s (Rückgängig) |
| Automatic refresh after updates/deletes (close only) | done 2.1–3.4 s after the write |
| Datasheet analysis (replay, 0.15 s per streamed chunk) · commit 14 parts | 7.0 s · 3.8 s |
| Datasheet search (replay) · URL import of a known PDF | 1.1 s · 0.03 s |
| Library switch during a job (cancel + open) · reopen · open moved library | 2.8 s · 0.23 s · 0.35 s |
| Altium releasing the SQLite file after uninstall | ≈ 60–90 s (library B, 6 runs); library A > 23 min |

---

## 6. Observations (no defect)

* The altium-mcp sandbox transport turns `Ω` into `O` and `±`/`°`/`µ` into `\ufffd` in its result text; PartForge's
  bridge (`%uHHHH` encoding) shows that Altium itself has `4.7kΩ ±1%` exactly (`06_*`).
* Quantity columns (series preview, parts grid) are displayed localised („1,1 kΩ“, „62,5 mW“) while the stored text and
  the generated description stay canonical („1.1kΩ“) – by design.
* `asyncio … ConnectionResetError [WinError 10054]` once in the server log when the browser closed a connection –
  Windows proactor noise.
* The series wizard advances on a category card click; the template step needs „Weiter: Werte festlegen“.
* The IC symbol generator remembers its last draft; a new symbol starts with „Neues IC-Symbol“ (command palette).

## 7. Still UNVERIFIED

1. Why Altium keeps library A's database open (F3) – needs an Altium restart to clear; the Components panel was not
   inspected (no screenshots of the user's UI).
2. Moving a library while its old installation is still installed (missing file) – avoided on purpose: a refresh with
   index rebuild over a missing DbLib might raise a modal message in the user's Altium.
3. The Components panel UI itself, „Update Parameters From Database“ on placed parts after deletes (F5).

## 8. Artefacts

* Screenshots: `docs/screenshots/e2e-live/` (J1 7, J2 8, J3 17, J4 19, J5 6, J6 20, J7 14, J8 9, J10 29, Z 2).
* Scratchpad `qa\e2e-live\`: `evidence\001…074`, `altium-logs\00_baseline.txt … 99_final_state.txt`,
  `altium-scripts\00_state.pas`, `09_place_on_scratch_schdoc.pas`, `kit\` (journey scripts and tools), `logs\`.
* Library folders (test data): `tests\_tmp\ws-e2e-live` (still locked by Altium, F3), `tests\_tmp\ws-e2e-live-moved\E2E
  Live B verschoben`, `tests\_tmp\home-e2e-live`.
