import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Schaltplansymbol als SVG (mil, +Y oben) – Pins mit Anschlussspitze, Namen (mit Überstrich) und Nummern,
 * alle Grafikarten, Platzhalter für Bezeichner/Kommentar, 100-mil-Punktraster, Zoom/Verschieben/Einpassen,
 * mehrteilige Symbole (Teil A/B/C …, Teil-0-Pins in jedem Teil), Pin-Tooltip und Hervorhebung.
 *
 *   <SymbolCanvas spec={spec} theme="altium" highlight={['3']} />
 */
import {
  memo,
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from 'react'
import { EyeOff } from 'lucide-react'
import { SegmentedControl } from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  designatorPlaceholder,
  displayText,
  electricalLabel,
  emptyBox,
  estimateTextWidth,
  boxAdd,
  boxAddBox,
  inPart,
  isEmptyBox,
  overbarSegments,
  partLetter,
  pinDirection,
  pinTip,
  spokenPinName,
  symbolBBox,
  symbolLabelPositions,
  type Box,
  type SymbolLabelPos,
  type SymGraphic,
  type SymPin,
  type SymbolSpec,
  type TextJustify,
} from '@/lib/geometry'
import { CanvasBadge, CanvasKeyHint, CanvasTooltip, CanvasZoomControls } from './CanvasChrome'
import type { CanvasHandle, SymbolCanvasTheme } from './types'
import { useElementSize } from './useElementSize'
import { gridStep, scaleBucket, usePanZoom } from './usePanZoom'

export interface SymbolCanvasProps {
  spec: SymbolSpec | null | undefined
  /** „auto“ folgt dem App-Theme (Körper Kupfer-Tönung, Linien in Textfarbe), „altium“ = weißes Blatt wie in Altium */
  theme?: SymbolCanvasTheme
  /** Angezeigtes Teil (1 … part_count), kontrolliert */
  part?: number
  defaultPart?: number
  onPartChange?: (part: number) => void
  /** Teil-Umschalter A/B/C … anzeigen (Standard: bei mehrteiligen Symbolen) */
  showPartTabs?: boolean
  /** Pins (Nummern) hervorheben, z. B. aus einer Prüfung oder dem Footprint */
  highlight?: readonly string[]
  /** Von außen hervorgehobener Pin (z. B. beim Überfahren des Pads im Footprint) */
  hoverDesignator?: string | null
  onPinHover?: (pin: SymPin | null) => void
  onPinClick?: (pin: SymPin) => void
  showGrid?: boolean
  /**
   * Verborgene Pins zeigen: gestrichelt an ihrer Stelle – würden sie dort sichtbare Pins, deren Texte, die
   * Symbolkontur oder einander überdecken (z. B. gestapelte Versorgungspins am Nullpunkt), stehen sie stattdessen
   * in der Liste „Verborgen“ oben rechts. Ohne diese Option werden verborgene Pins nie gezeichnet.
   */
  showHiddenPins?: boolean
  /**
   * Nullpunkt (Bauteil-Ursprung) als kleines neutrales Kreuz: `true` = immer, Standard = nur beim Überfahren bzw.
   * mit Tastaturfokus (interaktive Ansicht)
   */
  showOrigin?: boolean
  /** Bezeichner und Kommentar zeichnen */
  showLabels?: boolean
  /** Eigener Bezeichner statt „U?A“ (z. B. „U12“) */
  designator?: string
  /** Eigener Kommentar statt „*“ (z. B. „10k“) */
  comment?: string
  /** Zoomen und Verschieben erlauben */
  interactive?: boolean
  /** Schwebende Zoom-Knöpfe (aus, wenn eine PreviewPanel-Werkzeugleiste steuert) */
  controls?: boolean
  /** Name und Pinzahl unten links */
  showInfo?: boolean
  onZoomChange?: (zoom: number) => void
  /** Neuer Wert → Ansicht neu einpassen (Standard: Symbolname) */
  resetKey?: unknown
  className?: string
  'aria-label'?: string
  ref?: Ref<CanvasHandle>
}

// --------------------------------------------------------------------------- Farben

interface Palette {
  /** Ungefüllte Hauptform (Körper) im App-Theme mit Kupfer-Tönung füllen */
  fillBody: boolean
  background: string
  grid: string
  line: (g: SymGraphic) => string
  fill: (g: SymGraphic, filled: boolean) => { fill: string; opacity?: number }
  text: (g: SymGraphic) => string
  pin: string
  pinName: string
  pinNumber: string
  label: string
  comment: string
  font: string
  nameFont: string
  numberFont: string
  nameWeight: number
  /** Schriftgrößen in mil (Altium: 10 pt = 100 mil) */
  nameSize: number
  numberSize: number
  labelSize: number
}

const STROKE: Record<string, number> = { smallest: 5, small: 10, medium: 20, large: 30 }
const PIN_STROKE = 10
const EM = 100 // mil je 10 pt (Altium-Kalibrierung, siehe partforge/symbols/text.py)
const CAP = 66
const NAME_MARGIN = 50
const NUMBER_OFFSET = 40

const ALTIUM_LINE = '#800000'
const ALTIUM_FILL = '#FFFFB0'
const ALTIUM_TEXT = '#000080'

const isSolid = (g: SymGraphic) => !g.fill_color || (g.fill_color ?? '').toUpperCase() === (g.color ?? '').toUpperCase()

const PALETTES: Record<SymbolCanvasTheme, Palette> = {
  auto: {
    fillBody: true,
    background: 'var(--pf-bg)',
    grid: 'var(--pf-dot)',
    line: () => 'var(--pf-sym-line)',
    fill: (g, filled) => (!filled ? { fill: 'none' } : isSolid(g) ? { fill: 'var(--pf-sym-line)' } : { fill: 'var(--pf-sym-body)' }),
    text: () => 'var(--pf-sym-line)',
    pin: 'var(--pf-fg-muted)',
    pinName: 'var(--pf-sym-pin-name)',
    pinNumber: 'var(--pf-sym-pin-number)',
    label: 'var(--pf-fg)',
    comment: 'var(--pf-fg-muted)',
    font: 'var(--font-sans)',
    nameFont: 'var(--font-sans)',
    numberFont: 'var(--font-mono)',
    nameWeight: 500,
    nameSize: 72,
    numberSize: 60,
    labelSize: 72,
  },
  altium: {
    fillBody: false,
    background: 'var(--pf-altium-sheet)',
    grid: 'rgba(0, 0, 60, 0.16)',
    line: (g) => g.color ?? ALTIUM_LINE,
    fill: (g, filled) => (filled ? { fill: g.fill_color ?? g.color ?? ALTIUM_FILL } : { fill: 'none' }),
    text: (g) => g.color ?? ALTIUM_TEXT,
    pin: 'var(--pf-altium-pin)',
    pinName: '#000000',
    pinNumber: 'var(--pf-altium-pin)',
    label: ALTIUM_TEXT,
    comment: ALTIUM_TEXT,
    font: "'Times New Roman', Times, serif",
    nameFont: "'Times New Roman', Times, serif",
    numberFont: "'Times New Roman', Times, serif",
    nameWeight: 400,
    nameSize: EM,
    numberSize: EM,
    labelSize: EM,
  },
}


