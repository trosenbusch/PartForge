/**
 * Bauteile-API: Abfragen (Seiten, Filter, Sortierung), Anlegen/Ändern/Löschen (mit Rückgängig), Massenbearbeitung
 * (Teilenummern oder alle Treffer von Suche + Filtern), Prüfen, Smart-Eingabe, Vorlagen-Vorschau, Verlauf,
 * gespeicherte Ansichten, Tabellen-Import (Probelauf je Zeile, strenger Modus) und -Export sowie die
 * Bibliotheksdaten, die das Bauteile-Modul braucht (Symbol-/Footprint-Listen, -Geometrie, Vorschaubilder).
 *
 *   const page = await partsApi.query('Resistors', { search: '10k', filters, sort, offset: 0, limit: 100 })
 *   const { part, warnings } = await partsApi.update('Resistors', 'RC0603FR-0710KL', { Tolerance: '1%' })
 *   const { count } = await partsApi.count('Resistors', { search: '10k', filters })      // „Alle 12 Treffer“
 *   await partsApi.remove('Resistors', { search: '10k', filters, expectedCount: count })  // 409 selection_changed
 *   await partsApi.restore('Resistors', deleted.part_numbers)                             // Rückgängig
 *   await partsApi.restoreUpdates('Resistors', changed.audit_ids)       // Rückgängig einer Massenänderung
 *
 * Query-Keys beginnen mit `parts` (bzw. `categories`/`stats` für die Zähler) – beim Bibliothekswechsel und nach
 * jedem beendeten Job werden sie automatisch verworfen bzw. neu geladen. Die Tabelle hängt an
 * `partsKeys.revision(table)`: jede Invalidierung von `['parts', table]` lädt die sichtbaren Zeilen neu.
 */
