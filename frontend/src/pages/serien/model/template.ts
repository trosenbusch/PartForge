/**
 * Auswertung einer Serienvorlage für die Oberfläche: Art (Regeln, Matrix, Katalog), Varianten (Toleranz, TK,
 * Spannung, Verpackung), Baugrößen mit Kennwerten, Muster-Segmente. Spiegelt die Regeln von
 * partforge/domain/mpn (engine.py, series.py `_selection`) – nur lesend, das Backend bleibt maßgeblich.
 */
import type {
  CatalogEntry,
  SeriesTemplate,
  SeriesTemplateSummary,
  TemplateOption,
  TemplateSize,
  TemplateVariable,
  ValueFormat,
} from '@/api/series'
import { formatQuantityText } from '@/components/grid/cellFormat'
import type { ESeriesName } from '@/lib/units'
import { SERIES_NAMES, decodeValueCode, parseAmount } from './values'

/** Wie die Vorlage festlegt, welche Bauteile es gibt */
export type TemplateMode = 'rules' | 'matrix' | 'catalog' | 'open'

export function templateMode(t: Pick<SeriesTemplate, 'kind' | 'rules' | 'availability_count'>): TemplateMode {
  if (t.kind === 'catalog') return 'catalog'
  if (t.availability_count > 0) return 'matrix'
  if (t.rules.length > 0) return 'rules'
  return 'open'
}

/** Matrix-Vorlagen brauchen die volle Vorlage (Lieferbarkeitsmatrix) für exakte Zähler */
export const needsFullTemplate = (s: Pick<SeriesTemplateSummary, 'availability_count'>): boolean =>
  (s.availability_count ?? 0) > 0

export function variable(t: SeriesTemplate, name: string): TemplateVariable | undefined {
  return t.variables.find((v) => v.name === name)
}

export const isJumperOnly = (o: TemplateOption): boolean => Boolean(o.attrs?.jumper_only)

export const optionApplies = (o: TemplateOption, size: string | null): boolean =>
  !o.sizes.length || size === null || o.sizes.includes(size)

/** Text einer Option für die Oberfläche: Beschriftung, sonst Bedeutung, sonst Code */
export function optionText(o: TemplateOption): string {
  return o.label || (o.value ? formatQuantityText(o.value) : '') || o.code || 'ohne'
}

/** Vorauswahl einer Variable (je Baugröße, `default`, sonst die erste gültige) – ohne `requires` */
export function defaultOption(v: TemplateVariable, size: string | null = null): TemplateOption | undefined {
  const applicable = v.options.filter((o) => optionApplies(o, size) && !isJumperOnly(o))
  const perSize = size !== null ? v.defaults[size] : undefined
  if (perSize) {
    const hit = applicable.find((o) => o.code.toUpperCase() === perSize.toUpperCase())
    if (hit) return hit
  }
  return applicable.find((o) => o.default) ?? applicable[0]
}

export function findOptionByCode(v: TemplateVariable, code: string, size: string | null = null): TemplateOption | undefined {
  const wanted = code.toUpperCase()
  const hits = v.options.filter((o) => o.code.toUpperCase() === wanted)
  return hits.find((o) => optionApplies(o, size)) ?? hits[0]
}

// --------------------------------------------------------------------------- Baugrößen

export interface SizeInfo {
  size: string
  /** „0603 (1608)“ */
  label: string
  metric: string | null
  power: string | null
  voltage: string | null
  height: string | null
  /** Abmessungen (Katalog-Drosseln) */
  dimensions: string | null
}

export function sizeNames(t: SeriesTemplate): string[] {
  if (t.sizes.length) return t.sizes.map((s) => s.size)
  if (t.kind === 'catalog') return [...new Set(t.catalog.map((e) => e.size))]
  const v = variable(t, 'size')
  return v ? v.options.map((o) => o.value || o.code) : []
}

export function sizeSpec(t: SeriesTemplate, size: string): TemplateSize | undefined {
  return t.sizes.find((s) => s.size === size)
}

export function sizeInfo(t: SeriesTemplate, size: string): SizeInfo {
  const spec = sizeSpec(t, size)
  const attrs = { ...t.attrs, ...(spec?.attrs ?? {}) }
  return {
    size,
    label: spec?.label || size,
    metric: attrs.metric || null,
    power: attrs.power || null,
    voltage: attrs.voltage || null,
    height: attrs.height || null,
    dimensions: attrs.dimensions || null,
  }
}

