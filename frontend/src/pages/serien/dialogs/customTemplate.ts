/**
 * Eigene Serienvorlage als Formular-Entwurf ↔ `MpnTemplate` des Backends (partforge/domain/mpn/model.py).
 * Der Entwurf kennt nur Muster-Vorlagen mit einer Gültigkeitsregel für alle Baugrößen – genug für die meisten
 * Hersteller-Serien; Matrizen und Kataloge bleiben den eingebauten Vorlagen vorbehalten.
 */
import type { MpnTemplateInput, SeriesTemplate, ValueStyle } from '@/api/series'
import type { ESeriesName } from '@/lib/units'
import { unitFor } from '../model/categories'
import { parsePattern, valueLabel } from '../model/template'
import { SERIES_NAMES } from '../model/values'

export interface DraftOption {
  key: string
  code: string
  /** Bedeutung als Feldtext („±1%“, „50V“, „X7R“) */
  value: string
  label: string
  isDefault: boolean
}

export interface DraftVariable {
  name: string
  label: string
  options: DraftOption[]
}

export interface DraftSize {
  size: string
  /** Code im Muster (leer = Baugröße) */
  code: string
  power: string
  voltage: string
  height: string
}

export interface TemplateDraft {
  id: string
  idTouched: boolean
  category: string
  manufacturer: string
  series: string
  title: string
  titleTouched: boolean
  description: string
  datasheetUrl: string
  pattern: string
  valueStyle: ValueStyle
  /** Wert einer Code-Einheit in Basiseinheiten (pF = 1e-12) */
  valueScale: number
  /** nur uniohm4: 2 oder 3 Stellen */
  valueDigits: 2 | 3
  sizes: DraftSize[]
  variables: DraftVariable[]
  rangeMin: string
  rangeMax: string
  eSeries: ESeriesName[]
  jumper: boolean
  jumperCode: string
  /** feste Codes der Brücke je Variable ('' = Vorgabe) */
  jumperCodes: Record<string, string>
  verified: boolean
  /**
   * Lieferbarkeit geprüft: Bereich und E-Reihen stimmen mit dem Datenblatt überein (`availability_certain`). Eigene
   * Bestätigung – die vorbelegten Standardwerte (1 … 10M, E24/E96) sind keine Prüfung.
   */
  availabilityChecked: boolean
  sourceTitle: string
  sourceUrl: string
  /**
   * Bearbeiten: die gespeicherte Vorlage. Was das Formular nicht abbildet (Codes nur für bestimmte Baugrößen,
   * Bedingungen, abweichende Werteformate, mehrere Regeln, Footprint-Hinweise …), bleibt daraus erhalten.
   */
  original: SeriesTemplate | null
}

/** EIA-Größen des Chip-Generators */
export const CHIP_SIZES = ['01005', '0201', '0402', '0603', '0805', '1008', '1206', '1210', '1808', '1812', '2010', '2220', '2512']

export const METRIC: Record<string, string> = {
  '01005': '0402',
  '0201': '0603',
  '0402': '1005',
  '0603': '1608',
  '0805': '2012',
  '1008': '2520',
  '1206': '3216',
  '1210': '3225',
  '1808': '4520',
  '1812': '4532',
  '2010': '5025',
  '2220': '5750',
  '2512': '6332',
}

export const VALUE_STYLES: { value: ValueStyle; label: string; example: (unit: string) => string; description: string }[] = [
  { value: 'rkm', label: 'RKM kurz', example: (u) => (u === 'Ω' ? '4K7 · 10K · 100R' : '4N7 · 100N'), description: 'Buchstabe als Komma, kürzeste Form' },
  { value: 'rkm4', label: 'RKM 3-stellig', example: () => '4K70 · 10K0 · 100R', description: 'Buchstabe als Komma, immer 3 Ziffern' },
  { value: 'eia3', label: 'EIA 3-stellig', example: () => '472 · 103 · 4R7', description: '2 Ziffern + Zahl der Nullen' },
  { value: 'eia4', label: 'EIA 4-stellig', example: () => '4701 · 1002 · 10R0', description: '3 Ziffern + Zahl der Nullen' },
  { value: 'uniohm4', label: 'UniOhm 4-stellig', example: () => '4701 · 100J', description: 'Multiplikator als Ziffer oder Buchstabe' },
]

