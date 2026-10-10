import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Pin-Tabelle des IC-Editors (Tabellenkalkulations-Gefühl): Nummer, Name (Überstrich-Hilfe), elektrischer Typ,
 * Seite (automatisch/links/rechts/oben/unten), Gruppe, Teil, verborgen, Beschreibung; Zeilen duplizieren, löschen,
 * per Griff ziehen (Reihenfolge) oder mit Alt+↑/↓ verschieben. Ab {@link VIRTUAL_FROM} Pins werden nur die
 * sichtbaren Zeilen gerendert (große BGAs/MCUs bleiben beim Tippen flüssig).
 *
 * Tastatur: ↑/↓ wechseln die Zeile (gleiche Spalte – auch in den Auswahlfeldern Typ und Seite; dort öffnen Alt+↓,
 * Leertaste oder F4 die Liste, Buchstaben wählen direkt), Enter geht eine Zeile tiefer und legt in der letzten Zeile
 * einen neuen Pin an, Strg+D dupliziert, Strg+Entf löscht die Zeile, Strg+⇧+O schaltet den Überstrich um.
 */
import { useVirtualizer } from '@tanstack/react-virtual'
import { CopyPlus, EyeOff, GripVertical, Trash2 } from 'lucide-react'
import {
  memo,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type DragEvent,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from 'react'
import type { ElectricalType, IcSide } from '@/api/symbols'
import { Checkbox, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { hasOverbar, partLetter } from '@/lib/geometry'
import { matchesHotkey } from '@/lib/hotkeys'
import type { PinColumn } from '../store'
import { ElectricalDot, OverbarName, OverlineIcon } from '../shared'
import { ELECTRICAL_OPTIONS, SIDE_LABEL, SIDE_ORDER, toggleOverbar, type PinRow } from './pins'

type CellField = 'designator' | 'name' | 'electrical' | 'side' | 'group' | 'part' | 'hidden' | 'description'
type RowErrors = Partial<Record<'designator' | 'name' | 'part', string>>

export interface PinTableProps {
  pins: readonly PinRow[]
  errors: Map<string, RowErrors>
  columns: Record<PinColumn, boolean>
  /** Wirksame Seite automatisch platzierter Pins (aus der Vorschau) */
  effectiveSide: Map<string, IcSide>
  /** Teile verteilt der Generator („Automatisch“/„Anzahl“): Teil je Zeile aus der Vorschau, sonst null */
  autoParts: Map<string, number> | null
  hoverDesignator: string | null
  onHover: (designator: string | null) => void
  /** Zeile fokussieren (z. B. Klick auf einen Pin in der Vorschau) */
  focusRequest: { id: string; nonce: number } | null
  groupSuggestions: readonly string[]
  /** Scrollbereich der Tabelle (für die Virtualisierung langer Listen) */
  scrollRef: RefObject<HTMLElement | null>
  onChange: (id: string, patch: Partial<PinRow>, coalesceKey?: string) => void
  onRemove: (id: string) => void
  onDuplicate: (id: string) => void
  /** Neuen Pin nach `afterId` (bzw. am Ende) anlegen; gibt die neue ID zurück */
  onAdd: (afterId?: string) => string
  onMove: (id: string, delta: number) => void
  onReorder: (id: string, beforeId: string | null) => void
}

const DRAG_TYPE = 'application/x-partforge-pinrow'
/** Ab so vielen Pins werden nur die sichtbaren Zeilen gerendert */
export const VIRTUAL_FROM = 150
/** Zeilenhöhe: Zelle 28 px + 2 × 2 px Abstand + 1 px Linie */
const ROW_HEIGHT = 33
/** Höhe der Kopfzeile (sticky) */
const HEAD_HEIGHT = 32

/** Spaltenbreiten (px); der Name bekommt den Rest. Passt ohne Zusatzspalten in 512 px (Mindestbreite 1120). */
const COL_WIDTH = {
  handle: 24,
  designator: 58,
  name: 100,
  electrical: 146,
  side: 126,
  group: 100,
  part: 48,
  hidden: 44,
  description: 176,
  actions: 58,
} as const

/** Mindestbreite der Tabelle für die sichtbaren Spalten (darunter scrollt der Bereich waagerecht) */
function tableMinWidth(columns: Record<PinColumn, boolean>): number {
  let w = COL_WIDTH.handle + COL_WIDTH.designator + COL_WIDTH.name + COL_WIDTH.electrical + COL_WIDTH.side + COL_WIDTH.actions
  for (const c of ['group', 'part', 'hidden', 'description'] as const) if (columns[c]) w += COL_WIDTH[c]
  return w
}

const cellBase =
  'h-7 w-full min-w-0 rounded-md border border-transparent bg-transparent text-ui text-fg outline-none transition-[border-color,background-color,box-shadow] duration-100 hover:border-line-strong focus:border-accent focus:bg-control focus:shadow-[0_0_0_3px_var(--pf-accent-soft)]'
const cellInput = cn(cellBase, 'px-2 placeholder:text-fg-subtle aria-invalid:border-danger/70 aria-invalid:bg-danger/6')
const cellSelect = cn(cellBase, 'cursor-pointer appearance-none truncate pl-2 pr-5')

/** Pfeil der nativen Auswahl (appearance-none) */
function SelectChevron() {
  return (
    <svg aria-hidden viewBox="0 0 16 16" className="pointer-events-none absolute right-1.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle">
      <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function focusCell(table: HTMLElement | null, rowId: string, field: string): boolean {
  const cell = table?.querySelector<HTMLElement>(`[data-cell="${CSS.escape(`${rowId}:${field}`)}"]`)
  // Kontrollkästchen: Markierung sitzt am umgebenden Element
  const el = cell && !cell.matches('input, select, button') ? cell.querySelector<HTMLElement>('input, select, button') : cell
  if (!el) return false
  el.focus()
  if (el instanceof HTMLInputElement) el.select()
  return true
}

/** Unsichtbarer Fehlertext für `aria-describedby` (sichtbar ist der rote Rahmen, beim Überfahren der Titel) */
function ErrorText({ id, text }: { id: string; text: string | undefined }) {
  if (!text) return null
  return (
    <span id={id} className="sr-only">
      {text}
    </span>
  )
}

/** Teil-Zelle: hält den getippten Text (auch leer), übernimmt nur gültige Zahlen – sonst würde aus „3“ ein „13“. */
function PartCell({
  pin,
  label,
  error,
  errorId,
  onCommit,
  onKeyDown,
}: {
  pin: PinRow
  label: string
  error: string | undefined
  errorId: string
  onCommit: (part: number) => void
  onKeyDown: (e: KeyboardEvent<HTMLInputElement>) => void
}) {
  useI18n()
  const [draft, setDraft] = useState<{ text: string; part: number } | null>(null)
  // Änderung von außen (Rückgängig, Einfügen) verwirft den Entwurf
  const shown = draft && draft.part === pin.part ? draft.text : String(pin.part)
  return (
    <>
      <input
        data-cell={`${pin.id}:part`}
        value={shown}
        aria-label={tr("Teil von {value0} (0 = alle Teile)", { value0: String(label) })}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
        title={error ? localizeMessage(error) : error}
        inputMode="numeric"
        maxLength={2}
        spellCheck={false}
        autoComplete="off"
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, '').slice(0, 2)
          if (digits === '') {
            setDraft({ text: '', part: pin.part })
            return
          }
          const part = Number(digits)
          setDraft({ text: digits, part })
          onCommit(part)
        }}
        onFocus={(e) => e.currentTarget.select()}
        onBlur={() => setDraft(null)}
        onKeyDown={onKeyDown}
        className={cn(cellInput, 'mono text-center')}
      />
      <ErrorText id={errorId} text={error ? localizeMessage(error) : error} />
    </>
  )
}

interface RowProps {
  pin: PinRow
  index: number
  errors: RowErrors | undefined
  columns: Record<PinColumn, boolean>
  effectiveSide: IcSide | undefined
  /** Teil, wenn der Generator die Teile verteilt (0 = noch unbekannt); undefined = Teil von Hand */
  autoPart: number | undefined
  highlighted: boolean
  dragging: boolean
  dropBefore: boolean
  datalistId: string
  /** Position für Screenreader in der virtualisierten Tabelle (1 = Kopfzeile) */
  ariaRowIndex?: number
  onChange: PinTableProps['onChange']
  onRemove: (id: string, index: number, field: CellField | null) => void
  onDuplicate: (id: string, field: CellField | null) => void
  onHover: (designator: string | null) => void
  onNavigate: (rowIndex: number, field: CellField, delta: number) => void
  onMove: (id: string, delta: number) => void
  onDragStartRow: (id: string, e: DragEvent<HTMLElement>) => void
  onDragOverRow: (id: string, e: DragEvent<HTMLTableRowElement>) => void
  onDropRow: (id: string, e: DragEvent<HTMLTableRowElement>) => void
  onDragEnd: () => void
}

/** Feld der Zelle, in der ein Tastendruck passierte (für Fokus nach Duplizieren/Löschen) */
function cellField(target: EventTarget | null): CellField | null {
  const cell = target instanceof HTMLElement ? target.closest<HTMLElement>('[data-cell]')?.dataset.cell : undefined
  return cell ? (cell.slice(cell.lastIndexOf(':') + 1) as CellField) : null
}

const PinRowView = memo(function PinRowView({
  pin,
  index,
  errors,
  columns,
  effectiveSide,
  autoPart,
  highlighted,
  dragging,
  dropBefore,
  datalistId,
  ariaRowIndex,
  onChange,
  onRemove,
  onDuplicate,
  onHover,
  onNavigate,
  onMove,
  onDragStartRow,
  onDragOverRow,
  onDropRow,
  onDragEnd,
}: RowProps) {
  const [nameFocused, setNameFocused] = useState(false)
  const nameRef = useRef<HTMLInputElement>(null)
  const label = tr("Pin {value0}", { value0: String(pin.designator || index + 1) })
  const errId = (field: string) => `${pin.id}-${field}-fehler`

  const textKeys = (field: CellField) => (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault()
      onMove(pin.id, e.key === 'ArrowUp' ? -1 : 1)
      return
    }
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      onNavigate(index, field, e.key === 'ArrowUp' ? -1 : 1)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      onNavigate(index, field, 1)
    } else if (field === 'name' && matchesHotkey(e.nativeEvent, 'mod+shift+o')) {
      e.preventDefault()
      applyOverbar()
    }
  }

  /** Auswahlfelder: ↑/↓ wechseln wie in den Textzellen die Zeile statt den Wert (Alt+↓/F4/Leertaste öffnen die Liste) */
  const selectKeys = (field: CellField) => (e: KeyboardEvent<HTMLSelectElement>) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      onNavigate(index, field, e.key === 'ArrowUp' ? -1 : 1)
    }
  }

  /** Zeilen-Kürzel aus jeder Zelle: Strg+D duplizieren, Strg+Entf löschen */
  const rowKeys = (e: KeyboardEvent<HTMLTableRowElement>) => {
    if (matchesHotkey(e.nativeEvent, 'mod+d')) {
      e.preventDefault()
      onDuplicate(pin.id, cellField(e.target))
    } else if (matchesHotkey(e.nativeEvent, 'mod+delete')) {
      e.preventDefault()
      onRemove(pin.id, index, cellField(e.target))
    }
  }

  const applyOverbar = () => {
    const el = nameRef.current
    const { value, start, end } = toggleOverbar(pin.name, el?.selectionStart, el?.selectionEnd)
    onChange(pin.id, { name: value }, `${pin.id}:name`)
    requestAnimationFrame(() => {
      if (!el) return
      el.focus()
      el.setSelectionRange(start, end)
    })
  }

  const text = (
    field: 'designator' | 'group' | 'description',
    value: string,
    opts: { mono?: boolean; placeholder?: string; invalid?: string; className?: string; ariaLabel: string; maxLength?: number; list?: string },
  ) => (
    <>
      <input
        data-cell={`${pin.id}:${field}`}
        value={value}
        list={opts.list}
        aria-label={opts.ariaLabel}
        aria-invalid={opts.invalid ? true : undefined}
        aria-describedby={opts.invalid ? errId(field) : undefined}
        title={opts.invalid}
        placeholder={opts.placeholder}
        maxLength={opts.maxLength}
        spellCheck={false}
        autoComplete="off"
        onChange={(e) => onChange(pin.id, { [field]: e.target.value } as Partial<PinRow>, `${pin.id}:${field}`)}
        onKeyDown={textKeys(field)}
        className={cn(cellInput, opts.mono && 'mono', opts.className)}
      />
      <ErrorText id={errId(field)} text={opts.invalid} />
    </>
  )

  const electrical = ELECTRICAL_OPTIONS.find((o) => o.value === pin.electrical)
  const td = 'border-b border-line px-1 py-[2px] align-middle'
  return (
    <tr
      data-row={pin.id}
      aria-rowindex={ariaRowIndex}
      onKeyDown={rowKeys}
      onMouseEnter={() => onHover(pin.designator.trim() || null)}
      onMouseLeave={(e) => {
        if (!e.currentTarget.contains(document.activeElement)) onHover(null)
      }}
      onFocus={() => onHover(pin.designator.trim() || null)}
      onBlur={(e: FocusEvent<HTMLTableRowElement>) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onHover(null)
      }}
      onDragOver={(e) => onDragOverRow(pin.id, e)}
      onDrop={(e) => onDropRow(pin.id, e)}
      className={cn(
        'group/row relative transition-colors duration-100',
        highlighted ? 'bg-accent-soft/60' : 'hover:bg-surface-2/60',
        dragging && 'opacity-40',
        dropBefore && '[&>td]:shadow-[inset_0_2px_0_var(--pf-accent)]',
      )}
    >
      <td className={cn(td, 'pl-1 pr-0')}>
        <span
          role="button"
          tabIndex={-1}
          aria-label={tr("{value0} verschieben (Alt+↑/↓)", { value0: String(label) })}
          draggable
          onDragStart={(e) => onDragStartRow(pin.id, e)}
          onDragEnd={onDragEnd}
          className="flex h-7 w-5 cursor-grab items-center justify-center rounded-sm text-fg-subtle opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-60 active:cursor-grabbing"
        >
          <GripVertical className="size-3.5" />
        </span>
      </td>
      <td className={td}>
        {text('designator', pin.designator, { mono: true, ariaLabel: tr("Pin-Nummer, Zeile {value0}", { value0: String(index + 1) }), invalid: errors?.designator, maxLength: 12, className: 'font-semibold' })}
      </td>
      <td className={td}>
        <div className="relative">
          <input
            ref={nameRef}
            data-cell={`${pin.id}:name`}
            value={pin.name}
            aria-label={tr("Name von {value0}", { value0: String(label) })}
            aria-invalid={errors?.name ? true : undefined}
            aria-describedby={errors?.name ? errId('name') : undefined}
            aria-keyshortcuts="Control+Shift+O"
            placeholder={tr("Name")}
            spellCheck={false}
            autoComplete="off"
            onFocus={() => setNameFocused(true)}
            onBlur={() => setNameFocused(false)}
            onChange={(e) => onChange(pin.id, { name: e.target.value }, `${pin.id}:name`)}
            onKeyDown={textKeys('name')}
            className={cn(cellInput, 'mono pr-8', !nameFocused && hasOverbar(pin.name) && 'text-transparent')}
          />
          <ErrorText id={errId('name')} text={errors?.name} />
          {!nameFocused && hasOverbar(pin.name) && (
            <span aria-hidden className="mono pointer-events-none absolute inset-y-0 left-0 right-8 flex items-center overflow-hidden whitespace-nowrap px-[9px] text-ui text-fg">
              <OverbarName value={pin.name} />
            </span>
          )}
          <Tooltip content={tr("Überstrich (low-aktiv) für Markierung oder Namen")} hotkey="mod+shift+o">
            <button
              type="button"
              tabIndex={-1}
              aria-label={tr("Überstrich für {value0} umschalten", { value0: String(label) })}
              onMouseDown={(e) => e.preventDefault()}
              onClick={applyOverbar}
              className={cn(
                'absolute right-1 top-1/2 flex size-6 -translate-y-1/2 items-center justify-center rounded-md text-fg-subtle outline-none transition-[opacity,background-color,color] hover:bg-surface-3 hover:text-fg',
                hasOverbar(pin.name) && 'text-accent-text',
                'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100',
              )}
            >
              <OverlineIcon className="size-3.5" />
            </button>
          </Tooltip>
        </div>
      </td>
      <td className={td}>
        <div className="relative flex items-center">
          <ElectricalDot type={pin.electrical} className="pointer-events-none absolute left-2" />
          {/* Liste mit ausführlichen Namen („Open Collector / Drain“), in der Zelle die Kurzform */}
          <select
            data-cell={`${pin.id}:electrical`}
            aria-label={tr("Elektrischer Typ von {value0}", { value0: String(label) })}
            value={pin.electrical}
            onChange={(e) => onChange(pin.id, { electrical: e.target.value as ElectricalType })}
            onKeyDown={selectKeys('electrical')}
            className={cn(cellSelect, 'pl-6 text-transparent')}
          >
            {ELECTRICAL_OPTIONS.map((o) => (
              <option key={o.value} value={o.value} className="text-fg">
                {tr(o.label)}
              </option>
            ))}
          </select>
          <span aria-hidden className="pointer-events-none absolute inset-y-0 left-6 right-[18px] flex items-center truncate text-ui text-fg">
            {electrical?.short ?? pin.electrical}
          </span>
          <SelectChevron />
        </div>
      </td>
      <td className={td}>
        <div className="relative">
          <select
            data-cell={`${pin.id}:side`}
            aria-label={tr("Seite von {value0}", { value0: String(label) })}
            value={pin.side ?? ''}
            onChange={(e) => onChange(pin.id, { side: (e.target.value || null) as IcSide | null })}
            onKeyDown={selectKeys('side')}
            className={cn(cellSelect, !pin.side && 'text-fg-muted')}
          >
            <option value="" className="text-fg">
              {effectiveSide ? `Auto · ${tr(SIDE_LABEL[effectiveSide]).toLowerCase()}` : tr('Automatisch')}
            </option>
            {SIDE_ORDER.map((s) => (
              <option key={s} value={s} className="text-fg">
                {tr(SIDE_LABEL[s])}
              </option>
            ))}
          </select>
          <SelectChevron />
        </div>
      </td>
      {columns.group && (
        <td className={td}>{text('group', pin.group, { placeholder: '–', ariaLabel: tr("Gruppe von {value0}", { value0: String(label) }), list: datalistId })}</td>
      )}
      {columns.part && (
        <td className={td}>
          {autoPart !== undefined ? (
            <span
              title={autoPart ? tr("Vom Generator verteilt: Teil {value0}", { value0: String(partLetter(autoPart)) }) : tr('Wird verteilt …')}
              className="mono flex h-7 items-center justify-center text-ui text-fg-subtle"
            >
              {autoPart ? partLetter(autoPart) : '·'}
            </span>
          ) : (
            <PartCell
              pin={pin}
              label={label}
              error={errors?.part}
              errorId={errId('part')}
              onCommit={(part) => onChange(pin.id, { part }, `${pin.id}:part`)}
              onKeyDown={textKeys('part')}
            />
          )}
        </td>
      )}
      {columns.hidden && (
        <td className={cn(td, 'text-center')}>
          <div data-cell={`${pin.id}:hidden`} className="flex justify-center">
            <Checkbox
              checked={pin.hidden}
              onCheckedChange={(v) => onChange(pin.id, { hidden: v === true })}
              aria-label={tr("{value0} verborgen", { value0: String(label) })}
            />
          </div>
        </td>
      )}
      {columns.description && (
        <td className={td}>{text('description', pin.description, { placeholder: '–', ariaLabel: tr("Beschreibung von {value0}", { value0: String(label) }) })}</td>
      )}
      <td className={cn(td, 'pr-1')}>
        <RowActions label={label} onDuplicate={() => onDuplicate(pin.id, null)} onRemove={() => onRemove(pin.id, index, null)} />
      </td>
    </tr>
  )
})

