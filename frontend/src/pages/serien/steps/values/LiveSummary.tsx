import { localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Live-Zähler im Schritt „Werte und Varianten“: „4 Bauformen × 673 Werte + 4 Brücken = 2.696 Bauteile“ sofort
 * aus der Vorlage, daneben die Prüfung durch das Backend (neu/vorhanden/Konflikt/ungültig, Footprints) und ein
 * Beispiel mit dem Aufbau der Teilenummer. Ausgelassene Reihenwerte (laut Datenblatt mit dieser Auswahl nicht
 * lieferbar) zählt das Backend je Baugröße (`skipped_by_size`) – bis seine Antwort da ist, steht die Sofort-Schätzung.
 *
 * Die Karte ist ein Container: schmal (rechte Spalte) stehen die Abschnitte untereinander, breit (über dem Formular
 * in kleinen Fenstern) nebeneinander – der Zähler bleibt so beim Wählen der Bauformen im Blick.
 * Screenreader hören das Ergebnis einmal, wenn es sich gesetzt hat (nicht jede Zwischenzahl des Hochzählens).
 */
import { CircleCheck, CircuitBoard, Info, RefreshCw, TriangleAlert } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import type { SeriesPreview } from '@/api/series'
import { Button, Callout, CountUp, Skeleton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { MpnAnatomy } from '../../components/MpnAnatomy'
import type { MpnSegment } from '../../model/anatomy'
import type { Estimate } from '../../model/estimate'
import {
  countLabel,
  isSkippedWarning,
  midSentence,
  ROW_STATUS,
  serverParts,
  skippedSizes,
  STATUS_ORDER,
  TONE_DOT,
} from '../../model/status'

export interface LiveSummaryProps {
  estimate: Estimate
  maxRows: number
  /** Vorschau des Backends zur aktuellen Auswahl (oder die letzte, solange neu geprüft wird) */
  preview: SeriesPreview | undefined
  /** Vorschau passt zur aktuellen Auswahl */
  current: boolean
  checking: boolean
  /** Fehler der Prüfung zur aktuellen Auswahl (deutscher Text des Backends) */
  error: unknown
  onRetry?: () => void
  example: { mpn: string; segments: MpnSegment[] | null; description: string | null } | null
  /** Baugrößen in der Reihenfolge der Auswahl (ausgelassene Werte je Baugröße) */
  sizeOrder?: string[]
  className?: string
}

function Num({ children, muted }: { children: ReactNode; muted?: boolean }) {
  return <span className={cn('mono font-semibold', muted ? 'text-fg-muted' : 'text-fg')}>{children}</span>
}

/** Ansage erst, wenn sich die Zahl gesetzt hat; `null` = letzte Ansage behalten (z. B. während der Prüfung) */
function useSettledAnnouncement(text: string | null, delay = 900): string {
  const [said, setSaid] = useState('')
  useEffect(() => {
    if (text === null) return
    const t = window.setTimeout(() => setSaid(text), delay)
    return () => window.clearTimeout(t)
  }, [text, delay])
  return said
}

const SECTION = 'flex min-w-0 flex-col px-5 py-4'

export function LiveSummary({
  estimate: e,
  maxRows,
  preview,
  current,
  checking,
  error,
  onRetry,
  example,
  sizeOrder,
  className,
}: LiveSummaryProps) {
  const { t: tr } = useI18n()
  const serverTotal = preview && current && !error ? serverParts(preview.counts) : null
  const total = serverTotal ?? e.total
  /** Ausgelassene Reihenwerte: laut Prüfung (je Baugröße, mit Grund), bis dahin geschätzt */
  const checked = preview && current && !error ? preview : null
  const skipped = checked ? checked.skipped_total : e.skipped
  const skippedBySize = checked ? skippedSizes(checked.skipped_by_size, sizeOrder) : []
  const warnings = checked ? checked.warnings.filter((w) => !(checked.skipped_total > 0 && isSkippedWarning(w))) : []
  const tooMany = e.total + e.invalid > maxRows
  const product = e.sizes * e.values
  const exact = e.sizes > 0 && product === e.parts
  const needed = preview?.footprints_needed.length ?? 0
  const failed = Boolean(error)
  const counted = !tooMany && e.total > 0

  const partsWord = total === 1 ? tr("Bauteil") : tr("Bauteile")
  const announcement = useSettledAnnouncement(
    failed || checking
      ? null
      : serverTotal !== null && preview
        ? tr("{v0} {v1} laut Prüfung: {v2}.", { v0: formatNumber(total), v1: partsWord, v2: STATUS_ORDER.map((s) => `${formatNumber(preview.counts[s] ?? 0)} ${countLabel(s, preview.counts[s] ?? 0)}`).join(', ') })
        : `${formatNumber(total)} ${partsWord}.`,
  )

  const status = failed ? (
    <span className="flex items-center gap-1.5 font-medium text-danger-text">
      <TriangleAlert aria-hidden className="size-3.5" /> {tr("Prüfung fehlgeschlagen")}</span>
  ) : checking || !current ? (
    <>
      <Spinner size={12} /> {tr("wird geprüft …")}</>
  ) : preview ? (
    <>
      <CircleCheck aria-hidden className="size-3.5 text-success" /> {tr("geprüft in")} {formatNumber(Math.max(0.01, preview.duration_s), 2)} s
    </>
  ) : null

  return (
    <div
      data-estimate={e.total}
      data-server={serverTotal ?? undefined}
      data-skipped={skipped}
      className={cn('@container flex flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card', className)}
    >
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {announcement}
      </p>
      <div className="grid grid-cols-1 @[44rem]:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)_minmax(0,1fr)]">
        {/* ------------------------------------------------------------ Ergebnis */}
        <section aria-label={tr("Ergebnis")} className={cn(SECTION, 'relative')}>
          <div
            aria-hidden
            className="pointer-events-none absolute -right-16 -top-20 size-56 rounded-full bg-[radial-gradient(closest-side,var(--pf-ember-faint),transparent)]"
          />
          <div className="micro-label">{tr("Ergebnis")}</div>
          <div className="mt-1.5 flex flex-wrap items-baseline gap-x-2">
            <span
              aria-hidden
              className={cn('mono text-metric font-semibold tracking-[-0.02em]', tooMany ? 'text-danger-text' : 'text-fg')}
            >
              <CountUp value={total} />
            </span>
            <span aria-hidden className="text-ui text-fg-muted">
              {partsWord}
            </span>
            <span className="sr-only">{`${formatNumber(total)} ${partsWord}`}</span>
            {serverTotal !== null && serverTotal !== e.total && <span className="text-2xs text-fg-subtle">{tr("laut Prüfung")}</span>}
          </div>
          <p className="mt-1 flex flex-wrap items-baseline gap-x-1.5 text-ui text-fg-muted">
            <Num>{formatNumber(e.sizes)}</Num> {e.sizes === 1 ? tr("Bauform") : tr("Bauformen")}
            <span aria-hidden className="text-fg-subtle">
              ×
            </span>
            <span className="sr-only">{tr("mal")}</span>
            <Num>{formatNumber(e.values)}</Num> {e.values === 1 ? tr("Wert") : tr("Werte")}
            {e.jumpers > 0 && (
              <>
                <span aria-hidden className="text-fg-subtle">
                  +
                </span>
                <span className="sr-only">plus</span>
                <Num>{formatNumber(e.jumpers)}</Num> {e.jumpers === 1 ? tr("Brücke") : tr("Brücken")}
              </>
            )}
          </p>
          {!exact && e.parts > 0 && <p className="mt-1 text-2xs text-fg-subtle">{tr("Nicht jeder Wert ist in jeder Bauform lieferbar.")}</p>}
          {skipped > 0 && !tooMany && (
            <div className="mt-1.5 text-2xs leading-snug text-fg-subtle">
              <p>
                {plural(skipped, tr("Reihenwert"), tr("Reihenwerte"))} {tr("ausgelassen –")}{' '}
                {/* kurz – der volle Grund (mit Klammerzusatz) steht in der Vorschau */}
                {checked?.skipped_reason ? midSentence(localizeMessage(checked.skipped_reason).replace(/\s*\([^)]*\)\s*$/, '')) : tr("laut Datenblatt nicht lieferbar")}.
              </p>
              {skippedBySize.length > 1 && (
                <p className="mt-0.5 flex flex-wrap gap-x-2.5">
                  {skippedBySize.map(([size, n]) => (
                    <span key={size} className="whitespace-nowrap">
                      <span className="mono text-fg-muted">{size}</span> {formatNumber(n)}
                    </span>
                  ))}
                </p>
              )}
            </div>
          )}
          {e.invalid > 0 && (
            <p className="mt-1 text-2xs text-warning-text">
              {plural(e.invalid, tr("Kombination"), tr("Kombinationen"))} {tr("aus Wert und Bauform gibt es so nicht – sie erscheinen als „ungültig“.")}</p>
          )}
        </section>

        {/* ------------------------------------------------------------ Prüfung */}
        {tooMany ? (
          <div className="border-t border-line p-4 @[44rem]:col-span-2 @[44rem]:border-l @[44rem]:border-t-0">
            <Callout tone="danger" title={tr("Höchstens {v0} Bauteile je Serie", { v0: formatNumber(maxRows) })}>
              {tr("Bitte Bereich, Bauformen oder E-Reihe einschränken.")}</Callout>
          </div>
        ) : e.total === 0 ? (
          <div className="border-t border-line p-4 @[44rem]:col-span-2 @[44rem]:border-l @[44rem]:border-t-0">
            <Callout tone="warning" title={tr("Mit dieser Auswahl entstehen keine Bauteile")}>
              {tr("Bauformen, Bereich oder Varianten anpassen.")}</Callout>
          </div>
        ) : (
          <section aria-label={tr("Prüfung")} className={cn(SECTION, 'border-t border-line @[44rem]:border-l @[44rem]:border-t-0')}>
            <div className="flex items-center justify-between gap-2">
              <span className="micro-label">{tr("Prüfung")}</span>
              <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">{status}</span>
            </div>
            {failed ? (
              <div role="alert" className="mt-2 flex flex-col items-start gap-2.5">
                <p className="text-xs leading-relaxed text-danger-text">{errorMessage(error)}</p>
                {onRetry && (
                  <Button size="xs" variant="secondary" leftIcon={<RefreshCw />} onClick={onRetry}>
                    {tr("Erneut prüfen")}</Button>
                )}
              </div>
            ) : preview ? (
              <div className={cn('mt-2 flex flex-col gap-2 transition-opacity', !current && 'opacity-55')}>
                <ul className="grid grid-cols-2 gap-x-3 gap-y-1.5">
                  {STATUS_ORDER.map((s) => {
                    const n = preview.counts[s] ?? 0
                    const meta = ROW_STATUS[s]
                    return (
                      <li key={s} className={cn('flex items-center gap-2 text-xs', n === 0 ? 'text-fg-subtle' : 'text-fg-muted')}>
                        <span
                          aria-hidden
                          className={cn('size-1.5 shrink-0 rounded-full', n === 0 ? 'bg-line-strong' : TONE_DOT[meta.tone])}
                        />
                        <Num muted={n === 0}>{formatNumber(n)}</Num>
                        {countLabel(s, n)}
                      </li>
                    )
                  })}
                </ul>
                <p className="flex items-start gap-2 text-xs text-fg-muted">
                  <CircuitBoard aria-hidden className="mt-0.5 size-3.5 shrink-0 text-fg-subtle" />
                  <span>
                    {needed
                      ? tr("{v0} erzeugt", { v0: plural(needed, tr("Footprint wird"), tr("Footprints werden")) })
                      : tr("Alle {v0} vorhanden", { v0: plural(preview.footprints.length, tr("Footprint"), tr("Footprints")) })}
                    {preview.symbol ? tr(" · Symbol „{v0}“{v1}", { v0: preview.symbol.name, v1: preview.symbol.exists ? '' : tr("(neu)") }) : ''}
                  </span>
                </p>
              </div>
            ) : (
              <div className="mt-2 flex flex-col gap-1.5">
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3.5 w-1/2" />
              </div>
            )}
          </section>
        )}

        {/* ------------------------------------------------------------ Beispiel */}
        {counted && (
          <section aria-label={tr("Beispiel")} className={cn(SECTION, 'border-t border-line @[44rem]:border-l @[44rem]:border-t-0')}>
            <div className="micro-label mb-2">{tr("Beispiel")}</div>
            {example ? (
              <>
                <MpnAnatomy mpn={example.mpn} segments={example.segments} labels="short" size="md" />
                {example.description && <p className="mt-2 line-clamp-2 text-xs text-fg-muted">{example.description}</p>}
              </>
            ) : failed ? (
              <p className="text-xs text-fg-subtle">{tr("Erscheint nach der Prüfung.")}</p>
            ) : preview && current ? (
              <p className="text-xs text-fg-subtle">{tr("Kein anlegbares Bauteil in dieser Auswahl.")}</p>
            ) : (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-6 w-4/5" />
                <Skeleton className="h-3.5 w-3/5" />
              </div>
            )}
          </section>
        )}
      </div>

      {warnings.length > 0 && (
        <section aria-label={tr("Hinweise der Prüfung")} className="border-t border-line px-5 py-3.5">
          <ul className="flex flex-col gap-1.5">
            {warnings.slice(0, 4).map((w) => (
              <li key={w} className="flex gap-2 text-xs leading-snug text-fg-muted">
                <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning" />
                {localizeMessage(w)}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
