import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Miniatur einer Generator-Vorlage im Katalog: Vorschau ohne 3D und SVG (lange gecacht, je Hausstil), gezeichnet mit
 * `StaticFootprint`. Jede Karte lädt erst, wenn sie sichtbar wird (`LazyThumbnail`). Gespeicherte Footprints zeigen
 * das Vorschaubild des Backends (`FootprintThumb`).
 */
import { useQuery } from '@tanstack/react-query'
import { ImageOff } from 'lucide-react'
import { catalogThumbOptions, type FootprintFamily, type FootprintPreset } from '@/api/footprints'
import { useWorkspace } from '@/api/system'
import { CHROME_MUTED } from '@/components/preview'
import { Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { FootprintSpec } from '@/lib/geometry'
import { PackageGlyph } from '../PackageGlyph'
import { StaticFootprint } from './StaticFootprint'

function ThumbState({ spec, isError, isPending, family }: { spec: FootprintSpec | null | undefined; isError: boolean; isPending: boolean; family?: string | null }) {
  useI18n()
  if (spec) return <StaticFootprint spec={spec} className="size-full" />
  if (isPending) return <Skeleton className="absolute inset-3 rounded-control opacity-[0.12]" />
  return (
    <div className={cn('flex size-full items-center justify-center', CHROME_MUTED.board)}>
      {isError || !family ? <ImageOff aria-hidden className="size-5" /> : <PackageGlyph family={family} className="size-9" />}
      <span className="sr-only">{tr("Keine Vorschau")}</span>
    </div>
  )
}

/** Miniatur einer Generator-Vorlage (Katalog) */
export function PresetThumb({ family, preset }: { family: FootprintFamily; preset: FootprintPreset }) {
  const style = useWorkspace().data?.settings.footprint
  const q = useQuery(catalogThumbOptions(family.key, preset.key, style ? JSON.stringify(style) : 'standard'))
  return <ThumbState spec={q.data} isError={q.isError} isPending={q.isPending} family={family.key} />
}
