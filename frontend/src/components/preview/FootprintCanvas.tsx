/**
 * Footprint als SVG (mm, +Y oben, Draufsicht) auf dunkler Leiterplatten-Leinwand (beide Themes):
 * Pads (alle Formen, Drehung, Bohrungen/Langlöcher), Linien/Bögen/Flächen/Texte je logischer Lage in Altium-nahen
 * Farben, Lagen-Legende mit Umschaltern, Pad-Nummern (blenden sich bei kleiner Darstellung aus), Pad-Tooltip,
 * Koordinatenanzeige in mm, Zoom/Verschieben/Einpassen, Bemaßung aus dem Generator-Protokoll, Hervorhebung.
 *
 *   <FootprintCanvas spec={preview.spec} calc={preview.calc} highlight={['1']} />
 */
import {
  memo,
  useEffect,
  useId,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type Ref,
} from 'react'
import { ZoomIn } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  DRILL_COLOR,
  LAYERS,
  boxAddBox,
  boxHeight,
  boxWidth,
  footprintBBox,
  footprintLayers,
  formatMm,
  isEmptyBox,
  layerColor,
  layerFill,
  naturalCompare,
  padCornerRadius,
  padLayer,
  parseFootprintCalc,
  PAD_SHAPE_LABEL,
  type Arc,
  type Box,
  type CanvasLayer,
  type FootprintCalc,
  type FootprintSpec,
  type Pad,
} from '@/lib/geometry'
import { CanvasBadge, CanvasKeyHint, CanvasTooltip, CanvasZoomControls } from './CanvasChrome'
import { CHROME_MUTED, CHROME_SURFACE } from './chrome'
import { DEFAULT_LAYER_VISIBILITY, type LayerVisibility } from './layerVisibility'
import { footprintDimensions, type DimensionCallout, type DimensionLine } from './footprintDims'
import type { CanvasHandle } from './types'
import { useElementSize } from './useElementSize'
import { gridStep, scaleBucket, usePanZoom, type ViewState } from './usePanZoom'


export interface FootprintCanvasProps {
  spec: FootprintSpec | null | undefined
  /** Rechenprotokoll des Generators (`FootprintPreview.calc`) – liefert Zmax/Gmin/Xmax für die Bemaßung */
  calc?: unknown
  /** Bemaßung zeigen (Standard: wenn `calc` vorhanden) */
  showDimensions?: boolean
  /** Pads (Nummern) hervorheben */
  highlight?: readonly string[]
  /** Von außen hervorgehobenes Pad (z. B. beim Überfahren des Pins im Symbol) */
  hoverDesignator?: string | null
  onPadHover?: (pad: Pad | null) => void
  onPadClick?: (pad: Pad) => void
  /** Sichtbarkeit der Lagen (kontrolliert) */
  layers?: LayerVisibility
  defaultLayers?: LayerVisibility
  onLayersChange?: (layers: LayerVisibility) => void
  /**
   * Legende mit Lagen-Umschaltern: true = Chips (schmal: kompaktes Menü), „wide“ = nur Chips, wenn genug Platz ist
   * (z. B. in der PreviewPanel, die selbst ein Lagen-Menü hat), false = keine
   */
  showLegend?: boolean | 'wide'
  showPadNumbers?: boolean
  showGrid?: boolean
  interactive?: boolean
  /** Schwebende Zoom-Knöpfe (aus, wenn eine PreviewPanel-Werkzeugleiste steuert) */
  controls?: boolean
  /** Name, Padzahl und Maße oben links */
  showInfo?: boolean
  onZoomChange?: (zoom: number) => void
  resetKey?: unknown
  className?: string
  'aria-label'?: string
  ref?: Ref<CanvasHandle>
}

const PAD_TEXT = '#0B0E14'
const DIM_COLOR = '#C3CEE2'
const HOVER_COLOR = '#FFFFFF'

// --------------------------------------------------------------------------- Primitive

function arcElement(a: Arc, color: string, px: number, key: number): ReactNode {
  const span = (((a.end ?? 360) - (a.start ?? 0)) % 360 + 360) % 360
  const full = span === 0 && (a.end ?? 360) !== (a.start ?? 0)
  const width = Math.max(a.width, px)
  if (full || span >= 359.999) {
    if (a.width >= 2 * a.r - 1e-9) return <circle key={key} cx={a.cx} cy={-a.cy} r={a.r + a.width / 2} fill={color} />
    return <circle key={key} cx={a.cx} cy={-a.cy} r={a.r} fill="none" stroke={color} strokeWidth={width} />
  }
  const s = ((a.start ?? 0) * Math.PI) / 180
  const e = (((a.start ?? 0) + span) * Math.PI) / 180
  const x1 = a.cx + a.r * Math.cos(s)
  const y1 = -(a.cy + a.r * Math.sin(s))
  const x2 = a.cx + a.r * Math.cos(e)
  const y2 = -(a.cy + a.r * Math.sin(e))
  return (
    <path
      key={key}
      d={`M ${x1} ${y1} A ${a.r} ${a.r} 0 ${span > 180 ? 1 : 0} 0 ${x2} ${y2}`}
      fill="none"
      stroke={color}
      strokeWidth={width}
      strokeLinecap="round"
    />
  )
}

/** Pad-Grundform (ohne Bohrung) */
function PadShape({ pad, fill, stroke, strokeWidth, dash }: { pad: Pad; fill: string; stroke?: string; strokeWidth?: number; dash?: string }) {
  const { x, width: w, height: h } = pad
  const y = -pad.y
  const transform = pad.rotation ? `rotate(${-pad.rotation} ${x} ${y})` : undefined
  const common = { fill, stroke, strokeWidth, strokeDasharray: dash, transform }
  if (pad.shape === 'circle' && Math.abs(w - h) < 1e-9) return <circle cx={x} cy={y} r={w / 2} {...common} />
  if (pad.shape === 'octagon') {
    const c = (Math.min(w, h) * (1 - 1 / (1 + Math.SQRT2))) / 2
    const x1 = x - w / 2
    const y1 = y - h / 2
    const x2 = x + w / 2
    const y2 = y + h / 2
    const pts = [
      [x1 + c, y1],
      [x2 - c, y1],
      [x2, y1 + c],
      [x2, y2 - c],
      [x2 - c, y2],
      [x1 + c, y2],
      [x1, y2 - c],
      [x1, y1 + c],
    ]
      .map(([a, b]) => `${a},${b}`)
      .join(' ')
    return <polygon points={pts} {...common} />
  }
  const r = padCornerRadius(pad)
  return <rect x={x - w / 2} y={y - h / 2} width={w} height={h} rx={r || undefined} ry={r || undefined} {...common} />
}

