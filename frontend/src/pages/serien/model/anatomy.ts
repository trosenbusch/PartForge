/**
 * Aufbau einer Teilenummer: „CRCW0603 10K0 F K EA“ → Segmente mit Bedeutung (Baugröße, Wert, Toleranz …).
 * Die Karten bekommen die Segmente vom Backend (`TemplateSummary.example.segments`); hier entstehen sie für gelesene
 * Teilenummern (Schnellstart, Beispiel im Zähler): Muster der Vorlage + vom Backend gelesene Codes
 * (`/api/series/decode`) – gleiche Form wie `partforge/domain/mpn/examples.py` `mpn_segments`.
 */
import type { DecodedMpn, MpnSegment, SeriesTemplate } from '@/api/series'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { findOptionByCode, optionText, parsePattern, sizeInfo, valueLabelFor, variable } from './template'

export type { MpnSegment, MpnSegmentKind as SegmentKind } from '@/api/series'

const SHORT: Record<string, string> = {
  size: 'Größe',
  value: 'Wert',
  tolerance: 'Tol.',
  tcr: 'TK',
  packaging: 'Verp.',
  cspec: 'Verp.',
  packing: 'Gurt',
  voltage: 'Spg.',
  dielectric: 'Diel.',
  thickness: 'Dicke',
  marking: 'Druck',
  power: 'Leist.',
  quantity: 'Menge',
  termination: 'Anschl.',
  char: 'Merkm.',
}

/** Kurzform einer Variablenbezeichnung */
export function shortLabel(name: string, label: string): string {
  if (SHORT[name]) return SHORT[name]
  return label.length > 7 ? `${label.slice(0, 5)}.` : label
}

function sizeCode(t: SeriesTemplate, size: string | null): string {
  if (!size) return ''
  const v = variable(t, 'size')
  const o = v?.options.find((x) => (x.value || x.code) === size)
  return o?.code ?? size
}

/** Teilenummer in Segmente zerlegen; null, wenn sie nicht zum Muster passt */
export function splitMpn(t: SeriesTemplate, d: Pick<DecodedMpn, 'mpn' | 'size' | 'codes' | 'value_text' | 'jumper'>): MpnSegment[] | null {
  const segments = parsePattern(t.pattern)
  const valueIndex = segments.findIndex((s) => s.variable === 'value')
  if (!segments.length || valueIndex < 0) return null
  const mpn = d.mpn
  const upper = mpn.toUpperCase()
  const describe = (name: string, text: string): MpnSegment => {
    if (name === 'size') {
      const info = d.size ? sizeInfo(t, d.size) : null
      return { text, kind: 'size', name, label: 'Baugröße', short: 'Größe', meaning: info ? info.label : d.size }
    }
    const v = variable(t, name)
    const o = v ? findOptionByCode(v, text, d.size ?? null) : undefined
    const label = v?.label ?? name
    return { text, kind: 'code', name, label, short: shortLabel(name, label), meaning: o ? optionText(o) : null }
  }
  const expected = (seg: (typeof segments)[number]): { text: string; seg: MpnSegment } => {
    if (seg.literal !== undefined) {
      return { text: seg.literal, seg: { text: seg.literal, kind: 'literal', name: null, label: 'fest', short: '', meaning: null } }
    }
    const name = seg.variable ?? ''
    const text = name === 'size' ? sizeCode(t, d.size ?? null) : (d.codes[name] ?? '')
    return { text, seg: describe(name, text) }
  }
  const left: MpnSegment[] = []
  let pos = 0
  for (const seg of segments.slice(0, valueIndex)) {
    const e = expected(seg)
    if (!upper.startsWith(e.text.toUpperCase(), pos)) return null
    left.push({ ...e.seg, text: mpn.slice(pos, pos + e.text.length) })
    pos += e.text.length
  }
  const right: MpnSegment[] = []
  let end = mpn.length
  for (const seg of segments.slice(valueIndex + 1).reverse()) {
    const e = expected(seg)
    const start = end - e.text.length
    if (start < pos || upper.slice(start, end) !== e.text.toUpperCase()) return null
    right.unshift({ ...e.seg, text: mpn.slice(start, end) })
    end = start
  }
  const valueText = mpn.slice(pos, end)
  if (!valueText) return null
  const value: MpnSegment = {
    text: valueText,
    kind: 'value',
    name: 'value',
    label: d.jumper ? 'Brücke' : valueLabelFor(t),
    short: d.jumper ? 'Brücke' : 'Wert',
    meaning: d.jumper ? '0 Ω' : d.value_text ? formatQuantityText(d.value_text) : null,
  }
  return [...left, value, ...right].filter((s) => s.text.length > 0)
}
