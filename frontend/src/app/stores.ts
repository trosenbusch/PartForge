/**
 * Globale UI-Zustände (zustand).
 *
 * - useUi:          Sidebar, Theme-Präferenz, Befehlspalette, Bibliotheks-Dialoge
 * - useJobDock:     Job-Dock (aufgeklappt, ausgeblendete Jobs, hervorgehobener Job)
 * - useDroppedFiles: per Drag & Drop abgelegte Datenblätter (Übergabe an /import)
 */
import { useEffect } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { ThemePreference } from '@/api/system'
import { prefsStorage, readPref, writePref } from '@/lib/prefs'

// --------------------------------------------------------------------------- Theme-Persistenz
/** localStorage + Cookie (überlebt den Neustart trotz wechselndem Port), siehe lib/prefs.ts und index.html */
export const THEME_STORAGE_KEY = 'pf-theme'

function readStoredTheme(): ThemePreference | null {
  const raw = readPref(THEME_STORAGE_KEY)
  return raw === 'dark' || raw === 'light' || raw === 'system' ? raw : null
}

function writeStoredTheme(theme: ThemePreference) {
  writePref(THEME_STORAGE_KEY, theme)
}

// --------------------------------------------------------------------------- UI-Store
export type LibraryDialog = 'create' | 'open' | null

interface UiState {
  sidebarCollapsed: boolean
  setSidebarCollapsed: (collapsed: boolean) => void
  toggleSidebar: () => void

  /** Theme-Präferenz (wird in localStorage „pf-theme“ als Klartext gespeichert) */
  theme: ThemePreference
  /** true, wenn der Nutzer das Theme bereits selbst gewählt hat (sonst gilt die Backend-Einstellung) */
  themeExplicit: boolean
  setTheme: (theme: ThemePreference) => void

  commandPaletteOpen: boolean
  setCommandPaletteOpen: (open: boolean) => void
  toggleCommandPalette: () => void

  /** Dialog „Neue Bibliothek“ / „Bibliothek öffnen“ (von überall aufrufbar) */
  libraryDialog: LibraryDialog
  /** Vorbelegter Ordnerpfad für den Dialog */
  libraryDialogPath: string | null
  setLibraryDialog: (dialog: LibraryDialog, presetPath?: string | null) => void
}

const storedTheme = readStoredTheme()

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

      theme: storedTheme ?? 'dark',
      themeExplicit: storedTheme !== null,
      setTheme: (theme) => {
        writeStoredTheme(theme)
        set({ theme, themeExplicit: true })
      },

      commandPaletteOpen: false,
      setCommandPaletteOpen: (commandPaletteOpen) => set({ commandPaletteOpen }),
      toggleCommandPalette: () => set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),

      libraryDialog: null,
      libraryDialogPath: null,
      setLibraryDialog: (libraryDialog, presetPath = null) =>
        set({ libraryDialog, libraryDialogPath: presetPath, commandPaletteOpen: false }),
    }),
    {
      name: 'pf-ui',
      version: 1,
      storage: createJSONStorage(() => prefsStorage),
      partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed }),
    },
  ),
)

// --------------------------------------------------------------------------- Job-Dock
interface JobDockState {
  /** Panel aufgeklappt */
  open: boolean
  setOpen: (open: boolean) => void
  toggle: () => void
  /** Job, dessen Log aufgeklappt ist */
  expandedId: string | null
  toggleExpanded: (id: string) => void
  /** Vom Nutzer ausgeblendete (abgeschlossene) Jobs */
  dismissed: string[]
  dismiss: (ids: string | string[]) => void
  /**
   * Jobs, die eine Seite gerade selbst zeigt (`trackJob(job, { dock: false })`, `useInlineJob`): Sie zählen nicht in der
   * Pille (Ring, Zähler, Einblenden), stehen aber weiter im Panel.
   */
  inline: string[]
  setInline: (id: string, inline: boolean) => void
  /** Zuletzt gestarteter Job (kurz hervorgehoben) */
  highlightId: string | null
  /** Job im Dock anzeigen (z. B. nach dem Start); öffnet optional das Panel */
  reveal: (id: string, open?: boolean) => void
  /** Panel öffnen und das Log eines Jobs aufklappen (Aktion „Details“ der Job-Toasts) */
  showLog: (id: string) => void
  /** Dock ist sichtbar (Toasts weichen nach oben aus) */
  visible: boolean
  setVisible: (visible: boolean) => void
  /** Gemessene Höhe des Docks (Pille + ggf. Panel) in px – Abstand für Toasts */
  height: number
  setHeight: (height: number) => void
  /**
   * Platz, den die Pille unten rechts belegt (Höhe + Randabstand, px; 0 = ausgeblendet) – auch als CSS-Variable
   * `--pf-dock-reserve` (bzw. `--pf-dock-width`) auf `<html>`. Das aufgeklappte Panel zählt nicht (schwebt nur kurz).
   */
  reserve: { block: number; inline: number }
  setReserve: (reserve: { block: number; inline: number }) => void

