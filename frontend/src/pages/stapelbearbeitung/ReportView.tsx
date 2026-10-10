/**
 * Bericht der Stapelbearbeitung: Zusammenfassung („12 von 340 Bauteilen weichen vom Hausstil ab“, je Regel die Anzahl –
 * die Chips filtern die Bauteilliste), die Bibliotheken (Lagenrollen, Lagen-Kopf, Schriften) und die Bauteile mit
 * ihren Änderungen. Ist der Bericht veraltet (Auswahl, Regeln, Rollen oder Hausstil seit der Prüfung geändert),
 * klebt ein Hinweis mit „Erneut prüfen“ oben; während einer neuen Prüfung bleibt der alte Bericht gedimmt stehen.
 */
import { CircleCheck, FolderInput, RefreshCw, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import type { ConformRules, LayerRoleName } from '@/api/housestyle'
import { Button, Callout, Card, ChipGroup, EmptyState } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatNumber, formatRelativeTime, plural } from '@/lib/format'
import { ComponentList } from './ComponentList'
import { LibrarySection } from './LibrarySection'
import { describeSelection, PROBLEMS_FILTER, reportStats, ruleLabel, type ReportStats, type StyleInfo } from './model'
import type { StoredReport } from './store'

export interface ReportViewProps {
  stored: StoredReport
  /** Auswahl, Regeln oder Hausstil seit der Prüfung geändert */
  outdated: boolean
  /** eine neue Prüfung läuft – der Bericht bleibt gedimmt stehen */
  refreshing: boolean
  /** Regel-Entwurf (Lagenrollen) */
  rules: ConformRules
  onRoleChange: (library: string, layer: string, role: LayerRoleName | null) => void
  layers: StyleInfo['layers'] | null
  onRecheck: () => void
  /** „Erneut prüfen“ geht gerade nicht (Grund) – `null` = möglich */
  recheckBlocked: string | null
  recheckPending: boolean
  /** Herkunft schon vollständig gewählt? (sonst bietet „keine Treffer“ an, sie zu erweitern) */
  allSources: boolean
  onWidenSources: () => void
}

