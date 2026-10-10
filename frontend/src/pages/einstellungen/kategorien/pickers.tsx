import { t as translate, useI18n } from '@/lib/i18n'
/** Auswahl von Kategoriesymbol und -farbe (Radiogruppen mit Pfeiltasten) sowie die farbige Symbolkachel. */
import { Check, Pipette } from 'lucide-react'
import { useRef, type CSSProperties, type KeyboardEvent, type RefObject } from 'react'
import { CategoryIcon } from '@/components/data'
import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { CATEGORY_COLORS, CATEGORY_ICON_CHOICES, HEX_COLOR, sameIcon } from './meta'

/**
 * Symbolfarbe in Kategoriefarbe (`--cat`): im hellen Theme abgedunkelt, damit das Symbol auf der eigenen Tönung
 * ≥ 3:1 erreicht (Gelb, Grün, Grau wären sonst ~2:1).
 */
const TINTED_ICON = 'text-[color:var(--cat)] light:text-[color:color-mix(in_oklab,var(--cat)_72%,black)]'

/** Symbol in einer Kachel in Kategoriefarbe */
export function CategoryTile({
  icon,
  color,
  size = 'md',
  className,
}: {
  icon?: string | null
  color?: string | null
  size?: 'sm' | 'md' | 'lg'
  className?: string
}) {
  useI18n()
  const c = color && HEX_COLOR.test(color) ? color : '#94A3B8'
  return (
    <span
      aria-hidden
      className={cn(
        'flex shrink-0 items-center justify-center border',
        size === 'sm' && 'size-7 rounded-control [&_svg]:size-3.5',
        size === 'md' && 'size-9 rounded-control [&_svg]:size-4',
        size === 'lg' && 'size-12 rounded-button [&_svg]:size-5.5',
        TINTED_ICON,
        className,
      )}
      style={
        {
          '--cat': c,
          background: `color-mix(in oklab, ${c} 16%, transparent)`,
          borderColor: `color-mix(in oklab, ${c} 32%, transparent)`,
          boxShadow: size === 'lg' ? `0 8px 24px -12px ${c}` : undefined,
        } as CSSProperties
      }
    >
      <CategoryIcon name={icon} className="size-auto" />
    </span>
  )
}

/** Roving-Tabindex für Raster-Radiogruppen: Pfeile wählen, Pos1/Ende springen */
function useGridKeys<T>(ref: RefObject<HTMLDivElement | null>, items: T[], selectedIndex: number, onSelect: (item: T) => void) {
  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const buttons = Array.from(ref.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? [])
    if (!buttons.length) return
    const first = buttons[0].getBoundingClientRect().top
    const cols = Math.max(1, buttons.filter((b) => Math.abs(b.getBoundingClientRect().top - first) < 2).length)
    let next = index
    if (e.key === 'ArrowRight') next = index + 1
    else if (e.key === 'ArrowLeft') next = index - 1
    else if (e.key === 'ArrowDown') next = index + cols
    else if (e.key === 'ArrowUp') next = index - cols
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    else return
    e.preventDefault()
    next = Math.max(0, Math.min(items.length - 1, next))
    onSelect(items[next])
    buttons[next]?.focus()
  }
  const tabIndexOf = (index: number) => (index === (selectedIndex >= 0 ? selectedIndex : 0) ? 0 : -1)
  return { onKeyDown, tabIndexOf }
}

