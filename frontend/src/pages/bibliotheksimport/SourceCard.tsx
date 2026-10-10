import { localizeMessage } from '@/lib/i18n'
import { t, useI18n } from '@/lib/i18n'
import { ChevronDown, CircleStop, FileArchive, Folder, FolderInput, FolderSearch, History, ScanSearch, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router'
import { cleanErrorText } from '@/api/client'
import { jobCancelText } from '@/api/jobs'
import type { ImportScanSummary } from '@/api/libimport'
import { isJobActive, useCancelJob, type Job } from '@/api/system'
import {
  Button,
  Callout,
  Card,
  CardContent,
  CardHeader,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Field,
  IconButton,
  PathInput,
  ProgressBar,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatNumbersInText } from '@/lib/format'
import { pickFile, pickFolder, useNativeBridge } from '@/lib/native'
import { SETTINGS_PLACE } from '@/lib/settingsPlaces'
import { cleanSourcePath, folderOf, pathKey, SOURCE_FILE_FILTERS, sourceProblem } from './model'
import { useRecentSources } from './store'

/** ID des Pfadfelds (Fokus aus „Pfad eingeben“, „Weitere Quelle importieren“ und der Befehlspalette) */
export const SOURCE_INPUT_ID = 'bibliotheksimport-quelle'

/** Fehlertexte, die einen fehlenden Bibliotheks-Writer melden */
const NO_WRITER = /bibliotheks-writer/i

export interface SourceCardProps {
  path: string
  onPathChange: (path: string) => void
  /** Quelle einlesen (Pfad bereinigt und geprüft) */
  onScan: (path: string) => void
  /** Anfrage zum Start läuft */
  starting: boolean
  /** laufender bzw. zuletzt beendeter Job „Bibliothek einlesen“ */
  job: Job<ImportScanSummary> | undefined
  /** Fehler beim Start (Anfrage abgelehnt) */
  startError: string | null
  /** Fehler bzw. Abbruch ausblenden */
  onDismiss: () => void
  /** Quelle des angezeigten Scans – „Einlesen“ heißt dann „Erneut einlesen“ */
  currentSource: string | null
  /** Grund, warum gerade nichts eingelesen werden kann (Import läuft) */
  locked: string | null
  /** Einlesen ist die Primäraktion der Ansicht (noch kein Scan) */
  primary: boolean
}

export function SourceCard({
  path,
  onPathChange,
  onScan,
  starting,
  job,
  startError,
  onDismiss,
  currentSource,
  locked,
  primary,
}: SourceCardProps) {
  useI18n()
  const navigate = useNavigate()
  const cancel = useCancelJob()
  const recent = useRecentSources((s) => s.recent)
  const forget = useRecentSources((s) => s.forget)
  /** Prüfung erst beim Absenden – nicht schon beim Tippen */
  const [touched, setTouched] = useState(false)

  const scanning = Boolean(job && isJobActive(job))
  const busy = starting || scanning || Boolean(locked)
  const problem = touched ? sourceProblem(path) : null
  const again = Boolean(currentSource && cleanSourcePath(path) && pathKey(cleanSourcePath(path)) === pathKey(currentSource))
  const stopping = scanning && Boolean(job?.cancel_requested)
  const failed = job?.status === 'failed' ? cleanErrorText(job.error ?? job.message ?? '') || t("Einlesen fehlgeschlagen.") : null
  const error = startError ?? failed
  const cancelled = !error && job?.status === 'cancelled'

  const scan = (raw: string) => {
    setTouched(true)
    if (sourceProblem(raw)) return
    onScan(cleanSourcePath(raw))
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    scan(path)
  }

  const picked = (value: string) => {
    onPathChange(value)
    scan(value)
  }

  return (
    <Card>
      <CardHeader
        icon={<FolderInput />}
        title={t("Quelle")}
        description={t("Ein Ordner (mit allen Unterordnern) oder eine Bibliotheksdatei: .SchLib, .PcbLib, .IntLib, .LibPkg oder .zip. PartForge liest die Quelle nur.")}
      />
      <CardContent className="flex flex-col gap-3">
        <form onSubmit={submit} noValidate>
          <Field label={t("Ordner oder Bibliotheksdatei")} htmlFor={SOURCE_INPUT_ID} error={problem ?? undefined}>
            <div className="flex min-w-0 items-start gap-2">
              <PathInput
                id={SOURCE_INPUT_ID}
                className="min-w-0 flex-1"
                value={path}
                onValueChange={(v) => {
                  onPathChange(v)
                  if (!v.trim()) setTouched(false)
                }}
                placeholder={t("C:\\Bibliotheken\\Hersteller")}
                disabled={busy}
                invalid={Boolean(problem)}
              />
              <BrowseButton path={path} disabled={busy} onPicked={picked} />
              <Button
                type="submit"
                variant={primary ? 'primary' : 'secondary'}
                leftIcon={<ScanSearch />}
                loading={starting || scanning}
                disabled={Boolean(locked)}
              >
                {again ? t("Erneut einlesen") : t("Einlesen")}
              </Button>
            </div>
          </Field>
        </form>

        {locked && <p className="text-xs text-fg-subtle">{locked}</p>}

        {recent.length > 0 && !locked && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="micro-label mr-1 flex items-center gap-1">
              <History aria-hidden className="size-3" />
              {t("Zuletzt")}</span>
            <ul className="contents" aria-label={t("Zuletzt eingelesene Quellen")}>
              {recent.map((r) => {
                const name = baseName(r.path)
                const current = currentSource !== null && pathKey(r.path) === pathKey(currentSource)
                return (
                  <li
                    key={r.path}
                    className={cn(
                      'inline-flex h-6 items-center rounded-full border text-2xs font-medium transition-colors',
                      current ? 'border-accent/40 bg-accent-soft text-accent-text' : 'border-line-strong bg-surface-2 text-fg-muted',
                    )}
                  >
                    <Tooltip content={<span className="mono break-all">{r.path}</span>}>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => picked(r.path)}
                        aria-label={t("{0} einlesen – {1}", { "0": String(name), "1": String(r.path) })}
                        className="h-full max-w-[16rem] truncate rounded-full pl-2.5 pr-1 outline-none hover:text-fg focus-ring disabled:pointer-events-none disabled:opacity-50"
                      >
                        {name}
                      </button>
                    </Tooltip>
                    <button
                      type="button"
                      onClick={() => forget(r.path)}
                      aria-label={t("{0} aus der Liste entfernen", { "0": String(name) })}
                      title={t("Aus der Liste entfernen")}
                      className="mr-0.5 flex size-5 items-center justify-center rounded-full text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
                    >
                      <X aria-hidden className="size-3" />
                    </button>
                  </li>
                )
              })}
            </ul>
          </div>
        )}

        {scanning && job && (
          <div className="flex items-center gap-3 rounded-control bg-surface-2/60 px-3 py-2.5">
            <ProgressBar
              className="min-w-0 flex-1"
              value={job.progress}
              indeterminate={job.progress <= 0}
              live
              showValue
              label={stopping ? t("Wird abgebrochen …") : formatNumbersInText(localizeMessage(job.message)) || t("Quelle wird durchsucht …")}
            />
            <Button
              size="sm"
              variant="ghost"
              leftIcon={<CircleStop />}
              loading={cancel.isPending || stopping}
              disabled={stopping}
              onClick={() => cancel.mutate(job.id)}
            >
              {stopping ? t("Wird abgebrochen") : t("Abbrechen")}
            </Button>
          </div>
        )}

        {error && (
          <Callout
            tone="danger"
            title={t("Einlesen nicht möglich")}
            urgent
            actions={
              <>
                {NO_WRITER.test(error) && (
                  <Button size="sm" onClick={() => navigate(SETTINGS_PLACE.altium.to)}>
                    {t("Writer einrichten")}</Button>
                )}
                <IconButton size="sm" label={t("Hinweis schließen")} icon={<X />} onClick={onDismiss} />
              </>
            }
          >
            {formatNumbersInText(error)}
          </Callout>
        )}
        {cancelled && job && (
          <Callout tone="neutral" title={t("Einlesen abgebrochen")} actions={<IconButton size="sm" label={t("Hinweis schließen")} icon={<X />} onClick={onDismiss} />}>
            {jobCancelText(job) === 'Abgebrochen' ? t("Die Quelle wurde nicht vollständig gelesen.") : jobCancelText(job)} {t(" „Einlesen“ startet neu.")}</Callout>
        )}
      </CardContent>
    </Card>
  )
}

