/**
 * Brücke zum Desktop-Fenster (pywebview). Im normalen Browser sind diese Funktionen nicht verfügbar –
 * Aufrufer zeigen dann nur das Textfeld.
 *
 * Erwartete (optionale) Python-API (`webview.create_window(..., js_api=Api())`, `partforge/desktop.py`):
 *   pick_folder(initial: str | None) -> str | None
 *   pick_file(initial: str | None, filters: list[str] | None) -> str | None   # z. B. ["Programme (*.exe)"]
 *   save_file(suggested_name: str, content: str, filters: list[str] | None) -> str | None
 *       # content = Text (UTF-8) oder "base64:<daten>" für Binärdateien; Rückgabe = Pfad bzw. None (abgebrochen)
 *   pick_save_path(suggested_name: str, filters: list[str] | None) -> str | None
 *       # nur der Speichern-Dialog (schreibt nichts): Zielpfad bzw. None – das Backend schreibt dann selbst dorthin
 *       # (z. B. der Export-Job), ohne den Inhalt als Base64 durch die Brücke zu schicken
 *   open_path(path: str) -> None          # Ordner öffnen bzw. Dokument mit der zugeordneten Anwendung
 *   reveal_path(path: str) -> None        # im Explorer zeigen (Datei markiert), öffnet nie die Datei selbst
 *
 * Dateien speichern: **`saveFile`/`saveBlob` aus `@/lib/download`** (Brücke → Speichern-Dialog → Download-Link).
 * „Im Explorer zeigen“: **`revealPath(pfad)`** (außerhalb des Desktop-Programms: Pfad kopieren + Hinweis).
 *
 * pywebview stellt `window.pywebview.api` erst nach dem Laden bereit (Ereignis `pywebviewready`) –
 * deshalb in Komponenten `useNativeBridge()` verwenden, nicht einmalig beim Rendern prüfen.
 */
import { useSyncExternalStore } from 'react'
import { toast } from 'sonner'

export interface PyWebviewApi {
  pick_folder?: (initial?: string | null) => Promise<string | null>
  pick_file?: (initial?: string | null, filters?: string[] | null) => Promise<string | null>
  save_file?: (suggestedName: string, content: string, filters?: string[] | null) => Promise<string | null>
  pick_save_path?: (suggestedName: string, filters?: string[] | null) => Promise<string | null>
  open_path?: (path: string) => Promise<void>
  reveal_path?: (path: string) => Promise<void>
}

declare global {
  interface Window {
    pywebview?: { api?: PyWebviewApi }
  }
}

function api(): PyWebviewApi | undefined {
  return typeof window === 'undefined' ? undefined : window.pywebview?.api
}

/** Die Desktop-Brücke (pywebview) – `undefined` im normalen Browser bzw. bevor sie bereit ist. */
export function nativeApi(): PyWebviewApi | undefined {
  return api()
}

/** Läuft die Oberfläche im Desktop-Fenster (pywebview / WebView2)? Auch wahr, solange die Brücke noch lädt. */
export function isDesktopWindow(): boolean {
  if (typeof window === 'undefined') return false
  const w = window as Window & { chrome?: { webview?: unknown } }
  return Boolean(w.pywebview) || Boolean(w.chrome?.webview)
}

export function hasNativeSave(): boolean {
  return typeof api()?.save_file === 'function'
}

/** `pick_save_path` vorhanden: Speichern-Dialog ohne Inhalt (`saveFile({ saveTo })` aus `@/lib/download`) */
export function canPickSavePath(): boolean {
  return typeof api()?.pick_save_path === 'function'
}

export function hasNativeFolderPicker(): boolean {
  return typeof api()?.pick_folder === 'function'
}

export function hasNativeFilePicker(): boolean {
  return typeof api()?.pick_file === 'function'
}

export function canOpenPath(): boolean {
  return typeof api()?.open_path === 'function'
}

export async function pickFolder(initial?: string | null): Promise<string | null> {
  const fn = api()?.pick_folder
  if (!fn) return null
  try {
    return (await fn(initial ?? null)) ?? null
  } catch (e) {
    // wie Abbrechen behandeln – aber sichtbar für die Fehlersuche (Details im Protokoll des Programms)
    console.error('Ordnerdialog fehlgeschlagen', e)
    return null
  }
}

export async function pickFile(initial?: string | null, filters?: string[]): Promise<string | null> {
  const fn = api()?.pick_file
  if (!fn) return null
  try {
    return (await fn(initial ?? null, filters ?? null)) ?? null
  } catch (e) {
    // wie Abbrechen behandeln – aber sichtbar für die Fehlersuche (Details im Protokoll des Programms)
    console.error('Dateidialog fehlgeschlagen', e)
    return null
  }
}

export async function openPath(path: string): Promise<boolean> {
  const fn = api()?.open_path
  if (!fn) return false
  try {
    await fn(path)
    return true
  } catch {
    return false
  }
}

export function canRevealPath(): boolean {
  return typeof api()?.reveal_path === 'function'
}

