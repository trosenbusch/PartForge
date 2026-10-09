/**
 * Vorschläge für „Neues Bauteil“: passender Footprint der Bibliothek zur Baugröße (IPC-Namen wie RESC1608X50N für
 * einen 0603-Widerstand) und Erkennung von Hersteller-Teilenummern in der Smart-Eingabe.
 */
import type { FootprintEntry } from '@/api/parts'

/** Zoll-Baugröße → metrischer IPC-Code (0603 → 1608) */
const IMPERIAL_TO_METRIC: Record<string, string> = {
  '01005': '0402',
  '0201': '0603',
  '0402': '1005',
  '0603': '1608',
  '0805': '2012',
  '1206': '3216',
  '1210': '3225',
  '1812': '4532',
  '2010': '5025',
  '2512': '6332',
}

/** IPC-Präfixe der Chip-Footprints je Kategorie */
const CHIP_PREFIX: Record<string, string[]> = {
  Resistors: ['RESC'],
  Capacitors: ['CAPC'],
  Inductors: ['INDC'],
  'Ferrite Beads': ['INDC', 'BEADC', 'FBC'],
  LEDs: ['LEDC'],
  Fuses: ['FUSC'],
  Diodes: ['DIOC'],
  Oscillators: ['XTAL'],
}

/**
 * Footprint aus der Bibliothek, der zur Baugröße passt – der meistverwendete zuerst. `null`, wenn nichts
 * eindeutig passt (dann bleibt die Auswahl beim Nutzer).
 */
export function suggestFootprint(table: string, values: Record<string, string>, footprints: FootprintEntry[]): string | null {
  const size = (values.Size || values.Package || '').trim()
  const metric = IMPERIAL_TO_METRIC[size]
  const prefixes = CHIP_PREFIX[table]
  if (!metric || !prefixes) return null
  const hits = footprints
    .filter((f) => prefixes.some((p) => f.name.toUpperCase().startsWith(`${p}${metric}`)))
    .sort((a, b) => b.usage - a.usage)
  return hits[0]?.name ?? null
}

const MPN_TOKEN = /^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9][A-Za-z0-9\-_.#/+]{4,}$/
/** Messwert-ähnlich (10k, 100nF, 0,1W, 1%) – keine Teilenummer */
const QUANTITY_LIKE = /^[-+]?\d+(?:[.,]\d+)?\s*[pnuµμmkKMGTR]?\d*\s*[A-Za-zΩ%°/]*$/

/** Längstes Wort der Smart-Eingabe, das wie eine Hersteller-Teilenummer aussieht (z. B. „RC0603FR-0710KL“) */
export function mpnCandidate(text: string): string | null {
  const tokens = text
    .split(/[\s,;]+/)
    .map((t) => t.trim())
    .filter((t) => MPN_TOKEN.test(t) && !QUANTITY_LIKE.test(t))
  if (!tokens.length) return null
  return tokens.sort((a, b) => b.length - a.length)[0]
}
