/**
 * Felder einer Kategorie: Reihenfolge per Ziehen (Griff) oder Tastatur (Leertaste aufnehmen, ↑/↓, Leertaste ablegen,
 * Alt+↑/↓ direkt), Beschriftung direkt in der Zeile, Merkmale (Pflicht, Schaltplan, Design) als Umschalter – jede
 * Änderung wird sofort gespeichert und lässt sich im Toast rückgängig machen. Entfernen legt vorher eine Sicherung an.
 * Die Teilenummer steht immer an erster Stelle (wie im Backend, `categories.reorder_fields`).
 */
import { Reorder, useDragControls } from 'motion/react'
import { Asterisk, Eye, FileInput, GripVertical, Lock, Pencil, Plus, Search, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { PART_NUMBER } from '@/api/parts'
import {
  applySchemaResult,
  schemaApi,
  type CategoryDef,
  type FieldDef,
  type FieldKindInfo,
  type FieldPatch,
} from '@/api/settings'
import { Badge, Button, confirm, IconButton, Input, Switch, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useBooleanPref } from '../hooks'
import { templateColumns } from '../templateRender'
import { FieldDialog } from './FieldDialog'
import { FIELD_KIND_META, kindIcon } from './meta'
import { runUndo } from './undo'

const fold = (s: string) => s.toLocaleLowerCase('de-DE')
const sameOrder = (a: string[], b: string[]) => a.join('\u0000') === b.join('\u0000')

/** Neue Reihenfolge der sichtbaren Felder in die Gesamtreihenfolge einsetzen (ausgeblendete bleiben auf ihrem Platz) */
function mergeOrder(full: string[], visible: Set<string>, nextVisible: string[]): string[] {
  let i = 0
  return full.map((c) => (visible.has(c) ? nextVisible[i++] : c))
}

/** Teilenummer immer zuerst (das Backend sortiert sie ohnehin nach vorn) */
function pinFirst(columns: string[]): string[] {
  return columns.includes(PART_NUMBER) ? [PART_NUMBER, ...columns.filter((c) => c !== PART_NUMBER)] : columns
}

function kindText(f: FieldDef, kinds: FieldKindInfo[]): string {
  const base = kinds.find((k) => k.kind === f.kind)?.label ?? FIELD_KIND_META[f.kind]?.label ?? f.kind
  if ((f.kind === 'quantity' || f.kind === 'range') && f.unit) return `${f.kind === 'range' ? 'Bereich' : 'Messwert'} · ${f.unit}`
  if (f.kind === 'enum') return `Auswahl · ${f.options?.length ?? 0}`
  return base
}

/** Spalten: Griff · Feld · (Art) · Pflicht · Schaltplan · Design · Aktionen */
const ROW_GRID =
  'grid grid-cols-[1.75rem_minmax(0,1fr)_4.5rem_5.5rem_4.5rem_3.75rem] items-center gap-x-2 @[40rem]:grid-cols-[1.75rem_minmax(0,1fr)_8.5rem_4.5rem_5.5rem_4.5rem_3.75rem]'

export function FieldsPanel({ category, kinds }: { category: CategoryDef; kinds: FieldKindInfo[] }) {
  const navigate = useNavigate()
  const table = category.table
  const fields = category.fields
  const serverOrder = fields.map((f) => f.column)
  const [showCommon, setShowCommon] = useBooleanPref('pf-schema-standardfelder', false)
  const [query, setQuery] = useState('')
  const [dialog, setDialog] = useState<{ field: FieldDef | null } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  /** Noch offene „Rückgängig“-Meldungen: Ausgangsstand der Reihenfolge bzw. je Feld (mehrere Schritte = eine Meldung) */
  const orderUndo = useRef<{ order: string[]; steps: number } | null>(null)
  const fieldUndo = useRef(new Map<string, { patch: FieldPatch; steps: number }>())

  // Lokale Reihenfolge (folgt dem Server, solange nicht gezogen wird)
  const [order, setOrder] = useState(serverOrder)
  const [base, setBase] = useState(serverOrder.join('\u0000'))
  const [grabbed, setGrabbed] = useState<{ column: string; before: string[] } | null>(null)
  const [dragging, setDragging] = useState(false)
  const orderRef = useRef(order)
  useEffect(() => {
    orderRef.current = order
  })
  const serverKey = serverOrder.join('\u0000')
  if (serverKey !== base && !grabbed && !dragging) {
    setBase(serverKey)
    setOrder(serverOrder)
  }

  const byColumn = new Map(fields.map((f) => [f.column, f]))
  const used = new Set(
    [...templateColumns(category.description_template ?? ''), ...templateColumns(category.comment_template ?? '')].map(fold),
  )
  const q = fold(query.trim())
  const commonCount = fields.filter((f) => f.common).length
  const visible = order.filter((c) => {
    const f = byColumn.get(c)
    if (!f) return false
    if (!showCommon && f.common && !q) return false
    return !q || fold(`${f.label} ${f.column}`).includes(q)
  })
  const visibleSet = new Set(visible)

  // ------------------------------------------------------------------ Speichern

  const commitOrder = async (next: string[], previous: string[]) => {
    if (sameOrder(next, previous)) return
    try {
      const cat = await schemaApi.reorderFields(table, next)
      applySchemaResult(cat)
      // Immer den Stand des Servers zeigen – auch wenn er die Reihenfolge nicht übernommen hat
      const result = cat.fields.map((f) => f.column)
      setOrder(result)
      setBase(result.join('\u0000'))
      if (sameOrder(result, previous)) return
      // Mehrere Schritte kurz hintereinander teilen sich eine Meldung (gleiche ID) – „Rückgängig“ stellt dann die
      // Reihenfolge vor dem ersten Schritt her, statt nur den letzten zurückzunehmen
      const pending = orderUndo.current
      const undoTo = pending?.order ?? previous
      const steps = (pending?.steps ?? 0) + 1
      orderUndo.current = { order: undoTo, steps }
      const forget = () => {
        orderUndo.current = null
      }
      toast.success('Reihenfolge gespeichert', {
        id: 'schema-order',
        description: steps > 1 ? `Gilt für Tabelle, Formulare und die DbLib. „Rückgängig“ nimmt alle ${steps} Schritte zurück.` : 'Gilt für Tabelle, Formulare und die DbLib.',
        action: {
          label: 'Rückgängig',
          onClick: () => {
            forget()
            void runUndo(() => schemaApi.reorderFields(table, undoTo))
          },
        },
        onDismiss: forget,
        onAutoClose: forget,
      })
    } catch (error) {
      setOrder(previous)
      toast.error('Reihenfolge konnte nicht gespeichert werden', { description: errorMessage(error) })
    }
  }

  const patchField = async (f: FieldDef, patch: FieldPatch, message: string) => {
    const back: FieldPatch = {}
    for (const key of Object.keys(patch) as (keyof FieldPatch)[]) {
      ;(back as Record<string, unknown>)[key] = f[key as keyof FieldDef] ?? null
    }
    setBusy(f.column)
    try {
      const cat = await schemaApi.updateField(table, f.column, patch)
      applySchemaResult(cat)
      // Weitere Änderung am selben Feld, solange die Meldung steht: eine Meldung, ein „Rückgängig“ bis zum Stand
      // vor der ersten Änderung (frühere Werte gewinnen)
      const pending = fieldUndo.current.get(f.column)
      const undoPatch: FieldPatch = { ...back, ...(pending?.patch ?? {}) }
      const steps = (pending?.steps ?? 0) + 1
      fieldUndo.current.set(f.column, { patch: undoPatch, steps })
      const forget = () => {
        fieldUndo.current.delete(f.column)
      }
      toast.success(message, {
        id: `schema-field-${f.column}`,
        description: steps > 1 ? `„Rückgängig“ nimmt alle ${steps} Änderungen an „${f.label}“ zurück.` : undefined,
        action: {
          label: 'Rückgängig',
          onClick: () => {
            forget()
            void runUndo(() => schemaApi.updateField(table, f.column, undoPatch))
          },
        },
        onDismiss: forget,
        onAutoClose: forget,
      })
    } catch (error) {
      toast.error('Feld konnte nicht geändert werden', { description: errorMessage(error) })
    } finally {
      setBusy(null)
    }
  }

  const removeField = async (f: FieldDef) => {
    const ok = await confirm({
      title: `Feld „${f.label}“ entfernen?`,
      description: (
        <>
          Die Spalte <span className="mono text-fg">{f.column}</span> wird mit allen Werten aus „{category.label}“ gelöscht.
          PartForge legt vorher automatisch eine Sicherung an; Vorlagen, die das Feld nutzen, werden angepasst.
        </>
      ),
      confirmLabel: 'Entfernen',
      destructive: true,
      icon: <Trash2 />,
      onConfirm: async () => {
        try {
          const cat = await schemaApi.removeField(table, f.column)
          applySchemaResult(cat)
        } catch (error) {
          toast.error('Feld konnte nicht entfernt werden', { description: errorMessage(error) })
          throw error
        }
      },
    })
    if (ok) {
      toast.success(`Feld „${f.label}“ entfernt`, {
        description: 'Der vorherige Stand liegt in den Sicherungen.',
        action: { label: 'Sicherungen', onClick: () => navigate('/einstellungen/bibliothek') },
      })
    }
  }

  // ------------------------------------------------------------------ Tastatur-Verschieben

  const position = (column: string, list = visible) => list.indexOf(column) + 1

  const move = (column: string, dir: -1 | 1) => {
    const idx = visible.indexOf(column)
    const target = idx + dir
    if (idx < 0 || target < 0 || target >= visible.length) return null
    // An der Teilenummer vorbei geht es nicht – sie bleibt oben
    if (column === PART_NUMBER || visible[target] === PART_NUMBER) {
      setAnnouncement('Die Teilenummer steht immer an erster Stelle.')
      return null
    }
    const nextVisible = [...visible]
    ;[nextVisible[idx], nextVisible[target]] = [nextVisible[target], nextVisible[idx]]
    const next = mergeOrder(order, visibleSet, nextVisible)
    setOrder(next)
    setAnnouncement(`Position ${target + 1} von ${visible.length}`)
    return next
  }

  const onHandleKey = (e: KeyboardEvent<HTMLButtonElement>, f: FieldDef) => {
    const label = f.label
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault()
      const before = order
      const next = move(f.column, e.key === 'ArrowUp' ? -1 : 1)
      if (next) void commitOrder(next, before)
      return
    }
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault()
      if (!grabbed) {
        setGrabbed({ column: f.column, before: order })
        setAnnouncement(
          `„${label}“ aufgenommen, Position ${position(f.column)} von ${visible.length}. Pfeiltasten verschieben, Leertaste legt ab, Escape bricht ab.`,
        )
      } else {
        const before = grabbed.before
        setGrabbed(null)
        setAnnouncement(`„${label}“ abgelegt an Position ${position(f.column)}.`)
        void commitOrder(order, before)
      }
      return
    }
    if (grabbed && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault()
      move(f.column, e.key === 'ArrowUp' ? -1 : 1)
      return
    }
    if (grabbed && e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      setOrder(grabbed.before)
      setGrabbed(null)
      setAnnouncement('Verschieben abgebrochen.')
    }
  }

  return (
    <div className="flex flex-col">
      {/* Werkzeugleiste */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line px-5 py-3">
        <Input
          size="sm"
          prefix={<Search />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Feld suchen …"
          aria-label="Felder durchsuchen"
          containerClassName="w-52 max-w-full"
        />
        <Switch
          size="sm"
          checked={showCommon}
          onCheckedChange={setShowCommon}
          label={<span className="text-xs font-normal text-fg-muted">Standardfelder ({commonCount})</span>}
          className="gap-2.5"
        />
        <Button size="sm" variant="secondary" leftIcon={<Plus />} className="ml-auto" onClick={() => setDialog({ field: null })}>
          Feld hinzufügen
        </Button>
      </div>

      {/* Tabelle */}
      <div role="table" aria-label={`Felder von ${category.label}`} aria-rowcount={visible.length + 1} className="@container">
        <div role="rowgroup">
          <div role="row" className={cn(ROW_GRID, 'border-b border-line bg-surface-2/40 px-5 py-2')}>
            <span role="columnheader">
              <span className="sr-only">Reihenfolge</span>
            </span>
            <span role="columnheader" className="micro-label">
              Feld
            </span>
            <span role="columnheader" className="micro-label hidden @[40rem]:block">
              Art
            </span>
            <FlagHeader title="Pflicht" hint="Bauteile ohne Wert gelten als unvollständig" />
            <FlagHeader title="Schaltplan" hint="Parameter beim Platzieren im Schaltplan anzeigen" />
            <FlagHeader title="Design" hint="Als Bauteilparameter ins Altium-Design übernehmen" />
            <span role="columnheader">
              <span className="sr-only">Aktionen</span>
            </span>
          </div>
        </div>
        {visible.length === 0 ? (
          <div role="rowgroup">
            <div role="row" className="px-5 py-10 text-center text-xs text-fg-subtle">
              <span role="cell">
                {q
                  ? `Kein Feld passt zu „${query.trim()}“.`
                  : 'Diese Kategorie hat nur Standardfelder – „Feld hinzufügen“ legt das erste eigene Feld an.'}
              </span>
            </div>
          </div>
        ) : (
          <Reorder.Group
            as="div"
            role="rowgroup"
            axis="y"
            values={visible}
            onReorder={(nextVisible: string[]) => setOrder((o) => mergeOrder(o, new Set(nextVisible), pinFirst(nextVisible)))}
            className="divide-y divide-line"
          >
            {visible.map((column) => {
              const f = byColumn.get(column)
              if (!f) return null
              return (
                <FieldRow
                  key={column}
                  field={f}
                  kinds={kinds}
                  isValueField={(category.value_field ?? '').toLowerCase() === column.toLowerCase()}
                  inTemplate={used.has(fold(column))}
                  grabbed={grabbed?.column === column}
                  busy={busy === column}
                  onDragStart={() => {
                    setDragging(true)
                    setGrabbed(null)
                    return order
                  }}
                  onDragEnd={(before) => {
                    setDragging(false)
                    void commitOrder(orderRef.current, before)
                  }}
                  onHandleKey={(e) => onHandleKey(e, f)}
                  onHandleBlur={() => {
                    if (grabbed?.column === column) {
                      const before = grabbed.before
                      setGrabbed(null)
                      void commitOrder(order, before)
                    }
                  }}
                  onRename={(label) => void patchField(f, { label }, `Beschriftung „${label}“ gespeichert`)}
                  onToggle={(key, value) => void patchField(f, { [key]: value }, toggleMessage(f, key, value))}
                  onEdit={() => setDialog({ field: f })}
                  onRemove={() => void removeField(f)}
                />
              )
            })}
          </Reorder.Group>
        )}
      </div>
      <p className="sr-only" aria-live="assertive">
        {announcement}
      </p>
      <p className="border-t border-line px-5 py-2.5 text-2xs leading-relaxed text-fg-subtle">
        Feldänderungen werden sofort gespeichert und lassen sich über „Rückgängig“ in der Meldung zurücknehmen. Reihenfolge:
        Griff ziehen oder Griff fokussieren, Leertaste, ↑/↓, Leertaste (Alt+↑/↓ verschiebt direkt).
      </p>

      <FieldDialog open={dialog !== null} onOpenChange={(o) => !o && setDialog(null)} category={category} field={dialog?.field} kinds={kinds} />
    </div>
  )
}

function FlagHeader({ title, hint }: { title: string; hint: string }) {
  return (
    <span role="columnheader" title={hint} className="micro-label text-center">
      {title}
    </span>
  )
}

type FlagKey = 'required' | 'show_on_schematic' | 'add_to_design'

function toggleMessage(f: FieldDef, key: FlagKey, value: boolean): string {
  const name = `„${f.label}“`
  if (key === 'required') return value ? `${name} ist jetzt Pflichtfeld` : `${name} ist kein Pflichtfeld mehr`
  if (key === 'show_on_schematic') return value ? `${name} wird im Schaltplan angezeigt` : `${name} wird im Schaltplan ausgeblendet`
  return value ? `${name} wird ins Design übernommen` : `${name} wird nicht mehr ins Design übernommen`
}

// --------------------------------------------------------------------------- Zeile

interface FieldRowProps {
  field: FieldDef
  kinds: FieldKindInfo[]
  isValueField: boolean
  inTemplate: boolean
  grabbed: boolean
  busy: boolean
  onDragStart: () => string[]
  onDragEnd: (before: string[]) => void
  onHandleKey: (e: KeyboardEvent<HTMLButtonElement>) => void
  onHandleBlur: () => void
  onRename: (label: string) => void
  onToggle: (key: FlagKey, value: boolean) => void
  onEdit: () => void
  onRemove: () => void
}

function FieldRow({
  field: f,
  kinds,
  isValueField,
  inTemplate,
  grabbed,
  busy,
  onDragStart,
  onDragEnd,
  onHandleKey,
  onHandleBlur,
  onRename,
  onToggle,
  onEdit,
  onRemove,
}: FieldRowProps) {
  const controls = useDragControls()
  const before = useRef<string[]>([])
  const locked = f.protected
  const isPartNumber = f.column === PART_NUMBER
  const lockReason = isPartNumber
    ? 'die Teilenummer ist der Schlüssel jedes Bauteils'
    : 'gebraucht für die Altium-Verknüpfung bzw. die Verwaltung'

  return (
    <Reorder.Item
      as="div"
      role="row"
      value={f.column}
      dragListener={false}
      dragControls={controls}
      onDragStart={() => {
        before.current = onDragStart()
      }}
      onDragEnd={() => onDragEnd(before.current)}
      whileDrag={{ scale: 1.01, boxShadow: '0 12px 32px -12px rgba(0,0,0,.45)', zIndex: 5 }}
      className={cn(
        ROW_GRID,
        'group/fr relative bg-surface px-5 py-2',
        grabbed && 'z-10 bg-surface-2 shadow-[inset_0_0_0_2px_var(--pf-accent)]',
        busy && 'opacity-70',
      )}
    >
      <span role="cell" className="flex">
        {isPartNumber ? (
          <Tooltip content="Die Teilenummer steht immer an erster Stelle">
            <button
              type="button"
              aria-label="„Teilenummer“ verschieben (nicht möglich: steht immer an erster Stelle)"
              aria-disabled="true"
              onClick={() => undefined}
              className="flex size-7 cursor-not-allowed items-center justify-center rounded-control text-fg-subtle opacity-40 outline-none focus-ring"
            >
              <GripVertical aria-hidden className="size-4" />
            </button>
          </Tooltip>
        ) : (
          <button
            type="button"
            aria-label={`„${f.label}“ verschieben`}
            aria-pressed={grabbed}
            aria-keyshortcuts="Space Alt+ArrowUp Alt+ArrowDown"
            onPointerDown={(e) => {
              e.preventDefault()
              controls.start(e)
            }}
            onKeyDown={onHandleKey}
            onBlur={onHandleBlur}
            className={cn(
              'flex size-7 cursor-grab touch-none items-center justify-center rounded-control outline-none transition-colors focus-ring active:cursor-grabbing',
              grabbed ? 'bg-accent-soft text-accent' : 'text-fg-subtle hover:bg-surface-3 hover:text-fg',
            )}
          >
            <GripVertical aria-hidden className="size-4" />
          </button>
        )}
      </span>

      <span role="cell" className="flex min-w-0 items-center gap-2.5">
        <span aria-hidden className="flex size-7 shrink-0 items-center justify-center rounded-control bg-surface-2 text-fg-muted [&_svg]:size-3.5">
          {kindIcon(f.kind)}
        </span>
        <span className="min-w-0 flex-1">
          <InlineLabel value={f.label} onCommit={onRename} />
          <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
            <span className="mono truncate text-2xs text-fg-subtle">{f.column}</span>
            {f.common && <Badge className="h-4 px-1.5">Standard</Badge>}
            {isValueField && (
              <Badge variant="accent" className="h-4 px-1.5">
                Wert
              </Badge>
            )}
            {inTemplate && (
              <Tooltip content="Wird in der Beschreibungs- oder Kommentarvorlage verwendet">
                <Badge variant="outline" className="h-4 px-1.5">
                  Vorlage
                </Badge>
              </Tooltip>
            )}
            {locked && (
              <Tooltip content={`Geschützt – ${lockReason}`}>
                <span className="flex shrink-0 text-fg-subtle" role="img" aria-label="geschütztes Feld">
                  <Lock aria-hidden className="size-3" />
                </span>
              </Tooltip>
            )}
          </span>
        </span>
      </span>

      <span role="cell" className="hidden min-w-0 truncate text-xs text-fg-muted @[40rem]:block" title={kindText(f, kinds)}>
        {kindText(f, kinds)}
      </span>

      <span role="cell" className="flex justify-center">
        <FlagToggle
          on={f.required}
          icon={<Asterisk />}
          label="Pflichtfeld"
          field={f.label}
          disabled={isPartNumber}
          disabledReason="Die Teilenummer ist immer Pflicht"
          onChange={(v) => onToggle('required', v)}
        />
      </span>
      <span role="cell" className="flex justify-center">
        <FlagToggle
          on={f.show_on_schematic}
          icon={<Eye />}
          label="Im Schaltplan sichtbar"
          field={f.label}
          onChange={(v) => onToggle('show_on_schematic', v)}
        />
      </span>
      <span role="cell" className="flex justify-center">
        <FlagToggle
          on={f.add_to_design}
          icon={<FileInput />}
          label="Ins Design übernehmen"
          field={f.label}
          disabled={locked}
          disabledReason="Bei geschützten Feldern fest"
          onChange={(v) => onToggle('add_to_design', v)}
        />
      </span>

      <span role="cell" className="flex items-center justify-end">
        <IconButton size="sm" label={`„${f.label}“ bearbeiten`} icon={<Pencil />} onClick={onEdit} />
        {locked ? (
          // Kein IconButton: dessen aria-disabled schaltet Zeigerereignisse ab – der Grund soll beim Überfahren erscheinen
          <Tooltip content={`„${f.label}“ kann nicht entfernt werden – ${lockReason}.`}>
            <button
              type="button"
              aria-disabled="true"
              aria-label={`„${f.label}“ entfernen (nicht möglich: geschütztes Feld)`}
              onClick={() => undefined}
              className="flex size-7 cursor-not-allowed items-center justify-center rounded-control text-fg-subtle opacity-40 outline-none focus-ring [&_svg]:size-3.5"
            >
              <Trash2 aria-hidden />
            </button>
          </Tooltip>
        ) : (
          <IconButton size="sm" label={`„${f.label}“ entfernen`} icon={<Trash2 />} className="hover:text-danger-text" onClick={onRemove} />
        )}
      </span>
    </Reorder.Item>
  )
}

function FlagToggle({
  on,
  icon,
  label,
  field,
  disabled,
  disabledReason,
  onChange,
}: {
  on: boolean
  icon: ReactNode
  label: string
  /** Beschriftung des Felds – für eindeutige Namen je Zeile */
  field: string
  disabled?: boolean
  disabledReason?: string
  onChange: (value: boolean) => void
}) {
  const tip = disabled ? `${label}: ${on ? 'ja' : 'nein'} – ${disabledReason}` : `${label}: ${on ? 'ja' : 'nein'}`
  return (
    <Tooltip content={tip}>
      <button
        type="button"
        aria-pressed={on}
        aria-label={`${label} – ${field}`}
        aria-disabled={disabled || undefined}
        onClick={() => {
          if (!disabled) onChange(!on)
        }}
        className={cn(
          'flex size-7 items-center justify-center rounded-control outline-none transition-colors focus-ring [&_svg]:size-3.5',
          on
            ? 'bg-surface-3 text-fg shadow-[inset_0_0_0_1px_var(--pf-line-control)]'
            : 'text-fg-subtle hover:bg-surface-2 hover:text-fg-muted',
          disabled && 'cursor-not-allowed opacity-50 hover:bg-transparent',
        )}
      >
        {icon}
      </button>
    </Tooltip>
  )
}

/** Beschriftung direkt in der Zeile ändern (Klick oder Enter, Enter speichert, Esc bricht ab) */
function InlineLabel({ value, onCommit }: { value: string; onCommit: (label: string) => void }) {
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(value)
  const cancelled = useRef(false)
  const buttonRef = useRef<HTMLButtonElement>(null)
  // Nach Enter/Esc zurück auf die Beschriftung (sonst landet der Fokus auf <body>)
  const refocus = useRef(false)
  useEffect(() => {
    if (!editing && refocus.current) {
      refocus.current = false
      buttonRef.current?.focus()
    }
  }, [editing])

  if (!editing) {
    return (
      <button
        ref={buttonRef}
        type="button"
        onClick={() => {
          setText(value)
          setEditing(true)
        }}
        title="Beschriftung ändern"
        aria-label={`Beschriftung „${value}“ ändern`}
        className="-mx-1 block max-w-full truncate rounded-sm px-1 text-left text-ui font-medium text-fg outline-none transition-colors hover:bg-surface-3/70 focus-ring"
      >
        {value}
      </button>
    )
  }
  const finish = () => {
    setEditing(false)
    if (cancelled.current) {
      cancelled.current = false
      return
    }
    const next = text.trim()
    if (next && next !== value) onCommit(next)
  }
  return (
    <input
      // eslint-disable-next-line jsx-a11y/no-autofocus -- Bearbeiten wurde gerade per Klick/Enter gestartet
      autoFocus
      value={text}
      onChange={(e) => setText(e.target.value)}
      onBlur={finish}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          refocus.current = true
          e.currentTarget.blur()
        } else if (e.key === 'Escape') {
          e.preventDefault()
          e.stopPropagation()
          cancelled.current = true
          refocus.current = true
          e.currentTarget.blur()
        }
      }}
      aria-label="Beschriftung"
      className="-mx-1 block h-6 w-full rounded-sm border border-accent bg-control px-1 text-ui font-medium text-fg outline-none shadow-[0_0_0_3px_var(--pf-accent-soft)]"
    />
  )
}
