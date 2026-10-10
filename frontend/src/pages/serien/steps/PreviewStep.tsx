import { localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Schritt 4 – Vorschau: alle Zeilen der Serie mit Status (neu/vorhanden/Konflikt/ungültig) und Hinweisen in einer
 * virtualisierten Tabelle, Filter nach Status, Suche, „MPN prüfen“; rechts Symbol und Footprints (neue werden beim
 * Erzeugen generiert). Werte der Reihe, die keine Zeile ergeben (`skipped_by_size`), stehen als eigener Hinweis über
 * der Tabelle. Die Tabelle ist nur so hoch wie ihre Zeilen (höchstens bis zum Fensterrand). Es wird nichts geschrieben.
 */
import type { GridApi } from 'ag-grid-community'
import { CircleSlash, ListX, RefreshCw, Search } from 'lucide-react'
import { lazy, Suspense, useCallback, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { errorMessage } from '@/api/client'
import { useCategories } from '@/api/library'
import type { RowStatus, SeriesPreview, SeriesTemplate } from '@/api/series'
import { useElementSize } from '@/components/preview'
import { Button, Callout, EmptyState, Input, SegmentedControl, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural, pluralNoun } from '@/lib/format'
import { StepHeading } from '../components/StepHeading'
import type { Density } from '../model/settings'
import { exampleValue } from '../model/template'
import { parseAmount } from '../model/values'
import {
  isGenericNote,
  isSkippedWarning,
  midSentence,
  reasonKey,
  ROW_STATUS,
  rowReason,
  skippedSizes,
  STATUS_ORDER,
  TONE_DOT,
} from '../model/status'
import { FootprintPanel } from './preview/FootprintPanel'
import { MpnCheck } from './preview/MpnCheck'
import type { GridRow } from './preview/PreviewGrid'

const PreviewGrid = lazy(() => import('./preview/PreviewGrid'))

type Filter = 'all' | RowStatus
type View = 'rows' | 'footprints'

/** So viele Gründe für „nicht angelegt“ erscheinen über der Tabelle */
const TOP_REASONS = 4

/** Höhe der Tabelle: Kopf 34 px + Zeilen à 32 px + Rand und Platz für die waagrechte Bildlaufleiste */
const GRID_HEADER = 34
const GRID_ROW = 32
const GRID_CHROME = 16
/** Vor der ersten Messung: höchstens bis kurz vor die Fußleiste, mindestens 22 rem */
const GRID_MAX = 'max(22rem, calc(100dvh - 24rem))'
/** Unter Tabelle und Seitenleiste frei: Fußleiste des Assistenten (61 px) + Abstand zum Inhalt */
const BOTTOM_RESERVE = 88

/**
 * Platz von der Oberkante zweier Elemente bis zum unteren Fensterrand (abzüglich Fußleiste) – in px, gemessen wie ohne
 * Scrollen. Neu gemessen bei Fenstergröße und wenn sich der Inhalt darüber ändert (`layoutKey`).
 */
function useRoomBelow(
  first: RefObject<HTMLElement | null>,
  second: RefObject<HTMLElement | null>,
  layoutKey: string,
): [number | null, number | null] {
  const [room, setRoom] = useState<[number | null, number | null]>([null, null])
  useLayoutEffect(() => {
    const below = (el: HTMLElement | null, scroll: number) =>
      el ? Math.round(window.innerHeight - (el.getBoundingClientRect().top + scroll) - BOTTOM_RESERVE) : null
    const measure = () => {
      const scroll = document.getElementById('main')?.scrollTop ?? 0
      const next: [number | null, number | null] = [below(first.current, scroll), below(second.current, scroll)]
      setRoom((cur) => (cur[0] === next[0] && cur[1] === next[1] ? cur : next))
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [first, second, layoutKey])
  return room
}

interface ReasonGroup {
  status: RowStatus
  reason: string
  count: number
}

export interface PreviewStepProps {
  template: SeriesTemplate
  categoryLabel: string
  preview: SeriesPreview | undefined
  loading: boolean
  /** Vorschau passt (noch) nicht zur Auswahl – wird gerade neu berechnet */
  stale: boolean
  error: unknown
  onRetry: () => void
  sizes: string[]
  density: Density
  internalScheme: boolean
}

export function PreviewStep({
  template,
  categoryLabel,
  preview,
  loading,
  stale,
  error,
  onRetry,
  sizes,
  density,
  internalScheme,
}: PreviewStepProps) {
  const { t: tr } = useI18n()
  const [filter, setFilter] = useState<Filter>('all')
  const [view, setView] = useState<View>('rows')
  const [sectionRef, sectionSize] = useElementSize<HTMLElement>()
  const narrow = sectionSize.width > 0 && sectionSize.width < 992
  const [search, setSearch] = useState('')
  const api = useRef<GridApi<GridRow> | null>(null)
  const categories = useCategories()
  const labels = useMemo(() => {
    const def = categories.data?.find((c) => c.table === template.category)
    return Object.fromEntries((def?.fields ?? []).map((f) => [f.column, tr(f.label)]))
  }, [categories.data, template.category, tr])

  const rows = useMemo<GridRow[]>(() => (preview?.rows ?? []).map((r, index) => ({ ...r, index })), [preview])
  const shown = useMemo(() => (filter === 'all' ? rows : rows.filter((r) => r.status === filter)), [rows, filter])
  const usage = useMemo(() => {
    const out: Record<string, number> = {}
    for (const r of rows) if (r.footprint) out[r.footprint.name] = (out[r.footprint.name] ?? 0) + 1
    return out
  }, [rows])

  // Hinweise für alle Zeilen (z. B. „Lieferbarkeit nicht geprüft …“) stehen einmal über der Tabelle; Gründe für
  // „Konflikt“/„ungültig“ werden gezählt (häufigste zuerst)
  const { common, reasons } = useMemo(() => {
    const counts = new Map<string, number>()
    for (const r of rows) for (const m of new Set(r.messages)) counts.set(m, (counts.get(m) ?? 0) + 1)
    const blocked = rows.some((r) => r.status === 'invalid' || r.status === 'conflict')
    const commonNotes = new Map<string, number>()
    for (const [m, n] of counts) if (isGenericNote(m) || (!blocked && rows.length > 1 && n === rows.length)) commonNotes.set(m, n)
    const groups = new Map<string, ReasonGroup>()
    for (const r of rows) {
      if (r.status !== 'invalid' && r.status !== 'conflict') continue
      const reason = reasonKey(rowReason(r) ?? tr(ROW_STATUS[r.status].description))
      const key = `${r.status}|${reason}`
      const g = groups.get(key) ?? { status: r.status, reason, count: 0 }
      g.count += 1
      groups.set(key, g)
    }
    return { common: commonNotes, reasons: [...groups.values()].sort((a, b) => b.count - a.count) }
  }, [rows, tr])
  const hiddenMessages = useMemo(() => new Set(common.keys()), [common])
  const skippedTotal = preview?.skipped_total ?? 0
  const notes = useMemo(
    () => [
      ...(preview?.warnings ?? []).filter((w) => !(skippedTotal > 0 && isSkippedWarning(w))).map(localizeMessage),
      ...[...common].map(([m, n]) => (n === rows.length ? tr("{v0} (alle Zeilen)", { v0: localizeMessage(m) }) : `${localizeMessage(m)} (${plural(n, tr("Zeile"), tr("Zeilen"))})`)),
    ],
    [preview?.warnings, common, rows.length, skippedTotal, tr],
  )
  /** Kommentar eines typischen Bauteils der Serie („10k“, „100n“) für die Symbolvorschau */
  const sampleComment = useMemo(() => {
    const target = Math.log10(exampleValue(template.value_unit))
    let best: { comment: string; score: number } | null = null
    for (const r of rows) {
      if ((r.status !== 'new' && r.status !== 'exists') || r.jumper || !r.values.Comment) continue
      const v = parseAmount(r.value)
      const score = v !== null && v > 0 ? Math.abs(Math.log10(v) - target) : 99
      if (!best || score < best.score) best = { comment: r.values.Comment, score }
    }
    return best?.comment ?? null
  }, [rows, template.value_unit])
  const blockedCount = reasons.reduce((n, g) => n + g.count, 0)

  const showReason = (g: ReasonGroup) => {
    setView('rows')
    setFilter(g.status)
    setSearch(g.reason.replace(/[.…]+$/, ''))
  }

  const reveal = useCallback(
    (row: GridRow) => {
      setSearch('')
      setView('rows')
      if (filter !== 'all' && filter !== row.status) setFilter('all')
      // nach dem Neuzeichnen: hinscrollen, aufblinken lassen, Fokus auf die Zeile
      window.setTimeout(() => {
        const grid = api.current
        const node = grid?.getRowNode(String(row.index))
        if (!grid || !node || node.rowIndex === null) return
        const index = node.rowIndex
        grid.ensureIndexVisible(index, 'middle')
        // erst nach dem Rendern der Zeile fokussieren (sonst bleibt der Fokus im Leeren)
        window.setTimeout(() => {
          grid.setFocusedCell(index, 'pn')
          grid.flashCells({ rowNodes: [node] })
        }, 120)
      }, 150)
    },
    [filter],
  )

  const counts = preview?.counts ?? {}
  const total = counts.total ?? 0
  // Tabelle nur so hoch wie nötig (wenige Zeilen → kurze Tabelle, mindestens Platz für „Keine Zeile passt“), höchstens
  // bis zur Fußleiste; die Seitenleiste mit Symbol und Footprints endet ebenfalls dort
  const areaRef = useRef<HTMLDivElement>(null)
  const gridRef = useRef<HTMLDivElement>(null)
  const [areaRoom, gridRoom] = useRoomBelow(
    areaRef,
    gridRef,
    [Boolean(preview), Boolean(error), notes.length, reasons.length, skippedTotal, narrow, view].join('|'),
  )
  const rowsHeight = GRID_HEADER + Math.max(shown.length, 4) * GRID_ROW + GRID_CHROME
  const gridHeight = gridRoom !== null ? `${Math.min(rowsHeight, Math.max(352, gridRoom))}px` : `min(${GRID_MAX}, ${rowsHeight}px)`
  const panelHeight = areaRoom !== null ? Math.max(narrow ? 352 : 416, areaRoom) : null

  return (
    <section ref={sectionRef} aria-labelledby="serien-vorschau" className="flex min-h-0 flex-col gap-4">
      <StepHeading
        id="serien-vorschau"
        title={tr("Vorschau")}
        description={
          preview
            ? tr("{v0} für {v1} – geschrieben wird erst beim Erzeugen.", { v0: plural(total, tr("Zeile"), tr("Zeilen")), v1: categoryLabel })
            : tr("PartForge berechnet jede Teilenummer und prüft sie gegen die Bibliothek.")
        }
        actions={
          preview ? (
            <>
              {narrow && (
                <SegmentedControl<View>
                  size="sm"
                  aria-label={tr("Ansicht der Vorschau")}
                  value={view}
                  onValueChange={setView}
                  options={[
                    { value: 'rows', label: tr("Bauteile ({v0})", { v0: formatNumber(total) }) },
                    { value: 'footprints', label: tr("Footprints ({v0})", { v0: formatNumber(preview.footprints.length) }) },
                  ]}
                />
              )}
              <MpnCheck
                templateId={template.id}
                templateTitle={template.title}
                rows={rows}
                sizes={sizes}
                onReveal={reveal}
              />
            </>
          ) : undefined
        }
      />

      {error && !preview ? (
        <Callout
          tone="danger"
          urgent
          title={tr("Vorschau nicht möglich")}
          actions={
            <Button size="sm" variant="secondary" leftIcon={<RefreshCw />} onClick={onRetry}>
              {tr("Erneut versuchen")}</Button>
          }
        >
          {errorMessage(error)}
        </Callout>
      ) : !preview ? (
        <div className="grid grid-cols-1 gap-4 @[62rem]:grid-cols-[minmax(0,1fr)_18.5rem]">
          <div className="flex flex-col gap-3">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-[max(22rem,calc(100dvh-24rem))] rounded-card" />
          </div>
          <Skeleton className="h-[26rem] rounded-card" />
        </div>
      ) : (
        <>
          {error ? (
            <Callout tone="danger" title={tr("Die Auswahl lässt sich so nicht prüfen")} live>
              {errorMessage(error)} {tr("– angezeigt wird die letzte gültige Vorschau.")}</Callout>
          ) : null}
          {notes.length > 0 && (
            <Callout tone="warning" title={plural(notes.length, tr("Hinweis zur Serie"), tr("Hinweise zur Serie"))}>
              <ul className="flex list-disc flex-col gap-0.5 pl-4">
                {notes.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Callout>
          )}
          {reasons.length > 0 && (
            <section
              aria-labelledby="serien-gruende"
              className="flex flex-col gap-2 rounded-card border border-line bg-surface px-4 py-3 shadow-card"
            >
              <h3 id="serien-gruende" className="flex items-center gap-2 text-ui font-medium text-fg">
                <CircleSlash aria-hidden className="size-4 text-fg-subtle" />
                {plural(blockedCount, tr("Zeile wird"), tr("Zeilen werden"))} {tr("nicht angelegt")}<span className="font-normal text-fg-muted">{tr("– häufigste Gründe")}</span>
              </h3>
              <ul className="flex flex-col">
                {reasons.slice(0, TOP_REASONS).map((g) => (
                  <li key={`${g.status}|${g.reason}`}>
                    <button
                      type="button"
                      onClick={() => showReason(g)}
                      className="group/reason -mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-control px-2 py-1.5 text-left text-xs outline-none transition-colors hover:bg-surface-2 focus-ring"
                    >
                      <span className="mono w-14 shrink-0 text-right font-semibold tabular-nums text-fg">
                        {formatNumber(g.count)}
                      </span>
                      <span className="flex w-24 shrink-0 items-center gap-1.5 text-fg-muted">
                        <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', TONE_DOT[ROW_STATUS[g.status].tone])} />
                        {tr(ROW_STATUS[g.status].label)}
                      </span>
                      <span className="min-w-0 flex-1 text-fg">{localizeMessage(g.reason)}</span>
                      <span className="shrink-0 text-2xs text-fg-subtle opacity-0 transition-opacity group-hover/reason:opacity-100 group-focus-visible/reason:opacity-100">
                        {tr("Zeilen zeigen")}</span>
                    </button>
                  </li>
                ))}
              </ul>
              {reasons.length > TOP_REASONS && (
                <p className="text-2xs text-fg-subtle">
                  {plural(reasons.length - TOP_REASONS, tr("weiterer Grund"), tr("weitere Gründe"))} {tr("– Filter „Konflikte“ bzw. „Ungültig“ zeigt alle Zeilen.")}</p>
              )}
            </section>
          )}
          {skippedTotal > 0 && (
            <SkippedNote total={skippedTotal} bySize={skippedSizes(preview.skipped_by_size, sizes)} reason={preview.skipped_reason} />
          )}
          <div ref={areaRef} className="grid min-h-0 grid-cols-1 items-start gap-4 @[62rem]:grid-cols-[minmax(0,1fr)_18.5rem]">
            {(!narrow || view === 'rows') && (
            <div className="flex min-w-0 flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div role="group" aria-label={tr("Zeilen nach Status filtern")} className="flex flex-wrap items-center gap-1">
                  {(['all', ...STATUS_ORDER] as Filter[]).map((f) => {
                    const n = f === 'all' ? total : (counts[f] ?? 0)
                    const active = filter === f
                    const disabled = n === 0 && !active
                    return (
                      <button
                        key={f}
                        type="button"
                        aria-pressed={active}
                        disabled={disabled}
                        onClick={() => setFilter(f)}
                        className={cn(
                          'inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium outline-none transition-colors focus-ring',
                          'disabled:pointer-events-none disabled:opacity-45',
                          active
                            ? 'border-accent/45 bg-accent-soft text-accent-text'
                            : 'border-line-strong bg-surface-2 text-fg-muted hover:border-line-control hover:text-fg',
                        )}
                      >
                        {f !== 'all' && (
                          <span aria-hidden className={cn('size-1.5 rounded-full', TONE_DOT[ROW_STATUS[f].tone])} />
                        )}
                        {f === 'all' ? tr("Alle") : tr(ROW_STATUS[f].plural)}
                        <span className={cn('tabular-nums', active ? 'text-accent-text' : 'text-fg-subtle')}>
                          {formatNumber(n)}
                        </span>
                      </button>
                    )
                  })}
                </div>
                <Input
                  size="sm"
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={tr("In der Vorschau suchen …")}
                  aria-label={tr("In der Vorschau suchen")}
                  prefix={<Search />}
                  containerClassName="w-60"
                />
              </div>
              <div ref={gridRef} className={cn('relative transition-opacity', (stale || loading) && 'opacity-70')}>
                {total === 0 ? (
                  <div className="flex h-[22rem] items-center justify-center rounded-card border border-line bg-surface">
                    <EmptyState
                      illustration="search-empty"
                      title={tr("Keine Bauteile")}
                      description={tr("Mit dieser Auswahl entstehen keine Bauteile – Bauformen, Bereich oder Varianten anpassen.")}
                    />
                  </div>
                ) : (
                  <Suspense fallback={<Skeleton className="rounded-card" style={{ height: gridHeight }} />}>
                    <PreviewGrid
                      rows={shown}
                      hiddenMessages={hiddenMessages}
                      template={template}
                      labels={labels}
                      internalScheme={internalScheme}
                      density={density}
                      quickFilter={search}
                      onApiReady={(a) => {
                        api.current = a
                      }}
                      footprints={preview.footprints}
                      style={{ height: gridHeight }}
                    />
                  </Suspense>
                )}
              </div>
            </div>
            )}
            {(!narrow || view === 'footprints') && (
              <FootprintPanel
                template={template}
                symbol={preview.symbol ?? null}
                footprints={preview.footprints}
                usage={usage}
                density={density}
                comment={sampleComment}
                className={
                  panelHeight !== null
                    ? undefined
                    : narrow
                      ? 'h-[max(22rem,calc(100dvh-24rem+2.75rem))]'
                      : 'max-h-[max(26rem,calc(100dvh-24rem+2.75rem))]'
                }
                style={panelHeight !== null ? (narrow ? { height: panelHeight } : { maxHeight: panelHeight }) : undefined}
              />
            )}
          </div>
        </>
      )}
    </section>
  )
}

/** Werte der gewählten Reihe bzw. des Bereichs, die laut Datenblatt mit dieser Auswahl keine Zeile ergeben */
function SkippedNote({ total, bySize: sizes, reason }: { total: number; bySize: [string, number][]; reason: string | null }) {
  const { t: tr } = useI18n()
  return (
    <section
      aria-label={tr("Ausgelassene Werte")}
      className="flex items-start gap-3 rounded-card border border-line bg-surface px-4 py-3 shadow-card"
    >
      <ListX aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-subtle" />
      <div className="min-w-0 flex-1">
        <p className="text-ui text-fg">
          <span className="mono font-semibold">{formatNumber(total)}</span>{' '}
          {pluralNoun(total, tr("Wert der Reihe ist"), tr("Werte der Reihe sind"))} {tr("ausgelassen")}<span className="text-fg-muted"> – {midSentence(localizeMessage(reason ?? tr("laut Datenblatt mit dieser Auswahl nicht lieferbar")))}.</span>
        </p>
        <p className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs text-fg-muted">
          {sizes.map(([size, n]) => (
            <span key={size} className="whitespace-nowrap">
              <span className="mono text-fg">{size}</span> {formatNumber(n)}
            </span>
          ))}
          <span className="text-fg-subtle">{tr("Sie erscheinen nicht in der Tabelle und werden nicht angelegt.")}</span>
        </p>
      </div>
    </section>
  )
}
