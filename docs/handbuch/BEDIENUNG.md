# PartForge – Bedienungsanleitung

Diese Anleitung zeigt Schritt für Schritt, wie Sie mit PartForge eine Altium-Datenbankbibliothek anlegen und pflegen.
Installation, Datenablage und Deinstallation beschreibt das [Handbuch zum Programmpaket](README.md).

## Inhalt

1. [Überblick](#1-überblick)
2. [Erster Start und Bibliothek anlegen](#2-erster-start-und-bibliothek-anlegen)
3. [Übersicht](#3-übersicht)
4. [Bauteile verwalten](#4-bauteile-verwalten)
5. [Widerstandsserie anlegen](#5-widerstandsserie-anlegen)
6. [Bauteil aus Datenblatt](#6-bauteil-aus-datenblatt)
7. [Symbole und Footprints](#7-symbole-und-footprints)
8. [Altium](#8-altium)
9. [Einstellungen und Sicherungen](#9-einstellungen-und-sicherungen)
10. [Befehlspalette und Tastenkürzel](#10-befehlspalette-und-tastenkürzel)
11. [Häufige Fragen und Fehlerbehebung](#11-häufige-fragen-und-fehlerbehebung)

---

## 1. Überblick

PartForge legt Bauteile für Altium Designer an und hält sie aktuell – einzeln, als komplette Serie oder direkt aus
einem PDF-Datenblatt. Zu jedem Bauteil gehören ein Schaltplansymbol, ein Footprint nach IPC-7351B und ein
3D-Körper. Vorhandene Altium-Bibliotheken übernehmen Sie mit dem **Bibliotheksimport** und gleichen sie in einem
Arbeitsgang an Ihren Hausstil an (**Stapelbearbeitung**).

So arbeiten PartForge und Altium zusammen:

| Teil | Was es ist |
| --- | --- |
| Datenbank (`PartForge.sqlite`) | alle Bauteile mit ihren Werten, eine Tabelle je Kategorie |
| DbLib-Datei (z. B. `Firmenbibliothek.DbLib`) | sagt Altium, wo die Datenbank liegt und welche Spalten was bedeuten |
| SchLib/PcbLib (Ordner `Symbols`, `Footprints`) | die Symbole und Footprints, auf die die Bauteile verweisen |

Altium liest die Datenbank über den SQLite-ODBC-Treiber. In Altium müssen Sie nichts einrichten: PartForge installiert
die DbLib auf Knopfdruck und sorgt nach jeder Änderung dafür, dass Altium den neuen Stand sieht. Die Bibliothek
funktioniert auch ohne PartForge – es ist eine ganz normale Altium-DbLib.

Die KI (Claude) brauchen Sie nur für den Datenblatt-Import und die Datenblattsuche. Alles andere läuft offline.

## 2. Erster Start und Bibliothek anlegen

Beim ersten Start ist noch keine Bibliothek offen, PartForge zeigt die Willkommensseite.

![Willkommensseite](bilder/01-willkommen.png)

1. Klicken Sie auf **Neue Bibliothek anlegen …**.
2. Geben Sie einen **Name** ein, z. B. „Firmenbibliothek“. Ordner und DbLib-Datei heißen standardmäßig genauso. Den
   Namen der DbLib-Datei können Sie hier noch ändern; danach sollte er gleich bleiben, denn platzierte Bauteile finden
   ihre DbLib nur über den Dateinamen.
3. Prüfen Sie den **Ordner** (vorgeschlagen wird `Dokumente\PartForge\<Name>`). Mit **Durchsuchen …** wählen Sie
   einen anderen. Der Ordner muss auf einem lokalen Laufwerk liegen.
4. Lassen Sie **Beispielinhalte anlegen** eingeschaltet. Sie bekommen 19 echte Bauteile (Widerstände, Kondensatoren,
   Dioden, ICs …) mit fertigen Symbolen und Footprints – ideal zum Ausprobieren.
5. Klicken Sie auf **Bibliothek anlegen**.

![Neue Bibliothek anlegen](bilder/02-neue-bibliothek.png)

PartForge legt Datenbank, DbLib, Symbole und Footprints an und schreibt die Bibliotheksdateien. Mit
**Zur Übersicht** geht es weiter.

![Bibliothek angelegt](bilder/03-bibliothek-angelegt.png)

**ODBC-Treiber:** Fehlt auf Ihrem Rechner der „SQLite3 ODBC Driver“ (64 Bit), sagt Ihnen die Erfolgsmeldung das und
verlinkt den Download. Ohne ihn kann Altium die Datenbank nicht lesen.

**KI-Schlüssel (optional):** Für den Datenblatt-Import tragen Sie unter *Einstellungen › Allgemein › KI-Funktionen*
mit **Schlüssel eingeben …** einen Claude-API-Schlüssel ein und prüfen ihn mit **Verbindung testen**. Ohne Schlüssel
funktioniert alles außer der Datenblatt-Analyse und der Datenblattsuche.

Eine vorhandene Bibliothek öffnen Sie mit **Bibliothek öffnen …**. Zwischen Bibliotheken wechseln Sie oben links
über den Bibliotheks-Umschalter.

## 3. Übersicht

Die Übersicht zeigt auf einen Blick, wie es um Ihre Bibliothek steht:

- **Kennzahlen**: Bauteile, Kategorien, Symbole, Footprints und Probleme – ein Klick führt zur passenden Seite.
- **Bauteile je Kategorie** und **Letzte Änderungen** (auch gelöschte Bauteile lassen sich hier wiederherstellen).
- **Bibliotheksgesundheit**: Ergebnis der Prüfung auf fehlende Pflichtfelder, Symbole, Footprints und Datenblätter.
- **Altium und DbLib**: läuft Altium, ist die DbLib installiert und aktuell?
- Oben rechts: **Serie erzeugen** und **Datenblatt importieren**.

![Übersicht (helle Darstellung)](bilder/04-uebersicht.png)

Unten links in der Seitenleiste sehen Sie immer den Zustand von Datenbank, Altium und KI.

## 4. Bauteile verwalten

### Tabelle, Suche und Filter

1. Öffnen Sie **Bauteile** und wählen Sie links eine Kategorie.
2. Tippen Sie in das Suchfeld (**Strg+F**). Sie können nach Text und nach Werten suchen: „4k7“ findet alle
   4,7-kΩ-Widerstände, „50V“ alle Bauteile mit 50 V.
3. Mit **Filter** setzen Sie Bedingungen wie „Widerstand mindestens 10k“. Häufige Filter speichern Sie unter
   **Ansichten**, die sichtbaren Spalten wählen Sie unter **Spalten**.

![Bauteiltabelle (helle Darstellung)](bilder/05-bauteile-tabelle.png)

![Suche nach einem Wert](bilder/07-suche.png)

### Bearbeiten im Detailbereich

Ein Klick auf eine Zeile öffnet rechts den Detailbereich: Vorschau von Symbol, Footprint und 3D, alle Felder
(gruppiert) und unter **Verlauf** jede Änderung mit Datum und Bearbeiter. Eine Änderung wird gespeichert, sobald Sie
das Feld verlassen oder Enter drücken.
Über **Duplizieren** legen Sie eine Variante an, über das Freigabe-Menü (z. B. „Entwurf“) setzen Sie den Status.

![Detailbereich](bilder/06-bauteil-details.png)

Wert, Kommentar und Beschreibung erzeugt PartForge aus den Vorlagen der Kategorie, z. B.
„RES 0603 10kΩ ±1% 0.1W Dickschicht“. Im Schaltplan sichtbar ist nur der Kommentar (z. B. „10k“).

### Neues Bauteil

1. Klicken Sie auf **Neues Bauteil** (**Strg+N**) und wählen Sie die Kategorie.
2. Tippen Sie die Werte in die **Smart-Eingabe**, z. B. `220n 50V X7R 0603 10%`. PartForge verteilt sie auf die
   Felder (markiert mit „erkannt“) und schlägt Symbol und Footprint vor.
3. Ergänzen Sie **Hersteller** und **Hersteller-Teilenummer**. Bleibt die Teilenummer leer, gilt die
   Hersteller-Teilenummer.
4. Rechts sehen Sie Symbol, Footprint und die erzeugten Texte. Steht dort „Bereit zum Anlegen“, klicken Sie auf
   **Bauteil anlegen** (**Strg+Enter**).

![Neues Bauteil mit Smart-Eingabe](bilder/08-neues-bauteil.png)

### Massenänderung

1. Haken Sie die gewünschten Zeilen an (das Kästchen im Tabellenkopf wählt alle geladenen Zeilen).
2. Klicken Sie in der Leiste unten auf **Bearbeiten**.
3. Wählen Sie ein Feld und den neuen Wert, mit **Weiteres Feld** mehrere auf einmal, und bestätigen Sie mit
   **… Bauteile ändern**.

![Massenänderung](bilder/09-massenaenderung.png)

Direkt danach nimmt **Rückgängig** in der Meldung die Massenänderung zurück; Bauteile, die inzwischen erneut geändert
wurden, lässt PartForge dabei unverändert und nennt sie. Ändert eine Massenänderung mehr als 20 Bauteile, sichert
PartForge vorher außerdem automatisch die Datenbank (Kapitel 9).

### Löschen und Wiederherstellen

1. Zeilen anhaken und **Löschen** wählen (oder **Entf**), dann bestätigen.
2. Direkt danach holt **Rückgängig** in der Meldung die Bauteile mit allen Werten zurück.
3. Später geht das über *Übersicht › Letzte Änderungen*: das gelöschte Bauteil öffnen und **Wiederherstellen**
   wählen.

![Gelöscht – mit Rückgängig](bilder/10-loeschen-rueckgaengig.png)

### Import und Export (CSV, Excel)

**Import:** Klicken Sie auf **Import**, ziehen Sie eine CSV-, TSV-, XLSX- oder ODS-Datei in das Fenster und folgen
Sie den Schritten *Datei → Zuordnung → Prüfen → Import*.

- PartForge ordnet die Spalten selbst den Feldern zu, Einheiten im Spaltenkopf („Kapazität (pF)“) werden beachtet.
- Fehlt eine Pflichtspalte, setzen Sie unter **Feste Werte für alle Zeilen** einen Wert für alle (z. B. das Symbol).
- Vor dem Import zeigt ein Probelauf je Zeile, was passiert („neu“, „aktualisiert“, „abgelehnt“). Sie entscheiden,
  ob vorhandene Teilenummern übersprungen oder aktualisiert werden.
- Vor dem Import legt PartForge eine Sicherung an.

![Import – Prüfen](bilder/11-import-csv.png)

**Export:** **Export** › **Excel-Datei (XLSX)** oder **CSV-Datei** (Semikolon, UTF-8). Suche, Filter und Sortierung
der Tabelle gelten auch für den Export; mit **Nur sichtbare Spalten** exportieren Sie nur, was Sie sehen.

## 5. Widerstandsserie anlegen

Mit dem Serien-Assistenten legen Sie eine komplette Bauteilserie in einem Rutsch an – hier alle Vishay-Widerstände
CRCW in 0603, E24, von 1 Ω bis 10 MΩ, plus 0-Ω-Brücke. PartForge kennt das Teilenummern-Muster, die Codetabellen und
die lieferbaren Werte der Hersteller-Serie.

**Schritt 1 – Kategorie.** Öffnen Sie den **Serien-Assistent** und wählen Sie **Widerstände**.

![Serien-Assistent: Kategorie](bilder/12-serie-kategorie.png)

Tipp: Unter **Schnellstart aus einer Teilenummer** können Sie auch eine Teilenummer wie `CRCW060310K0FKEA`
einfügen – Serie, Baugröße, Toleranz und Verpackung werden übernommen.

**Schritt 2 – Hersteller-Serie.** Wählen Sie die Karte **VISHAY D/CRCW e3**. Jede Karte zeigt eine
Beispiel-Teilenummer mit ihren Bestandteilen und das Datenblatt, gegen das die Vorlage geprüft ist. Klicken Sie auf
**Weiter: Werte festlegen**.

![Serien-Assistent: Hersteller-Serie](bilder/13-serie-hersteller.png)

**Schritt 3 – Werte und Varianten.**

1. Unter **Bauformen** auf **Keine** klicken und dann **0603** wählen.
2. Unter **Widerstandswerte** die E-Reihe **E24** wählen. **Von**/**Bis** bleiben leer – dann gilt der ganze Bereich
   der Serie. Technische Schreibweise geht auch, z. B. `4k7` oder `1M`.
3. Unter **Varianten** die Toleranz wählen (hier ±1 %), Temperaturkoeffizient und Verpackung kommen aus dem
   Datenblatt.
4. **0-Ω-Brücken mit anlegen** einschalten, wenn Sie eine Brücke je Bauform brauchen.

Rechts rechnet der Zähler sofort mit: 1 Bauform × 169 Werte + 1 Brücke = 170 Bauteile. Darunter sehen Sie, ob
Footprints neu entstehen und welches Symbol verwendet wird. Weiter mit **Weiter: Vorschau**.

![Serien-Assistent: Werte und Varianten](bilder/14-serie-werte.png)

**Schritt 4 – Vorschau.** Hier stehen alle Zeilen, bevor etwas geschrieben wird – mit Status *Neu*, *Vorhanden*,
*Konflikte* oder *Ungültig*, dazu Symbol und Footprints. Weiter mit **Weiter: Erzeugen**.

![Serien-Assistent: Vorschau](bilder/15-serie-vorschau.png)

**Schritt 5 – Erzeugen.** Die Zusammenfassung nennt, was geschrieben wird. Klicken Sie auf **Serie erzeugen**
(**Strg+Enter**).

![Serien-Assistent: Erzeugen](bilder/16-serie-erzeugen.png)

PartForge sichert zuerst die Datenbank, legt fehlende Footprints und das Symbol an und schreibt dann die Bauteile.
Läuft Altium und ist die DbLib installiert, erscheinen die neuen Bauteile dort automatisch; ist sie nicht installiert,
sagt die Erfolgsansicht das und bietet **In Altium installieren** an. Mit **In Tabelle anzeigen** sehen Sie das
Ergebnis, mit **Neue Serie** beginnen Sie die nächste.

![Serie angelegt](bilder/17-serie-fertig.png)

Kondensator- und Induktivitätsserien funktionieren genauso. Fehlt eine Hersteller-Serie, legen Sie sie mit
**Eigene Vorlage** selbst an.

## 6. Bauteil aus Datenblatt

Aus einem PDF-Datenblatt erzeugt PartForge mit Claude komplette Bauteile: alle Bestellvarianten, Parameter, Symbol,
Footprint und 3D-Körper. Beispiel: der Operationsverstärker OPA656 von Texas Instruments.

**1. PDF ablegen.** Ziehen Sie die PDF-Datei einfach irgendwo ins PartForge-Fenster und lassen Sie sie los. Alternativ
auf der Seite **Datenblatt-Import**: **Datei auswählen**, eine Adresse unter **Aus URL laden** eingeben oder unter
**Datenblatt suchen** die Teilenummer eingeben – dann sucht Claude das offizielle PDF im Web (höchstens 0,50 $ je
Suche).

![Datenblatt ins Fenster ziehen](bilder/18-datenblatt-ablegen.png)

**2. KI-Analyse.** Claude liest das Datenblatt. Sie sehen die Schritte, die gelesenen Seiten, was schon erkannt
wurde, die Laufzeit und die **Kosten bisher** mit dem Kostenlimit (Standard 2,00 $ je Import). Eine typische Analyse
dauert etwa eine halbe Minute und kostet ein paar Cent bis rund 0,25 $. Mit **Abbrechen** stoppen Sie sie; bezahlte
Anfragen bleiben gespeichert.

![KI-Analyse läuft](bilder/19-ki-analyse.png)

**3. Prüfen.** Die Prüfansicht hat drei Spalten: links die PDF-Seiten, in der Mitte die erkannten Daten
(**Identität**, **Varianten**, **Parameter**, **Pins**, **Gehäuse**, **Hinweise**), rechts die Vorschau von Symbol,
Footprint und 3D.

- Jede Angabe hat ihre Fundstelle (z. B. „S. 2“) – ein Klick zeigt die Seite groß.
- Unter **Varianten** wählen Sie die Bestellnummern, die angelegt werden sollen.
- Unter **Pins** und **Gehäuse** kontrollieren Sie Pinbelegung und Maße. Werte korrigieren Sie per Klick;
  **Strg+Z** nimmt die letzte Korrektur zurück.
- Für den Footprint wählen Sie **IPC-7351B** (berechnet), **Hersteller** (Land Pattern aus dem Datenblatt) oder
  **Vorhanden** (ein Footprint aus Ihrer Bibliothek).

![Prüfansicht](bilder/20-pruefansicht.png)

![Gehäusemaße und Footprint-Vorschau](bilder/21-gehaeuse.png)

Meldet PartForge Probleme (z. B. Pins ohne Pad), müssen Sie jedes bestätigen, bevor angelegt werden kann.

**4. Bauteile anlegen.** Steht unten „Bereit zum Anlegen“, klicken Sie auf **… Bauteile anlegen** (**Strg+Enter**).
PartForge schreibt Symbol und Footprint in die Bibliotheksdateien und legt die Bauteile an – mit Link zum
Datenblatt.

![Bauteile angelegt](bilder/23-bauteile-angelegt.png)

**Nur Symbol oder nur Footprint speichern.** Über **Einzeln speichern** neben „Bauteile anlegen“ schreibt PartForge
nur das Symbol in die SchLib oder nur den Footprint in die PcbLib – ohne Bauteil in der Datenbank. Das hilft, wenn
noch etwas fehlt: Hat das Datenblatt z. B. keine Maßzeichnung, lässt sich das Symbol trotzdem schon speichern. Ein
gesperrter Eintrag nennt den Grund.

**Gehäusezeichnung in einem eigenen Dokument.** Manche Hersteller – etwa Texas Instruments – veröffentlichen die
Gehäusezeichnung als eigenes PDF (z. B. „RGY0019B“ zum LM25190-Q1). So entsteht trotzdem das vollständige Bauteil:

1. Das Datenblatt des Bauteils und die Gehäusezeichnung importieren und analysieren. Eine reine Gehäusezeichnung
   erkennt PartForge: Ihre Prüfansicht zeigt nur das Gehäuse, **Footprint speichern** schreibt den Footprint in die
   PcbLib.
2. In der Prüfansicht des Bauteils unter **Gehäuse** auf **Maße übernehmen …** klicken (fehlen Maße, steht dort ein
   Hinweis mit demselben Knopf). PartForge zeigt die passenden Zeichnungen der anderen Datenblätter, die beste zuerst,
   und übernimmt Maße, Herstellerempfehlung, Exposed-Pad-Nummer und Anschlussanordnung. Aus der Gehäusezeichnung
   heraus geht es umgekehrt mit **Einem Bauteil geben …** – oder in der Liste *Bisherige Datenblätter* über das
   Menü **…**.
3. Danach steht unten „Bereit zum Anlegen“. Das Gehäuse trägt den Hinweis „aus qfnd819.pdf“; darüber sehen Sie die
   Zeichnung, wählen eine andere oder heben die Übernahme wieder auf.

**Unregelmäßige QFN.** Sind die Anschlüsse nicht gleichmäßig auf vier Seiten verteilt (TI RGY: Pin 1 und 19 an der
oberen Stirnseite im Abstand 1,5 mm, rechts eine Position frei), tragen Sie unter **Gehäuse › Anschlussanordnung**
ein: Anschlüsse oben/unten und links/rechts je Seite, das Raster oben/unten, die Lage von Pin 1 und die fehlenden
Positionen – gezählt ab Pin 1 gegen den Uhrzeigersinn, als wären alle bestückt. Für RGY0019B: 2 und 8 je Seite,
1,5 mm, Pin 1 „Obere Seite, links“, fehlend 14. Für die Herstellerempfehlung braucht ein rechteckiges QFN zusätzlich
den **Reihenabstand oben/unten**. Dieselben Angaben gibt es im Footprint-Generator (Familie QFN/DFN).

**Kosten:** Der Betrag oben in der Kopfzeile (z. B. „0,23 $“) zeigt die Kosten der Analyse, aufgeteilt nach
Anfragen. **Neu analysieren** zeigt vor dem Start die erwarteten Kosten und lässt Sie Seiten, Modell,
Gründlichkeit und Kostenlimit wählen.

![Neu analysieren mit Kostenschätzung](bilder/22-neu-analysieren.png)

**Ohne KI-Schlüssel:** Das PDF wird trotzdem gespeichert und erscheint unter *Bisherige Datenblätter* als
„Noch nicht analysiert“. Ein Knopf führt zu den Einstellungen, um den Claude-API-Schlüssel zu hinterlegen; danach
starten Sie die Analyse mit **Mit Claude analysieren**. Datenblätter verlassen Ihren Rechner nur bei dieser Analyse.

## 7. Symbole und Footprints

**Symbole** (Seite *Symbole*): Unter **Generator** wählen Sie links einen von 40 Standardtypen (Widerstand, Diode,
OPV, Steckverbinder …) oder **IC (Pinliste)**. Für ICs geben Sie die Pins ein oder fügen sie mit **Einfügen …** aus
einer Tabelle ein; PartForge ordnet sie automatisch an (Versorgung oben links, Masse unten, Eingänge links, Ausgänge
rechts). Mit **In Bibliothek speichern** (**Strg+S**) landet das Symbol in der SchLib. Unter **Bibliothek** sehen Sie
alle Symbole mit ihrer Verwendung.

![IC-Symbol aus Pinliste](bilder/25-ic-symbol.png)

![Symbolbibliothek](bilder/24-symbolbibliothek.png)

**Footprints** (Seite *Footprints*): Gehäusefamilie wählen (21 Familien, 189 Vorlagen – von 0402 über SOT-23 bis
QFN und BGA), Vorlage anklicken, bei Bedarf Maße (min/nom/max) aus dem Datenblatt eintragen und die Dichte wählen
(**Klein (L)**, **Nominal (N)**, **Groß (M)**). PartForge rechnet nach IPC-7351B und zeigt Lötflächen, Courtyard und
den IPC-Namen. Eine Herstellerempfehlung ersetzt auf Wunsch die Berechnung. **In Bibliothek speichern** schreibt in
die PcbLib, **STEP herunterladen** liefert das 3D-Modell.

![Footprint-Generator](bilder/26-footprint-generator.png)

![3D-Ansicht](bilder/27-footprint-3d.png)

**Importierte 3D-Modelle:** Öffnen Sie bei einem Bauteil oder einem Footprint aus der Bibliothek den Reiter
**3D**. PartForge zeigt die tatsächliche STEP-Geometrie; mehrere Modelle eines Footprints werden mit ihren
jeweiligen Drehungen und Positionen dargestellt. Eingebettete Modelle werden beim ersten Öffnen aus der
importierten PcbLib gelesen und lokal zwischengespeichert. Das funktioniert auch bei bereits importierten
Bibliotheken, für die **3D-Modelle vorab ablegen** ausgeschaltet war – ein erneuter Import ist nicht nötig.
Die PcbLib bleibt unverändert, und für die Darstellung ist keine Internetverbindung erforderlich.

Kann ein Modell nicht geladen werden, zeigt die Vorschau die Ursache an. Bei einem verknüpften statt eingebetteten
STEP-Modell muss die referenzierte `.step`- oder `.stp`-Datei noch erreichbar sein; stellen Sie die Datei am
ursprünglich verknüpften Ort wieder bereit. Für das Lesen eingebetteter Modelle muss der Bibliotheks-Writer eingerichtet sein.
Die interaktive 3D-Ansicht benötigt WebGL im Browser bzw. in WebView2; ohne WebGL bleiben die 2D-Vorschau und
der Download vorhandener STEP-Dateien verfügbar.

**Hausstil:** Linienbreiten, Pin-1-Markierung, Namensschema, Symbolfarben, Schriften und die Zuordnung der
mechanischen Lagen stellen Sie einmal unter *Einstellungen › Hausstil* ein (Reiter Footprints, Lagen, Symbole). Alle
neuen Symbole und Footprints folgen ihm.

- **Schriften:** Im Reiter *Symbole* legen Sie die Hausschrift für Bezeichner, Kommentar und Parameter fest und ob
  Pinnamen und -nummern sie ebenfalls verwenden (*Hausschrift*) oder die Schrift des Schaltplanblatts
  (*Systemschrift*). Im Reiter *Footprints* wählen Sie für `.Designator` und `.Comment` Strichschrift oder eine
  TrueType-Schrift (z. B. Arial) und die Texthöhe.
- **Lagensatz:** Im Reiter *Lagen* wählt die Karte **Lagensatz**, welchen Altium-Lagensatz („View Configuration ›
  Layer Sets“) jede Footprint-Bibliothek erhält: *Keiner*, *Aus Zuordnung* („Component Layers“ – Kupfer, Paste,
  Lötstopp, Bestückungsdruck, Bohrlagen und alle Mechanik-Lagen der Zuordnung) oder *Aus Datei* (Ihre `.layerset`-Datei,
  z. B. `Component.layerset`; enthält sie mehrere Sätze, wählen Sie einen aus). Mit **Beim Öffnen aktiv** zeigt Altium
  beim Öffnen der Bibliothek nur diese Lagen. Neue Footprint-Bibliotheken erhalten den Satz automatisch, vorhandene
  über **Auf Bibliotheken anwenden …** oder die Stapelbearbeitung.
- **Aus Beispielbibliothek …:** Haben Sie ein Bauteil schon so in Altium angelegt, wie alle aussehen sollen, wählen
  Sie oben rechts **Aus Beispielbibliothek …** und geben die Bibliothek an (`.SchLib`, `.PcbLib`, `.IntLib`, ein
  `.zip` davon oder einen Ordner). PartForge liest Schriften, Pinlängen, Farben, Linienbreiten, Texte und die
  Lagen und zeigt, was vom Hausstil abweicht – mit Beleg. Übernehmen Sie die gewünschten Werte und speichern Sie wie
  gewohnt (**Strg+S**). Die Beispielbibliothek bleibt unverändert.

### In Altium bearbeiten

Was der Generator nicht kann – eine Sonderform des Bestückungsdrucks, ein anderes 3D-Modell, eine eigene
Pin-Anordnung –, ändern Sie direkt in Altium Designer:

1. Öffnen Sie unter **Bibliothek** das Symbol bzw. den Footprint und klicken Sie auf **In Altium bearbeiten**.
   Altium muss laufen; PartForge öffnet die SchLib/PcbLib, zeigt das Bauteil und holt Altium nach vorn.
2. Ändern Sie das Bauteil in Altium und speichern Sie (**Strg+S**). Sie können mehrmals speichern.
3. Wenige Sekunden nach jedem Speichern übernimmt PartForge die Änderungen: Vorschau, Pins bzw. Pads, Bauhöhe und
   3D-Modell kommen aus der gespeicherten Datei, die Herkunft lautet *In Altium bearbeitet*. Eine Meldung nennt die
   übernommenen Bauteile – auch andere, die Sie in derselben Datei geändert oder neu angelegt haben.

Solange PartForge die Datei beobachtet, zeigt die Detailansicht **In Altium geöffnet** mit **Jetzt übernehmen** und
**Bearbeitung beenden**; in der Bibliothek tragen solche Bauteile das Abzeichen *In Altium geöffnet*. Die Beobachtung
übersteht einen Neustart von PartForge und endet von selbst, wenn Altium beendet wird oder zwölf Stunden lang nicht
gespeichert wurde.

Gut zu wissen:

- Das Bauteil, das Sie mit **In Altium bearbeiten** geöffnet haben, gilt nach jedem Speichern als bearbeitet – so
  geht auch eine Änderung nicht verloren, die PartForge nicht darstellen kann (etwa am 3D-Modell). Bei den übrigen
  Bauteilen derselben Datei zählt nur eine Änderung an Geometrie, Pins/Pads, Texten, Beschreibung oder Bauhöhe; ein
  bloßes Neuspeichern nicht (Altium schreibt die Datei dabei komplett neu, PartForge erkennt das). Ändern Sie an einem
  anderen Bauteil nur das 3D-Modell, öffnen Sie es dafür ebenfalls mit **In Altium bearbeiten**.
- **Bearbeiten** (Generator) und **Neu generieren** ersetzen eine in Altium bearbeitete Fassung erst nach Rückfrage;
  die vorherige Datei bleibt in `Backups\lib`.
- Benennen Sie ein Bauteil in Altium um, meldet PartForge das: Der neue Name wird übernommen, Bauteile verweisen aber
  weiter auf den alten Namen (Status *Fehlt*) – passen Sie die Verweise an oder benennen Sie es zurück.
- Ändern Sie in Altium die Pins eines Symbols, nennt die Meldung die Änderung und wie viele Bauteile es verwenden;
  die Bibliotheksprüfung zeigt danach unpassende Pin/Pad-Zuordnungen.
- Bauteile externer Bibliotheken und noch nicht synchronisierte Bauteile lassen sich so nicht bearbeiten.

### Bibliotheken importieren

Die Seite **Bibliotheksimport** übernimmt Symbole und Footprints vorhandener Altium-Bibliotheken – etwa einer
Hersteller-Bibliothek oder einer großen Sammlung wie der Celestial-Bibliothek.

1. **Quelle wählen:** einen Ordner (wird mit allen Unterordnern durchsucht), eine `.SchLib`/`.PcbLib`, eine
   integrierte Bibliothek (`.IntLib`), ein Bibliothekspaket (`.LibPkg`) oder ein `.zip`-Archiv, dann **Einlesen**.
   Die Quelle wird nur gelesen. Eine `.DbLib` lässt sich nicht importieren (ihre Bauteildaten liegen in einer
   Datenbank) – wählen Sie den Ordner mit ihren SchLib/PcbLib-Dateien.
2. **Prüfen:** PartForge zeigt jede Datei mit ihren Symbolen bzw. Footprints und eine Vorschau. Jeder Name hat einen
   Zustand: *neu*, *schon importiert* (aus derselben Datei), *Name vergeben* (gibt es in Ihrer Bibliothek schon –
   Altium findet Symbole und Footprints nur über den Namen, darum wird er nicht übernommen) oder *doppelt* (mehrfach
   in der Quelle; übernommen wird der erste).
3. **Importieren:** Dateien auswählen, den **Zielordner** festlegen (die Dateien landen in `Symbols\Import\<Ziel>` und
   `Footprints\Import\<Ziel>`) und **Importieren**. Optional: geänderte, schon importierte Dateien ersetzen,
   **3D-Modelle vorab ablegen** und **danach an den Hausstil angleichen** (Regeln der letzten
   Stapelbearbeitung).

**3D-Modelle vorab ablegen** speichert eingebettete STEP-Dateien schon beim Import im Ordner `3D`.
Die Option ist standardmäßig aus: Die 3D-Vorschau lädt benötigte Modelle auch ohne sie aus der importierten
PcbLib. So müssen bei großen Bibliotheken nicht sofort alle Modelle entpackt werden.

Die Dateien werden unverändert kopiert – Schriften, Lagen und 3D-Modelle bleiben, wie sie sind. Mit **Bauteile
anlegen …** erzeugt PartForge aus den importierten Symbolen eine Tabelle (Teilenummer, Symbol, Footprint, Parameter)
und öffnet damit den Tabellenimport ([Import und Export](#import-und-export-csv-excel)): Sie wählen die Kategorie und
ordnen die Spalten zu.

### Stapelbearbeitung: an den Hausstil angleichen

Die Seite **Stapelbearbeitung** passt importierte (auf Wunsch auch eigene) Symbole und Footprints in einem Arbeitsgang
an Ihren Hausstil an.

1. **Auswahl:** Symbole und/oder Footprints, Herkunft (Standard: *Importiert*) und bei Bedarf einzelne Bibliotheken.
2. **Regeln:** Symbole – Schriften, Pinlänge von IC-Symbolen, Bezeichner-Präfix (z. B. `IC` → `U`), auf Wunsch
   Farben. Footprints – Lagen nach der Zuordnung, Linienbreiten, Texte in Hausschrift und -höhe, fehlende Texte und
   Bauteilmitte ergänzen, Lagen-Kopf (Lagenaufbau und Lagensatz).
3. **Prüfen:** Der Bericht zeigt je Bauteil, was sich ändert, und je Footprint-Bibliothek, welche Rolle PartForge
   jeder ihrer Mechanik-Lagen zuordnet (aus Lagentyp, Lagenname oder Inhalt: der äußere Umriss ist der Courtyard, der
   innere die Bestückungszeichnung). Eine falsch erkannte Rolle stellen Sie direkt im Bericht um und prüfen erneut.
4. **Anwenden:** Jede Datei wird vorher gesichert (`Backups\lib`). Geändert wird nur, was eine Regel betrifft –
   alles andere bleibt Byte für Byte erhalten, Namen ändern sich nie. Bibliotheken, die in Altium geöffnet **und**
   geändert sind, werden übersprungen; geöffnete, unveränderte lädt Altium danach neu.
5. **Rückgängig:** Die letzte Stapelbearbeitung lässt sich zurücknehmen, solange die Dateien seither unverändert
   sind.

## 8. Altium

Die Seite **Altium** zeigt die Kette Bauteile → DbLib → Bibliotheksdateien → Altium Designer und was zu tun ist.

![Altium-Seite](bilder/28-altium.png)

**Installieren:** Klicken Sie auf **In Altium installieren**. Danach steht die Bibliothek im Components-Panel von
Altium.

**Automatisch aktualisieren:** Ist der Schalter an, sieht ein laufendes Altium jede Änderung aus PartForge nach
wenigen Sekunden. Von Hand geht es mit **Aktualisieren**.

**Prüfen:**

- Der **Prüfbericht** findet fehlende Pflichtfelder, Symbole, Footprints, Datenblätter und doppelte Teilenummern –
  meist mit direktem Weg zur Lösung.
- **In Altium prüfen** lässt Altium jedes Bauteil auflösen, genau wie beim Platzieren (Stichprobe, alle Bauteile oder
  eine Kategorie). Im Reiter **In Altium geprüft** sehen Sie je Bauteil Symbol, Pins, Footprints sowie Comment und
  Beschreibung. Ein Klick auf „… Parameter“ vergleicht alle Parameter in Altium mit der Datenbank.

![In Altium geprüft](bilder/29-in-altium-geprueft.png)

**DbLib:** **Neu erzeugen** schreibt die DbLib neu, **Vorschau** zeigt ihren Inhalt, **ODBC testen** liest die
Datenbank so wie Altium.

**Deinstallieren:** Mit **Deinstallieren** entfernen Sie die DbLib aus Altium. Altium hält die Datenbank danach noch
eine Weile offen (meist etwa eine Minute); erst dann lässt sich der Ordner verschieben.

**Bauteil in Altium platzieren:** In Altium das Panel *Components* öffnen, oben die DbLib Ihrer Bibliothek wählen
(z. B. `Firmenbibliothek.DbLib`), Kategorie wählen, Bauteil suchen und in den Schaltplan ziehen. Symbol, Footprint,
3D-Modell und Parameter kommen aus der Bibliothek.

## 9. Einstellungen und Sicherungen

![Einstellungen › Allgemein](bilder/30-einstellungen.png)

**Sprache:** PartForge startet standardmäßig auf Englisch, auch wenn eine ältere Einstellungsdatei noch keine
Sprache enthält. Unter *Settings › General › Language* können Sie **Deutsch** auswählen und mit **Save**
speichern. Der Wechsel gilt sofort für die gesamte Oberfläche und bleibt nach einem Neustart erhalten.
Auf Deutsch finden Sie dieselbe Auswahl unter *Einstellungen › Allgemein › Sprache*; **English** wechselt
zurück. Die Auswahl gilt für den Windows-Benutzer, unabhängig von der geöffneten Bibliothek. Eigene Namen,
Bauteildaten, technische Kennungen und Dateipfade werden nicht übersetzt. Diese Anleitung zeigt die deutschen
Bezeichnungen.

- **Allgemein:** Autor (steht im Verlauf), Sprache (English, Deutsch), Farbschema (Dunkel, Hell, Wie System), Tabellendichte; **KI-Funktionen**
  (Schlüssel, Modell, Gründlichkeit, Kostenlimit je Import); **Altium Designer** (Pfad zu X2.EXE,
  Bibliotheks-Writer, automatisch aktualisieren).
- **Bibliothek:** Name, DbLib-Datei, Teilenummern-Schema (Hersteller-Teilenummer oder eigene Nummern), Speicherort
  und **Sicherungen**.
- **Kategorien und Felder:** eigene Kategorien und Felder, Text-Vorlagen für Wert, Kommentar und Beschreibung.
- **Namensregeln** und **Hausstil** (Footprints, Lagen, Symbole).

**Sicherungen:** PartForge sichert die Datenbank automatisch vor jeder riskanten Aktion (Serie, Import, Löschen oder
Massenänderung vieler Bauteile, Kategorie oder Feld löschen, Wiederherstellen). Unter
*Einstellungen › Bibliothek › Sicherungen* legen Sie mit **Jetzt sichern** selbst eine an und holen mit
**Wiederherstellen …** einen früheren Stand zurück. Der Stand vor dem Wiederherstellen wird dabei ebenfalls gesichert.

## 10. Befehlspalette und Tastenkürzel

Mit **Strg+K** (oder dem Suchfeld oben) öffnen Sie die Befehlspalette: Seiten, Aktionen und eine Live-Suche über alle
Bauteile.

![Befehlspalette](bilder/31-befehlspalette.png)

| Kürzel | Wirkung |
| --- | --- |
| Strg+K | Befehlspalette |
| Alt+1 … Alt+8 | Übersicht, Bauteile, Serien-Assistent, Datenblatt-Import, Symbole, Footprints, Altium, Einstellungen |
| Alt+9 / Alt+0 | Bibliotheksimport / Stapelbearbeitung |
| Strg+N | Neues Bauteil |
| Strg+B | Seitenleiste ein-/ausklappen |
| Strg+F | Suche in der Bauteiltabelle (im Footprint-Generator: Gehäusefamilie suchen) |
| Strg+Enter | Anlegen bzw. weiter: neues Bauteil, Serien-Assistent, Datenblatt-Import |
| Strg+S / Strg+Umschalt+S | Speichern / Speichern unter (Symbol, Footprint, Einstellungen) |
| Strg+Z / Strg+Y | Rückgängig / Wiederholen (Footprint-Generator, IC-Editor); Strg+Z nimmt auch die letzte Korrektur im Datenblatt-Import zurück |
| Enter | in der Tabelle: Details zum Bauteil öffnen |
| Entf | gewählte Bauteile löschen (mit Bestätigung) |
| Strg+A | alle geladenen Zeilen der Tabelle wählen |
| F6 / Umschalt+F6 | zwischen Suche, Tabelle und Details wechseln |
| Alt+← / Alt+→ | im Serien-Assistenten zurück / vor |
| Esc | Dialog oder Menü schließen |

In der IC-Pinliste: **Strg+D** dupliziert einen Pin, **Strg+Entf** löscht ihn, **Strg+Umschalt+O** setzt den
Überstrich (low-aktiv).

## 11. Häufige Fragen und Fehlerbehebung

**Neue Bauteile fehlen in Altium.** Seite *Altium* → **Aktualisieren**; prüfen, dass die DbLib installiert ist.

**Altium liest keine Bauteile.** Den „SQLite3 ODBC Driver“ (64 Bit) installieren, dann auf der Seite *Altium*
**ODBC testen**.

**Altium reagiert nicht auf PartForge.** In Altium hängt vermutlich ein Skript: in Altium **Strg+F3** drücken.

**„database is locked“.** Die Bibliothek liegt auf einem Netzlaufwerk – den Bibliotheksordner auf ein lokales
Laufwerk legen.

**SchLib/PcbLib werden nicht geschrieben.** *Einstellungen › Allgemein › Altium Designer*: Pfad zum
Bibliotheks-Writer (`altium-designer-mcp.exe`) prüfen. Die Bibliothek darf in Altium keine ungespeicherten
Änderungen haben.

**Datenblatt-Import nicht möglich.** *Einstellungen › Allgemein › KI-Funktionen*: Schlüssel eintragen und
**Verbindung testen**.

**Ordner lässt sich nach dem Deinstallieren nicht verschieben.** Altium hält die Datenbank noch offen – etwa eine
Minute warten, sonst Altium beenden. Vorher in PartForge die Bibliothek schließen.

**Etwas falsch geändert?** Gelöschte Bauteile: *Übersicht › Letzte Änderungen* → **Wiederherstellen**. Eine
Massenänderung: direkt danach **Rückgängig** in der Meldung. Alles andere: *Einstellungen › Bibliothek › Sicherungen*.

Weitere Hinweise zu Installation, Datenablage und Deinstallation stehen im [Handbuch zum Programmpaket](README.md).
