# PartForge Frontend – Fundament (für Seiten-Agenten)

Ergänzt das verbindliche Design-Briefing `docs/entwicklung/FRONTEND.md`. Hier steht, **was schon da ist, wie man es
benutzt und welche Regeln gelten**. Komponenten-Galerie: **`/ui-kit`** (im Dev-Server auch über Strg+K → „UI-Kit
anzeigen“; im gebauten Programm per URL).

```text
frontend/
  index.html               lang="en" (gespeicherte Sprache vom Backend), Theme-Bootstrap (kein Aufblitzen, liest localStorage → Cookie → <meta>), Favicon
  public/favicon.svg       Bildmarke
  scripts/export_openapi.py  → openapi.json (npm run gen:api) bzw. Prüfung (npm run gen:api:check)
  src/
    main.tsx               Fonts (Inter Variable opsz, JetBrains Mono Variable) + CSS + <App/>
    styles/index.css       Tokens, @theme-Mapping, Basis, Utilities
    lib/                   cn, i18n (en/de), format (aktive Locale), units (4k7, E-Reihen), hotkeys, native (pywebview), download (Dateien speichern),
                           prefs (Cookie), useCountUp, geometry, settingsPlaces (Orte in den Einstellungen, Begriffe)
    api/                   client, queryClient, types (ResponseOf/Filled), system, library, jobs, schema.d.ts (generiert)
    app/                   App, router, navigation (appNavigate), RootLayout, ThemeProvider/theme, stores, commands, page,
                           topbar, nav
    app/shell/             AppShell, Sidebar, Topbar, CommandPalette, JobDock, GlobalDropOverlay, LibraryDialogs,
                           librarySwitch (Rückfrage vor dem Wechsel), ShellCommands, useSystemStatus
    components/ui/         UI-Kit „Forge“ (Export über index.ts)
    components/brand/      ForgeLogo / ForgeMark
    pages/<modul>/         eine Seite je Modul (Default-Export, per Route lazy geladen)
  tests/                   Unit-Tests der Shell-Logik (npm test)
```

## Befehle

| Befehl | Zweck |
| --- | --- |
| `npm run dev` | Vite-Dev-Server :5173, `/api` → Proxy auf 127.0.0.1:8765 (Backend mit `python -m partforge --dev`, Token „dev“) |
| `npm run build` | **prüft zuerst das API-Schema** (`gen:api:check`), dann `tsc -b` + Build nach `../partforge/web` – samt **`third-party-licenses.txt`** (Plugin in `vite.config.ts`: Name, Version, Lizenz und Lizenztext jedes gebündelten Pakets inkl. der OFL der Schriften Inter/JetBrains Mono; im Programmpaket unter `partforge\web`) |
| `npm run build:nocheck` | Build ohne Schema-Prüfung (nur im Notfall, z. B. wenn das Backend gerade nicht importierbar ist) |
| `npm run typecheck` / `npm run lint` | TypeScript (strikt) / oxlint inkl. **jsx-a11y** – beide müssen sauber bleiben |
| `npm test` | Unit-Tests der Shell-Logik ohne Browser (`tests/*.test.mjs`, `node --test`; Module über Vites SSR-Loader): Job-Rückmeldung, Fehlertexte, Downloads, Bibliotheksbezug; Altium-Seite (`tests/altium.unit.test.mjs`: Hinweis nach dem Deinstallieren, Parameterliste, Schlagzeile). Oberflächen-Prüfungen der Shell: `tests/ui/shell_regressions.py` (Playwright gegen einen isolierten Server), der Altium-Seite mit einem Altium im Speicher: `tests/ui/polish_regressions.py` |
| `npm run gen:api` | OpenAPI exportieren + `src/api/schema.d.ts` neu erzeugen – **nach jeder Backend-API-Änderung** |
| `npm run gen:api:check` | Bricht ab, wenn `openapi.json` nicht mehr zum Backend passt („Bitte `npm run gen:api` ausführen“) |

Testen gegen das echte Backend (eigene Einstellungen bleiben unberührt):

```powershell
npm run build
$env:PARTFORGE_HOME='C:/PartForge-Examples/Tools/PartForge/tests/_tmp/fe-home'
& 'C:/PartForge-Examples/Tools/PartForge/.venv/Scripts/python.exe' -m partforge --server-only --port 8799
& 'C:/PartForge-Examples/Tools/PartForge/.venv/Scripts/python.exe' scripts/screenshot.py --url http://127.0.0.1:8799 `
    --out docs/screenshots/<modul> --pages "/bauteile" --themes dark,light
```

> Das Backend öffnet beim Start keine Bibliothek – vor Screenshots per API (`POST /api/workspace/open|create`,
> Token aus `<meta name="partforge-token">` der ausgelieferten Seite) eine Test-Bibliothek unter `tests/_tmp/` öffnen.
> `create` mit `with_examples: true` legt 19 Beispielbauteile (15 Symbole, 13 Footprints) an und startet mit
> `write_libraries: true` den Job „Bibliotheken schreiben“. In Git Bash werden Argumente wie `/bauteile` zu
> Windows-Pfaden umgeschrieben – Screenshot-Skript per PowerShell starten. Die Seiten scrollen in `<main id="main">`,
> nicht im Body: `--full-page` hilft nicht, besser ein hohes Viewport oder `document.getElementById('main').scrollTo(…)`.
> In Playwright-Tests `page.wait_for_timeout()` statt `time.sleep()` verwenden – sonst ist `page.url` veraltet.

## Regeln (verbindlich, aus dem Design-Review)

1. **Eine Primäraktion je Ansicht** (Forge-Verlauf). Alles andere `secondary`/`ghost`. Kupfer ist Signal, keine Deko:
   Icon-Kacheln, Kennzahlen, Karten sind neutral; Kupfer nur für Primäraktion, aktiven Zustand, Fokus, Auswahl.
2. **Funken (Cyan→Violett, `Sparkles`) nur für KI.** KI-Einstiege: `variant="spark"` + Icon `FileScan` (Datenblatt) bzw.
   `Sparkles`. Der Funkenrahmen rotiert nur während `loading` (aria-busy). Info-Blau ist kein KI-Signal.
3. **Eine `<h1>` je Seite**: der Topbar-Titel – außer die Seite rendert selbst eine (`PageHeader` macht das automatisch,
   eigene Heroes rufen `usePageHeading()` aus `@/app/topbar`). Kartentitel sind `<h2>` (`CardHeader`), leere Zustände
   in Karten `<h3>`; ohne umgebende Karte `EmptyState titleAs="h2"`.
4. **Mindestbreite 1120 px ohne abgeschnittene Texte**: Layouts mit Container-Queries (`@container` + `@[46rem]:…`) statt
   fester Spalten; `PageBody` ist bereits ein Container. Kein `truncate` auf Titeln, die wichtig sind (`line-clamp-2`).
5. **Schrift ≥ 11 px** (`text-2xs`), nur Token-Größen: `text-2xs` 11 · `text-xs` 12 · `text-ui` 13 · `text-sm` 14 ·
   `text-md` 15 · `text-h3` 20 · `text-h2` 24 · `text-metric` 28 · `text-h1` 32 · `text-display` 46. Keine `text-[…px]`.
6. **Radien nur aus Tokens**: `rounded-control` 8 · `rounded-button` 10 · `rounded-card` 14 · `rounded-panel` 20
   (Mikro-Elemente `rounded-sm`/`rounded-md`). Keine Rahmen-in-Rahmen: innerhalb von Karten Haarlinien (`divide-y
   divide-line`) und randlose Hover-Zeilen statt umrandeter Kacheln.
7. **Fokus immer sichtbar**: `focus-ring` (Controls) bzw. `focus-ring-inset` (Zeilen, die bis an den Kartenrand gehen),
   `focus-ring-panel` (fokussierbare Inhaltsbereiche – Ring unter dem Inhalt). Nie nur über eine Hintergrundfarbe.
8. **Englisch als Standard, Deutsch wählbar, ohne Jargon**: Texte über `useI18n()` aus `@/lib/i18n`, Zahlen über die aktive Locale (`formatNumber`). In Deutsch „und“ statt „&“, „Claude-API“, kurze
   Komposita mit geschütztem Bindestrich (`U+2011`, z. B. „3D‑Modelle“), „Altium Designer“ nicht umbrechen.
   **Feste Begriffe:** IPC-Dichte immer „Klein (L) · Nominal (N) · Groß (M)“ in dieser Reihenfolge (`densityLabel()`,
   `DENSITY_ORDER` aus `@/pages/footprints/lib/calc` – nie „Most/Least“, „Kompakt/Robust“); der Schreiber der
   SchLib/PcbLib heißt in allen Texten „Bibliotheks-Writer“ (den Dateinamen `altium-designer-mcp.exe` nur in Hilfen und
   Fehlermeldungen zum Pfad); Wert/Kommentar/Beschreibung aus den Vorlagen sind „Texte für Altium“ (Dezimalpunkt,
   „4.7kΩ“) und als solche beschriftet; Bibliotheksaktionen „Neue Bibliothek anlegen …“ / „Bibliothek öffnen …“.
9. **Endlos-Animationen sparsam** (WebView2-GPU im Leerlauf): nur während einer Aktion oder kurz nach dem Laden; keine
   `backdrop-blur` auf vielen/bewegten Elementen. `prefers-reduced-motion` wird global respektiert.

## Mehrsprachigkeit

Englisch ist die Vorgabe, Deutsch lässt sich unter Einstellungen → Allgemein → Sprache auswählen und speichern.
`AppSettings.language` (`en`/`de`) ist die dauerhafte Quelle. Das Backend setzt die Sprache bereits im HTML;
`LanguageProvider` übernimmt sie nach einem erfolgreichen Speichern ohne Neustart. Ein ungespeicherter Entwurf
ändert die Sprache nicht. Bestehende Einstellungen ohne Sprachfeld verwenden Englisch.

- `const { t, language, locale } = useI18n()` macht Komponenten reaktiv; `t` gehört in die Abhängigkeiten von
  Memos/Effekten, die übersetzte Texte erzeugen. Reine Helfer verwenden `t()` und `getLocale()` zur Laufzeit.
- Deutsche Quelltexte bilden die Schlüssel der englischen Kataloge unter `src/i18n/catalogs/`. Platzhalter werden
  als Werte übergeben, z. B. `t('Datei {name} gespeichert', { name })`. Benutzerdaten niemals als Übersetzungsschlüssel
  behandeln. Statische Metadaten bleiben Quelltexte bis zur Anzeige oder liefern ihre Texte über Getter.
- Routen, Befehlsgruppen, Kategorien-/Feldkennungen, Filterwerte und CAD-/Datenbankwerte bleiben stabil.
  `metadataLabel` liefert kontextbezogene eingebaute Feld-/Optionsbezeichnungen; freie Benutzereingaben bleiben unverändert.
- `localizeMessage()` übersetzt bereits gerenderte Backend-Diagnosen ausschließlich an der Anzeigestelle.
  Rohantworten und Jobprotokolle bleiben für Parser und Speicherung unverändert. Technische Dateiinhalte werden nicht übersetzt.
- Mengen, Datumsangaben und Einheiten verwenden Helfer aus `lib/format`, `lib/units` und `lib/geometry`.
  `pluralLabel` berücksichtigt auch unterschiedliche englische Pluralformen bei gleichlautenden deutschen Nomen.
- Weitere Sprachen benötigen einen Sprachcode in Backend/Frontend, einen Katalog und einen Eintrag in der Sprachauswahl.
  Die Anzeige darf für Sprachwechsel nicht neu geladen werden; Formular- und Bibliotheksdaten bleiben erhalten.

Regressionen: `frontend/tests/*i18n.unit.test.mjs` sowie `tests/ui/i18n_regressions.py` gegen einen isolierten Server.

## Seiten bauen

Jede Seite ist `src/pages/<modul>/<Name>Page.tsx` mit **Default-Export** und wird in `src/app/router.tsx` lazy geladen.
Die Platzhalter (`ModulePlaceholder`) einfach ersetzen. Routen: `/` Übersicht, `/bauteile`, `/bauteile/:table`,
`/serien`, `/import`, `/symbole`, `/footprints`, `/altium`, `/einstellungen[/:section]`, `/willkommen`, `/ui-kit`.
Alle Routen außer `/willkommen`, `/einstellungen` und `/ui-kit` liegen hinter dem `WorkspaceGuard` – dort ist garantiert
eine Bibliothek geöffnet (`useWorkspace().data` ist gesetzt). Ohne Bibliothek → Umleitung auf `/willkommen`.
**Fehler beim Rendern einer Seite** erscheinen im Inhaltsbereich (Sidebar/Topbar bleiben bedienbar).

```tsx
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { Button } from '@/components/ui'

export default function BauteilePage() {
  return (
    <PageBody width="full" flush>                               {/* default | narrow | wide | full; flush = ohne Padding */}
      <PageTitle title="Widerstände" subtitle="1.156 Bauteile" />  {/* Topbar: „Bauteile › Widerstände“ + Untertitel */}
      <PageActions>                                             {/* Portal rechts in die Topbar, Buttons automatisch „sm“ */}
        <Button variant="spark" leftIcon={<FileScan />}>Aus Datenblatt</Button>
        <Button variant="primary" leftIcon={<Plus />}>Neues Bauteil</Button>
      </PageActions>
      …
    </PageBody>
  )
}
```

- Die **Topbar sitzt im Scrollbereich** (`<main>`, `sticky top-0`) und übernimmt Breite und Polsterung von `<PageBody>`:
  Titel und Inhalt sind bündig (`full`+`flush` → `px-6`). Beim Scrollen bekommt sie Haarlinie und Unschärfe.
  Ihre Höhe steht in **`--pf-topbar-height`** (3,5 rem) – für eigene Sticky-Offsets (`top-(--pf-topbar-height)`) und
  Vollhöhen-Layouts (`h-[calc(100dvh-var(--pf-topbar-height))]`).
- **Job-Dock freihalten:** `--pf-dock-reserve` = Platz, den die Pille unten rechts gerade belegt (Höhe + Randabstand,
  `0px`, wenn sie ausgeblendet ist), `--pf-dock-width` = ihre Breite + Abstand. Beispiele: Fußleiste einer Tabelle
  `pb-(--pf-dock-reserve)`, schwebende Leiste `bottom-[calc(var(--pf-dock-reserve)+12px)]` bzw. rechts
  `mr-(--pf-dock-width)`. In JS: `useJobDock((s) => s.reserve)` (`{ block, inline }` in px). Das aufgeklappte Panel
  zählt nicht: Es öffnet sich **nur auf Wunsch** (Klick auf die Pille, „Details“ eines Job-Toasts, Befehl
  „Hintergrundjobs anzeigen“) – nie von selbst beim Start eines Jobs – und schließt mit „Minimieren“ oder Esc.
- `PageTitle` nur mit Strings (`title`, `subtitle`, optional `crumbs: { label, to? }[]`). Ohne `PageTitle` zeigt die
  Topbar den Namen des Navigationspunkts. Der Titel wird zugleich Dokumenttitel und für Screenreader angesagt.
- `PageHeader` (UI-Kit) ist der **große Kopf im Inhalt** (neutrale Icon-Kachel, Mikro-Label, Titel 24 px = `<h1>`,
  Beschreibung, Aktionen). **Tabellen-Seiten ohne `PageHeader`** – nur Topbar + `PageActions`.
- Seitenwechsel animiert die Shell (Fade + 6 px, Schlüssel = erster Pfadabschnitt → `/bauteile/:table` remountet nicht).
- Abfrage-Parameter der eingebauten Befehle auswerten: `/bauteile?neu=1` (Dialog „Neues Bauteil“),
  `/bauteile/:table?pn=<Teilenummer>` (Bauteil auswählen – Ziel der Schnellsuche und der Übersicht; ein **gelöschtes**
  Bauteil zeigt „Bauteil gelöscht“ mit Zeitpunkt, Bearbeiter, Werten beim Löschen und „Wiederherstellen“ – Ziel für
  Einträge „… gelöscht“ in Übersicht › Letzte Änderungen), `/einstellungen#profil|ki|altium` (Karte in „Allgemein“;
  `#altium` fokussiert das Feld „Bibliotheks-Writer“, solange keiner gefunden ist – Ziel von „Bibliotheks-Writer
  einrichten“), `/einstellungen/bibliothek`, `/einstellungen/hausstil?ansicht=lagen|symbole` (Reiter des Hausstils) –
  in Texten über `SETTINGS_PLACE` aus `@/lib/settingsPlaces` (siehe „Weitere Helfer“),
  `/serien?vorlage=<id>` bzw. `?kategorie=<Tabelle>` (Serien-Assistent vorbelegen),
  **`/serien?schritt=kategorie|serie|werte|vorschau|erzeugen`** (Schritt des Assistenten: Zurück/Vor des Fensters und
  Alt+←/→ wechseln ihn; ein noch nicht erreichbarer Schritt wird durch den höchsten erreichbaren ersetzt),
  `/import?suche=1` bzw. `?suche=<Teilenummer>` (Datenblattsuche fokussieren bzw. vorbelegen – Ziel des Befehls
  „Datenblatt suchen …“), `/import?url=1` (Feld „Aus URL laden“) und die **Altium-Seite**:

  | Parameter | Werte | Wirkung |
  | --- | --- | --- |
  | `bereich` | `pruefbericht` (Standard) · `dateien` · `altium` (Prüfung in Altium) · `extern` (externe Bibliotheken) | Reiter |
  | `pruefung` | Prüfungs-ID des Prüfberichts (`CHECK_META` in `@/api/libraries`). Datenebene: `required`, `value`, `format`, `enum`, `duplicate_pn`, `duplicate_mpn`, `symbol_missing`, `footprint_missing`, `library_file_missing`, `datasheet_missing`; Registry (beide Ebenen): `registry_missing`, `registry_error`; Dateiebene: `component_missing` (fehlt in der Bibliotheksdatei), `component_not_in_file`, `library_unassigned`, `path_empty`, `footprint_height_missing` (Höhe 0 in der PcbLib), `pin_pad_mismatch`, `library_changed_outside`; DbLib: `dblib.*` (z. B. `dblib.outdated`, `dblib.duplicates`) | Gruppe im Prüfbericht aufklappen (mit `bereich=pruefbericht`) |
  | `schwere` | `fehler` · `warnungen` · `hinweise` | Filter des Prüfberichts |

  Beispiel: `/altium?bereich=pruefbericht&pruefung=symbol_missing&schwere=fehler` (Übersicht › „Beheben“). Solange die
  Altium-Seite offen ist, führen die gleichnamigen Palettenbefehle die Aktionen direkt aus.

  **Aktionen der Altium-Seite** (`dblib` DbLib neu erzeugen · `sync` Bibliotheksdateien synchronisieren → Reiter
  „dateien“ · `pruefen` Bibliothek prüfen → „pruefbericht“ · `installieren` · `aktualisieren` In Altium aktualisieren ·
  `odbc` ODBC-Test, Dialog · `vorschau` DbLib-Vorschau) lösen andere Stellen **nur als Router-State** aus, nie über die
  Adresse: `navigate(ALTIUM_PATH, { state: altiumActionState('sync') })` bzw. `<Link to={ALTIUM_PATH}
  state={altiumActionState('pruefen')}>`, außerhalb von Komponenten `appNavigate(to, { state })` (alles aus
  `@/app/navigation`). Die Seite führt die Aktion einmal aus, sobald der Altium-Status geladen ist, und löscht den State
  (Neuladen und Zurück lösen sie nicht erneut aus). Den State kann nur PartForge selbst setzen – ein Link oder Rahmen
  einer fremden Website, ein Lesezeichen oder ein Link in einer Mail startet so keine Aktion; ein `?aktion=` in der
  Adresse (frühere Form) wird ignoriert und entfernt. **Neue Adressparameter lösen nie schreibende Aktionen aus** – sie
  dürfen nur anzeigen, vorbelegen oder fokussieren.

