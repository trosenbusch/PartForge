import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { after, before, test } from 'node:test'
import { fileURLToPath } from 'node:url'
import createImporter from 'occt-import-js'
import { createServer } from 'vite'

let server, occt, step, convert
const originalWorker = globalThis.Worker
const workers = []
const fixtureRoot = new URL('../node_modules/occt-import-js/test/testfiles/', import.meta.url)
const triangulation = { linearUnit: 'millimeter', linearDeflectionType: 'bounding_box_ratio', linearDeflection: 0.001, angularDeflection: 0.25 }
const bytes = () => new TextEncoder().encode('ISO-10303-21;').buffer

class FakeWorker {
  requests = []
  terminated = false
  constructor() { workers.push(this) }
  postMessage(request) { this.requests.push(request) }
  terminate() { this.terminated = true }
  respond(model) { this.onmessage({ data: { id: this.requests.at(-1).id, model } }) }
}

function bounds(model) {
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity]
  for (const mesh of model.meshes) {
    mesh.positions.forEach((v, i) => { min[i % 3] = Math.min(min[i % 3], v); max[i % 3] = Math.max(max[i % 3], v) })
  }
  return { min, max }
}

function realModel(path) {
  return convert(occt.ReadStepFile(readFileSync(new URL(path, fixtureRoot)), triangulation))
}

before(async () => {
  server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)), configFile: false,
    logLevel: 'silent', appType: 'custom',
    server: { middlewareMode: true, hmr: false, watch: null },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  convert = (await server.ssrLoadModule('/src/lib/stepMesh.ts')).stepModelFromOcct
  step = await server.ssrLoadModule('/src/lib/step.ts')
  occt = await createImporter({ print() {}, printErr() {} })
  globalThis.Worker = FakeWorker
})

after(async () => {
  // Cancelling a final active task also releases the parser's idle timer.
  const controller = new AbortController()
  const pending = step.parseStep(bytes(), { signal: controller.signal })
  controller.abort()
  await assert.rejects(pending, { name: 'AbortError' })
  globalThis.Worker = originalWorker
  await server?.close()
})

test('real STEP imports millimetres, metres and inches into the same millimetre coordinates', () => {
  for (const unit of ['mm', 'm', 'in']) {
    const model = realModel(`cube-units/cube-${unit}.step`)
    assert.equal(model.triangleCount, 12)
    assert.deepEqual(bounds(model), { min: [0, 0, 0], max: [1000, 1000, 1000] })
    assert.ok(model.meshes[0].positions instanceof Float32Array)
    assert.ok(model.meshes[0].indices instanceof Uint32Array)
  }
})

test('real STEP preserves per-face colours and tessellates curved faces', () => {
  const model = realModel('cube-fcstd/cube.step')
  assert.deepEqual(model.meshes[0].faceColors.map((f) => [f.first, f.last]), [[0, 1], [6, 7], [10, 11]])
  assert.deepEqual(model.meshes[0].faceColors[0].color, [1, 0, 0])
  assert.deepEqual(model.meshes[0].faceColors[1].color, [0, 0, 1])
  const curved = realModel('rounded-cube/rounded-cube.step')
  assert.ok(curved.triangleCount > 12)
  assert.deepEqual(bounds(curved), { min: [0, 0, 0], max: [10, 10, 10] })
})

test('real assembly STEP retains every placed solid and its colour', () => {
  const model = realModel('cax-if/as1-oc-214.stp')
  assert.equal(model.meshes.length, 18)
  assert.ok(model.triangleCount > 1000)
  assert.deepEqual(bounds(model), { min: [-10, 0, -4], max: [190, 150, 80] })
  assert.ok(model.meshes.every((mesh) => mesh.color?.length === 3))
})

test('malformed STEP and non-finite/out-of-range mesh coordinates are rejected before rendering', () => {
  assert.throws(() => convert(occt.ReadStepFile(new TextEncoder().encode('not a CAD file'), triangulation)), { code: 'invalid_step' })
  const raw = { success: true, meshes: [{ attributes: { position: { array: [0, 0, 0, 1, 0, 0, 0, 1, 0] } }, index: { array: [0, 1, 2] } }] }
  raw.meshes[0].attributes.position.array[0] = NaN
  assert.throws(() => convert(raw), { code: 'invalid_step' })
  raw.meshes[0].attributes.position.array[0] = 0
  raw.meshes[0].index.array[2] = 3
  assert.throws(() => convert(raw), { code: 'invalid_step' })
})

