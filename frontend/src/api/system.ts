import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { toMillis } from '@/lib/format'
import { prefsStorage } from '@/lib/prefs'
import { api, ApiError, apiUrl, cleanErrorText, errorMessage, observeApi } from './client'
import { queryClient } from './queryClient'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

export type { Filled } from './types'

// --------------------------------------------------------------------------- Typen (abgeleitet aus den Endpunkten)

type SettingsResponse = Filled<ResponseOf<'/api/settings', 'get'>>

/** Woher der Claude-API-Schlüssel stammt (der Schlüssel selbst verlässt das Backend nie); `replay` = Testmodus. */
export type ApiKeySource = 'env' | 'stored' | 'file' | 'replay'

export type SettingsOut = Omit<SettingsResponse, 'ai_key_source'> & { ai_key_source: ApiKeySource | null }
export type AppSettings = SettingsOut['settings']
export type AISettings = AppSettings['ai']
export type AltiumSettings = AppSettings['altium']
export type ThemePreference = AppSettings['theme']
export type LibraryBackend = AltiumSettings['library_backend']
export type AiEffort = AISettings['effort']

export type WorkspaceSettings = Filled<RequestBodyOf<'/api/workspace/settings', 'put'>>
export type DbSettings = WorkspaceSettings['db']
export type WorkspaceFolders = WorkspaceSettings['folders']
export type LayerMap = WorkspaceSettings['layers']
export type FootprintStyle = WorkspaceSettings['footprint']
/** Eigener Lagensatz der PcbLibs (Altium „Layer Sets“) */
export type LayerSetSettings = WorkspaceSettings['layer_set']
export type SymbolStyle = WorkspaceSettings['symbol']
export type RecentWorkspace = Filled<ResponseOf<'/api/workspace/recent', 'get'>>[number]
export type CreateWorkspaceInput = RequestBodyOf<'/api/workspace/create', 'post'>

/** GET /api/workspace (Backend: `Workspace.info()`, untypisiertes dict) */
export interface WorkspaceInfo {
  root: string
  name: string
  db_kind: DbSettings['kind']
  sqlite_path: string
  dblib_path: string
  settings: WorkspaceSettings
  /** Deutsche Hinweise zur Bibliothek (z. B. gleichnamige DbLib einer anderen Bibliothek bzw. in Altium installiert) */
  warnings?: string[]
}

/** Eine bekannte DbLib-Datei (in Altium installiert bzw. einer anderen Bibliothek) – gleicher Dateiname kollidiert */
export interface DbLibNameUse {
  file_name: string
  path: string
  /** `true` = in Altium installiert (letzte Prüfung), `null` = unbekannt (andere Bibliothek) */
  installed: boolean | null
  /** Bibliotheksordner, falls bekannt */
  library: string | null
}

/**
 * `GET /api/workspace/defaults?name=…`: Vorschlag für „Neue Bibliothek anlegen“ – neutraler Ordner unter den Dokumenten
 * des Benutzers (`parent`), ein Name, dessen Ordner es noch nicht gibt, ein eindeutiger DbLib-Dateiname und alle
 * bekannten DbLib-Dateien (`dblib_taken`).
 */
export interface WorkspaceDefaults {
  parent: string
  name: string
  path: string
  dblib_file: string
  dblib_taken: DbLibNameUse[]
}

/** Anzahl der angelegten Beispielinhalte (`POST /api/workspace/create`, `with_examples`) */
export interface CreatedExamples {
  parts: number
  symbols: number
  footprints: number
}

/**
 * POST /api/workspace/create: Workspace-Info plus Beispielinhalte und der Job „Bibliotheken schreiben“
 * (`null` ohne Beispiele bzw. mit `write_libraries: false`).
 */
export interface CreatedWorkspace extends WorkspaceInfo {
  examples?: CreatedExamples | null
  /** Deutscher Fehlertext, wenn die Beispiele nicht angelegt werden konnten (die Bibliothek ist trotzdem nutzbar) */
  examples_error?: string | null
  job?: Job | null
}