import { keepPreviousData, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { FootprintSpec, SymbolSpec } from '@/lib/geometry'
import { ApiError, api } from './client'
import { libraryKeys } from './library'
import type { Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

/** Eine Bauteilzeile: Spaltenname → Text (alle Werte sind Text, leer = null) */
export type PartRow = Record<string, string | null>
export type PartsPage = Omit<Filled<ResponseOf<'/api/parts/{table}/query', 'post'>>, 'rows'> & { rows: PartRow[] }
export type PartQueryBody = RequestBodyOf<'/api/parts/{table}/query', 'post'>
export type PartFilter = NonNullable<PartQueryBody['filters']>[number]
export type FilterOp = PartFilter['op']
export type SortSpec = NonNullable<PartQueryBody['sort']>[number]
export type PartWriteOut = Filled<ResponseOf<'/api/parts/{table}', 'post'>>
export type PartValidation = Filled<ResponseOf<'/api/parts/{table}/validate', 'post'>>
export type PartConflict = NonNullable<PartValidation['conflict']>
export type SmartFillResult = Filled<ResponseOf<'/api/parts/{table}/smart-fill', 'post'>>
export type BulkUpdateResult = Filled<ResponseOf<'/api/parts/{table}/bulk-update', 'post'>>
export type DeletePartsResult = Filled<ResponseOf<'/api/parts/{table}/delete', 'post'>>
export type PartsCount = Filled<ResponseOf<'/api/parts/{table}/count', 'post'>>
export type RestorePartsResult = Filled<ResponseOf<'/api/parts/{table}/restore', 'post'>>
export type RestoreUpdatesResult = Filled<ResponseOf<'/api/parts/{table}/restore-updates', 'post'>>
export type RenderTemplateResult = Filled<ResponseOf<'/api/parts/{table}/render-template', 'post'>>
export type RegenerateResult = Filled<ResponseOf<'/api/parts/{table}/regenerate-texts', 'post'>>
export type PartHistoryEntry = Filled<ResponseOf<'/api/parts/{table}/{pn}/history', 'get'>>[number]
export type HistoryAction = PartHistoryEntry['action']
export type DistinctValue = Filled<ResponseOf<'/api/distinct/{table}', 'get'>>[number]
export type SavedView = Filled<ResponseOf<'/api/views', 'get'>>[number]
export type SavedViewInput = RequestBodyOf<'/api/views', 'post'>
export type SavedViewPatch = RequestBodyOf<'/api/views/{view_id}', 'patch'>
export type ImportPreview = Filled<ResponseOf<'/api/import/preview', 'post'>>
export type MappingItem = ImportPreview['mapping'][number]
export type ImportSample = ImportPreview['samples'][number]
/** Probelauf einer Zeile: create · update · unchanged · skip · reject (mit Gründen) */
export type ImportRowStatus = ImportPreview['row_status'][number]
export type ImportRowStatusName = ImportRowStatus['status']
export type ImportCheck = NonNullable<ImportPreview['check']>
export type ImportRunInput = RequestBodyOf<'/api/import/run', 'post'>
export type ImportMode = ImportRunInput['mode']
export type ImportHeaderRow = number | 'auto' | null
export type SymbolEntry = Filled<ResponseOf<'/api/libraries/symbols', 'get'>>[number]
export type FootprintEntry = Filled<ResponseOf<'/api/libraries/footprints', 'get'>>[number]
/** `spec` als Geometrie-Typ (Filled würde die STEP-Tupel zu Arrays machen – die Geometrie-Typen erlauben beides) */
export type SymbolDetail = Omit<Filled<ResponseOf<'/api/libraries/symbols/{name}', 'get'>>, 'spec'> & { spec: SymbolSpec | null }
export type FootprintDetail = Omit<Filled<ResponseOf<'/api/libraries/footprints/{name}', 'get'>>, 'spec'> & {
  spec: FootprintSpec | null
}
export type DecodeResult = Filled<ResponseOf<'/api/series/decode', 'post'>>
export type DecodedPart = NonNullable<DecodeResult['best']>
export type StandardSymbolMatch = Filled<ResponseOf<'/api/symbols/standard-for', 'post'>>

/** Ergebnis des Import-Jobs (`job.result`, partforge/importers/spreadsheet.py `run_import`) */
export interface ImportResult {
  /** `ok` ohne abgelehnte Zeilen · `partial` = trotz Fehlern etwas übernommen · `failed` = nichts übernommen */
  outcome: 'ok' | 'partial' | 'failed'
  /**
   * Schlussmeldung des Jobs (= `job.message`): „Import fertig: 120 neu, 4 aktualisiert, 2 abgelehnt“ bzw. „Import
   * fehlgeschlagen – nichts übernommen: 2 abgelehnt“
   */
  message?: string
  /** Nicht lesbare Werte haben die Zeile abgelehnt (statt nur zu warnen) */
  strict: boolean
  table: string
  file: string
  rows: number
  created: number
  updated: number
  unchanged: number
  skipped: number
  error_count: number
  /** Abgelehnte Zeilen (höchstens 200): Teilenummer bzw. „Zeile n“ → Grund */
  errors: Record<string, string>
  warnings: Record<string, string[]>
  /** Neu angelegte Teilenummern (höchstens 500) */
  created_part_numbers: string[]
  backup: string | null
}

/** Ergebnis des Export-Jobs (`job.result`) bzw. von `POST /api/export/{table}` */
export interface ExportFileResult {
  path: string
  rel_path: string
  file_name: string
  rows: number
}

export type ExportFormat = 'xlsx' | 'csv'

export interface ExportOptions {
  format: ExportFormat
  /** Nur diese Bauteile (leer/undefiniert = alle Treffer der Abfrage) */
  partNumbers?: string[]
  /** Spalten in dieser Reihenfolge (leer = alle) */
  columns?: string[]
  search?: string
  filters?: PartFilter[]
  sort?: SortSpec[]
}

/**
 * Welche Bauteile eine Massenaktion trifft: ausdrücklich gewählte Teilenummern – oder **alle Treffer** von Suche und
 * Filtern. Dann mit der bestätigten Anzahl (`expectedCount` aus `partsApi.count`): weicht die Auswahl inzwischen ab,
 * lehnt das Backend mit 409 „selection_changed“ ab ({@link selectionChanged}).
 */
export type PartSelection =
  | { partNumbers: string[] }
  | { search: string; filters: PartFilter[]; expectedCount: number }

/** Optionen des Import-Probelaufs (gleiche Bedeutung wie beim Import selbst) */
export interface ImportCheckOptions {
  /** Aktuelle Zuordnung (`null` = Vorschlag des Backends) */
  mapping: MappingItem[] | null
  mode: ImportMode
  /** Feste Werte für alle Zeilen */
  defaults: Record<string, string>
  allowIncomplete: boolean
  /** Nicht lesbare Werte (keine Zahl, falsche Einheit …) lehnen die Zeile ab */
  strict: boolean
  /** So viele Zeilen prüfen (Standard des Backends: 200) */
  checkRows?: number
}

/** Spalte „Teilenummer“ (Primärschlüssel jeder Kategorietabelle) */
export const PART_NUMBER = 'Part Number'

// --------------------------------------------------------------------------- Fehler

/** Fachliches „nicht gefunden“ (z. B. Bauteil gelöscht, Symbol nicht registriert) */
export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}

/**
 * Validierungsfehler je Spalte aus einer Fehlerantwort (400 `{ message, errors: { Spalte: Text } }`).
 * Leer, wenn die Antwort keine Feldfehler enthält.
 */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !error.detail || typeof error.detail !== 'object') return {}
  const errors = (error.detail as { errors?: unknown }).errors
  if (!errors || typeof errors !== 'object') return {}
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(errors as Record<string, unknown>)) {
    if (typeof value === 'string') out[key] = value
  }
  return out
}

