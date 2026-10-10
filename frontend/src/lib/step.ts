import {
  MAX_STEP_BYTES, StepImportError,
  type StepModel, type StepWorkerRequest, type StepWorkerResponse,
} from './stepTypes'

export { MAX_STEP_BYTES, StepImportError } from './stepTypes'
export type { StepMesh, StepModel, StepColor, StepErrorCode } from './stepTypes'

const CACHE_LIMIT = 64 * 1024 * 1024
const CACHE_ENTRIES = 12
const QUEUE_BYTES_LIMIT = 128 * 1024 * 1024
const PARSE_TIMEOUT_MS = 90_000
const IDLE_TIMEOUT_MS = 30_000

interface Consumer {
  resolve(model: StepModel): void
  reject(error: Error): void
  cleanup(): void
}

interface Task {
  id: number
  key?: string
  bytes: ArrayBuffer
  consumers: Set<Consumer>
}

const cache = new Map<string, StepModel>()
const pending = new Map<string, Task>()
const queue: Task[] = []
let cacheBytes = 0
let queuedBytes = 0
let nextId = 0
let worker: Worker | undefined
let active: Task | undefined
let timeout: ReturnType<typeof setTimeout> | undefined
let idle: ReturnType<typeof setTimeout> | undefined
let workerParses = 0

const abortError = () => new DOMException('Aborted', 'AbortError')

function stopWorker() {
  clearTimeout(timeout)
  clearTimeout(idle)
  worker?.terminate()
  worker = undefined
  workerParses = 0
}

function remember(key: string, model: StepModel) {
  if (model.byteLength > CACHE_LIMIT) return
  cache.set(key, model)
  cacheBytes += model.byteLength
  while (cacheBytes > CACHE_LIMIT || cache.size > CACHE_ENTRIES) {
    const oldest = cache.keys().next().value
    if (oldest === undefined) break
    cacheBytes -= cache.get(oldest)!.byteLength
    cache.delete(oldest)
  }
}

function finish(error?: Error, model?: StepModel) {
  const task = active
  if (!task) return
  clearTimeout(timeout)
  active = undefined
  if (task.key) pending.delete(task.key)
  if (task.key && model) remember(task.key, model)
  for (const consumer of task.consumers) {
    consumer.cleanup()
    if (model) consumer.resolve(model)
    else consumer.reject(error ?? new StepImportError('invalid_step'))
  }
  task.consumers.clear()
  // Recycle native memory periodically even when models are opened continuously.
  if (++workerParses >= 8) stopWorker()
  pump()
}

function pump() {
  if (active) return
  clearTimeout(idle)
  const task = queue.shift()
  if (!task) {
    if (worker) idle = setTimeout(stopWorker, IDLE_TIMEOUT_MS)
    return
  }
  queuedBytes -= task.bytes.byteLength
  active = task
  try {
    if (!worker) {
      worker = new Worker(new URL('./step.worker.ts', import.meta.url), { type: 'module', name: 'partforge-step' })
      const createdWorker = worker
      worker.onmessage = ({ data }: MessageEvent<StepWorkerResponse>) => {
        if (worker !== createdWorker || data.id !== active?.id) return
        if ('model' in data) finish(undefined, data.model)
        else {
          // A failed import may leave native state unusable; retries start clean.
          stopWorker()
          finish(new StepImportError(data.error))
        }
      }
      worker.onerror = (event) => {
        event.preventDefault()
        if (worker !== createdWorker) return
        stopWorker()
        finish(new StepImportError('parser_unavailable'))
      }
      worker.onmessageerror = () => {
        if (worker !== createdWorker) return
        stopWorker()
        finish(new StepImportError('parser_unavailable'))
      }
    }
    timeout = setTimeout(() => {
      stopWorker()
      finish(new StepImportError('timeout'))
    }, PARSE_TIMEOUT_MS)
    const request: StepWorkerRequest = { id: task.id, bytes: task.bytes }
    worker.postMessage(request, [task.bytes])
  } catch {
    stopWorker()
    finish(new StepImportError('parser_unavailable'))
  }
}

/**
 * Tessellate STEP off the UI thread. Input buffers remain owned by the caller.
 * Use a content digest as cacheKey (never a path or an authentication token).
 * Concurrent consumers share parsing; the last abort terminates native work.
 */
export function parseStep(bytes: ArrayBuffer, options: { signal?: AbortSignal; cacheKey?: string } = {}): Promise<StepModel> {
  const { signal, cacheKey } = options
  if (signal?.aborted) return Promise.reject(abortError())
  if (!bytes.byteLength) return Promise.reject(new StepImportError('invalid_step'))
  if (bytes.byteLength > MAX_STEP_BYTES) return Promise.reject(new StepImportError('too_large'))
  const cached = cacheKey ? cache.get(cacheKey) : undefined
  if (cached) {
    cache.delete(cacheKey!)
    cache.set(cacheKey!, cached)
    return Promise.resolve(cached)
  }
  let task = cacheKey ? pending.get(cacheKey) : undefined
  if (!task) {
    if (queue.length >= 32 || queuedBytes + bytes.byteLength > QUEUE_BYTES_LIMIT) return Promise.reject(new StepImportError('busy'))
    task = { id: ++nextId, key: cacheKey, bytes: bytes.slice(0), consumers: new Set() }
    if (cacheKey) pending.set(cacheKey, task)
    queue.push(task)
    queuedBytes += task.bytes.byteLength
  }
  const subscribedTask = task
  return new Promise<StepModel>((resolve, reject) => {
    const consumer: Consumer = {
      resolve, reject,
      cleanup: () => signal?.removeEventListener('abort', onAbort),
    }
    function onAbort() {
      consumer.cleanup()
      subscribedTask.consumers.delete(consumer)
      reject(abortError())
      if (subscribedTask.consumers.size) return
      if (subscribedTask.key) pending.delete(subscribedTask.key)
      if (active === subscribedTask) {
        stopWorker()
        active = undefined
        pump()
      } else {
        const index = queue.indexOf(subscribedTask)
        if (index >= 0) {
          queue.splice(index, 1)
          queuedBytes -= subscribedTask.bytes.byteLength
        }
      }
    }
    subscribedTask.consumers.add(consumer)
    signal?.addEventListener('abort', onAbort, { once: true })
    pump()
  })
}
