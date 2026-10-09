/**
 * Vorlagen-Katalog, nach Familien gegliedert: je Familie eine Überschrift (Glyphe, Name, Anzahl) und ein Raster aus
 * Karten. Tastatur: je Familie ein Tab-Halt (Listbox), Pfeile bewegen sich im Raster und über Familiengrenzen
 * hinweg, Pos1/Ende springen an Anfang/Ende, Bild↑/↓ zur vorigen/nächsten Familie, Enter/Leertaste öffnet die
 * Vorlage im Generator. Miniaturen laden erst im Sichtbereich.
 */
import { useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { FootprintFamily, FootprintPreset } from '@/api/footprints'
import { GalleryCard, LazyThumbnail } from '@/components/data'
import { familyShortLabel, presetSubtitle } from '../lib/families'
import { PackageGlyph } from '../PackageGlyph'
import { PresetThumb } from './PresetThumb'

export interface CatalogItem {
  family: FootprintFamily
  preset: FootprintPreset
  key: string
}

export interface CatalogGroup {
  family: FootprintFamily
  items: CatalogItem[]
}

export interface CatalogGridProps {
  groups: CatalogGroup[]
  onOpen: (family: FootprintFamily, preset: FootprintPreset) => void
  empty: ReactNode
}

/** Spaltenzahl eines CSS-Rasters (auto-fill) */
function columnsOf(el: Element | null): number {
  if (!el) return 1
  const cols = getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length
  return Math.max(1, cols)
}

export function CatalogGrid({ groups, onOpen, empty }: CatalogGridProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  // Tab-Halt je Familie (zuletzt fokussierte Karte)
  const [active, setActive] = useState<Record<string, number>>({})

  if (!groups.length) return <div className="flex h-full items-center justify-center">{empty}</div>

  const focusCard = (g: number, i: number) => {
    const group = groups[g]
    if (!group) return
    const index = Math.max(0, Math.min(group.items.length - 1, i))
    setActive((a) => ({ ...a, [group.family.key]: index }))
    const el = rootRef.current?.querySelector<HTMLElement>(`[data-cat="${g}-${index}"]`)
    el?.focus({ preventScroll: true })
    el?.scrollIntoView({ block: 'nearest' })
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>, g: number, i: number) => {
    const group = groups[g]
    const grid = (e.currentTarget.parentElement as HTMLElement | null) ?? null
    const cols = columnsOf(grid)
    const col = i % cols
    switch (e.key) {
      case 'ArrowRight':
        if (i + 1 < group.items.length) focusCard(g, i + 1)
        else if (g + 1 < groups.length) focusCard(g + 1, 0)
        break
      case 'ArrowLeft':
        if (i > 0) focusCard(g, i - 1)
        else if (g > 0) focusCard(g - 1, groups[g - 1].items.length - 1)
        break
      case 'ArrowDown':
        if (i + cols < group.items.length) focusCard(g, i + cols)
        else if (Math.floor(i / cols) < Math.floor((group.items.length - 1) / cols)) focusCard(g, group.items.length - 1)
        else if (g + 1 < groups.length) focusCard(g + 1, col)
        break
      case 'ArrowUp':
        if (i - cols >= 0) focusCard(g, i - cols)
        else if (g > 0) {
          const prevLen = groups[g - 1].items.length
          const lastRow = Math.floor((prevLen - 1) / cols) * cols
          focusCard(g - 1, Math.min(lastRow + col, prevLen - 1))
        }
        break
      case 'Home':
        if (e.ctrlKey) focusCard(0, 0)
        else focusCard(g, i - col)
        break
      case 'End':
        if (e.ctrlKey) focusCard(groups.length - 1, groups[groups.length - 1].items.length - 1)
        else focusCard(g, Math.min(group.items.length - 1, i - col + cols - 1))
        break
      case 'PageDown':
        if (g + 1 < groups.length) focusCard(g + 1, 0)
        break
      case 'PageUp':
        if (g > 0) focusCard(g - 1, 0)
        break
      case 'Enter':
      case ' ':
        onOpen(group.family, group.items[i].preset)
        break
      default:
        return
    }
    e.preventDefault()
  }

  return (
    <div ref={rootRef} className="absolute inset-0 overflow-y-auto pr-1 [scrollbar-gutter:stable]">
      {groups.map((group, g) => {
        const headingId = `fp-cat-${group.family.key}`
        const activeIndex = Math.min(active[group.family.key] ?? 0, group.items.length - 1)
        return (
          <section key={group.family.key} aria-labelledby={headingId} className="pb-5">
            <div className="sticky top-0 z-[2] flex items-center gap-2 bg-bg py-2">
              <span className="flex size-6 items-center justify-center rounded-md border border-line bg-surface text-fg-muted">
                <PackageGlyph family={group.family.key} className="size-4" />
              </span>
              {/* <h2>: unter dem Seitentitel (<h1> der Topbar) die nächste Ebene */}
              <h2 id={headingId} className="text-ui font-semibold tracking-[-0.01em] text-fg">
                {familyShortLabel(group.family)}
              </h2>
              <span className="text-2xs tabular-nums text-fg-subtle">
                {group.items.length} {group.items.length === 1 ? 'Vorlage' : 'Vorlagen'}
                {group.family.group !== familyShortLabel(group.family) && ` · ${group.family.group}`}
              </span>
              <span aria-hidden className="ml-1 h-px flex-1 bg-line" />
            </div>
            <div
              role="listbox"
              aria-labelledby={headingId}
              className="grid grid-cols-[repeat(auto-fill,minmax(172px,1fr))] gap-3 p-0.5"
            >
              {group.items.map((item, i) => (
                <div
                  key={item.key}
                  role="option"
                  aria-selected={false}
                  data-cat={`${g}-${i}`}
                  tabIndex={i === activeIndex ? 0 : -1}
                  onClick={() => onOpen(item.family, item.preset)}
                  onFocus={() => setActive((a) => (a[group.family.key] === i ? a : { ...a, [group.family.key]: i }))}
                  onKeyDown={(e) => onKeyDown(e, g, i)}
                  className="h-[176px] rounded-card outline-none focus-ring"
                >
                  <GalleryCard
                    board
                    title={item.preset.key}
                    meta={presetSubtitle(item.preset)}
                    thumbnail={<LazyThumbnail render={() => <PresetThumb family={item.family} preset={item.preset} />} inset="p-4" />}
                  />
                </div>
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
