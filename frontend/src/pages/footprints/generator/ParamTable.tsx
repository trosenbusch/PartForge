/**
 * Maßtabelle wie im Datenblatt: Symbol (E, E1, D, L, b …), Bezeichnung und Min · Nom · Max in mm.
 *
 * Toleranzfelder verstehen Freitext – „0,25±0,05“, „0,20…0,30“, „0,20 0,25 0,30“, „max 1,75“ – in jeder Zelle
 * (auch beim Einfügen) und füllen die ganze Zeile; beim Tippen eines Ausdrucks wird das Feld zeilenbreit. ↑/↓ ändern
 * um 0,01 mm (⇧ 0,1 · Strg 0,001), Esc stellt den Wert vor dem Bearbeiten wieder her, Strg+Z nimmt Schritte zurück.
 * Jede Änderung geht sofort (entprellt) an die Live-Vorschau. Leere Felder zeigen den wirksamen Wert grau.
 */
import { ChevronRight, RotateCcw } from 'lucide-react'
import { Popover as PopoverPrimitive } from 'radix-ui'
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { FootprintFamily, FootprintParamSpec } from '@/api/footprints'
import { Input, SegmentedControl, Select, Switch, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { pinStep, stepToGrid } from '../lib/families'
import {
  defaultValue,
  EMPTY_TOL,
  effectiveTol,
  enumLabel,
  enumShortLabel,
  formatDim,
  formatPlain,
  groupParams,
  isEmptyTol,
  isTolExpression,
  isTolValue,
  normalizeParam,
  parseNumber,
  parseTolText,
  softHyphenate,
  splitLabel,
  tolProblem,
  type ParamGroup,
  type ParamValue,
  type ParamValues,
  type TolValue,
} from '../lib/params'
import { SectionLabel } from '../parts'
import { undoWithFeedback, type ChangeKind } from './store'
import { useFootprintUi } from './uiPrefs'

type Part = 'min' | 'nom' | 'max'
const PARTS: Part[] = ['min', 'nom', 'max']
const PART_LABEL: Record<Part, string> = { min: 'Minimum', nom: 'Nennwert', max: 'Maximum' }
const FREE_TEXT_HELP = 'Freitext: 0,25±0,05 · 0,20…0,30 · max 1,75 · ↑↓ ±0,01'

export interface ParamChangeOptions {
  mode?: ChangeKind
  /** Selektor-Logik (passende Vorlage) anwenden – erst beim Abschließen der Eingabe */
  commit?: boolean
}

export interface ParamTableProps {
  family: FootprintFamily
  values: ParamValues
  /** Wirksame Werte der letzten Vorschau (`spec.generator.params`) – Platzhalter leerer Felder */
  resolved: Record<string, unknown> | null
  /** Ersatz-Platzhalter, wenn das Backend nichts aufgelöst hat (Hausstil, IPC-Werte) */
  fallbacks: Record<string, ParamValue | string>
  /** Parameter, die in der aktuellen Fehlermeldung vorkommen */
  errorParams: ReadonlySet<string>
  /** Parameter, die von der Vorlage abweichen */
  changed: ReadonlySet<string>
  onChange: (name: string, value: ParamValue, opts?: ParamChangeOptions) => void
  onReset: (name: string) => void
}

const round = (v: number, digits = 4) => Math.round(v * 10 ** digits) / 10 ** digits

function hasValue(v: ParamValue | undefined): boolean {
  if (v === null || v === undefined || v === '') return false
  if (isTolValue(v)) return !isEmptyTol(v)
  return true
}

/** Standard: aufgeklappt – außer Name/Erweitert und ein leeres Exposed Pad */
function defaultOpen(group: ParamGroup, values: ParamValues, resolved: Record<string, unknown> | null): boolean {
  const anySet = group.params.some((p) => hasValue(values[p.name]))
  if (anySet) return true
  if (group.id === 'Name' || group.id === 'Erweitert') return false
  if (group.id === 'Exposed Pad') {
    const e2 = resolved?.E2 as { max?: number } | number | undefined
    const size = typeof e2 === 'number' ? e2 : e2?.max
    return Boolean(size && size > 0)
  }
  return true
}

/** Strg+Z / Strg+Y in den Feldern: Schritte des Generators statt Text-Rückgängig (die Felder sind gesteuert) */
function historyKey(e: KeyboardEvent<HTMLElement>, before?: () => void): boolean {
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return false
  const key = e.key.toLowerCase()
  if (key !== 'z' && key !== 'y') return false
  e.preventDefault()
  before?.()
  undoWithFeedback(key === 'y' || e.shiftKey ? 'redo' : 'undo')
  return true
}

export function ParamTable({ family, values, resolved, fallbacks, errorParams, changed, onChange, onReset }: ParamTableProps) {
  const groups = groupParams(family.params)
  const collapsed = useFootprintUi((s) => s.collapsed)
  const setCollapsed = useFootprintUi((s) => s.setCollapsed)

  // Eine ruhige Ansage für Vorleser (entprellt), statt bei jedem Tastendruck eine neue Statusmeldung
  const [live, setLive] = useState('')
  const liveTimer = useRef<number | undefined>(undefined)
  const announce = (text: string) => {
    window.clearTimeout(liveTimer.current)
    liveTimer.current = window.setTimeout(() => setLive(text), 700)
  }
  useEffect(() => () => window.clearTimeout(liveTimer.current), [])

  return (
    <section aria-labelledby="fp-params-label" className="flex flex-col [--ctl:9.25rem] @[21rem]/input:[--ctl:10.5rem]">
      <div className="sticky top-0 z-[2] -mx-4 flex items-end gap-2 border-b border-line bg-surface/95 px-4 pb-1.5 pt-2 backdrop-blur-sm">
        <SectionLabel id="fp-params-label" className="min-w-0 flex-1">
          Maße
        </SectionLabel>
        <div aria-hidden className="grid w-[var(--ctl)] shrink-0 grid-cols-3 pr-px text-right">
          {['min', 'nom', 'max'].map((p) => (
            <span key={p} className="micro-label pr-1.5">
              {p}
            </span>
          ))}
        </div>
      </div>
      <div className="flex flex-col">
        {groups.map((group) => {
          const pref = collapsed[group.id]
          const open = pref === undefined ? defaultOpen(group, values, resolved) : !pref
          const setCount = group.params.filter((p) => hasValue(values[p.name])).length
          return (
            <GroupView key={group.id} group={group} open={open} setCount={setCount} onToggle={() => setCollapsed(group.id, open)}>
              {group.params.map((spec) => (
                <ParamRow
                  key={spec.name}
                  spec={spec}
                  value={values[spec.name] ?? null}
                  resolved={resolved?.[spec.name]}
                  fallback={fallbacks[spec.name]}
                  error={errorParams.has(spec.name)}
                  changed={changed.has(spec.name)}
                  intStep={spec.name === 'pins' && spec.kind === 'int' ? pinStep(family, values) : 1}
                  announce={announce}
                  onChange={(v, opts) => onChange(spec.name, v, opts)}
                  onReset={() => onReset(spec.name)}
                />
              ))}
            </GroupView>
          )
        })}
      </div>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {live}
      </div>
    </section>
  )
}

function GroupView({
  group,
  open,
  setCount,
  onToggle,
  children,
}: {
  group: ParamGroup
  open: boolean
  setCount: number
  onToggle: () => void
  children: ReactNode
}) {
  const id = useId()
  return (
    <div role="group" aria-labelledby={id} className="flex flex-col">
      <button
        id={id}
        type="button"
        aria-expanded={open}
        onClick={onToggle}
        className="group/gh -mx-1.5 mt-1.5 flex h-7 items-center gap-1.5 rounded-control px-1.5 text-left outline-none transition-colors hover:bg-surface-2 focus-ring-inset"
      >
        <ChevronRight aria-hidden className={cn('size-3.5 shrink-0 text-fg-subtle transition-transform duration-150', open && 'rotate-90')} />
        <span className="micro-label text-fg-muted">{group.label}</span>
        {!open && setCount > 0 && (
          <span className="rounded-full bg-surface-3 px-1.5 text-2xs leading-4 tabular-nums text-fg-muted">{setCount}</span>
        )}
        <span aria-hidden className="ml-1 h-px flex-1 bg-line" />
      </button>
      {open && <div className="flex flex-col gap-px pb-1">{children}</div>}
    </div>
  )
}

// --------------------------------------------------------------------------- Zeile

interface RowProps {
  spec: FootprintParamSpec
  value: ParamValue
  resolved: unknown
  fallback: ParamValue | string | undefined
  error: boolean
  changed: boolean
  /** Schrittweite ganzzahliger Werte (Pinzahl zweireihiger Gehäuse: 2) */
  intStep: number
  announce: (text: string) => void
  onChange: (value: ParamValue, opts?: ParamChangeOptions) => void
  onReset: () => void
}

function ParamRow({ spec, value, resolved, fallback, error, changed, intStep, announce, onChange, onReset }: RowProps) {
  const labelId = useId()
  const helpId = useId()
  const issueId = useId()
  const { symbol, text } = splitLabel(spec)
  const tolIssue = spec.kind === 'tol' && isTolValue(value) ? tolProblem(value) : null
  const describedBy = [spec.help || spec.kind === 'tol' ? helpId : null, tolIssue ? issueId : null].filter(Boolean).join(' ') || undefined

  const labelText = (
    <span
      id={labelId}
      lang="de"
      className={cn(
        'min-w-0 break-words text-xs leading-tight text-fg-muted [hyphens:auto] group-focus-within/row:text-fg group-hover/row:text-fg',
        spec.help && 'cursor-help underline decoration-line-strong decoration-dotted underline-offset-[3px]',
      )}
    >
      {softHyphenate(text)}
      {changed && <span className="sr-only"> (von der Vorlage geändert)</span>}
    </span>
  )

  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={cn(
        'group/row relative -mx-1.5 grid grid-cols-[minmax(0,1fr)_var(--ctl)] items-center gap-x-2 rounded-control py-[3px] pl-1 pr-0',
        'transition-colors hover:bg-[color-mix(in_oklab,var(--pf-surface-2)_70%,transparent)] focus-within:bg-[color-mix(in_oklab,var(--pf-surface-2)_70%,transparent)]',
        error && 'bg-danger/8 hover:bg-danger/10 focus-within:bg-danger/10',
      )}
    >
      {error && <span aria-hidden className="absolute inset-y-1 left-0 w-0.5 rounded-full bg-danger" />}
      <div className="flex min-w-0 items-center gap-1">
        <ResetDot changed={changed} label={spec.label} onReset={onReset} />
        {symbol && (
          <span className="mono flex h-[18px] min-w-[18px] shrink-0 items-center justify-center rounded-md border border-line bg-surface-2 px-1 text-2xs font-semibold text-fg">
            {symbol}
          </span>
        )}
        {spec.help ? (
          <Tooltip content={spec.help} side="top" delayDuration={500}>
            {labelText}
          </Tooltip>
        ) : (
          labelText
        )}
      </div>
      <div className="min-w-0">
        <ParamControl
          spec={spec}
          value={value}
          resolved={resolved}
          fallback={fallback}
          label={spec.label}
          describedBy={describedBy}
          invalid={error || Boolean(tolIssue)}
          intStep={intStep}
          announce={announce}
          onChange={onChange}
        />
      </div>
      {(spec.help || spec.kind === 'tol') && (
        // Hilfe erscheint, sobald die Zeile den Fokus hat (Tastatur); mit der Maus als Tooltip an der Bezeichnung.
        // Toleranzzeilen nennen zusätzlich die Freitext-Formate – im Fluss, verdeckt also keine Nachbarzeile.
        <p id={helpId} className="col-span-2 hidden pb-0.5 pl-[18px] pr-1 pt-1 text-2xs leading-4 text-fg-subtle group-focus-within/row:block">
          {spec.help}
          {spec.kind === 'tol' && (
            <span className="block text-fg-subtle">{FREE_TEXT_HELP}</span>
          )}
        </p>
      )}
      {tolIssue && (
        <p id={issueId} className="col-span-2 pl-[18px] text-2xs leading-4 text-danger-text">
          {tolIssue}
        </p>
      )}
    </div>
  )
}

