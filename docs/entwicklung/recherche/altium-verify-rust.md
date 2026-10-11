# Verifying the Rust writer's libraries in Altium: BLOCKED (file-level pre-verification and a ready-to-run kit instead)

Research agent, UNDERSTAND phase, 2026-10-07, 21:40–22:15.
Every claim is tagged **[VERIFIED]** (I ran it or read the bytes) or **[UNVERIFIED]**.

Working folder: `<scratchpad>/altium-verify-rust`
(abbreviated as `AV` below).

---

## 0. Status: read this first

1. **I could not do the Altium part of the task.**
   * **[VERIFIED]** Altium's script executor is still paused in the DelphiScript debugger from the altium-live agent's 8th run (21:20).
   * **[VERIFIED]** A probe call `run_altium_script` (`SandboxLog('probe start'); ResultText := 'alive';`, timeout 5 s, about 21:42) returned `"script never started"`. No `C:/Users/Public/altium_mcp/sandbox_result.json` or `sandbox_log.txt` appeared within the next 35 s.
   * **[VERIFIED]** Every `mcp__altium__*` tool that does real work launches a DelphiScript, so none of them can run. That includes `get_symbol_primitives`, `get_footprint_primitives` and `get_screenshot`: `get_screenshot` first runs the script command `take_view_screenshot`.
   * Each further call only adds another Altium error box.
2. **Side effect of my probe [VERIFIED].** Altium now shows a modal message box.
   * Window: `TMessageForm`, title `Error`, hwnd 528274.
   * Text: *"Another script executing now. Scripting system is not able to execute more than one script simultaneously."*
   * Screenshot: `AV/shots/00_error_dialog.png`.
   * It was still open and in the foreground at 22:10.
   * I tried to close it with `WM_CLOSE`. **The permission system denied that ("Interfere With Workloads")**, so I made no further attempt to change Altium's state.
   * I also did **not** send `EditScript:Stop` (the command behind Ctrl+F3, found in `C:/Program Files/Altium/AD22/System/EditScript.rcs`: `Command='EditScript:Stop' … Shortcut1='Ctrl+F3'`).
3. **Steps the user must take before anyone continues:**
   1. Go to the Altium window `Sandbox.PrjScr - Altium Designer (26.10.1)` on the right monitor.
   2. Click **OK** on the *"Another script executing now"* error box.
   3. Stop the paused script with **Run » Stop (Ctrl+F3)** in the `Sandbox.pas` editor, or restart Altium after saving any work.
   4. Then run `altium-live/followup/00_cleanup_uninstall.txt`. `PF_Test_abs.DbLib` from the altium-live agent is still installed.
4. **Nothing else was touched [VERIFIED]:**
   * I opened no file in Altium and did not touch any user document or project.
   * The `run_altium_script` tool rewrote `<altium-mcp-checkout>/server/SandboxScript/Sandbox.pas` with my 2-line probe body. That is the tool's normal mechanism; lines 46–49 now hold the probe.
   * The Rust agent's `out/` files are unchanged. sha256 of the originals still equals my copies (§1).
5. **What I did instead** (all outside Altium):
   * **(a)** An acceptance test of every library through Windows' own compound-file implementation (ole32).
   * **(b)** A record-level comparison against native Altium files and the Altium API enums. It found **real format bugs** (§3).
   * **(c)** A complete, tested comparator plus DelphiScript bodies, so the Altium check is mechanical once Altium is free (§5).

**Verdict for "Rust writer as a no-Altium backend": NOT YET DECIDABLE in Altium.** At file level:
* **Strongly positive:** the files are structurally sound, ole32 opens them, and geometry, pads and holes match intent.
* **Bugs that are certain at file level:**
  * the pin IEEE-symbol enum table is wrong from index 7 on;
  * `text` is written as `RECORD=3`;
  * parameters are written with `OwnerPartId=1`;
  * the pad-stack shape blocks contradict each other;
  * STEP bodies have height 0.
* Each of these has a simple workaround on the PartForge side (§4).

---

## 1. Files examined (copies; originals in `rust-writer/out` not modified) [VERIFIED]

I copied all files to `AV/libs/`. The sha256 of every copy equals the original, checked at 22:05:

