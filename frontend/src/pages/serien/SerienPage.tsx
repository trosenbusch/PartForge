import { localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Serien-Assistent (`/serien`): eine komplette Bauteilserie in fünf Schritten – Kategorie → Hersteller-Serie →
 * Werte und Varianten (Live-Zähler) → Vorschau (alle Zeilen mit Status) → Erzeugen (Job mit Fortschritt).
 *
 * Einstiege: `/serien?kategorie=Resistors`, `/serien?vorlage=vishay-crcw-e3`, Befehl „Neue Serie“ (series.new).
 * Der Schritt steht in der Adresse (`?schritt=kategorie|serie|werte|vorschau|erzeugen`): Zurück/Vor des Fensters und
 * Alt+←/→ wechseln zwischen den Schritten (im Desktop-Fenster sind die Browser-Kürzel aus – die Seite übernimmt sie).
 * Die Auswahl je Vorlage wird gemerkt (model/store.ts); Schritt und laufender Job überstehen Seitenwechsel.
 * Ein laufender Job wird nie verworfen: „Neue Serie“ führt solange zu seinem Fortschritt, und eine zweite Serie
 * startet erst, wenn keine mehr läuft. Verlässt man „Erzeugen“ nach dem Ende, macht der Job der nächsten Serie Platz.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, useReducedMotion } from 'motion/react'
