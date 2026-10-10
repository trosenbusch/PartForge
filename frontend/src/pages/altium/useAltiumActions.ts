import { useI18n, localizeMessage } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import {
  altiumApi,
  altiumKeys,
  useRegenerateDblib,
  type AltiumStatus,
  type DbLibRegenerateResult,
  type JobStart,
  type OdbcReport,
  type VerifyInput,
} from '@/api/altium'
import { api, cleanErrorText, errorMessage } from '@/api/client'
import { fetchJob, jobOutcome, trackJob, useJob, type TrackJobOptions } from '@/api/jobs'
import {
  librariesApi,
  librariesKeys,
  mergeHealth,
  REPAIR_HEIGHTS_TITLE,
  RESTORE_BACKUP_TITLE,
  type HealthItem,
  type HeightRepairResult,
  type LibraryRestoreResult,
} from '@/api/libraries'
import { libraryKeys } from '@/api/library'
import { queryClient } from '@/api/queryClient'
import { isJobActive, isJobFinished, isJobResultTruncated, systemKeys, useLibraryJobs, useSettings, type Job } from '@/api/system'
import { ALTIUM_PATH, altiumActionState } from '@/app/navigation'
import { confirm } from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import {
  dblibIssue,
  duplicatesReplaceable,
  NEEDS_ALTIUM,
  uninstallWarning,
  VERIFY_SAMPLE,
  writerMissingText,
  writerLabel,
  type ActionKey,
  type UninstallResult,
} from './model'
import { SETTINGS_PLACE } from './settingsPlaces'

const isHeightsJob = (j: Pick<Job, 'kind' | 'title'>) => j.kind === 'libraries.sync' && j.title === REPAIR_HEIGHTS_TITLE
const isRestoreJob = (j: Pick<Job, 'kind' | 'title'>) => j.kind === 'libraries.sync' && j.title === RESTORE_BACKUP_TITLE
const isSyncJob = (j: Pick<Job, 'kind' | 'title'>) =>
  j.kind === 'libraries' || (j.kind === 'libraries.sync' && !isHeightsJob(j) && !isRestoreJob(j))
const ofKind =
  (...kinds: string[]) =>
  (j: Pick<Job, 'kind' | 'title'>) =>
    kinds.includes(j.kind)

/** Laufende Jobs je Aktion („läuft gerade“ am Knopf) – „Footprint-Höhen nachtragen“ ist auch `libraries.sync` */
const JOB_MATCH: Partial<Record<ActionKey, (j: Pick<Job, 'kind' | 'title'>) => boolean>> = {
  odbc: ofKind('altium.odbc_test'),
  installState: ofKind('altium.install_state'),
  install: ofKind('altium.install'),
  installReplace: ofKind('altium.install'),
  uninstall: ofKind('altium.uninstall'),
  refresh: ofKind('altium.refresh'),
  refreshRebuild: ofKind('altium.refresh'),
  verify: ofKind('altium.verify'),
  open: ofKind('altium.open'),
  sync: isSyncJob,
  scan: ofKind('libraries.scan'),
  scanSync: (j) => j.kind === 'libraries.scan' || isSyncJob(j),
  repairHeights: isHeightsJob,
  restoreBackup: isRestoreJob,
}

const ALL_KEYS: ActionKey[] = [
  'regenerate',
  'preview',
  'odbc',
  'sync',
  'scan',
  'scanSync',
  'repairHeights',
  'restoreBackup',
  'install',
  'installReplace',
  'uninstall',
  'installState',
  'refresh',
  'refreshRebuild',
  'verify',
  'open',
  'settings',
  'writer',
  'report',
  'check',
  'normalize',
  'series',
  'reload',
]

/** Standard von „In Altium prüfen“: Stichprobe über alle Kategorien (deterministisch, mindestens eins je Kategorie) */
export const VERIFY_SAMPLE_INPUT: VerifyInput = { limit: VERIFY_SAMPLE, all: false, sample: 'spread' }

export interface StartOptions<TResult = unknown> {
  /** Job-Dock aufklappen (Standard: ja; Aktionen mit eigener Anzeige: nein) */
  openDock?: boolean
  /** Abschluss-Toast (Standard: ja; `false`, solange die Seite das Ergebnis selbst zeigt) */
  toast?: boolean
  doneMessage?: TrackJobOptions<TResult>['doneMessage']
  warnWhen?: TrackJobOptions<TResult>['warnWhen']
}

