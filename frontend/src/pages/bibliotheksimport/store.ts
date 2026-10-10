/**
 * Zustand des Bibliotheksimports:
 *
 * - `useRecentSources` – zuletzt eingelesene Quellen (dauerhaft je Browser: localStorage + Cookie über
 *   `prefsStorage`, das Desktop-Programm startet jedes Mal auf einem anderen Port). Mit der Scan-ID, damit eine
 *   abgelaufene Quelle aus der Adresse (`?scan=…`) erneut eingelesen werden kann.
 * - `useImportSession` – laufendes Einlesen, angezeigter Scan und der Import-Job dazu (sessionStorage: übersteht
 *   Neuladen und Seitenwechsel, gilt aber nur für die geöffnete Bibliothek – ein Wechsel verwirft ihn).
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { prefsStorage } from '@/lib/prefs'
import { pathKey } from './model'

/** So viele zuletzt eingelesene Quellen merkt sich die Seite */
export const MAX_RECENT_SOURCES = 6

export interface RecentSource {
  path: string
  /** Scan dieser Quelle (bleibt einige Stunden im Backend) */
  scanId: string | null
  /** Zeitpunkt (ms seit Epoche) */
  at: number
}

interface RecentSourcesState {
  recent: RecentSource[]
  remember: (path: string, scanId: string | null) => void
  forget: (path: string) => void
}

export const useRecentSources = create<RecentSourcesState>()(
  persist(
    (set) => ({
      recent: [],
      remember: (path, scanId) =>
        set((s) => ({
          recent: [{ path, scanId, at: Date.now() }, ...s.recent.filter((r) => pathKey(r.path) !== pathKey(path))].slice(
            0,
            MAX_RECENT_SOURCES,
          ),
        })),
      forget: (path) => set((s) => ({ recent: s.recent.filter((r) => pathKey(r.path) !== pathKey(path)) })),
    }),
    {
      name: 'pf-bibliotheksimport',
      version: 1,
      storage: createJSONStorage(() => prefsStorage),
      partialize: (s) => ({ recent: s.recent }),
    },
  ),
)

/** Import-Job eines Scans (mit den Angaben, die das Ergebnis braucht) */
export interface ImportRun {
  jobId: string
  scanId: string
  /** Zielordner (bereinigt) */
  target: string
  convert: boolean
}

interface ImportSessionState {
  /** Bibliothek, zu der die Sitzung gehört */
  workspace: string | null
  /** Bibliothek gewechselt → Sitzung verwerfen. `true` = es war vorher eine andere Bibliothek geöffnet. */
  syncWorkspace: (root: string | null) => boolean
  /** laufendes (bzw. zuletzt beendetes) Einlesen */
  scanJobId: string | null
  setScanJob: (id: string | null) => void
  /** angezeigter Scan (die Adresse `?scan=` geht vor) */
  scanId: string | null
  setScan: (id: string | null) => void
  run: ImportRun | null
  setRun: (run: ImportRun | null) => void
  /** „Weitere Quelle importieren“: alles verwerfen */
  reset: () => void
}

function sessionStore(): Storage {
  return window.sessionStorage
}

export const useImportSession = create<ImportSessionState>()(
  persist(
    (set, get) => ({
      workspace: null,
      syncWorkspace: (root) => {
        const before = get().workspace
        if (before === root) return false
        set({ workspace: root, scanJobId: null, scanId: null, run: null })
        return before !== null
      },
      scanJobId: null,
      setScanJob: (scanJobId) => set({ scanJobId }),
      scanId: null,
      setScan: (scanId) => set({ scanId }),
      run: null,
      setRun: (run) => set({ run }),
      reset: () => set({ scanJobId: null, scanId: null, run: null }),
    }),
    {
      name: 'pf-bibliotheksimport-sitzung',
      version: 1,
      storage: createJSONStorage(sessionStore),
      partialize: (s) => ({ workspace: s.workspace, scanJobId: s.scanJobId, scanId: s.scanId, run: s.run }),
    },
  ),
)