/** Duplizieren/Löschen am Zeilenende (beim Überfahren bzw. Fokus in der Zeile sichtbar; Tastatur: Strg+D, Strg+Entf) */
function RowActions({ label, onDuplicate, onRemove }: { label: string; onDuplicate: () => void; onRemove: () => void }) {
  useI18n()
  return (
    <div className="flex items-center justify-end gap-0.5 opacity-0 transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-100">
      <Tooltip content={tr("Duplizieren (nächste Nummer)")} hotkey="mod+d">
        <button
          type="button"
          tabIndex={-1}
          aria-label={tr("{value0} duplizieren", { value0: String(label) })}
          aria-keyshortcuts="Control+D"
          onClick={onDuplicate}
          className="flex size-6 items-center justify-center rounded-md text-fg-muted outline-none transition-colors hover:bg-surface-3 hover:text-fg focus-ring"
        >
          <CopyPlus className="size-3.5" />
        </button>
      </Tooltip>
      <Tooltip content={tr("Löschen")} hotkey="mod+delete">
        <button
          type="button"
          tabIndex={-1}
          aria-label={tr("{value0} löschen", { value0: String(label) })}
          aria-keyshortcuts="Control+Delete"
          onClick={onRemove}
          className="flex size-6 items-center justify-center rounded-md text-fg-muted outline-none transition-colors hover:bg-danger/12 hover:text-danger-text focus-ring"
        >
          <Trash2 className="size-3.5" />
        </button>
      </Tooltip>
    </div>
  )
}

