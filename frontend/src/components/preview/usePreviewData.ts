/**
 * Live-Vorschauen vom Backend (Generatoren, ohne Speichern): Footprint (`POST /api/footprints/preview`) und Symbol
 * (`POST /api/symbols/preview`). Beim Ändern der Anfrage bleibt die letzte Vorschau sichtbar (keepPreviousData),
 * Fehler zeigen keinen Toast (Abfragen sind standardmäßig still) – die PreviewPanel zeigt sie im Panel an.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { Filled, ResponseOf } from '@/api/types'
import type { FootprintRequest, FootprintSpec, SymbolRequest } from '@/lib/geometry'

/** `spec` bleibt der Geometrie-Typ (Filled würde die STEP-Tupel zu Arrays machen) */
export type FootprintPreviewData = Omit<Filled<ResponseOf<'/api/footprints/preview', 'post'>>, 'spec'> & { spec: FootprintSpec }
export type SymbolPreviewData = Filled<ResponseOf<'/api/symbols/preview', 'post'>>

export const previewKeys = {
  footprint: (req: FootprintRequest | null) => ['footprints', 'preview', req] as const,
  symbol: (req: SymbolRequest | null) => ['symbols', 'preview', req] as const,
}

/** Footprint-Vorschau inkl. Rechenprotokoll (`calc`), Warnungen und Prüfungen. `null` = nichts laden. */
export function useFootprintPreview(req: FootprintRequest | null, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: previewKeys.footprint(req),
    queryFn: ({ signal }) =>
      api.post<FootprintPreviewData>('/api/footprints/preview', { ...req, with_3d: req?.with_3d ?? true }, { signal }),
    enabled: Boolean(req) && (opts.enabled ?? true),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}

/** Symbol-Vorschau (Spec + Backend-SVGs). `null` = nichts laden. */
export function useSymbolPreview(req: SymbolRequest | null, opts: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: previewKeys.symbol(req),
    queryFn: ({ signal }) => api.post<SymbolPreviewData>('/api/symbols/preview', req, { signal, query: { theme: 'dark' } }),
    enabled: Boolean(req) && (opts.enabled ?? true),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}
