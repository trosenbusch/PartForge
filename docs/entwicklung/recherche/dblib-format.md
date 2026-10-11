# Altium database library files (.DbLib, also .SvnDbLib and .DbLink): reference for PartForge

Research date: 2026-10-07. Author: research agent (UNDERSTAND phase).
Working folder (scripts, test databases, downloaded docs): `<scratchpad>/dblib-research/`

## Evidence tags used in this report

| Tag | Meaning |
|---|---|
| **[TEST]** | I tested it on this machine through ADO, then an OLE DB provider, then ODBC, in a 64-bit process. This is the same data-access stack Altium uses, but the test ran **outside Altium**. |
| **[FILE]** | Read in real DbLib files: `C:/PartForge-Examples/Capacitor.DbLib`, `electronpowered.dblib`, the two Celestial `*.DbLib`, or the Celestial SQLite snapshot. |
| **[BIN]** | Taken from strings or RTTI in the installed Altium binaries (`System/WorkspaceManager.dll`, `System/AdvSch.dll`). |
| **[DOC]** | Verbatim from Altium documentation fetched on 2026-10-07 (the pages are the current "Altium Designer" docs). |
| **[PRIOR]** | From earlier local work in `<altium-mcp-checkout>/dev/DBLIB_FINDINGS.md`. That work was tested against live Altium with a production Access DbLib. I did not re-test it. |
| **[INFERRED]** | My conclusion, drawn from the evidence listed with it. |
| **[UNVERIFIED]** | Not verified. Must be tested in Altium before anyone relies on it (see section 13). |

> **Important environment fact [TEST]:** the installed and running Altium is **Altium Designer 26.10.1 (build 26.10.1.5)**. Both `X2.EXE` ProductVersion and the registry key `HKLM\SOFTWARE\Altium\Builds\Altium Designer {A102241D-…}` (`Version=26.10.1.5`, `ProgramsInstallPath=C:\Program Files\Altium\AD22`) say so. Only the install folder is called "AD22". Every [BIN] fact below comes from this 26.10.1 install. The 64-bit rules from AD18 onwards apply.

---

## 1. File basics

- The file is an INI file with sections `[OutputDatabaseLinkFile]`, `[DatabaseLinks]`, `[Table1]…[TableN]` and `[FieldMap1]…[FieldMapM]`. **[FILE]**
- All four sample files are plain ASCII with CRLF line endings and no BOM. **[FILE]**
- Altium writes its other INI-style files (`*.PrjPcb`, `*.OutJob`) in ANSI cp1252 with no BOM. Example: `Butterh\xe4rte` (ä = 0xE4) in `C:/PartForge-Examples/**/Example.PrjPcb`, which is not valid UTF-8. **[FILE]** The DbLib is therefore very likely ANSI too **[INFERRED]**.
  - **Rule:** write DbLib files in cp1252 with no BOM and CRLF line endings.
  - Keep table names, column names and paths ASCII-only where you can.
  - Hint (weak evidence): `Capacitor.DbLib` contains a column written as `?Part Number`, which looks like a character that ANSI could not represent.
- Section numbering:
  - `TableN` and `FieldMapN` start at 1 and are contiguous in every sample.
  - `FieldMapN` numbering is **global across all tables**, not per table. **[FILE]**
  - Write them contiguously. A gap may stop the reader **[UNVERIFIED]**.
- Boolean formats are mixed, so copy them exactly. **[FILE]**
  - `Enabled=True|False` and `VisibleOnAdd=True|False` use words.
  - `QuoteTableNames`, `UseTableSchemaName`, `DatabasePathRelative`, `TopPanelCollapsed`, `SearchSubDirectories` and `UserWhere` use `0|1`.
- Whitespace around `=`:
  - The older Celestial file writes `Key = Value` with spaces, e.g. `Version = 1.1`.
  - The newer Celestial V2 file and the other samples use `Key=Value` with no spaces. **[FILE]**
  - Altium probably trims the spaces **[UNVERIFIED]**. Always write `Key=Value`.
- Values run to the end of the line and may contain `=`, `;` and `"`. Example: `ConnectionString=…Extended Properties="…"`. **[FILE]**
- Writer key order, from the AD 26 writer string table **[BIN]**. Use the same order:
  - `OutputDatabaseLinkFile`, `Version`
  - `DatabaseLinks`: `ConnectionString`, `AddMode`, `RemoveMode`, `UpdateMode`, `ViewMode`, `LeftQuote`, `RightQuote`, `QuoteTableNames`, `UseTableSchemaName`, `DefaultColumnType`, `LibraryDatabaseType`, `LibraryDatabasePath`, `DatabasePathRelative`, `TopPanelCollapsed`, `LibrarySearchPath`, `OrcadMultiValueDelimiter`, `SearchSubDirectories`, `SchemaName`, `LastFocusedTable`
  - `Table`: `TableName`, `Enabled`, `UserWhere`, `UserWhereText`, `BrowserOrder_Sorting`, `BrowserOrder_Grouping`, `BrowserOrder_Visible`
  - `FieldMap`: `FieldName` `=` `.` `|` `TableNameOnly`, `FieldNameOnly`, `FieldType`, `ParameterName`, `VisibleOnAdd`, `Options`
  - The samples also write `SchemaName=` as the first key of each `[TableN]`.

## 2. `[OutputDatabaseLinkFile]`

| Key | Value | Notes |
|---|---|---|
| `Version` | `1.1` | Every sample uses 1.1 **[FILE]**. The reader also recognises the strings `1.0`, `0.9` and `0.0` (old formats) **[BIN]**. Always write `1.1`. |

The section name comes from the DbLink format, the original "Database Link" file. DbLib and SvnDbLib documents are subclasses of `TDatabaseLinkDocument` **[BIN RTTI]**.

## 3. `[DatabaseLinks]`: every key

These are the RTTI fields of the classes **[BIN]**:
- `TDatabaseLinkDocument`: `ConnectionString, LeftQuote, RightQuote, DefaultColumnType, QuoteTableNames, UseTableSchemaName, DefaultMode_Add, DefaultMode_Remove, DefaultMode_Update, LastFocusedTable, LastTableViewMode, … RelativePath, DatabaseType, DatabasePath, TopPanelCollapsed, SchemaName`
- `TDatabaseLibDocument` adds `LibrarySearchPath, SearchSubDirectories, OrcadMultiValueDelimiter`.
- `TSVNDatabaseLibDocument` adds `RepositoryURL, FileRepositoryIsRelative`.

