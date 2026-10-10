import { getLocale, localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Seitenleiste der Vorschau: Symbol der Serie (große Vorschau mit Bezeichner und Kommentar eines Beispiels) und alle
 * Footprints – „neu“ = wird beim Erzeugen nach IPC-7351B generiert. Überfahren oder Fokus zeigt den Footprint auf der
 * Leiterplatten-Leinwand, Klick hält ihn fest. Trägt ein Name eine Kennung („CAPC1608X90N_4328“), steht die Kennung
 * gedämpft, und auf der Leinwand sagt ein Hinweis warum (`FootprintRef.name_reason`, voller Text im Tooltip; in der
 * Liste als Beschreibung der Zeile für Screenreader).
 */
import { CircuitBoard, Component, Info } from 'lucide-react'
import { useId, useState, type CSSProperties } from 'react'
import type { SeriesFootprintRef, SeriesSymbolRef, SeriesTemplate } from '@/api/series'
import { CHROME_MUTED, CHROME_SURFACE, FootprintCanvas, SymbolCanvas, useSymbolPreview } from '@/components/preview'
import { Badge, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatNumber } from '@/lib/format'
import { nameReasonTopic } from '../../model/footprint'
import { useFootprintPreviewFor } from '../../model/footprintPreview'
import type { Density } from '../../model/settings'
import { FootprintName } from './FootprintName'

export interface FootprintPanelProps {
  template: SeriesTemplate
  symbol: SeriesSymbolRef | null
  footprints: SeriesFootprintRef[]
  /** Bauteile je Footprint-Name */
  usage: Record<string, number>
  density: Density
  /** Kommentar eines Beispielbauteils („10k“) – das Symbol zeigt ihn statt des Platzhalters */
  comment?: string | null
  className?: string
  /** Höhe bzw. Höchsthöhe (die Vorschau misst den Platz bis zur Fußleiste) */
  style?: CSSProperties
}

const libName = (path: string | null) => (path ? baseName(path.replace(/\\/g, '/')) : null)


export function FootprintPanel({ template, symbol, footprints, usage, density, comment, className, style }: FootprintPanelProps) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const sorted = [...footprints].sort((a, b) => Number(a.exists) - Number(b.exists) || a.name.localeCompare(b.name, getLocale()))
  const [pinned, setPinned] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)
  const activeName = hovered ?? pinned ?? sorted[0]?.name ?? null
  const active = sorted.find((f) => f.name === activeName) ?? null
  const fp = useFootprintPreviewFor(active, template, density)
  const sym = useSymbolPreview(symbol?.kind ? { kind: symbol.kind } : null)
  const created = sorted.filter((f) => !f.exists).length
  const suffix = active?.plain_name && active.name.startsWith(active.plain_name) ? active.name.slice(active.plain_name.length) : ''

  return (
    <section
      aria-label={tr("Symbol und Footprints der Serie")}
      style={style}
      className={cn('@container flex min-w-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card', className)}
    >
      <div className="flex min-h-0 flex-1 flex-col @[40rem]:grid @[40rem]:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 shrink-0 flex-col @[40rem]:min-h-0 @[40rem]:border-r @[40rem]:border-line">
          <div className="px-4 pb-3 pt-3.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="micro-label">{tr("Symbol")}</span>
              {symbol && (
                <span className="min-w-0 truncate text-2xs text-fg-subtle">
                  {symbol.exists ? tr("vorhanden{v0}", { v0: symbol.library ? ` · ${libName(symbol.library)}` : '' }) : tr("wird angelegt")}
                </span>
              )}
            </div>
            {symbol ? (
              <>
                <div className="mt-2 h-24 overflow-hidden rounded-control border border-line bg-bg">
                  {sym.data?.spec ? (
                    <SymbolCanvas
                      spec={sym.data.spec}
                      interactive={false}
                      controls={false}
                      showInfo={false}
                      showGrid={false}
                      showPartTabs={false}
                      comment={comment ?? undefined}
                      className="size-full"
                      aria-label={tr("Symbol {v0}", { v0: symbol.name })}
                    />
                  ) : sym.isFetching ? (
                    <Skeleton className="m-2 h-[calc(100%-1rem)]" />
                  ) : (
                    <div className="flex size-full items-center justify-center text-fg-subtle">
                      <Component aria-hidden className="size-6" />
                    </div>
                  )}
                </div>
                <div className="mono mt-1.5 truncate text-ui font-medium text-fg">{symbol.name}</div>
              </>
            ) : (
              <p className="mt-2 text-xs text-warning-text">{tr("Kein sicheres Symbol – die Zeilen sind ungültig.")}</p>
            )}
          </div>

          <div className="flex flex-col border-t border-line @[40rem]:min-h-0 @[40rem]:flex-1">
            <div className="flex items-center justify-between gap-2 px-4 pt-3">
              <span className="micro-label">{tr("Footprints")}</span>
              <span className="text-2xs text-fg-subtle">
                {created ? tr("{v0} neu · ", { v0: formatNumber(created) }) : ''}
                {formatNumber(sorted.length - created)} {tr("vorhanden")}</span>
            </div>
            <div className="relative mx-3 mb-3 mt-2.5 h-40 shrink-0 overflow-hidden rounded-control border border-line bg-canvas @[40rem]:h-auto @[40rem]:min-h-32 @[40rem]:flex-1">
              {fp.data?.footprint ? (
                <FootprintCanvas
                  spec={fp.data.footprint}
                  interactive={false}
                  controls={false}
                  showLegend={false}
                  showInfo={false}
                  className="size-full"
                  aria-label={tr("Footprint {v0}", { v0: active?.name ?? '' })}
                />
              ) : fp.isFetching ? (
                <Skeleton className="m-3 h-[calc(100%-1.5rem)] bg-surface-3/30" />
              ) : (
                <div className={cn('flex size-full flex-col items-center justify-center gap-1.5 text-2xs', CHROME_MUTED.board)}>
                  <CircuitBoard aria-hidden className="size-5" />
                  {active ? tr("Keine Vorschau verfügbar") : tr("Keine Footprints")}
                </div>
              )}
              {active && (
                <span className={cn('mono absolute left-2 top-2 max-w-[calc(100%-1rem)] truncate rounded-md px-1.5 py-0.5 text-2xs', CHROME_SURFACE.board)}>
                  {active.name}
                </span>
              )}
              {active?.name_reason && (
                // warum der Name eine Kennung trägt – kurz auf der Leinwand, der volle Grund im Tooltip
                <Tooltip side="left" content={<span className="block max-w-xs leading-snug">{localizeMessage(active.name_reason)}</span>}>
                  <button
                    type="button"
                    className={cn(
                      'absolute bottom-2 left-2 flex max-w-[calc(100%-1rem)] items-center gap-1 rounded-md px-1.5 py-0.5 text-left text-2xs outline-none focus-ring',
                      CHROME_SURFACE.board,
                    )}
                  >
                    <Info aria-hidden className="size-3 shrink-0" />
                    <span className="min-w-0 truncate">
                      {tr("Kennung")} <span className="mono">{suffix || '…'}</span>: {nameReasonTopic(active.name_reason)}
                    </span>
                    <span className="sr-only"> – {localizeMessage(active.name_reason)}</span>
                  </button>
                </Tooltip>
              )}
            </div>
          </div>
        </div>
        <div className="flex min-h-24 min-w-0 flex-1 flex-col border-t border-line @[40rem]:min-h-0 @[40rem]:border-t-0">
          <ul className="flex min-h-0 flex-1 flex-col gap-0.5 overflow-y-auto p-2">
            {sorted.map((f, i) => {
              const isActive = f.name === activeName
              const reasonId = f.name_reason ? `${uid}-reason-${i}` : undefined
              return (
                <li key={f.name}>
                  <button
                    type="button"
                    aria-pressed={pinned === f.name}
                    aria-describedby={reasonId}
                    onMouseEnter={() => setHovered(f.name)}
                    onMouseLeave={() => setHovered(null)}
                    onFocus={() => setHovered(f.name)}
                    onBlur={() => setHovered(null)}
                    onClick={() => setPinned((p) => (p === f.name ? null : f.name))}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left outline-none transition-colors focus-ring',
                      isActive ? 'bg-surface-2' : 'hover:bg-surface-2',
                    )}
                  >
                    <span className="mono min-w-0 flex-1 truncate text-xs text-fg" title={f.name}>
                      <FootprintName footprint={f} />
                    </span>
                    {f.size && <span className="mono shrink-0 text-2xs text-fg-subtle">{f.size}</span>}
                    {f.exists ? <Badge variant="neutral">{tr("vorhanden")}</Badge> : <Badge variant="info">{tr("neu")}</Badge>}
                    <span className="w-10 shrink-0 text-right text-2xs tabular-nums text-fg-muted">
                      {formatNumber(usage[f.name] ?? 0)}
                    </span>
                  </button>
                  {reasonId && (
                    <span id={reasonId} hidden>
                      {localizeMessage(f.name_reason ?? '')}
                    </span>
                  )}
                </li>
              )
            })}
          </ul>
          {sorted.length > 0 && (
            <p className="shrink-0 border-t border-line px-4 py-2 text-2xs text-fg-subtle">
              {tr("Zahl rechts = Bauteile je Footprint. Neue Footprints entstehen nach IPC-7351B im Hausstil.")}</p>
          )}
        </div>
      </div>
    </section>
  )
}
