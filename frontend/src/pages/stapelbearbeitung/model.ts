import { t as tr, tc, localizeMessage, getLocale } from '@/lib/i18n'
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

export const KIND_LABEL: Record<Kind, string> = { get symbol() { return tr("Symbole") }, footprint: 'Footprints' }
/** Herkunft eines registrierten Symbols/Footprints (`RecordSource`) */
export const SOURCE_LABEL: Record<string, string> = {
  get imported() { return tr("Importiert") },
  get generated() { return tr("Erzeugt") },
  get datasheet() { return tr("Aus Datenblatt") },
  get external() { return tr("Extern") },
}
const SOURCE_ADJECTIVE: Record<Source, string> = {
  get imported() { return tr("importierte") },
  get generated() { return tr("erzeugte") },
  get datasheet() { return tr("aus Datenblättern übernommene") },
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

const byPath = (a: string, b: string) => a.localeCompare(b, 'en', { numeric: true, sensitivity: 'base' })

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
  if (!selection.kinds.length) return tr("Bitte Symbole, Footprints oder beides wählen.")
  if (!selection.sources.length) return tr("Bitte mindestens eine Herkunft wählen.")
  const libs = effectiveLibraries(selection)
  if (libs && !libs.length) {
    if (selection.kinds.length === 1) {
      return selection.kinds[0] === 'symbol'
        ? tr("Keine der gewählten Bibliotheken ist eine Symbolbibliothek (SchLib).")
        : tr("Keine der gewählten Bibliotheken ist eine Footprint-Bibliothek (PcbLib).")
    }
    return tr("Keine der gewählten Bibliotheken ist eine SchLib oder PcbLib.")
  }
  const active = selection.kinds.reduce((n, k) => n + activeRules(rules, k).length, 0)
  if (!active) return tr("Alle Regeln der Auswahl sind ausgeschaltet – bitte mindestens eine einschalten.")
  return null
}

/** „a“, „a und b“, „a, b und c“ */
export function joinDe(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  return tr("{0} und {1}", { "0": String(items.slice(0, -1).join(', ')), "1": String(items[items.length - 1]) })
}

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

/** Auswahl in Worten: „Importierte Symbole und Footprints aus allen Bibliotheken · 3 einzelne Bauteile“ */
export function describeSelection(selection: ConformInput['selection']): string {
  const libs = selection?.libraries ?? null
  // gewählte Bibliotheken bestimmen, was tatsächlich geprüft wird (nur SchLibs → nur Symbole)
  const kinds = (selection?.kinds ?? KINDS).filter(
    (k) => !libs?.length || libs.some((l) => libraryFileKind(l) === FILE_KIND_OF[k]),
  )
  const what = kinds.length === 1 ? KIND_LABEL[kinds[0]] : tr("Symbole und Footprints")
  const sources = SOURCES.filter((s) => !selection?.sources || selection.sources.includes(s))
  const adjective = sources.length === SOURCES.length ? tr("alle") : joinDe(sources.map((s) => SOURCE_ADJECTIVE[s]))
  const where =
    libs === null
      ? tr("aus allen Bibliotheken")
      : libs.length === 1
        ? tr("aus {0}", { "0": String(baseName(libs[0])) })
        : tr("aus {0}", { "0": String(plural(libs.length, tr("Bibliothek"), tr("Bibliotheken"))) })
  const names = selection?.names?.length
    ? ` · ${plural(selection.names.length, tr("einzelnes Bauteil"), tr("einzelne Bauteile"))}`
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
    get label() { return RULE_LABELS.fonts },
    help: (s) =>
      s
        ? tr("Bezeichner, Kommentar und Parameter in {0}{1}{2}, Pins in der {3}", { "0": String(s.symbol.font), "1": String(NBSP), "2": String(formatDecimal(s.symbol.font_size)), "3": String(s.symbol.pin_font === 'system' ? tc('inline', 'Systemschrift') : tc('inline', 'Hausschrift')) })
        : tr("Hausschrift für Bezeichner, Kommentar, Parameter und Pins"),
  },
  {
    key: 'pin_length',
    get label() { return RULE_LABELS.pin_length },
    help: (s) =>
      s
        ? tr("Pins von IC- und Box-Symbolen auf {0}{1}mil – das Ende am Körper bleibt", { "0": String(formatNumber(s.symbol.ic_pin_length)), "1": String(NBSP) })
        : tr("Pinlänge von IC- und Box-Symbolen wie im Hausstil"),
  },
  {
    key: 'prefix',
    get label() { return RULE_LABELS.prefix },
    help: () => tr("Bezeichner-Präfixe nach der Tabelle ersetzen, z. B. IC → U"),
  },
  {
    key: 'colors',
    get label() { return RULE_LABELS.colors },
    help: () => tr("Rahmen, Füllung und Pinfarbe von IC- und Box-Symbolen wie im Hausstil"),
  },
]