/** Code-Einheiten je Werteinheit */
export const SCALES: Record<string, { value: number; label: string }[]> = {
  Ω: [
    { value: 1, label: 'Ω' },
    { value: 1e-3, label: 'mΩ' },
  ],
  F: [
    { value: 1e-12, label: 'pF' },
    { value: 1e-9, label: 'nF' },
    { value: 1e-6, label: 'µF' },
  ],
  H: [
    { value: 1e-9, label: 'nH' },
    { value: 1e-6, label: 'µH' },
  ],
}

let keyCounter = 0
export const optionKey = (): string => `o${++keyCounter}`

const opt = (code: string, value: string, label = '', isDefault = false): DraftOption => ({
  key: optionKey(),
  code,
  value,
  label,
  isDefault,
})

/** Bekannte Variablen mit Bezeichnung und Vorschlägen */
export function knownVariable(name: string, unit: string): DraftVariable | null {
  switch (name) {
    case 'tolerance':
      return {
        name,
        label: 'Toleranz',
        options:
          unit === 'F'
            ? [opt('K', '±10%', '', true), opt('M', '±20%'), opt('J', '±5%')]
            : unit === 'H'
              ? [opt('M', '±20%', '', true), opt('K', '±10%')]
              : [opt('F', '±1%', '', true), opt('J', '±5%')],
      }
    case 'tcr':
      return { name, label: 'Temperaturkoeffizient', options: [opt('K', '±100ppm/K', '', true), opt('N', '±200ppm/K')] }
    case 'voltage':
      return { name, label: 'Nennspannung', options: [opt('16', '16V'), opt('25', '25V'), opt('50', '50V', '', true)] }
    case 'dielectric':
      return { name, label: 'Dielektrikum', options: [opt('R', 'X7R', '', true)] }
    case 'packaging':
      return { name, label: 'Verpackung', options: [opt('T', '', 'Rolle 7"', true)] }
    case 'packing':
      return { name, label: 'Gurtart', options: [opt('R', '', 'Papiergurt', true)] }
    default:
      return null
  }
}

/** Platzhalter des Musters ohne Baugröße und Wert */
export function patternVariables(pattern: string): string[] {
  return parsePattern(pattern)
    .map((s) => s.variable)
    .filter((v): v is string => Boolean(v) && v !== 'size' && v !== 'value')
}

/** Variablen des Entwurfs an das Muster anpassen (neue anlegen, vorhandene behalten) */
export function syncVariables(draft: TemplateDraft): DraftVariable[] {
  const unit = unitFor(draft.category)
  const out = [...draft.variables]
  for (const name of patternVariables(draft.pattern)) {
    if (!/^[a-z][a-z0-9_]{0,31}$/.test(name)) continue
    if (out.some((v) => v.name === name)) continue
    out.push(knownVariable(name, unit) ?? { name, label: name, options: [opt('', '', '', true)] })
  }
  return out
}

export function slug(text: string): string {
  return text
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/ß/g, 'ss')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
}

export const autoId = (d: Pick<TemplateDraft, 'manufacturer' | 'series'>): string => {
  const s = slug(`${d.manufacturer} ${d.series}`)
  return s ? `eigen-${s}` : ''
}

export const autoTitle = (d: Pick<TemplateDraft, 'manufacturer' | 'series' | 'category'>): string =>
  [d.manufacturer.trim(), d.series.trim()].filter(Boolean).join(' ') || ''

