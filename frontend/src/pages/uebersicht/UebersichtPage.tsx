import { useI18n, localizeMessage } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { motion } from 'motion/react'
import {
  ArchiveRestore,
  ArrowRight,
  Boxes,
  Check,
  CircuitBoard,
  FileDown,
  FileScan,
  FolderInput,
  FolderSearch,
  FolderSync,
  History,
  KeyRound,
  Layers,
  ListTree,
  Microchip,
  Pencil,
  PencilLine,
  PlugZap,
  Plus,
  RefreshCw,
  Replace,
  RotateCw,
  RulerDimensionLine,
  Shapes,
  ShieldCheck,
  Trash2,
  TriangleAlert,
  Wrench,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Fragment, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { useAltiumStatus, type AltiumStatus } from '@/api/altium'
import { useLibraryStats, type AuditEntry, type LibraryStats } from '@/api/library'
import {
  findingMessage,
  libraryFindings,
  partHealth,
  useHealthReport,
  useLibraryFiles,
  type FixKind,
  type HealthGroup,
  type LibraryFile,
  type MergedHealth,
} from '@/api/libraries'
import { useSettings, useWorkspace } from '@/api/system'
import { runCommand } from '@/app/commands'
import { PageBody } from '@/app/page'
import { usePageHeading } from '@/app/topbar'
import { Button, Card, CardContent, CardHeader, EmptyState, Kbd, ProgressRing, Skeleton, Spinner, StatCard } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatNumber, formatPercent, formatRelativeTime, greeting, plural } from '@/lib/format'
import { useCountUp } from '@/lib/useCountUp'
import {
  altiumBlocker,
  buildModel,
  lastRefreshText,
  summarizeFiles,
  writerLabel,
  type ActionKey,
  type FilesSummary,
  type PageModel,
} from '@/pages/altium/model'
import { partPath } from '@/pages/altium/paths'
import { SETTINGS_PLACE } from '@/pages/altium/settingsPlaces'
import { ACTION_META, LEVEL_TEXT } from '@/pages/altium/tokens'
import { HeadlineLink, LevelDot, SeverityIcon } from '@/pages/altium/ui'
import { useAltiumActions, type AltiumActions } from '@/pages/altium/useAltiumActions'
import { restoreParts } from '@/pages/bauteile/model/actions'

/** Stagger 20 ms (Brief §6: 15–25 ms für die ersten Elemente) */
const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.02, delayChildren: 0.02 } },
}
const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3, ease: [0.16, 1, 0.3, 1] as const } },
}

export default function UebersichtPage() {
  const { t: tr } = useI18n()
  usePageHeading() // die Begrüßung ist die <h1> dieser Seite
  const navigate = useNavigate()
  const workspace = useWorkspace().data
  const settings = useSettings().data
  const statsQuery = useLibraryStats()
  const stats = statsQuery.data
  const unavailable = statsQuery.isError
  const health = useHealthReport()
  const status = useAltiumStatus()
  const files = useLibraryFiles()
  const actions = useAltiumActions()
  const author = settings?.settings.author
  const run = (id: string) => runCommand(id, { navigate, close: () => {} })
  const isEmpty = stats ? stats.total_parts === 0 : false
  const statusError = status.isError && !status.data ? status.error.message : null
  const blocker = altiumBlocker(status.data, statusError)
  const lib = libraryFindings(health.report)
  const model =
    status.data || statusError
      ? buildModel({
          status: status.data,
          statusError,
          files: files.data,
          filesError: files.error?.message ?? null,
          backend: settings?.settings.altium.library_backend,
          // Bauteile und Befunde zeigen Kennzahlen und Gesundheitskarte – die Altium-Karte bleibt bei Altium, DbLib
          // und Dateien (keine Schlagzeile „Prüfbericht“ bzw. „Erste Schritte“ hier)
          partCount: undefined,
          dbKind: workspace?.db_kind,
          dbFile: workspace?.settings.db.sqlite_file,
          findings: null,
          reportErrors: 0,
          linkErrors: lib?.linkErrors ?? 0,
          heights: lib ? { total: lib.heights, repairable: lib.heightsRepairable } : undefined,
        })
      : null
  /** Bibliotheksdateien laut Dateiliste – fehlen sie, ist die Bibliothek für Altium nicht in Ordnung (Prüfbericht übergeht Ausstehendes) */
  const libraryFiles = model?.files ?? summarizeFiles(files.data)
  /** Writer-Status bekannt und kein Bibliotheks-Writer bereit */
  const writerMissing = Boolean(status.data) && !writerLabel(status.data, settings?.settings.altium.library_backend).ok

  return (
    // unten Platz für die Pille des Job-Docks, solange sie zu sehen ist
    <PageBody className="pb-[max(3rem,var(--pf-dock-reserve))]">
      <motion.div variants={stagger} initial="hidden" animate="show" className="flex flex-col gap-4">
        {/* Kopf: kompakt – bei 720 px Höhe bleiben Kennzahlen sichtbar */}
        <motion.section variants={item} aria-labelledby="dash-greeting">
          <div className="relative overflow-hidden rounded-panel border border-line bg-surface shadow-card">
            <div
              aria-hidden
              className="dot-grid absolute inset-0 opacity-50 [mask-image:linear-gradient(90deg,transparent_35%,black_80%)]"
            />
            <div
              aria-hidden
              className="absolute -right-28 -top-44 size-[440px] rounded-full bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]"
            />
            <div className="relative flex flex-col gap-4 px-6 py-5 @[52rem]:flex-row @[52rem]:items-center @[52rem]:gap-8">
              <div className="min-w-0 flex-1">
                <h1 id="dash-greeting" className="text-h2 font-semibold tracking-[-0.03em] text-fg">
                  {greeting()}
                  {author ? `, ${author}` : ''}
                  <span className="text-gradient-forge">.</span>
                </h1>
                <p className="mt-1 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5 text-ui text-fg-muted">
                  <span className="flex items-center gap-1.5">
                    <span aria-hidden className="size-1.5 rounded-full bg-success shadow-[0_0_8px_var(--pf-success)]" />
                    <span className="font-medium text-fg">{workspace?.name ?? tr("Bibliothek")}</span>
                  </span>
                  {workspace && (
                    <>
                      <span aria-hidden className="text-fg-subtle">
                        ·
                      </span>
                      <span title={workspace.root}>
                        {workspace.db_kind === 'postgres' ? 'PostgreSQL' : 'SQLite'} · {baseName(workspace.root)}
                      </span>
                    </>
                  )}
                  {stats && stats.total_parts > 0 && (
                    <>
                      <span aria-hidden className="text-fg-subtle">
                        ·
                      </span>
                      <span>
                        {plural(stats.total_parts, tr("Bauteil"), tr("Bauteile"))} in{' '}
                        {plural(stats.categories.filter((c) => c.count > 0).length, tr("Kategorie"), tr("Kategorien"))}
                      </span>
                    </>
                  )}
                </p>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-2.5" role="group" aria-label={tr("Schnellaktionen")}>
                <Button size="lg" variant="primary" leftIcon={<Layers />} onClick={() => run('series.new')}>
                  {tr("Serie erzeugen")}</Button>
                <Button size="lg" variant="spark" leftIcon={<FileScan />} onClick={() => run('import.datasheet')}>
                  {tr("Datenblatt importieren")}</Button>
              </div>
            </div>
          </div>
        </motion.section>

        {/* Kennzahlen */}
        <motion.section
          variants={item}
          aria-label={tr("Kennzahlen")}
          className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-4"
        >
          <KpiRow
            stats={stats}
            unavailable={unavailable}
            files={files.data}
            libraryFiles={libraryFiles}
            report={health.report}
            healthFailed={Boolean(health.error)}
            onNavigate={navigate}
          />
        </motion.section>

        {/* Verteilung / Erste Schritte + Gesundheit */}
        <div className="grid grid-cols-1 gap-4 @[46rem]:grid-cols-2 @[68rem]:grid-cols-12">
          <motion.div variants={item} className="min-w-0 @[68rem]:col-span-8">
            {isEmpty ? (
              <FirstSteps onRun={run} onNavigate={navigate} status={status.data} actions={actions} />
            ) : (
              <DistributionCard stats={stats} unavailable={unavailable} onNavigate={navigate} />
            )}
          </motion.div>
          <motion.div variants={item} className="min-w-0 @[68rem]:col-span-4">
            <HealthCard
              report={health.report}
              loading={health.isLoading}
              failed={Boolean(health.error)}
              updatedAt={health.updatedAt}
              totalParts={stats?.total_parts}
              files={libraryFiles}
              writerMissing={writerMissing}
              actions={actions}
            />
          </motion.div>
        </div>

        {/* Letzte Änderungen + Altium / Schnellaktionen */}
        <div className="grid grid-cols-1 gap-4 @[46rem]:grid-cols-2 @[68rem]:grid-cols-12">
          <motion.div variants={item} className="min-w-0 @[68rem]:col-span-7">
            <RecentChanges stats={stats} unavailable={unavailable} />
          </motion.div>
          <motion.div variants={item} className="flex min-w-0 flex-col gap-4 @[68rem]:col-span-5">
            <AltiumCard model={model} status={status.data} failed={Boolean(statusError)} actions={actions} onNavigate={navigate} />
            <QuickActions
              onRun={run}
              onNavigate={navigate}
              installed={model?.altium.installed ?? null}
              actions={actions}
              blocker={blocker}
              notRunning={Boolean(status.data?.altium_exe && !status.data.altium_running)}
            />
          </motion.div>
        </div>
      </motion.div>
    </PageBody>
  )
}