| File | sha256 (first 16) | Components |
|---|---|---|
| PartForge_Test.PcbLib | 4f6d4f893a9b27b7 | 5 |
| PartForge_Test.SchLib | 37cee39942cd1c5c | 4 |
| PartForge_Features.PcbLib | addea26d1aaeda2e | 4 |
| PartForge_Features.SchLib | b9ab88042067da6b | 1 |
| example_12_1.PcbLib / example_12_4.SchLib | 75af363e8c0956d2 / 3c9737ffe66210b8 | 3 / 3 |
| errors.PcbLib / errors.SchLib | 84f07c05b366fe5a / 73cbe39d65972ae6 | 20 / 16 |
| probe_mech_layers.PcbLib | f49afbf9061f6240 | 38 |
| PartForge_Test_reimported.PcbLib | 7bb3475e7dc87055 | 5 |
| perf_1000_onecall.PcbLib / .SchLib | f0c5b7b8186a3ebd / 5b0192b6cade6cfb | 1000 / 1000 |

**New probe libraries I wrote with the Rust exe** (my own config `AV/rw_config.json`, sandboxed to `AV/libs`, audit log `AV/rw_audit.log`):
* `probe_enums.SchLib`
* `probe_stack.PcbLib`
* `probe_stack2.PcbLib`

**Native Altium reference files** (read-only copies in `AV/native/`):

| File | Origin | Writer |
|---|---|---|
| `SpiritLevel_2E.SchLib` | AD22 example | |
| `Spirit_Level_Project.PcbLib` | AD22 example | AD6, 2007 |
| `MiniPC.PcbLib` | AD22 example | 2017 |
| `OrCAD-CAPSYM.SchLib` | AD22 `System/Templates` | |
| `CapSense_extracted.SchLib` | unzipped from `Cypress CapSense.IntLib`, stream `SchLib/0.schlib` | IntLib-compiled |

**Note:** the Altium version is 26.10.1, not AD22. The executable lives in the `AD22` folder.

---

## 2. Verified at file level

### 2.1 Windows structured storage (ole32) opens every file [VERIFIED]

Script: `AV/scripts/stg_check.py`. Results: `AV/dumps/stg_check.jsonl`.

**Method:**
* `pythoncom.StgOpenStorage` (pywin32 312) in two modes: `STGM_READ|STGM_SHARE_DENY_WRITE` (direct) and `STGM_READ|STGM_TRANSACTED|STGM_SHARE_DENY_NONE`.
* Recursive `EnumElements`, then **open every child by name** (`OpenStorage`/`OpenStream`), which exercises ole32's tree lookup.
* Read every stream fully and compare the bytes with olefile 0.47.

**Results for all 15 files:**
* 0 open errors, 0 lookup failures, 0 byte mismatches.
* Directory trees are valid BSTs under the MS-CFB order (length first, then upper-case): 0 violations.
* All nodes are black and there are no red-red violations.
* Maximum child-tree depth is 1001 for the 1000-part libraries:
  * `perf_1000_onecall.PcbLib`: 1008 storages, 4018 streams.
  * `.SchLib`: 1000 storages, 1002 streams.
* **ole32 handled the degenerate chain without problems.**
* [UNVERIFIED] Altium itself uses ole32. If it does, a container-level rejection is ruled out.

### 2.2 Record framing and counts [VERIFIED]

Decoders: `AV/scripts/pcb_records.py` and `AV/scripts/sch_records.py`. They are my own and independent of pyaltiumlib and of the Rust reader.

**PcbLib framing.**
* Every component `Header` record count equals the decoded `Data` records:
  * RESC1608X55N 14, SOIC 22, PINHDR 16, CAPC2012X125N 14, RESC2012X60N 14.
  * QFN 43, DCJACK 7, EXT_STEP_REF 4, AUTO_BODY 4.
* The pad geometry block is 202 bytes. Native MiniPC (2017) uses 171 bytes.
* Rounded rectangles are encoded as legacy shape 1 plus alt-shape 9 plus a corner % in the size-and-shape block (651 bytes). This matches Altium's convention (`eRoundedRectangular = 9` in the API constants).

**PcbLib library-level streams** (stream set like modern Altium, compared with MiniPC):
* `FileHeader`, `FileVersionInfo`, `Library/Data`, `Library/Header`, `Library/ComponentParamsTOC`
* `Library/Models/{Header,Data,0}`, `Library/ModelsNoEmbed`, `Library/PadViaLibrary`, `Library/Textures`, `Library/EmbeddedFonts`
* `Library/LayerKindMapping` (absent in MiniPC)

