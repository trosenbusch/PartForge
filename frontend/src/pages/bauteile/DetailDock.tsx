import { useI18n } from '@/lib/i18n'
/**
 * Platz für den Detailbereich rechts neben der Tabelle: schiebt die Tabelle zur Seite (genug Breite) oder liegt
 * darüber (schmales Fenster). Breite per Ziehen oder Pfeiltasten am linken Rand, gespeichert.
 */
import { AnimatePresence, motion } from 'motion/react'
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export const DETAIL_MIN = 360
export const DETAIL_MAX = 680
/** Mindestbreite der Tabelle neben dem Detailbereich (Teilenummer, Hauptwert, Beschreibung) – darunter liegt der
 * Bereich über der Tabelle */
const GRID_MIN = 560

export function DetailDock({
  open,
  width,
  onWidthChange,
  main,
  panel,
}: {
  open: boolean
  width: number
  onWidthChange: (width: number) => void
  main: ReactNode
  panel: ReactNode
}) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)
  const [dragWidth, setDragWidth] = useState<number | null>(null)
  const drag = useRef<{ x: number; w: number } | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setContainerWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const max = Math.max(DETAIL_MIN, Math.min(DETAIL_MAX, containerWidth - 120))
  const clamp = (w: number) => Math.round(Math.max(DETAIL_MIN, Math.min(max, w)))
  const w = clamp(dragWidth ?? width)
  const overlay = containerWidth > 0 && containerWidth - w < GRID_MIN

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, w }
    setDragWidth(w)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    setDragWidth(clamp(drag.current.w + (drag.current.x - e.clientX)))
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // ignorieren
    }
    if (dragWidth !== null) onWidthChange(dragWidth)
    setDragWidth(null)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16
    if (e.key === 'ArrowLeft') onWidthChange(clamp(w + step))
    else if (e.key === 'ArrowRight') onWidthChange(clamp(w - step))
    else if (e.key === 'Home') onWidthChange(DETAIL_MIN)
    else if (e.key === 'End') onWidthChange(max)
    else return
    e.preventDefault()
  }

  const dragging = dragWidth !== null
  const spring = { type: 'spring' as const, stiffness: 420, damping: 36 }
  return (
    <div ref={containerRef} className={cn('relative flex min-h-0 min-w-0 flex-1', dragging && 'select-none')}>
      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">{main}</div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            key="detail"
            className={cn('flex min-h-0 overflow-hidden', overlay ? 'absolute inset-y-0 right-0 z-sticky' : 'relative shrink-0')}
            initial={overlay ? { opacity: 0, x: 28 } : { width: 0, opacity: 0, x: 0 }}
            // Ziel immer mit x: 0 – wechselt der Modus während des Einblendens (Klick auf eine Teilenummer klappt den
            // Kategoriebaum ein, dann reicht der Platz neben der Tabelle), bliebe die Verschiebung sonst mitten in der
            // Feder stehen und das Panel rechts abgeschnitten
            animate={{ opacity: 1, x: 0, width: w }}
            exit={overlay ? { opacity: 0, x: 28 } : { width: 0, opacity: 0 }}
            transition={dragging ? { duration: 0 } : spring}
          >
            <div
              role="separator"
              tabIndex={0}
              aria-orientation="vertical"
              aria-label={t("Breite des Detailbereichs")}
              aria-valuenow={w}
              aria-valuemin={DETAIL_MIN}
              aria-valuemax={max}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
              onDoubleClick={() => onWidthChange(432)}
              onKeyDown={onKeyDown}
              className="group/handle relative z-sticky w-3 shrink-0 cursor-col-resize outline-none"
            >
              <span
                aria-hidden
                className={cn(
                  'absolute inset-y-6 left-1/2 w-[3px] -translate-x-1/2 rounded-full bg-accent opacity-0 shadow-[0_0_10px_var(--pf-glow-indicator)] transition-opacity',
                  'group-hover/handle:opacity-50 group-focus-visible/handle:opacity-100',
                  dragging && 'opacity-100',
                )}
              />
            </div>
            <div
              className={cn('flex min-h-0 min-w-0 flex-col', overlay && 'rounded-card shadow-pop')}
              style={{ width: w - 12 }}
            >
              {panel}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
