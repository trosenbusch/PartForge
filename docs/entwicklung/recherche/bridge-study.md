# altium-mcp bridge study (UNDERSTAND phase, for PartForge)

Subject: `<altium-mcp-checkout>` at commit `f2902b5` (2026-07-30, "Confirm update processes are no-ops on a real database-linked part", origin `github.com/coffeenmusic/altium-mcp`). Working tree: only `server/SandboxScript/Sandbox.pas` is modified, because `run_altium_script` rewrites it on every call. The other agent is using the live MCP server right now: `server/altium_mcp.log` shows `run_altium_script` calls on 2026-10-07.

Method: I read all code in `server/main.py`, `server/AltiumScript/*.pas`, `server/SandboxScript/*` and `dev/*`, plus the on-disk evidence this bridge produced on this PC (log, `C:\Users\Public\altium_mcp\*`). I also ran a few local, Altium-free tests in my scratchpad. I did not run Altium and called no `mcp__altium__*` tools.

Evidence tags used in this report:
- **[V-code]**: I read it in the source. File and line are cited.
- **[V-machine]**: proven by artifacts this bridge produced on this PC with AD22 (`server/altium_mcp.log`, files in `C:\Users\Public\altium_mcp\`).
- **[V-local]**: I ran a local test without Altium.
- **[UNVERIFIED]**: inference, API reference docs (`~/.claude/skills/altium-script/references`), or upstream dev notes I could not re-test. These need one test in Altium.

Supporting files in my folder:
- `research/examples/symbols_example.txt`: examples (a) and (c).
- `research/examples/footprints_example.txt`: examples (b) and (d).
- `research/examples/validate_spec.py`: a Python port of the two DelphiScript batch parsers. It flags every field that would make `StrToInt`/`StrToFloat` raise inside Altium. Run it with `python -I validate_spec.py symbols|footprints <file>`. Both example files pass **[V-local]**.

---

## 0. TL;DR

1. **Transport.** Python writes `C:\Users\Public\altium_mcp\request.json`, deletes `response.json`, then fires `X2.EXE -RScriptingSystem:RunScript(ProjectName="...Altium_API.PrjScr"^|ProcName="Altium_API>Run")` through `cmd.exe` (`shell=True`). It polls every 0.5 s for `response.json`, with a 120 s timeout. On this PC a round trip took 1.5–5.5 s; 15 logged commands had 0 timeouts **[V-machine]**.
2. **The Pascal side has no JSON parser.** It scans the request line by line, so the request must be written with `json.dump(..., indent=2)`. Values lose every `,` and `"`. Arrays end at the first line that contains `]`. `\uXXXX` escapes are never decoded **[V-code]**.
3. **Use the batch commands.** `create_symbols_batch` and `create_footprints_batch` read plain pipe-delimited spec files, so text survives intact; only the spec file path goes through JSON. Footprint batches worked on this AD22 (`{"created": 1, "primitive_errors": 0, "failed": []}`) **[V-machine]**.
4. **Units.** Symbols are in mils, and pin x/y and label x must be integers. Footprint batches are in mils, floats with `.` allowed. Footprint layers are given by name. Pad shape, hole type, pad mode and region kind are raw Altium enum integers **[V-code]**.
5. **Not supported** **[V-code]**:
   - Symbols: designator prefix (hard-coded `'U?'`), Comment, user parameters, footprint model links.
   - Footprints: 3D bodies, mask/paste overrides.
   - Libraries: creating a new `.SchLib`/`.PcbLib`, and saving. The batch commands only add objects to the library open in Altium's memory.
6. **Wrong-library risk.** `LIBRARY|path` / `FPLIB|path` only open a file that already exists. A path that does not exist is ignored silently, and the batch then writes into whatever library is focused **[V-code]**.
7. **Hostile failure mode.** A runtime error (a bad `StrToInt`, a nil access) pauses the script in Altium's debugger. Every later RunScript then silently does nothing until Ctrl+F3 or an Altium restart. Only the sandbox tool detects this; normal commands just time out **[V-code; upstream dev notes]**.
8. **Encoding.** Altium writes responses as cp1252 without BOM: bytes `0xB1` ±, `0xB0` °, `0xB5` µ appear in real dumps **[V-machine]**.
9. **Vendoring is small.** About 2,000 of 7,070 Pascal lines, plus about 40 lines of Python. Change the hard-coded exchange dir (`C:\Users\Public\altium_mcp\`) and the unit/project names, so we never collide with the user's live altium-mcp (the other agent is using it) **[V-code]**.

---

## 1. How `main.py` launches and talks to Altium

### 1.1 Pieces

| Piece | Where | Role |
|---|---|---|
| `AltiumConfig` | `main.py:53-221` | Loads `server/config.json`. Auto-discovers `C:\Program Files\Altium\AD*\X2.EXE` (highest number). Falls back to **tkinter file dialogs** if the exe or script is missing (`verify_paths`, 124-221) |
| `AltiumBridge.execute_command` | `main.py:236-320` | Request/response cycle, serialized by an `asyncio.Lock` |
| `AltiumBridge.run_altium_script` | `main.py:355-386` | Builds the X2 command line and `Popen`s it (never waits) |
| `run_altium_script` MCP tool | `main.py:1101-1211` | Separate sandbox project with wedge detection |
| `Altium_API.pas` `Run` | `Altium_API.pas:1165-1244` | Entry procedure: reads request, dispatches, writes response |

Current `server/config.json` **[V-machine]**:
```json
{
  "altium_exe_path": "C:\\Program Files\\Altium\\AD22\\X2.EXE",
  "script_path": "C:\\PartForge-Examples\\Tools\\altium-mcp\\server\\AltiumScript\\Altium_API.PrjScr"
}
```

### 1.2 Exact command line and RunScript syntax [V-code + V-machine]

`main.py:372-378`:
```python
# Command format: "X2.EXE" -RScriptingSystem:RunScript(ProjectName="path\file.PrjScr"|ProcName="ModuleName>Run")
command = f'"{self.config.altium_exe_path}" -RScriptingSystem:RunScript(ProjectName="{script_path}"^|ProcName="Altium_API>Run")'
...
process = subprocess.Popen(command, shell=True)
# Don't wait for completion - Altium will run the script and generate the response
```

As logged on this PC (`server/altium_mcp.log:134`):
```
"C:\Program Files\Altium\AD22\X2.EXE" -RScriptingSystem:RunScript(ProjectName="<altium-mcp-checkout>\server\AltiumScript\Altium_API.PrjScr"^|ProcName="Altium_API>Run")
```

How the syntax works:
- `ProcName="<UnitName>>Run"`. `<UnitName>` is the `.pas` file name without extension, and `Run` is a parameterless procedure in that unit.
- `^|` is cmd.exe's escape for the pipe, because the command goes through `shell=True`.
- `>` is safe because it sits inside quotes.
- The sandbox uses the same form: `ProjectName="...\SandboxScript\Sandbox.PrjScr"^|ProcName="Sandbox>Run"` (`main.py:1171-1173`).
- **[UNVERIFIED]** Without a shell, you would pass a raw command-line string to `CreateProcess` with a literal `|` and no caret.
- `ScriptingSystem:RunScriptText` also exists in the process catalog (`dev/altium_process_catalog.txt:724`), but its parameters are unknown and untested.

With Altium already running, the second X2.EXE hands the command to the running instance. Responses arrive 1.5–5.5 s later **[V-machine, timings from the log]**:

```
get_pcb_layers 2.0s | get_all_component_data 1.5s/4.5s | create_footprints_batch 2.0s/2.5s
get_footprint_primitives 5.5s/1.5s/4.5s | take_view_screenshot 1.5–2.0s | search_library_symbol 3.0s | get_schematic_data 2.5s
```

### 1.3 request.json: location and format [V-code + V-machine]

- **Location.** Fixed exchange dir `C:\Users\Public\altium_mcp\`. Python: `main.py:45-48` (`EXCHANGE_DIR = Path("C:/Users/Public/altium_mcp")`, created at import). Pascal: `Altium_API.pas:22-33`:
  ```pascal
  procedure InitializeFilePaths();
  begin
      ROOT_DIR := 'C:\Users\Public\altium_mcp\';
      if not DirectoryExists(ROOT_DIR) then
          ForceDirectories(ROOT_DIR);
      REQUEST_FILE := ROOT_DIR + 'request.json';
      RESPONSE_FILE := ROOT_DIR + 'response.json';
  end;
  ```
  (The README's "workspace\request.json" and `tests/test_altium_script.py`'s `C:/AltiumMCP` are outdated.)
- **Writing.** `main.py:244-252` deletes any old response first, then writes the request:
  ```python
  if RESPONSE_FILE.exists():
      RESPONSE_FILE.unlink()
  with open(REQUEST_FILE, "w") as f:
      json.dump({"command": command, **params}, f, indent=2)
  ```
  The file is CRLF, ASCII only, because `json.dump` defaults to `ensure_ascii=True` **[V-machine: request.json bytes `7b 0d 0a 20 20 22 63 6f…`]**.
- **Example** (what `create_symbols_batch` writes):
  ```json
  {
    "command": "create_symbols_batch",
    "spec_file": "C:\\Users\\Public\\altium_mcp\\symbols.txt"
  }
  ```
- **How the Pascal side reads it** (`Altium_API.pas:1191-1213`, `json_utils.pas:14-22`). It is line-based:
  - `CommandType` comes from the line containing `"command":`.
  - Each `Execute*` function then rescans `RequestData` with `Pos('"key"', line) > 0`.
  - A value is everything after the **first** `:` on the line, passed through `TrimJSON`. `TrimJSON` deletes **all** `"` and **all** `,`, then trims.
  - Arrays: the key line is followed by one element per line until the first line containing `]` (for example `Altium_API.pas:233-253`).
  - Consequences **[V-code]**:
    - `indent=2` is mandatory. Compact JSON puts everything on one line and breaks the parser.
    - Values lose commas and quotes.
    - An element containing `]` (such as pin name `D[0]`) ends the array early and is dropped.
    - `\uXXXX` and `\"` are never decoded. Only pins get `'\\'` turned into `'\'` (`Altium_API.pas:246`).
    - Paths keep doubled backslashes (`C:\\Users\\...`). Win32 still resolves them **[V-local: `GetFileAttributesW` on a doubled-backslash path → exists]**.
    - A non-ASCII path (`Widerstände`) arrives as `Widerst\u00e4nde` and breaks **[V-local: json.dump output]**.

### 1.4 response.json: format [V-code + V-machine]

`WriteResponse` (`Altium_API.pas:1116-1162`):
```pascal
if (Pos('ERROR:', Data) = 1) then begin ActualSuccess := False; ActualErrorMsg := Copy(Data, 8, Length(Data)); end
...
AddJSONBoolean(ResultProps, 'success', ActualSuccess);
if ActualSuccess then
    if (Length(Data) > 0) and ((Data[1] = '[') or (Data[1] = '{')) then
        ResultProps.Add(JSONPairStr('result', Data, False))   // raw JSON
    else
        AddJSONProperty(ResultProps, 'result', Data);           // escaped string
else
    AddJSONProperty(ResultProps, 'error', ActualErrorMsg);
ResponseData.Text := BuildJSONObject(ResultProps);
ResponseData.SaveToFile(RESPONSE_FILE);
```

Protocol for command functions: return JSON text starting with `{` or `[`, or `'ERROR: <msg>'`. An empty string means failure: `Run` writes `{"success": false, "error": "Command execution failed"}` and then shows a **modal ShowMessage**.

A real response from this PC **[V-machine, log lines 221-229]**:
```
{
  "success": true,
  "result": {
  "created": 1,
  "primitive_errors": 0,
  "failed": []
}

}
```

Encoding: cp1252 without BOM **[V-machine]**. Real dumps contain single bytes `0xB1` (±), `0xB0` (°), `0xB5` (µ) and `0x99` (™), and are not valid UTF-8. A resistor value appears as `kO`, which is consistent with Ω (absent from cp1252) being best-fit mapped to `O` **[UNVERIFIED]**. Python reads with the locale default (`open(RESPONSE_FILE, "r")`, `main.py:275`), which works only because the locale is cp1252.

Python's "repair" path (`main.py:282-316`): on a parse error it replaces `"[`→`[`, `]"`→`]` and `\"`→`"`, then retries. It can corrupt valid data.

Some functions return their own `{"success": false,...}` as a *result*. For example `CreatePCBFootprint` with no PcbLib produces outer `success: true` with inner `success: false` **[V-code: pcb_utils.pas:1856]**.

### 1.5 Polling and timeouts [V-code]

| Path | Behaviour |
|---|---|
| Normal commands | Poll `RESPONSE_FILE.exists()` every 0.5 s, up to `timeout = 120` s (`main.py:262-270`). On timeout: `{"success": False, "error": "No response received from Altium (timeout)"}` |
| Sandbox tool | Default 120 s (parameter), 0.5 s poll, `_dismiss_altium_dialogs()` after 6 s (`main.py:1175-1180`) |
| Screenshot | Thread join with a 10 s timeout (`main.py:2140`) |

There is no atomic write or completion marker. Python reads as soon as the file exists, so a large response could be read half-written **[V-code; UNVERIFIED that it happens]**.

### 1.6 Detecting a script stuck in the debugger [V-code]

- **Normal bridge commands: no detection.** A wedged executor looks exactly like the 120 s timeout.
- **Sandbox tool only** (`main.py:1182-1211`):
  - `Sandbox.pas` writes a flushed step log (`SandboxLog`) to `C:\Users\Public\altium_mcp\sandbox_log.txt` and the result to `sandbox_result.json`.
  - Result present: success.
  - Log present but no result: `"script started but did not finish"`, `"executor_wedged": True`, plus `last_step_reached`.
  - No log at all: `"script never started"`, meaning a compile error or a previously paused script.
- **Upstream dev notes** (`dev/README.md`; tested by the upstream author, not by me):
  - A runtime error "kills the script and wedges the script executor - every later RunScript silently does nothing until Altium restarts".
  - "Plain try/except does not catch runtime conversion errors".
  - "An undefined constant compiles fine and then kills the script at runtime".
  - Silent debugger pauses produce no dialog; compile errors do.
- **Recovery tools in `dev/`:**
  - `dev/unwedge.py` sends Ctrl+F3 (Stop Debugging) with PowerShell `SendKeys` to the first Altium window whose title contains `.pas` or `.PrjScr`. It "only lands when the script editor tab is the active document".
  - `dev/sandbox_runner.py --auto-restart` runs `taskkill /F /IM X2.EXE` (loses unsaved work), relaunches, and treats Altium as ready when a sandbox ping succeeds (polled up to 180 s).
  - `sandbox_runner.read_dialog_text` reads dialog text through UI Automation to spot "another script is running".

### 1.7 When Altium is not running

- `main.py` never checks for a running process **[V-code]**. It checks only `os.path.exists(exe)` and `os.path.exists(script)`; if either is missing it returns `"Failed to run Altium script"` (`main.py:357-365`).
- Otherwise it `Popen`s X2.EXE, which starts Altium **[UNVERIFIED]**. The script then presumably runs after startup.
- The dev notes say a restart takes about 60–90 s before a ping executes. A cold start, especially with license or startup dialogs, can therefore exceed the 120 s timeout **[UNVERIFIED]**.
- Process check used in dev: `tasklist /FI "IMAGENAME eq X2.EXE"` (`dev/sandbox_runner.py:230-233`) **[V-code]**.

### 1.8 Window and focus handling [V-code]

- **Python, pywin32.** Only `get_screenshot` (`main.py:1997-2132`) uses it:
  - `win32gui.EnumWindows` picks the first visible window whose title contains `"Altium"` and `".PrjPcb"` (fallback: any `"Altium"`).
  - `SetForegroundWindow`, sleep 0.5 s, then a GDI `BitBlt` copy into PIL.
- **Python, ctypes.** `_dismiss_altium_dialogs()` (`main.py:1065-1098`) enumerates **all** top-level windows system-wide. It posts `WM_CLOSE` to every visible `#32770` dialog, and to every `TMessageForm` titled Error/Warning/Information/Confirm. There is no process filter, so it can close other applications' dialogs, including our own pywebview window's dialogs.
- **Pascal side, document focus:**
  - `EnsureDocumentFocused` (`other_utils.pas:113-335`) maps the command to a document kind. Unknown commands default to `'PCB'` (`other_utils.pas:126`). It then calls `Doc.DM_OpenAndFocusDocument` + `Sleep(500)` on the focused project's documents. On failure it shows a **modal ShowMessage**, which blocks until a user clicks.
  - The library commands skip this function (skip list `other_utils.pas:129-138`: `search_library_symbol`, `get_symbol_primitives`, `create_symbols_batch`, `get_footprint_primitives`, `create_footprints_batch`, `create_pcb_footprint`). They focus libraries themselves with `Client.OpenDocument(...)` / `Client.GetDocumentByPath(...)`, then `Client.ShowDocument(ServerDoc)` and `Sleep(500)`. **This switches Altium's active document tab.**
  - Rule from the code comments: an already-open document is only focused, never re-opened, because "re-opening an open document reloads it from disk and silently discards any unsaved changes" (`schematic_utils.pas:980-983`, `pcb_utils.pas:295`).

### 1.9 Locking [V-code]

- `AltiumBridge.__init__` creates `self._command_lock = asyncio.Lock()` (`main.py:232-234`). `execute_command` holds it, so commands are serialized **within one Python process only**.
- `run_altium_script` (sandbox) does **not** take the lock.
- There is no file or cross-process lock. Two server instances share the same exchange dir. This PC has a `request.json` dated 2026-08-31 with no matching entry in `server/altium_mcp.log` **[V-machine]**, which suggests another instance (for example a Claude Desktop DXT install) used the same dir **[UNVERIFIED interpretation]**.

### 1.10 Other config and paths [V-code]

- `server/config.json` is created on first start. `*.json` is gitignored.
- The log goes to `server/altium_mcp.log` at DEBUG level.
- `_resolve_msix_path` (`main.py:322-353`) is Claude-Desktop-MSIX-specific and irrelevant to us.
- `symbol_placement_rules.txt` is AI-prompt text.
- `start_server.py` pins `mcp==1.5.0`. `main.py` imports `win32gui/win32ui/win32con/win32api` and `tkinter` at module load.

---

## 2. Spec formats

### 2.1 Symbols

#### 2.1.1 `create_symbols_batch` spec file (`schematic_utils.pas:806-927`) [V-code]

One record per line, pipe-delimited. The record keyword is `UpperCase(Trim(field0))`.

| Record | Fields | Notes |
|---|---|---|
| `LIBRARY\|<path>` | path (trimmed) | Opens with `Client.OpenDocument('SchLib', path)` or focuses if already open, then `ShowDocument` + `Sleep(500)`. **Only if `FileExists(path)`. Otherwise the line is silently ignored and the symbols go into whatever SchLib is current.** Optional; normally the first line |
| `SYMBOL\|<name>\|<description>\|<part_count>` | name trimmed; description **not** trimmed; part_count `StrToInt` (default 1 if empty) | Starts a new symbol and flushes the previous one |
| `PIN\|...` | `PinsList.Add(Copy(Line, 5, ...))`: the text after the first 4 characters | `PIN\|` must start at column 1 (case-insensitive) |
| `GRAPHIC\|...` | `GraphicsList.Add(Copy(Line, 9, ...))` | `GRAPHIC\|` must start at column 1 |
| anything else | ignored | So `# comment` lines are harmless (unofficial) |

Every symbol is built by `CreateSchematicSymbol` (`schematic_utils.pas:173-598`). It is "created" only if the result contains `"success": true` (`BatchCreateOne`, 794-804). The command returns `{"created": N, "failed": ["name", ...]}` **[V-code]**.

**PIN fields** (after `PIN|`), from `schematic_utils.pas:507-567`:

| idx | field | parse | required |
|---|---|---|---|
| 0 | pin number (designator) | trimmed string | yes |
| 1 | pin name | **not trimmed** (keeps trailing spaces) | yes |
| 2 | electrical type name | see enum below; unknown → `eElectricPassive` | yes |
| 3 | orientation name | `eRotate0/90/180/270`; unknown → `eRotate0` | yes |
| 4 | x (mils) | **`StrToInt`: integer only** | yes |
| 5 | y (mils) | **`StrToInt`: integer only.** If empty, the pin is skipped in the pin pass, **but** the earlier bounding-box pass calls `StrToInt('')` whenever x is present, which raises | yes |
| 6 | owner_part_id | `StrToInt`, default 1; `0` = shared across all parts | no |
| 7 | pin length (mils) | `SafeStrToFloat`; if empty, Altium's default applies (docstring says 300) | no |
| 8 | show name | `'1'` shows; anything else hides | no |
| 9 | show designator (number) | `'1'` shows; anything else hides | no |

- Overbar: a backslash after each overbarred character, e.g. `R\S\T\`. In batch files backslashes are kept literally.
- A `|` cannot appear inside a field.

**GRAPHIC entries** (after `GRAPHIC|`), `schematic_utils.pas:339-505`. Coordinates are in mils and parsed with `SafeStrToFloat`, except where noted.
- `part` = owner part id (`StrToInt`, default 1).
- `width` = `StrToInt` 0..3, meaning eZero/eSmall/eMedium/eLarge (default 1).
- `solid` is `'1'` or other.

| Entry | Field layout |
|---|---|
| line | `line\|part\|width\|x1\|y1\|x2\|y2` |
| polyline | `polyline\|part\|width\|x1\|y1\|x2\|y2\|...` (vertices are read until the first empty field; an odd count drops the last value) |
| polygon | `polygon\|part\|width\|solid\|x1\|y1\|...` |
| rectangle | `rectangle\|part\|width\|solid\|x1\|y1\|x2\|y2` (Location = x1,y1; Corner = x2,y2) |
| arc | `arc\|part\|width\|cx\|cy\|radius\|start_angle\|end_angle` (degrees CCW from 3 o'clock) |
| elliptical_arc | `elliptical_arc\|part\|width\|cx\|cy\|radius\|secondary_radius\|start\|end` |
| ellipse | `ellipse\|part\|width\|solid\|cx\|cy\|radius\|secondary_radius` |
| label | `label\|part\|x\|y\|text`. **Gotcha:** field 2 (x) also goes through the `StrToInt` "width" parse at line 361-363, so **label x must be an integer**. There is no font, size or justification control |

- Unknown graphic types are ignored silently. Beziers, pies and round rectangles can be dumped but not created.
- Polygons and rectangles get fixed colors: `AreaColor := $00B0FFFF` (yellow fill) and `Color := $00FF0000` (blue line).
- If a symbol has **no** GRAPHIC lines, each part gets an auto rectangle from `(MinX, MinY-100)` to `(MaxX, MaxY+100)` over that part's pin Locations. It has `IsSolid` set and `eSmall` lines (`schematic_utils.pas:317-331`).
- Component settings (`schematic_utils.pas:257-264, 334-336`):
  - `CurrentPartID := 1`, `DisplayMode := 0`, `PartCount`.
  - `LibReference := name`, `ComponentDescription := description` (default `'New Component'`).
  - **`Designator.Text := 'U?'` (hard-coded)**, designator located at `(MinX, MaxY+100)` of part 1.
- Registration (`schematic_utils.pas:569-577`):
  ```pascal
  CurrentLib.AddSchComponent(SchComponent);
  SchServer.RobotManager.SendMessage(nil, c_BroadCast, SCHM_PrimitiveRegistration, SchComponent.I_ObjectAddress);
  CurrentLib.CurrentSchComponent := SchComponent;
  CurrentLib.GraphicallyInvalidate;
  ```
  There is no duplicate-name check, no PreProcess/PostProcess (undo), and no save **[V-code]**.

**Enums** (string names in specs; the dumper outputs the ints):
- `TPinElectrical`: `eElectricInput`=0, `eElectricIO`=1, `eElectricOutput`=2, `eElectricOpenCollector`=3, `eElectricPassive`=4, `eElectricHiZ`=5, `eElectricOpenEmitter`=6, `eElectricPower`=7.
- `TRotationBy90`: `eRotate0`=0, `eRotate90`=1, `eRotate180`=2, `eRotate270`=3.
- Values are from the altium-script skill `Constants.md` **[UNVERIFIED in Altium, but consistent with `GetLibrarySymbolReference`'s case tables]**.

**Coordinate and pin-orientation convention** **[UNVERIFIED, needs one test]**:
- Units are mils from the symbol origin, Y up.
- Pin `Location` appears to be the body-side end of the pin, which extends outward by `PinLength` in the orientation direction. The hot spot is `Location + PinLength × dir`. Evidence:
  - The repo's auto-body rectangle spans exactly the min/max pin Locations.
  - The README demo GIF frames show pins outside that auto body.
  - KiCad's Altium importer comments "the location given is not the connection point".
- So a **left-side pin = `eRotate180` at the body's left edge** and a **right-side pin = `eRotate0`**.
- By rotation logic `eRotate90` points up (top-side pin) and `eRotate270` points down. **The `main.py` docstring (line 671) says the opposite: "eRotate90 (down) ... eRotate270 (up)".**
- The user's `1.SchLib` symbol `SK6805-EC1414` (in `temp_symbol_reference.json`) has right-side pins with `eRotate180` and left-side pins with `eRotate0`, which is inverted relative to the convention above. That suggests earlier confusion **[V-machine data; interpretation UNVERIFIED]**.

#### 2.1.2 `create_schematic_symbol` JSON [V-code]

- Tool signature: `create_schematic_symbol(symbol_name, description, pins: list[str], part_count=1, graphics: list[str]=None)` (`main.py:636-728`).
- Pin and graphic strings use the same pipe formats as above.
- Pascal parse: `Altium_API.pas:198-296`. It uses the focused SchLib (`EnsureDocumentFocused` → 'SCHLIB'), with no library path.
- In this JSON path, commas and quotes are stripped from description, pins and graphics. Pins get `\\`→`\`. An element containing `]` ends the array.

### 2.2 Footprints

#### 2.2.1 `create_footprints_batch` spec file (`pcb_utils.pas:21-259`) [V-code]

General rules:
- Coordinates and sizes are mils, parsed with `SafeStrToFloat`. Floats are fine, but the decimal separator must be `.`; the function swaps `.` for the locale separator.
- Angles are degrees CCW.
- Layers are names passed to `String2Layer`.
- Shape, hole type, mode and region kind are `StrToInt` integers.
- Booleans are `'1'` or other.
- Each line runs inside `try ... except` (counts `primitive_errors`, or adds the footprint to `failed`). The dev notes warn that try/except does **not** catch conversion errors, so validate before sending.
- Primitive lines before the first `FOOTPRINT` are ignored. Unknown keywords are ignored.

| Record | Fields (index after the keyword) | Code |
|---|---|---|
| `FPLIB\|<path>` | path (**not trimmed**) | Like LIBRARY: opens or focuses only if `FileExists`, else silently ignored |
| `FOOTPRINT\|name\|description` | name trimmed, description verbatim | `PCBServer.CreatePCBLibComp`; `.Name`, `.Description`; `PcbLib.RegisterComponent(LibComp)`. If no PcbLib is current: `ERROR: No PCB library document is active` |
| `PAD\|name\|x\|y\|rot\|layer\|plated\|hole_size\|hole_type\|hole_width\|hole_rot\|top_x\|top_y\|top_shape[\|corner_pct[\|mode\|mid_x\|mid_y\|mid_shape\|bot_x\|bot_y\|bot_shape]]` | 1 name (not trimmed); 2-3 float; 4 rotation float; 5 layer; 6 plated; 7 float; 8 **int**; 9-12 float; 13 **int**; 14 **int** optional → `StackCRPctOnLayer[eTopLayer]`; 15 mode **int** (empty = Simple); 16-17 float, 18 **int**, 19-20 float, 21 **int** (only read if mode ≠ 0) | Mode is set first; rotation last ("rotates the pad about its location"). `LibComp.AddPCBObject(Pad)` + `PCBM_BoardRegisteration` |
| `TRACK\|x1\|y1\|x2\|y2\|width\|layer` | floats + layer | |
| `ARC\|cx\|cy\|radius\|start_angle\|end_angle\|width\|layer` | floats + layer | Full circle: 0..360 |
| `FILL\|x1\|y1\|x2\|y2\|rotation\|layer` | floats + layer | |
| `VIA\|x\|y\|size\|hole_size\|low_layer\|high_layer` | floats + 2 layers | Implemented but **not documented** in the `main.py` docstring |
| `REGION\|layer\|kind\|x1\|y1\|x2\|y2\|...` | layer, kind **int**, vertex pairs until the first empty field | `PCBContourFactory` + `SetOutlineContour`; no holes, no arcs |
| `TEXT\|x\|y\|size\|width\|rotation\|layer\|mirror\|ttf\|text` | size = height, width = stroke width (floats); mirror/ttf `'1'`; text verbatim with `<NL>` → CRLF | Special strings like `.Designator` work as plain text. No justification, autoposition or font name |

Return value: `{"created": N, "primitive_errors": M, "failed": [footprint names whose FOOTPRINT line threw]}`. `created` counts registered footprints even if some of their primitives failed **[V-code; format V-machine]**.

There is no final `PcbLib.CurrentComponent := ...` or `ViewManager_FullUpdate` in the batch path, unlike `CreatePCBFootprint`, so the view may not refresh **[UNVERIFIED]**. There is no duplicate-name check and no save.

**Enums** (skill `Constants.md`/`PCB_API_Reference.md` **[UNVERIFIED in Altium]**; read back the truth with `get_footprint_primitives`, which prints raw ints):

| Enum | Values | Notes |
|---|---|---|
| `TShape` | `eNoShape`=0, `eRounded`=1, `eRectangular`=2, `eOctagonal`=3, `eCircleShape`=4, `eArcShape`=5, `eTerminator`=6, `eRoundRectShape`=7, `eRotatedRectShape`=8, `eRoundedRectangular`=9 | Use 1 for round/obround, 2 for rectangle, 9 for rounded rectangle + `corner_pct` |
| `THoleType` | `eRoundHole`=0, `eSquareHole`=1, `eSlotHole`=2 | For slots, `hole_size` vs `hole_width` meaning (slot width vs length) is **UNVERIFIED** |
| `TPadMode` | `ePadMode_Simple`=0, `ePadMode_LocalStack`=1 (top/mid/bottom), `ePadMode_ExternalStack`=2 | The batch only sets Top/Mid/Bot sizes, so don't use 2 |
| `TRegionKind` | `eRegionKind_Copper`=0, `_Cutout`=1, `_NamedRegion`=2, `_BoardCutout`=3, `_Cavity`=4 | |

**Layer names.** `String2Layer` inputs proven on this AD22 **[V-machine]**: `GetPCBLayers` printed `layer_id` from `String2Layer('<name>')` into `C:\Users\Public\altium_mcp\temp_layers_data.json`:

| Name | ID |
|---|---|
| `Top Overlay` | 33 |
| `Bottom Overlay` | 34 |
| `Top Paste` | 35 |
| `Bottom Paste` | 36 |
| `Top Solder Mask` | 37 |
| `Bottom Solder Mask` | 38 |
| `Drill Guide` | 55 |
| `Keep Out Layer` | 56 |
| `Drill Drawing` | 73 |
| `Multi Layer` | 74 |

- Not yet proven as input strings: `Top Layer`, `Bottom Layer`, `Mechanical N` **[UNVERIFIED; standard Layer2String names]**. Verify by dumping a footprint with `get_footprint_primitives`; its `layer` field is exactly `Layer2String` output, and the README claims an exact round trip.
- `ILayer.MechanicalLayer(i)` works on this AD22 for i=1..32 (used by `GetPCBLayers`, which produced the dump) **[V-machine]**.
- V6 IDs: Mechanical 1..16 = 57..72. Mechanical 17+ only has V7 IDs (the dump shows 72 for all of them).
- The user's board (HPI_Award) names its mechanical layers **[V-machine]**: M1 Board Shape, M9 Top Assembly, M10 Bottom Assembly, M11 Top Designator, M13 Top 3D Body, M15 **Top Courtyard**, M16 Bottom Courtyard, up to M31. `create_pcb_footprint` also puts the courtyard on Mechanical 15.

#### 2.2.2 `create_pcb_footprint` JSON (`pcb_utils.pas:1828-2036`) [V-code]

- Arguments: `footprint_name`, `description`, `pads: ["num|x_mm|y_mm|w_mm|h_mm|shape", ...]` with shape `Rect` (default) / `Round` / `Oval`, and `courtyard_x_mm`/`courtyard_y_mm` (half sizes; 0 = auto from pads + 0.25 mm).
- It works on the current PcbLib (`GetPcbLibSafe`) with no path, and creates SMD pads on Top Layer only.
- Courtyard: 4 tracks on `ILayer.MechanicalLayer(15)`, 0.1 mm wide.
- Silkscreen: a rectangle inset 0.1 mm from the courtyard on Top Overlay, with a 0.5 mm gap at the top-left for pin 1.
- **Bugs:**
  - `description` is never assigned. Only `LibComp.Name := FootprintName` at line 1869.
  - `'Oval'` maps to `eRoundedRectangle` (line 1906). In the constant list that is 3, which as a `TShape` value is `eOctagonal`, so oval pads probably become octagonal **[UNVERIFIED]**.
- Not available: through-hole pads, assembly outline, text, paste/mask control.

### 2.3 Complete minimal examples

All batch examples below are in `research/examples/` and pass the parser port **[V-local]**. They have **not** been run in Altium. Layer choices follow the user's board scheme (M9 assembly, M15 courtyard). Land-pattern numbers are illustrative only (0603 values match KiCad's `R_0603_1608Metric`); PartForge must compute real IPC-7351B values. Conversion: mils = mm / 0.0254.

**(a) 2-pin resistor symbol** (`symbols_example.txt`, first block):
```
LIBRARY|C:\PartForge\Libraries\PF_Passives.SchLib
SYMBOL|PF_RES|Resistor, generic 2-pin (IEC body)|1
PIN|1|1|eElectricPassive|eRotate180|-100|0|1|100|0|0
PIN|2|2|eElectricPassive|eRotate0|100|0|1|100|0|0
GRAPHIC|rectangle|1|1|0|-100|-40|100|40
```
- Hot spots should land at (−200,0) and (200,0), given the convention in 2.1.1.
- Names and numbers are hidden.
- The designator will be `U?` (gap).
- The same via JSON (`create_schematic_symbol`; commas in the description would be stripped):
  ```json
  {
    "command": "create_schematic_symbol",
    "symbol_name": "PF_RES",
    "description": "Resistor generic 2-pin",
    "part_count": 1,
    "pins": [
      "1|1|eElectricPassive|eRotate180|-100|0|1|100|0|0",
      "2|2|eElectricPassive|eRotate0|100|0|1|100|0|0"
    ],
    "graphics": [
      "rectangle|1|1|0|-100|-40|100|40"
    ]
  }
  ```

**(c) 8-pin IC box symbol** (`symbols_example.txt`, second block):
```
SYMBOL|PF_DEMO_IC8|Demo 8-pin IC, box symbol|1
PIN|1|VIN|eElectricPower|eRotate180|0|0|1|200|1|1
PIN|2|EN|eElectricInput|eRotate180|0|-100|1|200|1|1
PIN|3|R\S\T\|eElectricInput|eRotate180|0|-200|1|200|1|1
PIN|4|GND|eElectricPower|eRotate180|0|-300|1|200|1|1
PIN|5|NC|eElectricPassive|eRotate0|800|-300|1|200|1|1
PIN|6|SDA|eElectricIO|eRotate0|800|-200|1|200|1|1
PIN|7|SCL|eElectricInput|eRotate0|800|-100|1|200|1|1
PIN|8|VOUT|eElectricOutput|eRotate0|800|0|1|200|1|1
GRAPHIC|rectangle|1|1|1|0|-400|800|100
```
Omitting the GRAPHIC line produces the same auto body, (0,−400)–(800,100) solid **[V-code]**. In the JSON path, overbar names must be written `"3|R\\S\\T\\|..."`.

**(b) 0603 chip footprint** with silkscreen, assembly outline, courtyard and designator (`footprints_example.txt`, first block):
```
FPLIB|C:\PartForge\Libraries\PF_Passives.PcbLib
FOOTPRINT|PF_RESC1608X55N|Chip resistor 0603 (1608 metric), illustrative land pattern
PAD|1|-32.4803|0|0|Top Layer|1|0|0|0|0|31.4961|37.4016|9|25
PAD|2|32.4803|0|0|Top Layer|1|0|0|0|0|31.4961|37.4016|9|25
TRACK|-9.3409|20.5709|9.3409|20.5709|4.7244|Top Overlay
TRACK|-9.3409|-20.5709|9.3409|-20.5709|4.7244|Top Overlay
TRACK|-31.4961|-15.7480|31.4961|-15.7480|3.9370|Mechanical 9
TRACK|31.4961|-15.7480|31.4961|15.7480|3.9370|Mechanical 9
TRACK|31.4961|15.7480|-31.4961|15.7480|3.9370|Mechanical 9
TRACK|-31.4961|15.7480|-31.4961|-15.7480|3.9370|Mechanical 9
TRACK|-58.2677|-28.7402|58.2677|-28.7402|1.9685|Mechanical 15
TRACK|58.2677|-28.7402|58.2677|28.7402|1.9685|Mechanical 15
TRACK|58.2677|28.7402|-58.2677|28.7402|1.9685|Mechanical 15
TRACK|-58.2677|28.7402|-58.2677|-28.7402|1.9685|Mechanical 15
TEXT|-15.7480|-7.8740|15.7480|1.9685|0|Mechanical 9|0|0|.Designator
```
- Pads: 0.80×0.95 mm at ±0.825 mm, rounded rectangle (shape 9) with 25 % corners, SMD (hole 0).
- Silkscreen: 0.12 mm lines.
- Assembly body 1.6×0.8 mm on M9.
- Courtyard ±1.48×±0.73 mm on M15, 0.05 mm lines.
- The JSON alternative (no assembly outline possible, description ignored, shape `Rect`):
  ```json
  {
    "command": "create_pcb_footprint",
    "footprint_name": "PF_RESC1608X55N",
    "description": "ignored by the script",
    "pads": ["1|-0.825|0|0.8|0.95|Rect", "2|0.825|0|0.8|0.95|Rect"],
    "courtyard_x_mm": 1.48,
    "courtyard_y_mm": 0.73
  }
  ```
  `main.py` writes the `pads` list one element per line because of `indent=2`.

**(d) Through-hole footprint** (`footprints_example.txt`, second block). Two-pin header, 2.54 mm pitch, 1.0 mm drill, 1.7 mm pads, square pin 1:
```
FPLIB|C:\PartForge\Libraries\PF_Connectors.PcbLib
FOOTPRINT|PF_HDR_1X02_P2.54|Pin header 1x02, pitch 2.54 mm, drill 1.0 mm
PAD|1|0|0|0|Multi Layer|1|39.3701|0|0|0|66.9291|66.9291|2
PAD|2|100|0|0|Multi Layer|1|39.3701|0|0|0|66.9291|66.9291|1
TRACK|-55|-55|155|-55|5.9055|Top Overlay
TRACK|155|-55|155|55|5.9055|Top Overlay
TRACK|155|55|-55|55|5.9055|Top Overlay
TRACK|-55|55|-55|-55|5.9055|Top Overlay
ARC|-75|0|5|0|360|5.9055|Top Overlay
TRACK|-50|-50|150|-50|3.9370|Mechanical 9
TRACK|150|-50|150|50|3.9370|Mechanical 9
TRACK|150|50|-50|50|3.9370|Mechanical 9
TRACK|-50|50|-50|-50|3.9370|Mechanical 9
TRACK|-70|-70|170|-70|1.9685|Mechanical 15
TRACK|170|-70|170|70|1.9685|Mechanical 15
TRACK|170|70|-70|70|1.9685|Mechanical 15
TRACK|-70|70|-70|-70|1.9685|Mechanical 15
TEXT|-20|-10|30|3|0|Mechanical 9|0|0|.Designator
```

Optional record syntax (parser-valid, unproven in Altium):
- Local-stack pad: `PAD|1|0|0|0|Multi Layer|1|39.3701|0|0|0|66.9291|66.9291|2||1|59.0551|59.0551|1|66.9291|66.9291|2`.
- Slotted pad: `PAD|3|200|0|0|Multi Layer|1|39.3701|2|78.7402|0|66.9291|106.2992|1`.

Use one `FPLIB` per file, or at least make sure every path exists. Otherwise later footprints land in the previously focused library.

### 2.4 Read-back tools (for verification and import) [V-code]

- `get_symbol_primitives(library_path, symbol_name)` and `get_footprint_primitives(library_path, footprint_name)`. They take an empty name for an inventory, `*` for all items, or a name for one item. Output is in mils.
- The footprint dump uses the same field names and raw ints as the batch spec.
- The symbol dump gives electrical and orientation as **ints**; map them to names before feeding them back.
- 3D bodies, parameters and implementations are excluded from dumps.
- Inventory output on this PC (`HPI_Award.PcbLib`, footprint `LED_SK6812HV-4P_5050`, `pads: 4, tracks: 4, arcs: 1`) **[V-machine]**. Its description contains commas and parentheses, consistent with the batch path preserving text.

---

## 3. Feature support in the DelphiScript code

| Feature | Supported? | Evidence / how |
|---|---|---|
| Component Description | **Yes** for symbols (`ComponentDescription`), both paths; **yes** for footprints in the batch (`LibComp.Description`); **no** in `create_pcb_footprint` (bug) | [V-code] schematic_utils.pas:263, pcb_utils.pas:112, 1869 |
| Designator prefix | **No.** Hard-coded `SchComponent.Designator.Text := 'U?'` | [V-code] schematic_utils.pas:264. One-line patch, e.g. an optional 5th `SYMBOL` field |
| Comment | **No** in library creation. The dev placement script sets `Obj3.Comment.Text := ...` on sheet components | [V-code] dev/place_part_from_spec.pas:91-95 (tested on sheets per upstream; [UNVERIFIED] for SchLib) |
| User parameters | **No** in library creation. Dev pattern (sheet components): `SchServer.SchObjectFactory(eParameter, eCreate_Default)`; `.Name`, `.Text`, `.ParamType := eParameterType_String`, `.ReadOnlyState := eReadOnly_None`, `.IsHidden := True`; `Comp.AddSchObject(p)`; `RobotManager.SendMessage(Comp.I_ObjectAddress, c_BroadCast, SCHM_PrimitiveRegistration, p.I_ObjectAddress)` | [V-code] dev/place_part_from_spec.pas:144-152; [UNVERIFIED] in SchLib |
| Footprint model link on a symbol | **No.** Dev pattern (sheet components): `Impl := Comp.AddSchImplementation; Impl.ModelName := '<fp>'; Impl.ModelType := 'PCBLIB'; Impl.IsCurrent := True; Impl.UseComponentLibrary := True;`. `DBLIB_FINDINGS.md` adds `ClearAllDatafileLinks`; a GUI-placed reference had 1 datafile link (`ISch_Implementation.AddDataFileLink(EntityName, Location, FileKind)`) | [V-code] dev/place_part_from_spec.pas:101-111; [UNVERIFIED] in SchLib. For a DbLib, footprint/symbol refs come from DB columns mapped to `[Footprint Ref]`/`[Library Ref]` (upstream DBLIB_FINDINGS on a production DbLib), so SchLib links are optional |
| 3D bodies (extruded / STEP) | **No.** No BODY record; dumps skip `eComponentBodyObject` | [V-code] pcb_utils.pas:495-498. Candidate API [UNVERIFIED]: `PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default)`; `Body.ModelFactory_FromFilename(stepPath, False)` → `IPCB_Model`; `Body.SetState_FromModel`; `Model.SetState(RotX,RotY,RotZ,Dz)`; or `ModelFactory_CreateExtruded(MinZ, MaxZ, Color)` + `SetOutlineContour`; also `LoadGenericModelFromFile(path, embed)`; `e3DModelType_Extruded`=0, `_Generic`=1. `LibComp.Height` is never set |
| Pad mask/paste overrides, thermal, testpoint | **No** | Candidate: `Pad.Cache` / `SetState_Cache` with `eCacheManual` [UNVERIFIED] |
| Create a NEW .SchLib/.PcbLib at a path | **No.** `LIBRARY\|`/`FPLIB\|` require `FileExists`; everything else targets the focused document | [V-code] schematic_utils.pas:859, pcb_utils.pas:81. Options [UNVERIFIED]: copy a template empty library file from Python, then `LIBRARY\|path` (most robust; a fresh Altium library probably contains a default `Component_1`/`PCBCOMPONENT_1`); or `CreateNewDocumentFromDocumentKind('SCHLIB'/'PCBLIB')` + `IServerDocument.DoSafeChangeFileNameAndSave(path, kind)`; `IPCB_Library.SaveEmptyLibrary(FileName)`; `PCBServer.CreatePCBLibrary` |
| Saving libraries | **No save anywhere** in the bridge (grep for Save/DoFileSave: only JSON temp files). Objects live in Altium memory until the user saves; re-opening the document discards them | [V-code]. Candidates [UNVERIFIED]: `ServerDoc.DoFileSave(kind)` / `DoSafeFileSave(kind)`; `RunProcess('WorkspaceManager:SaveObject')` with `ObjectKind=FocusedDocument`, `SaveMode=Standard`; `ISch_Lib.SaveToFile(path)`; `IPCB_Library.SaveComponentWithLibrary(name, file)` |
| Upsert / duplicate handling | **No** | Candidates [UNVERIFIED]: `ISch_Lib.GetState_SchComponentByLibRef`, `RemoveSchComponent`; `IPCB_Library.GetComponentByName`, `RemoveComponent`, `GetUniqueCompName` |
| Undo grouping | **No** PreProcess/PostProcess in the library paths | [V-code] |

---

## 4. Driving the bridge from our own Python app (without the MCP server)

### 4.1 Minimal Pascal set to vendor (about 2,000 of 7,070 lines: schematic ≈ 970, pcb ≈ 540, json 173, Altium_API ≈ 340, other ≈ 26) [V-code]

| File | Keep | Drop |
|---|---|---|
| `Altium_API.pas` | `REPLACEALL` const (used by every unit), globals (`RequestData`, `ResponseData`, `REQUEST_FILE`, `RESPONSE_FILE`, `ROOT_DIR`), `InitializeFilePaths`, `ExecuteCreateSymbolsBatch` (558-582), `ExecuteCreateFootprintsBatch` (533-555), `ExecuteGetSymbolPrimitives` (585-617), `ExecuteGetFootprintPrimitives` (503-530), `WriteResponse` (1116-1162), `Run` (1165-1244), a trimmed `ExecuteCommand` | `Params`/`ExtractParameter` (populated, never used), all PCB-design commands |
| `json_utils.pas` | All 173 lines (`TrimJSON`, `JSONEscapeString`, `JSONPairStr`, `BuildJSONObject`, `BuildJSONArray`, `WriteJSONToFile`, `SafeStrToFloat`, `AddJSON*`) | |
| `other_utils.pas` | `GetFieldFromPipeString` (87-109) | `EnsureDocumentFocused` (drop the call, or keep its skip list; it needs `GetBoardSafe`/`GetPcbLibSafe`/`GetOpenOutputJob`), `ScriptProjectPath` (unused), OutJob and screenshot code |
| `schematic_utils.pas` | `StrToPinElectricalType`, `StrToPinOrientation`, `CreateSchematicSymbol` (173-598), `BatchCreateOne`, `CreateSymbolsBatch` (794-927), `AddVerticesProperty`, `GetSymbolPrimitives` (929-1300); optionally `SearchLibrarySymbol` | `GetSchematicData`, `GetLibrarySymbolReference` (optional) |
| `pcb_utils.pas` | `GetPcbLibSafe` (14-19), `CreateFootprintsBatch` (21-259), `GetFootprintPrimitives` (261-558) | Everything else |
| `.PrjScr` | A minimal project like `server/SandboxScript/Sandbox.PrjScr` (31 lines) with one `[DocumentN] DocumentPath=<unit>.pas` per unit | `pcb_layout_duplicator.pas` |

- All units in one `.PrjScr` share global scope; there are no `uses` clauses. `Altium_API.pas` calls `TrimJSON` and `GetFieldFromPipeString` from the other units directly **[V-code]**.
- Rename the units (for example `PartForgeBridge.pas` with `procedure Run`) and launch with `ProcName="PartForgeBridge>Run"`.
- License: MIT, `LICENSE` reads "Copyright (c) 2025 Siddharth Ahuja" (template copied from blender-mcp; actual authors are coffeenmusic and contributors). Keep the notice in the vendored files.

### 4.2 Launcher logic (minimal Python equivalent of `main.py`)

The launch, request, poll and decode parts are taken from `main.py` **[V-code]**. `CREATE_NO_WINDOW` and the half-written-file guard are my additions **[UNVERIFIED]**.
```python
import json, subprocess, time
from pathlib import Path

