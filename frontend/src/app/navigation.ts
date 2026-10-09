/**
 * Navigation außerhalb von Komponenten – z. B. Aktionen von Job-Toasts aus `@/api/jobs` („Writer einrichten“ →
 * `/einstellungen#altium`). Der Router meldet sich beim Start an (`router.tsx`); ohne ihn lädt die Adresse neu.
 *
 *   appNavigate('/einstellungen#altium')
 *   appNavigate(ALTIUM_PATH, { state: altiumActionState('sync') })   // Aktion der Altium-Seite auslösen
 */
export interface AppNavigateOptions {
  /** Router-State der neuen Adresse (steht nicht in der URL) */
  state?: unknown
  replace?: boolean
}

type Navigate = (to: string, options?: AppNavigateOptions) => void

let current: Navigate | null = null

/** Vom Router aufgerufen (einmal beim Start). */
export function setAppNavigate(navigate: Navigate | null): void {
  current = navigate
}

export function appNavigate(to: string, options?: AppNavigateOptions): void {
  if (current) current(to, options)
  // ohne Router nur die Adresse: eine Aktion im Router-State entfällt dann (nie ungewollt ausgeführt)
  else window.location.assign(to)
}

// --------------------------------------------------------------------------- Aktionen der Altium-Seite

/**
 * Aktionen, die andere Stellen der App (Shell-Befehle, Übersicht, Job-Toasts, Ergebnisansichten) auf der Altium-Seite
 * auslösen: DbLib neu erzeugen, Bibliotheksdateien synchronisieren (→ Reiter „dateien“), Bibliothek prüfen
 * (→ „pruefbericht“), in Altium installieren bzw. aktualisieren, ODBC-Test (Dialog), DbLib-Vorschau.
 *
 * Sie reisen als **Router-State**, nie als Parameter der Adresse:
 *
 *   navigate(ALTIUM_PATH, { state: altiumActionState('sync') })
 *   <Link to={ALTIUM_PATH} state={altiumActionState('pruefen')}>
 *
 * Den State setzt nur PartForge selbst – ein Link oder Rahmen einer fremden Website, ein Lesezeichen oder ein Link
 * in einer Mail kann so keine Aktion auslösen (früher `/altium?aktion=…`, Sicherheitsbefund
 * „sec-spa-crosssite-aktion“). Die Altium-Seite führt die Aktion einmal aus und löscht den State (Neuladen und
 * Zurück lösen sie nicht erneut aus); ein `?aktion=` in der Adresse ignoriert sie.
 */
export const ALTIUM_ACTIONS = ['dblib', 'sync', 'pruefen', 'installieren', 'aktualisieren', 'odbc', 'vorschau'] as const
export type AltiumAction = (typeof ALTIUM_ACTIONS)[number]

/** Adresse der Altium-Seite */
export const ALTIUM_PATH = '/altium'

/** Router-State, mit dem eine Navigation zur Altium-Seite dort eine Aktion auslöst */
export interface AltiumActionState {
  aktion: AltiumAction
}

export function altiumActionState(aktion: AltiumAction): AltiumActionState {
  return { aktion }
}

/** Aktion aus dem Router-State der Altium-Seite (`location.state`): nur bekannte Werte, sonst `null`. */
export function altiumActionFromState(state: unknown): AltiumAction | null {
  if (!state || typeof state !== 'object') return null
  const aktion = (state as { aktion?: unknown }).aktion
  return typeof aktion === 'string' && (ALTIUM_ACTIONS as readonly string[]).includes(aktion) ? (aktion as AltiumAction) : null
}
