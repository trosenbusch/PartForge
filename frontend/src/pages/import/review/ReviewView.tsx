import { ExternalLink, FileScan, MoreHorizontal, RotateCcw, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import {
  useAiStatus,
  useDeleteDatasheet,
  useExtraction,
  useProposal,
  type DatasheetDetail,
  type DeviceData,
  type PackageData,
} from '@/api/datasheets'
import { useCategories } from '@/api/library'
import { useRegisterCommands } from '@/app/commands'
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { SplitPane } from '@/components/data'
import { useElementSize } from '@/components/preview'
import {
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  IconButton,
  Skeleton,
} from '@/components/ui'
import { formatRelativeTime, plural } from '@/lib/format'
import { openPdf } from '../lib/openPdf'
import { useImportActions } from '../lib/useImportActions'
import { CostChip } from '../shared/CostChip'
import { ReanalyzeDialog, type ReanalyzeTarget } from '../shared/ReanalyzeDialog'
import { useDebounced } from '../shared/useDebounced'
import { EMPTY_CHOICES, toProposalChoices, useReviewDraft, useReviewDrafts, useReviewUi, type ChoiceDraft } from '../store'
import { CommitBar, type CommitGate } from './CommitBar'
import { ReviewContext, type ReviewContextValue } from './context'
import { DataColumn } from './DataColumn'
import { NotAnalyzedPanel } from './NotAnalyzedPanel'
import { PageOverlay } from './PageOverlay'
import { PdfColumn } from './PdfColumn'
import { PreviewColumn } from './PreviewColumn'
import { readiness } from './readiness'
import { useExtractionEditor } from './useExtractionEditor'

/** Mindestbreite der Datenspalte (Tabelle der Bestellvarianten: Auswahl, Nummer, Status, Gehäuse, Fundstelle) */
const DATA_MIN = 384
const PREVIEW_MIN = 260
/** Unter dieser Arbeitsbreite (≈ Fenster unter 1 280 px) startet die PDF-Spalte eingeklappt */
const PDF_AUTO_COLLAPSE = 1024

/** Entscheidungen eines unbekannten Bauteils (z. B. nach neuer Analyse) gelten nicht mehr */
function effectiveChoices(c: ChoiceDraft, devices: readonly { base_part: string }[] | undefined): ChoiceDraft {
  const known = !c.device || Boolean(devices?.some((d) => d.base_part === c.device))
  return known ? c : { ...c, device: null, variants: null }
}

/** Zeichnung mit Maßen oder Herstellerempfehlung (wie `PackageData.has_geometry` im Backend) */
function hasGeometry(p: PackageData): boolean {
  return p.land_pattern.present || p.dimensions.some((d) => d.unit === 'mm' && (d.nom ?? d.min ?? d.max) !== null)
}

/** Gehäusezeichnung ohne Bauteil: die Abschnitte arbeiten mit einem leeren Bauteil (keine Pins, Varianten, Werte) */
const NO_DEVICE: DeviceData = {
  base_part: '',
  description: '',
  category: null,
  category_raw: '',
  parameters: [],
  variants: [],
  pin_tables: [],
}

/** Prüfansicht (drei Spalten): PDF-Seiten · extrahierte Daten · Live-Vorschau, darunter die Übernahmeleiste. */
export function ReviewView({ ds }: { ds: DatasheetDetail }) {
  const navigate = useNavigate()
  const ai = useAiStatus().data
  const actions = useImportActions()
  const extractionQ = useExtraction(ds.id, { enabled: ds.has_extraction })
  const draft = useReviewDraft(ds.id)
  const setChoicesFor = useReviewDrafts((s) => s.setChoices)
  const updateDraft = useReviewDrafts((s) => s.update)
  const resetDraft = useReviewDrafts((s) => s.reset)
  const categoriesQ = useCategories()
  const edit = useExtractionEditor(ds.id)
  const remove = useDeleteDatasheet()
  const [reanalyzeOpen, setReanalyzeOpen] = useState(false)

  const extractionOut = extractionQ.data
  const extraction = extractionOut?.extraction
  const devices = extraction?.devices
  const choices = useMemo(() => effectiveChoices(draft.choices, devices), [draft.choices, devices])
  const proposalChoices = useMemo(() => toProposalChoices(choices), [choices])
  const debounced = useDebounced(proposalChoices, 250)
  const hasDevices = Boolean(extraction?.devices.length)
  // Gehäusezeichnung (z. B. TIs eigenes PDF zu RGY0019B): kein Bauteil, aber Maße – nur Footprints
  const packageOnly = Boolean(extraction && !hasDevices && extraction.packages.some(hasGeometry))
  const proposalQ = useProposal(ds.id, debounced, { enabled: Boolean(extraction) && (hasDevices || packageOnly) })

  // Spaltenaufteilung: PDF-Spalte im schmalen Fenster eingeklappt (bis der Benutzer selbst wählt)
  const [workspaceRef, workspaceSize] = useElementSize<HTMLDivElement>()
  const pdfPref = useReviewUi((s) => s.pdfCollapsed)
  const previewCollapsed = useReviewUi((s) => s.previewCollapsed)
  const narrow = workspaceSize.width > 0 ? workspaceSize.width < PDF_AUTO_COLLAPSE : window.innerWidth < 1280
  const pdfCollapsed = pdfPref ?? narrow

  useEffect(() => {
    useReviewUi.getState().open(ds.id, ds.selected_pages[0] ?? 1)
  }, [ds.id, ds.selected_pages])

  const proposal = proposalQ.data
  const categories = useMemo(() => categoriesQ.data ?? [], [categoriesQ.data])
  const deviceName = choices.device ?? proposal?.device ?? extraction?.devices[0]?.base_part
  const deviceIndex = Math.max(0, extraction?.devices.findIndex((d) => d.base_part === deviceName) ?? 0)
  const device = extraction?.devices[deviceIndex] ?? (packageOnly ? NO_DEVICE : undefined)
  const categoryTable = choices.category ?? proposal?.category ?? device?.category ?? null
  const category = categories.find((c) => c.table === categoryTable)
  const codes = useMemo(() => proposal?.footprints.map((f) => f.package) ?? [], [proposal])
  const state = readiness(proposal, choices, draft.acknowledged)

  const target: ReanalyzeTarget = {
    id: ds.id,
    name: ds.original_name,
    pageCount: ds.page_count,
    costUsd: ds.cost_usd,
    edited: ds.edited,
    hasExtraction: ds.has_extraction,
    selectedPages: ds.selected_pages,
  }

  const askDelete = async () => {
    const ok = await confirm({
      title: `„${(ds.has_extraction && ds.title) || ds.original_name}“ löschen?`,
      description: 'Eintrag, Analyse und Seitenbilder werden entfernt. Angelegte Bauteile bleiben unverändert, ihre PDF-Verknüpfung bleibt erhalten.',
      confirmLabel: 'Löschen',
      destructive: true,
      onConfirm: () => remove.mutateAsync({ id: ds.id }),
    })
    if (ok) {
      resetDraft(ds.id)
      toast.success('Datenblatt gelöscht', { description: ds.original_name })
      navigate('/import', { replace: true })
    }
  }

  useRegisterCommands([
    {
      id: 'import.reanalyze',
      title: 'Datenblatt neu analysieren …',
      subtitle: ds.original_name,
      group: 'Aktionen',
      icon: FileScan,
      ai: true,
      when: () => actions.aiReady,
      run: () => setReanalyzeOpen(true),
    },
    { id: 'import.pdf', title: 'PDF des Datenblatts öffnen', group: 'Aktionen', icon: ExternalLink, run: () => void openPdf(ds) },
  ])

  const title = device?.base_part || (ds.has_extraction && ds.title) || ds.original_name
  const subtitle = [
    packageOnly ? 'Gehäusezeichnung' : null,
    extraction?.manufacturer || ds.manufacturer,
    ds.original_name,
    plural(ds.page_count, 'Seite', 'Seiten'),
    ds.extracted ? `analysiert ${formatRelativeTime(ds.extracted)}` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const topbar = (
    <>
      <PageTitle title={title} subtitle={subtitle} />
      <PageActions>
        {ds.cost_usd > 0 || ds.runs.length ? (
          <CostChip costUsd={ds.cost_usd} runs={ds.runs} budgetUsd={ai?.max_cost_per_import_usd} />
        ) : null}
        {ds.has_extraction && (
          <Button variant="spark" leftIcon={<FileScan />} disabled={!actions.aiReady} onClick={() => setReanalyzeOpen(true)}>
            Neu analysieren
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <IconButton label="Weitere Aktionen" icon={<MoreHorizontal />} tooltip={false} />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-56">
            <DropdownMenuItem icon={<ExternalLink />} onSelect={() => void openPdf(ds)}>
              PDF öffnen
            </DropdownMenuItem>
            <DropdownMenuItem
              icon={<RotateCcw />}
              disabled={!ds.has_extraction}
              description="Kategorie, Auswahl, Werte und Footprint-Wahl"
              onSelect={() => {
                resetDraft(ds.id)
                toast.info('Entscheidungen zurückgesetzt', { description: 'Es gilt wieder der Vorschlag von Claude.' })
              }}
            >
              Entscheidungen zurücksetzen
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem icon={<Trash2 />} destructive onSelect={() => void askDelete()}>
              Datenblatt löschen …
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </PageActions>
      <ReanalyzeDialog open={reanalyzeOpen} onOpenChange={setReanalyzeOpen} target={target} onStart={(o) => actions.reanalyze(ds.id, o)} />
    </>
  )

  // Noch nicht analysiert (z. B. ohne Schlüssel gespeichert) bzw. Analyse fehlgeschlagen
  if (!ds.has_extraction) {
    return (
      <Workspace>
        {topbar}
        <SplitPane
          persistKey="import.seiten-leer"
          primary="end"
          defaultSize={460}
          minSize={360}
          maxSize={720}
          minRest={260}
          label="Breite des Hinweises"
          start={<PdfColumn ds={ds} />}
          end={<NotAnalyzedPanel ds={ds} aiReady={actions.aiReady} aiStatus={ai} onAnalyze={() => setReanalyzeOpen(true)} />}
          className="min-h-0 flex-1"
        />
        <PageOverlay ds={ds} />
      </Workspace>
    )
  }

  if (extractionQ.isError) {
    return (
      <Workspace>
        {topbar}
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            illustration="offline"
            titleAs="h2"
            title="Analyse konnte nicht geladen werden"
            description={errorMessage(extractionQ.error)}
            actions={
              <Button variant="secondary" onClick={() => void extractionQ.refetch()}>
                Erneut versuchen
              </Button>
            }
          />
        </div>
      </Workspace>
    )
  }

  if (!extractionOut || !extraction) {
    return (
      <Workspace>
        {topbar}
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(12rem,18rem)_minmax(0,1fr)_minmax(16rem,26rem)] gap-px bg-line" aria-busy>
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex flex-col gap-3 bg-bg p-4">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-40 w-full rounded-card" />
              <Skeleton className="h-24 w-full rounded-card" />
            </div>
          ))}
        </div>
      </Workspace>
    )
  }

  if (!device) {
    return (
      <Workspace>
        {topbar}
        <SplitPane
          persistKey="import.seiten-leer"
          primary="end"
          defaultSize={460}
          minSize={360}
          maxSize={720}
          minRest={260}
          label="Breite des Hinweises"
          start={<PdfColumn ds={ds} extraction={extraction} />}
          end={
            <div className="flex h-full items-center justify-center bg-bg p-6">
              <EmptyState
                illustration="search-empty"
                titleAs="h2"
                title="Kein Bauteil erkannt"
                description="Claude hat in den gelesenen Seiten kein bestellbares Bauteil gefunden. Am besten die Seiten mit Pinbelegung und Bestellangaben selbst auswählen und erneut analysieren."
                actions={
                  <Button variant="spark" leftIcon={<FileScan />} disabled={!actions.aiReady} onClick={() => setReanalyzeOpen(true)}>
                    Seiten wählen und analysieren
                  </Button>
                }
              />
            </div>
          }
          className="min-h-0 flex-1"
        />
        <PageOverlay ds={ds} extraction={extraction} />
      </Workspace>
    )
  }

  // Angelegt wird nur, was zu sehen ist: Vorschlag genau zu den aktuellen Entscheidungen, geladen, keine Korrektur offen
  const gate: CommitGate = {
    synced:
      JSON.stringify(proposalChoices) === JSON.stringify(debounced) &&
      proposalQ.isSuccess &&
      !proposalQ.isPlaceholderData &&
      !proposalQ.isFetching &&
      !edit.saving,
    choices: debounced,
    readCurrent: () =>
      JSON.stringify(toProposalChoices(effectiveChoices(useReviewDrafts.getState().drafts[ds.id]?.choices ?? EMPTY_CHOICES, devices))),
    failed: proposalQ.isError && !proposalQ.isFetching,
  }

  const ctx: ReviewContextValue = {
    ds,
    extractionOut,
    extraction,
    device,
    deviceIndex,
    packageOnly,
    proposal,
    proposalFetching: proposalQ.isFetching,
    proposalError: proposalQ.error,
    choices,
    setChoices: (change) => setChoicesFor(ds.id, change),
    acknowledged: draft.acknowledged,
    setAcknowledged: (list) => updateDraft(ds.id, (d) => ({ ...d, acknowledged: list })),
    categories,
    category,
    edit,
    codes,
    packageOf: (code) => extraction.packages.find((p) => p.code === code),
  }

  return (
    <ReviewContext.Provider value={ctx}>
      <Workspace>
        {topbar}
        <div ref={workspaceRef} className="flex min-h-0 flex-1">
          <SplitPane
            persistKey="import.seiten"
            primary="start"
            defaultSize={320}
            minSize={220}
            maxSize={760}
            minRest={DATA_MIN + 1 + (previewCollapsed ? 0 : PREVIEW_MIN)}
            collapsible
            collapsed={pdfCollapsed}
            onCollapsedChange={(c) => useReviewUi.getState().setPdfCollapsed(c)}
            label="Breite der PDF-Seiten"
            start={<PdfColumn ds={ds} extraction={extraction} device={device} onCollapse={() => useReviewUi.getState().setPdfCollapsed(true)} />}
            end={
              // Die Datenspalte bekommt den Rest (mindestens 384 px), die Vorschau hat eine feste, einklappbare Breite.
              <SplitPane
                persistKey="import.vorschau"
                primary="end"
                defaultSize={380}
                minSize={PREVIEW_MIN}
                maxSize={760}
                minRest={DATA_MIN}
                collapsible
                collapsed={previewCollapsed}
                onCollapsedChange={(c) => useReviewUi.getState().setPreviewCollapsed(c)}
                label="Breite der Vorschau"
                start={<DataColumn state={state} pdfCollapsed={pdfCollapsed} />}
                end={<PreviewColumn />}
                className="h-full"
              />
            }
            className="min-h-0 min-w-0 flex-1"
          />
        </div>
        <CommitBar state={state} gate={gate} />
        <PageOverlay ds={ds} extraction={extraction} device={device} />
      </Workspace>
    </ReviewContext.Provider>
  )
}

/** Vollflächiger Arbeitsbereich unter der Topbar (kein Seiten-Scroll – die Spalten scrollen selbst). */
function Workspace({ children }: { children: ReactNode }) {
  return (
    <PageBody width="full" flush className="flex h-[calc(100dvh-var(--pf-topbar-height,3.5rem))] min-h-[36rem] flex-col border-t border-line">
      {children}
    </PageBody>
  )
}
