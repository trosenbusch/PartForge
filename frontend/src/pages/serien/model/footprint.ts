/**
 * Footprint-Anfrage einer Baugröße – wie partforge/domain/series.py `_footprint_request` (Hinweis der Baugröße bzw.
 * der Vorlage, Chip-Bauteilart aus der Kategorie). Dient der Vorschau benötigter Footprints vor dem Erzeugen.
 */
import type { SeriesTemplate } from '@/api/series'
import type { FootprintRequest } from '@/lib/geometry'
import type { Density } from './settings'
import { sizeSpec } from './template'

const CHIP_KIND: Record<string, string> = { Resistors: 'R', Capacitors: 'C', Inductors: 'L', 'Ferrite Beads': 'FB' }
/** EIA-Größen, für die der Chip-Generator Tabellen hat */
const CHIP_SIZES = new Set(['01005', '0201', '0402', '0603', '0805', '1008', '1206', '1210', '1808', '1812', '2010', '2220', '2512'])

export function footprintRequestFor(t: SeriesTemplate, size: string, density: Density): FootprintRequest | null {
  const hint = sizeSpec(t, size)?.footprint ?? t.footprint
  const kind = hint.kind || t.footprint.kind || CHIP_KIND[t.category] || null
  const params: Record<string, unknown> = { ...(hint.params ?? {}) }
  if (hint.family === 'chip' && !params.L) {
    const chipSize = hint.size || size
    if (!kind || !CHIP_SIZES.has(chipSize)) return null
    return { family: 'chip', params: { kind, size: chipSize }, density, with_3d: false }
  }
  if (kind && !('kind' in params)) params.kind = kind
  return {
    family: hint.family,
    params,
    density,
    land_pattern: hint.land_pattern ?? null,
    with_3d: false,
  }
}

/**
 * Kurzform des Grunds einer Kennung im Footprint-Namen (`FootprintRef.name_reason`) für Hinweise: der erste Satzteil
 * („Footprint-Höhe „Exakt““, „Land Pattern nach Herstellerempfehlung im Datenblatt …“) – der volle Text steht im Tooltip.
 */
export function nameReasonTopic(reason: string): string {
  const first = reason.split(/:|\s[–—-]\s/)[0]?.trim() ?? ''
  if (!first) return 'eigenes Land Pattern'
  return first.length <= 90 ? first : `${first.slice(0, 80).trimEnd()} …`
}
