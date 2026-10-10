import { t as translate } from '@/lib/i18n'
/** Entwurf der Kategorie-Eigenschaften (alles außer den Feldern) – Prüfung und Patch wie im Backend. */
import type { CategoryDef, CategoryPatch } from '@/api/settings'
import { templateColumns } from '../templateRender'
import { HEX_COLOR, normalizeName, validateTableName } from './meta'

export interface CategoryDraft {
  table: string
  label: string
  prefix: string
  icon: string
  color: string
  default_symbol: string | null
  value_field: string | null
  description_template: string
  comment_template: string
  altium_enabled: boolean
}

export function toDraft(c: CategoryDef): CategoryDraft {
  return {
    table: c.table,
    label: c.label,
    prefix: c.prefix,
    icon: c.icon,
    color: c.color,
    default_symbol: c.default_symbol ?? null,
    value_field: c.value_field ?? null,
    description_template: c.description_template ?? '',
    comment_template: c.comment_template ?? '',
    altium_enabled: c.altium_enabled,
  }
}

/** Nur geänderte Eigenschaften */
export function draftPatch(saved: CategoryDraft, draft: CategoryDraft): CategoryPatch {
  const patch: CategoryPatch = {}
  const table = normalizeName(draft.table)
  if (table !== saved.table) patch.table = table
  const label = normalizeName(draft.label)
  if (label !== saved.label) patch.label = label
  const prefix = draft.prefix.trim().toUpperCase()
  if (prefix !== saved.prefix) patch.prefix = prefix
  if (draft.icon !== saved.icon) patch.icon = draft.icon
  if (draft.color.toUpperCase() !== saved.color.toUpperCase()) patch.color = draft.color.toUpperCase()
  if (draft.default_symbol !== saved.default_symbol) patch.default_symbol = draft.default_symbol
  if (draft.value_field !== saved.value_field) patch.value_field = draft.value_field
  if (draft.description_template !== saved.description_template) patch.description_template = draft.description_template
  if (draft.comment_template !== saved.comment_template) patch.comment_template = draft.comment_template
  if (draft.altium_enabled !== saved.altium_enabled) patch.altium_enabled = draft.altium_enabled
  return patch
}

export type DraftErrors = Partial<Record<keyof CategoryDraft, string>>

export function draftErrors(draft: CategoryDraft, category: CategoryDef, all: CategoryDef[]): DraftErrors {
  const errors: DraftErrors = {}
  if (!normalizeName(draft.label)) errors.label = translate("Bitte eine Bezeichnung eingeben.")
  if (!/^[A-Za-z]{1,8}$/.test(draft.prefix.trim())) errors.prefix = translate("1–8 Buchstaben, z. B. R, C, U oder FB.")
  if (!HEX_COLOR.test(draft.color)) errors.color = translate("Farbe im Format #RRGGBB.")
  if (normalizeName(draft.table) !== category.table) {
    const problem = validateTableName(draft.table, all, category.table)
    if (problem) errors.table = problem
  }
  const columns = new Set(category.fields.map((f) => f.column.toLowerCase()))
  const unknown = (tpl: string) => templateColumns(tpl).filter((c) => !columns.has(c.toLowerCase()))
  const badDescription = unknown(draft.description_template)
  if (badDescription.length) errors.description_template = translate("Unbekannte Felder: {value1}", { value1: badDescription.map((c) => `{${c}}`).join(', ') })
  const badComment = unknown(draft.comment_template)
  if (badComment.length) errors.comment_template = translate("Unbekannte Felder: {value1}", { value1: badComment.map((c) => `{${c}}`).join(', ') })
  if (draft.value_field && !columns.has(draft.value_field.toLowerCase())) errors.value_field = translate("Das Feld „{value1}“ gibt es nicht.", { value1: draft.value_field })
  return errors
}
