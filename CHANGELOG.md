# Changelog

English · [Deutsch](CHANGELOG.de.md)

## Unreleased

### Added

- **Stop script** (*Altium* page, offered whenever a PartForge script hangs in Altium): ends the script paused in
  Altium's debugger through Altium's own `EditScript:Stop` command – no keyboard or window focus needed – and checks
  that scripts run again. Ctrl+F3 only works while the script editor is Altium's active document, so the hints now
  point to this action.

### Fixed

- The Altium bridge reads Altium's response files on Windows systems with the "Beta: Use Unicode UTF-8" code page,
  where Altium writes them with a UTF-8 byte-order mark. Previously every bridge call failed there with
  "unknown format".

## 1.0.0b1 – 2026-10-11

First public beta (GitHub tag: `v1.0.0-beta.1`).
PartForge was developed largely through vibe coding with AI assistance and is in an early beta stage.
Review generated parts, symbols and footprints before use, and back up your libraries regularly.

### Added

- **Edit in Altium** (symbol or footprint detail view): opens the SchLib/PcbLib in Altium Designer and shows the
  component there. Saving in Altium updates PartForge automatically: the preview, pins/pads, component height and
  3D model come from the saved file, with the source shown as “Edited in Altium”. Changes to other components in
  the same file, renamed components and new components are detected too; saving without changes is ignored.
  “Edit” and “Regenerate” ask before replacing an Altium-edited version. Monitoring survives a restart and ends
  when “Stop editing” is selected, when Altium exits, or after 12 hours without a save.
- **English and German** (*Settings › General › Profile and appearance › Language*): the interface, desktop
  dialogs, messages and number formats use the selected language. English is the default, including for existing
  installations after updating, until German is selected and saved.
- **STEP models in the 3D preview**: shows a footprint's STEP models with their Altium placement, including
  embedded models in imported libraries that were not extracted during import. Each model can be downloaded.
- **Library import** (new page, Alt+9): import symbols and footprints from existing Altium libraries, including
  recursive folders, SchLib/PcbLib files, integrated libraries (IntLib), library packages (LibPkg) and ZIP archives.
  Each component has a preview and a name status (new, already imported, name taken or duplicate). Files are
  copied unchanged into folders under `Symbols\Import` / `Footprints\Import`. Imported symbols can also produce
  a table for the table import (“Create parts…”).
- **Batch editing** (new page, Alt+0): apply a house style to imported symbols and footprints, including fonts,
  IC symbol pin lengths, designator prefixes, colors, layer mapping, line widths, `.Designator`/`.Comment`
  fonts, missing text, component center and layer headers. Roles of external mechanical layers are detected and
  can be reassigned. Preview before applying; records outside the selected changes are retained, every file is
  backed up, and the most recent batch edit can be undone.
- **House style from an example library** (*Settings › House style*): copy fonts, pin lengths, colors, layers,
  line widths and text from a reference SchLib, PcbLib, IntLib, ZIP archive or folder.
- **Layer set** (*Settings › House style › Layers*): each footprint library receives its own Altium layer set,
  from the mapped “Component Layers” or a `.layerset` file; it can be activated automatically on opening.
- House style: TrueType fonts for footprint `.Designator`/`.Comment` text and symbol pin names/numbers
  (Altium “Custom Font”), registered in the SchLib font table.
- Datasheet import: **Save individually** saves only a proposed symbol (SchLib) or footprint (PcbLib), without a
  part record, such as the symbol of a datasheet with no package drawing.
- Datasheet import: **Use package from another datasheet** imports dimensions, recommended land patterns,
  exposed-pad numbers and terminal arrangements from a separate manufacturer package drawing (for example,
  TI “RGY0019B”). Matching drawings are suggested, the source is shown and the selection can be cleared.
  This also works from the package drawing (“Give to a part…”) and the datasheet list.
- Documents containing only a package drawing are recognized and have a review view with **Save footprint**.
- QFN/DFN footprint generator: irregular packages with **leads per side**, a separate **top/bottom pitch**,
  **pin 1 on the top side** and **missing leads** (for example, TI VQFN-19 RGY). Datasheet import exposes these
  settings as the package's “Terminal layout”.
- Manufacturer recommendations with a separate **top/bottom row spacing** for rectangular QFN/QFP packages.
- Datasheet import: Claude reads QFN/QFP **terminal layouts**, including lead counts on the pin-1 side and adjacent
  sides, pin-1 position, differing pitches and missing positions. Packages such as TI UQFN-10 RSW0010A
  (two leads on the left/right and three on the top/bottom) can be generated without manual correction.
  If the terminal layout is missing for a lead count not divisible by four, Claude checks rendered drawing
  pages. Older analyses still need the layout entered in the review view or a new analysis.

### Changed

- “Browse…” now opens file dialogs for external libraries, `.stackup` files and `X2.EXE`, where the file filter
  previously contained characters rejected by the desktop window.
- Writing to a library preserves all other components byte for byte, including Altium-saved components with
  TrueType text, Mechanical 17–32 layers, embedded fonts and pin fonts. Previously the writer replaced those
  records with its own representation.
- Footprints on Mechanical 17–32 are read with their correct layer (previously “Mechanical 16”). TrueType text
  is retained when reading and writing.
- A document with a package drawing but no part is no longer an error: it incurs no paid follow-up check, and
  Claude does not invent a placeholder part.
