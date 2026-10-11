# PartForge

[English](README.md) | **Deutsch**

**Datenbankbasierte Bauteilbibliotheken für Altium Designer – anlegen, pflegen, prüfen.**

PartForge erzeugt und verwaltet eine Altium-Datenbankbibliothek (DbLib) samt Schaltplansymbolen,
IPC-7351B-Footprints und 3D-Modellen. Komplette Bauteilserien entstehen mit wenigen Klicks,
Datenblätter werden per Drag & Drop von Claude ausgewertet und zu fertigen Bauteilen mit Symbol
und Footprint. Altium sieht neue Bauteile sofort – ohne Neustart.

> **Frühe Beta · Vibe Coding:** PartForge ist größtenteils durch Vibe Coding mit KI-Unterstützung
> entstanden und befindet sich in einem frühen Beta-Stadium. Fehler und Änderungen sind zu erwarten.
> Bitte erzeugte Bauteile, Symbole und Footprints vor dem Einsatz prüfen und Bibliotheken regelmäßig sichern.

Aktuelle Version: **1.0.0b1**, GitHub-Prerelease-Tag **v1.0.0-beta.1**.

Die Oberfläche unterstützt **Englisch (Standard)** und **Deutsch**. Die Sprache lässt sich unter
*Settings → General → Language* bzw. *Einstellungen → Allgemein → Sprache* wählen und speichern;
die Auswahl bleibt auch nach einem Neustart erhalten.

![Übersicht](docs/screenshots/readme/uebersicht-dark.png)

## Funktionen auf einen Blick

| Bereich | Was PartForge macht |
| --- | --- |
| **Bibliothek** | Ein verschiebbarer Ordner mit SQLite-Datenbank, DbLib, SchLib/PcbLib, 3D-Modellen, Datenblättern und Backups. Kategorien als eigene Tabellen (Widerstände, Kondensatoren, …), Felder mit Einheiten, Vorlagen für Beschreibung und Kommentar. |
| **Bauteile** | Tabelle mit Suche, die Werte versteht („10k“, „100n“), Filter mit Größenvergleich, Inline-Bearbeitung, Massenänderungen, Historie, Wiederherstellen, Import (CSV, Excel, ODS) und Export (CSV, Excel). |
| **Serien-Assistent** | Ganze E-Reihen (E3–E192) einer Hersteller-Serie auf einmal: Vishay CRCW, Yageo RC, Panasonic ERJ, KOA, Stackpole, UniOhm, Bourns, KEMET, Yageo CC, Samsung CL, Murata, Bourns SRR … inklusive passender Footprints. |
| **Datenblatt-Import** | PDF ablegen oder „Datenblatt suchen“ → Claude liest Hersteller, Bestellvarianten, Parameter, Pinbelegung und Gehäusemaße → Vorschlag mit Symbol, Footprint und 3D → ein Klick übernimmt alles. |
| **Footprint-Generator** | IPC-7351B (Dichte L/N/M) für 21 Gehäusefamilien von 01005 bis BGA und THT, mit Bemaßung, Berechnungsnachweis, 3D-Körper und STEP-Export. |
| **Symbol-Generator** | Rund 40 Standardsymbole im Hausstil plus IC-Symbole aus Pinlisten mit automatischer Pin-Anordnung und Mehrteil-Symbolen. |
| **Bibliotheksimport** | Symbole und Footprints vorhandener Altium-Bibliotheken übernehmen: Ordner, SchLib/PcbLib, IntLib, LibPkg oder ZIP; Namenskonflikte werden erkannt, aus den Symbolen entsteht auf Wunsch eine Bauteiltabelle. Eingebettete STEP-Modelle erscheinen in der 3D-Vorschau, auch bei bestehenden Importen ohne erneuten Import. |
| **Stapelbearbeitung** | Importierte Symbole und Footprints in einem Arbeitsgang an den Hausstil angleichen (Schriften, Pinlängen, Präfixe, Lagen, Linienbreiten, Texte, Lagensatz) – verlustfrei, mit Sicherung und Rückgängig; Hausstil aus einer Beispielbibliothek übernehmen. |
| **Altium** | DbLib automatisch aktuell halten, in Altium installieren, „In Altium aktualisieren“, alle Bauteile in Altium prüfen, Lagen nach der eigenen `.stackup`-Vorlage und eigener Lagensatz (`.layerset`). |