**Values decoded from the files** (intent = Rust §12; mm → mil):

| Footprint / pad | Decoded | Equals intent |
|---|---|---|
| RESC1608X55N pads | x=∓31.4961 mil (0.8 mm), 35.4331×37.4016 mil (0.90×0.95), shape 1+alt 9, corner 25 %, layer 1 (Top) | yes |
| SOIC pad 1 | (-97.4409, 75.0), 78.7402×23.6220 mil (2.0×0.6 after `update_pad`), shape 2 (rect), no size-and-shape block | yes |
| SOIC pads 2–8 | 76.7717×23.6220, RR 25 % | yes |
| PINHDR pads | layer 74 (Multi-Layer), 66.9291 mil (1.7 mm), hole 39.3701 (1.0 mm); pad 1 rect (2), pad 2 round (1), plated | yes |
| DCJACK pad 1 | hole 39.3701 + slot 102.3622 mil (1.0×2.6 mm), slot rot 0 | yes |
| DCJACK pad 2 | same slot, rot 90 | yes |
| DCJACK pad 3 | square hole (hole shape 1), 47.2441 mil | yes |
| DCJACK pad MH | plated=0, NPTH | yes |
| DCJACK pad 4 | `stack_mode`=1, top/mid/bot = 78.74/62.99/94.49 mil | sizes yes; shapes see §3.4 |
| QFN EP 17 | 66.9291 mil (1.7 mm) rect | yes |
| QFN side pads 5–8, 13–16 | rotation 90 | yes |

**Extruded body records:**
* RESC1608X55N `OVERALLHEIGHT=21.653543mil` (0.55 mm).
* SOIC `STANDOFFHEIGHT=3.937008mil|OVERALLHEIGHT=68.897638mil`.
* All on `V7_LAYER=MECHANICAL6`.

**SchLib.**
* Pin coordinates are stored in 10-mil units. For example RES pin 1: `x=-20 y=0 len=10 orient=2` → expected Altium dump (-200 mil, 0), length 100 mil, orientation 2 (eRotate180).
* `PartCount` is written as parts+1. The FileHeader `PartCount<i>` uses the same value. Native files show the same convention (CapSense `PARTCOUNT0=2` for single-part).

### 2.3 Pin electrical type and orientation ordinals match Altium [VERIFIED]

`AV/scripts/enum_probe.py` writes `AV/libs/probe_enums.SchLib`. Result: `AV/dumps/enum_probe.json`.

| Value | Stored ordinal |
|---|---|
| input | 0 |
| bidirectional | 1 |
| output | 2 |
| open_collector | 3 |
| passive | 4 |
| hi_z | 5 |
| tristate | 5 |
| open_emitter | 6 |
| power | 7 |

These equal the API constants (`eElectricInput=0 … eElectricPower=7`). Orientation right/up/left/down = 0/1/2/3 = eRotate0/90/180/270.

### 2.4 Pin flag bits [VERIFIED]

`PinConglomerate`, cross-checked on the Rust `HID` pin and on 600 native pins:

| Bits | Meaning |
|---|---|
| 0–1 | orientation |
| 0x04 | hidden |
| 0x08 | show name |
| 0x10 | show designator |

Rust sets these correctly. For example the RES pins: show_name and show_designator are false, so cong is 0x02/0x00.

---

## 3. Discrepancies found (file level). Each one still needs confirmation in Altium

### 3.1 Wrong IEEE pin-symbol ordinals from index 7 upward [VERIFIED stored values; UNVERIFIED rendering]

**Stored values.** `probe_enums.SchLib` has one pin per decoration name in each of the four slots (inner edge, outer edge, inside, outside). All four slots behave identically.

**Reference.** The Altium `TIeeeSymbol` ordinals come from the altium-script skill: `api/Constants.md` and the `SCH_API_Reference.md` order.
* `eShiftRight=7`, `ePostPonedOutput=8`, `eOpenCollector=9`, `eHiz=10`, `eHighCurrent=11`, `ePulse=12`, `eSchmitt=13`, `eDelay=14`.
* `eActiveLowOutput=17`, `eOpenCollectorPullUp=22`, `eOpenEmitter=23`, `eOpenEmitterPullUp=24`, `eDigitalSignalIn=25`.
* `eOpenCircuitOutput=32`, `eLeftRightSignalFlow=33`, `eBidirectionalSignalFlow=34`.