- A rectangular QFN manufacturer recommendation without top/bottom row spacing is rejected instead of placing
  the end-side leads at the wrong spacing.
- The acceptance bar labels invalid symbols/footprints as “invalid” rather than “present”; reasons no longer
  repeat the package name.
- Datasheet import no longer adds a default exposed pad to QFN/DFN packages without one. Previously this could
  also make pad calculation fail for small packages such as the 1.4 × 1.8 mm UQFN-10.

### Known limitations

- This is an early beta developed largely through vibe coding. Generated electrical and mechanical data need
  review against manufacturer documentation before use. Back up existing libraries before importing or editing.
- Windows 10/11 is the supported desktop platform. Altium integration has been tested with Altium Designer 26.10;
  other versions and configurations may behave differently.
- AI datasheet extraction can miss or misinterpret values. It requires the user's Claude API key and can incur
  charges; sending a datasheet for AI analysis sends it to the Claude API.
- XLSX export of very large tables is slow (about 6.5 seconds for 20,000 rows); CSV is much faster.
- Saving to very large existing PcbLib files can take several seconds, as every change rewrites the complete file.
- Automatic backups are not compressed; each occupies approximately as much space as the database.
- The Murata GRM series catalog has not been checked against manufacturer data. Verify part numbers before ordering.
- Altium's Components panel and “Update Parameters From Database” dialog are not covered by automated tests.
  DbLib generation, ODBC access and component resolution via “Check in Altium” are covered.
- Packaged `PartForge.exe` builds are not signed; Windows SmartScreen may show a warning on first launch.
- The altium-designer-mcp library writer (GPL-3.0) is a separate dependency and is not bundled.
- PostgreSQL multi-user operation is available only with a source installation.
- The full user manual is currently in German. The main README, release notes and application interface are
  available in English; English and German interface translations may still have gaps.

## Initial development snapshot – 2026-10-09

The first internal PartForge development snapshot: create, maintain and check database component libraries
(DbLib) for Altium Designer. Windows 10/11, tested with Altium Designer 26.10. This was not a public stable release.

### Features

#### Libraries

- A library is a self-contained, movable folder containing a SQLite database, DbLib file, SchLib/PcbLib files,
  STEP models, datasheets and backups. It can include 19 example parts with symbols and footprints.
- 19 categories (resistors, capacitors, diodes, ICs, etc.) with their own tables, fields, units and value/comment/
  description templates; custom categories, fields and part-number schemes.
- A library can be open in only one PartForge instance at a time, including across computers.
- PostgreSQL multi-user operation with a source installation.

#### Parts

- A table with value-aware search (“4k7”, “50V”), numeric comparison filters, saved views and inline editing.
  The detail panel previews the symbol, footprint and 3D model and shows the change history.
- Create parts using smart input (`220n 50V X7R 0603 10%`); bulk editing and text regeneration with undo,
  deletion with undo, and restoration from history.
- Import CSV, TSV, Excel (XLSX) and ODS files with automatic column mapping and a dry run; export CSV
  (safe for Excel) and XLSX.
- Range bounds containing ± are preserved (“2.8V to ±5.25V” → “2.8V … ±5.25V”).

#### Series wizard

- Generate entire manufacturer series in E3–E192 ranges: Vishay CRCW, Yageo RC, Panasonic ERJ, KOA, Stackpole,
  UniOhm, Bourns, KEMET, Yageo CC, Samsung CL, Murata GRM, Bourns SRR and more. Includes manufacturer
  part-number patterns and code tables, 0 Ω jumpers, matching footprints and a symbol. Custom series templates.

#### Datasheet import with Claude

- Drop a PDF into the window, download it from a URL or use “Find datasheet” to search for a manufacturer PDF.
- Claude reads manufacturer information, orderable variants, parameters, pin assignments, package dimensions
  and land patterns. The review view shows each value with its source; the proposal includes a symbol,
  a footprint (IPC-7351B, manufacturer recommendation or an existing one) and a 3D body.
- Cost estimate before analysis, per-import spending limit (default $2.00), and storage of every paid request,
  including when an import is cancelled.

#### Footprints and symbols

- IPC-7351B footprint generation (density L/N/M) for 21 package families and 189 templates, from 01005 to BGA
  and through-hole packages. Includes calculation reports, 3D bodies and STEP export; mechanical layers follow
  a custom `.stackup` template.
- About 40 standard symbols in the house style; IC symbols from pin lists with automatic arrangement and
  multi-part symbols.
- SchLib/PcbLib writing through the separately installed altium-designer-mcp library writer, without running Altium.

#### Altium

- Generate and maintain a DbLib, install/uninstall it in Altium, and refresh a running Altium instance within
  a few seconds. Open, unmodified libraries are reloaded.
- Validation report for required fields, symbols, footprints, datasheets and duplicate part numbers.
  “Check in Altium” resolves each component as Altium would when placing it.
- ODBC test and DbLib preview.

#### Interface and safeguards

- German interface with dark/light themes, command palette (Ctrl+K) and keyboard shortcuts; illustrated user
  manual (`Handbuch\Bedienung.html` in the program folder).
- Automatic backups before risky operations, library-file backup history and restoration.
- PartForge accepts connections only from the local computer (127.0.0.1), with a session token, protection from
  foreign websites and embedding. Claude API keys are encrypted using Windows DPAPI and never sent to the interface.
- A packaged application requiring no separate Python or Node.js installation, with license texts for bundled components.
