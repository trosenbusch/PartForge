/**
 * Aktionen auf mehreren Bauteilen: alle Treffer einer Abfrage holen bzw. zählen, Löschen mit Bestätigung
 * (Sicherungshinweis, „Rückgängig“ holt die gelöschten Bauteile aus der Änderungshistorie zurück) – für ausgewählte
 * Zeilen wie für **alle Treffer** von Suche und Filtern (Anzahl wird vorher bestätigt; ändern sich die Treffer bis zum
 * Löschen, fragt PartForge mit der neuen Zahl erneut).
 */
import type { QueryClient } from '@tanstack/react-query'
import { createElement } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import {
  invalidateParts,
  partsApi,
  PART_NUMBER,
  selectionChanged,
  type PartFilter,
  type PartRow,
  type PartSelection,
} from '@/api/parts'
import { confirm } from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'

/** Ab dieser Anzahl legt das Backend vor dem Löschen automatisch eine Sicherung an */
export const AUTO_BACKUP_THRESHOLD = 20
/** So viele Teilenummern nennt die Rückfrage */
const PREVIEW_PNS = 6
/** Zähler für die Toast-IDs der Lösch-Meldungen (je Löschen ein eigenes „Rückgängig“) */
let deleteToastCounter = 0

/** Alle Zeilen, die zu Suche und Filtern passen (z. B. zum Duplizieren aller Treffer) */
export async function fetchMatchingRows(table: string, search: string, filters: PartFilter[]): Promise<PartRow[]> {
  const page = await partsApi.query(table, { search: search || null, filters, sort: [], offset: 0, limit: 0 })
  return page.rows
}

/** Was gelöscht werden soll: bestimmte Zeilen oder alle Treffer der Abfrage */
export type DeleteTarget = { rows: PartRow[] } | { search: string; filters: PartFilter[] }

/** Gelöschte Bauteile aus der Änderungshistorie zurückholen (alle Werte, ursprüngliches Anlagedatum) */
export async function restoreParts(qc: QueryClient, table: string, partNumbers: string[]): Promise<string[]> {
  const id = toast.loading(`${plural(partNumbers.length, 'Bauteil wird', 'Bauteile werden')} wiederhergestellt …`)
  try {
    const res = await partsApi.restore(table, partNumbers)
    invalidateParts(qc, table)
    const conflicts = Object.values(res.conflicts)
    const problems = [...conflicts, ...res.not_found.map((pn) => `${pn}: keine Löschung in der Änderungshistorie`)]
    if (!res.restored.length) {
      toast.error('Nichts wiederhergestellt', { id, description: problems[0] ?? 'Die Bauteile sind nicht mehr in der Änderungshistorie.' })
    } else if (problems.length) {
      toast.warning(`${formatNumber(res.restored.length)} von ${formatNumber(partNumbers.length)} wiederhergestellt`, {
        id,
        description: problems.slice(0, 2).join(' · '),
        duration: 9000,
      })
    } else {
      toast.success(res.restored.length === 1 ? `„${res.restored[0]}“ wiederhergestellt` : `${plural(res.restored.length, 'Bauteil', 'Bauteile')} wiederhergestellt`, {
        id,
        description: res.warnings[0],
      })
    }
    return res.restored
  } catch (err) {
    toast.error('Wiederherstellen fehlgeschlagen', { id, description: errorMessage(err) })
    return []
  }
}

/** Beschreibung der Rückfrage (steht in einem <p> – darum nur <span>-Elemente) */
function deleteDescription(label: string, count: number, sample: string[], note?: string) {
  const many = count > AUTO_BACKUP_THRESHOLD
  return createElement(
    'span',
    { className: 'flex flex-col gap-2' },
    note && createElement('span', { className: 'block font-medium text-warning-text' }, note),
    count > 1 &&
      sample.length > 0 &&
      createElement(
        'span',
        { className: 'mono block text-xs text-fg' },
        sample.join(', ') + (count > sample.length ? ` … und ${formatNumber(count - sample.length)} weitere` : ''),
      ),
    createElement(
      'span',
      { className: 'block' },
      many
        ? `Aus „${label}“. Vorher legt PartForge automatisch eine Sicherung der Datenbank an (Ordner „Backups“); direkt danach nimmt „Rückgängig“ das Löschen zurück.`
        : `Aus „${label}“. Direkt danach lässt sich das Löschen mit „Rückgängig“ zurücknehmen.`,
    ),
  )
}

