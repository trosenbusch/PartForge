/**
 * Helfer rund um Gehäusefamilien und Vorlagen: Suche (wortweise, normalisiert wie im Backend), bevorzugte Vorlage,
 * Facetten (Bauart/Gehäusetyp), passende Vorlage zu Selektorwerten (wie `best_preset` im Backend), Kurzinfos und
 * Schrittweite der Pinzahl.
 */
import type { FootprintFamily, FootprintPreset } from '@/api/footprints'
import {
  changedParams,
  effectiveTol,
  formatDim,
  formatPlain,
  isTolValue,
  normalizeParam,
  normalizeParams,
  SELECTOR_PARAMS,
  STRONG_SELECTORS,
  type ParamValues,
} from './params'

/** Wie `_norm` im Backend: Kleinbuchstaben, nur Buchstaben/Ziffern („SOT-23-5“ → „sot235“) */
export const normalizeTerm = (text: string): string =>
  text
    .toLowerCase()
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .replace(/[^a-z0-9]/g, '')

/** Weitere Namen, die auf die Familie auflösen (`FamilyInfo.aliases` vom Backend, z. B. „lfcsp“ → nolead) */
export function familyAliases(f: FootprintFamily): readonly string[] {
  return f.aliases ?? []
}

/** Familie, deren Schlüssel oder Alias genau dem Suchbegriff entspricht („LFCSP“ → nolead); Schlüssel gewinnen */
export function aliasFamily(families: readonly FootprintFamily[], query: string): FootprintFamily | null {
  const q = normalizeTerm(query)
  if (!q) return null
  return (
    families.find((f) => normalizeTerm(f.key) === q) ??
    families.find((f) => familyAliases(f).some((a) => normalizeTerm(a) === q)) ??
    null
  )
}

/** Unterstützt die Familie eine Herstellerempfehlung (Land Pattern)? (`FamilyInfo.supports_land_pattern`, per Probe bestimmt) */
export function supportsLandPattern(f: FootprintFamily): boolean {
  return f.supports_land_pattern
}

/** Reihenfolge der Gruppen in der Auswahl (unbekannte Gruppen hinten in Backend-Reihenfolge) */
export const GROUP_ORDER = [
  'Chip-Bauteile',
  'Dioden',
  'Transistoren (SOT/TO)',
  'ICs (Gull-Wing)',
  'ICs (No-Lead)',
  'ICs (BGA)',
  'Bedrahtet',
]

export function groupFamilies(families: readonly FootprintFamily[]): { group: string; families: FootprintFamily[] }[] {
  const map = new Map<string, FootprintFamily[]>()
  for (const f of families) {
    const list = map.get(f.group)
    if (list) list.push(f)
    else map.set(f.group, [f])
  }
  const rank = (g: string) => {
    const i = GROUP_ORDER.indexOf(g)
    return i < 0 ? 100 : i
  }
  return [...map.entries()].sort((a, b) => rank(a[0]) - rank(b[0])).map(([group, list]) => ({ group, families: list }))
}

/** Kurzname der Familie für Kopfzeilen („SOIC / SSOP / …“ bleibt, Klammerzusätze entfallen) */
export const familyShortLabel = (f: FootprintFamily): string => f.label.replace(/\s*\([^)]*\)\s*$/, '')

/** Vorlage, mit der eine Familie startet (Chip-Bauteile: 0603 statt 01005) */
export function preferredPreset(f: FootprintFamily): FootprintPreset | null {
  if (!f.presets.length) return null
  return f.presets.find((p) => /(^|-)0603$/.test(p.key)) ?? f.presets[0]
}

/** Vorlagen-Untertitel ohne Wiederholung des Schlüssels: „SOIC-8 (3,9 mm, JEDEC MS-012)“ → „3,9 mm, JEDEC MS-012“ */
export function presetSubtitle(p: FootprintPreset): string {
  let label = p.label.trim()
  const key = p.key.trim()
  if (label.toLowerCase().startsWith(key.toLowerCase())) label = label.slice(key.length).trim()
  label = label.replace(/^[,–-]\s*/, '')
  if (label.startsWith('(') && label.endsWith(')')) label = label.slice(1, -1)
  return label || p.label
}

