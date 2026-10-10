/**
 * Bibliotheken: SchLib-/PcbLib-Dateien (Abgleich, Synchronisieren, Prüfen, Footprint-Höhen nachtragen), externe
 * Bibliotheken (schreibgeschützt eingebunden) und der **Prüfbericht** – zusammengeführt aus drei Quellen:
 *
 *   GET /api/health-check      Datenebene: Pflichtfelder, Dubletten, Werte, Verweise, Datenblätter (routes_parts)
 *   GET /api/libraries/health  Dateiebene: Bauteile in ihren Dateien, Pfade, Pins ↔ Pads, Footprint-Höhen,
 *                              außerhalb geändert – je Befund die betroffenen Bauteile (`affected_parts`)
 *   GET /api/altium/status     DbLib-Befunde (veraltet, fehlt, falsche Datenbank, gleichnamige Installation …)
 *
 *   const health = useHealthReport()           // { report: MergedHealth | undefined, isLoading, refetch, … }
 *   const files = useLibraryFiles()            // GET /api/libraries/files (inkl. Lagenprüfung)
 *   const { job } = await librariesApi.sync()  // Job „Bibliotheken synchronisieren“ → trackJob(job)
 *
 * Kennungen der Prüfungen: ARCHITEKTUR.md §8.4. Beide Ebenen verwenden für denselben Registry-Zustand dieselbe Kennung
 * (`registry_error`, `registry_missing`); `symbol_missing` / `footprint_missing` heißt nur noch „nicht registriert“
 * (Datenebene). Die Dateiebene nennt je Befund alle betroffenen Bauteile – daraus entsteht die exakte Quote.
 *
 * Query-Keys beginnen mit „libraries“ (Datenprüfung: `['libraries', 'health-check']`). Nach jedem erfolgreichen
 * Job lädt das Job-Dock alle modulbezogenen Abfragen neu – die Dateiliste aktualisiert sich so selbst. Der Prüfbericht
 * ist `meta.static` und lädt nur nach Jobs/Schreibzugriffen neu, die ihn ändern können (`HEALTH_JOB_KINDS`).
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useMemo } from 'react'
import { baseName } from '@/lib/format'
import { altiumKeys, useAltiumStatus, type DbLibStatus, type IssueSeverity, type JobStart } from './altium'
import { api, observeApi } from './client'
import type { Filled, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

export type LibraryFile = Filled<ResponseOf<'/api/libraries/files', 'get'>>[number]
export type DataHealthReport = Filled<ResponseOf<'/api/health-check', 'get'>>
export type FileHealthReport = Filled<ResponseOf<'/api/libraries/health', 'get'>>
export type HealthIssue = DataHealthReport['issues'][number]
/** Befund der Dateiprüfung: `HealthIssue` + `kind`, `component`, `library`, `affected_parts`, `part_numbers`, `fix_action` */
export type FileHealthIssue = FileHealthReport['issues'][number]
export type ExternalLibrary = Filled<ResponseOf<'/api/libraries/external', 'get'>>[number]
export type ExternalComponentsPage = Filled<ResponseOf<'/api/libraries/external/{library_id}/components', 'get'>>
export type ExternalComponent = ExternalComponentsPage['components'][number]
export type ExternalUseResult = Filled<ResponseOf<'/api/libraries/external/{library_id}/use', 'post'>>
export type ExternalRemoveResult = Filled<ResponseOf<'/api/libraries/external/{library_id}', 'delete'>>

/** Vorschau-Darstellung der Backend-SVGs */
export type PreviewTheme = 'altium' | 'dark' | 'light'

/** `fix_action` eines Befunds, den `POST /api/libraries/footprint-heights/repair` behebt (`footprint_height_missing`) */
export const REPAIR_HEIGHTS_ACTION = 'repair_footprint_heights'
/** Prüfung „Footprint-Höhe fehlt in der PcbLib“ (Dateiebene) */
export const HEIGHT_CHECK = 'footprint_height_missing'
/** Titel des Jobs „Footprint-Höhen nachtragen“ (Art `libraries.sync`, wie das Synchronisieren) */
export const REPAIR_HEIGHTS_TITLE = 'Footprint-Höhen nachtragen'
/** `fix_action` eines Befunds, den `POST /api/libraries/restore-backup` behebt (`library_unreadable` mit lesbarer Sicherung) */
export const RESTORE_BACKUP_ACTION = 'restore_library_backup'
/** Titel des Jobs „Bibliothek aus Sicherung wiederherstellen“ (Art `libraries.sync`) */
export const RESTORE_BACKUP_TITLE = 'Bibliothek aus Sicherung wiederherstellen'
/** Höchstzahl je Prüfung, die die Datenprüfung hier listet (`max_per_check`) */
export const DATA_CHECK_LIMIT = 500
/** Höchstzahl der Befunde, die die Dateiprüfung insgesamt listet (`sync.library_health(max_issues=500)`) */
export const FILE_ISSUE_LIMIT = 500

// --------------------------------------------------------------------------- Job-Ergebnisse (von Hand)

interface SyncCounts {
  total: number
  ok: number
  error: number
  missing: number
  adopted: number
}

/** `libraries.sync` – `partforge.altium.sync.sync_pending` */
export interface SyncResult {
  symbols: Partial<SyncCounts>
  footprints: Partial<SyncCounts>
  libraries: string[]
  errors: { kind: string; name: string; message: string | null }[]
  missing: { kind: string; name: string; message: string | null }[]
  relinked?: number
  /** kein Writer verfügbar – alles bleibt vorgemerkt */
  skipped?: boolean
  reason?: string
}

/** `libraries.scan` – `partforge.altium.sync.scan_workspace` */
export interface ScanResult {
  files: number
  updated: { kind: string; name: string; status: string; message: string | null }[]
  unregistered: { kind: string; name: string; library: string }[]
  registered: { kind: string; name: string; library: string }[]
  conflicts: { kind: string; name: string; library: string; registered_library: string | null; message: string }[]
  external_missing: { kind: string; name: string; message: string }[]
  changed_outside: string[]
}

/** „Footprint-Höhen nachtragen“ (`libraries.sync`) – `partforge.altium.sync.repair_footprint_heights` */
export interface HeightRepairResult {
  checked: number
  rewritten: string[]
  /** Bibliothek außerhalb von PartForge geändert – nicht neu geschrieben */
  skipped: { name: string; library: string; message: string }[]
  errors: { name: string; message: string | null }[]
  /** fehlt nach dem Neuschreiben weiterhin */
  remaining: string[]
  libraries: string[]
  message: string
}

