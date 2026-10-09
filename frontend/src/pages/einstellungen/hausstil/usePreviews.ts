/**
 * Vorschau-Anfragen des Hausstils – entprellt, damit Eingaben keine Anfrageflut auslösen.
 *
 * Die Generator-Vorschauen rechnen mit dem **gespeicherten** Hausstil; ein `style` in der Anfrage wertet das
 * Backend (noch) nicht aus. Deshalb bestimmen nur die echten Anfrage-Parameter (Gehäuse, Dichte, F/P, Rundung,
 * Kupferabstand, Courtyard-Raster bzw. Symboltyp und Pins) den Abruf – Linienbreiten oder Farben lösen keinen neuen
 * Abruf aus, die zeichnet `overlay.ts` direkt auf das Ergebnis. Sobald das Backend `style` unterstützt
 * (Wunsch an das Backend), gehört der Entwurf hier mit in Anfrage und Schlüssel.
 */
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { FootprintPreviewData, SymbolPreviewData } from '@/components/preview'
import type { FootprintRequest, SymbolRequest } from '@/lib/geometry'
import { useDebounced } from '../hooks'

export function useStyledFootprintPreview(req: FootprintRequest) {
  const body = useDebounced(req, 250)
  return useQuery({
    queryKey: ['footprints', 'style-preview', body],
    queryFn: ({ signal }) => api.post<FootprintPreviewData>('/api/footprints/preview', body, { signal }),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}

export function useStyledSymbolPreview(req: SymbolRequest) {
  const body = useDebounced(req, 350)
  return useQuery({
    queryKey: ['symbols', 'style-preview', body],
    queryFn: ({ signal }) => api.post<SymbolPreviewData>('/api/symbols/preview', body, { signal, query: { theme: 'altium' } }),
    placeholderData: keepPreviousData,
    staleTime: 5 * 60_000,
  })
}