/**
 * Rückmeldung, sobald ein Job beendet ist – unabhängig von der Seite (überlebt Seitenwechsel): beobachtet den
 * Job-Schnappschuss im Query-Cache bzw. die Job-Liste des Docks. Die Liste hält nur Kurzfassungen – ist das Ergebnis
 * gekürzt, wird der volle Schnappschuss nachgeladen (`fetchJob`), bevor `onFinished` ihn bekommt.
 */
function whenFinished(id: string, onFinished: (job: Job) => void): void {
  const cache = queryClient.getQueryCache()
  let finished = false
  const check = () => {
    if (finished) return
    const cached = queryClient.getQueryData<Job>(systemKeys.job(id))
    const fromList = queryClient.getQueryData<Job[]>(systemKeys.jobs())?.find((j) => j.id === id)
    const job = cached && isJobFinished(cached) ? cached : (fromList ?? cached)
    if (!job || !isJobFinished(job)) return
    finished = true
    unsubscribe()
    clearTimeout(timer)
    // Einträge der Jobliste sind Kurzfassungen (ohne Protokoll, große Ergebnisse gekürzt) – dann den vollen Schnappschuss
    if (job !== cached || isJobResultTruncated(job)) {
      fetchJob(id).then(onFinished, () => onFinished(job))
    } else {
      onFinished(job)
    }
  }
  const unsubscribe = cache.subscribe((event) => {
    if (event.type === 'updated' && event.query.queryKey[0] === 'system') check()
  })
  const timer = setTimeout(unsubscribe, 60 * 60_000) // Sicherheitsnetz: nach einer Stunde nicht mehr warten
  check()
}

/** „Kapazität: „10 k“ ist nicht im Standardformat („10kΩ“).“ → „„10 k“ → „10kΩ““ */
function formatExample(items: HealthItem[]): string | null {
  for (const i of items) {
    const m = /„([^“]+)“ ist nicht im Standardformat \(„([^“]+)“\)/.exec(i.message)
    if (m) return `„${m[1]}“ → „${m[2]}“`
  }
  return null
}

/** Rückmeldung von „DbLib neu erzeugen“: Grund in den Worten des Backends (`reason_text`), Hinweise dahinter */
function regenerateToast(result: DbLibRegenerateResult): void {
  const description = [result.reason_text, ...result.warnings].filter(Boolean).map(localizeMessage).join(' ')
  if (result.written) toast.success(tr("DbLib neu erzeugt"), { id: 'dblib-regenerate', description })
  else toast.success(tr("DbLib geprüft"), { id: 'dblib-regenerate', description })
}

/** Zuletzt ausgeführtes „DbLib neu erzeugen“ dieser Sitzung (Kette der Altium-Seite) */
export interface RegenerateReceipt {
  result: DbLibRegenerateResult
  at: number
}

