import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * 3D-Vorschau eines Footprints (Gehäuse aus `FootprintSpec.bodies` auf einer Leiterplatte mit Pads und Druck).
 * three.js wird **lazy** nachgeladen (eigener Chunk `vendor-3d`). Ohne WebGL – oder wenn der Kontext verloren geht –
 * erscheint eine isometrische SVG-Zeichnung mit Hinweis.
 *
 *   <Package3D spec={spec} autoRotate={rotate} onAutoRotateChange={setRotate} ref={handle} />
 */
import { Box } from 'lucide-react'
import { Component, lazy, Suspense, useState, type ErrorInfo, type ReactNode, type Ref } from 'react'
import { Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { FootprintSpec } from '@/lib/geometry'
import { IsoFallback } from './IsoFallback'
import type { CanvasHandle } from './types'
import { isWebGLAvailable } from './webgl'

const Package3DScene = lazy(() => import('./Package3DScene'))

export interface Package3DProps {
  spec: FootprintSpec | null | undefined
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

export function Package3D({ spec, className, ...props }: Package3DProps) {
  useI18n()
  const [supported] = useState(isWebGLAvailable)
  const [failure, setFailure] = useState<string | null>(null)

  if (!spec || !(spec.bodies ?? []).length) {
    return (
      <div className={cn('relative flex min-h-0 flex-col items-center justify-center gap-3 bg-canvas text-center', className)}>
        <span className="flex size-11 items-center justify-center rounded-card border border-white/10 bg-white/5 text-[#9AA4B6] [&_svg]:size-5">
          <Box aria-hidden />
        </span>
        <div className="max-w-64 text-ui text-[#C9D1DE]">{tr("Für diesen Footprint sind keine 3D‑Körper hinterlegt.")}</div>
      </div>
    )
  }

  if (!supported || failure) {
    return (
      <div className={cn('relative min-h-0', className)}>
        <IsoFallback spec={spec} className="absolute inset-0" />
        <div className="absolute left-3 top-3 z-10 max-w-80 rounded-control border border-white/10 bg-[rgba(13,17,24,0.86)] px-3 py-2 text-xs leading-snug text-[#D5DBE6] backdrop-blur-md">
          <div className="font-semibold text-white">{tr("Vereinfachte Ansicht")}</div>
          {failure ?? tr('WebGL ist in diesem Fenster nicht verfügbar – die Körper werden isometrisch gezeichnet.')}
        </div>
      </div>
    )
  }

  return (
    <SceneBoundary onError={() => setFailure(tr('Die 3D‑Darstellung ist fehlgeschlagen – die Körper werden isometrisch gezeichnet.'))}>
      <Suspense fallback={<Loading className={className} />}>
        <Package3DScene
          spec={spec}
          className={className}
          onContextLost={() => setFailure(tr('Der Grafiktreiber hat die 3D‑Darstellung beendet – die Körper werden isometrisch gezeichnet.'))}
          {...props}
        />
      </Suspense>
    </SceneBoundary>
  )
}
