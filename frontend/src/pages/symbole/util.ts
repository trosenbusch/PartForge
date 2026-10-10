import { t as tr, getLocale } from '@/components/preview/i18n'
/** Hilfsfunktionen des Symbole-Moduls (ohne Komponenten – Fast Refresh). */
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { GeneratedSpec, IcPin, IcSide, SymbolEntry, SymbolKindInfo, SymbolParamSpec } from '@/api/symbols'
import type { PinOrientation } from '@/lib/geometry'

/** Text in die Zwischenablage (mit Rückmeldung) */
export async function copyText(text: string, what = tr('Name')): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    toast.success(tr("{value0} kopiert", { value0: String(what) }), { id: 'symbole-copy', description: text })
  } catch {
    toast.error(tr('Kopieren nicht möglich'), {
      id: 'symbole-copy',
      description: tr('Die Zwischenablage ist gesperrt. Bitte den Text markieren und mit Strg+C kopieren.'),
    })
  }
}

/** Wert erst nach `delay` ms Ruhe übernehmen (Live-Vorschau beim Tippen) */
export function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

/** Seite eines Pins im erzeugten Symbol (Pins zeigen nach außen: „left“ = linke Körperseite) */
export const SIDE_OF_ORIENTATION: Record<PinOrientation, IcSide> = { left: 'left', right: 'right', up: 'top', down: 'bottom' }

/** Standardwert eines Parameters (Backend-Vorgabe; bei fehlender Vorgabe die erste Option bzw. Minimum) */
export function paramDefault(p: SymbolParamSpec): unknown {
  if (p.default !== null && p.default !== undefined) return p.default
  if (p.kind === 'bool') return false
  if (p.kind === 'int') return p.minimum ?? 0
  if (p.kind === 'enum') return p.options[0] ?? ''
  return ''
}

/** Effektive Parameter eines Symboltyps (Standardwerte + Änderungen) */
export function effectiveParams(kind: SymbolKindInfo, overrides: Record<string, unknown> | undefined): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const p of kind.params) out[p.name] = overrides && p.name in overrides ? overrides[p.name] : paramDefault(p)
  return out
}

/** Gleichheit von Parameterwerten (auch Objekte wie eine eigene Relais-Belegung) */
export function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a === 'object' || typeof b === 'object') return JSON.stringify(a) === JSON.stringify(b)
  return String(a) === String(b)
}

/** Nur vom Standard abweichende Parameter (so bleibt `generator.request` im Spec schlank) */
export function changedParams(kind: SymbolKindInfo, values: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const p of kind.params) {
    const v = values[p.name]
    if (v === undefined) continue
    if (!sameValue(v, paramDefault(p))) out[p.name] = v
  }
  return out
}

/** Weicht ein Parameter vom Standard ab? */
export function isParamModified(kind: SymbolKindInfo, overrides: Record<string, unknown> | undefined): boolean {
  if (!overrides) return false
  return kind.params.some((p) => p.name in overrides && !sameValue(overrides[p.name], paramDefault(p)))
}

/** Pinbelegung aus dem Generator-Protokoll (`generator.pinmap.pins` = Funktion → Pads) als Pad → Funktion */
export function resolvedPinmap(spec: GeneratedSpec | undefined): { pad: string; fn: string }[] | null {
  const gen = spec?.generator as Record<string, unknown> | null | undefined
  const pinmap = gen?.pinmap as { pins?: Record<string, unknown> } | undefined
  if (!pinmap?.pins || typeof pinmap.pins !== 'object') return null
  const out: { pad: string; fn: string }[] = []
  for (const [fn, pads] of Object.entries(pinmap.pins)) {
    if (!Array.isArray(pads)) continue
    for (const pad of pads) out.push({ pad: String(pad), fn })
  }
  return out.sort((a, b) => a.pad.localeCompare(b.pad, getLocale(), { numeric: true }))
}

/** Körpergröße eines IC-Symbols aus dem Generator-Protokoll (mil) */
export function icBodySize(spec: GeneratedSpec | undefined): { width: number; height: number } | null {
  const layout = (spec?.generator as Record<string, unknown> | null | undefined)?.layout as
    | { width?: unknown; height?: unknown }
    | undefined
  const w = Number(layout?.width)
  const h = Number(layout?.height)
  return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0 ? { width: w, height: h } : null
}

/** Gespeicherte Generator-Anfrage eines Specs (`generator.request`), falls vorhanden */
export function generatorRequest(spec: { generator?: unknown } | null | undefined): Record<string, unknown> | null {
  const gen = spec?.generator
  if (!gen || typeof gen !== 'object') return null
  const req = (gen as Record<string, unknown>).request
  if (req && typeof req === 'object') return req as Record<string, unknown>
  const kind = (gen as Record<string, unknown>).kind
  if (typeof kind === 'string') return { kind, params: (gen as Record<string, unknown>).params ?? {} }
  return null
}

/**
 * Eigener Name eines gespeicherten Symbols – für „Neu generieren“ und „Bearbeiten“: `generator.name`, den das Backend
 * beim Speichern nur für eigene Namen vermerkt (`with_name_record`, z. B. „MY_OPAMP“ statt „Op-Amp Dual“). `null` =
 * erzeugter Name, der dem Hausstil folgt. Ältere Specs ohne `generator.default_name` kennen diese Angabe noch nicht –
 * für sie gilt der Name der gespeicherten Anfrage (`generator.request.name`).
 */
