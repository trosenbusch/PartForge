# Altium DbLib refresh: making a running Altium see new or changed SQLite rows

Agent: Altium-access agent (exclusive use of the running Altium) · 2026-10-07 23:30 – 2026-10-08 00:20
Altium: `C:\Program Files\Altium\AD22\X2.EXE`, **26.10.1.5**. Driver: 64-bit "SQLite3 ODBC Driver" 0.99991 (SQLite 3.43.2) via MSDASQL.
Working folder `RF` = `C:/Users/Example/AppData/Local/Temp/claude/c--Projekte-Tools/c2f879a0-18cd-4140-bad7-eb46f08463d7/scratchpad/altium-refresh/`
(`kit/` tools, `scripts/` every Altium script body that was run, `logs/` results and probes, `exp/eNN_*` one fresh DB + DbLib per experiment).

Every statement is tagged **[VERIFIED]** (observed in this Altium session or measured) or **[UNVERIFIED]** (inference, not testable here).

---

## 0. TL;DR

1. **Root cause [VERIFIED]: it is a pinned SQLite snapshot, not an Altium data cache.**
   * `InstallLibrary` (also `IntegratedLibrary:RefreshInstalledLibraries`) loads the DbLib as a **hidden server document** (`Client.IsDocumentOpen(dblib)=True`, `IsShown=False`, 1 view).
   * Its ADO/ODBC connection keeps a **SQLite read transaction open**: a WAL read-lock slot stays held while Altium is idle (lock probe), and the WAL grows.
     * `wal_checkpoint` cannot copy any frame written after the pinned snapshot. In e01 that was every frame (`checkpointed=0`, `TRUNCATE busy=1`).
     * In DELETE journal mode the same transaction is the SHARED lock that blocks every writer.
   * Every lookup Altium routes through that library (`GetParametersForDBComponent`, `GetAvailableDBLibDocAtPath`+`GetParametersForComponent`, `LoadComponentFromDatabaseLibrary`, `FindComponentLibraryPath`) therefore sees the snapshot from the moment the document was opened.
   * Control: the identical DbLib on a **Microsoft Access (.accdb, ACE 16)** backend shows external updates **and** inserts immediately, without any action, while its hidden document is open.
2. **Fix [VERIFIED]: close the hidden DbLib document** (`Client.GetDocumentByPath(dblib)` → `Client.CloseDocument`, only if `Modified=False` and `IsShown=False`).
   * Takes 0.30–0.47 s; no dialog. The read lock is released at once; the WAL checkpoints fully again.
   * Afterwards all lookups are fresh (path, file name, document, `LoadComponentFromDatabaseLibrary`, placement of a **new** key on a sheet), and they **stay fresh for later writes**. The lookups do not reopen the document.
3. **Second, smaller cache [VERIFIED]: Altium remembers "not found" for DesignItemID lookups.**
   * Affected calls: `FindComponentLibraryPath`, `GetComponentPlacementParameters`.
   * A key looked up while it did not yet exist stays "not found" after the close, although parameter lookups and `LoadComponentFromDatabaseLibrary` already return it.
   * `IntegratedLibrary:RefreshInstalledLibraries` clears it. But it reloads **all** installed libraries (2.4–3.0 s here) and **reopens and re-pins** every hidden DbLib document.
   * Full sequence after inserts: **close → RefreshInstalledLibraries → close**. A refresh without the first close keeps the old snapshot [VERIFIED].
4. **Tried without effect.**

   | Category | Attempt | Result | Tag |
   |---|---|---|---|
   | ODBC driver options | `NoTXN=1`, `StepAPI=0`, `StepAPI=1`, `StepAPI=1;NoTXN=1`, `SyncPragma=OFF;Timeout=100`, `ShortNames=1` | Read lock still held after install | VERIFIED |
   | OLE DB properties | `OLE DB Services=-4`, `Mode=Read` | Read lock still held after install | VERIFIED |
   | Library manager | `RefreshInstalledLibraries` alone | Still stale | VERIFIED |
   | DbLib document | `IDatabaseLibDocument.SetConnectionString(<same>)` | No effect | VERIFIED |
   | Library manager | `UninstallLibrary` | **Leaves the hidden document open** | VERIFIED |
   | Library manager | Uninstall + install, `DeactivateLibrary`/`ActivateLibrary`, editing the DbLib file | No effect | VERIFIED by `altium-verify-2.md` §5.2, with distinct file names. My own repeats in e08 were confounded by §0.5 and are not counted. The uninstall behaviour above explains the result |
   | Harmful | `LongNames=1` | Breaks all lookups (`<none>`) | VERIFIED |
