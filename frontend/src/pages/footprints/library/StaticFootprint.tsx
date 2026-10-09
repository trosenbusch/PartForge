/**
 * Ruhige Footprint-Miniatur (SVG aus dem Spec, ohne Interaktion) für Katalogkarten: Kupfer, Bohrungen,
 * Bestückungsdruck, Bestückungszeichnung und Courtyard in den Farben der Leiterplatten-Leinwand.
 */
import { memo } from 'react'
import {
  boxExpand,
  DRILL_COLOR,
  footprintBBox,
  isEmptyBox,
  layerColor,
  padCornerRadius,
  padLayer,
  type Arc,
  type FootprintSpec,
  type Pad,
} from '@/lib/geometry'

const SHOWN = new Set(['top_silk', 'courtyard', 'assembly'])

function PadShape({ pad, fill }: { pad: Pad; fill: string }) {
  const { x, width: w, height: h } = pad
  const y = -pad.y
  const transform = pad.rotation ? `rotate(${-pad.rotation} ${x} ${y})` : undefined
  if (pad.shape === 'circle' && Math.abs(w - h) < 1e-9) return <circle cx={x} cy={y} r={w / 2} fill={fill} />
  const r = padCornerRadius(pad)
  return <rect x={x - w / 2} y={y - h / 2} width={w} height={h} rx={r || undefined} fill={fill} transform={transform} />
}

function arcPath(a: Arc): string | null {
  const span = ((((a.end ?? 360) - (a.start ?? 0)) % 360) + 360) % 360
  if (span === 0 || span >= 359.999) return null
  const s = ((a.start ?? 0) * Math.PI) / 180
  const e = (((a.start ?? 0) + span) * Math.PI) / 180
  const x1 = a.cx + a.r * Math.cos(s)
  const y1 = -(a.cy + a.r * Math.sin(s))
  const x2 = a.cx + a.r * Math.cos(e)
  const y2 = -(a.cy + a.r * Math.sin(e))
  return `M ${x1} ${y1} A ${a.r} ${a.r} 0 ${span > 180 ? 1 : 0} 0 ${x2} ${y2}`
}

export const StaticFootprint = memo(function StaticFootprint({ spec, className }: { spec: FootprintSpec; className?: string }) {
  const raw = footprintBBox(spec, { bodies: false })
  if (isEmptyBox(raw)) return null
  const pad = Math.max(0.25, Math.max(raw.x2 - raw.x1, raw.y2 - raw.y1) * 0.06)
  const b = boxExpand(raw, pad)
  const w = b.x2 - b.x1
  const h = b.y2 - b.y1
  const px = Math.max(w, h) / 160 // ~1 Bildpunkt bei 160 px Breite
  return (
    <svg
      viewBox={`${b.x1} ${-b.y2} ${w} ${h}`}
      className={className}
      role="img"
      aria-label={`Footprint ${spec.name}`}
      style={{ shapeRendering: 'geometricPrecision' }}
    >
      {(spec.tracks ?? [])
        .filter((t) => SHOWN.has(t.layer))
        .map((t, i) => (
          <line
            key={`t${i}`}
            x1={t.x1}
            y1={-t.y1}
            x2={t.x2}
            y2={-t.y2}
            stroke={layerColor(t.layer)}
            strokeWidth={t.layer === 'top_silk' ? Math.min(Math.max(t.width, px * 1.2), px * 3) : px * 1.1}
            strokeOpacity={t.layer === 'assembly' ? 0.55 : 1}
            strokeLinecap="round"
            strokeDasharray={t.layer === 'courtyard' ? `${px * 4} ${px * 3}` : undefined}
          />
        ))}
      {(spec.arcs ?? [])
        .filter((a) => SHOWN.has(a.layer))
        .map((a, i) => {
          const d = arcPath(a)
          const color = layerColor(a.layer)
          if (!d) {
            if (a.width >= 2 * a.r - 1e-9) return <circle key={`a${i}`} cx={a.cx} cy={-a.cy} r={a.r + a.width / 2} fill={color} />
            return <circle key={`a${i}`} cx={a.cx} cy={-a.cy} r={a.r} fill="none" stroke={color} strokeWidth={Math.max(a.width, px)} />
          }
          return <path key={`a${i}`} d={d} fill="none" stroke={color} strokeWidth={Math.max(a.width, px)} strokeLinecap="round" />
        })}
      {(spec.pads ?? []).map((p, i) => {
        const layer = padLayer(p)
        return (
          <g key={`p${i}`}>
            <PadShape pad={p} fill={layerColor(layer)} />
            {p.hole ? <circle cx={p.x} cy={-p.y} r={p.hole / 2} fill={DRILL_COLOR} /> : null}
          </g>
        )
      })}
    </svg>
  )
})
