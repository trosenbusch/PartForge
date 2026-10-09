/**
 * Werkzeugleiste über der Bauteiltabelle: Kategoriebaum ein/aus, Suche (entprellt, Strg+F, wächst mit dem Platz),
 * Filter, Ansichten | Trefferzahl, Spalten (inkl. Zeilenhöhe), Export, Import, Detailbereich. Bei wenig Platz
 * entfallen zuerst die Beschriftungen, nie die Trefferzahl.
 */
import { PanelLeftClose, PanelLeftOpen, PanelRight, Search, Upload, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode, type Ref } from 'react'
import { Button, IconButton, Kbd, Spinner, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'

/** Wartezeit nach der letzten Taste, bevor die Tabelle sucht (Suche über große Kategorien kostet Zeit) */
const SEARCH_DEBOUNCE_MS = 350

export interface PartsToolbarProps {
  label: string
  search: string
  onSearchChange: (search: string) => void
  searchRef?: Ref<HTMLInputElement>
  /** Filter-Knopf (Popover) */
  filter: ReactNode
  /** Ansichten-Menü */
  views: ReactNode
  columns: ReactNode
  exportMenu: ReactNode
  total: number | null
  unfilteredTotal: number | null
  loading: boolean
  /** Laden fehlgeschlagen – statt „…“ ein Gedankenstrich */
  failed?: boolean
  onImport: () => void
  treeCollapsed: boolean
  onToggleTree: () => void
  detailOpen: boolean
  onToggleDetail: () => void
  canOpenDetail: boolean
  /** Platzstufe: 0 = alles beschriftet, 1 = Spalten/Export/Import nur als Symbol, 2 = alles als Symbol */
  level: 0 | 1 | 2
}

/**
 * Sucheingabe mit eigener Entprellung: Tippen bleibt flüssig, die Tabelle fragt erst 350 ms nach der letzten Taste
 * (bei normalem Tipptempo eine Abfrage je Suchbegriff – überholte Abfragen bricht die Tabelle ab). Enter sucht sofort.
 */
function SearchField({
  value,
  onChange,
  label,
  inputRef,
  short,
}: {
  value: string
  onChange: (v: string) => void
  label: string
  inputRef?: Ref<HTMLInputElement>
  /** Wenig Platz: kurzer Platzhalter (der Kategoriename steht im Titel) */
  short?: boolean
}) {
  const [text, setText] = useState(value)
  const [synced, setSynced] = useState(value)
  // von außen gesetzt (Ansicht, „Filter zurücksetzen“) → übernehmen
  if (value !== synced) {
    setSynced(value)
    setText(value)
  }
  const latest = useRef(onChange)
  useEffect(() => {
    latest.current = onChange
  })
  useEffect(() => {
    if (text === value) return
    const t = window.setTimeout(() => latest.current(text), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(t)
  }, [text, value])

  return (
    <div className="@container w-full min-w-0">
      <div className="group/search flex h-8 w-full min-w-0 items-center gap-2 rounded-control border border-line-control bg-control px-2.5 shadow-[inset_0_1px_1px_rgba(0,0,0,.06)] transition-[border-color,box-shadow] duration-150 hover:border-line-control-hover focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--pf-accent-soft)]">
        <Search aria-hidden className="size-3.5 shrink-0 text-fg-subtle group-focus-within/search:text-fg-muted" />
        <input
          ref={inputRef}
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && text) {
              e.preventDefault()
              e.stopPropagation()
              setText('')
              onChange('')
            } else if (e.key === 'Enter') {
              onChange(text)
            }
          }}
          placeholder={short ? 'Suchen …' : `${label} durchsuchen …`}
          aria-label={`${label} durchsuchen`}
          aria-keyshortcuts="Control+F"
          spellCheck={false}
          className="h-full min-w-0 flex-1 truncate bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle [&::-webkit-search-cancel-button]:hidden"
        />
        {text ? (
          <button
            type="button"
            onClick={() => {
              setText('')
              onChange('')
            }}
            aria-label="Suche leeren"
            className="flex size-5 shrink-0 items-center justify-center rounded-sm text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
          >
            <X aria-hidden className="size-3" />
          </button>
        ) : label.length <= 16 ? (
          // Kürzel nur, wenn Platz ist – der Platzhalter geht vor
          <Kbd hotkey="mod+f" size="xs" className="hidden group-focus-within/search:opacity-0 @[17rem]:inline-flex" />
        ) : null}
      </div>
    </div>
  )
}

export function PartsToolbar({
  label,
  search,
  onSearchChange,
  searchRef,
  filter,
  views,
  columns,
  exportMenu,
  total,
  unfilteredTotal,
  loading,
  failed,
  onImport,
  treeCollapsed,
  onToggleTree,
  detailOpen,
  onToggleDetail,
  canOpenDetail,
  level,
}: PartsToolbarProps) {
  const filtered = total !== null && unfilteredTotal !== null && total !== unfilteredTotal
  const iconOnly = level >= 1
  return (
    <div role="group" aria-label={`Werkzeuge für ${label}`} className={cn('flex h-9 shrink-0 items-center', level === 2 ? 'gap-1' : 'gap-1.5')}>
      <IconButton
        size="sm"
        label={treeCollapsed ? 'Kategorien einblenden' : 'Kategorien ausblenden'}
        icon={treeCollapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
        onClick={onToggleTree}
        aria-pressed={!treeCollapsed}
      />
      <div className="min-w-40 max-w-80 flex-1">
        <SearchField value={search} onChange={onSearchChange} label={label} inputRef={searchRef} short={level === 2} />
      </div>
      {filter}
      {views}
      <span
        className="ml-auto flex shrink-0 items-center gap-1 whitespace-nowrap pl-2 pr-1 text-xs text-fg-muted"
        aria-live="polite"
      >
        {loading && <Spinner size={12} tone="accent" />}
        {total === null ? (
          failed ? null : '…'
        ) : filtered ? (
          <>
            <span className="mono font-medium text-fg">{formatNumber(total)}</span>
            <span>von {formatNumber(unfilteredTotal ?? 0)}</span>
          </>
        ) : (
          <>
            <span className="mono font-medium text-fg">{formatNumber(total)}</span>
            <span>{total === 1 ? 'Bauteil' : 'Bauteile'}</span>
          </>
        )}
      </span>
      <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-line-strong" />
      {columns}
      {exportMenu}
      {/* Name = sichtbarer Text („Import“); nur als Symbolknopf trägt er eine eigene Beschriftung */}
      <Tooltip content="Tabelle importieren (CSV, Excel, ODS)" disabled={!iconOnly}>
        <Button
          variant="ghost"
          size="sm"
          leftIcon={<Upload />}
          onClick={onImport}
          aria-label={iconOnly ? 'Tabelle importieren' : undefined}
          iconOnly={iconOnly}
        >
          {!iconOnly && 'Import'}
        </Button>
      </Tooltip>
      <span aria-hidden className="mx-1 h-5 w-px shrink-0 bg-line-strong" />
      <IconButton
        size="sm"
        label={detailOpen ? 'Details ausblenden' : 'Details einblenden'}
        icon={<PanelRight />}
        onClick={onToggleDetail}
        disabled={!detailOpen && !canOpenDetail}
        aria-pressed={detailOpen}
        className={cn(detailOpen && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text')}
      />
    </div>
  )
}
