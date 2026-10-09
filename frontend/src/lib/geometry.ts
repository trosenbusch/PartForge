/**
 * Geometrie-Vertrag für Symbole und Footprints – Typen aus dem OpenAPI-Schema (`schema.d.ts`, gespiegelt aus
 * `partforge/geometry/model.py`) plus Helfer für Vorschau-Leinwände, Tabellen und 3D.
 *
 * Konventionen (wie im Backend):
 * - Symbole in **mil** (1/1000 Zoll), +X rechts, +Y oben. `SymPin.x/y` = Körperende des Pins, `orientation` zeigt
 *   **nach außen** („left“ → Anschlussspitze bei x − length). Teil 0 = in allen Teilen sichtbar.
 * - Footprints in **mm**, +X rechts, +Y oben (Draufsicht), Ursprung = Gehäusemitte, Drehung in Grad gegen den
 *   Uhrzeigersinn. 3D-Körper = extrudierte Prismen (Umriss in XY, z_bottom … z_top).
 * - Active-low-Namen in Altium-Syntax: Backslash **nach** dem Zeichen (`R\E\S\E\T\`).
 */
import type { components } from '@/api/schema'

type S = components['schemas']

// --------------------------------------------------------------------------- Typen (aus dem Schema)

export type Point = S['Point']
export type FootprintLink = S['FootprintLink']

export type SymbolSpec = S['SymbolSpec']
export type SymPin = S['SymPin']
export type SymRect = S['SymRect']
export type SymLine = S['SymLine']
export type SymPolygon = S['SymPolygon']
export type SymArc = S['SymArc']
export type SymEllipse = S['SymEllipse']
export type SymText = S['SymText']
export type SymGraphic = NonNullable<SymbolSpec['graphics']>[number]
export type TextPos = S['TextPos']
export type ElectricalType = SymPin['electrical']
export type PinOrientation = SymPin['orientation']
export type PinDecoration = NonNullable<SymPin['inner_edge']>
export type TextJustify = SymText['justify']
export type LineWidth = SymRect['line_width']

/**
 * Footprint-Spezifikation. `step` ist gelockert (Zahlenlisten statt Tupel), damit sowohl Schema-Objekte als auch
 * `Filled<…>`-Antworten passen (`Filled` macht aus Tupeln Arrays).
 */
export type FootprintSpec = Omit<S['FootprintSpec'], 'step'> & { step?: StepModelLike | null }
/** STEP-Verweis wie im Schema, Tupel als Zahlenlisten */
export interface StepModelLike {
  file: string
  rotation?: number[]
  offset?: number[]
}
export type Pad = S['Pad']
export type PadShape = Pad['shape']
export type PadSide = Pad['side']
export type Track = S['Track']
export type Arc = S['Arc']
export type Region = S['Region']
export type FpText = S['FpText']
export type Body3D = S['Body3D']
export type StepModel = S['StepModel']
/** Logische Footprint-Lage (Abbildung auf Altium-Lagen über die `LayerMap` der Bibliothek) */
export type FpLayer = Track['layer']

export type SymbolRequest = S['SymbolRequest']
export type SymbolPreview = S['SymbolPreview']
export type FootprintRequest = S['FootprintRequest']
export type FootprintPreview = S['FootprintPreviewOut']
export type CheckIssue = S['CheckIssue']

// --------------------------------------------------------------------------- Einheiten

export const MM_PER_MIL = 0.0254
export const MIL_PER_MM = 1 / MM_PER_MIL

export const milToMm = (mil: number): number => mil * MM_PER_MIL
export const mmToMil = (mm: number): number => mm * MIL_PER_MM

const mmFormats = new Map<number, Intl.NumberFormat>()

