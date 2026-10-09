/**
 * Symbole: Generator (Symboltypen, Live-Vorschau, IC-Seitenzuordnung) und Symbolbibliothek (Registrierung).
 *
 *   const kinds = useSymbolKinds('dark')                    // GET  /api/symbols/kinds?thumbnails=true
 *   const preview = useSymbolGeneratorPreview(request)      // POST /api/symbols/preview?svg=false (entprellt aufrufen)
 *   await symbolsApi.autoSides(pins, true)                  // POST /api/symbols/auto-sides
 *   const lib = useSymbolLibrary()                          // GET  /api/libraries/symbols (ohne Vorschaubilder)
 *   symbolsApi.thumbnail(name, 'dark', entry.content_hash)  // GET  …/symbols/{name}/thumbnail.svg?v=<content_hash> (dauerhaft)
 *   const plan = await symbolsApi.save(input, { dryRun: true })   // PUT …?dry_run=true: Ziel, neu/unverändert, Pinänderung
 *   await symbolsApi.save({ ...input, library: 'Symbols\\PF_Power.SchLib' })   // ausdrückliche Ziel-SchLib (neue Namen)
 *
 * Die Leinwände zeichnen aus dem Spec – Vorschau und Detail werden darum ohne SVG geladen (`svg=false`).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { ApiError, api } from './client'
import { useWorkspace, type Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen (aus dem Schema)

export type SymbolKindInfo = Filled<ResponseOf<'/api/symbols/kinds', 'get'>>[number]
export type SymbolParamSpec = SymbolKindInfo['params'][number]
export type SymbolRequest = RequestBodyOf<'/api/symbols/preview', 'post'>
export type IcPin = NonNullable<SymbolRequest['pins']>[number]
export type IcSide = NonNullable<IcPin['side']>
export type ElectricalType = IcPin['electrical']
export type SymbolPreviewOut = Filled<ResponseOf<'/api/symbols/preview', 'post'>>
export type GeneratedSpec = SymbolPreviewOut['spec']
export type AutoSidesOut = Filled<ResponseOf<'/api/symbols/auto-sides', 'post'>>
export type SymbolEntry = Filled<ResponseOf<'/api/libraries/symbols', 'get'>>[number]
export type SymbolDetail = Filled<ResponseOf<'/api/libraries/symbols/{name}', 'get'>>
export type SymbolSaveIn = RequestBodyOf<'/api/libraries/symbols/{name}', 'put'>
export type SymbolSaveOut = Filled<ResponseOf<'/api/libraries/symbols/{name}', 'put'>>
export type SymbolDeleteOut = Filled<ResponseOf<'/api/libraries/symbols/{name}', 'delete'>>

/** Darstellung der Backend-SVGs (Vorschaubilder) */
export type SymbolSvgTheme = 'altium' | 'dark' | 'light'

/** Gruppen der Symboltypen in fester Reihenfolge (wie im Backend) */
export const SYMBOL_GROUPS = ['Passiv', 'Halbleiter', 'ICs', 'Verbinder', 'Sonstige'] as const

// --------------------------------------------------------------------------- Fehler

/** 409 „pinout_changed“: Speichern würde die Pinbelegung eines registrierten Symbols ändern */
export interface PinoutChange {
  message: string
  /** Änderungen auf Deutsch, z. B. „Pin 2: Name „TRIG“ → „TRIGGER““ */
  changes: string[]
  /** Bauteile, die das Symbol verwenden */
  usage: number
}

export function pinoutChanged(error: unknown): PinoutChange | null {
  if (!(error instanceof ApiError) || error.status !== 409 || !error.detail || typeof error.detail !== 'object') return null
  const d = error.detail as { code?: unknown; message?: unknown; changes?: unknown; usage?: unknown }
  if (d.code !== 'pinout_changed') return null
  return {
    message: typeof d.message === 'string' ? d.message : error.message,
    changes: Array.isArray(d.changes) ? d.changes.filter((c): c is string => typeof c === 'string') : [],
    usage: typeof d.usage === 'number' ? d.usage : 0,
  }
}

