/** Formatierungs-Helfer für die eingestellte Sprache. */

import { getLocale, t as tr } from './i18n'

const cachedFormats = new Map<string, ReturnType<typeof makeFormats>>()
function makeFormats(locale: string) {
  return {
    nf: new Intl.NumberFormat(locale),
    nf1: new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    pf: new Intl.NumberFormat(locale, { style: 'percent', maximumFractionDigits: 0 }),
    rtf: new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style: 'short' }),
    dtf: new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }),
    tf: new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    compact: new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }),
  }
}
function formats() {
  const locale = getLocale()
  let value = cachedFormats.get(locale)
  if (!value) { value = makeFormats(locale); cachedFormats.set(locale, value) }
  return value
}

const fixedFormats = new Map<string, Intl.NumberFormat>()

/** 1234 → „1.234“; mit `fractionDigits` feste Nachkommastellen (Formatierer werden zwischengespeichert). */
export function formatNumber(value: number, fractionDigits?: number): string {
  if (!Number.isFinite(value)) return '–'
  if (fractionDigits === undefined) return formats().nf.format(value)
  let f = fixedFormats.get(`${getLocale()}:${fractionDigits}`)
  if (!f) {
    f = new Intl.NumberFormat(getLocale(), { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits })
    fixedFormats.set(`${getLocale()}:${fractionDigits}`, f)
  }
  return f.format(value)
}

const maxFormats = new Map<string, Intl.NumberFormat>()

/** Höchstens `maxDigits` Nachkommastellen, ohne überflüssige Nullen: 2.5 → „2,5“, 2 → „2“. */
export function formatDecimal(value: number, maxDigits = 2): string {
  if (!Number.isFinite(value)) return '–'
  let f = maxFormats.get(`${getLocale()}:${maxDigits}`)
  if (!f) {
    f = new Intl.NumberFormat(getLocale(), { maximumFractionDigits: maxDigits })
    maxFormats.set(`${getLocale()}:${maxDigits}`, f)
  }
  return f.format(value)
}

/**
 * Zahleneingaben lesen: „2,5“, „2.5“, „1.234,5“, „-0,1“ → Zahl; ungültig → null.
 * Englisch erlaubt zusätzlich gruppierte Zahlen wie „1,234.5“; technische Punkt-Dezimalwerte bleiben gültig.
 */
export function parseDecimal(text: string): number | null {
  let t = text.trim().replace(/\s+/g, '').replace(/[−–]/g, '-')
  if (!t) return null
  if (t.includes(',')) {
    if (getLocale() === 'en-US' && /^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(t)) t = t.replace(/,/g, '')
    else t = t.replace(/\./g, '').replace(',', '.')
  }
  if (!/^[-+]?(\d+\.?\d*|\.\d+)(e[-+]?\d+)?$/i.test(t)) return null
  const n = Number(t)
  return Number.isFinite(n) ? n : null
}

/** EIA-Bauformen (Zoll und metrisch): vierstellige Codes, keine Mengen – bleiben in Texten ungruppiert */
const PACKAGE_CODES = new Set([
  '0201', '0402', '0603', '0805', '1206', '1210', '1806', '1808', '1812', '1825', '2010', '2220', '2225', '2512',
  '2920', '1005', '1608', '2012', '3216', '3225', '4532', '4564', '5025', '6332',
])