/** GET /api/health (untypisiertes dict) */
export interface HealthInfo {
  ok: boolean
  version: string
  workspace: WorkspaceInfo | null
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type JobLogLevel = 'info' | 'warn' | 'error' | 'success'

export interface JobLogEntry {
  /** Sekunden seit Epoche (Python time.time()) */
  ts: number
  level: JobLogLevel
  text: string
}

/** `Job.cancel_reason` eines Jobs, den ein Bibliothekswechsel abgebrochen hat (`partforge.jobs.CANCEL_LIBRARY_SWITCH`) */
export const JOB_CANCEL_LIBRARY_SWITCH = 'library_switch'

/**
 * Arten, die Bauteile, Registry-Einträge oder Bibliotheksdateien schreiben und ihre Bibliothek für die ganze Laufzeit
 * halten (`partforge.jobs.LIBRARY_JOB_KINDS`) – ein Bibliothekswechsel bricht sie ab.
 */
export const LIBRARY_JOB_KINDS: ReadonlySet<string> = new Set([
  'libraries',
  'libraries.sync',
  'libraries.scan',
  'libraries.save',
  'libraries.delete',
  'libraries.layers',
  'libraries.import',
  'libraries.conform',
  'altium.edit',
  'libraries.altium-edit',
  'series',
  'datasheet-commit',
  'import',
])

/** Arten, die ein Bibliothekswechsel abbricht: die {@link LIBRARY_JOB_KINDS} und der Export (liest nur, endet dann ohne Datei) */
export const SWITCH_CANCELLED_JOB_KINDS: ReadonlySet<string> = new Set([...LIBRARY_JOB_KINDS, 'export'])

/** Job-Schnappschuss (`partforge/jobs.py`, untypisiertes dict) */
export interface Job<TResult = unknown> {
  id: string
  kind: string
  title: string
  status: JobStatus
  /** 0…1 */
  progress: number
  message: string
  /** Bei GET /api/jobs leer, bei GET /api/jobs/{id} und SSE vollständig */
  log: JobLogEntry[]
  /** In Joblisten (`useJobs`) ggf. gekürzt – siehe `result_truncated` */
  result: TResult | null
  /** Deutscher Fehlertext eines fehlgeschlagenen Jobs (Anzeige über `jobOutcome`/`cleanErrorText`) */
  error: string | null
  /** Ausnahmeklasse eines fehlgeschlagenen Jobs, z. B. `AiUnavailable` – nur zum Auswerten, angezeigt wird `error` */
  error_type?: string | null
  /**
   * Strukturierter Fortschritt (`ctx.detail(…)` im Backend), z. B. `{ step: 'pins', cost_usd: 0.12 }` – statt Logzeilen
   * zu lesen; Zugriff typisiert über `jobDetail<T>(job)` aus `@/api/jobs`
   */
  detail?: Record<string, unknown>
  /** Abbruchgrund: `null` = vom Benutzer, {@link JOB_CANCEL_LIBRARY_SWITCH} = Bibliothek gewechselt/geschlossen */
  cancel_reason?: string | null
  /** Abbruch angefordert (der Job stoppt an seinem nächsten Prüfpunkt) – „Wird abgebrochen …“ */
  cancel_requested?: boolean
  /**
   * Ordner der Bibliothek, für die der Job gestartet wurde (beim Start gesetzt; `null`/fehlt = an keine Bibliothek
   * gebunden bzw. älteres Backend). Seiten zeigen nur Jobs der geöffneten Bibliothek ({@link isJobOfLibrary},
   * {@link useLibraryJobs}), das Job-Dock alle – fremde mit dem Namen ihrer Bibliothek.
   */
  library?: string | null
  /** Name dieser Bibliothek beim Start (für Anzeigen wie „gehört zu „Firmenbibliothek““) */
  library_name?: string | null
  /**
   * Nur in Kurzfassungen (`brief=true`): `result` ist gekürzt (Skalare bleiben, Listen/Objekte → `<name>_count`, von
   * `errors`/`warnings`/`missing` die ersten 5). Volles Ergebnis: `fetchJob(id)` / `useJobResult(id)`.
   */
  result_truncated?: boolean
  created: number
  started: number | null
  finished: number | null
  /** Steigt bei jeder Änderung – ältere Schnappschüsse nie über neuere schreiben */
  version: number
}

export function isJobActive(job: Pick<Job, 'status'>): boolean {
  return job.status === 'queued' || job.status === 'running'
}

export function isJobFinished(job: Pick<Job, 'status'>): boolean {
  return job.status === 'done' || job.status === 'failed' || job.status === 'cancelled'
}

/** Hat ein Bibliothekswechsel (bzw. das Schließen) den Job abgebrochen? */
export function isLibrarySwitchCancel(job: Pick<Job, 'status' | 'cancel_reason'>): boolean {
  return job.status === 'cancelled' && job.cancel_reason === JOB_CANCEL_LIBRARY_SWITCH
}

/** Bibliotheksordner für Vergleiche: Windows-Schreibweise egal (Groß/klein, `/` und `\`, abschließender Trenner) */
function normalizeRoot(path: string): string {
  return path.trim().replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
}

/** Derselbe Bibliotheksordner? (Pfade wie `WorkspaceInfo.root` bzw. `Job.library`) */
export function sameLibraryRoot(a: string | null | undefined, b: string | null | undefined): boolean {
  return Boolean(a && b) && normalizeRoot(a as string) === normalizeRoot(b as string)
}

/**
 * Gehört der Job zur Bibliothek `root` (in der Regel die geöffnete, `useWorkspace().data?.root`)? Jobs ohne `library`
 * (an keine Bibliothek gebunden, ältere Backends) gelten als zugehörig; ohne geöffnete Bibliothek nur diese.
 */
export function isJobOfLibrary(job: Pick<Job, 'library'>, root: string | null | undefined): boolean {
  if (!job.library) return true
  return sameLibraryRoot(job.library, root)
}

/**
 * Ist das Ergebnis eine Kurzfassung (Jobliste mit `brief=true`, Ergebnis > 8 KB)? Dann für Auswertungen, die mehr als
 * Zählfelder brauchen, `fetchJob(id)` verwenden. Erkennt das Kennzeichen am Schnappschuss und im Ergebnis.
 */
export function isJobResultTruncated(job: Pick<Job, 'result' | 'result_truncated'>): boolean {
  if (job.result_truncated === true) return true
  const r = job.result
  return Boolean(r && typeof r === 'object' && !Array.isArray(r) && (r as Record<string, unknown>).result_truncated === true)
}

// --------------------------------------------------------------------------- Query-Keys

export const systemKeys = {
  health: ['system', 'health'] as const,
  settings: ['system', 'settings'] as const,
  workspace: ['system', 'workspace'] as const,
  recent: ['system', 'workspace', 'recent'] as const,
  defaults: (name: string) => ['system', 'workspace', 'defaults', name] as const,
  jobs: (kind?: string) => ['system', 'jobs', kind ?? 'all'] as const,
  jobsAll: ['system', 'jobs'] as const,
  job: (id: string) => ['system', 'job', id] as const,
}

// --------------------------------------------------------------------------- Funktionen

export const systemApi = {
  health: (signal?: AbortSignal) => api.get<HealthInfo>('/api/health', { signal }),
  getSettings: (signal?: AbortSignal) => api.get<SettingsOut>('/api/settings', { signal }),
  putSettings: (settings: AppSettings) => api.put<SettingsOut>('/api/settings', settings),
  /**
   * Einstellungen ändern, ohne vom Server verwaltete Felder (`workspace`, `recent_workspaces`) mit einem
   * veralteten Stand zu überschreiben: frisch laden, ändern, speichern.
   */
  updateSettings: async (change: (current: AppSettings) => AppSettings) => {
    const fresh = await api.get<SettingsOut>('/api/settings')
    return api.put<SettingsOut>('/api/settings', change(fresh.settings))
  },
  /** Claude-API-Schlüssel verschlüsselt (Windows-DPAPI) für diesen Benutzer speichern */
  putApiKey: (key: string) => api.put<SettingsOut>('/api/settings/api-key', { key }),
  deleteApiKey: () => api.delete<SettingsOut>('/api/settings/api-key'),
  getWorkspace: (signal?: AbortSignal) => api.get<WorkspaceInfo | null>('/api/workspace', { signal }),
  recentWorkspaces: (signal?: AbortSignal) => api.get<RecentWorkspace[]>('/api/workspace/recent', { signal }),
  /** Vorschlag für eine neue Bibliothek (Ordner, eindeutiger DbLib-Name, bekannte DbLib-Dateien) */
  workspaceDefaults: (name: string, signal?: AbortSignal) =>
    api.get<WorkspaceDefaults>('/api/workspace/defaults', { query: { name: name || undefined }, signal }),
  openWorkspace: (path: string) => api.post<WorkspaceInfo>('/api/workspace/open', { path }),
  createWorkspace: (input: CreateWorkspaceInput) => api.post<CreatedWorkspace>('/api/workspace/create', input),
  closeWorkspace: () => api.post<{ ok: boolean }>('/api/workspace/close'),
  putWorkspaceSettings: (settings: WorkspaceSettings) => api.put<WorkspaceInfo>('/api/workspace/settings', settings),
  /**
   * Jobliste ohne Log. Standard: **Kurzfassung** (`brief=true` – große Ergebnisse gekürzt, `result_truncated`);
   * `brief = false` liefert volle Ergebnisse (teuer bei vielen Jobs).
   */
  listJobs: (kind?: string, signal?: AbortSignal, brief = true) =>
    api.get<Job[]>('/api/jobs', { query: { kind, brief: brief || undefined }, signal }),
  /** Vollständiger Schnappschuss eines Jobs (mit Log und ganzem Ergebnis) */
  getJob: <TResult = unknown>(id: string, signal?: AbortSignal) =>
    api.get<Job<TResult>>(`/api/jobs/${encodeURIComponent(id)}`, { signal }),
  cancelJob: (id: string) => api.post<{ cancelled: boolean }>(`/api/jobs/${encodeURIComponent(id)}/cancel`),
}

// --------------------------------------------------------------------------- Hooks

/** Health-Check (öffentlich, ohne Token); alle 15 s, damit die Statuspunkte aktuell bleiben. */
export function useHealth() {
  return useQuery({
    queryKey: systemKeys.health,
    queryFn: ({ signal }) => systemApi.health(signal),
    refetchInterval: 15_000,
    staleTime: 5_000,
  })
}

export function useSettings() {
  return useQuery({
    queryKey: systemKeys.settings,
    queryFn: ({ signal }) => systemApi.getSettings(signal),
    staleTime: 30_000,
  })
}

/**
 * Status von Altium und Bibliotheks-Writer (`GET /api/altium/status`, Key wie `altiumKeys.status` in `@/api/altium` –
 * hier als Literal, damit `system` nicht von `altium` abhängt). Hängt an den App-Einstellungen (X2-Pfad, Writer-Pfad,
 * Schreibweg) und wird nach dem Speichern sofort neu geladen, nicht erst beim nächsten 15-s-Abruf.
 */
const ALTIUM_STATUS_KEY = ['altium', 'status'] as const

/**
 * Einstellungen speichern. Übergeben wird eine Änderungsfunktion – sie wird auf den **aktuellen**
 * Serverstand angewendet (siehe `systemApi.updateSettings`). Danach laden Health und der Altium-/Writer-Status neu
 * (Seitenleiste, Einstellungen › Allgemein › Altium Designer zeigen den neuen Writer gleich).
 */
export function useSaveSettings() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.updateSettings,
    meta: { errorTitle: tr("Einstellungen konnten nicht gespeichert werden") },
    onSuccess: async (data) => {
      qc.setQueryData(systemKeys.settings, data)
      void qc.invalidateQueries({ queryKey: systemKeys.health })
      // `mutateAsync` endet erst mit dem neuen Status – die Seite kann ihn dann gleich melden („Writer gefunden“)
      await qc.invalidateQueries({ queryKey: ALTIUM_STATUS_KEY })
    },
  })
}