## Designsystem in Tailwind

Farben (Theme-abhängig über CSS-Variablen): `bg-bg`, `bg-bg-elev`, `bg-surface`, `bg-surface-2`, `bg-surface-3`,
`border-line`, `border-line-strong`, `border-line-control` (Rahmen von Controls, ≥ 3:1), `text-fg`, `text-fg-muted`,
`text-fg-subtle`, `text-accent`, `bg-accent-soft`, `text-on-accent`, `bg-control` (Füllung von Eingabefeldern),
`text-success|warning|danger|info` (Flächen/Punkte), `bg-canvas`.

**Text auf getönten Flächen** (Badges, Hinweise) immer mit den Text-Tokens – sie erreichen ≥ 4,5:1 auch auf ihrer
eigenen 10-%-Tönung: `text-accent-text`, `text-spark-text`, `text-success-text`, `text-warning-text`, `text-danger-text`,
`text-info-text`. Alle Text-Tokens sind auf bg/surface/surface-2/surface-3 in beiden Themes AA-geprüft.

| Thema | Klassen / Tokens |
| --- | --- |
| Radien | `rounded-control` 8 · `rounded-button` 10 · `rounded-card` 14 · `rounded-panel` 20 |
| Schatten | `shadow-card` · `shadow-raised` · `shadow-pop` · `shadow-glow` · `shadow-glow-spark`; Primär-/KI-Buttons: `--pf-shadow-primary`, `--pf-shadow-spark` |
| Glut (theme-abhängig, hell schwächer) | `--pf-ember-faint` · `--pf-ember` · `--pf-ember-strong` · `--pf-glow-indicator` · `--pf-glow-control` – **keine** `rgba(255,138,61,…)` mehr hart codieren |
| Ebenen | `z-sticky` 10 · `z-sidebar` 20 · `z-dock` 40 · `z-modal` 50 · `z-popover` 60 · `z-palette` 70 · `z-tooltip` 80 · `z-drop` 90 · `z-skip` 100 |
| Leiterplatte (§3) | `pcb-top` · `pcb-bottom` · `pcb-multi` · `pcb-drill` · `pcb-silk` · `pcb-courtyard` (gestrichelt) · `pcb-assembly` · `pcb-paste` · `pcb-body` · `pcb-grid`, Leinwand `canvas` – als `fill-pcb-top`, `stroke-pcb-silk`, `var(--pf-pcb-top)` |
| Symbol (§3) | Theme-Ansicht `sym-body` · `sym-line` · `sym-pin-number` · `sym-pin-name`; Altium-Ansicht `altium-sheet` · `altium-body` · `altium-line` · `altium-pin` |
| Diagramme | `chart-1` … `chart-6`, `chart-grid` (Kategorie-Farben aus der Datenbank haben Vorrang) |
| Verläufe | `--pf-gradient-forge` / `--pf-gradient-spark` aus den Stopps `--pf-forge-1…3` / `--pf-spark-1…3`; SVG-Verläufe nehmen dieselben Stopps (`FORGE_STOPS`/`SPARK_STOPS` aus `@/components/ui`, als `style={{ stopColor }}`) – keine Hex-Stopps |
| Utilities | `glass`, `text-gradient-forge`, `text-gradient-spark`, `bg-gradient-forge`, `bg-gradient-spark`, `spark-border` (rotierend, nur während Analyse), `spark-border-static`, `shimmer`, `dot-grid`, `mono`, `tabular`, `micro-label`, `focus-ring`, `focus-ring-inset`, `focus-ring-panel` (Inhaltsbereiche: Ring innen, aber **unter** dem Inhalt – verdeckt keine Kanten am Rand), `sheen`, `pop-anim`, `mask-radial`, `scrollbar-none`, `progress-hatched` |
| Varianten | `dark:` / `light:` (über `data-theme`), Container-Queries `@container` + `@[40rem]:…` (Tailwind 4 eingebaut) |
| Icons | Lucide mit **1,75 px Strich** global (`LucideProvider` in `App.tsx`) – kein `strokeWidth` je Zustand |

Abweichungen vom Brief (WCAG AA): `--pf-fg-subtle` dunkel `#858DA1`, hell `#5F6779`; hell `--pf-accent-text #9C440A`,
`--pf-spark-text #6D28D9`, Status-Text `#0E7040 / #8A5600 / #B92D33 / #2361BD`, Status-Grafik Warnung hell `#C2710C`
(≥ 3:1 auch auf surface-3); Verlaufstext im hellen Theme dunkler (`#C2410C → #B8325C`); Control-Rahmen dunkel
`#5B6475`, hell `#868EA1`; Eingabefelder hell mit weißer Füllung. Text auf dem Funken-Verlauf: `text-on-spark`.

`cn()` aus `@/lib/cn` (clsx + tailwind-merge, kennt die eigenen Radien/Schatten/Schriftgrößen/Ebenen).

## UI-Kit `@/components/ui`

