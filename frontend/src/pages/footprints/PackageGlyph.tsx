/**
 * Kleine Draufsicht-Glyphen je Gehäusefamilie (Linienstil wie Lucide, 24er-Raster, `currentColor`).
 * Dekorativ – die Familie steht immer auch als Text daneben.
 */
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

const BODY = { fill: 'currentColor', fillOpacity: 0.1 }
const SOLID = { fill: 'currentColor', stroke: 'none' }
const TINT = { fill: 'currentColor', fillOpacity: 0.38, stroke: 'none' }

const GLYPHS: Record<string, ReactNode> = {
  chip: (
    <>
      <rect x="3.5" y="7.5" width="17" height="9" rx="1.5" {...BODY} />
      <rect x="3.5" y="7.5" width="4" height="9" rx="1.2" {...TINT} />
      <rect x="16.5" y="7.5" width="4" height="9" rx="1.2" {...TINT} />
      <path d="M7.5 7.5v9M16.5 7.5v9" />
    </>
  ),
  molded: (
    <>
      <rect x="6" y="6.5" width="12" height="11" rx="1" {...BODY} />
      <path d="M6 10H3.5v4H6M18 10h2.5v4H18M8.75 6.5v11" />
    </>
  ),
  melf: (
    <>
      <rect x="3.5" y="8" width="17" height="8" rx="4" {...BODY} />
      <path d="M7.5 8.25v7.5M16.5 8.25v7.5" />
    </>
  ),
  sod: (
    <>
      <rect x="7" y="8" width="10" height="8" rx="1" {...BODY} />
      <rect x="3" y="10.75" width="4" height="2.5" rx=".5" {...TINT} />
      <rect x="17" y="10.75" width="4" height="2.5" rx=".5" {...TINT} />
      <path d="M9.25 8v8" />
    </>
  ),
  do214: (
    <>
      <rect x="6.5" y="6.5" width="11" height="11" rx="1" {...BODY} />
      <rect x="3" y="9" width="3.5" height="6" rx=".6" {...TINT} />
      <rect x="17.5" y="9" width="3.5" height="6" rx=".6" {...TINT} />
      <path d="M9 6.5v11" />
    </>
  ),
  sot23: (
    <>
      <rect x="6" y="8" width="12" height="8" rx="1" {...BODY} />
      <path d="M8.5 16v3.5M15.5 16v3.5M12 8V4.5" />
    </>
  ),
  sc70: (
    <>
      <rect x="7" y="9" width="10" height="6" rx="1" {...BODY} />
      <path d="M8.75 15v3.5M12 15v3.5M15.25 15v3.5M8.75 9V5.5M12 9V5.5M15.25 9V5.5" />
    </>
  ),
  sot523: (
    <>
      <rect x="8" y="9.5" width="8" height="5" rx="1" {...BODY} />
      <path d="M10 14.5v3M14 14.5v3M12 9.5v-3" />
    </>
  ),
  sot89: (
    <>
      <rect x="5.5" y="5" width="13" height="9.5" rx="1" {...BODY} />
      <rect x="10" y="8.5" width="4" height="11" rx=".6" {...TINT} />
      <path d="M7.75 14.5v5M16.25 14.5v5" />
    </>
  ),
  sot223: (
    <>
      <rect x="8" y="3.5" width="8" height="5.5" rx=".6" {...TINT} />
      <rect x="4.5" y="9" width="15" height="8" rx="1" {...BODY} />
      <path d="M7.5 17v3.5M12 17v3.5M16.5 17v3.5" />
    </>
  ),
  dpak: (
    <>
      <rect x="7" y="3.5" width="10" height="5.5" rx=".6" {...TINT} />
      <rect x="5" y="9" width="14" height="8.5" rx="1" {...BODY} />
      <path d="M8.5 17.5v3M15.5 17.5v3" />
    </>
  ),
  gullwing: (
    <>
      <rect x="7" y="4" width="10" height="16" rx="1" {...BODY} />
      <path d="M3.5 7H7M3.5 10.33H7M3.5 13.67H7M3.5 17H7M17 7h3.5M17 10.33h3.5M17 13.67h3.5M17 17h3.5" />
      <circle cx="9.25" cy="6.25" r=".9" {...SOLID} />
    </>
  ),
  qfp: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="1" {...BODY} />
      <path d="M9 6V3M12 6V3M15 6V3M9 18v3M12 18v3M15 18v3M6 9H3M6 12H3M6 15H3M18 9h3M18 12h3M18 15h3" />
      <circle cx="8.3" cy="8.3" r=".9" {...SOLID} />
    </>
  ),
  nolead: (
    <>
      <rect x="4.5" y="4.5" width="15" height="15" rx="1.5" {...BODY} />
      <rect x="9" y="9" width="6" height="6" rx=".7" {...TINT} />
      <path d="M8.5 4.5v2M12 4.5v2M15.5 4.5v2M8.5 19.5v-2M12 19.5v-2M15.5 19.5v-2M4.5 8.5h2M4.5 12h2M4.5 15.5h2M19.5 8.5h-2M19.5 12h-2M19.5 15.5h-2" />
    </>
  ),
  bga: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="1.5" {...BODY} />
      <path d="M4 8 8 4" />
      {[8, 12, 16].flatMap((y) =>
        [8, 12, 16].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.35" {...SOLID} />),
      )}
    </>
  ),
  dip: (
    <>
      <rect x="7.5" y="3" width="9" height="18" rx="1" {...BODY} />
      <path d="M10.5 3a1.5 1.5 0 0 0 3 0M4.5 6.5h3M4.5 10h3M4.5 13.5h3M4.5 17h3M16.5 6.5h3M16.5 10h3M16.5 13.5h3M16.5 17h3" />
    </>
  ),
  axial: (
    <>
      <path d="M2.5 12H7M17 12h4.5" />
      <rect x="7" y="8.5" width="10" height="7" rx="3" {...BODY} />
      <path d="M9.75 8.75v6.5" />
    </>
  ),
  radial: (
    <>
      <circle cx="12" cy="12" r="8.5" {...BODY} />
      <path d="M16.5 4.8a8.5 8.5 0 0 1 0 14.4" strokeWidth="2.5" strokeOpacity="0.45" />
      <circle cx="9" cy="12" r="1.5" {...SOLID} />
      <circle cx="15" cy="12" r="1.5" {...SOLID} />
    </>
  ),
  to92: (
    <>
      <path d="M4.5 15.5h15a7.5 7.5 0 0 0-15 0Z" {...BODY} />
      <circle cx="8" cy="12.75" r="1.25" {...SOLID} />
      <circle cx="12" cy="12.75" r="1.25" {...SOLID} />
      <circle cx="16" cy="12.75" r="1.25" {...SOLID} />
    </>
  ),
  to220: (
    <>
      <rect x="5.5" y="3" width="13" height="6.5" rx=".8" {...TINT} />
      <circle cx="12" cy="6.25" r="1.6" />
      <rect x="5.5" y="9.5" width="13" height="7" rx=".8" {...BODY} />
      <path d="M8.5 16.5V21M12 16.5V21M15.5 16.5V21" />
    </>
  ),
  pin_header: (
    <>
      <rect x="2.75" y="6.75" width="18.5" height="10.5" rx="1" {...BODY} />
      {[6, 10, 14, 18].flatMap((x) =>
        [9.75, 14.25].map((y) => <rect key={`${x}-${y}`} x={x - 1.2} y={y - 1.2} width="2.4" height="2.4" rx=".3" {...SOLID} />),
      )}
    </>
  ),
}

const FALLBACK = (
  <>
    <rect x="6" y="5" width="12" height="14" rx="1" {...BODY} />
    <path d="M3.5 8.5H6M3.5 12H6M3.5 15.5H6M18 8.5h2.5M18 12h2.5M18 15.5h2.5" />
  </>
)

export function PackageGlyph({ family, className }: { family: string | null | undefined; className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('size-5 shrink-0', className)}
    >
      {(family && GLYPHS[family]) || FALLBACK}
    </svg>
  )
}