function Hole({ pad, color, px }: { pad: Pad; color: string; px: number }) {
  if (!pad.hole) return null
  const hl = pad.hole_length ?? pad.hole
  if (hl > pad.hole + 1e-9) {
    const rot = pad.hole_rotation ?? ((pad.rotation ?? 0) + (pad.width >= pad.height ? 0 : 90))
    return (
      <rect
        x={pad.x - hl / 2}
        y={-pad.y - pad.hole / 2}
        width={hl}
        height={pad.hole}
        rx={pad.hole / 2}
        fill={color}
        stroke={pad.plated === false ? '#9AA4B6' : undefined}
        strokeWidth={pad.plated === false ? px : undefined}
        transform={rot ? `rotate(${-rot} ${pad.x} ${-pad.y})` : undefined}
      />
    )
  }
  return (
    <circle
      cx={pad.x}
      cy={-pad.y}
      r={pad.hole / 2}
      fill={color}
      stroke={pad.plated === false ? '#9AA4B6' : undefined}
      strokeWidth={pad.plated === false ? px : undefined}
    />
  )
}

/** Schriftgröße (mm) und Drehung der Pad-Nummer: entlang der langen Padseite, so groß wie möglich */
function padNumberLayout(pad: Pad): { size: number; rotate: boolean } {
  const len = Math.max(1, pad.designator.length)
  if (pad.hole) {
    const size = Math.max(0.12, Math.min(1, 0.62 * pad.hole, (pad.hole * 0.9) / (len * 0.62)))
    return { size, rotate: false }
  }
  // runde Pads (BGA-Kugeln): Text muss in den Kreis passen, nicht in sein umschreibendes Quadrat
  if (pad.shape === 'circle' && Math.abs(pad.width - pad.height) < 1e-6) {
    const d = pad.width
    const size = Math.max(0.08, Math.min(1, d * 0.5, (d * 0.7) / (len * 0.62)))
    return { size, rotate: false }
  }
  const rot = Math.abs((((pad.rotation ?? 0) % 180) + 180) % 180)
  const swapped = rot > 45 && rot < 135
  const w = swapped ? pad.height : pad.width
  const h = swapped ? pad.width : pad.height
  const rotate = h > w * 1.35
  const along = rotate ? h : w
  const across = rotate ? w : h
  // große Pads (Exposed Pad): Nummer nicht übergroß
  const cap = 0.42 + 0.12 * Math.min(pad.width, pad.height)
  const size = Math.max(0.1, Math.min(1.1, cap, across * 0.62, (along * 0.82) / (len * 0.62)))
  return { size, rotate }
}

/** Kleinste lesbare Pad-Nummer in Bildschirmpixeln – BGA-Ballnummern (A1, AB12) brauchen mehr als Zahlen */
const PAD_NUMBER_MIN_PX = 7
const BALL_NUMBER_MIN_PX = 9

/** Ball-Grid-Array: Rechenprotokoll mit BGA-Teil oder viele runde SMD-Pads mit Zeilen-/Spaltennamen (A1, B2 …) */
function isBallGrid(spec: FootprintSpec, calc: FootprintCalc | null): boolean {
  if (calc?.bga) return true
  const pads = spec.pads ?? []
  if (pads.length < 9) return false
  const balls = pads.filter((p) => !p.hole && p.shape === 'circle' && /^[A-Z]{1,2}\d{1,3}$/.test(p.designator))
  return balls.length >= pads.length * 0.8
}

// --------------------------------------------------------------------------- Inhalt (memoisiert)

interface ContentProps {
  spec: FootprintSpec
  visible: Record<CanvasLayer, boolean>
  px: number
  scale: number
  highlight: ReadonlySet<string>
  showPadNumbers: boolean
  /** BGA: Ballnummern erst ab {@link BALL_NUMBER_MIN_PX} zeigen (darunter wären sie nur Rauschen) */
  ballGrid: boolean
}

