import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * 3D-Vorschau eines Footprints mit STEP-Modellen und `FootprintSpec.bodies`, Leiterplatte, Pads und Druck.
 * three.js wird **lazy** nachgeladen (eigener Chunk `vendor-3d`). Ohne WebGL – oder wenn der Kontext verloren geht –
 * erscheint eine isometrische SVG-Zeichnung mit Hinweis.
 *
 *   <Package3D spec={spec} autoRotate={rotate} onAutoRotateChange={setRotate} ref={handle} />
 */
import { Box, Download, RefreshCw, TriangleAlert } from 'lucide-react'
import { Component, lazy, Suspense, useState, type ErrorInfo, type ReactNode, type Ref } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { stepModelsApi, type StepModelFile, type StepSource } from '@/api/stepModels'
import { Button, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { FILE_TYPES, notifySaveResult, saveFile } from '@/lib/download'
import type { FootprintSpec } from '@/lib/geometry'
import { localizeMessage } from '@/lib/i18n'
import { StepImportError } from '@/lib/stepTypes'
import { IsoFallback } from './IsoFallback'
import type { CanvasHandle } from './types'
import { useStepModels } from './useStepModels'
import { isWebGLAvailable } from './webgl'

const Package3DScene = lazy(() => import('./Package3DScene'))

export interface Package3DProps {
  spec: FootprintSpec | null | undefined
  /** Registered source; omitted for unsaved generator previews. */
  stepSource?: StepSource
  /** Automatische Drehung (kontrolliert) */
  autoRotate?: boolean
  onAutoRotateChange?: (on: boolean) => void
  /** Leiterplatte mit Pads und Bestückungsdruck (Standard: an) */
  showBoard?: boolean
  showInfo?: boolean
  className?: string
  'aria-label'?: string
  /** fit() = Ansicht zurücksetzen, zoomIn/zoomOut */
  ref?: Ref<CanvasHandle>
}

class SceneBoundary extends Component<{ onError: (error: Error) => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn(tr('3D-Vorschau fehlgeschlagen'), error, info.componentStack)
    this.props.onError(error)
  }
  render() {
    return this.state.failed ? null : this.props.children
  }
}

function Loading({ className }: { className?: string }) {
  useI18n()
  return (
    <div
      className={cn(
        'relative flex min-h-0 items-center justify-center bg-[radial-gradient(120%_90%_at_50%_35%,#121a26_0%,#080b10_55%,#05070a_100%)]',
        className,
      )}
    >
      <div className="flex items-center gap-2.5 rounded-full border border-white/10 bg-white/5 px-3.5 py-1.5 text-xs text-[#C9D1DE]">
        <Spinner size={14} tone="accent" label={tr("3D-Ansicht wird geladen")} />
        {tr("3D‑Ansicht wird geladen …")}
      </div>
    </div>
  )
}

function stepError(error: unknown): string {
  if (error instanceof StepImportError) {
    switch (error.code) {
      case 'invalid_step': return tr('Die STEP-Datei enthält keine darstellbare 3D-Geometrie oder ist beschädigt.')
      case 'too_large': return tr('Das STEP-Modell ist zu groß oder zu komplex für die Vorschau.')
      case 'parser_unavailable': return tr('Der STEP-Lader konnte nicht gestartet werden. Bitte die Ansicht erneut laden.')
      case 'timeout': return tr('Das Laden des STEP-Modells hat zu lange gedauert.')
      case 'busy': return tr('Es werden bereits andere STEP-Modelle geladen. Bitte erneut versuchen.')
    }
  }
  return errorMessage(error).split('\n').map(localizeMessage).join('\n')
}

function StepDownloads({ files }: { files: readonly StepModelFile[] }) {
  useI18n()
  const [busy, setBusy] = useState<string | null>(null)
  const download = async (file: StepModelFile) => {
    setBusy(file.id)
    try {
      const result = await saveFile({ suggestedName: file.name, type: FILE_TYPES.step, load: () => stepModelsApi.file(file.url) })
      notifySaveResult(result, { what: tr('STEP-Modell') })
    } catch (error) {
      toast.error(tr('STEP-Modell nicht verfügbar'), { description: errorMessage(error) })
    } finally { setBusy(null) }
  }
  if (!files.length) return null
  return (
    <details className="absolute bottom-3 right-3 z-30 max-w-[min(22rem,90%)] rounded-control border border-white/15 bg-[#0d111bd9] p-2 text-xs text-[#D5DBE6] backdrop-blur">
      <summary className="cursor-pointer rounded-sm px-1 outline-none focus-ring">{tr('STEP-Dateien')} ({files.length})</summary>
      <div className="mt-2 flex max-h-40 flex-col gap-1 overflow-y-auto">
        {files.map((file) => (
          <Button key={file.id} size="sm" variant="ghost" leftIcon={<Download />} loading={busy === file.id}
            disabled={busy !== null && busy !== file.id} onClick={() => void download(file)} className="justify-start text-[#D5DBE6]">
            <span className="truncate" title={file.name}>{file.name}</span>
          </Button>
        ))}
      </div>
    </details>
  )
}

