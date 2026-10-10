/**
 * Bauteile des Berichts mit Änderungen oder Problemen – virtualisiert (TanStack Virtual, Zeilenhöhe gemessen), nach
 * Bibliothek gruppiert: Name, Art, Herkunft, je Regel die Änderung als kurze Zeile, Probleme als Warnung. Suche
 * (Name, Bibliothek, Meldung), Filter nach Art und – aus der Zusammenfassung – nach Regel. Die Liste scrollt in sich
 * (Tab-Stopp mit Pfeiltasten, solange sie keine Bedienelemente enthält).
 */
import { useVirtualizer } from '@tanstack/react-virtual'
import { CircuitBoard, Search, Shapes, TriangleAlert, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ConformComponentReport, ConformReport } from '@/api/housestyle'
import { libraryKey } from '@/api/libraries'
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  IconButton,
  Input,
  PathText,
  ScrollArea,
  SegmentedControl,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import {
  joinDe,
  KIND_LABEL,
  libraryFileKind,
  localizeDecimals,
  PROBLEMS_FILTER,
  ruleLabel,
  SOURCE_LABEL,
  splitPath,
  type Kind,
} from './model'

interface LibraryRow {
  type: 'library'
  key: string
  library: string
  count: number
}
interface ComponentRow {
  type: 'component'
  key: string
  item: ConformComponentReport
}
type Row = LibraryRow | ComponentRow

const estimate = (row: Row | undefined) =>
  !row ? 40 : row.type === 'library' ? 31 : 37 + 18 * (row.item.changes.length + row.item.problems.length)

function matchesRule(item: ConformComponentReport, filter: string[]): boolean {
  if (!filter.length) return true
  if (filter.includes(PROBLEMS_FILTER) && item.problems.length > 0) return true
  return item.changes.some((c) => filter.includes(c.rule))
}

function matchesQuery(item: ConformComponentReport, terms: string[]): boolean {
  if (!terms.length) return true
  const hay = [
    item.name,
    item.library,
    ...item.changes.map((c) => `${ruleLabel(c.rule)} ${c.message}`),
    ...item.problems,
  ]
    .join('\n')
    .toLowerCase()
  return terms.every((t) => hay.includes(t))
}

/** Zeilen: je Bibliothek (Reihenfolge des Berichts) eine Überschrift und ihre Bauteile */
function groupRows(items: ConformComponentReport[], order: string[]): Row[] {
  const groups = new Map<string, ConformComponentReport[]>()
  for (const key of order) groups.set(libraryKey(key), [])
  for (const item of items) {
    const key = libraryKey(item.library)
    const list = groups.get(key)
    if (list) list.push(item)
    else groups.set(key, [item])
  }
  const rows: Row[] = []
  for (const [key, list] of groups) {
    if (!list.length) continue
    rows.push({ type: 'library', key: `lib:${key}`, library: list[0].library, count: list.length })
    list.forEach((item, i) => rows.push({ type: 'component', key: `${key}|${item.kind}|${item.name}|${i}`, item }))
  }
  return rows
}

export interface ComponentListProps {
  report: ConformReport
  /** Regeln aus der Zusammenfassung (leer = alle; {@link PROBLEMS_FILTER} = Bauteile mit Problemen) */
  ruleFilter: string[]
  onClearRuleFilter: () => void
}