## Installation und Start

Das Windows-Archiv aus dem [Beta-1-Release](https://github.com/trosenbusch/PartForge/releases/tag/v1.0.0-beta.1)
herunterladen und vollständig entpacken. SHA-256-Prüfsummen liegen dem Release bei.

**Programmpaket (empfohlen):** Den Ordner `PartForge` vollständig an einen festen Ort kopieren, z. B.
`%LOCALAPPDATA%\Programs\PartForge`, und `PartForge.exe` starten – Python und Node.js sind nicht nötig.
Das Paket enthält ein eigenes Handbuch (`README.md`), die [Bedienungsanleitung](#handbuch) als
`Handbuch\Bedienung.html` und die Lizenzen aller mitgelieferten Komponenten (`THIRD_PARTY_LICENSES.txt`). Gebaut
wird es mit `scripts\build.py` nach `dist\PartForge` (siehe [Entwicklung](#entwicklung)).

**Aus dem Quellcode:** `Start-PartForge.cmd` doppelklicken. Nötig sind Python ≥ 3.11 (getestet mit 3.13; von
[python.org](https://www.python.org/downloads/windows/) mit „Add python.exe to PATH“), Node.js mit npm
(20.19.x oder neuer innerhalb der 20.x-Reihe, oder ≥ 22.12) und beim ersten Start eine Internetverbindung. Das Skript

- richtet die Python-Umgebung `.venv` ein und installiert die getesteten Paketversionen (`constraints.txt`),
- baut die Oberfläche mit Node.js, wenn sie fehlt oder älter als ihr Quellcode ist,
- prüft bei jedem Start in Sekundenbruchteilen, ob sich `pyproject.toml`, `constraints.txt` oder die Quellen
  der Oberfläche geändert haben, und installiert bzw. baut dann neu – nach einem Update genügt ein normaler Start,
- meldet jeden Fehler auf Deutsch mit Lösung (kein Python, keine Internetverbindung, Proxy über `HTTPS_PROXY`,
  eigener Paketspiegel über `PIP_INDEX_URL`, fehlendes Node.js); bricht PartForge direkt nach dem Start ab, weil
  ein Paket fehlt, repariert es die Umgebung einmal und meldet sonst die Ursache – nichts scheitert unbemerkt.

`Start-PartForge.cmd` startet immer den Quellcode; ein gebautes Paket startet man mit `dist\PartForge\PartForge.exe`.

Voraussetzungen für die volle Funktion:

| Komponente | Wofür | Hinweis |
| --- | --- | --- |
| Windows 10/11 mit WebView2 | Programmfenster | bei Windows 11 vorhanden, sonst die [WebView2-Runtime](https://developer.microsoft.com/microsoft-edge/webview2/) installieren |
| SQLite3 ODBC Driver (64 bit) | Altium liest die Datenbank | [ch-werner.de/sqliteodbc](http://www.ch-werner.de/sqliteodbc/) |
| Altium Designer | Bibliothek nutzen, „In Altium aktualisieren“, Prüfung | getestet mit 26.10 |
| altium-designer-mcp.exe | SchLib/PcbLib schreiben (ohne Altium) | GPL-3.0, wird nicht mitgeliefert: Windows-Archiv der aktuellen Version von [github.com/embedded-society/altium-designer-mcp/releases](https://github.com/embedded-society/altium-designer-mcp/releases) laden und `altium-designer-mcp.exe` nach `%LOCALAPPDATA%\Programs\altium-designer-mcp\` kopieren (beim Programmpaket auch neben `PartForge.exe` möglich) – dort findet PartForge sie selbst; anderer Ort: *Einstellungen → Allgemein → Altium Designer* |
| Claude-API-Schlüssel | Datenblatt-Import | *Einstellungen → Allgemein → KI-Funktionen* (wird mit Windows-DPAPI verschlüsselt gespeichert) |

## Erste Schritte

1. **Bibliothek anlegen** – beim ersten Start „Neue Bibliothek anlegen“, Name und Ordner wählen,
   „Beispielinhalte anlegen“ aktiviert lassen. PartForge legt Datenbank, DbLib, Symbole und
   Footprints an; die DbLib-Datei heißt standardmäßig wie die Bibliothek (`<Name>.DbLib`, im Dialog änderbar).
2. **In Altium einbinden** – Seite *Altium* → „In Altium installieren“ (oder in Altium unter
   *Components → File-based Libraries Preferences* die DbLib-Datei der Bibliothek hinzufügen).
3. **Serie erzeugen** – *Serien-Assistent* → Widerstände → Hersteller-Serie → E-Reihe, Bereich
   und Bauformen wählen → Vorschau → *Erzeugen*. Fehlende Footprints entstehen automatisch.
4. **Datenblatt importieren** – PDF irgendwo ins Fenster ziehen. Nach der Analyse die Vorschläge
   prüfen (Pins, Gehäuse, Footprint-Variante) und *Bauteil anlegen*.
5. **In Altium platzieren** – Die Bauteile erscheinen im Components-Panel unter der DbLib der Bibliothek
   (z. B. `Firmenbibliothek.DbLib`). Änderungen aus PartForge werden automatisch übernommen („In Altium aktualisieren“).

## Handbuch

- **[Bedienungsanleitung](docs/handbuch/BEDIENUNG.md)** – Schritt für Schritt mit Bildern: Bibliothek anlegen,
  Bauteile verwalten, Widerstandsserie anlegen, Bauteil aus Datenblatt, Symbole und Footprints, Altium,
  Einstellungen und Sicherungen, Tastenkürzel, häufige Fragen. Im Programmpaket liegt sie als
  `Handbuch\Bedienung.html` (öffnet sich im Browser, mit den Bildern aus `Handbuch\bilder\`).
- **[Handbuch zum Programmpaket](docs/handbuch/README.md)** – Installation, benötigte Komponenten, Datenablage,
  Aktualisieren, Deinstallieren und Fehlerbehebung; im Programmpaket die Datei `README.md`.

## Wie PartForge mit Altium zusammenarbeitet

- Die Datenbank ist eine SQLite-Datei im WAL-Modus. Altium liest sie über ODBC, PartForge schreibt
  gleichzeitig – ohne Sperren.
- Altium hält den Datenstand einer DbLib fest. PartForge löst nach Änderungen automatisch eine
  Aktualisierung aus: Es schließt Altiums verstecktes DbLib-Dokument (nie ein sichtbares oder
  geändertes) und baut bei neuen Bauteilen den Bauteilindex neu auf. Abschaltbar unter
  *Einstellungen → Allgemein → Altium Designer*.
- Platzierte Bauteile merken sich die DbLib **nur über ihren Dateinamen**. Den DbLib-Dateinamen, der beim
  Anlegen der Bibliothek gewählt wurde, daher später nicht mehr ändern und nur eine DbLib mit diesem Namen
  installieren.
- Symbole und Footprints schreibt PartForge standardmäßig mit dem Rust-Writer (Altium muss dafür
  nicht laufen). Geöffnete, unveränderte Bibliotheken lädt PartForge in Altium automatisch neu;
  Bibliotheken mit ungespeicherten Änderungen in Altium werden nicht überschrieben.
- Footprint-Lagen folgen der eigenen Vorlage (Standard: Mech 9 Assembly, 11 Designator, 13 3D,
  15 Courtyard, 17 Component Center, 19 Value, 21 Component Outline). Die Lagennamen und -typen
  stehen in jeder PcbLib, sodass Altium beim Platzieren richtig zuordnet.
- Nach „Aus Altium deinstallieren“ hält Altium die Datenbank noch eine Weile offen (meist etwa eine
  Minute, manchmal bis zum Neustart von Altium). So lange lässt sich der Bibliotheksordner nicht
  verschieben oder umbenennen; PartForge meldet beim Deinstallieren, ob Altium die Datenbank schon freigibt.

## Mehrbenutzerbetrieb mit PostgreSQL (nur Quellcode-Installation)

Statt der SQLite-Datei kann eine Bibliothek ihre Daten auf einem PostgreSQL-Server halten. Die Oberfläche
stellt das nicht ein, und das Programmpaket enthält keinen PostgreSQL-Treiber. Mit der Quellcode-Installation:

1. Treiber installieren: `.venv\Scripts\python.exe -m pip install -e .[postgres] -c constraints.txt`
2. In `partforge.json` des Bibliotheksordners den Abschnitt `db` setzen: `"kind": "postgres"`,
   `"postgres_url": "postgresql+psycopg://benutzer:passwort@server:5432/datenbank"` und für Altium
   `"postgres_odbc": "DRIVER={PostgreSQL Unicode(x64)};SERVER=…;PORT=5432;DATABASE=…;UID=…;PWD=…"`
   (Altium braucht dafür den psqlODBC-Treiber, 64 bit).
3. PartForge neu starten und die Bibliothek öffnen.

## Daten und Sicherheit

- Alles Fachliche liegt im Bibliotheksordner; PartForge sendet nur beim Datenblatt-Import (und bei
  „Datenblatt suchen“) die ausgewählten PDF-Seiten bzw. die Suchanfrage an die Claude-API.
- Der API-Schlüssel wird nie an die Oberfläche gegeben; gespeichert wird er mit Windows-DPAPI
  (`%APPDATA%\PartForge\secret`), nur für das eigene Windows-Konto lesbar. Eine optionale Schlüsseldatei
  muss lokal liegen, klein sein und einen Claude-Schlüssel (`sk-ant-…`) enthalten – andere Dateiinhalte
  werden nie verschickt.
  Eine neue Installation startet ohne voreingestellte Schlüsseldatei. Schlüssel werden ausdrücklich
  unter *Einstellungen › Allgemein › KI-Funktionen* oder über `ANTHROPIC_API_KEY` hinterlegt.
- PartForge läuft als lokaler Server auf `127.0.0.1` und nimmt nur Verbindungen von diesem Rechner an
  (`127.0.0.1`/`localhost`); Anfragen fremder Webseiten werden abgewiesen. Der Zugriff ist zusätzlich durch
  ein Sitzungstoken geschützt, das PartForge bei jedem Start neu vergibt und das nie in Protokolldateien steht.
- Die Oberfläche öffnet sich im Programmfenster, über eine selbst eingegebene Adresse oder ein Lesezeichen –
  nicht aus einer fremden Website heraus: Ruft eine Website PartForge über einen Link, eine Weiterleitung oder
  einen eingebetteten Rahmen auf, erscheint nur der Hinweis „PartForge wurde von einer anderen Website
  aufgerufen“ mit dem Link „PartForge öffnen“. Es wird nichts ausgeführt, und keine Website kann PartForge in
  einen Rahmen einbetten. Aktionen wie „DbLib neu erzeugen“ oder „In Altium installieren“ lassen sich
  grundsätzlich nicht über die Adresse auslösen, auch nicht über einen Link in einer Mail.
- Die Pfade zu Altium (`X2.EXE`) und zum Bibliotheks-Writer müssen auf lokale Programmdateien zeigen;
  Netzwerk-/Gerätepfade lehnt PartForge ab und führt sie nie aus.
- CSV-Exporte sind Excel-sicher: Werte, die Excel als Formel ausführen würde (beginnend mit `=`, `+`, `@`
  oder `-` vor einem Ausdruck), bekommen ein `'` vorangestellt, das der Tabellen-Import wieder entfernt.
  XLSX-Exporte speichern solche Werte als Text, nie als Formel.
- Vor riskanten Aktionen (Kategorie löschen, viele Bauteile löschen, Import, Wiederherstellen)
  legt PartForge automatisch ein Backup unter `Backups\` an. Jede Bibliotheksdatei hat
  Sicherungsstände unter `Backups\lib\`.

Was PartForge außerhalb der Bibliotheksordner ablegt:

| Ort | Inhalt |
| --- | --- |
| `%APPDATA%\PartForge` (wandert mit dem Benutzerprofil) | `settings.json` (Einstellungen, zuletzt geöffnete Bibliotheken), `secret\` (verschlüsselter Claude-Schlüssel), `ai\search-costs.json` (Kosten der letzten Datenblattsuchen) |
| `%LOCALAPPDATA%\PartForge` (nur dieser Rechner) | Protokolle (`logs\partforge.log`, in der Größe begrenzt), Zwischenspeicher (Seitenbilder der Datenblätter, höchstens 512 MB; entpackte IntLib-/ZIP-Bibliotheken des Bibliotheksimports, nach zwei Tagen gelöscht), WebView-Profil des Programmfensters, temporäre Dateien, Austauschordner der Altium-Brücke |
| Altium Designer | die DbLib-Datei der Bibliothek (`<Name>.DbLib`) in der Liste der installierten Bibliotheken (bis „Aus Altium deinstallieren“) |

## Deinstallieren

1. In PartForge auf der Seite *Altium* „Aus Altium deinstallieren“ wählen (entfernt die DbLib der Bibliothek
   aus Altium) und die Bibliothek schließen.
2. Optional den gespeicherten Claude-Schlüssel entfernen: *Einstellungen → Allgemein → KI-Funktionen* →
   „Gespeicherten Schlüssel entfernen“.
3. PartForge beenden und den Programmordner löschen (Programmpaket) bzw. den Quellcode-Ordner mit `.venv`.
4. Die Ordner `%APPDATA%\PartForge` und `%LOCALAPPDATA%\PartForge` löschen (Einstellungen, Schlüssel,
   Protokolle, Zwischenspeicher, WebView-Profil).
5. Die Bibliotheksordner bleiben erhalten – sie gehören Ihnen und funktionieren in Altium auch ohne PartForge.
   Separat installierte Programme (altium-designer-mcp, SQLite3 ODBC Driver) bei Bedarf eigens entfernen.

## Fehlerbehebung

| Problem | Lösung |
| --- | --- |
| Neue Bauteile fehlen in Altium | *Altium → In Altium aktualisieren*. Prüfen, dass die DbLib installiert ist. |
| Altium reagiert nicht auf PartForge | In Altium hängt evtl. ein Skript: **Strg+F3** (Run → Stop) drücken. |
| „database is locked“ | Die Datenbank liegt auf einem Netzlaufwerk oder nicht im WAL-Modus – Bibliothek lokal ablegen (mehrere Benutzer: [PostgreSQL](#mehrbenutzerbetrieb-mit-postgresql-nur-quellcode-installation)). |
| Bibliotheksordner lässt sich nach „Aus Altium deinstallieren“ nicht verschieben oder umbenennen („Zugriff verweigert“) | Altium hält die Datenbank (`PartForge.sqlite`) noch offen. PartForge meldet das beim Deinstallieren: „Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen (sonst Altium neu starten).“ – dann kurz warten und erneut verschieben; klappt es dann noch nicht, Altium neu starten. Nennt die Meldung ein anderes Programm („Ordner erst nach dem Schließen von … verschiebbar“), dieses schließen. Vorher in PartForge „Bibliothek schließen“. |
| SchLib/PcbLib wird nicht geschrieben | *Einstellungen → Allgemein → Altium Designer*: Pfad zu `altium-designer-mcp.exe` prüfen; die Bibliothek darf in Altium keine ungespeicherten Änderungen haben. |
| Datenblatt-Import nicht möglich | *Einstellungen → Allgemein → KI-Funktionen*: Schlüssel hinterlegen, „Verbindung testen“. |
| `Start-PartForge.cmd` meldet einen Fehler | Der Meldung folgen (Python installieren, Internet/Proxy prüfen, Node.js installieren). Hilft das nicht: den Ordner `.venv` löschen und erneut starten – oder das Programmpaket verwenden. |
| PartForge startet nicht oder zeigt eine leere Seite | Protokoll `%LOCALAPPDATA%\PartForge\logs\partforge.log` ansehen; beim Programmpaket den Ordner `PartForge` vollständig lassen (nicht nur die EXE kopieren). |

## Entwicklung

```powershell
.venv\Scripts\python.exe -m pip install -e .[test,build] -c constraints.txt   # Test- und Paketwerkzeuge
.venv\Scripts\python.exe -m pytest -q          # rund 5 000 Tests (Altium/KI-Tests per Umgebungsvariable)
.venv\Scripts\python.exe -m partforge --dev    # API auf :8765, Token "dev"
cd frontend; npm ci; npm run dev               # Oberfläche auf :5173
.venv\Scripts\python.exe scripts\build.py      # Programmpaket nach dist\PartForge (mit Lizenzliste und Smoke-Test)
.venv\Scripts\python.exe scripts\update_constraints.py   # constraints.txt nach Paket-Updates neu schreiben
```

`scripts\build.py` baut die Oberfläche, das Paket (PyInstaller) samt Versionsressource, erzeugt die
Bedienungsanleitung als HTML (`Handbuch\Bedienung.html` aus `docs/handbuch/BEDIENUNG.md`, mit python-markdown aus
dem Extra `build`), schreibt `THIRD_PARTY_LICENSES.txt`, signiert auf Wunsch (`--sign`, Zertifikat aus dem Zertifikatsspeicher oder
`PARTFORGE_SIGN_CERT_SHA1`/`PARTFORGE_SIGN_PFX`) und prüft das Ergebnis mit `scripts\smoke_test.py`: Das Paket
startet isoliert, legt eine Bibliothek mit Beispielen an und schreibt sie; jede Warnung, fehlende Module,
Fehler im Protokoll oder zurückgebliebene Dateien lassen den Bau scheitern.

Architektur und Modulverträge: [docs/entwicklung/ARCHITEKTUR.md](docs/entwicklung/ARCHITEKTUR.md),
Designsystem: [docs/entwicklung/FRONTEND.md](docs/entwicklung/FRONTEND.md),
Recherche und Altium-Nachweise: [docs/entwicklung/recherche/](docs/entwicklung/recherche/),
Handbuch des Programmpakets: [docs/handbuch/README.md](docs/handbuch/README.md),
Bedienungsanleitung: [docs/handbuch/BEDIENUNG.md](docs/handbuch/BEDIENUNG.md),
Änderungen je Version: [CHANGELOG.md](CHANGELOG.md),
Lizenzen: [LICENSE](LICENSE) (MIT), [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Beiträge und Support

Fehler und Vorschläge können über [GitHub Issues](https://github.com/trosenbusch/PartForge/issues) gemeldet werden.
Hinweise für Mitwirkende stehen in [CONTRIBUTING.md](CONTRIBUTING.md), der vertrauliche Meldeweg für
Sicherheitslücken in [SECURITY.md](SECURITY.md). API-Schlüssel, interne Bibliotheksdateien und persönliche
Pfade vor dem Teilen aus Protokollen und Bildschirmfotos entfernen.
