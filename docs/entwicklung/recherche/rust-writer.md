# Rust writer probe: `altium-designer-mcp.exe` v0.1.0 (standalone SchLib/PcbLib writer)

Research agent, UNDERSTAND phase, 2026-10-07. Every claim is tagged **[VERIFIED]** (I ran it or read the bytes)
or **[UNVERIFIED]** (documentation, inference, or something that still needs Altium). I did not use Altium itself,
the `mcp__altium__*` tools, or `C:/PartForge-Examples/Altium_Libs`.

Root of all my work: `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer`
(abbreviated below as `RW`).

---

## 0. TL;DR for PartForge

* The binary is a fast, self-contained MCP stdio server with 34 tools. It writes PcbLib/SchLib files that an
  independent reader (pyaltiumlib 0.7.1) parses correctly, record counts included [VERIFIED].
  Whether Altium opens them still needs to be checked by the agent that has Altium access.
* Writing works for everything PartForge needs: IPC-style SMD and THT footprints, silkscreen, typed mechanical
  layers (assembly, courtyard, 3D body), extruded 3D bodies, **embedded** STEP files, symbols with parameters,
  Comment, designator prefix, footprint links and multi-part symbols [VERIFIED].
* **The biggest architectural constraint [VERIFIED]:** every mutation rewrites the whole library file at about
  **9–12 ms per footprint** it contains. Examples: 100 footprints take 0.9 s in one call but 58 s as 100 appends;
  a single update, append or delete on a 1000-footprint library takes 12–15 s.
  So PartForge should keep many small PcbLibs (one per package family, or even one per footprint),
  which DbLib supports through a per-row `Footprint Path`, and always batch its writes.
* **Dangerous silent behaviour in `write_schlib` [VERIFIED]:**
  * A pin whose `x`/`y` is a JSON float (even `-10.0`) or whose `designator` is an int is **silently dropped**.
  * Invalid enums silently fall back to defaults (`orientation:"west"` becomes `right`, `electrical_type:"analog"`
    becomes `passive`).
  * Polygons and polylines read back as `[[x,y],...]`, but writing back requires `[{x,y}]`, so a naive
    read-modify-write **drops them**.
  * PartForge therefore needs strict client-side validation, plus a check of the `geometry` echo in each response.
* **No upsert [VERIFIED]:** `append:true` with an existing name fails ("already exists").
  Use `component_exists`, then `update_component` or an append.
* **External STEP references do not work [VERIFIED]:** with `embed:false` no model reference is written,
  although the response says `"source":"step-external"`. Always embed.

---

## 1. Files produced (absolute paths)

### Libraries for the Altium-access agent to open (all inside `RW/out`)

| File | Content |
|---|---|
| `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.PcbLib` | **Main footprint library (5 footprints).** `RESC1608X55N` (0603), `SOIC127P600X175-8N` (pad 1 later widened to 2.0 mm and first silk track set to 0.15 mm by `update_pad`/`update_primitive`), `PINHDR_1X02_P2.54MM` (THT, drilled), `CAPC2012X125N` (embedded STEP box), `RESC2012X60N` (appended, then updated). |
| `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.SchLib` | **Main symbol library (4 symbols).** `RES_0603_10K` (Value later 22k via param ops), `NE555DR` (8-pin box, overbar RESET with dot), `LM358DR` (3 parts: A, B, power), `CAP_0603_100N` (appended). |
| `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.LibPkg` | LibPkg that references the two files above |
| `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Features.PcbLib` | `QFN50P300X300X80-17N` (EP, 4 tented vias, 4 paste windowpane regions, TrueType/inverted/mirrored text, fill, arcs), `DCJACK_SLOT_TEST` (slot holes, square hole, non-plated hole, top/mid/bottom stack, keep-out track), `EXT_STEP_REF` (shows that the external STEP reference is lost), `AUTO_BODY` (`auto_3d_body` placeholder) |
| `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Features.SchLib` | `GRAPHICS_TEST`: every graphic primitive, embedded PNG, pin decorations (clock/dot/open_collector), frac pin, hidden pin, swap group, display mode 2 |
| `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/CAPC2012X125N_box.step` | STEP AP214 box 2.0 × 1.25 × 1.25 mm that I generated (`RW/make_step_box.py`) |
| `.../rust-writer/out/errors.PcbLib`, `.../rust-writer/out/errors.SchLib` | Edge cases: 31-, 32- and 80-character names (SectionKeys), Unicode name `R_Ω_µ`, name `R 0603 (1608)`, empty footprints, duplicate pins, out-of-range `owner_part_id`, off-grid pins |
| `.../rust-writer/out/perf_1000_onecall.PcbLib`, `.../rust-writer/out/perf_1000_onecall.SchLib` | 1000-part libraries (degenerate CFB directory tree, see §10) |
| `.../rust-writer/out/probe_mech_layers.PcbLib` | One footprint per layer `Mechanical 1..32` plus the six aliases (layer-mapping check) |
| `.../rust-writer/out/PartForge_Test_reimported.PcbLib` | Result of `export_library(json)` → `import_library` (identical to source) |
| `.../rust-writer/out/example_12_1.PcbLib`, `.../rust-writer/out/example_12_4.SchLib` | The §12 examples, executed verbatim from this report (clean copies of 0603 with courtyard ±0.75, SOIC-8, header; RES/NE555/LM358) |

The other files in `out/` are probe and benchmark by-products (`scale_*`, `perf_*`, `cplx_*`, `smoke_*`, `rmw_*`,
`lock_test`, `*.bak`, `x.txt`, `lower.pcblib`, `wrongtype.PcbLib`, `garbage.PcbLib`).

### Client and tooling (stdlib only unless noted)

* `RW/mcp_client.py`: the stdlib-only MCP client (`McpClient`, `call_tool`, `call_tool_raw`, CLI `tools|schema|call`).
* `RW/config.json`: server config (`allowed_paths` = `RW/out`, audit log `RW/audit.log`).
  `RW/config_tight_ratelimit.json` is a burst-3 variant used to trigger the rate limiter.
* `RW/geom.py`: IPC-style footprint builders (chip, SOIC, 1xN header).
* `RW/make_step_box.py`: minimal valid AP214 box generator.
* Test scripts: `RW/t00_handshake.py` … `RW/t15` (the t15 smoke test was inline; its log is `logs/t15_smoke.json`).
* Inspection scripts (these use the venv `RW/.venv` with olefile, pyaltiumlib and steputils):
  `RW/inspect_ole.py`, `RW/inspect_schlib.py`, `RW/oracle_pyaltiumlib.py`, `RW/cfb_tree.py`.
* `RW/logs/`: full `tools/list` (`tools_list.json`), one verbatim JSON Schema per tool (`schema_<tool>.json`),
  request and response logs (`t03_write_pcblib_request.json`, `t05_write_schlib_request.json`, …), ASCII renders,
  perf numbers (`t12_perf.json`, `t13_perf_scaling.json`) and SVG renders from pyaltiumlib (`logs/svg/`).

---

## 2. Process, protocol and client

* **Binary [VERIFIED]:** `C:/PartForge-Examples/MCP/altium-designer-mcp-windows-x86_64/altium-designer-mcp.exe`.
  * `--version` prints `altium-designer-mcp 0.1.0`. SHA-256 is `18df32a3130d69aa80f5098a068a213e6c40d631409e9b3f752a99eae18bfeeb`.
  * Usage is `altium-designer-mcp.exe [OPTIONS] [CONFIG_FILE]`, with options `-v/-vv/-vvv`, `-q`, `-h`, `-V`.
* **License:** GPL-3.0-or-later.
  * [VERIFIED] The stderr banner on every start reads: "altium-designer-mcp 0.1.0 Copyright (C) 2026 The Embedded Society … GPL-3.0-or-later".
  * [VERIFIED] stdout carries only JSON-RPC messages.
  * [UNVERIFIED legal note] Spawning it as a separate process, as `mcp_client.py` does, is the intended arms-length use.
* **Transport [VERIFIED]:** newline-delimited JSON-RPC 2.0 on stdin/stdout, UTF-8.
  * 200 pipelined concurrent requests on one pipe all succeeded in 7.7 s (≈ 38 ms each).
  * That is consistent with sequential processing [inference, UNVERIFIED].
* **Handshake [VERIFIED]:** `initialize` → `notifications/initialized` → `tools/list` → `tools/call`.
  * The client requested `"protocolVersion":"2025-06-18"`; the server answers `"protocolVersion":"2024-11-05"`.
  * Full response: `{"capabilities":{"tools":{}},"instructions":"<AGENT_GUIDE.md text>","protocolVersion":"2024-11-05","serverInfo":{"name":"altium-designer-mcp","version":"0.1.0"}}`.
  * `ping` returns `{}`.
  * An unknown JSON-RPC method gives error `-32601 "Method not found: foo/bar"`.
  * `tools/call` before `initialize` gives error `-32600 "Server not initialised"`.
