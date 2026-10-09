import { createContext, useContext } from 'react'
import { flushSync } from 'react-dom'
import type { ThemePreference } from '@/api/system'
import { useUi } from './stores'

export type ResolvedTheme = 'dark' | 'light'

export const ThemeContext = createContext<ResolvedTheme>('dark')

const LIGHT_QUERY = '(prefers-color-scheme: light)'

export function prefersLight(): boolean {
  return typeof window !== 'undefined' && window.matchMedia?.(LIGHT_QUERY).matches === true
}

export function watchSystemTheme(onChange: (light: boolean) => void): () => void {
  const mq = window.matchMedia?.(LIGHT_QUERY)
  if (!mq) return () => {}
  const handler = () => onChange(mq.matches)
  mq.addEventListener('change', handler)
  return () => mq.removeEventListener('change', handler)
}

export function resolveTheme(theme: ThemePreference, systemLight = prefersLight()): ResolvedTheme {
  if (theme === 'system') return systemLight ? 'light' : 'dark'
  return theme
}

export function applyTheme(resolved: ResolvedTheme): void {
  const root = document.documentElement
  root.dataset.theme = resolved
  root.style.colorScheme = resolved
}

export interface ThemeApi {
  /** Präferenz (dark | light | system) */
  theme: ThemePreference
  /** Tatsächlich aktives Theme */
  resolvedTheme: ResolvedTheme
  /** Theme wechseln – mit weicher Überblendung (View Transitions), sofern verfügbar */
  setTheme: (theme: ThemePreference) => void
}

/** Theme lesen und wechseln. */
export function useTheme(): ThemeApi {
  const theme = useUi((s) => s.theme)
  const setStoredTheme = useUi((s) => s.setTheme)
  const resolvedTheme = useContext(ThemeContext)

  const setTheme = (next: ThemePreference) => {
    const target = resolveTheme(next)
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const doc = document as Document & { startViewTransition?: (cb: () => void) => unknown }
    if (target !== resolvedTheme && typeof doc.startViewTransition === 'function' && !reduce) {
      // React muss *innerhalb* des Callbacks fertig rendern, sonst landen themeabhängige Teile
      // (Toaster, Diagramme) erst nach dem Schnappschuss im neuen Zustand.
      doc.startViewTransition(() => {
        applyTheme(target)
        flushSync(() => setStoredTheme(next))
      })
    } else {
      setStoredTheme(next)
    }
  }

  return { theme, resolvedTheme, setTheme }
}
