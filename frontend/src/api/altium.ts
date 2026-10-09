/**
 * Altium-Anbindung: Status (Altium, Bibliotheks-Writer, DbLib, Aktualisierung), DbLib (Vorschau, Download, neu
 * erzeugen), ODBC-Test, Installation, Aktualisierung, Prüfung in Altium (samt gespeichertem letzten Ergebnis) und
 * Öffnen von Bibliotheken.
 *
 *   const status = useAltiumStatus()                         // GET  /api/altium/status (billig, ohne Altium-Skript)
 *   const regen = useRegenerateDblib()                       // POST /api/altium/dblib/regenerate (direkt, ohne Job)
 *   const last = useLastVerify()                             // GET  /api/altium/verify/last (übersteht Neustarts)
 *   const { job } = await altiumApi.verify({ limit: 20, sample: 'spread' })   // alles, was mit Altium spricht, ist ein Job
 *   const file = await altiumApi.dblibFile('target')         // exakte Bytes der DbLib + Dateiname (Content-Disposition)
 *
 * Job-Endpunkte antworten ohne laufendes Altium sofort mit 503 („Altium Designer ist nicht gestartet …“), bei
 * belegter Brücke mit 409. Jeder Altium-Job endet mit einem deutschen Ergebnissatz in `job.message`. Job-Ergebnisse
 * sind im Schema untypisierte dicts – ihre Form steht unten (aus dem Schema, wo das Backend ein Modell hat, sonst von
 * Hand gespiegelt aus `partforge/altium/odbc.py`).
 *
 * Query-Keys beginnen mit „altium“. `['altium', 'status']` teilt sich den Cache mit der Einstellungsseite.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, api, buildQuery, detailToMessage, getToken, isAbortError, TOKEN_HEADER } from './client'
import type { Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

/**
 * ODBC-Treiber, über den Altium die Datenbank liest (`odbc` im Status: billige, zwischengespeicherte Prüfung mit
 * `pyodbc.drivers()`). `installed: null` = nicht prüfbar (z. B. pyodbc fehlt) – dann keine Warnung.
 */
export interface OdbcDriverStatus {
  kind?: 'sqlite' | 'postgres'
  /** Name des Treibers aus der DbLib („SQLite3 ODBC Driver“, „PostgreSQL Unicode(x64)“) */
  driver: string
  installed: boolean | null
  /** deutscher Satz mit Lösungshinweis */
  message?: string | null
  /** Bezugsquelle des Treibers (Download-Seite) */
  download?: string | null
}

export type AltiumStatus = Filled<ResponseOf<'/api/altium/status', 'get'>> & {
  /** fehlt bei älteren Backends (dann unbekannt) */
  odbc?: OdbcDriverStatus | null
}
export type AltiumBackend = AltiumStatus['backends'][number]

/**
 * Treiberstatus aus `GET /api/altium/status` – `null`, wenn unbekannt (älteres Backend, nicht prüfbar). Versteht auch
 * `driver_installed` statt `installed` (Feldname des ODBC-Berichts).
 */
export function odbcDriverStatus(status: Pick<AltiumStatus, 'odbc'> | undefined): OdbcDriverStatus | null {
  const raw = status?.odbc as (Partial<OdbcDriverStatus> & { driver_installed?: boolean | null }) | null | undefined
  if (!raw || typeof raw !== 'object') return null
  const installed = typeof raw.installed === 'boolean' ? raw.installed : typeof raw.driver_installed === 'boolean' ? raw.driver_installed : null
  return {
    kind: raw.kind,
    driver: typeof raw.driver === 'string' && raw.driver ? raw.driver : 'SQLite3 ODBC Driver',
    installed,
    message: typeof raw.message === 'string' ? raw.message : null,
    download: typeof raw.download === 'string' && raw.download ? raw.download : null,
  }
}
export type DbLibStatus = NonNullable<AltiumStatus['dblib']>
export type DbLibIssue = DbLibStatus['issues'][number]
export type DbLibInstallState = NonNullable<DbLibStatus['install']>
export type RefreshStatus = AltiumStatus['refresh']
export type DbLibPreview = Filled<ResponseOf<'/api/altium/dblib/preview', 'get'>>
/** Ergebnis von „DbLib neu erzeugen“: `reason` (stabile Kennung) und `reason_text` (deutscher Satz des Backends) */
export type DbLibRegenerateResult = Filled<ResponseOf<'/api/altium/dblib/regenerate', 'post'>>
export type RegenerateReason = DbLibRegenerateResult['reason']
/** Anfrage „In Altium prüfen“ – alle Felder haben Standardwerte im Backend (`sample: 'spread'`, `limit: 20`) */
export type VerifyInput = Partial<NonNullable<RequestBodyOf<'/api/altium/verify', 'post'>>>
export type VerifySampleMode = NonNullable<VerifyInput['sample']>
export type RefreshInput = NonNullable<RequestBodyOf<'/api/altium/refresh', 'post'>>

