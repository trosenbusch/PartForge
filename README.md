# PartForge

**English** | [Deutsch](README.de.md)

**Create, maintain and verify database-backed component libraries for Altium Designer.**

PartForge manages an Altium database library (DbLib) together with schematic symbols,
IPC-7351B footprints and 3D models. Generate complete component series in a few clicks,
or drop a datasheet onto the application and let Claude propose a component with its
symbol and footprint. New components become available in Altium without restarting it.

> **Early beta · Vibe coding:** PartForge was developed largely through vibe coding with AI
> assistance and is in an early beta stage. Expect bugs and changes. Check generated components,
> symbols and footprints before use, and back up your libraries regularly.

The interface supports **English (default)** and **German**. Select and save your language under
*Settings → General → Language*. The selection persists across restarts.
The detailed manuals and changelog are currently in German.

![PartForge overview — German interface, dark theme](docs/screenshots/readme/uebersicht-dark.png)

## Features

| Area | What PartForge does |
| --- | --- |
| **Library** | One portable folder containing a SQLite database, DbLib, SchLib/PcbLib, 3D models, datasheets and backups. Categories have their own tables, fields with units, and templates for descriptions and comments. |
| **Components** | A table with value-aware search (`10k`, `100n`), numeric filters, inline editing, bulk updates, history and restore. Import CSV, TSV, Excel or ODS; export CSV or Excel. |
| **Series wizard** | Generate complete E-series (E3–E192) for manufacturer series from Vishay, Yageo, Panasonic, KOA, Stackpole, UniOhm, Bourns, KEMET, Samsung, Murata and others, including matching footprints. |
| **Datasheet import** | Drop a PDF or search for a datasheet. Claude proposes manufacturer information, ordering variants, parameters, pin assignments and package dimensions, along with symbols, footprints and 3D models for review. |
| **Footprint generator** | IPC-7351B footprints with L/N/M density levels for 21 package families, from 01005 to BGA and through-hole packages. Includes dimensions, calculation details, 3D bodies and STEP export. |
| **Symbol generator** | Around 40 standard symbols in a consistent library style, plus IC symbols generated from pin lists with automatic pin placement and multi-part symbols. |
| **Library import** | Import existing Altium symbols and footprints from folders, SchLib/PcbLib, IntLib, LibPkg or ZIP files. Detect naming conflicts and optionally create a component table from the symbols. Preview embedded STEP models, including those in previously imported libraries. |
| **Batch processing** | Apply your library style to imported symbols and footprints: fonts, pin lengths, prefixes, layers, line widths, text and layer sets. Includes backups and undo; learn a style from an example library. |
| **Altium integration** | Keep the DbLib current, install it in Altium, refresh components and verify them in Altium. Use your own `.stackup` template and `.layerset` layer set. |

## Installation and startup

PartForge targets **Windows 10/11**. Altium integration has been tested with **Altium Designer 26.10**.
A Claude API key is required only for AI features; API usage incurs charges on your Anthropic account.

### Packaged build

If you have a packaged build, copy the entire `PartForge` folder to a permanent location, such as
`%LOCALAPPDATA%\Programs\PartForge`, and run `PartForge.exe`. Python and Node.js are not required.
Keep the accompanying files with the executable.

