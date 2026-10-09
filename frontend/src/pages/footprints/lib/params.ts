/**
 * Parameter des Footprint-Generators im Formular: Werte lesen (Vorlagen, gespeicherte Generator-Parameter),
 * Toleranzen klug parsen („0,25±0,05“, „0,20…0,30“, „0,20 0,25 0,30“), für die Anfrage serialisieren,
 * vergleichen und deutsch formatieren. Gleiche Regeln wie `partforge/footprints/params.py`.
 */
import type { FootprintParamSpec } from '@/api/footprints'

// --------------------------------------------------------------------------- Typen

/** Toleriertes Maß (mm); `null` = nicht angegeben (Nennwert leer = Mitte aus Min/Max) */
export interface TolValue {
  min: number | null
  nom: number | null
  max: number | null
}

export type ParamValue = TolValue | number | boolean | string | null
export type ParamValues = Record<string, ParamValue>

export const EMPTY_TOL: TolValue = { min: null, nom: null, max: null }

export function isTolValue(value: unknown): value is TolValue {
  return Boolean(value) && typeof value === 'object' && 'min' in (value as object) && 'max' in (value as object)
}

export const isEmptyTol = (t: TolValue): boolean => t.min === null && t.nom === null && t.max === null

// --------------------------------------------------------------------------- Zahlen

const NUM = String.raw`[+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)`

/** „0,25“, „0.25“, „1,“ (beim Tippen) → Zahl; Einheit „mm“ wird ignoriert. Ungültig → null. */
export function parseNumber(text: string): number | null {
  const t = text
    .trim()
    .replace(/\s*mm$/i, '')
    .replace(/[−–]/g, '-')
    .replace(/\s+/g, '')
  if (!t) return null
  if (!new RegExp(`^-?${NUM}$`).test(t)) return null
  const n = Number(t.replace(',', '.').replace(/[.]$/, ''))
  return Number.isFinite(n) ? n : null
}

const fmtCache = new Map<string, Intl.NumberFormat>()
function fmt(min: number, max: number): Intl.NumberFormat {
  const key = `${min}-${max}`
  let f = fmtCache.get(key)
  if (!f) {
    f = new Intl.NumberFormat('de-DE', { minimumFractionDigits: min, maximumFractionDigits: max, useGrouping: false })
    fmtCache.set(key, f)
  }
  return f
}

/** Maß für Tabellen: mindestens 2, höchstens 3 Nachkommastellen („0,40“, „0,835“, „12,70“). */
export function formatDim(value: number | null | undefined, maxDigits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ''
  const v = Math.abs(value) < 5e-7 ? 0 : value
  return fmt(2, Math.max(2, maxDigits)).format(v).replace('-', '−')
}

/** Kompakt (ohne überflüssige Nullen): 0.5 → „0,5“, 8 → „8“ */
export function formatPlain(value: number | null | undefined, maxDigits = 3): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ''
  return fmt(0, maxDigits).format(value).replace('-', '−')
}

// --------------------------------------------------------------------------- Toleranzen klug parsen

export type TolParse =
  | { kind: 'empty' }
  | { kind: 'single'; value: number }
  | { kind: 'tol'; tol: TolValue; label: string }
  | { kind: 'invalid' }

const n = (s: string) => Number(s.replace(',', '.').replace(/[.]$/, ''))

const PM_RE = new RegExp(`^(${NUM})\\s*(?:±|\\+\\s*/\\s*-|\\+-)\\s*(${NUM})$`)
const ASYM_RE = new RegExp(`^(${NUM})\\s*\\+\\s*(${NUM})\\s*/?\\s*-\\s*(${NUM})$`)
const RANGE_RE = new RegExp(`^(${NUM})\\s*(?:\\.\\.\\.?|…|~|bis|to|–|—|-)\\s*(${NUM})$`, 'i')
const LIMIT_RE = new RegExp(`^(max\\.?|min\\.?|typ\\.?|nom\\.?|≤|<=|<|≥|>=|>)\\s*(${NUM})$`, 'i')

/**
 * Freitext eines Toleranzfelds lesen. Erkennt:
 * „0,25±0,05“ · „1,0 +0,1/−0,05“ · „0,20…0,30“ / „0,2-0,3“ / „0,2 bis 0,3“ · „0,20 0,25 0,30“ (Min Nom Max) ·
 * „0,20 / 0,30“ (Min Max) · „max 1,75“ / „≤1,75“ · „min 0,1“ · „typ 0,5“ · einzelne Zahl.
 */
