import { t, useI18n } from '@/lib/i18n'
import { useVirtualizer } from '@tanstack/react-virtual'
import { ChevronRight, Search, X } from 'lucide-react'
import {
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from 'react'
import { STATE_LABELS, type ImportComponentState, type ImportSourceComponent, type ImportSourceFile } from '@/api/libimport'
import {
  Badge,
  Button,
  ChipGroup,
  EmptyState,
  IconButton,
  Input,
  Kbd,
  SegmentedControl,
  type CheckedState,
  type ChipOption,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatBytes, formatNumber, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import {
  buildRows,
  COMPONENT_STATES,
  componentKey,
  filterScan,
  KIND_TEXT,
  LIB_KINDS,
  type ComponentRow,
  type FileRow,
  type FileView,
  type GroupRow,
  type ImportPlan,
  type KindFilter,
  type LibKind,
  type ScanIndex,
  type TreeRow,
  type VisibleFile,
} from './model'
import { CheckMark, KindIcon, RelPath, StateBadge } from './ui'

/** Bauteil der Quelle für die Vorschau */
export interface PreviewTarget {
  file: ImportSourceFile
  component: ImportSourceComponent
}

export interface FileTreeProps {
  index: ScanIndex
  selected: ReadonlySet<string>
  onSelectedChange: (next: Set<string>) => void
  plan: ImportPlan
  /** anderer Zielordner als vorgeschlagen – „schon importiert“ der Dateien gilt dann nicht */
  retargeted: boolean
  /** Ziel einer Datei (für den gewählten Zielordner) */
  targetOf: (file: ImportSourceFile) => string | null
  replace: boolean
  /** Bauteil der angehefteten Vorschau (`componentKey`) */
  previewKey: string | null
  /** `pin` = gewählt (Klick, Tastatur), `hover` = vorübergehend (Maus) */
  onPreview: (target: PreviewTarget | null, how: 'pin' | 'hover') => void
  /** Spalte rechts neben der Liste (Vorschau in breiten Fenstern) */
  side?: ReactNode
}

/** Chip „Alle“ der Zustandsfilter */
const ALL = 'alle'
type StateChip = ImportComponentState | typeof ALL

/** Höhe der Liste: füllt das Fenster, aber nicht unter 20 rem und nicht über 44 rem */
const LIST_HEIGHT = 'h-[clamp(20rem,calc(100dvh-22rem),44rem)]'

/** Geschätzte Zeilenhöhen (gemessen wird beim Rendern) */
function estimateRow(row: TreeRow | undefined): number {
  if (!row) return 40
  if (row.type === 'group') return 37
  if (row.type === 'file') return row.expanded ? 76 : 58
  return row.component.state === 'taken' || row.component.state === 'duplicate' ? 47 : 33
}

const previewOf = (row: ComponentRow): PreviewTarget => ({ file: row.view.file, component: row.component })

export function FileTree({
  index,
  selected,
  onSelectedChange,
  plan,
  retargeted,
  targetOf,
  replace,
  previewKey,
  onPreview,
  side,
}: FileTreeProps) {
  useI18n()
  const uid = useId().replace(/:/g, '')
  const [search, setSearch] = useState('')
  const needle = useDeferredValue(search.trim().toLowerCase())
  const [states, setStates] = useState<ImportComponentState[]>([])
  const [kind, setKind] = useState<KindFilter>('all')
  /** von Hand aufgeklappte Dateien */
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set())
  /** beim Suchen von Hand zugeklappte Dateien (Treffer in Bauteilnamen klappen sie sonst auf) */
  const [collapsed, setCollapsed] = useState<ReadonlySet<string>>(() => new Set())
  const [collapsedGroups, setCollapsedGroups] = useState<ReadonlySet<LibKind>>(() => new Set())
  const [activeKey, setActiveKey] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)

  // neue Suche → von Hand Zugeklapptes vergessen
  const [collapsedFor, setCollapsedFor] = useState(needle)
  if (collapsedFor !== needle) {
    setCollapsedFor(needle)
    setCollapsed(new Set())
  }

  const filter = useMemo(() => ({ needle, states, kind }), [needle, states, kind])
  const groups = useMemo(() => filterScan(index, filter), [index, filter])
  const rows = useMemo(
    () =>
      buildRows(groups, collapsedGroups, (item) => {
        const rel = item.view.file.rel
        return expanded.has(rel) || (Boolean(needle) && item.nameHit && !collapsed.has(rel))
      }),
    [groups, collapsedGroups, expanded, collapsed, needle],
  )
  const keyIndex = useMemo(() => new Map(rows.map((r, i) => [r.key, i])), [rows])
  const activeIndex = activeKey !== null && keyIndex.has(activeKey) ? (keyIndex.get(activeKey) as number) : rows.length ? 0 : -1
  const visibleViews = useMemo(() => groups.flatMap((g) => g.files.map((f) => f.view)), [groups])
  const filtered = Boolean(needle) || states.length > 0 || kind !== 'all'

  // TanStack Virtual verwaltet seinen Zustand selbst (nicht mit dem React Compiler memoisierbar) – bewusst so
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => estimateRow(rows[i]),
    getItemKey: (i) => rows[i]?.key ?? i,
    overscan: 10,
  })

  // neuer Filter → nach oben
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
  }, [filter])

  // Vorschau beim Überfahren: kurz verzögert (kein Anfragesturm beim schnellen Darüberfahren)
  const hoverTimer = useRef<number | undefined>(undefined)
  useEffect(() => {
    const timer = hoverTimer
    return () => window.clearTimeout(timer.current)
  }, [])
  const hover = (target: PreviewTarget | null) => {
    window.clearTimeout(hoverTimer.current)
    hoverTimer.current = window.setTimeout(() => onPreview(target, 'hover'), target ? 120 : 200)
  }

  useHotkey('mod+f', () => searchRef.current?.focus(), { allowInInputs: true })

  // ------------------------------------------------------------------ Auswahl

  const setMany = (views: readonly FileView[], on: boolean) => {
    const next = new Set(selected)
    for (const v of views) {
      if (!v.selectable) continue
      if (on) next.add(v.file.rel)
      else next.delete(v.file.rel)
    }
    onSelectedChange(next)
  }
  const toggleFile = (view: FileView) => {
    if (view.selectable) setMany([view], !selected.has(view.file.rel))
  }
  const groupChecked = (files: readonly VisibleFile[]): CheckedState => {
    let on = 0
    let selectable = 0
    for (const f of files) {
      if (!f.view.selectable) continue
      selectable += 1
      if (selected.has(f.view.file.rel)) on += 1
    }
    if (!on) return false
    return on === selectable ? true : 'indeterminate'
  }
  const toggleGroup = (row: GroupRow) =>
    setMany(
      row.group.files.map((f) => f.view),
      groupChecked(row.group.files) !== true,
    )

  // ------------------------------------------------------------------ Auf-/Zuklappen

  const toggleFileOpen = (row: FileRow) => {
    if (!row.expandable) return
    const rel = row.item.view.file.rel
    const nextExpanded = new Set(expanded)
    const nextCollapsed = new Set(collapsed)
    if (row.expanded) {
      nextExpanded.delete(rel)
      nextCollapsed.add(rel)
    } else {
      nextExpanded.add(rel)
      nextCollapsed.delete(rel)
    }
    setExpanded(nextExpanded)
    setCollapsed(nextCollapsed)
  }
  const toggleGroupOpen = (row: GroupRow) => {
    const next = new Set(collapsedGroups)
    if (next.has(row.group.kind)) next.delete(row.group.kind)
    else next.add(row.group.kind)
    setCollapsedGroups(next)
  }

  // ------------------------------------------------------------------ Tastatur und Maus

  const go = (i: number) => {
    if (!rows.length) return
    const target = Math.max(0, Math.min(rows.length - 1, i))
    const row = rows[target]
    setActiveKey(row.key)
    virtualizer.scrollToIndex(target, { align: 'auto' })
    if (row.type === 'component') onPreview(previewOf(row), 'pin')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!rows.length || activeIndex < 0) return
    const row = rows[activeIndex]
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
      e.preventDefault()
      setMany(visibleViews, true)
      return
    }
    const page = Math.max(1, Math.floor((scrollRef.current?.clientHeight ?? 480) / 44) - 1)
    switch (e.key) {
      case 'ArrowDown':
        go(activeIndex + 1)
        break
      case 'ArrowUp':
        go(activeIndex - 1)
        break
      case 'Home':
        go(0)
        break
      case 'End':
        go(rows.length - 1)
        break
      case 'PageDown':
        go(activeIndex + page)
        break
      case 'PageUp':
        go(activeIndex - page)
        break
      case 'ArrowRight':
        if (row.type === 'group') {
          if (!row.expanded) toggleGroupOpen(row)
          else go(activeIndex + 1)
        } else if (row.type === 'file' && row.expandable) {
          if (!row.expanded) toggleFileOpen(row)
          else go(activeIndex + 1)
        }
        break
      case 'ArrowLeft':
        if (row.type === 'group' && row.expanded) toggleGroupOpen(row)
        else if (row.type === 'file' && row.expanded) toggleFileOpen(row)
        else if (row.parent) go(keyIndex.get(row.parent) ?? activeIndex)
        break
      case ' ':
        if (row.type === 'group') toggleGroup(row)
        else if (row.type === 'file') toggleFile(row.item.view)
        else onPreview(previewOf(row), 'pin')
        break
      case 'Enter':
        if (row.type === 'group') toggleGroupOpen(row)
        else if (row.type === 'file') toggleFileOpen(row)
        else onPreview(previewOf(row), 'pin')
        break
      default:
        return
    }
    e.preventDefault()
  }

  const onRowClick = (row: TreeRow, e: MouseEvent<HTMLDivElement>) => {
    setActiveKey(row.key)
    const onCheck = e.target instanceof Element && e.target.closest('[data-check]') !== null
    if (row.type === 'group') {
      if (onCheck) toggleGroup(row)
      else toggleGroupOpen(row)
    } else if (row.type === 'file') {
      if (onCheck || !row.expandable) toggleFile(row.item.view)
      else toggleFileOpen(row)
    } else onPreview(previewOf(row), 'pin')
  }

  const keepFocus = (e: MouseEvent<HTMLDivElement>) => {
    // Fokus bleibt auf der Liste (aktive Zeile über aria-activedescendant)
    e.preventDefault()
    scrollRef.current?.focus({ preventScroll: true })
  }

  // ------------------------------------------------------------------ Filter

  const countFor = (state: ImportComponentState) =>
    LIB_KINDS.filter((k) => kind === 'all' || kind === k).reduce((n, k) => n + index.stateCounts[k][state], 0)
  const chipOptions: ChipOption<StateChip>[] = [
    { value: ALL, label: t("Alle") },
    ...COMPONENT_STATES.map((s): ChipOption<StateChip> => {
      const count = countFor(s)
      return { value: s, label: t(STATE_LABELS[s]), meta: formatNumber(count), disabled: count === 0 && !states.includes(s) }
    }),
  ]
  const chipValue: StateChip[] = states.length ? states : [ALL]
  const onChips = (next: StateChip[]) => {
    const added = next.find((v) => !chipValue.includes(v))
    if (added === ALL || next.length === 0) setStates([])
    else setStates(next.filter((v): v is ImportComponentState => v !== ALL))
  }
  const resetFilters = () => {
    setSearch('')
    setStates([])
    setKind('all')
  }

  // ------------------------------------------------------------------ Zeilen

  const rowId = (i: number) => `${uid}-zeile-${i}`
  const hintId = `${uid}-hinweis`

  /** Inhalt und ARIA-Angaben einer Zeile je Art */
  const describe = (
    row: TreeRow,
  ): {
    label: string
    expanded?: boolean
    checked?: boolean | 'mixed'
    disabled?: boolean
    current?: boolean
    className: string
    content: ReactNode
    onMouseEnter?: () => void
  } => {
    if (row.type === 'group') {
      const checked = groupChecked(row.group.files)
      const comps = row.group.files.reduce((n, f) => n + f.view.file.components.length, 0)
      const text = KIND_TEXT[row.group.kind]
      return {
        label: `${text.group}: ${plural(row.group.files.length, t("Datei"), t("Dateien"))}, ${plural(comps, text.one, text.many)}`,
        expanded: row.expanded,
        checked: checked === 'indeterminate' ? 'mixed' : checked,
        className: 'bg-surface-2/70 hover:bg-surface-3/60',
        onMouseEnter: () => hover(null),
        content: (
          <div className="flex items-center gap-2 px-3 py-2">
            <Chevron open={row.expanded} />
            <span data-check className="flex h-5 items-center px-0.5">
              <CheckMark checked={checked} />
            </span>
            <KindIcon kind={row.group.kind} />
            <span className="text-xs font-semibold text-fg">{text.group}</span>
            <span className="min-w-0 truncate text-xs text-fg-subtle">
              {plural(row.group.files.length, t("Datei"), t("Dateien"))} · {plural(comps, text.one, text.many)}
            </span>
          </div>
        ),
      }
    }
    if (row.type === 'file') {
      const view = row.item.view
      const file = view.file
      const isSelected = selected.has(file.rel)
      const outcome = isSelected ? plan.outcome.get(file.rel) : undefined
      const text = KIND_TEXT[file.kind]
      const total = file.components.length
      const shown = row.item.comps.length
      const target = row.expanded ? targetOf(file) : null
      return {
        label: `${view.name}${view.folder ? ` in ${view.folder.replace(/[\\/]+$/, '')}` : ''} – ${file.problem ? file.problem : plural(total, text.one, text.many)}`,
        expanded: row.expandable ? row.expanded : undefined,
        checked: isSelected,
        disabled: !view.selectable || undefined,
        className: 'hover:bg-surface-2/60',
        onMouseEnter: () => hover(null),
        content: (
          <div className="flex items-start gap-2 py-2 pl-6 pr-3">
            <span className="flex h-5 items-center">
              <Chevron open={row.expanded} hidden={!row.expandable} />
            </span>
            <span data-check className="flex h-5 items-center px-0.5">
              <CheckMark checked={isSelected} disabled={!view.selectable} />
            </span>
            <span className="flex h-5 items-center">
              <KindIcon kind={file.kind} className={cn(!isSelected && 'text-fg-subtle')} />
            </span>
            <div className="min-w-0 flex-1">
              <RelPath rel={file.rel} muted={!isSelected} className="text-ui leading-5" />
              <div className="mt-1 flex flex-wrap items-center gap-1.5 text-2xs text-fg-muted">
                {file.problem ? (
                  <span className="text-danger-text">{file.problem}</span>
                ) : (
                  <>
                    <span>
                      {filtered && shown > 0 && shown !== total
                        ? t("{0} von {1}", { "0": String(formatNumber(shown)), "1": String(plural(total, text.one, text.many)) })
                        : total
                          ? plural(total, text.one, text.many)
                          : t("keine {0} – leer", { "0": String(text.many) })}
                    </span>
                    {COMPONENT_STATES.filter((s) => view.counts[s] > 0).map((s) => (
                      <StateBadge key={s} state={s} count={view.counts[s]} />
                    ))}
                    {!retargeted && file.exists === 'same' && <Badge variant="neutral">{t("schon importiert, unverändert")}</Badge>}
                    {!retargeted && file.exists === 'different' && (
                      <>
                        <Badge variant="warning" dot>
                          {t("schon importiert, geändert")}</Badge>
                        <span className={replace ? 'text-fg-muted' : 'text-warning-text'}>
                          {replace ? t("wird ersetzt") : t("wird nur mit „Ersetzen“ überschrieben")}
                        </span>
                      </>
                    )}
                    {outcome === 'no-names' && <Badge variant="outline">{t("wird übersprungen – kein Name übernehmbar")}</Badge>}
                  </>
                )}
              </div>
              {target && (
                <p className="mt-1 text-2xs text-fg-subtle">
                  {t("Ziel: ")}<RelPath rel={target} className="text-2xs" />
                </p>
              )}
            </div>
            <span className="mono shrink-0 pt-0.5 text-2xs text-fg-subtle">{formatBytes(file.size)}</span>
          </div>
        ),
      }
    }
    const c = row.component
    const text = KIND_TEXT[row.view.file.kind]
    const pinned = previewKey === componentKey(row.view.file.rel, c.name)
    return {
      label: `${c.name} – ${t(STATE_LABELS[c.state])}${c.description ? ` – ${c.description}` : ''}`,
      current: pinned || undefined,
      className: cn('border-line/40', pinned ? 'bg-accent-soft/60' : 'hover:bg-surface-2/60'),
      onMouseEnter: () => hover(previewOf(row)),
      content: (
        <>
          {pinned && <span aria-hidden className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-accent" />}
          <div className="flex items-start gap-2 py-1.5 pl-[5.5rem] pr-3">
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-baseline gap-2">
                <span className="mono min-w-0 text-xs font-medium text-fg [overflow-wrap:anywhere]">{c.name}</span>
                {c.description && (
                  <span className="min-w-0 flex-1 truncate text-2xs text-fg-subtle" title={c.description}>
                    {c.description}
                  </span>
                )}
              </div>
              {c.state === 'taken' && c.registered_library && (
                <p className="mt-0.5 text-2xs text-warning-text">
                  {t("registriert in ")}<RelPath rel={c.registered_library} className="text-2xs" />
                </p>
              )}
              {c.state === 'duplicate' && c.registered_library && (
                <p className="mt-0.5 text-2xs text-fg-subtle">
                  {t("zuerst in ")}<RelPath rel={c.registered_library} className="text-2xs" />
                </p>
              )}
            </div>
            {c.count != null && <span className="mono shrink-0 pt-px text-2xs text-fg-muted">{plural(c.count, text.countOne, text.countMany)}</span>}
            {c.has_3d === true && (
              <Badge variant="outline" title={t("Eingebettetes 3D-Modell")}>
                3D
              </Badge>
            )}
            <StateBadge state={c.state} />
          </div>
        </>
      ),
    }
  }

  const items = virtualizer.getVirtualItems()

  return (
    <section aria-labelledby={`${uid}-titel`} className="flex min-w-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card">
      <h2 id={`${uid}-titel`} className="sr-only">
        {t("Dateien der Quelle")}</h2>
      {/* Filter */}
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2.5">
        <Input
          ref={searchRef}
          size="sm"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && search) {
              e.stopPropagation()
              setSearch('')
            }
          }}
          placeholder={t("Datei oder Name suchen …")}
          aria-label={t("Dateien und Namen durchsuchen")}
          aria-keyshortcuts="Control+F"
          prefix={<Search />}
          suffix={search ? <IconButton size="xs" label={t("Suche leeren")} icon={<X />} onClick={() => setSearch('')} tooltip={false} /> : undefined}
          containerClassName="w-60 max-w-full"
        />
        <SegmentedControl<KindFilter>
          size="sm"
          aria-label={t("Art der Bibliotheken")}
          value={kind}
          onValueChange={setKind}
          options={[
            { value: 'all', label: <FilterLabel label={t("Alle")} count={index.views.length} /> },
            { value: 'schlib', label: <FilterLabel label={t("Symbole")} count={index.byKind.schlib.length} />, disabled: !index.byKind.schlib.length },
            {
              value: 'pcblib',
              label: <FilterLabel label="Footprints" count={index.byKind.pcblib.length} />,
              disabled: !index.byKind.pcblib.length,
            },
          ]}
        />
        <ChipGroup<StateChip> size="sm" aria-label={t("Zustand der Namen")} value={chipValue} onValueChange={onChips} options={chipOptions} className="basis-full" />
      </div>
      {/* Auswahl */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-surface-2/40 px-3 py-1.5">
        <p className="min-w-0 flex-1 text-xs text-fg-muted" aria-live="polite">
          <span className="font-medium text-fg">{formatNumber(plan.selected)}</span> {t(" von ")}{plural(index.views.length, t("Datei"), t("Dateien"))}{' '}
          {t("ausgewählt")}{filtered && t(" · {0} angezeigt", { "0": String(formatNumber(visibleViews.length)) })}
        </p>
        <div className="flex items-center gap-1">
          <Button size="xs" variant="ghost" disabled={!visibleViews.length} onClick={() => setMany(visibleViews, true)}>
            {filtered ? t("Angezeigte auswählen") : t("Alle auswählen")}
          </Button>
          <Button size="xs" variant="ghost" disabled={!visibleViews.length} onClick={() => setMany(visibleViews, false)}>
            {filtered ? t("Angezeigte abwählen") : t("Keine")}
          </Button>
        </div>
      </div>
      {/* Baum (rechts daneben optional die Vorschau) */}
      <div className={cn('flex min-h-0', LIST_HEIGHT)}>
        {rows.length === 0 ? (
          <div className="flex min-w-0 flex-1 items-center justify-center">
            <EmptyState
              size="sm"
              illustration="search-empty"
              title={t("Keine Treffer")}
              titleAs="h3"
              description={needle ? t("Keine Datei und kein Name passt zu „{0}“.", { "0": String(search.trim()) }) : t("Kein Name passt zu diesen Filtern.")}
              actions={
                <Button size="sm" onClick={resetFilters}>
                  {t("Filter zurücksetzen")}</Button>
              }
            />
          </div>
        ) : (
          <div
            ref={scrollRef}
            role="tree"
            aria-label={t("Dateien und Bauteile der Quelle")}
            aria-describedby={hintId}
            aria-activedescendant={activeIndex >= 0 ? rowId(activeIndex) : undefined}
            tabIndex={0}
            onKeyDown={onKeyDown}
            onMouseLeave={() => hover(null)}
            className="relative min-w-0 flex-1 overflow-y-auto outline-none"
          >
            <div role="none" className="relative w-full" style={{ height: virtualizer.getTotalSize() }}>
              {items.map((item) => {
                const row = rows[item.index]
                if (!row) return null
                const d = describe(row)
                return (
                  <div
                    key={item.key}
                    ref={virtualizer.measureElement}
                    id={rowId(item.index)}
                    data-index={item.index}
                    data-active={item.index === activeIndex || undefined}
                    role="treeitem"
                    aria-level={row.level}
                    aria-posinset={row.posinset}
                    aria-setsize={row.setsize}
                    aria-expanded={d.expanded}
                    aria-checked={d.checked}
                    aria-disabled={d.disabled}
                    aria-current={d.current}
                    aria-label={d.label}
                    tabIndex={-1}
                    onMouseDown={keepFocus}
                    onClick={(e) => onRowClick(row, e)}
                    onKeyDown={onKeyDown}
                    onMouseEnter={d.onMouseEnter}
                    style={{ transform: `translateY(${item.start}px)` }}
                    className={cn(
                      'absolute left-0 top-0 w-full cursor-default select-none border-b border-line/70',
                      'data-[active]:in-focus-visible:outline-2 data-[active]:in-focus-visible:-outline-offset-2 data-[active]:in-focus-visible:outline-accent',
                      d.className,
                    )}
                  >
                    {d.content}
                  </div>
                )
              })}
            </div>
          </div>
        )}
        {side && <div className="w-64 shrink-0 border-l border-line">{side}</div>}
      </div>
      <p id={hintId} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line px-3 py-1.5 text-2xs text-fg-subtle">
        <span aria-hidden className="flex items-center gap-1">
          <Kbd keys={['↑', '↓']} size="xs" /> {t(" Zeile")}</span>
        <span aria-hidden className="flex items-center gap-1">
          <Kbd keys={['←', '→']} size="xs" /> {t(" zu-/aufklappen")}</span>
        <span aria-hidden className="flex items-center gap-1">
          <Kbd keys={[t("Leertaste")]} size="xs" /> {t(" auswählen")}</span>
        <span aria-hidden className="flex items-center gap-1">
          <Kbd keys={['Enter']} size="xs" /> {t(" Vorschau")}</span>
        <span className="sr-only">
          {t("Pfeiltasten wechseln die Zeile, rechts und links klappen auf und zu, die Leertaste wählt eine Datei aus oder ab, Enter zeigt ein Bauteil in der Vorschau, Strg+A wählt alle angezeigten Dateien.")}</span>
      </p>
    </section>
  )
}

function Chevron({ open, hidden }: { open: boolean; hidden?: boolean }) {
  useI18n()
  return (
    <ChevronRight
      aria-hidden
      className={cn('size-4 shrink-0 text-fg-subtle transition-transform duration-150', open && 'rotate-90', hidden && 'invisible')}
    />
  )
}

/** Beschriftung eines Filtersegments mit Zähler */
function FilterLabel({ label, count }: { label: string; count: number }) {
  useI18n()
  return (
    <span className="flex items-center gap-1.5">
      {label}
      <span className="mono rounded-full bg-surface-3 px-1.5 text-2xs leading-4 text-fg-subtle">{formatNumber(count)}</span>
    </span>
  )
}
