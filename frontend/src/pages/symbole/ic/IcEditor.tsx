import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * IC-Editor: Eigenschaften (Name, Präfix, Beschreibung, Teile, Sortierung), Pinliste als Tabelle oder als
 * Seiten-Editor (Drag & Drop), Einfügen aus der Zwischenablage, Seiten automatisch anordnen bzw. festlegen
 * (Backend), Rückgängig/Wiederholen (auch mit dem Fokus in einer Zelle) und Prüfmeldungen. Der Entwurf liegt im
 * Generator-Store (bleibt beim Seitenwechsel erhalten).
 */
import {
  ChevronDown,
  CircleAlert,
  ClipboardCopy,
  ClipboardPaste,
  Columns3,
  Ellipsis,
  FilePlus2,
  FlaskConical,
  Info,
  ListOrdered,
  Pin,
  Plus,
  Redo2,
  Rows3,
  Trash2,
  TriangleAlert,
  Undo2,
  Wand,
} from 'lucide-react'
import { useCallback, useEffect, useId, useRef, useState, type ClipboardEvent, type ReactNode } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { symbolsApi, type GeneratedSpec, type IcSide } from '@/api/symbols'
import {
  Badge,
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  Field,
  IconButton,
  Input,
  NumberInput,
  SegmentedControl,
  Select,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tooltip,
} from '@/components/ui'
import { useElementSize } from '@/components/preview'
import { cn } from '@/lib/cn'
import { baseName, formatNumber, plural } from '@/lib/format'
import { isEditableTarget, useHotkey } from '@/lib/hotkeys'
import { EMPTY_IC, useGenerator, useSymbolUiPrefs, type IcDraft, type IcOrder, type PartsMode, type PinColumn } from '../store'
import { LabeledGroup } from '../shared'
import { copyText, prefixError, SIDE_OF_ORIENTATION, symbolNameError } from '../util'
import type { LibraryInfo } from '../generator/NameResult'
import { PasteDialog } from './PasteDialog'
import { PinTable } from './PinTable'
import {
  ELECTRICAL_OPTIONS,
  fromIcPin,
  makePin,
  newPinId,
  nextDesignator,
  parsePinTable,
  SIDE_LABEL,
  sortByDesignator,
  toIcPin,
  validatePins,
  type PinIssue,
  type PinRow,
} from './pins'
import { SideLayout } from './SideLayout'

export interface IcEditorProps {
  /** Letzte Vorschau (bleibt bei Fehlern stehen) */
  spec: GeneratedSpec | undefined
  /** Die Vorschau passt zum aktuellen Stand (sonst keine Bibliotheks-Angaben am Namen) */
  valid: boolean
  fetching: boolean
  /** Fehler des Generators (Backend) – lokale Prüfungen zeigt der Editor selbst */
  generatorError: string | null
  library: LibraryInfo
  hoverDesignator: string | null
  onHover: (designator: string | null) => void
  part: number
  onPartChange: (part: number) => void
  focusRequest: { id: string; nonce: number } | null
  onFocusRow: (id: string) => void
  /** Speichern ohne Namen versucht (Zähler): Eigenschaften aufklappen, Namensfeld fokussieren, Fehler zeigen */
  nameAttempt: number
  /** Neuer, leerer Entwurf („Neues IC-Symbol“) – setzt die Namensprüfung zurück */
  onNewIc: () => void
  /** Symbol in der Bibliotheksansicht öffnen */
  onShowInLibrary: (name: string) => void
}

const ROLE_GROUPS = ['Versorgung', 'Masse', 'Eingänge', 'Ausgänge', 'Schaltknoten', 'Signale', 'Nicht verbunden', 'Thermal-Pad']
const COLUMN_LABEL: Record<PinColumn, string> = { group: 'Gruppe', part: 'Teil', hidden: 'Verborgen', description: 'Beschreibung' }
/** Unter dieser Höhe des Editors klappen die Eigenschaften automatisch ein (Fenster ≈ 760 px) */
const PROPS_AUTO_COLLAPSE_BELOW = 680

/** Beispiel: kleiner Abwärtswandler (zeigt Versorgung links, Masse unten, SW/BOOT oben, FB/PG rechts) */
const EXAMPLE: { name: string; pins: [string, string, PinRow['electrical']][] } = {
  name: 'Buck-Regler Beispiel',
  pins: [
    ['1', 'VIN', 'power'],
    ['2', 'EN', 'input'],
    ['3', 'SS', 'passive'],
    ['4', 'RT', 'passive'],
    ['5', 'FB', 'input'],
    ['6', 'PG', 'open_collector'],
    ['7', 'AGND', 'power'],
    ['8', 'PGND', 'power'],
    ['9', 'SW', 'output'],
    ['10', 'BOOT', 'input'],
  ],
}

