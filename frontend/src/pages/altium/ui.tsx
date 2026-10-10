import { useI18n } from '@/lib/i18n'
import { CircleAlert, CircleCheck, ExternalLink, Info, TriangleAlert } from 'lucide-react'
import type { IssueSeverity } from '@/api/altium'
import { Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { Headline, Level } from './model'
import { formatNumber } from '@/lib/format'
import { LEVEL_DOT, SEVERITY_TEXT } from './tokens'

/** Verweis einer Schlagzeile nach außen (z. B. Download des ODBC-Treibers) – öffnet im Browser */
export function HeadlineLink({ link, className }: { link: NonNullable<Headline['link']>; className?: string }) {
  const { t: tr } = useI18n()
  return (
    <a
      href={link.href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        'inline-flex items-center gap-1 rounded-sm text-xs font-medium text-accent-text underline-offset-2 outline-none hover:underline focus-ring',
        className,
      )}
    >
      {link.label}
      <ExternalLink aria-hidden className="size-3" />
      <span className="sr-only"> {tr(" (öffnet im Browser)")}</span>
    </a>
  )
}

/** Statuspunkt (dekorativ – der Zustand steht immer auch als Text daneben) */
export function LevelDot({ level, className }: { level: Level; className?: string }) {
  useI18n()
  if (level === 'busy') return <Spinner size={10} tone="accent" className={cn('shrink-0', className)} />
  return <span aria-hidden className={cn('inline-block size-2 shrink-0 rounded-full', LEVEL_DOT[level], className)} />
}

const SEVERITY_ICON = { error: CircleAlert, warning: TriangleAlert, info: Info } as const

export function SeverityIcon({ severity, className }: { severity: IssueSeverity; className?: string }) {
  useI18n()
  const Icon = SEVERITY_ICON[severity]
  return <Icon aria-hidden className={cn('size-4 shrink-0', SEVERITY_TEXT[severity], className)} />
}

export function OkIcon({ className }: { className?: string }) {
  useI18n()
  return <CircleCheck aria-hidden className={cn('size-4 shrink-0 text-success-text', className)} />
}

/** Beschriftung eines Filtersegments mit Zähler (Fehler rot, Warnungen gelb, sonst neutral) */
export function FilterLabel({ label, count, tone }: { label: string; count?: number; tone?: IssueSeverity | 'ok' }) {
  useI18n()
  return (
    <span className="flex items-center gap-1.5">
      {label}
      {count !== undefined && (
        <span
          className={cn(
            'mono rounded-full px-1.5 text-2xs leading-4',
            count > 0 && tone === 'error'
              ? 'bg-danger/12 text-danger-text'
              : count > 0 && tone === 'warning'
                ? 'bg-warning/12 text-warning-text'
                : 'bg-surface-3 text-fg-subtle',
          )}
        >
          {formatNumber(count)}
        </span>
      )}
    </span>
  )
}
