/**
 * Werte im Serien-Assistenten: E-Reihen-Zugehörigkeit (wie engine.py `in_series`), Wertcodes der Teilenummern lesen
 * (wie formats.py `decode_value`), Werteliste einfügen („10k, 4k7; 1M“), Anzeige- und Anfragetexte.
 */
import type { ValueFormat } from '@/api/series'
import { cleanFloat, E_SERIES, formatEngineering, parseEngineering, valuesInRange, type ESeriesName } from '@/lib/units'

export const SERIES_NAMES: ESeriesName[] = ['E3', 'E6', 'E12', 'E24', 'E48', 'E96', 'E192']

/** Zahl aus einem Backend-Text („10M“, „9.76“, „1e+08“, „6.3V“, „±20%“, „7.8mΩ“) */
export function parseAmount(text: string | null | undefined): number | null {
  if (!text) return null
  const t = String(text).replace(/[±\s]/g, '')
  const direct = parseEngineering(t)
  if (direct !== null) return direct
  const m = t.match(/^([+-]?\d+(?:[.,]\d+)?(?:e[+-]?\d+)?)([pnuµμmkKMGT]?)/i)
  return m ? parseEngineering(`${m[1]}${m[2]}`) : null
}

// --------------------------------------------------------------------------- E-Reihen

const round6 = (x: number): number => Math.round(x * 1e6) / 1e6

const SERIES_SETS = Object.fromEntries(
  SERIES_NAMES.map((name) => [name, new Set(E_SERIES[name].map((m) => round6(m)))]),
) as Record<ESeriesName, Set<number>>

/** Mantisse in [1, 10), auf 6 Stellen gerundet */
function mantissa(value: number): number {
  const exp = Math.floor(Math.log10(value))
  let m = round6(value / 10 ** exp)
  if (m >= 10) m = round6(m / 10)
  else if (m < 1) m = round6(m * 10)
  return m
}

/** Gehört der Wert zu einer der Reihen? */
export function inSeries(value: number, series: readonly string[]): boolean {
  if (!(value > 0)) return false
  const m = mantissa(value)
  return series.some((name) => SERIES_SETS[name.toUpperCase() as ESeriesName]?.has(m))
}

/** Werte aller Reihen in [lo, hi] (Vereinigung, aufsteigend) */
export function seriesValues(series: readonly ESeriesName[], lo: number, hi: number): number[] {
  const out = new Set<number>()
  for (const name of series) for (const v of valuesInRange(name, Math.max(lo, 1e-15), hi)) out.add(v)
  return [...out].sort((a, b) => a - b)
}

/** Werte je Dekade einer Reihe */
export const valuesPerDecade = (name: ESeriesName): number => E_SERIES[name].length

// --------------------------------------------------------------------------- Wertcodes (formats.py)

const RKM_LETTERS: Record<string, number> = { R: 0, K: 3, M: 6, G: 9 }
const UNIOHM_NEGATIVE: Record<string, number> = { J: -1, K: -2, L: -3, M: -4, N: -5, P: -6 }

