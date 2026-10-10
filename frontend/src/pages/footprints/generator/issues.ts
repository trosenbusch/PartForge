import { localizeMessage } from '@/components/preview/i18n'
/** Prüfergebnisse des Generators: Meldungen sammeln (jede genau einmal), zählen und zur Prüfung springen. */
import type { FootprintCheckIssue, TimedPreview } from '@/api/footprints'
import type { CalcRecord } from '../lib/calc'

export const CHECKS_ID = 'fp-checks'

export type Severity = 'error' | 'warning' | 'info'

export interface IssueItem {
  severity: Severity
  message: string
  key: string
}

const normMsg = (m: string) => m.replace(/^Fehler:\s*/, '').replace(/\s+/g, ' ').trim().toLowerCase()

/** Prüfergebnisse, Warnungen und Begrenzungen der Lötflächen – jede Meldung genau einmal, Fehler zuerst */
export function collectIssues(data: TimedPreview | null, calc: CalcRecord | null): IssueItem[] {
  if (!data) return []
  const items: IssueItem[] = []
  const seen = new Set<string>()
  const add = (severity: Severity, message: string, key: string) => {
    const n = normMsg(message)
    if (!n || seen.has(n)) return
    seen.add(n)
    items.push({ severity, message: localizeMessage(message.replace(/^Fehler:\s*/, '')), key })
  }
  data.issues.forEach((i: FootprintCheckIssue, n) => add(i.severity, i.message, `i${n}`))
  data.warnings.forEach((w, n) => add('warning', w, `w${n}`))
  calc?.lands.forEach((l, n) => l.clamps.forEach((c, m) => add('warning', c, `c${n}-${m}`)))
  const order = (s: Severity) => (s === 'error' ? 0 : s === 'warning' ? 1 : 2)
  return items.sort((a, b) => order(a.severity) - order(b.severity))
}

export function issueCounts(items: readonly IssueItem[]): { errors: number; warnings: number } {
  return {
    errors: items.filter((i) => i.severity === 'error').length,
    warnings: items.filter((i) => i.severity === 'warning').length,
  }
}

/** Zur Prüfung springen (Karte rechts bzw. Reiter „Berechnung“) */
export function focusChecks(): void {
  const el = document.getElementById(CHECKS_ID)
  if (!el) return
  el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  el.focus({ preventScroll: true })
}
