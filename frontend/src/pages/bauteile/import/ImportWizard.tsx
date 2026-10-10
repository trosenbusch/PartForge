import { metadataLabel, localizeMessage, t, useI18n } from '@/lib/i18n'
/**
 * Tabellen-Import (CSV, XLSX, ODS) in vier Schritten: Datei → Zuordnung (Tabellenblatt, Kopfzeile, Spalte → Feld mit
 * Vorschlägen, Treffergüte und Einheiten-Hinweis, feste Werte) → Prüfen (**Probelauf des Backends je Zeile**: neu,
 * aktualisieren, unverändert, übersprungen oder abgelehnt mit Gründen – für Zuordnung, Modus, feste Werte, Entwurf und
 * den strengen Modus) → Import als Hintergrundjob mit Fortschritt und Ergebnis.
 * Das Ergebnis zeigt ehrlich, was passiert ist (grün nur ohne Fehler); von dort geht es zurück zur Zuordnung oder
 * die abgelehnten Zeilen lassen sich als Entwurf nachholen. Vor dem Import legt das Backend eine Sicherung an.
 * Solange der Dialog den Job zeigt, gehört er nicht in die Pille des Job-Docks (`useInlineJob`); wird er vor dem Ende
 * geschlossen, übernimmt das Dock und meldet den Abschluss mit der Schlussmeldung des Backends („Import fertig: 120 neu,
 * 2 abgelehnt“ – bei abgelehnten Zeilen als Warnung mit dem ersten Grund).
 *
 * Vorbereitete Tabelle (`initialUpload`, z. B. „Bauteile anlegen …“ des Bibliotheksimports: schon hochgeladen, mit
 * Token): Schritt 1 zeigt statt der Drop-Zone die Tabelle (mit „Andere Datei wählen“); „Weiter“ liest sie für die
 * gewählte Kategorie (`importRepreview`) und geht wie nach einem Upload zur Zuordnung.
 */
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import {
  ArrowLeft,
  ArrowRight,
  CircleAlert,
  CircleCheck,
  CircleX,
  FilePen,
  FileSpreadsheet,
  ListChecks,
  Plus,
  RefreshCw,
  Sheet,
  TableProperties,
  TriangleAlert,
  Upload,
  X,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { cleanErrorText, errorMessage } from '@/api/client'
import { jobCancelText, trackJob, useInlineJob, useJob } from '@/api/jobs'
import type { Job } from '@/api/system'
import { useCategories, type CategoryDef, type FieldDef } from '@/api/library'
import {
  partsApi,
  PART_NUMBER,
  type ImportCheck,
  type ImportHeaderRow,
  type ImportMode,
  type ImportPreview,
  type ImportResult,
  type ImportRowStatus,
  type ImportRowStatusName,
  type MappingItem,
} from '@/api/parts'
import { FileDropZone } from '@/components/data/FileDropZone'
import { CATEGORY_GROUP_ORDER, CATEGORY_GROUPS } from '@/components/data/categoryTreeItems'
import { CategoryIcon } from '@/components/data/CategoryIcon'
import {
  Badge,
  Button,
  Callout,
  Combobox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Input,
  ProgressBar,
  SegmentedControl,
  Select,
  Skeleton,
  Spinner,
  Stepper,
  Switch,
  Tooltip,
  type ComboboxOption,
  type SelectGroupDef,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { FieldInput } from '../components/FieldInput'
import { BOOKKEEPING, FIELD_GROUPS, groupOf } from '../model/fields'

type Step = 0 | 1 | 2 | 3

const STEPS = [
  { id: 'datei', get label() { return t("Datei") } },
  { id: 'zuordnung', get label() { return t("Zuordnung") } },
  { id: 'pruefen', get label() { return t("Prüfen") } },
  { id: 'import', label: 'Import' },
]

const ACCEPT = {
  'text/csv': ['.csv', '.tsv', '.txt'],
  'text/plain': ['.csv', '.tsv', '.txt'],
  'text/tab-separated-values': ['.tsv'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'application/vnd.ms-excel.sheet.macroEnabled.12': ['.xlsm'],
  'application/vnd.oasis.opendocument.spreadsheet': ['.ods'],
  'application/vnd.ms-excel': ['.csv'],
}

const NONE = '__none__'

interface DefaultRow {
  id: number
  column: string | null
  value: string
}

/** Schon hochgeladene Tabelle (Token des Tabellen-Imports), z. B. aus dem Bibliotheksimport */
export interface ImportWizardUpload {
  token: string
  fileName: string
  rows: number
  /** Herkunft für die Anzeige, z. B. die Bibliotheksdatei („Resistors.SchLib“) */
  label?: string
}

export interface ImportWizardProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  defaultTable: string | null
  /** Import fertig (Tabelle neu laden, ggf. Kategorie wechseln) */
  onImported: (table: string, result: ImportResult) => void
  /** Vorbereitete Tabelle: Schritt 1 zeigt sie statt der Drop-Zone, „Weiter“ geht zur Zuordnung */
  initialUpload?: ImportWizardUpload | null
}

let defaultCounter = 0

export function ImportWizard({ open, onOpenChange, defaultTable, onImported, initialUpload = null }: ImportWizardProps) {
  const { t } = useI18n()
  const categories = useCategories()
  const [step, setStep] = useState<Step>(0)
  /** vorbereitete Tabelle (statt der Drop-Zone) – `null` nach „Andere Datei wählen“ */
  const [prepared, setPrepared] = useState<ImportWizardUpload | null>(initialUpload)
  /** Herkunft der gelesenen Tabelle (vorbereitete Tabelle) für die Beschreibung */
  const [previewLabel, setPreviewLabel] = useState<string | null>(null)
  const [table, setTable] = useState<string | null>(defaultTable)
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [mapping, setMapping] = useState<MappingItem[]>([])
  const [headerRow, setHeaderRow] = useState<ImportHeaderRow>('auto')
  const [defaults, setDefaults] = useState<DefaultRow[]>([])
  const [mode, setMode] = useState<ImportMode>('skip')
  const [allowIncomplete, setAllowIncomplete] = useState(false)
  /** Strenger Modus: nicht lesbare Werte (keine Zahl, falsche Einheit, kein Datum …) lehnen die Zeile ab */
  const [strict, setStrict] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [headerNote, setHeaderNote] = useState<string | null>(null)

  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setStep(0)
      setTable(defaultTable ?? categories.data?.[0]?.table ?? null)
      setPreview(null)
      setMapping([])
      setHeaderRow('auto')
      setDefaults([])
      setMode('skip')
      setAllowIncomplete(false)
      setStrict(false)
      setJobId(null)
      setError(null)
      setHeaderNote(null)
      setPrepared(initialUpload)
      setPreviewLabel(null)
    }
  }

  const category = categories.data?.find((c) => c.table === table) ?? null
  const fields = useMemo(() => new Map((category?.fields ?? []).map((f) => [f.column, f])), [category])

  const applyPreview = (p: ImportPreview) => {
    setPreview(p)
    setMapping(p.mapping)
    setError(null)
  }

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const first = await partsApi.importPreview(file, table, 'auto')
      // Keine Spalte erkannt (z. B. Titelzeilen über der Tabelle) → die nächsten Zeilen als Kopfzeile probieren
      if (!table || first.mapping.some((m) => m.column)) return { preview: first, headerRow: 'auto' as ImportHeaderRow }
      let best: { preview: ImportPreview; headerRow: ImportHeaderRow; mapped: number } | null = null
      const last = Math.min(6, first.row_count + 1)
      for (let row = 1; row <= last; row++) {
        if (row === first.header_row) continue
        try {
          const p = await partsApi.importRepreview(first.token, { table, sheet: first.sheet, headerRow: row })
          const mapped = p.mapping.filter((m) => m.column).length
          if (mapped >= 2 && (!best || mapped > best.mapped)) best = { preview: p, headerRow: row, mapped }
        } catch {
          // Zeile nicht lesbar – nächste probieren
        }
      }
      return best ? { preview: best.preview, headerRow: best.headerRow } : { preview: first, headerRow: 'auto' as ImportHeaderRow }
    },
    meta: { silentError: true },
    onSuccess: ({ preview: p, headerRow: hr }) => {
      applyPreview(p)
      setHeaderRow(hr)
      setHeaderNote(hr === 'auto' ? null : t("Kopfzeile in Zeile {1} erkannt – darüber stehen Titelzeilen.", { 1: hr ?? '' }))
      setPreviewLabel(null)
      setStep(1)
    },
    onError: (err) => setError(errorMessage(err)),
  })

  /** Vorbereitete Tabelle für die gewählte Kategorie lesen – weiter wie nach einem Upload */
  const readPrepared = useMutation({
    mutationFn: (upload: ImportWizardUpload) => partsApi.importRepreview(upload.token, { table, sheet: null, headerRow: 'auto' }),
    meta: { silentError: true },
    onSuccess: (p, upload) => {
      applyPreview(p)
      setHeaderRow('auto')
      setHeaderNote(null)
      setPreviewLabel(upload.label ?? null)
      setStep(1)
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const repreview = useMutation({
    mutationFn: (opts: { table: string | null; sheet?: string | null; headerRow: ImportHeaderRow }) =>
      partsApi.importRepreview(preview?.token as string, opts),
    meta: { silentError: true },
    onSuccess: applyPreview,
    onError: (err) => setError(errorMessage(err)),
  })

  const run = useMutation({
    /** `retryDrafts`: abgelehnte Zeilen als Entwurf nachholen (bereits importierte sind dann vorhanden → überspringen) */
    mutationFn: (opts: { retryDrafts?: boolean }) =>
      partsApi.importRun({
        token: preview?.token as string,
        table: table as string,
        mapping: mapping.filter((m) => m.column),
        mode: opts.retryDrafts ? 'skip' : mode,
        sheet: preview?.sheet ?? null,
        header_row: headerRow,
        defaults: Object.fromEntries(defaults.filter((d) => d.column && d.value.trim()).map((d) => [d.column as string, d.value.trim()])),
        allow_incomplete: opts.retryDrafts ? true : allowIncomplete,
        strict,
        author: null,
      }),
    meta: { silentError: true },
    onSuccess: ({ job }, opts) => {
      // Ergebnis zeigt der Dialog selbst (inline, nicht in der Pille); schließt er vorher, übernimmt das Job-Dock samt
      // Toast (`useInlineJob`) – Erfolg mit der Schlussmeldung des Backends, Teilerfolg als Warnung
      trackJob(job, { dock: false, toast: false, warnWhen: (j) => importProblem(j.result) })
      if (opts.retryDrafts) setAllowIncomplete(true)
      setJobId(job.id)
      setStep(3)
    },
    onError: (err) => setError(errorMessage(err)),
  })

  const { job } = useJob<ImportResult>(jobId, {
    onDone: (j) => {
      if (j.result) onImported(j.result.table, j.result)
    },
  })
  // Inline gezeigt, solange der Dialog offen ist – danach meldet ein noch laufender Import sich über das Job-Dock
  useInlineJob(open ? jobId : null)

  // Probelauf des Backends je Zeile – im Schritt „Prüfen“ für die aktuelle Zuordnung und alle Optionen
  const fixedValues = useMemo(
    () => Object.fromEntries(defaults.filter((d) => d.column && d.value.trim()).map((d) => [d.column as string, d.value.trim()])),
    [defaults],
  )
  const dryRun = useQuery({
    queryKey: [
      'parts',
      'import-check',
      preview?.token ?? '',
      table,
      preview?.sheet ?? null,
      headerRow,
      mapping,
      mode,
      fixedValues,
      allowIncomplete,
      strict,
    ] as const,
    queryFn: ({ signal }) =>
      partsApi.importRepreview(
        preview?.token as string,
        { table, sheet: preview?.sheet ?? null, headerRow, check: { mapping, mode, defaults: fixedValues, allowIncomplete, strict } },
        signal,
      ),
    enabled: open && step === 2 && Boolean(preview?.token && table) && mapping.some((m) => m.column),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: false,
  })

  /** Schließen: läuft der Import noch, übernimmt das Job-Dock (Pille, Abschluss-Toast – siehe `useInlineJob`) */
  const close = (o: boolean) => onOpenChange(o)

  // ------------------------------------------------------------------ Zuordnung auswerten
  const mapped = mapping.filter((m) => m.column)
  const mappedColumns = new Set(mapped.map((m) => m.column as string))
  const defaultColumns = new Set(defaults.filter((d) => d.column && d.value.trim()).map((d) => d.column as string))
  const requiredMissing = (category?.fields ?? []).filter(
    (f) =>
      f.required &&
      !mappedColumns.has(f.column) &&
      !defaultColumns.has(f.column) &&
      f.column !== 'Description' && // entsteht aus der Vorlage
      !(f.column === PART_NUMBER && (mappedColumns.has('Manufacturer Part Number') || defaultColumns.has('Manufacturer Part Number'))),
  )

  const setColumn = (index: number, column: string | null) => {
    setMapping((list) =>
      list.map((m) => {
        if (m.index === index) {
          const field = column ? fields.get(column) : undefined
          const unitKind = field && (field.kind === 'quantity' || field.kind === 'range') && field.unit
          return { ...m, column, score: column ? m.score : 0, unit_hint: unitKind ? m.unit_hint : null, unit_note: unitKind ? m.unit_note : null }
        }
        // 1:1 – ein Feld nur einer Spalte zuordnen
        return column && m.column === column ? { ...m, column: null, score: 0, unit_hint: null, unit_note: null } : m
      }),
    )
  }

  const canNext = step === 1 ? mapped.length > 0 && !repreview.isPending : true
  const result = job?.status === 'done' ? job.result : undefined
  const outcome = result ? importOutcome(result) : null
  const title =
    step !== 3
      ? t("Bauteile importieren")
      : job?.status === 'failed'
        ? t("Import fehlgeschlagen")
        : job?.status === 'cancelled'
          ? t("Import abgebrochen")
          : outcome === 'failed'
            ? t("Nichts importiert")
            : outcome === 'partial'
              ? t("Teilweise importiert")
              : outcome === 'success'
                ? t("Import abgeschlossen")
                : t("Import läuft")
  const draftable = result ? draftableRows(result) : 0
  // Würde jede Zeile abgelehnt? Laut Probelauf (sonst: Pflichtfeld weder zugeordnet noch fest gesetzt, ohne Entwurf)
  const counts = dryRun.data?.check?.counts
  const allRejected = counts
    ? (counts.reject ?? 0) > 0 && (counts.create ?? 0) + (counts.update ?? 0) + (counts.unchanged ?? 0) + (counts.skip ?? 0) === 0
    : requiredMissing.length > 0 && !allowIncomplete
  // Probelauf über alle Zeilen, und keine würde geschrieben (abgelehnt, übersprungen, unverändert): nichts zu importieren –
  // sonst liefe ein Job samt Sicherung, der nichts ändert
  // nur aus einem frischen Probelauf – nicht aus dem vorigen, der während einer Änderung stehen bleibt
  const freshCheck = dryRun.isPlaceholderData ? null : (dryRun.data?.check ?? null)
  const nothing = nothingToImport(freshCheck)
  const busyClose = run.isPending
  const backToMapping = () => {
    setJobId(null)
    setError(null)
    setStep(1)
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !busyClose && close(o)}>
      <DialogContent size="xl" className="max-w-[min(68rem,calc(100vw-48px))]">
        <DialogHeader
          icon={<Upload />}
          title={title}
          description={
            step === 0
              ? prepared
                ? t("Die Tabelle ist vorbereitet – Zielkategorie wählen, dann ordnet PartForge die Spalten zu. Vorher legt PartForge eine Sicherung an.")
                : t("Spalten werden automatisch den Feldern zugeordnet – Sie prüfen vor dem Import. Vorher legt PartForge eine Sicherung an.")
              : preview
                ? `${preview.file_name}${previewLabel ? ` (${previewLabel})` : ''} · ${plural(preview.row_count, t("Zeile"), t("Zeilen"))}`
                : undefined
          }
        />
        <div className="shrink-0 px-6 pb-3 pt-1">
          <Stepper
            steps={STEPS}
            current={step === 3 && outcome === 'success' ? STEPS.length : step}
            compact
            onStepClick={step < 3 ? (i) => setStep(i as Step) : undefined}
          />
        </div>
        <DialogBody className="flex min-h-[22rem] flex-col gap-4 border-t border-line pt-4">
          {error && (
            <Callout tone="danger" title={t("Das hat nicht geklappt")} urgent actions={<Button size="sm" variant="ghost" iconOnly aria-label={t("Hinweis schließen")} onClick={() => setError(null)}><X /></Button>}>
              {localizeMessage(error)}
            </Callout>
          )}
          {step === 0 && (
            <StepFile
              categories={categories.data ?? []}
              table={table}
              onTable={setTable}
              busy={upload.isPending}
              onFile={(file) => upload.mutate(file)}
              prepared={prepared}
              onDropPrepared={() => {
                setPrepared(null)
                setError(null)
              }}
            />
          )}
          {step === 1 && preview && category && (
            <StepMapping
              category={category}
              preview={preview}
              mapping={mapping}
              headerRow={headerRow}
              headerNote={headerNote}
              busy={repreview.isPending}
              requiredMissing={requiredMissing}
              defaults={defaults}
              onDefaults={setDefaults}
              onColumn={setColumn}
              onUnitHint={(index, hint) => setMapping((list) => list.map((m) => (m.index === index ? { ...m, unit_hint: hint || null } : m)))}
              onTable={(t) => {
                setTable(t)
                setDefaults([])
                repreview.mutate({ table: t, sheet: preview.sheet, headerRow })
              }}
              onSheet={(sheet) => repreview.mutate({ table, sheet, headerRow })}
              onHeaderRow={(hr) => {
                setHeaderRow(hr)
                setHeaderNote(null)
                repreview.mutate({ table, sheet: preview.sheet, headerRow: hr })
              }}
              categories={categories.data ?? []}
            />
          )}
          {step === 2 && preview && category && (
            <StepReview
              category={category}
              preview={dryRun.data ?? preview}
              checking={dryRun.isFetching}
              checkError={dryRun.error ? errorMessage(dryRun.error) : null}
              mapping={mapped}
              defaults={defaults}
              mode={mode}
              onMode={setMode}
              allowIncomplete={allowIncomplete}
              onAllowIncomplete={setAllowIncomplete}
              strict={strict}
              onStrict={setStrict}
              requiredMissing={requiredMissing}
              allRejected={allRejected}
              nothing={nothing}
              onBack={() => setStep(1)}
            />
          )}
          {step === 3 && <StepRun job={job} fields={fields} categories={categories.data ?? []} />}
        </DialogBody>
        <DialogFooter className="justify-between">
          <div>
            {step > 0 && step < 3 && (
              <Button variant="ghost" leftIcon={<ArrowLeft />} onClick={() => setStep((s) => (s - 1) as Step)}>
                {t("Zurück")}
              </Button>
            )}
            {step === 3 && preview && (outcome === 'failed' || outcome === 'partial' || job?.status === 'failed') && (
              <Button variant="ghost" leftIcon={<ArrowLeft />} onClick={backToMapping}>
                {t("Zurück zur Zuordnung")}
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            {step < 3 && (
              <Button variant="ghost" onClick={() => close(false)}>
                {t("Abbrechen")}
              </Button>
            )}
            {step === 0 && prepared && (
              <Button
                variant="primary"
                rightIcon={<ArrowRight />}
                loading={readPrepared.isPending}
                disabled={!table}
                onClick={() => readPrepared.mutate(prepared)}
              >
                {t("Weiter zur Zuordnung")}
              </Button>
            )}
            {step === 1 && (
              <Button variant="primary" rightIcon={<ArrowRight />} disabled={!canNext} onClick={() => setStep(2)}>
                {t("Weiter zur Prüfung")}
              </Button>
            )}
            {step === 2 && preview && (
              <Button
                variant="primary"
                leftIcon={<Upload />}
                loading={run.isPending}
                disabled={allRejected || (nothing !== null && !nothing.partial)}
                onClick={() => run.mutate({})}
              >
                {importLabel(preview.row_count, freshCheck)}
              </Button>
            )}
            {step === 3 && draftable > 0 && (
              <Button variant="secondary" leftIcon={<FilePen />} loading={run.isPending} onClick={() => run.mutate({ retryDrafts: true })}>
                {draftable === 1 ? t("Abgelehnte Zeile als Entwurf importieren") : t("{1} abgelehnte als Entwurf importieren", { 1: formatNumber(draftable) })}
              </Button>
            )}
            {step === 3 && (
              <Button variant={outcome === 'success' ? 'primary' : 'secondary'} onClick={() => close(false)}>
                {job && (job.status === 'queued' || job.status === 'running')
                  ? t("Im Hintergrund weiterlaufen lassen")
                  : outcome === 'success'
                    ? t("Fertig")
                    : t("Schließen")}
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// --------------------------------------------------------------------------- Schritt 1: Datei

function categoryGroups(list: CategoryDef[], translate = t): SelectGroupDef[] {
  const map = new Map<string, CategoryDef[]>()
  for (const c of list) {
    const g = CATEGORY_GROUPS[c.table] ?? 'Weitere'
    map.set(g, [...(map.get(g) ?? []), c])
  }
  return [...map.entries()]
    .sort(([a], [b]) => CATEGORY_GROUP_ORDER.indexOf(a) - CATEGORY_GROUP_ORDER.indexOf(b))
    .map(([label, items]) => ({
      label: translate(label),
      options: items.map((c) => ({ value: c.table, label: metadataLabel(c.label, translate), icon: <CategoryIcon name={c.icon} color={c.color} /> })),
    }))
}

function StepFile({
  categories,
  table,
  onTable,
  busy,
  onFile,
  prepared,
  onDropPrepared,
}: {
  categories: CategoryDef[]
  table: string | null
  onTable: (t: string) => void
  busy: boolean
  onFile: (file: File) => void
  /** vorbereitete Tabelle statt der Drop-Zone */
  prepared: ImportWizardUpload | null
  /** „Andere Datei wählen“: zurück zur Drop-Zone */
  onDropPrepared: () => void
}) {
  const { t } = useI18n()
  const groups = useMemo(() => categoryGroups(categories, t), [categories, t])
  if (prepared) {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex max-w-sm flex-col gap-1.5">
          <label htmlFor="imp-category" className="text-ui font-medium text-fg">
            {t("Zielkategorie")}
          </label>
          <Select id="imp-category" value={table ?? undefined} onValueChange={onTable} groups={groups} placeholder={t("Kategorie wählen …")} />
          <p className="text-xs text-fg-muted">{t("Alle Zeilen der Tabelle kommen in diese Kategorie.")}</p>
        </div>
        <section
          aria-label={t("Vorbereitete Tabelle")}
          className="flex items-center gap-3 rounded-card border border-line bg-surface-2/50 px-4 py-3"
        >
          <span
            aria-hidden
            className="flex size-10 shrink-0 items-center justify-center rounded-button border border-line-strong bg-surface text-fg-muted [&_svg]:size-5"
          >
            <FileSpreadsheet />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-ui font-medium text-fg [overflow-wrap:anywhere]">{prepared.label ?? prepared.fileName}</p>
            <p className="text-xs text-fg-muted">
              {prepared.label ? `${prepared.fileName} · ` : ''}
              {plural(prepared.rows, t("Zeile"), t("Zeilen"))}  {t("· vorbereitet vom Bibliotheksimport")}
            </p>
          </div>
          <Button size="sm" variant="ghost" leftIcon={<Upload />} onClick={onDropPrepared}>
            {t("Andere Datei wählen")}
          </Button>
        </section>
        <ul className="grid grid-cols-3 gap-3 text-xs text-fg-muted">
          <li className="flex items-start gap-2">
            <TableProperties aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
            {t("Je Zeile ein Symbol mit seinen Parametern – Teilenummer, Beschreibung, Kommentar.")}
          </li>
          <li className="flex items-start gap-2">
            <Sheet aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
            {t("Symbol und Footprint stehen schon als Verweise darin (Library Ref, Footprint Ref).")}
          </li>
          <li className="flex items-start gap-2">
            <CircleCheck aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
            {t("Im nächsten Schritt prüfen Sie die Zuordnung der Spalten.")}
          </li>
        </ul>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="flex max-w-sm flex-col gap-1.5">
        <label htmlFor="imp-category" className="text-ui font-medium text-fg">
          {t("Zielkategorie")}
        </label>
        <Select id="imp-category" value={table ?? undefined} onValueChange={onTable} groups={groups} placeholder={t("Kategorie wählen …")} />
      </div>
      <FileDropZone
        variant="table"
        size="md"
        multiple={false}
        accept={ACCEPT}
        typesLabel={t("CSV, Excel oder OpenDocument")}
        hint={t("CSV, TSV, XLSX oder ODS · bis 50 MB · eine Datei")}
        maxSize={50 * 1024 * 1024}
        disabled={!table}
        busy={busy ? t("Tabelle wird gelesen und zugeordnet …") : false}
        title={t("Tabelle hierher ziehen")}
        description={t("Auch OpenDocument (.ods) und Tab-getrennte Dateien (.tsv) – Trennzeichen und Zeichensatz werden erkannt.")}
        onFiles={([file]) => file && onFile(file)}
      />
      <ul className="grid grid-cols-3 gap-3 text-xs text-fg-muted">
        <li className="flex items-start gap-2">
          <TableProperties aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
          {t("Kopfzeile wird erkannt, auch wenn darüber Titelzeilen stehen.")}
        </li>
        <li className="flex items-start gap-2">
          <Sheet aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
          {t("Einheiten im Spaltenkopf („Kapazität (pF)“) gelten für reine Zahlen.")}
        </li>
        <li className="flex items-start gap-2">
          <CircleCheck aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
          {t("Vorhandene Teilenummern: überspringen oder aktualisieren.")}
        </li>
      </ul>
    </div>
  )
}

// --------------------------------------------------------------------------- Schritt 2: Zuordnung

function fieldOptions(category: CategoryDef, translate = t): ComboboxOption[] {
  const label = new Map(FIELD_GROUPS.map((g) => [g.id, metadataLabel(g.label, t)]))
  return [
    { value: NONE, label: t("Nicht importieren"), group: t("Auswahl") },
    ...category.fields
      .filter((f) => !BOOKKEEPING.has(f.column))
      .map((f) => ({
        value: f.column,
        label: metadataLabel(f.label, translate),
        description: f.unit ? `${f.column} · ${f.unit}` : f.column !== f.label ? f.column : undefined,
        keywords: [f.column],
        group: label.get(groupOf(f)),
      })),
  ]
}

function ScoreBadge({ item }: { item: MappingItem }) {
  const { t } = useI18n()
  if (!item.column) return <span className="text-2xs text-fg-subtle">–</span>
  const score = Math.round(item.score)
  if (score <= 0) return <Badge variant="outline">{t("manuell")}</Badge>
  const variant = score >= 95 ? 'success' : score >= 85 ? 'accent' : 'warning'
  return (
    <Tooltip content={score >= 95 ? t("Spaltenname passt genau") : t("Ähnlicher Spaltenname – bitte prüfen")}>
      <Badge variant={variant} className="tabular-nums">
        {score} %
      </Badge>
    </Tooltip>
  )
}

function StepMapping({
  category,
  preview,
  mapping,
  headerRow,
  headerNote,
  busy,
  requiredMissing,
  defaults,
  onDefaults,
  onColumn,
  onUnitHint,
  onTable,
  onSheet,
  onHeaderRow,
  categories,
}: {
  category: CategoryDef
  preview: ImportPreview
  mapping: MappingItem[]
  headerRow: ImportHeaderRow
  headerNote: string | null
  busy: boolean
  requiredMissing: FieldDef[]
  defaults: DefaultRow[]
  onDefaults: (d: DefaultRow[]) => void
  onColumn: (index: number, column: string | null) => void
  onUnitHint: (index: number, hint: string) => void
  onTable: (table: string) => void
  onSheet: (sheet: string) => void
  onHeaderRow: (hr: ImportHeaderRow) => void
  categories: CategoryDef[]
}) {
  const { t } = useI18n()
  const options = useMemo(() => fieldOptions(category, t), [category, t])
  const fields = new Map(category.fields.map((f) => [f.column, f]))
  const groups = useMemo(() => categoryGroups(categories, t), [categories, t])
  const samples = (index: number) =>
    preview.rows
      .map((r) => r[index])
      .filter((v): v is string => Boolean(v && v.trim()))
      .slice(0, 3)
  const headerValue = headerRow === 'auto' ? 'auto' : headerRow === null ? 'none' : String(headerRow)
  const mappedCount = mapping.filter((m) => m.column).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex min-w-[14rem] flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-muted">{t("Zielkategorie")}</span>
          <Select value={category.table} onValueChange={onTable} groups={groups} size="sm" aria-label={t("Zielkategorie")} />
        </div>
        {preview.sheets.length > 1 && (
          <div className="flex min-w-[12rem] flex-col gap-1.5">
            <span className="text-xs font-medium text-fg-muted">{t("Tabellenblatt")}</span>
            <Select
              size="sm"
              value={preview.sheet ?? preview.sheets[0]}
              onValueChange={onSheet}
              options={preview.sheets.map((s) => ({ value: s, label: s }))}
              aria-label={t("Tabellenblatt")}
            />
          </div>
        )}
        <div className="flex min-w-[12rem] flex-col gap-1.5">
          <span className="text-xs font-medium text-fg-muted">{t("Kopfzeile")}</span>
          <Select
            size="sm"
            value={headerValue}
            onValueChange={(v) => onHeaderRow(v === 'auto' ? 'auto' : v === 'none' ? null : Number(v))}
            options={[
              {
                value: 'auto',
                label: headerRow === 'auto' && preview.header_row ? t("Automatisch (Zeile {1})", { 1: preview.header_row }) : t("Automatisch"),
              },
              ...Array.from({ length: 8 }, (_, i) => ({ value: String(i + 1), label: t("Zeile {1}", { 1: i + 1 }) })),
              { value: 'none', label: t("Keine Kopfzeile") },
            ]}
            aria-label={t("Kopfzeile")}
          />
        </div>
        <div className="ml-auto flex items-center gap-2 pb-1 text-xs text-fg-muted">
          {busy && <Spinner size={13} tone="accent" />}
          <FileSpreadsheet aria-hidden className="size-3.5 text-fg-subtle" />
          {[
            preview.encoding && preview.encoding.toUpperCase(),
            preview.delimiter && t("Trennzeichen „{1}“", { 1: preview.delimiter === '\t' ? 'Tab' : preview.delimiter }),
            t("{1} von {2} Spalten zugeordnet", { 1: mappedCount, 2: mapping.length }),
          ]
            .filter(Boolean)
            .join(' · ')}
        </div>
      </div>

      {headerNote && (
        <Callout tone="info" live>
          {headerNote}
        </Callout>
      )}
      {mappedCount === 0 && !busy && (
        <Callout tone="warning" title={t("Keine Spalte zugeordnet")}>
          {t("Stimmt die Kopfzeile? Wählen Sie oben die Zeile mit den Spaltennamen – oder ordnen Sie die Spalten unten von Hand zu.")}
        </Callout>
      )}
      <div className={cn('overflow-hidden rounded-card border border-line', busy && 'opacity-60')}>
        <table className="w-full table-fixed text-left text-ui">
          <caption className="sr-only">{t("Zuordnung der Spalten zu Feldern")}</caption>
          <thead className="bg-surface-2/70 text-xs text-fg-muted">
            <tr>
              <th scope="col" className="w-[34%] px-3 py-2 font-medium">
                {t("Spalte in der Datei")}
              </th>
              <th scope="col" className="w-8">
                <span className="sr-only">{t("wird zu")}</span>
              </th>
              <th scope="col" className="px-3 py-2 font-medium">
                {t("Feld in PartForge")}
              </th>
              <th scope="col" className="w-24 px-3 py-2 font-medium">
                {t("Treffer")}
              </th>
              <th scope="col" className="w-36 px-3 py-2 font-medium">
                {t("Einheit")}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {mapping.map((m) => {
              const field = m.column ? fields.get(m.column) : undefined
              const unitField = field && (field.kind === 'quantity' || field.kind === 'range') && field.unit
              const vals = samples(m.index)
              return (
                <tr key={m.index} className={cn('align-top', !m.column && 'bg-surface-2/20')}>
                  <td className="px-3 py-2">
                    <div className={cn('truncate font-medium', m.column ? 'text-fg' : 'text-fg-muted')} title={m.header}>
                      {m.header || t("Spalte {1}", { 1: m.index + 1 })}
                    </div>
                    <div className="mono mt-0.5 truncate text-2xs text-fg-subtle" title={vals.join(' · ')}>
                      {vals.length ? vals.join(' · ') : t('leer')}
                    </div>
                  </td>
                  <td className="py-2.5 text-fg-subtle">
                    <ArrowRight aria-hidden className="size-3.5" />
                  </td>
                  <td className="px-3 py-1.5">
                    <Combobox
                      options={options}
                      value={m.column ?? NONE}
                      onValueChange={(v) => onColumn(m.index, !v || v === NONE ? null : v)}
                      size="sm"
                      searchPlaceholder={t("Feld suchen …")}
                      aria-label={t("Feld für Spalte „{1}“", { 1: m.header })}
                    />
                  </td>
                  <td className="px-3 py-2">
                    <ScoreBadge item={m} />
                  </td>
                  <td className="px-3 py-1.5">
                    {unitField ? (
                      <Tooltip content={m.unit_note ? localizeMessage(m.unit_note) : t("Reine Zahlen in dieser Spalte werden als … {1} gelesen (z. B. „k{2}“).", { 1: field.unit ?? '', 2: field.unit ?? '' })}>
                        <span className="block">
                          <Input
                            size="sm"
                            mono
                            value={m.unit_hint ?? ''}
                            onChange={(e) => onUnitHint(m.index, e.target.value)}
                            placeholder={field.unit ?? ''}
                            aria-label={t("Einheit für Spalte „{1}“", { 1: m.header })}
                          />
                        </span>
                      </Tooltip>
                    ) : (
                      <span className="text-2xs text-fg-subtle">–</span>
                    )}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <DefaultsEditor category={category} defaults={defaults} onChange={onDefaults} mapped={new Set(mapping.map((m) => m.column ?? ''))} />

      {requiredMissing.length > 0 && (
        <Callout tone="warning" title={t("{1} Zuordnung", { 1: plural(requiredMissing.length, t("Pflichtfeld ohne"), t("Pflichtfelder ohne")) })}>
          {requiredMissing.map((f) => metadataLabel(f.label, t)).join(', ')}  {t("– Spalte zuordnen, oben als festen Wert setzen oder beim Import „Unvollständige als Entwurf“ wählen.")}
        </Callout>
      )}
    </div>
  )
}

function DefaultsEditor({
  category,
  defaults,
  onChange,
  mapped,
}: {
  category: CategoryDef
  defaults: DefaultRow[]
  onChange: (d: DefaultRow[]) => void
  mapped: Set<string>
}) {
  const { t } = useI18n()
  const options = useMemo(() => fieldOptions(category, t).filter((o) => o.value !== NONE), [category, t])
  const fields = new Map(category.fields.map((f) => [f.column, f]))
  return (
    <section className="flex flex-col gap-2" aria-labelledby="imp-defaults">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h3 id="imp-defaults" className="text-ui font-medium text-fg">
            {t("Feste Werte für alle Zeilen")}
          </h3>
          <p className="text-xs text-fg-muted">{t("Füllt leere Zellen – z. B. Hersteller, Symbol oder Footprint, wenn sie in der Datei fehlen.")}</p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          leftIcon={<Plus />}
          onClick={() => onChange([...defaults, { id: ++defaultCounter, column: null, value: '' }])}
        >
          {t("Fester Wert")}
        </Button>
      </div>
      {defaults.length > 0 && (
        <ul className="flex flex-col gap-2">
          {defaults.map((d) => {
            const field = d.column ? fields.get(d.column) : undefined
            return (
              <li key={d.id} className="grid grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto] items-start gap-2">
                <Combobox
                  options={options.map((o) => ({ ...o, description: mapped.has(o.value) ? t("auch aus der Datei") : o.description }))}
                  value={d.column}
                  onValueChange={(column) => onChange(defaults.map((x) => (x.id === d.id ? { ...x, column, value: '' } : x)))}
                  size="sm"
                  placeholder={t("Feld wählen …")}
                  searchPlaceholder={t("Feld suchen …")}
                  aria-label={t("Feld")}
                />
                {field ? (
                  <FieldInput
                    field={field}
                    table={category.table}
                    value={d.value}
                    size="sm"
                    onChange={(value) => onChange(defaults.map((x) => (x.id === d.id ? { ...x, value } : x)))}
                    aria-label={t("Fester Wert für {1}", { 1: metadataLabel(field.label, t) })}
                  />
                ) : (
                  <span className="flex h-7 items-center text-xs text-fg-subtle">{t("← Feld wählen")}</span>
                )}
                <Button size="sm" variant="ghost" iconOnly aria-label={t("Festen Wert entfernen")} onClick={() => onChange(defaults.filter((x) => x.id !== d.id))}>
                  <X />
                </Button>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

// --------------------------------------------------------------------------- Schritt 3: Prüfen

const MODES: { value: ImportMode; label: string; description: string }[] = [
  { value: 'skip', get label() { return t("Überspringen") }, get description() { return t("Vorhandene Teilenummern bleiben unverändert.") } },
  { value: 'update', get label() { return t("Aktualisieren") }, get description() { return t("Gefüllte Zellen überschreiben vorhandene Werte; leere Zellen löschen nichts.") } },
  { value: 'error', get label() { return t("Als Fehler melden") }, get description() { return t("Vorhandene Teilenummern werden nicht importiert und im Ergebnis aufgeführt.") } },
]

/** Ergebnis des Probelaufs je Zeile */
const STATUS_META: Record<ImportRowStatusName, { label: string; variant: 'success' | 'neutral' | 'info' | 'danger' | 'outline' }> = {
  create: { get label() { return t("neu") }, variant: 'success' },
  update: { label: 'aktualisieren', variant: 'info' },
  unchanged: { get label() { return t("unverändert") }, variant: 'outline' },
  skip: { get label() { return t("übersprungen") }, variant: 'neutral' },
  reject: { get label() { return t("abgelehnt") }, variant: 'danger' },
}
const STATUS_ORDER: ImportRowStatusName[] = ['create', 'update', 'unchanged', 'skip', 'reject']

/** Gründe einer Zeile als Liste (Ablehnung, Feldfehler, fehlende Pflichtfelder, geänderte Felder) */
function rowReasons(st: ImportRowStatus, fields: Map<string, FieldDef>): string[] {
  const label = (col: string) => metadataLabel(fields.get(col)?.label ?? col, t)
  const out = [...st.reasons]
  for (const [col, msg] of Object.entries(st.errors)) {
    if (!out.some((r) => r.includes(msg))) out.push(`${label(col)}: ${msg}`)
  }
  if (st.missing.length && !out.some((r) => /pflicht/i.test(r))) {
    out.push(`${st.status === 'reject' ? t("Pflichtfelder leer") : t("Als Entwurf – leer")}: ${joinGerman(st.missing.map(label))}`)
  }
  if (st.status === 'update' && st.changed.length) out.push(t("Ändert {1}", { 1: joinGerman(st.changed.map(label)) }))
  return out
}

function StepReview({
  category,
  preview,
  checking,
  checkError,
  mapping,
  defaults,
  mode,
  onMode,
  allowIncomplete,
  onAllowIncomplete,
  strict,
  onStrict,
  requiredMissing,
  allRejected,
  nothing,
  onBack,
}: {
  category: CategoryDef
  preview: ImportPreview
  checking: boolean
  checkError: string | null
  mapping: MappingItem[]
  defaults: DefaultRow[]
  mode: ImportMode
  onMode: (m: ImportMode) => void
  allowIncomplete: boolean
  onAllowIncomplete: (v: boolean) => void
  strict: boolean
  onStrict: (v: boolean) => void
  requiredMissing: FieldDef[]
  allRejected: boolean
  /** Laut Probelauf würde keine (geprüfte) Zeile geschrieben – nicht alle abgelehnt, das meldet `allRejected` */
  nothing: NothingToImport | null
  onBack: () => void
}) {
  const { t } = useI18n()
  const fields = new Map(category.fields.map((f) => [f.column, f]))
  const columns = mapping.slice(0, 7)
  const fixedRows = defaults.filter((d) => d.column && d.value.trim())
  const shown = preview.rows.slice(0, 20)
  const statusByRow = new Map(preview.row_status.map((st) => [st.row, st]))
  const check: ImportCheck | null = preview.check
  const rejected = preview.row_status.filter((st) => st.status === 'reject')
  const missingLabels = requiredMissing.map((f) => metadataLabel(f.label, t))
  const nothingParts = nothing
    ? [
        nothing.reject ? t("{1} abgelehnt", { 1: formatNumber(nothing.reject) }) : null,
        nothing.skip ? t("{1} übersprungen", { 1: formatNumber(nothing.skip) }) : null,
        nothing.unchanged ? t("{1} unverändert", { 1: formatNumber(nothing.unchanged) }) : null,
      ].filter((p): p is string => p !== null)
    : []
  return (
    <div className="flex flex-col gap-4">
      {nothing && !allRejected && (
        <Callout
          tone={nothing.partial ? 'info' : 'warning'}
          title={nothing.partial ? t("Die ersten {1} Zeilen ändern nichts", { 1: formatNumber(nothing.checked) }) : t("Nichts zu importieren")}
          actions={
            nothing.skip > 0 && mode !== 'update' ? (
              <Button size="sm" variant="secondary" leftIcon={<RefreshCw />} onClick={() => onMode('update')}>
                {t("Vorhandene aktualisieren")}
              </Button>
            ) : nothing.reject > 0 ? (
              <Button size="sm" variant="secondary" leftIcon={<ArrowLeft />} onClick={onBack}>
                {t("Zur Zuordnung")}
              </Button>
            ) : undefined
          }
        >
          {nothing.partial
            ? t("Von den ersten {1} der {2} Zeilen würde keine ein Bauteil anlegen oder ändern ({3}); die übrigen prüft der Import selbst.", { 1: formatNumber(nothing.checked), 2: formatNumber(nothing.total), 3: joinGerman(nothingParts) })
            : t("Laut Probelauf würde kein Bauteil angelegt oder geändert ({1}).", { 1: joinGerman(nothingParts) })}{' '}
          {nothing.skip > 0 && mode !== 'update'
            ? t("Die Teilenummern gibt es schon – „Vorhandene aktualisieren“ übernimmt die Werte der Datei.")
            : nothing.unchanged > 0 && !nothing.reject
              ? t("Die Bibliothek enthält diese Werte bereits.")
              : t("Die Gründe stehen unten bei den Zeilen.")}
        </Callout>
      )}
      {allRejected && (
        <Callout
          tone="danger"
          title={t("So würde keine Zeile importiert")}
          actions={
            <>
              <Button size="sm" variant="secondary" leftIcon={<ArrowLeft />} onClick={onBack}>
                {t("Zur Zuordnung")}
              </Button>
              {!allowIncomplete && requiredMissing.length > 0 && (
                <Button size="sm" variant="ghost" leftIcon={<FilePen />} onClick={() => onAllowIncomplete(true)}>
                  {t("Als Entwurf importieren")}
                </Button>
              )}
            </>
          }
        >
          {requiredMissing.length > 0 && !allowIncomplete
            ? t("{1} {2} in jeder Zeile (Pflicht). Spalte zuordnen, einen festen Wert setzen – oder die Zeilen als Entwurf übernehmen und später ergänzen.", { 1: joinGerman(missingLabels), 2: requiredMissing.length === 1 ? t("fehlt") : t("fehlen") })
            : t("Der Probelauf lehnt jede geprüfte Zeile ab – die Gründe stehen unten. Zuordnung oder feste Werte anpassen.")}
        </Callout>
      )}
      {checkError && (
        <Callout tone="warning" title={t("Probelauf nicht möglich")}>
          {localizeMessage(checkError)}  {t("Der Import prüft die Zeilen trotzdem selbst.")}
        </Callout>
      )}
      <div className="overflow-hidden rounded-card border border-line">
        <div className={cn('max-h-64 overflow-auto transition-opacity', checking && 'opacity-70')}>
          <table className="w-full min-w-max text-left text-xs">
            <caption className="sr-only">{t("Vorschau der ersten Zeilen mit dem Ergebnis des Probelaufs")}</caption>
            <thead className="sticky top-0 z-sticky bg-surface-2 text-fg-muted">
              <tr>
                <th scope="col" className="w-12 px-3 py-2 text-right font-medium">
                  {t("Zeile")}
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  {t("Ergebnis")}
                </th>
                {columns.map((m) => (
                  <th key={m.index} scope="col" className="px-3 py-2 font-medium">
                    {metadataLabel(fields.get(m.column as string)?.label ?? m.column ?? '', t)}
                  </th>
                ))}
                {mapping.length > columns.length && (
                  <th scope="col" className="px-3 py-2 font-normal text-fg-subtle">
                    + {mapping.length - columns.length}  {t("weitere")}
                  </th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {shown.map((row, i) => {
                const st = statusByRow.get(i)
                return (
                  <tr key={i} className={cn(st?.status === 'reject' && 'bg-danger/5')}>
                    <td className="mono px-3 py-1.5 text-right text-2xs tabular-nums text-fg-subtle">{st?.line ?? i + 1}</td>
                    <td className="px-3 py-1.5">
                      {st ? (
                        <StatusBadge status={st} fields={fields} />
                      ) : checking ? (
                        <Skeleton className="h-4 w-16 rounded-full" />
                      ) : (
                        <span className="text-fg-subtle">–</span>
                      )}
                    </td>
                    {columns.map((m) => {
                      const raw = row[m.index]
                      return (
                        <td key={m.index} className="mono max-w-[16rem] truncate px-3 py-1.5 text-fg">
                          {raw ? (
                            `${raw}${m.unit_hint && /^[-+]?\d+(?:[.,]\d+)?$/.test(raw.trim()) ? ` ${m.unit_hint}` : ''}`
                          ) : (
                            <span className="text-fg-subtle">–</span>
                          )}
                        </td>
                      )
                    })}
                    {mapping.length > columns.length && <td className="px-3 text-fg-subtle">…</td>}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line bg-surface-2/50 px-3 py-1.5 text-2xs text-fg-subtle" aria-live="polite">
          {check ? (
            <>
              <span className="flex items-center gap-1.5">
                {checking ? <Spinner size={10} tone="accent" /> : <ListChecks aria-hidden className="size-3.5" />}
                {t("Probelauf")}{' '}
                {check.truncated ? t("der ersten {1} von {2}", { 1: formatNumber(check.checked), 2: formatNumber(check.total) }) : t("aller {1}", { 1: formatNumber(check.checked) })}{' '}
                {t("Zeilen:")}
              </span>
              {STATUS_ORDER.filter((k) => check.counts[k]).map((k) => (
                <span key={k} className={cn(k === 'reject' ? 'font-medium text-danger-text' : k === 'create' ? 'text-success-text' : 'text-fg-muted')}>
                  {formatNumber(check.counts[k] ?? 0)} {metadataLabel(STATUS_META[k].label, t)}
                </span>
              ))}
            </>
          ) : (
            <span className="flex items-center gap-1.5">
              <Spinner size={10} tone="accent" />  {t("Probelauf läuft …")}
            </span>
          )}
          {fixedRows.length > 0 && (
            <span>{t("· feste Werte:")} {fixedRows.map((d) => `${metadataLabel(fields.get(d.column as string)?.label ?? d.column ?? '', t)} = ${d.value}`).join(', ')}</span>
          )}
        </div>
      </div>

      {rejected.length > 0 && <RejectedRows key={rejected.length} rows={rejected} fields={fields} truncated={Boolean(check?.truncated)} />}

      <div className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-2">
          <span className="text-ui font-medium text-fg">{t("Vorhandene Teilenummern")}</span>
          <SegmentedControl<ImportMode>
            value={mode}
            onValueChange={onMode}
            options={MODES.map((m) => ({ value: m.value, label: metadataLabel(m.label, t) }))}
            aria-label={t("Vorhandene Teilenummern")}
          />
          <p className="text-xs text-fg-muted">{MODES.find((m) => m.value === mode)?.description}</p>
        </div>
        <div className="flex flex-col gap-3">
          <Switch
            checked={allowIncomplete}
            onCheckedChange={onAllowIncomplete}
            label={t("Unvollständige Zeilen als Entwurf importieren")}
            description={t("Leere Pflichtfelder werden dann nur als Hinweis gemeldet – die Bauteile starten als „Entwurf“.")}
          />
          <Switch
            checked={strict}
            onCheckedChange={onStrict}
            label={t("Streng prüfen")}
            description={t("Nicht lesbare Werte (keine Zahl, falsche Einheit, kein Datum) lehnen die Zeile ab, statt nur zu warnen.")}
          />
        </div>
      </div>
      <Callout tone="info" title={t("Sicherung inklusive")}>
        {t("Vor dem Import legt PartForge automatisch eine Sicherung der Datenbank an. Der Import läuft im Hintergrund – Sie können weiterarbeiten.")}
      </Callout>
    </div>
  )
}

function StatusBadge({ status, fields }: { status: ImportRowStatus; fields: Map<string, FieldDef> }) {
  const { t } = useI18n()
  const meta = STATUS_META[status.status]
  const reasons = rowReasons(status, fields)
  const warned = status.status !== 'reject' && status.warnings.length > 0
  const badge = (
    <Badge variant={warned ? 'warning' : meta.variant} dot={warned}>
      {metadataLabel(meta.label, t)}
    </Badge>
  )
  const lines = [...reasons, ...status.warnings]
  if (!lines.length) return badge
  return (
    <Tooltip
      content={
        <ul className="flex max-w-80 flex-col gap-0.5">
          {lines.slice(0, 6).map((r) => (
            <li key={r}>{localizeMessage(r)}</li>
          ))}
          {lines.length > 6 && <li>{t("… und")} {formatNumber(lines.length - 6)}  {t("weitere")}</li>}
        </ul>
      }
    >
      <button type="button" className="inline-flex rounded-full outline-none focus-ring" aria-label={`${meta.label} – ${lines.map(localizeMessage).join('; ')}`}>
        {badge}
      </button>
    </Tooltip>
  )
}

/** Abgelehnte Zeilen des Probelaufs mit Gründen (gleiche Gründe zusammengefasst) */
function RejectedRows({ rows, fields, truncated }: { rows: ImportRowStatus[]; fields: Map<string, FieldDef>; truncated: boolean }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(rows.length <= 4)
  const groups = new Map<string, { reasons: string[]; lines: string[] }>()
  for (const st of rows) {
    const reasons = rowReasons(st, fields)
    const key = reasons.join('\u0001')
    const g = groups.get(key) ?? { reasons, lines: [] }
    g.lines.push(st.part_number ? `${st.line ?? st.row + 1} (${st.part_number})` : String(st.line ?? st.row + 1))
    groups.set(key, g)
  }
  return (
    <section aria-labelledby="imp-rejected" className="overflow-hidden rounded-card border border-danger/25 bg-danger/[0.035]">
      <h3 id="imp-rejected">
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((o) => !o)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-ui font-medium text-fg outline-none focus-ring-inset"
        >
          <CircleX aria-hidden className="size-4 text-danger-text" />
          {plural(rows.length, t("Zeile würde"), t("Zeilen würden"))}  {t("abgelehnt")}
          {truncated && <span className="font-normal text-fg-subtle">{t("(im Probelauf)")}</span>}
          <span className="ml-auto text-xs font-normal text-fg-muted">{open ? t("Ausblenden") : t("Gründe zeigen")}</span>
        </button>
      </h3>
      {open && (
        <ul className="flex max-h-44 flex-col divide-y divide-line overflow-y-auto border-t border-danger/20">
          {[...groups.values()].map((g) => (
            <li key={g.lines[0]} className="flex flex-col gap-1 px-3 py-2">
              <ul className="flex flex-col gap-0.5 text-xs">
                {g.reasons.map((r) => (
                  <li key={r} className="flex items-start gap-1.5 text-fg-muted">
                    <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0 text-danger-text" />
                    <span>{r}</span>
                  </li>
                ))}
              </ul>
              <p className="pl-5 text-2xs text-fg-subtle">
                {g.lines.length === 1 ? t("Zeile") : t("{1} Zeilen", { 1: formatNumber(g.lines.length) })}:{' '}
                <span className="mono text-fg-muted">
                  {g.lines.slice(0, 8).map(localizeMessage).join(' · ')}
                  {g.lines.length > 8 && t(" … und {1} weitere", { 1: formatNumber(g.lines.length - 8) })}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** „A“, „A und B“, „A, B und C“ */
function joinGerman(items: string[]): string {
  if (items.length <= 1) return items[0] ?? ''
  return t("{1} und {2}", { 1: items.slice(0, -1).join(', '), 2: items[items.length - 1] })
}

// --------------------------------------------------------------------------- Schritt 4: Import

type Outcome = 'success' | 'partial' | 'failed'

/** Grün nur ohne Fehler; „teilweise“, wenn trotz Fehlern etwas übernommen wurde (Bewertung des Backends) */
function importOutcome(result: ImportResult): Outcome {
  const outcome = result.outcome ?? (!result.error_count ? 'ok' : result.created + result.updated > 0 ? 'partial' : 'failed')
  return outcome === 'ok' ? 'success' : outcome
}

/** Beschriftung des Import-Knopfs: laut Probelauf „2 Bauteile importieren“, sonst die Zeilenzahl der Datei */
function importLabel(rows: number, check: ImportCheck | null): string {
  if (!check || check.truncated) return t("{1} importieren", { 1: plural(rows, t("Zeile"), t("Zeilen")) })
  const written = (check.counts.create ?? 0) + (check.counts.update ?? 0)
  return written > 0 ? t("{1} importieren", { 1: plural(written, t("Bauteil"), t("Bauteile")) }) : t("Nichts zu importieren")
}

/** Laut Probelauf schreibt keine geprüfte Zeile etwas (mit den Gründen) */
interface NothingToImport {
  reject: number
  skip: number
  unchanged: number
  checked: number
  total: number
  /** Nur ein Teil der Datei wurde geprüft – die übrigen Zeilen könnten noch etwas schreiben */
  partial: boolean
}

/**
 * Würde der Import nichts schreiben? Sicher nur, wenn der Probelauf **alle** Zeilen geprüft hat (`partial: false` –
 * dann ist der Knopf gesperrt); bei großen Dateien gilt die Aussage nur für die geprüften Zeilen. `null` = es würde
 * etwas angelegt oder geändert bzw. noch kein Probelauf.
 */
function nothingToImport(check: ImportCheck | null): NothingToImport | null {
  if (!check || check.checked === 0) return null
  const c = check.counts
  if ((c.create ?? 0) + (c.update ?? 0) > 0) return null
  return {
    reject: c.reject ?? 0,
    skip: c.skip ?? 0,
    unchanged: c.unchanged ?? 0,
    checked: check.checked,
    total: check.total,
    partial: Boolean(check.truncated),
  }
}

/**
 * Warnung statt Erfolg, wenn Zeilen abgelehnt wurden: Schlussmeldung des Backends („Import fertig: 4 neu, 2 abgelehnt“
 * bzw. „Import fehlgeschlagen – nichts übernommen: 3 abgelehnt“) und der erste Grund. Ohne Meldung (älteres Backend)
 * aus den Zählern.
 */
function importProblem(result: ImportResult | null | undefined): string | null {
  if (!result || importOutcome(result) === 'success') return null
  const first = Object.entries(result.errors)[0]
  const reason = first ? ` – ${first[0]}: ${first[1]}` : ''
  const message =
    (result.message ? localizeMessage(result.message.trim()) : '') ||
    (importOutcome(result) === 'failed'
      ? t("Keine Zeile übernommen, {1} abgelehnt", { 1: plural(result.error_count, t("Zeile"), t("Zeilen")) })
      : t("{1} von {2} übernommen, {3} abgelehnt", { 1: formatNumber(result.created + result.updated), 2: plural(result.rows, t("Zeile"), t("Zeilen")), 3: formatNumber(result.error_count) }))
  return `${message}${reason}`
}

/**
 * Meldung des Backends („Symbol: Pflichtfeld ist leer.; Footprint: …“) → je Feld ein Eintrag; Tabellennamen
 * („Resistors“) werden zu Kategorienamen.
 */
function splitMessages(message: string, fields: Map<string, FieldDef>, labels: Map<string, string> = new Map()): { field: string; text: string }[] {
  const named = message.replace(/„([^“]+)“/g, (m, name: string) => (labels.has(name.toLowerCase()) ? `„${labels.get(name.toLowerCase())}“` : m))
  // nur an „; Feld: …“ trennen – Meldungen selbst enthalten Semikolons („erwartet z. B. 1%; Einheit %“)
  return named
    .split(/;\s+(?=[^:;()]{1,60}:\s)/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const m = part.match(/^([^:]{1,60}):\s*(.+)$/)
      if (!m) return { field: '', text: part.replace(/\.$/, '') }
      const label = fields.get(m[1].trim())?.label ?? m[1].trim()
      return { field: label, text: m[2].replace(/\.$/, '') }
    })
}

const isRequiredOnly = (items: { field: string; text: string }[]) =>
  items.length > 0 && items.every((i) => /pflichtfeld ist leer/i.test(i.text) && !/teilenummer/i.test(i.field))

/** Abgelehnte Zeilen, die nur an leeren Pflichtfeldern scheiterten (als Entwurf nachholbar) */
function draftableRows(result: ImportResult): number {
  return Object.values(result.errors).filter((msg) => isRequiredOnly(splitMessages(msg, new Map()))).length
}

function StepRun({
  job,
  fields,
  categories,
}: {
  job: Job<ImportResult> | undefined
  fields: Map<string, FieldDef>
  categories: CategoryDef[]
}) {
  const { t } = useI18n()
  const labels = new Map(categories.map((c) => [c.table.toLowerCase(), c.label]))
  if (!job) {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-ui text-fg-muted">
        <Spinner size={16} tone="accent" />  {t("Import wird gestartet …")}
      </div>
    )
  }
  const result = job.result
  if (job.status === 'failed' || job.status === 'cancelled') {
    // Abbruch: Grund aus `cancel_reason` (Bibliothekswechsel) bzw. der Schlussmeldung – importiert wurde dann nichts
    return (
      <Callout tone={job.status === 'failed' ? 'danger' : 'warning'} title={job.status === 'failed' ? t("Import fehlgeschlagen") : t("Import abgebrochen")} urgent>
        {job.status === 'failed' ? cleanErrorText(job.error ?? job.message) : t("{1} Es wurde nichts übernommen.", { 1: jobCancelText(job).replace(/\s*\.?$/, '.') })}
      </Callout>
    )
  }
  if (job.status !== 'done' || !result) {
    return (
      <div className="flex flex-1 flex-col justify-center gap-4 py-6">
        <ProgressBar value={job.progress} live label={job.message ? localizeMessage(job.message) : t("Import läuft …")} showValue size="md" />
        <ol className="mono flex max-h-40 flex-col gap-0.5 overflow-y-auto text-2xs text-fg-subtle" aria-label={t("Protokoll")}>
          {job.log.slice(-8).map((l, i) => (
            <li key={`${l.ts}-${i}`} className={cn(l.level === 'warn' && 'text-warning-text', l.level === 'error' && 'text-danger-text')}>
              {localizeMessage(l.text)}
            </li>
          ))}
        </ol>
      </div>
    )
  }
  const outcome = importOutcome(result)
  const stats: { label: string; value: number; tone?: string }[] = [
    { label: t("neu angelegt"), value: result.created, tone: result.created ? 'text-success-text' : undefined },
    { label: t("aktualisiert"), value: result.updated, tone: result.updated ? 'text-info-text' : undefined },
    { label: t("unverändert"), value: result.unchanged },
    { label: t("übersprungen"), value: result.skipped },
    { label: t("abgelehnt"), value: result.error_count, tone: result.error_count ? 'text-danger-text' : undefined },
  ]
  const created = result.created_part_numbers
  // Gleiche Gründe zusammenfassen: „Symbol und Footprint leer“ bei 4 Zeilen = ein Eintrag
  const groups = new Map<string, { items: { field: string; text: string }[]; rows: string[] }>()
  for (const [row, msg] of Object.entries(result.errors)) {
    const items = splitMessages(msg, fields, labels)
    const key = items.map((i) => `${i.field}\u0000${i.text}`).join('\u0001')
    const g = groups.get(key) ?? { items, rows: [] }
    g.rows.push(row)
    groups.set(key, g)
  }
  const head = {
    success: {
      icon: <CircleCheck aria-hidden className="size-5" />,
      ring: 'bg-success/12 text-success-text',
      title: t("{1} verarbeitet", { 1: plural(result.rows, t("Zeile"), t("Zeilen")) }),
    },
    partial: {
      icon: <TriangleAlert aria-hidden className="size-5" />,
      ring: 'bg-warning/14 text-warning-text',
      title: t("{1} von {2} übernommen – {3} abgelehnt", { 1: formatNumber(result.created + result.updated), 2: plural(result.rows, t("Zeile"), t("Zeilen")), 3: formatNumber(result.error_count) }),
    },
    failed: {
      icon: <CircleX aria-hidden className="size-5" />,
      ring: 'bg-danger/12 text-danger-text',
      title: t("Keine Zeile importiert – {1} abgelehnt", { 1: plural(result.error_count, t("Zeile"), t("Zeilen")) }),
    },
  }[outcome]
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex flex-col gap-4">
      <div className="flex items-center gap-3" role={outcome === 'success' ? 'status' : 'alert'}>
        <span className={cn('flex size-10 shrink-0 items-center justify-center rounded-full', head.ring)}>{head.icon}</span>
        <div className="min-w-0">
          <p className="text-md font-semibold text-fg">{head.title}</p>
          <p className="truncate text-xs text-fg-muted">
            {result.file}
            {result.backup && t(" · Sicherung: {1}", { 1: result.backup })}
          </p>
        </div>
      </div>
      <dl className="grid grid-cols-5 divide-x divide-line overflow-hidden rounded-card border border-line">
        {stats.map((st) => (
          <div key={st.label} className="flex flex-col gap-0.5 px-4 py-3">
            <dt className="text-2xs text-fg-subtle">{metadataLabel(st.label, t)}</dt>
            <dd className={cn('mono text-h3 font-semibold tabular-nums', st.tone ?? 'text-fg')}>{formatNumber(st.value)}</dd>
          </div>
        ))}
      </dl>
      {created.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-ui font-medium text-fg">{t("Neu in der Bibliothek")}</h3>
          <ul className="flex flex-wrap gap-1.5" aria-label={t("Neu angelegte Teilenummern")}>
            {created.slice(0, 18).map((pn) => (
              <li key={pn}>
                <Badge variant="success" className="mono">
                  {pn}
                </Badge>
              </li>
            ))}
            {created.length > 18 && <li className="self-center text-xs text-fg-subtle">{t("… und")} {formatNumber(created.length - 18)}  {t("weitere")}</li>}
          </ul>
          <p className="text-xs text-fg-muted">{t("In der Tabelle sind sie mit „neu“ markiert.")}</p>
        </div>
      )}
      {groups.size > 0 && (
        <section aria-labelledby="imp-errors" className="flex flex-col gap-2">
          <h3 id="imp-errors" className="text-ui font-medium text-fg">
            {t("Abgelehnt")}{' '}
            <span className="font-normal text-fg-muted">
              ({formatNumber(result.error_count)}
              {result.error_count > Object.keys(result.errors).length ? t(", die ersten {1}", { 1: formatNumber(Object.keys(result.errors).length) }) : ''})
            </span>
          </h3>
          <ul className="flex max-h-56 flex-col divide-y divide-line overflow-y-auto rounded-card border border-line">
            {[...groups.values()].map((g) => (
              <li key={g.rows[0]} className="flex flex-col gap-1.5 px-3 py-2.5">
                <ul className="flex flex-col gap-0.5 text-xs">
                  {g.items.map((it) => (
                    <li key={`${it.field}:${localizeMessage(it.text)}`} className="flex items-start gap-1.5">
                      <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0 text-danger-text" />
                      <span>
                        {it.field && <span className="font-medium text-fg">{it.field}</span>}
                        {it.field && <span className="text-fg-subtle"> – </span>}
                        <span className="text-fg-muted">{localizeMessage(it.text)}</span>
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="pl-5 text-2xs text-fg-subtle">
                  {/* Schlüssel = Teilenummer der Zeile, ohne Teilenummer „Zeile n“ */}
                  {g.rows.length === 1 ? t("Betrifft") : t("Betrifft {1} Zeilen", { 1: formatNumber(g.rows.length) })}:{' '}
                  <span className="mono text-fg-muted">
                    {g.rows.slice(0, 8).join(' · ')}
                    {g.rows.length > 8 && t(" … und {1} weitere", { 1: formatNumber(g.rows.length - 8) })}
                  </span>
                </p>
              </li>
            ))}
          </ul>
          {isRequiredOnlyAny(result) && (
            <p className="text-xs text-fg-muted">
              {t("Zeilen, denen nur Pflichtwerte fehlen, lassen sich unten als „Entwurf“ nachholen – oder zurück zur Zuordnung und die Spalten bzw. festen Werte ergänzen.")}
            </p>
          )}
        </section>
      )}
    </motion.div>
  )
}

const isRequiredOnlyAny = (result: ImportResult) => draftableRows(result) > 0
