import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { formatPercent } from '@/lib/format'
import { FORGE_STOPS, SPARK_STOPS } from './gradientStops'

export type ProgressTone = 'accent' | 'spark' | 'success' | 'warning' | 'danger' | 'info' | 'neutral'

const solid: Record<Exclude<ProgressTone, 'accent' | 'spark'>, string> = {
  success: 'var(--pf-success)',
  warning: 'var(--pf-warning)',
  danger: 'var(--pf-danger)',
  info: 'var(--pf-info)',
  neutral: 'var(--pf-fg-subtle)',
}

function fillBackground(tone: ProgressTone): string {
  if (tone === 'accent') return 'var(--pf-gradient-forge)'
  if (tone === 'spark') return 'var(--pf-gradient-spark)'
  return solid[tone]
}

// --------------------------------------------------------------------------- ProgressBar

export interface ProgressBarProps {
  /** 0…max */
  value?: number
  max?: number
  tone?: ProgressTone
  size?: 'xs' | 'sm' | 'md'
  /** Unbestimmter Fortschritt (läuft hin und her; bei „Bewegung reduzieren“ ruhiges Schraffurband) */
  indeterminate?: boolean
  /** Beschriftung links über dem Balken – zugleich der barrierefreie Name */
  label?: ReactNode
  /** Beschriftung nur für Screenreader (z. B. im Startbildschirm) */
  hideLabel?: boolean
  /** Prozentwert rechts über dem Balken */
  showValue?: boolean
  /** Laufender Vorgang: Glanzstreifen auf dem Balken (für statische Anteile weglassen – spart GPU im Leerlauf) */
  live?: boolean
  className?: string
}

export function ProgressBar({
  value = 0,
  max = 1,
  tone = 'accent',
  size = 'sm',
  indeterminate,
  label,
  hideLabel,
  showValue,
  live,
  className,
}: ProgressBarProps) {
  const labelId = useId()
  const fraction = Math.min(1, Math.max(0, max > 0 ? value / max : 0))
  const height = size === 'xs' ? 'h-1' : size === 'sm' ? 'h-1.5' : 'h-2.5'
  const visibleHeader = (label && !hideLabel) || showValue
  return (
    <div className={cn('w-full', className)}>
      {visibleHeader && (
        <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
          <span id={labelId} className="truncate text-fg-muted">
            {label}
          </span>
          {showValue && !indeterminate && <span className="tabular-nums text-fg">{formatPercent(fraction)}</span>}
        </div>
      )}
      {label && hideLabel && (
        <span id={labelId} className="sr-only">
          {label}
        </span>
      )}
      <div
        role="progressbar"
        aria-labelledby={label ? labelId : undefined}
        aria-label={label ? undefined : 'Fortschritt'}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={indeterminate ? undefined : Math.round(fraction * 100)}
        aria-valuetext={indeterminate ? 'läuft' : undefined}
        className={cn('relative w-full overflow-hidden rounded-full bg-surface-3', height)}
      >
        {indeterminate ? (
          <>
            <div
              className="progress-indeterminate absolute inset-y-0 left-0 w-1/2 rounded-full motion-reduce:hidden"
              style={{ background: fillBackground(tone) }}
            />
            <div aria-hidden className="progress-hatched absolute inset-0 hidden rounded-full motion-reduce:block" />
          </>
        ) : (
          <div
            className="relative h-full overflow-hidden rounded-full transition-[width] duration-500 ease-[cubic-bezier(.16,1,.3,1)]"
            style={{ width: `${fraction * 100}%`, background: fillBackground(tone) }}
          >
            {live && fraction > 0 && fraction < 1 && (
              <span
                aria-hidden
                className="absolute inset-y-0 w-1/3 animate-[pf-sheen_1.8s_ease-in-out_infinite] bg-[linear-gradient(90deg,transparent,rgba(255,255,255,.45),transparent)] motion-reduce:hidden"
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- ProgressRing

export interface ProgressRingProps {
  /** 0…1 */
  value?: number
  size?: number
  stroke?: number
  tone?: ProgressTone
  indeterminate?: boolean
  /** Inhalt in der Mitte (z. B. Prozent oder Icon) */
  children?: ReactNode
  /** Prozentwert in der Mitte anzeigen */
  showValue?: boolean
  className?: string
  /** Barrierefreier Name (Standard „Fortschritt“) */
  label?: string
  /** Text statt Prozent für Screenreader, z. B. „nicht geprüft“ */
  valueText?: string
}

export function ProgressRing({
  value = 0,
  size = 36,
  stroke = 3,
  tone = 'accent',
  indeterminate,
  children,
  showValue,
  className,
  label = 'Fortschritt',
  valueText,
}: ProgressRingProps) {
  const id = useId().replace(/:/g, '')
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const fraction = Math.min(1, Math.max(0, value))
  const gradient = tone === 'accent' || tone === 'spark'
  const strokeColor = gradient ? `url(#pr-${id})` : solid[tone as keyof typeof solid]
  const dash = indeterminate ? c * 0.28 : c * fraction

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate || valueText ? undefined : Math.round(fraction * 100)}
      aria-valuetext={valueText ?? (indeterminate ? 'läuft' : undefined)}
      className={cn('relative inline-flex shrink-0 items-center justify-center', className)}
      style={{ width: size, height: size }}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        className={cn('-rotate-90', indeterminate && 'animate-spin [animation-duration:1.1s]')}
        aria-hidden
      >
        {gradient && (
          <defs>
            <linearGradient id={`pr-${id}`} x1="0" y1="0" x2="1" y2="1">
              {(tone === 'accent' ? FORGE_STOPS : SPARK_STOPS).map(([offset, color]) => (
                <stop key={offset} offset={offset} style={{ stopColor: color }} />
              ))}
            </linearGradient>
          </defs>
        )}
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--pf-surface-3)" strokeWidth={stroke} />
        {indeterminate && (
          // „Bewegung reduzieren“: gestrichelter Vollkreis statt eines stehenden Bogens (der wie Fortschritt aussähe)
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={strokeColor}
            strokeWidth={stroke}
            strokeDasharray={`${Math.max(1.5, stroke)} ${Math.max(3, stroke * 1.6)}`}
            className="hidden motion-reduce:block"
          />
        )}
        {dash > 0.5 && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={strokeColor}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${c}`}
            className={cn(
              'transition-[stroke-dasharray] duration-500 ease-[cubic-bezier(.16,1,.3,1)]',
              indeterminate && 'motion-reduce:hidden',
            )}
          />
        )}
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-2xs font-semibold tabular-nums text-fg">
        {children ?? (showValue && !indeterminate ? Math.round(fraction * 100) : null)}
      </span>
    </div>
  )
}
