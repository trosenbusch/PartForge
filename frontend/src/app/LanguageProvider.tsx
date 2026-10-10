import { useLayoutEffect, type ReactNode } from 'react'
import { useSettings } from '@/api/system'
import { normalizeLanguage, setLanguage, useI18n } from '@/lib/i18n'

/** The application setting is authoritative, including after a save or a new port. */
export function LanguageProvider({ children }: { children: ReactNode }) {
  const settings = useSettings().data
  const { language } = useI18n()
  useLayoutEffect(() => {
    if (settings) setLanguage(normalizeLanguage(settings.settings.language))
    else document.documentElement.lang = language
  }, [settings, language])
  return children
}
