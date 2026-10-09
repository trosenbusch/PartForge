import { Check, CircleAlert, Info, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import type { ExtractionIssue } from '@/api/datasheets'
import { Badge } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { TipButton } from '../../shared/TipButton'
import type { DataSection } from '../../store'
import { severityCounts } from '../issues'

export interface SectionProps {
  id: DataSection
  title: string
  icon: ReactNode
  count?: number | string
  /** Prüfergebnis dieses Abschnitts (Konfidenz-Abzeichen); `undefined` = kein Abzeichen */
  issues?: readonly ExtractionIssue[]
  /** Fundstellen, Aktionen rechts im Kopf */
  aside?: ReactNode
  children: ReactNode
  className?: string
}

/** Abschnitt im Datenbereich: klebender Kopf mit Titel, Zähler, Konfidenz und Fundstellen. */
export function Section({ id, title, icon, count, issues, aside, children, className }: SectionProps) {
  return (
    <section id={`sec-${id}`} data-section={id} aria-labelledby={`sec-${id}-title`} className={cn('border-b border-line', className)}>
      <header className="sticky top-0 z-[2] flex min-h-11 items-center gap-2 bg-bg px-4 py-2">
        <span aria-hidden className="flex size-6 shrink-0 items-center justify-center rounded-md bg-surface-2 text-fg-muted [&_svg]:size-3.5">
          {icon}
        </span>
        <h2 id={`sec-${id}-title`} className="text-ui font-semibold tracking-[-0.01em] text-fg">
          {title}
        </h2>
        {count !== undefined && (
          <span className="whitespace-nowrap rounded-full bg-surface-3 px-1.5 text-2xs tabular-nums leading-4 text-fg-muted">
            {typeof count === 'number' ? formatNumber(count) : count}
          </span>
        )}
        {issues && <ConfidenceBadge issues={issues} />}
        <div className="ml-auto flex min-w-0 items-center gap-1.5">{aside}</div>
      </header>
      <div className="px-4 pb-5 pt-1">{children}</div>
    </section>
  )
}

/** „Plausibel“ bzw. Zahl der Fehler/Warnungen/Hinweise der automatischen Prüfung – Tooltip mit den Meldungen. */
export function ConfidenceBadge({ issues, className }: { issues: readonly ExtractionIssue[]; className?: string }) {
  const c = severityCounts(issues)
  const badge =
    c.error > 0 ? (
      <Badge variant="danger" className={className}>
        <CircleAlert />
        {formatNumber(c.error)} {c.error === 1 ? 'Fehler' : 'Fehler'}
      </Badge>
    ) : c.warning > 0 ? (
      <Badge variant="warning" className={className}>
        <TriangleAlert />
        {formatNumber(c.warning)} {c.warning === 1 ? 'Warnung' : 'Warnungen'}
      </Badge>
    ) : c.info > 0 ? (
      <Badge variant="info" className={className}>
        <Info />
        {formatNumber(c.info)} {c.info === 1 ? 'Hinweis' : 'Hinweise'}
      </Badge>
    ) : (
      <Badge variant="success" className={className}>
        <Check />
        Plausibel
      </Badge>
    )
  const content = issues.length ? (
    <ul className="flex max-w-80 flex-col gap-1">
      {issues.slice(0, 6).map((i, k) => (
        <li key={k} className="leading-snug">
          {i.message}
        </li>
      ))}
    </ul>
  ) : (
    'Die automatische Prüfung hat hier nichts beanstandet.'
  )
  return <TipButton tip={content}>{badge}</TipButton>
}

/** Kleine Feldbeschriftung im Raster (Label oben, Inhalt darunter) */
export function FieldLabel({ children, htmlFor, hint }: { children: ReactNode; htmlFor?: string; hint?: ReactNode }) {
  return (
    <div className="mb-1 flex items-baseline gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-fg-muted">
        {children}
      </label>
      {hint && <span className="text-2xs text-fg-subtle">{hint}</span>}
    </div>
  )
}
