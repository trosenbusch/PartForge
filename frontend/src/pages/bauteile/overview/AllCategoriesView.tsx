import { metadataLabel, t, useI18n } from '@/lib/i18n'
/**
 * „Alle Kategorien“ (`/bauteile`): Suche über die ganze Bibliothek (Teilenummer, MPN, Wert, Beschreibung) und die
 * Kategorien als Karten mit Anzahl und offenen Punkten (ohne Symbol/Footprint/Datenblatt). Ohne Bauteile ein
 * leerer Zustand mit den Wegen zum ersten Bauteil.
 */
import { useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { ArrowRight, FileScan, Layers, Plus, Search, Upload, X } from 'lucide-react'
import { useRef } from 'react'
import { useNavigate } from 'react-router'
import { errorMessage } from '@/api/client'
import { libraryApi, useCategories, useLibraryStats, type CategoryDef } from '@/api/library'
import { CATEGORY_GROUP_ORDER, CATEGORY_GROUPS } from '@/components/data/categoryTreeItems'
import { CategoryIcon } from '@/components/data/CategoryIcon'
import { Button, Callout, EmptyState, Kbd, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, formatRelativeTime, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { displayValue, parseDateText } from '../model/fields'
import { useDebounced } from '../model/useDebounced'

export interface AllCategoriesViewProps {
  search: string
  onSearchChange: (search: string) => void
  onNewPart: () => void
  onImport: () => void
}

const stagger = { hidden: {}, show: { transition: { staggerChildren: 0.018 } } }
const item = {
  hidden: { opacity: 0, y: 6 },
  show: { opacity: 1, y: 0, transition: { duration: 0.24, ease: [0.16, 1, 0.3, 1] as const } },
}

export function AllCategoriesView({ search, onSearchChange, onNewPart, onImport }: AllCategoriesViewProps) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const categories = useCategories()
  const stats = useLibraryStats()
  const inputRef = useRef<HTMLInputElement>(null)
  useHotkey('mod+f', () => inputRef.current?.focus(), { allowInInputs: true })
  const q = useDebounced(search.trim(), 220)
  const results = useQuery({
    queryKey: ['parts', 'global-search', q] as const,
    queryFn: ({ signal }) => libraryApi.search(q, 80, signal),
    enabled: q.length >= 2,
    placeholderData: (prev) => prev,
  })
  const total = (categories.data ?? []).reduce((s, c) => s + (c.part_count ?? 0), 0)
  const missing = new Map((stats.data?.categories ?? []).map((c) => [c.table, c]))
  const open = (c: CategoryDef) => navigate(`/bauteile/${encodeURIComponent(c.table)}`)

  if (categories.isSuccess && total === 0) {
    return (
      <div className="flex h-full items-center justify-center overflow-y-auto pl-4">
        <EmptyState
          size="lg"
          titleAs="h2"
          illustration="no-parts"
          title={t("Noch keine Bauteile in dieser Bibliothek")}
          description={t("Legen Sie eine komplette Serie an (z. B. alle E96-Widerstände in 0603), lesen Sie ein Datenblatt mit KI ein oder übernehmen Sie eine vorhandene Tabelle.")}
          actions={
            <>
              <Button variant="secondary" leftIcon={<Layers />} onClick={() => navigate('/serien')}>
                {t("Serien-Assistent")}
              </Button>
              <Button variant="spark" leftIcon={<FileScan />} onClick={() => navigate('/import')}>
                {t("Datenblatt importieren")}
              </Button>
              <Button variant="secondary" leftIcon={<Upload />} onClick={onImport}>
                {t("Tabelle importieren")}
              </Button>
              <Button variant="ghost" leftIcon={<Plus />} onClick={onNewPart}>
                {t("Einzelnes Bauteil")}
              </Button>
            </>
          }
        />
      </div>
    )
  }

  const grouped = groupCategories(categories.data ?? [])
  const showResults = q.length >= 2

  return (
    <div className="@container flex h-full min-h-0 flex-col gap-4 overflow-y-auto pb-6 pl-4 pr-1">
      {/* Suche über alle Kategorien */}
      <div className="sticky top-0 z-sticky -mb-1 bg-[linear-gradient(var(--pf-bg)_75%,transparent)] pb-2">
        <div className="flex h-10 items-center gap-2.5 rounded-button border border-line-control bg-control px-3 shadow-card transition-[border-color,box-shadow] focus-within:border-accent focus-within:shadow-[0_0_0_4px_var(--pf-accent-soft)]">
          <Search aria-hidden className="size-4 shrink-0 text-fg-subtle" />
          <input
            ref={inputRef}
            type="search"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && search) {
                e.preventDefault()
                onSearchChange('')
              }
            }}
            placeholder={t("In allen {1} Bauteilen suchen …", { 1: formatNumber(total) })}
            aria-label={t("In allen Bauteilen suchen")}
            aria-keyshortcuts="Control+F"
            className="h-full min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle [&::-webkit-search-cancel-button]:hidden"
          />
          {search ? (
            <button
              type="button"
              onClick={() => onSearchChange('')}
              aria-label={t("Suche leeren")}
              className="flex size-6 items-center justify-center rounded-control text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          ) : (
            <Kbd hotkey="mod+f" size="xs" />
          )}
        </div>
      </div>

      {showResults ? (
        <SearchResults
          query={q}
          loading={results.isFetching && !results.data}
          error={results.isError ? errorMessage(results.error) : null}
          hits={results.data ?? []}
          categories={categories.data ?? []}
          onOpen={(table, pn) => navigate(`/bauteile/${encodeURIComponent(table)}?pn=${encodeURIComponent(pn)}`)}
        />
      ) : categories.isPending ? (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
          {Array.from({ length: 12 }, (_, i) => (
            <Skeleton key={i} className="h-[92px] rounded-card" />
          ))}
        </div>
      ) : (
        <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col gap-5">
          {grouped.map(([group, list]) => (
            <section key={group} aria-labelledby={groupId(group)}>
              <div className="mb-2 flex items-baseline gap-2">
                <h2 id={groupId(group)} className="micro-label">
                  {t(group)}
                </h2>
                <span className="mono text-2xs text-fg-subtle">
                  {formatNumber(list.reduce((s, c) => s + (c.part_count ?? 0), 0))}
                </span>
              </div>
              <ul className="grid grid-cols-[repeat(auto-fill,minmax(15rem,1fr))] gap-3">
                {list.map((c) => {
                  const m = missing.get(c.table)
                  const count = c.part_count ?? 0
                  const issue = m ? missingSummary(m.missing_library_ref, m.missing_footprint_ref, m.missing_datasheet) : null
                  const values = c.fields.filter((f) => !f.common).slice(0, 3).map((f) => metadataLabel(f.label, t))
                  return (
                    <motion.li key={c.table} variants={item}>
                      <button
                        type="button"
                        onClick={() => open(c)}
                        className={cn(
                          'group/card relative flex w-full flex-col gap-3 overflow-hidden rounded-card border border-line bg-surface p-3.5 text-left shadow-card outline-none',
                          'transition-[border-color,transform,box-shadow] duration-150 hover:-translate-y-px hover:border-line-strong hover:shadow-raised focus-ring',
                        )}
                      >
                        <span
                          aria-hidden
                          className="pointer-events-none absolute -right-10 -top-12 size-28 rounded-full opacity-[0.07] blur-xl transition-opacity group-hover/card:opacity-[0.16]"
                          style={{ background: c.color }}
                        />
                        <span className="flex items-center gap-2.5">
                          <span
                            aria-hidden
                            className="flex size-8 items-center justify-center rounded-button border border-line-strong bg-surface-2"
                          >
                            <CategoryIcon name={c.icon} color={c.color} />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-ui font-semibold text-fg">{metadataLabel(c.label, t)}</span>
                            <span className="block truncate text-2xs text-fg-subtle" title={values.join(', ')}>
                              {values.length ? values.join(' · ') : t("Bezeichner {1}", { 1: c.prefix })}
                            </span>
                          </span>
                          <ArrowRight
                            aria-hidden
                            className="size-4 shrink-0 -translate-x-1 text-fg-subtle opacity-0 transition-[opacity,transform] group-hover/card:translate-x-0 group-hover/card:opacity-100"
                          />
                        </span>
                        <span className="flex items-end justify-between gap-2">
                          <span className="flex items-baseline gap-1.5">
                            <span className={cn('mono text-h3 font-semibold tabular-nums', count ? 'text-fg' : 'text-fg-subtle')}>
                              {formatNumber(count)}
                            </span>
                            <span className="text-xs text-fg-muted">{count === 1 ? t("Bauteil") : t("Bauteile")}</span>
                          </span>
                          <span className="min-w-0 truncate text-right text-2xs text-fg-subtle">
                            {count === 0 ? t("noch leer") : issue ? <span className="text-warning-text">{issue}</span> : t("vollständig")}
                          </span>
                        </span>
                      </button>
                    </motion.li>
                  )
                })}
              </ul>
            </section>
          ))}
          <RecentParts />
        </motion.div>
      )}
    </div>
  )
}