export function ComponentList({ report, ruleFilter, onClearRuleFilter }: ComponentListProps) {
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<'all' | Kind>('all')
  const counts = useMemo(() => {
    const out = { symbol: 0, footprint: 0 }
    for (const c of report.components) out[c.kind] += 1
    return out
  }, [report.components])
  const bothKinds = counts.symbol > 0 && counts.footprint > 0
  const effectiveKind = bothKinds ? kind : 'all'
  const terms = useMemo(() => query.trim().toLowerCase().split(/\s+/).filter(Boolean), [query])

  const items = useMemo(
    () =>
      report.components.filter(
        (c) =>
          (effectiveKind === 'all' || c.kind === effectiveKind) && matchesRule(c, ruleFilter) && matchesQuery(c, terms),
      ),
    [report.components, effectiveKind, ruleFilter, terms],
  )
  const order = useMemo(() => report.libraries.map((l) => l.library), [report.libraries])
  const rows = useMemo(() => groupRows(items, order), [items, order])

  const scrollRef = useRef<HTMLDivElement | null>(null)
  // TanStack Virtual verwaltet seinen Zustand selbst (nicht mit dem React Compiler memoisierbar) – bewusst so
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => estimate(rows[index]),
    getItemKey: (index) => rows[index]?.key ?? index,
    overscan: 8,
  })
  // neuer Filter bzw. neue Suche → wieder oben beginnen
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [items])

  const filtered = items.length !== report.components.length
  const ruleNames = ruleFilter.map((r) => (r === PROBLEMS_FILTER ? 'Probleme' : ruleLabel(r)))
  const resetAll = () => {
    setQuery('')
    setKind('all')
    onClearRuleFilter()
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Bauteile"
        description={
          report.truncated
            ? `Mit Änderungen oder Problemen – die ersten ${formatNumber(report.components.length)}, nach Bibliothek`
            : 'Mit Änderungen oder Problemen, nach Bibliothek'
        }
      />
      <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5">
        {bothKinds && (
          <SegmentedControl<'all' | Kind>
            size="sm"
            aria-label="Nach Art filtern"
            value={effectiveKind}
            onValueChange={setKind}
            options={[
              { value: 'all', label: `Alle ${formatNumber(report.components.length)}` },
              { value: 'symbol', label: `${KIND_LABEL.symbol} ${formatNumber(counts.symbol)}` },
              { value: 'footprint', label: `${KIND_LABEL.footprint} ${formatNumber(counts.footprint)}` },
            ]}
          />
        )}
        <Input
          size="sm"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && query) {
              e.stopPropagation()
              setQuery('')
            }
          }}
          placeholder="Name, Bibliothek, Änderung …"
          aria-label="Bauteile durchsuchen"
          prefix={<Search />}
          suffix={
            query ? (
              <IconButton size="xs" label="Suche leeren" icon={<X />} onClick={() => setQuery('')} tooltip={false} />
            ) : undefined
          }
          containerClassName="w-56 min-w-0 flex-1 basis-40 @[60rem]:max-w-72"
        />
        <span className="ml-auto text-xs text-fg-subtle" aria-live="polite">
          {filtered
            ? `${formatNumber(items.length)} von ${formatNumber(report.components.length)}`
            : plural(items.length, 'Bauteil', 'Bauteile')}
        </span>
      </div>
      {ruleFilter.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-line bg-accent-soft/40 px-4 py-1.5 text-2xs text-fg-muted">
          <span>
            Nur <span className="font-medium text-fg">{joinDe(ruleNames)}</span>
          </span>
          <Button size="xs" variant="link" className="text-2xs" onClick={onClearRuleFilter}>
            Filter aufheben
          </Button>
        </div>
      )}

      {rows.length === 0 ? (
        <div className="border-t border-line">
          <EmptyState
            size="sm"
            illustration="search-empty"
            title="Keine Treffer"
            description="Kein Bauteil passt zu Suche und Filter."
            actions={
              <Button size="sm" onClick={resetAll}>
                Filter zurücksetzen
              </Button>
            }
          />
        </div>
      ) : (
        <ScrollArea
          viewportRef={scrollRef}
          viewportClassName="max-h-[min(40rem,calc(100dvh-15rem))]"
          aria-label="Bauteile mit Änderungen"
        >
          <div className="relative w-full border-t border-line" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((v) => {
              const row = rows[v.index]
              if (!row) return null
              return (
                <div
                  key={v.key}
                  data-index={v.index}
                  ref={virtualizer.measureElement}
                  className="absolute left-0 top-0 w-full"
                  style={{ transform: `translateY(${v.start}px)` }}
                >
                  {row.type === 'library' ? (
                    <LibraryHeading row={row} first={v.index === 0} />
                  ) : (
                    <ComponentItem item={row.item} highlight={ruleFilter} />
                  )}
                </div>
              )
            })}
          </div>
        </ScrollArea>
      )}

      {report.truncated && (
        <p className="border-t border-line px-4 py-2 text-2xs leading-snug text-fg-subtle">
          Sehr viele Abweichungen – die Liste zeigt die ersten {formatNumber(report.components.length)} Bauteile. Die
          Zahlen der Zusammenfassung zählen alle; „Anwenden“ ändert alle.
        </p>
      )}
    </Card>
  )
}

function LibraryHeading({ row, first }: { row: LibraryRow; first: boolean }) {
  const { folder, name } = splitPath(row.library)
  const Icon = libraryFileKind(row.library) === 'schlib' ? Shapes : CircuitBoard
  return (
    <h3
      className={cn(
        'flex min-w-0 items-center gap-2 bg-[color-mix(in_oklab,var(--pf-surface-2)_60%,transparent)] px-4 py-1.5 text-xs font-normal',
        !first && 'border-t border-line',
      )}
    >
      <Icon aria-hidden className="size-3.5 shrink-0 text-fg-muted" />
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <span className="font-semibold text-fg">{name}</span>
        {folder && <PathText path={folder} className="ml-2 text-2xs text-fg-subtle" />}
      </span>
      <span className="ml-auto shrink-0 text-2xs text-fg-subtle">{plural(row.count, 'Bauteil', 'Bauteile')}</span>
    </h3>
  )
}

function ComponentItem({ item, highlight }: { item: ConformComponentReport; highlight: string[] }) {
  const Icon = item.kind === 'symbol' ? Shapes : CircuitBoard
  return (
    <div className="flex gap-2.5 border-t border-line px-4 py-2">
      <Icon aria-hidden className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <span className="mono text-xs font-semibold text-fg [overflow-wrap:anywhere]">{item.name}</span>
          <span className="sr-only">
            {item.kind === 'symbol' ? 'Symbol' : 'Footprint'} in {splitPath(item.library).name}
          </span>
          <Badge variant="outline" className="font-normal">
            {SOURCE_LABEL[item.source] ?? item.source}
          </Badge>
        </div>
        {item.changes.length > 0 && (
          <ul className="mt-1 flex flex-col gap-0.5" aria-label="Änderungen">
            {item.changes.map((c, i) => (
              <li
                key={`${c.rule}-${i}`}
                className="grid grid-cols-[7.25rem_minmax(0,1fr)] gap-x-2 text-xs leading-[18px]"
              >
                <span
                  className={cn(
                    'truncate',
                    highlight.includes(c.rule) ? 'font-medium text-accent-text' : 'text-fg-subtle',
                  )}
                >
                  {ruleLabel(c.rule)}
                  <span className="sr-only">:</span>
                </span>
                <span className="min-w-0 text-fg-muted [overflow-wrap:anywhere]">{localizeDecimals(c.message)}</span>
              </li>
            ))}
          </ul>
        )}
        {item.problems.map((p, i) => (
          <p key={i} className="mt-1 flex items-start gap-1.5 text-xs leading-[18px] text-warning-text">
            <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{p}</span>
          </p>
        ))}
      </div>
    </div>
  )
}
