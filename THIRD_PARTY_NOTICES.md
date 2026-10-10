# Drittanbieter-Komponenten

PartForge selbst steht unter der MIT-Lizenz ([LICENSE](LICENSE)). Diese Übersicht nennt die Komponenten von
Drittanbietern, die PartForge verwendet; die vollständigen Lizenztexte stehen

- **im Programmpaket** in `THIRD_PARTY_LICENSES.txt` neben `PartForge.exe` – `scripts/build.py` erzeugt die Datei
  bei jedem Bau aus genau den Dateien, die PyInstaller ins Paket gepackt hat (`scripts/third_party.py`), samt
  den Lizenzen der Oberflächen-Pakete und der Schriften;
- **im Quellcode** bei den installierten Paketen (`.venv\Lib\site-packages\<paket>*.dist-info`,
  `frontend\node_modules\<paket>`) bzw. unter `scripts/licenses/` für Pakete ohne eigene Lizenzdatei.

## Copyleft-Prüfung

Die Komponenten behalten ihre jeweiligen Lizenzen; PartForges eigener Quellcode steht unter MIT.
Mitgelieferte Copyleft-Komponenten sind insbesondere:

- **occt-import-js 0.0.23** (LGPL-2.1) und **Open CASCADE Technology 7.6.1** (LGPL-2.1 mit OCCT-Ausnahme):
  Die STEP-Vorschau verwendet diese Bibliotheken als Web Worker mit separat ausgeliefertem WASM. PartForge
  verändert ihren Bibliotheksquellcode nicht. Quellen und Hinweise zum Austausch stehen [unten](#step-bibliothek-quellen-bauen-und-austauschen).
- **odfpy** steht wahlweise unter Apache-2.0 oder GPL-2.0-or-later – PartForge nutzt es unter **Apache-2.0**.
- **PyInstaller-Bootloader** (Teil von `PartForge.exe`): GPL-2.0-or-later **mit Bootloader-Ausnahme**, die die
  Weitergabe zusammen mit Programmen beliebiger Lizenz erlaubt; die Laufzeit-Hooks stehen unter Apache-2.0.
- **certifi** (Zertifikatsliste): MPL-2.0, unverändert mitgeliefert; Quelle: <https://github.com/certifi/python-certifi>.
- **FreeType** (in PDFium/pypdfium2) steht unter der FreeType License (FTL), die diesen Hinweis verlangt:
  *Portions of this software are copyright © 1996-2025 The FreeType Project (www.freetype.org). All rights reserved.*
- **altium-designer-mcp** (GPL-3.0) wird nicht mitgeliefert (siehe unten).

## Laufzeit im Programmpaket

| Komponente | Lizenz |
| --- | --- |
| Python 3.13 (CPython: `python313.dll`, Standardbibliothek) mit OpenSSL (`libssl`, `libcrypto`), libffi, SQLite, zlib, expat, bzip2, xz und der Microsoft Visual C++ Runtime (`vcruntime140*.dll`) | PSF-2.0; die Bibliotheken unter ihren eigenen Lizenzen (Apache-2.0, MIT, Public Domain, zlib, BSD) bzw. den Microsoft-Bedingungen für verteilbaren Code |
| PyInstaller (Bootloader, Laufzeit-Hooks), pyinstaller-hooks-contrib (Laufzeit-Hooks) | GPL-2.0-or-later mit Bootloader-Ausnahme / Apache-2.0 |
| Microsoft Edge WebView2 SDK (`Microsoft.Web.WebView2.*.dll`, `WebView2Loader.dll`, über pywebview) | BSD-artige Lizenz der Microsoft Corporation |

## Python-Pakete im Programmpaket

| Paket | Lizenz |
| --- | --- |
| FastAPI, Starlette, Pydantic, pydantic-core, typing-inspection, annotated-types, annotated-doc | MIT / BSD-3-Clause |
| uvicorn, h11, httptools, websockets, watchfiles, python-dotenv, PyYAML, click | BSD-3-Clause / MIT |
| anyio, sniffio, idna, truststore, certifi | MIT / MIT OR Apache-2.0 / BSD-3-Clause / MPL-2.0 |
| httpx, httpx2, httpcore, httpcore2 | BSD-3-Clause |
| anthropic (Claude SDK, mit vendortem httpx-aiohttp), jiter, docstring-parser, opentelemetry-api | MIT / Apache-2.0 |
| python-multipart | Apache-2.0 |
| SQLAlchemy, greenlet | MIT / MIT AND PSF-2.0 |
| pypdf | BSD-3-Clause |
| pypdfium2 mit PDFium (enthält u. a. FreeType, ICU, libjpeg-turbo, libpng, OpenJPEG, Little CMS, zlib, Abseil) | Apache-2.0 / BSD-3-Clause; Bestandteile unter ihren eigenen Lizenzen |
| cryptography (mit eigenem OpenSSL), cffi, pycparser | Apache-2.0 OR BSD-3-Clause / MIT-0 / BSD-3-Clause |
| pywebview, bottle, proxy_tools | BSD-3-Clause / MIT |
| pythonnet, clr_loader | MIT |
| pywin32 | PSF-2.0 |
| pyodbc | MIT |
| openpyxl, et_xmlfile | MIT |
| odfpy, defusedxml | Apache-2.0 (gewählt) / PSF-2.0 |
| Pillow | MIT-CMU (HPND) |
| platformdirs, RapidFuzz | MIT |
| typing_extensions | PSF-2.0 |

Nur für die Entwicklung (nicht im Programmpaket): pytest, Playwright (Apache-2.0, Screenshots),
pdfplumber/pdfminer.six (MIT, Auswertung des Datenblatt-Korpus), PyInstaller als Werkzeug.

## Oberfläche (im Programmpaket gebündelt)

| Paket | Lizenz |
| --- | --- |
| React, React DOM, React Router, scheduler | MIT |
| Radix UI, cmdk, sonner, motion, zustand, react-dropzone, clsx, tailwind-merge | MIT |
| class-variance-authority | **Apache-2.0** |
| lucide-react | ISC |
| TanStack Query, TanStack Virtual | MIT |
| AG Grid Community | MIT |
| three.js, @react-three/fiber, @react-three/drei (mit u. a. draco3d, @mediapipe/tasks-vision, @dimforge/rapier3d-compat, hls.js: Apache-2.0) | MIT / Apache-2.0 |
| occt-import-js 0.0.23 mit Open CASCADE Technology 7.6.1 (STEP-Import im Web Worker/WASM) | LGPL-2.1 / LGPL-2.1 mit OCCT-Ausnahme |
| Recharts mit victory-vendor und d3-Modulen | MIT / ISC / BSD-3-Clause |
| Tailwind CSS (erzeugtes CSS) | MIT |
| Inter, JetBrains Mono (Schriften über @fontsource-variable) | SIL Open Font License 1.1 |
| tslib | 0BSD |
| Laufzeithilfen von Vite und Rolldown | MIT |

Zum Bauen (nicht im Paket): Vite, Rolldown, TypeScript, oxlint, openapi-typescript, Tailwinds Compiler mit
lightningcss (MPL-2.0).

### STEP-Bibliothek: Quellen, Bauen und Austauschen

Die STEP-Vorschau nutzt Funktionen von **Open CASCADE Technology**. Der JavaScript-Wrapper wird mit dem
eigenen STEP-Worker gebündelt; die WASM-Datei aus dem npm-Paket wird unverändert als separate Datei unter
`partforge/web/assets/` ausgeliefert. Die vollständigen LGPL-Texte des Wrappers und des OCCT-Kerns stehen
in der erzeugten Lizenzliste. Die OCCT-Ausnahme lautet:

> Open CASCADE exception (version 1.0) to GNU LGPL version 2.1.
>
> The object code (i.e. not a source) form of a "work that uses the Library"
> can incorporate material from a header file that is part of the Library.
> As a special exception to the GNU Lesser General Public License version 2.1,
> you may distribute such object code incorporating material from header files
> provided with the Open CASCADE Technology libraries (including code of CDL
> generic classes) under terms of your choice, provided that you give
> prominent notice in supporting documentation to this code that it makes use
> of or is based on facilities provided by the Open CASCADE Technology software.

Die verwendeten Quellen und Bauanweisungen sind frei verfügbar:

- [occt-import-js 0.0.23](https://github.com/kovacsv/occt-import-js/tree/0.0.23), Commit
  `c2148e54b456b571238d35cac037d304053d64b2`; Wrapper unter `occt-import-js/src/`, Build unter `tools/`
  und [Bauanleitung](https://github.com/kovacsv/occt-import-js/tree/0.0.23#how-to-build-on-windows).
- Das dort festgelegte Submodul ist [Open CASCADE Technology V7_6_1](https://github.com/Open-Cascade-SAS/OCCT/tree/V7_6_1),
  Commit `d2abb6d844231cb8f29be6894440874a4700e4a5`, einschließlich
  [LGPL-2.1](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_6_1/LICENSE_LGPL_21.txt) und
  [OCCT-Ausnahme](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_6_1/OCCT_LGPL_EXCEPTION.txt).

Zum eigenen Bauen unter Windows CMake und Node.js installieren, die Quellen samt OCCT-Submodul auschecken,
`npm install` ausführen und den Skripten `tools\setup_emscripten_win.bat` (Emscripten 3.1.69) und
`tools\build_wasm_win_dist.bat` folgen. Falls die historische Submoduladresse nicht verfügbar ist, lässt sich
für `submodule.occt.url` das oben verlinkte offizielle GitHub-Repository einsetzen; der festgelegte Commit
bleibt derselbe.

Eine eigene Bibliotheksfassung kann PartForge ohne Änderung seiner Anwendung verwenden: Nach `npm ci` im
PartForge-Ordner `frontend` die Dateien `occt-import-js.js` und `occt-import-js.wasm` sowie die zugehörigen
Lizenzdateien unter `node_modules/occt-import-js/dist/` durch den eigenen Build ersetzen. Anschließend
`npm run build` ausführen; der neue Worker und das neue WASM landen in `partforge/web/`. Ein erneutes
`npm ci` setzt die Bibliothek wieder auf die festgelegte npm-Version zurück. Der Anwendungscode, die
Worker-Schnittstelle und der Build stehen ebenfalls als Quellcode bereit; eigene Bibliotheksänderungen
und deren Fehlersuche werden nicht technisch eingeschränkt.

## Altium-Anbindung

- **altium-mcp** (Siddharth Ahuja, MIT): Teile der DelphiScript-Brücke unter
  `partforge/altium/bridge/scripts/` basieren auf diesem Projekt; siehe `THIRD_PARTY_NOTICES.txt` dort.
- **altium-designer-mcp** (The Embedded Society, GPL-3.0-or-later): wird **nicht** mitgeliefert.
  PartForge startet das separat installierte Programm als eigenen Prozess und kommuniziert über
  stdio (JSON-RPC). Quelle und Download: <https://github.com/embedded-society/altium-designer-mcp>.
- **SQLite3 ODBC Driver** (Christian Werner, BSD-ähnlich): wird **nicht** mitgeliefert; Altium nutzt
  ihn, um die Datenbank zu lesen.

Altium und Altium Designer sind Marken der Altium Ltd. PartForge ist kein Produkt von Altium.
