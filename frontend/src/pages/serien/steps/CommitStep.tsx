/**
 * Schritt 5 – Erzeugen: Zusammenfassung und Modus für vorhandene Bauteile (überspringen/aktualisieren), Start als
 * Hintergrundjob (POST /api/series/commit), Fortschritt und Protokoll (`useJob`), danach der Erfolgsbildschirm mit
 * „In Tabelle anzeigen“ und „Neue Serie“.
 *
 * Fortschritt, Abschnitte und Protokoll kommen vom Backend: `job.detail` (`SeriesCommitDetail`: Phase plan → symbol →
 * footprints → backup → parts → done mit Zählern), jede Phase ist eine Logzeile, die Schlussmeldung steht in
 * `job.message`/`result.message`. Solange der Schritt den Job zeigt, gehört er nicht in die Pille des Job-Docks
 * (`useInlineJob`) – verlässt man ihn mitten im Lauf, übernimmt das Dock samt Abschluss-Toast.
 */
import { motion } from 'motion/react'
import {
  ArrowLeft,
  CircleSlash,
  CircuitBoard,
  Component,
  DatabaseBackup,
  Info,
  Play,
  RefreshCw,
  SkipForward,
  Square,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useRef, type ReactNode } from 'react'
import { ApiError, cleanErrorText, errorMessage } from '@/api/client'
import { jobCancelText, jobDetail, useInlineJob, useJob } from '@/api/jobs'
import type {
  CommitMode,
  SeriesCommitDetail,
  SeriesCommitPhase,
  SeriesCommitResult,
  SeriesFootprintRef,
  SeriesJob,
  SeriesPreview,
  SeriesTemplate,
} from '@/api/series'
import { useCancelJob } from '@/api/system'
import { Button, Callout, Kbd, ProgressRing, SegmentedControl, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, formatNumbersInText, formatPercent, plural } from '@/lib/format'
import { focusWhenReady } from '../components/focus'
import { StepHeading } from '../components/StepHeading'
import { nameReasonTopic } from '../model/footprint'
import type { JobContextInfo, JobPlan } from '../model/store'
import { JobLog } from './commit/JobLog'
import { SuccessView, TemplateTrustNote } from './commit/SuccessView'
import { FootprintName } from './preview/FootprintName'

export interface CommitStepProps {
  template: SeriesTemplate
  categoryLabel: string
  preview: SeriesPreview | undefined
  previewError: unknown
  mode: CommitMode
  onModeChange: (mode: CommitMode) => void
  job: JobContextInfo | null
  starting: boolean
  startError: unknown
  /** läuft gerade eine andere Serie (Titel) – dann kein zweiter Start */
  busyWith: string | null
  onStart: () => void
  onBack: () => void
  onShowTable: () => void
  onNewSeries: () => void
}

/** Abschnitte des Serien-Jobs (`SeriesCommitDetail.phase`, series.py `_write`) */
const PHASES: { id: SeriesCommitPhase; label: string; running: string }[] = [
  { id: 'plan', label: 'Berechnen', running: 'Serie wird berechnet' },
  { id: 'symbol', label: 'Symbol', running: 'Symbol wird angelegt' },
  { id: 'footprints', label: 'Footprints', running: 'Footprints werden angelegt' },
  { id: 'backup', label: 'Sicherung', running: 'Sicherung wird angelegt' },
  { id: 'parts', label: 'Bauteile', running: 'Bauteile werden gespeichert' },
]

type PhaseState = 'done' | 'active' | 'todo' | 'failed' | 'stopped' | 'skipped'

const PHASE_STATE_TEXT: Record<PhaseState, string> = {
  done: 'erledigt',
  active: 'läuft',
  todo: 'ausstehend',
  failed: 'fehlgeschlagen',
  stopped: 'abgebrochen',
  skipped: 'nicht nötig',
}

function Stat({ label, value, hint }: { label: string; value: number; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5 bg-surface px-5 py-4">
      <span className="micro-label">{label}</span>
      <span className={cn('mono text-metric font-semibold tracking-[-0.02em]', value ? 'text-fg' : 'text-fg-subtle')}>
        {formatNumber(value)}
      </span>
      {hint && <span className="truncate text-2xs text-fg-subtle">{hint}</span>}
    </div>
  )
}

