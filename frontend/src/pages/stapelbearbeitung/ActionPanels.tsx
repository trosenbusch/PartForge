/**
 * Fortschritt und Ergebnis der Jobs auf der Seite: laufender Job (Fortschritt, bei der Prüfung „Abbrechen“), Ergebnis
 * von „Anwenden“ (angepasste Bauteile und Bibliotheken, je Regel, übersprungene und fehlerhafte Dateien) und von
 * „Rückgängig machen“, dazu der Hinweis auf die letzte Stapelbearbeitung, die sich rückgängig machen lässt.
 *
 * Anwenden und Rückgängig bieten bewusst kein „Abbrechen“: ein Abbruch mitten im Lauf hinterließe geänderte Dateien
 * ohne Rückgängig-Datensatz (das Backend schreibt ihn erst am Ende).
 */
import { CircleCheck, CircleX, Info, PaintbrushVertical, RefreshCw, TriangleAlert, Undo2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { cleanErrorText } from '@/api/client'
import type { ConformApplyResult, ConformUndoResult, UndoInfo } from '@/api/housestyle'
import { jobCancelText } from '@/api/jobs'
import type { Job } from '@/api/system'
import { Badge, Button, Callout, Card, CardFooter, PathText, ProgressBar } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatNumber, formatNumbersInText, plural } from '@/lib/format'
import { ruleLabel, splitPath } from './model'
import type { RunView } from './useBatchJobs'

// --------------------------------------------------------------------------- laufender Job

export interface JobProgressProps {
  job: Job | undefined
  title: string
  icon: ReactNode
  /** Zeile unter dem Balken (z. B. „Jede Datei wird vorher gesichert“) */
  note?: ReactNode
  onCancel?: () => void
  cancelling?: boolean
}

export function JobProgress({ job, title, icon, note, onCancel, cancelling }: JobProgressProps) {
  const stopping = Boolean(job?.cancel_requested)
  const waiting = !job || job.status === 'queued'
  const status = stopping
    ? 'Wird abgebrochen …'
    : job?.message
      ? formatNumbersInText(job.message)
      : waiting
        ? 'Wartet auf den Start …'
        : 'Läuft …'
  return (
    <Card className="px-5 py-4" aria-busy="true">
      <div className="flex items-start gap-4">
        <span
          aria-hidden
          className="flex size-10 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted [&_svg]:size-5"
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-fg">{title}</h2>
          {/* Meldung des Jobs links über dem Balken, Prozent rechts – zugleich Name des Fortschrittsbalkens */}
          <ProgressBar
            className="mt-2"
            value={job?.progress ?? 0}
            indeterminate={waiting}
            live
            label={
              <span aria-live="polite" title={job?.message || undefined}>
                {status}
              </span>
            }
            showValue={!waiting}
          />
          {note && <p className="mt-2 text-2xs leading-snug text-fg-subtle">{note}</p>}
        </div>
        {onCancel && (
          <Button size="sm" variant="ghost" onClick={onCancel} loading={cancelling} disabled={stopping}>
            Abbrechen
          </Button>
        )}
      </div>
    </Card>
  )
}

// --------------------------------------------------------------------------- Liste übersprungener/fehlerhafter Dateien

const LIST_PAGE = 8

function IssueList({
  title,
  tone,
  items,
}: {
  title: string
  tone: 'warning' | 'danger'
  items: { library: string; message: string }[]
}) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, LIST_PAGE)
  const Icon = tone === 'danger' ? CircleX : TriangleAlert
  return (
    <section className="border-t border-line px-5 py-3">
      <h3
        className={cn(
          'flex items-center gap-1.5 text-xs font-medium',
          tone === 'danger' ? 'text-danger-text' : 'text-warning-text',
        )}
      >
        <Icon aria-hidden className="size-3.5" />
        {title}
        <span className="mono text-fg-subtle">{formatNumber(items.length)}</span>
      </h3>
      <ul className="mt-1.5 flex flex-col gap-1">
        {shown.map((item, i) => (
          <li key={`${item.library}-${i}`} className="text-xs leading-snug">
            <PathText path={item.library} className="font-medium text-fg" />
            <span className="text-fg-muted"> – {formatNumbersInText(cleanErrorText(item.message))}</span>
          </li>
        ))}
      </ul>
      {items.length > LIST_PAGE && (
        <Button size="xs" variant="ghost" className="mt-1" onClick={() => setAll((v) => !v)}>
          {all ? 'Weniger anzeigen' : `${formatNumber(items.length - LIST_PAGE)} weitere anzeigen`}
        </Button>
      )}
    </section>
  )
}

