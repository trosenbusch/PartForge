/** Texte und Formatierung des Datenblatt-Imports (deutsch). */
import type { CostEstimate, DatasheetStatus, IssueSeverity } from '@/api/datasheets'
import type { BadgeProps } from '@/components/ui'
import { formatNumber } from '@/lib/format'

/**
 * US-Dollar deutsch, **immer zwei Nachkommastellen** – nebeneinander stehende Beträge sehen gleich aus („0,09 $“ neben
 * „0,24 $“, nicht „0,090 $“): 0.229 → „0,23 $“, Beträge unter einem Cent als „< 0,01 $“ (nie „0,00 $“ für eine bezahlte
 * Anfrage), 0 → „0,00 $“. `precise`: drei Stellen für Aufstellungen einzelner Anfragen (dort durchgehend drei).
 */
export function formatUsd(value: number | null | undefined, opts: { precise?: boolean } = {}): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '–'
  const digits = opts.precise ? 3 : 2
  const smallest = opts.precise ? 0.001 : 0.01
  if (value > 0 && value < smallest) return `< ${formatNumber(smallest, digits)} $`
  // nichts bezahlt: „0,00 $“ – auch in der genauen Darstellung keine „0,000 $“
  // geschütztes Leerzeichen: Betrag und „$“ bleiben in einer Zeile
  return `${formatNumber(value, value === 0 ? 2 : digits)} $`
}

/** Erwartete Kosten einer Backend-Schätzung: typisch („low“) und höchstens („high“: lange Antworten, Kontrolle). */
export interface EstimateText {
  /** „ca. 0,23 $“ */
  typical: string
  /** „höchstens 0,72 $“ – `null`, wenn kaum über dem typischen Wert */
  upTo: string | null
  /** Für Screenreader und Tooltips: „ca. 0,23 $, höchstens 0,72 $“ */
  full: string
}

/** `extraUsd` kommt zum typischen Wert hinzu (z. B. die Kontrolle mit Seitenbildern bei „Immer“). */
export function estimateText(est: Pick<CostEstimate, 'est_cost_usd_low' | 'est_cost_usd_high'>, extraUsd = 0): EstimateText {
  const low = est.est_cost_usd_low + extraUsd
  const high = Math.max(low, est.est_cost_usd_high)
  const typical = `ca. ${formatUsd(Math.max(low, 0.01))}`
  const upTo = high > low * 1.2 + 0.005 ? `höchstens ${formatUsd(high)}` : null
  return { typical, upTo, full: upTo ? `${typical}, ${upTo}` : typical }
}

/** Host einer Adresse ohne „www.“ („ti.com“) – `null` bei ungültiger Adresse */
export function hostOf(url: string | null | undefined): string | null {
  if (!url) return null
  try {
    return new URL(url).host.replace(/^www\./, '')
  } catch {
    return null
  }
}

/** Seitenliste kompakt: [1, 2, 17, 18, 19, 20] → „1, 2, 17–20“ (Läufe ab drei Seiten). */
export function pagesText(pages: readonly number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b)
  const out: string[] = []
  let run: number[] = []
  const flush = () => {
    if (!run.length) return
    out.push(run.length > 2 ? `${run[0]}–${run[run.length - 1]}` : run.join(', '))
  }
  for (const p of sorted) {
    if (run.length && p === run[run.length - 1] + 1) {
      run.push(p)
      continue
    }
    flush()
    run = [p]
  }
  flush()
  return out.join(', ')
}

/** Seitenliste lesen: „1, 2, 17–24“ bzw. „1-3; 7“ → Zahlen (1-basiert, ≤ max). */
export function parsePages(text: string, max = Infinity): number[] {
  return parsePageInput(text, max).pages
}

export interface PageInput {
  /** gültige Seiten (sortiert, ohne Doppelte) */
  pages: number[]
  /** Seiten, die es im PDF nicht gibt (> max oder 0) */
  outOfRange: number[]
  /** unlesbare Teile der Eingabe („a“, „3-“) */
  invalid: string[]
}

/** Wie {@link parsePages}, nennt aber auch, was wegfällt – damit nichts stillschweigend verschwindet. */
export function parsePageInput(text: string, max = Infinity): PageInput {
  const pages = new Set<number>()
  const outOfRange = new Set<number>()
  const invalid: string[] = []
  // „17 – 24“ (Leerzeichen um den Strich) zusammenziehen, damit es als ein Bereich gelesen wird
  const normalized = text.replace(/\s*([-–…])\s*/g, '$1')
  for (const part of normalized.split(/[,;\s]+/)) {
    if (!part) continue
    const m = part.match(/^(\d+)(?:[-–…](\d+))?$/)
    if (!m) {
      invalid.push(part)
      continue
    }
    const a = Number(m[1])
    const b = m[2] ? Number(m[2]) : a
    for (let p = Math.min(a, b); p <= Math.max(a, b) && p - Math.min(a, b) < 5000; p++) {
      if (p >= 1 && p <= max) pages.add(p)
      else outOfRange.add(p)
    }
  }
  const sort = (s: Set<number>) => [...s].sort((x, y) => x - y)
  return { pages: sort(pages), outOfRange: sort(outOfRange), invalid }
}

