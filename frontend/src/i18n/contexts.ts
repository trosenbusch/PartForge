/**
 * English for German sources whose translation depends on where they appear (gettext's msgctxt).
 * Used through `tc(context, source)`; sources without an entry here use the flat catalogs.
 * The flat catalogs hold each source's default wording and must not contradict each other.
 */
const contexts = {
  /** „von“ before a person: „geändert von Tobias“ */
  author: { von: 'by' },
  /** Lower bound of a range: „von … bis …“ */
  range: { von: 'from' },
  /** Lines of a text (DbLib file), not table rows */
  text: { Zeile: 'Line', Zeilen: 'Lines' },
  /** Font names inside a sentence */
  inline: { Systemschrift: 'system font', Hausschrift: 'house font', Strichschrift: 'stroke font' },
  /** Role of a datasheet page */
  pageRole: { Inhalt: 'Contents' },
  /** Verified against the datasheet (MPN templates) */
  verification: { Geprüft: 'Verified' },
  /** Claude API key */
  apiKey: { Schlüssel: 'API key' },
  /** Reload state from Altium Designer */
  refresh: { Aktualisieren: 'Refresh' },
  /** Snap grid of a schematic symbol (the default „Raster“ is a footprint pitch) */
  grid: { Raster: 'Grid' },
  /** Abbreviated segments of a manufacturer part number */
  mpn: { Druck: 'Marking' },
  /** The component, not the electrical quantity */
  component: { Widerstand: 'Resistor' },
} as const satisfies Record<string, Readonly<Record<string, string>>>

export type TranslationContext = keyof typeof contexts

export default contexts
