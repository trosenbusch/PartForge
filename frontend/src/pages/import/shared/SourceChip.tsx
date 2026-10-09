import { FileText } from 'lucide-react'
import { Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { pagesText } from '../lib/format'
import { useReviewUi } from '../store'

export interface SourceChipProps {
  pages: readonly (number | null | undefined)[]
  /** Was dort steht (Tooltip und Kopf der großen Seitenansicht), z. B. „Pintabelle“ */
  what?: string
  className?: string
  /** Teil einer Tabellenzeile mit einem einzigen Tab-Stopp (nur mit den Pfeiltasten erreichbar) */
  navItem?: boolean
}

/**
 * Fundstelle im Datenblatt („S. 2“): Klick öffnet die Seite groß zum Prüfen (die PDF-Spalte springt mit),
 * Überfahren hebt die Miniatur hervor.
 */
export function SourceChip({ pages, what, className, navItem }: SourceChipProps) {
  const list = [...new Set(pages.filter((p): p is number => typeof p === 'number' && p > 0))].sort((a, b) => a - b)
  const openOverlay = useReviewUi((s) => s.openOverlay)
  const hover = useReviewUi((s) => s.setHoverPage)
  if (!list.length) return null
  const label = `S. ${pagesText(list)}`
  const tip = `${what ? `${what} – ` : ''}Seite ${pagesText(list)} groß anzeigen`
  return (
    <Tooltip content={tip}>
      <button
        type="button"
        aria-haspopup="dialog"
        tabIndex={navItem ? -1 : undefined}
        data-nav-item={navItem ? '' : undefined}
        onClick={() => {
          hover(null)
          openOverlay(list[0], what)
        }}
        onMouseEnter={() => hover(list[0])}
        onMouseLeave={() => hover(null)}
        onFocus={() => hover(list[0])}
        onBlur={() => hover(null)}
        className={cn(
          'inline-flex h-5 shrink-0 items-center gap-1 rounded-md border border-line px-1.5 text-2xs font-medium tabular-nums text-fg-muted',
          'outline-none transition-colors hover:border-spark-b/40 hover:bg-[color-mix(in_oklab,var(--pf-spark-b)_10%,transparent)] hover:text-spark-text focus-ring',
          className,
        )}
      >
        <FileText aria-hidden className="size-3" />
        {label}
        {/* Name = sichtbares „S. 2“ plus Zweck (kein abweichendes aria-label) */}
        <span className="sr-only"> – {tip}</span>
      </button>
    </Tooltip>
  )
}
