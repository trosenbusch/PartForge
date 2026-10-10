import { t, useI18n } from '@/lib/i18n'
import { useReducedMotion } from 'motion/react'
import { ChevronLeft, ChevronRight, ExternalLink, FileText, Minus, Plus, Sparkles, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { datasheetPageUrl, type DatasheetDetail, type DeviceData, type ExtractionData } from '@/api/datasheets'
import { useElementSize } from '@/components/preview'
import { Dialog, DialogClose, DialogContent, DialogTitle, IconButton, SegmentedControl, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatPercent } from '@/lib/format'
import { pageTopics } from '../lib/format'
import { openPdf } from '../lib/openPdf'
import { DEFAULT_PAGE_ASPECT, PageImage } from '../shared/PageImage'
import { useReviewUi } from '../store'
import { pageReferences, type PageReference } from './references'

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3]
const DPI_STEPS = [110, 150, 200, 300]
const BODY_ID = 'pf-page-overlay-body'

function nextZoom(current: number, dir: 1 | -1): number {
  if (dir > 0) return ZOOMS.find((z) => z > current + 0.001) ?? ZOOMS[ZOOMS.length - 1]
  return [...ZOOMS].reverse().find((z) => z < current - 0.001) ?? ZOOMS[0]
}

/**
 * Große Seitenansicht zum Prüfen einer Fundstelle (≈ 70 % des Fensters, scharf gerendert): öffnet sich mit einem
 * Klick auf „S. 31“ oder auf die Seite in der PDF-Spalte. ←/→ blättern, +/− zoomen, 0 einpassen, Esc schließt.
 * Die Seite bleibt mit der PDF-Spalte verbunden – nach dem Schließen steht dort dieselbe Seite.
 */
export function PageOverlay({ ds, extraction, device }: { ds: DatasheetDetail; extraction?: ExtractionData; device?: DeviceData }) {
  useI18n()
  const overlay = useReviewUi((s) => s.overlay)
  const close = useReviewUi((s) => s.closeOverlay)
  return (
    <Dialog
      open={Boolean(overlay)}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      {overlay && (
        <DialogContent
          size="full"
          hideClose
          aria-describedby={undefined}
          className="max-w-[min(1180px,calc(100vw-48px))]"
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            document.getElementById(BODY_ID)?.focus()
          }}
        >
          <OverlayBody ds={ds} extraction={extraction} device={device} origin={overlay} />
        </DialogContent>
      )}
    </Dialog>
  )
}