// --------------------------------------------------------------------------- Text

const ANCHOR: Record<string, 'start' | 'middle' | 'end'> = { left: 'start', center: 'middle', right: 'end' }

/** Basislinie relativ zum Ankerpunkt (SVG-Y nach unten) je vertikaler Ausrichtung */
function baselineOffset(vertical: string, em: number): number {
  const cap = em * 0.66
  if (vertical === 'top') return cap
  if (vertical === 'middle') return cap / 2
  return -0.2 * em
}

// --------------------------------------------------------------------------- Textmaße (fürs Einpassen)

let measureCtx: CanvasRenderingContext2D | null | undefined
const familyCache = new Map<string, string>()
const widthCache = new Map<string, number>()

/** CSS-Schriftfamilie auflösen (`var(--font-sans)` → „'Inter Variable', …“) – Canvas versteht keine Variablen */
function resolveFontFamily(font: string): string {
  const cached = familyCache.get(font)
  if (cached) return cached
  const m = /^var\((--[\w-]+)\)$/.exec(font.trim())
  if (!m) return font
  if (typeof document === 'undefined') return 'sans-serif'
  const value = getComputedStyle(document.documentElement).getPropertyValue(m[1]).trim()
  if (value) familyCache.set(font, value)
  return value || 'sans-serif'
}

/**
 * Breite eines Texts in mil, so wie die Leinwand ihn zeichnet: Canvas-Messung mit derselben Schrift und Stärke
 * (Großbuchstaben-MPNs wie „LTC6244CDHC#PBF“ sind deutlich breiter als die Faustregel 0,6 em); ohne Canvas eine
 * großzügige Schätzung. Überstrich-Markierungen (`\`) zählen nicht.
 */
function textWidthMil(text: string, sizeMil: number, font: string, weight = 400, cache = true): number {
  const shown = displayText(text)
  if (!shown) return 0
  const family = resolveFontFamily(font)
  const key = `${weight}|${family}|${shown}`
  let per100 = widthCache.get(key)
  if (per100 === undefined) {
    if (measureCtx === undefined) {
      measureCtx = typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null
    }
    if (measureCtx) {
      const spec = `${weight} 100px ${family}`
      measureCtx.font = spec
      per100 = measureCtx.measureText(shown).width
      // Webschriften noch nicht geladen (Ersatzschrift gemessen): nicht merken, nach dem Laden neu messen
      if (cache) widthCache.set(key, per100)
    } else {
      per100 = estimateTextWidth(shown, 100) * 1.2
    }
  }
  return (per100 * sizeMil) / 100
}

/** Ober-/Unterlänge relativ zur Grundlinie (em) – inkl. Überstrich, großzügig für Einpassen und Überdeckung */
const ASCENT = 0.82
const DESCENT = 0.26

/** Rahmen eines Bezeichner-/Kommentartexts (mil, +Y oben) – so, wie `LabelText` ihn zeichnet */
function labelBox(pos: SymbolLabelPos, text: string, pal: Palette, weight?: number, cache = true): Box {
  const size = pal.labelSize
  const w = textWidthMil(text, size, pal.font, weight, cache) * 1.03
  const [vertical, horizontal] = pos.justify.split('_')
  const x1 = horizontal === 'right' ? pos.x - w : horizontal === 'center' ? pos.x - w / 2 : pos.x
  // LabelText setzt die Grundlinie in SVG-Koordinaten auf −y + baselineOffset → in Weltkoordinaten y − baselineOffset
  const base = pos.y - baselineOffset(vertical, size)
  return { x1, x2: x1 + w, y1: base - DESCENT * size, y2: base + ASCENT * size }
}

