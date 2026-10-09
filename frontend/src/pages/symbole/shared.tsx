/** Kleine Bausteine des Symbole-Moduls: SVG als Bild, Überstrich-Text, Typ-Punkt, Überstrich-Icon. */
import { useMemo, useState, type ReactNode } from 'react'
import type { ElectricalType } from '@/api/symbols'
import { cn } from '@/lib/cn'
import { overbarSegments } from '@/lib/geometry'
import { ELECTRICAL_COLOR } from './ic/pins'

/**
 * SVG-Markup des Backends als Bild – nie direkt ins DOM. Data-URL statt Blob-URL: virtualisierte Karten werden beim
 * Scrollen neu eingehängt, eine bereits freigegebene Blob-URL würde dann als Ladefehler in der Konsole landen.
 * Strichstärken und Schrift der Vorschaubilder vereinheitlicht das Backend (`render_thumbnail`).
 */
export function SvgImage({ svg, alt = '', className }: { svg: string | null | undefined; alt?: string; className?: string }) {
  const url = useMemo(
    () => (svg ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}` : null),
    [svg],
  )
  const [loaded, setLoaded] = useState<string | null>(null)
  if (!url) return null
  return (
    <img
      src={url}
      alt={alt}
      draggable={false}
      onLoad={() => setLoaded(url)}
      className={cn(
        'size-full object-contain transition-opacity duration-300 motion-reduce:transition-none',
        loaded === url ? 'opacity-100' : 'opacity-0',
        className,
      )}
    />
  )
}

/** Pinname mit Altium-Überstrich (`R\E\S\E\T\`) als HTML */
export function OverbarName({ value, className, placeholder }: { value: string; className?: string; placeholder?: string }) {
  const segments = overbarSegments(value)
  if (!segments.length) return placeholder ? <span className={cn('text-fg-subtle', className)}>{placeholder}</span> : null
  return (
    <span className={className}>
      {segments.map((s, i) =>
        s.barred ? (
          <span key={i} className="[text-decoration-line:overline] [text-decoration-thickness:1px]">
            {s.text}
          </span>
        ) : (
          <span key={i}>{s.text}</span>
        ),
      )}
    </span>
  )
}

/** Farbpunkt des elektrischen Typs (kategorial; hohl = Open-Collector/-Emitter, Tri-State) */
export function ElectricalDot({ type, className }: { type: ElectricalType; className?: string }) {
  const c = ELECTRICAL_COLOR[type] ?? ELECTRICAL_COLOR.passive
  return (
    <span
      aria-hidden
      className={cn('inline-block size-2 shrink-0 rounded-full', className)}
      style={c.hollow ? { boxShadow: `inset 0 0 0 1.5px ${c.color}` } : { background: c.color }}
    />
  )
}

/**
 * Beschriftete Gruppe für Controls ohne eigenes Formularfeld (SegmentedControl, Schalterreihen): sichtbares Label
 * wie bei <Field>, die Controls tragen ihren zugänglichen Namen selbst (aria-label).
 */
export function LabeledGroup({ label, help, children, className }: { label: ReactNode; help?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <div aria-hidden className="flex min-h-5 items-baseline text-ui font-medium text-fg">
        {label}
      </div>
      {children}
      {help && <p className="text-xs leading-snug text-fg-muted">{help}</p>}
    </div>
  )
}

/** Icon „Überstrich“ (Lucide hat keins): Buchstabe mit Linie darüber */
export function OverlineIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round" aria-hidden className={className}>
      <path d="M6 4h12" />
      <path d="M7 20l5-12 5 12" />
      <path d="M9 15h6" />
    </svg>
  )
}
