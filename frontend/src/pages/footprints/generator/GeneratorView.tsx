import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Footprint-Generator: links Eingabe (Familie, Vorlage, Dichte, Maßtabelle, Herstellerempfehlung), Mitte die Bühne
 * (Footprint mit Bemaßung, 3D), rechts das Rechenprotokoll. Schmalere Fenster: Protokoll als Reiter „Berechnung“
 * der Bühne plus Messleiste (Z/G/X, Pad, Prüfung) unter der Leinwand – die Leinwand bekommt die volle Breite.
 *
 * Live-Vorschau: jede Eingabe erzeugt (entprellt) eine neue Anfrage; veraltete Anfragen werden abgebrochen, der
 * letzte gültige Stand bleibt sichtbar. STEP und Speichern verwenden genau den angezeigten Stand.
 *
 * Speichern: Ein Probelauf (`PUT …?dry_run=true`) zeigt schon vor dem Klick, wohin der Footprint geschrieben wird
 * (neu, ersetzt einen gespeicherten oder ist bereits aktuell) und ob das Backend ihn annimmt. Beim Speichern prüft ein
 * frischer Probelauf erneut; ersetzt der Footprint einen gespeicherten, fragt PartForge vorher (mit Verwendung).
 */
import { useQuery } from '@tanstack/react-query'
import { Download, Info, LibraryBig, Redo2, TriangleAlert, Undo2, X } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { ApiError, errorMessage } from '@/api/client'
import {
  errorParams,
  footprintKeys,
  footprintsApi,
  generatorPreviewOptions,
  useGeneratorPreview,
  useSaveFootprint,
  type FootprintFamily,
  type FootprintSaveResult,
  type TimedPreview,
} from '@/api/footprints'
import { trackJob, useJob } from '@/api/jobs'
import { queryClient } from '@/api/queryClient'
import { useWorkspace, type Job } from '@/api/system'
import { runCommand, useRegisterCommands } from '@/app/commands'
import { PageActions } from '@/app/page'
import { CHROME_SURFACE } from '@/components/preview'
import { Button, confirm, IconButton, Separator, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { FILE_TYPES, notifySaveResult, saveFile } from '@/lib/download'
import { baseName, plural } from '@/lib/format'
import { useHotkey } from '@/lib/hotkeys'
import { densityLabel, readCalc, ROUNDING_LABEL } from '../lib/calc'
import { supportsLandPattern } from '../lib/families'
import { paramsInMessage } from '../lib/params'
import { buildRequest } from '../lib/request'
import { DensityControl } from './DensityControl'
import { FamilyPicker, type FamilyPick } from './FamilyPicker'
import { GeneratorStage, type StageTab } from './GeneratorStage'
import { LandPatternSection } from './LandPatternSection'
import { ParamTable } from './ParamTable'
import { PresetPicker } from './PresetPicker'
import { collectIssues, focusChecks, issueCounts } from './issues'
import { ResultBody, ResultPanel, ResultReadout, type SaveTarget } from './ResultPanel'
import { changedFromPreset, findPreset, undoWithFeedback, useGenerator, type Density } from './store'
import { useGeneratorUi } from './uiPrefs'

/** Ab dieser Breite (px) stehen Eingabe, Bühne und Protokoll nebeneinander */
const WIDE = 1160

function useDebouncedValue<T>(value: T, delay: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), delay)
    return () => window.clearTimeout(t)
  }, [value, delay])
  return v
}