/** Kopf einer Ergebniskarte: Statussymbol, Titel, Meldung */
function OutcomeHead({
  tone,
  title,
  children,
}: {
  tone: 'success' | 'warning' | 'neutral'
  title: string
  children?: ReactNode
}) {
  const icon = tone === 'success' ? <CircleCheck /> : tone === 'warning' ? <TriangleAlert /> : <Info />
  const ring =
    tone === 'success'
      ? 'bg-success/12 text-success-text'
      : tone === 'warning'
        ? 'bg-warning/14 text-warning-text'
        : 'bg-surface-3 text-fg-muted'
  return (
    <div className="flex items-start gap-3.5 px-5 py-4">
      <span
        aria-hidden
        className={cn('flex size-10 shrink-0 items-center justify-center rounded-full [&_svg]:size-5', ring)}
      >
        {icon}
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="text-md font-semibold tracking-[-0.01em] text-fg">{title}</h2>
        {children}
      </div>
    </div>
  )
}

interface RecheckProps {
  onRecheck: () => void
  /** Grund, warum gerade nicht geprüft werden kann (`null` = möglich) */
  recheckBlocked: string | null
  recheckPending: boolean
}

function RecheckButton({ onRecheck, recheckBlocked, recheckPending }: RecheckProps) {
  return (
    <Button
      size="sm"
      variant="secondary"
      leftIcon={<RefreshCw />}
      onClick={onRecheck}
      disabled={Boolean(recheckBlocked)}
      loading={recheckPending}
      title={recheckBlocked ?? undefined}
    >
      Erneut prüfen
    </Button>
  )
}

// --------------------------------------------------------------------------- Anwenden

export interface ApplyOutcomeProps extends RecheckProps {
  view: RunView<ConformApplyResult>
  /** was der Bericht beim Start versprach (Bauteile, Bibliotheken) */
  plan: { components: number; libraries: number } | null
  result: ConformApplyResult | null
  /** „Rückgängig machen“ (nur, wenn es einen Rückgängig-Datensatz gibt und nichts läuft) */
  onUndo: (() => void) | null
}

