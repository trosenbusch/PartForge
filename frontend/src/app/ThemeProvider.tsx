import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useLayoutEffect, useState, type ReactNode } from 'react'
import { systemApi, systemKeys, useSettings } from '@/api/system'
import { useUi } from './stores'
import { applyTheme, prefersLight, resolveTheme, ThemeContext, watchSystemTheme } from './theme'

/**
 * Setzt data-theme auf <html> (dark | light) und folgt bei „system“ dem Betriebssystem.
 * Synchronisation mit den App-Einstellungen (settings.json):
 * - noch keine lokale Wahl → Theme aus dem Backend übernehmen (Erststart),
 * - lokale Wahl (Topbar-Menü, Einstellungen, Befehlspalette) → im Backend speichern.
 * Lesen/Wechseln: `useTheme()` aus `@/app/theme`.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useUi((s) => s.theme)
  const themeExplicit = useUi((s) => s.themeExplicit)
  const [systemLight, setSystemLight] = useState(prefersLight)
  const qc = useQueryClient()

  useEffect(() => watchSystemTheme(setSystemLight), [])

  const resolved = resolveTheme(theme, systemLight)

  useLayoutEffect(() => {
    applyTheme(resolved)
  }, [resolved])

  const settings = useSettings().data
  useEffect(() => {
    if (!settings) return
    const backendTheme = settings.settings.theme
    if (!themeExplicit) {
      if (backendTheme !== theme) useUi.setState({ theme: backendTheme })
      return
    }
    if (backendTheme === theme) return
    const timer = setTimeout(() => {
      // frisch laden und nur das Theme ändern – vom Server verwaltete Felder (zuletzt geöffnet …) bleiben unberührt
      systemApi
        .updateSettings((current) => ({ ...current, theme }))
        .then((out) => qc.setQueryData(systemKeys.settings, out))
        .catch(() => {
          // lokal bleibt das Theme trotzdem aktiv
        })
    }, 500)
    return () => clearTimeout(timer)
  }, [settings, theme, themeExplicit, qc])

  return <ThemeContext.Provider value={resolved}>{children}</ThemeContext.Provider>
}
