/**
 * Anfragen und Beispieldaten für die Demos der geteilten Komponenten im UI-Kit.
 * Die Vorschauen kommen **live vom Backend** (Generatoren) – hier stehen nur die Anfragen.
 */
import type { FootprintRequest, SymbolRequest } from '@/lib/geometry'

/** SOIC-8 (JEDEC MS-012) – identisch mit dem Generator-Preset „SOIC-8“ */
export const SOIC8_REQUEST: FootprintRequest = {
  family: 'gullwing',
  density: 'N',
  with_3d: true,
  params: {
    variant: 'SOIC',
    pins: 8,
    e: 1.27,
    E: { min: 5.8, max: 6.2 },
    E1: { min: 3.8, max: 4.0 },
    L: { min: 0.4, max: 1.27 },
    b: { min: 0.31, max: 0.51 },
    A: { min: 1.35, max: 1.75 },
    A1: { min: 0.1, max: 0.25 },
    c: { min: 0.1, max: 0.25 },
    D: { min: 4.8, max: 5.0 },
  },
}

/** QFN-16 3×3 mm, Raster 0,5 mm, mit Exposed Pad 1,75 mm */
export const QFN16_REQUEST: FootprintRequest = {
  family: 'nolead',
  density: 'N',
  with_3d: true,
  params: {
    variant: 'QFN',
    pins: 16,
    e: 0.5,
    E: { min: 2.95, max: 3.05 },
    L: { min: 0.3, max: 0.5 },
    b: { min: 0.18, max: 0.3 },
    E2: { min: 1.65, max: 1.85 },
    D2: { min: 1.65, max: 1.85 },
    A: { min: 0.7, max: 0.8 },
    A1: { min: 0.0, max: 0.05 },
  },
}

export const OPAMP_DUAL_REQUEST: SymbolRequest = { kind: 'opamp_dual' }

const bar = (name: string) =>
  name
    .split('')
    .map((c) => `${c}\\`)
    .join('')

type DemoPin = { designator: string; name: string; electrical: NonNullable<SymbolRequest['pins']>[number]['electrical']; hidden?: boolean }
const pin = (p: DemoPin) => ({ part: 1, hidden: false, ...p })

/** Demo-IC mit 17 Pins (QFN-16 + Exposed Pad): Versorgung, SPI/I²C, invertierte Signale, verborgener NC-Pin */
export const DEMO_IC_REQUEST: SymbolRequest = {
  kind: 'ic',
  name: 'PF-DEMO-16',
  description: 'Demo-Sensor-IC mit SPI/I²C (QFN-16, EP)',
  pins: ([
    { designator: '1', name: 'VDD', electrical: 'power' },
    { designator: '2', name: 'VDDIO', electrical: 'power' },
    { designator: '3', name: bar('RESET'), electrical: 'input' },
    { designator: '4', name: 'EN', electrical: 'input' },
    { designator: '5', name: 'SCL', electrical: 'input' },
    { designator: '6', name: 'SDA', electrical: 'io' },
    { designator: '7', name: bar('CS'), electrical: 'input' },
    { designator: '8', name: 'SCK', electrical: 'input' },
    { designator: '9', name: 'MOSI', electrical: 'input' },
    { designator: '10', name: 'MISO', electrical: 'output' },
    { designator: '11', name: bar('INT'), electrical: 'open_collector' },
    { designator: '12', name: 'OUT', electrical: 'output' },
    { designator: '13', name: 'ADC0', electrical: 'input' },
    { designator: '14', name: 'ADC1', electrical: 'input' },
    { designator: '15', name: 'GND', electrical: 'power' },
    { designator: '16', name: 'NC', electrical: 'passive', hidden: true },
    { designator: '17', name: 'EP', electrical: 'power' },
  ] satisfies DemoPin[]).map(pin),
}
