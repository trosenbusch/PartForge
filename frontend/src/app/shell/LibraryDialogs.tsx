import { localizeMessage } from '@/lib/i18n'
import { useI18n } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
import { AnimatePresence, motion } from 'motion/react'
import {
  ArrowRight,
  Check,
  CircleCheck,
  CircleX,
  Database,
  ExternalLink,
  FileCode2,
  Folder,
  FolderOpen,
  FolderPlus,
  Info,
  Library,
  RotateCw,
  Settings2,
  TriangleAlert,
} from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate, type NavigateOptions } from 'react-router'
import { toast } from 'sonner'
import { odbcDriverStatus, useAltiumStatus } from '@/api/altium'
import { ApiError, errorMessage } from '@/api/client'
import { jobOutcome, SETUP_WRITER_ACTION, trackJob, useInlineJob, useJob } from '@/api/jobs'
import {
  isJobFinished,
  useCreateWorkspace,
  useOpenWorkspace,
  useRecentWorkspaces,
  useWorkspace,
  useWorkspaceDefaults,
  type CreatedWorkspace,
  type CreateWorkspaceInput,
  type DbLibNameUse,
  type Job,
  type WorkspaceInfo,
} from '@/api/system'
import {
  Button,
  Callout,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  Input,
  PathInput,
  ProgressBar,
  Switch,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatNumber, formatPercent, plural, shortenPath } from '@/lib/format'
import { DEFAULT_LIBRARY_NAME } from '@/lib/libraryDefaults'
import { SETTINGS_PLACE, WRITER } from '@/lib/settingsPlaces'
import { ALTIUM_PATH, altiumActionState } from '../navigation'
import { useUi } from '../stores'
import { confirmLibrarySwitch, switchCancelNote } from './librarySwitch'

