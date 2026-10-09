/**
 * Sofort-Zähler des Serien-Assistenten: wie viele Bauteile die Auswahl ergibt – je Baugröße, je Spannung, mit Brücken
 * und ausgelassenen Werten. Spiegelt partforge/domain/series.py (`_rule_candidates`, `_matrix_candidates`,
 * `_catalog_candidates`) und engine.py (`match_rule`, `in_series`). Die Vorschau des Backends bestätigt die Zahlen.
 */
import type { SeriesTemplate, TemplateRule } from '@/api/series'
import type { ESeriesName } from '@/lib/units'
import { effectiveSeries, listValues, parsedValues, type SeriesSettings } from './settings'
import {
  catalogTolerance,
  catalogValue,
  cellValue,
  defaultOption,
  effectiveTolerance,
  findOptionByCode,
  normTolerance,
  optionApplies,
  packagingVariable,
  tcrChoices,
  tcrMagnitude,
  templateMode,
  variable,
  type TemplateMode,
} from './template'
import { inSeries, parseAmount, seriesValues } from './values'

export interface Estimate {
  mode: TemplateMode
  /** lieferbare Bauteile ohne Brücken */
  parts: number
  /** 0-Ω-Brücken */
  jumpers: number
  /** parts + jumpers */
  total: number
  /** Zeilen der Werteliste, die es laut Vorlage nicht gibt (erscheinen als „ungültig“) */
  invalid: number
  /** verschiedene Werte */
  values: number
  /** Baugrößen mit mindestens einem Bauteil */
  sizes: number
  perSize: Record<string, number>
  /** Matrix/Katalog: Bauteile je Spannung (ohne Spannungsfilter) */
  perVoltage: Record<string, number>
  /**
   * Reihenwerte im Bereich, die laut Datenblatt fehlen – nur die Sofort-Schätzung: sobald die Vorschau zur Auswahl passt,
   * zeigt die Seite `SeriesPreview.skipped_total`/`skipped_by_size` des Backends
   */
  skipped: number
  /** Wertebereich der Serie für die gewählten Baugrößen (Basiseinheit) */
  domain: [number, number] | null
  /** lieferbare Werte im ganzen Wertebereich (Werteskala unter dem Regler) */
  candidates: number[]
  /** Reihen, nach denen gezählt wurde */
  series: ESeriesName[]
}

const EMPTY = (mode: TemplateMode): Estimate => ({
  mode,
  parts: 0,
  jumpers: 0,
  total: 0,
  invalid: 0,
  values: 0,
  sizes: 0,
  perSize: {},
  perVoltage: {},
  skipped: 0,
  domain: null,
  candidates: [],
  series: [],
})

const REL = 1e-9
const inRange = (v: number, lo: number | null, hi: number | null) =>
  (lo === null || v >= lo * (1 - REL)) && (hi === null || v <= hi * (1 + REL))
const close = (a: number, b: number, rel = 1e-9) => Math.abs(a - b) <= rel * Math.max(Math.abs(a), Math.abs(b))

/** Bereich für Vorlagen ohne Wertebereiche */
function openDomain(unit: string): [number, number] {
  if (unit === 'F') return [1e-12, 100e-6]
  if (unit === 'H') return [1e-9, 1e-3]
  return [1, 10e6]
}

// --------------------------------------------------------------------------- Regeln

interface CompiledRule {
  sizes: Set<string>
  when: [string, Set<string>][]
  ranges: [number, number][]
  series: string[]
  tcr: number | null
  hasTcr: boolean
}

const compiledRules = new WeakMap<TemplateRule[], CompiledRule[]>()

