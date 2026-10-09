import { cn } from '@/lib/cn'
import { overbarSegments, spokenPinName } from '@/lib/geometry'

/** Pinname in Altium-Überstrich-Syntax (`R\E\S\E\T\`) mit echtem Überstrich; Screenreader hören „(invertiert)“. */
export function OverbarName({ name, className }: { name: string; className?: string }) {
  const segments = overbarSegments(name)
  if (!segments.length) return <span className={cn('text-fg-subtle', className)}>–</span>
  return (
    <span className={cn('inline-flex min-w-0 items-baseline whitespace-pre', className)}>
      <span aria-hidden className="inline-flex min-w-0 items-baseline overflow-hidden pt-0.5">
        {segments.map((s, i) =>
          s.barred ? (
            // Überstrich als Rahmen oben am Block – liegt dicht über den Großbuchstaben wie im Schaltplan
            <span key={i} className="inline-block border-t border-current pt-px leading-[1.1]">
              {s.text}
            </span>
          ) : (
            <span key={i} className="leading-[1.1]">
              {s.text}
            </span>
          ),
        )}
      </span>
      <span className="sr-only">{spokenPinName(name)}</span>
    </span>
  )
}
