import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Ergebnis des Generators: Symbolname (kopierbar) und was „In Bibliothek speichern“ damit tut – aus dem Probelauf des
 * Backends: neu (Ziel-SchLib), bereits aktuell, aktualisiert ein gespeichertes Symbol (Verwendung) oder ändert seine
 * Pinbelegung (Änderungen), bzw. warum es nicht gespeichert werden kann.
 */
import { ArrowRight, Copy, TriangleAlert } from 'lucide-react'
import type { SymbolEntry } from '@/api/symbols'
import { Badge, Button, IconButton, Skeleton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, plural } from '@/lib/format'
import { copyText, STATUS_LABEL } from '../util'
import type { SymbolSavePlan } from './GeneratorView'

export interface LibraryInfo {
  available: boolean
  entry: SymbolEntry | null
  loading: boolean
  /** Probelauf des Speicherns (null = kein gültiges Symbol) */
  plan?: SymbolSavePlan | null
}

export interface NameResultProps {
  name: string | null
  /** Vorschau läuft noch (Name unbekannt) */
  pending?: boolean
  library: LibraryInfo
  /** Symbol in der Bibliotheksansicht öffnen */
  onShowInLibrary?: (name: string) => void
  className?: string
}

function PlanBadge({ entry, plan }: { entry: SymbolEntry | null; plan: SymbolSavePlan | null | undefined }) {
  useI18n()
  if (plan?.error) {
    return (
      <Badge variant="danger" dot>
        {tr("Nicht speicherbar")}
      </Badge>
    )
  }
  if (plan?.unchanged) {
    return (
      <Badge variant="success" dot>
        {tr("In der Bibliothek · aktuell")}
      </Badge>
    )
  }
  if (entry && plan?.changes.length) {
    return (
      <Badge variant="warning" dot>
        {tr("Pinbelegung ändert sich")}
      </Badge>
    )
  }
  if (entry) {
    const status = STATUS_LABEL[entry.status] ?? { label: entry.status, tone: 'neutral' as const }
    return (
      <Badge variant={status.tone === 'success' ? 'success' : status.tone === 'danger' ? 'danger' : 'warning'} dot>
        {status.tone === 'success' ? tr('In der Bibliothek') : tr(status.label)}
      </Badge>
    )
  }
  return (
    <Badge variant="accent" dot>
      {tr("Neu")}
    </Badge>
  )
}

export function NameResult({ name, pending, library, onShowInLibrary, className }: NameResultProps) {
  useI18n()
  const entry = library.entry
  const plan = library.plan
  const target = plan?.library ?? entry?.library ?? null
  return (
    <section aria-label={tr("Ergebnis")} className={cn('border-t border-line px-5 py-4', className)}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <h3 className="micro-label">{tr("Symbolname")}</h3>
        {name && !library.loading && <PlanBadge entry={entry} plan={plan} />}
        {library.loading && <Skeleton className="h-5 w-24 rounded-full" />}
      </div>
      <div className="flex min-h-11 items-center gap-2 rounded-button border border-line bg-surface-2/60 py-1.5 pl-3 pr-1.5 shadow-[inset_0_1px_0_var(--pf-highlight)]">
        {name ? (
          <span className="mono min-w-0 flex-1 select-all break-all text-sm font-semibold text-fg">{name}</span>
        ) : pending ? (
          <Skeleton className="h-4 w-40" />
        ) : (
          <span className="flex-1 text-xs text-fg-subtle">{tr("– noch kein gültiges Symbol –")}</span>
        )}
        <IconButton size="sm" label={tr("Symbolnamen kopieren")} icon={<Copy />} disabled={!name} onClick={() => name && void copyText(name, tr('Symbolname'))} />
      </div>
      {name && (
        <div className="mt-2 flex flex-col gap-1.5 text-xs leading-snug text-fg-muted" aria-live="polite">
          {plan?.error ? (
            <p className="flex items-start gap-1.5 text-danger-text">
              <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
              <span>{localizeMessage(plan.error)}</span>
            </p>
          ) : (
            <div className="flex min-h-4 flex-col gap-0.5">
              {plan?.checking && !target ? (
                <span className="flex items-center gap-1.5 text-fg-subtle">
                  <Spinner size={11} /> {tr("Ziel in der Bibliothek wird geprüft …")}
                </span>
              ) : target ? (
                <>
                  <span>
                    {entry ? (plan?.unchanged ? tr('Gespeichert in') : tr('Speichern aktualisiert es in')) : tr('Speichert neu in')}{' '}
                    <span className="mono text-fg" title={target}>
                      {baseName(target)}
                    </span>
                    {entry?.status_message && <span className="text-warning-text"> ({localizeMessage(entry.status_message)})</span>}
                  </span>
                  {entry && (
                    <span>
                      {entry.usage > 0 ? (
                        <>
                          {tr('Von {parts} verwendet', { parts: plural(entry.usage, tr('Bauteil'), tr('Bauteilen')) })}
                          {!plan?.unchanged && tr(' – die Änderung gilt überall')}
                        </>
                      ) : (
                        tr('Noch von keinem Bauteil verwendet')
                      )}
                    </span>
                  )}
                </>
              ) : null}
            </div>
          )}
          {entry && plan && plan.changes.length > 0 && !plan.error && (
            <ul className="flex flex-col gap-0.5 rounded-control border border-warning/30 bg-warning/8 px-2.5 py-1.5 text-2xs">
              {plan.changes.slice(0, 4).map((c) => (
                <li key={c} className="mono text-warning-text">
                  {c}
                </li>
              ))}
              {plan.changes.length > 4 && <li className="text-fg-subtle">{tr("… und")}{' '}{plan.changes.length - 4} {tr("weitere – Speichern fragt nach")}</li>}
            </ul>
          )}
        </div>
      )}
      {entry && onShowInLibrary && (
        <Button size="xs" variant="link" rightIcon={<ArrowRight />} onClick={() => onShowInLibrary(entry.name)} className="mt-1.5 h-auto px-0">
          {tr("In der Bibliothek zeigen")}
        </Button>
      )}
    </section>
  )
}
