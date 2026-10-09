/** Formularzustand → `FootprintRequest` des Generators. */
import type { FootprintFamily } from '@/api/footprints'
import type { FootprintRequest } from '@/lib/geometry'
import type { Density, LandPatternState, NameOverrides } from '../generator/store'
import { serializeParams, type ParamValues } from './params'

/** Herstellerempfehlung als `land_pattern` (nur vollständig: Padbreite, Padlänge, Reihenabstand) */
export function landPatternPayload(land: LandPatternState): Record<string, unknown> | null {
  if (!land.enabled) return null
  if (land.pad_width === null || land.pad_length === null || land.row_spacing === null) return null
  const out: Record<string, unknown> = {
    pad_width: land.pad_width,
    pad_length: land.pad_length,
    row_spacing: land.row_spacing,
    reference: land.reference,
  }
  if (land.row_spacing_y !== null) out.row_spacing_y = land.row_spacing_y
  if (land.ep_width !== null && land.ep_length !== null) {
    out.ep_width = land.ep_width
    out.ep_length = land.ep_length
  }
  return out
}

/** Ist die Herstellerempfehlung eingeschaltet, aber unvollständig? */
export const landPatternIncomplete = (land: LandPatternState): boolean =>
  land.enabled && (land.pad_width === null || land.pad_length === null || land.row_spacing === null)

export function buildRequest(
  family: FootprintFamily,
  values: ParamValues,
  density: Density,
  land: LandPatternState,
  overrides?: NameOverrides,
): FootprintRequest {
  const req: FootprintRequest = {
    family: family.key,
    params: serializeParams(family.params, values),
    density,
    with_3d: true,
  }
  const lp = landPatternPayload(land)
  if (lp) req.land_pattern = lp
  const name = overrides?.name?.trim()
  const description = overrides?.description?.trim()
  if (name) req.name = name
  if (description) req.description = description
  return req
}
