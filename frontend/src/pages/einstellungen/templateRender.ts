import { t } from '@/lib/i18n'
/**
 * Beschreibungs-/Kommentarvorlagen im Browser rendern – Port von `partforge/db/values.py::render_template`
 * und den Formaten aus `partforge/domain/units.py` (si, rkm, nounit, upper, lower). Damit zeigt der
 * Schema-Designer sofort, was eine **ungespeicherte** Vorlage für ein echtes Bauteil ergibt; die gespeicherte
 * Vorlage rendert das Backend (`POST /api/parts/{table}/render-templates`) exakt.
 */

export interface RenderField {
  column: string
  unit?: string | null
}

const PLACEHOLDER = /\{([^{}:]+?)(?::([A-Za-z]+))?\}/g
const SEPARATOR_TOKEN = /^[,;/|\-–—·]+$/

// --------------------------------------------------------------------------- Einheiten (domain/units.py)

const PREFIXES: Record<string, number> = {
  f: 1e-15,
  p: 1e-12,
  n: 1e-9,
  u: 1e-6,
  µ: 1e-6,
  μ: 1e-6,
  m: 1e-3,
  k: 1e3,
  K: 1e3,
  M: 1e6,
  G: 1e9,
  T: 1e12,
}
const SI_SYMBOLS: Record<number, string> = { [-15]: 'f', [-12]: 'p', [-9]: 'n', [-6]: 'µ', [-3]: 'm', 0: '', 3: 'k', 6: 'M', 9: 'G', 12: 'T' }
const RKM_SYMBOLS: Record<number, string> = { [-15]: 'f', [-12]: 'p', [-9]: 'n', [-6]: 'u', [-3]: 'm', 3: 'k', 6: 'M', 9: 'G', 12: 'T' }
const NO_PREFIX_UNITS = new Set(['%', 'ppm/K', 'ppm', '°C', '°', 'dB', 'mm', 'nm', 'mil', 'K', 'in'])
const RKM_UNIT_LETTERS = new Set(['V', 'A', 'W', 'F', 'H', 'C', 's'])
const PLUS_MINUS_UNITS = new Set(['%', 'ppm'])

const UNIT_ALIASES: Record<string, string[]> = {
  Ω: ['Ω', 'Ω', 'ohm', 'ohms', 'Ohm', 'OHM', 'R'],
  F: ['F', 'farad'],
  H: ['H', 'henry'],
  V: ['V', 'volt', 'VDC', 'VAC', 'Vdc', 'Vac'],
  A: ['A', 'amp', 'ampere'],
  W: ['W', 'watt'],
  Hz: ['Hz', 'hz', 'HZ'],
  '%': ['%'],
  'ppm/K': ['ppm/K', 'ppm/°C', 'ppm/C', 'ppm/k'],
  ppm: ['ppm'],
  '°C': ['°C', 'degC', 'C°'],
  '°': ['°', 'deg', 'grad'],
  s: ['s', 'sec'],
  dB: ['dB'],
  cd: ['cd'],
  C: ['C', 'coulomb'],
  'V/µs': ['V/µs', 'V/us', 'V/μs'],
  mm: ['mm'],
  nm: ['nm'],
  mil: ['mil', 'mils'],
}
const ALIAS_LOOKUP: [string, string][] = Object.entries(UNIT_ALIASES)
  .flatMap(([canonical, aliases]) => aliases.map((a) => [a, canonical] as [string, string]))
  .sort((a, b) => b[0].length - a[0].length)

export function normalizeUnit(unit: string | null | undefined): string {
  if (!unit) return ''
  const u = unit.trim()
  for (const [alias, canonical] of ALIAS_LOOKUP) {
    if (alias.length === 1) {
      if (u === alias) return canonical
    } else if (u.toLowerCase() === alias.toLowerCase()) return canonical
  }
  return u
}

function isKnownUnit(u: string): boolean {
  return Object.prototype.hasOwnProperty.call(UNIT_ALIASES, u)
}

interface Quantity {
  value: number
  unit: string
}

function clean(text: string): string {
  return text
    .trim()
    .replace(/[    ]/g, '')
    .replace(/±/g, '')
    .replace('+/-', '')
    .replace(/Ω/g, 'Ω')
    .replace(/(?<=\d),(?=\d)/g, '.')
    .replace(/[−‒–‐‑﹣－]/g, '-')
}

