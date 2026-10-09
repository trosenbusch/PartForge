# Altium live research for PartForge (UNDERSTAND phase)

Agent: altium-live research agent · Date: 2026-10-07 · Working folder:
`C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/altium-live/`

Every claim is tagged **VERIFIED** (I ran or read it) or **UNVERIFIED** (inference, untested, or a ready-made script that was never run).

---

## 0. Status: read this first

1. **The Altium script executor is wedged (VERIFIED).** My 8th sandbox run paused in the DelphiScript debugger at
   `Sandbox.pas` line 85: `ResultText := ResultText + IntToStr(Ord(Obj3.Text[I3])) + ' ';`.
   The cause is indexing a *property of an interface variable* (`Obj3.Text[I3]`). The `run_altium_script` tool reported
   `executor_wedged: true` and dismissed one dialog. The Altium main window title stayed
   `Sandbox.PrjScr - Altium Designer (26.10.1)`, and no result file appeared within 90 s or on re-checks at 21:27.
   Following the ground rules, **I stopped using Altium after that.** **The user has to press Ctrl+F3 in Altium** (stop the paused script).
2. **State left behind (VERIFIED):** `…\scratchpad\altium-live\PF_Test_abs.DbLib` is **still installed** in Altium's
   Installed Libraries, because the failed run never reached its `UninstallLibrary`. After Ctrl+F3, run
   `followup/00_cleanup_uninstall.txt` through `run_altium_script`, or remove the library by hand in the Components panel under File-based Libraries Preferences → Installed.
   Nothing else was left behind: the SchLib and PcbLib I created were saved and closed, the Free Documents project shows 0 documents, and no user
   document or project was touched. One `ISch_Component` object from `LoadComponentFromDatabaseLibrary` was never freed. It belongs to no document and does no harm.
3. **The installed Altium is NOT AD22 (VERIFIED).** `C:\Program Files\Altium\AD22\X2.EXE` has FileVersion
   **26.10.1.5**, `Client.GetProductVersion` returns `26.10.1.5`, and the window title says `Altium Designer (26.10.1)`. Only the folder name says AD22.

What was completed: goal A core (DbLib through SQLite ODBC installs, tables and views listed, fields and mapping read, record → symbol
resolution with a relative path), goal B in full (SchLib and PcbLib creation including the 3D body, saved, verified at file level), and goal C
partially (latency taken from logs, per-step timings). Still open: Unicode *inside* Altium, VARCHAR-table lookups, relative DB path,
footprint-path resolution, placing on a schematic, and the 50-footprint timing. Ready-to-run scripts for these are in `altium-live/followup/` (section 7).

---

## 1. Environment (all VERIFIED)

