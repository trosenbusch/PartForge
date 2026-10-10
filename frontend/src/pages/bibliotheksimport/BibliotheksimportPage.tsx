import { t, useI18n } from '@/lib/i18n'
import { useQueryClient } from '@tanstack/react-query'
import { FolderInput, RotateCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ApiError, cleanErrorText, errorMessage } from '@/api/client'
import { trackJob, useInlineJob, useJob } from '@/api/jobs'
import {
  isScanGone,
  useImportScan,
  useStartLibraryImport,
  useStartLibraryScan,
  type ImportOptions,
  type ImportRunResult,
  type ImportScanSummary,
} from '@/api/libimport'
import { isJobActive, systemKeys, useWorkspace } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { PageBody, PageTitle } from '@/app/page'
import { Button, Callout, Skeleton } from '@/components/ui'
import { baseName, plural } from '@/lib/format'
import { IntroState } from './IntroState'
import { importProblem } from './model'
import { RunView } from './RunView'
import { ScanView } from './ScanView'
import { SOURCE_INPUT_ID, SourceCard } from './SourceCard'
import { useImportSession, useRecentSources } from './store'

const focusSource = () => requestAnimationFrame(() => document.getElementById(SOURCE_INPUT_ID)?.focus())

export default function BibliotheksimportPage() {
  useI18n()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const workspace = useWorkspace().data
  const root = workspace?.root ?? null
  const bases = {
    symbols: workspace?.settings.folders.symbols || 'Symbols',
    footprints: workspace?.settings.folders.footprints || 'Footprints',
  }
  const session = useImportSession()
  const remember = useRecentSources((s) => s.remember)
  const recent = useRecentSources((s) => s.recent)
  const [path, setPath] = useState('')
  const [scanStartError, setScanStartError] = useState<string | null>(null)
  const [runStartError, setRunStartError] = useState<unknown>(null)

  const urlScan = params.get('scan')
  const scanId = urlScan ?? session.scanId

  // Adresse und Sitzung abgleichen: die Adresse geht vor …
  useEffect(() => {
    const s = useImportSession.getState()
    if (urlScan && urlScan !== s.scanId) s.setScan(urlScan)
  }, [urlScan])
  // … ohne `?scan` (Rückkehr über die Navigation) zeigt die Seite den zuletzt angezeigten Scan und schreibt ihn **einmal**
  // in die Adresse (danach gilt die Adresse – „Weitere Quelle importieren“ entfernt beides)
  const restoreScan = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (restoreScan.current !== undefined) return
    const id = urlScan ? null : useImportSession.getState().scanId
    restoreScan.current = id
    if (!id) return
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        if (!n.has('scan')) n.set('scan', id)
        return n
      },
      { replace: true },
    )
  }, [urlScan, setParams])

  // Bibliothek gewechselt → Scan, Einlesen und Import gehören zur alten Bibliothek
  useEffect(() => {
    if (!root) return
    if (useImportSession.getState().syncWorkspace(root)) {
      setParams(
        (p) => {
          const n = new URLSearchParams(p)
          n.delete('scan')
          return n
        },
        { replace: true },
      )
    }
  }, [root, setParams])
  const [pathFor, setPathFor] = useState(root)
  if (root !== pathFor) {
    setPathFor(root)
    if (pathFor && root) setPath('')
  }

  // ------------------------------------------------------------------ Einlesen

  const startScan = useStartLibraryScan()
  const scanJobId = session.scanJobId
  const scanJob = useJob<ImportScanSummary>(scanJobId, {
    onDone: (j) => {
      const r = j.result
      if (!r) return
      remember(r.source, r.id)
      const s = useImportSession.getState()
      if (s.scanJobId === j.id) s.setScanJob(null)
      s.setScan(r.id)
      setParams(
        (p) => {
          const n = new URLSearchParams(p)
          n.set('scan', r.id)
          return n
        },
        { replace: true },
      )
      setPath(r.source)
    },
  })
  // Fortschritt und Ergebnis stehen hier – solange die Seite offen ist, nicht in der Pille und ohne Toast
  useInlineJob(scanJobId)
  const scanJobGone = scanJob.error instanceof ApiError && scanJob.error.isNotFound
  useEffect(() => {
    if (scanJobGone) useImportSession.getState().setScanJob(null)
  }, [scanJobGone])
  const scanning = startScan.isPending || Boolean(scanJob.job && isJobActive(scanJob.job))

  const scanSource = (source: string) => {
    setScanStartError(null)
    setRunStartError(null)
    setPath(source)
    startScan.mutate(source, {
      onSuccess: ({ job }) => {
        trackJob(job, { dock: false, toast: false })
        useImportSession.getState().setScanJob(job.id)
      },
      onError: (err) => setScanStartError(cleanErrorText(errorMessage(err))),
    })
  }

  // ------------------------------------------------------------------ Scan

  const scanQ = useImportScan(scanId)
  const scan = scanQ.data?.id === scanId ? scanQ.data : undefined
  /** Quelle des Scans – auch nach Ablauf (aus der Liste der zuletzt eingelesenen) */
  const knownSource = scan?.source ?? recent.find((r) => r.scanId === scanId)?.path ?? null

  // Pfadfeld mit der Quelle des angezeigten Scans füllen (Neuladen, Rückkehr) – eigene Eingaben bleiben
  const [filledFrom, setFilledFrom] = useState<string | null>(null)
  if (scan && scan.source !== filledFrom) {
    setFilledFrom(scan.source)
    if (!path.trim()) setPath(scan.source)
  }

  // ------------------------------------------------------------------ Import

  const startRun = useStartLibraryImport()
  const run = session.run && session.run.scanId === scanId ? session.run : null
  const runJob = useJob<ImportRunResult>(run?.jobId)
  useInlineJob(run?.jobId)
  const runJobGone = runJob.error instanceof ApiError && runJob.error.isNotFound
  useEffect(() => {
    if (runJobGone) useImportSession.getState().setRun(null)
  }, [runJobGone])
  const running = startRun.isPending || Boolean(runJob.job && isJobActive(runJob.job))

  const startImport = (options: ImportOptions, folder: string) => {
    setRunStartError(null)
    startRun.mutate(options, {
      onSuccess: ({ job }) => {
        // Ergebnis zeigt die Seite; wird sie vorher verlassen, meldet das Job-Dock den Abschluss – mit Befund als Warnung
        trackJob(job, { dock: false, toast: false, warnWhen: (j) => importProblem(j.result) })
        useImportSession.getState().setRun({ jobId: job.id, scanId: options.scan_id, target: folder, convert: options.convert })
      },
      onError: setRunStartError,
    })
  }

  const rescan = knownSource ? () => scanSource(knownSource) : null

  const reset = () => {
    useImportSession.getState().reset()
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        n.delete('scan')
        return n
      },
      { replace: true },
    )
    setPath('')
    setScanStartError(null)
    setRunStartError(null)
    focusSource()
  }

  useRegisterCommands([
    {
      id: 'libimport.source',
      title: t("Andere Quelle einlesen …"),
      subtitle: t("Ordner oder Bibliotheksdatei für den Bibliotheksimport"),
      group: 'Aktionen',
      icon: FolderInput,
      keywords: ['bibliotheksimport', 'schlib', 'pcblib', 'intlib', 'quelle'],
      disabled: () => (running ? t("Erst nach dem laufenden Import") : false),
      run: ({ close }) => {
        close()
        focusSource()
      },
    },
  ])

  // ------------------------------------------------------------------ Ansicht

  const runStartErrorNode = runStartError ? (
    <Callout tone="danger" title={t("Import nicht gestartet")} urgent className="px-3 py-2.5">
      <span className="block">{cleanErrorText(errorMessage(runStartError))}</span>
      {isScanGone(runStartError) && rescan && (
        <Button size="xs" variant="secondary" leftIcon={<RotateCw />} className="mt-2" onClick={rescan}>
          {t("Erneut einlesen")}</Button>
      )}
    </Callout>
  ) : null

  let content
  if (run && scanId) {
    content = (
      <RunView
        run={run}
        job={runJob.job}
        error={runJobGone ? null : runJob.error}
        onRetry={() => void qc.invalidateQueries({ queryKey: systemKeys.job(run.jobId) })}
        onBack={() => useImportSession.getState().setRun(null)}
        onRescan={rescan}
        onReset={reset}
      />
    )
  } else if (scanId && scan) {
    content = (
      <ScanView
        key={scan.id}
        scan={scan}
        bases={bases}
        onStart={startImport}
        starting={startRun.isPending}
        startError={runStartErrorNode}
        blocked={scanning ? t("Es wird gerade eine Quelle eingelesen …") : null}
      />
    )
  } else if (scanId && scanQ.isError) {
    content = isScanGone(scanQ.error) ? (
      <Callout
        tone="warning"
        title={t("Diese Quelle ist nicht mehr eingelesen")}
        actions={
          rescan ? (
            <Button size="sm" leftIcon={<RotateCw />} loading={scanning} onClick={rescan}>
              {t("Erneut einlesen")}</Button>
          ) : undefined
        }
      >
        {knownSource
          ? t("„{0}“ wurde vor einiger Zeit eingelesen – PartForge hält eingelesene Quellen einige Stunden bereit.", { "0": String(baseName(knownSource)) })
          : t("PartForge hält eingelesene Quellen einige Stunden bereit. Bitte die Quelle oben erneut einlesen.")}
      </Callout>
    ) : (
      <Callout
        tone="danger"
        title={t("Die Quelle konnte nicht geladen werden")}
        urgent
        actions={
          <Button size="sm" leftIcon={<RotateCw />} onClick={() => void scanQ.refetch()}>
            {t("Erneut versuchen")}</Button>
        }
      >
        {cleanErrorText(errorMessage(scanQ.error))}
      </Callout>
    )
  } else if (scanId) {
    content = <ScanSkeleton />
  } else {
    content = (
      <IntroState
        folders={bases}
        onPicked={(picked) => scanSource(picked)}
        onFocusInput={focusSource}
      />
    )
  }

  const subtitle = scan
    ? `${scan.name} · ${plural(scan.files.length, t("Datei"), t("Dateien"))}`
    : t("Symbole und Footprints aus Altium-Bibliotheken übernehmen")

  return (
    // unten Platz für die Pille des Job-Docks, solange sie zu sehen ist
    <PageBody className="pb-[max(3rem,var(--pf-dock-reserve))]">
      <PageTitle title={t("Bibliotheksimport")} subtitle={subtitle} />
      <div className="flex flex-col gap-5">
        <SourceCard
          path={path}
          onPathChange={(v) => {
            setPath(v)
            // neue Eingabe: Fehler bzw. Abbruch des letzten Einlesens ausblenden
            if (scanStartError) setScanStartError(null)
            if (scanJob.job && !isJobActive(scanJob.job) && useImportSession.getState().scanJobId) {
              useImportSession.getState().setScanJob(null)
            }
          }}
          onScan={scanSource}
          starting={startScan.isPending}
          job={scanJob.job}
          startError={scanStartError}
          onDismiss={() => {
            setScanStartError(null)
            const s = useImportSession.getState()
            if (s.scanJobId && scanJob.job && !isJobActive(scanJob.job)) s.setScanJob(null)
          }}
          currentSource={scan?.source ?? null}
          locked={running ? t("Während des Imports gesperrt – danach lässt sich eine weitere Quelle einlesen.") : null}
          primary={!scan && !run}
        />
        {content}
      </div>
    </PageBody>
  )
}

function ScanSkeleton() {
  useI18n()
  return (
    <div className="flex flex-col gap-4" aria-busy="true" aria-label={t("Quelle wird geladen")}>
      <Skeleton className="h-[7.25rem] rounded-card" />
      <div className="grid grid-cols-[minmax(0,1fr)_18rem] gap-4 @[76rem]:grid-cols-[minmax(0,1fr)_22rem]">
        <Skeleton className="h-[32rem] rounded-card" />
        <div className="flex flex-col gap-4">
          <Skeleton className="h-[26rem] rounded-card" />
          <Skeleton className="h-[16rem] rounded-card" />
        </div>
      </div>
    </div>
  )
}