| Key | Typical value | Meaning, allowed values and default | Evidence |
|---|---|---|---|
| `ConnectionString` | see section 9 | ADO/OLE DB connection string. Altium uses it verbatim unless the type-based relative mode applies (see `DatabasePathRelative`). Docs: "Any database which provides OLE DB support can be connected to … The OLE DB provider for the ODBC database is specified as part of the connection string." | [DOC][FILE] |
| `AddMode` | `3` | Global default for **Add To Design**. Applies to fields whose per-field AddMode is 0 (Default). **1 = Do not add, 2 = Add, 3 = Add only if not blank in database.** Every sample uses 3 (Altium's new-file default). Docs: "This option is obeyed both when initially placing the component from the database library and when using the Update Parameters From Database command". | codes [BIN]+[FILE], see 3.1 |
| `RemoveMode` | `1` | Global default for **Remove From Design**. **1 = Do not remove, 2 = Remove only if blank in database.** Default 1. | [BIN]+[FILE] |
| `UpdateMode` | `2` | Global default for **Update Values**. **1 = Do not update, 2 = Update.** Default 2. | [BIN]+[FILE] |
| `ViewMode` | `0` | UI state only: the last active tab of the DbLib editor. It maps to RTTI `LastTableViewMode` of type `TTableViewMode = (eTableView_Linking, eTableView_Browser)`, so 0 = Field Mappings and 1 = Table Browser. It does **not** control parameter visibility. Write 0. | [BIN] / [INFERRED] |
| `LeftQuote` / `RightQuote` | `[` / `]` | Characters used to quote identifiers in the SQL Altium generates and in the Where clause. Docs: "Left Quote Character … The default is "["" / "Right Quote Character … The default is "]"". For PostgreSQL use `"` and `"`; for MySQL use a backtick. | [DOC][FILE][TEST] |
| `QuoteTableNames` | `1` | "Quote Tables - enable to use specific quote characters to quote tables." Always write 1, because table names contain spaces. | [DOC][FILE] |
| `UseTableSchemaName` | `0` | "Include Table Schema Names … By default, this option is off". Needed for Oracle-style schemas. Keep 0 for SQLite and PG `public`. | [DOC][FILE] |
| `DefaultColumnType` | `VARCHAR(255)` | "Field Data Type - specify the data type for new fields." Altium uses this type when it **adds columns itself**, for example `Supplier n` / `Supplier Part Number n` from *Edit Supplier Links*. Default `VARCHAR(255)`. | [DOC][BIN][TEST: `ALTER TABLE … ADD [Supplier 2] VARCHAR(255)` works on SQLite] |
| `LibraryDatabaseType` | empty, `Microsoft Access`, `Microsoft Access 2007`, `Microsoft Excel`, `Microsoft Excel 2007` | Used by the "Select Database Type" fast connection (Access/Excel only). Leave it empty for custom connection strings (SQLite, PG, SQL Server); Celestial does. The file filters link `Access 2007` to `*.accdb` and `Excel 2007` to `*.xlsx`. | [BIN][FILE] |
| `LibraryDatabasePath` | e.g. `electronpowered.xls` | Database file used by the type-based connection. Relative to the DbLib folder when `DatabasePathRelative=1`. | [FILE][DOC] |
| `DatabasePathRelative` | `0`/`1` | Docs: "The full path can be specified, or you can opt to store the path relative to the Database Library/SVN Database Library file." In electronpowered the stale absolute `ConnectionString` points at `C:\projects\altium-library\electronpowered.xls` while `LibraryDatabasePath=electronpowered.xls` and `DatabasePathRelative=1`. This shows Altium **rebuilds** the connection string from type + path. That applies only to the Access/Excel types. | [DOC][FILE]; rebuild behaviour [INFERRED] |
| `TopPanelCollapsed` | `0` | UI state (whether the top region is collapsed). | [BIN] |
| `LibrarySearchPath` | empty | Library Search Paths from *Tools » Options » Symbol & Model Search Paths*. Entries may be relative "to the location of the DbLib file". **The format for several entries is [UNVERIFIED].** Prior tooling (`altium-mcp/dev/make_part_spec.py`) parses a production AD file with `search.split(";")`. | [DOC][BIN][PRIOR] |
| `OrcadMultiValueDelimiter` | `,` | Only used for OrCAD CIS import. Keep `,`. | [BIN][FILE] |
| `SearchSubDirectories` | `0` | "Search Subdirectories - check this box to perform the search in subdirectories as well." | [DOC][FILE] |
| `SchemaName` | empty | Schema filter used with UseTableSchemaName. Keep empty. | [FILE] |
| `LastFocusedTable` | table name | UI state. | [FILE] |

### 3.1 How the numeric mode codes were derived

WorkspaceManager.dll contains these Delphi `UnicodeString` constants, contiguous and in this order **[BIN]**. Offsets are hex addresses in the DLL.

```
017a7680 'Lookup Key'     017a76a4 'Normal'                                   <- FieldType 0,1
017a76c0 'Default'        017a76dc 'Do not add'  017a7700 'Add'  017a7714 'Add only if not blank in database'   <- AddMode 0..3
017a7764 'Default'        017a7780 'Do not remove'  017a77a8 'Remove only if blank in database'               <- RemoveMode 0..2
017a77f8 'Default'        017a7814 'Do not update'  017a783c 'Update'                                          <- UpdateMode 0..2
```

These are Delphi `array[TEnum] of string` tables, so the ordinal value equals the index.

The mapping is consistent with all four sample files:
- Per-field values are always `0` (Default).
- The global values are `AddMode=3`, `RemoveMode=1`, `UpdateMode=2`.
- Index 0 has no meaning at global level.

The docs list the same choices: Update Values "Update and Do not update"; Add To Design "Do not add, Add, and Add only if not blank in database"; Remove From Design "Do not remove and Remove only if blank in database" **[DOC]**.

| Code | FieldType | AddMode (field / global) | RemoveMode | UpdateMode |
|---|---|---|---|---|
| 0 | **Lookup Key** (the key field) | Default (use global) | Default | Default |
| 1 | **Normal** | Do not add | Do not remove | Do not update |
| 2 | – | Add | Remove only if blank in database | Update |
| 3 | – | Add only if not blank in database | – | – |

## 4. `[TableN]`

| Key | Meaning | Evidence |
|---|---|---|
| `SchemaName` | Raw schema of the table (RTTI `RawSchemaName`). Empty unless UseTableSchemaName=1. | [FILE][BIN] |
| `TableName` | Table or view name exactly as the provider reports it. Excel sheets end with `$` ("The name of the table will have the suffix $"). | [FILE][DOC] |
| `Enabled` | `True`/`False`. "The Enable option next to each table entry allows you to control whether or not that table is to be part of the resulting database library." Each enabled table shows in the Components panel as `<LibraryName>.DbLib - <TableName>`. | [DOC][FILE] |
| `UserWhere` | `0` = **Single key lookup** (radio `Radio_BasicLookup`), `1` = **Where clause** (radio `Radio_Where`). "Matching criteria is specified on a per-table basis." | [DOC][BIN][FILE] |
| `UserWhereText` | The Where clause. It is stored even when UserWhere=0; Celestial keeps `[Part Number] = '{Part Number}'` with UserWhere=0. See section 6. | [FILE][DOC] |
| `BrowserOrder_Sorting`, `BrowserOrder_Grouping`, `BrowserOrder_Visible` | Table Browser grid layout (UI state). Format seen: `Part Number0=134\|Description0=128\|…\|F100=48`, i.e. `<column><digit>=<width>`. `F10`/`F11` are Excel auto-names. **Optional**: electronpowered `[Table2]` has none of these keys. | [FILE] |

Altium lists every table **and view** the connection can see and writes all of them, using `Enabled=False` for unwanted ones. Celestial V2 lists 311 tables including `sysdiagrams` and 147 disabled `z_*` base tables **[FILE]**. Views appear as tables:
- SQLite views are reported by ADO `OpenSchema(adSchemaTables)` with `TABLE_TYPE=VIEW` **[TEST]**.
- PDXpert docs: "Altium will treat each view in the LocalDB database as a library table."
- Celestial's MSSQL categories are views. Users on its issue tracker asked for "SHOW VIEW" privileges.

## 5. `[FieldMapN]`: one `Options=` line per mapped column

Sub-keys appear in this exact order in every sample **[FILE]**:

```
Options=FieldName=<Table>.<Column>|TableNameOnly=<Table>|FieldNameOnly=<Column>|FieldType=<0|1>|ParameterName=<name>|VisibleOnAdd=<True|False>|AddMode=<0..3>|RemoveMode=<0..2>|UpdateMode=<0..2>
```

| Sub-key | Meaning |
|---|---|
| `FieldName` | `Table.Column`, using the separator `.` **[BIN]**. Redundant, because `TableNameOnly` and `FieldNameOnly` disambiguate. |
| `TableNameOnly` / `FieldNameOnly` | Table name and column name, case exactly as in the DB. |
| `FieldType` | **0 = Lookup Key** (the *Database field* of the Single key lookup) and **1 = Normal** **[BIN]**. Every enabled sample table has exactly one `FieldType=0` entry. Celestial and electronpowered use `Part Number`; Capacitor.DbLib uses `ID` **[FILE]**. For the key row, `ParameterName` is the **Part parameter**, i.e. the component parameter that stores the key value. |
| `ParameterName` | The **Design Parameter**. See 5.1 for the special forms: `[Reserved]`, plain name, and empty (= `[None]`). |
| `VisibleOnAdd` | "Visible On Add - … whether a newly added parameter, resulting from initial placement or update after placement, is made visible for the component on the schematic sheet". Default False **[DOC]**. Celestial sets it True for `Comment`, `Value`, `Capacitance`, … **[FILE]**. |
| `AddMode` / `RemoveMode` / `UpdateMode` | Per-field overrides; 0 = Default, meaning use the global value. Codes are in 3.1. They have no effect on bracketed mappings or on the key field. Docs: "Attribute and Model based mappings (entries with square brackets…) will have no associated update options" and "The key field … will have no associated update options." **[DOC]** |

### 5.1 `ParameterName` semantics

- **Square brackets** = reserved attribute or model mapping. Docs: "The square brackets denote a reserved name, such as [Library Ref]. This data is used to populate the component's attributes and models. Design Parameters that do not include square brackets become component parameters." **[DOC]** The full list is in section 7.
- **Plain name** = a component parameter with that name. "All other database field names will be automatically mapped to design parameters using the same names." Renaming is allowed: the column can differ from the parameter name **[DOC]**.
- **Empty `ParameterName=`** = the UI's **`[None]`** ("set the Design Parameter entry to [None]", meaning not transferred) **[DOC]**.
  - A production DbLib written by Altium maps excluded columns (`PKG_TYPE`, `DxDesigner_*`) to an **empty** ParameterName. **[PRIOR]**
  - `[None]` and `<Choose Parameter>` are UI display strings **[BIN]**.
  - Write `ParameterName=` (empty) for excluded columns.
- **Automatic mapping on connect:** "Initial mapping is performed automatically upon connection to the database, with all database fields mapped. Note that the automatic mapping assumes that the Database Field Names match the reserved name used in Altium Designer." **[DOC]**
- [PRIOR] also notes that symbol parameters are filled from the column with the same name, case-insensitively.

### 5.2 Which FieldMaps Altium writes (observed rule)

The rule below fits all four sample files **[FILE]** and is **[INFERRED]**. The RTTI has `TFieldLink.IsDefault` **[BIN]**.

A FieldMap is written only when the field differs from the implicit default. The implicit default is: `ParameterName = column name`, `FieldType=1`, all modes 0, `VisibleOnAdd=False`.

Consequences:
- The key (`FieldType=0`) is always written.
- Every bracketed mapping is written, even when the column is literally called `Library Ref`.
- Every `VisibleOnAdd=True` is written.
- Every rename and every `[None]` (empty) is written.
- Ordinary same-name parameters are **not** written. Example: electronpowered has `Manufacturer`, `Package` and `Value` columns but no FieldMaps for them.
- Disabled tables usually have no FieldMaps (Celestial: 147 disabled, 0 FieldMaps).

**Generator rule for PartForge:** for each enabled table, write exactly one `FieldType=0` key row plus every non-default mapping. Writing explicit rows for ordinary same-name columns as well is harmless, but Altium may drop them when it re-saves the file **[INFERRED]**.

## 6. Matching (key field, `UserWhere`, `UserWhereText`)

- **Single key lookup** (`UserWhere=0`), quoted from the docs **[DOC]**:
  > If the Single key lookup option is enabled (default) the Database field and Part parameter fields become available. … Typically, the lookup key field used is something that uniquely identifies each component in the external database, such as a Part Number.

  > When using the Update Parameters From Database feature at some stage after placement, information is read from the chosen key parameter in the placed schematic components and then searched for in the chosen (key) field of the database - across all enabled tables.

  So **key values must be unique across all enabled tables**, not only within one table.
- **Where clause** (`UserWhere=1`), quoted from the docs **[DOC]**:
  > For example if the Database field was chosen to be Part Number - the default - the Part parameter field would automatically be set to Part Number also, and the entry for the Where clause would be : `[Part Number] = '{Part Number}'`

  > The curly brackets (braces) specify that the entry being referenced is a design parameter. The single quotes are used to specify the design parameter be treated as a string, as opposed to a number (no quotes).

  > Example: `[Capacitance] = '{Capacitance}' AND [Tolerance] = {Tolerance} AND [Manufacturer] = '{Manufacturer}'`

  Column quoting follows LeftQuote/RightQuote, e.g. `"Part Number" = '{Part Number}'` on PostgreSQL **[TEST]**.
- **What a placed DbLib part stores [PRIOR]:**
  - `DesignItemID` = key value (the part number)
  - `LibReference` = symbol name
  - `DatabaseTableName` = table/view name
  - `DatabaseLibraryName` and `SourceLibraryName` = DbLib **file name only**
  - `LibraryPath='*'`
  - parameters `hidden=True`
  - one `PCBLIB` model with `IsCurrent=True`, `UseComponentLibrary=True` and one datafile link

  "Update from Database" re-links a part through `DesignItemID`. The AD binary contains the placement parameter strings `PlacingFromDatabase=TRUE` and `DesignItemId=` **[BIN]**.
- **Several link files:** "If the same database field has been used for matching in both the DbLink and DbLib/SVNDbLib files, the database linked by the DbLink file will be searched first … you could quite possibly match and update from the wrong external record." **[DOC]**
- **Uniqueness in real data:** the Celestial snapshot (2020-12-15, 149,624 rows, 132 tables) has **5,607 duplicated `Part Number` values** **[FILE]**. PartForge must enforce global uniqueness itself.

## 7. Reserved design parameters, and columns Altium treats specially

Automatic mapping applies when the column has exactly the name shown **[DOC]**:

| Column name | Design Parameter | Notes |
|---|---|---|
| `Library Ref` | `[Library Ref]` | **Required.** Altium shows "The following … tables do not have the Library Ref field designated: This field must be assigned in order to place components from this database library." **[BIN]** "The [Library Ref] entry must exist in the Design Parameter column … to be able to place a component" **[DOC]**. |
| `Library Path` | `[Library Path]` | Path to the `.SchLib` (resolution: section 8). |
| `Footprint Ref` | `[Footprint Ref]` | **Default footprint**: "The Database Field Name that is mapped to Design Parameter [Footprint Ref] will be the default footprint … It is this footprint that will be placed when the design is transferred to the PCB domain." **[DOC]** |
| `Footprint Path` | `[Footprint Path]` | Path to the `.PcbLib`. |
| `Footprint Ref n` / `Footprint Path n` | `[Footprint Ref n]` / `[Footprint Path n]` | "Unlimited footprint model references (and paths) can be specified … In the reserved names, n represents a positive integer starting from 2." **[DOC]** The binary builds them from the prefixes `[Footprint Ref` / `[Footprint Path` (`GetModelIndex`) **[BIN]**. Use 2, 3, …, never 1. Celestial uses `Footprint Ref 2/3` and `Footprint Path 2/3` **[FILE]**. |
| `Description` | `[Description]` | The component Description attribute, not a parameter. |
| `PCB3D Ref` / `PCB3D Path` | `[PCB3D Ref]` / `[PCB3D Path]` | **Legacy.** "References to PCB3D refer to the legacy 3D viewer, these should not be used for new designs." **[DOC]** STEP models belong in the footprint (PcbLib 3D body). |
| `Orcad Library` / `Orcad Footprint` | `[Orcad Library]` / `[Orcad Footprint]` | Only for OrCAD CIS import. In the binary, the strings `Schematic Part` and `Layout PCB Footprint` (OrCAD CIS field names) sit next to them **[BIN]**. The pairing is [INFERRED]. |
| `Sim Model Name`, `Sim File`, `Sim Kind`, `Sim SubKind`, `Sim Netlist`, `Sim Spice Prefix`, `Sim Port Map`, `Sim Parameters`, `Sim Excluded Parts`, `Sim Description` | `[Sim …]` | Internally mapped to "Simulation ModelName/File/Kind/SubKind/Netlist/SpicePrefix/PortMap/Parameters/ExcludedParts/Description" **[BIN]**. Syntax **[DOC]**: Port Map `(1:1),(3:2)`; Excluded Parts `2,4`; Parameters `!Area Factor=2\|!Temperature=22` (`\|` separator, `!` = do not also create a component parameter). "Sim Netlist … must be defined and not left blank". "Only one simulation model link can be defined for a component in an external database." Concrete Sim Kind/SubKind/Netlist values for R/C/L are **[UNVERIFIED]**; copy them from a generic sim part placed in AD. |

Other names Altium treats specially. These are ordinary (non-bracket) parameters with built-in meaning:

| Name | Effect | Evidence |
|---|---|---|
| `Part Number` | Conventional key. "By default, only the Part Number and Library Ref fields are displayed in the component listing region of the panel." | [DOC] |
| `Comment` | Fills the component **Comment**, which is shown on the schematic and carried to the PCB. A value of `=Value` or `=Part Number` uses string indirection: "to map the value of the component parameter Capacitance into the component's Comment field, enter the string =Capacitance". Celestial maps `Comment` with `VisibleOnAdd=True`; values are `=Value` in 132,132 rows and `=Part Number` in 17,492 rows. Without a Comment mapping, a DB-placed part showed Comment = LibReference [PRIOR]. | [DOC][FILE][PRIOR]; that a `Comment` column sets the Comment attribute is **[UNVERIFIED in AD26]** |
| `Value` | Ordinary parameter, normally referenced by `Comment` = `=Value`. | [FILE] |
| `Supplier n` + `Supplier Part Number n` | **Supplier link.** "Creation of a Supplier Link involves the addition of two parameters … Supplier n … Supplier Part Number n … n is an integer suffix". *Edit Supplier Links* in the Table Browser **adds columns to the table**: "The record for the component in the database will be updated, with additional fields for Supplier n and Supplier Part Number n added". The BOM turns each pair into a Solution. | [DOC] |
| `Manufacturer n` + `Manufacturer Part Number n` | BOM solution fields. KB: "Altium Designer treats Manufacturer n and Manufacturer Part Number n as system-reserved fields. When part choices are present, ActiveBOM automatically fills these fields … overriding any local values." DbLib parts have no Part Choices. ActiveBOM's *Define Manufacturer Link Fields* dialog can pair any name/MPN parameters ("Detect fields - … all parameter pairs that include the term manufacturer in their name"). Celestial uses plain `Manufacturer`. | [DOC] |
| `ComponentLinknDescription` + `ComponentLinknURL` | Clickable component links in the right-click **References** menu and in PDFs. AdvSch uses the formats `ComponentLink%dURL` / `ComponentLink%dDescription` [BIN]. "While any number of named links can be defined, only the first 9 will be available in the Schematic editor's right-click References context menu." A supplier datasheet import "will add a ComponentLink parameter pair … ComponentLinknDescription and ComponentLinknURL" [DOC, AD18 archive]. Celestial: `ComponentLink1Description='Datasheet'` and `ComponentLink1URL=<pdf url>`, up to 6 pairs. | [DOC][BIN][FILE] |
| `HelpURL` | Help link (AdvSch string `HelpURL`). "HelpURL and ComponentLinks can become links in the PDF". | [BIN][DOC] |
| `Datasheet` | No special handling found in AD26 strings. Use a ComponentLink pair instead. | [BIN, negative search] |

The **designator prefix** (`R?`, `C?`) is not a DbLib field. It comes from the symbol's default designator in the SchLib **[INFERRED]** (it is not in the reserved list).

## 8. How `Library Path` / `Footprint Path` (and `Sim File`) are resolved

Search order, verbatim **[DOC]**:
> 1. If a full path exists in the mapped path field for the symbol or model, use that library/model file and extract the symbol or model specified in the applicable reference field.
> 2. If a relative path exists in the mapped path field … use that library/model file …
> 3. If only a library/model file name exists in the mapped path field …, use the search paths to locate the first library/model file that matches the specified name and which contains a match …
> 4. If no library/model file information exists in the database, use the search paths to locate the first library/model file containing a match …

What "relative" is relative to: **the DbLib file's folder.**
- For `Sim File` the docs say so explicitly: "You can enter a relative path (relative to the DbLib file) to a model file (e.g., Libraries\JAS33.mdl)".
- For search paths: "You can add either as a full path, or as a relative path (relative to the location of the DbLib file)" **[DOC]**.
- Celestial evidence:
  - Every one of its 149,624 rows uses paths relative to the repo root with **forward slashes**, e.g. `symbols/Passives/SCH - PASSIVES - CAPACITOR.SCHLIB` and `footprints/Capacitor - MLCC/PCB - CAPACITOR - MLCC - CAP 01005_0402.PCBLIB`.
  - Its DbLib sits in the repo root with an empty `LibrarySearchPath`.
  - That setup only works if relative paths resolve against the DbLib folder and forward slashes are accepted **[FILE] + [INFERRED]**.
  - Backslashes are the Windows-native form and are also expected to work.

Performance and robustness:
- Prefer explicit relative paths over search paths. "Using Search Paths with a large number of symbol/model files - … this approach is not recommended when there are a large number of symbol or model files present in the search location."
- "a footprint will only be found if it is in a file with a .Lib or .PcbLib extension" **[DOC]**.

For SVNDbLib: a relative path is relative to the repository root, and "Any defined path mappings for symbols and footprint models are ignored" after converting a DbLib to SVNDbLib **[DOC]**.

## 9. Connection strings

Every **[TEST]** below:
- ran in a **64-bit** Windows PowerShell 5.1 process through `ADODB.Connection`;
- listed tables with `OpenSchema(adSchemaTables)`;
- ran `SELECT * FROM [T]`, a key lookup, `LIKE`, `SELECT DISTINCT … ORDER BY`, and `COUNT(*) AS NoOfCount`. These statement shapes come from AD strings: `SELECT DISTINCT %s FROM %s ORDER BY %0:s`, `SELECT COUNT(*) AS NoOfCount`, `Select * From`, ` LIKE '`, `WHERE ` **[BIN]**.

Drivers present on this PC:

| Component | Version |
|---|---|
| `SQLite3 ODBC Driver` (Christian Werner, `C:\WINDOWS\system32\sqlite3odbc.dll`) | 0.99991, embedded SQLite 3.43.2 |
| `PostgreSQL Unicode(x64)` (`C:\Program Files\psqlODBC\1700\bin\podbc35w.dll`) | 17.00.0008 |
| `ODBC Driver 17/18 for SQL Server` | – |
| OLE DB `Microsoft.ACE.OLEDB.12.0`, `Microsoft.ACE.OLEDB.16.0`, `MSOLEDBSQL`, `MSOLEDBSQL19`, `SQLNCLI11`, `SQLOLEDB`, `MSDASQL` | – |

### 9.1 SQLite through the 64-bit "SQLite3 ODBC Driver" with MSDASQL **[TEST]**

The string Altium's Build/Data Link dialog produces. **Recommended:**
```
Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="Driver={SQLite3 ODBC Driver};Database=C:\PartForgeLib\PartForge.sqlite;NoCreat=1;"
```

Also verified:
```
Provider=MSDASQL;Driver={SQLite3 ODBC Driver};Database=C:\PartForgeLib\PartForge.sqlite
Driver={SQLite3 ODBC Driver};Database=...            (no Provider: ADO defaults to MSDASQL; do not use in a DbLib)
Provider=MSDASQL.1;Persist Security Info=False;Data Source=SQLite3 Datasource;Database=C:\...\PartForge.sqlite;NoCreat=1   (DSN + override)
```

Notes:
- Keep the literal prefix `Provider=MSDASQL.1`. AD contains a provider-recognition list **[BIN]**: `Provider=Microsoft.Jet.OLEDB`, `Provider=Microsoft.ACE.OLEDB`, `Driver={Microsoft Access Driver`, `Provider=sqloledb`, `Driver={SQL Server`, `Driver={SQL Native Client`, `Provider=SQLNCLI`, `Driver={MySQL`, `Provider=MySQLProv`, `Provider=msdaora`, `Provider=OraOLEDB.Oracle`, `{Microsoft ODBC for Oracle`, `Provider=MSDASQL.1`.
- Driver keywords (README of ch-werner.de/sqliteodbc) **[DOC]**:
  - `Database`
  - `Timeout` (lock timeout in ms, **default 100000**)
  - `StepAPI` (default false)
  - `NoTXN`
  - `NoWCHAR` ("don't support WCHAR types")
  - `NoCreat` ("if true and database file doesn't exist, don't create it automatically; default false")
  - `LongNames`, `ShortNames`
  - `SyncPragma`, `FKSupport`, `JournalMode`
  - `OEMCP`, `BigInt`, `JDConv`
  - `TraceFile`, `AttachAs`, `ILike`
  - connectionstrings.com example: `DRIVER=SQLite3 ODBC Driver;Database=c:\mydb.db;LongNames=0;Timeout=1000;NoTXN=0;SyncPragma=NORMAL;StepAPI=0;`
- **`NoCreat=1` is important [TEST]:** without it, a wrong path silently creates a **0-byte empty database**. The connection then succeeds and shows no tables. With `NoCreat=1` it fails with `connect failed`.
- **Do not set `NoWCHAR=1` [TEST]:**
  - Default (WCHAR) returns `äöü µ Ω ±` correctly as UTF-16.
  - `NoWCHAR=1` returns mojibake (UTF-8 bytes read as Latin-1).
  - `OEMCP=1;NoWCHAR=1` loses `Ω` (becomes `O`).
- **A relative `Database=` path resolves against the *process working directory*, not the DbLib [TEST]:**
  - `Database=.\typetest.sqlite` worked only when the CWD was the DB folder; from another CWD it gave `connect failed`.
  - Altium's CWD is not controlled, so a relative DB path in an ODBC string is **not portable** **[INFERRED]**. See section 12 for the strategy.
- Bracket quoting `[ ]` works on SQLite, as do `"` and backtick **[TEST]**, so `LeftQuote=[`/`RightQuote=]` is fine.

### 9.2 MS Access `.accdb` **[TEST: ACE 12.0 and 16.0, 64-bit]**
```
Provider=Microsoft.ACE.OLEDB.12.0;Data Source=C:\PartForgeLib\PartForge.accdb;Persist Security Info=False
Provider=Microsoft.ACE.OLEDB.16.0;Data Source=C:\PartForgeLib\PartForge.accdb;Persist Security Info=False
```

Templates Altium uses for "Select Database Type" **[BIN]**:
- `Microsoft Access` → `'Provider=' + <provider> + ';Data Source=' + path + ';Persist Security Info=False'`
- `Microsoft Access 2007` → `'Provider=Microsoft.ACE.OLEDB.12.0;Data Source=' + path + …`
- `Microsoft Excel` → `… + ';Extended Properties="Excel 8.0;HDR=Yes;IMEX=1"'`
- `Microsoft Excel 2007` → `… + ';Extended Properties="Excel 12.0 Xml;HDR=Yes;IMEX=1"'`
- Sample (electronpowered) **[FILE]**: `ConnectionString=Provider=MICROSOFT.ACE.OLEDB.12.0;Data Source=…\electronpowered.xls;Extended Properties="Excel 8.0;HDR=Yes;IMEX=1"`

Access is the only backend whose DB path can be relative to the DbLib through `LibraryDatabaseType`/`LibraryDatabasePath`/`DatabasePathRelative=1`. Example for a fully movable folder **[INFERRED from electronpowered, UNVERIFIED in AD26]**:
```
ConnectionString=Provider=Microsoft.ACE.OLEDB.12.0;Data Source=C:\old\location\PartForge.accdb;Persist Security Info=False
LibraryDatabaseType=Microsoft Access 2007
LibraryDatabasePath=PartForge.accdb
DatabasePathRelative=1
```

Altium's default provider for new DbLibs is "Microsoft Office <Version> Access Database Engine OLE DB Provider" **[DOC]**.

### 9.3 PostgreSQL through "PostgreSQL Unicode(x64)" **[TEST: PostgreSQL 17.6 temporary local server + psqlODBC 17.00.0008]**
```
Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="DRIVER={PostgreSQL Unicode(x64)};SERVER=127.0.0.1;PORT=5432;DATABASE=partforge;UID=partforge_ro;PWD=<secret>;"
```

The short form `Provider=MSDASQL;Driver={PostgreSQL Unicode(x64)};Server=…;Port=…;Database=…;Uid=…;Pwd=…;TextAsLongVarchar=0;MaxVarcharSize=4000` also works **[TEST]**.

Results:
- **`[Resistors]` gives `syntax error at or near "["` [TEST].** A PG DbLib must use `LeftQuote="`, `RightQuote="` and a Where clause like `"Part Number" = '{Part Number}'`.
- Unquoted identifiers fold to lower case. Create tables with quoted, mixed-case names to match the DbLib's quoted names.
- `TOP 1` gives a syntax error (PG uses `LIMIT`) **[TEST]**.
- Views are listed as `VIEW` **[TEST]**.
- Unicode `Ω` round-trips **[TEST]**.
- A role with only `GRANT SELECT` gets `ERROR: permission denied for table Resistors` on UPDATE **[TEST]**. This gives true read-only access for Altium users.
- Type mapping with default driver settings:
  - `varchar(n)` → `adVarWChar(n)`; `text` → `adVarWChar(8190)`.
  - With `MaxVarcharSize=4000`: `text` → `adVarWChar(4000)` **[TEST]**.
- Relevant psqlODBC keywords **[DOC odbc.postgresql.org]**: `TextAsLongVarchar` (B7), `UnknownsAsLongVarchar` (B8), `MaxVarcharSize` (B0), `MaxLongVarcharSize` (B1), `BoolsAsChar` (B9), `UseDeclareFetch` (B6), `ShowSystemTables` (A5), `ReadOnly` (A0), `ConnSettings` (A6), `SSLmode`.
- Altium KB: to hide system tables, disable "Show system tables" in the DSN. To restrict to a schema, use `SET search_path To myschema,public;` (put it in ConnSettings) **[DOC KB]**.

### 9.4 SQL Server (**[UNVERIFIED]**: no server available. Driver loading only was **[TEST]**ed: MSOLEDBSQL tried TCP and timed out.)
```
Provider=MSOLEDBSQL;Server=tcp:SQLHOST,1433;Database=PartForge;Integrated Security=SSPI;
Provider=MSOLEDBSQL;Server=tcp:SQLHOST,1433;Database=PartForge;UID=altium_ro;PWD=<secret>;
Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="Driver={ODBC Driver 18 for SQL Server};Server=tcp:SQLHOST,1433;Database=PartForge;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
```

Celestial (real, credentials redacted) **[FILE]**:
```
Provider=SQLNCLI11.1; User ID=<redacted>; Password="<redacted>"; Initial Catalog=altium_library; Data Source=<host>,1433; Initial File Name=""; Server SPN=""
```

- `MSOLEDBSQL19` enforces encryption by default and needs a trusted certificate or `Trust Server Certificate=True` **[UNVERIFIED]**.
- SQL Server accepts `[ ]`.
- `MSOLEDBSQL` is not in AD's provider list (see 9.1), but `sqloledb`/`SQLNCLI` are. The effect on dialect detection is **[UNVERIFIED]**.

### 9.5 32-bit vs 64-bit **[DOC][TEST]**

- "With the release of version 18.0, Altium Designer became 64-bit. To link from design components to a database in a 64-bit version of Altium Designer, the backend database engine must also be 64-bit."
- "Note that certain connection errors, such as incorrect syntax in the Provider details of the Connection String, can result in the wrong database engine being called and the error dialog shown above appearing".
- ODBC drivers and DSNs must be the **64-bit** ones, created in `C:\Windows\System32\odbcad32.exe`, not SysWOW64. This PC has both 32-bit and 64-bit entries; for example `PostgreSQL Unicode` exists in both.
- Access Database Engine 2016 x64 cannot officially coexist with 32-bit Office. Altium's workaround applies only to Office 2007.

## 10. Pitfalls checklist (with evidence)

1. **TEXT vs VARCHAR in SQLite [TEST].**
   - Declared `TEXT` → `adLongVarWChar` (memo, DefinedSize 65536).
   - `VARCHAR(n)` → `adVarWChar(n)`, including `VARCHAR(4000)`.
   - Untyped and `VARCHAR` without length → `adVarWChar(255)`.
   - `VARCHAR(65535)` → long.
   - In views, a column keeps its base declared type; expressions and `CAST(... AS VARCHAR(50))` become `adVarWChar(255)`.
   - Memo or long fields are a classic problem in Delphi/ADO grids and in DISTINCT/ORDER BY on Access. **Declare every Altium-visible column as `VARCHAR(n)`, n ≤ 4000** (Celestial: all `varchar(255)`).
2. **Store display values as text [UNVERIFIED].** REAL/INTEGER columns become parameter strings through the Delphi/ADO conversion, possibly with a locale decimal comma on German Windows. Keep numeric helper columns for sorting, but map them to `[None]`.
3. **Quoting.** SQLite accepts `[ ]`. PostgreSQL needs `"`. Names with spaces need `QuoteTableNames=1` **[TEST][DOC]**.
4. **`TOP 1` [BIN][TEST].**
   - AD contains the strings `' TOP 1'`, `'Select'`, `' * From '` and "Could not get column list for table … Please check your quote and connection settings and try again."
   - SQLite and PG reject `TOP 1`. SQLite's error through MSDASQL is the misleading "Der ODBC-Treiber unterstützt die angeforderten Eigenschaften nicht".
   - There are no LIMIT/ROWNUM strings. `TOP` is presumably added only for Access/SQL Server providers **[INFERRED]**, but this must be **tested in AD26 with SQLite**.
5. **`UNION ALL (` [BIN][TEST].** AD contains the string `' UNION ALL ('` (field `FUnionFieldNames`). SQLite rejects a parenthesised compound member (`near "(": syntax error`). The Altium feature that uses it is unknown **[UNVERIFIED]**. Test the DbLib-wide search, Update Parameters From Database and Offline IntLib Maker with SQLite.
6. **Relative DB path** in an ODBC connection string depends on CWD [TEST]. See section 12.
7. **Silent empty DB** without `NoCreat=1` [TEST].
8. **Concurrency on SQLite [TEST]:**
   - While an ADO/ODBC reader is open (static client cursor, server forward-only cursor, even `StepAPI=1` with 20k unread rows), an external Python writer committed in 0.01 s in both `DELETE` and `WAL` journal modes.
   - An open ADO connection sees external commits **immediately** (count +1 on the same connection, both modes). So PartForge can write while Altium is open; Altium needs only a panel refresh, not a reconnect **[INFERRED]**.
   - Keep write transactions short. The default ODBC busy `Timeout` is **100 s**, so a long exclusive lock would freeze Altium.
   - Use **WAL** locally. SQLite docs: "PRAGMA journal_mode=WAL is persistent", but "All processes using a database must be on the same host computer; WAL does not work over a network filesystem" and "It is not possible to open read-only WAL databases" unless -shm/-wal can be created **[DOC sqlite.org]**.
   - Do **not** put `JournalMode=` in the DbLib connection string. It would change the mode for all connections.
9. **Never replace the DB file while it is open [TEST].** While an ADO connection is open, `os.replace(new, db)` fails with `PermissionError(13)`.
   - The handle stays open until the COM objects are released; after an explicit release, the replace worked.
   - PDXpert reports that "Altium Designer connects to the SQLite database using an exclusive file lock, which blocks PDXpert's updates to the SQLite database". My tests show **SQL-level** writes are not blocked (item 8). The PDXpert observation fits **file-level replacement** being blocked [INFERRED].
   - Update in place with SQL transactions. Copy or move a WAL DB only when it is closed or checkpointed; the `-wal` file belongs to the DB.
10. **Views are read-only in SQLite [TEST]:** `UPDATE` on a view through ADO fails with "cannot modify … because it is a view". Use them to stop users editing in Altium's Table Browser. Altium's *Add New Component*, *Edit*, *Delete* and *Edit Supplier Links* need real tables:
    - `ALTER TABLE … ADD [Supplier 2] VARCHAR(255)` works through ADO on SQLite [TEST].
    - Client-cursor recordset edits work on SQLite tables with a primary key [TEST].
    - Excel: "commands for adding, modifying and removing components will not be available" [DOC].
11. **Read-only access:** use a SELECT-only role in PG/SQL Server [TEST for PG], views in SQLite, or psqlODBC `ReadOnly=1`.
12. **Network shares.**
    - The DbLib itself works over UNC: `GetAvailableDBLibDocAtPath` worked over a network share [PRIOR].
    - SQLite on SMB: use rollback (`DELETE`) mode and a single writer, or better a server DB (PG) for multi-user use.
    - Excel needs to be opened before Altium for write access (electronpowered README) [FILE].
    - Excel has a limit of 64 sheets ("the number of sheets that can connect is limited to 64") [DOC].
13. **Encoding of the DbLib**: ANSI (see section 1). Avoid `|`, `=`, `.`, `[`, `]`, `{`, `}`, `$` and quotes in table and column names, because they break `Options=`, Where clauses and Excel naming [INFERRED].
14. **Schema drift:** AD shows "The database underlying this library has changed. Links to tables and columns which no longer exist have been removed." [BIN]. Altium also re-saves UI state (`LastFocusedTable`, `BrowserOrder_*`, `ViewMode`). PartForge should regenerate the DbLib after schema changes and accept Altium's re-saves.
15. **Duplicate keys across tables** break Update Parameters From Database (section 6).
16. **System tables** show up in table lists (Celestial `sysdiagrams`; PG KB). Disable them, or hide them through the driver or role.

## 11. Best-practice schema conventions

### 11.1 Celestial Altium Library
Sources: the two local DbLibs **[FILE]** and the community SQLite snapshot of the MSSQL views, `celestial-2020-12-15.sqlite3` (132 tables, 149,624 rows) **[FILE]**.

- **One table (MSSQL view) per category, with human-readable names** such as `Capacitors - Ceramic - 0603`, `Resistors - Surface Mount - 0603` and `Microcontrollers - ARM`. In V2: 311 tables or views, 164 enabled.
- **Columns present in all 132 tables:**
  - `Part Number` (= the **MPN**, the key), `Manufacturer`, `Description`, `Comment`, `Value`
  - `Library Ref`, `Library Path`, `Footprint Ref`, `Footprint Path`, `Footprint Ref 2`, `Footprint Path 2`, `Footprint Ref 3`, `Footprint Path 3`
  - `ComponentLink1..6Description`, `ComponentLink1..6URL`
  - `Supplier 1..6`, `Supplier Part Number 1..6`
  - `Price`, `Minimum Order`, `Packaging`, `Part Status`, `Lifecycle Status`, `Series`, `Device Package`, `Type`, `LastUpdated`
- **Category-specific columns** use distributor names: `Capacitance`, `Tolerance`, `Voltage - Rated`, `Temperature Coefficient`, `Package / Case`, `Mounting Type`, `Operating Temperature`, and so on.
- All columns are `varchar(255)`.
- Sample row (0201 cap):
  - `Comment='=Value'`, `Value='18pF'`, `Library Ref='CAPACITOR'`, `Library Path='symbols/Passives/SCH - PASSIVES - CAPACITOR.SCHLIB'`
  - `Footprint Ref='CAP 01005_0402'`, `Footprint Path='footprints/Capacitor - MLCC/PCB - CAPACITOR - MLCC - CAP 01005_0402.PCBLIB'`
  - `ComponentLink1Description='Datasheet'`, `Supplier 1='DigiKey'`, `Supplier Part Number 1='1253-CM02CG180J25AHCT-ND'`
- **Generic symbols** are shared by thousands of rows: `RESISTOR` (60,093 rows), `POLARISED CAPACITOR` (30,478), `CAPACITOR` (30,091). This is the "many database records-to-one Altium Designer component" model **[DOC]**.
- **One symbol or footprint per file**, in category subfolders: `symbols/<Category>/SCH - <CAT> - <NAME>.SchLib` and `footprints/<Category>/PCB - <CAT> - <NAME>.PcbLib`. There are 7,812 SchLib and 2,155 PcbLib files.
- DbLib mapping: key `Part Number` (FieldType=0); bracket mappings for Library Ref/Path, Footprint Ref/Path 1..3 and Description; `Comment`, plus `Value`/`Capacitance`/… with `VisibleOnAdd=True`. Everything else uses default same-name mapping.

### 11.2 electronpowered
- Excel workbook, one sheet per category (`capacitors$`, `connectors$`, `inductors$`, `integrated$`, `misc$`, `resistors$`).
- Columns: `Part Number`, `Description`, `Library Path`, `Library Ref`, `Footprint Path`, `Footprint Ref`, `Manufacturer`, `Package`, `Value`.
- One SchLib and one PcbLib for everything.
- `Part Number` is an internal descriptive key, e.g. `RES-SM-0603-33K` (README) **[FILE]**.

### 11.3 Altium itself
- When the DbLib editor creates a table, it issues `CREATE TABLE <name> ([Part Number] <DefaultColumnType> CONSTRAINT PrimaryKey PRIMARY KEY, [Library Ref] …, [Library Path] …)`. This is reconstructed from the adjacent string fragments `'CREATE TABLE '`, `' ('`, `'Part Number'`, `' CONSTRAINT PrimaryKey PRIMARY KEY,'`, `'Library Ref'`, `','`, `'Library Path'`, `')'` **[BIN]**. It is Altium's minimal canonical table.
- The IntLib-to-DbLib wizard takes `Part Number` from the component's Design Item ID **[DOC]**.

### 11.4 Recommendations for PartForge
- Use one real table per category, named for display (e.g. `Resistors`, `Capacitors`, or `Resistors - 0603`).
- Key column `Part Number`, globally unique. Use either the MPN, as Celestial does, or an internal PN scheme; be consistent.
- **Standard columns:**
  - `Part Number`, `Library Ref`, `Library Path`, `Footprint Ref`, `Footprint Path`, `Footprint Ref 2`/`Footprint Path 2` (alternative density, e.g. IPC-7351B `…N`/`…L`/`…M`)
  - `Comment` (`=Value` for passives, `=Part Number` for ICs), `Value`, `Description`
  - `Manufacturer`, `Manufacturer Part Number`, or the BOM-reserved `Manufacturer 1`/`Manufacturer Part Number 1`
  - `Supplier 1`/`Supplier Part Number 1` …
  - `ComponentLink1Description='Datasheet'`, `ComponentLink1URL`
- Add category parameters such as `Resistance`, `Tolerance`, `Power`, `Voltage`, `Dielectric`, `Package`, `TCR`.
- Map internal or helper columns to empty `ParameterName` (`[None]`).
- All `VARCHAR(n)`, UTF-8 data. Path values relative to the DbLib.
- Library Ref naming: generic, function-based symbols (`RES`, `CAP`, `CAP-POL`, `IND`). Footprint Ref: IPC-7351B names (`RESC1608X55N`, `CAPC1608X90N`).

## 12. Example: SQLite with Resistors and Capacitors, relative library paths **[TEST at the ADO level]**

The example was generated by `scripts/make_example.py` and validated by `scripts/validate_dblib.ps1`, both in the working folder. The tested copy is in `example/PartForgeLib/`.

```
PartForgeLib/                      <- move this whole folder
  PartForge.DbLib
  PartForge.sqlite                 (WAL mode; -wal/-shm appear while in use)
  SchLib/Passives.SchLib           (symbols RES, CAP)            <- files not created by this research
  PcbLib/Chip_Passives.PcbLib      (RESC1608X55N, RESC1608X55L, CAPC1608X90N)
```

### 12.1 SQL schema (both tables share the first and last column blocks)
```sql
CREATE TABLE "Resistors" (
  "Part Number"               VARCHAR(64)  NOT NULL PRIMARY KEY,
  "Library Ref"               VARCHAR(255) NOT NULL,
  "Library Path"              VARCHAR(255),
  "Footprint Ref"             VARCHAR(255),
  "Footprint Path"            VARCHAR(255),
  "Footprint Ref 2"           VARCHAR(255),
  "Footprint Path 2"          VARCHAR(255),
  "Comment"                   VARCHAR(255),
  "Value"                     VARCHAR(64),
  "Description"               VARCHAR(255),
  "Resistance"                VARCHAR(32),
  "Tolerance"                 VARCHAR(16),
  "Power"                     VARCHAR(16),
  "TCR"                       VARCHAR(32),
  "Package"                   VARCHAR(32),
  "Manufacturer"              VARCHAR(128),
  "Manufacturer Part Number"  VARCHAR(128),
  "Supplier 1"                VARCHAR(64),
  "Supplier Part Number 1"    VARCHAR(64),
  "ComponentLink1Description" VARCHAR(64),
  "ComponentLink1URL"         VARCHAR(1024),
  "Notes"                     VARCHAR(1024)
);
-- "Capacitors": same, with "Capacitance","Tolerance","Voltage","Dielectric","Package" instead of the 5 resistor columns.
INSERT INTO "Resistors" VALUES ('RC0603FR-0710KL','RES','SchLib\Passives.SchLib','RESC1608X55N','PcbLib\Chip_Passives.PcbLib',
  'RESC1608X55L','PcbLib\Chip_Passives.PcbLib','=Value','10k','RES SMD 10kΩ ±1% 0.1W 0603',
  '10kΩ','±1%','0.1W','±100ppm/K','0603','YAGEO','RC0603FR-0710KL','','','Datasheet','https://…/PYu-RC_Group_51_RoHS_L_12.pdf','example row');
```

### 12.2 `PartForge.DbLib`

Write it in cp1252 with CRLF endings. Byte for byte this is the generated file, except that the absolute DB path is shortened to `C:\PartForgeLib`:
```ini
[OutputDatabaseLinkFile]
Version=1.1
[DatabaseLinks]
ConnectionString=Provider=MSDASQL.1;Persist Security Info=False;Extended Properties="Driver={SQLite3 ODBC Driver};Database=C:\PartForgeLib\PartForge.sqlite;NoCreat=1;"
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
LibraryDatabasePath=
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
UserWhereText=[Part Number] = '{Part Number}'
[Table2]
SchemaName=
TableName=Capacitors
Enabled=True
UserWhere=0
UserWhereText=[Part Number] = '{Part Number}'
[FieldMap1]
Options=FieldName=Resistors.Part Number|TableNameOnly=Resistors|FieldNameOnly=Part Number|FieldType=0|ParameterName=Part Number|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap2]
Options=FieldName=Resistors.Library Ref|TableNameOnly=Resistors|FieldNameOnly=Library Ref|FieldType=1|ParameterName=[Library Ref]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap3]
Options=FieldName=Resistors.Library Path|TableNameOnly=Resistors|FieldNameOnly=Library Path|FieldType=1|ParameterName=[Library Path]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap4]
Options=FieldName=Resistors.Footprint Ref|TableNameOnly=Resistors|FieldNameOnly=Footprint Ref|FieldType=1|ParameterName=[Footprint Ref]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap5]
Options=FieldName=Resistors.Footprint Path|TableNameOnly=Resistors|FieldNameOnly=Footprint Path|FieldType=1|ParameterName=[Footprint Path]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap6]
Options=FieldName=Resistors.Footprint Ref 2|TableNameOnly=Resistors|FieldNameOnly=Footprint Ref 2|FieldType=1|ParameterName=[Footprint Ref 2]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap7]
Options=FieldName=Resistors.Footprint Path 2|TableNameOnly=Resistors|FieldNameOnly=Footprint Path 2|FieldType=1|ParameterName=[Footprint Path 2]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap8]
Options=FieldName=Resistors.Description|TableNameOnly=Resistors|FieldNameOnly=Description|FieldType=1|ParameterName=[Description]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap9]
Options=FieldName=Resistors.Comment|TableNameOnly=Resistors|FieldNameOnly=Comment|FieldType=1|ParameterName=Comment|VisibleOnAdd=True|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap10]
Options=FieldName=Resistors.Notes|TableNameOnly=Resistors|FieldNameOnly=Notes|FieldType=1|ParameterName=|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap11]
Options=FieldName=Capacitors.Part Number|TableNameOnly=Capacitors|FieldNameOnly=Part Number|FieldType=0|ParameterName=Part Number|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap12]
Options=FieldName=Capacitors.Library Ref|TableNameOnly=Capacitors|FieldNameOnly=Library Ref|FieldType=1|ParameterName=[Library Ref]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap13]
Options=FieldName=Capacitors.Library Path|TableNameOnly=Capacitors|FieldNameOnly=Library Path|FieldType=1|ParameterName=[Library Path]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap14]
Options=FieldName=Capacitors.Footprint Ref|TableNameOnly=Capacitors|FieldNameOnly=Footprint Ref|FieldType=1|ParameterName=[Footprint Ref]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap15]
Options=FieldName=Capacitors.Footprint Path|TableNameOnly=Capacitors|FieldNameOnly=Footprint Path|FieldType=1|ParameterName=[Footprint Path]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap16]
Options=FieldName=Capacitors.Footprint Ref 2|TableNameOnly=Capacitors|FieldNameOnly=Footprint Ref 2|FieldType=1|ParameterName=[Footprint Ref 2]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap17]
Options=FieldName=Capacitors.Footprint Path 2|TableNameOnly=Capacitors|FieldNameOnly=Footprint Path 2|FieldType=1|ParameterName=[Footprint Path 2]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap18]
Options=FieldName=Capacitors.Description|TableNameOnly=Capacitors|FieldNameOnly=Description|FieldType=1|ParameterName=[Description]|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap19]
Options=FieldName=Capacitors.Comment|TableNameOnly=Capacitors|FieldNameOnly=Comment|FieldType=1|ParameterName=Comment|VisibleOnAdd=True|AddMode=0|RemoveMode=0|UpdateMode=0
[FieldMap20]
Options=FieldName=Capacitors.Notes|TableNameOnly=Capacitors|FieldNameOnly=Notes|FieldType=1|ParameterName=|VisibleOnAdd=False|AddMode=0|RemoveMode=0|UpdateMode=0
```

Not mapped explicitly, and therefore same-name parameters: `Value`, `Resistance`/`Capacitance`, `Tolerance`, `Power`/`Voltage`, `TCR`/`Dielectric`, `Package`, `Manufacturer`, `Manufacturer Part Number`, `Supplier 1`, `Supplier Part Number 1`, `ComponentLink1Description`, `ComponentLink1URL`.

The global `AddMode=3` ("Add only if not blank") keeps empty supplier fields off the part.

**Validation results [TEST]**, using the ConnectionString read from this file:
- Connected (SQLite 3.43.2); both tables are listed.
- All 22 columns are `adVarWChar` (type 202).
- Key lookup `SELECT * FROM [Resistors] WHERE [Part Number] = 'RC0603FR-0710KL'` finds the row (`Comment==Value`, `Value=10k`).
- `LIKE '%0603%'` and `SELECT DISTINCT [Value] … ORDER BY` work.
- `SchLib\Passives.SchLib` resolves against the DbLib folder.

**Not yet verified inside Altium**: placement, the Components panel, Update Parameters From Database and the Comment rendering. See section 13.

### 12.3 What is movable

- `Library Path` / `Footprint Path` are relative to the DbLib, so the folder can move **[DOC + Celestial evidence]**.
- The SQLite path inside an ODBC `ConnectionString` **cannot** be relative to the DbLib. It is relative to Altium's CWD [TEST]. Options:
  - (a) **Recommended.** PartForge rewrites `Database=` to `<DbLib folder>\PartForge.sqlite` at startup and when it detects a move. `scripts/relocate_dblib.py` does this: it preserves CRLF and cp1252 [TEST: a moved copy reconnected]. Altium must reload or refresh the DbLib afterwards **[UNVERIFIED]**.
  - (b) An ODBC **user DSN** (HKCU, no admin rights; PartForge maintains its `Database=`). The DbLib then uses `Provider=MSDASQL.1;Persist Security Info=False;Data Source=PartForge` and contains no path. The DSN form is [TEST]ed with the existing system DSN plus an override.
  - (c) An Access `.accdb` backend with `DatabasePathRelative=1` (section 9.2) **[UNVERIFIED in AD26]**.

Core of `relocate_dblib.py`:
```python
raw = dblib.read_bytes().decode("cp1252")
db_abs = str((dblib.parent / db_file).resolve())
def fix_line(m):
    return re.sub(r'(Database=)[^;"\r\n]*', lambda mm: mm.group(1) + db_abs, m.group(0), count=1)
new = re.sub(r"^ConnectionString=.*$", fix_line, raw, count=1, flags=re.M)
dblib.write_bytes(new.encode("cp1252"))
```

## 13. Acceptance checks to run in Altium 26 (implementation phase, through the Altium MCP)

1. Install `example/PartForgeLib/PartForge.DbLib` and confirm it connects. With SQLite, check for **no** "Could not get column list" error (the `TOP 1` question, section 10 item 4).
2. Components panel:
   - Tables appear as `PartForge.DbLib - Resistors`.
   - The search box works across all fields.
   - The "Database Components" search works (the `UNION ALL (` question).
3. Place `RC0603FR-0710KL` and check:
   - symbol `RES` taken from `SchLib\Passives.SchLib` (relative path);
   - footprint `RESC1608X55N` is current and `RESC1608X55L` is listed as an alternative;
   - Comment shows `10k` (`=Value`);
   - parameters `Value`/`Tolerance`/… are hidden and `Notes` is absent;
   - `DesignItemID=RC0603FR-0710KL`;
   - ComponentLink1 appears under right-click » References.
4. Change `Tolerance` in SQLite while Altium is open, run *Tools » Update Parameters From Database*, and confirm the change is proposed.
5. Save the DbLib from Altium's editor and diff it against the generated file. This confirms the FieldMap write rule (section 5.2), `[None]` as an empty ParameterName, the `LibrarySearchPath` multi-entry separator (add two paths), and the file encoding.
6. PostgreSQL variant: same checks with `LeftQuote="`/`RightQuote="`.

## 14. `.SvnDbLib` and `.DbLink` (brief)

- **.SvnDbLib** = a DbLib whose symbol and footprint libraries live in Subversion.
  - It uses the same INI sections. `[DatabaseLinks]` adds `SVNRepositoryURL` and `FileRepositoryIsRelative` and also reads and writes `LibrarySearchPath` **[BIN]**. The Models Location (Symbols/Footprints base directories) are probably stored there **[INFERRED]**.
  - Connection methods: `file`, `http`, `https`, `svn` **[DOC]**.
  - Paths in the DB are relative to the repo root, a file name only, or a full URL.
  - "each symbol and model must be stored in its own library file" **[DOC]**.
  - Symbols are cached locally. Search order for a name-only entry: "the system will initially look for the first library named like the symbol or footprint itself" **[DOC]**.
- **.DbLink** = Database Link file (base class `TDatabaseLinkDocument`) with the same `[OutputDatabaseLinkFile]`/`[DatabaseLinks]`/`[TableN]`/`[FieldMapN]` structure, but without the DbLib-only keys `LibrarySearchPath`, `SearchSubDirectories` and `OrcadMultiValueDelimiter` **[BIN, INFERRED]**.
  - It does not create components. It links **existing** SchLib or placed components to records by key for *Update Parameters From Database*: "the model and parameter information for the component must be predefined as part of the Altium Designer library component".
  - It must be added to the project or LibPkg and appears under `Settings\Database Link Files` **[DOC]**.

## 15. Sources

- Altium, "Creating & Defining the Database Library", https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries/creating-defining (updated 2025-11-18). Local text: `web/creating-defining.txt`.
- Altium, "Database Libraries", https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries
- Altium, "Using Database Libraries with 32-bit and 64-bit Altium Designer on the Same Computer", https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries/using-32-64-bit-altium-designer-same-computer
- Altium, "Modifying a Database Table", https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries/modifying-database-table
- Altium, "Database Library Migration Tools", https://www.altium.com/documentation/altium-designer/components-libraries/database-libraries/migration-tools
- Altium, "Searching for Components in Database & File-based Libraries", https://www.altium.com/documentation/altium-designer/schematic/components-file-based-database-libraries
- Altium, "Updating Components from Database and File-based Libraries", https://www.altium.com/documentation/altium-designer/schematic/updating-components-database-file-based-libraries
- Altium, Database Options dialog, https://www.altium.com/documentation/altium-nexus/workspacemanager-dlg-databaselinksoptionsformdatabase-options-ad
- Altium, "Linking to Supply Chain Data…", https://www.altium.com/documentation/altium-designer/components-libraries/linking-supply-chain-data-database-file-based , and the AD18 archive https://web.archive.org/web/2019id_/https://www.altium.com/documentation/18.0/display/ADES/((Linking+to+Supplier+Data))_AD
- Altium KB, "Manufacturer Parameters Overwritten by Part Choices in Exported BOM", https://www.altium.com/documentation/knowledge-base/altium-designer/manufacturer-parameters-overwritten-by-part-choices-in-exported-bom
- Altium KB, "Configuring SQL Database Library to display only relevant tables", https://www.altium.com/documentation/knowledge-base/altium-designer/configuring-sql-database-library-to-display-only-relevant-tables
- Altium KB, "Control component parameter appearance in schematic", https://www.altium.com/documentation/knowledge-base/altium-designer/control-component-parameter-appearance-in-schematic
- Altium, "Define Manufacturer Link Fields" dialog, https://www.altium.com/documentation/altium-nexus/activebom-dlg-manufacturerlinkfieldsdialogdefine-manufacturer-link-fields-ad
- SQLite ODBC driver README, http://www.ch-werner.de/sqliteodbc/README ; connection string, https://www.connectionstrings.com/sqlite3-odbc-driver/
- SQLite WAL, https://www.sqlite.org/wal.html
- psqlODBC configuration options, https://odbc.postgresql.org/docs/config-opt.html
- PDXpert application note (Altium + SQLite/LocalDB views), https://www.buyplm.com/application-notes/pdxpert-plm-integration-altium-designer.aspx
- Celestial offline DB issue #83, https://hub.allspice.io/AllSpice-Demos/Altium-Celestial-library/issues/83 ; snapshot https://github.com/issus/altium-library/files/5696845/celestial-2020-12-15.sqlite3.zip (extracted copy: `celestial_x/celestial.sqlite3` in the working folder)
- Local files (read-only): `C:/PartForge-Examples/Capacitor.DbLib`, `C:/PartForge-Examples/libraries/altium-library-master/electronpowered.dblib` + README, `C:/PartForge-Examples/libraries/Celestial_Altium_Library/*.DbLib` + README + BOM template, `<altium-mcp-checkout>/dev/DBLIB_FINDINGS.md`, `make_part_spec.py`
- Altium binaries: `C:/Program Files/Altium/AD22/System/WorkspaceManager.dll` and `AdvSch.dll` (AD 26.10.1.5). String dumps are in `out/*.strings.txt` in the working folder.