5. **File-name resolution [VERIFIED]:**
   * Placed parts store only `SourceLibraryName=<file name>.DbLib` and `LibraryPath=*` (checked at file level).
   * `IntMan.GetParametersForDBComponent` resolves the library **by file name** even when a full path is passed. If two installed DbLibs share a file name, the **first installed one wins**.
   * This caused misleading "stale" results in my first experiments, which all used `PartForge.DbLib`.
   * PartForge must never have two installed DbLibs with the same file name.
6. **Path rotation [VERIFIED] works, but is not needed:**
   * Keep the same file name in a new folder; uninstall the old path, install the new one.
   * Placed parts follow the new folder. A **new file name breaks placed parts**.
7. **State [VERIFIED]:** 64 `run_altium_script` calls, all with `timeout_seconds=5`.
   * One run (two refreshes, about 5–6 s) exceeded the tool timeout and was polled from `sandbox_result.json`. It finished normally; it was not a wedge.
   * No dialog appeared and the executor never wedged. `get_screenshot` was never used.
   * Final state equals the baseline: 20 installed libraries (same list), 4 projects with the same document counts, Free Documents 0, focused project "Free Documents" (`logs/00_baseline.txt` and `logs/99_final_state.txt` are identical).

---

## 1. Safety log [VERIFIED]

| Item | Value |
|---|---|
| Baseline 23:33 | 20 installed IntLibs, AVAILABLE 20, projects Free Documents (0), `1355.PrjPcb` (31), `HPI_Award.PrjPcb` (13), `Sandbox.PrjScr` (1), focused Free Documents |
| Script rules | Every body is ASCII-only, contains no `Exit`, indexes no interface string, and logs with `SandboxLog` before risky calls. `CreateOleObject` was **not** used: it is not in the Altium 26 script engine's function tables (`ScriptingSystem.dll`) and the API dump, so the compile-error risk was too high. "Brand-new ADO connection in Altium" was tested with a new DbLib path using the identical connection string (Altium's own ADO stack) |
| Temp documents | One hidden free SchDoc `RF/exp/e17_rot/place_test.SchDoc`, created with `CreateNewFreeDocumentFromDocumentKind('SCH', False)`, so no tab and no focus change. It was saved, then closed with `Modified:=False` (the second placement was discarded) |
| Libraries | 26 test DbLibs were installed and all were uninstalled. Every hidden DbLib server document of my test libraries was closed (21 in the final cleanup, the rest during the experiments). **Uninstall does not close them**, see §3.3 |
| Previous agents' leftovers | 8 hidden DbLib documents from `altium-live` / `altium-verify2` were still open, uninstalled but holding connections. I closed them with the same verified call (unmodified, not shown, kind DATABASELIB). Result: their DELETE-mode test DBs are writable again and the file has no handle left (§3.3) |
| Final 00:20 | Identical to the baseline (diff empty). No `-wal`/`-shm` left on any test DB, so no SQLite connection is open. The Access lock file `pf.laccdb` is gone |

---

## 2. Method

* **Fresh DB per experiment [VERIFIED].**
  * `kit/mkexp.py` builds `pf.db` (WAL, table `[Resistors]`, all TEXT, RES-0001..0003) plus `libs/` and one or more DbLibs with absolute `Database=`.
  * Each experiment uses a new folder; most use a **unique DbLib file name** (see §0.5).
