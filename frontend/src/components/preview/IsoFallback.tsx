import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Rückfall ohne WebGL: isometrische SVG-Zeichnung der 3D-Körper (Maleralgorithmus, ohne three.js).
 * Zeigt Leiterplatte, Pads und die extrudierten Körper schattiert – keine Drehung, aber ein ehrliches Bild des Gehäuses.
 */
import {} from 'react'
import { cn } from '@/lib/cn'
import { boxHeight, boxWidth, footprintBBox, formatMm, isEmptyBox, padOutline, type FootprintSpec, type Point } from '@/lib/geometry'
import { CanvasBadge } from './CanvasChrome'

const AZ = (32 * Math.PI) / 180
const EL = (32 * Math.PI) / 180
const LIGHT = { x: 0.45, y: -0.55, z: 0.7 }

interface P3 {
  x: number
  y: number
  z: number
}

function project(p: P3): Point {
  const xr = p.x * Math.cos(AZ) - p.y * Math.sin(AZ)
  const yr = p.x * Math.sin(AZ) + p.y * Math.cos(AZ)
  return { x: xr, y: -(yr * Math.sin(EL) + p.z * Math.cos(EL)) }
}

const depth = (p: P3) => p.x * Math.sin(AZ) + p.y * Math.cos(AZ) - p.z * 0.01

function shade(hex: string, factor: number): string {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.replace(/(.)/g, '$1$1') : h.slice(0, 6), 16)
  const r = Math.min(255, Math.round(((n >> 16) & 255) * factor))
  const g = Math.min(255, Math.round(((n >> 8) & 255) * factor))
  const b = Math.min(255, Math.round((n & 255) * factor))
  return `rgb(${r},${g},${b})`
}

function ccw(pts: Point[]): Point[] {
  let area = 0
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % pts.length]
    area += a.x * b.y - b.x * a.y
  }
  return area < 0 ? [...pts].reverse() : pts
}

interface Face {
  points: Point[]
  fill: string
  stroke?: string
  depth: number
  order: number
}

function prismFaces(outline: Point[], z0: number, z1: number, color: string, order: number): Face[] {
  const pts = ccw(outline)
  const faces: Face[] = []
  for (let i = 0; i < pts.length; i++) {
    const a = pts[i]
    const b = pts[(i + 1) % pts.length]
    // Außennormale (CCW): (dy, −dx)
    const nx = b.y - a.y
    const ny = -(b.x - a.x)
    const len = Math.hypot(nx, ny) || 1
    // zum Betrachter (vorn = −y nach Drehung)?
    const facing = (nx / len) * Math.sin(AZ) + (ny / len) * Math.cos(AZ)
    if (facing >= 0) continue
    const lambert = Math.max(0, (nx / len) * LIGHT.x + (ny / len) * LIGHT.y)
    faces.push({
      points: [project({ ...a, z: z0 }), project({ ...b, z: z0 }), project({ ...b, z: z1 }), project({ ...a, z: z1 })],
      fill: shade(color, 0.55 + lambert * 0.6),
      depth: depth({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: z0 }),
      order,
    })
  }
  faces.push({
    points: pts.map((p) => project({ ...p, z: z1 })),
    fill: shade(color, 1.18),
    stroke: shade(color, 1.45),
    depth: -Infinity,
    order,
  })
  return faces
}