| Baustein | Hinweise |
| --- | --- |
| `Button` | `variant`: primary · secondary · outline · ghost · danger · spark (KI) · link; `size`: xs/sm/md/lg (Standard über `ButtonDefaultsContext`, in `PageActions` „sm“); `loading` (aria-busy, Funkenrahmen rotiert), `leftIcon`, `rightIcon`, `iconOnly`, `asChild` (`disabled` → aria-disabled + Klick gesperrt) |
| `IconButton` | `label` (aria + Tooltip), `icon`, `hotkey` (Tooltip + `aria-keyshortcuts`), `tooltipSide` |
| `Input` / `Textarea` | `prefix`, `suffix`, `mono`, `invalid`, `size`; Textarea `autoResize` |
| `NumberInput` | behält den getippten Text, liest beim Verlassen/Enter („2,5“, „2.5“, „1.000,5“), `min`/`max`/`step` (↑/↓, ⇧ ×10), `unit`, `decimals`, `allowEmpty`, `engineering` („4k7“, „100n“) |
| `PathInput` | Pfadfeld: zeigt ohne Fokus das **Ende** des Pfads; `browse="folder" \| "file"` zeigt „Durchsuchen …“, sobald pywebview einen Dialog anbietet |
| `PathText` | Pfad als Text, Umbruch nur an `\` / `/` |
| `Field` | `label`, `help`, `error`, `hint`, `required` (→ `aria-required` am Control), `layout="row"` (Einstellungszeile – zweispaltig erst ab 40 rem, darunter gestapelt); verdrahtet id/aria automatisch. Eigene Controls lesen die Verdrahtung mit `useFieldContext()` (`{ id, labelId, describedBy, invalid, disabled, required }` – `labelId` für Controls ohne `<label for>`, z. B. Radiogruppen: `aria-labelledby`); `FieldContext` ist exportiert – `<FieldContext.Provider value={null}>` schaltet sie für verschachtelte Controls ab, die nicht das beschriftete Element sind |
| `Select` | Radix; `options` oder `groups`, Option mit `description`, `icon`, `badge`; `prefix` |
| `Combobox` | durchsuchbar (cmdk), `allowCustom`, `clearable` (✕ ist ein eigener Button neben dem Auslöser), `mono` |
| `Checkbox`, `Switch` | optional `label` + `description`; Switch `tone="spark"` nur für KI-Optionen |
| `ChipGroup` | Mehrfachauswahl als Chips (z. B. Bauformen), Pfeiltasten, `mono`, Option mit `meta` |
| `Slider` | `value: number[]` (1 Wert = einfach, 2 = Bereich), `scale="log"`, `snap` (z. B. `(v) => nearestInSeries('E24', v)`) – **Pfeiltasten springen von Stufe zu Stufe**, Bild↑/↓ = 1/10 des Bereichs; Screenreader bekommen echte Werte (`aria-valuenow/min/max` als Dezimalzahl ohne Exponent – 1 pF = „0.000000000001“, `plainNumber` aus `@/lib/format` – und `aria-valuetext` aus `formatValue`) |
| `SegmentedControl` | Radio-Semantik, gleitende Markierung; `options` mit `label`/`icon`/`title`. `title` = Tooltip; bei reinen Icon-Segmenten zugleich der Name, sonst bleibt das sichtbare `label` der Name. Gruppenname: `aria-label` **oder** `aria-labelledby`; in einem `Field` automatisch dessen Label (+ Hilfe als Beschreibung) |
| `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` | `variant="underline"` (Standard) oder `"pill"`; Trigger mit `count`. `TabsContent` ist ein Tab-Stopp mit **sichtbarem Fokusring nach innen, der unter dem Inhalt liegt** (`focus-ring-panel` – verdeckt keine Kanten ungepolsterter Inhalte; enthält der Inhalt selbst Bedienelemente, z. B. eine Leinwand: `tabIndex={-1}`). Reiter ohne `TabsContent` (reine Umschalter) bekommen kein `aria-controls` ins Leere |
| `Badge` | neutral · outline · accent · success · warning · danger · info · spark; `dot`, `pulse`, `size` |
| `Callout` | Hinweisbox: `tone` neutral · info · success · warning · danger · spark, `title`, `actions`, `live`/`urgent` |
| `Tooltip` | `content`, `hotkey`, `side`; `TooltipProvider` ist global gesetzt |
| `Popover*`, `DropdownMenu*`, `ContextMenu*` | gestylte Radix-Wrapper; Menüeinträge mit `icon` (auch eigenes Element, z. B. Farbpunkt), `hotkey`, `destructive`, `description`, `DropdownMenuItem` mit `trailing` (rechts, z. B. Anzahl – `children` nur Text; zählt der Zusatz für Screenreader mit, den Namen per `aria-label` ausschreiben: „Widerstände, 17 Bauteile“) |
| `Dialog`, `DialogContent` (`size` sm/md/lg/xl/full, `centered`), `DialogHeader` (`icon`, `tone` neutral/spark/danger/accent/success), `DialogBody`, `DialogFooter` | Höhe auf das Fenster begrenzt – `DialogBody` scrollt. Formulare im Dialog: `<form className="flex min-h-0 flex-1 flex-col">`. Fokus kehrt nach dem Schließen zurück (auch ohne Auslöser) |
| `Drawer`, `DrawerContent` (`size` sm/md/lg/xl), `DrawerHeader`, `DrawerBody`, `DrawerFooter` | Panel von rechts; **`modal={false}` für das Detailpanel neben der Tabelle**: schließt nicht bei Klick/Fokus daneben, Esc nur mit Fokus im Panel, globale Kürzel bleiben aktiv |
| `confirm({ title, description, confirmLabel, destructive, onConfirm })` | `Promise<boolean>` (Radix AlertDialog). Destruktiv: Fokus startet auf **„Abbrechen“** (Entf + Enter löscht nichts versehentlich) |
| `Card` (`variant` default/interactive/glass/spark/highlight/ghost, `padding`), `CardHeader` (`icon`, `title` = `<h2>`, `titleAs`, `description`, `actions`, `eyebrow`), `CardContent`, `CardFooter` | |
| `PageHeader` | großer Seitenkopf (siehe oben), meldet seine `<h1>` an |
| `StatCard` | Kennzahl in JetBrains Mono, zählt hoch; `value` `null` = „–“ (unbekannt), `undefined` = lädt. `tone` **nur für Status** (warning/danger/success); Verlauf (`sparkline`) erscheint nur bei echter Historie |
| `EmptyState` | `illustration`: no-library · no-parts · drop-pdf · search-empty · all-good · forge · offline (oder `icon`), `actions` (secondary – die Primäraktion steht meist schon in der Topbar), `size`, `titleAs` |
| `Skeleton`, `SkeletonText`, `Spinner`, `ProgressBar`, `ProgressRing` | Spinner ohne `label` ist dekorativ; mit `label` → `role="status"`. ProgressBar `label` (sichtbar oder `hideLabel`), `live` (Glanzstreifen nur bei laufenden Vorgängen), ProgressRing `label`/`valueText`; unbestimmt bei „Bewegung reduzieren“ = Schraffur bzw. gestrichelter Ring. Verläufe (`tone` accent/spark) aus den Tokens `--pf-forge-*`/`--pf-spark-*` |
| `Kbd` | `hotkey="mod+k"` → „Strg K“; standardmäßig dekorativ (`aria-hidden`) – Kürzel gehören in `aria-keyshortcuts` des Controls; `decorative={false}` liest „Strg+K“ vor |
| `Stepper` | `steps`, `current`, `onStepClick` (zurückspringen), `compact` (ohne Beschreibungen), animierte Verbindung. Jeder Schritt ist so breit wie sein Inhalt; freier Platz – und Enge – geht zuerst an die Linien (mindestens 16 px), erst dann wird eine Beschriftung gekürzt |
| `KeyValueList` | `items` mit `mono`, `copy`, `hint` |
| `Toolbar`, `ToolbarButton` (asChild), `ToolbarSeparator`, `ToolbarGroup`, `ToolbarSpacer` | Pfeiltasten-Navigation |
| `Separator` (`fade`), `ScrollArea`, `Sparkline`, `CountUp`, `useCountUp`, `Illustration`, `useReturnFocus` | `ScrollArea`: `focusable` (`'auto'` Standard = Tab-Stopp nur, wenn der Bereich scrollt und nichts Fokussierbares enthält – Pfeiltasten scrollen; `true`/`false` erzwingen), `aria-label` für den Bereich |

Toasts: `import { toast } from 'sonner'` → `toast.success('Serie angelegt', { description })`, `toast.error`,
`toast.promise`, `toast(…, { action: { label, onClick } })`. Fehlertexte in der gewählten Sprache mit Lösungsweg. Wiederholbare
Meldungen mit fester `id`, damit sie sich nicht stapeln. Toasts weichen dem Job-Dock automatisch aus.

Logo: `ForgeLogo` (`variant="full|mark"`, `glow`, `animated`) und `ForgeMark` (`title=""` = dekorativ).

## Geteilte Komponenten (Vorschau, Tabellen, Daten)

Live-Demos mit echten Backend-Daten: **`/ui-kit` → „Vorschau und Daten“** (Adresse `/ui-kit#vorschau`;
`/ui-kit#vorschau-3d` öffnet zusätzlich die 3D-Vollansicht). Drei Module, jeweils mit `index.ts`:

| Modul | Inhalt | Bundle |
| --- | --- | --- |
| `@/lib/geometry` | Geometrie-Typen (aus `schema.d.ts`) und Helfer | klein |
| `@/components/preview` | `PreviewPanel`, `SymbolCanvas`, `FootprintCanvas`, `Package3D`, Vorschau-Hooks | three.js nur lazy (`vendor-3d`) |
| `@/components/grid` | `DataGrid`, Theme „Forge“, Zellen-Renderer, Spaltentypen | lädt AG Grid (`vendor-grid`) – nur in Tabellen-Seiten importieren |
| `@/components/data` | `CategoryTree`, `FileDropZone`, `SplitPane`, `VirtualGallery`, `GalleryCard`, `LazyThumbnail`, `TemplateTokenInput` | klein |

### Geometrie `@/lib/geometry`

Typen kommen **aus dem OpenAPI-Schema** (keine Doppelungen): `SymbolSpec`, `SymPin`, `SymGraphic` (Union aus
`SymRect | SymLine | SymPolygon | SymArc | SymEllipse | SymText`), `TextPos`, `ElectricalType`, `PinOrientation`,
`PinDecoration`, `FootprintSpec`, `Pad`, `PadShape`, `Track`, `Arc`, `Region`, `FpText`, `Body3D`, `FpLayer`,
`SymbolRequest`, `FootprintRequest`, `SymbolPreview`, `FootprintPreview`, `CheckIssue`. Einzige Abweichung:
`FootprintSpec.step` ist gelockert (`rotation/offset: number[]`), damit auch `Filled<…>`-Antworten passen.
Konventionen: Symbole in **mil** (Y oben, `SymPin.x/y` = Körperende, `orientation` zeigt nach außen), Footprints in
**mm** (Y oben, Ursprung = Gehäusemitte, Drehung gegen den Uhrzeigersinn).

```ts
import { milToMm, formatLength, symbolBBox, footprintBBox, parseOverbar, overbarSegments, displayText, spokenPinName,
  electricalLabel, pinTip, partLetter, LAYERS, layerColor, layerFill, padLayer, padOutline, parseFootprintCalc } from '@/lib/geometry'

milToMm(100)                         // 2.54          (mmToMil, MIL_PER_MM)
formatLength(1.27)                   // „1,27 mm“     (formatMm(v, stellen) ohne Einheit, echtes Minus)
displayText('R\\E\\S\\E\\T\\')       // „RESET“       (parseOverbar → [{ch, barred}], overbarSegments → Abschnitte)
spokenPinName('C\\S\\')              // „CS (invertiert)“ – für Screenreader
electricalLabel('io')                // „Ein-/Ausgang“
symbolBBox(spec, part)               // { x1, y1, x2, y2 } in mil (Pins inkl. Spitze, Grafiken; Teil 0 zählt immer)
footprintBBox(spec, { bodies: true }) // mm inkl. Strichbreiten; Optionen layers, bodies, texts
LAYERS.courtyard                     // { label: 'Courtyard', altium: 'Mechanical 15', cssVar, color: { dark, light }, order, visible, dashed }
layerColor('top_silk', 'light')      // '#F2D14B' (Leiterplatte ist in beiden Themes dunkel) · layerFill() = var(--pf-pcb-…, Hex)
parseFootprintCalc(preview.calc)     // { lands: [{ axis, z, g, x, pad_center … }], tht, courtyard, bga, height, ipcName, … }
```

Weitere: `boxAdd/boxExpand/boxWidth/boxHeight/boxCenter/isEmptyBox`, `symbolPins(spec, part)`,
`symbolLabelPositions(spec, part)` (Bezeichner/Kommentar wie im Backend: `designator_pos` → `generator.text_positions` →
Standard), `designatorPlaceholder` („U?A“), `footprintLayers(spec)` (vorhandene Lagen), `padCornerRadius`, `padExtent`,
`pointInPad`, `bodiesHeight`, `naturalCompare` (1, 2, 10, A1 …), `PAD_SHAPE_LABEL`, `PAD_SIDE_LABEL`, `ELECTRICAL_LABEL`.

### Vorschau `@/components/preview`

**`PreviewPanel`** – Reiter Symbol | Footprint | 3D mit Werkzeugleiste (Altium-Ansicht, Lagen-Menü, Bemaßung,
automatische Drehung, Zoom −/%/+, Einpassen, Vollbild). Im Vollbild zusätzlich „Nebeneinander“: alle drei Ansichten mit
**Kreuz-Hervorhebung** (Pin im Symbol überfahren → Pad im Footprint und umgekehrt). Vorlieben (Altium-Ansicht, Lagen,
Bemaßung, Pad-Nummern, Drehung) gelten für alle Panels und werden gespeichert (`usePreviewPrefs`).

```tsx
import { PreviewPanel, useFootprintPreview, useSymbolPreview } from '@/components/preview'

const fp = useFootprintPreview({ family: 'gullwing', params, density: 'N', with_3d: true })   // POST /api/footprints/preview
const sym = useSymbolPreview({ kind: 'opamp_dual' })                                        // POST /api/symbols/preview
<PreviewPanel
  symbol={sym.data?.spec} footprint={fp.data?.spec} calc={fp.data?.calc}
  loading={{ symbol: sym.isFetching, footprint: fp.isFetching }}     // vorhandene Inhalte bleiben sichtbar
  error={{ footprint: fp.error ? errorMessage(fp.error) : null }}
  highlight={['1']} designator="U3" comment="TLV9062"
  actions={<IconButton size="sm" label="STEP herunterladen" icon={<Download />} onClick={…} />}
  className="h-[460px]" />
```

