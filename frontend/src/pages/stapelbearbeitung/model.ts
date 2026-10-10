/**
 * Stapelbearbeitung – Modell ohne Oberfläche: Auswahl und Anfrage an das Backend (`ConformInput`), Kennung einer
 * Prüfung (ändern sich Auswahl, Regeln oder Hausstil, ist der Bericht veraltet), Texte der Regeln mit den Werten des
 * Hausstils, Lagenrollen von Hand, Kennzahlen des Berichts und Meldungen für Job-Dock und Ergebnis.
 *
 * Semantik wie im Backend (`partforge/altium/conform.py`, `housestyle.py`): geprüft werden nur **registrierte**
 * Symbole und Footprints der geöffneten Bibliothek (nie externe), `sources: null` hieße „alle außer extern“,
 * `libraries`/`names: null` = alle. Eine leere Liste ist im Backend dasselbe wie `null` – die Seite schickt daher nie
 * leere Listen, sondern verlangt eine gültige Auswahl ({@link selectionProblem}).
 */
import {
  DEFAULT_RULES,
  RULE_LABELS,
  type ConformApplyResult,
  type ConformInput,
  type ConformLibraryReport,
  type ConformReport,
  type ConformRules,
  type ConformUndoResult,
  type LayerRoleName,
} from '@/api/housestyle'
import { libraryKey } from '@/api/libraries'
import type { WorkspaceSettings } from '@/api/system'
import { SETTINGS_PLACE } from '@/lib/settingsPlaces'
import { baseName, formatDecimal, formatNumber, plural } from '@/lib/format'

// --------------------------------------------------------------------------- Auswahl

export type Kind = 'symbol' | 'footprint'
export type Source = 'imported' | 'generated' | 'datasheet'
export type LibraryFileKind = 'schlib' | 'pcblib'

export const KINDS: readonly Kind[] = ['symbol', 'footprint']
export const SOURCES: readonly Source[] = ['imported', 'generated', 'datasheet']

export const KIND_LABEL: Record<Kind, string> = { symbol: 'Symbole', footprint: 'Footprints' }
/** Herkunft eines registrierten Symbols/Footprints (`RecordSource`) */
export const SOURCE_LABEL: Record<string, string> = {
  imported: 'Importiert',
  generated: 'Erzeugt',
  datasheet: 'Aus Datenblatt',
  external: 'Extern',
}
const SOURCE_ADJECTIVE: Record<Source, string> = {
  imported: 'importierte',
  generated: 'erzeugte',
  datasheet: 'aus Datenblättern übernommene',
}
export const FILE_KIND_OF: Record<Kind, LibraryFileKind> = { symbol: 'schlib', footprint: 'pcblib' }

export interface Selection {
  kinds: Kind[]
  sources: Source[]
  /** Bibliotheksdateien, relativ zum Bibliotheksordner; `null` = alle */
  libraries: string[] | null
  /** einzelne Symbole/Footprints (kommen per Router-State); `null` = alle */
  names: string[] | null
}

export const DEFAULT_SELECTION: Selection = {
  kinds: ['symbol', 'footprint'],
  sources: ['imported'],
  libraries: null,
  names: null,
}

/** Art einer Bibliotheksdatei nach ihrer Endung (`null` = weder SchLib noch PcbLib) */
export function libraryFileKind(path: string): LibraryFileKind | null {
  if (/\.schlib$/i.test(path)) return 'schlib'
  if (/\.pcblib$/i.test(path)) return 'pcblib'
  return null
}

/** Datei- und Ordnerteil eines relativen Pfads („Footprints\PF_CHIP.PcbLib“ → „Footprints\“ + „PF_CHIP.PcbLib“) */
export function splitPath(rel: string): { folder: string; name: string } {
  const i = Math.max(rel.lastIndexOf('\\'), rel.lastIndexOf('/'))
  return i < 0 ? { folder: '', name: rel } : { folder: rel.slice(0, i + 1), name: rel.slice(i + 1) }
}

const byPath = (a: string, b: string) => a.localeCompare(b, 'de', { numeric: true, sensitivity: 'base' })

