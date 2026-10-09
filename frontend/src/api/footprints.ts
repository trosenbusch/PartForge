/**
 * Footprint-Modul: Generator (Familien, Vorlagen, Live-Vorschau, STEP) und Footprint-Bibliothek (Registrierung).
 *
 *   const families = useFootprintFamilies()                      // GET /api/footprints/families (Aliase, Herstellerempfehlung)
 *   const preview = useGeneratorPreview(request, styleKey)        // POST /api/footprints/preview (with_svg=false)
 *   const blob = await footprintsApi.step(request)                // POST /api/footprints/step → STEP-Datei
 *   const list = useLibraryFootprints({})                         // GET /api/libraries/footprints (ohne Vorschaubilder)
 *   footprintsApi.thumbnail(name, entry.content_hash)             // GET …/footprints/{name}/thumbnail.svg?v=<content_hash>
 *   const plan = await footprintsApi.save(spec, { dryRun: true }) // PUT …?dry_run=true: Ziel, neu/unverändert, Verwendung
 *
 * Query-Keys beginnen mit „footprints“ (werden beim Bibliothekswechsel verworfen). Statische Daten (Familien,
 * Katalog-Miniaturen) tragen `meta.static` – das Job-Dock lädt sie nach Jobs nicht neu.
 */
import { keepPreviousData, queryOptions, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import type { FootprintRequest, FootprintSpec } from '@/lib/geometry'
import { api, ApiError } from './client'
import type { Filled, QueryOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

export type FootprintFamily = Filled<ResponseOf<'/api/footprints/families', 'get'>>[number]
export type FootprintParamSpec = FootprintFamily['params'][number]
export type FootprintParamKind = FootprintParamSpec['kind']
export type FootprintPreset = FootprintFamily['presets'][number]
export type FootprintDensity = FootprintRequest['density']
export type FootprintCheckIssue = Filled<ResponseOf<'/api/footprints/preview', 'post'>>['issues'][number]

/** Generator-Ergebnis; `spec` als Geometrie-Typ (Filled würde die STEP-Tupel zu Arrays machen) */
export type GeneratorPreview = Omit<Filled<ResponseOf<'/api/footprints/preview', 'post'>>, 'spec'> & {
  spec: FootprintSpec
}

export type LibraryFootprint = Filled<ResponseOf<'/api/libraries/footprints', 'get'>>[number]
export type LibraryFootprintQuery = QueryOf<'/api/libraries/footprints', 'get'>
export type LibraryFootprintDetail = Omit<Filled<ResponseOf<'/api/libraries/footprints/{name}', 'get'>>, 'spec'> & {
  spec: FootprintSpec | null
}
export type FootprintSaveResult = Filled<ResponseOf<'/api/libraries/footprints/{name}', 'put'>>
export type FootprintDeleteResult = Filled<ResponseOf<'/api/libraries/footprints/{name}', 'delete'>>

/** Vorschau mit gemessener Antwortzeit und der Anfrage, die sie erzeugt hat (STEP, Speichern) */
export interface TimedPreview extends GeneratorPreview {
  /** Dauer der Anfrage in ms */
  elapsed: number
  /** Anfrage, aus der diese Vorschau entstand – STEP-Datei und Dateiname passen so immer zusammen */
  request: FootprintRequest
}

// --------------------------------------------------------------------------- Keys

export const footprintKeys = {
  all: ['footprints'] as const,
  families: ['footprints', 'families'] as const,
  /** `styleKey` = Hausstil der Bibliothek (anderer Stil → andere Geometrie) */
  generator: (styleKey: string, req: FootprintRequest | null) => ['footprints', 'generator', styleKey, req] as const,
  catalogThumb: (family: string, preset: string, styleKey: string) => ['footprints', 'catalog', family, preset, styleKey] as const,
  library: ['footprints', 'library'] as const,
  libraryList: (query: LibraryFootprintQuery) => ['footprints', 'library', 'list', query] as const,
  libraryDetail: (name: string) => ['footprints', 'library', 'detail', name] as const,
  /** Vorschaubild je Inhalt (`content_hash`) – ein geänderter Footprint bekommt ein neues Bild */
  libraryThumb: (name: string, contentHash: string) => ['footprints', 'library', 'thumb', name, contentHash] as const,
  /** Probelauf des Speicherns (Ziel-Bibliothek, neu/unverändert) – unter „library“, damit Speichern ihn neu lädt */
  savePlan: (name: string, geometry: string | null, styleKey: string) => ['footprints', 'library', 'save-plan', name, geometry, styleKey] as const,
}

// --------------------------------------------------------------------------- Rohfunktionen

/** Footprint-Namen für den Pfad kodieren (Hausnamen enthalten Leerzeichen, Punkte …) */
export const encodeFootprintName = (name: string): string => encodeURIComponent(name)

export const footprintsApi = {
  families: (signal?: AbortSignal) => api.get<FootprintFamily[]>('/api/footprints/families', { signal }),
  /** Generator-Vorschau ohne SVG – Leinwand und Miniaturen zeichnen aus dem Spec */
  preview: (req: FootprintRequest, signal?: AbortSignal) =>
    api.post<GeneratorPreview>('/api/footprints/preview', { ...req, with_svg: false }, { signal }),
  /** STEP-Datei (AP214) der extrudierten 3D-Körper */
  step: (req: FootprintRequest) =>
    api.post<Blob>('/api/footprints/step', { ...req, with_3d: true }, { responseType: 'blob', timeoutMs: 60_000 }),
  library: (query: LibraryFootprintQuery, signal?: AbortSignal) =>
    api.get<LibraryFootprint[]>('/api/libraries/footprints', { query: { ...query }, signal }),
  /** Eintrag, Geometrie und 3D-Daten (ohne SVG – PreviewPanel zeichnet selbst) */
  libraryDetail: (name: string, signal?: AbortSignal) =>
    api.get<LibraryFootprintDetail>(`/api/libraries/footprints/${encodeFootprintName(name)}`, { signal, query: { svg: false } }),
  /**
   * Vorschaubild eines registrierten Footprints (SVG-Text, immer auf dunkler Leiterplatte). `contentHash` =
   * `content_hash` des Eintrags: als `?v=` speichert der Browser das Bild dauerhaft (`immutable`), ohne fragt er per
   * ETag nach (304).
   */
  thumbnail: (name: string, contentHash: string | null, signal?: AbortSignal) =>
    api.get<string>(`/api/libraries/footprints/${encodeFootprintName(name)}/thumbnail.svg`, {
      query: { theme: 'dark', v: contentHash || undefined },
      responseType: 'text',
      signal,
    }),
  libraryStep: (name: string) =>
    api.get<Blob>(`/api/libraries/footprints/${encodeFootprintName(name)}/step`, { responseType: 'blob', timeoutMs: 60_000 }),
  /**
   * Footprint speichern (registrieren + in die PcbLib schreiben) – direkt oder als Job. `dryRun`: nur prüfen
   * (Ziel-Bibliothek, neu, unverändert, Verwendung); nichts wird geschrieben.
   */
  save: (spec: FootprintSpec, opts: { dryRun?: boolean; signal?: AbortSignal } = {}) =>
    api.put<FootprintSaveResult>(
      `/api/libraries/footprints/${encodeFootprintName(spec.name)}`,
      { spec, source: 'generated' },
      { query: { dry_run: opts.dryRun || undefined }, timeoutMs: opts.dryRun ? 30_000 : 120_000, signal: opts.signal },
    ),
  /** Footprint löschen; `force` auch dann, wenn Bauteile ihn verwenden */
  remove: (name: string, force: boolean) =>
    api.delete<FootprintDeleteResult>(`/api/libraries/footprints/${encodeFootprintName(name)}`, {
      query: { force },
    }),
}

/**
 * Parameter, die das Backend in einem 400-Fehler ausdrücklich nennt (`detail: { message, params }`).
 * `null` = keine strukturierte Angabe (dann sucht der Aufrufer die Bezeichnungen im Text).
 */
export function errorParams(error: unknown): string[] | null {
  if (!(error instanceof ApiError) || !error.detail || typeof error.detail !== 'object') return null
  const params = (error.detail as { params?: unknown }).params
  return Array.isArray(params) ? params.filter((p): p is string => typeof p === 'string') : null
}

// --------------------------------------------------------------------------- Hooks: Generator

/** Alle Gehäusefamilien mit Parametern, Vorlagen, Aliasen und Herstellerempfehlung (statisch je Programmversion). */
export function useFootprintFamilies() {
  return useQuery({
    queryKey: footprintKeys.families,
    queryFn: ({ signal }) => footprintsApi.families(signal),
    staleTime: Infinity,
    gcTime: 60 * 60_000,
    meta: { static: true },
  })
}

/** Abfrage-Optionen der Generator-Vorschau (auch für `queryClient.fetchQuery`, z. B. vor dem Speichern) */
export function generatorPreviewOptions(req: FootprintRequest | null, styleKey: string) {
  return queryOptions({
    queryKey: footprintKeys.generator(styleKey, req),
    queryFn: async ({ signal }): Promise<TimedPreview> => {
      const request = req as FootprintRequest
      const started = performance.now()
      const data = await footprintsApi.preview(request, signal)
      return { ...data, elapsed: Math.round(performance.now() - started), request }
    },
    staleTime: 5 * 60_000,
    gcTime: 5 * 60_000,
    retry: false,
  })
}

/**
 * Live-Vorschau des Generators. Bei einer neuen Anfrage bleibt die letzte Vorschau sichtbar; die veraltete Anfrage
 * wird abgebrochen (das AbortSignal wird an fetch weitergereicht – React Query bricht unbenutzte Abfragen ab).
 */
export function useGeneratorPreview(req: FootprintRequest | null, styleKey: string) {
  return useQuery({
    ...generatorPreviewOptions(req, styleKey),
    enabled: Boolean(req),
    placeholderData: keepPreviousData,
  })
}

/** Miniatur einer Vorlage (Katalog): Vorschau ohne 3D und SVG, lange gecacht (je Hausstil) */
export function catalogThumbOptions(family: string, preset: string, styleKey: string) {
  return queryOptions({
    queryKey: footprintKeys.catalogThumb(family, preset, styleKey),
    queryFn: async ({ signal }) =>
      (await footprintsApi.preview({ family, params: { preset }, density: 'N', with_3d: false }, signal)).spec,
    staleTime: Infinity,
    gcTime: 30 * 60_000,
    retry: false,
    meta: { static: true },
  })
}

// --------------------------------------------------------------------------- Hooks: Bibliothek

/** Registrierte Footprints (ohne Vorschaubilder – die lädt jede Karte selbst, sobald sie sichtbar ist). */
export function useLibraryFootprints(query: LibraryFootprintQuery, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: footprintKeys.libraryList(query),
    queryFn: ({ signal }) => footprintsApi.library(query, signal),
    enabled: opts.enabled ?? true,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  })
}