/** Rahmen einer Text-Grafik (Ausrichtung und Drehung wie in `Graphic`) */
function textGraphicBox(g: Extract<SymGraphic, { kind: 'text' }>, pal: Palette, cache = true): Box {
  const em = (g.size ?? 10) * 10
  const w = textWidthMil(g.text, em, pal.font, 400, cache) * 1.03
  const [vertical, horizontal] = (g.justify ?? 'bottom_left').split('_')
  const x1 = horizontal === 'right' ? -w : horizontal === 'center' ? -w / 2 : 0
  const base = -baselineOffset(vertical, em)
  const rad = ((g.rotation ?? 0) * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  const box = emptyBox()
  for (const [x, y] of [
    [x1, base - DESCENT * em],
    [x1 + w, base - DESCENT * em],
    [x1, base + ASCENT * em],
    [x1 + w, base + ASCENT * em],
  ]) {
    // `rotate(−rotation)` in SVG (Y nach unten) = gegen den Uhrzeigersinn in Weltkoordinaten (Y nach oben)
    boxAdd(box, g.x + x * cos - y * sin, g.y + x * sin + y * cos)
  }
  return box
}

/** Angezeigte Texte von Bezeichner und Kommentar (eigene Texte der Props vor den Platzhaltern) */
function labelTexts(spec: SymbolSpec, part: number, designator?: string, comment?: string) {
  return {
    designator: designator ?? designatorPlaceholder(spec, part),
    comment: comment ?? (spec.comment || '*'),
  }
}

/** Text mit Altium-Überstrich (`R\E\S\E\T\`) als tspans */
function OverbarText({ value }: { value: string }) {
  const segments = overbarSegments(value)
  if (segments.length === 1 && !segments[0].barred) return <>{segments[0].text}</>
  return (
    <>
      {segments.map((s, i) =>
        s.barred ? (
          <tspan key={i} textDecoration="overline">
            {s.text}
          </tspan>
        ) : (
          <tspan key={i}>{s.text}</tspan>
        ),
      )}
    </>
  )
}

/** Überstrich-Text für HTML (Tooltips) */
function OverbarHtml({ value }: { value: string }) {
  return (
    <>
      {overbarSegments(value).map((s, i) =>
        s.barred ? (
          <span key={i} className="[text-decoration-line:overline]">
            {s.text}
          </span>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </>
  )
}

// --------------------------------------------------------------------------- Grafiken

function arcPath(cx: number, cy: number, r: number, start: number, end: number): string | null {
  let span = (((end - start) % 360) + 360) % 360
  if (span === 0 && end !== start) span = 360
  if (span >= 359.999) return null
  const s = (start * Math.PI) / 180
  const e = ((start + span) * Math.PI) / 180
  const sx = cx + r * Math.cos(s)
  const sy = cy + r * Math.sin(s)
  const ex = cx + r * Math.cos(e)
  const ey = cy + r * Math.sin(e)
  // Welt gegen den Uhrzeigersinn → in SVG (Y gespiegelt) im Uhrzeigersinn: sweep = 0
  return `M ${sx} ${-sy} A ${r} ${r} 0 ${span > 180 ? 1 : 0} 0 ${ex} ${-ey}`
}

function Graphic({ g, pal, px, body }: { g: SymGraphic; pal: Palette; px: number; body?: boolean }) {
  const width = Math.max(STROKE[g.line_width] ?? 10, px * 1.1)
  const stroke = pal.line(g)
  const common = { stroke, strokeWidth: width, strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const }
  const fillOf = (filled: boolean) =>
    !filled && body && pal.fillBody ? { fill: 'var(--pf-sym-body)', opacity: undefined } : pal.fill(g, filled)
  switch (g.kind) {
    case 'rect': {
      const { fill, opacity } = fillOf(g.filled)
      const x = Math.min(g.x1, g.x2)
      const y = Math.max(g.y1, g.y2)
      return (
        <rect
          x={x}
          y={-y}
          width={Math.abs(g.x2 - g.x1)}
          height={Math.abs(g.y2 - g.y1)}
          rx={g.corner_radius || undefined}
          fill={fill}
          fillOpacity={opacity}
          {...common}
        />
      )
    }
    case 'line':
      return <polyline points={g.points.map((p) => `${p.x},${-p.y}`).join(' ')} fill="none" {...common} />
    case 'polygon': {
      const { fill, opacity } = fillOf(g.filled)
      return <polygon points={g.points.map((p) => `${p.x},${-p.y}`).join(' ')} fill={fill} fillOpacity={opacity} {...common} />
    }
    case 'arc': {
      const d = arcPath(g.cx, g.cy, g.r, g.start ?? 0, g.end ?? 360)
      return d ? <path d={d} fill="none" {...common} /> : <circle cx={g.cx} cy={-g.cy} r={g.r} fill="none" {...common} />
    }
    case 'ellipse': {
      const { fill, opacity } = fillOf(g.filled)
      return <ellipse cx={g.cx} cy={-g.cy} rx={g.rx} ry={g.ry} fill={fill} fillOpacity={opacity} {...common} />
    }
    case 'text': {
      const em = (g.size ?? 10) * 10
      const [vertical, horizontal] = (g.justify ?? 'bottom_left').split('_')
      return (
        <text
          x={0}
          y={baselineOffset(vertical, em)}
          transform={`translate(${g.x} ${-g.y})${g.rotation ? ` rotate(${-g.rotation})` : ''}`}
          textAnchor={ANCHOR[horizontal] ?? 'start'}
          fontSize={em}
          fill={pal.text(g)}
          style={{ fontFamily: pal.font }}
        >
          <OverbarText value={g.text} />
        </text>
      )
    }
  }
}

// --------------------------------------------------------------------------- Pins

interface PinVisualState {
  highlighted: boolean
  dimmed: boolean
}

function PinDecoration({ pin, which, color, bg, px }: { pin: SymPin; which: 'inner' | 'outer'; color: string; bg: string; px: number }) {
  const deco = which === 'inner' ? pin.inner_edge : pin.outer_edge
  if (!deco || deco === 'none') return null
  const [dx, dy] = pinDirection(pin.orientation)
  const nx = -dy
  const ny = dx
  const ax = pin.x
  const ay = pin.y
  const w = Math.max(PIN_STROKE, px * 1.1)
  const pt = (x: number, y: number) => `${x},${-y}`
  switch (deco) {
    case 'dot': {
      const r = 18
      return <circle cx={ax + dx * r} cy={-(ay + dy * r)} r={r} fill={bg} stroke={color} strokeWidth={w} />
    }
    case 'clock':
      return (
        <polyline
          points={[pt(ax + nx * 25, ay + ny * 25), pt(ax - dx * 40, ay - dy * 40), pt(ax - nx * 25, ay - ny * 25)].join(' ')}
          fill="none"
          stroke={color}
          strokeWidth={w}
          strokeLinejoin="round"
        />
      )
    case 'active_low_input': {
      // kleiner Keil außen an der Körperkante (wie Altium „Active Low Input“)
      const ux = dx === 0 ? -1 : 0
      const uy = dx === 0 ? 0 : 1
      return (
        <polyline
          points={[pt(ax, ay), pt(ax + ux * 30, ay + uy * 30), pt(ax + dx * 50, ay + dy * 50)].join(' ')}
          fill="none"
          stroke={color}
          strokeWidth={w}
          strokeLinejoin="round"
        />
      )
    }
    case 'not_logic_connection': {
      const tip = pinTip(pin)
      const s = 22
      return (
        <path
          d={`M ${tip.x - s} ${-(tip.y - s)} L ${tip.x + s} ${-(tip.y + s)} M ${tip.x - s} ${-(tip.y + s)} L ${tip.x + s} ${-(tip.y - s)}`}
          stroke={color}
          strokeWidth={w}
        />
      )
    }
    default: {
      // Signalfluss / Analogeingang: kleiner Pfeil auf dem Pin (nach innen)
      const mx = ax + dx * 100
      const my = ay + dy * 100
      return (
        <polyline
          points={[pt(mx + dx * 25 + nx * 20, my + dy * 25 + ny * 20), pt(mx - dx * 15, my - dy * 15), pt(mx + dx * 25 - nx * 20, my + dy * 25 - ny * 20)].join(' ')}
          fill="none"
          stroke={color}
          strokeWidth={w}
          strokeLinejoin="round"
        />
      )
    }
  }
}

function PinLabels({ pin, pal, color }: { pin: SymPin; pal: Palette; color?: string }) {
  const out: ReactNode[] = []
  const nameColor = color ?? pal.pinName
  const numberColor = color ?? pal.pinNumber
  const { x, y } = pin
  const rotate = pin.orientation === 'up' || pin.orientation === 'down'
  if (pin.show_name !== false && pin.name) {
    let ax = x
    let ay = y
    let anchor: 'start' | 'end' = 'start'
    switch (pin.orientation) {
      case 'left':
        ax = x + NAME_MARGIN
        anchor = 'start'
        break
      case 'right':
        ax = x - NAME_MARGIN
        anchor = 'end'
        break
      case 'up':
        ay = y - NAME_MARGIN
        anchor = 'end'
        break
      case 'down':
        ay = y + NAME_MARGIN
        anchor = 'start'
        break
    }
    out.push(
      <text
        key="name"
        x={0}
        y={pal.nameSize * 0.34}
        transform={`translate(${ax} ${-ay})${rotate ? ' rotate(-90)' : ''}`}
        textAnchor={anchor}
        fontSize={pal.nameSize}
        fontWeight={pal.nameWeight}
        fill={nameColor}
        style={{ fontFamily: pal.nameFont }}
      >
        <OverbarText value={pin.name} />
      </text>,
    )
  }
  if (pin.show_designator !== false && pin.designator) {
    let ax = x
    let ay = y
    let anchor: 'start' | 'end' = 'start'
    switch (pin.orientation) {
      case 'left':
        ax = x - NUMBER_OFFSET
        anchor = 'end'
        break
      case 'right':
        ax = x + NUMBER_OFFSET
        anchor = 'start'
        break
      case 'up':
        ay = y + NUMBER_OFFSET
        anchor = 'start'
        break
      case 'down':
        ay = y - NUMBER_OFFSET
        anchor = 'end'
        break
    }
    out.push(
      <text
        key="number"
        x={0}
        y={-15}
        transform={`translate(${ax} ${-ay})${rotate ? ' rotate(-90)' : ''}`}
        textAnchor={anchor}
        fontSize={pal.numberSize}
        fill={numberColor}
        style={{ fontFamily: pal.numberFont }}
      >
        {pin.designator}
      </text>,
    )
  }
  return <>{out}</>
}

function PinShape({
  pin,
  index,
  pal,
  px,
  state,
  showText,
}: {
  pin: SymPin
  index: number
  pal: Palette
  px: number
  state: PinVisualState
  showText: boolean
}) {
  const tip = pinTip(pin)
  const color = state.highlighted ? 'var(--pf-accent)' : pal.pin
  const width = Math.max(PIN_STROKE, px * 1.25) * (state.highlighted ? 1.6 : 1)
  const hitWidth = Math.max(70, px * 14)
  return (
    <g
      data-pin={index}
      opacity={pin.hidden ? 0.55 : 1}
      style={state.highlighted ? { filter: 'drop-shadow(0 0 3px var(--pf-glow-indicator))' } : undefined}
    >
      {/* abgeblendet wird nur die Linie – Pin-Namen bleiben voll lesbar */}
      <line
        opacity={state.dimmed ? 0.4 : undefined}
        x1={pin.x}
        y1={-pin.y}
        x2={tip.x}
        y2={-tip.y}
        stroke={color}
        strokeWidth={width}
        strokeLinecap="round"
        strokeDasharray={pin.hidden ? `${px * 4} ${px * 3}` : undefined}
      />
      {/* Anschlussspitze (Hot Spot) */}
      <circle cx={tip.x} cy={-tip.y} r={Math.max(7, px * 2.1)} fill={color} opacity={state.dimmed ? 0.4 : undefined} />
      <PinDecoration pin={pin} which="inner" color={color} bg={pal.background} px={px} />
      <PinDecoration pin={pin} which="outer" color={color} bg={pal.background} px={px} />
      {showText && <PinLabels pin={pin} pal={pal} color={state.highlighted ? 'var(--pf-accent-text)' : undefined} />}
      {/* großzügige, unsichtbare Trefferfläche */}
      <line x1={pin.x} y1={-pin.y} x2={tip.x} y2={-tip.y} stroke="transparent" strokeWidth={hitWidth} strokeLinecap="round" />
    </g>
  )
}

/** Größte geschlossene Form eines Teils = Körper (Rechteck, Polygon, Ellipse), sofern sie ≥ 25 % der Fläche einnimmt */
function mainBodyIndex(graphics: SymGraphic[]): number {
  let best = -1
  let bestArea = 0
  let total = emptyBox()
  graphics.forEach((g, i) => {
    let area = 0
    if (g.kind === 'rect') area = Math.abs((g.x2 - g.x1) * (g.y2 - g.y1))
    else if (g.kind === 'ellipse') area = Math.PI * g.rx * g.ry
    else if (g.kind === 'polygon' && g.points.length >= 3) {
      let a = 0
      g.points.forEach((p, k) => {
        const q = g.points[(k + 1) % g.points.length]
        a += p.x * q.y - q.x * p.y
      })
      area = Math.abs(a) / 2
    }
    if (g.kind === 'rect') {
      total = boxAdd(boxAdd(total, g.x1, g.y1), g.x2, g.y2)
    } else if (g.kind === 'polygon' || g.kind === 'line') for (const p of g.points) total = boxAdd(total, p.x, p.y)
    if (area > bestArea) {
      bestArea = area
      best = i
    }
  })
  const totalArea = isEmptyBox(total) ? 0 : (total.x2 - total.x1) * (total.y2 - total.y1)
  return best >= 0 && totalArea > 0 && bestArea >= totalArea * 0.25 ? best : -1
}

// --------------------------------------------------------------------------- Verborgene Pins ohne Überdeckung

/** Begrenzungsrahmen (mil, +Y oben) aus zwei Punkten */
const segBox = (x1: number, y1: number, x2: number, y2: number, grow = 0): Box => ({
  x1: Math.min(x1, x2) - grow,
  y1: Math.min(y1, y2) - grow,
  x2: Math.max(x1, x2) + grow,
  y2: Math.max(y1, y2) + grow,
})

const overlaps = (a: Box, b: Box) => a.x1 < b.x2 - 0.5 && b.x1 < a.x2 - 0.5 && a.y1 < b.y2 - 0.5 && b.y1 < a.y2 - 0.5

/** Flächen eines Pins: Linie (mit Strichbreite), Name und Nummer – so, wie `PinLabels` sie zeichnet */
function pinBoxes(pin: SymPin, pal: Palette): { line: Box; labels: Box[] } {
  const tip = pinTip(pin)
  const line = segBox(pin.x, pin.y, tip.x, tip.y, 12)
  const labels: Box[] = []
  const { x, y } = pin
  if (pin.show_name !== false && pin.name) {
    const w = estimateTextWidth(pin.name, pal.nameSize)
    const h = pal.nameSize / 2
    if (pin.orientation === 'left') labels.push({ x1: x + NAME_MARGIN, x2: x + NAME_MARGIN + w, y1: y - h, y2: y + h })
    else if (pin.orientation === 'right') labels.push({ x1: x - NAME_MARGIN - w, x2: x - NAME_MARGIN, y1: y - h, y2: y + h })
    else if (pin.orientation === 'up') labels.push({ x1: x - h, x2: x + h, y1: y - NAME_MARGIN - w, y2: y - NAME_MARGIN })
    else labels.push({ x1: x - h, x2: x + h, y1: y + NAME_MARGIN, y2: y + NAME_MARGIN + w })
  }
  if (pin.show_designator !== false && pin.designator) {
    const w = estimateTextWidth(pin.designator, pal.numberSize)
    const cap = pal.numberSize * 0.75
    if (pin.orientation === 'left') labels.push({ x1: x - NUMBER_OFFSET - w, x2: x - NUMBER_OFFSET, y1: y + 10, y2: y + 15 + cap })
    else if (pin.orientation === 'right') labels.push({ x1: x + NUMBER_OFFSET, x2: x + NUMBER_OFFSET + w, y1: y + 10, y2: y + 15 + cap })
    else if (pin.orientation === 'up') labels.push({ x1: x - 15 - cap, x2: x - 10, y1: y + NUMBER_OFFSET, y2: y + NUMBER_OFFSET + w })
    else labels.push({ x1: x - 15 - cap, x2: x - 10, y1: y - NUMBER_OFFSET - w, y2: y - NUMBER_OFFSET })
  }
  return { line, labels }
}

/** Kanten der Grafiken (Körperkontur, Linien) als schmale Rahmen – Texte verborgener Pins dürfen sie nicht kreuzen */
function graphicEdges(graphics: SymGraphic[]): Box[] {
  const out: Box[] = []
  const poly = (pts: { x: number; y: number }[], closed: boolean) => {
    for (let i = 0; i + 1 < pts.length; i++) out.push(segBox(pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y, 6))
    if (closed && pts.length > 2) out.push(segBox(pts[pts.length - 1].x, pts[pts.length - 1].y, pts[0].x, pts[0].y, 6))
  }
  for (const g of graphics) {
    if (g.kind === 'rect') {
      poly(
        [
          { x: g.x1, y: g.y1 },
          { x: g.x2, y: g.y1 },
          { x: g.x2, y: g.y2 },
          { x: g.x1, y: g.y2 },
        ],
        true,
      )
    } else if (g.kind === 'line') poly(g.points, false)
    else if (g.kind === 'polygon') poly(g.points, true)
  }
  return out
}

interface HiddenPinLayout {
  /** Verborgene Pins (Index in `spec.pins`), die überdeckungsfrei an ihrer Stelle gezeichnet werden */
  inPlace: ReadonlySet<number>
  /** Verborgene Pins für die Liste „Verborgen“ (sie würden Sichtbares oder einander überdecken) */
  listed: number[]
}

const NO_HIDDEN: HiddenPinLayout = { inPlace: new Set(), listed: [] }

/**
 * Wohin mit verborgenen Pins? An ihrer Stelle nur, wenn weder Linie noch Texte einen sichtbaren Pin (samt Texten),
 * Bezeichner/Kommentar oder einen anderen verborgenen Pin berühren und die Texte keine Symbolkante kreuzen.
 */
function layoutHiddenPins(
  spec: SymbolSpec,
  part: number,
  pal: Palette,
  showLabels: boolean,
  designator?: string,
  comment?: string,
  cache = true,
): HiddenPinLayout {
  const pins = spec.pins ?? []
  const hidden = pins.map((p, i) => [p, i] as const).filter(([p]) => p.hidden && inPart(p.part, part))
  if (!hidden.length) return NO_HIDDEN
  const occupied: Box[] = []
  for (const p of pins) {
    if (p.hidden || !inPart(p.part, part)) continue
    const b = pinBoxes(p, pal)
    occupied.push(b.line, ...b.labels)
  }
  if (showLabels) {
    const pos = symbolLabelPositions(spec, part)
    const texts = labelTexts(spec, part, designator, comment)
    occupied.push(labelBox(pos.designator, texts.designator, pal, pal.fillBody ? 600 : undefined, cache))
    occupied.push(labelBox(pos.comment, texts.comment, pal, undefined, cache))
  }
  const edges = graphicEdges((spec.graphics ?? []).filter((g) => inPart(g.part, part)))
  const boxes = new Map(hidden.map(([p, i]) => [i, pinBoxes(p, pal)]))
  const inPlace = new Set<number>()
  const listed: number[] = []
  for (const [, i] of hidden) {
    const own = boxes.get(i)
    if (!own) continue
    const all = [own.line, ...own.labels]
    const hitsVisible = all.some((b) => occupied.some((o) => overlaps(b, o)))
    const crossesEdge = own.labels.some((b) => edges.some((e) => overlaps(b, e)))
    const hitsHidden = hidden.some(([, j]) => {
      if (j === i) return false
      const other = boxes.get(j)
      return Boolean(other && all.some((b) => [other.line, ...other.labels].some((o) => overlaps(b, o))))
    })
    if (hitsVisible || crossesEdge || hitsHidden) listed.push(i)
    else inPlace.add(i)
  }
  return { inPlace, listed }
}

// --------------------------------------------------------------------------- Inhalt (memoisiert)

interface ContentProps {
  spec: SymbolSpec
  part: number
  pal: Palette
  px: number
  showText: boolean
  /** Verborgene Pins, die an ihrer Stelle gezeichnet werden (leer = keine) */
  hiddenInPlace: ReadonlySet<number>
  showLabels: boolean
  highlight: ReadonlySet<string>
  designator?: string
  comment?: string
}

const SymbolContent = memo(function SymbolContent({
  spec,
  part,
  pal,
  px,
  showText,
  hiddenInPlace,
  showLabels,
  highlight,
  designator,
  comment,
}: ContentProps) {
  const graphics = (spec.graphics ?? []).filter((g) => inPart(g.part, part))
  const bodyIndex = mainBodyIndex(graphics)
  // verborgene Pins zuerst (darunter), sichtbare darüber – und verborgene nur, wo sie nichts überdecken
  const pins = (spec.pins ?? [])
    .map((p, i) => [p, i] as const)
    .filter(([p, i]) => inPart(p.part, part) && (!p.hidden || hiddenInPlace.has(i)))
    .sort(([a], [b]) => Number(Boolean(b.hidden)) - Number(Boolean(a.hidden)))
  const labels = showLabels ? symbolLabelPositions(spec, part) : null
  const hasHighlight = highlight.size > 0
  return (
    <>
      <g>
        {graphics.map((g, i) => (
          <Graphic key={i} g={g} pal={pal} px={px} body={i === bodyIndex} />
        ))}
      </g>
      <g>
        {pins.map(([p, i]) => (
          <PinShape
            key={i}
            pin={p}
            index={i}
            pal={pal}
            px={px}
            showText={showText}
            state={{ highlighted: highlight.has(p.designator), dimmed: hasHighlight && !highlight.has(p.designator) }}
          />
        ))}
      </g>
      {labels && showText && (
        <g>
          <LabelText
            pos={labels.designator}
            value={designator ?? designatorPlaceholder(spec, part)}
            color={pal.label}
            pal={pal}
            weight={pal.fillBody ? 600 : undefined}
          />
          <LabelText pos={labels.comment} value={comment ?? (spec.comment || '*')} color={pal.comment} pal={pal} />
        </g>
      )}
    </>
  )
})

function LabelText({
  pos,
  value,
  color,
  pal,
  weight,
}: {
  pos: { x: number; y: number; justify: TextJustify }
  value: string
  color: string
  pal: Palette
  weight?: number
}) {
  const [vertical, horizontal] = pos.justify.split('_')
  return (
    <text
      x={pos.x}
      y={-pos.y + baselineOffset(vertical, pal.labelSize)}
      textAnchor={ANCHOR[horizontal] ?? 'start'}
      fontSize={pal.labelSize}
      fontWeight={weight}
      fill={color}
      style={{ fontFamily: pal.font }}
    >
      <OverbarText value={value} />
    </text>
  )
}

// --------------------------------------------------------------------------- Bounding Box inkl. Texte

/**
 * Begrenzung aller gezeichneten Inhalte eines Teils (mil): Pins, Grafiken samt Text-Grafiken, Pin-Nummern sowie
 * Bezeichner und Kommentar mit ihrem **tatsächlichen** Text (lange MPNs wie „LTC6244CDHC#PBF“ werden nicht abgeschnitten).
 */
function contentBox(
  spec: SymbolSpec,
  part: number,
  hiddenInPlace: ReadonlySet<number>,
  showLabels: boolean,
  pal: Palette,
  designator?: string,
  comment?: string,
  /** Textmaße merken (erst, wenn die Webschriften geladen sind) */
  cache = true,
): Box {
  const b = symbolBBox(spec, part)
  // Text-Grafiken: symbolBBox kennt nur den Ankerpunkt – die Laufweite zählt mit
  for (const g of spec.graphics ?? []) {
    if (g.kind === 'text' && inPart(g.part, part) && g.text) boxAddBox(b, textGraphicBox(g, pal, cache))
  }
  // verborgene Pins zählen nur, wenn sie an ihrer Stelle gezeichnet werden (nicht in der Liste „Verborgen“)
  for (const i of hiddenInPlace) {
    const p = spec.pins?.[i]
    if (!p) continue
    const tip = pinTip(p)
    boxAdd(b, p.x, p.y)
    boxAdd(b, tip.x, tip.y)
  }
  // Pin-Nummern und -Namen ragen über die Linien hinaus → großzügig erweitern
  for (const [i, p] of (spec.pins ?? []).entries()) {
    if (!inPart(p.part, part) || (p.hidden && !hiddenInPlace.has(i))) continue
    if (p.show_designator !== false && p.designator) {
      const w = estimateTextWidth(p.designator)
      const [dx, dy] = pinDirection(p.orientation)
      boxAdd(b, p.x + dx * (NUMBER_OFFSET + w) - 20, p.y + dy * (NUMBER_OFFSET + w) + CAP + 20)
    }
  }
  if (showLabels && !isEmptyBox(b)) {
    const pos = symbolLabelPositions(spec, part)
    const texts = labelTexts(spec, part, designator, comment)
    boxAddBox(b, labelBox(pos.designator, texts.designator, pal, pal.fillBody ? 600 : undefined, cache))
    boxAddBox(b, labelBox(pos.comment, texts.comment, pal, undefined, cache))
  }
  return b
}

// --------------------------------------------------------------------------- Liste „Verborgen“

const HIDDEN_LIST_MAX = { wide: 6, compact: 3 }

/** Verborgene Pins, die an ihrer Stelle Sichtbares überdecken würden: kompakt oben rechts (Nummer + Name). */
function HiddenPinList({ pins, active, compact }: { pins: SymPin[]; active: ReadonlySet<string>; compact: boolean }) {
  useI18n()
  const max = compact ? HIDDEN_LIST_MAX.compact : HIDDEN_LIST_MAX.wide
  const shown = pins.slice(0, max)
  const more = pins.length - shown.length
  const full = pins.map((p) => `${p.designator}${p.name ? ` ${displayText(p.name)}` : ''}`).join(' · ')
  return (
    // nur Anzeige – Screenreader bekommen die Liste über die Beschreibung der Leinwand
    <div
      aria-hidden
      className="absolute right-3 top-3 z-10 flex max-w-[min(30rem,calc(100%-1.5rem))] justify-end"
      onPointerDown={(e) => e.stopPropagation()}
    >
      <CanvasBadge className="pointer-events-auto min-w-0 cursor-default gap-2.5 pr-3">
        <span className="flex shrink-0 items-center gap-1.5 text-fg-muted" title={tr("Verborgene Pins: {value0}", { value0: String(full) })}>
          <EyeOff aria-hidden className="size-3.5" />
          <span className="font-semibold uppercase tracking-[0.06em]">{tr("Verborgen")}</span>
        </span>
        <span className="flex min-w-0 items-center gap-2.5 overflow-hidden whitespace-nowrap" title={full}>
          {shown.map((p) => {
            const on = active.has(p.designator)
            return (
              <span key={`${p.designator}-${p.name}`} className={cn('flex items-baseline gap-1', on ? 'text-accent-text' : 'text-fg')}>
                <span className={cn('mono font-semibold', !on && 'text-fg-muted')}>{p.designator}</span>
                {p.name && (
                  <span className="truncate font-medium">
                    <OverbarHtml value={p.name} />
                  </span>
                )}
              </span>
            )
          })}
          {more > 0 && <span className="shrink-0 text-fg-muted">+{more}</span>}
        </span>
      </CanvasBadge>
    </div>
  )
}

// --------------------------------------------------------------------------- Komponente

export function SymbolCanvas({
  spec,
  theme = 'auto',
  part: partProp,
  defaultPart = 1,
  onPartChange,
  showPartTabs,
  highlight,
  hoverDesignator,
  onPinHover,
  onPinClick,
  showGrid = true,
  showHiddenPins = false,
  showOrigin,
  showLabels = true,
  designator,
  comment,
  interactive = true,
  controls = true,
  showInfo = true,
  onZoomChange,
  resetKey,
  className,
  'aria-label': ariaLabel,
  ref,
}: SymbolCanvasProps) {
  useI18n()
  const uid = useId().replace(/:/g, '')
  const [sizeRef, size, node] = useElementSize<HTMLDivElement>()
  const partCount = Math.max(1, spec?.part_count ?? 1)
  const [innerPart, setInnerPart] = useState(defaultPart)
  const part = Math.min(Math.max(1, partProp ?? innerPart), partCount)
  const setPart = (p: number) => {
    if (partProp === undefined) setInnerPart(p)
    onPartChange?.(p)
  }
  const pal = PALETTES[theme]

  // Webschriften fertig geladen → Texte neu vermessen (vorher kann die Messung eine Ersatzschrift treffen)
  const [fontsReady, setFontsReady] = useState(() => typeof document === 'undefined' || document.fonts?.status === 'loaded')
  useEffect(() => {
    if (fontsReady || typeof document === 'undefined' || !document.fonts) return
    let alive = true
    void document.fonts.ready.then(() => {
      if (alive) setFontsReady(true)
    })
    return () => {
      alive = false
    }
  }, [fontsReady])
  const hiddenLayout = useLocalizedMemo(
    () =>
      spec && showHiddenPins ? layoutHiddenPins(spec, part, pal, showLabels, designator, comment, fontsReady) : NO_HIDDEN,
    [spec, part, pal, showHiddenPins, showLabels, designator, comment, fontsReady],
  )
  const listedHidden = hiddenLayout.listed
  const box = useLocalizedMemo(
    () => (spec ? contentBox(spec, part, hiddenLayout.inPlace, showLabels, pal, designator, comment, fontsReady) : null),
    [spec, part, hiddenLayout, showLabels, pal, designator, comment, fontsReady],
  )
  const topBand = (partCount > 1 && (showPartTabs ?? true)) || listedHidden.length > 0
  const pz = usePanZoom({
    bbox: box && !isEmptyBox(box) ? box : null,
    width: size.width,
    height: size.height,
    padding: 24,
    insets: { top: topBand ? 40 : 0, bottom: showInfo ? 40 : 0 },
    maxFitScale: 0.48,
    minZoom: 0.25,
    maxZoom: 24,
    resetKey: resetKey ?? `${spec?.name ?? ''}|${part}`,
    enabled: interactive,
  })
  const { view } = pz
  const bucket = scaleBucket(view.scale)
  const px = 1 / bucket // Welteinheiten (mil) je Bildschirmpixel
  const showText = EM * view.scale >= 4.5

  useImperativeHandle(
    ref,
    () => ({
      fit: () => pz.fit(true),
      zoomIn: () => pz.zoomBy(1.4, undefined, true),
      zoomOut: () => pz.zoomBy(1 / 1.4, undefined, true),
    }),
    [pz],
  )

  const zoomRounded = Math.round(pz.zoom * 100) / 100
  const onZoomChangeRef = useRef(onZoomChange)
  useEffect(() => {
    onZoomChangeRef.current = onZoomChange
  })
  useEffect(() => {
    onZoomChangeRef.current?.(zoomRounded)
  }, [zoomRounded])

  const highlightSet = useLocalizedMemo(() => new Set(highlight ?? []), [highlight])

  // ------------------------------------------------------------------ Hover / Tastatur-Fokus auf Pins
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const [keyIndex, setKeyIndex] = useState<number | null>(null)
  const pins = useLocalizedMemo(() => spec?.pins ?? [], [spec])
  const visiblePins = useLocalizedMemo(
    () =>
      pins
        .map((p, i) => [p, i] as const)
        .filter(([p, i]) => inPart(p.part, part) && (!p.hidden || hiddenLayout.inPlace.has(i)))
        .map(([, i]) => i),
    [pins, part, hiddenLayout],
  )
  const externalIndex = hoverDesignator ? pins.findIndex((p, i) => p.designator === hoverDesignator && visiblePins.includes(i)) : -1
  const activeIndex = hoverIndex ?? keyIndex ?? (externalIndex >= 0 ? externalIndex : null)
  const activePin = activeIndex !== null ? pins[activeIndex] : null

  const setHover = (i: number | null) => {
    if (i === hoverIndex) return
    setHoverIndex(i)
    onPinHover?.(i === null ? null : (pins[i] ?? null))
  }

  const pinFromEvent = (e: MouseEvent<Element>): number | null => {
    const el = (e.target as Element).closest?.('[data-pin]')
    if (!el) return null
    const i = Number(el.getAttribute('data-pin'))
    return Number.isFinite(i) ? i : null
  }

  const [announce, setAnnounce] = useState('')
  const describePin = (p: SymPin) =>
    tr("Pin {value0}{value1}, {value2}{value3}", { value0: String(p.designator), value1: String(p.name ? `, ${spokenPinName(p.name)}` : ''), value2: String(electricalLabel(p.electrical)), value3: String(partCount > 1 ? `, ${p.part === 0 ? tr('alle Teile') : tr("Teil {value0}", { value0: String(partLetter(p.part ?? 1)) })}` : '') })

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (pz.handleKey(e)) {
      e.preventDefault()
      return
    }
    if ((e.key === 'n' || e.key === 'N') && visiblePins.length) {
      e.preventDefault()
      const cur = keyIndex === null ? -1 : visiblePins.indexOf(keyIndex)
      const next = e.shiftKey
        ? visiblePins[(cur - 1 + visiblePins.length) % visiblePins.length]
        : visiblePins[(cur + 1) % visiblePins.length]
      setKeyIndex(next)
      setAnnounce(describePin(pins[next]))
      onPinHover?.(pins[next] ?? null)
    } else if (e.key === 'Escape' && keyIndex !== null) {
      e.preventDefault()
      e.stopPropagation()
      setKeyIndex(null)
      onPinHover?.(null)
    } else if (e.key === 'Enter' && keyIndex !== null && onPinClick) {
      onPinClick(pins[keyIndex])
    } else if (partCount > 1 && (e.key === 'PageDown' || e.key === 'PageUp')) {
      e.preventDefault()
      setPart(e.key === 'PageDown' ? (part % partCount) + 1 : ((part - 2 + partCount) % partCount) + 1)
    }
  }

  // ------------------------------------------------------------------ Raster
  const step = gridStep(view.scale, [100, 500, 1000], 9)
  const stepPx = step * view.scale
  const gridOffsetX = ((view.tx % stepPx) + stepPx) % stepPx
  const gridOffsetY = ((view.ty % stepPx) + stepPx) % stepPx

  const hoverOverlay = activePin ? (
    <g style={{ pointerEvents: 'none' }}>
      <line
        x1={activePin.x}
        y1={-activePin.y}
        x2={pinTip(activePin).x}
        y2={-pinTip(activePin).y}
        stroke="var(--pf-accent)"
        strokeOpacity={0.28}
        strokeWidth={Math.max(PIN_STROKE * 4, px * 9)}
        strokeLinecap="round"
      />
      <line
        x1={activePin.x}
        y1={-activePin.y}
        x2={pinTip(activePin).x}
        y2={-pinTip(activePin).y}
        stroke="var(--pf-accent)"
        strokeWidth={Math.max(PIN_STROKE * 1.6, px * 2)}
        strokeLinecap="round"
      />
    </g>
  ) : null

  const tooltipAnchor = activePin
    ? (() => {
        const tip = pinTip(activePin)
        return pz.toScreen((activePin.x + tip.x) / 2, (activePin.y + tip.y) / 2)
      })()
    : null

  const hasSpec = Boolean(spec && ((spec.pins ?? []).length || (spec.graphics ?? []).length))
  const label =
    ariaLabel ??
    (spec
      ? tr("Symbol {value0}{value1}, {value2} Pins", { value0: String(spec.name), value1: String(partCount > 1 ? tr(", Teil {value0} von {value1}", { value0: String(partLetter(part)), value1: String(partCount) }) : ''), value2: String(visiblePins.length) })
      : tr('Symbolvorschau'))

  return (
    // Leinwand-Widget mit eigener Tastatursteuerung (Zoom, Verschieben, Pins ansagen) – role="application"
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      ref={(el) => {
        sizeRef(el)
        pz.wheelRef(el)
      }}
      role="application"
      aria-roledescription={tr("Symbolvorschau")}
      aria-label={label}
      aria-describedby={`${uid}-help`}
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      className={cn(
        'group/canvas relative isolate min-h-0 overflow-hidden outline-none select-none',
        'focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset',
        theme === 'altium' ? 'bg-altium-sheet' : 'bg-bg',
        pz.panning ? 'cursor-grabbing' : interactive ? 'cursor-grab' : '',
        className,
      )}
      {...pz.handlers}
      onPointerMove={(e) => {
        pz.handlers.onPointerMove(e)
        if (!pz.panning) setHover(pinFromEvent(e))
      }}
      onPointerLeave={() => setHover(null)}
      onClick={(e) => {
        if (pz.wasDrag(e.timeStamp) || !onPinClick) return
        const i = pinFromEvent(e)
        if (i !== null && pins[i]) onPinClick(pins[i])
      }}
      onKeyDown={onKeyDown}
      onBlur={() => setKeyIndex(null)}
    >
      {size.width > 0 && (
        <svg
          width={size.width}
          height={size.height}
          className="absolute inset-0 block"
          aria-hidden
          style={{ shapeRendering: 'geometricPrecision', textRendering: 'geometricPrecision' }}
        >
          {showGrid && stepPx >= 9 && (
            <>
              <defs>
                <pattern
                  id={`${uid}-grid`}
                  width={stepPx}
                  height={stepPx}
                  patternUnits="userSpaceOnUse"
                  x={gridOffsetX}
                  y={gridOffsetY}
                >
                  <circle cx={0.75} cy={0.75} r={step === 100 ? 0.95 : 1.15} fill={pal.grid} />
                </pattern>
              </defs>
              <rect width={size.width} height={size.height} fill={`url(#${uid}-grid)`} />
            </>
          )}
          {node && hasSpec && spec && (
            <g transform={`matrix(${view.scale} 0 0 ${view.scale} ${view.tx} ${view.ty})`}>
              <SymbolContent
                spec={spec}
                part={part}
                pal={pal}
                px={px}
                showText={showText}
                hiddenInPlace={hiddenLayout.inPlace}
                showLabels={showLabels}
                highlight={highlightSet}
                designator={designator}
                comment={comment}
              />
              {/* Ursprung (Bauteil-Nullpunkt): kleines neutrales Kreuz – dezent nur beim Überfahren/Fokus, sonst mit showOrigin */}
              {(showOrigin || interactive) && (
                <path
                  aria-hidden
                  d={`M ${-px * 4} 0 H ${px * 4} M 0 ${-px * 4} V ${px * 4}`}
                  stroke={theme === 'altium' ? '#8A8F99' : 'var(--pf-fg-subtle)'}
                  strokeWidth={px}
                  strokeLinecap="round"
                  pointerEvents="none"
                  className={cn(
                    'transition-opacity duration-150',
                    showOrigin
                      ? 'opacity-70'
                      : 'opacity-0 group-hover/canvas:opacity-70 group-focus-visible/canvas:opacity-70',
                  )}
                />
              )}
              {hoverOverlay}
            </g>
          )}
        </svg>
      )}

      {listedHidden.length > 0 && hasSpec && spec && (
        <HiddenPinList
          pins={listedHidden.map((i) => pins[i]).filter((p): p is SymPin => Boolean(p))}
          active={new Set([...(highlight ?? []), ...(hoverDesignator ? [hoverDesignator] : [])])}
          compact={size.width < 520}
        />
      )}

      {!hasSpec && (
        <div className="absolute inset-0 flex items-center justify-center text-ui text-fg-subtle">{tr("Kein Symbol")}</div>
      )}

      {partCount > 1 && (showPartTabs ?? true) && (
        <div className="absolute left-3 top-3 z-10 flex items-center gap-2" onPointerDown={(e) => e.stopPropagation()}>
          <SegmentedControl
            size="sm"
            aria-label={tr("Teil des Symbols")}
            value={String(part)}
            onValueChange={(v) => setPart(Number(v))}
            options={Array.from({ length: partCount }, (_, i) => ({
              value: String(i + 1),
              label: <span className="mono">{partLetter(i + 1)}</span>,
            }))}
            className="bg-[color-mix(in_oklab,var(--pf-surface)_85%,transparent)] shadow-raised backdrop-blur-md"
          />
        </div>
      )}

      {showInfo && hasSpec && spec && (
        <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-w-[calc(100%-11rem)] items-center gap-2">
          <CanvasBadge>
            <span className="mono truncate font-medium text-fg">{spec.name}</span>
            {size.width >= 420 && (
              <span className="whitespace-nowrap text-fg-muted">
                {visiblePins.length} {visiblePins.length === 1 ? tr('Pin') : tr('Pins')}
                {partCount > 1 && tr(" · Teil {value0}/{value1}", { value0: String(partLetter(part)), value1: String(partLetter(partCount)) })}
              </span>
            )}
          </CanvasBadge>
        </div>
      )}

      {controls && interactive && hasSpec && (
        <CanvasZoomControls
          zoom={pz.zoom}
          onZoomIn={() => pz.zoomBy(1.4, undefined, true)}
          onZoomOut={() => pz.zoomBy(1 / 1.4, undefined, true)}
          onFit={() => pz.fit(true)}
        />
      )}

      {activePin && tooltipAnchor && (
        <CanvasTooltip x={tooltipAnchor.x} y={tooltipAnchor.y} bounds={size}>
          <div className="flex items-baseline gap-2">
            <span className="mono rounded-sm bg-surface-3 px-1.5 text-2xs font-semibold text-fg">{activePin.designator}</span>
            <span className="truncate text-ui font-semibold text-fg">
              {activePin.name ? <OverbarHtml value={activePin.name} /> : <span className="text-fg-subtle">{tr("ohne Namen")}</span>}
            </span>
          </div>
          <div className="mt-1 flex flex-wrap gap-x-2 text-fg-muted">
            <span>{electricalLabel(activePin.electrical)}</span>
            {partCount > 1 && <span>· {activePin.part === 0 ? tr('alle Teile') : tr("Teil {value0}", { value0: String(partLetter(activePin.part ?? 1)) })}</span>}
            {activePin.hidden && <span>{tr("· verborgen")}</span>}
          </div>
          {(activePin.group || activePin.description) && (
            <div className="mt-1 text-fg-subtle">{[activePin.group, activePin.description].filter(Boolean).join(' · ')}</div>
          )}
        </CanvasTooltip>
      )}

      {interactive && hasSpec && (
        <CanvasKeyHint>
          {tr("Pfeiltasten verschieben · +/− zoomen · 0 einpassen · N nächster Pin")}
          {partCount > 1 ? tr(' · Bild↑/↓ Teil') : ''}
        </CanvasKeyHint>
      )}

      <p id={`${uid}-help`} className="sr-only">
        {spec
          ? `${(spec.pins ?? [])
              .filter((p) => inPart(p.part, part) && !p.hidden)
              .map((p) => tr("Pin {value0}{value1}", { value0: String(p.designator), value1: String(p.name ? ` ${displayText(p.name)}` : '') }))
              .join(', ')}. `
          : ''}
        {spec && showHiddenPins && (spec.pins ?? []).some((p) => p.hidden && inPart(p.part, part))
          ? tr("Verborgen: {value0}. ", { value0: String((spec.pins ?? [])
              .filter((p) => p.hidden && inPart(p.part, part))
              .map((p) => tr("Pin {value0}{value1}", { value0: String(p.designator), value1: String(p.name ? ` ${displayText(p.name)}` : '') }))
              .join(', ')) })
          : ''}
        {tr("Mit N den nächsten Pin ansagen, Pfeiltasten verschieben, Plus und Minus zoomen, 0 passt ein.")}
      </p>
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </div>
  )
}