function OverlayBody({
  ds,
  extraction,
  device,
  origin,
}: {
  ds: DatasheetDetail
  extraction?: ExtractionData
  device?: DeviceData
  origin: { page: number; what?: string }
}) {
  const { t: localize } = useI18n()
  const page = useReviewUi((s) => s.page)
  const setPage = useReviewUi((s) => s.setPage)
  const showSection = useReviewUi((s) => s.showSection)
  const close = useReviewUi((s) => s.closeOverlay)
  const reduce = useReducedMotion()
  const [fit, setFit] = useState<'width' | 'page'>('width')
  const [zoom, setZoom] = useState(1)

  const info = useMemo(() => new Map(ds.pages.map((p) => [p.page, p])), [ds.pages])
  const used = useMemo(() => new Set(ds.selected_pages), [ds.selected_pages])
  const refs = useMemo(
    () => (extraction ? pageReferences(extraction, device, localize) : new Map<number, PageReference[]>()),
    [extraction, device, localize],
  )
  const current = info.get(page)
  const aspect = current && current.height_pt > 0 ? current.width_pt / current.height_pt : DEFAULT_PAGE_ASPECT
  const topics = pageTopics(current?.categories ?? [])
  const pageRefs = refs.get(page) ?? []
  const what = page === origin.page ? origin.what : undefined

  const go = (p: number) => setPage(Math.min(ds.page_count, Math.max(1, p)))

  // Größe der Seite: Breite einpassen (Standard – Maßzeichnungen lesbar) oder ganze Seite
  const [bodyRef, body, bodyEl] = useElementSize<HTMLDivElement>()
  const availW = Math.max(240, body.width - 48)
  const availH = Math.max(240, body.height - 48)
  const base = fit === 'width' ? availW : Math.min(availW, availH * aspect)
  const displayWidth = Math.round(base * zoom)
  const dpr = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1
  const needed = (displayWidth * dpr) / ((current?.width_pt || 612) / 72)
  const dpi = DPI_STEPS.find((d) => d >= needed) ?? 300

  // neue Seite: oben beginnen
  useEffect(() => {
    bodyEl?.scrollTo({ top: 0, left: 0 })
  }, [page, bodyEl])

  // Strg+Mausrad zoomt die Seite (nicht das Fenster)
  useEffect(() => {
    if (!bodyEl) return
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey) return
      e.preventDefault()
      setZoom((z) => nextZoom(z, e.deltaY < 0 ? 1 : -1))
    }
    bodyEl.addEventListener('wheel', onWheel, { passive: false })
    return () => bodyEl.removeEventListener('wheel', onWheel)
  }, [bodyEl])

  // Miniatur der aktuellen Seite im Filmstreifen sichtbar halten
  const stripRef = useRef<HTMLUListElement>(null)
  useEffect(() => {
    stripRef.current
      ?.querySelector<HTMLElement>(`[data-page="${page}"]`)
      ?.scrollIntoView({ block: 'nearest', inline: 'center', behavior: reduce ? 'auto' : 'smooth' })
  }, [page, reduce])

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    const target = e.target as HTMLElement
    if (target.closest('[role="radiogroup"]')) return // Pfeiltasten gehören dort der Auswahl
    const keys: Record<string, () => void> = {
      ArrowLeft: () => go(page - 1),
      ArrowRight: () => go(page + 1),
      PageUp: () => go(page - 1),
      PageDown: () => go(page + 1),
      Home: () => go(1),
      End: () => go(ds.page_count),
      '+': () => setZoom((z) => nextZoom(z, 1)),
      '=': () => setZoom((z) => nextZoom(z, 1)),
      '-': () => setZoom((z) => nextZoom(z, -1)),
      '0': () => setZoom(1),
    }
    const fn = keys[e.key]
    if (!fn) return
    e.preventDefault()
    fn()
  }

  const pages = Array.from({ length: ds.page_count }, (_, i) => i + 1)

  return (
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions -- Tastatur der Seitenansicht (Blättern, Zoomen)
    <div className="flex min-h-0 flex-1 flex-col" onKeyDown={onKeyDown}>
      {/* Kopf: Seite, Inhalt, Fundstelle – rechts Blättern, Zoom, Einpassen, PDF, Schließen */}
      <div className="flex shrink-0 items-center gap-3 border-b border-line px-4 py-2.5">
        <span
          aria-hidden
          className="flex size-9 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted [&_svg]:size-4"
        >
          <FileText />
        </span>
        <div className="min-w-0 flex-1">
          <DialogTitle className="flex items-baseline gap-2 text-md font-semibold tracking-[-0.015em] text-fg">
            {t("Seite ")}<span className="tabular-nums">{page}</span>
            <span className="text-ui font-normal text-fg-subtle tabular-nums">{t("von ")}{ds.page_count}</span>
          </DialogTitle>
          <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
            {what && (
              <span className="inline-flex items-center gap-1 rounded-md bg-surface-3 px-1.5 py-px font-medium text-fg">
                {t("Fundstelle: ")}{what}
              </span>
            )}
            {used.has(page) && (
              <span className="inline-flex items-center gap-1 text-spark-text">
                <Sparkles aria-hidden className="size-3" />
                {t("Von Claude gelesen")}</span>
            )}
            {topics.length > 0 && <span className="truncate text-fg-subtle">{topics.join(', ')}</span>}
            <span className="truncate text-fg-subtle">{ds.original_name}</span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton size="sm" label={t("Vorherige Seite")} hotkey="arrowleft" icon={<ChevronLeft />} onClick={() => go(page - 1)} disabled={page <= 1} />
          <IconButton
            size="sm"
            label={t("Nächste Seite")}
            hotkey="arrowright"
            icon={<ChevronRight />}
            onClick={() => go(page + 1)}
            disabled={page >= ds.page_count}
          />
          <span aria-hidden className="mx-1 h-5 w-px bg-line" />
          <IconButton size="sm" label={t("Verkleinern")} icon={<Minus />} onClick={() => setZoom((z) => nextZoom(z, -1))} disabled={zoom <= ZOOMS[0]} />
          <Tooltip content={t("Zoom zurücksetzen (0)")}>
            <button
              type="button"
              onClick={() => setZoom(1)}
              aria-label={t("Zoom {0} – zurücksetzen", { "0": String(formatPercent(zoom)) })}
              className="h-7 min-w-12 rounded-control px-1 text-xs tabular-nums text-fg-muted outline-none hover:bg-surface-2 hover:text-fg focus-ring"
            >
              {formatPercent(zoom)}
            </button>
          </Tooltip>
          <IconButton size="sm" label={t("Vergrößern")} icon={<Plus />} onClick={() => setZoom((z) => nextZoom(z, 1))} disabled={zoom >= ZOOMS[ZOOMS.length - 1]} />
          <SegmentedControl
            size="sm"
            aria-label={t("Einpassen")}
            value={fit}
            onValueChange={(v) => {
              setFit(v)
              setZoom(1)
            }}
            options={[
              { value: 'width', label: t("Breite") },
              { value: 'page', label: t("Ganze Seite") },
            ]}
            className="ml-1"
          />
          <span aria-hidden className="mx-1 h-5 w-px bg-line" />
          <IconButton size="sm" label={t("PDF öffnen")} icon={<ExternalLink />} onClick={() => void openPdf(ds)} />
          <DialogClose asChild>
            <IconButton size="sm" label={t("Schließen (Esc)")} icon={<X />} />
          </DialogClose>
        </div>
      </div>

      {/* Seite */}
      <div className="relative min-h-0 flex-1">
        <div
          ref={bodyRef}
          id={BODY_ID}
          // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- scrollbare Seite per Tastatur
          tabIndex={0}
          role="region"
          aria-label={t("Seite {0} – ←/→ blättern, +/− zoomen, 0 zurücksetzen", { "0": String(page) })}
          className="absolute inset-0 overflow-auto bg-bg outline-none focus-ring-inset light:bg-surface-3"
        >
          <div className="flex min-h-full min-w-fit items-start justify-center p-6">
            <div className="relative shadow-pop" style={{ width: displayWidth }}>
              <img
                aria-hidden
                alt=""
                src={datasheetPageUrl(ds.id, page, 48)}
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
                placeholder={false}
                alt={t("Seite {0} des Datenblatts{1}", { "0": String(page), "1": String(topics.length ? ` (${topics.join(', ')})` : '') })}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Fuß: Fundstellen dieser Seite und Filmstreifen */}
      <div className="flex shrink-0 items-center gap-3 border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)] px-4 py-2">
        {pageRefs.length > 0 && (
          <div className="flex shrink-0 flex-col gap-1">
            <span className="micro-label">{t("Auf dieser Seite")}</span>
            <div className="flex max-w-72 flex-wrap gap-1">
              {pageRefs.slice(0, 4).map((r) => (
                <button
                  key={`${r.section}-${r.label}`}
                  type="button"
                  onClick={() => {
                    close()
                    showSection(r.section)
                  }}
                  className="h-6 rounded-md border border-line-strong bg-surface px-1.5 text-2xs font-medium text-fg-muted outline-none transition-colors hover:border-line-control hover:text-fg focus-ring"
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>
        )}
        <ul ref={stripRef} aria-label={t("Seiten")} className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto scrollbar-none py-1">
          {pages.map((p) => {
            const pInfo = info.get(p)
            const isCurrent = p === page
            return (
              <li key={p} className="shrink-0">
                <button
                  type="button"
                  data-page={p}
                  aria-current={isCurrent ? 'page' : undefined}
                  aria-label={t("Seite {0}{1}", { "0": String(p), "1": String(used.has(p) ? t(", von Claude gelesen") : '') })}
                  onClick={() => go(p)}
                  className={cn(
                    'group/strip relative block w-10 rounded-md p-[2px] outline-none transition-colors focus-ring',
                    isCurrent ? 'bg-accent-soft' : 'hover:bg-surface-3',
                  )}
                >
                  <PageImage
                    datasheetId={ds.id}
                    page={p}
                    dpi={36}
                    alt=""
                    aspect={pInfo && pInfo.height_pt > 0 ? pInfo.width_pt / pInfo.height_pt : DEFAULT_PAGE_ASPECT}
                    className={cn('rounded-sm ring-1', isCurrent ? 'ring-2 ring-accent' : 'ring-line-strong')}
                  />
                  <span className="mt-0.5 flex items-center justify-center gap-0.5 text-2xs leading-3 tabular-nums">
                    {used.has(p) && <span aria-hidden className="size-1 rounded-full bg-gradient-spark" />}
                    <span className={isCurrent ? 'font-semibold text-fg' : 'text-fg-subtle'}>{p}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
