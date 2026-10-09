/**
 * Import starten: PDF-Dateien (Drop-Zone, globales Overlay), Web-Adresse oder erneute Analyse.
 *
 * Bezahlte Analysen nie doppelt und nie ungefragt im Stapel:
 * - Vor dem Hochladen wird die Datenblatt-ID (SHA-256 des Inhalts, 16 Zeichen – wie im Backend) berechnet. Ist das
 *   PDF schon analysiert, öffnet sich das vorhandene Ergebnis; ist die letzte Analyse fehlgeschlagen, öffnet sich
 *   ihre Fehleransicht (ein neuer Versuch kostet erneut – das entscheidet der Benutzer dort).
 * - Automatisch analysiert wird nur **ein einzelnes neues** PDF. Mehrere PDFs werden gespeichert, dann fragt
 *   „Datenblätter analysieren?“ mit den erwarteten Kosten (`useBatchPrompt`, Dialog in der Import-Seite).
 * - Ohne Claude-Schlüssel wird nur gespeichert.
 *
 * Rückmeldung: Die Seite zeigt laufende Analysen selbst (Analyseansicht, `useInlineJob`) – sie zählen dann nicht in der
 * Pille des Job-Docks; erst wenn die Ansicht verlassen wird, übernimmt das Dock samt Abschluss-Toast (Schlusssatz des
 * Backends, z. B. „Analyse fertig: 14 Bestellvarianten, 13 Pins, 2 Gehäuse – 0,23 $“). Analysen im Hintergrund
 * (Stapel) laufen gleich über das Dock.
 *
 * Ist Claude nicht nutzbar, antwortet das Backend mit 503 `{ code, message }` – der Fehler-Toast nennt den Grund und
 * bietet bei Schlüssel-/Einstellungsproblemen den Weg zu Einstellungen › KI.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ApiError, cleanErrorText, errorMessage } from '@/api/client'
import { datasheetKeys, datasheetsApi, useAiStatus, type DatasheetDetail, type ExtractOptions } from '@/api/datasheets'
import { trackJob } from '@/api/jobs'
import { classifyAiError, isJobFinished, systemApi, type AiProblemCode, type Job } from '@/api/system'
import { plural } from '@/lib/format'
import { useActiveImports, useBatchPrompt, type BatchItem } from '../store'
import { analysisFailed } from './format'

/** Datenblatt-ID wie im Backend (`sha256[:16]`); `null`, wenn der Browser nicht hashen kann. */
export async function datasheetIdOf(file: File): Promise<string | null> {
  try {
    if (!globalThis.crypto?.subtle) return null
    const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0'))
      .join('')
      .slice(0, 16)
  } catch {
    return null
  }
}

export function importPath(datasheetId: string, jobId?: string | null): string {
  return `/import?ds=${encodeURIComponent(datasheetId)}${jobId ? `&job=${encodeURIComponent(jobId)}` : ''}`
}

/** KI-Probleme, die sich unter Einstellungen › Allgemein › KI-Funktionen beheben lassen (Schlüssel, Modell, ausgeschaltet) */
export const AI_SETTINGS_CODES: ReadonlySet<AiProblemCode> = new Set<AiProblemCode>([
  'key_missing',
  'key_rejected',
  'model_unavailable',
  'ai_disabled',
])

/** Kurztext je KI-Problem (`detail.code` der 503-Antwort bzw. von `POST /api/ai/test`) */
export const AI_PROBLEM_TITLE: Record<AiProblemCode, string> = {
  key_missing: 'Kein Claude-API-Schlüssel hinterlegt',
  key_rejected: 'Claude-API-Schlüssel abgelehnt',
  model_unavailable: 'Modell nicht verfügbar',
  network: 'Claude-API nicht erreichbar',
  rate_limited: 'Anfragelimit der Claude-API erreicht',
  ai_disabled: 'KI-Funktionen sind ausgeschaltet',
  unknown: 'Die Claude-API meldet einen Fehler',
}

/** Ist das ein „Claude nicht nutzbar“-Fehler (503 `{ code, message }`)? Dann Code und deutscher Text. */
export function aiUnavailable(error: unknown): { code: AiProblemCode; message: string } | null {
  if (!(error instanceof ApiError) || error.status !== 503) return null
  const detail = error.detail
  if (!detail || typeof detail !== 'object' || typeof (detail as { code?: unknown }).code !== 'string') return null
  return classifyAiError(error)
}