export function useSaveApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.putApiKey,
    meta: { silentError: true }, // Fehler (z. B. „beginnt nicht mit sk-“) zeigt der Dialog selbst
    onSuccess: (data) => qc.setQueryData(systemKeys.settings, data),
  })
}

export function useDeleteApiKey() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.deleteApiKey,
    meta: { errorTitle: tr("Schlüssel konnte nicht entfernt werden") },
    onSuccess: (data) => qc.setQueryData(systemKeys.settings, data),
  })
}

/** Aktuell geöffnete Bibliothek – `null`, wenn keine geöffnet ist. */
export function useWorkspace() {
  return useQuery({
    queryKey: systemKeys.workspace,
    queryFn: ({ signal }) => systemApi.getWorkspace(signal),
    staleTime: 60_000,
  })
}

/**
 * Vorschlag für „Neue Bibliothek anlegen“ zum Namen (`GET /api/workspace/defaults`): Ordner unter den Dokumenten, eindeutiger
 * DbLib-Name, bekannte DbLib-Dateien. Ältere Backends ohne den Endpunkt: Fehler (404) – der Dialog schlägt dann selbst vor.
 */
export function useWorkspaceDefaults(name: string, enabled = true) {
  return useQuery({
    queryKey: systemKeys.defaults(name),
    queryFn: ({ signal }) => systemApi.workspaceDefaults(name, signal),
    enabled,
    staleTime: 15_000,
    retry: false,
    placeholderData: (previous) => previous,
  })
}

