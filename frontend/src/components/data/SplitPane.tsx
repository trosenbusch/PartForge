import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { readPref, writePref } from '@/lib/prefs'

export interface SplitPaneProps {
  start: ReactNode
  end: ReactNode
  /** horizontal = nebeneinander (Trenner senkrecht), vertical = übereinander */
  direction?: 'horizontal' | 'vertical'
  /** Bereich mit fester Größe (der andere füllt den Rest) */
  primary?: 'start' | 'end'
  defaultSize?: number
  minSize?: number
  maxSize?: number
  /** Mindestgröße des anderen Bereichs */
  minRest?: number
  /** Größe dauerhaft speichern unter diesem Schlüssel */
  persistKey?: string
  /** Primären Bereich per Doppelklick/Enter ein- und ausklappen */
  collapsible?: boolean
  collapsed?: boolean
  onCollapsedChange?: (collapsed: boolean) => void
  onSizeChange?: (size: number) => void
  /** Beschriftung des Trenners (Screenreader) */
  label?: string
  className?: string
  startClassName?: string
  endClassName?: string
}

export function SplitPane({
  start,
  end,
  direction = 'horizontal',
  primary = 'start',
  defaultSize = 280,
  minSize = 160,
  maxSize = 640,
  minRest = 240,
  persistKey,
  collapsible = false,
  collapsed: collapsedProp,
  onCollapsedChange,
  onSizeChange,
  label = tr("Bereichsgröße"),
  className,
  startClassName,
  endClassName,
}: SplitPaneProps) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const prefKey = persistKey ? `pf-split:${persistKey}` : null
  const [size, setSize] = useState(() => {
    const stored = prefKey ? Number(readPref(prefKey)) : NaN
    return Number.isFinite(stored) && stored > 0 ? stored : defaultSize
  })
  const [innerCollapsed, setInnerCollapsed] = useState(false)
  const collapsed = collapsible && (collapsedProp ?? innerCollapsed)
  const setCollapsed = (c: boolean) => {
    if (collapsedProp === undefined) setInnerCollapsed(c)
    onCollapsedChange?.(c)
  }
  const [dragging, setDragging] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const drag = useRef<{ startPos: number; startSize: number } | null>(null)
  const horizontal = direction === 'horizontal'

  const clamp = useCallback(
    (value: number) => {
      const total = containerRef.current ? (horizontal ? containerRef.current.clientWidth : containerRef.current.clientHeight) : Infinity
      const hi = Math.min(maxSize, total - minRest)
      return Math.round(Math.max(minSize, Math.min(hi, value)))
    },
    [horizontal, maxSize, minRest, minSize],
  )

  const commit = useCallback(
    (value: number) => {
      const v = clamp(value)
      setSize(v)
      onSizeChange?.(v)
      if (prefKey) writePref(prefKey, String(v))
    },
    [clamp, onSizeChange, prefKey],
  )

  // Fenstergröße ändert sich → Größe in den erlaubten Bereich holen
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize((s) => clamp(s)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [clamp])

  const sign = primary === 'start' ? 1 : -1
  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0 || collapsed) return
    e.preventDefault()
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { startPos: horizontal ? e.clientX : e.clientY, startSize: size }
    setDragging(true)
  }
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d) return
    const delta = ((horizontal ? e.clientX : e.clientY) - d.startPos) * sign
    setSize(clamp(d.startSize + delta))
  }
  const onPointerUp = (e: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return
    drag.current = null
    setDragging(false)
    try {
      e.currentTarget.releasePointerCapture(e.pointerId)
    } catch {
      // ignorieren
    }
    commit(size)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 64 : 16
    const grow = horizontal ? (primary === 'start' ? 'ArrowRight' : 'ArrowLeft') : primary === 'start' ? 'ArrowDown' : 'ArrowUp'
    const shrink = horizontal ? (primary === 'start' ? 'ArrowLeft' : 'ArrowRight') : primary === 'start' ? 'ArrowUp' : 'ArrowDown'
    if (e.key === grow) {
      e.preventDefault()
      if (collapsed) setCollapsed(false)
      else commit(size + step)
    } else if (e.key === shrink) {
      e.preventDefault()
      if (!collapsed) commit(size - step)
    } else if (e.key === 'Home') {
      e.preventDefault()
      commit(minSize)
    } else if (e.key === 'End') {
      e.preventDefault()
      commit(maxSize)
    } else if (e.key === 'Enter' && collapsible) {
      e.preventDefault()
      setCollapsed(!collapsed)
    }
  }

  const primaryStyle = collapsed ? { [horizontal ? 'width' : 'height']: 0 } : { [horizontal ? 'width' : 'height']: size }
  const primaryPane = (
    <div
      id={`${uid}-primary`}
      className={cn(
        'relative min-h-0 min-w-0 shrink-0 overflow-hidden',
        !dragging && 'transition-[width,height] duration-200 ease-out motion-reduce:transition-none',
        primary === 'start' ? startClassName : endClassName,
      )}
      style={primaryStyle}
      hidden={collapsed || undefined}
    >
      {primary === 'start' ? start : end}
    </div>
  )
  const restPane = (
    <div className={cn('relative min-h-0 min-w-0 flex-1 overflow-hidden', primary === 'start' ? endClassName : startClassName)}>
      {primary === 'start' ? end : start}
    </div>
  )

  return (
    <div
      ref={containerRef}
      className={cn('flex min-h-0 min-w-0', horizontal ? 'flex-row' : 'flex-col', dragging && 'select-none', className)}
    >
      {primary === 'start' ? primaryPane : restPane}
      <div
        role="separator"
        tabIndex={0}
        aria-orientation={horizontal ? 'vertical' : 'horizontal'}
        aria-label={label}
        aria-controls={`${uid}-primary`}
        aria-valuenow={collapsed ? 0 : size}
        aria-valuemin={collapsible ? 0 : minSize}
        aria-valuemax={maxSize}
        aria-valuetext={collapsed ? tr("eingeklappt") : tr("{0} Pixel", { "0": String(size) })}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => (collapsible ? setCollapsed(!collapsed) : commit(defaultSize))}
        onKeyDown={onKeyDown}
        className={cn(
          'group/sep relative z-10 shrink-0 outline-none',
          horizontal ? 'w-px cursor-col-resize' : 'h-px cursor-row-resize',
          'bg-line',
        )}
      >
        {/* großzügige Greiffläche */}
        <span aria-hidden className={cn('absolute', horizontal ? '-inset-x-1.5 inset-y-0' : '-inset-y-1.5 inset-x-0')} />
        {/* Kupferlinie beim Hover, Ziehen und Tastaturfokus */}
        <span
          aria-hidden
          className={cn(
            'pointer-events-none absolute rounded-full bg-accent opacity-0 shadow-[0_0_10px_var(--pf-glow-indicator)] transition-opacity duration-150',
            horizontal ? 'inset-y-0 -left-px w-[3px]' : 'inset-x-0 -top-px h-[3px]',
            'group-hover/sep:opacity-60 group-focus-visible/sep:opacity-100',
            dragging && 'opacity-100',
          )}
        />
        {/* Griff in der Mitte */}
        <span
          aria-hidden
          className={cn(
            'pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full border border-line-strong bg-surface-3 opacity-0 transition-opacity',
            horizontal ? 'h-7 w-1.5' : 'h-1.5 w-7',
            'group-hover/sep:opacity-100 group-focus-visible/sep:opacity-100',
            dragging && 'opacity-100',
          )}
        />
      </div>
      {primary === 'start' ? restPane : primaryPane}
    </div>
  )
}
