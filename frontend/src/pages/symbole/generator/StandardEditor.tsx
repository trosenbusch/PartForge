/**
 * Editor für Standardsymbole: Kopf mit Typ und Beschreibung, Ergebnis (Symbolname + Bibliotheksstatus),
 * Parameter aus `SymbolKindInfo.params` (Auswahl mit deutschen Beschriftungen, Pinbelegung mit eigener Eingabe,
 * Ganzzahl mit Grenzen, Ja/Nein, Text), aufgelöste Pinbelegung aus der Vorschau und erweiterte Angaben.
 */
import { ChevronDown, RotateCcw } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { GeneratedSpec, SymbolKindInfo, SymbolParamSpec } from '@/api/symbols'
import { Badge, Button, Combobox, Field, Input, Kbd, NumberInput, SegmentedControl, Select, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import { displayText, partLetter } from '@/lib/geometry'
import type { StandardExtras } from '../store'
import { SvgImage } from '../shared'
import { connectorLayout, paramDefault, prefixError, resolvedPinmap, symbolNameError } from '../util'
import { ConnectorPins } from './ConnectorPins'
import { NameResult, type LibraryInfo } from './NameResult'

export interface StandardEditorProps {
  kind: SymbolKindInfo
  values: Record<string, unknown>
  modified: boolean
  extras: StandardExtras
  onParam: (param: SymbolParamSpec, value: unknown) => void
  onExtras: (patch: Partial<StandardExtras>) => void
  onReset: () => void
  spec: GeneratedSpec | undefined
  error: string | null
  library: LibraryInfo
  onHoverPins: (designators: string[] | null) => void
  categoryLabel: (table: string) => string
  onShowInLibrary: (name: string) => void
}

function Section({ title, children, aside, className }: { title: string; children: ReactNode; aside?: ReactNode; className?: string }) {
  const id = useId()
  return (
    <section aria-labelledby={id} className={cn('border-t border-line px-5 py-4', className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 id={id} className="micro-label">
          {title}
        </h3>
        {aside}
      </div>
      {children}
    </section>
  )
}

const optionLabel = (p: SymbolParamSpec, v: string) => p.option_labels[v] ?? v

/**
 * Parameter, die nur unter Bedingungen wirken (sonst ausgeblendet), und Beschriftungen ohne die dann überflüssige
 * Bedingung – z. B. „Nummerierung (2 Reihen)“ beim Steckverbinder nur bei 2 Reihen, dann als „Nummerierung“.
 */
const PARAM_APPLIES: Record<string, Record<string, (values: Record<string, unknown>) => boolean>> = {
  connector: { numbering: (v) => String(v.rows) === '2' },
}
const paramLabel = (p: SymbolParamSpec) => p.label.replace(/\s*\(2 Reihen\)$/, '')

function asText(v: unknown): string {
  if (v === null || v === undefined) return ''
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

/** Eigene Eingabe einer Pinbelegung: Objekte (z. B. Relais) als JSON, sonst Text */
function parseCustom(text: string): unknown {
  const t = text.trim()
  if (t.startsWith('{')) {
    try {
      return JSON.parse(t) as unknown
    } catch {
      return t
    }
  }
  return t
}

function ParamField({ param, value, onChange, error }: { param: SymbolParamSpec; value: unknown; onChange: (v: unknown) => void; error?: string }) {
  if (param.kind === 'bool') {
    return <Switch label={paramLabel(param)} description={param.help ?? undefined} checked={value === true} onCheckedChange={onChange} />
  }
  if (param.kind === 'int') {
    return (
      <Field label={paramLabel(param)} help={param.help ?? undefined} error={error} hint={param.minimum != null && param.maximum != null ? `${param.minimum} … ${param.maximum}` : undefined}>
        <NumberInput
          value={typeof value === 'number' ? value : Number(value) || null}
          onValueChange={(v) => onChange(v ?? paramDefault(param))}
          min={param.minimum ?? undefined}
          max={param.maximum ?? undefined}
          decimals={0}
          containerClassName="w-36"
        />
      </Field>
    )
  }
  if (param.kind === 'enum' && param.allow_custom) {
    const current = asText(value)
    const options = param.options.map((o) => ({
      value: o,
      label: o === 'auto' ? 'Hausstil' : o,
      description: optionLabel(param, o),
      keywords: [optionLabel(param, o)],
    }))
    const known = param.options.includes(current)
    if (!known && current) options.push({ value: current, label: current, description: 'Eigene Belegung', keywords: [] })
    return (
      <Field
        label={paramLabel(param)}
        error={error}
        help={
          <>
            {known ? optionLabel(param, current) : current ? 'Eigene Belegung' : null}
            {param.help && <span className="mt-0.5 block text-fg-subtle">{param.help}</span>}
          </>
        }
      >
        <Combobox
          options={options}
          value={current || null}
          onValueChange={(v) => onChange(v === null ? paramDefault(param) : parseCustom(v))}
          allowCustom
          customLabel={(q) => `Eigene Belegung „${q}“ verwenden`}
          searchPlaceholder="Belegung suchen oder eingeben …"
          mono
        />
      </Field>
    )
  }
  if (param.kind === 'enum') {
    const current = asText(value)
    const short = param.options.length <= 3 && param.options.every((o) => optionLabel(param, o).length <= 16)
    if (short) {
      return (
        <Field label={paramLabel(param)} help={param.help ?? undefined} error={error}>
          <SegmentedControl
            fullWidth
            size="sm"
            aria-label={paramLabel(param)}
            value={current}
            onValueChange={onChange}
            options={param.options.map((o) => ({ value: o, label: optionLabel(param, o) }))}
          />
        </Field>
      )
    }
    return (
      <Field label={paramLabel(param)} help={param.help ?? undefined} error={error}>
        <Select value={current} onValueChange={onChange} options={param.options.map((o) => ({ value: o, label: optionLabel(param, o) }))} />
      </Field>
    )
  }
  return (
    <Field label={paramLabel(param)} help={param.help ?? undefined} error={error}>
      <Input value={asText(value)} onChange={(e) => onChange(e.target.value)} />
    </Field>
  )
}

/** Pins des Ergebnisses: aufgelöste Pinbelegung (Pad → Funktion) bzw. Pins je Teil */
function PinSummary({ spec, onHoverPins }: { spec: GeneratedSpec; onHoverPins: (d: string[] | null) => void }) {
  const pinmap = resolvedPinmap(spec)
  const chip = (key: string, pad: string, label: string, title?: string) => (
    <button
      key={key}
      type="button"
      onMouseEnter={() => onHoverPins([pad])}
      onMouseLeave={() => onHoverPins(null)}
      onFocus={() => onHoverPins([pad])}
      onBlur={() => onHoverPins(null)}
      title={title}
      className="group/chip flex h-7 items-center overflow-hidden rounded-control border border-line bg-surface-2 text-xs outline-none transition-colors hover:border-accent/50 focus-ring"
    >
      <span className="mono flex h-full items-center border-r border-line bg-surface-3 px-1.5 font-semibold text-fg group-hover/chip:text-accent-text">
        {pad}
      </span>
      <span className="mono px-2 text-fg-muted">{label}</span>
    </button>
  )
  if (pinmap?.length) {
    return (
      <div className="flex flex-wrap gap-1.5" aria-label="Pinbelegung: Pin-Nummer und Funktion">
        {pinmap.map((m) => chip(`${m.pad}-${m.fn}`, m.pad, m.fn))}
      </div>
    )
  }
  const parts = Math.max(1, spec.part_count)
  const named = spec.pins.some((p) => p.name && p.name !== p.designator)
  if (!named && parts === 1) {
    return <p className="text-xs text-fg-muted">{spec.pins.length === 1 ? 'Ein Pin' : `${spec.pins.length} Pins`} ohne eigene Namen (nur Nummern).</p>
  }
  return (
    <div className="space-y-2">
      {Array.from({ length: parts }, (_, i) => i + 1).map((part) => {
        const pins = spec.pins.filter((p) => p.part === part || p.part === 0)
        if (!pins.length) return null
        return (
          <div key={part} className="flex items-start gap-2">
            {parts > 1 && <span className="mono mt-1 w-12 shrink-0 text-2xs font-semibold text-fg-subtle">Teil {partLetter(part)}</span>}
            <div className="flex flex-wrap gap-1.5">
              {pins.map((p) => chip(`${part}-${p.designator}`, p.designator, displayText(p.name) || p.designator))}
            </div>
          </div>
        )
      })}
    </div>
  )
}

export function StandardEditor({
  kind,
  values,
  modified,
  extras,
  onParam,
  onExtras,
  onReset,
  spec,
  error,
  library,
  onHoverPins,
  categoryLabel,
  onShowInLibrary,
}: StandardEditorProps) {
  // ohne Parameter gibt es sonst wenig zu tun – dann die erweiterten Angaben gleich zeigen
  const [advanced, setAdvanced] = useState(Boolean(extras.prefix || extras.description || extras.name) || kind.params.length === 0)
  const nameProblem = symbolNameError(extras.name)
  const prefixProblem = prefixError(extras.prefix)
  const advancedId = useId()
  const extrasChanged = Boolean(extras.prefix || extras.description || extras.name)
  // Fehler des Generators einem Parameter zuordnen (z. B. „unbekanntes Zeichen … in der Pinbelegung“)
  const paramError = (p: SymbolParamSpec) => (error && error.toLowerCase().includes(paramLabel(p).toLowerCase()) ? error : undefined)
  const applies = PARAM_APPLIES[kind.key] ?? {}
  const visibleParams = kind.params.filter((p) => applies[p.name]?.(values) ?? true)
  const connector = kind.key === 'connector' ? connectorLayout(values) : null

  return (
    <div className="flex min-h-full flex-col">
      {/* Kopf */}
      <div className="px-5 pb-4 pt-5">
        <div className="flex items-start gap-3.5">
          <span aria-hidden className="dot-grid flex h-14 w-20 shrink-0 items-center justify-center rounded-button border border-line bg-bg p-1.5 shadow-[inset_0_1px_0_var(--pf-highlight)]">
            <SvgImage svg={kind.thumbnail_svg} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h2 className="text-md font-semibold tracking-[-0.015em] text-fg">{kind.label}</h2>
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <Badge>{kind.group}</Badge>
              <Badge variant="outline">
                Präfix <span className="mono text-fg">{extras.prefix || kind.prefix}</span>
              </Badge>
            </div>
          </div>
        </div>
        {kind.description && <p className="mt-3 text-xs leading-relaxed text-fg-muted">{kind.description}</p>}
        {kind.categories.length > 0 && (
          <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
            <span className="text-2xs text-fg-subtle">Passt zu</span>
            {kind.categories.map((c) => (
              <Badge key={c} variant="outline">
                {categoryLabel(c)}
              </Badge>
            ))}
          </div>
        )}
      </div>

      <NameResult name={spec?.name ?? null} pending={!spec && !error} library={library} onShowInLibrary={onShowInLibrary} />

      <Section
        title="Parameter"
        aside={
          modified && (
            <Button size="xs" variant="ghost" leftIcon={<RotateCcw />} onClick={onReset}>
              Zurücksetzen
            </Button>
          )
        }
      >
        {visibleParams.length ? (
          <div className="flex flex-col gap-4">
            {visibleParams.map((p) => (
              <ParamField key={p.name} param={p} value={values[p.name]} onChange={(v) => onParam(p, v)} error={paramError(p)} />
            ))}
          </div>
        ) : (
          <p className="text-xs leading-relaxed text-fg-muted">
            Keine Parameter – Form, Strichstärke und Pinlänge legt der{' '}
            <Link
              to="/einstellungen/hausstil?ansicht=symbole"
              className="rounded-sm font-medium text-fg underline decoration-line-strong underline-offset-2 outline-none hover:decoration-fg focus-ring"
            >
              Hausstil
            </Link>{' '}
            der Bibliothek fest. Name, Präfix und Beschreibung lassen sich unten anpassen.
          </p>
        )}
      </Section>

      {connector && (
        <Section title={`Pinnamen (${connector.pairs.flat().filter(Boolean).length} Pins)`}>
          <ConnectorPins
            layout={connector}
            pins={extras.pins}
            onChange={(pins) => onExtras({ pins })}
            onHoverPin={(d) => onHoverPins(d ? [d] : null)}
          />
        </Section>
      )}

      {spec && (
        <Section title={resolvedPinmap(spec) ? 'Pinbelegung (Ergebnis)' : 'Pins'}>
          <PinSummary spec={spec} onHoverPins={onHoverPins} />
        </Section>
      )}

      <section className="border-t border-line px-5 py-3">
        <button
          type="button"
          aria-expanded={advanced}
          aria-controls={advancedId}
          onClick={() => setAdvanced((v) => !v)}
          className="-mx-1 flex items-center gap-1.5 rounded-control px-1 py-0.5 text-xs font-medium text-fg-muted outline-none transition-colors hover:text-fg focus-ring"
        >
          <ChevronDown aria-hidden className={cn('size-3.5 transition-transform duration-200', !advanced && '-rotate-90')} />
          Erweitert
          {extrasChanged && (
            <>
              <span aria-hidden className="size-1.5 rounded-full bg-accent" />
              <span className="sr-only">(geändert)</span>
            </>
          )}
        </button>
        <div id={advancedId} hidden={!advanced} className="mt-3 grid grid-cols-[7rem_minmax(0,1fr)] gap-3">
          <Field
            label="Eigener Name"
            className="col-span-2"
            error={nameProblem}
            help={nameProblem ? undefined : 'Leer lassen: Name nach Hausstil – gleiche Form und Belegung ergeben denselben Namen, das Symbol wird wiederverwendet.'}
          >
            <Input mono value={extras.name} placeholder={spec && !extras.name ? spec.name : kind.default_name} maxLength={64} onChange={(e) => onExtras({ name: e.target.value })} />
          </Field>
          <Field label="Präfix" hint={`Standard ${kind.prefix}`} error={prefixProblem}>
            <Input
              mono
              value={extras.prefix}
              placeholder={kind.prefix}
              maxLength={10}
              onChange={(e) => onExtras({ prefix: e.target.value.replace(/\s/g, '') })}
            />
          </Field>
          <Field label="Beschreibung" hint="in der SchLib">
            <Input value={extras.description} placeholder={spec?.description || 'aus dem Hausstil'} onChange={(e) => onExtras({ description: e.target.value })} />
          </Field>
        </div>
      </section>
      <div className="flex-1" />
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 pb-4 pt-6 text-2xs text-fg-subtle">
        <span className="flex items-center gap-1">
          <Kbd keys={['↑', '↓']} size="xs" /> Typ wechseln (in der Liste)
        </span>
        <span className="flex items-center gap-1">
          <Kbd hotkey="mod+s" size="xs" /> speichern
        </span>
        <span className="flex items-center gap-1">
          <Kbd hotkey="mod+k" size="xs" /> Typ suchen
        </span>
      </p>
    </div>
  )
}
