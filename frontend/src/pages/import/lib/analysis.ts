import { t as translate } from '@/lib/i18n'
import type { DatasheetJobDetail, DatasheetStep } from '@/api/datasheets'
import { jobDetail } from '@/api/jobs'
import type { Job, JobLogEntry } from '@/api/system'
import { formatNumber, plural } from '@/lib/format'

export type StepKey = DatasheetStep
/** `cancelled` = hier abgebrochen (neutral, kein Fehler) */
export type StepState = 'pending' | 'active' | 'done' | 'warn' | 'error' | 'cancelled'

export interface StepInfo {
  key: StepKey
  label: string
  /** Kurzbeschreibung, solange der Schritt aussteht/läuft */
  hint: string
  state: StepState
  /** Ergebniszeile (z. B. „8 von 25 Seiten · automatisch gewählt“) bzw. live während des Schritts */
  detail?: string
  /** Weitere Ereignisse (Warnungen, Korrekturen) */
  notes: { level: JobLogEntry['level']; text: string }[]
}

/** Zähler wie `detail.counters` */
export interface AnalysisCounters {
  mpns?: number
  pins?: number
  parameters?: number
  packages?: number
  dimensions?: number
}

export interface AnalysisProgress {
  steps: StepInfo[]
  current: StepKey | null
  /** Datenblatt des Jobs (`detail.datasheet_id` – beim URL-Import, sobald das PDF gespeichert ist) */
  datasheetId: string | null
  fileName?: string
  pageCount?: number
  /** Seiten ohne Textebene (Claude liest sie als Bild) */
  imagePages: number[]
  selectedPages: number[]
  identityPages: number[]
  geometryPages: number[]
  visionPages: number[]
  /** Seiten, die Claude gerade liest */
  activePages: number[]
  /** Bereits gelesene Seiten (abgeschlossene Durchgänge) */
  donePages: number[]
  /** Fortschritt beim Lesen der Textebene („Seite 12 von 25“) */
  readUpTo?: number
  counters: AnalysisCounters
  manufacturer?: string
  devicesText?: string
  /** „Claude Opus 5.5 · Aufwand niedrig“ (Backend, `detail.model_label`) */
  modelLabel?: string
  /** Kosten bisher (laufend, `detail.cost_usd`) */
  costUsd: number
  /** Kostenlimit dieses Imports (`detail.budget_usd`) */
  budgetUsd: number | null
  /** Endgültige Kosten dieses Imports (nach dem Speichern bzw. beim Abbruch) */
  finalCostUsd: number | null
  /** Anzahl bezahlter Anfragen laut Abschlusszeile */
  requests?: number
  /** URL-Import, der nur geladen hat (die Analyse folgt als eigener Job) */
  loadOnly: boolean
  isUrlJob: boolean
  download?: { url?: string; name?: string; kb?: number }
  duplicate: boolean
  /** `job.detail` war vorhanden (sonst nur das Protokoll ausgewertet) */
  structured: boolean
}

/** Bezeichnungen wie `extract.STEP_LABELS` im Backend, dazu eine Kurzbeschreibung für ausstehende Schritte */
const STEP_DEFS: Record<StepKey, { label: string; hint: string }> = {
  download: { get label() { return translate("Datenblatt herunterladen") }, get hint() { return translate("PDF vom Hersteller laden") } },
  read: { get label() { return translate("Datenblatt lesen") }, get hint() { return translate("Textebene und Seitenbilder prüfen") } },
  select_pages: { get label() { return translate("Seiten auswählen") }, get hint() { return translate("Pinbelegung, Bestellangaben und Zeichnungen finden") } },
  identity: { get label() { return translate("Bauteile und Pins") }, get hint() { return translate("Hersteller, Bestellnummern, Parameter, Pintabellen") } },
  geometry: { get label() { return translate("Gehäusemaße") }, get hint() { return translate("Maßzeichnungen und empfohlene Lötflächen") } },
  check: { get label() { return translate("Prüfung") }, get hint() { return translate("Plausibilität, bei Bedarf Kontrolle mit Seitenbildern") } },
  save: { get label() { return translate("Ergebnis speichern") }, get hint() { return translate("Vorschlag für Symbol, Footprint und Bauteile") } },
}

