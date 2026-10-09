/**
 * Wertebereich: logarithmischer Doppel-Slider (rastet auf lieferbare Werte ein) mit Werteskala darüber – jeder
 * Strich ein lieferbarer Wert, im Bereich hervorgehoben – und Eingabefeldern für Unter-/Obergrenze, die
 * technische Schreibweise verstehen („4k7“, „1M“, „100n“). Der Regler rechnet in einer Untereinheit (pF, nH …), damit
 * seine ARIA-Werte gültige Dezimalzahlen bleiben („10“ statt „1e-11“).
 */
import { useMemo, useState } from 'react'
import { Input, Slider } from '@/components/ui'
import { cn } from '@/lib/cn'
import { parseEngineering } from '@/lib/units'
import { compactValue, displayValue } from '../../model/values'

export interface RangeControlProps {
  domain: [number, number]
  /** null = Grenze der Serie */
  value: [number | null, number | null]
  onValueChange: (value: [number | null, number | null]) => void
  /** lieferbare Werte im ganzen Bereich (Skala und Einrasten) */
  candidates: number[]
  unit: string
  idPrefix: string
  disabled?: boolean
}

const REL = 1e-9

/** nächster Wert einer sortierten Liste (logarithmischer Abstand) */
function nearest(sorted: number[], v: number): number {
  if (!sorted.length) return v
  let lo = 0
  let hi = sorted.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (sorted[mid] < v) lo = mid + 1
    else hi = mid
  }
  const a = sorted[Math.max(0, lo - 1)]
  const b = sorted[lo]
  return Math.abs(Math.log(v / a)) <= Math.abs(Math.log(b / v)) ? a : b
}

/** Faktor in eine Untereinheit, in der der kleinste Wert ≥ 1 ist (F → pF, H → nH; Ω bleibt) */
function sliderScale(lo: number): number {
  if (!(lo > 0) || lo >= 1e-3) return 1
  return 10 ** Math.ceil(-Math.log10(lo) - REL)
}

function decadeMarks(lo: number, hi: number): number[] {
  const out: number[] = []
  for (let e = Math.ceil(Math.log10(lo) - REL); e <= Math.floor(Math.log10(hi) + REL); e++) out.push(10 ** e)
  if (out.length > 9) return out.filter((_, i) => i % 2 === 0)
  return out
}

function BoundInput({
  id,
  label,
  value,
  fallback,
  unit,
  onCommit,
  disabled,
}: {
  id: string
  label: string
  value: number | null
  fallback: number
  unit: string
  /** übernimmt den Wert – oder liefert den Grund, warum nicht (deutsch, kurz) */
  onCommit: (v: number | null) => string | null
  disabled?: boolean
}) {
  const shown = value ?? fallback
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const display = compactValue(shown)
  const commit = () => {
    if (text === null) return
    const t = text.trim()
    if (!t) {
      setText(null)
      setError(null)
      onCommit(null)
      return
    }
    const parsed = parseEngineering(t)
    if (parsed === null || !(parsed > 0)) {
      setError('Kein gültiger Wert – z. B. 4k7, 1M')
      return
    }
    const problem = onCommit(parsed)
    setError(problem)
    if (!problem) setText(null)
  }
  return (
    <div className="flex w-[7.5rem] shrink-0 flex-col gap-1">
      <label htmlFor={id} className="text-2xs font-medium text-fg-muted">
        {label}
      </label>
      <Input
        id={id}
        size="sm"
        mono
        value={text ?? display}
        invalid={Boolean(error)}
        disabled={disabled}
        onChange={(e) => {
          setText(e.target.value)
          setError(null)
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault()
            commit()
          } else if (e.key === 'Escape' && text !== null) {
            e.preventDefault()
            setText(null)
            setError(null)
          }
        }}
        suffix={<span className="text-2xs">{unit}</span>}
        aria-describedby={error ? `${id}-error ${id}-hint` : `${id}-hint`}
        title={displayValue(shown, unit)}
      />
      <span id={`${id}-hint`} className="sr-only">
        Technische Schreibweise möglich, z. B. 4k7, 1M, 100n. Leer = Grenze der Serie.
      </span>
      {error && (
        <p id={`${id}-error`} role="alert" className="text-2xs leading-snug text-danger-text">
          {error}
        </p>
      )}
    </div>
  )
}