export function IconPicker({
  value,
  onChange,
  color,
  className,
}: {
  value: string
  onChange: (icon: string) => void
  color?: string
  className?: string
}) {
  useI18n()
  const selected = CATEGORY_ICON_CHOICES.findIndex((c) => sameIcon(value, c.name))
  const ref = useRef<HTMLDivElement>(null)
  const grid = useGridKeys(ref, CATEGORY_ICON_CHOICES, selected, (c) => onChange(c.name))
  return (
    <div
      ref={ref}
      role="radiogroup"
      aria-label={translate("Symbol der Kategorie")}
      className={cn('grid grid-cols-[repeat(auto-fill,minmax(2.125rem,1fr))] gap-1', className)}
    >
      {CATEGORY_ICON_CHOICES.map((c, i) => {
        const active = i === selected
        return (
          <Tooltip key={c.name} content={translate(c.label)} delayDuration={300}>
            <button
              type="button"
              role="radio"
              aria-checked={active}
              aria-label={translate(c.label)}
              tabIndex={grid.tabIndexOf(i)}
              onClick={() => onChange(c.name)}
              onKeyDown={(e) => grid.onKeyDown(e, i)}
              className={cn(
                'flex aspect-square items-center justify-center rounded-control border outline-none transition-colors focus-ring [&_svg]:size-4',
                active ? cn('border-transparent', color && TINTED_ICON) : 'border-transparent text-fg-muted hover:bg-surface-2 hover:text-fg',
              )}
              style={
                active && color
                  ? ({
                      '--cat': color,
                      background: `color-mix(in oklab, ${color} 16%, transparent)`,
                      borderColor: `color-mix(in oklab, ${color} 40%, transparent)`,
                    } as CSSProperties)
                  : undefined
              }
            >
              <CategoryIcon name={c.name} className="size-auto" />
            </button>
          </Tooltip>
        )
      })}
    </div>
  )
}

/** Helle Farbe → dunkles Häkchen */
function checkColor(hex: string): string {
  const n = Number.parseInt(hex.slice(1), 16)
  const r = (n >> 16) & 255
  const g = (n >> 8) & 255
  const b = n & 255
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#0B0E14' : '#FFFFFF'
}

export function ColorPicker({ value, onChange, className }: { value: string; onChange: (color: string) => void; className?: string }) {
  useI18n()
  const upper = value.toUpperCase()
  const selected = CATEGORY_COLORS.findIndex((c) => c.value.toUpperCase() === upper)
  const custom = selected < 0 && HEX_COLOR.test(value)
  const ref = useRef<HTMLDivElement>(null)
  const grid = useGridKeys(ref, CATEGORY_COLORS, selected, (c) => onChange(c.value))
  return (
    <div className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <div ref={ref} role="radiogroup" aria-label={translate("Farbe der Kategorie")} className="flex flex-wrap gap-1.5">
        {CATEGORY_COLORS.map((c, i) => {
          const active = i === selected
          return (
            <Tooltip key={c.value} content={`${translate(c.label)} · ${c.value}`} delayDuration={300}>
              <button
                type="button"
                role="radio"
                aria-checked={active}
                aria-label={translate(c.label)}
                tabIndex={grid.tabIndexOf(custom ? -1 : i)}
                onClick={() => onChange(c.value)}
                onKeyDown={(e) => grid.onKeyDown(e, i)}
                className={cn(
                  'relative flex size-6 items-center justify-center rounded-full outline-none transition-transform focus-ring hover:scale-110',
                  active && 'ring-2 ring-fg/80 ring-offset-2 ring-offset-surface',
                )}
                style={{ background: c.value }}
              >
                {active && <Check aria-hidden className="size-3.5" style={{ color: checkColor(c.value) }} strokeWidth={3} />}
              </button>
            </Tooltip>
          )
        })}
      </div>
      <Tooltip content={translate("Eigene Farbe wählen")}>
        <label
          className={cn(
            'relative flex size-6 cursor-pointer items-center justify-center rounded-full border border-dashed border-line-control text-fg-subtle transition-colors focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent hover:text-fg',
            custom && 'border-solid ring-2 ring-fg/80 ring-offset-2 ring-offset-surface',
          )}
          style={custom ? { background: value, borderColor: 'transparent' } : undefined}
        >
          {custom ? <Check aria-hidden className="size-3.5" style={{ color: checkColor(value) }} strokeWidth={3} /> : <Pipette aria-hidden className="size-3" />}
          <input
            type="color"
            aria-label={translate("Eigene Farbe")}
            value={HEX_COLOR.test(value) ? value : '#94A3B8'}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            className="absolute inset-0 cursor-pointer opacity-0"
          />
        </label>
      </Tooltip>
      <span className="mono ml-1 text-2xs text-fg-subtle">{upper}</span>
    </div>
  )
}
