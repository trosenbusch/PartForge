/**
 * Das gerade bearbeitete Feld (fokussiertes CommitInput/CellInput) übernimmt seinen getippten Wert erst beim
 * Verlassen. Strg+Enter („Bauteile anlegen“) ruft vorher `flushActiveInput()` auf – so geht nichts verloren, was
 * gerade getippt wurde, und der Fokus bleibt im Feld.
 */
let activeFlush: (() => void) | null = null

export function setActiveFlush(flush: (() => void) | null): void {
  activeFlush = flush
}

/** Nur abmelden, wenn `flush` noch das aktive Feld ist (ein anderes Feld kann schon fokussiert sein). */
export function clearActiveFlush(flush: () => void): void {
  if (activeFlush === flush) activeFlush = null
}

/** Getippten, noch nicht übernommenen Wert des fokussierten Feldes sofort übernehmen. */
export function flushActiveInput(): void {
  activeFlush?.()
}
