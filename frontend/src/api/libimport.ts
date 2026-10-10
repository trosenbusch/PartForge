import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, apiUrl, ApiError } from './client'
import type { Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

/** Job „Bibliothek einlesen“ (liest nur) */
export const SCAN_JOB_KIND = 'library-import.scan'
/** Job „Bibliotheksimport“ (schreibt, hält die Bibliothek) */
export const IMPORT_JOB_KIND = 'libraries.import'

export type ImportScan = Filled<ResponseOf<'/api/library-import/scans/{scan_id}', 'get'>>
export type ImportSourceFile = ImportScan['files'][number]
export type ImportSourceComponent = ImportSourceFile['components'][number]
export type ImportComponentState = ImportSourceComponent['state']
export type ImportOptions = RequestBodyOf<'/api/library-import/run', 'post'>
export type PreviewTheme = 'altium' | 'dark' | 'light'

/** `job.result` von „Bibliothek einlesen“ (`library-import.scan`) */
export interface ImportScanSummary {
  id: string
  source: string
  name: string
  files: number
  symbols: number
  footprints: number
  new: number
  taken: number
  duplicates: number
  imported: number
  notes: string[]
  message: string
}

export interface ImportConflict {
  kind: 'symbol' | 'footprint'
  name: string
  library: string
  registered_library: string | null
  reason: string
}

/** `job.result` des Imports (`libraries.import`) */
export interface ImportRunResult {
  copied: number
  unchanged: number
  symbols: number
  footprints: number
  libraries: string[]
  conflicts: ImportConflict[]
  skipped: { rel: string; reason: string }[]
  errors: { rel: string; message: string }[]
  /**
   * Beim Ersetzen geänderter Dateien abgemeldete Namen: schon importierte Symbole bzw. Footprints, die die neue Fassung
   * der Datei nicht mehr enthält (fehlt bei älteren Backends)
   */
  removed?: { kind: 'symbol' | 'footprint'; name: string; library: string }[]
  conversion: {
    components: number
    libraries: string[]
    skipped: { library: string; message: string }[]
    errors: { library: string; message: string }[]
    undo: string | null
    message: string
  } | null
  message: string
}

export interface PartsTableUpload {
  token: string
  file_name: string
  rows: number
}

export const STATE_LABELS: Record<ImportComponentState, string> = {
  new: 'neu',
  get imported() { return tr("schon importiert") },
  get taken() { return tr("Name vergeben") },
  duplicate: 'doppelt',
}

export const libImportKeys = {
  all: ['library-import'] as const,
  /** `target`: anderer Zielordner als der Vorschlag des Scans (`null` = Vorschlag) */
  scan: (id: string, target: string | null = null) => ['library-import', 'scan', id, target] as const,
}

export const libImportApi = {
  scan: (path: string) => api.post<{ job: Job<ImportScanSummary> }>('/api/library-import/scan', { path }),
  /** Scan – mit `target` so, wie er in diesen Zielordner importierte (Ziele, vorhandene Dateien, Namenszustände) */
  getScan: (id: string, signal?: AbortSignal, target?: string | null) =>
    api.get<ImportScan>(`/api/library-import/scans/${encodeURIComponent(id)}`, {
      signal,
      query: target ? { target } : undefined,
    }),
  run: (options: ImportOptions) => api.post<{ job: Job<ImportRunResult> }>('/api/library-import/run', options),
  partsTable: (body: { libraries?: string[] | null; names?: string[] | null }) =>
    api.post<PartsTableUpload>('/api/library-import/parts-table', body),
  /** SVG-Vorschau eines Bauteils der Quelle (Token im Query – für `<img>`) */
  previewUrl: (scanId: string, rel: string, name: string, theme: PreviewTheme = 'dark') =>
    apiUrl('/api/library-import/preview', { scan_id: scanId, rel, name, theme }),
}

/**
 * Vollständiger Scan (alle Dateien und Namen) – bleibt im Backend einige Stunden erhalten. Mit `target` (anderer
 * Zielordner als der Vorschlag) berechnet das Backend Ziele, vorhandene Dateien und Namenszustände für diesen Ordner
 * neu, ohne die Quelle erneut zu lesen.
 */
export function useImportScan(id: string | null | undefined, target: string | null = null) {
  return useQuery({
    queryKey: libImportKeys.scan(id ?? '', target),
    queryFn: ({ signal }) => libImportApi.getScan(id as string, signal, target),
    enabled: Boolean(id),
    staleTime: Infinity,
    retry: false,
  })
}

/** Der Scan ist im Backend nicht (mehr) vorhanden – abgelaufen oder verdrängt: erneut einlesen */
export function isScanGone(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/** Quelle einlesen (`POST /api/library-import/scan` → Job) – Fehler zeigt die Seite selbst */
export function useStartLibraryScan() {
  return useMutation({
    mutationFn: (path: string) => libImportApi.scan(path),
    meta: { silentError: true },
  })
}

/** Import starten (`POST /api/library-import/run` → Job `libraries.import`) – Fehler zeigt die Seite selbst */
export function useStartLibraryImport() {
  return useMutation({
    mutationFn: (options: ImportOptions) => libImportApi.run(options),
    meta: { silentError: true },
  })
}

/** Tabelle der importierten Symbole für den Tabellen-Import („Bauteile anlegen“) */
export function usePartsTable() {
  const { t: tr } = useI18n()
  return useMutation({
    mutationFn: (body: { libraries?: string[] | null; names?: string[] | null }) => libImportApi.partsTable(body),
    meta: { errorTitle: tr("Tabelle für „Bauteile anlegen“ nicht erstellt") },
  })
}
