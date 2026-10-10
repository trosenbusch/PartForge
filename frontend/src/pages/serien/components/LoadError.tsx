import { useI18n } from '@/lib/i18n'
/**
 * Ladefehler im Assistenten (Vorlagen, Vorlagendetails): deutscher Text des Backends, „Erneut versuchen“ und
 * optional weitere Aktionen (z. B. „Andere Serie wählen“). Nie ein leerer Zustand, der wie „keine Daten“ aussieht.
 */
import { CircleAlert, RefreshCw, WifiOff } from 'lucide-react'
import type { ReactNode } from 'react'
import { ApiError, errorMessage } from '@/api/client'
import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'

export interface LoadErrorProps {
  title: string
  error: unknown
  /** eigener Text statt der Fehlermeldung (z. B. bei 404) */
  description?: ReactNode
  onRetry?: () => void
  retrying?: boolean
  actions?: ReactNode
  className?: string
}

export function LoadError({ title, error, description, onRetry, retrying, actions, className }: LoadErrorProps) {
  const { t: tr } = useI18n()
  const offline = error instanceof ApiError && error.status === 0
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center gap-3 rounded-panel border border-dashed border-danger/35 bg-danger/5 px-6 py-10 text-center',
        className,
      )}
    >
      <span
        aria-hidden
        className="flex size-10 items-center justify-center rounded-full border border-danger/30 bg-danger/10 text-danger-text [&_svg]:size-5"
      >
        {offline ? <WifiOff /> : <CircleAlert />}
      </span>
      <div className="flex max-w-xl flex-col gap-1">
        <h3 className="text-md font-semibold text-fg">{title}</h3>
        <p className="text-ui leading-relaxed text-fg-muted">{description ?? errorMessage(error)}</p>
      </div>
      {(onRetry || actions) && (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-2">
          {onRetry && (
            <Button variant="secondary" leftIcon={<RefreshCw />} loading={retrying} onClick={onRetry}>
              {tr("Erneut versuchen")}</Button>
          )}
          {actions}
        </div>
      )}
    </div>
  )
}
