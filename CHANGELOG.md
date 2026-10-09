# Änderungen

## 1.0.0 – 2026-10-09

Erste Version von PartForge: datenbankbasierte Bauteilbibliotheken (DbLib) für Altium Designer anlegen, pflegen und
prüfen. Windows 10/11, getestet mit Altium Designer 26.10.

### Was PartForge kann

#### Bibliothek

- Eine Bibliothek ist ein in sich geschlossener, verschiebbarer Ordner: SQLite-Datenbank, DbLib-Datei, SchLib/PcbLib,
  3D-Modelle (STEP), Datenblätter und Sicherungen. Auf Wunsch mit 19 Beispielbauteilen samt Symbolen und Footprints.
- 19 Kategorien (Widerstände, Kondensatoren, Dioden, ICs …) als eigene Tabellen mit Feldern, Einheiten und Vorlagen
  für Wert, Kommentar und Beschreibung; eigene Kategorien und Felder, eigenes Teilenummern-Schema.
- Eine Bibliothek ist immer nur in einem PartForge geöffnet – auch über Rechner hinweg.
- Mehrbenutzerbetrieb mit PostgreSQL (nur mit der Quellcode-Installation).

#### Bauteile

- Tabelle mit Suche, die Werte versteht („4k7“, „50V“), Filtern mit Größenvergleich, gespeicherten Ansichten und
  Bearbeitung direkt in der Tabelle; Detailbereich mit Vorschau von Symbol, Footprint und 3D sowie dem Verlauf jeder
  Änderung.
- Neues Bauteil mit Smart-Eingabe (`220n 50V X7R 0603 10%`); Massenänderungen und „Texte neu erzeugen“ mit
  Rückgängig; Löschen mit Rückgängig und Wiederherstellen aus dem Verlauf.
- Import aus CSV, TSV, Excel (XLSX) und ODS mit automatischer Spaltenzuordnung und Probelauf; Export als CSV
  (Excel-sicher) und XLSX.
- Bereichswerte mit ± in einer Grenze bleiben erhalten (symmetrische Versorgung: „2.8V to ±5.25V“ → „2.8V … ±5.25V“).

#### Serien-Assistent

- Ganze E-Reihen (E3–E192) einer Hersteller-Serie auf einmal: Vishay CRCW, Yageo RC, Panasonic ERJ, KOA, Stackpole,
  UniOhm, Bourns, KEMET, Yageo CC, Samsung CL, Murata GRM, Bourns SRR … mit den Teilenummern-Mustern und Codetabellen
  der Hersteller, 0-Ω-Brücken, passenden Footprints und Symbol. Eigene Serienvorlagen.

#### Datenblatt-Import mit Claude

- PDF ins Fenster ziehen, von einer Adresse laden oder „Datenblatt suchen“ (Websuche nach dem Hersteller-PDF).
- Claude liest Hersteller, Bestellvarianten, Parameter, Pinbelegung, Gehäusemaße und Land Pattern. Die Prüfansicht
  zeigt jede Angabe mit Fundstelle; der Vorschlag bringt Symbol, Footprint (IPC-7351B, Herstellerempfehlung oder ein
  vorhandener) und 3D-Körper mit; ein Klick legt alles an.
- Kostenschätzung vor der Analyse, Kostenlimit je Import (Standard 2,00 $); jede bezahlte Anfrage wird gespeichert,
  auch bei Abbruch.

#### Footprints und Symbole

- Footprint-Generator nach IPC-7351B (Dichte L/N/M) für 21 Gehäusefamilien mit 189 Vorlagen von 01005 bis BGA und
  THT, mit Berechnungsnachweis, 3D-Körper und STEP-Export; mechanische Lagen nach der eigenen `.stackup`-Vorlage.
- Rund 40 Standardsymbole im Hausstil, IC-Symbole aus Pinlisten mit automatischer Pin-Anordnung und Mehrteil-Symbolen.
- SchLib/PcbLib schreibt der Bibliotheks-Writer altium-designer-mcp – Altium muss dafür nicht laufen.

#### Altium

- DbLib erzeugen und aktuell halten, in Altium installieren und deinstallieren; ein laufendes Altium sieht Änderungen
  nach wenigen Sekunden, geöffnete und unveränderte Bibliotheken werden neu geladen.
- Prüfbericht (Pflichtfelder, Symbole, Footprints, Datenblätter, doppelte Teilenummern) und „In Altium prüfen“: Altium
  löst jedes Bauteil auf wie beim Platzieren.
- ODBC-Test und Vorschau der DbLib.

#### Bedienung und Sicherheit

- Deutsche Oberfläche in Dunkel und Hell, Befehlspalette (Strg+K) und Tastenkürzel; Bedienungsanleitung mit Bildern
  (`Handbuch\Bedienung.html` im Programmordner).
- Automatische Sicherungen vor riskanten Aktionen, Sicherungsstände je Bibliotheksdatei, Wiederherstellen.
- PartForge nimmt nur Verbindungen von diesem Rechner an (127.0.0.1, Sitzungstoken, Schutz vor fremden Websites und
  vor dem Einbetten); der Claude-Schlüssel wird mit Windows-DPAPI verschlüsselt gespeichert und nie an die Oberfläche
  gegeben.
- Programmpaket ohne Python und Node.js, mit den Lizenztexten aller mitgelieferten Komponenten.

### Bekannte Einschränkungen

- Der XLSX-Export sehr großer Tabellen ist langsam (etwa 6,5 s für 20 000 Zeilen); CSV ist deutlich schneller.
- Das Speichern in sehr große vorhandene PcbLib-Dateien dauert mehrere Sekunden – jede Änderung schreibt die ganze
  Datei.
- Automatische Sicherungen werden nicht komprimiert; jede belegt etwa so viel Platz wie die Datenbank.
- Der Murata-GRM-Katalog des Serien-Assistenten ist nicht gegen die Herstellerdaten geprüft – Teilenummern vor der
  Bestellung kontrollieren.
- Das Components-Panel und der Dialog „Update Parameters From Database“ in Altium sind nicht automatisch getestet
  (geprüft sind DbLib, ODBC-Zugriff und das Auflösen jedes Bauteils über „In Altium prüfen“).
- `PartForge.exe` ist nicht signiert; Windows SmartScreen kann beim ersten Start warnen.
- Der Bibliotheks-Writer altium-designer-mcp (GPL-3.0) wird nicht mitgeliefert und muss separat installiert werden.