/** 409 „selection_changed“: die Treffer haben sich seit der Bestätigung geändert (`count` = jetzt, `expected` = bestätigt) */
export interface SelectionChanged {
  message: string
  count: number
  expected: number
}

export function selectionChanged(error: unknown): SelectionChanged | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.detail || typeof error.detail !== 'object') return null
  const d = error.detail as { code?: unknown; message?: unknown; count?: unknown; expected?: unknown }
  if (d.code !== 'selection_changed') return null
  return {
    message: typeof d.message === 'string' ? d.message : error.message,
    count: typeof d.count === 'number' ? d.count : 0,
    expected: typeof d.expected === 'number' ? d.expected : 0,
  }
}

// --------------------------------------------------------------------------- Query-Keys

export const partsKeys = {
  all: ['parts'] as const,
  table: (table: string) => ['parts', table] as const,
  /** Zähler, an dem die Tabelle hängt (jede Invalidierung von `table(…)` lädt die Zeilen neu) */
  revision: (table: string) => ['parts', table, 'revision'] as const,
  detail: (table: string, pn: string) => ['parts', table, 'detail', pn] as const,
  history: (table: string, pn: string) => ['parts', table, 'history', pn] as const,
  distinct: (table: string, column: string) => ['parts', table, 'distinct', column] as const,
  views: (table: string | null) => ['parts', 'views', table ?? '*'] as const,
  viewsAll: ['parts', 'views'] as const,
  symbols: ['parts', 'library', 'symbols'] as const,
  footprints: ['parts', 'library', 'footprints'] as const,
  symbol: (name: string) => ['parts', 'library', 'symbol', name] as const,
  footprint: (name: string) => ['parts', 'library', 'footprint', name] as const,
  standardSymbol: (table: string, values: Record<string, unknown>) => ['parts', 'standard-symbol', table, values] as const,
}

// --------------------------------------------------------------------------- Funktionen

const enc = (value: string) => encodeURIComponent(value)
const tablePath = (table: string) => `/api/parts/${enc(table)}`
const partPath = (table: string, pn: string) => `${tablePath(table)}/${enc(pn)}`

/** Auswahl → Body der Massenaktionen (nie Teilenummern und Filter zugleich – das lehnt das Backend ab) */
function selectionBody(sel: PartSelection) {
  if ('partNumbers' in sel) return { part_numbers: sel.partNumbers }
  return { search: sel.search.trim() || null, filters: sel.filters, expected_count: sel.expectedCount }
}

/**
 * CSV immer Excel-sicher: Werte, die mit =, +, @ (bzw. - ohne Ziffer dahinter) beginnen, schützt das Backend mit einem
 * vorangestellten ' – sonst rechnet Excel Formeln aus Herstellerangaben oder Datenblättern aus (Formel-Injektion). Der
 * Tabellen-Import entfernt das ' wieder. XLSX speichert Zellen ohnehin als Text.
 */
