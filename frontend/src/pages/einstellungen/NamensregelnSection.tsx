import { getLocale, useI18n } from '@/lib/i18n'
import { t as geometryLabel } from '@/components/preview/i18n'
/**
 * Namensregeln: Footprint-Namen (IPC-7351 oder Hausnamen) mit echten Beispielen aus dem Generator, Hinweise zu
 * Symbolnamen und die Dioden-Konvention (Pin 1 = Kathode oder Anode) mit Symbol- und Footprint-Vorschau.
 */
import { CircuitBoard, Info, Shapes } from 'lucide-react'
import type { ReactNode } from 'react'
import { useSymbolKinds } from '@/api/settings'
import type { WorkspaceSettings } from '@/api/system'
import { FootprintCanvas, SymbolCanvas, useFootprintPreview, useSymbolPreview } from '@/components/preview'
import { Badge, Callout, Field, SegmentedControl, Skeleton, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { FootprintRequest } from '@/lib/geometry'
import { densityLabel } from '@/pages/footprints/lib/calc'
import { NoWorkspace, SettingsCard } from './components'
import { useWorkspaceDraft } from './draft'
import { UnsavedChanges } from './UnsavedChanges'

interface NamingDraft {
  naming: WorkspaceSettings['footprint']['naming']
  diode_pin1: WorkspaceSettings['symbol']['diode_pin1']
}

const selectNaming = (s: WorkspaceSettings): NamingDraft => ({ naming: s.footprint.naming, diode_pin1: s.symbol.diode_pin1 })
const applyNaming = (s: WorkspaceSettings, v: NamingDraft): WorkspaceSettings => ({
  ...s,
  footprint: { ...s.footprint, naming: v.naming },
  symbol: { ...s.symbol, diode_pin1: v.diode_pin1 },
})

export default function NamensregelnSection() {
  const { t } = useI18n()
  const ws = useWorkspaceDraft(selectNaming, applyNaming, {
    label: t("Namensregeln"),
    savedDescription: t("Gilt für neu erzeugte Footprints und Symbole."),
  })
  if (ws.workspace.isPending) {
    return (
      <div className="flex flex-col gap-5" aria-busy="true">
        <Skeleton className="h-80 rounded-card" />
        <Skeleton className="h-64 rounded-card" />
      </div>
    )
  }
  if (!ws.info || !ws.draft) return <NoWorkspace what={t("Namensregeln")} />
  const draft = ws.draft
  const density = ws.info.settings.footprint.density

  return (
    <div className="flex flex-col gap-5">
      <SettingsCard
        icon={<CircuitBoard />}
        title={t("Footprint-Namen")}
        description={t("So heißen neu erzeugte Footprints in den PcbLib-Dateien und in der Spalte „Footprint Ref“")}
        flush
      >
        <div className="flex flex-col divide-y divide-line px-5">
          <Field
            label={t("Namensschema")}
            layout="row"
            className="py-4"
            help={
              draft.naming === 'ipc'
                ? t("Genormte Namen nach IPC-7351B – sie beschreiben Bauform, Maße, Höhe und Dichte vollständig.")
                : t("Sprechende Namen wie in Ihren bisherigen TR-Bibliotheken – kürzer und vertraut.")
            }
          >
            <SegmentedControl<NamingDraft['naming']>
              aria-label={t("Namensschema")}
              fullWidth
              value={draft.naming}
              onValueChange={(v) => ws.setDraft((d) => ({ ...d, naming: v }))}
              options={[
                { value: 'ipc', label: 'IPC-7351' },
                { value: 'house', label: t("Hausnamen") },
              ]}
            />
          </Field>
        </div>
        <NamingExamples naming={draft.naming} density={density} />
        <div className="flex items-start gap-2 border-t border-line px-5 py-3 text-xs text-fg-muted">
          <Info aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
          <span>
            {t("Vorhandene Footprints behalten ihren Namen – Altium-Designs verweisen darauf. Das Schema gilt für neu erzeugte Footprints. Die Dichte – hier")} {densityLabel(density)}  {t("– stellen Sie im Hausstil ein.")}</span>
        </div>
      </SettingsCard>

      <SymbolNamesCard />

      <SettingsCard
        icon={<DiodeGlyph />}
        title={t("Dioden: Pin 1")}
        description={t("Welcher Anschluss einer Diode die Nummer 1 trägt – in Symbol und Footprint gleich")}
        flush
      >
        <div className="flex flex-col divide-y divide-line px-5">
          <Field
            label={t("Pin 1 ist")}
            layout="row"
            className="py-4"
            help={
              draft.diode_pin1 === 'cathode'
                ? t("IPC-7351 und die meisten Hersteller: Pin 1 = Kathode (Ring auf dem Gehäuse). Empfohlen.")
                : t("Wie in älteren Hausbibliotheken: Pin 1 = Anode. Neue Symbole heißen dann z. B. „Diode (AK)“.")
            }
          >
            <SegmentedControl<NamingDraft['diode_pin1']>
              aria-label={t("Pin 1 der Diode")}
              fullWidth
              value={draft.diode_pin1}
              onValueChange={(v) => ws.setDraft((d) => ({ ...d, diode_pin1: v }))}
              options={[
                { value: 'cathode', label: t("Kathode (IPC)") },
                { value: 'anode', label: t("Anode") },
              ]}
            />
          </Field>
        </div>
        <DiodePreview pin1={draft.diode_pin1} />
        <div className="flex items-start gap-2 border-t border-line px-5 py-3 text-xs text-fg-muted">
          <Info aria-hidden className="mt-px size-3.5 shrink-0 text-fg-subtle" />
          <span>
            {t("Gilt für neu erzeugte Dioden-Symbole und -Footprints (auch LEDs, Z- und Schottky-Dioden). Vorhandene behalten ihre Belegung – der Symbolname zeigt sie an: „Diode“ = Kathode an Pin 1, „Diode (AK)“ = Anode an Pin 1. So passen Symbol und Footprint immer zusammen.")}</span>
        </div>
      </SettingsCard>

      <UnsavedChanges dirty={ws.dirty} saving={ws.saving} onSave={ws.save} onDiscard={ws.reset} label={t("Namensregeln")} root={ws.root} />
    </div>
  )
}

// --------------------------------------------------------------------------- Beispiele (Generator)

/** 0603-Widerstand – auch Grundlage von „So liest sich ein IPC-Name“ (dieselbe Anfrage, ein Abruf) */
const R0603: Omit<FootprintRequest, 'density'> = { family: 'chip', params: { kind: 'R', size: '0603' }, with_3d: false }

const EXAMPLES: { key: string; label: string; req: Omit<FootprintRequest, 'density'> }[] = [
  { key: 'r0603', label: 'Widerstand 0603', req: R0603 },
  { key: 'c0805', label: 'Kondensator 0805', req: { family: 'chip', params: { kind: 'C', size: '0805' }, with_3d: false } },
  { key: 'soic8', label: 'SOIC-8', req: { family: 'gullwing', params: { preset: 'SOIC-8' }, with_3d: false } },
  { key: 'sot23', label: 'SOT-23-3', req: { family: 'sot23', params: { preset: 'SOT-23-3' }, with_3d: false } },
  { key: 'qfn16', label: 'QFN-16 3×3', req: { family: 'nolead', params: { preset: 'QFN-16-3x3-P0.5' }, with_3d: false } },
]

interface CalcNames {
  names?: { ipc?: string; house?: string }
}

function NamingExamples({ naming, density }: { naming: NamingDraft['naming']; density: FootprintRequest['density'] }) {
  const { t } = useI18n()
  return (
    <div className="@container border-t border-line">
      <div role="table" aria-label={t("Beispielnamen")} className="w-full">
        <div role="row" className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_minmax(0,1fr)] gap-4 bg-surface-2/40 px-5 py-2">
          <span role="columnheader" className="micro-label">
            {t("Gehäuse")}</span>
          <ColumnHead active={naming === 'ipc'}>IPC-7351</ColumnHead>
          <ColumnHead active={naming === 'house'}>{t("Hausname")}</ColumnHead>
        </div>
        {EXAMPLES.map((ex) => (
          <ExampleRow key={ex.key} label={t(ex.label)} req={{ ...ex.req, density }} naming={naming} />
        ))}
      </div>
      <IpcAnatomy density={density} />
    </div>
  )
}

