/**
 * Orte in den Einstellungen – **ein** Wortlaut für alle Texte der Seiten (Trenner „›“, wie die Oberfläche gegliedert
 * ist) und die Adresse dorthin. Texte nennen den Ort mit `label`, Knöpfe/Links springen mit `to` hin.
 *
 *   `Pfad unter ${SETTINGS_PLACE.altium.label} eintragen`      → „… unter Einstellungen › Allgemein › Altium Designer …“
 *   navigate(SETTINGS_PLACE.altium.to)                          → /einstellungen#altium
 */
export const SETTINGS_PLACE = {
  /** Karte „Altium Designer“: X2.EXE, Bibliotheks-Writer, Aktualisierung */
  altium: { label: 'Einstellungen › Allgemein › Altium Designer', to: '/einstellungen#altium' },
  /** Karte „KI-Funktionen“: Schlüssel, Modell, Gründlichkeit, Kostenlimit */
  ai: { label: 'Einstellungen › Allgemein › KI-Funktionen', to: '/einstellungen#ki' },
  /** Hausstil, Reiter „Lagen“ (Lagenzuordnung der Footprints) */
  layers: { label: 'Einstellungen › Hausstil › Lagen', to: '/einstellungen/hausstil?ansicht=lagen' },
} as const

/** Download des 64-Bit-SQLite-ODBC-Treibers, über den Altium die Datenbank liest (README „Voraussetzungen“) */
export const SQLITE_ODBC_URL = 'http://www.ch-werner.de/sqliteodbc/'