/** Punkt „geändert“ – zugleich Knopf zum Zurücksetzen auf den Vorlagenwert (Maus und Tastatur) */
function ResetDot({ changed, label, onReset }: { changed: boolean; label: string; onReset: () => void }) {
  if (!changed) return <span aria-hidden className="w-3.5 shrink-0" />
  return (
    <Tooltip content="Auf den Wert der Vorlage zurücksetzen" side="top">
      <button
        type="button"
        aria-label={`${label}: auf den Wert der Vorlage zurücksetzen`}
        onClick={onReset}
        className="group/reset relative flex size-3.5 shrink-0 items-center justify-center rounded-sm text-fg-muted outline-none before:absolute before:-inset-1.5 before:content-[''] hover:text-fg focus-ring"
      >
        <span
          aria-hidden
          className="size-1.5 rounded-full bg-accent shadow-[0_0_6px_var(--pf-glow-indicator)] group-hover/reset:hidden group-focus-visible/reset:hidden"
        />
        <RotateCcw aria-hidden className="hidden size-3 group-hover/reset:block group-focus-visible/reset:block" />
      </button>
    </Tooltip>
  )
}

// --------------------------------------------------------------------------- Controls

interface ControlProps {
  spec: FootprintParamSpec
  value: ParamValue
  resolved: unknown
  fallback: ParamValue | string | undefined
  label: string
  describedBy?: string
  invalid: boolean
  intStep: number
  announce: (text: string) => void
  onChange: (value: ParamValue, opts?: ParamChangeOptions) => void
}

