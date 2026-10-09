/**
 * Datenblatt-Import (Claude): Upload, URL-Import, Datenblattsuche, Seitenbilder, Kostenschätzung, Analyse-Job,
 * Extraktion (lesen/korrigieren), Vorschlag (Trockenlauf) und Übernahme (Job) sowie KI-Status und Verbindungstest.
 *
 *   const list = useDatasheets()                          // GET  /api/datasheets
 *   const ds = useDatasheet(id)                           // GET  /api/datasheets/{id}
 *   const ex = useExtraction(id)                          // GET  /api/datasheets/{id}/extraction
 *   const pr = useProposal(id, choices)                   // POST /api/datasheets/{id}/proposal (entprellt aufrufen)
 *   const est = useCostEstimate(id, { vision: 'auto' })   // POST /api/datasheets/{id}/estimate (keine Claude-Anfrage)
 *   const { job } = await datasheetsApi.extract(id, opts) // POST /api/datasheets/{id}/extract → Job
 *   const { job } = await datasheetsApi.find({ query })   // POST /api/datasheets/find → Job „datasheet-find“
 *   <img src={datasheetPageUrl(id, 3, 40)} />             // Seitenbild (PNG, serverseitig gecacht)
 *
 * Kosten: Jede bezahlte Claude-Anfrage steht in `runs` (auch fehlgeschlagene), `cost_usd` ist die Summe je
 * Datenblatt. Der Schlüssel verlässt das Backend nie – `/api/ai/status` meldet nur, ob und woher er kommt
 * (`key_source` = env | stored | file | replay). Ist Claude nicht nutzbar, antworten die KI-Endpunkte mit 503
 * `{ code, message }` (`AiErrorCode`) – einordnen mit `classifyAiError` aus `@/api/system`.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type DownloadResult } from './client'
import type { AiProblemCode, Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

export type DatasheetSummary = Filled<ResponseOf<'/api/datasheets', 'get'>>[number]
export type DatasheetDetail = Filled<ResponseOf<'/api/datasheets/{datasheet_id}', 'get'>>
export type DatasheetStatus = DatasheetSummary['status']
export type PageInfo = DatasheetDetail['pages'][number]
export type PageQuality = PageInfo['quality']
export type RunInfo = DatasheetDetail['runs'][number]
export type CommitInfo = DatasheetDetail['committed'][number]
export type UploadResult = Filled<ResponseOf<'/api/datasheets', 'post'>>

export type ExtractionOut = Filled<ResponseOf<'/api/datasheets/{datasheet_id}/extraction', 'get'>>
export type ExtractionData = ExtractionOut['extraction']
export type DeviceData = ExtractionData['devices'][number]
export type ParameterData = DeviceData['parameters'][number]
export type VariantData = DeviceData['variants'][number]
export type PinTableData = DeviceData['pin_tables'][number]
export type PinData = PinTableData['pins'][number]
export type PackageData = ExtractionData['packages'][number]
export type DimValue = PackageData['dimensions'][number]
export type LandPatternData = PackageData['land_pattern']
export type RowReference = LandPatternData['row_spacing_reference']
export type ExtractionIssue = ExtractionData['issues'][number]
export type IssueSeverity = ExtractionIssue['severity']

export type PartProposal = Filled<ResponseOf<'/api/datasheets/{datasheet_id}/proposal', 'post'>>
export type VariantProposal = PartProposal['variants'][number]
export type SymbolProposal = PartProposal['symbols'][number]
export type FootprintProposal = PartProposal['footprints'][number]
export type FootprintAlternative = FootprintProposal['alternatives'][number]
export type ProposalChoices = NonNullable<RequestBodyOf<'/api/datasheets/{datasheet_id}/proposal', 'post'>>
export type PackageChoice = NonNullable<ProposalChoices['packages']>[string]
export type SymbolChoice = NonNullable<ProposalChoices['symbol']>
export type ExtractOptions = NonNullable<RequestBodyOf<'/api/datasheets/{datasheet_id}/extract', 'post'>>
export type FromUrlInput = RequestBodyOf<'/api/datasheets/from-url', 'post'>
export type FindInput = RequestBodyOf<'/api/datasheets/find', 'post'>
export type DeleteResult = Filled<ResponseOf<'/api/datasheets/{datasheet_id}', 'delete'>>
/** Kostenschätzung einer Analyse (`POST …/estimate`, keine Claude-Anfrage) */
export type CostEstimate = Filled<ResponseOf<'/api/datasheets/{datasheet_id}/estimate', 'post'>>

