/**
 * Vorlieben der Vorschau (Altium-Ansicht, Lagen, Bemaßung, Drehung) – geteilt zwischen allen PreviewPanels und
 * dauerhaft gespeichert (localStorage + Cookie über `prefsStorage`, siehe lib/prefs.ts).
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { prefsStorage } from '@/lib/prefs'
import type { LayerVisibility } from './layerVisibility'

export interface PreviewPrefs {
  /** Symbol im Altium-Stil (weißes Blatt) */
  altium: boolean
  /** Abweichungen von der Standard-Sichtbarkeit der Lagen */
  layers: LayerVisibility
  /** Bemaßung im Footprint */
  dimensions: boolean
  /** Pad-Nummern */
  padNumbers: boolean
  /** 3D automatisch drehen */
  autoRotate: boolean
  set: (patch: Partial<Omit<PreviewPrefs, 'set'>>) => void
}

export const usePreviewPrefs = create<PreviewPrefs>()(
  persist(
    (set) => ({
      altium: false,
      layers: {},
      dimensions: true,
      padNumbers: true,
      autoRotate: false,
      set: (patch) => set(patch),
    }),
    {
      name: 'pf-preview',
      version: 1,
      storage: createJSONStorage(() => prefsStorage),
      partialize: (s) => ({
        altium: s.altium,
        layers: s.layers,
        dimensions: s.dimensions,
        padNumbers: s.padNumbers,
        autoRotate: s.autoRotate,
      }),
    },
  ),
)