// --------------------------------------------------------------------------- Query-Keys

export const symbolKeys = {
  all: ['symbols'] as const,
  kinds: (theme: SymbolSvgTheme, style = '') => ['symbols', 'kinds', theme, style] as const,
  preview: (req: SymbolRequest | null, style = '') => ['symbols', 'generator-preview', req, style] as const,
  /** Einträge der Bibliothek (ohne Vorschaubilder – die lädt jede Karte selbst) */
  library: ['symbols', 'library', 'list'] as const,
  libraryAll: ['symbols', 'library'] as const,
  /** Vorschaubild je Inhalt (`content_hash`: Geometrie, Hausstil, Darstellung) – neuer Inhalt = neuer Schlüssel */
  thumbnail: (name: string, theme: string, contentHash: string) => ['symbols', 'library', 'thumb', name, theme, contentHash] as const,
  detail: (name: string) => ['symbols', 'detail', name] as const,
  detailAll: ['symbols', 'detail'] as const,
  /**
   * Probelauf des Speicherns (Ziel, neu/unverändert, Pinänderungen) – unter „library“, damit Speichern ihn neu lädt.
   * `library` = ausdrückliche Ziel-SchLib (`null` = automatisch nach Kategorie).
   */
  savePlan: (name: string, fingerprint: string, category: string | null, library: string | null = null) =>
    ['symbols', 'library', 'save-plan', name, fingerprint, category, library] as const,
}

// --------------------------------------------------------------------------- Funktionen

const enc = (name: string) => encodeURIComponent(name)

export const symbolsApi = {
  kinds: (theme: SymbolSvgTheme, signal?: AbortSignal) =>
    api.get<SymbolKindInfo[]>('/api/symbols/kinds', { query: { thumbnails: true, theme }, signal }),
  /** Generator-Vorschau: Spec und Hinweise (ohne SVG – die Leinwand zeichnet selbst) */
  preview: (req: SymbolRequest, signal?: AbortSignal) =>
    api.post<SymbolPreviewOut>('/api/symbols/preview', req, { query: { svg: false }, signal }),
  /** Seiten für IC-Pins bestimmen; `overwrite` = auch bereits gesetzte Seiten neu bestimmen */
  autoSides: (pins: IcPin[], overwrite: boolean, signal?: AbortSignal) =>
    api.post<AutoSidesOut>('/api/symbols/auto-sides', { pins, overwrite }, { signal }),
  /** Registrierte Symbole (Status, Verwendung, Pins) – ohne Vorschaubilder */
  library: (signal?: AbortSignal) => api.get<SymbolEntry[]>('/api/libraries/symbols', { signal }),
  /** Ein Symbol der Bibliothek: Eintrag, Geometrie, Hinweise (ohne SVG) */
  detail: (name: string, signal?: AbortSignal) =>
    api.get<SymbolDetail>(`/api/libraries/symbols/${enc(name)}`, { query: { svg: false }, signal }),
  /**
   * Vorschaubild eines registrierten Symbols (SVG-Text). `contentHash` = `content_hash` des Eintrags (Liste, Detail,
   * Speichern): Mit ihm als `?v=` speichert der Browser das Bild dauerhaft (`immutable`) – ein neuer Inhalt hat einen
   * neuen Prüfwert, also eine neue Adresse. Ohne Prüfwert fragt der Browser per ETag nach (304).
   */
  thumbnail: (name: string, theme: 'dark' | 'light', contentHash: string | null, signal?: AbortSignal) =>
    api.get<string>(`/api/libraries/symbols/${enc(name)}/thumbnail.svg`, {
      query: { theme, v: contentHash || undefined },
      responseType: 'text',
      signal,
    }),
  /**
   * Symbol speichern (registrieren + in die SchLib schreiben). `dryRun`: nur prüfen – Ziel-Bibliothek, neu/unverändert,
   * Pinänderungen (`changes`, `needs_confirmation`) und Verwendung; nichts wird geschrieben. `input.library` = Ziel-SchLib
   * für einen **neuen** Namen (vorhandene Datei unter `Symbols\` oder neue `PF_<Name>.SchLib`; leer = nach Kategorie) –
   * ein schon registrierter Name bleibt in seiner Datei (eine andere Angabe lehnt das Backend mit 409 ab).
   */
  save: (input: SymbolSaveIn, opts: { dryRun?: boolean; signal?: AbortSignal } = {}) =>
    api.put<SymbolSaveOut>(`/api/libraries/symbols/${enc(input.spec.name)}`, input, {
      query: { dry_run: opts.dryRun || undefined },
      timeoutMs: opts.dryRun ? 30_000 : 120_000,
      signal: opts.signal,
    }),
  remove: (name: string, force = false) =>
    api.delete<SymbolDeleteOut>(`/api/libraries/symbols/${enc(name)}`, { query: { force: force || undefined } }),
}

