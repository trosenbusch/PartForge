/** Feldwerte der Prüfansicht: gemeinsame Werte der Bestellnummern, sichtbare Felder je Kategorie. */
import type { CategoryDef, FieldDef } from '@/api/library'
import type { PartProposal } from '@/api/datasheets'

/** Gemeinsamer Wert aller Einträge (oder `null`, wenn sie sich unterscheiden) */
export function commonValue(values: readonly (string | undefined)[]): string | null {
  const set = new Set(values.map((v) => v ?? ''))
  return set.size === 1 ? [...set][0] : null
}

/** Felder, die die Übernahme selbst setzt (Identität, Verweise, Buchhaltung) – nicht im Abschnitt „Parameter“ */
const MANAGED = new Set(
  [
    'Part Number',
    'Manufacturer',
    'Manufacturer Part Number',
    'Value',
    'Comment',
    'Description',
    'Library Ref',
    'Library Path',
    'Footprint Ref',
    'Footprint Path',
    'Footprint Ref 2',
    'Footprint Path 2',
    'ComponentLink1Description',
    'ComponentLink1URL',
    'Supplier 1',
    'Supplier Part Number 1',
    'Supplier 2',
    'Supplier Part Number 2',
    'PF Status',
    'PF Created',
    'PF Modified',
    'PF Author',
  ].map((c) => c.toLowerCase()),
)

/** Allgemeine Felder, die ein Datenblatt liefert (Reihenfolge der Anzeige) */
const GENERAL = ['Package', 'Mounting', 'Height', 'Operating Temperature', 'Lifecycle', 'RoHS', 'Notes']

export interface FieldGroups {
  specific: FieldDef[]
  general: FieldDef[]
}

export function parameterFields(category: CategoryDef | undefined): FieldDef[] {
  if (!category) return []
  return category.fields.filter((f) => !f.system && !MANAGED.has(f.column.toLowerCase()))
}

export function fieldGroups(category: CategoryDef | undefined): FieldGroups {
  const fields = parameterFields(category)
  const specific = fields.filter((f) => !f.common)
  const general = GENERAL.map((c) => fields.find((f) => f.column === c)).filter((f): f is FieldDef => Boolean(f))
  const extra = fields.filter((f) => f.common && !GENERAL.includes(f.column))
  return { specific, general: [...general, ...extra] }
}

/** Werte einer Spalte über die gewählten Bestellnummern des Vorschlags */
export function proposalValues(p: PartProposal | undefined, column: string): string[] {
  return (p?.variants ?? []).map((v) => v.values[column] ?? '')
}

/** Fehler einer Spalte (Prüfung `validate_part`) über alle gewählten Bestellnummern */
export function proposalErrors(p: PartProposal | undefined, column: string): string[] {
  const out = new Set<string>()
  for (const v of p?.variants ?? []) {
    const e = v.errors[column]
    if (e) out.add(e)
  }
  return [...out]
}
