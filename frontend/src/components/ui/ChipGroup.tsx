import { Check } from 'lucide-react'
import { ToggleGroup } from 'radix-ui'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface ChipOption<V extends string = string> {
  value: V
  label: ReactNode
  /** Zusatz rechts im Chip (z. B. Anzahl) */
  meta?: ReactNode
  disabled?: boolean
}

export interface ChipGroupProps<V extends string = string> {
  /** Ausgewählte Werte (Mehrfachauswahl) */
  value: V[]
  onValueChange: (value: V[]) => void
  options: ChipOption<V>[]
  size?: 'sm' | 'md'
  /** Monospace-Beschriftung (Bauformen, Werte) */
  mono?: boolean
  disabled?: boolean
  className?: string
  'aria-label': string
}

/**
 * Mehrfachauswahl als Chips (z. B. Bauformen 0402 · 0603 · 0805 im Serien-Assistenten).
 * Pfeiltasten bewegen den Fokus, Leertaste/Enter schaltet um.
 */
export function ChipGroup<V extends string = string>({
  value,
  onValueChange,
  options,
  size = 'md',
  mono,
  disabled,
  className,
  'aria-label': ariaLabel,
}: ChipGroupProps<V>) {
  return (
    <ToggleGroup.Root
      type="multiple"
      value={value}
      onValueChange={(v) => onValueChange(v as V[])}
      disabled={disabled}
      aria-label={ariaLabel}
      className={cn('flex flex-wrap gap-1.5', className)}
    >
      {options.map((opt) => (
        <ToggleGroup.Item
          key={opt.value}
          value={opt.value}
          disabled={opt.disabled}
          className={cn(
            'group/chip inline-flex items-center gap-1.5 rounded-full border font-medium outline-none transition-[background-color,border-color,color] duration-150 focus-ring',
            'border-line-strong bg-surface-2 text-fg-muted hover:border-line-control hover:text-fg',
            'data-[state=on]:border-accent/45 data-[state=on]:bg-accent-soft data-[state=on]:text-accent-text',
            'disabled:pointer-events-none disabled:opacity-45',
            size === 'sm' ? 'h-6 px-2.5 text-2xs' : 'h-7 px-3 text-xs',
            mono && 'mono',
          )}
        >
          <Check aria-hidden className="-ml-0.5 hidden size-3.5 group-data-[state=on]/chip:block" />
          {opt.label}
          {opt.meta !== undefined && <span className="tabular-nums text-fg-subtle">{opt.meta}</span>}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  )
}
