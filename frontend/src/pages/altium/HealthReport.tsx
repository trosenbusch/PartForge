import { useI18n, localizeMessage } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { AnimatePresence, motion } from 'motion/react'
import {
  ArchiveRestore,
  ArrowRight,
  ChevronRight,
  FileScan,
  FolderInput,
  FolderSearch,
  FolderSync,
  Layers,
  ListTree,
  PencilLine,
  RefreshCw,
  Replace,
  RulerDimensionLine,
  Search,
  Settings2,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type Ref } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import type { IssueSeverity } from '@/api/altium'
import { errorMessage } from '@/api/client'
import { libraryApi, useCategories, type CategoryDef } from '@/api/library'
import {
  AREA_LABEL,
  DATA_CHECK_LIMIT,
  FILE_ISSUE_LIMIT,
  findingMessage,
  RESTORE_BACKUP_ACTION,
  SEVERITY_LABEL,
  type FixKind,
  type HealthGroup,
  type HealthItem,
  type MergedHealth,
} from '@/api/libraries'
import { Badge, Button, Callout, Card, EmptyState, IconButton, Input, SegmentedControl, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatNumber, formatRelativeTime, plural } from '@/lib/format'
import type { ActionKey } from './model'
import { partPath } from './paths'
import type { AltiumActions } from './useAltiumActions'
import { FilterLabel, SeverityIcon } from './ui'

export type SeverityFilter = 'all' | IssueSeverity

const FIX: Record<FixKind, { label: string; icon: LucideIcon }> = {
  regenerate: { get label() { return tr("DbLib neu erzeugen") }, icon: RefreshCw },
  sync: { get label() { return tr("Synchronisieren") }, icon: FolderSync },
  scan: { get label() { return tr("Dateien prüfen") }, icon: FolderSearch },
  'scan-register': { get label() { return tr("Aus Dateien übernehmen") }, icon: FolderInput },
  'scan-sync': { get label() { return tr("Prüfen und synchronisieren") }, icon: FolderSync },
  'repair-heights': { get label() { return tr("Footprint-Höhen nachtragen") }, icon: RulerDimensionLine },
  'restore-backup': { get label() { return tr("Aus Sicherung wiederherstellen") }, icon: ArchiveRestore },
  'install-replace': { get label() { return tr("Ersetzen und installieren") }, icon: Replace },
  normalize: { get label() { return tr("Vereinheitlichen") }, icon: Wrench },
  'open-part': { get label() { return tr("Bauteil öffnen") }, icon: PencilLine },
  import: { get label() { return tr("Datenblatt-Import öffnen") }, icon: FileScan },
  categories: { get label() { return tr("Kategorien öffnen") }, icon: ListTree },
  settings: { get label() { return tr("Einstellungen öffnen") }, icon: Settings2 },
}

/** Aktionsschlüssel der Seite je Behebung (Fortschrittsanzeige am Knopf) */
const FIX_ACTION: Partial<Record<FixKind, ActionKey>> = {
  regenerate: 'regenerate',
  sync: 'sync',
  scan: 'scan',
  'scan-register': 'scan',
  'scan-sync': 'scanSync',
  'repair-heights': 'repairHeights',
  'restore-backup': 'restoreBackup',
  'install-replace': 'installReplace',
  normalize: 'normalize',
}

const ITEM_PAGE = 40
/** So viele Teilenummern nennt eine Zeile zu Symbol, Footprint oder Datei (der Rest als Anzahl) */
const PART_LINKS = 3

export interface HealthReportProps {
  report: MergedHealth | undefined
  loading: boolean
  fetching: boolean
  error: Error | null
  updatedAt: number | null
  actions: AltiumActions
  onRecheck: () => void
  /** Prüfung, die geöffnet und angesteuert werden soll (Sprung aus der Übersicht) */
  focusCheck?: string | null
  /** Filter beim Öffnen (`?schwere=…`) */
  initialFilter?: SeverityFilter
  /** alle Teilprüfungen haben geantwortet (erst dann werden Gruppen vorab aufgeklappt) */
  ready: boolean
}