export type AiStatus = Filled<ResponseOf<'/api/ai/status', 'get'>>
export type AiTestResult = Filled<ResponseOf<'/api/ai/test', 'post'>>
/** `detail.code` einer 503-Antwort der KI-Endpunkte (und jedes Fehlers von `POST /api/ai/test`) – `classifyAiError` */
export type AiErrorCode = AiProblemCode

/** Registrierte Symbole/Footprints (Auswahl „vorhandenes Symbol/Footprint verwenden“) */
export type LibrarySymbolEntry = Filled<ResponseOf<'/api/libraries/symbols', 'get'>>[number]
export type LibraryFootprintEntry = Filled<ResponseOf<'/api/libraries/footprints', 'get'>>[number]

// --------------------------------------------------------------------------- Job-Ergebnisse (untypisierte dicts)

/** `partforge.datasheet.extract.ExtractionSummary` – Ergebnis von POST …/extract */
export interface ExtractionSummary {
  datasheet_id: string
  model: string
  served_model: string
  effort: string
  pages: number[]
  identity_pages: number[]
  geometry_pages: number[]
  selection_method: string
  devices: string[]
  mpns: number
  packages: string[]
  pins: number
  issues: Partial<Record<IssueSeverity, number>>
  vision: boolean
  cost_usd: number
  duration_s: number
  /** „Claude Opus 5.5 · Aufwand niedrig“ */
  model_label?: string
  /** `pending` = die Bibliothek war beim Speichern geschlossen – das Ergebnis liegt in ihrem Ordner */
  stored?: 'library' | 'pending'
  /** Schlusssatz des Jobs („Analyse fertig: 14 Bestellvarianten, 13 Pins, 2 Gehäuse – 0,23 $“) */
  message?: string
}

/** Ergebnis von Upload- bzw. URL-Job (Textebene lesen, optional analysieren) */
export interface AnalysisJobResult {
  datasheet_id: string
  page_count: number
  extraction?: ExtractionSummary
  duplicate?: boolean
}

export type ImportJobResult = ExtractionSummary | AnalysisJobResult

/** `partforge.datasheet.proposal.commit_proposal` – Ergebnis des Übernahme-Jobs */
export interface CommitResult {
  table: string
  created: string[]
  updated: string[]
  skipped: string[]
  unchanged: string[]
  errors: Record<string, string>
  symbols: string[]
  footprints: string[]
  warnings: string[]
  /** Fingerabdruck des geschriebenen Vorschlags */
  fingerprint?: string
  /** „Angelegt: 2 Bauteile, 2 Symbole, 2 Footprints“ */
  message?: string
}

/** Ein gefundener Link der Datenblattsuche (`partforge.datasheet.find.FindCandidate`) */
export interface FindCandidate {
  url: string
  title: string
  manufacturer: string
  part_numbers: string[]
  /** hersteller = Website des Herstellers, distributor, andere (Archive, alles Übrige) */
  source: 'hersteller' | 'distributor' | 'andere'
  /** Die Prüfung (kleiner Range-GET) hat ein PDF gefunden */
  is_pdf: boolean
  size_bytes: number | null
  /** Anmerkung von Claude (deutsch) */
  note: string
  /** Ergebnis der Prüfung, wenn es kein brauchbares PDF ist („Webseite statt PDF“, „HTTP 403“ …) */
  check: string | null
  final_url: string | null
  in_search_results: boolean
  /** Nicht von Claude: die stabile Datenblattadresse des Herstellers (geprüft) */
  derived: boolean
}

/** Ergebnis des Jobs „Datenblatt suchen“ (`partforge.datasheet.find.FindResult`) */
export interface FindResult {
  query: string
  manufacturer: string | null
  candidates: FindCandidate[]
  cost_usd: number
  /** Suchanfragen, die Claude gestellt hat */
  searches: string[]
  note: string
  model: string
  model_label: string
  structured: boolean
  runs: RunInfo[]
  message: string
  /** Datenblatt, dem die Suchkosten zugerechnet wurden */
  attached_to?: string
}

// --------------------------------------------------------------------------- Strukturierter Fortschritt (job.detail)

/** Schritt-IDs der Datenblatt-Jobs (`detail.step`, stabil) */
export type DatasheetStep = 'download' | 'read' | 'select_pages' | 'identity' | 'geometry' | 'check' | 'save'

