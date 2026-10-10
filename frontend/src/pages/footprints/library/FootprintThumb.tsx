import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Vorschaubild eines registrierten Footprints aus `GET /api/libraries/footprints/{name}/thumbnail.svg?v=<content_hash>`
 * (Leiterplatte, immer dunkel) – lädt erst im Sichtbereich. `content_hash` (aus Liste, Detail und Speichern) ändert sich
 * mit der Geometrie und der Darstellung: Der Browser speichert das Bild unter dieser Adresse dauerhaft (`immutable`)
 * und lädt nach jeder Änderung – auch zwei Speicherungen in derselben Sekunde – das neue Bild (Token als Kopfzeile, die
 * Adresse bleibt über Neustarts gleich).
 *
 * Ohne `content_hash` hat der Eintrag keine Geometrie (z. B. ein nur namentlich bekannter Footprint einer externen
 * Bibliothek) – dann zeigt die Karte die Glyphe der Familie, ohne eine Anfrage, die 404 ergäbe.
 */
import { footprintKeys, footprintsApi, type LibraryFootprint } from '@/api/footprints'
import { LazyThumbnail } from '@/components/data'
import { CHROME_MUTED } from '@/components/preview'
import { cn } from '@/lib/cn'
import { PackageGlyph } from '../PackageGlyph'

type ThumbEntry = Pick<LibraryFootprint, 'name' | 'content_hash' | 'family'>

function Glyph({ family, small }: { family: string | null; small?: boolean }) {
  useI18n()
  return (
    <span className={cn('flex size-full items-center justify-center', CHROME_MUTED.board)}>
      <PackageGlyph family={family} className={small ? 'size-4' : 'size-9'} />
      <span className="sr-only">{tr("Keine Vorschau")}</span>
    </span>
  )
}

export interface FootprintThumbProps {
  entry: ThumbEntry
  inset?: string
  /** Kleine Kachel (Auswahllisten): kleine Glyphe */
  compact?: boolean
  className?: string
}

export function FootprintThumb({ entry, inset = 'p-3', compact = false, className }: FootprintThumbProps) {
  const hash = entry.content_hash
  if (!hash) {
    if (compact) return <Glyph family={entry.family} small />
    return <LazyThumbnail render={() => <Glyph family={entry.family} />} inset={inset} className={className} />
  }
  return (
    <LazyThumbnail
      queryKey={footprintKeys.libraryThumb(entry.name, hash)}
      loadSvg={(signal) => footprintsApi.thumbnail(entry.name, hash, signal)}
      alt=""
      inset={inset}
      className={className}
    />
  )
}
