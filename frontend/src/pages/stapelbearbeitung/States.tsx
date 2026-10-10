import { useI18n } from '@/lib/i18n'
import { FolderInput, RefreshCw, ScanSearch } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { cleanErrorText } from '@/api/client'
import type { ConformReport } from '@/api/housestyle'
import { jobCancelText } from '@/api/jobs'
import { isLibrarySwitchCancel, type Job } from '@/api/system'
import { Button, Callout, Card, EmptyState, Skeleton } from '@/components/ui'
import type { RunState } from './useBatchJobs'

interface CheckActionProps {
  onCheck: () => void
  /** Grund, warum gerade nicht geprüft werden kann (`null` = möglich) */
  checkBlocked: string | null
  checkPending: boolean
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  useI18n()
  return (
    <li className="flex items-start gap-2.5">
      <span
        aria-hidden
        className="mono flex size-6 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface-2 text-2xs font-semibold text-fg-muted"
      >
        {n}
      </span>
      <span className="min-w-0">
        <span className="block text-ui font-medium text-fg">{title}</span>
        <span className="block text-xs leading-snug text-fg-muted">{children}</span>
      </span>
    </li>
  )
}

/** Noch keine Prüfung: was die Stapelbearbeitung tut und wie (`actions: false` – die Knöpfe stehen schon darüber) */
export function IntroState({
  onCheck,
  checkBlocked,
  checkPending,
  actions = true,
}: CheckActionProps & { actions?: boolean }) {
  const { t: tr } = useI18n()
  return (
    <Card className="@container">
      <EmptyState
        illustration="forge"
        titleAs="h2"
        title={tr("Symbole und Footprints an den Hausstil angleichen")}
        description={tr("Bringt registrierte Symbole und Footprints – etwa aus übernommenen Hersteller- oder Celestial-Bibliotheken – in einem Arbeitsgang auf den Hausstil: Schriften, Pinlängen, Bezeichner, Lagen, Linienbreiten und Texte.")}
        actions={
          actions && (
            <>
              <Button
                size="sm"
                leftIcon={<ScanSearch />}
                onClick={onCheck}
                disabled={Boolean(checkBlocked)}
                loading={checkPending}
              >
                {tr("Prüfen")}</Button>
              <Button asChild size="sm" variant="ghost">
                <Link to="/bibliotheksimport">
                  <FolderInput aria-hidden />
                  {tr("Bibliotheksimport")}</Link>
              </Button>
            </>
          )
        }
      >
        <ol className="grid w-full max-w-2xl gap-3 pt-1 text-left @[38rem]:grid-cols-3" aria-label={tr("Ablauf")}>
          <Step n={1} title={tr("Auswählen")}>
            {tr("Art, Herkunft, Bibliotheken und Regeln links festlegen.")}</Step>
          <Step n={2} title={tr("Prüfen")}>
            {tr("Zeigt je Bauteil, was sich ändern würde – geändert wird dabei nichts.")}</Step>
          <Step n={3} title={tr("Anwenden")}>
            {tr("Verlustfrei: Namen bleiben, jede Datei wird vorher gesichert, Rückgängig ist möglich.")}</Step>
        </ol>
        {actions && checkBlocked && <p className="text-xs text-warning-text">{checkBlocked}</p>}
      </EmptyState>
    </Card>
  )
}

/** Die Bibliothek hat (noch) keine registrierten Symbole oder Footprints */
export function NoComponentsState() {
  const { t: tr } = useI18n()
  return (
    <Card>
      <EmptyState
        illustration="no-parts"
        titleAs="h2"
        title={tr("Noch keine Symbole oder Footprints")}
        description={tr("Die Stapelbearbeitung gleicht vorhandene Symbole und Footprints an den Hausstil an – verlustfrei, Namen bleiben, jede Datei wird vorher gesichert. Zuerst eine Altium-Bibliothek übernehmen, z. B. eine Celestial- oder Herstellerbibliothek.")}
        actions={
          <Button asChild size="sm">
            <Link to="/bibliotheksimport">
              <FolderInput aria-hidden />
              {tr("Bibliotheksimport öffnen")}</Link>
          </Button>
        }
      />
    </Card>
  )
}

/** Platzhalter, solange die erste Prüfung läuft (kein Springen, wenn der Bericht kommt) */
export function ReportSkeleton() {
  useI18n()
  return (
    <div className="flex flex-col gap-4" aria-hidden>
      <Card className="px-5 py-4">
        <Skeleton className="h-5 w-72 max-w-full" />
        <Skeleton className="mt-2 h-3 w-56 max-w-full" />
        <Skeleton className="mt-4 h-1.5 w-full rounded-full" />
        <div className="mt-4 flex flex-wrap gap-1.5">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-6 w-24 rounded-full" />
          ))}
        </div>
      </Card>
      <Card className="divide-y divide-line">
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="size-4" />
            <Skeleton className="h-3.5 w-48" />
            <Skeleton className="ml-auto h-5 w-20 rounded-full" />
          </div>
        ))}
      </Card>
    </div>
  )
}

/** Prüfung gescheitert, abgebrochen oder nicht mehr bekannt */
export function CheckIssue({
  state,
  job,
  hasReport,
  ...action
}: CheckActionProps & { state: RunState; job: Job<ConformReport> | undefined; hasReport: boolean }) {
  const { t: tr } = useI18n()
  const failed = state === 'failed'
  const title = failed
    ? tr("Prüfung fehlgeschlagen")
    : state === 'cancelled'
      ? tr("Prüfung abgebrochen")
      : tr("Prüfung nicht mehr verfügbar")
  const text = failed
    ? cleanErrorText(job?.error ?? '') || tr("Unbekannter Fehler.")
    : state === 'cancelled' && job
      ? isLibrarySwitchCancel(job)
        ? jobCancelText(job)
        : tr("Geändert wurde nichts – die Prüfung liest nur.")
      : tr("Das Ergebnis liegt nicht mehr vor (z. B. nach einem Neustart von PartForge).")
  return (
    <Callout
      tone={failed ? 'danger' : 'neutral'}
      urgent={failed}
      title={title}
      actions={
        <Button
          size="sm"
          leftIcon={<RefreshCw />}
          onClick={action.onCheck}
          disabled={Boolean(action.checkBlocked)}
          loading={action.checkPending}
        >
          {tr("Erneut prüfen")}</Button>
      }
    >
      {text}
      {hasReport && <span className="block">{tr("Unten steht weiter der letzte Bericht.")}</span>}
    </Callout>
  )
}