/** Ergebnis von {@link revealPath} */
export type RevealResult =
  /** Explorer zeigt die Datei markiert (bzw. öffnet den Ordner) */
  | 'revealed'
  /** ohne Desktop-Brücke: Pfad in die Zwischenablage kopiert */
  | 'copied'
  /** nichts möglich (z. B. Pfad existiert nicht, Zwischenablage gesperrt) – mit Toast gemeldet */
  | 'failed'

export interface RevealOptions {
  /** Rückmeldung als Toast (Standard: ja) – Fehler, Kopie im Browser */
  toast?: boolean
  /** Was gezeigt wird, für die Meldungen (Standard „Pfad“), z. B. „Bibliotheksdatei“ */
  what?: string
}

const parentDir = (path: string) => path.replace(/[\\/]+$/, '').replace(/[\\/][^\\/]*$/, '') || path

/**
 * Datei bzw. Ordner im Windows-Explorer zeigen – die Datei ist markiert, sie wird **nie** geöffnet
 * (`window.pywebview.api.reveal_path`, `partforge/desktop.py`). Ältere Desktop-Brücke ohne `reveal_path`: Ordner öffnen.
 * Außerhalb des Desktop-Programms (Browser, Vite) kann PartForge keinen Explorer öffnen: der Pfad wird kopiert und ein
 * Hinweis erscheint.
 *
 *   <Button leftIcon={<FolderOpen />} onClick={() => void revealPath(file.path)}>Im Explorer zeigen</Button>
 */
export async function revealPath(path: string, opts: RevealOptions = {}): Promise<RevealResult> {
  const { toast: notify = true, what = 'Pfad' } = opts
  const bridge = api()
  if (bridge?.reveal_path || bridge?.open_path) {
    try {
      if (bridge.reveal_path) await bridge.reveal_path(path)
      else await bridge.open_path?.(parentDir(path))
      return 'revealed'
    } catch (err) {
      if (notify) {
        // pywebview lehnt mit einem Error bzw. einem Objekt { name, message } der Python-Ausnahme ab
        const raw = typeof err === 'string' ? err : err && typeof err === 'object' ? (err as { message?: unknown }).message : null
        const message = typeof raw === 'string' ? raw : ''
        toast.error(`${what} konnte nicht im Explorer gezeigt werden`, {
          id: 'pf-reveal-path',
          description: /nicht gefunden|not found|no such/i.test(message)
            ? `Nicht gefunden: ${path}`
            : `${message || 'Unbekannter Fehler'} – ${path}`,
        })
      }
      return 'failed'
    }
  }
  try {
    await navigator.clipboard.writeText(path)
    if (notify) {
      toast.success(`${what} kopiert`, {
        id: 'pf-reveal-path',
        description: `${path} – den Explorer kann PartForge nur im Desktop-Programm öffnen.`,
      })
    }
    return 'copied'
  } catch {
    if (notify) {
      toast.info(what, {
        id: 'pf-reveal-path',
        description: `${path} – der Explorer lässt sich nur im Desktop-Programm öffnen.`,
        duration: 9000,
      })
    }
    return 'failed'
  }
}

// --------------------------------------------------------------------------- reaktiver Zustand

export interface NativeBridge {
  canPickFolder: boolean
  canPickFile: boolean
  canOpenPath: boolean
  /** `save_file` vorhanden (nativer Speichern-Dialog, siehe `@/lib/download`) */
  canSaveFile: boolean
  /** `reveal_path` vorhanden – `revealPath()` zeigt die Datei markiert im Explorer (sonst: Pfad kopieren) */
  canRevealPath: boolean
  /** `pick_save_path` vorhanden – Speichern-Dialog zuerst, das Backend schreibt die Datei selbst (`saveFile({ saveTo })`) */
  canPickSavePath: boolean
}

let snapshot: NativeBridge = {
  canPickFolder: false,
  canPickFile: false,
  canOpenPath: false,
  canSaveFile: false,
  canRevealPath: false,
  canPickSavePath: false,
}

function readBridge(): NativeBridge {
  const next: NativeBridge = {
    canPickFolder: hasNativeFolderPicker(),
    canPickFile: hasNativeFilePicker(),
    canOpenPath: canOpenPath(),
    canSaveFile: hasNativeSave(),
    canRevealPath: canRevealPath(),
    canPickSavePath: canPickSavePath(),
  }
  if (
    next.canPickFolder !== snapshot.canPickFolder ||
    next.canPickFile !== snapshot.canPickFile ||
    next.canOpenPath !== snapshot.canOpenPath ||
    next.canSaveFile !== snapshot.canSaveFile ||
    next.canRevealPath !== snapshot.canRevealPath ||
    next.canPickSavePath !== snapshot.canPickSavePath
  ) {
    snapshot = next
  }
  return snapshot
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('pywebviewready', onChange)
  return () => window.removeEventListener('pywebviewready', onChange)
}

/** Welche Desktop-Funktionen verfügbar sind – aktualisiert sich, sobald pywebview bereit ist. */
export function useNativeBridge(): NativeBridge {
  return useSyncExternalStore(subscribe, readBridge, () => snapshot)
}
