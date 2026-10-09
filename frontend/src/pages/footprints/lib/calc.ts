/**
 * Rechenprotokoll des Footprint-Generators (`FootprintPreview.calc`, freies Objekt) defensiv und vollständig lesen:
 * Lötflächen je Anschlussreihe (Zmax/Gmin/Xmax mit Rohwerten, J-Werten, Eingangsmaßen, Begrenzungen), Toleranzen,
 * Rundung, Courtyard, Namen, Bedrahtet (IPC-2222), BGA. Gleiche Felder wie `partforge/footprints/families/base.py`.
 */

export interface DimRecord {
  min: number
  nom: number
  max: number
  tol: number
}

export interface SpanRecord extends DimRecord {
  minRms: number
  maxRms: number
  tolRms: number
  mode: 'rms' | 'direct'
}

export interface LandRecord {
  label: string
  axis: 'x' | 'y'
  source: 'ipc' | 'manufacturer'
  standard: string
  table: string
  tableKey: string
  tableLabel: string
  toe: number
  heel: number
  side: number
  F: number
  P: number
  L: DimRecord
  T: DimRecord
  W: DimRecord
  S: SpanRecord
  zRaw: number
  gRaw: number
  xRaw: number
  rounding: string
  roundBase: number
  z: number
  g: number
  x: number
  /** gerundet, vor Begrenzungen */
  zRounded: number
  gRounded: number
  xRounded: number
  clamps: string[]
  /** Welche Werte durch Begrenzungen (Mindest-Kupferabstand …) vom gerundeten IPC-Wert abweichen */
  clamped: { z: boolean; g: boolean; x: boolean }
  padLength: number
  padWidth: number
  padCenter: number
}

export interface ThtRecord {
  what: string
  leadSize: number | null
  hole: number | null
  pad: number | null
  padWidth: number | null
  padHeight: number | null
  shape: string | null
  level: string | null
  holeAllowance: number | null
  fabAllowance: number | null
  pitch: number | null
}

export interface BgaRecord {
  ball: number | null
  land: number | null
  collapsible: boolean | null
  rule: string | null
}

export interface CalcRecord {
  family: string | null
  package: string | null
  standard: string | null
  density: string | null
  densityLabel: string | null
  F: number | null
  P: number | null
  roundingMode: string | null
  roundingBase: number[]
  lands: LandRecord[]
  courtyard: { excess: number; grid: number; width: number; height: number } | null
  padCount: number | null
  height: number | null
  ipcName: string | null
  houseName: string | null
  /** Namenszusatz bei eigenen Maßen (z. B. „6E43“) */
  tag: string | null
  /** Vorlage/Standardmaße, denen die Maße entsprechen (null = eigene Maße) */
  standardMatch: string | null
  tht: ThtRecord[]
  bga: BgaRecord | null
  pasteWindows: number | null
}

/**
 * Deutsche Bezeichnungen der J-Tabellen je `table_key` (stabiler Schlüssel aus partforge/footprints/ipc7351.py).
 * Das Backend liefert `table_title` derzeit englisch – unbekannte Schlüssel zeigen dessen Text.
 */
const TABLE_LABELS: Record<string, string> = {
  gullwing: 'Gull-Wing-/L-Anschlüsse, Raster > 0,625 mm',
  gullwing_fine: 'Gull-Wing-/L-Anschlüsse, Raster ≤ 0,625 mm',
  jlead: 'J-Anschlüsse',
  chip: 'Chip-Bauteile ab 0603 (1608)',
  chip_small: 'Chip-Bauteile kleiner 0603 (1608)',
  melf: 'Zylindrische Endkappen (MELF)',
  castellated: 'Castellated-Anschlüsse (LCC)',
  chip_array: 'Chip-Arrays',
  butt: 'Stumpfstoß-Anschlüsse',
  inward_l: 'Nach innen gebogene L-Anschlüsse',
  flat_lug: 'Flache Laschen (Kühlfahnen)',
  qfn: 'QFN (ohne Anschlussbeinchen)',
  son: 'SON/DFN (ohne Anschlussbeinchen)',
  pullback: 'Pull-back-QFN/SON',
  flat_lead: 'Flache Anschlüsse (SOD-F, SOT-89)',
  inward_l_7352: 'Nach innen gebogene L-Anschlüsse (IPC-7352)',
  manufacturer: 'Herstellerempfehlung',
}

type Rec = Record<string, unknown>
const isRec = (v: unknown): v is Rec => Boolean(v) && typeof v === 'object' && !Array.isArray(v)
const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const n0 = (v: unknown): number => num(v) ?? 0
const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v : null)

function dim(v: unknown): DimRecord {
  const r = isRec(v) ? v : {}
  return { min: n0(r.min), nom: n0(r.nom), max: n0(r.max), tol: n0(r.tol) }
}

function span(v: unknown): SpanRecord {
  const r = isRec(v) ? v : {}
  return {
    ...dim(r),
    minRms: n0(r.min_rms),
    maxRms: n0(r.max_rms),
    tolRms: n0(r.tol_rms),
    mode: r.mode === 'direct' ? 'direct' : 'rms',
  }
}

