import { useState } from 'react'
import { datasheetPageUrl } from '@/api/datasheets'
import { cn } from '@/lib/cn'

/** Standard-Seitenverhältnis (US Letter), solange die echten Seitenmaße noch nicht bekannt sind */
export const DEFAULT_PAGE_ASPECT = 612 / 792

export interface PageImageProps {
  datasheetId: string
  page: number
  /** 36…300 dpi (Miniaturen 36–48, Ansicht 110, Details 200) */
  dpi?: number
  /** Breite / Höhe der Seite */
  aspect?: number
  alt?: string
  loading?: 'lazy' | 'eager'
  className?: string
  imgClassName?: string
  /** Leinwand statt Papierweiß während des Ladens */
  dark?: boolean
  /** Schimmer-Platzhalter während des Ladens (aus, wenn darunter schon eine Vorschau liegt) */
  placeholder?: boolean
}

/** Gerendertes PDF-Blatt (PNG vom Backend) mit Platzhalter in Seitengröße – kein Layout-Springen. */
export function PageImage({
  datasheetId,
  page,
  dpi = 40,
  aspect = DEFAULT_PAGE_ASPECT,
  alt,
  loading = 'lazy',
  className,
  imgClassName,
  dark,
  placeholder = true,
}: PageImageProps) {
  const src = datasheetPageUrl(datasheetId, page, dpi)
  const [loaded, setLoaded] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const ready = loaded === src
  return (
    <div className={cn('relative overflow-hidden', placeholder && 'bg-white', className)} style={{ aspectRatio: String(aspect) }}>
      {placeholder && !ready && failed !== src && <div aria-hidden className={cn('shimmer absolute inset-0', dark && 'opacity-60')} />}
      {failed === src ? (
        <div className="absolute inset-0 flex items-center justify-center bg-surface-2 text-2xs text-fg-subtle">
          Seite {page} nicht verfügbar
        </div>
      ) : (
        <img
          src={src}
          alt={alt ?? `Seite ${page}`}
          loading={loading}
          decoding="async"
          draggable={false}
          onLoad={() => setLoaded(src)}
          onError={() => setFailed(src)}
          className={cn(
            'absolute inset-0 size-full select-none object-contain transition-opacity duration-300',
            ready ? 'opacity-100' : 'opacity-0',
            imgClassName,
          )}
        />
      )}
    </div>
  )
}