/**
 * Bauteil nur über die Teilenummer öffnen (Befunde der Dateiprüfung nennen keine Kategorie): die Schnellsuche liefert
 * die Tabelle, dann `/bauteile/:table?pn=…`.
 */
function useOpenPartNumber() {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  return async (pn: string) => {
    try {
      const hits = await libraryApi.search(pn, 8)
      const hit = hits.find((h) => h.part_number.toLowerCase() === pn.toLowerCase())
      if (hit) navigate(partPath({ table: hit.table, part_number: hit.part_number }))
      else toast.info(tr("Bauteil nicht gefunden"), { id: 'health-open-part', description: tr("„{0}“ steht nicht mehr in der Bibliothek.", { "0": String(pn) }) })
    } catch (err) {
      toast.error(tr("Bauteil konnte nicht geöffnet werden"), { id: 'health-open-part', description: errorMessage(err) })
    }
  }
}

export function HealthReport({
  report,
  loading,
  fetching,
  error,
  updatedAt,
  actions,
  onRecheck,
  focusCheck,
  initialFilter = 'all',
  ready,
}: HealthReportProps) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const openPartNumber = useOpenPartNumber()
  const categories = useCategories().data
  const catMap = useMemo(() => new Map((categories ?? []).map((c) => [c.table, c] as const)), [categories])
  const [filter, setFilter] = useState<SeverityFilter>(initialFilter)
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<Set<string>>(() => new Set())
  const [seededFor, setSeededFor] = useState<MergedHealth | undefined>(undefined)

  // Vollständige erste Antwort: wenige Fehler gleich zeigen, die angesteuerte Prüfung aufklappen
  if (report && ready && seededFor === undefined) {
    setSeededFor(report)
    const initial = new Set<string>()
    const errors = report.groups.filter((g) => g.severity === 'error')
    if (errors.reduce((n, g) => n + g.items.length, 0) <= 6) errors.filter((g) => g.items.length > 1).forEach((g) => initial.add(g.key))
    if (focusCheck) report.groups.filter((g) => g.check === focusCheck).forEach((g) => initial.add(g.key))
    setOpen(initial)
  }

  const needle = query.trim().toLowerCase()
  const groups = useMemo(() => {
    if (!report) return []
    return report.groups
      .filter((g) => filter === 'all' || g.severity === filter)
      .map((g) => {
        if (!needle) return g
        const items = g.items.filter((i) => matches(i, g, needle, catMap))
        return items.length || tr(g.info.label).toLowerCase().includes(needle)
          ? { ...g, items: items.length ? items : g.items, total: items.length || g.total, partial: items.length ? false : g.partial }
          : null
      })
      .filter((g): g is HealthGroup => g !== null)
  }, [report, filter, needle, catMap, tr])

  const focusRef = useRef<HTMLLIElement | null>(null)
  useEffect(() => {
    if (focusCheck && seededFor) focusRef.current?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [focusCheck, seededFor, tr])

  const toggle = (key: string) =>
    setOpen((cur) => {
      const next = new Set(cur)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  const runFix = (fix: FixKind, group: HealthGroup) => {
    switch (fix) {
      case 'regenerate':
        actions.run('regenerate')
        break
      case 'sync':
        actions.run('sync')
        break
      case 'scan':
        void actions.scan(false)
        break
      case 'scan-register':
        void actions.scan(true)
        break
      case 'scan-sync':
        actions.run('scanSync')
        break
      case 'repair-heights':
        // alle betroffenen Footprints – außerhalb geänderte Bibliotheken überspringt das Backend (mit Hinweis)
        void actions.repairHeights()
        break
      case 'restore-backup':
        // nur Dateien, für die es eine lesbare Sicherung gibt (fix_action des Backends)
        void actions.restoreBackup(
          group.items.filter((i) => i.fixAction === RESTORE_BACKUP_ACTION && i.library).map((i) => i.library as string),
        )
        break
      case 'install-replace':
        void actions.install(true)
        break
      case 'normalize':
        void actions.normalize(group.items)
        break
      case 'open-part': {
        const first = group.items.find((i) => i.table && i.part_number)
        if (first) navigate(partPath(first))
        break
      }
      case 'import':
        navigate('/import')
        break
      case 'categories':
        navigate('/einstellungen/kategorien')
        break
      case 'settings':
        navigate('/einstellungen/bibliothek')
        break
    }
  }

  const counts = report?.counts
  const totalIssues = counts ? counts.error + counts.warning + counts.info : 0
  const sections = (['error', 'warning', 'info'] as IssueSeverity[])
    .map((severity) => ({ severity, groups: groups.filter((g) => g.severity === severity) }))
    .filter((s) => s.groups.length > 0)

  return (
    <div className="flex flex-col gap-4">
      {/* Werkzeugleiste – bei 1120 px in einer Zeile (Stand-Text erst ab 60 rem) */}
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedControl<SeverityFilter>
          size="sm"
          aria-label={tr("Nach Schwere filtern")}
          value={filter}
          onValueChange={setFilter}
          options={[
            { value: 'all', label: <FilterLabel label={tr("Alle")} count={counts ? totalIssues : undefined} /> },
            { value: 'error', label: <FilterLabel label={tr("Fehler")} count={counts?.error} tone="error" /> },
            { value: 'warning', label: <FilterLabel label={tr("Warnungen")} count={counts?.warning} tone="warning" /> },
            { value: 'info', label: <FilterLabel label={tr("Hinweise")} count={counts?.info} tone="info" /> },
          ]}
        />
        <Input
          size="sm"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && query) {
              e.stopPropagation()
              setQuery('')
            }
          }}
          placeholder={tr("Bauteil, Kategorie, Meldung …")}
          aria-label={tr("Prüfbericht durchsuchen")}
          prefix={<Search />}
          suffix={query ? <IconButton size="xs" label={tr("Suche leeren")} icon={<X />} onClick={() => setQuery('')} tooltip={false} /> : undefined}
          containerClassName="w-60 max-w-full @[62rem]:w-72"
        />
        <div className="ml-auto flex items-center gap-3">
          {report && (
            <span className="hidden text-xs text-fg-subtle @[62rem]:inline" aria-live="polite">
              {report.checkedParts > 0 && `${plural(report.checkedParts, tr("Bauteil"), tr("Bauteile"))} · `}
              {updatedAt ? tr("geprüft {0}", { "0": String(formatRelativeTime(updatedAt)) }) : tr("geprüft")}
            </span>
          )}
          <Button
            size="sm"
            variant="secondary"
            leftIcon={<RefreshCw />}
            loading={fetching}
            onClick={onRecheck}
            title={updatedAt ? tr("Zuletzt geprüft {0}", { "0": String(formatRelativeTime(updatedAt)) }) : undefined}
          >
            {tr("Erneut prüfen")}</Button>
        </div>
      </div>

      {/* Teilprüfungen ohne Antwort */}
      {report && (report.missing.data || report.missing.files || report.missing.dblib) && (
        <Callout
          tone="warning"
          title={tr("Der Bericht ist unvollständig")}
          actions={
            <Button size="sm" onClick={onRecheck} loading={fetching}>
              {tr("Erneut prüfen")}</Button>
          }
        >
          {report.missing.data && <span className="block">{tr("Datenprüfung: ")}{report.missing.data}</span>}
          {report.missing.files && <span className="block">{tr("Dateiprüfung: ")}{report.missing.files}</span>}
          {report.missing.dblib && <span className="block">{tr("DbLib-Status: ")}{report.missing.dblib}</span>}
        </Callout>
      )}

      {loading && <ReportSkeleton />}

      {error && !report && (
        <Callout tone="danger" title={tr("Die Prüfung ist fehlgeschlagen")} actions={<Button size="sm" onClick={onRecheck} loading={fetching}>{tr("Erneut versuchen")}</Button>}>
          {localizeMessage(error.message)}
        </Callout>
      )}

      {report && totalIssues === 0 && (
        <Card>
          {report.checkedParts > 0 ? (
            <EmptyState
              illustration="all-good"
              title={tr("Keine Probleme gefunden")}
              description={tr("{0}, ihre Symbole, Footprints und Bibliotheksdateien sowie die DbLib sind in Ordnung.", { "0": String(plural(report.checkedParts, tr("Bauteil"), tr("Bauteile"))) })}
            />
          ) : (
            <EmptyState
              illustration="no-parts"
              title={tr("Noch nichts zu prüfen")}
              description={tr("Sobald Bauteile angelegt sind, prüft PartForge Pflichtfelder, Werte und Dubletten, Symbole, Footprints und Bibliotheksdateien – und die DbLib für Altium.")}
              actions={
                <Button size="sm" leftIcon={<Layers />} onClick={() => navigate('/serien')}>
                  {tr("Serie erzeugen")}</Button>
              }
            />
          )}
        </Card>
      )}

      {report && totalIssues > 0 && sections.length === 0 && (
        <Card>
          <EmptyState
            size="sm"
            illustration="search-empty"
            title={tr("Keine Treffer")}
            description={tr("Kein Befund passt zu Filter und Suche.")}
            actions={
              <Button
                size="sm"
                onClick={() => {
                  setQuery('')
                  setFilter('all')
                }}
              >
                {tr("Filter zurücksetzen")}</Button>
            }
          />
        </Card>
      )}

      {sections.map((section) => (
        <section key={section.severity} aria-labelledby={`sev-${section.severity}`} className="flex flex-col gap-2">
          <h3 id={`sev-${section.severity}`} className="flex items-center gap-2 px-1 text-ui font-semibold text-fg">
            <SeverityIcon severity={section.severity} />
            {SEVERITY_LABEL[section.severity].section}
            <span className="mono text-xs font-medium text-fg-subtle">
              {formatNumber(section.groups.reduce((n, g) => n + g.total, 0))}
            </span>
          </h3>
          <Card className="overflow-hidden">
            <ul className="divide-y divide-line">
              {section.groups.map((group) => (
                <GroupRow
                  key={group.key}
                  ref={focusCheck && group.check === focusCheck ? focusRef : undefined}
                  group={group}
                  open={open.has(group.key) || Boolean(needle)}
                  onToggle={() => toggle(group.key)}
                  catMap={catMap}
                  fixPending={group.info.fix && FIX_ACTION[group.info.fix] ? actions.pending[FIX_ACTION[group.info.fix] as ActionKey] : false}
                  onFix={(fix) => runFix(fix, group)}
                  onOpenPart={(item) => navigate(partPath(item))}
                  onOpenPartNumber={(pn) => void openPartNumber(pn)}
                />
              ))}
            </ul>
          </Card>
        </section>
      ))}

      {report && (report.dataTruncated || report.filesTruncated) && <TruncationNote report={report} />}
    </div>
  )
}

