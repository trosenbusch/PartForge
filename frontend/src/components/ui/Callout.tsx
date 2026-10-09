import { CircleAlert, CircleCheck, Info, Sparkles, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type CalloutTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'spark'

const toneClass: Record<CalloutTone, { box: string; icon: string }> = {
  neutral: { box: 'border-line bg-surface-2/60', icon: 'text-fg-muted' },
  info: { box: 'border-info/25 bg-info/8', icon: 'text-info-text' },
  success: { box: 'border-success/25 bg-success/8', icon: 'text-success-text' },
  warning: { box: 'border-warning/30 bg-warning/8', icon: 'text-warning-text' },
  danger: { box: 'border-danger/30 bg-danger/8', icon: 'text-danger-text' },
  spark: {
    box: 'border-spark-b/25 bg-[linear-gradient(135deg,color-mix(in_oklab,var(--pf-spark-a)_7%,transparent),color-mix(in_oklab,var(--pf-spark-b)_9%,transparent))]',
    icon: 'text-spark-text',
  },
}

const defaultIcon: Record<CalloutTone, ReactNode> = {
  neutral: <Info />,
  info: <Info />,
  success: <CircleCheck />,
  warning: <TriangleAlert />,
  danger: <CircleAlert />,
  spark: <Sparkles />,
}

export interface CalloutProps {
  tone?: CalloutTone
  title?: ReactNode
  children?: ReactNode
  /** Eigenes Icon; `false` = keins */
  icon?: ReactNode | false
  /** Aktionen rechts (z. B. „Beheben“) */
  actions?: ReactNode
  /** Als Statusmeldung ansagen (role="status"); Fehler mit `role="alert"` über `urgent` */
  live?: boolean
  urgent?: boolean
  className?: string
}

/** Hinweisbox im Inhalt (Info, Warnung, Fehler, Erfolg, KI-Hinweis) – für Toasts stattdessen `sonner`. */
export function Callout({
  tone = 'neutral',
  title,
  children,
  icon,
  actions,
  live,
  urgent,
  className,
}: CalloutProps) {
  const t = toneClass[tone]
  return (
    <div
      role={urgent ? 'alert' : live ? 'status' : undefined}
      className={cn('flex items-start gap-3 rounded-card border px-3.5 py-3 text-ui', t.box, className)}
    >
      {icon !== false && (
        <span aria-hidden className={cn('mt-0.5 flex shrink-0 [&_svg]:size-4', t.icon)}>
          {icon ?? defaultIcon[tone]}
        </span>
      )}
      <div className="min-w-0 flex-1">
        {title && <div className="font-medium text-fg">{title}</div>}
        {children && <div className={cn('text-xs leading-relaxed text-fg-muted', title && 'mt-0.5')}>{children}</div>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2 self-center">{actions}</div>}
    </div>
  )
}
