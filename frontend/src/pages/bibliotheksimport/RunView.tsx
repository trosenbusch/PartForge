/**
 * Import-Job (`libraries.import`) inline: Fortschritt mit Protokoll und „Abbrechen“, danach das Ergebnis – ehrlich: grün
 * nur ohne Fehler, Konflikte und übersprungene Dateien, sonst als Warnung – mit den Listen (nicht übernommene Namen,
 * übersprungene Dateien, Fehler, Angleichen an den Hausstil) und den nächsten Schritten.
 */
import { motion } from 'motion/react'
import { ChevronDown, CircleAlert, CircleCheck, CircleStop, CircleX, Info, PaintbrushVertical, TriangleAlert, Upload } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { cleanErrorText } from '@/api/client'
import { jobCancelText } from '@/api/jobs'
import type { ImportConflict, ImportRunResult } from '@/api/libimport'
import { useCancelJob, type Job } from '@/api/system'
import { Badge, Button, Callout, Card, CardContent, CardHeader, ProgressBar, Skeleton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, formatNumbersInText, plural } from '@/lib/format'
import { SETTINGS_PLACE } from '@/lib/settingsPlaces'
import { NextSteps } from './NextSteps'
import type { ImportRun } from './store'
import { RelPath } from './ui'

/** So viele Einträge zeigt eine Ergebnisliste zuerst (weitere auf Wunsch) */
const ISSUE_PAGE = 50

export interface RunViewProps {
  run: ImportRun
  job: Job<ImportRunResult> | undefined
  /** Stand des Jobs nicht abrufbar (Verbindung) */
  error: Error | null
  /** Stand erneut abrufen */
  onRetry: () => void
  /** zurück zur Auswahl (Scan bleibt) */
  onBack: () => void
  /** Quelle erneut einlesen – `null`, wenn sie nicht bekannt ist */
  onRescan: (() => void) | null
  /** weitere Quelle importieren (alles zurücksetzen) */
  onReset: () => void
}

export function RunView({ run, job, error, onRetry, onBack, onRescan, onReset }: RunViewProps) {
  if (!job && error) {
    return (
      <Callout
        tone="warning"
        title="Stand des Imports nicht abrufbar"
        actions={
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Erneut versuchen
          </Button>
        }
      >
        {cleanErrorText(error.message)} Der Import läuft im Backend weiter – das Job-Dock zeigt ihn ebenfalls.
      </Callout>
    )
  }
  if (!job) {
    return (
      <Card className="flex items-center gap-3 px-5 py-5">
        <Spinner size={16} tone="accent" />
        <span className="text-ui text-fg-muted">Import wird gestartet …</span>
        <Skeleton className="ml-auto h-7 w-24" />
      </Card>
    )
  }
  if (job.status === 'queued' || job.status === 'running') return <RunProgress job={job} convert={run.convert} />
  if (job.status === 'failed' || job.status === 'cancelled') return <RunStopped job={job} onBack={onBack} onRescan={onRescan} />
  if (!job.result) return <RunStopped job={job} onBack={onBack} onRescan={onRescan} />
  return <RunResult result={job.result} run={run} onBack={onBack} onRescan={onRescan} onReset={onReset} />
}

// --------------------------------------------------------------------------- Fortschritt

