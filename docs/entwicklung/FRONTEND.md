# PartForge – Frontend & Designsystem „Forge"

Verbindliches Design-Briefing für alle Frontend-Arbeiten. Ziel: ein professionelles
Engineering-Werkzeug mit Premium-Anmutung, das sich sofort vertraut anfühlt, aber
eigenständig und beeindruckend aussieht. Sprache der Oberfläche: **Deutsch**.

## 1. Stack (installierte Versionen – APIs gegen `node_modules/*/dist/*.d.ts` prüfen!)

| Paket | Version | Zweck |
| --- | --- | --- |
| react / react-dom | 19.2 | UI |
| vite | 8.3 | Build/Dev-Server (`/api` → Proxy auf 127.0.0.1:8765) |
| typescript | 6.0 | `erasableSyntaxOnly` (keine `enum`s, keine Parameter-Properties), `verbatimModuleSyntax` (`import type`) |
| tailwindcss + @tailwindcss/vite | 4.3 | CSS-first Konfiguration (`@theme`), keine tailwind.config.js |
| motion | 14 | Animationen (`import { motion, AnimatePresence } from 'motion/react'`) |
| radix-ui | 1.7 | Unified-Paket (`import { Dialog, DropdownMenu, Tooltip, ... } from 'radix-ui'`) |
| lucide-react | 1.52 | Icons |
| @tanstack/react-query | 5 | Server-State |
| @tanstack/react-virtual | 3 | lange Listen/Galerien |
| react-router | 8.4 | Routing (Hash- oder Browser-Router; Backend liefert SPA-Fallback) |
| zustand | 5 | UI-State (Theme, Sidebar, Job-Dock) |
| cmdk | 1.1 | Befehlspalette (Strg+K) |
| sonner | 2 | Toasts |
| ag-grid-community / ag-grid-react | 36.2 | Bauteiltabelle (Theming-API, Quartz-Basis) |
| three, @react-three/fiber, @react-three/drei | 0.186 / 9.8 / 10.7 | 3D-Vorschau der Gehäuse |
| recharts | 3.10 | Dashboard-Diagramme |
| react-dropzone | 20 | Datenblatt-Drop |
| @fontsource-variable/inter, …/jetbrains-mono | 5 | Schriften lokal (App läuft offline) |

Diese Versionen sind neuer als das Trainingswissen der Modelle. **Vor Nutzung einer API die Typdefinitionen
im installierten Paket lesen** (z. B. `frontend/node_modules/ag-grid-react/dist/types/...`).

## 2. Markenidee

„PartForge" – die Schmiede für Bauteile. Leitmotiv **Kupfer & Glut**: tiefes Blauschwarz wie eine
Werkstatt bei Nacht, Akzente in glühendem Kupfer-Orange (PCB-Kupfer + Schmiedeglut).
KI-Funktionen erhalten ein eigenes Motiv: **Funken** – ein kühler Cyan→Violett-Verlauf, damit
KI-generierte Inhalte immer erkennbar sind.

Logo: abgerundetes Quadrat mit Kupfer-Verlauf, darin stilisiertes IC-Gehäuse (Pins links/rechts)
mit einem Funken. Als Inline-SVG-Komponente `<ForgeLogo />`.

## 3. Design-Tokens (CSS-Variablen, Theme über `data-theme="dark|light"` auf `<html>`)

