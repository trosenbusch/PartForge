import { useI18n } from '@/lib/i18n'
import { useMutation } from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  housestyleApi,
  type ConformApplyResult,
  type ConformInput,
  type ConformReport,
  type ConformUndoResult,
} from '@/api/housestyle'
import { trackJob, useInlineJob, useJob } from '@/api/jobs'
import { useCancelJob, type Job } from '@/api/system'
import { toMillis } from '@/lib/format'
import { applyProblem, undoProblem } from './model'
import { getBatchSession, updateBatchSession, useBatchSession, type StoredReport } from './store'

/** Zustand eines gestarteten Jobs aus Sicht der Seite (`unknown` = Job im Backend nicht mehr bekannt) */
export type RunState = 'idle' | 'running' | 'done' | 'failed' | 'cancelled' | 'unknown'

function runState(id: string | undefined, job: Job | undefined, error: Error | null, stored: boolean): RunState {
  if (!id) return 'idle'
  if (job) return job.status === 'queued' || job.status === 'running' ? 'running' : job.status
  if (stored) return 'done'
  // Schnappschuss wird noch geladen – bzw. der Job ist weg (Neustart des Backends)
  return error ? 'unknown' : 'running'
}

export interface RunView<TResult> {
  id: string | undefined
  job: Job<TResult> | undefined
  state: RunState
}

export function useBatchJobs(root: string) {
  const { t: tr } = useI18n()
  const session = useBatchSession(root)
  const checkId = session.check?.jobId
  const applyId = session.apply?.jobId
  const undoId = session.undo?.jobId

  // ------------------------------------------------------------------ Jobs beobachten (Ergebnis einmal ablegen)

  const check = useJob<ConformReport>(checkId, {
    onDone: (j) => {
      const s = getBatchSession(root)
      if (!j.result || !s.check || s.check.jobId !== j.id || s.report?.jobId === j.id) return
      updateBatchSession(root, {
        report: { ...s.check, report: j.result, finished: toMillis(j.finished ?? j.created) },
      })
    },
  })
  const apply = useJob<ConformApplyResult>(applyId, {
    onDone: (j) => {
      const s = getBatchSession(root)
      if (!j.result || s.apply?.jobId !== j.id || s.applyResult?.jobId === j.id) return
      updateBatchSession(root, { applyResult: { jobId: j.id, result: j.result } })
    },
  })
  const undo = useJob<ConformUndoResult>(undoId, {
    onDone: (j) => {
      const s = getBatchSession(root)
      if (!j.result || s.undo?.jobId !== j.id || s.undoResult?.jobId === j.id) return
      updateBatchSession(root, { undoResult: { jobId: j.id, result: j.result } })
    },
  })
  // Fortschritt und Ergebnis stehen auf der Seite – solange sie offen ist, nicht in der Pille des Job-Docks
  useInlineJob(checkId)
  useInlineJob(applyId)
  useInlineJob(undoId)

  // ------------------------------------------------------------------ Ergebnisse (auch im Takt vor dem Ablegen)

  const checkRun = session.check
  const storedReport = session.report
  const checkJob = check.job
  const report = useMemo<StoredReport | null>(() => {
    if (
      checkRun &&
      checkJob?.id === checkRun.jobId &&
      checkJob.status === 'done' &&
      checkJob.result &&
      storedReport?.jobId !== checkRun.jobId
    ) {
      return { ...checkRun, report: checkJob.result, finished: toMillis(checkJob.finished ?? checkJob.created) }
    }
    return storedReport
  }, [checkRun, checkJob, storedReport])

  const applyResult =
    session.applyResult && session.applyResult.jobId === applyId
      ? session.applyResult.result
      : apply.job?.status === 'done'
        ? apply.job.result
        : null
  const undoResult =
    session.undoResult && session.undoResult.jobId === undoId
      ? session.undoResult.result
      : undo.job?.status === 'done'
        ? undo.job.result
        : null

  const checkState = runState(checkId, check.job, check.error, Boolean(checkId && session.report?.jobId === checkId))
  const applyState = runState(applyId, apply.job, apply.error, Boolean(applyResult))
  const undoState = runState(undoId, undo.job, undo.error, Boolean(undoResult))

  // ------------------------------------------------------------------ Starten

  const startCheck = useMutation({
    mutationFn: ({ input }: { input: ConformInput; key: string }) => housestyleApi.check(input),
    meta: { errorTitle: tr("Prüfung konnte nicht gestartet werden") },
    onSuccess: ({ job }, { input, key }) => {
      trackJob(job, { dock: false, toast: false, doneMessage: (j) => j.result?.message })
      // der alte Bericht bleibt stehen, bis der neue da ist; Ergebnisse von Anwenden/Rückgängig sind damit erledigt
      updateBatchSession(root, {
        last: 'check',
        check: { jobId: job.id, key, input },
        apply: null,
        applyResult: null,
        undo: null,
        undoResult: null,
      })
    },
  })

  const startApply = useMutation({
    mutationFn: ({ input }: { input: ConformInput; components: number; libraries: number }) =>
      housestyleApi.apply(input),
    meta: { errorTitle: tr("Hausstil konnte nicht angewendet werden") },
    onSuccess: ({ job }, { input, components, libraries }) => {
      trackJob(job, {
        dock: false,
        toast: false,
        doneMessage: (j) => j.result?.message,
        warnWhen: (j) => applyProblem(j.result),
      })
      updateBatchSession(root, {
        last: 'apply',
        apply: { jobId: job.id, input, components, libraries },
        applyResult: null,
        check: null,
        report: null,
        undo: null,
        undoResult: null,
      })
    },
  })

  const startUndo = useMutation({
    mutationFn: () => housestyleApi.undo(),
    meta: { errorTitle: tr("Stapelbearbeitung konnte nicht rückgängig gemacht werden") },
    onSuccess: ({ job }) => {
      trackJob(job, {
        dock: false,
        toast: false,
        doneMessage: (j) => j.result?.message,
        warnWhen: (j) => undoProblem(j.result),
      })
      updateBatchSession(root, {
        last: 'undo',
        undo: { jobId: job.id },
        undoResult: null,
        check: null,
        report: null,
        apply: null,
        applyResult: null,
      })
    },
  })

  const cancel = useCancelJob()

  const starting = startCheck.isPending || startApply.isPending || startUndo.isPending
  const running = checkState === 'running' || applyState === 'running' || undoState === 'running'

  return {
    session,
    check: { id: checkId, job: check.job, state: checkState } satisfies RunView<ConformReport>,
    apply: { id: applyId, job: apply.job, state: applyState } satisfies RunView<ConformApplyResult>,
    undo: { id: undoId, job: undo.job, state: undoState } satisfies RunView<ConformUndoResult>,
    report,
    applyResult,
    undoResult,
    /** Start einer Aktion läuft (Anfrage unterwegs) */
    starting: { check: startCheck.isPending, apply: startApply.isPending, undo: startUndo.isPending },
    /** irgendein Job der Seite startet oder läuft – keine zweite Aktion */
    busy: starting || running,
    startCheck: (input: ConformInput, key: string) => startCheck.mutate({ input, key }),
    startApply: (input: ConformInput, plan: { components: number; libraries: number }) =>
      startApply.mutate({ input, ...plan }),
    startUndo: () => startUndo.mutate(),
    /** laufende Prüfung abbrechen (liest nur – Abbrechen ist gefahrlos) */
    cancelCheck: () => {
      if (checkId) cancel.mutate(checkId)
    },
    cancelling: cancel.isPending,
  }
}

export type BatchJobs = ReturnType<typeof useBatchJobs>