function land(v: unknown): LandRecord | null {
  if (!isRec(v)) return null
  const z = num(v.z)
  const g = num(v.g)
  const x = num(v.x)
  if (z === null || g === null || x === null) return null
  const tableKey = str(v.table_key) ?? ''
  const zr = num(v.z_rounded) ?? z
  const gr = num(v.g_rounded) ?? g
  const xr = num(v.x_rounded) ?? x
  const off = (a: number, b: number) => Math.abs(a - b) > 1e-6
  return {
    label: str(v.label) ?? 'Anschlüsse',
    axis: v.axis === 'y' ? 'y' : 'x',
    source: v.source === 'manufacturer' ? 'manufacturer' : 'ipc',
    standard: str(v.standard) ?? 'IPC-7351B',
    table: str(v.table) ?? '–',
    tableKey,
    tableLabel: TABLE_LABELS[tableKey] ?? str(v.table_title) ?? '',
    toe: n0(v.toe),
    heel: n0(v.heel),
    side: n0(v.side),
    F: n0(v.F),
    P: n0(v.P),
    L: dim(v.L),
    T: dim(v.T),
    W: dim(v.W),
    S: span(v.S),
    zRaw: n0(v.z_raw),
    gRaw: n0(v.g_raw),
    xRaw: n0(v.x_raw),
    rounding: str(v.rounding) ?? '',
    roundBase: n0(v.round_base),
    zRounded: zr,
    gRounded: gr,
    xRounded: xr,
    z,
    g,
    x,
    clamps: Array.isArray(v.clamps) ? v.clamps.filter((c): c is string => typeof c === 'string') : [],
    clamped: { z: off(z, zr), g: off(g, gr), x: off(x, xr) },
    padLength: num(v.pad_length) ?? (z - g) / 2,
    padWidth: num(v.pad_width) ?? x,
    padCenter: num(v.pad_center) ?? (z + g) / 4,
  }
}

function tht(v: unknown): ThtRecord | null {
  if (!isRec(v)) return null
  return {
    what: str(v.what) ?? 'Anschlüsse',
    leadSize: num(v.lead_size),
    hole: num(v.hole),
    pad: num(v.pad),
    padWidth: num(v.pad_width),
    padHeight: num(v.pad_height),
    shape: str(v.shape),
    level: str(v.level),
    holeAllowance: num(v.hole_allowance),
    fabAllowance: num(v.fab_allowance),
    pitch: num(v.pitch),
  }
}

/** `FootprintPreview.calc` lesen (unbekannte Felder werden ignoriert) */
export function readCalc(raw: unknown): CalcRecord | null {
  if (!isRec(raw)) return null
  const rounding = isRec(raw.rounding) ? raw.rounding : {}
  const cy = isRec(raw.courtyard) ? raw.courtyard : null
  const names = isRec(raw.names) ? raw.names : {}
  const bga = isRec(raw.bga) ? raw.bga : null
  return {
    family: str(raw.family),
    package: str(raw.package),
    standard: str(raw.standard),
    density: str(raw.density),
    densityLabel: str(raw.density_label),
    F: num(raw.F),
    P: num(raw.P),
    roundingMode: str(rounding.mode),
    roundingBase: Array.isArray(rounding.base) ? rounding.base.filter((b): b is number => typeof b === 'number') : [],
    lands: Array.isArray(raw.lands) ? raw.lands.map(land).filter((l): l is LandRecord => l !== null) : [],
    courtyard: cy ? { excess: n0(cy.excess), grid: n0(cy.grid), width: n0(cy.width), height: n0(cy.height) } : null,
    padCount: num(raw.pad_count),
    height: num(raw.height),
    ipcName: str(raw.ipc_name) ?? str(names.ipc),
    houseName: str(raw.house_name) ?? str(names.house),
    tag: str(names.tag),
    standardMatch: str(names.standard),
    tht: Array.isArray(raw.tht) ? raw.tht.map(tht).filter((t): t is ThtRecord => t !== null) : [],
    bga: bga
      ? {
          ball: num(bga.ball),
          land: num(bga.land),
          collapsible: typeof bga.collapsible === 'boolean' ? bga.collapsible : null,
          rule: str(bga.rule),
        }
      : null,
    pasteWindows: num(raw.paste_windows),
  }
}

/**
 * Dichte nach IPC-7351 – **ein** Wortlaut in der ganzen App (Footprints, Hausstil, Namensregeln, Bibliothek):
 * „Klein (L) · Nominal (N) · Groß (M)“, immer in dieser Reihenfolge (IPC: Least · Nominal · Most).
 */
export const DENSITY_ORDER = ['L', 'N', 'M'] as const
export type DensityCode = (typeof DENSITY_ORDER)[number]

export const DENSITY_INFO: Record<DensityCode, { name: string; level: string; text: string }> = {
  L: {
    name: 'Klein',
    level: 'Level C',
    text: 'Kleine Lötflächen für hohe Bestückungsdichte.',
  },
  N: {
    name: 'Nominal',
    level: 'Level B',
    text: 'Ausgewogene Lötflächen – Standard für die meisten Baugruppen.',
  },
  M: {
    name: 'Groß',
    level: 'Level A',
    text: 'Große Lötflächen – robust, gut für Handlöten.',
  },
}

/** „Klein (L)“, „Nominal (N)“, „Groß (M)“ – unbekannte Werte unverändert */
export function densityLabel(density: string | null | undefined): string {
  if (!density) return '–'
  const info = DENSITY_INFO[density as DensityCode] as (typeof DENSITY_INFO)[DensityCode] | undefined
  return info ? `${info.name} (${density})` : density
}

export const ROUNDING_LABEL: Record<string, string> = {
  kicad: 'KiCad',
  ipc: 'IPC',
  none: 'keine',
}
