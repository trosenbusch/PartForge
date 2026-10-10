/**
 * Auswahl der Bibliotheksdateien (Mehrfachauswahl) für die Stapelbearbeitung. Suchfeld und Liste nach dem
 * Combobox-Muster: ↑/↓ bewegen die Markierung, Enter schaltet um, Esc leert erst die Suche und schließt dann.
 * „Alle Bibliotheken“ hebt die Auswahl auf. Angeboten werden Dateien mit registrierten Symbolen bzw. Footprints der
 * gewählten Art (`useLibraryFiles`); lange Listen (eine Datei je Bauteil) zeigen höchstens {@link MAX_OPTIONS} Treffer.
 * Unter dem Auslöser stehen die gewählten Dateien als entfernbare Chips.
 */
import { Check, ChevronsUpDown, CircuitBoard, RotateCw, Search, Shapes, X } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { libraryKey, type LibraryFile } from '@/api/libraries'
import {
  Button,
  controlShell,
  IconButton,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Skeleton,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { FILE_KIND_OF, libraryFileKind, splitPath, type Kind, type LibraryFileKind } from './model'

/** So viele Treffer zeigt die Liste höchstens (die Suche grenzt ein) */
const MAX_OPTIONS = 200
/** So viele gewählte Dateien stehen als Chips unter dem Auslöser */
const MAX_CHIPS = 6

const KIND_META: Record<LibraryFileKind, { title: string; icon: typeof Shapes }> = {
  schlib: { title: 'Symbolbibliotheken', icon: Shapes },
  pcblib: { title: 'Footprint-Bibliotheken', icon: CircuitBoard },
}

interface Option {
  rel: string
  key: string
  kind: LibraryFileKind
  name: string
  folder: string
  /** registrierte Symbole/Footprints (`null` = Datei nicht in der Liste, z. B. aus dem Bibliotheksimport) */
  registered: number | null
}

export interface LibraryPickerProps {
  files: LibraryFile[] | undefined
  loading: boolean
  error: Error | null
  onRetry: () => void
  kinds: Kind[]
  /** gewählte Dateien (relativ); `null` = alle */
  value: string[] | null
  onChange: (value: string[] | null) => void
  /** ID des sichtbaren Labels (Name des Auslösers zusammen mit der Auswahl) */
  labelId: string
}

const byPath = (a: Option, b: Option) => a.rel.localeCompare(b.rel, 'de', { numeric: true, sensitivity: 'base' })

export function LibraryPicker({ files, loading, error, onRetry, kinds, value, onChange, labelId }: LibraryPickerProps) {
  const uid = useId().replace(/:/g, '')
  const listId = `${uid}-list`
  const valueId = `${uid}-value`
  const optionId = (index: number) => `${uid}-opt-${index}`
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  const allowed = useMemo(() => new Set(kinds.map((k) => FILE_KIND_OF[k])), [kinds])
  const selectedKeys = useMemo(() => new Set((value ?? []).map(libraryKey)), [value])

  // Angebot: Dateien mit registrierten Einträgen der gewählten Art – dazu gewählte, die (noch) nicht in der Liste stehen
  const options = useMemo(() => {
    const out: Option[] = []
    const seen = new Set<string>()
    for (const f of files ?? []) {
      const key = libraryKey(f.rel)
      if (!f.exists || f.registered <= 0 || !allowed.has(f.kind) || seen.has(key)) continue
      seen.add(key)
      out.push({ rel: f.rel, key, kind: f.kind, ...splitPath(f.rel), registered: f.registered })
    }
    for (const rel of value ?? []) {
      const key = libraryKey(rel)
      const kind = libraryFileKind(rel)
      if (!kind || !allowed.has(kind) || seen.has(key)) continue
      seen.add(key)
      out.push({ rel, key, kind, ...splitPath(rel), registered: null })
    }
    return out.sort(byPath)
  }, [files, value, allowed])

  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const matches = terms.length ? options.filter((o) => terms.every((t) => o.rel.toLowerCase().includes(t))) : options
  const visible = matches.slice(0, MAX_OPTIONS)
  const hidden = matches.length - visible.length
  const groups = (['schlib', 'pcblib'] as const)
    .map((kind) => ({ kind, options: visible.filter((o) => o.kind === kind) }))
    .filter((g) => g.options.length > 0)
  // Tastaturreihenfolge: 0 = „Alle Bibliotheken“, danach die Treffer in der angezeigten Reihenfolge
  const flat = groups.flatMap((g) => g.options)
  const count = flat.length + 1
  const activeIndex = Math.min(active, count - 1)

  // markierte Zeile sichtbar halten
  useEffect(() => {
    if (open) document.getElementById(`${uid}-opt-${activeIndex}`)?.scrollIntoView({ block: 'nearest' })
  }, [open, activeIndex, uid])

  const toggle = (option: Option) => {
    const current = value ?? []
    const next = selectedKeys.has(option.key)
      ? current.filter((rel) => libraryKey(rel) !== option.key)
      : [...current, option.rel]
    onChange(next.length ? next : null)
  }
  const choose = (index: number) => {
    if (index === 0) onChange(null)
    else if (flat[index - 1]) toggle(flat[index - 1])
  }

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    const step = { ArrowDown: 1, ArrowUp: -1, PageDown: 8, PageUp: -8 }[e.key]
    if (step !== undefined) {
      e.preventDefault()
      setActive(Math.max(0, Math.min(count - 1, activeIndex + step)))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      choose(activeIndex)
    }
  }

  // Auslöser: „Alle Bibliotheken“, der Dateiname oder die Anzahl (nur Dateien der gewählten Art zählen)
  const effective = (value ?? []).filter((rel) => {
    const kind = libraryFileKind(rel)
    return kind !== null && allowed.has(kind)
  })
  const summary =
    value === null
      ? 'Alle Bibliotheken'
      : effective.length === 1
        ? splitPath(effective[0]).name
        : `${formatNumber(effective.length)} Bibliotheken`

  return (
    <div className="flex flex-col gap-2">
      <Popover
        open={open}
        onOpenChange={(o) => {
          setOpen(o)
          if (!o) setQuery('')
          else setActive(0)
        }}
      >
        <PopoverTrigger asChild>
          <button
            type="button"
            aria-labelledby={`${labelId} ${valueId}`}
            aria-haspopup="dialog"
            aria-expanded={open}
            className={cn(
              controlShell({ size: 'sm' }),
              'justify-between text-left outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
              open && 'border-accent',
            )}
          >
            <span id={valueId} className={cn('min-w-0 flex-1 truncate', value === null && 'text-fg-muted')}>
              {summary}
            </span>
            <ChevronsUpDown aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="flex w-[min(26rem,calc(100vw-2rem))] flex-col p-0"
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            inputRef.current?.focus()
          }}
          onEscapeKeyDown={(e) => {
            // erst die Suche leeren, dann schließen
            if (query) {
              e.preventDefault()
              setQuery('')
              setActive(0)
            }
          }}
        >
          <div className="border-b border-line p-2">
            <Input
              ref={inputRef}
              size="sm"
              type="search"
              role="combobox"
              aria-label="Bibliotheksdateien durchsuchen"
              aria-controls={listId}
              aria-expanded
              aria-autocomplete="list"
              aria-activedescendant={optionId(activeIndex)}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setActive(0)
              }}
              onKeyDown={onKeyDown}
              placeholder="Datei oder Ordner suchen …"
              prefix={<Search />}
            />
          </div>
          {error && !files ? (
            <div className="flex flex-col items-start gap-2 px-3 py-3 text-xs text-danger-text" role="alert">
              Bibliotheksdateien konnten nicht gelesen werden: {error.message}
              <Button size="xs" leftIcon={<RotateCw />} onClick={onRetry}>
                Erneut laden
              </Button>
            </div>
          ) : null}
          <div
            id={listId}
            role="listbox"
            aria-multiselectable="true"
            aria-label="Bibliotheksdateien"
            className="max-h-72 overflow-y-auto p-1"
          >
            <PickerOption
              id={optionId(0)}
              active={activeIndex === 0}
              checked={value === null}
              onActivate={() => setActive(0)}
              onToggle={() => choose(0)}
              onKeyDown={onKeyDown}
            >
              <span className="min-w-0 flex-1 text-ui text-fg">Alle Bibliotheken</span>
              <span className="text-2xs text-fg-subtle">keine Einschränkung</span>
            </PickerOption>
            {groups.map((g) => {
              const meta = KIND_META[g.kind]
              const Icon = meta.icon
              return (
                <div key={g.kind} role="group" aria-labelledby={`${uid}-${g.kind}`}>
                  <div id={`${uid}-${g.kind}`} className="micro-label flex items-center gap-1.5 px-2 pb-1 pt-2.5">
                    <Icon aria-hidden className="size-3" />
                    {meta.title}
                  </div>
                  {g.options.map((o) => {
                    const index = flat.indexOf(o) + 1
                    return (
                      <PickerOption
                        key={o.key}
                        id={optionId(index)}
                        active={activeIndex === index}
                        checked={selectedKeys.has(o.key)}
                        onActivate={() => setActive(index)}
                        onToggle={() => choose(index)}
                        onKeyDown={onKeyDown}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block text-ui leading-5 text-fg [overflow-wrap:anywhere]">{o.name}</span>
                          {o.folder && (
                            <span className="mono block text-2xs text-fg-subtle [overflow-wrap:anywhere]">
                              {o.folder}
                            </span>
                          )}
                        </span>
                        <span className="mono shrink-0 text-2xs text-fg-subtle">
                          {o.registered === null ? '–' : formatNumber(o.registered)}
                          <span className="sr-only"> registriert</span>
                        </span>
                      </PickerOption>
                    )
                  })}
                </div>
              )
            })}
            {loading && !files && (
              <div aria-hidden className="flex flex-col gap-2 px-2 py-2">
                {[0, 1, 2].map((i) => (
                  <Skeleton key={i} className="h-4 w-full" />
                ))}
              </div>
            )}
          </div>
          {(hidden > 0 || (files && !options.length) || (terms.length > 0 && !matches.length)) && (
            <p className="border-t border-line px-3 py-2 text-2xs text-fg-subtle" aria-live="polite">
              {hidden > 0
                ? `… und ${formatNumber(hidden)} weitere – Suche eingrenzen`
                : terms.length && !matches.length
                  ? `Keine Datei passt zu „${query.trim()}“.`
                  : 'Keine Bibliothek mit registrierten Bauteilen dieser Art.'}
            </p>
          )}
          <div className="flex items-center justify-between gap-3 border-t border-line px-3 py-2">
            <span className="text-2xs text-fg-subtle" aria-live="polite">
              {value === null ? 'Alle Bibliotheken' : `${plural(effective.length, 'Datei', 'Dateien')} gewählt`}
            </span>
            <Button size="xs" variant="secondary" onClick={() => setOpen(false)}>
              Fertig
            </Button>
          </div>
        </PopoverContent>
      </Popover>

      {value !== null && value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Gewählte Bibliotheken">
          {value.slice(0, MAX_CHIPS).map((rel) => {
            const kind = libraryFileKind(rel)
            const fits = kind !== null && allowed.has(kind)
            const name = splitPath(rel).name
            return (
              <li
                key={rel}
                title={fits ? rel : `${rel} – passt nicht zur gewählten Art und wird nicht geprüft`}
                className={cn(
                  'inline-flex h-6 max-w-full items-center gap-1 rounded-full border border-line-strong bg-surface-2 pl-2.5 pr-0.5 text-2xs text-fg',
                  !fits && 'border-dashed text-fg-subtle',
                )}
              >
                <span className="min-w-0 truncate">{name}</span>
                {!fits && <span className="sr-only"> (passt nicht zur gewählten Art)</span>}
                <IconButton
                  size="xs"
                  className="size-5 rounded-full"
                  label={`${name} aus der Auswahl entfernen`}
                  icon={<X />}
                  tooltip={false}
                  onClick={() => {
                    const next = value.filter((r) => r !== rel)
                    onChange(next.length ? next : null)
                  }}
                />
              </li>
            )
          })}
          {value.length > MAX_CHIPS && (
            <li>
              <Button size="xs" variant="ghost" className="h-6" onClick={() => setOpen(true)}>
                + {formatNumber(value.length - MAX_CHIPS)} weitere
              </Button>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

function PickerOption({
  id,
  active,
  checked,
  onActivate,
  onToggle,
  onKeyDown,
  children,
}: {
  id: string
  active: boolean
  checked: boolean
  onActivate: () => void
  onToggle: () => void
  onKeyDown: (e: KeyboardEvent<HTMLElement>) => void
  children: ReactNode
}) {
  return (
    <div
      id={id}
      role="option"
      aria-selected={checked}
      tabIndex={-1}
      data-active={active || undefined}
      // Fokus bleibt im Suchfeld (aktives Element über aria-activedescendant)
      onMouseDown={(e) => e.preventDefault()}
      onMouseMove={() => {
        if (!active) onActivate()
      }}
      onClick={onToggle}
      onKeyDown={onKeyDown}
      className="flex cursor-default select-none items-center gap-2.5 rounded-control px-2 py-1.5 outline-none data-[active]:bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)]"
    >
      <span
        aria-hidden
        className={cn(
          'flex size-4 shrink-0 items-center justify-center rounded-sm border transition-colors',
          checked ? 'border-transparent bg-gradient-forge text-on-accent' : 'border-line-control bg-control',
        )}
      >
        {checked && <Check className="size-3" />}
      </span>
      {children}
    </div>
  )
}
