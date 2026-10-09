/**
 * „Rückgängig“ für Massenänderungen und „Texte neu erzeugen“: Die Antwort nennt die Einträge der Änderungshistorie
 * (`audit_ids`), `POST /api/parts/{table}/restore-updates` setzt damit die alten Werte zurück – je Bauteil ganz oder gar
 * nicht; Bauteile, die seither erneut geändert oder gelöscht wurden, bleiben unverändert (`conflicts`).
 *
 *   showChangeToast(qc, table, res, '12 Bauteile geändert')   // Erfolgsmeldung mit „Rückgängig“
 */
import type { QueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { invalidateParts, partsApi, type RestoreUpdatesResult } from '@/api/parts'
import { formatNumber, plural } from '@/lib/format'

/** So lange bleibt „Rückgängig“ erreichbar (wie beim Löschen; der Zeitgeber pausiert beim Überfahren) */
export const UNDO_TOAST_MS = 30_000
/** So viele übersprungene Bauteile nennt die Rückmeldung mit Grund */
const NAMED_CONFLICTS = 2

/** Zähler für die Toast-IDs (je Änderung ein eigenes „Rückgängig“) */
let changeToastCounter = 0

/** Antwort einer Massenänderung bzw. von „Texte neu erzeugen“ (der Teil, den die Meldung braucht) */
export interface ChangeResult {
  updated: number
  /** automatische Sicherung vorher (mehr als 20 Bauteile) */
  backup?: string | null
  audit_ids?: number[]
}

export interface UndoOutcome {
  tone: 'success' | 'warning' | 'info'
  title: string
  description?: string
}

/** „Seit der Änderung erneut geändert (Toleranz) – nicht zurückgesetzt.“ → „Seit der Änderung erneut geändert (Toleranz)“ */
function conflictReason(text: string): string {
  return text.replace(/\s*–\s*nicht zurückgesetzt\.?\s*$/, '').trim()
}

/**
 * Rückmeldung nach „Rückgängig“: zurückgesetzte Bauteile, übersprungene (Konflikte, mit Teilenummer und Grund) und
 * Einträge, die die Änderungshistorie nicht mehr kennt. `total` = Bauteile der zurückgenommenen Änderung.
 */
export function restoreUpdatesOutcome(
  res: Pick<RestoreUpdatesResult, 'restored' | 'conflicts' | 'unchanged' | 'not_found' | 'warnings'>,
  total: number,
): UndoOutcome {
  const restored = res.restored.length
  const conflicts = Object.entries(res.conflicts)
  const problems: string[] = []
  if (conflicts.length) {
    const named = conflicts
      .slice(0, NAMED_CONFLICTS)
      .map(([pn, why]) => `${pn}: ${conflictReason(why)}`)
      .join(' · ')
    const more = conflicts.length > NAMED_CONFLICTS ? ` … und ${formatNumber(conflicts.length - NAMED_CONFLICTS)} weitere` : ''
    problems.push(`${plural(conflicts.length, 'Bauteil', 'Bauteile')} übersprungen – ${named}${more}`)
  }
  if (res.not_found.length) {
    problems.push(`${plural(res.not_found.length, 'Änderung ist', 'Änderungen sind')} nicht mehr in der Änderungshistorie`)
  }
  if (!restored) {
    return problems.length
      ? { tone: 'warning', title: 'Nichts zurückgesetzt', description: problems.join('. ') }
      : { tone: 'info', title: 'Nichts zurückzusetzen', description: 'Die Bauteile haben schon wieder die alten Werte.' }
  }
  if (problems.length) {
    return {
      tone: 'warning',
      title: `${formatNumber(restored)} von ${plural(Math.max(total, restored), 'Bauteil', 'Bauteilen')} zurückgesetzt`,
      description: problems.join('. '),
    }
  }
  return {
    tone: 'success',
    title: restored === 1 ? `„${res.restored[0]}“ zurückgesetzt` : `${plural(restored, 'Bauteil', 'Bauteile')} zurückgesetzt`,
    description: res.warnings[0],
  }
}

/** „Rückgängig“: alte Werte zurück, Tabelle, Details, Verlauf und Kennzahlen neu laden, Ergebnis melden */
export async function restoreUpdates(qc: QueryClient, table: string, auditIds: number[]): Promise<RestoreUpdatesResult | null> {
  const id = toast.loading('Änderung wird zurückgenommen …')
  try {
    const res = await partsApi.restoreUpdates(table, auditIds)
    invalidateParts(qc, table)
    const outcome = restoreUpdatesOutcome(res, auditIds.length)
    const opts = { id, description: outcome.description }
    if (outcome.tone === 'success') toast.success(outcome.title, opts)
    else if (outcome.tone === 'warning') toast.warning(outcome.title, { ...opts, duration: 12_000 })
    else toast.info(outcome.title, opts)
    return res
  } catch (err) {
    toast.error('Rückgängig fehlgeschlagen', { id, description: errorMessage(err) })
    return null
  }
}

/**
 * Erfolgsmeldung einer Massenänderung bzw. von „Texte neu erzeugen“ mit „Rückgängig“ (eigene ID je Änderung – eine
 * zweite Änderung ersetzt nie das „Rückgängig“ der ersten). Mit automatischer Sicherung nennt sie den Ordner.
 */
export function showChangeToast(qc: QueryClient, table: string, res: ChangeResult, title: string, description?: string): void {
  const ids = res.audit_ids ?? []
  const text = [description, res.backup ? 'Vorher gesichert im Ordner „Backups“.' : null].filter(Boolean).join(' ')
  toast.success(title, {
    id: `changed:${table}:${++changeToastCounter}`,
    description: text || undefined,
    duration: ids.length ? UNDO_TOAST_MS : undefined,
    action: ids.length ? { label: 'Rückgängig', onClick: () => void restoreUpdates(qc, table, ids) } : undefined,
  })
}