export function Package3D({ spec, stepSource, className, ...props }: Package3DProps) {
  useI18n()
  const [supported] = useState(isWebGLAvailable)
  const step = useStepModels(stepSource, supported)
  const sceneKey = `${stepSource?.name ?? spec?.name}:${stepSource?.revision ?? ''}:${step.dataUpdatedAt}`
  const [failure, setFailure] = useState<{ key: string; message: string } | null>(null)
  const sceneFailure = failure?.key === sceneKey ? failure.message : null
  const models = step.data?.models ?? []
  const files = step.data?.files ?? []
  const bodies = (spec?.bodies ?? []).length
  const loading = Boolean(stepSource && step.isFetching)
  const messages = [
    ...(step.error ? [stepError(step.error)] : []),
    ...(step.data?.warnings ?? []).map((message) => message.split('\n').map(localizeMessage).join('\n')),
    ...(step.data?.failures ?? []).map(({ name, error }) => `${name}: ${stepError(error)}`),
  ]
  const hasGeometry = Boolean(spec && (bodies || models.length))
  const fallback = !supported || Boolean(sceneFailure)
  const status = loading ? 'loading' : messages.length || sceneFailure ? 'error' : hasGeometry ? 'ready' : 'empty'

  return (
    <div className={cn('relative min-h-0 bg-canvas', className)} data-step-status={status} aria-busy={loading}>
      {hasGeometry && spec && !fallback && (
        <SceneBoundary key={sceneKey} onError={() => setFailure({ key: sceneKey, message: 'Die 3D-Darstellung ist fehlgeschlagen.' })}>
          <Suspense fallback={<Loading className="absolute inset-0" />}>
            <Package3DScene {...props} spec={spec} stepModels={models} className="absolute inset-0"
              onContextLost={() => setFailure({ key: sceneKey, message: 'Der Grafiktreiber hat die 3D-Darstellung beendet.' })} />
          </Suspense>
        </SceneBoundary>
      )}
      {fallback && spec && bodies > 0 && <IsoFallback spec={spec} className="absolute inset-0" />}
      {loading && (
        <div role="status" className={cn('pointer-events-none absolute z-20 flex items-center gap-2 rounded-control bg-[#0d111be6] px-3 py-2 text-xs text-[#D5DBE6]', hasGeometry ? 'left-3 top-3' : 'left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2')}>
          <Spinner size={14} tone="accent" /> {tr('STEP-Modelle werden geladen …')}
        </div>
      )}
      {!loading && !hasGeometry && !messages.length && !fallback && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center text-ui text-[#C9D1DE]">
          <Box aria-hidden className="size-6 text-[#9AA4B6]" />
          <p>{tr('Für diesen Footprint sind keine 3D-Körper oder STEP-Modelle hinterlegt.')}</p>
        </div>
      )}
      {(messages.length > 0 || fallback) && (
        <div role={messages.length || sceneFailure ? 'alert' : 'status'} className="absolute left-3 right-3 top-3 z-20 max-h-[65%] overflow-y-auto rounded-control border border-white/15 bg-[#0d111be6] p-3 text-xs text-[#D5DBE6] backdrop-blur">
          <div className="flex items-center gap-2 font-semibold text-white"><TriangleAlert aria-hidden className="size-4 shrink-0" />
            {fallback ? tr('3D-Ansicht nicht verfügbar') : models.length || bodies ? tr('Nicht alle STEP-Modelle konnten geladen werden') : tr('STEP-Modell konnte nicht geladen werden')}
          </div>
          {fallback && <p className="mt-1">{sceneFailure ? tr(sceneFailure) : tr('WebGL ist nicht verfügbar. STEP-Dateien können heruntergeladen und in einem CAD-Viewer geöffnet werden.')}</p>}
          {messages.map((message, index) => <p key={index} className="mt-1 whitespace-pre-wrap break-words">{message}</p>)}
          {stepSource && <Button size="sm" variant="secondary" className="mt-2" leftIcon={<RefreshCw />} loading={loading}
            onClick={() => { setFailure(null); void step.refetch() }}>{tr('Erneut versuchen')}</Button>}
        </div>
      )}
      <StepDownloads files={files} />
    </div>
  )
}
