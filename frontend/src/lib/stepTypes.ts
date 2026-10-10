/** STEP coordinates stay in their original frame; all lengths are millimetres. */
export type StepColor = readonly [number, number, number]

export interface StepMesh {
  readonly name?: string
  readonly positions: Float32Array
  readonly normals?: Float32Array
  readonly indices: Uint32Array
  readonly color?: StepColor
  /** Inclusive triangle ranges, as returned by OpenCascade. */
  readonly faceColors?: readonly { first: number; last: number; color: StepColor }[]
}

/** Shared cache data: callers must not mutate or transfer these arrays. */
export interface StepModel {
  readonly meshes: readonly StepMesh[]
  readonly triangleCount: number
  readonly byteLength: number
}

export type StepErrorCode = 'invalid_step' | 'too_large' | 'parser_unavailable' | 'timeout' | 'busy'

export class StepImportError extends Error {
  readonly code: StepErrorCode
  constructor(code: StepErrorCode) {
    super(code)
    this.name = 'StepImportError'
    this.code = code
  }
}

export const MAX_STEP_BYTES = 64 * 1024 * 1024
export const MAX_STEP_MESH_BYTES = 128 * 1024 * 1024
export const MAX_STEP_TRIANGLES = 2_000_000

export interface StepWorkerRequest {
  id: number
  bytes: ArrayBuffer
}

export type StepWorkerResponse =
  | { id: number; model: StepModel }
  | { id: number; error: StepErrorCode }

export interface OcctMesh {
  name?: string
  color?: number[]
  brep_faces?: { first: number; last: number; color: number[] | null }[]
  attributes: { position: { array: number[] }; normal?: { array: number[] } }
  index: { array: number[] }
}

export interface OcctResult {
  success: boolean
  meshes?: OcctMesh[]
}

export interface OcctImporter {
  ReadStepFile(bytes: Uint8Array, params: {
    linearUnit: 'millimeter'
    linearDeflectionType: 'bounding_box_ratio'
    linearDeflection: number
    angularDeflection: number
  }): OcctResult
}
