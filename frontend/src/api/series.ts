import { useI18n } from '@/lib/i18n'
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api } from './client'
import type { Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

export type SeriesTemplateSummary = Filled<ResponseOf<'/api/series/templates', 'get'>>[number]
/** Beispiel-Teilenummer einer Vorlagenkarte (vom Backend vorberechnet: Zerlegung, Beschreibung, Pflichtfeldprüfung) */
export type TemplateExample = NonNullable<SeriesTemplateSummary['example']>
/** Abschnitt einer Teilenummer („0603“ = Baugröße, „10K0“ = Wert …) */
export type MpnSegment = TemplateExample['segments'][number]
export type MpnSegmentKind = MpnSegment['kind']
/** Pflichtfeld der Kategorie (Spalte + deutsche Bezeichnung) */
export type RequiredField = TemplateExample['missing_fields'][number]
/** Wie die Vorlage festlegt, welche Bauteile es gibt */
export type TemplateMode = SeriesTemplateSummary['mode']

/** Vorlage mit Codetabellen, Baugrößen, Regeln, Katalog (Matrix nur mit `full`) */
export type SeriesTemplate = Filled<ResponseOf<'/api/series/templates/{template_id}', 'get'>>
export type TemplateVariable = SeriesTemplate['variables'][number]
export type TemplateOption = TemplateVariable['options'][number]
export type TemplateSize = SeriesTemplate['sizes'][number]
export type TemplateRule = SeriesTemplate['rules'][number]
export type AvailabilityCell = SeriesTemplate['availability'][number]
export type CatalogEntry = SeriesTemplate['catalog'][number]
export type TemplateJumper = NonNullable<SeriesTemplate['jumper']>
export type TemplateSource = SeriesTemplate['sources'][number]
export type ValueFormat = NonNullable<TemplateVariable['format']>
export type ValueStyle = ValueFormat['style']

export type SeriesRequest = RequestBodyOf<'/api/series/preview', 'post'>
export type SeriesPreview = Filled<ResponseOf<'/api/series/preview', 'post'>>
export type PreviewRow = SeriesPreview['rows'][number]
export type RowStatus = PreviewRow['status']
export type SeriesFootprintRef = SeriesPreview['footprints'][number]
export type SeriesSymbolRef = NonNullable<SeriesPreview['symbol']>

export type SeriesCommitBody = RequestBodyOf<'/api/series/commit', 'post'>
export type CommitMode = SeriesCommitBody['mode']
type SeriesJobOut = Filled<ResponseOf<'/api/series/commit', 'post'>>

/**
 * Symbol bzw. Footprint der Serie, das **nicht** in seine Bibliotheksdatei geschrieben wurde (`result.library_problems`,
 * partforge/domain/series.py `LibraryProblem`): `status: 'error'` = Schreiben fehlgeschlagen (z. B. Datei gesperrt) –
 * die Zeilen damit sind nicht angelegt (`errors`/`error_details`); `'pending'` = vorgemerkt, weil kein
 * Bibliotheks-Writer bereit war – die Bauteile sind angelegt, Altium findet sie erst nach dem Synchronisieren.
 */
export interface SeriesLibraryProblem {
  /** fehlt bei älteren Backends – dann aus der Dateiendung */
  kind?: 'symbol' | 'footprint'
  name: string
  /** Bibliotheksdatei relativ zur Bibliothek (`Footprints\PF_CHIP.PcbLib`) */
  library?: string | null
  /** `error`/`missing`: Bauteile damit sind nicht angelegt; `pending`: angelegt, die Datei folgt beim Synchronisieren */
  status: 'error' | 'pending' | 'missing' | (string & {})
  message?: string | null
  /** Zeilen der Serie mit diesem Symbol/Footprint */
  parts?: number
}

/** Ergebnis des Serien-Jobs (`job.result`, partforge/domain/series.py `SeriesCommitResult`) */
export type SeriesCommitResult = NonNullable<SeriesJobOut['job']['result']> & {
  /** nicht geschriebene Symbole/Footprints (fehlt bei älteren Backends) */
  library_problems?: SeriesLibraryProblem[]
}
/** Fortschritt des Serien-Jobs (`job.detail`): Phase und Zähler der Phase (nie rückwärts) */
export type SeriesCommitDetail = SeriesJobOut['job']['detail']
export type SeriesCommitPhase = NonNullable<SeriesCommitDetail['phase']>
/** Job „series“ (Schnappschuss wie alle Jobs, Ergebnis typisiert) */
export type SeriesJob = Job<SeriesCommitResult>

export type DecodeResult = Filled<ResponseOf<'/api/series/decode', 'post'>>
export type DecodedMpn = NonNullable<DecodeResult['best']>

/** Eigene Vorlage (Anfragekörper von Anlegen/Ändern/Testen) */
export type MpnTemplateInput = RequestBodyOf<'/api/series/templates/custom', 'post'>
export type TemplateTestBody = RequestBodyOf<'/api/series/templates/test', 'post'>
export type TemplateTestResult = Filled<ResponseOf<'/api/series/templates/test', 'post'>>
/** Ein Beispiel des Vorlagentests: Teilenummer, Rücklesen, Pflichtfelder (`missing_fields`), gespeicherte Werte */
export type TemplateSampleResult = TemplateTestResult['samples'][number]

/** Höchstzahl der Zeilen einer Vorschau/Serie (Backend: 1 … 50.000, Standard 5.000) */
export const SERIES_MAX_ROWS = 10_000

// --------------------------------------------------------------------------- Query-Keys

export const seriesKeys = {
  all: ['series'] as const,
  templates: ['series', 'templates'] as const,
  templateList: (category: string | null) => ['series', 'templates', 'list', category ?? '*'] as const,
  template: (id: string, full: boolean) => ['series', 'templates', 'detail', id, full] as const,
  preview: (req: SeriesRequest | null) => ['series', 'preview', req] as const,
  decode: (mpn: string, templateId: string | null) => ['series', 'decode', mpn, templateId ?? '*'] as const,
  test: (body: TemplateTestBody | null) => ['series', 'test', body] as const,
}

// --------------------------------------------------------------------------- Rohfunktionen

const enc = encodeURIComponent

export const seriesApi = {
  templates: (category?: string | null, signal?: AbortSignal) =>
    api.get<SeriesTemplateSummary[]>('/api/series/templates', { query: { category: category ?? undefined }, signal }),
  template: (id: string, full = false, signal?: AbortSignal) =>
    api.get<SeriesTemplate>(`/api/series/templates/${enc(id)}`, { query: { full }, signal }),
  /** Zeilen mit Status neu/vorhanden/Konflikt/ungültig – schreibt nichts (große Serien: einige Sekunden) */
  preview: (req: SeriesRequest, signal?: AbortSignal) =>
    api.post<SeriesPreview>('/api/series/preview', req, { signal, timeoutMs: 120_000 }),
  /** Serie als Hintergrundjob erzeugen (Symbol, Footprints, Bauteile) */
  commit: (body: SeriesCommitBody) => api.post<{ job: SeriesJob }>('/api/series/commit', body),
  /** Teilenummer lesen – mit allen Vorlagen oder nur mit `templateId` */
  decode: (mpn: string, templateId?: string | null, signal?: AbortSignal) =>
    api.post<DecodeResult>('/api/series/decode', { mpn, template_id: templateId ?? null }, { signal }),
  /** Vorlagenentwurf: Teilenummern für Beispielwerte bauen, zurücklesen und gegen die Pflichtfelder prüfen */
  test: (body: TemplateTestBody, signal?: AbortSignal) =>
    api.post<TemplateTestResult>('/api/series/templates/test', body, { signal }),
  createCustom: (template: MpnTemplateInput) => api.post<SeriesTemplate>('/api/series/templates/custom', template),
  updateCustom: (id: string, template: MpnTemplateInput) =>
    api.put<SeriesTemplate>(`/api/series/templates/custom/${enc(id)}`, template),
  deleteCustom: (id: string) => api.delete<{ deleted: boolean }>(`/api/series/templates/custom/${enc(id)}`),
}

// --------------------------------------------------------------------------- Hooks

/** Abfrage einer Vorlage – auch für `queryClient.fetchQuery` (z. B. Schnellstart übernimmt eine erkannte Serie) */
export function templateQueryOptions(id: string, full: boolean) {
  return {
    queryKey: seriesKeys.template(id, full),
    queryFn: ({ signal }: { signal: AbortSignal }) => seriesApi.template(id, full, signal),
    staleTime: 10 * 60_000,
    gcTime: 30 * 60_000,
    meta: { static: true },
  }
}

/**
 * Alle Vorlagen (eingebaut + eigene der Bibliothek), optional einer Kategorie – mit Beispiel und Kennwerten für die
 * Karten. `static`: kein Job ändert Vorlagen (eigene Vorlagen laden über ihre Mutationen neu).
 */
export function useSeriesTemplates(category: string | null = null) {
  return useQuery({
    queryKey: seriesKeys.templateList(category),
    queryFn: ({ signal }) => seriesApi.templates(category, signal),
    staleTime: 5 * 60_000,
    meta: { static: true },
  })
}

/** Eine Vorlage; `full` = mit Lieferbarkeitsmatrix (für exakte Zähler bei MLCC-Serien) */
export function useSeriesTemplate(id: string | null, opts: { full?: boolean; enabled?: boolean } = {}) {
  const full = opts.full ?? false
  return useQuery({
    ...templateQueryOptions(id ?? '–', full),
    enabled: Boolean(id) && (opts.enabled ?? true),
  })
}

/** Vorschau einer Auswahl (`null` = nichts laden); die letzte Vorschau bleibt beim Ändern sichtbar */
export function useSeriesPreview(req: SeriesRequest | null, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: seriesKeys.preview(req),
    queryFn: ({ signal }) => seriesApi.preview(req as SeriesRequest, signal),
    enabled: Boolean(req) && (opts.enabled ?? true),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    // große Antworten (mehrere MB) nicht lange im Speicher halten
    gcTime: 60_000,
  })
}

