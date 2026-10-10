import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Rechenprotokoll des Generators als Messinstrument: Namen (IPC/Haus, eigener Name), Kennwerte, je Anschlussreihe
 * Zmax · Gmin · Xmax mit ungerundeten Werten und J-Zuschlägen, Eingangsgrößen, Toleranzen, Courtyard,
 * Bedrahtet/BGA und die Prüfung (Fehler, Warnungen, Hinweise – jede Meldung genau einmal).
 *
 * `ResultPanel` = Karte (breites Fenster, rechte Spalte) · `ResultBody` = Inhalt (schmales Fenster: Reiter der
 * Bühne) · `ResultReadout` = Messleiste unter der Leinwand (schmales Fenster).
 */
import {
  Calculator,
  ChevronRight,
  CircleCheck,
  CircleX,
  FilePlus2,
  Info,
  LibraryBig,
  PenLine,
  Replace,
  RotateCcw,
  TriangleAlert,
} from 'lucide-react'
import { useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { TimedPreview } from '@/api/footprints'
import { Badge, IconButton, Skeleton, Spinner, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, plural } from '@/lib/format'
import { densityLabel, readCalc, ROUNDING_LABEL, type CalcRecord, type LandRecord } from '../lib/calc'
import { formatDim, formatPlain } from '../lib/params'
import { CopyButton, FlashValue, SectionLabel } from '../parts'
import { CHECKS_ID, collectIssues, focusChecks, issueCounts, type IssueItem } from './issues'
import { useGenerator } from './store'

const sign = (v: number) => (v > 0 ? '+' : v < 0 ? '−' : '±')
const signed = (v: number) => `${sign(v)}${formatDim(Math.abs(v))}`
const countLabel = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

// --------------------------------------------------------------------------- Karte

/** Ergebnis des Speicher-Probelaufs für den angezeigten Stand */
export interface SaveTarget {
  state: 'checking' | 'ready' | 'error'
  /** Ziel-Bibliotheksdatei (relativ zum Bibliotheksordner) */
  library: string | null
  /** Name ist noch nicht registriert */
  isNew: boolean
  /** Gleiche Geometrie liegt schon so in der Bibliothek */
  unchanged: boolean
  /** Bauteile, die den Namen verwenden */
  usage: number
  /** Das Backend würde den Footprint ablehnen (Konflikt, ungültig) */
  error: string | null
  /** Gespeicherten Footprint in der Bibliothek zeigen */
  onShow: (() => void) | null
}

export interface ResultPanelProps {
  data: TimedPreview | null
  fetching: boolean
  error: string | null
  /** Wohin „In Bibliothek speichern“ schreiben würde (Probelauf) */
  saveTarget?: SaveTarget | null
  className?: string
}

export function ResultPanel({ data, fetching, error, saveTarget, className }: ResultPanelProps) {
  useI18n()
  const calc = readCalc(data?.calc)
  const counts = issueCounts(collectIssues(data, calc))
  return (
    <section
      aria-labelledby="fp-result-title"
      aria-busy={fetching || undefined}
      className={cn('flex min-h-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card', className)}
    >
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-4">
        <h2 id="fp-result-title" className="text-ui font-semibold tracking-[-0.01em] text-fg">
          {tr("Berechnung")}
        </h2>
        <ResultStatus data={data} calc={calc} fetching={fetching} error={error ? localizeMessage(error) : error} counts={counts} />
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <ResultBody data={data} error={error ? localizeMessage(error) : error} saveTarget={saveTarget} />
      </div>
    </section>
  )
}

function ResultStatus({
  data,
  calc,
  fetching,
  error,
  counts,
}: {
  data: TimedPreview | null
  calc: CalcRecord | null
  fetching: boolean
  error: string | null
  counts: { errors: number; warnings: number }
}) {
  useI18n()
  return (
    <span className="ml-auto flex min-w-0 items-center gap-2 text-2xs text-fg-subtle">
      {fetching ? (
        <span className="flex items-center gap-1.5">
          <Spinner size={12} tone="accent" />
          {tr("rechnet …")}
        </span>
      ) : error ? (
        <span className="flex items-center gap-1.5 text-danger-text">
          <CircleX aria-hidden className="size-3.5" />
          {tr("nicht berechenbar")}
        </span>
      ) : data ? (
        counts.errors + counts.warnings > 0 ? (
          <>
            <IssueChip counts={counts} onClick={focusChecks} />
            <span className="mono tabular-nums">{data.elapsed} ms</span>
          </>
        ) : (
          <span className="truncate">
            <span aria-hidden className="mr-1.5 inline-block size-1.5 rounded-full bg-success align-middle shadow-[0_0_6px_color-mix(in_oklab,var(--pf-success)_60%,transparent)]" />
            {calc?.standard === 'Herstellerempfehlung' ? tr('Hersteller') : (calc?.standard ?? 'IPC-7351B')} ·{' '}
            <span className="mono tabular-nums">{data.elapsed} ms</span>
          </span>
        )
      ) : null}
    </span>
  )
}

/** Zähler „⚠ 2“ / „✕ 1“ – führt zur Prüfung */
export function IssueChip({
  counts,
  onClick,
  className,
}: {
  counts: { errors: number; warnings: number }
  onClick: () => void
  className?: string
}) {
  useI18n()
  if (!counts.errors && !counts.warnings) return null
  const danger = counts.errors > 0
  const text = danger
    ? countLabel(counts.errors, tr('Fehler'), tr('Fehler'))
    : countLabel(counts.warnings, tr('Warnung'), tr('Warnungen'))
  return (
    <Tooltip content={tr("Zur Prüfung")}>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'flex h-5 shrink-0 items-center gap-1 rounded-full border px-1.5 text-2xs font-medium outline-none transition-colors focus-ring',
          danger
            ? 'border-danger/35 bg-danger/10 text-danger-text hover:bg-danger/15'
            : 'border-warning/35 bg-warning/10 text-warning-text hover:bg-warning/15',
          className,
        )}
      >
        {danger ? <CircleX aria-hidden className="size-3" /> : <TriangleAlert aria-hidden className="size-3" />}
        {text}
      </button>
    </Tooltip>
  )
}