const FootprintContent = memo(function FootprintContent({ spec, visible, px, scale, highlight, showPadNumbers, ballGrid }: ContentProps) {
  const groups = new Map<CanvasLayer, ReactNode[]>()
  const push = (layer: CanvasLayer, node: ReactNode) => {
    const list = groups.get(layer)
    if (list) list.push(node)
    else groups.set(layer, [node])
  }
  const color = layerFill
  const strokeColor = layerFill

  ;(spec.bodies ?? []).forEach((b, i) => {
    const pts = b.outline.map((p) => `${p.x},${-p.y}`).join(' ')
    const main = i === 0 || /body|mold|sleeve/i.test(b.name)
    push(
      'body3d',
      <polygon
        key={`b${i}`}
        points={pts}
        fill={main ? color('body3d') : 'none'}
        fillOpacity={main ? 0.06 : undefined}
        stroke={color('body3d')}
        strokeOpacity={main ? 0.75 : 0.45}
        strokeWidth={px}
      />,
    )
  })
  ;(spec.tracks ?? []).forEach((t, i) => {
    const layer = (t.layer in LAYERS ? t.layer : 'keepout') as CanvasLayer
    const dashed = LAYERS[layer]?.dashed
    push(
      layer,
      <line
        key={`t${i}`}
        x1={t.x1}
        y1={-t.y1}
        x2={t.x2}
        y2={-t.y2}
        stroke={strokeColor(layer)}
        strokeWidth={Math.max(t.width, px * (dashed ? 1 : 1.1))}
        strokeLinecap={dashed ? 'butt' : 'round'}
        strokeDasharray={dashed ? `${px * 6} ${px * 4}` : undefined}
      />,
    )
  })
  ;(spec.arcs ?? []).forEach((a, i) => {
    const layer = (a.layer in LAYERS ? a.layer : 'keepout') as CanvasLayer
    push(layer, arcElement(a, strokeColor(layer), px, i))
  })
  ;(spec.regions ?? []).forEach((r, i) => {
    const layer = (r.layer in LAYERS ? r.layer : 'keepout') as CanvasLayer
    const pts = r.points.map((p) => `${p.x},${-p.y}`).join(' ')
    if (layer === 'top_paste' || layer === 'bottom_paste') {
      push(
        layer,
        <polygon
          key={`r${i}`}
          points={pts}
          fill="rgba(141,150,168,0.22)"
          stroke={layerColor(layer)}
          strokeWidth={px * 1.2}
          strokeDasharray={`${px * 3} ${px * 2}`}
        />,
      )
    } else {
      push(layer, <polygon key={`r${i}`} points={pts} fill={color(layer)} fillOpacity={0.85} />)
    }
  })

  const hasHighlight = highlight.size > 0
  ;(spec.pads ?? []).forEach((p, i) => {
    const layer = padLayer(p)
    const highlighted = highlight.has(p.designator)
    const dim = hasHighlight && !highlighted
    const npth = layer === 'multi_layer' && p.plated === false
    push(
      layer,
      <g key={`p${i}`} data-pad={i} opacity={dim ? 0.55 : 1} style={highlighted ? { filter: 'drop-shadow(0 0 0.35mm var(--pf-glow-indicator))' } : undefined}>
        {npth ? (
          <PadShape pad={p} fill="none" stroke={layerColor('multi_layer')} strokeWidth={px} dash={`${px * 3} ${px * 2}`} />
        ) : (
          <PadShape pad={p} fill={color(layer)} />
        )}
        <Hole pad={p} color={DRILL_COLOR} px={px} />
        {highlighted && <PadShape pad={p} fill="none" stroke="var(--pf-accent)" strokeWidth={px * 2.2} />}
      </g>,
    )
    if (p.paste !== false && layer !== 'multi_layer') {
      const pasteLayer: CanvasLayer = p.side === 'bottom' ? 'bottom_paste' : 'top_paste'
      const grow = p.paste_expansion ?? 0
      push(
        pasteLayer,
        <PadShape
          key={`pp${i}`}
          pad={{ ...p, width: Math.max(0, p.width + 2 * grow), height: Math.max(0, p.height + 2 * grow) }}
          fill="rgba(141,150,168,0.18)"
          stroke={layerColor(pasteLayer)}
          strokeWidth={px * 1.2}
          dash={`${px * 3} ${px * 2}`}
        />,
      )
    }
  })

  // Pad-Nummern (oberhalb der Kupferlagen, blenden sich bei kleiner Darstellung aus)
  const numbers: ReactNode[] = []
  const minPx = ballGrid ? BALL_NUMBER_MIN_PX : PAD_NUMBER_MIN_PX
  if (showPadNumbers) {
    ;(spec.pads ?? []).forEach((p, i) => {
      const layer = padLayer(p)
      if (!visible[layer] || !p.designator) return
      const { size, rotate } = padNumberLayout(p)
      if (size * scale < minPx) return
      numbers.push(
        <text
          key={`n${i}`}
          x={p.x}
          y={-p.y}
          transform={rotate ? `rotate(-90 ${p.x} ${-p.y})` : undefined}
          fontSize={size}
          fill={p.hole ? '#C9CED8' : PAD_TEXT}
          textAnchor="middle"
          dominantBaseline="central"
          fontWeight={650}
          style={{ fontFamily: 'var(--font-mono)', pointerEvents: 'none' }}
          opacity={hasHighlight && !highlight.has(p.designator) ? 0.75 : 1}
        >
          {p.designator}
        </text>,
      )
    })
  }

  ;(spec.texts ?? []).forEach((t, i) => {
    const layer = (t.layer in LAYERS ? t.layer : 'designator') as CanvasLayer
    const [vertical, horizontal] = (t.justify ?? 'middle_center').split('_')
    push(
      layer,
      <text
        key={`x${i}`}
        x={0}
        y={0}
        transform={`translate(${t.x} ${-t.y})${t.rotation ? ` rotate(${-t.rotation})` : ''}`}
        fontSize={t.height ?? 1}
        fill={layerColor(layer)}
        textAnchor={horizontal === 'left' ? 'start' : horizontal === 'right' ? 'end' : 'middle'}
        dominantBaseline={vertical === 'top' ? 'hanging' : vertical === 'bottom' ? 'alphabetic' : 'central'}
        style={{ fontFamily: 'var(--font-sans)' }}
      >
        {t.text}
      </text>,
    )
  })

  const order = (Object.values(LAYERS) as { id: CanvasLayer; order: number }[]).sort((a, b) => a.order - b.order)
  return (
    <>
      {order.map(({ id }) =>
        visible[id] && groups.has(id) ? (
          <g key={id} data-layer={id}>
            {groups.get(id)}
          </g>
        ) : null,
      )}
      <g>{numbers}</g>
    </>
  )
})

// --------------------------------------------------------------------------- Bemaßung (Bildschirm-Abstände)

/** Rechteck in Bildschirmpixeln */
interface Rect {
  x: number
  y: number
  w: number
  h: number
}

const rectsOverlap = (a: Rect, b: Rect, gap = 0) =>
  a.x < b.x + b.w + gap && b.x < a.x + a.w + gap && a.y < b.y + b.h + gap && b.y < a.y + a.h + gap

const LABEL_H = 18
const labelWidth = (text: string) => text.length * 6.6 + 12
const clampNum = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

interface DimLayout {
  d: DimensionLine
  isH: boolean
  /** Lage der Maßlinie quer zur Messrichtung */
  basePx: number
  a: number
  b: number
  lo: number
  hi: number
  edgeA: number
  edgeB: number
  arrowsOut: boolean
  /** Mitte der Beschriftung (senkrechte Maße: gedreht) */
  lx: number
  ly: number
  labelW: number
  /** Beschriftung neben der Maßlinie: kurze Verlängerung der Linie bis zur Beschriftung */
  leader: string | null
  /** belegte Flächen (Beschriftung, Maßlinie) für die Platzierung der Hinweise */
  rects: Rect[]
}