// --------------------------------------------------------------------------- Query-Keys

export const librariesKeys = {
  all: ['libraries'] as const,
  /** mit Lagenprüfung (die Einstellungen nutzen `['libraries', 'files', 'settings']` ohne) */
  files: ['libraries', 'files', 'full'] as const,
  fileHealth: ['libraries', 'health'] as const,
  dataHealth: ['libraries', 'health-check'] as const,
  external: ['libraries', 'external'] as const,
  externalComponents: (id: string, search: string, theme: PreviewTheme) =>
    ['libraries', 'external', id, 'components', search, theme] as const,
}

// --------------------------------------------------------------------------- Rohfunktionen

const enc = encodeURIComponent

export const librariesApi = {
  files: (signal?: AbortSignal) => api.get<LibraryFile[]>('/api/libraries/files', { query: { layers: true }, signal }),
  sync: () => api.post<JobStart>('/api/libraries/sync'),
  scan: (registerUnknown = false) => api.post<JobStart>('/api/libraries/scan', { register_unknown: registerUnknown }),
  /** Job „Footprint-Höhen nachtragen“ – ohne Namen alle betroffenen Footprints (außerhalb geänderte überspringt er) */
  repairHeights: (names?: string[]) =>
    api.post<JobStart>('/api/libraries/footprint-heights/repair', names?.length ? { names } : {}),
  /** Job „Bibliothek aus Sicherung wiederherstellen“ – `library` wie im Befund `library_unreadable` (relativ) */
  restoreBackup: (library: string) => api.post<JobStart>('/api/libraries/restore-backup', { library }),
  fileHealth: (signal?: AbortSignal) => api.get<FileHealthReport>('/api/libraries/health', { signal, timeoutMs: 120_000 }),
  dataHealth: (signal?: AbortSignal) =>
    api.get<DataHealthReport>('/api/health-check', { query: { max_per_check: DATA_CHECK_LIMIT }, signal, timeoutMs: 120_000 }),
  external: (signal?: AbortSignal) => api.get<ExternalLibrary[]>('/api/libraries/external', { signal }),
  addExternal: (path: string) => api.post<ExternalLibrary>('/api/libraries/external', { path }),
  removeExternal: (id: string) => api.delete<ExternalRemoveResult>(`/api/libraries/external/${enc(id)}`),
  externalComponents: (
    id: string,
    opts: { search?: string; offset?: number; limit?: number; theme?: PreviewTheme; previews?: boolean },
    signal?: AbortSignal,
  ) =>
    api.get<ExternalComponentsPage>(`/api/libraries/external/${enc(id)}/components`, {
      query: {
        search: opts.search || undefined,
        offset: opts.offset ?? 0,
        limit: opts.limit ?? 60,
        theme: opts.theme ?? 'dark',
        previews: opts.previews ?? true,
      },
      signal,
      timeoutMs: 120_000,
    }),
  useExternal: (id: string, name: string) => api.post<ExternalUseResult>(`/api/libraries/external/${enc(id)}/use`, { name }),
}

// --------------------------------------------------------------------------- Hooks: Dateien und externe Bibliotheken

/** Alle SchLib-/PcbLib-Dateien der Bibliothek mit Abgleich (synchron, ausstehend, außerhalb geändert, Lagen). */
export function useLibraryFiles(enabled = true) {
  return useQuery({
    queryKey: librariesKeys.files,
    queryFn: ({ signal }) => librariesApi.files(signal),
    enabled,
    staleTime: 20_000,
    retry: false,
  })
}

export function useExternalLibraries(enabled = true) {
  return useQuery({
    queryKey: librariesKeys.external,
    queryFn: ({ signal }) => librariesApi.external(signal),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

export function useAddExternalLibrary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: librariesApi.addExternal,
    meta: { silentError: true }, // Fehler erscheinen am Eingabefeld
    onSuccess: () => qc.invalidateQueries({ queryKey: librariesKeys.external }),
  })
}

export function useRemoveExternalLibrary() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: librariesApi.removeExternal,
    meta: { errorTitle: 'Externe Bibliothek konnte nicht entfernt werden' },
    onSuccess: () => qc.invalidateQueries({ queryKey: librariesKeys.all }),
  })
}

export function useUseExternalComponent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => librariesApi.useExternal(id, name),
    meta: { errorTitle: 'Bauteil konnte nicht übernommen werden' },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: librariesKeys.external })
      void qc.invalidateQueries({ queryKey: ['symbols'] })
      void qc.invalidateQueries({ queryKey: ['footprints'] })
    },
  })
}

// --------------------------------------------------------------------------- Prüfbericht: Katalog der Prüfungen

/** Ein-Klick-Behebungen (nur dort, wo es einen Endpunkt gibt) bzw. Sprungziele */
export type FixKind =
  | 'regenerate' // POST /api/altium/dblib/regenerate
  | 'sync' // POST /api/libraries/sync
  | 'scan' // POST /api/libraries/scan
  | 'scan-register' // POST /api/libraries/scan { register_unknown: true }
  | 'scan-sync' // erst prüfen, dann synchronisieren
  | 'repair-heights' // POST /api/libraries/footprint-heights/repair (fix_action „repair_footprint_heights“)
  | 'restore-backup' // POST /api/libraries/restore-backup { library } (fix_action „restore_library_backup“)
  | 'install-replace' // POST /api/altium/install { replace_others: true }
  | 'normalize' // PATCH /api/parts/{table}/{pn} mit dem gespeicherten Text → Standardformat
  | 'open-part' // Sprung: erstes betroffenes Bauteil in der Bauteiltabelle (Korrektur von Hand)
  | 'import' // Sprung: Datenblatt-Import
  | 'categories' // Sprung: Einstellungen › Kategorien und Felder
  | 'settings' // Sprung: Einstellungen › Bibliothek

export type HealthArea = 'data' | 'files' | 'dblib'

export interface CheckInfo {
  label: string
  /** kurze Erklärung, falls das Backend keinen Lösungshinweis liefert */
  hint?: string
  fix?: FixKind
  /** Beschriftung der Behebung, wenn sie vom Standard abweicht (z. B. „Library Ref korrigieren“) */
  fixLabel?: string
  /**
   * Abweichungen je Schwere: dieselbe Prüfung kann als Fehler etwas anderes bedeuten als als Warnung (z. B.
   * „Symbol nicht registriert“ – als Fehler fehlt es **auch** in der Datei, „Aus Dateien übernehmen“ hilft dann nicht).
   * Ein gesetzter `hint` hat hier Vorrang vor den Hinweisen des Backends.
   */
  bySeverity?: Partial<Record<IssueSeverity, Omit<CheckInfo, 'bySeverity'>>>
}