function compileRules(rules: TemplateRule[]): CompiledRule[] {
  const cached = compiledRules.get(rules)
  if (cached) return cached
  const out = rules.map((r) => ({
    sizes: new Set(r.sizes),
    when: Object.entries(r.when).map(([k, v]) => [k, new Set(v.map((c) => c.toUpperCase()))] as [string, Set<string>]),
    ranges: r.ranges
      .map(([a, b]) => [parseAmount(a), parseAmount(b)] as [number | null, number | null])
      .filter((x): x is [number, number] => x[0] !== null && x[1] !== null),
    series: r.series.map((s) => s.toUpperCase()),
    tcr: r.attrs?.tcr ? tcrMagnitude(r.attrs.tcr) : null,
    hasTcr: Boolean(r.attrs?.tcr),
  }))
  compiledRules.set(rules, out)
  return out
}

/** Codes, die die Auswahl festlegt (wie `_fixed_codes`) */
function fixedCodes(t: SeriesTemplate, s: SeriesSettings, size: string): Record<string, string> {
  const fixed: Record<string, string> = {}
  const tol = effectiveTolerance(t, s.tolerance)
  if (tol) fixed.tolerance = tol.toUpperCase()
  const tcr = tcrChoices(t)
  if (tcr?.kind === 'code' && s.tcr) fixed.tcr = s.tcr.toUpperCase()
  const pack = packagingVariable(t)
  if (pack && s.packaging) {
    const o = findOptionByCode(pack, s.packaging, size)
    if (o && optionApplies(o, size)) fixed[pack.name] = o.code.toUpperCase()
  }
  return fixed
}

function whenFits(r: CompiledRule, fixed: Record<string, string>): boolean {
  return r.when.every(([name, codes]) => !(name in fixed) || codes.has(fixed[name]))
}

function matchRule(
  rules: CompiledRule[],
  size: string,
  value: number,
  fixed: Record<string, string>,
  tcrFilter: number | null,
): boolean {
  for (const r of rules) {
    if (r.sizes.size && !r.sizes.has(size)) continue
    if (!whenFits(r, fixed)) continue
    if (r.ranges.length && !r.ranges.some(([lo, hi]) => value >= lo * (1 - REL) && value <= hi * (1 + REL))) continue
    if (r.series.length && !inSeries(value, r.series)) continue
    if (tcrFilter !== null && !(r.tcr !== null && close(Math.abs(r.tcr), Math.abs(tcrFilter), 1e-6))) continue
    return true
  }
  return false
}

/** Wertebereich der Regeln, die zur Auswahl passen (sonst bzw. mit `all` aller Regeln der Baugröße) */
function ruleDomain(rules: CompiledRule[], size: string, fixed: Record<string, string>, all = false): [number, number] | null {
  const span = (filter: (r: CompiledRule) => boolean): [number, number] | null => {
    let lo = Infinity
    let hi = -Infinity
    for (const r of rules) {
      if (r.sizes.size && !r.sizes.has(size)) continue
      if (!filter(r)) continue
      for (const [a, b] of r.ranges) {
        lo = Math.min(lo, a)
        hi = Math.max(hi, b)
      }
    }
    return Number.isFinite(lo) ? [lo, hi] : null
  }
  if (all) return span(() => true)
  return span((r) => whenFits(r, fixed)) ?? span(() => true)
}

export interface RuleBasis {
  domain: [number, number] | null
  /** lieferbare Werte je Baugröße im ganzen Bereich */
  bySize: Map<string, number[]>
  /**
   * Wertebereich **aller** Regeln je Baugröße (wie series.py `_rule_span`): ohne gesendete Grenze probiert das Backend
   * jeden Reihenwert darin – was davon nicht lieferbar ist, meldet es als „ausgelassen“. Nur für die Sofort-Schätzung
   * von `skipped`, bis die Antwort des Backends (`skipped_by_size`) da ist.
   */
  spanAll: Map<string, [number, number]>
}