/**
 * Maßketten in Bildschirmkoordinaten: Maßlinie außerhalb der Kontur (Abstand je Staffel), Beschriftung mittig auf
 * der Linie – passt sie nicht dazwischen, steht sie hinter dem Linienende (bzw. davor, wenn der Platz am Rand fehlt)
 * und die Maßlinie wird bis zu ihr verlängert.
 */
function layoutDimensions(lines: DimensionLine[], view: ViewState, bounds: { width: number; height: number }): DimLayout[] {
  const s = view.scale
  const sx = (x: number) => x * s + view.tx
  const sy = (y: number) => -y * s + view.ty
  return lines.map((d) => {
    const offset = 18 + d.level * 22
    const isH = d.orient === 'h'
    const basePx = isH ? sy(d.base) - d.side * offset : sx(d.base) + d.side * offset
    const a = isH ? sx(d.a) : sy(d.a)
    const b = isH ? sx(d.b) : sy(d.b)
    const lo = Math.min(a, b)
    const hi = Math.max(a, b)
    const len = hi - lo
    const labelW = labelWidth(d.label)
    const arrowsOut = len < 22
    const inside = len > labelW + 10
    const limit = isH ? bounds.width : bounds.height
    let along = (lo + hi) / 2
    let leader: string | null = null
    if (!inside) {
      const ext = arrowsOut ? 12 : 0
      const after = hi + ext + 6 + labelW / 2
      const before = lo - ext - 6 - labelW / 2
      along = after + labelW / 2 <= limit - 6 || before - labelW / 2 < 6 ? after : before
      const from = along > hi ? hi + ext : lo - ext
      const to = along > hi ? along - labelW / 2 : along + labelW / 2
      leader = isH ? `M ${from} ${basePx} H ${to}` : `M ${basePx} ${from} V ${to}`
    }
    const lx = isH ? along : basePx
    const ly = isH ? basePx : along
    const labelRect: Rect = isH
      ? { x: lx - labelW / 2, y: ly - LABEL_H / 2, w: labelW, h: LABEL_H }
      : { x: lx - LABEL_H / 2, y: ly - labelW / 2, w: LABEL_H, h: labelW }
    const lineRect: Rect = isH
      ? { x: lo - (arrowsOut ? 12 : 0), y: basePx - 3, w: len + (arrowsOut ? 24 : 0), h: 6 }
      : { x: basePx - 3, y: lo - (arrowsOut ? 12 : 0), w: 6, h: len + (arrowsOut ? 24 : 0) }
    return {
      d,
      isH,
      basePx,
      a,
      b,
      lo,
      hi,
      edgeA: isH ? sy(d.edgeA) : sx(d.edgeA),
      edgeB: isH ? sy(d.edgeB) : sx(d.edgeB),
      arrowsOut,
      lx,
      ly,
      labelW,
      leader,
      rects: [labelRect, lineRect],
    }
  })
}

function DimLabel({ x, y, width, text, rotate }: { x: number; y: number; width: number; text: string; rotate?: boolean }) {
  return (
    <g transform={`translate(${x} ${y})${rotate ? ' rotate(-90)' : ''}`}>
      <rect
        x={-width / 2}
        y={-LABEL_H / 2}
        width={width}
        height={LABEL_H}
        rx={5}
        fill="rgba(8,11,16,0.92)"
        stroke="rgba(255,255,255,0.14)"
      />
      <text
        x={0}
        y={0.5}
        textAnchor="middle"
        dominantBaseline="central"
        fontSize={11}
        fontWeight={600}
        fill="#E9EEF7"
        style={{ fontFamily: 'var(--font-mono)' }}
      >
        {text}
      </text>
    </g>
  )
}

function DimensionLayer({ layout }: { layout: DimLayout[] }) {
  return (
    <g style={{ pointerEvents: 'none' }} aria-hidden>
      {layout.map((l, i) => {
        const { d, isH, basePx, a, b, lo, hi, edgeA, edgeB, arrowsOut } = l
        const over = 4 * (isH ? -d.side : d.side)
        const arrow = (at: number, dir: 1 | -1) => {
          const back = at - dir * 6
          return isH
            ? `M ${at} ${basePx} L ${back} ${basePx - 2.6} L ${back} ${basePx + 2.6} Z`
            : `M ${basePx} ${at} L ${basePx - 2.6} ${back} L ${basePx + 2.6} ${back} Z`
        }
        return (
          <g key={i}>
            <title>{d.title}</title>
            {/* Hilfslinien: von der Padkante bis knapp über die Maßlinie */}
            {isH ? (
              <path
                d={`M ${a} ${edgeA - d.side * 3} V ${basePx + over} M ${b} ${edgeB - d.side * 3} V ${basePx + over}`}
                stroke={DIM_COLOR}
                strokeOpacity={0.45}
                strokeWidth={1}
              />
            ) : (
              <path
                d={`M ${edgeA + d.side * 3} ${a} H ${basePx + over} M ${edgeB + d.side * 3} ${b} H ${basePx + over}`}
                stroke={DIM_COLOR}
                strokeOpacity={0.45}
                strokeWidth={1}
              />
            )}
            {/* Maßlinie */}
            {isH ? (
              <path d={`M ${lo - (arrowsOut ? 12 : 0)} ${basePx} H ${hi + (arrowsOut ? 12 : 0)}`} stroke={DIM_COLOR} strokeOpacity={0.85} strokeWidth={1} />
            ) : (
              <path d={`M ${basePx} ${lo - (arrowsOut ? 12 : 0)} V ${hi + (arrowsOut ? 12 : 0)}`} stroke={DIM_COLOR} strokeOpacity={0.85} strokeWidth={1} />
            )}
            {l.leader && <path d={l.leader} stroke={DIM_COLOR} strokeOpacity={0.55} strokeWidth={1} strokeDasharray="2 2" />}
            <path d={arrowsOut ? arrow(lo, 1) : arrow(lo, -1)} fill={DIM_COLOR} />
            <path d={arrowsOut ? arrow(hi, -1) : arrow(hi, 1)} fill={DIM_COLOR} />
            {/* Beschriftung (senkrechte Maße gedreht auf der Linie – stapelt sich nicht seitlich) */}
            <DimLabel x={l.lx} y={l.ly} width={l.labelW} text={d.label} rotate={!isH} />
          </g>
        )
      })}
    </g>
  )
}