export const FOOTPRINT_RULES: RuleDef<FootprintFlag>[] = [
  {
    key: 'layers',
    get label() { return RULE_LABELS.layers },
    help: (s) =>
      s
        ? tr("Primitive nach ihrer Rolle auf die Lagen der Lagenzuordnung – z. B. Bestückungszeichnung auf {0}, Courtyard auf {1}", { "0": String(s.layers.assembly), "1": String(s.layers.courtyard) })
        : tr("Primitive nach ihrer Rolle auf die Lagen der Lagenzuordnung"),
  },
  {
    key: 'widths',
    get label() { return RULE_LABELS.widths },
    help: (s) =>
      s
        ? tr("Bestückungszeichnung und Umriss {0}, Courtyard {1}, Mittelkreuz {2}", { "0": String(mm(s.footprint.assembly_width)), "1": String(mm(s.footprint.courtyard_width)), "2": String(mm(0.1)) })
        : tr("Linienbreiten je Rolle (Bestückung, Courtyard, Mitte, Umriss)"),
  },
  {
    key: 'silk_width',
    get label() { return tr("Auch Bestückungsdruck") },
    parent: 'widths',
    help: (s) =>
      s
        ? tr("Auch den Bestückungsdruck auf {0} setzen", { "0": String(mm(s.footprint.silk_width)) })
        : tr("Auch den Bestückungsdruck auf die Hausstil-Breite setzen"),
  },
  {
    key: 'texts',
    get label() { return RULE_LABELS.texts },
    help: (s) =>
      s
        ? tr(".Designator und .Comment in {0}, {1} hoch (kleiner bei winzigen Bauteilen)", { "0": String(s.footprint.text_font === 'truetype' ? s.footprint.text_font_name || 'Arial' : tc('inline', 'Strichschrift')), "1": String(mm(s.footprint.text_height)) })
        : tr(".Designator und .Comment in Schrift und Höhe des Hausstils"),
  },
  {
    key: 'add_texts',
    get label() { return RULE_LABELS.add_texts },
    help: () => tr("Fehlende .Designator und .Comment in der Bauteilmitte ergänzen"),
  },
  {
    key: 'add_center',
    get label() { return RULE_LABELS.add_center },
    help: (s) =>
      s
        ? tr("Fehlendes Kreuz der Bauteilmitte auf {0} ergänzen", { "0": String(s.layers.component_center) })
        : tr("Fehlendes Kreuz der Bauteilmitte ergänzen"),
  },
  {
    key: 'header',
    get label() { return RULE_LABELS.header },
    help: () => tr("Lagenaufbau und Lagensatz im Kopf der PcbLib wie im Hausstil"),
  },
]

/** Filter „Probleme“ neben den Regeln in der Zusammenfassung des Berichts */
export const PROBLEMS_FILTER = '__problems'

/** Bezeichnung einer Regel (auch unbekannter Kennungen) */
export const ruleLabel = (rule: string) => RULE_LABELS[rule] ?? rule

/** Orte des Hausstils in den Einstellungen */
export const STYLE_PLACES = {
  footprints: { label: 'Footprints', to: '/einstellungen/hausstil' },
  layers: { get label() { return tr("Lagen") }, to: SETTINGS_PLACE.layers.to },
  symbols: { get label() { return tr("Symbole") }, to: '/einstellungen/hausstil?ansicht=symbole' },
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
  if (role === 'keep') return tr("bleiben auf ihrer Lage")
  if (role === 'silkscreen') return tr("bleiben auf ihrer Lage – Linienbreite wie Bestückungsdruck")
  return layers ? `→ ${layers[role]}` : tr("→ Lage laut Lagenzuordnung")
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
  /** Bauteile mit Problemen (nicht lesbar bzw. nicht angepasst) */
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
  const message = localizeMessage(text)
  return getLocale() === 'de-DE' ? message.replace(/(\d)\.(\d)(?=\d*\s*(?:mm|mil|pt|%))/g, '$1,$2') : message
}

const firstEntry = (list: { library: string; message: string }[]) =>
  list.length ? `${baseName(list[0].library)}: ${localizeMessage(list[0].message)}` : ''

/** Problem im Ergebnis von „Anwenden“ (Warnung im Job-Dock) */
export function applyProblem(result: ConformApplyResult | null | undefined): string | null {
  if (!result) return null
  const parts: string[] = []
  if (result.errors?.length)
    parts.push(`${plural(result.errors.length, tr("Fehler"), tr("Fehler"))} – ${firstEntry(result.errors)}`)
  if (result.skipped?.length) {
    parts.push(
      tr("{0} übersprungen – {1}", { "0": String(plural(result.skipped.length, tr("Bibliothek"), tr("Bibliotheken"))), "1": String(firstEntry(result.skipped)) }),
    )
  }
  return parts.length ? parts.join(' · ') : null
}

/** Problem im Ergebnis von „Rückgängig machen“ */
export function undoProblem(result: ConformUndoResult | null | undefined): string | null {
  if (!result?.skipped?.length) return null
  return tr("{0} nicht zurückgesetzt – {1}", { "0": String(plural(result.skipped.length, tr("Bibliothek"), tr("Bibliotheken"))), "1": String(firstEntry(result.skipped)) })
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
