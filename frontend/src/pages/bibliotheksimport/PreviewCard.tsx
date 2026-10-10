/**
 * Vorschau eines Bauteils der Quelle (vor dem Import): SVG aus `GET /api/library-import/preview` als Bild – gelesen
 * über den Bibliotheks-Writer, deshalb mit Platzhalter, bis es da ist. Symbole im Theme der App bzw. in der
 * Altium-Ansicht (geteilte Vorliebe der Vorschau), Footprints auf der dunklen Leiterplatte.
 *
 * `variant="pane"`: Spalte rechts im Dateibaum (breite Fenster), `card`: eigene Karte unter den Optionen.
 */
import { Eye, ImageOff, Square } from 'lucide-react'
import { useState } from 'react'
import { libImportApi, STATE_LABELS, type PreviewTheme } from '@/api/libimport'
import { useTheme } from '@/app/theme'
import { usePreviewPrefs } from '@/components/preview/previewPrefs'
import { Card, CardHeader, Skeleton, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { plural } from '@/lib/format'
import type { PreviewTarget } from './FileTree'
import { KIND_TEXT } from './model'
import { RelPath, StateBadge } from './ui'

export interface PreviewCardProps {
  scanId: string
  target: PreviewTarget | null
  /** gewählt (Klick, Tastatur) statt nur überfahren */
  pinned: boolean
  variant?: 'card' | 'pane'
}

export function PreviewCard({ scanId, target, pinned, variant = 'card' }: PreviewCardProps) {
  const { resolvedTheme } = useTheme()
  const altium = usePreviewPrefs((s) => s.altium)
  const setPrefs = usePreviewPrefs((s) => s.set)
  const board = target?.file.kind === 'pcblib'
  const theme: PreviewTheme = board ? 'dark' : altium ? 'altium' : resolvedTheme
  const url = target ? libImportApi.previewUrl(scanId, target.file.rel, target.component.name, theme) : null
  const c = target?.component
  const text = target ? KIND_TEXT[target.file.kind] : null

  const toggle =
    target && !board ? (
      <Tooltip content={altium ? 'PartForge-Darstellung' : 'Wie in Altium Designer (weißes Blatt)'}>
        <button
          type="button"
          aria-pressed={altium}
          onClick={() => setPrefs({ altium: !altium })}
          className={cn(
            'flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium text-fg-muted outline-none transition-colors focus-ring hover:bg-surface-2 hover:text-fg',
            altium && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text',
          )}
        >
          <Square aria-hidden className={cn('size-3.5', altium && 'fill-altium-body text-altium-line')} />
          Altium
        </button>
      </Tooltip>
    ) : null

  const image = (
    <div
      className={cn(
        'relative h-44 overflow-hidden rounded-control border',
        !target ? 'dot-grid border-line bg-bg' : board ? 'border-white/5 bg-canvas' : altium ? 'border-line bg-altium-sheet' : 'dot-grid border-line bg-bg',
      )}
    >
      {url && c ? (
        <PreviewImage key={url} src={url} alt={`Vorschau ${c.name}`} />
      ) : (
        <p className="flex size-full items-center justify-center px-6 text-center text-xs leading-relaxed text-fg-subtle">
          Über ein Bauteil fahren oder es in der Liste wählen – hier erscheint seine Vorschau.
        </p>
      )}
    </div>
  )

  const details =
    c && target && text ? (
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="mono min-w-0 text-ui font-semibold text-fg [overflow-wrap:anywhere]">{c.name}</span>
          <StateBadge state={c.state} />
        </div>
        {c.description && <p className="text-xs leading-snug text-fg-muted">{c.description}</p>}
        <p className="text-2xs text-fg-subtle">
          {[
            c.count != null ? plural(c.count, text.countOne, text.countMany) : null,
            c.has_3d === true ? 'mit 3D‑Modell' : c.has_3d === false && board ? 'ohne 3D‑Modell' : null,
          ]
            .filter(Boolean)
            .join(' · ') || text.one}
        </p>
        <p className="text-2xs text-fg-subtle">
          aus <RelPath rel={target.file.rel} className="text-2xs" />
        </p>
        {c.state !== 'new' && c.registered_library && (
          <p className={cn('text-2xs', c.state === 'taken' ? 'text-warning-text' : 'text-fg-subtle')}>
            {c.state === 'taken' ? 'Name schon registriert in ' : c.state === 'duplicate' ? 'zuerst in ' : 'importiert nach '}
            <RelPath rel={c.registered_library} className="text-2xs" />
            {c.state === 'taken' && ' – wird nicht übernommen.'}
          </p>
        )}
        <span className="sr-only" aria-live="polite">
          {`${c.name}, ${STATE_LABELS[c.state]}`}
        </span>
      </div>
    ) : (
      <p className="text-xs leading-relaxed text-fg-muted">
        Symbole und Footprints lassen sich vor dem Import ansehen – PartForge liest sie über den Bibliotheks-Writer aus der Quelle.
      </p>
    )

  if (variant === 'pane') {
    return (
      <section aria-label="Vorschau" className="flex h-full min-h-0 flex-col overflow-y-auto">
        <div className="flex h-11 shrink-0 items-center justify-between gap-2 pl-3 pr-2">
          <h3 className="micro-label flex items-center gap-1.5">
            <Eye aria-hidden className="size-3.5" />
            Vorschau
          </h3>
          {toggle}
        </div>
        <div className="px-3">{image}</div>
        <div className="px-3 pb-3 pt-3">{details}</div>
      </section>
    )
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader
        icon={<Eye />}
        title="Vorschau"
        titleAs="h2"
        description={target ? (pinned ? `${text?.one} der Quelle` : `${text?.one} unter dem Mauszeiger`) : 'Vor dem Import, direkt aus der Quelle'}
        actions={toggle ?? undefined}
      />
      <div className="mx-4">{image}</div>
      <div className="min-h-24 px-4 pb-4 pt-3">{details}</div>
    </Card>
  )
}

/** SVG als Bild – Platzhalter bis geladen, ruhiger Hinweis, wenn es nicht geht */
function PreviewImage({ src, alt }: { src: string; alt: string }) {
  const [state, setState] = useState<'loading' | 'done' | 'error'>('loading')
  return (
    <>
      {state === 'loading' && <Skeleton className="absolute inset-3 rounded-control opacity-60" />}
      {state === 'error' ? (
        <div className="flex size-full flex-col items-center justify-center gap-1.5 px-6 text-center text-2xs text-fg-subtle">
          <ImageOff aria-hidden className="size-5" />
          Vorschau nicht verfügbar – die Datei ist nicht lesbar oder der Bibliotheks-Writer fehlt.
        </div>
      ) : (
        <img
          src={src}
          alt={alt}
          draggable={false}
          onLoad={() => setState('done')}
          onError={() => setState('error')}
          className={cn('absolute inset-0 size-full object-contain p-4 transition-opacity duration-300', state === 'done' ? 'opacity-100' : 'opacity-0')}
        />
      )}
    </>
  )
}