export const AREA_LABEL: Record<HealthArea, string> = { data: 'Daten', files: 'Dateien', dblib: 'DbLib' }

export const SEVERITY_LABEL: Record<IssueSeverity, { one: string; many: string; section: string }> = {
  error: { one: 'Fehler', many: 'Fehler', section: 'Fehler' },
  warning: { one: 'Warnung', many: 'Warnungen', section: 'Warnungen' },
  info: { one: 'Hinweis', many: 'Hinweise', section: 'Hinweise' },
}

export const SEVERITY_ORDER: Record<IssueSeverity, number> = { error: 0, warning: 1, info: 2 }

/** Deutsche Namen der Prüfungen (Daten-, Datei- und DbLib-Ebene; Kennungen: ARCHITEKTUR.md §8.4) */
export const CHECKS: Record<string, CheckInfo> = {
  // Datenebene (/api/health-check)
  required: { label: 'Pflichtfeld leer' },
  duplicate_pn: { label: 'Teilenummer mehrfach vergeben' },
  duplicate_mpn: { label: 'Hersteller-Teilenummer mehrfach' },
  value: { label: 'Ungültiger Wert' },
  format: { label: 'Wert nicht im Standardformat', fix: 'normalize' },
  enum: { label: 'Wert nicht in der Auswahlliste' },
  // Warnung: nicht registriert, steht aber evtl. in der Datei → „Aus Dateien übernehmen“ registriert es.
  // Fehler (mit „nicht in der eingetragenen Datei“ zusammengeführt): weder registriert noch in der Datei.
  symbol_missing: {
    label: 'Symbol nicht registriert',
    fix: 'scan-register',
    bySeverity: {
      error: {
        label: 'Symbol fehlt',
        hint: '„Library Ref“ des Bauteils korrigieren oder das Symbol erzeugen bzw. importieren.',
        fix: 'open-part',
        fixLabel: 'Library Ref korrigieren',
      },
    },
  },
  footprint_missing: {
    label: 'Footprint nicht registriert',
    fix: 'scan-register',
    bySeverity: {
      error: {
        label: 'Footprint fehlt',
        hint: '„Footprint Ref“ des Bauteils korrigieren oder den Footprint mit dem Generator erzeugen.',
        fix: 'open-part',
        fixLabel: 'Footprint Ref korrigieren',
      },
    },
  },
  library_file_missing: { label: 'Bibliotheksdatei fehlt', fix: 'scan-sync' },
  datasheet_missing: { label: 'Kein Datenblatt verknüpft', fix: 'import', fixLabel: 'Datenblatt-Import öffnen' },
  // Registry-Zustand (beide Ebenen, dieselbe Bedeutung)
  registry_error: { label: 'Nicht in die Bibliothek geschrieben', fix: 'sync' },
  registry_missing: {
    label: 'Fehlt und ist nicht erzeugbar',
    hint: 'Registriert, aber ohne Geometrie und nicht aus den gespeicherten Angaben erzeugbar (oder aus der externen Bibliothek verschwunden) – im Symbol- bzw. Footprint-Generator anlegen oder aus einer Bibliothek übernehmen.',
  },
  // Dateiebene (/api/libraries/health)
  component_missing: {
    label: 'Fehlt in der Bibliotheksdatei',
    hint: '„Bibliotheken prüfen“ merkt es vor, „Synchronisieren“ schreibt es neu.',
    fix: 'scan-sync',
  },
  component_not_in_file: { label: 'Nicht in der eingetragenen Datei', fix: 'sync' },
  library_unassigned: { label: 'Keiner Bibliotheksdatei zugeordnet', fix: 'sync' },
  path_empty: { label: 'Bibliothekspfad leer', fix: 'sync' },
  footprint_height_missing: { label: 'Footprint-Höhe fehlt in der PcbLib', fix: 'repair-heights' },
  pin_pad_mismatch: { label: 'Pins und Pads passen nicht zusammen' },
  library_changed_outside: { label: 'Außerhalb von PartForge geändert', fix: 'scan' },
  library_unreadable: { label: 'Bibliotheksdatei nicht lesbar (beschädigt?)', fix: 'restore-backup' },
  // DbLib (/api/altium/status → dblib.issues)
  'dblib.missing': { label: 'DbLib fehlt', fix: 'regenerate' },
  'dblib.outdated': { label: 'DbLib veraltet', fix: 'regenerate' },
  'dblib.format': { label: 'DbLib nicht im Altium-Format', fix: 'regenerate' },
  'dblib.db_path': { label: 'DbLib verweist auf eine andere Datenbank', fix: 'regenerate' },
  'dblib.unreadable': { label: 'DbLib nicht lesbar', fix: 'regenerate' },
  'dblib.db_path_chars': { label: 'Datenbankpfad für Altium ungeeignet' },
  'dblib.file_name': { label: 'Ungültiger DbLib-Dateiname', fix: 'settings' },
  'dblib.build': { label: 'Soll-Stand der DbLib unbekannt' },
  'dblib.parse': { label: 'Auffälligkeit in der DbLib', fix: 'regenerate' },
  'dblib.no_enabled_tables': { label: 'Keine Kategorie für Altium aktiviert', fix: 'categories' },
  'dblib.library_ref': { label: 'Kategorie ohne Spalte „Library Ref“', fix: 'categories' },
  'dblib.unsafe_name': { label: 'Name für die DbLib ungeeignet', fix: 'categories' },
  'dblib.no_key': { label: 'Kategorie ohne Schlüsselspalte', fix: 'categories' },
  'dblib.encoding': { label: 'Zeichen außerhalb von Windows-1252' },
  'dblib.network': { label: 'Datenbank auf einem Netzlaufwerk' },
  'dblib.db_missing': { label: 'Datenbankdatei fehlt' },
  'dblib.wal': { label: 'Datenbank nicht im WAL-Modus' },
  'dblib.other_dblibs': { label: 'Weitere DbLib-Dateien im Bibliotheksordner' },
  'dblib.duplicates': { label: 'Gleichnamige DbLib in Altium installiert', fix: 'install-replace' },
  'dblib.moved_install': { label: 'Alte Installation aus einem anderen Ordner', fix: 'install-replace' },
  'dblib.open_in_editor': { label: 'DbLib in Altium in einem Editor geöffnet' },
}

