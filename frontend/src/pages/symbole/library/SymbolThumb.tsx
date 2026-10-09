/**
 * Vorschaubild eines registrierten Symbols aus `GET /api/libraries/symbols/{name}/thumbnail.svg?v=<content_hash>` –
 * lädt erst im Sichtbereich, im Theme der App. `content_hash` (aus Liste, Detail und Speichern) ändert sich mit
 * Geometrie, Symbol-Hausstil und Darstellung: Der Browser speichert das Bild unter dieser Adresse dauerhaft
 * (`immutable`) und lädt nach jeder Änderung – auch zwei Speicherungen in derselben Sekunde – das neue Bild. Das Token
 * geht als Kopfzeile mit, die Adresse bleibt über Neustarts gleich (Browser-Cache bleibt gültig).
 *
 * Ohne `content_hash` hat der Eintrag keine Geometrie (z. B. ein nur namentlich bekanntes Symbol einer externen
 * Bibliothek) – dann zeigt die Karte einen ruhigen Platzhalter, ohne eine Anfrage, die 404 ergäbe.
 */
import { Component as SymbolIcon } from 'lucide-react'
import { symbolKeys, symbolsApi, type SymbolEntry } from '@/api/symbols'
import { useTheme } from '@/app/theme'
import { LazyThumbnail } from '@/components/data'

type ThumbEntry = Pick<SymbolEntry, 'name' | 'content_hash'>

function Placeholder({ small }: { small?: boolean }) {
  return (
    <span className="flex size-full items-center justify-center text-fg-subtle">
      <SymbolIcon aria-hidden className={small ? 'size-3.5' : 'size-6'} />
      <span className="sr-only">Keine Vorschau</span>
    </span>
  )
}

export interface SymbolThumbProps {
  entry: ThumbEntry
  /** Innenabstand des Bildes */
  inset?: string
  /** Kleine Kachel (Auswahllisten): kleineres Platzhalter-Symbol */
  compact?: boolean
  className?: string
}

export function SymbolThumb({ entry, inset = 'p-5', compact = false, className }: SymbolThumbProps) {
  const { resolvedTheme } = useTheme()
  const hash = entry.content_hash
  if (!hash) {
    return compact ? <Placeholder small /> : <LazyThumbnail render={() => <Placeholder />} inset={inset} className={className} />
  }
  return (
    <LazyThumbnail
      queryKey={symbolKeys.thumbnail(entry.name, resolvedTheme, hash)}
      loadSvg={(signal) => symbolsApi.thumbnail(entry.name, resolvedTheme, hash, signal)}
      alt=""
      inset={inset}
      className={className}
    />
  )
}