/** Beispiel in Platzhaltern und Hinweisen – bewusst kein Pfad dieses Rechners */
const EXAMPLE_PATH = 'C:\\Bibliotheken\\Firmenbibliothek'
const DEFAULT_NAME = DEFAULT_LIBRARY_NAME
const DBLIB_EXT = '.DbLib'
/** In Windows-Dateinamen unzulässige Zeichen (inkl. Steuerzeichen) */
// oxlint-disable-next-line no-control-regex -- Steuerzeichen sind in Windows-Dateinamen verboten
const BAD_FILE_CHARS = /[<>:"/\\|?*\u0000-\u001f]/

function isAbsoluteWindowsPath(path: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(path) || /^\\\\[^\\]+\\[^\\]+/.test(path)
}

function joinPath(base: string, name: string): string {
  return `${base.replace(/[\\/]+$/, '')}\\${name}`
}

/** Übergeordneter Ordner („C:\A\B“ → „C:\A“), `null` für ein Laufwerk */
function parentDir(path: string): string | null {
  const trimmed = path.trim().replace(/[\\/]+$/, '')
  const i = Math.max(trimmed.lastIndexOf('\\'), trimmed.lastIndexOf('/'))
  return i > 2 ? trimmed.slice(0, i) : null
}

/**
 * Kollidiert der DbLib-Dateiname mit einer bekannten DbLib? Deutscher Satz („„PartForge.DbLib“ ist in Altium installiert
 * (C:\…)“ bzw. „… verwendet schon die Bibliothek „A“ (C:\…)“) oder `null`.
 */
function findDblibClash(file: string, taken: DbLibNameUse[], open: WorkspaceInfo | null | undefined): string | null {
  const key = file.toLowerCase()
  const hits = taken.filter((t) => t.file_name.toLowerCase() === key)
  const installed = hits.find((t) => t.installed)
  if (installed) return tr("„{0}“ ist in Altium bereits installiert ({1}).", { "0": String(file), "1": String(installed.path) })
  if (open && baseName(open.dblib_path).toLowerCase() === key) {
    return tr("Die geöffnete Bibliothek „{0}“ verwendet schon „{1}“.", { "0": String(open.name), "1": String(file) })
  }
  const other = hits[0]
  if (other) return tr("„{0}“ gibt es schon in der Bibliothek {1} ({2}).", { "0": String(file), "1": String(other.library ? `„${baseName(other.library)}“` : ''), "2": String(other.path) })
  return null
}

/** Umbruchstellen in Datei- und Ordnernamen: vor „.“ (Endung) und nach „-“, „_“, Leerzeichen – nie mitten im Wort */
function withBreaks(name: string): ReactNode[] {
  return name.split(/(?=\.)|(?<=[-_ ])/).flatMap((part, i) => (i === 0 ? [part] : [<wbr key={i} />, part]))
}

/** Ordnername zu einem Bibliotheksnamen – wie das Backend (`routes_system._folder_name`): unzulässige Zeichen → Leerzeichen */
function folderNameFor(name: string): string {
  // oxlint-disable-next-line no-control-regex -- Steuerzeichen sind in Windows-Ordnernamen verboten
  const text = name.replace(/[<>:"/\\|?*\u0000-\u001f]+/g, ' ').trim().replace(/\.+$/, '').replace(/\s+/g, ' ')
  return text.slice(0, 80) || tr(DEFAULT_NAME)
}

/** Wert nach einer Pause (Tippen) übernehmen */
function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return debounced
}

/**
 * Vorschlag für Ordner und DbLib-Namen einer neuen Bibliothek. Vom Backend (`GET /api/workspace/defaults?name=`):
 * „<Dokumente>\PartForge\<Name>“ (ein Ordner, den es noch nicht gibt) und ein DbLib-Name, den keine bekannte DbLib
 * verwendet – solange die Antwort zum gerade getippten Namen fehlt, aus Name und Basisordner. Ältere Backends ohne den
 * Endpunkt: neben der zuletzt verwendeten Bibliothek, sonst kein Vorschlag (Feld leer, Beispiel als Platzhalter) – nie
 * ein Pfad des Entwicklerrechners.
 */
function useLibrarySuggestion(name: string): { path: string; dblib: string; taken: DbLibNameUse[] } {
  const typed = name.trim()
  const debounced = useDebounced(typed, 250)
  const defaults = useWorkspaceDefaults(debounced)
  const recent = useRecentWorkspaces().data
  const data = defaults.isError ? undefined : defaults.data
  // nur eine Antwort zum gerade getippten Namen (nicht die vorige, die während des Ladens stehen bleibt)
  const current = data && !defaults.isPlaceholderData && debounced === typed ? data : null
  const lastUsed = recent?.find((r) => r.exists)?.path
  const parent = data?.parent ?? (lastUsed ? parentDir(lastUsed) : null)
  const folder = folderNameFor(typed)
  return {
    path: current?.path ?? (parent ? joinPath(parent, folder) : ''),
    dblib: current ? current.dblib_file.replace(/\.dblib$/i, '') : folder,
    taken: data?.dblib_taken ?? [],
  }
}

/**
 * 409 beim Anlegen, der den **Ordner** betrifft (dort liegt schon eine Bibliothek) – nicht: Bibliothek wird gerade
 * geschrieben (vorübergehend) oder die neue Datenbank ließ sich nicht öffnen (allgemeiner Fehler).
 */
function isFolderConflict(error: unknown): error is ApiError {
  return (
    error instanceof ApiError &&
    error.status === 409 &&
    !error.isLibraryBusy &&
    !/^bibliothek kann nicht geöffnet werden/i.test(error.message.trim())
  )
}

/** Beide Bibliotheks-Dialoge; gesteuert über useUi().libraryDialog. Einmal in der App rendern. */
export function LibraryDialogs() {
  useI18n()
  const dialog = useUi((s) => s.libraryDialog)
  const setDialog = useUi((s) => s.setLibraryDialog)
  return (
    <>
      <Dialog open={dialog === 'create'} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent size="lg">
          <CreateLibraryFlow />
        </DialogContent>
      </Dialog>
      <Dialog open={dialog === 'open'} onOpenChange={(o) => !o && setDialog(null)}>
        <DialogContent size="md">
          <OpenLibraryForm />
        </DialogContent>
      </Dialog>
    </>
  )
}

/** Ein Fehler, der vorübergehend ist (Bibliotheks-Job hält die Bibliothek): Hinweis mit „Erneut versuchen“. */
function BusyCallout({ error, onRetry, retrying }: { error: ApiError; onRetry: () => void; retrying: boolean }) {
  const { t: tr } = useI18n()
  return (
    <Callout tone="warning" urgent title={tr("Gerade beschäftigt")}>
      <span className="block">{error.message}</span>
      <Button size="sm" variant="secondary" leftIcon={<RotateCw />} loading={retrying} onClick={onRetry} className="mt-2.5">
        {tr("Erneut versuchen")}</Button>
    </Callout>
  )
}

// --------------------------------------------------------------------------- Neue Bibliothek

/** Formular → nach dem Anlegen mit Beispielen: Erfolgsansicht mit dem Fortschritt von „Bibliotheken schreiben“. */
function CreateLibraryFlow() {
  useI18n()
  const [created, setCreated] = useState<CreatedWorkspace | null>(null)
  return (
    <AnimatePresence mode="wait" initial={false}>
      {created ? (
        <motion.div
          key="created"
          className="flex min-h-0 flex-col"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
        >
          <LibraryCreated info={created} />
        </motion.div>
      ) : (
        <motion.div key="form" className="flex min-h-0 flex-col" exit={{ opacity: 0, y: -4, transition: { duration: 0.12 } }}>
          <CreateLibraryForm onCreated={setCreated} />
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function CreateLibraryForm({ onCreated }: { onCreated: (info: CreatedWorkspace) => void }) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const preset = useUi((s) => s.libraryDialogPath)
  const setDialog = useUi((s) => s.setLibraryDialog)
  const create = useCreateWorkspace()
  const current = useWorkspace().data
  const [name, setName] = useState(() => tr(DEFAULT_NAME))
  /** eigener Ordner (`null` = Vorschlag, folgt dem Namen) */
  const [ownPath, setOwnPath] = useState<string | null>(preset)
  /** eigener DbLib-Name ohne Endung (`null` = Vorschlag, folgt dem Namen) */
  const [ownDblib, setOwnDblib] = useState<string | null>(null)
  const [examples, setExamples] = useState(true)
  const [submitted, setSubmitted] = useState(false)
  const suggestion = useLibrarySuggestion(name)

  const path = ownPath ?? suggestion.path
  const dblib = ownDblib ?? suggestion.dblib
  const trimmedPath = path.trim()
  const dblibName = dblib.trim().replace(/\.dblib$/i, '')
  const dblibFile = `${dblibName}${DBLIB_EXT}`

  const pathError =
    submitted && !trimmedPath
      ? tr("Bitte einen Ordner angeben, z. B. {0}", { "0": tr(EXAMPLE_PATH) })
      : submitted && !isAbsoluteWindowsPath(trimmedPath)
        ? tr("Bitte einen vollständigen Pfad angeben, z. B. {0}", { "0": tr(EXAMPLE_PATH) })
        : null
  const dblibError = !dblibName
    ? submitted
      ? tr("Bitte einen Namen für die DbLib-Datei angeben.")
      : null
    : BAD_FILE_CHARS.test(dblibName)
      ? tr("Der Name enthält Zeichen, die Windows in Dateinamen nicht erlaubt (< > : \" / \\ | ? *).")
      : null
  // Altium unterscheidet Datenbankbibliotheken nur am Dateinamen – eine zweite „PartForge.DbLib“ kollidiert: bekannte
  // DbLibs (installiert bzw. anderer Bibliotheken, vom Backend) und – auch ohne diese Liste – die der geöffneten Bibliothek
  const clash = dblibName ? findDblibClash(dblibFile, suggestion.taken, current) : null

  const conflict = isFolderConflict(create.error) ? create.error : null
  const busy = create.error instanceof ApiError && create.error.isLibraryBusy ? create.error : null
  const otherError = create.error && !conflict && !busy ? errorMessage(create.error) : null

  const run = async () => {
    // laufende Jobs der offenen Bibliothek würde das Anlegen (= Wechseln) abbrechen – vorher fragen
    if (!(await confirmLibrarySwitch('create'))) return
    // write_libraries: die Beispiel-Symbole/-Footprints gleich schreiben (Job „Bibliotheken schreiben“)
    create.mutate(
      {
        path: trimmedPath,
        name: name.trim() || undefined,
        with_examples: examples,
        write_libraries: true,
        // nur die abweichende Angabe – das Backend ergänzt alle übrigen Bibliothekseinstellungen mit ihren Standardwerten
        settings: { dblib_file: dblibFile } as unknown as CreateWorkspaceInput['settings'],
      },
      {
        onSuccess: (info) => {
          navigate('/')
          if (info.job) {
            // Fortschritt zeigt die Erfolgsansicht – nicht in der Pille, kein Toast (außer sie wird vorher geschlossen)
            trackJob(info.job, { dock: false, toast: false })
            onCreated(info)
            return
          }
          const warning = info.warnings?.[0]
          if (warning) toast.warning(tr("Bibliothek „{0}“ angelegt", { "0": String(info.name) }), { description: localizeMessage(warning), duration: 12_000 })
          else {
            toast.success(tr("Bibliothek „{0}“ angelegt", { "0": String(info.name) }), {
              description: info.examples_error ?? (examples ? tr("Mit Beispielinhalten – viel Spaß beim Schmieden!") : shortenPath(info.root, 56)),
            })
          }
          setDialog(null)
        },
      },
    )
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setSubmitted(true)
    if (!trimmedPath || !isAbsoluteWindowsPath(trimmedPath) || !dblibName || BAD_FILE_CHARS.test(dblibName)) return
    void run()
  }

  const structure = [
    { icon: Database, name: 'PartForge.sqlite', hint: tr("Datenbank (ODBC)") },
    { icon: FileCode2, name: dblibName ? dblibFile : `…${DBLIB_EXT}`, hint: tr("Altium-Datenbankbibliothek") },
    { icon: Folder, name: 'Symbols\\', hint: tr("Schaltplansymbole (.SchLib)") },
    { icon: Folder, name: 'Footprints\\', hint: 'Footprints (.PcbLib)' },
    { icon: Folder, name: '3D\\', hint: tr("STEP-Modelle") },
    { icon: Folder, name: 'Datasheets\\', hint: tr("Datenblätter (PDF)") },
  ]

  return (
    <form onSubmit={submit} className="flex min-h-0 flex-col">
      <DialogHeader
        icon={<FolderPlus />}
        title={tr("Neue Bibliothek anlegen")}
        description={tr("Ein Bibliotheksordner enthält Datenbank, DbLib-Datei, Symbole, Footprints, 3D-Modelle und Datenblätter – vollständig und verschiebbar.")}
      />
      <DialogBody className="grid grid-cols-[minmax(0,1fr)_220px] gap-6">
        <div className="flex flex-col gap-4">
          <Field label="Name" required help={tr("Name der Bibliothek in PartForge – Ordner und DbLib-Datei heißen standardmäßig genauso.")}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={tr("z. B. Firmenbibliothek")} />
          </Field>
          <Field
            label={tr("Ordner")}
            required
            error={pathError ?? (conflict ? conflict.message : undefined)}
            help={tr("Der Ordner wird bei Bedarf erstellt. Pfad z. B. aus dem Explorer kopieren.")}
          >
            <PathInput
              value={path}
              onValueChange={setOwnPath}
              prefix={<FolderOpen />}
              placeholder={tr("z. B. {0}", { "0": tr(EXAMPLE_PATH) })}
              browse="folder"
            />
          </Field>
          {conflict && (
            <div className="-mt-1 flex items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => setDialog('open', trimmedPath)}>
                {tr("Stattdessen diese Bibliothek öffnen")}</Button>
            </div>
          )}
          <Field
            label={tr("DbLib-Datei")}
            required
            error={dblibError ?? undefined}
            help={tr("Altium unterscheidet Datenbankbibliotheken am Dateinamen – jede Bibliothek braucht einen eigenen.")}
          >
            <Input
              value={dblib}
              onChange={(e) => setOwnDblib(e.target.value)}
              mono
              suffix={<span className="mono">{DBLIB_EXT}</span>}
              placeholder={tr("z. B. Firmenbibliothek")}
            />
          </Field>
          {clash && !dblibError && (
            <Callout tone="warning" className="-mt-1 text-xs" title={tr("Gleichnamige DbLib")}>
              {clash} {tr(" Altium findet Bauteile nur über den Dateinamen der DbLib – sind beide installiert, gewinnt die zuerst installierte. Bitte einen anderen Namen wählen.")}</Callout>
          )}
          <div className="rounded-card border border-line bg-surface-2/50 p-3.5">
            <Switch
              checked={examples}
              onCheckedChange={setExamples}
              label={tr("Beispielinhalte anlegen")}
              description={tr("Typische Bauteile (Widerstände, Kondensatoren, Dioden, ICs) mit fertigen Symbolen und Footprints – ideal zum Kennenlernen.")}
            />
          </div>
          {busy && <BusyCallout error={busy} onRetry={() => void run()} retrying={create.isPending} />}
          {otherError && (
            <Callout tone="danger" urgent>
              {otherError}
            </Callout>
          )}
        </div>

        {/* Vorschau der Ordnerstruktur */}
        <div className="flex flex-col gap-2">
          <div className="micro-label">{tr("Wird angelegt")}</div>
          <div className="rounded-card border border-line bg-bg/60 p-3">
            <div className="mono mb-2 flex items-center gap-1.5 text-2xs text-fg" title={trimmedPath || undefined}>
              <FolderOpen aria-hidden className="size-3.5 shrink-0 text-accent" />
              <span className="min-w-0 break-words">{withBreaks(`${baseName(trimmedPath) || '…'}\\`)}</span>
            </div>
            <ul className="flex flex-col gap-1.5 border-l border-line-strong pl-3">
              {structure.map((item, i) => (
                <motion.li
                  key={item.hint}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.05 + i * 0.03 }}
                  className="flex min-w-0 flex-col"
                >
                  <span className="mono flex items-start gap-1.5 text-2xs text-fg-muted">
                    <item.icon aria-hidden className="mt-0.5 size-3 shrink-0 text-fg-subtle" />
                    <span className="min-w-0 break-words">{withBreaks(item.name)}</span>
                  </span>
                  <span className="pl-[18px] text-2xs leading-tight text-fg-subtle">{item.hint}</span>
                </motion.li>
              ))}
            </ul>
          </div>
        </div>
      </DialogBody>
      <DialogFooter>
        <span className="mr-auto flex items-center gap-1.5 text-2xs text-fg-subtle">
          <Info aria-hidden className="size-3.5" />
          {tr("Altium greift später per ODBC auf die Datenbank zu.")}</span>
        <Button variant="ghost" onClick={() => setDialog(null)}>
          {tr("Abbrechen")}</Button>
        <Button type="submit" variant="primary" loading={create.isPending} leftIcon={<FolderPlus />}>
          {tr("Bibliothek anlegen")}</Button>
      </DialogFooter>
    </form>
  )
}

// --------------------------------------------------------------------------- Erfolgsansicht + „Bibliotheken schreiben“

interface WriteCount {
  total?: number
  ok?: number
  adopted?: number
}

interface LibraryWriteResult {
  symbols?: WriteCount
  footprints?: WriteCount
  libraries?: string[]
  skipped?: boolean
}

/** „15 Symbole und 13 Footprints in 14 Bibliotheksdateien geschrieben“ */
function writeSummary(result: LibraryWriteResult | null | undefined): string {
  const sym = result?.symbols?.ok ?? 0
  const fp = result?.footprints?.ok ?? 0
  const files = result?.libraries?.length ?? 0
  const parts = [sym ? plural(sym, 'Symbol', tr("Symbole")) : null, fp ? plural(fp, 'Footprint', 'Footprints') : null].filter(Boolean)
  if (!parts.length) return tr("Alle Symbole und Footprints sind bereits in den Bibliotheksdateien.")
  return tr("{0}{1} geschrieben.", { "0": String(parts.join(' und ')), "1": String(files ? ` in ${plural(files, tr("Bibliotheksdatei"), tr("Bibliotheksdateien"))}` : '') })
}

function LibraryCreated({ info }: { info: CreatedWorkspace }) {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const setDialog = useUi((s) => s.setLibraryDialog)
  const initial = info.job ?? null
  const { job: live } = useJob<LibraryWriteResult>(initial?.id)
  const job = (live ?? initial) as Job<LibraryWriteResult> | null
  const finished = job ? isJobFinished(job) : true
  const outcome = job ? jobOutcome(job) : null
  const examples = info.examples
  /** ohne Bibliotheks-Writer wurde nichts geschrieben: Behebung „Bibliotheks-Writer einrichten“ */
  const needsWriter = outcome?.action === SETUP_WRITER_ACTION

  // Solange die Ansicht offen ist, zeigt sie den Job; wird sie vor dem Ende geschlossen, übernimmt das Job-Dock
  // (Pille und Abschluss-Toast)
  useInlineJob(initial?.id)

  const close = () => setDialog(null)
  const goTo = (to: string, options?: NavigateOptions) => {
    setDialog(null)
    navigate(to, options)
  }
  const stats = examples && examples.parts + examples.symbols + examples.footprints > 0
    ? [
        { label: tr("Bauteile"), value: examples.parts },
        { label: tr("Symbole"), value: examples.symbols },
        { label: 'Footprints', value: examples.footprints },
      ]
    : []

  return (
    <>
      <DialogHeader
        tone="success"
        icon={<CircleCheck />}
        title={tr("Bibliothek „{0}“ angelegt", { "0": String(info.name) })}
        description={
          <span className="mono block truncate text-xs text-fg-subtle" title={info.root}>
            {info.root}
          </span>
        }
      />
      <DialogBody className="flex flex-col gap-4">
        {stats.length > 0 && (
          <div className="grid grid-cols-3 divide-x divide-line rounded-card border border-line bg-bg/50">
            {stats.map((s, i) => (
              <motion.div
                key={s.label}
                className="flex flex-col gap-0.5 px-4 py-3"
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.06 + i * 0.04 }}
              >
                <span className="mono text-h3 font-semibold leading-7 tracking-[-0.02em] text-fg">{formatNumber(s.value)}</span>
                <span className="text-xs text-fg-muted">{tr("Beispiel-")}{s.label}</span>
              </motion.div>
            ))}
          </div>
        )}
        {info.examples_error && (
          <Callout tone="warning" title={tr("Beispielinhalte unvollständig")}>
            {localizeMessage(info.examples_error)} {tr(" Die Bibliothek ist trotzdem angelegt und nutzbar.")}</Callout>
        )}
        {(info.warnings ?? []).map((warning) => (
          <Callout key={warning} tone="warning">
            {localizeMessage(warning)}
          </Callout>
        ))}
        <OdbcDriverNote onTest={() => goTo(ALTIUM_PATH, { state: altiumActionState('odbc') })} />

        {job && (
          <section aria-labelledby="pf-libwrite-title" className="rounded-card border border-line bg-surface-2/40 p-4">
            <div className="mb-2.5 flex items-center gap-2">
              <span id="pf-libwrite-title" className="micro-label">
                {localizeMessage(job.title)}
              </span>
              <span className="ml-auto text-xs tabular-nums text-fg-muted" aria-hidden>
                {finished ? '' : formatPercent(job.progress)}
              </span>
            </div>
            <AnimatePresence mode="wait" initial={false}>
              {!finished ? (
                <motion.div key="running" exit={{ opacity: 0, transition: { duration: 0.12 } }}>
                  <ProgressBar
                    value={job.progress}
                    indeterminate={job.progress <= 0}
                    live
                    size="sm"
                    label={`${localizeMessage(job.title)}: ${formatPercent(job.progress)}`}
                    hideLabel
                  />
                  <p className="mt-2 truncate text-xs text-fg-muted" aria-live="polite">
                    {localizeMessage(job.message || '') || tr("Symbole und Footprints werden in die Bibliotheksdateien geschrieben …")}
                  </p>
                </motion.div>
              ) : (
                <motion.div
                  key="done"
                  initial={{ opacity: 0, y: 4 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.2 }}
                  className="flex items-start gap-2.5"
                  role="status"
                >
                  <JobOutcomeIcon tone={outcome?.tone ?? 'success'} />
                  <div className="min-w-0 flex-1 text-ui">
                    <p
                      className={cn(
                        'leading-relaxed',
                        outcome?.tone === 'success' ? 'text-fg' : outcome?.tone === 'error' ? 'text-danger-text' : 'text-fg',
                      )}
                    >
                      {outcome?.tone === 'success'
                        ? writeSummary(job.result)
                        : outcome?.tone === 'info'
                          ? tr("Abgebrochen – noch nicht geschriebene Symbole und Footprints bleiben vorgemerkt.")
                          : // voller Text (Toasts kürzen auf 200 Zeichen – hier ist Platz)
                            (outcome?.problem ?? outcome?.description)}
                    </p>
                    {outcome && outcome.tone !== 'success' && (
                      <p className="mt-1 text-xs text-fg-muted">
                        {needsWriter
                          ? tr("Ist der {0} eingetragen (oder Altium Designer gestartet), schreibt „Bibliotheksdateien synchronisieren“ auf der Altium-Seite alles Vorgemerkte.", { "0": tr(WRITER) })
                          : tr("Nachholen jederzeit über Altium › „Bibliotheksdateien synchronisieren“ (auch in der Befehlspalette).")}
                      </p>
                    )}
                    {needsWriter && (
                      <Button
                        size="sm"
                        variant="secondary"
                        leftIcon={<Settings2 />}
                        className="mt-2.5"
                        onClick={() => goTo(SETTINGS_PLACE.writer.to)}
                      >
                        {tr("{0} einrichten", { 0: tr(WRITER) })}
                      </Button>
                    )}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </section>
        )}
      </DialogBody>
      <DialogFooter>
        {!finished && (
          <span className="mr-auto flex items-center gap-1.5 text-2xs text-fg-subtle">
            <Info aria-hidden className="size-3.5" />
            {tr("Läuft im Hintergrund weiter, auch wenn Sie schließen.")}</span>
        )}
        <Button variant="primary" rightIcon={<ArrowRight />} onClick={close}>
          {tr("Zur Übersicht")}</Button>
      </DialogFooter>
    </>
  )
}

/** Bezugsquelle des 64-Bit-SQLite-ODBC-Treibers (README „Voraussetzungen“), falls das Backend keine nennt */
const SQLITE_ODBC_DOWNLOAD = 'http://www.ch-werner.de/sqliteodbc/'

/**
 * Fehlt der ODBC-Treiber, über den Altium die Datenbank liest (`GET /api/altium/status` → `odbc.installed === false`),
 * sagt die Erfolgsansicht es gleich: Die Bibliothek ist fertig, aber Altium findet ohne Treiber kein Bauteil. Mit
 * Download (Bezugsquelle des Backends) und „ODBC testen“ (Altium-Seite: Bericht mit Hilfe zum Treiber).
 */
function OdbcDriverNote({ onTest }: { onTest: () => void }) {
  const { t: tr } = useI18n()
  const odbc = odbcDriverStatus(useAltiumStatus().data)
  if (!odbc || odbc.installed !== false) return null
  const sqlite = odbc.kind ? odbc.kind === 'sqlite' : /sqlite/i.test(odbc.driver)
  const href = odbc.download || (sqlite ? SQLITE_ODBC_DOWNLOAD : null)
  let host = href ?? ''
  try {
    host = href ? new URL(href).host.replace(/^www\./, '') : ''
  } catch {
    // keine gültige Adresse – dann der Text selbst
  }
  return (
    <Callout tone="warning" title={tr("Altium braucht noch den ODBC-Treiber „{0}“", { "0": String(odbc.driver) })}>
      {tr("Altium liest die Bibliothek über ODBC – ohne den 64-Bit-Treiber findet Altium keine Bauteile, auch wenn die Bibliothek fertig ist.")}{' '}
      {sqlite ? tr("Den SQLite-ODBC-Treiber installieren (sqliteodbc_w64.exe)") : tr("Den 64-Bit-Treiber psqlODBC installieren")}{tr(", danach „ODBC testen“.")}<span className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
        {href && (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-sm font-medium text-accent-text underline-offset-2 outline-none hover:underline focus-ring"
          >
            {sqlite ? tr("SQLite-ODBC-Treiber") : tr("ODBC-Treiber")} herunterladen{host ? ` (${host})` : ''}
            <ExternalLink aria-hidden className="size-3" />
            <span className="sr-only"> {tr(" (öffnet im Browser)")}</span>
          </a>
        )}
        <Button variant="link" size="xs" rightIcon={<ArrowRight />} onClick={onTest}>
          {tr("ODBC testen")}</Button>
      </span>
    </Callout>
  )
}

function JobOutcomeIcon({ tone }: { tone: 'success' | 'warning' | 'error' | 'info' }) {
  useI18n()
  const cls = 'mt-0.5 size-4 shrink-0'
  if (tone === 'success') return <Check aria-hidden className={cn(cls, 'text-success')} />
  if (tone === 'warning') return <TriangleAlert aria-hidden className={cn(cls, 'text-warning')} />
  if (tone === 'error') return <CircleX aria-hidden className={cn(cls, 'text-danger')} />
  return <Info aria-hidden className={cn(cls, 'text-fg-subtle')} />
}

// --------------------------------------------------------------------------- Bibliothek öffnen

function OpenLibraryForm() {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const preset = useUi((s) => s.libraryDialogPath)
  const setDialog = useUi((s) => s.setLibraryDialog)
  const recent = useRecentWorkspaces()
  const open = useOpenWorkspace()
  const [path, setPath] = useState(preset ?? '')
  const [lastTarget, setLastTarget] = useState<string | null>(null)
  /** „Öffnen“ ohne Ordner: Hinweis statt einer Anfrage mit einem geratenen Pfad */
  const [missing, setMissing] = useState(false)
  const notFound = open.error instanceof ApiError && open.error.status === 404 ? open.error : null
  const busy = open.error instanceof ApiError && open.error.isLibraryBusy ? open.error : null
  const otherError = open.error && !notFound && !busy ? errorMessage(open.error) : null
  const hasRecent = recent.data?.some((r) => r.exists) ?? false

  const doOpen = async (target: string) => {
    const trimmed = target.trim()
    if (!trimmed) return
    // laufende Jobs der offenen Bibliothek würde der Wechsel abbrechen – vorher fragen
    if (!(await confirmLibrarySwitch('switch'))) return
    const note = switchCancelNote()
    setLastTarget(trimmed)
    open.mutate(trimmed, {
      onSuccess: (info) => {
        toast.success(tr("„{0}“ geöffnet", { "0": String(info.name) }), { description: note ?? shortenPath(info.root, 56) })
        setDialog(null)
        navigate('/')
      },
    })
  }

  const fieldError = missing
    ? hasRecent
      ? tr("Bitte den Ordner einer Bibliothek angeben – oder unten eine zuletzt verwendete wählen.")
      : tr("Bitte den Ordner einer Bibliothek angeben.")
    : notFound?.message

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!path.trim()) {
          setMissing(true)
          return
        }
        void doOpen(path)
      }}
      className="flex min-h-0 flex-col"
    >
      <DialogHeader
        icon={<FolderOpen />}
        title={tr("Bibliothek öffnen")}
        description={tr("Ordner einer bestehenden PartForge-Bibliothek (enthält partforge.json).")}
      />
      <DialogBody className="flex flex-col gap-4">
        <Field label={tr("Ordner")} required error={fieldError}>
          <PathInput
            value={path}
            placeholder={tr("z. B. {0}", { "0": tr(EXAMPLE_PATH) })}
            onValueChange={(v) => {
              setPath(v)
              if (v.trim()) setMissing(false)
            }}
            prefix={<FolderOpen />}
            browse="folder"
          />
        </Field>
        {notFound && !missing && (
          <div className="-mt-2">
            <Button
              size="sm"
              variant="secondary"
              leftIcon={<FolderPlus />}
              onClick={() => setDialog('create', lastTarget ?? path.trim())}
            >
              {tr("Hier eine neue Bibliothek anlegen")}</Button>
          </div>
        )}
        {busy && (
          <BusyCallout error={busy} onRetry={() => void doOpen(lastTarget ?? path)} retrying={open.isPending} />
        )}
        {otherError && (
          <Callout tone="danger" urgent>
            {otherError}
          </Callout>
        )}
        {(recent.data?.length ?? 0) > 0 && (
          <div className="flex flex-col gap-1.5">
            <div className="micro-label">{tr("Zuletzt verwendet")}</div>
            <div className="flex max-h-56 flex-col gap-1 overflow-y-auto">
              {recent.data?.map((r) => (
                <button
                  key={r.path}
                  type="button"
                  disabled={!r.exists || open.isPending}
                  onClick={() => void doOpen(r.path)}
                  className={cn(
                    'group/recent flex items-center gap-3 rounded-button border border-transparent px-2.5 py-2 text-left outline-none transition-colors',
                    'hover:border-line hover:bg-surface-2 focus-ring disabled:cursor-not-allowed disabled:opacity-50',
                  )}
                >
                  <Library aria-hidden className="size-4 shrink-0 text-fg-subtle group-hover/recent:text-fg-muted" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-ui font-medium text-fg">{r.name ?? baseName(r.path)}</span>
                    <span className="mono block truncate text-2xs text-fg-subtle">{r.path}</span>
                  </span>
                  {!r.exists && <span className="shrink-0 text-2xs text-warning-text">{tr("nicht gefunden")}</span>}
                </button>
              ))}
            </div>
          </div>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => setDialog(null)}>
          {tr("Abbrechen")}</Button>
        <Button type="submit" variant="primary" loading={open.isPending} leftIcon={<FolderOpen />}>
          {tr("Öffnen")}</Button>
      </DialogFooter>
    </form>
  )
}
