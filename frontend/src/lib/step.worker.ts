import createImporter from 'occt-import-js'
import wasmUrl from 'occt-import-js/dist/occt-import-js.wasm?url'
import { stepModelFromOcct } from './stepMesh'
import { MAX_STEP_BYTES, StepImportError, type OcctImporter, type StepWorkerRequest, type StepWorkerResponse } from './stepTypes'

// Worker globals are structurally declared to keep the main DOM lib separate
// from lib.webworker (including both creates conflicting global declarations).
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<StepWorkerRequest>) => void) | null
  postMessage(message: StepWorkerResponse, transfer?: Transferable[]): void
}

let importer: Promise<OcctImporter> | undefined

scope.onmessage = async ({ data: { id, bytes } }) => {
  try {
    if (!bytes.byteLength) throw new StepImportError('invalid_step')
    if (bytes.byteLength > MAX_STEP_BYTES) throw new StepImportError('too_large')
    importer ??= createImporter({
      // Vite emits the WASM alongside this worker. Never fetch from a CDN.
      locateFile: () => wasmUrl,
      // Parser diagnostics can contain model names; expose only stable errors.
      print: () => {},
      printErr: () => {},
    }).catch(() => { throw new StepImportError('parser_unavailable') })
    const occt = await importer
    const result = occt.ReadStepFile(new Uint8Array(bytes), {
      linearUnit: 'millimeter',
      linearDeflectionType: 'bounding_box_ratio',
      linearDeflection: 0.001,
      angularDeflection: 0.25,
    })
    const model = stepModelFromOcct(result)
    const transfer: Transferable[] = []
    for (const mesh of model.meshes) {
      transfer.push(mesh.positions.buffer, mesh.indices.buffer)
      if (mesh.normals) transfer.push(mesh.normals.buffer)
    }
    scope.postMessage({ id, model }, transfer)
  } catch (error) {
    scope.postMessage({ id, error: error instanceof StepImportError ? error.code : 'invalid_step' })
  }
}
