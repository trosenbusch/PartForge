/**
 * Auswahl im Schritt „Werte und Varianten“ (je Vorlage gemerkt) und die daraus gebaute Anfrage an das Backend
 * (`SeriesRequest`, partforge/domain/series.py).
 */
import type { SeriesRequest, SeriesTemplate } from '@/api/series'
import { SERIES_MAX_ROWS } from '@/api/series'
import type { ESeriesName } from '@/lib/units'
import {
  defaultSizes,
  effectiveTolerance,
  packagingChoices,
  ruleSeries,
  sizeNames,
  tcrChoices,
  templateMode,
  toleranceChoices,
  toleranceSeries,
  voltageChoices,
} from './template'
import { parseValueList, requestNumber, SERIES_NAMES, type ParsedValue } from './values'

export type ValueMode = 'range' | 'list'
/** „auto“ = Reihen laut Datenblatt (Toleranz) bzw. alle lieferbaren Werte */
export type SeriesChoice = 'auto' | ESeriesName
export type Density = 'L' | 'N' | 'M'
export type FootprintHeight = 'standard' | 'class' | 'exact'

export interface SeriesSettings {
  sizes: string[]
  valueMode: ValueMode
  series: SeriesChoice
  /** E24-Werte zu E48/E96/E192 ergänzen (4k7, 2k2 …) */
  addE24: boolean
  /** null = untere bzw. obere Grenze der Serie */
  rangeMin: number | null
  rangeMax: number | null
  /** eingefügte Werteliste */
  valuesText: string
  /** Code bzw. Text (Katalog); null = Vorgabe der Vorlage */
  tolerance: string | null
  /** TK-Code bzw. TK-Filter („±100ppm/K“); null = laut Datenblatt / beliebig */
  tcr: string | null
  /** Spannungs-Codes (Matrix) bzw. -Texte (Katalog); leer = alle */
  voltages: string[]
  /** Verpackungscode; null = Standard je Baugröße */
  packaging: string | null
  includeJumper: boolean
  /** IPC-Dichte; null = Hausstil */
  density: Density | null
  footprintHeight: FootprintHeight
}

/** Reihen mit so vielen Werten, dass E24-Werte (4k7, 2k2 …) fehlen können */
export const FINE_SERIES: readonly ESeriesName[] = ['E48', 'E96', 'E192']

export function defaultSettings(t: SeriesTemplate): SeriesSettings {
  return {
    sizes: defaultSizes(t),
    valueMode: 'range',
    series: 'auto',
    addE24: true,
    rangeMin: null,
    rangeMax: null,
    valuesText: '',
    tolerance: null,
    tcr: null,
    voltages: [],
    packaging: null,
    // Brücken nur auf Wunsch (Toleranz, TK, Leistung und Spannung gelten für sie nicht – Rmax und Nennstrom in den Notizen)
    includeJumper: false,
    density: null,
    footprintHeight: 'class',
  }
}

/** Gemerkte Auswahl an die Vorlage anpassen (unbekannte Baugrößen/Codes fallen weg) */
export function reconcileSettings(t: SeriesTemplate, saved: Partial<SeriesSettings> | undefined): SeriesSettings {
  const d = defaultSettings(t)
  if (!saved) return d
  const sizesAll = sizeNames(t)
  const sizes = (saved.sizes ?? []).filter((s) => sizesAll.includes(s))
  const tolerances = toleranceChoices(t).map((o) => o.value)
  const tcr = tcrChoices(t)?.options.map((o) => o.value) ?? []
  const voltages = voltageChoices(t).map((o) => o.value)
  const sizesNow = sizes.length ? sizes : d.sizes
  const packaging = packagingChoices(t, sizesNow).map((o) => o.value)
  const series = saved.series && (saved.series === 'auto' || SERIES_NAMES.includes(saved.series)) ? saved.series : d.series
  return {
    ...d,
    sizes: sizesNow,
    valueMode: saved.valueMode === 'list' ? 'list' : 'range',
    series,
    addE24: saved.addE24 ?? d.addE24,
    rangeMin: typeof saved.rangeMin === 'number' && saved.rangeMin > 0 ? saved.rangeMin : null,
    rangeMax: typeof saved.rangeMax === 'number' && saved.rangeMax > 0 ? saved.rangeMax : null,
    valuesText: typeof saved.valuesText === 'string' ? saved.valuesText : '',
    tolerance: saved.tolerance && tolerances.includes(saved.tolerance) ? saved.tolerance : null,
    tcr: saved.tcr && tcr.includes(saved.tcr) ? saved.tcr : null,
    voltages: (saved.voltages ?? []).filter((v) => voltages.includes(v)),
    packaging: saved.packaging && packaging.includes(saved.packaging) ? saved.packaging : null,
    includeJumper: Boolean(t.jumper) && t.kind !== 'catalog' ? (saved.includeJumper ?? d.includeJumper) : false,
    density: saved.density === 'L' || saved.density === 'N' || saved.density === 'M' ? saved.density : null,
    footprintHeight:
      saved.footprintHeight === 'standard' || saved.footprintHeight === 'exact' ? saved.footprintHeight : 'class',
  }
}

