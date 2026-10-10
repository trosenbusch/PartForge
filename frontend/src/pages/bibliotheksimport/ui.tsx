/**
 * Kleine Bausteine des Bibliotheksimports: Zustand eines Namens, Art einer Bibliothek, Auswahlkästchen im Dateibaum,
 * relativer Pfad mit hervorgehobenem Dateinamen.
 */
import { CircuitBoard, Shapes } from 'lucide-react'
import { Fragment } from 'react'
import { STATE_LABELS, type ImportComponentState } from '@/api/libimport'
import { Badge, type BadgeProps, type CheckedState } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import type { LibKind } from './model'

const STATE_VARIANT: Record<ImportComponentState, NonNullable<BadgeProps['variant']>> = {
  new: 'success',
  imported: 'info',
  taken: 'warning',
  duplicate: 'neutral',
}

/** Zustände mit Anzahl („1 Name vergeben“, „77 Namen vergeben“) */
const COUNT_LABELS: Record<ImportComponentState, readonly [string, string]> = {
  new: ['neu', 'neu'],
  imported: ['schon importiert', 'schon importiert'],
  taken: ['Name vergeben', 'Namen vergeben'],
  duplicate: ['doppelt', 'doppelt'],
}

/** Zustand eines Namens der Quelle (neu, schon importiert, Name vergeben, doppelt) – optional mit Anzahl */
export function StateBadge({ state, count, className }: { state: ImportComponentState; count?: number; className?: string }) {
  return (
    <Badge variant={STATE_VARIANT[state]} className={cn('tabular-nums', className)}>
      {count !== undefined ? `${formatNumber(count)} ${COUNT_LABELS[state][count === 1 ? 0 : 1]}` : STATE_LABELS[state]}
    </Badge>
  )
}

/**
 * Relativer Pfad in Monospace: Ordner gedämpft, Dateiname hervorgehoben; Umbruch nur an Pfadtrennern (wie
 * `PathText`), sehr lange Namen notfalls an beliebiger Stelle.
 */
export function RelPath({ rel, muted, className }: { rel: string; muted?: boolean; className?: string }) {
  const parts = rel.split(/(?<=[\\/])/)
  const last = parts.length - 1
  return (
    <span className={cn('mono [overflow-wrap:anywhere]', className)} title={rel}>
      {parts.map((part, i) => (
        <Fragment key={i}>
          <span className={i === last ? cn('font-medium', muted ? 'text-fg-muted' : 'text-fg') : 'text-fg-subtle'}>{part}</span>
          {i < last && <wbr />}
        </Fragment>
      ))}
    </span>
  )
}

/** Symbol (SchLib) bzw. Footprint (PcbLib) – dekorativ, die Art steht immer auch als Text daneben */
export function KindIcon({ kind, className }: { kind: LibKind; className?: string }) {
  const Icon = kind === 'schlib' ? Shapes : CircuitBoard
  return <Icon aria-hidden className={cn('size-4 shrink-0 text-fg-muted', className)} />
}

/**
 * Auswahlkästchen im Dateibaum – nur die Anzeige: Der Baum ist ein zusammengesetztes Bedienelement (Fokus auf der
 * Liste, `aria-checked` an der Zeile, Leertaste schaltet), darin dürfen keine eigenen Bedienelemente liegen.
 */
export function CheckMark({ checked, disabled }: { checked: CheckedState; disabled?: boolean }) {
  const on = checked === true
  const mixed = checked === 'indeterminate'
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-4 shrink-0 items-center justify-center rounded-sm border transition-[background-color,border-color] duration-150',
        on || mixed
          ? 'border-transparent bg-gradient-forge text-on-accent shadow-[var(--pf-glow-control)]'
          : 'border-line-control bg-control shadow-[inset_0_1px_1px_rgba(0,0,0,.12)]',
        disabled && 'opacity-45',
      )}
    >
      {(on || mixed) && (
        <svg viewBox="0 0 16 16" className="size-3" fill="none">
          {mixed ? (
            <path d="M4 8h8" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
          ) : (
            <path d="M3.5 8.5l3 3 6-7" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          )}
        </svg>
      )}
    </span>
  )
}
