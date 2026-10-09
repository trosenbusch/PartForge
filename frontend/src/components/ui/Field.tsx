import { CircleAlert } from 'lucide-react'
import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { FieldContext } from './fieldContext'

export interface FieldProps {
  label: ReactNode
  children: ReactNode
  /** Hilfetext (bei layout="row" unter dem Label, sonst unter dem Control) */
  help?: ReactNode
  /** Fehlermeldung (ersetzt den Hilfetext, setzt aria-invalid) */
  error?: ReactNode
  /** Kleiner Hinweis rechts neben dem Label (z. B. „optional“, Einheit) */
  hint?: ReactNode
  /** Pflichtfeld: Sternchen am Label + `aria-required` am Control */
  required?: boolean
  disabled?: boolean
  /** Eigene ID für das Control (Standard: automatisch) */
  htmlFor?: string
  /**
   * stacked = Label oben; row = Einstellungszeile: Label + Hilfe links, Control rechts –
   * aber erst, wenn die Zeile mindestens 40 rem breit ist (Container-Query), darunter gestapelt.
   */
  layout?: 'stacked' | 'row'
  className?: string
}

/** Formularfeld: Label, Control, Hilfe-/Fehlertext. Das Control erhält id & aria-Attribute automatisch. */
export function Field({
  label,
  children,
  help,
  error,
  hint,
  required,
  disabled,
  htmlFor,
  layout = 'stacked',
  className,
}: FieldProps) {
  const auto = useId()
  const id = htmlFor ?? `field-${auto.replace(/:/g, '')}`
  const labelId = `${id}-label`
  const helpId = `${id}-help`
  const errorId = `${id}-error`
  const invalid = Boolean(error)
  const describedBy = invalid ? errorId : help ? helpId : undefined

  const labelEl = (
    <div className={cn('flex min-h-5 items-baseline gap-3', layout === 'row' ? 'justify-start gap-2' : 'justify-between')}>
      <label id={labelId} htmlFor={id} className={cn('text-ui font-medium text-fg', disabled && 'opacity-60')}>
        {label}
        {required && (
          <span className="ml-0.5 text-accent-text" aria-hidden>
            *
          </span>
        )}
      </label>
      {hint && <span className="text-2xs text-fg-subtle">{hint}</span>}
    </div>
  )

  const messages = invalid ? (
    <p id={errorId} role="alert" className="flex items-start gap-1.5 text-xs leading-snug text-danger-text">
      <CircleAlert className="mt-px size-3.5 shrink-0" aria-hidden />
      <span>{error}</span>
    </p>
  ) : help ? (
    <p id={helpId} className="text-xs leading-snug text-fg-muted">
      {help}
    </p>
  ) : null

  return (
    <FieldContext.Provider value={{ id, labelId, describedBy, invalid, disabled, required }}>
      {layout === 'row' ? (
        <div className={cn('@container', className)}>
          <div className="grid gap-x-8 gap-y-2 @[40rem]:grid-cols-[minmax(12rem,1fr)_minmax(16rem,22rem)] @[40rem]:items-start">
            <div className="flex min-w-0 flex-col gap-1 @[40rem]:pt-1.5">
              {labelEl}
              {messages}
            </div>
            <div className="min-w-0">{children}</div>
          </div>
        </div>
      ) : (
        <div className={cn('flex flex-col gap-1.5', className)}>
          {labelEl}
          {children}
          {messages}
        </div>
      )}
    </FieldContext.Provider>
  )
}
