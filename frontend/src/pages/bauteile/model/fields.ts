import { metadataLabel, t, getLocale } from '@/lib/i18n'
/**
 * Felder einer Kategorie: Gruppen (Allgemein, Werte, Altium, Beschaffung, Verwaltung), Bearbeitbarkeit,
 * Standard-Sichtbarkeit und -Breite in der Tabelle, Filter-Operatoren je Feldart und Formatierung.
 */
import type { CategoryDef, FieldDef } from '@/api/library'
import type { PartFilter } from '@/api/parts'
import { formatQuantityText, quantityValue, type StatusTone } from '@/components/grid/cellFormat'
import { formatDecimal } from '@/lib/format'
import { formatEngineering, parseEngineering } from '@/lib/units'

export type FieldKind = FieldDef['kind']

// --------------------------------------------------------------------------- Gruppen

export type FieldGroupId = 'allgemein' | 'werte' | 'altium' | 'beschaffung' | 'verwaltung'

export const FIELD_GROUPS: { id: FieldGroupId; label: string; description: string }[] = [
  { id: 'allgemein', get label() { return t("Allgemein") }, get description() { return t("Teilenummer, Hersteller, Beschreibung, Gehäuse") } },
  { id: 'werte', get label() { return t("Werte") }, get description() { return t("Kategoriespezifische Kennwerte") } },
  { id: 'altium', label: 'Altium', get description() { return t("Symbol, Footprint und Datenblatt-Verknüpfung") } },
  { id: 'beschaffung', get label() { return t("Beschaffung") }, get description() { return t("Lieferanten, Lebenszyklus, RoHS") } },
  { id: 'verwaltung', get label() { return t("Verwaltung") }, get description() { return t("Freigabe, Notizen, Änderungsdaten") } },
]

const COMMON_GROUP: Record<string, FieldGroupId> = {
  'Part Number': 'allgemein',
  Manufacturer: 'allgemein',
  'Manufacturer Part Number': 'allgemein',
  Value: 'allgemein',
  Description: 'allgemein',
  Comment: 'allgemein',
  Package: 'allgemein',
  Mounting: 'allgemein',
  Height: 'allgemein',
  'Operating Temperature': 'allgemein',
  'Library Ref': 'altium',
  'Library Path': 'altium',
  'Footprint Ref': 'altium',
  'Footprint Path': 'altium',
  'Footprint Ref 2': 'altium',
  'Footprint Path 2': 'altium',
  ComponentLink1Description: 'altium',
  ComponentLink1URL: 'altium',
  'Supplier 1': 'beschaffung',
  'Supplier Part Number 1': 'beschaffung',
  'Supplier 2': 'beschaffung',
  'Supplier Part Number 2': 'beschaffung',
  Lifecycle: 'beschaffung',
  RoHS: 'beschaffung',
  'PF Status': 'verwaltung',
  Notes: 'verwaltung',
  'PF Created': 'verwaltung',
  'PF Modified': 'verwaltung',
  'PF Author': 'verwaltung',
}

/** Gruppe eines Felds: bekannte Standardfelder nach Name, Kategoriefelder unter „Werte“. */
export function groupOf(field: FieldDef): FieldGroupId {
  const known = COMMON_GROUP[field.column]
  if (known) return known
  if (field.common) return field.system ? 'altium' : 'allgemein'
  return 'werte'
}

/** Felder einer Kategorie nach Gruppen (Reihenfolge wie in der Datenbank) */
export function groupFields(fields: FieldDef[], translate = t): { id: FieldGroupId; label: string; fields: FieldDef[] }[] {
  return FIELD_GROUPS.map((g) => ({ id: g.id, label: metadataLabel(g.label, translate), fields: fields.filter((f) => groupOf(f) === g.id) })).filter(
    (g) => g.fields.length > 0,
  )
}

// --------------------------------------------------------------------------- Eigenschaften

/** Buchhaltungsfelder – setzt das Backend selbst (Angelegt, Geändert, Bearbeiter) */
export const BOOKKEEPING = new Set(['PF Created', 'PF Modified', 'PF Author'])

