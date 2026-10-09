/** Kleine Hooks der Einstellungsseite */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { readPref, writePref } from '@/lib/prefs'

/** Text in die Zwischenablage kopieren (mit Bestätigung) */
export function useCopyText() {
  const [copied, setCopied] = useState<string | null>(null)
  const copy = async (text: string, what = 'Pfad') => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(text)
      window.setTimeout(() => setCopied((c) => (c === text ? null : c)), 1600)
      toast.success(`${what} kopiert`, { id: 'settings-copy', description: text })
    } catch {
      toast.error(`${what} konnte nicht kopiert werden`, { id: 'settings-copy' })
    }
  }
  return { copied, copy }
}

/** Kleine UI-Vorliebe (bleibt über Neustarts erhalten, siehe `@/lib/prefs`) */
export function useBooleanPref(name: string, initial: boolean): [boolean, (value: boolean) => void] {
  const [value, setValue] = useState(() => {
    const stored = readPref(name)
    return stored === null ? initial : stored === '1'
  })
  const set = (next: boolean) => {
    setValue(next)
    writePref(name, next ? '1' : '0')
  }
  return [value, set]
}

/** Gemerkte Auswahl aus einer festen Liste (z. B. Reiter) */
export function useChoicePref<T extends string>(name: string, choices: readonly T[], initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    const stored = readPref(name)
    return stored && (choices as readonly string[]).includes(stored) ? (stored as T) : initial
  })
  const set = (next: T) => {
    setValue(next)
    writePref(name, next)
  }
  return [value, set]
}

/** Wert erst nach einer Pause übernehmen (z. B. für Vorschau-Anfragen beim Ziehen eines Farbreglers) */
export function useDebounced<T>(value: T, ms = 350): T {
  const [debounced, setDebounced] = useState(value)
  const key = JSON.stringify(value)
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(JSON.parse(key) as T), ms)
    return () => window.clearTimeout(t)
  }, [key, ms])
  return debounced
}
