import { useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { ArrowLeft, Check, CircleStop, FileScan, ListChecks, Sparkles } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { cleanErrorText } from '@/api/client'
import {
  datasheetKeys,
  jobDatasheetId,
  jobExtractionSummary,
  useAiStatus,
  useCostEstimate,
  useDatasheet,
  useDatasheets,
  type ImportJobResult,
} from '@/api/datasheets'
import { jobCancelText, useInlineJob, useJob } from '@/api/jobs'
import { JOB_CANCEL_LIBRARY_SWITCH, useCancelJob, type Job } from '@/api/system'
import { PageBody, PageTitle } from '@/app/page'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import { Button, Callout, EmptyState, ProgressBar, Skeleton } from '@/components/ui'
import { useCountUp } from '@/lib/useCountUp'
import { cn } from '@/lib/cn'
import { formatDuration, formatNumber, formatNumbersInText, plural } from '@/lib/format'
import { analyzeJob, cleanJobError, jobElapsed, type AnalysisCounters, type AnalysisProgress } from '../lib/analysis'
import { effortLabel, estimateText, formatUsd, runLabel } from '../lib/format'
import { importPath, useImportActions } from '../lib/useImportActions'
import { ReanalyzeDialog } from '../shared/ReanalyzeDialog'
import { useNow } from '../shared/useDebounced'
import { useScrollTabStop } from '../shared/useScrollTabStop'
import { useActiveImports, useReviewDrafts } from '../store'
import { JobLog } from './JobLog'
import { PageMosaic } from './PageMosaic'
import { StepTimeline } from './StepTimeline'

const CELEBRATE_MS = 1100

/**
 * Was die Live-Region (höflich) ansagt: der Schritt beim Wechsel („Schritt 3 von 6: Bauteile und Pins“) und das Ende
 * (Schlusssatz des Backends). Hängt nur von Status und Schritt ab – Zähler und Kosten lösen keine Ansage aus.
 */
function announcementOf(job: Job<ImportJobResult> | undefined, progress: AnalysisProgress, celebrating: boolean): string {
  if (!job) return ''
  if (job.status === 'done' || celebrating) {
    const text = formatNumbersInText(job.message || '')
    return progress.loadOnly ? `Datenblatt geladen. ${text}` : text || 'Analyse abgeschlossen.'
  }
  if (job.status === 'cancelled') return 'Analyse abgebrochen.'
  if (job.status === 'failed') return '' // die Fehlermeldung meldet sich selbst (role="alert")
  const index = progress.steps.findIndex((s) => s.state === 'active')
  if (index < 0) return ''
  return `Schritt ${index + 1} von ${progress.steps.length}: ${progress.steps[index].label}`
}

/**
 * Laufende (oder gerade beendete) Analyse: Funkenrahmen, Schritte, Seiten und Zähler aus `job.detail` (das Protokoll
 * ergänzt nur), Seiten, die aufleuchten, sobald Claude sie liest, laufende Kosten. Fertig → Prüfansicht; Fehler →
 * Ursache, Kosten, erneut versuchen (mit geschätzten Kosten vom Backend).
 */
export function AnalysisView({ jobId, datasheetId }: { jobId: string; datasheetId: string | null }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const reduce = useReducedMotion()
  const cancel = useCancelJob()
  const actions = useImportActions()
  const ai = useAiStatus().data
  const urlEntry = useActiveImports((s) => s.urls.find((u) => u.jobId === jobId))
  const wasActive = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [celebrating, setCelebrating] = useState(false)
  const [retryOpen, setRetryOpen] = useState(false)
  /** Ergebnis für eine inzwischen geschlossene Bibliothek gesichert (`stored: 'pending'`) */
  const [keptElsewhere, setKeptElsewhere] = useState<string | null>(null)
  const guessedRef = useRef<string | null>(null)

  const { job, isActive, error } = useJob<ImportJobResult>(jobId, {
    onDone: (j) => {
      const id = jobDatasheetId(j.result) ?? datasheetId ?? guessedRef.current
      const store = useActiveImports.getState()
      if (id) store.finish(id, jobId)
      store.finishUrl(jobId)
      if (!id) return
      const summary = jobExtractionSummary(j.result)
      // URL-Import: nur geladen – jetzt entscheiden (vorhandenes Ergebnis oder Analyse starten). Nur, wenn der Download
      // hier miterlebt wurde: ein späterer Besuch der Adresse startet nie unbemerkt eine bezahlte Analyse.
      if (!summary && !datasheetId) {
        if (wasActive.current) void actions.continueAfterDownload(id)
        else navigate(importPath(id), { replace: true })
        return
      }
      // die Bibliothek wurde inzwischen gewechselt: Ergebnis liegt in ihrem Ordner, hier gibt es keine Prüfansicht
      if (summary?.stored === 'pending') {
        setKeptElsewhere(formatNumbersInText(j.message || summary.message || ''))
        return
      }
      // eine hier miterlebte neue Analyse ist eine neue Ausgangslage: frühere Entscheidungen und Bestätigungen verwerfen
      if (wasActive.current) useReviewDrafts.getState().reset(id)
      const go = () => navigate(`/import?ds=${encodeURIComponent(id)}`, { replace: true })
      if (wasActive.current && !reduce) {
        setCelebrating(true)
        timer.current = setTimeout(go, CELEBRATE_MS)
      } else go()
    },
    onFailed: () => {
      const store = useActiveImports.getState()
      if (datasheetId) store.finish(datasheetId, jobId)
      store.finishUrl(jobId)
      // Fehlerursache und bezahlte Anfragen stehen jetzt im Datenblatt (Liste, Fehleransicht)
      void qc.invalidateQueries({ queryKey: datasheetKeys.all })
    },
    onCancelled: () => {
      const store = useActiveImports.getState()
      if (datasheetId) store.finish(datasheetId, jobId)
      store.finishUrl(jobId)
      void qc.invalidateQueries({ queryKey: datasheetKeys.all })
    },
  })
  // Diese Ansicht zeigt den Job selbst: nicht in der Pille des Job-Docks, kein Toast. Wird sie verlassen, solange er
  // läuft, übernimmt das Dock (mit Abschluss-Toast).
  useInlineJob(jobId)
  useEffect(() => {
    if (isActive) wasActive.current = true
  }, [isActive])
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current)
    },
    [],
  )

  const progress = useMemo(() => analyzeJob(job, { urlJob: !datasheetId }), [job, datasheetId])
  // Zähler bleiben stehen, auch wenn ein Schnappschuss (Rückfall ohne `detail`) sie nicht nennt
  const [peak, setPeak] = useState<{ job: string; counters: AnalysisCounters }>({ job: jobId, counters: {} })
  const counters = peak.job === jobId ? mergeCounters(peak.counters, progress.counters) : progress.counters
  if (peak.job !== jobId || !sameCounters(counters, peak.counters)) setPeak({ job: jobId, counters })

  // URL-Import: Datenblatt-ID aus `detail.datasheet_id` (sobald das PDF gespeichert ist); ältere Jobs: in der Liste suchen
  const list = useDatasheets()
  const downloadName = progress.download?.name
  const needsGuess = !datasheetId && !progress.datasheetId && !jobDatasheetId(job?.result)
  useEffect(() => {
    if (needsGuess && downloadName) void qc.invalidateQueries({ queryKey: datasheetKeys.list })
  }, [needsGuess, downloadName, qc, progress.pageCount])
  const guessed = useMemo(() => {
    if (datasheetId) return datasheetId
    const known = progress.datasheetId ?? jobDatasheetId(job?.result)
    if (known) return known
    const url = urlEntry?.url ?? progress.download?.url
    if (!downloadName && !url) return null
    const hit = (list.data ?? []).find((d) => (url && d.source_url === url) || (downloadName && d.original_name === downloadName))
    return hit?.id ?? null
  }, [datasheetId, progress.datasheetId, job?.result, urlEntry?.url, progress.download?.url, downloadName, list.data])
  useEffect(() => {
    guessedRef.current = guessed
  }, [guessed])

  const ds = useDatasheet(guessed)
  // Seitenmaße stehen nach dem Lesen der Textebene bereit
  useEffect(() => {
    if (guessed && progress.pageCount) void qc.invalidateQueries({ queryKey: datasheetKeys.detail(guessed) })
  }, [guessed, progress.pageCount, qc])

  const aspects = useMemo(
    () => new Map((ds.data?.pages ?? []).filter((p) => p.height_pt > 0).map((p) => [p.page, p.width_pt / p.height_pt])),
    [ds.data?.pages],
  )
  const pageCount = progress.pageCount || ds.data?.page_count || 0
  const now = useNow(isActive)
  const elapsed = jobElapsed(job, now)

  const failed = job?.status === 'failed'
  const cancelled = job?.status === 'cancelled'
  const done = job?.status === 'done'
  const switched = cancelled && job?.cancel_reason === JOB_CANCEL_LIBRARY_SWITCH
  const label =
    runLabel(progress.modelLabel) ||
    (ai ? `${ai.model_label || modelDisplayName(ai.model)} · Gründlichkeit ${effortLabel(ai.effort)}` : '')
  const budget = progress.budgetUsd ?? ai?.max_cost_per_import_usd ?? null
  const cost = progress.finalCostUsd ?? progress.costUsd
  const name = progress.fileName ?? ds.data?.original_name ?? urlEntry?.url ?? 'Datenblatt'
  const currentStep = progress.steps.find((s) => s.state === 'active')
  // „Erneut analysieren“ kostet erneut – die erwarteten Kosten (Schätzung des Backends) stehen am Knopf
  const canRetry = Boolean(guessed && actions.aiReady && (failed || cancelled) && !progress.loadOnly)
  const retryEstimate = useCostEstimate(guessed, null, { enabled: canRetry })
  const retryCost = retryEstimate.data ? estimateText(retryEstimate.data) : null

  const title = failed
    ? progress.loadOnly
      ? 'Download fehlgeschlagen'
      : 'Analyse fehlgeschlagen'
    : cancelled
      ? 'Abgebrochen'
      : progress.loadOnly
        ? done
          ? 'Datenblatt geladen – die Analyse startet …'
          : 'Datenblatt wird geladen'
        : done || celebrating
          ? 'Analyse abgeschlossen'
          : 'Claude liest das Datenblatt'
  const announcement = announcementOf(job, progress, celebrating)

  if (error && !job) {
    return (
      <PageBody width="narrow">
        <PageTitle title="Analyse" />
        <EmptyState
          illustration="search-empty"
          titleAs="h2"
          title="Diese Analyse ist nicht mehr verfügbar"
          description="PartForge wurde inzwischen neu gestartet oder der Job ist abgelaufen. Das Ergebnis einer abgeschlossenen Analyse steht in der Prüfansicht."
          actions={
            <>
              {datasheetId && (
                <Button asChild variant="secondary">
                  <Link to={importPath(datasheetId)}>
                    <ListChecks aria-hidden />Prüfansicht öffnen
                  </Link>
                </Button>
              )}
              <Button asChild variant="ghost">
                <Link to="/import">
                  <ArrowLeft aria-hidden />Zur Übersicht
                </Link>
              </Button>
            </>
          }
        />
      </PageBody>
    )
  }

  return (
    <PageBody width="wide" className="flex h-[calc(100dvh-var(--pf-topbar-height,3.5rem))] min-h-[36rem] flex-col pb-6 pt-4">
      <PageTitle
        title={(ds.data?.has_extraction && ds.data.title) || name}
        subtitle={failed ? 'Analyse fehlgeschlagen' : cancelled ? 'Analyse abgebrochen' : currentStep ? `Analyse · ${currentStep.label}` : 'Analyse'}
      />
      {/* Ansage für Screenreader: Schrittwechsel und Abschluss (höflich, ohne Zählerstände) */}
      <div aria-live="polite" aria-atomic="true" className="sr-only">
        {announcement}
      </div>
      <section
        aria-labelledby="analysis-title"
        aria-busy={isActive || undefined}
        className={cn(
          'relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-panel shadow-raised',
          isActive
            ? 'spark-border [--spark-fill:var(--pf-surface)]'
            : failed
              ? 'border border-danger/35 bg-surface'
              : cancelled
                ? 'border border-line-strong bg-surface'
                : 'spark-border-static [--spark-fill:var(--pf-surface)]',
        )}
      >
        {/* Funkenschein hinter dem Kopf – nur während der Analyse */}
        <div
          aria-hidden
          className={cn(
            'pointer-events-none absolute -top-40 left-1/3 size-[34rem] rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--pf-spark-b)_14%,transparent),transparent)] transition-opacity duration-700',
            isActive || celebrating ? 'opacity-100' : 'opacity-0',
          )}
        />

        <header className="relative flex flex-wrap items-start gap-4 border-b border-line px-5 py-4">
          <span
            aria-hidden
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-button [&_svg]:size-5',
              failed
                ? 'border border-danger/30 bg-danger/10 text-danger-text'
                : cancelled
                  ? 'border border-line-strong bg-surface-2 text-fg-muted'
                  : 'bg-gradient-spark text-on-spark shadow-[var(--pf-shadow-spark)]',
            )}
          >
            {done || celebrating ? <Check /> : failed || cancelled ? <FileScan /> : <Sparkles className={cn(isActive && 'animate-pulse-soft')} />}
          </span>
          <div className="min-w-0 flex-1">
            <div className="micro-label truncate">KI-Analyse{label ? ` · ${label}` : ''}</div>
            <h2 id="analysis-title" className="mt-0.5 text-h3 font-semibold tracking-[-0.02em] text-fg">
              {title}
            </h2>
            <p className="mt-0.5 truncate text-xs text-fg-muted">
              <span className="mono">{name}</span>
              {pageCount ? ` · ${plural(pageCount, 'Seite', 'Seiten')}` : ''}
              {progress.manufacturer ? ` · ${progress.manufacturer}` : ''}
              {progress.devicesText ? ` · ${progress.devicesText}` : ''}
            </p>
          </div>
          <dl className="flex shrink-0 items-stretch gap-5">
            <Metric label="Laufzeit" value={job ? formatDuration(Math.round(elapsed)) : '–'} />
            <div className="min-w-32">
              <dt className="micro-label">{done || failed || cancelled ? 'Kosten' : 'Kosten bisher'}</dt>
              <dd className="mono mt-0.5 text-md font-semibold text-fg tabular-nums">
                {formatUsd(cost)}
                {budget ? <span className="ml-1 text-2xs font-normal text-fg-subtle">von {formatUsd(budget)}</span> : null}
                {budget ? (
                  <ProgressBar
                    value={Math.min(cost, budget)}
                    max={budget}
                    size="xs"
                    tone="spark"
                    label="Anteil am Kostenlimit"
                    hideLabel
                    className="mt-1"
                  />
                ) : null}
              </dd>
            </div>
          </dl>
          {isActive && (
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<CircleStop />}
              loading={cancel.isPending || job?.cancel_requested}
              onClick={() => cancel.mutate(jobId)}
              className="self-center"
            >
              {job?.cancel_requested ? 'Wird abgebrochen …' : 'Abbrechen'}
            </Button>
          )}
        </header>

        {(failed || cancelled || keptElsewhere) && (
          <div className="relative border-b border-line px-5 py-3">
            {keptElsewhere ? (
              <Callout tone="info" title="Ergebnis für die andere Bibliothek gesichert">
                {keptElsewhere}
              </Callout>
            ) : (
              <Callout
                tone={failed ? 'danger' : 'neutral'}
                urgent={failed}
                title={
                  failed
                    ? progress.loadOnly
                      ? 'Das Datenblatt konnte nicht geladen werden'
                      : 'Die Analyse konnte nicht abgeschlossen werden'
                    : 'Die Analyse wurde abgebrochen'
                }
              >
                <p>
                  {failed
                    ? cleanErrorText(cleanJobError(job?.error || job?.message)) || 'Unbekannter Fehler.'
                    : switched
                      ? jobCancelText(job as Job)
                      : cost > 0
                        ? 'Bereits bezahlte Anfragen sind gespeichert.'
                        : 'Es sind keine Kosten entstanden.'}
                  {cost > 0 ? ` Kosten bis hierhin: ${formatUsd(cost)} – im Datenblatt vermerkt.` : ''}
                </p>
                {/* Aktionen unter dem Text: lange Fehlermeldungen behalten die volle Breite */}
                <div className="mt-2.5 flex flex-wrap items-center gap-2">
                  {canRetry && guessed && (
                    <>
                      <Button
                        size="sm"
                        variant="spark"
                        leftIcon={<FileScan />}
                        onClick={() => void actions.reanalyze(guessed)}
                        title={retryCost ? `Erwartet ${retryCost.full} (Schätzung, ein neuer Versuch kostet erneut)` : undefined}
                      >
                        Erneut analysieren
                        {retryCost && (
                          <span className="mono ml-0.5 rounded-sm bg-[color-mix(in_oklab,var(--pf-surface)_40%,transparent)] px-1 text-2xs font-medium">
                            {retryCost.typical}
                          </span>
                        )}
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setRetryOpen(true)}>
                        Seiten wählen …
                      </Button>
                    </>
                  )}
                  <Button asChild size="sm" variant="ghost">
                    <Link to={guessed ? importPath(guessed) : '/import'}>{guessed ? 'Zum Datenblatt' : 'Zur Übersicht'}</Link>
                  </Button>
                </div>
              </Callout>
            )}
          </div>
        )}

        <div className="relative grid min-h-0 flex-1 grid-cols-[minmax(16rem,20rem)_minmax(0,1fr)] gap-0">
          <StepColumn progress={progress} live={isActive} />
          <div className="relative flex min-h-0 flex-col">
            {!progress.loadOnly && <Counters counters={counters} />}
            <div className="relative min-h-0 flex-1 p-5">
              {pageCount > 0 && !ds.data && guessed ? (
                <Skeleton className="size-full rounded-card opacity-50" />
              ) : (
                <PageMosaic datasheetId={guessed} pageCount={pageCount} aspects={aspects} progress={progress} live={isActive} />
              )}
            </div>
            <AnimatePresence>
              {celebrating && (
                <motion.div
                  key="done"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 flex items-center justify-center bg-[color-mix(in_oklab,var(--pf-surface)_72%,transparent)]"
                >
                  <motion.div
                    initial={{ scale: 0.85, y: 8 }}
                    animate={{ scale: 1, y: 0 }}
                    transition={{ type: 'spring', stiffness: 380, damping: 24 }}
                    className="flex max-w-md flex-col items-center gap-3 px-6 text-center"
                  >
                    <span className="flex size-14 items-center justify-center rounded-full bg-gradient-spark text-on-spark shadow-glow-spark [&_svg]:size-7">
                      <Check />
                    </span>
                    <div className="text-md font-semibold text-fg">Fertig – die Prüfansicht öffnet sich</div>
                    <div className="text-xs leading-relaxed text-fg-muted">{formatNumbersInText(job?.message || formatUsd(cost))}</div>
                  </motion.div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        <JobLog log={job?.log ?? []} defaultOpen={failed} className="relative" />
      </section>

      <ReanalyzeDialog
        open={retryOpen}
        onOpenChange={setRetryOpen}
        target={
          guessed && ds.data
            ? {
                id: guessed,
                name: ds.data.original_name,
                pageCount: ds.data.page_count,
                costUsd: ds.data.cost_usd,
                edited: ds.data.edited,
                hasExtraction: ds.data.has_extraction,
                selectedPages: ds.data.selected_pages.length ? ds.data.selected_pages : progress.selectedPages,
              }
            : null
        }
        onStart={(options) => (guessed ? actions.reanalyze(guessed, options) : Promise.resolve(false))}
      />
    </PageBody>
  )
}