export function parseTolText(raw: string): TolParse {
  const text = raw
    .trim()
    .replace(/mm\b/gi, '')
    .replace(/[−]/g, '-')
    .replace(/,\s+/g, ' ')
    .trim()
  if (!text) return { kind: 'empty' }
  let m = PM_RE.exec(text)
  if (m) {
    const c = n(m[1])
    const d = Math.abs(n(m[2]))
    return { kind: 'tol', tol: { min: round6(c - d), nom: c, max: round6(c + d) }, label: 'Nennwert ± Toleranz' }
  }
  m = ASYM_RE.exec(text)
  if (m) {
    const c = n(m[1])
    return {
      kind: 'tol',
      tol: { min: round6(c - Math.abs(n(m[3]))), nom: c, max: round6(c + Math.abs(n(m[2]))) },
      label: 'Nennwert mit Abmaßen',
    }
  }
  m = RANGE_RE.exec(text)
  if (m) {
    const a = n(m[1])
    const b = n(m[2])
    return { kind: 'tol', tol: { min: Math.min(a, b), nom: null, max: Math.max(a, b) }, label: 'Bereich Min…Max' }
  }
  m = LIMIT_RE.exec(text)
  if (m) {
    const v = n(m[2])
    const word = m[1].toLowerCase()
    if (word.startsWith('max') || word.startsWith('<') || word.startsWith('≤'))
      return { kind: 'tol', tol: { min: null, nom: null, max: v }, label: 'nur Maximum' }
    if (word.startsWith('min') || word.startsWith('>') || word.startsWith('≥'))
      return { kind: 'tol', tol: { min: v, nom: null, max: null }, label: 'nur Minimum' }
    return { kind: 'tol', tol: { min: null, nom: v, max: null }, label: 'Nennwert' }
  }
  const parts = text.split(/[\s;/|]+/).filter(Boolean)
  if (parts.length >= 2 && parts.length <= 3 && parts.every((p) => parseNumber(p) !== null)) {
    const vals = parts.map((p) => parseNumber(p) as number)
    if (vals.length === 2) {
      return { kind: 'tol', tol: { min: Math.min(vals[0], vals[1]), nom: null, max: Math.max(vals[0], vals[1]) }, label: 'Min und Max' }
    }
    return { kind: 'tol', tol: { min: vals[0], nom: vals[1], max: vals[2] }, label: 'Min, Nom und Max' }
  }
  const single = parseNumber(text)
  if (single !== null) return { kind: 'single', value: single }
  return { kind: 'invalid' }
}

const round6 = (v: number) => Math.round(v * 1e6) / 1e6

/** Wirksame Toleranz wie im Backend (`_tol_from_parts`): fehlende Teile ergänzt; `null` = leer. */
export function effectiveTol(t: TolValue | null | undefined): { min: number; nom: number; max: number } | null {
  if (!t) return null
  let { min, max } = t
  const nom = t.nom
  if (min === null && nom === null && max === null) return null
  if (min !== null && max !== null) {
    if (max < min) [min, max] = [max, min]
    return { min, nom: nom ?? round6((min + max) / 2), max }
  }
  if (nom !== null) {
    if (min !== null) return { min, nom, max: Math.max(nom, round6(2 * nom - min)) }
    if (max !== null) return { min: Math.max(0, Math.min(nom, round6(2 * nom - max))), nom, max }
    return { min: nom, nom, max: nom }
  }
  const single = (min ?? max) as number
  return { min: single, nom: single, max: single }
}

/** Widerspruch in einem Toleranzwert (deutscher Text) oder null */
export function tolProblem(t: TolValue | null | undefined): string | null {
  if (!t) return null
  const { min, nom, max } = t
  if (min !== null && max !== null && nom !== null) {
    const lo = Math.min(min, max)
    const hi = Math.max(min, max)
    if (nom < lo - 1e-9 || nom > hi + 1e-9) return 'Nennwert liegt nicht zwischen Min und Max.'
  }
  if (min !== null && max !== null && max < min) return 'Min ist größer als Max – die Werte werden getauscht.'
  return null
}

// --------------------------------------------------------------------------- Werte normalisieren

const SENTINEL = -1

function toNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'string') return parseNumber(value)
  return null
}