export function useRecentWorkspaces() {
  return useQuery({
    queryKey: systemKeys.recent,
    queryFn: ({ signal }) => systemApi.recentWorkspaces(signal),
  })
}

const isWorkspaceScoped = (q: { queryKey: readonly unknown[] }) => q.queryKey[0] !== 'system'

/**
 * Nach einem Bibliothekswechsel: laufende Abfragen der alten Bibliothek abbrechen, alle modulbezogenen
 * Daten zurücksetzen (aktive Abfragen laden sofort für die neue Bibliothek) und Systemabfragen auffrischen.
 */
export function resetWorkspaceScopedQueries(qc: QueryClient, info: WorkspaceInfo | null): void {
  qc.setQueryData(systemKeys.workspace, info)
  void qc
    .cancelQueries({ predicate: isWorkspaceScoped })
    .then(() => qc.resetQueries({ predicate: isWorkspaceScoped }))
  void qc.invalidateQueries({ queryKey: systemKeys.health })
  void qc.invalidateQueries({ queryKey: systemKeys.recent })
  void qc.invalidateQueries({ queryKey: systemKeys.settings })
}

export function useOpenWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.openWorkspace,
    meta: { silentError: true },
    onSuccess: (info) => resetWorkspaceScopedQueries(qc, info),
  })
}