interface CalloutLayout {
  c: DimensionCallout
  target: { x: number; y: number }
  rect: Rect
  /** Endpunkt der Hinweislinie am Etikett */
  anchor: { x: number; y: number }
}

/**
 * Hinweise (Padmaß, Bohrung, BGA-Land) **außerhalb der Kontur** mit Hinweislinie zum Ziel platzieren: zuerst an der
 * nächstgelegenen Ecke, dann seitlich auf Höhe des Ziels bzw. darüber/darunter, dann an den übrigen Ecken – ohne
 * Maßketten, Overlays (Info oben, Legende/Zoom unten) oder andere Hinweise zu überdecken.
 */
function layoutCallouts(
  callouts: DimensionCallout[],
  view: ViewState,
  contour: Box | null,
  occupied: Rect[],
  area: Rect,
): CalloutLayout[] {
  const s = view.scale
  const toScreen = (x: number, y: number) => ({ x: x * s + view.tx, y: -y * s + view.ty })
  const c0 = contour ? toScreen(contour.x1, contour.y2) : null
  const c1 = contour ? toScreen(contour.x2, contour.y1) : null
  const box: Rect | null = c0 && c1 ? { x: c0.x - 4, y: c0.y - 4, w: c1.x - c0.x + 8, h: c1.y - c0.y + 8 } : null
  const taken = [...occupied]
  const out: CalloutLayout[] = []
  for (const c of callouts) {
    const target = toScreen(c.x, c.y)
    // Ziel außerhalb des sichtbaren Bereichs (hineingezoomt/verschoben): kein Hinweis ins Leere
    if (target.x < area.x || target.x > area.x + area.w || target.y < area.y || target.y > area.y + area.h) continue
    const w = labelWidth(c.label)
    const h = LABEL_H
    const candidates: Rect[] = []
    if (box) {
      const left = target.x < box.x + box.w / 2
      const top = target.y < box.y + box.h / 2
      const corners: [boolean, boolean][] = [
        [left, top],
        [left, !top],
        [!left, top],
        [!left, !top],
      ]
      for (const [l, t] of corners.slice(0, 1)) {
        for (const g of [10, 26, 44]) {
          // diagonal vor der Ecke
          candidates.push({ x: l ? box.x - g - w : box.x + box.w + g, y: t ? box.y - g - h : box.y + box.h + g, w, h })
          // seitlich auf Höhe des Ziels
          candidates.push({ x: l ? box.x - g - w : box.x + box.w + g, y: target.y - h / 2, w, h })
          // darüber bzw. darunter auf Höhe des Ziels
          candidates.push({ x: target.x - w / 2, y: t ? box.y - g - h : box.y + box.h + g, w, h })
        }
      }
      for (const [l, t] of corners.slice(1)) {
        candidates.push({ x: l ? box.x - 10 - w : box.x + box.w + 10, y: t ? box.y - 10 - h : box.y + box.h + 10, w, h })
      }
    } else {
      candidates.push({ x: target.x - 30 - w, y: target.y - 30 - h / 2, w, h })
    }
    const fits = (r: Rect) =>
      r.x >= area.x && r.y >= area.y && r.x + r.w <= area.x + area.w && r.y + r.h <= area.y + area.h
    const rect = candidates.find((r) => fits(r) && !(box && rectsOverlap(r, box)) && !taken.some((o) => rectsOverlap(r, o, 3)))
    // Kein freier Platz außerhalb der Kontur (stark hineingezoomt): Hinweis weglassen statt Linien zu überdecken –
    // die Werte stehen im Tooltip des Pads und im Rechenprotokoll
    if (!rect) continue
    taken.push(rect)
    out.push({
      c,
      target,
      rect,
      anchor: { x: clampNum(target.x, rect.x, rect.x + rect.w), y: clampNum(target.y, rect.y, rect.y + rect.h) },
    })
  }
  return out
}

// --------------------------------------------------------------------------- Legende

function LegendSwatch({ layer, on }: { layer: CanvasLayer; on: boolean }) {
  const c = layerColor(layer)
  const meta = LAYERS[layer]
  if (meta?.dashed) {
    return <span aria-hidden className="size-2.5 rounded-[2px] border border-dashed" style={{ borderColor: c, opacity: on ? 1 : 0.5 }} />
  }
  if (layer === 'top_paste' || layer === 'bottom_paste' || layer === 'body3d' || layer === 'component_outline') {
    return <span aria-hidden className="size-2.5 rounded-[2px] border" style={{ borderColor: c, opacity: on ? 1 : 0.5 }} />
  }
  return (
    <span
      aria-hidden
      className="size-2.5 rounded-[2px]"
      style={on ? { background: c, boxShadow: `0 0 8px -1px ${c}` } : { border: `1px solid ${c}`, opacity: 0.55 }}
    />
  )
}

// --------------------------------------------------------------------------- Komponente

