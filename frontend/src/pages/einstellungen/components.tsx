/** Bausteine der Einstellungsseite: Karten, Zeilen, Pfade, Standardwert-Hinweise, Leer-/Fehlerzustände. */
import { Check, Copy, FolderOpen, Hammer, RotateCcw } from 'lucide-react'
import type { ReactNode } from 'react'
import { useUi } from '@/app/stores'
import { Button, Card, CardHeader, EmptyState, IconButton, PathText, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { revealPath } from '@/lib/native'
import { useCopyText } from './hooks'

// --------------------------------------------------------------------------- Karten

export interface SettingsCardProps {
  id?: string
  icon: ReactNode
  title: ReactNode
  description?: ReactNode
  /** Status/Aktionen rechts im Kopf */
  aside?: ReactNode
  /** KI-Karte: Funkenlinie oben, Icon im Funken-Ton */
  spark?: boolean
  children?: ReactNode
  /** Inhalt ohne Zeilen-Polsterung (z. B. Listen, die bis an den Rand gehen) */
  flush?: boolean
  footer?: ReactNode
  className?: string
}

export function SettingsCard({ id, icon, title, description, aside, spark, children, flush, footer, className }: SettingsCardProps) {
  return (
    <Card
      id={id}
      className={cn(
        'scroll-mt-20 overflow-hidden',
        // Sprungziel: Fokus landet auf der Überschrift (siehe anchors.ts) – mit Tastatur sichtbar
        '[&_h2]:rounded-sm [&_h2]:outline-none [&_h2:focus-visible]:outline-2 [&_h2:focus-visible]:outline-offset-4 [&_h2:focus-visible]:outline-accent',
        className,
      )}
    >
      {spark && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,var(--pf-spark-a),var(--pf-spark-b),transparent)]"
        />
      )}
      <CardHeader
        icon={icon}
        title={title}
        description={description}
        actions={aside}
        className={cn('border-b border-line px-5 pb-4 pt-5', spark && '[&>span:first-child]:text-spark-text')}
      />
      {children !== undefined && (flush ? children : <div className="flex flex-col divide-y divide-line px-5">{children}</div>)}
      {footer && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line bg-surface-2/40 px-5 py-3">{footer}</div>
      )}
    </Card>
  )
}

/** Einstellungszeile ohne Field (z. B. Schalter mit eigener Beschriftung) */
export function Row({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('py-4', className)}>{children}</div>
}

// --------------------------------------------------------------------------- Standardwert

/** „Standard: 0,20 mm“ + Zurücksetzen, sobald der Wert abweicht */
export function DefaultHint({
  isDefault,
  defaultText,
  onReset,
  label,
}: {
  isDefault: boolean
  defaultText: string
  onReset: () => void
  /** Name der Einstellung (für die Beschriftung des Knopfs) */
  label: string
}) {
  if (isDefault) return null
  return (
    <span className="inline-flex items-center gap-1 text-2xs text-fg-subtle">
      <span>Standard: {defaultText}</span>
      <Tooltip content={`${label} auf ${defaultText} zurücksetzen`}>
        <button
          type="button"
          onClick={onReset}
          aria-label={`${label} auf Standard (${defaultText}) zurücksetzen`}
          className="flex size-5 items-center justify-center rounded-md text-fg-subtle outline-none transition-colors hover:bg-surface-3 hover:text-fg focus-ring"
        >
          <RotateCcw aria-hidden className="size-3" />
        </button>
      </Tooltip>
    </span>
  )
}

// --------------------------------------------------------------------------- Pfade

/**
 * Pfad mit „Im Explorer zeigen“ (Datei markiert bzw. Ordner geöffnet – außerhalb des Desktop-Programms kopiert
 * `revealPath` den Pfad) und „Kopieren“. `revealTarget` = stattdessen zu zeigender Pfad; `reveal={false}` für Angaben,
 * die keine Dateien sind (Server-Adresse).
 */
export function PathActions({
  path,
  revealTarget,
  reveal = true,
  what = 'Pfad',
}: {
  path: string
  revealTarget?: string
  reveal?: boolean
  what?: string
}) {
  const { copied, copy } = useCopyText()
  return (
    <div className="flex shrink-0 items-center">
      {reveal && (
        <IconButton size="sm" label="Im Explorer zeigen" icon={<FolderOpen />} onClick={() => void revealPath(revealTarget ?? path, { what })} />
      )}
      <IconButton
        size="sm"
        label={copied === path ? 'Kopiert' : `${what} kopieren`}
        icon={copied === path ? <Check className="text-success-text" /> : <Copy />}
        onClick={() => void copy(path, what)}
      />
    </div>
  )
}

// --------------------------------------------------------------------------- Zustände

/** Bereich braucht eine geöffnete Bibliothek */
export function NoWorkspace({ what }: { what: string }) {
  const setLibraryDialog = useUi((s) => s.setLibraryDialog)
  return (
    <Card>
      <EmptyState
        illustration="no-library"
        size="lg"
        titleAs="h2"
        title="Keine Bibliothek geöffnet"
        description={`${what} gehören zu einer Bibliothek. Öffnen Sie eine Bibliothek oder legen Sie eine neue an.`}
        actions={
          <>
            <Button variant="secondary" onClick={() => setLibraryDialog('open')}>
              Bibliothek öffnen …
            </Button>
            <Button variant="secondary" onClick={() => setLibraryDialog('create')}>
              Neue Bibliothek anlegen …
            </Button>
          </>
        }
      />
    </Card>
  )
}

/** Hinweis für Funktionen, deren Backend gerade gebaut wird (404/501) */
export function PendingFeature({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start gap-2.5 rounded-control border border-dashed border-line-strong px-3 py-2.5 text-xs text-fg-muted', className)}>
      <Hammer aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
      <span>
        <span className="font-medium text-fg">Funktion wird gerade eingebaut.</span> {children}
      </span>
    </div>
  )
}

/** Pfad-Zeile (Symbol, Beschriftung, Pfad, Aktionen) für Übersichten */
export function PathLine({
  icon,
  label,
  path,
  hint,
  revealTarget,
  reveal,
  what,
  className,
}: {
  icon: ReactNode
  label: string
  path: string
  hint?: ReactNode
  /** Im Explorer stattdessen zeigen (z. B. ein Ordner) */
  revealTarget?: string
  /** `false` = keine Datei (z. B. Server-Adresse): nur kopieren */
  reveal?: boolean
  /** Was der Pfad ist – für die Meldungen („Datenbankdatei“) */
  what?: string
  className?: string
}) {
  return (
    <div className={cn('flex min-w-0 items-center gap-3 py-2.5', className)}>
      <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-control bg-surface-2 text-fg-muted [&_svg]:size-3.5">
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-ui font-medium text-fg">{label}</span>
          {hint && <span className="text-2xs text-fg-subtle">{hint}</span>}
        </div>
        <PathText path={path} className="mono block text-xs text-fg-muted" />
      </div>
      <PathActions path={path} revealTarget={revealTarget} reveal={reveal} what={what} />
    </div>
  )
}
