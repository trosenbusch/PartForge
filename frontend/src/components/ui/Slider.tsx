import { Slider as SliderPrimitive } from 'radix-ui'
import type { KeyboardEvent } from 'react'
import { cn } from '@/lib/cn'
import { formatNumber, plainNumber } from '@/lib/format'

export interface SliderMark {
  value: number
  label?: string
}

export interface SliderProps {
  /** Ein Wert = einfacher Slider, zwei Werte = Bereich (Doppel-Slider) */
  value: number[]
  onValueChange?: (value: number[]) => void
  /** Nach dem Loslassen bzw. nach einer Tastatureingabe */
  onValueCommit?: (value: number[]) => void
  min: number
  max: number
  /** Schrittweite (linear) */
  step?: number
  /** Logarithmische Skala, z. B. für Widerstandswerte 1 Ω … 10 MΩ (min > 0) */
  scale?: 'linear' | 'log'
  /** Wert einrasten, z. B. auf die nächste E-Reihen-Stufe (Pfeiltasten springen dann von Stufe zu Stufe) */
  snap?: (value: number) => number
  formatValue?: (value: number) => string
  /** Wertanzeige über dem Regler */
  showValue?: 'auto' | 'always' | 'never'
  /** Skalenmarken unter der Spur */
  marks?: (number | SliderMark)[]
  minStepsBetweenThumbs?: number
  disabled?: boolean
  /** Barrierefreie Namen je Regler, z. B. ['Minimum', 'Maximum'] */
  thumbLabels?: string[]
  tone?: 'accent' | 'spark'
  className?: string
  'aria-label'?: string
}

const RESOLUTION = 1000

