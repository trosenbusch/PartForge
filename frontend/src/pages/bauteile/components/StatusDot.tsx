/** Status mit Farbpunkt außerhalb der Tabelle (Freigabe, Lebenszyklus) – gleiche Töne wie die Tabellenzellen. */
import { statusTone, type StatusTone } from '@/components/grid/cellFormat'
import { cn } from '@/lib/cn'
import { STATUS_DOT, STATUS_TEXT } from '../model/status'

export function StatusDot({
  value,
  tones,
  label,
  className,
}: {
  value: string
  tones?: Record<string, StatusTone>
  /** Vorangestellte Beschriftung, z. B. „Freigabe“ (nur für Screenreader sichtbar) */
  label?: string
  className?: string
}) {
  const tone = statusTone(value, tones)
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs font-medium', STATUS_TEXT[tone], className)}>
      <span aria-hidden className={cn('size-1.5 rounded-full', STATUS_DOT[tone])} />
      {label && <span className="sr-only">{label}: </span>}
      {value}
    </span>
  )
}
