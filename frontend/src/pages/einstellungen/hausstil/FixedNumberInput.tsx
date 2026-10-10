/**
 * Zahlenfeld mit **fester** Nachkommazahl („0,10“, „0,05“, „1,00“ mm) – Maße im Hausstil lesen sich so als
 * einheitliche Spalte. Verhalten wie `NumberInput` aus dem UI-Kit (getippter Text bleibt bis Enter/Verlassen,
 * ↑/↓ = Schritt, ⇧ ×10, Esc verwirft), nur die Anzeige ist fest formatiert.
 *
 * Wunsch an das UI-Kit: `NumberInput` mit Option `fixedDecimals` – dann entfällt diese Datei.
 */
import { useState, type KeyboardEvent } from 'react'
import { getLocale, useI18n } from '@/lib/i18n'
import { useFieldContext } from '@/components/ui/fieldContext'
import { controlShell } from '@/components/ui/variants'
import { cn } from '@/lib/cn'
import { parseDecimal } from '@/lib/format'

const formats = new Map<string, Intl.NumberFormat>()
function formatFixed(value: number, decimals: number): string {
  const key = `${getLocale()}:${decimals}`
  let f = formats.get(key)
  if (!f) {
    f = new Intl.NumberFormat(getLocale(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
    formats.set(key, f)
  }
  return f.format(value)
}

const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n))

export interface FixedNumberInputProps {
  value: number
  onValueChange: (value: number) => void
  min: number
  max: number
  step: number
  decimals: number
  unit: string
  className?: string
  'aria-label'?: string
}

export function FixedNumberInput({ value, onValueChange, min, max, step, decimals, unit, className, 'aria-label': ariaLabel }: FixedNumberInputProps) {
  const { locale } = useI18n()
  const field = useFieldContext()
  const display = (v: number) => formatFixed(v, decimals)
  const [text, setText] = useState(() => display(value))
  const [editing, setEditing] = useState(false)
  const [lastValue, setLastValue] = useState(value)
  const [lastLocale, setLastLocale] = useState(locale)

  // Wert von außen geändert (Zurücksetzen, Verwerfen) und gerade nicht in Bearbeitung → Anzeige übernehmen
  if (value !== lastValue || locale !== lastLocale) {
    setLastLocale(locale)
    setLastValue(value)
    if (!editing) setText(display(value))
  }

  const parsed = parseDecimal(text)
  const invalid = editing && text.trim() !== '' && parsed === null

  const commit = () => {
    if (parsed === null) {
      setText(display(value)) // ungültig/leer: letzten gültigen Wert wiederherstellen
      return
    }
    // auf die angezeigte Genauigkeit runden, damit gespeicherter und angezeigter Wert gleich sind
    const next = clamp(Number(parsed.toFixed(decimals)), min, max)
    if (next !== value) onValueChange(next)
    setText(display(next))
  }

  const nudge = (dir: 1 | -1, big: boolean) => {
    const base = parsed ?? value
    const next = clamp(Number((base + dir * step * (big ? 10 : 1)).toFixed(decimals)), min, max)
    setText(display(next))
    if (next !== value) onValueChange(next)
  }

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') commit()
    else if (e.key === 'Escape' && editing) {
      e.stopPropagation()
      setText(display(value))
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      nudge(e.key === 'ArrowUp' ? 1 : -1, e.shiftKey)
    }
  }

  return (
    <div data-invalid={invalid || undefined} className={cn(controlShell({ size: 'md' }), className)}>
      <input
        id={field?.id}
        type="text"
        inputMode="decimal"
        autoComplete="off"
        spellCheck={false}
        role="spinbutton"
        aria-label={ariaLabel}
        aria-valuenow={value}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuetext={`${display(value)} ${unit}`}
        aria-invalid={invalid || undefined}
        aria-describedby={field?.describedBy}
        value={editing ? text : display(value)}
        onChange={(e) => setText(e.target.value)}
        onFocus={() => setEditing(true)}
        onBlur={() => {
          setEditing(false)
          commit()
        }}
        onKeyDown={onKeyDown}
        className="mono tabular h-full w-full min-w-0 flex-1 bg-transparent text-ui outline-none"
      />
      <span className="shrink-0 pl-1 text-xs text-fg-subtle">{unit}</span>
    </div>
  )
}
