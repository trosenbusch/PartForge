/**
 * Bauformen als Mehrfachauswahl (ToggleGroup wie `ChipGroup`): je Kachel Baugröße, metrischer Code und die
 * Kennwerte laut Datenblatt (Leistung, Spannung bzw. Abmessungen „12,5 × 12,5 × 6,0 mm“), bei Auswahl die Zahl der
 * Bauteile – laut Prüfung des Backends, solange die Vorschau zur Auswahl passt, sonst die Sofort-Schätzung.
 */
import { Check } from 'lucide-react'
import { ToggleGroup } from 'radix-ui'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import type { SizeInfo } from '../../model/template'

export interface SizeTilesProps {
  sizes: SizeInfo[]
  value: string[]
  onValueChange: (sizes: string[]) => void
  /** Bauteile je gewählter Baugröße */
  counts: Record<string, number>
  'aria-label': string
}

const DIMENSION_NUMBER = /^\d+(?:[.,]\d+)?$/

/**
 * Abmessungen deutsch: „12.5 x 12.5 x 6.0 mm“ → „12,5 × 12,5 × 6,0 mm“ (Stellen wie im Datenblatt, Einheit einmal am
 * Ende). Andere Schreibweisen gehen an `formatQuantityText`.
 */
function formatDimensions(text: string): string {
  const m = text.trim().match(/^(.*?)\s*(mm|cm|in|mil)?$/i)
  const body = m?.[1] ?? text
  const unit = m?.[2] ?? ''
  const parts = body.split(/\s*[x×*]\s*/i).filter(Boolean)
  if (parts.length < 2 || !parts.every((x) => DIMENSION_NUMBER.test(x))) return formatQuantityText(text)
  return `${parts.map((x) => x.replace('.', ',')).join(' × ')}${unit ? ` ${unit}` : ''}`
}

function facts(info: SizeInfo): string {
  const out: string[] = []
  if (info.power) out.push(formatQuantityText(info.power))
  if (info.voltage) out.push(formatQuantityText(info.voltage))
  if (!out.length && info.dimensions) out.push(formatDimensions(info.dimensions))
  if (!out.length && info.height) out.push(`H ${formatQuantityText(info.height)}`)
  return out.join(' · ')
}

export function SizeTiles({ sizes, value, onValueChange, counts, 'aria-label': ariaLabel }: SizeTilesProps) {
  // Reihenfolge der Vorlage beibehalten
  const order = sizes.map((s) => s.size)
  return (
    <ToggleGroup.Root
      type="multiple"
      value={value}
      onValueChange={(v) => onValueChange(order.filter((s) => v.includes(s)))}
      aria-label={ariaLabel}
      className="grid grid-cols-[repeat(auto-fill,minmax(8.25rem,1fr))] gap-2"
    >
      {sizes.map((info) => {
        const on = value.includes(info.size)
        const count = counts[info.size]
        const detail = facts(info)
        return (
          <ToggleGroup.Item
            key={info.size}
            value={info.size}
            className={cn(
              'group/tile relative flex min-h-[4.25rem] flex-col items-start justify-between gap-1 rounded-control border px-3 py-2 text-left outline-none',
              'transition-[background-color,border-color,box-shadow] duration-150 focus-ring',
              on
                ? 'border-accent/50 bg-accent-soft shadow-[inset_0_1px_0_var(--pf-highlight)]'
                : 'border-line-strong bg-surface-2/70 hover:border-line-control hover:bg-surface-2',
            )}
          >
            <span className="flex w-full items-center justify-between gap-2">
              <span className="flex min-w-0 items-baseline gap-1.5">
                <span className={cn('mono text-ui font-semibold', on ? 'text-accent-text' : 'text-fg')}>{info.size}</span>
                {info.metric && (
                  // auf der Kupfertönung reicht fg-subtle nicht für 11 px (AA)
                  <span className={cn('mono truncate text-2xs', on ? 'text-fg-muted' : 'text-fg-subtle')}>{info.metric}</span>
                )}
              </span>
              <span
                aria-hidden
                className={cn(
                  'flex size-4 items-center justify-center rounded-sm border transition-colors',
                  on ? 'border-transparent bg-accent text-on-accent' : 'border-line-control bg-control',
                )}
              >
                {on && <Check className="size-3" strokeWidth={3} />}
              </span>
            </span>
            <span className="flex w-full flex-col gap-0.5">
              {detail && <span className="truncate text-2xs text-fg-muted">{detail}</span>}
              <span className="h-4 text-2xs tabular-nums text-fg-muted">
                {on && count !== undefined ? `${formatNumber(count)} ${count === 1 ? 'Bauteil' : 'Bauteile'}` : ''}
              </span>
            </span>
          </ToggleGroup.Item>
        )
      })}
    </ToggleGroup.Root>
  )
}
