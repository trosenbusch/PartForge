import {
  MAX_STEP_MESH_BYTES, MAX_STEP_TRIANGLES, StepImportError,
  type OcctResult, type StepColor, type StepMesh, type StepModel,
} from './stepTypes'

function color(value: number[] | null | undefined): StepColor | undefined {
  if (!value || value.length < 3 || !value.slice(0, 3).every(Number.isFinite)) return undefined
  const clamp = (c: number) => Math.max(0, Math.min(1, c))
  return [clamp(value[0]), clamp(value[1]), clamp(value[2])]
}

/** Validate the native parser's output before allocating GPU/transfer buffers. */
export function stepModelFromOcct(result: OcctResult): StepModel {
  if (!result.success || !result.meshes?.length) throw new StepImportError('invalid_step')
  let triangleCount = 0
  let byteLength = 0
  const meshes: StepMesh[] = []
  for (const raw of result.meshes) {
    const positions = raw.attributes?.position?.array
    const indices = raw.index?.array
    if (!positions?.length || !indices?.length) continue
    const normals = raw.attributes.normal?.array
    if (positions.length % 3 || indices.length % 3 || (normals && normals.length !== positions.length)) {
      throw new StepImportError('invalid_step')
    }
    triangleCount += indices.length / 3
    byteLength += (positions.length + indices.length + (normals?.length ?? 0)) * 4
    if (triangleCount > MAX_STEP_TRIANGLES || byteLength > MAX_STEP_MESH_BYTES) throw new StepImportError('too_large')
    // Float32 conversion must not overflow; NaN/Infinity would poison scene bounds.
    if (!positions.every((v) => Number.isFinite(v) && Math.abs(v) <= 1e12)
      || (normals && !normals.every((v) => Number.isFinite(v) && Math.abs(v) <= 1.001))
      || !indices.every((i) => Number.isInteger(i) && i >= 0 && i < positions.length / 3)) {
      throw new StepImportError('invalid_step')
    }
    const faceColors: { first: number; last: number; color: StepColor }[] = []
    for (const face of raw.brep_faces ?? []) {
      const rgb = color(face.color)
      if (rgb && Number.isInteger(face.first) && Number.isInteger(face.last)
        && face.first >= 0 && face.last >= face.first && face.last < indices.length / 3) {
        faceColors.push({ first: face.first, last: face.last, color: rgb })
      }
    }
    // The native importer already applies assembly placements to each mesh.
    meshes.push({
      name: raw.name,
      positions: new Float32Array(positions),
      normals: normals ? new Float32Array(normals) : undefined,
      indices: new Uint32Array(indices),
      color: color(raw.color),
      faceColors: faceColors.length ? faceColors : undefined,
    })
  }
  if (!meshes.length) throw new StepImportError('invalid_step')
  return { meshes, triangleCount, byteLength }
}