export function useAltiumActions() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const regen = useRegenerateDblib()
  // „läuft gerade“ nur für Jobs dieser Bibliothek (ein Job einer anderen Bibliothek gehört nicht auf diese Seite)
  const jobs = useLibraryJobs().data
  const backend = useSettings().data?.settings.altium.library_backend
  const [starting, setStarting] = useState<Partial<Record<ActionKey, boolean>>>({})
  /** Doppelklick-Schutz für Aktionen ohne Job (Zustand ist asynchron, die Referenz nicht) */
  const busy = useRef<Partial<Record<ActionKey, boolean>>>({})
  /** zuletzt gestarteter Job – nach Ende (auch bei Fehlern) den Status neu laden */
  const [watched, setWatched] = useState<string | null>(null)

  useJob(watched, {
    onDone: () => void qc.invalidateQueries({ queryKey: altiumKeys.all }),
    onFailed: () => void qc.invalidateQueries({ queryKey: altiumKeys.all }),
    onCancelled: () => void qc.invalidateQueries({ queryKey: altiumKeys.all }),
  })

  const setFlag = (key: ActionKey, value: boolean) => {
    busy.current[key] = value
    setStarting((s) => ({ ...s, [key]: value }))
  }

  const active = (jobs ?? []).filter(isJobActive)
  const isPending = (key: ActionKey) => {
    const match = JOB_MATCH[key]
    return Boolean(starting[key]) || (match ? active.some(match) : false) || (key === 'regenerate' && regen.isPending)
  }
  const pending = Object.fromEntries(ALL_KEYS.map((k) => [k, isPending(k)])) as Record<ActionKey, boolean>

  /** Läuft Altium? Bei veraltetem Status einmal frisch nachfragen; sonst ein klarer Hinweis statt eines 503. */
  async function ensureAltium(): Promise<boolean> {
    let status = qc.getQueryData<AltiumStatus>(altiumKeys.status)
    if (!status?.altium_running) {
      try {
        status = await qc.fetchQuery({ queryKey: altiumKeys.status, queryFn: ({ signal }) => altiumApi.status(signal), staleTime: 0 })
      } catch {
        return true // Status unbekannt – das Backend entscheidet und meldet sich verständlich
      }
    }
    if (!status) return true
    if (!status.altium_exe) {
      toast.warning(tr("Altium Designer wurde nicht gefunden"), {
        id: 'altium-missing',
        description: tr("Pfad zu X2.EXE unter {0} festlegen.", { "0": String(SETTINGS_PLACE.altium.label) }),
        action: { label: tr("Einstellungen"), onClick: () => navigate(SETTINGS_PLACE.altium.to) },
      })
      return false
    }
    if (!status.altium_running) {
      toast.warning(tr("Altium Designer ist nicht gestartet"), {
        id: 'altium-not-running',
        description: tr("Installieren, Aktualisieren und Prüfen brauchen ein laufendes Altium Designer – bitte starten und erneut versuchen."),
      })
      return false
    }
    return true
  }

  /**
   * Schreibt gerade ein Bibliotheks-Writer? Ohne Writer (kein altium-designer-mcp.exe, Altium nicht gestartet) bliebe
   * „Synchronisieren“ wirkungslos – stattdessen ein Hinweis mit dem Weg zum Writer-Pfad (bei veraltetem Status frisch
   * nachgefragt; unbekannter Status: das Backend entscheidet).
   */
  async function ensureWriter(): Promise<boolean> {
    const ready = (s: AltiumStatus | undefined) => !s || writerLabel(s, backend).ok
    let status = qc.getQueryData<AltiumStatus>(altiumKeys.status)
    if (!status || !ready(status)) {
      try {
        status = await qc.fetchQuery({ queryKey: altiumKeys.status, queryFn: ({ signal }) => altiumApi.status(signal), staleTime: 0 })
      } catch {
        return true
      }
    }
    if (ready(status)) return true
    toast.warning(tr("Kein Bibliotheks-Writer verfügbar"), {
      id: 'writer-missing',
      description: `${writerMissingText()}.`,
      duration: 10_000,
      action: { label: tr("Writer einrichten"), onClick: () => navigate(SETTINGS_PLACE.altium.to) },
    })
    return false
  }

  async function start<TResult = unknown>(
    key: ActionKey,
    errorTitle: string,
    run: () => Promise<JobStart>,
    opts: StartOptions<TResult> = {},
  ): Promise<Job | null> {
    if (NEEDS_ALTIUM.includes(key) && !(await ensureAltium())) return null
    setFlag(key, true)
    try {
      const { job } = await run()
      trackJob(job as Job<TResult>, {
        openDock: opts.openDock ?? true,
        toast: opts.toast,
        doneMessage: opts.doneMessage,
        warnWhen: opts.warnWhen,
      })
      setWatched(job.id)
      return job
    } catch (err) {
      toast.error(errorTitle, { description: cleanErrorText(errorMessage(err)) })
      return null
    } finally {
      setFlag(key, false)
    }
  }

  // ------------------------------------------------------------------ DbLib

  const [lastRegenerate, setLastRegenerate] = useState<RegenerateReceipt | null>(null)

  async function regenerate() {
    try {
      const result = await regen.mutateAsync()
      setLastRegenerate({ result, at: Date.now() })
      regenerateToast(result)
    } catch {
      // Toast kommt über meta.errorTitle
    }
  }

  /**
   * ODBC-Test: Der Job endet mit seiner Zusammenfassung als Meldung („ODBC-Verbindung in Ordnung: 13 Tabellen …“ bzw.
   * „ODBC-Test fehlgeschlagen: …“) – sie ist der Text des Toasts; ein fehlgeschlagener Test ist eine Warnung.
   */
  const odbc = (opts?: Omit<StartOptions<OdbcReport>, 'warnWhen'>) =>
    start<OdbcReport>('odbc', tr("ODBC-Test konnte nicht starten"), () => altiumApi.odbcTest(), {
      ...opts,
      warnWhen: (j) => (j.result && j.result.ok === false ? j.message || j.result.summary || tr("ODBC-Test fehlgeschlagen") : null),
    })

  // ------------------------------------------------------------------ Bibliotheksdateien

  async function sync() {
    if (!(await ensureWriter())) return null
    return start('sync', tr("Synchronisieren konnte nicht starten"), librariesApi.sync)
  }
  const scan = (registerUnknown = false) =>
    start('scan', tr("Prüfen konnte nicht starten"), () => librariesApi.scan(registerUnknown))

  /** Erst prüfen (fehlende Einträge werden vorgemerkt), dann synchronisieren – auch wenn die Seite gewechselt wird */
  async function scanThenSync() {
    if (!(await ensureWriter())) return
    const job = await start('scanSync', tr("Prüfen konnte nicht starten"), () => librariesApi.scan(false))
    if (!job) return
    whenFinished(job.id, (done) => {
      if (done.status !== 'done') return
      librariesApi
        .sync()
        .then(({ job: next }) => trackJob(next))
        .catch((err: unknown) => toast.error(tr("Synchronisieren konnte nicht starten"), { description: cleanErrorText(errorMessage(err)) }))
    })
  }

  /**
   * „Footprint-Höhen nachtragen“: schreibt die Footprints, deren PcbLib die Höhe 0 trägt, über den normalen Weg neu
   * (außerhalb geänderte Bibliotheken überspringt das Backend). Ohne Namen alle betroffenen.
   */
  const repairHeights = (names?: string[]) =>
    start<HeightRepairResult>('repairHeights', tr("Footprint-Höhen konnten nicht nachgetragen werden"), () => librariesApi.repairHeights(names), {
      warnWhen: (j) => {
        const r = j.result
        if (!r) return null
        return r.errors?.length || r.remaining?.length || r.skipped?.length ? j.message || r.message : null
      },
    })

  /**
   * „Aus Sicherung wiederherstellen“ (Befund `library_unreadable`): je beschädigte Datei ein Job, nacheinander – er
   * holt die neueste lesbare Sicherung aus Backups\lib zurück (die beschädigte bleibt als …defekt dort) und schreibt
   * die Einträge von PartForge neu. Braucht einen Bibliotheks-Writer.
   */
  async function restoreBackup(libraries: string[]): Promise<void> {
    const queue = [...new Set(libraries)]
    if (!queue.length || !(await ensureWriter())) return
    const next = async (): Promise<void> => {
      const library = queue.shift()
      if (!library) return
      const job = await start<LibraryRestoreResult>('restoreBackup', tr("Wiederherstellen konnte nicht starten"), () => librariesApi.restoreBackup(library), {
        warnWhen: (j) => (j.result?.errors?.length ? j.message || j.result.message : null),
      })
      if (job && queue.length) whenFinished(job.id, () => void next())
    }
    await next()
  }

  // ------------------------------------------------------------------ Prüfbericht

  /**
   * Bibliothek prüfen: Daten-, Datei- und DbLib-Prüfung neu – die Meldung sagt ehrlich, was geprüft wurde
   * (beide gescheitert = Fehler, eine gescheitert = Warnung „nur teilweise geprüft“).
   */
  async function checkLibrary(): Promise<void> {
    if (busy.current.check) return
    setFlag('check', true)
    const id = toast.loading(tr("Bibliothek wird geprüft …"), { id: 'library-check', description: undefined })
    try {
      const [data, files, status] = await Promise.allSettled([
        qc.fetchQuery({ queryKey: librariesKeys.dataHealth, queryFn: ({ signal }) => librariesApi.dataHealth(signal), staleTime: 0 }),
        qc.fetchQuery({ queryKey: librariesKeys.fileHealth, queryFn: ({ signal }) => librariesApi.fileHealth(signal), staleTime: 0 }),
        qc.fetchQuery({ queryKey: altiumKeys.status, queryFn: ({ signal }) => altiumApi.status(signal), staleTime: 0 }),
      ])
      const retry = { label: tr("Erneut prüfen"), onClick: () => void checkLibrary() }
      const failures = [
        data.status === 'rejected' ? tr("Datenprüfung: {0}", { "0": String(errorMessage(data.reason)) }) : null,
        files.status === 'rejected' ? tr("Dateiprüfung: {0}", { "0": String(errorMessage(files.reason)) }) : null,
        status.status === 'rejected' ? tr("DbLib-Status: {0}", { "0": String(errorMessage(status.reason)) }) : null,
      ].filter((f): f is string => f !== null)
      if (data.status === 'rejected' && files.status === 'rejected') {
        toast.error(tr("Prüfung fehlgeschlagen"), { id, description: failures.join(' · '), action: retry, duration: 10_000 })
        return
      }
      const report = mergeHealth(
        data.status === 'fulfilled' ? data.value : undefined,
        files.status === 'fulfilled' ? files.value : undefined,
        status.status === 'fulfilled' ? status.value.dblib : qc.getQueryData<AltiumStatus>(altiumKeys.status)?.dblib,
      )
      const { error, warning, info } = report.counts
      const counts = [
        error && plural(error, 'Fehler', 'Fehler'),
        warning && plural(warning, tr("Warnung"), tr("Warnungen")),
        info && plural(info, tr("Hinweis"), tr("Hinweise")),
      ].filter(Boolean)
      const summary = counts.length ? counts.join(' · ') : tr("keine Befunde")
      if (failures.length) {
        toast.warning(tr("Bibliothek nur teilweise geprüft"), {
          id,
          description: tr("{0}. Bisher: {1}.", { "0": String(failures.join(' · ')), "1": String(summary) }),
          action: retry,
          duration: 10_000,
        })
      } else if (error + warning === 0) {
        toast.success(tr("Bibliothek geprüft"), { id, description: info ? tr("Keine Fehler oder Warnungen · {0}", { "0": String(summary) }) : tr("Keine Probleme gefunden") })
      } else {
        toast.warning(tr("Bibliothek geprüft"), { id, description: summary })
      }
    } finally {
      setFlag('check', false)
    }
  }

  // ------------------------------------------------------------------ Altium

  const checkInstallState = () =>
    start('installState', tr("Installationsstatus konnte nicht geprüft werden"), altiumApi.installState)

  /** Installieren; gleichnamige alte Installationen dieser Bibliothek werden nur nach Rückfrage ersetzt */
  async function install(replace = false) {
    if (!(await ensureAltium())) return null
    const dblib = qc.getQueryData<AltiumStatus>(altiumKeys.status)?.dblib
    const conflict = dblibIssue(dblib, 'duplicates', 'moved_install')
    let replaceOthers = replace
    if (conflict) {
      if (!duplicatesReplaceable(dblib)) {
        toast.error(tr("DbLib kann nicht installiert werden"), { id: 'dblib-duplicates', description: conflict.message })
        return null
      }
      const ok = await confirm({
        title: tr("Alte Installation ersetzen?"),
        description: conflict.message,
        confirmLabel: tr("Ersetzen und installieren"),
      })
      if (!ok) return null
      replaceOthers = true
    }
    return start(replaceOthers ? 'installReplace' : 'install', tr("Installation konnte nicht starten"), () => altiumApi.install(replaceOthers))
  }

  async function uninstall() {
    if (!(await ensureAltium())) return null
    const ok = await confirm({
      title: tr("DbLib aus Altium deinstallieren?"),
      description:
        tr("Altium gibt die Datenbank frei und entfernt die DbLib aus den installierten Bibliotheken. Bereits platzierte Bauteile bleiben im Schaltplan, lassen sich aber erst nach erneutem Installieren aktualisieren."),
      confirmLabel: tr("Deinstallieren"),
    })
    if (!ok) return null
    // Hält Altium die Datenbank noch offen, ist das ein Hinweis (gelb, „Fertig mit Hinweisen“) mit dem vollen Text –
    // kein grüner, auf 200 Zeichen gekürzter Erfolg (E2EREG-2)
    return start<UninstallResult>('uninstall', tr("Deinstallieren konnte nicht starten"), altiumApi.uninstall, {
      warnWhen: (j) => uninstallWarning(j),
    })
  }

  const refresh = (rebuildIndex: boolean | null = null) =>
    start(rebuildIndex ? 'refreshRebuild' : 'refresh', tr("Aktualisieren konnte nicht starten"), () => altiumApi.refresh(rebuildIndex))

  /**
   * In Altium prüfen (Standard: Stichprobe über alle Kategorien). Mit `resultAction` (Start außerhalb der Altium-Seite)
   * meldet der Abschluss-Toast das Ergebnis mit „Ergebnis ansehen“ – der Bericht steht im Reiter „In Altium geprüft“.
   */
  async function verify(input: VerifyInput = VERIFY_SAMPLE_INPUT, opts: StartOptions & { resultAction?: boolean } = {}) {
    const { resultAction, ...rest } = opts
    const job = await start('verify', tr("Prüfung in Altium konnte nicht starten"), () => altiumApi.verify(input), {
      ...rest,
      toast: resultAction ? false : rest.toast,
    })
    if (job && resultAction) {
      whenFinished(job.id, (done) => {
        const outcome = jobOutcome(done)
        if (!outcome) return
        const show = { label: tr("Ergebnis ansehen"), onClick: () => navigate('/altium?bereich=altium') }
        const id = `job:${done.id}`
        if (outcome.tone === 'success') toast.success(outcome.title, { id, description: outcome.description, action: show })
        else if (outcome.tone === 'warning') toast.warning(outcome.title, { id, description: outcome.description, action: show, duration: 9000 })
        else if (outcome.tone === 'error') toast.error(outcome.title, { id, description: outcome.description, action: show, duration: 10_000 })
        else toast.info(outcome.title, { id, description: outcome.description })
      })
    }
    return job
  }

  const openInAltium = (path?: string) => start('open', tr("Datei konnte nicht in Altium geöffnet werden"), () => altiumApi.open(path))

  /** Status, Dateiliste und Prüfbericht neu laden (nach einem Lesefehler) */
  function reload() {
    void qc.invalidateQueries({ queryKey: altiumKeys.status })
    void qc.invalidateQueries({ queryKey: librariesKeys.files })
    void qc.invalidateQueries({ queryKey: librariesKeys.fileHealth })
    void qc.invalidateQueries({ queryKey: librariesKeys.dataHealth })
  }

  // ------------------------------------------------------------------ Werte vereinheitlichen (Prüfbericht)

  /**
   * „Wert nicht im Standardformat“ beheben: den gespeicherten Text unverändert zurückschreiben – das Backend
   * normalisiert ihn dabei (derselbe Weg wie beim Speichern im Formular). Jede Änderung steht in der Historie.
   * Läuft schon ein Durchgang, passiert nichts (Doppelklick startet keinen zweiten).
   */
  async function normalize(items: HealthItem[]) {
    if (busy.current.normalize) return
    const byPart = new Map<string, { table: string; pn: string; columns: Set<string> }>()
    for (const i of items) {
      if (!i.table || !i.part_number || !i.column) continue
      const key = `${i.table}|${i.part_number}`
      const entry = byPart.get(key) ?? { table: i.table, pn: i.part_number, columns: new Set<string>() }
      entry.columns.add(i.column)
      byPart.set(key, entry)
    }
    const parts = [...byPart.values()]
    const values = parts.reduce((n, p) => n + p.columns.size, 0)
    if (!parts.length) return
    setFlag('normalize', true)
    try {
      const example = formatExample(items)
      const ok = await confirm({
        title: tr("{0} vereinheitlichen?", { "0": String(plural(values, tr("Wert"), tr("Werte"))) }),
        description: tr("PartForge speichert {0} von {1} im Standardformat{2}. Jede Änderung steht in der Historie des Bauteils.", { "0": String(values === 1 ? tr("den Wert") : tr("die Werte")), "1": String(plural(parts.length, tr("Bauteil"), tr("Bauteilen"))), "2": String(example ? tr(" (z. B. {0})", { 0: String(example) }) : '') }),
        confirmLabel: tr("Vereinheitlichen"),
      })
      if (!ok) return
      const id = toast.loading(tr("Werte werden vereinheitlicht … 0 von {0}", { "0": String(formatNumber(parts.length)) }))
      let done = 0
      let failed = 0
      let firstError = ''
      const queue = [...parts]
      const worker = async () => {
        for (let p = queue.shift(); p; p = queue.shift()) {
          const path = `/api/parts/${encodeURIComponent(p.table)}/${encodeURIComponent(p.pn)}`
          try {
            const row = await api.get<Record<string, string | null>>(path)
            const patch = Object.fromEntries([...p.columns].map((c) => [c, row[c] ?? '']))
            await api.patch(path, { values: patch, allow_incomplete: true })
          } catch (err) {
            failed += 1
            firstError ||= `${p.pn}: ${cleanErrorText(errorMessage(err))}`
          } finally {
            done += 1
            toast.loading(tr("Werte werden vereinheitlicht … {0} von {1}", { "0": String(formatNumber(done)), "1": String(formatNumber(parts.length)) }), { id })
          }
        }
      }
      await Promise.all([worker(), worker(), worker()])
      if (failed) toast.error(tr("{0} nicht geändert", { "0": String(plural(failed, tr("Bauteil"), tr("Bauteile"))) }), { id, description: firstError })
      else toast.success(tr("{0} vereinheitlicht", { "0": String(plural(values, tr("Wert"), tr("Werte"))) }), { id })
      void qc.invalidateQueries({ queryKey: librariesKeys.all })
      void qc.invalidateQueries({ queryKey: ['parts'] })
      void qc.invalidateQueries({ queryKey: libraryKeys.stats })
    } finally {
      setFlag('normalize', false)
    }
  }

  // ------------------------------------------------------------------ Verteiler (Knöpfe, Behebungen, Übersicht)

  function run(action: ActionKey): void {
    switch (action) {
      case 'regenerate':
        void regenerate()
        break
      case 'odbc':
        navigate(ALTIUM_PATH, { state: altiumActionState('odbc') }) // Bericht im Dialog der Altium-Seite
        break
      case 'preview':
        navigate(ALTIUM_PATH, { state: altiumActionState('vorschau') })
        break
      case 'report':
        navigate('/altium?bereich=pruefbericht')
        break
      case 'sync':
        void sync()
        break
      case 'scan':
        void scan(false)
        break
      case 'scanSync':
        void scanThenSync()
        break
      case 'repairHeights':
        void repairHeights()
        break
      case 'install':
        void install(false)
        break
      case 'installReplace':
        void install(true)
        break
      case 'uninstall':
        void uninstall()
        break
      case 'installState':
        void checkInstallState()
        break
      case 'refresh':
        void refresh(null)
        break
      case 'refreshRebuild':
        void refresh(true)
        break
      case 'verify':
        void verify(VERIFY_SAMPLE_INPUT, { resultAction: true })
        break
      case 'open':
        void openInAltium()
        break
      case 'settings':
      case 'writer':
        navigate(SETTINGS_PLACE.altium.to)
        break
      case 'check':
        void checkLibrary()
        break
      case 'series':
        navigate('/serien')
        break
      case 'reload':
        reload()
        break
      case 'normalize':
        break // braucht die Befunde – über normalize(items)
      case 'restoreBackup':
        break // braucht die Dateien der Befunde – über restoreBackup(libraries)
    }
  }

  return {
    run,
    regenerate,
    lastRegenerate,
    odbc,
    sync,
    scan,
    scanThenSync,
    repairHeights,
    restoreBackup,
    checkLibrary,
    checkInstallState,
    install,
    uninstall,
    refresh,
    verify,
    openInAltium,
    reload,
    normalize,
    ensureAltium,
    pending,
  }
}

export type AltiumActions = ReturnType<typeof useAltiumActions>

/**
 * Neuester Job einer Art **der geöffneten Bibliothek** aus der Job-Liste (geteilt mit dem Job-Dock – keine zusätzlichen
 * Abfragen; eine Prüfung, die vor einem Bibliothekswechsel startete, erscheint nicht bei der neuen Bibliothek). Die
 * Liste hält **Kurzfassungen**: für Status und Fortschritt genügt das; das volle Ergebnis über `useJobResult`/`fetchJob`.
 */
export function useLatestJob(kind: string): Job | undefined {
  const jobs = useLibraryJobs().data
  return useMemo(() => (jobs ?? []).filter((j) => j.kind === kind).sort((a, b) => b.created - a.created)[0], [jobs, kind])
}