function ParamControl(props: ControlProps) {
  const { spec } = props
  switch (spec.kind) {
    case 'tol':
      return <TolCells {...props} />
    case 'int':
    case 'float':
      return <NumberCell {...props} />
    case 'enum':
      return <EnumCell {...props} />
    case 'bool':
      return <BoolCell {...props} />
    default:
      return <TextCell {...props} />
  }
}

const cellShell = cn(
  'relative flex h-7 w-full rounded-control border border-line-control bg-control',
  'shadow-[inset_0_1px_1px_rgba(0,0,0,.06)] transition-[border-color,box-shadow] duration-150',
  'hover:border-line-control-hover focus-within:border-accent focus-within:shadow-[0_0_0_3px_var(--pf-accent-soft)]',
  'data-[invalid]:border-danger data-[invalid]:focus-within:shadow-[0_0_0_3px_color-mix(in_oklab,var(--pf-danger)_18%,transparent)]',
)

/** Zelle: der fokussierte Teil trägt eine eigene Kupferlinie (nicht nur eine Tönung) */
const cellInput = cn(
  'mono h-full w-full min-w-0 bg-transparent px-1 text-right text-xs tracking-[-0.02em] tabular-nums text-fg outline-none',
  'placeholder:text-fg-subtle focus:bg-[color-mix(in_oklab,var(--pf-accent)_9%,transparent)] focus:shadow-[inset_0_-2px_0_var(--pf-accent)]',
  '@[21rem]/input:px-1.5',
)

