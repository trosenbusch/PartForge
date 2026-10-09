/** Metadaten des Schema-Designers: Feldarten, Einheiten, Symbole, Farbpalette und Namensregeln (wie im Backend). */
import {
  Binary,
  Calendar,
  FolderOpen,
  Hash,
  Link2,
  ListChecks,
  MoveHorizontal,
  Ruler,
  ToggleLeft,
  Type,
  type LucideIcon,
} from 'lucide-react'
import { createElement, type ReactElement } from 'react'
import type { CategoryDef, FieldDef, FieldKind } from '@/api/settings'

export const FIELD_KIND_META: Record<FieldKind, { icon: LucideIcon; label: string; help: string }> = {
  text: { icon: Type, label: 'Text', help: 'Beliebiger Text, z. B. Gehäuse oder Hersteller.' },
  quantity: { icon: Ruler, label: 'Messwert mit Einheit', help: 'Technischer Wert wie „10k“ → 10kΩ – sortier- und filterbar.' },
  range: { icon: MoveHorizontal, label: 'Bereich (von … bis)', help: 'Zwei Werte, z. B. „-40 bis 125“ → -40°C … 125°C.' },
  enum: { icon: ListChecks, label: 'Auswahlliste', help: 'Feste Werte zur Auswahl (freie Eingabe bleibt möglich).' },
  bool: { icon: ToggleLeft, label: 'Ja/Nein', help: 'Gespeichert als „Ja“ oder „Nein“.' },
  int: { icon: Hash, label: 'Ganzzahl', help: 'Ganze Zahl, z. B. Pinzahl oder Kanäle.' },
  url: { icon: Link2, label: 'Link/URL', help: 'Webadresse, z. B. Datenblatt oder Produktseite.' },
  path: { icon: FolderOpen, label: 'Dateipfad', help: 'Pfad relativ zur Bibliothek (Altium-Schreibweise mit \\).' },
  date: { icon: Calendar, label: 'Datum', help: 'Datum im ISO-Format (2026-10-08).' },
}

/** Symbol einer Feldart als Element (keine Komponenten-Variablen im Render) */
export function kindIcon(kind: FieldKind): ReactElement {
  return createElement(FIELD_KIND_META[kind]?.icon ?? Binary, { 'aria-hidden': true })
}

/** Gängige Einheiten für Messwerte (freie Eingabe möglich) */
export const UNIT_SUGGESTIONS: { value: string; label: string }[] = [
  { value: 'Ω', label: 'Ohm' },
  { value: 'F', label: 'Farad' },
  { value: 'H', label: 'Henry' },
  { value: 'V', label: 'Volt' },
  { value: 'A', label: 'Ampere' },
  { value: 'W', label: 'Watt' },
  { value: 'Hz', label: 'Hertz' },
  { value: '%', label: 'Prozent (±)' },
  { value: 'ppm', label: 'ppm (Verhältnis)' },
  { value: 'ppm/K', label: 'ppm/K (Temperaturkoeffizient)' },
  { value: '°C', label: 'Grad Celsius' },
  { value: 'mm', label: 'Millimeter' },
  { value: 's', label: 'Sekunden' },
  { value: 'dB', label: 'Dezibel' },
  { value: 'cd', label: 'Candela' },
  { value: 'nm', label: 'Nanometer' },
  { value: 'V/µs', label: 'Anstiegsrate' },
]

/** Symbole, die `CategoryIcon` kennt (Lucide-Name → deutsche Beschriftung) */
export const CATEGORY_ICON_CHOICES: { name: string; label: string }[] = [
  { name: 'activity', label: 'Signal' },
  { name: 'square-split-horizontal', label: 'Platten' },
  { name: 'waves', label: 'Wellen' },
  { name: 'magnet', label: 'Magnet' },
  { name: 'triangle-right', label: 'Diode' },
  { name: 'lightbulb', label: 'Leuchte' },
  { name: 'git-fork', label: 'Verzweigung' },
  { name: 'git-merge', label: 'Zusammenführung' },
  { name: 'triangle', label: 'Verstärker' },
  { name: 'gauge', label: 'Regler' },
  { name: 'zap', label: 'Blitz' },
  { name: 'binary', label: 'Binär' },
  { name: 'cpu', label: 'Prozessor' },
  { name: 'microchip', label: 'Mikrochip' },
  { name: 'memory-stick', label: 'Speicher' },
  { name: 'sun-medium', label: 'Licht' },
  { name: 'audio-waveform', label: 'Schwingung' },
  { name: 'radio', label: 'Funk' },
  { name: 'radio-tower', label: 'Antenne' },
  { name: 'wifi', label: 'WLAN' },
  { name: 'plug', label: 'Stecker' },
  { name: 'cable', label: 'Kabel' },
  { name: 'toggle-left', label: 'Schalter' },
  { name: 'shield', label: 'Schutz' },
  { name: 'battery', label: 'Batterie' },
  { name: 'thermometer', label: 'Temperatur' },
  { name: 'fan', label: 'Lüfter' },
  { name: 'speaker', label: 'Lautsprecher' },
  { name: 'monitor', label: 'Anzeige' },
  { name: 'circuit-board', label: 'Leiterplatte' },
  { name: 'layers', label: 'Lagen' },
  { name: 'component', label: 'Bauteil' },
  { name: 'package', label: 'Paket' },
  { name: 'box', label: 'Box' },
  { name: 'boxes', label: 'Boxen' },
  { name: 'cog', label: 'Zahnrad' },
  { name: 'wrench', label: 'Werkzeug' },
]

