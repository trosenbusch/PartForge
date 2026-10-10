import { useI18n } from '@/lib/i18n'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Illustration, type IllustrationName } from './illustrations'

export interface EmptyStateProps {
  /** Linien-Illustration (Standard: keine) */
  illustration?: IllustrationName
  /** Alternativ ein Icon in einer Kachel */
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  /** Nächste Aktion(en) */
  actions?: ReactNode
  size?: 'sm' | 'md' | 'lg'
  /** Überschriftenebene des Titels (Standard h3 – in Karten unter einer h2) */
  titleAs?: 'h1' | 'h2' | 'h3' | 'h4'
  className?: string
  children?: ReactNode
}

/** Leerer Zustand: Illustration + klare nächste Aktion. */
export function EmptyState({
  illustration,
  icon,
  title,
  description,
  actions,
  size = 'md',
  titleAs: Title = 'h3',
  className,
  children,
}: EmptyStateProps) {
  useI18n()
  const illoSize = size === 'sm' ? 'w-32' : size === 'md' ? 'w-44' : 'w-56'
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        size === 'sm' ? 'gap-3 px-4 py-6' : size === 'md' ? 'gap-4 px-6 py-10' : 'gap-5 px-8 py-14',
        className,
      )}
    >
      {(illustration || icon) && (
        <div className="relative flex items-center justify-center">
          <div aria-hidden className="dot-grid mask-radial absolute -inset-10 opacity-80" />
          {illustration ? (
            <Illustration name={illustration} className={cn('relative h-auto', illoSize)} />
          ) : (
            <div className="relative flex size-14 items-center justify-center rounded-card border border-line-strong bg-surface-2 text-fg-muted shadow-card [&_svg]:size-6">
              {icon}
            </div>
          )}
        </div>
      )}
      <div className="relative flex max-w-md flex-col gap-1.5">
        <Title className={cn('font-semibold tracking-[-0.01em] text-fg', size === 'lg' ? 'text-h3' : 'text-md')}>
          {title}
        </Title>
        {description && <p className="text-ui leading-relaxed text-fg-muted">{description}</p>}
      </div>
      {children}
      {actions && <div className="relative flex flex-wrap items-center justify-center gap-2 pt-1">{actions}</div>}
    </div>
  )
}
