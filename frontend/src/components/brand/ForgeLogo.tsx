import { useId } from 'react'
import { cn } from '@/lib/cn'

export interface ForgeMarkProps {
  size?: number
  /** Weicher Kupfer-Schein hinter dem Zeichen */
  glow?: boolean
  /** Funke funkelt, Glut pulsiert (Hero/Ladeanzeige) */
  animated?: boolean
  className?: string
  title?: string
}

/** Bildmarke: Kupfer-Quadrat mit stilisiertem IC-Gehäuse und Funken. */
export function ForgeMark({ size = 32, glow, animated, className, title = 'PartForge' }: ForgeMarkProps) {
  const uid = useId().replace(/:/g, '')
  const g = (name: string) => `${name}-${uid}`
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role={title ? 'img' : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      className={cn('shrink-0 overflow-visible', className)}
      style={glow ? { filter: 'drop-shadow(0 6px 18px var(--pf-ember-strong))' } : undefined}
    >
      <defs>
        <linearGradient id={g('bg')} x1="4" y1="2" x2="60" y2="62" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFC27A" />
          <stop offset="0.45" stopColor="#FF8A3D" />
          <stop offset="1" stopColor="#E8467C" />
        </linearGradient>
        <linearGradient id={g('hl')} x1="32" y1="0" x2="32" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#fff" stopOpacity="0.65" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <radialGradient id={g('shade')} cx="0.5" cy="1.05" r="0.75">
          <stop offset="0" stopColor="#7A1F2E" stopOpacity="0.35" />
          <stop offset="1" stopColor="#7A1F2E" stopOpacity="0" />
        </radialGradient>
        <radialGradient id={g('spark')} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FFFFFF" />
          <stop offset="0.45" stopColor="#FFE6C2" />
          <stop offset="1" stopColor="#FFB067" />
        </radialGradient>
        <radialGradient id={g('ember')} cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#FF9A4D" stopOpacity="0.95" />
          <stop offset="1" stopColor="#FF6B1A" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Kupfer-Quadrat */}
      <rect x="0" y="0" width="64" height="64" rx="16" fill={`url(#${g('bg')})`} />
      <rect x="0" y="0" width="64" height="64" rx="16" fill={`url(#${g('shade')})`} />
      <rect x="0.75" y="0.75" width="62.5" height="62.5" rx="15.25" fill="none" stroke={`url(#${g('hl')})`} strokeWidth="1.5" />

      {/* IC-Gehäuse mit Pins links/rechts */}
      <g fill="#1A0C03" fillOpacity="0.9">
        <rect x="21" y="13" width="22" height="38" rx="4.5" />
        <rect x="13.5" y="18.5" width="9" height="4.5" rx="1.6" />
        <rect x="13.5" y="29.75" width="9" height="4.5" rx="1.6" />
        <rect x="13.5" y="41" width="9" height="4.5" rx="1.6" />
        <rect x="41.5" y="18.5" width="9" height="4.5" rx="1.6" />
        <rect x="41.5" y="29.75" width="9" height="4.5" rx="1.6" />
        <rect x="41.5" y="41" width="9" height="4.5" rx="1.6" />
      </g>
      <circle cx="26.5" cy="18.5" r="1.7" fill="#FF9A55" />

      {/* Funke (Glut + Vierstrahl-Stern) */}
      <circle
        cx="32"
        cy="33"
        r="9"
        fill={`url(#${g('ember')})`}
        className={animated ? 'animate-pulse-soft' : undefined}
        style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
      />
      <path
        d="M32 23.5 Q33.9 31.1 41.5 33 Q33.9 34.9 32 42.5 Q30.1 34.9 22.5 33 Q30.1 31.1 32 23.5 Z"
        fill={`url(#${g('spark')})`}
        className={animated ? 'origin-center animate-[pf-twinkle_3.2s_ease-in-out_infinite]' : undefined}
        style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
      />
    </svg>
  )
}

export interface ForgeLogoProps extends ForgeMarkProps {
  /** full = Zeichen + Wortmarke, mark = nur Zeichen */
  variant?: 'full' | 'mark'
  /** Zusatz unter der Wortmarke (z. B. Version) */
  subtitle?: string
}

/** Logo „PartForge“ (Zeichen + Wortmarke). */
export function ForgeLogo({ variant = 'full', size = 28, subtitle, className, ...mark }: ForgeLogoProps) {
  if (variant === 'mark') return <ForgeMark size={size} className={className} {...mark} />
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      {/* Bildmarke dekorativ – die Wortmarke daneben nennt den Namen bereits */}
      <ForgeMark size={size} {...mark} title="" />
      <span className="flex flex-col leading-none">
        <span className="text-md font-semibold tracking-[-0.02em] text-fg">
          Part<span className="text-gradient-forge">Forge</span>
        </span>
        {subtitle && <span className="mt-1 text-2xs font-medium text-fg-subtle">{subtitle}</span>}
      </span>
    </span>
  )
}
