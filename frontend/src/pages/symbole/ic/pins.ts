import { t as tr } from '@/components/preview/i18n'
/**
 * IC-Pinliste: Zeilenmodell des Editors, Umwandlung in `IcPin`, Einfügen aus der Zwischenablage (TSV aus Excel oder
 * Datenblatt), Überstrich-Helfer (Altium-Syntax `R\E\S\E\T\`), nächste freie Pin-Nummer und Prüfungen.
 */
import type { ElectricalType, IcPin, IcSide } from '@/api/symbols'
import { plural } from '@/lib/format'
import { naturalCompare, parseOverbar } from '@/lib/geometry'

// --------------------------------------------------------------------------- Zeilenmodell

export interface PinRow {
  /** Stabile ID (Schlüssel, Drag & Drop, Fokus) */
  id: string
  designator: string
  name: string
  electrical: ElectricalType
  /** null = automatisch */
  side: IcSide | null
  group: string
  /** 1 … n, 0 = in allen Teilen */
  part: number
  hidden: boolean
  description: string
}

let idCounter = 0

export function newPinId(): string {
  idCounter += 1
  return `p${Date.now().toString(36)}${idCounter.toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

export function makePin(designator: string, patch: Partial<Omit<PinRow, 'id'>> = {}): PinRow {
  return {
    id: newPinId(),
    designator,
    name: '',
    electrical: 'passive',
    side: null,
    group: '',
    part: 1,
    hidden: false,
    description: '',
    ...patch,
  }
}

export function toIcPin(row: PinRow): IcPin {
  return {
    designator: row.designator.trim(),
    name: row.name.trim(),
    electrical: row.electrical,
    side: row.side,
    group: row.group.trim() || null,
    part: row.part,
    hidden: row.hidden,
    description: row.description.trim() || null,
  }
}

const SIDES = new Set<string>(['left', 'right', 'top', 'bottom'])
const ELECTRICAL = new Set<string>(['input', 'output', 'io', 'passive', 'power', 'open_collector', 'open_emitter', 'hiz'])

/** Pin aus einer gespeicherten Anfrage bzw. einem Spec übernehmen (fehlende Felder mit Standardwerten). */
export function fromIcPin(pin: Partial<IcPin> & { designator?: unknown }): PinRow {
  const side = typeof pin.side === 'string' && SIDES.has(pin.side) ? (pin.side as IcSide) : null
  const electrical =
    typeof pin.electrical === 'string' && ELECTRICAL.has(pin.electrical) ? (pin.electrical as ElectricalType) : 'passive'
  const part = Number(pin.part ?? 1)
  return makePin(String(pin.designator ?? ''), {
    name: typeof pin.name === 'string' ? pin.name : '',
    electrical,
    side,
    group: typeof pin.group === 'string' ? pin.group : '',
    part: Number.isFinite(part) ? Math.max(0, Math.round(part)) : 1,
    hidden: pin.hidden === true,
    description: typeof pin.description === 'string' ? pin.description : '',
  })
}

// --------------------------------------------------------------------------- Beschriftungen

export const SIDE_LABEL: Record<IcSide, string> = { left: 'Links', right: 'Rechts', top: 'Oben', bottom: 'Unten' }
export const SIDE_ORDER: IcSide[] = ['left', 'right', 'top', 'bottom']
/** Tastenkürzel im Seiten-Editor (deutsche Anfangsbuchstaben) */
export const SIDE_KEYS: Record<string, IcSide | null> = { l: 'left', r: 'right', o: 'top', u: 'bottom', a: null }

export const ELECTRICAL_OPTIONS: { value: ElectricalType; label: string; short: string }[] = [
  { value: 'input', label: 'Eingang', short: 'Eingang' },
  { value: 'output', label: 'Ausgang', short: 'Ausgang' },
  { value: 'io', label: 'Ein-/Ausgang', short: 'Ein-/Ausgang' },
  { value: 'power', label: 'Versorgung', short: 'Versorgung' },
  { value: 'passive', label: 'Passiv', short: 'Passiv' },
  { value: 'open_collector', label: 'Open Collector / Drain', short: 'Open Collector' },
  { value: 'open_emitter', label: 'Open Emitter / Source', short: 'Open Emitter' },
  { value: 'hiz', label: 'Hochohmig (Tri-State)', short: 'Tri-State' },
]

export const electricalShort = (type: ElectricalType): string =>
  tr(ELECTRICAL_OPTIONS.find((o) => o.value === type)?.short ?? type)

/** Kategoriale Farbe je elektrischem Typ (Punkte in Tabelle und Seiten-Editor) */
export const ELECTRICAL_COLOR: Record<ElectricalType, { color: string; hollow?: boolean }> = {
  input: { color: 'var(--pf-chart-2)' },
  output: { color: 'var(--pf-chart-3)' },
  io: { color: 'var(--pf-chart-5)' },
  power: { color: 'var(--pf-chart-4)' },
  passive: { color: 'var(--pf-chart-6)' },
  open_collector: { color: 'var(--pf-chart-3)', hollow: true },
  open_emitter: { color: 'var(--pf-chart-3)', hollow: true },
  hiz: { color: 'var(--pf-chart-2)', hollow: true },
}

// --------------------------------------------------------------------------- Überstrich

/** Ganzen Text überstreichen: „RESET“ → „R\E\S\E\T\“ (bereits überstrichene Zeichen bleiben es) */
export function overbarAll(text: string): string {
  return parseOverbar(text)
    .map((c) => `${c.ch}\\`)
    .join('')
}

/**
 * Überstrich für die markierten Zeichen umschalten (Markierung in Rohtext-Positionen, z. B. aus einem `<input>`).
 * Ohne Markierung gilt der ganze Name. Sind alle betroffenen Zeichen überstrichen, wird der Überstrich entfernt.
 * Gibt den neuen Rohtext und die neue Markierung zurück.
 */
export function toggleOverbar(raw: string, selStart?: number | null, selEnd?: number | null): { value: string; start: number; end: number } {
  const chars = parseOverbar(raw)
  if (!chars.length) return { value: raw, start: 0, end: 0 }
  // Rohtext-Spanne je Zeichen
  const spans: [number, number][] = []
  let pos = 0
  for (const c of chars) {
    while (raw[pos] === '\\') pos += 1 // verwaiste Backslashes überspringen
    const len = c.barred ? 2 : 1
    spans.push([pos, pos + len])
    pos += len
  }
  const hasSelection = selStart != null && selEnd != null && selEnd > selStart
  const affected = chars.map((_, i) => !hasSelection || (spans[i][1] > (selStart as number) && spans[i][0] < (selEnd as number)))
  if (!affected.some(Boolean)) affected.fill(true)
  const allBarred = chars.every((c, i) => !affected[i] || c.barred)
  const next = chars.map((c, i) => ({ ch: c.ch, barred: affected[i] ? !allBarred : c.barred }))
  let value = ''
  let start = -1
  let end = 0
  next.forEach((c, i) => {
    if (affected[i] && start < 0) start = value.length
    value += c.barred ? `${c.ch}\\` : c.ch
    if (affected[i]) end = value.length
  })
  return { value, start: Math.max(0, start), end }
}

/**
 * Low-aktive Schreibweisen aus Datenblättern in Altium-Syntax umwandeln:
 * `/RESET`, `~RESET`, `!RESET`, `RESET#`, `RESET*`, `nRESET`, `R̅E̅S̅E̅T̅` (kombinierender Überstrich) → `R\E\S\E\T\`.
 * Namen mit Backslash (schon Altium-Syntax) bleiben unverändert; `_N`/`_B` werden bewusst nicht umgewandelt
 * (oft Differenzpaar bzw. Kanal B).
 */
export function activeLowToOverbar(name: string): string {
  const text = name.trim()
  if (!text || text.includes('\\')) return name
  if (/[\u0305\u0304]/.test(text)) {
    let out = ''
    for (let i = 0; i < text.length; i += 1) {
      const ch = text[i]
      if (ch === '\u0305' || ch === '\u0304') continue
      const barred = text[i + 1] === '\u0305' || text[i + 1] === '\u0304'
      out += barred ? `${ch}\\` : ch
    }
    return out
  }
  let m = /^[/~!](.+)$/.exec(text)
  if (m) return overbarAll(m[1])
  m = /^(.+?)[#*]$/.exec(text)
  if (m) return overbarAll(m[1])
  m = /^n([A-Z][A-Z0-9_]*)$/.exec(text)
  if (m) return overbarAll(m[1])
  return name
}

// --------------------------------------------------------------------------- Elektrischer Typ

const TYPE_EXACT: [RegExp, ElectricalType][] = [
  [/^(i\/o|io|e\/a|ein-?\/?ausgang|bidir(ektional|ectional)?|in\/?out|inout|b|bi|bidi)$/, 'io'],
  [/^(od|oc|o\/d|o\/c|open[- ]?(drain|collector|kollektor)|opendrain|opencollector)$/, 'open_collector'],
  [/^(oe|os|open[- ]?(emitter|source))$/, 'open_emitter'],
  [/^(z|hi-?z|hiz|tri|tri-?state|3-?state|hochohmig)$/, 'hiz'],
  [/^(i|in|input|eingang|e|di|ai|ein|dig\. ?in)$/, 'input'],
  [/^(o|out|output|ausgang|do|ao|aus|dig\. ?out)$/, 'output'],
  [/^(p|pwr|power|supply|versorgung|g|gnd|ground|masse|s|ps|pi|po|v|power in|power out|stromversorgung)$/, 'power'],
  [/^(passive|passiv|pas|nc|n\/c|-|–|—|analog|a|an)$/, 'passive'],
]

const TYPE_KEYWORDS: [RegExp, ElectricalType][] = [
  [/open[- ]?(drain|collector|kollektor)/, 'open_collector'],
  [/open[- ]?(emitter|source)/, 'open_emitter'],
  [/(bidir|i\/o|ein-?\/ausgang|input\/output)/, 'io'],
  [/(tri-?state|hi-?z|hochohmig)/, 'hiz'],
  [/(power|supply|versorgung|ground|masse)/, 'power'],
  [/(input|eingang)/, 'input'],
  [/(output|ausgang)/, 'output'],
  [/(passive|passiv|analog|no connect|not connected)/, 'passive'],
]

/** Typ-Angabe aus einer Tabelle („I/O“, „Eingang“, „PWR“, „OD“ …) erkennen; null = unbekannt */
export function parseElectrical(raw: string): ElectricalType | null {
  const t = raw.trim().toLowerCase().replace(/\s+/g, ' ')
  if (!t) return null
  if (ELECTRICAL.has(t)) return t as ElectricalType
  for (const [re, type] of TYPE_EXACT) if (re.test(t)) return type
  const head = t.split(/[,(;]/)[0].trim()
  for (const [re, type] of TYPE_EXACT) if (re.test(head)) return type
  for (const [re, type] of TYPE_KEYWORDS) if (re.test(t)) return type
  return null
}

const POWER_NAME =
  /^(V(CC|DD|EE|SS|IN|BAT|BATT|BUS|SYS|PP|M|S|IO|REF|LED|DRV|CORE|AUX)[A-Z0-9_+-]*|[ADP]?VDD[A-Z0-9_]*|[ADP]?VCC[A-Z0-9_]*|[ADPS]?GND[A-Z0-9_]*|[ADP]?VSS[A-Z0-9_]*|V\+|V-|\+\d+V\d*)$/i

/** Typ aus dem Pinnamen schätzen (nur Versorgung/Masse sind eindeutig) */
export function guessElectrical(name: string): ElectricalType {
  const text = parseOverbar(name)
    .map((c) => c.ch)
    .join('')
    .trim()
  return POWER_NAME.test(text) ? 'power' : 'passive'
}

// --------------------------------------------------------------------------- Einfügen (TSV)

export type PasteColumn = 'designator' | 'name' | 'electrical' | 'description' | 'side' | 'group' | 'part' | 'hidden'

export const PASTE_COLUMN_LABEL: Record<PasteColumn, string> = {
  designator: 'Nummer',
  name: 'Name',
  electrical: 'Typ',
  description: 'Beschreibung',
  side: 'Seite',
  group: 'Gruppe',
  part: 'Teil',
  hidden: 'Verborgen',
}

const HEADER_PATTERNS: [RegExp, PasteColumn][] = [
  [/^(pin|pins|nr\.?|no\.?|number|nummer|pin ?(nr\.?|no\.?|number|#|nummer)|pin-nr\.?|#|designator|ball|pad)$/, 'designator'],
  [/^(name|signal|pin ?name|pin-name|signal ?name|bezeichnung|pinbezeichnung|symbol)$/, 'name'],
  [/^(type|typ|i\/o|io|direction|richtung|art|pin ?type|pin-typ|elektrisch|electrical|e\/a)$/, 'electrical'],
  [/^(beschreibung|description|funktion|function|kommentar|comment|bemerkung)$/, 'description'],
  [/^(seite|side)$/, 'side'],
  [/^(gruppe|group)$/, 'group'],
  [/^(teil|part|unit|einheit)$/, 'part'],
  [/^(verborgen|hidden|versteckt)$/, 'hidden'],
]

function headerColumn(cell: string): PasteColumn | null {
  const t = cell.trim().toLowerCase().replace(/\s+/g, ' ')
  for (const [re, col] of HEADER_PATTERNS) if (re.test(t)) return col
  return null
}

const DESIGNATOR_RE = /^([A-Z]{0,3}\d{1,4}[A-Z]?|EP\d*|PAD\d*|TAB|SH\d*|MP\d*)$/i

function isDesignatorLike(cell: string): boolean {
  return expandDesignators(cell).length > 0
}

/** „5“, „A1“, „5, 6“, „5-8“, „5–8“ → einzelne Pin-Nummern ([] = keine Pin-Nummer) */
export function expandDesignators(cell: string): string[] {
  const text = cell.trim()
  if (!text) return []
  const parts = text.split(/\s*[,;/]\s*|\s+/).filter(Boolean)
  const out: string[] = []
  for (const part of parts) {
    const range = /^(\d{1,4})\s*[-–]\s*(\d{1,4})$/.exec(part)
    if (range) {
      const a = Number(range[1])
      const b = Number(range[2])
      if (b < a || b - a > 255) return []
      for (let n = a; n <= b; n += 1) out.push(String(n))
      continue
    }
    if (!DESIGNATOR_RE.test(part)) return []
    out.push(part.toUpperCase())
  }
  return out
}

export type PasteSeparator = 'tab' | 'semicolon' | 'comma' | 'spaces'

export const SEPARATOR_LABEL: Record<PasteSeparator, string> = {
  tab: 'Tabulator',
  semicolon: 'Semikolon',
  comma: 'Komma',
  spaces: 'Leerzeichen',
}

export interface ParsedPin {
  designator: string
  name: string
  electrical: ElectricalType
  /** Herkunft des Typs: Spalte, aus dem Namen geschätzt oder unbekannt (→ Passiv) */
  electricalSource: 'column' | 'guess' | 'unknown'
  rawType: string
  description: string
  side: IcSide | null
  group: string
  part: number
  hidden: boolean
  /** Zeile im eingefügten Text (1-basiert) */
  line: number
}

export interface PasteResult {
  pins: ParsedPin[]
  separator: PasteSeparator
  headerSkipped: boolean
  columns: PasteColumn[]
  /** Zuordnung je Spalte des eingefügten Texts (null = ignoriert) */
  mapping: (PasteColumn | null)[]
  /** Anzahl der Spalten (größte Zeile) */
  columnCount: number
  /** Erste Datenzeile (Beispielwerte je Spalte für die Zuordnung) */
  sample: string[]
  /** Zeilen ohne erkennbare Pin-Nummer */
  ignoredLines: number[]
  unknownTypes: string[]
}

export interface PasteOptions {
  /** Low-aktive Schreibweisen in Überstriche umwandeln (Standard: ja) */
  convertActiveLow?: boolean
  /** Eigene Spaltenzuordnung (überschreibt Kopfzeile und Erkennung) */
  mapping?: readonly (PasteColumn | null)[] | null
}

function splitCsvLine(line: string, sep: string): string[] {
  const out: string[] = []
  let cur = ''
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') {
        cur += '"'
        i += 1
      } else quoted = !quoted
    } else if (ch === sep && !quoted) {
      out.push(cur)
      cur = ''
    } else cur += ch
  }
  out.push(cur)
  return out.map((c) => c.trim())
}

function detectSeparator(lines: string[]): PasteSeparator {
  if (lines.some((l) => l.includes('\t'))) return 'tab'
  const share = (ch: string) => lines.filter((l) => l.includes(ch)).length / lines.length
  if (share(';') >= 0.6) return 'semicolon'
  if (share(',') >= 0.6 && lines.every((l) => l.split(',').length <= 8)) return 'comma'
  return 'spaces'
}

function splitLine(line: string, sep: PasteSeparator): string[] {
  switch (sep) {
    case 'tab':
      return line.split('\t').map((c) => c.trim())
    case 'semicolon':
      return splitCsvLine(line, ';')
    case 'comma':
      return splitCsvLine(line, ',')
    default: {
      if (/\s{2,}/.test(line)) return line.trim().split(/\s{2,}/)
      // einfache Leerzeichen: ab der vierten Spalte ist alles Beschreibung
      const cells = line.trim().split(/\s+/)
      return cells.length > 4 ? [...cells.slice(0, 3), cells.slice(3).join(' ')] : cells
    }
  }
}

const SIDE_ALIASES: Record<string, IcSide> = {
  l: 'left',
  links: 'left',
  left: 'left',
  r: 'right',
  rechts: 'right',
  right: 'right',
  o: 'top',
  oben: 'top',
  top: 'top',
  t: 'top',
  u: 'bottom',
  unten: 'bottom',
  bottom: 'bottom',
  b: 'bottom',
}

/** Reine Pin-Nummern („12“, „5, 6“, „5–8“) – eindeutiger als BGA-Kugeln, die wie Signalnamen aussehen (PA0, IO12) */
const NUMERIC_CELL_RE = /^\d{1,4}(\s*[,;/–-]\s*\d{1,4})*$/

/**
 * Tabelle aus der Zwischenablage lesen: Trennzeichen (Tab, Semikolon, Komma, Leerzeichen) und Kopfzeile werden
 * erkannt. Ohne Kopfzeile gilt „Nummer, Name, Typ, Beschreibung“ – vertauschte Spalten „Name, Nummer“ werden an
 * den rein numerischen Nummern erkannt (Namen wie PA0 oder IO12 sehen sonst wie Kugelnummern aus). Eine eigene
 * Zuordnung (`mapping`) hat Vorrang. Mehrfachnummern („5, 6“ oder „5–8“) ergeben je einen Pin gleichen Namens.
 */
export function parsePinTable(text: string, opts: PasteOptions = {}): PasteResult {
  const lines = text
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((l, i) => ({ text: l.replace(/\s+$/, ''), line: i + 1 }))
    .filter((l) => l.text.trim() !== '')
  const empty: PasteResult = {
    pins: [],
    separator: 'tab',
    headerSkipped: false,
    columns: [],
    mapping: [],
    columnCount: 0,
    sample: [],
    ignoredLines: [],
    unknownTypes: [],
  }
  if (!lines.length) return empty
  const separator = detectSeparator(lines.map((l) => l.text))
  const rows = lines.map((l) => ({ cells: splitLine(l.text, separator), line: l.line }))
  const columnCount = Math.max(...rows.map((r) => r.cells.length))

  // Kopfzeile?
  let columns: (PasteColumn | null)[] = []
  let headerSkipped = false
  const headerCols = rows[0].cells.map(headerColumn)
  if (headerCols.filter(Boolean).length >= 1 && !isDesignatorLike(rows[0].cells[0] ?? '')) {
    columns = headerCols
    headerSkipped = true
    rows.shift()
    if (!columns.includes('designator')) {
      // Kopfzeile ohne Nummernspalte: erste freie Spalte mit Pin-Nummern suchen
      const idx = columns.findIndex((c, i) => c === null && rows.every((r) => isDesignatorLike(r.cells[i] ?? '')))
      if (idx >= 0) columns[idx] = 'designator'
    }
  } else {
    // Position: Nummer, Name, Typ, Beschreibung – vertauschte Spalten (Name, Nummer) erkennen
    const numeric = (i: number) => rows.filter((r) => NUMERIC_CELL_RE.test((r.cells[i] ?? '').trim())).length
    const designatorLike = (i: number) => rows.filter((r) => isDesignatorLike(r.cells[i] ?? '')).length
    const [num0, num1] = [numeric(0), numeric(1)]
    const swapped = num1 !== num0 ? num1 > num0 : designatorLike(1) > designatorLike(0)
    columns = swapped ? ['name', 'designator', 'electrical', 'description'] : ['designator', 'name', 'electrical', 'description']
  }
  if (opts.mapping) columns = Array.from({ length: columnCount }, (_, i) => opts.mapping?.[i] ?? null)
  const mapping = Array.from({ length: columnCount }, (_, i) => columns[i] ?? null)

  const col = (cells: string[], kind: PasteColumn) => {
    const i = columns.indexOf(kind)
    return i >= 0 ? (cells[i] ?? '').trim() : ''
  }
  const hasTypeColumn = columns.includes('electrical')
  const pins: ParsedPin[] = []
  const ignoredLines: number[] = []
  const unknown = new Set<string>()

  for (const row of rows) {
    const designators = expandDesignators(col(row.cells, 'designator'))
    if (!designators.length) {
      ignoredLines.push(row.line)
      continue
    }
    let name = col(row.cells, 'name')
    if (opts.convertActiveLow ?? true) name = activeLowToOverbar(name)
    const rawType = col(row.cells, 'electrical')
    let electrical: ElectricalType = 'passive'
    let electricalSource: ParsedPin['electricalSource'] = 'guess'
    if (hasTypeColumn && rawType) {
      const parsed = parseElectrical(rawType)
      if (parsed) {
        electrical = parsed
        electricalSource = 'column'
      } else {
        unknown.add(rawType)
        electricalSource = 'unknown'
        electrical = guessElectrical(name)
      }
    } else {
      electrical = guessElectrical(name)
    }
    const sideRaw = col(row.cells, 'side').toLowerCase()
    const partRaw = Number(col(row.cells, 'part'))
    const hiddenRaw = col(row.cells, 'hidden').toLowerCase()
    for (const designator of designators) {
      pins.push({
        designator,
        name,
        electrical,
        electricalSource,
        rawType,
        description: col(row.cells, 'description'),
        side: SIDE_ALIASES[sideRaw] ?? null,
        group: col(row.cells, 'group'),
        part: Number.isFinite(partRaw) && col(row.cells, 'part') !== '' ? Math.max(0, Math.round(partRaw)) : 1,
        hidden: ['1', 'ja', 'x', 'yes', 'true', 'wahr'].includes(hiddenRaw),
        line: row.line,
      })
    }
  }
  return {
    pins,
    separator,
    headerSkipped,
    columns: mapping.filter((c): c is PasteColumn => c !== null),
    mapping,
    columnCount,
    sample: rows[0]?.cells ?? [],
    ignoredLines,
    unknownTypes: [...unknown],
  }
}

export function parsedToRow(p: ParsedPin): PinRow {
  return makePin(p.designator, {
    name: p.name,
    electrical: p.electrical,
    side: p.side,
    group: p.group,
    part: p.part,
    hidden: p.hidden,
    description: p.description,
  })
}

// --------------------------------------------------------------------------- Nummern

/** Nächste freie Pin-Nummer: nach `after` hochzählen („A7“ → „A8“) bzw. höchste Zahl + 1 */
export function nextDesignator(pins: readonly Pick<PinRow, 'designator'>[], after?: string): string {
  const used = new Set(pins.map((p) => p.designator.trim().toUpperCase()))
  const free = (d: string) => !used.has(d.toUpperCase())
  const base = after?.trim()
  if (base) {
    const m = /^(.*?)(\d+)$/.exec(base)
    if (m) {
      let n = Number(m[2])
      for (let i = 0; i < 10_000; i += 1) {
        n += 1
        const candidate = `${m[1]}${n}`
        if (free(candidate)) return candidate
      }
    }
    for (let i = 2; i < 10_000; i += 1) if (free(`${base}_${i}`)) return `${base}_${i}`
  }
  let max = 0
  for (const p of pins) {
    const n = Number(p.designator)
    if (Number.isInteger(n) && n > max) max = n
  }
  let n = max + 1
  while (!free(String(n))) n += 1
  return String(n)
}

/** Natürliche Sortierung nach Pin-Nummer (1, 2, 10, A1 …) */
export function sortByDesignator(pins: PinRow[]): PinRow[] {
  return [...pins].sort((a, b) => naturalCompare(a.designator, b.designator))
}

// --------------------------------------------------------------------------- Prüfungen

export interface PinIssue {
  level: 'error' | 'warning' | 'info'
  message: string
  /** betroffene Zeile (für „Zur Zeile springen“) */
  rowId?: string
  field?: 'designator' | 'name' | 'part'
}

export interface ValidationResult {
  issues: PinIssue[]
  /** Zeilen-ID → Feld → Meldung (für die Markierung in der Tabelle) */
  byRow: Map<string, Partial<Record<'designator' | 'name' | 'part', string>>>
  errorCount: number
}

export const MAX_PARTS = 64

/** [2, 3, 4, 7] → „2–4, 7“ */
export function formatRanges(numbers: readonly number[]): string {
  const out: string[] = []
  let i = 0
  while (i < numbers.length) {
    let j = i
    while (j + 1 < numbers.length && numbers[j + 1] === numbers[j] + 1) j += 1
    out.push(j > i ? `${numbers[i]}–${numbers[j]}` : String(numbers[i]))
    i = j + 1
  }
  return out.join(', ')
}

/**
 * Prüft die Pinliste wie der Generator auf Fehler (doppelte/fehlende Nummern, ungültige oder lückenhafte Teile,
 * Teile-Spalte zusammen mit „Teile: Anzahl“) und Hinweise (Pins ohne Namen). `partsMode` = Einstellung „Teile“.
 */
export function validatePins(pins: readonly PinRow[], opts: { partsMode?: '1' | 'auto' | 'fixed' } = {}): ValidationResult {
  const issues: PinIssue[] = []
  const byRow = new Map<string, Partial<Record<'designator' | 'name' | 'part', string>>>()
  const mark = (id: string, field: 'designator' | 'name' | 'part', msg: string) => {
    byRow.set(id, { ...byRow.get(id), [field]: msg })
  }

  const seen = new Map<string, number[]>()
  pins.forEach((p, i) => {
    const d = p.designator.trim()
    if (!d) {
      issues.push({ level: 'error', message: tr("Zeile {value0}: Die Pin-Nummer fehlt.", { value0: String(i + 1) }), rowId: p.id, field: 'designator' })
      mark(p.id, 'designator', tr('Pin-Nummer fehlt'))
      return
    }
    if (/\s/.test(d)) {
      issues.push({ level: 'error', message: tr("Pin-Nummer „{value0}“ enthält Leerzeichen.", { value0: String(d) }), rowId: p.id, field: 'designator' })
      mark(p.id, 'designator', tr('Keine Leerzeichen in Pin-Nummern'))
    }
    const key = d.toUpperCase()
    seen.set(key, [...(seen.get(key) ?? []), i])
  })
  for (const [key, rows] of seen) {
    if (rows.length < 2) continue
    const label = pins[rows[0]].designator.trim() || key
    issues.push({
      level: 'error',
      message: tr("Pin-Nummer {value0} ist doppelt vergeben (Zeilen {value1}).", { value0: String(label), value1: String(rows.map((r) => r + 1).join(', ')) }),
      rowId: pins[rows[1]].id,
      field: 'designator',
    })
    for (const r of rows) mark(pins[r].id, 'designator', tr("Pin-Nummer {value0} ist doppelt vergeben", { value0: String(label) }))
  }

  let partsValid = true
  for (const p of pins) {
    if (!Number.isInteger(p.part) || p.part < 0 || p.part > MAX_PARTS) {
      partsValid = false
      issues.push({ level: 'error', message: tr("Pin {value0}: Teil {value1} ist ungültig (0 … {value2}).", { value0: String(p.designator || '?'), value1: String(p.part), value2: String(MAX_PARTS) }), rowId: p.id, field: 'part' })
      mark(p.id, 'part', tr("Teil 0 … {value0}", { value0: String(MAX_PARTS) }))
    }
  }

  const userParts = pins.filter((p) => p.part !== 1)
  if (partsValid && opts.partsMode === 'fixed' && userParts.length) {
    // „Teile: Anzahl“ verteilt selbst – zusammen mit eigenen Teilen lehnt der Generator ab
    issues.push({
      level: 'error',
      message: tr("Die Spalte „Teil“ legt schon Teile fest ({value0} nicht in Teil 1) – für „Teile: Anzahl“ alle auf 1 setzen oder „Ein Teil“ wählen.", { value0: String(plural(userParts.length, tr('Pin'), tr('Pins'))) }),
      rowId: userParts[0].id,
      field: 'part',
    })
    for (const p of userParts) mark(p.id, 'part', tr('Bei „Teile: Anzahl“ verteilt der Generator – hier 1 eintragen'))
  } else if (partsValid && !pins.some((p) => p.part === 0)) {
    // Teile lückenlos ab 1 (Pins mit Teil 0 erscheinen in jedem Teil – dann sind Lücken erlaubt)
    const used = new Set(pins.map((p) => p.part))
    const maxPart = Math.max(0, ...used)
    const missing: number[] = []
    for (let k = 1; k <= maxPart; k += 1) if (!used.has(k)) missing.push(k)
    if (missing.length) {
      const after = pins.filter((p) => p.part > missing[0])
      issues.push({
        level: 'error',
        message: tr("{value0} keine Pins – bitte die Teile lückenlos ab 1 nummerieren (höchster Teil: {value1}).", { value0: String(missing.length === 1 ? tr("Teil {value0} hat", { value0: String(missing[0]) }) : tr("Teile {value0} haben", { value0: String(formatRanges(missing)) })), value1: String(maxPart) }),
        rowId: after[0]?.id,
        field: 'part',
      })
      for (const p of after) mark(p.id, 'part', tr("Teil {value0} fehlt – Teile lückenlos ab 1 nummerieren", { value0: String(missing[0]) }))
    }
  }

  const unnamed = pins.filter((p) => p.designator.trim() && !p.name.trim())
  if (unnamed.length) {
    issues.push({
      level: 'warning',
      message:
        unnamed.length === 1
          ? tr("Pin {value0} hat keinen Namen.", { value0: String(unnamed[0].designator) })
          : tr("{value0} Pins ohne Namen: {value1}{value2}", { value0: String(unnamed.length), value1: String(unnamed
              .slice(0, 8)
              .map((p) => p.designator)
              .join(', ')), value2: String(unnamed.length > 8 ? ' …' : '') }),
      rowId: unnamed[0].id,
      field: 'name',
    })
  }

  const maxPart = pins.reduce((m, p) => (Number.isInteger(p.part) ? Math.max(m, p.part) : m), 0)
  if (maxPart > 1 && opts.partsMode !== 'fixed') {
    issues.push({ level: 'info', message: tr("Die Pinliste legt {value0} Teile fest (Spalte „Teil“).", { value0: String(maxPart) }) })
  }

  // Fehler zuerst (die Fußzeile zeigt die erste Meldung)
  const rank = { error: 0, warning: 1, info: 2 } as const
  issues.sort((a, b) => rank[a.level] - rank[b.level])
  return { issues, byRow, errorCount: issues.filter((i) => i.level === 'error').length }
}