function Row({ icon, children, muted }: { icon: ReactNode; children: ReactNode; muted?: boolean }) {
  return (
    <li className={cn('flex items-start gap-3 px-5 py-3 text-ui', muted ? 'text-fg-muted' : 'text-fg')}>
      <span aria-hidden className="mt-0.5 flex size-5 shrink-0 items-center justify-center text-fg-subtle [&_svg]:size-4">
        {icon}
      </span>
      <div className="min-w-0 flex-1">{children}</div>
    </li>
  )
}

/** Index der laufenden Phase (`done` = alle erledigt, -1 = noch keine) */
function phaseIndex(detail: Partial<SeriesCommitDetail>): number {
  if (detail.phase === 'done') return PHASES.length
  return PHASES.findIndex((p) => p.id === detail.phase)
}

/** Zustand eines Abschnitts aus Phase und Jobstatus; Abschnitte ohne Arbeit (alle Footprints vorhanden) „nicht nötig“ */
function phaseState(i: number, current: number, job: SeriesJob | undefined, plan: JobPlan): PhaseState {
  const id = PHASES[i].id
  const idle = id === 'footprints' && plan.footprints === 0
  const failed = job?.status === 'failed'
  const stopped = job?.status === 'cancelled'
  // vor dem ersten Schnappschuss mit Phase: das Berechnen läuft
  const at = current < 0 && !failed && !stopped ? 0 : current
  if (i < at) return idle ? 'skipped' : 'done'
  if (i === at) {
    if (failed) return 'failed'
    if (stopped) return 'stopped'
    return idle ? 'skipped' : 'active'
  }
  return idle ? 'skipped' : 'todo'
}

/** Zweite Zeile eines Abschnitts: Zähler der laufenden Phase bzw. was erledigt ist (Plan aus der Vorschau) */
function phaseNote(i: number, state: PhaseState, detail: Partial<SeriesCommitDetail>, plan: JobPlan): string {
  const id = PHASES[i].id
  const counter =
    state === 'active' && typeof detail.total === 'number' && detail.total > 0
      ? `${formatNumber(detail.done ?? 0)} / ${formatNumber(detail.total)}`
      : null
  switch (id) {
    case 'plan':
      return state === 'done' ? plural(plan.rows, 'Zeile', 'Zeilen') : state === 'active' ? 'läuft …' : ''
    case 'symbol':
      return plan.symbol ? `${plan.symbol}${plan.symbolExists ? '' : ' · neu'}` : '–'
    case 'footprints':
      if (state === 'skipped') return 'alle vorhanden'
      // neue laut Vorschau (das Backend gleicht beim Anlegen auch vorhandene ab – der Zähler der Phase zählt sie mit)
      return counter ?? `${formatNumber(plan.footprints)} neu`
    case 'backup':
      return state === 'done' ? 'angelegt' : state === 'active' ? 'läuft …' : 'vor dem Schreiben'
    default:
      return counter ?? (state === 'done' ? `${formatNumber(plan.writes)} gespeichert` : plural(plan.writes, 'Bauteil', 'Bauteile'))
  }
}

