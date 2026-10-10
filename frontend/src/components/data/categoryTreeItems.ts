import { metadataLabel, useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { useMemo } from 'react'
import { useCategories, type CategoryDef } from '@/api/library'
import type { CategoryTreeItem } from './CategoryTree'

/** Standard-Gruppen je Tabellenname (eigene Kategorien landen unter „Weitere“) */
export const CATEGORY_GROUPS: Record<string, string> = {
  Resistors: "Passive Bauteile",
  Capacitors: "Passive Bauteile",
  Inductors: "Passive Bauteile",
  'Ferrite Beads': "Passive Bauteile",
  Oscillators: "Passive Bauteile",
  Diodes: "Halbleiter",
  LEDs: "Halbleiter",
  'Transistors BJT': "Halbleiter",
  'Transistors FET': "Halbleiter",
  Optocouplers: "Halbleiter",
  Amplifiers: "Integrierte Schaltungen",
  'Power Linear': "Integrierte Schaltungen",
  'Power Switchmode': "Integrierte Schaltungen",
  'Data Converters': "Integrierte Schaltungen",
  'Integrated Circuits': "Integrierte Schaltungen",
  Connectors: "Elektromechanik",
  Electromechanical: "Elektromechanik",
  Fuses: "Elektromechanik",
  Mechanical: "Elektromechanik",
}

export const CATEGORY_GROUP_ORDER = ['Passive Bauteile', 'Halbleiter', 'Integrierte Schaltungen', 'Elektromechanik', 'Weitere']

/** CategoryDef → Baumeintrag */
export function categoryToTreeItem(c: CategoryDef, groups: Record<string, string> = CATEGORY_GROUPS, translate = tr): CategoryTreeItem {
  return {
    id: c.table,
    label: metadataLabel(c.label, translate),
    icon: c.icon,
    color: c.color,
    count: c.part_count ?? null,
    group: groups[c.table] ?? "Weitere",
    keywords: `${c.table} ${c.prefix}`,
  }
}

/** Kategorien aus `/api/categories` (mit Zählern) als Baumeinträge */
export function useCategoryTreeItems(groups: Record<string, string> = CATEGORY_GROUPS) {
  const { t: tr } = useI18n()
  const q = useCategories()
  const items = useMemo(() => (q.data ?? []).map((c) => categoryToTreeItem(c, groups, tr)), [q.data, groups, tr])
  const total = useMemo(() => (q.data ?? []).reduce((s, c) => s + (c.part_count ?? 0), 0), [q.data])
  return { items, total, isLoading: q.isLoading, error: q.error }
}