function ColumnHead({ active, children }: { active: boolean; children: ReactNode }) {
  const { t } = useI18n()
  return (
    <span role="columnheader" className="flex items-center gap-2">
      <span className={cn('micro-label', active && 'text-accent-text')}>{children}</span>
      {active && <Badge variant="accent">{t("aktiv")}</Badge>}
    </span>
  )
}

function ExampleRow({ label, req, naming }: { label: string; req: FootprintRequest; naming: NamingDraft['naming'] }) {
  const { t } = useI18n()
  const q = useFootprintPreview(req)
  const names = (q.data?.calc as CalcNames | undefined)?.names
  const cell = (value: string | undefined, active: boolean) => (
    <span
      role="cell"
      className={cn(
        'mono min-w-0 break-all rounded-control px-2 py-1 text-xs transition-colors',
        active ? 'bg-accent-soft/60 font-medium text-fg' : 'text-fg-muted',
      )}
    >
      {q.isPending ? <Skeleton className="h-4 w-32" /> : q.isError ? <span className="font-sans text-danger-text">{t("nicht verfügbar")}</span> : value ?? '–'}
    </span>
  )
  return (
    <div role="row" className="grid grid-cols-[minmax(0,9rem)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-4 border-t border-line px-5 py-1.5">
      <span role="rowheader" className="text-xs text-fg-muted">
        {label}
      </span>
      {cell(names?.ipc, naming === 'ipc')}
      {cell(names?.house, naming === 'house')}
    </div>
  )
}