/** Name einer Prüfung je Schwere (unbekannte Schlüssel lesbar machen) */
export function checkInfo(check: string, severity?: IssueSeverity): CheckInfo {
  const known = CHECKS[check]
  if (known) {
    const { bySeverity, ...base } = known
    const override = severity ? bySeverity?.[severity] : undefined
    return override ? { ...base, ...override } : base
  }
  if (check.startsWith('dblib.')) return { label: 'Hinweis zur DbLib' }
  const text = check.replace(/_/g, ' ')
  return { label: text.charAt(0).toUpperCase() + text.slice(1) }
}

// --------------------------------------------------------------------------- Prüfbericht: Zusammenführen

export interface HealthItem {
  id: string
  area: HealthArea
  severity: IssueSeverity
  check: string
  table: string | null
  part_number: string | null
  column: string | null
  message: string
  fix_hint: string | null
  /** Wovon der Befund handelt, wenn kein Bauteil betroffen ist: Symbol/Footprint, Bibliotheksdatei bzw. DbLib */
  subject: string | null
  /** Symbol oder Footprint (Dateiprüfung) */
  kind: 'symbol' | 'footprint' | null
  /** Name des Symbols/Footprints (Dateiprüfung) */
  component: string | null
  /** Bibliotheksdatei, relativ zum Bibliotheksordner (Dateiprüfung) */
  library: string | null
  /** Bauteile, die der Befund betrifft (ein Bauteil bzw. alle, die Symbol/Footprint/Datei verwenden) */
  affectedParts: number
  /** ihre Teilenummern (sortiert, höchstens 20 – `affectedParts` ist die echte Anzahl) */
  partNumbers: string[]
  /** Ein-Klick-Korrektur des Backends (`repair_footprint_heights`) – nur, wo sie für diesen Eintrag möglich ist */
  fixAction: string | null
}

export interface HealthGroup {
  /** `${severity}:${check}` */
  key: string
  check: string
  severity: IssueSeverity
  info: CheckInfo
  items: HealthItem[]
  /** echte Anzahl – bei gekürzten Prüfungen größer als `items.length` */
  total: number
  /** Liste gekürzt: es gibt mehr Befunde als `items` */
  partial: boolean
  areas: HealthArea[]
  /** häufigster Lösungshinweis der Gruppe */
  hint: string | null
}

export interface MergedHealth {
  items: HealthItem[]
  groups: HealthGroup[]
  counts: Record<IssueSeverity, number>
  /**
   * Bauteile mit mindestens einem Fehler oder einer Warnung: Daten-Befunde je Bauteil und `affected_part_numbers` der
   * Dateiprüfung (jedes Bauteil genau einmal). Untergrenze, wenn `affectedExact` falsch ist.
   */
  affectedParts: number
  /** `affectedParts` ist exakt (keine Teilprüfung fehlt, keine Fehler-/Warnungsprüfung der Datenebene gekürzt) */
  affectedExact: boolean
  /** schwerste Einstufung unter den Befunden, die Bauteile betreffen (`null` = kein Bauteil betroffen) */
  partSeverity: Exclude<IssueSeverity, 'info'> | null
  /** DbLib-Fehler: Altium sieht dann keines der Bauteile (oder die falschen) */
  dblibErrors: number
  /** Fehler und Warnungen, die kein Bauteil betreffen (z. B. ein unbenutzter Eintrag fehlt in seiner Datei) */
  unrelated: { errors: number; warnings: number }
  checkedParts: number
  truncated: boolean
  /** Datenprüfung gekürzt (je Prüfung höchstens {@link DATA_CHECK_LIMIT} gelistet) */
  dataTruncated: boolean
  /** Dateiprüfung gekürzt (insgesamt höchstens {@link FILE_ISSUE_LIMIT} gelistet) */
  filesTruncated: boolean
  /** ISO-Zeitpunkt der Datenprüfung */
  checkedAt: string | null
  /** Teilprüfungen, die nicht geantwortet haben (deutscher Grund) */
  missing: Partial<Record<HealthArea, string>>
}

/** Registry-Zustand: beide Ebenen melden ihn unter derselben Kennung – die Dateiprüfung mit den betroffenen Bauteilen */
const REGISTRY_CHECKS = new Set(['registry_error', 'registry_missing'])
/** DbLib-Codes, die Status statt Befund sind (stehen im Altium-Bereich) */
const DBLIB_STATUS_CODES = new Set(['not_installed'])

/**
 * Darf „Ersetzen und installieren“ die gleichnamigen Installationen ersetzen? Nur alte Ordner derselben Bibliothek
 * (gleiche Datenbank) oder verschwundene Dateien – eine fremde Bibliothek ersetzt PartForge nie.
 */
function duplicatesReplaceable(dblib: DbLibStatus | null | undefined): boolean {
  if (dblib?.issues.some((i) => i.code === 'moved_install')) return true
  const kinds = Object.values(dblib?.install?.duplicate_kinds ?? {})
  return kinds.length > 0 && kinds.every((k) => k === 'same_database' || k === 'missing')
}

/** Name in „…“ (Meldungen der Datenebene ohne strukturierte Angaben: „Symbol „R_0603“ konnte nicht …“) */
function quotedName(message: string): string | null {
  return /„([^“]+)“/.exec(message)?.[1] ?? null
}

function itemKey(item: HealthItem): string {
  if (item.part_number) return `${item.check}|${item.table ?? ''}|${item.part_number}|${item.column ?? ''}`
  if (item.component) return `${item.check}|${item.kind ?? ''}|${item.component.toLowerCase()}`
  if (item.library) return `${item.check}|lib|${item.library.toLowerCase()}`
  return `${item.check}|${item.area}|${item.message}`
}

function mostCommon(values: (string | null)[]): string | null {
  const counts = new Map<string, number>()
  for (const v of values) if (v) counts.set(v, (counts.get(v) ?? 0) + 1)
  let best: string | null = null
  let max = 0
  for (const [v, n] of counts) {
    if (n > max) {
      best = v
      max = n
    }
  }
  return best
}

const rank = (s: IssueSeverity) => SEVERITY_ORDER[s]

/** „Symbol „X“ ist in PartForge nicht registriert.“ + „Symbol „X“ ist nicht in Y enthalten.“ → ein Satz */
function twinMessage(issue: HealthIssue, twin: FileHealthIssue): string {
  const name = twin.component ?? quotedName(issue.message)
  const file = twin.library ?? /ist nicht in (.+?) enthalten\.?$/.exec(twin.message)?.[1]
  if (!name || !file) return `${issue.message} ${twin.message}`
  const kind = issue.check === 'symbol_missing' ? 'Symbol' : 'Footprint'
  return `${kind} „${name}“ ist weder registriert noch in ${file} enthalten.`
}

