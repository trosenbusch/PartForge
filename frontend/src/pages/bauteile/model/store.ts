/**
 * Zustand des Bauteile-Moduls: Suche, Filter und aktive Ansicht je Kategorie (für die Sitzung) sowie dauerhafte
 * Vorlieben (Zeilendichte, Kategoriebaum eingeklappt, Breite des Detailbereichs).
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { GridDensity } from '@/components/grid/theme'
import type { PreviewTab } from '@/components/preview/PreviewPanel'
import { prefsStorage } from '@/lib/prefs'
import type { FilterCondition } from './fields'

export interface TableQuery {
  search: string
  filters: FilterCondition[]
  /** Angewendete gespeicherte Ansicht */
  viewId: number | null
}

export const EMPTY_QUERY: TableQuery = { search: '', filters: [], viewId: null }

interface BauteileState {
  /** Bibliothek, zu der `queries` gehören */
  workspace: string | null
  /** Bei einem Bibliothekswechsel Suche/Filter verwerfen (Spalten können anders heißen) */
  syncWorkspace: (root: string | null) => void
  queries: Record<string, TableQuery>
  setSearch: (table: string, search: string) => void
  setFilters: (table: string, filters: FilterCondition[]) => void
  setQuery: (table: string, query: TableQuery) => void
  setView: (table: string, viewId: number | null) => void

  density: GridDensity
  setDensity: (density: GridDensity) => void
  treeCollapsed: boolean
  setTreeCollapsed: (collapsed: boolean) => void
  /**
   * Bei geöffnetem Detailbereich wird der Kategoriebaum automatisch ausgeblendet (mehr Platz für die Tabelle).
   * true = trotzdem einblenden (gilt, bis der Detailbereich schließt – nicht gespeichert).
   */
  treeShownWithDetail: boolean
  setTreeShownWithDetail: (shown: boolean) => void
  detailWidth: number
  setDetailWidth: (width: number) => void
  /** Zuletzt geöffnete Kategorie (Vorauswahl „Neues Bauteil“ auf der Übersicht) */
  lastTable: string | null
  setLastTable: (table: string) => void
  /** Ansicht der Vorschau im Detailbereich (bleibt beim Wechsel des Bauteils) */
  previewTab: PreviewTab
  setPreviewTab: (tab: PreviewTab) => void
}

const patch = (s: BauteileState, table: string, change: Partial<TableQuery>) => ({
  queries: { ...s.queries, [table]: { ...(s.queries[table] ?? EMPTY_QUERY), ...change } },
})

export const useBauteile = create<BauteileState>()(
  persist(
    (set) => ({
      workspace: null,
      syncWorkspace: (root) => set((s) => (s.workspace === root ? s : { workspace: root, queries: {} })),
      queries: {},
      setSearch: (table, search) => set((s) => patch(s, table, { search })),
      setFilters: (table, filters) => set((s) => patch(s, table, { filters })),
      setQuery: (table, query) => set((s) => patch(s, table, query)),
      setView: (table, viewId) => set((s) => patch(s, table, { viewId })),

      density: 'compact',
      setDensity: (density) => set({ density }),
      treeCollapsed: false,
      setTreeCollapsed: (treeCollapsed) => set({ treeCollapsed }),
      treeShownWithDetail: false,
      setTreeShownWithDetail: (treeShownWithDetail) => set({ treeShownWithDetail }),
      detailWidth: 432,
      setDetailWidth: (detailWidth) => set({ detailWidth }),
      lastTable: null,
      setLastTable: (lastTable) => set({ lastTable }),
      previewTab: 'symbol',
      setPreviewTab: (previewTab) => set({ previewTab }),
    }),
    {
      name: 'pf-bauteile',
      version: 1,
      storage: createJSONStorage(() => prefsStorage),
      partialize: (s) => ({
        density: s.density,
        treeCollapsed: s.treeCollapsed,
        detailWidth: s.detailWidth,
        lastTable: s.lastTable,
        previewTab: s.previewTab,
      }),
    },
  ),
)

/**
 * Sichtbarkeit des Kategoriebaums: die gespeicherte Vorliebe – bei geöffnetem Detailbereich automatisch
 * eingeklappt, bis man ihn ausdrücklich wieder einblendet.
 */
export function useTreeVisibility(detailOpen: boolean): { collapsed: boolean; setCollapsed: (collapsed: boolean) => void } {
  const treeCollapsed = useBauteile((s) => s.treeCollapsed)
  const shownWithDetail = useBauteile((s) => s.treeShownWithDetail)
  const collapsed = treeCollapsed || (detailOpen && !shownWithDetail)
  const setCollapsed = (next: boolean) => {
    const st = useBauteile.getState()
    if (next) {
      // nur „wieder automatisch“ – die gespeicherte Vorliebe bleibt, solange der Baum sonst offen sein soll
      if (detailOpen && !st.treeCollapsed) st.setTreeShownWithDetail(false)
      else st.setTreeCollapsed(true)
    } else {
      st.setTreeCollapsed(false)
      if (detailOpen) st.setTreeShownWithDetail(true)
    }
  }
  return { collapsed, setCollapsed }
}

/** Abfrage einer Kategorie (stabile Referenz, solange sie sich nicht ändert) */
export function useTableQuery(table: string): TableQuery {
  return useBauteile((s) => s.queries[table] ?? EMPTY_QUERY)
}