/** 1.27 → „1,27“ (feste Nachkommastellen, deutsches Komma, echtes Minuszeichen) */
export function formatMm(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '–'
  let f = mmFormats.get(digits)
  if (!f) {
    f = new Intl.NumberFormat('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    mmFormats.set(digits, f)
  }
  const rounded = Math.abs(value) < 0.5 * 10 ** -digits ? 0 : value
  return f.format(rounded).replace('-', '−')
}

/** Länge mit Einheit: „1,27 mm“ (geschütztes Leerzeichen) */
export const formatLength = (mm: number, digits = 2): string => `${formatMm(mm, digits)} mm`

/** mil als Text: „200 mil“ */
export const formatMil = (mil: number): string => `${Math.round(mil).toLocaleString('de-DE')} mil`

// --------------------------------------------------------------------------- Rechtecke (Bounding Boxes)

export interface Box {
  x1: number
  y1: number
  x2: number
  y2: number
}

export const emptyBox = (): Box => ({ x1: Infinity, y1: Infinity, x2: -Infinity, y2: -Infinity })
export const isEmptyBox = (b: Box): boolean => !(b.x1 <= b.x2 && b.y1 <= b.y2)

export function boxAdd(b: Box, x: number, y: number): Box {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return b
  b.x1 = Math.min(b.x1, x)
  b.y1 = Math.min(b.y1, y)
  b.x2 = Math.max(b.x2, x)
  b.y2 = Math.max(b.y2, y)
  return b
}

export function boxAddBox(b: Box, o: Box): Box {
  if (isEmptyBox(o)) return b
  boxAdd(b, o.x1, o.y1)
  return boxAdd(b, o.x2, o.y2)
}

export const boxExpand = (b: Box, d: number): Box => ({ x1: b.x1 - d, y1: b.y1 - d, x2: b.x2 + d, y2: b.y2 + d })
export const boxWidth = (b: Box): number => (isEmptyBox(b) ? 0 : b.x2 - b.x1)
export const boxHeight = (b: Box): number => (isEmptyBox(b) ? 0 : b.y2 - b.y1)
export const boxCenter = (b: Box): Point => ({ x: (b.x1 + b.x2) / 2, y: (b.y1 + b.y2) / 2 })

// --------------------------------------------------------------------------- Überstrich (Altium-Syntax)

export interface OverbarChar {
  ch: string
  barred: boolean
}

/**
 * Altium-Pinname in (Zeichen, überstrichen)-Paare zerlegen: `R\E\S\E\T\` → alle fünf Zeichen überstrichen,
 * `C\S\/A` → C und S. Backslashes, die keinem Zeichen folgen, werden ignoriert (wie im Backend).
 */
export function parseOverbar(name: string): OverbarChar[] {
  const out: OverbarChar[] = []
  let i = 0
  while (i < name.length) {
    const ch = name[i]
    if (ch === '\\') {
      i += 1
      continue
    }
    const barred = i + 1 < name.length && name[i + 1] === '\\'
    out.push({ ch, barred })
    i += barred ? 2 : 1
  }
  return out
}

export interface OverbarSegment {
  text: string
  barred: boolean
}

/** Zusammenhängende Abschnitte: `R\S\T` → [{text:'RS', barred:true}, {text:'T', barred:false}] */
export function overbarSegments(name: string): OverbarSegment[] {
  const segments: OverbarSegment[] = []
  for (const { ch, barred } of parseOverbar(name)) {
    const last = segments[segments.length - 1]
    if (last && last.barred === barred) last.text += ch
    else segments.push({ text: ch, barred })
  }
  return segments
}

/** Sichtbarer Text ohne Backslashes */
export const displayText = (name: string): string => parseOverbar(name).map((c) => c.ch).join('')
export const hasOverbar = (name: string): boolean => parseOverbar(name).some((c) => c.barred)

/** Für Screenreader: „RESET (invertiert)“ bzw. „C S (teilweise invertiert) …“ */
export function spokenPinName(name: string): string {
  const text = displayText(name)
  if (!hasOverbar(name)) return text
  const all = parseOverbar(name).every((c) => c.barred)
  return `${text} (${all ? 'invertiert' : 'teilweise invertiert'})`
}

// --------------------------------------------------------------------------- Symbole

export const ELECTRICAL_LABEL: Record<ElectricalType, string> = {
  input: 'Eingang',
  output: 'Ausgang',
  io: 'Ein-/Ausgang',
  passive: 'Passiv',
  power: 'Versorgung',
  open_collector: 'Open Collector',
  open_emitter: 'Open Emitter',
  hiz: 'Hochohmig (Tri-State)',
}

export const electricalLabel = (type: ElectricalType | null | undefined): string =>
  type ? (ELECTRICAL_LABEL[type] ?? type) : '–'

const ORIENTATION_VECTOR: Record<PinOrientation, [number, number]> = {
  left: [-1, 0],
  right: [1, 0],
  up: [0, 1],
  down: [0, -1],
}

/** Richtung des Pins nach außen (Einheitsvektor) */
export const pinDirection = (o: PinOrientation): [number, number] => ORIENTATION_VECTOR[o] ?? [-1, 0]

/** Anschlussspitze (Hot Spot) eines Pins */
export function pinTip(pin: Pick<SymPin, 'x' | 'y' | 'orientation' | 'length'>): Point {
  const [dx, dy] = pinDirection(pin.orientation)
  const length = pin.length ?? 200
  return { x: pin.x + dx * length, y: pin.y + dy * length }
}

const PART_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

/** 1 → „A“, 2 → „B“ … (wie Altium) */
export const partLetter = (part: number): string =>
  part >= 1 && part <= PART_LETTERS.length ? PART_LETTERS[part - 1] : String(part)

/** Primitive eines Teils (Teil 0 = in allen Teilen) */
export const inPart = (itemPart: number | undefined, part: number): boolean => {
  const p = itemPart ?? 1
  return p === 0 || p === part
}

export function symbolPins(spec: SymbolSpec, part?: number, includeHidden = false): SymPin[] {
  return (spec.pins ?? []).filter((p) => (part === undefined || inPart(p.part, part)) && (includeHidden || !p.hidden))
}

/** Grobe Textbreite (mil) für Begrenzungsrahmen: Times New Roman ~0,6 em je Zeichen bei 10 pt (em = 100 mil). */
export function estimateTextWidth(text: string, emMil = 100): number {
  return displayText(text).length * emMil * 0.6
}

/** Begrenzungsrahmen eines Symbol-Teils (mil) – Pins (Körperende + Spitze) und Grafiken, optional ohne Texte. */
export function symbolBBox(spec: SymbolSpec, part?: number, opts: { includeHidden?: boolean } = {}): Box {
  const b = emptyBox()
  for (const p of spec.pins ?? []) {
    if (part !== undefined && !inPart(p.part, part)) continue
    if (p.hidden && !opts.includeHidden) continue
    const tip = pinTip(p)
    boxAdd(b, p.x, p.y)
    boxAdd(b, tip.x, tip.y)
  }
  for (const g of spec.graphics ?? []) {
    if (part !== undefined && !inPart(g.part, part)) continue
    switch (g.kind) {
      case 'rect':
        boxAdd(b, g.x1, g.y1)
        boxAdd(b, g.x2, g.y2)
        break
      case 'line':
      case 'polygon':
        for (const pt of g.points) boxAdd(b, pt.x, pt.y)
        break
      case 'arc':
        boxAdd(b, g.cx - g.r, g.cy - g.r)
        boxAdd(b, g.cx + g.r, g.cy + g.r)
        break
      case 'ellipse':
        boxAdd(b, g.cx - g.rx, g.cy - g.ry)
        boxAdd(b, g.cx + g.rx, g.cy + g.ry)
        break
      case 'text':
        boxAdd(b, g.x, g.y)
        break
    }
  }
  return b
}

export interface SymbolLabelPos {
  x: number
  y: number
  justify: TextJustify
}

const JUSTIFY_VALUES = new Set<string>([
  'bottom_left',
  'bottom_center',
  'bottom_right',
  'middle_left',
  'middle_center',
  'middle_right',
  'top_left',
  'top_center',
  'top_right',
])

function asLabelPos(raw: unknown): SymbolLabelPos | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as { x?: unknown; y?: unknown; justify?: unknown }
  const x = Number(r.x)
  const y = Number(r.y)
  if (!Number.isFinite(x) || !Number.isFinite(y) || Math.abs(x) > 1e6 || Math.abs(y) > 1e6) return null
  const justify = typeof r.justify === 'string' && JUSTIFY_VALUES.has(r.justify) ? (r.justify as TextJustify) : 'bottom_left'
  return { x, y, justify }
}