type ItemInput = Omit<HealthItem, 'id' | 'area' | 'subject' | 'kind' | 'component' | 'library' | 'affectedParts' | 'partNumbers' | 'fixAction'> &
  Partial<Pick<HealthItem, 'kind' | 'component' | 'library' | 'affectedParts' | 'partNumbers' | 'fixAction'>>

function fromFileIssue(issue: FileHealthIssue): ItemInput {
  return {
    severity: issue.severity,
    check: issue.check,
    table: issue.table,
    part_number: issue.part_number,
    column: issue.column,
    message: issue.message,
    fix_hint: issue.fix_hint,
    kind: issue.kind,
    component: issue.component,
    library: issue.library,
    affectedParts: issue.affected_parts || (issue.part_number ? 1 : 0),
    partNumbers: issue.part_numbers.length ? issue.part_numbers : issue.part_number ? [issue.part_number] : [],
    fixAction: issue.fix_action,
  }
}

/**
 * Datenprüfung, Dateiprüfung und DbLib-Befunde zu einem Bericht zusammenführen, gruppiert nach Schwere und Prüfung.
 * Gleiche Befunde beider Ebenen erscheinen einmal (je Bauteil und Spalte bzw. je Symbol/Footprint – die strengere
 * Einstufung gewinnt); den Registry-Zustand (`registry_*`) liefert die Dateiprüfung samt betroffenen Bauteilen, die
 * Datenprüfung nur noch, wenn die Dateiprüfung fehlt. Ein nicht registrierter Verweis, der auch nicht in seiner Datei
 * steht, ist **ein** Befund („Symbol fehlt“, Fehler) statt zweier. Fehlt eine Quelle, bleibt der Bericht nutzbar
 * (`missing`).
 */