/** Grundlage der Regel-Vorlagen – unabhängig vom eingestellten Bereich (Regler ziehen bleibt schnell) */
export function ruleBasis(t: SeriesTemplate, s: SeriesSettings): RuleBasis {
  const mode = templateMode(t)
  const rules = compileRules(t.rules)
  const series = effectiveSeries(t, s)
  const tcr = tcrChoices(t)
  const tcrFilter = tcr?.kind === 'filter' && s.tcr ? tcrMagnitude(s.tcr) : null
  const bySize = new Map<string, number[]>()
  const spanAll = new Map<string, [number, number]>()
  let lo = Infinity
  let hi = -Infinity
  const domains = new Map<string, [number, number]>()
  for (const size of s.sizes) {
    const d = mode === 'open' ? openDomain(t.value_unit) : ruleDomain(rules, size, fixedCodes(t, s, size))
    if (!d) continue
    domains.set(size, d)
    lo = Math.min(lo, d[0])
    hi = Math.max(hi, d[1])
    if (mode !== 'open') {
      const all = ruleDomain(rules, size, {}, true)
      if (all) spanAll.set(size, all)
    }
  }
  if (!Number.isFinite(lo)) return { domain: null, bySize, spanAll }
  for (const [size, d] of domains) {
    const fixed = fixedCodes(t, s, size)
    const values = seriesValues(series, d[0], d[1])
    bySize.set(size, mode === 'open' ? values : values.filter((v) => matchRule(rules, size, v, fixed, tcrFilter)))
  }
  return { domain: [lo, hi], bySize, spanAll }
}

function jumperSizes(t: SeriesTemplate, s: SeriesSettings): string[] {
  if (!t.jumper || t.kind === 'catalog' || !s.includeJumper) return []
  const allowed = t.jumper.sizes
  return s.sizes.filter((size) => !allowed.length || allowed.includes(size))
}

function finish(e: Estimate, perSizeValues: Map<string, number[]>): Estimate {
  const distinct = new Set<number>()
  for (const [size, values] of perSizeValues) {
    e.perSize[size] = (e.perSize[size] ?? 0) + values.length
    for (const v of values) distinct.add(v)
  }
  e.parts = [...perSizeValues.values()].reduce((n, v) => n + v.length, 0)
  e.values = distinct.size
  e.sizes = Object.values(e.perSize).filter((n) => n > 0).length
  e.total = e.parts + e.jumpers
  return e
}

function estimateRules(t: SeriesTemplate, s: SeriesSettings, basis: RuleBasis): Estimate {
  const e = EMPTY(templateMode(t))
  e.domain = basis.domain
  e.series = effectiveSeries(t, s)
  const rules = compileRules(t.rules)
  const tcr = tcrChoices(t)
  const tcrFilter = tcr?.kind === 'filter' && s.tcr ? tcrMagnitude(s.tcr) : null
  const perSize = new Map<string, number[]>()
  const candidates = new Set<number>()
  for (const values of basis.bySize.values()) for (const v of values) candidates.add(v)
  e.candidates = [...candidates].sort((a, b) => a - b)
  const jumpers = new Set(jumperSizes(t, s))
  if (s.valueMode === 'list') {
    const values = listValues(parsedValues(t, s))
    for (const size of s.sizes) {
      const fixed = fixedCodes(t, s, size)
      const ok: number[] = []
      for (const v of values) {
        if (v === 0) {
          const allowed = !t.jumper?.sizes.length || t.jumper.sizes.includes(size)
          if (t.jumper && allowed) jumpers.add(size)
          else e.invalid += 1
          continue
        }
        if (templateMode(t) === 'open' || matchRule(rules, size, v, fixed, tcrFilter)) ok.push(v)
        else e.invalid += 1
      }
      perSize.set(size, ok)
    }
  } else {
    const lo = s.rangeMin
    const hi = s.rangeMax
    // Grenzen auf dem Rand schickt die Anfrage nicht mit (settings.ts `buildRequest`) – dann probiert das Backend
    // den Bereich aller Regeln der Baugröße und zählt jeden nicht lieferbaren Reihenwert als „ausgelassen“
    const dom = basis.domain
    const sentLo = lo !== null && !(dom && lo <= dom[0] * (1 + REL)) ? lo : null
    const sentHi = hi !== null && !(dom && hi >= dom[1] * (1 - REL)) ? hi : null
    for (const [size, values] of basis.bySize) {
      const ok = values.filter((v) => inRange(v, lo, hi))
      perSize.set(size, ok)
      const span = basis.spanAll.get(size)
      const low = sentLo ?? span?.[0]
      const high = sentHi ?? span?.[1]
      if (low === undefined || high === undefined || !(high > 0)) continue
      const tried = seriesValues(e.series, Math.max(low, 1e-12), high).length
      e.skipped += Math.max(0, tried - ok.length)
    }
  }
  e.jumpers = jumpers.size
  for (const size of jumpers) e.perSize[size] = (e.perSize[size] ?? 0) + 1
  return finish(e, perSize)
}

