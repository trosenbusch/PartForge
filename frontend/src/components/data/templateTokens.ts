/** Zerlegung von Beschreibungs-/Kommentar-Vorlagen wie „RES {Size} {Resistance:rkm}“ (wie partforge/db/values.py). */

export interface TemplateSegmentText {
  kind: 'text'
  start: number
  end: number
  text: string
}

export interface TemplateSegmentToken {
  kind: 'token'
  start: number
  /** exklusiv; bei offenem Platzhalter = Textende */
  end: number
  /** Feldname (getrimmt) */
  name: string
  /** Formatangabe nach „:“ (rkm, si, nounit, upper, lower) */
  format: string | null
  /** schließende Klammer vorhanden */
  closed: boolean
  /** Position des „:“ (absolut) */
  colon: number | null
}

export type TemplateSegment = TemplateSegmentText | TemplateSegmentToken

/** Vorlage in Text und Platzhalter zerlegen (auch unvollständige Platzhalter während der Eingabe) */
export function parseTemplate(value: string): TemplateSegment[] {
  const out: TemplateSegment[] = []
  let i = 0
  let textStart = 0
  while (i < value.length) {
    if (value[i] === '{') {
      if (i > textStart) out.push({ kind: 'text', start: textStart, end: i, text: value.slice(textStart, i) })
      let j = i + 1
      let colon: number | null = null
      while (j < value.length && value[j] !== '}' && value[j] !== '{') {
        if (value[j] === ':' && colon === null) colon = j
        j++
      }
      const closed = j < value.length && value[j] === '}'
      const inner = value.slice(i + 1, j)
      const name = (colon !== null ? value.slice(i + 1, colon) : inner).trim()
      const format = colon !== null ? value.slice(colon + 1, j).trim() : null
      const end = closed ? j + 1 : j
      out.push({ kind: 'token', start: i, end, name, format, closed, colon })
      i = end
      textStart = i
      continue
    }
    i++
  }
  if (textStart < value.length) out.push({ kind: 'text', start: textStart, end: value.length, text: value.slice(textStart) })
  return out
}

/** Platzhalter, in dem der Cursor steht (zwischen „{“ und „}“) */
export function tokenAt(segments: TemplateSegment[], caret: number): TemplateSegmentToken | null {
  for (const s of segments) {
    if (s.kind !== 'token') continue
    const innerEnd = s.closed ? s.end - 1 : s.end
    if (caret > s.start && caret <= innerEnd) return s
  }
  return null
}

/** Platzhalter neu schreiben */
export function buildToken(name: string, format: string | null): string {
  return `{${name}${format ? `:${format}` : ''}}`
}

/** Platzhalter-Feldnamen einer Vorlage */
export function templateFields(value: string): string[] {
  return parseTemplate(value)
    .filter((s): s is TemplateSegmentToken => s.kind === 'token' && Boolean(s.name))
    .map((s) => s.name)
}

export interface TemplateFormatDef {
  name: string
  label: string
  example?: string
}

/** Formatangaben des Backends (partforge/db/values.py) */
export const TEMPLATE_FORMATS: TemplateFormatDef[] = [
  { name: 'rkm', label: 'RKM-Code', example: '4k7 · 100n · 6V3' },
  { name: 'si', label: 'SI mit Einheit', example: '4.7kΩ' },
  { name: 'nounit', label: 'ohne Einheit', example: '4.7k' },
  { name: 'upper', label: 'GROSSBUCHSTABEN', example: 'SMD' },
  { name: 'lower', label: 'kleinbuchstaben', example: 'smd' },
]