interface Started {
  id: string
  jobId: string | null
  name: string
  pageCount: number
  state: BatchItem['state']
  error?: string | null
}

/** Auf das Ende eines kurzen Jobs warten (Textebene lesen) – höchstens `timeoutMs`. */
async function waitForJob(id: string, timeoutMs = 60_000): Promise<Job | null> {
  const end = Date.now() + timeoutMs
  while (Date.now() < end) {
    try {
      const job = await systemApi.getJob(id)
      if (isJobFinished(job)) return job
    } catch {
      return null
    }
    await new Promise((r) => setTimeout(r, 400))
  }
  return null
}

export function useImportActions() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const ai = useAiStatus()
  const aiReady = Boolean(ai.data?.enabled && ai.data.key_configured)
  const [busy, setBusy] = useState<string | null>(null)

  /** Fehler beim Start (Upload, Analyse, Download) – bei „Claude nicht nutzbar“ mit Grund und Weg zu den Einstellungen */
  const startError = useCallback(
    (title: string, e: unknown) => {
      const ai = aiUnavailable(e)
      toast.error(ai ? AI_PROBLEM_TITLE[ai.code] : title, {
        id: ai ? `ds-ai-${ai.code}` : undefined,
        description: cleanErrorText(ai?.message ?? errorMessage(e)),
        action: ai && AI_SETTINGS_CODES.has(ai.code) ? { label: 'KI einrichten', onClick: () => navigate('/einstellungen#ki') } : undefined,
      })
    },
    [navigate],
  )

  /**
   * Analyse-Job merken. `background` = niemand zeigt ihn (Stapel): Job-Dock mit Abschluss-Toast. Sonst zeigt ihn die
   * Analyseansicht – nicht in der Pille, kein Toast; verlässt man sie vorher, übernimmt das Dock (`useInlineJob`).
   */
  const track = useCallback((datasheetId: string, job: Job, opts: { background?: boolean } = {}) => {
    if (opts.background) trackJob(job, { openDock: false, toast: true })
    else trackJob(job, { dock: false, toast: false })
    useActiveImports.getState().start(datasheetId, job.id)
  }, [])

  const analyzeExisting = useCallback(
    async (datasheetId: string, options?: Partial<ExtractOptions> | null, opts: { background?: boolean } = {}): Promise<string> => {
      const { job } = await datasheetsApi.extract(datasheetId, options)
      track(datasheetId, job, opts)
      return job.id
    },
    [track],
  )

  /** Eine Datei speichern; `analyze` startet die Analyse gleich mit (nur für ein einzelnes neues PDF). */
  const importFile = useCallback(
    async (file: File, opts: { analyze: boolean; quiet?: boolean; background?: boolean }): Promise<Started> => {
      const id = await datasheetIdOf(file)
      let existing: DatasheetDetail | null = null
      if (id) {
        const known = await qc.fetchQuery({ queryKey: datasheetKeys.list, queryFn: ({ signal }) => datasheetsApi.list(signal), staleTime: 2_000 })
        if (known.some((d) => d.id === id)) {
          try {
            existing = await datasheetsApi.detail(id)
          } catch (e) {
            if (!(e instanceof ApiError && e.isNotFound)) throw e
          }
        }
      }
      if (existing) {
        const base = { id: existing.id, jobId: null, name: existing.original_name, pageCount: existing.page_count }
        if (existing.has_extraction) {
          if (!opts.quiet) {
            toast.info(`„${file.name}“ ist bereits analysiert`, {
              id: `ds-known-${existing.id}`,
              description: 'Das vorhandene Ergebnis wird geöffnet. Eine neue Analyse startet „Neu analysieren“.',
            })
          }
          return { ...base, state: 'analyzed' }
        }
        if (analysisFailed(existing)) {
          if (!opts.quiet) {
            toast.info(`Die letzte Analyse von „${file.name}“ ist fehlgeschlagen`, {
              id: `ds-failed-${existing.id}`,
              description: 'Ursache und Kosten stehen in der Ansicht. Ein neuer Versuch kostet erneut – dort lässt er sich starten.',
            })
          }
          return { ...base, state: 'failed', error: existing.last_error }
        }
        if (opts.analyze && aiReady) {
          return { ...base, jobId: await analyzeExisting(existing.id, null, { background: opts.background }), state: 'new' }
        }
        return { ...base, state: 'new' }
      }
      // Ohne Hash (sehr alte WebView) erst speichern und dann entscheiden – nie blind eine zweite Analyse
      const analyzeNow = opts.analyze && aiReady && Boolean(id)
      const out = await datasheetsApi.upload(file, { extract: analyzeNow })
      void qc.invalidateQueries({ queryKey: datasheetKeys.list })
      const ds = out.datasheet
      const base = { id: ds.id, name: ds.original_name, pageCount: ds.page_count }
      // `job` ist im Schema ein untypisiertes dict (Job-Schnappschuss)
      const job = out.job as unknown as Job | null
      if (out.warning) toast.warning('Datenblatt gespeichert, nicht analysiert', { description: out.warning })
      if (job && analyzeNow) {
        track(ds.id, job, { background: opts.background })
        return { ...base, jobId: job.id, state: 'new' }
      }
      if (job) {
        // nur die Textebene lesen (schnell) – im Stapel abwarten, damit Seitenzahl und Auswahl stimmen
        trackJob(job, { openDock: false, toast: false })
        if (opts.quiet) {
          const finished = await waitForJob(job.id)
          const result = finished?.result as { page_count?: number } | undefined
          if (result?.page_count) base.pageCount = result.page_count
        }
      }
      if (!id && opts.analyze && aiReady && !ds.has_extraction) {
        return { ...base, jobId: await analyzeExisting(ds.id, null, { background: opts.background }), state: 'new' }
      }
      return { ...base, jobId: null, state: ds.has_extraction ? 'analyzed' : 'new' }
    },
    [aiReady, analyzeExisting, qc, track],
  )

  /**
   * Dateien importieren. Ein einzelnes neues PDF wird gleich analysiert (Analyseansicht); mehrere werden gespeichert
   * und erst nach Rückfrage analysiert.
   */
  const startFiles = useCallback(
    async (files: File[], opts: { open?: boolean } = {}) => {
      const pdfs = files.filter((f) => f.type === 'application/pdf' || /\.pdf$/i.test(f.name))
      if (!pdfs.length) return
      if (pdfs.length === 1) {
        const [file] = pdfs
        setBusy(`Lade ${file.name} …`)
        let started: Started | null = null
        try {
          // ohne Analyseansicht (open: false) läuft die Analyse über das Job-Dock
          started = await importFile(file, { analyze: true, background: opts.open === false })
        } catch (e) {
          startError(`„${file.name}“ konnte nicht importiert werden`, e)
        }
        setBusy(null)
        if (!started) return
        if (!aiReady && started.state === 'new') {
          toast.warning('Datenblatt gespeichert', {
            id: 'ds-no-ai',
            description:
              ai.data?.enabled === false
                ? 'Die KI-Analyse ist ausgeschaltet – nach dem Einschalten lässt sie sich starten.'
                : 'Für die Analyse fehlt ein Claude-API-Schlüssel – nach dem Einrichten lässt sie sich starten.',
            action: { label: 'KI einrichten', onClick: () => navigate('/einstellungen#ki') },
          })
        }
        if (opts.open !== false) navigate(importPath(started.id, started.jobId))
        return
      }

      // mehrere PDFs: speichern (kostenlos), dann fragen
      const results: Started[] = []
      for (const [i, file] of pdfs.entries()) {
        setBusy(`Speichere ${file.name} (${i + 1} von ${pdfs.length}) …`)
        try {
          results.push(await importFile(file, { analyze: false, quiet: true }))
        } catch (e) {
          startError(`„${file.name}“ konnte nicht gespeichert werden`, e)
        }
      }
      setBusy(null)
      void qc.invalidateQueries({ queryKey: datasheetKeys.list })
      if (!results.length) return
      const unique = [...new Map(results.map((r) => [r.id, r])).values()]
      const open = unique.filter((r) => r.state !== 'analyzed')
      if (aiReady && open.length) {
        useBatchPrompt.getState().show(unique.map(({ id, name, pageCount, state, error }) => ({ id, name, pageCount, state, error })))
      } else {
        toast.success(`${plural(unique.length, 'Datenblatt', 'Datenblätter')} gespeichert`, {
          description: !open.length
            ? 'Alle waren schon analysiert – die Ergebnisse stehen in der Liste.'
            : ai.data?.enabled === false
              ? 'Die KI-Analyse ist ausgeschaltet – analysiert wird erst nach dem Einschalten.'
              : 'Für die Analyse fehlt ein Claude-API-Schlüssel – nach dem Einrichten lässt sie sich je Datenblatt starten.',
          action: aiReady || !open.length ? undefined : { label: 'KI einrichten', onClick: () => navigate('/einstellungen#ki') },
        })
      }
      if (opts.open !== false) navigate('/import')
    },
    [ai.data?.enabled, aiReady, importFile, navigate, qc, startError],
  )

  /** Bestätigter Stapel: die gewählten Datenblätter analysieren (Fortschritt in der Liste, Toast je Ergebnis). */
  const analyzeBatch = useCallback(
    async (ids: string[]): Promise<number> => {
      let started = 0
      for (const id of ids) {
        try {
          await analyzeExisting(id, null, { background: true })
          started += 1
        } catch (e) {
          startError('Analyse konnte nicht starten', e)
          // ohne Claude startet auch keine weitere – nicht je Datenblatt denselben Fehler melden
          if (aiUnavailable(e)) break
        }
      }
      return started
    },
    [analyzeExisting, startError],
  )

  /**
   * Datenblatt von einer Web-Adresse laden. Analysiert wird erst danach (Analyseansicht, `continueAfterDownload`) –
   * so kostet ein PDF, das schon analysiert in der Bibliothek liegt, nichts ein zweites Mal. `searchJobId` = die
   * Datenblattsuche, die den Link gefunden hat (ihre Kosten werden dem Datenblatt zugerechnet).
   */
  const startUrl = useCallback(
    async (url: string, opts: { searchJobId?: string | null } = {}): Promise<boolean> => {
      setBusy('Download wird gestartet …')
      try {
        const { job } = await datasheetsApi.fromUrl({ url, extract: false, search_job_id: opts.searchJobId ?? null })
        trackJob(job, { dock: false, toast: false })
        useActiveImports.getState().startUrl(job.id, url, opts.searchJobId)
        navigate(`/import?job=${encodeURIComponent(job.id)}`)
        return true
      } catch (e) {
        startError('Download nicht möglich', e)
        return false
      } finally {
        setBusy(null)
      }
    },
    [navigate, startError],
  )

  /** Vorhandenes Datenblatt (erneut) analysieren und die Analyseansicht öffnen. */
  const reanalyze = useCallback(
    async (datasheetId: string, options?: Partial<ExtractOptions> | null): Promise<boolean> => {
      try {
        const jobId = await analyzeExisting(datasheetId, options)
        navigate(importPath(datasheetId, jobId))
        return true
      } catch (e) {
        startError('Analyse konnte nicht starten', e)
        return false
      }
    },
    [analyzeExisting, navigate, startError],
  )

  /** Nach dem Download einer Web-Adresse: vorhandenes Ergebnis öffnen oder (mit Schlüssel) die Analyse starten. */
  const continueAfterDownload = useCallback(
    async (datasheetId: string) => {
      try {
        const ds = await datasheetsApi.detail(datasheetId)
        if (ds.has_extraction) {
          toast.info(`„${ds.original_name}“ ist bereits analysiert`, {
            id: `ds-known-${ds.id}`,
            description: 'Das vorhandene Ergebnis wird geöffnet. Eine neue Analyse startet „Neu analysieren“.',
          })
        } else if (analysisFailed(ds)) {
          toast.info(`Die letzte Analyse von „${ds.original_name}“ ist fehlgeschlagen`, {
            id: `ds-failed-${ds.id}`,
            description: 'Ursache und Kosten stehen in der Ansicht. Ein neuer Versuch kostet erneut – dort lässt er sich starten.',
          })
        } else if (aiReady) {
          const jobId = await analyzeExisting(ds.id)
          navigate(importPath(ds.id, jobId), { replace: true })
          return
        }
      } catch (e) {
        startError('Analyse konnte nicht starten', e)
      }
      navigate(importPath(datasheetId), { replace: true })
    },
    [aiReady, analyzeExisting, navigate, startError],
  )

  return {
    startFiles,
    startUrl,
    reanalyze,
    analyzeBatch,
    continueAfterDownload,
    startError,
    aiReady,
    aiStatus: ai.data,
    aiLoading: ai.isLoading,
    busy,
  }
}
