/**
 * Footprint-Geometrie für die Vorschau einer Serie: vorhandene aus der Bibliothek, noch zu erzeugende über den
 * Generator (gleiche Anfrage wie das Backend beim Erzeugen). Gemeinsamer Cache mit den Verweis-Zellen der Tabelle
 * (`['footprints', 'ref-preview', name]`).
 */
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { SeriesFootprintRef, SeriesTemplate } from '@/api/series'
import type { FootprintPreviewData } from '@/components/preview'
import type { FootprintSpec } from '@/lib/geometry'
import { footprintRequestFor } from './footprint'
import type { Density } from './settings'

export interface FootprintPreviewResult {
  footprint: FootprintSpec | null
  description: string | null
}

export const footprintPreviewKey = (name: string) => ['footprints', 'ref-preview', name] as const

export async function loadFootprintPreview(
  ref: Pick<SeriesFootprintRef, 'name' | 'exists' | 'size' | 'library'>,
  t: SeriesTemplate,
  density: Density,
  signal: AbortSignal,
): Promise<FootprintPreviewResult> {
  if (ref.exists) {
    try {
      const detail = await api.get<{ spec: FootprintSpec | null }>(`/api/libraries/footprints/${encodeURIComponent(ref.name)}`, {
        signal,
        query: { theme: 'dark' },
      })
      if (detail.spec) return { footprint: detail.spec, description: ref.library ? `vorhanden · ${ref.library}` : 'vorhanden' }
    } catch (error) {
      if (signal.aborted) throw error
    }
  }
  const req = ref.size ? footprintRequestFor(t, ref.size, density) : null
  if (!req) return { footprint: null, description: null }
  const preview = await api.post<FootprintPreviewData>('/api/footprints/preview', req, { signal })
  return { footprint: preview.spec, description: ref.exists ? 'vorhanden' : 'wird erzeugt' }
}

export function useFootprintPreviewFor(
  ref: SeriesFootprintRef | null,
  t: SeriesTemplate,
  density: Density,
) {
  return useQuery({
    queryKey: footprintPreviewKey(ref?.name ?? '–'),
    queryFn: ({ signal }) => loadFootprintPreview(ref as SeriesFootprintRef, t, density, signal),
    enabled: Boolean(ref),
    staleTime: 5 * 60_000,
    retry: false,
  })
}
