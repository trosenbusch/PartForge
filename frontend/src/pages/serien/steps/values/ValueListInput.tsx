import { useI18n } from '@/lib/i18n'
/**
 * Werteliste einfügen (statt E-Reihe): eine Zeile je Wert oder durch Komma/Semikolon getrennt – „10k, 4k7, 2,2 µ“,
 * „0“ für die Brücke. Darunter die gelesenen Werte als Chips (ungültige rot mit Grund, doppelte durchgestrichen).
 */
import { Textarea, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { displayValue, type ParsedValue } from '../../model/values'

const MAX_CHIPS = 80

export interface ValueListInputProps {
  id: string
  text: string
  onTextChange: (text: string) => void
  parsed: ParsedValue[]
  unit: string
  jumper: boolean
}

export function ValueListInput({ id, text, onTextChange, parsed, unit, jumper }: ValueListInputProps) {
  const { t: tr } = useI18n()
  const valid = parsed.filter((p) => p.value !== null && !p.error && !p.duplicate).length
  const invalid = parsed.filter((p) => p.error).length
  const duplicates = parsed.filter((p) => p.duplicate).length
  const example = unit === 'F' ? '100n, 220n, 1µ, 4,7µ' : unit === 'H' ? '1µ, 2,2µ, 4,7µ, 10µ' : '10k, 4k7, 2k2, 1M'
  return (
    <div className="flex flex-col gap-2.5">
      <Textarea
        id={id}
        value={text}
        onChange={(e) => onTextChange(e.target.value)}
        rows={4}
        autoResize
        spellCheck={false}
        className="mono text-ui"
        placeholder={`${example}${jumper ? '\n' + tr("0 (0-Ω-Brücke)") : ''}`}
        aria-label={tr("Werteliste – ein Wert je Zeile oder durch Komma getrennt")}
        aria-describedby={`${id}-summary`}
      />
      <div id={`${id}-summary`} aria-live="polite" className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-muted">
        {parsed.length === 0 ? (
          <span>{tr("Werte mit Einheit oder technischer Schreibweise: 4k7 · 2,2 µ · 100n · R47 – eine Zeile oder durch Komma getrennt.")}</span>
        ) : (
          <>
            <span>
              <span className="mono font-semibold text-fg">{formatNumber(valid)}</span> {valid === 1 ? tr("Wert") : tr("Werte")}
            </span>
            {invalid > 0 && <span className="text-danger-text">{plural(invalid, tr("ungültig"), tr("ungültig"))}</span>}
            {duplicates > 0 && <span>{plural(duplicates, tr("doppelt"), tr("doppelt"))}</span>}
          </>
        )}
      </div>
      {parsed.length > 0 && (
        <ul aria-label={tr("Gelesene Werte")} className="flex flex-wrap gap-1">
          {parsed.slice(0, MAX_CHIPS).map((p, i) => {
            const chip = (
              <span
                className={cn(
                  'mono inline-flex h-6 items-center gap-1 rounded-full border px-2 text-2xs',
                  p.error
                    ? 'border-danger/35 bg-danger/10 text-danger-text'
                    : p.duplicate
                      ? 'border-line text-fg-subtle line-through'
                      : 'border-line-strong bg-surface-2 text-fg',
                )}
              >
                {p.value !== null && !p.error ? (p.jumper ? tr("0 Ω · Brücke") : displayValue(p.value, unit)) : p.raw}
              </span>
            )
            return (
              <li key={`${p.raw}-${i}`}>
                {p.error ? (
                  <Tooltip content={tr("„{v0}“: {v1}", { v0: p.raw, v1: p.error })}>
                    <span className="cursor-help">
                      {chip}
                      <span className="sr-only">: {p.error}</span>
                    </span>
                  </Tooltip>
                ) : (
                  chip
                )}
              </li>
            )
          })}
          {parsed.length > MAX_CHIPS && (
            <li className="flex h-6 items-center px-1 text-2xs text-fg-subtle">{tr("… und")} {formatNumber(parsed.length - MAX_CHIPS)} {tr("weitere")}</li>
          )}
        </ul>
      )}
    </div>
  )
}
