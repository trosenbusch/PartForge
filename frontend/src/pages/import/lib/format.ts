import { getLocale, t, tc } from '@/lib/i18n'
import type { CostEstimate, DatasheetStatus, IssueSeverity } from '@/api/datasheets'
import type { BadgeProps } from '@/components/ui'
import { formatNumber } from '@/lib/format'

/** Currency formatters are cached per locale and precision; tiny paid requests never round down to zero. */
const usdFormats = new Map<string, Intl.NumberFormat>()

export function formatUsd(value: number | null | undefined, opts: { precise?: boolean } = {}): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '–'
  const digits = value === 0 ? 2 : opts.precise ? 3 : 2
  const smallest = opts.precise ? 0.001 : 0.01
  const locale = getLocale()
  const key = `${locale}:${digits}`
  let formatter = usdFormats.get(key)
  if (!formatter) {
    formatter = new Intl.NumberFormat(locale, {
      style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol',
      minimumFractionDigits: digits, maximumFractionDigits: digits,
    })
    usdFormats.set(key, formatter)
  }
  return value > 0 && value < smallest ? `< ${formatter.format(smallest)}` : formatter.format(value)
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
  const typical = t("ca. {0}", { "0": String(formatUsd(Math.max(low, 0.01))) })
  const upTo = high > low * 1.2 + 0.005 ? t("höchstens {0}", { "0": String(formatUsd(high)) }) : null
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
  neu: { get label() { return t("Neu") }, variant: 'neutral' },
  gelesen: { get label() { return t("Nicht analysiert") }, variant: 'neutral' },
  analysiert: { get label() { return t("Analysiert") }, variant: 'spark' },
  übernommen: { get label() { return t("Übernommen") }, variant: 'success' },
}

/** Ist die letzte Analyse fehlgeschlagen (und es gibt noch kein verwertbares Ergebnis)? */
export function analysisFailed(d: { last_error?: string | null; status: DatasheetStatus }): boolean {
  return Boolean(d.last_error) && d.status !== 'analysiert' && d.status !== 'übernommen'
}

export const EFFORT_LABEL: Record<string, string> = {
  get low() { return t("niedrig") },
  get medium() { return t("mittel") },
  get high() { return t("hoch") },
  get xhigh() { return t("sehr hoch") },
  get max() { return t("maximal") },
}

export function effortLabel(effort: string | null | undefined): string {
  if (!effort) return t('Standard')
  return EFFORT_LABEL[effort] ?? effort
}

/**
 * Lauf-Bezeichnung des Backends („Claude Opus 5.5 · Aufwand niedrig“, `detail.model_label`) in den Worten der
 * Oberfläche („Claude Opus 5.5 · Gründlichkeit niedrig“ – wie in Einstellungen › KI).
 */
export function runLabel(label: string | null | undefined): string {
  return (label ?? '').replace(/(^|·\s*)(?:Aufwand|Gründlichkeit)\s+([^·]+)/g, (_, prefix: string, effort: string) => `${prefix}${t('Gründlichkeit')} ${t(effort.trim())}`).trim()
}

/** Woher der Claude-Schlüssel kommt (`/api/ai/status` → `key_source`) */
export const KEY_SOURCE_LABEL: Record<string, string> = {
  get stored() { return t("Verschlüsselt gespeichert") },
  get env() { return t("Umgebungsvariable") },
  get file() { return t("Schlüsseldatei") },
  get replay() { return t("Testmodus") },
}

export function keySourceLabel(source: string | null | undefined): string | null {
  if (!source) return null
  return KEY_SOURCE_LABEL[source] ?? source
}

export const SELECTION_LABEL: Record<string, string> = {
  get heuristic() { return t("automatisch gewählt") },
  get 'heuristic+triage'() { return t("mit Vorauswahl durch Claude") },
  get manual() { return t("manuell gewählt") },
  get all() { return t("alle Seiten") },
  get scan() { return t("als Bild gelesen") },
  get empty() { return t('keine') },
}

/** Schlagwörter der Textebene je Seite → kurze Beschreibung („Pinbelegung“, „Gehäuse“ …) */
export const PAGE_TOPIC: Record<string, string> = {
  get pins() { return t("Pinbelegung") },
  get ordering() { return t("Bestellangaben") },
  get orderable() { return t("Bestellbare Typen") },
  get package() { return t("Gehäuse") },
  get land_pattern() { return t("Lötflächen") },
  get drawing() { return t("Zeichnung") },
  get reel() { return t("Verpackung") },
  get toc() { return tc('pageRole', 'Inhalt') },
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
  error: { get one() { return t("Fehler") }, get many() { return t("Fehler") } },
  warning: { get one() { return t("Warnung") }, get many() { return t("Warnungen") } },
  info: { get one() { return t("Hinweis") }, get many() { return t("Hinweise") } },
}

export function severityCount(severity: IssueSeverity, n: number): string {
  const l = SEVERITY_LABEL[severity]
  return `${formatNumber(n)} ${n === 1 ? l.one : l.many}`
}

/** Lebenszyklus aus der Bestellübersicht (wie `proposal._LIFECYCLE`) → deutsches Etikett */
export function lifecycleLabel(status: string): string | null {
  const key = status.trim().toUpperCase().replace(/\s+/g, ' ')
  if (!key) return null
  if (['ACTIVE', 'PRODUCTION', 'IN PRODUCTION'].includes(key)) return t("Aktiv")
  if (['NRND', 'NOT RECOMMENDED FOR NEW DESIGNS'].includes(key)) return 'NRND'
  if (['LIFEBUY', 'LAST TIME BUY', 'EOL'].includes(key)) return t("Abgekündigt")
  if (['DISCONTINUED', 'OBSOLETE'].includes(key)) return t("Obsolet")
  if (key === 'PREVIEW') return t("Vorschau")
  return status.trim()
}