/**
 * Bibliotheken, die tatsächlich geprüft werden: die gewählten, deren Art zu Symbolen/Footprints der Auswahl passt
 * (je Datei einmal, sortiert). `null` = alle Bibliotheken.
 */
export function effectiveLibraries(selection: Pick<Selection, 'kinds' | 'libraries'>): string[] | null {
  if (!selection.libraries) return null
  const kinds = new Set(selection.kinds.map((k) => FILE_KIND_OF[k]))
  const seen = new Set<string>()
  const out: string[] = []
  for (const lib of selection.libraries) {
    const kind = libraryFileKind(lib)
    const key = libraryKey(lib)
    if (!kind || !kinds.has(kind) || seen.has(key)) continue
    seen.add(key)
    out.push(lib)
  }
  return out.sort(byPath)
}

// --------------------------------------------------------------------------- Regeln

const PREFIX = /^[A-Z]{1,8}$/

/** Präfix-Eingabe: nur Buchstaben, groß, höchstens 8 (wie `conform.parse_prefix_map`) */
export function cleanPrefix(text: string): string {
  return text
    .toUpperCase()
    .replace(/[^A-Z]/g, '')
    .slice(0, 8)
}

/** Gültige Einträge „alt → neu“ (Buchstaben, groß, alt ≠ neu) */
export function cleanPrefixMap(map: Record<string, string> | null | undefined): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [from, to] of Object.entries(map ?? {})) {
    const a = from.trim().toUpperCase()
    const b = to.trim().toUpperCase()
    if (PREFIX.test(a) && PREFIX.test(b) && a !== b) out[a] = b
  }
  return out
}

type RoleMap = ConformRules['footprints']['roles']

/** Lagenrollen ohne leere Einträge */
function cleanRoles(roles: RoleMap | null | undefined): RoleMap {
  const out: RoleMap = {}
  for (const [library, map] of Object.entries(roles ?? {})) {
    if (map && Object.keys(map).length) out[library] = { ...map }
  }
  return out
}

/** Regeln vollständig machen (fehlende Felder älterer Stände → Standard) */
export function normalizeRules(raw: ConformRules | null | undefined): ConformRules {
  if (!raw) return DEFAULT_RULES
  return {
    symbols: {
      ...DEFAULT_RULES.symbols,
      ...raw.symbols,
      prefix_map: { ...(raw.symbols?.prefix_map ?? DEFAULT_RULES.symbols.prefix_map) },
    },
    footprints: { ...DEFAULT_RULES.footprints, ...raw.footprints, roles: cleanRoles(raw.footprints?.roles) },
  }
}

/** Schalter und Präfixe wie die Standardregeln? (Lagenrollen zählen nicht – sie gehören zu einzelnen Bibliotheken) */
export function isDefaultRules(rules: ConformRules): boolean {
  const strip = (r: ConformRules) => ({
    symbols: { ...r.symbols, prefix_map: cleanPrefixMap(r.symbols.prefix_map) },
    footprints: { ...r.footprints, roles: {} },
  })
  return stableStringify(strip(rules)) === stableStringify(strip(DEFAULT_RULES))
}

/** Standardregeln – eigene Lagenrollen bleiben erhalten (sie beschreiben einzelne Bibliotheken, keine Regel) */
export function defaultRulesKeepingRoles(rules: ConformRules): ConformRules {
  return {
    symbols: { ...DEFAULT_RULES.symbols, prefix_map: { ...DEFAULT_RULES.symbols.prefix_map } },
    footprints: { ...DEFAULT_RULES.footprints, roles: cleanRoles(rules.footprints.roles) },
  }
}

/** Eingeschaltete Regeln, die bei `kind` etwas ändern können */
export function activeRules(rules: ConformRules, kind: Kind): string[] {
  const list: (string | false)[] =
    kind === 'symbol'
      ? [
          rules.symbols.fonts && 'fonts',
          rules.symbols.pin_length && 'pin_length',
          rules.symbols.prefix && Object.keys(cleanPrefixMap(rules.symbols.prefix_map)).length > 0 && 'prefix',
          rules.symbols.colors && 'colors',
        ]
      : [
          rules.footprints.layers && 'layers',
          rules.footprints.widths && 'widths',
          rules.footprints.texts && 'texts',
          rules.footprints.add_texts && 'add_texts',
          rules.footprints.add_center && 'add_center',
          rules.footprints.header && 'header',
        ]
  return list.filter((x): x is string => Boolean(x))
}