// --------------------------------------------------------------------------- Kennzahlen

/** Einträge einer Art, die registriert sind, aber nicht in ihrer Datei stehen (Dateiliste) */
function absentIn(files: LibraryFile[] | undefined, kind: 'schlib' | 'pcblib'): number | undefined {
  if (!files) return undefined
  return files.filter((f) => f.kind === kind).reduce((n, f) => n + f.missing.length, 0)
}

/** Fehler der Bibliotheksdateien, die der Prüfbericht nicht zählt: fehlende Dateien und gescheitertes Schreiben */
function fileErrorCount(files: FilesSummary | null | undefined): number {
  return files ? files.missingFiles + files.errors : 0
}

function KpiRow({
  stats,
  unavailable,
  files,
  libraryFiles,
  report,
  healthFailed,
  onNavigate,
}: {
  stats: LibraryStats | undefined
  unavailable: boolean
  files: LibraryFile[] | undefined
  libraryFiles: FilesSummary | null
  report: MergedHealth | undefined
  healthFailed: boolean
  onNavigate: (to: string) => void
}) {
  const { t: tr } = useI18n()
  const v = (n: number | undefined) => (unavailable ? null : n)
  const lastChange = stats?.recent_parts[0]?.modified
  const pendingSymbols = (stats?.symbols.by_status.pending ?? 0) + (stats?.symbols.by_status.error ?? 0)
  const pendingFootprints = (stats?.footprints.by_status.pending ?? 0) + (stats?.footprints.by_status.error ?? 0)
  // „In Dateien“ erst sagen, wenn die Dateien es bestätigen (Registrierung allein reicht nicht)
  const absentSymbols = Math.max(absentIn(files, 'schlib') ?? 0, stats?.symbols.by_status.missing ?? 0)
  const absentFootprints = Math.max(absentIn(files, 'pcblib') ?? 0, stats?.footprints.by_status.missing ?? 0)
  const syncHint = (total: number, pending: number, absent: number) =>
    total === 0
      ? tr("noch keine")
      : pending
        ? tr("{0} ausstehend", { "0": String(formatNumber(pending)) })
        : absent
          ? plural(absent, tr("fehlt in Datei"), tr("fehlen in Dateien"))
          : files
            ? tr("alle in Dateien")
            : tr("registriert")
  const filled = stats?.categories.filter((c) => c.count > 0).length ?? 0
  // fehlende/nicht geschriebene Bibliotheksdateien sind Fehler – auch wenn der Prüfbericht (der Ausstehendes übergeht) nichts meldet
  const fileErrors = fileErrorCount(libraryFiles)
  const errors = (report?.counts.error ?? 0) + fileErrors
  const warnings = report?.counts.warning ?? 0
  // ohne Bauteile und ohne Befunde gibt es nichts zu prüfen → „–“ statt einer beruhigenden 0
  const nothingToCheck = Boolean(report && stats && stats.total_parts === 0 && errors + warnings === 0)
  const problems = nothingToCheck ? null : report ? errors + warnings : healthFailed ? null : undefined
  const problemHint = nothingToCheck
    ? tr("noch nichts zu prüfen")
    : !report
      ? healthFailed
        ? tr("Prüfung nicht verfügbar")
        : undefined
      : fileErrors && libraryFiles?.missingFiles
        ? plural(libraryFiles.missingFiles, tr("Bibliotheksdatei fehlt"), tr("Bibliotheksdateien fehlen"))
        : errors
        ? warnings
          ? tr("davon {0}", { "0": String(plural(errors, tr("Fehler"), tr("Fehler"))) })
          : tr("Fehler")
        : warnings
          ? warnings === 1
            ? tr("Warnung")
            : tr("Warnungen")
          : report.counts.info
            ? tr("nur {0}", { "0": String(plural(report.counts.info, tr("Hinweis"), tr("Hinweise"))) })
            : tr("alles in Ordnung")

  return (
    <>
      <StatCard
        label={tr("Bauteile")}
        value={v(stats?.total_parts)}
        icon={<Microchip />}
        hint={unavailable ? tr("nicht verfügbar") : !stats ? undefined : lastChange ? tr("zuletzt {0}", { "0": String(formatRelativeTime(lastChange)) }) : tr("noch keine")}
        onClick={() => onNavigate('/bauteile')}
        actionLabel={tr("Zur Bauteiltabelle")}
      />
      <StatCard
        label={tr("Kategorien")}
        value={v(stats?.category_count)}
        icon={<Boxes />}
        hint={stats ? tr("{0} mit Bauteilen", { "0": String(formatNumber(filled)) }) : undefined}
        onClick={() => onNavigate('/einstellungen/kategorien')}
        actionLabel={tr("Kategorien und Felder bearbeiten")}
      />
      <StatCard
        label={tr("Symbole")}
        value={v(stats?.symbols.total)}
        icon={<Shapes />}
        hint={stats ? syncHint(stats.symbols.total, pendingSymbols, absentSymbols) : undefined}
        tone={pendingSymbols || absentSymbols ? 'warning' : 'neutral'}
        onClick={() => onNavigate('/symbole')}
        actionLabel={tr("Zu den Symbolen")}
      />
      <StatCard
        label="Footprints"
        value={v(stats?.footprints.total)}
        icon={<CircuitBoard />}
        hint={stats ? syncHint(stats.footprints.total, pendingFootprints, absentFootprints) : undefined}
        tone={pendingFootprints || absentFootprints ? 'warning' : 'neutral'}
        onClick={() => onNavigate('/footprints')}
        actionLabel={tr("Zu den Footprints")}
      />
      <StatCard
        label={tr("Probleme")}
        value={problems}
        icon={problems ? <TriangleAlert /> : <ShieldCheck />}
        tone={errors ? 'danger' : warnings ? 'warning' : report && !nothingToCheck ? 'success' : 'neutral'}
        hint={problemHint}
        onClick={() => onNavigate(fileErrors && !report?.counts.error ? '/altium?bereich=dateien' : '/altium?bereich=pruefbericht')}
        actionLabel={fileErrors && !report?.counts.error ? tr("Bibliotheksdateien ansehen") : tr("Prüfbericht öffnen")}
      />
    </>
  )
}

