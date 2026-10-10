import { localizeMessage } from '@/lib/i18n'
import { t, useI18n } from '@/lib/i18n'
import { Coins, TriangleAlert } from 'lucide-react'
import type { RunInfo } from '@/api/datasheets'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import { Popover, PopoverContent, PopoverTrigger, ProgressBar } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDuration, formatNumber, plural, pluralNoun } from '@/lib/format'
import { formatUsd, pagesText } from '../lib/format'

const RUN_LABEL: Record<RunInfo['kind'], string> = {
  get triage() { return t("Seiten-Vorauswahl") },
  get identity() { return t("Bauteile und Pins") },
  get geometry() { return t("Gehäusemaße") },
  get verify_identity() { return t("Kontrolle der Pintabellen") },
  get verify_geometry() { return t("Kontrolle der Zeichnungen") },
  get test() { return t("Verbindungstest") },
  get find() { return t("Datenblattsuche im Web") },
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
export function CostChip({ costUsd, runs = [], budgetUsd, className, label = t("Analyse") }: CostChipProps) {
  useI18n()
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
          <span className="sr-only">{label}{t(": Kosten ")}</span>
          <span className="mono font-semibold text-fg">{formatUsd(costUsd)}</span>
          <span className="sr-only">
            {failed > 0 ? t(" – {0} bezahlte {1} nicht verwertbar", { "0": String(failed), "1": pluralNoun(failed, t("Anfrage"), t("Anfragen")) }) : ''} {t(" – Einzelheiten anzeigen")}</span>
          {failed > 0 && <TriangleAlert aria-hidden className="size-3.5 text-warning-text" />}
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label={t("Kosten der Analyse")} className="w-[22rem] p-0">
        <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <div className="micro-label">{t("Kosten der Analyse")}</div>
            <div className="mono mt-0.5 text-h3 font-semibold text-fg">{formatUsd(costUsd, { precise: true })}</div>
          </div>
          <div className="text-right text-xs text-fg-muted">
            {plural(runs.length, t("Anfrage"), t("Anfragen"))}
            {budgetUsd ? <div className="text-fg-subtle">{t("Limit je Import ")}{formatUsd(budgetUsd)}</div> : null}
          </div>
        </div>
        {budgetUsd ? (
          <div className="px-4 pt-3">
            <ProgressBar
              value={Math.min(costUsd, budgetUsd)}
              max={budgetUsd}
              tone={costUsd > budgetUsd * 0.8 ? 'warning' : 'spark'}
              size="xs"
              label={t("Anteil am Kostenlimit")}
              hideLabel
            />
          </div>
        ) : null}
        {runs.length ? (
          // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- scrollbare Liste per Tastatur lesbar
          <ul tabIndex={0} aria-label={t("Bezahlte Anfragen")} className="max-h-72 divide-y divide-line overflow-y-auto px-4 py-1 outline-none focus-ring-inset">
            {runs.map((r, i) => (
              <li key={`${r.ts}-${i}`} className="py-2.5">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-ui font-medium text-fg">{RUN_LABEL[r.kind] ?? r.kind}</span>
                  <span className="mono text-ui text-fg">{formatUsd(r.cost_usd, { precise: true })}</span>
                </div>
                <div className="mt-0.5 text-2xs leading-4 text-fg-subtle">
                  {modelDisplayName(r.served_model || r.model)}
                  {r.fallback ? t(" (Ausweichmodell)") : ''}
                  {r.pages.length ? t(" · Seiten {0}", { "0": String(pagesText(r.pages)) }) : ''} · {formatDuration(r.duration_s)}
                  {' · '}
                  {formatNumber(r.usage.input_tokens + r.usage.cache_write_tokens + r.usage.cache_read_tokens)} →{' '}
                  {formatNumber(r.usage.output_tokens)} Token
                </div>
                {r.error && <div className="mt-1 text-2xs leading-4 text-warning-text">{t("Bezahlt, aber nicht verwertbar: ")}{localizeMessage(r.error)}</div>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-xs text-fg-muted">{t("Noch keine bezahlten Anfragen.")}</p>
        )}
        <p className="border-t border-line px-4 py-2.5 text-2xs leading-4 text-fg-subtle">
          {t("Jede bezahlte Anfrage wird gespeichert – auch wenn eine Analyse scheitert oder abgebrochen wird.")}</p>
      </PopoverContent>
    </Popover>
  )
}