function Th({ children, className, title }: { children?: ReactNode; className?: string; title?: string }) {
  return (
    <th
      scope="col"
      title={title}
      className={cn(
        'sticky top-0 z-[3] h-8 border-b border-line-strong bg-surface px-3 text-left text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle',
        className,
      )}
    >
      {children}
    </th>
  )
}

export function PinTable({
  pins,
  errors,
  columns,
  effectiveSide,
  autoParts,
  hoverDesignator,
  onHover,
  focusRequest,
  groupSuggestions,
  scrollRef,
  onChange,
  onRemove,
  onDuplicate,
  onAdd,
  onMove,
  onReorder,
}: PinTableProps) {
  useI18n()
  const uid = useId().replace(/:/g, '')
  const datalistId = `${uid}-groups`
  const tableRef = useRef<HTMLTableElement>(null)
  const [dragId, setDragId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const virtual = pins.length > VIRTUAL_FROM

  // TanStack Virtual verwaltet seinen Zustand selbst (nicht mit dem React Compiler memoisierbar) – bewusst so
  // oxlint-disable-next-line react/incompatible-library
  const virtualizer = useVirtualizer({
    count: virtual ? pins.length : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 12,
    scrollMargin: HEAD_HEIGHT,
  })

  // aktuelle Props/Werte für die stabilen Rückrufe (Zeilen sind memoisiert)
  const latest = useRef({ pins, onAdd, onMove, onReorder, onRemove, onDuplicate, virtual, virtualizer })
  useEffect(() => {
    latest.current = { pins, onAdd, onMove, onReorder, onRemove, onDuplicate, virtual, virtualizer }
  })

  /** Zeile sichtbar machen (in langen Listen erst rendern lassen) und eine Zelle fokussieren */
  const reveal = useCallback((rowId: string, field: CellField, opts: { smooth?: boolean } = {}) => {
    const { pins: list, virtual: isVirtual, virtualizer: v } = latest.current
    const index = list.findIndex((p) => p.id === rowId)
    if (index < 0) return
    const tryFocus = (attempt: number) => {
      if (focusCell(tableRef.current, rowId, field) || focusCell(tableRef.current, rowId, 'designator')) {
        tableRef.current
          ?.querySelector<HTMLElement>(`[data-row="${CSS.escape(rowId)}"]`)
          ?.scrollIntoView({ block: 'nearest', behavior: opts.smooth ? 'smooth' : 'auto' })
        return
      }
      if (attempt < 4) requestAnimationFrame(() => tryFocus(attempt + 1))
    }
    if (isVirtual) v.scrollToIndex(index, { align: 'auto' })
    requestAnimationFrame(() => tryFocus(0))
  }, [])

  // Zeile fokussieren (Klick auf einen Pin in der Vorschau, „Zur Zeile“)
  useEffect(() => {
    if (focusRequest) reveal(focusRequest.id, 'name', { smooth: true })
  }, [focusRequest, reveal])

  const onNavigate = useCallback(
    (rowIndex: number, field: CellField, delta: number) => {
      const list = latest.current.pins
      const target = rowIndex + delta
      if (target >= list.length && delta > 0) {
        const id = latest.current.onAdd(list[rowIndex]?.id)
        reveal(id, field === 'designator' ? 'name' : field)
        return
      }
      const row = list[Math.max(0, target)]
      if (row) reveal(row.id, field)
    },
    [reveal],
  )
  const onMoveRow = useCallback((id: string, delta: number) => {
    latest.current.onMove(id, delta)
    requestAnimationFrame(() => (document.activeElement as HTMLElement | null)?.scrollIntoView({ block: 'nearest' }))
  }, [])
  const onDuplicateRow = useCallback(
    (id: string, field: CellField | null) => {
      latest.current.onDuplicate(id)
      // Fokus in die Kopie (gleiche Spalte), damit Strg+D mehrfach hintereinander funktioniert
      if (field) {
        requestAnimationFrame(() => {
          const list = latest.current.pins
          const i = list.findIndex((p) => p.id === id)
          const copy = list[i + 1]
          if (copy) reveal(copy.id, field)
        })
      }
    },
    [reveal],
  )
  const onRemoveRow = useCallback(
    (id: string, index: number, field: CellField | null) => {
      const list = latest.current.pins
      const next = list[index + 1] ?? list[index - 1]
      latest.current.onRemove(id)
      if (field && next) reveal(next.id, field)
    },
    [reveal],
  )
  const onDragStartRow = useCallback((id: string, e: DragEvent<HTMLElement>) => {
    e.dataTransfer.setData(DRAG_TYPE, id)
    e.dataTransfer.effectAllowed = 'move'
    const row = (e.currentTarget as HTMLElement).closest('tr')
    if (row) e.dataTransfer.setDragImage(row, 24, 16)
    setDragId(id)
  }, [])
  const onDragOverRow = useCallback((id: string, e: DragEvent<HTMLTableRowElement>) => {
    if (!e.dataTransfer.types.includes(DRAG_TYPE)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDropTarget((cur) => (cur === id ? cur : id))
  }, [])
  const onDropRow = useCallback((id: string, e: DragEvent<HTMLTableRowElement>) => {
    const from = e.dataTransfer.getData(DRAG_TYPE)
    if (!from) return
    e.preventDefault()
    if (from !== id) latest.current.onReorder(from, id)
    setDragId(null)
    setDropTarget(null)
  }, [])
  const onDragEnd = useCallback(() => {
    setDragId(null)
    setDropTarget(null)
  }, [])

  const colCount = 6 + (['group', 'part', 'hidden', 'description'] as const).filter((c) => columns[c]).length
  const items = virtual ? virtualizer.getVirtualItems() : null
  const padTop = items?.length ? items[0].start - HEAD_HEIGHT : 0
  const padBottom = items?.length ? virtualizer.getTotalSize() - (items[items.length - 1].end - HEAD_HEIGHT) : 0
  const visible: { pin: PinRow; index: number }[] = items
    ? items.map((it) => ({ pin: pins[it.index], index: it.index })).filter((r) => r.pin)
    : pins.map((pin, index) => ({ pin, index }))

  return (
    <div
      className="relative"
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropTarget(null)
      }}
    >
      <table
        ref={tableRef}
        aria-rowcount={virtual ? pins.length + 1 : undefined}
        className="w-full table-fixed border-separate border-spacing-0 text-ui"
        style={{ minWidth: tableMinWidth(columns) }}
      >
        <caption className="sr-only">
          {tr("Pinliste. ↑ und ↓ wechseln die Zeile, Enter legt in der letzten Zeile einen Pin an, Alt+↑/↓ verschiebt die Zeile, Strg+D dupliziert, Strg+Entf löscht sie.")}
        </caption>
        <colgroup>
          <col style={{ width: COL_WIDTH.handle }} />
          <col style={{ width: COL_WIDTH.designator }} />
          <col />
          <col style={{ width: COL_WIDTH.electrical }} />
          <col style={{ width: COL_WIDTH.side }} />
          {columns.group && <col style={{ width: COL_WIDTH.group }} />}
          {columns.part && <col style={{ width: COL_WIDTH.part }} />}
          {columns.hidden && <col style={{ width: COL_WIDTH.hidden }} />}
          {columns.description && <col style={{ width: COL_WIDTH.description }} />}
          <col style={{ width: COL_WIDTH.actions }} />
        </colgroup>
        <thead>
          <tr aria-rowindex={virtual ? 1 : undefined}>
            <Th className="px-0">
              <span className="sr-only">{tr("Verschieben")}</span>
            </Th>
            <Th className="pl-3">{tr("Nr.")}</Th>
            <Th>{tr("Name")}</Th>
            <Th className="pl-7">{tr("Typ")}</Th>
            <Th>{tr("Seite")}</Th>
            {columns.group && <Th>{tr("Gruppe")}</Th>}
            {columns.part && (
              <Th className="px-1 text-center" title={tr("Teil (0 = in allen Teilen)")}>
                {tr("Teil")}
              </Th>
            )}
            {columns.hidden && (
              <Th className="px-1 text-center" title={tr("Verborgen (z. B. Masse eines mehrteiligen ICs)")}>
                <EyeOff aria-hidden className="mx-auto size-3.5" />
                <span className="sr-only">{tr("Verborgen")}</span>
              </Th>
            )}
            {columns.description && <Th>{tr("Beschreibung")}</Th>}
            <Th>
              <span className="sr-only">{tr("Aktionen")}</span>
            </Th>
          </tr>
        </thead>
        <tbody>
          {padTop > 0 && (
            <tr aria-hidden style={{ height: padTop }}>
              <td colSpan={colCount} className="p-0">
                <span className="sr-only">{tr("Weitere Pins oberhalb")}</span>
              </td>
            </tr>
          )}
          {visible.map(({ pin, index }) => (
            <PinRowView
              key={pin.id}
              pin={pin}
              index={index}
              errors={errors.get(pin.id)}
              columns={columns}
              effectiveSide={pin.side ? undefined : effectiveSide.get(pin.id)}
              autoPart={autoParts ? (autoParts.get(pin.id) ?? 0) : undefined}
              highlighted={hoverDesignator !== null && pin.designator.trim() === hoverDesignator}
              dragging={dragId === pin.id}
              dropBefore={dragId !== null && dropTarget === pin.id && dragId !== pin.id}
              datalistId={datalistId}
              ariaRowIndex={virtual ? index + 2 : undefined}
              onChange={onChange}
              onRemove={onRemoveRow}
              onDuplicate={onDuplicateRow}
              onHover={onHover}
              onNavigate={onNavigate}
              onMove={onMoveRow}
              onDragStartRow={onDragStartRow}
              onDragOverRow={onDragOverRow}
              onDropRow={onDropRow}
              onDragEnd={onDragEnd}
            />
          ))}
          {padBottom > 0 && (
            <tr aria-hidden style={{ height: padBottom }}>
              <td colSpan={colCount} className="p-0">
                <span className="sr-only">{tr("Weitere Pins unterhalb")}</span>
              </td>
            </tr>
          )}
        </tbody>
      </table>
      <datalist id={datalistId} aria-label={tr("Vorschläge für Gruppen")}>
        {groupSuggestions.map((g) => (
          <option key={g} value={g}>
            {g}
          </option>
        ))}
      </datalist>
    </div>
  )
}
