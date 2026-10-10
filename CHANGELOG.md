# Änderungen

## Unveröffentlicht

### Neu

- **Englisch und Deutsch** (*Einstellungen › Allgemein › Profil und Darstellung › Sprache*): Oberfläche,
  Desktop-Dialoge, Meldungen und Zahlenformate in der gewählten Sprache. Standard ist Englisch – auch bestehende
  Installationen zeigen nach dem Update Englisch, bis „Deutsch“ gewählt und gespeichert ist.
- **STEP-Modelle in der 3D-Vorschau**: die Vorschau zeigt die STEP-Modelle eines Footprints mit ihrer
  Altium-Platzierung, auch eingebettete Modelle importierter Bibliotheken, die beim Import nicht abgelegt wurden;
  jedes Modell lässt sich herunterladen.
- **Bibliotheksimport** (neue Seite, Alt+9): Symbole und Footprints vorhandener Altium-Bibliotheken übernehmen – aus
  einem Ordner (rekursiv), einer SchLib/PcbLib, einer integrierten Bibliothek (IntLib), einem Bibliothekspaket
  (LibPkg) oder einem ZIP-Archiv. Vorschau je Bauteil, Zustand je Name (neu, schon importiert, Name vergeben,
  doppelt), Zielordner unter `Symbols\Import` / `Footprints\Import`, Dateien werden unverändert kopiert. Aus den
  importierten Symbolen entsteht auf Wunsch eine Tabelle für den Tabellenimport („Bauteile anlegen …“).
- **Stapelbearbeitung** (neue Seite, Alt+0): importierte Symbole und Footprints an den Hausstil angleichen –
  Schriften, Pinlänge von IC-Symbolen, Bezeichner-Präfixe, Farben, Lagen nach der Lagenzuordnung (Rollen der fremden
  Mechanik-Lagen werden erkannt und lassen sich umstellen), Linienbreiten, `.Designator`/`.Comment` in Hausschrift,
  fehlende Texte und Bauteilmitte, Lagen-Kopf. Erst prüfen, dann anwenden; verlustfrei auf Datensatzebene, jede Datei
  wird gesichert, die letzte Stapelbearbeitung lässt sich rückgängig machen.
- **Hausstil aus Beispielbibliothek** (*Einstellungen › Hausstil*): Schriften, Pinlängen, Farben, Lagen,
  Linienbreiten und Texte aus einer Bibliothek übernehmen, die so aussieht, wie alle Bauteile aussehen sollen
  (SchLib, PcbLib, IntLib, ZIP oder Ordner).
- **Lagensatz** (*Einstellungen › Hausstil › Lagen*): jede Footprint-Bibliothek erhält einen eigenen Altium-Lagensatz –
  „Component Layers“ aus der Lagenzuordnung oder ein Satz aus einer `.layerset`-Datei, auf Wunsch beim Öffnen aktiv.
- Hausstil: TrueType-Schrift für `.Designator`/`.Comment` der Footprints; Hausschrift auch für Pinnamen und
  -nummern der Symbole (Altium „Custom Font“), eingetragen in die Schrifttabelle der SchLib.

- Datenblatt-Import: **Einzeln speichern** – nur das Symbol (SchLib) oder nur den Footprint (PcbLib) eines Vorschlags
  speichern, ohne Bauteil; etwa das Symbol eines Datenblatts, dessen Gehäusezeichnung fehlt.
- Datenblatt-Import: **Gehäuse aus anderem Datenblatt übernehmen** – Maße, Herstellerempfehlung, Exposed-Pad-Nummer
  und Anschlussanordnung aus einer eigenen Gehäusezeichnung des Herstellers (z. B. TI „RGY0019B“) in das Datenblatt
  des Bauteils holen; passende Zeichnungen werden vorgeschlagen, die Herkunft angezeigt, die Übernahme lässt sich
  aufheben. Auch aus der Gehäusezeichnung heraus („Einem Bauteil geben …“) und in der Datenblattliste.
- Gehäusezeichnungen ohne Bauteil werden als solche erkannt: eigene Prüfansicht mit **Footprint speichern**.
- Footprint-Generator QFN/DFN: unregelmäßige Gehäuse mit **Anschlüssen je Seite**, eigenem **Raster oben/unten**,
  **Pin 1 an der oberen Seite** und **fehlenden Anschlüssen** (z. B. TI VQFN-19 RGY); im Datenblatt-Import als
  „Anschlussanordnung“ am Gehäuse.
- Herstellerempfehlung mit eigenem **Reihenabstand oben/unten** für rechteckige QFN/QFP.

### Geändert

- „Durchsuchen …“ öffnet den Dateidialog jetzt auch dort, wo bisher nichts geschah: externe Bibliotheken, `.stackup`,
  `X2.EXE` (der Dateifilter enthielt Zeichen, die das Programmfenster ablehnte).
- Schreibt PartForge in eine Bibliothek, bleiben alle anderen Bauteile darin Byte für Byte erhalten – auch in Altium
  gespeicherte mit TrueType-Texten, Mechanical 17–32, eingebetteten Schriften und Pinschriften (bisher setzte der
  Bibliotheks-Writer sie auf seinen eigenen Stand zurück).
- Footprints auf Mechanical 17–32 werden mit ihrer richtigen Lage gelesen (bisher „Mechanical 16“); TrueType-Texte
  bleiben beim Lesen und Zurückschreiben erhalten.
- Ein Dokument ohne Bauteil, aber mit Gehäusezeichnung ist kein Fehler mehr: keine bezahlte Nachkontrolle, und Claude
  erfindet kein Platzhalter-Bauteil.
- Ein rechteckiger QFN mit Herstellerempfehlung ohne Reihenabstand oben/unten wird abgelehnt, statt die Stirnseiten-Pins
  auf den falschen Abstand zu setzen.
- Die Übernahmeleiste zeigt ungültige Symbole/Footprints als „ungültig“ statt „vorhanden“; Gründe nennen den
  Gehäusenamen nicht mehr doppelt.

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