/** Startentwurf je Kategorie (typische Muster, Codes und Bereiche) */
export function emptyDraft(category: string): TemplateDraft {
  const unit = unitFor(category)
  const base: TemplateDraft = {
    id: '',
    idTouched: false,
    category,
    manufacturer: '',
    series: '',
    title: '',
    titleTouched: false,
    description: '',
    datasheetUrl: '',
    pattern: 'ABC{size}{value}{tolerance}',
    valueStyle: 'rkm',
    valueScale: 1,
    valueDigits: 3,
    sizes: ['0402', '0603', '0805', '1206'].map((size) => ({ size, code: '', power: '', voltage: '', height: '' })),
    variables: [],
    rangeMin: '1',
    rangeMax: '10M',
    eSeries: ['E24', 'E96'],
    jumper: false,
    jumperCode: '0R',
    jumperCodes: {},
    verified: false,
    availabilityChecked: false,
    sourceTitle: '',
    sourceUrl: '',
    original: null,
  }
  if (unit === 'F') {
    Object.assign(base, {
      pattern: 'CAP{size}{value}{tolerance}{voltage}',
      valueStyle: 'eia3',
      valueScale: 1e-12,
      rangeMin: '10p',
      rangeMax: '10µ',
      eSeries: ['E6', 'E12'],
    })
  } else if (unit === 'H') {
    Object.assign(base, {
      pattern: 'IND{size}-{value}{tolerance}',
      valueStyle: 'eia3',
      valueScale: 1e-6,
      rangeMin: '1µ',
      rangeMax: '1m',
      eSeries: ['E6', 'E12'],
    })
  } else if (category === 'Ferrite Beads') {
    Object.assign(base, { pattern: 'FB{size}{value}', valueStyle: 'eia3', valueScale: 1, rangeMin: '10', rangeMax: '2.2k', eSeries: ['E6'] })
  }
  base.variables = syncVariables(base)
  return base
}

// --------------------------------------------------------------------------- Entwurf → Vorlage

const RESISTOR_FIELDS: Record<string, string> = {
  Resistance: '{value}',
  Tolerance: '{tolerance}',
  Power: '{power}',
  Voltage: '{voltage}',
  TCR: '{tcr}',
  Size: '{size}',
  Package: '{size}',
  Mounting: 'SMD',
  Height: '{height}',
}
const CAPACITOR_FIELDS: Record<string, string> = {
  Capacitance: '{value}',
  Voltage: '{voltage}',
  Tolerance: '{tolerance}',
  Dielectric: '{dielectric}',
  Type: 'MLCC',
  Polarized: 'Nein',
  Size: '{size}',
  Package: '{size}',
  Mounting: 'SMD',
  Height: '{height}',
}
const INDUCTOR_FIELDS: Record<string, string> = {
  Inductance: '{value}',
  Tolerance: '{tolerance}',
  'Current Rating': '{current}',
  Size: '{size}',
  Package: '{size}',
  Mounting: 'SMD',
  Height: '{height}',
}
const FERRITE_FIELDS: Record<string, string> = {
  Impedance: '{value}',
  'Current Rating': '{current}',
  Size: '{size}',
  Package: '{size}',
  Mounting: 'SMD',
  Height: '{height}',
}

export function fieldsFor(category: string): Record<string, string> {
  if (category === 'Capacitors') return CAPACITOR_FIELDS
  if (category === 'Inductors') return INDUCTOR_FIELDS
  if (category === 'Ferrite Beads') return FERRITE_FIELDS
  return RESISTOR_FIELDS
}

const sizeLabel = (size: string) => (METRIC[size] ? `${size} (${METRIC[size]} metrisch)` : size)