/**
 * Position von Bezeichner („U?“) und Kommentar wie im Backend-Renderer: Vertragsfelder `designator_pos`/`comment_pos`,
 * sonst `generator.text_positions`, sonst links über/unter dem Körper.
 */
export function symbolLabelPositions(spec: SymbolSpec, part = 1): { designator: SymbolLabelPos; comment: SymbolLabelPos } {
  const generator = spec.generator && typeof spec.generator === 'object' ? (spec.generator as Record<string, unknown>) : {}
  const positions = (generator.text_positions && typeof generator.text_positions === 'object'
    ? generator.text_positions
    : {}) as Record<string, unknown>
  const box = symbolBBox(spec, part)
  const x1 = isEmptyBox(box) ? 0 : box.x1
  const y1 = isEmptyBox(box) ? 0 : box.y1
  const y2 = isEmptyBox(box) ? 0 : box.y2
  return {
    designator: asLabelPos(spec.designator_pos) ??
      asLabelPos(positions.designator) ?? { x: x1, y: y2 + 30, justify: 'bottom_left' },
    comment: asLabelPos(spec.comment_pos) ?? asLabelPos(positions.comment) ?? { x: x1, y: y1 - 96, justify: 'bottom_left' },
  }
}

/** Platzhalter-Bezeichner eines Teils: „U?A“ (mehrteilig) bzw. „R?“ */
export function designatorPlaceholder(spec: SymbolSpec, part = 1): string {
  const prefix = spec.designator_prefix || 'U'
  return `${prefix}?${(spec.part_count ?? 1) > 1 ? partLetter(part) : ''}`
}

