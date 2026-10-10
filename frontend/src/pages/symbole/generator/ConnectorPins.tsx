import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Eigene Pinnamen eines Steckverbinders (optional): je Pin ein Feld, angeordnet wie im Symbol (zweireihig links
 * und rechts). Mehrzeiliger Text aus der Zwischenablage (Spalte aus Excel, „1⇥VCC“-Tabellen) verteilt sich auf
 * die folgenden Pins.
 */
import { Eraser } from 'lucide-react'
import { useId, type ClipboardEvent } from 'react'
import type { IcPin } from '@/api/symbols'
import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'
import { naturalCompare } from '@/lib/geometry'
import type { ConnectorLayout } from '../util'

export interface ConnectorPinsProps {
  layout: ConnectorLayout
  pins: readonly IcPin[] | undefined
  onChange: (pins: IcPin[] | undefined) => void
  onHoverPin: (designator: string | null) => void
}

const pin = (designator: string, name: string): IcPin => ({ designator, name, electrical: 'passive', part: 1, hidden: false })

/** Name aus einer eingefügten Zeile: „VCC“, „1⇥VCC“ oder „1;VCC“ (führende Pin-Nummer wird übersprungen) */
function nameFromLine(line: string): string {
  const cells = line.split(/\t|;/).map((c) => c.trim())
  if (cells.length > 1 && /^\d{1,3}$/.test(cells[0])) return cells[1] ?? ''
  return cells[0] ?? ''
}

export function ConnectorPins({ layout, pins, onChange, onHoverPin }: ConnectorPinsProps) {
  useI18n()
  const uid = useId().replace(/:/g, '')
  const names = new Map((pins ?? []).map((p) => [p.designator, p.name]))
  const order = layout.pairs
    .flat()
    .filter(Boolean)
    .sort((a, b) => naturalCompare(a, b))
  const named = order.filter((d) => names.get(d)?.trim()).length

  const write = (next: Map<string, string>) => {
    const list = order.filter((d) => next.get(d)?.trim()).map((d) => pin(d, next.get(d) ?? ''))
    onChange(list.length ? list : undefined)
  }
  const setName = (designator: string, name: string) => {
    const next = new Map(names)
    next.set(designator, name)
    write(next)
  }
  const onPaste = (designator: string) => (e: ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData('text/plain').replace(/\r\n?/g, '\n').replace(/\n+$/, '')
    if (!text.includes('\n')) return
    e.preventDefault()
    const lines = text.split('\n')
    const start = order.indexOf(designator)
    const next = new Map(names)
    lines.forEach((line, i) => {
      const target = order[start + i]
      if (target) next.set(target, nameFromLine(line))
    })
    write(next)
  }

  const field = (designator: string, align: 'left' | 'right') => (
    <div
      key={designator}
      className={cn('flex min-w-0 items-center gap-2', align === 'right' && 'flex-row-reverse')}
      onMouseEnter={() => onHoverPin(designator)}
      onMouseLeave={() => onHoverPin(null)}
    >
      <label
        htmlFor={`${uid}-${designator}`}
        className={cn('mono w-7 shrink-0 text-xs font-semibold tabular-nums text-fg-subtle', align === 'left' ? 'text-right' : 'text-left')}
      >
        {designator}
      </label>
      <input
        id={`${uid}-${designator}`}
        value={names.get(designator) ?? ''}
        placeholder="–"
        maxLength={40}
        spellCheck={false}
        autoComplete="off"
        aria-label={tr("Name von Pin {value0}", { value0: String(designator) })}
        onChange={(e) => setName(designator, e.target.value)}
        onPaste={onPaste(designator)}
        onFocus={() => onHoverPin(designator)}
        onBlur={() => onHoverPin(null)}
        className={cn(
          'mono h-7 w-full min-w-0 rounded-md border border-line bg-control px-2 text-ui text-fg outline-none transition-[border-color,box-shadow] duration-100 placeholder:text-fg-subtle hover:border-line-strong focus:border-accent focus:shadow-[0_0_0_3px_var(--pf-accent-soft)]',
          align === 'right' && 'text-right',
        )}
      />
    </div>
  )

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs leading-relaxed text-fg-muted">
          {tr("Optional – leer lassen für reine Nummern. Mehrzeiliger Text (z. B. eine Spalte aus Excel) füllt die folgenden Pins.")}
          {named > 0 && tr(' Mit eigenen Namen bekommt das Symbol einen eigenen Namen (Kennung in Klammern) – oder unter „Erweitert“ selbst benennen.')}
        </p>
        {named > 0 && (
          <Button size="xs" variant="ghost" leftIcon={<Eraser />} onClick={() => onChange(undefined)} className="shrink-0">
            {tr("Leeren")}
          </Button>
        )}
      </div>
      <div
        role="group"
        aria-label={tr("Pinnamen")}
        className={cn('grid gap-x-3 gap-y-1.5', layout.rows === 2 ? 'grid-cols-2' : 'grid-cols-1 @[26rem]:max-w-72')}
      >
        {layout.pairs.flatMap(([left, right]) => (layout.rows === 2 ? [field(left, 'left'), field(right, 'right')] : [field(left, 'left')]))}
      </div>
    </div>
  )
}