import { ArrowLeft, CircleCheck, FilePlus2, Layers, RotateCcw, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { ApiError, cleanErrorText, errorMessage } from '@/api/client'
import { useCategories } from '@/api/library'
import { trackJob, useJob } from '@/api/jobs'
import { queryClient } from '@/api/queryClient'
import {
  SERIES_MAX_ROWS,
  seriesApi,
  seriesKeys,
  templateQueryOptions,
  useDeleteCustomTemplate,
  useSeriesPreview,
  useSeriesTemplate,
  useSeriesTemplates,
  type DecodedMpn,
  type MpnSegment,
  type PreviewRow,
  type SeriesCommitResult,
  type SeriesTemplate,
  type SeriesTemplateSummary,
} from '@/api/series'
import { isJobActive, isJobFinished, systemKeys, useLibraryJobs, useWorkspace, type Job } from '@/api/system'
import { useRegisterCommands } from '@/app/commands'
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { Button, confirm, Skeleton, Spinner, Stepper, type StepDef } from '@/components/ui'
import { useElementSize } from '@/components/preview'
import { cn } from '@/lib/cn'
import { formatNumber, pluralNoun } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { useBauteile } from '@/pages/bauteile/model/store'
import type { FilterCondition } from '@/pages/bauteile/model/fields'
import { focusWhenReady } from './components/focus'
import { LoadError } from './components/LoadError'
import { StepHeading } from './components/StepHeading'
import { useDebounced } from './components/useDebounced'
import { WizardFooter } from './components/WizardFooter'
import { CustomTemplateDialog } from './dialogs/CustomTemplateDialog'
import { splitMpn } from './model/anatomy'
import { SERIES_CATEGORIES } from './model/categories'
import { settingsFromDecoded } from './model/decoded'
import { estimateSeries, ruleBasis, seriesDomain, withRange } from './model/estimate'
import { buildRequest, reconcileSettings, requestKey, type Density, type SeriesSettings } from './model/settings'
import { serverParts } from './model/status'
import {
  chooseTemplate,
  LAST_STEP,
  STEP_IDS,
  stepFromParam,
  useSerien,
  type JobContextInfo,
  type StepIndex,
} from './model/store'
import { exampleValue, mpnPrefix, needsFullTemplate, templateMode } from './model/template'
import { parseAmount } from './model/values'
import { CategoryStep } from './steps/CategoryStep'
import { CommitStep } from './steps/CommitStep'
import { PreviewStep } from './steps/PreviewStep'
import type { QuickStartApply } from './steps/QuickStart'
import { TemplateStep } from './steps/TemplateStep'
import { ValuesStep } from './steps/ValuesStep'

const STEPS: StepDef[] = [
  { id: 'kategorie', label: 'Kategorie', description: 'Was entsteht' },
  { id: 'serie', label: 'Hersteller-Serie', description: 'Vorlage mit Codes' },
  { id: 'werte', label: 'Werte und Varianten', description: 'E-Reihe, Bauformen' },
  { id: 'vorschau', label: 'Vorschau', description: 'Alle Zeilen prüfen' },
  { id: 'erzeugen', label: 'Erzeugen', description: 'Bauteile anlegen' },
]
/** Schmale Fenster: kurze Bezeichnungen ohne Beschreibung */
const STEPS_SHORT: StepDef[] = STEPS.map((s, i) => ({ id: s.id, label: ['Kategorie', 'Serie', 'Werte', 'Vorschau', 'Erzeugen'][i] }))
/** Überschriften der Schritte (auch für Lade- und Fehlerzustände) */
const STEP_HEADINGS = ['serien-kategorie', 'serien-vorlage', 'serien-werte', 'serien-vorschau', 'serien-erzeugen']

interface Draft {
  id: string
  settings: SeriesSettings
}

/** Warum die Vorlage eines Schritts ab „Werte“ fehlt */
type TemplateIssue = { kind: 'list'; error: unknown } | { kind: 'missing' } | { kind: 'detail'; error: unknown }

/** Beispiel im Zähler: Zeile der Auswahl, Segmente (von der Vorlagenkarte, sonst gelesen) */
interface ExampleChoice {
  row: PreviewRow
  segments: MpnSegment[] | null
}

/** Steht die Serie nach dem Job in der Bibliothek (angelegt, aktualisiert oder schon vorhanden)? */
function seriesWritten(r: SeriesCommitResult | null | undefined): boolean {
  return Boolean(r && r.created + r.updated + r.unchanged + r.skipped > 0)
}

/** Adresse mit anderem Schritt (übrige Parameter bleiben) */
/** Title of the running series' template: built-in titles are catalog sources, custom ones stay as written */
function TemplateTitle({ title }: { title: string }) {
  useI18n()
  return <>{localizeMessage(title)}</>
}

function withStep(params: URLSearchParams, step: StepIndex): URLSearchParams {
  const next = new URLSearchParams(params)
  next.set('schritt', STEP_IDS[step])
  return next
}

export default function SerienPage() {
  const { t: tr } = useI18n()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const reduceMotion = useReducedMotion()
  const [params, setParams] = useSearchParams()
  const workspace = useWorkspace().data
  const root = workspace?.root ?? null
  const houseDensity: Density = workspace?.settings.footprint.density ?? 'N'
  const internalScheme = workspace?.settings.part_number_scheme === 'internal'
  const categories = useCategories()

  const storeStep = useSerien((s) => s.step)
  const category = useSerien((s) => s.category)
  const templateId = useSerien((s) => s.templateId)
  const saved = useSerien((s) => s.settings)
  const mode = useSerien((s) => s.mode)
  const setMode = useSerien((s) => s.setMode)
  const jobInfo = useSerien((s) => s.job)

  // ------------------------------------------------------------------ Schritt (Adresse ist maßgeblich)
  const paramCategory = params.get('kategorie')
  const paramTemplate = params.get('vorlage')
  const entering = Boolean(paramCategory || paramTemplate)
  const urlStep = stepFromParam(params.get('schritt'))
  /** höchster Schritt, den die Auswahl erlaubt: ohne Kategorie keine Serie, ohne Serie keine Werte */
  const reachable: StepIndex = templateId ? LAST_STEP : category ? 1 : 0
  const step = Math.min(urlStep ?? storeStep, reachable) as StepIndex

  useEffect(() => {
    const st = useSerien.getState()
    if (st.workspace === root) return
    const switched = st.workspace !== null
    st.syncWorkspace(root)
    // andere Bibliothek: von vorn (beim ersten Aufruf der Sitzung gilt die Adresse, z. B. nach einem Neuladen)
    if (switched) setParams((p) => withStep(p, 0), { replace: true })
  }, [root, setParams])

  // Adresse ohne (gültigen, erreichbaren) Schritt → ersetzen; der Store merkt sich den Schritt für Seitenwechsel
  useEffect(() => {
    if (entering) return
    if (urlStep !== step) {
      setParams((p) => withStep(p, step), { replace: true })
      return
    }
    if (useSerien.getState().step !== step) useSerien.getState().setStep(step)
  }, [entering, urlStep, step, setParams])

  // ------------------------------------------------------------------ Vorlagen
  const templates = useSeriesTemplates()
  const summary = templates.data?.find((t) => t.id === templateId) ?? null
  const full = summary ? needsFullTemplate(summary) : false
  const templateQuery = useSeriesTemplate(summary ? summary.id : null, { full })
  const template = templateQuery.data && templateQuery.data.id === templateId ? templateQuery.data : undefined
  const categoryLabel = useMemo(() => {
    const table = (step >= 2 ? template?.category : null) ?? category
    if (!table) return ''
    return (
      tr(categories.data?.find((c) => c.table === table)?.label ??
      SERIES_CATEGORIES.find((c) => c.table === table)?.label ??
      table)
    )
  }, [categories.data, category, template?.category, step, tr])

  const templateIssue: TemplateIssue | null =
    template || step < 2
      ? null
      : templates.isError && !templates.data
        ? { kind: 'list', error: templates.error }
        : templates.data && !summary
          ? { kind: 'missing' }
          : templateQuery.isError
            ? templateQuery.error instanceof ApiError && templateQuery.error.isNotFound
              ? { kind: 'missing' }
              : { kind: 'detail', error: templateQuery.error }
            : null

  // ------------------------------------------------------------------ Auswahl (Entwurf je Vorlage)
  const [draft, setDraft] = useState<Draft | null>(null)
  if (template && draft?.id !== template.id) {
    setDraft({ id: template.id, settings: reconcileSettings(template, saved[template.id]) })
  }
  const settings = template && draft?.id === template.id ? draft.settings : null
  useEffect(() => {
    if (!draft) return
    const t = window.setTimeout(() => useSerien.getState().saveSettings(draft.id, draft.settings), 400)
    return () => window.clearTimeout(t)
  }, [draft])
  const updateSettings = useCallback((patch: Partial<SeriesSettings>) => {
    setDraft((d) => (d ? { ...d, settings: { ...d.settings, ...patch } } : d))
  }, [])

  // ------------------------------------------------------------------ Job
  const liveJob = useJob<SeriesCommitResult>(jobInfo?.id).job
  const jobRunning = Boolean(jobInfo) && (!liveJob || isJobActive(liveJob))
  // nur Jobs dieser Bibliothek – eine Serie einer anderen Bibliothek sperrt hier nichts (K2)
  const jobs = useLibraryJobs().data
  /** eine andere Serie läuft gerade (nach einem Seitenwechsel, aus einem anderen Fenster …) */
  const otherSeries = jobs?.find((j) => j.kind === 'series' && isJobActive(j) && j.id !== jobInfo?.id) ?? null
  const busyWith = otherSeries ? otherSeries.title.replace(/^Serie\s+/, '') : null

  // ------------------------------------------------------------------ Zähler und Anfrage
  // Grundlage der Regel-Vorlagen hängt nicht vom Bereich ab – Ziehen am Regler bleibt flüssig
  const basisKey = settings ? JSON.stringify({ ...settings, rangeMin: null, rangeMax: null, valuesText: '' }) : ''
  const basis = useMemo(() => {
    if (!template || !basisKey) return null
    const m = templateMode(template)
    if (m === 'matrix' || m === 'catalog') return null
    return ruleBasis(template, JSON.parse(basisKey) as SeriesSettings)
  }, [template, basisKey])
  const computed = useMemo(() => {
    if (!template || !settings) return null
    const domain = seriesDomain(template, settings, basis)
    const effective = withRange(settings, domain)
    const estimate = estimateSeries(template, effective, basis)
    return { domain, effective, estimate, request: buildRequest(template, effective, domain) }
  }, [template, settings, basis])
  const estimate = computed?.estimate ?? null
  const request = computed?.request ?? null
  const rowsPlanned = estimate ? estimate.total + estimate.invalid : 0
  const withinLimits = rowsPlanned > 0 && rowsPlanned <= SERIES_MAX_ROWS

  const debouncedRequest = useDebounced(request, 650)
  const previewRequest = step === 2 ? debouncedRequest : step >= 3 ? request : null
  // Schritt „Erzeugen“ mit Job: nichts nachrechnen (das Ergebnis zeigt der Job; nach dem Ende lädt „Neue Serie“ frisch)
  const previewPaused = Boolean(jobInfo) && step === LAST_STEP
  const preview = useSeriesPreview(withinLimits && !previewPaused ? previewRequest : null)
  const forCurrent = requestKey(previewRequest) === requestKey(request)
  const previewCurrent = Boolean(preview.data) && !preview.isPlaceholderData && forCurrent
  /** Fehler der Prüfung genau dieser Auswahl (nicht einer früheren) */
  const previewError = preview.isError && forCurrent ? preview.error : null
  const checking = preview.isFetching || requestKey(debouncedRequest) !== requestKey(request)

  /** Bauteile je Baugröße laut Prüfung (neu + vorhanden) – ersetzt die Schätzung, sobald die Vorschau passt */
  const serverPerSize = useMemo(() => {
    if (!previewCurrent || !preview.data) return null
    const out: Record<string, number> = {}
    for (const r of preview.data.rows) if (r.status === 'new' || r.status === 'exists') out[r.size] = (out[r.size] ?? 0) + 1
    return out
  }, [previewCurrent, preview.data])

  // Beispiel im Zähler: das der Vorlagenkarte, wenn es in der Auswahl liegt (Segmente schon da, keine Anfrage),
  // sonst die Zeile nahe dem typischen Wert – gelesen für den Aufbau der Teilenummer
  const cardExample = summary?.example ?? null
  const exampleChoice = useMemo<ExampleChoice | null>(() => {
    const rows = preview.data?.rows ?? []
    if (!rows.length || !template) return null
    const pool = rows.filter((r) => (r.status === 'new' || r.status === 'exists') && !r.jumper)
    if (!pool.length) return null
    if (cardExample && cardExample.segments.length > 1) {
      const hit = pool.find((r) => r.mpn === cardExample.mpn)
      if (hit) return { row: hit, segments: cardExample.segments }
    }
    const target = exampleValue(template.value_unit)
    const firstSize = settings?.sizes[0]
    const sized = pool.filter((r) => r.size === firstSize)
    const list = sized.length ? sized : pool
    const score = (r: PreviewRow) => {
      const v = parseAmount(r.value)
      return v !== null && v > 0 ? Math.abs(Math.log10(v) - Math.log10(target)) : 99
    }
    return { row: list.reduce((best, r) => (score(r) < score(best) ? r : best), list[0]), segments: null }
  }, [preview.data, template, settings?.sizes, cardExample])
  const exampleMpn = exampleChoice?.row.mpn ?? ''
  const exampleDecode = useQuery({
    queryKey: seriesKeys.decode(exampleMpn, template?.id ?? null),
    queryFn: ({ signal }) => seriesApi.decode(exampleMpn, template?.id ?? null, signal),
    enabled: Boolean(exampleChoice && !exampleChoice.segments && template && step === 2),
    staleTime: 5 * 60_000,
  })
  const example =
    exampleChoice && template
      ? {
          mpn: exampleDecode.data?.best?.mpn ?? exampleChoice.row.mpn,
          segments:
            exampleChoice.segments ?? (exampleDecode.data?.best ? splitMpn(template, exampleDecode.data.best) : null),
          description: exampleChoice.row.values.Description ?? null,
        }
      : null

  // ------------------------------------------------------------------ Navigation und Fokus
  const contentRef = useRef<HTMLDivElement>(null)
  /** Schritt wechseln: neuer Eintrag im Verlauf (Zurück führt zum vorigen Schritt); `replace` für Automatisches */
  const goTo = useCallback(
    (next: StepIndex, opts: { replace?: boolean } = {}) => {
      useSerien.getState().setStep(next)
      setParams((p) => withStep(p, next), { replace: opts.replace })
    },
    [setParams],
  )
  /** gerade gespeicherte eigene Vorlage – die Karte holt sich den Fokus, nicht die Überschrift */
  const [revealId, setRevealId] = useState<string | null>(null)
  const clearReveal = useCallback(() => setRevealId(null), [])

  const commit = useMutation({
    mutationFn: () => {
      if (!request) throw new Error(tr("Keine gültige Auswahl."))
      return seriesApi.commit({ ...request, mode })
    },
    // Fehler stehen im Schritt „Erzeugen“ (deutscher Text des Backends)
    meta: { silentError: true },
    onSuccess: ({ job }) => {
      // Fortschritt und Ergebnis zeigt der Schritt „Erzeugen“ selbst – nicht in der Pille, kein Toast. Verlässt man
      // den Schritt, übernimmt das Job-Dock (useInlineJob im Schritt)
      trackJob(job, { dock: false, toast: false })
      if (!template) return
      const counts = preview.data?.counts ?? {}
      const info: JobContextInfo = {
        id: job.id,
        templateId: template.id,
        title: template.title,
        table: template.category,
        manufacturer: template.manufacturer,
        prefix: mpnPrefix(template),
        plan: {
          rows: counts.total ?? 0,
          writes: (counts.new ?? 0) + (mode === 'update' ? (counts.exists ?? 0) : 0),
          footprints: preview.data?.footprints_needed.length ?? 0,
          symbol: preview.data?.symbol?.name ?? null,
          symbolExists: preview.data?.symbol?.exists ?? false,
        },
      }
      useSerien.getState().setJob(info)
    },
  })
  const resetCommit = commit.reset

  // Nach jedem Schrittwechsel (Klick, Zurück/Vor, Alt+←/→): nach oben scrollen und Fokus auf die Überschrift des neuen
  // Schritts (der alte Inhalt samt fokussiertem Element ist weg – sonst fiele der Fokus auf <body>). Wer „Erzeugen“
  // nach dem Ende des Jobs verlässt, beginnt beim nächsten Mal mit dem Startbildschirm und frischer Vorschau.
  const shownStep = useRef(step)
  useEffect(() => {
    if (shownStep.current === step) return
    const previous = shownStep.current
    shownStep.current = step
    if (previous === LAST_STEP) {
      const info = useSerien.getState().job
      const snap = info ? queryClient.getQueryData<Job>(systemKeys.job(info.id)) : undefined
      if (info && snap && isJobFinished(snap)) {
        useSerien.getState().setJob(null)
        resetCommit()
        void queryClient.invalidateQueries({ queryKey: [...seriesKeys.all, 'preview'] })
      }
    }
    document.getElementById('main')?.scrollTo({ top: 0, behavior: reduceMotion ? 'auto' : 'smooth' })
    if (revealId) return
    return focusWhenReady(() => contentRef.current?.querySelector<HTMLElement>('h2[tabindex="-1"]'))
  }, [step, revealId, reduceMotion, resetCommit])

  // Alt+←/→ wie Zurück/Vor des Browsers (WebView2 schaltet die Browser-Kürzel ab); nicht hinter modalen Dialogen und
  // nicht in Eingabefeldern (Alt allein)
  useHotkey(['alt+left', 'alt+right'], (e) => {
    if (document.querySelector('[aria-modal="true"]')) return
    if (e.key === 'ArrowRight') {
      void navigate(1)
      return
    }
    const index = (window.history.state as { idx?: number } | null)?.idx ?? 0
    if (index > 0) void navigate(-1)
    else if (step > 0) goTo((step - 1) as StepIndex)
  })

  const pickCategory = (table: string) => {
    const st = useSerien.getState()
    const current = templates.data?.find((t) => t.id === st.templateId)
    const remembered = st.lastTemplate[table]
    const known = remembered && templates.data?.some((t) => t.id === remembered && t.category === table) ? remembered : null
    useSerien.setState({ category: table, templateId: known ?? (current?.category === table ? current.id : null) })
    goTo(1)
  }

  const resume = (t: SeriesTemplateSummary) => {
    chooseTemplate(t.category, t.id)
    goTo(2)
  }

  const [quickDecoded, setQuickDecoded] = useState<DecodedMpn | null>(null)
  const applyDecoded = async ({ decoded }: QuickStartApply) => {
    try {
      const sum = templates.data?.find((t) => t.id === decoded.template_id)
      const t = await queryClient.fetchQuery(templateQueryOptions(decoded.template_id, sum ? needsFullTemplate(sum) : false))
      const base = reconcileSettings(t, useSerien.getState().settings[t.id])
      setDraft({ id: t.id, settings: settingsFromDecoded(t, decoded, base) })
      chooseTemplate(t.category, t.id)
      goTo(2)
    } catch (error) {
      toast.error(tr("Vorlage konnte nicht geladen werden"), { description: cleanErrorText(errorMessage(error)) })
    }
  }

  // URL-Einstiege (einmal je Aufruf). Läuft gerade eine Serie, wird die Wahl nur gemerkt und der Fortschritt gezeigt;
  // ein beendeter Job macht der neuen Serie Platz.
  useEffect(() => {
    if (!paramCategory && !paramTemplate) return
    if (paramTemplate && !templates.data) return
    const hit = paramTemplate ? templates.data?.find((t) => t.id === paramTemplate) : undefined
    const info = useSerien.getState().job
    const snap = info ? queryClient.getQueryData<Job>(systemKeys.job(info.id)) : undefined
    const running = Boolean(info) && (!snap || isJobActive(snap))
    if (info && !running) useSerien.getState().setJob(null)
    let target: StepIndex = useSerien.getState().step
    if (hit) {
      chooseTemplate(hit.category, hit.id)
      target = running ? LAST_STEP : 2
    } else if (paramCategory) {
      useSerien.setState({ category: paramCategory })
      target = running ? LAST_STEP : 1
    }
    useSerien.getState().setStep(target)
    if (running) {
      toast.info(tr("Eine Serie wird gerade erzeugt"), {
        id: 'serien-laeuft',
        description: tr("Die Auswahl ist gemerkt – nach dem Ende geht es mit „Neue Serie“ weiter."),
      })
    }
    setParams(
      (p) => {
        const next = withStep(p, target)
        next.delete('kategorie')
        next.delete('vorlage')
        return next
      },
      { replace: true },
    )
  }, [paramCategory, paramTemplate, templates.data, setParams, tr])

  // ------------------------------------------------------------------ Eigene Vorlagen
  const [dialog, setDialog] = useState<{ open: boolean; edit: string | null }>({ open: false, edit: null })
  const openCustom = useCallback((edit?: SeriesTemplateSummary) => setDialog({ open: true, edit: edit?.id ?? null }), [])
  const deleteCustom = useDeleteCustomTemplate()
  const removeCustom = async (t: SeriesTemplateSummary) => {
    const ok = await confirm({
      title: tr("Vorlage „{v0}“ löschen?", { v0: t.title }),
      description: tr("Bereits angelegte Bauteile bleiben unverändert. Die Vorlage lässt sich nicht wiederherstellen."),
      destructive: true,
      confirmLabel: tr("Löschen"),
      onConfirm: async () => {
        await deleteCustom.mutateAsync(t.id)
        if (useSerien.getState().templateId === t.id) useSerien.setState({ templateId: null })
      },
    })
    if (ok) toast.success(tr("Vorlage gelöscht"), { description: t.title })
  }

  // ------------------------------------------------------------------ Erzeugen
  const showTable = useCallback(() => {
    const info = useSerien.getState().job
    if (!info) return
    const filters: FilterCondition[] = [{ id: 'serie-hersteller', column: 'Manufacturer', op: 'eq', value: info.manufacturer }]
    if (info.prefix.length >= 2) {
      filters.push({ id: 'serie-mpn', column: 'Manufacturer Part Number', op: 'startswith', value: info.prefix })
    }
    const b = useBauteile.getState()
    b.syncWorkspace(root)
    b.setQuery(info.table, { search: '', filters, viewId: null })
    void navigate(`/bauteile/${encodeURIComponent(info.table)}`)
  }, [navigate, root])

  const newSeries = useCallback(() => {
    if (jobRunning) {
      // nie einen laufenden Job verwerfen – stattdessen seinen Fortschritt zeigen
      goTo(LAST_STEP)
      toast.info(tr("Eine Serie wird gerade erzeugt"), {
        id: 'serien-laeuft',
        description: tr("Eine neue Serie lässt sich beginnen, sobald sie fertig ist."),
      })
      return
    }
    useSerien.getState().restart()
    commit.reset()
    setQuickDecoded(null)
    void qc.invalidateQueries({ queryKey: [...seriesKeys.all, 'preview'] })
    goTo(0)
  }, [jobRunning, commit, qc, goTo, tr])

  // ------------------------------------------------------------------ Schritte
  const counts = preview.data?.counts ?? {}
  const writable = (counts.new ?? 0) + (counts.exists ?? 0)
  const writes = (counts.new ?? 0) + (mode === 'update' ? (counts.exists ?? 0) : 0)
  const canPreview = Boolean(request) && withinLimits
  const templateReason = templateIssue ? tr("Vorlage nicht geladen") : tr("Vorlage wird geladen")
  const next = (() => {
    switch (step) {
      case 0:
        // Schnellstart hat eine Serie erkannt: die ist das Naheliegende (Strg+Enter übernimmt sie)
        if (quickDecoded) {
          return { label: tr("Serie übernehmen"), disabled: false, reason: null, run: () => void applyDecoded({ decoded: quickDecoded }) }
        }
        return { label: tr("Weiter"), disabled: !category, reason: category ? null : tr("Kategorie wählen"), run: () => goTo(1) }
      case 1:
        return {
          label: tr("Weiter: Werte festlegen"),
          disabled: !templateId || !summary || summary.category !== category,
          reason: templateId && summary?.category === category ? null : tr("Hersteller-Serie wählen"),
          run: () => goTo(2),
        }
      case 2:
        return {
          label: tr("Weiter: Vorschau"),
          disabled: !canPreview || Boolean(previewError),
          reason: !template
            ? templateReason
            : !settings?.sizes.length
              ? tr("Bauform wählen")
              : rowsPlanned > SERIES_MAX_ROWS
                ? tr("Zu viele Bauteile")
                : !rowsPlanned
                  ? tr("Keine Bauteile")
                  : previewError
                    ? tr("Prüfung fehlgeschlagen")
                    : null,
          run: () => goTo(3),
        }
      case 3:
        return {
          label: tr("Weiter: Erzeugen"),
          disabled: !previewCurrent || !writable || !preview.data?.symbol,
          reason: !template
            ? templateReason
            : previewError || (!withinLimits && rowsPlanned > 0)
              ? tr("Prüfung fehlgeschlagen")
              : !previewCurrent
                ? tr("Vorschau wird berechnet")
                : !writable
                  ? tr("Nichts zu erzeugen")
                  : !preview.data?.symbol
                    ? tr("Kein sicheres Symbol")
                    : null,
          run: () => goTo(4),
        }
      default:
        return null
    }
  })()

  const canCommit = !jobInfo && previewCurrent && writes > 0 && Boolean(preview.data?.symbol) && !commit.isPending && !otherSeries
  useHotkey(
    'mod+enter',
    () => {
      // nicht hinter einem offenen Dialog (eigene Vorlage, Löschen bestätigen …)
      if (dialog.open || document.querySelector('[aria-modal="true"]')) return
      if (step === LAST_STEP) {
        if (canCommit) commit.mutate()
        return
      }
      if (next && !next.disabled) next.run()
    },
    { allowInInputs: true },
  )

  useRegisterCommands([
    {
      id: 'series.new',
      title: tr("Neue Serie"),
      subtitle: jobRunning
        ? tr("Zeigt die laufende Serie – eine neue beginnt, sobald sie fertig ist")
        : tr("Serien-Assistent von vorn beginnen (die gemerkte Auswahl bleibt)"),
      group: tr('Aktionen'),
      icon: Layers,
      priority: 90,
      target: '/serien',
      keywords: [tr("serie anlegen"), 'serien-assistent', 'e-reihe', 'widerstand', 'kondensator', tr("neu")],
      run: ({ close }) => {
        close()
        newSeries()
      },
    },
    {
      id: 'series.template.new',
      title: tr("Eigene Serienvorlage anlegen"),
      subtitle: tr("Teilenummern-Muster mit Codetabellen, sofort testbar"),
      group: tr('Aktionen'),
      icon: FilePlus2,
      priority: 40,
      keywords: ['vorlage', 'muster', 'mpn', 'hersteller', 'serie'],
      run: ({ close }) => {
        close()
        openCustom()
      },
    },
  ])

  // ------------------------------------------------------------------ Darstellung
  const [stepperRef, stepperSize] = useElementSize<HTMLDivElement>()
  const compactStepper = stepperSize.width > 0 && stepperSize.width < 900
  const subtitle = tr("Schritt {v0} von {v1}{v2}", { v0: step + 1, v1: STEPS.length, v2: categoryLabel && step > 0 ? ` · ${categoryLabel}` : '' })

  const serverCount = previewCurrent && preview.data ? serverParts(preview.data.counts) : null
  const footerCount = (() => {
    if (!estimate || step < 2) return null
    if (step === LAST_STEP) {
      return previewCurrent ? (
        <span className="shrink-0">
          <span className="mono font-semibold text-fg">{formatNumber(writes)}</span> {writes === 1 ? tr("wird") : tr("werden")} {tr("geschrieben")}</span>
      ) : null
    }
    const n = serverCount ?? estimate.total
    return (
      <span className="flex shrink-0 items-center gap-1.5">
        <span>
          <span className="mono font-semibold text-fg">{formatNumber(n)}</span> {pluralNoun(n, tr("Bauteil"), tr("Bauteile"))}
        </span>
        {step === 2 &&
          (previewError ? (
            // der Grund steht schon neben „Weiter“
            <TriangleAlert aria-hidden className="size-3.5 text-danger" />
          ) : checking || !previewCurrent ? (
            <Spinner size={12} />
          ) : (
            <CircleCheck aria-hidden className="size-3.5 text-success" />
          ))}
      </span>
    )
  })()
  const footerContext =
    step >= 1 && summary ? (
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate">{summary.category === category ? <TemplateTitle title={summary.title} /> : categoryLabel}</span>
        {footerCount && (
          <>
            <span aria-hidden className="text-fg-subtle">
              ·
            </span>
            {footerCount}
          </>
        )}
      </span>
    ) : step === 1 && category ? (
      <span>{categoryLabel}</span>
    ) : step === 0 && quickDecoded ? (
      <span className="truncate">
        {tr("Erkannt:")} <span className="font-medium text-fg">{quickDecoded.template_title}</span>
      </span>
    ) : null

  let content: ReactNode
  if (step === 0) {
    content = (
      <CategoryStep
        onPick={pickCategory}
        onResume={resume}
        onApplyDecoded={applyDecoded}
        onDecodedChange={setQuickDecoded}
        onCustomTemplate={() => openCustom()}
      />
    )
  } else if (step === 1) {
    content = category ? (
      <TemplateStep
        category={category}
        categoryLabel={categoryLabel}
        value={summary?.category === category ? templateId : null}
        onChange={(id) => chooseTemplate(category, id)}
        onNext={(id) => {
          chooseTemplate(category, id)
          goTo(2)
        }}
        onCustomTemplate={openCustom}
        onDeleteCustom={removeCustom}
        revealId={revealId}
        onRevealed={clearReveal}
      />
    ) : null
  } else if (!template || !settings || !estimate) {
    content = templateIssue ? (
      <section aria-labelledby={STEP_HEADINGS[step]} className="flex flex-col gap-5">
        <StepHeading id={STEP_HEADINGS[step]} title={tr(STEPS[step].label)} />
        <LoadError
          title={templateIssue.kind === 'missing' ? tr("Diese Hersteller-Serie gibt es nicht mehr") : tr("Vorlage nicht geladen")}
          error={templateIssue.kind === 'missing' ? null : templateIssue.error}
          description={
            templateIssue.kind === 'missing'
              ? tr("Die Vorlage „{v0}“ wurde gelöscht oder umbenannt. Bitte eine andere Hersteller‑Serie wählen.", { v0: templateId ?? '–' })
              : undefined
          }
          onRetry={
            templateIssue.kind === 'missing'
              ? undefined
              : () => void (templateIssue.kind === 'list' ? templates.refetch() : templateQuery.refetch())
          }
          retrying={templates.isFetching || templateQuery.isFetching}
          actions={
            <Button variant={templateIssue.kind === 'missing' ? 'secondary' : 'ghost'} leftIcon={<ArrowLeft />} onClick={() => goTo(1)}>
              {tr("Andere Serie wählen")}</Button>
          }
        />
      </section>
    ) : (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-10 w-1/2" />
        <div className="grid grid-cols-1 gap-5 @[68rem]:grid-cols-[minmax(0,1fr)_21.5rem]">
          <Skeleton className="h-[34rem] rounded-card" />
          <Skeleton className="h-80 rounded-card" />
        </div>
      </div>
    )
  } else if (step === 2) {
    content = (
      <ValuesStep
        template={template}
        settings={computed?.effective ?? settings}
        onChange={updateSettings}
        estimate={estimate}
        sizeCounts={serverPerSize ?? estimate.perSize}
        houseDensity={houseDensity}
        summary={{
          maxRows: SERIES_MAX_ROWS,
          preview: preview.data,
          current: previewCurrent,
          checking,
          error: previewError,
          onRetry: () => void preview.refetch(),
          example,
          sizeOrder: settings.sizes,
        }}
      />
    )
  } else if (step === 3) {
    content = (
      <PreviewStep
        template={template}
        categoryLabel={categoryLabel}
        preview={preview.data}
        loading={preview.isFetching}
        stale={!previewCurrent}
        error={
          !withinLimits
            ? new Error(tr("Die Auswahl ergibt {v0} Zeilen – höchstens {v1}.", { v0: formatNumber(rowsPlanned), v1: formatNumber(SERIES_MAX_ROWS) }))
            : previewError
        }
        onRetry={() => void preview.refetch()}
        sizes={settings.sizes}
        density={settings.density ?? houseDensity}
        internalScheme={internalScheme}
      />
    )
  } else {
    content = (
      <CommitStep
        template={template}
        categoryLabel={categoryLabel}
        preview={previewCurrent ? preview.data : undefined}
        previewError={previewError}
        mode={mode}
        onModeChange={setMode}
        job={jobInfo}
        starting={commit.isPending}
        startError={commit.error}
        busyWith={busyWith}
        onStart={() => commit.mutate()}
        onBack={() => {
          useSerien.getState().setJob(null)
          commit.reset()
          // ein abgebrochener oder fehlgeschlagener Job kann schon geschrieben haben
          void qc.invalidateQueries({ queryKey: [...seriesKeys.all, 'preview'] })
          goTo(3)
        }}
        onShowTable={showTable}
        onNewSeries={newSeries}
      />
    )
  }

  const showFooter = !(step === LAST_STEP && jobInfo)

  const onTemplateSaved = (savedTemplate: SeriesTemplate, info: { created: boolean }): boolean => {
    const title = info.created ? tr("Vorlage angelegt") : tr("Vorlage gespeichert")
    if (jobRunning) {
      // laufende Serie nicht verlassen – die Vorlage ist beim nächsten Mal in ihrer Kategorie vorgewählt
      useSerien.setState((s) => ({ lastTemplate: { ...s.lastTemplate, [savedTemplate.category]: savedTemplate.id } }))
      toast.success(title, {
        description: tr("{v0} – wählbar, sobald die laufende Serie fertig ist.", { v0: savedTemplate.title }),
      })
      return false
    }
    toast.success(title, { description: savedTemplate.title })
    useSerien.getState().setJob(null)
    commit.reset()
    chooseTemplate(savedTemplate.category, savedTemplate.id)
    setRevealId(savedTemplate.id)
    goTo(1)
    return true
  }

  return (
    <PageBody width="wide" className="flex min-h-[calc(100dvh-var(--pf-topbar-height))] flex-col gap-5 pb-0">
      <PageTitle title={tr("Serien-Assistent")} subtitle={subtitle} />
      <PageActions>
        {step > 0 && !jobInfo && (
          <Button variant="ghost" leftIcon={<RotateCcw />} onClick={newSeries}>
            {tr("Neu beginnen")}</Button>
        )}
        <Button variant="secondary" leftIcon={<FilePlus2 />} onClick={() => openCustom()}>
          {tr("Eigene Vorlage")}</Button>
      </PageActions>

      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {tr("Schritt {v0} von {v1}: {v2}", { v0: step + 1, v1: STEPS.length, v2: tr(STEPS[step].label) })}
      </p>
      <div ref={stepperRef} className="rounded-card border border-line bg-surface/70 px-3 py-2 shadow-card">
        <Stepper
          steps={(compactStepper ? STEPS_SHORT : STEPS).map((s) => ({ ...s, label: tr(s.label), description: s.description ? tr(s.description) : undefined }))}
          // abgeschlossen erst, wenn die Serie in der Bibliothek steht (nicht, wenn nichts geschrieben werden konnte)
          current={liveJob?.status === 'done' && step === LAST_STEP && seriesWritten(liveJob.result) ? STEPS.length : step}
          compact={compactStepper}
          onStepClick={(i) => goTo(i as StepIndex)}
        />
      </div>

      <motion.div
        ref={contentRef}
        key={step}
        initial={reduceMotion ? false : { opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
        // ohne Fußleiste (Fortschritt, Ergebnis) hält der Inhalt der Pille des Job-Docks Platz frei
        className={cn('flex min-h-0 flex-1 flex-col', showFooter ? 'pb-6' : 'pb-[max(1.5rem,var(--pf-dock-reserve))]')}
      >
        {content}
      </motion.div>

      {showFooter && (
        <WizardFooter
          onBack={step > 0 ? () => goTo((step - 1) as StepIndex) : undefined}
          context={footerContext}
          primary={
            next
              ? { label: next.label, onClick: next.run, disabled: next.disabled, reason: next.disabled ? next.reason : null }
              : undefined
          }
        />
      )}

      <CustomTemplateDialog
        open={dialog.open}
        editId={dialog.edit}
        defaultCategory={category ?? 'Resistors'}
        onOpenChange={(open) => setDialog((d) => ({ ...d, open }))}
        onSaved={onTemplateSaved}
      />
    </PageBody>
  )
}