export function toTemplate(d: TemplateDraft): MpnTemplateInput {
  const unit = unitFor(d.category)
  const used = new Set(patternVariables(d.pattern))
  const variables: MpnTemplateInput['variables'] = [
    {
      name: 'size',
      label: 'Baugröße',
      options: d.sizes.map((s) => ({ code: s.code.trim() || s.size, value: s.size, label: sizeLabel(s.size), default: false })),
    },
    {
      name: 'value',
      label: valueLabel(unit),
      format: {
        style: d.valueStyle,
        scale: d.valueScale,
        ...(d.valueStyle === 'uniohm4' ? { digits: d.valueDigits } : {}),
      },
    },
    ...d.variables
      .filter((v) => used.has(v.name))
      .map((v) => ({
        name: v.name,
        label: v.label.trim() || v.name,
        options: v.options.map((o) => ({
          code: o.code.trim(),
          value: o.value.trim() || null,
          label: o.label.trim() || null,
          default: o.isDefault,
        })),
      })),
  ]
  const sizes = d.sizes.map((s) => {
    const attrs: Record<string, string> = {}
    if (METRIC[s.size]) attrs.metric = METRIC[s.size]
    if (s.power.trim()) attrs.power = s.power.trim()
    if (s.voltage.trim()) attrs.voltage = s.voltage.trim()
    if (s.height.trim()) attrs.height = s.height.trim()
    return { size: s.size, label: METRIC[s.size] ? `${s.size} (${METRIC[s.size]})` : s.size, attrs }
  })
  const hasRange = Boolean(d.rangeMin.trim() && d.rangeMax.trim())
  const rules =
    hasRange || d.eSeries.length
      ? [
          {
            sizes: [],
            when: {},
            ranges: hasRange ? ([[d.rangeMin.trim(), d.rangeMax.trim()]] as [string, string][]) : [],
            series: d.eSeries,
          },
        ]
      : []
  const jumperCodes = Object.fromEntries(
    Object.entries(d.jumperCodes).filter(([name, code]) => used.has(name) && code !== ''),
  )
  const title = d.title.trim() || autoTitle(d) || d.id
  const fresh: MpnTemplateInput = {
    id: d.id.trim(),
    manufacturer: d.manufacturer.trim(),
    series: d.series.trim(),
    category: d.category,
    title,
    description: d.description.trim(),
    datasheet_url: d.datasheetUrl.trim() || null,
    kind: 'pattern',
    pattern: d.pattern.trim(),
    value_unit: unit,
    variables,
    sizes,
    rules,
    jumper: d.jumper && unit === 'Ω' ? { value_code: d.jumperCode.trim(), codes: jumperCodes } : null,
    fields: fieldsFor(d.category),
    footprint: { family: 'chip' },
    sources: d.sourceTitle.trim() ? [{ title: d.sourceTitle.trim(), url: d.sourceUrl.trim() || null }] : [],
    verified: d.verified,
    // nur auf ausdrückliche Bestätigung – vorbelegte Bereiche sind keine Prüfung
    availability_certain: d.verified && d.availabilityChecked && rules.length > 0,
    builtin: false,
  }
  return d.original ? mergeOriginal(fresh, d.original) : fresh
}

// --------------------------------------------------------------------------- Pflichtfelder der Kategorie

/** Platzhalter, die jede Zeile hat (engine.py `base_attrs`, Größen-Attribut `metric`) */
const BASE_ATTRS = new Set(['value', 'size', 'mpn', 'manufacturer', 'series', 'metric'])
/** Platzhalter aus der Tabelle „Baugrößen“ */
export const SIZE_ATTRS = ['power', 'voltage', 'height'] as const
export type SizeAttr = (typeof SIZE_ATTRS)[number]

/** Pflichtfeld, das laut Vorlagentest (`/api/series/templates/test`, `missing_fields`) leer bliebe */
export interface RequiredGap {
  /** Spalte der Kategorie, z. B. „Power“ */
  column: string
  /** deutsche Bezeichnung, z. B. „Leistung“ */
  label: string
  /** Größen-Attribut, das das Feld füllt (Spalte der Tabelle „Baugrößen“) */
  sizeAttr: SizeAttr | null
  /** Baugrößen, bei denen das Feld leer bliebe */
  sizes: string[]
  /** was zu tun ist (deutsch) */
  hint: string
}

const PLACEHOLDER = /\{([a-z][a-z0-9_]*)\}/g

/** Welches Eingabefeld des Formulars die Spalte füllt (Feldzuordnung der Vorlage) – für Markierung und Hinweis */
export function columnSource(
  d: TemplateDraft,
  column: string,
): { kind: 'none' } | { kind: 'size'; attr: SizeAttr } | { kind: 'code'; name: string } | { kind: 'missing'; name: string } | { kind: 'fixed' } {
  const text = (d.original?.fields ?? fieldsFor(d.category))[column]
  if (text === undefined) return { kind: 'none' }
  const used = new Set(patternVariables(d.pattern))
  for (const [, name] of text.matchAll(PLACEHOLDER)) {
    if (BASE_ATTRS.has(name)) continue
    if ((SIZE_ATTRS as readonly string[]).includes(name)) return { kind: 'size', attr: name as SizeAttr }
    if (used.has(name)) return { kind: 'code', name }
    return { kind: 'missing', name }
  }
  return { kind: 'fixed' }
}

