# House style of the user's hand-made Altium libraries (TR_*)

Research agent `user-lib-style`, UNDERSTAND phase, 2026-10-07.
Legend: **[V]** = VERIFIED (read from the files / reproduced in this session), **[U]** = UNVERIFIED (inference or background knowledge, not tested here).

---

## 0. Scope, method, evidence

* Libraries (read-only): `C:/PartForge-Examples/Altium_Libs/Local/SchLib/*.SchLib` (18 + 3 `.bak`), `PcbLib/*.PcbLib` (21 + 4 `.bak`), 16 `TR_*.LibPkg`.
* Primary reader: `altium-designer-mcp.exe` v0.1.0 (stdio JSON-RPC, newline-delimited), driven by my stdlib client
  `scratchpad/user-lib-style/mcp_client.py`. That client has a whitelist of the 8 read tools: `read_schlib`, `read_pcblib`, `list_components`,
  `extract_style`, `render_symbol`, `render_footprint`, `search_components`, `get_component`. Its own `config.json` has
  `"allowed_paths": ["C:/PartForge-Examples/Altium_Libs/Local"]`. Handshake used: `initialize` (protocolVersion `2024-11-05`) →
  `notifications/initialized` → `tools/call`. The server lists 34 tools [V].
* Cross-check: my own olefile parsers of the raw OLE streams (`pcblib_raw.py`, `pcblib_header.py`, `schlib_raw.py`, venv in my folder, run with `python -I`).
* **Read-only proof [V]:** I recorded SHA-256, size and mtime of all 62 SchLib/PcbLib/LibPkg files before the first read and again after all reads. They are identical (`hash_before.txt`, `stat_before.txt`).
* **Units [V]:**
  * PcbLib: the tool reports mm, which equals raw internal units × 2.54e-6 (10000 units = 1 mil).
  * SchLib: 1 unit = 10 mil, and the tool's numbers equal the raw `Location.X/Y` values. Example: designator raw `Location.X=-11` matches tool `designator_x: -11.0`, and raw pin length `5` matches tool `length: 5`.

### 0.1 What counts as "house style" (important)
[V] Several files were rewritten or extended on **2026-08-22/23** by an automated writer. The fingerprints are consistent with altium-designer-mcp; attributing them to that tool is an inference [U], but strong:
* `*.YYYYMMDD_HHMMSS.bak` siblings, which is the tool's documented backup naming;
* PcbLib header replaced by a template with Mech 2/3 = Assembly, 4/5 = Courtyard, 6/7 = 3D Body;
* `Library/LayerKindMapping` emptied;
* SchLib font table cut to 1 entry;
* component `UniqueID` dropped.

That content is **not** the user's style. It is excluded from all statistics below, and the `.bak` originals were analysed instead:

| File (current) | What happened 2026-08-22/23 [V] | Original used |
|---|---|---|
| `TR_FET.PcbLib` | Content replaced: now only `FS8205A_TSSOP8` | `TR_FET.PcbLib.20260822_195408.bak` (`Diodes PowerDI3333-8`) |
| `TR_LEDs.PcbLib` | `SK6812HV-4P-002` appended; Mech17/19 primitives degraded to Mech16 (see §5) | `TR_LEDs.PcbLib.20260822_192519.bak` |
| `TR_Integrated.PcbLib`, `TR_Power-Switchmode.PcbLib` | New files (not referenced by any LibPkg) | – |
| `TR_FET/TR_Integrated/TR_Power-Switchmode.SchLib` | `FS8205A`, `TP4056`, `DW01`, `MCP1640` appended | `*.SchLib.20260822_195539.bak` |
| `Battery_Power_Management.*`, `LED_1010`, `LED_1414`, `Microcontrollers` | New 2026-08 libraries (tool or other template) | excluded |
| `WL-SMCW_0603.SchLib` | Würth vendor library (2020) | excluded from style statistics |

House-style sample [V]: **54 symbols** (16 SchLibs) and **79 footprints** (15 PcbLibs), dated 2020-10 to 2023-11.

---

## 1. Executive summary