function splitPrefixUnit(rest: string, defaultUnit: string | null): [number, string] | null {
  const def = normalizeUnit(defaultUnit)
  if (rest === '') return [1, def]
  if ((rest === 'C' || rest === 'c') && def === '°C') return [1, '°C']
  if (def && normalizeUnit(rest) === def) return [1, def]
  if (rest.toLowerCase().startsWith('meg')) return [1e6, normalizeUnit(rest.slice(3)) || def]
  const canonical = normalizeUnit(rest)
  if (canonical !== rest || isKnownUnit(rest)) return [1, canonical]
  const first = rest[0]
  if (first in PREFIXES) {
    const unitPart = rest.slice(1)
    const c = unitPart ? normalizeUnit(unitPart) : def
    if (unitPart === '' || c !== unitPart || isKnownUnit(unitPart) || (def && c === def)) return [PREFIXES[first], c]
  }
  return null
}

const RKM_RE = /^(\d*)([RrEkKMGmunpµμfVAW])(\d+)([A-Za-zΩ°/%]*)$/
const NUM_RE = /^([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(.*)$/
const FRACTION_RE = /^(\d+)\/(\d+)(.*)$/

export function parseQuantity(text: string, defaultUnit: string | null): Quantity | null {
  const t = clean(text)
  if (!t) return null
  let m = FRACTION_RE.exec(t)
  if (m) {
    const d = Number(m[2])
    if (!d) return null
    const split = splitPrefixUnit(m[3], defaultUnit)
    return split ? { value: (Number(m[1]) / d) * split[0], unit: split[1] } : null
  }
  m = RKM_RE.exec(t)
  if (m) {
    const [, a, letter, b, suffix] = m
    let mult = 1
    let unit: string
    if ('RrE'.includes(letter)) unit = 'Ω'
    else if ('VAW'.includes(letter)) unit = letter
    else {
      mult = PREFIXES[letter] ?? 1
      unit = suffix ? normalizeUnit(suffix) : normalizeUnit(defaultUnit)
    }
    if ('RrE'.includes(letter) && suffix) unit = normalizeUnit(suffix)
    return { value: Number(`${a || '0'}.${b}`) * mult, unit }
  }
  m = NUM_RE.exec(t)
  if (!m) return null
  const num = Number(m[1])
  const rest = m[2]
  if ((rest[0] === 'R' || rest[0] === 'r') && (rest.length === 1 || normalizeUnit(rest.slice(1)) === 'Ω')) return { value: num, unit: 'Ω' }
  const split = splitPrefixUnit(rest, defaultUnit)
  if (!split || !Number.isFinite(num)) return null
  return { value: num * split[0], unit: split[1] }
}

function significant(value: number, digits: number): number {
  if (value === 0 || !Number.isFinite(value)) return value
  return Number(value.toPrecision(digits))
}

function exactDigits(value: number): number {
  if (value === 0 || !Number.isFinite(value)) return 3
  for (let d = 3; d <= 9; d++) {
    if (Math.abs(significant(value, d) - value) <= Math.abs(value) * 1e-9) return d
  }
  return 9
}

function plain(value: number, digits: number): string {
  if (value === 0) return '0'
  const magnitude = Math.floor(Math.log10(Math.abs(value)))
  const decimals = Math.max(0, digits - 1 - magnitude)
  let text = value.toFixed(Math.min(decimals, 20))
  if (text.includes('.')) text = text.replace(/0+$/, '').replace(/\.$/, '')
  return text === '-0' || text === '' ? '0' : text
}

function engineering(value: number, digits: number): [string, number] {
  if (value === 0) return ['0', 0]
  let exp3 = Math.floor(Math.log10(Math.abs(value)) / 3) * 3
  exp3 = Math.max(-15, Math.min(12, exp3))
  let text = plain(value / 10 ** exp3, digits)
  if (Math.abs(Number(text)) >= 1000 && exp3 + 3 <= 12) {
    exp3 += 3
    text = plain(value / 10 ** exp3, digits)
  }
  return [text, exp3]
}

export function formatQuantity(value: number, unit: string, plusMinus = false): string {
  const u = normalizeUnit(unit)
  const sign = plusMinus && value >= 0 ? '±' : ''
  if (value === 0) return `${sign}0${u}`
  const places = exactDigits(value)
  const v = significant(value, places)
  if (NO_PREFIX_UNITS.has(u) || (u === 'W' && Math.abs(value) >= 0.1)) return `${sign}${plain(v, places)}${u}`
  const [text, exp3] = engineering(v, places)
  return `${sign}${text}${SI_SYMBOLS[exp3] ?? ''}${u}`
}

export function formatRkmCode(value: number, unit: string): string {
  const u = normalizeUnit(unit)
  const isOhm = u === 'Ω'
  if (value === 0) return isOhm ? '0R' : `0${u}`
  const places = exactDigits(value)
  const v = significant(value, places)
  const sign = v < 0 ? '-' : ''
  const magnitude = Math.abs(v)
  if (NO_PREFIX_UNITS.has(u)) return `${sign}${plain(magnitude, places)}${u}`
  if (isOhm && magnitude < 1) {
    const frac = plain(magnitude, places)
    return `${sign}R${frac.includes('.') ? frac.split('.')[1] : frac}`
  }
  const [text, exp3] = engineering(magnitude, places)
  let letter: string
  if (exp3 === 0) {
    if (!isOhm && u && !RKM_UNIT_LETTERS.has(u)) return `${sign}${text}${u}`
    letter = isOhm ? 'R' : u || '.'
  } else if (exp3 === 3) letter = 'k'
  else letter = RKM_SYMBOLS[exp3] ?? ''
  if (text.includes('.')) {
    const [whole, frac] = text.split('.')
    return `${sign}${whole}${letter}${frac}`
  }
  return `${sign}${text}${letter}`
}

// --------------------------------------------------------------------------- Vorlagen (db/values.py)

function lookup(values: Record<string, unknown>, column: string): unknown {
  if (column in values) return values[column]
  const folded = column.toLowerCase()
  const key = Object.keys(values).find((k) => k.toLowerCase() === folded)
  return key === undefined ? null : values[key]
}

function toText(raw: unknown): string | null {
  if (raw === null || raw === undefined) return null
  if (typeof raw === 'boolean') return raw ? t("Ja") : t("Nein")
  const text = String(raw).trim()
  return text ? text : null
}

function formatPlaceholder(column: string, spec: string | undefined, values: Record<string, unknown>, fields: RenderField[]): string {
  const text = toText(lookup(values, column))
  if (text === null) return ''
  if (!spec) return text
  const s = spec.toLowerCase()
  if (s === 'upper') return text.toUpperCase()
  if (s === 'lower') return text.toLowerCase()
  const field = fields.find((f) => f.column.toLowerCase() === column.toLowerCase())
  const unit = field?.unit ?? null
  const q = parseQuantity(text, unit)
  if (!q) return text
  const effective = unit || q.unit
  if (s === 'rkm') return formatRkmCode(q.value, effective)
  if (s === 'si') return formatQuantity(q.value, effective, text.includes('±') || PLUS_MINUS_UNITS.has(normalizeUnit(effective)))
  if (s === 'nounit' || s === 'num') return formatQuantity(q.value, '')
  return text
}

/** Vorlage an Leerraum außerhalb von {…} teilen */
function templateTokens(template: string): string[] {
  const tokens: string[] = []
  let buf = ''
  let depth = 0
  for (const ch of template) {
    if (ch === '{') depth++
    else if (ch === '}' && depth > 0) depth--
    if (/\s/.test(ch) && depth === 0) {
      if (buf) tokens.push(buf)
      buf = ''
    } else buf += ch
  }
  if (buf) tokens.push(buf)
  return tokens
}

/**
 * Vorlage rendern. Leerzeichen-getrennte Teile, deren Platzhalter alle leer sind, entfallen
 * („IC {Channels}CH {GBW}“ ohne Channels → „IC <GBW>“); Trennzeichen am Anfang/Ende ebenso.
 */
export function renderTemplate(template: string | null | undefined, values: Record<string, unknown>, fields: RenderField[] = []): string {
  if (!template) return ''
  const out: string[] = []
  for (const token of templateTokens(template)) {
    let hasPlaceholder = false
    let filled = false
    const rendered = token.replace(PLACEHOLDER, (_m, name: string, spec?: string) => {
      hasPlaceholder = true
      const value = formatPlaceholder(name.trim(), spec, values, fields)
      if (value) filled = true
      return value
    })
    if (!hasPlaceholder || (filled && rendered.trim())) out.push(rendered)
  }
  while (out.length && SEPARATOR_TOKEN.test(out[0])) out.shift()
  while (out.length && SEPARATOR_TOKEN.test(out[out.length - 1])) out.pop()
  return out.join(' ').replace(/\s+/g, ' ').trim()
}

/** Platzhalter-Spalten einer Vorlage (ohne Doppelte) */
export function templateColumns(template: string): string[] {
  const seen: string[] = []
  for (const m of template.matchAll(PLACEHOLDER)) {
    const name = m[1].trim()
    if (!seen.includes(name)) seen.push(name)
  }
  return seen
}
