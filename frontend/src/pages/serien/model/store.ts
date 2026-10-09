/**
 * Zustand des Serien-Assistenten: aktueller Schritt, Kategorie, Vorlage, Auswahl je Vorlage und der laufende Job.
 * Schritt und Job gelten für die Sitzung (Seitenwechsel behalten sie); Kategorie, Vorlage je Kategorie, die Auswahl der
 * zuletzt benutzten Vorlagen und der Modus werden dauerhaft gemerkt (`pf-serien`: localStorage vollständig, das
 * portübergreifende Cookie gekürzt auf ~3 KB, siehe {@link cookieValue}).
 */
import { create } from 'zustand'
import { createJSONStorage, persist, type StateStorage } from 'zustand/middleware'
import type { CommitMode } from '@/api/series'
import { readPref, writePref } from '@/lib/prefs'
import type { SeriesSettings } from './settings'

export type StepIndex = 0 | 1 | 2 | 3 | 4
export const LAST_STEP: StepIndex = 4

/** Schritte in der Adresse (`/serien?schritt=werte`) – Zurück/Alt+← wechseln so zwischen den Schritten */
export const STEP_IDS = ['kategorie', 'serie', 'werte', 'vorschau', 'erzeugen'] as const
export type StepId = (typeof STEP_IDS)[number]

export function stepFromParam(value: string | null): StepIndex | null {
  const index = (STEP_IDS as readonly string[]).indexOf(value ?? '')
  return index >= 0 ? (index as StepIndex) : null
}

/** Was die Vorschau beim Start versprach – für die Abschnitte des Fortschritts (Zähler erledigter Abschnitte) */
export interface JobPlan {
  /** Zeilen der Vorschau */
  rows: number
  /** Bauteile, die geschrieben werden (neu bzw. neu + vorhanden beim Aktualisieren) */
  writes: number
  /** neue Footprints */
  footprints: number
  symbol: string | null
  symbolExists: boolean
}

/** Merkmale des gestarteten Jobs (für „In Tabelle anzeigen“ nach dem Erzeugen) */
export interface JobContextInfo {
  id: string
  templateId: string
  title: string
  table: string
  manufacturer: string
  /** gemeinsamer Anfang der Teilenummern (Tabellenfilter) */
  prefix: string
  plan: JobPlan
}

/** Wie viele Vorlagen ihre Auswahl behalten */
const MAX_REMEMBERED = 6
const MAX_LIST_CHARS = 600
/**
 * Höchstlänge des Cookies (kodiert). Browser verwerfen Cookies über ~4 KB stillschweigend – dann bliebe nach einem
 * Neustart (neuer Port, leerer localStorage) ein veralteter Stand stehen.
 */
const COOKIE_LIMIT = 3000

interface Persisted {
  state: {
    recent?: string[]
    settings?: Record<string, Partial<SeriesSettings>>
    [key: string]: unknown
  }
  version?: number
}

/**
 * Fassung für das Cookie: höchstens {@link COOKIE_LIMIT} Zeichen. Zuerst fallen die Wertelisten weg, dann die
 * Auswahl der am längsten nicht benutzten Vorlagen. localStorage behält alles.
 */
export function cookieValue(json: string): string | null {
  const fits = (s: string) => encodeURIComponent(s).length <= COOKIE_LIMIT
  if (fits(json)) return json
  let data: Persisted
  try {
    data = JSON.parse(json) as Persisted
  } catch {
    return null
  }
  const settings = { ...(data.state.settings ?? {}) }
  for (const id of Object.keys(settings)) settings[id] = { ...settings[id], valuesText: '' }
  // neueste zuerst; Auswahl ohne Eintrag in „recent“ fällt zuerst weg
  const order = (data.state.recent ?? []).filter((id) => id in settings)
  for (const id of Object.keys(settings)) if (!order.includes(id)) order.push(id)
  const encode = () => JSON.stringify({ ...data, state: { ...data.state, settings } })
  let out = encode()
  while (!fits(out) && order.length) {
    delete settings[order.pop() as string]
    out = encode()
  }
  return fits(out) ? out : null
}