* **`tools/list` [VERIFIED]:** 34 tools in one page (no `nextCursor`). Each tool has only `name`, `description` and `inputSchema`
  (no annotations, no outputSchema).
* **Result envelope [VERIFIED]:**
  * Success: `{"content":[{"type":"text","text":"<pretty-printed JSON object>"}]}`. `isError` is absent and there is no `structuredContent`.
  * Error: `{"content":[{"type":"text","text":"<message>"}],"isError":true}`. The message is either plain text
    (e.g. `Access denied: path is outside the configured allowed directories`) or a pretty JSON object such as
    `{"component":..,"details":..,"error":..,"filepath":"<file name only>","operation":..,"status":"error"}`.
    **Parse the message defensively.**
  * An unknown tool name is **not** a JSON-RPC error: it returns `isError:true` with `Unknown tool: no_such_tool`.
* **Timings [VERIFIED]:** process spawn ≈ 8 ms, `initialize` ≈ 27 ms, `tools/list` ≈ 62 ms.
* **Config file [VERIFIED working]:**
  ```json
  {"allowed_paths": ["C:/.../rust-writer/out"],
   "logging": {"level": "warn", "audit_log_path": "C:/.../rust-writer/audit.log"},
   "rate_limit": {"max_burst": 120, "refill_per_sec": 30.0}}
  ```
  * The audit log is JSON Lines, e.g. `{"timestamp":"2026-10-07T21:08:37.542052600+02:00","operation":"write_pcblib","outcome":"success","filepath":"probe_layers.PcbLib"}` [VERIFIED].
  * The user's own `C:/PartForge-Examples/MCP/altium-designer-mcp-windows-x86_64/config.json` points `allowed_paths` at
    `C:/PartForge-Examples/Altium_Libs` [VERIFIED, read only].
* **Minimal client usage (from `RW/mcp_client.py`) [VERIFIED]:**
  ```python
  from mcp_client import McpClient, ToolError
  with McpClient(exe="C:/PartForge-Examples/MCP/altium-designer-mcp-windows-x86_64/altium-designer-mcp.exe",
                 config="C:/.../rust-writer/config.json") as c:       # spawn + initialize + initialized
      tools = c.list_tools()
      res = c.call_tool("list_components", {"filepath": "C:/.../out/PartForge_Test.PcbLib"})  # parsed JSON
      raw = c.call_tool_raw("render_footprint", {...})               # raw CallToolResult
  # ToolError (isError:true) carries .text; McpError carries the JSON-RPC error object.
  ```

---

## 3. Units, coordinates and conventions

### PcbLib [VERIFIED]

* Units are **millimetres**. The origin is whatever `(0,0)` you supply; the server never re-centres anything.
* **+Y is up.** `render_footprint` draws +Y at the top, and pin 1 placed at y=+1.905 renders top-left.
* Values are quantised to Altium internal units (1/10000 mil = 2.54e-6 mm). For example 0.95 reads back as
  0.950001 and -0.8 as -0.800001, so compare with a tolerance of at least 1e-5.
* Angles are in degrees. Arcs use `start_angle`/`end_angle` with 0 to 360 giving a full circle.

### SchLib

* Units are **schematic units: 10 units = 1 grid = 100 mil**. The raw record stores the same numbers
  (`Location.X=-20` for `x1:-20`) [VERIFIED]. Reading 1 unit as 10 mil follows the Altium format convention [UNVERIFIED in the Altium UI].
* Graphics accept floats. **Pins must be JSON integers.**

### Pin geometry [VERIFIED by response echo and read-back]

* `(x,y)` is the **body end** of the pin, not the tip.
* `orientation` is the direction the pin points:
  * `left`: tip at `x-length`
  * `right`: tip at `x+length`
  * `up`: tip at `y+length`
  * `down`: tip at `y-length`
* Example: the resistor pin `{"x":-20,"y":0,"length":10,"orientation":"left"}` is echoed as
  `"body_end":{"x":-20,"y":0},"tip":{"x":-30,"y":0}`.
* Keep tips on the 10-unit grid. The server does not warn about off-grid tips: `x:-15` was accepted silently.

### Symbol conventions [VERIFIED]

* **Overbar:** write a backslash after each barred character. The JSON string `"R\\E\\S\\E\\T\\"` is stored verbatim.
* **Multi-part symbols:** set `part_count` and give every pin and graphic an `owner_part_id` (1-based).
  The raw `PartCount` is written as part_count+1, which is Altium's own convention: `PartCount=2` for 1 part, `PartCount=4` for 3 parts.

---

## 4. PCB layer names (exact, case-sensitive) [VERIFIED]

**Accepted names:**
* `Top Layer`, `Bottom Layer`, `Mid-Layer N`, `Internal Plane N`, `Multi-Layer`
* `Top Overlay`, `Bottom Overlay`, `Top Paste`, `Bottom Paste`, `Top Solder`, `Bottom Solder`
* `Keep-Out Layer`, `Drill Guide`, `Drill Drawing`
* `Mechanical 1` … `Mechanical 32`
* The aliases `Top Assembly`, `Bottom Assembly`, `Top Courtyard`, `Bottom Courtyard`, `Top 3D Body`, `Bottom 3D Body`

**Rejected names:** `MultiLayer`, `TopLayer`, `TopOverlay`, `KeepOut`, `Mechanical 33`, `Courtyard`, `Assembly`,
`mechanical 1`, `TOP OVERLAY`, `M1`, `Mech1`, `""`.
* Rejection message: `Track has invalid layer 'X'. Valid layers include: Top Layer, Bottom Layer, Top Overlay, Top Assembly, etc.`

**Alias mapping**, verified from the raw layer byte in the binary:

| Name | Raw layer | Library header written by the server |
|---|---|---|
| `Top Assembly` | Mechanical 2 (byte 58) | `LAYER58NAME=Top Assembly`, `LAYER58MECHKIND=AssemblyTop` |
| `Bottom Assembly` | Mechanical 3 (59) | `MECHKIND=AssemblyBottom` |
| `Top Courtyard` | Mechanical 4 (60) | `MECHKIND=CourtyardTop` |
| `Bottom Courtyard` | Mechanical 5 (61) | `MECHKIND=CourtyardBottom` |
| `Top 3D Body` | Mechanical 6 (62) | `MECHKIND=3DBodyTop` |
| `Bottom 3D Body` | Mechanical 7 (63) | `MECHKIND=3DBodyBottom` |

* `Mechanical 2..7` and the aliases are identical. Reading back always returns the alias, so `Mechanical 2` comes back as `Top Assembly`.
* `Mechanical 17..32` are stored as layer byte 186..201 plus a V7 layer id `0x0102_0011…0x0102_0020` in the record tail.
* The header also enables `Mechanical 13` and `Mechanical 15` as plain layers (template default).
* **Implication [UNVERIFIED]:** a company standard that uses Mech 13/15 for assembly/courtyard (the classic Altium
  IPC wizard layout) has to pass `Mechanical 13`/`Mechanical 15` explicitly. Those then have no MECHKIND.
  Alternatively, `batch_update` with `rename_layer` (dry-run verified) can move primitives between layers afterwards.
  How Altium maps typed layers when placing on a PCB with a different layer setup still needs to be checked in Altium.

**Default pad layer [VERIFIED].** The schema text says "Multi-Layer (default for SMD)", which is misleading. In practice:
* A pad **without** `hole_size` defaults to `Top Layer`.
* A pad **with** `hole_size` defaults to `Multi-Layer`.
* An SMD pad explicitly on `Multi-Layer` with no hole is accepted silently.
* A hole on a `Top Layer` pad is accepted silently.

---

## 5. `write_pcblib`: exact input (verbatim schema in `RW/logs/schema_write_pcblib.json`)

**Top level:**
* `filepath` (string, required): absolute path inside `allowed_paths`.
* `footprints` (array, required).
* `append` (bool). `false` or absent creates or overwrites the file, with a `.bak` of any old file.
* `auto_3d_body` (bool, default false).

**Footprint object.** Schema-required: `name`, `pads`. In reality `pads` may be omitted or empty; that only produces
a validation warning [VERIFIED].

| Field | Type | Notes |
|---|---|---|
| `name` | string | Required. Not empty. Must not contain `/ \ : * ? " < > \|`. Longer than 31 characters is fine, see §10. |
| `description` | string | Stored as `DESCRIPTION=` |
| `pads`, `tracks`, `arcs`, `regions`, `text`, `vias`, `fills` | arrays | See below |
| `component_bodies` | array | Extruded bodies |
| `step_model` | object | `{filepath (required), embed=true, rotation, x_offset, y_offset, z_offset}` |
| `model_3d` | object/null | Alias of `step_model` in read format. Ignored when `step_model` is given. With a full path it embeds [VERIFIED]. |
| `guid`, `primitive_order` | — | Accepted though not in the schema (listed in the unknown-field error message). Pass back what `read_pcblib` returned. |

