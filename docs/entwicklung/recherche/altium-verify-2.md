# Altium verification, round 2: Rust libraries in Altium, DbLib follow-ups, lock/reload

Agent: Altium-access agent (exclusive use of the running Altium) · 2026-10-07, 22:17–23:20
Altium: `C:\Program Files\Altium\AD22\X2.EXE`, **26.10.1.5**.
Working folder: `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/altium-verify2/` (abbreviated `V2`).
Kit used: `.../scratchpad/altium-verify-rust/` (`AV`).

Every statement is tagged **[VERIFIED]** (observed in Altium 26.10 or measured in this run) or **[UNVERIFIED]** (inference, or not testable in this session).

---

## 0. TL;DR

1. **Altium is back to its starting state [VERIFIED]:**
   * Installed libraries are the original 20; `PF_Test_abs.DbLib` and the 6 DbLibs I installed are gone.
   * Same 4 projects; Free Documents is empty; no modal dialog; nothing of the user's was touched or saved.
   * Cosmetic differences: the focused project is now "Free Documents" (it was `Sandbox.PrjScr`), and `Sandbox.pas` holds my last script body (the tool's normal mechanism).
   * Altium keeps ODBC handles on my two scratchpad test DBs until it restarts (§5.2).
2. **The executor never wedged.** Every `run_altium_script` call used `timeout_seconds=5` with self-polling. No dialog sweep was triggered and no dialog ever appeared.
3. **Rust writer → Altium [VERIFIED]: all 15 libraries open** without dialogs, including both 1000-part files.
   * After presentation normalisation (§3.1), geometry matches the writer's intent with **0 differences in 10 of 12 compared libraries**. The two remaining libraries differ only by real findings (pad stacks, Unicode name).
   * Several format problems are now confirmed in Altium. The most visible one is new: **pin names are invisible on every Rust symbol with a filled body.** The writer emits pins before the body, so Altium paints the fill over the names.
   * Fix: `primitive_order` with graphics first. This was verified end-to-end (§3.3).
4. **DbLib on SQLite [VERIFIED]:**
   * Unicode arrives exactly in Altium: U+03A9, U+00B5, U+00B1 and U+00FC were checked byte-exactly in a saved SchDoc.
   * `VARCHAR(255)` truncates to 255 characters. REAL/NUMERIC values render with the German decimal comma.
   * Relative Library and Footprint paths resolve against the DbLib folder. A relative **database** path does not: it resolves against Altium's CWD, and `DatabasePathRelative` is ignored for ODBC strings.
   * Placing a DbLib part works and reads back correctly. Bridge timing for 50 footprints: 0.55 s.
5. **Lock and refresh [VERIFIED]:**
   * Altium holds **no** handle on an open PcbLib, so the Rust exe can rewrite it. Altium does not notice by itself; close plus reopen through the bridge refreshes it.
   * For SQLite, Altium's DbLib connection **blocks all writers in DELETE journal mode for the whole session**. **WAL mode** allows concurrent writes.
   * However, a DbLib path that has already been used **keeps showing its first snapshot**. Reinstall, RefreshInstalledLibraries, Deactivate/Activate and editing the DbLib file do not help. Only a new DbLib path sees new rows.

---

## 1. Safety log and state handling [VERIFIED]

| Item | Value |
|---|---|
| Baseline (22:19) | 21 installed (20 originals + `altium-live\PF_Test_abs.DbLib`); projects: Free Documents (0), `1355.PrjPcb`, `HPI_Award.PrjPcb`, `Sandbox.PrjScr`; focused project `Sandbox.PrjScr` (`V2/logs/00_baseline_before.txt`) |
| Script runs | About 70 `run_altium_script` calls, all with timeout 5 s. Long runs (1000-part open, 50-footprint build, RefreshInstalledLibraries, close-all) were polled from `C:\Users\Public\altium_mcp\sandbox_result.json`. No `Exit`; no `Ord`; no indexing of string properties; no non-ASCII literals. |
| `get_screenshot` | Never used. Screenshots came from `AV/scripts/capture_window.ps1` (PrintWindow, read-only) and `V2/kit/screen_capture.ps1` (CopyFromScreen, read-only). |
| Final (23:19) | 20 installed, identical list; projects: the same 4; Free Documents 0; no dialog windows (`capture_window.ps1 -ListOnly`). |
| Closed | 16 library documents, 2 temp SchDocs, 1 temp PcbLib. None was modified (`V2/logs/close_all.txt`). |
| Extra project | `Altium_API.PrjScr` (altium-mcp's own script project) had been loaded by the `get_*_primitives` tools. I closed it with `DM_CloseProject` after checking that none of its documents was loaded or modified. |
| Display | The user's monitors had switched off (5-min timeout). For 15 min I held a display power request (`SetThreadExecutionState`, `V2/kit/display_on.ps1`). No input was sent to any window. The user became active again at about 23:00. |

**Bridge hazard found [VERIFIED].** altium-mcp's `get_*_primitives(library_path=...)` opens documents under a path with **doubled backslashes**. The JSON escape is not decoded: Free Documents lists `C:\\Users\\...`.
* As a result, `Client.IsDocumentOpen` and `GetDocumentByPath` with a normal path return False or nil.
* A second `OpenDocument` with the normal path then creates a **second, hidden instance of the same file**. I created two that way and closed them.
* PartForge's bridge must use one canonical path spelling.

---

## 2. Task A: probe and cleanup [VERIFIED]

* Probe `kit/00_probe.txt` returned `alive 26.10.1.5`.
* `altium-live/followup/00_cleanup_uninstall.txt` uninstalled 1 library (`PF_Test_abs.DbLib`). Installed count went 21 → 20, the original 20.

---

## 3. Task B: Rust-written libraries in Altium

### 3.1 Method

* **Dumps:**
  * Kit dumps (`get_symbol_primitives` / `get_footprint_primitives` with `"*"`).
  * For the larger libraries, a file-based compact dumper with the same property calls as altium-mcp's production code (`V2/kit/pcb_dump.tmpl` → `V2/kit/compact2json.py`).
  * Comparator: `AV/scripts/altium_compare.py` via `V2/kit/norm_compare.py`.
* **Normalisations, each a presentation artefact verified in Altium:**
  * The footprint that is *current* in the PcbLib editor is reported in absolute board coordinates. The library origin is `Board.XOrigin/YOrigin` = 50000/50000 mil, so I subtract it for that footprint.
  * `Layer2String` returns `Mechanical Layer N`.
  * Tracks of the current footprint come back with start and end swapped.
  * Region contours start at a different vertex of the same cycle.

### 3.2 Checklist 5.4

| # | Item | Result |
|---|---|---|
| 1 | Opens with no dialog; counts; Modified=False | **[VERIFIED]** All 15: example_12_4 (3), PartForge_Test.SchLib (4), PartForge_Features.SchLib (1), errors.SchLib (16), probe_enums (5), perf_1000.SchLib (1000), example_12_1 (3), PartForge_Test.PcbLib (5), PartForge_Features.PcbLib (4), errors.PcbLib (20), probe_mech_layers (38), probe_stack (4), probe_stack2 (7), PartForge_Test_reimported (5), perf_1000.PcbLib (1000). All `Modified=False` from opening to close. Also my own `order_test.SchLib` and `lock_test.PcbLib`. |
| 2 | Comparator (pins, pads) | **[VERIFIED]** 0 issues: example_12_4, PartForge_Test.SchLib, errors.SchLib, example_12_1, PartForge_Test.PcbLib, PartForge_Features.PcbLib, probe_mech_layers, reimported. Remaining issues: GRAPHICS_TEST pin 3 at x=-395 mil (correct; the expected file ignores the frac offset +50000/100000 unit); probe_stack ×4 and probe_stack2 ×1 (item 9); errors.PcbLib Unicode name (item 6). Details are in `V2/issues/*.json`. |
| 3 | LM358DR parts A/B/C; Comment on part B | **[VERIFIED]** API `PartCount=3`. Placed on a schematic, parts A, B and C render, and **part B (U1B, U3B) displays the Comment "LM358DR"** although its parameter has `OwnerPartId=1` (screenshots `shots/10_*`, `11_*`). `OwnerPartId=1` survives placement unchanged. **No workaround needed.** |
| 4 | NE555 overbar and dot | **[VERIFIED]** `R̅E̅S̅E̅T̅` overbar and the outer-edge dot on pin 4 render correctly (`shots/13_ne555_unfilled_zoom.png`). The names only become visible once the body fill no longer covers them (§3.3). |
| 5 | GRAPHICS_TEST: OC glyph, RECORD=3 | **[VERIFIED]** The OC pin shows the **postponed-output** glyph (stored 8). `RECORD=3` loads as an IEEE-symbol object (`ObjectId 34 = eSymbol`, `Symbol=0`), so **the text is invisible**. LABEL (RECORD=4), all graphic primitives, the text frame with word wrap, the embedded image, the frac pin, the hidden pin and the bidirectional pin all render (`shots/16_graphics_test_zoom.png`). |
| 5b | All decoration ordinals | **[VERIFIED]** Altium reads the stored byte as `TIeeeSymbol` (`V2/altium/pin_decorations.txt`) and draws its glyph (`shots/15_probe_inside_top.png`). `postponed_output` shows ShiftRight, `open_collector` shows PostponedOutput, `hi_z` shows OpenCollector, `high_current` shows HiZ, `pulse` shows HighCurrent, `schmitt` shows Pulse, `active_low_output` shows Schmitt, and so on, exactly as in AV §3.1. The seven ordinals 0–6 are correct. |
| 6 | Unicode and long names | **[VERIFIED]** SchLib parameters `±1%` and `10kΩ` are decoded from `%UTF8%Text` exactly: U+00B1 and U+03A9, byte-checked in a saved SchDoc. **The footprint name `R_Ω_µ` appears as `R_Î©_Âµ`** (UTF-8 bytes read as cp1252). The PcbLib description stores `Ω` as `?`: the Rust writer is lossy here (Latin-1). Names of 31, 32 and 80 characters (footprints) and 40 characters (symbols) display in full. |
| 7 | STEP model, DataSize, heights | **[VERIFIED API]** The `CAPC2012X125N` body has a model with `Name=CAPC2012X125N_box.step`, `Embed=True`, `ModelType=1`, `DataSize=6285` (equal to the STEP file size) and a checksum Altium computes itself. **`OverallHeight=0`, `StandoffHeight=0`**, and the footprint `Height=0` for every Rust footprint. Extruded heights are correct: 0.55, 1.75/0.1, 2.54, 0.6, 1.0 and 0.8 mm. **[UNVERIFIED visually]**: the 3D view could not be captured (§3.6). |
| 8 | Mech 2/4/6 kinds | **[VERIFIED]** Kinds: Mech2 `Top Assembly` 1, Mech3 `Bottom Assembly` 2, Mech4 `Top Courtyard` 11, Mech5 `Bottom Courtyard` 12, Mech6 `Top 3D Body` 26, Mech7 `Bottom 3D Body` 27; Mech 13/15 are plain (0). The numbers are `TMechanicalLayerKind` RTTI ordinals from `ScriptingSystem.dll`. The editor's layer tabs show the typed names. probe_mech_layers: all 38 footprints sit on the intended layers, Mech 17–32 included. Only Mech 1–7, 13 and 15 are *enabled* in the library layer stack. |
| 9 | probe_stack2 S_J and S_A | **[VERIFIED API]** For top-mid-bottom stacks, Altium uses the size-and-shape block. Per-layer shapes survive **only** when an explicit pad-level shape without that block is given: `rectangle` (S_E → rect/round/oct) or `round` (DCJACK pad 4 → round/round/oct, as intended). With `rounded_rectangle` (S_J) or an omitted shape (S_A–S_D, written without `shape`, so default RR 50 %; their read-back merely reports the legacy byte) every layer becomes a rounded rectangle (shape 9). All simple pads are correct. |
| 10 | Footprint-link resolution | **[VERIFIED]** `DatafileLink[0].Location` holds the forward-slash absolute path verbatim. `IntMan.FindDatafileInStandardLibs` resolves `RESC1608X55N` and the SOIC to that PcbLib. Missing footprints, and links without a path to a library that isn't installed, resolve to `''` (`logs/footprint_link_resolution.txt`). |
| 11 | 1000-part files | **[VERIFIED]** PcbLib: opened hidden in **18.25 s**, 1000 footprints and 2000 pads, names correct. SchLib: **0.45 s**, 1000 symbols and 2000 pins. Neither showed a dialog. |

### 3.3 New and confirmed findings

1. **Pin names are hidden behind filled bodies [VERIFIED, high impact].**
   * The Rust writer emits pins first, then rectangles and polygons (default `filled`/`is_solid=True`). Altium draws in record order, so the fill covers the pin names and inside glyphs. Pin numbers, lines, edge glyphs and parameters stay visible.
   * Proof chain:
     * The native symbol `SN74AHC1G04DBVR` on the same sheet shows its names.
     * The Rust NE555 shows none, although `ShowName=True` and the font and position modes are identical.
     * Making the body unfilled shows all names.
     * **`write_schlib` with `primitive_order: ["rectangle", "pin"×8, "parameter"]`** stores RECORD=14 before the pins, and Altium then shows all names (`shots/14_order_test_canvas.png`, symbols D1 vs F1).
   * Setting PinConglomerate bit 0x20 (native files always set it) has **no** visible effect (patched copy `V2/libs/PartForge_Test_bit20.SchLib`).
2. **Text justification [VERIFIED].** Single-line stroke text written as `middle_center` is anchored bottom-left in Altium: SOIC `.Designator` at location (0,0) has bbox (-4,-14)…(319,35) mil. The `MultilineTextAutoPosition`/`TTFInvertedTextJustify` value (5) only applies to frame or inverted text.
3. **Via tenting [VERIFIED API].** Vias written with `TENTING_TOP | TENTING_BOTTOM` report `IsTenting_Top/Bottom = False`. The EP manual paste −0.85 mm and solder +0.05 mm are honoured.
4. **`export_library` → `import_library` loses the embedded STEP [VERIFIED].**
   * In `PartForge_Test_reimported.PcbLib` the body record still names the model, but `Library/Models/Data` is empty and `Library/Models/0` is missing.
   * Altium shows an empty extruded body (DataSize 0, height 0).
   * Rust's own `compare_components` called it "identical".
5. **External STEP (`embed:false`) gives an empty, 0-height body** in Altium [VERIFIED] (`EXT_STEP_REF`).
6. **Placement API [VERIFIED].** Setting `ISch_Component.Location` before `RegisterSchObjectInContainer` moves only the anchor; the children stay at library coordinates. Use `MoveToXY` after registration. `LoadComponentFromLibrary(LibRef, <full path>)` works for any SchLib file, the native examples included.

### 3.4 Screenshots [VERIFIED where listed]

| File | Content |
|---|---|
| `V2/shots/01_PartForge_Test_PcbLib_current.png`, `02_RESC1608X55N_view.png` | 2D CAPC2012X125N and RESC1608X55N: RR 25 % pads, silk, Top Assembly, Top Courtyard, hatched 3D-body area. The PCB Library panel shows typed layer names. |
| `03_SOIC127P600X175-8N_screen.png`, `08_QFN_panel_preview.png` | The SOIC and QFN appear only in the panel lists and previews: pad 1 2.0 mm, 4 vias "Top Layer to Bottom". The main canvas was stale (§3.6). |
| `10_place_test_full_small.png`, `11_*`, `12_*`, `13_ne555_unfilled_zoom.png`, `14_order_test_canvas.png`, `15_probe_inside_top.png`, `16_graphics_test_zoom.png` | Schematic: LM358DR A/B/C, NE555DR (names hidden; visible once unfilled), native vs bit20-patched vs primitive_order symbols, decoration glyphs, GRAPHICS_TEST |

### 3.5 Bridge facts collected on the way [VERIFIED]

* `ISch_Component.PartCount` returns parts (3), while the file stores parts+1 (4).
* `IPCB_Library.Navigate_Component(name)` changes the panel and preview.
* `ClientAPI` preference: `HKCU\...\Client Preferences\ReloadDocumentsModifiedOutside = AskIfModified`. The enum values are `coNever / coAlways / coAskFirst / coAskIfModified`.
* DelphiScript `Chr(n)` wraps modulo 256. `UTF8Encode`/`UTF8Decode` are unusable through Variants.
* `TStringList.SaveToFile` best-fits `Ω`→`O` and other non-cp1252 characters→`?`. For exact Unicode, save a temp SchDoc and parse its `%UTF8%` keys.

### 3.6 Limitation: GPU canvas [VERIFIED symptom, UNVERIFIED cause]

* After the monitors had switched off, the PCB editor canvas stopped presenting new frames. It still showed the 0603 after navigating, zooming, redrawing, switching tabs, switching to 3D, and `RedrawWindow`. Panels and previews kept updating.
* New schematic documents did render through PrintWindow.
* Consequently there is no PCB 2D/3D screenshot of the SOIC, the QFN, or the STEP model in 3D.
* `get_screenshot` was not used (rule 3).

---

## 4. Task C: DbLib follow-ups (`V2/db/`: fresh copy of the test DB and libraries; `V2/altium/dblib_resolve.txt`)

| Topic | Result |
|---|---|
| Speed | **[VERIFIED]** `InstallLibrary` 62 ms. 13 records (SchLib path/ref, parameters, `LoadComponentFromDatabaseLibrary`, footprint path) took 421 ms in total. |
| Unicode inside Altium, TEXT and VARCHAR | **[VERIFIED, byte-exact]** Temp SchDoc saved and parsed with olefile (`PF_Place_Test.SchDoc`). `10 kΩ` → U+03A9 (TEXT table); `4.7 MΩ`; `4.7 µF` → U+00B5 (VARCHAR table); `±1 %` → U+00B1; untyped column `ü` → U+00FC. Altium writes `Text=` as a cp1252 best-fit (`10 kO`) plus `%UTF8%Text=` holding the exact value. |
| VARCHAR(255) | **[VERIFIED]** Lookups work. **The 284-character Description is truncated to 255** (`desclen=255`, CAP-0003). In the TEXT table it stays 284 (RES-0006). ADO outside Altium returns 284, so Altium truncates to the declared size. |
| Typed columns | **[VERIFIED]** REAL 4.7 → `"4,7"`, NUMERIC 2.25 → `"2,25"` (German locale); INTEGER → `"1500"`. |
| Views | **[VERIFIED]** `Resistors_0603` and `AllPassives` (UNION with expression and constant columns) resolve and place. |
| Library Path variants | **[VERIFIED]** `libs\…` and `libs/…` resolve against the DbLib folder; absolute paths work. A bare `PF_Test.SchLib` (not next to the DbLib) and an empty path give **LOAD=NIL**: there is no implicit search. A missing symbol (RES-0007) also gives NIL, without a dialog. |
| Footprint Path (relative) | **[VERIFIED]** `IntMan.GetDatabaseModelFullLibPath(DbLib, rawPath, Model, 'PCBLIB')` resolves `libs\PF_Test.PcbLib` and `libs/…` to the absolute path in the DbLib folder. The placed parts carry the implementation `PF_R0603`/`PF_C0603` with 1 link. |
| Symbol-embedded links | **[VERIFIED]** A symbol's own footprint link is **kept in addition** to the DB footprint (RES-0006: PF_R0603 from the symbol plus PF_R0805 from the DB, both `IsCurrent=True`). |
| Relative DB path / `DatabasePathRelative` | **[VERIFIED]** Altium passes the ODBC connection string through unchanged (`GetConnectionString` echoes it). The SQLite3 ODBC driver resolves `Database=` against the **process CWD** (Altium: `C:\Program Files\Altium\AD22`). `LibraryDatabasePath` (absolute or relative) and `DatabasePathRelative=0/1` were **ignored**: both probes read `MARKER_CWD` (`logs/relpath_probe.txt`). This was proven with a design in which every branch connects, so no failing connection was risked. |
| Placement and read-back | **[VERIFIED]** Free SchDoc → `LoadComponentFromDatabaseLibrary` → `RegisterSchObjectInContainer` → read-back (`altium/place_test.txt`): `SourceLibraryName=PF_V2_abs.DbLib` (file name only), `DatabaseTableName`, `DesignItemId`, `GetState_DatabaseLibraryKeys('|')`, footprint implementation. Parameters are `OwnerPartId=-1` and hidden (VisibleOnAdd=False). Saved component records: `LibraryPath=*`, `SourceLibraryName=<DbLib name>`. |
| 50 footprints via the bridge | **[VERIFIED]** New PcbLib 1.47 s; first footprint 0.34 s (one-time init); all 50 in **0.55 s** (≈4 ms each); save 0.19 s; close 0.97 s; about 3.2 s plus about 1 s launch. The Rust exe needs about 0.47 s for 50 footprints in one call. |

---

## 5. Task D: lock and reload behaviour

### 5.1 Rust write to an open PcbLib (`V2/libs/lock_test.PcbLib`, `logs/lock_reload.txt`)

* **[VERIFIED]** The library was opened and shown in Altium (`Modified=False`, `OwnsFile=False`, `SupportsReload=False`). While open, `CreateFile` with **share=none** and with DELETE access both succeed, so **Altium keeps no handle**.
* **[VERIFIED]** Rust `write_pcblib` with `append:true` while open: **success in 125 ms** (atomic temp+rename), 6 footprints in the file. No dialog appeared.
* **[VERIFIED]** **Altium does not notice:**
  * After 9 s it still shows 5 footprints, and `GetFileModifiedDate` returns the cached old time.
  * The same holds after a programmatic tab switch.
* **[VERIFIED]** **Close (unmodified) + `OpenDocument` + `ShowDocument` → 6 footprints**, 3.1 s, no dialog.
* **[UNVERIFIED]** What happens on real app activation with `AskIfModified` and an unmodified document. Expected: a silent reload, because `AskFirst` exists as a separate value. If the document has unsaved edits, Altium will ask, and saving would overwrite the Rust change.

### 5.2 SQLite while the DbLib is installed (`logs/sqlite_concurrency.txt`)

* **DELETE journal (default) [VERIFIED]:**
  * After Altium has queried the DbLib, any commit from another process fails with **`database is locked`** after the full 5 s busy timeout.
  * This persists after `UninstallLibrary`, and still at 23:16, 11+ minutes after the last query.
  * `PRAGMA journal_mode=WAL` is also locked.
  * The file handle has no `FILE_SHARE_DELETE`, so the DB file can't be replaced or renamed either.
  * Cause: Altium's ODBC connection keeps a SQLite shared lock for the session.
* **WAL journal [VERIFIED]:**
  * WAL was set before Altium first connected.
  * Altium reads normally (`-wal`/`-shm` appear). Another process commits **in 7 ms while Altium is connected**.
* **Freshness [VERIFIED]:** Altium does **not** show new or updated rows for a DbLib path it has already used. All of the following still return the old snapshot:
  * the same DbLib after reinstall;
  * `IntegratedLibrary:RefreshInstalledLibraries` (≈16 s, no dialog);
  * `DeactivateLibrary`/`ActivateLibrary`;
  * editing the DbLib file and reinstalling (Altium doesn't re-read it);
  * `NoTXN=1`.
* **[VERIFIED]** A **new DbLib file path**, even with an identical connection string, opens a new connection and sees all current rows. Each DbLib path is then frozen at its first query (RES-0102 inserted later was not visible in `wal2`).
* **[UNVERIFIED]** Whether the Components panel "Refresh" button or an Altium restart shows new rows. A restart is expected to.

---

## 6. Recommendations for PartForge (design advice derived from the VERIFIED facts above)

### 6.1 Default library backend

**Use the Rust writer as the default no-Altium backend for SchLib/PcbLib.** It is fast (≈10 ms per footprint), needs no Altium, and Altium opens its files cleanly, including 1000-part libraries.

**Mandatory workarounds:**
1. **Symbols: always pass `primitive_order` with all graphics (rectangles, polygons, lines, …) before pins and parameters.** Alternatively write bodies with `filled:false`. Without this, pin names are invisible. Re-check with `read_schlib`'s `primitive_order`.
2. Pin decorations: only `none, dot, right_left_signal_flow, clock, active_low_input, analog_signal_in, not_logic_connection`. Otherwise patch the byte to the Altium `TIeeeSymbol` ordinal.
3. Never use `text` (RECORD=3); use `labels`.
4. Prefer `stack_mode:"simple"`. For top-mid-bottom stacks, the pad-level `shape` must be `rectangle` (or round/octagonal), never `rounded_rectangle` or omitted.
5. STEP: always `embed:true`, **plus** an extruded body with the real height (STEP bodies get `OverallHeight=0` and footprint `Height=0`). Never rely on `embed:false`. **Never use `export_library` → `import_library` for libraries with STEP models.**
6. Footprint names ASCII only (`[A-Za-z0-9_.\- ()+]`). PcbLib descriptions in Latin-1 only (`Ω` becomes `?`). SchLib parameter values may use full Unicode.
7. Stroke text is anchored bottom-left. Compute the location yourself to centre it, for example `.Designator` on the assembly layer.
8. Don't rely on via tenting flags (no effect in Altium); handle tenting by rule or by mask expansion **[UNVERIFIED alternative]**.
9. `OwnerPartId=1` parameters and the missing pin bit 0x20 need **no** workaround (no visible effect).
10. Keep the earlier client-side validation (integer pin coordinates, string designators, enum whitelist).

**Use the Altium bridge for verification and refresh, not for bulk creation:**
* Batch everything into one script with `timeout_seconds ≤ 5` and file polling.
* Never use `Exit`; set the result before any early end.
* Use one canonical path spelling (the double-backslash bug, §1).
* Place schematic parts with `MoveToXY` after registration.

### 6.2 DbLib connection string (generate exactly this)

```
ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3 ODBC Driver;Database=<ABSOLUTE path to .db>;NoCreat=1;"
LibraryDatabasePath=<same absolute path>   (informational; Altium ignores it for ODBC)
DatabasePathRelative=0
```
* Relative `Database=` paths do not work: they resolve against Altium's CWD. When the library folder moves, regenerate the DbLib, or use a DSN **[UNVERIFIED alternative]**.
* **Create the DB in WAL mode** (`PRAGMA journal_mode=WAL` right after creation, before Altium ever connects). In DELETE mode PartForge cannot commit while Altium runs. Keep the DB folder writable (`-wal`/`-shm` files).

### 6.3 Column types

* **`TEXT` for all DbLib-facing columns**, including the key and all numeric parameters stored as pre-formatted strings such as `"4.7 µH"` or `"0.1 W"`.
* Avoid `VARCHAR(n)`: Altium truncates at n.
* Avoid `REAL`/`NUMERIC`: Altium formats them with the locale decimal comma.
* `INTEGER` is acceptable for pure counts.
* Plain `SELECT *` views inherit TEXT and work. UNION views are reported as `VARCHAR(255)`; truncation through such views is **[UNVERIFIED]**, so keep long descriptions out of UNION views.
* Library and Footprint paths: relative to the DbLib folder (`libs\X.SchLib` or `libs/X.SchLib`), or absolute. No bare file names unless the file sits next to the DbLib. Symbols used through a DbLib should carry **no footprint links** (they are added to the DB footprint).

### 6.4 Layer mapping (Rust aliases → what Altium shows)

| Rust name | Altium layer | Kind (`TMechanicalLayerKind`) |
|---|---|---|
| `Top Assembly` / `Bottom Assembly` | Mechanical 2 / 3 | 1 AssemblyTop / 2 AssemblyBottom |
| `Top Courtyard` / `Bottom Courtyard` | Mechanical 4 / 5 | 11 CourtyardTop / 12 CourtyardBottom |
| `Top 3D Body` / `Bottom 3D Body` | Mechanical 6 / 7 | 26 3DBodyTop / 27 3DBodyBottom |
| `Mechanical 13`, `Mechanical 15` | Mech 13 / 15 | 0 (plain, enabled) |
| `Mechanical 8–12, 14, 16–32` | correct layer | not enabled in the library layer stack |

Make the mapping configurable to match the user's TR house style.

### 6.5 How PartForge should trigger an Altium refresh

* **SchLib/PcbLib** (bridge, after a Rust write):
  1. Find the document by canonical path.
  2. Not open: nothing to do.
  3. Open and **unmodified**: `CloseDocument` + `OpenDocument` + `ShowDocument`, about 3 s **[VERIFIED]**.
  4. Open and **modified**: refuse to write. Ask the user to save or close, otherwise their next save overwrites PartForge's change.
  5. Altium keeps no lock, so the write itself never fails because of Altium **[VERIFIED]**.
* **DbLib/SQLite:** writes work in WAL mode **[VERIFIED]**, but an Altium session keeps showing the snapshot from its first query of that DbLib path **[VERIFIED]**. Options, in order of preference:
  1. **[UNVERIFIED, test next]** Components panel "Refresh" or an Altium restart. If Refresh works, PartForge just tells the user to press it.
  2. **[partly VERIFIED]** Scripted refresh by **DbLib path rotation**:
     * Keep the DbLib file *name* constant (placed parts reference `SourceLibraryName` = file name only).
     * Install it from a new versioned folder: uninstall the old path, install the new one. A new path gives a fresh connection **[VERIFIED]**.
     * Write absolute Library and Footprint paths (or paths valid from every version folder).
     * **[UNVERIFIED]** That placed parts and "Update from Libraries" follow the renamed path. Old cached connections keep their WAL snapshot until Altium restarts, so the WAL file may grow.
  3. Show changes to the user immediately inside PartForge's own preview. Never promise Altium live updates without option 1 or 2.

---

## 7. Open questions / still UNVERIFIED

1. Does the Components panel **Refresh**, or an Altium restart, show new or changed DbLib rows for an already-used DbLib path?
2. Does option 2 above ("DbLib path rotation") keep placed parts linked (same DbLib file name at a different path)?
3. Natural outside-change handling with `AskIfModified` on app activation: is the reload silent for an unmodified PcbLib or SchLib? Is a SchLib held the same way as a PcbLib (no handle)? Only the PcbLib was tested.
4. Visual 3D check of the embedded STEP. It needs a live PCB canvas: move the mouse over Altium, then capture.
5. The correct way to tent vias in AD 26 from a writer.
6. Truncation through UNION views; behaviour of a 64-bit DSN instead of a file path.

## 8. Artefacts (all under `V2`)

* `logs/`: `00_baseline_before.txt`, `close_all.txt`, `relpath_probe.txt`, `features_extras.txt`, `text_justification.txt`, `footprint_link_resolution.txt`, `lock_reload.txt`, `sqlite_concurrency.txt`, `timing.txt`.
* `altium/`:
  * library dumps: `*.dump.json` (raw), `*.normalized.json`, `compact__*.txt`;
  * `pin_decorations.txt`, `sch_extras_1.txt`, `pcb_extras__*.txt`;
  * `dblib_resolve.txt`, `place_test.txt`, `perf1000_*.txt`.
* `issues/`: comparator results per library.
* `shots/`: 38 PNGs (see §3.4).
* `kit/`:
  * `save_dump.py`, `norm_compare.py`, `compact2json.py`;
  * `pcb_dump.tmpl` + `gen_pcb_dump.py`, `pcb_extras.tmpl`;
  * `crop.ps1`, `screen_capture.ps1`, `display_on.ps1`, `lock_probe.py`;
  * `make_rel.py`, `rw_order_test.py`, `rw_lock_write.py`, `adoq.ps1`.
* `db/`: `partforge_test.db` (DELETE mode; Altium holds a handle until restart), `PF_V2_*.DbLib`, `rel/` marker DBs, `wal/` WAL DB with `PF_V2_wal*.DbLib`.
* `libs/`: `PartForge_Test_bit20.SchLib`, `order_test.SchLib`, `lock_test.PcbLib` (with a Rust `.bak`), `PF_Timing50.PcbLib`.
* Temp sheets: `PF_Place_Test.SchDoc`, `PF_Visual_Test.SchDoc`.
