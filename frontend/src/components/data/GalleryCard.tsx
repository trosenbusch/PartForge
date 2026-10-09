/**
 * Karte für die <VirtualGallery>: Vorschaufläche oben, Name (Monospace, höchstens zwei Zeilen) und Zusatzzeile unten.
 * `board` = dunkle Leiterplatten-Fläche (Footprints), sonst App-Hintergrund (Symbole).
 * Lange Namen (IPC-Footprints wie `SOIC127P600X175-8N_6E43`) brechen an beliebiger Stelle um und werden nach
 * zwei Zeilen gekürzt – der volle Name steht im `title`-Attribut (Hover).
 */
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export interface GalleryCardProps {
  title: ReactNode
  /** Klartext des Titels für den Hover-Tooltip (`title`-Attribut), wenn `title` kein String ist */
  titleText?: string
  /** Titel in Monospace (Standard: ja – Symbol- und Footprintnamen) */
  mono?: boolean
  /** Zusatzzeile (Gruppe, Pinzahl, Maße) */
  meta?: ReactNode
  /** Vorschau (z. B. <LazyThumbnail>) */
  thumbnail?: ReactNode
  /** Badge rechts oben auf der Vorschau */
  badge?: ReactNode
  selected?: boolean
  /** Tastatur-Cursor (wird von der Galerie gesetzt) */
  active?: boolean
  board?: boolean
  className?: string
}

const plain = (node: ReactNode): string | undefined =>
  typeof node === 'string' ? node : typeof node === 'number' ? String(node) : undefined

export function GalleryCard({ title, titleText, mono = true, meta, thumbnail, badge, selected, board, className }: GalleryCardProps) {
  const fullTitle = titleText ?? plain(title)
  const fullMeta = plain(meta)
  return (
    <div
      className={cn(
        'group/card relative flex size-full cursor-pointer flex-col overflow-hidden rounded-card border bg-surface shadow-card transition-[transform,border-color,box-shadow] duration-200 ease-out',
        'hover:-translate-y-px hover:border-line-strong hover:shadow-raised',
        selected ? 'border-accent/60 shadow-glow' : 'border-line',
        className,
      )}
    >
      <div
        className={cn(
          'relative min-h-0 flex-1 overflow-hidden border-b',
          board ? 'border-white/5 bg-canvas' : 'dot-grid border-line bg-bg',
        )}
      >
        {thumbnail}
        {badge && <div className="absolute right-2 top-2">{badge}</div>}
        {selected && (
          <span
            aria-hidden
            className="absolute left-2 top-2 flex size-5 items-center justify-center rounded-full bg-gradient-forge text-on-accent shadow-glow [&_svg]:size-3"
          >
            <Check strokeWidth={3} />
          </span>
        )}
      </div>
      <div className="flex shrink-0 flex-col gap-0.5 px-3 py-2">
        <div
          className={cn('line-clamp-2 text-xs font-semibold leading-4 text-fg [overflow-wrap:anywhere]', mono && 'mono')}
          title={fullTitle}
        >
          {title}
        </div>
        {meta && (
          <div className="truncate text-2xs text-fg-subtle" title={fullMeta}>
            {meta}
          </div>
        )}
      </div>
    </div>
  )
}
