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
    // „{0}“ marks user data (names, files); an unquoted value may be fixed wording of the backend
    const quoted = new Set<string>()
    const chunks = source.split(/(\{(?:\d+|value\d+)\})/g)
    const literalLength = chunks.filter((chunk) => !/^\{(?:\d+|value\d+)\}$/.test(chunk)).join('').length
    const pattern = chunks.map((chunk, index) => {
      if (/^\{(?:\d+|value\d+)\}$/.test(chunk)) {
        const name = chunk.slice(1, -1)
        names.push(name)
        if (/[„“"'‚‘«»]$/.test(chunks[index - 1] ?? '')) quoted.add(name)
        return '([\\s\\S]*?)'
      }
      return chunk.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    }).join('')
    // placeholders before the first literal text („{0}{1} geschrieben.“)
    const firstLiteral = chunks.findIndex((chunk) => chunk !== '' && !/^\{(?:\d+|value\d+)\}$/.test(chunk))
    const leading = chunks.slice(0, firstLiteral < 0 ? chunks.length : firstLiteral).filter((chunk) => chunk.startsWith('{')).map((chunk) => chunk.slice(1, -1))
    return { pattern: new RegExp(`^${pattern}$`), names, quoted, leading, english, literalLength, short: literalLength < 12 }
  })
  // a short template („Gehäuse {0}“, „{0} läuft.“) only applies to names and numbers, see localizeTemplate
  .filter(({ names, literalLength }) => names.length <= 8 && literalLength >= 5)
  .sort((a, b) => b.literalLength - a.literalLength)
const messageCache = new Map<string, string>()
const GERMAN_FUNCTION_WORDS = /(^|[^\p{L}])(und|oder|nicht|nichts|der|die|das|den|dem|des|ist|sind|wird|werden|wurde|kein|keine|mit|für|von|davon|bei|nach|ohne|auf|zum|zur)(?!\p{L})/iu
const WORDS = /\p{L}{4,}/gu
let germanWords: Set<string> | undefined
/** German text, not a name, number or path: German function words or words that only the German sources use */
function looksGerman(text: string): boolean {
  if (GERMAN_FUNCTION_WORDS.test(text)) return true
  if (!germanWords) {
    const words = (s: string) => s.toLowerCase().match(WORDS) ?? []
    const english = new Set(Object.values(englishMessages).flatMap(words))
    germanWords = new Set(Object.keys(englishMessages).flatMap(words).filter((word) => !english.has(word)))
  }
  return (text.toLowerCase().match(WORDS) ?? []).some((word) => germanWords!.has(word))
}

function localizeTemplate(source: string): string {
  for (const { pattern, names, quoted, leading, short, english } of messageTemplates) {
    const match = pattern.exec(source)
    if (!match) continue
    const values = Object.fromEntries(names.map((name, index) => [name, match[index + 1]]))
    // An unquoted value may be the backend's own wording or a whole message („Kontrolle der {0} …“ with
    // „Gehäusezeichnungen“); quoted values („{0}“) are names and stay verbatim.
    // (values are shorter than the message, so this recursion ends)
    const localized = Object.fromEntries(names.map((name) => [name, quoted.has(name) ? values[name] : localizeMessage(values[name])]))
    // „{0} wurde nicht gefunden.“ must not swallow „Die STEP-Datei“: a German subject needs its own entry
    if (looksGerman(leading.filter((name) => !quoted.has(name)).map((name) => localized[name]).join(''))) continue
    // „Gehäuse {0}“ translates „Gehäuse SOT-23“, but must not swallow „Gehäuse fehlt in der Zeichnung“
    if (short && names.some((name) => !quoted.has(name) && looksGerman(localized[name]))) continue
    return singularAfterOne(english.replace(/\{(\d+|value\d+)\}/g, (placeholder, name: string) => localized[name] ?? placeholder))
  }
  return source
}

/** English plural nouns of the catalogs and their singular, for „{0} Fehler“ → „{0} errors“ with the count 1 */
const SINGULAR: Readonly<Record<string, string>> = {
  errors: 'error', warnings: 'warning', notes: 'note', notices: 'notice', parts: 'part', files: 'file',
  packages: 'package', pins: 'pin', pads: 'pad', symbols: 'symbol', footprints: 'footprint', entries: 'entry',
  values: 'value', rows: 'row', fields: 'field', categories: 'category', libraries: 'library', matches: 'match',
  items: 'item', pages: 'page', sizes: 'size', templates: 'template', layers: 'layer', models: 'model',
  bodies: 'body', conflicts: 'conflict', problems: 'problem', requests: 'request', links: 'link', results: 'result',
  parameters: 'parameter', lines: 'line', tables: 'table', series: 'series', components: 'component',
}

