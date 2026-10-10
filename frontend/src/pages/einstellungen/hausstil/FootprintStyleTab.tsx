import { t as translate, useI18n, localizeMessage, getLocale } from '@/lib/i18n'
/**
 * Hausstil der Footprints: Dichte und Toleranzen, Pads, Bestückungsdruck, Mechanik-Lagen, 3D – mit Live-Vorschau
 * (0603 und SOIC-8) aus dem Generator, Vergleich mit dem gespeicherten Stand und Prüfergebnis.
 */
import { CircleCheck, GitCompareArrows, Hourglass, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import type { FootprintStyle } from '@/api/system'
import { FootprintCanvas } from '@/components/preview'
import { Badge, Card, Combobox, IconButton, SegmentedControl, Slider, Spinner, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { CheckIssue, FootprintRequest } from '@/lib/geometry'
import { DENSITY_ORDER, densityLabel } from '@/pages/footprints/lib/calc'
import { useChoicePref } from '../hooks'
import { applyFootprintStyle, footprintParamOverrides, footprintStyleHonored, pendingFootprintKeys } from './overlay'
import { FOOTPRINT_DEFAULTS } from './defaults'
import { NumberRow, ResetAll, StyleGroup, StyleRow } from './StyleRow'
import { useStyledFootprintPreview } from './usePreviews'


/** TrueType-Schriften, die auf jedem Windows-Rechner vorhanden sind (eigene Eingabe möglich) */
const TRUETYPE_FONTS = ['Arial', 'Calibri', 'Consolas', 'Segoe UI', 'Tahoma', 'Verdana']

const PENDING_LABEL: Partial<Record<keyof FootprintStyle, string>> = {
  silk_pad_clearance: 'Abstand Druck–Pad',
  exposed_pad_designator: 'Nummer des Exposed Pads',
  generate_3d: '3D-Körper',
}

export function FootprintStyleTab({
  saved,
  draft,
  onChange,
}: {
  saved: FootprintStyle
  draft: FootprintStyle
  onChange: (patch: Partial<FootprintStyle>) => void
}) {
  useI18n()
  const d = FOOTPRINT_DEFAULTS
  const pendingKeys = pendingFootprintKeys(saved, draft, false)
  const pending = (k: keyof FootprintStyle) => pendingKeys.includes(k)

  return (
    <div className="grid grid-cols-1 items-start gap-5 @[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <Card className="px-5 pb-2">
        <StyleGroup title={translate("Dichte und Toleranzen")} description={translate("Grundlage der IPC-7351B-Berechnung aller Pads und Courtyards")}>
          <StyleRow
            label={translate("Dichte")}
            help={translate("Klein (L): kleine Pads für dichte Bestückung (Level C) · Nominal (N): Standard (Level B) · Groß (M): große Pads (Level A)")}
            isDefault={draft.density === d.density}
            defaultText={densityLabel(d.density)}
            onReset={() => onChange({ density: d.density })}
          >
            <SegmentedControl<FootprintStyle['density']>
              aria-label={translate("Dichte")}
              size="sm"
              value={draft.density}
              onValueChange={(v) => onChange({ density: v })}
              options={DENSITY_ORDER.map((value) => ({ value, label: densityLabel(value) }))}
            />
          </StyleRow>
          <StyleRow
            label={translate("Rundung")}
            help={translate("Rundet die berechneten Maße Z, G und X.")}
            isDefault={draft.rounding === d.rounding}
            defaultText={translate("0,05 mm")}
            onReset={() => onChange({ rounding: d.rounding })}
          >
            <SegmentedControl<FootprintStyle['rounding']>
              aria-label={translate("Rundung")}
              size="sm"
              value={draft.rounding}
              onValueChange={(v) => onChange({ rounding: v })}
              options={[
                { value: 'kicad', label: translate("0,05 mm") },
                { value: 'ipc', label: translate("0,01 mm (IPC)") },
              ]}
            />
          </StyleRow>
          <NumberRow
            label={translate("Fertigungstoleranz F")}
            help={translate("Toleranz des Leiterplattenherstellers (gesamt).")}
            value={draft.fab_tolerance}
            defaultValue={d.fab_tolerance}
            onChange={(v) => onChange({ fab_tolerance: v })}
            min={0}
            max={0.5}
            step={0.01}
          />
          <NumberRow
            label={translate("Bestückungstoleranz P")}
            help={translate("Platzierungsgenauigkeit des Bestückers (gesamt).")}
            value={draft.placement_tolerance}
            defaultValue={d.placement_tolerance}
            onChange={(v) => onChange({ placement_tolerance: v })}
            min={0}
            max={0.5}
            step={0.01}
          />
        </StyleGroup>

        <StyleGroup title="Pads">
          <StyleRow
            label={translate("Eckenradius")}
            help={translate("Altium-Prozentwert für abgerundete SMD-Pads (50 % = Radius ¼ der kürzeren Seite).")}
            isDefault={draft.pad_corner_radius_pct === d.pad_corner_radius_pct}
            defaultText="50 %"
            onReset={() => onChange({ pad_corner_radius_pct: d.pad_corner_radius_pct })}
          >
            <Slider
              aria-label={translate("Eckenradius")}
              value={[draft.pad_corner_radius_pct]}
              onValueChange={([v]) => onChange({ pad_corner_radius_pct: Math.round(v) })}
              min={0}
              max={100}
              step={5}
              showValue="always"
              formatValue={(v) => `${Math.round(v)} %`}
              className="w-40"
            />
          </StyleRow>
          <NumberRow
            label={translate("Min. Kupferabstand")}
            help={translate("Pads benachbarter Anschlüsse werden auf diesen Abstand begrenzt.")}
            value={draft.min_copper_gap}
            defaultValue={d.min_copper_gap}
            onChange={(v) => onChange({ min_copper_gap: v })}
            min={0.05}
            max={1}
            step={0.01}
          />
          <StyleRow
            label="Exposed Pad"
            help={translate("Nummer des Wärmepads bei QFN/DFN: nächste freie Nummer (wie im Datenblatt) oder „EP“.")}
            pending={pending('exposed_pad_designator')}
            isDefault={draft.exposed_pad_designator === d.exposed_pad_designator}
            defaultText="N+1"
            onReset={() => onChange({ exposed_pad_designator: d.exposed_pad_designator })}
          >
            <SegmentedControl<FootprintStyle['exposed_pad_designator']>
              aria-label={translate("Nummer des Exposed Pads")}
              size="sm"
              value={draft.exposed_pad_designator}
              onValueChange={(v) => onChange({ exposed_pad_designator: v })}
              options={[
                { value: 'next', label: 'N+1' },
                { value: 'EP', label: 'EP' },
              ]}
            />
          </StyleRow>
        </StyleGroup>

        <StyleGroup title={translate("Bestückungsdruck")} description={translate("Top Overlay – nie auf Kupfer")}>
          <NumberRow
            label={translate("Linienbreite ICs")}
            help={translate("ICs, Steckverbinder und größere Gehäuse.")}
            value={draft.silk_width}
            defaultValue={d.silk_width}
            onChange={(v) => onChange({ silk_width: v })}
            min={0.05}
            max={0.5}
            step={0.01}
          />
          <NumberRow
            label={translate("Linienbreite Chips")}
            help={translate("Chip-Widerstände, -Kondensatoren und -Induktivitäten.")}
            value={draft.silk_width_small}
            defaultValue={d.silk_width_small}
            onChange={(v) => onChange({ silk_width_small: v })}
            min={0.05}
            max={0.5}
            step={0.01}
          />
          <NumberRow
            label={translate("Abstand zu Pads")}
            help={translate("Mindestabstand zwischen Druck und Kupfer (Kante zu Kante).")}
            value={draft.silk_pad_clearance}
            defaultValue={d.silk_pad_clearance}
            onChange={(v) => onChange({ silk_pad_clearance: v })}
            min={0}
            max={1}
            step={0.01}
            pending={pending('silk_pad_clearance')}
          />
          <NumberRow
            label={translate("Pin‑1‑Punkt")}
            help={translate("Durchmesser des gefüllten Punkts neben Pin 1.")}
            value={draft.pin1_dot_radius * 4}
            defaultValue={d.pin1_dot_radius * 4}
            onChange={(v) => onChange({ pin1_dot_radius: Number((v / 4).toFixed(4)) })}
            min={0.2}
            max={2}
            step={0.05}
          />
        </StyleGroup>

        <StyleGroup title={translate("Mechanik-Lagen")} description={translate("Bestückungszeichnung, Courtyard, Bauteilmitte und Texte")}>
          <NumberRow
            label={translate("Linienbreite Bestückung")}
            help={translate("Bestückungszeichnung und Bauteilumriss.")}
            value={draft.assembly_width}
            defaultValue={d.assembly_width}
            onChange={(v) => onChange({ assembly_width: v })}
            min={0.02}
            max={0.5}
            step={0.01}
          />
          <NumberRow
            label={translate("Linienbreite Courtyard")}
            value={draft.courtyard_width}
            defaultValue={d.courtyard_width}
            onChange={(v) => onChange({ courtyard_width: v })}
            min={0.01}
            max={0.25}
            step={0.01}
          />
          <NumberRow
            label={translate("Courtyard-Raster")}
            help={translate("Der Courtyard wird nach außen auf dieses Raster gerundet.")}
            value={draft.courtyard_grid}
            defaultValue={d.courtyard_grid}
            onChange={(v) => onChange({ courtyard_grid: v })}
            min={0.01}
            max={0.5}
            step={0.01}
          />
          <StyleRow
            label={translate("Mittelkreuz im Courtyard")}
            help={translate("Kreuz ±0,5 mm im Ursprung, zusätzlich zur Bauteilmitte.")}
            isDefault={draft.center_cross === d.center_cross}
            defaultText={translate("an")}
            onReset={() => onChange({ center_cross: d.center_cross })}
          >
            <Switch checked={draft.center_cross} onCheckedChange={(v) => onChange({ center_cross: v })} />
          </StyleRow>
          <NumberRow
            label={translate("Texthöhe")}
            help={translate(".Designator und .Comment – bei kleinen Bauteilen automatisch kleiner.")}
            value={draft.text_height}
            defaultValue={d.text_height}
            onChange={(v) => onChange({ text_height: v })}
            min={0.3}
            max={3}
            step={0.1}
          />
          <StyleRow
            label={translate("Textschrift")}
            help={translate("Strichschrift (Altium „Stroke“) oder TrueType – für .Designator und .Comment; Altium misst TrueType-Höhen mit Ober- und Unterlänge.")}
            isDefault={draft.text_font === d.text_font}
            defaultText={translate("Strichschrift")}
            onReset={() => onChange({ text_font: d.text_font })}
          >
            <SegmentedControl<FootprintStyle['text_font']>
              aria-label={translate("Textschrift")}
              size="sm"
              value={draft.text_font}
              onValueChange={(v) => onChange({ text_font: v })}
              options={[
                { value: 'stroke', label: translate("Strich") },
                { value: 'truetype', label: 'TrueType' },
              ]}
            />
          </StyleRow>
          {draft.text_font === 'truetype' && (
            <StyleRow
              label={translate("TrueType-Schrift")}
              help={translate("Muss auf den Rechnern installiert sein, die die Leiterplatte öffnen.")}
              isDefault={draft.text_font_name === d.text_font_name}
              defaultText={d.text_font_name}
              onReset={() => onChange({ text_font_name: d.text_font_name })}
            >
              <Combobox
                options={TRUETYPE_FONTS.map((f) => ({ value: f, label: f }))}
                value={draft.text_font_name}
                onValueChange={(v) => onChange({ text_font_name: v?.trim() || d.text_font_name })}
                allowCustom
                searchPlaceholder={translate("Schrift suchen oder eingeben …")}
                className="w-44"
              />
            </StyleRow>
          )}
        </StyleGroup>

        <StyleGroup title="3D">
          <StyleRow
            label={translate("3D-Körper erzeugen")}
            help={translate("Extrudierte Gehäuse auf der 3D-Lage – für Kollisionsprüfung und 3D-Ansicht in Altium.")}
            pending={pending('generate_3d')}
            isDefault={draft.generate_3d === d.generate_3d}
            defaultText={translate("an")}
            onReset={() => onChange({ generate_3d: d.generate_3d })}
          >
            <Switch checked={draft.generate_3d} onCheckedChange={(v) => onChange({ generate_3d: v })} />
          </StyleRow>
        </StyleGroup>
        <ResetAll
          disabled={(Object.keys(d) as (keyof FootprintStyle)[]).every((k) => k === 'naming' || draft[k] === d[k])}
          onReset={() => onChange({ ...d, naming: draft.naming })}
          label={translate("Alle Footprint-Werte auf Standard")}
        />
      </Card>

      <FootprintStylePreview saved={saved} draft={draft} pendingKeys={pendingKeys} className="order-first @[48rem]:sticky @[48rem]:top-[4.5rem] @[48rem]:order-none" />
    </div>
  )
}

// --------------------------------------------------------------------------- Vorschau

/** Maß mit fest zwei Nachkommastellen („0,60“) – wie die Eingabefelder */
const mm2 = (v: number) => v.toLocaleString(getLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })

interface CourtyardBox {
  x1: number
  y1: number
  x2: number
  y2: number
}

const courtyardOf = (calc: unknown): CourtyardBox | null => {
  const c = (calc as { courtyard?: Partial<CourtyardBox> } | null | undefined)?.courtyard
  return c && [c.x1, c.y1, c.x2, c.y2].every((v) => typeof v === 'number') ? (c as CourtyardBox) : null
}

/** `calc` mit dem gemeinsamen Courtyard zweier Vorschauen (bestimmt nur das Einpassen der Leinwand) */
function withCourtyardUnion(calc: unknown, a: unknown, b: unknown): unknown {
  const ca = courtyardOf(a)
  const cb = courtyardOf(b)
  if (!calc || typeof calc !== 'object' || !ca || !cb) return calc
  return {
    ...(calc as Record<string, unknown>),
    courtyard: {
      ...((calc as { courtyard?: object }).courtyard ?? {}),
      x1: Math.min(ca.x1, cb.x1),
      y1: Math.min(ca.y1, cb.y1),
      x2: Math.max(ca.x2, cb.x2),
      y2: Math.max(ca.y2, cb.y2),
    },
  }
}

type Sample = '0603' | 'SOIC-8'
const SAMPLES: Record<Sample, { req: Omit<FootprintRequest, 'density' | 'with_3d'>; silk: 'small' | 'regular'; label: string }> = {
  '0603': { req: { family: 'chip', params: { kind: 'R', size: '0603' } }, silk: 'small', label: 'Widerstand 0603' },
  'SOIC-8': { req: { family: 'gullwing', params: { preset: 'SOIC-8' } }, silk: 'regular', label: 'SOIC-8' },
}

function FootprintStylePreview({
  saved,
  draft,
  pendingKeys,
  className,
}: {
  saved: FootprintStyle
  draft: FootprintStyle
  pendingKeys: (keyof FootprintStyle)[]
  className?: string
}) {
  useI18n()
  const [sample, setSample] = useChoicePref<Sample>('pf-hausstil-fp-beispiel', ['0603', 'SOIC-8'], 'SOIC-8')
  const [compare, setCompare] = useState(false)
  const s = SAMPLES[sample]
  const overrides = footprintParamOverrides(saved, draft)
  const req: FootprintRequest = {
    ...s.req,
    params: { ...s.req.params, ...overrides },
    density: draft.density,
    with_3d: true,
  }
  const savedReq: FootprintRequest = { ...s.req, density: saved.density, with_3d: true }
  const live = useStyledFootprintPreview(req)
  const before = useStyledFootprintPreview(savedReq)
  const changed = JSON.stringify(saved) !== JSON.stringify(draft)
  const showSaved = compare && changed
  const q = showSaved ? before : live
  const honored = footprintStyleHonored(q.data?.calc, draft)
  const spec = q.data?.spec
  const display = spec && !showSaved && !honored ? applyFootprintStyle(spec, saved, draft, { silk: s.silk, calc: q.data?.calc }) : spec
  // Beim Umschalten Entwurf ⇄ gespeichert denselben Ausschnitt zeigen: beide Courtyards bestimmen das Einpassen,
  // so bleibt der Maßstab gleich und Größenunterschiede werden sichtbar
  const frameCalc = changed ? withCourtyardUnion(q.data?.calc, live.data?.calc, before.data?.calc) : q.data?.calc
  const issues: CheckIssue[] = (q.data?.issues ?? []).filter((i) => i.severity !== 'info')
  const cy = (q.data?.calc as { courtyard?: { width?: number; height?: number } } | undefined)?.courtyard
  const pad = display?.pads?.[0]

  return (
    <Card className={cn('overflow-hidden', className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
        <h2 className="text-ui font-semibold text-fg">{translate("Vorschau")}</h2>
        {q.isFetching && <Spinner size={12} label={translate("Vorschau wird berechnet")} />}
        <div className="ml-auto flex items-center gap-1.5">
          <SegmentedControl<Sample>
            aria-label={translate("Beispielgehäuse")}
            size="sm"
            value={sample}
            onValueChange={setSample}
            options={[
              { value: '0603', label: '0603' },
              { value: 'SOIC-8', label: 'SOIC-8' },
            ]}
          />
          <IconButton
            size="sm"
            variant={compare ? 'secondary' : 'ghost'}
            label={compare ? translate("Entwurf zeigen") : translate("Gespeicherten Stand zeigen")}
            aria-pressed={compare}
            icon={<GitCompareArrows />}
            disabled={!changed}
            onClick={() => setCompare((c) => !c)}
          />
        </div>
      </div>
      <div className="relative">
        <FootprintCanvas
          spec={display}
          calc={frameCalc}
          showLegend
          showInfo={false}
          resetKey={`${sample}`}
          aria-label={translate("Footprint-Vorschau {value1}", { value1: translate(s.label) })}
          className="h-[19rem]"
        />
        {showSaved && (
          <span className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full border border-line-strong bg-surface/90 px-2.5 py-0.5 text-2xs font-medium text-fg">
            {translate("Gespeicherter Stand")}</span>
        )}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-line px-4 py-3 text-xs">
        <div>
          <dt className="text-2xs text-fg-subtle">Courtyard</dt>
          <dd className="mono tabular text-fg">{cy?.width && cy?.height ? `${mm2(cy.width)} × ${mm2(cy.height)} mm` : '–'}</dd>
        </div>
        <div>
          <dt className="text-2xs text-fg-subtle">Pad 1</dt>
          <dd className="mono tabular text-fg">{pad ? `${mm2(pad.width)} × ${mm2(pad.height)} mm` : '–'}</dd>
        </div>
      </dl>
      <div className="flex flex-col gap-2 border-t border-line px-4 py-3" aria-live="polite">
        {q.isError ? (
          <p className="flex items-start gap-2 text-xs text-danger-text">
            <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
            {translate("Mit diesen Werten entsteht kein gültiger Footprint – bitte die Toleranzen prüfen.")}</p>
        ) : issues.length === 0 ? (
          <p className="flex items-center gap-2 text-xs text-success-text">
            <CircleCheck aria-hidden className="size-3.5 shrink-0" />
            {translate("Prüfung bestanden – keine Abstands- oder Lagenprobleme.")}</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {issues.slice(0, 3).map((i) => (
              <li key={`${i.code}-${i.message}`} className={cn('flex items-start gap-2 text-xs', i.severity === 'error' ? 'text-danger-text' : 'text-warning-text')}>
                <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                <span>{localizeMessage(i.message)}</span>
              </li>
            ))}
          </ul>
        )}
        {pendingKeys.length > 0 && !showSaved && (
          <p className="flex items-start gap-2 text-2xs leading-snug text-fg-muted">
            <Hourglass aria-hidden className="mt-px size-3 shrink-0" />
            <span>
              {translate("Exakt nach dem Speichern:")}{' '}
              {pendingKeys.map((k, i) => (
                <Badge key={k} className={cn('h-4 px-1.5', i > 0 && 'ml-1')}>
                  {translate(PENDING_LABEL[k] ?? k)}
                </Badge>
              ))}
            </span>
          </p>
        )}
      </div>
    </Card>
  )
}