**Why the file stores the API ordinal:**
* Rust `dot` → 1 and `clock` → 3 match `eDot=1` and `eClock=3`.
* In the native `SpiritLevel_2E.SchLib`, pins TCK, CCLK and GCK* store inner-edge 3 (clock), and PROGRAM and Y store outer-edge 1 (dot).
* All 37 TIeeeSymbol constants were checked against `Constants.md`, e.g. `eShiftLeft=30`, `eLessEqual=20`, `eSigma=21`.

**Correct (0–6):** none 0, dot 1, right_left_signal_flow 2, clock 3, active_low_input 4, analog_signal_in 5, not_logic_connection 6.

**Wrong:**

| Rust name | Stored | Altium meaning of stored value | Correct value |
|---|---|---|---|
| postponed_output | 7 | ShiftRight | 8 |
| **open_collector** | **8** | **PostPonedOutput** | 9 |
| hi_z / hiz | 9 | OpenCollector | 10 |
| high_current | 10 | Hiz | 11 |
| pulse | 11 | HighCurrent | 12 |
| schmitt | 12 | Pulse | 13 |
| active_low_output | 13 | Schmitt | 17 |
| open_collector_pull_up | 14 | Delay | 22 |
| open_emitter | 15 | GroupLine | 23 |
| open_emitter_pull_up | 16 | GroupBin | 24 |
| digital_signal_in | 17 | ActiveLowOutput | 25 |
| shift_left | 18 | PiSymbol | 30 |
| left_right_signal_flow | 20 | LessEqual | 33 |
| bidirectional_signal_flow | 21 | Sigma | 34 |

* Not accepted at all, **silently stored as 0 (none)**: shift_right, delay, group_line, group_bin, pi_symbol, greater_equal, less_equal, sigma, and, invertor/inverter, or, xor, input_output, open_circuit_output, internal_pull_up, internal_pull_down.
* Existing file affected: `PartForge_Features.SchLib` pin `OC` has `symbol_inside` stored as **8**.
  * Expected in Altium: a "Postponed Output" glyph instead of "Open Collector".
* **PartForge rule:** use only none/dot/clock/active_low_input/analog_signal_in/not_logic_connection/right_left_signal_flow. Otherwise patch the byte after writing, or fix upstream.

### 3.2 Rust `text` primitive is written as `RECORD=3` [VERIFIED bytes; UNVERIFIED meaning in Altium]

Verbatim from `PartForge_Features.SchLib`:
```
|RECORD=3|IsNotAccesible=T|IndexInSheet=20|OwnerPartId=1|Location.Y=-45|Justification=4|Color=128|FontID=1|Text=TEXT rec3|UniqueID=QLGXQTSD
```
* [UNVERIFIED, format knowledge] In Altium's SchLib format `RECORD=3` is the **IEEE symbol** object and `RECORD=4` is the text string (`ISch_Label`, "Text String" in the UI).
* Expected: Altium shows no text for this object. altium-mcp's dump would list it as `{"type":"unknown","object_id":…}`.
* **PartForge rule:** use `labels` (`RECORD=4`, verbatim: `|RECORD=4|…|Location.X=-30|Location.Y=42|Color=128|FontID=1|Text=LABEL rec4|…`) for free text.

### 3.3 Component parameters written with `OwnerPartId=1` [VERIFIED bytes; UNVERIFIED effect]

* **Rust:** every parameter is written with `OwnerPartId=1`. Verbatim from LM358DR:
  ```
  |RECORD=41|IndexInSheet=11|OwnerPartId=1|Color=8388608|FontID=1|Text=LM358DR|Name=Comment|…
  ```
* **Native Altium** writes `OWNERPARTID=-1` for every parameter seen: SpiritLevel `…|OWNERPARTID=-1|…|NAME=Created|…`, CapSense Comment/ConfiguratorName. The designator uses -1 in both writers.
* **Risk [UNVERIFIED]:** on multi-part parts (LM358DR B/C) the Comment and other parameters may be visible or editable only on part A.
* **PartForge rule:** check in Altium (switch LM358DR to Part B). If confirmed, post-patch to -1 or fix upstream.