### Dark (Standard)
| Token | Wert | Verwendung |
| --- | --- | --- |
| `--pf-bg` | `#090B10` | App-Hintergrund |
| `--pf-bg-elev` | `#0D1016` | Sidebar, Topbar |
| `--pf-surface` | `#11151D` | Karten, Panels |
| `--pf-surface-2` | `#171C26` | Eingabefelder, Hover |
| `--pf-surface-3` | `#1F2532` | aktive Elemente |
| `--pf-line` | `rgba(148,163,184,.12)` | Haarlinien |
| `--pf-line-strong` | `rgba(148,163,184,.22)` | betonte Linien |
| `--pf-fg` | `#E8EBF2` | Text |
| `--pf-fg-muted` | `#9AA3B5` | Sekundärtext |
| `--pf-fg-subtle` | `#6B7385` | Hinweise, Platzhalter |
| `--pf-accent` | `#FF8A3D` | Kupfer-Glut (Primäraktionen, Fokus) |
| `--pf-accent-strong` | `#FF6B1A` | Hover/Pressed |
| `--pf-accent-soft` | `rgba(255,138,61,.14)` | Flächen, Badges |
| `--pf-spark-a` / `--pf-spark-b` | `#38BDF8` / `#A78BFA` | KI-Verlauf |
| `--pf-success` | `#3DD68C` | |
| `--pf-warning` | `#F5B544` | |
| `--pf-danger` | `#F2555A` | |
| `--pf-info` | `#5AA9FF` | |

### Light
`--pf-bg #F5F6FA`, `--pf-bg-elev #FFFFFF`, `--pf-surface #FFFFFF`, `--pf-surface-2 #F0F2F7`,
`--pf-surface-3 #E6E9F0`, `--pf-line rgba(15,23,42,.08)`, `--pf-line-strong rgba(15,23,42,.16)`,
`--pf-fg #0E1320`, `--pf-fg-muted #4A5468`, `--pf-fg-subtle #8A93A6`, `--pf-accent #E8681A`,
`--pf-accent-strong #CF5A10`, `--pf-accent-soft rgba(232,104,26,.12)`, Status-Farben je etwas dunkler.

Verläufe:
- `--pf-gradient-forge: linear-gradient(135deg, #FFC27A 0%, #FF8A3D 45%, #E8467C 100%)`
- `--pf-gradient-spark: linear-gradient(135deg, #38BDF8 0%, #818CF8 50%, #C084FC 100%)`

Tailwind v4: Tokens per `@theme inline { --color-bg: var(--pf-bg); ... }` als Utilities verfügbar machen
(`bg-bg`, `bg-surface`, `text-fg`, `text-fg-muted`, `border-line`, `text-accent`, …).
Dark-Variante: `@custom-variant dark (&:where([data-theme=dark], [data-theme=dark] *));`

### Leiterplatten-/Symbol-Farben (Vorschau-Leinwände)
Footprint (an Altium angelehnt, verfeinert): Top-Kupfer `#E5484D`, Bottom-Kupfer `#4C7DFF`,
Multilayer-Pads (THT) `#C9CED8` mit Bohrung `#05070A`, Bestückungsdruck `#F2D14B`,
Courtyard `#D16BFF` (gestrichelt), Bestückungszeichnung/Assembly `#6FA8FF`, Paste `#8D96A8`
(nur Umriss), 3D-Körper-Umriss `#3DD68C`, Leinwand `#05070A` mit Punktraster.
Symbol: Theme-abhängig (Körperfläche `accent-soft`, Linien `fg`, Pin-Nummern `fg-subtle`,
Pin-Namen `fg-muted`) **plus** Umschalter „Altium-Ansicht" (weißes Blatt, Körper `#FFFFB0`,
Linien `#800000`, Pins `#000080`) – so sehen Symbole aus wie später in Altium.

## 4. Typografie
- UI: **Inter Variable**, Basis 13 px (dichtes Werkzeug), 14 px in Formularen.
- Werte, MPNs, Maße, Codes: **JetBrains Mono Variable**, `font-variant-numeric: tabular-nums`.
- Überschriften: 20 / 24 / 32 px, `letter-spacing: -0.02em`, Gewicht 600.
- Labels: 11–12 px, Großbuchstaben nur für Mikro-Labels (Tracking +0.06em).

