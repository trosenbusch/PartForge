/**
 * Orte in den Einstellungen – **ein** Wortlaut für alle Texte (Trenner „›“, gegliedert wie die Oberfläche) und die
 * Adresse dorthin. Texte nennen den Ort mit `label`, Knöpfe und Links springen mit `to` hin. Das Backend schreibt
 * dieselben Orte (`partforge/altium/texts.py`).
 *
 *   `Pfad unter ${SETTINGS_PLACE.altium.label} eintragen`   → „… unter Einstellungen › Allgemein › Altium Designer …“
 *   navigate(SETTINGS_PLACE.altium.to)                       → /einstellungen#altium
 *
 * Begriffe: das Programm, das SchLib/PcbLib schreibt, heißt in allen Texten **Bibliotheks-Writer** ({@link WRITER};
 * der Dateiname `altium-designer-mcp.exe` nur in Hilfetexten).
 */
export const SETTINGS_PLACE = {
  /** Karte „Altium Designer“: X2.EXE, Bibliotheks-Writer, Schreibweg, Aktualisierung */
  altium: { label: 'Einstellungen › Allgemein › Altium Designer', to: '/einstellungen#altium' },
  /** Feld „Bibliotheks-Writer“ in der Karte „Altium Designer“ */
  writer: { label: 'Einstellungen › Allgemein › Altium Designer › Bibliotheks-Writer', to: '/einstellungen#altium' },
  /** Karte „KI-Funktionen“: Schlüssel, Modell, Gründlichkeit, Kostenlimit */
  ai: { label: 'Einstellungen › Allgemein › KI-Funktionen', to: '/einstellungen#ki' },
  /** Bibliothekseinstellungen: Pfade, Datenbank, Teilenummern, Sicherungen */
  library: { label: 'Einstellungen › Bibliothek', to: '/einstellungen/bibliothek' },
  /** Hausstil, Reiter „Lagen“ (Lagenzuordnung der Footprints) */
  layers: { label: 'Einstellungen › Hausstil › Lagen', to: '/einstellungen/hausstil?ansicht=lagen' },
} as const

export type SettingsPlace = keyof typeof SETTINGS_PLACE

/** Name des Programms, das Symbole und Footprints in SchLib/PcbLib schreibt – in allen Oberflächentexten */
export const WRITER = 'Bibliotheks-Writer'
