/**
 * Seiten-Editor des IC-Symbols: Körper in der Mitte, Pins als Chips an den vier Seiten – so, wie der Generator sie
 * platziert (automatisch platzierte Pins stehen an ihrer berechneten Seite). Chips per Drag & Drop auf eine andere
 * Seite ziehen (legt die Seite fest), auf einen anderen Chip derselben Gruppe (Reihenfolge innerhalb der Seite)
 * oder auf „Automatisch“ (gibt die Seite wieder frei).
 *
 * Tastatur: Chip fokussieren und L/R/O/U drücken (links/rechts/oben/unten), A = automatisch, Alt+↑/↓ = früher bzw.
 * später auf der Seite; Enter öffnet das Menü (↑/↓ wählen, Enter übernimmt).
 */
import { EyeOff, Pin, Wand } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'
import type { GeneratedSpec, IcSide } from '@/api/symbols'
import { Popover, PopoverContent, PopoverTrigger, SegmentedControl } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { displayText, inPart, partLetter, spokenPinName, type SymPin } from '@/lib/geometry'
import { ElectricalDot, OverbarName } from '../shared'
import { SIDE_OF_ORIENTATION, icBodySize } from '../util'
import { ELECTRICAL_OPTIONS, SIDE_KEYS, SIDE_LABEL, type PinRow } from './pins'

export interface SideLayoutProps {
  pins: readonly PinRow[]
  spec: GeneratedSpec | undefined
  part: number
  onPartChange: (part: number) => void
  hoverDesignator: string | null
  onHover: (designator: string | null) => void
  onSetSide: (ids: string[], side: IcSide | null) => void
  /** Pin `id` vor bzw. hinter `targetId` auf Seite `side` setzen (Reihenfolge der Pinliste) */
  onPlace: (id: string, targetId: string, where: 'before' | 'after', side: IcSide) => void
  onShowInTable: (id: string) => void
  /** Vorschau wird gerade neu berechnet */
  stale?: boolean
}

type Zone = IcSide | 'auto'
const DRAG_TYPE = 'application/x-partforge-pin'
/** So lange darf ein per Tastatur verschobener Chip den Fokus zurückholen (er springt erst mit der Vorschau an seinen Platz) */
const REFOCUS_MS = 4000
/** Zeitstempel (nur in Ereignissen und Effekten aufgerufen) */
const now = () => Date.now()

interface Placed {
  row: PinRow
  sp: SymPin | undefined
  side: IcSide | null
  explicit: boolean
}

const ZONE_LABEL: Record<Zone, string> = { ...SIDE_LABEL, auto: 'Automatisch' }
const MENU_ORDER: { zone: Zone; key: string }[] = [
  { zone: 'auto', key: 'A' },
  { zone: 'left', key: 'L' },
  { zone: 'right', key: 'R' },
  { zone: 'top', key: 'O' },
  { zone: 'bottom', key: 'U' },
]

/** Gleicher Block des Generators (Rolle bzw. Gruppe) – nur dort bestimmt die Pinliste die Reihenfolge */
const sameBlock = (a: Placed, b: Placed) => Boolean(a.sp && b.sp && (a.sp.group ?? '') === (b.sp.group ?? ''))