// --------------------------------------------------------------------------- Hooks

/**
 * Hausstil der Bibliothek als Schlüsselteil: Ändert jemand die Symbol-Einstellungen (Raster, Diode Pin 1,
 * Widerstandssymbol …), werden Typen und Vorschauen neu berechnet statt aus dem Cache gezeigt.
 */
export function useSymbolStyleKey(): string {
  const style = useWorkspace().data?.settings.symbol
  return style ? JSON.stringify(style) : ''
}

/** Kurzer, stabiler Prüfwert eines Texts (FNV-1a, 8 Hex-Zeichen) – für Cache-Versionen in Adressen */
export function shortHash(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return (h >>> 0).toString(16).padStart(8, '0')
}

/** Alle Symboltypen mit SVG-Vorschau (im Theme der App). Ändert sich nur mit dem Hausstil. */
export function useSymbolKinds(theme: SymbolSvgTheme) {
  const style = useSymbolStyleKey()
  return useQuery({
    queryKey: symbolKeys.kinds(theme, style),
    queryFn: ({ signal }) => symbolsApi.kinds(theme, signal),
    staleTime: 5 * 60_000,
    placeholderData: keepPreviousData,
    meta: { static: true },
  })
}

/**
 * Cache-Dauer der Generator-Vorschauen: Jeder entprellte Tastendruck ist eine eigene Anfrage – ungenutzte Einträge
 * darum schnell freigeben.
 */
export const PREVIEW_GC_MS = 20_000

/** Abfrage-Optionen der Generator-Vorschau (auch für `queryClient.fetchQuery` vor dem Speichern) */
export function symbolPreviewOptions(req: SymbolRequest, styleKey: string) {
  return {
    queryKey: symbolKeys.preview(req, styleKey),
    queryFn: ({ signal }: { signal: AbortSignal }) => symbolsApi.preview(req, signal),
    staleTime: 5 * 60_000,
    gcTime: PREVIEW_GC_MS,
  }
}

/**
 * Live-Vorschau des Generators. Die Anfrage entprellt der Aufrufer; die letzte Vorschau bleibt beim Laden sichtbar.
 * Gezeichnet wird aus dem Spec – ein Wechsel der Darstellung (Altium-Ansicht, Theme) löst keine neue Berechnung aus.
 */
export function useSymbolGeneratorPreview(req: SymbolRequest | null) {
  const style = useSymbolStyleKey()
  return useQuery({
    queryKey: symbolKeys.preview(req, style),
    queryFn: ({ signal }) => symbolsApi.preview(req as SymbolRequest, signal),
    enabled: req !== null,
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
    gcTime: PREVIEW_GC_MS,
    retry: false,
  })
}

/** Einträge der Symbolbibliothek (Galerie, Zähler, „schon in der Bibliothek?“ im Generator) */
export function useSymbolLibrary(opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: symbolKeys.library,
    queryFn: ({ signal }) => symbolsApi.library(signal),
    enabled: opts.enabled ?? true,
    staleTime: 20_000,
    placeholderData: keepPreviousData,
  })
}