export function ApplyOutcome({ view, plan, result, onUndo, ...recheck }: ApplyOutcomeProps) {
  const { job, state } = view
  if (state === 'running') {
    return (
      <JobProgress
        job={job}
        title="Hausstil wird angewendet"
        icon={<PaintbrushVertical />}
        note={
          <>
            {plan &&
              (plan.components > 0
                ? `${plural(plan.components, 'Bauteil', 'Bauteile')} in ${plural(plan.libraries, 'Bibliothek', 'Bibliotheken')}. `
                : `Lagen-Kopf von ${plural(plan.libraries, 'Bibliothek', 'Bibliotheken')}. `)}
            Jede Datei wird vorher nach <span className="mono">Backups\lib</span> gesichert; Bibliotheken, die in Altium
            geöffnet und geändert sind, werden übersprungen.
          </>
        }
      />
    )
  }
  if ((state === 'failed' || state === 'cancelled') && job) {
    return (
      <Callout
        tone={state === 'failed' ? 'danger' : 'warning'}
        urgent
        title={state === 'failed' ? 'Anwenden fehlgeschlagen' : 'Anwenden abgebrochen'}
        actions={<RecheckButton {...recheck} />}
      >
        {state === 'failed' ? cleanErrorText(job.error ?? '') || 'Unbekannter Fehler.' : jobCancelText(job)}
        <span className="block">
          Bereits angepasste Bibliotheken bleiben geändert – ihre Sicherungen liegen unter{' '}
          <span className="mono">Backups\lib</span>. Erneut prüfen zeigt den aktuellen Stand.
        </span>
      </Callout>
    )
  }
  if (!result) {
    return (
      <Callout tone="neutral" title="Ergebnis nicht mehr verfügbar" actions={<RecheckButton {...recheck} />}>
        Das Ergebnis des letzten Anwendens liegt nicht mehr vor (z. B. nach einem Neustart von PartForge). Erneut prüfen
        zeigt den aktuellen Stand.
      </Callout>
    )
  }

  const skipped = result.skipped ?? []
  const errors = result.errors ?? []
  const nothing = !result.components && !result.libraries.length
  const tone = errors.length || skipped.length ? 'warning' : nothing ? 'neutral' : 'success'
  const title = nothing
    ? errors.length || skipped.length
      ? 'Nichts angepasst'
      : 'Nichts zu ändern'
    : `${plural(result.components, 'Bauteil', 'Bauteile')} in ${plural(result.libraries.length, 'Bibliothek', 'Bibliotheken')} angepasst`
  const perRule = result.report ? Object.entries(result.report.summary).filter(([, n]) => n > 0) : []
  const stats = [
    {
      label: 'Bauteile angepasst',
      value: result.components,
      tone: result.components ? 'text-success-text' : undefined,
    },
    { label: 'Bibliotheken geändert', value: result.libraries.length },
    { label: 'Übersprungen', value: skipped.length, tone: skipped.length ? 'text-warning-text' : undefined },
    { label: 'Fehler', value: errors.length, tone: errors.length ? 'text-danger-text' : undefined },
  ]

  return (
    <Card className="@container overflow-hidden">
      <OutcomeHead tone={tone} title={title}>
        {/* bei Erfolg sagt der Titel schon alles; sonst nennt die Meldung, was übersprungen wurde */}
        {result.message && tone !== 'success' && (
          <p className="mt-0.5 text-xs text-fg-muted">{formatNumbersInText(result.message)}</p>
        )}
        {!nothing && (
          <p className="mt-1 text-xs leading-snug text-fg-subtle">
            Die vorherigen Dateien liegen unter <span className="mono">Backups\lib</span>
            {result.undo ? ' – „Rückgängig machen“ stellt sie wieder her.' : '.'}
          </p>
        )}
      </OutcomeHead>
      <dl className="grid grid-cols-2 border-t border-line @[34rem]:grid-cols-4">
        {stats.map((s, i) => (
          <div
            key={s.label}
            className={cn(
              'flex flex-col gap-0.5 border-line px-5 py-3',
              i % 2 === 1 && 'border-l',
              i >= 2 && 'border-t @[34rem]:border-t-0',
              i === 2 && '@[34rem]:border-l',
            )}
          >
            <dt className="text-2xs text-fg-subtle">{s.label}</dt>
            <dd className={cn('mono text-h3 font-semibold tabular-nums', s.tone ?? 'text-fg')}>
              {formatNumber(s.value)}
            </dd>
          </div>
        ))}
      </dl>
      {perRule.length > 0 && (
        <section className="border-t border-line px-5 py-3">
          <h3 className="text-xs font-medium text-fg">Angepasst je Regel</h3>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {perRule.map(([rule, n]) => (
              <li key={rule}>
                <Badge variant="neutral" className="gap-1.5 font-normal">
                  {ruleLabel(rule)}
                  <span className="mono text-fg-subtle">{formatNumber(n)}</span>
                </Badge>
              </li>
            ))}
          </ul>
        </section>
      )}
      {skipped.length > 0 && <IssueList title="Übersprungen" tone="warning" items={skipped} />}
      {errors.length > 0 && <IssueList title="Fehler" tone="danger" items={errors} />}
      <CardFooter className="flex-wrap">
        <RecheckButton {...recheck} />
        <span className="text-2xs text-fg-subtle">zeigt, ob jetzt alles im Hausstil ist</span>
        {result.undo && onUndo && (
          <Button size="sm" variant="ghost" leftIcon={<Undo2 />} className="ml-auto" onClick={onUndo}>
            Rückgängig machen
          </Button>
        )}
      </CardFooter>
    </Card>
  )
}

// --------------------------------------------------------------------------- Rückgängig machen

export interface UndoOutcomeProps extends RecheckProps {
  view: RunView<ConformUndoResult>
  result: ConformUndoResult | null
}

