import { LAYERS, type CanvasLayer } from '@/lib/geometry'

/** Lagen-Sichtbarkeit (true = sichtbar); Abweichungen vom Standard */
export type LayerVisibility = Partial<Record<CanvasLayer, boolean>>

/** Standard-Sichtbarkeit aus den Lagen-Metadaten */
export const DEFAULT_LAYER_VISIBILITY: Record<CanvasLayer, boolean> = Object.fromEntries(
  Object.values(LAYERS).map((l) => [l.id, l.visible]),
) as Record<CanvasLayer, boolean>
