import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Symboltypen-Leiste: gruppierte Liste (Passiv, Halbleiter, ICs, Verbinder, Sonstige) mit Vorschaubildern und Suche.
 * Listbox mit „Auswahl folgt dem Fokus“: ↑/↓ wählt sofort (die Vorschau ist schnell), Pos1/Ende, Bild↑/↓;
 * Tippen springt in die Suche, in der Suche wechselt ↓ zurück in die Liste.
 */
import { Check, RotateCcw, Search, X } from 'lucide-react'
import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { SYMBOL_GROUPS, type SymbolKindInfo } from '@/api/symbols'
import { Button, Callout, Input, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { SvgImage } from '../shared'

export interface KindBrowserProps {
  kinds: SymbolKindInfo[] | undefined
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  value: string
  onValueChange: (key: string) => void
  /** Namen (klein geschrieben), die schon in der Bibliothek liegen – Typen mit diesem Standardnamen bekommen einen Haken */
  inLibrary?: ReadonlySet<string>
  className?: string
}

const IC_KEY = 'ic'

const fold = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')

function matches(kind: SymbolKindInfo, query: string): boolean {
  if (!query) return true
  const hay = fold([kind.label, tr(kind.label), kind.key, kind.default_name, kind.group, tr(kind.group), kind.description, tr(kind.description), ...kind.categories].join(' '))
  return fold(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((t) => hay.includes(t))
}

export function KindBrowser({ kinds, loading, error, onRetry, value, onValueChange, inLibrary, className }: KindBrowserProps) {
  useI18n()
  const uid = useId().replace(/:/g, '')
  const [query, setQuery] = useState('')
  const listRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const groups = useLocalizedMemo(() => {
    const filtered = (kinds ?? []).filter((k) => matches(k, query.trim()))
    const order = [...SYMBOL_GROUPS, ...new Set(filtered.map((k) => k.group).filter((g) => !(SYMBOL_GROUPS as readonly string[]).includes(g)))]
    return order
      .map((g) => ({
        group: g,
        // der IC-Generator (Pinliste) ist der vielseitigste Typ – in seiner Gruppe zuerst
        items: filtered.filter((k) => k.group === g).sort((a, b) => Number(b.key === IC_KEY) - Number(a.key === IC_KEY)),
      }))
      .filter((g) => g.items.length > 0)
  }, [kinds, query])
  const flat = useLocalizedMemo(() => groups.flatMap((g) => g.items), [groups])
  const optionId = (key: string) => `${uid}-kind-${key}`

  // ausgewählten Typ sichtbar halten: bei Auswahl in der Liste nur nachführen, bei Auswahl von außen (Adresse,
  // „Bearbeiten“ aus der Bibliothek, erster Aufruf) mittig zeigen
  const localPick = useRef(false)
  useEffect(() => {
    const el = document.getElementById(`${uid}-kind-${value}`)
    el?.scrollIntoView({ block: localPick.current ? 'nearest' : 'center' })
    localPick.current = false
  }, [uid, value, flat.length])

  const index = flat.findIndex((k) => k.key === value)
  const choose = (i: number) => {
    const k = flat[Math.max(0, Math.min(flat.length - 1, i))]
    if (!k) return
    localPick.current = true
    onValueChange(k.key)
  }

  const onListKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!flat.length) return
    const pageSize = 8
    switch (e.key) {
      case 'ArrowDown':
        choose(index < 0 ? 0 : index + 1)
        break
      case 'ArrowUp':
        choose(index < 0 ? 0 : index - 1)
        break
      case 'Home':
        choose(0)
        break
      case 'End':
        choose(flat.length - 1)
        break
      case 'PageDown':
        choose(index + pageSize)
        break
      case 'PageUp':
        choose(index - pageSize)
        break
      default:
        // Tippen = Suchen
        if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== ' ') {
          searchRef.current?.focus()
          setQuery((q) => q + e.key)
          e.preventDefault()
        }
        return
    }
    e.preventDefault()
  }

  const onSearchKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'Enter') {
      e.preventDefault()
      if (flat.length && !flat.some((k) => k.key === value)) onValueChange(flat[0].key)
      else if (e.key === 'Enter' && flat.length) onValueChange(flat[0].key)
      listRef.current?.focus()
    } else if (e.key === 'Escape' && query) {
      e.preventDefault()
      e.stopPropagation()
      setQuery('')
    }
  }

  const total = kinds?.length ?? 0

  return (
    <div className={cn('flex h-full min-h-0 flex-col', className)}>
      <div className="shrink-0 px-3 pb-2 pt-3">
        <div className="mb-2 flex items-baseline justify-between px-0.5">
          <h2 id={`${uid}-title`} className="micro-label">
            {tr("Symboltypen")}
          </h2>
          {total > 0 && (
            <span className="text-2xs tabular-nums text-fg-subtle">
              {query ? tr("{value0} von {value1}", { value0: String(formatNumber(flat.length)), value1: String(formatNumber(total)) }) : formatNumber(total)}
            </span>
          )}
        </div>
        <Input
          ref={searchRef}
          size="sm"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onSearchKeyDown}
          placeholder={tr("Typ suchen, z. B. MOSFET")}
          aria-label={tr("Symboltypen durchsuchen")}
          aria-controls={`${uid}-list`}
          prefix={<Search />}
          suffix={
            query ? (
              <button
                type="button"
                onClick={() => {
                  setQuery('')
                  searchRef.current?.focus()
                }}
                aria-label={tr("Suche leeren")}
                className="flex size-5 items-center justify-center rounded-sm text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
              >
                <X className="size-3.5" />
              </button>
            ) : undefined
          }
        />
      </div>

      {error && !kinds ? (
        <div className="px-3">
          <Callout tone="danger" title={tr("Nicht geladen")}>
            <span className="block">{localizeMessage(error)}</span>
            {onRetry && (
              <Button size="xs" variant="secondary" leftIcon={<RotateCcw />} onClick={onRetry} className="mt-2">
                {tr("Erneut versuchen")}
              </Button>
            )}
          </Callout>
        </div>
      ) : (
        <div
          ref={listRef}
          id={`${uid}-list`}
          role="listbox"
          tabIndex={0}
          aria-labelledby={`${uid}-title`}
          aria-activedescendant={index >= 0 ? optionId(value) : undefined}
          aria-busy={loading || undefined}
          onKeyDown={onListKeyDown}
          className="group/list relative min-h-0 flex-1 overflow-y-auto px-2 pb-3 outline-none"
        >
          {loading && !kinds && (
            <div className="flex flex-col gap-1 px-1 pt-1" aria-hidden>
              {Array.from({ length: 9 }, (_, i) => (
                <div key={i} className="flex items-center gap-2.5 py-1">
                  <Skeleton className="h-10 w-14" />
                  <div className="flex-1 space-y-1.5">
                    <Skeleton className="h-3 w-3/4" />
                    <Skeleton className="h-2.5 w-1/2" />
                  </div>
                </div>
              ))}
            </div>
          )}
          {kinds && flat.length === 0 && (
            <div className="flex flex-col items-center gap-3 px-4 py-10 text-center">
              <p className="text-ui text-fg-muted">{tr("Kein Symboltyp passt zu „")}{query}“.</p>
              <Button size="sm" variant="secondary" onClick={() => setQuery('')}>
                {tr("Suche zurücksetzen")}
              </Button>
            </div>
          )}
          {groups.map((g) => (
            <div key={g.group} role="group" aria-labelledby={`${uid}-g-${g.group}`} className="pb-1">
              <div
                id={`${uid}-g-${g.group}`}
                className="sticky top-0 z-[2] -mx-2 flex items-center justify-between bg-bg-elev px-4 pb-1 pt-2.5"
              >
                <span className="micro-label">{tr(g.group)}</span>
                <span className="text-2xs tabular-nums text-fg-subtle">{formatNumber(g.items.length)}</span>
              </div>
              {g.items.map((k) => {
                const selected = k.key === value
                return (
                  <div
                    key={k.key}
                    id={optionId(k.key)}
                    role="option"
                    aria-selected={selected}
                    tabIndex={-1}
                    data-active={selected || undefined}
                    onKeyDown={onListKeyDown}
                    onMouseDown={(e) => {
                      // Fokus bleibt auf der Liste (aktives Element über aria-activedescendant)
                      e.preventDefault()
                      listRef.current?.focus({ preventScroll: true })
                    }}
                    onClick={() => {
                      localPick.current = true
                      onValueChange(k.key)
                    }}
                    className={cn(
                      'group/opt relative flex cursor-pointer items-center gap-2.5 rounded-control px-1.5 py-1.5 transition-colors duration-100',
                      selected ? 'bg-surface-3' : 'hover:bg-surface-2',
                      'data-[active]:in-focus-visible:outline-2 data-[active]:in-focus-visible:-outline-offset-2 data-[active]:in-focus-visible:outline-accent',
                    )}
                  >
                    {selected && (
                      <span
                        aria-hidden
                        className="absolute -left-2 top-1/2 h-6 w-[3px] -translate-y-1/2 rounded-r-full bg-gradient-forge shadow-[0_0_10px_var(--pf-glow-indicator)]"
                      />
                    )}
                    <span
                      aria-hidden
                      className={cn(
                        'dot-grid flex h-11 w-16 shrink-0 items-center justify-center overflow-hidden rounded-control border bg-bg p-1 transition-colors',
                        selected ? 'border-accent/45' : 'border-line group-hover/opt:border-line-strong',
                      )}
                    >
                      <SvgImage svg={k.thumbnail_svg} />
                    </span>
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className={cn('line-clamp-2 text-ui leading-tight', selected ? 'font-semibold text-fg' : 'font-medium text-fg')}>
                        {tr(k.label)}
                      </span>
                      <span className="flex min-w-0 items-center gap-1.5">
                        <span className="mono truncate text-2xs text-fg-subtle">{k.default_name}</span>
                        {inLibrary?.has(k.default_name.toLowerCase()) && (
                          <>
                            <Check aria-hidden className="size-3 shrink-0 text-success-text" strokeWidth={2.5} />
                            <span className="sr-only">{tr("(in der Bibliothek)")}</span>
                          </>
                        )}
                      </span>
                    </span>
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
