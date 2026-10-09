/** Kurztexte über eine Auswahl („4 Bauformen · E24 + E96 · 1 Ω … 10 MΩ“) für Zusammenfassungen. */
import type { SeriesTemplateSummary } from '@/api/series'
import { plural } from '@/lib/format'
import { FINE_SERIES, type SeriesSettings } from './settings'
import { displayValue, parseValueList } from './values'

/** E-Reihe der Auswahl; „auto“ ohne Vorlagendetails: „Reihe laut Datenblatt“ (Regel-Vorlagen z. B. E24 + E96) */
export function seriesText(s: Pick<SeriesSettings, 'series' | 'addE24'>, datasheet?: string[]): string {
  if (s.series === 'auto') return datasheet?.length ? `laut Datenblatt (${datasheet.join(' + ')})` : 'Reihe laut Datenblatt'
  return s.addE24 && FINE_SERIES.includes(s.series) ? `${s.series} + E24` : s.series
}

export function rangeText(s: Pick<SeriesSettings, 'rangeMin' | 'rangeMax'>, unit: string): string {
  if (s.rangeMin === null && s.rangeMax === null) return 'ganze Serie'
  const lo = s.rangeMin !== null ? displayValue(s.rangeMin, unit) : 'Anfang'
  const hi = s.rangeMax !== null ? displayValue(s.rangeMax, unit) : 'Ende'
  return `${lo} … ${hi}`
}

/** Zusammenfassung einer gemerkten Auswahl */
export function describeSettings(t: Pick<SeriesTemplateSummary, 'value_unit'>, s: Partial<SeriesSettings>): string[] {
  const out: string[] = []
  if (s.sizes?.length) out.push(s.sizes.length <= 3 ? s.sizes.join(', ') : plural(s.sizes.length, 'Bauform', 'Bauformen'))
  if (s.valueMode === 'list') {
    const n = parseValueList(s.valuesText ?? '', t.value_unit, { jumper: true }).filter((v) => v.value !== null && !v.error).length
    out.push(plural(n, 'Wert aus Liste', 'Werte aus Liste'))
  } else {
    out.push(seriesText({ series: s.series ?? 'auto', addE24: s.addE24 ?? true }))
    out.push(rangeText({ rangeMin: s.rangeMin ?? null, rangeMax: s.rangeMax ?? null }, t.value_unit))
  }
  return out
}