export function useCreateWorkspace() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.createWorkspace,
    meta: { silentError: true },
    onSuccess: (info) => resetWorkspaceScopedQueries(qc, info),
  })
}

export function useCloseWorkspace() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.closeWorkspace,
    meta: { errorTitle: tr("Bibliothek konnte nicht geschlossen werden") },
    onSuccess: () => resetWorkspaceScopedQueries(qc, null),
  })
}

export function useSaveWorkspaceSettings() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.putWorkspaceSettings,
    meta: { errorTitle: tr("Bibliothekseinstellungen konnten nicht gespeichert werden") },
    onSuccess: (info) => {
      qc.setQueryData(systemKeys.workspace, info)
      void qc.invalidateQueries({ queryKey: systemKeys.health })
    },
  })
}

// --------------------------------------------------------------------------- Joblisten: Abgleich nach Version

const withoutLog = <T>(job: Job<T>): Job<T> => (job.log?.length ? { ...job, log: [] } : job)

/**
 * Welcher von zwei Schnappschüssen desselben Jobs gilt? Der neuere (`version`); bei gleicher Version bleibt der
 * vorhandene – außer er ist eine Kurzfassung und der neue vollständig.
 */
function pickJob<T>(incoming: Job<T>, existing: Job<T> | undefined): Job<T> {
  if (!existing) return incoming
  if (incoming.version !== existing.version) return incoming.version > existing.version ? incoming : existing
  return isJobResultTruncated(existing) && !isJobResultTruncated(incoming) ? incoming : existing
}

const byCreatedDesc = (a: Job, b: Job) => b.created - a.created

/**
 * Schnappschüsse in alle geladenen Joblisten übernehmen (`['system','jobs',…]`, je nach Art) – nur, wenn sie neuer sind.
 * So zeigen Job-Dock und Seiten (`useJob`, SSE je Job) immer denselben, neuesten Stand. Logs werden nicht übernommen.
 */
export function upsertJobsInLists(qc: QueryClient, jobs: readonly Job[]): void {
  if (!jobs.length) return
  for (const [key, list] of qc.getQueriesData<Job[]>({ queryKey: systemKeys.jobsAll })) {
    if (!list) continue
    const kind = key[2]
    let next: Job[] | null = null
    for (const job of jobs) {
      if (kind !== 'all' && kind !== job.kind) continue
      const current = next ?? list
      const i = current.findIndex((j) => j.id === job.id)
      if (i >= 0) {
        const chosen = pickJob(withoutLog(job), current[i])
        if (chosen === current[i]) continue
        next = next ?? list.slice()
        next[i] = chosen
      } else {
        next = [withoutLog(job), ...(next ?? list)]
        next.sort(byCreatedDesc)
      }
    }
    if (next) qc.setQueryData(key, next)
  }
}

export function upsertJobInLists(qc: QueryClient, job: Job): void {
  upsertJobsInLists(qc, [job])
}

/** Frisch geladene Liste mit dem Cache abgleichen: je Job der neueste Stand aus Liste, Cache und Job-Schnappschuss. */
function mergeFetchedList(qc: QueryClient, key: readonly unknown[], fresh: Job[]): Job[] {
  const cached = new Map((qc.getQueryData<Job[]>(key) ?? []).map((j) => [j.id, j]))
  return fresh.map((job) => {
    let best = pickJob(job, cached.get(job.id))
    const own = qc.getQueryData<Job>(systemKeys.job(job.id))
    if (own && own.version > best.version) best = withoutLog(own)
    return best
  })
}

/**
 * Fortschritt eines laufenden Jobs aus der Liste in einen vorhandenen Job-Schnappschuss (`useJob`) übernehmen –
 * Log und Ergebnis bleiben, beendete Jobs liefert erst der vollständige Schnappschuss (SSE bzw. Abfrage je Job).
 */
