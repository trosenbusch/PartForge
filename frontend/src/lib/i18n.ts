import { useMemo, useSyncExternalStore } from 'react'
import { readPref, writePref } from './prefs'
import partMetadata from '../i18n/catalogs/parts-metadata'

export type Language = 'en' | 'de'
export type TranslationParams = Record<string, string | number>
export const LANGUAGES = [{ value: 'en', label: 'English' }, { value: 'de', label: 'Deutsch' }] as const

// Source messages are German; catalogs supply English. Keeping interpolation in the
// translator ensures names, paths and other user data are never translated.
const modules = import.meta.glob<{ default: Record<string, string> }>('../i18n/catalogs/*.ts', { eager: true })
export const englishMessages: Readonly<Record<string, string>> = Object.assign(Object.create(null), ...Object.values(modules).map((m) => m.default))

export function normalizeLanguage(value: unknown): Language {
  return value === 'de' ? 'de' : 'en'
}

function initialLanguage(): Language {
  if (typeof document === 'undefined') return 'en'
  const saved = document.querySelector<HTMLMetaElement>('meta[name="partforge-language"]')?.content
  return normalizeLanguage(saved ?? readPref('pf-language'))
}

let language = initialLanguage()
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } }
export const getLanguage = (): Language => language
export const getLocale = (): string => language === 'de' ? 'de-DE' : 'en-US'

/** Apply a saved setting. Persistence in settings.json is handled by the settings API. */
export function setLanguage(next: Language): void {
  const normalized = normalizeLanguage(next)
  if (typeof document !== 'undefined') document.documentElement.lang = normalized
  writePref('pf-language', normalized)
  if (language === normalized) return
  language = normalized
  for (const listener of listeners) listener()
}

export function translate(source: string, selected: Language, params?: TranslationParams): string {
  const message = selected === 'de' ? source : (englishMessages[source] ?? source)
  return params ? message.replace(/\{(\w+)\}/g, (match, name: string) => Object.hasOwn(params, name) ? String(params[name]) : match) : message
}

/** Context-specific built-in category, field and option labels. Stored values stay unchanged. */
export function metadataLabel(source: string, fallback: typeof t = t): string {
  if (language === 'de') return source
  const labels: Record<string, string> = partMetadata
  return Object.hasOwn(labels, source) ? labels[source] : fallback(source)
}

/** For event handlers and non-React helpers; translate at display time. */
export function t(source: string, params?: TranslationParams): string {
  return translate(source, language, params)
}

// Older jobs and backend diagnostics contain rendered German messages. Localize
// those only at the display boundary; parsers and stored data keep their originals.
const messageTemplates = Object.entries(englishMessages)
  .filter(([source]) => /\{(?:\d+|value\d+)\}/.test(source))
  .map(([source, english]) => {
    const names: string[] = []
    const chunks = source.split(/(\{(?:\d+|value\d+)\})/g)
    const literalLength = chunks.filter((chunk) => !/^\{(?:\d+|value\d+)\}$/.test(chunk)).join('').length
    const pattern = chunks.map((chunk) => {
      if (/^\{(?:\d+|value\d+)\}$/.test(chunk)) { names.push(chunk.slice(1, -1)); return '([\\s\\S]*?)' }
      return chunk.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    }).join('')
    return { pattern: new RegExp(`^${pattern}$`), names, english, literalLength }
  })
  .filter(({ names, literalLength }) => names.length <= 8 && literalLength >= 12)
  .sort((a, b) => b.literalLength - a.literalLength)
const messageCache = new Map<string, string>()

export function localizeMessage(source: string): string {
  if (language === 'de' || !source) return source
  if (Object.hasOwn(englishMessages, source)) return englishMessages[source]
  const cached = messageCache.get(source)
  if (cached !== undefined) return cached
  let result = source
  if (source.length <= 16_000) {
    for (const { pattern, names, english } of messageTemplates) {
      const match = pattern.exec(source)
      if (!match) continue
      const values = Object.fromEntries(names.map((name, index) => [name, match[index + 1]]))
      result = english.replace(/\{(\d+|value\d+)\}/g, (placeholder, name: string) => values[name] ?? placeholder)
      break
    }
  }
  if (result === source && source.includes('\n')) result = source.split('\n').map(localizeMessage).join('\n')
  if (messageCache.size >= 1000) messageCache.clear()
  messageCache.set(source, result)
  return result
}

/** A translator whose identity changes with the language, including memo dependencies. */
export function useI18n() {
  const selected = useSyncExternalStore(subscribe, getLanguage, () => 'en' as const)
  return useMemo(() => ({
    language: selected,
    locale: selected === 'de' ? 'de-DE' : 'en-US',
    t: (source: string, params?: TranslationParams) => translate(source, selected, params),
  }), [selected])
}
