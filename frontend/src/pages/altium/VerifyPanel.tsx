import { useI18n, localizeMessage } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { CircleX, RotateCw, Search, ShieldCheck, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { useLastVerify, type FootprintCheck, type VerifiedPart, type VerifyResult, type VerifyRun } from '@/api/altium'
import { cleanErrorText, errorMessage } from '@/api/client'
import { jobCancelText, useInlineJob, useJob } from '@/api/jobs'
import { useCategories, type CategoryDef } from '@/api/library'
import { isJobActive, useCancelJob, type Job } from '@/api/system'
import { Button, Callout, Card, EmptyState, IconButton, Input, ProgressBar, SegmentedControl, Skeleton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatDuration, formatNumber, formatRelativeTime, plural, toMillis } from '@/lib/format'
import { partPath } from './paths'
import { VerifyMenu, type VerifyScope } from './StatusHero'
import { useLatestJob } from './useAltiumActions'
import { FilterLabel, OkIcon, SeverityIcon } from './ui'
import { PartTexts } from './VerifyParameters'

type Filter = 'all' | 'error' | 'warning' | 'ok'
const PAGE = 100

export interface VerifyPanelProps {
  /** Warum gerade nicht in Altium geprüft werden kann (`null` = Altium bereit) */
  blocker: string | null
  pending: boolean
  onVerify: (scope: VerifyScope) => void
}

/** Ende eines Jobs bzw. einer gespeicherten Prüfung in ms */
const jobEnd = (job: Pick<Job, 'finished' | 'created'>) => toMillis(job.finished ?? job.created)

export function VerifyPanel({ blocker, pending, onVerify }: VerifyPanelProps) {
  const { t: tr } = useI18n()
  const lastQ = useLastVerify()
  const run = lastQ.data ?? null
  // Laufende bzw. gescheiterte Prüfung aus der Jobliste (Kurzfassung – für Zustand und Fortschritt genügt sie)
  const latest = useLatestJob('altium.verify')
  const running = latest && isJobActive(latest) ? latest : undefined
  const { job: live } = useJob<VerifyResult>(running?.id)
  const progress = running ? (live && live.version >= running.version ? live : running) : undefined
  const finishedAt = run ? toMillis(run.finished) : 0
  // Neuer als das gespeicherte Ergebnis gescheitert/abgebrochen: Hinweis darüber, das letzte Ergebnis bleibt
  const failed =
    latest && (latest.status === 'failed' || latest.status === 'cancelled') && jobEnd(latest) > finishedAt ? latest : undefined
  // Gerade fertig geworden, das neue Ergebnis wird noch geladen
  const loadingNew = Boolean(latest?.status === 'done' && jobEnd(latest) > finishedAt + 1500 && lastQ.isFetching)

  if (lastQ.isPending && !progress) return <VerifySkeleton />

  return (
    <div className="flex flex-col gap-4">
      {progress && <VerifyProgress job={progress as Job<VerifyResult>} />}
      {!progress && failed && (
        <Callout
          tone={failed.status === 'cancelled' ? 'neutral' : 'danger'}
          title={failed.status === 'cancelled' ? tr("Prüfung abgebrochen") : tr("Prüfung in Altium fehlgeschlagen")}
          // mit gespeichertem Ergebnis steht „Erneut prüfen“ (samt „nur mit Befund“) an dessen Zusammenfassung
          actions={run ? undefined : <VerifyMenu onVerify={onVerify} pending={pending} label={tr("Erneut prüfen")} blocked={blocker} />}
        >
          {failed.status === 'cancelled' ? jobCancelText(failed) : cleanErrorText(failed.error ?? '') || tr("Kein Ergebnis.")}
          {run && (
            <span className="block">
              {tr("Unten steht weiter das Ergebnis vom ")}{formatDateTime(run.finished)}.
            </span>
          )}
        </Callout>
      )}
      {lastQ.isError && !run && (
        <Callout
          tone="danger"
          title={tr("Letztes Prüfergebnis nicht verfügbar")}
          actions={
            <Button size="sm" leftIcon={<RotateCw />} onClick={() => void lastQ.refetch()} loading={lastQ.isFetching}>
              {tr("Erneut laden")}</Button>
          }
        >
          {errorMessage(lastQ.error)}
        </Callout>
      )}
      {run ? (
        <VerifyResults key={run.finished} run={run} pending={pending} blocker={blocker} onVerify={onVerify} refreshing={loadingNew} />
      ) : (
        !progress &&
        !failed &&
        !lastQ.isError && (
          <Card>
            <EmptyState
              illustration="forge"
              title={tr("Noch nicht in Altium geprüft")}
              description={
                blocker
                  ? tr("Sobald Altium Designer läuft, lässt PartForge Altium jedes Bauteil auflösen – Symbol, Pins und Footprints, genau wie beim Platzieren. Das Ergebnis bleibt in der Bibliothek gespeichert.")
                  : tr("Altium löst jedes Bauteil auf – genau wie beim Platzieren: Symbol gefunden, Pins vollständig, jeder Footprint zugeordnet und in seiner Bibliothek enthalten, Parameter und Beschreibung wie in der Datenbank. Die Stichprobe verteilt sich über alle Kategorien.")
              }
              actions={<VerifyMenu onVerify={onVerify} pending={pending} size="md" label={tr("In Altium prüfen")} blocked={blocker} />}
            />
          </Card>
        )
      )}
    </div>
  )
}

function VerifySkeleton() {
  const { t: tr } = useI18n()
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label={tr("Letztes Prüfergebnis wird geladen")}>
      <Card className="px-5 py-4">
        <Skeleton className="h-4 w-72" />
        <Skeleton className="mt-2 h-3 w-56" />
        <Skeleton className="mt-4 h-1.5 w-full rounded-full" />
      </Card>
      <Card className="divide-y divide-line">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex items-center gap-4 px-4 py-3">
            <Skeleton className="size-4" />
            <Skeleton className="h-3.5 w-40" />
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="ml-auto h-3.5 w-64" />
          </div>
        ))}
      </Card>
    </div>
  )
}