* **External writer [VERIFIED].** `kit/dbop.py` does `update`, `insert` (BEGIN IMMEDIATE…COMMIT, 4–13 ms while Altium is connected) and `probe`. `probe` reports:
  * the sizes of `-wal`/`-shm`;
  * the wal-index header (`mxFrame`, `nBackfill`, `aReadMark[0..4]`), read-only;
  * **which SQLite shm lock bytes are held by another process**: a non-blocking exclusive `LockFileEx` on bytes 120+i, released immediately;
  * `PRAGMA wal_checkpoint(PASSIVE)` and optionally `(TRUNCATE)` with a 300 ms busy timeout.
* **Altium side.** `kit/gen2.py` generates query blocks (verbatim bodies are in `RF/scripts/`). The three lookup families:
  * `i` = `IntMan.GetParametersForDBComponent(path|name, table, key)`
  * `d` = `IntMan.GetAvailableDBLibDocAtPath(path).GetParametersForComponent(0, key)`
  * `l` = `SchServer.LoadComponentFromDatabaseLibrary(path, table, key)`, only called when `d` sees the key, so no untested missing-key path is used
  * index probes: `IntMan.FindComponentLibraryPath(kind, lib, DesignItemID)` and `IntMan.GetComponentPlacementParameters(3, path, key)`
* **Outside-Altium reproduction.** `kit/ado_lockrepro.py` runs pywin32 ADO through MSDASQL with the same connection string and probes the locks from a separate process.

---

## 3. Q1: snapshot or Altium cache?

### 3.1 Evidence