function mergeProgressIntoJob(qc: QueryClient, job: Job): void {
  if (!isJobActive(job)) return
  const key = systemKeys.job(job.id)
  const cur = qc.getQueryData<Job>(key)
  if (!cur || !isJobActive(cur) || cur.version >= job.version) return
  qc.setQueryData<Job>(key, {
    ...cur,
    status: job.status,
    progress: job.progress,
    message: job.message,
    detail: job.detail ?? cur.detail,
    started: job.started ?? cur.started,
    version: job.version,
  })
}

// --------------------------------------------------------------------------- Jobliste live (SSE, geteilt)

/**
 * Eine EventSource auf `/api/jobs/events?brief=true` für **alle** Joblisten (Job-Dock, Seiten): das Backend schickt
 * je geänderten Job den Schnappschuss (ohne Log). Fällt der Strom aus, pollen die Listen wieder (1 s / 4 s).
 */
const listStream = {
  source: null as EventSource | null,
  refs: 0,
  open: false,
  qc: null as QueryClient | null,
  retry: null as ReturnType<typeof setTimeout> | null,
  flush: null as ReturnType<typeof setTimeout> | null,
  pending: new Map<string, Job>(),
  listeners: new Set<() => void>(),
}

function setListStreamOpen(open: boolean): void {
  if (listStream.open === open) return
  listStream.open = open
  listStream.listeners.forEach((l) => l())
}

function flushListEvents(): void {
  listStream.flush = null
  const qc = listStream.qc
  const jobs = [...listStream.pending.values()]
  listStream.pending.clear()
  if (!qc || !jobs.length) return
  upsertJobsInLists(qc, jobs)
  for (const job of jobs) mergeProgressIntoJob(qc, job)
}

function openListStream(): void {
  if (typeof EventSource === 'undefined' || listStream.source) return
  const source = new EventSource(apiUrl('/api/jobs/events', { brief: true }))
  listStream.source = source
  source.onopen = () => setListStreamOpen(true)
  source.onmessage = (event) => {
    let payload: unknown
    try {
      payload = JSON.parse(event.data as string)
    } catch {
      return // ungültiges Ereignis ignorieren
    }
    const raw = payload && typeof payload === 'object' && 'job' in payload ? (payload as { job: unknown }).job : payload
    if (!raw || typeof raw !== 'object' || typeof (raw as Job).id !== 'string') return
    const job = { ...(raw as Job), log: [] as JobLogEntry[] }
    const prev = listStream.pending.get(job.id)
    listStream.pending.set(job.id, prev && prev.version > job.version ? prev : job)
    // Bündeln: das Backend schickt alle 0,2 s die geänderten Jobs als Stoß
    listStream.flush ??= setTimeout(flushListEvents, 60)
  }
  source.onerror = () => {
    setListStreamOpen(false)
    if (source.readyState !== EventSource.CLOSED) return // der Browser verbindet sich selbst neu
    source.close()
    if (listStream.source === source) listStream.source = null
    // endgültig abgelehnt (z. B. Backend neu gestartet): später erneut versuchen, bis dahin pollen die Listen
    if (listStream.refs > 0 && !listStream.retry) {
      listStream.retry = setTimeout(() => {
        listStream.retry = null
        if (listStream.refs > 0) openListStream()
      }, 15_000)
    }
  }
}

function closeListStream(): void {
  if (listStream.retry) clearTimeout(listStream.retry)
  listStream.retry = null
  listStream.source?.close()
  listStream.source = null
  setListStreamOpen(false)
}

function connectListStream(qc: QueryClient): () => void {
  listStream.refs += 1
  listStream.qc = qc
  openListStream()
  return () => {
    listStream.refs -= 1
    if (listStream.refs <= 0) {
      listStream.refs = 0
      closeListStream()
    }
  }
}

const subscribeListStream = (listener: () => void) => {
  listStream.listeners.add(listener)
  return () => {
    listStream.listeners.delete(listener)
  }
}

/** Verbindet die geteilte Live-Jobliste (solange gemountet); `true`, solange der Strom offen ist. */
function useJobListStream(): boolean {
  const qc = useQueryClient()
  useEffect(() => connectListStream(qc), [qc])
  return useSyncExternalStore(subscribeListStream, () => listStream.open, () => false)
}

