import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface StepHeadingProps {
  /** Mikro-Label über dem Titel, z. B. „Schritt 2 von 5“ */
  eyebrow?: ReactNode
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  id?: string
  className?: string
}

/**
 * Überschrift eines Assistentenschritts (h2 – die h1 ist der Topbar-Titel). Programmatisch fokussierbar
 * (`data-step-heading`): nach jedem Schrittwechsel setzt die Seite den Fokus hierher, statt ihn auf `<body>` fallen zu
 * lassen.
 */
export function StepHeading({ eyebrow, title, description, actions, id, className }: StepHeadingProps) {
  return (
    <div className={cn('flex flex-col gap-3 @[52rem]:flex-row @[52rem]:items-end @[52rem]:justify-between', className)}>
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="micro-label mb-1">{eyebrow}</div>}
        <h2
          id={id}
          tabIndex={-1}
          data-step-heading=""
          className="scroll-mt-[calc(var(--pf-topbar-height)+1rem)] text-h3 font-semibold tracking-[-0.02em] text-fg outline-none"
        >
          {title}
        </h2>
        {description && <p className="mt-1 text-ui leading-relaxed text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
