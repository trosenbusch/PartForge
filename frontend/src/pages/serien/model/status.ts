import { getLocale, t as tr } from '@/lib/i18n'
/** Status der Vorschauzeilen (series.py `RowStatus`) – Beschriftung, Ton und Erklärung. */
import type { RowStatus } from '@/api/series'

export type StatusTone = 'success' | 'neutral' | 'danger' | 'warning'

export interface StatusMeta {
  label: string
  /** Mehrzahl für Zähler („2 Konflikte“) */
  plural: string
  tone: StatusTone
  description: string
}

export const ROW_STATUS: Record<RowStatus, StatusMeta> = {
  new: { label: 'Neu', plural: 'Neu', tone: 'success', description: 'Wird angelegt – die Teilenummer ist frei.' },
  exists: {
    label: 'Vorhanden',
    plural: 'Vorhanden',
    tone: 'neutral',
    description: 'Gibt es schon in dieser Kategorie – wird übersprungen oder aktualisiert.',
  },
  conflict: {
    label: 'Konflikt',
    plural: 'Konflikte',
    tone: 'danger',
    description: 'Teilenummer oder Hersteller-Teilenummer gehört schon einem anderen Bauteil.',
  },
  invalid: {
    label: 'Ungültig',
    plural: 'Ungültig',
    tone: 'warning',
    description: 'Laut Vorlage nicht lieferbar oder nicht speicherbar – wird nicht angelegt.',
  },
}

export const STATUS_ORDER: RowStatus[] = ['new', 'exists', 'conflict', 'invalid']

/** Punktfarbe je Ton */
export const TONE_DOT: Record<StatusTone, string> = {
  success: 'bg-success',
  neutral: 'bg-fg-subtle',
  danger: 'bg-danger',
  warning: 'bg-warning',
}

/** Textfarbe je Ton (AA auf getönten Flächen) */
export const TONE_TEXT: Record<StatusTone, string> = {
  success: 'text-success-text',
  neutral: 'text-fg-muted',
  danger: 'text-danger-text',
  warning: 'text-warning-text',
}

/** Hinweise, die das Backend an jede Zeile einer ungeprüften Vorlage hängt – sie sind kein Grund für „ungültig“ */
const GENERIC_NOTES = [/^Lieferbarkeit nicht geprüft/i, /^Vorlage nicht gegen das Datenblatt geprüft/i]

export const isGenericNote = (message: string): boolean => GENERIC_NOTES.some((re) => re.test(message))

/** Grund einer ungültigen bzw. Konflikt-Zeile (erster Hinweis, der kein allgemeiner Vermerk ist) */
export function rowReason(row: { messages: string[] }): string | null {
  return row.messages.find((m) => !isGenericNote(m)) ?? row.messages[0] ?? null
}

/** Hinweise einer Zeile ohne die allgemeinen (`hidden`); der Grund für „ungültig“/„Konflikt“ zuerst */
export function rowMessages(row: { status: RowStatus; messages: string[] }, hidden: ReadonlySet<string>): string[] {
  const own = row.messages.filter((m) => !hidden.has(m))
  const reason = row.status === 'invalid' || row.status === 'conflict' ? rowReason(row) : null
  return reason && own.includes(reason) ? [reason, ...own.filter((m) => m !== reason)] : own
}

const LEADING_VALUE = /^[+-]?\d+(?:[.,]\d+)?(?:e[+-]?\d+)?\s?[pnuµμmkKMG]?(?:Ω|F|H)\s+(?:(?:liegt|ist)\s+)?/i

/**
 * Grund ohne den führenden Wert, damit gleiche Gründe zusammen gezählt werden:
 * „33MΩ liegt außerhalb des lieferbaren Bereichs (…)“ → „Außerhalb des lieferbaren Bereichs (…)“,
 * „1.02Ω ist kein Wert der Reihe E24.“ → „Kein Wert der Reihe E24.“
 */
export function reasonKey(message: string): string {
  const rest = message.replace(LEADING_VALUE, '')
  return rest === message || !rest ? message : rest.charAt(0).toLocaleUpperCase(getLocale()) + rest.slice(1)
}

/**
 * Warnung des Backends zu ausgelassenen Werten („128 Werte ausgelassen (0402: 96, …) – …“): die Seite zeigt
 * `skipped_by_size`/`skipped_total`/`skipped_reason` selbst – die Warnung nicht noch einmal
 */
export const isSkippedWarning = (warning: string): boolean => /^\d[\d.]*\s+Werte?\s+ausgelassen\b/.test(warning)

/** Ausgelassene Werte je Baugröße in der Reihenfolge der Auswahl (`order`), übrige dahinter */
export function skippedSizes(bySize: Record<string, number>, order: readonly string[] = []): [string, number][] {
  const entries = Object.entries(bySize).filter(([, n]) => n > 0)
  const rank = (size: string) => (order.includes(size) ? order.indexOf(size) : order.length)
  return entries.sort((a, b) => rank(a[0]) - rank(b[0]))
}

/** Grund des Backends mitten im Satz: „Laut Datenblatt …“ → „laut Datenblatt …“ */
export const midSentence = (text: string): string => (/^Laut\s/.test(text) ? `l${text.slice(1)}` : text)

/** Bauteile laut Prüfung: neu + vorhanden (Konflikte und ungültige Zeilen entstehen nicht) */
export function serverParts(counts: Partial<Record<string, number>>): number {
  return (counts.new ?? 0) + (counts.exists ?? 0)
}

/** Zählerbeschriftung im Satz: „3 neu“, „1 Konflikt“, „2 Konflikte“, „4 ungültig“ */
export function countLabel(status: RowStatus, n: number): string {
  if (status === 'new') return tr("neu")
  if (status === 'exists') return tr("vorhanden")
  if (status === 'conflict') return n === 1 ? tr("Konflikt") : tr("Konflikte")
  return tr("ungültig")
}
