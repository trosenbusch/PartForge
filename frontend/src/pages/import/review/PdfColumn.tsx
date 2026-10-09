import { motion, useReducedMotion } from 'motion/react'
import { ChevronLeft, ChevronRight, ExternalLink, Maximize2, Minus, PanelLeftClose, Plus, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type MouseEvent, type WheelEvent } from 'react'
import { datasheetPageUrl, type DatasheetDetail, type DeviceData, type ExtractionData } from '@/api/datasheets'
import { useElementSize } from '@/components/preview'
import { IconButton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatPercent } from '@/lib/format'
import { pageTopics } from '../lib/format'
import { openPdf } from '../lib/openPdf'
import { DEFAULT_PAGE_ASPECT, PageImage } from '../shared/PageImage'
import { useReviewUi } from '../store'
import { pageReferences, type PageReference } from './references'

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3]
const DPI_STEPS = [72, 110, 150, 200, 300]

function nextZoom(current: number, dir: 1 | -1): number {
  if (dir > 0) return ZOOMS.find((z) => z > current + 0.001) ?? ZOOMS[ZOOMS.length - 1]
  return [...ZOOMS].reverse().find((z) => z < current - 0.001) ?? ZOOMS[0]
}

/**
 * Spalte 1: Seitenminiaturen und große Seite mit Zoom; Fundstellen-Sprünge lassen die Seite aufleuchten. Klick auf
 * die Seite (oder Enter) öffnet sie groß zum Prüfen. `onCollapse` blendet die Spalte aus (Prüfansicht).
 */