export const STATUS_META: Record<DatasheetStatus, { label: string; variant: NonNullable<BadgeProps['variant']> }> = {
  neu: { label: 'Neu', variant: 'neutral' },
  gelesen: { label: 'Nicht analysiert', variant: 'neutral' },
  analysiert: { label: 'Analysiert', variant: 'spark' },
  übernommen: { label: 'Übernommen', variant: 'success' },
}

/** Ist die letzte Analyse fehlgeschlagen (und es gibt noch kein verwertbares Ergebnis)? */
export function analysisFailed(d: { last_error?: string | null; status: DatasheetStatus }): boolean {
  return Boolean(d.last_error) && d.status !== 'analysiert' && d.status !== 'übernommen'
}

export const EFFORT_LABEL: Record<string, string> = {
  low: 'niedrig',
  medium: 'mittel',
  high: 'hoch',
  xhigh: 'sehr hoch',
  max: 'maximal',
}

export function effortLabel(effort: string | null | undefined): string {
  if (!effort) return 'Standard'
  return EFFORT_LABEL[effort] ?? effort
}

/**
 * Lauf-Bezeichnung des Backends („Claude Opus 5.5 · Aufwand niedrig“, `detail.model_label`) in den Worten der
 * Oberfläche („Claude Opus 5.5 · Gründlichkeit niedrig“ – wie in Einstellungen › KI).
 */
export function runLabel(label: string | null | undefined): string {
  return (label ?? '').replace(/(^|·\s*)Aufwand(?=\s)/, '$1Gründlichkeit').trim()
}

/** Woher der Claude-Schlüssel kommt (`/api/ai/status` → `key_source`) */
export const KEY_SOURCE_LABEL: Record<string, string> = {
  stored: 'Verschlüsselt gespeichert',
  env: 'Umgebungsvariable',
  file: 'Schlüsseldatei',
  replay: 'Testmodus',
}

export function keySourceLabel(source: string | null | undefined): string | null {
  if (!source) return null
  return KEY_SOURCE_LABEL[source] ?? source
}

export const SELECTION_LABEL: Record<string, string> = {
  heuristic: 'automatisch gewählt',
  'heuristic+triage': 'mit Vorauswahl durch Claude',
  manual: 'manuell gewählt',
  all: 'alle Seiten',
  scan: 'als Bild gelesen',
  empty: 'keine',
}

/** Schlagwörter der Textebene je Seite → kurze Beschreibung („Pinbelegung“, „Gehäuse“ …) */
export const PAGE_TOPIC: Record<string, string> = {
  pins: 'Pinbelegung',
  ordering: 'Bestellangaben',
  orderable: 'Bestellbare Typen',
  package: 'Gehäuse',
  land_pattern: 'Lötflächen',
  drawing: 'Zeichnung',
  reel: 'Verpackung',
  toc: 'Inhalt',
}

export function pageTopics(categories: readonly string[]): string[] {
  const out: string[] = []
  for (const c of categories) {
    const label = PAGE_TOPIC[c]
    if (label && !out.includes(label)) out.push(label)
  }
  return out
}

export const SEVERITY_LABEL: Record<IssueSeverity, { one: string; many: string }> = {
  error: { one: 'Fehler', many: 'Fehler' },
  warning: { one: 'Warnung', many: 'Warnungen' },
  info: { one: 'Hinweis', many: 'Hinweise' },
}

export function severityCount(severity: IssueSeverity, n: number): string {
  const l = SEVERITY_LABEL[severity]
  return `${formatNumber(n)} ${n === 1 ? l.one : l.many}`
}

/** Lebenszyklus aus der Bestellübersicht (wie `proposal._LIFECYCLE`) → deutsches Etikett */
export function lifecycleLabel(status: string): string | null {
  const key = status.trim().toUpperCase().replace(/\s+/g, ' ')
  if (!key) return null
  if (['ACTIVE', 'PRODUCTION', 'IN PRODUCTION'].includes(key)) return 'Aktiv'
  if (['NRND', 'NOT RECOMMENDED FOR NEW DESIGNS'].includes(key)) return 'NRND'
  if (['LIFEBUY', 'LAST TIME BUY', 'EOL'].includes(key)) return 'Abgekündigt'
  if (['DISCONTINUED', 'OBSOLETE'].includes(key)) return 'Obsolet'
  if (key === 'PREVIEW') return 'Vorschau'
  return status.trim()
}