/** Kurzer Platzhalter aus der Hilfe des Backends („Leer = wie X.“ → „wie X“, „leer = ohne“ → „ohne“) */
function helpPlaceholder(spec: FootprintParamSpec): string | null {
  const m = /leer\s*=\s*([^.;(]+)/i.exec(spec.help ?? '')
  const text = m?.[1]?.trim()
  return text && text.length <= 14 ? text : null
}

/** Platzhalter für leere Toleranzteile: wirksamer Wert der letzten Vorschau bzw. Standard */
function tolPlaceholder(spec: FootprintParamSpec, resolved: unknown, fallback: unknown): { min: number; nom: number; max: number } | null {
  const fromResolved = normalizeParam(spec, resolved)
  const r = effectiveTol(isTolValue(fromResolved) ? fromResolved : null)
  if (r) return r
  const def = defaultValue(spec)
  const d = effectiveTol(isTolValue(def) ? def : null)
  if (d) return d
  return typeof fallback === 'number' ? { min: fallback, nom: fallback, max: fallback } : null
}

interface TolEdit {
  part: Part
  /** Wert beim Betreten des Felds – Esc stellt ihn wieder her (auch nach ↑/↓) */
  start: TolValue | null
  /** Getippter Text; `null` = formatierter Wert wird gezeigt */
  text: string | null
}

type Hint = { text: string; tone: 'ok' | 'bad' | 'help' }

function TolCells({ spec, value, resolved, fallback, label, describedBy, invalid, announce, onChange }: ControlProps) {
  const cur: TolValue = isTolValue(value) ? value : EMPTY_TOL
  const [edit, setEdit] = useState<TolEdit | null>(null)
  const [hint, setHint] = useState<Hint | null>(null)
  const ph = tolPlaceholder(spec, resolved, fallback)
  const empty = isEmptyTol(cur)
  const expanded = edit?.text != null && (isTolExpression(edit.text) || edit.text.length > 6)

  const emit = (t: TolValue, mode: ChangeKind = 'typing') => onChange(isEmptyTol(t) ? null : t, { mode })

  const display = (part: Part) => (edit?.part === part && edit.text !== null ? edit.text : formatDim(cur[part]))
  const placeholder = (part: Part) => {
    if (part === 'nom' && cur.min !== null && cur.max !== null) return formatDim(round((cur.min + cur.max) / 2, 4))
    if (!empty) return ''
    if (ph) return formatDim(ph[part])
    return part === 'nom' ? (helpPlaceholder(spec) ?? '') : ''
  }

  const onText = (part: Part, text: string) => {
    setEdit((e) => ({ part, start: e?.part === part ? e.start : isTolValue(value) ? value : null, text }))
    const parsed = parseTolText(text)
    if (parsed.kind === 'empty') {
      setHint({ text: FREE_TEXT_HELP, tone: 'help' })
      emit({ ...cur, [part]: null })
    } else if (parsed.kind === 'single') {
      setHint({ text: FREE_TEXT_HELP, tone: 'help' })
      emit({ ...cur, [part]: parsed.value })
    } else if (parsed.kind === 'tol') {
      const t = parsed.tol
      const summary = `${formatDim(t.min) || '–'} / ${formatDim(t.nom) || 'Mitte'} / ${formatDim(t.max) || '–'}`
      setHint({ text: `${parsed.label} → ${summary}`, tone: 'ok' })
      announce(`${label}: ${parsed.label} erkannt, ${summary}`)
      emit(t)
    } else {
      setHint({ text: 'Nicht erkannt – z. B. 0,25±0,05 oder 0,20…0,30', tone: 'bad' })
      announce(`${label}: Eingabe nicht erkannt`)
    }
  }

  const settle = (part: Part) => {
    setEdit((e) => (e ? { ...e, part, text: null } : e))
    setHint({ text: FREE_TEXT_HELP, tone: 'help' })
  }

  const onKey = (part: Part, e: KeyboardEvent<HTMLInputElement>) => {
    if (historyKey(e, () => settle(part))) return
    if (e.key === 'Enter') {
      settle(part)
    } else if (e.key === 'Escape') {
      if (!edit) return
      const start = edit.start ?? EMPTY_TOL
      const changedSinceFocus = JSON.stringify(start) !== JSON.stringify(cur)
      if (!changedSinceFocus && edit.text === null) return // nichts zu verwerfen → Esc darf weiter (z. B. Dialog)
      e.stopPropagation()
      emit(start, 'discrete')
      settle(part)
      announce(`${label}: Eingabe verworfen`)
    } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
      e.preventDefault()
      const step = e.shiftKey ? 0.1 : e.ctrlKey || e.metaKey ? 0.001 : 0.01
      const eff = effectiveTol(cur) ?? ph
      const base = cur[part] ?? eff?.[part] ?? 0
      const next = Math.max(0, round(base + (e.key === 'ArrowUp' ? step : -step), 4))
      emit({ ...cur, [part]: next })
      // Startwert bleibt erhalten: Esc nimmt auch Pfeil-Änderungen zurück
      setEdit((x) => ({ part, start: x ? x.start : isTolValue(value) ? value : null, text: null }))
    }
  }

  // Rückmeldung nur beim Tippen eines Ausdrucks („0,25±0,05“ erkannt / nicht erkannt) – die Formate stehen im Fluss
  const hintOpen = Boolean(hint && edit && hint.tone !== 'help')

  return (
    <PopoverPrimitive.Root open={hintOpen}>
      <PopoverPrimitive.Anchor asChild>
        <div data-invalid={invalid || undefined} className={cn(cellShell, 'grid grid-cols-3 overflow-hidden')}>
          {PARTS.map((part, i) => {
            const isExpanded = expanded && edit?.part === part
            return (
              <input
                key={part}
                type="text"
                inputMode="decimal"
                autoComplete="off"
                spellCheck={false}
                aria-label={`${label} – ${PART_LABEL[part]} (mm)`}
                aria-describedby={describedBy}
                aria-invalid={invalid || undefined}
                value={display(part)}
                placeholder={placeholder(part)}
                onChange={(e) => onText(part, e.target.value)}
                onKeyDown={(e) => onKey(part, e)}
                onFocus={(e) => {
                  setEdit({ part, start: isTolValue(value) ? value : null, text: null })
                  setHint({ text: FREE_TEXT_HELP, tone: 'help' })
                  e.currentTarget.select()
                }}
                onBlur={(e) => {
                  // Wechsel in die Nachbarzelle: Hinweis bleibt stehen (kein Flackern)
                  if (e.relatedTarget instanceof Node && e.currentTarget.parentElement?.contains(e.relatedTarget)) return
                  setEdit(null)
                  setHint(null)
                }}
                className={cn(
                  cellInput,
                  i > 0 && 'border-l border-line',
                  part === 'nom' && 'text-fg',
                  // Ausdruck („0,25±0,05“): Feld wird zeilenbreit und linksbündig – gut lesbar beim Tippen
                  isExpanded &&
                    'absolute inset-0 z-10 border-l-0 bg-control px-2 text-left tracking-normal focus:bg-control focus:shadow-[inset_0_-2px_0_var(--pf-accent)]',
                )}
              />
            )
          })}
        </div>
      </PopoverPrimitive.Anchor>
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          side="top"
          align="end"
          sideOffset={6}
          collisionPadding={10}
          aria-hidden
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onInteractOutside={(e) => e.preventDefault()}
          onEscapeKeyDown={(e) => e.preventDefault()}
          className={cn(
            'pointer-events-none z-popover max-w-[22rem] rounded-control border px-2 py-1 text-2xs leading-4 shadow-raised',
            hint?.tone === 'ok'
              ? 'border-accent/35 bg-surface text-accent-text'
              : hint?.tone === 'bad'
                ? 'border-danger/35 bg-surface text-danger-text'
                : 'border-line-strong bg-surface text-fg-muted',
          )}
        >
          {hint?.text}
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  )
}