const ORDER: StepKey[] = ['download', 'read', 'select_pages', 'identity', 'geometry', 'check', 'save']
const EXTRACTION: StepKey[] = ['read', 'select_pages', 'identity', 'geometry', 'check', 'save']

const isStep = (key: unknown): key is StepKey => typeof key === 'string' && key in STEP_DEFS

export function stepLabel(key: StepKey): string {
  return STEP_DEFS[key].label
}

/** „1, 2, 17, 18, 21–24“ → Seitenzahlen */
export function parsePageList(text: string): number[] {
  const out: number[] = []
  for (const part of text.split(',')) {
    const m = part.trim().match(/^(\d+)(?:\s*[–-]\s*(\d+))?$/)
    if (!m) continue
    const a = Number(m[1])
    const b = m[2] ? Number(m[2]) : a
    for (let p = a; p <= b && p - a < 2000; p++) out.push(p)
  }
  return out
}

/** Zähler aus „1 Bauteil, 14 Bestellnummern, 13 Pins, 2 Gehäuse mit 20 Maßen“ (Rückfall ohne `detail.counters`) */
export function parseCounters(text: string): AnalysisCounters {
  const num = (re: RegExp) => {
    const m = text.match(re)
    return m ? Number(m[1]) : undefined
  }
  const out: AnalysisCounters = {}
  const mpns = num(/(\d+) Bestellnummern/)
  const pins = num(/(\d+) Pins/)
  const packages = num(/(\d+) Gehäuse\b/)
  const dims = num(/(\d+) Maße/)
  if (mpns !== undefined) out.mpns = mpns
  if (pins !== undefined) out.pins = pins
  if (packages !== undefined) out.packages = packages
  if (dims !== undefined) out.dimensions = dims
  return out
}

function stepFromMessage(message: string): StepKey | null {
  const m = message.trim()
  if (!m) return null
  if (/heruntergeladen/.test(m)) return 'download'
  if (/^Textebene wird gelesen|^Datenblatt wird gelesen|^Seite \d+ von \d+ wird gelesen/.test(m)) return 'read'
  if (/^Seiten werden ausgewählt/.test(m)) return 'select_pages'
  if (/liest Bauteile und Pins/.test(m)) return 'identity'
  if (/liest die Gehäusemaße/.test(m)) return 'geometry'
  if (/^Kontrolle mit Seitenbildern|prüft die Seitenbilder|^Ergebnis wird geprüft/.test(m)) return 'check'
  if (/^Ergebnis wird gespeichert/.test(m)) return 'save'
  return null
}

const SELECTION_SHORT: Record<string, string> = {
  get heuristic() { return translate("automatisch") },
  get 'heuristic+triage'() { return translate("Vorauswahl durch Claude") },
  get manual() { return translate("manuell") },
  get all() { return translate("alle Seiten") },
  get scan() { return translate("Bildseiten") },
}

// --------------------------------------------------------------------------- Protokoll (Ergänzung und Rückfall)

interface LogInfo {
  isUrlJob: boolean
  download?: { url?: string; name?: string; kb?: number }
  duplicate: boolean
  fileName?: string
  pageCount?: number
  imagePages: number[]
  selectedPages: number[]
  identityPages: number[]
  geometryPages: number[]
  visionPages: number[]
  /** Seiten der laufenden Kontrolle mit Seitenbildern */
  visionActive: boolean
  visionDone: boolean
  selectionMethod?: string
  modelLabel?: string
  manufacturer?: string
  devicesText?: string
  identityDuration?: number
  counters: AnalysisCounters
  checkResult?: { errors: number; warnings: number; infos: number; afterVision: boolean }
  passCost: number
  finalCostUsd: number | null
  requests?: number
  /** letzter erreichter Schritt laut Protokoll */
  reached: StepKey
  notes: Map<StepKey, StepInfo['notes']>
}