/** Vorauswahl der Baugrößen: die gängigen 0402 … 1206, sonst alle (höchstens vier) */
export function defaultSizes(t: SeriesTemplate): string[] {
  const all = sizeNames(t)
  const common = ['0402', '0603', '0805', '1206'].filter((s) => all.includes(s))
  if (common.length >= 2) return common
  return all.slice(0, Math.min(4, all.length))
}

// --------------------------------------------------------------------------- Varianten

export interface ChoiceOption {
  /** Wert für die Anfrage (Code bzw. Text) */
  value: string
  label: string
  description?: string
}

/** Toleranzen: Codes der Variable (ohne Brücken-Code) bzw. Toleranzen im Katalog */
export function toleranceChoices(t: SeriesTemplate): ChoiceOption[] {
  const v = variable(t, 'tolerance')
  if (t.kind === 'catalog') {
    const seen = new Map<string, string>()
    for (const e of t.catalog) {
      const text = catalogTolerance(t, e)
      if (text) seen.set(normTolerance(text), text)
    }
    return [...seen.values()]
      .sort((a, b) => (parseAmount(a.replace('±', '')) ?? 0) - (parseAmount(b.replace('±', '')) ?? 0))
      .map((text) => ({ value: text, label: formatQuantityText(text) }))
  }
  if (!v) return []
  return v.options.filter((o) => !isJumperOnly(o)).map((o) => ({ value: o.code, label: optionText(o) }))
}

export const normTolerance = (text: string): string => text.replace(/[±\s%]/g, '').trim()

/** Toleranz eines Katalogeintrags (Attribut oder Code) */
export function catalogTolerance(t: SeriesTemplate, e: CatalogEntry): string | null {
  if (e.attrs.tolerance) return e.attrs.tolerance
  const v = variable(t, 'tolerance')
  const code = e.codes.tolerance
  if (v && code) return findOptionByCode(v, code)?.value ?? null
  return null
}

/** Code der Toleranz, die ohne Auswahl gilt (Muster-Vorlagen) */
export function effectiveTolerance(t: SeriesTemplate, chosen: string | null): string | null {
  if (t.kind === 'catalog') return chosen
  const v = variable(t, 'tolerance')
  if (!v) return null
  if (chosen) return chosen
  return defaultOption(v)?.code ?? null
}

/** E-Reihen laut Datenblatt für eine Toleranz (Option-Attribut `eseries`, z. B. „E24+E96“) */
export function toleranceSeries(t: SeriesTemplate, toleranceCode: string | null): ESeriesName[] {
  const v = variable(t, 'tolerance')
  if (!v || !toleranceCode) return []
  const o = findOptionByCode(v, toleranceCode)
  return parseSeriesList(o?.attrs?.eseries ?? '')
}

export function parseSeriesList(text: string): ESeriesName[] {
  const out: ESeriesName[] = []
  for (const part of text.split(/[\s,;+/]+/)) {
    let name = part.trim().toUpperCase()
    if (!name) continue
    if (!name.startsWith('E')) name = `E${name}`
    if ((SERIES_NAMES as string[]).includes(name) && !out.includes(name as ESeriesName)) out.push(name as ESeriesName)
  }
  return out
}

const TCR_RE = /^[+]?(\d+(?:[.,]\d+)?)\s*ppm(?:\/K)?$/i

/** Betrag eines TK-Texts („±100ppm/K“ → 100); Bereiche („-100 … +350ppm/K“) → null */
export function tcrMagnitude(text: string): number | null {
  const m = text.replace('±', '').trim().match(TCR_RE)
  return m ? Number(m[1].replace(',', '.')) : null
}