function numberPlaceholder(spec: FootprintParamSpec, resolved: unknown, fallback: ParamValue | string | undefined): string {
  const r = normalizeParam(spec, resolved)
  if (typeof r === 'number') return formatPlain(r, 3)
  const d = defaultValue(spec)
  if (typeof d === 'number') return formatPlain(d, 3)
  if (typeof fallback === 'number') return formatPlain(fallback, 3)
  if (typeof fallback === 'string') return fallback
  return helpPlaceholder(spec) ?? 'auto'
}

function NumberCell({ spec, value, resolved, fallback, label, describedBy, invalid, intStep, onChange }: ControlProps) {
  const isInt = spec.kind === 'int'
  const num = typeof value === 'number' ? value : null
  const [edit, setEdit] = useState<{ text: string; start: number | null } | null>(null)
  const [bad, setBad] = useState(false)
  const text = edit ? edit.text : num === null ? '' : formatPlain(num, isInt ? 0 : 3)

  const parse = (t: string): number | null | 'bad' => {
    if (!t.trim()) return null
    const v = parseNumber(t)
    if (v === null) return 'bad'
    return isInt ? (Number.isInteger(v) ? v : 'bad') : v
  }

  const commit = () => {
    if (edit && edit.start !== num) onChange(num, { mode: 'discrete', commit: true })
    setEdit(null)
    setBad(false)
  }

  const clamp = (v: number) => {
    let next = v
    if (spec.minimum !== null && spec.minimum !== undefined) next = Math.max(spec.minimum, next)
    if (spec.maximum !== null && spec.maximum !== undefined) next = Math.min(spec.maximum, next)
    return next
  }

  return (
    <div data-invalid={invalid || bad || undefined} className={cn(cellShell, 'overflow-hidden')}>
      <input
        type="text"
        inputMode={isInt ? 'numeric' : 'decimal'}
        autoComplete="off"
        spellCheck={false}
        aria-label={`${label}${spec.unit ? ` (${spec.unit})` : ''}`}
        aria-describedby={describedBy}
        aria-invalid={invalid || bad || undefined}
        value={text}
        placeholder={numberPlaceholder(spec, resolved, fallback)}
        onFocus={(e) => {
          setEdit({ text: e.currentTarget.value, start: num })
          e.currentTarget.select()
        }}
        onChange={(e) => {
          const t = e.target.value
          setEdit((cur) => ({ text: t, start: cur?.start ?? num }))
          const v = parse(t)
          if (v === 'bad') {
            setBad(true)
            return
          }
          setBad(false)
          onChange(v, { mode: 'typing', commit: false })
        }}
        onBlur={commit}
        onKeyDown={(e) => {
          if (historyKey(e, () => setEdit(null))) return
          if (e.key === 'Enter') commit()
          else if (e.key === 'Escape' && edit) {
            if (edit.start === num && !bad) return
            e.stopPropagation()
            onChange(edit.start, { mode: 'discrete', commit: false })
            setEdit({ text: edit.start === null ? '' : formatPlain(edit.start, isInt ? 0 : 3), start: edit.start })
            setBad(false)
          } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
            e.preventDefault()
            const dir = e.key === 'ArrowUp' ? 1 : -1
            const ph = parseNumber(numberPlaceholder(spec, resolved, fallback)) ?? 0
            const base = num ?? ph
            const next = clamp(
              isInt
                ? stepToGrid(Math.round(base), dir, intStep * (e.shiftKey ? 5 : 1))
                : round(base + dir * (e.shiftKey ? 0.1 : e.ctrlKey || e.metaKey ? 0.001 : 0.01), 4),
            )
            setEdit({ text: formatPlain(next, isInt ? 0 : 3), start: edit?.start ?? num })
            onChange(next, { mode: 'typing', commit: true })
          }
        }}
        className={cn(cellInput, 'px-2 @[21rem]/input:px-2')}
      />
      {spec.unit && <span className="flex shrink-0 items-center pr-2 text-2xs text-fg-subtle">{spec.unit}</span>}
    </div>
  )
}