export function FootprintCanvas({
  spec,
  calc,
  showDimensions,
  highlight,
  hoverDesignator,
  onPadHover,
  onPadClick,
  layers: layersProp,
  defaultLayers,
  onLayersChange,
  showLegend = true,
  showPadNumbers = true,
  showGrid = true,
  interactive = true,
  controls = true,
  showInfo = true,
  onZoomChange,
  resetKey,
  className,
  'aria-label': ariaLabel,
  ref,
}: FootprintCanvasProps) {
  const uid = useId().replace(/:/g, '')
  const [sizeRef, size, node] = useElementSize<HTMLDivElement>()
  const parsedCalc: FootprintCalc | null = useMemo(() => parseFootprintCalc(calc), [calc])

  const [innerLayers, setInnerLayers] = useState<LayerVisibility>(defaultLayers ?? {})
  const overrides = layersProp ?? innerLayers
  const visible = useMemo(() => ({ ...DEFAULT_LAYER_VISIBILITY, ...overrides }), [overrides])
  const toggleLayer = (layer: CanvasLayer) => {
    const next = { ...overrides, [layer]: !visible[layer] }
    if (layersProp === undefined) setInnerLayers(next)
    onLayersChange?.(next)
  }

  const present = useMemo(() => (spec ? footprintLayers(spec) : []), [spec])

  const box = useMemo(() => {
    if (!spec) return null
    const b = footprintBBox(spec, { bodies: true })
    if (parsedCalc?.courtyard) boxAddBox(b, parsedCalc.courtyard)
    return isEmptyBox(b) ? null : b
  }, [spec, parsedCalc])

  const dims = useMemo(
    () => (spec && (showDimensions ?? Boolean(parsedCalc)) ? footprintDimensions(spec, parsedCalc) : null),
    [spec, parsedCalc, showDimensions],
  )
  const dimPadding = dims && dims.lines.length ? 60 : 26
  const [legendRef, legendSize] = useElementSize<HTMLDivElement>()
  // Chips nur bei genug Fläche – sonst kompaktes Menü (der Footprint braucht den Platz)
  const wideLegend = size.width >= 640 && size.height >= 380
  const legendMode: 'chips' | 'menu' | 'none' =
    !showLegend || !spec || present.length === 0 ? 'none' : wideLegend ? 'chips' : showLegend === 'wide' ? 'none' : 'menu'
  const legendVisible = legendMode === 'chips'

  const pz = usePanZoom({
    bbox: box,
    width: size.width,
    height: size.height,
    padding: dimPadding,
    insets: { top: showInfo ? 40 : 0, bottom: legendVisible && legendSize.height ? legendSize.height + 10 : 0 },
    maxFitScale: 90,
    minZoom: 0.25,
    maxZoom: 40,
    resetKey: resetKey ?? spec?.name,
    enabled: interactive,
  })
  const { view } = pz
  const bucket = scaleBucket(view.scale)
  const px = 1 / bucket

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

  const highlightSet = useMemo(() => new Set(highlight ?? []), [highlight])
  const pads = useMemo(() => spec?.pads ?? [], [spec])

  // ------------------------------------------------------------------ Hover / Tastatur
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)
  const [keyIndex, setKeyIndex] = useState<number | null>(null)
  const sortedPads = useMemo(
    () =>
      pads
        .map((p, i) => [p, i] as const)
        .sort((a, b) => naturalCompare(a[0].designator, b[0].designator))
        .map(([, i]) => i),
    [pads],
  )
  const externalIndex = hoverDesignator ? pads.findIndex((p) => p.designator === hoverDesignator) : -1
  const activeIndex = hoverIndex ?? keyIndex ?? (externalIndex >= 0 ? externalIndex : null)
  const activePad = activeIndex !== null ? pads[activeIndex] : null

  const padFromEvent = (e: MouseEvent<Element>): number | null => {
    const el = (e.target as Element).closest?.('[data-pad]')
    if (!el) return null
    const i = Number(el.getAttribute('data-pad'))
    return Number.isFinite(i) ? i : null
  }
  const setHover = (i: number | null) => {
    if (i === hoverIndex) return
    setHoverIndex(i)
    onPadHover?.(i === null ? null : (pads[i] ?? null))
  }

  const readoutRef = useRef<HTMLSpanElement>(null)
  const updateReadout = (e: MouseEvent<HTMLDivElement> | null) => {
    const el = readoutRef.current
    if (!el) return
    if (!e || !node) {
      el.textContent = ''
      return
    }
    const rect = node.getBoundingClientRect()
    const w = pz.toWorld(e.clientX - rect.left, e.clientY - rect.top)
    el.textContent = `X ${formatMm(w.x, 3)}  Y ${formatMm(w.y, 3)}`
  }

  const [announce, setAnnounce] = useState('')
  const describePad = (p: Pad) =>
    `Pad ${p.designator}, ${PAD_SHAPE_LABEL[p.shape] ?? p.shape}, ${formatMm(p.width)} mal ${formatMm(p.height)} Millimeter`

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (pz.handleKey(e)) {
      e.preventDefault()
      return
    }
    if ((e.key === 'n' || e.key === 'N') && sortedPads.length) {
      e.preventDefault()
      const cur = keyIndex === null ? -1 : sortedPads.indexOf(keyIndex)
      const next = e.shiftKey
        ? sortedPads[(cur - 1 + sortedPads.length) % sortedPads.length]
        : sortedPads[(cur + 1) % sortedPads.length]
      setKeyIndex(next)
      setAnnounce(describePad(pads[next]))
      onPadHover?.(pads[next] ?? null)
    } else if (e.key === 'Escape' && keyIndex !== null) {
      e.preventDefault()
      e.stopPropagation()
      setKeyIndex(null)
      onPadHover?.(null)
    } else if (e.key === 'Enter' && keyIndex !== null && onPadClick) {
      onPadClick(pads[keyIndex])
    }
  }

  // ------------------------------------------------------------------ Raster + Maßstab
  const step = gridStep(view.scale, [0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 25], 14)
  const stepPx = step * view.scale
  const gridOffsetX = ((view.tx % stepPx) + stepPx) % stepPx
  const gridOffsetY = ((view.ty % stepPx) + stepPx) % stepPx
  const scaleBar = gridStep(view.scale, [0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50], 56)

  const hasSpec = Boolean(spec && (pads.length || (spec.tracks ?? []).length))
  const courtyard = parsedCalc?.courtyard ?? (spec ? footprintBBox(spec, { layers: ['courtyard'], bodies: false }) : null)
  const sizeBox: Box | null = courtyard && !isEmptyBox(courtyard) ? courtyard : box
  const label = ariaLabel ?? (spec ? `Footprint ${spec.name}, ${pads.length} Pads` : 'Footprintvorschau')

  const tooltipAnchor = activePad ? pz.toScreen(activePad.x, activePad.y) : null

  // BGA: Ballnummern erst ab lesbarer Größe – darunter ein Hinweis im Info-Etikett
  const ballGrid = useMemo(() => (spec ? isBallGrid(spec, parsedCalc) : false), [spec, parsedCalc])
  const ballNumbersHidden =
    ballGrid && showPadNumbers && pads.length > 0 && pads.every((p) => padNumberLayout(p).size * bucket < BALL_NUMBER_MIN_PX)

  // Bemaßung + Hinweise in Bildschirmkoordinaten (Hinweise meiden Maßketten und die Overlays oben/unten)
  const dimLayout = dims && dims.lines.length ? layoutDimensions(dims.lines, view, size) : null
  const topReserve = showInfo || size.width >= 560 ? 46 : 8
  const bottomReserve = Math.max(
    8,
    legendVisible && legendSize.height ? legendSize.height + 18 : 0,
    legendMode === 'menu' ? 46 : 0,
    controls && interactive ? 46 : 0,
  )
  const calloutLayout =
    dims && dims.callouts.length
      ? layoutCallouts(dims.callouts, view, dims.contour, dimLayout?.flatMap((l) => l.rects) ?? [], {
          x: 8,
          y: topReserve,
          w: Math.max(0, size.width - 16),
          h: Math.max(0, size.height - topReserve - bottomReserve),
        })
      : null

  return (
    // Leinwand-Widget mit eigener Tastatursteuerung (Zoom, Verschieben, Pads ansagen) – role="application"
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      ref={(el) => {
        sizeRef(el)
        pz.wheelRef(el)
      }}
      role="application"
      aria-roledescription="Footprintvorschau"
      aria-label={label}
      aria-describedby={`${uid}-help`}
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
      className={cn(
        'group/canvas relative isolate min-h-0 overflow-hidden bg-canvas outline-none select-none',
        'focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-inset',
        pz.panning ? 'cursor-grabbing' : interactive ? 'cursor-crosshair' : '',
        className,
      )}
      {...pz.handlers}
      onPointerMove={(e) => {
        pz.handlers.onPointerMove(e)
        updateReadout(e)
        if (!pz.panning) setHover(padFromEvent(e))
      }}
      onPointerLeave={() => {
        setHover(null)
        updateReadout(null)
      }}
      onClick={(e) => {
        if (pz.wasDrag(e.timeStamp) || !onPadClick) return
        const i = padFromEvent(e)
        if (i !== null && pads[i]) onPadClick(pads[i])
      }}
      onKeyDown={onKeyDown}
      onBlur={() => setKeyIndex(null)}
    >
      {/* sanfter Lichthof in der Mitte der Leiterplatte */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_42%,rgba(120,140,170,0.07),transparent_62%)]"
      />
      {size.width > 0 && (
        <svg width={size.width} height={size.height} className="absolute inset-0 block" aria-hidden style={{ shapeRendering: 'geometricPrecision' }}>
          {showGrid && stepPx >= 14 && (
            <>
              <defs>
                <pattern id={`${uid}-grid`} width={stepPx} height={stepPx} patternUnits="userSpaceOnUse" x={gridOffsetX} y={gridOffsetY}>
                  <circle cx={0.75} cy={0.75} r={0.95} fill="var(--pf-pcb-grid)" />
                </pattern>
              </defs>
              <rect width={size.width} height={size.height} fill={`url(#${uid}-grid)`} />
            </>
          )}
          {node && hasSpec && spec && (
            <g transform={`matrix(${view.scale} 0 0 ${view.scale} ${view.tx} ${view.ty})`}>
              {/* Ursprung (Gehäusemitte) – unter dem Inhalt */}
              <path d={`M ${-px * 7} 0 H ${px * 7} M 0 ${-px * 7} V ${px * 7}`} stroke="rgba(233,238,247,0.4)" strokeWidth={px} />
              <FootprintContent
                spec={spec}
                visible={visible}
                px={px}
                scale={bucket}
                highlight={highlightSet}
                showPadNumbers={showPadNumbers}
                ballGrid={ballGrid}
              />
              {activePad && (
                <g style={{ pointerEvents: 'none' }}>
                  <PadShape pad={activePad} fill="rgba(255,255,255,0.12)" stroke={HOVER_COLOR} strokeWidth={px * 1.6} />
                </g>
              )}
            </g>
          )}
          {dimLayout && hasSpec && <DimensionLayer layout={dimLayout} />}
          {calloutLayout &&
            hasSpec &&
            calloutLayout.map(({ c, target, rect, anchor }, i) => (
              <g key={i} style={{ pointerEvents: 'none' }} aria-hidden>
                <title>{c.title}</title>
                <path d={`M ${target.x} ${target.y} L ${anchor.x} ${anchor.y}`} stroke={DIM_COLOR} strokeOpacity={0.7} strokeWidth={1} />
                <circle cx={target.x} cy={target.y} r={2.2} fill={DIM_COLOR} stroke="rgba(8,11,16,0.9)" strokeWidth={1} />
                <DimLabel x={rect.x + rect.w / 2} y={rect.y + rect.h / 2} width={rect.w} text={c.label} />
              </g>
            ))}
        </svg>
      )}

      {!hasSpec && <div className="absolute inset-0 flex items-center justify-center text-ui text-[#9AA4B6]">Kein Footprint</div>}

      {showInfo && hasSpec && spec && (
        <div className="pointer-events-none absolute left-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-2">
          <CanvasBadge tone="board">
            <span className="mono truncate font-medium text-[#EEF2F8]">{spec.name}</span>
            <span className={cn('whitespace-nowrap', CHROME_MUTED.board)}>
              {pads.length} {pads.length === 1 ? 'Pad' : 'Pads'}
              {size.width >= 460 && sizeBox && ` · ${formatMm(boxWidth(sizeBox))} × ${formatMm(boxHeight(sizeBox))} mm`}
              {size.width >= 460 && (spec.height ?? parsedCalc?.height)
                ? ` · H ${formatMm(spec.height ?? parsedCalc?.height ?? 0)}`
                : ''}
            </span>
          </CanvasBadge>
        </div>
      )}

      {/* Koordinaten + Maßstab */}
      {hasSpec && size.width >= 560 && (
        <div className="pointer-events-none absolute right-3 top-3 z-10 flex items-center gap-2">
          <CanvasBadge tone="board" className="mono tabular-nums">
            <span ref={readoutRef} className="text-[#E9EEF7]" />
            <span className="flex items-center gap-1.5 text-[#9AA4B6]">
              <span aria-hidden className="h-1.5 border-x border-b border-[#9AA4B6]" style={{ width: Math.round(scaleBar * view.scale) }} />
              {formatMm(scaleBar, scaleBar < 1 ? 1 : 0)} mm
            </span>
          </CanvasBadge>
        </div>
      )}

      {legendVisible && hasSpec && (
        <div
          ref={legendRef}
          role="group"
          aria-label="Lagen"
          className={cn(
            'absolute bottom-3 left-3 z-10 flex max-w-[calc(100%-1.5rem)] flex-wrap items-center gap-1 rounded-control p-1',
            CHROME_SURFACE.board,
            controls && interactive && 'max-w-[calc(100%-12rem)]',
          )}
          onPointerDown={(e) => e.stopPropagation()}
        >
          {present.map((layer) => {
            const on = visible[layer]
            return (
              <button
                key={layer}
                type="button"
                aria-pressed={on}
                title={`${LAYERS[layer].label} (${LAYERS[layer].altium}) ${on ? 'ausblenden' : 'einblenden'}`}
                onClick={() => toggleLayer(layer)}
                className={cn(
                  'flex h-6 items-center gap-1.5 rounded-[6px] px-2 text-2xs font-medium outline-none transition-colors focus-ring',
                  on ? 'text-[#E3E8F1] hover:bg-white/10' : 'text-[#8E97A8] hover:bg-white/5 hover:text-[#C9D1DE]',
                )}
              >
                <LegendSwatch layer={layer} on={on} />
                {LAYERS[layer].label}
              </button>
            )
          })}
        </div>
      )}

      {legendMode === 'menu' && hasSpec && (
        <div className="absolute bottom-3 left-3 z-10" onPointerDown={(e) => e.stopPropagation()}>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                className={cn(
                  'flex h-7 items-center gap-2 rounded-control px-2.5 text-2xs font-medium outline-none transition-colors focus-ring hover:bg-white/10',
                  CHROME_SURFACE.board,
                )}
              >
                <span aria-hidden className="flex -space-x-0.5">
                  {present
                    .filter((l) => visible[l])
                    .slice(0, 5)
                    .map((l) => (
                      <span key={l} className="size-2 rounded-full ring-1 ring-[#0D1118]" style={{ background: layerColor(l) }} />
                    ))}
                </span>
                Lagen
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" side="top" className="min-w-56">
              <DropdownMenuLabel>Lagen</DropdownMenuLabel>
              {present.map((l) => (
                <DropdownMenuCheckboxItem
                  key={l}
                  checked={visible[l]}
                  onCheckedChange={() => toggleLayer(l)}
                  onSelect={(e) => e.preventDefault()}
                >
                  <span className="flex items-center gap-2">
                    <span aria-hidden className="size-2.5 rounded-[3px]" style={{ background: layerColor(l) }} />
                    {LAYERS[l].label}
                  </span>
                </DropdownMenuCheckboxItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      )}

      {/* BGA: Ballnummern sind bei dieser Größe ausgeblendet – sagen, wie man sie sieht */}
      {ballNumbersHidden && hasSpec && interactive && legendMode === 'none' && size.width >= 300 && (
        <div className="pointer-events-none absolute bottom-3 left-3 z-10">
          <CanvasBadge tone="board">
            <ZoomIn aria-hidden className="size-3.5 text-[#9AA4B6]" />
            <span className={CHROME_MUTED.board}>Zum Lesen der Ballnummern hineinzoomen</span>
          </CanvasBadge>
        </div>
      )}

      {controls && interactive && hasSpec && (
        <CanvasZoomControls
          tone="board"
          zoom={pz.zoom}
          onZoomIn={() => pz.zoomBy(1.4, undefined, true)}
          onZoomOut={() => pz.zoomBy(1 / 1.4, undefined, true)}
          onFit={() => pz.fit(true)}
        />
      )}

      {activePad && tooltipAnchor && (
        <CanvasTooltip
          x={tooltipAnchor.x}
          y={tooltipAnchor.y - (Math.min(activePad.width, activePad.height) / 2) * view.scale}
          bounds={size}
          tone="board"
        >
          <div className="flex items-baseline gap-2">
            <span className="mono rounded-sm bg-white/12 px-1.5 text-2xs font-semibold text-white">{activePad.designator}</span>
            <span className="text-ui font-semibold text-white">
              {PAD_SHAPE_LABEL[activePad.shape] ?? activePad.shape}
              {activePad.shape === 'roundrect' && ` (${activePad.corner_radius_pct ?? 50} %)`}
            </span>
          </div>
          <div className="mono mt-1 tabular-nums text-[#D5DBE6]">
            {formatMm(activePad.width)} × {formatMm(activePad.height)} mm
            {activePad.rotation ? ` · ${formatMm(activePad.rotation, 0)}°` : ''}
          </div>
          <div className="mono tabular-nums text-[#9AA4B6]">
            X {formatMm(activePad.x, 3)} · Y {formatMm(activePad.y, 3)}
          </div>
          {activePad.hole ? (
            <div className="mono tabular-nums text-[#9AA4B6]">
              {(activePad.hole_length ?? 0) > activePad.hole
                ? `Langloch ${formatMm(activePad.hole_length ?? 0)} × ${formatMm(activePad.hole)}`
                : `Bohrung Ø ${formatMm(activePad.hole)}`}
              {activePad.plated === false ? ' · nicht durchkontaktiert' : ''}
            </div>
          ) : (
            <div className="text-[#9AA4B6]">
              {activePad.side === 'bottom' ? 'Unterseite' : 'Oberseite'} (SMD)
              {activePad.thermal ? ' · Thermal-Pad' : ''}
              {activePad.paste === false ? ' · ohne Paste' : ''}
            </div>
          )}
        </CanvasTooltip>
      )}

      {interactive && hasSpec && (
        <CanvasKeyHint tone="board">Pfeiltasten verschieben · +/− zoomen · 0 einpassen · N nächstes Pad</CanvasKeyHint>
      )}

      <p id={`${uid}-help`} className="sr-only">
        {spec
          ? `${pads.length} Pads: ${sortedPads
              .slice(0, 64)
              .map((i) => pads[i].designator)
              .join(', ')}${pads.length > 64 ? ' …' : ''}. Maße in Millimeter. `
          : ''}
        Mit N das nächste Pad ansagen, Pfeiltasten verschieben, Plus und Minus zoomen, 0 passt ein.
      </p>
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </div>
  )
}
