/** Farben der Statuspunkte (Freigabe, Lebenszyklus, Bibliotheksstatus) – gleiche Töne wie die Tabellenzellen. */
import type { StatusTone } from '@/components/grid/cellFormat'

export const STATUS_DOT: Record<StatusTone, string> = {
  success: 'bg-success shadow-[0_0_6px_var(--pf-success)]',
  warning: 'bg-warning',
  danger: 'bg-danger shadow-[0_0_6px_var(--pf-danger)]',
  info: 'bg-info',
  neutral: 'bg-fg-subtle',
  spark: 'bg-gradient-spark',
}

export const STATUS_TEXT: Record<StatusTone, string> = {
  success: 'text-success-text',
  warning: 'text-warning-text',
  danger: 'text-danger-text',
  info: 'text-info-text',
  neutral: 'text-fg-muted',
  spark: 'text-spark-text',
}