function VerifyProgress({ job }: { job: Job<VerifyResult> }) {
  const { t: tr } = useI18n()
  const cancel = useCancelJob()
  // Fortschritt und Ergebnis stehen hier – solange sichtbar, zählt der Job nicht in der Pille des Job-Docks
  useInlineJob(job.id)
  const stopping = Boolean(job.cancel_requested)
  return (
    <Card className="px-5 py-5">
      <div className="flex items-start gap-4">
        <span
          aria-hidden
          className="flex size-10 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface-2 text-fg-muted [&_svg]:size-5"
        >
          <ShieldCheck />
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-fg">{job.title}</h3>
          <p className="mt-0.5 truncate text-xs text-fg-muted" aria-live="polite">
            {stopping ? tr("Wird abgebrochen …") : job.message || tr("Altium wird vorbereitet …")}
          </p>
          <ProgressBar className="mt-3" value={job.progress} live label={tr("Fortschritt der Prüfung in Altium")} hideLabel showValue />
        </div>
        <Button size="sm" variant="ghost" onClick={() => cancel.mutate(job.id)} loading={cancel.isPending} disabled={stopping}>
          {tr("Abbrechen")}</Button>
      </div>
    </Card>
  )
}

// --------------------------------------------------------------------------- Ergebnisse

/** Was die Prüfung umfasste – „Stichprobe über 13 Kategorien · aus 7.077 Bauteilen“ */
function scopeText(run: VerifyRun, catMap: Map<string, CategoryDef>): string {
  const { summary } = run
  const tables = run.tables.map((t) => catMap.get(t)?.label ?? t)
  const where = tables.length === 1 ? tr(" in „{0}“", { "0": String(tables[0]) }) : tables.length > 1 ? ` in ${plural(tables.length, tr("Kategorie"), tr("Kategorien"))}` : ''
  if (run.scope === 'part_numbers') return tr("ausgewählte Bauteile")
  if (run.scope === 'all') return tables.length ? tr("alle Bauteile{0}", { "0": String(where) }) : tr("alle Bauteile aus {0}", { "0": String(plural(summary.categories, tr("Kategorie"), tr("Kategorien"))) })
  const of = summary.total > summary.checked ? tr(" · aus {0}", { "0": String(plural(summary.total, tr("Bauteil"), tr("Bauteilen"))) }) : ''
  if (run.sample === 'first') return tr("die ersten in Kategorie-Reihenfolge{0}{1}", { "0": String(where), "1": String(of) })
  return tr("Stichprobe über {0}{1}{2}", { "0": String(plural(summary.categories, tr("Kategorie"), tr("Kategorien"))), "1": String(where), "2": String(of) })
}