// --------------------------------------------------------------------------- Inhalt

export function ResultBody({
  data,
  error,
  saveTarget,
}: {
  data: TimedPreview | null
  error: string | null
  saveTarget?: SaveTarget | null
}) {
  useI18n()
  const calc = readCalc(data?.calc)
  const spec = data?.spec ?? null
  const issues = collectIssues(data, calc)

  if (!data) {
    // Erste Berechnung scheitert: ruhiger Leerzustand (die Meldung steht einmal auf der Bühne)
    return error ? <ResultEmpty /> : <ResultSkeleton />
  }
  return (
    <>
      {error && (
        <div className="flex gap-2.5 border-b border-danger/25 bg-danger/8 px-4 py-3">
          <CircleX aria-hidden className="mt-0.5 size-4 shrink-0 text-danger-text" />
          <div className="min-w-0 text-xs leading-relaxed">
            <div className="font-medium text-fg">{tr("Neue Maße nicht berechenbar")}</div>
            <p className="text-fg-muted">{tr("Angezeigt wird der letzte gültige Stand.")}</p>
          </div>
        </div>
      )}
      <div className={cn('transition-opacity duration-200', error && 'opacity-55')}>
        <NameBlock data={data} calc={calc} saveTarget={error ? null : saveTarget} />
        <Metrics data={data} calc={calc} />
        {mergeLands(calc?.lands ?? []).map(({ land, both }, i) => (
          <LandBlock key={`${land.label}-${land.axis}-${i}`} land={land} both={both} />
        ))}
        {calc && calc.tht.length > 0 && <ThtBlock calc={calc} />}
        {calc?.bga && <BgaBlock calc={calc} />}
        {calc && <ToleranceBlock calc={calc} />}
        <IssuesBlock items={issues} />
        <DescriptionBlock description={spec?.description ?? null} />
      </div>
    </>
  )
}

function ResultEmpty() {
  useI18n()
  return (
    <div className="flex flex-col items-center gap-2.5 px-6 py-12 text-center">
      <span className="flex size-10 items-center justify-center rounded-card border border-line bg-surface-2 text-fg-subtle">
        <Calculator aria-hidden className="size-5" />
      </span>
      <h3 className="text-ui font-medium text-fg">{tr("Noch keine Berechnung")}</h3>
      <p className="max-w-56 text-2xs leading-4 text-fg-muted">
        {tr("Sobald die Maße zueinander passen, erscheinen hier Zmax, Gmin und Xmax und die Prüfung.")}
      </p>
    </div>
  )
}

// --------------------------------------------------------------------------- Namen

