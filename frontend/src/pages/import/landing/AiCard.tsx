import { Activity, ArrowRight, CircleCheck, Hammer, KeyRound, ListChecks, Power, ScanText, Settings2, Sparkles, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useAiTest, type AiStatus } from '@/api/datasheets'
import { aiSettingsSignature, classifyAiError, useAiConnection, useSettings, type AiConnectionCheck } from '@/api/system'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import { Badge, Button, Card, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, formatRelativeTime } from '@/lib/format'
import { SETTINGS_PLACE } from '@/pages/altium/settingsPlaces'
import { effortLabel, formatUsd, keySourceLabel } from '../lib/format'
import { AI_PROBLEM_TITLE, AI_SETTINGS_CODES } from '../lib/useImportActions'

export interface AiCardStats {
  total: number
  analyzed: number
  committed: number
  costUsd: number
}

const STEPS: { icon: ReactNode; title: string; text: string }[] = [
  { icon: <ScanText />, title: 'Claude liest', text: 'Bestellangaben, Parameter, Pintabellen, Maßzeichnungen' },
  { icon: <ListChecks />, title: 'Sie prüfen', text: 'jede Angabe mit Fundstelle – korrigieren per Klick' },
  { icon: <Hammer />, title: 'PartForge legt an', text: 'Bauteile, Symbol, Footprint und 3D-Körper' },
]

/** Ergebnis eines Verbindungstests (frisch oder der zuletzt gespeicherte) als eine Zeile */
interface TestLine {
  ok: boolean
  text: string
  /** Problem, das sich in Einstellungen › Allgemein › KI-Funktionen beheben lässt */
  fixable: boolean
  at?: number
}

function lineFromCheck(check: AiConnectionCheck): TestLine {
  if (check.ok) {
    return {
      ok: true,
      text: `Verbunden – ${check.model ? modelDisplayName(check.model) : 'Claude'}${check.latencyMs !== null ? ` in ${formatNumber(check.latencyMs)} ms` : ''}`,
      fixable: false,
      at: check.at,
    }
  }
  const title = check.code === 'unexpected' ? 'Unerwartete Antwort' : check.code ? AI_PROBLEM_TITLE[check.code] : 'Verbindung fehlgeschlagen'
  return {
    ok: false,
    text: check.message && check.code !== 'unexpected' ? `${title} – ${check.message}` : (check.message ?? title),
    fixable: Boolean(check.code && check.code !== 'unexpected' && AI_SETTINGS_CODES.has(check.code)),
    at: check.at,
  }
}

/**
 * KI-Status (Modell, Gründlichkeit, Schlüssel, Kostenlimit), Kennzahlen bisheriger Analysen, Ablauf (nur solange die
 * Bibliothek noch keine Datenblätter hat – `compact`), Verbindungstest. Fehler des Tests ordnet `classifyAiError` über
 * `detail.code` ein; der letzte Test bleibt stehen (`useAiConnection`), solange Schlüssel und Modell gleich sind.
 */
