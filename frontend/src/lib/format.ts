/** Formatierungs-Helfer (deutsch). */

const nf = new Intl.NumberFormat('de-DE')
const nf1 = new Intl.NumberFormat('de-DE', { maximumFractionDigits: 1 })
const pf = new Intl.NumberFormat('de-DE', { style: 'percent', maximumFractionDigits: 0 })
const rtf = new Intl.RelativeTimeFormat('de-DE', { numeric: 'auto', style: 'short' })
const dtf = new Intl.DateTimeFormat('de-DE', { dateStyle: 'medium', timeStyle: 'short' })
const tf = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' })

const fixedFormats = new Map<number, Intl.NumberFormat>()

/** 1234 → „1.234“; mit `fractionDigits` feste Nachkommastellen (Formatierer werden zwischengespeichert). */
export function formatNumber(value: number, fractionDigits?: number): string {
  if (!Number.isFinite(value)) return '–'
  if (fractionDigits === undefined) return nf.format(value)
  let f = fixedFormats.get(fractionDigits)
  if (!f) {
    f = new Intl.NumberFormat('de-DE', { minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits })
    fixedFormats.set(fractionDigits, f)
  }
  return f.format(value)
}

const maxFormats = new Map<number, Intl.NumberFormat>()

/** Höchstens `maxDigits` Nachkommastellen, ohne überflüssige Nullen: 2.5 → „2,5“, 2 → „2“. */
export function formatDecimal(value: number, maxDigits = 2): string {
  if (!Number.isFinite(value)) return '–'
  let f = maxFormats.get(maxDigits)
  if (!f) {
    f = new Intl.NumberFormat('de-DE', { maximumFractionDigits: maxDigits })
    maxFormats.set(maxDigits, f)
  }
  return f.format(value)
}

/**
 * Deutsche Zahleneingabe lesen: „2,5“, „2.5“, „1.234,5“, „-0,1“ → Zahl; ungültig → null.
 * Enthält der Text ein Komma, sind Punkte Tausendertrenner, sonst ist der Punkt das Dezimalzeichen.
 */
export function parseDecimal(text: string): number | null {
  let t = text.trim().replace(/\s+/g, '').replace(/[−–]/g, '-')
  if (!t) return null
  if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.')
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
const COUNT_AFTER_OF = /(\bvon\s+)(\d{4,9})(?=$|\s|[…).,;:!?](?!\d))/gu

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
    digits.startsWith('0') || (digits.length === 4 && PACKAGE_CODES.has(digits)) ? all : pre + nf.format(Number(digits))
  return text.replace(COUNT_IN_TEXT, group).replace(COUNT_AFTER_OF, group)
}

/** 12 300 → „12,3 Tsd.“ – kompakt für Kennzahlen */
export function formatCompact(value: number): string {
  if (Math.abs(value) < 10_000) return nf.format(value)
  if (Math.abs(value) < 1_000_000) return `${nf1.format(value / 1000)} Tsd.`
  return `${nf1.format(value / 1_000_000)} Mio.`
}

/** 0.42 → „42 %“ */
export function formatPercent(fraction: number): string {
  return pf.format(fraction)
}

/** Zeitstempel (Sekunden oder Millisekunden seit Epoche bzw. ISO-String) → „vor 3 Min.“ */
export function formatRelativeTime(value: number | string | Date, now = Date.now()): string {
  const ms = toMillis(value)
  const diff = (ms - now) / 1000
  const abs = Math.abs(diff)
  if (abs < 45) return 'gerade eben'
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour')
  if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day')
  return dtf.format(new Date(ms))
}

export function formatDateTime(value: number | string | Date): string {
  return dtf.format(new Date(toMillis(value)))
}

export function formatClock(value: number | string | Date): string {
  return tf.format(new Date(toMillis(value)))
}

/** Dauer in Sekunden → „1:05 min“ bzw. „12 s“ */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '–'
  if (seconds < 60) return `${nf1.format(seconds)} s`
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
  if (h < 5) return 'Gute Nacht'
  if (h < 11) return 'Guten Morgen'
  if (h < 18) return 'Guten Tag'
  return 'Guten Abend'
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
export function plural(count: number, one: string, many: string): string {
  return `${formatNumber(count)} ${count === 1 ? one : many}`
}

/** Bytes → „1,2 MB“ */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${nf1.format(bytes / 1024)} KB`
  return `${nf1.format(bytes / (1024 * 1024))} MB`
}