function JobProgress({
  info,
  job,
  starting,
  busyWith,
  onStart,
  onBack,
}: {
  info: JobContextInfo
  job: SeriesJob | undefined
  starting: boolean
  busyWith: string | null
  onStart: () => void
  onBack: () => void
}) {
  const cancel = useCancelJob()
  const headingRef = useRef<HTMLHeadingElement>(null)
  const failed = job?.status === 'failed'
  const cancelled = job?.status === 'cancelled'
  const queued = !job || job.status === 'queued'
  const running = !job || job.status === 'queued' || job.status === 'running'
  const stopping = running && Boolean(job?.cancel_requested)
  const progress = job?.progress ?? 0
  const detail = jobDetail<SeriesCommitDetail>(job)
  const current = phaseIndex(detail)
  const states = PHASES.map((_, i) => phaseState(i, current, job, info.plan))
  const activePhase = states.indexOf('active')
  const log = job?.log ?? []
  // Fortschritt der laufenden Phase als letzte Protokollzeile (sonst steht „Zeile 1.801 von 3.686“ nur oben)
  const lastText = log.length ? log[log.length - 1].text : null
  const live = running && job?.message && job.message !== lastText ? job.message : null

  // Start: Fokus auf die Fortschrittsüberschrift (der Startknopf ist weg)
  useEffect(() => focusWhenReady(() => headingRef.current), [info.id])

  const headline = failed
    ? 'Erzeugen fehlgeschlagen'
    : cancelled
      ? 'Abgebrochen'
      : stopping
        ? 'Wird abgebrochen …'
        : queued
          ? 'Wartet auf den Start …'
          : 'Serie wird erzeugt …'
  const message = failed
    ? cleanErrorText(job?.error ?? 'Unbekannter Fehler')
    : cancelled && job
      ? `${jobCancelText(job)} Schon angelegte Symbole und Footprints bleiben erhalten – die Vorschau zeigt den aktuellen Stand.`
      : formatNumbersInText(job?.message || 'Wird vorbereitet …')
  /** Ansage für Screenreader: Abschnitt bzw. Ergebnis – nicht jede Zahl des Fortschritts */
  const announcement = failed || cancelled ? `${headline}. ${message}` : activePhase >= 0 ? `${PHASES[activePhase].running} …` : headline

  return (
    <section aria-labelledby="serien-job" className="flex w-full flex-col">
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      <div className="@container relative overflow-hidden rounded-panel border border-line bg-surface shadow-raised">
        {running && (
          <motion.div
            aria-hidden
            className="pointer-events-none absolute -left-24 -top-24 size-80 rounded-full bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]"
            animate={{ opacity: [0.55, 0.9, 0.55] }}
            transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
          />
        )}
        <div className="relative flex flex-col items-start gap-5 px-6 py-6 @[44rem]:flex-row @[44rem]:items-center">
          <ProgressRing
            value={progress}
            size={112}
            stroke={7}
            tone={failed ? 'danger' : cancelled ? 'neutral' : 'accent'}
            indeterminate={queued}
            label="Fortschritt der Serie"
            valueText={queued ? 'wartet' : undefined}
          >
            <span className="mono text-h3 font-semibold tabular-nums text-fg">
              {failed ? '!' : cancelled ? '–' : formatPercent(progress).replace(/\s/g, ' ')}
            </span>
          </ProgressRing>
          <div className="min-w-0 flex-1">
            <div className="micro-label">{info.title}</div>
            <h2
              id="serien-job"
              ref={headingRef}
              tabIndex={-1}
              className="mt-1 text-h3 font-semibold tracking-[-0.02em] text-fg outline-none"
            >
              {headline}
            </h2>
            <p className={cn('mt-1 max-w-3xl text-ui', failed ? 'text-danger-text' : 'text-fg-muted')}>{message}</p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            {running ? (
              <Button
                variant="secondary"
                leftIcon={<Square />}
                loading={cancel.isPending || stopping}
                disabled={!job || stopping}
                onClick={() => job && cancel.mutate(job.id)}
              >
                {stopping ? 'Wird abgebrochen' : 'Abbrechen'}
              </Button>
            ) : (
              <>
                <Button variant="ghost" leftIcon={<ArrowLeft />} onClick={onBack}>
                  Zur Vorschau
                </Button>
                <Button variant="secondary" leftIcon={<RefreshCw />} onClick={onStart} loading={starting} disabled={Boolean(busyWith)}>
                  Erneut starten
                </Button>
              </>
            )}
          </div>
        </div>
        <ol aria-label="Ablauf" className="relative grid grid-cols-5 gap-px border-t border-line bg-line">
          {PHASES.map((ph, i) => {
            const state = states[i]
            const note = phaseNote(i, state, detail, info.plan)
            return (
              <li key={ph.id} aria-current={state === 'active' ? 'step' : undefined} className="flex min-w-0 flex-col gap-1 bg-surface px-4 py-3">
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className={cn(
                      'size-2 shrink-0 rounded-full',
                      state === 'done' && 'bg-success',
                      state === 'active' && 'animate-pulse bg-accent motion-reduce:animate-none',
                      state === 'failed' && 'bg-danger',
                      (state === 'stopped' || state === 'skipped') && 'bg-fg-subtle',
                      state === 'todo' && 'bg-line-strong',
                    )}
                  />
                  <span
                    className={cn(
                      'truncate text-xs font-medium',
                      state === 'todo' || state === 'skipped'
                        ? 'text-fg-subtle'
                        : state === 'failed'
                          ? 'text-danger-text'
                          : 'text-fg',
                    )}
                  >
                    {ph.label}
                    <span className="sr-only">{` – ${PHASE_STATE_TEXT[state]}`}</span>
                  </span>
                </span>
                <span className={cn('mono truncate pl-4 text-2xs tabular-nums', state === 'active' ? 'text-fg-muted' : 'text-fg-subtle')}>
                  {note || '\u00a0'}
                </span>
              </li>
            )
          })}
        </ol>
        <div className="relative border-t border-line px-6 py-4">
          <div className="mb-2 flex items-baseline justify-between gap-3">
            <h3 className="micro-label">Protokoll</h3>
            {log.length > 0 && <span className="text-2xs text-fg-subtle">{plural(log.length, 'Eintrag', 'Einträge')}</span>}
          </div>
          <JobLog
            entries={log}
            live={live}
            emptyText={queued ? 'Der Job wartet auf den Start …' : 'Noch keine Einträge …'}
            className="h-56"
          />
        </div>
      </div>
    </section>
  )
}

