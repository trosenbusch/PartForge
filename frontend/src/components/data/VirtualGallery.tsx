/**
 * Virtualisierte Galerie (TanStack Virtual, Zeilen mit dynamischer Spaltenzahl) für Symbole/Footprints u. ä.
 * Listbox-Semantik mit aktivem Element: ←/→/↑/↓, Pos1/Ende, Bild↑/↓, Enter (öffnen), Leertaste (auswählen).
 * Nur sichtbare Karten werden gerendert; Vorschaubilder laden mit <LazyThumbnail> erst im Sichtbereich.
 *
 *   <VirtualGallery items={footprints} getKey={(f) => f.name} minItemWidth={180} itemHeight={196}
 *     selectedKey={sel} onSelect={(f) => setSel(f.name)} onActivate={open}
 *     renderItem={(f, s) => <GalleryCard title={f.name} selected={s.selected} active={s.active} thumbnail={…} />} />
 */
import { useVirtualizer } from '@tanstack/react-virtual'
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useElementSize } from '@/components/preview/useElementSize'

export interface GalleryItemState {
  index: number
  selected: boolean
  /** Tastatur-Cursor steht auf dieser Karte */
  active: boolean
}

export interface VirtualGalleryProps<T> {
  items: readonly T[]
  getKey: (item: T, index: number) => string
  renderItem: (item: T, state: GalleryItemState) => ReactNode
  /** Mindestbreite einer Karte (px) – die Spaltenzahl ergibt sich aus der Breite */
  minItemWidth?: number
  /** Höhe einer Karte (px) */
  itemHeight?: number
  gap?: number
  /** Innenabstand des Scrollbereichs (px) */
  padding?: number
  selectedKey?: string | null
  onSelect?: (item: T, index: number) => void
  /** Enter / Doppelklick */
  onActivate?: (item: T, index: number) => void
  /** Zugänglicher Name, z. B. „Footprints“ */
  'aria-label': string
  /** Inhalt bei leerer Liste */
  empty?: ReactNode
  className?: string
  overscan?: number
}