/** Neue/geänderte eigene Vorlage: Listen und Details neu laden */
export function invalidateTemplates(qc: QueryClient): Promise<void> {
  return qc.invalidateQueries({ queryKey: seriesKeys.templates })
}

export function useSaveCustomTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ template, existingId }: { template: MpnTemplateInput; existingId?: string | null }) =>
      existingId ? seriesApi.updateCustom(existingId, template) : seriesApi.createCustom(template),
    // nicht abwarten: der Dialog schließt sofort, Listen (samt Beispiel) und die geänderte Vorlage laden im Hintergrund
    onSuccess: (saved) => {
      void qc.invalidateQueries({ queryKey: [...seriesKeys.templates, 'list'] })
      void qc.invalidateQueries({ queryKey: [...seriesKeys.templates, 'detail', saved.id] })
    },
    meta: { silentError: true },
  })
}

export function useDeleteCustomTemplate() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => seriesApi.deleteCustom(id),
    onSuccess: async (_result, id) => {
      // erst aus den Listen nehmen (Karten verschwinden), dann Details verwerfen – kein Nachladen einer gelöschten Vorlage
      qc.setQueriesData<SeriesTemplateSummary[]>({ queryKey: [...seriesKeys.templates, 'list'] }, (list) =>
        list?.filter((t) => t.id !== id),
      )
      qc.removeQueries({ queryKey: [...seriesKeys.templates, 'detail', id] })
      await qc.invalidateQueries({ queryKey: [...seriesKeys.templates, 'list'] })
    },
    meta: { errorTitle: tr("Vorlage konnte nicht gelöscht werden") },
  })
}