function NameBlock({
  data,
  calc,
  saveTarget,
}: {
  data: TimedPreview
  calc: CalcRecord | null
  saveTarget?: SaveTarget | null
}) {
  useI18n()
  const overrides = useGenerator((s) => s.overrides)
  const setOverrides = useGenerator((s) => s.setOverrides)
  const [editing, setEditing] = useState(false)
  const name = data.spec.name
  const ipc = calc?.ipcName ?? data.spec.ipc_name ?? null
  const house = calc?.houseName ?? null
  const density = (calc?.density ?? data.spec.density ?? 'N') as 'L' | 'N' | 'M'
  const custom = Boolean(overrides.name)
  const base = calc?.tag ? tr('-Basis') : ''

  return (
    <div className="border-b border-line px-4 pb-3.5 pt-3">
      <div className="micro-label">{custom ? tr('Footprint-Name · eigener') : name === ipc ? tr('Footprint-Name · IPC') : tr('Footprint-Name')}</div>
      {editing ? (
        <NameEditor
          initial={overrides.name ?? name}
          onCancel={() => setEditing(false)}
          onApply={(text) => {
            const value = text.trim()
            if (!value) setOverrides({ name: null })
            else if (value !== name) setOverrides({ name: value })
            setEditing(false)
          }}
        />
      ) : (
        <div className="mt-1 flex items-start gap-0.5">
          <FlashValue value={name} className="min-w-0 flex-1">
            <span className="mono block break-all text-md font-semibold leading-snug tracking-[-0.01em] text-fg">{name}</span>
          </FlashValue>
          <CopyButton text={name} label={name === ipc ? tr('IPC-Namen kopieren') : tr('Namen kopieren')} className="-mt-0.5 shrink-0" />
          <IconButton size="xs" label={tr("Namen ändern")} icon={<PenLine />} className="-mt-0.5 shrink-0" onClick={() => setEditing(true)} />
        </div>
      )}
      {custom && !editing && (
        <button
          type="button"
          onClick={() => setOverrides({ name: null })}
          className="mt-1 flex items-center gap-1 rounded-sm text-2xs text-fg-muted outline-none transition-colors hover:text-fg focus-ring"
        >
          <RotateCcw aria-hidden className="size-3" />
          {tr("Erzeugten Namen verwenden")}
        </button>
      )}
      {(ipc && ipc !== name) || (house && house !== name) ? (
        // Kopieren gehört ins <dd> (ein <dl> darf nur dt/dd enthalten)
        <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-2 gap-y-0.5 text-2xs">
          {ipc && ipc !== name && (
            <>
              <dt className="text-fg-subtle">
                {base ? (
                  <Tooltip content={tr("IPC-Name ohne den Zusatz _{value0} für eigene Maße", { value0: String(calc?.tag) })}>
                    <button type="button" className="cursor-help rounded-sm underline decoration-dotted underline-offset-2 outline-none focus-ring">
                      IPC{base}
                    </button>
                  </Tooltip>
                ) : (
                  'IPC'
                )}
              </dt>
              <dd className="flex min-w-0 items-center gap-2">
                <span className="mono min-w-0 flex-1 break-all text-fg-muted">{ipc}</span>
                <CopyButton text={ipc} label={tr("IPC-Namen kopieren")} />
              </dd>
            </>
          )}
          {house && house !== name && (
            <>
              <dt className="text-fg-subtle">{tr("Haus")}{base}</dt>
              <dd className="flex min-w-0 items-center gap-2">
                <span className="mono min-w-0 flex-1 break-all text-fg-muted">{house}</span>
                <CopyButton text={house} label={tr("Hausnamen kopieren")} />
              </dd>
            </>
          )}
        </dl>
      ) : null}
      <div className="mt-2.5 flex flex-wrap items-center gap-1">
        {calc?.standardMatch ? (
          <Tooltip content={tr("Die Maße entsprechen einer Vorlage bzw. Standardmaßen – der Name bleibt ohne Zusatz.")}>
            <button type="button" className="cursor-help rounded-full outline-none focus-ring">
              <Badge variant="success" dot>
                {tr("Standard ·")}{' '}{calc.standardMatch}
              </Badge>
            </button>
          </Tooltip>
        ) : (
          <Tooltip content={tr("Eigene Maße: Der Name erhält einen Zusatz, damit er eindeutig zum Land Pattern passt.")}>
            <button type="button" className="cursor-help rounded-full outline-none focus-ring">
              <Badge variant="neutral">{tr("Eigene Maße")}{calc?.tag ? ` · _${calc.tag}` : ''}</Badge>
            </button>
          </Tooltip>
        )}
        <Badge variant="outline">{tr("Dichte")}{' '}{densityLabel(density)}</Badge>
        {calc?.package && calc.package !== calc.standardMatch && <Badge variant="outline">{localizeMessage(calc.package)}</Badge>}
      </div>
      {saveTarget && <SaveTargetLine target={saveTarget} />}
    </div>
  )
}

/**
 * Wohin „In Bibliothek speichern“ schreibt – aus dem Probelauf des Backends: neu, ersetzt einen gespeicherten
 * Footprint (mit Verwendung) oder ist bereits aktuell; abgelehnt mit Grund.
 */
function SaveTargetLine({ target }: { target: SaveTarget }) {
  useI18n()
  const file = target.library ? baseName(target.library) : null
  let tone: 'success' | 'warning' | 'neutral' | 'danger' = 'neutral'
  let icon: ReactNode = <FilePlus2 aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
  let title: string
  let detail: ReactNode = file ? <span className="mono">{file}</span> : null
  if (target.state === 'checking') {
    icon = <Spinner size={12} />
    title = tr('Ziel wird geprüft …')
    detail = null
  } else if (target.state === 'error') {
    tone = 'danger'
    icon = <CircleX aria-hidden className="size-3.5 shrink-0 text-danger-text" />
    title = tr('Nicht speicherbar')
    detail = <span className="text-danger-text">{localizeMessage(target.error ?? '')}</span>
  } else if (target.unchanged) {
    tone = 'success'
    icon = <CircleCheck aria-hidden className="size-3.5 shrink-0 text-success-text" />
    title = tr('In der Bibliothek · aktuell')
  } else if (!target.isNew) {
    tone = 'warning'
    icon = <Replace aria-hidden className="size-3.5 shrink-0 text-warning-text" />
    title = tr('Ersetzt gespeicherte Version')
    detail = (
      <>
        {file && <span className="mono">{file}</span>}
        {target.usage > 0 && <span> · {plural(target.usage, tr('Bauteil verwendet'), tr('Bauteile verwenden'))} {tr("ihn")}</span>}
      </>
    )
  } else {
    title = tr('Neu in der Bibliothek')
  }
  return (
    <div
      aria-live="polite"
      className={cn(
        'mt-2.5 rounded-control border px-2.5 py-2 text-2xs',
        tone === 'success' && 'border-success/25 bg-success/8',
        tone === 'warning' && 'border-warning/30 bg-warning/8',
        tone === 'danger' && 'border-danger/30 bg-danger/8',
        tone === 'neutral' && 'border-line bg-surface-2/60',
      )}
    >
      <div className="flex min-h-5 items-center gap-2">
        {icon}
        <span className="min-w-0 flex-1 font-medium text-fg">{title}</span>
        {target.onShow && (
          <IconButton size="xs" label={tr("In der Bibliothek anzeigen")} icon={<LibraryBig />} onClick={target.onShow} className="-my-1 -mr-1 shrink-0" />
        )}
      </div>
      {detail && <div className="mt-0.5 break-words pl-5.5 leading-snug text-fg-muted">{detail}</div>}
    </div>
  )
}

