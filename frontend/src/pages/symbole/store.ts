/**
 * Zustand des Symbol-Generators: gewählter Symboltyp, Parameter je Typ, IC-Entwurf (Pinliste) mit
 * Rückgängig/Wiederholen. Der Entwurf überlebt Seitenwechsel (localStorage – Pinlisten sind zu groß für Cookies).
 * Ansichts-Vorlieben (eingeklappte Bereiche, Spalten) liegen getrennt in `useSymbolUiPrefs` (Cookie + localStorage).
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { IcPin, SymbolRequest } from '@/api/symbols'
import { prefsStorage } from '@/lib/prefs'
import { toIcPin, type PinRow } from './ic/pins'

export const IC_KIND = 'ic'

export type PartsMode = '1' | 'auto' | 'fixed'
export type IcOrder = 'name' | 'designator' | 'input'

/**
 * Bibliothekssymbol, aus dem ein Entwurf geladen wurde („Bearbeiten“): Speichern unter einem neuen Namen legt die
 * Kopie in dieselbe SchLib (statt in die Standard-Bibliothek des Symboltyps, z. B. PF_ICs.SchLib).
 */
export interface DraftOrigin {
  name: string
  /** Bibliotheksdatei (relativ zum Bibliotheksordner), z. B. „Symbols\PF_Power.SchLib“ */
  library: string
}

export interface IcDraft {
  name: string
  description: string
  prefix: string
  partsMode: PartsMode
  /** Anzahl bei `partsMode = 'fixed'` */
  partCount: number
  order: IcOrder
  maxPinsPerSide: number
  pins: PinRow[]
  origin?: DraftOrigin | null
}

export interface StandardExtras {
  prefix: string
  description: string
  /** Eigener Symbolname (leer = Name nach Hausstil) */
  name: string
  /** Eigene Pinnamen eines Steckverbinders (aus der Bibliothek übernommen, unverändert durchgereicht) */
  pins?: IcPin[]
  origin?: DraftOrigin | null
}

export const EMPTY_EXTRAS: StandardExtras = { prefix: '', description: '', name: '' }

export const EMPTY_IC: IcDraft = {
  name: '',
  description: '',
  prefix: '',
  partsMode: '1',
  partCount: 2,
  order: 'name',
  maxPinsPerSide: 40,
  pins: [],
}

const HISTORY_LIMIT = 60
/** Tippen in dasselbe Feld innerhalb dieser Zeit ergibt nur einen Rückgängig-Schritt */
const COALESCE_MS = 1500

interface GeneratorState {
  kind: string
  /** Vom Standard abweichende Parameter je Symboltyp */
  params: Record<string, Record<string, unknown>>
  extras: Record<string, StandardExtras>
  ic: IcDraft
  past: IcDraft[]
  future: IcDraft[]
  lastEdit: { key: string; at: number } | null

  setKind: (kind: string) => void
  setParam: (kind: string, name: string, value: unknown, isDefault: boolean) => void
  resetParams: (kind: string) => void
  setExtras: (kind: string, patch: Partial<StandardExtras>) => void
  /** Standard-Symbol laden (z. B. „Bearbeiten“ aus der Bibliothek) */
  loadStandard: (kind: string, params: Record<string, unknown>, extras: Partial<StandardExtras>) => void
  /** IC-Entwurf ändern; gleicher `coalesceKey` kurz hintereinander = ein Rückgängig-Schritt */
  updateIc: (change: (draft: IcDraft) => IcDraft, coalesceKey?: string) => void
  /** IC-Entwurf ersetzen (mit Rückgängig-Schritt) und zum IC-Editor wechseln */
  loadIc: (draft: IcDraft) => void
  undo: () => void
  redo: () => void
}

export const useGenerator = create<GeneratorState>()(
  persist(
    (set, get) => ({
      kind: 'resistor',
      params: {},
      extras: {},
      ic: EMPTY_IC,
      past: [],
      future: [],
      lastEdit: null,

      setKind: (kind) => set({ kind }),
      setParam: (kind, name, value, isDefault) =>
        set((s) => {
          const current = { ...(s.params[kind] ?? {}) }
          if (isDefault) delete current[name]
          else current[name] = value
          return { params: { ...s.params, [kind]: current } }
        }),
      resetParams: (kind) => set((s) => ({ params: { ...s.params, [kind]: {} }, extras: { ...s.extras, [kind]: EMPTY_EXTRAS } })),
      setExtras: (kind, patch) =>
        set((s) => ({
          extras: { ...s.extras, [kind]: { ...EMPTY_EXTRAS, ...s.extras[kind], ...patch } },
        })),
      loadStandard: (kind, params, extras) =>
        set((s) => ({
          kind,
          params: { ...s.params, [kind]: { ...params } },
          extras: { ...s.extras, [kind]: { ...EMPTY_EXTRAS, ...extras } },
        })),

      updateIc: (change, coalesceKey) => {
        const s = get()
        const next = change(s.ic)
        if (next === s.ic) return
        const now = Date.now()
        const coalesce =
          coalesceKey !== undefined && s.lastEdit?.key === coalesceKey && now - s.lastEdit.at < COALESCE_MS && s.past.length > 0
        set({
          ic: next,
          past: coalesce ? s.past : [...s.past, s.ic].slice(-HISTORY_LIMIT),
          future: [],
          lastEdit: coalesceKey !== undefined ? { key: coalesceKey, at: now } : null,
        })
      },
      loadIc: (draft) => {
        const s = get()
        set({ kind: IC_KIND, ic: draft, past: [...s.past, s.ic].slice(-HISTORY_LIMIT), future: [], lastEdit: null })
      },
      undo: () => {
        const s = get()
        const prev = s.past[s.past.length - 1]
        if (!prev) return
        set({ ic: prev, past: s.past.slice(0, -1), future: [s.ic, ...s.future].slice(0, HISTORY_LIMIT), lastEdit: null })
      },
      redo: () => {
        const s = get()
        const next = s.future[0]
        if (!next) return
        set({ ic: next, past: [...s.past, s.ic].slice(-HISTORY_LIMIT), future: s.future.slice(1), lastEdit: null })
      },
    }),
    {
      name: 'pf-symbole-entwurf',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({ kind: s.kind, params: s.params, extras: s.extras, ic: s.ic }),
    },
  ),
)