export function mergeHealth(
  data: DataHealthReport | undefined,
  files: FileHealthReport | undefined,
  dblib: DbLibStatus | null | undefined,
  missing: Partial<Record<HealthArea, string>> = {},
): MergedHealth {
  const byKey = new Map<string, HealthItem>()
  let seq = 0
  const add = (area: HealthArea, issue: ItemInput) => {
    const component = issue.component ?? null
    const library = issue.library ?? null
    const subject = issue.part_number
      ? null
      : area === 'dblib'
        ? (dblib?.file_name ?? 'DbLib')
        : (component ?? (library ? baseName(library) : quotedName(issue.message)))
    const item: HealthItem = {
      ...issue,
      kind: issue.kind ?? null,
      component,
      library,
      affectedParts: issue.affectedParts ?? (issue.part_number ? 1 : 0),
      partNumbers: issue.partNumbers ?? (issue.part_number ? [issue.part_number] : []),
      fixAction: issue.fixAction ?? null,
      area,
      subject,
      id: `${area}-${seq++}`,
    }
    const key = itemKey(item)
    const existing = byKey.get(key)
    if (!existing) {
      byKey.set(key, item)
      return
    }
    // derselbe Befund aus beiden Prüfungen: die strengere Einstufung; Angaben der Dateiprüfung (betroffene Bauteile) bleiben
    const keep = rank(item.severity) < rank(existing.severity) ? item : existing
    const other = keep === item ? existing : item
    byKey.set(key, {
      ...keep,
      fix_hint: keep.fix_hint ?? other.fix_hint,
      kind: keep.kind ?? other.kind,
      component: keep.component ?? other.component,
      library: keep.library ?? other.library,
      affectedParts: Math.max(keep.affectedParts, other.affectedParts),
      partNumbers: keep.partNumbers.length >= other.partNumbers.length ? keep.partNumbers : other.partNumbers,
      fixAction: keep.fixAction ?? other.fixAction,
    })
  }

  for (const issue of dblib?.issues ?? []) {
    if (DBLIB_STATUS_CODES.has(issue.code)) continue
    add('dblib', {
      severity: issue.severity,
      check: `dblib.${issue.code}`,
      table: null,
      part_number: null,
      column: null,
      message: issue.message,
      fix_hint: null,
    })
  }
  // Verweis auf ein nicht registriertes Symbol/Footprint, das auch nicht in der eingetragenen Datei steht: ein Befund
  // („nicht registriert“, als Fehler – Altium findet es nicht) statt zweier
  const notInFile = new Map<string, FileHealthIssue>()
  for (const issue of files?.issues ?? []) {
    if (issue.check === 'component_not_in_file' && issue.part_number && issue.column) {
      notInFile.set(`${issue.table}|${issue.part_number}|${issue.column}`, issue)
    }
  }
  const consumed = new Set<FileHealthIssue>()
  for (const issue of data?.issues ?? []) {
    if (files && REGISTRY_CHECKS.has(issue.check)) continue // kommt mit betroffenen Bauteilen aus der Dateiprüfung
    if ((issue.check === 'symbol_missing' || issue.check === 'footprint_missing') && issue.part_number && issue.column) {
      const pathColumn = issue.column.replace(/^Library Ref$/i, 'Library Path').replace(/^Footprint Ref/i, 'Footprint Path')
      const twin = notInFile.get(`${issue.table}|${issue.part_number}|${pathColumn}`)
      if (twin) {
        consumed.add(twin)
        // Lösungsweg steht an der Gruppe („… Ref korrigieren“) – kein abweichender Hinweis je Zeile
        add('data', {
          ...issue,
          severity: 'error',
          message: twinMessage(issue, twin),
          fix_hint: null,
          kind: twin.kind,
          component: twin.component,
          library: twin.library,
        })
        continue
      }
    }
    add('data', { ...issue })
  }
  for (const issue of files?.issues ?? []) {
    if (consumed.has(issue)) continue
    add('files', fromFileIssue(issue))
  }

  const items = [...byKey.values()]
  const groupsByKey = new Map<string, HealthGroup>()
  for (const item of items) {
    const key = `${item.severity}:${item.check}`
    let group = groupsByKey.get(key)
    if (!group) {
      group = {
        key,
        check: item.check,
        severity: item.severity,
        info: checkInfo(item.check, item.severity),
        items: [],
        total: 0,
        partial: false,
        areas: [],
        hint: null,
      }
      groupsByKey.set(key, group)
    }
    group.items.push(item)
    if (!group.areas.includes(item.area)) group.areas.push(item.area)
  }

  // Gleichnamige DbLib einer **anderen** Bibliothek: „Ersetzen“ ginge nicht – stattdessen der Lösungsweg
  const duplicates = groupsByKey.get('error:dblib.duplicates')
  if (duplicates && !duplicatesReplaceable(dblib)) {
    duplicates.info = {
      ...duplicates.info,
      fix: undefined,
      hint: 'Der anderen Bibliothek einen eigenen DbLib-Dateinamen geben oder sie in Altium deinstallieren – PartForge ersetzt nur Installationen dieser Bibliothek.',
    }
  }
  // Footprint-Höhen bzw. beschädigte Dateien: die Ein-Klick-Korrektur gibt es nur, wenn mindestens ein Eintrag sie
  // erlaubt (sonst in Altium setzen bzw. ohne lesbare Sicherung: Datei prüfen oder entfernen, siehe Hinweis)
  for (const group of groupsByKey.values()) {
    const action = group.info.fix === 'repair-heights' ? REPAIR_HEIGHTS_ACTION : group.info.fix === 'restore-backup' ? RESTORE_BACKUP_ACTION : null
    if (action && !group.items.some((i) => i.fixAction === action)) {
      group.info = { ...group.info, fix: undefined }
    }
  }

  // Gekürzte Prüfungen: echte Anzahl aus `summary` der Quelle – nur, wenn die Gruppe allein aus ihr stammt und die
  // Prüfung nur in dieser einen Gruppe steht (zusammengeführte Doppelbefunde ließen sich sonst doppelt zählen)
  const groupsPerCheck = new Map<string, number>()
  for (const g of groupsByKey.values()) groupsPerCheck.set(g.check, (groupsPerCheck.get(g.check) ?? 0) + 1)
  for (const group of groupsByKey.values()) {
    group.total = group.items.length
    const severityHint = (group === duplicates ? group.info.hint : undefined) ?? CHECKS[group.check]?.bySeverity?.[group.severity]?.hint
    group.hint = severityHint ?? mostCommon(group.items.map((i) => i.fix_hint)) ?? group.info.hint ?? null
    const only = group.areas.length === 1 ? group.areas[0] : null
    const source = only === 'data' && data?.truncated ? data : only === 'files' && files?.truncated ? files : null
    const reported = source?.summary?.[group.check]
    if (reported && reported > group.total && groupsPerCheck.get(group.check) === 1) {
      group.total = reported
      group.partial = true
    } else if ((data?.truncated && group.areas.includes('data')) || (files?.truncated && group.areas.includes('files'))) {
      const listed = group.areas.includes('data') ? (data?.summary?.[group.check] ?? 0) : 0
      const fileListed = group.areas.includes('files') ? (files?.summary?.[group.check] ?? 0) : 0
      group.partial = Math.max(listed, fileListed) > group.items.length
    }
  }

  const groups = [...groupsByKey.values()].sort(
    (a, b) => rank(a.severity) - rank(b.severity) || b.total - a.total || a.info.label.localeCompare(b.info.label, 'de'),
  )
  const counts: Record<IssueSeverity, number> = { error: 0, warning: 0, info: 0 }
  for (const g of groups) counts[g.severity] += g.total

  // Betroffene Bauteile: Daten-Befunde je Bauteil + alle Bauteile der Dateiprüfung (`affected_part_numbers`, exakt)
  const affected = new Set<string>()
  let partSeverity: MergedHealth['partSeverity'] = null
  let dblibErrors = 0
  const unrelated = { errors: 0, warnings: 0 }
  for (const g of groups) {
    if (g.severity === 'info') continue
    for (const item of g.items) {
      if (item.area === 'dblib') {
        if (item.severity === 'error') dblibErrors += 1
        else unrelated.warnings += 1
        continue
      }
      const concernsParts = Boolean(item.part_number) || item.affectedParts > 0
      if (item.part_number) affected.add(item.part_number)
      for (const pn of item.partNumbers) affected.add(pn)
      if (concernsParts) {
        if (item.severity === 'error') partSeverity = 'error'
        else if (partSeverity === null) partSeverity = 'warning'
      } else if (item.severity === 'error') unrelated.errors += 1
      else unrelated.warnings += 1
    }
  }
  for (const pn of files?.affected_part_numbers ?? []) affected.add(pn)
  if (dblibErrors) partSeverity = 'error'
  // Untergrenze, wenn eine Teilprüfung fehlt oder eine Fehler-/Warnungsprüfung der Datenebene gekürzt ist
  let affectedExact = !missing.data && !missing.files && Boolean(data) && Boolean(files)
  if (data?.truncated) {
    const listed = new Map<string, number>()
    for (const issue of data.issues) listed.set(issue.check, (listed.get(issue.check) ?? 0) + 1)
    const severityOf = new Map(data.issues.map((i) => [i.check, i.severity] as const))
    for (const [check, n] of Object.entries(data.summary)) {
      if (severityOf.get(check) !== 'info' && n > (listed.get(check) ?? 0) && !REGISTRY_CHECKS.has(check)) affectedExact = false
    }
  }

  return {
    items,
    groups,
    counts,
    affectedParts: affected.size,
    affectedExact,
    partSeverity,
    dblibErrors,
    unrelated,
    checkedParts: files?.checked_parts ?? 0,
    truncated: Boolean(data?.truncated || files?.truncated),
    dataTruncated: Boolean(data?.truncated),
    filesTruncated: Boolean(files?.truncated),
    checkedAt: data?.checked_at ?? null,
    missing,
  }
}

/**
 * Meldung eines Befunds ohne den Namen seiner Prüfung davor – die Gruppe nennt ihn schon
 * („Footprint-Höhe fehlt in der PcbLib: „X“ hat …“ → „„X“ hat …“).
 */
export function findingMessage(item: Pick<HealthItem, 'message'>, group: { info: Pick<CheckInfo, 'label'> }): string {
  const prefix = `${group.info.label}: `
  const { message } = item
  return message.length > prefix.length && message.toLowerCase().startsWith(prefix.toLowerCase()) ? message.slice(prefix.length) : message
}

/** Bauteile ohne Fehler und Warnungen – für den Gesundheitsring der Übersicht */
export interface PartHealth {
  /** Anteil 0…1 */
  score: number
  clean: number
  affected: number
  /** `clean` ist exakt – sonst eine Obergrenze („höchstens“) */
  exact: boolean
  /** DbLib-Fehler: alle Bauteile betroffen */
  dblib: boolean
  tone: 'success' | 'warning' | 'danger'
}