| Prop | Bedeutung |
| --- | --- |
| `symbol`, `footprint`, `calc` | Specs und Rechenprotokoll (`FootprintPreview.calc` → Bemaßung Zmax/Gmin/Xmax/Raster) |
| `tab` / `defaultTab` / `onTabChange` | `'symbol' \| 'footprint' \| '3d'` |
| `highlight` | Pin-/Padnummern hervorheben (beide Ansichten) |
| `loading`, `error` | je Ansicht (`{ symbol, footprint, '3d' }`) oder für alle; Fehler erscheinen im Panel |
| `emptyText` | Text je Ansicht ohne Inhalt |
| `actions` | eigene Knöpfe rechts in der Werkzeugleiste |
| `designator`, `comment` | echte Texte statt „U?“/„*“ |
| `hideEmptyTabs`, `allowFullscreen`, `fullscreen`/`defaultFullscreen`/`onFullscreenChange`, `layout` (`tabs \| split`), `allowLayoutSwitch`, `title` | |

Die Werkzeugleiste passt sich der Panelbreite an (Container-Queries); ab 30 rem Zoom-Knöpfe, ab 34 rem Beschriftungen.

**`SymbolCanvas`** – SVG in mil: Pins mit Anschlussspitze, Namen (Überstrich `R\E\S\E\T\`), Nummern, alle
Grafikarten, Pin-Dekorationen (Punkt, Takt …), Bezeichner/Kommentar an `designator_pos`/`comment_pos`, 100-mil-Punktraster,
mehrteilige Symbole (A/B/C …; Teil-0-Pins in jedem Teil), Pin-Tooltip (Nummer, Name, elektrischer Typ, Teil, Gruppe).
`theme="auto"` folgt dem App-Theme (Körper `--pf-sym-body`, auch die größte ungefüllte Form wie das OPV-Dreieck),
`theme="altium"` zeigt weißes Blatt, Farben aus dem Spec (Hausstil) bzw. `#FFFFB0`/`#800000`, Pins `#000080`.

```tsx
<SymbolCanvas spec={spec} theme="altium" part={part} onPartChange={setPart} highlight={['3']}
  onPinHover={(pin) => setHover(pin?.designator ?? null)} onPinClick={(pin) => …} className="h-72" />
```

Props: `spec`, `theme`, `part`/`defaultPart`/`onPartChange`, `showPartTabs`, `highlight`, `hoverDesignator` (von außen),
`onPinHover`, `onPinClick`, `showGrid`, `showHiddenPins`, `showOrigin`, `showLabels`, `designator`, `comment`,
`interactive` (Zoom/Verschieben), `controls` (schwebende Zoom-Knöpfe), `showInfo`, `onZoomChange` (1 = eingepasst),
`resetKey` (neuer Wert → neu einpassen; Standard Name + Teil), `ref` → `CanvasHandle { fit(), zoomIn(), zoomOut() }`.

**Einpassen** berücksichtigt alles Gezeichnete mit seiner echten Laufweite: Bezeichner und Kommentar mit dem
**übergebenen** Text (`designator`/`comment`, sonst „U?A“/`spec.comment`), gemessen in derselben Schrift und Stärke
(Canvas-Messung, nach dem Laden der Webschriften neu) samt Ausrichtung (`justify`) – lange MPNs wie „LTC6244CDHC#PBF“ werden
nicht abgeschnitten – sowie Text-Grafiken (Ausrichtung und Drehung) und Pin-Nummern.

- **Verborgene Pins** werden nur mit `showHiddenPins` gezeichnet – und nie über Sichtbares: gestrichelt an ihrer Stelle
  nur, wenn Linie und Texte weder sichtbare Pins (samt Namen/Nummern), Bezeichner/Kommentar, die Symbolkontur noch
  einander berühren. Sonst (typisch: gestapelte Versorgungspins eines IC am Nullpunkt) stehen sie in der Liste
  **„Verborgen“** oben rechts (`7 AGND · 8 PGND`, hervorgehobene in Kupfer, volle Liste als Tooltip und für
  Screenreader in der Beschreibung der Leinwand); die Ansicht reserviert dafür oben Platz.
- **Nullpunkt**: kleines neutrales Kreuz – standardmäßig nur beim Überfahren bzw. mit Tastaturfokus (interaktiv),
  mit `showOrigin` immer, in Vorschaubildern (`interactive={false}`) nie.

**`FootprintCanvas`** – SVG in mm auf dunkler Leiterplatte (`--pf-canvas`, Punktraster passt sich dem Zoom an): Pads aller
Formen (abgerundet mit Altium-%, Drehung, Bohrung/Langloch, nicht durchkontaktiert gestrichelt), Linien/Bögen/Flächen/
Texte je Lage, Lagen-Legende mit Umschaltern (schmal: Menü), Pad-Nummern entlang der langen Padseite (blenden sich unter
7 px aus), Pad-Tooltip, Koordinatenanzeige und Maßstab, Bemaßung aus `calc` (Z/G/X/e, THT-Raster und Bohrung, BGA-Raster).

- **Bemaßung kollisionsfrei:** Maßlinien liegen außerhalb der Kontur aus Pads, Bestückungsdruck, Courtyard und
  Bestückungszeichnung (`footprintContour`), Hilfslinien führen von den Padkanten hinaus. Passt eine Beschriftung nicht
  zwischen die Pfeile, steht sie hinter dem Linienende (am Rand davor) mit gestrichelter Verlängerung. Hinweise (Padmaß,
  Bohrung, BGA-Land Ø) stehen mit **Hinweislinie** außerhalb der Kontur – an der nächsten Ecke, sonst seitlich bzw.
  darüber –, nie auf Maßketten, Info-/Legenden-/Zoom-Overlays; liegt das Ziel außerhalb des Ausschnitts oder ist kein
  freier Platz (stark hineingezoomt), entfallen sie.
- **BGA:** Ballnummern (A1, AB12) passen in den Kreis und erscheinen erst ab 9 px Schrifthöhe; solange sie ausgeblendet
  sind, sagt ein Etikett unten links „Zum Lesen der Ballnummern hineinzoomen“ (nur ohne Legende dort).

```tsx
<FootprintCanvas spec={fp.spec} calc={fp.calc} highlight={['1']} layers={vis} onLayersChange={setVis} className="h-80" />
```

Props: `spec`, `calc`, `showDimensions` (Standard: wenn `calc`), `highlight`, `hoverDesignator`, `onPadHover`,
`onPadClick`, `layers`/`defaultLayers`/`onLayersChange` (`LayerVisibility` = Abweichungen von `DEFAULT_LAYER_VISIBILITY`),
`showLegend` (`true` \| `'wide'` = nur Chips, wenn Platz ist \| `false`), `showPadNumbers`, `showGrid`, `interactive`,
`controls`, `showInfo`, `onZoomChange`, `resetKey`, `ref`. Standardmäßig ausgeblendet: 3D‑Körper, Bauteilumriss, Paste,
Lötstopp, Bezeichner/Kommentar-Texte.

**`Package3D`** – three.js-Szene aus `FootprintSpec.bodies` (extrudierte Prismen, Farbe/Deckkraft aus dem Spec; BGA-Kugeln
als Kugeln) auf einer Leiterplatte mit Bohrungen, vergoldeten Pads (THT mit Hülse) und Bestückungsdruck. **Offline**:
prozedurale Raumumgebung (RoomEnvironment) + Umgebungs-, Halbkugel- und gerichtete Lichter, `ContactShadows`,
`OrbitControls` mit Dämpfung, Kamera passt sich ein, `frameloop="demand"` (kein Dauer-Rendern im Leerlauf). Lazy geladen;
ohne WebGL (oder bei Kontextverlust) erscheint `IsoFallback` – eine isometrische SVG-Zeichnung mit Hinweis.

```tsx
<Package3D spec={fp.spec} autoRotate={rotate} onAutoRotateChange={setRotate} ref={handle} className="h-80" />
// handle.current.fit() = Ansicht zurücksetzen · Tastatur: Pfeile drehen, +/− zoomen, 0 zurück, Leertaste dreht automatisch
```

**Bedienung aller Leinwände** (`role="application"`, fokussierbar): Mausrad zoomt am Zeiger, Ziehen verschiebt,
Doppelklick passt ein; Tastatur: Pfeile verschieben (⇧ weiter), `+`/`−`, `0`/`F` einpassen, **`N`/⇧`N` nächster
Pin bzw. nächstes Pad** (mit Tooltip und Ansage), `Esc`, `Bild↑/↓` wechselt das Teil. Ein Hinweis erscheint bei
Tastaturfokus. Für eigene Leinwände: `usePanZoom({ bbox, width, height, padding, insets, resetKey })` und
`useElementSize()`; Overlays mit `CanvasTooltip`, `CanvasBadge`, `CanvasZoomControls`, Flächen `CHROME_SURFACE.board|app`.

### Tabellen `@/components/grid`

**`DataGrid<T>`** – AG Grid (Community) mit Theme **„Forge“** (Theming-API v36, alle Farben `var(--pf-…)` → folgt dem
Theme ohne Neuaufbau), kompakt (32 px), deutsche Texte, Overlays im UI-Kit-Stil, Spaltenzustand gespeichert.

**Module:** Statt `AllCommunityModule` sind nur die genutzten Module gebündelt (`FORGE_GRID_MODULES` in
`components/grid/modules.ts`: Client-/Infinite-Row-Model, Auswahl, Text-/Zahl-/Eigene Editoren, Text-/Zahl-/Datums- und
Schnellfilter, Grid-State, Spalten-/Zeilen-/Scroll-/Render-/Event-API, Auto-Breite, Zell-Aufleuchten, Zell-/Zeilenstile,
Tooltips, Locale). Sie sind **global registriert**, sobald `@/components/grid` geladen ist – eigene `<AgGridReact>` brauchen
kein `modules`. Ein vorhandenes `modules={[AllCommunityModule]}` bleibt gültig: Für Quelldateien leitet
`vite.config.ts` den Export `AllCommunityModule` auf `ForgeCommunityModule` (dieselben Module) um. Neue Grid-Funktion
(z. B. Pagination, CSV-Export, Zeilen ziehen)? Das Modul in `FORGE_GRID_MODULES` ergänzen – im Entwicklungsmodus nennt
AG Grid fehlende Module („error #200 … is not registered“).

```tsx
import { DataGrid } from '@/components/grid'

<DataGrid<Part>
  aria-label="Widerstände" rowData={rows} columnDefs={cols} getRowId={(r) => r['Part Number']}
  selection="multiple" onSelectionChange={setSelected} onRowActivated={(r) => openDrawer(r)}
  persistKey="parts:Resistors" loading={q.isLoading} refreshing={q.isFetching}
  emptyState={{ title: 'Noch keine Bauteile', description: '…', illustration: 'no-parts', actions: <Button>…</Button> }}
  quickFilterText={search} gridRef={gridRef} className="h-full" />

const cols: ColDef<Part>[] = [
  { field: 'Part Number', type: 'mono', pinned: 'left' },
  { field: 'Resistance', headerName: 'Widerstand', type: 'quantity' },          // „10 kΩ“, sortiert numerisch
  { field: 'Package', type: 'badge', cellRendererParams: { mono: true } },
  { field: 'Library Ref', type: 'symbolRef', cellRendererParams: { loadPreview, libraryField: 'Library Path' } },
  { field: 'Footprint Ref', type: 'footprintRef', cellRendererParams: { loadPreview } },
  { field: 'Lifecycle', type: 'status' },                                       // Aktiv ● grün, NRND ● gelb, Abgekündigt ● rot …
  { field: 'ComponentLink1URL', headerName: 'Datenblatt', type: 'link' },
]
```

| Prop | Bedeutung |
| --- | --- |
| `selection` | `'single'` (Klick) \| `'multiple'` (Kontrollkästchen-Spalte, ⇧/Strg) \| `false` |
| `onRowActivated` | **Enter** oder Doppelklick; Enter auf einer Zelle mit Link/Knopf löst diesen aus (Datenblatt, Vorschau). Gilt auch für die Bauteiltabelle (`pages/bauteile/grid/PartsGrid`, eigenes AG Grid mit Server-Paging): Doppelklick öffnet die Details – auf einem Wert mit dem Fokus in diesem Feld –, bearbeitet wird dort mit F2, Tippen oder dem Kontextmenü („… bearbeiten“); der Popup-Editor heißt „Beschreibung bearbeiten – CRCW…“ |
| `persistKey` | Breiten, Reihenfolge, ausgeblendete Spalten, Sortierung, Anheften: localStorage vollständig + Cookie-Pref `pf-grids` begrenzt auf ~3 KB (zuletzt benutzte Tabellen) – `clearGridState(key)` setzt zurück |
| `loading` / `refreshing` | Overlay beim ersten Laden / Ladebalken oben bei vorhandenen Zeilen |
| `emptyState`, `noMatchState`, `loadingText` | Overlays (EmptyState-Illustrationen) |
| `density` | `'compact'` (32 px) \| `'comfortable'` (40 px) |
| `gridRef`, `onApiReady` | Zugriff auf die Grid-API |
| alle übrigen AG-Grid-Props | werden durchgereicht (`quickFilterText`, `onCellValueChanged`, `pagination` …) |

Spaltentypen (`FORGE_COLUMN_TYPES`, kombinierbar `type: ['mono', 'right']`): `mono`, `right`, `number`, `quantity`,
`badge`, `status`, `link`, `symbolRef`, `footprintRef`. Renderer einzeln: `QuantityCell` (`unit`, `digits`),
`EnumBadgeCell` (`tones`, `mono`), `StatusCell` (`tones`, `labels`; bekannte Werte in `STATUS_TONES`), `LinkCell`
(`kind: 'url' | 'path'` – Pfade öffnen den Explorer über die Desktop-Brücke), `SymbolRefCell`/`FootprintRefCell`
(Vorschau-Karte beim Überfahren oder Enter; `loadPreview(ref, row, signal) → { symbol | footprint | svg }`, gecacht unter
`['symbols' | 'footprints', 'ref-preview', ref]`). Formatierung: `formatQuantityText('0.1W')` → „0,1 W“,
`quantityComparator`. Filter-Knöpfe der Kopfzeile erscheinen beim Überfahren/Fokus oder bei aktivem Filter.

### Daten `@/components/data`

**`CategoryTree`** – ARIA-Tree mit Gruppen (einklappbar, gespeichert), Suche (markiert Treffer), Zähler, Symbol in
Kategoriefarbe. Tastatur: ↑/↓, →/← (auf-/zuklappen bzw. zur Gruppe), Pos1/Ende, Enter/Leertaste, Anfangsbuchstaben;
aus der Suche mit ↓ in den Baum.

```tsx
const { items, total, isLoading } = useCategoryTreeItems()     // /api/categories mit Zählern, gruppiert (CATEGORY_GROUPS)
<CategoryTree items={items} value={table} onValueChange={setTable} allItem={{ label: 'Alle Bauteile', count: total }}
  groupOrder={CATEGORY_GROUP_ORDER} loading={isLoading} persistKey="bauteile" className="h-full" />
```

Eintrag: `{ id, label, icon?: lucide-Name | ReactNode, color?, count?, group?, keywords? }`. `CategoryIcon` bildet die
Lucide-Namen der Datenbank ab (feste Auswahl, „waves“ → `WavesHorizontal`, Unbekanntes → `Box`).

**`FileDropZone`** – ganze Fläche ist ein Knopf (Klick/Enter/Leertaste öffnen die Auswahl), animierter Rahmen beim Ziehen,
falscher Typ rot mit deutscher Erklärung, `busy` zeigt den Fortschritt. Unterdrückt das globale Datenblatt-Overlay.

```tsx
<FileDropZone variant="pdf" onFiles={startImport} />                                  // KI-Stil (Funken), PDF bis 50 MB
<FileDropZone variant="pdf" tone="neutral" onFiles={attach} />                        // PDF ohne KI-Bezug (z. B. anhängen)
<FileDropZone variant="table" size="md" multiple={false} onFiles={([f]) => preview(f)} busy={pending && 'Lese Tabelle …'} />
<FileDropZone variant="csv" size="sm" onFiles={…} />                                  // kompakte Zeile
```

Props: `variant` (`pdf | table | csv | xlsx`), `onFiles`, `onReject`, `multiple`, `maxSize`, `accept` (eigene Typen),
`typesLabel` (erlaubte Typen in Worten für Hinweis und Ablehnung, z. B. „CSV, Excel oder OpenDocument“ – zu eigenem
`accept` immer setzen), `hint` (eigene Hinweiszeile statt „PDF · bis 50 MB · mehrere Dateien möglich“; `false` = keine),
`disabled`, `busy` (`true` oder Text), `size` (`lg | md | sm`), `title`, `description`, `tone`.

**`tone`**: `ai` = Funken-Stil, „Loslassen zum Analysieren“, Text verspricht die KI-Erkennung; `neutral` = Kupfer/neutral,
„Loslassen zum Hinzufügen“, Text ohne KI („Das PDF wird in der Bibliothek abgelegt … die Analyse mit KI ist derzeit nicht
verfügbar“); `auto` (**Standard bei `pdf`**) = `ai`, solange die KI eingeschaltet und ein Schlüssel hinterlegt ist, sonst
`neutral` – Seiten müssen dafür nichts tun. Tabellen sind immer `neutral`. Barrierefreiheit: Name = sichtbarer Titel (+ „oder
klicken, um Dateien auszuwählen“ für Screenreader), Beschreibung und Hinweis per `aria-describedby`, das Dateifeld liegt
**außerhalb** des Knopfs (keine verschachtelten Bedienelemente).

```tsx
<FileDropZone variant="table" accept={ACCEPT} typesLabel="CSV, Excel oder OpenDocument" hint="Bis 50 MB · eine Datei" … />
```

**`SplitPane`** – zwei Bereiche, Trenner mit Maus und Tastatur (←/→ 16 px, ⇧ 64 px, Pos1/Ende, Enter klappt ein),
Doppelklick setzt zurück bzw. klappt ein; Größe des **primären** Bereichs in px, gespeichert unter `persistKey`.

```tsx
<SplitPane persistKey="bauteile.baum" primary="start" defaultSize={264} minSize={200} maxSize={420} collapsible
  label="Breite des Kategoriebaums" start={<CategoryTree … />} end={<DataGrid … />} />
```

Props: `start`, `end`, `direction` (`horizontal | vertical`), `primary`, `defaultSize`, `minSize`, `maxSize`, `minRest`,
`persistKey`, `collapsible`, `collapsed`/`onCollapsedChange`, `onSizeChange`, `label`, Klassen je Bereich.

**`VirtualGallery`** + **`GalleryCard`** + **`LazyThumbnail`** – virtualisierte Kartengalerie (Spaltenzahl aus der
Breite), Listbox mit aktivem Element: Pfeile, Pos1/Ende (Strg = Anfang/Ende der Liste), Bild↑/↓, Leertaste wählt, Enter
öffnet. Vorschaubilder laden erst im Sichtbereich; SVG-Markup wird als Bild (Blob-URL) eingebunden, nie ins DOM.

```tsx
<VirtualGallery aria-label="Footprints" items={list} getKey={(f) => f.name} minItemWidth={172} itemHeight={188}
  selectedKey={sel} onSelect={(f) => setSel(f.name)} onActivate={open}
  renderItem={(f, s) => (
    <GalleryCard board title={f.name} meta={f.description} selected={s.selected} active={s.active}
      thumbnail={<LazyThumbnail queryKey={['footprints', 'thumb', f.name]} loadSvg={(signal) => renderSvg(f, signal)} />} />
  )} />
```

`LazyThumbnail`: `src` (Bild-URL) **oder** `loadSvg` + `queryKey` (React Query, erstes Element = Modulname) **oder**
`render` (z. B. `<SymbolCanvas interactive={false} … />`), `rootMargin`, `inset`. `GalleryCard`: `board` = dunkle
Leiterplatten-Fläche (Footprints), sonst Punktraster (Symbole); `badge`, `meta`. Der Titel bricht an beliebiger Stelle
um und wird nach **zwei Zeilen** gekürzt (`line-clamp-2`), der volle Text steht im `title`-Attribut (bei String-Titeln
automatisch, sonst `titleText`); `mono={false}` für Klartext-Titel. Eigene `line-clamp`-Hüllen sind nicht mehr nötig.

**`TemplateTokenInput`** – Vorlagen wie `RES {Size} {Resistance:rkm}`: Platzhalter als Chips (unbekannte Felder rot und
gewellt unterstrichen, unbekannte Formate gelb), `{` öffnet die Feldliste, `:` im Platzhalter die Formate
(`TEMPLATE_FORMATS`: rkm, si, nounit, upper, lower), ↑/↓, Enter/Tab, Esc; **Strg+Leertaste** fügt an der Schreibmarke ein.
Live-Vorschau entprellt über `onPreviewRequest`.

```tsx
<Field label="Beschreibung (Vorlage)">
  <TemplateTokenInput value={tpl} onValueChange={setTpl}
    fields={category.fields.map((f) => ({ name: f.column, label: f.label, kind: f.kind, unit: f.unit }))}
    preview={preview} previewLoading={pending} onPreviewRequest={(t) => requestPreview(t)} />
</Field>
```

Hilfsfunktionen: `parseTemplate`, `tokenAt`, `buildToken`, `templateFields` (gleiche Syntax wie `partforge/db/values.py`).

## Technische Werte `@/lib/units`

```ts
parseEngineering('4k7')            // 4700   (auch „100n“, „2,2 µF“, „0R“, „R47“, „1e3“)
formatEngineering(4700, 'Ω')       // „4,7 kΩ“ (geschütztes Leerzeichen)
formatRkm(4700)                    // „4k7“   (Comment = Wert)
valuesInRange('E24', 10, 1e6)      // [10, 11, 12, …]  – Tabellen identisch mit partforge/domain/eseries.py
nearestInSeries('E12', 5000)       // 4700
stepInSeries('E12', 4700, +1)      // 5600
E_SERIES_TOLERANCE.E96             // „±1 %“
```

`@/lib/format`: `formatNumber` (Formatierer gecacht), `formatNumbersInText` (Mengen in Backend-Texten gruppieren: „6212
Bauteile exportiert“ → „6.212 Bauteile exportiert“; Teilenummern, Bauformen wie 0603/1206, Pfade, Uhrzeiten, Datums- und
Dezimalzahlen bleiben – Job-Toasts und das Job-Dock nutzen es automatisch), `formatDecimal`, `parseDecimal` (deutsche Eingabe),
`formatCompact`, `formatPercent`, `formatRelativeTime`, `formatDateTime`, `formatDuration`, `formatBytes`,
`shortenPath`, `baseName`, `plural`, `greeting`.

## API

```ts
import { api, ApiError, errorMessage, isAbortError } from '@/api/client'
import type { Filled, RequestBodyOf, ResponseOf } from '@/api/types'

type Page = Filled<ResponseOf<'/api/parts/{table}', 'get'>>          // Typen über den Endpunkt, nicht den Modellnamen
const parts = await api.get<Page>('/api/parts/Resistors', { query: { search: '10k' }, signal })
await api.post('/api/parts/Resistors', body)    // JSON; put/patch/delete analog; Zeitlimit 30 s (timeoutMs)
await api.upload('/api/import/preview', form)   // multipart (FormData), ohne Zeitlimit
api.url('/api/datasheets/123/file')             // URL mit ?token=… für <img>, <iframe>, Downloads, EventSource
const { blob, fileName } = await api.download('/api/altium/dblib/preview', { query: { raw: true } })
//   Datei + Name aus Content-Disposition (UTF-8 nach RFC 5987 vor filename="…"; sonst `fallbackName` bzw. letzter
//   Pfadabschnitt) – speichern mit saveBlob(blob, fileName, …) aus @/lib/download; fileNameFromDisposition() einzeln
```

- **Typen immer aus `schema.d.ts` ableiten** (`ResponseOf`, `RequestBodyOf`, `QueryOf`; `Filled<T>` macht die bei
  Pydantic-Standardwerten optionalen Felder verpflichtend und **erhält Tupel** – `StepModel.rotation` bleibt
  `[number, number, number]`). Backend-Modelle dürfen umbenannt werden – Endpunkte nicht.
  `npm run build` bricht ab, wenn das Schema veraltet ist → `npm run gen:api` und Typfehler beheben.
- Fehler sind `ApiError` mit `status`, `detail` (roh) und `message` (deutscher Text; Pydantic-Validierungen übersetzt);
  `isTimeout` (408 = Client-Zeitlimit), `isNoWorkspace` (409 – bevorzugt über `detail.code === 'no_workspace'`),
  `isLibraryBusy` (409 „Die Bibliothek wird gerade geschrieben …“ – vorübergehend, „Erneut versuchen“ anbieten, kein
  Konflikt mit der Eingabe). Abbrüche (`AbortSignal`) werfen den Grund des Signals unverändert (`isAbortError`).
- `cleanErrorText(text)` entfernt vorsorglich einen führenden Python-Klassennamen („ValueError: Die Datei …“ → „Die
  Datei …“; „Interner Fehler (KeyError): …“ bleibt) und übersetzt Python-Darstellungen von Betriebssystemfehlern
  („[Errno 13] Permission denied: 'C:\\…\\PF_CHIP.PcbLib'“ → „Zugriff verweigert – die Datei ist von einem anderen
  Programm geöffnet oder schreibgeschützt (C:\…\PF_CHIP.PcbLib)“; „[WinError 32] …“ ohne Präfix, Pfade mit einfachen
  Backslashes) – die automatischen Fehler-Toasts (Mutationen, `meta.errorToast`) und alle Job-Meldungen nutzen es;
  eigene Toasts mit Backend-Text ebenso: `cleanErrorText(errorMessage(err))`.
- `observeApi(method, path, listener)` beobachtet einen Endpunkt, gleich wer ihn aufruft (`{ ok: true, data } | { ok: false,
  error }`, Abbrüche nicht) – so merkt sich die Seitenleiste das Ergebnis von `POST /api/ai/test` aus Einstellungen und Import.
- 401 → Vollbild „Sitzung ungültig“; 409 „keine Bibliothek geöffnet“ → **ein** Hinweis + zurück zu `/willkommen`.
- React Query (`queryClient`): `staleTime` 10 s, kein Refetch bei Fokus, Retry nur bei Netzwerkfehlern.
  **Mutationen zeigen bei Fehlern automatisch einen Toast** – steuerbar über
  `meta: { errorTitle: '…', silentError: true, successMessage: '…' }`. Queries: `meta: { errorToast: 'Titel' }`.
- **Query-Keys: erstes Element = Modulname** (`['parts', …]`, `['series', …]`). Beim Bibliothekswechsel werden laufende
  Abfragen abgebrochen und alle Queries außer `['system', …]` zurückgesetzt (`resetWorkspaceScopedQueries`).
  Nach einem **beendeten Job** lädt das Dock die Module neu, die der Job geändert haben kann (`jobRefreshScopes(kind)`
  aus `@/api/jobs`): `export`, `datasheet-find`, `altium.odbc_test`, `altium.open` → nichts; `altium.install|uninstall|
  install_state|refresh|verify` → nur `['altium', …]`; `datasheet` → `['datasheets', …]` und `['stats']`; alle übrigen
  (`series`, `import`, `libraries…`, `datasheet-commit`, unbekannte Arten) → alle modulbezogenen Queries – schreibende
  Jobs auch nach Fehlschlag oder Abbruch (bis dahin Geschriebenes bleibt), nicht nach einem Bibliothekswechsel. Nie
  neu geladen werden Queries mit **`meta: { static: true }`** (Daten, die kein Job ändert: Generator-Familien, Vorlagen,
  Symboltypen …).
  Der **Prüfbericht** (`useHealthReport` aus `@/api/libraries`: `/api/health-check` + `/api/libraries/health`, beide
  über die ganze Bibliothek) ist ebenfalls `static`: er lädt nur nach Jobs, die Bauteile oder Bibliotheksdateien ändern
  (`HEALTH_JOB_KINDS`: `series`, `import`, `datasheet-commit`, `libraries*`), nach direkten Schreibzugriffen auf
  Bauteile/Kategorien/externe Bibliotheken (gebündelt, 1,2 s) und bei „Bibliothek prüfen“ neu – sonst zeigen Übersicht
  und Altium-Seite den vorhandenen Bericht sofort (spätestens nach 10 Minuten frisch).
- `@/api/system`: Typen (`AppSettings`, `SettingsOut` inkl. `ai_key_source`, `WorkspaceInfo`, `WorkspaceSettings`,
  `LayerMap`, `FootprintStyle`, `SymbolStyle`, `Job`, …) und Hooks `useHealth`, `useSettings`, `useSaveSettings`
  (**bekommt eine Änderungsfunktion**: `save.mutate((cur) => ({ ...cur, author }))` – angewendet auf den frischen
  Serverstand, damit `workspace`/`recent_workspaces` nie mit veralteten Werten überschrieben werden), `useSaveApiKey`,
  `useDeleteApiKey`, `useWorkspace`, `useRecentWorkspaces`, `useOpenWorkspace`, `useCreateWorkspace`, `useCloseWorkspace`,
  `useSaveWorkspaceSettings`, `useWorkspaceDefaults(name)` (Vorschlag für eine neue Bibliothek),
  `useJobs`, `useLibraryJobs` (nur Jobs der geöffneten Bibliothek, siehe „Hintergrundjobs“),
  `useCancelJob`; Rohfunktionen in `systemApi`, Keys in `systemKeys`. `useSaveSettings` lädt danach Health **und den
  Altium-/Writer-Status** (`['altium', 'status']`) neu – `await save.mutateAsync(…)` endet erst mit dem frischen Status
  (Seitenleiste und Einstellungen zeigen einen neuen Writer-Pfad sofort, nicht erst nach dem 15-s-Abruf).
  KI-Verbindung: `useAiConnection((s) => s.last)` → letzter Verbindungstest `{ at, ok, code, message, model, latencyMs,
  signature, source }` (gespeichert; ein neuer/entfernter Schlüssel setzt ihn zurück; gilt nur, solange
  `aiSettingsSignature(settings)` gleich ist), `classifyAiError(err)` → `{ code, message }` mit den Codes von
  `POST /api/ai/test` (`key_missing | key_rejected | model_unavailable | network | rate_limited | ai_disabled | unknown`;
  ältere Backends ohne `detail.code`: aus dem Wortlaut).
  `useCreateWorkspace` liefert `CreatedWorkspace` (Workspace-Info + `examples`, `examples_error`, `job`).
- `@/api/library`: `useCategories()`, `useCategoryLabel(table)`, `useLibraryStats()` (`/api/stats`), `libraryApi.search`;
  Typen `CategoryDef`, `FieldDef`, `LibraryStats`, `AuditEntry`, `SearchHit`. Module legen eigene Dateien an
  (`src/api/parts.ts`, `src/api/series.ts` …).
- `@/api/settings`: u. a. `refreshAltiumStatus()` – Altium-Status (`['altium', 'status']`) sofort neu laden und den
  frischen Stand liefern (nach dem Speichern eines X2- oder Writer-Pfads; Einstellungen › Allgemein meldet damit
  „Bibliotheks-Writer gefunden (0.1.0)“ bzw. „Bibliotheks-Writer nicht gefunden: C:\…“).
- `@/api/parts`: CSV-Exporte fragen immer `excel_safe` an (Formel-Injektion: Werte mit =, +, @ … bekommen ein `'`);
  `partsApi.query(table, body, signal)` – überholte Abfragen der Bauteiltabelle werden abgebrochen.

## Hintergrundjobs

```ts
import { jobOutcome, jobResultProblem, setJobFeedback, trackJob, useJob } from '@/api/jobs'

const { job } = await api.post<{ job: Job }>('/api/import/run', body)
trackJob(job)                                  // Cache befüllen + im Job-Dock zeigen (Pille; das Panel öffnet sich nie von selbst)
const { job: live, isActive } = useJob(job.id, {
  onDone: (j) => navigate(`/bauteile/${j.result.table}`),   // Folgeaktion – KEIN eigener Erfolgs-Toast
  onFailed: (j) => setError(j.error),
})

// Rückmeldung steuern (alle Optionen frei kombinierbar):
trackJob(job, { dock: false, toast: false })                // Seite zeigt Fortschritt/Ergebnis selbst (Inline, Erfolgsbildschirm)
trackJob(job, { doneMessage: (j) => `${j.result.created} Bauteile angelegt` })   // Text des Erfolgs-Toasts
trackJob(job, { warnWhen: (j) => (j.result.conflicts ? `${j.result.conflicts} Konflikte` : null) })
setJobFeedback(job.id, { toast: true })                     // nachträglich ändern, z. B. wenn die Inline-Anzeige schließt
```

- **Das Panel öffnet sich nie von selbst** (es verdeckte sonst Inhalte, z. B. die Aktionsleiste der Altium-Seite): Ein
  neuer Job erscheint in der Pille; `openDock` ist ohne Wirkung (veraltet). Öffnen: Klick auf die Pille, „Details“ eines
  Job-Toasts, Befehl „Hintergrundjobs anzeigen“ – schließen: „Minimieren“ oder Esc (Fokus im Panel).
- **Abschluss-Toast** genau einmal je Job (egal ob per SSE, Polling oder Jobliste erkannt – auch für Jobs, die fertig
  waren, bevor die Jobliste sie je laufend sah): Erfolg mit `doneMessage` bzw. der letzten Meldung; **Warnung** (mit
  Aktion „Details“ = Panel + Log bzw. der **Behebung** als Aktion und „Details“ daneben), wenn das Ergebnis Probleme
  meldet; Fehler mit „Details“; Abbruch als Info. **Ein Abbruch durch einen Bibliothekswechsel** (`cancel_reason
  'library_switch'`) wird **immer** gemeldet – auch bei `toast: false`/inline gezeigten Jobs (deren Seite gehört zur
  alten Bibliothek) – und kehrt in die Pille zurück („Erledigt mit Hinweisen“). Vor dem Wechsel fragt die Shell, wenn
  dabei Jobs abgebrochen würden (`confirmLibrarySwitch`, siehe „Weitere Helfer“). **Kein** Toast für erfolgreiche Jobs
  mit `result.quiet === true` (automatisches `altium.refresh`, das keine installierte DbLib fand – ARCHITEKTUR §8.2).
- **Probleme im Ergebnis** (Standard `jobResultProblem(job)`, `warnWhen` ersetzt sie): `skipped: true` (+ `reason`),
  `outcome: 'partial'`, `error_count > 0`, `errors` als Zahl/Liste/Objekt (erster Eintrag wird genannt),
  **`library_problems`** (Symbole/Footprints, die **nicht** in ihre SchLib/PcbLib geschrieben wurden: `[{ name, library,
  status: 'error' | 'pending', message }]` – „Footprint RESC6332X70N wurde nicht in PF_CHIP.PcbLib geschrieben – Datei
  gesperrt“, Kurzfassung über `library_problems_count`; lesen mit `jobLibraryProblems(result)`) und `missing` als Liste
  von Einträgen mit `name` („2 Einträge nicht erzeugbar – …“). Zählfelder wie `skipped: 12` sind kein Problem.
- `jobOutcome(job)` → `{ tone: 'success' | 'warning' | 'error' | 'info', title, description, problem, action }` – dieselbe
  Bewertung für eigene Anzeigen (das Job-Dock zeigt Warnungen mit gelbem Ring und dem Problem als Statuszeile).
  `description` ist für Toasts auf 200 Zeichen gekürzt – am Satz- bzw. Wortende, nie mitten im Wort (`clipText`);
  **`problem` ist der volle Text** (Inline-Anzeigen, Tooltips). `action` = Behebung `{ label, to, state? }` oder `null`
  (`state` = Router-State des Ziels, `appNavigate(to, { state })`):
  `SETUP_WRITER_ACTION` („Writer einrichten“ → `/einstellungen#altium`), wenn mangels Bibliotheks-Writer nichts geschrieben
  wurde (`jobLacksWriter(job)`; der Toast nennt dann die kurze Schlussmeldung), `SYNC_LIBRARIES_ACTION`
  („Synchronisieren“ → `/altium` mit `altiumActionState('sync')`) bei **ausstehenden** `library_problems` (`status: 'pending'` – die Bauteile
  sind angelegt, Synchronisieren schreibt nach); fehlgeschlagene (`error`: Ursache beheben, Job wiederholen) haben keinen
  Knopf. Eine Fehlerzahl (`errors: 22`) nennt als ersten Grund den Eintrag aus `library_problems` bzw. `error_details`.
  Texte sind bereinigt (`cleanErrorText`) und deutsch gruppiert (`formatNumbersInText`: „7077 Bauteile exportiert“ → „7.077 …“).
- **Abbruch:** `jobCancelText(job, short?)` – bei `cancel_reason === 'library_switch'` („Die Bibliothek wurde gewechselt oder
  geschlossen – der Job wurde abgebrochen. In die andere Bibliothek wurde nichts geschrieben.“, Toast länger und mit
  „Details“), sonst die Schlussmeldung des Jobs bzw. „Abgebrochen“. Solange `cancel_requested` gilt, zeigt das Dock
  „Wird abgebrochen …“.

**Job-Felder** (`Job` aus `@/api/system`): zusätzlich `detail` (strukturierter Fortschritt `ctx.detail(…)`, z. B.
`{ step, step_label, cost_usd, phase, done, total }` – typisiert lesen mit `jobDetail<T>(job)` statt Logzeilen zu parsen),
`error_type` (Ausnahmeklasse, nur zum Auswerten), `cancel_reason`, `cancel_requested`, `result_truncated` (Kurzfassung),
**`library`** (Ordner der Bibliothek, für die der Job gestartet wurde; fehlt bzw. `null` = an keine gebunden).

**Jobs anderer Bibliotheken:** Seiten zeigen Fortschritt und Ergebnis nur für Jobs der **geöffneten** Bibliothek –
`useLibraryJobs(kind?)` statt `useJobs(kind)` bzw. `isJobOfLibrary(job, workspace.root)` (Jobs ohne `library` gelten
als zugehörig; `sameLibraryRoot(a, b)` vergleicht Ordner ohne Rücksicht auf Groß/klein und `/`/`\`). Das Job-Dock listet
weiter alle und nennt bei fremden den Namen ihrer Bibliothek (aus „Zuletzt verwendet“, sonst der Ordnername).

**Kurzfassungen und volle Ergebnisse:** `useJobs()` (Job-Dock, Joblisten der Seiten) lädt `GET /api/jobs?brief=true` und
hört live auf `/api/jobs/events?brief=true` (eine geteilte EventSource; ohne Strom wird gepollt). Ergebnisse über 8 KB sind
dort gekürzt (`isJobResultTruncated(job)`: Skalare bleiben, Listen/Objekte → `<name>_count`, von `errors`/`warnings`/
`missing` die ersten 5) – `jobResultProblem` zählt dann mit `errors_count`/`missing_count`. **Das volle Ergebnis:**

```ts
import { fetchJob, useJobResult } from '@/api/jobs'

const { result, job } = useJobResult<VerifyResult>(latest?.id)   // in Komponenten (null, solange er läuft)
const full = await fetchJob<VerifyResult>(id)                    // in Folgeaktionen (Cache wird befüllt)
```

`useJob`/`trackJob`/`fetchJob` halten immer vollständige Schnappschüsse. `doneMessage`/`warnWhen` bekommen ebenfalls das
volle Ergebnis (das Dock lädt es bei Bedarf nach); wirft eine dieser Funktionen, gilt der Standardtext.

**Dock und Seite stimmen überein:** Jeder Schnappschuss aus `useJob` (SSE je Job, Abfrage) und `trackJob` wird – nach
`version` – in die Joblisten übernommen; Fortschritt aus dem Live-Strom fließt umgekehrt in laufende `useJob`-Schnappschüsse.
Kein Ort zeigt einen älteren Stand als ein anderer.

**Inline gezeigte Jobs:** Zeigt die Seite Fortschritt und Ergebnis selbst, gehört der Job nicht in die Pille:

```ts
trackJob(job, { dock: false, toast: false })   // beim Start: zählt nicht in Pille/Ring, kein Toast, Panel listet ihn weiter
useInlineJob(jobId)                            // in der Anzeige: solange gemountet inline – danach übernimmt das Dock
setJobFeedback(jobId, { dock: true })          // von Hand zurück in die Pille
```

`useInlineJob` gibt einen beim Verlassen noch laufenden Job an die Pille zurück (mit Abschluss-Toast); ein schon beendeter
bleibt still im Panel – außer ein Bibliothekswechsel hat ihn abgebrochen (immer Pille und Toast, s. o.). Beispiel:
„Neue Bibliothek“ (Erfolgsansicht mit „Bibliotheken schreiben“).

`useJob` hört per SSE auf `/api/jobs/{id}/events` – **eine geteilte Verbindung je Job-ID**, höchstens `MAX_STREAMS` (2)
gleichzeitig, weitere Jobs werden gepollt (die 6 HTTP/1.1-Verbindungen je Host bleiben frei). Ältere Schnappschüsse
überschreiben nie neuere (`version`); unbekannte Jobs (404) werden nicht endlos abgefragt. Das Job-Dock zeigt alle
Jobs aus `/api/jobs?brief=true` (live) mit Fortschrittsring, Abbrechen und Log (letzte 200 Zeilen, voller Schnappschuss).

**Job-Dock im Ruhezustand:** Laufen keine Jobs, blendet sich die Pille („Alle Jobs erledigt“ / „Erledigt mit
Hinweisen“) nach 4,5 s aus (Zeitgeber wartet, solange Maus oder Tastaturfokus auf dem Dock liegen; nach dem Zuklappen des
Panels erneut). **Ungesehene Fehlschläge** verkleinern sie nach 6 s zu einem runden Hinweis (rotes ✕), der bleibt, bis
das Panel einmal offen war. Beim Start schon fertige Jobs erscheinen gar nicht erst. Panel öffnen: Strg+K →
„Hintergrundjobs anzeigen“, Klick auf die Pille oder `useJobDock.getState().setOpen(true)` / `showLog(id)` (ein neuer
Job zeigt nur die Pille). Platzbedarf: `--pf-dock-reserve` (siehe „Seiten bauen“).

## Befehlspalette & Tastenkürzel

```ts
import { useRegisterCommands, useRegisterSearchProvider } from '@/app/commands'

useRegisterCommands([
  { id: 'parts.new', title: 'Neues Bauteil', group: 'Aktionen', icon: Plus, hotkey: 'mod+n', run: () => setOpen(true) },
  { id: 'parts.export', title: 'Tabelle exportieren', group: 'Aktionen', icon: Download, run: exportCsv },
])
```

- Befehle gelten, solange die Komponente gemountet ist; `run`/`when` dürfen sich ändern. Gleiche ID überlagert: Es gilt
  die **zuletzt gemountete** Komponente (stabil, auch wenn die Shell ihre Liste neu registriert). Eingebaut
  (`app/shell/ShellCommands.tsx`): `parts.new` → `/bauteile?neu=1`, `series.new` „Serie erzeugen“ → `/serien`,
  `import.datasheet` → `/import`, `import.find` „Datenblatt suchen …“ → `/import?suche=1` (KI-Stil; gesperrt, solange
  die KI aus ist oder kein Schlüssel hinterlegt ist), `altium.regenerate`, `library.sync`, `library.check` und
  `altium.install` → `/altium` mit der Aktion `dblib`, `sync`, `pruefen` bzw. `installieren` als Router-State
  (`altiumActionState`, siehe „Seiten bauen“ › Aktionen der Altium-Seite),
  `settings.ai` „KI-Funktionen einstellen“ → `/einstellungen#ki`, `settings.altium` „Altium und Bibliotheks-Writer
  einstellen“ → `/einstellungen#altium`; Bibliotheksaktionen „Neue Bibliothek anlegen …“, „Bibliothek öffnen …“,
  „Wechseln zu …“, „Bibliothek schließen“ (fragen vorher, wenn dabei Jobs abgebrochen würden).
- `disabled: () => string | false` – sichtbar, aber gerade nicht ausführbar: Die Palette zeigt den Grund statt des
  Untertitels, dimmt den Eintrag und wählt ihn nicht aus; sein Tastenkürzel und `runCommand` wirken nicht.
- `target` (z. B. `'/serien'`): Befehle mit gleichem Ziel erscheinen in den Suchergebnissen nur einmal.
- Rangfolge der Suche: echte Titeltreffer (cmdk-Bewertung ≥ 0,1 – Wortanfang, zusammenhängend, mitten im Wort) vor
  Treffern in Untertitel/Stichworten; verstreute Einzelbuchstaben („Serie“ in „Bibliotheksordner im Explorer zeigen“)
  zählen nicht.
- **Bauteil-Schnellsuche ist eingebaut** (Suchanbieter `parts`, `/api/search`, Ziel `/bauteile/:table?pn=…`). Eigene
  Anbieter: `useRegisterSearchProvider({ id, group, minQueryLength, search: async (q, signal) => [...] })`. Treffer-Titel
  stehen in Monospace (Teilenummern, Namen) – für Klartext (Kategorien, Symboltypen, Einstellungen) `mono: false` am
  Treffer setzen.
- Gruppen: „Aktionen“, „Navigation“, „Bibliothek“, „Darstellung“, „System“ (eigene möglich). `ai: true` = Funken-Stil.
- Globale Kürzel: `Strg+K` Palette, `Alt+1…8` Navigation, `Strg+B` Seitenleiste, `Strg+N` neues Bauteil,
  `Strg+S` speichern (siehe unten). Befehls-`hotkey`s werden automatisch ausgelöst – in Eingabefeldern nur mit
  Strg/⌘ (**nie mit Alt allein**: Windows-Alt-Codes wie Alt+0177 = ±), Alt+Ziffer nur über die Hauptreihe, nicht bei
  offenem **modalem** Dialog (`aria-modal="true"`). Seitenlokale Kürzel: `useHotkey('mod+f', handler, { allowInInputs: true })`.
- **Strg+S / Strg+⇧+S** fängt die Shell **immer** ab (Capture-Phase – auch hinter modalen Dialogen, im Palette-Feld
  und bei gehaltener Taste; WebView2 öffnet nie „Seite speichern unter“). Eigenes `preventDefault` oder
  `useHotkey('mod+s', () => undefined)` ist nicht mehr nötig. Ausgeführt wird der **zuletzt gemountete aktive**
  Speichern-Handler – Befehle mit `hotkey: 'mod+s'` (bzw. `'mod+shift+s'`) nehmen an derselben Rangfolge teil:

  ```ts
  import { useSaveHandler } from '@/app/commands'

  useSaveHandler(save, { enabled: dirty && !saving, saveAs: () => setSaveAsOpen(true) })   // Seite
  useSaveHandler(submit, { modal: true })     // im Dialog: speichert den Dialog, nicht die Seite dahinter
  ```

  Ohne `modal: true` läuft ein Handler nicht, solange ein modaler Dialog offen ist; inaktive (`enabled: false`)
  werden übersprungen; bei gehaltener Taste oder offener Palette wird nichts ausgelöst. Ist nichts registriert,
  passiert nichts (seiteneigene Rückmeldung wie „Nichts zu speichern“ gehört in einen eigenen Handler).
  `hasSaveTarget()` sagt, ob gerade etwas speichern würde.
- `runCommand(id, ctx)` führt einen registrierten Befehl aus (z. B. aus Schnellaktionen).

## Datenblatt-Drop

PDF irgendwo ins Fenster ziehen → Vollbild-Overlay (Funken-Stil, KI-Analyse) → Dateien landen im Store → `/import`.
Das Fenster navigiert **nie** zu abgelegten Dateien oder Links (Desktop-Fenster ohne Zurück-Knopf): erlaubt sind nur
Text-Drops in Eingabefelder und eigene Drop-Zonen (die selbst `preventDefault()` aufrufen). Ziehvorgänge aus der Seite
heraus (Bilder, Zeilen) lösen kein Overlay aus.

```ts
import { useDroppedFiles, useSuppressGlobalDrop } from '@/app/stores'

const files = useDroppedFiles((s) => s.files)      // DroppedFile { id, file: File, name, size, addedAt }
useEffect(() => { if (files.length) startImport(useDroppedFiles.getState().take()) }, [files])   // entnehmen = leeren
useSuppressGlobalDrop()   // Seite mit eigener Drop-Zone (z. B. react-dropzone): Overlay aus, Fensterschutz bleibt
```

## Weitere Helfer

- Theme: `useTheme()` aus `@/app/theme` → `{ theme, resolvedTheme, setTheme }` (`'dark' | 'light' | 'system'`).
  Gespeichert in localStorage **und Cookie** `pf-theme` (Cookies gelten portübergreifend – das Desktop-Programm startet
  jedes Mal auf einem anderen Port) sowie über den ThemeProvider in den App-Einstellungen. Seitenleiste ebenso (`pf-ui`).
  Eigene Vorlieben: `readPref`/`writePref`/`prefsStorage` aus `@/lib/prefs`.
- UI-Zustand: `useUi` (Sidebar, Palette, `setLibraryDialog('create' | 'open', pfad?)`), `useJobDock` (`setOpen`,
  `reveal`, `showLog(id)`, `reserve`). „Neue Bibliothek“ zeigt nach dem Anlegen mit Beispielen eine Erfolgsansicht mit
  dem Fortschritt von „Bibliotheken schreiben“ (Ergebnis bzw. Warnung inline; wird sie vorher geschlossen, meldet das
  Job-Dock den Abschluss; ohne Bibliotheks-Writer steht der volle Grund da und „Bibliotheks-Writer einrichten“ führt zu
  `/einstellungen#altium`). Ein 409 „Die Bibliothek wird gerade geschrieben …“ erscheint in beiden Bibliotheks-Dialogen
  als Hinweis mit „Erneut versuchen“, nicht als Ordnerkonflikt.
  **„Neue Bibliothek anlegen“** schlägt Ordner und **DbLib-Datei** nach dem Namen vor – vom Backend
  (`useWorkspaceDefaults(name)` → `GET /api/workspace/defaults?name=`: `…\Dokumente\PartForge\Name`, ein Ordner, den
  es noch nicht gibt, und ein DbLib-Name, den keine bekannte DbLib verwendet; `dblib_taken` = bekannte DbLib-Dateien).
  Beide Felder folgen dem Namen, bis man sie selbst ändert; ein DbLib-Name, der in Altium installiert ist oder einer
  anderen Bibliothek gehört, zeigt die Warnung „Gleichnamige DbLib“ (Altium unterscheidet Datenbankbibliotheken nur am
  Dateinamen). Gesendet wird `settings.dblib_file`; Hinweise der neuen Bibliothek (`WorkspaceInfo.warnings`) erscheinen
  in der Erfolgsansicht bzw. als Warn-Toast. Ältere Backends ohne den Endpunkt: neben der zuletzt verwendeten
  Bibliothek, sonst leer – nie ein Pfad des Entwicklerrechners. **„Bibliothek öffnen“** verlangt einen Ordner (leer →
  Hinweis, keine Anfrage).
- **Bibliothek wechseln** (Öffnen, Anlegen, Schließen): `confirmLibrarySwitch('switch' | 'create' | 'close')` aus
  `@/app/shell/librarySwitch` fragt, wenn dabei laufende Jobs abgebrochen würden (`jobsCancelledBySwitch()`: schreibende
  Arten `LIBRARY_JOB_KINDS` und der Export) – „Weiterlaufen lassen“ / „Trotzdem wechseln“; `true` = wechseln.
  `switchCancelNote()` (vor dem Wechsel abfragen) liefert den Satz für die Erfolgsmeldung („„Serie …“ wurde
  abgebrochen – Details im Job-Dock.“), damit der Abbruch auch obenauf steht.
- **Navigation außerhalb von Komponenten** (Toast-Aktionen, Stores): `appNavigate('/einstellungen#altium')` bzw.
  `appNavigate(ALTIUM_PATH, { state: altiumActionState('sync') })` aus `@/app/navigation` (über den Router, ohne
  Neuladen; der Router-State steht nicht in der Adresse).
- **Orte in den Einstellungen** (ein Wortlaut für alle Texte, Trenner „›“, wie das Backend in `partforge/altium/texts.py`):
  `SETTINGS_PLACE` aus **`@/lib/settingsPlaces`** – `altium` („Einstellungen › Allgemein › Altium Designer“,
  `/einstellungen#altium`), `writer` („… › Altium Designer › Bibliotheks-Writer“), `ai` („… › KI-Funktionen“, `#ki`),
  `library` („Einstellungen › Bibliothek“, `/einstellungen/bibliothek`), `layers` („Einstellungen › Hausstil › Lagen“,
  `/einstellungen/hausstil?ansicht=lagen`): `` `Pfad unter ${SETTINGS_PLACE.altium.label} eintragen` `` bzw.
  `navigate(SETTINGS_PLACE.altium.to)`; `pages/altium/settingsPlaces.ts` (Altium-Seite) kann daraus re-exportieren.
  Das Programm `altium-designer-mcp.exe` heißt in Texten immer „Bibliotheks-Writer“ (`WRITER`; Dateiname nur in
  Hilfetexten).
- Systemstatus (Ampel Datenbank/Altium/KI): `useSystemStatus()` und `modelDisplayName()` aus `@/app/shell/useSystemStatus`.
  Stufen `ok` grün · `warn` gelb · `error` rot · `off` grau (aus/nicht gestartet) · `unknown` grauer Ring (Abfrage
  fehlgeschlagen) · `pending` (wird geprüft). **Altium** aus `GET /api/altium/status` (`useAltiumStatus`): „läuft“ (grün),
  „Skript hängt“ (Brücke hängt, rot – in Altium Strg+F3), „nicht gestartet“ (grau), „kein Writer“ (gelb: Altium nicht
  gestartet und kein Bibliotheks-Writer – es entstehen keine Bibliotheksdateien; der Klick führt zum Writer-Feld
  `/einstellungen#altium`, nicht zur Altium-Seite, deren „Synchronisieren“ ebenso scheitern würde),
  „nicht gefunden“ (→ `/einstellungen#altium`), „unbekannt“ (Abfrage fehlgeschlagen) – nie grün ohne frische,
  erfolgreiche Antwort. Klickziele: Datenbank → `/einstellungen/bibliothek`, KI → `/einstellungen#ki`. **KI** aus den
  Einstellungen plus letztem Verbindungstest (`useAiConnection`): „aus“, „kein Schlüssel“, „abgelehnt“ (rot, bleibt bis
  zum neuen Schlüssel – auch nach Neustart), „keine Verbindung“, „Modell fehlt“, „Limit erreicht“; sonst das Modell.
  Auch eine an Schlüssel/Modell gescheiterte Datenblatt-Analyse setzt den Status.
- Desktop-Brücke `@/lib/native`: `useNativeBridge()` → `{ canPickFolder, canPickFile, canOpenPath, canSaveFile,
  canRevealPath, canPickSavePath }` (reagiert auf `pywebviewready`), `pickFolder()`, `pickFile(initial, filters)`,
  `openPath()`, `revealPath()`, `isDesktopWindow()`, `nativeApi()`. Nutzt `window.pywebview.api.pick_folder/pick_file/
  save_file/open_path/reveal_path` und – sobald das Backend sie anbietet – `pick_save_path(name, filters) → pfad | None`
  (nur der Speichern-Dialog, schreibt nichts; `partforge/desktop.py`) – „Durchsuchen …“-Buttons in allen `PathInput`s
  erscheinen automatisch.
- **„Im Explorer zeigen“:** `revealPath(pfad, { what?: 'Bibliotheksdatei' })` → `'revealed' | 'copied' | 'failed'`: zeigt die
  Datei **markiert** im Explorer (öffnet sie nie; Ordner werden geöffnet); ältere Desktop-Brücke: Ordner öffnen; außerhalb
  des Desktop-Programms: Pfad in die Zwischenablage + Hinweis-Toast. Fehler (Pfad fehlt) meldet es als Toast. Den Knopf
  daher immer anbieten – nicht mehr nur bei `canOpenPath`. `notifySaveResult` bietet nach dem Speichern „Im Explorer zeigen“.
- **Dateien speichern / Downloads `@/lib/download`** – im Desktop-Fenster funktionieren `<a download>`-Links nicht
  (pywebview verwirft sie). Immer diesen Helfer nehmen:

  ```ts
  import { FILE_TYPES, notifySaveResult, saveBlob, saveFile, saveFileWithFeedback } from '@/lib/download'

  // im Klick-Handler (der Browser-Dialog braucht eine frische Nutzeraktion):
  const result = await saveFile({ suggestedName: 'Widerstände', content: csvText, type: FILE_TYPES.csv })  // → „Widerstände.csv“
  notifySaveResult(result, { what: 'CSV-Datei' })        // Erfolg mit „Ordner öffnen“, „Download gestartet“, Abbruch still

  await saveFile({ suggestedName: `${name}.step`, type: FILE_TYPES.step,       // Inhalt erst laden, wenn nötig
    load: () => api.get<Blob>(`/api/…/step`, { responseType: 'blob' }) })
  await saveBlob(blob, 'Export.xlsx', { type: FILE_TYPES.xlsx })              // Kurzform
  await saveFileWithFeedback({ suggestedName, content, type, what: 'Prüfbericht' })   // inkl. Toasts und Fehler-Toast

  // Große Dateien, die das Backend selbst schreiben kann (Export-Job): erst der Dialog, dann schreibt der Job direkt
  // in die gewählte Datei (kein Base64 durch die Brücke, ein Abbruch kostet nichts); `busy` = Lade-Toast bis zum Ergebnis
  await saveFileWithFeedback({ suggestedName: 'Widerstände.xlsx', type: FILE_TYPES.xlsx, what: 'Excel-Datei',
    busy: 'Excel-Datei wird erstellt …',
    saveTo: async (path) => { /* Export-Job mit Zielpfad starten und auf ihn warten */ },
    load: () => api.get<Blob>(url, { responseType: 'blob' }) })                // Weg ohne `pick_save_path`
  ```

  `saveTo` greift nur mit `pick_save_path` (Desktop-Brücke); sonst gilt der Weg über `content`/`load`.
  Reihenfolge: Desktop-Brücke `save_file` (nativer Windows-Dialog; Text als UTF-8, **Binärdaten exakt** als
  `base64:<…>` – BOM einer CSV, XLSX, PNG bleiben erhalten) → im Desktop-Fenster ohne Brücke der Speichern-Dialog von
  WebView2 (File-System-Access-API; `picker: 'always'` auch im Browser) → im Browser ein Download-Link.
  Ergebnis: `{ status: 'saved', path, via } | { status: 'started', desktop } | { status: 'cancelled' }`; echte Fehler
  werfen einen deutschen `Error`. `safeFileName()` ersetzt unzulässige Zeichen, fehlende Endungen werden ergänzt;
  `FILE_TYPES`: csv, xlsx, step, json, svg, png, pdf, txt, zip.
- Barrierefreiheit der Shell: Sprunglink „Zum Inhalt springen“ (ohne `#main` in der Adresse), Seitenwechsel werden über
  eine Live-Region angesagt, Fokus kehrt nach jedem Overlay zurück.

## Offene Punkte

**Frontend (bewusst Platzhalter):**

- Einstellungen: nur „Allgemein“ ist fertig. „Bibliothek“, „Kategorien und Felder“, „Namensregeln“, „Hausstil“ sind
  Platzhalter in `pages/einstellungen/EinstellungenPage.tsx` (`SECTIONS`, `ready: false`); Speichern der
  Bibliothekseinstellungen: `useSaveWorkspaceSettings()`; Typen `LayerMap`, `FootprintStyle`, `SymbolStyle` stehen bereit.
- Module Bauteile (zeigt bereits die Kategorien mit Zählern), Serien, Import (zeigt abgelegte PDFs), Symbole,
  Footprints, Altium: Platzhalterseiten.
- AG-Grid-Theme, Kategoriebaum, Datei-Drop-Zone, virtualisierte Galerie, teilbare Bereiche, Vorlagen-Eingabe und die
  Vorschau-Leinwände sind fertig – siehe **Geteilte Komponenten**.
- Vorschau-Karten der Verweis-Zellen (`SymbolRefCell`/`FootprintRefCell`) brauchen einen Lader je Seite, bis die
  Bibliotheks-API (`/api/libraries/*`, Welle 2) Symbole/Footprints nach Namen liefert.

**Wünsche an das Backend:**

- `<meta name="partforge-theme" content="…">` neben dem Token einsetzen (index.html liest es bereits) – dann stimmt das
  Theme schon beim allerersten Start; alternativ ein fester Port.
- 409 „keine Bibliothek“ mit `detail: { code: 'no_workspace', message }` (das Frontend versteht beides).
- `POST /api/parts/{table}/render-template` (beliebige Vorlage + Werte → Text) für die exakte Live-Vorschau des
  `TemplateTokenInput` im Schema-Designer (heute rendert `render-templates` nur die gespeicherten Vorlagen).
- Spec eines Bibliothekssymbols/-footprints nach Namen (z. B. `GET /api/libraries/symbols/{name}`) für die
  Hover-Vorschau in Tabellen.

**Umstellungen für Seiten – erledigt** (Stand Review-Runde, im Code geprüft):

- [x] **Jobs inline zeigen** – Serien „Erzeugen“ (`CommitStep`), Import-Analyse (`AnalysisView`), `CommitBar`,
  Tabellen-Import (`ImportWizard`), Datenblattsuche: `trackJob(job, { dock: false, toast: false })` + `useInlineJob`.
  Footprint speichern meldet über Pille und Toast (`trackJob` ohne `dock: false`).
- [x] **Volle Ergebnisse aus Joblisten** – `whenFinished` in `pages/altium/useAltiumActions.ts` lädt gekürzte Ergebnisse
  mit `fetchJob` nach.
- [x] **Strukturierter Fortschritt** – `jobDetail<…>(job)` in Serien, `CommitBar`, Datenblattsuche.
- [x] **„Im Explorer zeigen“** – `revealPath` in `LibraryFilesPanel`, `ExternalPanel`, `DblibPreviewDialog`, `PartForm`,
  Grid-Zellen, Symbol- und Footprint-Dialogen (`openPath` nur noch zum Öffnen einer Datei, nicht zum Zeigen).
- [x] **KI-Verbindungstest** – `classifyAiError` in Einstellungen › KI, Import › KI-Karte und `useImportActions`.
- [x] **Eigene Fehler-Toasts** mit `cleanErrorText(errorMessage(err))`; **Datenblatt-Drop-Zone** `tone="auto"`.
- [x] **Strg+S** – `UnsavedChanges` und Symbole („Nichts zu speichern“) über `useSaveHandler`.
- [x] **Downloads** über `@/lib/download` (Export, Footprints); `PartsGrid` ohne `AllCommunityModule`.
- [x] **Galerie-Karten/Suchtreffer/Drop-Zonen** – `mono: false` für Klartext-Treffer, `typesLabel` zu eigenem `accept`.

**Neu für Seiten (Review-Runde „fix“):**

- Fortschritts- und Ergebnisanzeigen nur für Jobs der geöffneten Bibliothek: `useLibraryJobs(kind)` / `isJobOfLibrary`
  (Altium-Prüfung, Serie, Import) – sobald das Backend `Job.library` liefert.
- Große Exporte im Desktop-Fenster: `saveFileWithFeedback({ saveTo, busy, load })` (Dialog zuerst, Export-Job schreibt
  direkt in den Zielpfad) – braucht `pick_save_path` (Desktop-Brücke) und einen Zielpfad im Export-Job (Backend).
- Erfolgsansichten mit Job-Ergebnis: `jobOutcome(job).problem` (voller Text) und `.action` (Behebung) statt
  `description` (für Toasts gekürzt) – z. B. Serien-Erfolgsbildschirm mit `library_problems`.
- Ortsangaben in Texten über `SETTINGS_PLACE` aus `@/lib/settingsPlaces` (statt eigener Kopien).

**Werkzeuge:** `.npmrc` enthält noch global `legacy-peer-deps` (wegen openapi-typescript ↔ TypeScript 6) – besser ein
`overrides`-Eintrag in package.json. `noUncheckedIndexedAccess` ist nicht aktiv.
`FootprintSpec.step` in `@/lib/geometry` ist aus Verträglichkeit weiter gelockert (`number[]`), obwohl `Filled<T>`
jetzt Tupel erhält. Chunks (alle unter der Warnschwelle von 900 kB): `vendor-grid` ~870 kB + `vendor-ag-stack` +
`vendor-grid-react` (nur Seiten mit Tabellen), `vendor-three` ~740 kB + `vendor-3d` (nur die 3D-Szene) – beide
Gruppen werden **nicht** mehr vom Start-Bundle vorgeladen (vorher zog die 3D-Gruppe React-Abhängigkeiten an sich).