### 3.4 Pad stacks: per-layer shapes contradict the size-and-shape block [VERIFIED bytes; UNVERIFIED which block Altium honours]

Probes: `probe_stack.PcbLib` and `probe_stack2.PcbLib`, decoded with `pcb_records.py`.

* **The Rust report's "non-simple stacks lose rectangular shapes" is an input-vocabulary error.**
  * Its test passed `"rectangular"`, which is **silently stored as round**.
  * `per_layer_shapes:["rectangle","round","octagonal"]` is stored correctly: block-4 shapes 2,1,3, and the Rust read-back agrees.
* **The real bug:** the pad-level `shape` alone drives the size-and-shape block's 32 alt-shapes. Per-layer shapes only go into the legacy top/mid/bot bytes.

| Case | Legacy top/mid/bot | Alt-shapes (all 32 layers) | Rust read-back |
|---|---|---|---|
| tmb, `shape` omitted (default RR 50 %), per-layer rect/round/oct | 2,1,3 | **9 (RR) 50 %** | rectangle/round/octagonal |
| tmb, `shape:"rounded_rectangle"`, 25 % | 2,1,3 | **9 / 25 %** | shape=rectangle, corner lost |
| tmb, `shape:"rectangle"` | 2,1,3 | none (no block) | consistent |
| simple, `shape` omitted | 1,1,1 | 9 / 50 % | rounded_rectangle 50 |
| simple rect / round / oct (SMD or THT) | 2 / 1 / 3 | none | consistent |

* In conflicting files Altium may draw rounded rectangles on every layer [UNVERIFIED].
* **PartForge rule:** use `stack_mode:"simple"`. For non-simple stacks, always set the pad-level `shape` to anything except rounded_rectangle, and use the exact tokens `rectangle|round|octagonal`.

### 3.5 Embedded STEP body: zero heights, zero checksum [VERIFIED bytes; UNVERIFIED effect]

Verbatim CAPC2012X125N body:
```
V7_LAYER=MECHANICAL6|…|STANDOFFHEIGHT=0mil|OVERALLHEIGHT=0mil|…|IDENTIFIER=|…|MODELID={52398B2B-D5D2-4117-9E8B-44C8D02B87E7}|MODEL.CHECKSUM=0|MODEL.EMBED=TRUE|MODEL.NAME=CAPC2012X125N_box.step|MODEL.2D.X=0mil|MODEL.2D.Y=0mil|MODEL.2D.ROTATION=0.000|MODEL.3D.ROTX=0.000|MODEL.3D.ROTY=0.000|MODEL.3D.ROTZ=0.000|MODEL.3D.DZ=0mil|MODEL.MODELTYPE=1|MODEL.MODELSOURCE=Undefined
```
Its `Library/Models/Data` entry:
```
EMBED=TRUE|MODELSOURCE=Undefined|ID={52398B2B-…}|ROTX=0.000|ROTY=0.000|ROTZ=0.000|DZ=0|CHECKSUM=0|NAME=CAPC2012X125N_box.step
```
* Native MiniPC writes `MODEL.CHECKSUM=126397164`, `OVERALLHEIGHT=1067.9133mil`, `STANDOFFHEIGHT=-184.0551mil` and an IDENTIFIER.
* **Risk [UNVERIFIED]:** height-based DRC and 3D clearance see 0 mm. The checksum may trigger "model changed" handling.
* **PartForge rule:** additionally write an extruded `component_bodies` entry with the real height. The kit's `20_pcb_extras` reads `Model.DataSize/CheckSum/Embed` and `OverallHeight` from Altium.

### 3.6 Extruded bodies lack every `MODEL.*` key [VERIFIED bytes; low risk]

* **Rust** writes only `STANDOFFHEIGHT`/`OVERALLHEIGHT` plus the outline.
  * This matches the 2007 (AD6) native example `Spirit_Level_Project.PcbLib`, which ships with the installed Altium.
  * An extruded body there:
    ```
    |KIND=0|…|ISSHAPEBASED=TRUE|STANDOFFHEIGHT=190mil|OVERALLHEIGHT=350mil|…|MAINCONTOURVERTEXCOUNT=4|…
    ```