export function IsoFallback({ spec, className }: { spec: FootprintSpec; className?: string }) {
  useI18n()
  const { faces, viewBox, size, height } = useLocalizedMemo(() => {
    const content = footprintBBox(spec, { bodies: true })
    const box = isEmptyBox(content) ? { x1: -1, y1: -1, x2: 1, y2: 1 } : content
    const margin = Math.max(0.8, Math.max(boxWidth(box), boxHeight(box)) * 0.12)
    const thickness = Math.min(1.6, Math.max(0.22, Math.max(boxWidth(box), boxHeight(box)) * 0.09))
    const board = [
      { x: box.x1 - margin, y: box.y1 - margin },
      { x: box.x2 + margin, y: box.y1 - margin },
      { x: box.x2 + margin, y: box.y2 + margin },
      { x: box.x1 - margin, y: box.y2 + margin },
    ]
    const all: Face[] = prismFaces(board, -thickness, 0, '#0F3A2C', 0)
    // Pads flach auf der Oberseite
    ;(spec.pads ?? []).forEach((p) => {
      const r = ((p.rotation ?? 0) * Math.PI) / 180
      const outline = padOutline(p, 4).map((q) => ({
        x: p.x + q.x * Math.cos(r) - q.y * Math.sin(r),
        y: p.y + q.x * Math.sin(r) + q.y * Math.cos(r),
        z: 0.002,
      }))
      all.push({ points: outline.map(project), fill: '#C99B52', stroke: '#E2BC7A', depth: -Infinity, order: 1 })
    })
    // Körper: erst nach Unterkante, dann von hinten nach vorn
    const bodies = [...(spec.bodies ?? [])].sort((a, b) => {
      if (a.z_bottom !== b.z_bottom) return a.z_bottom - b.z_bottom
      const ca = a.outline.reduce((s, p) => s + depth({ ...p, z: 0 }), 0) / a.outline.length
      const cb = b.outline.reduce((s, p) => s + depth({ ...p, z: 0 }), 0) / b.outline.length
      return cb - ca
    })
    bodies.forEach((b, i) => {
      if (b.outline.length >= 3) all.push(...prismFaces(b.outline, b.z_bottom, b.z_top, b.color ?? '#2B2B2B', 2 + i))
    })
    // Sortierung: Gruppe (order), innerhalb der Gruppe Seitenflächen hinten → vorn, Deckfläche zuletzt
    all.sort((a, b) => (a.order !== b.order ? a.order - b.order : b.depth === a.depth ? 0 : b.depth > a.depth ? 1 : -1))
    let x1 = Infinity
    let y1 = Infinity
    let x2 = -Infinity
    let y2 = -Infinity
    for (const f of all)
      for (const p of f.points) {
        x1 = Math.min(x1, p.x)
        y1 = Math.min(y1, p.y)
        x2 = Math.max(x2, p.x)
        y2 = Math.max(y2, p.y)
      }
    const pad = Math.max(x2 - x1, y2 - y1) * 0.08
    const h = (spec.bodies ?? []).reduce((m, b) => Math.max(m, b.z_top), 0)
    return {
      faces: all,
      viewBox: `${x1 - pad} ${y1 - pad} ${x2 - x1 + pad * 2} ${y2 - y1 + pad * 2}`,
      size: box,
      height: h,
    }
  }, [spec])

  return (
    <div className={cn('relative isolate min-h-0 overflow-hidden bg-[radial-gradient(120%_90%_at_50%_35%,#121a26_0%,#080b10_55%,#05070a_100%)]', className)}>
      <svg viewBox={viewBox} className="absolute inset-0 size-full p-6" role="img" aria-label={tr("Isometrische Ansicht {value0}", { value0: String(spec.name) })}>
        {faces.map((f, i) => (
          <polygon
            key={i}
            points={f.points.map((p) => `${p.x},${p.y}`).join(' ')}
            fill={f.fill}
            stroke={f.stroke ?? f.fill}
            strokeWidth={0.01}
            strokeLinejoin="round"
          />
        ))}
      </svg>
      <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex items-center gap-2">
        <CanvasBadge tone="board">
          <span className="mono font-medium text-[#EEF2F8]">{spec.name}</span>
          <span className="text-[#9AA4B6]">
            {formatMm(boxWidth(size))} × {formatMm(boxHeight(size))} × {formatMm(height)} mm
          </span>
        </CanvasBadge>
      </div>
    </div>
  )
}