/**
 * Anteil der Bauteile ohne Fehler und Warnungen: jedes betroffene Bauteil genau einmal (Daten- und Dateiebene, auch
 * Befunde zu Symbol, Footprint oder Datei mit allen Bauteilen, die sie verwenden). Ein DbLib-Fehler betrifft alle
 * Bauteile. Der Ton folgt den Befunden, die Bauteile betreffen – ein unbenutzter Eintrag färbt den Ring nicht.
 */
export function partHealth(report: MergedHealth, totalParts: number): PartHealth | null {
  if (totalParts <= 0) return null
  const dblib = report.dblibErrors > 0
  const affected = dblib ? totalParts : Math.min(totalParts, report.affectedParts)
  const clean = totalParts - affected
  const tone = dblib || report.partSeverity === 'error' ? 'danger' : report.partSeverity === 'warning' ? 'warning' : 'success'
  return { score: clean / totalParts, clean, affected, exact: dblib || report.affectedExact, dblib, tone }
}

/**
 * Fehler und Warnungen der **Datenebene**, die zu einem Bauteil gehören (Pflichtfelder, Dubletten, Werte, Verweise) –
 * das Glied „Bauteile“ der Altium-Kette. DbLib- und Dateibefunde zählen bei ihren eigenen Gliedern.
 */
export function partFindings(report: MergedHealth | null | undefined): { errors: number; warnings: number } | null {
  if (!report) return null
  const out = { errors: 0, warnings: 0 }
  for (const g of report.groups) {
    if (g.severity === 'info') continue
    const own = g.items.filter((i) => i.area === 'data' && i.part_number).length
    // gekürzte reine Datengruppe: die echte Anzahl steht in `total`
    const n = own === g.items.length && g.total > g.items.length ? g.total : own
    if (g.severity === 'error') out.errors += n
    else out.warnings += n
  }
  return out
}

/** Fehler außerhalb der Bauteildaten – für die Kette (Glied „Bibliotheksdateien“) */
export interface LibraryFindings {
  /** DbLib-Fehler: Altium sieht dann keine oder die falschen Bauteile */
  dblibErrors: number
  /** Dateifehler ohne Bauteil: ein registriertes Symbol/Footprint fehlt in seiner Datei oder die Datei fehlt */
  fileErrors: number
  /** Bauteile, die auf eine fehlende Bibliothek oder einen fehlenden Eintrag verweisen (Dateiprüfung, je Bauteil einmal) */
  linkErrors: number
  /** Footprints, deren PcbLib die Höhe 0 trägt (`footprint_height_missing`; gekürzte Liste: echte Anzahl) */
  heights: number
  /** davon mit Ein-Klick-Korrektur (`repair_footprint_heights`) */
  heightsRepairable: number
  /** Footprints ohne Höhe je Bibliotheksdatei (Schlüssel: {@link libraryKey}) – davon mit Ein-Klick-Korrektur */
  heightsByLibrary: Map<string, LibraryHeights>
}

/** Footprints ohne Höhe in einer Bibliotheksdatei */
export interface LibraryHeights {
  total: number
  /** mit Ein-Klick-Korrektur (sonst: Datei außerhalb geändert – Höhe in Altium eintragen) */
  repairable: number
}

/** „Bibliothek aus Sicherung wiederherstellen“ (`libraries.sync`) – `partforge.altium.sync.restore_library_backup` */
export interface LibraryRestoreResult {
  library: string | null
  backup: string | null
  /** beschädigte Datei, aufbewahrt unter Backups\lib (…defekt) */
  damaged: string | null
  components: number
  rewritten: string[]
  errors: { name?: string; message?: string | null }[]
  message: string
}