/** Breite eines Elements – beim Einhängen gemessen (vor dem ersten Zeichnen, kein Springen des Layouts) */
function useWidth<T extends HTMLElement>(): [(el: T | null) => (() => void) | undefined, number] {
  const [width, setWidth] = useState(0)
  const ref = useCallback((el: T | null) => {
    if (!el) return undefined
    setWidth(el.getBoundingClientRect().width)
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width]
}

const geometryHash = (p: TimedPreview | null): string | null => {
  const h = (p?.spec.generator as Record<string, unknown> | null | undefined)?.geometry_hash
  return typeof h === 'string' ? h : null
}

export interface GeneratorViewProps {
  families: FootprintFamily[]
  /** Ansicht sichtbar (Aktionen, Kürzel und Befehle nur dann) */
  active: boolean
  /** Bibliothek zeigen (optional mit geöffnetem Footprint) */
  onShowLibrary: (name?: string) => void
}

export function GeneratorView({ families, active, onShowLibrary }: GeneratorViewProps) {
  useI18n()
  const navigate = useNavigate()
  const workspace = useWorkspace().data
  const style = workspace?.settings.footprint
  const styleKey = useLocalizedMemo(() => (style ? JSON.stringify(style) : 'standard'), [style])
  const styleDensity: Density = style?.density ?? 'N'

  const s = useGenerator()
  const family = families.find((f) => f.key === s.family) ?? null

  // Start: zuletzt benutzte Familie, sonst SOIC
  useEffect(() => {
    if (family || !families.length) return
    const start = families.find((f) => f.key === 'gullwing') ?? families[0]
    useGenerator.getState().selectFamily(start)
  }, [family, families])

  const density: Density = s.density ?? styleDensity

  const request = useLocalizedMemo(
    () => (family ? buildRequest(family, s.values, density, s.landPattern, s.overrides) : null),
    [family, s.values, density, s.landPattern, s.overrides],
  )
  const debounced = useDebouncedValue(request, s.lastChange === 'typing' ? 170 : 20)
  const preview = useGeneratorPreview(debounced, styleKey)

  // Letzter gültiger Stand bleibt sichtbar (auch bei Fehlern)
  const [lastGood, setLastGood] = useState<TimedPreview | null>(null)
  if (preview.data && !preview.isPlaceholderData && preview.data !== lastGood) setLastGood(preview.data)
  const shown = preview.data ?? lastGood
  const error = preview.isError && !preview.isFetching ? errorMessage(preview.error) : null
  const requestKey = JSON.stringify(request)
  const pending = requestKey !== JSON.stringify(debounced)
  const updating = preview.isFetching || pending
  const fresh = Boolean(preview.data) && !preview.isPlaceholderData && !updating && !error
  const calc = useLocalizedMemo(() => readCalc(shown?.calc), [shown])
  const issues = useLocalizedMemo(() => collectIssues(shown, calc), [shown, calc])
  const counts = issueCounts(issues)

  const shownFamily = typeof shown?.spec.generator?.family === 'string' ? shown.spec.generator.family : null
  const resolved =
    shown && family && shownFamily === family.key ? ((shown.spec.generator?.params as Record<string, unknown> | undefined) ?? null) : null
  const changed = useLocalizedMemo(() => new Set(changedFromPreset(family, s.preset, s.values)), [family, s.preset, s.values])
  // Fehlerhafte Parameter: ausdrücklich vom Backend genannt, sonst über die Bezeichnungen im Text
  const errorParamSet = useLocalizedMemo<ReadonlySet<string>>(() => {
    if (!error) return new Set()
    const named = errorParams(preview.error)
    return named ? new Set(named) : paramsInMessage(family?.params ?? [], error)
  }, [family, error, preview.error])

  const fallbacks = useLocalizedMemo(
    () => ({
      fab_tolerance: style?.fab_tolerance ?? 0.1,
      placement_tolerance: style?.placement_tolerance ?? 0.05,
      courtyard_excess: calc?.courtyard?.excess ?? null,
      courtyard_grid: style?.courtyard_grid ?? 0.05,
      min_copper_gap: style?.min_copper_gap ?? 0.15,
      rounding: tr("Hausstil ({value0})", { value0: String(tr(ROUNDING_LABEL[style?.rounding ?? 'kicad']) ?? style?.rounding ?? 'KiCad') }),
      drill: calc?.tht[0]?.hole ?? null,
      pad_diameter: calc?.tht[0]?.pad ?? null,
      ep_name: style?.exposed_pad_designator === 'EP' ? 'EP' : 'n + 1',
    }),
    [style, calc],
  )

  // Exposed Pad (für die Herstellerempfehlung): größtes Pad mit Bezeichner „EP“ bzw. n+1 in der Mitte
  const exposedPad = useLocalizedMemo(() => {
    const pads = shown?.spec.pads ?? []
    const center = pads.filter((p) => Math.abs(p.x) < 1e-6 && Math.abs(p.y) < 1e-6 && !p.hole)
    const ep = center.sort((a, b) => b.width * b.height - a.width * a.height)[0]
    return ep && pads.length > 2 ? { width: ep.width, height: ep.height } : null
  }, [shown])
  // Herstellerempfehlung nicht unterstützt (Kennzeichen der Familie vom Backend)
  const landUnsupported = family ? !supportsLandPattern(family) : false

  // ------------------------------------------------------------------ Aktionen
  const pickerOpen = useGeneratorUi((u) => u.pickerOpen)
  const setPickerOpen = useGeneratorUi((u) => u.setPickerOpen)
  const [busy, setBusy] = useState<'step' | 'save' | null>(null)
  const save = useSaveFootprint()
  const [saveJob, setSaveJob] = useState<{ id: string; name: string } | null>(null)
  const refreshLibrary = () => {
    void queryClient.invalidateQueries({ queryKey: footprintKeys.library })
    void queryClient.invalidateQueries({ queryKey: ['parts', 'library'] })
    void queryClient.invalidateQueries({ queryKey: ['stats'] })
  }
  // Speichern als Hintergrundjob: Rückmeldung kommt vom Job-Dock („… gespeichert in …“); hier nur Folgeaktionen
  const job = useJob(saveJob?.id ?? null, { onDone: refreshLibrary, onFailed: refreshLibrary, onCancelled: refreshLibrary })
  const saving = busy === 'save' || job.isActive

  // Probelauf des Speicherns für den angezeigten Stand: Ziel-Bibliothek, neu/ersetzt/aktuell, Annahme durch das Backend
  const planFor = active && fresh && shown && counts.errors === 0 ? shown : null
  const plan = useQuery({
    queryKey: footprintKeys.savePlan(planFor?.spec.name ?? '', geometryHash(planFor), styleKey),
    queryFn: ({ signal }) => footprintsApi.save((planFor as TimedPreview).spec, { dryRun: true, signal }),
    enabled: Boolean(planFor),
    staleTime: 15_000,
    retry: false,
  })
  const saveTarget: SaveTarget | null = !planFor
    ? null
    : plan.data
      ? {
          state: 'ready',
          library: plan.data.library,
          isNew: plan.data.new,
          unchanged: plan.data.unchanged,
          usage: plan.data.usage,
          error: null,
          onShow: plan.data.new ? null : () => onShowLibrary(planFor.spec.name),
        }
      : plan.isError
        ? { state: 'error', library: null, isNew: false, unchanged: false, usage: 0, error: errorMessage(plan.error), onShow: null }
        : { state: 'checking', library: null, isNew: false, unchanged: false, usage: 0, error: null, onShow: null }

  const onPick = (f: FootprintFamily, pick: FamilyPick) => {
    const st = useGenerator.getState()
    if (pick.values) {
      st.loadSnapshot(f, { family: f.key, params: pick.values }, { styleRounding: style?.rounding, notice: pick.note ?? null, label: tr('Alias geladen') })
    } else {
      st.selectFamily(f, pick.preset ?? null)
      if (pick.note) st.showNotice(pick.note)
    }
  }

  const stepBlockedReason = !shown
    ? tr('Noch keine Vorschau')
    : error
      ? tr('Erst den Fehler beheben – mit diesen Maßen entsteht kein Footprint')
      : null

  const downloadStep = async () => {
    if (stepBlockedReason || !shown) {
      toast(stepBlockedReason ?? tr('Noch keine Vorschau'), { id: 'fp-step-blocked' })
      return
    }
    if (busy) return
    // Inhalt und Dateiname aus derselben Vorschau (der angezeigten)
    const target = shown
    setBusy('step')
    try {
      const result = await saveFile({
        suggestedName: `${target.spec.name}.step`,
        load: () => footprintsApi.step(target.request),
        type: FILE_TYPES.step,
      })
      notifySaveResult(result, { what: tr('STEP-Datei'), id: 'fp-file' })
    } catch (e) {
      toast.error(tr('STEP-Export fehlgeschlagen'), { id: 'fp-file', description: errorMessage(e) })
    } finally {
      setBusy(null)
    }
  }

  /** Ergebnis eines direkten Speicherns melden (mit Ziel-Bibliothek und „Anzeigen“) */
  const announceSaved = (result: FootprintSaveResult, name: string) => {
    const rec = result.record
    const library = rec?.library ?? result.library
    const pending = rec && rec.status !== 'ok'
    toast[pending ? 'warning' : 'success'](pending ? tr("„{value0}“ vorgemerkt", { value0: String(name) }) : tr("„{value0}“ gespeichert", { value0: String(name) }), {
      id: 'fp-save',
      description: [library ? `${result.new ? tr('Neu in') : tr('Ersetzt in')} ${library}` : null, pending ? (rec?.status_message ?? tr('Noch nicht in die PcbLib geschrieben.')) : null]
        .filter(Boolean)
        .join(' – '),
      action: { label: tr('Anzeigen'), onClick: () => onShowLibrary(name) },
    })
  }

  const saveToLibrary = async () => {
    if (!request || busy || job.isActive) return
    setBusy('save')
    let specName = ''
    try {
      // Läuft die Berechnung noch (oder ist sie entprellt), auf das Ergebnis der aktuellen Eingabe warten
      const current = fresh && shown ? shown : await queryClient.fetchQuery(generatorPreviewOptions(request, styleKey))
      if (current.issues.some((i) => i.severity === 'error')) {
        toast(tr('Die Prüfung meldet Fehler – erst beheben'), { id: 'fp-save-blocked' })
        return
      }
      const spec = current.spec
      specName = spec.name
      // Frischer Probelauf: alle Prüfungen des Backends, Ziel-Bibliothek, neu oder ersetzt, unverändert
      const dry = await footprintsApi.save(spec, { dryRun: true })
      const library = dry.library ? baseName(dry.library) : tr('die Bibliothek')
      if (dry.unchanged) {
        toast.info(tr("„{value0}“ ist bereits aktuell", { value0: String(spec.name) }), {
          id: 'fp-save',
          description: tr("Gleiche Geometrie in {value0} – nichts zu schreiben.", { value0: String(library) }),
          action: { label: tr('Anzeigen'), onClick: () => onShowLibrary(spec.name) },
        })
        return
      }
      if (!dry.new) {
        const ok = await confirm({
          title: tr("„{value0}“ ersetzen?", { value0: String(spec.name) }),
          description:
            tr("In {value0} liegt bereits ein Footprint mit diesem Namen", { value0: String(library) }) +
            (dry.usage === 1
              ? tr(' – ein Bauteil verwendet ihn, sein Footprint ändert sich mit.')
              : dry.usage
                ? tr(" – {value0} ihn, ihr Footprint ändert sich mit.", { value0: String(plural(dry.usage, tr('Bauteil verwendet'), tr('Bauteile verwenden'))) })
                : tr('. Noch verwendet ihn kein Bauteil.')) +
            tr(' Er wird durch die neue Geometrie ersetzt (die alte Datei landet in der Sicherung).'),
          confirmLabel: tr('Ersetzen'),
          destructive: dry.usage > 0,
        })
        if (!ok) return
      }
      const result = await save.mutateAsync(spec)
      if (result.job) {
        // Fortschritt und Abschluss („… gespeichert in …“) meldet das Job-Dock
        const started = result.job as unknown as Job
        trackJob(started, { openDock: false })
        setSaveJob({ id: started.id, name: spec.name })
      } else {
        announceSaved(result, spec.name)
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 503) {
        // Registriert („ausstehend“), aber noch nicht in die PcbLib geschrieben
        toast.warning(tr("„{value0}“ vorgemerkt – noch nicht geschrieben", { value0: String(specName) }), {
          id: 'fp-save',
          duration: 12_000,
          description: tr("{value0} Der Footprint ist registriert und wird bei der nächsten Synchronisierung in die PcbLib geschrieben.", { value0: String(e.message) }),
          action: { label: tr('Synchronisieren'), onClick: () => void runCommand('library.sync', { navigate, close: () => {} }) },
        })
      } else if (e instanceof ApiError && e.status === 409) {
        const altium = /altium/i.test(e.message)
        toast.error(tr('Speichern nicht möglich'), {
          id: 'fp-save',
          duration: 12_000,
          description: altium
            ? e.message
            : tr("{value0} Tipp: Ist die PcbLib in Altium Designer geöffnet und geändert, dort speichern oder schließen – dann erneut speichern.", { value0: String(e.message) }),
        })
      } else {
        toast.error(tr('Speichern fehlgeschlagen'), { id: 'fp-save', description: errorMessage(e) })
      }
    } finally {
      setBusy(null)
    }
  }

  // Gesperrt nur bei echten Hindernissen – eine laufende Berechnung wird abgewartet (kein Flackern beim Tippen)
  const saveBlockedReason = !shown
    ? tr('Noch keine Vorschau')
    : error
      ? tr('Erst den Fehler beheben – mit diesen Maßen entsteht kein Footprint')
      : counts.errors > 0
        ? tr('Die Prüfung meldet Fehler – erst beheben')
        : null
  const trySave = () => {
    if (saveBlockedReason) {
      toast(saveBlockedReason, { id: 'fp-save-blocked' })
      return
    }
    void saveToLibrary()
  }

  const canUndo = s.past.length > 0
  const canRedo = s.future.length > 0
  // Strg+Z / Strg+Y außerhalb von Textfeldern (in den Maßfeldern behandelt die Tabelle die Tasten selbst)
  useHotkey('mod+z', () => undoWithFeedback('undo'), { enabled: active, allowInInputs: false })
  useHotkey(['mod+y', 'mod+shift+z'], () => undoWithFeedback('redo'), { enabled: active, allowInInputs: false })

  useRegisterCommands(
    active
      ? [
          {
            id: 'footprints.family',
            title: tr('Gehäusefamilie wählen …'),
            group: 'Footprints',
            hotkey: 'mod+f',
            keywords: ['familie', 'gehäuse', 'package', 'soic', 'qfn'],
            run: () => setPickerOpen(true),
          },
          {
            id: 'footprints.save',
            title: tr('Footprint in Bibliothek speichern'),
            subtitle: shown?.spec.name,
            group: 'Footprints',
            icon: LibraryBig,
            hotkey: 'mod+s',
            run: trySave,
          },
          {
            id: 'footprints.step',
            title: tr('STEP-Modell herunterladen'),
            subtitle: shown?.spec.name,
            group: 'Footprints',
            icon: Download,
            when: () => !stepBlockedReason,
            run: () => void downloadStep(),
          },
          {
            id: 'footprints.undo',
            title: tr('Rückgängig'),
            subtitle: s.past[s.past.length - 1]?.label ? tr("{value0} · Strg+Z", { value0: String(s.past[s.past.length - 1]?.label) }) : tr('Strg+Z'),
            group: 'Footprints',
            icon: Undo2,
            when: () => canUndo,
            run: () => undoWithFeedback('undo'),
          },
          {
            id: 'footprints.redo',
            title: tr('Wiederholen'),
            subtitle: s.future[s.future.length - 1]?.label ? tr("{value0} · Strg+Y", { value0: String(s.future[s.future.length - 1]?.label) }) : tr('Strg+Y'),
            group: 'Footprints',
            icon: Redo2,
            when: () => canRedo,
            run: () => undoWithFeedback('redo'),
          },
          {
            id: 'footprints.copy-ipc',
            title: tr('IPC-Namen kopieren'),
            subtitle: calc?.ipcName ?? undefined,
            group: 'Footprints',
            when: () => Boolean(calc?.ipcName),
            run: async () => {
              if (!calc?.ipcName) return
              try {
                await navigator.clipboard.writeText(calc.ipcName)
                toast.success(tr('IPC-Name kopiert'), { description: calc.ipcName })
              } catch {
                toast.error(tr('Kopieren nicht möglich'))
              }
            },
          },
          ...(['L', 'N', 'M'] as const).map((d) => ({
            id: `footprints.density.${d}`,
            title: tr("Dichte {value0}", { value0: String(densityLabel(d)) }),
            group: 'Footprints',
            keywords: ['dichte', 'density', 'ipc'],
            when: () => density !== d,
            run: () => s.setDensity(d),
          })),
        ]
      : [],
  )

  // ------------------------------------------------------------------ Layout
  const [rootRef, width] = useWidth<HTMLDivElement>()
  const wide = width === 0 || width >= WIDE
  const [stageTab, setStageTab] = useState<StageTab>('footprint')
  const showIssues = () => {
    if (wide) focusChecks()
    else {
      setStageTab('calc')
      window.setTimeout(focusChecks, 60)
    }
  }

  if (!family) return null

  const stageResetKey = `${family.key}:${s.preset ?? 'eigen'}`
  const issueTotal = counts.errors + counts.warnings

  return (
    <div
      ref={rootRef}
      className={cn(
        'grid h-full min-h-0 gap-3',
        wide
          ? 'grid-cols-[clamp(316px,28%,348px)_minmax(0,1fr)_clamp(272px,23%,300px)]'
          : 'grid-cols-[clamp(316px,34%,348px)_minmax(0,1fr)]',
      )}
    >
      {active && (
        <PageActions>
          <Tooltip content={stepBlockedReason ?? tr("{value0}.step – extrudierte 3D‑Körper", { value0: String(shown?.spec.name ?? 'Footprint') })}>
            <span className="inline-flex">
              <Button
                variant="secondary"
                leftIcon={<Download />}
                loading={busy === 'step'}
                aria-disabled={Boolean(stepBlockedReason) || undefined}
                onClick={() => void downloadStep()}
              >
                {tr("STEP herunterladen")}
              </Button>
            </span>
          </Tooltip>
          <Tooltip
            content={
              saveBlockedReason ??
              (saveTarget?.state === 'ready' && saveTarget.library
                ? saveTarget.unchanged
                  ? tr("Bereits aktuell in {value0}", { value0: String(baseName(saveTarget.library)) })
                  : `${saveTarget.isNew ? tr('Neu in') : tr('Ersetzt in')} ${baseName(saveTarget.library)}`
                : tr('In die Footprint-Bibliothek schreiben'))
            }
            hotkey={saveBlockedReason ? undefined : 'mod+s'}
          >
            <span className="inline-flex">
              <Button
                variant="primary"
                leftIcon={<LibraryBig />}
                loading={saving}
                aria-disabled={Boolean(saveBlockedReason) || undefined}
                aria-keyshortcuts="Control+S"
                onClick={trySave}
              >
                {tr("In Bibliothek speichern")}
              </Button>
            </span>
          </Tooltip>
        </PageActions>
      )}

      {/* ------------------------------------------------------------ Eingabe */}
      <aside
        aria-labelledby="fp-input-title"
        className="@container/input flex min-h-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card"
      >
        <h2 id="fp-input-title" className="sr-only">
          {tr("Eingabe")}
        </h2>
        {/* kein Innenabstand oben: der klebende Tabellenkopf schließt bündig ab */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-5 [scrollbar-gutter:stable]">
          <div aria-hidden className="h-3.5" />
          <FamilyPicker families={families} value={family} onPick={onPick} open={pickerOpen} onOpenChange={setPickerOpen} />
          <NoticeLine />
          <div className="mt-4">
            <PresetPicker
              family={family}
              presets={family.presets}
              value={s.preset}
              changed={changed.size}
              onSelect={(p) => s.selectPreset(family, p)}
              onReset={() => s.resetAll(family)}
            />
            <SuggestionLine family={family} />
          </div>
          <Separator className="my-4" />
          <DensityControl value={density} styleDensity={styleDensity} onChange={s.setDensity} />
          <Separator className="mb-1 mt-4" />
          <ParamTable
            family={family}
            values={s.values}
            resolved={resolved}
            fallbacks={fallbacks}
            errorParams={errorParamSet}
            changed={changed}
            onChange={(name, value, opts) => s.setParam(family, name, value, opts)}
            onReset={(name) => s.resetParam(family, name)}
          />
          <Separator className="my-3" />
          <LandPatternSection
            state={s.landPattern}
            onChange={s.setLandPattern}
            lands={calc?.lands ?? []}
            exposedPad={exposedPad}
            unsupported={landUnsupported}
          />
        </div>
      </aside>

      {/* ------------------------------------------------------------ Bühne */}
      <GeneratorStage
        spec={shown?.spec ?? null}
        calc={shown?.calc}
        loading={!shown && !error}
        updating={updating && Boolean(shown)}
        error={error ? localizeMessage(error) : error}
        resetKey={stageResetKey}
        family={family.key}
        tab={stageTab}
        onTabChange={setStageTab}
        calcPanel={wide ? undefined : <ResultBody data={shown} error={error ? localizeMessage(error) : error} saveTarget={saveTarget} />}
        calcBadge={
          !wide && issueTotal > 0 ? (
            <span
              className={cn(
                'ml-1 rounded-full px-1.5 text-2xs font-semibold leading-4 tabular-nums',
                counts.errors ? 'bg-danger/15 text-danger-text' : 'bg-warning/15 text-warning-text',
              )}
            >
              {issueTotal}
              <span className="sr-only"> {counts.errors ? tr('Fehler') : issueTotal === 1 ? tr('Warnung') : tr('Warnungen')}</span>
            </span>
          ) : undefined
        }
        readout={wide ? undefined : <ResultReadout data={shown} error={error ? localizeMessage(error) : error} onShowIssues={showIssues} />}
        overlay={wide && !error ? <BoardIssueChip counts={counts} onClick={showIssues} /> : undefined}
        className="min-h-0 min-w-0"
      />

      {wide && (
        <ResultPanel data={shown} fetching={updating && !error} error={error ? localizeMessage(error) : error} saveTarget={saveTarget} className="min-h-0" />
      )}
    </div>
  )
}

/** Warn-/Fehlerzähler auf der (immer dunklen) Leiterplatte – führt zur Prüfung */
function BoardIssueChip({ counts, onClick }: { counts: { errors: number; warnings: number }; onClick: () => void }) {
  useI18n()
  if (!counts.errors && !counts.warnings) return null
  const danger = counts.errors > 0
  const n = danger ? counts.errors : counts.warnings
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex h-7 items-center gap-1.5 rounded-control px-2.5 text-2xs font-medium outline-none transition-colors focus-ring',
        CHROME_SURFACE.board,
        'hover:border-white/20',
      )}
    >
      <TriangleAlert aria-hidden className={cn('size-3.5', danger ? 'text-danger' : 'text-warning')} />
      {danger ? tr("{value0} Fehler", { value0: String(n) }) : `${n} ${n === 1 ? tr('Warnung') : tr('Warnungen')}`}
      <span className="sr-only"> {tr("– zur Prüfung")}</span>
    </button>
  )
}