/** Was gekürzt ist – passend zu den Grenzen des Backends (Datenprüfung je Prüfung, Dateiprüfung insgesamt) */
function TruncationNote({ report }: { report: MergedHealth }) {
  const { t: tr } = useI18n()
  const parts = [
    report.dataTruncated && tr("die Datenprüfung je Prüfung höchstens {0} Befunde", { "0": String(formatNumber(DATA_CHECK_LIMIT)) }),
    report.filesTruncated && tr("die Dateiprüfung insgesamt die ersten {0} (nach Schwere sortiert)", { "0": String(formatNumber(FILE_ISSUE_LIMIT)) }),
  ].filter(Boolean)
  const mixed = report.groups.some((g) => g.partial && g.areas.length > 1)
  return (
    <p className="px-1 text-xs leading-relaxed text-fg-subtle">
      {tr("Sehr viele Befunde – aufgeführt sind ")}{parts.join(' und ')}{tr(". Die Zahlen an den Gruppen zählen alle Befunde")}{mixed ? tr("; bei Gruppen aus beiden Prüfungen nur die aufgeführten") : ''}.
    </p>
  )
}

function matches(item: HealthItem, group: HealthGroup, needle: string, catMap: Map<string, CategoryDef>): boolean {
  const cat = item.table ? catMap.get(item.table) : undefined
  return [item.part_number, item.subject, item.message, item.table, cat?.label, item.column, item.library, group.info.label, ...item.partNumbers]
    .filter(Boolean)
    .some((v) => String(v).toLowerCase().includes(needle))
}

