/** Anzeigetexte der Footprint-Bibliothek (Status, Herkunft). */
import type { BadgeVariantProps } from '@/components/ui'

type BadgeVariant = NonNullable<BadgeVariantProps['variant']>

export const STATUS_META: Record<string, { label: string; variant: BadgeVariant; text: string }> = {
  ok: { label: 'Aktuell', variant: 'success', text: 'In der PcbLib vorhanden und aktuell.' },
  pending: { label: 'Ausstehend', variant: 'warning', text: 'Noch nicht in die PcbLib geschrieben – „Synchronisieren“ in Altium.' },
  missing: { label: 'Fehlt', variant: 'danger', text: 'In der PcbLib nicht gefunden.' },
  error: { label: 'Fehler', variant: 'danger', text: 'Beim Schreiben ist ein Fehler aufgetreten.' },
}

export const statusMeta = (status: string) =>
  STATUS_META[status] ?? { label: status, variant: 'neutral' as BadgeVariant, text: '' }

export const SOURCE_LABEL: Record<string, string> = {
  generated: 'Generator',
  datasheet: 'Datenblatt (KI)',
  imported: 'Importiert',
  external: 'Externe Bibliothek',
}