test('cache deduplicates imports while one cancelled consumer does not cancel another', async () => {
  const controller = new AbortController()
  const input = bytes()
  const first = step.parseStep(input, { signal: controller.signal, cacheKey: 'same-content' })
  const firstRejection = assert.rejects(first, { name: 'AbortError' })
  const second = step.parseStep(input, { cacheKey: 'same-content' })
  const worker = workers.at(-1)
  assert.equal(worker.requests.length, 1)
  controller.abort()
  assert.equal(worker.terminated, false)
  const model = realModel('cube-fcstd/cube.step')
  worker.respond(model)
  await firstRejection
  assert.equal(await second, model)
  assert.equal(await step.parseStep(input, { cacheKey: 'same-content' }), model)
  assert.equal(worker.requests.length, 1)
  assert.ok(input.byteLength, 'input ownership remains with the caller')
})

test('cancelling the last consumer kills native work and a subsequent import starts cleanly', async () => {
  const controller = new AbortController()
  const pending = step.parseStep(bytes(), { signal: controller.signal })
  const failed = assert.rejects(pending, { name: 'AbortError' })
  const worker = workers.at(-1)
  controller.abort()
  await failed
  assert.equal(worker.terminated, true)
  const next = step.parseStep(bytes())
  const fresh = workers.at(-1)
  assert.notEqual(fresh, worker)
  worker.onerror({ preventDefault() {} })
  assert.equal(fresh.terminated, false, 'a stale failure event cannot terminate the replacement worker')
  const model = realModel('cube-fcstd/cube.step')
  fresh.respond(model)
  assert.equal(await next, model)
})

test('cancelled queued work is never sent to the worker', async () => {
  const active = step.parseStep(bytes())
  const controller = new AbortController()
  const queued = step.parseStep(bytes(), { signal: controller.signal })
  const failure = assert.rejects(queued, { name: 'AbortError' })
  const worker = workers.at(-1), requests = worker.requests.length
  controller.abort()
  worker.respond(realModel('cube-fcstd/cube.step'))
  await active
  await failure
  assert.equal(worker.requests.length, requests)
})

test('worker crashes reject only that import and leave subsequent imports usable', async () => {
  const pending = step.parseStep(bytes())
  const failure = assert.rejects(pending, { code: 'parser_unavailable' })
  const worker = workers.at(-1)
  worker.onerror({ preventDefault() {} })
  await failure
  assert.equal(worker.terminated, true)
  const next = step.parseStep(bytes())
  const fresh = workers.at(-1)
  assert.notEqual(fresh, worker)
  fresh.respond(realModel('cube-fcstd/cube.step'))
  assert.equal((await next).triangleCount, 12)
})

test('empty and oversized data and pre-aborted requests fail without creating a worker', async () => {
  const count = workers.length
  await assert.rejects(step.parseStep(new ArrayBuffer(0)), { code: 'invalid_step' })
  await assert.rejects(step.parseStep(new ArrayBuffer(step.MAX_STEP_BYTES + 1)), { code: 'too_large' })
  await assert.rejects(step.parseStep(bytes(), { signal: AbortSignal.abort() }), { name: 'AbortError' })
  assert.equal(workers.length, count)
})

test('a hung native import times out and the queued model runs on a fresh worker', async (context) => {
  // Clear the real idle timer before enabling the scoped virtual clock.
  const reset = new AbortController()
  const resetTask = step.parseStep(bytes(), { signal: reset.signal })
  reset.abort()
  await assert.rejects(resetTask, { name: 'AbortError' })
  context.mock.timers.enable({ apis: ['setTimeout'] })
  const hung = step.parseStep(bytes())
  const failure = assert.rejects(hung, { code: 'timeout' })
  const old = workers.at(-1)
  const next = step.parseStep(bytes())
  context.mock.timers.tick(90_001)
  await failure
  assert.equal(old.terminated, true)
  const fresh = workers.at(-1)
  assert.notEqual(fresh, old)
  fresh.respond(realModel('cube-fcstd/cube.step'))
  assert.equal((await next).triangleCount, 12)
  context.mock.timers.tick(30_001)
  assert.equal(fresh.terminated, true)
})
