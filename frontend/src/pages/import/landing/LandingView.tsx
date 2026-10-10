import { t, useI18n } from '@/lib/i18n'
import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { datasheetKeys, useDatasheets, type DatasheetSummary } from '@/api/datasheets'
import { useJob } from '@/api/jobs'
import { isJobActive, useLibraryJobs, type Job } from '@/api/system'
import { PageBody, PageTitle } from '@/app/page'
import { FileDropZone } from '@/components/data'
import { plural } from '@/lib/format'
import { SETTINGS_PLACE } from '@/pages/altium/settingsPlaces'
import { formatUsd } from '../lib/format'
import type { useImportActions } from '../lib/useImportActions'
import { ReanalyzeDialog, type ReanalyzeTarget } from '../shared/ReanalyzeDialog'
import { useActiveImports, type UrlImport } from '../store'
import { AiCard } from './AiCard'
import { DatasheetList } from './DatasheetList'
import { DatasheetSearch } from './DatasheetSearch'
import { UrlImport as UrlImportForm } from './UrlImport'

type Actions = ReturnType<typeof useImportActions>

/** Live-Zustand eines URL-Imports (eigene Komponente je Job – Hooks nicht in Schleifen) */
function useUrlJobs(entries: UrlImport[]): { entry: UrlImport; job: Job | undefined }[] {
  // nur Importe der geöffneten Bibliothek – die einer anderen Bibliothek gehören nicht auf diese Seite
  const jobs = useLibraryJobs('datasheet').data
  return entries.map((entry) => ({ entry, job: jobs?.find((j) => j.id === entry.jobId) }))
}

export interface LandingViewProps {
  actions: Actions
  /** Neuer Wert → URL-Feld fokussieren (Befehl „Datenblatt aus URL laden“) */
  focusUrl?: string | null
  /** Neuer Wert → Suchfeld fokussieren (Befehl „Datenblatt suchen …“) */
  focusSearch?: string | null
  /** Vorbelegung der Suche (`/import?suche=OPA656`) */
  searchQuery?: string | null
}

/**
 * Einstieg: Datenblatt suchen (KI), PDF ablegen (kleiner, sobald es Datenblätter gibt – die Liste bleibt sichtbar),
 * URL-Import, KI-Status und die bisherigen Datenblätter.
 */
