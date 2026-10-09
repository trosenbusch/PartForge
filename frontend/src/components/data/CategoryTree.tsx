/**
 * Kategoriebaum (ARIA-Tree): Kategorien mit Symbol, Farbe und Zähler in einklappbaren Gruppen, Suche, vollständige
 * Tastaturbedienung (↑/↓, ←/→ ein-/ausklappen, Pos1/Ende, Enter/Leertaste, Tippen springt zum Anfangsbuchstaben).
 *
 *   const items = useCategoryTreeItems()          // aus /api/categories, gruppiert
 *   <CategoryTree items={items} value={table} onValueChange={setTable} allItem={{ label: 'Alle Bauteile' }} />
 */
import { ChevronRight, Search, X } from 'lucide-react'
import { Fragment, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { readPref, writePref } from '@/lib/prefs'
import { CategoryIcon } from './CategoryIcon'

export interface CategoryTreeItem {
  /** Eindeutige ID (Tabellenname) */
  id: string
  label: string
  /** Lucide-Name (aus der Datenbank) oder eigenes Element */
  icon?: string | ReactNode
  color?: string | null
  count?: number | null
  /** Gruppe (Überschrift); ohne Gruppe erscheint der Eintrag oben */
  group?: string
  /** Zusätzliche Suchbegriffe (z. B. Tabellenname) */
  keywords?: string
}

export interface CategoryTreeProps {
  items: CategoryTreeItem[]
  value?: string | null
  onValueChange?: (id: string) => void
  /** Eintrag „Alle“ ganz oben (ID = leerer Text) */
  allItem?: { label: string; count?: number | null } | false
  /** Reihenfolge der Gruppen (übrige alphabetisch dahinter) */
  groupOrder?: string[]
  searchable?: boolean
  searchPlaceholder?: string
  loading?: boolean
  /** Eingeklappte Gruppen dauerhaft merken */
  persistKey?: string
  className?: string
  'aria-label'?: string
}

interface Node {
  key: string
  kind: 'group' | 'item'
  id: string
  label: string
  level: number
  item?: CategoryTreeItem
  group?: string
  count?: number | null
}

const ALL_ID = ''

const fold = (s: string) =>
  s
    .toLocaleLowerCase('de-DE')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>
  const idx = fold(text).indexOf(fold(query))
  if (idx < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, idx)}
      <mark className="rounded-[3px] bg-accent-soft px-px text-accent-text">{text.slice(idx, idx + query.length)}</mark>
      {text.slice(idx + query.length)}
    </>
  )
}

