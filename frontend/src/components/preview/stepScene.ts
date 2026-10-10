import * as THREE from 'three'
import type { StepMesh } from '@/lib/stepTypes'

export interface StepSceneModel {
  id: string
  meshes: readonly StepMesh[]
  /** Altium model rotation, in degrees around the fixed footprint X, Y and Z axes. */
  rotation: readonly [number, number, number]
  /** Translation in footprint millimeters, applied after rotation. */
  offset: readonly [number, number, number]
  opacity?: number
}

type Rgb = readonly [number, number, number]

/** OCCT already applies STEP assembly locations. Only the Altium body placement belongs here. */
export function stepToSceneMatrix(rotation: StepSceneModel['rotation'], offset: StepSceneModel['offset']): THREE.Matrix4 {
  const radians = rotation.map((angle) => THREE.MathUtils.degToRad(angle))
  // Fixed-axis X, then Y, then Z: Rz * Ry * Rx. Three's Euler order is intrinsic.
  const placement = new THREE.Matrix4().makeRotationFromEuler(new THREE.Euler(radians[0], radians[1], radians[2], 'ZYX'))
  placement.setPosition(offset[0], offset[1], offset[2])
  // The footprint uses Z up; the viewer uses Y up: (x, y, z) -> (x, z, -y).
  return new THREE.Matrix4().makeRotationX(-Math.PI / 2).multiply(placement)
}

/** An instance owns its buffers, so placement and disposal cannot corrupt the parsed STEP cache. */
export function createStepGeometry(mesh: StepMesh, placement: Pick<StepSceneModel, 'rotation' | 'offset'>) {
  const geometry = new THREE.BufferGeometry()
  geometry.setAttribute('position', new THREE.BufferAttribute(mesh.positions.slice(), 3))
  geometry.setIndex(new THREE.BufferAttribute(mesh.indices.slice(), 1))
  if (mesh.normals?.length === mesh.positions.length) {
    geometry.setAttribute('normal', new THREE.BufferAttribute(mesh.normals.slice(), 3))
  } else {
    geometry.computeVertexNormals()
  }
  geometry.applyMatrix4(stepToSceneMatrix(placement.rotation, placement.offset))

  const colors: Rgb[] = [mesh.color ?? [0.66, 0.69, 0.73]]
  const colorIndex = new Map<string, number>([[colors[0].join(','), 0]])
  const faces = [...(mesh.faceColors ?? [])].sort((a, b) => a.first - b.first)
  const triangleCount = mesh.indices.length / 3
  const addGroup = (start: number, count: number, materialIndex: number) => {
    const last = geometry.groups.at(-1)
    if (last && last.materialIndex === materialIndex && last.start + last.count === start) last.count += count
    else geometry.addGroup(start, count, materialIndex)
  }
  let cursor = 0
  for (const face of faces) {
    const first = Math.max(cursor, Math.min(triangleCount, Math.floor(face.first)))
    const end = Math.min(triangleCount, Math.floor(face.last) + 1)
    if (end <= first) continue
    if (first > cursor) addGroup(cursor * 3, (first - cursor) * 3, 0)
    const key = face.color.join(',')
    let materialIndex = colorIndex.get(key)
    if (materialIndex === undefined) {
      materialIndex = colors.length
      colors.push(face.color)
      colorIndex.set(key, materialIndex)
    }
    addGroup(first * 3, (end - first) * 3, materialIndex)
    cursor = end
  }
  if (cursor < triangleCount) addGroup(cursor * 3, (triangleCount - cursor) * 3, 0)
  geometry.computeBoundingBox()
  geometry.computeBoundingSphere()
  return { geometry, colors }
}

/** Union actual geometry bounds, including off-center placements and parts below the board. */
export function fitSceneBounds(bounds: readonly THREE.Box3[]) {
  const box = new THREE.Box3()
  for (const bound of bounds) box.union(bound)
  if (box.isEmpty()) box.set(new THREE.Vector3(-1, 0, -1), new THREE.Vector3(1, 1, 1))
  const center = box.getCenter(new THREE.Vector3())
  const radius = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 0.01)
  return { box, center, radius }
}
