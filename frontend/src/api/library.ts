/**
 * Bibliotheksdaten, die mehrere Seiten brauchen: Kategorien, Kennzahlen (Übersicht), Schnellsuche.
 * Query-Keys beginnen mit dem Modulnamen – sie werden beim Bibliothekswechsel automatisch verworfen.
 * Module (Bauteile, Serien …) legen ihre eigenen Dateien an (`src/api/parts.ts` usw.).
 */
import { useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { Filled, ResponseOf } from './types'

export type CategoryDef = Filled<ResponseOf<'/api/categories', 'get'>>[number]
export type FieldDef = CategoryDef['fields'][number]
export type LibraryStats = Filled<ResponseOf<'/api/stats', 'get'>>
export type CategoryStat = LibraryStats['categories'][number]
export type AuditEntry = LibraryStats['recent_changes'][number]
export type SearchHit = Filled<ResponseOf<'/api/search', 'get'>>[number]

export const libraryKeys = {
  categories: ['categories', 'list'] as const,
  stats: ['stats'] as const,
  search: (q: string) => ['search', q] as const,
}

export const libraryApi = {
  categories: (signal?: AbortSignal) => api.get<CategoryDef[]>('/api/categories', { query: { counts: true }, signal }),
  stats: (signal?: AbortSignal) => api.get<LibraryStats>('/api/stats', { signal }),
  search: (q: string, limit = 8, signal?: AbortSignal) => api.get<SearchHit[]>('/api/search', { query: { q, limit }, signal }),
}

/** Kategorien mit Bauteilzahlen (Bauteilbaum, Brotkrumen, Auswahllisten). */
export function useCategories() {
  return useQuery({
    queryKey: libraryKeys.categories,
    queryFn: ({ signal }) => libraryApi.categories(signal),
    staleTime: 30_000,
  })
}

/** Kennzahlen der Bibliothek (Übersicht). */
export function useLibraryStats() {
  return useQuery({
    queryKey: libraryKeys.stats,
    queryFn: ({ signal }) => libraryApi.stats(signal),
    staleTime: 15_000,
  })
}

/** Anzeigename einer Kategorie (Tabellenname → „Widerstände“); solange unbekannt: null. */
export function useCategoryLabel(table: string | undefined): string | null {
  const categories = useCategories()
  if (!table) return null
  return categories.data?.find((c) => c.table.toLowerCase() === table.toLowerCase())?.label ?? null
}
