import { t as tr, localizeMessage } from '@/lib/i18n'
import { useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ALTIUM_PATH, altiumActionState, appNavigate, type AltiumActionState } from '@/app/navigation'
import { useJobDock } from '@/app/stores'
import { formatNumber, formatNumbersInText } from '@/lib/format'
import { SETTINGS_PLACE } from '@/lib/settingsPlaces'
import { apiUrl, cleanErrorText } from './client'
import { queryClient } from './queryClient'
import {
  isJobActive,
  isJobFinished,
  isJobResultTruncated,
  isLibrarySwitchCancel,
  JOB_CANCEL_LIBRARY_SWITCH,
  noteAiJobFailure,
  systemApi,
  systemKeys,
  upsertJobInLists,
  type Job,
} from './system'

export interface UseJobOptions<TResult> {
  /** Job erfolgreich beendet (einmal je Job-ID) */
  onDone?: (job: Job<TResult>) => void
  /** Job fehlgeschlagen */
  onFailed?: (job: Job<TResult>) => void
  /** Job abgebrochen */
  onCancelled?: (job: Job<TResult>) => void
  /** Polling-Intervall im Fallback-Modus (ms), Standard 750 */
  pollInterval?: number
}

export interface UseJobResult<TResult> {
  job: Job<TResult> | undefined
  isActive: boolean
  isFinished: boolean
  /** true, solange der SSE-Stream verbunden ist */
  isStreaming: boolean
  error: Error | null
}

/** Schnappschuss nur übernehmen, wenn er nicht älter als der vorhandene ist. */
function newer<T>(next: Job<T>, current: Job<T> | undefined): Job<T> {
  return current && current.version > next.version ? current : next
}

/**
 * Schnappschuss im Job-Cache (`useJob`) und in den Joblisten (Job-Dock) ablegen – so zeigen Seite und Dock denselben
 * Stand. Kurzfassungen (`result_truncated`) gehören nur in die Listen: der Job-Cache hält immer das volle Ergebnis.
 */
function storeSnapshot<T>(qc: QueryClient, job: Job<T>): void {
  if (!isJobResultTruncated(job)) qc.setQueryData<Job<T>>(systemKeys.job(job.id), (current) => newer(job, current))
  upsertJobInLists(qc, job as Job)
  noteJobSnapshot(job as Job)
}

// --------------------------------------------------------------------------- Rückmeldung (Toasts)

export interface TrackJobOptions<TResult = unknown> {
  /**
   * @deprecated Ohne Wirkung: Das Panel des Job-Docks öffnet sich nie von selbst – es verdeckte sonst Inhalte der
   * Seite (z. B. die Aktionsleiste der Altium-Seite). Der neue Job erscheint in der Pille; das Panel öffnet ein Klick
   * darauf, „Details“ eines Job-Toasts oder `useJobDock.getState().setOpen(true)`.
   */
  openDock?: boolean
  /**
   * In der Pille des Job-Docks zählen (Standard: ja). `false`, solange die Seite den Job inline zeigt (Fortschritt,
   * Ergebnis): Er treibt dann weder Ring, Zähler noch Einblenden der Pille – im aufgeklappten Panel steht er weiter.
   * Zurückgeben mit `setJobFeedback(id, { dock: true })`; bequemer: {@link useInlineJob}.
   */
  dock?: boolean
  /**
   * Abschluss als Toast melden (Standard: ja). `false`, wenn die Seite selbst Rückmeldung gibt (Inline-Fortschritt,
   * Erfolgsbildschirm). Nach erfolgreichem Ende werden die Daten trotzdem neu geladen. Ein Abbruch durch einen
   * Bibliothekswechsel wird **immer** gemeldet (die Seite, die den Job zeigte, gehört zur alten Bibliothek).
   */
  toast?: boolean
  /**
   * Beschreibung des Erfolgs-Toasts (Standard: letzte Meldung des Jobs bzw. „Erfolgreich abgeschlossen“). Zahlen im Text
   * werden deutsch gruppiert (`formatNumbersInText`); bekommt immer das **volle** Ergebnis.
   */
  doneMessage?: string | ((job: Job<TResult>) => string | null | undefined)
  /**
   * Probleme im Ergebnis erkennen → Warn-Toast (mit „Details“) statt Erfolg; Rückgabe = Beschreibung, `null` = kein
   * Problem. Ersetzt die Standarderkennung {@link jobResultProblem} (die sich darin selbst aufrufen lässt).
   */
  warnWhen?: (job: Job<TResult>) => string | null | undefined
}

type FeedbackOptions = Omit<TrackJobOptions<never>, 'openDock'>

/** Rückmeldeoptionen je Job-ID (aus `trackJob`/`setJobFeedback`) */
const feedback = new Map<string, FeedbackOptions>()
/** In dieser Sitzung laufend gesehene Jobs – nur deren Abschluss wird gemeldet (nicht alte, längst fertige) */
const seenActive = new Set<string>()
/** Bereits gemeldete Abschlüsse (genau ein Toast je Job, egal ob per SSE, Polling oder Jobliste erkannt) */
const announced = new Set<string>()

