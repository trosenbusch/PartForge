import { Checkbox as CheckboxPrimitive } from 'radix-ui'
import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'

export type CheckedState = boolean | 'indeterminate'

export interface CheckboxProps {
  checked?: CheckedState
  defaultChecked?: CheckedState
  onCheckedChange?: (checked: CheckedState) => void
  disabled?: boolean
  /** Beschriftung rechts (klickbar) */
  label?: ReactNode
  description?: ReactNode
  id?: string
  name?: string
  className?: string
  'aria-label'?: string
}

export function Checkbox({
  checked,
  defaultChecked,
  onCheckedChange,
  disabled,
  label,
  description,
  id,
  name,
  className,
  'aria-label': ariaLabel,
}: CheckboxProps) {
  const field = useFieldContext()
  const auto = useId()
  const boxId = id ?? field?.id ?? `cb-${auto.replace(/:/g, '')}`

  const box = (
    <CheckboxPrimitive.Root
      id={boxId}
      name={name}
      checked={checked}
      defaultChecked={defaultChecked}
      onCheckedChange={onCheckedChange}
      disabled={disabled ?? field?.disabled}
      aria-label={ariaLabel}
      aria-describedby={field?.describedBy}
      aria-required={field?.required || undefined}
      className={cn(
        'group/cb peer relative flex size-4 shrink-0 items-center justify-center rounded-sm border border-line-control bg-control',
        'shadow-[inset_0_1px_1px_rgba(0,0,0,.12)] outline-none transition-[background-color,border-color,box-shadow] duration-150',
        'hover:border-line-control-hover focus-ring',
        'data-[state=checked]:border-transparent data-[state=checked]:bg-gradient-forge data-[state=checked]:shadow-[var(--pf-glow-control)]',
        'data-[state=indeterminate]:border-transparent data-[state=indeterminate]:bg-gradient-forge',
        'disabled:cursor-not-allowed disabled:opacity-50',
        !label && className,
      )}
    >
      <CheckboxPrimitive.Indicator forceMount className="flex items-center justify-center text-on-accent">
        <svg viewBox="0 0 16 16" className="size-3" fill="none" aria-hidden>
          <path
            d="M4 8h8"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            pathLength={1}
            className="[stroke-dasharray:1] [stroke-dashoffset:1] transition-[stroke-dashoffset] duration-150 ease-out group-data-[state=indeterminate]/cb:[stroke-dashoffset:0]"
          />
          <path
            d="M3.5 8.5l3 3 6-7"
            stroke="currentColor"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
            pathLength={1}
            className="[stroke-dasharray:1] [stroke-dashoffset:1] transition-[stroke-dashoffset] duration-200 ease-out group-data-[state=checked]/cb:[stroke-dashoffset:0]"
          />
        </svg>
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  )

  if (!label) return box
  return (
    <div className={cn('flex items-start gap-2.5', className)}>
      <div className="flex h-5 items-center">{box}</div>
      <label htmlFor={boxId} className="flex cursor-pointer select-none flex-col gap-0.5 peer-disabled:cursor-not-allowed">
        <span className="text-ui leading-5 text-fg">{label}</span>
        {description && <span className="text-xs leading-snug text-fg-muted">{description}</span>}
      </label>
    </div>
  )
}