* **Altium 26** writes `MODEL.MODELTYPE=0` and `MODEL.EXTRUDED.MINZ/MAXZ`, per the altium-live report §3.4.
* [UNVERIFIED] Altium reads the legacy style for these files.

### 3.7 Pin flag bit 0x20 never set [VERIFIED; meaning UNKNOWN]

* All 612 native pins have `PinConglomerate & 0x20` set: 600 in SpiritLevel, values 0x20–0x3e, and 12 in CapSense, value 0x2a.
* Rust pins never do. Values seen: 0x00, 0x02, 0x10, 0x18, 0x19, 0x1a, 0x1b, 0x1c.
* The effect is unknown. Check in Altium whether any pin property differs from a pin drawn by Altium.

### 3.8 Unicode parameter values [VERIFIED bytes; UNVERIFIED display]

Verbatim:
```
|RECORD=41|…|IsHidden=T|Text=Â±1%|%UTF8%Text=Â±1%|Name=Tolerance|…
|RECORD=41|…|IsHidden=T|Text=10kÎ©|%UTF8%Text=10kÎ©|Name=Resistance|…
```
These are UTF-8 bytes in both keys, shown here as Latin-1. The kit reads them back in Altium as `Length()` plus the positions of `Chr(194)`/`Chr(206)`/`Chr(177)`:

| Read in Altium as | Length | Position markers |
|---|---|---|
| `±1%` (correct) | 3 | posB1=1 |
| `Â±1%` (mojibake) | 4 | posC2=1 |
| `10kΩ` (correct) | 4 | posCE=0 |
| `10kÎ©` (mojibake) | 5 | posCE=4 |

### 3.9 Footprint links [VERIFIED bytes]

* `RES_0603_10K` (final state) has three `RECORD=45` links:
  * `RESC1608X55N`: `IsCurrent=T|ModelDatafile0=<scratchpad>/rust-writer/out/PartForge_Test.PcbLib`
  * `RESC3216X70N`: no `ModelDatafile0`.
  * `RESC1005X40N`: the same absolute forward-slash path.
* RESC3216X70N and RESC1005X40N **do not exist** in that PcbLib. They are expected not to resolve in Altium; this is not a writer bug.
* `OwnerIndex` chains are consistent: 44 → 45 → 46/48, counting pin records.
* [UNVERIFIED] Altium resolves forward-slash absolute paths.

### 3.10 Final content differs from the §12.4 example [VERIFIED]

This comes from the later maintenance calls and is not a bug. `RES_0603_10K` in `PartForge_Test.SchLib` now has:
* description "Thick film resistor 4.7 kOhm 1% 0.1 W 0603";
* Value=22k and MPN RC0603FR-074K7L;
* Power removed and Package=0603 added;
* the 3 links above.

The kit's expected values are built from the **final** files (Rust read-back), not from §12.

### 3.11 Mechanical layer kinds [VERIFIED bytes; UNVERIFIED in Altium]

`Library/Data` writes the kinds three times:
* `V9_CACHE_LAYER70..75_MECHKIND`, `LAYER_V8_12..17MECHKIND` and `LAYER58..63MECHKIND`, each set to AssemblyTop/AssemblyBottom/CourtyardTop/CourtyardBottom/3DBodyTop/3DBodyBottom;
* `LAYER58NAME=Top Assembly … LAYER63NAME=Bottom 3D Body` with `MECHENABLED=TRUE`.

MiniPC (2017) has no kinds.

---

## 4. Consequences for PartForge if it used the Rust writer today (design advice, based on §3)

* Keep pin decorations to the seven correct ones (§3.1).
* Never use `text`; use `labels` (§3.2).
* Use `stack_mode:"simple"` (§3.4).
* Always add an extruded body with the real height next to an embedded STEP (§3.5).
* Validate shape and decoration tokens client-side. Unknown tokens are silently accepted: `rectangular` → round, unknown decorations → none.
* Whether `OwnerPartId=1` (§3.3) and bit 0x20 (§3.7) matter can only be decided in Altium.
* Every item can be post-patched at record level. Alternatively, ask upstream for fixes: the GPL tool is used only as a separate process.

---

## 5. Ready-to-run Altium verification kit (for the next run, after the user's recovery steps)

### 5.1 Contents [VERIFIED written, comparator self-tested]