function PinChip({
  item,
  zone,
  highlighted,
  dragging,
  dropMark,
  onDragStart,
  onDragEnd,
  onChipDragOver,
  onChipDrop,
  onHover,
  onMoveTo,
  onStep,
  onFocusChip,
  onShowInTable,
}: {
  item: Placed
  zone: Zone
  highlighted: boolean
  dragging: boolean
  /** Ablage-Markierung vor/hinter diesem Chip */
  dropMark: 'before' | 'after' | null
  onDragStart: (id: string, e: DragEvent<HTMLButtonElement>) => void
  onDragEnd: () => void
  onChipDragOver: (item: Placed, zone: Zone, e: DragEvent<HTMLButtonElement>) => void
  onChipDrop: (item: Placed, zone: Zone, e: DragEvent<HTMLButtonElement>) => void
  onHover: (designator: string | null) => void
  onMoveTo: (id: string, side: IcSide | null, viaKeyboard: boolean) => void
  onStep: (item: Placed, zone: Zone, delta: -1 | 1) => void
  onFocusChip: (id: string) => void
  onShowInTable: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const { row, explicit } = item
  const d = row.designator.trim() || '?'
  const typeLabel = ELECTRICAL_OPTIONS.find((o) => o.value === row.electrical)?.label ?? row.electrical
  const where = explicit ? `Seite festgelegt: ${SIDE_LABEL[row.side as IcSide]}` : `automatisch${item.side ? `, ${SIDE_LABEL[item.side].toLowerCase()}` : ''}`
  const vertical = zone === 'left' || zone === 'right' || zone === 'auto'

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault()
      onStep(item, zone, e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 1)
      return
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return
    const key = e.key.toLowerCase()
    if (key in SIDE_KEYS) {
      e.preventDefault()
      onMoveTo(row.id, SIDE_KEYS[key], true)
    }
  }

  /** Menü: ↑/↓/Pos1/Ende wandern durch die Einträge, Buchstaben wählen direkt */
  const onMenuKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const key = e.key.toLowerCase()
    if (!e.ctrlKey && !e.metaKey && !e.altKey && key in SIDE_KEYS) {
      e.preventDefault()
      setOpen(false)
      onMoveTo(row.id, SIDE_KEYS[key], true)
      return
    }
    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitemradio"], [role="menuitem"]') ?? [])]
    const i = items.indexOf(document.activeElement as HTMLElement)
    let next = -1
    if (e.key === 'ArrowDown') next = (i + 1) % items.length
    else if (e.key === 'ArrowUp') next = (i - 1 + items.length) % items.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = items.length - 1
    if (next >= 0) {
      e.preventDefault()
      items[next]?.focus()
    }
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-chip={row.id}
          draggable
          aria-label={`Pin ${d}${row.name ? ` ${spokenPinName(row.name)}` : ''}, ${typeLabel}, ${where}${row.hidden ? ', verborgen' : ''}`}
          aria-keyshortcuts="L R O U A Alt+ArrowUp Alt+ArrowDown"
          onDragStart={(e) => onDragStart(row.id, e)}
          onDragEnd={onDragEnd}
          onDragOver={(e) => onChipDragOver(item, zone, e)}
          onDrop={(e) => onChipDrop(item, zone, e)}
          onMouseEnter={() => onHover(row.designator.trim() || null)}
          onMouseLeave={() => onHover(null)}
          onFocus={() => {
            onHover(row.designator.trim() || null)
            onFocusChip(row.id)
          }}
          onBlur={() => onHover(null)}
          onKeyDown={onKeyDown}
          className={cn(
            'group/chip relative flex h-7 max-w-full cursor-grab items-center gap-1.5 rounded-control border bg-surface pl-2 pr-1.5 text-xs shadow-card outline-none transition-[border-color,background-color,box-shadow,opacity] duration-150 focus-ring active:cursor-grabbing',
            highlighted ? 'border-accent bg-accent-soft shadow-glow' : 'border-line-strong hover:border-line-control',
            (row.hidden || zone === 'auto') && 'border-dashed',
            dragging && 'opacity-35',
          )}
        >
          {dropMark && (
            <span
              aria-hidden
              className={cn(
                'pointer-events-none absolute rounded-full bg-accent shadow-glow',
                vertical
                  ? cn('inset-x-1 h-0.5', dropMark === 'before' ? '-top-[3px]' : '-bottom-[3px]')
                  : cn('inset-y-1 w-0.5', dropMark === 'before' ? '-left-[3px]' : '-right-[3px]'),
              )}
            />
          )}
          <ElectricalDot type={row.electrical} />
          <span className="mono shrink-0 font-semibold text-fg">{d}</span>
          <OverbarName value={row.name} placeholder="–" className="mono min-w-0 truncate pt-px leading-5 text-fg-muted" />
          {row.hidden && <EyeOff aria-hidden className="size-3 shrink-0 text-fg-subtle" />}
          {explicit && <Pin aria-hidden className="size-3 shrink-0 rotate-45 text-accent-text" />}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-60 p-1.5" align="center" onKeyDown={onMenuKeyDown}>
        <div className="flex items-center gap-2 px-2 pb-1.5 pt-1">
          <ElectricalDot type={row.electrical} />
          <span className="mono text-xs font-semibold text-fg">{d}</span>
          <OverbarName value={row.name} className="mono truncate text-xs text-fg-muted" />
        </div>
        <div ref={menuRef} role="menu" aria-label={`Seite für Pin ${d}`} className="flex flex-col">
          {MENU_ORDER.map(({ zone: z, key }) => {
            const checked = z === 'auto' ? !explicit : row.side === z
            return (
              <button
                key={z}
                type="button"
                role="menuitemradio"
                aria-checked={checked}
                aria-keyshortcuts={key}
                tabIndex={checked ? 0 : -1}
                onClick={() => {
                  setOpen(false)
                  onMoveTo(row.id, z === 'auto' ? null : z, true)
                }}
                className={cn(
                  'flex h-8 items-center gap-2.5 rounded-control px-2 text-left text-ui outline-none transition-colors hover:bg-surface-3 focus-visible:bg-surface-3 focus-visible:text-fg',
                  checked ? 'text-fg' : 'text-fg-muted',
                )}
              >
                <span aria-hidden className={cn('flex size-3.5 items-center justify-center rounded-full border', checked ? 'border-accent' : 'border-line-control')}>
                  {checked && <span className="size-1.5 rounded-full bg-accent" />}
                </span>
                <span className="flex-1">
                  {ZONE_LABEL[z]}
                  {z === 'auto' && !explicit && item.side && <span className="text-fg-subtle"> · {SIDE_LABEL[item.side].toLowerCase()}</span>}
                </span>
                <kbd aria-hidden className="rounded-sm border border-line-strong px-1 font-sans text-2xs text-fg-subtle">
                  {key}
                </kbd>
              </button>
            )
          })}
          <div aria-hidden className="my-1 h-px bg-line" />
          <button
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={() => {
              setOpen(false)
              onShowInTable(row.id)
            }}
            className="flex h-8 w-full items-center rounded-control px-2 text-left text-ui text-fg-muted outline-none transition-colors hover:bg-surface-3 hover:text-fg focus-visible:bg-surface-3 focus-visible:text-fg"
          >
            In der Pinliste zeigen
          </button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

export function SideLayout({ pins, spec, part, onPartChange, hoverDesignator, onHover, onSetSide, onPlace, onShowInTable, stale }: SideLayoutProps) {
  const [dragId, setDragId] = useState<string | null>(null)
  const [over, setOver] = useState<Zone | null>(null)
  const [mark, setMark] = useState<{ id: string; where: 'before' | 'after' } | null>(null)
  const [announce, setAnnounce] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  /** Chip, der nach einer Tastatur-Aktion den Fokus behalten soll (wird beim Umsortieren neu eingehängt) */
  const refocusRef = useRef<{ id: string; until: number } | null>(null)
  const partCount = Math.max(1, spec?.part_count ?? 1)
  const current = Math.min(part, partCount)

  const zones = useMemo(() => {
    const bySpec = new Map((spec?.pins ?? []).map((p) => [p.designator, p]))
    const out: Record<Zone, Placed[]> = { left: [], right: [], top: [], bottom: [], auto: [] }
    for (const row of pins) {
      const sp = bySpec.get(row.designator.trim())
      const partOf = sp ? sp.part : row.part
      if (!inPart(partOf, current)) continue
      const side = row.side ?? (sp ? SIDE_OF_ORIENTATION[sp.orientation] : null)
      const item: Placed = { row, sp, side, explicit: row.side !== null }
      out[side ?? 'auto'].push(item)
    }
    const pos = (it: Placed, key: 'x' | 'y', dir: 1 | -1) => (it.sp ? it.sp[key] * dir : Number.MAX_SAFE_INTEGER)
    out.left.sort((a, b) => pos(a, 'y', -1) - pos(b, 'y', -1))
    out.right.sort((a, b) => pos(a, 'y', -1) - pos(b, 'y', -1))
    out.top.sort((a, b) => pos(a, 'x', 1) - pos(b, 'x', 1))
    out.bottom.sort((a, b) => pos(a, 'x', 1) - pos(b, 'x', 1))
    return out
  }, [pins, spec, current])

  // Ein per Tastatur verschobener Chip wird in einer anderen Spalte neu eingehängt und verliert dabei den Fokus –
  // ihn nur dann zurückholen, wenn der Fokus verloren ging (nie einem anderen Element wegnehmen). Jeder Klick und
  // jeder Fokus auf einen anderen Chip beendet das.
  useEffect(() => {
    const r = refocusRef.current
    if (!r) return
    if (now() > r.until) {
      refocusRef.current = null
      return
    }
    const active = document.activeElement
    const el = rootRef.current?.querySelector<HTMLElement>(`[data-chip="${CSS.escape(r.id)}"]`)
    if (!el || active === el) return
    if (!active || active === document.body) el.focus()
    else refocusRef.current = null
  }, [zones])
  useEffect(() => {
    const clear = () => {
      refocusRef.current = null
    }
    window.addEventListener('pointerdown', clear, true)
    return () => window.removeEventListener('pointerdown', clear, true)
  }, [])
  const keepFocus = (id: string) => {
    refocusRef.current = { id, until: now() + REFOCUS_MS }
  }

  const describe = (row: PinRow) => `Pin ${row.designator}${row.name ? ` ${displayText(row.name)}` : ''}`

  const moveTo = (id: string, side: IcSide | null, viaKeyboard: boolean) => {
    const row = pins.find((p) => p.id === id)
    if (!row) return
    if (row.side !== side) onSetSide([id], side)
    setAnnounce(`${describe(row)}: ${side ? SIDE_LABEL[side] : 'automatisch'}`)
    if (viaKeyboard) keepFocus(id)
  }

  /** Alt+↑/↓: mit dem Nachbarn derselben Gruppe auf dieser Seite tauschen */
  const step = (item: Placed, zone: Zone, delta: -1 | 1) => {
    if (zone === 'auto') return
    const list = zones[zone]
    const i = list.findIndex((p) => p.row.id === item.row.id)
    const neighbour = list[i + delta]
    if (!neighbour || !sameBlock(item, neighbour)) {
      setAnnounce(`${describe(item.row)}: ${delta < 0 ? 'schon zuoberst' : 'schon zuunterst'} in seiner Gruppe`)
      return
    }
    onPlace(item.row.id, neighbour.row.id, delta < 0 ? 'before' : 'after', zone)
    setAnnounce(`${describe(item.row)} ${delta < 0 ? 'vor' : 'hinter'} ${describe(neighbour.row)}`)
    keepFocus(item.row.id)
  }

  const endDrag = () => {
    setDragId(null)
    setOver(null)
    setMark(null)
  }

  const dropHandlers = (zone: Zone) => ({
    onDragOver: (e: DragEvent<HTMLDivElement>) => {
      if (!e.dataTransfer.types.includes(DRAG_TYPE)) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      if (over !== zone) setOver(zone)
    },
    onDragLeave: (e: DragEvent<HTMLDivElement>) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver((z) => (z === zone ? null : z))
    },
    onDrop: (e: DragEvent<HTMLDivElement>) => {
      const id = e.dataTransfer.getData(DRAG_TYPE)
      if (!id) return
      e.preventDefault()
      endDrag()
      moveTo(id, zone === 'auto' ? null : zone, false)
    },
  })

  const dragged = useMemo(() => {
    if (!dragId) return null
    for (const list of Object.values(zones)) {
      const hit = list.find((p) => p.row.id === dragId)
      if (hit) return hit
    }
    return null
  }, [dragId, zones])

  /** Ablage auf einem Chip derselben Gruppe: davor/dahinter einsortieren (Mitte des Chips entscheidet) */
  const chipDropPosition = (target: Placed, zone: Zone, e: DragEvent<HTMLButtonElement>): 'before' | 'after' | null => {
    if (zone === 'auto' || !dragged || dragged.row.id === target.row.id || !sameBlock(dragged, target)) return null
    const r = e.currentTarget.getBoundingClientRect()
    const vertical = zone === 'left' || zone === 'right'
    return (vertical ? e.clientY - r.top < r.height / 2 : e.clientX - r.left < r.width / 2) ? 'before' : 'after'
  }
  const onChipDragOver = (target: Placed, zone: Zone, e: DragEvent<HTMLButtonElement>) => {
    const where = chipDropPosition(target, zone, e)
    if (!where) {
      if (mark) setMark(null)
      return
    }
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'move'
    if (over !== zone) setOver(zone)
    if (mark?.id !== target.row.id || mark.where !== where) setMark({ id: target.row.id, where })
  }
  const onChipDrop = (target: Placed, zone: Zone, e: DragEvent<HTMLButtonElement>) => {
    const where = chipDropPosition(target, zone, e)
    if (!where || !dragged || zone === 'auto') return
    e.preventDefault()
    e.stopPropagation()
    endDrag()
    onPlace(dragged.row.id, target.row.id, where, zone)
    setAnnounce(`${describe(dragged.row)} ${where === 'before' ? 'vor' : 'hinter'} ${describe(target.row)}`)
  }

  const chip = (it: Placed, zone: Zone) => (
    <PinChip
      key={it.row.id}
      item={it}
      zone={zone}
      highlighted={hoverDesignator !== null && it.row.designator.trim() === hoverDesignator}
      dragging={dragId === it.row.id}
      dropMark={mark?.id === it.row.id ? mark.where : null}
      onDragStart={(id, e) => {
        e.dataTransfer.setData(DRAG_TYPE, id)
        e.dataTransfer.effectAllowed = 'move'
        refocusRef.current = null
        setDragId(id)
      }}
      onDragEnd={endDrag}
      onChipDragOver={onChipDragOver}
      onChipDrop={onChipDrop}
      onHover={onHover}
      onMoveTo={moveTo}
      onStep={step}
      onFocusChip={(id) => {
        if (refocusRef.current && refocusRef.current.id !== id) refocusRef.current = null
      }}
      onShowInTable={onShowInTable}
    />
  )

  const zoneBox = (zone: Zone, children: ReactNode, className?: string) => {
    const count = zones[zone].length
    return (
      <div
        role="group"
        aria-label={`${ZONE_LABEL[zone]}: ${plural(count, 'Pin', 'Pins')}`}
        data-zone={zone}
        {...dropHandlers(zone)}
        className={cn(
          'relative rounded-card border border-dashed p-2 transition-[border-color,background-color,box-shadow] duration-150',
          over === zone
            ? 'border-accent bg-accent-soft/50 shadow-[0_0_0_3px_var(--pf-accent-soft)]'
            : dragId
              ? 'border-line-control bg-surface-2/40'
              : 'border-transparent',
          className,
        )}
      >
        {children}
      </div>
    )
  }

  const header = (zone: Zone, align: 'start' | 'end' | 'center') => (
    <>
      <div className={cn('mb-1.5 flex items-center gap-1.5 px-0.5', align === 'end' ? 'justify-end' : align === 'center' ? 'justify-center' : 'justify-start')}>
        <span className="micro-label">{ZONE_LABEL[zone]}</span>
        <span className="text-2xs tabular-nums text-fg-subtle">{formatNumber(zones[zone].length)}</span>
      </div>
      {zones[zone].length === 0 && (
        <p className={cn('px-0.5 text-2xs text-fg-subtle', align === 'end' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left')}>
          {dragId ? 'Hier ablegen' : 'leer – Pins hierher ziehen'}
        </p>
      )}
    </>
  )

  const body = icBodySize(spec)
  const total = zones.left.length + zones.right.length + zones.top.length + zones.bottom.length + zones.auto.length
  const fixed = [...zones.left, ...zones.right, ...zones.top, ...zones.bottom, ...zones.auto].filter((p) => p.explicit).length
  const designator = `${spec?.designator_prefix ?? 'U'}?${partCount > 1 ? partLetter(current) : ''}`

  return (
    <div ref={rootRef} className="flex flex-col gap-3 p-4">
      {partCount > 1 && (
        <div className="flex items-center gap-3">
          <SegmentedControl
            size="sm"
            aria-label="Teil des Symbols"
            value={String(current)}
            onValueChange={(v) => onPartChange(Number(v))}
            options={Array.from({ length: partCount }, (_, i) => ({ value: String(i + 1), label: <span className="mono">{partLetter(i + 1)}</span> }))}
          />
          <span className="text-xs text-fg-muted">
            Teil {partLetter(current)} von {formatNumber(partCount)} – Pins mit Teil 0 erscheinen in jedem Teil.
          </span>
        </div>
      )}

      <div
        className={cn(
          'grid grid-cols-[minmax(9rem,1fr)_minmax(9rem,1.15fr)_minmax(9rem,1fr)] grid-rows-[auto_1fr_auto] gap-2 transition-opacity',
          stale && 'opacity-80',
        )}
      >
        {zoneBox('top', <>{header('top', 'center')}<div className="flex flex-wrap justify-center gap-1">{zones.top.map((p) => chip(p, 'top'))}</div></>, 'col-start-2 row-start-1 min-h-[4.5rem]')}
        {zoneBox('left', <>{header('left', 'end')}<div className="flex flex-col items-end gap-1">{zones.left.map((p) => chip(p, 'left'))}</div></>, 'col-start-1 row-start-2 min-h-40')}
        <div className="col-start-2 row-start-2 flex min-h-40 flex-col items-center justify-center gap-1 rounded-button border-2 border-[color-mix(in_oklab,var(--pf-sym-line)_55%,transparent)] bg-sym-body px-3 py-4 text-center">
          <span className="mono text-ui font-semibold text-fg">{designator}</span>
          <span className="mono max-w-full truncate text-xs text-fg-muted">{spec?.name ?? '–'}</span>
          <span className="mt-1 text-2xs text-fg-subtle">
            {plural(total, 'Pin', 'Pins')} · {formatNumber(fixed)} festgelegt
          </span>
          {body && (
            <span className="mono text-2xs text-fg-subtle">
              {formatNumber(body.width)} × {formatNumber(body.height)} mil
            </span>
          )}
        </div>
        {zoneBox('right', <>{header('right', 'start')}<div className="flex flex-col items-start gap-1">{zones.right.map((p) => chip(p, 'right'))}</div></>, 'col-start-3 row-start-2 min-h-40')}
        {zoneBox('bottom', <>{header('bottom', 'center')}<div className="flex flex-wrap justify-center gap-1">{zones.bottom.map((p) => chip(p, 'bottom'))}</div></>, 'col-start-2 row-start-3 min-h-[4.5rem]')}
      </div>

      {zoneBox(
        'auto',
        <div className="flex flex-wrap items-center gap-2">
          <Wand aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
          <span className="text-xs text-fg-muted">
            {zones.auto.length
              ? 'Wird platziert …'
              : 'Hierher ziehen (oder Taste A), um die Seite wieder automatisch bestimmen zu lassen.'}
          </span>
          {zones.auto.map((p) => chip(p, 'auto'))}
        </div>,
        cn('border-line-strong', over !== 'auto' && !dragId && 'border-line'),
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-fg-subtle">
        <span className="flex items-center gap-1">
          <Pin aria-hidden className="size-3 rotate-45 text-accent-text" /> Seite festgelegt
        </span>
        <span>ohne Nadel: automatisch platziert</span>
        <span className="flex items-center gap-1">
          <EyeOff aria-hidden className="size-3" /> verborgen
        </span>
        <span className="ml-auto">Ziehen oder Chip fokussieren: L, R, O, U, A wechseln die Seite, Alt+↑/↓ sortiert innerhalb der Gruppe</span>
      </div>
      <div className="sr-only" aria-live="polite">
        {announce}
      </div>
    </div>
  )
}
