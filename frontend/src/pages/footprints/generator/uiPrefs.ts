/** Kleine Ansichts-Vorlieben des Generators (auf-/zugeklappte Abschnitte, gespeichert) und flüchtiger UI-Zustand. */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

interface FootprintUiState {
  /** Abschnitt → zugeklappt (true) / aufgeklappt (false); fehlt = Standard des Abschnitts */
  collapsed: Record<string, boolean>
  setCollapsed: (id: string, collapsed: boolean) => void
}

export const useFootprintUi = create<FootprintUiState>()(
  persist(
    (set) => ({
      collapsed: {},
      setCollapsed: (id, collapsed) => set((s) => ({ collapsed: { ...s.collapsed, [id]: collapsed } })),
    }),
    { name: 'pf-footprint-ui', version: 1, storage: createJSONStorage(() => localStorage) },
  ),
)

interface GeneratorUiState {
  /** Auswahl der Gehäusefamilie offen (Strg+F, „Neuer Footprint“ aus der Bibliothek) */
  pickerOpen: boolean
  setPickerOpen: (open: boolean) => void
}

/** Flüchtiger UI-Zustand des Generators (nicht gespeichert) */
export const useGeneratorUi = create<GeneratorUiState>()((set) => ({
  pickerOpen: false,
  setPickerOpen: (pickerOpen) => set({ pickerOpen }),
}))