export function RangeControl({ domain, value, onValueChange, candidates, unit, idPrefix, disabled }: RangeControlProps) {
  const [dLo, dHi] = domain
  const lo = Math.min(Math.max(value[0] ?? dLo, dLo), dHi)
  const hi = Math.max(Math.min(value[1] ?? dHi, dHi), dLo)
  const single = dHi <= dLo * (1 + REL)
  const marks = useMemo(() => decadeMarks(dLo, dHi).map((v) => ({ value: v, label: compactValue(v) })), [dLo, dHi])

  // Werteskala: ein Strich je lieferbarem Wert (Pfad statt vieler Elemente)
  const { inside, outside } = useMemo(() => {
    if (single) return { inside: '', outside: '' }
    const span = Math.log(dHi) - Math.log(dLo)
    let a = ''
    let b = ''
    for (const v of candidates) {
      const x = ((Math.log(v) - Math.log(dLo)) / span) * 1000
      if (x < -0.5 || x > 1000.5) continue
      const seg = `M${x.toFixed(1)} 1V13`
      if (v >= lo * (1 - REL) && v <= hi * (1 + REL)) a += seg
      else b += seg
    }
    return { inside: a, outside: b }
  }, [candidates, dLo, dHi, lo, hi, single])

  const commitBound = (index: 0 | 1, v: number | null): string | null => {
    if (v === null) {
      onValueChange(index === 0 ? [null, value[1]] : [value[0], null])
      return null
    }
    if (v < dLo * (1 - REL) || v > dHi * (1 + REL)) {
      return `Nur ${displayValue(dLo, unit)} … ${displayValue(dHi, unit)}`
    }
    if (index === 0 && v > hi * (1 + REL)) return `Größer als „Bis“ (${displayValue(hi, unit)})`
    if (index === 1 && v < lo * (1 - REL)) return `Kleiner als „Von“ (${displayValue(lo, unit)})`
    const atEdge = index === 0 ? v <= dLo * (1 + REL) : v >= dHi * (1 - REL)
    onValueChange(index === 0 ? [atEdge ? null : v, value[1]] : [value[0], atEdge ? null : v])
    return null
  }

  // Regler in der Untereinheit (k): Werte, Grenzen, Einrasten, Marken und Anzeige umrechnen
  const k = sliderScale(dLo)
  const snap = candidates.length ? (v: number) => nearest(candidates, v / k) * k : undefined
  const scaledMarks = useMemo(() => marks.map((m) => ({ value: m.value * k, label: m.label })), [marks, k])
  // viele Werte (E96, E192): Striche dichter als Pixel – zurückhaltender zeichnen
  const dense = candidates.length > 250

  return (
    <div className="flex items-start gap-4">
      <BoundInput
        id={`${idPrefix}-min`}
        label="Von"
        value={value[0]}
        fallback={dLo}
        unit={unit}
        disabled={disabled}
        onCommit={(v) => commitBound(0, v)}
      />
      <div className={cn('min-w-0 flex-1 pt-1', single && 'opacity-60')}>
        <svg aria-hidden viewBox="0 0 1000 14" preserveAspectRatio="none" className="block h-3 w-[calc(100%-18px)] translate-x-[9px]">
          <path d={outside} className="stroke-line-strong" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={dense ? 0.55 : 0.8} />
          <path d={inside} className="stroke-fg-subtle" strokeWidth={1} vectorEffect="non-scaling-stroke" opacity={dense ? 0.6 : 1} />
        </svg>
        <Slider
          value={[lo * k, hi * k]}
          min={dLo * k}
          max={(single ? dLo * 1.0001 : dHi) * k}
          scale="log"
          snap={snap}
          disabled={disabled || single}
          marks={scaledMarks}
          formatValue={(v) => displayValue(v / k, unit)}
          thumbLabels={['Untergrenze', 'Obergrenze']}
          aria-label="Wertebereich"
          onValueChange={([sa, sb]) => {
            const a = sa / k
            const b = sb / k
            const nextLo = a <= dLo * (1 + REL) ? null : a
            const nextHi = b >= dHi * (1 - REL) ? null : b
            if (nextLo !== value[0] || nextHi !== value[1]) onValueChange([nextLo, nextHi])
          }}
          className="mt-1"
        />
      </div>
      <BoundInput
        id={`${idPrefix}-max`}
        label="Bis"
        value={value[1]}
        fallback={dHi}
        unit={unit}
        disabled={disabled}
        onCommit={(v) => commitBound(1, v)}
      />
    </div>
  )
}