export function UndoOutcome({ view, result, ...recheck }: UndoOutcomeProps) {
  const { job, state } = view
  if (state === 'running') {
    return (
      <JobProgress
        job={job}
        title="Stapelbearbeitung wird rückgängig gemacht"
        icon={<Undo2 />}
        note="Nur Bibliotheken, die seit der Stapelbearbeitung unverändert sind, bekommen ihre Sicherung zurück."
      />
    )
  }
  if ((state === 'failed' || state === 'cancelled') && job) {
    return (
      <Callout
        tone={state === 'failed' ? 'danger' : 'warning'}
        urgent
        title={state === 'failed' ? 'Rückgängig machen fehlgeschlagen' : 'Rückgängig machen abgebrochen'}
        actions={<RecheckButton {...recheck} />}
      >
        {state === 'failed' ? cleanErrorText(job.error ?? '') || 'Unbekannter Fehler.' : jobCancelText(job)}
      </Callout>
    )
  }
  if (!result) {
    return (
      <Callout tone="neutral" title="Ergebnis nicht mehr verfügbar" actions={<RecheckButton {...recheck} />}>
        Das Ergebnis liegt nicht mehr vor (z. B. nach einem Neustart von PartForge). Erneut prüfen zeigt den aktuellen
        Stand.
      </Callout>
    )
  }
  const restored = result.restored ?? []
  const skipped = result.skipped ?? []
  const tone = skipped.length ? 'warning' : restored.length ? 'success' : 'neutral'
  const title = restored.length
    ? `${plural(restored.length, 'Bibliothek', 'Bibliotheken')} wiederhergestellt`
    : 'Nichts wiederhergestellt'
  return (
    <Card className="overflow-hidden">
      <OutcomeHead tone={tone} title={title}>
        {result.message && tone !== 'success' && (
          <p className="mt-0.5 text-xs text-fg-muted">{formatNumbersInText(result.message)}</p>
        )}
        {restored.length > 0 && (
          <p className="mt-1 text-xs leading-snug text-fg-subtle">
            Auch die Einträge in PartForge haben ihren vorherigen Stand zurück.
            {skipped.length > 0 && ' Die übersprungenen lassen sich später erneut zurücksetzen.'}
          </p>
        )}
      </OutcomeHead>
      {restored.length > 0 && (
        <section className="border-t border-line px-5 py-3">
          <h3 className="text-xs font-medium text-fg">Wiederhergestellt</h3>
          <p className="mt-1 text-xs leading-snug text-fg-muted [overflow-wrap:anywhere]">
            {restored
              .slice(0, 12)
              .map((rel) => splitPath(rel).name)
              .join(' · ')}
            {restored.length > 12 && ` und ${formatNumber(restored.length - 12)} weitere`}
          </p>
        </section>
      )}
      {skipped.length > 0 && <IssueList title="Nicht zurückgesetzt" tone="warning" items={skipped} />}
      <CardFooter className="flex-wrap">
        <RecheckButton {...recheck} />
        <span className="text-2xs text-fg-subtle">zeigt den Stand nach dem Zurücksetzen</span>
      </CardFooter>
    </Card>
  )
}

// --------------------------------------------------------------------------- letzte Stapelbearbeitung

export function UndoNotice({
  info,
  onUndo,
  disabled,
  pending,
}: {
  info: UndoInfo
  onUndo: () => void
  disabled: boolean
  pending: boolean
}) {
  const libraries = info.libraries ?? []
  const when = info.created ? ` vom ${formatDateTime(info.created)}` : ''
  return (
    <Callout
      tone="neutral"
      icon={<Undo2 />}
      title={`Letzte Stapelbearbeitung${when} (${plural(libraries.length, 'Bibliothek', 'Bibliotheken')})`}
      actions={
        <Button
          size="sm"
          variant="secondary"
          leftIcon={<Undo2 />}
          onClick={onUndo}
          disabled={disabled}
          loading={pending}
        >
          Rückgängig machen
        </Button>
      }
    >
      Stellt die Bibliotheken aus ihren Sicherungen wieder her – nur solche, die seitdem unverändert sind.
      {libraries.length > 0 && (
        <span className="block text-fg-subtle [overflow-wrap:anywhere]">
          {libraries
            .slice(0, 3)
            .map((rel) => splitPath(rel).name)
            .join(' · ')}
          {libraries.length > 3 && ` und ${formatNumber(libraries.length - 3)} weitere`}
        </span>
      )}
    </Callout>
  )
}
