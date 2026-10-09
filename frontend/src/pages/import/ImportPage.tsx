/**
 * Modul „Datenblatt-Import“ (/import): Teilenummer suchen (Claude findet das PDF im Web), PDF ablegen oder per
 * Web-Adresse laden → Claude analysiert (Job mit Live-Schritten und Kosten) → Prüfansicht in drei Spalten (PDF-Seiten ·
 * extrahierte Daten · Live-Vorschau) → „Bauteile anlegen“ (Job) → Ergebnis mit Links zu den neuen Bauteilen.
 *
 * Adressen: `/import` (Übersicht) · `/import?suche=1` bzw. `?suche=<Teilenummer>` (Suchfeld fokussieren/vorbelegen –
 * gesucht wird erst auf Knopfdruck) · `/import?url=1` (URL-Feld) · `/import?ds=<id>` (Prüfansicht) ·
 * `/import?ds=<id>&job=<job>` (laufende Analyse) · `/import?job=<job>` (URL-Import, Datenblatt noch unbekannt) ·
 * `/import?ds=<id>&ansicht=ergebnis`.
 * Per Drag & Drop ins Fenster gezogene PDFs (globales Overlay → `useDroppedFiles`): ein einzelnes neues PDF wird
 * sofort analysiert, mehrere werden gespeichert und erst nach Rückfrage (mit erwarteten Kosten) analysiert.
 */
import { ArrowLeft, FileScan, Globe, Search } from 'lucide-react'
import { useEffect } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router'
import { ApiError } from '@/api/client'
import { useDatasheet } from '@/api/datasheets'
import { useJob } from '@/api/jobs'
import { isJobOfLibrary, useWorkspace } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { PageBody, PageTitle } from '@/app/page'
import { useDroppedFiles } from '@/app/stores'
import { Button, EmptyState, Skeleton } from '@/components/ui'
import { AnalysisView } from './analysis/AnalysisView'
import { LandingView } from './landing/LandingView'
import { useImportActions } from './lib/useImportActions'
import { ResultView } from './result/ResultView'
import { ReviewView } from './review/ReviewView'
import { BatchAnalyzeDialog } from './shared/BatchAnalyzeDialog'
import { useActiveImports } from './store'

export default function ImportPage() {
  const [params] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const actions = useImportActions()
  const { aiLoading, startFiles } = actions
  const datasheetId = params.get('ds')
  const jobId = params.get('job')
  const view = params.get('ansicht')

  // Übergabe vom globalen Drop-Overlay: erst starten, wenn der KI-Status bekannt ist (sonst ohne Analyse)
  const dropped = useDroppedFiles((s) => s.files)
  useEffect(() => {
    if (!dropped.length || aiLoading) return
    const taken = useDroppedFiles.getState().take()
    if (taken.length) void startFiles(taken.map((f) => f.file))
  }, [dropped, aiLoading, startFiles])

  useRegisterCommands([
    {
      id: 'import.overview',
      title: 'Datenblatt-Übersicht',
      group: 'Navigation',
      icon: FileScan,
      run: () => navigate('/import'),
      when: () => Boolean(datasheetId || jobId),
    },
    {
      id: 'import.find',
      title: 'Datenblatt suchen …',
      subtitle: 'Claude sucht das PDF zur Teilenummer im Web',
      group: 'Aktionen',
      icon: Search,
      ai: true,
      keywords: ['teilenummer', 'suche', 'web', 'internet', 'pdf finden', 'hersteller', 'claude'],
      run: () => navigate('/import?suche=1'),
    },
    {
      id: 'import.url',
      title: 'Datenblatt aus URL laden',
      group: 'Aktionen',
      icon: Globe,
      ai: true,
      run: () => navigate('/import?url=1'),
    },
  ])

  // Fokus-Wünsche (Befehle): je Aufruf ein neuer Schlüssel, auch wenn die Adresse gleich bleibt
  const search = params.get('suche')
  const focusSearch = search !== null ? location.key : null
  const searchQuery = search && search !== '1' ? search : null
  const focusUrl = params.get('url') === '1' ? location.key : null

  const content =
    jobId && !datasheetId ? (
      <AnalysisView key={jobId} jobId={jobId} datasheetId={null} />
    ) : datasheetId ? (
      <DatasheetRoute key={datasheetId} id={datasheetId} jobId={jobId} view={view} />
    ) : (
      <LandingView actions={actions} focusUrl={focusUrl} focusSearch={focusSearch} searchQuery={searchQuery} />
    )
  return (
    <>
      {content}
      {/* mehrere abgelegte PDFs: erst fragen, dann (bezahlt) analysieren */}
      <BatchAnalyzeDialog onAnalyze={actions.analyzeBatch} />
    </>
  )
}

function DatasheetRoute({ id, jobId, view }: { id: string; jobId: string | null; view: string | null }) {
  const ds = useDatasheet(id)
  const activeJob = useActiveImports((s) => s.jobs[id])
  const watched = useJob(jobId ? null : activeJob)
  const root = useWorkspace().data?.root ?? null
  // eine Analyse, die für eine andere Bibliothek läuft (gleiches PDF dort), gehört nicht in diese Ansicht
  const foreign = Boolean(watched.job && !isJobOfLibrary(watched.job, root))

  if (jobId) return <AnalysisView key={jobId} jobId={jobId} datasheetId={id} />
  // laufende Analyse dieses Datenblatts (auch solange ihr Zustand noch geladen wird – kein Aufblitzen der Prüfansicht)
  if (activeJob && !foreign && (watched.isActive || (!watched.job && !watched.error))) {
    return <AnalysisView key={activeJob} jobId={activeJob} datasheetId={id} />
  }

  if (ds.isError) {
    const missing = ds.error instanceof ApiError && ds.error.isNotFound
    return (
      <PageBody width="narrow">
        <PageTitle title="Datenblatt" />
        <EmptyState
          illustration={missing ? 'search-empty' : 'offline'}
          titleAs="h2"
          title={missing ? 'Datenblatt nicht gefunden' : 'Datenblatt konnte nicht geladen werden'}
          description={missing ? 'Es wurde gelöscht oder gehört zu einer anderen Bibliothek.' : ds.error.message}
          actions={
            <Button asChild variant="secondary">
              <Link to="/import">
                <ArrowLeft aria-hidden />Zur Übersicht
              </Link>
            </Button>
          }
        />
      </PageBody>
    )
  }
  if (!ds.data) {
    return (
      <PageBody width="full" flush className="flex h-[calc(100dvh-var(--pf-topbar-height,3.5rem))] flex-col border-t border-line">
        <PageTitle title="Datenblatt" />
        <div className="grid min-h-0 flex-1 grid-cols-[18rem_minmax(0,1fr)_24rem] gap-px bg-line" aria-busy aria-label="Wird geladen">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-3 bg-bg p-4">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-48 w-full rounded-card" />
              <Skeleton className="h-24 w-full rounded-card" />
            </div>
          ))}
        </div>
      </PageBody>
    )
  }
  if (view === 'ergebnis') return <ResultView ds={ds.data} />
  return <ReviewView ds={ds.data} />
}