export function generatorName(spec: { generator?: unknown } | null | undefined): string | null {
  const gen = spec?.generator
  if (!gen || typeof gen !== 'object') return null
  const g = gen as Record<string, unknown>
  if (typeof g.name === 'string' && g.name.trim()) return g.name
  if (typeof g.default_name === 'string') return null
  const legacy = g.request && typeof g.request === 'object' ? (g.request as Record<string, unknown>).name : null
  return typeof legacy === 'string' && legacy.trim() ? legacy : null
}

/** Zeitstempel des Backends („2026-10-08T02:31:49“) als Millisekunden; ungültig → null */
export function parseUpdated(value: string | null | undefined): number | null {
  if (!value) return null
  const t = Date.parse(value)
  return Number.isFinite(t) ? t : null
}

const NAME_RE = /^[A-Za-z0-9_.\-+() ]{1,64}$/
const PREFIX_RE = /^[A-Za-z][A-Za-z0-9_]{0,9}$/

/** Prüft einen Symbolnamen wie das Backend (ASCII, max. 64 Zeichen); undefined = in Ordnung bzw. leer */
export function symbolNameError(name: string): string | undefined {
  if (!name) return undefined
  if (name !== name.trim()) return tr('Keine Leerzeichen am Anfang oder Ende.')
  if (!NAME_RE.test(name)) return tr('Erlaubt sind A–Z, a–z, 0–9, Leerzeichen und _ . - + ( ) – höchstens 64 Zeichen (keine Umlaute).')
  if (name.startsWith('__PF')) return tr('Das Präfix __PF ist reserviert.')
  return undefined
}

/** Prüft ein Bezeichner-Präfix (z. B. „U“, „FB“); undefined = in Ordnung bzw. leer */
export function prefixError(prefix: string): string | undefined {
  if (!prefix) return undefined
  return PREFIX_RE.test(prefix) ? undefined : tr('Ein Buchstabe, danach Buchstaben, Ziffern oder _ (max. 10).')
}

export const SOURCE_LABEL: Record<string, string> = {
  generated: 'Generator',
  datasheet: 'Datenblatt',
  imported: 'Importiert',
  external: 'Extern',
  altium: 'In Altium bearbeitet',
}

export const STATUS_LABEL: Record<string, { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }> = {
  ok: { label: 'Aktuell', tone: 'success' },
  pending: { label: 'Ausstehend', tone: 'warning' },
  missing: { label: 'Datei fehlt', tone: 'danger' },
  error: { label: 'Fehler', tone: 'danger' },
}

// --------------------------------------------------------------------------- Steckverbinder

export interface ConnectorLayout {
  rows: 1 | 2
  /** Pin-Nummern je Reihe des Symbols: [links, rechts] (rechts leer bei einreihigen Steckverbindern) */
  pairs: [string, string][]
}

/**
 * Pin-Nummern eines Steckverbinders wie im Generator (`_connector_designators`): einreihig 1…N, zweireihig
 * „odd_even“ (1-2 / 3-4 …), „row“ (1…N links, N+1…2N rechts) oder „dip“ (gegen den Uhrzeigersinn).
 * null = Parameter ungültig (z. B. ungerade Polzahl auf 2 Reihen).
 */
export function connectorLayout(values: Record<string, unknown>): ConnectorLayout | null {
  const pins = Number(values.pins)
  const rows = Number(values.rows)
  const numbering = String(values.numbering ?? 'odd_even')
  if (!Number.isInteger(pins) || pins < 1 || pins > 200) return null
  if (rows === 1) return { rows: 1, pairs: Array.from({ length: pins }, (_, i) => [String(i + 1), ''] as [string, string]) }
  if (rows !== 2 || pins % 2 || pins < 2) return null
  const n = pins / 2
  const pairs: [string, string][] = []
  for (let k = 0; k < n; k += 1) {
    if (numbering === 'row') pairs.push([String(k + 1), String(n + k + 1)])
    else if (numbering === 'dip') pairs.push([String(k + 1), String(2 * n - k)])
    else pairs.push([String(2 * k + 1), String(2 * k + 2)])
  }
  return { rows: 2, pairs }
}

/** Eigene Pinnamen eines Steckverbinders für die Anfrage: nur vorhandene Pins mit Namen */
export function connectorRequestPins(values: Record<string, unknown>, pins: readonly IcPin[] | undefined): IcPin[] {
  const layout = connectorLayout(values)
  if (!layout || !pins?.length) return []
  const valid = new Set(layout.pairs.flat().filter(Boolean))
  return pins
    .filter((p) => valid.has(p.designator) && p.name.trim())
    .map((p) => ({ designator: p.designator, name: p.name.trim(), electrical: 'passive', part: 1, hidden: false }))
}

// --------------------------------------------------------------------------- Namen

/** Freien Namen vorschlagen: „Name 2“, „Name 3“ … (max. 64 Zeichen) */
export function suggestFreeName(base: string, entries: readonly SymbolEntry[] | undefined): string {
  const taken = new Set((entries ?? []).map((e) => e.name.toLowerCase()))
  const stem = base.replace(/\s+\d+$/, '').trim() || tr('Symbol')
  for (let i = 2; i < 1000; i += 1) {
    const candidate = `${stem.slice(0, 60)} ${i}`
    if (!taken.has(candidate.toLowerCase())) return candidate
  }
  return stem
}
