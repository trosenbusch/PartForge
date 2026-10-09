/**
 * Herstellerempfehlung (Land Pattern aus dem Datenblatt) statt IPC-Berechnung: Padbreite, Padlänge,
 * Reihenabstand mit Bezug (Mitte–Mitte C, Innenkante G, Außenkante Z), optional Reihenabstand oben/unten und
 * Exposed Pad. Beim Einschalten werden die aktuellen IPC-Werte übernommen – dann nur noch anpassen.
 */
import { ChevronRight } from 'lucide-react'
import { useId } from 'react'
import { CHROME_MUTED } from '@/components/preview'
import { NumberInput, SegmentedControl, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { LandRecord } from '../lib/calc'
import { landPatternIncomplete } from '../lib/request'
import type { LandPatternState, LandReference } from './store'
import { useFootprintUi } from './uiPrefs'

const REFERENCES: { value: LandReference; label: string; title: string }[] = [
  { value: 'center', label: 'Mitte (C)', title: 'Reihenabstand von Padmitte zu Padmitte' },
  { value: 'inner', label: 'Innen (G)', title: 'Abstand der inneren Padkanten' },
  { value: 'outer', label: 'Außen (Z)', title: 'Abstand der äußeren Padkanten' },
]

export interface LandPatternSectionProps {
  state: LandPatternState
  onChange: (patch: Partial<LandPatternState>, mode?: 'typing' | 'discrete') => void
  /** Aktuelle IPC-Lötflächen (zum Vorbelegen beim Einschalten) */
  lands: readonly LandRecord[]
  /** Exposed Pad vorhanden (Größe zum Vorbelegen) */
  exposedPad: { width: number; height: number } | null
  /** Familie berechnet ihre Pads immer nach IPC (Backend-Kennzeichen bzw. Rechenprotokoll ohne Herstellerwerte) */
  unsupported: boolean
}

export function LandPatternSection({ state, onChange, lands, exposedPad, unsupported }: LandPatternSectionProps) {
  const id = useId()
  const collapsedPref = useFootprintUi((s) => s.collapsed['land-pattern'])
  const setCollapsed = useFootprintUi((s) => s.setCollapsed)
  const open = state.enabled || collapsedPref === false
  const quad = lands.length > 1 && lands.some((l) => l.axis === 'y')

  const enable = (on: boolean) => {
    if (!on) {
      onChange({ enabled: false }, 'discrete')
      return
    }
    const first = lands.find((l) => l.axis === 'x') ?? lands[0]
    const second = lands.find((l) => l.axis === 'y')
    const empty = state.pad_width === null && state.pad_length === null && state.row_spacing === null
    onChange(
      empty && first
        ? {
            enabled: true,
            pad_width: round(first.x),
            pad_length: round(first.padLength),
            row_spacing: round(2 * first.padCenter),
            reference: 'center',
            row_spacing_y: second ? round(2 * second.padCenter) : null,
            ep_width: exposedPad ? round(exposedPad.width) : null,
            ep_length: exposedPad ? round(exposedPad.height) : null,
          }
        : { enabled: true },
      'discrete',
    )
  }

  const num = (key: keyof LandPatternState, label: string, optional = false) => (
    <label className="flex min-w-0 flex-col gap-1">
      <span className="truncate text-2xs text-fg-muted">
        {label}
        {optional && <span className="text-fg-subtle"> · optional</span>}
      </span>
      <NumberInput
        size="sm"
        unit="mm"
        decimals={3}
        step={0.01}
        min={0}
        allowEmpty
        disabled={!state.enabled}
        value={state[key] as number | null}
        onValueChange={(v) => onChange({ [key]: v } as Partial<LandPatternState>, 'discrete')}
        aria-label={label}
      />
    </label>
  )

  return (
    <section aria-labelledby={`${id}-title`} className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={`${id}-body`}
          onClick={() => setCollapsed('land-pattern', open)}
          disabled={state.enabled}
          className="group/lp -mx-1.5 flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-control px-1.5 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset disabled:cursor-default disabled:hover:bg-transparent"
        >
          <ChevronRight aria-hidden className={cn('size-3.5 shrink-0 text-fg-subtle transition-transform', open && 'rotate-90')} />
          <span id={`${id}-title`} className="micro-label text-fg-muted">
            Herstellerempfehlung
          </span>
        </button>
        <Switch size="sm" aria-label="Land Pattern des Herstellers verwenden" checked={state.enabled} onCheckedChange={enable} />
      </div>
      {open && (
        <div id={`${id}-body`} className="flex flex-col gap-2.5">
          <p className="text-2xs leading-4 text-fg-muted">
            Padmaße aus dem Datenblatt statt IPC-7351-Berechnung. Beim Einschalten werden die aktuellen Werte übernommen.
          </p>
          {unsupported && state.enabled && (
            <p className="rounded-control border border-warning/30 bg-warning/8 px-2.5 py-1.5 text-2xs leading-4 text-warning-text">
              Diese Gehäusefamilie berechnet ihre Pads immer nach IPC – die Herstellerempfehlung wird ignoriert.
            </p>
          )}
          <div className="grid grid-cols-2 gap-2">
            {num('pad_width', 'Padbreite X')}
            {num('pad_length', 'Padlänge Y')}
          </div>
          <div className="flex flex-col gap-1">
            <div className="grid grid-cols-2 gap-2">{num('row_spacing', 'Reihenabstand')}</div>
            <SegmentedControl
              size="sm"
              fullWidth
              aria-label="Bezug des Reihenabstands"
              disabled={!state.enabled}
              value={state.reference}
              onValueChange={(v) => onChange({ reference: v }, 'discrete')}
              options={REFERENCES.map((r) => ({ value: r.value, label: r.label }))}
            />
            <ReferenceDiagram reference={state.reference} dimmed={!state.enabled} />
          </div>
          {(quad || state.row_spacing_y !== null) && <div className="grid grid-cols-2 gap-2">{num('row_spacing_y', 'Abstand oben/unten', true)}</div>}
          {(exposedPad || state.ep_width !== null) && (
            <div className="grid grid-cols-2 gap-2">
              {num('ep_width', 'Exposed Pad X', true)}
              {num('ep_length', 'Exposed Pad Y', true)}
            </div>
          )}
          {landPatternIncomplete(state) && (
            <p role="status" className="text-2xs leading-4 text-warning-text">
              Padbreite, Padlänge und Reihenabstand angeben – bis dahin rechnet der Generator nach IPC.
            </p>
          )}
        </div>
      )}
    </section>
  )
}

const round = (v: number) => Math.round(v * 1000) / 1000

/**
 * Skizze: zwei Pads mit den Bezugsmaßen C, G, Z – der gewählte Bezug leuchtet in Kupfer. Die Leiterplatte ist in
 * beiden Themes dunkel; die übrigen Bezüge stehen deshalb in der gedämpften Leinwandfarbe (≥ 4,5:1).
 */
function ReferenceDiagram({ reference, dimmed }: { reference: LandReference; dimmed: boolean }) {
  const on = (r: LandReference) => (r === reference ? 'var(--pf-accent)' : 'currentColor')
  const op = (r: LandReference) => (r === reference ? 1 : 0.9)
  const arrow = (x1: number, x2: number, y: number, r: LandReference, label: string) => (
    <g stroke={on(r)} fill={on(r)} opacity={op(r)}>
      <path d={`M ${x1 + 4} ${y} H ${x2 - 4}`} strokeWidth={1} />
      <path d={`M ${x1} ${y} l 5 -2.6 v 5.2 Z M ${x2} ${y} l -5 -2.6 v 5.2 Z`} stroke="none" />
      <text
        x={(x1 + x2) / 2}
        y={y - 3.5}
        textAnchor="middle"
        fontSize={9}
        fontWeight={700}
        stroke="none"
        style={{ fontFamily: 'var(--font-mono)' }}
      >
        {label}
      </text>
    </g>
  )
  return (
    <svg
      viewBox="0 0 220 74"
      aria-hidden
      className={cn('mt-1 h-auto w-full rounded-control border border-line bg-canvas', CHROME_MUTED.board, dimmed && 'opacity-60')}
    >
      <rect x="34" y="24" width="44" height="26" rx="3" fill="var(--pf-pcb-top)" opacity="0.88" />
      <rect x="142" y="24" width="44" height="26" rx="3" fill="var(--pf-pcb-top)" opacity="0.88" />
      <path d="M56 20v48M164 20v48" stroke="currentColor" strokeOpacity="0.45" strokeDasharray="2 2" />
      <path d="M34 13v12M186 13v12M78 30v14M142 30v14" stroke="currentColor" strokeOpacity="0.4" />
      {arrow(34, 186, 14, 'outer', 'Z')}
      {arrow(78, 142, 37, 'inner', 'G')}
      {arrow(56, 164, 64, 'center', 'C')}
    </svg>
  )
}
