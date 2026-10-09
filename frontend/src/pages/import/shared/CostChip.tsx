import { Coins, TriangleAlert } from 'lucide-react'
import type { RunInfo } from '@/api/datasheets'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import { Popover, PopoverContent, PopoverTrigger, ProgressBar } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDuration, formatNumber } from '@/lib/format'
import { formatUsd, pagesText } from '../lib/format'

const RUN_LABEL: Record<RunInfo['kind'], string> = {
  triage: 'Seiten-Vorauswahl',
  identity: 'Bauteile und Pins',
  geometry: 'Gehäusemaße',
  verify_identity: 'Kontrolle der Pintabellen',
  verify_geometry: 'Kontrolle der Zeichnungen',
  test: 'Verbindungstest',
  find: 'Datenblattsuche im Web',
}

export interface CostChipProps {
  costUsd: number
  runs?: RunInfo[]
  budgetUsd?: number | null
  className?: string
  /** Beschriftung vor dem Betrag (Standard „Analyse“) */
  label?: string
}

/** Kosten der Claude-Anfragen eines Datenblatts – Klick zeigt jede Anfrage mit Modell, Seiten, Token und Dauer. */
export function CostChip({ costUsd, runs = [], budgetUsd, className, label = 'Analyse' }: CostChipProps) {
  const failed = runs.filter((r) => r.error).length
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          // Name = sichtbarer Betrag mit Zusatz für Screenreader (kein abweichendes aria-label)
          className={cn(
            'inline-flex h-7 items-center gap-1.5 rounded-control border border-line-strong bg-surface-2 px-2.5 text-xs text-fg-muted',
            'shadow-[inset_0_1px_0_var(--pf-highlight)] outline-none transition-colors hover:bg-surface-3 hover:text-fg focus-ring',
            'data-[state=open]:bg-surface-3 data-[state=open]:text-fg',
            className,
          )}
        >
          <Coins aria-hidden className="size-3.5" />
          <span className="sr-only">{label}: Kosten </span>
          <span className="mono font-semibold text-fg">{formatUsd(costUsd)}</span>
          <span className="sr-only">
            {failed > 0 ? ` – ${failed} bezahlte ${failed === 1 ? 'Anfrage' : 'Anfragen'} nicht verwertbar` : ''} – Einzelheiten anzeigen
          </span>
          {failed > 0 && <TriangleAlert aria-hidden className="size-3.5 text-warning-text" />}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label="Kosten der Analyse" className="w-[22rem] p-0">
        <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <div className="micro-label">Kosten der Analyse</div>
            <div className="mono mt-0.5 text-h3 font-semibold text-fg">{formatUsd(costUsd, { precise: true })}</div>
          </div>
          <div className="text-right text-xs text-fg-muted">
            {formatNumber(runs.length)} {runs.length === 1 ? 'Anfrage' : 'Anfragen'}
            {budgetUsd ? <div className="text-fg-subtle">Limit je Import {formatUsd(budgetUsd)}</div> : null}
          </div>
        </div>
        {budgetUsd ? (
          <div className="px-4 pt-3">
            <ProgressBar
              value={Math.min(costUsd, budgetUsd)}
              max={budgetUsd}
              tone={costUsd > budgetUsd * 0.8 ? 'warning' : 'spark'}
              size="xs"
              label="Anteil am Kostenlimit"
              hideLabel
            />
          </div>
        ) : null}
        {runs.length ? (
          // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- scrollbare Liste per Tastatur lesbar
          <ul tabIndex={0} aria-label="Bezahlte Anfragen" className="max-h-72 divide-y divide-line overflow-y-auto px-4 py-1 outline-none focus-ring-inset">
            {runs.map((r, i) => (
              <li key={`${r.ts}-${i}`} className="py-2.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-ui font-medium text-fg">{RUN_LABEL[r.kind] ?? r.kind}</span>
                  <span className="mono text-ui text-fg">{formatUsd(r.cost_usd, { precise: true })}</span>
                </div>
                <div className="mt-0.5 text-2xs leading-4 text-fg-subtle">
                  {modelDisplayName(r.served_model || r.model)}
                  {r.fallback ? ' (Ausweichmodell)' : ''}
                  {r.pages.length ? ` · Seiten ${pagesText(r.pages)}` : ''} · {formatDuration(r.duration_s)}
                  {' · '}
                  {formatNumber(r.usage.input_tokens + r.usage.cache_write_tokens + r.usage.cache_read_tokens)} →{' '}
                  {formatNumber(r.usage.output_tokens)} Token
                </div>
                {r.error && <div className="mt-1 text-2xs leading-4 text-warning-text">Bezahlt, aber nicht verwertbar: {r.error}</div>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-xs text-fg-muted">Noch keine bezahlten Anfragen.</p>
        )}
        <p className="border-t border-line px-4 py-2.5 text-2xs leading-4 text-fg-subtle">
          Jede bezahlte Anfrage wird gespeichert – auch wenn eine Analyse scheitert oder abgebrochen wird.
        </p>
      </PopoverContent>
    </Popover>
  )
}