// --------------------------------------------------------------------------- Footprints: Lagen

/** Lagen der Footprint-Leinwand: logische Lagen + „multi_layer“ für durchkontaktierte Pads */
export type CanvasLayer = FpLayer | 'multi_layer'

export interface LayerMeta {
  id: CanvasLayer
  /** Deutsche Bezeichnung */
  label: string
  /** Altium-Lage (Standard-LayerMap der Bibliothek) */
  altium: string
  /** CSS-Variable aus dem Designsystem, falls es ein Token gibt (SVG: `var(--pf-pcb-…)`) */
  cssVar?: string
  /** Farbe je Theme (für three.js, Canvas, Legenden) – die Leiterplatten-Leinwand ist in beiden Themes dunkel */
  color: { dark: string; light: string }
  /** Zeichenreihenfolge (klein = unten) */
  order: number
  /** Standardmäßig sichtbar */
  visible: boolean
  /** Gestrichelt gezeichnet (Courtyard) */
  dashed?: boolean
}

const meta = (
  id: CanvasLayer,
  label: string,
  altium: string,
  color: string,
  order: number,
  visible: boolean,
  extra: Partial<LayerMeta> = {},
): LayerMeta => ({ id, label, altium, color: { dark: color, light: color }, order, visible, ...extra })

/** Lagen-Metadaten (Farben aus FRONTEND.md §3 bzw. den `--pf-pcb-*`-Tokens) */
export const LAYERS: Record<CanvasLayer, LayerMeta> = {
  body3d: meta('body3d', '3D‑Körper', 'Mechanical 13', '#3DD68C', 0, false, { cssVar: '--pf-pcb-body' }),
  component_outline: meta('component_outline', 'Bauteilumriss', 'Mechanical 21', '#5E6B7D', 1, false),
  courtyard: meta('courtyard', 'Courtyard', 'Mechanical 15', '#D16BFF', 2, true, { cssVar: '--pf-pcb-courtyard', dashed: true }),
  assembly: meta('assembly', 'Bestückungszeichnung', 'Mechanical 9', '#6FA8FF', 3, true, { cssVar: '--pf-pcb-assembly' }),
  component_center: meta('component_center', 'Bauteilmitte', 'Mechanical 17', '#7D8794', 4, true),
  keepout: meta('keepout', 'Sperrfläche', 'Keep-Out Layer', '#FF4FD8', 5, true),
  bottom_mask: meta('bottom_mask', 'Lötstopp unten', 'Bottom Solder', '#6A5AAE', 6, false),
  bottom_paste: meta('bottom_paste', 'Lotpaste unten', 'Bottom Paste', '#8D96A8', 7, false),
  bottom_copper: meta('bottom_copper', 'Kupfer unten', 'Bottom Layer', '#4C7DFF', 8, true, { cssVar: '--pf-pcb-bottom' }),
  bottom_silk: meta('bottom_silk', 'Bestückungsdruck unten', 'Bottom Overlay', '#B9A23A', 9, true),
  top_copper: meta('top_copper', 'Kupfer oben', 'Top Layer', '#E5484D', 10, true, { cssVar: '--pf-pcb-top' }),
  multi_layer: meta('multi_layer', 'Durchsteck-Pads', 'Multi-Layer', '#C9CED8', 11, true, { cssVar: '--pf-pcb-multi' }),
  top_mask: meta('top_mask', 'Lötstopp oben', 'Top Solder', '#7C5CC4', 12, false),
  top_paste: meta('top_paste', 'Lotpaste oben', 'Top Paste', '#8D96A8', 13, false, { cssVar: '--pf-pcb-paste' }),
  top_silk: meta('top_silk', 'Bestückungsdruck', 'Top Overlay', '#F2D14B', 14, true, { cssVar: '--pf-pcb-silk' }),
  designator: meta('designator', 'Bezeichner', 'Mechanical 11', '#9AA4B2', 15, false),
  comment: meta('comment', 'Kommentar', 'Mechanical 19', '#7D8794', 16, false),
}

