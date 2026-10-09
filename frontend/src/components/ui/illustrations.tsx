import { useId, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type IllustrationName =
  | 'no-library'
  | 'no-parts'
  | 'drop-pdf'
  | 'search-empty'
  | 'all-good'
  | 'forge'
  | 'offline'

/** Kleiner Vierstrahl-Funke */
function Spark({ x, y, r = 5, fill }: { x: number; y: number; r?: number; fill: string }) {
  const k = r * 0.28
  return (
    <path
      d={`M${x} ${y - r} Q${x + k} ${y - k} ${x + r} ${y} Q${x + k} ${y + k} ${x} ${y + r} Q${x - k} ${y + k} ${x - r} ${y} Q${x - k} ${y - k} ${x} ${y - r}Z`}
      fill={fill}
    />
  )
}

function Frame({ children, gid, className }: { children: ReactNode; gid: string; className?: string }) {
  return (
    <svg
      viewBox="0 0 160 120"
      fill="none"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('text-fg-subtle', className)}
      aria-hidden
    >
      <defs>
        <linearGradient id={`${gid}-forge`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#FFC27A" />
          <stop offset="45%" stopColor="#FF8A3D" />
          <stop offset="100%" stopColor="#E8467C" />
        </linearGradient>
        <linearGradient id={`${gid}-spark`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#38BDF8" />
          <stop offset="50%" stopColor="#818CF8" />
          <stop offset="100%" stopColor="#C084FC" />
        </linearGradient>
        <radialGradient id={`${gid}-glow`} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0%" stopColor="var(--pf-accent)" stopOpacity="0.35" />
          <stop offset="100%" stopColor="var(--pf-accent)" stopOpacity="0" />
        </radialGradient>
      </defs>
      {children}
    </svg>
  )
}

const FILL = 'var(--pf-surface-2)'
const FILL_2 = 'var(--pf-surface-3)'
const ACCENT = 'var(--pf-accent)'
const BG = 'var(--pf-bg-elev)'

export function Illustration({ name, className }: { name: IllustrationName; className?: string }) {
  const gid = `il${useId().replace(/:/g, '')}`
  const forge = `url(#${gid}-forge)`
  const spark = `url(#${gid}-spark)`
  const glow = `url(#${gid}-glow)`

  switch (name) {
    case 'no-library':
      return (
        <Frame gid={gid} className={className}>
          <ellipse cx="72" cy="100" rx="40" ry="5" fill="currentColor" opacity="0.08" stroke="none" />
          <path d="M36 30v54c0 6.1 16.1 11 36 11s36-4.9 36-11V30" fill={FILL} stroke="currentColor" />
          <path d="M36 48c0 6.1 16.1 11 36 11s36-4.9 36-11" stroke="currentColor" opacity="0.55" />
          <path d="M36 66c0 6.1 16.1 11 36 11s36-4.9 36-11" stroke="currentColor" opacity="0.55" />
          <ellipse cx="72" cy="30" rx="36" ry="11" fill={FILL_2} stroke="currentColor" />
          <path d="M46 58h9M46 76h9" stroke={ACCENT} strokeWidth="2" />
          <path d="M60 58h4M60 76h4" stroke="currentColor" opacity="0.6" strokeWidth="2" />
          <circle cx="112" cy="86" r="20" fill={glow} stroke="none" />
          <circle cx="112" cy="86" r="13" fill={BG} stroke={ACCENT} strokeWidth="1.75" />
          <path d="M112 80v12M106 86h12" stroke={ACCENT} strokeWidth="2" />
          <Spark x={124} y={26} r={5} fill={forge} />
          <Spark x={20} y={46} r={3.5} fill={ACCENT} />
        </Frame>
      )
    case 'no-parts':
      return (
        <Frame gid={gid} className={className}>
          <ellipse cx="80" cy="102" rx="34" ry="4.5" fill="currentColor" opacity="0.08" stroke="none" />
          {[44, 54, 64, 74].map((y) => (
            <g key={y}>
              <path d={`M42 ${y}h10`} stroke="currentColor" opacity="0.7" />
              <path d={`M108 ${y}h10`} stroke="currentColor" opacity="0.7" />
            </g>
          ))}
          <rect x="52" y="34" width="56" height="52" rx="7" fill={FILL} stroke="currentColor" strokeDasharray="4 4" />
          <circle cx="61" cy="43" r="2.6" fill={ACCENT} stroke="none" />
          <path d="M66 58h28M66 66h18" stroke="currentColor" opacity="0.45" />
          <circle cx="126" cy="30" r="16" fill={glow} stroke="none" />
          <Spark x={126} y={30} r={6} fill={forge} />
          <Spark x={34} y={24} r={3.5} fill={ACCENT} />
          <Spark x={138} y={56} r={2.5} fill={ACCENT} />
        </Frame>
      )
    case 'drop-pdf':
      return (
        <Frame gid={gid} className={className}>
          <ellipse cx="80" cy="108" rx="36" ry="4.5" fill="currentColor" opacity="0.08" stroke="none" />
          <path d="M56 14h34l18 18v64a4 4 0 0 1-4 4H56a4 4 0 0 1-4-4V18a4 4 0 0 1 4-4Z" fill={FILL} stroke="currentColor" />
          <path d="M90 14v14a4 4 0 0 0 4 4h14" fill={FILL_2} stroke="currentColor" />
          <path d="M62 46h30M62 54h38M62 62h24M62 70h32" stroke="currentColor" opacity="0.45" />
          <rect x="40" y="74" width="34" height="16" rx="4" fill={spark} stroke="none" />
          <text
            x="57"
            y="85.5"
            textAnchor="middle"
            fontSize="9"
            fontWeight="700"
            letterSpacing="0.06em"
            fill="var(--pf-on-spark)"
            stroke="none"
            fontFamily="Inter Variable, sans-serif"
          >
            PDF
          </text>
          <circle cx="108" cy="90" r="18" fill="var(--pf-spark-b)" opacity="0.16" stroke="none" />
          <circle cx="108" cy="90" r="12" fill={BG} stroke="var(--pf-spark-b)" strokeWidth="1.75" />
          <path d="M108 84v11M103 90.5l5 5 5-5" stroke="var(--pf-spark-b)" strokeWidth="2" />
          <Spark x={128} y={30} r={6} fill={spark} />
          <Spark x={30} y={34} r={4} fill={spark} />
          <Spark x={138} y={58} r={2.5} fill="var(--pf-spark-a)" />
        </Frame>
      )
    case 'search-empty':
      return (
        <Frame gid={gid} className={className}>
          {[26, 46, 66].map((y, i) => (
            <g key={y} opacity={1 - i * 0.22}>
              <rect x="28" y={y} width="78" height="13" rx="4" fill={FILL} stroke="currentColor" opacity="0.8" />
              <circle cx="37" cy={y + 6.5} r="2.2" fill="currentColor" stroke="none" opacity="0.6" />
              <path d={`M45 ${y + 6.5}h${36 - i * 8}`} stroke="currentColor" opacity="0.45" />
            </g>
          ))}
          <circle cx="108" cy="72" r="24" fill={glow} stroke="none" />
          <circle cx="104" cy="68" r="19" fill={BG} fillOpacity="0.85" stroke="currentColor" strokeWidth="2" />
          <path d="M118 82l15 15" stroke={ACCENT} strokeWidth="5" />
          <path d="M98 62l12 12M110 62l-12 12" stroke={ACCENT} strokeWidth="2" />
        </Frame>
      )
    case 'all-good':
      return (
        <Frame gid={gid} className={className}>
          <circle cx="80" cy="58" r="44" fill="var(--pf-success)" opacity="0.08" stroke="none" />
          <path
            d="M80 18l30 11v23c0 21-13 35-30 44-17-9-30-23-30-44V29l30-11Z"
            fill="color-mix(in oklab, var(--pf-success) 14%, var(--pf-surface))"
            stroke="var(--pf-success)"
          />
          <path d="M67 57l9 9 18-20" stroke="var(--pf-success)" strokeWidth="3" />
          <Spark x={124} y={28} r={6} fill={forge} />
          <Spark x={36} y={36} r={4} fill={ACCENT} />
          <Spark x={130} y={74} r={3} fill="var(--pf-success)" />
        </Frame>
      )
    case 'forge':
      return (
        <Frame gid={gid} className={className}>
          <ellipse cx="86" cy="100" rx="40" ry="4.5" fill="currentColor" opacity="0.08" stroke="none" />
          <ellipse cx="88" cy="46" rx="34" ry="20" fill={glow} stroke="none" />
          <path
            d="M50 52h72v10c-12 0-20 4-22 10v12l14 6v6H58v-6l14-6V72c-2-6-10-10-22-10-10 0-20-4-26-8 8-1.5 16-2 26-2Z"
            fill={FILL}
            stroke="currentColor"
          />
          <path d="M50 52h72" stroke="currentColor" />
          <rect x="74" y="45" width="28" height="7" rx="3.5" fill={forge} stroke="none" />
          <path d="M84 41l-5-11M90 40l2-14M96 41l7-10M80 43l-11-6M100 44l11-5" stroke={ACCENT} strokeWidth="1.6" />
          <circle cx="76" cy="26" r="1.6" fill={ACCENT} stroke="none" />
          <circle cx="108" cy="28" r="1.4" fill="#FFC27A" stroke="none" />
          <circle cx="64" cy="34" r="1.2" fill="#FFC27A" stroke="none" />
          <Spark x={120} y={20} r={5} fill={forge} />
        </Frame>
      )
    case 'offline':
      return (
        <Frame gid={gid} className={className}>
          <path d="M24 70h28" stroke="currentColor" />
          <rect x="52" y="58" width="22" height="24" rx="5" fill={FILL} stroke="currentColor" />
          <path d="M74 64h8M74 76h8" stroke="currentColor" />
          <path d="M136 70h-28" stroke="currentColor" />
          <rect x="88" y="58" width="22" height="24" rx="5" fill={FILL} stroke="currentColor" />
          <path d="M82 50l-4 8 6 4-4 8" stroke="var(--pf-danger)" strokeWidth="2" />
          <Spark x={84} y={36} r={5} fill="var(--pf-danger)" />
        </Frame>
      )
  }
}