/** Feld, das beim Erscheinen den Fokus bekommt (Bearbeiten wurde gerade ausdrücklich gestartet) */
function useFocusOnMount<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useLayoutEffect(() => {
    ref.current?.focus()
    if (ref.current instanceof HTMLInputElement || ref.current instanceof HTMLTextAreaElement) ref.current.select()
  }, [])
  return ref
}

function NameEditor({ initial, onApply, onCancel }: { initial: string; onApply: (text: string) => void; onCancel: () => void }) {
  useI18n()
  const [text, setText] = useState(initial)
  const ref = useFocusOnMount<HTMLInputElement>()
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      onApply(text)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      onCancel()
    }
  }
  return (
    <div className="mt-1 flex flex-col gap-1">
      <input
        ref={ref}
        aria-label={tr("Eigener Footprint-Name")}
        value={text}
        spellCheck={false}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => onApply(text)}
        className="mono h-8 w-full rounded-control border border-accent bg-control px-2 text-ui font-semibold text-fg shadow-[0_0_0_3px_var(--pf-accent-soft)] outline-none"
      />
      <p className="text-2xs text-fg-subtle">{tr("Enter übernimmt · Esc bricht ab · leer = erzeugter Name")}</p>
    </div>
  )
}

// --------------------------------------------------------------------------- Kennwerte

/** Kennwert; bei Wertepaaren („7,40 × 5,40“) steht die Einheit im Titel, damit nichts umbricht */
function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  const pair = value.includes('×') || value.includes('·')
  return (
    <div className="min-w-0 bg-surface px-3 py-2.5">
      <div className="micro-label truncate">
        {label}
        {unit && pair && <span className="normal-case tracking-normal"> · {unit}</span>}
      </div>
      <div className="mt-0.5 flex items-baseline gap-1 whitespace-nowrap">
        <FlashValue value={value}>
          <span className="mono text-sm font-semibold tabular-nums text-fg">{value}</span>
        </FlashValue>
        {unit && !pair && <span className="text-2xs text-fg-subtle">{unit}</span>}
      </div>
    </div>
  )
}