export const LAYER_ORDER: CanvasLayer[] = (Object.values(LAYERS) as LayerMeta[])
  .sort((a, b) => a.order - b.order)
  .map((l) => l.id)

/** Farbe einer Lage für das gewählte Theme (Hex) */
export const layerColor = (layer: CanvasLayer, theme: 'dark' | 'light' = 'dark'): string =>
  LAYERS[layer]?.color[theme] ?? '#888888'

/** Farbe für SVG: Token (`var(--pf-pcb-…)`) mit Hex-Rückfall bzw. Hex */
export const layerFill = (layer: CanvasLayer): string => {
  const m = LAYERS[layer]
  if (!m) return '#888888'
  return m.cssVar ? `var(${m.cssVar}, ${m.color.dark})` : m.color.dark
}

/** Deutsche Bezeichnung einer Lage */
export const layerLabel = (layer: CanvasLayer): string => LAYERS[layer]?.label ?? layer

/** Farbe der Bohrung (Leinwand) */
export const DRILL_COLOR = '#05070A'
/** Leinwand der Leiterplatte (beide Themes) */
export const BOARD_COLOR = '#05070A'

/** Lage eines Pads: durchkontaktiert → multi_layer */
export function padLayer(pad: Pad): CanvasLayer {
  if (pad.side === 'through' || (pad.hole ?? 0) > 0) return 'multi_layer'
  return pad.side === 'bottom' ? 'bottom_copper' : 'top_copper'
}

export const PAD_SHAPE_LABEL: Record<PadShape, string> = {
  rect: 'Rechteck',
  roundrect: 'Rechteck, abgerundet',
  circle: 'Rund',
  oval: 'Oval',
  octagon: 'Achteck',
}

export const PAD_SIDE_LABEL: Record<PadSide, string> = {
  top: 'oben (SMD)',
  bottom: 'unten (SMD)',
  through: 'durchkontaktiert',
}

/** Eckenradius eines Pads in mm (roundrect: Altium-% vom halben kürzeren Maß, Standard 50 %) */
export function padCornerRadius(pad: Pad): number {
  const half = Math.min(pad.width, pad.height) / 2
  switch (pad.shape) {
    case 'circle':
    case 'oval':
      return half
    case 'roundrect':
      return (half * (pad.corner_radius_pct ?? 50)) / 100
    default:
      return 0
  }
}

/**
 * Umriss eines Pads als Polygon in **lokalen** Koordinaten (Mitte = 0/0, vor der Drehung) – für 3D und Hit-Tests.
 * `segments` = Stützpunkte je Viertelkreis.
 */
export function padOutline(pad: Pad, segments = 6): Point[] {
  const w = pad.width / 2
  const h = pad.height / 2
  if (pad.shape === 'octagon') {
    const c = Math.min(pad.width, pad.height) * (1 - 1 / (1 + Math.SQRT2)) / 2
    return [
      { x: -w + c, y: -h },
      { x: w - c, y: -h },
      { x: w, y: -h + c },
      { x: w, y: h - c },
      { x: w - c, y: h },
      { x: -w + c, y: h },
      { x: -w, y: h - c },
      { x: -w, y: -h + c },
    ]
  }
  const r = Math.min(padCornerRadius(pad), w, h)
  if (r <= 1e-6) {
    return [
      { x: -w, y: -h },
      { x: w, y: -h },
      { x: w, y: h },
      { x: -w, y: h },
    ]
  }
  const pts: Point[] = []
  const corners: [number, number, number][] = [
    [w - r, -h + r, -90],
    [w - r, h - r, 0],
    [-w + r, h - r, 90],
    [-w + r, -h + r, 180],
  ]
  for (const [cx, cy, start] of corners) {
    for (let i = 0; i <= segments; i++) {
      const a = ((start + (90 * i) / segments) * Math.PI) / 180
      pts.push({ x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) })
    }
  }
  return pts
}