/**
 * Alle Jobs (ohne Log, **Kurzfassung** – große Ergebnisse gekürzt, siehe `Job.result_truncated`), optional einer Art.
 * Live über SSE; ohne Strom wird gepollt (1 s, solange etwas läuft, sonst 4 s). Enthält immer den neuesten bekannten
 * Stand je Job – auch aus `useJob`/`trackJob` (Job-Dock und Seiten stimmen überein).
 */
export function useJobs(kind?: string) {
  const qc = useQueryClient()
  const live = useJobListStream()
  return useQuery({
    queryKey: systemKeys.jobs(kind),
    queryFn: async ({ signal }) => mergeFetchedList(qc, systemKeys.jobs(kind), await systemApi.listJobs(kind, signal)),
    // live: nur gelegentlich abgleichen (vom Backend entfernte Jobs); sonst pollen
    refetchInterval: (query) => (live ? 30_000 : query.state.data?.some(isJobActive) ? 1000 : 4000),
    staleTime: 500,
  })
}

/**
 * Wie {@link useJobs}, aber nur Jobs der **geöffneten** Bibliothek (`Job.library`, {@link isJobOfLibrary}) – für
 * Fortschritts- und Ergebnisanzeigen der Seiten (Altium-Prüfung, Serie, Import): Ein Job, der vor einem
 * Bibliothekswechsel startete, erscheint dort nicht in der neuen Bibliothek. Das Job-Dock zeigt weiter alle.
 */
export function useLibraryJobs(kind?: string) {
  const root = useWorkspace().data?.root ?? null
  const query = useJobs(kind)
  const all = query.data
  const data = useMemo(() => all?.filter((j) => isJobOfLibrary(j, root)), [all, root])
  return { data, isLoading: query.isLoading, isError: query.isError, error: query.error, refetch: query.refetch }
}

export function useCancelJob() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: systemApi.cancelJob,
    meta: { errorTitle: tr("Job konnte nicht abgebrochen werden") },
    onSettled: () => qc.invalidateQueries({ queryKey: systemKeys.jobsAll }),
  })
}

// --------------------------------------------------------------------------- KI-Verbindung (letzter Test)

/** Fehlercodes von `POST /api/ai/test` (`detail.code`) – ältere Backends liefern nur Text, dann aus dem Wortlaut */
export type AiProblemCode =
  | 'key_missing'
  | 'key_rejected'
  | 'model_unavailable'
  | 'network'
  | 'rate_limited'
  | 'ai_disabled'
  | 'unknown'

const AI_PROBLEM_CODES = new Set<string>([
  'key_missing',
  'key_rejected',
  'model_unavailable',
  'network',
  'rate_limited',
  'ai_disabled',
  'unknown',
])

/** Ergebnis des letzten Verbindungstests (bzw. einer an Schlüssel/Modell gescheiterten Datenblatt-Analyse) */
export interface AiConnectionCheck {
  /** Zeitpunkt (ms seit Epoche) */
  at: number
  ok: boolean
  /** Problem bei `ok: false`; `unexpected` = Claude hat geantwortet, aber nicht wie erwartet */
  code: AiProblemCode | 'unexpected' | null
  /** Deutscher Text (Fehlermeldung bzw. Hinweis) */
  message: string | null
  model: string | null
  latencyMs: number | null
  /** Schlüsselquelle, -datei und Modelle beim Test ({@link aiSettingsSignature}) – ändert sich etwas, gilt er nicht mehr */
  signature: string | null
  source: 'test' | 'job'
}

/** Kennung der KI-Konfiguration: Ein Testergebnis gilt nur, solange sie gleich bleibt. */
export function aiSettingsSignature(settings: SettingsOut | null | undefined): string | null {
  if (!settings) return null
  const ai = settings.settings.ai
  return [settings.ai_key_source ?? '', ai.api_key_file ?? '', ai.model, ai.fast_model].join('|')
}

/** Problemcode aus einem deutschen Fehlertext der KI-Anbindung (`partforge/datasheet/llm.py`) */
export function aiProblemFromText(text: string): AiProblemCode {
  if (/schlüssel.*abgelehnt|keinen zugriff/i.test(text)) return 'key_rejected'
  if (/kein\w* (claude-)?api-schlüssel|schlüssel (fehlt|hinterlegen)/i.test(text)) return 'key_missing'
  if (/modell.*nicht verfügbar/i.test(text)) return 'model_unavailable'
  if (/anfragelimit|\b429\b/i.test(text)) return 'rate_limited'
  if (/ausgeschaltet|deaktiviert/i.test(text)) return 'ai_disabled'
  if (/keine verbindung|zeitüberschreitung|überlastet|gestört|nicht erreichbar|internetverbindung/i.test(text)) return 'network'
  return 'unknown'
}