  // --- Ruhezustand der Pille (vom JobDock gesteuert; nicht gespeichert)
  /** Erste Jobliste gesehen (vorher zeigt das Dock nichts – kein Aufblitzen alter Jobs) */
  booted: boolean
  /**
   * Zeitpunkt (ms) der ersten Jobliste: Jobs, die davor schon fertig waren, sind Historie – sie stehen im Panel, färben
   * aber weder Ring noch Schlagzeile der Pille („Job fehlgeschlagen“ nach einem Neuladen wäre keine Neuigkeit)
   */
  bootedAt: number | null
  /** Signatur der Jobliste (`id:status,…`), bei der die Pille ausgeblendet wurde */
  idleHiddenFor: string | null
  /** Signatur, bei der die Pille mit ungesehenen Fehlschlägen zum runden Hinweis verkleinert wurde */
  idleCompactFor: string | null
  /** Fehlschläge, die der Nutzer gesehen hat (Panel war offen) */
  seenFailures: string[]
  bootIdle: (signature: string | null, failed: string[]) => void
  hideIdle: (signature: string) => void
  compactIdle: (signature: string) => void
  markFailuresSeen: (ids: string[]) => void
}

/** Nach dem Zuklappen bleibt die Pille noch kurz sichtbar (Ruhe-Zeitgeber startet neu) */
const idleReset = { idleHiddenFor: null, idleCompactFor: null }

export const useJobDock = create<JobDockState>()(
  persist(
    (set) => ({
      open: false,
      setOpen: (open) => set((s) => (s.open && !open ? { open, ...idleReset } : { open })),
      toggle: () => set((s) => (s.open ? { open: false, ...idleReset } : { open: true })),
      expandedId: null,
      toggleExpanded: (id) => set((s) => ({ expandedId: s.expandedId === id ? null : id })),
      dismissed: [],
      dismiss: (ids) =>
        set((s) => {
          const list = Array.isArray(ids) ? ids : [ids]
          return { dismissed: [...new Set([...s.dismissed, ...list])].slice(-300) }
        }),
      inline: [],
      setInline: (id, inline) =>
        set((s) => {
          const has = s.inline.includes(id)
          if (has === inline) return s
          return { inline: inline ? [...s.inline, id].slice(-100) : s.inline.filter((x) => x !== id) }
        }),
      highlightId: null,
      reveal: (id, open = true) =>
        set((s) => ({
          highlightId: id,
          open: open || s.open,
          dismissed: s.dismissed.filter((d) => d !== id),
        })),
      showLog: (id) =>
        set((s) => ({
          open: true,
          expandedId: id,
          highlightId: id,
          dismissed: s.dismissed.filter((d) => d !== id),
        })),
      visible: false,
      setVisible: (visible) => set({ visible }),
      height: 0,
      setHeight: (height) => set({ height }),
      reserve: { block: 0, inline: 0 },
      setReserve: (reserve) =>
        set((s) => (s.reserve.block === reserve.block && s.reserve.inline === reserve.inline ? s : { reserve })),
      booted: false,
      bootedAt: null,
      idleHiddenFor: null,
      idleCompactFor: null,
      seenFailures: [],
      bootIdle: (signature, failed) =>
        set((s) =>
          s.booted
            ? s
            : { booted: true, bootedAt: Date.now(), idleHiddenFor: signature, seenFailures: [...new Set([...s.seenFailures, ...failed])] },
        ),
      hideIdle: (signature) => set({ idleHiddenFor: signature }),
      compactIdle: (signature) => set({ idleCompactFor: signature }),
      markFailuresSeen: (ids) =>
        set((s) => (ids.every((id) => s.seenFailures.includes(id)) ? s : { seenFailures: [...new Set([...s.seenFailures, ...ids])].slice(-300) })),
    }),
    {
      name: 'pf-jobdock',
      version: 1,
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ dismissed: s.dismissed }),
    },
  ),
)

// --------------------------------------------------------------------------- Abgelegte Dateien
export interface DroppedFile {
  id: string
  file: File
  name: string
  size: number
  addedAt: number
}

interface DroppedFilesState {
  files: DroppedFile[]
  /** Dateien hinzufügen (Duplikate nach Name+Größe werden ignoriert) */
  add: (files: File[]) => DroppedFile[]
  remove: (id: string) => void
  clear: () => void
  /** Alle Dateien entnehmen und den Store leeren – für die Import-Seite */
  take: () => DroppedFile[]
  /** > 0: globales Drop-Overlay ist unterdrückt (Seite hat eigene Drop-Zone) */
  suppressCount: number
  suppress: () => () => void
}

let fileCounter = 0

export const useDroppedFiles = create<DroppedFilesState>()((set, get) => ({
  files: [],
  add: (files) => {
    const existing = get().files
    const fresh = files
      .filter((f) => !existing.some((e) => e.name === f.name && e.size === f.size))
      .map<DroppedFile>((file) => ({
        id: `drop-${Date.now().toString(36)}-${(fileCounter++).toString(36)}`,
        file,
        name: file.name,
        size: file.size,
        addedAt: Date.now(),
      }))
    if (fresh.length) set({ files: [...existing, ...fresh] })
    return fresh
  },
  remove: (id) => set((s) => ({ files: s.files.filter((f) => f.id !== id) })),
  clear: () => set({ files: [] }),
  take: () => {
    const files = get().files
    set({ files: [] })
    return files
  },
  suppressCount: 0,
  suppress: () => {
    set((s) => ({ suppressCount: s.suppressCount + 1 }))
    let released = false
    return () => {
      if (released) return
      released = true
      set((s) => ({ suppressCount: Math.max(0, s.suppressCount - 1) }))
    }
  },
}))

/** Globales Datenblatt-Drop-Overlay unterdrücken, solange die Komponente gemountet ist. */
export function useSuppressGlobalDrop(active = true): void {
  useEffect(() => {
    if (!active) return
    return useDroppedFiles.getState().suppress()
  }, [active])
}