/** Facette zum schnellen Filtern der Vorlagen (Bauteilart oder Gehäusetyp), falls sinnvoll */
export function presetFacet(presets: readonly FootprintPreset[]): { param: string; values: { value: string; count: number }[] } | null {
  for (const param of ['kind', 'variant', 'rows']) {
    const counts = new Map<string, number>()
    for (const p of presets) {
      const v = p.params[param]
      if (v === undefined || v === null) continue
      const key = String(v)
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    // Reihen nur als Kategorie (Stiftleisten 1/2), nicht als Anzahl (BGA 8, 10, 12 …)
    if (param === 'rows' && [...counts.keys()].some((k) => k !== '1' && k !== '2')) continue
    if (counts.size >= 2 && counts.size <= 8 && [...counts.values()].reduce((a, b) => a + b, 0) === presets.length) {
      return { param, values: [...counts.entries()].map(([value, count]) => ({ value, count })) }
    }
  }
  return null
}

/** Zweite Zeile der Familie: Gruppe (falls nicht gleich dem Namen) bzw. Klammerzusatz, Vorlagenzahl */
export function familySubtitle(f: FootprintFamily): string {
  const short = familyShortLabel(f)
  const extra = /\(([^)]*)\)\s*$/.exec(f.label)?.[1]
  const lead = f.group !== short ? f.group : (extra ?? f.group)
  return `${lead} · ${f.presets.length} ${f.presets.length === 1 ? 'Vorlage' : 'Vorlagen'}`
}

const FACET_LABEL: Record<string, Record<string, string>> = {
  kind: {
    R: 'Widerstand',
    C: 'Kondensator',
    L: 'Induktivität',
    FB: 'Ferrit',
    D: 'Diode',
    LED: 'LED',
    CAPMP: 'Tantal',
    INDM: 'Induktivität',
    CAPPRD: 'Elko',
    CAPRD: 'Elko bipolar',
  },
  rows: { '1': '1 Reihe', '2': '2 Reihen' },
}

export const facetLabel = (param: string, value: string): string => FACET_LABEL[param]?.[value] ?? value

/** Werte einer Vorlage als Formularwerte */
export function presetValues(f: FootprintFamily, p: FootprintPreset): ParamValues {
  return normalizeParams(f.params, p.params)
}

function same(a: unknown, b: unknown): boolean {
  const na = Number(String(a).replace(',', '.'))
  const nb = Number(String(b).replace(',', '.'))
  if (Number.isFinite(na) && Number.isFinite(nb) && String(a).trim() !== '' && String(b).trim() !== '') return Math.abs(na - nb) < 1e-6
  return String(a).trim().toLowerCase() === String(b).trim().toLowerCase()
}

const raw = (v: unknown): unknown => {
  if (v && typeof v === 'object' && 'nom' in (v as object)) return (v as { nom: unknown }).nom
  return v
}

/** Übereinstimmung der Selektoren (Gehäusetyp, Größe, Pinzahl, Raster …) – Bewertung wie `best_preset` im Backend */
function selectorScore(preset: FootprintPreset, values: ParamValues): number {
  let score = 0
  for (const key of SELECTOR_PARAMS) {
    const hint = raw(values[key])
    const own = preset.params[key]
    if (hint === null || hint === undefined || own === undefined || own === null) continue
    const strong = STRONG_SELECTORS.includes(key)
    if (same(own, hint)) score += key === 'pins' || key === 'pins_per_row' ? 20 : strong ? 10 : 5
    else score -= strong ? 100 : key === 'pins' || key === 'pins_per_row' ? 50 : 20
  }
  return score
}

/**
 * Vorlage, die zu den Selektorwerten passt (stimmige Selektoren zählen positiv, widersprüchliche starke Selektoren
 * schließen aus). `null` = keine.
 */
export function matchPreset(f: FootprintFamily, values: ParamValues, only?: readonly FootprintPreset[]): FootprintPreset | null {
  let best: { score: number; preset: FootprintPreset } | null = null
  for (const preset of only ?? f.presets) {
    const score = selectorScore(preset, values)
    if (!best || score > best.score) best = { score, preset }
  }
  return best && best.score > 0 ? best.preset : null
}

/** Wie `matchPreset`, bei Gleichstand gewinnt die Vorlage mit den wenigsten abweichenden Werten (SOIC-16 vs. 16W) */
export function closestPreset(f: FootprintFamily, values: ParamValues): FootprintPreset | null {
  let best: { score: number; diff: number; preset: FootprintPreset } | null = null
  for (const preset of f.presets) {
    const score = selectorScore(preset, values)
    if (score <= 0) continue
    const diff = changedParams(f.params, values, presetValues(f, preset)).length
    if (!best || score > best.score || (score === best.score && diff < best.diff)) best = { score, diff, preset }
  }
  return best?.preset ?? null
}

/** Stimmen die starken Selektoren (Gehäusetyp, Größe, Bauart, Code) zweier Wertesätze überein? */
export function sameStrongSelectors(a: ParamValues, b: ParamValues): boolean {
  return STRONG_SELECTORS.every((k) => {
    const x = raw(a[k])
    const y = raw(b[k])
    if (x === null || x === undefined || y === null || y === undefined) return true
    return same(x, y)
  })
}