/** Bibliothekspfad als Schlüssel (relativ, klein geschrieben, „/“ und „\“ als Trenner gleich) */
export function libraryKey(rel: string): string {
  return rel.replace(/\//g, '\\').toLowerCase()
}

export function libraryFindings(report: MergedHealth | null | undefined): LibraryFindings | null {
  if (!report) return null
  const links = new Set<string>()
  let fileErrors = 0
  let heightsRepairable = 0
  const heightsByLibrary = new Map<string, LibraryHeights>()
  for (const item of report.items) {
    if (item.check === HEIGHT_CHECK) {
      const repairable = item.fixAction === REPAIR_HEIGHTS_ACTION
      if (repairable) heightsRepairable += 1
      if (item.library) {
        const key = libraryKey(item.library)
        const cur = heightsByLibrary.get(key) ?? { total: 0, repairable: 0 }
        heightsByLibrary.set(key, { total: cur.total + 1, repairable: cur.repairable + (repairable ? 1 : 0) })
      }
    }
    if (item.severity !== 'error' || item.area !== 'files') continue
    if (item.part_number) links.add(item.part_number)
    else fileErrors += 1
  }
  const heights = report.groups.filter((g) => g.check === HEIGHT_CHECK).reduce((n, g) => n + g.total, 0)
  return { dblibErrors: report.dblibErrors, fileErrors, linkErrors: links.size, heights, heightsRepairable, heightsByLibrary }
}

// --------------------------------------------------------------------------- Prüfbericht: wann neu prüfen

/**
 * Jobarten, nach denen sich der Prüfbericht ändern kann: Bauteile (Serie, Tabellen-Import, Datenblatt-Übernahme),
 * Registry und Bibliotheksdateien (`libraries*`). Exporte, Datenblatt-Analyse/-Suche, ODBC-Test, Altium-Jobs ändern ihn
 * nicht (DbLib-Befunde kommen ohnehin frisch aus `/api/altium/status`).
 */
export const HEALTH_JOB_KINDS: ReadonlySet<string> = new Set([
  'series',
  'import',
  'datasheet-commit',
  'libraries',
  'libraries.sync',
  'libraries.scan',
  'libraries.save',
  'libraries.delete',
  'libraries.layers',
  'libraries.import',
  'libraries.conform',
])

/** Direkte Schreibzugriffe (ohne Job), nach denen der Bericht nicht mehr stimmt: Bauteile, Kategorien, externe Bibliotheken */
const HEALTH_WRITES: readonly (readonly [string, RegExp])[] = [
  ['POST', /^\/api\/parts\/[^/]+(?:\/(?:delete|bulk-update|restore|restore-updates|regenerate-texts))?$/],
  ['POST', /^\/api\/parts\/[^/]+\/.+\/duplicate$/],
  ['PATCH', /^\/api\/parts\/[^/]+\/.+$/],
  ['DELETE', /^\/api\/parts\/[^/]+$/],
  ['POST', /^\/api\/backups\/[^/]+\/restore$/],
  ['POST', /^\/api\/categories(?:\/.*)?$/],
  ['PATCH', /^\/api\/categories\/.+$/],
  ['DELETE', /^\/api\/categories\/.+$/],
  ['POST', /^\/api\/libraries\/external(?:\/[^/]+\/use)?$/],
  ['DELETE', /^\/api\/libraries\/external\/[^/]+$/],
]

/** Seit wann diese Sitzung läuft (s) – vorher beendete Jobs lösen keine Prüfung aus */
const sessionStart = Date.now() / 1000
const healthJobsHandled = new Set<string>()
let healthWatchers = false
let healthRefreshTimer: ReturnType<typeof setTimeout> | null = null

/** Prüfbericht neu laden – gebündelt (viele Änderungen kurz nacheinander = eine Prüfung, das Backend rechnet sonst je Anfrage) */
function scheduleHealthRefresh(qc: QueryClient): void {
  if (healthRefreshTimer) clearTimeout(healthRefreshTimer)
  healthRefreshTimer = setTimeout(() => {
    healthRefreshTimer = null
    void qc.invalidateQueries({ queryKey: librariesKeys.dataHealth, exact: true })
    void qc.invalidateQueries({ queryKey: librariesKeys.fileHealth, exact: true })
  }, 1200)
}

/** Schnappschüsse aus Job-Cache und Joblisten (`['system', 'job', id]`, `['system', 'jobs', …]`) */
function jobsIn(data: unknown): { id: string; kind: string; status: string; finished?: number | null }[] {
  const isJob = (j: unknown): j is { id: string; kind: string; status: string; finished?: number | null } =>
    Boolean(j && typeof j === 'object' && 'id' in j && 'kind' in j && 'status' in j)
  if (Array.isArray(data)) return data.filter(isJob)
  return isJob(data) ? [data] : []
}

/**
 * Der Prüfbericht ist teuer (beide Prüfungen laufen über die ganze Bibliothek): er lädt **nicht** nach jedem beliebigen
 * Job neu (`meta.static`), sondern nur nach Jobs, die Bauteile oder Bibliotheksdateien ändern ({@link HEALTH_JOB_KINDS}),
 * nach direkten Schreibzugriffen ({@link HEALTH_WRITES}) und auf ausdrücklichen Wunsch („Bibliothek prüfen“). Einmal
 * je Sitzung eingerichtet.
 */
function watchHealthTriggers(qc: QueryClient): void {
  if (healthWatchers) return
  healthWatchers = true
  qc.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated' || event.action.type !== 'success' || event.query.queryKey[0] !== 'system') return
    let hit = false
    for (const job of jobsIn(event.query.state.data)) {
      if (job.status !== 'done' || !HEALTH_JOB_KINDS.has(job.kind) || healthJobsHandled.has(job.id)) continue
      if ((job.finished ?? 0) < sessionStart) continue
      healthJobsHandled.add(job.id)
      hit = true
    }
    if (hit) scheduleHealthRefresh(qc)
  })
  for (const [method, path] of HEALTH_WRITES) {
    observeApi(method, path, (outcome) => {
      if (outcome.ok) scheduleHealthRefresh(qc)
    })
  }
}

// --------------------------------------------------------------------------- Prüfbericht: Hook

/**
 * Zusammengeführter Prüfbericht (Daten + Dateien + DbLib). `report` ist gesetzt, sobald Daten- und Dateiprüfung
 * geantwortet haben (mindestens eine erfolgreich); gescheiterte Teilprüfungen stehen in `report.missing`.
 * `refetch()` prüft alles neu. Ein vorhandener Bericht erscheint sofort (Übersicht ↔ Altium-Seite teilen ihn) und wird
 * nur neu erstellt, wenn sich etwas geändert hat (siehe {@link watchHealthTriggers}) – oder spätestens nach 10 Minuten.
 */
export function useHealthReport(enabled = true) {
  const qc = useQueryClient()
  watchHealthTriggers(qc)
  const dataQ = useQuery({
    queryKey: librariesKeys.dataHealth,
    queryFn: ({ signal }) => librariesApi.dataHealth(signal),
    enabled,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    retry: false,
    meta: { static: true },
  })
  const filesQ = useQuery({
    queryKey: librariesKeys.fileHealth,
    queryFn: ({ signal }) => librariesApi.fileHealth(signal),
    enabled,
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    retry: false,
    meta: { static: true },
  })
  const statusQ = useAltiumStatus(enabled)

  const dataError = dataQ.error ? dataQ.error.message : undefined
  const filesError = filesQ.error ? filesQ.error.message : undefined
  const statusError = statusQ.error ? statusQ.error.message : undefined
  // erst zeigen, wenn beide Prüfungen geantwortet haben (sonst springen Gruppen um, sobald die zweite eintrifft)
  const dataSettled = Boolean(dataQ.data) || dataQ.isError
  const filesSettled = Boolean(filesQ.data) || filesQ.isError
  const report = useMemo(() => {
    if (!dataSettled || !filesSettled) return undefined
    if (!dataQ.data && !filesQ.data) return undefined
    const missing: Partial<Record<HealthArea, string>> = {}
    if (dataError) missing.data = dataError
    if (filesError) missing.files = filesError
    if (statusError) missing.dblib = statusError
    return mergeHealth(dataQ.data, filesQ.data, statusQ.data?.dblib, missing)
  }, [dataQ.data, filesQ.data, statusQ.data?.dblib, dataError, filesError, statusError, dataSettled, filesSettled])

  const failed = Boolean(dataQ.error && filesQ.error)
  return {
    report,
    /** erste vollständige Antwort steht noch aus */
    isLoading: !report && !failed && (!dataSettled || !filesSettled),
    isFetching: dataQ.isFetching || filesQ.isFetching,
    /** beide Prüfungen fehlgeschlagen */
    error: failed ? (dataQ.error ?? filesQ.error) : null,
    /** Zeitpunkt der letzten vollständigen Antwort (ms) */
    updatedAt: Math.max(dataQ.dataUpdatedAt, filesQ.dataUpdatedAt) || null,
    refetch: async () => {
      await Promise.all([
        qc.refetchQueries({ queryKey: librariesKeys.dataHealth, exact: true }),
        qc.refetchQueries({ queryKey: librariesKeys.fileHealth, exact: true }),
        qc.refetchQueries({ queryKey: altiumKeys.status, exact: true }),
      ])
    },
  }
}