function Metrics({ data, calc }: { data: TimedPreview; calc: CalcRecord | null }) {
  useI18n()
  const pads = data.spec.pads?.length ?? calc?.padCount ?? 0
  const h = data.spec.height ?? calc?.height ?? null
  const cy = calc?.courtyard
  const land = calc?.lands[0]
  const tht = calc?.tht[0]
  const bga = calc?.bga
  return (
    <div className="grid grid-cols-2 gap-px border-b border-line bg-line">
      <Metric label={tr("Pads")} value={formatPlain(pads, 0)} />
      <Metric label={tr("Höhe max.")} value={h !== null ? formatDim(h) : '–'} unit={h !== null ? 'mm' : undefined} />
      <Metric label={tr("Courtyard")} value={cy ? `${formatDim(cy.width)} × ${formatDim(cy.height)}` : '–'} unit={cy ? 'mm' : undefined} />
      {land ? (
        <Metric label={tr("Pad L × B")} value={`${formatDim(land.padLength)} × ${formatDim(land.padWidth)}`} unit="mm" />
      ) : tht ? (
        <Metric label={tr("Bohrung · Pad")} value={`${formatDim(tht.hole)} · ${formatDim(tht.pad)}`} unit="mm" />
      ) : bga ? (
        <Metric label={tr("Land Ø")} value={formatDim(bga.land)} unit="mm" />
      ) : (
        <Metric label={tr("Pad")} value="–" />
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- Lötflächen

const FORMULA = {
  z: 'Zmax = Lmin + 2·JT + √(CL² + F² + P²) – Außenmaß über die Pads',
  g: 'Gmin = Smax − 2·JH − √(CS² + F² + P²) – Innenabstand der Pads',
  x: 'Xmax = Wmin + 2·JS + √(CW² + F² + P²) – Padbreite',
}

function ColHead({ sym, sub, formula }: { sym: string; sub: string; formula: string }) {
  return (
    <th scope="col" aria-label={`${sym}${sub}`} className="pb-1 text-right font-normal">
      <Tooltip content={tr(formula)}>
        <button
          type="button"
          className="mono inline-flex cursor-help items-baseline rounded-sm text-xs font-semibold text-fg-muted outline-none focus-ring"
        >
          {sym}
          <sub className="text-2xs font-medium text-fg-subtle">{sub}</sub>
        </button>
      </Tooltip>
    </th>
  )
}

/** Zwei gleiche Anschlussreihen (quadratische QFN/QFP) als eine Lötfläche „ringsum“ zeigen */
function mergeLands(lands: readonly LandRecord[]): { land: LandRecord; both: boolean }[] {
  if (lands.length === 2) {
    const [a, b] = lands
    const same = (u: number, v: number) => Math.abs(u - v) < 1e-6
    if (a.axis !== b.axis && a.table === b.table && same(a.z, b.z) && same(a.g, b.g) && same(a.x, b.x) && a.clamps.join() === b.clamps.join()) {
      return [{ land: { ...a, label: tr('Anschlüsse ringsum') }, both: true }]
    }
  }
  return lands.map((land) => ({ land, both: false }))
}

function AxisBadge({ both, axis }: { both: boolean; axis: 'x' | 'y' }) {
  useI18n()
  return (
    <Badge variant="outline" size="sm" className="mono">
      <span aria-hidden>{both ? '↔ ↕' : axis === 'x' ? '↔' : '↕'}</span>
      <span className="sr-only">{tr("Achse")}</span> {both ? 'X/Y' : axis.toUpperCase()}
    </Badge>
  )
}

function LandBlock({ land, both }: { land: LandRecord; both: boolean }) {
  useI18n()
  const manufacturer = land.source === 'manufacturer'
  const [open, setOpen] = useState(false)
  const id = useId()
  const c = 2 * land.padCenter
  const values: { v: number; clamped: boolean }[] = [
    { v: land.z, clamped: land.clamped.z },
    { v: land.g, clamped: land.clamped.g },
    { v: land.x, clamped: land.clamped.x },
  ]
  const anyClamped = values.some((x) => x.clamped)
  return (
    <div className="border-b border-line px-4 py-3">
      <SectionLabel actions={<AxisBadge both={both} axis={land.axis} />}>
        {tr(land.label).length > 14 ? tr(land.label) : tr("Lötfläche · {value0}", { value0: tr(land.label) })}
      </SectionLabel>
      <table className="mt-1.5 w-full table-fixed border-collapse">
        <caption className="sr-only">{tr("Lötfläche")}{' '}{tr(land.label)}{tr(": Zmax, Gmin und Xmax in Millimeter")}</caption>
        <colgroup>
          <col className="w-[30%]" />
          <col />
          <col />
          <col />
        </colgroup>
        <thead>
          <tr>
            <th scope="col" className="pb-1">
              <span className="sr-only">{tr("Wert")}</span>
            </th>
            <ColHead sym="Z" sub="max" formula={FORMULA.z} />
            <ColHead sym="G" sub="min" formula={FORMULA.g} />
            <ColHead sym="X" sub="max" formula={FORMULA.x} />
          </tr>
        </thead>
        <tbody className="mono tabular-nums">
          <tr>
            <th scope="row" className="py-0.5 text-left font-sans text-2xs font-normal text-fg-subtle">
              {tr("Ergebnis")}
            </th>
            {values.map(({ v, clamped }, i) => (
              <td key={i} className="py-0.5 text-right text-md font-semibold tracking-[-0.01em] text-fg">
                <FlashValue value={formatDim(v)}>
                  {clamped ? (
                    // begrenzter Wert: getönt hinterlegt (Begründung einmal unter „Prüfung“)
                    <span className="-mr-1 rounded-sm bg-warning/12 px-1 text-warning-text">
                      {formatDim(v)}
                      <span className="sr-only"> {tr("(begrenzt)")}</span>
                    </span>
                  ) : (
                    formatDim(v)
                  )}
                </FlashValue>
              </td>
            ))}
          </tr>
          {!manufacturer && (
            <>
              <tr className="text-2xs text-fg-muted">
                <th scope="row" className="py-px text-left font-sans font-normal text-fg-subtle">
                  {tr("ungerundet")}
                </th>
                <td className="py-px text-right">{formatDim(land.zRaw, 3)}</td>
                <td className="py-px text-right">{formatDim(land.gRaw, 3)}</td>
                <td className="py-px text-right">{formatDim(land.xRaw, 3)}</td>
              </tr>
              <tr className="text-2xs text-fg-muted">
                <th scope="row" className="py-px text-left font-sans font-normal text-fg-subtle">
                  <Tooltip content={tr("J-Werte (Lötkegel) der Dichte: JT Zehe (wirkt auf Z), JH Ferse (auf G), JS Seite (auf X)")}>
                    {/* Name beginnt mit dem sichtbaren Text, danach die Erklärung */}
                    <button type="button" aria-label={tr("J · T/H/S – J-Zuschläge Zehe, Ferse, Seite")} className="cursor-help rounded-sm outline-none focus-ring">
                      J · T/H/S
                    </button>
                  </Tooltip>
                </th>
                <td className="py-px text-right">{signed(land.toe)}</td>
                <td className="py-px text-right">{signed(land.heel)}</td>
                <td className="py-px text-right">{signed(land.side)}</td>
              </tr>
            </>
          )}
        </tbody>
      </table>
      <p className="mt-2 text-2xs leading-4 text-fg-muted">
        {tr("Pad")}{' '}<span className="mono text-fg">{formatDim(land.padLength)} × {formatDim(land.padWidth)}</span> {tr("mm · Mitte–Mitte")}{' '}
        <span className="mono text-fg">{formatDim(c)}</span> mm
      </p>
      <p className="text-2xs leading-4 text-fg-subtle">
        {manufacturer ? tr('Herstellerempfehlung (keine IPC-Berechnung)') : tr("{value0} Tab. {value1} · {value2}", { value0: String(land.standard), value1: String(land.table), value2: tr(land.tableLabel) })}
      </p>
      {anyClamped && (
        <button
          type="button"
          onClick={focusChecks}
          className="mt-1.5 flex items-center gap-1 rounded-sm text-left text-2xs leading-4 text-warning-text outline-none hover:underline focus-ring"
        >
          <TriangleAlert aria-hidden className="size-3 shrink-0" />
          {tr("Begrenzt – Begründung unter „Prüfung“")}
        </button>
      )}
      {!manufacturer && (
        <div className="mt-2">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={`${id}-inputs`}
            onClick={() => setOpen((o) => !o)}
            className="-mx-1 flex items-center gap-1 rounded-sm px-1 text-2xs font-medium text-fg-muted outline-none transition-colors hover:text-fg focus-ring"
          >
            <ChevronRight aria-hidden className={cn('size-3 transition-transform', open && 'rotate-90')} />
            {tr("Eingangsgrößen (L · T · W · S)")}
          </button>
          {open && (
            <table id={`${id}-inputs`} className="mt-1.5 w-full table-fixed text-2xs">
              <caption className="sr-only">{tr("Eingangsgrößen der IPC-Berechnung in Millimeter")}</caption>
              <thead className="text-fg-subtle">
                <tr>
                  <th scope="col" className="w-[38%] pb-0.5 text-left font-normal">
                    {tr("Größe")}
                  </th>
                  <th scope="col" className="pb-0.5 text-right font-normal">
                    min
                  </th>
                  <th scope="col" className="pb-0.5 text-right font-normal">
                    max
                  </th>
                  <th scope="col" className="pb-0.5 text-right font-normal">
                    {tr("Tol.")}
                  </th>
                </tr>
              </thead>
              <tbody className="mono tabular-nums text-fg-muted">
                {(
                  [
                    ['L', tr('Spannweite'), land.L.min, land.L.max, land.L.tol],
                    ['T', tr('Anschlusslänge'), land.T.min, land.T.max, land.T.tol],
                    ['W', tr('Anschlussbreite'), land.W.min, land.W.max, land.W.tol],
                    [
                      'S',
                      land.S.mode === 'rms' ? tr('Innenmaß (RMS)') : tr('Innenmaß'),
                      land.S.mode === 'rms' ? land.S.minRms : land.S.min,
                      land.S.mode === 'rms' ? land.S.maxRms : land.S.max,
                      land.S.mode === 'rms' ? land.S.tolRms : land.S.tol,
                    ],
                  ] as const
                ).map(([sym, label, mn, mx, tol]) => (
                  <tr key={sym}>
                    <th scope="row" className="py-px text-left font-sans font-normal">
                      <span className="mono font-semibold text-fg">{sym}</span> <span className="text-fg-subtle">{label}</span>
                    </th>
                    <td className="py-px text-right">{formatDim(mn)}</td>
                    <td className="py-px text-right">{formatDim(mx)}</td>
                    <td className="py-px text-right">{formatDim(tol)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- Bedrahtet, BGA, Toleranzen

/** Zeile „Bezeichnung … Wert“; die Erklärung erscheint per Tooltip – auch mit der Tastatur erreichbar */
function Row({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-0.5 text-2xs">
      <dt className="shrink-0 text-fg-subtle">
        {hint ? (
          <Tooltip content={hint}>
            <button type="button" className="cursor-help rounded-sm underline decoration-line-strong decoration-dotted underline-offset-[3px] outline-none focus-ring">
              {label}
            </button>
          </Tooltip>
        ) : (
          label
        )}
      </dt>
      <dd className="mono min-w-0 truncate text-right tabular-nums text-fg-muted">{children}</dd>
    </div>
  )
}

function ThtBlock({ calc }: { calc: CalcRecord }) {
  useI18n()
  return (
    <div className="border-b border-line px-4 py-3">
      <SectionLabel>{tr("Bohrungen · IPC-2222")}</SectionLabel>
      {calc.tht.map((t, i) => (
        <dl key={`${t.what}-${i}`} className="mt-1.5">
          {calc.tht.length > 1 && <div className="text-2xs font-medium text-fg-muted">{t.what}</div>}
          <Row label={tr("Bohrung")} hint={tr("Anschluss (Diagonale) + Bohrzugabe der IPC-Stufe")}>
            <span className="text-fg">{formatDim(t.hole)} mm</span>
            {t.leadSize !== null && t.holeAllowance !== null && (
              <span className="text-fg-subtle">
                {' '}
                = {formatDim(t.leadSize)} + {formatDim(t.holeAllowance)}
              </span>
            )}
          </Row>
          <Row label={tr("Pad")} hint={tr("Bohrung + 2 × Restring + Fertigungszugabe")}>
            <span className="text-fg">
              {t.shape === 'oval' && t.padWidth !== null && t.padHeight !== null
                ? `${formatDim(t.padWidth)} × ${formatDim(t.padHeight)} oval`
                : `Ø ${formatDim(t.pad)}`}{' '}
              mm
            </span>
          </Row>
          {t.level && (
            <Row label={tr("Stufe")}>
              {t.level}
              {t.fabAllowance !== null && <span className="text-fg-subtle"> {tr("· Zugabe")}{' '}{formatDim(t.fabAllowance)}</span>}
            </Row>
          )}
          {t.pitch !== null && <Row label={tr("Raster")}>{formatDim(t.pitch)} mm</Row>}
        </dl>
      ))}
    </div>
  )
}

function BgaBlock({ calc }: { calc: CalcRecord }) {
  useI18n()
  const bga = calc.bga
  if (!bga) return null
  return (
    <div className="border-b border-line px-4 py-3">
      <SectionLabel>{tr("Kugeln · IPC-7351B")}</SectionLabel>
      <dl className="mt-1.5">
        <Row label={tr("Kugel Ø")}>
          {formatDim(bga.ball)} mm
          {bga.collapsible !== null && <span className="text-fg-subtle"> · {bga.collapsible ? tr('kollabierend') : tr('nicht kollabierend')}</span>}
        </Row>
        <Row label={tr("Land Ø")}>
          <span className="text-fg">{formatDim(bga.land)} mm</span>
        </Row>
      </dl>
      {bga.rule && <p className="mt-1 text-2xs leading-4 text-fg-subtle">{localizeMessage(bga.rule)}</p>}
    </div>
  )
}

function ToleranceBlock({ calc }: { calc: CalcRecord }) {
  useI18n()
  const bases = calc.roundingBase.filter((b) => b > 0)
  const base = bases.length ? bases.map((b) => formatDim(b)).join(' / ') : null
  const manufacturer = calc.lands.length > 0 && calc.lands.every((l) => l.source === 'manufacturer')
  return (
    <div className="border-b border-line px-4 py-3">
      <SectionLabel>{tr("Toleranzen und Raster")}</SectionLabel>
      <dl className="mt-1.5">
        {calc.F !== null && (
          <Row label={tr("Fertigung F")} hint={tr("Leiterplatten-Fertigungstoleranz (gesamt)")}>
            {formatDim(calc.F)} mm
          </Row>
        )}
        {calc.P !== null && (
          <Row label={tr("Bestückung P")} hint={tr("Platzierungstoleranz des Bestückers (gesamt)")}>
            {formatDim(calc.P)} mm
          </Row>
        )}
        {calc.roundingMode && !manufacturer && (
          <Row label={tr("Rundung")} hint={tr("KiCad: Z/G/X auf 0,05 mm (0,02 mm bei kleinen Chips); IPC: auf 0,01 mm")}>
            {tr(ROUNDING_LABEL[calc.roundingMode]) ?? calc.roundingMode}
            {base && <span className="text-fg-subtle"> · {base} mm</span>}
          </Row>
        )}
        {calc.courtyard && (
          <Row label={tr("Courtyard")} hint={tr("Zugabe um Pads und Körper, nach außen auf das Raster gerundet")}>
            +{formatDim(calc.courtyard.excess)} mm
            <span className="text-fg-subtle"> {tr("· Raster")}{' '}{formatDim(calc.courtyard.grid)}</span>
          </Row>
        )}
        {calc.pasteWindows !== null && calc.pasteWindows > 0 && <Row label={tr("Pastenfenster EP")}>{calc.pasteWindows}</Row>}
      </dl>
    </div>
  )
}

// --------------------------------------------------------------------------- Prüfung

const ISSUE_META = {
  error: { icon: CircleX, cls: 'text-danger-text', label: 'Fehler' },
  warning: { icon: TriangleAlert, cls: 'text-warning-text', label: 'Warnung' },
  info: { icon: Info, cls: 'text-info-text', label: 'Hinweis' },
} as const

function IssuesBlock({ items }: { items: readonly IssueItem[] }) {
  useI18n()
  const { errors, warnings } = issueCounts(items)
  return (
    <div id={CHECKS_ID} tabIndex={-1} className="scroll-mt-2 px-4 py-3 outline-none focus-visible:bg-surface-2/50">
      <SectionLabel
        actions={
          items.length > 0 ? (
            <span className="flex items-center gap-1">
              {errors > 0 && (
                <Badge variant="danger" size="sm">
                  {errors} {tr("Fehler")}
                </Badge>
              )}
              {warnings > 0 && (
                <Badge variant="warning" size="sm">
                  {countLabel(warnings, tr('Warnung'), tr('Warnungen'))}
                </Badge>
              )}
            </span>
          ) : undefined
        }
      >
        {tr("Prüfung")}
      </SectionLabel>
      {items.length === 0 ? (
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-success-text">
          <CircleCheck aria-hidden className="size-3.5 shrink-0" />
          {tr("Keine Auffälligkeiten – bereit zum Speichern.")}
        </p>
      ) : (
        <ul className="mt-1.5 flex flex-col gap-1.5">
          {items.map((item) => {
            const meta = ISSUE_META[item.severity]
            const Icon = meta.icon
            return (
              <li key={item.key} className="flex gap-2 text-xs leading-snug">
                <Icon aria-hidden className={cn('mt-0.5 size-3.5 shrink-0', meta.cls)} />
                <span className="text-fg-muted">
                  <span className="sr-only">{tr(meta.label)}: </span>
                  {localizeMessage(item.message)}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

// --------------------------------------------------------------------------- Beschreibung

function DescriptionBlock({ description }: { description: string | null }) {
  useI18n()
  const override = useGenerator((s) => s.overrides.description)
  const setOverrides = useGenerator((s) => s.setOverrides)
  const [editing, setEditing] = useState(false)
  return (
    <div className="border-t border-line px-4 py-3">
      <SectionLabel
        actions={
          !editing ? (
            <>
              {override && (
                <IconButton size="xs" label={tr("Erzeugte Beschreibung verwenden")} icon={<RotateCcw />} onClick={() => setOverrides({ description: null })} />
              )}
              <IconButton size="xs" label={tr("Beschreibung ändern")} icon={<PenLine />} onClick={() => setEditing(true)} />
            </>
          ) : undefined
        }
      >
        {override ? tr('Beschreibung · eigene') : tr('Beschreibung')}
      </SectionLabel>
      {editing ? (
        <DescriptionEditor
          initial={description ?? ''}
          onCancel={() => setEditing(false)}
          onApply={(text) => {
            const value = text.trim()
            if (!value) setOverrides({ description: null })
            else if (value !== description) setOverrides({ description: value })
            setEditing(false)
          }}
        />
      ) : (
        <p className="mt-1 text-2xs leading-4 text-fg-muted">{description || '–'}</p>
      )}
    </div>
  )
}

function DescriptionEditor({ initial, onApply, onCancel }: { initial: string; onApply: (text: string) => void; onCancel: () => void }) {
  useI18n()
  const [text, setText] = useState(initial)
  const ref = useFocusOnMount<HTMLTextAreaElement>()
  return (
    <div className="mt-1 flex flex-col gap-1">
      <textarea
        ref={ref}
        aria-label={tr("Eigene Beschreibung")}
        value={text}
        rows={3}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => onApply(text)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            onApply(text)
          } else if (e.key === 'Escape') {
            e.preventDefault()
            e.stopPropagation()
            onCancel()
          }
        }}
        className="w-full resize-none rounded-control border border-accent bg-control px-2 py-1.5 text-2xs leading-4 text-fg shadow-[0_0_0_3px_var(--pf-accent-soft)] outline-none"
      />
      <p className="text-2xs text-fg-subtle">{tr("Enter übernimmt · ⇧ Enter neue Zeile · Esc bricht ab · leer = erzeugte")}</p>
    </div>
  )
}

// --------------------------------------------------------------------------- Messleiste (schmale Fenster)

function Reading({ label, value, warn, unit }: { label: string; value: string; warn?: boolean; unit?: string }) {
  return (
    <span className="flex shrink-0 items-baseline gap-1">
      <span className="micro-label">{label}</span>
      <FlashValue value={value}>
        <span className={cn('mono text-ui font-semibold tabular-nums', warn ? 'text-warning-text' : 'text-fg')}>{value}</span>
      </FlashValue>
      {unit && <span className="text-2xs text-fg-subtle">{unit}</span>}
    </span>
  )
}

/** Kompakte Messleiste unter der Leinwand: Z/G/X (bzw. Bohrung/Kugel), Pad, Pads, Prüfung */
export function ResultReadout({
  data,
  error,
  onShowIssues,
}: {
  data: TimedPreview | null
  error: string | null
  onShowIssues: () => void
}) {
  useI18n()
  const calc = readCalc(data?.calc)
  const counts = issueCounts(collectIssues(data, calc))
  const land = calc?.lands[0]
  const tht = calc?.tht[0]
  const bga = calc?.bga
  const pads = data?.spec.pads?.length ?? calc?.padCount ?? null
  return (
    <div className="flex h-10 shrink-0 items-center gap-3 overflow-hidden border-t border-line bg-surface px-3">
      {!data ? (
        <span className="text-2xs text-fg-subtle">{error ? tr('Nicht berechenbar') : tr('Berechnung läuft …')}</span>
      ) : (
        <div className={cn('flex min-w-0 items-center gap-3.5 overflow-hidden', error && 'opacity-55')}>
          {land ? (
            <>
              <Reading label="Z" value={formatDim(land.z)} warn={land.clamped.z} />
              <Reading label="G" value={formatDim(land.g)} warn={land.clamped.g} />
              <Reading label="X" value={formatDim(land.x)} warn={land.clamped.x} />
              <span aria-hidden className="h-4 w-px shrink-0 bg-line-strong" />
              <Reading label={tr("Pad")} value={`${formatDim(land.padLength)}×${formatDim(land.padWidth)}`} />
            </>
          ) : tht ? (
            <>
              <Reading label={tr("Bohrung")} value={formatDim(tht.hole)} />
              <Reading label={tr("Pad")} value={tht.shape === 'oval' && tht.padWidth !== null && tht.padHeight !== null ? `${formatDim(tht.padWidth)}×${formatDim(tht.padHeight)}` : `Ø${formatDim(tht.pad)}`} />
            </>
          ) : bga ? (
            <>
              <Reading label={tr("Kugel")} value={formatDim(bga.ball)} />
              <Reading label={tr("Land")} value={`Ø${formatDim(bga.land)}`} />
            </>
          ) : pads !== null ? (
            <Reading label={tr("Pads")} value={formatPlain(pads, 0)} />
          ) : null}
        </div>
      )}
      <span className="ml-auto flex shrink-0 items-center">
        {data && !error && counts.errors + counts.warnings === 0 ? (
          <button
            type="button"
            onClick={onShowIssues}
            className="flex h-6 items-center gap-1 rounded-full px-1.5 text-2xs text-success-text outline-none transition-colors hover:bg-surface-2 focus-ring"
          >
            <CircleCheck aria-hidden className="size-3.5" />
            {tr("Prüfung ok")}
          </button>
        ) : (
          <IssueChip counts={counts} onClick={onShowIssues} className="h-6 px-2" />
        )}
      </span>
    </div>
  )
}

// --------------------------------------------------------------------------- Laden

function ResultSkeleton() {
  return (
    <div className="flex flex-col gap-4 p-4" aria-hidden>
      <div className="flex flex-col gap-2">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-3 w-36" />
      </div>
      <div className="grid grid-cols-2 gap-2">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
      <Skeleton className="h-3 w-32" />
      <div className="grid grid-cols-3 gap-2">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-5" />
        ))}
      </div>
      <Skeleton className="h-16" />
    </div>
  )
}