/** Letzte abgeschlossene Prüfung in Altium (`GET /api/altium/verify/last`, in der Bibliothek gespeichert) */
export type VerifyRun = Filled<NonNullable<ResponseOf<'/api/altium/verify/last', 'get'>>>
/** Zähler und Dauer einer Prüfung (`VerifySummary`) */
export type VerifySummary = VerifyRun['summary']
/** Ein in Altium aufgelöstes Bauteil (`VerifiedPart`) */
export type VerifiedPart = VerifyRun['results'][number]
/** Ein Footprint-Verweis eines Bauteils (`Footprint Ref` / `Footprint Ref n`) */
export type FootprintCheck = VerifiedPart['footprint_checks'][number]
/** Umfang einer Prüfung: Stichprobe, alle Bauteile, genannte Teilenummern */
export type VerifyRunScope = VerifyRun['scope']

// --------------------------------------------------------------------------- Job-Ergebnisse

export type IssueSeverity = 'error' | 'warning' | 'info'

/** `altium.odbc_test` – `partforge.altium.odbc.OdbcTableResult` */
export interface OdbcTableResult {
  table: string
  label: string | null
  enabled: boolean
  found: boolean
  rows: number | null
  columns: number | null
  seconds: number | null
  lookup_seconds: number | null
  lookup_ok: boolean | null
  /** nach `max_rows` abgebrochen */
  truncated: boolean
  missing_columns: string[]
  /** VARCHAR(n)-Spalten: Altium schneidet Werte auf n Zeichen ab */
  sized_columns: Record<string, number>
  error: string | null
  ok: boolean
}

/** `altium.odbc_test` – `partforge.altium.odbc.OdbcReport`. Der Job endet mit `summary` als `job.message`. */
export interface OdbcReport {
  ok: boolean
  kind: 'sqlite' | 'postgres'
  driver: string
  driver_installed: boolean
  driver_version: string | null
  dbms_version: string | null
  python_bits: number
  available_drivers: string[]
  /** ODBC-Attribute, Kennwort maskiert */
  connection_string: string
  database: string | null
  connected: boolean
  connect_seconds: number | null
  tables: OdbcTableResult[]
  /** sichtbare Tabellen, die keine Kategorien sind */
  other_tables: string[]
  journal_mode: string | null
  wal_ok: boolean | null
  unicode_ok: boolean | null
  total_seconds: number
  issues: { severity: IssueSeverity; message: string }[]
  /** deutscher Bericht, eine Zeile je Schritt */
  lines: string[]
  summary: string
}

/**
 * `altium.verify` – Job-Ergebnis von „Bibliothek in Altium prüfen“: die Zähler (`VerifySummary`), die Auswahl
 * (`scope`, `sample`, `limit`, `tables`, `started`, `finished`) und `parts`. Dasselbe liefert `GET /api/altium/verify/last`
 * als `VerifyRun` (`summary` + `results`) – die Seite liest das gespeicherte Ergebnis, nicht den Job.
 */
export type VerifyResult = VerifySummary &
  Pick<VerifyRun, 'scope' | 'sample' | 'limit' | 'tables' | 'started' | 'finished'> & { parts: VerifiedPart[] }

