import { metadataLabel, t as translate, useI18n, getLocale } from '@/lib/i18n'
/** Linke Spalte des Schema-Designers: Suche, Kategorien mit Symbol, Tabellenname, Zähler und Altium-Status. */
import { motion } from 'motion/react'
import { EyeOff, Plus, Search } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { CategoryDef } from '@/api/settings'
import { Button, Input, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { CategoryTile } from './pickers'

export interface CategoryListProps {
  categories: CategoryDef[]
  loading: boolean
  selected: string | null
  /** Kategorie mit ungespeicherten Änderungen (Punkt) */
  dirtyTable?: string | null
  onSelect: (table: string) => void
  onCreate: () => void
  className?: string
}

const fold = (s: string) => s.toLocaleLowerCase(getLocale())

export function CategoryList({ categories, loading, selected, dirtyTable, onSelect, onCreate, className }: CategoryListProps) {
  useI18n()
  const [query, setQuery] = useState('')
  const listRef = useRef<HTMLUListElement>(null)
  const q = fold(query.trim())
  const visible = q
    ? categories.filter((c) => fold(`${metadataLabel(c.label, translate)} ${c.label} ${c.table} ${c.prefix}`).includes(q))
    : categories

  // Gewählte Kategorie sichtbar halten (nach „Neue Kategorie“, Sprung per ?k=…) – nur die Liste scrollen, nie die Seite
  useEffect(() => {
    const list = listRef.current
    if (!list || !selected) return
    const item = Array.from(list.querySelectorAll<HTMLElement>('button[data-table]')).find((b) => b.dataset.table === selected)
    if (!item) return
    const top = item.offsetTop // die Liste ist `relative` → Abstand zum Listenanfang
    const bottom = top + item.offsetHeight
    if (top < list.scrollTop + 4) list.scrollTop = Math.max(0, top - 8)
    else if (bottom > list.scrollTop + list.clientHeight - 4) list.scrollTop = bottom - list.clientHeight + 8
  }, [selected, categories.length])

  const focusAt = (index: number) => {
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>('button[data-table]')
    if (!buttons?.length) return
    buttons[Math.max(0, Math.min(buttons.length - 1, index))]?.focus()
  }

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (e.key === 'ArrowDown') focusAt(index + 1)
    else if (e.key === 'ArrowUp') focusAt(index - 1)
    else if (e.key === 'Home') focusAt(0)
    else if (e.key === 'End') focusAt(visible.length - 1)
    else if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
      // Anfangsbuchstabe: nächste passende Kategorie
      const letter = fold(e.key)
      const start = index + 1
      const order = [...visible.slice(start), ...visible.slice(0, start)]
      const hit = order.find((c) => fold(metadataLabel(c.label, translate)).startsWith(letter))
      if (hit) focusAt(visible.indexOf(hit))
      else return
    } else return
    e.preventDefault()
  }

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      <div className="flex items-center gap-2 border-b border-line p-3">
        <Input
          size="sm"
          prefix={<Search />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              focusAt(0)
            } else if (e.key === 'Escape' && query) {
              e.stopPropagation()
              setQuery('')
            }
          }}
          placeholder={translate("Kategorie suchen …")}
          aria-label={translate("Kategorien durchsuchen")}
          containerClassName="flex-1"
        />
        <Tooltip content={translate("Neue Kategorie")}>
          <Button size="sm" variant="secondary" iconOnly aria-label={translate("Neue Kategorie")} onClick={onCreate}>
            <Plus />
          </Button>
        </Tooltip>
      </div>
      {loading ? (
        <div className="flex flex-col gap-1.5 p-2" aria-busy="true">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-12 rounded-button" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <p className="px-4 py-8 text-center text-xs text-fg-subtle">
          {q ? translate("Keine Kategorie passt zu „{value1}“.", { value1: query.trim() }) : translate("Noch keine Kategorien.")}
        </p>
      ) : (
        <ul ref={listRef} aria-label={translate("Kategorien")} className="relative min-h-0 flex-1 overflow-y-auto p-2">
          {visible.map((c, i) => {
            const active = c.table === selected
            return (
              <li key={c.table}>
                <button
                  type="button"
                  data-table={c.table}
                  aria-current={active ? 'true' : undefined}
                  onClick={() => onSelect(c.table)}
                  onKeyDown={(e) => onKeyDown(e, i)}
                  className={cn(
                    'group/cat relative isolate flex w-full items-center gap-2.5 rounded-button px-2 py-1.5 text-left outline-none transition-colors focus-ring',
                    active ? 'text-fg' : 'text-fg-muted hover:bg-surface-2/70 hover:text-fg',
                  )}
                >
                  {active && (
                    <motion.span
                      layoutId="schema-category"
                      aria-hidden
                      className="absolute inset-0 -z-10 rounded-button border border-line-strong bg-surface-2 shadow-card"
                      transition={{ type: 'spring', stiffness: 500, damping: 40 }}
                    />
                  )}
                  <CategoryTile icon={c.icon} color={c.color} size="sm" />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-start gap-1.5">
                      <span className="line-clamp-2 text-ui font-medium leading-snug text-fg">{metadataLabel(c.label, translate)}</span>
                      {dirtyTable === c.table && (
                        <span aria-label={translate("ungespeichert")} role="img" className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent shadow-[0_0_6px_var(--pf-accent)]" />
                      )}
                    </span>
                    <span className="mono block truncate text-2xs text-fg-subtle">
                      {c.table} · {c.prefix}
                    </span>
                  </span>
                  {!c.altium_enabled && (
                    <Tooltip content={translate("Nicht in Altium sichtbar")}>
                      <span className="flex shrink-0 text-fg-subtle" role="img" aria-label={translate("nicht in Altium sichtbar")}>
                        <EyeOff aria-hidden className="size-3.5" />
                      </span>
                    </Tooltip>
                  )}
                  <span className="mono tabular shrink-0 text-2xs text-fg-subtle">{formatNumber(c.part_count ?? 0)}</span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