/** Anfrage für den IC-Generator (Pins ohne Editor-IDs) */
export function icRequest(d: IcDraft): SymbolRequest {
  const parts = d.partsMode === 'fixed' ? String(Math.max(2, d.partCount)) : d.partsMode
  return {
    kind: IC_KIND,
    name: d.name.trim() || null,
    description: d.description.trim() || null,
    designator_prefix: d.prefix.trim() || null,
    params: { parts, order: d.order, max_pins_per_side: d.maxPinsPerSide },
    pins: d.pins.map(toIcPin),
  }
}

// --------------------------------------------------------------------------- Ansichts-Vorlieben

export type IcTab = 'pins' | 'sides'
export type PinColumn = 'group' | 'part' | 'hidden' | 'description'

interface SymbolUiPrefs {
  /** Symboltypen-Leiste eingeklappt – getrennt für Standard-Symbole und den IC-Editor */
  kindsCollapsed: { standard: boolean; ic: boolean | null }
  /** IC-Eigenschaften eingeklappt; null = automatisch (in niedrigen Fenstern eingeklappt) */
  icPropsCollapsed: boolean | null
  icTab: IcTab
  /** Sichtbare Spalten der Pinliste; null = automatisch (nur bei genug Platz) */
  columns: Record<PinColumn, boolean | null>
  set: (patch: Partial<Omit<SymbolUiPrefs, 'set'>>) => void
}

type StoredPrefs = Partial<Omit<SymbolUiPrefs, 'set'>>

export const useSymbolUiPrefs = create<SymbolUiPrefs>()(
  persist(
    (set) => ({
      kindsCollapsed: { standard: false, ic: null },
      icPropsCollapsed: null,
      icTab: 'pins',
      columns: { group: null, part: null, hidden: null, description: false },
      set: (patch) => set(patch),
    }),
    {
      name: 'pf-symbole',
      version: 2,
      storage: createJSONStorage(() => prefsStorage),
      partialize: (s) => ({ kindsCollapsed: s.kindsCollapsed, icPropsCollapsed: s.icPropsCollapsed, icTab: s.icTab, columns: s.columns }),
      // v1 kannte nur ein- oder ausgeklappt – jetzt passt sich der Bereich der Fensterhöhe an
      migrate: (stored, version) => (version < 2 ? { ...(stored as StoredPrefs), icPropsCollapsed: null } : stored) as StoredPrefs,
    },
  ),
)

// --------------------------------------------------------------------------- Filter der Bibliothek

export type LibrarySort = 'name' | 'usage' | 'updated'
/** Geöffnete Detailansicht: Bibliothekssymbol oder Symboltyp des Katalogs */
export type LibraryDetail = { type: 'symbol'; name: string } | { type: 'kind'; key: string }

interface LibraryFilters {
  query: string
  group: string
  source: string
  status: string
  sort: LibrarySort
  selected: string | null
  detail: LibraryDetail | null
  set: (patch: Partial<Omit<LibraryFilters, 'set' | 'reset' | 'showSymbol'>>) => void
  /** Suche und Filter zurücksetzen (Sortierung und Auswahl bleiben) */
  reset: () => void
  /** Symbol zeigen (z. B. nach dem Speichern): Filter zurücksetzen, auswählen und die Detailansicht öffnen */
  showSymbol: (name: string) => void
}

/** Zustand der Bibliotheksansicht – bleibt beim Wechsel zwischen Generator und Bibliothek erhalten (nur Sitzung). */
export const useLibraryFilters = create<LibraryFilters>()((set) => ({
  query: '',
  group: 'alle',
  source: 'alle',
  status: 'alle',
  sort: 'name',
  selected: null,
  detail: null,
  set: (patch) => set(patch),
  reset: () => set({ query: '', group: 'alle', source: 'alle', status: 'alle' }),
  showSymbol: (name) =>
    set({ query: '', group: 'alle', source: 'alle', status: 'alle', selected: name, detail: { type: 'symbol', name } }),
}))