function tolFromUnknown(value: unknown): TolValue | null {
  if (value === null || value === undefined || value === '') return null
  if (typeof value === 'number') return Number.isFinite(value) ? { min: null, nom: value, max: null } : null
  if (typeof value === 'string') {
    const parsed = parseTolText(value)
    if (parsed.kind === 'tol') return parsed.tol
    if (parsed.kind === 'single') return { min: null, nom: parsed.value, max: null }
    return null
  }
  if (Array.isArray(value)) {
    const vals = value.map(toNumber)
    if (vals.length === 1) return { min: null, nom: vals[0], max: null }
    if (vals.length === 2) return { min: vals[0], nom: null, max: vals[1] }
    if (vals.length === 3) return { min: vals[0], nom: vals[1], max: vals[2] }
    return null
  }
  if (typeof value === 'object') {
    const rec = value as Record<string, unknown>
    const part = (v: unknown) => {
      const x = toNumber(v)
      return x === SENTINEL ? null : x
    }
    const tol: TolValue = { min: part(rec.min), nom: part(rec.nom ?? rec.typ), max: part(rec.max) }
    // vollständige Werte aus dem Generator (Nennwert = Mitte) → Nennwert leer lassen (zeigt „Mitte“)
    if (tol.min !== null && tol.max !== null && tol.nom !== null && Math.abs(tol.nom - (tol.min + tol.max) / 2) < 1e-6 && tol.min !== tol.max) {
      tol.nom = null
    }
    return isEmptyTol(tol) ? null : tol
  }
  return null
}

function matchOption(spec: FootprintParamSpec, raw: unknown): string | null {
  if (raw === null || raw === undefined || raw === '') return null
  const text = String(raw).trim()
  if (!spec.options.length) return text
  const exact = spec.options.find((o) => o.toLowerCase() === text.toLowerCase())
  if (exact) return exact
  const asNum = toNumber(text)
  if (asNum !== null) {
    const numeric = spec.options.find((o) => toNumber(o) === asNum)
    if (numeric) return numeric
  }
  return text
}

/** Einen Rohwert (Vorlage, Generator-Protokoll, Alias) in den Formularwert der Parameterart umwandeln. */
export function normalizeParam(spec: FootprintParamSpec, raw: unknown): ParamValue {
  if (raw === null || raw === undefined) return null
  switch (spec.kind) {
    case 'tol':
      return tolFromUnknown(raw)
    case 'int': {
      const v = toNumber(raw)
      return v === null ? null : Math.round(v)
    }
    case 'float':
      return toNumber(raw)
    case 'bool':
      if (typeof raw === 'boolean') return raw
      if (typeof raw === 'number') return raw !== 0
      return ['1', 'true', 'ja', 'yes', 'j', 'an', 'on'].includes(String(raw).trim().toLowerCase())
    case 'enum':
      return matchOption(spec, raw)
    default:
      return raw === '' ? null : String(raw)
  }
}

/** Alle bekannten Parameter aus einem Rohobjekt lesen (unbekannte Schlüssel und „preset“ entfallen). */
export function normalizeParams(specs: readonly FootprintParamSpec[], raw: Record<string, unknown> | null | undefined): ParamValues {
  const out: ParamValues = {}
  if (!raw) return out
  for (const spec of specs) {
    if (!(spec.name in raw)) continue
    const v = normalizeParam(spec, raw[spec.name])
    if (v !== null) out[spec.name] = v
  }
  return out
}

/** Standardwert des Parameters (normalisiert) */
export function defaultValue(spec: FootprintParamSpec): ParamValue {
  return normalizeParam(spec, spec.default)
}

/**
 * Gespeicherte Generator-Parameter fürs Formular: Werte der Gruppen „Erweitert“/„Name“, die nur den Standard
 * wiederholen (Kupferabstand, Courtyard-Raster …), weglassen – Maße und Selektoren bleiben sichtbar stehen.
 */
export function withoutDefaults(specs: readonly FootprintParamSpec[], values: ParamValues): ParamValues {
  const out: ParamValues = {}
  for (const spec of specs) {
    const v = values[spec.name]
    if (v === null || v === undefined) continue
    const def = defaultValue(spec)
    if ((spec.group === 'Erweitert' || spec.group === 'Name') && def !== null && sameValue(spec, v, def)) continue
    out[spec.name] = v
  }
  return out
}

// --------------------------------------------------------------------------- Vergleichen und serialisieren

const close = (a: number, b: number) => Math.abs(a - b) < 1e-6