/**
 * Pflichtfelder, die laut Test des Backends leer blieben (je Spalte mit den betroffenen Baugrößen), mit dem Hinweis,
 * welches Eingabefeld sie füllt. Ob ein Feld fehlt, entscheidet allein das Backend (`missing_fields` je Beispiel –
 * dieselbe Prüfung wie die Vorschau der Serie, Brücken ohne die Felder, die für sie nicht gelten).
 */
export function requiredGaps(
  d: TemplateDraft,
  results: { sample: { size: string }; missing_fields: { column: string; label: string }[] }[],
): RequiredGap[] {
  const byColumn = new Map<string, { label: string; sizes: Set<string> }>()
  for (const r of results) {
    for (const f of r.missing_fields) {
      const entry = byColumn.get(f.column) ?? { label: f.label, sizes: new Set<string>() }
      entry.sizes.add(r.sample.size)
      byColumn.set(f.column, entry)
    }
  }
  const order = d.sizes.map((s) => s.size)
  return [...byColumn.entries()].map(([column, { label, sizes }]) => {
    const list = order.filter((size) => sizes.has(size))
    const source = columnSource(d, column)
    if (source.kind === 'size') {
      return {
        column,
        label,
        sizeAttr: source.attr,
        sizes: list,
        hint: `${label} je Baugröße angeben (${list.length === d.sizes.length ? 'alle' : list.join(', ')}).`,
      }
    }
    let hint: string
    if (source.kind === 'code') {
      const v = d.variables.find((x) => x.name === source.name)
      const empty = v ? v.options.filter((o) => !o.value.trim()) : []
      hint = empty.length
        ? `In der Codetabelle „${v?.label ?? source.name}“ fehlt die Bedeutung (z. B. ${source.name === 'tolerance' ? '±1%' : '50V'}) bei ${empty.length === 1 ? `Code „${empty[0].code || 'ohne'}“` : `${empty.length} Codes`}.`
        : `Bedeutungen in der Codetabelle „${v?.label ?? source.name}“ prüfen – ${label} lässt sich daraus nicht lesen.`
    } else if (source.kind === 'missing') {
      hint = `Platzhalter {${source.name}} ins Muster aufnehmen – sonst bleibt ${label} leer.`
    } else {
      hint = `${label} füllt diese Vorlage nicht – das Feld in den Einstellungen der Kategorie optional machen.`
    }
    return { column, label, sizeAttr: null, sizes: list, hint }
  })
}

/** Bearbeitete Felder über die gespeicherte Vorlage legen – Nicht-Abgebildetes bleibt erhalten */
function mergeOriginal(fresh: MpnTemplateInput, o: SeriesTemplate): MpnTemplateInput {
  const variables = (fresh.variables ?? []).map((v) => {
    const ov = o.variables.find((x) => x.name === v.name)
    if (!ov) return v
    const options = (v.options ?? []).map((opt) => {
      const prev = ov.options.find((x) => x.code.toUpperCase() === opt.code.toUpperCase())
      return prev ? { ...opt, sizes: prev.sizes, requires: prev.requires, attrs: prev.attrs, note: prev.note } : opt
    })
    const format = v.format && ov.format ? { ...ov.format, ...v.format } : v.format
    return { ...v, options, format, defaults: ov.defaults, format_overrides: ov.format_overrides, help: ov.help }
  })
  const sizes = (fresh.sizes ?? []).map((sz) => {
    const prev = o.sizes.find((x) => x.size === sz.size)
    if (!prev) return sz
    const attrs = { ...prev.attrs, ...sz.attrs }
    for (const key of ['power', 'voltage', 'height'] as const) if (!sz.attrs?.[key]) delete attrs[key]
    return { ...sz, label: prev.label ?? sz.label, attrs, footprint: prev.footprint }
  })
  const jumper = fresh.jumper && o.jumper ? { ...o.jumper, ...fresh.jumper } : fresh.jumper
  const sources = fresh.sources?.length ? [...fresh.sources, ...o.sources.slice(1)] : o.sources.slice(1)
  return {
    ...fresh,
    variables,
    sizes,
    rules: complexRules(o) ? o.rules : fresh.rules,
    jumper,
    sources,
    attrs: o.attrs,
    fields: o.fields,
    footprint: o.footprint,
    symbol_kind: o.symbol_kind,
    symbol_params: o.symbol_params,
    notes: o.notes,
    availability: o.availability,
    availability_keys: o.availability_keys,
    catalog: o.catalog,
    kind: o.kind,
    // Matrix/Katalog bestimmen die Lieferbarkeit selbst; sonst gilt die Bestätigung im Formular
    availability_certain:
      (o.availability_count ?? 0) > 0 || o.catalog.length > 0 ? o.availability_certain : fresh.availability_certain,
  }
}

