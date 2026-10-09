import type { ComponentProps } from 'react'
import { cn } from '@/lib/cn'
import { useFieldContext } from './fieldContext'

export interface TextareaProps extends ComponentProps<'textarea'> {
  invalid?: boolean
  mono?: boolean
  /** Höhe wächst mit dem Inhalt (CSS field-sizing) */
  autoResize?: boolean
}

export function Textarea({ className, invalid, mono, autoResize, disabled, id, rows = 3, ...props }: TextareaProps) {
  const field = useFieldContext()
  const isInvalid = invalid ?? field?.invalid ?? false
  return (
    <textarea
      id={id ?? field?.id}
      rows={rows}
      aria-invalid={isInvalid || undefined}
      aria-describedby={field?.describedBy}
      aria-required={field?.required || undefined}
      disabled={disabled ?? field?.disabled}
      className={cn(
        'block w-full min-w-0 resize-y rounded-button border border-line-control bg-control px-3 py-2 text-sm text-fg',
        'shadow-[inset_0_1px_1px_rgba(0,0,0,.06)] outline-none transition-[border-color,box-shadow,background-color] duration-150',
        'hover:border-line-control-hover',
        'focus:border-accent focus:bg-control-focus focus:shadow-[0_0_0_4px_var(--pf-accent-soft)]',
        'aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-55',
        autoResize && 'resize-none [field-sizing:content] min-h-[4.5rem] max-h-80',
        mono && 'mono text-ui',
        className,
      )}
      {...props}
    />
  )
}
