import { useI18n } from '@/lib/i18n'
import { useState, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { formatInputNumber, parseDecimal } from '@/lib/format'
import { formatEngineering, parseEngineering } from '@/lib/units'
import { useFieldContext } from './fieldContext'
import { controlShell } from './variants'

export interface NumberInputProps {
  value: number | null
  /** Wird erst beim Verlassen des Felds bzw. mit Enter gemeldet (Tippen „zieht“ nicht am Wert) */
  onValueChange: (value: number | null) => void
  min?: number
  max?: number
  /** Schrittweite für ↑/↓ (Umschalt = ×10) */
  step?: number
  /** Nachkommastellen in der Anzeige (Standard 2, ohne überflüssige Nullen) */
  decimals?: number
  /** Einheit rechts im Feld, z. B. „s“, „USD“, „mm“ */
  unit?: ReactNode
  /** Leeres Feld erlaubt (→ null) */
  allowEmpty?: boolean
  /** Technische Schreibweise zulassen: „4k7“, „100n“, „2,2 µ“ (SI-Präfixe, RKM) */
  engineering?: boolean
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  invalid?: boolean
  placeholder?: string
  id?: string
  className?: string
  containerClassName?: string
  'aria-label'?: string
}

function clamp(n: number, min?: number, max?: number): number {
  let v = n
  if (min !== undefined) v = Math.max(min, v)
  if (max !== undefined) v = Math.min(max, v)
  return v
}

/**
 * Zahlenfeld mit deutscher Eingabe: behält den getippten Text, liest ihn erst beim Verlassen/Enter
 * („2,5“, „2.5“, „1.000,5“), begrenzt auf min/max und stellt bei ungültiger Eingabe den letzten Wert wieder her.
 * ↑/↓ ändern um `step` (Umschalt ×10), Esc verwirft die Eingabe.
 */
export function NumberInput({
  value,
  onValueChange,
  min,
  max,
  step = 1,
  decimals = 2,
  unit,
  allowEmpty,
  engineering,
  size = 'md',
  disabled,
  invalid,
  placeholder,
  id,
  className,
  containerClassName,
  'aria-label': ariaLabel,
}: NumberInputProps) {
  const { t, locale } = useI18n()
  const field = useFieldContext()
  // technisch: „4,7k“ statt „4.700“ (Präfix direkt am Wert, Einheit steht rechts im Feld)
  const display = (v: number | null) =>
    v === null ? '' : engineering ? formatEngineering(v, '', Math.max(3, decimals)).replace('\u00a0', '') : formatInputNumber(v, decimals)
  const [text, setText] = useState(() => display(value))
  const [editing, setEditing] = useState(false)
  const [lastValue, setLastValue] = useState(value)
  const [lastLocale, setLastLocale] = useState(locale)

  // Wert von außen geändert (z. B. „Verwerfen“) und gerade nicht in Bearbeitung → Anzeige übernehmen
  if (value !== lastValue || locale !== lastLocale) {
    setLastValue(value)
    setLastLocale(locale)
    if (!editing) setText(display(value))
  }

  const parse = (t: string) => (engineering ? parseEngineering(t) : parseDecimal(t))
  const parsed = parse(text)
  const textInvalid = text.trim() !== '' ? parsed === null : !allowEmpty
  const isInvalid = invalid ?? field?.invalid ?? (editing && textInvalid)
  const isDisabled = disabled ?? field?.disabled

  const commit = () => {
    if (text.trim() === '' && allowEmpty) {
      if (value !== null) onValueChange(null)
      setText('')
      return
    }
    if (parsed === null) {
      setText(display(value)) // ungültig: letzten gültigen Wert wiederherstellen
      return
    }
    const next = clamp(parsed, min, max)
    if (next !== value) onValueChange(next)
    setText(display(next))
  }

  const nudge = (dir: 1 | -1, big: boolean) => {
    const base = parsed ?? value ?? min ?? 0
    const next = clamp(Number((base + dir * step * (big ? 10 : 1)).toFixed(10)), min, max)
    setText(display(next))
    if (next !== value) onValueChange(next)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      commit()
    } else if (e.key === 'Escape' && editing) {
      e.stopPropagation()
      setText(display(value))
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      nudge(e.key === 'ArrowUp' ? 1 : -1, e.shiftKey)
    }
  }

  return (
    <div
      data-invalid={isInvalid || undefined}
      data-disabled={isDisabled || undefined}
      className={cn(controlShell({ size }), containerClassName)}
    >
      <input
        id={id ?? field?.id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        spellCheck={false}
        role="spinbutton"
        aria-label={ariaLabel}
        aria-valuenow={value ?? undefined}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuetext={value === null ? t('leer') : `${display(value)}${typeof unit === 'string' ? ` ${unit}` : ''}`}
        aria-invalid={isInvalid || undefined}
        aria-describedby={field?.describedBy}
        aria-required={field?.required || undefined}
        disabled={isDisabled}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onFocus={() => setEditing(true)}
        onBlur={() => {
          setEditing(false)
          commit()
        }}
        onKeyDown={onKeyDown}
        className={cn('mono h-full w-full min-w-0 flex-1 bg-transparent text-ui outline-none disabled:cursor-not-allowed', className)}
      />
      {unit && <span className="shrink-0 pl-1 text-xs text-fg-subtle">{unit}</span>}
    </div>
  )
}