export function Slider({
  value,
  onValueChange,
  onValueCommit,
  min,
  max,
  step = 1,
  scale = 'linear',
  snap,
  formatValue = (v) => formatNumber(v),
  showValue = 'auto',
  marks,
  minStepsBetweenThumbs = 0,
  disabled,
  thumbLabels,
  tone = 'accent',
  className,
  'aria-label': ariaLabel,
}: SliderProps) {
  const isLog = scale === 'log'
  const safeMin = isLog ? Math.max(min, Number.MIN_VALUE) : min
  const lmin = Math.log(safeMin)
  const lmax = Math.log(Math.max(max, safeMin * 1.0001))
  const posMin = isLog ? 0 : min
  const posMax = isLog ? RESOLUTION : max

  const toPos = (v: number) => {
    if (!isLog) return v
    const clamped = Math.min(Math.max(v, safeMin), max)
    return ((Math.log(clamped) - lmin) / (lmax - lmin)) * RESOLUTION
  }
  const fromPos = (p: number) => {
    const raw = isLog ? Math.exp(lmin + (p / RESOLUTION) * (lmax - lmin)) : p
    return snap ? snap(raw) : raw
  }
  const pct = (v: number) => {
    const p = toPos(v)
    return isLog ? (p / RESOLUTION) * 100 : ((p - min) / (max - min || 1)) * 100
  }

  /**
   * Tastatur: Bei Log-Skala oder Einrasten würde Radix in internen Positionsschritten (1/1000) laufen und
   * immer wieder auf denselben Wert zurückschnappen. Deshalb hier selbst: ←/→/↑/↓ = nächster Wert,
   * Bild↑/↓ = ein Zehntel des Bereichs, Pos1/Ende = Grenzen.
   */
  const handleKeyDown = (e: KeyboardEvent<HTMLSpanElement>) => {
    if (!isLog && !snap) return // linear ohne Einrasten: Radix-Standard genügt
    const thumb = (e.target as HTMLElement).closest<HTMLElement>('[data-thumb-index]')
    if (!thumb) return
    const index = Number(thumb.dataset.thumbIndex)
    const current = value[index]
    if (current === undefined) return
    const key = e.key
    const dir = key === 'ArrowRight' || key === 'ArrowUp' || key === 'PageUp' ? 1 : key === 'ArrowLeft' || key === 'ArrowDown' || key === 'PageDown' ? -1 : 0
    let next: number | null = null
    if (key === 'Home') next = fromPos(posMin)
    else if (key === 'End') next = fromPos(posMax)
    else if (dir !== 0) {
      const big = key === 'PageUp' || key === 'PageDown' || e.shiftKey
      const unit = isLog ? 1 : step
      const jump = big ? (posMax - posMin) / 10 : unit
      let p = toPos(current)
      next = current
      // so lange weiterlaufen, bis sich der (eingerastete) Wert wirklich ändert
      for (let i = 0; i < RESOLUTION * 2 && next === current; i++) {
        p = Math.min(posMax, Math.max(posMin, p + dir * jump))
        next = fromPos(p)
        if (p === posMin || p === posMax) break
      }
    }
    if (next === null) return
    e.preventDefault()
    // Bereichsregler dürfen sich nicht überholen
    const lower = index > 0 ? value[index - 1] : -Infinity
    const upper = index < value.length - 1 ? value[index + 1] : Infinity
    const clamped = Math.min(Math.max(next, lower), upper)
    if (clamped === current) return
    const updated = value.map((v, i) => (i === index ? clamped : v))
    onValueChange?.(updated)
    onValueCommit?.(updated)
  }

  const normalizedMarks = (marks ?? []).map((m) => (typeof m === 'number' ? { value: m, label: formatValue(m) } : m))
  const domainMin = isLog ? safeMin : min

  return (
    <div className={cn('relative w-full select-none', normalizedMarks.length > 0 && 'pb-6', showValue === 'always' && 'pt-7', className)}>
      <SliderPrimitive.Root
        value={value.map(toPos)}
        min={posMin}
        max={posMax}
        step={isLog ? 1 : step}
        minStepsBetweenThumbs={minStepsBetweenThumbs}
        disabled={disabled}
        aria-label={ariaLabel}
        onKeyDown={handleKeyDown}
        onValueChange={(positions) => onValueChange?.(positions.map(fromPos))}
        onValueCommit={(positions) => onValueCommit?.(positions.map(fromPos))}
        className="relative flex h-5 w-full touch-none items-center data-[disabled]:opacity-50"
      >
        <SliderPrimitive.Track className="relative h-1.5 w-full grow overflow-hidden rounded-full bg-surface-3 shadow-[inset_0_1px_2px_rgba(0,0,0,.25)]">
          <SliderPrimitive.Range
            className={cn(
              'absolute h-full rounded-full',
              tone === 'accent'
                ? 'bg-gradient-forge shadow-[0_0_12px_var(--pf-ember-strong)]'
                : 'bg-gradient-spark shadow-[var(--pf-glow-control-spark)]',
            )}
          />
        </SliderPrimitive.Track>
        {value.map((v, i) => (
          <SliderPrimitive.Thumb
            key={i}
            data-thumb-index={i}
            aria-label={thumbLabels?.[i] ?? ariaLabel}
            // echte Werte statt interner Positionen (Props überschreiben die von Radix), als Dezimalzahl ohne Exponent
            {...({
              'aria-valuemin': plainNumber(domainMin),
              'aria-valuemax': plainNumber(max),
              'aria-valuenow': plainNumber(v),
            } as Record<string, string>)}
            aria-valuetext={formatValue(v)}
            className={cn(
              'group/thumb relative block size-[18px] rounded-full border-2 bg-white outline-none',
              'shadow-[0_2px_6px_rgba(0,0,0,.35)] transition-[box-shadow,transform] duration-150',
              'hover:scale-110 focus-ring active:scale-105',
              tone === 'accent' ? 'border-accent' : 'border-spark-b',
              disabled ? 'cursor-not-allowed' : 'cursor-grab active:cursor-grabbing',
            )}
          >
            {showValue !== 'never' && (
              <span
                aria-hidden
                className={cn(
                  'pointer-events-none absolute bottom-[calc(100%+8px)] left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md',
                  'border border-line-strong bg-surface-3 px-1.5 py-0.5 text-2xs font-medium text-fg shadow-pop mono',
                  'transition-[opacity,transform] duration-150',
                  showValue === 'always'
                    ? 'opacity-100'
                    : 'translate-y-1 opacity-0 group-hover/thumb:translate-y-0 group-hover/thumb:opacity-100 group-focus-visible/thumb:translate-y-0 group-focus-visible/thumb:opacity-100 group-active/thumb:opacity-100',
                )}
              >
                {formatValue(v)}
              </span>
            )}
          </SliderPrimitive.Thumb>
        ))}
      </SliderPrimitive.Root>
      {normalizedMarks.length > 0 && (
        <div aria-hidden className="pointer-events-none absolute inset-x-[9px] top-[calc(100%-1.25rem)] h-5">
          {normalizedMarks.map((m) => (
            <span
              key={m.value}
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-0.5"
              style={{ left: `${pct(m.value)}%` }}
            >
              <span className="h-1 w-px bg-line-strong" />
              <span className="mono whitespace-nowrap text-2xs leading-none text-fg-subtle">{m.label}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