/** „waves-horizontal“ und „waves“ zeigen dasselbe Symbol */
export const sameIcon = (a: string | null | undefined, b: string) =>
  (a === 'waves-horizontal' ? 'waves' : a) === (b === 'waves-horizontal' ? 'waves' : b)

/** Kuratierte Kategoriefarben (gut unterscheidbar, in beiden Themes lesbar) */
export const CATEGORY_COLORS: { value: string; label: string }[] = [
  { value: '#F2555A', label: 'Rot' },
  { value: '#FB7185', label: 'Rosé' },
  { value: '#E8467C', label: 'Magenta' },
  { value: '#C084FC', label: 'Lila' },
  { value: '#A78BFA', label: 'Violett' },
  { value: '#818CF8', label: 'Indigo' },
  { value: '#60A5FA', label: 'Blau' },
  { value: '#38BDF8', label: 'Himmelblau' },
  { value: '#06B6D4', label: 'Cyan' },
  { value: '#2DD4BF', label: 'Türkis' },
  { value: '#3DD68C', label: 'Grün' },
  { value: '#22C55E', label: 'Smaragd' },
  { value: '#EAB308', label: 'Gelb' },
  { value: '#F5B544', label: 'Bernstein' },
  { value: '#FF8A3D', label: 'Kupfer' },
  { value: '#F97316', label: 'Orange' },
  { value: '#94A3B8', label: 'Schiefer' },
  { value: '#9CA3AF', label: 'Grau' },
]

export const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/

// --------------------------------------------------------------------------- Namensregeln (partforge/db/categories.py)

const TABLE_RE = /^[A-Za-z][A-Za-z0-9 _-]{0,63}$/
const FORBIDDEN_COLUMN_CHARS = new Set('[]"\'`|=.{}$:;\\'.split(''))

export function normalizeName(name: string): string {
  return name.split(/\s+/).filter(Boolean).join(' ')
}

export function validateTableName(name: string, existing: CategoryDef[], current?: string): string | null {
  const cleaned = normalizeName(name)
  if (!cleaned) return 'Bitte einen Tabellennamen eingeben.'
  if (!TABLE_RE.test(cleaned)) {
    return 'Nur Buchstaben A–Z (ohne Umlaute), Ziffern, Leerzeichen, „-“ und „_“; am Anfang ein Buchstabe, höchstens 64 Zeichen.'
  }
  if (/^(pf_|sqlite_)/i.test(cleaned)) return 'Namen mit „pf_“ oder „sqlite_“ am Anfang sind für PartForge reserviert.'
  const folded = cleaned.toLowerCase()
  if (existing.some((c) => c.table.toLowerCase() === folded && c.table.toLowerCase() !== current?.toLowerCase())) {
    return `Eine Tabelle „${cleaned}“ gibt es bereits.`
  }
  return null
}

export function validateColumnName(name: string, fields: FieldDef[], current?: string): string | null {
  const cleaned = normalizeName(name)
  if (!cleaned) return 'Bitte einen Spaltennamen eingeben.'
  if (cleaned.length > 64) return 'Höchstens 64 Zeichen.'
  if (!/^[\x20-\x7E]+$/.test(cleaned)) {
    return 'Keine Umlaute oder Sonderzeichen – der Spaltenname wird zum Altium-Parameter. Die Beschriftung darf deutsch sein.'
  }
  const bad = [...new Set(cleaned.split('').filter((ch) => FORBIDDEN_COLUMN_CHARS.has(ch)))]
  if (bad.length) return `Nicht erlaubt: ${bad.join(' ')} (stört DbLib bzw. Vorlagen).`
  if (!/^[A-Za-z0-9]/.test(cleaned)) return 'Muss mit einem Buchstaben oder einer Ziffer beginnen.'
  if (/^pf /i.test(cleaned)) return 'Namen mit „PF “ am Anfang sind für PartForge-Verwaltungsfelder reserviert.'
  const folded = cleaned.toLowerCase()
  if (fields.some((f) => f.column.toLowerCase() === folded && f.column.toLowerCase() !== current?.toLowerCase())) {
    return `Das Feld „${cleaned}“ gibt es bereits.`
  }
  return null
}

/** Vorschlag für einen Spaltennamen aus der deutschen Beschriftung („Nennstrom“ → „Nennstrom“, „Größe“ → „Groesse“) */
export function suggestColumn(label: string): string {
  return normalizeName(
    label
      .replace(/ä/g, 'ae')
      .replace(/ö/g, 'oe')
      .replace(/ü/g, 'ue')
      .replace(/Ä/g, 'Ae')
      .replace(/Ö/g, 'Oe')
      .replace(/Ü/g, 'Ue')
      .replace(/ß/g, 'ss')
      .normalize('NFKD')
      .replace(/[^\x20-\x7E]/g, '')
      .replace(/[[\]"'`|=.{}$:;\\]/g, ' '),
  ).slice(0, 64)
}

/** Standard der weichen Längengrenze, wenn `length` leer ist (wie `partforge/db/values.py::length_limit`) */
export function defaultLength(field: Pick<FieldDef, 'column' | 'kind'>): number {
  const special: Record<string, number> = { Description: 1000, Notes: 4000, ComponentLink1URL: 2000 }
  return special[field.column] ?? (field.kind === 'url' ? 2000 : 255)
}