export function ReportView({
  stored,
  outdated,
  refreshing,
  rules,
  onRoleChange,
  layers,
  onRecheck,
  recheckBlocked,
  recheckPending,
  allSources,
  onWidenSources,
}: ReportViewProps) {
  const { report } = stored
  const stats = reportStats(report)
  const [filter, setFilter] = useState<string[]>([])
  const fontsChecked = Boolean(stored.input.rules?.symbols?.fonts)

  return (
    <div className="flex flex-col gap-4">
      {outdated && !refreshing && (
        // klebt unter der Topbar; das Band darüber deckt den durchscrollenden Bericht ab
        <div className="sticky top-(--pf-topbar-height) z-sticky -mt-3 bg-bg pt-3">
          <div className="rounded-card bg-bg shadow-raised">
            <Callout
              tone="warning"
              live
              title="Der Bericht ist veraltet"
              actions={
                <Button
                  size="sm"
                  leftIcon={<RefreshCw />}
                  onClick={onRecheck}
                  disabled={Boolean(recheckBlocked)}
                  loading={recheckPending}
                >
                  Erneut prüfen
                </Button>
              }
            >
              Auswahl, Regeln, Lagenrollen oder Hausstil haben sich seit der Prüfung geändert – „Anwenden“ ist erst nach
              erneutem Prüfen möglich.
              {recheckBlocked && <span className="block text-warning-text">{recheckBlocked}</span>}
            </Callout>
          </div>
        </div>
      )}

      <div
        inert={refreshing}
        aria-busy={refreshing || undefined}
        className={cn('flex flex-col gap-4 transition-opacity duration-200', refreshing && 'opacity-50')}
      >
        {report.checked === 0 ? (
          <Card>
            <EmptyState
              illustration="search-empty"
              title="Keine passenden Symbole oder Footprints"
              description={
                allSources
                  ? 'In der Auswahl gibt es keine registrierten Symbole oder Footprints dieser Bibliothek. Vorhandene Altium-Bibliotheken lassen sich mit dem Bibliotheksimport übernehmen.'
                  : 'Die Auswahl umfasst nur die gewählte Herkunft – die Bauteile stammen vielleicht aus dem Generator oder aus Datenblättern. Weitere Herkunft wählen oder Bibliotheken übernehmen.'
              }
              actions={
                <>
                  {!allSources && (
                    <Button size="sm" onClick={onWidenSources}>
                      Alle Herkünfte wählen
                    </Button>
                  )}
                  <Button asChild size="sm" variant="ghost">
                    <Link to="/bibliotheksimport">
                      <FolderInput aria-hidden />
                      Bibliotheksimport öffnen
                    </Link>
                  </Button>
                </>
              }
            >
              <p className="text-xs text-fg-subtle">{describeSelection(stored.input.selection)}</p>
            </EmptyState>
          </Card>
        ) : (
          <>
            <Summary stored={stored} stats={stats} filter={filter} onFilterChange={setFilter} />
            {report.libraries.length > 0 && (
              <LibrarySection
                libraries={report.libraries}
                rules={rules}
                fontsChecked={fontsChecked}
                onRoleChange={onRoleChange}
                layers={layers}
              />
            )}
            {report.components.length > 0 && (
              <ComponentList report={report} ruleFilter={filter} onClearRuleFilter={() => setFilter([])} />
            )}
          </>
        )}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- Zusammenfassung

function Summary({
  stored,
  stats,
  filter,
  onFilterChange,
}: {
  stored: StoredReport
  stats: ReportStats
  filter: string[]
  onFilterChange: (filter: string[]) => void
}) {
  const { report } = stored
  const when = (
    <time dateTime={new Date(stored.finished).toISOString()} title={formatDateTime(stored.finished)}>
      geprüft {formatRelativeTime(stored.finished)}
    </time>
  )
  const meta = (
    <>
      {describeSelection(stored.input.selection)} · {when}
    </>
  )

  if (!stats.pending) {
    return (
      <Card>
        <EmptyState
          illustration="all-good"
          title="Alles im Hausstil"
          description={`${plural(stats.checked, 'Bauteil', 'Bauteile')} geprüft – keine eingeschaltete Regel ändert etwas.${
            stats.problemComponents || stats.unreadable
              ? ' Einzelne Dateien oder Bauteile ließen sich nicht lesen (siehe unten).'
              : ''
          }`}
        >
          <p className="text-xs text-fg-subtle">{meta}</p>
        </EmptyState>
      </Card>
    )
  }

  const rules = Object.entries(report.summary)
    .filter(([rule, n]) => rule !== 'header' && n > 0)
    .sort((a, b) => b[1] - a[1])
  const options = [
    ...rules.map(([rule, n]) => ({ value: rule, label: ruleLabel(rule), meta: formatNumber(n) })),
    ...(stats.problemComponents
      ? [{ value: PROBLEMS_FILTER, label: 'Probleme', meta: formatNumber(stats.problemComponents) }]
      : []),
  ]
  const ok = Math.max(0, stats.checked - stats.affected)
  const notes = [
    stats.headerLibraries > 0 &&
      `Der Lagen-Kopf weicht in ${plural(stats.headerLibraries, 'Bibliothek', 'Bibliotheken')} ab – „Anwenden“ erneuert ihn.`,
    stats.refused > 0 &&
      `${plural(stats.refused, 'Bibliothek wird', 'Bibliotheken werden')} beim Anwenden übersprungen.`,
    stats.unreadable > 0 &&
      (stats.unreadable === 1
        ? '1 Bibliothek ist nicht lesbar und bleibt unverändert.'
        : `${formatNumber(stats.unreadable)} Bibliotheken sind nicht lesbar und bleiben unverändert.`),
  ].filter((n): n is string => Boolean(n))

  return (
    <Card className="px-5 py-4">
      <h2 className="text-md font-semibold tracking-[-0.01em] text-fg">
        {stats.affected > 0 ? (
          <>
            <span className="mono">{formatNumber(stats.affected)}</span> von{' '}
            <span className="mono">{formatNumber(stats.checked)}</span> {stats.checked === 1 ? 'Bauteil' : 'Bauteilen'}{' '}
            {stats.affected === 1 ? 'weicht' : 'weichen'} vom Hausstil ab
          </>
        ) : (
          <>
            Alle Bauteile im Hausstil – {plural(stats.headerLibraries, 'Lagen-Kopf weicht', 'Lagen-Köpfe weichen')} ab
          </>
        )}
      </h2>
      <p className="mt-0.5 text-xs text-fg-subtle">{meta}</p>

      {/* Anteil: im Hausstil · weicht ab */}
      <div className="mt-3" aria-hidden>
        <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
          {ok > 0 && (
            <span className="h-full bg-success" style={{ width: `${(ok / Math.max(1, stats.checked)) * 100}%` }} />
          )}
          {stats.affected > 0 && (
            <span
              className="h-full bg-accent"
              style={{ width: `${(stats.affected / Math.max(1, stats.checked)) * 100}%` }}
            />
          )}
        </div>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
        <li className="flex items-center gap-1.5">
          <CircleCheck aria-hidden className="size-3.5 text-success-text" />
          <span className="mono font-medium text-fg">{formatNumber(ok)}</span> im Hausstil
        </li>
        <li className="flex items-center gap-1.5">
          <span aria-hidden className="size-2 rounded-full bg-accent" />
          <span className="mono font-medium text-fg">{formatNumber(stats.affected)}</span>{' '}
          {stats.affected === 1 ? 'weicht' : 'weichen'} ab
        </li>
        {stats.problemComponents > 0 && (
          <li className="flex items-center gap-1.5">
            <TriangleAlert aria-hidden className="size-3.5 text-warning-text" />
            <span className="mono font-medium text-fg">{formatNumber(stats.problemComponents)}</span> mit Problemen
          </li>
        )}
      </ul>

      {options.length > 0 && (
        <div className="mt-4 flex flex-col gap-1.5">
          <span className="text-2xs text-fg-subtle" aria-hidden>
            Bauteile je Regel – die Auswahl filtert die Liste unten
          </span>
          <ChipGroup
            size="sm"
            aria-label="Bauteilliste nach Regel filtern"
            value={filter}
            onValueChange={onFilterChange}
            options={options}
          />
        </div>
      )}

      {notes.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 border-t border-line pt-3 text-xs leading-snug text-fg-muted">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </Card>
  )
}