/** localStorage bekommt die volle Fassung, das Cookie (portübergreifend) die gekürzte */
const serienStorage: StateStorage = {
  getItem: (name) => readPref(name),
  setItem: (name, value) => {
    writePref(name, cookieValue(value))
    try {
      localStorage.setItem(name, value)
    } catch {
      // Speicher gesperrt – das Cookie reicht
    }
  },
  removeItem: (name) => writePref(name, null),
}

interface SerienState {
  /** Bibliothek, zu der Schritt, Vorlage und Job gehören */
  workspace: string | null
  syncWorkspace: (root: string | null) => void
  step: StepIndex
  setStep: (step: StepIndex) => void
  category: string | null
  setCategory: (table: string | null) => void
  templateId: string | null
  setTemplate: (id: string | null) => void
  lastTemplate: Record<string, string>
  settings: Record<string, Partial<SeriesSettings>>
  /** zuletzt benutzte Vorlagen, neueste zuerst */
  recent: string[]
  saveSettings: (templateId: string, settings: SeriesSettings) => void
  mode: CommitMode
  setMode: (mode: CommitMode) => void
  job: JobContextInfo | null
  setJob: (job: JobContextInfo | null) => void
  /** Neue Serie: zurück zu Schritt 1 (gemerkte Auswahl bleibt) */
  restart: () => void
}

export const useSerien = create<SerienState>()(
  persist(
    (set) => ({
      workspace: null,
      syncWorkspace: (root) => set((s) => (s.workspace === root ? s : { workspace: root, step: 0, job: null })),
      step: 0,
      setStep: (step) => set({ step }),
      category: null,
      setCategory: (category) => set({ category }),
      templateId: null,
      setTemplate: (templateId) =>
        set((s) => {
          if (!templateId) return { templateId }
          const recent = [templateId, ...s.recent.filter((id) => id !== templateId)].slice(0, MAX_REMEMBERED)
          return { templateId, recent }
        }),
      lastTemplate: {},
      settings: {},
      recent: [],
      saveSettings: (templateId, settings) =>
        set((s) => {
          const recent = s.recent.includes(templateId) ? s.recent : [templateId, ...s.recent].slice(0, MAX_REMEMBERED)
          const kept: Record<string, Partial<SeriesSettings>> = {}
          for (const id of recent) if (s.settings[id]) kept[id] = s.settings[id]
          kept[templateId] = settings
          return { settings: kept, recent }
        }),
      mode: 'skip',
      setMode: (mode) => set({ mode }),
      job: null,
      setJob: (job) => set({ job }),
      restart: () => set({ step: 0, job: null }),
    }),
    {
      name: 'pf-serien',
      version: 1,
      storage: createJSONStorage(() => serienStorage),
      partialize: (s) => ({
        category: s.category,
        templateId: s.templateId,
        lastTemplate: s.lastTemplate,
        recent: s.recent,
        mode: s.mode,
        settings: Object.fromEntries(
          s.recent
            .filter((id) => s.settings[id])
            .map((id) => {
              const v = s.settings[id]
              // lange Wertelisten nicht ins Cookie
              const list = typeof v.valuesText === 'string' && v.valuesText.length > MAX_LIST_CHARS ? '' : v.valuesText
              return [id, { ...v, valuesText: list }]
            }),
        ),
      }),
    },
  ),
)

/** Kategorie und Vorlage gemeinsam setzen (Vorlage wird je Kategorie gemerkt) */
export function chooseTemplate(category: string, templateId: string): void {
  const st = useSerien.getState()
  useSerien.setState({ category, lastTemplate: { ...st.lastTemplate, [category]: templateId } })
  st.setTemplate(templateId)
}
