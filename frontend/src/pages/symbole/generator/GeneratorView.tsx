/**
 * Generator-Ansicht: Symboltypen links (einklappbar), Editor in der Mitte (Standardsymbol-Parameter oder IC-Editor),
 * Live-Vorschau rechts. Speichern über die Topbar („In Bibliothek speichern“, Strg+S; „Speichern unter …“,
 * Strg+⇧+S) bzw. die Befehlspalette. Ungültige Eingaben (Name, Präfix, Pinliste) prüft schon das Frontend – dann
 * geht keine Anfrage ans Backend, und Name/Status/Pinbelegung zeigen keine veralteten Ergebnisse.
 *
 * Speichern mit Probelauf (`PUT …?dry_run=true`): Schon beim Bearbeiten zeigt der Editor, in welche SchLib das Symbol
 * geschrieben wird, ob es neu ist, bereits aktuell – und ob sich die Pinbelegung eines gespeicherten Symbols ändert
 * (mit Verwendung). Beim Speichern prüft ein frischer Probelauf erneut; eine Pinänderung muss bestätigt werden
 * (`allow_pinout_change`), sonst antwortet das Backend 409 „pinout_changed“ mit denselben Angaben.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Cpu, FilePlus2, RotateCcw, Save, SaveAll, Shapes, Square } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { ApiError, errorMessage } from '@/api/client'
import { useCategories } from '@/api/library'
import {
  pinoutChanged,
  shortHash,
  symbolKeys,
  symbolPreviewOptions,
  symbolsApi,
  useSaveSymbol,
  useSymbolGeneratorPreview,
  useSymbolKinds,
  useSymbolLibrary,
  useSymbolStyleKey,
  type SymbolEntry,
  type SymbolKindInfo,
  type SymbolParamSpec,
  type SymbolPreviewOut,
  type SymbolRequest,
} from '@/api/symbols'
import { useRegisterCommands } from '@/app/commands'
import { PageActions } from '@/app/page'
import { useTheme } from '@/app/theme'
import { SplitPane } from '@/components/data'
import { usePreviewPrefs } from '@/components/preview'
import { Button, EmptyState, IconButton, Skeleton, Tooltip } from '@/components/ui'
import { baseName, plural } from '@/lib/format'
import { IcEditor } from '../ic/IcEditor'
import { validatePins } from '../ic/pins'
import { EMPTY_EXTRAS, EMPTY_IC, IC_KIND, icRequest, useGenerator, useSymbolUiPrefs } from '../store'
import { useSymbolJob } from '../useSymbolJob'
import {
  changedParams,
  connectorRequestPins,
  copyText,
  effectiveParams,
  isParamModified,
  paramDefault,
  prefixError,
  sameValue,
  suggestFreeName,
  symbolNameError,
  useDebouncedValue,
} from '../util'
import { KindBrowser } from './KindBrowser'
import { PreviewStage } from './PreviewStage'
import { SaveAsDialog, SaveConflictDialog, type ConflictChoice, type SaveConflict } from './SaveDialogs'
import { StandardEditor } from './StandardEditor'

export interface GeneratorViewProps {
  /** Symboltypen-Leiste eingeklappt (Seite steuert den Umschalter in der Ansichtsleiste) */
  kindsCollapsed: boolean
  onKindsCollapsedChange: (collapsed: boolean) => void
  /** Nach dem Speichern: Symbol in der Bibliothek zeigen */
  onShowInLibrary: (name: string) => void
  /** Schmaler Inhaltsbereich (Mindestbreite): kleinere Standardbreite der Vorschau im IC-Editor */
  compact?: boolean
}

/** Ergebnis des Speicher-Probelaufs (für Editor und Knopf) */
export interface SymbolSavePlan {
  checking: boolean
  /** Ziel-Bibliotheksdatei (relativ) */
  library: string | null
  isNew: boolean
  unchanged: boolean
  usage: number
  /** Änderungen der Pinbelegung eines gespeicherten Symbols (deutsch) */
  changes: string[]
  /** Das Backend würde ablehnen (extern, fremdes Bauteil, ungültig) */
  error: string | null
}