export function CommitStep({
  template,
  categoryLabel,
  preview,
  previewError,
  mode,
  onModeChange,
  job: jobInfo,
  starting,
  startError,
  busyWith,
  onStart,
  onBack,
  onShowTable,
  onNewSeries,
}: CommitStepProps) {
  const { job } = useJob<SeriesCommitResult>(jobInfo?.id)
  // Fortschritt und Ergebnis stehen hier – solange der Schritt sichtbar ist, nicht in der Pille und ohne Toast
  useInlineJob(jobInfo?.id)
  const headingRef = useRef<HTMLHeadingElement>(null)
  const done = job?.status === 'done' && job.result

  // Erfolg: Fokus auf das Ergebnis
  useEffect(() => {
    if (done) headingRef.current?.focus({ preventScroll: true })
  }, [done])

  if (jobInfo && job?.status === 'done' && job.result) {
    const duration = job.started && job.finished ? job.finished - job.started : null
    return (
      <section aria-label="Ergebnis" className="flex w-full flex-col">
        <SuccessView
          result={job.result}
          title={jobInfo.title}
          template={template.id === jobInfo.templateId ? template : null}
          categoryLabel={categoryLabel}
          duration={duration}
          log={job.log}
          onShowTable={onShowTable}
          onNewSeries={onNewSeries}
          onRetry={onStart}
          headingRef={headingRef}
        />
      </section>
    )
  }

  if (jobInfo) {
    return <JobProgress info={jobInfo} job={job} starting={starting} busyWith={busyWith} onStart={onStart} onBack={onBack} />
  }

  // ------------------------------------------------------------------ vor dem Start
  const counts = preview?.counts ?? {}
  const created = counts.new ?? 0
  const existing = counts.exists ?? 0
  const blocked = (counts.conflict ?? 0) + (counts.invalid ?? 0)
  const writes = created + (mode === 'update' ? existing : 0)
  const needed = preview?.footprints_needed ?? []
  const busy = startError instanceof ApiError && startError.isLibraryBusy
  /** Footprints mit Kennung im Namen (`_4328`): eigenes Land Pattern – der Grund steht beim Footprint */
  const marked = needed.filter((f) => f.name_reason)

  return (
    <section aria-labelledby="serien-erzeugen" className="flex flex-col gap-5">
      <StepHeading
        id="serien-erzeugen"
        title="Erzeugen"
        description={`${template.title} → ${categoryLabel}. PartForge legt zuerst eine Sicherung an, dann Symbol, Footprints und Bauteile.`}
      />
      {!preview ? (
        previewError ? (
          <Callout tone="danger" urgent title="Vorschau nicht möglich">
            {errorMessage(previewError)}
          </Callout>
        ) : (
          <Skeleton className="h-80 rounded-panel" />
        )
      ) : (
        <div className="grid grid-cols-1 items-start gap-5 @[64rem]:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="overflow-hidden rounded-panel border border-line bg-surface shadow-card">
            <div className="grid grid-cols-3 gap-px border-b border-line bg-line">
              <Stat label="Neu" value={created} hint={`Kategorie ${categoryLabel}`} />
              <Stat
                label="Vorhanden"
                value={existing}
                hint={existing ? (mode === 'update' ? 'werden aktualisiert' : 'werden übersprungen') : undefined}
              />
              <Stat label="Footprints neu" value={needed.length} hint={needed.length ? 'nach IPC-7351B' : 'alle vorhanden'} />
            </div>
            <ul className="divide-y divide-line">
              {existing > 0 && (
                <Row icon={mode === 'update' ? <RefreshCw /> : <SkipForward />}>
                  <div className="flex flex-col gap-2.5 @[40rem]:flex-row @[40rem]:items-center @[40rem]:justify-between">
                    <span>
                      <span className="mono font-semibold">{formatNumber(existing)}</span>{' '}
                      {existing === 1 ? 'Bauteil ist' : 'Bauteile sind'} schon vorhanden
                    </span>
                    <SegmentedControl<CommitMode>
                      size="sm"
                      aria-label="Vorhandene Bauteile"
                      value={mode}
                      onValueChange={onModeChange}
                      options={[
                        { value: 'skip', label: 'Überspringen' },
                        { value: 'update', label: 'Aktualisieren' },
                      ]}
                    />
                  </div>
                  <p className="mt-1.5 text-xs text-fg-muted">
                    {mode === 'update'
                      ? 'Werte und Texte werden erneuert. Freigabestatus, ein abweichender Lebenszyklus, Datenblatt-Link, Symbol und Footprint bleiben erhalten.'
                      : 'Vorhandene Bauteile bleiben unverändert.'}
                  </p>
                </Row>
              )}
              {blocked > 0 && (
                <Row icon={<CircleSlash />} muted>
                  {plural(blocked, 'Zeile wird', 'Zeilen werden')} nicht angelegt (
                  {[
                    counts.conflict ? plural(counts.conflict, 'Konflikt', 'Konflikte') : null,
                    counts.invalid ? `${formatNumber(counts.invalid)} ungültig` : null,
                  ]
                    .filter(Boolean)
                    .join(', ')}
                  ) – Gründe stehen in der Vorschau.
                </Row>
              )}
              <Row icon={<CircuitBoard />} muted={!needed.length}>
                {needed.length ? (
                  <>
                    {plural(needed.length, 'Footprint wird', 'Footprints werden')} erzeugt:{' '}
                    <FootprintList footprints={needed} />
                    {marked.length > 0 && (
                      <p className="mt-1.5 flex items-start gap-1.5 text-xs text-fg-muted">
                        <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
                        <span>{markedText(marked, needed.length)}</span>
                      </p>
                    )}
                  </>
                ) : (
                  'Alle Footprints sind schon vorhanden.'
                )}
              </Row>
              <Row icon={<Component />}>
                {preview.symbol ? (
                  <>
                    Symbol <span className="mono">{preview.symbol.name}</span>{' '}
                    {preview.symbol.exists ? '– vorhanden, wird verwendet' : '– wird angelegt'}
                  </>
                ) : (
                  <span className="text-warning-text">Kein sicheres Symbol – es wird nichts angelegt.</span>
                )}
              </Row>
              <Row icon={<DatabaseBackup />} muted>
                Vor dem Schreiben sichert PartForge die Datenbank (Ordner „Backups“).
              </Row>
            </ul>
            {(!template.verified || !template.availability_certain) && (
              <div className="border-t border-line px-5 py-3">
                <TemplateTrustNote verified={template.verified} availabilityCertain={template.availability_certain} />
              </div>
            )}
            {startError ? (
              <div className="border-t border-line px-5 py-3">
                {busy ? (
                  <Callout
                    tone="warning"
                    title="Die Bibliothek wird gerade geschrieben"
                    actions={
                      <Button size="sm" variant="secondary" leftIcon={<RefreshCw />} loading={starting} onClick={onStart}>
                        Erneut versuchen
                      </Button>
                    }
                  >
                    Ein anderer Vorgang schreibt gerade in die Bibliothek. In einigen Sekunden erneut versuchen.
                  </Callout>
                ) : (
                  <Callout tone="danger" title="Serie konnte nicht gestartet werden" urgent>
                    {cleanErrorText(errorMessage(startError))}
                  </Callout>
                )}
              </div>
            ) : null}
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface-2/40 px-5 py-4">
              <span className={cn('text-xs', busyWith ? 'text-warning-text' : 'text-fg-muted')} aria-live="polite">
                {busyWith
                  ? `„${busyWith}“ wird gerade erzeugt – danach kann diese Serie starten.`
                  : writes
                    ? `${plural(writes, 'Bauteil wird', 'Bauteile werden')} geschrieben.`
                    : 'Nichts zu schreiben – alle Bauteile sind schon vorhanden.'}
              </span>
              <div className="ml-auto flex items-center gap-2.5">
                <Kbd hotkey="mod+enter" />
                <Button
                  variant="primary"
                  size="lg"
                  leftIcon={<Play />}
                  loading={starting}
                  disabled={!writes || !preview.symbol || Boolean(busyWith)}
                  aria-keyshortcuts="Control+Enter"
                  onClick={onStart}
                >
                  Serie erzeugen
                </Button>
              </div>
            </div>
          </div>
          <section aria-label="So läuft es ab" className="rounded-panel border border-line bg-surface/60 p-5">
            <h3 className="micro-label">So läuft es ab</h3>
            <ol className="mt-3 flex flex-col gap-3">
              {[
                ['Sicherung', 'Kopie der Datenbank vor jeder Änderung.'],
                ['Symbol', 'Standardsymbol der Kategorie – nie geraten.'],
                ['Footprints', 'IPC-7351B im Hausstil, in die PcbLib der Familie.'],
                ['Bauteile', 'Werte wie bei der Handeingabe, Texte aus den Vorlagen.'],
                ['Altium Designer', 'sieht die neuen Bauteile nach der Aktualisierung.'],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="mono flex size-5 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface-2 text-2xs text-fg-muted">
                    {i + 1}
                  </span>
                  <span className="min-w-0 text-xs leading-relaxed text-fg-muted">
                    <span className="font-medium text-fg">{t}</span> – {d}
                  </span>
                </li>
              ))}
            </ol>
            {blocked > 0 && (
              <p className="mt-4 flex gap-2 text-xs text-warning-text">
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                Konflikte und ungültige Zeilen werden ausgelassen.
              </p>
            )}
          </section>
        </div>
      )}
    </section>
  )
}


