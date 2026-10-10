import { useI18n } from '@/lib/i18n'
/**
 * Schritt 3 – Werte und Varianten: Bauformen (mit Leistung/Spannung je Baugröße), E-Reihe und logarithmischer
 * Bereich (oder eingefügte Werteliste), Varianten der Vorlage (Toleranz, TK, Spannung, Verpackung, 0-Ω-Brücke) und
 * Footprint-Optionen. Rechts der Live-Zähler mit Prüfung durch das Backend.
 */
import { ChevronDown, CircuitBoard } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'
import type { SeriesTemplate } from '@/api/series'
import { Badge, Button, Checkbox, ChipGroup, Field, SegmentedControl, Select, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { StepHeading } from '../components/StepHeading'
import type { Estimate } from '../model/estimate'
import {
  datasheetSeries,
  FINE_SERIES,
  parsedValues,
  type Density,
  type FootprintHeight,
  type SeriesSettings,
  type ValueMode,
} from '../model/settings'
import {
  defaultSizes,
  dielectricText,
  effectiveTolerance,
  findOptionByCode,
  optionText,
  packagingChoices,
  sizeInfo,
  sizeNames,
  tcrChoices,
  templateMode,
  toleranceChoices,
  valuesTitle,
  variable,
  voltageChoices,
} from '../model/template'
import { ESeriesControl } from './values/ESeriesControl'
import { LiveSummary, type LiveSummaryProps } from './values/LiveSummary'
import { RangeControl } from './values/RangeControl'
import { SizeTiles } from './values/SizeTiles'
import { ValueListInput } from './values/ValueListInput'

export interface ValuesStepProps {
  template: SeriesTemplate
  settings: SeriesSettings
  onChange: (patch: Partial<SeriesSettings>) => void
  estimate: Estimate
  /** Bauteile je Baugröße für die Kacheln – laut Prüfung, solange die Vorschau passt, sonst geschätzt */
  sizeCounts: Record<string, number>
  summary: Omit<LiveSummaryProps, 'estimate'>
  houseDensity: Density
}

const AUTO = '__auto'

/** Beschriftete Gruppe ohne `<label for>` – für Radiogruppen und reine Anzeigen (Field verweist auf eine Control-ID) */
function Group({ id, label, help, hint, children }: { id: string; label: string; help?: string; hint?: string; children: ReactNode }) {
  return (
    <div role="group" aria-labelledby={`${id}-label`} aria-describedby={help ? `${id}-help` : undefined} className="flex flex-col gap-1.5">
      <div className="flex min-h-5 items-baseline justify-between gap-3">
        <span id={`${id}-label`} className="text-ui font-medium text-fg">
          {label}
        </span>
        {hint && <span className="text-2xs text-fg-subtle">{hint}</span>}
      </div>
      {children}
      {help && (
        <p id={`${id}-help`} className="text-xs leading-snug text-fg-muted">
          {help}
        </p>
      )}
    </div>
  )
}

function Section({ title, aside, children, id }: { title: string; aside?: ReactNode; children: ReactNode; id?: string }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3 px-5 py-4">
      <div className="flex min-h-7 flex-wrap items-center justify-between gap-2">
        <h3 id={id} className="micro-label">
          {title}
        </h3>
        {aside && <div className="flex flex-wrap items-center gap-1.5">{aside}</div>}
      </div>
      {children}
    </section>
  )
}