const excelSafe = (format: ExportFormat) => format === 'csv'

function exportQuery(opts: ExportOptions) {
  return {
    format: opts.format,
    pns: opts.partNumbers?.length ? opts.partNumbers : undefined,
    columns: opts.columns?.length ? opts.columns : undefined,
    search: opts.search || undefined,
    filters: opts.filters?.length ? JSON.stringify(opts.filters) : undefined,
    sort: opts.sort?.length ? JSON.stringify(opts.sort) : undefined,
    excel_safe: excelSafe(opts.format) || undefined,
  }
}

export const partsApi = {
  /** Seite einer Kategorie (Suche, Filter, Sortierung im Backend – Werte mit Einheiten werden verglichen) */
  query: (table: string, body: PartQueryBody, signal?: AbortSignal) =>
    api.post<PartsPage>(`${tablePath(table)}/query`, body, { signal }),
  get: (table: string, pn: string, signal?: AbortSignal) => api.get<PartRow>(partPath(table, pn), { signal }),
  create: (table: string, values: Record<string, unknown>, allowIncomplete = false) =>
    api.post<PartWriteOut>(tablePath(table), { values, allow_incomplete: allowIncomplete }),
  update: (table: string, pn: string, values: Record<string, unknown>) =>
    api.patch<PartWriteOut>(partPath(table, pn), { values, allow_incomplete: false }),
  /** Löschen (Teilenummern oder alle Treffer); die Antwort nennt die gelöschten Teilenummern für `restore` */
  remove: (table: string, selection: PartSelection) =>
    api.post<DeletePartsResult>(`${tablePath(table)}/delete`, selectionBody(selection), { timeoutMs: 120_000 }),
  /** Gelöschte Bauteile aus der Änderungshistorie zurückholen (Rückgängig) */
  restore: (table: string, partNumbers: string[]) =>
    api.post<RestorePartsResult>(`${tablePath(table)}/restore`, { part_numbers: partNumbers }, { timeoutMs: 120_000 }),
  /** Dieselben Werte für viele Bauteile; die Antwort nennt `audit_ids` für `restoreUpdates` (Rückgängig) */
  bulkUpdate: (table: string, selection: PartSelection, values: Record<string, unknown>) =>
    api.post<BulkUpdateResult>(`${tablePath(table)}/bulk-update`, { ...selectionBody(selection), values }, { timeoutMs: 120_000 }),
  /**
   * Massenänderung bzw. „Texte neu erzeugen“ zurücknehmen (`audit_ids` aus deren Antwort): alte Werte aus der
   * Änderungshistorie, je Bauteil ganz oder gar nicht – seither erneut geänderte Bauteile bleiben (`conflicts`)
   */
  restoreUpdates: (table: string, auditIds: number[]) =>
    api.post<RestoreUpdatesResult>(`${tablePath(table)}/restore-updates`, { audit_ids: auditIds }, { timeoutMs: 120_000 }),
  /** Wie viele Bauteile Suche + Filter treffen (Bestätigung einer Massenaktion; `sample` = erste Teilenummern) */
  count: (table: string, body: { search?: string | null; filters?: PartFilter[]; sample?: number }, signal?: AbortSignal) =>
    api.post<PartsCount>(
      `${tablePath(table)}/count`,
      { search: body.search?.trim() || null, filters: body.filters ?? [], sample: body.sample ?? 20 },
      { signal },
    ),
  duplicate: (table: string, pn: string, newPartNumber: string) =>
    api.post<PartWriteOut>(`${partPath(table, pn)}/duplicate`, { new_part_number: newPartNumber }),
  validate: (
    table: string,
    values: Record<string, unknown>,
    opts: { partNumber?: string | null; allowIncomplete?: boolean; signal?: AbortSignal } = {},
  ) =>
    api.post<PartValidation>(
      `${tablePath(table)}/validate`,
      { values, part_number: opts.partNumber ?? null, allow_incomplete: opts.allowIncomplete ?? false },
      { signal: opts.signal },
    ),
  /** Wert, Kommentar und Beschreibung, wie die gespeicherten Vorlagen sie für diese Werte erzeugen */
  renderTemplates: (table: string, values: Record<string, unknown>, signal?: AbortSignal) =>
    api.post<Record<string, string>>(`${tablePath(table)}/render-templates`, { values }, { signal }),
  /** Beliebige Vorlage für diese Werte rendern (Werte normalisiert wie beim Speichern) – `unknown` = Platzhalter ohne Feld */
  renderTemplate: (table: string, template: string, values: Record<string, unknown>, signal?: AbortSignal) =>
    api.post<RenderTemplateResult>(`${tablePath(table)}/render-template`, { template, values }, { signal }),
  smartFill: (table: string, text: string, signal?: AbortSignal) =>
    api.post<SmartFillResult>(`${tablePath(table)}/smart-fill`, { text }, { signal }),
  regenerateTexts: (table: string, partNumbers: string[] | null) =>
    api.post<RegenerateResult>(`${tablePath(table)}/regenerate-texts`, {
      part_numbers: partNumbers,
      columns: ['Value', 'Comment', 'Description'],
    }),
  history: (table: string, pn: string, signal?: AbortSignal) =>
    api.get<PartHistoryEntry[]>(`${partPath(table, pn)}/history`, { signal }),
  distinct: (table: string, column: string, signal?: AbortSignal) =>
    api.get<DistinctValue[]>(`/api/distinct/${enc(table)}`, { query: { column, limit: 200 }, signal }),

  // --- gespeicherte Ansichten
  views: (table: string | null, signal?: AbortSignal) =>
    api.get<SavedView[]>('/api/views', { query: { table: table ?? undefined }, signal }),
  createView: (view: SavedViewInput) => api.post<SavedView>('/api/views', view),
  updateView: (id: number, patch: SavedViewPatch) => api.patch<SavedView>(`/api/views/${id}`, patch),
  deleteView: (id: number) => api.delete<{ deleted: boolean }>(`/api/views/${id}`),

  // --- Tabellen-Import
  importPreview: (file: File, table: string | null, headerRow: ImportHeaderRow = 'auto', sheet?: string | null) => {
    const form = new FormData()
    form.append('file', file)
    if (table) form.append('table', table)
    if (sheet) form.append('sheet', sheet)
    form.append('header_row', headerRow === null ? '0' : String(headerRow))
    return api.upload<ImportPreview>('/api/import/preview', form)
  },
  /**
   * Hochgeladene Datei erneut lesen (anderes Blatt, andere Kopfzeile, andere Kategorie). Mit `check` zusätzlich der
   * Probelauf je Zeile (`row_status`, `check`) für Zuordnung, Modus, feste Werte, Entwurf und strengen Modus.
   */
  importRepreview: (
    token: string,
    opts: { table: string | null; sheet?: string | null; headerRow: ImportHeaderRow; check?: ImportCheckOptions },
    signal?: AbortSignal,
  ) =>
    api.post<ImportPreview>(
      `/api/import/preview/${enc(token)}`,
      {
        table: opts.table,
        sheet: opts.sheet ?? null,
        header_row: opts.headerRow,
        ...(opts.check
          ? {
              mapping: opts.check.mapping,
              mode: opts.check.mode,
              defaults: opts.check.defaults,
              allow_incomplete: opts.check.allowIncomplete,
              strict: opts.check.strict,
              check_rows: opts.check.checkRows ?? 200,
            }
          : {}),
      },
      { signal, timeoutMs: 120_000 },
    ),
  importRun: (input: ImportRunInput) => api.post<{ job: Job<ImportResult> }>('/api/import/run', input),

  // --- Export
  /**
   * Adresse des Downloads (`GET /api/export/{table}`) – zum Prüfen der Länge vor `exportFile`. **Ohne** Token: `exportFile`
   * sendet ihn als Header, nicht in der Adresse.
   */
  exportUrl: (table: string, opts: ExportOptions) => api.url(`/api/export/${enc(table)}`, exportQuery(opts), false),
  /** Exportdatei als Blob (XLSX bzw. CSV mit BOM) – zum Speichern über `@/lib/download` */
  exportFile: (table: string, opts: ExportOptions) =>
    api.get<Blob>(`/api/export/${enc(table)}`, { query: exportQuery(opts), responseType: 'blob', timeoutMs: 180_000 }),
  /** Export in den Ordner „Exports“ der Bibliothek als Hintergrundjob (sehr große Auswahl) */
  exportJob: (table: string, opts: ExportOptions) =>
    api.post<{ job: Job<ExportFileResult> }>(`/api/export/${enc(table)}/job`, {
      format: opts.format,
      part_numbers: opts.partNumbers?.length ? opts.partNumbers : null,
      columns: opts.columns?.length ? opts.columns : null,
      search: opts.search || null,
      filters: opts.filters ?? [],
      sort: opts.sort ?? [],
      delimiter: ';',
      excel_safe: excelSafe(opts.format),
    }),

  // --- Bibliothek (Symbole/Footprints der Registrierung)
  symbols: (signal?: AbortSignal) => api.get<SymbolEntry[]>('/api/libraries/symbols', { signal }),
  footprints: (signal?: AbortSignal) => api.get<FootprintEntry[]>('/api/libraries/footprints', { signal }),
  /** Geometrie eines Symbols (ohne SVG – die Leinwand zeichnet selbst) */
  symbol: (name: string, signal?: AbortSignal) =>
    api.get<SymbolDetail>(`/api/libraries/symbols/${enc(name)}`, { query: { svg: false }, signal }),
  /** Geometrie und 3D-Daten eines Footprints (ohne SVG) */
  footprint: (name: string, signal?: AbortSignal) =>
    api.get<FootprintDetail>(`/api/libraries/footprints/${enc(name)}`, { query: { svg: false }, signal }),
  /** Hersteller-Teilenummer mit den Serienvorlagen lesen */
  decode: (mpn: string, signal?: AbortSignal) => api.post<DecodeResult>('/api/series/decode', { mpn }, { signal }),
  /** Passendes Standardsymbol für Kategorie + Werte */
  standardSymbol: (table: string, values: Record<string, unknown>, signal?: AbortSignal) =>
    api.post<StandardSymbolMatch>('/api/symbols/standard-for', { table, values, pins: [], pads: [] }, { signal }),
}

