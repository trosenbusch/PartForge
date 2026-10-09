import { motion, useReducedMotion } from 'motion/react'
import { CircleAlert, ExternalLink, FileScan, FileText, Globe, MoreHorizontal, RefreshCw, Search, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'
import { useDeleteDatasheet, type DatasheetSummary } from '@/api/datasheets'
import { isJobActive, type Job } from '@/api/system'
import {
  Badge,
  Card,
  CardHeader,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  IconButton,
  Input,
  ProgressRing,
  Skeleton,
  Spinner,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatBytes, formatNumber, formatRelativeTime, plural } from '@/lib/format'
import { SETTINGS_PLACE } from '@/pages/altium/settingsPlaces'
import { analysisFailed, formatUsd, hostOf, STATUS_META } from '../lib/format'
import { importPath } from '../lib/useImportActions'
import type { UrlImport } from '../store'
import { openPdf } from '../lib/openPdf'
import { PageImage } from '../shared/PageImage'
import { TipButton } from '../shared/TipButton'

export interface DatasheetListProps {
  items: DatasheetSummary[] | undefined
  loading: boolean
  /** Datenblatt-ID → laufender Analyse-Job */
  active: Record<string, Job | undefined>
  urlJobs: { entry: UrlImport; job: Job | undefined }[]
  aiReady: boolean
  /** „Neu analysieren …“ – öffnet den Dialog (Seiten, Modell, erwartete Kosten) */
  onReanalyze: (d: DatasheetSummary) => void
}

const fold = (s: string) => s.toLocaleLowerCase('de-DE').replace(/[\s\-_/]+/g, '')

/** Spalten: schmal Miniatur · Titel · (Status, Kosten, Menü) – mittel + Bestellnummern, Status, Kosten – breit + Hersteller, Datum */
const ROW_GRID =
  '@[44rem]:grid-cols-[2.5rem_minmax(0,1fr)_8.5rem_7rem_4.5rem_auto] @[60rem]:grid-cols-[2.5rem_minmax(0,1fr)_9rem_8.5rem_7rem_4.5rem_6rem_auto]'

/** „OPA656 – Wideband …“: Bauteil kräftig, Beschreibung gedämpft (gekürzt wird nur die Beschreibung). */
function TitleText({ title }: { title: string }) {
  const [base, ...rest] = title.split(' – ')
  return (
    <>
      <span className="font-semibold">{base}</span>
      {rest.length > 0 && <span className="text-fg-muted"> – {rest.join(' – ')}</span>}
    </>
  )
}

/** Status einer Zeile: laufende Analyse, fehlgeschlagen (mit Ursache) oder der gespeicherte Stand */
function StatusCell({ d, job, compact }: { d: DatasheetSummary; job: Job | undefined; compact?: boolean }) {
  const running = job ? isJobActive(job) : false
  const meta = STATUS_META[d.status]
  if (running && job) {
    return compact ? (
      <ProgressRing value={job.progress} size={20} stroke={2} tone="spark" label="Analyse läuft" />
    ) : (
      <Tooltip content={job.message || 'Analyse läuft'}>
        <span className="relative z-10 flex items-center gap-1.5 text-xs text-spark-text">
          <ProgressRing value={job.progress} size={18} stroke={2} tone="spark" label="Analyse läuft" />
          Analyse …
        </span>
      </Tooltip>
    )
  }
  if (analysisFailed(d)) {
    return (
      <TipButton tip={d.last_error} label={`Analyse fehlgeschlagen: ${d.last_error ?? ''}`} className="relative z-10">
        <Badge variant="danger">
          <CircleAlert />
          Fehlgeschlagen
        </Badge>
      </TipButton>
    )
  }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}

/** Bisherige Datenblätter: Miniatur, Titel, Hersteller, Bestellnummern, Seiten, Status, Kosten – neueste zuerst. */
export function DatasheetList({ items, loading, active, urlJobs, aiReady, onReanalyze }: DatasheetListProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const reduce = useReducedMotion()
  const remove = useDeleteDatasheet()

  const sorted = useMemo(() => {
    const list = [...(items ?? [])]
    list.sort((a, b) => (b.extracted ?? b.created ?? '').localeCompare(a.extracted ?? a.created ?? ''))
    const q = fold(query.trim())
    if (!q) return list
    return list.filter((d) =>
      [d.title ?? '', d.original_name, d.manufacturer ?? '', ...d.mpns, ...d.devices].some((t) => fold(t).includes(q)),
    )
  }, [items, query])

  const count = items?.length ?? 0

  const askDelete = async (d: DatasheetSummary) => {
    const ok = await confirm({
      title: `„${(d.has_extraction && d.title) || d.original_name}“ löschen?`,
      description:
        'Eintrag, Analyse und Seitenbilder werden entfernt. Die PDF-Datei bleibt erhalten, solange Bauteile auf sie verlinken. Angelegte Bauteile bleiben unverändert.',
      confirmLabel: 'Löschen',
      destructive: true,
      onConfirm: () => remove.mutateAsync({ id: d.id }),
    })
    if (ok) toast.success('Datenblatt gelöscht', { description: d.original_name })
  }

  return (
    <Card className="@container overflow-hidden">
      <CardHeader
        icon={<FileText />}
        title="Bisherige Datenblätter"
        description={
          count
            ? `${plural(count, 'Datenblatt', 'Datenblätter')} in dieser Bibliothek – Klick öffnet die Prüfansicht.`
            : 'Analysierte und gespeicherte Datenblätter erscheinen hier.'
        }
        actions={
          count > 3 ? (
            <Input
              size="sm"
              type="search"
              aria-label="Datenblätter durchsuchen"
              placeholder="Suchen …"
              prefix={<Search />}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              containerClassName="w-52"
            />
          ) : undefined
        }
      />

      {/* Spaltenköpfe (ab mittlerer Breite; schmal stehen Status und Kosten rechts in der Zeile) */}
      {(loading || sorted.length > 0 || urlJobs.length > 0) && (
        <div
          aria-hidden
          className={cn(
            'hidden items-center gap-4 border-y border-line bg-surface-2/40 px-4 py-1.5 text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle @[44rem]:grid',
            ROW_GRID,
          )}
        >
          <span />
          <span>Datenblatt</span>
          <span className="hidden @[60rem]:block">Hersteller</span>
          <span>Bestellnummern</span>
          <span>Status</span>
          <span className="text-right">Kosten</span>
          <span className="hidden text-right @[60rem]:block">Datum</span>
          <span className="w-7" />
        </div>
      )}

      {loading ? (
        <ul aria-label="Datenblätter werden geladen" className="divide-y divide-line">
          {[0, 1, 2].map((i) => (
            <li key={i} className="flex items-center gap-4 px-4 py-3">
              <Skeleton className="h-[3.25rem] w-10 rounded-md" />
              <div className="flex-1 space-y-2">
                <Skeleton className="h-3.5 w-1/3" />
                <Skeleton className="h-3 w-1/5" />
              </div>
            </li>
          ))}
        </ul>
      ) : sorted.length === 0 && urlJobs.length === 0 ? (
        query ? (
          <EmptyState illustration="search-empty" size="sm" title="Keine Treffer" description={`Nichts gefunden für „${query}“.`} />
        ) : (
          <EmptyState
            illustration="drop-pdf"
            size="sm"
            title="Noch keine Datenblätter"
            description={
              aiReady
                ? 'PDF oben ablegen oder eine Web-Adresse eingeben – in etwa einer halben Minute steht der Bauteil-Vorschlag bereit.'
                : `Abgelegte PDFs erscheinen hier. Analysiert werden sie, sobald die KI eingerichtet ist (${SETTINGS_PLACE.ai.label}).`
            }
          />
        )
      ) : (
        <ul aria-label="Datenblätter" className="divide-y divide-line">
          {urlJobs.map(({ entry, job }) => (
            <li key={entry.jobId} className="relative flex items-center gap-4 px-4 py-3">
              <span aria-hidden className="flex h-[3.25rem] w-10 shrink-0 items-center justify-center rounded-md border border-dashed border-line-strong text-fg-subtle">
                <Globe className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <Link
                  to={`/import?job=${encodeURIComponent(entry.jobId)}`}
                  className="block truncate text-ui font-medium text-fg outline-none after:absolute after:inset-0 hover:underline focus-ring-inset"
                >
                  {entry.url}
                </Link>
                <div className="mt-0.5 flex items-center gap-1.5 text-2xs text-fg-subtle">
                  <Spinner size={11} tone="spark" />
                  {job?.message || 'Wird heruntergeladen …'}
                </div>
              </div>
              {job && <ProgressRing value={job.progress} size={28} stroke={2.5} tone="spark" label="Fortschritt" />}
            </li>
          ))}
          {sorted.map((d, i) => {
            const job = active[d.id]
            const running = job ? isJobActive(job) : false
            const host = hostOf(d.source_url)
            const errors = d.issues.error ?? 0
            const warnings = d.issues.warning ?? 0
            const title = (d.has_extraction && d.title) || d.original_name
            const when = d.extracted || d.created ? formatRelativeTime((d.extracted ?? d.created) as string) : null
            const cost = d.cost_usd > 0 ? formatUsd(d.cost_usd) : '–'
            return (
              <motion.li
                key={d.id}
                initial={reduce ? false : { opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2, delay: Math.min(i, 20) * 0.02 }}
                className={cn(
                  'group/row relative grid grid-cols-[2.5rem_minmax(0,1fr)_auto] items-center gap-4 px-4 py-2.5 transition-colors hover:bg-surface-2/60',
                  ROW_GRID,
                )}
              >
                <PageImage datasheetId={d.id} page={1} dpi={36} alt="" className="w-10 rounded-sm border border-line shadow-card" />
                <div className="min-w-0">
                  <Link
                    to={importPath(d.id, running ? job?.id : null)}
                    className="block truncate text-ui text-fg outline-none after:absolute after:inset-0 after:rounded-none focus-ring-inset"
                  >
                    <TitleText title={title} />
                  </Link>
                  {/* Meta-Zeile: Datei und Seiten immer; breit Größe und Quelle, sonst Hersteller und Datum (eigene Spalten fehlen) */}
                  <div className="mt-0.5 flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap text-2xs text-fg-subtle">
                    <span className="min-w-[3.5rem] shrink truncate">{d.original_name}</span>
                    <span aria-hidden>·</span>
                    <span className="shrink-0 tabular-nums">{plural(d.page_count, 'Seite', 'Seiten')}</span>
                    {d.size_bytes > 0 && (
                      <span className="hidden shrink-0 items-center gap-1.5 @[60rem]:flex">
                        <span aria-hidden>·</span>
                        {formatBytes(d.size_bytes)}
                      </span>
                    )}
                    {host && (
                      <span className="hidden shrink-0 items-center gap-1.5 @[60rem]:flex">
                        <span aria-hidden>·</span>
                        <Globe aria-hidden className="size-3" />
                        {host}
                      </span>
                    )}
                    {d.manufacturer && (
                      <span className="flex min-w-0 shrink-[2] items-center gap-1.5 @[60rem]:hidden">
                        <span aria-hidden>·</span>
                        <span className="truncate">{d.manufacturer}</span>
                      </span>
                    )}
                    {when && (
                      <span className="flex shrink-0 items-center gap-1.5 @[60rem]:hidden">
                        <span aria-hidden>·</span>
                        {when}
                      </span>
                    )}
                  </div>
                </div>
                <div className="hidden min-w-0 truncate text-xs text-fg-muted @[60rem]:block">{d.manufacturer || '–'}</div>
                <div className="hidden min-w-0 items-center gap-1 @[44rem]:flex">
                  {d.mpns.length ? (
                    <>
                      <span className="mono truncate rounded-md bg-surface-3/70 px-1.5 py-0.5 text-2xs text-fg">{d.mpns[0]}</span>
                      {d.mpns.length > 1 && (
                        <TipButton
                          tip={d.mpns.slice(1, 16).join(', ') + (d.mpns.length > 16 ? ' …' : '')}
                          label={`${formatNumber(d.mpns.length - 1)} weitere Bestellnummern`}
                          className="relative z-10 rounded-md px-1 text-2xs tabular-nums text-fg-subtle"
                        >
                          +{formatNumber(d.mpns.length - 1)}
                        </TipButton>
                      )}
                    </>
                  ) : (
                    <span className="text-xs text-fg-subtle">–</span>
                  )}
                </div>
                <div className="hidden min-w-0 items-center gap-1.5 @[44rem]:flex">
                  <StatusCell d={d} job={job} />
                  {!running && (errors > 0 || warnings > 0) && (
                    <TipButton
                      tip={`${errors} Fehler, ${warnings} Warnungen der Prüfung`}
                      label={`${errors} Fehler, ${warnings} Warnungen`}
                      className="relative z-10 p-1"
                    >
                      <span aria-hidden className={cn('size-1.5 rounded-full', errors ? 'bg-danger' : 'bg-warning')} />
                    </TipButton>
                  )}
                </div>
                <div className="mono hidden text-right text-xs text-fg @[44rem]:block">{cost}</div>
                <div className="hidden text-right text-xs text-fg-subtle @[60rem]:block">{when ?? '–'}</div>
                <div className="relative z-10 flex items-center justify-end gap-2.5">
                  {/* schmal: Status und Kosten hier (Kosten immer sichtbar) */}
                  <span className="flex items-center gap-2.5 @[44rem]:hidden">
                    <StatusCell d={d} job={job} compact />
                    <span className="mono w-14 text-right text-xs text-fg">{cost}</span>
                  </span>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <IconButton size="sm" label={`Aktionen für „${title}“`} icon={<MoreHorizontal />} tooltip={false} />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="min-w-52">
                      <DropdownMenuItem icon={<FileScan />} onSelect={() => navigate(importPath(d.id, running ? job?.id : null))}>
                        Prüfansicht öffnen
                      </DropdownMenuItem>
                      <DropdownMenuItem icon={<ExternalLink />} onSelect={() => void openPdf(d)}>
                        PDF öffnen
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        icon={<RefreshCw />}
                        disabled={!aiReady || running}
                        onSelect={() => onReanalyze(d)}
                        description={d.cost_usd > 0 ? `Bisher ${formatUsd(d.cost_usd)} für dieses Datenblatt` : 'Seiten, Modell und erwartete Kosten wählen'}
                      >
                        {d.has_extraction ? 'Neu analysieren …' : 'Analysieren …'}
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem icon={<Trash2 />} destructive disabled={running} onSelect={() => void askDelete(d)}>
                        Löschen …
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </motion.li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