export type JobOutcomeTone = 'success' | 'warning' | 'error' | 'info'

/** Behebung eines Problems – Knopf in Toasts und eigenen Anzeigen („Writer einrichten“ → Einstellungen) */
export interface JobOutcomeAction {
  label: string
  /** Ziel in der App, z. B. `/einstellungen#altium` (über `navigate`/`appNavigate`) */
  to: string
  /** Router-State des Ziels – die Aktion der Altium-Seite (`altiumActionState('sync')`), nie als `?aktion=` */
  state?: AltiumActionState
}

export interface JobOutcome {
  tone: JobOutcomeTone
  title: string
  /** Kurzfassung für Toasts (höchstens 200 Zeichen, am Satz- bzw. Wortende gekürzt) */
  description: string
  /** Problem aus dem Ergebnis (Warnung) bzw. Fehlertext – **ungekürzt** (Inline-Anzeigen, Tooltips) */
  problem: string | null
  /** Behebung, wenn PartForge eine kennt (fehlender Bibliotheks-Writer, nicht geschriebene Bibliothekseinträge) */
  action: JobOutcomeAction | null
}

/** Typische Abkürzungen, nach deren Punkt kein Satz endet („z. B.“, „ca.“, „Nr.“) */
const ABBREVIATION = /(?:^|[\s(„"])(?:[a-zäöü]|ca|bzw|usw|vgl|ggf|inkl|evtl|bspw|nr|max|min|etc|sog|zzgl|abs)\.$/i

/**
 * Text auf höchstens `max` Zeichen kürzen – bevorzugt am Satzende, sonst am Wortende, nie mitten im Wort
 * („Bitte den Rust- …“). Gekürzte Texte enden auf „ …“.
 */
export function clipText(text: string, max = 200): string {
  if (text.length <= max) return text
  const head = text.slice(0, max - 2)
  let sentence = -1
  for (let i = head.length - 1; i >= Math.floor(max * 0.45); i--) {
    const ch = head[i]
    if ((ch === '.' || ch === '!' || ch === '?') && /\s/.test(text[i + 1] ?? '') && !ABBREVIATION.test(head.slice(0, i + 1))) {
      sentence = i
      break
    }
  }
  if (sentence >= 0) return `${head.slice(0, sentence + 1)} …`
  const space = head.lastIndexOf(' ')
  const cut = space >= max * 0.45 ? head.slice(0, space) : head
  return `${cut.replace(/[\s,;:–—-]+$/u, '')} …`
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

/** Text einer Seite (`doneMessage`/`warnWhen`) – wirft sie (z. B. bei unerwarteter Ergebnisform), gilt der Standard */
function safely<T>(fn: () => T, fallback: T): T {
  try {
    return fn()
  } catch (err) {
    console.error(err)
    return fallback
  }
}

function describeItem(item: unknown): string | null {
  if (typeof item === 'string') return text(item)
  if (item && typeof item === 'object') {
    const rec = item as { name?: unknown; message?: unknown; part_number?: unknown; error?: unknown }
    const name = text(rec.name) ?? text(rec.part_number)
    const message = text(rec.message) ?? text(rec.error)
    if (name && message) return `${name}: ${message}`
    return message ?? name
  }
  return null
}

/** Anzahl und erster Eintrag einer Fehlerliste (`[…]`, `{schlüssel: text}` oder Zahl) */
function problemList(value: unknown): { count: number; first: string | null } {
  if (typeof value === 'number' && Number.isFinite(value)) return { count: Math.max(0, Math.round(value)), first: null }
  if (Array.isArray(value)) return { count: value.length, first: value.length ? describeItem(value[0]) : null }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    const [key, msg] = entries[0] ?? []
    const first = key === undefined ? null : text(msg) ? `${key}: ${text(msg)}` : key
    return { count: entries.length, first }
  }
  return { count: 0, first: null }
}

/** `<name>_count` einer Kurzfassung (Listen/Objekte des Ergebnisses als Anzahl) */
function briefCount(rec: Record<string, unknown>, name: string): number | null {
  const v = rec[`${name}_count`]
  return typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.round(v)) : null
}

const errorsLabel = (n: number) => (n === 1 ? tr("1 Fehler") : tr("{0} Fehler", { "0": String(formatNumber(n)) }))

/**
 * Eintrag von `result.library_problems` (Serie, Datenblatt-Übernahme …): ein Symbol bzw. Footprint, das **nicht** in
 * seine SchLib/PcbLib geschrieben wurde (`status` `error` = Schreiben fehlgeschlagen, `pending` = noch ausstehend,
 * z. B. ohne Bibliotheks-Writer, `missing` = nicht erzeugbar). Die Bauteile verweisen dann auf etwas, das Altium nicht
 * findet. (`partforge.domain.series.LibraryProblem`)
 */
export interface LibraryProblem {
  /** `symbol` | `footprint` (ältere Ergebnisse: aus der Dateiendung) */
  kind?: 'symbol' | 'footprint' | string | null
  name: string
  /** Bibliotheksdatei, relativ zum Bibliotheksordner, z. B. `Footprints\PF_CHIP.PcbLib` */
  library?: string | null
  status?: 'error' | 'pending' | 'missing' | string | null
  /** deutscher Grund (z. B. „Datei gesperrt“) */
  message?: string | null
  /** Zeilen (Bauteile), die dieses Symbol bzw. diesen Footprint verwenden */
  parts?: number
}

/** `result.library_problems` eines Ergebnisses (leer, wenn es keine gibt bzw. nur die Anzahl der Kurzfassung) */
export function jobLibraryProblems(result: unknown): LibraryProblem[] {
  if (!result || typeof result !== 'object') return []
  const list = (result as { library_problems?: unknown }).library_problems
  return Array.isArray(list) ? list.filter((p): p is LibraryProblem => Boolean(p && typeof p === 'object' && 'name' in p)) : []
}

function problemKind(p: LibraryProblem): 'symbol' | 'footprint' | null {
  if (p.kind === 'symbol' || p.kind === 'footprint') return p.kind
  if (/\.pcblib$/i.test(p.library ?? '')) return 'footprint'
  if (/\.schlib$/i.test(p.library ?? '')) return 'symbol'
  return null
}

/** Dateiname der Bibliotheksdatei („Footprints\PF_CHIP.PcbLib“ → „PF_CHIP.PcbLib“) */
const libraryFile = (p: LibraryProblem) => text(p.library)?.split(/[\\/]/).pop() ?? null

function problemReason(p: LibraryProblem): string {
  return (
    text(p.message) ?? (p.status === 'pending' ? tr("noch ausstehend") : p.status === 'missing' ? tr("nicht erzeugbar") : tr("Schreiben fehlgeschlagen"))
  )
}

/** „Footprint“, „2 Symbole“, „3 Bibliothekseinträge“ (gemischt bzw. unbekannt) */
function libraryItemsLabel(problems: LibraryProblem[], count: number): string {
  const kinds = new Set(problems.map(problemKind))
  const only = problems.length > 0 && kinds.size === 1 ? [...kinds][0] : null
  if (only === 'footprint') return count === 1 ? 'Footprint' : `${formatNumber(count)} Footprints`
  if (only === 'symbol') return count === 1 ? 'Symbol' : tr("{0} Symbole", { "0": String(formatNumber(count)) })
  return count === 1 ? tr("1 Bibliothekseintrag") : tr("{0} Bibliothekseinträge", { "0": String(formatNumber(count)) })
}

function describeLibraryProblem(p: LibraryProblem): string {
  const file = libraryFile(p)
  return `${p.name}${file ? ` (${file})` : ''}: ${problemReason(p)}`
}

/** Text für `library_problems` (auch Kurzfassungen mit `library_problems_count`) oder `null` */
function libraryProblemText(rec: Record<string, unknown>): string | null {
  const problems = jobLibraryProblems(rec)
  const count = briefCount(rec, 'library_problems') ?? problems.length
  if (count <= 0) return null
  const what = libraryItemsLabel(problems, count)
  if (count === 1 && problems.length === 1) {
    const p = problems[0]
    const file = libraryFile(p)
    const reason = problemReason(p)
    // nennt der Grund die Datei schon („PF_CHIP.PcbLib wurde nicht geschrieben – …“), nicht doppelt sagen
    if (file && reason.toLowerCase().includes(file.toLowerCase())) return `${what} ${p.name}: ${reason}`
    return tr("{0} {1} wurde nicht {2} geschrieben – {3}", { "0": String(what), "1": String(p.name), "2": String(file ? `in ${file}` : tr('in die Bibliotheksdatei')), "3": String(reason) })
  }
  const first = problems.length ? describeLibraryProblem(problems[0]) : null
  return tr("{0} nicht in die Bibliotheksdateien geschrieben{1}", { "0": String(what), "1": String(first ? ` – ${first}` : '') })
}

/**
 * Standarderkennung von Problemen im Ergebnis eines **erfolgreich** beendeten Jobs (deutscher Text oder `null`):
 * `skipped: true` (+ `reason`), `outcome: 'partial'`, `error_count > 0`, `errors` (Zahl, Liste oder Objekt),
 * `library_problems` (Symbole/Footprints, die nicht in ihre Bibliotheksdatei geschrieben wurden, `{name, library,
 * status, message}`), `missing` als Liste von Einträgen mit `name` (Bibliotheken schreiben: nicht erzeugbare
 * Symbole/Footprints). Versteht Kurzfassungen der Jobliste (`errors_count`/`missing_count`/`library_problems_count`).
 */
export function jobResultProblem(job: Pick<Job, 'result'>): string | null {
  const r = job.result
  if (!r || typeof r !== 'object' || Array.isArray(r)) return null
  const rec = r as Record<string, unknown>
  if (rec.skipped === true) return text(rec.reason) ?? tr("Übersprungen – es wurde nichts geändert.")
  if (rec.outcome === 'partial') {
    return text(rec.message) ?? text(rec.reason) ?? tr("Nur teilweise abgeschlossen – Details im Protokoll.")
  }
  const errors = problemList(rec.errors)
  const count =
    typeof rec.error_count === 'number' && rec.error_count > 0 ? rec.error_count : (briefCount(rec, 'errors') ?? errors.count)
  if (count > 0) {
    // erster Fehler: aus der Liste, sonst der Grund (nicht geschriebener Footprint …) bzw. `error_details` (Serie)
    const first = errors.first ?? libraryProblemText(rec) ?? problemList(rec.error_details).first
    return `${errorsLabel(count)}${first ? ` – ${first}` : ''}`
  }
  const library = libraryProblemText(rec)
  if (library) return library
  if (Array.isArray(rec.missing) && rec.missing.some((m) => m && typeof m === 'object' && 'name' in m)) {
    const first = describeItem(rec.missing[0])
    const n = briefCount(rec, 'missing') ?? rec.missing.length
    return tr("{0} nicht erzeugbar{1}", { "0": String(n === 1 ? tr('1 Eintrag') : tr('{0} Einträge', {0: formatNumber(n)})), "1": String(first ? ` – ${first}` : '') })
  }
  return null
}

/** Texte, die einen fehlenden Bibliotheks-Writer melden (`partforge.altium.libwriter.WriterUnavailable`) */
const NO_WRITER = /bibliotheks-writer|rust-writer|kein\w*\s+writer|writer\b.*nicht (gefunden|verfügbar)/i

/**
 * Hat der Job nichts geschrieben, weil kein Bibliotheks-Writer verfügbar ist (`skipped: true` mit dem Grund
 * „Kein Bibliotheks-Writer verfügbar …“, auch `code: 'no_writer'`)? Behebung: {@link SETTINGS_PLACE}`.altium`.
 */
export function jobLacksWriter(job: Pick<Job, 'result' | 'message'>): boolean {
  const r = job.result
  if (!r || typeof r !== 'object' || Array.isArray(r)) return false
  const rec = r as Record<string, unknown>
  if (rec.skipped !== true) return false
  if (rec.code === 'no_writer' || rec.reason_code === 'no_writer') return true
  return NO_WRITER.test(`${text(rec.reason) ?? ''} ${text(job.message) ?? ''}`)
}

/** Knopf „Writer einrichten“ → Einstellungen › Allgemein › Altium Designer */
export const SETUP_WRITER_ACTION: JobOutcomeAction = { get label() { return tr("Writer einrichten") }, to: SETTINGS_PLACE.altium.to }
/** Knopf „Synchronisieren“ → Altium › Bibliotheksdateien synchronisieren (Aktion als Router-State) */
export const SYNC_LIBRARIES_ACTION: JobOutcomeAction = {
  get label() { return tr("Synchronisieren") },
  to: ALTIUM_PATH,
  state: altiumActionState('sync'),
}

/** Behebung für das Ergebnis eines beendeten Jobs (oder `null`) */
function outcomeAction(job: Job): JobOutcomeAction | null {
  if (jobLacksWriter(job)) return SETUP_WRITER_ACTION
  // nur ausstehende Einträge holt „Synchronisieren“ nach (die Bauteile sind angelegt); fehlgeschlagene (`error`) heißen:
  // Ursache beheben und den Job wiederholen – dafür gibt es keinen Knopf, „Details“ zeigt das Protokoll
  const pending = jobLibraryProblems(job.result).filter((p) => p.status === 'pending')
  if (!pending.length) return null
  return pending.some((p) => NO_WRITER.test(p.message ?? '')) ? SETUP_WRITER_ACTION : SYNC_LIBRARIES_ACTION
}

/**
 * Warum ein Job abgebrochen wurde – für Toasts, das Job-Dock und eigene Anzeigen. `short` = Statuszeile.
 * Bibliothekswechsel (`cancel_reason: 'library_switch'`): der Job hat in die andere Bibliothek nichts geschrieben.
 * Sonst die Schlussmeldung des Jobs („Serie abgebrochen – 1.200 von 3.196 Bauteilen angelegt“) bzw. „Abgebrochen“.
 */
export function jobCancelText(job: Pick<Job, 'cancel_reason' | 'message'>, short = false): string {
  if (job.cancel_reason === JOB_CANCEL_LIBRARY_SWITCH) {
    return short
      ? tr("Abgebrochen – Bibliothek gewechselt")
      : tr("Die Bibliothek wurde gewechselt oder geschlossen – der Job wurde abgebrochen. In die andere Bibliothek wurde nichts geschrieben.")
  }
  const own = text(job.message)
  return own ? formatNumbersInText(localizeMessage(own)) : tr("Abgebrochen")
}

/**
 * Wie ein beendeter Job gemeldet wird (Ton, Titel, Beschreibung, Behebung) – berücksichtigt die Optionen aus
 * `trackJob`. `null`, solange der Job läuft. Für eigene Anzeigen (z. B. Inline-Status) wiederverwendbar: `description`
 * ist für Toasts gekürzt, `problem` der volle Text. Fehlertexte ohne Python-Klassenname, Zahlen deutsch gruppiert
 * („6.212 Bauteile“).
 */
export function jobOutcome<TResult>(job: Job<TResult>, opts?: TrackJobOptions<TResult>): JobOutcome | null {
  const outcome = rawJobOutcome(job, opts)
  if (!outcome) return null
  return {
    ...outcome,
    title: localizeMessage(outcome.title),
    description: outcome.description ? localizeMessage(outcome.description) : outcome.description,
    problem: outcome.problem ? localizeMessage(outcome.problem) : outcome.problem,
  }
}

function rawJobOutcome<TResult>(job: Job<TResult>, opts?: TrackJobOptions<TResult>): JobOutcome | null {
  if (!isJobFinished(job)) return null
  const o = (opts ?? feedback.get(job.id) ?? {}) as TrackJobOptions<TResult>
  if (job.status === 'failed') {
    const error = formatNumbersInText(cleanErrorText(text(job.error) ?? '') || tr("Fehlgeschlagen"))
    return { tone: 'error', title: job.title, description: clipText(error), problem: error, action: null }
  }
  if (job.status === 'cancelled') {
    return { tone: 'info', title: job.title, description: jobCancelText(job), problem: null, action: null }
  }
  const detect = o.warnWhen ?? jobResultProblem
  const found = safely(() => detect(job), o.warnWhen ? jobResultProblem(job) : null)
  if (found) {
    const problem = formatNumbersInText(cleanErrorText(found))
    const action = outcomeAction(job as Job)
    // ohne Writer: die kurze Schlussmeldung vorn, sofern sie den Writer nennt (die Behebung ist der Knopf); der volle
    // Grund steht in `problem` – sonst der gekürzte Grund (das Backend nennt die Behebung zuerst)
    const message = text(job.message)
    const lead = action === SETUP_WRITER_ACTION && jobLacksWriter(job) && message && NO_WRITER.test(message) ? message : null
    return { tone: 'warning', title: job.title, description: clipText(lead ? formatNumbersInText(lead) : problem), problem, action }
  }
  const done = typeof o.doneMessage === 'function' ? safely(() => (o.doneMessage as (j: Job<TResult>) => unknown)(job), null) : o.doneMessage
  const description = formatNumbersInText(text(done) ?? text(job.message) ?? tr("Erfolgreich abgeschlossen"))
  return { tone: 'success', title: job.title, description: clipText(description), problem: null, action: null }
}

// --------------------------------------------------------------------------- Daten nach einem Job neu laden

/**
 * Was ein beendeter Job geändert haben kann: die Module (erstes Element des Query-Keys), deren Abfragen danach neu
 * laden. `'all'` = alle modulbezogenen Abfragen (außer `system` und `meta: { static: true }`). Arten, die hier nicht
 * stehen, gelten als `'all'` – darunter alle, die Bauteile oder Bibliotheksdateien schreiben (`series`, `import`,
 * `libraries…`, `datasheet-commit`); ein Export oder eine Datenblattsuche lädt nichts neu. Die teure Bibliotheksprüfung
 * (`useHealthReport`) ist `meta.static` und lädt selbst nur nach schreibenden Jobs neu (`HEALTH_JOB_KINDS` in
 * `@/api/libraries`).
 */
const JOB_SCOPES: Readonly<Record<string, readonly string[]>> = {
  // lesen nur
  export: [],
  'datasheet-find': [],
  'altium.odbc_test': [],
  'altium.open': [],
  'library-import.scan': [],
  'housestyle.check': [],
  // Zustand in Altium (Installation, Aktualisierung, Prüfung in Altium)
  'altium.install_state': ['altium'],
  'altium.install': ['altium'],
  'altium.uninstall': ['altium'],
  'altium.refresh': ['altium'],
  'altium.verify': ['altium'],
  // Datenblatt laden bzw. analysieren: Datenblatt-Bestand und Kennzahlen, keine Bauteile
  datasheet: ['datasheets', 'stats'],
}

/** Module, die nach dem Job `kind` neu laden (`'all'` = alle) */
export function jobRefreshScopes(kind: string): readonly string[] | 'all' {
  return Object.hasOwn(JOB_SCOPES, kind) ? JOB_SCOPES[kind] : 'all'
}

const pendingScopes = new Set<string>()
let invalidateAll = false
let invalidateScheduled = false

/**
 * Nach einem Job die betroffenen Abfragen neu laden ({@link jobRefreshScopes}). Erfolgreiche Jobs immer; schreibende
 * Jobs auch nach Fehlschlag oder Abbruch (bis dahin Geschriebenes bleibt) – außer nach einem Bibliothekswechsel, der
 * ohnehin alles zurückgesetzt hat. Mehrere Abschlüsse im selben Takt laden einmal.
 */
function invalidateAfterJob(job: Job): void {
  const scopes = jobRefreshScopes(job.kind)
  // fehlgeschlagen/abgebrochen: nur Jobs, die schreiben (bzw. unbekannte) – und nicht nach einem Bibliothekswechsel
  if (job.status !== 'done' && (scopes !== 'all' || isLibrarySwitchCancel(job))) return
  if (scopes === 'all') invalidateAll = true
  else scopes.forEach((s) => pendingScopes.add(s))
  if (invalidateScheduled) return
  invalidateScheduled = true
  queueMicrotask(() => {
    invalidateScheduled = false
    const all = invalidateAll
    const only = new Set(pendingScopes)
    invalidateAll = false
    pendingScopes.clear()
    if (!all && !only.size) return
    void queryClient.invalidateQueries({
      predicate: (q) => {
        const scope = q.queryKey[0]
        if (scope === 'system' || q.meta?.static) return false
        return all || (typeof scope === 'string' && only.has(scope))
      },
    })
  })
}

function isQuietResult(result: unknown): boolean {
  return typeof result === 'object' && result !== null && (result as { quiet?: unknown }).quiet === true
}

function showOutcomeToast(job: Job): void {
  const outcome = jobOutcome(job)
  if (!outcome) return
  const id = `job:${job.id}`
  const details = { label: 'Details', onClick: () => useJobDock.getState().showLog(job.id) }
  const fix = outcome.action
  const remedy = fix ? { label: fix.label, onClick: () => appNavigate(fix.to, fix.state && { state: fix.state }) } : null
  if (outcome.tone === 'success') toast.success(outcome.title, { id, description: outcome.description })
  else if (outcome.tone === 'warning') {
    toast.warning(outcome.title, {
      id,
      description: outcome.description,
      duration: remedy ? 12_000 : 9000,
      action: remedy ?? details,
      cancel: remedy ? details : undefined,
    })
  } else if (outcome.tone === 'error') toast.error(outcome.title, { id, description: outcome.description, duration: 10_000, action: details })
  else if (isLibrarySwitchCancel(job)) {
    toast.info(outcome.title, { id, description: outcome.description, duration: 9000, action: details })
  } else toast.info(outcome.title, { id, description: outcome.description })
}

function announce(job: Job): void {
  const opts = feedback.get(job.id) ?? {}
  invalidateAfterJob(job)
  if (job.status === 'failed') noteAiJobFailure(job)
  const switched = isLibrarySwitchCancel(job)
  // Ein Bibliothekswechsel hat den Job abgebrochen: immer melden und zurück in die Pille (gelb) – die Seite, die ihn
  // inline zeigte, gehört zur alten Bibliothek und ist weg bzw. zeigt schon die neue
  if (switched) useJobDock.getState().setInline(job.id, false)
  if (opts.toast === false && !switched) return
  // Automatischer Lauf ohne Wirkung (`altium.refresh`, DbLib nicht installiert): das Backend markiert das Ergebnis mit
  // `quiet` – dafür keine Meldung (ARCHITEKTUR §8.2; Joblisten behalten das Feld auch in der Kurzfassung)
  if (job.status === 'done' && isQuietResult(job.result)) return
  // Texte brauchen das volle Ergebnis (erster nicht geschriebener Footprint, Seitentexte) – die Jobliste liefert bei
  // großen Ergebnissen nur eine Kurzfassung
  if (job.status === 'done' && isJobResultTruncated(job)) {
    fetchJob(job.id).then(showOutcomeToast, () => showOutcomeToast(job))
    return
  }
  showOutcomeToast(job)
}

/**
 * Jeden Job-Schnappschuss hier durchreichen (Jobliste, SSE, Polling): merkt laufende Jobs und meldet den Abschluss
 * genau einmal – auch, wenn ein mit `trackJob` gestarteter Job fertig war, bevor ihn die Jobliste je laufend sah.
 */
export function noteJobSnapshot(job: Job): void {
  if (isJobActive(job)) {
    seenActive.add(job.id)
    return
  }
  if (!isJobFinished(job) || announced.has(job.id)) return
  if (!seenActive.has(job.id) && !feedback.has(job.id)) return // war schon fertig, als wir ihn zum ersten Mal sahen
  announced.add(job.id)
  announce(job)
}

/**
 * Rückmeldung eines bekannten Jobs nachträglich ändern – z. B. Toast wieder einschalten, wenn der Inline-Status
 * verschwindet, oder mit `dock: true` zurück in die Pille des Job-Docks.
 */
export function setJobFeedback<TResult = unknown>(id: string, patch: Omit<TrackJobOptions<TResult>, 'openDock'>): void {
  feedback.set(id, { ...feedback.get(id), ...(patch as FeedbackOptions) })
  if (patch.dock !== undefined) useJobDock.getState().setInline(id, patch.dock === false)
}

/** Optionen eines Jobs (aus `trackJob`/`setJobFeedback`) – z. B. für die Anzeige im Job-Dock. */
export function getJobFeedback(id: string): TrackJobOptions | undefined {
  return feedback.get(id) as TrackJobOptions | undefined
}

/** Neuester bekannter Stand eines Jobs: voller Schnappschuss oder Eintrag einer Jobliste */
function latestKnown(id: string): Job | undefined {
  let best = queryClient.getQueryData<Job>(systemKeys.job(id))
  for (const [, list] of queryClient.getQueriesData<Job[]>({ queryKey: systemKeys.jobsAll })) {
    const hit = list?.find((j) => j.id === id)
    if (hit && (!best || hit.version > best.version)) best = hit
  }
  return best
}

/**
 * Die Seite zeigt diesen Job selbst (Fortschritt, Ergebnis): Solange die Komponente gemountet ist, zählt er nicht in
 * der Pille des Job-Docks und meldet keinen Abschluss-Toast (`toast: true` = trotzdem). Danach übernimmt das Dock:
 * Läuft der Job noch, erscheint er in der Pille und meldet sein Ende als Toast; ein schon beendeter bleibt still
 * (das Ergebnis stand auf der Seite) und steht nur im Panel – **außer** ein Bibliothekswechsel hat ihn abgebrochen:
 * der erscheint immer in der Pille und als Toast (auch wenn der Abbruch eintraf, solange die Seite ihn noch zeigte).
 *
 *   const { job } = useJob(jobId)
 *   useInlineJob(jobId)
 */
export function useInlineJob(id: string | null | undefined, opts: { toast?: boolean } = {}): void {
  const toastWhileInline = opts.toast ?? false
  useEffect(() => {
    if (!id) return
    setJobFeedback(id, { dock: false, toast: toastWhileInline })
    return () => {
      const latest = latestKnown(id)
      if (!latest || !isJobFinished(latest)) setJobFeedback(id, { dock: true, toast: true })
      else if (isLibrarySwitchCancel(latest)) {
        setJobFeedback(id, { dock: true, toast: true })
        if (!announced.has(id)) noteJobSnapshot(latest)
      }
    }
  }, [id, toastWhileInline])
}

/** Strukturierter Fortschritt eines Jobs (`job.detail`, Backend `ctx.detail(…)`) – typisiert, nie `undefined`. */
export function jobDetail<T extends Record<string, unknown> = Record<string, unknown>>(
  job: Pick<Job, 'detail'> | null | undefined,
): Partial<T> {
  return (job?.detail ?? {}) as Partial<T>
}

// --------------------------------------------------------------------------- Volle Schnappschüsse

/**
 * Vollständigen Job laden (Log und ganzes Ergebnis – auch wenn die Jobliste nur eine Kurzfassung hat) und im Cache
 * ablegen. Für Folgeaktionen außerhalb von Komponenten (`await fetchJob(id)`); in Komponenten `useJobResult`.
 */
export async function fetchJob<TResult = unknown>(id: string, signal?: AbortSignal): Promise<Job<TResult>> {
  const snap = await systemApi.getJob<TResult>(id, signal)
  storeSnapshot(queryClient, snap)
  return newer(snap, queryClient.getQueryData<Job<TResult>>(systemKeys.job(id)))
}

// --------------------------------------------------------------------------- geteilte Streams

export const MAX_STREAMS = 2

interface Stream {
  source: EventSource
  refs: number
  open: boolean
  listeners: Set<(state: 'open' | 'closed' | 'failed') => void>
}

const streams = new Map<string, Stream>()

/**
 * Stream für eine Job-ID abonnieren. Liefert `null`, wenn kein Stream möglich ist (kein EventSource
 * oder Limit erreicht) – dann pollt der Aufrufer.
 */
function subscribeStream(
  qc: QueryClient,
  id: string,
  onState: (state: 'open' | 'closed' | 'failed') => void,
): (() => void) | null {
  if (typeof EventSource === 'undefined') return null
  let stream = streams.get(id)
  if (!stream) {
    if (streams.size >= MAX_STREAMS) return null
    const source = new EventSource(apiUrl(`/api/jobs/${encodeURIComponent(id)}/events`))
    const created: Stream = { source, refs: 0, open: false, listeners: new Set() }
    const emit = (state: 'open' | 'closed' | 'failed') => created.listeners.forEach((l) => l(state))
    const close = (state: 'closed' | 'failed') => {
      source.close()
      created.open = false
      if (streams.get(id) === created) streams.delete(id)
      emit(state)
    }
    source.onopen = () => {
      created.open = true
      emit('open')
    }
    source.onmessage = (event) => {
      try {
        const job = JSON.parse(event.data as string) as Job
        storeSnapshot(qc, job)
        if (isJobFinished(job)) {
          close('closed')
          void qc.invalidateQueries({ queryKey: systemKeys.jobsAll })
        }
      } catch {
        // ungültiges Ereignis ignorieren
      }
    }
    source.onerror = () => close('failed')
    streams.set(id, created)
    stream = created
  }
  const s = stream
  s.refs += 1
  s.listeners.add(onState)
  if (s.open) onState('open')
  return () => {
    s.listeners.delete(onState)
    s.refs -= 1
    if (s.refs <= 0) {
      s.source.close()
      if (streams.get(id) === s) streams.delete(id)
    }
  }
}

// --------------------------------------------------------------------------- Hook

export function useJob<TResult = unknown>(
  id: string | null | undefined,
  options: UseJobOptions<TResult> = {},
): UseJobResult<TResult> {
  const qc = useQueryClient()
  const { pollInterval = 750 } = options
  // Für diese ID kein Stream (fehlgeschlagen, Limit, beendet) → Polling
  const [pollFor, setPollFor] = useState<string | null>(null)
  const [streamingFor, setStreamingFor] = useState<string | null>(null)
  const mode: 'sse' | 'poll' = id && pollFor !== id ? 'sse' : 'poll'

  // --- SSE-Stream (geteilt)
  useEffect(() => {
    if (!id || mode !== 'sse') return
    const cached = qc.getQueryData<Job>(systemKeys.job(id))
    if (cached && isJobFinished(cached)) return // nichts mehr zu erwarten
    const unsubscribe = subscribeStream(qc, id, (state) => {
      if (state === 'open') setStreamingFor(id)
      else {
        setStreamingFor(null)
        if (state === 'failed') {
          const latest = qc.getQueryData<Job>(systemKeys.job(id))
          if (!latest || !isJobFinished(latest)) setPollFor(id)
        }
      }
    })
    if (!unsubscribe) {
      // Limit erreicht oder kein EventSource: auf Polling ausweichen (nach dem Effekt, nicht synchron)
      const t = setTimeout(() => setPollFor(id), 0)
      return () => clearTimeout(t)
    }
    return () => {
      unsubscribe()
      setStreamingFor(null)
    }
  }, [id, mode, qc])

  // --- Schnappschuss (Initialzustand inkl. Log) + Polling-Fallback
  const query = useQuery({
    queryKey: systemKeys.job(id ?? '–'),
    queryFn: async ({ signal }) => {
      const snap = await systemApi.getJob<TResult>(id as string, signal)
      // Eine inzwischen per SSE eingetroffene neuere Fassung nicht überschreiben
      const latest = newer(snap, qc.getQueryData<Job<TResult>>(systemKeys.job(id as string)))
      upsertJobInLists(qc, latest as Job)
      noteJobSnapshot(latest as Job)
      return latest
    },
    enabled: Boolean(id),
    staleTime: mode === 'sse' ? Infinity : 0,
    refetchInterval: (q) => {
      if (mode !== 'poll' || q.state.status === 'error') return false // z. B. 404: Job existiert nicht
      const data = q.state.data
      return data && isJobFinished(data) ? false : pollInterval
    },
  })

  const job = id ? query.data : undefined

  // --- Callbacks genau einmal je Job-ID
  const callbacks = useRef(options)
  useEffect(() => {
    callbacks.current = options
  })
  const fired = useRef<string | null>(null)
  useEffect(() => {
    if (!job || !isJobFinished(job) || fired.current === job.id) return
    fired.current = job.id
    const cb = callbacks.current
    if (job.status === 'done') cb.onDone?.(job)
    else if (job.status === 'failed') cb.onFailed?.(job)
    else cb.onCancelled?.(job)
  }, [job])

  return {
    job,
    isActive: job ? isJobActive(job) : false,
    isFinished: job ? isJobFinished(job) : false,
    isStreaming: streamingFor === id && Boolean(id),
    error: query.error,
  }
}

/**
 * Volles Ergebnis eines Jobs – nie die Kurzfassung der Jobliste (`useJob` lädt `GET /api/jobs/{id}` bzw. hört per SSE).
 * `result` ist `null`, solange der Job läuft oder nicht erfolgreich endete.
 *
 *   const { result, job } = useJobResult<VerifyResult>(latestVerify?.id)
 */
export function useJobResult<TResult = unknown>(
  id: string | null | undefined,
  options: UseJobOptions<TResult> = {},
): UseJobResult<TResult> & { result: TResult | null } {
  const state = useJob<TResult>(id, options)
  const job = state.job
  const result = job && job.status === 'done' && !isJobResultTruncated(job) ? job.result : null
  return { ...state, result }
}

/**
 * Einen soeben gestarteten Job bekannt machen: Cache befüllen, Rückmeldung festlegen und im Job-Dock anzeigen (die
 * Pille erscheint mit dem neuen Job; das Panel öffnet sich **nicht** von selbst – es verdeckte sonst Inhalte und
 * Aktionsleisten der Seite).
 *
 *   const { job } = await api.post<{ job: Job }>('/api/series/generate', body)
 *   trackJob(job)                                                     // Pille, Toast bei Abschluss
 *   trackJob(job, { toast: false })                                   // Seite zeigt das Ergebnis selbst
 *   trackJob(job, { dock: false, toast: false })                      // … und den Fortschritt (Pille ignoriert ihn)
 *   trackJob(job, { doneMessage: (j) => `${j.result.created} Bauteile angelegt` })
 *   trackJob(job, { warnWhen: (j) => (j.result.conflicts ? `${j.result.conflicts} Konflikte` : null) })
 *
 * Erneuter Aufruf mit derselben Job-ID ergänzt die Optionen (`setJobFeedback` ebenso, ohne Hervorheben).
 */
export function trackJob<TResult = unknown>(job: Job<TResult>, opts: TrackJobOptions<TResult> = {}): void {
  const rest: TrackJobOptions<TResult> = { ...opts }
  delete rest.openDock // ohne Wirkung (siehe Option)
  feedback.set(job.id, { ...feedback.get(job.id), ...(rest as FeedbackOptions) })
  if (rest.dock !== undefined) useJobDock.getState().setInline(job.id, rest.dock === false)
  storeSnapshot(queryClient, job)
  void queryClient.invalidateQueries({ queryKey: systemKeys.jobsAll })
  useJobDock.getState().reveal(job.id, false)
}