/** Semantische Gleichheit (Toleranzen über die wirksamen Werte, Zahlen mit Toleranz, Texte ohne Großschreibung). */
export function sameValue(spec: FootprintParamSpec, a: ParamValue | undefined, b: ParamValue | undefined): boolean {
  const an = a ?? null
  const bn = b ?? null
  if (spec.kind === 'tol') {
    const ea = effectiveTol(isTolValue(an) ? an : null)
    const eb = effectiveTol(isTolValue(bn) ? bn : null)
    if (!ea || !eb) return !ea && !eb
    return close(ea.min, eb.min) && close(ea.nom, eb.nom) && close(ea.max, eb.max)
  }
  if (an === null || bn === null || an === '' || bn === '') return (an === null || an === '') && (bn === null || bn === '')
  if (typeof an === 'number' && typeof bn === 'number') return close(an, bn)
  if (spec.kind === 'enum') {
    const na = toNumber(String(an))
    const nb = toNumber(String(bn))
    if (na !== null && nb !== null) return close(na, nb)
  }
  return String(an).toLowerCase() === String(bn).toLowerCase()
}

/** Namen der Parameter, die sich zwischen zwei Wertesätzen unterscheiden */
export function changedParams(specs: readonly FootprintParamSpec[], values: ParamValues, base: ParamValues): string[] {
  return specs.filter((s) => !sameValue(s, values[s.name], base[s.name])).map((s) => s.name)
}

/** Formularwerte → `FootprintRequest.params` (nur angegebene Werte, Toleranzen ohne leere Teile). */
export function serializeParams(specs: readonly FootprintParamSpec[], values: ParamValues): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const spec of specs) {
    const v = values[spec.name]
    if (v === null || v === undefined || v === '') continue
    if (spec.kind === 'tol') {
      if (!isTolValue(v) || isEmptyTol(v)) continue
      const t: Record<string, number> = {}
      if (v.min !== null) t.min = v.min
      if (v.nom !== null) t.nom = v.nom
      if (v.max !== null) t.max = v.max
      out[spec.name] = t
    } else if (spec.kind === 'int' || spec.kind === 'float') {
      if (typeof v === 'number' && Number.isFinite(v)) out[spec.name] = v
    } else if (spec.kind === 'bool') {
      out[spec.name] = Boolean(v)
    } else {
      const text = String(v).trim()
      if (text) out[spec.name] = text
    }
  }
  return out
}

// --------------------------------------------------------------------------- Darstellung

/** „Gesamtbreite E“ → { symbol: 'E', text: 'Gesamtbreite' }; „Körper X (E)“ → { symbol: 'E', text: 'Körper X' } */
export function splitLabel(spec: FootprintParamSpec): { symbol: string | null; text: string } {
  const label = spec.label.trim()
  const name = spec.name
  if (name.length <= 3 && /^[A-Za-z][A-Za-z0-9]?\d?$/.test(name)) {
    if (label.endsWith(` (${name})`)) return { symbol: name, text: label.slice(0, -(name.length + 3)).trim() }
    if (label.endsWith(` ${name}`)) return { symbol: name, text: label.slice(0, -(name.length + 1)).trim() }
  }
  return { symbol: null, text: label }
}

/** Kurze, deutsche Anzeigenamen für Auswahlwerte (Rohwert bleibt der gesendete Wert) */
const ENUM_LABELS: Record<string, Record<string, string>> = {
  rounding: { kicad: 'KiCad', ipc: 'IPC' },
  cathode_pad: { '1': 'Pad 1', '2': 'Pad 2' },
  lead_style: { gullwing: 'Gull-Wing', flat: 'Flach' },
  pad_shape: { round: 'Rund', oval: 'Oval' },
  ipc_table: { '7351B': 'IPC-7351B', '7352': 'IPC-7352' },
  rows: { '1': '1 Reihe', '2': '2 Reihen' },
  kind: {
    R: 'R · Widerstand',
    C: 'C · Kondensator',
    L: 'L · Induktivität',
    FB: 'FB · Ferrit',
    D: 'D · Diode',
    LED: 'LED',
    CAPMP: 'CAPMP · Tantal',
    INDM: 'INDM · Induktivität',
    FUSM: 'FUSM · Sicherung',
    DIOM: 'DIOM · Diode',
    CAPPRD: 'CAPPRD · Elko gepolt',
    CAPRD: 'CAPRD · Elko bipolar',
  },
}