## 5. Formensprache
- Radien: 8 px (kleine Controls), 10 px (Buttons/Inputs), 14 px (Karten), 20 px (Dialoge, Hero-Flächen).
- Haarlinien statt schwerer Rahmen; Karten mit Innen-Highlight `inset 0 1px 0 rgba(255,255,255,.04)`.
- Schatten (dark): `0 10px 30px -10px rgba(0,0,0,.55)`; Overlays mit `backdrop-filter: blur(16px)`.
- Fokus: 2 px Ring in `--pf-accent` mit weichem Glow; vollständig tastaturbedienbar.
- Primärbutton: Forge-Verlauf, dezenter Glanz beim Hover. Sekundär: Surface-2 mit Haarlinie. Ghost.
- KI-Elemente: rotierender konischer Spark-Rahmen während der Analyse (`@property --angle`).
- Leere Zustände: Illustration (Inline-SVG im Linienstil), klare nächste Aktion.

## 6. Bewegung
- Seitenwechsel: Fade + 6 px Slide, 180 ms. Panels/Drawer: Spring (stiffness 420, damping 34).
- Listen: Stagger 15–25 ms für die ersten 20 Elemente. Hover: 1 px Lift. Klick: scale .98.
- Dashboard-Zahlen zählen hoch; Skeletons mit Shimmer; Fortschrittsringe für Jobs.
- `prefers-reduced-motion` respektieren (Animationen auf Opacity reduzieren).

