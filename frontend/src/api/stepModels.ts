import { api } from './client'
import type { Filled, ResponseOf } from './types'

export type StepModelManifest = Filled<ResponseOf<'/api/libraries/footprints/{name}/step-models', 'get'>>
export type StepModelFile = StepModelManifest['models'][number]

/** A registered footprint, distinct from an unsaved generator preview with the same name. */
export interface StepSource {
  name: string
  revision?: string | null
}

export const stepModelsApi = {
  manifest: (name: string, signal?: AbortSignal) =>
    api.get<StepModelManifest>(`/api/libraries/footprints/${encodeURIComponent(name)}/step-models`, {
      signal, timeoutMs: 120_000,
    }),
  file: (url: string, signal?: AbortSignal) =>
    api.get<Blob>(url, { signal, responseType: 'blob', timeoutMs: 60_000 }),
}
