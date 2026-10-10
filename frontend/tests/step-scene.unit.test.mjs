import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import * as THREE from 'three'

let server
let scene

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)),
    configFile: false,
    resolve: { alias: { '@': fileURLToPath(new URL('../src', import.meta.url)) } },
    logLevel: 'silent',
    appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  scene = await server.ssrLoadModule('/src/components/preview/stepScene.ts')
})
after(async () => { await server?.close() })

function near(actual, expected) {
  assert.equal(actual.length, expected.length)
  actual.forEach((value, index) => assert.ok(Math.abs(value - expected[index]) < 1e-5, `${actual} != ${expected}`))
}

function point(rotation, offset, xyz = [2, 3, 5]) {
  return new THREE.Vector3(...xyz).applyMatrix4(scene.stepToSceneMatrix(rotation, offset)).toArray()
}

test('STEP coordinates use the same PCB plane and height as pads and generated bodies', () => {
  near(point([0, 0, 0], [0, 0, 0]), [2, 5, -3])
  near(point([0, 0, 0], [10, -7, 0.25]), [12, 5.25, 4])
})

test('Altium axis rotations precede translation and the viewer coordinate mapping', () => {
  near(point([90, 0, 0], [10, 20, 30]), [12, 33, -15])
  near(point([0, 90, 0], [10, 20, 30]), [15, 28, -23])
  near(point([0, 0, 90], [10, 20, 30]), [7, 35, -22])
  // Fixed X followed by Y and Z maps (2,3,5) to (5,3,-2) before the offset.
  near(point([90, 90, 90], [10, 20, 30]), [15, 28, -23])
})

function sampleMesh() {
  return {
    positions: new Float32Array([0, 0, 0, 2, 0, 0, 0, 4, 0, 0, 0, 6]),
    normals: new Float32Array([0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 0]),
    indices: new Uint32Array([0, 1, 2, 0, 1, 3, 0, 2, 3, 1, 2, 3]),
    color: [0.1, 0.2, 0.3],
    faceColors: [
      { first: 1, last: 1, color: [1, 0, 0] },
      { first: 3, last: 3, color: [1, 0, 0] },
    ],
  }
}

test('separate placements retain source buffers and rotate normals without translating them', () => {
  const mesh = sampleMesh()
  const original = mesh.positions.slice()
  const one = scene.createStepGeometry(mesh, { rotation: [0, 0, 0], offset: [0, 0, 0] })
  const two = scene.createStepGeometry(mesh, { rotation: [90, 0, 0], offset: [12, 3, 4] })
  near(Array.from(two.geometry.attributes.position.array.slice(0, 3)), [12, 4, -3])
  near(Array.from(two.geometry.attributes.normal.array.slice(0, 3)), [0, 0, 1])
  assert.deepEqual(mesh.positions, original)
  assert.notEqual(one.geometry.attributes.position.array, mesh.positions)
  assert.notEqual(one.geometry.index.array, mesh.indices)
  assert.notEqual(two.geometry.attributes.position.array, one.geometry.attributes.position.array)
  one.geometry.dispose()
  near(Array.from(two.geometry.attributes.position.array.slice(0, 3)), [12, 4, -3])
  two.geometry.dispose()
})

test('STEP face colors preserve the mesh default between colored faces', () => {
  const { geometry, colors } = scene.createStepGeometry(sampleMesh(), { rotation: [0, 0, 0], offset: [0, 0, 0] })
  assert.deepEqual(colors, [[0.1, 0.2, 0.3], [1, 0, 0]])
  assert.deepEqual(geometry.groups, [
    { start: 0, count: 3, materialIndex: 0 },
    { start: 3, count: 3, materialIndex: 1 },
    { start: 6, count: 3, materialIndex: 0 },
    { start: 9, count: 3, materialIndex: 1 },
  ])
  geometry.dispose()
})

test('adjacent CAD faces sharing a color need only one draw group', () => {
  const mesh = sampleMesh()
  mesh.faceColors = [
    { first: 0, last: 0, color: [1, 0, 0] },
    { first: 1, last: 1, color: [1, 0, 0] },
    { first: 2, last: 3, color: [1, 0, 0] },
  ]
  const { geometry } = scene.createStepGeometry(mesh, { rotation: [0, 0, 0], offset: [0, 0, 0] })
  assert.deepEqual(geometry.groups, [{ start: 0, count: 12, materialIndex: 1 }])
  geometry.dispose()
})

test('camera bounds contain the board and every asymmetric, off-center STEP placement', () => {
  const board = new THREE.Box3(new THREE.Vector3(-3, -1.6, -3), new THREE.Vector3(3, 0.035, 3))
  const first = scene.createStepGeometry(sampleMesh(), { rotation: [0, 0, 90], offset: [20, 10, 12] })
  const second = scene.createStepGeometry(sampleMesh(), { rotation: [0, 90, 0], offset: [-14, -2, -2] })
  const fit = scene.fitSceneBounds([board, first.geometry.boundingBox, second.geometry.boundingBox])
  near(fit.box.min.toArray(), [-14, -4, -12])
  near(fit.box.max.toArray(), [20, 18, 3])
  near(fit.center.toArray(), [3, 7, -4.5])
  for (const geometry of [first.geometry, second.geometry]) {
    for (let i = 0; i < geometry.attributes.position.count; i++) {
      const vertex = new THREE.Vector3().fromBufferAttribute(geometry.attributes.position, i)
      assert.ok(vertex.distanceTo(fit.center) <= fit.radius + 1e-5)
    }
    geometry.dispose()
  }
})

test('uncolored STEP meshes without supplied normals get complete geometry and stable bounds', () => {
  const mesh = sampleMesh()
  delete mesh.normals
  delete mesh.color
  delete mesh.faceColors
  const { geometry, colors } = scene.createStepGeometry(mesh, { rotation: [0, 0, 0], offset: [0, 0, 0] })
  assert.equal(geometry.attributes.normal.count, 4)
  assert.ok(Array.from(geometry.attributes.normal.array).every(Number.isFinite))
  assert.equal(colors.length, 1)
  assert.deepEqual(geometry.groups, [{ start: 0, count: 12, materialIndex: 0 }])
  near(geometry.boundingBox.min.toArray(), [0, 0, -4])
  near(geometry.boundingBox.max.toArray(), [2, 6, 0])
  geometry.dispose()
})