// --------------------------------------------------------------------------- Kurzinfos der Vorlagen

const BODY_LENGTH = /^(Körperlänge|Körper Y|Körpertiefe|Gesamtlänge)/
const BODY_WIDTH = /^(Körperbreite|Körper X)/
const DIAMETER = /^(Körper)?durchmesser/i

function nominal(f: FootprintFamily, p: FootprintPreset, name: string): number | null {
  const spec = f.params.find((s) => s.name === name)
  if (!spec) return null
  const v = normalizeParam(spec, p.params[name])
  if (typeof v === 'number') return v
  if (typeof v === 'string') {
    const n = Number(v.replace(',', '.'))
    return Number.isFinite(n) ? n : null
  }
  if (isTolValue(v)) return effectiveTol(v)?.nom ?? null
  return null
}

/** Anschlusszahl einer Vorlage (Pins, Zeilen × Spalten, Reihen × Pins je Reihe) */
export function presetPins(p: FootprintPreset): number | null {
  const n = (v: unknown) => (v === undefined || v === null || v === '' ? null : Number(v))
  const pins = n(p.params.pins)
  if (pins !== null && Number.isFinite(pins)) return pins
  const rows = n(p.params.rows)
  const cols = n(p.params.cols) ?? n(p.params.pins_per_row)
  return rows !== null && cols !== null && Number.isFinite(rows * cols) ? rows * cols : null
}

/** Kompakte Kennzahlen einer Vorlage für einzeilige Listen: Pins · Raster · Körper (Breite × Länge) */
export function presetFacts(f: FootprintFamily, p: FootprintPreset): { pins: number | null; pitch: number | null; body: string | null } {
  const pins = presetPins(p)
  const pitchSpec = f.params.find((s) => /^Raster/.test(s.label))
  const pitch = pitchSpec ? nominal(f, p, pitchSpec.name) : null
  const len = f.params.find((s) => s.kind === 'tol' && BODY_LENGTH.test(s.label))
  const wid = f.params.find((s) => s.kind === 'tol' && BODY_WIDTH.test(s.label))
  const dia = f.params.find((s) => s.kind === 'tol' && DIAMETER.test(s.label))
  const l = len ? nominal(f, p, len.name) : null
  const w = wid ? nominal(f, p, wid.name) : null
  const d = dia ? nominal(f, p, dia.name) : null
  const fmt = (v: number) => formatPlain(v, 2)
  let body: string | null = null
  if (w !== null && l !== null) body = (pins ?? 2) > 2 ? `${fmt(w)}×${fmt(l)}` : `${fmt(l)}×${fmt(w)}`
  else if (d !== null && l !== null) body = `${fmt(l)}×Ø${fmt(d)}`
  else if (d !== null) body = `Ø${fmt(d)}`
  else if (w !== null) body = `${fmt(w)}×${fmt(w)}`
  else if (l !== null) body = `${fmt(l)}×${fmt(l)}`
  return { pins: pins !== null && pins > 2 ? pins : null, pitch, body }
}

/**
 * Kennzahlen für die einzeilige Vorlagenliste – ohne das, was der Schlüssel schon sagt
 * („QFN-16-3x3-P0.5“ nennt Pins, Körper und Raster selbst; „SOIC-8“ nur die Pins).
 */
export function presetFactsShort(f: FootprintFamily, p: FootprintPreset): string {
  const { pins, pitch, body } = presetFacts(f, p)
  const key = p.key.toLowerCase()
  const out: string[] = []
  if (pins && !new RegExp(`(^|[^0-9])${pins}([^0-9]|$)`).test(key)) out.push(`${pins} Pins`)
  if (pitch !== null && !key.includes(`p${String(pitch)}`)) out.push(`e ${formatPlain(pitch, 2)}`)
  if (body && !/\d(\.\d+)?x\d/.test(key)) out.push(body)
  return out.join(' · ')
}

/** Kurzinfo als Text für Tooltips: „8 Anschlüsse · Raster 1,27 mm · Körper 3,9×4,9 mm“ */
export function presetFactsText(f: FootprintFamily, p: FootprintPreset): string {
  const { pins, pitch, body } = presetFacts(f, p)
  const out: string[] = []
  if (pins) out.push(`${pins} Anschlüsse`)
  if (pitch !== null) out.push(`Raster ${formatDim(pitch)} mm`)
  if (body) out.push(`Körper ${body} mm`)
  return out.join(' · ')
}

// --------------------------------------------------------------------------- Pinzahl