/** `altium.install` / `altium.uninstall` / `altium.install_state` */
export interface InstallJobResult {
  message: string
  state?: DbLibInstallState
  removed?: string[]
  dblib_written?: boolean
}

/** `altium.open` */
export interface OpenJobResult {
  message: string
  path: string
  was_open: boolean
}

export interface JobStart {
  job: Job
}

/** DbLib als Datei (`?raw=true`): exakte Bytes (Windows-1252, CRLF, Kennwort unmaskiert) und der Dateiname */
export interface DbLibFile {
  blob: Blob
  /** aus `Content-Disposition` (UTF-8-Name, sonst ASCII-Ersatz) */
  fileName: string
  size: number
}

/** `target` = wie PartForge die DbLib jetzt schreiben würde, `file` = die Datei auf der Festplatte (404, wenn sie fehlt) */
export type DbLibFileWhich = 'target' | 'file'

// --------------------------------------------------------------------------- Query-Keys

export const altiumKeys = {
  all: ['altium'] as const,
  /** identisch mit `settingsKeys.altiumStatus` (Einstellungen › Allgemein › Altium Designer) */
  status: ['altium', 'status'] as const,
  preview: ['altium', 'dblib-preview'] as const,
  /** letzte abgeschlossene Prüfung in Altium (nach jedem erfolgreichen Job neu geladen) */
  verifyLast: ['altium', 'verify-last'] as const,
}

// --------------------------------------------------------------------------- Rohfunktionen

const DBLIB_FALLBACK_NAME = 'PartForge.DbLib'

/** Dateiname aus `Content-Disposition` – `filename*=UTF-8''…` (RFC 5987) vor `filename="…"` */
export function fileNameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  const star = /filename\*\s*=\s*([^';]*)'[^']*'([^;]+)/i.exec(header)
  if (star) {
    try {
      const name = decodeURIComponent(star[2].trim().replace(/^"|"$/g, ''))
      if (name) return name
    } catch {
      // ungültige Kodierung: auf den einfachen Namen zurückfallen
    }
  }
  const quoted = /filename\s*=\s*"((?:[^"\\]|\\.)*)"/i.exec(header)
  if (quoted?.[1]) return quoted[1].replace(/\\(.)/g, '$1')
  const bare = /filename\s*=\s*([^;]+)/i.exec(header)
  return bare?.[1]?.trim() || fallback
}

/**
 * DbLib als Datei laden (`GET /api/altium/dblib/preview?raw=true&which=…`): exakte Bytes und Dateiname aus der Antwort.
 * Eigener Abruf statt `api.get`, weil der Dateiname im Kopf `Content-Disposition` steht. Fehler wie `api`: `ApiError`.
 */
async function fetchDblibFile(which: DbLibFileWhich, signal?: AbortSignal): Promise<DbLibFile> {
  const path = '/api/altium/dblib/preview'
  const headers: Record<string, string> = { Accept: 'text/plain, application/json' }
  const token = getToken()
  if (token) headers[TOKEN_HEADER] = token
  const timeout = AbortSignal.timeout(30_000)
  let response: Response
  try {
    response = await fetch(`${path}${buildQuery({ raw: true, which })}`, {
      headers,
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    })
  } catch (err) {
    if (signal?.aborted) throw signal.reason ?? err
    if (isAbortError(err) && !timeout.aborted) throw err
    const status = timeout.aborted ? 408 : 0
    throw new ApiError(status, detailToMessage(null, status), null, 'GET', path)
  }
  if (!response.ok) {
    const text = await response.text().catch(() => '')
    let detail: unknown = null
    try {
      const parsed = JSON.parse(text) as { detail?: unknown }
      detail = parsed && typeof parsed === 'object' && 'detail' in parsed ? parsed.detail : parsed
    } catch {
      detail = text && text.length < 400 ? text : null
    }
    throw new ApiError(response.status, detailToMessage(detail, response.status), detail, 'GET', path)
  }
  const blob = await response.blob()
  return {
    blob,
    fileName: fileNameFromDisposition(response.headers.get('content-disposition'), DBLIB_FALLBACK_NAME),
    size: blob.size,
  }
}