function toTsv(pins: readonly PinRow[]): string {
  const head = [tr('Nr'), tr('Name'), tr('Typ'), tr('Seite'), tr('Gruppe'), tr('Teil'), tr('Verborgen'), tr('Beschreibung')].join('\t')
  const rows = pins.map((p) =>
    [
      p.designator,
      p.name,
      ELECTRICAL_OPTIONS.find((o) => o.value === p.electrical)?.label.replace(' / Drain', '').replace(' / Source', '') ?? p.electrical,
      p.side ? tr(SIDE_LABEL[p.side]) : tr('Automatisch'),
      p.group,
      String(p.part),
      p.hidden ? tr('ja') : '',
      p.description,
    ].join('\t'),
  )
  return [head, ...rows].join('\n')
}

function IssueIcon({ level }: { level: PinIssue['level'] }) {
  if (level === 'error') return <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger-text" />
  if (level === 'warning') return <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning-text" />
  return <Info aria-hidden className="mt-0.5 size-3.5 shrink-0 text-info-text" />
}

const modalOpen = () => document.querySelector('[aria-modal="true"]') !== null

export function IcEditor({
  spec,
  valid,
  fetching,
  generatorError,
  library,
  hoverDesignator,
  onHover,
  part,
  onPartChange,
  focusRequest,
  onFocusRow,
  nameAttempt,
  onNewIc,
  onShowInLibrary,
}: IcEditorProps) {
  useI18n()
  const uid = useId().replace(/:/g, '')
  const ic = useGenerator((s) => s.ic)
  const updateIc = useGenerator((s) => s.updateIc)
  const undo = useGenerator((s) => s.undo)
  const redo = useGenerator((s) => s.redo)
  const canUndo = useGenerator((s) => s.past.length > 0)
  const canRedo = useGenerator((s) => s.future.length > 0)
  const prefs = useSymbolUiPrefs()
  const [rootRef, rootSize, rootEl] = useElementSize<HTMLDivElement>()
  const tableScrollRef = useRef<HTMLDivElement>(null)
  const nameRef = useRef<HTMLInputElement>(null)

  // optionale Spalten automatisch nur bei genug Breite (ausdrückliche Wahl im Menü hat Vorrang). Stabil halten:
  // ein neues Objekt je Render ließe jede (memoisierte) Tabellenzeile bei jedem Tastendruck neu zeichnen.
  const roomy = rootSize.width === 0 || rootSize.width >= 720
  const colPrefs = prefs.columns
  const columns = useLocalizedMemo<Record<PinColumn, boolean>>(
    () => ({
      group: colPrefs.group ?? roomy,
      part: colPrefs.part ?? roomy,
      hidden: colPrefs.hidden ?? roomy,
      description: colPrefs.description ?? false,
    }),
    [colPrefs, roomy],
  )

  // Eigenschaften: ausdrücklich ein-/ausgeklappt oder automatisch (niedrige Fenster → eingeklappt)
  const [forceOpen, setForceOpen] = useState(false)
  const autoCollapsed = rootSize.height > 0 && rootSize.height < PROPS_AUTO_COLLAPSE_BELOW
  const propsCollapsed = !forceOpen && (prefs.icPropsCollapsed ?? autoCollapsed)
  const toggleProps = () => {
    setForceOpen(false)
    prefs.set({ icPropsCollapsed: !propsCollapsed })
  }

  const [paste, setPaste] = useState<{ open: boolean; text?: string }>({ open: false })
  const [arranging, setArranging] = useState(false)
  const [issuesOpen, setIssuesOpen] = useState(false)

  // Speichern ohne Namen: Eigenschaften zeigen und ins Namensfeld springen
  const [handledAttempt, setHandledAttempt] = useState(nameAttempt)
  if (nameAttempt !== handledAttempt) {
    setHandledAttempt(nameAttempt)
    if (propsCollapsed) setForceOpen(true)
  }
  useEffect(() => {
    if (nameAttempt > 0) requestAnimationFrame(() => nameRef.current?.focus())
  }, [nameAttempt])
  const nameMissing = nameAttempt > 0 && !ic.name.trim()

  const set = useCallback((patch: Partial<IcDraft>, key?: string) => updateIc((d) => ({ ...d, ...patch }), key), [updateIc])

  // ------------------------------------------------------------------ Pin-Operationen (stabil für die Tabelle)
  const onChange = useCallback(
    (id: string, patch: Partial<PinRow>, key?: string) =>
      updateIc((d) => ({ ...d, pins: d.pins.map((p) => (p.id === id ? { ...p, ...patch } : p)) }), key),
    [updateIc],
  )
  const onRemove = useCallback((id: string) => updateIc((d) => ({ ...d, pins: d.pins.filter((p) => p.id !== id) })), [updateIc])
  const onDuplicate = useCallback(
    (id: string) =>
      updateIc((d) => {
        const i = d.pins.findIndex((p) => p.id === id)
        if (i < 0) return d
        const src = d.pins[i]
        const copy: PinRow = { ...src, id: newPinId(), designator: nextDesignator(d.pins, src.designator) }
        return { ...d, pins: [...d.pins.slice(0, i + 1), copy, ...d.pins.slice(i + 1)] }
      }),
    [updateIc],
  )
  const onAdd = useCallback(
    (afterId?: string) => {
      const pins = useGenerator.getState().ic.pins
      const i = afterId ? pins.findIndex((p) => p.id === afterId) : pins.length - 1
      const after = i >= 0 ? pins[i] : undefined
      const pin = makePin(nextDesignator(pins, after?.designator), { part: after?.part ?? 1, group: after?.group ?? '' })
      updateIc((d) => ({ ...d, pins: [...d.pins.slice(0, i + 1), pin, ...d.pins.slice(i + 1)] }))
      return pin.id
    },
    [updateIc],
  )
  const onMove = useCallback(
    (id: string, delta: number) =>
      updateIc((d) => {
        const i = d.pins.findIndex((p) => p.id === id)
        const j = i + delta
        if (i < 0 || j < 0 || j >= d.pins.length) return d
        const pins = [...d.pins]
        ;[pins[i], pins[j]] = [pins[j], pins[i]]
        return { ...d, pins }
      }),
    [updateIc],
  )
  const onReorder = useCallback(
    (id: string, beforeId: string | null) =>
      updateIc((d) => {
        const moving = d.pins.find((p) => p.id === id)
        if (!moving) return d
        const rest = d.pins.filter((p) => p.id !== id)
        const at = beforeId ? rest.findIndex((p) => p.id === beforeId) : rest.length
        return { ...d, pins: [...rest.slice(0, at < 0 ? rest.length : at), moving, ...rest.slice(at < 0 ? rest.length : at)] }
      }),
    [updateIc],
  )
  const onSetSide = useCallback(
    (ids: string[], side: IcSide | null) =>
      updateIc((d) => ({ ...d, pins: d.pins.map((p) => (ids.includes(p.id) ? { ...p, side } : p)) })),
    [updateIc],
  )
  /**
   * Seiten-Editor: Pin vor/hinter einen anderen derselben Seite setzen. Die Reihenfolge innerhalb einer Gruppe
   * folgt dann der Pinliste (Sortierung „Wie in der Liste“); beim Umstellen wird die Liste zuerst in die
   * Reihenfolge des Symbols gebracht, damit sich außer dem verschobenen Pin nichts bewegt.
   */
  const onPlace = useCallback(
    (id: string, targetId: string, where: 'before' | 'after', side: IcSide) => {
      const switchOrder = useGenerator.getState().ic.order !== 'input'
      updateIc((d) => {
        if (!d.pins.some((p) => p.id === id) || id === targetId) return d
        let list = d.pins
        if (d.order !== 'input' && spec) {
          const bySpec = new Map(spec.pins.map((p) => [p.designator, p]))
          const sideRank = { left: 0, right: 1, up: 2, down: 3 } as const
          const keyOf = (row: PinRow): [number, number, number] => {
            const sp = bySpec.get(row.designator.trim())
            if (!sp || sp.hidden) return [Number.MAX_SAFE_INTEGER, 0, 0]
            const along = sp.orientation === 'left' || sp.orientation === 'right' ? -sp.y : sp.x
            return [sp.part ?? 1, sideRank[sp.orientation], along]
          }
          list = list
            .map((row, i) => ({ row, i, k: keyOf(row) }))
            .sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.k[2] - b.k[2] || a.i - b.i)
            .map((x) => x.row)
        }
        const moving = list.find((p) => p.id === id) as PinRow
        const rest = list.filter((p) => p.id !== id)
        const target = rest.findIndex((p) => p.id === targetId)
        const at = target < 0 ? rest.length : where === 'before' ? target : target + 1
        return { ...d, order: 'input', pins: [...rest.slice(0, at), { ...moving, side }, ...rest.slice(at)] }
      })
      if (switchOrder) {
        toast.info(tr('Sortierung: Wie in der Liste'), {
          id: 'symbole-order',
          description: tr('Die Reihenfolge auf den Seiten folgt jetzt der Pinliste – sie wurde dafür in die Reihenfolge des Symbols gebracht.'),
          action: { label: tr('Rückgängig'), onClick: () => useGenerator.getState().undo() },
        })
      }
    },
    [updateIc, spec],
  )

  const applyPaste = (rows: PinRow[], mode: 'replace' | 'append') => {
    updateIc((d) => ({ ...d, pins: mode === 'replace' ? rows : [...d.pins, ...rows] }))
    toast.success(`${plural(rows.length, tr('Pin'), tr('Pins'))} ${mode === 'replace' ? tr('übernommen') : tr('angehängt')}`, {
      id: 'symbole-paste',
      action: { label: tr('Rückgängig'), onClick: () => useGenerator.getState().undo() },
    })
  }

  // ------------------------------------------------------------------ Seiten anordnen
  const explicitCount = ic.pins.filter((p) => p.side !== null).length
  const openCount = ic.pins.length - explicitCount

  /** Aktuelle automatische Seiten fest übernehmen (neue Pins verschieben die Anordnung dann nicht mehr) */
  const fixSides = async () => {
    const pins = useGenerator.getState().ic.pins
    if (!pins.some((p) => p.side === null)) return
    setArranging(true)
    try {
      const out = await symbolsApi.autoSides(pins.map(toIcPin), false)
      const sides = out.pins.map((p) => p.side ?? null)
      let fixed = 0
      updateIc((d) => ({
        ...d,
        pins: d.pins.map((p, i) => {
          if (p.side !== null || i >= sides.length || !sides[i]) return p
          fixed += 1
          return { ...p, side: sides[i] }
        }),
      }))
      const counts = { left: 0, right: 0, top: 0, bottom: 0 }
      for (const s of sides) if (s) counts[s] += 1
      toast.success(tr("{value0} festgelegt", { value0: String(plural(fixed, tr('Seite'), tr('Seiten'))) }), {
        id: 'symbole-arrange',
        description: tr("Die Anordnung bleibt jetzt auch bei neuen Pins erhalten: {value0} links · {value1} rechts · {value2} oben · {value3} unten.", { value0: String(counts.left), value1: String(counts.right), value2: String(counts.top), value3: String(counts.bottom) }),
        action: { label: tr('Rückgängig'), onClick: () => useGenerator.getState().undo() },
      })
    } catch (error) {
      toast.error(tr('Seiten festlegen fehlgeschlagen'), { id: 'symbole-arrange', description: errorMessage(error) })
    } finally {
      setArranging(false)
    }
  }

  /** Alle festgelegten Seiten freigeben – der Generator ordnet wieder selbst an */
  const releaseSides = () => {
    const count = useGenerator.getState().ic.pins.filter((p) => p.side !== null).length
    if (!count) return
    updateIc((d) => ({ ...d, pins: d.pins.map((p) => (p.side ? { ...p, side: null } : p)) }))
    toast.success(tr('Automatisch angeordnet'), {
      id: 'symbole-arrange',
      description: tr("{value0} freigegeben – der Generator verteilt alle Pins neu.", { value0: String(plural(count, tr('festgelegte Seite'), tr('festgelegte Seiten'))) }),
      action: { label: tr('Rückgängig'), onClick: () => useGenerator.getState().undo() },
    })
  }

  const clearAll = async () => {
    const ok = await confirm({
      title: tr('Alle Pins entfernen?'),
      description: tr("{value0} aus dem Entwurf gelöscht. Mit Rückgängig (Strg+Z) lässt sich das zurückholen.", { value0: String(plural(ic.pins.length, tr('Pin wird'), tr('Pins werden'))) }),
      confirmLabel: tr('Alle entfernen'),
      destructive: true,
    })
    if (ok) updateIc((d) => ({ ...d, pins: [] }))
  }

  const newIc = () => {
    useGenerator.getState().loadIc(EMPTY_IC)
    onNewIc()
    toast(tr('Neues IC-Symbol'), {
      id: 'symbole-new-ic',
      description: tr('Der bisherige Entwurf lässt sich mit Rückgängig zurückholen.'),
      action: { label: tr('Rückgängig'), onClick: () => useGenerator.getState().undo() },
    })
    requestAnimationFrame(() => nameRef.current?.focus())
  }

  const loadExample = () => {
    useGenerator.getState().loadIc({
      ...ic,
      name: EXAMPLE.name,
      pins: EXAMPLE.pins.map(([d, n, e]) => fromIcPin({ designator: d, name: n, electrical: e })),
    })
  }

  // ------------------------------------------------------------------ Tastatur & Einfügen
  // Rückgängig/Wiederholen gilt auch in den Zellen und Feldern des Editors (sie zeigen den Store-Stand) –
  // nicht in anderen Eingabefeldern der Seite und nicht hinter einem offenen Dialog
  const history = (e: KeyboardEvent, action: () => void) => {
    if (modalOpen()) return
    if (isEditableTarget(e.target) && !(e.target instanceof Node && rootEl?.contains(e.target))) return
    e.preventDefault()
    action()
  }
  useHotkey('mod+z', (e) => history(e, undo), { allowInInputs: true, preventDefault: false })
  useHotkey(['mod+shift+z', 'mod+y'], (e) => history(e, redo), { allowInInputs: true, preventDefault: false })

  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    // Ereignisse aus Portalen (Dialoge) laufen im React-Baum hierher – nur echte Nachfahren behandeln
    if (!e.currentTarget.contains(e.target as Node)) return
    const text = e.clipboardData.getData('text/plain')
    if (!text) return
    const multi = /[\t\n]/.test(text.trim())
    if (multi || !isEditableTarget(e.target)) {
      if (parsePinTable(text).pins.length === 0 && !multi) return
      e.preventDefault()
      setPaste({ open: true, text })
    }
  }

  // ------------------------------------------------------------------ abgeleitete Daten
  const validation = useLocalizedMemo(() => validatePins(ic.pins, { partsMode: ic.partsMode }), [ic.pins, ic.partsMode])
  const effectiveSide = useLocalizedMemo(() => {
    const bySpec = new Map((spec?.pins ?? []).map((p) => [p.designator, p]))
    const map = new Map<string, IcSide>()
    for (const row of ic.pins) {
      const sp = bySpec.get(row.designator.trim())
      if (sp) map.set(row.id, SIDE_OF_ORIENTATION[sp.orientation])
    }
    return map
  }, [ic.pins, spec])
  // Teile verteilt der Generator nur, wenn die Pinliste selbst keine Teile festlegt
  const userParts = ic.pins.some((p) => p.part !== 1)
  const autoParts = useLocalizedMemo(() => {
    if (ic.partsMode === '1' || userParts) return null
    const bySpec = new Map((spec?.pins ?? []).map((p) => [p.designator, p.part]))
    const map = new Map<string, number>()
    for (const row of ic.pins) {
      const part = bySpec.get(row.designator.trim())
      if (part !== undefined) map.set(row.id, part)
    }
    return map
  }, [ic.partsMode, ic.pins, spec, userParts])
  const groupSuggestions = useLocalizedMemo(
    () => [...new Set([...ic.pins.map((p) => p.group.trim()).filter(Boolean), ...ROLE_GROUPS])],
    [ic.pins],
  )
  const sideWarnings: PinIssue[] = useLocalizedMemo(() => {
    if (!spec || ic.partsMode !== '1') return []
    const counts: Record<IcSide, number> = { left: 0, right: 0, top: 0, bottom: 0 }
    for (const p of spec.pins) if (p.part === 1 || p.part === 0) counts[SIDE_OF_ORIENTATION[p.orientation]] += 1
    return (Object.keys(counts) as IcSide[])
      .filter((s) => counts[s] > ic.maxPinsPerSide)
      .map((s) => ({
        level: 'warning' as const,
        message: tr("{value0} {value1} Pins – mehr als {value2} je Seite. Mit „Teile: Automatisch“ aufteilen.", { value0: String(tr(SIDE_LABEL[s])), value1: String(counts[s]), value2: String(ic.maxPinsPerSide) }),
      }))
  }, [spec, ic.partsMode, ic.maxPinsPerSide])
  const issues = [...validation.issues.filter((i) => i.level === 'error'), ...sideWarnings, ...validation.issues.filter((i) => i.level !== 'error')]
  const errorCount = validation.errorCount
  const warnCount = issues.filter((i) => i.level === 'warning').length
  const nameProblem = symbolNameError(ic.name) ?? (nameMissing ? tr('Bitte einen Namen eingeben – unter ihm steht das Symbol in der Bibliothek.') : undefined)
  const prefixProblem = prefixError(ic.prefix)

  const entry = library.entry
  const plan = library.plan
  const libraryHint: ReactNode = !library.available || !valid ? undefined : plan?.error ? (
    <span className="text-danger-text" title={plan.error ? localizeMessage(plan.error) : undefined}>
      {tr("nicht speicherbar")}
    </span>
  ) : entry ? (
    <button
      type="button"
      title={tr("{value0} – in der Bibliothek zeigen", { value0: String(entry.library) })}
      onClick={() => onShowInLibrary(entry.name)}
      className={cn(
        'rounded-sm underline-offset-2 outline-none hover:underline focus-ring',
        plan?.changes.length ? 'text-warning-text' : 'text-success-text',
      )}
    >
      {plan?.changes.length ? tr('Pinbelegung ändert sich · ') : plan?.unchanged ? tr('aktuell · ') : ''}{tr("in")}{' '}{baseName(entry.library)}
      {entry.usage ? ` · ${plural(entry.usage, tr('Bauteil'), tr('Bauteile'))}` : ''}
    </button>
  ) : (
    <span className="text-accent-text" title={plan?.library ?? undefined}>
      {tr("neu")}{plan?.library ? ` · ${baseName(plan.library)}` : ''}
    </span>
  )

  const summary = [
    ic.name.trim() || tr('ohne Namen'),
    ic.prefix.trim() || 'U',
    ic.partsMode === '1' ? tr('1 Teil') : ic.partsMode === 'auto' ? tr('Teile automatisch') : tr("{value0} Teile", { value0: String(ic.partCount) }),
    ic.order === 'name' ? tr('nach Name') : ic.order === 'designator' ? tr('nach Nummer') : tr('wie eingegeben'),
  ].join(' · ')

  const empty = ic.pins.length === 0
  const emptyState = (
    <EmptyState
      icon={<Rows3 />}
      title={tr("Noch keine Pins")}
      description={tr("Pin-Tabelle aus dem Datenblatt oder aus Excel kopieren und einfügen – Nummer, Name und Typ werden erkannt. Oder Pins einzeln anlegen.")}
      actions={
        <>
          <Button variant="secondary" leftIcon={<ClipboardPaste />} onClick={() => setPaste({ open: true })}>
            {tr("Pinliste einfügen …")}
          </Button>
          <Button variant="ghost" leftIcon={<Plus />} onClick={() => onFocusRow(onAdd())}>
            {tr("Pin hinzufügen")}
          </Button>
          <Button variant="ghost" leftIcon={<FlaskConical />} onClick={loadExample}>
            {tr("Beispiel laden")}
          </Button>
        </>
      }
      className="h-full"
    />
  )

  // Hauptknopf „Anordnen“: mit festgelegten Seiten → wieder automatisch, sonst → aktuelle Anordnung festlegen
  const arrangeMain =
    explicitCount > 0
      ? { label: tr('Automatisch anordnen'), short: tr('Automatisch'), icon: <Wand />, run: releaseSides, hint: tr("{value0} freigeben – der Generator verteilt alle Pins", { value0: String(plural(explicitCount, tr('festgelegte Seite'), tr('festgelegte Seiten'))) }) }
      : { label: tr('Seiten festlegen'), short: tr('Festlegen'), icon: <Pin />, run: () => void fixSides(), hint: tr('Aktuelle automatische Anordnung fest übernehmen – neue Pins verschieben sie nicht mehr') }

  const footerMessage = issues[0]?.message ?? (generatorError ? generatorError : plural(ic.pins.length, tr('Pin'), tr('Pins')))

  return (
    <div ref={rootRef} className="@container flex h-full min-h-0 flex-col" onPaste={onPaste}>
      {/* ------------------------------------------------------------ Eigenschaften */}
      <section aria-labelledby={`${uid}-props`} className="shrink-0 border-b border-line">
        <div className="flex h-11 items-center gap-2 px-4">
          <h2 id={`${uid}-props`} className="flex min-w-0 shrink-0 text-xs font-semibold text-fg">
            <button
              type="button"
              aria-expanded={!propsCollapsed}
              aria-controls={`${uid}-props-body`}
              onClick={toggleProps}
              className="-ml-1 flex items-center gap-1.5 rounded-control px-1 py-0.5 outline-none focus-ring"
            >
              <ChevronDown aria-hidden className={cn('size-3.5 shrink-0 text-fg-subtle transition-transform duration-200', propsCollapsed && '-rotate-90')} />
              {tr("IC-Eigenschaften")}
            </button>
          </h2>
          {propsCollapsed && (
            <span className={cn('mono min-w-0 flex-1 truncate text-2xs', ic.name.trim() ? 'text-fg-subtle' : 'text-warning-text')}>{summary}</span>
          )}
        </div>
        <div id={`${uid}-props-body`} hidden={propsCollapsed} className="@container px-4 pb-4">
          <div className="grid grid-cols-[minmax(0,1fr)_6.5rem] gap-x-3 gap-y-3 @[38rem]:grid-cols-[minmax(0,1.3fr)_6.5rem_minmax(0,1.2fr)]">
            <Field label={tr("Name")} required error={nameProblem} hint={nameProblem ? undefined : libraryHint}>
              <Input
                ref={nameRef}
                mono
                value={ic.name}
                placeholder={tr("z. B. TPS54331")}
                maxLength={64}
                onChange={(e) => set({ name: e.target.value }, 'name')}
              />
            </Field>
            <Field label={tr("Präfix")} error={prefixProblem}>
              <Input mono value={ic.prefix} placeholder="U" maxLength={10} onChange={(e) => set({ prefix: e.target.value.replace(/\s/g, '') }, 'prefix')} />
            </Field>
            <Field label={tr("Beschreibung")} className="col-span-2 @[38rem]:col-span-1">
              <Input value={ic.description} placeholder={tr("z. B. Buck-Regler 3 A, 28 V")} onChange={(e) => set({ description: e.target.value }, 'description')} />
            </Field>
          </div>
          <div className="mt-3 flex flex-wrap items-start gap-x-2.5 gap-y-3">
            <LabeledGroup label={tr("Teile")}>
              <div className="flex items-center gap-2">
                <SegmentedControl
                  size="sm"
                  aria-label={tr("Teile")}
                  value={ic.partsMode}
                  onValueChange={(v: PartsMode) => set({ partsMode: v })}
                  options={[
                    { value: '1', label: tr('Ein Teil') },
                    { value: 'auto', label: tr('Automatisch') },
                    { value: 'fixed', label: tr('Anzahl') },
                  ]}
                />
                {ic.partsMode === 'fixed' && (
                  <NumberInput
                    size="sm"
                    aria-label={tr("Anzahl der Teile")}
                    value={ic.partCount}
                    onValueChange={(v) => set({ partCount: Math.max(2, Math.round(v ?? 2)) })}
                    min={2}
                    max={64}
                    decimals={0}
                    containerClassName="w-16"
                  />
                )}
              </div>
            </LabeledGroup>
            <Field label={tr("Sortierung")} className="w-36">
              <Select<IcOrder>
                size="sm"
                value={ic.order}
                onValueChange={(v) => set({ order: v })}
                options={[
                  { value: 'name', label: tr('Nach Pinname') },
                  { value: 'designator', label: tr('Nach Pin-Nummer') },
                  { value: 'input', label: tr('Wie in der Liste') },
                ]}
              />
            </Field>
            {ic.partsMode === 'auto' && (
              <Field label={tr("Pins je Seite")} hint={tr("max.")} className="w-32">
                <NumberInput
                  size="sm"
                  value={ic.maxPinsPerSide}
                  onValueChange={(v) => set({ maxPinsPerSide: Math.round(v ?? 40) })}
                  min={4}
                  max={500}
                  decimals={0}
                />
              </Field>
            )}
          </div>
          {ic.partsMode !== '1' && (
            <p className={cn('mt-2 text-xs leading-snug', userParts ? 'text-warning-text' : 'text-fg-muted')}>
              {userParts
                ? ic.partsMode === 'fixed'
                  ? tr('Die Spalte „Teil“ legt die Teile schon fest – eine feste Anzahl geht nur, wenn alle Pins Teil 1 haben.')
                  : tr('Die Spalte „Teil“ legt die Teile schon fest – die automatische Aufteilung entfällt.')
                : tr('Der Generator verteilt die Pins; Versorgung und Masse kommen in eigene Teile.')}
            </p>
          )}
        </div>
      </section>

      {/* ------------------------------------------------------------ Reiter + Werkzeuge */}
      <Tabs
        value={prefs.icTab}
        onValueChange={(v) => prefs.set({ icTab: v as 'pins' | 'sides' })}
        className="min-h-0 flex-1"
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-line pl-2 pr-3">
          <TabsList aria-label={tr("Pin-Editor")} className="border-b-0">
            <TabsTrigger value="pins" icon={<Rows3 />} count={formatNumber(ic.pins.length)}>
              {tr("Pinliste")}
            </TabsTrigger>
            <TabsTrigger value="sides" icon={<Columns3 />}>
              {tr("Seiten")}
            </TabsTrigger>
          </TabsList>
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <Button size="sm" variant="ghost" leftIcon={<ClipboardPaste />} onClick={() => setPaste({ open: true })} className="hidden @[44rem]:inline-flex">
              {tr("Einfügen …")}
            </Button>
            <div className="flex items-center">
              <Tooltip content={arrangeMain.hint}>
                <Button
                  size="sm"
                  variant="secondary"
                  leftIcon={arrangeMain.icon}
                  loading={arranging}
                  disabled={empty}
                  onClick={arrangeMain.run}
                  className="rounded-r-none"
                >
                  <span className="hidden @[40rem]:inline">{tr(arrangeMain.label)}</span>
                  <span className="@[40rem]:hidden">{arrangeMain.short}</span>
                </Button>
              </Tooltip>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="sm" variant="secondary" iconOnly aria-label={tr("Weitere Optionen zum Anordnen")} disabled={empty} className="-ml-px rounded-l-none">
                    <ChevronDown />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-80">
                  <DropdownMenuItem
                    icon={<Wand />}
                    disabled={explicitCount === 0}
                    description={explicitCount ? tr("{value0} freigeben", { value0: String(plural(explicitCount, tr('festgelegte Seite'), tr('festgelegte Seiten'))) }) : tr('Alle Seiten sind bereits automatisch')}
                    onSelect={releaseSides}
                  >
                    {tr("Automatisch anordnen")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    icon={<Pin />}
                    disabled={openCount === 0}
                    description={openCount ? tr("{value0} fest übernehmen", { value0: String(plural(openCount, tr('automatische Seite'), tr('automatische Seiten'))) }) : tr('Alle Seiten sind festgelegt')}
                    onSelect={() => void fixSides()}
                  >
                    {tr("Seiten festlegen")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <span aria-hidden className="mx-0.5 h-4 w-px bg-line-strong" />
            <IconButton size="sm" label={tr("Rückgängig")} hotkey="mod+z" icon={<Undo2 />} disabled={!canUndo} onClick={undo} />
            <IconButton size="sm" label={tr("Wiederholen")} hotkey="mod+shift+z" icon={<Redo2 />} disabled={!canRedo} onClick={redo} />
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" variant="ghost" iconOnly aria-label={tr("Weitere Aktionen")}>
                  <Ellipsis />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-64">
                <DropdownMenuItem icon={<Plus />} onSelect={() => onFocusRow(onAdd())}>
                  {tr("Pin hinzufügen")}
                </DropdownMenuItem>
                <DropdownMenuItem icon={<ClipboardPaste />} onSelect={() => setPaste({ open: true })}>
                  {tr("Pinliste einfügen …")}
                </DropdownMenuItem>
                <DropdownMenuItem icon={<ClipboardCopy />} disabled={empty} onSelect={() => void copyText(toTsv(ic.pins), tr('Pinliste'))}>
                  {tr("Pinliste kopieren (Tabelle)")}
                </DropdownMenuItem>
                <DropdownMenuItem icon={<ListOrdered />} disabled={empty} onSelect={() => updateIc((d) => ({ ...d, pins: sortByDesignator(d.pins) }))}>
                  {tr("Nach Pin-Nummer sortieren")}
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>{tr("Spalten der Pinliste")}</DropdownMenuLabel>
                {(Object.keys(COLUMN_LABEL) as PinColumn[]).map((c) => (
                  <DropdownMenuCheckboxItem
                    key={c}
                    checked={columns[c]}
                    onCheckedChange={(on) => prefs.set({ columns: { ...prefs.columns, [c]: on === true } })}
                    onSelect={(e) => e.preventDefault()}
                  >
                    {tr(COLUMN_LABEL[c])}
                  </DropdownMenuCheckboxItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem icon={<FilePlus2 />} onSelect={newIc}>
                  {tr("Neues IC-Symbol")}
                </DropdownMenuItem>
                <DropdownMenuItem icon={<FlaskConical />} onSelect={loadExample}>
                  {tr("Beispiel laden")}
                </DropdownMenuItem>
                <DropdownMenuItem icon={<Trash2 />} destructive disabled={empty} onSelect={() => void clearAll()}>
                  {tr("Alle Pins entfernen")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* ------------------------------------------------------------ Inhalt */}
        <TabsContent ref={tableScrollRef} value="pins" className="relative min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
          {empty ? (
            emptyState
          ) : (
            <div className="pb-3">
              <PinTable
                pins={ic.pins}
                errors={validation.byRow}
                columns={columns}
                effectiveSide={effectiveSide}
                autoParts={autoParts}
                hoverDesignator={hoverDesignator}
                onHover={onHover}
                focusRequest={focusRequest}
                groupSuggestions={groupSuggestions}
                scrollRef={tableScrollRef}
                onChange={onChange}
                onRemove={onRemove}
                onDuplicate={onDuplicate}
                onAdd={onAdd}
                onMove={onMove}
                onReorder={onReorder}
              />
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 pt-2">
                <Button size="sm" variant="ghost" leftIcon={<Plus />} onClick={() => onFocusRow(onAdd())}>
                  {tr("Pin hinzufügen")}
                </Button>
                <span className="text-2xs text-fg-subtle">
                  {tr("Enter in der letzten Zeile: neuer Pin · Strg+D dupliziert · Strg+Entf löscht · Strg+V fügt ein")}
                </span>
              </div>
            </div>
          )}
        </TabsContent>
        <TabsContent value="sides" className="relative min-h-0 flex-1 overflow-auto data-[state=inactive]:hidden">
          {empty ? (
            emptyState
          ) : (
            <SideLayout
              pins={ic.pins}
              spec={spec}
              part={part}
              onPartChange={onPartChange}
              hoverDesignator={hoverDesignator}
              onHover={onHover}
              onSetSide={onSetSide}
              onPlace={onPlace}
              onShowInTable={onFocusRow}
              stale={fetching}
            />
          )}
        </TabsContent>
      </Tabs>

      {/* ------------------------------------------------------------ Prüfmeldungen */}
      {!empty && (
        <div className="shrink-0 border-t border-line">
          <button
            type="button"
            aria-expanded={issues.length ? issuesOpen : undefined}
            aria-controls={issues.length ? `${uid}-issues` : undefined}
            disabled={issues.length === 0}
            onClick={() => setIssuesOpen((v) => !v)}
            className="flex h-9 w-full items-center gap-2.5 px-4 text-left text-xs outline-none transition-colors focus-ring-inset enabled:hover:bg-surface-2/60"
          >
            {errorCount > 0 ? (
              <Badge variant="danger" dot>
                {plural(errorCount, tr('Fehler'), tr('Fehler'))}
              </Badge>
            ) : generatorError ? (
              <Badge variant="danger" dot>
                {tr("Generator-Fehler")}
              </Badge>
            ) : (
              <Badge variant="success" dot>
                {tr("Pinliste gültig")}
              </Badge>
            )}
            {warnCount > 0 && (
              <Badge variant="warning" dot>
                {plural(warnCount, tr('Hinweis'), tr('Hinweise'))}
              </Badge>
            )}
            <span className={cn('min-w-0 flex-1 truncate', !errorCount && generatorError ? 'text-danger-text' : 'text-fg-muted')} title={footerMessage}>
              {errorCount === 0 && generatorError ? generatorError : footerMessage}
            </span>
            {issues.length > 0 && (
              <ChevronDown aria-hidden className={cn('size-3.5 shrink-0 text-fg-subtle transition-transform', !issuesOpen && 'rotate-180')} />
            )}
          </button>
          {issuesOpen && issues.length > 0 && (
            <ul id={`${uid}-issues`} className="max-h-40 overflow-y-auto border-t border-line px-2 py-1.5">
              {issues.map((issue, i) => (
                <li key={`${localizeMessage(issue.message)}-${i}`}>
                  <button
                    type="button"
                    disabled={!issue.rowId}
                    onClick={() => issue.rowId && onFocusRow(issue.rowId)}
                    className="flex w-full items-start gap-2 rounded-control px-2 py-1 text-left text-xs text-fg-muted outline-none transition-colors focus-ring-inset enabled:hover:bg-surface-2 enabled:hover:text-fg"
                  >
                    <IssueIcon level={issue.level} />
                    <span className="flex-1">{localizeMessage(issue.message)}</span>
                    {issue.rowId && <span className="shrink-0 text-2xs text-accent-text">{tr("Zeigen")}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <PasteDialog
        open={paste.open}
        initialText={paste.text}
        onOpenChange={(open) => setPaste((p) => ({ ...p, open }))}
        existing={ic.pins}
        onApply={applyPaste}
      />
    </div>
  )
}