function VerifyResults({
  run,
  pending,
  blocker,
  onVerify,
  refreshing,
}: {
  run: VerifyRun
  pending: boolean
  blocker: string | null
  onVerify: (scope: VerifyScope) => void
  /** ein neues Ergebnis wird gerade geladen */
  refreshing: boolean
}) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const categories = useCategories().data
  const catMap = useMemo(() => new Map((categories ?? []).map((c) => [c.table, c] as const)), [categories])
  const { summary } = run
  const [filter, setFilter] = useState<Filter>(() => (summary.errors ? 'error' : summary.warnings ? 'warning' : 'all'))
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(PAGE)

  const needle = query.trim().toLowerCase()
  const rows = useMemo(
    () =>
      run.results.filter((p) => {
        if (filter !== 'all' && p.status !== filter) return false
        if (!needle) return true
        return [p.part_number, p.table, catMap.get(p.table)?.label, p.library_ref, p.lib_reference, p.comment, p.description, ...p.footprint_checks.map((c) => c.footprint), ...p.messages.map((message) => tr(localizeMessage(message)))]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(needle))
      }),
    [run.results, filter, needle, catMap, tr],
  )
  const shown = rows.slice(0, limit)
  const flagged = run.results.filter((p) => p.status !== 'ok').map((p) => p.part_number)

  return (
    <div className="flex flex-col gap-4">
      {/* Zusammenfassung */}
      <Card className="px-5 py-4">
        <div className="flex flex-col gap-4 @[48rem]:flex-row @[48rem]:items-center">
          <div className="min-w-0 flex-1">
            <h3 className="flex flex-wrap items-baseline gap-x-1.5 text-sm font-semibold text-fg">
              {plural(summary.checked, tr("Bauteil"), tr("Bauteile"))} {tr(" in Altium geprüft")}<span className="font-normal text-fg-muted">· {scopeText(run, catMap)}</span>
              {refreshing && <Spinner size={12} tone="accent" label={tr("Neues Ergebnis wird geladen")} className="self-center" />}
            </h3>
            <p className="mt-0.5 text-xs text-fg-subtle">
              <time dateTime={run.finished} title={formatDateTime(run.finished)}>
                {formatRelativeTime(run.finished)}
              </time>
              {tr(" · Dauer {0}", { "0": String(formatDuration(summary.duration_s)) })}
              {summary.altium_runs ? ` · ${plural(summary.altium_runs, tr("Altium-Lauf"), tr("Altium-Läufe"))}` : ''}
              {summary.temporarily_installed && tr(" · DbLib dafür vorübergehend installiert")}
            </p>
            <ResultBar summary={summary} />
          </div>
          <VerifyMenu
            onVerify={onVerify}
            pending={pending}
            blocked={blocker}
            label={tr("Erneut prüfen")}
            extra={
              flagged.length
                ? [
                    {
                      scope: { kind: 'parts', partNumbers: flagged, label: tr("Nur {0} mit Befund", { "0": String(plural(flagged.length, tr("Bauteil"), tr("Bauteile"))) }) },
                      description: tr("nach dem Beheben gezielt nachprüfen"),
                    },
                  ]
                : undefined
            }
          />
        </div>
      </Card>

      {/* Filter */}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl<Filter>
          size="sm"
          aria-label={tr("Ergebnisse filtern")}
          value={filter}
          onValueChange={(v) => {
            setFilter(v)
            setLimit(PAGE)
          }}
          options={[
            { value: 'all', label: <FilterLabel label={tr("Alle")} count={summary.checked} /> },
            { value: 'error', label: <FilterLabel label={tr("Fehler")} count={summary.errors} tone="error" /> },
            { value: 'warning', label: <FilterLabel label={tr("Hinweise")} count={summary.warnings} tone="warning" /> },
            { value: 'ok', label: <FilterLabel label={tr("In Ordnung")} count={summary.ok} /> },
          ]}
        />
        <Input
          size="sm"
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value)
            setLimit(PAGE)
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && query) {
              e.stopPropagation()
              setQuery('')
            }
          }}
          placeholder={tr("Bauteil, Symbol, Footprint …")}
          aria-label={tr("Ergebnisse durchsuchen")}
          prefix={<Search />}
          suffix={query ? <IconButton size="xs" label={tr("Suche leeren")} icon={<X />} onClick={() => setQuery('')} tooltip={false} /> : undefined}
          containerClassName="w-64 max-w-full"
        />
        <span className="ml-auto text-xs text-fg-subtle" aria-live="polite">
          {rows.length === run.results.length ? plural(rows.length, tr("Bauteil"), tr("Bauteile")) : tr("{0} von {1}", { "0": String(formatNumber(rows.length)), "1": String(formatNumber(run.results.length)) })}
        </span>
      </div>

      <Card className="@container overflow-hidden">
        {rows.length === 0 ? (
          <EmptyState
            size="sm"
            illustration={filter === 'error' && !needle ? 'all-good' : 'search-empty'}
            title={filter === 'error' && !needle ? tr("Keine Fehler") : tr("Keine Treffer")}
            description={filter === 'error' && !needle ? tr("Altium hat jedes geprüfte Bauteil vollständig aufgelöst.") : tr("Kein Bauteil passt zu Filter und Suche.")}
          />
        ) : (
          <>
            <table className="w-full table-fixed border-collapse text-left">
              <caption className="sr-only">{tr("Ergebnis der Prüfung in Altium")}</caption>
              <thead>
                <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
                  <th scope="col" className="w-10 py-2.5 pl-4 pr-1">
                    <span className="sr-only">Status</span>
                  </th>
                  <th scope="col" className="w-[28%] px-3 py-2.5 @[60rem]:w-[19%]">{tr("Bauteil")}</th>
                  <th scope="col" className="w-[22%] px-3 py-2.5 @[60rem]:w-[15%]">Symbol</th>
                  <th scope="col" className="w-20 px-3 py-2.5 text-right">Pins</th>
                  <th scope="col" className="px-3 py-2.5">Footprints</th>
                  <th scope="col" className="hidden w-[32%] py-2.5 pl-3 pr-4 @[60rem]:table-cell">{tr("Meldungen")}</th>
                </tr>
              </thead>
              {shown.map((p) => (
                <PartRows key={`${p.table}|${p.part_number}`} part={p} cat={catMap.get(p.table)} onOpen={() => navigate(partPath(p))} />
              ))}
            </table>
            {rows.length > shown.length && (
              <div className="flex items-center gap-3 border-t border-line px-4 py-2.5">
                <Button size="xs" variant="ghost" onClick={() => setLimit((l) => l + PAGE)}>
                  {formatNumber(Math.min(PAGE, rows.length - shown.length))} {tr(" weitere anzeigen")}</Button>
                <span className="text-2xs text-fg-subtle">
                  {formatNumber(shown.length)} {tr(" von ")}{formatNumber(rows.length)} {' '}{tr("angezeigt")}</span>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  )
}

function ResultBar({ summary }: { summary: VerifyRun['summary'] }) {
  const { t: tr } = useI18n()
  const total = Math.max(1, summary.checked)
  const parts = [
    { key: 'ok', n: summary.ok, label: tr("in Ordnung"), color: 'var(--pf-success)' },
    { key: 'warning', n: summary.warnings, label: tr("mit Hinweisen"), color: 'var(--pf-warning)' },
    { key: 'error', n: summary.errors, label: tr("mit Fehlern"), color: 'var(--pf-danger)' },
  ]
  return (
    <div className="mt-3">
      <div aria-hidden className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-3">
        {parts.map((p) =>
          p.n > 0 ? <span key={p.key} className="h-full first:rounded-l-full last:rounded-r-full" style={{ width: `${(p.n / total) * 100}%`, background: p.color }} /> : null,
        )}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-muted">
        {parts.map((p) => (
          <li key={p.key} className="flex items-center gap-1.5">
            <span aria-hidden className="size-2 rounded-full" style={{ background: p.color }} />
            <span className="mono font-medium text-fg">{formatNumber(p.n)}</span> {p.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** Ein Bauteil: Zeile mit Symbol, Pins, Footprints – Meldungen als Spalte (breit) bzw. als zweite Zeile (schmal) */
function PartRows({ part: p, cat, onOpen }: { part: VerifiedPart; cat: CategoryDef | undefined; onOpen: () => void }) {
  const { t: tr } = useI18n()
  const [expanded, setExpanded] = useState(false)
  const symbolName = p.lib_reference || p.library_ref || '–'
  const loadsOther = Boolean(p.library_ref && p.lib_reference && p.lib_reference.toLowerCase() !== p.library_ref.toLowerCase())
  const pinsMismatch = p.pin_count !== null && p.expected_pins !== null && p.pin_count !== p.expected_pins
  const messages = <Messages messages={p.messages} expanded={expanded} onToggle={() => setExpanded((v) => !v)} />
  /** Zeile mit Comment, Beschreibung und Parametern (nur für gefundene Datensätze mit etwas zu zeigen) */
  const hasTexts = p.symbol_found && Boolean(p.comment || p.description || Object.keys(p.parameters ?? {}).length || p.parameter_diffs?.length)
  return (
    <tbody className="border-t border-line transition-colors hover:bg-surface-2/50">
      <tr className="align-top">
        <td className="py-2.5 pl-4 pr-1">
          <span className="flex h-5 items-center">
            {p.status === 'ok' ? <OkIcon /> : <SeverityIcon severity={p.status} />}
            <span className="sr-only">{p.status === 'ok' ? tr("in Ordnung") : p.status === 'warning' ? tr("Hinweis") : tr("Fehler")}</span>
          </span>
        </td>
        <td className="min-w-0 px-3 py-2.5">
          <button
            type="button"
            onClick={onOpen}
            className="mono block max-w-full break-all rounded-sm text-left text-xs font-semibold text-fg outline-none hover:text-accent-text hover:underline focus-ring"
            aria-label={tr("{0} in der Bauteiltabelle öffnen", { "0": String(p.part_number) })}
          >
            {p.part_number}
          </button>
          <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-2xs text-fg-subtle">
            <span aria-hidden className="size-1.5 shrink-0 rounded-full" style={{ background: cat?.color || 'var(--pf-fg-subtle)' }} />
            <span className="truncate">{cat?.label ?? p.table}</span>
          </span>
        </td>
        <td className="min-w-0 px-3 py-2.5">
          <span className={cn('flex min-w-0 items-center gap-1.5 text-xs', p.symbol_found ? 'text-fg' : 'text-danger-text')}>
            {p.symbol_found ? <OkIcon className="size-3.5" /> : <CircleX aria-hidden className="size-3.5 shrink-0" />}
            <span className="min-w-0 break-words">{symbolName}</span>
          </span>
          {!p.symbol_found && <span className="mt-0.5 block text-2xs text-danger-text">{tr("nicht gefunden")}</span>}
          {loadsOther && <span className="mt-0.5 block text-2xs text-warning-text">{tr("statt „")}{p.library_ref}“</span>}
        </td>
        <td className="mono px-3 py-2.5 text-right text-xs">
          {p.pin_count === null ? (
            <span className="text-fg-subtle">–</span>
          ) : (
            <span className={pinsMismatch ? 'text-warning-text' : 'text-fg'}>
              {formatNumber(p.pin_count)}
              {pinsMismatch && <span className="block text-2xs text-fg-muted">{tr("erwartet")}{' '}{formatNumber(p.expected_pins ?? 0)}</span>}
            </span>
          )}
        </td>
        <td className="min-w-0 px-3 py-2.5">
          {p.footprint_checks.length === 0 ? (
            <span className="text-xs text-fg-subtle">{tr("kein Footprint")}</span>
          ) : (
            <ul className="flex flex-col gap-1">
              {p.footprint_checks.map((c) => (
                <FootprintLine key={`${c.column}-${c.footprint}`} check={c} showColumn={p.footprint_checks.length > 1} />
              ))}
            </ul>
          )}
        </td>
        <td className="hidden py-2.5 pl-3 pr-4 @[60rem]:table-cell">{messages}</td>
      </tr>
      {p.messages.length > 0 && (
        <tr className="@[60rem]:hidden">
          <td aria-hidden />
          <td colSpan={4} className="px-3 pb-2.5 pt-0">
            {messages}
          </td>
        </tr>
      )}
      {hasTexts && (
        // Comment, Beschreibung und Parameter (aufklappbar) – unter Bauteil bis Footprints; die Meldungsspalte bleibt frei
        <tr>
          <td aria-hidden />
          <td colSpan={4} className="px-3 pb-3 pt-0">
            <PartTexts part={p} cat={cat} />
          </td>
          <td aria-hidden className="hidden @[60rem]:table-cell" />
        </tr>
      )}
    </tbody>
  )
}

function Messages({ messages, expanded, onToggle }: { messages: string[]; expanded: boolean; onToggle: () => void }) {
  const { t: tr } = useI18n()
  if (messages.length === 0) return <span className="text-xs text-fg-subtle">–</span>
  const visible = expanded ? messages : messages.slice(0, 1)
  return (
    <div className="text-xs leading-snug text-fg-muted">
      <ul className="flex flex-col gap-0.5">
        {visible.map((m, i) => (
          <li key={i}>{localizeMessage(m)}</li>
        ))}
      </ul>
      {messages.length > 1 && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={onToggle}
          className="mt-0.5 rounded-sm text-2xs text-fg-subtle underline decoration-dotted underline-offset-2 outline-none hover:text-fg focus-ring"
        >
          {expanded ? tr("Weniger anzeigen") : `+ ${plural(messages.length - 1, tr("weitere Meldung"), tr("weitere Meldungen"))}`}
        </button>
      )}
    </div>
  )
}

/** Footprint-Verweis mit Zustand im Text (zugeordnet, Bibliothek vorhanden, enthalten) */
function FootprintLine({ check: c, showColumn }: { check: FootprintCheck; showColumn: boolean }) {
  const { t: tr } = useI18n()
  const ok = c.assigned && c.library_found && c.in_library === true
  const unknown = c.assigned && c.library_found && c.in_library === null
  const problems = [
    !c.assigned && tr("nicht zugeordnet"),
    !c.library_found && tr("Bibliothek fehlt"),
    c.library_found && c.in_library === false && tr("nicht in der Bibliothek"),
    unknown && tr("Inhalt ungeprüft"),
  ].filter((x): x is string => Boolean(x))
  const ref = /(\d+)$/.exec(c.column)?.[1]
  return (
    <li className="grid min-w-0 grid-cols-[0.75rem_minmax(0,1fr)] items-start gap-x-1.5 text-2xs leading-4">
      <span className="flex h-4 items-center">
        {ok ? (
          <OkIcon className="size-3" />
        ) : unknown ? (
          <SeverityIcon severity="warning" className="size-3" />
        ) : (
          <CircleX aria-hidden className="size-3 shrink-0 text-danger-text" />
        )}
      </span>
      <span className="min-w-0">
        <span className={cn('mono break-all', ok ? 'text-fg' : unknown ? 'text-warning-text' : 'text-danger-text')}>{c.footprint}</span>
        {showColumn && <span className="text-fg-subtle"> ({ref ? `Ref ${ref}` : 'Ref'})</span>}
        {problems.length > 0 ? (
          <span className={cn('block', unknown ? 'text-warning-text' : 'text-danger-text')}>{problems.join(' · ')}</span>
        ) : (
          <span className="sr-only">{tr(": in Altium zugeordnet und in der Bibliothek enthalten")}</span>
        )}
      </span>
    </li>
  )
}