* An unknown footprint-level key is rejected: `Unknown field 'foo'. Allowed fields are: ["name","description","pads","tracks","arcs","regions","text","vias","fills","step_model","model_3d","component_bodies","guid","primitive_order"]` [VERIFIED].
* An unknown **pad**-level key is silently ignored [VERIFIED].

### Pad

* Required: `designator` (must be a **string**), `x`, `y`, `width`, `height` (all must be **numbers**).
* Errors on violation [VERIFIED]:
  * `designator` given as an int gives "Pad missing required field 'designator'".
  * `x` given as a string gives "Pad missing required field 'x'".
  * `width` ≤ 0 gives "Pad '1' has invalid width 0. Width must be greater than 0."
* Optional fields:
  * `shape`: `rectangle | rounded_rectangle | round | circle | oval | octagonal`. Case-insensitive, `_`/`-` ignored;
    an invalid value is an error.
    * Omitted, it becomes **rounded_rectangle with corner 50 %**, even for THT pads [VERIFIED]. The schema claims corner default 0, which is wrong.
    * `oval` reads back as `round`, which is equivalent (Altium's Round with width ≠ height is an obround).
  * `corner_radius_percent`: 0..100. **150 was silently changed to 50** [VERIFIED].
  * `rotation`: degrees (45 works).
  * `layer`: see §4.
  * `hole_size`.
  * `hole_shape`: `round | square | slot`. With `slot`, also set `hole_slot_length` and `hole_rotation` [VERIFIED round-trip].
  * `is_plated`: default true. `false` works [VERIFIED].
  * `hole_positive_tolerance`, `hole_negative_tolerance`.
  * `solder_mask_expansion` with `solder_mask_expansion_mode` (`none|from_rule|manual`), and `paste_mask_expansion` with
    `paste_mask_expansion_mode`. Manual -0.85 paste and +0.05 mask round-tripped [VERIFIED].
  * `solder_mask_expansion_from_hole_edge`.
  * `stack_mode`: `simple|top_middle_bottom|full_stack`, with `per_layer_sizes` (3 or 32 entries of `{width,height}`),
    `per_layer_shapes` and `per_layer_offsets`.
    * **Non-simple stacks lose rectangular and rounded-rectangle shapes**: they read back as `round`, and only
      `round`/`octagonal` survive [VERIFIED read-back]. Use `simple`.
  * Thermal and plane fields: `power_plane_connect_style` (`relief|direct|no_connect`), `power_plane_clearance`
    (0.508), `power_plane_relief_expansion` (0.508), `relief_air_gap` (0.254), `relief_conductor_width` (0.254), `relief_entries` (4).
  * `jumper_id`.
  * `flags`: string such as `"LOCKED | KEEPOUT"` or an int bitmask.
  * Round-trip fields to pass back unchanged: `unique_id`, `identity_guid`, `identity_guid_b`, `net_index`,
    `polygon_index`, `component_index`, and the raw blobs `raw_tail`/`raw_block` that read returns.
* **Duplicate pad designators** are written, but the whole-library validation then reports
  `"Duplicate pad designator: '1'"` with severity *error* (Altium itself allows them) [VERIFIED].
* **Coordinate limit:** values beyond ±5000 mm give an error, e.g.
  "pad 0 x value 1000000 mm exceeds the maximum safe range of ±5000 mm". 5000 itself is accepted [VERIFIED].

### Other primitives (required fields in **bold**)

* **Track:** **x1, y1, x2, y2, width, layer**; optional `flags`, `keepout_restrictions`, `solder_mask_expansion`, `unique_id`.
* **Arc:** **x, y, radius, start_angle, end_angle, width, layer**.
* **Region:** **vertices** (`[{x,y}]`), **layer**; optional `holes` (`[[{x,y}]]`), `kind` (`"copper"` default, `"cutout"`
  or an int), `name`, plus round-trip keys. A region on `Top Paste` works, which suits paste windowpanes [VERIFIED].
* **Fill:** **x1, y1, x2, y2**; `layer` (default Top Layer), `rotation`.
* **Via:** **x, y, diameter, hole_size**; `from_layer`/`to_layer` (default Top/Bottom), `flags`
  (`"TENTING_TOP | TENTING_BOTTOM"` round-trips [VERIFIED]), `drill_layer_pair_type`, plus mask and thermal fields.
* **Text:** **x, y, text, height, layer**.
  * `kind`: `stroke` (default), `true_type`, `bar_code`. Related fields: `font_name` (Arial), `bold`, `italic`, `stroke_font`, `stroke_width` (default ≈ 0.1016).
  * Placement: `justification` (9 values, default bottom_left), `rotation`, `mirror`.
  * Inverted text: `is_inverted`, `inverted_border`, `use_inverted_rectangle` and `inverted_rect_*`.
  * Component fields: `is_designator`, `is_comment`.
  * Special strings such as `.Designator` are stored verbatim [VERIFIED].
* **component_bodies** (extruded): **overall_height** (mm above board).
  * Other fields: `standoff_height`, `layer` (`Top 3D Body` default), `outline` (`[{x,y}]`; if omitted, the pad bounding
    box is used), `body_color_3d` (int, default 8421504), `body_opacity_3d`, `cavity_height`, `z_offset`,
    `rotation_x/y/z`, `kind`, `is_shape_based`, the `model_*` keys and round-trip keys.

### Behaviours to know [VERIFIED]

* **Auto text:** a footprint with no `text` gets an automatic `.Designator` on **Top Overlay** at (0, 1.1), height 1.0 mm,
  stroke width 0.1016 mm, bottom_left. Supplying any text, for example `.Designator` on Top Assembly, suppresses it.
* **Response shape:**
  `{"bodies":[...],"filepath":..,"footprint_count":N,"footprint_names":[..],"status":"success","validation":{"error_count","issues","status","warning_count"},"warnings":[...]}`.
  * `validation` covers the **whole library**, not only the new parts.
  * `warnings` contains `silk_over_pad` entries such as
    `{"footprint":"SILKOVER","layer":"Top Overlay","message":"Top Overlay track overlaps pad '1' — move silkscreen clear of the pad","pad":"1","type":"silk_over_pad"}`.
* **`bodies` echo:**
  * `{"source":"extruded","overall_height":..,"standoff_height":..,"assumed_height":false}`
  * `{"source":"step-embedded"}`
  * `{"source":"none","note":...}`
  * `{"source":"auto-extruded","assumed_height":true,"action_required":...}`
* **Embedded STEP:**
  * The file must exist, be absolute and lie inside `allowed_paths`.
    * A relative path gives "Parent directory of 'x.step' does not exist".
    * A path outside the sandbox gives "Access denied".
    * A missing file gives "STEP file not found ... use embed: false for external reference".
  * It is stored compressed in `Library/Models/0`. The body record contains `MODEL.EMBED=TRUE|MODEL.NAME=<file name>|MODELID={GUID}|MODEL.CHECKSUM=0|MODEL.3D.DZ=0mil`
    together with `OVERALLHEIGHT=0mil` and `STANDOFFHEIGHT=0mil`, and an outline equal to the pad bounding box.
  * `extract_step_model` returns the 6285 identical bytes.
  * [UNVERIFIED] Whether Altium displays the model correctly and accepts CHECKSUM=0 and OVERALLHEIGHT=0.
* **`step_model.embed:false` is broken:** the body is written **without any MODEL.\* key**. `read_pcblib` shows
  `model_3d.filepath:""`, while the write response claims `{"source":"step-external","model":"C:/Libraries/3D/does_not_exist.step"}`.
* **HEIGHT parameter:** the footprint parameter stream always holds `HEIGHT=0mil`; there is no field to set it.
  Stream content: `|PATTERN=<name>|HEIGHT=0mil|DESCRIPTION=..|ITEMGUID=|REVISIONGUID=`.

---

## 6. `write_schlib`: exact input (verbatim schema in `RW/logs/schema_write_schlib.json`)

**Top level:** `filepath` (required), `symbols` (required), `append` (bool).

### Symbol

* Required: **name**, **pins** (may be empty, which gives the warning "Symbol has no pins").
* `description`: stored as `ComponentDescription=` and in the FileHeader as `CompDescr<i>`.
* `designator_prefix`: written as `<prefix>?` (`RECORD=34 Name=Designator Text=R? ReadOnlyState=1`) [VERIFIED].
  * If it is omitted, the documented fallback is `component_type` (`resistor` → R, … unknown → U) [UNVERIFIED].
  * With neither prefix nor type, the result is `U?` [VERIFIED].
* `designator_x`/`designator_y`: default -5/5.
* `part_count` (default 1), `current_part_id`, `part_id_locked`, `display_mode_count` (default 1).
* `parameters`, `footprints`.
* Graphic arrays: `rectangles`, `round_rects`, `lines`, `polylines`, `polygons`, `arcs`, `ellipses`,
  `elliptical_arcs`, `pies`, `beziers`, `labels` (RECORD 4), `text` (RECORD 3), `text_frames` (RECORD 28), `images` (RECORD 30).
* `source_library_name`, `target_file_name` (default `*`), `designator_unique_id`.

### Pin

* Required: **designator** (string), **name** (string), **x** (int), **y** (int), **length** (number), **orientation**.
* Optional:
  * `electrical_type`: `input|output|bidirectional|passive|power|open_collector|open_emitter|hi_z|tristate`; default passive.
  * Visibility: `hidden`, `show_name`, `show_designator`.
  * Decorations: `symbol_inner_edge` (e.g. `clock`), `symbol_outer_edge` (e.g. `dot`), `symbol_inside` (e.g. `open_collector`), `symbol_outside`.
    All three examples round-tripped [VERIFIED].
  * `owner_part_id`, `owner_part_display_mode`, `swap_id_group`, `part_and_sequence`, `description`, `default_value`, `colour`.
  * `frac` = `{x,y,length}` in 1/100000-unit steps; round-tripped [VERIFIED].
  * `symbol_line_width`, `graphically_locked`.

**Strictness matrix for pins [VERIFIED]. These are silent, no error:**

| Input | Result |
|---|---|
| `x: -12.5` or `x: -10.0` (JSON float) | **Pin dropped.** Response echo `"pins": []`; validation warns "Symbol has no pins" |
| `designator: 1` (int) | **Pin dropped** |
| `orientation: "west"` | Stored as `right` |
| `electrical_type: "analog"` | Stored as `passive` |
| `symbol_outer_edge: "sparkle"` | Stored as `none` |
| `length: 10.5` | Truncated to 10 |
| `length: 0` | Accepted; validation warning "Pin '1' has zero or negative length: 0" |
| `owner_part_id: 3` with `part_count: 1` | Accepted, no warning |
| Footprint link without `name` | Link silently dropped |
| Duplicate pin designators (also across display modes) | Written; validation reports *error* "Duplicate pin designator" |

### Parameters

* Required: **name**. `value` defaults to `*`.
* Optional: `hidden`, `x`, `y`, `color` (BGR int, default 0x800000), `font_id`, `param_type` (0 = String, 1 = Bool, 2 = Int, 3 = Float),
  `read_only_state`, `show_name`, `hide_name`, `orientation` (0–3), `justification` (0–8), `auto_position`, `is_configurable`,
  `is_rule`, `is_system_parameter`, `description`, `owner_part_id`, `unique_id`, `text_horz_anchor`, `text_vert_anchor`.
* **Comment [VERIFIED raw]:** the component's Comment is just a parameter named `Comment`, stored as `|RECORD=41|…|Text==Value|Name=Comment|`.
* **Unicode [VERIFIED raw]:** for `±1%` the record is `Text=\xc2\xb11%|%UTF8%Text=\xc2\xb11%`, i.e. **UTF-8 bytes in both keys**.
  * Altium's own files put cp1252 in `Text=`.
  * pyaltiumlib, which reads the plain key, shows `Â±1%`.
  * [UNVERIFIED] What Altium shows (it probably prefers the `%UTF8%` key).

### Footprint links

* Format: `[{name (required), library_path?, description?}]`.
* The first link is `IsCurrent=T`.
* Raw record [VERIFIED]:
  `|RECORD=45|OwnerIndex=12|IndexInSheet=-1|Description=0603 IPC-7351B nominal|ModelName=RESC1608X55N|ModelType=PCBLIB|DatafileCount=1|ModelDatafile0=C:/.../out/PartForge_Test.PcbLib|ModelDatafileEntity0=RESC1608X55N|ModelDatafileKind0=PCBLib|IsCurrent=T|UniqueID=EZUTKTOT`
  followed by `RECORD=46` and `RECORD=48`.
  * The path is stored with **forward slashes**, exactly as given.
  * There is **no check** that the footprint exists. `RESC2012X60N` was linked before it existed.

### Response [VERIFIED]

`{"filepath":..,"geometry":[{"name":..,"bounding_box":{min_x,min_y,max_x,max_y},"pins":[{"designator","name","orientation","body_end":{x,y},"tip":{x,y}}]}],"status":"success","symbol_count":N,"symbol_names":[..],"validation":{...}}`.
**Compare the echoed pin count against the pins you sent** to catch silent drops.

### DbLib relevance [UNVERIFIED, standard Altium behaviour]

In a DbLib, Altium takes the symbol from `[Library Ref]`/`[Library Path]` and the footprints from
`[Footprint Ref]`/`[Footprint Path]` columns, and the parameters from DB columns. Symbols written for DbLib use can
therefore be generic (`RES`, `CAP`, `OPAMP_DUAL`), without parameters or footprint links.

---

## 7. Read and inspect tools: response shapes [VERIFIED]

* **`read_pcblib {filepath, component_name?, limit?, offset?, compact?=true}`** returns
  `{compact, filepath, footprints:[...], has_more, offset, returned_count, status, total_count, units:"mm"}`.
  * Footprint keys: `arcs, component_bodies, description, fills, model_3d, name, pads, primitive_order, regions, text, tracks, vias`.
  * Primitives carry raw round-trip blobs (`raw_tail`, `raw_geometry`, `raw_block`, `param_key_order`).
  * Body `outline` comes back as `[[x,y],...]` pairs; region `vertices` come back as `[{x,y}]`.
* **`read_schlib {filepath, component_name?, limit?, offset?}`** returns `{filepath, has_more, offset, returned_count, status, symbols:[...], total_count, units}`.
  * Symbol keys: all write keys plus `designator` (e.g. `"R?"`) and `primitive_order`. Empty arrays are omitted in `get_component` output.
  * Pins add `formal_type`, `is_not_accessible`.
  * **Polygons and polylines `points` come back as `[[x,y],...]` pairs, which `write_schlib`/`update_component` do not accept (see §8).**
* **`get_component {filepath, component_name}`** returns `{component:{...}, component_name, filepath, message, status, type:"PcbLib"|"SchLib", units}`.
* **`list_components {filepath, include_metadata?, limit?, offset?}`** returns `{components:[names] | [objects], file_type, filepath, has_more, include_metadata, offset, returned_count, status, total_count}`.
  * PcbLib metadata: `{arc_count, description, has_3d_model, name, pad_count, region_count, text_count, track_count}`.
  * SchLib metadata: `{description, designator, footprint_count, name, part_count, pin_count}`.
* **`render_footprint {filepath, component_name, scale=2 chars/mm, max_width=80, max_height=40}`** returns
  `{component_name, filepath, render:"<ASCII>", scale, status}`. Legend: `# pad, - track, o arc, + origin`.
* **`render_symbol {…, part_id=1 (0 = all parts overlaid), scale=1 char/10 units}`** returns `{…, part_id, render}`.
  It does **not draw polygons**: the op-amp triangles are missing from the ASCII.
* **`validate_library {filepath}`** returns `{component_count, error_count, file_type, filepath, issues:[{component, issue, severity}], status:"valid"|"warnings"|"invalid", warning_count}`.
  * Flags: no pads or pins (warning), duplicate pad or pin designator (error), zero pin length (warning).
  * Does **not** flag: hole ≥ pad, a hole on a single-layer pad, an SMD pad on Multi-Layer, off-grid pins, `owner_part_id` > `part_count`.
* **`extract_step_model`:**
  * `mode:list` returns `{models:[{id:"{GUID}", name, size_bytes}], …}`.
  * `mode:auto` with `output_path` writes the file.
* **`extract_style`** returns layer usage, pad-shape counts, track widths per layer and text heights (PcbLib), or colours, pin lengths and line widths (SchLib).
* **`export_library {format:json|csv}`:**
  * JSON has the same `footprints` shape as `read_pcblib`, so it can be fed directly to `import_library {output_path, json_data}`.
    That round-trip was **identical** for all 5 footprints (`compare_components`), taking 75 ms.
  * CSV is a summary table.

---

## 8. Maintenance operations [VERIFIED unless noted]

### Append

* `write_pcblib`/`write_schlib` with `append:true` adds the new components. Untouched components remain
  **byte-identical** at OLE-stream level (sha256 of each `Data`/`Header`/`Parameters`/`WideStrings` stream and of
  `Library/Models/0`). This was checked after a sequence of append, update, copy, rename and delete.
  * Besides the components that were deliberately edited (here `SOIC127P600X175-8N/Data`), only `FileHeader`,
    `Library/Data`, `Library/ComponentParamsTOC/Data` and `Library/PadViaLibrary/Data` changed.
  * SchLib: `LM358DR/Data`, `NE555DR/Data` and `Storage` were unchanged after an append, update and parameter edits on other symbols.
* `append:true` on a non-existent file creates the file.
* `append:true` with an existing name returns `isError`: `Footprint 'RESC1608X55N' already exists in the library` (or `Symbol '…' already exists…`).
* Duplicate names within one call: error `Duplicate footprint name: 'X'`.
* **Write calls are atomic.** A batch failing on its 2nd item (duplicate or invalid layer) leaves the file **sha256-identical**.

### Upsert pattern

1. `component_exists {filepath, component_names:[..]}` returns `{all_exist, exists_count, results:[{exists, name}]}`.
2. Then `update_component` for existing names and `write_*` with `append:true` for new ones.

### `update_component {filepath, component_name, footprint|symbol, dry_run?}`

* Replaces the component in place, keeping its position in the library.
* If `footprint.name` differs from `component_name`, the component is **renamed** (`"renamed": true/false` in the response).
* `dry_run` only reports name and description changes in `changes`; geometry changes are not listed.
* **Read-modify-write fidelity:**
  * Replaying a `get_component` footprint unchanged gave an identical component (`compare_components identical:true`). Changing one pad height produced exactly that one difference.
  * **Replaying a symbol unchanged lost its polygons and polylines.** Converting them first fixes it, after which the replay is identical:
    ```python
    for key in ("polygons", "polylines"):
        for prim in sym.get(key, []):
            prim["points"] = [{"x": p[0], "y": p[1]} if isinstance(p, list) else p for p in prim["points"]]
    ```

### Other editing tools

* **`update_pad {filepath, component_name, designator, updates:{x,y,width,height,shape,rotation,hole_size}, dry_run?}`**
  returns `{"changes":[{"new":2.0,"old":1.950001,"property":"width"},…]}`.
* **`update_primitive {filepath, component_name, primitive_type: track|arc|region|text|fill|via, index, updates:{…}}`**:
  index-based (0-based within that primitive type). I used it to move the 0603 courtyard to y=±0.75.
* **`delete_component {filepath, component_names:[..], dry_run?}`** returns per-name status
  `would_delete|deleted|not_found`, plus `orphaned_models_removed` and `remaining_count`.
* **`copy_component`, `rename_component`, `copy_component_cross_library`, `merge_libraries`, `reorder_components`,
  `bulk_rename` (regex with `$1`), `repair_library`:** all work; see `RW/logs/t15_smoke.json`.
  * `copy_component_cross_library` copies embedded STEP data (`embedded_models_copied:1`).
  * `merge_libraries` with `on_duplicate: skip|error|rename` worked.
* **`batch_update`:**
  * PcbLib: `update_track_width {from_width, to_width, tolerance}` and `rename_layer {from_layer, to_layer}`.
  * SchLib: `update_parameters {param_name, param_value, symbol_filter (regex), add_if_missing}`.
  * Dry runs list per-component changes.

### SchLib parameter and link helpers

* **`manage_schlib_parameters` `operation`:**
  * `list`, `get`, `set` (an unknown name gives an error telling you to use 'add'), `add`, `delete`.
  * `add` with an existing name gives an error telling you to use 'set'.
  * Optional fields: `hidden`, `param_type`, `read_only_state`, `x`, `y`, `unique_id`.
* **`manage_schlib_footprints` `operation`:**
  * `list`: entries are `{description, library_path|null, name}`.
  * `add`: `footprint_name`, optional `library_path` and `description`.
  * `remove`.

### Comparing libraries

* **`diff_libraries` is shallow.**
  * PcbLib: it reported SOIC as unchanged after its pad width and track width were modified.
  * SchLib: it reports description and footprint_count changes but not parameter values.
* **`compare_components` is accurate.** It lists pad size and track width changes and parameter value, added and removed differences.

### Backups

* Before every mutation the server copies the old file to `<lib>.<YYYYMMDD_HHMMSS>.bak` **in the same folder**.
  * At most **5** are retained per library.
  * The timestamp has **1-second resolution**, so several writes within one second overwrite the same `.bak` and the true pre-batch state can be lost.
  * A failed write (target locked) can still leave a `.bak`.
* `list_backups` paths mix separators (`...out\\PartForge_Test.PcbLib.20261007_211628.bak`). `restore_backup` works.
* No option to disable backups is documented in the bundled README or example config [UNVERIFIED whether a hidden option exists].

### Write strategy

* While writing, a temp file `<name>.<lowercased ext>.tmp` (e.g. `perf_100_onecall.pcblib.tmp`) appears next to the
  target and is then renamed over it, i.e. an atomic replace.
* If another process holds the target:
  * Without sharing (share=0), reads and writes fail.
  * With FILE_SHARE_READ only, reads work but writes fail with `Failed to write file: lock_test.PcbLib`.
  * In both cases the original file stays intact.
* [UNVERIFIED] Whether Altium keeps a lock on open SchLib/PcbLib documents, and whether it notices external changes.

### LibPkg

* `write_libpkg {filepath, documents:[...]}` writes 8 lines, including `DocumentPath=PartForge_Test.SchLib` and
  `DocumentPath=PartForge_Test.PcbLib` (relative to the LibPkg).
* Response: `{"count":2,"documents":[..],"note":"Open in Altium and run Project > Compile Integrated Library to produce the .IntLib.","status":"success"}`.

---

## 9. Error behaviour matrix [VERIFIED]

| Case | Result |
|---|---|
| Unknown tool | `isError` `Unknown tool: no_such_tool` |
| Missing `filepath` | `isError` `Missing required parameter: filepath` |
| `footprints:"abc"` | `isError` `Missing required parameter: footprints` (misleading text) |
| Path outside `allowed_paths`; `out/../x`; STEP outside the sandbox | `isError` `Access denied: path is outside the configured allowed directories` (nothing created) |
| Relative path | `isError` `Parent directory of 'rel.PcbLib' does not exist or is inaccessible` |
| Backslash path, lowercase `.pcblib` | Works |
| **Wrong extension** (`write_pcblib` to `x.txt`, `write_schlib` to `*.PcbLib`) | **Succeeds**: writes a PcbLib into `.txt`, or a **SchLib into a .PcbLib** file. The client must enforce extensions. |
| Read of a missing file | `isError` JSON `{"error":"Failed to read file: nope.PcbLib",...}` |
| Read of a garbage file | `isError` `Invalid OLE structure: Failed to open OLE file: Invalid CFB file (wrong magic number)…` |
| `footprints: []` | Success; an empty library file is created (104 960 bytes) |
| Invalid layer, shape or width; missing `height` | Error with JSON details (§5) |
| Name containing `/ \ : * ? " < > \|`, or empty name | `isError` `Footprint name 'SOT-23/5' contains invalid character '/'…` / `Footprint name cannot be empty` (same wording for symbols) |
| Rate limit exceeded | `isError` `Rate limit exceeded: too many write operations in a short period. Please slow down and retry.` Only mutating tools are limited; 300 read-only calls were never limited. |
| `tools/call` before `initialize` | JSON-RPC `-32600 Server not initialised` |

---

## 10. Limits [VERIFIED unless noted]

* **Names**
  * More than 31 characters is supported the way Altium does it: the OLE storage name is truncated to 31 characters
    (e.g. `RESC1608X55N_YAGEO_RC0603FR-071`), and a `SectionKeys` stream maps `LibRef→SectionKey`.
    * The full name lives in `PATTERN=` (PcbLib) or `LibRef<i>` (SchLib).
    * An 80-character name round-tripped through the tools.
    * [UNVERIFIED] How Altium displays it.
  * Spaces and parentheses work (`R 0603 (1608)`).
  * **Unicode names are written as UTF-8 bytes into the storage name and PATTERN**; the storage name shows as `R_Î©_Âµ`.
    Altium will likely show mojibake [UNVERIFIED]. **Keep names ASCII.**
* **Coordinates:** at most ±5000 mm. **Quantisation:** 2.54e-6 mm.
* **Corner radius:** 0–100 %; out-of-range values are silently replaced by 50.
* **CFB directory tree:**
  * The writer emits a **degenerate, all-black chain**. Root-children tree depth is 102 for 104 entries and 1001 for 1003 entries,
    whereas a balanced tree would be about 20 deep.
  * olefile, and therefore pyaltiumlib, crashes with `RecursionError` on the 1000-part PcbLib and SchLib unless the recursion limit is raised.
    With the limit raised, both parse fully (1000 parts each).
  * [UNVERIFIED] Whether Altium opens `perf_1000_onecall.PcbLib`.
* **Rate limiter:** default burst 120, refill 30/s.
  * With real libraries, mutations take at least ~38 ms each, so the limit was never hit: 250 sequential and 200 pipelined mutations gave 0 errors.
  * Burst 3 / refill 0.2 rejected the 4th write.
* **Payload:** 1000 footprints is a 1.66 MiB request (accepted). A full `read_pcblib` of 1000 footprints is an 8 MiB response.

---

## 11. Performance (Windows 11, this machine; client round-trip times; two runs) [VERIFIED]

| Operation | Time |
|---|---|
| Spawn + `initialize` | ≈ 35 ms |
| `write_pcblib` 100 chip footprints (2 pads, 10 tracks, 1 text, 1 body each) in **one call** | **0.905–0.917 s** (6 reps), file 531 KiB |
| Same 100 footprints as **100 calls** (`append:true`) | **57.6 s / 57.9 s**; per call first 40–48 ms, median 572 ms, p90 ≈ 990 ms, last ≈ 1.05 s |
| `write_pcblib` 1000 footprints, one call | 10.9 s / 11.2 s, file 4385 KiB |
| On the 1000-footprint lib: `read_pcblib` full | 7.9–8.0 s (8 MiB JSON) |
| … `list_components` (names) | 1.4–1.5 s |
| … `list_components` + metadata | 1.6–2.2 s |
| … `validate_library` | 1.4–1.7 s |
| … `update_component` (1 footprint) | **12.2–14.9 s** |
| … append 1 footprint | **12.5–12.7 s** |
| … delete 1 footprint | **12.0–12.3 s** |
| `write_schlib` 100 symbols, one call | 0.49–0.53 s |
| `write_schlib` 100 symbols, 100 calls | 25.6–25.8 s (median 267 ms/call) |
| `write_schlib` 1000 symbols, one call | 5.2–5.3 s (1927 KiB); `read_schlib` 3.6–4.4 s |

**Scaling.** Write *n* in one call, then append 1 to that library, then list it:

| n | Write n | Append 1 | List |
|---|---|---|---|
| 1 | 40 ms | 54 ms | 6 ms |
| 10 | 120 ms | 134 ms | 12 ms |
| 50 | 470 ms | 498 ms | 42 ms |
| 100 | 897 ms | 1023 ms | 91 ms |
| 200 | 2.03 s | 2.16 s | 208 ms |
| 400 | 4.34 s | 4.55 s | 426 ms |

* The cost is linear: about 9–11 ms per footprint for writes and about 1 ms per footprint for reads.
* Any mutation costs as much as rewriting the entire library.
* Per-footprint cost does not follow primitive count: 100 SOIC-8 took 373 ms, 100 single-pad minimal footprints (which receive the auto `.Designator` text) took 594 ms, and 100 chip footprints took about 900 ms. [UNVERIFIED cause]

---

## 12. Complete working JSON examples (all executed successfully) [VERIFIED]

The JSON blocks in 12.1, 12.2, 12.3 (header) and 12.4 were parsed **out of this report file** and executed verbatim,
with only `filepath` redirected:
* 12.1, 12.2 and 12.3 went into `RW/out/example_12_1.PcbLib`: status success, validation valid, no warnings.
* 12.4 went into `RW/out/example_12_4.SchLib`: success, pin echo counts 2/8/8, validation valid.

### 12.1 `write_pcblib`: 0603 IPC-7351B nominal

Derivation: Z=2.50, G=0.70, X=0.95, giving pads 0.90 × 0.95 at C=1.60 and a courtyard of ±1.50 × ±0.75 (0.25 excess).
The file was first written with ±0.70 and then corrected through `update_primitive`.
```json
{"name":"write_pcblib","arguments":{"filepath":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.PcbLib","append":false,"footprints":[
 {"name":"RESC1608X55N","description":"Chip resistor 0603 (1608 metric), IPC-7351B nominal",
  "pads":[{"designator":"1","x":-0.8,"y":0,"width":0.9,"height":0.95,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
          {"designator":"2","x":0.8,"y":0,"width":0.9,"height":0.95,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"}],
  "tracks":[{"x1":-0.35,"y1":0.68,"x2":0.35,"y2":0.68,"width":0.12,"layer":"Top Overlay"},
            {"x1":-0.35,"y1":-0.68,"x2":0.35,"y2":-0.68,"width":0.12,"layer":"Top Overlay"},
            {"x1":-0.8,"y1":-0.4,"x2":0.8,"y2":-0.4,"width":0.1,"layer":"Top Assembly"},
            {"x1":0.8,"y1":-0.4,"x2":0.8,"y2":0.4,"width":0.1,"layer":"Top Assembly"},
            {"x1":0.8,"y1":0.4,"x2":-0.8,"y2":0.4,"width":0.1,"layer":"Top Assembly"},
            {"x1":-0.8,"y1":0.4,"x2":-0.8,"y2":-0.4,"width":0.1,"layer":"Top Assembly"},
            {"x1":-1.5,"y1":-0.75,"x2":1.5,"y2":-0.75,"width":0.05,"layer":"Top Courtyard"},
            {"x1":1.5,"y1":-0.75,"x2":1.5,"y2":0.75,"width":0.05,"layer":"Top Courtyard"},
            {"x1":1.5,"y1":0.75,"x2":-1.5,"y2":0.75,"width":0.05,"layer":"Top Courtyard"},
            {"x1":-1.5,"y1":0.75,"x2":-1.5,"y2":-0.75,"width":0.05,"layer":"Top Courtyard"}],
  "text":[{"x":0,"y":0,"text":".Designator","height":0.4,"layer":"Top Assembly","justification":"middle_center","stroke_width":0.05}],
  "component_bodies":[{"overall_height":0.55,"standoff_height":0.0,"layer":"Top 3D Body",
     "outline":[{"x":-0.8,"y":-0.4},{"x":0.8,"y":-0.4},{"x":0.8,"y":0.4},{"x":-0.8,"y":0.4}]}]}]}}
```
Response excerpt: `{"bodies":[{"assumed_height":false,"name":"RESC1608X55N","overall_height":0.55,"source":"extruded","standoff_height":0.0}], "footprint_count":4,"status":"success","validation":{"error_count":0,"issues":[],"status":"valid","warning_count":0},"warnings":[]}`.

### 12.2 SOIC-8 (JEDEC MS-012AA, IPC-7351B nominal)

Derivation: Z=6.90, G=3.00, giving pads 1.95 × 0.60 at x=±2.475. Pin 1 is top-left and the numbering runs counter-clockwise.
```json
{"name":"SOIC127P600X175-8N","description":"SOIC-8, 1.27 mm pitch, 3.9 x 4.9 mm body, IPC-7351B nominal",
 "pads":[{"designator":"1","x":-2.475,"y":1.905,"width":1.95,"height":0.6,"shape":"rectangle","corner_radius_percent":0,"layer":"Top Layer"},
  {"designator":"2","x":-2.475,"y":0.635,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
  {"designator":"3","x":-2.475,"y":-0.635,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
  {"designator":"4","x":-2.475,"y":-1.905,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
  {"designator":"5","x":2.475,"y":-1.905,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
  {"designator":"6","x":2.475,"y":-0.635,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
  {"designator":"7","x":2.475,"y":0.635,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
  {"designator":"8","x":2.475,"y":1.905,"width":1.95,"height":0.6,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"}],
 "tracks":[{"x1":-3.45,"y1":2.51,"x2":1.95,"y2":2.51,"width":0.12,"layer":"Top Overlay"},
  {"x1":-1.95,"y1":-2.51,"x2":1.95,"y2":-2.51,"width":0.12,"layer":"Top Overlay"},
  {"x1":-0.975,"y1":2.45,"x2":1.95,"y2":2.45,"width":0.1,"layer":"Top Assembly"},
  {"x1":1.95,"y1":2.45,"x2":1.95,"y2":-2.45,"width":0.1,"layer":"Top Assembly"},
  {"x1":1.95,"y1":-2.45,"x2":-1.95,"y2":-2.45,"width":0.1,"layer":"Top Assembly"},
  {"x1":-1.95,"y1":-2.45,"x2":-1.95,"y2":1.475,"width":0.1,"layer":"Top Assembly"},
  {"x1":-1.95,"y1":1.475,"x2":-0.975,"y2":2.45,"width":0.1,"layer":"Top Assembly"},
  {"x1":-3.7,"y1":-2.7,"x2":3.7,"y2":-2.7,"width":0.05,"layer":"Top Courtyard"},
  {"x1":3.7,"y1":-2.7,"x2":3.7,"y2":2.7,"width":0.05,"layer":"Top Courtyard"},
  {"x1":3.7,"y1":2.7,"x2":-3.7,"y2":2.7,"width":0.05,"layer":"Top Courtyard"},
  {"x1":-3.7,"y1":2.7,"x2":-3.7,"y2":-2.7,"width":0.05,"layer":"Top Courtyard"}],
 "arcs":[{"x":-1.35,"y":1.85,"radius":0.2,"start_angle":0,"end_angle":360,"width":0.1,"layer":"Top Assembly"}],
 "text":[{"x":0,"y":0,"text":".Designator","height":0.8,"layer":"Top Assembly","justification":"middle_center","stroke_width":0.1}],
 "component_bodies":[{"overall_height":1.75,"standoff_height":0.1,"layer":"Top 3D Body",
   "outline":[{"x":-1.95,"y":-2.45},{"x":1.95,"y":-2.45},{"x":1.95,"y":2.45},{"x":-1.95,"y":2.45}]}]}
```

### 12.3 THT 2-pin header with drilled pads, and 0805 with an embedded STEP

```json
{"name":"PINHDR_1X02_P2.54MM","description":"Pin header 1x02, 2.54 mm pitch, straight, through-hole",
 "pads":[{"designator":"1","x":-1.27,"y":0,"width":1.7,"height":1.7,"shape":"rectangle","hole_size":1.0,"is_plated":true,"layer":"Multi-Layer"},
         {"designator":"2","x":1.27,"y":0,"width":1.7,"height":1.7,"shape":"round","hole_size":1.0,"is_plated":true,"layer":"Multi-Layer"}],
 "tracks":[{"x1":-2.62,"y1":-1.35,"x2":2.62,"y2":-1.35,"width":0.15,"layer":"Top Overlay"},
   {"x1":2.62,"y1":-1.35,"x2":2.62,"y2":1.35,"width":0.15,"layer":"Top Overlay"},
   {"x1":2.62,"y1":1.35,"x2":-2.62,"y2":1.35,"width":0.15,"layer":"Top Overlay"},
   {"x1":-2.62,"y1":1.35,"x2":-2.62,"y2":-1.35,"width":0.15,"layer":"Top Overlay"},
   {"x1":-2.54,"y1":-1.27,"x2":2.54,"y2":-1.27,"width":0.1,"layer":"Top Assembly"},
   {"x1":2.54,"y1":-1.27,"x2":2.54,"y2":1.27,"width":0.1,"layer":"Top Assembly"},
   {"x1":2.54,"y1":1.27,"x2":-2.54,"y2":1.27,"width":0.1,"layer":"Top Assembly"},
   {"x1":-2.54,"y1":1.27,"x2":-2.54,"y2":-1.27,"width":0.1,"layer":"Top Assembly"},
   {"x1":-2.8,"y1":-1.5,"x2":2.8,"y2":-1.5,"width":0.05,"layer":"Top Courtyard"},
   {"x1":2.8,"y1":-1.5,"x2":2.8,"y2":1.5,"width":0.05,"layer":"Top Courtyard"},
   {"x1":2.8,"y1":1.5,"x2":-2.8,"y2":1.5,"width":0.05,"layer":"Top Courtyard"},
   {"x1":-2.8,"y1":1.5,"x2":-2.8,"y2":-1.5,"width":0.05,"layer":"Top Courtyard"}],
 "text":[{"x":0,"y":0,"text":".Designator","height":1.0,"layer":"Top Assembly","justification":"middle_center","stroke_width":0.1}],
 "component_bodies":[{"overall_height":2.54,"standoff_height":0,"layer":"Top 3D Body",
   "outline":[{"x":-2.54,"y":-1.27},{"x":2.54,"y":-1.27},{"x":2.54,"y":1.27},{"x":-2.54,"y":1.27}]}]}
```
```json
{"name":"CAPC2012X125N","description":"Chip capacitor 0805 (2012 metric) with embedded STEP",
 "pads":[{"designator":"1","x":-0.95,"y":0,"width":1.0,"height":1.45,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"},
         {"designator":"2","x":0.95,"y":0,"width":1.0,"height":1.45,"shape":"rounded_rectangle","corner_radius_percent":25,"layer":"Top Layer"}],
 "tracks":[ "... silk, assembly and courtyard as for 0603; see RW/logs/t03_write_pcblib_request.json ..." ],
 "text":[{"x":0,"y":0,"text":".Designator","height":0.5,"layer":"Top Assembly","justification":"middle_center","stroke_width":0.05}],
 "step_model":{"filepath":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/CAPC2012X125N_box.step",
               "embed":true,"rotation":0,"x_offset":0,"y_offset":0,"z_offset":0}}
```
The `tracks` placeholder above is abbreviated in this report only; the verbatim, complete request is in `RW/logs/t03_write_pcblib_request.json`.

QFN exposed pad and paste windowpane (from `RW/t11_features.py`):
```json
{"designator":"17","x":0,"y":0,"width":1.7,"height":1.7,"shape":"rectangle",
 "paste_mask_expansion":-0.85,"paste_mask_expansion_mode":"manual","solder_mask_expansion":0.05,"solder_mask_expansion_mode":"manual"}
```
Plus regions such as `{"layer":"Top Paste","vertices":[{"x":-0.725,"y":-0.725},{"x":-0.125,"y":-0.725},{"x":-0.125,"y":-0.125},{"x":-0.725,"y":-0.125}]}`
and vias such as `{"x":-0.5,"y":-0.5,"diameter":0.5,"hole_size":0.25,"flags":"TENTING_TOP | TENTING_BOTTOM"}`.

Slot pad: `{"designator":"1","x":0,"y":0,"width":3.5,"height":1.8,"shape":"oval","hole_size":1.0,"hole_shape":"slot","hole_slot_length":2.6,"hole_rotation":0,"layer":"Multi-Layer"}`.

### 12.4 `write_schlib`: resistor, 8-pin IC, and 3-part op-amp

```json
{"name":"write_schlib","arguments":{"filepath":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.SchLib","append":false,"symbols":[
{"name":"RES_0603_10K","description":"Thick film resistor 10 kOhm 1% 0.1 W 0603","designator_prefix":"R","component_type":"resistor","designator_x":-10,"designator_y":10,
 "pins":[{"designator":"1","name":"1","x":-20,"y":0,"length":10,"orientation":"left","electrical_type":"passive","show_name":false,"show_designator":false},
         {"designator":"2","name":"2","x":20,"y":0,"length":10,"orientation":"right","electrical_type":"passive","show_name":false,"show_designator":false}],
 "rectangles":[{"x1":-20,"y1":-4,"x2":20,"y2":4,"filled":false,"line_width":1}],
 "parameters":[{"name":"Comment","value":"=Value","x":-10,"y":-15},{"name":"Value","value":"10k","x":10,"y":-15,"hidden":true},
   {"name":"Manufacturer","value":"Yageo","hidden":true},{"name":"Manufacturer Part Number","value":"RC0603FR-0710KL","hidden":true},
   {"name":"Tolerance","value":"\u00b11%","hidden":true},{"name":"Power","value":"0.1W","hidden":true},{"name":"Resistance","value":"10k\u03a9","hidden":true,"param_type":0}],
 "footprints":[{"name":"RESC1608X55N","library_path":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.PcbLib","description":"0603 IPC-7351B nominal"},
               {"name":"RESC2012X60N","library_path":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.PcbLib","description":"0805 alternative"}]},
{"name":"NE555DR","description":"Single precision timer, SOIC-8","designator_prefix":"U","designator_x":-40,"designator_y":55,
 "pins":[{"designator":"2","name":"TRIG","x":-40,"y":30,"length":20,"orientation":"left","electrical_type":"input"},
  {"designator":"6","name":"THR","x":-40,"y":10,"length":20,"orientation":"left","electrical_type":"input"},
  {"designator":"5","name":"CV","x":-40,"y":-10,"length":20,"orientation":"left","electrical_type":"input"},
  {"designator":"4","name":"R\\E\\S\\E\\T\\","x":-40,"y":-30,"length":20,"orientation":"left","electrical_type":"input","symbol_outer_edge":"dot"},
  {"designator":"8","name":"VCC","x":40,"y":30,"length":20,"orientation":"right","electrical_type":"power"},
  {"designator":"7","name":"DIS","x":40,"y":10,"length":20,"orientation":"right","electrical_type":"open_collector"},
  {"designator":"3","name":"OUT","x":40,"y":-10,"length":20,"orientation":"right","electrical_type":"output"},
  {"designator":"1","name":"GND","x":40,"y":-30,"length":20,"orientation":"right","electrical_type":"power"}],
 "rectangles":[{"x1":-40,"y1":-50,"x2":40,"y2":50}],
 "parameters":[{"name":"Comment","value":"NE555DR","x":-40,"y":-60},{"name":"Manufacturer","value":"Texas Instruments","hidden":true},
   {"name":"Manufacturer Part Number","value":"NE555DR","hidden":true},{"name":"Datasheet","value":"https://www.ti.com/lit/ds/symlink/ne555.pdf","hidden":true}],
 "footprints":[{"name":"SOIC127P600X175-8N","library_path":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.PcbLib"}]},
{"name":"LM358DR","description":"Dual operational amplifier, SOIC-8 (multi-part: A, B, power)","designator_prefix":"U","part_count":3,
 "pins":[{"designator":"2","name":"-","x":-20,"y":10,"length":20,"orientation":"left","electrical_type":"input","owner_part_id":1,"show_name":true},
  {"designator":"3","name":"+","x":-20,"y":-10,"length":20,"orientation":"left","electrical_type":"input","owner_part_id":1,"show_name":true},
  {"designator":"1","name":"OUT","x":30,"y":0,"length":20,"orientation":"right","electrical_type":"output","owner_part_id":1,"show_name":false},
  {"designator":"6","name":"-","x":-20,"y":10,"length":20,"orientation":"left","electrical_type":"input","owner_part_id":2,"show_name":true},
  {"designator":"5","name":"+","x":-20,"y":-10,"length":20,"orientation":"left","electrical_type":"input","owner_part_id":2,"show_name":true},
  {"designator":"7","name":"OUT","x":30,"y":0,"length":20,"orientation":"right","electrical_type":"output","owner_part_id":2,"show_name":false},
  {"designator":"8","name":"V+","x":0,"y":20,"length":20,"orientation":"up","electrical_type":"power","owner_part_id":3},
  {"designator":"4","name":"V-","x":0,"y":-20,"length":20,"orientation":"down","electrical_type":"power","owner_part_id":3}],
 "polygons":[{"points":[{"x":-20,"y":30},{"x":-20,"y":-30},{"x":30,"y":0}],"owner_part_id":1},
             {"points":[{"x":-20,"y":30},{"x":-20,"y":-30},{"x":30,"y":0}],"owner_part_id":2}],
 "rectangles":[{"x1":-10,"y1":-20,"x2":10,"y2":20,"owner_part_id":3}],
 "parameters":[{"name":"Comment","value":"LM358DR"},{"name":"Manufacturer Part Number","value":"LM358DR","hidden":true}],
 "footprints":[{"name":"SOIC127P600X175-8N","library_path":"C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/rust-writer/out/PartForge_Test.PcbLib"}]}]}}
```
Response geometry echo for pin 1 of the resistor: `{"body_end":{"x":-20,"y":0},"designator":"1","name":"1","orientation":"left","tip":{"x":-30,"y":0}}`.
Bounding box: `{"max_x":30,"max_y":4,"min_x":-30,"min_y":-4}`.

### 12.5 Maintenance calls (all executed)

```json
{"name":"update_component","arguments":{"filepath":".../PartForge_Test.PcbLib","component_name":"RESC2012X60N","footprint":{ "...full footprint object, same format as write_pcblib..." }}}
{"name":"update_pad","arguments":{"filepath":".../PartForge_Test.PcbLib","component_name":"SOIC127P600X175-8N","designator":"1","updates":{"width":2.0,"shape":"rectangle"}}}
{"name":"update_primitive","arguments":{"filepath":".../PartForge_Test.PcbLib","component_name":"RESC1608X55N","primitive_type":"track","index":6,"updates":{"y1":-0.75,"y2":-0.75}}}
{"name":"delete_component","arguments":{"filepath":".../PartForge_Test.PcbLib","component_names":["RESC1608X55L","TEMP_RENAMED_BY_UPDATE"],"dry_run":false}}
{"name":"manage_schlib_parameters","arguments":{"filepath":".../PartForge_Test.SchLib","component_name":"RES_0603_10K","operation":"set","parameter_name":"Value","value":"22k"}}
{"name":"manage_schlib_parameters","arguments":{"filepath":".../PartForge_Test.SchLib","component_name":"RES_0603_10K","operation":"add","parameter_name":"Package","value":"0603","hidden":true}}
{"name":"manage_schlib_footprints","arguments":{"filepath":".../PartForge_Test.SchLib","component_name":"RES_0603_10K","operation":"add","footprint_name":"RESC1005X40N","library_path":"C:/.../out/PartForge_Test.PcbLib"}}
{"name":"batch_update","arguments":{"filepath":".../PartForge_Test.SchLib","operation":"update_parameters","dry_run":true,"parameters":{"param_name":"Manufacturer","param_value":"ACME","symbol_filter":"^(RES|CAP)_","add_if_missing":true}}}
{"name":"write_libpkg","arguments":{"filepath":".../out/PartForge_Test.LibPkg","documents":[".../out/PartForge_Test.SchLib",".../out/PartForge_Test.PcbLib"]}}
```
The full request and response pairs are in `RW/logs/t07_modify_pcb.json`, `t09_modify_sch.json` and `t15_smoke.json`.

---

## 13. Bugs and pitfalls, ranked by impact on PartForge [all VERIFIED]

1. Whole-library rewrite on every mutation, at about 10 ms per footprint (§11).
2. `write_schlib` silently drops pins with float `x`/`y` or an int `designator`, and silently defaults invalid enums (§6).
3. Symbol read-modify-write drops polygons and polylines because of the point-format mismatch (§8).
4. `step_model.embed:false` writes no model reference, yet reports `step-external`.
5. No upsert: append with an existing name is an error.
6. The file extension is not checked; `write_schlib` will write into a `.PcbLib`.
7. Unicode handling:
   * Names are written as raw UTF-8 into storage names and PATTERN.
   * SchLib parameters put UTF-8 into the plain `Text=` key as well.
8. Non-simple pad stacks lose rectangular and rounded-rectangle shapes on read-back.
9. `diff_libraries` misses geometry and parameter-value changes; `update_component` dry-run lists only description and name.
10. Backups have 1-second granularity (they overwrite each other), at most 5, written beside the library, and are created even when a write fails.
11. Defaults that differ from the schema text:
    * Pads without `shape` become rounded_rectangle with 50 % corners, including THT pads.
    * `corner_radius_percent` greater than 100 becomes 50.
    * The automatic `.Designator` text is added on Top Overlay.
12. The CFB directory tree is degenerate, which breaks recursive readers at about 1000 entries.
13. Embedded STEP bodies are written with `OVERALLHEIGHT=0`, `CHECKSUM=0` and a pad-bounding-box outline; footprint `HEIGHT=0mil`.
14. `validate_library` gives false positives (duplicate designators are allowed in Altium) and misses real problems (hole ≥ pad, holes on single-layer pads).
15. `render_symbol` ignores polygons. Some error texts are misleading ("Missing required parameter: footprints" for a type error).
16. The bundled docs link to `AI_WORKFLOW.md`, `ARCHITECTURE.md` and `CONTRIBUTING.md`, which are not in the bundle.

---

## 14. Integration recommendations for PartForge [UNVERIFIED design advice, based on the verified facts]

* **Process:** run one long-lived server per backend process.
  * Spawning costs only about 35 ms, so a per-job process is fine too.
  * Serialize all mutations per file. The server processes requests sequentially anyway.
* **Config:** generate a per-installation config with `allowed_paths` covering the library root and the STEP model folder.
  STEP files must be inside the sandbox, as must the files themselves.
  Enable `audit_log_path`.
* **Library layout:** many small libraries (per package family, or one footprint per PcbLib) to keep edits under about 1 s.
  Batch all new footprints of a series into a single `write_pcblib` call.
* **Client-side validation layer** (e.g. pydantic) before every call:
  * Integer pin coordinates.
  * String designators.
  * Enum whitelist.
  * ASCII names matching `[A-Za-z0-9_.\- ()+]`, with none of `/\:*?"<>|`.
  * Extension matches the tool; absolute paths only.
  * Coordinates within ±5000 mm.
  * Footprint names exist before linking them.
* **Post-write verification:**
  * Check that `symbol_names`/`footprint_names` and the per-symbol `geometry[].pins` counts match the request.
  * Check the `bodies[].source` values.
  * Check `validation` and `warnings` (`silk_over_pad`).
  * Optionally run `get_component` and compare.
* **Upsert:** `component_exists`, then `update_component` or `write_*(append:true)`.
  For symbols, convert polygon and polyline points to `{x,y}` before writing back.
* **Versioning:** keep PartForge's own snapshots or git history instead of relying on `.bak`. Optionally clean up `.bak` files.
* **3D models:** always `embed:true`. Optionally add an extruded `component_bodies` entry for height checks.
* **Layers:** default to the friendly aliases (Mech 2–7, typed). Offer a configurable mapping to company layers
  (`Mechanical 13`/`15`, …). `batch_update`/`rename_layer` can migrate existing libraries.

---

## 15. To be verified in Altium AD22 by the agent with Altium access

1. **Basic opening and layers.** Do `out/PartForge_Test.PcbLib`, `out/PartForge_Test.SchLib` and the `PartForge_Features.*` files open without errors?
   Are Mech 2/4/6 shown as typed layers (Top Assembly, Top Courtyard, Top 3D Body)?
2. **Embedded STEP.** Is the STEP model of `CAPC2012X125N` shown in 3D? Is a body with `OVERALLHEIGHT=0mil` or `CHECKSUM=0` a problem?
3. **Footprint links.** Do the links (forward-slash absolute `ModelDatafile0`) resolve and preview in the SchLib editor?
4. **Symbol appearance.** Does `LM358DR` show parts A/B/C? Does `NE555DR` show the overbar and dot on RESET?
   In `PartForge_Features.SchLib`, do the GRAPHICS_TEST decorations, frac pin, image and display modes look right?
5. **Unicode.** How do the parameters `±1%` and `10kΩ` (in `RES_0603_10K`) display? How does the footprint name `R_Ω_µ` in `out/errors.PcbLib` display?
6. **Long names and large libraries.** Do names longer than 31 characters display correctly (`out/errors.PcbLib`, `out/errors.SchLib`)?
   Does the 1000-part `out/perf_1000_onecall.PcbLib` open (degenerate CFB tree)?
7. **Pad features.** Are the slot holes, square hole and NPTH correct in `DCJACK_SLOT_TEST`? What does pad 4's top/mid/bottom stack really contain?
   Do the QFN paste windowpanes and the EP paste/mask expansions behave as intended?
8. **Concurrent editing.** Can `write_pcblib` replace a library while it is open in Altium (locks)? Does Altium detect and reload the change?