export function CategoryTree({
  items,
  value,
  onValueChange,
  allItem = false,
  groupOrder,
  searchable = true,
  searchPlaceholder = 'Kategorie suchen …',
  loading,
  persistKey,
  className,
  'aria-label': ariaLabel = 'Kategorien',
}: CategoryTreeProps) {
  const uid = useId().replace(/:/g, '')
  const [query, setQuery] = useState('')
  const prefKey = persistKey ? `pf-tree:${persistKey}` : null
  const [collapsed, setCollapsed] = useState<Set<string>>(() => {
    if (!prefKey) return new Set()
    try {
      const raw = readPref(prefKey)
      return new Set(raw ? (JSON.parse(raw) as string[]) : [])
    } catch {
      return new Set()
    }
  })
  const toggleGroup = (group: string, open?: boolean) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      const isOpen = !next.has(group)
      if (open ?? !isOpen) next.delete(group)
      else next.add(group)
      if (prefKey) writePref(prefKey, next.size ? JSON.stringify([...next]) : null)
      return next
    })
  }

  // ------------------------------------------------------------------ Struktur (gefiltert)
  const q = query.trim()
  const filtered = useMemo(
    () => (q ? items.filter((it) => fold(`${it.label} ${it.id} ${it.keywords ?? ''}`).includes(fold(q))) : items),
    [items, q],
  )
  const groups = useMemo(() => {
    const map = new Map<string, CategoryTreeItem[]>()
    for (const it of filtered) {
      const g = it.group ?? ''
      const list = map.get(g)
      if (list) list.push(it)
      else map.set(g, [it])
    }
    const order = groupOrder ?? []
    return [...map.entries()].sort(([a], [b]) => {
      if (!a) return -1
      if (!b) return 1
      const ia = order.indexOf(a)
      const ib = order.indexOf(b)
      if (ia >= 0 || ib >= 0) return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib)
      return a.localeCompare(b, 'de')
    })
  }, [filtered, groupOrder])

  const visible: Node[] = useMemo(() => {
    const out: Node[] = []
    if (allItem && !q) out.push({ key: 'all', kind: 'item', id: ALL_ID, label: allItem.label, level: 1, count: allItem.count })
    for (const [group, list] of groups) {
      if (!group) {
        for (const it of list) out.push({ key: `i:${it.id}`, kind: 'item', id: it.id, label: it.label, level: 1, item: it })
        continue
      }
      const open = q ? true : !collapsed.has(group)
      const total = list.reduce((s, it) => s + (it.count ?? 0), 0)
      out.push({ key: `g:${group}`, kind: 'group', id: `g:${group}`, label: group, level: 1, group, count: total })
      if (open) for (const it of list) out.push({ key: `i:${it.id}`, kind: 'item', id: it.id, label: it.label, level: 2, item: it, group })
    }
    return out
  }, [groups, collapsed, allItem, q])

  // ------------------------------------------------------------------ Fokus (roving tabindex)
  const [focusKey, setFocusKey] = useState<string | null>(null)
  const selectedKey = value === null || value === undefined ? null : value === ALL_ID ? 'all' : `i:${value}`
  const tabKey = visible.some((n) => n.key === focusKey)
    ? focusKey
    : visible.some((n) => n.key === selectedKey)
      ? selectedKey
      : (visible[0]?.key ?? null)
  const refs = useRef(new Map<string, HTMLElement>())
  const moveFocus = (key: string | null | undefined) => {
    if (!key) return
    setFocusKey(key)
    refs.current.get(key)?.focus()
  }
  const typeahead = useRef({ text: '', at: 0 })

  const onKeyDown = (e: KeyboardEvent<HTMLElement>, node: Node) => {
    const idx = visible.findIndex((n) => n.key === node.key)
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        moveFocus(visible[idx + 1]?.key)
        return
      case 'ArrowUp':
        e.preventDefault()
        if (idx === 0 && searchable) document.getElementById(`${uid}-search`)?.focus()
        else moveFocus(visible[idx - 1]?.key)
        return
      case 'Home':
        e.preventDefault()
        moveFocus(visible[0]?.key)
        return
      case 'End':
        e.preventDefault()
        moveFocus(visible[visible.length - 1]?.key)
        return
      case 'ArrowRight':
        e.preventDefault()
        if (node.kind === 'group' && node.group) {
          if (collapsed.has(node.group) && !q) toggleGroup(node.group, true)
          else moveFocus(visible[idx + 1]?.key)
        }
        return
      case 'ArrowLeft':
        e.preventDefault()
        if (node.kind === 'group' && node.group && !collapsed.has(node.group) && !q) toggleGroup(node.group, false)
        else if (node.kind === 'item' && node.group) moveFocus(`g:${node.group}`)
        return
      case 'Enter':
      case ' ':
        e.preventDefault()
        if (node.kind === 'group' && node.group) {
          if (!q) toggleGroup(node.group)
        } else onValueChange?.(node.id)
        return
      default:
        if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
          const now = e.timeStamp
          const t = typeahead.current
          t.text = now - t.at < 700 ? t.text + e.key : e.key
          t.at = now
          const start = idx + (t.text.length === 1 ? 1 : 0)
          const order = [...visible.slice(start), ...visible.slice(0, start)]
          const hit = order.find((n) => n.kind === 'item' && fold(n.label).startsWith(fold(t.text)))
          if (hit) moveFocus(hit.key)
        }
    }
  }

  // Auswahl sichtbar halten (nur den Baum scrollen, nie die Seite) – auch, wenn die Einträge erst nachladen
  const treeRef = useRef<HTMLDivElement>(null)
  const hasSelected = visible.some((n) => n.key === selectedKey)
  useEffect(() => {
    const box = treeRef.current
    const el = selectedKey ? refs.current.get(selectedKey) : undefined
    if (!box || !el || !hasSelected) return
    const top = el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop
    const bottom = top + el.offsetHeight
    if (top < box.scrollTop) box.scrollTop = top - 8
    else if (bottom > box.scrollTop + box.clientHeight) box.scrollTop = bottom - box.clientHeight + 8
  }, [selectedKey, hasSelected])

  const rowClass =
    // Mindesthöhe statt fester Höhe: lange Namen („Linearregler und Referenzen“) brechen in eine zweite Zeile um
    'group/row relative flex min-h-8 w-full cursor-pointer select-none items-center gap-2.5 rounded-control py-1 pl-2.5 pr-2 text-left text-ui leading-snug outline-none transition-colors focus-ring-inset'

  // ------------------------------------------------------------------ Darstellung
  const renderItem = (n: Node) => {
    const selected = n.key === selectedKey
    const it = n.item
    return (
      <div
        key={n.key}
        ref={(el) => {
          if (el) refs.current.set(n.key, el)
          else refs.current.delete(n.key)
        }}
        role="treeitem"
        aria-level={n.level}
        aria-selected={selected}
        tabIndex={n.key === tabKey ? 0 : -1}
        onFocus={() => setFocusKey(n.key)}
        onKeyDown={(e) => onKeyDown(e, n)}
        onClick={() => onValueChange?.(n.id)}
        className={cn(
          rowClass,
          n.level === 2 && 'pl-4',
          selected ? 'bg-surface-3 font-medium text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
        )}
      >
        {selected && (
          <span
            aria-hidden
            className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-gradient-forge shadow-[0_0_8px_var(--pf-glow-indicator)]"
          />
        )}
        {it ? (
          typeof it.icon === 'string' || it.icon === undefined ? (
            <CategoryIcon name={it.icon as string | undefined} color={it.color} className={cn(!selected && 'opacity-90')} />
          ) : (
            <span aria-hidden className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
              {it.icon}
            </span>
          )
        ) : (
          <span aria-hidden className="flex size-4 items-center justify-center">
            <span className="size-2 rounded-full bg-gradient-forge" />
          </span>
        )}
        {/* nie abgeschnitten ohne Tooltip: höchstens zwei Zeilen, voller Name als title (FOUNDATION Regel 4) */}
        <span className="line-clamp-2 min-w-0 flex-1 break-words" title={n.label}>
          <Highlight text={n.label} query={q} />
        </span>
        {(it?.count ?? n.count) !== undefined && (it?.count ?? n.count) !== null && (
          <span className={cn('mono text-2xs tabular-nums', selected ? 'text-fg-muted' : 'text-fg-subtle')}>
            {formatNumber((it?.count ?? n.count) as number)}
          </span>
        )}
      </div>
    )
  }

  // Gruppen: Kopf (treeitem, Ebene 1) und Einträge (Ebene 2) stehen nebeneinander – die Hierarchie trägt aria-level.
  // So ist der Name der Gruppe ihr sichtbarer Titel (nicht der Text aller Einträge; axe „label-content-name-mismatch“).
  const renderGroup = (n: Node, children: Node[]) => {
    const open = q ? true : !collapsed.has(n.group ?? '')
    return (
      <Fragment key={n.key}>
        <div
          ref={(el) => {
            if (el) refs.current.set(n.key, el)
            else refs.current.delete(n.key)
          }}
          role="treeitem"
          aria-level={1}
          aria-expanded={open}
          aria-selected={false}
          tabIndex={n.key === tabKey ? 0 : -1}
          onFocus={() => setFocusKey(n.key)}
          onKeyDown={(e) => onKeyDown(e, n)}
          onClick={() => {
            if (!q && n.group) toggleGroup(n.group)
          }}
          className="mt-3 flex h-7 cursor-pointer items-center gap-1.5 rounded-control px-1.5 text-fg-subtle outline-none transition-colors first:mt-0 hover:text-fg-muted focus-ring-inset"
        >
          <ChevronRight
            aria-hidden
            className={cn('size-3.5 shrink-0 transition-transform duration-150', open && 'rotate-90', q && 'opacity-40')}
          />
          <span className="micro-label min-w-0 flex-1 truncate" title={n.label}>
            {n.label}
          </span>
          {n.count ? (
            <span aria-hidden className="mono text-2xs tabular-nums text-fg-subtle">
              {formatNumber(n.count)}
            </span>
          ) : null}
        </div>
        {open && <div className="mt-0.5 flex flex-col gap-px">{children.map(renderItem)}</div>}
      </Fragment>
    )
  }

  const tree: ReactNode[] = []
  for (let i = 0; i < visible.length; i++) {
    const n = visible[i]
    if (n.kind === 'group') {
      const children: Node[] = []
      while (visible[i + 1]?.kind === 'item' && visible[i + 1].group === n.group) children.push(visible[++i])
      tree.push(renderGroup(n, children))
    } else {
      tree.push(<Fragment key={n.key}>{renderItem(n)}</Fragment>)
    }
  }

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      {searchable && (
        <div className="mb-2 flex h-8 shrink-0 items-center gap-2 rounded-control border border-line bg-control px-2.5 transition-colors focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--pf-accent-soft)]">
          <Search aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
          <input
            id={`${uid}-search`}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'ArrowDown') {
                e.preventDefault()
                moveFocus(visible[0]?.key)
              } else if (e.key === 'Escape' && query) {
                e.preventDefault()
                e.stopPropagation()
                setQuery('')
              } else if (e.key === 'Enter') {
                const first = visible.find((n) => n.kind === 'item')
                if (first) onValueChange?.(first.id)
              }
            }}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder.replace(/ …$/, '')}
            aria-controls={`${uid}-tree`}
            className="h-full min-w-0 flex-1 bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle [&::-webkit-search-cancel-button]:hidden"
          />
          {query && (
            <button
              type="button"
              onClick={() => setQuery('')}
              aria-label="Suche leeren"
              className="flex size-5 items-center justify-center rounded-[5px] text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
            >
              <X aria-hidden className="size-3" />
            </button>
          )}
        </div>
      )}
      {loading ? (
        <div className="flex flex-col gap-2 px-1 pt-1" aria-hidden>
          <Skeleton className="h-3 w-24" />
          {Array.from({ length: 7 }, (_, i) => (
            <Skeleton key={i} className="h-6" style={{ width: `${88 - (i % 3) * 12}%` }} />
          ))}
        </div>
      ) : (
        <div ref={treeRef} id={`${uid}-tree`} role="tree" aria-label={ariaLabel} className="min-h-0 flex-1 overflow-y-auto pr-0.5">
          {tree}
          {visible.length === 0 && (
            <p className="px-2 py-6 text-center text-xs text-fg-subtle">
              {q ? `Keine Kategorie zu „${q}“` : 'Noch keine Kategorien'}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
