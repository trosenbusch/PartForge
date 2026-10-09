/** Kategorien des Serien-Assistenten (passive Chip-Bauteile) mit Kurzbeschreibung und Schaltzeichen. */

export type GlyphKind = 'resistor' | 'capacitor' | 'inductor' | 'ferrite' | 'generic'

export interface SeriesCategory {
  table: string
  /** Fallback, falls die Bibliothek die Kategorie anders benennt */
  label: string
  description: string
  glyph: GlyphKind
  /** Einheit des Werts (für eigene Vorlagen) */
  unit: string
}

export const SERIES_CATEGORIES: SeriesCategory[] = [
  {
    table: 'Resistors',
    label: 'Widerstände',
    description: 'Chipwiderstände in E-Reihen – mit Toleranz, TK und 0-Ω-Brücken.',
    glyph: 'resistor',
    unit: 'Ω',
  },
  {
    table: 'Capacitors',
    label: 'Kondensatoren',
    description: 'MLCC nach Lieferbarkeitsmatrix – je Spannung und Dicke.',
    glyph: 'capacitor',
    unit: 'F',
  },
  {
    table: 'Inductors',
    label: 'Induktivitäten',
    description: 'Speicherdrosseln aus dem Katalog – mit Strom und DCR.',
    glyph: 'inductor',
    unit: 'H',
  },
  {
    table: 'Ferrite Beads',
    label: 'Ferrite',
    description: 'Chip-Ferrite mit Impedanz bei 100 MHz.',
    glyph: 'ferrite',
    unit: 'Ω',
  },
]

export function glyphFor(table: string): GlyphKind {
  return SERIES_CATEGORIES.find((c) => c.table === table)?.glyph ?? 'generic'
}

export function unitFor(table: string): string {
  return SERIES_CATEGORIES.find((c) => c.table === table)?.unit ?? 'Ω'
}