/**
 * Bauteile nach Bestätigung löschen – bestimmte Zeilen oder alle Treffer von Suche + Filtern. Gibt die gelöschten
 * Teilenummern zurück (leer bei Abbruch oder Fehler). Der Erfolgs-Toast bietet „Rückgängig“ an.
 */
export async function confirmAndDelete(qc: QueryClient, table: string, label: string, target: DeleteTarget): Promise<string[]> {
  let selection: PartSelection
  let count: number
  let sample: string[]
  if ('rows' in target) {
    const pns = target.rows.map((r) => String(r[PART_NUMBER] ?? '')).filter(Boolean)
    if (!pns.length) return []
    selection = { partNumbers: pns }
    count = pns.length
    sample = pns.slice(0, PREVIEW_PNS)
  } else {
    try {
      const res = await partsApi.count(table, { search: target.search, filters: target.filters, sample: PREVIEW_PNS })
      count = res.count
      sample = res.part_numbers
      selection = { search: target.search, filters: target.filters, expectedCount: res.count }
    } catch (err) {
      toast.error('Treffer konnten nicht gezählt werden', { description: errorMessage(err) })
      return []
    }
    if (!count) {
      toast.info('Keine Treffer mehr', { description: 'Zu Suche und Filtern passt kein Bauteil – es wurde nichts gelöscht.' })
      return []
    }
  }

  let note: string | undefined
  for (;;) {
    const ok = await confirm({
      title: count === 1 && sample[0] ? `„${sample[0]}“ löschen?` : `${plural(count, 'Bauteil', 'Bauteile')} löschen?`,
      description: deleteDescription(label, count, sample, note),
      confirmLabel: count === 1 ? 'Löschen' : `${formatNumber(count)} löschen`,
      destructive: true,
    })
    if (!ok) return []
    try {
      const res = await partsApi.remove(table, selection)
      const deleted = res.part_numbers
      invalidateParts(qc, table, { skipPns: deleted })
      toast.success(res.deleted === 1 ? `„${deleted[0] ?? sample[0]}“ gelöscht` : `${plural(res.deleted, 'Bauteil', 'Bauteile')} gelöscht`, {
        // eigene ID je Löschen: ein zweites Löschen ersetzt nie das „Rückgängig“ des ersten
        id: `deleted:${table}:${++deleteToastCounter}`,
        // Dateiname ist lang (Zeitstempel + Anlass) und bricht im Toast unschön um – der Ordner genügt.
        // Später geht es auch ohne Toast: Übersicht › Letzte Änderungen bzw. die Adresse des Bauteils
        // (`?pn=` zeigt „Bauteil gelöscht“ mit „Wiederherstellen“)
        description: res.backup
          ? 'Vorher gesichert im Ordner „Backups“. Später wiederherstellen: Übersicht › Letzte Änderungen.'
          : 'Später wiederherstellen: Übersicht › Letzte Änderungen.',
        // länger als üblich: Rückgängig soll in Ruhe erreichbar sein (der Zeitgeber pausiert beim Überfahren)
        duration: 30_000,
        action: deleted.length ? { label: 'Rückgängig', onClick: () => void restoreParts(qc, table, deleted) } : undefined,
      })
      return deleted
    } catch (err) {
      const changed = selectionChanged(err)
      if (changed && 'expectedCount' in selection) {
        // Treffer haben sich geändert (jemand hat Bauteile angelegt oder geändert): mit der neuen Zahl erneut fragen
        selection = { ...selection, expectedCount: changed.count }
        note = `Die Treffer haben sich geändert: jetzt ${plural(changed.count, 'Bauteil', 'Bauteile')} statt ${formatNumber(changed.expected)}.`
        count = changed.count
        try {
          sample = (await partsApi.count(table, { search: selection.search, filters: selection.filters, sample: PREVIEW_PNS })).part_numbers
        } catch {
          // Stichprobe ist nur Anzeige
        }
        if (!count) {
          toast.info('Keine Treffer mehr', { description: 'Es wurde nichts gelöscht.' })
          return []
        }
        continue
      }
      toast.error('Löschen fehlgeschlagen', { description: errorMessage(err) })
      return []
    }
  }
}