## 7. App-Shell
- **Sidebar** links (248 px, einklappbar auf 68 px, Zustand persistent): Logo + Bibliotheks-Umschalter
  (aktuelle Bibliothek, zuletzt verwendete, „Neue Bibliothek…"), Navigation:
  Übersicht · Bauteile · Serien-Assistent · Datenblatt-Import · Bibliotheksimport · Symbole · Footprints ·
  Stapelbearbeitung · Altium · Einstellungen (Alt+1 … Alt+8 wie bisher, Alt+9 Bibliotheksimport, Alt+0
  Stapelbearbeitung).
  Unten Statuszeile: Datenbank ●, Altium ●, KI ● (grün/gelb/rot mit Tooltip).
- **Topbar** je Seite: Titel + Untertitel/Breadcrumb, globale Suche (öffnet Befehlspalette, `Strg+K`),
  seitenbezogene Aktionen, Theme-Umschalter.
- **Befehlspalette** (cmdk): Navigation, Aktionen (Neues Bauteil, Serie erzeugen, Datenblatt importieren,
  DbLib neu erzeugen, Bibliothek prüfen, In Altium installieren), Live-Bauteilsuche.
- **Globale Drop-Zone**: PDF irgendwo ins Fenster ziehen → Vollbild-Overlay mit animiertem Dokument
  („Loslassen, um das Datenblatt zu analysieren") → Import startet, Navigation zur Import-Seite.
- **Job-Dock** unten rechts: laufende Hintergrundjobs mit Fortschrittsring, aufklappbares Log.
- **Willkommen/Onboarding**, wenn keine Bibliothek geöffnet ist: Hero mit Logo, „Neue Bibliothek anlegen"
  (Ordnerwahl, Name, Beispielinhalte ja/nein), „Bibliothek öffnen", zuletzt verwendet.

## 8. Seiten (Kurzspezifikation)
1. **Übersicht**: KPI-Karten (Bauteile, Kategorien, Symbole, Footprints, Probleme), Verteilung je Kategorie
   (Balken/Donut), Bibliotheksgesundheit (Ampel + Top-Probleme mit „Beheben"), letzte Änderungen (Timeline),
   Schnellaktionen, Altium-/KI-Status.
2. **Bauteile**: links Kategoriebaum mit Zählern und Farbpunkten; Mitte AG-Grid (kategoriespezifische Spalten,
   Schnellfilter, Spaltenwahl, Inline-Bearbeitung, Mehrfachauswahl → Massenbearbeitung, Duplizieren, Löschen,
   Export); rechts Detail-Drawer mit Symbol-/Footprint-/3D-Vorschau, Parametern, Datenblatt, Historie.
   „Neues Bauteil" als geführter Dialog mit Smart-Eingabe („10k 1% 0603" → Felder werden befüllt).
3. **Serien-Assistent**: Schritte Kategorie → Hersteller-Serie (Karten mit Beispiel-MPN) → Werte & Varianten
   (E-Reihe, Bereich mit logarithmischem Doppel-Slider, Bauformen als Chips, Toleranz, …, Live-Zähler
   „4 Bauformen × 289 Werte = 1 156 Bauteile") → Vorschau (virtualisierte Tabelle, Status neu/vorhanden/Konflikt,
   benötigte Footprints werden erzeugt) → Erzeugen (Fortschritt, Erfolgsbildschirm mit Link zur Tabelle).
4. **Datenblatt-Import**: große Drop-Zone + Liste bisheriger Importe. Prüfansicht in drei Spalten:
   PDF-Seiten (Miniaturen + große Seite, Sprung zu Fundstellen), extrahierte Daten (gruppiert, Konfidenz,
   editierbar, Varianten/Bestellnummern), Live-Vorschau Symbol / Footprint / 3D. Aktion „Bauteil anlegen".
5. **Symbole**: Galerie (virtualisiert, Karten mit SVG-Vorschau), Filter nach Typ/Bibliothek, Editor:
   Standard-Symbole parametrieren oder IC-Pinliste bearbeiten (Seiten per Drag&Drop) mit Live-Vorschau.
6. **Footprints**: Galerie; **Footprint-Generator**: Gehäusefamilie wählen → Maße (min/nom/max) →
   Dichte L/N/M → Live-Vorschau mit Bemaßung, Lagen-Umschaltern, 3D-Ansicht, IPC-Name.
7. **Altium**: DbLib-Status (aktuell/veraltet) mit „Neu erzeugen", ODBC-Verbindungstest, „In Altium
   installieren/öffnen", Bibliotheksdateien (synchron/ausstehend) mit „Synchronisieren", Backend-Wahl,
   Prüfbericht („Bibliothek prüfen") mit Fix-Aktionen.
8. **Einstellungen**: Bibliothek (Pfade, Datenbank), Kategorien & Felder (Schema-Designer), Namensregeln,
   Hausstil Symbole/Footprints (Lagen-Zuordnung, Lagensatz, Schriften, „Aus Beispielbibliothek …“), KI (Modell,
   Key-Datei, Budget), Altium (X2-Pfad, Backend), Darstellung (Theme, Dichte).
9. **Bibliotheksimport**: Quelle (Ordner/Datei) einlesen (Job), Dateien und Bauteile mit Zustand, Filter und
   Vorschau, Optionen (Zielordner, ersetzen, 3D, angleichen), Import als Job, Ergebnis mit „Bauteile anlegen …“
   (Tabellenimport mit vorbereiteter Tabelle) und „An Hausstil angleichen …“.
10. **Stapelbearbeitung**: Auswahl und Regeln links, Bericht rechts (je Bibliothek Rollen der Mechanik-Lagen mit
    Umstellen, je Bauteil die Änderungen), Prüfen → Anwenden (Bestätigung, Job) → Rückgängig.

## 9. Qualitätskriterien
- Kein Layout-Springen, keine abgeschnittenen Texte; Mindestbreite 1120 px.
- Jede Aktion gibt Feedback (Toast, Inline-Status oder Job-Dock); Fehler auf Deutsch mit Lösungsweg.
- Ladezustände mit Skeletons; leere Zustände mit Illustration + Aktion.
- Tastatur: Strg+K Palette, Strg+N neues Bauteil, Strg+F Tabellenfilter, Entf löschen (mit Bestätigung), Esc schließt.
- Kontrast WCAG AA in beiden Themes.
- Screenshots jeder Seite (dark + light) zur Abnahme: `scripts/screenshot.py` (Playwright mit Edge).