// --------------------------------------------------------------------------- Anfrage und Kennung

/** Anfrage an `POST /api/housestyle/check|apply` – normalisiert (Reihenfolgen fest, keine leeren Einträge) */
export function buildInput(selection: Selection, rules: ConformRules): ConformInput {
  const names = selection.names?.length ? [...new Set(selection.names)].sort(byPath) : null
  return {
    selection: {
      kinds: KINDS.filter((k) => selection.kinds.includes(k)),
      sources: SOURCES.filter((s) => selection.sources.includes(s)),
      libraries: effectiveLibraries(selection),
      names,
    },
    rules: {
      symbols: { ...rules.symbols, prefix_map: cleanPrefixMap(rules.symbols.prefix_map) },
      footprints: { ...rules.footprints, roles: cleanRoles(rules.footprints.roles) },
    },
  }
}

/** JSON mit sortierten Objektschlüsseln – gleiche Inhalte ergeben denselben Text */
export function stableStringify(value: unknown): string {
  return JSON.stringify(value, (_key, v: unknown) => {
    if (v && typeof v === 'object' && !Array.isArray(v)) {
      const rec = v as Record<string, unknown>
      return Object.fromEntries(
        Object.keys(rec)
          .sort()
          .map((k) => [k, rec[k]]),
      )
    }
    return v
  })
}

/** Vergleichstext der Regeln (gleiche Wirkung = gleicher Text) */
export function rulesKey(rules: ConformRules): string {
  return stableStringify(buildInput(DEFAULT_SELECTION, rules).rules)
}

/** Was vom Hausstil der Bibliothek in die Prüfung eingeht */
export type StyleInfo = Pick<WorkspaceSettings, 'symbol' | 'footprint' | 'layers' | 'layer_stackup'>

/** Kennung einer Prüfung: Anfrage + Hausstil. Weicht sie von der aktuellen ab, ist der Bericht veraltet. */
export function checkKey(input: ConformInput, style: StyleInfo | null): string {
  return stableStringify({
    input,
    style: style
      ? { symbol: style.symbol, footprint: style.footprint, layers: style.layers, stackup: style.layer_stackup ?? null }
      : null,
  })
}

/** Warum gerade nicht geprüft werden kann (`null` = Auswahl und Regeln sind brauchbar) */
export function selectionProblem(selection: Selection, rules: ConformRules): string | null {
  if (!selection.kinds.length) return 'Bitte Symbole, Footprints oder beides wählen.'
  if (!selection.sources.length) return 'Bitte mindestens eine Herkunft wählen.'
  const libs = effectiveLibraries(selection)
  if (libs && !libs.length) {
    if (selection.kinds.length === 1) {
      return selection.kinds[0] === 'symbol'
        ? 'Keine der gewählten Bibliotheken ist eine Symbolbibliothek (SchLib).'
        : 'Keine der gewählten Bibliotheken ist eine Footprint-Bibliothek (PcbLib).'
    }
    return 'Keine der gewählten Bibliotheken ist eine SchLib oder PcbLib.'
  }
  const active = selection.kinds.reduce((n, k) => n + activeRules(rules, k).length, 0)
  if (!active) return 'Alle Regeln der Auswahl sind ausgeschaltet – bitte mindestens eine einschalten.'
  return null
}