/** Zeitleiste der Schritte – scrollt sie (kleines Fenster, viele Hinweise), ist sie per Tastatur erreichbar. */
function StepColumn({ progress, live }: { progress: AnalysisProgress; live: boolean }) {
  const [el, setEl] = useState<HTMLDivElement | null>(null)
  const stop = useScrollTabStop(el)
  return (
    <div
      ref={setEl}
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Tab-Stopp nur, wenn der Bereich scrollt (WCAG 2.1.1)
      tabIndex={stop ? 0 : undefined}
      role={stop ? 'region' : undefined}
      aria-label={stop ? 'Schritte der Analyse' : undefined}
      className="flex min-h-0 flex-col overflow-y-auto border-r border-line px-5 py-5 outline-none focus-ring-inset"
    >
      <StepTimeline steps={progress.steps} live={live} />
    </div>
  )
}

function mergeCounters(a: AnalysisCounters, b: AnalysisCounters): AnalysisCounters {
  const out: AnalysisCounters = { ...a }
  for (const key of Object.keys(b) as (keyof AnalysisCounters)[]) {
    const v = b[key]
    if (v !== undefined) out[key] = v
  }
  return out
}

function sameCounters(a: AnalysisCounters, b: AnalysisCounters): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]) as Set<keyof AnalysisCounters>
  return [...keys].every((k) => a[k] === b[k])
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="micro-label">{label}</dt>
      <dd className="mono mt-0.5 text-md font-semibold tabular-nums text-fg">{value}</dd>
    </div>
  )
}