/** TK-Auswahl: Codes der Variable, sonst die eindeutigen TK-Werte der Regeln (als Filter) */
export function tcrChoices(t: SeriesTemplate): { kind: 'code' | 'filter'; options: ChoiceOption[] } | null {
  const v = variable(t, 'tcr')
  if (v) {
    const options = v.options.filter((o) => !isJumperOnly(o)).map((o) => ({ value: o.code, label: optionText(o) }))
    return options.length > 1 ? { kind: 'code', options } : null
  }
  if (t.kind === 'catalog' || !t.rules.length) return null
  const values = new Map<number, string>()
  for (const r of t.rules) {
    const text = r.attrs?.tcr
    const mag = text ? tcrMagnitude(text) : null
    if (text && mag !== null && !values.has(mag)) values.set(mag, text)
  }
  if (values.size < 2) return null
  return {
    kind: 'filter',
    options: [...values.entries()].sort((a, b) => a[0] - b[0]).map(([, text]) => ({ value: text, label: formatQuantityText(text) })),
  }
}

/** Verpackungs-Variable (wie series.py `_packaging_var`) */
export function packagingVariable(t: SeriesTemplate): TemplateVariable | undefined {
  if (t.kind === 'catalog') return undefined
  return ['packaging', 'cspec', 'packing'].map((n) => variable(t, n)).find(Boolean)
}

export interface PackagingChoice extends ChoiceOption {
  /** gilt nur für diese der gewählten Baugrößen (leer = alle) */
  sizes: string[]
}

/** Verpackungen, die für mindestens eine gewählte Baugröße gelten */
export function packagingChoices(t: SeriesTemplate, sizes: string[]): PackagingChoice[] {
  const v = packagingVariable(t)
  if (!v) return []
  // ein Code kann je Baugröße eigene Einträge haben – die Baugrößen aller Einträge zusammenfassen
  const byCode = new Map<string, { value: string; label: string; fits: Set<string> }>()
  for (const o of v.options) {
    if (isJumperOnly(o)) continue
    const fits = sizes.filter((s) => optionApplies(o, s))
    if (!fits.length) continue
    const key = o.code.toUpperCase()
    const entry = byCode.get(key) ?? { value: o.code, label: optionText(o), fits: new Set<string>() }
    for (const s of fits) entry.fits.add(s)
    byCode.set(key, entry)
  }
  return [...byCode.values()].map((e) => ({
    value: e.value,
    label: e.label,
    sizes: e.fits.size >= sizes.length ? [] : sizes.filter((s) => e.fits.has(s)),
  }))
}

export interface VoltageChoice extends ChoiceOption {
  volts: number
}

/** Nennspannungen (Matrix: Codes der Variable, die in den Zellen vorkommen; Katalog: Texte) */
export function voltageChoices(t: SeriesTemplate): VoltageChoice[] {
  const v = variable(t, 'voltage')
  if (t.kind === 'catalog') {
    const seen = new Map<number, string>()
    for (const e of t.catalog) {
      const text = e.attrs.voltage
      const volts = text ? parseAmount(text) : null
      if (text && volts !== null && !seen.has(volts)) seen.set(volts, text)
    }
    return [...seen.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([volts, text]) => ({ value: text, label: formatQuantityText(text), volts }))
  }
  if (!v || !t.availability_keys.includes('voltage')) return []
  const used = new Set(t.availability.map((c) => (c.codes.voltage ?? '').toUpperCase()))
  return v.options
    .filter((o) => !t.availability.length || used.has(o.code.toUpperCase()))
    .map((o) => ({ value: o.code, label: optionText(o), volts: parseAmount(o.value ?? '') ?? 0 }))
    .sort((a, b) => a.volts - b.volts)
}

/** Dielektrikum (nur Anzeige – die Serie verwendet die Vorgabe der Vorlage) */
export function dielectricText(t: SeriesTemplate): string | null {
  const v = variable(t, 'dielectric')
  if (v) {
    const values = [...new Set(v.options.map((o) => o.value || o.code).filter(Boolean))]
    return values.length ? values.join(', ') : null
  }
  if (t.kind === 'catalog') {
    const values = [...new Set(t.catalog.map((e) => e.attrs.dielectric).filter(Boolean))]
    return values.length ? values.join(', ') : null
  }
  return t.attrs.dielectric || null
}

// --------------------------------------------------------------------------- Werte

/** Werteformat (inkl. abweichender Formate für bestimmte Codes) */
export function valueFormat(t: SeriesTemplate, codes: Record<string, string> = {}): ValueFormat | null {
  const v = variable(t, 'value')
  if (!v?.format) return null
  const upper = Object.fromEntries(Object.entries(codes).map(([k, c]) => [k, String(c).toUpperCase()]))
  for (const o of v.format_overrides ?? []) {
    const ok = Object.entries(o.when).every(([name, allowed]) => allowed.map((a) => a.toUpperCase()).includes(upper[name] ?? ''))
    if (ok) return o.format as ValueFormat
  }
  return v.format
}