/**
 * Schrittweite der Pinzahl (↑/↓): 4 bei vierseitigen Gehäusen (QFN/QFP – alle Vorlagen des Gehäusetyps durch 4
 * teilbar), 2 bei zweireihigen (alle gerade), sonst 1. Abgeleitet aus den Vorlagen des aktuellen Gehäusetyps.
 */
export function pinStep(f: FootprintFamily, values: ParamValues): number {
  const pool = f.presets.filter((p) =>
    STRONG_SELECTORS.every((k) => {
      const v = raw(values[k])
      return v === null || v === undefined || p.params[k] === undefined || same(p.params[k], v)
    }),
  )
  const counts = (pool.length ? pool : f.presets).map((p) => Number(p.params.pins)).filter((n) => Number.isFinite(n) && n > 0)
  if (!counts.length) return 1
  const quad = f.params.some((p) => p.name === 'pins_x')
  if (quad && counts.length >= 2 && counts.every((n) => n % 4 === 0)) return 4
  if (counts.every((n) => n % 2 === 0)) return 2
  return 1
}

/** Nächster Wert auf dem Raster `step` (8 → 10, ungerade 9 → 10 bzw. 8) */
export function stepToGrid(current: number, dir: 1 | -1, step: number): number {
  return dir > 0 ? Math.floor(current / step) * step + step : Math.ceil(current / step) * step - step
}

// --------------------------------------------------------------------------- Suche

/** Wörter eines Texts, normalisiert („Gull-Wing (SOIC / SSOP)“ → gullwing, gull, wing, soic, ssop) */
function words(text: string | null | undefined): string[] {
  if (!text) return []
  const out = new Set<string>()
  for (const part of text.toLowerCase().split(/[\s/(),;:·•–—|]+/)) {
    const whole = normalizeTerm(part)
    if (!whole) continue
    out.add(whole)
    for (const sub of part.split(/[-_.+]+/)) {
      const s = normalizeTerm(sub)
      if (s && s !== whole) out.add(s)
    }
  }
  return [...out]
}

/** Suchbegriffe (jedes Wort normalisiert, „SOT-23 5“ → sot23, 5) */
function queryTokens(query: string): string[] {
  return query.split(/\s+/).map(normalizeTerm).filter(Boolean)
}

const wordScore = (list: readonly string[], t: string, exact: number, prefix: number) =>
  list.some((w) => w === t) ? exact : list.some((w) => w.startsWith(t)) ? prefix : 0

/** Normalisierte Suche: jedes Wort muss im Schlüssel, in einem Wort von Name/Gruppe/Beschreibung oder einem Alias stehen */
export function familyMatches(f: FootprintFamily, query: string): number {
  const tokens = queryTokens(query)
  if (!tokens.length) return 1
  const key = normalizeTerm(f.key)
  const label = words(f.label)
  const group = words(f.group)
  const desc = words(f.description)
  const aliases = familyAliases(f).map(normalizeTerm)
  let score = 0
  for (const t of tokens) {
    const best = Math.max(
      key === t ? 4 : key.startsWith(t) ? 3.5 : 0,
      wordScore(label, t, 4, 3),
      wordScore(aliases, t, 3.5, 1.5),
      wordScore(group, t, 1.5, 1),
      wordScore(desc, t, 1, 0.6),
    )
    if (best <= 0) return 0
    score += best
  }
  return score
}

/** Suche in Vorlagen: Schlüssel (auch Teilfolge – „0805“ in „C-0805-0.70“), Wörter der Bezeichnung und Quelle */
export function presetMatches(p: FootprintPreset, query: string): number {
  const tokens = queryTokens(query)
  if (!tokens.length) return 1
  const key = normalizeTerm(p.key)
  const keyWords = words(p.key)
  const label = words(p.label)
  const source = words(p.source)
  let score = 0
  for (const t of tokens) {
    const s = Math.max(
      key === t ? 6 : key.startsWith(t) ? 4 : key.includes(t) && t.length >= 2 ? 3 : 0,
      wordScore(keyWords, t, 3.5, 3),
      wordScore(label, t, 2, 1.5),
      wordScore(source, t, 1, 0.5),
    )
    if (!s) return 0
    score += s
  }
  return score
}

/** Vorlage, deren Schlüssel genau dem Suchbegriff entspricht („DIP-8“, „dip8“) */
export function exactPreset(families: readonly FootprintFamily[], query: string): { family: FootprintFamily; preset: FootprintPreset } | null {
  const q = normalizeTerm(query)
  if (!q) return null
  for (const family of families) {
    const preset = family.presets.find((p) => normalizeTerm(p.key) === q)
    if (preset) return { family, preset }
  }
  return null
}