// --------------------------------------------------------------------------- Hilfen

/**
 * Nach einer Änderung an Bauteilen: Tabelle, Details und Verlauf der Kategorie sowie die Zähler (Kategoriebaum,
 * Übersicht) neu laden.
 */
export function invalidateParts(qc: QueryClient, table: string, opts: { counts?: boolean; skipPns?: string[] } = {}): void {
  // Details/Verlauf gelöschter Bauteile nicht neu laden (das Panel schließt gerade – sonst 404)
  const skip = new Set((opts.skipPns ?? []).map((pn) => pn.toLowerCase()))
  void qc.invalidateQueries({
    queryKey: partsKeys.table(table),
    predicate: (q) => {
      const [, , kind, pn] = q.queryKey
      return !((kind === 'detail' || kind === 'history') && typeof pn === 'string' && skip.has(pn.toLowerCase()))
    },
  })
  if (opts.counts ?? true) {
    void qc.invalidateQueries({ queryKey: libraryKeys.categories })
    void qc.invalidateQueries({ queryKey: libraryKeys.stats })
  }
}

// --------------------------------------------------------------------------- Hooks

/** Ein Bauteil (frisch vom Server, z. B. für das Detailpanel). `initial` = Zeile aus der Tabelle. */
export function usePart(table: string | undefined, pn: string | null | undefined, initial?: PartRow | null) {
  return useQuery({
    queryKey: partsKeys.detail(table ?? '', pn ?? ''),
    queryFn: ({ signal }) => partsApi.get(table as string, pn as string, signal),
    enabled: Boolean(table && pn),
    initialData: initial ?? undefined,
    initialDataUpdatedAt: 0, // Tabellenzeile sofort zeigen, trotzdem frisch laden
    staleTime: 5_000,
  })
}