// --------------------------------------------------------------------------- Matrix

function estimateMatrix(t: SeriesTemplate, s: SeriesSettings): Estimate {
  const e = EMPTY('matrix')
  const series = effectiveSeries(t, s)
  e.series = series
  const tolVar = variable(t, 'tolerance')
  const tol = tolVar ? (s.tolerance ?? defaultOption(tolVar)?.code ?? null) : null
  const wantedVoltages = new Set(s.voltages.map((v) => v.toUpperCase()))
  const list = s.valueMode === 'list' ? listValues(parsedValues(t, s)) : null
  const perSize = new Map<string, number[]>()
  const candidates = new Set<number>()
  let lo = Infinity
  let hi = -Infinity
  const sizes = new Set(s.sizes)
  const cells: { size: string; value: number; voltage: string; tolOk: boolean }[] = []
  for (const cell of t.availability) {
    if (!sizes.has(cell.size)) continue
    const value = cellValue(t, cell)
    if (value === null) continue
    const tolOk = !tol || !cell.tolerances.length || cell.tolerances.some((c) => c.toUpperCase() === tol.toUpperCase())
    cells.push({ size: cell.size, value, voltage: (cell.codes.voltage ?? '').toUpperCase(), tolOk })
  }
  for (const c of cells) {
    if (wantedVoltages.size && !wantedVoltages.has(c.voltage)) continue
    lo = Math.min(lo, c.value)
    hi = Math.max(hi, c.value)
  }
  e.domain = Number.isFinite(lo) ? [lo, hi] : null
  const seriesOk = (v: number) => !series.length || inSeries(v, series)
  for (const c of cells) {
    const voltageOk = !wantedVoltages.size || wantedVoltages.has(c.voltage)
    const valueOk = list ? list.some((v) => close(v, c.value)) : inRange(c.value, s.rangeMin, s.rangeMax) && seriesOk(c.value)
    if (valueOk && c.tolOk) e.perVoltage[c.voltage] = (e.perVoltage[c.voltage] ?? 0) + 1
    if (!voltageOk) continue
    if (c.tolOk && seriesOk(c.value)) candidates.add(c.value)
    if (!valueOk) continue
    if (!c.tolOk) {
      if (list) e.invalid += 1
      else e.skipped += 1
      continue
    }
    const arr = perSize.get(c.size) ?? []
    arr.push(c.value)
    perSize.set(c.size, arr)
  }
  if (list) {
    // Werte der Liste, die es in einer Baugröße gar nicht gibt, erscheinen als „ungültig“
    for (const size of s.sizes) {
      const have = cells.filter((c) => c.size === size && (!wantedVoltages.size || wantedVoltages.has(c.voltage)))
      for (const v of list) if (v > 0 && !have.some((c) => close(c.value, v))) e.invalid += 1
    }
  }
  e.candidates = [...candidates].sort((a, b) => a - b)
  return finish(e, perSize)
}

// --------------------------------------------------------------------------- Katalog