/** `job.detail` der Jobs `datasheet` (Lesen, Analyse, URL-Import) */
export type DatasheetJobDetail = {
  steps: string[]
  step: string
  step_label: string
  /** beim URL-Import, sobald das PDF gespeichert ist */
  datasheet_id: string
  pages_total: number
  pages_selected: number[]
  /** Seiten der laufenden Anfrage bzw. der Kontrolle mit Seitenbildern */
  pages_active: number[]
  counters: Partial<Record<'mpns' | 'pins' | 'parameters' | 'packages' | 'dimensions', number>>
  cost_usd: number
  budget_usd: number
  /** „Claude Opus 5.5 · Aufwand niedrig“ */
  model_label: string
}

/** `job.detail` des Übernahme-Jobs (`datasheet-commit`) – `code` bei einer Ablehnung (`error_type: CommitRefused`) */
export type CommitJobDetail = {
  steps: string[]
  step: string
  step_label: string
  datasheet_id: string
  fingerprint: string
  code: 'unconfirmed_blockers' | 'proposal_changed'
  unconfirmed_blockers: string[]
  expected_fingerprint: string
}

/** `job.detail` der Datenblattsuche (`datasheet-find`) */
export type FindJobDetail = {
  steps: string[]
  step: 'search' | 'check'
  step_label: string
  searches: number
  queries: string[]
  candidates: number
  cost_usd: number
  budget_usd: number
  model_label: string
}

export const FIND_JOB_KIND = 'datasheet-find'

/** Datenblatt-ID aus dem Ergebnis eines Upload-, URL- oder Analyse-Jobs */
export function jobDatasheetId(result: unknown): string | null {
  if (!result || typeof result !== 'object') return null
  const id = (result as { datasheet_id?: unknown }).datasheet_id
  return typeof id === 'string' && id ? id : null
}

/** Analyse-Zusammenfassung aus dem Ergebnis eines Upload-, URL- oder Analyse-Jobs */
export function jobExtractionSummary(result: unknown): ExtractionSummary | null {
  if (!result || typeof result !== 'object') return null
  const r = result as Partial<AnalysisJobResult & ExtractionSummary>
  if (r.extraction && typeof r.extraction === 'object') return r.extraction
  return typeof r.model === 'string' && Array.isArray(r.pages) ? (r as ExtractionSummary) : null
}

// --------------------------------------------------------------------------- Query-Keys

export const datasheetKeys = {
  all: ['datasheets'] as const,
  list: ['datasheets', 'list'] as const,
  detail: (id: string) => ['datasheets', 'detail', id] as const,
  extraction: (id: string) => ['datasheets', 'extraction', id] as const,
  proposalAll: (id: string) => ['datasheets', 'proposal', id] as const,
  proposal: (id: string, choices: ProposalChoices) => ['datasheets', 'proposal', id, choices] as const,
  estimate: (id: string, options: Partial<ExtractOptions> | null) => ['datasheets', 'estimate', id, options ?? {}] as const,
  aiStatus: ['datasheets', 'ai-status'] as const,
  symbols: ['datasheets', 'library-symbols'] as const,
  footprints: ['datasheets', 'library-footprints'] as const,
}

// --------------------------------------------------------------------------- Funktionen

const enc = encodeURIComponent

/**
 * Seitenbild als URL **mit** Token im Query-Parameter. Das ist bewusst: ein `<img src>` kann keinen
 * Header senden. Das Token taucht dadurch im uvicorn-Zugriffsprotokoll auf – dort wird `token=` jedoch
 * geschwärzt (siehe ARCHITEKTUR.md, „Sicherheit“). `dpi` 36…300, Standard 110; 200 für Details.
 */
export function datasheetPageUrl(id: string, page: number, dpi?: number): string {
  return api.url(`/api/datasheets/${enc(id)}/pages/${page}.png`, dpi ? { dpi: Math.round(dpi) } : undefined)
}

/** Die PDF-Datei (inline) als Blob laden – mit Token-**Header**, nicht als `?token=` in der Adresse. */
export function datasheetFile(id: string): Promise<DownloadResult> {
  return api.download(`/api/datasheets/${enc(id)}/file`)
}