/** Wert einer Matrixzelle (Basiseinheit) */
export function cellValue(t: SeriesTemplate, cell: SeriesTemplate['availability'][number]): number | null {
  const fmt = valueFormat(t, cell.codes)
  return fmt ? decodeValueCode(cell.value, fmt) : null
}

/** Wert eines Katalogeintrags (Basiseinheit) */
export function catalogValue(e: CatalogEntry): number | null {
  return parseAmount(e.value)
}

/** Bezeichnung des Werts einer Vorlage (Ferrite: Impedanz) */
export function valueLabelFor(t: Pick<SeriesTemplate, 'category' | 'value_unit'>): string {
  return t.category === 'Ferrite Beads' ? 'Impedanz' : valueLabel(t.value_unit)
}

/** Überschrift des Werte-Abschnitts: „Widerstandswerte“, „Kapazitätswerte“ … */
export function valuesTitle(t: Pick<SeriesTemplate, 'category' | 'value_unit'>): string {
  const label = valueLabelFor(t)
  return label === 'Wert' ? 'Werte' : `${label}swerte`
}

export function valueLabel(unit: string): string {
  if (unit === 'F') return 'Kapazität'
  if (unit === 'H') return 'Induktivität'
  if (unit === 'Ω') return 'Widerstand'
  return 'Wert'
}

/** Beispielwert für Vorlagenkarten */
export function exampleValue(unit: string): number {
  if (unit === 'F') return 100e-9
  if (unit === 'H') return 10e-6
  return 10e3
}

// --------------------------------------------------------------------------- Muster

export interface PatternSegment {
  literal?: string
  variable?: string
}

/** „CRCW{size}{value}“ → Literale und Platzhalter (wie model.py `parse_pattern`) */
export function parsePattern(pattern: string | null | undefined): PatternSegment[] {
  if (!pattern) return []
  const out: PatternSegment[] = []
  const re = /\{([^{}]*)\}/g
  let pos = 0
  for (const m of pattern.matchAll(re)) {
    const start = m.index ?? 0
    if (start > pos) out.push({ literal: pattern.slice(pos, start) })
    out.push({ variable: m[1].trim() })
    pos = start + m[0].length
  }
  if (pos < pattern.length) out.push({ literal: pattern.slice(pos) })
  return out
}

/** Gemeinsamer Anfang aller Teilenummern der Serie (für den Tabellenfilter „beginnt mit“) */
export function mpnPrefix(t: Pick<SeriesTemplate, 'pattern' | 'catalog'>): string {
  const segments = parsePattern(t.pattern)
  if (segments.length && segments[0].literal) return segments[0].literal
  if (!t.pattern && t.catalog.length) {
    let prefix = t.catalog[0].mpn
    for (const e of t.catalog) {
      let i = 0
      while (i < prefix.length && i < e.mpn.length && prefix[i] === e.mpn[i]) i++
      prefix = prefix.slice(0, i)
      if (!prefix) break
    }
    return prefix
  }
  return ''
}

/** Kurzbeschreibung der Gültigkeit (für Karten): „E24/E96 · 1 Ω … 10 MΩ“ */
export function ruleSeries(t: SeriesTemplate): ESeriesName[] {
  const out = new Set<ESeriesName>()
  for (const r of t.rules) for (const s of parseSeriesList(r.series.join('+'))) out.add(s)
  return SERIES_NAMES.filter((s) => out.has(s))
}

/** Wertebereich aller Regeln (Basiseinheit) */
export function ruleSpan(t: SeriesTemplate, sizes?: string[]): [number, number] | null {
  let lo = Infinity
  let hi = -Infinity
  for (const r of t.rules) {
    if (sizes && r.sizes.length && !r.sizes.some((s) => sizes.includes(s))) continue
    for (const [a, b] of r.ranges) {
      const x = parseAmount(a)
      const y = parseAmount(b)
      if (x !== null) lo = Math.min(lo, x)
      if (y !== null) hi = Math.max(hi, y)
    }
  }
  return Number.isFinite(lo) && Number.isFinite(hi) ? [lo, hi] : null
}