/** Änderungsverlauf eines Bauteils (neueste zuerst) */
export function usePartHistory(table: string | undefined, pn: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: partsKeys.history(table ?? '', pn ?? ''),
    queryFn: ({ signal }) => partsApi.history(table as string, pn as string, signal),
    enabled: Boolean(table && pn) && enabled,
    placeholderData: keepPreviousData,
  })
}

/** Vorhandene Werte einer Spalte mit Häufigkeit (Filter, Vorschläge) */
export function useDistinctValues(table: string | undefined, column: string | null, enabled = true) {
  return useQuery({
    queryKey: partsKeys.distinct(table ?? '', column ?? ''),
    queryFn: ({ signal }) => partsApi.distinct(table as string, column as string, signal),
    enabled: Boolean(table && column) && enabled,
    staleTime: 30_000,
  })
}

/** Gespeicherte Ansichten einer Kategorie (inkl. kategorieübergreifender Ansichten) */
export function useSavedViews(table: string | null) {
  return useQuery({
    queryKey: partsKeys.views(table),
    queryFn: ({ signal }) => partsApi.views(table, signal),
    staleTime: 30_000,
  })
}

const libraryQueryOptions = { staleTime: 60_000, retry: false } as const

/** Registrierte Symbole (Namen, Status, Verwendung – ohne Vorschaubilder) */
export function useLibrarySymbols(enabled = true) {
  return useQuery({
    queryKey: partsKeys.symbols,
    queryFn: ({ signal }) => partsApi.symbols(signal),
    enabled,
    ...libraryQueryOptions,
  })
}