function singularAfterOne(text: string): string {
  return text.replace(/(^|[\s(])1 (\p{Ll}+)\b/gu, (match, before: string, word: string) =>
    Object.hasOwn(SINGULAR, word) ? `${before}1 ${SINGULAR[word]}` : match)
}

/** German nouns whose plural equals the singular: the catalog cannot tell „1 Gehäuse“ from „3 Gehäuse“ */
const SAME_PLURAL: Readonly<Record<string, readonly [string, string]>> = {
  Gehäuse: ['package', 'packages'], Fehler: ['error', 'errors'], Parameter: ['parameter', 'parameters'], Treffer: ['match', 'matches'],
}

/** A count from the backend's plural(): „12 Bauteile“ → „12 parts“ (English nouns are lowercase after a number) */
function localizeCount(source: string): string {
  const count = /^(\s*[\d.,]+\s+)(\p{L}[\p{L}-]*(?: \p{L}[\p{L}-]*)?)(\s*)$/u.exec(source)
  if (!count) return source
  const [, number, noun, tail] = count
  if (Object.hasOwn(SAME_PLURAL, noun)) return number + SAME_PLURAL[noun][/^\s*1\s+$/.test(number) ? 0 : 1] + tail
  if (!Object.hasOwn(englishMessages, noun)) return source
  const english = englishMessages[noun]
  const lower = /^[A-Z][a-z]+(\s|$)/.test(english) && !/^(Altium|Claude|PartForge)\b/.test(english) ? english[0].toLowerCase() + english.slice(1) : english
  return number + lower + tail
}

/** Live progress counts: „2 Bauteile, 14 Bestellnummern, 30 Pins“ (only when every item is a count) */
function localizeCountList(source: string): string {
  const items = source.split(', ')
  if (items.length < 2) return source
  const localized = items.map(localizeCount)
  return localized.every((item, index) => item !== items[index]) ? localized.join(', ') : source
}

/** Exact entry, count or template, without splitting the text (inserted values) */
function localizeExact(source: string): string {
  const key = source.trim()
  if (key.length >= 4 && Object.hasOwn(englishMessages, key)) return source.replace(key, englishMessages[key])
  const counted = localizeCountList(localizeCount(source))
  if (counted !== source) return counted
  return source.length <= 16_000 ? localizeTemplate(source) : source
}

/**
 * Messages the backend assembles from known parts: „<name>: <message>“ (the name stays, a known label such as
 * „Bestätigt“ is translated), and sentences or clauses joined with „ – “ / „; “. Each known part is translated;
 * unknown parts stay as they are.
 */
function localizeParts(source: string): string {
  // clauses first, so that each one keeps its own prefix („Abgebrochen – R-1: …; R-2: …“)
  const parts = source.split(/((?<=[.!?…])\s+(?=[A-ZÄÖÜ„"(])|;\s+|\s+–\s+)/)
  if (parts.length >= 3) {
    let changed = false
    const out = parts.map((part, index) => {
      if (index % 2) return part
      const localized = localizeMessage(part)
      if (localized !== part) changed = true
      return localized
    })
    if (changed) return out.join('')
  }
  const prefixed = /^(.{1,200}?): (.+)$/.exec(source)
  if (prefixed) {
    const label = localizeExact(prefixed[1])
    const rest = localizeMessage(prefixed[2])
    if (rest !== prefixed[2] || label !== prefixed[1]) return `${label}: ${rest}`
  }
  return source
}

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
  } else if (/^(\s*[•·–-]\s+)(.+)$/.test(source)) {
    // list items of a multi-line message („• Footprint X: …“)
    const [, bullet, item] = /^(\s*[•·–-]\s+)(.+)$/.exec(source)!
    result = bullet + localizeMessage(item)
  } else if (source.length <= 16_000) {
    // counts first: „1 Gehäuse“ must not become „1 packages“ through the template „{0} Gehäuse“
    result = localizeCountList(localizeCount(source))
    if (result === source) result = localizeTemplate(source)
    if (result === source) result = localizeParts(source)
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