/**
 * „N Bauteile betroffen“ zeigen? Bei Befunden zu Symbol, Footprint oder Datei immer; bei Befunden je Bauteil nur, wenn
 * ein Bauteil mehrere hat (sonst wiederholt es die Anzahl) – und nie für gekürzte Gruppen je Bauteil (unbekannt).
 */
function showParts(group: HealthGroup, count: number): boolean {
  const perPart = group.items.every((i) => i.part_number)
  if (!perPart) return true
  return !group.partial && count !== group.total
}

/** Bauteile, die eine Gruppe betrifft (Teilenummern der Zeilen; `exact` = keine Zeile nennt nur einen Teil) */
function groupParts(group: HealthGroup): { count: number; exact: boolean } {
  const pns = new Set<string>()
  let exact = !group.partial
  let max = 0
  for (const item of group.items) {
    if (item.part_number) pns.add(item.part_number)
    for (const pn of item.partNumbers) pns.add(pn)
    if (item.affectedParts > item.partNumbers.length) exact = false
    max = Math.max(max, item.affectedParts)
  }
  return { count: Math.max(pns.size, max), exact }
}

// --------------------------------------------------------------------------- Gruppe

function GroupRow({
  group,
  open,
  onToggle,
  catMap,
  fixPending,
  onFix,
  onOpenPart,
  onOpenPartNumber,
  ref,
}: {
  group: HealthGroup
  open: boolean
  onToggle: () => void
  catMap: Map<string, CategoryDef>
  fixPending: boolean
  onFix: (fix: FixKind) => void
  onOpenPart: (item: HealthItem) => void
  onOpenPartNumber: (pn: string) => void
  ref?: Ref<HTMLLIElement>
}) {
  const { t: tr } = useI18n()
  const [limit, setLimit] = useState(ITEM_PAGE)
  const fix = group.info.fix
  const meta = fix ? FIX[fix] : null
  const FixIcon = meta?.icon
  const listId = `grp-${group.key.replace(/[^a-z0-9]/gi, '-')}`
  const parts = groupParts(group)
  const shown = group.items.slice(0, limit)
  const hidden = group.total - shown.length
  // Hinweise sind keine Störungen: leise Schaltfläche; Fehler und Warnungen: sekundär (die Primäraktion steht oben)
  const quiet = group.severity === 'info'
  // Nur ein Befund: er steht gleich im Kopf (ohne Aufklappen lesbar)
  const single = group.total === 1 && group.items.length === 1 ? group.items[0] : null

  return (
    <li ref={ref} className="scroll-mt-24">
      <div className="flex items-start gap-3 px-3 py-2.5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={listId}
          onClick={onToggle}
          className="group/g flex min-w-0 flex-1 items-start gap-2.5 rounded-control px-1 py-0.5 text-left outline-none focus-ring"
        >
          <ChevronRight
            aria-hidden
            className={cn('mt-0.5 size-4 shrink-0 text-fg-subtle transition-transform duration-200', open && 'rotate-90')}
          />
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span className="text-ui font-medium text-fg">{group.info.label}</span>
              <span className="mono text-xs text-fg-muted">
                {formatNumber(group.total)}
                <span className="sr-only"> {group.total === 1 ? tr("Befund") : tr("Befunde")}</span>
              </span>
              {parts.count > 0 && showParts(group, parts.count) && (
                <span className="text-xs text-fg-subtle">
                  · {parts.exact ? '' : 'mind. '}
                  {plural(parts.count, tr("Bauteil"), tr("Bauteile"))} {' '}{tr("betroffen")}</span>
              )}
              {group.areas.map((a) => (
                <Badge key={a} variant="outline" size="sm" className="font-normal">
                  {AREA_LABEL[a]}
                </Badge>
              ))}
            </span>
            {single && (
              <span className="mt-0.5 block text-xs leading-snug text-fg-muted">
                {singlePrefix(single) && (
                  <>
                    <span className={cn('font-medium text-fg', (single.part_number || single.subject) && 'mono')}>{singlePrefix(single)}</span>
                    {' – '}
                  </>
                )}
                {findingMessage(single, group)}
              </span>
            )}
            {group.hint && <span className="mt-0.5 block text-xs leading-snug text-fg-subtle">{localizeMessage(group.hint)}</span>}
          </span>
        </button>
        {meta && FixIcon && fix && (
          <Button
            size="sm"
            variant={quiet ? 'ghost' : 'secondary'}
            leftIcon={<FixIcon />}
            loading={fixPending}
            onClick={() => onFix(fix)}
            className="mt-0.5"
          >
            {group.info.fixLabel ?? meta.label}
          </Button>
        )}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={listId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <ul className="border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_40%,transparent)] py-1">
              {shown.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  group={group}
                  cat={item.table ? catMap.get(item.table) : undefined}
                  onOpenPart={onOpenPart}
                  onOpenPartNumber={onOpenPartNumber}
                />
              ))}
              {(hidden > 0 || group.partial) && (
                <li className="px-4 py-1.5 pl-12">
                  {shown.length < group.items.length ? (
                    <Button size="xs" variant="ghost" onClick={() => setLimit((l) => l + 200)}>
                      {formatNumber(Math.min(200, group.items.length - shown.length))} {tr(" weitere anzeigen")}</Button>
                  ) : hidden > 0 ? (
                    <span className="text-xs text-fg-subtle">{tr("… und ")}{formatNumber(hidden)} {tr(" weitere (nicht aufgeführt)")}</span>
                  ) : (
                    <span className="text-xs text-fg-subtle">{tr("… weitere Befunde nicht aufgeführt (Liste gekürzt)")}</span>
                  )}
                </li>
              )}
            </ul>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}

