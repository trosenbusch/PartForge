import { useQuery } from '@tanstack/react-query'
import { isAbortError } from '@/api/client'
import { stepModelsApi, type StepModelFile, type StepSource } from '@/api/stepModels'
import { useWorkspace } from '@/api/system'
import { MAX_STEP_MESH_BYTES, MAX_STEP_TRIANGLES, StepImportError } from '@/lib/stepTypes'
import type { StepSceneModel } from './stepScene'

export interface LoadedStepModels {
  models: StepSceneModel[]
  files: StepModelFile[]
  warnings: string[]
  failures: { name: string; error: unknown }[]
}

/** Fetch only when a registered footprint's 3D view is actually opened. */
export function useStepModels(source: StepSource | undefined, render: boolean) {
  const root = useWorkspace().data?.root
  return useQuery({
    queryKey: ['footprints', 'library', 'step-models', root, source?.name, source?.revision, render],
    enabled: Boolean(root && source),
    staleTime: 30_000,
    gcTime: 60_000,
    retry: false,
    structuralSharing: false,
    queryFn: async ({ signal }): Promise<LoadedStepModels> => {
      const manifest = await stepModelsApi.manifest(source!.name, signal)
      const result: LoadedStepModels = { models: [], files: manifest.models, warnings: manifest.warnings, failures: [] }
      if (!render || !manifest.models.length) return result
      const { parseStep } = await import('@/lib/step')
      let bytes = 0
      let triangles = 0
      // Sequential parsing bounds memory and lets a changed selection cancel queued work promptly.
      for (const file of manifest.models) {
        signal.throwIfAborted()
        try {
          const blob = await stepModelsApi.file(file.url, signal)
          const buffer = await blob.arrayBuffer()
          // A PcbLib can place the same file many times; share tessellation across placements.
          const digest = await crypto.subtle.digest('SHA-256', buffer)
          const contentKey = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
          signal.throwIfAborted()
          const model = await parseStep(buffer, { signal, cacheKey: contentKey })
          signal.throwIfAborted()
          bytes += model.byteLength
          triangles += model.triangleCount
          if (bytes > MAX_STEP_MESH_BYTES || triangles > MAX_STEP_TRIANGLES) {
            result.failures.push({ name: file.name, error: new StepImportError('too_large') })
            break
          }
          result.models.push({
            id: file.id, meshes: model.meshes,
            rotation: [file.rotation[0] ?? 0, file.rotation[1] ?? 0, file.rotation[2] ?? 0],
            offset: [file.offset[0] ?? 0, file.offset[1] ?? 0, file.offset[2] ?? 0],
          })
        } catch (error) {
          if (signal.aborted || isAbortError(error)) throw error
          result.failures.push({ name: file.name, error })
        }
      }
      return result
    },
  })
}