/** Texte, die aus Vorlagen erzeugt werden (Value, Comment, Description) */
export const GENERATED_TEXTS = ['Value', 'Comment', 'Description'] as const

export const PN = 'Part Number'
export const SYMBOL_REF = 'Library Ref'
export const FOOTPRINT_REF = 'Footprint Ref'
export const DATASHEET = 'ComponentLink1URL'
export const STATUS = 'PF Status'

/** Freigabestatus → Ton */
export const RELEASE_TONES: Record<string, StatusTone> = {
  Entwurf: 'neutral',
  Geprüft: 'info',
  Freigegeben: 'success',
  Gesperrt: 'danger',
}

/** Footprint-Verweis (auch Alternativen „Footprint Ref 2“ …) */
export function isFootprintRef(column: string): boolean {
  return /^Footprint Ref( \d+)?$/.test(column)
}

export function isEditable(field: FieldDef): boolean {
  return !BOOKKEEPING.has(field.column)
}

/** Monospace-Darstellung (Werte, Teilenummern, Codes, Footprint-/Symbolnamen) */
export function isMono(field: FieldDef): boolean {
  if (['quantity', 'range', 'int'].includes(field.kind)) return true
  return [
    PN,
    'Manufacturer Part Number',
    'Value',
    'Comment',
    'Supplier Part Number 1',
    'Supplier Part Number 2',
    SYMBOL_REF,
    FOOTPRINT_REF,
    'Footprint Ref 2',
    'Package',
  ].includes(field.column)
}

export function isNumericKind(kind: FieldKind): boolean {
  return kind === 'quantity' || kind === 'int' || kind === 'range'
}

/** Standardmäßig ausgeblendete Spalten (Detailfelder, Pfade, Buchhaltung) */
const DEFAULT_HIDDEN = new Set([
  'Value',
  'Comment',
  'Mounting',
  'Height',
  'Operating Temperature',
  'Library Path',
  'Footprint Path',
  'Footprint Ref 2',
  'Footprint Path 2',
  'ComponentLink1Description',
  'Supplier 1',
  'Supplier Part Number 1',
  'Supplier 2',
  'Supplier Part Number 2',
  'RoHS',
  'Notes',
  'PF Created',
  'PF Modified',
  'PF Author',
])

/**
 * Standard-Sichtbarkeit einer Spalte. Beim Teilenummern-Schema „mpn“ ist die Hersteller-Teilenummer identisch
 * mit der Teilenummer – dann ist sie zunächst ausgeblendet. Hat die Kategorie eine Baugröße („0603“), wäre das
 * Gehäuse meist derselbe Text – dann bleibt das Gehäuse ausgeblendet.
 */
export function defaultVisible(field: FieldDef, scheme: string | undefined, category?: CategoryDef): boolean {
  if (field.column === 'Manufacturer Part Number') return scheme !== 'mpn'
  if (field.column === 'Package' && category?.fields.some((f) => f.column === 'Size')) return false
  return !DEFAULT_HIDDEN.has(field.column)
}

const KIND_WIDTH: Record<FieldKind, number> = {
  text: 150,
  quantity: 112,
  range: 150,
  enum: 124,
  bool: 92,
  int: 88,
  url: 200,
  path: 180,
  date: 150,
}

/** Spaltenbreite: aus dem Feld (grid_width), sonst je Feldart – nie schmaler als nötig für die Kopfzeile */
export function defaultWidth(field: FieldDef): number {
  if (field.grid_width) return field.grid_width
  const base = KIND_WIDTH[field.kind] ?? 140
  const header = Math.min(180, Math.round(field.label.length * 6.6 + 44))
  return Math.max(base, header)
}

/**
 * Spaltenreihenfolge der Tabelle – das Wichtigste passt ohne Scrollen: Teilenummer, Hauptwert der Kategorie
 * („Widerstand“), Beschreibung, Hersteller, die übrigen Kategoriewerte, Gehäuse, Altium-Verweise, Lebenszyklus,
 * Freigabe – danach alle übrigen (ausgeblendeten) Felder.
 */