| # | Experiment | Observation | Tag |
|---|---|---|---|
| 1 | e01: install + query, Altium idle | `locks: READ0=HELD` (probed twice, 1 min apart) | VERIFIED |
| 2 | e01: external UPDATE + INSERT | Commits fine in 7–9 ms. `wal_checkpoint(PASSIVE) busy=0 log=3 checkpointed=0`, `wal_checkpoint(TRUNCATE) busy=1`. WAL 0 → 12392 bytes | VERIFIED |
| 3 | e01: re-query old path | V1, new key absent (stale). **New DbLib path with identical connection string** (`PartForge_fresh.DbLib`): V2 and the new key. Afterwards **READ0 and READ1 both HELD**: the new connection pins its own snapshot | VERIFIED |
| 4 | e07: `InstallLibrary` only, no lookup | `READ0=HELD`. Install alone opens and pins | VERIFIED |
| 5 | e13: hidden doc after install | `Kind=DATABASELIB Modified=False IsShown=False ViewCount=1 CanClose=True`, not listed in Free Documents | VERIFIED |
| 6 | e11/e12: unique names, close the hidden doc | Lock released; `i`, `d`, `l` all return V2 and the new key. Then V3 + another key without a new close: also fresh (doc stays closed) | VERIFIED |
| 7 | e16 Access (.accdb, ACE.OLEDB.16.0) | Install 422 ms, hidden doc open. External UPDATE/INSERT via ADO: `i`, `d` and the index see V2 and the new key **with no action** | VERIFIED |
| 8 | DELETE mode (previous agents' DBs) | `BEGIN EXCLUSIVE` → `database is locked` while their (already uninstalled) hidden docs were open. After closing those docs: `EXCLUSIVE lock OK (1 ms)`, and `CreateFile` share=none and delete access both OK | VERIFIED |

**Conclusion [VERIFIED].**
* The staleness is the open read transaction of the connection behind the hidden DbLib document.
* Apart from the "not found" cache in §7.2, Altium does **not** cache DbLib rows itself: Access shows fresh rows, and a closed document gives fresh rows.

### 3.2 Which ADO pattern holds the transaction (outside Altium, `logs/x_ado_*.txt`)

All patterns ran against this driver, one fresh connection each. "HELD" means the read lock stays held while the recordset is open.

| Pattern | Default (StepAPI=0) | NoTXN=1 | StepAPI=1;NoTXN=1 |
|---|---|---|---|
| Recordsets fully fetched by the driver (Execute, server fwd/keyset/static, client static), OpenSchema tables/columns, parameterised/prepared commands | free | free | Execute and server fwd-only partly read: **HELD** |
| `BeginTrans` + select, no commit | **HELD** | free | free |
| `Recordset.MaxRecords = N` with N ≤ rows (server fwd/static, client static, prepared) | **HELD** | **HELD** | static/client: **HELD** |
| `MaxRecords` > rows, or `WHERE 1=0` | free | free | free |

* **[VERIFIED]** The SQLite ODBC driver stops stepping at `SQL_ATTR_MAX_ROWS` without resetting the statement. The read transaction then stays open until the recordset closes, with every option combination.
* **[UNVERIFIED]** Which of these patterns Altium uses. Neither `NoTXN=1` nor `StepAPI` releases the lock in Altium (§6), and closing the document releases it, so it is most likely a limited or partly fetched dataset owned by the hidden document. No driver option can fix that.

### 3.3 Lifecycle of the hidden document [VERIFIED]

| Trigger | Hidden doc |
|---|---|
| `InstallLibrary` (first time for a path) | opened, pinned |
| `RefreshInstalledLibraries` | reopened **for every installed DbLib**, pinned at that moment (e11–e15 were closed earlier and open again at cleanup) |
| `UninstallLibrary` | **stays open** (e08 `uninstall … isopen=True`; e01–e10 and 8 docs of previous agents still open long after uninstall). This explains the previous agent's "locked until Altium restarts" |
| `Client.CloseDocument` | closed, connection released, `-wal`/`-shm` can be checkpointed or removed |
| `GetParametersForDBComponent` (path or name), `GetAvailableDBLibDocAtPath`, `LoadComponentFromDatabaseLibrary`, `FindComponentLibraryPath`, `GetComponentPlacementParameters`, placing a part with `RegisterSchObjectInContainer` | do **not** reopen it |
| `ISch_Component.GetState_DatabaseLibraryKeys` on a **placed** part | **reopens** it and holds a read lock, but lookups stayed fresh in that state (V5 and a new key visible through `i`/`d`/`l`/name/index, e17h) |
| Altium start-up | **[UNVERIFIED]** expected to open it like the library load (restart not allowed) |

---

## 4. Q2: process and command resources (read-only grep, `RF/strings/`)

* **[VERIFIED]** `System/IntegratedLibrary.INS` commands:
  * `RefreshInstalledLibraries` ("Refresh one or all installed libraries"). No parameter name for a single library was found in the DLL strings; called without parameters it refreshes all.
  * Also `AddRemoveLibraries`, `Refresh` / `Update` / `Commit` (repository), `RefreshSVNDBLibraries`, `PlaceLibraryComponent`, `FindComponent`, `InstallCurrentLibrary`.
* **[VERIFIED]** `WorkspaceManager.ins/.rcs`:
  * The DbLib editor window kind is `DatabaseLib`.
  * `PLDatabaseLink:EditConnection` = `WorkspaceManager:DocumentOptions ObjectKind=DatabaseLink|Mode=EditConnection`: a modal dialog, **not run**.
  * "Update Parameters From Database" = `WorkspaceManager:DocumentOptions ObjectKind=Project|Action=DatabaseUpdate`: a modal dialog, **not run**.
  * There is **no** reconnect, clear-cache or reload process for DbLibs.
* **[VERIFIED]** DLL strings found:
  * `WorkspaceManager.dll`: `&Connect` / `&Connected` / `&Reconnect`. These are button captions of the DbLib editor view, not processes. Also `TDatabaseLibDocument`, `TDatabaseLibView`.
  * `IntegratedLibrary.dll`: class `TDatabaseLibrary` with fields `fADODataSet`, `FComponentCache`, `FFieldCache`, `FDatabaseLibDocument` and methods `DisposeDatabaseLibDocument`, `ResetComponentCache`, `SetFileModified`, `GetOrCreateComponentFromDataset`. Also `TLibrary.GetLibraryInstance(aVFSAddress, aForced, AUseCache, …)` and `TLibraryReleaser` (`FReleased`, `FReleasedTime`).
  * Library objects are cached and released lazily, which is why reinstall takes 0 ms. None of these internals is reachable from DelphiScript.
* **[VERIFIED]** `IntegratedLibrary:RefreshInstalledLibraries` was run 7 times: 2375–2953 ms, never a dialog.

## 5. Q3: interface methods

* **[VERIFIED from the API dump]** `IDatabaseLibDocument` (42 members) has **no** Connect, Disconnect, Reconnect, Refresh, ClearCache or Reload. Candidates were `SetConnectionString`, `DisposeIfNotShowing` and `ClearDatabaseTypeFields`. `IIntegratedLibraryManager` has `UpdateCachedFileIfNecessary` (SVN/vault cache) and Install/Uninstall/Activate/Deactivate. `IDatabaseLinkDocument.ClearDbCache` exists only for `.DbLink`.
* **[VERIFIED]** `DbDoc.SetConnectionString(DbDoc.GetConnectionString)`: no reconnect, still stale (V1, new key absent), `Modified` stays False (e19).
* **[VERIFIED]** `Client.OpenDocument('DATABASELIB', path)` returns the **already open hidden document** (`isopen before=True`). `Client.CloseDocument` on it is the fix (§7).
* **Not tested: `DisposeIfNotShowing`.** IntegratedLibrary keeps its own `FDatabaseLibDocument` reference to the document, so disposing it underneath risks a use-after-free crash with the user's work open. It is not needed, because `CloseDocument` is the normal, safe lifecycle path.

## 6. Q4: ODBC / OLE DB options (lock probe right after install, each on its own DB)

| Option(s) in `Extended Properties` / outer string | Read lock after install | Lookups |
|---|---|---|
| default (`NoCreat=1`) | HELD | stale after external write |
| `NoTXN=1` (e02, e12 unique name) | HELD | **stale** (e12) |
| `StepAPI=0` | HELD | — |
| `StepAPI=1` | HELD | — |
| `StepAPI=1;NoTXN=1` | HELD | — |
| `SyncPragma=OFF;Timeout=100` | HELD | — |
| `ShortNames=1` | HELD | — |
| outer `OLE DB Services=-4` | HELD | — |
| outer `Mode=Read` | HELD | — |
| `LongNames=1` (with SyncPragma/Timeout) | free | **broken**: RES-0001 → `<none>` (columns become table-qualified). Never use it |

* All rows: **[VERIFIED]**.
* `JournalMode`, `NoWCHAR`, `FKSupport`, `BigInt`, `JDConv`, `OEMCP`, `LoadExt`, `AttachAs` were not tried. **[UNVERIFIED]**, but by mechanism (§3.2) none of them changes the lifetime of the statement or transaction.

---

## 7. The fix and its verification

### 7.1 Procedure

* **Variant A, values (always, after every PartForge write batch):** close the hidden DbLib document if it is open, unmodified and not shown. This is enough for changed rows and for new keys that Altium has never looked up.
* **Variant B, index rebuild (after inserting parts):**
  1. close;
  2. `RunProcess('IntegratedLibrary:RefreshInstalledLibraries')`;
  3. close again.

  This clears Altium's cached "not found" results and rebuilds the IntegratedLibrary component index. The second close is mandatory, because the refresh reopens and re-pins the document.

### 7.2 Verification matrix (e18 `PartForgeFinal.DbLib`, unique name)

Setup: install, then look up RES-0201 while it is absent (creates a negative entry). PartForge then writes RES-0001 V2, inserts RES-0201 and RES-0202.

| Lookup | after A | after B | later write V3 + RES-0301, no new call |
|---|---|---|---|
| `GetParametersForDBComponent('PartForgeFinal.DbLib',…)` RES-0001 | V2 | V2 | V3 |
| same, RES-0201 (was looked up while absent) | V2 | V2 | — |
| `LoadComponentFromDatabaseLibrary` RES-0201, RES-0202 | V2, pins=2 | V2 | — |
| `FindComponentLibraryPath(2, name, RES-0202)` (never looked up) | found | found | RES-0301 found |
| `FindComponentLibraryPath` / `GetComponentPlacementParameters` RES-0201 | **NOT found / empty** | **found / V2** | — |
| hidden doc open afterwards | False | False | False |

* Every cell is **[VERIFIED]**.
* Timings [VERIFIED]: close 313 ms (A); refresh 2625 ms + close 469 ms (B); plus about 1 s script launch.
* The negative cache was also reproduced on Access (e16: `index NOT found`, `params V3`), so it is Altium-side [VERIFIED].

### 7.3 The three use cases

* **(a) IntegratedLibraryManager lookups and placing a NEW key [VERIFIED].**
  * `GetParametersForDBComponent` (path and name), `LoadComponentFromDatabaseLibrary`, and `RegisterSchObjectInContainer` placement of a newly inserted key (e17e: R2 = RES-0005, V3, pins=2) are all fresh after variant A.
  * `FindComponentLibraryPath` / `GetComponentPlacementParameters` are fresh after A for keys never looked up before, and after B for all keys.
* **(b) Components panel listing [UNVERIFIED in the UI].**
  * Testing it would need clicks in the user's panel, which I did not do.
  * What is verified: after B, the IntegratedLibrary component index that backs the library object contains the new keys, and `GetComponentPlacementParameters` returns their parameters.
  * Still open: whether an open panel repaints by itself, or whether the user must re-select the library or use the panel's refresh.
* **(c) "Update Parameters From Database" [VERIFIED at API level, dialog UNVERIFIED].**
  * The command is a modal dialog and was not run.
  * The lookup it must do was verified (e17c/e17e): take the placed part's `DatabaseLibraryName` (= file name), `DatabaseTableName` and `GetState_DatabaseLibraryKeys('|')`, then call `IntMan.GetParametersForDBComponent(<file name>, table, keys)`.
  * Result: the stale V1 before rotation or close; V2/V3 after it, while the placed part still shows V1, so there is something to update.

### 7.4 Bridge snippet (tested verbatim)

* `RF/scripts/bridge_refresh_dblib_by_name.pas` is the template. It resolves the installed path by **file name**, so path spelling and case don't matter.
* It was run exactly as below with `S2 := 'PartForgeFinal.DbLib';` and `B1 := 0;` (e18b, variant A) or `B1 := 1;` (e18d, variant B). Those two lines are the only changes from the template.
* It uses only the altium-mcp sandbox scratch variables (`S1,S2,I1..I3,B1,Obj1,List1,IntMan,ResultText`).

```pascal
{ PartForge bridge: make the running Altium see rows PartForge inserted/changed in its SQLite DbLib.
  Mechanism: InstallLibrary / RefreshInstalledLibraries / Altium start-up load the DbLib as a HIDDEN
  server document whose ADO connection keeps a SQLite read transaction open (pinned WAL snapshot).
  Closing that hidden document releases the snapshot; afterwards Altium's lookups use fresh queries.
  Parameters (edit before running):
    S2 = DbLib FILE NAME as installed (placed parts reference the DbLib by file name only)
    B1 = 0: values only (changed rows; brand-new keys that Altium never looked up)
         1: also rebuild Altium's component index (after inserting parts: clears "not found"
            results Altium cached for keys it looked up before they existed). Runs
            IntegratedLibrary:RefreshInstalledLibraries (refreshes ALL installed libraries, ~2.5-3 s here)
            and closes the hidden document again afterwards.
  Never closes a DbLib that is visible in an editor tab or has unsaved edits. No Exit, ASCII only. }
S2 := 'PartForgeFinal.DbLib';
B1 := 1;
IntMan := IntegratedLibraryManager;
List1 := TStringList.Create;
For I2 := 0 To B1 Do
Begin
    If I2 = 1 Then
    Begin
        I3 := GetTickCount;
        ResetParameters;
        RunProcess('IntegratedLibrary:RefreshInstalledLibraries');
        List1.Add('refreshed installed libraries ms=' + IntToStr(GetTickCount - I3));
    End;
    For I1 := 0 To IntMan.InstalledLibraryCount - 1 Do
    Begin
        S1 := IntMan.InstalledLibraryPath(I1);
        If UpperCase(ExtractFileName(S1)) = UpperCase(S2) Then
        Begin
            Obj1 := Client.GetDocumentByPath(S1);
            If Obj1 = Nil Then List1.Add('pass' + IntToStr(I2) + ' not open: ' + S1)
            Else If Obj1.Modified Then List1.Add('pass' + IntToStr(I2) + ' SKIPPED (unsaved edits): ' + S1)
            Else If Obj1.IsShown Then List1.Add('pass' + IntToStr(I2) + ' SKIPPED (open in editor): ' + S1)
            Else
            Begin
                I3 := GetTickCount;
                Client.CloseDocument(Obj1);
                List1.Add('pass' + IntToStr(I2) + ' closed hidden document ms=' + IntToStr(GetTickCount - I3) + ': ' + S1);
            End;
        End;
    End;
End;
ResultText := List1.Text;
List1.Free;
```

Observed results:
* A: `pass0 closed hidden document ms=313: …\PartForgeFinal.DbLib`.
* B: `pass0 not open … / refreshed installed libraries ms=2625 / pass1 closed hidden document ms=469`.

Notes:
* With `B1 = 1` the run takes longer than 5 s on slow machines. Use the file-polling pattern.
* In a standalone PartForge script project, declare `S1,S2: String; I1,I2,I3,B1: Integer; Obj1: IDispatch; List1: TStringList; IntMan: IIntegratedLibraryManager` **[UNVERIFIED outside the sandbox]**.

---

## 8. Q5: path rotation (e17, `kit/mk_rot.py`)

Setup: stable root with `pf.db` + `libs/`; DbLibs in `.dblib\v1..v3\PartForge.DbLib` and `.dblib\v4\PartForge_r4.DbLib`.

| Question | Result | Tag |
|---|---|---|
| What does a placed part store? | `SourceLibraryName=PartForge.DbLib` (file name only), `DatabaseLibraryName` = the same, `LibraryPath=*`, `DatabaseTableName`, `DesignItemId`, keys. The implementation stores `ModelName=PF_R0603`, no datafile path, `DatabaseDatalinksLocked=T` (API read-back and SchDoc `FileHeader` parsed with olefile) | VERIFIED |
| Same file name, new folder (v3 → v1: close + uninstall v3, install v1) | `FindComponentLibraryPath(2,'PartForge.DbLib','RES-0003')` → v1 path. Name lookup → V2 (fresh); the placed part still shows V1 | VERIFIED |
| New file name (only `PartForge_r4.DbLib` installed) | Placed part's library `PartForge.DbLib` → `''`, parameters empty: **broken** | VERIFIED |
| Two `PartForge.DbLib` installed (v2, then v1) | Resolves to **v2, the first installed** | VERIFIED |

Relative paths after rotation [VERIFIED, symbol + footprint resolution and `LoadComponentFromDatabaseLibrary` pins=2]:

| `[Library Path]` / `[Footprint Path]` | v1: `LibrarySearchPath` empty | v2: `=<root>\libs`, SubDirs 0 | v3: `=<root>`, SubDirs 1 |
|---|---|---|---|
| `libs\PF_Test.SchLib` (relative to the DbLib folder) | unresolved | unresolved | unresolved |
| `PF_Test.SchLib` (bare name) | unresolved | resolved via search path | resolved via search path + subdirs |
| absolute | resolved | resolved | resolved |
| `..\..\libs\PF_Test.SchLib` (fixed depth) | resolved | resolved | resolved |

* Folder-qualified relative paths are **not** combined with `LibrarySearchPath`.
* A rotation design would need bare file names plus an absolute `LibrarySearchPath`, or absolute paths.
* Rotation also leaves the old hidden document open (uninstall doesn't close it). It is unnecessary given §7.

## 9. Q6: Access backend (e16) [VERIFIED]

* `Provider=Microsoft.ACE.OLEDB.16.0` works as a DbLib (install 422 ms). Altium opens the `.accdb` shared (`pf.laccdb` present), and external ADO writes take about 0.3 s.
* External UPDATE and INSERT are visible about 20 s later and again 7 s later through `i`, `d` and the index, while the hidden document stays open.
* The negative DesignItemID cache applies here too.
* This rules out an Altium-side row cache as the main cause; for SQLite it is the pinned snapshot.

---

## 10. Recommendations for PartForge (derived from the VERIFIED facts)

1. Keep SQLite in WAL mode with the existing connection string (`…;NoCreat=1;`). Don't add NoTXN, StepAPI or `OLE DB Services`. **Never use `LongNames=1`.**
2. After every write batch, run the bridge snippet with `B1 := 0` (about 0.3 s + launch).
   * After **inserting** parts, run it with `B1 := 1`, or offer it as a "Sync to Altium" action, because it refreshes all installed libraries (about 3 s).
   * Then PartForge may run `PRAGMA wal_checkpoint(TRUNCATE)`. PASSIVE was verified to complete fully once the document is closed; TRUNCATE succeeding in that state is **[UNVERIFIED]**.
3. Exactly **one** installed DbLib per file name.
   * Keep the file name stable forever, because placed parts reference it.
   * When moving the library, uninstall the old path (and close its hidden document) before installing the new one.
4. If the snippet reports `SKIPPED (open in editor)` or `SKIPPED (unsaved edits)`, tell the user to close the DbLib tab. PartForge cannot refresh it then.
5. Anything that reloads libraries pins the snapshot again from that moment on: Altium start-up [UNVERIFIED], `RefreshInstalledLibraries` (also a Components panel refresh, if it maps to it [UNVERIFIED]), and installation. Running the snippet after each write covers this.
6. Bridge facts:
   * `UninstallLibrary` alone does not release the DB; always close the hidden document too.
   * `GetState_DatabaseLibraryKeys` on placed parts reopens the document, which is harmless for freshness in the tests.

## 11. Open / UNVERIFIED

1. The Components panel UI: whether it repaints, and whether closing the hidden document while the panel shows that DbLib has any side effect. **Test once by hand** with the PartForge DbLib selected in the panel.
2. The "Update Parameters From Database" dialog itself (modal, not run). Only its lookup was verified.
3. Altium start-up behaviour: is the hidden document opened at start or lazily on first use?
4. Which exact ADO pattern Altium uses (MaxRecords-limited or partly fetched dataset of the hidden document, §3.2).
5. `IDatabaseLibDocument.DisposeIfNotShowing`: deliberately not called (crash risk, not needed).
6. Running the snippet in a standalone PartForge script project (variable declarations), and timing with many more installed libraries.

## 12. Artefacts (all under `RF`)

* `kit/`:
  * DB and DbLib builders: `mkexp.py`, `mk_rot.py`
  * external writers and probes: `dbop.py`, `dbop_access.py`, `excl_probe.py`
  * outside-Altium ADO matrix: `ado_lockrepro.py`
  * script generators: `gen.py`, `gen2.py`, `compose.py`, `find_block.py`
  * result polling: `poll.py`
  * read-only DLL string tools: `dllstrings.py`, `dllnear.py`
  * SchDoc record reader: `schdoc_records.py`
* `scripts/`: every script body that was run (`eNN*.pas`), the bridge templates `bridge_refresh_dblib*.pas`, `99_cleanup.pas`, `99_final_state.pas`.
* `logs/`:
  * baseline and final state;
  * one `*_result.txt` per run;
  * lock and checkpoint probes: `e01_probe*.txt`, `e02_05_probe1.txt`, `e19_21_probe1.txt`, `e22_23_probe1.txt`, `99_locks_after_cleanup.txt`;
  * ADO matrix: `x_ado_*.txt`.
* `strings/`: DLL string extracts (`lib_dlls.txt`, `sqlite3odbc.txt`).
* `exp/`: e01–e23, e17_rot (with `place_test.SchDoc`), x_ado. Altium no longer holds any of these files.
