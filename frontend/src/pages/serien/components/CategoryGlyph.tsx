/**
 * Schaltzeichen der Serien-Kategorien als Linienzeichnung (dekorativ): Widerstand (IEC), Kondensator, Induktivität,
 * Ferrit. Linien in `currentColor`, die Anschlüsse enden in Lötaugen – wie auf der Leiterplatte.
 */
import { cn } from '@/lib/cn'
import type { GlyphKind } from '../model/categories'

function Body({ kind }: { kind: GlyphKind }) {
  switch (kind) {
    case 'resistor':
      return (
        <>
          <path d="M14 24h26M80 24h26" />
          <rect x="40" y="15" width="40" height="18" rx="1.5" />
        </>
      )
    case 'capacitor':
      return (
        <>
          <path d="M14 24h40M66 24h40" />
          <path d="M54 9v30M66 9v30" strokeWidth={2.75} />
        </>
      )
    case 'inductor':
      return (
        <>
          <path d="M14 24h22M84 24h22" />
          <path d="M36 24a6 6 0 0 1 12 0a6 6 0 0 1 12 0a6 6 0 0 1 12 0a6 6 0 0 1 12 0" />
        </>
      )
    case 'ferrite':
      return (
        <>
          <path d="M14 24h28M78 24h28" />
          <rect x="42" y="15" width="36" height="18" rx="1.5" />
          <rect x="47" y="20" width="26" height="8" rx="1" className="fill-current opacity-35" stroke="none" />
        </>
      )
    default:
      return (
        <>
          <path d="M14 24h30M76 24h30" />
          <rect x="44" y="12" width="32" height="24" rx="2" />
        </>
      )
  }
}

export function CategoryGlyph({ kind, className }: { kind: GlyphKind; className?: string }) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 120 48"
      className={cn('h-12 w-30', className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <Body kind={kind} />
      <circle cx="10" cy="24" r="3.25" className="fill-current opacity-25" />
      <circle cx="110" cy="24" r="3.25" className="fill-current opacity-25" />
      <circle cx="10" cy="24" r="3.25" />
      <circle cx="110" cy="24" r="3.25" />
    </svg>
  )
}