/** „3 davon mit Kennung im Namen: eigene Land Patterns statt der Standard-Footprints (Footprint-Höhe „Exakt“).“ */
function markedText(marked: SeriesFootprintRef[], total: number): string {
  const topics = [...new Set(marked.map((f) => nameReasonTopic(f.name_reason ?? '')))].slice(0, 2).join('; ')
  if (total === 1) return `Mit Kennung im Namen: ein eigenes Land Pattern statt des Standard-Footprints (${topics}).`
  const who = marked.length === total ? 'Alle' : `${formatNumber(marked.length)} davon`
  return `${who} mit Kennung im Namen: eigene Land Patterns statt der Standard-Footprints (${topics}).`
}

/** Die ersten Footprint-Namen (Kennung gedämpft, Grund als Tooltip), Rest als „+ n weitere“ */
function FootprintList({ footprints }: { footprints: SeriesFootprintRef[] }) {
  const shown = footprints.slice(0, 4)
  return (
    <span className="mono text-xs text-fg-muted">
      {shown.map((f, i) => (
        <span key={f.name}>
          {f.name_reason ? (
            <Tooltip content={<span className="block max-w-sm font-sans">{f.name_reason}</span>}>
              <span className="cursor-help rounded-sm underline decoration-dotted decoration-fg-subtle underline-offset-2">
                <FootprintName footprint={f} />
              </span>
            </Tooltip>
          ) : (
            <FootprintName footprint={f} />
          )}
          {i < shown.length - 1 ? ', ' : ''}
        </span>
      ))}
      {footprints.length > shown.length ? (
        <span className="font-sans"> und {plural(footprints.length - shown.length, 'weiterer', 'weitere')}</span>
      ) : null}
    </span>
  )
}
