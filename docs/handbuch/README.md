# PartForge – Handbuch zum Programmpaket

PartForge erzeugt und pflegt Datenbankbibliotheken (DbLib) für Altium Designer: Bauteile in einer
SQLite-Datenbank, dazu Schaltplansymbole (SchLib), IPC-7351B-Footprints (PcbLib) und 3D-Modelle.
Komplette Bauteilserien entstehen mit wenigen Klicks, Datenblätter wertet Claude aus.

Dieses Handbuch gehört zum fertigen Programmpaket (Ordner `PartForge` mit `PartForge.exe`). Die Bedienung
Schritt für Schritt mit Bildern zeigt die [Bedienungsanleitung](BEDIENUNG.md) – im Programmordner die Datei
`Handbuch\Bedienung.html`, die sich im Browser öffnet.

## Inhalt des Ordners

| Datei / Ordner | Bedeutung |
| --- | --- |
| `PartForge.exe` | das Programm |
| `_internal\` | Laufzeit und Programmteile – gehört zur EXE, nicht löschen oder verschieben |
| `README.md` | dieses Handbuch |
| `Handbuch\` | Bedienungsanleitung mit Bildern: `Bedienung.html` im Browser öffnen |
| `CHANGELOG.md` | was diese Version kann und welche Einschränkungen bekannt sind |
| `LICENSE` | Lizenz von PartForge (MIT) |
| `THIRD_PARTY_NOTICES.md`, `THIRD_PARTY_LICENSES.txt` | Übersicht und vollständige Lizenztexte der mitgelieferten Komponenten |
| `Start-PartForge.cmd` | startet ebenfalls `PartForge.exe` |

## Installation

1. Den ganzen Ordner `PartForge` an einen festen Ort kopieren, empfohlen
   `%LOCALAPPDATA%\Programs\PartForge` (Explorer-Adresszeile: `%LOCALAPPDATA%\Programs` eingeben).
   Nicht nur die EXE kopieren – sie braucht den Ordner `_internal` daneben.
2. `PartForge.exe` starten. Für eine Verknüpfung: Rechtsklick auf `PartForge.exe` → *Weitere Optionen
   anzeigen* → *Senden an* → *Desktop (Verknüpfung erstellen)*.
3. Meldet Windows SmartScreen „Der Computer wurde durch Windows geschützt“, kennt Windows das Programm noch nicht
   (z. B. weil es nicht signiert ist; Eigenschaften → *Digitale Signaturen* zeigt das). Nur wenn das Paket aus
   einer vertrauenswürdigen Quelle stammt: *Weitere Informationen* → *Trotzdem ausführen*.

Python oder Node.js sind nicht nötig. Für die volle Funktion braucht PartForge außerdem:

| Komponente | Wofür | Bezugsquelle |
| --- | --- | --- |
| WebView2-Runtime | Programmfenster | bei Windows 11 vorhanden; sonst <https://developer.microsoft.com/microsoft-edge/webview2/> (Evergreen-Runtime) |
| SQLite3 ODBC Driver (64 bit) | Altium liest damit die Datenbank | <http://www.ch-werner.de/sqliteodbc/> – `sqliteodbc_w64.exe` installieren |
| Altium Designer | Bibliotheken nutzen, „In Altium aktualisieren“, Prüfung | getestet mit Version 26.10 |
| altium-designer-mcp.exe | schreibt SchLib/PcbLib, ohne dass Altium laufen muss | <https://github.com/embedded-society/altium-designer-mcp/releases> – das Windows-Archiv der aktuellen Version laden und `altium-designer-mcp.exe` nach `%LOCALAPPDATA%\Programs\altium-designer-mcp\` kopieren (oder neben `PartForge.exe`); dort findet PartForge die Datei selbst. Ein anderer Ort wird unter *Einstellungen → Allgemein → Altium Designer* eingetragen. Das Programm steht unter der GPL-3.0 und wird deshalb nicht mitgeliefert. |
| Claude-API-Schlüssel | Datenblatt-Import und „Datenblatt suchen“ | <https://console.anthropic.com> – unter *Einstellungen → Allgemein → KI-Funktionen* eintragen; PartForge speichert ihn mit Windows-DPAPI verschlüsselt |

## Erste Schritte

1. **Bibliothek anlegen** – beim ersten Start „Neue Bibliothek anlegen“, einen Namen und einen Ordner wählen und
   „Beispielinhalte anlegen“ aktiviert lassen. PartForge legt Datenbank, DbLib, Symbole und Footprints an; die
   DbLib-Datei heißt standardmäßig wie die Bibliothek (`<Name>.DbLib`, im Dialog änderbar).
2. **In Altium einbinden** – Seite *Altium* → „In Altium installieren“ (oder in Altium unter
   *Components → File-based Libraries Preferences* die DbLib-Datei der Bibliothek hinzufügen).
3. **Serie erzeugen** – *Serien-Assistent* → Kategorie → Hersteller-Serie → E-Reihe, Bereich und Bauformen
   wählen → Vorschau → *Erzeugen*. Fehlende Footprints entstehen automatisch.
4. **Datenblatt importieren** – eine PDF-Datei ins Fenster ziehen oder „Datenblatt suchen“. Nach der Analyse
   die Vorschläge prüfen (Pins, Gehäuse, Footprint-Variante) und *Bauteil anlegen*.
5. **In Altium platzieren** – die Bauteile erscheinen im Components-Panel unter der DbLib der Bibliothek (z. B.
   `Firmenbibliothek.DbLib`). Änderungen aus PartForge übernimmt Altium automatisch („In Altium aktualisieren“).

Bauteile lassen sich aus CSV, Excel und ODS importieren und als CSV oder Excel exportieren. Jeden dieser Schritte
zeigt die [Bedienungsanleitung](BEDIENUNG.md) ausführlich mit Bildern.

## Zusammenarbeit mit Altium

- Altium liest die Datenbank über ODBC, PartForge schreibt gleichzeitig. Nach Änderungen sorgt PartForge dafür,
  dass ein laufendes Altium den neuen Stand sieht (abschaltbar unter *Einstellungen → Allgemein → Altium Designer*).
- Platzierte Bauteile merken sich die DbLib nur über ihren Dateinamen: den DbLib-Dateinamen, der beim Anlegen der
  Bibliothek gewählt wurde, später nicht mehr ändern und in Altium nur eine DbLib mit diesem Namen installieren.
- Bibliotheken, die in Altium ungespeicherte Änderungen haben, überschreibt PartForge nicht.
- Nach „Aus Altium deinstallieren“ hält Altium die Datenbank noch eine Weile offen – meist etwa eine Minute,
  manchmal bis Altium neu gestartet wird. Erst danach lässt sich der Bibliotheksordner verschieben oder
  umbenennen. PartForge meldet beim Deinstallieren, welcher Fall vorliegt.

## Wo PartForge Daten ablegt

| Ort | Inhalt |
| --- | --- |
| Bibliotheksordner (frei gewählt) | Datenbank, DbLib-Datei (`<Name>.DbLib`), Symbole, Footprints, 3D-Modelle, Datenblätter, Backups |
| `%APPDATA%\PartForge` | Einstellungen (`settings.json`), der verschlüsselte Claude-Schlüssel (`secret\`) und die Kosten der letzten Datenblattsuchen (`ai\search-costs.json`) |
| `%LOCALAPPDATA%\PartForge` | Protokolle (`logs\partforge.log`), Zwischenspeicher (Seitenbilder der Datenblätter, höchstens 512 MB; entpackte IntLib-/ZIP-Bibliotheken des Bibliotheksimports, nach zwei Tagen gelöscht), WebView-Profil des Fensters, temporäre Dateien, Austauschordner für Altium |

PartForge sendet nur beim Datenblatt-Import und bei „Datenblatt suchen“ Daten ins Internet (die ausgewählten
PDF-Seiten bzw. die Suchanfrage an die Claude-API).

## Aktualisieren

PartForge beenden, den alten Ordner `PartForge` durch den neuen ersetzen (nicht hineinkopieren, sondern den alten
vorher löschen) und starten. Einstellungen, Schlüssel und Bibliotheken bleiben erhalten.

## Deinstallieren

1. In PartForge auf der Seite *Altium* „Aus Altium deinstallieren“ wählen und die Bibliothek schließen.
2. Optional den gespeicherten Claude-Schlüssel entfernen: *Einstellungen → Allgemein → KI-Funktionen* →
   „Gespeicherten Schlüssel entfernen“.
3. PartForge beenden und den Ordner `PartForge` löschen.
4. Die Ordner `%APPDATA%\PartForge` und `%LOCALAPPDATA%\PartForge` löschen.
5. Die Bibliotheksordner bleiben erhalten; Altium kann sie auch ohne PartForge nutzen. altium-designer-mcp und
   den SQLite3 ODBC Driver bei Bedarf separat entfernen.

## Fehlerbehebung

| Problem | Lösung |
| --- | --- |
| Neue Bauteile fehlen in Altium | Seite *Altium* → „In Altium aktualisieren“; prüfen, dass die DbLib installiert ist. |
| Altium reagiert nicht auf PartForge | In Altium hängt vermutlich ein Skript im Debugger: Seite *Altium* → **Skript anhalten** (oder in Altium *Run → Stop*; Strg+F3 wirkt nur im aktiven Skript-Editor). |
| „database is locked“ | Die Bibliothek liegt auf einem Netzlaufwerk – Bibliotheksordner auf ein lokales Laufwerk legen. |
| Bibliotheksordner lässt sich nach „Aus Altium deinstallieren“ nicht verschieben („Zugriff verweigert“) | Altium hält die Datenbank noch offen. Meldung „Ordner erst in etwa einer Minute verschiebbar – Altium hält die Datenbank noch offen …“: kurz warten und erneut versuchen; klappt es dann noch nicht, Altium beenden und dann verschieben. Meldung „Ordner erst nach dem Schließen von … verschiebbar“: das genannte Programm schließen. Vorher in PartForge „Bibliothek schließen“. |
| SchLib/PcbLib werden nicht geschrieben | *Einstellungen → Allgemein → Altium Designer*: Pfad zu `altium-designer-mcp.exe` prüfen; die Bibliothek darf in Altium keine ungespeicherten Änderungen haben. |
| Datenblatt-Import nicht möglich | *Einstellungen → Allgemein → KI-Funktionen*: Schlüssel eintragen und „Verbindung testen“. |
| Fenster bleibt leer oder PartForge startet nicht | Den Ordner `PartForge` vollständig lassen (mit `_internal`); WebView2-Runtime installieren; Protokoll `%LOCALAPPDATA%\PartForge\logs\partforge.log` ansehen. |

## Lizenz

PartForge steht unter der MIT-Lizenz (`LICENSE`). Die mitgelieferten Komponenten und ihre Lizenzen nennt
`THIRD_PARTY_NOTICES.md`, die vollständigen Lizenztexte stehen in `THIRD_PARTY_LICENSES.txt`.
Altium und Altium Designer sind Marken der Altium Ltd. PartForge ist kein Produkt von Altium.