function parseLog(log: readonly JobLogEntry[]): LogInfo {
  const out: LogInfo = {
    isUrlJob: false,
    duplicate: false,
    imagePages: [],
    selectedPages: [],
    identityPages: [],
    geometryPages: [],
    visionPages: [],
    visionActive: false,
    visionDone: false,
    counters: {},
    passCost: 0,
    finalCostUsd: null,
    reached: 'read',
    notes: new Map(),
  }
  const note = (key: StepKey, level: JobLogEntry['level'], text: string) => {
    const list = out.notes.get(key) ?? []
    list.push({ level, text })
    out.notes.set(key, list)
  }

  for (const entry of log) {
    const t = entry.text.trim()
    let m: RegExpMatchArray | null
    if ((m = t.match(/^Download: (.+)$/))) {
      out.isUrlJob = true
      out.download = { ...out.download, url: m[1] }
      out.reached = 'download'
    } else if ((m = t.match(/^(\d+) kB heruntergeladen \((.+)\)$/))) {
      out.isUrlJob = true
      out.download = { ...out.download, kb: Number(m[1]), name: m[2] }
      out.fileName = out.fileName ?? m[2]
      out.reached = 'read'
    } else if (/bereits in der Bibliothek/.test(t)) {
      out.duplicate = true
      note('download', entry.level, t)
    } else if ((m = t.match(/^(\d+) Seiten gelesen(?:, davon ohne Textebene: (\d+))?/))) {
      out.pageCount = Number(m[1])
      out.reached = 'select_pages'
    } else if ((m = t.match(/^Datenblatt „(.+)“: (\d+) Seiten(?:, ohne lesbare Textebene: ([\d,\s–-]+))?/))) {
      out.fileName = m[1]
      out.pageCount = Number(m[2])
      out.imagePages = m[3] ? parsePageList(m[3]) : []
      out.reached = 'select_pages'
    } else if (/^Seiten-Vorauswahl mit/.test(t)) {
      note('select_pages', 'info', translate("Vorauswahl mit dem schnellen Modell"))
      out.reached = 'select_pages'
    } else if (/^Seiten-Vorauswahl übersprungen/.test(t)) {
      note('select_pages', entry.level, t)
    } else if ((m = t.match(/^Seitenauswahl: (.+?) \((\d+) von (\d+) Seiten, ([^)]+)\); Bauteile\/Pins: (.+?), Gehäuse: (.+)$/))) {
      out.selectedPages = parsePageList(m[1])
      out.identityPages = parsePageList(m[5])
      out.geometryPages = parsePageList(m[6])
      out.pageCount = out.pageCount ?? Number(m[3])
      out.selectionMethod = m[4]
      out.reached = 'identity'
    } else if (/^Seiten .+ nicht übernommen/.test(t) || /keine Textebene/.test(t)) {
      note('select_pages', entry.level, t)
    } else if ((m = t.match(/^(.+?) liest Bauteile und Pins/))) {
      // „Claude Opus 5.5 · Gründlichkeit niedrig liest …“ (älter: „· Aufwand niedrig“ bzw. „Claude (claude-opus-5-5, Aufwand low) liest …“)
      if (!/^Claude \(/.test(m[1])) out.modelLabel = m[1]
      out.reached = 'identity'
    } else if ((m = t.match(/^Hersteller erkannt: (.+)$/))) {
      out.manufacturer = m[1]
    } else if ((m = t.match(/^Bauteile: (.*?); Gehäuse: (.*) \((\d+) s, (\d+(?:\.\d+)?) USD\)$/))) {
      out.devicesText = m[1] && m[1] !== 'keine' ? m[1] : undefined
      out.identityDuration = Number(m[3])
      out.passCost += Number(m[4])
      out.reached = 'geometry'
    } else if (/liest die Gehäusemaße/.test(t)) {
      out.reached = 'geometry'
    } else if ((m = t.match(/^Antwort vollständig: (.+)$/))) {
      out.counters = { ...out.counters, ...parseCounters(m[1]) }
      if (!out.manufacturer) {
        const maker = m[1].split(',')[0]
        if (maker && maker !== 'Hersteller unbekannt') out.manufacturer = maker
      }
      out.reached = 'check'
    } else if ((m = t.match(/^Prüfung: (\d+) Fehler, (\d+) Warnungen, (\d+) Hinweise/))) {
      out.checkResult = { errors: Number(m[1]), warnings: Number(m[2]), infos: Number(m[3]), afterVision: false }
      out.reached = 'check'
    } else if ((m = t.match(/^Kontrolle der (.+?) mit hochaufgelösten Seitenbildern \(Seiten ([^)]+)\)/))) {
      out.visionPages = parsePageList(m[2])
      out.visionActive = true
      note('check', 'info', translate("Kontrolle der {0} mit Seitenbildern", { "0": String(m[1]) }))
      out.reached = 'check'
    } else if ((m = t.match(/^Nach der Kontrolle: .*; (\d+) Fehler, (\d+) Warnungen/))) {
      out.visionActive = false
      out.visionDone = true
      out.counters = { ...out.counters, ...parseCounters(t) }
      out.checkResult = { errors: Number(m[1]), warnings: Number(m[2]), infos: 0, afterVision: true }
    } else if (/^Kontrolle .*(nicht möglich|nicht verwertbar)|^Die Kontrolle brachte keine Verbesserung/.test(t)) {
      out.visionActive = false
      note('check', entry.level, t)
    } else if ((m = t.match(/^Ergebnis gespeichert\. Kosten dieses Imports: (\d+(?:\.\d+)?) USD \((\d+) Anfragen?/))) {
      out.finalCostUsd = Number(m[1])
      out.requests = Number(m[2])
      out.reached = 'save'
    } else if ((m = t.match(/^Bisherige Kosten dieses Imports gespeichert: (\d+(?:\.\d+)?) USD \((\d+)/))) {
      out.finalCostUsd = Number(m[1])
      out.requests = Number(m[2])
    } else if (t.startsWith('Traceback')) {
      // Entwicklerdetails bleiben im Protokoll
    } else if (/Modell gewechselt|Antwort zu lang|kennt keine Aufwandsstufe|lässt keine Gründlichkeit wählen/.test(t)) {
      // ältere Backends: „kennt keine Aufwandsstufe“ – in den Worten der Oberfläche (Einstellungen › KI: „Gründlichkeit“)
      note(
        out.reached,
        entry.level,
        t.replace(/kennt keine Aufwandsstufe – Anfrage ohne Aufwandsstufe/, 'lässt keine Gründlichkeit wählen – Anfrage mit der Standardeinstellung des Modells'),
      )
    } else if (entry.level === 'warn' || entry.level === 'error') {
      note(out.reached, entry.level, cleanJobError(t))
    } else if (out.reached === 'check' && t && !/^Ergebnis/.test(t)) {
      note('check', entry.level, t) // z. B. „Gehäuse DB: Maße nach der Kontrolle korrigiert.“
    }
  }
  return out
}

function countersFromDetail(detail: Partial<DatasheetJobDetail>): AnalysisCounters | null {
  const c = detail.counters
  if (!c || typeof c !== 'object') return null
  const out: AnalysisCounters = {}
  for (const key of ['mpns', 'pins', 'parameters', 'packages', 'dimensions'] as const) {
    const v = c[key]
    if (typeof v === 'number' && Number.isFinite(v)) out[key] = v
  }
  return out
}

const numberList = (v: unknown): number[] | null =>
  Array.isArray(v) ? v.filter((p): p is number => typeof p === 'number' && Number.isFinite(p)) : null

/** Ergebniszeile bzw. Live-Text eines Schritts */
function stepDetail(key: StepKey, ctx: {
  info: LogInfo
  counters: AnalysisCounters
  pageCount?: number
  selected: number[]
  costUsd: number
  readUpTo?: number
}): string | undefined {
  const { info, counters: c } = ctx
  switch (key) {
    case 'download':
      return info.download?.kb !== undefined ? `${formatNumber(info.download.kb)} kB · ${info.download.name ?? ''}`.trim() : undefined
    case 'read': {
      if (!ctx.pageCount) return ctx.readUpTo ? translate("Seite {0} …", { "0": String(ctx.readUpTo) }) : undefined
      const images = info.imagePages.length
      return images
        ? translate("{0} · {1} ohne Textebene (als Bild gelesen)", { "0": String(plural(ctx.pageCount, translate("Seite"), translate("Seiten"))), "1": String(formatNumber(images)) })
        : translate("{0} mit Textebene", { "0": String(plural(ctx.pageCount, translate("Seite"), translate("Seiten"))) })
    }
    case 'select_pages': {
      if (!ctx.selected.length) return undefined
      const how = info.selectionMethod ? (SELECTION_SHORT[info.selectionMethod] ?? info.selectionMethod) : null
      return translate("{0}{1} Seiten{2}", { "0": String(formatNumber(ctx.selected.length)), "1": String(ctx.pageCount ? translate(" von {0}", { "0": String(formatNumber(ctx.pageCount)) }) : ''), "2": String(how ? ` · ${how}` : '') })
    }
    case 'identity': {
      const parts: string[] = []
      if (c.mpns !== undefined) parts.push(plural(c.mpns, translate("Bestellnummer"), translate("Bestellnummern")))
      if (c.pins !== undefined) parts.push(plural(c.pins, 'Pin', 'Pins'))
      if (!parts.length) return info.devicesText
      return info.devicesText ? `${info.devicesText} · ${parts.join(', ')}` : parts.join(', ')
    }
    case 'geometry': {
      if (c.packages === undefined && c.dimensions === undefined) return undefined
      return [
        c.packages !== undefined ? plural(c.packages, translate("Gehäuse"), translate("Gehäuse")) : null,
        c.dimensions !== undefined ? plural(c.dimensions, translate("Maß"), translate("Maße")) : null,
      ]
        .filter(Boolean)
        .join(' · ')
    }
    case 'check': {
      const r = info.checkResult
      if (!r) return undefined
      if (r.afterVision) return r.errors || r.warnings ? translate("Nach der Kontrolle: {0} Fehler, {1} Warnungen", { "0": String(r.errors), "1": String(r.warnings) }) : translate("Kontrolle bestanden")
      const parts = [
        r.errors ? translate("{0} Fehler", { "0": String(r.errors) }) : '',
        r.warnings ? `${r.warnings} ${r.warnings === 1 ? translate("Warnung") : translate("Warnungen")}` : '',
        r.infos ? `${r.infos} ${r.infos === 1 ? translate("Hinweis") : translate("Hinweise")}` : '',
      ].filter(Boolean)
      return parts.length ? parts.join(' · ') : translate("Keine Auffälligkeiten")
    }
    case 'save':
      return info.requests !== undefined ? translate("{0} an Claude", { "0": String(plural(info.requests, translate("Anfrage"), translate("Anfragen"))) }) : undefined
  }
}

/**
 * Analyse-Fortschritt aus einem Job-Schnappschuss (laufend oder beendet). `urlJob` hilft, solange der Job noch wartet
 * (dann gibt es weder `detail` noch Protokoll).
 */
export function analyzeJob(
  job: Pick<Job, 'status' | 'message' | 'log' | 'progress' | 'detail' | 'title'> | undefined,
  opts: { urlJob?: boolean } = {},
): AnalysisProgress {
  const detail = jobDetail<DatasheetJobDetail>(job)
  const info = parseLog(job?.log ?? [])
  const structured = Array.isArray(detail.steps) && detail.steps.length > 0
  const urlJob = Boolean(opts.urlJob || info.isUrlJob || /^Datenblatt laden:/.test(job?.title ?? ''))

  // Schritte dieses Jobs: laut Backend, sonst wie bisher (URL-Import mit Download)
  let keys = structured ? (detail.steps as unknown[]).filter(isStep) : []
  if (!keys.length) keys = urlJob ? ['download', ...EXTRACTION] : EXTRACTION
  keys = ORDER.filter((k) => keys.includes(k))
  const isUrlJob = keys.includes('download') || urlJob
  // URL-Import ohne Analyse: nur Laden und Lesen (die Analyse startet danach als eigener Job)
  const loadOnly = isUrlJob && structured && !keys.includes('identity')

  const status = job?.status
  const running = status === 'running' || status === 'queued'
  const message = job?.message ?? ''
  const readMatch = message.match(/^Seite (\d+) von (\d+) wird gelesen/)
  const readUpTo = readMatch && running ? Number(readMatch[1]) : undefined

  // aktueller Schritt (laufend) bzw. der Schritt, an dem der Job endete (fehlgeschlagen/abgebrochen)
  let current: StepKey | null = null
  if (job) {
    if (status === 'queued') current = keys[0]
    else if (isStep(detail.step) && keys.includes(detail.step)) current = detail.step
    else current = (running ? stepFromMessage(message) : null) ?? (keys.includes(info.reached) ? info.reached : keys[0])
    if (running && info.visionActive && keys.includes('check')) current = 'check'
    if (status === 'done') current = null
  }
  const ci = current ? keys.indexOf(current) : -1

  const counters = { ...info.counters, ...(running && !structured ? parseCounters(message) : {}), ...(countersFromDetail(detail) ?? {}) }
  const pageCount = (typeof detail.pages_total === 'number' && detail.pages_total > 0 ? detail.pages_total : undefined) ??
    info.pageCount ?? (readMatch ? Number(readMatch[2]) : undefined)
  const selected = numberList(detail.pages_selected) ?? info.selectedPages
  const costUsd = typeof detail.cost_usd === 'number' ? detail.cost_usd : Math.max(info.passCost, info.finalCostUsd ?? 0)
  const finished = status === 'done' || status === 'failed' || status === 'cancelled'
  const finalCostUsd = finished ? (typeof detail.cost_usd === 'number' ? detail.cost_usd : info.finalCostUsd) : info.finalCostUsd

  const steps: StepInfo[] = keys.map((key, i) => {
    const def = STEP_DEFS[key]
    let state: StepState = 'pending'
    if (status === 'done') state = 'done'
    else if (running) state = i < ci ? 'done' : i === ci ? 'active' : 'pending'
    else if (job) state = i < ci ? 'done' : i === ci ? (status === 'cancelled' ? 'cancelled' : 'error') : 'pending'
    if (state === 'done' && key === 'check' && info.checkResult?.errors) state = 'warn'
    const label = i === ci && running && typeof detail.step_label === 'string' && detail.step_label ? translate(detail.step_label) : def.label
    return {
      key,
      label,
      hint: def.hint,
      state,
      detail: state === 'pending' ? undefined : stepDetail(key, { info, counters, pageCount, selected, costUsd, readUpTo }),
      notes: info.notes.get(key) ?? [],
    }
  })

  const stateOf = (key: StepKey) => steps.find((s) => s.key === key)?.state
  const passed = (key: StepKey) => {
    const s = stateOf(key)
    return s === 'done' || s === 'warn'
  }
  const activeFromDetail = numberList(detail.pages_active)
  const activePages = !running
    ? []
    : activeFromDetail && structured
      ? activeFromDetail
      : current === 'identity'
        ? info.identityPages
        : current === 'geometry'
          ? info.geometryPages
          : current === 'check' && info.visionActive
            ? info.visionPages
            : []
  const donePages = [
    ...(passed('identity') ? info.identityPages : []),
    ...(passed('geometry') ? info.geometryPages : []),
    ...(info.visionDone ? info.visionPages : []),
  ]

  return {
    steps,
    current,
    datasheetId: typeof detail.datasheet_id === 'string' && detail.datasheet_id ? detail.datasheet_id : null,
    fileName: info.fileName,
    pageCount,
    imagePages: info.imagePages,
    selectedPages: selected,
    identityPages: info.identityPages,
    geometryPages: info.geometryPages,
    visionPages: info.visionPages,
    activePages,
    donePages: [...new Set(donePages)],
    readUpTo,
    counters,
    manufacturer: info.manufacturer,
    devicesText: info.devicesText,
    modelLabel: (typeof detail.model_label === 'string' && detail.model_label) || info.modelLabel,
    costUsd,
    budgetUsd: typeof detail.budget_usd === 'number' && detail.budget_usd > 0 ? detail.budget_usd : null,
    finalCostUsd,
    requests: info.requests,
    loadOnly,
    isUrlJob,
    download: info.download,
    duplicate: info.duplicate,
    structured,
  }
}

/** Fehlertext eines Jobs ohne Python-Klassennamen („ExtractionFailed: …“ → „…“). */
export function cleanJobError(text: string | null | undefined): string {
  if (!text) return ''
  return text.replace(/^[A-Z][A-Za-z]*(?:Error|Failed|Unavailable|Exceeded|NotFound|Exception|Changed|Busy|Refused): /, '')
}

/** Dauer seit dem Start in Sekunden (laufend: bis jetzt) */
export function jobElapsed(job: Pick<Job, 'started' | 'finished' | 'created'> | undefined, now = Date.now()): number {
  if (!job) return 0
  const start = job.started ?? job.created
  const end = job.finished ?? now / 1000
  return Math.max(0, end - start)
}
