import type { ComponentProps, ReactNode, Ref } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'
import { controlShell } from './variants'

export interface InputProps extends Omit<ComponentProps<'input'>, 'size' | 'prefix'> {
  /** Links im Feld, z. B. Icon oder „€“ */
  prefix?: ReactNode
  /** Rechts im Feld, z. B. Einheit „Ω“ oder Status-Icon */
  suffix?: ReactNode
  /** Monospace + tabellarische Ziffern (Werte, MPNs, Pfade) */
  mono?: boolean
  invalid?: boolean
  size?: 'sm' | 'md' | 'lg'
  containerClassName?: string
  ref?: Ref<HTMLInputElement>
}

export function Input({
  prefix,
  suffix,
  mono,
  invalid,
  size = 'md',
  className,
  containerClassName,
  disabled,
  id,
  ...props
}: InputProps) {
  const field = useFieldContext()
  const isInvalid = invalid ?? field?.invalid ?? false
  const isDisabled = disabled ?? field?.disabled
  return (
    <div
      data-invalid={isInvalid || undefined}
      data-disabled={isDisabled || undefined}
      className={cn(controlShell({ size }), containerClassName)}
    >
      {prefix && (
        <span
          aria-hidden
          className="flex shrink-0 items-center text-fg-subtle [&_svg]:size-4 group-focus-within/control:text-fg-muted"
        >
          {prefix}
        </span>
      )}
      <input
        id={id ?? field?.id}
        aria-invalid={isInvalid || undefined}
        aria-describedby={field?.describedBy}
        aria-required={field?.required || undefined}
        disabled={isDisabled}
        className={cn(
          'h-full w-full min-w-0 flex-1 bg-transparent outline-none',
          'disabled:cursor-not-allowed [&::-webkit-search-cancel-button]:hidden',
          mono && 'mono text-ui placeholder:font-sans placeholder:tracking-normal',
          className,
        )}
        {...props}
      />
      {suffix && (
        <span className="flex shrink-0 items-center gap-1 pl-1 text-xs text-fg-subtle [&_svg]:size-4">{suffix}</span>
      )}
    </div>
  )
}
