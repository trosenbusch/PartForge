/**
 * Sitzungszustand der Stapelbearbeitung je Bibliothek (nur im Speicher, nicht dauerhaft): Auswahl, Regel-Entwurf, die
 * zuletzt gestarteten Jobs und ihre Ergebnisse. Ein Seitenwechsel – etwa zum Hausstil in den Einstellungen und zurück –
 * behält alles; ein Bericht, dessen Auswahl, Regeln oder Hausstil sich seitdem geändert haben, gilt dann als veraltet.
 * Jede Bibliothek hat ihren eigenen Stand (Schlüssel = Bibliotheksordner).
 */
import { create } from 'zustand'
import type { ConformApplyResult, ConformInput, ConformReport, ConformRules, ConformUndoResult } from '@/api/housestyle'
import { DEFAULT_SELECTION, type Selection } from './model'

export type BatchAction = 'check' | 'apply' | 'undo'

/** Gestartete Prüfung: Job, Kennung (Anfrage + Hausstil) und Anfrage */
export interface CheckRun {
  jobId: string
  key: string
  input: ConformInput
}

/** Ergebnis einer Prüfung (bleibt sichtbar, bis eine neue Prüfung fertig ist oder angewendet wird) */
export interface StoredReport extends CheckRun {
  report: ConformReport
  /** Ende der Prüfung (ms) */
  finished: number
}

/** Gestartetes „Anwenden“ mit dem, was der Bericht versprach */
export interface ApplyRun {
  jobId: string
  input: ConformInput
  components: number
  libraries: number
}

export interface StoredResult<T> {
  jobId: string
  result: T
}

export interface BatchSession {
  selection: Selection
  /** Regel-Entwurf; `null` = die zuletzt angewendeten Regeln der Bibliothek (Server) */
  rules: ConformRules | null
  /** zuletzt gestartete Aktion – bestimmt, was rechts im Mittelpunkt steht */
  last: BatchAction | null
  check: CheckRun | null
  /** gültiger Bericht – „Anwenden“ und „Rückgängig“ verbrauchen ihn (die Dateien ändern sich) */
  report: StoredReport | null
  apply: ApplyRun | null
  applyResult: StoredResult<ConformApplyResult> | null
  undo: { jobId: string } | null
  undoResult: StoredResult<ConformUndoResult> | null
}

export const EMPTY_SESSION: BatchSession = {
  selection: DEFAULT_SELECTION,
  rules: null,
  last: null,
  check: null,
  report: null,
  apply: null,
  applyResult: null,
  undo: null,
  undoResult: null,
}

type Patch = Partial<BatchSession> | ((session: BatchSession) => Partial<BatchSession>)

interface BatchStore {
  sessions: Record<string, BatchSession>
  update: (root: string, patch: Patch) => void
}

export const useBatchStore = create<BatchStore>()((set) => ({
  sessions: {},
  update: (root, patch) =>
    set((state) => {
      const current = state.sessions[root] ?? EMPTY_SESSION
      const next = typeof patch === 'function' ? patch(current) : patch
      return { sessions: { ...state.sessions, [root]: { ...current, ...next } } }
    }),
}))

/** Stand der Bibliothek `root` (ohne Eintrag: Ausgangszustand) */
export function useBatchSession(root: string): BatchSession {
  return useBatchStore((s) => s.sessions[root] ?? EMPTY_SESSION)
}

/** Stand außerhalb von Komponenten (Rückrufe von Jobs) */
export function getBatchSession(root: string): BatchSession {
  return useBatchStore.getState().sessions[root] ?? EMPTY_SESSION
}

export function updateBatchSession(root: string, patch: Patch): void {
  useBatchStore.getState().update(root, patch)
}
