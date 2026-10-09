/**
 * Bausteine für Overlays auf den Vorschau-Leinwänden: Tooltip am Objekt, schwebende Zoom-Steuerung, Infozeilen.
 * „board“-Ton = immer dunkel (Leiterplatte und 3D sind in beiden Themes dunkel), „app“ = folgt dem Theme.
 */
import { Minus, Plus, Scan } from 'lucide-react'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { CHROME_MUTED, CHROME_SURFACE } from './chrome'
import type { ChromeTone } from './types'

export interface CanvasTooltipProps {
  /** Ankerpunkt in Pixeln relativ zur Leinwand (z. B. Mitte des Pads) */
  x: number
  y: number
  /** Größe der Leinwand (zum Begrenzen) */
  bounds: { width: number; height: number }
  /** Abstand zum Anker */
  offset?: number
  tone?: ChromeTone
  children: ReactNode
  className?: string
}

/** Tooltip an einem Objekt der Leinwand: bevorzugt oberhalb, sonst unterhalb; bleibt innerhalb der Leinwand. */
export function CanvasTooltip({ x, y, bounds, offset = 12, tone = 'app', children, className }: CanvasTooltipProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })
  // Größe messen (ResizeObserver: auch wenn sich der Inhalt ändert)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const w = el.offsetWidth
      const h = el.offsetHeight
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const margin = 8
  let left = x - size.w / 2
  left = Math.max(margin, Math.min(left, bounds.width - size.w - margin))
  let top = y - offset - size.h
  if (top < margin) top = Math.min(y + offset, bounds.height - size.h - margin)
  return (
    <div
      ref={ref}
      aria-hidden
      className={cn(
        'pointer-events-none absolute left-0 top-0 z-10 min-w-36 max-w-72 rounded-control px-2.5 py-2 text-xs leading-snug',
        CHROME_SURFACE[tone],
        size.w === 0 && 'opacity-0',
        className,
      )}
      style={{ transform: `translate(${Math.round(left)}px, ${Math.round(top)}px)` }}
    >
      {children}
    </div>
  )
}

export interface CanvasZoomControlsProps {
  onZoomIn: () => void
  onZoomOut: () => void
  onFit: () => void
  zoom?: number
  tone?: ChromeTone
  className?: string
}

/** Schwebende Zoom-Steuerung (für Leinwände ohne PreviewPanel-Werkzeugleiste) */
export function CanvasZoomControls({ onZoomIn, onZoomOut, onFit, zoom, tone = 'app', className }: CanvasZoomControlsProps) {
  const btn = cn(
    'flex size-7 items-center justify-center rounded-[6px] outline-none transition-colors focus-ring [&_svg]:size-3.5',
    tone === 'board' ? 'hover:bg-white/10' : 'hover:bg-surface-3',
  )
  return (
    <div
      role="toolbar"
      aria-label="Ansicht"
      className={cn('absolute bottom-3 right-3 z-10 flex items-center gap-0.5 rounded-control p-0.5', CHROME_SURFACE[tone], className)}
    >
      <button type="button" className={btn} onClick={onZoomOut} aria-label="Verkleinern" title="Verkleinern (−)">
        <Minus />
      </button>
      {zoom !== undefined && (
        <span className={cn('mono w-11 text-center text-2xs tabular-nums', CHROME_MUTED[tone])} aria-live="off">
          {Math.round(zoom * 100)} %
        </span>
      )}
      <button type="button" className={btn} onClick={onZoomIn} aria-label="Vergrößern" title="Vergrößern (+)">
        <Plus />
      </button>
      <button type="button" className={btn} onClick={onFit} aria-label="Einpassen" title="Einpassen (0)">
        <Scan />
      </button>
    </div>
  )
}

/** Kleines Etikett auf der Leinwand (Name, Maße, Koordinaten) */
export function CanvasBadge({
  children,
  tone = 'app',
  className,
}: {
  children: ReactNode
  tone?: ChromeTone
  className?: string
}) {
  return (
    <div
      className={cn(
        'pointer-events-none flex h-7 items-center gap-2 rounded-control px-2.5 text-2xs leading-none',
        CHROME_SURFACE[tone],
        className,
      )}
    >
      {children}
    </div>
  )
}

/** Hinweis für Tastaturnutzer – erscheint nur, wenn die Leinwand per Tastatur fokussiert ist */
export function CanvasKeyHint({ children, tone = 'app' }: { children: ReactNode; tone?: ChromeTone }) {
  return (
    <div
      className={cn(
        'pointer-events-none absolute left-1/2 top-3 z-10 hidden -translate-x-1/2 whitespace-nowrap rounded-full px-3 py-1 text-2xs',
        'group-has-[:focus-visible]/canvas:block group-focus-visible/canvas:block',
        CHROME_SURFACE[tone],
      )}
    >
      {children}
    </div>
  )
}
