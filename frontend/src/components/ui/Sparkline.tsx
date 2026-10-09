import { useId } from 'react'
import { cn } from '@/lib/cn'

export interface SparklineProps {
  data: number[]
  width?: number
  height?: number
  /** Volle Breite des Containers (z. B. als Band am Kartenrand) */
  fluid?: boolean
  /** CSS-Farbe, Standard: Kupfer */
  color?: string
  /** Fläche unter der Linie füllen */
  area?: boolean
  className?: string
}

/** Kleine Verlaufslinie ohne Achsen (geglättet). Flache Reihen erscheinen als gestrichelte Grundlinie. */
export function Sparkline({
  data,
  width = 120,
  height = 36,
  fluid,
  color = 'var(--pf-accent)',
  area = true,
  className,
}: SparklineProps) {
  const id = useId().replace(/:/g, '')
  const vbWidth = fluid ? 200 : width
  const values = data.length > 1 ? data : [data[0] ?? 0, data[0] ?? 0]
  const min = Math.min(...values)
  const max = Math.max(...values)
  const flat = max === min
  const pad = 3
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * vbWidth
    const y = flat ? height - pad - 4 : pad + (1 - (v - min) / (max - min)) * (height - pad * 2)
    return [x, y] as const
  })

  // Catmull-Rom → kubische Bézierkurven
  let d = `M${pts[0][0]},${pts[0][1]}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[i + 2] ?? p2
    const c1x = p1[0] + (p2[0] - p0[0]) / 6
    const c1y = p1[1] + (p2[1] - p0[1]) / 6
    const c2x = p2[0] - (p3[0] - p1[0]) / 6
    const c2y = p2[1] - (p3[1] - p1[1]) / 6
    d += ` C${c1x},${c1y} ${c2x},${c2y} ${p2[0]},${p2[1]}`
  }
  const last = pts[pts.length - 1]

  return (
    <svg
      width={fluid ? '100%' : width}
      height={height}
      viewBox={`0 0 ${vbWidth} ${height}`}
      preserveAspectRatio="none"
      className={cn('block overflow-visible', className)}
      aria-hidden
    >
      <defs>
        <linearGradient id={`sl-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={flat ? 0.1 : 0.3} />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {area && <path d={`${d} L${vbWidth},${height} L0,${height} Z`} fill={`url(#sl-${id})`} />}
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeOpacity={flat ? 0.4 : 1}
        strokeDasharray={flat ? '2 5' : undefined}
        vectorEffect="non-scaling-stroke"
      />
      {!flat && !fluid && <circle cx={last[0]} cy={last[1]} r={2.5} fill={color} />}
    </svg>
  )
}