/** Aufbau eines IPC-Namens am Beispiel 0603 */
function IpcAnatomy({ density }: { density: FootprintRequest['density'] }) {
  const { t } = useI18n()
  const q = useFootprintPreview({ ...R0603, density })
  const name = (q.data?.calc as CalcNames | undefined)?.names?.ipc ?? ''
  const m = /^([A-Z]+?C)(\d{2})(\d{2})X(\d+)([MNL])$/.exec(name)
  if (!m) return null
  const mm = (v: number) => v.toLocaleString(getLocale(), { minimumFractionDigits: 1 })
  const parts: { text: string; label: string; tone: string }[] = [
    { text: m[1], label: t("Bauart (Chip-Widerstand)"), tone: 'var(--pf-chart-1)' },
    { text: `${m[2]}${m[3]}`, label: t("Länge × Breite {0} × {1} mm", { "0": mm(Number(m[2]) / 10), "1": mm(Number(m[3]) / 10) }), tone: 'var(--pf-chart-2)' },
    { text: `X${m[4]}`, label: t("Höhe {0} mm", { "0": (Number(m[4]) / 100).toLocaleString(getLocale(), { minimumFractionDigits: 2 }) }), tone: 'var(--pf-chart-3)' },
    { text: m[5], label: t("Dichte {0}", { "0": densityLabel(m[5]) }), tone: 'var(--pf-chart-4)' },
  ]
  return (
    <div className="border-t border-line bg-surface-2/30 px-5 py-3.5">
      <div className="micro-label mb-2">{t("So liest sich ein IPC-Name")}</div>
      <div className="flex flex-wrap items-start gap-x-1.5 gap-y-3">
        {parts.map((p) => (
          <span key={p.text} className="flex flex-col items-start gap-1">
            <span className="mono text-md font-semibold text-fg">{p.text}</span>
            <span className="w-full min-w-16 max-w-40 border-t-2 pt-1 text-2xs leading-snug text-fg-muted" style={{ borderColor: p.tone }}>
              {p.label}
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}

// --------------------------------------------------------------------------- Symbolnamen

function SymbolNamesCard() {
  const { t } = useI18n()
  const kinds = useSymbolKinds()
  const wanted = ['resistor', 'capacitor', 'capacitor_polarized', 'inductor', 'diode', 'led', 'npn', 'nmos', 'opamp_dual', 'crystal_2']
  const list = (kinds.data ?? []).filter((k) => wanted.includes(k.key)).sort((a, b) => wanted.indexOf(a.key) - wanted.indexOf(b.key))
  return (
    <SettingsCard icon={<Shapes />} title={t("Symbolnamen")} description={t("Wie PartForge Schaltplansymbole benennt – automatisch, ohne Einstellung")}>
      <div className="@container py-4">
        <div className="grid grid-cols-1 gap-5 @[40rem]:grid-cols-[minmax(0,1fr)_minmax(0,18rem)]">
          <ul className="flex flex-col gap-3 text-xs leading-relaxed text-fg-muted">
            <li>
              <span className="font-medium text-fg">{t("Standardsymbole")}</span>  {t("heißen nach ihrem Typ und werden von allen passenden Bauteilen geteilt – ein Widerstandssymbol für alle Widerstände.")}</li>
            <li>
              <span className="font-medium text-fg">{t("Mehrpolige Typen")}</span>  {t("tragen ihre Pinbelegung im Namen, z. B.")}{' '}
              <span className="mono text-fg">Diode (AK)</span>  {t("oder")} <span className="mono text-fg">NPN (BCE)</span>{t(". Ein Name ändert so nie seine Belegung.")}</li>
            <li>
              <span className="font-medium text-fg">{t("IC-Symbole")}</span>  {t("aus dem Datenblatt-Import heißen nach der Hersteller-Teilenummer, z. B.")} <span className="mono text-fg">TLV9062IDR</span>.
            </li>
          </ul>
          <div className="rounded-control bg-surface-2/50">
            <div className="micro-label px-3 pb-1 pt-2.5">{t("In dieser Bibliothek")}</div>
            {kinds.isPending ? (
              <div className="flex flex-col gap-1.5 p-3">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-4" />
                ))}
              </div>
            ) : (
              <ul className="divide-y divide-line">
                {list.map((k) => (
                  <li key={k.key} className="flex items-baseline justify-between gap-3 px-3 py-1.5 text-xs">
                    <span className="min-w-0 text-fg-muted">{geometryLabel(k.label)}</span>
                    <span className="mono shrink-0 text-fg">{k.default_name}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </SettingsCard>
  )
}

// --------------------------------------------------------------------------- Diode

function DiodePreview({ pin1 }: { pin1: NamingDraft['diode_pin1'] }) {
  const { t } = useI18n()
  const symbol = useSymbolPreview({ kind: 'diode', params: { pinmap: pin1 === 'cathode' ? 'KA' : 'AK' } })
  const footprint = useFootprintPreview({
    family: 'sod',
    params: { preset: 'SOD-123', cathode_pad: pin1 === 'cathode' ? '1' : '2' },
    density: 'N',
    with_3d: false,
  })
  const caption = pin1 === 'cathode' ? t("Pin 1 = Kathode (K)") : t("Pin 1 = Anode (A)")
  return (
    <div className="@container border-t border-line p-4">
      <div className="grid grid-cols-1 gap-3 @[36rem]:grid-cols-2">
        <PreviewFrame title="Symbol" name={symbol.data?.spec.name} loading={symbol.isFetching} caption={caption}>
          <SymbolCanvas
            spec={symbol.data?.spec}
            theme="altium"
            highlight={['1']}
            interactive={false}
            showInfo={false}
            showLabels={false}
            aria-label={t("Diodensymbol, {0}", { "0": caption })}
            className="h-full"
          />
        </PreviewFrame>
        <PreviewFrame title="Footprint SOD-123" name={footprint.data?.spec.name} loading={footprint.isFetching} caption={caption}>
          <FootprintCanvas
            spec={footprint.data?.spec}
            highlight={['1']}
            showLegend={false}
            showDimensions={false}
            interactive={false}
            showInfo={false}
            aria-label={`Footprint SOD-123, ${caption}`}
            className="h-full"
          />
        </PreviewFrame>
      </div>
      {(symbol.isError || footprint.isError) && (
        <Callout tone="warning" className="mt-3" title={t("Vorschau nicht verfügbar")}>
          {t("Der Generator hat nicht geantwortet – die Einstellung lässt sich trotzdem speichern.")}</Callout>
      )}
    </div>
  )
}

function PreviewFrame({
  title,
  name,
  loading,
  caption,
  children,
}: {
  title: string
  name?: string
  loading: boolean
  caption: string
  children: ReactNode
}) {
  return (
    <figure className="flex min-w-0 flex-col overflow-hidden rounded-card border border-line bg-surface-2/40">
      <figcaption className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-xs font-medium text-fg">{title}</span>
        {name && <span className="mono truncate text-2xs text-fg-subtle">{name}</span>}
        {loading && <Spinner size={12} className="ml-auto" />}
      </figcaption>
      <div className="relative h-48">{children}</div>
      <div className="flex items-center gap-2 border-t border-line px-3 py-1.5 text-2xs text-fg-muted">
        <span aria-hidden className="size-2 rounded-full bg-accent shadow-[0_0_6px_var(--pf-accent)]" />
        {caption}
      </div>
    </figure>
  )
}

/** Diodensymbol als Icon (Dreieck mit Kathodenstrich) */
function DiodeGlyph() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 12h5M17 12h5M7 6l10 6-10 6z" />
      <path d="M17 6v12" />
    </svg>
  )
}