/** Alleinstehende ganze Zahl (4–9 Stellen) vor einem Wort: „6212 Bauteile“, „von 12000 Zeilen“ */
const COUNT_IN_TEXT = /(^|[\s(„"«»])(\d{4,9})(?=\s+\p{L})/gu
/** Gesamtzahl nach „von“ am Ende einer Meldung: „Zeile 4801 von 6314 …“, „(12 von 1500)“ */
const COUNT_AFTER_OF = /(\b(?:von|of)\s+)(\d{4,9})(?=$|\s|[…).,;:!?](?!\d))/gu

/**
 * Mengen in Fließtext (Job-Meldungen, Toasts) deutsch gruppieren: „6212 Bauteile exportiert“ → „6.212 Bauteile
 * exportiert“, „500 von 12000 Zeilen“ → „500 von 12.000 Zeilen“. Nur alleinstehende ganze Zahlen vor einem Wort –
 * Teilenummern (`CRCW060310K0`), Bauformen (`0603`, `1206`), Pfade, Uhrzeiten, Datums-, Dezimal- und schon
 * gruppierte Zahlen bleiben unverändert (idempotent). Vierstellige Zahlen dürfen nach DIN 5008 ungruppiert bleiben –
 * im Zweifel wird nichts geändert.
 */
export function formatNumbersInText(text: string): string {
  if (!text || !/\d{4}/.test(text)) return text
  const group = (all: string, pre: string, digits: string) =>
    digits.startsWith('0') || (digits.length === 4 && PACKAGE_CODES.has(digits)) ? all : pre + formats().nf.format(Number(digits))
  return text.replace(COUNT_IN_TEXT, group).replace(COUNT_AFTER_OF, group)
}

/** 12 300 → „12,3 Tsd.“ – kompakt für Kennzahlen */
export function formatCompact(value: number): string {
  if (Math.abs(value) < 10_000) return formats().nf.format(value)
  return formats().compact.format(value)
}

/** 0.42 → „42 %“ */
export function formatPercent(fraction: number): string {
  return formats().pf.format(fraction)
}

/** Zeitstempel (Sekunden oder Millisekunden seit Epoche bzw. ISO-String) → „vor 3 Min.“ */
export function formatRelativeTime(value: number | string | Date, now = Date.now()): string {
  const ms = toMillis(value)
  const diff = (ms - now) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return tr('gerade eben')
  if (abs < 3600) return formats().rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return formats().rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return formats().rtf.format(Math.round(diff / 86400), 'day')
  return formats().dtf.format(new Date(ms))
}

export function formatDateTime(value: number | string | Date): string {
  return formats().dtf.format(new Date(toMillis(value)))
}

export function formatClock(value: number | string | Date): string {
  return formats().tf.format(new Date(toMillis(value)))
}

/** Dauer in Sekunden → „1:05 min“ bzw. „12 s“ */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '–'
  if (seconds < 60) return `${formats().nf1.format(seconds)} s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}:${String(s).padStart(2, '0')} min`
  const h = Math.floor(m / 60)
  return `${h}:${String(m % 60).padStart(2, '0')} h`
}

/** Sekunden (Python time.time()) und Millisekunden gleichermaßen akzeptieren. */
export function toMillis(value: number | string | Date): number {
  if (value instanceof Date) return value.getTime()
  if (typeof value === 'string') return new Date(value).getTime()
  return value < 1e12 ? value * 1000 : value
}

/** Langer Windows-Pfad → „C:\PartForge-Examples\…\PartForge“ (Mitte gekürzt) */
export function shortenPath(path: string, max = 42): string {
  if (path.length <= max) return path
  const sep = path.includes('\\') ? '\\' : '/'
  const parts = path.split(sep)
  if (parts.length <= 3) return `${path.slice(0, max / 2 - 1)}…${path.slice(-(max / 2))}`
  const head = parts[0]
  let tail = parts[parts.length - 1]
  for (let i = parts.length - 2; i > 0; i--) {
    const candidate = `${parts[i]}${sep}${tail}`
    if (head.length + candidate.length + 3 > max) break
    tail = candidate
  }
  return `${head}${sep}…${sep}${tail}`
}

/** Letztes Pfadsegment */
export function baseName(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean)
  return parts[parts.length - 1] ?? path
}

/** Tageszeitabhängige Begrüßung */
export function greeting(date = new Date()): string {
  const h = date.getHours()
  if (h < 5) return tr('Gute Nacht')
  if (h < 11) return tr('Guten Morgen')
  if (h < 18) return tr('Guten Tag')
  return tr('Guten Abend')
}

/** Ordnernamen-taugliche Variante eines Bibliotheksnamens */
export function toFolderName(name: string): string {
  const cleaned = name
    .trim()
    .replace(/[<>:"/\\|?*]+/g, '')
    .replace(/\s+/g, '_')
  return cleaned || 'PartForge'
}

const PLAIN_NUMBER = new Intl.NumberFormat('en-US', { useGrouping: false, maximumSignificantDigits: 15 })

/**
 * Zahl als einfache Dezimalzahl mit Punkt, **nie** in Exponentialschreibweise – für Attribute wie `aria-valuenow`
 * („1e-12“ ist kein gültiger Wert; 1 pF = „0.000000000001“). Kleinste Beträge unter 1e-18 werden „0“.
 */
export function plainNumber(value: number): string {
  if (!Number.isFinite(value)) return '0'
  if (value !== 0 && Math.abs(value) < 1e-18) return '0'
  return PLAIN_NUMBER.format(value)
}

/** Singular/Plural: plural(3, 'Bauteil', 'Bauteile') → „3 Bauteile“ */
export function pluralLabel(count: number, one: string, many: string): string {
  const label = tr(count === 1 ? one : many)
  const invariant: Record<string, [string, string]> = {
    Fehler: ['Error', 'Errors'], Error: ['Error', 'Errors'],
    Gehäuse: ['Package', 'Packages'], Package: ['Package', 'Packages'],
    Parameter: ['Parameter', 'Parameters'], Parameters: ['Parameter', 'Parameters'],
  }
  const forms = getLocale() === 'en-US' && one === many ? invariant[one] : undefined
  return forms ? forms[count === 1 ? 0 : 1] : label
}

/** A localized count and noun, preserving the source language's plural forms. */
export function plural(count: number, one: string, many: string): string {
  return `${formatNumber(count)} ${pluralLabel(count, one, many)}`
}

/** Bytes → „1,2 MB“ */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${formats().nf1.format(bytes / 1024)} KB`
  return `${formats().nf1.format(bytes / (1024 * 1024))} MB`
}