/**
 * Reihen, die das Datenblatt nennt: die der Toleranz (Option `eseries`), sonst die der Regeln. Leer, wenn die Vorlage
 * keine nennt (Vorlagen ohne Regeln, Matrix ohne Reihe an der Toleranz, Katalog) – dann gibt es auch keinen
 * „laut Datenblatt“-Hinweis.
 */
export function datasheetSeries(t: SeriesTemplate, s: SeriesSettings): ESeriesName[] {
  const mode = templateMode(t)
  if (mode === 'catalog') return []
  const fromTolerance = toleranceSeries(t, effectiveTolerance(t, s.tolerance))
  if (fromTolerance.length) return fromTolerance
  return mode === 'rules' ? ruleSeries(t) : []
}

/** Reihen ohne eigene Wahl: laut Datenblatt, sonst E24 (Regeln/offen) bzw. alle lieferbaren Werte (Matrix, Katalog) */
export function autoSeries(t: SeriesTemplate, s: SeriesSettings): ESeriesName[] {
  const fromDatasheet = datasheetSeries(t, s)
  if (fromDatasheet.length) return fromDatasheet
  const mode = templateMode(t)
  return mode === 'rules' || mode === 'open' ? ['E24'] : []
}

/** Reihen, die die Serie verwendet (gewählt, sonst laut Datenblatt) */
export function effectiveSeries(t: SeriesTemplate, s: SeriesSettings): ESeriesName[] {
  if (s.series !== 'auto') return s.addE24 && FINE_SERIES.includes(s.series) ? [s.series, 'E24'] : [s.series]
  return autoSeries(t, s)
}

/**
 * `e_series` der Anfrage: gewählte Reihe; „laut Datenblatt“ ohne Reihe an der Toleranz → die Reihen der Regeln
 * ausdrücklich (sonst nähme das Backend E24 und ließe die übrigen Werte mit Warnung aus).
 */
export function requestSeries(t: SeriesTemplate, s: SeriesSettings): string | null {
  if (s.series === 'auto') {
    if (templateMode(t) !== 'rules' || toleranceSeries(t, effectiveTolerance(t, s.tolerance)).length) return null
    const fromRules = ruleSeries(t)
    return fromRules.length ? fromRules.join('+') : null
  }
  return s.addE24 && FINE_SERIES.includes(s.series) ? `${s.series}+E24` : s.series
}

/** Werteliste der Auswahl (gelesen) */
export function parsedValues(t: SeriesTemplate, s: SeriesSettings): ParsedValue[] {
  if (s.valueMode !== 'list') return []
  return parseValueList(s.valuesText, t.value_unit, { jumper: Boolean(t.jumper) && t.kind !== 'catalog' })
}

/** gültige, eindeutige Werte der Liste */
export const listValues = (values: ParsedValue[]): number[] =>
  values.filter((v) => v.value !== null && !v.error && !v.duplicate).map((v) => v.value as number)

/**
 * Anfrage an /api/series/preview bzw. /commit. `domain` = Wertebereich der Serie für die gewählten Baugrößen –
 * Grenzen auf dem Rand werden nicht mitgeschickt (das Backend nimmt dann den Bereich je Baugröße).
 */
export function buildRequest(
  t: SeriesTemplate,
  s: SeriesSettings,
  domain: [number, number] | null,
): SeriesRequest | null {
  if (!s.sizes.length) return null
  const mode = templateMode(t)
  const list = s.valueMode === 'list'
  const values = list ? listValues(parsedValues(t, s)) : []
  if (list && !values.length) return null
  let rangeMin: string | null = null
  let rangeMax: string | null = null
  if (!list) {
    const lo = s.rangeMin
    const hi = s.rangeMax
    const atLo = lo === null || (domain !== null && lo <= domain[0] * (1 + 1e-9))
    const atHi = hi === null || (domain !== null && hi >= domain[1] * (1 - 1e-9))
    if (mode === 'open') {
      // ohne Wertebereiche in der Vorlage braucht das Backend beide Grenzen
      const a = lo ?? domain?.[0]
      const b = hi ?? domain?.[1]
      if (a === undefined || b === undefined) return null
      rangeMin = requestNumber(a)
      rangeMax = requestNumber(b)
    } else {
      rangeMin = atLo ? null : requestNumber(lo as number)
      rangeMax = atHi ? null : requestNumber(hi as number)
    }
  }
  const jumper = Boolean(t.jumper) && t.kind !== 'catalog' && s.includeJumper
  return {
    template_id: t.id,
    sizes: s.sizes,
    tolerance: s.tolerance,
    tcr: s.tcr,
    e_series: list ? null : requestSeries(t, s),
    range_min: rangeMin,
    range_max: rangeMax,
    values: values.map(requestNumber),
    include_jumper: jumper,
    voltages: s.voltages,
    dielectrics: [],
    packaging: s.packaging,
    part_number_scheme: null,
    density: s.density,
    footprint_height: s.footprintHeight,
    field_overrides: {},
    datasheet_url: null,
    replace_links: false,
    max_rows: SERIES_MAX_ROWS,
  }
}

/** Stabiler Schlüssel einer Anfrage (Vergleich „Vorschau passt zur Auswahl“) */
export const requestKey = (req: SeriesRequest | null): string => (req ? JSON.stringify(req) : '')