/** Ein Symbol der Bibliothek (Spec, Teile, Warnungen, Datei vorhanden). */
export function useSymbolDetail(name: string | null) {
  return useQuery({
    queryKey: symbolKeys.detail(name ?? '–'),
    queryFn: ({ signal }) => symbolsApi.detail(name as string, signal),
    enabled: Boolean(name),
    staleTime: 20_000,
    retry: false,
  })
}

export type SaveSymbolResult = { kind: 'saved'; record: SymbolEntry; out: SymbolSaveOut } | { kind: 'job'; job: Job; out: SymbolSaveOut }

/**
 * Symbol speichern (registrieren + in die SchLib schreiben) – direkt oder als Job. Fehler (400 Validierung, 409
 * Pinbelegung/extern/fremd, 503 Schreiber) behandelt der Aufrufer selbst (`silentError`), z. B. die Rückfrage bei
 * geänderter Pinbelegung ({@link pinoutChanged}).
 */
export function useSaveSymbol() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: SymbolSaveIn): Promise<SaveSymbolResult> => {
      const out = await symbolsApi.save(input)
      if (out.job) return { kind: 'job', job: out.job as unknown as Job, out }
      if (out.record) return { kind: 'saved', record: out.record, out }
      throw new Error('Das Backend hat weder einen Eintrag noch einen Job geliefert.')
    },
    meta: { silentError: true },
    // auch bei 503 („vorgemerkt“) ist der Eintrag registriert → Liste neu laden
    onSettled: () => invalidateSymbolLibrary(qc),
  })
}

/**
 * Nach dem Speichern/Löschen: Liste, Speicher-Probeläufe, Details, die Bibliothekslisten des Bauteile-Moduls und die
 * Kennzahlen neu laden. Vorschaubilder nicht – ihr Schlüssel trägt den `content_hash` (neuer Inhalt = neues Bild).
 * `deleted`: Detail und Geometrie dieses Namens nur als veraltet markieren, nicht neu laden (der Dialog schließt
 * gerade – ein erneutes Holen ergäbe 404).
 */
export function invalidateSymbolLibrary(qc: QueryClient, deleted?: string | null) {
  const gone = deleted?.toLowerCase() ?? null
  const isGone = (key: readonly unknown[], kind: string, at: number) =>
    gone !== null && key[at - 1] === kind && typeof key[at] === 'string' && (key[at] as string).toLowerCase() === gone
  if (deleted) {
    void qc.invalidateQueries({ queryKey: symbolKeys.detail(deleted), refetchType: 'none' })
    void qc.invalidateQueries({ queryKey: ['parts', 'library', 'symbol', deleted], refetchType: 'none' })
  }
  void qc.invalidateQueries({ queryKey: symbolKeys.libraryAll, predicate: (q) => q.queryKey[2] !== 'thumb' })
  void qc.invalidateQueries({ queryKey: symbolKeys.detailAll, predicate: (q) => !isGone(q.queryKey, 'detail', 2) })
  void qc.invalidateQueries({ queryKey: ['parts', 'library'], predicate: (q) => !isGone(q.queryKey, 'symbol', 3) })
  void qc.invalidateQueries({ queryKey: ['stats'] })
}

/**
 * Symbol aus Bibliothek und Registrierung löschen (vom Backend verweigert, solange Bauteile es nutzen). Nach einem
 * direkten Löschen lädt das Detail des Namens nicht neu; läuft es als Job, lädt der Job-Abschluss alles neu.
 */
export function useDeleteSymbol() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ name, force }: { name: string; force?: boolean }) => symbolsApi.remove(name, force),
    meta: { errorTitle: 'Symbol konnte nicht gelöscht werden' },
    onSettled: (out, error, { name }) => {
      const gone = !error && Boolean(out?.result && (out.result.deleted.length || out.result.unregistered.length))
      invalidateSymbolLibrary(qc, gone ? name : null)
    },
  })
}