const specKind = (data: SymbolPreviewOut | undefined) =>
  (data?.spec.generator as { kind?: unknown } | null | undefined)?.kind as string | undefined

interface SaveOptions {
  /** Unter diesem Namen speichern („Speichern unter …“) */
  name?: string
  allowPinoutChange?: boolean
  /** Rückfrage „fremde Zeichnung ersetzen“ schon bestätigt */
  replaceConfirmed?: boolean
}

export function GeneratorView({ kindsCollapsed, onKindsCollapsedChange, onShowInLibrary, compact = false }: GeneratorViewProps) {
  const qc = useQueryClient()
  const { resolvedTheme } = useTheme()
  const prefs = usePreviewPrefs()
  const kinds = useSymbolKinds(resolvedTheme)
  const categories = useCategories()
  const library = useSymbolLibrary()
  const styleKey = useSymbolStyleKey()
  const setUiPrefs = useSymbolUiPrefs((s) => s.set)

  const kindKey = useGenerator((s) => s.kind)
  const setKind = useGenerator((s) => s.setKind)
  const overrides = useGenerator((s) => s.params[kindKey])
  const storedExtras = useGenerator((s) => s.extras[kindKey])
  const extras = useMemo(() => ({ ...EMPTY_EXTRAS, ...storedExtras }), [storedExtras])
  const ic = useGenerator((s) => s.ic)
  const setParam = useGenerator((s) => s.setParam)
  const setExtras = useGenerator((s) => s.setExtras)
  const resetParams = useGenerator((s) => s.resetParams)

  const kind: SymbolKindInfo | undefined = kinds.data?.find((k) => k.key === kindKey) ?? kinds.data?.[0]
  const isIc = kind?.key === IC_KIND
  // unbekannter Typ (alter Entwurf o. Ä.): auf den ersten Typ wechseln (?art=… prüft schon die Seite)
  useEffect(() => {
    if (kinds.data?.length && !kinds.data.some((k) => k.key === kindKey)) setKind(kinds.data[0].key)
  }, [kinds.data, kindKey, setKind])
  const values = useMemo(() => (kind ? effectiveParams(kind, overrides) : {}), [kind, overrides])

  // ------------------------------------------------------------------ lokale Prüfung, Anfrage (entprellt), Vorschau
  const icErrors = useMemo(() => (isIc ? validatePins(ic.pins, { partsMode: ic.partsMode }).errorCount : 0), [isIc, ic.pins, ic.partsMode])
  const localError: string | null = useMemo(() => {
    if (!kind) return null
    if (isIc) {
      if (icErrors > 0) return `Die Pinliste enthält ${icErrors === 1 ? 'einen Fehler' : `${icErrors} Fehler`} – Details unter der Tabelle.`
      const nameErr = symbolNameError(ic.name)
      if (nameErr) return `Name: ${nameErr}`
      const prefixErr = prefixError(ic.prefix)
      if (prefixErr) return `Präfix: ${prefixErr}`
      return null
    }
    const nameErr = symbolNameError(extras.name)
    if (nameErr) return `Eigener Name (Erweitert): ${nameErr}`
    const prefixErr = prefixError(extras.prefix)
    if (prefixErr) return `Präfix (Erweitert): ${prefixErr}`
    return null
  }, [kind, isIc, icErrors, ic.name, ic.prefix, extras.name, extras.prefix])

  const request: SymbolRequest | null = useMemo(() => {
    if (!kind || localError) return null
    if (isIc) return ic.pins.length ? icRequest(ic) : null
    const req: SymbolRequest = {
      kind: kind.key,
      params: changedParams(kind, values),
      name: extras.name.trim() || null,
      designator_prefix: extras.prefix.trim() || null,
      description: extras.description.trim() || null,
    }
    if (kind.key === 'connector') {
      const pins = connectorRequestPins(values, extras.pins)
      if (pins.length) req.pins = pins
    }
    return req
  }, [kind, localError, isIc, ic, values, extras])
  const requestJson = request ? JSON.stringify(request) : ''
  const debouncedJson = useDebouncedValue(requestJson, isIc ? 260 : 120)
  const debounced = useMemo(() => (debouncedJson ? (JSON.parse(debouncedJson) as SymbolRequest) : null), [debouncedJson])
  const preview = useSymbolGeneratorPreview(debounced)

  // letzte gültige Vorschau behalten (auch bei Fehlern), aber nie die eines anderen Symboltyps zeigen
  const [lastGood, setLastGood] = useState<SymbolPreviewOut | undefined>(undefined)
  if (preview.data && !preview.isPlaceholderData && preview.data !== lastGood) setLastGood(preview.data)
  const shown = preview.data ?? lastGood
  const pendingDebounce = requestJson !== debouncedJson
  const shownMatches = Boolean(shown && specKind(shown) === kind?.key && (isIc ? ic.pins.length > 0 : true))
  /** Spec für die Leinwand (bleibt bei Fehlern als „letzte gültige Vorschau“ sichtbar) */
  const spec = shownMatches ? shown?.spec : undefined
  const generatorError = request && preview.error && !pendingDebounce ? errorMessage(preview.error) : null
  const previewError = localError ?? generatorError
  /** Spec, der zum aktuellen Stand passt – nur damit Name, Status, Pinbelegung und Kopieren arbeiten */
  const validSpec = previewError ? undefined : spec
  const fetching = Boolean(request) && (preview.isFetching || pendingDebounce)
  const warnings = previewError || !shownMatches ? [] : (shown?.warnings ?? [])

  const entries = library.data
  const libraryNames = useMemo(() => (entries ? new Set(entries.map((e) => e.name.toLowerCase())) : undefined), [entries])
  const findEntry = (name: string | undefined | null): SymbolEntry | null =>
    name ? (entries?.find((e) => e.name.toLowerCase() === name.toLowerCase()) ?? null) : null

  // Ziel neuer Namen: Aus der Bibliothek geladene Entwürfe („Bearbeiten“) speichern Kopien ausdrücklich in die SchLib
  // des Originals (z. B. PF_Power.SchLib, `library`), sonst entscheidet die Standardkategorie des Symboltyps
  // (IC → PF_ICs.SchLib). Schon registrierte Namen bleiben in ihrer Datei – für sie geht keine Zielbibliothek mit (eine
  // andere lehnte das Backend mit 409 ab). Ohne geladene Liste entscheidet das Backend (automatisch).
  const origin = (isIc ? ic.origin : extras.origin) ?? null
  const saveCategory = kind?.categories[0] ?? null
  const targetLibrary = (name: string | null | undefined): string | null =>
    origin && entries && name && !findEntry(name) ? origin.library : null

  // Probelauf des Speicherns für den gültigen Stand: Ziel-SchLib, neu/aktuell, Pinänderungen, Ablehnung
  const planSpec = validSpec && !fetching ? validSpec : null
  const planKey = useMemo(() => (planSpec ? shortHash(JSON.stringify(planSpec)) : ''), [planSpec])
  const planLibrary = targetLibrary(planSpec?.name)
  const planQuery = useQuery({
    queryKey: symbolKeys.savePlan(planSpec?.name ?? '', planKey, saveCategory, planLibrary),
    queryFn: ({ signal }) =>
      symbolsApi.save(
        {
          spec: planSpec as SymbolPreviewOut['spec'],
          category: saveCategory,
          source: 'generated',
          allow_pinout_change: false,
          library: planLibrary,
        },
        { dryRun: true, signal },
      ),
    enabled: Boolean(planSpec),
    staleTime: 15_000,
    retry: false,
  })
  const plan: SymbolSavePlan | null = !planSpec
    ? null
    : planQuery.data
      ? {
          checking: false,
          library: planQuery.data.library,
          isNew: planQuery.data.new,
          unchanged: planQuery.data.unchanged,
          usage: planQuery.data.usage,
          changes: planQuery.data.changes,
          error: null,
        }
      : {
          checking: planQuery.isFetching,
          library: null,
          isNew: false,
          unchanged: false,
          usage: 0,
          changes: [],
          error: planQuery.error ? errorMessage(planQuery.error) : null,
        }
  const libraryInfo = {
    available: true,
    loading: library.isLoading,
    entry: findEntry(validSpec?.name),
    plan,
  }

  // ------------------------------------------------------------------ Hover, Teil, Fokus
  const [hover, setHover] = useState<string | null>(null)
  const [highlight, setHighlight] = useState<string[] | null>(null)
  const [part, setPart] = useState(1)
  const [partFor, setPartFor] = useState(kindKey)
  if (partFor !== kindKey) {
    setPartFor(kindKey)
    setPart(1)
  }
  const [focusRequest, setFocusRequest] = useState<{ id: string; nonce: number } | null>(null)
  const focusRow = (id: string) => {
    setUiPrefs({ icTab: 'pins' })
    setFocusRequest({ id, nonce: Date.now() })
  }
  /** Speichern ohne IC-Namen versucht (Zähler für den Editor) */
  const [nameAttempt, setNameAttempt] = useState(0)

  const chooseKind = (key: string) => {
    setKind(key)
    setHover(null)
    setHighlight(null)
    setNameAttempt(0)
  }

  const onParam = (p: SymbolParamSpec, value: unknown) => kind && setParam(kind.key, p.name, value, sameValue(value, paramDefault(p)))

  // ------------------------------------------------------------------ Speichern
  const save = useSaveSymbol()
  const savedToast = (name: string, library: string | null, isNew = false) =>
    toast.success(`„${name}“ gespeichert`, {
      id: 'symbole-save',
      description: library ? `${isNew ? 'Neu in' : 'Aktualisiert in'} ${library}` : 'In die Symbolbibliothek geschrieben.',
      action: { label: 'In der Bibliothek zeigen', onClick: () => onShowInLibrary(name) },
    })
  // Speichern als Hintergrundjob (Altium geöffnet o. Ä.): Das Job-Dock meldet den Abschluss mit Ziel
  // („Symbol „X“ gespeichert in Symbols\PF_….SchLib“); danach lädt die Bibliothek neu (Name, Status, Plan).
  const startJob = useSymbolJob()

  const icNameMissing = isIc && ic.pins.length > 0 && !ic.name.trim()
  const canSave = Boolean(request) && !previewError && !save.isPending && !icNameMissing
  /** Warum Speichern gerade nicht geht (Tooltip am Knopf, Hinweis bei Strg+S) */
  const blockedReason = canSave
    ? null
    : save.isPending
      ? 'Wird gespeichert …'
      : !kind
        ? 'Die Symboltypen sind noch nicht geladen.'
        : isIc && !ic.pins.length
          ? 'Die Pinliste ist noch leer.'
          : (localError ??
            (icNameMissing ? 'Bitte zuerst einen Namen eingeben.' : (generatorError ?? (fetching ? 'Die Vorschau wird berechnet …' : 'Das Symbol ist noch nicht gültig.'))))

  const [conflict, setConflict] = useState<(SaveConflict & { resolve: (c: ConflictChoice) => void }) | null>(null)
  const askConflict = (c: SaveConflict) => new Promise<ConflictChoice>((resolve) => setConflict({ ...c, resolve }))
  const [saveAs, setSaveAs] = useState<{ open: boolean; initial: string }>({ open: false, initial: '' })
  const currentName = validSpec?.name ?? (isIc ? ic.name.trim() : extras.name.trim())
  const openSaveAs = () =>
    setSaveAs({
      open: true,
      // unbenanntes IC: kein Vorschlag aus dem Platzhalternamen („IC 10-Pin 2“) – der Name gehört dem Nutzer
      initial: isIc && !ic.name.trim() ? '' : suggestFreeName(currentName || kind?.default_name || 'Symbol', entries),
    })

  /** Nach „Speichern unter …“ arbeitet der Entwurf mit dem neuen Namen weiter */
  const adoptName = (name: string) => {
    if (!kind) return
    if (isIc) useGenerator.getState().updateIc((d) => ({ ...d, name }))
    else setExtras(kind.key, { name })
  }

  /** Rückfrage bei geänderter Pinbelegung (aus Probelauf oder 409 „pinout_changed“) */
  const askPinout = (name: string, changes: string[], usage: number) =>
    askConflict({
      title: `Pinbelegung von „${name}“ ändert sich`,
      description: (
        <>
          {changes.length > 0 ? (
            <ul className="mb-2 flex max-h-40 flex-col gap-0.5 overflow-y-auto rounded-control border border-line bg-surface-2/50 px-3 py-2 text-xs">
              {changes.slice(0, 12).map((c) => (
                <li key={c} className="mono text-fg">
                  {c}
                </li>
              ))}
              {changes.length > 12 && <li className="text-fg-subtle">… und {changes.length - 12} weitere</li>}
            </ul>
          ) : (
            <p className="mb-2">Die Pins des gespeicherten Symbols unterscheiden sich vom Entwurf.</p>
          )}
          <p>
            {usage === 1
              ? 'Ein Bauteil verwendet das Symbol – die Zuordnung seiner Pins zum Footprint ändert sich mit. Bitte danach das Bauteil prüfen.'
              : usage > 1
                ? `${plural(usage, 'Bauteil verwendet', 'Bauteile verwenden')} das Symbol – die Zuordnung ihrer Pins zum Footprint ändert sich mit. Bitte danach die Bauteile prüfen.`
                : 'Noch verwendet kein Bauteil das Symbol – die Änderung ist unkritisch.'}
          </p>
        </>
      ),
      confirmLabel: 'Neue Belegung übernehmen',
      destructive: usage > 0,
    })

  const doSave = async (opts: SaveOptions = {}): Promise<void> => {
    if (!request || !kind) return
    const req: SymbolRequest = opts.name ? { ...request, name: opts.name } : request
    let fresh: SymbolPreviewOut
    try {
      // genau das speichern, was die Vorschau für den aktuellen Stand zeigt (auch während der Entprellung)
      fresh = await qc.fetchQuery(symbolPreviewOptions(req, styleKey))
    } catch (error) {
      toast.error('Symbol ist nicht gültig', { id: 'symbole-save', description: errorMessage(error) })
      return
    }
    const name = fresh.spec.name
    const existing = findEntry(name)

    // Symbole externer Bibliotheken sind schreibgeschützt – gleich den Ausweg anbieten
    if (existing?.source === 'external') {
      toast.error(`„${existing.name}“ ist schreibgeschützt`, {
        id: 'symbole-save',
        description: `Es gehört zur externen Bibliothek ${baseName(existing.library)}. Bitte unter einem neuen Namen speichern.`,
        action: { label: 'Speichern unter …', onClick: openSaveAs },
      })
      return
    }

    // Gleichnamiges Symbol ohne Generator (importiert, Datenblatt) bzw. anderen Typs: Zeichnung würde ersetzt
    if (existing && existing.kind !== kind.key && !opts.replaceConfirmed && !opts.allowPinoutChange) {
      const typeLabel = existing.kind ? (kinds.data?.find((k) => k.key === existing.kind)?.label ?? existing.kind) : null
      const choice = await askConflict({
        title: `„${existing.name}“ ersetzen?`,
        description: (
          <>
            <p>
              {typeLabel ? (
                <>
                  In der Bibliothek ist „{existing.name}“ ein Symbol vom Typ <span className="font-medium text-fg">{typeLabel}</span>.
                </>
              ) : (
                <>„{existing.name}“ wurde importiert bzw. von Hand gezeichnet und hat keine Generator-Angaben.</>
              )}{' '}
              Beim Speichern wird seine Zeichnung durch {isIc ? 'ein Kastensymbol aus der Pinliste' : `das ${kind.label}-Symbol`} ersetzt.
            </p>
            <p className="mt-2">
              {existing.usage > 0
                ? `${plural(existing.usage, 'Bauteil verwendet', 'Bauteile verwenden')} das Symbol – ihre Schaltpläne zeigen danach die neue Zeichnung.`
                : 'Noch verwendet kein Bauteil das Symbol.'}
            </p>
          </>
        ),
        confirmLabel: 'Zeichnung ersetzen',
        destructive: existing.usage > 0,
      })
      if (choice === 'saveAs') openSaveAs()
      if (choice !== 'confirm') return
      return doSave({ ...opts, replaceConfirmed: true })
    }

    const input = {
      spec: fresh.spec,
      category: saveCategory,
      source: 'generated' as const,
      allow_pinout_change: opts.allowPinoutChange ?? false,
      library: targetLibrary(name),
    }
    try {
      // Probelauf: alle Prüfungen des Backends, Ziel, unverändert, Pinänderungen – nichts wird geschrieben
      const dry = await symbolsApi.save(input, { dryRun: true })
      if (dry.unchanged) {
        if (opts.name) adoptName(name)
        toast.info(`„${name}“ ist bereits aktuell`, {
          id: 'symbole-save',
          description: `Gleiche Zeichnung in ${dry.library ? baseName(dry.library) : 'der Bibliothek'} – nichts zu schreiben.`,
          action: { label: 'In der Bibliothek zeigen', onClick: () => onShowInLibrary(name) },
        })
        return
      }
      if (dry.needs_confirmation && !opts.allowPinoutChange) {
        const choice = await askPinout(name, dry.changes, dry.usage)
        if (choice === 'saveAs') openSaveAs()
        if (choice === 'confirm') await doSave({ ...opts, allowPinoutChange: true, replaceConfirmed: true })
        return
      }
      const result = await save.mutateAsync(input)
      if (opts.name) adoptName(name)
      if (result.kind === 'job') startJob(result.job)
      else savedToast(name, result.record.library, dry.new)
    } catch (error) {
      const pinout = pinoutChanged(error)
      if (pinout) {
        const choice = await askPinout(name, pinout.changes, pinout.usage)
        if (choice === 'saveAs') openSaveAs()
        if (choice === 'confirm') await doSave({ ...opts, allowPinoutChange: true, replaceConfirmed: true })
        return
      }
      if (error instanceof ApiError && error.status === 503) {
        toast.warning(`„${name}“ vorgemerkt – noch nicht geschrieben`, {
          id: 'symbole-save',
          duration: 12_000,
          description: `${error.message} Das Symbol ist registriert und wird bei der nächsten Synchronisierung in die SchLib geschrieben.`,
        })
        return
      }
      toast.error('Symbol konnte nicht gespeichert werden', { id: 'symbole-save', description: errorMessage(error) })
    }
  }

  const copyName = () => validSpec && void copyText(validSpec.name, 'Symbolname')

  /** Strg+S und Knopf: auch ohne gültiges Symbol abfangen (sonst öffnet WebView2 „Seite speichern“) und erklären */
  const trySave = () => {
    if (canSave) return void doSave()
    if (save.isPending) return
    if (icNameMissing && !localError) {
      setNameAttempt((n) => n + 1)
      toast.warning('Bitte einen Namen eingeben', {
        id: 'symbole-save',
        description: 'Unter diesem Namen steht das IC-Symbol in der Bibliothek und in den Bauteilen.',
      })
      return
    }
    toast.warning('Speichern noch nicht möglich', { id: 'symbole-save', description: blockedReason ?? undefined })
  }
  const trySaveAs = () => {
    if (!request || previewError) {
      toast.warning('Speichern noch nicht möglich', { id: 'symbole-save', description: blockedReason ?? undefined })
      return
    }
    openSaveAs()
  }

  const newIc = () => {
    useGenerator.getState().loadIc(EMPTY_IC)
    setNameAttempt(0)
    chooseKind(IC_KIND)
  }

  useRegisterCommands([
    {
      id: 'symbols.save',
      title: 'Symbol in Bibliothek speichern',
      subtitle: validSpec?.name,
      group: 'Aktionen',
      icon: Save,
      hotkey: 'mod+s',
      priority: 10,
      run: trySave,
    },
    {
      id: 'symbols.saveAs',
      title: 'Symbol speichern unter …',
      subtitle: 'Unter einem neuen Namen in die Bibliothek',
      group: 'Aktionen',
      icon: SaveAll,
      hotkey: 'mod+shift+s',
      priority: 9,
      run: trySaveAs,
    },
    { id: 'symbols.copyName', title: 'Symbolnamen kopieren', group: 'Aktionen', icon: Copy, when: () => Boolean(validSpec), run: copyName },
    { id: 'symbols.newIc', title: 'IC-Symbol aus Pinliste', group: 'Aktionen', icon: Cpu, keywords: ['pinliste', 'ic'], run: () => chooseKind(IC_KIND) },
    { id: 'symbols.resetIc', title: 'Neues IC-Symbol (leere Pinliste)', group: 'Aktionen', icon: FilePlus2, keywords: ['ic', 'neu', 'leeren'], run: newIc },
    {
      id: 'symbols.altium',
      title: prefs.altium ? 'Symbol in PartForge-Darstellung zeigen' : 'Symbol wie in Altium zeigen',
      group: 'Darstellung',
      icon: Square,
      run: () => prefs.set({ altium: !prefs.altium }),
    },
  ])

  const categoryLabel = (table: string) => categories.data?.find((c) => c.table.toLowerCase() === table.toLowerCase())?.label ?? table
  const existing = libraryInfo.entry

  const kindsFailed = Boolean(kinds.error && !kinds.data)
  let editor: ReactNode
  if (!kind) {
    editor = kindsFailed ? (
      <EmptyState
        illustration="offline"
        titleAs="h2"
        title="Symboltypen nicht geladen"
        description={
          <>
            {errorMessage(kinds.error).replace(/\.?$/, '.')} Ohne die Symboltypen kann der Generator nichts erzeugen – bitte
            erneut versuchen oder das Programm neu starten.
          </>
        }
        actions={
          <Button variant="secondary" leftIcon={<RotateCcw />} loading={kinds.isFetching} onClick={() => void kinds.refetch()}>
            Erneut versuchen
          </Button>
        }
        className="h-full"
      />
    ) : (
      <div className="flex flex-col gap-4 p-5" aria-busy="true">
        <span className="sr-only">Symboltypen werden geladen …</span>
        <div className="flex items-start gap-3.5">
          <Skeleton className="h-14 w-20 rounded-button" />
          <div className="flex-1 space-y-2 pt-1">
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        </div>
        <Skeleton className="h-24 rounded-card" />
        <Skeleton className="h-40 rounded-card" />
      </div>
    )
  } else if (isIc) {
    editor = (
      <IcEditor
        spec={spec}
        valid={Boolean(validSpec)}
        fetching={fetching}
        generatorError={generatorError}
        library={libraryInfo}
        hoverDesignator={hover}
        onHover={setHover}
        part={part}
        onPartChange={setPart}
        focusRequest={focusRequest}
        onFocusRow={focusRow}
        nameAttempt={nameAttempt}
        onNewIc={() => setNameAttempt(0)}
        onShowInLibrary={onShowInLibrary}
      />
    )
  } else {
    editor = (
      <div className="h-full overflow-y-auto">
        <StandardEditor
          key={kind.key}
          kind={kind}
          values={values}
          modified={isParamModified(kind, overrides) || Boolean(extras.prefix || extras.description || extras.name || extras.pins?.length)}
          extras={extras}
          onParam={onParam}
          onExtras={(patch) => setExtras(kind.key, patch)}
          onReset={() => resetParams(kind.key)}
          spec={validSpec}
          error={previewError}
          library={libraryInfo}
          onHoverPins={setHighlight}
          categoryLabel={categoryLabel}
          onShowInLibrary={onShowInLibrary}
        />
      </div>
    )
  }

  const stage = (
    <PreviewStage
      spec={spec}
      fetching={fetching}
      error={previewError}
      warnings={warnings}
      part={part}
      onPartChange={setPart}
      highlight={highlight ?? undefined}
      hoverDesignator={hover}
      onPinHover={(p) => setHover(p?.designator ?? null)}
      onPinClick={(p) => {
        if (!isIc) return
        const row = ic.pins.find((r) => r.designator.trim() === p.designator)
        if (row) focusRow(row.id)
      }}
      empty={
        isIc ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
            <Cpu aria-hidden className="size-7 text-fg-subtle" />
            <p className="text-ui font-medium text-fg">Noch keine Vorschau</p>
            <p className="max-w-64 text-xs leading-relaxed text-fg-muted">Sobald die Pinliste Pins enthält, erscheint hier das Symbol – live bei jeder Änderung.</p>
          </div>
        ) : !kind ? (
          <div className="flex h-full flex-col items-center justify-center gap-2 px-8 text-center">
            <Shapes aria-hidden className="size-7 text-fg-subtle" />
            <p className="text-ui font-medium text-fg">{kindsFailed ? 'Keine Vorschau' : 'Symboltypen werden geladen …'}</p>
            {kindsFailed && <p className="max-w-64 text-xs leading-relaxed text-fg-muted">Die Symboltypen konnten nicht geladen werden.</p>}
          </div>
        ) : undefined
      }
    />
  )

  const saveTooltip =
    blockedReason && !icNameMissing
      ? blockedReason
      : icNameMissing
        ? 'Name fehlt – Klick springt ins Namensfeld'
        : plan?.error
          ? plan.error
          : plan?.unchanged && plan.library
            ? `Bereits aktuell in ${baseName(plan.library)}`
            : existing
              ? `Aktualisiert „${existing.name}“ in ${baseName(existing.library)}${existing.usage ? ` (${plural(existing.usage, 'Bauteil', 'Bauteile')})` : ''}`
              : plan?.library
                ? `Neu in ${baseName(plan.library)}`
                : 'Symbol registrieren und in die SchLib schreiben'
  const saveEnabled = canSave || (icNameMissing && !localError && Boolean(request) && !save.isPending)

  return (
    <>
      <PageActions>
        <IconButton label="Symbolnamen kopieren" icon={<Copy />} disabled={!validSpec} onClick={copyName} />
        <IconButton label="Speichern unter …" hotkey="mod+shift+s" icon={<SaveAll />} disabled={!request || Boolean(previewError) || save.isPending} onClick={trySaveAs} />
        <Tooltip content={saveTooltip} hotkey={saveEnabled ? 'mod+s' : undefined}>
          <span tabIndex={saveEnabled ? undefined : 0} className="rounded-control outline-none focus-ring">
            <Button
              variant="primary"
              leftIcon={<Save />}
              loading={save.isPending}
              disabled={!saveEnabled}
              aria-keyshortcuts="Control+S"
              onClick={trySave}
            >
              In Bibliothek speichern
            </Button>
          </span>
        </Tooltip>
      </PageActions>

      <SplitPane
        persistKey="symbole.typen"
        primary="start"
        defaultSize={276}
        minSize={224}
        maxSize={400}
        minRest={600}
        collapsible
        collapsed={kindsCollapsed}
        onCollapsedChange={onKindsCollapsedChange}
        label="Breite der Symboltypen-Leiste"
        className="h-full"
        startClassName="bg-bg-elev"
        start={
          <KindBrowser
            kinds={kinds.data}
            loading={kinds.isLoading}
            error={kinds.error ? errorMessage(kinds.error) : null}
            onRetry={() => void kinds.refetch()}
            value={kind?.key ?? kindKey}
            onValueChange={chooseKind}
            inLibrary={libraryNames}
          />
        }
        end={
          <SplitPane
            key={isIc ? 'ic' : 'standard'}
            persistKey={isIc ? 'symbole.ic-vorschau' : 'symbole.parameter'}
            primary={isIc ? 'end' : 'start'}
            defaultSize={isIc ? (compact ? 280 : 380) : compact ? 340 : 372}
            minSize={isIc ? 260 : 320}
            maxSize={isIc ? 760 : 560}
            minRest={isIc ? 500 : 300}
            label={isIc ? 'Breite der Vorschau' : 'Breite des Parameter-Bereichs'}
            className="h-full"
            startClassName="bg-surface/40"
            start={editor}
            end={stage}
          />
        }
      />

      <SaveAsDialog
        open={saveAs.open}
        onOpenChange={(open) => setSaveAs((s) => ({ ...s, open }))}
        initialName={saveAs.initial}
        currentName={currentName}
        entries={entries}
        origin={origin}
        planFor={
          validSpec
            ? (name, signal) =>
                symbolsApi.save(
                  {
                    spec: { ...validSpec, name },
                    category: saveCategory,
                    source: 'generated',
                    allow_pinout_change: false,
                    library: targetLibrary(name),
                  },
                  { dryRun: true, signal },
                )
            : undefined
        }
        onSubmit={(name) => {
          setSaveAs((s) => ({ ...s, open: false }))
          void doSave({ name })
        }}
      />
      <SaveConflictDialog
        conflict={conflict}
        onChoice={(choice) => {
          conflict?.resolve(choice)
          setConflict(null)
        }}
      />
    </>
  )
}