export function significantDigits(fmt: Pick<ValueFormat, 'style' | 'digits'>): number {
  if (fmt.digits) return fmt.digits
  return { rkm: 3, rkm4: 3, eia3: 2, eia4: 3, uniohm4: 3 }[fmt.style]
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Wert (Basiseinheit) eines Wertcodes, z. B. „104“ (eia3, pF) → 1e-7; ungültig → null */
export function decodeValueCode(code: string, fmt: ValueFormat): number | null {
  const text = code.trim().toUpperCase()
  if (!text) return null
  let units: number
  if (fmt.style === 'rkm' || fmt.style === 'rkm4') {
    const letters = fmt.letters && Object.keys(fmt.letters).length ? fmt.letters : RKM_LETTERS
    const m = text.match(new RegExp(`^(\\d*)([${escapeRe(Object.keys(letters).join(''))}])(\\d*)$`))
    if (!m || !(m[1] || m[3])) return null
    if (fmt.style === 'rkm4' && m[1].length + m[3].length !== significantDigits(fmt)) return null
    units = Number(`${m[1] || '0'}.${m[3] || '0'}`) * 10 ** letters[m[2]]
  } else if (fmt.style === 'eia3' || fmt.style === 'eia4') {
    const digits = significantDigits(fmt)
    if (text.includes('R')) {
      if (text.length !== digits + 1 || !/^\d*R\d*$/.test(text)) return null
      units = Number(text.replace('R', '.'))
    } else {
      if (text.length !== digits + 1 || !/^\d+$/.test(text)) return null
      const mult = text.slice(-1)
      const exp = fmt.small_multipliers?.[mult] ?? Number(mult)
      units = Number(text.slice(0, -1)) * 10 ** exp
    }
  } else {
    const m = text.match(/^(\d{3})([0-6JKLMNP])$/)
    if (!m) return null
    if (significantDigits(fmt) === 2 && !m[1].startsWith('0')) return null
    const exp = /\d/.test(m[2]) ? Number(m[2]) : UNIOHM_NEGATIVE[m[2]]
    units = Number(m[1]) * 10 ** exp
  }
  return Number.isFinite(units) ? cleanFloat(units * fmt.scale, 12) : null
}

// --------------------------------------------------------------------------- Anzeige und Anfrage

const compactFormat = new Intl.NumberFormat('de-DE', { maximumSignificantDigits: 4 })
const PREFIXES: [number, string][] = [
  [1e12, 'T'],
  [1e9, 'G'],
  [1e6, 'M'],
  [1e3, 'k'],
  [1, ''],
  [1e-3, 'm'],
  [1e-6, 'µ'],
  [1e-9, 'n'],
  [1e-12, 'p'],
  [1e-15, 'f'],
]

/** Kompakt ohne Einheit (Skalenmarken): 4700 → „4,7k“, 1e-7 → „100n“ */
export function compactValue(value: number): string {
  if (value === 0) return '0'
  const abs = Math.abs(value)
  const [factor, prefix] = PREFIXES.find(([f]) => abs >= f * 0.9995) ?? PREFIXES[PREFIXES.length - 1]
  return `${compactFormat.format(value / factor)}${prefix}`
}

/** Anzeige mit Einheit: „4,7 kΩ“, „100 nF“, „0 Ω“ */
export function displayValue(value: number, unit: string): string {
  if (value === 0) return `0 ${unit}`
  return formatEngineering(value, unit, 4)
}

/** Text für das Backend (`parse_quantity` versteht Zahlen mit Exponent): 4700 → „4700“, 1e-7 → „1e-7“ */
export const requestNumber = (value: number): string => String(cleanFloat(value, 12))

// --------------------------------------------------------------------------- Werteliste

export interface ParsedValue {
  /** eingegebener Text */
  raw: string
  value: number | null
  /** deutsche Fehlermeldung */
  error: string | null
  /** schon weiter oben in der Liste */
  duplicate: boolean
  jumper: boolean
}

/** Einheit (mit Vorsatz) nach einem Leerzeichen: „µF“, „kΩ“, „Ohm“, „n“ */
const UNIT_WORD = /^(?:[pnuµμmkKMG]?(?:Ω|ω|ohms?|F|H)|[pnuµμmkKMG])$/i

/**
 * Werteliste zerlegen: Zeilen, Semikolon, Tab, Komma (außer Dezimalkomma „4,7k“) und Leerzeichen trennen
 * („10k 4k7“), Leerzeichen vor einer Einheit nicht („2,2 µF“, „10 kΩ“).
 */
export function tokenizeValues(text: string): string[] {
  const s = text.replace(/\r/g, '')
  const out: string[] = []
  let cur = ''
  const push = () => {
    const t = cur.trim()
    if (t) out.push(t)
    cur = ''
  }
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '\n' || ch === ';' || ch === '\t') {
      push()
      continue
    }
    if (ch === ',') {
      const prev = s[i - 1] ?? ''
      const next = s[i + 1] ?? ''
      if (/\d/.test(prev) && /\d/.test(next)) cur += ch
      else push()
      continue
    }
    if (/\s/.test(ch)) {
      let j = i + 1
      while (j < s.length && s[j] === ' ') j++
      // nur eine Einheit gehört zum Wert davor („2,2 µF“, „10 kΩ“) – alles andere beginnt einen neuen Eintrag
      const word = s.slice(j).match(/^[^\s,;]+/)?.[0] ?? ''
      if (!cur || !UNIT_WORD.test(word)) push()
      i = j - 1
      continue
    }
    cur += ch
  }
  push()
  return out
}

const UNIT_SUFFIX = /(ω|Ω|ohms?|f|h)$/i

function unitOf(token: string): 'Ω' | 'F' | 'H' | null {
  const m = token.match(UNIT_SUFFIX)
  if (!m) return null
  const u = m[1].toLowerCase()
  if (u === 'f') return 'F'
  if (u === 'h') return 'H'
  return 'Ω'
}

/** Werteliste lesen (Einheit der Serie, „0“ = Brücke) */
export function parseValueList(text: string, unit: string, opts: { jumper: boolean }): ParsedValue[] {
  const seen = new Set<number>()
  return tokenizeValues(text).map((raw) => {
    const result: ParsedValue = { raw, value: null, error: null, duplicate: false, jumper: false }
    const u = unitOf(raw)
    if (u && u !== unit) {
      result.error = `Einheit passt nicht – die Serie erwartet ${unit}.`
      return result
    }
    if (unit !== 'Ω' && /\d[Rr]\d|^[Rr]\d|\d[Rr]$/.test(raw)) {
      result.error = 'Die R-Schreibweise gibt es nur bei Widerständen.'
      return result
    }
    const value = parseEngineering(raw)
    if (value === null || !Number.isFinite(value)) {
      result.error = 'Kein gültiger Wert (z. B. 4k7, 100n, 2,2 µ).'
      return result
    }
    if (value < 0) {
      result.error = 'Negative Werte gibt es nicht.'
      return result
    }
    if (value === 0) {
      if (unit !== 'Ω' || !opts.jumper) {
        result.error = unit === 'Ω' ? 'Diese Serie hat keine 0-Ω-Brücke.' : '0 ist kein gültiger Wert.'
        return result
      }
      result.jumper = true
    }
    result.value = value
    if (seen.has(value)) result.duplicate = true
    seen.add(value)
    return result
  })
}
