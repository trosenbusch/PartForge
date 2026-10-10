import { useI18n } from '@/lib/i18n'
import { useId } from 'react'
import { cn } from '@/lib/cn'
import { FORGE_STOPS, SPARK_STOPS } from './gradientStops'

export interface SpinnerProps {
  size?: number
  /** current = Textfarbe, accent = Kupfer-Verlauf, spark = KI-Verlauf */
  tone?: 'current' | 'accent' | 'spark'
  className?: string
  /**
   * Nur angeben, wenn der Spinner allein für den Ladezustand steht – dann wird er als `role="status"` angesagt.
   * Ohne `label` ist er dekorativ (z. B. in Buttons mit aria-busy).
   */
  label?: string
}

export function Spinner({ size = 16, tone = 'current', className, label }: SpinnerProps) {
  useI18n()
  const id = useId()
  const gradientId = `sp${id.replace(/:/g, '')}`
  const stroke = tone === 'current' ? 'currentColor' : `url(#${gradientId})`
  return (
    <svg
      role={label ? 'status' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={cn('animate-spin [animation-duration:0.8s]', className)}
    >
      {tone !== 'current' && (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
            {/* Farben aus den Tokens --pf-forge-1…3 bzw. --pf-spark-1…3 (wie die CSS-Verläufe) */}
            {(tone === 'accent' ? FORGE_STOPS : SPARK_STOPS).map(([offset, color]) => (
              <stop key={offset} offset={offset} style={{ stopColor: color }} />
            ))}
          </linearGradient>
        </defs>
      )}
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.16" strokeWidth="2.5" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke={stroke} strokeWidth="2.5" strokeLinecap="round" />
    </svg>
  )
}