export function VirtualGallery<T>({
  items,
  getKey,
  renderItem,
  minItemWidth = 180,
  itemHeight = 200,
  gap = 12,
  padding = 2,
  selectedKey,
  onSelect,
  onActivate,
  'aria-label': ariaLabel,
  empty,
  className,
  overscan = 3,
}: VirtualGalleryProps<T>) {
  const uid = useId().replace(/:/g, '')
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [sizeRef, size] = useElementSize<HTMLDivElement>()
  const inner = Math.max(0, size.width - padding * 2)
  const columns = Math.max(1, Math.floor((inner + gap) / (minItemWidth + gap)))
  const rows = Math.ceil(items.length / columns)

  // TanStack Virtual verwaltet seinen Zustand selbst (nicht mit dem React Compiler memoisierbar) – bewusst so
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => itemHeight + gap,
    overscan,
    paddingStart: padding,
    paddingEnd: padding,
  })

  const keys = useMemo(() => items.map((it, i) => getKey(it, i)), [items, getKey])
  const selectedIndex = selectedKey ? keys.indexOf(selectedKey) : -1
  // aktives Element gilt nur für die aktuelle Liste (neue Liste → wieder bei der Auswahl bzw. vorn beginnen)
  const [activeState, setActiveState] = useState<{ items: readonly T[]; index: number }>({ items, index: -1 })
  const active = activeState.items === items ? activeState.index : -1
  const setActive = (index: number) => setActiveState({ items, index })
  const activeIndex = active >= 0 && active < items.length ? active : selectedIndex >= 0 ? selectedIndex : items.length ? 0 : -1

  // aktive Karte sichtbar halten
  const scrollToItem = useRef<(index: number) => void>(() => {})
  useEffect(() => {
    scrollToItem.current = (index) => virtualizer.scrollToIndex(Math.floor(index / columns), { align: 'auto' })
  })
  const goTo = (index: number) => {
    if (index < 0 || index >= items.length) return
    setActive(index)
    scrollToItem.current(index)
  }
  // Auswahl von außen (z. B. Suche) → in den Sichtbereich holen
  useEffect(() => {
    if (selectedIndex >= 0) scrollToItem.current(selectedIndex)
  }, [selectedIndex])
  // neue Liste (Filter) → nach oben
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [items])

  const visibleRows = Math.max(1, Math.floor(size.height / (itemHeight + gap)))
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!items.length) return
    const i = activeIndex < 0 ? 0 : activeIndex
    let next: number | null = null
    switch (e.key) {
      case 'ArrowRight':
        next = Math.min(items.length - 1, i + 1)
        break
      case 'ArrowLeft':
        next = Math.max(0, i - 1)
        break
      case 'ArrowDown':
        next = Math.min(items.length - 1, i + columns)
        break
      case 'ArrowUp':
        next = Math.max(0, i - columns)
        break
      case 'Home':
        next = e.ctrlKey ? 0 : i - (i % columns)
        break
      case 'End':
        next = e.ctrlKey ? items.length - 1 : Math.min(items.length - 1, i - (i % columns) + columns - 1)
        break
      case 'PageDown':
        next = Math.min(items.length - 1, i + columns * visibleRows)
        break
      case 'PageUp':
        next = Math.max(0, i - columns * visibleRows)
        break
      case ' ':
        e.preventDefault()
        onSelect?.(items[i], i)
        return
      case 'Enter':
        e.preventDefault()
        onSelect?.(items[i], i)
        onActivate?.(items[i], i)
        return
      default:
        return
    }
    e.preventDefault()
    goTo(next)
  }

  const optionId = (index: number) => `${uid}-opt-${index}`
  const cardWidth = columns > 0 ? (inner - gap * (columns - 1)) / columns : minItemWidth

  return (
    <div
      ref={(el) => {
        scrollRef.current = el
        sizeRef(el)
      }}
      role="listbox"
      aria-label={ariaLabel}
      aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
      aria-multiselectable={false}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className={cn('relative min-h-0 overflow-y-auto overflow-x-hidden rounded-card outline-none', className)}
    >
      {items.length === 0 ? (
        (empty ?? <div className="flex h-full items-center justify-center p-8 text-ui text-fg-subtle">Keine Einträge</div>)
      ) : (
        <div className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
          {virtualizer.getVirtualItems().map((row) => {
            const from = row.index * columns
            return (
              <div
                key={row.key}
                role="presentation"
                className="absolute left-0 top-0 flex w-full"
                style={{ transform: `translateY(${row.start}px)`, height: itemHeight, gap, paddingInline: padding }}
              >
                {Array.from({ length: columns }, (_, c) => {
                  const index = from + c
                  if (index >= items.length) return <div key={c} style={{ width: cardWidth }} />
                  const item = items[index]
                  const selected = index === selectedIndex
                  const isActive = index === activeIndex
                  return (
                    <div
                      key={keys[index]}
                      id={optionId(index)}
                      data-active={isActive || undefined}
                      role="option"
                      aria-selected={selected}
                      aria-setsize={items.length}
                      aria-posinset={index + 1}
                      tabIndex={-1}
                      onMouseDown={(e) => {
                        // Fokus bleibt auf der Liste (aktives Element über aria-activedescendant)
                        e.preventDefault()
                        scrollRef.current?.focus()
                      }}
                      onClick={() => {
                        setActive(index)
                        onSelect?.(item, index)
                      }}
                      onKeyDown={onKeyDown}
                      onDoubleClick={() => onActivate?.(item, index)}
                      className="min-w-0 shrink-0 rounded-card data-[active]:in-focus-visible:outline-2 data-[active]:in-focus-visible:outline-offset-2 data-[active]:in-focus-visible:outline-accent"
                      style={{ width: cardWidth, height: itemHeight }}
                    >
                      {renderItem(item, { index, selected, active: isActive })}
                    </div>
                  )
                })}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