// --------------------------------------------------------------------------- Verteilung

function DistributionCard({
  stats,
  unavailable,
  onNavigate,
}: {
  stats: LibraryStats | undefined
  unavailable: boolean
  onNavigate: (to: string) => void
}) {
  const { t: tr } = useI18n()
  const rows = (stats?.categories ?? []).filter((c) => c.count > 0).sort((a, b) => b.count - a.count)
  const shown = rows.slice(0, 7)
  const max = Math.max(1, ...shown.map((r) => r.count))
  const total = stats?.total_parts ?? 0
  const empty = (stats?.categories.length ?? 0) - rows.length
  const hidden = rows.length - shown.length

  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        icon={<Boxes />}
        title={tr("Bauteile je Kategorie")}
        description={
          stats
            ? tr("{0} in {1} von {2} Kategorien", { "0": String(plural(total, tr("Bauteil"), tr("Bauteile"))), "1": String(formatNumber(rows.length)), "2": String(formatNumber(stats.categories.length)) })
            : tr("Wie sich Ihre Bauteile verteilen")
        }
        actions={
          <Button size="sm" variant="ghost" rightIcon={<ArrowRight />} onClick={() => onNavigate('/bauteile')}>
            {tr("Alle Bauteile")}</Button>
        }
      />
      <CardContent className="flex flex-1 flex-col">
        {!stats && !unavailable && (
          <div className="flex flex-col gap-3 py-1">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-6" style={{ width: `${92 - i * 12}%` }} />
            ))}
          </div>
        )}
        {unavailable && (
          <EmptyState size="sm" illustration="offline" title={tr("Kennzahlen nicht verfügbar")} description={tr("Die Datenbank antwortet gerade nicht.")} />
        )}
        {stats && (
          <ul className="-mx-2 flex flex-col">
            {shown.map((c) => (
              <li key={c.table}>
                <button
                  type="button"
                  onClick={() => onNavigate(`/bauteile/${encodeURIComponent(c.table)}`)}
                  className="group/row grid w-full grid-cols-[minmax(7rem,11rem)_minmax(0,1fr)_3.5rem] items-center gap-3 rounded-control px-2 py-1.5 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset"
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ background: c.color ?? 'var(--pf-fg-subtle)' }} />
                    <span className="truncate text-ui text-fg">{c.label}</span>
                  </span>
                  <span aria-hidden className="relative h-2 overflow-hidden rounded-full bg-surface-3">
                    <motion.span
                      className="absolute inset-y-0 left-0 rounded-full"
                      style={{ background: c.color ?? 'var(--pf-fg-subtle)' }}
                      initial={{ width: 0 }}
                      animate={{ width: `${(c.count / max) * 100}%` }}
                      transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
                    />
                  </span>
                  <span className="mono text-right text-ui text-fg">
                    <CountNumber value={c.count} />
                    <span className="sr-only"> {tr(" Bauteile, ")}{shareText(c.count, total)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {stats && (hidden > 0 || empty > 0) && (
          <p className="mt-auto pt-3 text-xs text-fg-subtle">
            {hidden > 0 && `+ ${plural(hidden, tr("weitere Kategorie"), tr("weitere Kategorien"))}`}
            {hidden > 0 && empty > 0 && ' · '}
            {empty > 0 && tr("{0} noch leer", { "0": String(plural(empty, tr("Kategorie"), tr("Kategorien"))) })}
          </p>
        )}
      </CardContent>
    </Card>
  )
}

function CountNumber({ value }: { value: number }) {
  useI18n()
  return <>{formatNumber(Math.round(useCountUp(value)))}</>
}

/** Anteil für Screenreader: nie „0 %“ für vorhandene Bauteile bzw. „100 %“ für einen Teil („< 1 %“, „> 99 %“) */
function shareText(count: number, total: number): string {
  const f = count / Math.max(1, total)
  if (count > 0 && f < 0.005) return '< 1 %'
  if (count < total && f > 0.995) return '> 99 %'
  return formatPercent(f)
}

// --------------------------------------------------------------------------- Erste Schritte (leere Bibliothek)

function FirstSteps({
  onRun,
  onNavigate,
  status,
  actions,
}: {
  onRun: (id: string) => void
  onNavigate: (to: string) => void
  status: AltiumStatus | undefined
  actions: AltiumActions
}) {
  const { t: tr } = useI18n()
  const settings = useSettings().data
  const workspace = useWorkspace().data
  const keyOk = Boolean(settings?.ai_key_configured)
  const altiumOk = Boolean(status?.altium_exe ?? settings?.altium_exe) || Boolean(status?.backends.some((b) => b.name === 'rust' && b.available))
  const installed = status?.dblib?.installed_in_altium === true
  const running = Boolean(status?.altium_running)

  const steps: {
    id: string
    title: string
    text: string
    done: boolean
    optional?: boolean
    action?: ReactNode
  }[] = [
    { id: 'lib', title: tr("Bibliothek angelegt"), text: workspace?.name ?? tr("Bibliotheksordner bereit"), done: true },
    {
      id: 'key',
      title: tr("Claude-API-Schlüssel hinterlegt"),
      text: keyOk ? tr("Datenblatt-Import per KI ist bereit.") : tr("Optional – nur für den Datenblatt-Import nötig."),
      done: keyOk,
      optional: true,
      action: (
        <Button size="sm" variant="ghost" leftIcon={<KeyRound />} onClick={() => onNavigate(SETTINGS_PLACE.ai.to)}>
          {tr("Einrichten")}</Button>
      ),
    },
    {
      id: 'altium',
      title: tr("Altium Designer gefunden"),
      text: altiumOk
        ? tr("Symbol- und Footprint-Bibliotheken können erzeugt werden.")
        : tr("Bibliotheks-Writer oder Pfad zu X2.EXE unter {0} festlegen.", { "0": String(SETTINGS_PLACE.altium.label) }),
      done: altiumOk,
      optional: true,
      action: (
        <Button size="sm" variant="ghost" onClick={() => onNavigate(SETTINGS_PLACE.altium.to)}>
          {tr("Pfad festlegen")}</Button>
      ),
    },
    {
      id: 'series',
      title: tr("Erste Bauteile anlegen"),
      text: tr("Eine komplette Widerstandsserie mit dem Serien-Assistenten – oder ein Datenblatt importieren."),
      done: false,
      action: (
        <Button size="sm" variant="secondary" leftIcon={<Layers />} onClick={() => onRun('series.new')}>
          {tr("Serie erzeugen")}</Button>
      ),
    },
    {
      id: 'install',
      title: tr("DbLib in Altium einbinden"),
      text: installed
        ? tr("Die DbLib ist in Altium installiert.")
        : running
          ? tr("Danach stehen alle Bauteile in Altium im Components-Panel bereit.")
          : tr("Sobald Altium Designer läuft, lässt sich die DbLib hier mit einem Klick installieren."),
      done: installed,
      action: running ? (
        <Button size="sm" variant="ghost" leftIcon={<PlugZap />} loading={actions.pending.install} onClick={() => actions.run('install')}>
          {tr("In Altium installieren")}</Button>
      ) : undefined,
    },
  ]
  const current = steps.findIndex((s) => !s.done && !s.optional)
  const doneCount = steps.filter((s) => s.done).length

  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        icon={<ListTree />}
        title={tr("Erste Schritte")}
        description={tr("In wenigen Minuten zur ersten Altium-Bibliothek")}
        actions={
          <span className="mono text-xs text-fg-subtle">
            {doneCount}/{steps.length}
          </span>
        }
      />
      <CardContent className="flex-1">
        <ol className="flex flex-col">
          {steps.map((s, i) => {
            const isCurrent = i === current
            return (
              <li
                key={s.id}
                className={cn('relative flex items-start gap-3 rounded-button px-2 py-2.5', isCurrent && 'bg-surface-2/70')}
              >
                {i < steps.length - 1 && (
                  <span aria-hidden className="absolute left-[19px] top-9 h-[calc(100%-1.75rem)] w-px bg-line-strong" />
                )}
                <span
                  aria-hidden
                  className={cn(
                    'relative flex size-6 shrink-0 items-center justify-center rounded-full border text-2xs font-semibold',
                    s.done
                      ? 'border-success/30 bg-success/10 text-success-text'
                      : isCurrent
                        ? 'border-transparent bg-gradient-forge text-on-accent'
                        : 'border-line-strong bg-surface text-fg-subtle',
                  )}
                >
                  {s.done ? <Check className="size-3.5" strokeWidth={2.25} /> : i + 1}
                </span>
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className={cn('text-ui font-medium', s.done ? 'text-fg-muted' : 'text-fg')}>
                    {s.title}
                    <span className="sr-only">{s.done ? tr(" – erledigt") : isCurrent ? tr(" – nächster Schritt") : ''}</span>
                  </div>
                  <p className="mt-0.5 text-xs leading-snug text-fg-subtle">{s.text}</p>
                </div>
                {!s.done && s.action && <div className="shrink-0 self-center">{s.action}</div>}
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- Bibliotheksgesundheit

/** Behebung je Prüfung auf der Übersicht (ohne Eintrag: bei genau einem Bauteil „Bauteil öffnen“) */
const DASH_FIX: Partial<Record<FixKind, { label: string; icon: LucideIcon; action?: ActionKey }>> = {
  regenerate: { get label() { return tr("DbLib neu erzeugen") }, icon: RefreshCw, action: 'regenerate' },
  sync: { get label() { return tr("Synchronisieren") }, icon: FolderSync, action: 'sync' },
  scan: { get label() { return tr("Dateien prüfen") }, icon: FolderSearch, action: 'scan' },
  'scan-sync': { get label() { return tr("Prüfen und synchronisieren") }, icon: FolderSync, action: 'scanSync' },
  'scan-register': { get label() { return tr("Aus Dateien übernehmen") }, icon: FolderInput, action: 'scan' },
  'repair-heights': { get label() { return tr("Footprint-Höhen nachtragen") }, icon: RulerDimensionLine, action: 'repairHeights' },
  'install-replace': { get label() { return tr("Ersetzen und installieren") }, icon: Replace, action: 'installReplace' },
  normalize: { get label() { return tr("Vereinheitlichen") }, icon: Wrench, action: 'normalize' },
  'open-part': { get label() { return tr("Bauteil öffnen") }, icon: PencilLine },
}

/** Einziges betroffenes Bauteil einer Gruppe (sonst `null`) */
function singlePart(group: HealthGroup) {
  const parts = new Set(group.items.filter((i) => i.part_number).map((i) => `${i.table}|${i.part_number}`))
  return parts.size === 1 ? (group.items.find((i) => i.table && i.part_number) ?? null) : null
}

/** Wovon ein einzelner Befund handelt: Teilenummer bzw. Symbol/Footprint/Datei und die Meldung */
function singleLine(group: HealthGroup): string | null {
  if (group.total !== 1 || group.items.length !== 1) return null
  const item = group.items[0]
  const message = localizeMessage(findingMessage(item, group))
  const subject = item.part_number ?? (item.subject && !message.includes(item.subject) ? item.subject : null)
  return subject ? `${subject} – ${message}` : message
}

/** Ring der Gesundheitskarte in ganzen Prozent: abgerundet und nie 100 %, solange Fehler oder Warnungen offen sind */
function healthPercent(score: number, open: boolean): number {
  const pct = Math.floor(score * 100 + 1e-9)
  return open && pct >= 100 ? 99 : pct
}

function HealthCard({
  report,
  loading,
  failed,
  updatedAt,
  totalParts,
  files,
  writerMissing,
  actions,
}: {
  report: MergedHealth | undefined
  loading: boolean
  failed: boolean
  updatedAt: number | null
  totalParts: number | undefined
  /** Bibliotheksdateien laut Dateiliste (fehlende Dateien und Ausstehendes übergeht der Prüfbericht) */
  files: FilesSummary | null
  /** kein Bibliotheks-Writer bereit – „Synchronisieren“ hilft dann nicht */
  writerMissing: boolean
  actions: AltiumActions
}) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const hasParts = (totalParts ?? 0) > 0
  // Bibliotheksdateien fehlen bzw. scheitern (Fehler) oder Einträge warten noch auf das Schreiben (Warnung): Altium
  // findet Symbole und Footprints dann nicht – der Prüfbericht zählt das nicht, die Karte muss es trotzdem sagen
  const fileErrors = fileErrorCount(files)
  const filePending = files?.pending ?? 0
  const fileProblem: 'error' | 'warning' | null = fileErrors ? 'error' : filePending ? 'warning' : null
  // exakt: jedes betroffene Bauteil genau einmal (Dateibefunde nennen alle Bauteile, die Symbol/Footprint/Datei verwenden)
  const scored = report && hasParts && totalParts ? partHealth(report, totalParts) : null
  const counts = report?.counts
  const open = Boolean(counts?.error || counts?.warning || fileProblem)
  const percent = scored ? healthPercent(scored.score, open) : 0
  const shownScore = Math.min(percent, Math.floor(useCountUp(percent)))
  /** fehlende Dateien: kein Prozentwert (er beschriebe nur die Daten) – der Ring zeigt „!“ */
  const blocked = fileProblem === 'error' && hasParts
  const baseTone = !report ? 'neutral' : scored ? scored.tone : counts?.error ? 'danger' : counts?.warning ? 'warning' : 'success'
  const tone = fileProblem === 'error' ? 'danger' : fileProblem === 'warning' && baseTone === 'success' ? 'warning' : baseTone
  // Befunde ohne betroffenes Bauteil (z. B. unbenutzter Footprint) nur erwähnen, wenn der Ring sonst milder wirkt als die Zähler
  const unrelated = !report || !scored
    ? 0
    : scored.tone === 'success'
      ? report.unrelated.errors + report.unrelated.warnings
      : scored.tone === 'warning'
        ? report.unrelated.errors
        : 0
  const top = report ? report.groups.filter((g) => g.severity !== 'info').slice(0, fileProblem ? 2 : 3) : []
  const infoOnly = Boolean(report && top.length === 0 && counts?.info && !fileProblem)

  const fileVerdict = !files
    ? null
    : files.missingFiles
      ? plural(files.missingFiles, tr("Bibliotheksdatei fehlt"), tr("Bibliotheksdateien fehlen"))
      : files.errors
        ? tr("{0} nicht geschrieben", { "0": String(plural(files.errors, tr("Eintrag"), tr("Einträge"))) })
        : filePending
          ? tr("{0} auf das Schreiben", { "0": String(plural(filePending, tr("Eintrag wartet"), tr("Einträge warten"))) })
          : null
  const verdict = !report
    ? failed
      ? tr("Prüfung nicht verfügbar")
      : tr("Wird geprüft …")
    : fileProblem === 'error' && fileVerdict
      ? fileVerdict
      : !hasParts && !counts?.error && !counts?.warning
        ? tr("Noch nichts zu prüfen")
        : counts?.error
          ? tr("{0} zu beheben", { "0": String(plural(counts.error, tr("Fehler"), tr("Fehler"))) })
          : counts?.warning
            ? tr("{0} offen", { "0": String(plural(counts.warning, tr("Warnung"), tr("Warnungen"))) })
            : fileProblem && fileVerdict
              ? fileVerdict
              : counts?.info
                ? tr("Keine Fehler oder Warnungen")
                : tr("Alles in Ordnung")

  const fileDetail = fileProblem
    ? tr("Altium findet Symbole und Footprints erst, wenn sie in den SchLib-/PcbLib-Dateien stehen{0}.", { "0": String(writerMissing ? tr(" – dafür fehlt ein Bibliotheks-Writer") : '') })
    : null
  const detail = !hasParts
    ? tr("Sobald Bauteile angelegt sind, zeigt PartForge hier, wie gut sie für Altium vorbereitet sind.")
    : blocked
      ? fileDetail
      : !scored || totalParts === undefined
        ? fileDetail
        : scored.dblib
          ? tr("DbLib-Fehler: Altium sieht die {0} nicht oder falsch.", { "0": String(plural(totalParts, tr("Bauteil"), tr("Bauteile"))) })
          : tr("{0}{1} von {2} ohne Fehler und Warnungen{3}{4}", { "0": String(scored.exact ? '' : tr("Höchstens ")), "1": String(formatNumber(scored.clean)), "2": String(plural(totalParts, tr("Bauteil"), tr("Bauteilen"))), "3": String(unrelated ? tr(" · {0} kein Bauteil", { 0: String(plural(unrelated, tr("Befund betrifft"), tr("Befunde betreffen"))) }) : ''), "4": String(fileDetail ? `. ${fileDetail}` : '') })

  const fix = (group: HealthGroup) => {
    const meta = group.info.fix ? DASH_FIX[group.info.fix] : undefined
    if (group.info.fix === 'normalize') return void actions.normalize(group.items)
    if (group.info.fix === 'scan-register') return void actions.scan(true)
    if (group.info.fix === 'repair-heights') return void actions.repairHeights()
    if (meta?.action) return actions.run(meta.action)
    const first = group.items.find((i) => i.table && i.part_number)
    if (first) navigate(partPath(first))
  }
  const fileFix: ActionKey = writerMissing ? 'writer' : 'sync'
  const FileFixIcon = ACTION_META[fileFix].icon

  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        icon={<ShieldCheck />}
        title={tr("Bibliotheksgesundheit")}
        description={updatedAt ? tr("Daten, Dateien und DbLib · geprüft {0}", { "0": String(formatRelativeTime(updatedAt)) }) : tr("Daten, Dateien und DbLib")}
      />
      <CardContent className="@container flex flex-1 flex-col">
        <div className="flex flex-col items-start gap-4 @[20rem]:flex-row @[20rem]:items-center">
          <ProgressRing
            value={blocked ? 1 : scored ? percent / 100 : 0}
            size={92}
            stroke={7}
            tone={tone}
            label={tr("Bibliotheksgesundheit")}
            valueText={
              blocked
                ? tr("{0} – Altium findet die Bauteile noch nicht", { "0": String(fileVerdict ?? tr("Bibliotheksdateien fehlen")) })
                : scored
                  ? tr("{0}{1} Prozent der Bauteile ohne Fehler und Warnungen", { "0": String(scored.exact ? '' : tr("höchstens ")), "1": String(percent) })
                  : failed
                    ? tr("nicht verfügbar")
                    : !report
                      ? tr("wird geprüft")
                      : tr("noch keine Bauteile")
            }
          >
            <span
              className={cn(
                'mono flex items-baseline text-h3 font-semibold leading-none',
                blocked ? 'text-danger-text' : scored ? 'text-fg' : 'text-fg-subtle',
              )}
            >
              {blocked ? '!' : scored ? shownScore : '–'}
              {scored && !blocked && <span className="ml-0.5 text-xs font-medium text-fg-subtle">%</span>}
            </span>
          </ProgressRing>
          <div className="min-w-0 flex-1">
            {loading ? (
              <>
                <Skeleton className="h-4 w-32" />
                <Skeleton className="mt-2 h-3 w-44" />
                <Skeleton className="mt-3 h-3 w-40" />
              </>
            ) : (
              <>
                <div className={cn('text-ui font-medium', fileProblem === 'error' ? 'text-danger-text' : 'text-fg')}>{verdict}</div>
                {detail && <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{detail}</p>}
                {counts && (
                  <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-fg-muted" aria-label={tr("Befunde nach Schwere")}>
                    <SeverityCount n={counts.error} label={tr("Fehler")} color="var(--pf-danger)" />
                    <SeverityCount n={counts.warning} label={counts.warning === 1 ? tr("Warnung") : tr("Warnungen")} color="var(--pf-warning)" />
                    <SeverityCount n={counts.info} label={counts.info === 1 ? tr("Hinweis") : tr("Hinweise")} color="var(--pf-info)" />
                  </ul>
                )}
              </>
            )}
          </div>
        </div>

        {(top.length > 0 || (fileProblem && fileVerdict)) && (
          <div className="mt-4">
            <h3 className="micro-label mb-1">{tr("Wichtigste Befunde")}</h3>
            <ul className="-mx-2 flex flex-col">
              {fileProblem && fileVerdict && (
                <li className="rounded-control px-2 py-1">
                  <div className="flex items-start gap-2">
                    <SeverityIcon severity={fileProblem} className="mt-[3px] size-3.5" />
                    <button
                      type="button"
                      onClick={() => navigate('/altium?bereich=dateien')}
                      className="line-clamp-2 min-w-0 flex-1 rounded-sm text-left text-ui leading-snug text-fg outline-none hover:underline focus-ring"
                    >
                      {fileVerdict}
                      <span className="sr-only"> {tr(" – Bibliotheksdateien ansehen")}</span>
                    </button>
                  </div>
                  {writerMissing && (
                    <p className="ml-[1.375rem] mt-0.5 text-2xs leading-snug text-fg-subtle">
                      {tr("Kein Bibliotheks-Writer bereit – Pfad unter ")}{SETTINGS_PLACE.altium.label}
                    </p>
                  )}
                  <Button
                    variant="ghost"
                    size="xs"
                    leftIcon={<FileFixIcon />}
                    className="ml-4 mt-0.5"
                    loading={actions.pending[fileFix]}
                    onClick={() => actions.run(fileFix)}
                  >
                    {ACTION_META[fileFix].label}
                  </Button>
                </li>
              )}
              {top.map((g) => {
                // eigene Behebung – sonst bei genau einem Bauteil der Sprung dorthin (die Zeile selbst führt zum Bericht)
                const meta = g.info.fix ? DASH_FIX[g.info.fix] : singlePart(g) ? DASH_FIX['open-part'] : undefined
                const pending = meta?.action ? actions.pending[meta.action] : false
                const FixIcon = meta?.icon
                const line = singleLine(g)
                return (
                  <li key={g.key} className="rounded-control px-2 py-1">
                    <div className="flex items-start gap-2">
                      <SeverityIcon severity={g.severity} className="mt-[3px] size-3.5" />
                      <button
                        type="button"
                        onClick={() => navigate(`/altium?bereich=pruefbericht&pruefung=${encodeURIComponent(g.check)}`)}
                        className="line-clamp-2 min-w-0 flex-1 rounded-sm text-left text-ui leading-snug text-fg outline-none hover:underline focus-ring"
                      >
                        {g.info.label}
                        <span className="sr-only">: {plural(g.total, tr("Befund"), tr("Befunde"))} {tr(" – im Prüfbericht ansehen")}</span>
                      </button>
                      <span aria-hidden className="mono shrink-0 text-xs leading-5 text-fg-muted">
                        {formatNumber(g.total)}
                      </span>
                    </div>
                    {line && (
                      <p className="ml-[1.375rem] mt-0.5 line-clamp-2 text-2xs leading-snug text-fg-subtle" title={line}>
                        {line}
                      </p>
                    )}
                    {meta && FixIcon && (
                      <Button
                        variant="ghost"
                        size="xs"
                        leftIcon={<FixIcon />}
                        className="ml-4 mt-0.5"
                        loading={pending}
                        onClick={() => fix(g)}
                      >
                        {g.info.fix ? (g.info.fixLabel ?? meta.label) : meta.label}
                      </Button>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        )}
        {infoOnly && counts && (
          <p className="mt-4 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-control bg-success/8 px-3 py-2 text-xs text-success-text">
            <Check aria-hidden className="size-3.5" />
            {tr("Keine Fehler ·")}<button
              type="button"
              onClick={() => navigate('/altium?bereich=pruefbericht&schwere=hinweise')}
              className="rounded-sm font-medium underline-offset-2 outline-none hover:underline focus-ring"
            >
              {plural(counts.info, tr("Hinweis"), tr("Hinweise"))} {' '}{tr("ansehen")}</button>
          </p>
        )}
        {report && !top.length && !infoOnly && !fileProblem && hasParts && (
          <p className="mt-4 flex items-center gap-2 rounded-control bg-success/8 px-3 py-2 text-xs text-success-text">
            <Check aria-hidden className="size-3.5" />
            {tr("Keine Befunde – Daten, Dateien und DbLib passen zusammen.")}</p>
        )}
        <div className="mt-auto pt-4">
          <Button className="w-full" variant="secondary" leftIcon={<ShieldCheck />} loading={actions.pending.check} onClick={() => void actions.checkLibrary()}>
            {tr("Bibliothek prüfen")}</Button>
        </div>
      </CardContent>
    </Card>
  )
}

function SeverityCount({ n, label, color }: { n: number; label: string; color: string }) {
  useI18n()
  return (
    <li className="flex items-center gap-1.5">
      <span aria-hidden className="size-2 rounded-full" style={{ background: n ? color : 'var(--pf-surface-3)' }} />
      <span className={cn('mono font-medium', n ? 'text-fg' : 'text-fg-subtle')}>{formatNumber(n)}</span> {label}
    </li>
  )
}

// --------------------------------------------------------------------------- Letzte Änderungen

/** Neue Aktionen des Backends fallen auf „bearbeitet“ zurück (kein Typfehler bei Erweiterungen) */
const ACTION_LABEL: Partial<Record<AuditEntry['action'], { label: string; icon: LucideIcon }>> & {
  update: { label: string; icon: LucideIcon }
} = {
  create: { get label() { return tr("angelegt") }, icon: Plus },
  update: { get label() { return tr("bearbeitet") }, icon: Pencil },
  delete: { get label() { return tr("gelöscht") }, icon: Trash2 },
  restore: { get label() { return tr("wiederhergestellt") }, icon: ArchiveRestore },
  bulk_update: { get label() { return tr("per Massenänderung geändert") }, icon: Layers },
  import: { get label() { return tr("importiert") }, icon: FileDown },
  schema: { get label() { return tr("Kategorie geändert") }, icon: ListTree },
}

/** Autor automatischer Sammeländerungen (Vorlagen neu angewendet, Pfade nachgezogen – `db.lifecycle.MIGRATION_AUTHOR`) */
const AUTOMATIC_AUTHOR = 'PartForge'

/** Schlüssel eines Bauteils in der Historie (Kategorie + Teilenummer, ohne Groß-/Kleinschreibung) */
const partKey = (e: Pick<AuditEntry, 'table' | 'part_number'>) => `${e.table ?? ''}|${(e.part_number ?? '').toLowerCase()}`

function RecentChanges({ stats, unavailable }: { stats: LibraryStats | undefined; unavailable: boolean }) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const labels = new Map((stats?.categories ?? []).map((c) => [c.table, c] as const))
  const entries = (stats?.recent_changes ?? []).slice(0, 8)
  const [restoring, setRestoring] = useState<string | null>(null)
  /** Gelöschtes Bauteil aus der Änderungshistorie zurückholen (gleicher Weg wie „Rückgängig“ in der Tabelle) */
  const restore = async (e: AuditEntry) => {
    if (!e.table || !e.part_number || restoring) return
    setRestoring(partKey(e))
    try {
      await restoreParts(qc, e.table, [e.part_number])
    } finally {
      setRestoring(null)
    }
  }

  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        icon={<History />}
        title={tr("Letzte Änderungen")}
        description={tr("Neu angelegte und bearbeitete Bauteile")}
        actions={
          entries.length > 0 ? (
            <Button size="sm" variant="ghost" rightIcon={<ArrowRight />} onClick={() => navigate('/bauteile')}>
              {tr("Zu den Bauteilen")}</Button>
          ) : undefined
        }
      />
      <CardContent className="flex-1">
        {!stats && !unavailable && (
          <div className="flex flex-col gap-3">
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        )}
        {stats && entries.length === 0 && (
          <EmptyState
            size="sm"
            icon={<History />}
            title={tr("Noch keine Änderungen")}
            description={tr("Neu angelegte und bearbeitete Bauteile erscheinen hier als Zeitleiste.")}
          />
        )}
        {entries.length > 0 && (
          <ol className="-mx-2 flex flex-col">
            {entries.map((e, i) => {
              const meta =
                e.action === 'bulk_update' && e.author === AUTOMATIC_AUTHOR
                  ? { label: tr("automatisch angepasst"), icon: Layers }
                  : (ACTION_LABEL[e.action] ?? ACTION_LABEL.update)
              const cat = e.table ? labels.get(e.table) : undefined
              const target =
                e.table && e.part_number && e.action !== 'delete'
                  ? `/bauteile/${encodeURIComponent(e.table)}?pn=${encodeURIComponent(e.part_number)}`
                  : null
              // Wiederherstellen nur, solange danach nichts mehr mit dem Bauteil geschah (neuere Einträge stehen davor)
              const restorable =
                e.action === 'delete' && Boolean(e.table && e.part_number) && !entries.slice(0, i).some((n) => partKey(n) === partKey(e))
              // Metazeile bricht zwischen den Angaben um statt abzuschneiden (Kategorie und Autor vollständig, auch bei 1120 px)
              const metaParts: ReactNode[] = []
              if (cat) {
                metaParts.push(
                  <span className="inline-flex items-center gap-1.5">
                    <span aria-hidden className="size-1.5 shrink-0 rounded-full" style={{ background: cat.color ?? undefined }} />
                    {cat.label}
                  </span>,
                )
              }
              metaParts.push(formatRelativeTime(e.ts))
              if (e.author) metaParts.push(e.author)
              const content = (
                <>
                  <span
                    aria-hidden
                    className="flex size-7 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted [&_svg]:size-3.5"
                  >
                    <meta.icon />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex min-w-0 flex-wrap items-baseline gap-x-2">
                      <span className={cn('min-w-0 break-all text-ui text-fg', e.part_number && 'mono')}>{e.part_number ?? cat?.label ?? tr("Bibliothek")}</span>
                      <span className="shrink-0 text-xs text-fg-subtle">{meta.label}</span>
                    </span>
                    <span className="block text-2xs leading-4 text-fg-subtle">
                      {metaParts.map((part, n) => (
                        <Fragment key={n}>
                          {n > 0 && ' '}
                          {/* Trenner am Ende der Angabe – eine neue Zeile beginnt nie mit „·“ */}
                          <span className="whitespace-nowrap">
                            {part}
                            {n < metaParts.length - 1 && (
                              <span aria-hidden className="pl-1">
                                ·
                              </span>
                            )}
                          </span>
                        </Fragment>
                      ))}
                    </span>
                  </span>
                </>
              )
              return (
                <motion.li
                  key={e.id}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.25, delay: 0.1 + i * 0.02 }}
                >
                  {target ? (
                    <button
                      type="button"
                      onClick={() => navigate(target)}
                      className="flex w-full items-center gap-3 rounded-control px-2 py-1.5 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset"
                    >
                      {content}
                    </button>
                  ) : (
                    <div className="flex items-center gap-3 px-2 py-1.5">
                      {content}
                      {restorable && (
                        <Button
                          size="xs"
                          variant="ghost"
                          leftIcon={<ArchiveRestore />}
                          className="shrink-0"
                          loading={restoring === partKey(e)}
                          disabled={Boolean(restoring) && restoring !== partKey(e)}
                          aria-label={tr("{0} wiederherstellen", { "0": String(e.part_number) })}
                          onClick={() => void restore(e)}
                        >
                          {tr("Wiederherstellen")}</Button>
                      )}
                    </div>
                  )}
                </motion.li>
              )
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- Altium und DbLib

function AltiumCard({
  model,
  status,
  failed,
  actions,
  onNavigate,
}: {
  model: PageModel | null
  status: AltiumStatus | undefined
  failed: boolean
  actions: AltiumActions
  onNavigate: (to: string) => void
}) {
  const { t: tr } = useI18n()
  const primary = model?.headline.primary ?? null
  const order = ['altium', 'dblib', 'files'] as const
  const rows = model ? order.map((k) => model.nodes.find((n) => n.key === k)).filter((n) => n !== undefined) : []
  const refreshed = lastRefreshText(status)
  const PrimaryIcon = primary ? ACTION_META[primary].icon : null

  return (
    <Card className="flex flex-col">
      <CardHeader
        icon={<PlugZap />}
        title={tr("Altium und DbLib")}
        description={failed ? tr("Status nicht verfügbar") : (model?.headline.title ?? tr("Wird geprüft …"))}
        actions={
          <Button size="sm" variant="ghost" rightIcon={<ArrowRight />} onClick={() => onNavigate('/altium')}>
            Details
          </Button>
        }
      />
      <CardContent className="flex flex-col gap-3">
        {!model ? (
          <div className="flex flex-col gap-2.5" aria-hidden>
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : (
          <dl className="divide-y divide-line border-y border-line">
            {rows.map((node) => (
              // Beschriftung behält ihre Breite; ein langer Grund („ODBC-Treiber fehlt – …“) bricht rechts um
              <div key={node.key} className="flex items-center gap-3 py-2">
                <dt className="flex shrink-0 items-center gap-2 text-xs text-fg-muted">
                  <LevelDot level={node.level} />
                  <span>{node.label}</span>
                </dt>
                <dd className="min-w-0 flex-1 text-right">
                  <span className={cn('block truncate text-xs font-medium', node.emphasis === 'detail' ? 'text-fg' : LEVEL_TEXT[node.level])}>
                    {node.value}
                  </span>
                  {node.detail && (
                    <span
                      className={cn(
                        'line-clamp-2 text-2xs',
                        node.emphasis === 'detail' && node.level !== 'ok' ? LEVEL_TEXT[node.level] : 'text-fg-subtle',
                      )}
                      title={localizeMessage(node.detail)}
                    >
                      {localizeMessage(node.detail)}
                    </span>
                  )}
                </dd>
              </div>
            ))}
            {status?.altium_running && (
              <div className="flex items-center gap-3 py-2">
                <dt className="flex min-w-0 flex-1 items-center gap-2 text-xs text-fg-muted">
                  <LevelDot level={status.refresh.running ? 'busy' : status.refresh.last_error ? 'warn' : 'ok'} />
                  <span className="truncate">{tr("Aktualisierung")}</span>
                </dt>
                <dd className="min-w-0 text-right">
                  <span className="block truncate text-xs font-medium text-fg">
                    {status.refresh.running ? tr("läuft …") : refreshed ? refreshed : tr("noch nicht")}
                  </span>
                  <span className="block truncate text-2xs text-fg-subtle">
                    {status.refresh.auto_refresh ? tr("automatisch nach Änderungen") : tr("nur manuell")}
                  </span>
                </dd>
              </div>
            )}
          </dl>
        )}
        {model?.headline.link && <HeadlineLink link={model.headline.link} className="self-start" />}
        {primary && PrimaryIcon && (
          <Button variant="secondary" leftIcon={<PrimaryIcon />} loading={actions.pending[primary]} onClick={() => actions.run(primary)}>
            {ACTION_META[primary].label}
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- Weitere Aktionen

function QuickActions({
  onRun,
  onNavigate,
  installed,
  actions,
  blocker,
  notRunning,
}: {
  onRun: (id: string) => void
  onNavigate: (to: string) => void
  installed: boolean | null
  actions: AltiumActions
  /** Warum Altium-Aktionen gerade nicht gehen (`null` = bereit) */
  blocker: string | null
  /** Altium gefunden, aber nicht gestartet */
  notRunning: boolean
}) {
  const { t: tr } = useI18n()
  const altiumText = (ready: string) => (blocker ? (notRunning ? tr("erst Altium starten") : tr("Altium nicht bereit")) : ready)
  return (
    <Card>
      <CardHeader icon={<Zap />} title={tr("Weitere Aktionen")} />
      <CardContent className="@container -mt-1">
        <div className="grid grid-cols-1 gap-x-2 @[26rem]:grid-cols-2">
          <QuickAction icon={Plus} title={tr("Neues Bauteil")} text={tr("Mit Smart-Eingabe")} hotkey="mod+n" onClick={() => onRun('parts.new')} />
          <QuickAction
            icon={ShieldCheck}
            title={tr("Bibliothek prüfen")}
            text={tr("Prüfbericht aktualisieren")}
            pending={actions.pending.check}
            onClick={() => void actions.checkLibrary()}
          />
          <QuickAction
            icon={RefreshCw}
            title={tr("DbLib neu erzeugen")}
            text={tr("Für Altium")}
            pending={actions.pending.regenerate}
            onClick={() => actions.run('regenerate')}
          />
          {installed ? (
            <QuickAction
              icon={RotateCw}
              title={tr("In Altium aktualisieren")}
              text={altiumText(tr("Datenbank neu einlesen"))}
              pending={actions.pending.refresh}
              blocked={Boolean(blocker)}
              onClick={() => actions.run('refresh')}
            />
          ) : (
            <QuickAction
              icon={PlugZap}
              title={tr("In Altium installieren")}
              text={altiumText(tr("DbLib einbinden"))}
              pending={actions.pending.install}
              blocked={Boolean(blocker)}
              onClick={() => actions.run('install')}
            />
          )}
          <QuickAction
            icon={FolderSync}
            title={tr("Synchronisieren")}
            text={tr("SchLib/PcbLib schreiben")}
            pending={actions.pending.sync}
            onClick={() => actions.run('sync')}
          />
          <QuickAction icon={ListTree} title={tr("Kategorien und Felder")} text={tr("Felder anpassen")} onClick={() => onNavigate('/einstellungen/kategorien')} />
        </div>
      </CardContent>
    </Card>
  )
}

function QuickAction({
  icon: Icon,
  title,
  text,
  hotkey,
  pending,
  blocked,
  onClick,
}: {
  icon: LucideIcon
  title: string
  text: string
  hotkey?: string
  pending?: boolean
  /** gesperrt (Grund steht in `text`) – bleibt fokussierbar */
  blocked?: boolean
  onClick: () => void
}) {
  useI18n()
  return (
    <button
      type="button"
      onClick={blocked || pending ? undefined : onClick}
      aria-disabled={blocked || undefined}
      aria-busy={pending || undefined}
      className={cn(
        'group/qa relative flex min-w-0 items-center gap-3 rounded-button px-2 py-2 text-left outline-none transition-colors focus-ring-inset',
        blocked ? 'cursor-not-allowed' : 'hover:bg-surface-2',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted transition-colors',
          !blocked && 'group-hover/qa:border-accent/30 group-hover/qa:bg-accent-soft group-hover/qa:text-accent-text',
          blocked && 'opacity-60',
        )}
      >
        {pending ? <Spinner size={14} tone="accent" /> : <Icon className="size-4" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className={cn('line-clamp-2 text-ui font-medium leading-tight', blocked ? 'text-fg-muted' : 'text-fg')}>{title}</span>
        <span className="mt-0.5 block truncate text-2xs text-fg-subtle">{text}</span>
      </span>
      {hotkey && (
        <Kbd
          hotkey={hotkey}
          size="xs"
          className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 transition-opacity group-hover/qa:opacity-100 group-focus-visible/qa:opacity-100"
        />
      )}
    </button>
  )
}