The package includes its own `README.md`, the [user manual](#manuals) as `Handbuch\Bedienung.html`,
and the bundled components' licenses in `THIRD_PARTY_LICENSES.txt`.
To build a package from source, see [Development](#development).

### Run from source

Install **Python ≥ 3.11** (tested with 3.13) with the Windows installer's PATH option enabled,
and **Node.js with npm**. The current frontend requires Node.js **20.19.x or newer in the 20.x series,
or 22.12 or later**. An internet connection is needed for the first setup.

```powershell
git clone https://github.com/trosenbusch/PartForge.git
cd PartForge
.\Start-PartForge.cmd
```

You can also double-click `Start-PartForge.cmd`. It:

- creates `.venv` and installs the tested Python dependency versions from `constraints.txt`;
- builds the frontend if it is missing or older than its source files;
- checks for dependency and frontend changes on each start and updates them when necessary;
- reports setup failures with suggested fixes and attempts one repair if the environment is incomplete.

The launcher's setup messages are currently in German. For a proxy, set `HTTPS_PROXY`; for a private
Python package mirror, set `PIP_INDEX_URL`.

`Start-PartForge.cmd` always runs the source checkout. A packaged build is started with
`dist\PartForge\PartForge.exe`.

### Additional components

| Component | Purpose | Setup |
| --- | --- | --- |
| WebView2 Runtime | Desktop application window | Included with Windows 11; otherwise install the [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/). |
| SQLite3 ODBC Driver, 64-bit | Allows Altium to read the SQLite database | Install from [Christian Werner's site](http://www.ch-werner.de/sqliteodbc/). |
| Altium Designer | Use libraries, refresh and verify components | Tested with version 26.10. |
| `altium-designer-mcp.exe` | Write SchLib/PcbLib files without running Altium | Separately installed, GPL-3.0; not bundled. Download the Windows archive from the [project's releases](https://github.com/embedded-society/altium-designer-mcp/releases) and place the executable in `%LOCALAPPDATA%\Programs\altium-designer-mcp\`. For packaged builds, it can also sit beside `PartForge.exe`. Set another location under *Settings → General → Altium Designer*. |
| Claude API key | Datasheet import and search | Configure under *Settings → General → AI features*. Stored keys are encrypted with Windows DPAPI. |

## First steps

1. **Create a library.** Choose a name and folder, and leave example content enabled.
   PartForge creates the database, DbLib, symbols and footprints. The DbLib filename defaults to
   `<Library name>.DbLib` and can be changed in the creation dialog.
2. **Install it in Altium.** On the *Altium* page, choose the installation action, or add the DbLib under
   Altium's *Components → File-based Libraries Preferences*.
3. **Generate a series.** In the series wizard, choose resistors, a manufacturer series, an E-series,
   a value range and package sizes. Review the preview and generate the components.
   Missing footprints are created automatically.
4. **Import a datasheet.** Drop a PDF anywhere in the window. Review the proposed pins, package and
   footprint variant, then create the component.
5. **Place components in Altium.** They appear in the Components panel under your library's DbLib.
   PartForge can refresh Altium automatically after changes.

## Manuals

These documents are currently in German:

- **[User manual](docs/handbuch/BEDIENUNG.md)** — illustrated instructions for library creation,
  component management, series generation, datasheet import, symbols, footprints, Altium integration,
  settings, backups, keyboard shortcuts and troubleshooting. In a packaged build, open
  `Handbuch\Bedienung.html`; its images are under `Handbuch\bilder\`.
- **[Packaged-build manual](docs/handbuch/README.md)** — installation, required components, data storage,
  updates, removal and troubleshooting. This becomes the package's `README.md`.

## How PartForge works with Altium

- The SQLite database uses WAL mode. Altium reads it through ODBC while PartForge writes to it.
- Altium caches DbLib data. After changes, PartForge can close Altium's hidden DbLib document and rebuild
  the component index when new components have been added. Visible or modified documents are left open.
  Automatic refresh can be disabled under *Settings → General → Altium Designer*.
- Placed components identify their DbLib **by filename**. Keep the name chosen when creating the library,
  and avoid installing a second DbLib with that name.
- Symbols and footprints are written with the Rust library writer by default; Altium need not be running.
  Open, unmodified libraries are reloaded in Altium. Libraries with unsaved edits are not overwritten.
- Footprint layers follow your template. Defaults are Mechanical 9 Assembly, 11 Designator, 13 3D,
  15 Courtyard, 17 Component Center, 19 Value and 21 Component Outline. Layer names and types are stored
  in each PcbLib for placement in Altium.
- After uninstalling a library from Altium, Altium may retain a database handle for about a minute,
  sometimes until it is restarted. PartForge reports when this prevents moving or renaming the folder.

## PostgreSQL for multiple users — source installation only

A library can store its data on a PostgreSQL server instead of in a SQLite file.
This is configured outside the UI, and the packaged build does not include the PostgreSQL driver.
For a source installation:

1. Install the driver: `.venv\Scripts\python.exe -m pip install -e .[postgres] -c constraints.txt`.
2. In the library folder's `partforge.json`, set `db` to `"kind": "postgres"`, add
   `"postgres_url": "postgresql+psycopg://user:password@server:5432/database"`, and configure Altium's
   `"postgres_odbc": "DRIVER={PostgreSQL Unicode(x64)};SERVER=…;PORT=5432;DATABASE=…;UID=…;PWD=…"`.
   Altium requires the 64-bit psqlODBC driver.
3. Restart PartForge and open the library.

## Data and security

- Component and library data stays in your library folder. For AI datasheet import or search, the selected
  PDF pages or search request are sent to the Claude API.
- The API key is not returned to the frontend. Stored keys use Windows DPAPI under
  `%APPDATA%\PartForge\secret`, tied to the current Windows account. An optional key file must be local,
  small and contain a Claude API key. On first start, this beta also checks a legacy ExampleProject
  key-file location defined in `partforge/config.py`; any selected file can be changed or removed in settings.
- PartForge listens on `127.0.0.1` and accepts only local connections. Requests from other websites are
  rejected. Each session has a new access token that is excluded from application logs.
- Open the interface through the desktop window, a directly entered address or a bookmark. Navigation
  initiated by another website shows a confirmation page. Other websites cannot embed the application,
  and URLs cannot trigger actions such as rebuilding a DbLib or installing it in Altium.
- Configured Altium and library-writer executables must be local files. Network and device paths are rejected.
- CSV exports prefix values that could become spreadsheet formulas with an apostrophe; the importer removes
  that prefix. XLSX exports write these values as text.
- Before operations such as deleting categories or many components, imports or restores, PartForge creates
  a backup under `Backups\`. Library-file backups are kept under `Backups\lib\`.

Data stored outside library folders:

| Location | Contents |
| --- | --- |
| `%APPDATA%\PartForge` — roaming user profile | `settings.json`, recent library paths, encrypted keys under `secret\`, and recent datasheet search costs in `ai\search-costs.json`. |
| `%LOCALAPPDATA%\PartForge` — this computer only | Size-limited logs in `logs\partforge.log`, datasheet page-image cache (up to 512 MB), unpacked library-import archives (removed after two days), desktop WebView profile, temporary files and Altium bridge exchange files. |
| Altium Designer | The library's `<Library name>.DbLib` in the installed-library list until you uninstall it. |

## Uninstall

1. On PartForge's *Altium* page, uninstall the library from Altium, then close the library.
   In the German interface, the action is called *Aus Altium deinstallieren*.
2. Optionally remove the stored Claude key under *Settings → General → AI features*.
3. Exit PartForge and delete the packaged application folder, or the source folder including `.venv`.
4. Delete `%APPDATA%\PartForge` and `%LOCALAPPDATA%\PartForge` to remove settings, keys, logs, caches and
   the WebView profile.
5. Your library folders remain usable in Altium without PartForge. Remove separately installed components,
   such as the Rust library writer and SQLite3 ODBC Driver, separately if you no longer need them.

## Troubleshooting

| Problem | Suggested fix |
| --- | --- |
| New components do not appear in Altium | Refresh Altium from PartForge's *Altium* page and check that the DbLib is installed. |
| Altium does not respond to PartForge | A script may be stuck. Press **Ctrl+F3** in Altium (*Run → Stop*). |
| `database is locked` | Keep SQLite libraries on a local drive and use WAL mode. For multiple users, see [PostgreSQL](#postgresql-for-multiple-users--source-installation-only). |
| Library folder cannot be moved after uninstalling it from Altium | Close the library in PartForge, wait about a minute and retry. Altium may still hold the database open; restart or close Altium if needed. If PartForge names another program holding the file, close that program. |
| SchLib/PcbLib files are not written | Check the writer's path under *Settings → General → Altium Designer*. The library must not have unsaved edits in Altium. |
| Datasheet import is unavailable | Configure a key under *Settings → General → AI features* and test the connection. |
| The launcher reports an error | Follow its guidance about Python, network/proxy settings or Node.js. If necessary, delete `.venv` and start again, or use a packaged build. |
| PartForge fails to start or shows a blank page | Check `%LOCALAPPDATA%\PartForge\logs\partforge.log`. Keep all packaged files together instead of copying only the executable. |

## Development

Start with the source-installation steps above to create `.venv`. Run the following from the repository root:

```powershell
.venv\Scripts\python.exe -m pip install -e .[test,build] -c constraints.txt
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m partforge --dev
```

The development API listens on `:8765` with the development token `dev`.
In another terminal, run the frontend on `:5173`:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Use `npm.cmd` on Windows if PowerShell's execution policy blocks `npm.ps1`.
Frontend checks are `npm.cmd run build`, `npm.cmd run lint` and `npm.cmd test`.
Tests requiring Altium, the Rust writer or the Claude API are gated by the environment variables
`PARTFORGE_TEST_ALTIUM`, `PARTFORGE_TEST_RUST` and `PARTFORGE_TEST_AI` in `tests/conftest.py`.

From the repository root:

```powershell
.venv\Scripts\python.exe scripts\build.py
.venv\Scripts\python.exe scripts\update_constraints.py
```

The build script creates `dist\PartForge` using PyInstaller, includes version information, renders
`docs/handbuch/BEDIENUNG.md` as `Handbuch\Bedienung.html`, writes `THIRD_PARTY_LICENSES.txt` and runs an
isolated smoke test. Build warnings, missing modules, log errors or leftover files fail that test.
Signing is optional via `--sign`, the Windows certificate store, `PARTFORGE_SIGN_CERT_SHA1` or
`PARTFORGE_SIGN_PFX`. Update `constraints.txt` after dependency updates.

Further documentation (currently in German):

- [Architecture and module contracts](docs/entwicklung/ARCHITEKTUR.md)
- [Frontend design system](docs/entwicklung/FRONTEND.md)
- [Research and Altium verification notes](docs/entwicklung/recherche/)
- [Changelog and known limitations](CHANGELOG.md)

## License

PartForge's own code is released under the **MIT license**: see [LICENSE](LICENSE).
Third-party components retain their own licenses; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
and the full license list included with packaged builds.

Altium and Altium Designer are trademarks of Altium Ltd. PartForge is an independent project,
not an Altium product.
