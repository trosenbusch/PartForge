import { useI18n } from '@/lib/i18n'
import { ScrollArea as ScrollAreaPrimitive } from 'radix-ui'
import { useCallback, useEffect, useState, type ReactNode, type Ref } from 'react'
import { cn } from '@/lib/cn'

export interface ScrollAreaProps {
  children: ReactNode
  className?: string
  viewportClassName?: string
  viewportRef?: Ref<HTMLDivElement>
  orientation?: 'vertical' | 'horizontal' | 'both'
  /** Scrollbar nur beim Hover/Scrollen zeigen (Standard) oder immer */
  type?: 'hover' | 'scroll' | 'auto' | 'always'
  /**
   * Bereich per Tastatur erreichbar machen (Tab-Stopp, Pfeiltasten scrollen): `auto` (Standard) = nur, wenn er
   * tatsächlich scrollt und nichts Fokussierbares enthält (WCAG 2.1.1, axe „scrollable-region-focusable“)
   */
  focusable?: boolean | 'auto'
  /** Name des fokussierbaren Bereichs für Screenreader (z. B. „Protokoll“) */
  'aria-label'?: string
}

const FOCUSABLE = 'a[href], button, input, select, textarea, summary, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]'

/** Ref eines Aufrufers bedienen (Callback oder Ref-Objekt) */
function assignRef<T>(ref: Ref<T> | undefined, value: T | null): void {
  if (typeof ref === 'function') ref(value)
  else if (ref) (ref as { current: T | null }).current = value
}

/** Scrollt der Bereich, ohne dass ein Element darin per Tastatur erreichbar ist? */
function needsTabStop(el: HTMLElement): boolean {
  const scrolls = el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1
  return scrolls && !el.querySelector(FOCUSABLE)
}

/** Scrollbereich mit dezenter, schmaler Scrollbar. */
export function ScrollArea({
  children,
  className,
  viewportClassName,
  viewportRef,
  orientation = 'vertical',
  type = 'hover',
  focusable = 'auto',
  'aria-label': ariaLabel,
}: ScrollAreaProps) {
  useI18n()
  const [viewport, setViewport] = useState<HTMLDivElement | null>(null)
  const [autoFocusable, setAutoFocusable] = useState(false)
  const setRefs = useCallback(
    (el: HTMLDivElement | null) => {
      setViewport(el)
      assignRef(viewportRef, el)
    },
    [viewportRef],
  )

  // Inhalt und Größe beobachten: erst wenn er überläuft und keine Bedienelemente hat, wird der Bereich ein Tab-Stopp
  useEffect(() => {
    if (focusable !== 'auto' || !viewport) return
    const update = () => setAutoFocusable(needsTabStop(viewport))
    update()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    ro?.observe(viewport)
    if (viewport.firstElementChild) ro?.observe(viewport.firstElementChild)
    const mo = typeof MutationObserver !== 'undefined' ? new MutationObserver(update) : null
    mo?.observe(viewport, { childList: true, subtree: true, attributes: true, attributeFilter: ['tabindex', 'href', 'disabled'] })
    return () => {
      ro?.disconnect()
      mo?.disconnect()
    }
  }, [focusable, viewport])

  const tabStop = focusable === 'auto' ? autoFocusable : focusable
  return (
    <ScrollAreaPrimitive.Root type={type} className={cn('relative overflow-hidden', className)}>
      <ScrollAreaPrimitive.Viewport
        ref={setRefs}
        tabIndex={tabStop ? 0 : undefined}
        role={tabStop && ariaLabel ? 'region' : undefined}
        aria-label={tabStop ? ariaLabel : undefined}
        className={cn('size-full rounded-[inherit] outline-none focus-ring-inset', viewportClassName)}
      >
        {children}
      </ScrollAreaPrimitive.Viewport>
      {(orientation === 'vertical' || orientation === 'both') && <Bar orientation="vertical" />}
      {(orientation === 'horizontal' || orientation === 'both') && <Bar orientation="horizontal" />}
      <ScrollAreaPrimitive.Corner />
    </ScrollAreaPrimitive.Root>
  )
}

function Bar({ orientation }: { orientation: 'vertical' | 'horizontal' }) {
  useI18n()
  return (
    <ScrollAreaPrimitive.Scrollbar
      orientation={orientation}
      className={cn(
        'z-10 flex touch-none select-none p-0.5 transition-opacity duration-200 data-[state=hidden]:opacity-0',
        orientation === 'vertical' ? 'h-full w-2.5' : 'h-2.5 flex-col',
      )}
    >
      <ScrollAreaPrimitive.Thumb className="relative flex-1 rounded-full bg-line-strong transition-colors hover:bg-[color-mix(in_oklab,var(--pf-fg-subtle)_70%,transparent)]" />
    </ScrollAreaPrimitive.Scrollbar>
  )
}
