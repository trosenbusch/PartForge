import { useI18n } from '@/lib/i18n'
import { useQueryClient } from '@tanstack/react-query'
import { Cable, FileCode2, FolderSearch, FolderSync, PlugZap, RefreshCw, RotateCw, ScanSearch, Settings2, ShieldCheck } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import { useAltiumStatus, useLastVerify, type VerifyInput } from '@/api/altium'
import { setJobFeedback } from '@/api/jobs'
import { useLibraryStats } from '@/api/library'
import {
  librariesKeys,
  libraryFindings,
  partFindings,
  useExternalLibraries,
  useHealthReport,
  useLibraryFiles,
} from '@/api/libraries'
import { isJobActive, isJobFinished, systemKeys, useSettings, useWorkspace, type Job } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { altiumActionFromState, type AltiumAction } from '@/app/navigation'
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { Button, IconButton, Spinner, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { formatNumber } from '@/lib/format'
import { DblibPreviewDialog } from './DblibPreviewDialog'
import { ExternalPanel } from './ExternalPanel'
import { HealthReport, type SeverityFilter } from './HealthReport'
import { LibraryFilesPanel } from './LibraryFilesPanel'
import { altiumBlocker, buildModel, VERIFY_SAMPLE, writerLabel, type ActionKey } from './model'
import { OdbcDialog } from './OdbcDialog'
import { StatusHero, type VerifyScope } from './StatusHero'
import { useAltiumActions, useLatestJob, VERIFY_SAMPLE_INPUT } from './useAltiumActions'
import { VerifyPanel } from './VerifyPanel'

type TabKey = 'pruefbericht' | 'dateien' | 'altium' | 'extern'
const TABS: TabKey[] = ['pruefbericht', 'dateien', 'altium', 'extern']
const SEVERITY_PARAM: Record<string, SeverityFilter> = { fehler: 'error', warnungen: 'warning', hinweise: 'info' }

export default function AltiumPage() {
  const { t: tr } = useI18n()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const workspace = useWorkspace().data
  const settings = useSettings().data
  const statusQ = useAltiumStatus()
  const status = statusQ.data
  const filesQ = useLibraryFiles()
  const stats = useLibraryStats().data
  const health = useHealthReport()
  const externals = useExternalLibraries()
  const actions = useAltiumActions()
  const latestVerify = useLatestJob('altium.verify')
  const lastVerify = useLastVerify().data

  const [previewOpen, setPreviewOpen] = useState(false)
  const [odbc, setOdbc] = useState<{ open: boolean; jobId: string | null }>({ open: false, jobId: null })
  /** Dialog noch offen? (für den asynchronen Start – der Zustand im Abschluss ist sonst veraltet) */
  const odbcOpen = useRef(false)
  useEffect(() => {
    odbcOpen.current = odbc.open
  }, [odbc.open, tr])

  const rawTab = params.get('bereich') as TabKey | null
  const tab: TabKey = rawTab && TABS.includes(rawTab) ? rawTab : 'pruefbericht'
  const focusCheck = params.get('pruefung')
  const severityFilter = SEVERITY_PARAM[params.get('schwere') ?? ''] ?? 'all'
  const setTab = (next: TabKey) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        n.set('bereich', next)
        n.delete('pruefung')
        n.delete('schwere')
        return n
      },
      { replace: true },
    )

  const backend = settings?.settings.altium.library_backend
  const statusError = statusQ.isError && !status ? statusQ.error.message : null
  const report = health.report
  const lib = useMemo(() => libraryFindings(report), [report])
  const model = status || statusError
        ? buildModel({
            status,
            statusError,
            files: filesQ.data,
            filesError: filesQ.error?.message ?? null,
            backend,
            partCount: stats?.total_parts,
            dbKind: workspace?.db_kind,
            dbFile: workspace?.settings.db.sqlite_file,
            findings: partFindings(report),
            findingsError: health.error?.message ?? null,
            reportErrors: report?.counts.error ?? 0,
            linkErrors: lib?.linkErrors ?? 0,
            heights: lib ? { total: lib.heights, repairable: lib.heightsRepairable } : undefined,
          })
        : null
  const blocker = altiumBlocker(status, statusError)
  const tabsRef = useRef<HTMLDivElement>(null)
  const writer = writerLabel(status, backend)

  // ------------------------------------------------------------------ Aktionen mit Seitenbezug

  /**
   * ODBC-Test im Dialog: solange er offen ist, kein zusätzlicher Abschluss-Toast. Der Job endet mit seiner
   * Zusammenfassung als Meldung – der Dialog zeigt sie, der Toast (nach dem Schließen) ebenso.
   */
  const startOdbc = async () => {
    setOdbc({ open: true, jobId: null })
    const job = await actions.odbc({ openDock: false, toast: false })
    if (!job) {
      setOdbc({ open: false, jobId: null })
      return
    }
    if (odbcOpen.current) setOdbc({ open: true, jobId: job.id })
    else setJobFeedback(job.id, { toast: true }) // schon geschlossen, bevor der Job begann: Ergebnis als Meldung
  }

  const onOdbcOpenChange = (open: boolean) => {
    setOdbc((cur) => ({ ...cur, open }))
    if (open || !odbc.jobId) return
    // vor dem Ende geschlossen: Abschluss als Meldung (mit der Zusammenfassung des Berichts)
    const job = qc.getQueryData<Job>(systemKeys.job(odbc.jobId))
    if (!job || !isJobFinished(job)) setJobFeedback(odbc.jobId, { toast: true })
  }

  /** Standard: Stichprobe über alle Kategorien (`sample: 'spread'`); sonst alle, eine Kategorie oder genannte Bauteile */
  const startVerify = async (scope: VerifyScope) => {
    const input: VerifyInput =
      scope.kind === 'all'
        ? { all: true }
        : scope.kind === 'table'
          ? { all: true, tables: [scope.table] }
          : scope.kind === 'parts'
            ? { all: false, part_numbers: scope.partNumbers }
            : VERIFY_SAMPLE_INPUT
    const job = await actions.verify(input, { openDock: false })
    if (job) setTab('altium')
  }

  const showReport = () => {
    if (tab !== 'pruefbericht') setTab('pruefbericht')
    requestAnimationFrame(() => tabsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }

  const onAction = (key: ActionKey) => {
    switch (key) {
      case 'preview':
        setPreviewOpen(true)
        break
      case 'odbc':
        void startOdbc()
        break
      case 'verify':
        void startVerify({ kind: 'sample' })
        break
      case 'sync':
      case 'scanSync':
        if (tab !== 'dateien') setTab('dateien')
        actions.run(key)
        break
      case 'report':
        showReport()
        break
      case 'check':
        if (tab !== 'pruefbericht') setTab('pruefbericht')
        void actions.checkLibrary()
        break
      default:
        actions.run(key)
    }
  }

  // ------------------------------------------------------------------ Aktion im Router-State (Shell-Befehle, Übersicht)

  const location = useLocation()
  /** Aktion, die eine andere Stelle von PartForge per Router-State verlangt (nie aus der Adresse) */
  const aktion = altiumActionFromState(location.state)
  /** frühere Adressform `?aktion=…` – führt nichts aus (sonst könnte ein Link einer fremden Seite Aktionen starten) */
  const staleParam = params.has('aktion')
  const statusReady = statusQ.isSuccess || statusQ.isError
  /** `location.key` der zuletzt ausgeführten Aktion (je Navigation genau einmal, auch im StrictMode) */
  const handled = useRef<string | null>(null)
  const latest = useRef({ onAction, actions })
  useEffect(() => {
    latest.current = { onAction, actions }
  })
  useEffect(() => {
    if (!aktion) {
      if (staleParam) {
        setParams(
          (p) => {
            const n = new URLSearchParams(p)
            n.delete('aktion')
            return n
          },
          { replace: true },
        )
      }
      return
    }
    if (!statusReady || handled.current === location.key) return
    handled.current = location.key
    const target: Partial<Record<AltiumAction, TabKey>> = { sync: 'dateien', pruefen: 'pruefbericht' }
    // State löschen (Neuladen und Zurück lösen die Aktion nicht erneut aus), passenden Reiter zeigen
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        n.delete('aktion')
        const t = target[aktion]
        if (t) n.set('bereich', t)
        return n
      },
      { replace: true, state: null },
    )
    const run = latest.current
    switch (aktion) {
      case 'dblib':
        run.onAction('regenerate')
        break
      case 'sync':
        run.actions.run('sync')
        break
      case 'pruefen':
        void run.actions.checkLibrary()
        break
      case 'installieren':
        run.onAction('install')
        break
      case 'aktualisieren':
        run.onAction('refresh')
        break
      case 'odbc':
        run.onAction('odbc')
        break
      case 'vorschau':
        run.onAction('preview')
        break
    }
    // nur bei neuer Navigation bzw. sobald der Status da ist – die Funktionen kommen aktuell über `latest`
  }, [aktion, staleParam, statusReady, location.key, setParams, tr])

  // ------------------------------------------------------------------ Befehlspalette (überlagert die Shell-Befehle)

  useRegisterCommands([
    {
      id: 'altium.regenerate',
      title: tr("DbLib neu erzeugen"),
      group: 'Aktionen',
      icon: RefreshCw,
      priority: 60,
      keywords: ['dblib', 'odbc', 'altium'],
      run: () => onAction('regenerate'),
    },
    {
      id: 'library.sync',
      title: tr("Bibliotheksdateien synchronisieren"),
      subtitle: tr("Ausstehende Symbole und Footprints in SchLib/PcbLib schreiben"),
      group: 'Aktionen',
      icon: FolderSync,
      priority: 55,
      keywords: ['schlib', 'pcblib', 'symbole', 'footprints', 'ausstehend'],
      run: () => onAction('sync'),
    },
    {
      id: 'library.check',
      title: tr("Bibliothek prüfen"),
      subtitle: tr("Fehlende Symbole, Footprints und Felder finden"),
      group: 'Aktionen',
      icon: ShieldCheck,
      priority: 50,
      keywords: ['validieren', tr("prüfbericht"), 'fehler'],
      run: () => onAction('check'),
    },
    {
      id: 'altium.install',
      title: model?.altium.installed ? tr("Aus Altium deinstallieren") : tr("In Altium installieren"),
      subtitle: model?.altium.installed ? tr("DbLib aus Altium Designer entfernen") : tr("DbLib in Altium Designer einbinden"),
      group: 'Aktionen',
      icon: PlugZap,
      priority: 40,
      run: () => onAction(model?.altium.installed ? 'uninstall' : 'install'),
    },
    {
      id: 'altium.refresh',
      title: tr("In Altium aktualisieren"),
      subtitle: tr("Altium liest die Datenbank neu ein"),
      group: 'Altium',
      icon: RotateCw,
      keywords: ['refresh', tr("neu laden")],
      run: () => onAction('refresh'),
    },
    {
      id: 'altium.verify',
      title: tr("Bibliothek in Altium prüfen"),
      subtitle: tr("Stichprobe über alle Kategorien ({0} Bauteile, mindestens eines je Kategorie)", { "0": String(VERIFY_SAMPLE) }),
      group: 'Altium',
      icon: ScanSearch,
      keywords: ['verify', tr("auflösen"), 'symbol', 'footprint', 'pins'],
      run: () => onAction('verify'),
    },
    {
      id: 'altium.odbc',
      title: tr("ODBC-Verbindung testen"),
      subtitle: tr("Datenbank lesen wie Altium"),
      group: 'Altium',
      icon: Cable,
      keywords: ['treiber', 'verbindung', 'sqlite'],
      run: () => onAction('odbc'),
    },
    {
      id: 'altium.preview',
      title: tr("DbLib-Vorschau anzeigen"),
      group: 'Altium',
      icon: FileCode2,
      keywords: ['dblib', 'text', 'ini'],
      run: () => onAction('preview'),
    },
    {
      id: 'library.scan',
      title: tr("Bibliotheksdateien prüfen"),
      subtitle: tr("Dateien und Registrierung vergleichen"),
      group: 'Altium',
      icon: FolderSearch,
      keywords: ['scan', 'schlib', 'pcblib'],
      run: () => {
        if (tab !== 'dateien') setTab('dateien')
        void actions.scan(false)
      },
    },
  ])

  // ------------------------------------------------------------------ Ansicht

  const issues = report ? report.counts.error + report.counts.warning : undefined
  const verifyRunning = latestVerify ? isJobActive(latestVerify) : false
  const verifyCount = lastVerify?.summary.checked
  const subtitle = [status?.dblib?.file_name ?? workspace?.settings.dblib_file, model?.altium.short].filter(Boolean).join(' · ')

  return (
    // unten Platz für die Pille des Job-Docks, solange sie zu sehen ist
    <PageBody className="pb-[max(3rem,var(--pf-dock-reserve))]">
      <PageTitle title="Altium" subtitle={subtitle || undefined} />
      <PageActions>
        <IconButton
          label={tr("Status neu laden")}
          icon={<RotateCw />}
          loading={statusQ.isFetching || filesQ.isFetching}
          onClick={() => actions.reload()}
        />
        <Button variant="ghost" leftIcon={<Settings2 />} onClick={() => navigate('/einstellungen#altium')}>
          {tr("Einstellungen")}</Button>
      </PageActions>

      <div className="flex flex-col gap-5">
        <StatusHero
          model={model}
          status={status}
          backend={backend}
          actions={actions}
          onAction={onAction}
          onVerify={(scope) => void startVerify(scope)}
          blocker={blocker}
        />

        <Tabs ref={tabsRef} value={tab} onValueChange={(v) => setTab(v as TabKey)} className="scroll-mt-16">
          <TabsList aria-label={tr("Bereiche")}>
            <TabsTrigger value="pruefbericht" count={issues ? formatNumber(issues) : undefined}>
              {tr("Prüfbericht")}</TabsTrigger>
            <TabsTrigger value="dateien" count={filesQ.data ? formatNumber(filesQ.data.length) : undefined}>
              {tr("Bibliotheksdateien")}</TabsTrigger>
            <TabsTrigger
              value="altium"
              count={verifyRunning ? <Spinner size={10} tone="accent" className="my-[3px]" /> : verifyCount !== undefined ? formatNumber(verifyCount) : undefined}
            >
              {tr("In Altium geprüft")}</TabsTrigger>
            <TabsTrigger value="extern" count={externals.data?.length ? formatNumber(externals.data.length) : undefined}>
              {tr("Externe Bibliotheken")}</TabsTrigger>
          </TabsList>
          {/* Panels enthalten eigene Bedienelemente – kein zusätzlicher (unsichtbarer) Tabstopp */}
          <TabsContent value="pruefbericht" tabIndex={-1} className="pt-4">
            <h2 className="sr-only">{tr("Prüfbericht")}</h2>
            <HealthReport
              report={report}
              loading={health.isLoading}
              fetching={health.isFetching || actions.pending.check}
              error={health.error}
              updatedAt={health.updatedAt}
              actions={actions}
              onRecheck={() => void actions.checkLibrary()}
              focusCheck={focusCheck}
              initialFilter={severityFilter}
              ready={!health.isLoading && !health.isFetching}
            />
          </TabsContent>
          <TabsContent value="dateien" tabIndex={-1} className="pt-4">
            <h2 className="sr-only">{tr("Bibliotheksdateien")}</h2>
            <LibraryFilesPanel
              files={filesQ.data}
              heightsByLibrary={lib?.heightsByLibrary}
              summary={model?.files ?? null}
              loading={filesQ.isPending}
              error={filesQ.error}
              writer={writer}
              actions={actions}
              blocker={blocker}
              onRetry={() => void qc.invalidateQueries({ queryKey: librariesKeys.files })}
            />
          </TabsContent>
          <TabsContent value="altium" tabIndex={-1} className="pt-4">
            <h2 className="sr-only">{tr("In Altium geprüft")}</h2>
            <VerifyPanel blocker={blocker} pending={actions.pending.verify} onVerify={(scope) => void startVerify(scope)} />
          </TabsContent>
          <TabsContent value="extern" tabIndex={-1} className="pt-4">
            <h2 className="sr-only">{tr("Externe Bibliotheken")}</h2>
            <ExternalPanel />
          </TabsContent>
        </Tabs>
      </div>

      <DblibPreviewDialog open={previewOpen} onOpenChange={setPreviewOpen} />
      <OdbcDialog
        jobId={odbc.jobId}
        open={odbc.open}
        onOpenChange={onOdbcOpenChange}
        onRetry={() => void startOdbc()}
        retrying={actions.pending.odbc}
      />
    </PageBody>
  )
}
