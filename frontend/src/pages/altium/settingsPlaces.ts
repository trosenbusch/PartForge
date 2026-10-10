import { t as tr } from '@/lib/i18n'
export const SETTINGS_PLACE = {
  /** Karte „Altium Designer“: X2.EXE, Bibliotheks-Writer, Aktualisierung */
  altium: { get label() { return tr("Einstellungen › Allgemein › Altium Designer") }, to: '/einstellungen#altium' },
  /** Karte „KI-Funktionen“: Schlüssel, Modell, Gründlichkeit, Kostenlimit */
  ai: { get label() { return tr("Einstellungen › Allgemein › KI-Funktionen") }, to: '/einstellungen#ki' },
  /** Hausstil, Reiter „Lagen“ (Lagenzuordnung der Footprints) */
  layers: { get label() { return tr("Einstellungen › Hausstil › Lagen") }, to: '/einstellungen/hausstil?ansicht=lagen' },
} as const

/** Download des 64-Bit-SQLite-ODBC-Treibers, über den Altium die Datenbank liest (README „Voraussetzungen“) */
export const SQLITE_ODBC_URL = 'http://www.ch-werner.de/sqliteodbc/'
