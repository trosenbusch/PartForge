import { t as tr } from '@/lib/i18n'
export const SETTINGS_PLACE = {
  /** Karte „Altium Designer“: X2.EXE, Bibliotheks-Writer, Schreibweg, Aktualisierung */
  altium: { get label() { return tr("Einstellungen › Allgemein › Altium Designer") }, to: '/einstellungen#altium' },
  /** Feld „Bibliotheks-Writer“ in der Karte „Altium Designer“ */
  writer: { get label() { return tr("Einstellungen › Allgemein › Altium Designer › Bibliotheks-Writer") }, to: '/einstellungen#altium' },
  /** Karte „KI-Funktionen“: Schlüssel, Modell, Gründlichkeit, Kostenlimit */
  ai: { get label() { return tr("Einstellungen › Allgemein › KI-Funktionen") }, to: '/einstellungen#ki' },
  /** Bibliothekseinstellungen: Pfade, Datenbank, Teilenummern, Sicherungen */
  library: { get label() { return tr("Einstellungen › Bibliothek") }, to: '/einstellungen/bibliothek' },
  /** Hausstil, Reiter „Lagen“ (Lagenzuordnung der Footprints) */
  layers: { get label() { return tr("Einstellungen › Hausstil › Lagen") }, to: '/einstellungen/hausstil?ansicht=lagen' },
} as const

export type SettingsPlace = keyof typeof SETTINGS_PLACE

/** Name des Programms, das Symbole und Footprints in SchLib/PcbLib schreibt – in allen Oberflächentexten */
export const WRITER = 'Bibliotheks-Writer'
