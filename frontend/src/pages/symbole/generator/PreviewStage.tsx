/**
 * Live-Vorschau des Generators: SymbolCanvas mit Teil-Reitern, Altium-Ansicht, verborgenen Pins, Zoom, Vollbild,
 * Status („berechnet …“), Fehlerkarte und Hinweisen des Generators. Die letzte gültige Vorschau bleibt sichtbar.
 */
import { EyeOff, Eye, Maximize2, Minus, Plus, Scan, Square, TriangleAlert } from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import type { GeneratedSpec } from '@/api/symbols'
import { SymbolCanvas, usePreviewPrefs, type CanvasHandle } from '@/components/preview'
import { Dialog, DialogContent, DialogHeader, IconButton, Spinner, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { SymPin } from '@/lib/geometry'
import { icBodySize } from '../util'

export interface PreviewStageProps {
  spec: GeneratedSpec | undefined
  fetching?: boolean
  error?: string | null
  warnings?: readonly string[]
  part: number
  onPartChange: (part: number) => void
  highlight?: readonly string[]
  hoverDesignator?: string | null
  onPinHover?: (pin: SymPin | null) => void
  onPinClick?: (pin: SymPin) => void
  /** Inhalt ohne Vorschau (z. B. leere Pinliste) */
  empty?: ReactNode
  /** Leiste unter der Leinwand (Name, Bibliotheksstatus) */
  footer?: ReactNode
  className?: string
}

function ToggleButton({
  pressed,
  onClick,
  label,
  tooltip,
  icon,
  compactLabel,
}: {
  pressed: boolean
  onClick: () => void
  label: string
  tooltip: string
  icon: ReactNode
  compactLabel?: boolean
}) {
  return (
    <Tooltip content={tooltip}>
      <button
        type="button"
        aria-label={label}
        aria-pressed={pressed}
        onClick={onClick}
        className={cn(
          'flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium text-fg-muted outline-none transition-colors focus-ring hover:bg-surface-2 hover:text-fg [&_svg]:size-3.5',
          pressed && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text',
        )}
      >
        {icon}
        {compactLabel !== false && <span className="hidden whitespace-nowrap @[30rem]:inline">{label}</span>}
      </button>
    </Tooltip>
  )
}

export function PreviewStage({
  spec,
  fetching,
  error,
  warnings = [],
  part,
  onPartChange,
  highlight,
  hoverDesignator,
  onPinHover,
  onPinClick,
  empty,
  footer,
  className,
}: PreviewStageProps) {
  const prefs = usePreviewPrefs()
  const canvasRef = useRef<CanvasHandle>(null)
  const fullRef = useRef<CanvasHandle>(null)
  const fullWrapRef = useRef<HTMLDivElement>(null)
  const [zoom, setZoom] = useState(1)
  const [showHidden, setShowHidden] = useState(true)
  const [fullscreen, setFullscreen] = useState(false)

  const hasHidden = Boolean(spec?.pins.some((p) => p.hidden))
  const body = icBodySize(spec)
  const resetKey = spec ? `${spec.name}|${part}|${spec.pins.length}|${spec.part_count}|${body ? `${body.width}x${body.height}` : ''}` : ''
  const theme = prefs.altium ? 'altium' : 'auto'

  const canvasProps = {
    spec,
    theme,
    part,
    onPartChange,
    highlight,
    hoverDesignator,
    onPinHover,
    onPinClick,
    showHiddenPins: showHidden,
    showInfo: false,
    resetKey,
    className: 'absolute inset-0',
  } as const

  const status = fetching ? (
    <span className="flex items-center gap-1.5 text-2xs text-fg-muted">
      <Spinner size={11} tone="accent" />
      berechnet …
    </span>
  ) : error ? (
    <span className="flex items-center gap-1.5 text-2xs text-danger-text">
      <span aria-hidden className="size-1.5 rounded-full bg-danger" />
      Fehler
    </span>
  ) : spec ? (
    <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">
      <span aria-hidden className="size-1.5 rounded-full bg-success shadow-[0_0_6px_var(--pf-success)]" />
      aktuell
    </span>
  ) : null

  const tools = (
    <>
      {hasHidden && (
        <ToggleButton
          pressed={showHidden}
          onClick={() => setShowHidden((v) => !v)}
          label="Verborgene Pins"
          tooltip={showHidden ? 'Verborgene Pins ausblenden' : 'Verborgene Pins gestrichelt zeigen'}
          icon={showHidden ? <Eye /> : <EyeOff />}
        />
      )}
      <ToggleButton
        pressed={prefs.altium}
        onClick={() => prefs.set({ altium: !prefs.altium })}
        label="Altium-Ansicht"
        tooltip={prefs.altium ? 'PartForge-Darstellung' : 'Wie in Altium Designer (weißes Blatt)'}
        icon={<Square className={cn(prefs.altium && 'fill-altium-body text-altium-line')} />}
      />
    </>
  )

  return (
    <section aria-label="Vorschau" className={cn('@container flex h-full min-h-0 flex-col bg-surface', className)}>
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-3">
        <h2 className="text-xs font-semibold text-fg">Vorschau</h2>
        {status}
        <div className="ml-auto flex items-center gap-0.5">
          {tools}
          <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
          <div className="hidden items-center gap-0.5 @[24rem]:flex">
            <IconButton size="sm" label="Verkleinern" icon={<Minus />} onClick={() => canvasRef.current?.zoomOut()} disabled={!spec} />
            <span className="mono w-10 text-center text-2xs tabular-nums text-fg-muted" aria-hidden>
              {Math.round(zoom * 100)} %
            </span>
            <IconButton size="sm" label="Vergrößern" icon={<Plus />} onClick={() => canvasRef.current?.zoomIn()} disabled={!spec} />
          </div>
          <IconButton size="sm" label="Einpassen" icon={<Scan />} onClick={() => canvasRef.current?.fit()} disabled={!spec} />
          <IconButton size="sm" label="Vollbild" icon={<Maximize2 />} onClick={() => setFullscreen(true)} disabled={!spec} />
        </div>
      </header>

      {warnings.length > 0 && (
        <div className="shrink-0 border-b border-line bg-[color-mix(in_oklab,var(--pf-warning)_6%,var(--pf-surface))] px-3 py-2" role="status">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-warning-text">
            <TriangleAlert aria-hidden className="size-3.5" />
            {warnings.length === 1 ? 'Hinweis des Generators' : `${warnings.length} Hinweise des Generators`}
          </div>
          <ul className="mt-1 max-h-24 space-y-0.5 overflow-y-auto pl-5 text-xs leading-snug text-fg-muted">
            {warnings.map((w) => (
              <li key={w} className="list-disc marker:text-fg-subtle">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="relative min-h-0 flex-1">
        <SymbolCanvas ref={canvasRef} {...canvasProps} controls={false} onZoomChange={setZoom} />
        {!spec && fetching && (
          <div className="absolute inset-0 flex items-center justify-center bg-bg">
            <div className="flex items-center gap-2 rounded-full border border-line bg-surface px-3.5 py-1.5 text-xs text-fg-muted">
              <Spinner size={14} tone="accent" />
              Vorschau wird berechnet …
            </div>
          </div>
        )}
        {!spec && !fetching && !error && empty && <div className="absolute inset-0 bg-bg">{empty}</div>}
        {error && (
          <div
            className={cn(
              'absolute inset-0 z-20 flex items-center justify-center p-6',
              spec ? 'bg-[color-mix(in_oklab,var(--pf-bg)_62%,transparent)] backdrop-blur-[2px]' : 'bg-bg',
            )}
          >
            <div role="alert" className="flex max-w-sm items-start gap-2.5 rounded-card border border-danger/30 bg-surface px-4 py-3 shadow-raised">
              <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger-text" />
              <div className="min-w-0">
                <div className="text-ui font-semibold text-fg">Vorschau nicht möglich</div>
                <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{error}</p>
                {spec && <p className="mt-1.5 text-2xs text-fg-subtle">Darunter: die letzte gültige Vorschau.</p>}
              </div>
            </div>
          </div>
        )}
      </div>

      {footer}

      <Dialog open={fullscreen} onOpenChange={setFullscreen}>
        <DialogContent
          size="full"
          aria-describedby={undefined}
          onOpenAutoFocus={(e) => {
            // Fokus auf die Leinwand (nicht auf einen Knopf mit Tooltip – sonst schließt Esc erst den Tooltip)
            const canvas = fullWrapRef.current?.querySelector<HTMLElement>('[role="application"]')
            if (canvas) {
              e.preventDefault()
              canvas.focus()
            }
          }}
        >
          <DialogHeader title={spec?.name ?? 'Vorschau'} />
          <div className="flex items-center justify-end gap-0.5 px-6 pb-2">
            {tools}
            <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
            <IconButton size="sm" label="Einpassen" icon={<Scan />} onClick={() => fullRef.current?.fit()} />
          </div>
          <div ref={fullWrapRef} className="relative mx-6 mb-6 min-h-0 flex-1 overflow-hidden rounded-card border border-line">
            {fullscreen && <SymbolCanvas ref={fullRef} {...canvasProps} controls />}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  )
}