function estimateCatalog(t: SeriesTemplate, s: SeriesSettings): Estimate {
  const e = EMPTY('catalog')
  const series = s.series === 'auto' ? [] : effectiveSeries(t, s)
  e.series = series
  const wantedTol = s.tolerance ? normTolerance(s.tolerance) : null
  const volts = s.voltages.map((v) => parseAmount(v)).filter((v): v is number => v !== null)
  const list = s.valueMode === 'list' ? listValues(parsedValues(t, s)) : null
  const sizes = new Set(s.sizes)
  const perSize = new Map<string, number[]>()
  const candidates = new Set<number>()
  let lo = Infinity
  let hi = -Infinity
  for (const entry of t.catalog) {
    if (!sizes.has(entry.size)) continue
    const value = catalogValue(entry)
    if (value === null) continue
    const tolText = catalogTolerance(t, entry)
    if (wantedTol !== null && normTolerance(tolText ?? '') !== wantedTol) continue
    const v = parseAmount(entry.attrs.voltage)
    const voltageKey = entry.attrs.voltage ?? ''
    const valueOk = list ? list.some((x) => close(x, value)) : inRange(value, s.rangeMin, s.rangeMax) && (!series.length || inSeries(value, series))
    if (valueOk && voltageKey) e.perVoltage[voltageKey] = (e.perVoltage[voltageKey] ?? 0) + 1
    if (volts.length && (v === null || !volts.some((w) => close(w, v, 1e-6)))) continue
    lo = Math.min(lo, value)
    hi = Math.max(hi, value)
    if (!series.length || inSeries(value, series)) candidates.add(value)
    if (!valueOk) continue
    const arr = perSize.get(entry.size) ?? []
    arr.push(value)
    perSize.set(entry.size, arr)
  }
  e.domain = Number.isFinite(lo) ? [lo, hi] : null
  e.candidates = [...candidates].sort((a, b) => a - b)
  return finish(e, perSize)
}

// --------------------------------------------------------------------------- Einstieg

/** Wertebereich der Serie für die gewählten Baugrößen (unabhängig vom eingestellten Bereich) */
export function seriesDomain(t: SeriesTemplate, s: SeriesSettings, basis: RuleBasis | null): [number, number] | null {
  const mode = templateMode(t)
  if (!s.sizes.length) return null
  if (mode === 'matrix' || mode === 'catalog') {
    const free = { ...s, rangeMin: null, rangeMax: null, valueMode: 'range' as const }
    return (mode === 'matrix' ? estimateMatrix(t, free) : estimateCatalog(t, free)).domain
  }
  return (basis ?? ruleBasis(t, s)).domain
}

/** Bereichsgrenzen außerhalb des Wertebereichs (z. B. nach Wechsel der Baugrößen) fallen auf die Serie zurück */
export function withRange(s: SeriesSettings, domain: [number, number] | null): SeriesSettings {
  if (!domain) return s
  const inside = (v: number | null) => (v !== null && v >= domain[0] * (1 - REL) && v <= domain[1] * (1 + REL) ? v : null)
  let lo = inside(s.rangeMin)
  let hi = inside(s.rangeMax)
  if (lo !== null && hi !== null && lo > hi) {
    lo = null
    hi = null
  }
  return lo === s.rangeMin && hi === s.rangeMax ? s : { ...s, rangeMin: lo, rangeMax: hi }
}

/**
 * Zähler für die Auswahl. `basis` (aus {@link ruleBasis}) nur bei Regel-Vorlagen – getrennt berechnet, damit das
 * Ziehen am Bereichsregler nicht alle Reihenwerte neu prüft.
 */
export function estimateSeries(t: SeriesTemplate, s: SeriesSettings, basis: RuleBasis | null): Estimate {
  const mode = templateMode(t)
  if (!s.sizes.length) return EMPTY(mode)
  if (mode === 'matrix') return estimateMatrix(t, s)
  if (mode === 'catalog') return estimateCatalog(t, s)
  return estimateRules(t, s, basis ?? ruleBasis(t, s))
}
