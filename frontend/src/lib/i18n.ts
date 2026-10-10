import { useMemo, useSyncExternalStore } from 'react'
import { readPref, writePref } from './prefs'
import partMetadata from '../i18n/catalogs/parts-metadata'
import contextMessages, { type TranslationContext } from '../i18n/contexts'

export type Language = 'en' | 'de'
export type TranslationParams = Record<string, string | number>
export type { TranslationContext }
export const LANGUAGES = [{ value: 'en', label: 'English' }, { value: 'de', label: 'Deutsch' }] as const

/**
 * Catalogs with their own translator (`@/components/preview/i18n`, {@link metadataLabel}). Their domain
 * terms (Sicherung = fuse, Seite = pin side) must not replace general wording, so they rank lowest.
 * All other catalogs share one namespace and must agree; a source that needs another English
 * wording somewhere uses {@link tc}.
 */
export const CONTEXT_CATALOGS: ReadonlySet<string> = new Set(['geometry', 'parts-metadata'])

// Source messages are German; catalogs supply English. Keeping interpolation in the
// translator ensures names, paths and other user data are never translated.
const modules = import.meta.glob<{ default: Record<string, string> }>('../i18n/catalogs/*.ts', { eager: true })
const isContextCatalog = (path: string) => CONTEXT_CATALOGS.has(path.replace(/^.*\/|\.ts$/g, ''))
export const englishMessages: Readonly<Record<string, string>> = Object.assign(
  Object.create(null),
  ...Object.entries(modules)
    .sort(([a], [b]) => Number(isContextCatalog(b)) - Number(isContextCatalog(a)))
    .map(([, m]) => m.default),
)

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

function interpolate(message: string, params?: TranslationParams): string {
  return params ? message.replace(/\{(\w+)\}/g, (match, name: string) => Object.hasOwn(params, name) ? String(params[name]) : match) : message
}

export function translate(source: string, selected: Language, params?: TranslationParams): string {
  return interpolate(selected === 'de' ? source : (englishMessages[source] ?? source), params)
}

/** {@link translate} for a source whose English depends on its use (see `i18n/contexts.ts`). */
export function translateContext(context: TranslationContext, source: string, selected: Language, params?: TranslationParams): string {
  const messages: Readonly<Record<string, string>> = contextMessages[context]
  return selected === 'en' && Object.hasOwn(messages, source)
    ? interpolate(messages[source], params)
    : translate(source, selected, params)
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

/** Like gettext's msgctxt: `tc('author', 'von')` is "by", while `t('von')` stays "of". */
export function tc(context: TranslationContext, source: string, params?: TranslationParams): string {
  return translateContext(context, source, language, params)
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
  if (source.includes('\n')) {
    // Line by line: a template's placeholder also matches line breaks and would swallow the following lines
    // ("Aus Altium übernommen: {0}." over a whole two-line job message). No catalog template spans lines.
    result = source.split('\n').map(localizeMessage).join('\n')
  } else if (source.length <= 16_000) {
    for (const { pattern, names, english } of messageTemplates) {
      const match = pattern.exec(source)
      if (!match) continue
      const values = Object.fromEntries(names.map((name, index) => [name, match[index + 1]]))
      result = english.replace(/\{(\d+|value\d+)\}/g, (placeholder, name: string) => values[name] ?? placeholder)
      break
    }
  }
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
    tc: (context: TranslationContext, source: string, params?: TranslationParams) => translateContext(context, source, selected, params),
  }), [selected])
}