export const altiumApi = {
  status: (signal?: AbortSignal) => api.get<AltiumStatus>('/api/altium/status', { signal }),
  /** Soll-Stand und Datei auf der Festplatte als Text (Kennwörter maskiert) – zum Ansehen, nicht zum Speichern */
  preview: (signal?: AbortSignal) => api.get<DbLibPreview>('/api/altium/dblib/preview', { signal }),
  /** DbLib zum Speichern: exakte Bytes (Kennwort unmaskiert, Altium braucht es) + Dateiname – über `saveFile` speichern */
  dblibFile: fetchDblibFile,
  regenerate: () => api.post<DbLibRegenerateResult>('/api/altium/dblib/regenerate'),
  odbcTest: (maxRows?: number) => api.post<JobStart>('/api/altium/odbc-test', maxRows ? { max_rows: maxRows } : {}),
  installState: () => api.post<JobStart>('/api/altium/install-state'),
  install: (replaceOthers = false) => api.post<JobStart>('/api/altium/install', { replace_others: replaceOthers }),
  uninstall: () => api.post<JobStart>('/api/altium/uninstall'),
  refresh: (rebuildIndex: boolean | null = null) => api.post<JobStart>('/api/altium/refresh', { rebuild_index: rebuildIndex }),
  verify: (input: VerifyInput) => api.post<JobStart>('/api/altium/verify', input),
  /** Letzte abgeschlossene Prüfung der offenen Bibliothek (`null` = noch nie geprüft) */
  verifyLast: (signal?: AbortSignal) => api.get<VerifyRun | null>('/api/altium/verify/last', { signal }),
  /** Bibliotheksdatei (absolut oder relativ zur Bibliothek) in Altium öffnen; ohne Pfad die DbLib */
  open: (path?: string) => api.post<JobStart>('/api/altium/open', { path: path ?? null }),
}

// --------------------------------------------------------------------------- Hooks

/**
 * Status von Altium, Writern, DbLib und Aktualisierung. Billig (kein Altium-Skript) – pollt alle 15 s, damit
 * „Altium läuft“ nach dem Start von Altium ohne Neuladen erscheint.
 */
export function useAltiumStatus(enabled = true) {
  return useQuery({
    queryKey: altiumKeys.status,
    queryFn: ({ signal }) => altiumApi.status(signal),
    enabled,
    staleTime: 5_000,
    refetchInterval: 15_000,
    retry: false,
  })
}

/** DbLib-Vorschau (Soll-Stand und Datei auf der Festplatte) – nur laden, solange der Dialog offen ist. */
export function useDblibPreview(enabled: boolean) {
  return useQuery({
    queryKey: altiumKeys.preview,
    queryFn: ({ signal }) => altiumApi.preview(signal),
    enabled,
    staleTime: 0,
    gcTime: 30_000,
    retry: false,
  })
}

/**
 * Letzte abgeschlossene Prüfung in Altium – gespeichert in der Bibliothek (übersteht Neustarts, gehört zur offenen
 * Bibliothek). Nach jedem erfolgreich beendeten Job (also auch nach einer neuen Prüfung) lädt das Job-Dock neu.
 */
export function useLastVerify(enabled = true) {
  return useQuery({
    queryKey: altiumKeys.verifyLast,
    queryFn: ({ signal }) => altiumApi.verifyLast(signal),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

/** DbLib jetzt schreiben (ohne Job). Ein laufendes Altium liest sie danach selbst neu ein (falls aktiviert). */
export function useRegenerateDblib() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: altiumApi.regenerate,
    meta: { errorTitle: 'DbLib konnte nicht erzeugt werden' },
    onSuccess: (result) => {
      qc.setQueryData<AltiumStatus>(altiumKeys.status, (cur) => (cur ? { ...cur, dblib: result.status } : cur))
      void qc.invalidateQueries({ queryKey: altiumKeys.all })
    },
  })
}
