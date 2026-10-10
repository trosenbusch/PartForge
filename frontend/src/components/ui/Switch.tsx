import { useI18n } from '@/lib/i18n'
import { Switch as SwitchPrimitive } from 'radix-ui'
import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'

export interface SwitchProps {
  checked?: boolean
  defaultChecked?: boolean
  onCheckedChange?: (checked: boolean) => void
  disabled?: boolean
  size?: 'sm' | 'md'
  /** Beschriftung links, Schalter rechts (Einstellungszeile) */
  label?: ReactNode
  description?: ReactNode
  /** KI-Schalter im Funken-Verlauf */
  tone?: 'accent' | 'spark'
  id?: string
  name?: string
  className?: string
  'aria-label'?: string
}

const sizes = {
  sm: { root: 'h-4 w-7', thumb: 'size-3 data-[state=checked]:translate-x-[12px]' },
  md: { root: 'h-5 w-9', thumb: 'size-4 data-[state=checked]:translate-x-[16px]' },
}

export function Switch({
  checked,
  defaultChecked,
  onCheckedChange,
  disabled,
  size = 'md',
  label,
  description,
  tone = 'accent',
  id,
  name,
  className,
  'aria-label': ariaLabel,
}: SwitchProps) {
  useI18n()
  const field = useFieldContext()
  const auto = useId()
  const switchId = id ?? field?.id ?? `sw-${auto.replace(/:/g, '')}`

  const control = (
    <SwitchPrimitive.Root
      id={switchId}
      name={name}
      checked={checked}
      defaultChecked={defaultChecked}
      onCheckedChange={onCheckedChange}
      disabled={disabled ?? field?.disabled}
      aria-label={ariaLabel}
      aria-describedby={field?.describedBy}
      aria-required={field?.required || undefined}
      className={cn(
        'group/sw relative inline-flex shrink-0 items-center rounded-full border border-line-control bg-surface-3 p-px',
        'shadow-[inset_0_1px_2px_rgba(0,0,0,.25)] outline-none transition-[background-color,border-color,box-shadow] duration-200 focus-ring',
        tone === 'accent'
          ? 'data-[state=checked]:border-transparent data-[state=checked]:bg-gradient-forge data-[state=checked]:shadow-[var(--pf-glow-control)]'
          : 'data-[state=checked]:border-transparent data-[state=checked]:bg-gradient-spark data-[state=checked]:shadow-[var(--pf-glow-control-spark)]',
        'disabled:cursor-not-allowed disabled:opacity-50',
        sizes[size].root,
        !label && className,
      )}
    >
      <SwitchPrimitive.Thumb
        className={cn(
          'pointer-events-none block translate-x-px rounded-full bg-white shadow-[0_1px_3px_rgba(0,0,0,.35)]',
          'transition-transform duration-[260ms] ease-[cubic-bezier(.34,1.56,.64,1)]',
          sizes[size].thumb,
        )}
      />
    </SwitchPrimitive.Root>
  )

  if (!label) return control
  return (
    <div className={cn('flex items-center justify-between gap-6', className)}>
      <label htmlFor={switchId} className="flex min-w-0 cursor-pointer select-none flex-col gap-0.5">
        <span className="text-ui font-medium text-fg">{label}</span>
        {description && <span className="text-xs leading-snug text-fg-muted">{description}</span>}
      </label>
      {control}
    </div>
  )
}
