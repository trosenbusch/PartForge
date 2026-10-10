import { useI18n } from '@/lib/i18n'
import { ArrowDownRight, ArrowRight, ArrowUpRight, Minus } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { useCountUp } from '@/lib/useCountUp'
import { Skeleton } from './Skeleton'
import { Sparkline } from './Sparkline'

/**
 * Farbe nur für **Status** – reine Zählwerte bleiben neutral.
 * neutral (Standard) · success · warning · danger · accent (Hervorhebung) · spark (KI-Kennzahl)
 */
export type StatTone = 'neutral' | 'success' | 'warning' | 'danger' | 'accent' | 'spark' | 'info'

const toneColor: Record<StatTone, string> = {
  neutral: 'var(--pf-fg-subtle)',
  accent: 'var(--pf-accent)',
  info: 'var(--pf-info)',
  success: 'var(--pf-success)',
  warning: 'var(--pf-warning)',
  danger: 'var(--pf-danger)',
  spark: 'var(--pf-spark-b)',
}

const toneIcon: Record<StatTone, string> = {
  neutral: 'border-line bg-surface-2 text-fg-muted',
  accent: 'border-accent/25 bg-accent-soft text-accent-text',
  info: 'border-info/25 bg-info/10 text-info-text',
  success: 'border-success/25 bg-success/10 text-success-text',
  warning: 'border-warning/30 bg-warning/10 text-warning-text',
  danger: 'border-danger/30 bg-danger/10 text-danger-text',
  spark: 'border-spark-b/30 bg-[color-mix(in_oklab,var(--pf-spark-b)_12%,transparent)] text-spark-text',
}

/** Hinweiszeile: bei Status-Tönen farbig (bleibt sichtbar, auch wenn die Icon-Kachel in schmalen Karten entfällt) */
const toneHint: Record<StatTone, string> = {
  neutral: 'text-fg-subtle',
  accent: 'text-fg-subtle',
  info: 'text-fg-subtle',
  spark: 'text-fg-subtle',
  success: 'text-success-text',
  warning: 'text-warning-text',
  danger: 'text-danger-text',
}

export function CountUp({ value, format = (n) => formatNumber(Math.round(n)) }: { value: number; format?: (n: number) => string }) {
  useI18n()
  const display = useCountUp(value)
  return <>{format(display)}</>
}

export interface StatDelta {
  value: number
  /** z. B. „seit letzter Woche“ */
  label?: string
  /** Ist ein Anstieg gut? (Standard: ja) */
  upIsGood?: boolean
  format?: (n: number) => string
}

export interface StatCardProps {
  label: string
  /** null = „–“ (unbekannt / nicht geprüft), undefined = lädt */
  value: number | null | undefined
  icon?: ReactNode
  tone?: StatTone
  delta?: StatDelta
  /** Verlauf – wird nur gezeigt, wenn es echte Historie gibt (≥ 2 Punkte mit Veränderung) */
  sparkline?: number[]
  format?: (n: number) => string
  /** Zusatzzeile unter dem Wert */
  hint?: ReactNode
  loading?: boolean
  onClick?: () => void
  /** Barrierefreie Beschreibung des Klickziels, z. B. „Zur Bauteiltabelle“ */
  actionLabel?: string
  className?: string
}

export function StatCard({
  label,
  value,
  icon,
  tone = 'neutral',
  delta,
  sparkline,
  format,
  hint,
  loading,
  onClick,
  actionLabel,
  className,
}: StatCardProps) {
  useI18n()
  const interactive = Boolean(onClick)
  const Comp = interactive ? 'button' : 'div'
  const hasHistory = Boolean(sparkline && sparkline.length > 1 && Math.max(...sparkline) !== Math.min(...sparkline))

  let deltaEl: ReactNode = null
  if (delta) {
    const up = delta.value > 0
    const down = delta.value < 0
    const good = delta.upIsGood ?? true
    const positive = (up && good) || (down && !good)
    const negative = (down && good) || (up && !good)
    const Icon = up ? ArrowUpRight : down ? ArrowDownRight : Minus
    deltaEl = (
      <span
        className={cn(
          'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-2xs font-medium tabular-nums',
          positive && 'bg-success/10 text-success-text',
          negative && 'bg-danger/10 text-danger-text',
          !positive && !negative && 'bg-surface-3 text-fg-subtle',
        )}
      >
        <Icon aria-hidden className="size-3" />
        {delta.format ? delta.format(delta.value) : `${up ? '+' : ''}${formatNumber(delta.value)}`}
        {delta.label && <span className="ml-1 font-normal text-fg-subtle">{delta.label}</span>}
      </span>
    )
  }

  return (
    <Comp
      type={interactive ? 'button' : undefined}
      onClick={onClick}
      // Name aus dem sichtbaren Inhalt („Bauteile: 7.093 – zuletzt vor 2 Min. – Zur Bauteiltabelle“): Sprachsteuerung trifft
      // die Beschriftung, Zahlen sind deutsch formatiert; Trennzeichen und Klickziel nur für Screenreader
      className={cn(
        'group/stat @container relative flex min-w-0 flex-col rounded-card border border-line bg-surface text-left shadow-card',
        interactive &&
          'outline-none transition-[transform,border-color,box-shadow] duration-200 hover:-translate-y-px hover:border-line-strong hover:shadow-raised focus-ring',
        className,
      )}
    >
      <div className="flex flex-1 flex-col px-4 pb-3.5 pt-3.5">
        <div className="flex items-center justify-between gap-2">
          <span className="truncate text-xs font-medium text-fg-muted">
            {label}
            <span className="sr-only">: </span>
          </span>
          {icon && (
            <span
              aria-hidden
              className={cn(
                'hidden size-7 shrink-0 items-center justify-center rounded-control border @[10rem]:flex [&_svg]:size-3.5',
                toneIcon[tone],
              )}
            >
              {icon}
            </span>
          )}
        </div>
        {loading || value === undefined ? (
          <Skeleton className="mt-2 h-8 w-16" />
        ) : (
          <div
            className={cn(
              'mono mt-1.5 text-metric font-semibold tracking-[-0.04em]',
              value === null ? 'text-fg-subtle' : 'text-fg',
            )}
          >
            {value === null ? '–' : <CountUp value={value} format={format} />}
          </div>
        )}
        <div className={cn('mt-1 flex min-h-4 items-center gap-1.5 text-xs', toneHint[tone])}>
          {(deltaEl || hint) && <span className="sr-only"> – </span>}
          {deltaEl}
          {hint && <span className="min-w-0 truncate">{hint}</span>}
          {interactive && actionLabel && <span className="sr-only"> – {actionLabel}</span>}
        </div>
        {interactive && (
          <ArrowRight
            aria-hidden
            className="absolute bottom-3.5 right-3.5 size-3.5 -translate-x-1 text-fg-subtle opacity-0 transition-all group-hover/stat:translate-x-0 group-hover/stat:opacity-100 group-focus-visible/stat:translate-x-0 group-focus-visible/stat:opacity-100"
          />
        )}
      </div>
      {hasHistory && sparkline && (
        <div className="relative -mt-1 h-8 w-full overflow-hidden rounded-b-card">
          <Sparkline data={sparkline} color={toneColor[tone === 'neutral' ? 'accent' : tone]} fluid height={32} />
        </div>
      )}
    </Comp>
  )
}
