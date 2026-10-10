import { useMemo, type DependencyList } from 'react'
import { useI18n } from '@/lib/i18n'

/** Recompute derived UI data when helpers read the current display language. */
export function useLocalizedMemo<T>(factory: () => T, dependencies: DependencyList): T {
  const { language } = useI18n()
  // Locale-aware helpers (formatters, validation and metadata labels) read language
  // implicitly. Callers supply the remaining dependencies exactly as for useMemo.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  return useMemo(factory, [language, ...dependencies])
}
