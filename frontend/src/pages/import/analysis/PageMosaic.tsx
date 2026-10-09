import { motion, useReducedMotion } from 'motion/react'
import { Check, Globe } from 'lucide-react'
import { useMemo } from 'react'
import { useElementSize } from '@/components/preview'
import { Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { AnalysisProgress } from '../lib/analysis'
import { DEFAULT_PAGE_ASPECT, PageImage } from '../shared/PageImage'
import { useScrollTabStop } from '../shared/useScrollTabStop'

const GAP = 10
const LABEL_H = 20
const MAX_TILE = 156
const MIN_TILE = 40

/** Spaltenzahl, bei der alle Seiten in die Fläche passen und die Miniaturen möglichst groß sind. */
function fitGrid(n: number, width: number, height: number, aspect: number): { cols: number; tile: number; scroll: boolean } {
  if (n <= 0 || width <= 0) return { cols: 1, tile: 0, scroll: false }
  let best = { cols: 1, tile: 0 }
  for (let cols = 1; cols <= n; cols++) {
    const tile = Math.min(MAX_TILE, (width - GAP * (cols - 1)) / cols)
    const rows = Math.ceil(n / cols)
    const total = rows * (tile / aspect + LABEL_H) + GAP * (rows - 1)
    if (total <= height && tile > best.tile) best = { cols, tile }
  }
  if (best.tile >= MIN_TILE) return { ...best, scroll: false }
  const cols = Math.max(1, Math.floor((width + GAP) / (MIN_TILE + GAP)))
  return { cols, tile: (width - GAP * (cols - 1)) / cols, scroll: true }
}

export interface PageMosaicProps {
  datasheetId: string | null
  pageCount: number
  /** Seite → Breite/Höhe (aus der Textebenen-Analyse) */
  aspects: Map<number, number>
  progress: AnalysisProgress
  live: boolean
}

/**
 * Alle Seiten des Datenblatts: Die von Claude gewählten leuchten auf, die gerade gelesenen tragen den rotierenden
 * Funkenrahmen und einen Scan-Strahl, nicht gewählte treten zurück.
 */
export function PageMosaic({ datasheetId, pageCount, aspects, progress, live }: PageMosaicProps) {
  const [ref, size, el] = useElementSize<HTMLDivElement>()
  // scrollt das Raster (sehr viele Seiten, kleines Fenster), ist es per Tastatur erreichbar
  const tabStop = useScrollTabStop(el)
  const reduce = useReducedMotion()
  // Rasterzeilen sind so hoch wie ihre höchste Miniatur → mit dem schmalsten Seitenformat rechnen (Hochformat)
  const aspect = useMemo(() => {
    const values = [...aspects.values()]
    return values.length ? Math.min(...values) : DEFAULT_PAGE_ASPECT
  }, [aspects])
  const grid = fitGrid(pageCount, size.width, size.height, aspect)
  const selected = new Set(progress.selectedPages)
  const identity = new Set(progress.identityPages)
  const geometry = new Set(progress.geometryPages)
  const vision = new Set(progress.visionPages)
  const active = new Set(progress.activePages)
  const done = new Set(progress.donePages)
  const image = new Set(progress.imagePages)
  const chosen = selected.size > 0

  if (!datasheetId || pageCount <= 0) {
    return (
      <div className="flex h-full min-h-56 flex-col items-center justify-center gap-3 text-center">
        <span className="relative flex size-16 items-center justify-center rounded-card border border-line-strong bg-surface-2">
          <Globe aria-hidden className="size-6 text-fg-subtle" />
          <span className="absolute -bottom-1.5 -right-1.5 flex size-6 items-center justify-center rounded-full border border-line bg-surface">
            <Spinner size={14} tone="spark" />
          </span>
        </span>
        <p className="max-w-64 text-xs leading-relaxed text-fg-muted">
          {progress.download?.name
            ? `„${progress.download.name}“ geladen – die Seiten erscheinen gleich.`
            : 'Das Datenblatt wird geladen. Sobald es da ist, erscheinen hier seine Seiten.'}
        </p>
      </div>
    )
  }

  const pages = Array.from({ length: pageCount }, (_, i) => i + 1)
  return (
    <div
      ref={ref}
      // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Tab-Stopp nur, wenn das Raster scrollt (WCAG 2.1.1)
      tabIndex={tabStop ? 0 : undefined}
      role={tabStop ? 'region' : undefined}
      aria-label={tabStop ? 'Seiten des Datenblatts' : undefined}
      className={cn('relative size-full min-h-0 outline-none focus-ring-inset', grid.scroll ? 'overflow-y-auto pr-1' : 'overflow-hidden')}
    >
      {grid.tile > 0 && (
        <ul
          aria-label="Seiten des Datenblatts"
          className="mx-auto grid content-start"
          style={{
            gridTemplateColumns: `repeat(${grid.cols}, ${grid.tile}px)`,
            gap: GAP,
            width: grid.cols * grid.tile + GAP * (grid.cols - 1),
          }}
        >
          {pages.map((p, i) => {
            const isActive = active.has(p)
            const isSelected = selected.has(p)
            const isDone = done.has(p)
            const dim = chosen && !isSelected
            const roles = [identity.has(p) && 'Pins', geometry.has(p) && 'Maße', vision.has(p) && 'Kontrolle'].filter(Boolean) as string[]
            const state = isActive
              ? 'wird gerade gelesen'
              : isDone
                ? 'gelesen'
                : isSelected
                  ? `ausgewählt (${roles.join(', ')})`
                  : chosen
                    ? 'nicht benötigt'
                    : ''
            return (
              <motion.li
                key={p}
                initial={reduce ? false : { opacity: 0, scale: 0.94 }}
                animate={{ opacity: 1, scale: isActive && !reduce ? 1.04 : 1 }}
                transition={{ duration: 0.35, delay: reduce ? 0 : Math.min(i, 30) * 0.012 }}
                className={cn('relative flex flex-col', isActive && 'z-10')}
              >
                <div
                  className={cn(
                    'relative rounded-md p-[2px] transition-[box-shadow,filter] duration-300',
                    isActive
                      ? cn('spark-border shadow-glow-spark [--spark-fill:var(--pf-surface-2)]', !live && 'animate-none')
                      : isSelected
                        ? 'spark-border-static [--spark-fill:var(--pf-surface-2)]'
                        : 'border border-line bg-surface-2',
                    dim && 'grayscale',
                  )}
                >
                  <PageImage
                    datasheetId={datasheetId}
                    page={p}
                    dpi={grid.tile > 110 ? 48 : 36}
                    aspect={aspects.get(p) ?? aspect}
                    alt=""
                    className="rounded-sm"
                  />
                  {isActive && !reduce && (
                    <div aria-hidden className="pointer-events-none absolute inset-[2px] overflow-hidden rounded-sm">
                      <motion.div
                        className="absolute inset-x-0 top-0 h-1/4 bg-[linear-gradient(180deg,transparent,color-mix(in_oklab,var(--pf-spark-a)_35%,transparent)_45%,color-mix(in_oklab,var(--pf-spark-b)_45%,transparent)_55%,transparent)]"
                        initial={{ y: '-100%' }}
                        animate={{ y: ['-100%', '400%'] }}
                        transition={{ duration: 1.9, repeat: Infinity, ease: 'easeInOut', delay: (i % 4) * 0.25 }}
                      />
                    </div>
                  )}
                  {/* nicht benötigte Seiten: nur das Blatt tritt zurück (Schleier), die Seitenzahl bleibt lesbar */}
                  {dim && (
                    <span
                      aria-hidden
                      className="pointer-events-none absolute inset-[2px] rounded-sm bg-[color-mix(in_oklab,var(--pf-bg)_58%,transparent)] light:bg-[rgba(15,23,42,.2)]"
                    />
                  )}
                  {image.has(p) && (
                    <span className="absolute left-1.5 top-1.5 rounded-sm bg-[rgba(9,11,16,.72)] px-1 text-2xs font-medium leading-4 text-white">
                      Bild
                    </span>
                  )}
                  {isDone && !isActive && (
                    <span
                      aria-hidden
                      className="absolute right-1.5 top-1.5 flex size-4 items-center justify-center rounded-full bg-gradient-spark text-on-spark shadow-card [&_svg]:size-2.5"
                    >
                      <Check />
                    </span>
                  )}
                </div>
                <div className="mt-1 flex h-4 items-center justify-between gap-1 px-0.5 text-2xs leading-4">
                  <span className={cn('tabular-nums', isSelected ? 'font-semibold text-fg' : 'text-fg-subtle')}>{p}</span>
                  {roles.length > 0 && grid.tile >= 72 && (
                    <span className={cn('truncate', isActive ? 'text-spark-text' : 'text-fg-subtle')}>{roles.join(' · ')}</span>
                  )}
                </div>
                {state && <span className="sr-only">Seite {p}: {state}</span>}
              </motion.li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
