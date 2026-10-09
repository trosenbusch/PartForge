/** Formatierung und Sortierung für Tabellenzellen (deutsch, technische Werte). */
import { parseEngineering } from '@/lib/units'
import type { BadgeVariantProps } from '@/components/ui'

/**
 * Kanonischen Werttext des Backends lesbar machen: Dezimalkomma, geschütztes schmales Leerzeichen vor der Einheit,
 * echtes Minuszeichen. „10kΩ“ → „10 kΩ“, „0.1W“ → „0,1 W“, „±1%“ → „±1 %“, „-55°C … 155°C“ → „−55 °C … 155 °C“.
 */
export function formatQuantityText(text: string): string {
  return text.replace(/([+\-−±]?)(\d+(?:[.,]\d+)?)(\s*)([A-Za-zµμΩ°%‰][A-Za-z0-9µμΩ°%‰/·²³]*)?/g, (_m, sign, num, _sp, unit) => {
    const s = sign === '-' ? '−' : sign
    const n = String(num).replace('.', ',')
    return unit ? `${s}${n} ${unit}` : `${s}${n}`
  })
}

/** Zahl hinter einem technischen Wert (für Sortierung), sonst null */
export function quantityValue(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string') return null
  const t = value.trim().replace(/^±/, '').split(/\s*(?:…|\.\.\.|bis| to )\s*/)[0]
  // Einheit am Ende entfernen, die parseEngineering nicht kennt (z. B. „ppm/K“, „°C“, „mm“)
  const direct = parseEngineering(t)
  if (direct !== null) return direct
  const m = t.match(/^([+\-−]?\d+(?:[.,]\d+)?)\s*([pnuµμmkKMGT]?)/)
  if (!m) return null
  return parseEngineering(`${m[1].replace('−', '-')}${m[2]}`)
}

/** Vergleichsfunktion für Spalten mit technischen Werten (leere Werte zuletzt) */
export function quantityComparator(a: unknown, b: unknown): number {
  const x = quantityValue(a)
  const y = quantityValue(b)
  if (x === null && y === null) return String(a ?? '').localeCompare(String(b ?? ''), 'de')
  if (x === null) return 1
  if (y === null) return -1
  return x - y
}

export type StatusTone = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'spark'

/** Bekannte Statuswerte (Lebenszyklus, Synchronisation, Import) → Ton */
export const STATUS_TONES: Record<string, StatusTone> = {
  aktiv: 'success',
  active: 'success',
  freigegeben: 'success',
  'in produktion': 'success',
  synchron: 'success',
  ok: 'success',
  geprüft: 'success',
  fertig: 'success',
  neu: 'info',
  new: 'info',
  entwurf: 'neutral',
  vorhanden: 'neutral',
  unbekannt: 'neutral',
  ausstehend: 'warning',
  veraltet: 'warning',
  prüfen: 'warning',
  nrnd: 'warning',
  'nicht für neue designs': 'warning',
  'letzte bestellung': 'warning',
  warnung: 'warning',
  abgekündigt: 'danger',
  obsolet: 'danger',
  obsolete: 'danger',
  eol: 'danger',
  fehler: 'danger',
  konflikt: 'danger',
  ki: 'spark',
}

export const statusTone = (value: string, custom?: Record<string, StatusTone>): StatusTone =>
  custom?.[value] ?? custom?.[value.toLowerCase()] ?? STATUS_TONES[value.toLowerCase()] ?? 'neutral'

export type BadgeVariant = NonNullable<BadgeVariantProps['variant']>

/** Werte einer Aufzählung (Komma-/Semikolon-getrennt) */
export function splitEnum(value: unknown): string[] {
  if (value === null || value === undefined || value === '') return []
  if (Array.isArray(value)) return value.map(String)
  return String(value)
    .split(/\s*[;,]\s*/)
    .filter(Boolean)
}

/** Anzeigetext für URL-Zellen: Host + Pfadanfang */
export function linkLabel(url: string): string {
  try {
    const u = new URL(url)
    const path = u.pathname.length > 1 ? u.pathname.split('/').filter(Boolean).slice(-1)[0] : ''
    return path ? `${u.hostname.replace(/^www\./, '')} › ${decodeURIComponent(path)}` : u.hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export const isUrl = (value: string): boolean => /^https?:\/\//i.test(value.trim())