export function columnOrder(category: CategoryDef): FieldDef[] {
  const byColumn = new Map(category.fields.map((f) => [f.column, f]))
  const main = category.value_field && byColumn.get(category.value_field)?.common === false ? [category.value_field] : []
  const head = [PN, ...main, 'Description', 'Manufacturer', 'Manufacturer Part Number']
  const values = category.fields.filter((f) => !f.common).map((f) => f.column)
  const tail = ['Package', SYMBOL_REF, FOOTPRINT_REF, DATASHEET, 'Lifecycle', STATUS]
  const ordered = [...head, ...values, ...tail].filter((c, i, all) => byColumn.has(c) && all.indexOf(c) === i)
  const rest = category.fields.map((f) => f.column).filter((c) => !ordered.includes(c))
  return [...ordered, ...rest].map((c) => byColumn.get(c) as FieldDef)
}

/** Feldart für Menschen */
export const KIND_LABEL: Record<FieldKind, string> = {
  text: 'Text',
  get quantity() { return t("Messwert") },
  get range() { return metadataLabel("Bereich", t) },
  get enum() { return t("Auswahl") },
  get bool() { return t("Ja/Nein") },
  get int() { return t("Ganzzahl") },
  url: 'Link',
  get path() { return t("Dateipfad") },
  get date() { return t("Datum") },
}

/** Typische Eingaben je Einheit (Platzhalter) */
const UNIT_EXAMPLE: Record<string, string> = {
  'Ω': '4k7',
  F: '100n',
  H: '4u7',
  V: '50 V',
  get A() { return t("1,5 A") },
  get W() { return t("0,1 W") },
  Hz: '16M',
  '%': '1 %',
  ppm: '20 ppm',
  'ppm/K': '100 ppm/K',
  get mm() { return t("1,6 mm") },
  '°C': '85 °C',
  nm: '525 nm',
  get cd() { return t("0,2 cd") },
  '°': '120°',
  C: '15n',
}

/** Beispiel-Eingabe je Feldart (Platzhalter) */
export function placeholderFor(field: FieldDef): string {
  switch (field.kind) {
    case 'quantity':
      return t("z. B. {1}", { 1: (field.unit && UNIT_EXAMPLE[field.unit]) || (field.unit ? `10 ${field.unit}` : '10k') })
    case 'range':
      return t("z. B. −40 … 85{1}", { 1: field.unit ? ` ${field.unit}` : '' })
    case 'int':
      return t("z. B. 4")
    case 'url':
      return 'https://…'
    case 'path':
      return t("Pfad relativ zur Bibliothek")
    case 'date':
      return t("TT.MM.JJJJ")
    case 'enum':
      return field.options.length ? field.options.slice(0, 3).join(', ') + ' …' : ''
    default:
      return ''
  }
}

// --------------------------------------------------------------------------- Werte anzeigen

/** Wert für die Anzeige: technische Werte mit Leerzeichen/Dezimalkomma, Datumswerte deutsch */
export function displayValue(field: FieldDef | undefined, value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return ''
  if (!field) return value
  if (field.kind === 'quantity' || field.kind === 'range') return isUnreadable(field, value) ? value : formatQuantityText(value)
  if (field.kind === 'date') return formatDateText(value)
  return field.kind === 'bool' || (field.kind === 'enum' && field.options.includes(value)) ? metadataLabel(value, t) : value
}

/** „2026-10-08 02:34:48“ → „08.10.2026, 02:34“ (reine Daten „2026-10-08“ → „08.10.2026“) */
export function formatDateText(value: string): string {
  const m = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/)
  if (!m) return value
  const date = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4] ?? 0), Number(m[5] ?? 0))
  return new Intl.DateTimeFormat(getLocale(), { year: 'numeric', month: '2-digit', day: '2-digit', ...(m[4] ? { hour: '2-digit', minute: '2-digit' } as const : {}) }).format(date)
}