export function LandingView({ actions, focusUrl = null, focusSearch = null, searchQuery = null }: LandingViewProps) {
  useI18n()
  const list = useDatasheets()
  const activeMap = useActiveImports((s) => s.jobs)
  const urlEntries = useActiveImports((s) => s.urls)
  const jobs = useLibraryJobs('datasheet').data
  const urlJobs = useUrlJobs(urlEntries)
  // beendete URL-Importe ausblenden (die Liste zeigt dann das Datenblatt selbst)
  const visibleUrlJobs = urlJobs.filter(({ job }) => !job || isJobActive(job))

  const active = useMemo(() => {
    const out: Record<string, Job | undefined> = {}
    for (const [dsId, jobId] of Object.entries(activeMap)) out[dsId] = jobs?.find((j) => j.id === jobId)
    return out
  }, [activeMap, jobs])

  const stats = useMemo(() => {
    const items = list.data ?? []
    return {
      total: items.length,
      analyzed: items.filter((d) => d.has_extraction).length,
      committed: items.filter((d) => d.status === 'übernommen').length,
      costUsd: items.reduce((sum, d) => sum + d.cost_usd, 0),
    }
  }, [list.data])

  const subtitle = list.data
    ? stats.total
      ? t("{0} · {1} · Kosten {2}", { "0": String(plural(stats.total, t("Datenblatt"), t("Datenblätter"))), "1": String(plural(stats.committed, 'übernommen', 'übernommen')), "2": String(formatUsd(stats.costUsd)) })
      : t("Teilenummer suchen oder PDF ablegen – Claude schlägt das Bauteil vor")
    : undefined

  const aiReady = actions.aiReady
  const status = actions.aiStatus
  const aiOff = status?.enabled === false
  // Sobald es Datenblätter gibt, wird die Drop-Zone eine kompakte Zeile – die Liste bleibt auch bei 720 px im Blick
  // (PDFs lassen sich ohnehin überall ins Fenster ziehen).
  const hasList = stats.total > 0 || visibleUrlJobs.length > 0
  // KI-Stil nur, wenn die KI wirklich analysiert; sonst neutral (die Drop-Zone verspricht dann keine Analyse)
  const tone = status ? (aiReady ? 'ai' : 'neutral') : 'auto'

  // „Neu analysieren …“ aus der Liste: erst der Dialog (Seiten, Modell, erwartete Kosten) – nie ein Klick = bezahlt
  const [target, setTarget] = useState<ReanalyzeTarget | null>(null)
  const [dialogOpen, setDialogOpen] = useState(false)
  const askReanalyze = (d: DatasheetSummary) => {
    setTarget({
      id: d.id,
      name: d.original_name,
      pageCount: d.page_count,
      costUsd: d.cost_usd,
      edited: d.edited,
      hasExtraction: d.has_extraction,
      selectedPages: null,
    })
    setDialogOpen(true)
  }

  return (
    <PageBody width="wide">
      <PageTitle title={t("Datenblatt-Import")} subtitle={subtitle} />
      <WatchFinished active={activeMap} />
      {/* items-start: Suchergebnisse verlängern nur die linke Spalte, die KI-Karte bleibt kompakt */}
      <div className="grid items-start gap-5 @[46rem]:grid-cols-[minmax(0,1fr)_17.5rem] @[64rem]:grid-cols-[minmax(0,1fr)_21rem]">
        <section aria-label={t("Datenblatt hinzufügen")} className="@container flex min-w-0 flex-col gap-4">
          <DatasheetSearch
            aiReady={aiReady}
            aiStatus={status}
            aiLoading={actions.aiLoading}
            focusKey={focusSearch}
            initialQuery={searchQuery}
            known={list.data ?? []}
            importing={Boolean(actions.busy?.startsWith('Download'))}
            onImport={(url, searchJobId) => actions.startUrl(url, { searchJobId })}
          />
          <FileDropZone
            variant="pdf"
            tone={tone}
            size={hasList ? 'sm' : 'lg'}
            onFiles={(files) => void actions.startFiles(files)}
            busy={actions.busy ?? false}
            disabled={actions.aiLoading}
            maxSize={64 * 1024 * 1024}
            title={hasList ? t("PDF hierher ziehen") : t("Datenblatt hierher ziehen")}
            description={
              aiReady || !status
                ? t("Claude liest Bestellnummern, Parameter, Pinbelegung und Gehäusemaße. Sie prüfen jede Angabe mit Fundstelle und legen Bauteile, Symbol und Footprint in einem Schritt an.")
                : aiOff
                  ? t("Die KI-Analyse ist ausgeschaltet – das PDF wird nur gespeichert. Eingeschaltet ({0}) lässt sich die Analyse jederzeit nachholen.", { "0": String(SETTINGS_PLACE.ai.label) })
                  : t("Ohne Claude-API-Schlüssel wird das PDF nur gespeichert – die Analyse lässt sich jederzeit nachholen.")
            }
            hint={
              aiReady || !status
                ? hasList
                  ? t("PDF · bis 64 MB · mehrere möglich")
                  : undefined
                : t("PDF · bis 64 MB · wird nur gespeichert")
            }
            className={hasList ? undefined : '[&>[role=button]]:min-h-[15rem]'}
          />
          <UrlImportForm
            onSubmit={(url) => actions.startUrl(url)}
            aiReady={aiReady}
            busy={Boolean(actions.busy?.startsWith('Download'))}
            focusKey={focusUrl}
          />
        </section>
        <AiCard status={status} loading={actions.aiLoading} stats={stats} compact={hasList} />
      </div>

      <div className="mt-6">
        <DatasheetList
          items={list.data}
          loading={list.isLoading}
          active={active}
          urlJobs={visibleUrlJobs}
          aiReady={aiReady}
          onReanalyze={askReanalyze}
        />
      </div>
      <ReanalyzeDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        target={target}
        onStart={(o) => (target ? actions.reanalyze(target.id, o) : Promise.resolve(false))}
      />
    </PageBody>
  )
}

/** Beendete Analysen aus der Liste der laufenden entfernen (eine Komponente je Job: SSE/Polling über useJob). */
function WatchFinished({ active }: { active: Record<string, string> }) {
  useI18n()
  return (
    <>
      {Object.entries(active).map(([dsId, jobId]) => (
        <WatchJob key={jobId} datasheetId={dsId} jobId={jobId} />
      ))}
    </>
  )
}

function WatchJob({ datasheetId, jobId }: { datasheetId: string; jobId: string }) {
  const finish = useActiveImports((s) => s.finish)
  const qc = useQueryClient()
  // nach einem Fehlschlag/Abbruch lädt nichts von selbst neu (nur nach Erfolg) – Status „Fehlgeschlagen“ und Kosten holen
  const settle = () => {
    finish(datasheetId, jobId)
    void qc.invalidateQueries({ queryKey: datasheetKeys.list })
    void qc.invalidateQueries({ queryKey: datasheetKeys.detail(datasheetId) })
  }
  useJob(jobId, { onDone: () => finish(datasheetId, jobId), onFailed: settle, onCancelled: settle })
  return null
}