export const datasheetsApi = {
  list: (signal?: AbortSignal) => api.get<DatasheetSummary[]>('/api/datasheets', { signal }),
  detail: (id: string, signal?: AbortSignal) => api.get<DatasheetDetail>(`/api/datasheets/${enc(id)}`, { signal }),
  /** PDF hochladen (multipart). `extract` startet die Claude-Analyse gleich mit (sonst nur die Textebene). */
  upload: (file: File, opts: { extract?: boolean; options?: ExtractOptions | null } = {}) => {
    const form = new FormData()
    form.append('file', file, file.name)
    form.append('extract', opts.extract ? 'true' : 'false')
    if (opts.options) form.append('options', JSON.stringify(opts.options))
    return api.upload<UploadResult>('/api/datasheets', form)
  },
  fromUrl: (input: FromUrlInput) => api.post<{ job: Job<AnalysisJobResult> }>('/api/datasheets/from-url', input),
  /** „Datenblatt suchen“ – Claude sucht das PDF im Web (bezahlt, höchstens 3 Suchen; braucht keine Bibliothek) */
  find: (input: FindInput) => api.post<{ job: Job<FindResult> }>('/api/datasheets/find', input),
  /** Erwartete Kosten einer Analyse mit diesen Optionen – ohne Claude-Anfrage (liest ggf. erst die Textebene) */
  estimate: (id: string, options: Partial<ExtractOptions> | null, signal?: AbortSignal) =>
    api.post<CostEstimate>(`/api/datasheets/${enc(id)}/estimate`, options ?? {}, { signal }),
  extract: (id: string, options?: Partial<ExtractOptions> | null) =>
    api.post<{ job: Job<ExtractionSummary> }>(`/api/datasheets/${enc(id)}/extract`, options ?? {}),
  extraction: (id: string, signal?: AbortSignal) =>
    api.get<ExtractionOut>(`/api/datasheets/${enc(id)}/extraction`, { signal }),
  saveExtraction: (id: string, data: ExtractionData) =>
    api.put<ExtractionOut>(`/api/datasheets/${enc(id)}/extraction`, data),
  /** Trockenlauf „Bauteil anlegen“ (schreibt nichts). Ohne SVGs – die Vorschau zeichnet die Specs selbst. */
  proposal: (id: string, choices: ProposalChoices, signal?: AbortSignal, svg = false) =>
    api.post<PartProposal>(`/api/datasheets/${enc(id)}/proposal`, choices, { query: { svg }, signal }),
  /**
   * Übernahme (Job). Mit `accept_issues` = bestätigte Blocker-Texte und `expected_fingerprint` = Fingerabdruck des
   * geprüften Vorschlags: Der Job lehnt ab (`CommitRefused`, nichts geschrieben), wenn etwas nicht bestätigt ist oder
   * der neu gebaute Vorschlag abweicht – `detail.code` sagt, was (`CommitJobDetail`).
   */
  commit: (id: string, choices: ProposalChoices) =>
    api.post<{ job: Job<CommitResult> }>(`/api/datasheets/${enc(id)}/commit`, choices),
  remove: (id: string, deleteFile = true) =>
    api.delete<DeleteResult>(`/api/datasheets/${enc(id)}`, { query: { delete_file: deleteFile } }),
  aiStatus: (signal?: AbortSignal) => api.get<AiStatus>('/api/ai/status', { signal }),
  /** Winzige Testanfrage an das schnelle Modell (kostet einen Bruchteil eines Cents) */
  aiTest: () => api.post<AiTestResult>('/api/ai/test', undefined, { timeoutMs: 90_000 }),
  librarySymbols: (signal?: AbortSignal) => api.get<LibrarySymbolEntry[]>('/api/libraries/symbols', { signal }),
  libraryFootprints: (signal?: AbortSignal) => api.get<LibraryFootprintEntry[]>('/api/libraries/footprints', { signal }),
}

// --------------------------------------------------------------------------- Hooks

/** Alle Datenblätter der Bibliothek (neueste zuerst sortiert die Seite selbst). */
export function useDatasheets() {
  return useQuery({
    queryKey: datasheetKeys.list,
    queryFn: ({ signal }) => datasheetsApi.list(signal),
    staleTime: 5_000,
  })
}

export function useDatasheet(id: string | null | undefined) {
  return useQuery({
    queryKey: datasheetKeys.detail(id ?? '–'),
    queryFn: ({ signal }) => datasheetsApi.detail(id as string, signal),
    enabled: Boolean(id),
    staleTime: 5_000,
  })
}

/** Extraktion (normalisiert, ggf. vom Benutzer korrigiert); 404 = noch nicht analysiert. */
export function useExtraction(id: string | null | undefined, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: datasheetKeys.extraction(id ?? '–'),
    queryFn: ({ signal }) => datasheetsApi.extraction(id as string, signal),
    enabled: Boolean(id) && (opts.enabled ?? true),
    staleTime: 30_000,
  })
}

