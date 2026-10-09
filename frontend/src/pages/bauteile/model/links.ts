/** Dateien und Links der Bibliothek öffnen (Datenblatt-URL im Browser, Dateien über die Desktop-Brücke). */
import { openPath } from '@/lib/native'

/** Absoluter Pfad einer Datei der Bibliothek (relativ gespeicherte Pfade beziehen sich auf den Bibliotheksordner) */
export function resolveLibraryPath(root: string | undefined, value: string): string {
  const v = value.trim()
  if (/^[a-z]:[\\/]/i.test(v) || v.startsWith('\\\\') || v.startsWith('/')) return v
  if (!root) return v
  return `${root.replace(/[\\/]+$/, '')}\\${v.replace(/\//g, '\\')}`
}

/** Was ein Pfadfeld enthält – für die Meldungen von „Im Explorer zeigen“ */
export function pathLabel(column: string): string {
  return /^(Library|Footprint) Path( \d+)?$/.test(column) ? 'Bibliotheksdatei' : 'Datei'
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim())
}

/** Datenblatt öffnen: URL im Browser, Datei über die Desktop-Brücke. false = nicht möglich. */
export async function openDatasheet(value: string, root: string | undefined): Promise<boolean> {
  if (isHttpUrl(value)) {
    window.open(value, '_blank', 'noopener,noreferrer')
    return true
  }
  return openPath(resolveLibraryPath(root, value))
}