/** Wovon ein einzelner Befund handelt (Teilenummer bzw. Symbol/Footprint/Datei) – entfällt, wenn die Meldung es nennt */
function singlePrefix(item: HealthItem): string | null {
  if (item.part_number) return item.part_number
  const subject = item.subject ?? subjectKind(item)
  return item.message.includes(subject) ? null : subject
}

/** Art des Gegenstands einer Zeile ohne Bauteil */
function subjectKind(item: HealthItem): string {
  if (item.area === 'dblib') return 'DbLib'
  if (item.kind === 'symbol') return 'Symbol'
  if (item.kind === 'footprint') return 'Footprint'
  const name = (item.subject ?? item.library ?? '').toLowerCase()
  if (name.endsWith('.schlib')) return tr("Symbolbibliothek")
  if (name.endsWith('.pcblib')) return tr("Footprint-Bibliothek")
  return item.area === 'files' ? tr("Bibliotheksdatei") : tr("Registrierung")
}

/** Betroffene Bauteile einer Zeile zu Symbol, Footprint oder Datei: die ersten als Links, der Rest als Anzahl */
function AffectedParts({ item, onOpenPartNumber }: { item: HealthItem; onOpenPartNumber: (pn: string) => void }) {
  const { t: tr } = useI18n()
  const total = Math.max(item.affectedParts, item.partNumbers.length)
  if (!total) return <span className="mt-0.5 block text-2xs text-fg-subtle">{tr("Kein Bauteil verwendet es.")}</span>
  const first = item.partNumbers.slice(0, PART_LINKS)
  const rest = total - first.length
  return (
    <span className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-2xs text-fg-subtle">
      <span>{total === 1 ? tr("Betrifft") : tr("Betrifft {0}:", { "0": String(plural(total, tr("Bauteil"), tr("Bauteile"))) })}</span>
      {first.map((pn, i) => (
        <span key={pn}>
          <button
            type="button"
            onClick={() => onOpenPartNumber(pn)}
            className="mono rounded-sm text-fg-muted underline decoration-line-strong underline-offset-2 outline-none hover:text-accent-text hover:decoration-current focus-ring"
            aria-label={tr("{0} in der Bauteiltabelle öffnen", { "0": String(pn) })}
          >
            {pn}
          </button>
          {i < first.length - 1 ? ',' : ''}
        </span>
      ))}
      {rest > 0 && <span>{tr("und ")}{formatNumber(rest)} {' '}{tr("weitere")}</span>}
    </span>
  )
}

