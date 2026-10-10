import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { Command } from 'cmdk'
import { Check, ChevronsUpDown, Plus, Search, X } from 'lucide-react'
import { Popover as PopoverPrimitive } from 'radix-ui'
import { useId, useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'
import { controlShell } from './variants'

export interface ComboboxOption {
  value: string
  label: string
  description?: string
  icon?: ReactNode
  /** Zusätzliche Suchbegriffe */
  keywords?: string[]
  group?: string
  disabled?: boolean
}

export interface ComboboxProps {
  options: ComboboxOption[]
  value: string | null
  onValueChange: (value: string | null) => void
  placeholder?: string
  searchPlaceholder?: string
  emptyText?: string
  /** Eigene Eingabe als neuen Wert zulassen (Eintrag „xyz“ übernehmen) */
  allowCustom?: boolean
  customLabel?: (query: string) => string
  /** Auswahl per ✕ zurücksetzbar */
  clearable?: boolean
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  invalid?: boolean
  mono?: boolean
  id?: string
  className?: string
  contentClassName?: string
  'aria-label'?: string
}

/** Durchsuchbare Auswahl (Popover + cmdk), vollständig per Tastatur bedienbar. */
export function Combobox({
  options,
  value,
  onValueChange,
  placeholder = tr("Auswählen …"),
  searchPlaceholder = tr("Suchen …"),
  emptyText = tr("Keine Treffer"),
  allowCustom,
  customLabel = (q) => tr("„{0}“ übernehmen", { "0": String(q) }),
  clearable,
  size = 'md',
  disabled,
  invalid,
  mono,
  id,
  className,
  contentClassName,
  'aria-label': ariaLabel,
}: ComboboxProps) {
  const { t: tr } = useI18n()
  const field = useFieldContext()
  const listId = `cb-pop-${useId().replace(/:/g, '')}`
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const selected = options.find((o) => o.value === value)
  const isInvalid = invalid ?? field?.invalid ?? false
  const isDisabled = disabled ?? field?.disabled

  const grouped = useMemo(() => {
    const map = new Map<string, ComboboxOption[]>()
    for (const opt of options) {
      const key = opt.group ?? ''
      map.set(key, [...(map.get(key) ?? []), opt])
    }
    return [...map.entries()]
  }, [options])

  const trimmed = query.trim()
  const showCustom =
    allowCustom && trimmed.length > 0 && !options.some((o) => o.label.toLowerCase() === trimmed.toLowerCase())

  const select = (v: string | null) => {
    onValueChange(v)
    setOpen(false)
    setQuery('')
  }

  const onTriggerKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !open) {
      e.preventDefault()
      setOpen(true)
    } else if ((e.key === 'Delete' || e.key === 'Backspace') && clearable && value) {
      e.preventDefault()
      onValueChange(null)
    }
  }

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) setQuery('')
      }}
    >
      {/* Trigger und „Auswahl entfernen“ sind Geschwister – kein Button im Button */}
      <PopoverPrimitive.Anchor asChild>
        <div className={cn('relative min-w-0', className)}>
          <PopoverPrimitive.Trigger asChild disabled={isDisabled}>
            <button
              type="button"
              id={id ?? field?.id}
              role="combobox"
              aria-expanded={open}
              aria-controls={listId}
              aria-haspopup="dialog"
              aria-label={ariaLabel}
              aria-invalid={isInvalid || undefined}
              aria-describedby={field?.describedBy}
              aria-required={field?.required || undefined}
              data-invalid={isInvalid || undefined}
              data-disabled={isDisabled || undefined}
              onKeyDown={onTriggerKeyDown}
              className={cn(
                controlShell({ size }),
                'justify-between text-left outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
                open && 'border-accent',
                clearable && value && 'pr-9',
              )}
            >
              <span className={cn('flex min-w-0 flex-1 items-center gap-2', !selected && !value && 'text-fg-subtle')}>
                {selected?.icon}
                <span className={cn('truncate', mono && 'mono text-ui')}>{selected?.label ?? value ?? placeholder}</span>
              </span>
              {!(clearable && value) && <ChevronsUpDown aria-hidden className="size-4 shrink-0 text-fg-subtle" />}
            </button>
          </PopoverPrimitive.Trigger>
          {clearable && value && !isDisabled && (
            <button
              type="button"
              tabIndex={-1}
              aria-label={tr("Auswahl entfernen")}
              onClick={() => onValueChange(null)}
              className="absolute right-2 top-1/2 flex size-5 -translate-y-1/2 items-center justify-center rounded-sm text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      </PopoverPrimitive.Anchor>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          id={listId}
          aria-label={ariaLabel ? tr("{0} – Auswahl", { "0": String(ariaLabel) }) : tr("Auswahl")}
          align="start"
          sideOffset={6}
          collisionPadding={10}
          className={cn(
            'pop-anim glass z-popover w-[max(var(--radix-popover-trigger-width),16rem)] overflow-hidden rounded-card p-0 text-fg outline-none',
            contentClassName,
          )}
        >
          <Command
            loop
            vimBindings={false}
            defaultValue={selected ? `${selected.label} ${selected.value}` : undefined}
            className="flex flex-col"
          >
            <div className="flex items-center gap-2 border-b border-line px-3">
              <Search className="size-4 shrink-0 text-fg-subtle" />
              <Command.Input
                value={query}
                onValueChange={setQuery}
                placeholder={searchPlaceholder}
                className="h-10 w-full bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle"
              />
            </div>
            <Command.List className="max-h-72 overflow-y-auto p-1">
              <Command.Empty className="px-3 py-6 text-center text-xs text-fg-muted">{emptyText}</Command.Empty>
              {grouped.map(([group, opts]) => (
                <Command.Group
                  key={group || '_'}
                  heading={group || undefined}
                  className="[&_[cmdk-group-heading]]:micro-label [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:pt-2"
                >
                  {opts.map((opt) => (
                    <Command.Item
                      key={opt.value}
                      value={`${opt.label} ${opt.value}`}
                      keywords={opt.keywords}
                      disabled={opt.disabled}
                      onSelect={() => select(opt.value)}
                      className={cn(
                        'flex cursor-default select-none items-center gap-2.5 rounded-control px-2 py-1.5 text-ui outline-none',
                        'data-[selected=true]:bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)] data-[disabled=true]:opacity-45',
                        '[&_svg]:size-4 [&_svg]:text-fg-muted',
                      )}
                    >
                      {opt.icon}
                      <span className="flex min-w-0 flex-1 flex-col">
                        <span className={cn('truncate', mono && 'mono text-xs')}>{opt.label}</span>
                        {opt.description && <span className="truncate text-2xs text-fg-subtle">{opt.description}</span>}
                      </span>
                      {opt.value === value && <Check className="text-accent!" />}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
              {showCustom && (
                <Command.Item
                  value={`__custom__ ${trimmed}`}
                  onSelect={() => select(trimmed)}
                  className="flex cursor-default items-center gap-2.5 rounded-control px-2 py-1.5 text-ui text-accent-text outline-none data-[selected=true]:bg-accent-soft"
                >
                  <Plus className="size-4" />
                  {customLabel(trimmed)}
                </Command.Item>
              )}
            </Command.List>
          </Command>
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}