export function AiCard({
  status,
  loading,
  stats,
  compact = false,
}: {
  status: AiStatus | undefined
  loading: boolean
  stats: AiCardStats
  compact?: boolean
}) {
  const test = useAiTest()
  const settings = useSettings().data
  const last = useAiConnection((s) => s.last)
  const ready = Boolean(status?.enabled && status.key_configured)
  const average = stats.analyzed ? stats.costUsd / stats.analyzed : null
  const replay = status?.key_source === 'replay'

  // frisches Ergebnis dieses Knopfs, sonst der gespeicherte letzte Test (gleiche Schlüssel-/Modell-Konfiguration)
  const stored = last && last.source === 'test' && settings && last.signature === aiSettingsSignature(settings) ? last : null
  let line: TestLine | null = null
  if (test.isError) {
    const { code, message } = classifyAiError(test.error)
    line = { ok: false, text: `${AI_PROBLEM_TITLE[code]} – ${message}`, fixable: AI_SETTINGS_CODES.has(code) }
  } else if (test.data) {
    line = test.data.ok
      ? {
          ok: true,
          text: `Verbunden – ${test.data.model_label || modelDisplayName(test.data.model)} in ${formatNumber(test.data.latency_ms)} ms · ${formatUsd(test.data.cost_usd)}`,
          fixable: false,
        }
      : { ok: false, text: `Unerwartete Antwort – ${test.data.reply || 'leer'}`, fixable: false }
  } else if (stored && ready) {
    line = lineFromCheck(stored)
  }
  const rejected = ready && line && !line.ok && line.fixable

  return (
    <Card className="flex flex-col overflow-hidden" aria-labelledby="ai-card-title">
      <div className="flex items-start gap-3 px-4 pb-3 pt-4">
        <span
          aria-hidden
          className={cn(
            'flex size-9 shrink-0 items-center justify-center rounded-control [&_svg]:size-[18px]',
            ready ? 'bg-gradient-spark text-on-spark shadow-[var(--pf-shadow-spark)]' : 'border border-line bg-surface-2 text-fg-muted',
          )}
        >
          <Sparkles />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="ai-card-title" className="min-w-0">
            <span className="micro-label block">KI-Analyse</span>
            {!loading && (
              // Modellname vollständig (bricht notfalls um) – „Claude O…“ sagt nichts
              <span className="block break-words text-sm font-semibold leading-snug tracking-[-0.01em] text-fg">
                {status ? status.model_label || modelDisplayName(status.model) : 'Status unbekannt'}
              </span>
            )}
          </h2>
          {loading && <Skeleton className="mt-1 h-4 w-32" />}
        </div>
        {status && (
          <Badge variant={rejected ? 'danger' : ready ? 'success' : status.enabled ? 'warning' : 'neutral'} dot>
            {rejected ? 'Problem' : ready ? 'bereit' : status.enabled ? 'Schlüssel fehlt' : 'aus'}
          </Badge>
        )}
      </div>

      {status && !ready ? (
        <div className="mx-4 mb-4 rounded-card border border-warning/30 bg-warning/8 px-3.5 py-3">
          <div className="flex items-center gap-2 text-ui font-medium text-fg">
            {status.enabled ? <KeyRound aria-hidden className="size-4 text-warning-text" /> : <Power aria-hidden className="size-4 text-warning-text" />}
            {status.enabled ? 'Claude-API-Schlüssel fehlt' : 'KI ist ausgeschaltet'}
          </div>
          <p className="mt-1 text-xs leading-relaxed text-fg-muted">
            {compact
              ? 'Datenblätter werden nur gespeichert – Analyse und Suche brauchen Claude.'
              : status.enabled
                ? 'Datenblätter werden gespeichert, aber nicht analysiert und nicht gesucht. Mit einem Schlüssel aus der Claude Console liest PartForge Parameter, Pins und Gehäusemaße selbst.'
                : `Datenblätter werden nur gespeichert. Analyse und Datenblattsuche lassen sich unter ${SETTINGS_PLACE.ai.label} einschalten.`}
          </p>
          <Button asChild size="sm" variant="secondary" className="mt-2.5">
            <Link to={SETTINGS_PLACE.ai.to}>
              {status.enabled ? 'Schlüssel hinterlegen' : 'Einstellungen öffnen'}
              <ArrowRight aria-hidden />
            </Link>
          </Button>
        </div>
      ) : null}

      {/* ohne nutzbare KI (kompakt) zählt nur der Weg zu den Einstellungen – die Einzelheiten stehen dort */}
      {(ready || !compact) && (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 border-t border-line px-4 py-3 text-xs">
          <dt className="text-fg-subtle">Gründlichkeit</dt>
          <dd className="text-right text-fg" title={status?.use_fallbacks ? 'Bei Überlastung antwortet ein Ausweichmodell' : undefined}>
            {status ? effortLabel(status.effort) : '–'}
          </dd>
          <dt className="text-fg-subtle">Schlüssel</dt>
          <dd
            className="truncate text-right text-fg"
            title={replay ? 'Aufgezeichnete Antworten statt der Claude-API (PARTFORGE_AI_REPLAY_DIR) – nichts kostet' : undefined}
          >
            {status ? (keySourceLabel(status.key_source) ?? 'nicht hinterlegt') : '–'}
          </dd>
          <dt className="text-fg-subtle">Kostenlimit</dt>
          <dd className="text-right text-fg">
            {status ? (
              <>
                <span className="mono">{formatUsd(status.max_cost_per_import_usd)}</span> je Import
              </>
            ) : (
              '–'
          )}
        </dd>
      </dl>
      )}

      <dl className="grid grid-cols-3 border-t border-line">
        <Stat label={stats.analyzed === 1 ? 'Analyse' : 'Analysen'} value={formatNumber(stats.analyzed)} />
        <Stat label="Ø Kosten" value={average === null ? '–' : formatUsd(average)} />
        <Stat label="gesamt" value={formatUsd(stats.costUsd)} />
      </dl>

      {ready && !compact && (
        <ol aria-label="Ablauf" className="flex flex-col gap-2.5 border-t border-line px-4 py-3.5">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex items-start gap-2.5">
              <span
                aria-hidden
                className="flex size-6 shrink-0 items-center justify-center rounded-md border border-line bg-surface-2 text-fg-muted [&_svg]:size-3.5"
              >
                {s.icon}
              </span>
              <div className="min-w-0 text-xs leading-snug">
                <span className="font-medium text-fg">
                  <span className="sr-only">{i + 1}. </span>
                  {s.title}
                </span>
                <span className="block text-fg-subtle">{s.text}</span>
              </div>
            </li>
          ))}
        </ol>
      )}

      {/* ohne nutzbare KI gibt es nichts zu testen – der Weg zu den Einstellungen steht im Hinweis oben */}
      <div className={cn('mt-auto flex flex-wrap items-center gap-2 border-t border-line bg-surface-2/40 px-4 py-3', !ready && status && 'hidden')}>
        <Button size="sm" variant="secondary" leftIcon={<Activity />} loading={test.isPending} disabled={!ready} onClick={() => test.mutate()}>
          Verbindung testen
        </Button>
        <Tooltip content="KI-Einstellungen">
          <Button asChild size="sm" variant="ghost" iconOnly className="ml-auto">
            <Link to={SETTINGS_PLACE.ai.to} aria-label="KI-Einstellungen">
              <Settings2 aria-hidden />
            </Link>
          </Button>
        </Tooltip>
        <div aria-live="polite" className="w-full empty:hidden">
          {line && (
            <p className={cn('flex items-start gap-1.5 text-xs leading-snug', line.ok ? 'text-success-text' : 'text-danger-text')}>
              {line.ok ? (
                <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              ) : (
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
              )}
              <span className="min-w-0">
                {line.text}
                {line.at && !test.data && !test.isError ? <span className="text-fg-subtle"> · {formatRelativeTime(line.at)}</span> : null}
              </span>
            </p>
          )}
        </div>
      </div>
    </Card>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 flex-col-reverse gap-0.5 border-r border-line px-3.5 py-3 last:border-r-0">
      <dt className="truncate text-2xs text-fg-subtle">{label}</dt>
      <dd className="mono truncate text-md font-semibold tabular-nums text-fg">{value}</dd>
    </div>
  )
}