const COUNTER_LABELS: [keyof AnalysisCounters, string, string][] = [
  ['mpns', 'Bestellnummer', 'Bestellnummern'],
  ['parameters', 'Parameter', 'Parameter'],
  ['pins', 'Pin', 'Pins'],
  ['packages', 'Gehäuse', 'Gehäuse'],
  ['dimensions', 'Maß', 'Maße'],
]

/** „Bisher erkannt“ – Zähler über dem Seitenraster (`detail.counters`, live aus der gestreamten Antwort) */
function Counters({ counters }: { counters: AnalysisCounters }) {
  return (
    <div className="flex shrink-0 items-center gap-5 border-b border-line px-5 py-2.5">
      <div className="micro-label shrink-0">Bisher erkannt</div>
      <dl className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-5 gap-y-1">
        {COUNTER_LABELS.map(([key, one, many]) => (
          <CounterValue key={key} label={counters[key] === 1 ? one : many} value={counters[key]} />
        ))}
      </dl>
    </div>
  )
}

function CounterValue({ label, value }: { label: string; value: number | undefined }) {
  const shown = useCountUp(value ?? 0, 0.8)
  return (
    <div className="flex min-w-0 flex-row-reverse items-baseline gap-1.5">
      <dt className="truncate text-xs text-fg-subtle">{label}</dt>
      <dd className={cn('mono text-md font-semibold tabular-nums', value === undefined ? 'text-fg-subtle' : 'text-fg')}>
        {value === undefined ? '–' : formatNumber(Math.round(shown))}
      </dd>
    </div>
  )
}