* **`AV/expected/<lib>.expected.json`** for 13 libraries.
  * Built from the Rust read-back of the **final** files (`AV/dumps/<lib>.rust_read.json`).
  * Converted to the exact schema and units of altium-mcp's `get_footprint_primitives`/`get_symbol_primitives` "*" dumps, as read in `pcb_utils.pas:266ff` and `schematic_utils.pas:958ff`.
  * Units are mils. Enums: pad shape 1/2/3/9 plus `corner_pct`, hole type 0/1/2, mode 0/1/2, electrical 0–7, orientation 0–3.
* **`AV/scripts/altium_compare.py`**, usage:
  ```
  C:/.../altium-verify-rust/.venv/Scripts/python.exe -I AV/scripts/altium_compare.py compare AV/expected/PartForge_Test.PcbLib.expected.json <saved_altium_dump.json> <issues.json>
  ```
  * Pads are matched by name and pins by (number, part). Other primitives use global greedy matching.
  * Tolerances: 0.02 mil, 0.01°.
  * Layer names are normalised. The aliases Top/Bottom Assembly/Courtyard/3D Body map to Mechanical 2–7.
  * **Self-test** (`selftest` mode) on 6 libraries:
    * A synthetic exact dump gives 0 issues. GRAPHICS_TEST also gets one `info` entry for its 3 expected unknown objects.
    * PcbLib: pad.x+1 mil, a dropped track and a changed layer give exactly 4 issues (x, layer, count, presence).
    * SchLib: pin.x+1 mil and a dropped rectangle give exactly 3 issues.
* **`AV/kit/*.txt`**: DelphiScript bodies for `run_altium_script`, generated by `AV/scripts/make_kit.py`.
  * Rules applied: no `Exit`, no indexing of interface string properties, no non-ASCII literals, a `SandboxLog` before every non-production call.

| Kit file | Purpose | Status |
|---|---|---|
| `00_probe.txt` | Executor alive check | uses verified calls |
| `05_status_open_libs.txt` | Which of our 15 libs are open and whether each is `Modified` | |
| `10_sch_extras__<lib>.txt` | Per symbol: name length and markers, PartCount, DisplayModeCount, pins, designator, comment; per parameter: name, value, `Length`, hidden, OwnerPartId, mojibake markers; per implementation: ModelName, ModelType, IsCurrent, link count | UNVERIFIED calls marked |
| `11_sch_links__<lib>.txt` | `DatafileLink[0].Location/EntityName/FileKind` | riskiest; run last |
| `20_pcb_extras__<lib>.txt` | Per footprint: height; per body: layer, overall/standoff (1e-4 mil ints), `GetState_ModelType`, `Model.Name/FileName/Embed/ModelType/DataSize/CheckSum`; per pad: paste/solder expansion, hole type, plated; per via: tenting top/bottom | UNVERIFIED API |
| `30_show_symbol__*.txt` / `31_show_footprint__*.txt` | Focus one symbol or footprint and zoom, for screenshots | `Sch:Zoom`/`PCB:Zoom` UNVERIFIED |
| `90_close_all.txt` | Close all our libs. A copy marked modified is reset (`Modified := False`) first; disk files are never written | |

* **`AV/scripts/capture_window.ps1`**: a read-only window list and PrintWindow screenshot of the X2 process.
  * `-ListOnly` detects modal dialogs (`TMessageForm`/`#32770`) after each open.
  * `-Hwnd` captures one window.

### 5.2 Run order (use backslash paths `<scratchpad>\altium-verify-rust\libs\<file>`)

1. **Probe.** `run_altium_script(kit/00_probe.txt, timeout_seconds=5)`.
   * If it returns "never started", poll `C:/Users/Public/altium_mcp/sandbox_result.json` for 20 s yourself before concluding anything.
2. **Cleanup.** `run_altium_script(altium-live/followup/00_cleanup_uninstall.txt, 5)` plus polling.
3. **SchLibs.** For each SchLib in `AV/libs`:
   1. `get_symbol_primitives(library_path=<path>)` (inventory).
   2. `get_symbol_primitives(library_path=<path>, symbol_name="*")`, and save the text to `AV/altium/<lib>.json`.
   3. `capture_window.ps1 -ListOnly` (dialog check).
   4. `altium_compare.py compare`.