/** „a“, „a und b“, „a, b und c“ */
export function joinDe(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  return `${items.slice(0, -1).join(', ')} und ${items[items.length - 1]}`
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** Auswahl in Worten: „Importierte Symbole und Footprints aus allen Bibliotheken · 3 einzelne Bauteile“ */
export function describeSelection(selection: ConformInput['selection']): string {
  const libs = selection?.libraries ?? null
  // gewählte Bibliotheken bestimmen, was tatsächlich geprüft wird (nur SchLibs → nur Symbole)
  const kinds = (selection?.kinds ?? KINDS).filter(
    (k) => !libs?.length || libs.some((l) => libraryFileKind(l) === FILE_KIND_OF[k]),
  )
  const what = kinds.length === 1 ? KIND_LABEL[kinds[0]] : 'Symbole und Footprints'
  const sources = SOURCES.filter((s) => !selection?.sources || selection.sources.includes(s))
  const adjective = sources.length === SOURCES.length ? 'alle' : joinDe(sources.map((s) => SOURCE_ADJECTIVE[s]))
  const where =
    libs === null
      ? 'aus allen Bibliotheken'
      : libs.length === 1
        ? `aus ${baseName(libs[0])}`
        : `aus ${plural(libs.length, 'Bibliothek', 'Bibliotheken')}`
  const names = selection?.names?.length
    ? ` · ${plural(selection.names.length, 'einzelnes Bauteil', 'einzelne Bauteile')}`
    : ''
  return `${capitalize(`${adjective} ${what}`)} ${where}${names}`
}

// --------------------------------------------------------------------------- Texte der Regeln

export type SymbolFlag = 'fonts' | 'pin_length' | 'prefix' | 'colors'
export type FootprintFlag = 'layers' | 'widths' | 'silk_width' | 'texts' | 'add_texts' | 'add_center' | 'header'

export interface RuleDef<K extends string> {
  key: K
  label: string
  /** Kurze Hilfe – mit den Werten des Hausstils, sobald er geladen ist */
  help: (style: StyleInfo | null) => string
  /** wirkt nur zusammen mit dieser Regel (eingerückt, sonst gesperrt) */
  parent?: K
}

/** geschütztes Leerzeichen zwischen Zahl und Einheit (kein Umbruch „0,1 | mm“) */
const NBSP = '\u00a0'
const mm = (value: number) => `${formatDecimal(value, 3)}${NBSP}mm`

export const SYMBOL_RULES: RuleDef<SymbolFlag>[] = [
  {
    key: 'fonts',
    label: RULE_LABELS.fonts,
    help: (s) =>
      s
        ? `Bezeichner, Kommentar und Parameter in ${s.symbol.font}${NBSP}${formatDecimal(s.symbol.font_size)}, Pins in der ${s.symbol.pin_font === 'system' ? 'Systemschrift' : 'Hausschrift'}`
        : 'Hausschrift für Bezeichner, Kommentar, Parameter und Pins',
  },
  {
    key: 'pin_length',
    label: RULE_LABELS.pin_length,
    help: (s) =>
      s
        ? `Pins von IC- und Box-Symbolen auf ${formatNumber(s.symbol.ic_pin_length)}${NBSP}mil – das Ende am Körper bleibt`
        : 'Pinlänge von IC- und Box-Symbolen wie im Hausstil',
  },
  {
    key: 'prefix',
    label: RULE_LABELS.prefix,
    help: () => 'Bezeichner-Präfixe nach der Tabelle ersetzen, z. B. IC → U',
  },
  {
    key: 'colors',
    label: RULE_LABELS.colors,
    help: () => 'Rahmen, Füllung und Pinfarbe von IC- und Box-Symbolen wie im Hausstil',
  },
]

export const FOOTPRINT_RULES: RuleDef<FootprintFlag>[] = [
  {
    key: 'layers',
    label: RULE_LABELS.layers,
    help: (s) =>
      s
        ? `Primitive nach ihrer Rolle auf die Lagen der Lagenzuordnung – z. B. Bestückungszeichnung auf ${s.layers.assembly}, Courtyard auf ${s.layers.courtyard}`
        : 'Primitive nach ihrer Rolle auf die Lagen der Lagenzuordnung',
  },
  {
    key: 'widths',
    label: RULE_LABELS.widths,
    help: (s) =>
      s
        ? `Bestückungszeichnung und Umriss ${mm(s.footprint.assembly_width)}, Courtyard ${mm(s.footprint.courtyard_width)}, Mittelkreuz ${mm(0.1)}`
        : 'Linienbreiten je Rolle (Bestückung, Courtyard, Mitte, Umriss)',
  },
  {
    key: 'silk_width',
    label: 'Auch Bestückungsdruck',
    parent: 'widths',
    help: (s) =>
      s
        ? `Auch den Bestückungsdruck auf ${mm(s.footprint.silk_width)} setzen`
        : 'Auch den Bestückungsdruck auf die Hausstil-Breite setzen',
  },
  {
    key: 'texts',
    label: RULE_LABELS.texts,
    help: (s) =>
      s
        ? `.Designator und .Comment in ${s.footprint.text_font === 'truetype' ? s.footprint.text_font_name || 'Arial' : 'Strichschrift'}, ${mm(s.footprint.text_height)} hoch (kleiner bei winzigen Bauteilen)`
        : '.Designator und .Comment in Schrift und Höhe des Hausstils',
  },
  {
    key: 'add_texts',
    label: RULE_LABELS.add_texts,
    help: () => 'Fehlende .Designator und .Comment in der Bauteilmitte ergänzen',
  },
  {
    key: 'add_center',
    label: RULE_LABELS.add_center,
    help: (s) =>
      s
        ? `Fehlendes Kreuz der Bauteilmitte auf ${s.layers.component_center} ergänzen`
        : 'Fehlendes Kreuz der Bauteilmitte ergänzen',
  },
  {
    key: 'header',
    label: RULE_LABELS.header,
    help: () => 'Lagenaufbau und Lagensatz im Kopf der PcbLib wie im Hausstil',
  },
]

/** Filter „Probleme“ neben den Regeln in der Zusammenfassung des Berichts */
export const PROBLEMS_FILTER = '__problems'

/** Bezeichnung einer Regel (auch unbekannter Kennungen) */
export const ruleLabel = (rule: string) => RULE_LABELS[rule] ?? rule

/** Orte des Hausstils in den Einstellungen */
export const STYLE_PLACES = {
  footprints: { label: 'Footprints', to: '/einstellungen/hausstil' },
  layers: { label: 'Lagen', to: SETTINGS_PLACE.layers.to },
  symbols: { label: 'Symbole', to: '/einstellungen/hausstil?ansicht=symbole' },
} as const

// --------------------------------------------------------------------------- Lagenrollen

/** Reihenfolge in der Auswahl der Rolle */
export const ROLE_ORDER: readonly LayerRoleName[] = [
  'assembly',
  'courtyard',
  'component_outline',
  'component_center',
  'designator',
  'comment',
  'body3d',
  'silkscreen',
  'keep',
]

/** Wohin die Primitive einer Rolle wandern (Lagenzuordnung des Hausstils) – bzw. dass sie bleiben */
export function roleTarget(role: LayerRoleName, layers: StyleInfo['layers'] | null | undefined): string {
  if (role === 'keep') return 'bleiben auf ihrer Lage'
  if (role === 'silkscreen') return 'bleiben auf ihrer Lage – Linienbreite wie Bestückungsdruck'
  return layers ? `→ ${layers[role]}` : '→ Lage laut Lagenzuordnung'
}

/** Eigene Rollen einer Bibliothek (Schreibweise des Pfads egal) */
export function manualRolesFor(rules: ConformRules, library: string): Record<string, LayerRoleName> {
  const key = libraryKey(library)
  const out: Record<string, LayerRoleName> = {}
  for (const [lib, map] of Object.entries(rules.footprints.roles)) {
    if (libraryKey(lib) === key) Object.assign(out, map)
  }
  return out
}

/** Rolle einer Quell-Lage von Hand setzen (`null` = wieder automatisch) – unter dem Pfad aus dem Bericht */
export function withManualRole(
  rules: ConformRules,
  library: string,
  layer: string,
  role: LayerRoleName | null,
): ConformRules {
  const key = libraryKey(library)
  const roles: RoleMap = {}
  const current: Record<string, LayerRoleName> = {}
  for (const [lib, map] of Object.entries(rules.footprints.roles)) {
    if (libraryKey(lib) === key) Object.assign(current, map)
    else roles[lib] = map
  }
  if (role === null) delete current[layer]
  else current[layer] = role
  if (Object.keys(current).length) roles[library] = current
  return { ...rules, footprints: { ...rules.footprints, roles } }
}

/** Quell-Lagen ohne erkannte Rolle (bleiben unverändert) mit Primitiven darauf */
export function undeterminedLayers(lib: ConformLibraryReport): number {
  return lib.roles.filter((r) => r.reason === 'default' && r.primitives > 0).length
}

// --------------------------------------------------------------------------- Bericht

export interface ReportStats {
  checked: number
  affected: number
  /** Bibliotheken, deren Lagen-Kopf abweicht */
  headerLibraries: number
  /** Bauteile mit Problemen (nicht lesbar) */
  problemComponents: number
  unreadable: number
  /** Bibliotheken, die „Anwenden“ überspringen würde */
  refused: number
  /** Bibliotheken bzw. Bauteile, die „Anwenden“ schreiben würde */
  writeLibraries: number
  writeComponents: number
  /** Es gibt etwas anzugleichen (Bauteile oder Lagen-Köpfe) */
  pending: boolean
}

export function reportStats(report: ConformReport): ReportStats {
  let headerLibraries = 0
  let unreadable = 0
  let refused = 0
  let writeLibraries = 0
  let writeComponents = 0
  for (const lib of report.libraries) {
    if (lib.problem) {
      unreadable += 1
      continue
    }
    if (lib.header.length) headerLibraries += 1
    if (lib.refusal) {
      refused += 1
      continue
    }
    if (lib.affected > 0 || lib.header.length > 0) {
      writeLibraries += 1
      writeComponents += lib.affected
    }
  }
  return {
    checked: report.checked,
    affected: report.affected,
    headerLibraries,
    problemComponents: report.components.filter((c) => c.problems.length > 0).length,
    unreadable,
    refused,
    writeLibraries,
    writeComponents,
    pending: report.affected > 0 || headerLibraries > 0,
  }
}

/** Dezimalpunkte in Meldungen des Backends („0.05 mm“) deutsch schreiben („0,05 mm“) */
export function localizeDecimals(text: string): string {
  return text.replace(/(\d)\.(\d)/g, '$1,$2')
}

const firstEntry = (list: { library: string; message: string }[]) =>
  list.length ? `${baseName(list[0].library)}: ${list[0].message}` : ''

/** Problem im Ergebnis von „Anwenden“ (Warnung im Job-Dock) */
export function applyProblem(result: ConformApplyResult | null | undefined): string | null {
  if (!result) return null
  const parts: string[] = []
  if (result.errors?.length)
    parts.push(`${plural(result.errors.length, 'Fehler', 'Fehler')} – ${firstEntry(result.errors)}`)
  if (result.skipped?.length) {
    parts.push(
      `${plural(result.skipped.length, 'Bibliothek', 'Bibliotheken')} übersprungen – ${firstEntry(result.skipped)}`,
    )
  }
  return parts.length ? parts.join(' · ') : null
}

/** Problem im Ergebnis von „Rückgängig machen“ */
export function undoProblem(result: ConformUndoResult | null | undefined): string | null {
  if (!result?.skipped?.length) return null
  return `${plural(result.skipped.length, 'Bibliothek', 'Bibliotheken')} nicht zurückgesetzt – ${firstEntry(result.skipped)}`
}

// --------------------------------------------------------------------------- Router-State

/** Was eine andere Seite (Bibliotheksimport) per Router-State vorgibt */
export interface IncomingSelection {
  libraries: string[] | null
  names: string[] | null
}

/** `location.state` → Vorgabe der Auswahl (nur Listen von Texten; sonst `null`) */
export function incomingFromState(state: unknown): IncomingSelection | null {
  if (!state || typeof state !== 'object') return null
  const rec = state as { libraries?: unknown; names?: unknown }
  const strings = (value: unknown) =>
    Array.isArray(value)
      ? value.filter((x): x is string => typeof x === 'string' && x.trim() !== '').map((x) => x.trim())
      : []
  const libraries = strings(rec.libraries)
  const names = strings(rec.names)
  if (!libraries.length && !names.length) return null
  return { libraries: libraries.length ? libraries : null, names: names.length ? names : null }
}