// --------------------------------------------------------------------------- Vorlage → Entwurf (Bearbeiten)

export function fromTemplate(t: SeriesTemplate): TemplateDraft {
  const sizeVar = t.variables.find((v) => v.name === 'size')
  const valueVar = t.variables.find((v) => v.name === 'value')
  const rule = t.rules[0]
  const sizes: DraftSize[] = (t.sizes.length ? t.sizes.map((s) => s.size) : (sizeVar?.options.map((o) => o.value || o.code) ?? [])).map(
    (size) => {
      const spec = t.sizes.find((s) => s.size === size)
      const code = sizeVar?.options.find((o) => (o.value || o.code) === size)?.code ?? ''
      return {
        size,
        code: code === size ? '' : code,
        power: spec?.attrs.power ?? '',
        voltage: spec?.attrs.voltage ?? '',
        height: spec?.attrs.height ?? '',
      }
    },
  )
  const draft: TemplateDraft = {
    id: t.id,
    idTouched: true,
    category: t.category,
    manufacturer: t.manufacturer,
    series: t.series,
    title: t.title,
    titleTouched: true,
    description: t.description,
    datasheetUrl: t.datasheet_url ?? '',
    pattern: t.pattern ?? '',
    valueStyle: valueVar?.format?.style ?? 'rkm',
    valueScale: valueVar?.format?.scale ?? 1,
    valueDigits: valueVar?.format?.digits === 2 ? 2 : 3,
    sizes,
    variables: t.variables
      .filter((v) => v.name !== 'size' && v.name !== 'value')
      .map((v) => ({
        name: v.name,
        label: v.label,
        options: v.options.map((o) => ({ key: optionKey(), code: o.code, value: o.value ?? '', label: o.label ?? '', isDefault: o.default })),
      })),
    rangeMin: rule?.ranges[0]?.[0] ?? '',
    rangeMax: rule?.ranges[0]?.[1] ?? '',
    eSeries: (rule?.series ?? []).filter((s): s is ESeriesName => (SERIES_NAMES as string[]).includes(s)),
    jumper: Boolean(t.jumper),
    jumperCode: t.jumper?.value_code ?? '0R',
    jumperCodes: { ...(t.jumper?.codes ?? {}) },
    verified: t.verified,
    availabilityChecked: t.availability_certain,
    sourceTitle: t.sources[0]?.title ?? '',
    sourceUrl: t.sources[0]?.url ?? '',
    original: t,
  }
  draft.variables = syncVariables(draft)
  return draft
}

/** Regeln der gespeicherten Vorlage, die das Formular nicht abbilden kann (mehrere, mit Bedingungen …) */
export function complexRules(t: SeriesTemplate | null): boolean {
  if (!t || !t.rules.length) return false
  if (t.rules.length > 1) return true
  const r = t.rules[0]
  return r.sizes.length > 0 || Object.keys(r.when).length > 0 || r.ranges.length > 1 || Object.keys(r.attrs ?? {}).length > 0
}

function sampleValues(category: string): string[] {
  const unit = unitFor(category)
  if (category === 'Ferrite Beads') return ['220', '470', '1k']
  if (unit === 'F') return ['100n', '4,7µ', '10p']
  if (unit === 'H') return ['10µ', '2,2µ', '100µ']
  return ['10k', '4k7', '1M']
}

/** Typischer Wert der Kategorie (Prüfbeispiele der Pflichtfelder je Baugröße) */
export const typicalValue = (category: string): string => sampleValues(category)[0]

/** Typische Testwerte je Einheit */
export function defaultSamples(category: string, sizes: string[]): { key: string; size: string; value: string }[] {
  const values = sampleValues(category)
  const pick = (i: number) => sizes[Math.min(i, sizes.length - 1)] ?? ''
  return values.map((value, i) => ({ key: optionKey(), size: pick(i === 0 ? Math.min(1, sizes.length - 1) : i - 1), value }))
}