function RunProgress({ job, convert }: { job: Job<ImportRunResult>; convert: boolean }) {
  const cancel = useCancelJob()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const queued = job.status === 'queued'
  const stopping = Boolean(job.cancel_requested)
  // Start: Fokus auf die Überschrift des Fortschritts (der Startknopf ist weg)
  useEffect(() => headingRef.current?.focus({ preventScroll: true }), [])
  const log = job.log.slice(-10)
  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      aria-labelledby="bibliotheksimport-lauf"
      className="overflow-hidden rounded-panel border border-line bg-surface shadow-raised"
    >
      <div className="flex items-start gap-4 px-5 py-5">
        <span
          aria-hidden
          className="flex size-10 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted [&_svg]:size-5"
        >
          <Upload />
        </span>
        <div className="min-w-0 flex-1">
          <h2 id="bibliotheksimport-lauf" ref={headingRef} tabIndex={-1} className="text-md font-semibold text-fg outline-none">
            {stopping ? 'Wird abgebrochen …' : queued ? 'Wartet auf den Start …' : 'Bibliotheksimport läuft'}
          </h2>
          <p className="mt-0.5 text-xs text-fg-muted [overflow-wrap:anywhere]">
            {formatNumbersInText(job.message) || 'Wird vorbereitet …'}
            {convert && ' Danach wird an den Hausstil angeglichen.'}
          </p>
          <ProgressBar
            className="mt-3"
            value={job.progress}
            indeterminate={queued}
            live
            showValue
            label={job.title}
            size="md"
          />
        </div>
        <Button
          variant="secondary"
          leftIcon={<CircleStop />}
          loading={cancel.isPending || stopping}
          disabled={stopping}
          onClick={() => cancel.mutate(job.id)}
        >
          {stopping ? 'Wird abgebrochen' : 'Abbrechen'}
        </Button>
      </div>
      {log.length > 0 && (
        <div className="border-t border-line px-5 py-3">
          <h3 className="micro-label mb-1.5">Protokoll</h3>
          <ol className="mono flex flex-col gap-0.5 text-2xs text-fg-subtle" aria-label="Letzte Einträge des Protokolls">
            {log.map((l, i) => (
              <li key={`${l.ts}-${i}`} className={cn('[overflow-wrap:anywhere]', l.level === 'warn' && 'text-warning-text', l.level === 'error' && 'text-danger-text')}>
                {formatNumbersInText(l.text)}
              </li>
            ))}
          </ol>
        </div>
      )}
      <p className="border-t border-line bg-surface-2/40 px-5 py-2.5 text-xs text-fg-muted">
        Der Import schreibt in die Bibliothek – Quelle und Auswahl sind so lange gesperrt. Sie können die Seite verlassen; das Job-Dock meldet
        den Abschluss.
      </p>
    </motion.section>
  )
}

// --------------------------------------------------------------------------- abgebrochen / fehlgeschlagen

function RunStopped({ job, onBack, onRescan }: { job: Job<ImportRunResult>; onBack: () => void; onRescan: (() => void) | null }) {
  const navigate = useNavigate()
  const failed = job.status !== 'cancelled'
  const error = failed ? cleanErrorText(job.error ?? job.message ?? '') || 'Der Import ist fehlgeschlagen.' : null
  const cancelText = jobCancelText(job)
  return (
    <Callout
      tone={failed ? 'danger' : 'info'}
      urgent={failed}
      title={failed ? 'Import fehlgeschlagen' : 'Import abgebrochen'}
      actions={
        <>
          {error && /bibliotheks-writer/i.test(error) && (
            <Button size="sm" onClick={() => navigate(SETTINGS_PLACE.altium.to)}>
              Writer einrichten
            </Button>
          )}
          <Button size="sm" variant="secondary" onClick={onBack}>
            Zur Auswahl
          </Button>
          {onRescan && (
            <Button size="sm" variant="ghost" onClick={onRescan}>
              Erneut einlesen
            </Button>
          )}
        </>
      }
    >
      {error
        ? formatNumbersInText(error)
        : `${cancelText === 'Abgebrochen' ? 'Der Import wurde abgebrochen.' : cancelText.replace(/\s*\.?$/, '.')} Bis dahin übernommene Dateien bleiben in der Bibliothek – für den aktuellen Stand die Quelle erneut einlesen.`}
    </Callout>
  )
}

// --------------------------------------------------------------------------- Ergebnis

type Tone = 'success' | 'warning' | 'danger'

/** Grün nur ohne Fehler, Konflikte und Übersprungenes; nichts übernommen und Fehler = rot */
function resultTone(r: ImportRunResult): Tone {
  const conversionProblems = r.conversion ? r.conversion.errors.length + r.conversion.skipped.length : 0
  const problems = r.conflicts.length + r.skipped.length + r.errors.length + conversionProblems
  const imported = r.copied + r.unchanged + r.symbols + r.footprints
  if (!imported && r.errors.length) return 'danger'
  if (problems || !imported) return 'warning'
  return 'success'
}