/** Fehler von `POST /api/ai/test` einordnen: `detail.code` des Backends, sonst Netzwerkstatus bzw. Wortlaut. */
export function classifyAiError(error: unknown): { code: AiProblemCode; message: string } {
  const message = cleanErrorText(errorMessage(error, tr("Unbekannter Fehler")))
  if (error instanceof ApiError) {
    const detail = error.detail
    const code = detail && typeof detail === 'object' ? (detail as { code?: unknown }).code : undefined
    if (typeof code === 'string' && AI_PROBLEM_CODES.has(code)) return { code: code as AiProblemCode, message }
    if (error.isNetworkError || error.isTimeout) return { code: 'network', message }
  }
  const raw = error instanceof Error ? error.message : typeof error === 'string' ? error : message
  return { code: aiProblemFromText(raw), message }
}

interface AiConnectionState {
  last: AiConnectionCheck | null
  record: (check: AiConnectionCheck) => void
  reset: () => void
}

/**
 * Letzter KI-Verbindungstest – gleich, wo er lief (Einstellungen, Datenblatt-Import): `POST /api/ai/test` wird zentral
 * beobachtet. Gespeichert (localStorage + Cookie), damit ein abgelehnter Schlüssel nach dem Neustart nicht wieder grün
 * erscheint; ein neuer/entfernter Schlüssel setzt das Ergebnis zurück.
 */
export const useAiConnection = create<AiConnectionState>()(
  persist(
    (set) => ({
      last: null,
      record: (last) => set({ last }),
      reset: () => set({ last: null }),
    }),
    {
      name: 'pf-ai-check',
      version: 1,
      storage: createJSONStorage(() => prefsStorage),
      partialize: (s) => ({ last: s.last }),
    },
  ),
)

function currentAiSignature(): string | null {
  return aiSettingsSignature(queryClient.getQueryData<SettingsOut>(systemKeys.settings))
}

interface AiTestReply {
  ok?: boolean
  model?: string
  reply?: string
  latency_ms?: number
}

const aiObservers = [
  observeApi('POST', '/api/ai/test', (outcome) => {
    const base = { at: Date.now(), signature: currentAiSignature(), source: 'test' as const }
    if (outcome.ok) {
      const data = (outcome.data ?? {}) as AiTestReply
      const ok = data.ok === true
      useAiConnection.getState().record({
        ...base,
        ok,
        code: ok ? null : 'unexpected',
        message: ok ? null : tr("Unerwartete Antwort{0}", { "0": String(data.reply ? `: „${data.reply}“` : '') }),
        model: data.model ?? null,
        latencyMs: typeof data.latency_ms === 'number' ? data.latency_ms : null,
      })
    } else {
      const { code, message } = classifyAiError(outcome.error)
      useAiConnection.getState().record({ ...base, ok: false, code, message, model: null, latencyMs: null })
    }
  }),
  // neuer oder entfernter Schlüssel: früheres Ergebnis gilt nicht mehr
  observeApi('PUT', '/api/settings/api-key', (outcome) => {
    if (outcome.ok) useAiConnection.getState().reset()
  }),
  observeApi('DELETE', '/api/settings/api-key', (outcome) => {
    if (outcome.ok) useAiConnection.getState().reset()
  }),
]
if (import.meta.hot) import.meta.hot.dispose(() => aiObservers.forEach((off) => off()))

/**
 * Eine in dieser Sitzung beendete Job-Ausführung, die an Schlüssel oder Modell gescheitert ist (Datenblatt-Analyse),
 * als KI-Problem merken – ein abgelehnter Schlüssel bleibt so nicht grün. Netzwerkfehler zählen hier nicht
 * (vorübergehend). Aufgerufen vom Job-Dock beim Melden des Abschlusses.
 */
export function noteAiJobFailure(job: Pick<Job, 'status' | 'error' | 'error_type' | 'finished'>): void {
  if (job.status !== 'failed' || !job.error) return
  if (job.error_type && job.error_type !== 'AiUnavailable') return
  const code = aiProblemFromText(job.error)
  if (code !== 'key_rejected' && code !== 'key_missing' && code !== 'model_unavailable') return
  const at = job.finished ? toMillis(job.finished) : Date.now()
  const last = useAiConnection.getState().last
  if (last && last.at >= at) return
  useAiConnection.getState().record({
    at,
    ok: false,
    code,
    message: cleanErrorText(job.error),
    model: null,
    latencyMs: null,
    signature: currentAiSignature(),
    source: 'job',
  })
}