/** ID für eine Gruppenüberschrift („Passive Bauteile“ → „grp-passive-bauteile“) */
const groupId = (group: string) => `grp-${group.toLowerCase().replace(/[^a-z0-9äöüß]+/g, '-')}`

/**
 * Wichtigster offener Punkt einer Kategorie, gut lesbar: „3 ohne Symbol und Footprint“ (gleiche Anzahl), sonst
 * der größte Einzelpunkt.
 */
function missingSummary(symbol: number, footprint: number, datasheet: number): string | null {
  if (symbol && footprint && symbol === footprint) return t("{1} ohne Symbol und Footprint", { 1: formatNumber(symbol) })
  const items: [number, string][] = [
    [footprint, t("ohne Footprint")],
    [symbol, t("ohne Symbol")],
    [datasheet, t("ohne Datenblatt")],
  ]
  const top = items.filter(([n]) => n > 0).sort((a, b) => b[0] - a[0])[0]
  return top ? `${formatNumber(top[0])} ${top[1]}` : null
}

function groupCategories(list: CategoryDef[]): [string, CategoryDef[]][] {
  const map = new Map<string, CategoryDef[]>()
  for (const c of list) {
    const g = CATEGORY_GROUPS[c.table] ?? 'Weitere'
    map.set(g, [...(map.get(g) ?? []), c])
  }
  return [...map.entries()].sort(([a], [b]) => {
    const ia = CATEGORY_GROUP_ORDER.indexOf(a)
    const ib = CATEGORY_GROUP_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
}

function SearchResults({
  query,
  loading,
  error,
  hits,
  categories,
  onOpen,
}: {
  query: string
  loading: boolean
  error: string | null
  hits: Awaited<ReturnType<typeof libraryApi.search>>
  categories: CategoryDef[]
  onOpen: (table: string, pn: string) => void
}) {
  const { t } = useI18n()
  if (error) return <Callout tone="danger" title={t("Suche nicht möglich")}>{error}</Callout>
  if (loading) {
    return (
      <div className="flex flex-col gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-11" />
        ))}
      </div>
    )
  }
  if (!hits.length) {
    return (
      <EmptyState
        illustration="search-empty"
        titleAs="h2"
        title={t("Nichts zu „{1}“ gefunden", { 1: query })}
        description={t("Gesucht wird in Teilenummer, Hersteller-Teilenummer, Wert, Kommentar und Beschreibung aller Kategorien. Werte mit Einheit werden erkannt („10k“ findet „10 kΩ“).")}
      />
    )
  }
  const byTable = new Map(categories.map((c) => [c.table, c]))
  return (
    <section aria-label={t("Suchergebnisse für „{1}“", { 1: query })} className="flex flex-col gap-2">
      <p className="text-xs text-fg-muted" aria-live="polite">
        {plural(hits.length, t("Treffer"), t("Treffer"))}  {t("in")} {plural(new Set(hits.map((h) => h.table)).size, t("Kategorie"), t("Kategorien"))}
        {hits.length >= 80 && t(" – die besten 80")}
      </p>
      <ul className="divide-y divide-line overflow-hidden rounded-card border border-line bg-surface shadow-card">
        {hits.map((h) => {
          const cat = byTable.get(h.table)
          const valueField = cat?.fields.find((f) => f.column === cat.value_field)
          return (
            <li key={`${h.table}:${h.part_number}`}>
              <button
                type="button"
                onClick={() => onOpen(h.table, h.part_number)}
                className="group/hit grid w-full grid-cols-[minmax(0,11rem)_minmax(0,13rem)_minmax(0,7rem)_minmax(0,1fr)_auto] items-center gap-3 px-3.5 py-2.5 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset"
              >
                <span className="flex min-w-0 items-center gap-2 text-xs text-fg-muted">
                  <CategoryIcon name={h.icon} color={h.color} className="size-3.5" />
                  <span className="truncate">{metadataLabel(h.label, t)}</span>
                </span>
                <span className="mono truncate text-ui font-medium text-fg">{h.part_number}</span>
                <span className="mono truncate text-xs text-fg">{h.value ? displayValue(valueField, h.value) : '–'}</span>
                <span className="truncate text-xs text-fg-muted">
                  {h.description}
                  {h.manufacturer && <span className="text-fg-subtle"> · {h.manufacturer}</span>}
                </span>
                <ArrowRight aria-hidden className="size-3.5 text-fg-subtle opacity-0 transition-opacity group-hover/hit:opacity-100" />
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function RecentParts() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const stats = useLibraryStats()
  const recent = (stats.data?.recent_parts ?? [])
    .slice()
    .sort((a, b) => (parseDateText(b.modified) ?? 0) - (parseDateText(a.modified) ?? 0))
    .slice(0, 8)
  if (!recent.length) return null
  return (
    <section aria-labelledby="recent-parts">
      <h2 id="recent-parts" className="micro-label mb-2">
        {t("Zuletzt geändert")}
      </h2>
      <ul className="divide-y divide-line overflow-hidden rounded-card border border-line bg-surface shadow-card">
        {recent.map((r) => (
          <li key={`${r.table}:${r.part_number}`}>
            <button
              type="button"
              onClick={() => r.part_number && navigate(`/bauteile/${encodeURIComponent(r.table)}?pn=${encodeURIComponent(r.part_number)}`)}
              className="grid w-full grid-cols-[0.5rem_minmax(0,13rem)_minmax(0,1fr)_auto] items-center gap-3 px-3.5 py-2 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset"
            >
              <span aria-hidden className="size-2 rounded-full" style={{ background: r.color ?? 'var(--pf-fg-subtle)' }} />
              <span className="mono truncate text-ui text-fg">{r.part_number}</span>
              <span className="truncate text-xs text-fg-muted">
                {metadataLabel(r.label, t)}
                {r.description && <span className="text-fg-subtle"> · {r.description}</span>}
              </span>
              <span className="whitespace-nowrap text-2xs text-fg-subtle">
                {r.modified ? formatRelativeTime(parseDateText(r.modified) ?? r.modified) : ''}
                {r.author && ` · ${r.author}`}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
