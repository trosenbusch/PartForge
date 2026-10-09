/**
 * Sprungziele innerhalb von „Allgemein“ (Karten-IDs). Erreichbar über das Inhaltsverzeichnis rechts und als
 * Adresse, z. B. `/einstellungen#ki` (API-Schlüssel) oder `/einstellungen#altium` (X2-Pfad, Bibliotheks-Writer).
 *
 * `/einstellungen#altium` setzt den Fokus **in das Feld „Bibliotheks-Writer“**, solange kein Writer gefunden ist (Ziel
 * von „Bibliotheks-Writer einrichten“ – nach dem Anlegen einer Bibliothek, auf der Altium-Seite, in der Seitenleiste);
 * sonst auf die Kartenüberschrift.
 */
export const GENERAL_ANCHORS = [
  { id: 'profil', label: 'Profil und Darstellung' },
  { id: 'ki', label: 'KI-Funktionen' },
  { id: 'altium', label: 'Altium Designer' },
] as const

export type GeneralAnchor = (typeof GENERAL_ANCHORS)[number]['id']

export const isGeneralAnchor = (id: string): id is GeneralAnchor => GENERAL_ANCHORS.some((a) => a.id === id)

/** ID des Felds „Bibliotheks-Writer“ (Pfad zur altium-designer-mcp.exe) */
export const WRITER_FIELD_ID = 'einstellungen-bibliotheks-writer'
/** ID des Felds „Altium Designer (X2.EXE)“ */
export const X2_FIELD_ID = 'einstellungen-altium-x2'

/**
 * Karte in den Blick holen (ohne Animation bei „Bewegung reduzieren“) und den Fokus auf ihre Überschrift setzen,
 * damit Tastatur und Screenreader dort weitermachen. `focusId` = stattdessen dieses Feld der Karte fokussieren
 * (mittig in den Blick).
 */
export function revealAnchor(id: string, focusId?: string | null): boolean {
  const el = document.getElementById(id)
  if (!el) return false
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
  const field = focusId ? document.getElementById(focusId) : null
  if (field && el.contains(field)) {
    field.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' })
    field.focus({ preventScroll: true })
    return true
  }
  el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
  const heading = el.querySelector<HTMLElement>('h2') ?? el
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1')
  heading.focus({ preventScroll: true })
  return true
}