/** Registrierte Footprints (Namen, Familie, Status – ohne Vorschaubilder) */
export function useLibraryFootprints(enabled = true) {
  return useQuery({
    queryKey: partsKeys.footprints,
    queryFn: ({ signal }) => partsApi.footprints(signal),
    enabled,
    ...libraryQueryOptions,
  })
}

/**
 * Ist der Name in der Liste registriert? `undefined` = Liste noch nicht geladen. Geprüft wird vor dem Laden der
 * Geometrie – so entstehen für nicht registrierte Verweise keine 404-Anfragen (und keine Konsolenfehler).
 */
function isRegistered(list: { name: string }[] | undefined, name: string | null | undefined): boolean | undefined {
  if (!name) return false
  if (!list) return undefined
  const wanted = name.toLowerCase()
  return list.some((entry) => entry.name.toLowerCase() === wanted)
}

/** Eintrag der Liste zu einem Namen (Groß-/Kleinschreibung egal) */
export function findEntry<T extends { name: string }>(list: readonly T[] | undefined, name: string | null | undefined): T | null {
  if (!name || !list) return null
  const wanted = name.toLowerCase()
  return list.find((e) => e.name.toLowerCase() === wanted) ?? null
}

export interface LibraryItemState<T> {
  data: T | undefined
  isFetching: boolean
  error: unknown
  /** Name ist nicht in der Bibliothek registriert */
  notRegistered: boolean
}

/** Symbol aus der Bibliothek (Geometrie für die Vorschau) */
export function useLibrarySymbol(name: string | null | undefined): LibraryItemState<SymbolDetail> {
  const list = useLibrarySymbols(Boolean(name))
  const known = isRegistered(list.data, name)
  const q = useQuery({
    queryKey: partsKeys.symbol(name ?? ''),
    queryFn: ({ signal }) => partsApi.symbol(name as string, signal),
    enabled: known === true,
    ...libraryQueryOptions,
  })
  return {
    data: known ? q.data : undefined,
    isFetching: q.isFetching || (Boolean(name) && list.isPending),
    error: q.error ?? list.error ?? null,
    notRegistered: known === false && Boolean(name),
  }
}

/** Footprint aus der Bibliothek (Geometrie + 3D-Körper für die Vorschau) */
export function useLibraryFootprint(name: string | null | undefined): LibraryItemState<FootprintDetail> {
  const list = useLibraryFootprints(Boolean(name))
  const known = isRegistered(list.data, name)
  const q = useQuery({
    queryKey: partsKeys.footprint(name ?? ''),
    queryFn: ({ signal }) => partsApi.footprint(name as string, signal),
    enabled: known === true,
    ...libraryQueryOptions,
  })
  return {
    data: known ? q.data : undefined,
    isFetching: q.isFetching || (Boolean(name) && list.isPending),
    error: q.error ?? list.error ?? null,
    notRegistered: known === false && Boolean(name),
  }
}

