/**
 * Technische Werte im Frontend: Eingaben wie „4k7“, „100n“, „2,2 µF“, „0R“ lesen, Werte mit SI-Präfix
 * formatieren („4,7 kΩ“) und E-Reihen (IEC 60063, identisch mit partforge/domain/eseries.py).
 *
 *   parseEngineering('4k7')            → 4700
 *   parseEngineering('100 nF')         → 1e-7
 *   formatEngineering(4700, 'Ω')       → „4,7 kΩ“
 *   formatRkm(4700)                    → „4k7“   (Hauskonvention für Comment = Wert)
 *   valuesInRange('E24', 10, 1e6)      → [10, 11, 12, …, 1000000]
 *   nearestInSeries('E12', 5000)       → 4700
 *   stepInSeries('E12', 4700, +1)      → 5600
 */

const PREFIX: Record<string, number> = {
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

const UNIT_RE = /(Ω|ohms?|Ohm|F|H|Hz|V|A|W|%|ppm)$/i

/**
 * Technischen Wert lesen. Akzeptiert Komma oder Punkt, SI-Präfixe (p n µ/u m k M G T), RKM-Schreibweise
 * („4k7“, „2R2“, „0R“, „4n7“) und eine angehängte Einheit. Ungültig → null.
 */
export function parseEngineering(text: string): number | null {
  let t = text.trim().replace(/\s+/g, '').replace(/[−–]/g, '-')
  if (!t) return null
  // Einheit am Ende entfernen (nicht das „m“ von „mF“ usw.)
  const unit = t.match(UNIT_RE)
  if (unit && t.length > unit[0].length) t = t.slice(0, -unit[0].length)
  t = t.replace(',', '.')
  // RKM: Präfix/R als Dezimalzeichen („4k7“, „2R2“, „R47“)
  const rkm = t.match(/^([-+]?\d*)([pnuµμmkKMGTRr])(\d+)$/)
  if (rkm) {
    const [, intPart, marker, frac] = rkm
    const mantissa = Number(`${intPart || '0'}.${frac}`)
    const factor = marker === 'R' || marker === 'r' ? 1 : PREFIX[marker]
    return Number.isFinite(mantissa) && factor !== undefined ? cleanFloat(mantissa * factor) : null
  }
  const m = t.match(/^([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)([pnuµμmkKMGTRr]?)$/i)
  if (!m) return null
  const base = Number(m[1])
  if (!Number.isFinite(base)) return null
  const marker = t.slice(m[1].length)
  if (!marker || marker === 'R' || marker === 'r') return cleanFloat(base)
  const factor = PREFIX[marker]
  return factor === undefined ? null : cleanFloat(base * factor)
}

/** Gleitkomma-Rauschen entfernen (4.7 * 1000 → 4700). */
export function cleanFloat(value: number, digits = 12): number {
  if (value === 0 || !Number.isFinite(value)) return value
  return Number(value.toPrecision(digits))
}

const ENG_PREFIXES: [number, string][] = [
  [1e12, 'T'],
  [1e9, 'G'],
  [1e6, 'M'],
  [1e3, 'k'],
  [1, ''],
  [1e-3, 'm'],
  [1e-6, 'µ'],
  [1e-9, 'n'],
  [1e-12, 'p'],
]

const mantissaFormat = new Map<number, Intl.NumberFormat>()
function formatMantissa(value: number, digits: number): string {
  let f = mantissaFormat.get(digits)
  if (!f) {
    f = new Intl.NumberFormat('de-DE', { maximumSignificantDigits: digits })
    mantissaFormat.set(digits, f)
  }
  return f.format(value)
}

/** Wert mit SI-Präfix: formatEngineering(4700, 'Ω') → „4,7 kΩ“ (geschütztes Leerzeichen vor der Einheit). */
export function formatEngineering(value: number, unit = '', significantDigits = 3): string {
  if (!Number.isFinite(value)) return '–'
  if (value === 0) return unit ? `0\u00a0${unit}` : '0'
  const abs = Math.abs(value)
  const [factor, prefix] = ENG_PREFIXES.find(([f]) => abs >= f * 0.9995) ?? ENG_PREFIXES[ENG_PREFIXES.length - 1]
  const text = formatMantissa(value / factor, significantDigits)
  const suffix = `${prefix}${unit}`
  return suffix ? `${text}\u00a0${suffix}` : text
}

/** RKM-Code nach IEC 60062 (Widerstände): 4700 → „4k7“, 100 → „100R“, 2.2 → „2R2“, 1e6 → „1M“. */
export function formatRkm(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '–'
  if (value === 0) return '0R'
  const steps: [number, string][] = [
    [1e9, 'G'],
    [1e6, 'M'],
    [1e3, 'k'],
    [1, 'R'],
    [1e-3, 'm'],
  ]
  const [factor, letter] = steps.find(([f]) => value >= f * 0.9995) ?? steps[steps.length - 1]
  const scaled = cleanFloat(value / factor, 3)
  const [int, frac = ''] = String(scaled).split('.')
  return `${int}${letter}${frac}`
}

// --------------------------------------------------------------------------- E-Reihen (IEC 60063)

export const E_SERIES = {
  E3: [1.0, 2.2, 4.7],
  E6: [1.0, 1.5, 2.2, 3.3, 4.7, 6.8],
  E12: [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2],
  E24: [
    1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0, 3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2,
    9.1,
  ],
  E48: [
    1.0, 1.05, 1.1, 1.15, 1.21, 1.27, 1.33, 1.4, 1.47, 1.54, 1.62, 1.69, 1.78, 1.87, 1.96, 2.05, 2.15, 2.26, 2.37, 2.49,
    2.61, 2.74, 2.87, 3.01, 3.16, 3.32, 3.48, 3.65, 3.83, 4.02, 4.22, 4.42, 4.64, 4.87, 5.11, 5.36, 5.62, 5.9, 6.19, 6.49,
    6.81, 7.15, 7.5, 7.87, 8.25, 8.66, 9.09, 9.53,
  ],
  E96: [
    1.0, 1.02, 1.05, 1.07, 1.1, 1.13, 1.15, 1.18, 1.21, 1.24, 1.27, 1.3, 1.33, 1.37, 1.4, 1.43, 1.47, 1.5, 1.54, 1.58,
    1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.0, 2.05, 2.1, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
    2.61, 2.67, 2.74, 2.8, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24, 3.32, 3.4, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
    4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23, 5.36, 5.49, 5.62, 5.76, 5.9, 6.04, 6.19, 6.34, 6.49, 6.65,
    6.81, 6.98, 7.15, 7.32, 7.5, 7.68, 7.87, 8.06, 8.25, 8.45, 8.66, 8.87, 9.09, 9.31, 9.53, 9.76,
  ],
  E192: [
    1.0, 1.01, 1.02, 1.04, 1.05, 1.06, 1.07, 1.09, 1.1, 1.11, 1.13, 1.14, 1.15, 1.17, 1.18, 1.2, 1.21, 1.23, 1.24, 1.26,
    1.27, 1.29, 1.3, 1.32, 1.33, 1.35, 1.37, 1.38, 1.4, 1.42, 1.43, 1.45, 1.47, 1.49, 1.5, 1.52, 1.54, 1.56, 1.58, 1.6,
    1.62, 1.64, 1.65, 1.67, 1.69, 1.72, 1.74, 1.76, 1.78, 1.8, 1.82, 1.84, 1.87, 1.89, 1.91, 1.93, 1.96, 1.98, 2.0, 2.03,
    2.05, 2.08, 2.1, 2.13, 2.15, 2.18, 2.21, 2.23, 2.26, 2.29, 2.32, 2.34, 2.37, 2.4, 2.43, 2.46, 2.49, 2.52, 2.55, 2.58,
    2.61, 2.64, 2.67, 2.71, 2.74, 2.77, 2.8, 2.84, 2.87, 2.91, 2.94, 2.98, 3.01, 3.05, 3.09, 3.12, 3.16, 3.2, 3.24, 3.28,
    3.32, 3.36, 3.4, 3.44, 3.48, 3.52, 3.57, 3.61, 3.65, 3.7, 3.74, 3.79, 3.83, 3.88, 3.92, 3.97, 4.02, 4.07, 4.12, 4.17,
    4.22, 4.27, 4.32, 4.37, 4.42, 4.48, 4.53, 4.59, 4.64, 4.7, 4.75, 4.81, 4.87, 4.93, 4.99, 5.05, 5.11, 5.17, 5.23, 5.3,
    5.36, 5.42, 5.49, 5.56, 5.62, 5.69, 5.76, 5.83, 5.9, 5.97, 6.04, 6.12, 6.19, 6.26, 6.34, 6.42, 6.49, 6.57, 6.65, 6.73,
    6.81, 6.9, 6.98, 7.06, 7.15, 7.23, 7.32, 7.41, 7.5, 7.59, 7.68, 7.77, 7.87, 7.96, 8.06, 8.16, 8.25, 8.35, 8.45, 8.56,
    8.66, 8.76, 8.87, 8.98, 9.09, 9.2, 9.31, 9.42, 9.53, 9.65, 9.76, 9.88,
  ],
} as const

export type ESeriesName = keyof typeof E_SERIES

/** Übliche Toleranz je Reihe (Vorgabe im Serien-Assistenten). */
export const E_SERIES_TOLERANCE: Record<ESeriesName, string> = {
  E3: '±40 %',
  E6: '±20 %',
  E12: '±10 %',
  E24: '±5 %',
  E48: '±2 %',
  E96: '±1 %',
  E192: '±0,5 %',
}

/** Alle Reihenwerte v mit min ≤ v ≤ max (aufsteigend, Basiseinheit). */
export function valuesInRange(series: ESeriesName, min: number, max: number): number[] {
  if (min <= 0 || max <= 0 || max < min) return []
  const base = E_SERIES[series]
  const start = Math.floor(Math.log10(min)) - 1
  const stop = Math.floor(Math.log10(max)) + 1
  const out = new Set<number>()
  for (let decade = start; decade <= stop; decade++) {
    for (const mantissa of base) {
      const v = cleanFloat(mantissa * 10 ** decade, 3)
      if (v >= min * (1 - 1e-9) && v <= max * (1 + 1e-9)) out.add(v)
    }
  }
  return [...out].sort((a, b) => a - b)
}

/** Nächster Reihenwert (logarithmischer Abstand). */
export function nearestInSeries(series: ESeriesName, value: number): number {
  if (!(value > 0)) return value
  const candidates = valuesInRange(series, value / 10, value * 10)
  let best = candidates[0] ?? value
  for (const c of candidates) {
    if (Math.abs(Math.log10(c) - Math.log10(value)) < Math.abs(Math.log10(best) - Math.log10(value))) best = c
  }
  return best
}

/** Nächster (dir = +1) bzw. vorheriger (dir = -1) Reihenwert ausgehend von `value`. */
export function stepInSeries(series: ESeriesName, value: number, dir: 1 | -1): number {
  const snapped = nearestInSeries(series, value)
  const candidates = valuesInRange(series, snapped / 20, snapped * 20)
  const i = candidates.findIndex((c) => Math.abs(c - snapped) <= snapped * 1e-9)
  return candidates[i + dir] ?? snapped
}

/** Kleinste E-Reihe, die den Wert enthält (null = kein Reihenwert). */
export function seriesOf(value: number): ESeriesName | null {
  if (!(value > 0)) return null
  const mantissa = cleanFloat(value / 10 ** Math.floor(Math.log10(value)), 9)
  for (const name of Object.keys(E_SERIES) as ESeriesName[]) {
    if (E_SERIES[name].some((m) => Math.abs(m - mantissa) <= 1e-6 * m)) return name
  }
  return null
}