const AUTO = '__auto__'

function EnumCell({ spec, value, resolved, fallback, label, onChange }: ControlProps) {
  const current = typeof value === 'string' ? value : null
  const def = defaultValue(spec)
  const resolvedText = typeof resolved === 'string' ? resolved : resolved !== undefined && resolved !== null ? String(resolved) : null
  const autoText =
    typeof fallback === 'string' && fallback
      ? fallback
      : resolvedText
        ? `automatisch (${enumShortLabel(spec, resolvedText)})`
        : 'automatisch'
  const hasAuto = def === null
  const shown = current ?? (hasAuto ? AUTO : String(def))
  const short = spec.options.map((o) => enumShortLabel(spec, o))
  // Segmente sind gleich breit (≈ Steuerspalte / Anzahl) – nur für kurze Beschriftungen
  const count = spec.options.length + (hasAuto ? 1 : 0)
  const segmented = count <= 3 && short.every((s) => s.length <= (count === 3 ? 5 : 9))

  const set = (v: string) => onChange(v === AUTO ? null : v, { mode: 'discrete', commit: true })

  if (segmented) {
    return (
      <SegmentedControl
        size="sm"
        fullWidth
        aria-label={label}
        value={shown}
        onValueChange={set}
        options={[
          ...(hasAuto ? [{ value: AUTO, label: 'Auto', title: autoText }] : []),
          ...spec.options.map((o, i) => ({ value: o, label: short[i] })),
        ]}
        className="w-full"
      />
    )
  }
  return (
    <Select
      size="sm"
      aria-label={label}
      value={shown}
      onValueChange={set}
      options={[
        ...(hasAuto ? [{ value: AUTO, label: <span className="text-fg-muted">{autoText}</span> }] : []),
        ...spec.options.map((o) => ({ value: o, label: enumLabel(spec, o) })),
      ]}
      className="mono text-xs"
    />
  )
}

function BoolCell({ spec, value, label, onChange }: ControlProps) {
  const def = defaultValue(spec)
  const checked = typeof value === 'boolean' ? value : def === true
  return (
    <div className="flex h-7 items-center justify-end gap-2 pr-0.5">
      <span className="text-2xs text-fg-muted">{checked ? 'Ja' : 'Nein'}</span>
      <Switch size="sm" aria-label={label} checked={checked} onCheckedChange={(c) => onChange(c, { mode: 'discrete', commit: true })} />
    </div>
  )
}

function TextCell({ spec, value, fallback, label, describedBy, onChange }: ControlProps) {
  const text = typeof value === 'string' ? value : ''
  const placeholder = typeof fallback === 'string' ? fallback : spec.name === 'manufacturer' ? 'z. B. TI' : spec.name === 'package_code' ? 'z. B. PW' : ''
  return (
    <Input
      size="sm"
      aria-label={label}
      aria-describedby={describedBy}
      value={text}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value || null, { mode: 'typing', commit: false })}
      containerClassName="h-7"
      className="text-xs"
    />
  )
}