/**
 * Vorschlag für „Bauteil anlegen“ mit den Entscheidungen des Benutzers – `choices` entprellt übergeben.
 * Die letzte Antwort bleibt sichtbar, solange die neue berechnet wird.
 */
export function useProposal(id: string | null | undefined, choices: ProposalChoices, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: datasheetKeys.proposal(id ?? '–', choices),
    queryFn: ({ signal }) => datasheetsApi.proposal(id as string, choices, signal),
    enabled: Boolean(id) && (opts.enabled ?? true),
    placeholderData: keepPreviousData,
    staleTime: 20_000,
  })
}

/**
 * Erwartete Kosten einer Analyse (Backend-Schätzung aus Seitenauswahl, Seitenart und Modellpreisen – keine
 * Claude-Anfrage). `options` wie für die Analyse; die letzte Schätzung bleibt sichtbar, solange die neue lädt.
 */
export function useCostEstimate(
  id: string | null | undefined,
  options: Partial<ExtractOptions> | null = null,
  opts: { enabled?: boolean } = {},
) {
  return useQuery({
    queryKey: datasheetKeys.estimate(id ?? '–', options),
    queryFn: ({ signal }) => datasheetsApi.estimate(id as string, options, signal),
    enabled: Boolean(id) && (opts.enabled ?? true),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
  })
}

/** KI-Status (Schlüssel vorhanden? Modell, Aufwand, Budget) – immer frisch, Einstellungen ändern sich woanders. */
export function useAiStatus() {
  return useQuery({
    queryKey: datasheetKeys.aiStatus,
    queryFn: ({ signal }) => datasheetsApi.aiStatus(signal),
    staleTime: 5_000,
    refetchOnMount: 'always',
  })
}

export function useLibrarySymbolNames(enabled = true) {
  return useQuery({
    queryKey: datasheetKeys.symbols,
    queryFn: ({ signal }) => datasheetsApi.librarySymbols(signal),
    enabled,
    staleTime: 30_000,
  })
}

export function useLibraryFootprintNames(enabled = true) {
  return useQuery({
    queryKey: datasheetKeys.footprints,
    queryFn: ({ signal }) => datasheetsApi.libraryFootprints(signal),
    enabled,
    staleTime: 30_000,
  })
}

/**
 * Korrigierte Extraktion speichern (bereinigt und neu geprüft vom Backend). Speichervorgänge eines Datenblatts
 * laufen nacheinander (`scope`); die Antwort ersetzt den Cache nur, wenn kein neuerer Stand mehr wartet.
 * Vorschlag, Detail und Liste laden danach neu.
 */
export function useSaveExtraction(id: string) {
  const qc = useQueryClient()
  const mutationKey = ['datasheets', 'save-extraction', id] as const
  return useMutation({
    mutationKey,
    scope: { id: `datasheets:save-extraction:${id}` },
    mutationFn: (data: ExtractionData) => datasheetsApi.saveExtraction(id, data),
    meta: { errorTitle: 'Korrektur konnte nicht gespeichert werden' },
    onSuccess: (out) => {
      if (qc.isMutating({ mutationKey }) <= 1) qc.setQueryData(datasheetKeys.extraction(id), out)
      void qc.invalidateQueries({ queryKey: datasheetKeys.proposalAll(id) })
      void qc.invalidateQueries({ queryKey: datasheetKeys.detail(id) })
      void qc.invalidateQueries({ queryKey: datasheetKeys.list })
    },
    onError: () => {
      // optimistischer Stand verwerfen → Serverstand neu laden
      void qc.invalidateQueries({ queryKey: datasheetKeys.extraction(id) })
    },
  })
}

export function useDeleteDatasheet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, deleteFile = true }: { id: string; deleteFile?: boolean }) => datasheetsApi.remove(id, deleteFile),
    meta: { errorTitle: 'Datenblatt konnte nicht gelöscht werden' },
    onSuccess: (_out, { id }) => {
      qc.removeQueries({ queryKey: datasheetKeys.detail(id) })
      qc.removeQueries({ queryKey: datasheetKeys.extraction(id) })
      qc.removeQueries({ queryKey: datasheetKeys.proposalAll(id) })
      void qc.invalidateQueries({ queryKey: datasheetKeys.list })
    },
  })
}

export function useAiTest() {
  return useMutation({
    mutationFn: datasheetsApi.aiTest,
    meta: { silentError: true }, // das Ergebnis (auch ein Fehler) erscheint an der Karte
  })
}