4. **PcbLibs.** Same as step 3 with `get_footprint_primitives(..., footprint_name="*")`. For the two `perf_1000_*` files use only the inventory, which gives component counts.
5. **Screenshots.**
   * `31_show_footprint__*`, then `get_screenshot(view_type="pcb")` **only while a PcbLib is focused**, or `capture_window.ps1`.
   * `30_show_symbol__*`, then **`capture_window.ps1` only. Never call `get_screenshot("sch")`** (see §5.3).
6. **Extras.** `10_*`, `20_*`, then `11_*` (one library per call).
7. **Close.** `90_close_all.txt`, then a final `-ListOnly`.

### 5.3 Hazards in the altium-mcp tools [VERIFIED by reading the code]

* **`get_screenshot` ignores `view_type` when focusing.**
  * `EnsureDocumentFocused('take_view_screenshot')` always targets 'PCB' (`other_utils.pas:141-160`).
  * With a SchLib focused, `GetCurrentPCBBoard` is nil. It then runs `Doc.DM_OpenAndFocusDocument` on the **focused project's first PCB document**, which would be a user document. If there is none, it shows a modal `ShowMessage('Error: No PCB document found in the project.')` (`:260-332`).
  * The Python capture then takes the first window whose title contains "Altium" and ".PrjPcb" (`main.py:2003-2040`).
* **`run_altium_script` with `timeout_seconds` ≥ 6** (the loop dismisses once more than 6 s have elapsed) posts `WM_CLOSE` to **every visible `#32770` window of any process**, and to Altium `TMessageForm`s titled Error/Warning/Information/Confirm (`main.py:1065-1098, 1177-1180`). Use timeout ≤ 5 and poll the result file.
* **A body containing `Exit` skips writing the result file** (`Sandbox.pas:45-63`). The tool then reports a false `executor_wedged:true`.
* **`get_*_primitives` behaviour:**
  * They open the library with `Client.OpenDocument` and `Client.ShowDocument`, and **leave it open** (`pcb_utils.pas:288-307`, `schematic_utils.pas:984-1002`).
  * Their dumps omit 3D bodies, parameters, footprint links, mask expansions, pin decorations and hidden flags. That is why the kit has the extras scripts.
  * Output goes through `TStringList.SaveToFile` (ANSI), so non-ASCII text arrives best-fitted.

### 5.4 Checklist the next run must answer (maps to the Rust report §15)

1. Each library opens with no modal dialog, the component counts match, and `Modified=False` right after opening.
2. Pin positions, lengths and orientations; pad sizes, layers and holes: run the comparator (§5.1).
3. LM358DR shows parts A/B/C; the Comment is visible on part B (§3.3).
4. The NE555 overbar and dot.
5. GRAPHICS_TEST: the `OC` pin glyph (§3.1) and the `RECORD=3` object (§3.2). Use the screenshots of PROBE_SYMBOL_INSIDE/OUTSIDE.
6. Unicode lengths and markers (§3.8). Long and Unicode names in `errors.*`.
7. The STEP model is shown and its `DataSize` is greater than 0; the heights (§3.5).
8. Mech 2/4/6 kinds (§3.11).
9. `probe_stack2` S_J and S_A rendering (§3.4).
10. Footprint-link resolution (`11_*`).
11. The 1000-part files open.

---

## 6. Artefacts (all under `AV`)

* **`scripts/`**
  * `stg_check.py`, `pcb_records.py`, `sch_records.py`, `inspect_fmt.py`
  * `enum_probe.py`, `rw_read.py` (a minimal stdlib MCP client for the Rust exe, read-only use)
  * `altium_compare.py`, `make_kit.py`
  * `capture_window.ps1` and `close_altium_error.ps1` (never executed; denied)
* **`dumps/`**
  * `stg_check.jsonl`, `enum_probe.json`
  * `*.rust_read.json`
  * `sch_records_*.txt`, `fmt_*.txt`
  * `sha256_libs_final.txt`, `rw_tools_list.json`
* **`expected/`**: 13 expected files.
* **`kit/`**: 36 script bodies.
* **`shots/`**: `00_state_before.png` (Altium window with paused `Sandbox.pas`) and `00_error_dialog.png`.
* **`libs/`**: copies and probes. **`native/`**: Altium reference files.