/** Ausführlicher Text eines Auswahlwerts für Listen */
export function enumLabel(spec: FootprintParamSpec, option: string): string {
  const mapped = ENUM_LABELS[spec.name]?.[option]
  if (mapped) return mapped
  if (spec.name === 'pitch' || spec.unit === 'mm') {
    const v = toNumber(option)
    if (v !== null) return `${formatDim(v)} mm`
  }
  return option
}

/** Kurzer Text eines Auswahlwerts (Segmente) */
export function enumShortLabel(spec: FootprintParamSpec, option: string): string {
  const mapped = ENUM_LABELS[spec.name]?.[option]
  if (mapped) return mapped.split(' · ')[0]
  if (spec.name === 'pitch') {
    const v = toNumber(option)
    if (v !== null) return formatDim(v)
  }
  return option
}

/** Gruppen in sinnvoller Reihenfolge (Typ zuerst, Name/Erweitert zuletzt), Parameter in Backend-Reihenfolge */
export interface ParamGroup {
  id: string
  label: string
  params: FootprintParamSpec[]
}

const GROUP_LAST = ['Name', 'Erweitert']

export function groupParams(specs: readonly FootprintParamSpec[]): ParamGroup[] {
  const map = new Map<string, FootprintParamSpec[]>()
  for (const spec of specs) {
    const g = spec.group ?? 'Optionen'
    const list = map.get(g)
    if (list) list.push(spec)
    else map.set(g, [spec])
  }
  const order = [...map.keys()].sort((a, b) => {
    const ra = a === 'Typ' ? -1 : GROUP_LAST.indexOf(a) >= 0 ? 100 + GROUP_LAST.indexOf(a) : 0
    const rb = b === 'Typ' ? -1 : GROUP_LAST.indexOf(b) >= 0 ? 100 + GROUP_LAST.indexOf(b) : 0
    return ra - rb
  })
  return order.map((g) => ({ id: g, label: g, params: map.get(g) ?? [] }))
}

const SOFT_HYPHEN = String.fromCharCode(0xad)

/** Wortbestandteile, vor denen lange Komposita umbrechen dürfen („Anschluss|breite“, „Draht|durch|messer“) */
const MORPHEMES = [
  'breite', 'länge', 'dicke', 'höhe', 'tiefe', 'abstand', 'durchmesser', 'messer', 'raster', 'toleranz', 'zugabe',
  'querschnitt', 'fläche', 'achse', 'fahne', 'körper', 'weite', 'dichte', 'anschlüsse', 'kupfer',
]
const MORPHEME_RE = MORPHEMES.map((m) => new RegExp(`(?<=[a-zäöüß]{3})(${m})`, 'gi'))

/**
 * Weiche Trennstellen (U+00AD) in langen Komposita – der Text bricht bei schmaler Spalte an einer Silbengrenze
 * statt mitten im Wort abgeschnitten zu werden. Nur für sichtbaren Text (Vorleser ignorieren U+00AD).
 */
export function softHyphenate(text: string): string {
  return text.replace(/[A-Za-zÄÖÜäöüß]{10,}/g, (word) => MORPHEME_RE.reduce((w, re) => w.replace(re, `${SOFT_HYPHEN}$1`), word))
}

/** Ist der getippte Text mehr als eine (angefangene) Zahl – also ein Ausdruck wie „0,25±0,05“ oder „max 1,75“? */
export const isTolExpression = (text: string): boolean => !/^\s*[+-]?[\d.,]*\s*(mm)?\s*$/i.test(text)

/** Parameter, deren Bezeichnung in einer Fehlermeldung vorkommt (für die Markierung im Formular) */
export function paramsInMessage(specs: readonly FootprintParamSpec[], message: string | null | undefined): Set<string> {
  const hits = new Set<string>()
  if (!message) return hits
  const sorted = [...specs].sort((a, b) => b.label.length - a.label.length)
  let rest = message
  for (const spec of sorted) {
    const escaped = spec.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const re = new RegExp(`${escaped}(?![\\wÄÖÜäöüß])`, 'g')
    if (re.test(rest)) {
      hits.add(spec.name)
      rest = rest.replace(re, ' ')
    }
  }
  return hits
}

/** Selektoren (wählen innerhalb der Familie ein Gehäuse) – wie `SELECTORS` im Backend */
export const SELECTOR_PARAMS = ['variant', 'size', 'kind', 'case', 'pins', 'leads', 'rows', 'cols', 'pins_per_row', 'pitch', 'e', 'eA']
export const STRONG_SELECTORS = ['variant', 'size', 'kind', 'case']
