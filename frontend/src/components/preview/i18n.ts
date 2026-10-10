import {
  getLanguage,
  localizeMessage as localizeSharedMessage,
  t as translateShared,
  type TranslationParams,
} from '@/lib/i18n'
import geometryMessages from '@/i18n/catalogs/geometry'

export { getLocale, useI18n } from '@/lib/i18n'

/** Engineering terms have domain meanings: Sicherung is a fuse, Seite a pin side. */
export function t(source: string, params?: TranslationParams): string {
  if (getLanguage() !== 'en' || !Object.hasOwn(geometryMessages, source)) return translateShared(source, params)
  const message = geometryMessages[source]
  return params
    ? message.replace(/\{(\w+)\}/g, (placeholder, name: string) => Object.hasOwn(params, name) ? String(params[name]) : placeholder)
    : message
}

/** Translate backend diagnostics only where they are displayed. */
export function localizeMessage(source: string): string {
  return getLanguage() === 'en' && Object.hasOwn(geometryMessages, source)
    ? geometryMessages[source]
    : localizeSharedMessage(source)
}
