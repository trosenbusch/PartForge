# Altium E2E, wave 2: PartForge end to end in a running Altium 26.10

Agent: Altium E2E agent (exclusive use of the running Altium) · 2026-10-08, 04:04–04:56
Altium: `C:\Program Files\Altium\AD22\X2.EXE`, **26.10.1.5**. Rust writer `altium-designer-mcp.exe` 0.1.0.
ODBC: 64-bit "SQLite3 ODBC Driver" 0.99991 (SQLite 3.43.2) through MSDASQL.

Working folder `E2E` = `C:\PartForge-Examples\Tools\PartForge\tests\_tmp\e2e-wave2\`:

| Path | Content |
| --- | --- |
| `Bibliothek\` | the E2E library (DbLib `PF_E2E_Wave2.DbLib`, database, Symbols, Footprints, 3D, Datasheets, Backups) |
| `evidence\NN_*.json` | every HTTP response and final job snapshot of the run, numbered in run order |
| `altium-logs\` | Altium-side read-backs (layers and primitives, placement), baseline and final state |
| `kit\` | `e2e_server.py` (launcher), `e2e.py` (HTTP driver), comparison and probe tools; `kit\altium-scripts\*.pas` = the main Altium script bodies |
| `umlaut\Bauteile Übersicht\` | second library in a folder with umlauts |
| `place\`, `resave\`, `reload\` | temporary SchDoc, Altium's re-saved PcbLib copy, hidden-reload test library |
| `home\`, `home-umlaut\` | isolated `PARTFORGE_HOME` of the E2E server and of the umlaut run |

Every statement is tagged **[VERIFIED]** (observed in this Altium session or measured) or **[UNVERIFIED]**
(inference, or not testable without touching the user's UI).

> **Welle 3 (§10, same day):** the remaining defects of §6 are fixed and re-verified in Altium – Comment visible
> (db-core fix), footprint `Height` patch, batch verification (`resolve_db_components`); the whole chain ran again,
> including a moved library folder.

---

## 0. TL;DR

1. **The whole chain works in Altium without a restart [VERIFIED].**
   * New library with examples → Rust writer (15 symbols, 13 footprints, 14 files, layer header patch) → DbLib →
     ODBC test → **install** → **verify: 19/19 example parts resolve** (symbol loaded, pin count = registry, every
     footprint assigned, its PcbLib present and containing it).
   * The **patched layer header is accepted**: Altium shows all 32 mechanical layers with the user's names, kinds and
     enabled flags, keeps all 11 layer pairs and both layer sets when it saves the library itself, and every footprint
     has exactly the primitives per layer that the file contains. The header patch stays **on**.
   * **Vishay CRCW 0603 E24 1k–10k** (25 parts) via `POST /series/commit` → automatic refresh (index rebuild) ~6 s
     later → the new parts resolve, **including a key Altium had cached as "not found"** → verify 29/29.
   * **opa656.pdf** (recorded Claude answers) → proposal → commit → automatic refresh → `OPA656U` resolves with the
     new symbol `Op-Amp (SOIC8)` (5 pins) and `SOIC127P600X175-8N` → verify 3/3 Amplifiers.
   * **Placement** of `OPA656U` and `CRCW06034K70FKEA` on a hidden temporary SchDoc: library link by file name,
     table, key, symbol, pins, parameters and footprint read back; closed without saving.
   * **Uninstall** (close, then uninstall) leaves nothing open; Altium's final state equals the baseline.
2. **Defects found and fixed in this stage** (§5):
   * `refresh.py`: a **new, renamed or removed column stayed invisible** in Altium after the automatic refresh
     (close only) – Altium caches the column list; now every structure change rebuilds the index.
   * `PFLibraries.pas` `resolve_db_component`: a temporary installation **leaked Altium's hidden DbLib document** and
     its database connection; now released before the uninstall.
   * `PFLibraries.pas` `refresh_document`: a library Altium held open **hidden** came back as a **visible editor tab**;
     now it is reopened hidden.
   * Live tests: one stable exchange directory instead of one script project per test; the graphics-before-pins test
     now checks the order per part (what Altium actually needs); the dispatch test no longer uses a magic number.
3. **Remaining defects** (§6): the **Comment of placed parts is hidden** (db-core template default), footprint
   `Height` = 0 for Rust-written footprints, verify needs ~1.4 s per part, two stale tests of other modules.
4. **Safety [VERIFIED]:** 23 sandbox scripts (all `timeout_seconds=5`, all finished inside it, `dialogs_dismissed=0`),
   more than 200 PartForge bridge runs, no dialog, no wedge, `get_screenshot` never used, no user document touched.

---

## 1. Safety log [VERIFIED]

| Item | Value |
| --- | --- |
| Baseline 04:05 (`altium-logs\00_baseline.txt`) | 20 installed IntLibs; projects Free Documents (0), `1355.PrjPcb` (31), `HPI_Award.PrjPcb` (13), `Sandbox.PrjScr` (1), `%LOCALAPPDATA%\PartForge\bridge\script\PartForgeBridge.PrjScr` (5, **already loaded before this run**, its script files dated 02:41); focused Free Documents |
| Final 04:53 (`altium-logs\99_final_state.txt`) | identical to the baseline |
| My script project | `tests\_tmp\altium-live\exchange\script\PartForgeBridge.PrjScr` (live tests) closed with `GetWorkspace.DM_CloseProject` after checking that none of its documents was loaded, modified or shown (twice, after each live run) |
| Documents | All opened hidden (`Client.OpenDocument` without `ShowDocument`, `CreateNewFreeDocumentFromDocumentKind('SCH', False)`) and closed again: PF_CHIP.PcbLib ×4, PF_Reload.SchLib, 2 temporary SchDocs (closed with `Modified := False`, placement discarded) |
| Libraries | Installed and uninstalled: `PF_E2E_Wave2.DbLib`, `PF_E2E_Umlaut.DbLib`, the unique `PF_Live_*.DbLib` of each live test. Every hidden DbLib document closed (one leak of the old `resolve_db_component` reproduced on purpose and closed by hand, §5.2) |
| Other PartForge servers | Other agents' PartForge servers ran the whole time (ports 8812–8915). To stay out of their way every library here used a **unique DbLib file name**; their refresh services only touch their own DbLib names |
| Databases | After the run no process holds the E2E databases (`kit\lockprobe.py`: no shm, all lock bytes free) |

---

## 2. Live tests (`pytest -m altium`, `PARTFORGE_TEST_ALTIUM=1`)

Final run (`evidence\26_live_tests_final.txt`): **11 passed in 82 s**.

| Test | Result | Notes |
| --- | --- | --- |
| `test_bridge_live::test_ping`, `test_installed_libraries` | pass | 1.3 s per script run |
| `test_write_and_list_libraries`, `test_altium_writer_full_cycle` | pass | Altium backend writes SchLib/PcbLib and closes them |
| `test_bridge_symbols_store_graphics_before_pins` | **failed → test fixed** | see §4.9 |
| `test_resolve_db_component` | pass | run with `PARTFORGE_TEST_DBLIB` = the E2E DbLib (installed, and later not installed → temporary-install path, §5.2) |
| `test_refresh_altium_live::test_install_state_and_refresh_make_new_rows_visible` | pass | |
| `test_refresh_without_installation_touches_nothing` | pass | |
| `test_close_then_uninstall_releases_the_database` | pass | |
| `test_new_column_is_visible_after_the_automatic_refresh` | **new**, pass | fails with the old close-only behaviour (`assert None == 'sichtbar'`), passes with the fix (§5.1) |
| `test_automatic_refresh_after_a_write` | pass | |

---

## 3. E2E run through the HTTP API

**Setup.** The real server (`python -m partforge --server-only`, not pytest) started by `kit\e2e_server.py` with
`PARTFORGE_HOME=E2E\home` and the recorded Claude answers for `opa656.pdf` (`tests\data\ai_fixtures\opa656.json`,
replayed – no network, no cost). Default settings: `auto_refresh` on, Rust backend, default bridge exchange directory.
The library uses the DbLib file name `PF_E2E_Wave2.DbLib`. `kit\e2e.py` drives the API and saves every response.

### 3.1 Steps [VERIFIED]

| # | Step (endpoint) | Result | Time | Evidence |
| --- | --- | --- | --- | --- |
| 1 | `POST /workspace/create` (examples, `write_libraries`) | 19 parts, 15 symbols, 13 footprints; job "Bibliotheken schreiben": 8 SchLib + 6 PcbLib written, 0 errors, header patch on every PcbLib | 2.3 s | `01_create` |
| 2 | DbLib status | written by the auto-writer, `up_to_date`, `db_path_ok`, 19 enabled tables, 255 field maps; the refresh service probed Altium once (DbLib not installed, nothing touched) and cached the result | – | `02_status_after_create` |
| 3 | `POST /altium/odbc-test` | 64-bit driver, WAL, 19 tables / 19 parts read like Altium, Ω µ ± umlauts unchanged | 0.03 s | `03_odbc` |
| 4 | `POST /altium/install` | installed | 3.9 s | `04_install` |
| 5 | `POST /altium/verify {all}` | **19/19 ok** (table below) | 27.8 s | `05_verify_examples` |
| 6 | PcbLib in Altium | §3.2 | – | `altium-logs\06_pf_chip_altium.txt` |
| 7 | `POST /series/preview` + `/series/commit` | 25 new `CRCW0603…FKEA` (1k–10k E24), symbol `Resistor` and `RESC1608X50N` reused | 0.2 s | `07_series_preview`, `08_series_commit` |
| 8 | automatic refresh | job `altium.refresh` (trigger `auto`, rebuild): close → `RefreshInstalledLibraries` 2.7 s → close | 4.35 s, ~6 s after the commit | `09_refresh_after_series` |
| 9 | `POST /altium/verify {tables: Resistors}` | **29/29 ok** | 40.1 s | `10_verify_resistors` |
| 10 | `POST /datasheets` (upload) + `/extract {"vision":"off"}` | 25 pages (4 without text layer); TI OPA656, 14 MPNs, 13 pins, packages D (SOIC-8) and DBV (SOT-23-5); 0 issues | 1.8 s + 1.4 s | `11_ds_upload`, `12_ds_extract` |
| 11 | `/proposal {variants: [OPA656U]}` + `/commit` | category Amplifiers, new symbol `Op-Amp (SOIC8)` (2 IN−, 3 IN+, 4 V−, 6 OUT, 7 V+; 1/5/8 NC), footprint `SOIC127P600X175-8N` reused; the sync checked `PF_Analog.SchLib` in Altium before writing it (not open) | 1.5 s | `13_ds_proposal`, `14_ds_commit` |
| 12 | automatic refresh | rebuild, 4.3 s | | `15_refresh_after_datasheet` |
| 13 | `POST /altium/verify {tables: Amplifiers}` | **3/3 ok** (LM358DR, OPA656U, TLV9001IDBVR) | 6.6 s | `16_verify_amplifiers` |
| 14 | placement on a temporary SchDoc | §3.4 | | `altium-logs\09_place_readback.txt` |
| 15 | `POST /altium/uninstall` | released, uninstalled | 5.2 s | `23_uninstall`, `24_dblib_after_uninstall` |

Example parts in step 5 (all `ok`, `[assigned, library found, in library]` for every footprint):

| Table | Part | Symbol | Pins | Footprint |
| --- | --- | --- | --- | --- |
| Resistors | RC0603FR-07100RL, -0710KL, -071KL, -074K7L | Resistor | 2/2 | RESC1608X50N |
| Capacitors | GRM188R71H104KA93D / GRM21BR61E106KA73L | Capacitor | 2/2 | CAPC1608X87N / CAPC2012X145N |
| Inductors | SRR1260-100M | Inductor | 2/2 | INDM125125X650N_6E43 |
| Ferrite Beads | BLM18PG221SN1D | Ferrite Bead | 2/2 | INDC1608X95N |
| Diodes | MBR0520LT1G / MMSZ5231B-7-F | Schottky Diode / Zener Diode | 2/2 | SOD3716X135N |
| LEDs | 150060RS75000 | LED | 2/2 | LEDC1608X80N |
| Transistors BJT / FET | MMBT3904LT1G / 2N7002,215 | NPN / NMOS | 3/3 | SOT95P237X112-3N |
| Amplifiers | LM358DR / TLV9001IDBVR | Op-Amp Dual / Op-Amp | 8/8, 5/5 | SOIC127P600X175-8N / SOT95P280X145-5N |
| Power Linear | AP2112K-3.3TRG1 | AP2112K | 5/5 | SOT95P280X145-5N |
| Oscillators | ABS07-32.768KHZ-T | Crystal | 2/2 | XTAL3215X90N |
| Connectors | 61300411121 | Connector 1x04 | 4/4 | HDRV4W64P254_1X4_1016X254X854B |
| Fuses | 0466001.NR | Fuse | 2/2 | FUSC3216X60N |

### 3.2 The patched PcbLib in Altium [VERIFIED]

`PF_CHIP.PcbLib` (7 footprints) opened hidden (`IsShown=False`, `Modified=False`) and closed again
(`kit\altium-scripts\06_pcblib_layers_and_primitives.pas`).

* **Mechanical layers 1–32**, `LayerObject_V7[ILayer.MechanicalLayer(n)]`: name, `Kind`, `MechanicalLayerEnabled` equal
  the header PartForge wrote **and** the user's `mechanical_layer.stackup` for every layer (`kit\compare_pcblib.py`:
  "MECH mismatches: none"). Examples: Mech 9 *Top Assembly* kind 1, Mech 11 *Top Designator* 13, Mech 13 *Top 3D
  Body* 26, Mech 15 *Top Courtyard* 11, Mech 17 *Top Component Center* 7, Mech 19 *Top Value* 23, Mech 21 *Top
  Component Outline* 9, Mech 1 *Board Shape* 30, Mech 32 disabled. `UsedByPrims` is True exactly on 9, 11, 13, 15, 17,
  19, 21.
* **Kind ordinals.** `IPCB_LayerObject_V7.Kind` returns the `TMechanicalLayerKind` ordinal. The full order, taken from
  the RTTI string table of `ScriptingSystem.dll` (identical in 11 Altium DLLs), is in `kit\mech_kinds.json`: 0 Undefined,
  1 AssemblyTop, 2 AssemblyBottom, 3 AssemblyNotes, 4 Board, 5 CoatingTop, 6 CoatingBottom, 7 ComponentCenterTop,
  8 ComponentCenterBottom, 9 ComponentOutlineTop, 10 ComponentOutlineBottom, 11 CourtyardTop, 12 CourtyardBottom,
  13 DesignatorTop, 14 DesignatorBottom, 15 Dimensions, 16 DimensionsTop, 17 DimensionsBottom, 18 FabNotes,
  19 GluePointsTop, 20 GluePointsBottom, 21 GoldPlatingTop, 22 GoldPlatingBottom, 23 ValueTop, 24 ValueBottom,
  25 VCut, 26 3DBodyTop, 27 3DBodyBottom, 28 RouteToolPath, 29 Sheet, 30 BoardShape, 31 OverlayTop … 48. It matches
  the ordinals altium-verify-2 §3.2 observed (1, 2, 11, 12, 26, 27).
* **Layer pairs and layer sets.** Instead of the unverified `IPCB_Board.MechanicalPairs` API, Altium itself saved a
  **copy** of the patched library (`kit\altium-scripts\07_resave_copy.pas`: open hidden, `SetFileName` to
  `E2E\resave\`, `DoFileSave`, close). Altium's own file has the same 32 layers, the same **11 pairs**
  (9/10 … 29/30) and the same "&All Layers" / "&Mechanical Layers" sets (31 mechanical layers each) as the patched one
  and as the user's stack. The original file is unchanged (same SHA-256). Note: `DoFileSave` into a folder that does
  not exist returns 0 without a dialog.
* **Footprints intact.** Per footprint the primitives per layer (pads, tracks, texts, bodies) are identical in Altium
  (`Layer2String`) and in the Rust reader (`kit\expected_pcblib.py` → `altium-logs\expected_PF_CHIP.json`):
  "primitives per layer identical for all footprints: True". `.Designator` on Mech 11, `.Comment` on Mech 19.
* **3D.** `RESC1608X50N` carries the embedded STEP model `RESC1608X50N.step` (`Embed=True`, `ModelType=1`,
  `DataSize=13543` = size of `3D\RESC1608X50N.step`) plus three extruded bodies; all four are 0.5 mm high.
  The footprint `Height` property is 0 (§6.2).

### 3.3 Automatic refresh and the "not found" cache [VERIFIED]

Before the series existed, Altium was asked for `CRCW06034K70FKEA` (`GetParametersForDBComponent` length 0,
`FindComponentLibraryPath` NOT found) – that creates Altium's negative cache entry (altium-refresh.md §7.2). After the
commit **no manual action**: the refresh service ran its job ~6 s later. Then, read-only
(`kit\altium-scripts\08_lookup_probe.pas`):

| Key | Parameters | Index (`FindComponentLibraryPath`) | Placement parameters | `LoadComponentFromDatabaseLibrary` |
| --- | --- | --- | --- | --- |
| CRCW06034K70FKEA (looked up before it existed) | 1623 chars | found | 1623 chars | Resistor, 2 pins |
| CRCW06031K00FKEA, CRCW060310K0FKEA | ✓ | found | ✓ | Resistor, 2 pins |

The same after the datasheet commit for `OPA656U`: parameters, index, symbol path `…\Symbols\PF_Analog.SchLib`,
`Op-Amp (SOIC8)` with 5 pins, Comment `OPA656U`, implementation `PCBLIB SOIC127P600X175-8N` current.

### 3.4 Placement and read-back [VERIFIED]

Hidden free SchDoc in `E2E\place\`, `LoadComponentFromDatabaseLibrary` → `RegisterSchObjectInContainer` →
`MoveToXY`, read back, `Modified := False`, `CloseDocument` (`kit\altium-scripts\09_place_on_temp_schdoc.pas`):

* **U1 = OPA656U:** `SourceLibraryName = DatabaseLibraryName = PF_E2E_Wave2.DbLib` (file name only), `LibraryPath=*`,
  table Amplifiers, DesignItemId and keys `OPA656U`, LibReference `Op-Amp (SOIC8)`, 5 pins, Comment `OPA656U`,
  description, 16 parameters (Manufacturer, MPN, Value, Package, Mounting, Height, Operating Temperature,
  ComponentLink1Description/URL, Lifecycle, Amplifier Type, Channels, GBW, Input Offset …), footprint
  `SOIC127P600X175-8N` current.
* **R1 = CRCW06034K70FKEA:** `Resistor`, 2 pins, Comment `4k7`, Resistance **visible** (`VisibleOnAdd=True`), all other
  parameters hidden, `RESC1608X50N` current, datasheet link = Vishay URL of the template.
* **Field-map options work as written:** `VisibleOnAdd=True` → visible; `AddMode=1` (PF Status, Notes, PF Created/
  Modified/Author) → **not added** to the placed part.
* **Comment is hidden** on both parts although the SchLib symbols carry a visible Comment (`kit\sym_params.py`:
  `{'name': 'Comment', 'value': '*', 'hidden': False}`): without a `Comment` field map Altium applies the default
  `VisibleOnAdd=False`. With `PATCH /categories/Amplifiers/fields/Comment {"show_on_schematic": true}` the auto-writer
  wrote `Amplifiers.Comment … VisibleOnAdd=True`, the automatic refresh rebuilt the index, and a new placement showed
  the Comment (`hidden=False`). See §6.1.
* `GetState_DatabaseLibraryKeys` on the placed part reopened the hidden DbLib document (as altium-refresh.md §3.3
  says); PartForge's next refresh closed it again.

---

## 4. Findings on the open questions of the module reports

| # | Question | Result |
| --- | --- | --- |
| 4.1 | `DefaultColumnType=TEXT` accepted? | Altium loads the DbLib with it (install, lookups, placement) **[VERIFIED]**. *Edit Supplier Links* (a modal dialog) was not run **[UNVERIFIED]** |
| 4.2 | Closing the hidden DbLib document while the Components panel shows that DbLib | **[UNVERIFIED]** (needs the user's panel) |
| 4.3 | Do deleted parts disappear with the close only (no rebuild)? | **Yes [VERIFIED]**: after `POST /parts/Resistors/delete` and the automatic close-only refresh, the deleted key has no parameters, **NOT found** in the index, no placement parameters; a neighbour key still resolves (`evidence\18_refresh_after_delete.json`) |
| 4.4 | Comment visibility with `VisibleOnAdd=False` | **Hidden [VERIFIED]**; visible with `VisibleOnAdd=True` **[VERIFIED]** (§3.4, §6.1) |
| 4.5 | Windows-1252 umlauts in the database path | **Work [VERIFIED]**: library `umlaut\Bauteile Übersicht` (examples, Rust writer, DbLib, ODBC test) installed through the bridge; Altium reports the path with `Ü`, resolves `RC0603FR-0710KL` (Resistor, 2 pins), `LM358DR` (Op-Amp Dual, 8), `61300411121` (Connector 1x04, 4) with symbol and footprint paths inside the umlaut folder; released and uninstalled (`evidence\20_umlaut_altium.txt`). Checked first outside Altium with ADO → MSDASQL → SQLite3 ODBC and PartForge's exact connection string (`kit\umlaut_ado.py`), so no failing connection was risked |
| 4.6 | Structure-only change (new plain column, no field map) with the close only | **Not enough [VERIFIED]**: the column is missing from parameters, placement parameters and the loaded component until `RefreshInstalledLibraries` runs. Fixed (§5.1) |
| 4.7 | DbLib rewritten while installed (new field map) | Altium uses the new file after PartForge's automatic refresh (close → rebuild → close), no reinstall, no restart **[VERIFIED]** (§3.4) |
| 4.8 | PartForge updates its script files while Altium has the script project loaded | Altium runs the **new** code at the next call (an extra `KV` added to `ping` appeared at once and disappeared after the revert) **[VERIFIED]** (`kit\stale_script_probe.py`) |
| 4.9 | Graphics before pins in Altium-written multi-part symbols | Altium **regroups the records by part** when it saves (LM358_DUAL: part 2, part 3, part 1), so the global order the test expected never holds; per part every graphic precedes the pins **[VERIFIED]**. Altium draws one part at a time, so the per-part order is what keeps pin names visible |
| 4.10 | Column removal | With the fix: rebuild, lookups work, the column is gone, no dialog **[VERIFIED]** (`evidence\22_refresh_removed_column.json`) |

---

## 5. Defects fixed in this stage

### 5.1 New/renamed/removed columns invisible after the automatic refresh – `partforge/altium/refresh.py`

* Cause [VERIFIED]: Altium caches the column list of every DbLib table in its library object (`FFieldCache`,
  altium-refresh.md §4). Closing the hidden document refreshes rows, not columns; only
  `IntegratedLibrary:RefreshInstalledLibraries` reloads them. `_on_schema_changed` requested `rebuild=False` for
  structure changes and for notifications without a baseline.
* Fix: both request `rebuild=True`; metadata-only edits still do nothing. Module docstring updated.
* Tests: `test_refresh_service.py` (classification, no-baseline case) updated; new live test
  `test_refresh_altium_live.py::test_new_column_is_visible_after_the_automatic_refresh` – fails with the old
  behaviour, passes with the fix. Re-checked through the HTTP API with the restarted server
  (`evidence\21_refresh_new_column_fixed.json`: Capacitors column visible after the automatic refresh).

### 5.2 Temporary installation leaked the hidden DbLib document – `bridge/scripts/PFLibraries.pas`, `bridge/core.py`

* Reproduced [VERIFIED]: `resolve_db_component` on a DbLib that is not installed → script installs it, resolves,
  `UninstallLibrary` → **document still open** (`document_state(...).open == True`). `refresh_dblib` cannot release it
  later because it only visits installed libraries, so the SQLite connection stays until Altium restarts (the folder
  cannot be moved or deleted meanwhile).
* Fix: `PFCmdResolveDbComponent` closes the hidden document before the temporary uninstall (only when unmodified, not
  shown and of kind `DATABASELIB`, same checks as `refresh_dblib`) and reports `released`;
  `DbComponentResolution.released: bool | None` (additive).
* Verified [VERIFIED]: `LM358DR` from the umlaut library, `temporarily_installed=True`, `released=True`, afterwards
  not installed and no document open (`evidence\25_resolve_temp_install_released.txt`); the final live run's
  `test_resolve_db_component` used the same path. Tests: `test_bridge_core.py`, `test_bridge_scripts.py`.

### 5.3 Reload made hidden libraries visible – `PFLibraries.pas` `PFCmdRefreshDocument`

* `refresh_document` (the sync's auto-reload) always called `ShowDocument` after reopening. A library that Altium or
  another script held open without an editor tab would pop up as a tab in the user's session.
* Fix: `ShowDocument` only if the document was shown before (response key `shown`).
* Verified [VERIFIED] with `kit\reload_hidden.py`: SchLib opened hidden (3 symbols) → Rust writer added
  `PF_RELOAD_TEST` → `refresh_document` = `reloaded` → still hidden, 4 symbols. Static test in
  `test_bridge_scripts.py`.

### 5.4 Live tests

* `test_bridge_live.py`, `test_refresh_altium_live.py`: a fresh `tmp_path` exchange directory per test left **one
  script project per test** loaded in Altium's Projects panel, pointing at folders pytest deletes later; the refresh
  live tests also used the user's real exchange directory. Now both use the stable `tests/_tmp/altium-live/exchange`
  (one project for all live runs; close it with `DM_CloseProject` after a run if it should not stay).
* `test_bridge_symbols_store_graphics_before_pins`: checks the order per part (§4.9) using the owner part of every
  record (`_drawing_order`).
* `test_bridge_scripts.py::test_dispatch_covers_every_command`: the magic number 12 (there are 14 commands) is
  replaced by "the command names the Python client sends = the dispatch branches" (contract change request of the
  DbLib module).

---

## 6. Remaining defects and proposals

### 6.1 Comment of placed DbLib parts is hidden (owner: db-core) – `partforge/db/templates.py:81`

**Fixed by db-core, VERIFIED in Welle 3 (§10.4).**

`F("Comment", "Kommentar (Schaltplan)", …)` has the default `show_on_schematic=False`, so the DbLib gets no Comment
field map and Altium places every part with a **hidden Comment** [VERIFIED]. That contradicts the house convention
(ARCHITEKTUR §4 "Comment = Wert … bzw. MPN", user-lib-style.md §3.6 "Comment is the only visible parameter") and the
field's own help text ("Wird im Schaltplan als Comment angezeigt"). Meanwhile the value fields
(`templates.py:118, 134, 135, 153, 169, 199, 337, 388`: Resistance, Capacitance, Voltage, Inductance, Impedance,
Frequency, Current Rating …) are `show_on_schematic=True`, so a resistor shows "4.7kΩ" (Resistance) instead of "4k7"
(Comment) and an IC shows only its designator.
**Fix:** `show_on_schematic=True` for `Comment` (verified to work, §3.4), plus a data migration of `pf_fields` for
existing libraries; decide with the user whether the value fields become `False` (house symbols show only the Comment).

### 6.2 Footprint `Height` = 0 in Altium (owner: writers) – `partforge/altium/rustwriter.py` (footprint JSON)

**Fixed and VERIFIED in Welle 3 (§10.2)** – the defect was larger: every Rust mutation reset all heights.

The Rust writer has no footprint-level height, so Altium's footprint `Height` property is 0 for every PartForge
footprint [VERIFIED], while the 3D bodies carry the correct heights. Impact on Altium's Height rule and component
properties [UNVERIFIED]. Proposal: after writing, patch the component's `HEIGHT=` in the PcbLib component record with
the same structured-storage approach as `stackup.patch_pcblib_layers`, or add the field to the Rust writer.

### 6.3 Verify needs one Altium script per part (owner: altium) – `partforge/api/routes_altium.py:657-670`

**Fixed and VERIFIED in Welle 3 (§10.3)** – one script run per 50 parts.

~1.4 s per part (19 parts 27.8 s, 29 parts 40.1 s; ~25 min for 1000 parts with `all=true`). It works (job, progress,
cancel), but a batch command `resolve_db_components` (e.g. 50 keys per script run) in `PFLibraries.pas` would cut this
by an order of magnitude. Needs a live check like every bridge command.

### 6.4 Stale tests of other modules (full suite: 2 failed, 4089 passed)

**Fixed in Welle 3 by the db and guard agents** (full suite green).

* `tests/test_api_parts.py:253` expects 15 example parts; db-core seeds 19 (ARCHITEKTUR §4). Update the expected counts.
* `tests/test_symbols_standard.py:183` expects `CategoryDef.default_symbol` to be a symbol **name**; it is a symbol
  **type key** (`resistor`, ARCHITEKTUR §4). Compare against `partforge.symbols.kinds()` keys.

### 6.5 Observations (no code change)

* The bridge script project `%LOCALAPPDATA%\PartForge\bridge\script\PartForgeBridge.PrjScr` stays loaded in Altium's
  Projects panel after the first bridge call (like altium-mcp's `Sandbox.PrjScr`); a running script cannot close its
  own project. Harmless – the path is stable. Whether Altium reopens it at the next start is [UNVERIFIED].
* A datasheet stored in the library becomes an **absolute** `ComponentLink1URL`
  (`…\Bibliothek\Datasheets\opa656_e9e615f9.pdf`), unlike every other path in the database; it breaks when the
  library folder moves. Whether Altium resolves a relative component link is [UNVERIFIED] (owner: datasheet).
* After an abrupt stop of PartForge the database keeps its `-wal` file until the next open (SQLite recovers it).

---

## 7. Still UNVERIFIED

1. The Components panel UI itself (repaint, behaviour while PartForge closes the hidden document). Every lookup that
   backs it (`FindComponentLibraryPath`, `GetComponentPlacementParameters`) was verified.
2. *Edit Supplier Links* and *Update Parameters From Database* (modal dialogs, not run).
3. The effect of footprint `Height = 0` on design rules.
4. Altium start-up behaviour with the PartForge script project loaded.
5. `IPCB_Board.MechanicalPairs` (avoided; the re-save copy answered the question instead).

---

## 8. Timings [VERIFIED]

| Operation | Time |
| --- | --- |
| One bridge command (script start + run) | 1.3 s (ping, install state, document state, close-only refresh) |
| Refresh with index rebuild | 4.1–4.7 s (`RefreshInstalledLibraries` 2.6–2.9 s with 21 installed libraries) |
| Automatic refresh after a write | first Altium action ~2 s after the last write (debounce), done ~6 s after it |
| Library write job (15 symbols + 13 footprints, 14 files, header patch) | 2.3 s |
| Install / uninstall job | 3.9 s / 5.2 s |
| Verify | ~1.4 s per part |
| Series commit (25 parts, no library writes) | 0.2 s |
| Datasheet: text 1.8 s, extraction (replay) 1.4 s, commit 1.5 s (incl. a 1.3 s document-state check) | |

---

## 9. Artefacts

* `E2E\evidence\00…26` – HTTP responses and job snapshots in run order (names in §3.1, §4, §5).
* `E2E\altium-logs\` – `00_baseline.txt`, `99_final_state.txt`, `06_pf_chip_altium.txt` (layers + primitives),
  `09_place_readback.txt`, `expected_PF_CHIP.json`, `full_suite_1.txt`.
* `E2E\kit\` – `e2e_server.py`, `e2e.py`, `expected_pcblib.py`, `compare_pcblib.py`, `mech_kinds.json`,
  `lockprobe.py`, `umlaut_ado.py`, `umlaut_e2e.py`, `reload_hidden.py`, `stale_script_probe.py`, `sym_params.py`,
  `dump_order.py`, `dump_keys.py`; `kit\altium-scripts\06/07/08/09_*.pas`.
* Code changed: `partforge/altium/refresh.py`, `partforge/altium/bridge/core.py`,
  `partforge/altium/bridge/scripts/PFLibraries.pas`, `tests/test_bridge_live.py`, `tests/test_refresh_altium_live.py`,
  `tests/test_refresh_service.py`, `tests/test_bridge_scripts.py`, `tests/test_bridge_core.py`.

---

## 10. Welle 3: footprint heights, batch verification, the chain after the db fixes

Agent: Altium fixes agent (exclusive use of the running Altium) · 2026-10-08, 11:30–13:00. Same Altium 26.10.1.5,
Rust writer 0.1.0, SQLite3 ODBC 0.99991. Working folder `E2E3` = `C:\PartForge-Examples\Tools\PartForge\tests\_tmp\e2e-wave3\`:

| Path | Content |
| --- | --- |
| `Bibliothek\` | the E2E library (DbLib `PF_E2E_Wave3.DbLib`): 19 examples, 25 series parts, OPA656U with datasheet |
| `moved\Bibliothek Kopie\` | a copy of the library, opened from the new folder (§10.6) |
| `evidence\NN_*.json` | HTTP responses and final job snapshots in run order |
| `altium-logs\` | Altium read-backs: baseline/final state, heights, placement, re-save comparison, lock probe |
| `kit\` | `e2e_server.py`, `e2e.py` (HTTP driver), `heights_check.py`, `resolve_probe.py`, `poll.py`, `lockprobe.py`; `kit\altium-scripts\*.pas` |
| `place\`, `resave\`, `home\` | temporary SchDoc, Altium's re-saved PcbLib copy, isolated `PARTFORGE_HOME` of the server |

### 10.0 TL;DR

1. **Footprint heights fixed [VERIFIED].** Altium reports `IPCB_LibComponent.Height` equal to `FootprintSpec.height`
   **to the coordinate** for all 13 example footprints, and for all 8 footprints of `PF_CHIP.PcbLib` after a series
   rewrote it. The libraries open hidden and unmodified without any dialog; when Altium saves a copy itself, the
   `Parameters` streams are **byte-identical** to PartForge's and the table of contents keeps the heights.
2. **The height defect was larger than reported [VERIFIED]:** every Rust mutation – append, update or delete, also of
   *another* footprint – rewrites **all** components with `HEIGHT=0mil`. A later PartForge write would also have
   erased heights saved in Altium. Fixed by reading the heights before and setting them after every mutation.
3. **Batch verification [VERIFIED]:** `resolve_db_components` resolves up to 50 parts per Altium script run.
   `POST /altium/verify {all}` for 45 parts: **7.5 s in one run** (wave 2: ~1.4 s per part, ~63 s); 19 examples
   6.3 s (wave 2: 27.8 s), 29 resistors 5.7 s (wave 2: 40.1 s). A live test resolves 55 keys in 2 runs, identical to the
   single lookup.
4. **The chain after the db fixes [VERIFIED]:** placed parts show the **Comment visible with the house text** (`4k7`,
   `100n 50V`) and every other parameter hidden; the batch verify reports the same for all 45 parts. Series commit →
   automatic refresh 6.4 s later → 29/29. A copied library folder opened through the API relocates the datasheet link
   (also as Altium resolves it). Live tests 12/12.
5. **Safety [VERIFIED]:** 7 sandbox scripts (`timeout_seconds=5`, own polling once, `dialogs_dismissed=0`),
   35 bridge runs of the E2E server (its log: no warning, no error), 1 of the probe and those of the 12 live tests –
   no wedge, `get_screenshot` never used, no user document touched; the final Altium state equals the baseline.

### 10.1 Safety log [VERIFIED]

| Item | Value |
| --- | --- |
| Baseline 12:06 (`altium-logs\00_baseline.txt`) | 20 installed IntLibs; projects Free Documents (0), `1355.PrjPcb` (31), `HPI_Award.PrjPcb` (13), `Sandbox.PrjScr` (1), `%LOCALAPPDATA%\PartForge\bridge\script\PartForgeBridge.PrjScr` (5); focused Free Documents (= wave 2's final state) |
| Final 12:40 (`altium-logs\99_final_state.txt`) | identical to the baseline (29 of 29 lines) |
| Sandbox scripts | 7: baseline, heights of 6 PcbLibs, re-save copy, placement, heights after the series, close live project + final state, final-code re-check of the heights (own temporary PcbLib, opened hidden and closed). The heights script ran ~7 s: the tool reported "did not finish" after its 5 s window, the script finished on its own (`sandbox end` in the log) and its result was read by polling `sandbox_result.json` (`kit\poll.py`); every later script ran normally |
| Documents | all opened hidden and closed again: 6 PcbLibs (+ PF_CHIP twice more), the temporary SchDoc (closed with `Modified := False`, placement discarded) |
| Libraries | `PF_E2E_Wave3.DbLib` installed and uninstalled; the moved copy only installed temporarily (verify job, batch command) and released; the unique `PF_Live_*.DbLib` of the live tests |
| Script projects | the live tests' project `tests\_tmp\altium-live\exchange\script\PartForgeBridge.PrjScr` was closed with `DM_CloseProject` after checking that none of its 5 documents was open |
| Databases | no process holds either E2E database afterwards (`altium-logs\98_lockprobe.txt`: every lock byte free) |
| Other PartForge servers | one more server ran (port 8812); the E2E library used its own DbLib file name |

### 10.2 Footprint height – `partforge/altium/heights.py`, `compound.py`, `rustwriter.py`

**Format [VERIFIED]** from PcbLibs Altium 26.10 wrote itself (Altium backend, wave-2 live tests `PF_Cycle.PcbLib`,
`PF_Live.PcbLib`): component `Parameters` = `u32 length` + `|PATTERN=RESC1608X55N|HEIGHT=21.6535mil|DESCRIPTION=…|`
`ITEMGUID=|REVISIONGUID=` + NUL; table of contents `Library/ComponentParamsTOC/Data` = `u32 length` + one line
`Name=…|Pad Count=2|Height=21.6535|Description=…` CRLF per component + NUL (mil **without** unit). The value is the
height in Altium's coordinate (1/10000 mil, **rounded**) with at most four decimals: 0.55 mm → `21.6535`, 1.75 mm →
`68.8976`, 8.5 mm → `334.6457` (truncating would give `334.6456`).

**Rust writer behaviour [VERIFIED]** (experiment with the real writer, then regression tests): a fresh write stores
`HEIGHT=0mil` and `Height=0` for every footprint; after setting a height, an **append** of another footprint, an
**update** of another footprint and a **delete** of another footprint each reset it to `0mil` – the writer rebuilds
every component record from its own model, which has no height.

**Fix.** `RustLibraryOps` reads the heights before every PcbLib mutation (`upsert_footprints`,
`write_library_full`, `delete_components`) and afterwards sets every component again: the footprints of the call get
`heights.footprint_height(spec)` (`spec.height`, else the top of the highest 3D body – the Altium backend's rule),
every other component and a call footprint of unknown height keep their previous value (also heights saved in
Altium). `heights.patch_footprint_heights` changes only the `HEIGHT=` value of the `Parameters` streams and the
`Height=` value of the table of contents, with the safety of the layer header patch: plan + self-check, write into a
copy (`<stem>.pfhgt<hex>`, structured storage, transacted commit), re-read of the whole copy (only the planned streams
differ), Rust reader lists the same components, atomic replace; any unexpected structure (missing/duplicate
`PATTERN`/`HEIGHT`, bad lengths, duplicate names in the table of contents …) leaves the file untouched with a German
warning, a patch never fails a write. Idempotent; switch `PARTFORGE_HEIGHT_PATCH=0`. Components are matched by
`PATTERN` (full name), so 31-character storage names do not matter. The shared structured-storage code moved to
`compound.py` (`replace_streams`); `stackup.patch_pcblib_layers` uses it unchanged in behaviour.

**Live check [VERIFIED]** (`altium-logs\02_heights_files.json`, `03_heights_altium.txt`): every PcbLib opened hidden
(`IsShown=False`, `Modified=False`, component count as written), heights read, closed:

| Footprint | mm | Altium `Height` (1/10000 mil) |
| --- | --- | --- |
| RESC1608X50N / CAPC1608X87N / CAPC2012X145N | 0.5 / 0.87 / 1.45 | 196850 / 342520 / 570866 |
| INDC1608X95N / LEDC1608X80N / XTAL3215X90N / FUSC3216X60N | 0.95 / 0.8 / 0.9 / 0.6 | 374016 / 314961 / 354331 / 236220 |
| SOD3716X135N / SOT95P237X112-3N / SOT95P280X145-5N | 1.35 / 1.12 / 1.45 | 531496 / 440945 / 570866 |
| SOIC127P600X175-8N / INDM125125X650N_6E43 / HDRV4W64P254_1X4_1016X254X854B | 1.75 / 6.5 / 8.54 | 688976 / 2559055 / 3362205 |

All 13 equal the expected coordinate. **Altium's own re-save** (`PF_CHIP` opened hidden, `SetFileName` →
`E2E3\resave\`, `DoFileSave` = -1, closed; `altium-logs\04_resave_compare.json`): the seven `Parameters` streams are
byte-identical to PartForge's, the table of contents has the same heights, the layer header has no problems, the
original is unchanged (same SHA-256). After the series of §10.5 rewrote `PF_CHIP` with the new `RESC2012X60N`, Altium
showed 8/8 heights (`altium-logs\13_heights_after_series_altium.txt`). Final-code re-check
(`kit\recheck_write.py`, `altium-logs\32_recheck_heights_altium.txt`): full write, append of a third footprint,
update of another one – Altium shows 216535 / 688976 / 3346457 (0.55 / 1.75 / 8.5 mm).

### 10.3 Batch verification – `bridge/scripts/PFLibraries.pas`, `bridge/core.py`, `api/routes_altium.py`

* New bridge command **`resolve_db_components`** (`PFCmdResolveDbComponents` + `PFResolveOne`); it replaces the
  single-key command, `AltiumBridge.resolve_db_component` is a batch of one. Arguments `count`, `table<i>`, `key<i>`;
  every output row carries the key index (`ROW|res|i|…`, `raw`, `models`, `parameters`), `KV|count` comes after the
  loop – a run that stopped midway raises `BridgeCommandError` and is never read as "not found". Per key the same
  fields as before plus `comment_visible` and `visible_parameters`. A DbLib that is not installed is installed once per
  run and released (hidden document closed) before the uninstall. Python sends at most `RESOLVE_BATCH_SIZE` = 50 keys
  per run (hard limit `PF_MAX_RESOLVE` = 200 in the script).
* **`POST /altium/verify`**: one run per 50 parts; cancellation and progress between runs; a failing run marks only
  its own parts as errors. The result has `altium_runs` and `resolve_s`; `VerifiedPart` has `comment`,
  `comment_visible`, `visible_parameters` (additive).

Timings [VERIFIED] (`evidence\05`, `11`, `20`, `21`, `27`):

| Verify | Parts | Script runs | Lookups | Job total | Wave 2 |
| --- | --- | --- | --- | --- | --- |
| Amplifiers | 3 | 1 | 1.8 s | 4.5 s | 6.6 s |
| all examples | 19 | 1 | 2.8 s | 6.3 s | 27.8 s |
| Resistors (4 examples + 25 series) | 29 | 1 | 3.1 s | 5.7 s | 40.1 s |
| whole library | 45 | 1 | 4.6 s | 7.5 s | (~63 s) |
| moved copy, temporary installation | 45 | 1 | 4.6 s | 10.4 s | – |

One run costs about 1.6 s plus about 67 ms per part (wave 2: 1.4 s per part). 1000 parts: about 100 s instead of
about 25 min [UNVERIFIED extrapolation]. The job total includes the install-state check and the refresh before the
lookups (about 1.3 s each).

* Live: `test_resolve_db_components_in_several_runs` – 55 keys (50 + 5 in two runs) incl. an unknown key: request
  order kept, the unknown key is "not loaded", every other result equals the single lookup. Temporary install inside
  the script: OPA656U from the not installed moved DbLib → `temporarily_installed=True`, `released=True`, afterwards
  not installed and no document open (`evidence\28_resolve_moved_links.json`).

### 10.4 Comment visible after the db fixes [VERIFIED]

* The DbLib has `VisibleOnAdd=True` for exactly the `Comment` field map of all 19 tables; the value fields are
  `VisibleOnAdd=False`.
* Batch verify (`evidence\21_verify_all_45.json`): 45/45 `comment_visible=True`, the only visible parameter is
  `Comment`; Comments `100R` `10k` `1k` `4k7` (resistors), `100n 50V` `10u 25V` (capacitors), `10u`, `220R@100MHz`,
  `Rot`, `32.768kHz`, `1A`, the MPN for semiconductors and ICs, `1k1`…`10k` for the series.
* **Placement** on a hidden temporary SchDoc (`kit\altium-scripts\07_place_on_temp_schdoc.pas`,
  `altium-logs\07_place_readback.txt`): R1 = `RC0603FR-074K7L` (Resistor, 2 pins, `RESC1608X50N` current) and
  C1 = `GRM188R71H104KA93D` (Capacitor, `CAPC1608X87N` current): **Comment `4k7` / `100n 50V` visible**, all other
  parameters hidden (`Resistance`, `Capacitance`, `Value`, `Voltage`, `Tolerance` …), designator visible; sheet closed
  without saving, no DbLib document left open. The loaded (not yet placed) component of the batch resolve has the same
  visibility as the placed one, so verify can report it for every part.

### 10.5 Series → automatic refresh → verify [VERIFIED]

`POST /series/commit` Vishay CRCW **0805** E24 1k–10k (25 parts, new footprint `RESC2012X60N` 0.6 mm, symbol reused):
2.1 s; `PF_CHIP.PcbLib` rewritten with 8 footprints, all heights correct (file and Altium, §10.2). The refresh
service ran by itself: index rebuild 4.8 s, done 6.4 s after the commit. Verify Resistors 29/29 ok, new parts on
`RESC2012X60N`. The same after the datasheet commit (OPA656U): automatic rebuild 4.3 s, verify Amplifiers 3/3.

### 10.6 Moved library folder [VERIFIED]

OPA656U from `opa656.pdf` (recorded Claude answers, no network) has the absolute link
`…\e2e-wave3\Bibliothek\Datasheets\opa656_e9e615f9.pdf`. Uninstall, `POST /workspace/close`, folder copied to
`E2E3\moved\Bibliothek Kopie\` (WAL fully checkpointed, no lock held), `POST /workspace/open` of the copy:

* the link points into the copy (`…\moved\Bibliothek Kopie\Datasheets\opa656_e9e615f9.pdf`, file present); one audit
  entry (`bulk_update`, author PartForge) and the log line "Bibliotheksordner verschoben (…): 1 Verweise in 1
  Bauteilen angepasst."; the original database is unchanged;
* the DbLib of the copy was rewritten to the copy's database (`Database=` and `LibraryDatabasePath=`);
* Altium (verify with temporary installation): 45/45 ok, symbol and footprint libraries resolved inside the copy;
  the batch resolve returns `ComponentLink1URL` = the copy's PDF.

### 10.7 Live tests (`pytest -m altium`, `PARTFORGE_TEST_ALTIUM=1`) [VERIFIED]

`evidence\22_live_tests_run1.txt`: **12 passed in 89 s** – `test_bridge_live` (7, incl. the new multi-run batch test;
`PARTFORGE_TEST_DBLIB` = the E2E DbLib) and `test_refresh_altium_live` (5, all lookups now through the batch command).

### 10.8 Still UNVERIFIED / open

1. The effect of the footprint height on Altium's design rules (component clearance with heights) – only the
   property and the file were checked.
2. Libraries written **before** this fix get their heights when PartForge next writes them: a managed library is
   regenerated as a whole (all heights set); in a library that is only upserted, older PartForge footprints keep 0
   until they are written again [inference]. A repair action could patch them from the registry.
3. The Altium backend (bridge writer) rebuilds untouched footprints from the Rust read-back, whose height comes from
   the 3D bodies; a `HEIGHT` without bodies would be lost there [inference; PartForge's own footprints always have
   bodies].
4. Components panel UI (unchanged from §7).

### 10.9 Artefacts and code

* `E2E3\evidence\01…31` (`01_create`, `03_odbc`, `04_install`, `05_verify_examples`, `08/09_series_*`,
  `10_refresh_after_series`, `11_verify_resistors`, `14…17_ds_*`, `19_refresh_after_datasheet`, `20_verify_amplifiers`,
  `21_verify_all_45`, `22_live_tests_run1.txt`, `23_uninstall_original`, `25_open_moved`, `26_opa656u_after_move`,
  `27_verify_moved`, `28_resolve_moved_links`, `29…31` final checks), `E2E3\altium-logs\00…99`.
* Code: `partforge/altium/heights.py` (new), `partforge/altium/compound.py` (new, shared structured storage),
  `partforge/altium/stackup.py` (uses `compound`), `partforge/altium/rustwriter.py` (height hook),
  `partforge/altium/libwriter.py` (temporary copy `*.pfhgt<hex>` never listed), `partforge/altium/bridge/core.py`,
  `bridge/scripts/PFLibraries.pas`, `PFUtils.pas`, `PartForgeBridge.pas`, `partforge/api/routes_altium.py`.
* Tests: `tests/test_stackup_heights.py` (new), `test_sync_support.py`, `test_sync_rust.py`, `test_bridge_core.py`,
  `test_bridge_scripts.py`, `test_bridge_live.py`, `test_api_altium.py`.