/**
 * Vorschau-Geometrie für Tabellenzellen (außerhalb von Hooks): Liste aus dem Cache bzw. laden, nur registrierte
 * Namen abfragen. `null` = nicht registriert.
 */
export async function loadLibraryPreview(
  qc: QueryClient,
  kind: 'symbol' | 'footprint',
  name: string,
  signal: AbortSignal,
): Promise<SymbolDetail | FootprintDetail | null> {
  try {
    const list =
      kind === 'symbol'
        ? await qc.fetchQuery({ queryKey: partsKeys.symbols, queryFn: ({ signal: s }) => partsApi.symbols(s), staleTime: 60_000 })
        : await qc.fetchQuery({ queryKey: partsKeys.footprints, queryFn: ({ signal: s }) => partsApi.footprints(s), staleTime: 60_000 })
    if (!isRegistered(list, name)) return null
    return kind === 'symbol'
      ? await qc.fetchQuery({ queryKey: partsKeys.symbol(name), queryFn: ({ signal: s }) => partsApi.symbol(name, s ?? signal), staleTime: 60_000 })
      : await qc.fetchQuery({ queryKey: partsKeys.footprint(name), queryFn: ({ signal: s }) => partsApi.footprint(name, s ?? signal), staleTime: 60_000 })
  } catch (err) {
    if (isNotFound(err)) return null
    throw err
  }
}

/** Bauteil, das ein Symbol bzw. einen Footprint verwendet */
export interface PartUsageHit {
  table: string
  partNumber: string
  description: string | null
  /** Spalte des Verweises (z. B. „Footprint Ref 2“) */
  column: string
}

/** Höchstens so viele Treffer je Kategorie und Spalte */
const USAGE_LIMIT = 50

/**
 * Bauteile, die einen Bibliotheksnamen verwenden (`Library Ref` bzw. `Footprint Ref`, `Footprint Ref 2` …): je Kategorie
 * mit einer der Spalten eine Abfrage – erst auf Wunsch (`enabled`). Kategorien ohne Bauteile oder ohne die Spalten
 * werden übersprungen.
 */
export function usePartsUsing(
  columns: readonly string[],
  name: string | null,
  categories: readonly { table: string; part_count?: number | null; fields: readonly { column: string }[] }[] | undefined,
  enabled: boolean,
) {
  const targets = (categories ?? [])
    .filter((c) => (c.part_count ?? 0) > 0)
    .flatMap((c) => c.fields.filter((f) => columns.includes(f.column)).map((f) => ({ table: c.table, column: f.column })))
  return useQuery({
    queryKey: ['parts', 'using', columns.join('|'), name ?? '', targets.map((t) => `${t.table}:${t.column}`).join(',')],
    enabled: enabled && Boolean(name) && targets.length > 0,
    staleTime: 30_000,
    queryFn: async ({ signal }): Promise<PartUsageHit[]> => {
      const pages = await Promise.allSettled(
        targets.map((t) =>
          partsApi.query(t.table, { filters: [{ column: t.column, op: 'eq', value: name }], limit: USAGE_LIMIT, offset: 0, sort: [] }, signal),
        ),
      )
      const hits: PartUsageHit[] = []
      const seen = new Set<string>()
      pages.forEach((p, i) => {
        if (p.status !== 'fulfilled') return
        for (const row of p.value.rows) {
          const pn = row[PART_NUMBER]
          if (!pn) continue
          const key = `${targets[i].table}|${pn}`
          if (seen.has(key)) continue
          seen.add(key)
          hits.push({ table: targets[i].table, partNumber: pn, description: row.Description || null, column: targets[i].column })
        }
      })
      return hits
    },
  })
}

/** Zugriff auf den Query-Client für Bauteil-Mutationen (Invalidierung) */
export function usePartsInvalidation() {
  const qc = useQueryClient()
  return (table: string, opts?: { counts?: boolean }) => invalidateParts(qc, table, opts)
}