/** „Durchsuchen …“: Ordner bzw. Bibliotheksdatei wählen (nur im Desktop-Fenster) – die Wahl wird gleich eingelesen */
function BrowseButton({ path, disabled, onPicked }: { path: string; disabled: boolean; onPicked: (path: string) => void }) {
  useI18n()
  const bridge = useNativeBridge()
  const chooseFolder = async () => {
    const picked = await pickFolder(folderOf(path) || null)
    if (picked) onPicked(picked)
  }
  const chooseFile = async () => {
    const picked = await pickFile(cleanSourcePath(path) || null, SOURCE_FILE_FILTERS.map((filter) => t(filter)))
    if (picked) onPicked(picked)
  }
  if (bridge.canPickFolder && bridge.canPickFile) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="secondary" leftIcon={<FolderSearch />} rightIcon={<ChevronDown />} disabled={disabled}>
            {t("Durchsuchen …")}</Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-72">
          <DropdownMenuItem icon={<Folder />} description={t("Mit allen Unterordnern")} onSelect={() => void chooseFolder()}>
            {t("Ordner wählen …")}</DropdownMenuItem>
          <DropdownMenuItem icon={<FileArchive />} description={t("SchLib, PcbLib, IntLib, LibPkg oder ZIP")} onSelect={() => void chooseFile()}>
            {t("Bibliotheksdatei wählen …")}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }
  if (bridge.canPickFolder) {
    return (
      <Button variant="secondary" leftIcon={<FolderSearch />} disabled={disabled} onClick={() => void chooseFolder()}>
        {t("Ordner wählen …")}</Button>
    )
  }
  if (bridge.canPickFile) {
    return (
      <Button variant="secondary" leftIcon={<FolderSearch />} disabled={disabled} onClick={() => void chooseFile()}>
        {t("Datei wählen …")}</Button>
    )
  }
  return null
}