* **Workflow:** the existing workflow is integrated libraries: `TR_<Category>.LibPkg` → `.IntLib`. There is no DbLib in `Local` [V].
* **Symbols:**
  * Graphics are blue (`16711680` = #0000FF), LineWidth 1 (Small).
  * IC symbols are a single Altium-default box: border `128` (#800000), fill `11599871` (#FFFFB0), LineWidth 0. The top-left corner is at the origin and the box grows to +x/−y. Pins are 200 mil long on a 100 mil pitch, with names and numbers shown.
  * Discretes have hidden pin names and numbers.
  * The designator is at (−5, 5) and the Comment at (−5, −15), both in font 1 (Times New Roman 10, navy `8388608`). Comment is the only visible parameter.
  * Footprint links are name-only (`ModelType=PCBLIB`, `ModelDatafileEntity0=<name>`, no path) [V].
* **Footprints** (IPC-7351B wizard style, mm):
  * SMD pads are rounded rectangles with 50 % corner radius.
  * Silk 0.15 mm (chips) / 0.20 mm (ICs, connectors, newer libs). The pin-1 silk dot is Ø0.5 mm (arc r=0.125, w=0.25).
  * Courtyard: **Mech 15**, 0.05 mm lines, excess 0.25 mm (0.10 mm for "RF" = IPC High Density), plus a 0.1 mm centre cross ±0.5 mm.
  * Assembly body outline: **Mech 5**, 0.1 mm.
  * `.Comment`: **Mech 7**. `.Designator`: on the library's "Top Designator" layer, which is **Mech 9** in layer-variant-A libraries and **Mech 2** in variant-B libraries (§4.1). Both 1.0 mm high and centred at the origin.
  * 3D STEP body: **Mech 13** (embedded).
  * **Mech 17** (component centre cross) and **Mech 19** (component outline): 0.1 mm.
  * Origin = pad-pattern / body centre [V].
* **Tool caveats** (§5) [V]:
  * altium-designer-mcp names mechanical layers with a fixed table that contradicts the user's layer kinds: its "Bottom Courtyard" is Mech 5, its "Bottom 3D Body" is Mech 7, its "Top Assembly" is Mech 2.
  * It cannot see Mech 17–20 (it reports them as Mech 16).
  * Rewriting existing files with it is lossy.

---

## 2. Inventory: component names per library [V]

### 2.1 SchLib
| File (mtime) | # | Examples |
|---|---|---|
| TR_BJT.SchLib (2023-11-18) | 1 | `BC807-40LT1G` |
| TR_Connector.SchLib (2022-12-23) | 10 | `SCH - CONNECTORS - Wurth 74980111211`, `SCH - CONNECTORS - Molex 532610271`, `SCH - CONNECTORS - Wurth 61300611121` (4 of 10 are Würth vendor imports) |
| TR_Converter.SchLib (2020-10-31) | 1 | `DAC70508ZRTET` |
| TR_Diode.SchLib (2022-12-13) | 9 | `BZX84C12LT1G`, `PDZ6.2B,115`, `SMAJ5.0A`, `SMAJ24CA`, `BAT54C`, `PESD3V3S4UD`, `SD24-01FTG`, `SBR1A40S3-7` |
| TR_Electromechanic.SchLib (2022-12-17) | 2 | `PCM12SMTR`, `SMTRAM25-6-5ET` |
| TR_FET.SchLib (2026-08-22, orig 4) | 5 | `DMPH6050SFGQ-7`, `2N7002NXAKR`, `SI2369DS-T1-GE3`, `2N7002` (+ tool `FS8205A`) |
| TR_Fuse.SchLib (2022-11-12) | 2 | `1206L110THYR`, `MF-GSMF300/36X-2` |
| TR_Inductors.SchLib (2023-01-15) | 10 | `LQM18PNR47NC0L`, `74438356022`, `744235900`, `742792624`, `SRP1038C-1R5M`, generics `Inductor`, `Ferrite Chip` |
| TR_Integrated.SchLib (2026-08-22, orig 2) | 4 | `M95160-DFMN6TP`, `INA219AIDCNR` (+ tool `TP4056`, `DW01`) |
| TR_LEDs.SchLib (2020-10-05) | 1 | `LY Q396` |
| TR_Opamp.SchLib (2020-10-08) | 2 | `OPA2192IDGKR` (3 parts), `OPA4192IPW` (5 parts) |
| TR_Optoisolator.SchLib (2020-10-08) | 1 | `SCH - OPTOISOLATORS - VISHAY TCMT1109` |
| TR_Oscillator.SchLib (2020-10-13) | 1 | `LFXTAL035268REEL` |
| TR_Passives.SchLib (2023-09-11) | 4 | `R - Resistor SMD` (11 footprints), `C - Ceramic SMD` (6 footprints), `T495X476K035ATE300`, `NFM18PS105R0J3D` |
| TR_Power-Linear.SchLib (2022-11-13) | 1 | `AP2138N-3.6TRG1` |
| TR_Power-Switchmode.SchLib (2026-08-22, orig 3) | 4 | `LMR50410YQDBVRQ1`, `LTC3128EUFD#PBF`, `MP3431GL-P` (+ tool `MCP1640`) |
| WL-SMCW_0603.SchLib (2020, vendor) | 14 | `150060YS75020` … `150060AS75000` |
| Battery_Power_Management.SchLib (2026-08, tool) | 4 | `TP4056`, `DW01`, `MCP1640`, `FS8205A` |

### 2.2 PcbLib
| File (mtime) | # | Examples |
|---|---|---|
| TR_Passives.PcbLib (2020-11-03) | 31 | `RES 0201_0603`, `RES 0402_1005`, `RES 0402_1005 RF`, `RES 0603_1608`, `RES 0603_1608 RF`, `RES 0805_2012(+RF)`, `RES 1206_3216(+RF)`, `RES 1210_3225`, `RES 2512_6432`, `CAP 0603_1608(+RF)`, `CAP 0805_2012(+RF)`, `CAP 1206_3216`, `CAP 1206_3216 - 0.8MM/1.0MM/1.2MM/1.8MM`, `CAP 1210_3225 - 1MM/1.2MM/…/2.8MM` (9), `CAP POL 2917_7343`, `Murata NFM18PS` |
| TR_Connector.PcbLib (2022-12-20) | 11 | `PCB - CONNECTOR - WURTH 61300611121`, `PCB - CONNECTOR - Molex 5040500491`, `PCB - CONNECTOR - MOLX-53261-0271_V`, `PCB - CONNECTOR - WURTH 621004242921 TE` / `… BE` |
| TR_Inductor.PcbLib (2022-12-22) | 9 | `FER 0402_1005`, `FER 0603_1608`, `FER 0805_2012`, `FER 1206_3216 - to be checked`, `FER 1806_4516 - to be checked`, `Bourns SRP1038C`, `WE-CNSW 1812`, `WE-MAPI_4020`, `DLW5BSM601TQ2L` |
| TR_Leaded_SOT-23.PcbLib (2022-11-13) | 4 | `ON SEMI SOT-23-3`, `INFINEON SOT-23-3`, `NXP SOT-23-3 TO-236AB`, `DIODES SOT-23-3` |
| TR_Leaded_SOT.PcbLib (2020-11-02) | 3 | `NEXPERIA SC74-6 SOT457`, `TI SOT-23-6 DBV`, `TI SOT-23-8 DCN` |
| TR_Leaded_SOP.PcbLib (2020-10-08) | 4 | `TI TSSOP-14 PW`, `TI TSSOP-8 PW`, `TI VSSOP-8 DGK`, `VISHAY SSOP-4` |
| TR_Leaded_SOIC.PcbLib (2020-10-17) | 1 | `Microchip SOIC-8N` |
| TR_Leadless_QFN.PcbLib (2023-01-13) | 4 | `LTC QFN-20 UFD`, `MPS QFN-13 3x4MM`, `TI PWQFN-16 3x3MM RTE HS 1.7`, `TI PWQFN-N16 3x3MM RTE HS 0.8` |
| TR_Diode.PcbLib (2020-11-03) | 2 | `PCB - DIODES - SOD323`, `PCB - DIODES - DO214AC SMA` |
| TR_Electromechanic.PcbLib (2023-01-15) | 2 | `CKCP-PCM12SMTR_V`, `SMTRAM25-6-5ET` |
| TR_Fuse.PcbLib (2022-11-12) | 2 | `FP-1206L-MFG`, `FP-MF-GSMF-MFG` |
| TR_LEDs.PcbLib (orig .bak, 2020-10-05) | 3 | `WL-SMCW_0603 dome`, `WL-SMCW_0603_H=0.25mm`, `WL-SMCW_0603_H=0.7mm` |
| TR_Optoisolator.PcbLib (2020-10-05) | 1 | `PCB - LEADED - SOP - VISHAY SSOP-4` (file not referenced by any LibPkg) |
| TR_Oscillator.PcbLib (2020-10-13) | 1 | `CFPX-180` |
| TR_FET.PcbLib (orig .bak, 2020-10-18) | 1 | `Diodes PowerDI3333-8` |
| tool-written (excluded) | – | `FS8205A_TSSOP8`, `DW01_SOT23-6`, `TP4056_ESOP8`, `MCP1640_SOT23-6`, `SK6812HV-4P-002`, `LED_1010_RGB`, `SK6805-EC1414`, `TQFP-32_7x7_P0.8` |

### 2.3 LibPkg files [V]
* Standard Altium library packages (`[Design]`, `[Document1..n]`, default output groups, no project parameters).
* Documents are referenced relatively, e.g. `DocumentPath=SchLib\TR_Passives.SchLib`, `DocumentPath=PcbLib\TR_Passives.PcbLib`.
* Footprints are shared across packages:
  * `TR_Leaded_SOT-23.PcbLib` is used by BJT, Diode, FET and Power-Linear;
  * `TR_Leaded_SOT.PcbLib` by Diode, Integrated and Power-Switchmode;
  * `TR_Leaded_SOP.PcbLib` by Opamp and Optoisolator;
  * `TR_Leadless_QFN.PcbLib` by Converter and Power-Switchmode.
* Compiled outputs: `Project Outputs for TR_*/*.IntLib`.

---

## 3. Symbol conventions (SchLib)

### 3.1 File header: grid and fonts [V]
Verbatim TR_Passives `FileHeader` (abridged):
`|HEADER=Protel for Windows - Schematic Library Editor Binary File Version 5.0|Weight=201|MinorVersion=9|UniqueID=UCRMJDRI|FontIdCount=3|Size1=10|FontName1=Times New Roman|Size2=10|FontName2=Verdana|Size3=10|Underline3=T|FontName3=Times New Roman|UseMBCS=T|IsBOC=T|SheetStyle=9|BorderOn=T|SheetNumberSpaceSize=12|AreaColor=16317695|SnapGridOn=T|SnapGridSize=5|VisibleGridOn=T|VisibleGridSize=10|CustomX=18000|CustomY=18000|UseCustomSheet=T|ReferenceZonesOn=T|Display_Unit=0|CompCount=4|LibRef0=…`

* **Font 1** is `Times New Roman 10` in every file. It is used for the designator and Comment.
* **Font 2** is mostly `Times New Roman 10, Underline=T`, used for the hyperlink parameters `ComponentLink*URL`. TR_Passives uses `Verdana 10` (hidden parameters) instead, with TNR-underline as font 3.
* **Font 3** is `Arial 12` in TR_Opamp (part labels A/B/C).
* **Snap grid** is `5` (50 mil) in Passives, Diode, Inductors, FET (orig), Electromechanic and Opamp; `10` in Connector, Converter, LEDs, Optoisolator, Oscillator, Power-*, Integrated (orig); `1` in BJT and Fuse.
* **Visible grid** is `10`, except `5` in Electromechanic and Opamp.

### 3.2 IC ("box") symbols [V]
Examples: DAC70508ZRTET, M95160-DFMN6TP, INA219AIDCNR, AP2138N-3.6TRG1, LMR50410YQDBVRQ1, LTC3128EUFD#PBF, MP3431GL-P, PESD3V3S4UD.

* **Body:** one rectangle with corner (0,0) = top-left and the opposite corner at (W, −H). Raw record (DAC70508):
  `{'RECORD': '14', 'IsNotAccesible': 'T', 'IndexInSheet': '22', 'OwnerPartId': '1', 'Location.Y': '-150', 'Corner.X': '100', 'Color': '128', 'AreaColor': '11599871', 'IsSolid': 'T'}`
  * `Location.X=0` and `LineWidth` are omitted, i.e. 0 = "Smallest" [U for the semantics].
  * Body widths seen: 60, 80, 100, 110 units (600–1100 mil). Heights: 40–180 units.
* **Pins:**
  * Length 20 units = 200 mil (LTC3128: 30). Pitch 10 units = 100 mil, attach points on the body edge.
  * The first pin sits 10 units below the top edge; the last sits 10 units above the bottom edge (DAC: last −140, edge −150). Function groups are separated by empty rows.
  * Left side: supply first (VDD/VIN/Vcc), then control/inputs. Right side: outputs, FB, SW.
  * Top edge: switch-node pins (SW, BST, SW1, SW2). Bottom edge: AGND/PGND/NC. GND sits either at the bottom of a side or on the bottom edge.
  * Exposed pad as its own pin: `HS` named `Heat Sink` (DAC70508; the footprint `TI PWQFN-N16 … 0.8` has a pad `HS`), or the next number (`21` = GND on LTC3128).
  * `show_name` and `show_designator` are both true (8 of 9 box symbols).
  * Electrical types are used (`power`, `input`, `output`, `bidirectional`, `passive`, `open_collector`).
  * Active-low names use a backslash after each character: `C\S\`, `H\O\L\D\`, `W\P\`, `P\F\O\`, `SDO/A\L\A\R\M\`.
* **Colours:** border `128` (#800000), fill `11599871` (#FFFFB0), `IsSolid=T`. These are the Altium defaults.

### 3.3 Discrete and graphic symbols [V]
R, C, L, FB, D, Q, F, Y, LED, most connectors.

* **Drawing:** lines, polylines, (elliptical) arcs and polygons in colour `16711680` (#0000FF), `LineWidth=1`. Polygons are filled blue (`AreaColor=16711680`, `IsSolid=T`). No body box.
* **Pin visibility:** 27/54 house symbols hide both pin names and numbers (R, C, L, FB, D, Q, F, Y). 16 show numbers only (connectors, common-mode chokes, op-amps).
* **Pin hot-spots:** 48/54 symbols have every pin tip on the 100 mil grid. The other 6 are on a 50 mil grid only: `R - Resistor SMD`, `C - Ceramic SMD`, BC807-40LT1G, SI2369DS-T1-GE3, 2N7002, SMTRAM25-6-5ET.
* **Generic geometries** (units, pin x/y = body-attach end):
  * `R - Resistor SMD`: rectangle drawn as 4 polylines from (−10,−4) to (10,4). Pins 1 (left, x=−10) and 2 (right, x=10), length 5, so the tips are at ±15. Passive, names and numbers hidden.
  * `C - Ceramic SMD`: plates are line (−1,−5)→(−1,5) and polyline (1,−5)→(1,5). Pins at x=∓1, length 4 (tips ±5).
  * Tantalum `T495X476K035ATE300`: pins at ±5, length 5. Plates ±3 with height ±8, plus a polarity "+" from polylines at (−9…−5, 5) and (−7, 3…7).
  * `Inductor`: 4 half-circles (`elliptical_arc` r=2.5, centred at x=−7.5, −2.5, 2.5, 7.5, 0→180°). Pins ±10, length 10. Two core lines at y=5 and y=8. Chip inductor `LQM18PNR47NC0L` is the same without core lines.
  * `Ferrite Chip`: parallelogram polyline (0,−8),(−5,−6),(0,8),(5,6) plus lead lines; pins ±10, length 10.
  * Fuse `1206L110THYR`: rectangle −10..10 × −4..4 plus PTC slash; pins ±10, length 10.
  * Crystal `LFXTAL035268REEL`: rectangle −10..10 (#800000/#FFFFB0), plates. Pins 1 and 3 are left/right (name `Crystal`); pins 2 and 4 point down (name `GND`).
  * Diode `BZX84C12LT1G`: filled triangle (0,−10),(10,0),(0,10) plus cathode-bar polyline. Pin `1 Anode` points left from (0,0) with length 10; pin `3 Cathode` points right from (10,0) with length 10. So the origin is at the anode edge.
  * BJT `BC807-40LT1G`: B at (0,0) left, length 5; C at (5,7) up, length 3; E at (5,−7) down, length 3.
  * MOSFET `2N7002NXAKR`: G at (−14,−10) left, length 6; S at (0,−10) down, length 10; D at (0,10) up, length 10.
* **Polarity convention:** pin 1 = **Anode**, cathode = pin 2 (or pin 3 on SOT-23). `BAT54C` names its cathode `Kathode` (German).

### 3.4 Multi-part op-amps [V]
OPA2192IDGKR has 3 parts: A and B amplifiers plus C = power.

* Triangle drawn as lines (0,−20)–(40,0)–(0,20).
* IN− at (0,10) and IN+ at (0,−10), pointing left, length 20. OUT at (40,0), pointing right, length 20.
* Power part: V+ up at (20,10), V− down at (20,−10).
* Pin names are hidden; numbers are shown.
* Part labels `A`/`B`/`C` are Label records in FontID 3 (Arial 12, blue). The power part has a red `+` (colour `2232046` = #EE0E22) and a dark-blue `−` (`8323857` = #11037F).

### 3.5 Colours and line widths [V]
* Symbol graphics: `16711680` (#0000FF), `LineWidth 1`.
* Box symbol: border `128` (#800000), fill `11599871` (#FFFFB0), `LineWidth 0`.
* Pins: colour `0` (#000000).
* Designator and parameter text: `8388608` (#000080).

Colour ints are Win32 COLORREF (`0x00BBGGRR`). Note that the tool's `extract_style` prints `"#FF0000"` for 16711680, which is raw hex, not RGB (§5).

### 3.6 Designator and Comment placement and fonts [V]
* Designator raw record:
  `{'RECORD': '34', 'IndexInSheet': '-1', 'OwnerPartId': '-1', 'Location.X': '-11', 'Location.Y': '5', 'Color': '8388608', 'FontID': '1', 'Text': 'R?', 'Name': 'Designator', 'ReadOnlyState': '1', 'UniqueID': 'YHGJYWDJ'}`
* Comment raw record:
  `{'RECORD': '41', 'IndexInSheet': '-1', 'OwnerPartId': '-1', 'Location.X': '-11', 'Location.Y': '-15', 'Color': '8388608', 'FontID': '1', 'Text': '1k', 'Name': 'Comment', 'UniqueID': 'MZWREPTO'}`
* **43 of 54** house symbols use exactly designator **(−5, 5)** and Comment **(−5, −15)**, regardless of body size. Altium autoposition probably handles placement on the sheet [U].
* Exceptions:
  * R: (−11,5)/(−11,−15)
  * Tantalum: (−10,9)/(−10,−19), Comment hidden
  * NFM18: (−1,5)/(−1,−52)
  * LQM18: (−10,3)/(−10,−13)
  * Inductor: (−25,5)/(−25,−15)
  * TCMT1109: (−1,7)/(−1,−37)
  * 5 Würth connector symbols in TR_Connector: (0,0)/(20 or 30, 0)
* Comment is the only visible parameter (2 Molex connectors and the tantalum have it hidden). All other parameters are hidden, mostly at (−5,15) or (−5,25), FontID 1 or 2.

### 3.7 Designator prefixes (house symbols) [V]
| Prefix | Count | Used for |
|---|---|---|
| `U?` | 10 | ICs, PESD3V3S4UD, op-amps, optocoupler |
| `J?` | 9 | connectors |
| `D?` | 8 | diodes, TVS, LED |
| `L?` | 7 | inductors, CMC |
| `Q?` | 3 | BC807, DMPH6050, 2N7002NXAKR |
| `T?` | 3 | SI2369DS, 2N7002 (inconsistent with Q), LAN transformer 74980111211 |
| `FB?` | 3 | ferrite beads |
| `C?` | 3 | capacitors |
| `F?` | 2 | fuses |
| `R?` | 1 | resistor |
| `Y?` | 1 | crystal |
| `SW?` | 1 | switch |
| `M?` | 1 | mechanical (SMTRAM25 bracket) |
| `*` | 2 | unfinished: OPA4192IPW, SBR1A40S3-7 |

### 3.8 Parameters stored in symbols (exact names) [V]
**(a) User-defined generics** (verbatim name = value):

* `R - Resistor SMD`:
  * `Publisher` = `Tobias Rosenbusch`
  * `TK` = `100ppm`
  * `Tolerance` = `1%`
  * `Info` = `='RES '+Value+' '+Tolerance+' '+Power+' '+CurrentFootprint`
  * `Power` = `1/16W`
  * `Case/Package` = `=CurrentFootprint`
  * `Value` = `=Comment`
  * `Comment` = `1k` (visible)
* `C - Ceramic SMD`:
  * `Publisher` = `Tobias Rosenbusch`
  * `Dielectric` = `X7R`
  * `Case/Package` = `=CurrentFootprint`
  * `Info` = `='CAP CER'+Value+' '+Voltage+' '+Dielectric+' '+CurrentFootprint'`. This is stored as written: the space after `CER` is missing and there is a stray trailing quote.
  * `Tolerance` = `20%`
  * `Voltage` = `50V`
  * `Value` = `=Comment`
  * `Comment` = `100n`
* `Inductor`: only `Comment` = `=Value`.
* `Ferrite Chip`: only `Comment` = `*`.

The user's convention: **Comment holds the value; Value = `=Comment`**.

**(b) Altium Manufacturer Part Search / ciiva import set** (specific parts). Counts over 54 symbols:

| Name | Count |
|---|---|
| `Comment` | 54 |
| `Manufacturer` | 47 |
| `Manufacturer Part Number` | 47 |
| `RoHS` | 43 |
| `Supplier 1` | 40 |
| `Packaging` | 39 |
| `Pricing 1` | 38 |
| `ComponentLink1URL` / `ComponentLink1Description` | 38 each |
| `Stock 1` | 37 |
| `Category` | 36 |
| `Min Operating Temperature` / `Max Operating Temperature` | 33 each |
| `Case/Package` | 29 |
| `ComponentLink2URL`/`…Description` | 28 |
| `Supplier Part Number 1` | 25 |
| `Mount` | 24 |
| `Number of Pins` | 23 |
| `Package Quantity` | 22 |
| `Length` | 20 |
| `Width` | 18 |
| `Lead Free` | 18 |
| `Height` | 16 |
| `Termination` | 15 |
| `RoHS Compliant` | 14 |
| `REACH SVHC` | 12 |
| `Tolerance` | 12 |
| `Radiation Hardening` | 11 |

`ComponentLink1..11URL/Description` are mostly ciiva datasheet URLs. There are also many category-specific parameters, for example `Zener Voltage`, `Drain to Source Voltage (Vdss)`, `Rds On Max`, `Inductance`, `DC Resistance (DCR)`, `Capacitance`, `Voltage Rating (DC)`, `Forward Voltage`, `Clamping Voltage`, `Current Rating`, `Self Resonant Frequency`, `Case Code (Metric)`, `Case Code (Imperial)`, `Dielectric`.

Value formats: German-locale pricing (`1=0,16000, 10=0,14200, … (USD)`). `°C` is stored twice, as ANSI `Text=-55\xb0C` and as `%UTF8%Text=-55°C`.

**(c) Würth vendor set** (4 connector symbols):
`Published Date`, `Publisher` (= `Wurth Elektronik`), `Part Number`, `Pin Number`, `Mounting Technology`, `Operating Temperature`, `Type`, `Rated Current [UL]`, `Working Voltage [UL]`, `Compliance`, `Modularity`, `PCB/Cable/Panel`, `Application`, `Datasheet URL`, `Manufacturer URL`, `Package Reference`.

**(d) Murata/Mouser set** (NFM18PS105R0J3D):
`Datasheet URL`, `Package Reference`, `Brand`, `Tradename`, `Product`, `Product Category`, `Factory Pack Quantity`, `Capacitance - nF`, …

Full census: `scratchpad/user-lib-style/dump/_sch_census.txt` (231 distinct names).

### 3.9 Footprint model link (RECORD 45) [V]
Verbatim:
`{'RECORD': '45', 'OwnerIndex': '16', 'IndexInSheet': '-1', 'Description': 'Chip Resistor, 2-Leads, Body 0.60x0.30mm, IPC Medium Density', 'ModelName': 'RES 0201_0603', 'ModelType': 'PCBLIB', 'DatafileCount': '1', 'ModelDatafileEntity0': 'RES 0201_0603', 'ModelDatafileKind0': 'PCBLib', 'UniqueID': 'GQJPDOVV'}`

* The record is followed by `RECORD=46` and `RECORD=48`, plus `RECORD=47` pin-map entries where pins map to several pads. Example from the original LTC3128: `{'RECORD': '47', 'OwnerIndex': '57', 'DesIntf': '1', 'DesImpCount': '2', 'DesImp0': '1', 'DesImp1': '19'}`.
* `ModelName` and `ModelDatafileEntity0` equal the footprint name. `Description` is a copy of the footprint description.
* There is **no `ModelDatafileLocation0`/library path**, so links resolve by name.
* `IsCurrent=T` marks the default footprint. The generic R links 11 footprints (current: `RES 0603_1608 RF`); the generic C links 6 (current: `CAP 0603_1608 RF`).
* Only `ModelType=PCBLIB` occurs: no SIM, SI or 3D model links.

### 3.10 Naming, Comment and description [V]
* **LibReference:**
  * Specific parts use the full orderable MPN (`LTC3128EUFD#PBF`, `MP3431GL-P`, `BC807-40LT1G`).
  * Generics: `R - Resistor SMD`, `C - Ceramic SMD`, `Inductor`, `Ferrite Chip`.
  * Legacy 2020 style: `SCH - <CATEGORY> - <MFR> <MPN>`.
  * `DesignItemId` = LibReference where present.
* **Comment** is either the base part number without ordering suffix (`BC807-40`, `DAC70508`, `INA219`, `M95160`, `LTC3128`, `MP3431GL`, `LMR50410-Q1`, `2N7002`, `SI2369DS`, `OPA2192`, `TCMT1109`, `LFXTAL035268`), the full MPN, or a value string. Value strings: `1k`, `100n`, `47u 35V`, `1u 6V3 2A`, `470nH`, `2u2 4.7A`, `90R@100MHz 60V 2A`, `180R@100MHz`, `8VDC 1.1A`, `PPTC 3A Hold/5A Trip`.
* **ComponentDescription** is the supplier text as imported (e.g. `LDO Regulator Pos 3.6V 0.25A 3-Pin SOT-23 T/R`) or `Generic Resistor`.
* **PartCount:** the raw `PartCount` is the number of parts + 1 (`PartCount=2` for single-part symbols). The tool reports `part_count: 1`.

---

## 4. Footprint conventions (PcbLib)

### 4.1 Mechanical layer kinds in the library header [V]
These are stored as `V9_CACHE_LAYERnn_NAME/LAYERID/MECHKIND` and in the legacy `LAYER57..72NAME`. Example: `V9_CACHE_LAYER83_NAME=Top Courtyard`, `…_LAYERID=16908303` (0x0102000F = Mech 15), `…_MECHKIND=CourtyardTop`. They are also stored in `Library/LayerKindMapping/Data` as (layerId, kind) pairs.

| Mech | House variant A (Connector, SOIC, SOP, SOT-23, QFN, Optoisolator, Oscillator, LEDs orig, Electromechanic; 2020-10 … 2023-01) | Variant B (Passives, Leaded_SOT, FET orig: 2020; Inductor: 2022-12) | Tool template (2026-08, not house) |
|---|---|---|---|
| 1 | Board | – | – |
| 2 / 3 | Fab Notes / Assembly Notes | **Top / Bottom Designator** | Top / Bottom Assembly |
| 4 | Sheet | – | Top Courtyard |
| 5 / 6 | **Top / Bottom Assembly** | **Top / Bottom Assembly** | Bottom Courtyard / Top 3D Body |
| 7 / 8 | **Top / Bottom Value** | **Top / Bottom Value** | Bottom 3D Body / – |
| 9 / 10 | **Top / Bottom Designator** | – | – |
| 11 / 12 | Top / Bottom Dimensions | – | – |
| 13 / 14 | **Top / Bottom 3D Body** | **Top / Bottom 3D Body** | – |
| 15 / 16 | **Top / Bottom Courtyard** | **Top / Bottom Courtyard** | – |
| 17 / 18 | Top / Bottom Component Center | same | – |
| 19 / 20 | Top / Bottom Component Outline | same | – |

* Layer pairs (`MECHPAIRn`), variant A: 15/16, 13/14, 11/12, 5/6, 7/8, 17/18, 19/20, 9/10.
* Variant B has 2/3 instead of 9/10.
* TR_Diode is a hybrid (2/3 = Designator, and Mech 10 is named "Top Designator").
* TR_Fuse leaves 9/10 unnamed.

### 4.2 What goes on which layer: 79 house footprints, true layers incl. V7 [V]
| Element | Layer | Primitive / width | Prevalence |
|---|---|---|---|
| Silkscreen | Top Overlay | tracks/arcs/regions; 0.15 or 0.20 mm | 76/79 |
| Courtyard | **Mech 15** | 4 tracks (rectangle), **0.05 mm** | 298 tracks |
| Courtyard centre cross | Mech 15 | 2 tracks, ±0.5 mm (smaller on tiny parts), **0.1 mm** | 74/79 |
| Assembly body outline | **Mech 5** | 4 tracks **0.1 mm** (+ pin-1 circle, + cathode fill on diodes) | 74/79 |
| Component centre | **Mech 17** | 2 tracks cross ±0.5 mm, 0.1 mm | 68/79 |
| Component outline | **Mech 19** | 4 tracks body rectangle, 0.1 mm (0.15 in 2) | 68/79 |
| 3D body | **Mech 13** | ComponentBody, `V7_LAYER=MECHANICAL13`, embedded STEP. TR_Passives also has 4 tracks of 0.1 mm body outline. | 69/79 (10 on Mech 1 = mistake) |
| `.Designator` | **Mech 9** (variant-A libs) / **Mech 2** (variant-B libs incl. TR_Diode) / Mech 5 (TR_Fuse) | text | 31 / 46 / 2 |
| `.Comment` | **Mech 7** | text | 79/79 |
| Bottom-side mech layers 6/8/10/14/16/18/20 | unused | – | 0 |

There is **no** `.Designator` (or `.Comment`) on Top Overlay in any house footprint. Silkscreen designators are not part of the footprints.

### 4.3 Silkscreen [V]
* **Width by library:**
  * 0.15 mm: Passives (26/31), Inductor (7/9), Leaded_SOT (2020), Oscillator, Optoisolator.
  * 0.20 mm: Connector (11/11), SOT-23 (2022), SOIC, SOP (3/4), QFN, Diode, Fuse.
  * Overall: 0.15 = 41 footprints, 0.20 = 33.
* **Clearance silk → pad copper** (edge to edge, n = 75): median **0.19 mm**, 25th percentile 0.137, min 0.05 (one connector), max 0.725.
* **Shapes:**
  * 2-terminal chips: two lines parallel to the long body edges spanning about the body length (RES 0603: y=±0.7, x −0.75..0.75, w 0.15). Several sizes add a centre line (0,−0.7)→(0,0.7).
  * SOT-23: partial outline that avoids the pads (right side and top/bottom stubs) plus a short line between pins 1 and 2 (`(-0.7,-0.25)->(-0.7,0.25)`).
  * TSSOP/SOIC: body outline (±1.6 × ±2.5 for TSSOP-14) with a chamfered pin-1 corner, an arc r=0.6 and a filled sector region at the pin-1 corner.
  * QFN: four corner brackets (`(-1.5,1.565)->(-1.5,2.0)->(-1.35,2.0)` etc.).
  * DO-214AC: outline plus a diode symbol (triangle region + bar) inside the silk outline.

### 4.4 Pads [V]
* SMD pads are on Top Layer. 64 footprints use `rounded_rectangle` with **corner radius 50 %**. Others:
  * SOIC/TSSOP gull-wing ICs use `round` (obround).
  * QFNs use rounded 25 % / 75 % or round, with a rectangular exposed pad.
  * Two footprints use 10 %.
* Pads are often stored with `rotation=90` and swapped X/Y (an IPC-wizard artefact). For example RES 0603 pad `0.950x0.850 rot=90` has an effective 0.85 (x) × 0.95 (y).
* THT pads (Multi-Layer) are `round`, with pad 1 `rectangle` (square).
* Designators are numeric. The exposed pad is either `n+1` (17, 21) or `HS`.
* Solder and paste mask: `from_rule` (38) or raw mode 0 (tool: `none`, 40); semantics of 0 [U]. Only 3 footprints have local overrides.

### 4.5 Pin-1 marking [V]
* **Silk dot:** full-circle arc **r=0.125 mm, width 0.25** (filled Ø0.5 mm) in 17 footprints; r=0.1/w=0.2 (Ø0.4) in 3. It sits outside the body next to pin 1:
  * SOT-23: pad 1 at (−1.0, 0.95), dot at (−1.0, 1.8).
  * TSSOP-14: pad 1 at (−2.8, 1.95), dot at (−2.792, 2.675).
  * QFN-13: dot at (−1.8, 2.3).
* **Assembly mark (Mech 5):** circle **r=0.5, w=0.1** inside the body at the pin-1 corner (TSSOP/QFN, 6 footprints), or a small dot r≈0.1 (SOT-23).
* **Polar 2-pins:**
  * Tantalum: silk fill.
  * Diodes: silk diode symbol plus a Mech 5 cathode-band fill at the pad-2 side. Pad 1 = anode, matching the symbol.
  * LEDs: silk triangle region.
* Non-polar chips (R/C/FB) have no pin-1 mark. 47 of 79 footprints have no explicit marker.

### 4.6 Courtyard [V]
* Rectangle on Mech 15, line 0.05 mm. Median clearance to max(pads ∪ body): **0.25 mm** (n=73).
  * "IPC Medium Density" footprints: 0.25.
  * "IPC High Density" (`… RF` names): **0.10**.
  * Connectors: mostly 0.2.
* **Rule check:** ceil((extent + 0.25) / 0.05) × 0.05 reproduces 29/45 Medium-Density footprints exactly. The remaining ones are probably IPC body-tolerance effects [U].
* Example ON SEMI SOT-23-3: pads reach x = ±1.45 and the body y = ±1.5; the courtyard is ±1.70 × ±1.75.
* A centre cross (0.1 mm, ±0.5 mm) is also drawn on Mech 15.

### 4.7 Assembly, component outline, centre and 3D body [V]
* **Mech 5 (assembly)** and **Mech 19 (component outline):** body rectangle at nominal body size, 0.1 mm. Examples: 0603 ±0.8 × ±0.4; SOT-23 ±0.7 × ±1.5; TSSOP-14 ±2.25 × ±2.5.
* **Mech 17 (centre cross):** ±0.5 mm; ±0.475 on 0603, ±0.275–0.3 on 0402, ±0.165 on 0201.
* **3D body:**
  * 77/79 are embedded STEP models named after the vendor file (`0603 resistor.STEP`, `sot-23-3-infineon.STEP`, `SO-8.STEP`, `TSSOP-14.STEP`, `SMA.STEP`). The 2 TI PWQFN have a generic body without a model.
  * Standoff is 0 for SMD. Body colour is `8421504` (#808080) in 45 footprints. Opacity 1.0.
* **Footprint `Parameters` stream** (verbatim): `|PATTERN=ON SEMI SOT-23-3|HEIGHT=53.1496mil|DESCRIPTION=SOT23, 3-Leads, Body 2.90x2.40mm, Pitch 0.95mm, IPC Medium Density|ITEMGUID=|REVISIONGUID=`. `HEIGHT` is set in 74/79 footprints.

### 4.8 Footprint text [V]
* `.Designator` and `.Comment` are centred on the origin. TrueType example: h=1.0 at lower-left (−2.252, −0.226).
* Height 1.0 mm. Exceptions: 0201 = 0.4/0.6, 0402 = 0.5/0.6, 2512 = 2.0, some connectors = 1.524.
* Font kind follows the layer variant, not the year:
  * Variant-B libraries (`.Designator` on Mech 2: Passives, Inductor, Diode) mostly use Arial TrueType (42 of 46; stroke field 0.2). Leaded_SOT and FET orig use a stroke font, 0.15.
  * Variant-A libraries (Mech 9) mostly use a stroke font with **stroke width 0.15** (25 of 31, some h=1.524/0.254). Leaded_SOT-23 and Electromechanic use TrueType.
* Raw `WideStrings` stream: `|ENCODEDTEXT0=46,68,101,115,105,103,110,97,116,111,114|ENCODEDTEXT1=46,67,111,109,109,101,110,116` (= `.Designator`, `.Comment`).

### 4.9 Origin and orientation [V]
* The origin is the centre of the pad pattern, which equals the body centre, in **69/79** footprints. Deviations are connectors and vendor parts.
* Orientation:
  * 2-terminal parts: pin 1 at −x.
  * SOT-23: pin 1 top-left (−1.0, +0.95), pin 3 right.
  * SOIC/TSSOP: pin 1 top-left, counting down the left side and up the right side.
  * QFN: pin 1 on the left side, at the top.
* Diodes: pad 1 = anode (left), pad 2 = cathode (right).

### 4.10 Footprint naming and description [V]
* **Passives:** `<TYPE> <imperial>_<metric>[ RF][ - <height>MM]` with TYPE ∈ `RES`, `CAP`, `CAP POL`, `FER`. `RF` marks the IPC High Density variant; the height suffix is used for MLCC height variants (`CAP 1210_3225 - 2.8MM`).
* **ICs:** `<MFR> <PACKAGE>[ <mfr package code>]`, e.g. `TI TSSOP-14 PW`, `ON SEMI SOT-23-3`, `NXP SOT-23-3 TO-236AB`, `LTC QFN-20 UFD`, `TI PWQFN-16 3x3MM RTE HS 1.7`.
* **Legacy 2020:** `PCB - <CATEGORY> - <MFR> <MPN/PKG>`, e.g. `PCB - CONNECTOR - WURTH 61300611121`, `PCB - DIODES - SOD323`, `PCB - LEADED - SOP - VISHAY SSOP-4`.
* **Vendor parts:** delivered name kept (`CFPX-180`, `FP-1206L-MFG`, `WE-MAPI_4020`).
* **DESCRIPTION** follows the IPC wizard text: `<Family>, <n>-Leads, Body <L>x<W>mm[, Pitch <p>mm][, Thermal Pad <a>x<b>mm], IPC <Medium|High> Density`, e.g. `Chip Resistor, 2-Leads, Body 1.60x0.80mm, IPC Medium Density`.

---

## 5. altium-designer-mcp findings that matter for implementation

1. **Fixed layer-name table [V].** The tool reports raw Mechanical 2/4/5/6/7 as `Top Assembly` / `Top Courtyard` / `Bottom Courtyard` / `Top 3D Body` / `Bottom 3D Body`. Mech 3 is presumably `Bottom Assembly` [U]. All other mechanical layers are reported as `Mechanical N`, whatever the library header says. As a result, in the user's libraries:
   * the tool's `Bottom Courtyard` is the user's **Top Assembly (Mech 5)**;
   * the tool's `Bottom 3D Body` is the user's **Top Value (Mech 7)**;
   * the tool's `Top Assembly` is the user's **Top Designator (Mech 2, variant B)**.

   I verified this by aligning all primitives against raw layer bytes:
   `'Bottom 3D Body' -> Mechanical 7 (78)`, `'Bottom Courtyard' -> Mechanical 5 (347)`, `'Top Assembly' -> Mechanical 2 (66)`, `'Top Courtyard' -> Mechanical 4 (16)`, `'Top 3D Body' -> Mechanical 6 (6)`.

   **Consequence:** to write house-style footprints with this tool, the generator must use the tool's names for the physical layers. Assembly = Mech 5 → `"Bottom Courtyard"`; value text = Mech 7 → `"Bottom 3D Body"`; courtyard → `"Mechanical 15"`; 3D body → `"Mechanical 13"`. Whether `write_pcblib` accepts `"Mechanical 5"` literally is [U] (writing was not tested).
2. **Layers above Mech 16 are invisible to the tool [V].** Primitives on Mech 17–20 are stored with legacy layer byte 72 (Mech 16) plus a u32 V7 layer id `0x0102000N`. The id sits at record offset 41 (track), 52 (arc), 226 (text), 42 (fill) or 203 (via); regions and bodies carry `V7_LAYER=MECHANICAL17` in their property string. The tool reports these primitives as `Mechanical 16` (430 tracks, 9 arcs, 1 text across all analysed files incl. `.bak`).
   * **Also:** the `write_pcblib` example in `docs/TOOLS.md` uses `"layer": "Top Courtyard"`. With the tool's table that is **Mech 4**, not the user's Mech 15 (inferred from the read mapping; write path [U]).
   * The 2026-08-22 append to `TR_LEDs.PcbLib` rewrote such primitives to real Mech 16 (V7 `0x1020011`/`0x1020013` → `0x1020010`), i.e. onto Bottom Courtyard [V].
   * Whether the tool can write Mech 17/19 at all is [U].
3. **Colour strings [V].** `extract_style` prints COLORREF ints without byte swap: `"#FF0000"` = 16711680 = blue (#0000FF in RGB).
4. **LineWidth default [V].** Rectangles whose raw record omits `LineWidth` (0) are reported with `line_width: 1`. The tool's rewrite of TR_Integrated persisted `LineWidth=1`.
5. **Rewrites lose data [V]** (comparison of the `.bak` originals with the current files):
   * RECORD 47 pin maps dropped (LTC3128: pin 1 → pads 1 and 19, pin 17 → 17 and 18, pin 15 → 15 and 16).
   * `FontIdCount` reduced from 2 to 1 while parameters still reference `FontID=2`.
   * `UniqueID` removed from RECORD 1.
   * PcbLib header replaced by the template (Mech 2–7 names, LayerKindMapping count 0, snap grid changed).

   **Recommendation:** never let the writer append to or rewrite the user's TR_* files. Write to new files.
6. The read tools accept the `.bak` paths. The degree sign is decoded correctly (U+00B0).

---

## 6. Integrity issues found in the user's libraries (reported only, nothing changed) [V]
* `TR_FET.LibPkg`: `DMPH6050SFGQ-7` → `Diodes PowerDI3333-8` is missing from the package's PcbLibs. It now exists only in `TR_FET.PcbLib.20260822_195408.bak`.
* `TR_Integrated.LibPkg`: `TP4056` and `DW01` link to footprints that exist only in `TR_Integrated.PcbLib`, which is not in the package.
* `TR_Power-Switchmode.LibPkg`: `MCP1640` has the same problem. The LTC3128 pin map was lost (see §5).
* `TR_LEDs.PcbLib`: the WL-SMCW centre and outline primitives are now on Mech 16 (Bottom Courtyard).
* No footprint link: `Ferrite Chip`, `Inductor` (generics), `LY Q396`.
* Designator `*`: `OPA4192IPW`, `SBR1A40S3-7`.
* 3D body on Mech 1 instead of Mech 13: all 9 `CAP 1210_3225 - …` footprints and `Bourns SRP1038C`.
* `TR_Optoisolator.PcbLib` is not used by `TR_Optoisolator.LibPkg`.
* The generic C `Info` formula contains a stray quote.

---

## 7. Database-relevant names
* **Use these exact existing parameter names [V-in-use]:**
  * Sourcing: `Manufacturer`, `Manufacturer Part Number`, `Supplier 1`, `Supplier Part Number 1` (MPS numbering scheme, so `Supplier 2`… are natural extensions [U])
  * Value: `Comment`, `Value`
  * Electrical: `Tolerance`, `Power`, `Voltage`, `Dielectric`, `TK`
  * Package/description: `Case/Package`, `Info`, `Publisher`, `Category`, `Mount`, `Packaging`
  * Compliance: `RoHS`
  * Physical: `Number of Pins`, `Min Operating Temperature`, `Max Operating Temperature`, `Height`
  * Datasheet links: `ComponentLink1URL`, `ComponentLink1Description`
  * Also `Datasheet URL` (Würth/Murata style) and the PcbLib footprint parameter `HEIGHT`.
* **Footprint reference** = the exact PcbLib footprint name. Symbol links carry no library path.
* **Description templates already used by the user:**
  * `Info` formulas `RES <Value> <Tolerance> <Power> <Footprint>` and `CAP CER<Value> <Voltage> <Dielectric> <Footprint>`.
  * The user's spreadsheets `C:/PartForge-Examples/Altium_Libs/{Capacitors*,240213_Capacitors_*,Resistor_Calc*}.ods` (2024-02) are Altium-365 workspace component exports. They contain item IDs (`CMP-428-000063`, `PCC-432-000016-1`, `SYM-CAP-000002-3`, `SIM-432-000293-1`) and descriptions such as `CAP CER 68pF 50V ±5% NP0 1210` and `RES SMD 360 OHM 1% 1W 2512`. Row 1 is data, i.e. there is no header row [V, first rows only].
* Third-party DbLibs exist outside `Local` (`Celestial_Altium_Library/*.DbLib`, `altium-library-master/electronpowered.dblib`). They were not analysed.
* **Recommendation [U]:**
  * DB columns: `Comment` (shown), `Value`, `Description`, `Manufacturer`, `Manufacturer Part Number`, `Supplier 1`, `Supplier Part Number 1`, `Library Ref`, `Library Path`, `Footprint Ref` (+ `Footprint Ref 2..n` for density/height variants), `Footprint Path`, `ComponentLink1URL` (datasheet), plus category-specific columns.
  * Keep Comment = displayed value as the user does.

---

## 8. House style: rules a generator can follow

**Symbols (.SchLib)**
1. Font table: Font1 = Times New Roman 10; Font2 = Times New Roman 10 underlined (for URL parameters).
2. Designator: FontID 1, colour 8388608, at (−5, 5). Comment: FontID 1, visible, at (−5, −15). All other parameters hidden (FontID 1).
3. ICs:
   * One rectangle from (0,0) to (W, −H): Color 128, AreaColor 11599871, IsSolid, LineWidth 0 (Smallest).
   * W = 60–110 units.
   * Pins: length 20, pitch 10, attach points on the box edges, first row 10 below the top, 10 margin at the bottom.
   * Supplies top-left, inputs left, outputs right, SW/BST on top, GNDs bottom.
   * Show pin names and numbers; set electrical types. Overbar via `X\`; exposed pad as an extra pin (`EP`/`HS` or n+1, matching the footprint pad).
4. Discretes:
   * Blue (16711680) lines, LineWidth 1, blue-filled polygons, no box.
   * Pin names and numbers hidden; pin tips on the 50 mil grid (passives) or 100 mil grid.
   * R: rectangle 20×8, pins length 5 at ±10. C: plates at ±1, height 10, pins length 4.
   * Diodes: pin 1 = Anode (left), last pin = Cathode (right).
5. Multi-unit ICs (op-amps): parts A/B plus a power part, triangle 40×40, IN−/IN+ at y=±10, OUT at (40,0), V+/V− on the power part. Names hidden, numbers shown.
6. Prefixes: R, C, L, FB, D, Q (transistors and FETs; prefer Q over T), U, J, F, Y, SW, M, T (transformers).
7. Parameters:
   * Generic passives: `Comment`=value; `Value`=`=Comment`; `Tolerance`, `Power`/`Voltage`/`Dielectric`/`TK`; `Case/Package`=`=CurrentFootprint`; `Info` formula; `Publisher`=`Tobias Rosenbusch`.
   * Specific parts: MPS set (`Manufacturer`, `Manufacturer Part Number`, `Supplier 1`, `Supplier Part Number 1`, …, `ComponentLink1URL`).
8. Footprint link: `ModelType=PCBLIB`, `ModelName`=`ModelDatafileEntity0`=footprint name, `ModelDatafileKind0=PCBLib`, `Description`=footprint description, no path, `IsCurrent=T` on the default. Several links are allowed (e.g. Medium plus RF variants).

**Footprints (.PcbLib, mm)**
1. Library header: AD22 layer kinds as in §4.1 variant A (Mech 5/6 Assembly, 7/8 Value, 9/10 Designator, 13/14 3D Body, 15/16 Courtyard, 17/18 Component Center, 19/20 Component Outline) with the listed pairs.
2. Pads: SMD `rounded_rectangle` with 50 % corner radius (gull-wing IC pads may use obround). THT: round, pin 1 square. Masks from rule. IPC-7351B Nominal ("IPC Medium Density"); optional "RF" variant = IPC Least/High Density.
3. Silkscreen 0.15 mm (2-terminal chips) / 0.20 mm (everything else), at least 0.15 mm from copper. Pin-1 dot r=0.125, w=0.25 outside the body next to pin 1. No designator on silk.
4. Courtyard: Mech 15 rectangle, 0.05 mm, excess 0.25 mm (0.10 for High Density), rounded up to 0.05 mm, plus a 0.1 mm centre cross ±0.5 mm.
5. Assembly: Mech 5 body rectangle 0.1 mm, pin-1 circle r=0.5 w=0.1 for ICs, cathode-band fill for diodes.
6. Mech 17 centre cross ±0.5 mm (scaled down below 0603), 0.1 mm. Mech 19 body rectangle 0.1 mm.
7. 3D: ComponentBody on Mech 13, embedded STEP, standoff 0, colour 8421504; or an extruded body to the `HEIGHT` value if no STEP is available.
8. Text: `.Designator` on Mech 9 (the variant-A "Top Designator" layer) and `.Comment` on Mech 7, centred at (0,0), height 1.0 mm, stroke font with width 0.15 (dominant variant-A style).
9. Origin at the body/pad centre. Pin 1 at the top-left (ICs) or left (2-pin). Diode pad 1 = anode.
10. Naming:
    * passives `RES|CAP|FER <imp>_<metric>[ RF][ - <h>MM]`
    * ICs `<MFR> <PKG>[ <code>]`
    * Parameter `DESCRIPTION` in IPC wizard wording; `HEIGHT` = body height in mil string (`53.1496mil`).

---

## 9. Numeric defaults (JSON)
```json
{
  "source": "user-lib-style research 2026-10-07; house = TR_* libs 2020-10..2023-11, tool-written 2026-08 content excluded",
  "schematic": {
    "units": "1 unit = 10 mil (raw Location.X/Y; altium-designer-mcp uses the same numbers)",
    "snap_grid": 5, "visible_grid": 10,
    "fonts": [{"id": 1, "name": "Times New Roman", "size": 10},
              {"id": 2, "name": "Times New Roman", "size": 10, "underline": true}],
    "designator": {"x": -5, "y": 5, "font_id": 1, "color": 8388608},
    "comment": {"x": -5, "y": -15, "font_id": 1, "color": 8388608, "visible": true},
    "hidden_parameter": {"x": -5, "y": 15, "font_id": 1, "color": 8388608},
    "pin_color": 0,
    "ic_box": {"origin": "top_left", "line_color": 128, "fill_color": 11599871, "is_solid": true,
               "line_width": 0, "pin_length": 20, "pin_pitch": 10, "top_margin": 10, "bottom_margin": 10,
               "body_width_options": [60, 80, 100, 110], "show_pin_name": true, "show_pin_number": true},
    "discrete": {"line_color": 16711680, "fill_color": 16711680, "line_width": 1,
                 "show_pin_name": false, "show_pin_number": false, "pin_tip_grid": 5},
    "resistor": {"body": [-10, -4, 10, 4], "pin_x": 10, "pin_length": 5},
    "capacitor": {"plate_x": 1, "plate_half_height": 5, "pin_x": 1, "pin_length": 4},
    "inductor": {"arc_radius": 2.5, "arc_centers_x": [-7.5, -2.5, 2.5, 7.5], "pin_x": 10, "pin_length": 10},
    "diode": {"triangle": [[0, -10], [10, 0], [0, 10]], "anode_pin": {"designator": "1", "x": 0, "length": 10},
              "cathode_pin": {"x": 10, "length": 10}},
    "opamp": {"triangle": [[0, -20], [40, 0], [0, 20]], "in_minus_y": 10, "in_plus_y": -10, "pin_length": 20},
    "footprint_link": {"ModelType": "PCBLIB", "ModelDatafileKind0": "PCBLib", "DatafileCount": 1, "library_path": null}
  },
  "footprint": {
    "units": "mm",
    "layers": {"courtyard": "Mechanical 15", "assembly": "Mechanical 5", "value_text": "Mechanical 7",
               "designator_text": "Mechanical 9", "designator_text_variant_b": "Mechanical 2", "body_3d": "Mechanical 13",
               "component_center": "Mechanical 17", "component_outline": "Mechanical 19", "silkscreen": "Top Overlay"},
    "mcp_tool_layer_names_for_these": {"Mechanical 5": "Bottom Courtyard", "Mechanical 7": "Bottom 3D Body",
                                       "Mechanical 2": "Top Assembly", "Mechanical 15": "Mechanical 15",
                                       "Mechanical 13": "Mechanical 13", "Mechanical 9": "Mechanical 9",
                                       "Mechanical 17": "NOT REPRESENTABLE (shown as Mechanical 16)",
                                       "Mechanical 19": "NOT REPRESENTABLE (shown as Mechanical 16)"},
    "mech_pairs": [[5, 6], [7, 8], [9, 10], [11, 12], [13, 14], [15, 16], [17, 18], [19, 20]],
    "pad": {"smd_shape": "rounded_rectangle", "corner_radius_percent": 50, "tht_shape": "round",
            "tht_pin1_shape": "rectangle", "mask": "from_rule"},
    "silkscreen": {"width_chip": 0.15, "width_ic": 0.20, "min_clearance_to_pad": 0.15, "median_clearance_observed": 0.19,
                   "pin1_dot_radius": 0.125, "pin1_dot_width": 0.25},
    "courtyard": {"line_width": 0.05, "excess_nominal": 0.25, "excess_high_density": 0.10, "excess_connector": 0.2,
                  "rounding_grid": 0.05, "center_cross_half": 0.5, "center_cross_width": 0.1},
    "assembly": {"line_width": 0.1, "pin1_circle_radius": 0.5, "pin1_circle_width": 0.1},
    "component_center": {"cross_half": 0.5, "line_width": 0.1, "cross_half_0603": 0.475, "cross_half_0402": 0.275, "cross_half_0201": 0.165},
    "component_outline": {"line_width": 0.1},
    "text": {"designator": ".Designator", "comment": ".Comment", "height": 1.0, "stroke_width": 0.15,
             "font": "Arial", "position": [0, 0], "justification": "middle_center"},
    "body_3d": {"embedded_step": true, "standoff": 0.0, "color": 8421504, "opacity": 1.0},
    "origin": "pad_pattern_center",
    "names": {"passive": "{TYPE} {imperial}_{metric}[ RF][ - {height}MM]", "ic": "{MFR} {PACKAGE}[ {MFR_CODE}]",
              "description": "{Family}, {n}-Leads, Body {L}x{W}mm[, Pitch {p}mm], IPC Medium Density"}
  }
}
```

---

## 10. Artifacts (all in `scratchpad/user-lib-style/`)
* **Client and config:** `mcp_client.py` (stdlib MCP client, read-only whitelist), `config.json`.
* **Dump scripts:** `dump_all.py`, `dump_baks.py`.
* **Raw parsers:** `pcblib_raw.py` (V7-aware primitive parser), `pcblib_header.py`, `schlib_raw.py`.
* **Analysis scripts:** `analyze_sch.py`, `census_sch.py`, `analyze_pcb.py`, `compact_pcb.py`, `check_courtyard.py`, `check_links.py`, `render_samples.py`.
* **Outputs:**
  * `dump/*.read.json|list.json|style.json` (tool output)
  * `raw/*.raw.json`, `rawsch/*.raw.json` (raw parses)
  * `dump/_pcb_house_compact.txt` (per-footprint table)
  * `dump/_sch_census.txt` (parameter census)
  * `dump/pcblib_headers.json`
  * `dump/_renders.json`
  * `hash_before.txt` / `stat_before.txt` (read-only proof)