/** Ausdehnung eines gedrehten Pads (halbe Breite/Höhe der achsparallelen Hülle) */
export function padExtent(pad: Pad): { ex: number; ey: number } {
  const rad = ((pad.rotation ?? 0) * Math.PI) / 180
  const hw = pad.width / 2
  const hh = pad.height / 2
  return {
    ex: Math.abs(hw * Math.cos(rad)) + Math.abs(hh * Math.sin(rad)),
    ey: Math.abs(hw * Math.sin(rad)) + Math.abs(hh * Math.cos(rad)),
  }
}

/** Liegt der Punkt (mm, Footprint-Koordinaten) auf dem Pad? */
export function pointInPad(pad: Pad, x: number, y: number): boolean {
  const rad = (-(pad.rotation ?? 0) * Math.PI) / 180
  const dx = x - pad.x
  const dy = y - pad.y
  const lx = dx * Math.cos(rad) - dy * Math.sin(rad)
  const ly = dx * Math.sin(rad) + dy * Math.cos(rad)
  return Math.abs(lx) <= pad.width / 2 && Math.abs(ly) <= pad.height / 2
}

export interface FootprintBBoxOptions {
  /** Nur diese Lagen berücksichtigen (Standard: alle) */
  layers?: Iterable<CanvasLayer>
  /** 3D-Körper einbeziehen (Standard: ja) */
  bodies?: boolean
  /** Texte (.Designator usw.) einbeziehen (Standard: nein) */
  texts?: boolean
}

/** Begrenzungsrahmen eines Footprints (mm) inkl. Strichbreiten */
export function footprintBBox(spec: FootprintSpec, opts: FootprintBBoxOptions = {}): Box {
  const only = opts.layers ? new Set(opts.layers) : null
  const on = (layer: CanvasLayer) => !only || only.has(layer)
  const b = emptyBox()
  for (const p of spec.pads ?? []) {
    if (!on(padLayer(p))) continue
    const { ex, ey } = padExtent(p)
    boxAdd(b, p.x - ex, p.y - ey)
    boxAdd(b, p.x + ex, p.y + ey)
  }
  for (const t of spec.tracks ?? []) {
    if (!on(t.layer)) continue
    const w = t.width / 2
    boxAdd(b, Math.min(t.x1, t.x2) - w, Math.min(t.y1, t.y2) - w)
    boxAdd(b, Math.max(t.x1, t.x2) + w, Math.max(t.y1, t.y2) + w)
  }
  for (const a of spec.arcs ?? []) {
    if (!on(a.layer)) continue
    const r = a.r + a.width / 2
    boxAdd(b, a.cx - r, a.cy - r)
    boxAdd(b, a.cx + r, a.cy + r)
  }
  for (const rg of spec.regions ?? []) {
    if (!on(rg.layer)) continue
    for (const pt of rg.points) boxAdd(b, pt.x, pt.y)
  }
  if (opts.bodies !== false && on('body3d')) {
    for (const body of spec.bodies ?? []) for (const pt of body.outline) boxAdd(b, pt.x, pt.y)
  }
  if (opts.texts) {
    for (const t of spec.texts ?? []) {
      if (!on(t.layer)) continue
      const h = t.height ?? 1
      const w = t.text.length * h * 0.6
      boxAdd(b, t.x - w / 2, t.y - h / 2)
      boxAdd(b, t.x + w / 2, t.y + h / 2)
    }
  }
  return b
}

/** Lagen, die im Footprint tatsächlich vorkommen (in Zeichenreihenfolge) */
export function footprintLayers(spec: FootprintSpec): CanvasLayer[] {
  const used = new Set<CanvasLayer>()
  for (const p of spec.pads ?? []) {
    used.add(padLayer(p))
    if (p.paste !== false && padLayer(p) !== 'multi_layer') used.add(p.side === 'bottom' ? 'bottom_paste' : 'top_paste')
  }
  for (const t of spec.tracks ?? []) used.add(t.layer)
  for (const a of spec.arcs ?? []) used.add(a.layer)
  for (const r of spec.regions ?? []) used.add(r.layer)
  for (const t of spec.texts ?? []) used.add(t.layer)
  if ((spec.bodies ?? []).length) used.add('body3d')
  return LAYER_ORDER.filter((l) => used.has(l))
}

/** Höhe der 3D-Körper (z_top max., mm) */
export function bodiesHeight(spec: FootprintSpec): number {
  let h = 0
  for (const body of spec.bodies ?? []) h = Math.max(h, body.z_top)
  return h || spec.height || 0
}

