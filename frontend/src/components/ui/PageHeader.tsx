import type { ReactNode } from 'react'
import { usePageHeading } from '@/app/topbar'
import { cn } from '@/lib/cn'

export interface PageHeaderProps {
  title: ReactNode
  description?: ReactNode
  /** Mikro-Label über dem Titel (z. B. Bereich) */
  eyebrow?: ReactNode
  /** Icon in einer neutralen Kachel links */
  icon?: ReactNode
  /** Aktionen rechts (Buttons) */
  actions?: ReactNode
  /** Zusätzlicher Inhalt unter dem Titel (Tabs, Filter, Badges) */
  children?: ReactNode
  className?: string
}

/**
 * Großer Seitenkopf im Inhaltsbereich. Sein Titel ist die <h1> der Seite (die Topbar zeigt den Titel dann
 * ohne Überschrift). Für Tabellen-Seiten weglassen und nur Topbar + `<PageActions>` nutzen.
 */
export function PageHeader({ title, description, eyebrow, icon, actions, children, className }: PageHeaderProps) {
  usePageHeading()
  return (
    <header className={cn('flex flex-col gap-4', className)}>
      <div className="flex items-start gap-4">
        {icon && (
          <div
            aria-hidden
            className="flex size-11 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted shadow-[inset_0_1px_0_var(--pf-highlight)] [&_svg]:size-5"
          >
            {icon}
          </div>
        )}
        <div className="min-w-0 flex-1">
          {eyebrow && <div className="micro-label mb-1">{eyebrow}</div>}
          <h1 className="text-h2 font-semibold tracking-[-0.02em] text-fg">{title}</h1>
          {description && <p className="mt-1 max-w-3xl text-ui leading-relaxed text-fg-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 items-center gap-2 pt-1">{actions}</div>}
      </div>
      {children}
    </header>
  )
}