export function PdfColumn({
  ds,
  extraction,
  device,
  onCollapse,
}: {
  ds: DatasheetDetail
  extraction?: ExtractionData
  device?: DeviceData
  onCollapse?: () => void
}) {
  const page = useReviewUi((s) => s.page)
  const setPage = useReviewUi((s) => s.setPage)
  const zoom = useReviewUi((s) => s.zoom)
  const setZoom = useReviewUi((s) => s.setZoom)
  const hoverPage = useReviewUi((s) => s.hoverPage)
  const flash = useReviewUi((s) => s.flash)
  const showSection = useReviewUi((s) => s.showSection)
  const openOverlay = useReviewUi((s) => s.openOverlay)
  const reduce = useReducedMotion()
  const [onlyUsed, setOnlyUsed] = useState(false)

  const used = useMemo(() => new Set(ds.selected_pages), [ds.selected_pages])
  const refs = useMemo(
    () => (extraction ? pageReferences(extraction, device) : new Map<number, PageReference[]>()),
    [extraction, device],
  )
  const info = useMemo(() => new Map(ds.pages.map((p) => [p.page, p])), [ds.pages])
  const all = useMemo(() => Array.from({ length: ds.page_count }, (_, i) => i + 1), [ds.page_count])
  const pages = onlyUsed && used.size ? all.filter((p) => used.has(p)) : all
  const current = info.get(page)
  const aspect = current && current.height_pt > 0 ? current.width_pt / current.height_pt : DEFAULT_PAGE_ASPECT
  const topics = pageTopics(current?.categories ?? [])
  const pageRefs = refs.get(page) ?? []

  // Seite wechseln – auch per Tastatur in Miniaturen und Ansicht
  const go = (p: number) => setPage(Math.min(ds.page_count, Math.max(1, p)))
  const step = (dir: 1 | -1) => {
    const i = pages.indexOf(page)
    const target = i < 0 ? pages[0] : pages[Math.min(pages.length - 1, Math.max(0, i + dir))]
    if (target) go(target)
  }

  // Miniatur der aktuellen Seite in den Blick holen
  const railRef = useRef<HTMLUListElement>(null)
  useEffect(() => {
    const btn = railRef.current?.querySelector<HTMLButtonElement>(`[data-page="${page}"]`)
    btn?.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: reduce ? 'auto' : 'smooth' })
  }, [page, reduce])

  const onRailKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    const keys: Record<string, () => void> = {
      ArrowDown: () => step(1),
      ArrowRight: () => step(1),
      ArrowUp: () => step(-1),
      ArrowLeft: () => step(-1),
      Home: () => go(pages[0]),
      End: () => go(pages[pages.length - 1]),
    }
    const fn = keys[e.key]
    if (!fn) return
    e.preventDefault()
    fn()
    requestAnimationFrame(() => railRef.current?.querySelector<HTMLButtonElement>('[aria-current="page"]')?.focus())
  }

  // große Ansicht
  const [viewerRef, viewerSize, viewerEl] = useElementSize<HTMLDivElement>()
  const fitWidth = Math.max(120, Math.min(viewerSize.width - 32, (viewerSize.height - 32) * aspect * 1.6))
  const displayWidth = Math.round(fitWidth * zoom)
  const dpr = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1
  const needed = (displayWidth * dpr) / ((current?.width_pt ?? 612) / 72)
  const dpi = DPI_STEPS.find((d) => d >= needed) ?? 300

  useEffect(() => {
    if (flash && viewerEl) viewerEl.scrollTo({ top: 0, left: 0 })
  }, [flash, viewerEl])

  const onViewerKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'PageDown' || (e.key === 'ArrowRight' && e.altKey)) step(1)
    else if (e.key === 'PageUp' || (e.key === 'ArrowLeft' && e.altKey)) step(-1)
    else if (e.key === '+' || e.key === '=') setZoom(nextZoom(zoom, 1))
    else if (e.key === '-') setZoom(nextZoom(zoom, -1))
    else if (e.key === '0') setZoom(1)
    else if (e.key === 'Enter' || e.key === ' ') openOverlay(page)
    else return
    e.preventDefault()
  }
  // Klick auf das Blatt: groß anzeigen (Ränder daneben bleiben zum Scrollen)
  const onViewerClick = (e: MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('[data-sheet]')) openOverlay(page)
  }
  const onWheel = (e: WheelEvent<HTMLDivElement>) => {
    if (!e.ctrlKey) return
    e.preventDefault()
    setZoom(nextZoom(zoom, e.deltaY < 0 ? 1 : -1))
  }
  // Strg+Mausrad darf die Seite nicht zoomen (passiver Listener → nativ abfangen)
  useEffect(() => {
    if (!viewerEl) return
    const block = (e: globalThis.WheelEvent) => {
      if (e.ctrlKey) e.preventDefault()
    }
    viewerEl.addEventListener('wheel', block, { passive: false })
    return () => viewerEl.removeEventListener('wheel', block)
  }, [viewerEl])

  const flashKey = flash && flash.page === page ? flash.nonce : 0

  return (
    <div className="@container flex h-full min-h-0 flex-col bg-bg-elev">
      {/* Werkzeugleiste */}
      <div className="flex h-10 shrink-0 items-center gap-0.5 border-b border-line px-1.5">
        <IconButton
          size="sm"
          label="Vorherige Seite"
          icon={<ChevronLeft />}
          onClick={() => step(-1)}
          disabled={pages.indexOf(page) <= 0}
          className="hidden @[18rem]:inline-flex"
        />
        <span className="min-w-12 px-1 text-center text-xs tabular-nums text-fg" aria-live="polite">
          <span className="sr-only">Seite </span>
          <span className="font-semibold">{page}</span>
          <span className="text-fg-subtle"> / {ds.page_count}</span>
        </span>
        <IconButton
          size="sm"
          label="Nächste Seite"
          icon={<ChevronRight />}
          onClick={() => step(1)}
          disabled={pages.indexOf(page) === pages.length - 1}
          className="hidden @[18rem]:inline-flex"
        />
        {used.size > 0 && (
          <Tooltip content={onlyUsed ? 'Alle Seiten zeigen' : 'Nur die Seiten zeigen, die Claude gelesen hat'}>
            <button
              type="button"
              aria-pressed={onlyUsed}
              onClick={() => setOnlyUsed((v) => !v)}
              className={cn(
                'ml-1 inline-flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium outline-none transition-colors focus-ring',
                onlyUsed ? 'bg-[color-mix(in_oklab,var(--pf-spark-b)_14%,transparent)] text-spark-text' : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
              )}
            >
              <Sparkles aria-hidden className="size-3.5" />
              <span className="hidden @[28rem]:inline">Gelesen</span>
              <span className="tabular-nums">{used.size}</span>
            </button>
          </Tooltip>
        )}
        <div className="ml-auto flex items-center gap-0.5">
          <IconButton size="sm" label="Verkleinern" icon={<Minus />} onClick={() => setZoom(nextZoom(zoom, -1))} disabled={zoom <= ZOOMS[0]} />
          <Tooltip content="Einpassen (0)">
            <button
              type="button"
              onClick={() => setZoom(1)}
              className="hidden h-7 min-w-11 rounded-control px-1 text-xs tabular-nums text-fg-muted outline-none hover:bg-surface-2 hover:text-fg focus-ring @[24rem]:block"
              aria-label={`Zoom ${formatPercent(zoom)} – einpassen`}
            >
              {formatPercent(zoom)}
            </button>
          </Tooltip>
          <IconButton size="sm" label="Vergrößern" icon={<Plus />} onClick={() => setZoom(nextZoom(zoom, 1))} disabled={zoom >= ZOOMS[ZOOMS.length - 1]} />
          <IconButton size="sm" label="Seite groß anzeigen (Enter)" icon={<Maximize2 />} onClick={() => openOverlay(page)} />
          <IconButton
            size="sm"
            label="PDF öffnen"
            icon={<ExternalLink />}
            onClick={() => void openPdf(ds)}
            className="hidden @[26rem]:inline-flex"
          />
          {onCollapse && <IconButton size="sm" label="PDF-Spalte ausblenden" icon={<PanelLeftClose />} onClick={onCollapse} />}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col-reverse @[17rem]:flex-row">
        {/* Miniaturen */}
        <ul
          ref={railRef}
          aria-label="Seiten"
          className={cn(
            'flex shrink-0 gap-2 overflow-auto scrollbar-none p-2',
            'h-[5.75rem] flex-row border-t border-line @[17rem]:h-auto @[17rem]:w-[5.25rem] @[17rem]:flex-col @[17rem]:border-r @[17rem]:border-t-0',
          )}
        >
          {pages.map((p) => {
            const pInfo = info.get(p)
            const isCurrent = p === page
            const isUsed = used.has(p)
            const t = pageTopics(pInfo?.categories ?? [])
            return (
              <li key={p} className="shrink-0">
                <button
                  type="button"
                  data-page={p}
                  tabIndex={isCurrent ? 0 : -1}
                  aria-current={isCurrent ? 'page' : undefined}
                  aria-label={`Seite ${p}${isUsed ? ', von Claude gelesen' : ''}${t.length ? ` – ${t.join(', ')}` : ''}`}
                  onClick={() => go(p)}
                  onKeyDown={onRailKey}
                  className={cn(
                    'group/thumb relative block w-12 rounded-md p-[3px] outline-none transition-colors focus-ring @[17rem]:w-full',
                    isCurrent ? 'bg-accent-soft' : 'hover:bg-surface-2',
                  )}
                >
                  <PageImage
                    datasheetId={ds.id}
                    page={p}
                    dpi={36}
                    alt=""
                    aspect={pInfo && pInfo.height_pt > 0 ? pInfo.width_pt / pInfo.height_pt : DEFAULT_PAGE_ASPECT}
                    className={cn(
                      'rounded-sm ring-1 transition-shadow',
                      isCurrent ? 'ring-2 ring-accent' : 'ring-line-strong',
                      hoverPage === p && !isCurrent && 'ring-2 ring-spark-b',
                    )}
                  />
                  <span className="mt-1 flex items-center justify-center gap-1 text-2xs leading-4 tabular-nums">
                    {isUsed && <span aria-hidden className="size-1.5 rounded-full bg-gradient-spark" />}
                    <span className={cn(isCurrent ? 'font-semibold text-fg' : 'text-fg-subtle')}>{p}</span>
                  </span>
                  {hoverPage === p && (
                    <span aria-hidden className="pointer-events-none absolute inset-0 rounded-md shadow-glow-spark" />
                  )}
                </button>
              </li>
            )
          })}
        </ul>

        {/* große Seite */}
        <div className="relative flex min-h-0 min-w-0 flex-1 flex-col">
          {(topics.length > 0 || pageRefs.length > 0 || used.has(page)) && (
            <div className="flex min-h-8 shrink-0 flex-wrap items-center gap-1 border-b border-line px-3 py-1 text-2xs text-fg-subtle">
              {used.has(page) && (
                <span className="inline-flex items-center gap-1 text-spark-text">
                  <Sparkles aria-hidden className="size-3" />
                  Von Claude gelesen
                </span>
              )}
              {topics.length > 0 && <span className="truncate">{(used.has(page) ? ' · ' : '') + topics.join(', ')}</span>}
              {pageRefs.length > 0 && (
                <span className="ml-auto flex flex-wrap items-center justify-end gap-1">
                  {pageRefs.slice(0, 3).map((r) => (
                    <button
                      key={`${r.section}-${r.label}`}
                      type="button"
                      onClick={() => showSection(r.section)}
                      className="h-5 rounded-md border border-line px-1.5 font-medium text-fg-muted outline-none transition-colors hover:border-line-strong hover:text-fg focus-ring"
                    >
                      {r.label}
                    </button>
                  ))}
                </span>
              )}
            </div>
          )}
          {/* Seitenansicht mit eigener Tastatursteuerung (Blättern, Zoomen) – role="application" wie die Leinwände */}
          {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
          <div
            ref={viewerRef}
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            tabIndex={0}
            role="application"
            aria-roledescription="Seitenansicht"
            aria-label={`Seite ${page} von ${ds.page_count} – Enter zeigt sie groß, Bild↑/↓ blättern, +/− zoomen, 0 einpassen`}
            onKeyDown={onViewerKey}
            onWheel={onWheel}
            onClick={onViewerClick}
            className="relative min-h-0 flex-1 overflow-auto bg-bg outline-none focus-ring-inset light:bg-surface-3"
          >
            <div className="flex min-h-full min-w-fit items-start justify-center p-4">
              <div data-sheet className="relative cursor-zoom-in shadow-pop" style={{ width: displayWidth }} title="Klicken, um die Seite groß anzuzeigen">
                {/* Miniatur als Unterlage, bis das scharfe Bild geladen ist */}
                <img
                  aria-hidden
                  alt=""
                  src={datasheetPageUrl(ds.id, page, 36)}
                  className="absolute inset-0 size-full bg-white object-contain blur-[1px]"
                  draggable={false}
                />
                <PageImage
                  key={`${page}-${dpi}`}
                  datasheetId={ds.id}
                  page={page}
                  dpi={dpi}
                  aspect={aspect}
                  loading="eager"
                  alt={`Seite ${page} des Datenblatts${topics.length ? ` (${topics.join(', ')})` : ''}`}
                  placeholder={false}
                />
                {flashKey > 0 && !reduce && (
                  <motion.span
                    key={flashKey}
                    aria-hidden
                    className="pointer-events-none absolute -inset-1.5 rounded-md border-2 border-spark-b shadow-glow-spark"
                    initial={{ opacity: 1, scale: 1.015 }}
                    animate={{ opacity: 0, scale: 1 }}
                    transition={{ duration: 1.6, ease: [0.16, 1, 0.3, 1] }}
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
