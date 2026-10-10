/** Regeln von „In Altium bearbeiten“ ohne Komponenten (Fast Refresh): wann es geht, Rückfrage vor dem Ersetzen. */
import { t as tr } from '@/components/preview/i18n'
import { confirm } from '@/components/ui'

/** Mindestangaben eines Registry-Eintrags (Symbol oder Footprint) */
export interface AltiumEditRecord {
  name: string
  source: string
  status: string
}

/** Warum das Bauteil nicht in Altium bearbeitet werden kann (`null` = es geht). */
export function altiumEditBlocker(rec: AltiumEditRecord | null | undefined, fileExists: boolean | undefined): string | null {
  if (!rec) return null
  if (rec.source === 'external') return tr('Gehört zu einer externen Bibliothek – bitte die Bibliothek selbst in Altium öffnen.')
  if (rec.status !== 'ok') return tr('Erst nach dem Synchronisieren möglich – das Bauteil ist noch nicht in der Bibliotheksdatei.')
  if (fileExists === false) return tr('Die Bibliotheksdatei wurde nicht gefunden.')
  return null
}

/**
 * Rückfrage vor „Bearbeiten“ / „Neu generieren“ einer in Altium bearbeiteten Fassung. `true` = fortfahren (auch für
 * Bauteile, die nicht aus Altium stammen – dann ohne Rückfrage).
 */
export async function confirmReplaceAltiumVersion(rec: AltiumEditRecord | null | undefined, action: 'edit' | 'rebuild'): Promise<boolean> {
  if (!rec || rec.source !== 'altium') return true
  return confirm({
    title: tr('Fassung aus Altium ersetzen?'),
    description: tr('„{0}“ wurde in Altium bearbeitet. Speichert PartForge es aus dem Generator neu, ersetzt das die Fassung aus Altium – Änderungen, die nur dort gemacht wurden, gehen verloren (die vorherige Datei bleibt in Backups\\lib).', { 0: rec.name }),
    confirmLabel: action === 'edit' ? tr('Trotzdem bearbeiten') : tr('Trotzdem neu generieren'),
    destructive: true,
  })
}