/** „2026-10-08 02:34:48“ → Millisekunden (für relative Zeitangaben) */
export function parseDateText(value: string | null | undefined): number | null {
  if (!value) return null
  const t = Date.parse(value.replace(' ', 'T'))
  return Number.isFinite(t) ? t : null
}

const pad2 = (n: number) => String(n).padStart(2, '0')
const isoDay = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`

/**
 * Datumseingabe lesen: „09.10.2026“, „9.10.26“, „9.10.“ (laufendes Jahr), „2026-10-09“, „heute“, „gestern“ →
 * ISO-Tag „2026-10-09“. `null` = nicht lesbar.
 */
export function parseDateInput(text: string | null | undefined, now: Date = new Date()): string | null {
  const t = (text ?? '').trim().toLowerCase()
  if (!t) return null
  if (t === 'heute' || t === 'today') return isoDay(now)
  if (t === 'gestern' || t === 'yesterday') return isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1))
  let year: number
  let month: number
  let day: number
  const iso = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t].*)?$/)
  const de = t.match(/^(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})?$/)
  if (iso) {
    ;[year, month, day] = [Number(iso[1]), Number(iso[2]), Number(iso[3])]
  } else if (de) {
    day = Number(de[1])
    month = Number(de[2])
    year = de[3] ? (de[3].length === 2 ? 2000 + Number(de[3]) : Number(de[3])) : now.getFullYear()
  } else {
    return null
  }
  const d = new Date(year, month - 1, day)
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return null
  return isoDay(d)
}

/** ISO-Tag → „09.10.2026“ (für Eingabefelder und Filter-Chips) */
export function formatDateInput(iso: string): string {
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m && getLocale() === 'de-DE' ? `${m[3]}.${m[2]}.${m[1]}` : iso
}

/** Tag relativ zu heute als Eingabetext („vor 7 Tagen“ → „01.10.2026“) */
export function daysAgoInput(days: number, now: Date = new Date()): string {
  return formatDateInput(isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - days)))
}

const BOOL_WORDS = new Set(['ja', 'nein', 'yes', 'no', 'true', 'false', '1', '0', 'wahr', 'falsch', 'x'])

/**
 * Gespeicherter Wert, den das Backend nicht lesen konnte (z. B. „abc“ als Toleranz): solche Werte werden beim
 * Sortieren, Filtern und in den Vorlagen nicht als Zahl verstanden. Auswahlfelder mit freiem Wert zählen nicht.
 */
export function isUnreadable(field: FieldDef | undefined, value: string | null | undefined): boolean {
  if (!field || value === null || value === undefined || value.trim() === '') return false
  switch (field.kind) {
    case 'quantity':
    case 'range':
      return quantityValue(value) === null
    case 'int':
      return !/^[-−]?\d+$/.test(value.trim())
    case 'bool':
      return !BOOL_WORDS.has(value.trim().toLowerCase())
    case 'date':
      return parseDateText(value) === null
    default:
      return false
  }
}

/** Warnungen des Backends zu genau diesem Feld („Toleranz: „abc“ ist kein gültiger Wert …“) ohne Präfix */
export function ownWarnings(field: FieldDef, warnings: readonly string[]): string[] {
  const prefix = `${field.label}:`
  return warnings.filter((w) => w.startsWith(prefix)).map((w) => w.slice(prefix.length).trim())
}

/** Warnungen zu anderen Feldern (z. B. „Beschreibung: länger als 255 Zeichen“) */
export function otherWarnings(fields: readonly FieldDef[], warnings: readonly string[]): string[] {
  const prefixes = fields.map((f) => `${f.label}:`)
  return warnings.filter((w) => !prefixes.some((p) => w.startsWith(p)))
}

// --------------------------------------------------------------------------- Filter

export type UiFilterOp =
  | 'contains'
  | 'startswith'
  | 'eq'
  | 'ne'
  | 'gt'
  | 'ge'
  | 'lt'
  | 'le'
  | 'between'
  | 'in'
  | 'notin'
  | 'empty'
  | 'notempty'

export interface FilterCondition {
  id: string
  column: string
  op: UiFilterOp
  /** Vergleichswert (Text, Messwert „10k“) */
  value?: string
  /** Obergrenze bei „zwischen“ */
  to?: string
  /** Mehrere Werte (Auswahlfelder) */
  values?: string[]
}

export const OP_LABEL: Record<UiFilterOp, string> = {
  get contains() { return t("enthält") },
  get startswith() { return t("beginnt mit") },
  get eq() { return t("ist gleich") },
  get ne() { return t("ist ungleich") },
  get gt() { return t("größer als") },
  get ge() { return t("mindestens") },
  get lt() { return t("kleiner als") },
  get le() { return t("höchstens") },
  get between() { return t("zwischen") },
  get in() { return t("ist") },
  get notin() { return t("ist nicht") },
  get empty() { return t("ist leer") },
  get notempty() { return t("ist nicht leer") },
}

/** Kurzform in Filter-Chips */
export const OP_SYMBOL: Partial<Record<UiFilterOp, string>> = {
  eq: '=',
  ne: '≠',
  gt: '>',
  ge: '≥',
  lt: '<',
  le: '≤',
}

/**
 * Vergleiche bei Datumsfeldern (das Backend vergleicht tageweise: „am“ = der ganze Tag, „ab“/„bis“ einschließlich,
 * „vor“/„nach“ ohne den Tag selbst)
 */
const DATE_OP_LABEL: Partial<Record<UiFilterOp, string>> = {
  get ge() { return t("ab") },
  get le() { return t("bis") },
  get eq() { return t("am") },
  get between() { return t("zwischen") },
  get lt() { return t("vor") },
  get gt() { return t("nach") },
}

/** Beschriftung des Datumsfelds einer Bedingung („ab“, „bis einschließlich“, „vor“ …) */
export function dateInputLabel(op: UiFilterOp): string {
  if (op === 'le') return t("bis einschließlich")
  return DATE_OP_LABEL[op] ?? OP_LABEL[op]
}

/** Beschriftung eines Vergleichs – bei Datumsfeldern „am“, „ab“, „bis“ statt „ist gleich“, „mindestens“ … */
export function opLabel(op: UiFilterOp, field?: FieldDef): string {
  return (field?.kind === 'date' ? DATE_OP_LABEL[op] : undefined) ?? OP_LABEL[op]
}

export function opsFor(field: FieldDef): UiFilterOp[] {
  switch (field.kind) {
    case 'quantity':
    case 'int':
    case 'range':
      return ['ge', 'le', 'between', 'gt', 'lt', 'eq', 'ne', 'empty', 'notempty']
    case 'date':
      return ['ge', 'le', 'between', 'eq', 'lt', 'gt', 'empty', 'notempty']
    case 'enum':
    case 'bool':
      return ['in', 'notin', 'empty', 'notempty']
    default:
      return ['contains', 'startswith', 'eq', 'ne', 'empty', 'notempty']
  }
}

export function defaultOp(field: FieldDef): UiFilterOp {
  return opsFor(field)[0]
}

export function needsValue(op: UiFilterOp): boolean {
  return op !== 'empty' && op !== 'notempty'
}

/** Vollständig ausgefüllte Bedingung? (unvollständige werden ignoriert; Datumsfelder brauchen ein lesbares Datum) */
export function isComplete(c: FilterCondition, field?: FieldDef): boolean {
  if (!needsValue(c.op)) return true
  if (c.op === 'in' || c.op === 'notin') return Boolean(c.values?.length)
  const ok = (v: string | undefined) => Boolean(v?.trim()) && (field?.kind !== 'date' || parseDateInput(v) !== null)
  if (c.op === 'between') return ok(c.value) && ok(c.to)
  return ok(c.value)
}

/** Datum für das Backend als ISO-Tag („09.10.2026“ → „2026-10-09“); das Backend vergleicht Datumsfelder tageweise */
function isoDate(text: string | undefined): string | undefined {
  return parseDateInput(text) ?? text?.trim()
}

type FieldLookup = ReadonlyMap<string, FieldDef> | readonly FieldDef[] | undefined
const lookupField = (fields: FieldLookup, column: string): FieldDef | undefined =>
  !fields ? undefined : Array.isArray(fields) ? fields.find((f) => f.column === column) : (fields as ReadonlyMap<string, FieldDef>).get(column)

/** Datumsvergleich der Oberfläche → Operator des Backends („vor“/„nach“ heißen dort `before`/`after`) */
function dateBackendOp(op: Exclude<UiFilterOp, 'between' | 'empty' | 'notempty'>): PartFilter['op'] {
  switch (op) {
    case 'lt':
      return 'before'
    case 'gt':
      return 'after'
    case 'notin':
      return 'ne'
    default:
      return op
  }
}

/**
 * Operator für Vergleiche (gespeicherte Ansicht ↔ aktuelle Filter): `before`/`after` sind dasselbe wie `lt`/`gt` –
 * beide gibt es nur bzw. wirken gleich auf Datumsfeldern.
 */
export function canonicalFilterOp(op: PartFilter['op']): PartFilter['op'] {
  return op === 'before' ? 'lt' : op === 'after' ? 'gt' : op
}

/**
 * Bedingungen der Oberfläche → Filter des Backends. „zwischen“ ist ein Filter `between` mit `[von, bis]` (beide
 * einschließlich; Messwerte mit Einheiten, Datumswerte tageweise). Datumswerte gehen als ISO-Tag: das Backend wertet
 * `ge` ab Tagesbeginn, `le` bis Tagesende, `eq` als den ganzen Tag, `before` vor und `after` nach dem Tag.
 */
export function toPartFilters(conditions: FilterCondition[], fields?: FieldLookup): PartFilter[] {
  const out: PartFilter[] = []
  for (const c of conditions) {
    const field = lookupField(fields, c.column)
    if (!isComplete(c, field)) continue
    if (field?.kind === 'date' && c.op !== 'empty' && c.op !== 'notempty') {
      if (c.op === 'between') out.push({ column: c.column, op: 'between', value: [isoDate(c.value), isoDate(c.to)] })
      else out.push({ column: c.column, op: dateBackendOp(c.op), value: isoDate(c.value) })
      continue
    }
    switch (c.op) {
      case 'between':
        out.push({ column: c.column, op: 'between', value: [c.value?.trim(), c.to?.trim()] })
        break
      case 'in':
        out.push({ column: c.column, op: 'in', value: c.values })
        break
      case 'notin':
        out.push({ column: c.column, op: 'ne', value: c.values })
        break
      case 'empty':
      case 'notempty':
        out.push({ column: c.column, op: c.op })
        break
      default:
        out.push({ column: c.column, op: c.op, value: c.value?.trim() })
    }
  }
  return out
}

/** Gespeicherte Filter (Backend) → Bedingungen der Oberfläche (ge+le derselben Spalte = zwischen) */
export function fromPartFilters(filters: PartFilter[], fields?: FieldLookup): FilterCondition[] {
  const out: FilterCondition[] = []
  const used = new Set<number>()
  filters.forEach((f, i) => {
    if (used.has(i)) return
    const isDate = lookupField(fields, f.column)?.kind === 'date'
    const text = (v: unknown) => {
      if (v === null || v === undefined) return undefined
      const s = String(v)
      return isDate && /^\d{4}-\d{2}-\d{2}/.test(s) ? formatDateInput(s) : s
    }
    if (f.op === 'between') {
      const [lo, hi] = Array.isArray(f.value) ? f.value : [null, null]
      out.push({ id: newConditionId(), column: f.column, op: 'between', value: text(lo), to: text(hi) })
      return
    }
    // ältere gespeicherte Ansichten: „zwischen“ als ge + le derselben Spalte
    if (f.op === 'ge') {
      const j = filters.findIndex((g, k) => k > i && !used.has(k) && g.column === f.column && g.op === 'le')
      if (j >= 0) {
        used.add(j)
        out.push({ id: newConditionId(), column: f.column, op: 'between', value: text(f.value), to: text(filters[j].value) })
        return
      }
    }
    if (f.op === 'before' || f.op === 'after') {
      out.push({ id: newConditionId(), column: f.column, op: f.op === 'before' ? 'lt' : 'gt', value: text(f.value) })
      return
    }
    if (f.op === 'in' || (f.op === 'ne' && Array.isArray(f.value))) {
      const values = (Array.isArray(f.value) ? f.value : [f.value]).map(String)
      out.push({ id: newConditionId(), column: f.column, op: f.op === 'in' ? 'in' : 'notin', values })
      return
    }
    out.push({ id: newConditionId(), column: f.column, op: f.op as UiFilterOp, value: text(f.value) })
  })
  return out
}

let conditionCounter = 0
export function newConditionId(): string {
  conditionCounter += 1
  return `f${Date.now().toString(36)}${conditionCounter}`
}

/** Einheiten, die SI-Präfixe tragen (k, M, µ …) – andere (%, °C, ppm, mm) werden ohne Präfix gezeigt */
const SI_UNITS = new Set(['Ω', 'F', 'H', 'V', 'A', 'W', 'Hz', 's', 'C', 'cd'])

/** Messwert mit Einheit des Felds anzeigen („1k“ → „1 kΩ“, „4k7“ → „4,7 kΩ“, „1%“ → „1 %“) */
export function quantityLabel(field: FieldDef | undefined, raw: string): string {
  const text = raw.trim()
  if (!field || !field.unit || !isNumericKind(field.kind)) return text
  const value = parseEngineering(text.endsWith(field.unit) ? text.slice(0, -field.unit.length) : text)
  if (value !== null) {
    return SI_UNITS.has(field.unit) ? formatEngineering(value, field.unit) : `${formatDecimal(value, 4)}\u00a0${field.unit}`
  }
  return formatQuantityText(text)
}

/** Text eines Filter-Chips, z. B. „Widerstand ≥ 1 kΩ“, „Baugröße: 0603, 0805“, „Geändert ab 09.10.2026“ */
export function conditionLabel(c: FilterCondition, field: FieldDef | undefined): { field: string; rest: string } {
  const name = metadataLabel(field?.label ?? c.column, t)
  const q = (v: string | undefined) => {
    if (field?.kind === 'date') {
      const iso = parseDateInput(v)
      return iso ? formatDateInput(iso) : (v ?? '')
    }
    return quantityLabel(field, v ?? '')
  }
  switch (c.op) {
    case 'between':
      return { field: name, rest: field?.kind === 'date' ? ` ${q(c.value)} – ${q(c.to)}` : ` ${q(c.value)} … ${q(c.to)}` }
    case 'in':
      return { field: name, rest: `: ${(c.values ?? []).map((value) => field?.kind === 'bool' || field?.options.includes(value) ? metadataLabel(value, t) : value).join(', ')}` }
    case 'notin':
      return { field: name, rest: t(" ist nicht {1}", { 1: (c.values ?? []).map((value) => field?.kind === 'bool' || field?.options.includes(value) ? metadataLabel(value, t) : value).join(', ') }) }
    case 'empty':
      return { field: name, rest: t(" ist leer") }
    case 'notempty':
      return { field: name, rest: t(" ist gesetzt") }
    case 'contains':
      return { field: name, rest: t(" enthält „{1}“", { 1: c.value ?? '' }) }
    case 'startswith':
      return { field: name, rest: t(" beginnt mit „{1}“", { 1: c.value ?? '' }) }
    default:
      if (field?.kind === 'date') return { field: name, rest: ` ${opLabel(c.op, field)} ${q(c.value)}` }
      return {
        field: name,
        rest: ` ${OP_SYMBOL[c.op] ?? OP_LABEL[c.op]} ${field && isNumericKind(field.kind) ? q(c.value) : (c.value ?? '')}`,
      }
  }
}
