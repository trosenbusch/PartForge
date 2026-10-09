import { AnimatePresence, motion } from 'motion/react'
import { Ban, Check, ChevronDown, ChevronUp, CircleStop, Minus, ScrollText, TriangleAlert, X } from 'lucide-react'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { jobCancelText, jobOutcome, noteJobSnapshot, useJob, type JobOutcome } from '@/api/jobs'
import {
  isJobActive,
  isJobFinished,
  isLibrarySwitchCancel,
  sameLibraryRoot,
  useCancelJob,
  useJobs,
  useRecentWorkspaces,
  useWorkspace,
  type Job,
  type JobLogLevel,
  type JobStatus,
} from '@/api/system'
import { Badge, Button, IconButton, ProgressRing, type ProgressTone } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatClock, formatNumber, formatNumbersInText, formatPercent, formatRelativeTime, toMillis } from '@/lib/format'
import { useJobDock } from '../stores'

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: 'Wartet …',
  running: 'Läuft …',
  done: 'Fertig',
  failed: 'Fehlgeschlagen',
  cancelled: 'Abgebrochen',
}

const STATUS_TONE: Record<JobStatus, ProgressTone> = {
  queued: 'neutral',
  running: 'accent',
  done: 'success',
  failed: 'danger',
  cancelled: 'neutral',
}

const LOG_COLOR: Record<JobLogLevel, string> = {
  info: 'text-fg-muted',
  warn: 'text-warning-text',
  error: 'text-danger-text',
  success: 'text-success-text',
}

/** Höchstens so viele Log-Zeilen rendern (das Backend hält bis zu 2000) */
const LOG_WINDOW = 200
/** Ruhezustand („Alle Jobs erledigt“): Pille nach dieser Zeit ausblenden */
const IDLE_HIDE_MS = 4500
/** Ungesehene Fehlschläge: Pille nach dieser Zeit zum runden Hinweis verkleinern (bleibt, bis das Panel offen war) */
const FAILED_COLLAPSE_MS = 6000
/** Abstand der Pille zum Fensterrand (bottom-5/right-5) + Luft zum Inhalt – Teil von `--pf-dock-reserve` */
const DOCK_EDGE = 20
const DOCK_GAP = 12

/** Maus über dem Dock oder Tastaturfokus darin (ein Mausklick-Fokus zählt nicht – sonst bliebe die Pille stehen) */
function isEngaged(el: HTMLElement | null): boolean {
  return Boolean(el && (el.matches(':hover') || el.querySelector(':focus-visible')))
}

/**
 * Braucht ein beendeter Job Aufmerksamkeit (gelbe Pille „Erledigt mit Hinweisen“)? Probleme im Ergebnis – und ein
 * Abbruch durch einen Bibliothekswechsel (nicht vom Benutzer gewollt, der Job ist nicht fertig geworden).
 */
const hasProblem = (job: Job) => (job.status === 'done' && jobOutcome(job)?.tone === 'warning') || isLibrarySwitchCancel(job)

/**
 * Name der Bibliothek eines Jobs, wenn sie **nicht** die geöffnete ist (`Job.library`) – sonst `null`. Der Name kommt
 * aus dem Job (`library_name`), aus „Zuletzt verwendet“, sonst der Ordnername.
 */
function useForeignLibraryName(): (job: Job) => string | null {
  const root = useWorkspace().data?.root ?? null
  const recent = useRecentWorkspaces().data
  return (job) => {
    if (!job.library || sameLibraryRoot(job.library, root)) return null
    if (job.library_name?.trim()) return job.library_name.trim()
    const known = recent?.find((r) => sameLibraryRoot(r.path, job.library))
    return known?.name ?? baseName(job.library)
  }
}

/** Statuszeile eines Jobs im Panel: Meldung, Fehler, Problem bzw. „Fertig · vor 2 Min.“ */
function statusLine(job: Job, outcome: JobOutcome | null): string {
  if (job.status === 'failed') return outcome?.description ?? STATUS_LABEL.failed
  if (outcome?.tone === 'warning') return outcome.problem ?? outcome.description
  if (isJobActive(job) && job.cancel_requested) return 'Wird abgebrochen …'
  if (isJobActive(job)) return formatNumbersInText(job.message) || STATUS_LABEL[job.status]
  const when = formatRelativeTime(job.finished ?? job.created)
  if (job.status === 'cancelled') {
    // Grund vor Zeit: „Abgebrochen – Bibliothek gewechselt“ passt sonst nicht in die Zeile (voller Text als Tooltip)
    const reason = jobCancelText(job, true)
    return reason === STATUS_LABEL.cancelled ? `${reason} · ${when}` : reason
  }
  return `${STATUS_LABEL[job.status]} · ${when}`
}