// --------------------------------------------------------------------------- Rechenprotokoll des Generators

/** Landefläche einer Anschlussreihe (IPC-7351: Zmax/Gmin/Xmax) */
export interface LandCalc {
  label?: string
  /** Achse der Anschlussreihe: x = Pads links/rechts, y = oben/unten */
  axis: 'x' | 'y'
  /** Zmax: Außenmaß über die Pads (mm) */
  z: number
  /** Gmin: Innenabstand zwischen den Pads (mm, ≤ 0 = durchgehend) */
  g: number
  /** Xmax: Padbreite quer zur Achse (mm) */
  x: number
  pad_length?: number
  pad_width?: number
  pad_center?: number
  source?: string
}

export interface ThtCalc {
  what?: string
  hole?: number
  pad?: number
  pad_width?: number
  pad_height?: number
  pitch?: number
  pitch_axis?: 'x' | 'y'
}

/** Getypte Sicht auf `FootprintPreview.calc` (das Backend liefert ein freies Objekt) */
export interface FootprintCalc {
  lands: LandCalc[]
  tht: ThtCalc[]
  courtyard: Box | null
  bga: { ball?: number; land?: number } | null
  height: number | null
  ipcName: string | null
  density: string | null
  densityLabel: string | null
  package: string | null
}

const num = (v: unknown): number | undefined => (typeof v === 'number' && Number.isFinite(v) ? v : undefined)

/** Rechenprotokoll defensiv lesen (unbekannte Felder werden ignoriert) */
export function parseFootprintCalc(raw: unknown): FootprintCalc | null {
  if (!raw || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const lands: LandCalc[] = []
  if (Array.isArray(r.lands)) {
    for (const item of r.lands) {
      if (!item || typeof item !== 'object') continue
      const l = item as Record<string, unknown>
      const z = num(l.z)
      const g = num(l.g)
      const x = num(l.x)
      if (z === undefined || g === undefined || x === undefined) continue
      lands.push({
        label: typeof l.label === 'string' ? l.label : undefined,
        axis: l.axis === 'y' ? 'y' : 'x',
        z,
        g,
        x,
        pad_length: num(l.pad_length),
        pad_width: num(l.pad_width),
        pad_center: num(l.pad_center),
        source: typeof l.source === 'string' ? l.source : undefined,
      })
    }
  }
  const tht: ThtCalc[] = []
  if (Array.isArray(r.tht)) {
    for (const item of r.tht) {
      if (!item || typeof item !== 'object') continue
      const t = item as Record<string, unknown>
      tht.push({
        what: typeof t.what === 'string' ? t.what : undefined,
        hole: num(t.hole),
        pad: num(t.pad),
        pad_width: num(t.pad_width),
        pad_height: num(t.pad_height),
        pitch: num(t.pitch),
        pitch_axis: t.pitch_axis === 'y' ? 'y' : t.pitch_axis === 'x' ? 'x' : undefined,
      })
    }
  }
  let courtyard: Box | null = null
  if (r.courtyard && typeof r.courtyard === 'object') {
    const c = r.courtyard as Record<string, unknown>
    const x1 = num(c.x1)
    const y1 = num(c.y1)
    const x2 = num(c.x2)
    const y2 = num(c.y2)
    if (x1 !== undefined && y1 !== undefined && x2 !== undefined && y2 !== undefined) courtyard = { x1, y1, x2, y2 }
  }
  const bgaRaw = r.bga && typeof r.bga === 'object' ? (r.bga as Record<string, unknown>) : null
  return {
    lands,
    tht,
    courtyard,
    bga: bgaRaw ? { ball: num(bgaRaw.ball), land: num(bgaRaw.land) } : null,
    height: num(r.height) ?? null,
    ipcName: typeof r.ipc_name === 'string' ? r.ipc_name : null,
    density: typeof r.density === 'string' ? r.density : null,
    densityLabel: typeof r.density_label === 'string' ? r.density_label : null,
    package: typeof r.package === 'string' ? r.package : null,
  }
}

// --------------------------------------------------------------------------- Sonstiges

const collator = new Intl.Collator('de-DE', { numeric: true, sensitivity: 'base' })

/** Natürliche Sortierung von Pin-/Pad-Nummern: 1, 2, 10, A1, A2, B1 … */
export const naturalCompare = (a: string, b: string): number => collator.compare(a, b)