/** Ein Footprint der Bibliothek mit Geometrie und 3D-Daten (`enabled` = Dialog offen). */
export function useLibraryFootprint(name: string | null, enabled = true) {
  return useQuery({
    queryKey: footprintKeys.libraryDetail(name ?? '–'),
    queryFn: ({ signal }) => footprintsApi.libraryDetail(name as string, signal),
    enabled: enabled && Boolean(name),
    staleTime: 60_000,
    retry: false,
  })
}

/**
 * Nach dem Speichern/Löschen: Bibliothek, Kennzahlen und die Bibliothekslisten des Bauteile-Moduls neu laden.
 * Vorschaubilder nicht – ihr Schlüssel trägt den `content_hash`, ein neuer Inhalt lädt ohnehin ein neues Bild.
 * `deleted`: Detail und Geometrie dieses Namens nur als veraltet markieren, nicht neu laden (der offene Dialog
 * schließt gerade – ein erneutes Holen ergäbe 404).
 */
export function invalidateFootprintLibrary(qc: QueryClient, deleted?: string | null) {
  const gone = deleted?.toLowerCase() ?? null
  const isGone = (key: readonly unknown[], kind: string, at: number) =>
    gone !== null && key[at - 1] === kind && typeof key[at] === 'string' && (key[at] as string).toLowerCase() === gone
  if (deleted) {
    void qc.invalidateQueries({ queryKey: footprintKeys.libraryDetail(deleted), refetchType: 'none' })
    void qc.invalidateQueries({ queryKey: ['parts', 'library', 'footprint', deleted], refetchType: 'none' })
  }
  void qc.invalidateQueries({
    queryKey: footprintKeys.library,
    predicate: (q) => q.queryKey[2] !== 'thumb' && !isGone(q.queryKey, 'detail', 3),
  })
  void qc.invalidateQueries({ queryKey: ['parts', 'library'], predicate: (q) => !isGone(q.queryKey, 'footprint', 3) })
  void qc.invalidateQueries({ queryKey: ['stats'] })
}

/** Footprint in die Bibliothek schreiben (direkt oder – bei langsamen Schreibvorgängen – als Job). */
export function useSaveFootprint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (spec: FootprintSpec) => footprintsApi.save(spec),
    // Fehler zeigt der Aufrufer selbst (503 „registriert, noch nicht geschrieben“, 409 Altium …)
    meta: { silentError: true },
    // Auch bei 503/409 registriert das Backend den Footprint (Status „ausstehend“) → immer neu laden
    onSettled: () => invalidateFootprintLibrary(qc),
  })
}

/**
 * Footprint aus Bibliothek und PcbLib löschen (direkt oder als Job). Nach einem direkten Löschen lädt das Detail des
 * Namens nicht neu (404); läuft es als Job, lädt der Job-Abschluss ohnehin alles neu.
 */
export function useDeleteFootprint() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, force }: { name: string; force: boolean }) => footprintsApi.remove(name, force),
    meta: { silentError: true },
    onSettled: (out, error, { name }) => {
      const gone = !error && Boolean(out?.result && (out.result.deleted.length || out.result.unregistered.length))
      invalidateFootprintLibrary(qc, gone ? name : null)
    },
  })
}