function ItemRow({
  item,
  group,
  cat,
  onOpenPart,
  onOpenPartNumber,
}: {
  item: HealthItem
  group: HealthGroup
  cat: CategoryDef | undefined
  onOpenPart: (item: HealthItem) => void
  onOpenPartNumber: (pn: string) => void
}) {
  const { t: tr } = useI18n()
  const linkable = Boolean(item.table && item.part_number)
  const ownHint = item.fix_hint && item.fix_hint !== group.hint ? item.fix_hint : null
  // Befund zu Symbol, Footprint oder Datei (ohne eigenes Bauteil): die Bauteile, die es verwenden
  const aboutComponent = !item.part_number && item.area === 'files'
  const others = item.part_number && item.affectedParts > 1 ? item.affectedParts - 1 : 0
  const where = item.component && item.library ? baseName(item.library) : null
  const content = (
    <>
      {item.part_number ? (
        <span className="mono min-w-0 break-all text-xs font-medium text-fg">{item.part_number}</span>
      ) : (
        <span className={cn('min-w-0 break-all text-xs font-medium text-fg', item.subject && 'mono')}>
          {item.subject ?? subjectKind(item)}
        </span>
      )}
      <span className="flex min-w-0 flex-col text-xs text-fg-muted">
        {cat ? (
          <span className="flex min-w-0 items-center gap-1.5">
            <span aria-hidden className="size-1.5 shrink-0 rounded-full" style={{ background: cat.color || 'var(--pf-fg-subtle)' }} />
            <span className="truncate">{cat.label}</span>
          </span>
        ) : item.table ? (
          <span className="truncate">{item.table}</span>
        ) : (
          <span className="text-fg-subtle">{item.part_number ? '–' : subjectKind(item)}</span>
        )}
        {where && (
          <span className="mono truncate text-2xs text-fg-subtle" title={item.library ?? undefined}>
            {where}
          </span>
        )}
      </span>
      <span className="min-w-0 text-xs leading-snug text-fg-muted">
        <span className="block">{localizeMessage(findingMessage(item, group))}</span>
        {ownHint && <span className="mt-0.5 block text-2xs text-fg-subtle">{localizeMessage(ownHint)}</span>}
        {others > 0 && <span className="mt-0.5 block text-2xs text-fg-subtle">{tr("und ")}{plural(others, tr("weiteres Bauteil"), tr("weitere Bauteile"))} {tr(" mit demselben Paar")}</span>}
        {aboutComponent && <AffectedParts item={item} onOpenPartNumber={onOpenPartNumber} />}
      </span>
      <span aria-hidden className="flex justify-end">
        {linkable && (
          <ArrowRight className="size-3.5 -translate-x-1 text-fg-subtle opacity-0 transition-all group-hover/item:translate-x-0 group-hover/item:opacity-100 group-focus-visible/item:translate-x-0 group-focus-visible/item:opacity-100" />
        )}
      </span>
    </>
  )
  const grid = 'grid w-full grid-cols-[minmax(8rem,12rem)_minmax(6rem,10rem)_minmax(0,1fr)_1.25rem] items-start gap-3 px-4 py-1.5 pl-12 text-left'
  return (
    <li>
      {linkable ? (
        <button
          type="button"
          onClick={() => onOpenPart(item)}
          aria-label={tr("{0} in der Bauteiltabelle öffnen: {1}", { "0": String(item.part_number), "1": String(localizeMessage(item.message)) })}
          className={cn(grid, 'group/item outline-none transition-colors hover:bg-surface-2 focus-ring-inset')}
        >
          {content}
        </button>
      ) : (
        <div className={grid}>{content}</div>
      )}
    </li>
  )
}

function ReportSkeleton() {
  const { t: tr } = useI18n()
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label={tr("Prüfbericht wird erstellt")}>
      {[0, 1].map((s) => (
        <div key={s} className="flex flex-col gap-2">
          <Skeleton className="h-4 w-28" />
          <Card className="divide-y divide-line">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-3.5">
                <Skeleton className="size-4" />
                <div className="flex-1">
                  <Skeleton className="h-3.5 w-56" />
                  <Skeleton className="mt-1.5 h-3 w-96 max-w-full" />
                </div>
                <Skeleton className="h-7 w-32" />
              </div>
            ))}
          </Card>
        </div>
      ))}
    </div>
  )
}