EXCHANGE = Path(r"C:\Users\Public\partforge_bridge")   # own dir - never C:\Users\Public\altium_mcp
REQ, RESP = EXCHANGE / "request.json", EXCHANGE / "response.json"
X2 = r"C:\Program Files\Altium\AD22\X2.EXE"
PRJ = r"C:\...\bridge\PartForgeBridge.PrjScr"
UNIT = "PartForgeBridge"                                # unit file holding `procedure Run;`

def call(command: str, timeout: float = 120.0, **params) -> dict:
    EXCHANGE.mkdir(parents=True, exist_ok=True)
    RESP.unlink(missing_ok=True)
    # Pascal parser is LINE-BASED: indent=2 mandatory; keep values ASCII, no ',' '"' ']' in values
    REQ.write_text(json.dumps({"command": command, **params}, indent=2), encoding="ascii")
    cmd = f'"{X2}" -RScriptingSystem:RunScript(ProjectName="{PRJ}"^|ProcName="{UNIT}>Run")'
    subprocess.Popen(cmd, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if RESP.exists():
            time.sleep(0.2)                      # crude guard against a half-written file
            return json.loads(RESP.read_text(encoding="cp1252"))   # Altium writes ANSI/cp1252
        time.sleep(0.5)
    raise TimeoutError("no response: Altium not running/busy, modal dialog open, or script wedged")
```

Recommended additions, modelled on `Sandbox.pas` **[design V-code; untested here]**:
- Have `Run` write a `started` marker first, and write the response to `response.tmp` then `RenameFile` it. Python can then tell "never started" (Altium down, wedged, or compile error) from "started but died", and never reads a partial file.
- Check `tasklist /FI "IMAGENAME eq X2.EXE"` before calling.
- Write spec files to an ASCII-only path without commas.

### 4.3 Hard-coded paths and config to change [V-code]

| Item | Locations |
|---|---|
| Exchange dir | `C:\Users\Public\altium_mcp\`: `Altium_API.pas:24` (`ROOT_DIR`), `main.py:45`, `SandboxScript/Sandbox.pas` (LogPath/OutPath), `dev/sandbox/Sandbox.pas:43-44`, `dev/sandbox_runner.py:40`, `dev/make_part_spec.py:17`, `dev/place_part_from_spec.pas:12` |
| Project / unit names | `constScriptProjectName = 'Altium_API'` (`Altium_API.pas:6`, only used by the unused `ScriptProjectPath`) and `ProcName="Altium_API>Run"` (`main.py:373`). Rename both, since `other_utils.pas:24-26` mentions "stale copies cached by Altium" of same-named script projects |
| Exe discovery | `C:\Program Files\Altium\AD*\X2.EXE` (`main.py:79-102`); tkinter prompt fallback (blocking; replace with our GUI) |
| `config.json` | `server/config.json` beside `main.py`: `{"altium_exe_path", "script_path"}` |
| Temp outputs | `ROOT_DIR + 'temp_*.json'` (`WriteJSONToFile`). Some calls add an extra `'\'`; harmless |

### 4.4 Adding our own commands [V-code for the mechanics; sketch UNVERIFIED]

Steps:
1. Write `function MyCmd(...): String;` that returns JSON text starting with `{`, or `'ERROR: ...'`. Never return `''` (it triggers a modal `ShowMessage`), and never call `ShowMessage` yourself.
2. Add a parser `ExecuteMyCmd(RequestData)` following the `ExecuteCreateSymbolsBatch` pattern: `Pos('"key"', line)`, `Copy` after `:`, then `TrimJSON`.
3. Add `'my_cmd': Result := ExecuteMyCmd(RequestData);` to the `case` in `ExecuteCommand`.
4. **Add the name to the `EnsureDocumentFocused` skip list, or drop that call.** Unknown commands default to `'PCB'` and may pop a modal "No PCB document found" (`other_utils.pas:126, 325-332`).
5. Add the unit to the `.PrjScr`.
6. Keep helpers parameterised, since only parameterless procedures show up in Altium's Run Script dialog.

Sketch for a "build a whole SchLib from a spec file and save it" command. The spec is the same format, minus the `LIBRARY` line. Nil checks are split into separate `if`s because short-circuit evaluation in DelphiScript is **UNVERIFIED**:
```pascal
function BuildSchLib(SpecFile, LibPath: String; DoSave: Boolean): String;
var
    ServerDoc  : IServerDocument;
    CurrentLib : ISch_Lib;
    R          : String;
begin
    Result := '';
    if not FileExists(LibPath) then begin Result := 'ERROR: library file does not exist: ' + LibPath; Exit; end;
    if Client.IsDocumentOpen(LibPath) then ServerDoc := Client.GetDocumentByPath(LibPath)
    else ServerDoc := Client.OpenDocument('SchLib', LibPath);
    if ServerDoc = nil then begin Result := 'ERROR: cannot open ' + LibPath; Exit; end;
    Client.ShowDocument(ServerDoc);
    Sleep(500);
    if SchServer = nil then begin Result := 'ERROR: SCH server not available'; Exit; end;
    CurrentLib := SchServer.GetCurrentSchDocument;
    if CurrentLib = nil then begin Result := 'ERROR: no current SCH document'; Exit; end;
    if CurrentLib.ObjectID <> eSchLib then begin Result := 'ERROR: focused document is not a SchLib'; Exit; end;
    // guard against writing into the wrong library (DocumentName assumed to be the full path - UNVERIFIED)
    if UpperCase(CurrentLib.DocumentName) <> UpperCase(LibPath) then
    begin Result := 'ERROR: focus mismatch: ' + CurrentLib.DocumentName; Exit; end;
    R := CreateSymbolsBatch(SpecFile);
    if Pos('ERROR:', R) = 1 then begin Result := R; Exit; end;
    if DoSave then
        if not ServerDoc.DoFileSave('SCHLIB') then begin Result := 'ERROR: save failed'; Exit; end;   // UNVERIFIED API/kind
    Result := R;
end;
```
The PcbLib variant uses `GetPcbLibSafe(0)` and compares `PcbLib.Board.FileName` with the path; `CreateFootprintsBatch(SpecFile)`; `DoFileSave('PCBLIB')` **[UNVERIFIED]**. Prototype the save, new-document and 3D-body calls in the sandbox before relying on them.

---

## 5. Gaps and risks (most severe first)

1. **Wedged executor.** Any runtime error inside Altium (bad number, nil access, undefined constant) pauses the script in the debugger and blocks all later runs. The normal bridge only sees a 120 s timeout. Recovery is Ctrl+F3 with the script editor tab focused, or killing Altium (unsaved work lost).
   - Known nil hazard: `CreateSchematicSymbol` does `CurrentLib := SchServer.GetCurrentSchDocument; if (CurrentLib.ObjectID <> eSchLib)` with no nil check (`schematic_utils.pas:207-208`). Running a symbol batch while no SCH document is current will wedge.
   - Mitigation: validate every spec with the parser port; always focus and verify the target library first.
2. **Writes into the wrong library.** A missing `LIBRARY`/`FPLIB` file is silently skipped, and objects go into whatever library is current. `dev/README.md` records that this once put stray components into three shared libraries. Our own command must verify the target path and abort on a mismatch.
3. **No save and no new-library creation.** Results exist only in Altium memory. A crash, a careless close, or re-opening the same document loses them. PartForge needs an explicit save step and a library-file creation step (template copy recommended); both are unproven.
4. **Shared exchange dir and concurrency.** `C:\Users\Public\altium_mcp` is shared by every altium-mcp instance (the other agent is using it now). There is no cross-process lock, and `run_altium_script` ignores even the in-process lock. PartForge must use its own exchange dir, its own project and unit names, and a process-wide queue.
5. **Modal dialogs.** `ShowMessage` is called in several error paths: missing request file, unknown command, empty result, focus failures. It blocks until a human clicks. `_dismiss_altium_dialogs` closes **every** `#32770` dialog on the desktop, including other apps' dialogs.
6. **Lossy JSON hand-off.**
   - Commas, quotes, `]`, non-ASCII and `\u` escapes break the JSON path.
   - Spec-file paths must avoid commas and non-ASCII characters.
   - **Encoding:** responses are cp1252 (verified), so Ω is lost. Spec-file encoding is unproven: `TStringList.LoadFromFile` probably assumes ANSI without a BOM. Safest is ASCII names and descriptions in bridge specs; keep rich text in the database.
7. **Functional gaps for a production library:**
   - Symbols: designator prefix fixed to `U?`; no Comment, parameters, model links, duplicate handling, undo, label fonts or text justification.
   - Footprints: no 3D bodies or `Height`; no mask/paste overrides.
   - `create_pcb_footprint`: drops the description, likely maps `Oval` to octagonal, is SMD-only, and draws a silk box about 0.15 mm from the pads.
8. **Semantics to verify before generating geometry** (each needs one test by the agent with Altium access):
   - Pin `Location`/orientation convention; the docstring contradicts the code for `eRotate90`/`eRotate270`.
   - `String2Layer` inputs `Top Layer`, `Bottom Layer`, `Mechanical N`.
   - Slot `HoleSize` vs `HoleWidth`.
   - Text anchor point.
   - Whether try/except in `CreateFootprintsBatch` actually catches bad numbers.
9. **Altium availability and UX.**
   - No running-check; a cold start can exceed 120 s.
   - The script runs on Altium's UI thread, so Altium freezes during big batches.
   - `ShowDocument` switches the user's active tab.
   - Per-symbol `GraphicallyInvalidate` may slow very large batches (README claims a 514-symbol round trip works, duration unknown). Make the timeout configurable and chunk batches.
10. **Response race and fragile repair.** There is no atomic write, and the Python "fix JSON" heuristics can corrupt data.
11. **Locale.** `SafeStrToFloat` only works if numbers use `.`. Integer fields (pin x/y, label x, shapes, hole type, mode, kind, part ids) must be plain integers; `1.0` raises.
12. **Mechanical layers 17-32.** They have no V6 IDs (the dump shows 72 for all of them). `String2Layer` and `Layer2String` may not round-trip them. `ILayer.MechanicalLayer(i)` works (verified).

### Architectural note for PartForge (derived; not about this code)

In a DbLib, a whole resistor series shares one symbol and a handful of footprints. Per-part data (value, MPN, parameters, `[Library Ref]`, `[Footprint Ref]`) lives in database rows, as the upstream `DBLIB_FINDINGS.md` shows on a production DbLib. So series generation is pure database work. The bridge is only needed for the occasional new symbol or footprint, plus read-back and verification. That keeps exposure to the risks above small.