/** `--pf-dock-reserve`/`--pf-dock-width` auf <html> setzen (0px = Dock ausgeblendet). */
function publishReserve(block: number, inline: number) {
  const root = document.documentElement.style
  root.setProperty('--pf-dock-reserve', `${block}px`)
  root.setProperty('--pf-dock-width', `${inline}px`)
  useJobDock.getState().setReserve({ block, inline })
}

/**
 * Job-Dock unten rechts: Pille mit Fortschrittsring (laufende Jobs), aufklappbares Panel mit Log und Abbrechen.
 * Im Ruhezustand blendet sich die Pille nach wenigen Sekunden aus; ungesehene Fehlschläge bleiben als runder
 * Hinweis stehen, bis das Panel einmal offen war. Abschluss-Toasts und das Neuladen der Daten erledigt
 * `noteJobSnapshot` (`@/api/jobs`) – genau einmal je Job.
 */
export function JobDock() {
  const jobsQuery = useJobs()
  // gezielt abonnieren – nicht bei jeder Änderung im Dock-Store neu rendern
  const open = useJobDock((s) => s.open)
  const setOpen = useJobDock((s) => s.setOpen)
  const toggle = useJobDock((s) => s.toggle)
  const dismissed = useJobDock((s) => s.dismissed)
  const dismiss = useJobDock((s) => s.dismiss)
  const setVisible = useJobDock((s) => s.setVisible)
  const setHeight = useJobDock((s) => s.setHeight)
  const rootRef = useRef<HTMLDivElement>(null)
  const pillRef = useRef<HTMLButtonElement>(null)

  const booted = useJobDock((s) => s.booted)
  const hiddenFor = useJobDock((s) => s.idleHiddenFor)
  const compactFor = useJobDock((s) => s.idleCompactFor)
  const seenFailures = useJobDock((s) => s.seenFailures)
  const inline = useJobDock((s) => s.inline)
  const bootedAt = useJobDock((s) => s.bootedAt)
  const [paused, setPaused] = useState(false)

  const libraryOf = useForeignLibraryName()

  // Esc schließt das Panel, solange der Fokus darin liegt (Fokus zurück auf die Pille)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      const root = rootRef.current
      if (!root || !root.contains(document.activeElement)) return
      e.preventDefault()
      setOpen(false)
      setPaused(false)
      pillRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, setOpen])

  // Die Liste hält je Job den neuesten bekannten Stand – auch aus `useJob` der Seiten (Dock und Seite stimmen überein)
  const all = jobsQuery.data
  /** Panel: alle nicht ausgeblendeten Jobs */
  const jobs = (all ?? []).filter((j) => !dismissed.includes(j.id))
  /** Historie: schon vor dieser Sitzung (erste Jobliste) beendet – im Panel, aber keine Neuigkeit für die Pille */
  const isHistory = (j: Job) => bootedAt !== null && isJobFinished(j) && toMillis(j.finished ?? j.created) < bootedAt - 1000
  /** Pille: ohne Historie und ohne Jobs, die eine Seite gerade selbst zeigt (`dock: false`) */
  const pillJobs = jobs.filter((j) => !inline.includes(j.id) && !isHistory(j))
  const active = pillJobs.filter(isJobActive)
  const finished = pillJobs.filter(isJobFinished)
  const failedIds = finished.filter((j) => j.status === 'failed').map((j) => j.id)
  const anyFailed = failedIds.length > 0
  const anyWarning = !anyFailed && finished.some(hasProblem)
  const signature = pillJobs.map((j) => `${j.id}:${j.status}`).join(',')
  const panelActive = jobs.filter(isJobActive).length
  const panelFinished = jobs.filter(isJobFinished)

  // Abschluss melden (Toast, Daten neu laden) – auch für Jobs, die die Jobliste nur noch fertig sieht. Beim ersten
  // Laden schon fertige Jobs (z. B. nach „Neu laden“) gar nicht erst als Pille zeigen.
  useEffect(() => {
    if (!all) return
    for (const job of all) noteJobSnapshot(job)
    const dock = useJobDock.getState()
    if (!dock.booted) {
      const shown = all.filter((j) => !dock.dismissed.includes(j.id) && !dock.inline.includes(j.id))
      dock.bootIdle(
        all.some(isJobActive) ? null : shown.map((j) => `${j.id}:${j.status}`).join(','),
        all.filter((j) => j.status === 'failed').map((j) => j.id),
      )
    }
  }, [all])

  // ------------------------------------------------------------------ Ruhezustand: ausblenden bzw. verkleinern
  // Panel geöffnet = Fehlschläge gesehen (nach dem Zuklappen startet der Ruhe-Zeitgeber neu, siehe Store)
  const failedKey = failedIds.join(',')
  useEffect(() => {
    if (open && failedKey) useJobDock.getState().markFailuresSeen(failedKey.split(','))
  }, [open, failedKey])

  const unseenFailures = failedIds.some((id) => !seenFailures.includes(id))
  const idle = pillJobs.length > 0 && active.length === 0 && !open
  const autoHidden = idle && !unseenFailures && hiddenFor === signature
  const compact = idle && unseenFailures && compactFor === signature && !paused
  const pillVisible = booted && pillJobs.length > 0 && !autoHidden
  const visible = pillVisible || (open && jobs.length > 0)

  // Ruhe-Zeitgeber: wartet, solange Maus oder Tastaturfokus auf dem Dock liegen (zur Laufzeit geprüft – ein unter dem
  // Zeiger verschwundenes Panel hinterlässt keinen „hängenden“ Zustand)
  useEffect(() => {
    if (!booted || !idle) return
    const action = !unseenFailures && hiddenFor !== signature ? 'hide' : unseenFailures && compactFor !== signature ? 'compact' : null
    if (!action) return
    const cancelled = new AbortController()
    const check = () => {
      if (cancelled.signal.aborted) return
      if (isEngaged(rootRef.current)) {
        window.setTimeout(check, 300)
        return
      }
      const dock = useJobDock.getState()
      if (action === 'hide') dock.hideIdle(signature)
      else dock.compactIdle(signature)
    }
    window.setTimeout(check, action === 'hide' ? IDLE_HIDE_MS : FAILED_COLLAPSE_MS)
    return () => cancelled.abort()
  }, [booted, idle, unseenFailures, hiddenFor, compactFor, signature])

  useEffect(() => {
    setVisible(visible)
  }, [visible, setVisible])

  // Höhe messen, damit Toasts über Pille bzw. Panel erscheinen und nichts verdecken
  useEffect(() => {
    const el = rootRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(() => setHeight(Math.round(el.getBoundingClientRect().height)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [setHeight])

  // Platzbedarf der Pille als CSS-Variable (`--pf-dock-reserve`) – Seiten halten damit Inhalte frei
  useLayoutEffect(() => {
    if (!pillVisible) {
      publishReserve(0, 0)
      return
    }
    const el = pillRef.current
    if (!el) return
    // Layoutmaße (ohne die Skalierung der Einblend-Animation)
    const update = () => publishReserve(el.offsetHeight + DOCK_EDGE + DOCK_GAP, el.offsetWidth + DOCK_EDGE + DOCK_GAP)
    update()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [pillVisible, compact])
  useEffect(() => () => publishReserve(0, 0), [])

  const avg = active.length ? active.reduce((sum, j) => sum + j.progress, 0) / active.length : 1
  const lead = active[0]
  const ringTone: ProgressTone = active.length ? 'accent' : anyFailed ? 'danger' : anyWarning ? 'warning' : 'success'
  const headline =
    active.length === 0
      ? anyFailed
        ? failedIds.length === 1
          ? 'Job fehlgeschlagen'
          : `${formatNumber(failedIds.length)} Jobs fehlgeschlagen`
        : anyWarning
          ? 'Erledigt mit Hinweisen'
          : 'Alle Jobs erledigt'
      : active.length === 1
        ? '1 Job läuft'
        : `${formatNumber(active.length)} Jobs laufen`
  /** Zweite Zeile der Pille: Meldung des ersten laufenden Jobs (gekürzt) und – immer sichtbar – sein Fortschritt */
  const leadText = lead ? formatNumbersInText(lead.message) || lead.title : 'Details anzeigen'
  const leadPercent = lead ? formatPercent(lead.progress) : null

  return (
    <div
      ref={rootRef}
      className="pointer-events-none fixed bottom-5 right-5 z-dock flex flex-col items-end gap-2"
      onPointerEnter={() => setPaused(true)}
      onPointerLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setPaused(false)
      }}
    >
      <AnimatePresence initial={false}>
        {visible && open && (
          <motion.section
            key="panel"
            aria-label="Hintergrundjobs"
            className="pointer-events-auto flex w-[400px] flex-col overflow-hidden rounded-panel border border-line-strong bg-surface shadow-pop"
            initial={{ opacity: 0, y: 14, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 10, scale: 0.98, transition: { duration: 0.14 } }}
            transition={{ type: 'spring', stiffness: 420, damping: 34 }}
            style={{ transformOrigin: 'bottom right' }}
          >
            <header className="flex items-center gap-2 border-b border-line px-4 py-3">
              <h2 className="text-ui font-semibold text-fg">Hintergrundjobs</h2>
              {panelActive > 0 && (
                <Badge variant="accent" dot pulse>
                  {formatNumber(panelActive)} aktiv
                </Badge>
              )}
              <div className="ml-auto flex items-center gap-1">
                {panelFinished.length > 0 && (
                  <Button size="xs" variant="ghost" onClick={() => dismiss(panelFinished.map((j) => j.id))}>
                    Erledigte ausblenden
                  </Button>
                )}
                <IconButton
                  size="xs"
                  label="Minimieren"
                  icon={<Minus />}
                  onClick={() => {
                    setOpen(false)
                    setPaused(false) // das Panel verschwindet unter dem Zeiger – kein pointerleave
                  }}
                />
              </div>
            </header>
            <div className="max-h-[min(420px,60vh)] overflow-y-auto">
              {jobs.slice(0, 15).map((job) => (
                <JobRow key={job.id} job={job} library={libraryOf(job)} onDismiss={() => dismiss(job.id)} />
              ))}
            </div>
          </motion.section>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {pillVisible && (
          <motion.button
            ref={pillRef}
            key="pill"
            type="button"
            layout
            onClick={toggle}
            aria-expanded={open}
            // Eingeklappt (nur Symbol) braucht die Pille einen Namen; sonst gilt der sichtbare Text (Sprachsteuerung)
            aria-label={compact ? `${headline} – Jobliste anzeigen` : undefined}
            title={compact ? headline : undefined}
            className={cn(
              'pointer-events-auto flex items-center rounded-full border border-line-strong bg-surface text-left shadow-pop outline-none focus-ring',
              'transition-[border-color] hover:border-line-control',
              compact ? 'size-12 justify-center p-0' : 'h-12 gap-3 py-1.5 pl-1.5 pr-4',
            )}
            initial={{ opacity: 0, y: 16, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.92, transition: { duration: 0.18 } }}
            transition={{ type: 'spring', stiffness: 420, damping: 30 }}
          >
            <motion.span layout="position" className="flex" aria-hidden>
              <ProgressRing
                value={avg}
                size={36}
                stroke={3}
                tone={ringTone}
                indeterminate={active.length > 0 && active.every((j) => j.progress <= 0)}
              >
                {active.length > 0 ? (
                  <span className="text-2xs font-semibold">{active.length}</span>
                ) : anyFailed ? (
                  <X className="size-3.5 text-danger" />
                ) : anyWarning ? (
                  <TriangleAlert className="size-3.5 text-warning" />
                ) : (
                  <Check className="size-3.5 text-success" />
                )}
              </ProgressRing>
            </motion.span>
            {!compact && (
              <>
                <span className="flex min-w-0 flex-col">
                  <span className="whitespace-nowrap text-ui font-medium leading-5 text-fg">{headline}</span>
                  <span className="sr-only">, </span>
                  <span
                    className="flex max-w-[220px] text-2xs leading-4 text-fg-subtle"
                    title={leadPercent ? `${leadText} · ${leadPercent}` : undefined}
                  >
                    <span className="min-w-0 truncate">{leadText}</span>
                    {leadPercent && <span className="shrink-0 whitespace-pre tabular-nums">{` · ${leadPercent}`}</span>}
                  </span>
                </span>
                {open ? (
                  <ChevronDown aria-hidden className="size-4 text-fg-subtle" />
                ) : (
                  <ChevronUp aria-hidden className="size-4 text-fg-subtle" />
                )}
              </>
            )}
          </motion.button>
        )}
      </AnimatePresence>
    </div>
  )
}

/** Zeile im Panel; `library` = Name der Bibliothek, wenn der Job zu einer anderen als der geöffneten gehört */
function JobRow({ job, library, onDismiss }: { job: Job; library: string | null; onDismiss: () => void }) {
  const expandedId = useJobDock((s) => s.expandedId)
  const toggleExpanded = useJobDock((s) => s.toggleExpanded)
  const highlightId = useJobDock((s) => s.highlightId)
  const cancel = useCancelJob()
  const expanded = expandedId === job.id
  const active = isJobActive(job)
  const outcome = jobOutcome(job)
  const warned = outcome?.tone === 'warning'
  const switched = isLibrarySwitchCancel(job)
  // Abbruch durch Bibliothekswechsel: gelb wie „Hinweis“ (nicht gewollt, nicht fertig) – Abbruch durch den Benutzer: grau
  const tone: ProgressTone = warned || switched ? 'warning' : STATUS_TONE[job.status]
  const statusLabel = warned ? 'Fertig mit Hinweisen' : switched ? jobCancelText(job, true) : STATUS_LABEL[job.status]
  const line = statusLine(job, outcome)
  /** voller Text als Tooltip, wenn die Zeile gekürzt sein kann */
  const fullText =
    job.status === 'failed' || warned ? (outcome?.problem ?? undefined) : job.status === 'cancelled' ? jobCancelText(job) : undefined

  return (
    <div className={cn('border-b border-line last:border-b-0', highlightId === job.id && active && 'bg-accent-soft/40')}>
      <div className="flex items-center gap-3 px-4 py-2.5">
        <ProgressRing
          value={job.progress}
          size={34}
          stroke={3}
          tone={tone}
          indeterminate={job.status === 'queued'}
          label={`${job.title}: ${statusLabel}`}
        >
          {warned ? (
            <TriangleAlert className="size-3.5 text-warning" />
          ) : job.status === 'done' ? (
            <Check className="size-3.5 text-success" />
          ) : job.status === 'failed' ? (
            <X className="size-3.5 text-danger" />
          ) : job.status === 'cancelled' ? (
            <Ban className={cn('size-3.5', switched ? 'text-warning' : 'text-fg-subtle')} />
          ) : job.status === 'running' ? (
            <span className="text-2xs tracking-tight">{Math.round(job.progress * 100)}</span>
          ) : null}
        </ProgressRing>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-baseline gap-1.5">
            <span className="min-w-0 truncate text-ui font-medium text-fg" title={job.title}>
              {job.title}
            </span>
            {library && (
              <span
                className="max-w-[40%] shrink-0 truncate rounded-full border border-line-strong px-1.5 text-2xs leading-4 text-fg-muted"
                title={`Gehört zur Bibliothek „${library}“ (nicht die geöffnete)`}
              >
                <span className="sr-only">Bibliothek </span>
                {library}
              </span>
            )}
          </div>
          <div
            className={cn(
              'truncate text-2xs',
              job.status === 'failed' ? 'text-danger-text' : warned || switched ? 'text-warning-text' : 'text-fg-subtle',
            )}
            title={fullText}
          >
            {line}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          {active && (
            <IconButton
              size="xs"
              label={job.cancel_requested ? 'Wird abgebrochen …' : 'Abbrechen'}
              icon={<CircleStop />}
              loading={cancel.isPending || Boolean(job.cancel_requested)}
              disabled={Boolean(job.cancel_requested)}
              onClick={() => cancel.mutate(job.id)}
            />
          )}
          <IconButton
            size="xs"
            label={expanded ? 'Log ausblenden' : 'Log anzeigen'}
            icon={<ScrollText />}
            onClick={() => toggleExpanded(job.id)}
            className={cn(expanded && 'bg-surface-2 text-fg')}
          />
          {!active && <IconButton size="xs" label="Ausblenden" icon={<X />} onClick={onDismiss} />}
        </div>
      </div>
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <JobLog id={job.id} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function JobLog({ id }: { id: string }) {
  const { job } = useJob(id)
  const ref = useRef<HTMLDivElement>(null)
  const count = job?.log.length ?? 0
  const offset = Math.max(0, count - LOG_WINDOW)
  const visible = job ? job.log.slice(offset) : []
  useLayoutEffect(() => {
    const el = ref.current
    if (el) el.scrollTop = el.scrollHeight
  }, [count])
  return (
    <div
      ref={ref}
      role="log"
      aria-label="Protokoll"
      className="mx-4 mb-3 max-h-44 overflow-y-auto rounded-button border border-line bg-bg/80 px-3 py-2 font-mono text-2xs leading-[1.6]"
    >
      {!job && <div className="text-fg-subtle">Log wird geladen …</div>}
      {job && count === 0 && <div className="text-fg-subtle">Noch keine Einträge.</div>}
      {offset > 0 && <div className="pb-1 text-fg-subtle">… {offset} ältere Einträge ausgeblendet</div>}
      {visible.map((entry, i) => (
        <div key={offset + i} className="flex gap-2">
          <span className="shrink-0 text-fg-subtle">{formatClock(entry.ts)}</span>
          <span className={cn('min-w-0 whitespace-pre-wrap break-words', LOG_COLOR[entry.level])}>{entry.text}</span>
        </div>
      ))}
    </div>
  )
}