| Item | Value |
|---|---|
| Altium | `C:\Program Files\Altium\AD22\X2.EXE`, version 26.10.1.5, process started 07.10.2026 11:18 |
| Altium CWD (`GetCurrentDir` in script) | `C:\Program Files\Altium\AD22` (relevant for relative ODBC paths) |
| `SpecialFolder_MyDesigns` | `C:\Users\Example\Documents\My Designs` |
| PCBServer / SchServer | both running |
| Open projects at start | Free Documents (0 docs), two user `.PrjPcb` projects, `altium-mcp\server\SandboxScript\Sandbox.PrjScr` |
| Installed libraries at start | 20 (IntLibs); available 23 |
| ODBC driver | "SQLite3 ODBC Driver", 64-bit, `C:\WINDOWS\system32\sqlite3odbc.dll`, Christian Werner, FileVersion 0.99991, embeds SQLite **3.43.2** |
| Other 64-bit ODBC drivers present | SQL Server (several), PostgreSQL ANSI/Unicode(x64), MS Access, Excel, Text, dBASE |
| Python | `C:\Python313\python.exe` 3.13.5, `sqlite3` module = SQLite 3.49.1 (newer than the driver's 3.43.2, so avoid newer SQL features in the DB file) |
| Document kinds (`Client.GetDocumentKindFromDocumentPath`) | `.SchLib`→`SCHLIB`, `.PcbLib`→`PCBLIB`, `.DbLib`→`DATABASELIB`, `.SchDoc`→`SCH`, `.DbLink`→`DATABASELINK`, `.IntLib`→`IntLibrary` |

How the altium-mcp sandbox works (VERIFIED by reading `C:\PartForge-Examples\Tools\altium-mcp\server\main.py`): the tool splices the body into
`SandboxScript\Sandbox.pas` between `// === BEGIN EXPERIMENT` and `// === END EXPERIMENT`. It then launches
`"X2.EXE" -RScriptingSystem:RunScript(ProjectName="…\Sandbox.PrjScr"^|ProcName="Sandbox>Run")` through `cmd` and polls
`C:\Users\Public\altium_mcp\sandbox_result.json` every 0.5 s. After 6 s it starts closing `#32770` and `TMessageForm` dialogs. Only the scratch variables
`S1..S3, I1..I3, B1, Obj1..Obj5 (IDispatch), List1, IntMan, DbDoc, ResultText` are available.

---

## 2. Goal A: SQLite as a DbLib source through MSDASQL and the SQLite3 ODBC Driver

### 2.1 Test database (VERIFIED, built by `altium-live/tools/build_db.py`)

File: `altium-live/partforge_test.db`.
- `Resistors`: all 14 columns are `TEXT` (`[Part Number] TEXT PRIMARY KEY, [Library Ref], [Library Path], [Footprint Ref], [Footprint Path], Value, Description, Comment, Manufacturer, [Manufacturer Part Number], Tolerance, Power, Package, Datasheet`). It has 7 rows covering the path variants:
  RES-0001 `libs\PF_Test.SchLib` (relative to the DbLib) · RES-0002 absolute path · RES-0003 bare file name `PF_Test.SchLib` · RES-0004 empty
  path · RES-0005 `libs/PF_Test.SchLib` (forward slash) · RES-0006 has a 284-character Description · RES-0007 has a symbol name and footprint name that do not exist.
  Unicode values include `10 kΩ` (U+03A9), `±1 %`, `4.7 MΩ`, `−55 °C … +155 °C`, `äöüß €` and `µ`.
- `Capacitors`: the same 14 columns declared as `VARCHAR(255)`. Rows CAP-0001..0003 contain `4.7 µF` (U+00B5), `±10 %`, and one 284-character Description.
- `Inductors`: typed columns: `[Part Number] VARCHAR(64) PK`, `[Inductance_uH] REAL`, `[Current_mA] INTEGER`, `[Isat_A] NUMERIC`, and one column `[Untyped]` with no declared type.
- Views: `Resistors_0603` (`SELECT * FROM [Resistors] WHERE [Package]='0603'`) and `AllPassives` (`UNION ALL` of Resistors and Capacitors, including an expression column
  `[Value] || ' ' || [Tolerance] AS [Short Text]` and a constant column `'R' AS [Kind]`).

### 2.2 The same ADO chain outside Altium (VERIFIED, `tools/ado_probe.ps1` in 64-bit PowerShell, output in `tools/ado_probe_out.txt`)

Connection string (exactly what the DbLib uses):
```
Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3 ODBC Driver;Database=C:\…\altium-live\partforge_test.db;NoCreat=1;"
```
- The connection opens: `Provider: MSDASQL.1 Version: 10.0`.
- `OpenSchema(adSchemaTables)` lists `Resistors/Capacitors/Inductors` as `TYPE=TABLE` and `Resistors_0603/AllPassives` as `TYPE=VIEW`.
- How SQLite declared types reach ADO:

| SQLite declaration | ADO type | DefinedSize |
|---|---|---|
| `TEXT` | 203 adLongVarWChar (memo) | 65536 |
| `VARCHAR(255)` | 202 adVarWChar | 255 |
| `VARCHAR(64)` | 202 | 64 |
| `REAL` | 5 adDouble | 8 |
| `INTEGER` | 3 adInteger | 4 |
| `NUMERIC` | 5 adDouble | 8 |
| no declared type | 202 | 255 |
| view `SELECT *` from a TEXT table | 203 (inherited) | 65536 |
| `UNION ALL` view (every column, including the expression column) | 202 | 255 |

- Unicode survives intact: `10 kΩ` arrives as `U+0031 U+0030 U+0020 U+006B U+03A9`, and `4.7 µF` arrives with `U+00B5`.
- A WHERE clause with a Unicode literal (`[Value] = '10 kΩ'`) returns 1 row.
- A 284-character value in a `VARCHAR(255)` column comes back **untruncated** through ADO (DescLen=284), even though DefinedSize is 255.

### 2.3 The DbLib file that Altium accepted (VERIFIED, generated by `tools/write_dblib.py`, verbatim excerpt of `PF_Test_abs.DbLib`)
```
[OutputDatabaseLinkFile]
Version=1.1
[DatabaseLinks]
ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER=SQLite3 ODBC Driver;Database=C:\Users\Example\AppData\Local\Temp\claude\c--Projekte-Tools\c2f879a0-18cd-4140-bad7-eb46f08463d7\scratchpad\altium-live\partforge_test.db;NoCreat=1;"
AddMode=3
RemoveMode=1
UpdateMode=2
ViewMode=0
LeftQuote=[
RightQuote=]
QuoteTableNames=1
UseTableSchemaName=0
DefaultColumnType=VARCHAR(255)
LibraryDatabaseType=
LibraryDatabasePath=C:\…\altium-live\partforge_test.db
DatabasePathRelative=0
TopPanelCollapsed=0
LibrarySearchPath=
OrcadMultiValueDelimiter=,
SearchSubDirectories=0
SchemaName=
LastFocusedTable=Resistors
[Table1]
SchemaName=
TableName=Resistors
Enabled=True
UserWhere=0
UserWhereText=
… [Table2]..[Table5] identical, with TableName=Capacitors / Inductors / Resistors_0603 / AllPassives …
[FieldMap1]
Options=FieldName=Resistors.Part Number|TableNameOnly=Resistors|FieldNameOnly=Part Number|FieldType=0|ParameterName=Part Number|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap2]
Options=FieldName=Resistors.Library Ref|TableNameOnly=Resistors|FieldNameOnly=Library Ref|FieldType=1|ParameterName=[Library Ref]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
… FieldType=1 / ParameterName=[<field>] for Library Path, Footprint Ref, Footprint Path, Description, for each of the 5 tables (30 FieldMaps in total) …
```
I took the format from existing DbLib files on disk (`C:\PartForge-Examples\Capacitor.DbLib` and `C:\PartForge-Examples\Altium_Libs\…\electronpowered.dblib`, read-only).
- UNVERIFIED: that `FieldType=0` marks the key field. Every test table had `Part Number` as its first column, so a "first column is the key" default would behave the same way.
- File encoding written: ASCII with CRLF.

### 2.4 What Altium 26.10 did with it (VERIFIED, sandbox runs 3 and 8)

- `IntegratedLibraryManager.InstallLibrary(<DbLib path>)` takes **≈107 ms**. The library is added at the end of `InstalledLibraryPath(i)` (index 20) and also appears in `AvailableLibraryPath(i)`. `UninstallLibrary(path)` removes it again (count went back to 20 in run 3).
- `IntMan.GetAvailableDBLibDocAtPath(path)` returns an `IDatabaseLibDocument`.
  - `GetFileName` and `GetConnectionString` echo the file. `GetLibrarySearchPath` returns `''`.
- **Tables and views are both visible:** `GetTableCount = 5`.
  - Index order is **alphabetical**, not the `[TableN]` order: `0 AllPassives, 1 Capacitors, 2 Inductors, 3 Resistors, 4 Resistors_0603`.
  - `TableEnabled(i)` is True for all five.
- Fields are readable (`GetFieldCount`, `GetFieldNameAt`, `GetParameterNameAt`):
  - Resistors and Capacitors have 14 fields each, Inductors 11, Resistors_0603 14, AllPassives 9.
  - Mapped model fields come back as `[Library Ref]`, `[Library Path]`, `[Footprint Ref]`, `[Footprint Path]`, `[Description]`.
  - Every other field maps to a parameter with the same name (Value, Comment, Manufacturer, …, Inductance_uH, Current_mA, Isat_A, Untyped, Short Text, Kind).
  - Both TEXT (memo) and VARCHAR tables, and both views, are listed.
- Other `IDatabaseLibDocument` calls:
  - `GetKeyFieldCount(i) = 1` for every table.
  - `GetKeyField(False,i,0)` and `GetKeyField(True,i,0)` both return `''`. The meaning of the index is unknown, so these calls are not useful as tested.
  - `GetLibraryPathFieldName(i) = 'Library Path'`.
  - `GetCommandString(i,'','')` returns `'Select * From [Resistors] '`.
- **Per-record resolution worked for RES-0001**, which lives in the TEXT table and uses relative `libs\PF_Test.SchLib`. The run wedged after this record (RES-0002 was never reached):
  - `DbDoc.GetSchLibPathForComponent(3,'RES-0001')` = `libs\PF_Test.SchLib` (raw field value)
  - `DbDoc.GetSchLibRefForComponent(3,'RES-0001')` = `PF_RES`
  - `IntMan.GetSchLibPathForDBComponent(<DbLib full path>,'Resistors','RES-0001')` = `C:\…\altium-live\libs\PF_Test.SchLib`. **The relative Library Path is resolved against the DbLib folder** (with LibrarySearchPath empty).
  - `IntMan.GetSchLibRefForDBComponent(...)` = `PF_RES`
  - `IntMan.GetParametersForDBComponent(...)` and `DbDoc.GetParametersForComponent(3,'RES-0001')` return the same string. Verbatim below, except that Ω and ± were mangled by the ANSI log (see 2.6):
    ```
    ParameterName0=Part Number|ParameterValue0=RES-0001|ParameterVisible0=False|ModelType0=PCBLIB|ModelName0=PF_R0603|Description=Chip resistor 10 kO ±1 % 0.1 W 0603 (relative paths)|ParameterName1=Value|ParameterValue1=10 kO|ParameterVisible1=False|ParameterName2=Comment|ParameterValue2==Value|ParameterVisible2=False|ParameterName3=Manufacturer|ParameterValue3=Yageo|ParameterVisible3=False|ParameterName4=Manufacturer Part Number|ParameterValue4=RC0603FR-0710KL|ParameterVisible4=False|ParameterName5=Tolerance|ParameterValue5=±1 %|ParameterVisible5=False|ParameterName6=Power|ParameterValue6=0.1 W|ParameterVisible6=False|ParameterName7=Package|ParameterValue7=0603|ParameterVisible7=False|ParameterName8=Datasheet|ParameterValue8=https://example.com/rc0603.pdf|ParameterVisible8=False|PlacingFromDatabase=TRUE|DesignItemId=RES-0001
    ```
    The footprint mapping is visible in this string (`ModelType0=PCBLIB|ModelName0=PF_R0603`). The *footprint path* does not appear in it.
  - `SchServer.LoadComponentFromDatabaseLibrary(<DbLib full path>,'Resistors','RES-0001')` returns a real `ISch_Component` **with the symbol loaded from the SchLib**:
    - `LibReference=PF_RES`, `GetAllPinCount=2`.
    - It keeps the symbol-level parameter `PF_SymbolParam=symbol-level value` and adds the DB parameters `Part Number` and `Value` (both `IsHidden=True`, because VisibleOnAdd=False).
    - `Designator.Text='R?'`, `Comment.Text='=Value'`.
    - `ComponentDescription` = the DB Description, which overrides the symbol's own description.
    - `LibraryPath='*'`, `SourceLibraryName='PF_Test_abs.DbLib'` (file name only), `DatabaseLibraryName='PF_Test_abs.DbLib'`, `DatabaseTableName='Resistors'`, `DesignItemId='RES-0001'`.
- `ALibraryName` arguments accept the **full DbLib path** (VERIFIED for `GetSchLibPathForDBComponent`, `GetParametersForDBComponent`, `LoadComponentFromDatabaseLibrary`).
- TEXT (adLongVarWChar memo) columns work in Altium for key lookup, parameters and description (VERIFIED for RES-0001).

### 2.5 Scriptable verification path for the test suite (calls VERIFIED individually; whole loop UNVERIFIED)
```pascal
IntMan := IntegratedLibraryManager;
IntMan.InstallLibrary(DbLibPath);                                   // VERIFIED ~0.1 s
DbDoc := IntMan.GetAvailableDBLibDocAtPath(DbLibPath);               // VERIFIED
// tables (alphabetical, tables + views): DbDoc.GetTableCount / GetTableNameAt(i) / TableEnabled(i)   VERIFIED
// fields: DbDoc.GetFieldCount(i) / GetFieldNameAt(i,f) / GetParameterNameAt(i,f)                    VERIFIED
// per record (keys come from PartForge's own SQLite DB, not from Altium):
S := IntMan.GetParametersForDBComponent(DbLibPath, TableName, Key);  // VERIFIED: 'ParameterName0=…|ModelName0=…|DesignItemId=…'
S := IntMan.GetSchLibPathForDBComponent(DbLibPath, TableName, Key);  // VERIFIED: resolved absolute SchLib path
S := IntMan.GetSchLibRefForDBComponent(DbLibPath, TableName, Key);   // VERIFIED
Comp := SchServer.LoadComponentFromDatabaseLibrary(DbLibPath, TableName, Key); // VERIFIED: Nil = not resolvable (UNVERIFIED for failures)
//   Comp.LibReference, Comp.GetAllPinCount, Comp.DesignItemId, Comp.DatabaseTableName, children via SchIterator_Create  VERIFIED
IntMan.UninstallLibrary(DbLibPath);                                  // VERIFIED
```
- Enumerating keys *inside* Altium is UNVERIFIED. `DbDoc.GetAllComponentKeys(TableIndex, AResults: IStrings)` needs an `IStrings`, and `TStringsAdapter.Create(TStringList)` exists in the API dump but was not tried. Recommendation: take keys from PartForge's own DB.
- Footprint-path resolution is UNVERIFIED. Candidates are `IntMan.GetDatabaseModelFullLibPath(DbLibPath, <raw [Footprint Path]>, ModelName, 'PCBLIB')` (no var parameters; used in follow-up 01) and `PCBServer.LoadCompFromLibrary(Pattern, LibPath)`. Avoid `GetDatabaseDatafileLocation` and `GetComponentLocationFromDatabase` because their `var` parameters are untested.

### 2.6 Still open for A (UNVERIFIED)
- **Unicode inside Altium: inconclusive.** The sandbox log is written by `TStringList.SaveToFile`, which uses **cp1252 with no BOM** (VERIFIED from raw bytes: `ParameterValue1=10 kO`, `±` stored as byte `0xB1`). `Ω` was best-fit to `O` *during logging*, so loss inside Altium cannot be told apart from loss in the log.
  - Supporting evidence: ADO from MSDASQL returns Unicode `adVarWChar`/`adLongVarWChar` (2.2), and Altium consumes it as WideString. Unicode most likely survives, but this is not proven.
  - Follow-up 01 dumps `Ord()` code points from a String copy and logs `Length()`. Expected lengths: `10 kΩ`=5, `±1 %`=4, `4.7 µF`=6.
- VARCHAR(255) table lookups (Capacitors) and truncation of the 284-character values inside Altium: not reached.
- `DatabasePathRelative=1` with a relative ODBC `Database=` (`PF_Test_rel.DbLib`): not run.
  - Inference: the ODBC driver resolves relative to Altium's CWD `C:\Program Files\Altium\AD22`, so it fails (`NoCreat=1` prevents an empty DB from being created). As far as I know, Altium rewrites `LibraryDatabasePath` only for its own Access and Excel types (UNVERIFIED).
  - Recommendation: write the absolute DB path, regenerate the DbLib when the path changes, or use an ODBC DSN.
- Path variants RES-0002..0005 (absolute, bare file name, empty, forward slash), the views, the typed Inductors table, missing symbol and missing footprint (RES-0007), placement on a SchDoc: not reached. Scripts are ready (followup 01, 03).

---

## 3. Goal B: creating libraries through the DelphiScript API (snippets VERIFIED, verbatim)

### 3.1 New SchLib with 2 symbols (pins, description, designator prefix, comment, parameter, footprint link), saved to a path (run 4, VERIFIED)
```pascal
S1 := 'C:\Users\Example\AppData\Local\Temp\claude\c--Projekte-Tools\c2f879a0-18cd-4140-bad7-eb46f08463d7\scratchpad\altium-live\libs\PF_Test.SchLib';
I3 := GetTickCount;
SandboxLog('create free SCHLIB');
Obj1 := CreateNewFreeDocumentFromDocumentKind('SCHLIB', True);
If Obj1 = Nil Then
Begin
    SandboxLog('Obj1 NIL');
    Exit;
End;
SandboxLog('created doc FileName=' + Obj1.FileName + ' Kind=' + Obj1.Kind + ' ms=' + IntToStr(GetTickCount - I3));
Obj2 := SchServer.GetCurrentSchDocument;
If Obj2 = Nil Then
Begin
    SandboxLog('current sch doc NIL');
    Exit;
End;
SandboxLog('current doc name=' + Obj2.DocumentName + ' ObjectID=' + IntToStr(Obj2.ObjectID) + ' eSchLib=' + IntToStr(eSchLib));
If Obj2.ObjectID <> eSchLib Then
Begin
    SandboxLog('ABORT: current doc is not a SchLib');
    Exit;
End;
If Pos(ExtractFileName(Obj1.FileName), Obj2.DocumentName) = 0 Then
Begin
    SandboxLog('ABORT: current doc is not the new doc');
    Exit;
End;
SandboxLog('existing comp lib ref=' + Obj2.GetState_CurrentSchComponentLibReference);
Obj5 := Obj2.CurrentSchComponent;
If Obj5 <> Nil Then SandboxLog('default comp=' + Obj5.LibReference);

SandboxLog('build PF_RES');
Obj3 := SchServer.SchObjectFactory(eSchComponent, eCreate_Default);
Obj3.CurrentPartID := 1;
Obj3.DisplayMode := 0;
Obj3.LibReference := 'PF_RES';
Obj3.ComponentDescription := 'PartForge test resistor symbol';
Obj3.Designator.Text := 'R?';
Obj3.Comment.Text := '=Value';
Obj4 := SchServer.SchObjectFactory(eRectangle, eCreate_Default);
Obj4.Location := Point(MilsToCoord(-100), MilsToCoord(-40));
Obj4.Corner := Point(MilsToCoord(100), MilsToCoord(40));
Obj4.LineWidth := eSmall;
Obj4.IsSolid := False;
Obj4.OwnerPartId := 1;
Obj4.OwnerPartDisplayMode := 0;
Obj3.AddSchObject(Obj4);
SandboxLog('rect added');
Obj4 := SchServer.SchObjectFactory(ePin, eCreate_Default);
Obj4.Designator := '1';
Obj4.Name := '1';
Obj4.Electrical := eElectricPassive;
Obj4.Orientation := eRotate180;
Obj4.Location := Point(MilsToCoord(-100), 0);
Obj4.PinLength := MilsToCoord(200);
Obj4.ShowName := False;
Obj4.OwnerPartId := 1;
Obj4.OwnerPartDisplayMode := 0;
Obj3.AddSchObject(Obj4);
Obj4 := SchServer.SchObjectFactory(ePin, eCreate_Default);
Obj4.Designator := '2';
Obj4.Name := '2';
Obj4.Electrical := eElectricPassive;
Obj4.Orientation := eRotate0;
Obj4.Location := Point(MilsToCoord(100), 0);
Obj4.PinLength := MilsToCoord(200);
Obj4.ShowName := False;
Obj4.OwnerPartId := 1;
Obj4.OwnerPartDisplayMode := 0;
Obj3.AddSchObject(Obj4);
SandboxLog('pins added');
Obj4 := SchServer.SchObjectFactory(eParameter, eCreate_Default);
Obj4.Name := 'PF_SymbolParam';
Obj4.Text := 'symbol-level value';
Obj4.IsHidden := True;
Obj4.Location := Point(0, MilsToCoord(-100));
Obj3.AddSchObject(Obj4);
SandboxLog('param added');
Obj4 := Obj3.AddSchImplementation;
Obj4.ModelName := 'PF_R0603';
Obj4.ModelType := 'PCBLIB';
Obj4.Description := 'PartForge footprint link';
Obj4.IsCurrent := True;
Obj4.AddDataFileLink('PF_R0603', 'PF_Test.PcbLib', 'PCBLIB');
SandboxLog('implementation added');
Obj2.AddSchComponent(Obj3);
SchServer.RobotManager.SendMessage(nil, c_BroadCast, SCHM_PrimitiveRegistration, Obj3.I_ObjectAddress);
SandboxLog('PF_RES registered');
{ … PF_CAP built the same way: two eLine plates (LineWidth := eMedium) at x=±20 mil,
  pins at (-20,0) eRotate180 and (20,0) eRotate0 with PinLength 180 mil,
  Obj4.AddDataFileLink('PF_C0603', '', 'PCBLIB') (empty location = any library) … }
If Obj5 <> Nil Then
Begin
    SandboxLog('remove default ' + Obj5.LibReference);
    Obj2.RemoveSchComponent(Obj5);
End;
Obj2.CurrentSchComponent := Obj3;
Obj2.GraphicallyInvalidate;
SandboxLog('build done ms=' + IntToStr(GetTickCount - I3));
SandboxLog('SetFileName');
S2 := Obj1.SetFileName(S1);
SandboxLog('SetFileName returned=' + S2 + ' FileName=' + Obj1.FileName);
I2 := GetTickCount;
B1 := Obj1.DoFileSave('');
SandboxLog('DoFileSave result=' + IntToStr(B1) + ' ms=' + IntToStr(GetTickCount - I2) + ' exists=' + BoolToStr(FileExists(S1), True));
```
Observed log:
- The new document is `Schlib1.SchLib`, kind `SCHLIB`; creation took **2062 ms**. `ObjectID=33=eSchLib`.
- A new SchLib always contains a default `Component_1`, which the script removed.
- `SetFileName` returned `''`, and the document's FileName became the target path. `DoFileSave('')` returned **-1 (True)** and the file exists.
- The saved file is 6144 bytes (OLE compound file). Its storages are `FileHeader, PF_CAP, PF_RES, Storage` (read with `olefile`).
- The records include `RECORD=45 … ModelName=PF_R0603|ModelType=PCBLIB|DatafileCount=1|ModelDatafile0=PF_Test.PcbLib|ModelDatafileEntity0=PF_R0603|ModelDatafileKind0=PCBLIB|IsCurrent=T`, `RECORD=34 … Text=R?|Name=Designator`, `RECORD=41 … Text==Value|Name=Comment` and `RECORD=41 … IsHidden=T|Text=symbol-level value|Name=PF_SymbolParam`.
- SchLib coordinates are stored in 10-mil units (`Location.Y=-10` for -100 mil).
- Pin semantics: `Location` is the body end and the pin extends toward `Orientation`. This is my assumption, consistent with altium-mcp's convention "eRotate0 (right)". It is UNVERIFIED visually because no screenshot was taken.

### 3.2 New PcbLib with pads, tracks and an extruded 3D body (runs 5 and 6, VERIFIED)
Run 5 (document plus the full PF_R0603):
```pascal
S1 := 'C:\Users\Example\AppData\Local\Temp\claude\c--Projekte-Tools\c2f879a0-18cd-4140-bad7-eb46f08463d7\scratchpad\altium-live\libs\PF_Test.PcbLib';
I3 := GetTickCount;
SandboxLog('create free PCBLIB');
Obj1 := CreateNewFreeDocumentFromDocumentKind('PCBLIB', True);
If Obj1 = Nil Then
Begin
    SandboxLog('Obj1 NIL');
    Exit;
End;
SandboxLog('created doc FileName=' + Obj1.FileName + ' Kind=' + Obj1.Kind + ' ms=' + IntToStr(GetTickCount - I3));
Obj2 := PCBServer.GetCurrentPCBLibrary;
If Obj2 = Nil Then
Begin
    SandboxLog('current pcblib NIL');
    Exit;
End;
SandboxLog('current lib board file=' + Obj2.Board.FileName + ' comps=' + IntToStr(Obj2.ComponentCount));
If Pos(ExtractFileName(Obj1.FileName), Obj2.Board.FileName) = 0 Then
Begin
    SandboxLog('ABORT: current pcblib is not the new doc');
    Exit;
End;
Obj5 := Obj2.CurrentComponent;
If Obj5 <> Nil Then SandboxLog('default fp=' + Obj5.Name);
PCBServer.PreProcess;
SandboxLog('PF_R0603');
Obj3 := PCBServer.CreatePCBLibComp;
Obj3.Name := 'PF_R0603';
Obj3.Description := 'PartForge test 0603 resistor (RESC1608X55N)';
Obj3.Height := MMsToCoord(0.55);
Obj2.RegisterComponent(Obj3);
SandboxLog('registered');
Obj4 := PCBServer.PCBObjectFactory(ePadObject, eNoDimension, eCreate_Default);
Obj4.Name := '1';
Obj4.Mode := ePadMode_Simple;
Obj4.x := MMsToCoord(-0.8);
Obj4.y := 0;
Obj4.Layer := eTopLayer;
Obj4.HoleSize := 0;
Obj4.TopXSize := MMsToCoord(0.95);
Obj4.TopYSize := MMsToCoord(1.0);
Obj4.TopShape := eRoundRectShape;
Obj4.StackCRPctOnLayer[eTopLayer] := 25;
Obj3.AddPCBObject(Obj4);
PCBServer.SendMessageToRobots(Obj3.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
{ … pad '2' identical at x = +0.8 mm … }
SandboxLog('pads');
Obj4 := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
Obj4.x1 := MMsToCoord(-0.15); Obj4.y1 := MMsToCoord(0.7); Obj4.x2 := MMsToCoord(0.15); Obj4.y2 := MMsToCoord(0.7);
Obj4.Width := MMsToCoord(0.12);
Obj4.Layer := eTopOverlay;
Obj3.AddPCBObject(Obj4);
PCBServer.SendMessageToRobots(Obj3.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
{ … second silk track at y = -0.7 mm … }
SandboxLog('silk');
For I1 := 0 To 3 Do
Begin
    Obj4 := PCBServer.PCBObjectFactory(eTrackObject, eNoDimension, eCreate_Default);
    If I1 = 0 Then Begin Obj4.x1 := MMsToCoord(-1.5); Obj4.y1 := MMsToCoord(-0.75); Obj4.x2 := MMsToCoord(1.5); Obj4.y2 := MMsToCoord(-0.75); End;
    If I1 = 1 Then Begin Obj4.x1 := MMsToCoord(1.5); Obj4.y1 := MMsToCoord(-0.75); Obj4.x2 := MMsToCoord(1.5); Obj4.y2 := MMsToCoord(0.75); End;
    If I1 = 2 Then Begin Obj4.x1 := MMsToCoord(1.5); Obj4.y1 := MMsToCoord(0.75); Obj4.x2 := MMsToCoord(-1.5); Obj4.y2 := MMsToCoord(0.75); End;
    If I1 = 3 Then Begin Obj4.x1 := MMsToCoord(-1.5); Obj4.y1 := MMsToCoord(0.75); Obj4.x2 := MMsToCoord(-1.5); Obj4.y2 := MMsToCoord(-0.75); End;
    Obj4.Width := MMsToCoord(0.05);
    Obj4.Layer := ILayer.MechanicalLayer(15);
    Obj3.AddPCBObject(Obj4);
    PCBServer.SendMessageToRobots(Obj3.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
End;
SandboxLog('courtyard');
Obj4 := PCBServer.PCBObjectFactory(eComponentBodyObject, eNoDimension, eCreate_Default);
SandboxLog('body created');
Obj5 := PCBServer.PCBContourFactory;
Obj5.AddPoint(MMsToCoord(-0.8), MMsToCoord(-0.4));
Obj5.AddPoint(MMsToCoord(0.8), MMsToCoord(-0.4));
Obj5.AddPoint(MMsToCoord(0.8), MMsToCoord(0.4));
Obj5.AddPoint(MMsToCoord(-0.8), MMsToCoord(0.4));
SandboxLog('contour pts=' + IntToStr(Obj5.Count));
Obj4.SetOutlineContour(Obj5);
SandboxLog('outline set');
Obj4.Layer := ILayer.MechanicalLayer(13);
Obj4.BodyProjection := eBoardSide_Top;
Obj4.BodyColor3D := $00303030;
Obj4.BodyOpacity3D := 1.0;
SandboxLog('body props');
Obj5 := Obj4.ModelFactory_CreateExtruded(0, MMsToCoord(0.55), $00303030);
SandboxLog('model created');
Obj4.Model := Obj5;
SandboxLog('model assigned');
Obj4.SetState_Identifier('PF_R0603_body');
Obj3.AddPCBObject(Obj4);
PCBServer.SendMessageToRobots(Obj3.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj4.I_ObjectAddress);
SandboxLog('body added; overall=' + FloatToStr(CoordToMMs(Obj4.OverallHeight)) + ' standoff=' + FloatToStr(CoordToMMs(Obj4.StandoffHeight)));
PCBServer.SendMessageToRobots(Obj2.Board.I_ObjectAddress, c_Broadcast, PCBM_BoardRegisteration, Obj3.I_ObjectAddress);
SandboxLog('PF_R0603 done');
PCBServer.PostProcess;
```
Run 5 log:
- The new document is `PcbLib1.PcbLib` (**2047 ms**). It holds a default footprint `PCBComponent_1`.
- `body added; overall=0,55 standoff=0`. **FloatToStr uses the German decimal comma.**
- Total run **5906 ms**, so PF_R0603 alone took ≈3.86 s (see section 4).

Run 6 (two more footprints, save, remove the default footprint, verbatim key parts):
```pascal
Obj2 := PCBServer.GetCurrentPCBLibrary;
If Obj2.Board.FileName <> 'PcbLib1.PcbLib' Then Begin SandboxLog('ABORT: unexpected lib'); Exit; End;
{ … loop creating PF_C0603 / PF_R0805 exactly like above (2 pads + extruded body):
    Obj4.Model := Obj4.ModelFactory_CreateExtruded(0, MMsToCoord(0.8), $00505050);
    SandboxLog('created ' + Obj3.Name + ' pads=' + IntToStr(Obj3.GetPrimitiveCount(MkSet(ePadObject))) + ' bodies=' + IntToStr(Obj3.GetPrimitiveCount(MkSet(eComponentBodyObject)))); … }
Obj1 := Client.GetDocumentByPath(Obj2.Board.FileName);      // works for the unsaved 'PcbLib1.PcbLib'
If Obj1 = Nil Then Obj1 := Client.CurrentView.OwnerDocument;
If Obj1.FileName <> 'PcbLib1.PcbLib' Then Begin SandboxLog('ABORT: wrong server doc'); Exit; End;
S2 := Obj1.SetFileName(S1);
B1 := Obj1.DoFileSave('');                                   // -1, 109 ms
Obj5 := Obj2.GetComponentByName('PCBComponent_1');
If Obj5 <> Nil Then
Begin
    Obj2.CurrentComponent := Obj2.GetComponentByName('PF_R0603');
    Obj2.RemoveComponent(Obj5);                              // comps 4 -> 3
    Obj1.Modified := True;
    B1 := Obj1.DoFileSave('');                               // -1
End;
```
Run 6 log: `created PF_C0603 pads=2 bodies=1`, `created PF_R0805 pads=2 bodies=1`, `comps now=4 ms=125`, `save1 result=-1 ms=109`, `removed; comps=3`, `save2 result=-1`.
After `SetFileName`, `Obj2.Board.FileName` also reports the new path.

### 3.3 Closing documents I created (run 7, VERIFIED)
```pascal
Obj1 := Client.GetDocumentByPath(S1);
If Obj1 <> Nil Then
    If Not Obj1.Modified Then Client.CloseDocument(Obj1);
SandboxLog('isopen schlib=' + BoolToStr(Client.IsDocumentOpen(S1), True) + …);   // False / False
```
No save prompt appeared (the documents were unmodified), and Free Documents was back to 0.

### 3.4 File-level check of the PcbLib (VERIFIED with `olefile` in `altium-live/.venv`)
- Storages are `PF_C0603`, `PF_R0603`, `PF_R0805` (no `PCBComponent_1`), plus `Library/*` and `FileHeader`.
- PF_R0603's `Data` record types are `[2,2,4,4,4,4,4,4,12]`: 2 pads, 6 tracks, 1 component body. PF_C0603 and PF_R0805 have `[2,2,12]`.
- PF_R0603 body record: `V7_LAYER=MECHANICAL13 … STANDOFFHEIGHT=0mil|OVERALLHEIGHT=21.6535mil|BODYPROJECTION=0 … BODYCOLOR3D=3158064|BODYOPACITY3D=1.000|IDENTIFIER=80,70,95,82,48,54,48,51,95,98,111,100,121 … MODEL.MODELTYPE=0 … MODEL.EXTRUDED.MINZ=0mil|MODEL.EXTRUDED.MAXZ=21.6535mil`. The identifier is stored as comma-separated character codes.
- PF_R0603 `Parameters`: `|PATTERN=PF_R0603|HEIGHT=21.6535mil|DESCRIPTION=PartForge test 0603 resistor (RESC1608X55N)|…`.

### 3.5 API facts and gotchas for B
- **Constant values** (VERIFIED from the skill's `Constants.md` dump): pad TShape `eNoShape=0, eRounded=1, eRectangular=2, eOctagonal=3, eCircleShape=4, eArcShape=5, eTerminator=6, eRoundRectShape=7, eRotatedRectShape=8`. `eRoundedRectangle=3` belongs to a different enum.
- **Probable altium-mcp bug** (UNVERIFIED in a real library): altium-mcp's `CreatePCBFootprint` maps "Oval" to `eRoundedRectangle`, which would produce an *octagonal* pad. Use `eRoundRectShape` together with `StackCRPctOnLayer[eTopLayer]`.
- Members present in the API dump but **not tried** (UNVERIFIED):
  - `SchServer.CreateSchLibrary` with `ISch_Lib.SaveToFile`, and `SchServer.SaveSchDocument(Doc, Path, Format)`
  - `PCBServer.CreatePCBLibrary` with `IPCB_Library.LibraryLoaderSaver_Create.SaveToFile(Lib, Path)`, `SaveEmptyLibrary`, `SaveComponentWithLibrary`
  - `IPCB_ComponentBody.LoadGenericModelFromFile(AFileName, AMakeEmbeded)` (STEP import)
  - These are candidates for headless creation without stealing focus; see follow-up 06.

---

## 4. Goal C: timings
Source: MCP server log `altium_mcp.log` (tool-call timestamp in ms) compared with in-script `Now`/`GetTickCount` (VERIFIED numbers; small sample, 0.5 s polling granularity on round trips).

| Measurement | Value |
|---|---|
| Launch → first script statement, 1st run of the session | **2.86 s** (call 21:11:15.672, `t0` 21:11:18.527) |
| Launch → first script statement, warm | **0.99 s** (call 21:15:06.087, first log 21:15:07.078) |
| Round trip of the MCP tool for a trivial script (13 lines) | **1.02 s** |
| `CreateNewFreeDocumentFromDocumentKind('SCHLIB'/'PCBLIB', True)` | **2.06 s / 2.05 s** |
| Building 2 symbols in an open SchLib | ≈0.67 s |
| First footprint (2 pads, 2 silk, 4 courtyard tracks, extruded body) | ≈3.86 s (cause unknown; most likely one-time init of 3D/PreProcess, UNVERIFIED) |
| Next 2 footprints (2 pads + body each) | **125 ms total (≈60 ms each)** |
| `DoFileSave('')` PcbLib (3 footprints) | 109 ms |
| `DoFileSave('')` SchLib (2 symbols) | < 16 ms (below GetTickCount resolution) |
| `InstallLibrary(DbLib)` | 107 ms |
| Closing 2 saved documents | ≈2.5 s (3.5 s round trip minus ≈1 s launch, UNVERIFIED breakdown) |

- **50 footprints in one run: not measured** (UNVERIFIED). Extrapolating the ≈60 ms per footprint gives ≈3 s, plus ≈2 s for document creation and any first-use overhead.
- Ready-to-run measurements: `followup/04_timing_50_footprints.txt`, plus `followup/05_latency_ping_body.txt` with `05b_latency_harness.py` (10 ms polling, relaunching the unchanged sandbox).

---

## 5. DelphiScript pitfalls confirmed in this run
- **VERIFIED, wedges the executor:** indexing a property of an interface variable, e.g. `Ord(Obj3.Text[I3])`. Copy the value into a declared `String` first (`S2 := Obj3.Text; … S2[I3]`). Indexing a declared String variable is the pattern altium-mcp's `pcb_utils.pas` uses (`PadData[j]`). It is UNVERIFIED in this run.
- **VERIFIED:** `try/except` does not stop the debugger from pausing. One runtime error blocks **all** later script runs, MCP tools included, until the user presses Ctrl+F3.
- **VERIFIED:** `FloatToStr` follows the locale (`0,55`). Exchange integers (coordinates/mils) or format numbers explicitly.
- **VERIFIED:** `TStringList.SaveToFile` writes cp1252 with no BOM, so Unicode is lost or best-fitted (`Ω`→`O`). Results containing Unicode need another channel. UNVERIFIED idea: load a UTF-8-with-BOM template into the TStringList first so its Encoding becomes UTF-8.
- **VERIFIED:** new SchLib and PcbLib documents carry a default `Component_1` / `PCBComponent_1`. Remove it with `ISch_Lib.RemoveSchComponent` or `IPCB_Library.RemoveComponent`.
- **VERIFIED:** `Client.GetDocumentByPath('PcbLib1.PcbLib')` finds an unsaved new document by its temporary name.
- **VERIFIED:** `SetFileName(path)` followed by `DoFileSave('')` performs a dialog-free "save as".

## 6. Incident log
| # | Script | Result |
|---|---|---|
| 1 | baseline (read-only) | ok |
| 2 | document kinds, CWD | ok |
| 3 | DbLib install, list tables/fields/keys, uninstall | ok |
| 4 | SchLib create and save | ok |
| 5 | PcbLib create + PF_R0603 + 3D body | ok |
| 6 | 2 more footprints, save, remove default, save | ok |
| 7 | close both libraries | ok |
| 8 | DbLib resolve RES-0001 and RES-0002 | **wedged** at the code-point loop (Sandbox.pas line 85). DbLib left installed. |

Snapshot of the wedged script: `altium-live/followup/wedged_Sandbox_snapshot.pas`.

## 7. Follow-up scripts (ALL UNVERIFIED, in `altium-live/followup/`; run in this order after Ctrl+F3)
- `00_cleanup_uninstall.txt`: uninstalls everything under `…\scratchpad\altium-live\` from Installed Libraries. **Run this first.**
- `01_dblib_resolve_all.txt`: all 13 test records across TEXT, VARCHAR, typed tables and both views. Logs resolved SchLib path, parameters, pins, implementations, `GetDatabaseModelFullLibPath` footprint path, `Length()` and code points of Value/Tolerance. Uninstalls at the end.
- `02_dblib_relative_db_path.txt`: tests the relative ODBC `Database=` with `DatabasePathRelative=1`.
- `03_place_on_temp_schdoc.txt`: free SCH document saved as `altium-live\PF_Place_Test.SchDoc`. Places RES-0002 through `LoadComponentFromDatabaseLibrary` + `RegisterSchObjectInContainer`, reads back parameters and `GetState_DatabaseLibraryKeys('|')`, then sets `Modified := False` and closes.
- `04_timing_50_footprints.txt`: 50-footprint timing, save, close.
- `05_latency_ping_body.txt` + `05b_latency_harness.py`: launch latency.
- `06_headless_library_experiment.txt`: `CreateSchLibrary/SaveToFile` and `CreatePCBLibrary/LibraryLoaderSaver`. **Run last; most likely to wedge.**

## 8. Implications for PartForge (recommendations; conclusions drawn from the VERIFIED facts above)
1. SQLite through `MSDASQL.1` and `SQLite3 ODBC Driver` is a working DbLib backend in AD 26.10 (VERIFIED).
   - Generate the ConnectionString with the **absolute** DB path plus `NoCreat=1`.
   - Write `[Library Path]` and `[Footprint Path]` **relative to the DbLib folder** (VERIFIED for the symbol path).
2. Prefer `VARCHAR(n)` (adVarWChar) for DbLib-facing columns, or expose them through views. TEXT works for short values (VERIFIED), but is reported as a memo type. Long-value behaviour inside Altium is UNVERIFIED.
3. Run a test-suite check per record with `IntMan.GetParametersForDBComponent` and `SchServer.LoadComponentFromDatabaseLibrary` (VERIFIED). Take keys from PartForge's DB. Batch many records into one script run, because each launch costs ≈1 s (≈2.9 s cold).
4. The Altium bridge must never trigger a runtime error, because one error wedges Altium for the user.
   - Generate DelphiScript only from vetted templates and move data through spec files (altium-mcp `create_*_batch` pattern).
   - Log every step and detect the wedge.
   - Show a clear "press Ctrl+F3 in Altium" recovery hint.
   - For bulk SchLib/PcbLib generation, writing files directly (for example with the separate Rust exe) avoids this risk and avoids stealing editor focus.
5. Creating documents through Altium steals focus (`CreateNewFreeDocumentFromDocumentKind(..., True)`, ≈2 s per document). Headless alternatives exist in the API but are untested (follow-up 06).