const HEAD: Record<Tone, { icon: ReactNode; ring: string }> = {
  success: { icon: <CircleCheck aria-hidden className="size-5" />, ring: 'bg-success/12 text-success-text' },
  warning: { icon: <TriangleAlert aria-hidden className="size-5" />, ring: 'bg-warning/14 text-warning-text' },
  danger: { icon: <CircleX aria-hidden className="size-5" />, ring: 'bg-danger/12 text-danger-text' },
}

function RunResult({
  result,
  run,
  onBack,
  onRescan,
  onReset,
}: {
  result: ImportRunResult
  run: ImportRun
  onBack: () => void
  onRescan: (() => void) | null
  onReset: () => void
}) {
  const headingRef = useRef<HTMLHeadingElement>(null)
  // Ergebnis: Fokus auf die Überschrift (der Fortschritt ist weg)
  useEffect(() => headingRef.current?.focus({ preventScroll: true }), [])
  const tone = resultTone(result)
  const imported = result.symbols + result.footprints
  const title =
    tone === 'success'
      ? 'Import abgeschlossen'
      : tone === 'danger'
        ? 'Import fehlgeschlagen'
        : imported || result.copied || result.unchanged
          ? 'Import mit Hinweisen'
          : 'Nichts übernommen'
  const stats: { label: string; value: number; tone?: string }[] = [
    { label: 'kopiert', value: result.copied },
    { label: 'unverändert', value: result.unchanged },
    { label: 'Symbole', value: result.symbols, tone: result.symbols ? 'text-success-text' : undefined },
    { label: 'Footprints', value: result.footprints, tone: result.footprints ? 'text-success-text' : undefined },
    { label: 'Namen nicht übernommen', value: result.conflicts.length, tone: result.conflicts.length ? 'text-warning-text' : undefined },
    { label: 'Dateien übersprungen', value: result.skipped.length, tone: result.skipped.length ? 'text-warning-text' : undefined },
    { label: 'Fehler', value: result.errors.length, tone: result.errors.length ? 'text-danger-text' : undefined },
  ]
  const conflictGroups = groupConflicts(result.conflicts)
  const removed = result.removed ?? []
  const hasDetails = Boolean(result.conflicts.length || result.skipped.length || result.errors.length || removed.length || result.conversion)

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18 }}
      aria-labelledby="bibliotheksimport-ergebnis"
      className="flex flex-col gap-4"
    >
      <Card className="overflow-hidden">
        <div className="flex items-center gap-3 px-5 py-4" role={tone === 'success' ? 'status' : 'alert'}>
          <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-full', HEAD[tone].ring)}>{HEAD[tone].icon}</span>
          <div className="min-w-0 flex-1">
            <h2 id="bibliotheksimport-ergebnis" ref={headingRef} tabIndex={-1} className="text-md font-semibold text-fg outline-none">
              {title}
            </h2>
            <p className="text-xs text-fg-muted">
              {formatNumbersInText(result.message)} Zielordner „{run.target}“.
            </p>
          </div>
          {/* nichts geschrieben: die Auswahl stimmt noch – sonst „Quelle erneut einlesen“ (aktuelle Zustände) */}
          {!result.copied && !result.unchanged && (
            <Button size="sm" variant="ghost" onClick={onBack}>
              Zur Auswahl
            </Button>
          )}
        </div>
        <dl className="grid grid-cols-7 divide-x divide-line border-t border-line">
          {stats.map((s) => (
            <div key={s.label} className="flex min-w-0 flex-col justify-between gap-0.5 px-4 py-2.5">
              <dt className="text-2xs leading-tight text-fg-subtle">{s.label}</dt>
              <dd className={cn('mono text-h3 font-semibold tabular-nums', s.tone ?? 'text-fg')}>{formatNumber(s.value)}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <div className={cn('grid items-start gap-4', hasDetails && '@[64rem]:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]')}>
        {hasDetails && (
          <div className="flex min-w-0 flex-col gap-4">
            {result.conversion && <ConversionCard conversion={result.conversion} />}
            {conflictGroups.map((g) => (
              <IssueSection
                key={g.reason}
                tone="warning"
                title={`${g.reason} – ${plural(g.items.length, 'Name', 'Namen')} nicht übernommen`}
                hint={
                  /doppelt/i.test(g.reason)
                    ? 'Der Name kommt in der Quelle mehrfach vor – übernommen wurde nur das erste Vorkommen.'
                    : 'Altium findet Symbole und Footprints nur über den Namen – ein schon registrierter Name wird nicht ein zweites Mal übernommen.'
                }
                items={g.items}
                render={(c) => (
                  <>
                    <Badge variant="outline">{c.kind === 'symbol' ? 'Symbol' : 'Footprint'}</Badge>
                    <span className="mono text-xs font-medium text-fg [overflow-wrap:anywhere]">{c.name}</span>
                    {c.registered_library && (
                      <span className="text-2xs text-fg-subtle">
                        {/doppelt/i.test(c.reason) ? 'übernommen aus ' : 'registriert in '}
                        <RelPath rel={c.registered_library} className="text-2xs" />
                      </span>
                    )}
                  </>
                )}
                itemKey={(c) => `${c.kind}:${c.name}:${c.library}`}
              />
            ))}
            {result.skipped.length > 0 && (
              <IssueSection
                tone="warning"
                title={`${plural(result.skipped.length, 'Datei', 'Dateien')} übersprungen`}
                items={result.skipped}
                render={(s) => (
                  <>
                    <RelPath rel={s.rel} className="text-xs" />
                    <span className="text-2xs text-fg-muted">{s.reason}</span>
                  </>
                )}
                itemKey={(s) => s.rel}
              />
            )}
            {removed.length > 0 && (
              <IssueSection
                tone="info"
                title={`${plural(removed.length, 'Name', 'Namen')} abgemeldet – nicht mehr in der neuen Fassung`}
                hint="Ersetzte Dateien bestimmen, was registriert ist: Schon importierte Symbole bzw. Footprints, die ihre neue Fassung nicht mehr enthält, wurden abgemeldet."
                items={removed}
                render={(r) => (
                  <>
                    <Badge variant="outline">{r.kind === 'symbol' ? 'Symbol' : 'Footprint'}</Badge>
                    <span className="mono text-xs font-medium text-fg [overflow-wrap:anywhere]">{r.name}</span>
                    <span className="text-2xs text-fg-subtle">
                      aus <RelPath rel={r.library} className="text-2xs" />
                    </span>
                  </>
                )}
                itemKey={(r) => `${r.kind}:${r.name}`}
              />
            )}
            {result.errors.length > 0 && (
              <IssueSection
                tone="danger"
                title={plural(result.errors.length, 'Fehler', 'Fehler')}
                items={result.errors}
                render={(e) => (
                  <>
                    <RelPath rel={e.rel} className="text-xs" />
                    <span className="text-2xs text-danger-text">{cleanErrorText(e.message)}</span>
                  </>
                )}
                itemKey={(e) => e.rel}
              />
            )}
          </div>
        )}
        <NextSteps libraries={result.libraries} folder={run.target} converted={Boolean(result.conversion)} onReset={onReset} onRescan={onRescan} />
      </div>
    </motion.section>
  )
}

function groupConflicts(list: ImportConflict[]): { reason: string; items: ImportConflict[] }[] {
  const map = new Map<string, ImportConflict[]>()
  for (const c of list) map.set(c.reason, [...(map.get(c.reason) ?? []), c])
  return [...map.entries()].map(([reason, items]) => ({ reason, items }))
}

const ISSUE_TONE = {
  info: { box: 'border-info/25 bg-info/[0.035]', icon: 'text-info-text' },
  warning: { box: 'border-warning/25 bg-warning/[0.035]', icon: 'text-warning-text' },
  danger: { box: 'border-danger/25 bg-danger/[0.035]', icon: 'text-danger-text' },
} as const

/** Aufklappbare Ergebnisliste (wenige Einträge offen, viele zu) mit „weitere anzeigen“ */
function IssueSection<T>({
  tone,
  title,
  hint,
  items,
  render,
  itemKey,
}: {
  tone: 'info' | 'warning' | 'danger'
  title: string
  hint?: string
  items: T[]
  render: (item: T) => ReactNode
  itemKey: (item: T) => string
}) {
  const [open, setOpen] = useState(items.length <= 5)
  const [limit, setLimit] = useState(ISSUE_PAGE)
  const shown = items.slice(0, limit)
  const rest = items.length - shown.length
  const Icon = tone === 'danger' ? CircleX : tone === 'info' ? Info : CircleAlert
  return (
    <section className={cn('overflow-hidden rounded-card border', ISSUE_TONE[tone].box)}>
      <h3>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-ui font-medium text-fg outline-none focus-ring-inset"
        >
          <Icon aria-hidden className={cn('size-4 shrink-0', ISSUE_TONE[tone].icon)} />
          <span className="min-w-0 flex-1">{title}</span>
          <span className="flex shrink-0 items-center gap-1 text-xs font-normal text-fg-muted">
            {open ? 'Ausblenden' : 'Anzeigen'}
            <ChevronDown aria-hidden className={cn('size-3.5 transition-transform', open && 'rotate-180')} />
          </span>
        </button>
      </h3>
      {open && (
        <div className="border-t border-line">
          {hint && <p className="px-3.5 pt-2.5 text-xs text-fg-muted">{hint}</p>}
          <ul className="flex max-h-80 flex-col divide-y divide-line overflow-y-auto px-3.5 py-1">
            {shown.map((item) => (
              <li key={itemKey(item)} className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1.5">
                {render(item)}
              </li>
            ))}
          </ul>
          {rest > 0 && (
            <div className="flex items-center gap-3 border-t border-line px-3.5 py-2 text-2xs text-fg-subtle">
              <Button size="xs" variant="ghost" onClick={() => setLimit((l) => l + ISSUE_PAGE * 4)}>
                {formatNumber(Math.min(rest, ISSUE_PAGE * 4))} weitere anzeigen
              </Button>
              {formatNumber(shown.length)} von {formatNumber(items.length)}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/** Ergebnis des Angleichens an den Hausstil (Option „An den Hausstil angleichen“) */
function ConversionCard({ conversion }: { conversion: NonNullable<ImportRunResult['conversion']> }) {
  const navigate = useNavigate()
  const problems = [
    ...conversion.errors.map((e) => ({ ...e, error: true })),
    ...conversion.skipped.map((s) => ({ ...s, error: false })),
  ]
  return (
    <Card>
      <CardHeader
        icon={<PaintbrushVertical />}
        title="An den Hausstil angeglichen"
        titleAs="h3"
        description={formatNumbersInText(conversion.message) || `${plural(conversion.components, 'Bauteil', 'Bauteile')} angeglichen`}
        actions={
          conversion.undo ? (
            <Button size="sm" variant="ghost" onClick={() => navigate('/stapelbearbeitung')}>
              Rückgängig …
            </Button>
          ) : undefined
        }
      />
      {problems.length > 0 && (
        <CardContent>
          <ul className="flex flex-col gap-1 text-xs">
            {problems.slice(0, 20).map((p) => (
              <li key={`${p.error ? 'e' : 's'}:${p.library}`} className="flex flex-wrap items-baseline gap-x-2">
                <RelPath rel={p.library} className="text-xs" />
                <span className={p.error ? 'text-danger-text' : 'text-fg-muted'}>{cleanErrorText(p.message)}</span>
              </li>
            ))}
            {problems.length > 20 && <li className="text-fg-subtle">… und {formatNumber(problems.length - 20)} weitere</li>}
          </ul>
        </CardContent>
      )}
    </Card>
  )
}