/** Kurzer Hinweis nach automatischen Wechseln (Vorlage übernommen, Alias aufgelöst …) */
function NoticeLine() {
  useI18n()
  const notice = useGenerator((s) => s.notice)
  const dismiss = useGenerator((s) => s.dismissNotice)
  useEffect(() => {
    if (!notice) return
    const t = window.setTimeout(dismiss, 4500)
    return () => window.clearTimeout(t)
  }, [notice, dismiss])
  return (
    <div role="status" aria-live="polite">
      <AnimatePresence initial={false}>
        {notice && (
          <motion.div
            key={notice.at}
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.18 }}
            className="overflow-hidden"
          >
            <div className="mt-2 flex items-center gap-2 rounded-control border border-line bg-surface-2/70 px-2.5 py-1.5 text-2xs text-fg-muted">
              <Info aria-hidden className="size-3.5 shrink-0 text-info-text" />
              <span className="min-w-0 flex-1">{notice.text}</span>
              <button type="button" aria-label={tr("Hinweis schließen")} onClick={dismiss} className="rounded-sm text-fg-subtle outline-none hover:text-fg focus-ring">
                <X className="size-3" />
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** Vorschlag einer passenden Vorlage, wenn Selektoren bei angepassten Werten geändert wurden */
function SuggestionLine({ family }: { family: FootprintFamily }) {
  useI18n()
  const suggestion = useGenerator((s) => s.suggestion)
  const preset = findPreset(family, suggestion)
  if (!preset) return null
  return (
    <div className="mt-2 flex items-center gap-2 rounded-control border border-accent/25 bg-accent-soft/60 px-2.5 py-1.5 text-2xs">
      <span className="min-w-0 flex-1 text-fg-muted">
        {tr("Passende Vorlage:")}{' '}<span className="mono font-semibold text-fg">{preset.key}</span>
      </span>
      <Button size="xs" variant="secondary" onClick={() => useGenerator.getState().selectPreset(family, preset)}>
        {tr("Übernehmen")}
      </Button>
      <IconButton size="xs" label={tr("Vorschlag verwerfen")} icon={<X />} onClick={() => useGenerator.setState({ suggestion: null })} />
    </div>
  )
}
