import { useI18n } from '@/lib/i18n'
import { motion } from 'motion/react'
import { RadioGroup } from 'radix-ui'
import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'
import { Tooltip } from './Tooltip'

export interface SegmentedOption<V extends string = string> {
  value: V
  label?: ReactNode
  icon?: ReactNode
  disabled?: boolean
  /**
   * Tooltip. Bei reinen Icon-Segmenten zugleich der Name (`aria-label`); mit sichtbarem `label` bleibt der Name das
   * Label, der Tooltip ergänzt es (Beschreibung beim Fokus) – z. B. „Klein (L)“ mit „Kleine Pads für dichte Bestückung“.
   */
  title?: string
}

export interface SegmentedControlProps<V extends string = string> {
  value: V
  onValueChange: (value: V) => void
  options: SegmentedOption<V>[]
  size?: 'sm' | 'md'
  /** Segmente füllen die Breite gleichmäßig */
  fullWidth?: boolean
  disabled?: boolean
  className?: string
  /** Name der Gruppe, wenn kein sichtbares Label sie beschriftet */
  'aria-label'?: string
  /**
   * ID des sichtbaren Labels der Gruppe. In einem `Field` automatisch dessen Label (Radiogruppen verstehen kein
   * `<label for>`); ein `aria-label` geht vor.
   */
  'aria-labelledby'?: string
}

/** Umschalter mit gleitender Markierung (Radio-Semantik, Pfeiltasten). */
export function SegmentedControl<V extends string = string>({
  value,
  onValueChange,
  options,
  size = 'md',
  fullWidth,
  disabled,
  className,
  'aria-label': ariaLabel,
  'aria-labelledby': ariaLabelledBy,
}: SegmentedControlProps<V>) {
  useI18n()
  const layoutId = `seg-${useId()}`
  const field = useFieldContext()
  const labelledBy = ariaLabel ? undefined : (ariaLabelledBy ?? field?.labelId)
  return (
    <RadioGroup.Root
      value={value}
      onValueChange={(v) => onValueChange(v as V)}
      orientation="horizontal"
      loop
      disabled={disabled ?? field?.disabled}
      aria-label={ariaLabel}
      aria-labelledby={labelledBy}
      aria-describedby={field?.describedBy}
      aria-required={field?.required || undefined}
      className={cn(
        'relative inline-flex items-center gap-0.5 rounded-button border border-line bg-surface-2 p-0.5',
        'shadow-[inset_0_1px_2px_rgba(0,0,0,.15)]',
        fullWidth && 'flex w-full',
        size === 'sm' ? 'h-7' : 'h-8.5',
        className,
      )}
    >
      {options.map((opt) => {
        const active = opt.value === value
        const iconOnly = !opt.label
        const item = (
          <RadioGroup.Item
            key={opt.value}
            value={opt.value}
            disabled={opt.disabled}
            // Name = sichtbares Label (Sprachsteuerung); nur reine Icon-Segmente heißen wie ihr Tooltip
            aria-label={iconOnly ? opt.title : undefined}
            className={cn(
              'relative z-0 flex h-full items-center justify-center gap-1.5 whitespace-nowrap rounded-control font-medium outline-none',
              'text-fg-muted transition-colors duration-150 hover:text-fg focus-ring',
              'disabled:pointer-events-none disabled:opacity-45 data-[state=checked]:text-fg',
              size === 'sm' ? 'px-2.5 text-xs [&_svg]:size-3.5' : 'px-3 text-ui [&_svg]:size-4',
              fullWidth && 'flex-1',
            )}
          >
            {active && (
              <motion.span
                layoutId={layoutId}
                aria-hidden
                className="absolute inset-0 -z-10 rounded-control border border-line-strong bg-surface shadow-[0_1px_3px_rgba(0,0,0,.18),inset_0_1px_0_var(--pf-highlight)]"
                transition={{ type: 'spring', stiffness: 520, damping: 38 }}
              />
            )}
            {opt.icon}
            {opt.label}
          </RadioGroup.Item>
        )
        return opt.title ? (
          <Tooltip key={opt.value} content={opt.title}>
            {item}
          </Tooltip>
        ) : (
          item
        )
      })}
    </RadioGroup.Root>
  )
}