export function ValuesStep({ template: t, settings: s, onChange, estimate, sizeCounts, summary, houseDensity }: ValuesStepProps) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const [advanced, setAdvanced] = useState(false)
  const mode = templateMode(t)
  const sizes = sizeNames(t).map((size) => sizeInfo(t, size))
  const common = defaultSizes(t)
  const unit = t.value_unit
  const tolerances = toleranceChoices(t)
  const tolEffective = effectiveTolerance(t, s.tolerance)
  const tolVar = variable(t, 'tolerance')
  const tolLabel = tolEffective && tolVar ? (findOptionByCode(tolVar, tolEffective)?.label ?? null) : null
  const tcr = tcrChoices(t)
  const voltages = voltageChoices(t)
  const packaging = packagingChoices(t, s.sizes)
  const dielectric = dielectricText(t)
  const hasJumper = Boolean(t.jumper) && t.kind !== 'catalog'
  const datasheet = datasheetSeries(t, s)
  const parsed = parsedValues(t, s)
  const showHeight = t.category === 'Capacitors'

  const toleranceControl = (() => {
    if (!tolerances.length) return null
    const options =
      mode === 'catalog'
        ? [{ value: AUTO, label: tr("Alle") }, ...tolerances]
        : tolerances.map((o) => ({ value: o.value, label: o.label }))
    const value = mode === 'catalog' ? (s.tolerance ?? AUTO) : (s.tolerance ?? tolEffective ?? options[0]?.value)
    const set = (v: string) => onChange({ tolerance: v === AUTO ? null : v })
    // Radiogruppe: sichtbare Beschriftung + Name am Control (ein <label for> hätte kein Ziel)
    return options.length <= 5 ? (
      <div className="flex flex-col gap-1.5">
        <span aria-hidden className="flex min-h-5 items-baseline text-ui font-medium text-fg">
          {tr("Toleranz")}</span>
        <SegmentedControl size="sm" fullWidth aria-label={tr("Toleranz")} value={value ?? ''} onValueChange={set} options={options} />
      </div>
    ) : (
      <Field label={tr("Toleranz")}>
        <Select size="sm" value={value ?? undefined} onValueChange={set} options={options} />
      </Field>
    )
  })()

  return (
    <section aria-labelledby="serien-werte" className="flex flex-col gap-5">
      <StepHeading
        id="serien-werte"
        title={tr("Werte und Varianten")}
        description={tr("{v0}. Bauformen und Bereich wählen – der Zähler rechnet sofort, PartForge prüft jede Teilenummer gegen die Daten der Serie.", { v0: t.builtin ? tr(t.title) : t.title })}
      />
      <div className="grid grid-cols-1 items-start gap-5 @[68rem]:grid-cols-[minmax(0,1fr)_21.5rem]">
        <div className="flex min-w-0 flex-col divide-y divide-line rounded-card border border-line bg-surface shadow-card">
          <Section
            id={`${uid}-sizes`}
            title={tr("Bauformen")}
            aside={
              <>
                <span className="mr-1 text-2xs text-fg-subtle">
                  {formatNumber(s.sizes.length)} {tr("von")} {formatNumber(sizes.length)}
                </span>
                {common.length > 0 && common.length < sizes.length && (
                  <Button size="xs" variant="ghost" onClick={() => onChange({ sizes: common })}>
                    {tr("Gängige")}</Button>
                )}
                <Button size="xs" variant="ghost" onClick={() => onChange({ sizes: sizes.map((x) => x.size) })}>
                  {tr("Alle")}</Button>
                <Button size="xs" variant="ghost" disabled={!s.sizes.length} onClick={() => onChange({ sizes: [] })}>
                  {tr("Keine")}</Button>
              </>
            }
          >
            <SizeTiles
              aria-label={tr("Bauformen")}
              sizes={sizes}
              value={s.sizes}
              onValueChange={(v) => onChange({ sizes: v })}
              counts={sizeCounts}
            />
            {!s.sizes.length && <p className="text-xs text-warning-text">{tr("Mindestens eine Bauform wählen.")}</p>}
          </Section>

          <Section
            id={`${uid}-values`}
            title={valuesTitle(t)}
            aside={
              <SegmentedControl<ValueMode>
                size="sm"
                aria-label={tr("Werte festlegen")}
                value={s.valueMode}
                onValueChange={(v) => onChange({ valueMode: v })}
                options={[
                  { value: 'range', label: tr("E-Reihe und Bereich") },
                  { value: 'list', label: tr("Werteliste") },
                ]}
              />
            }
          >
            {s.valueMode === 'range' ? (
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-2">
                  <span id={`${uid}-series`} className="text-ui font-medium text-fg">
                    {tr("E-Reihe")}</span>
                  <ESeriesControl
                    aria-label={tr("E-Reihe")}
                    value={s.series}
                    onValueChange={(v) => onChange({ series: v })}
                    datasheet={datasheet}
                    toleranceLabel={tolLabel}
                    fallbackTip={
                      mode === 'catalog' || mode === 'matrix'
                        ? undefined
                        : tr("Das Datenblatt nennt keine Reihe – PartForge nimmt E24.")
                    }
                  />
                  <div className="flex min-h-6 flex-wrap items-center justify-between gap-x-4 gap-y-1">
                    <span className="text-xs text-fg-muted">
                      {datasheet.length ? (
                        <>
                          {tr("Laut Datenblatt")}{tolLabel ? tr(" für {v0}", { v0: tolLabel }) : ''}:{' '}
                          <span className="mono text-fg">{datasheet.join(' + ')}</span>
                          <span aria-hidden className="ml-1.5 inline-block size-1 translate-y-[-2px] rounded-full bg-success" />
                        </>
                      ) : mode === 'catalog' || mode === 'matrix' ? (
                        tr("Ohne Reihe: alle Werte, die laut Datenblatt lieferbar sind.")
                      ) : (
                        <>
                          {tr("Das Datenblatt nennt keine Reihe – ohne Wahl:")} <span className="mono text-fg">E24</span>
                        </>
                      )}
                    </span>
                    {s.series !== 'auto' && FINE_SERIES.includes(s.series) && (
                      <Checkbox
                        checked={s.addE24}
                        onCheckedChange={(v) => onChange({ addE24: v === true })}
                        label={tr("E24-Werte ergänzen (4k7, 2k2 …)")}
                      />
                    )}
                  </div>
                </div>
                {estimate.domain ? (
                  <RangeControl
                    idPrefix={`${uid}-range`}
                    domain={estimate.domain}
                    value={[s.rangeMin, s.rangeMax]}
                    onValueChange={([a, b]) => onChange({ rangeMin: a, rangeMax: b })}
                    candidates={estimate.candidates}
                    unit={unit}
                  />
                ) : (
                  <p className="text-xs text-fg-subtle">
                    {s.sizes.length ? tr("Für diese Auswahl gibt es keinen Wertebereich.") : tr("Bauform wählen, um den Bereich zu sehen.")}
                  </p>
                )}
              </div>
            ) : (
              <ValueListInput
                id={`${uid}-list`}
                text={s.valuesText}
                onTextChange={(v) => onChange({ valuesText: v })}
                parsed={parsed}
                unit={unit}
                jumper={hasJumper}
              />
            )}
          </Section>

          {(tolerances.length > 0 || tcr || voltages.length > 0 || packaging.length > 1 || dielectric || hasJumper) && (
            <Section id={`${uid}-variants`} title={tr("Varianten")}>
              <div className="grid grid-cols-1 gap-x-5 gap-y-4 @[40rem]:grid-cols-2">
                {toleranceControl}
                {tcr && (
                  <Field
                    label={tr("Temperaturkoeffizient")}
                    help={tcr.kind === 'code' ? tr("Ohne Wahl passend zur Toleranz laut Datenblatt.") : tr("Nur Werte mit diesem TK.")}
                  >
                    <Select
                      size="sm"
                      value={s.tcr ?? AUTO}
                      onValueChange={(v) => onChange({ tcr: v === AUTO ? null : v })}
                      options={[
                        { value: AUTO, label: tcr.kind === 'code' ? tr("Laut Datenblatt") : tr("Beliebig") },
                        ...tcr.options.map((o) => ({ value: o.value, label: o.label })),
                      ]}
                    />
                  </Field>
                )}
                {packaging.length > 1 && (
                  <Field label={tr("Verpackung")} help={tr("Ohne Wahl die Standardverpackung je Baugröße.")}>
                    <Select
                      size="sm"
                      value={s.packaging ?? AUTO}
                      onValueChange={(v) => onChange({ packaging: v === AUTO ? null : v })}
                      options={[
                        { value: AUTO, label: tr("Standard je Baugröße") },
                        ...packaging.map((o) => ({
                          value: o.value,
                          label: o.label,
                          description: o.sizes.length ? tr("nur {v0}", { v0: o.sizes.join(', ') }) : undefined,
                        })),
                      ]}
                      contentClassName="max-w-[28rem]"
                    />
                  </Field>
                )}
                {dielectric && (
                  <Group id={`${uid}-dielectric`} label={tr("Dielektrikum")} hint={tr("laut Vorlage")}>
                    <div className="flex h-7 items-center gap-1.5">
                      {dielectric.split(', ').map((d) => (
                        <Badge key={d} variant="neutral" size="md" className="mono">
                          {d}
                        </Badge>
                      ))}
                    </div>
                  </Group>
                )}
                {voltages.length > 0 && (
                  <div className="flex flex-col gap-1.5 @[40rem]:col-span-2">
                    <div className="flex items-baseline justify-between gap-3">
                      <span id={`${uid}-voltage`} className="text-ui font-medium text-fg">
                        {tr("Nennspannung")}</span>
                      <span className="text-2xs text-fg-subtle">
                        {s.voltages.length ? tr("{v0} gewählt", { v0: s.voltages.length }) : tr("keine Auswahl = alle")}
                      </span>
                    </div>
                    <ChipGroup
                      aria-label={tr("Nennspannung")}
                      value={s.voltages}
                      onValueChange={(v) => onChange({ voltages: v })}
                      options={voltages.map((o) => {
                        const n = estimate.perVoltage[o.value.toUpperCase()] ?? estimate.perVoltage[o.value] ?? 0
                        return { value: o.value, label: o.label, meta: formatNumber(n), disabled: n === 0 && !s.voltages.includes(o.value) }
                      })}
                    />
                  </div>
                )}
                {hasJumper && (
                  <div className="@[40rem]:col-span-2">
                    <Switch
                      checked={s.includeJumper}
                      onCheckedChange={(v) => onChange({ includeJumper: v })}
                      label={tr("0-Ω-Brücken mit anlegen")}
                      description={tr("Je Bauform eine Brücke (Wertcode {v0}) mit 0 Ω. Toleranz, TK, Leistung und Spannung gelten für Brücken nicht – Maximalwiderstand und Nennstrom laut Datenblatt stehen in den Notizen.", { v0: t.jumper?.value_code ?? '' })}
                    />
                  </div>
                )}
              </div>
            </Section>
          )}

          <section aria-labelledby={`${uid}-adv`} className="px-5 py-3">
            <button
              type="button"
              id={`${uid}-adv`}
              aria-expanded={advanced}
              aria-controls={`${uid}-adv-body`}
              onClick={() => setAdvanced((o) => !o)}
              className="-mx-2 flex w-[calc(100%+1rem)] items-center gap-2 rounded-control px-2 py-1.5 text-left outline-none transition-colors hover:bg-surface-2 focus-ring"
            >
              <CircuitBoard aria-hidden className="size-4 text-fg-subtle" />
              <span className="micro-label">{tr("Footprints")}</span>
              <span className="ml-1 truncate text-xs text-fg-muted">
                {tr("IPC-Dichte")} {s.density ?? tr("{v0} (Hausstil)", { v0: houseDensity })}
                {showHeight ? ` · ${s.footprintHeight === 'class' ? tr("Höhenklassen") : s.footprintHeight === 'exact' ? tr("exakte Höhe") : tr("ein Footprint je Baugröße")}` : ''}
              </span>
              <ChevronDown
                aria-hidden
                className={cn('ml-auto size-4 text-fg-subtle transition-transform', advanced && 'rotate-180')}
              />
            </button>
            {advanced && (
              <div id={`${uid}-adv-body`} className="grid grid-cols-1 gap-x-5 gap-y-4 pb-2 pt-3 @[40rem]:grid-cols-2">
                <Field label={tr("IPC-Dichte")} help={tr("L kompakt · N nominal · M robust (IPC-7351B).")}>
                  <SegmentedControl<string>
                    size="sm"
                    fullWidth
                    aria-label={tr("IPC-Dichte")}
                    value={s.density ?? AUTO}
                    onValueChange={(v) => onChange({ density: v === AUTO ? null : (v as Density) })}
                    options={[
                      { value: AUTO, label: tr("Hausstil ({v0})", { v0: houseDensity }) },
                      { value: 'L', label: 'L' },
                      { value: 'N', label: 'N' },
                      { value: 'M', label: 'M' },
                    ]}
                  />
                </Field>
                {showHeight && (
                  <Field label={tr("Footprint-Höhe")} help={tr("Höhenklassen: kleinste Standardhöhe ≥ Bauteilhöhe (wenige Footprints, korrekte 3D‑Höhe).")}>
                    <SegmentedControl<FootprintHeight>
                      size="sm"
                      fullWidth
                      aria-label={tr("Footprint-Höhe")}
                      value={s.footprintHeight}
                      onValueChange={(v) => onChange({ footprintHeight: v })}
                      options={[
                        { value: 'standard', label: tr("Je Baugröße") },
                        { value: 'class', label: tr("Höhenklassen") },
                        { value: 'exact', label: tr("Exakt") },
                      ]}
                    />
                  </Field>
                )}
                {packaging.length === 1 && (
                  <p className="text-xs text-fg-muted @[40rem]:col-span-2">
                    {tr("Verpackung:")} {packaging[0].label}
                  </p>
                )}
                {tolerances.length === 0 && tolVar && (
                  <p className="text-xs text-fg-muted">{tr("Toleranz:")} {tolVar.options.map((o) => optionText(o, t.builtin)).join(', ')}</p>
                )}
              </div>
            )}
          </section>
        </div>

        {/* schmale Fenster: Zähler über dem Formular (breit, Abschnitte nebeneinander), sonst klebend rechts */}
        <LiveSummary
          {...summary}
          estimate={estimate}
          className="order-first @[68rem]:sticky @[68rem]:top-[calc(var(--pf-topbar-height)+1rem)] @[68rem]:order-none"
        />
      </div>
    </section>
  )
}
