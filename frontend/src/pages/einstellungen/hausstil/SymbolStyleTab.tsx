/**
 * Hausstil der Schaltplansymbole: Farben, Raster und Pinlängen, Linien und Schrift, Widerstandsform – mit
 * Live-Vorschau (Widerstand, Diode, IC) in der Altium-Ansicht.
 */
import { Hourglass, Link2, Palette } from 'lucide-react'
import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router'
import type { SymbolStyle } from '@/api/system'
import { SymbolCanvas } from '@/components/preview'
import { Badge, Button, Card, Combobox, Input, SegmentedControl, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import type { SymbolRequest } from '@/lib/geometry'
import { applySymbolStyle, pendingSymbolKeys, symbolStyleHonored } from './overlay'
import { SYMBOL_DEFAULTS } from './defaults'
import { NumberRow, ResetAll, StyleGroup, StyleRow } from './StyleRow'
import { useStyledSymbolPreview } from './usePreviews'


const HEX = /^#[0-9A-Fa-f]{6}$/
const FONTS = ['Times New Roman', 'Arial', 'Calibri', 'Consolas', 'Courier New', 'Segoe UI', 'Tahoma', 'Verdana']

const PENDING_LABEL: Partial<Record<keyof SymbolStyle, string>> = {
  grid: 'Raster',
  discrete_pin_length: 'Pinlänge diskret',
  font: 'Schriftart',
  font_size: 'Schriftgröße',
  resistor_style: 'Widerstandsform',
}

export function SymbolStyleTab({
  saved,
  draft,
  onChange,
}: {
  saved: SymbolStyle
  draft: SymbolStyle
  onChange: (patch: Partial<SymbolStyle>) => void
}) {
  const d = SYMBOL_DEFAULTS
  const pendingKeys = pendingSymbolKeys(saved, draft, false)
  const pending = (k: keyof SymbolStyle) => pendingKeys.includes(k)
  const altiumColors = draft.ic_line_color === d.ic_line_color && draft.ic_fill_color === d.ic_fill_color && draft.discrete_line_color === d.discrete_line_color && draft.pin_color === d.pin_color

  return (
    <div className="grid grid-cols-1 items-start gap-5 @[48rem]:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
      <Card className="px-5 pb-2">
        <StyleGroup title="Farben" description="Wie im Altium-Schaltplan – Körper, Linien und Pins">
          <ColorRow label="IC-Umriss" help="Rahmen von IC- und Box-Symbolen." value={draft.ic_line_color} defaultValue={d.ic_line_color} onChange={(v) => onChange({ ic_line_color: v })} />
          <ColorRow label="IC-Füllung" help="Fläche von IC-Symbolen." value={draft.ic_fill_color} defaultValue={d.ic_fill_color} onChange={(v) => onChange({ ic_fill_color: v })} />
          <ColorRow
            label="Diskrete Bauteile"
            help="Linien und gefüllte Formen von R, C, L, Dioden, Transistoren."
            value={draft.discrete_line_color}
            defaultValue={d.discrete_line_color}
            onChange={(v) => onChange({ discrete_line_color: v })}
          />
          <ColorRow label="Pins" value={draft.pin_color} defaultValue={d.pin_color} onChange={(v) => onChange({ pin_color: v })} />
          {!altiumColors && (
            <div className="flex justify-end py-2.5">
              <Button
                size="sm"
                variant="ghost"
                leftIcon={<Palette />}
                onClick={() =>
                  onChange({ ic_line_color: d.ic_line_color, ic_fill_color: d.ic_fill_color, discrete_line_color: d.discrete_line_color, pin_color: d.pin_color })
                }
              >
                Altium-Standardfarben
              </Button>
            </div>
          )}
        </StyleGroup>

        <StyleGroup title="Raster und Pins" description="Längen in mil (100 mil = 2,54 mm)">
          <StyleRow
            label="Raster"
            help="Pins und Körperkanten liegen auf diesem Raster – 100 mil ist Altium-Standard."
            pending={pending('grid')}
            isDefault={draft.grid === d.grid}
            defaultText="100 mil"
            onReset={() => onChange({ grid: d.grid })}
          >
            <SegmentedControl<string>
              aria-label="Raster"
              size="sm"
              value={String(draft.grid)}
              onValueChange={(v) => onChange({ grid: Number(v) })}
              options={['10', '20', '50', '100'].map((g) => ({ value: g, label: g }))}
            />
          </StyleRow>
          <NumberRow
            label="Pinlänge ICs"
            help="Wird auf ein Vielfaches des Rasters gerundet."
            value={draft.ic_pin_length}
            defaultValue={d.ic_pin_length}
            onChange={(v) => onChange({ ic_pin_length: Math.round(v) })}
            min={10}
            max={1000}
            step={draft.grid || 100}
            decimals={0}
            unit="mil"
          />
          <NumberRow
            label="Pinlänge diskret"
            help="Richtwert – die Pinspitze landet immer auf dem Raster."
            value={draft.discrete_pin_length}
            defaultValue={d.discrete_pin_length}
            onChange={(v) => onChange({ discrete_pin_length: Math.round(v) })}
            min={10}
            max={1000}
            step={10}
            decimals={0}
            unit="mil"
            pending={pending('discrete_pin_length')}
          />
        </StyleGroup>

        <StyleGroup title="Linien und Schrift">
          <StyleRow
            label="Linienbreite"
            help="Diskrete Symbole; IC-Rahmen bleiben „Smallest“ wie in Altium."
            isDefault={draft.line_width === d.line_width}
            defaultText="Small"
            onReset={() => onChange({ line_width: d.line_width })}
          >
            <SegmentedControl<SymbolStyle['line_width']>
              aria-label="Linienbreite"
              size="sm"
              value={draft.line_width}
              onValueChange={(v) => onChange({ line_width: v })}
              options={(['smallest', 'small', 'medium', 'large'] as const).map((w, i) => ({
                value: w,
                title: ['Smallest', 'Small', 'Medium', 'Large'][i],
                icon: <LineGlyph weight={[1, 1.75, 2.75, 3.75][i]} />,
              }))}
            />
          </StyleRow>
          <StyleRow
            label="Schriftart"
            help="Pinnamen und Texte in Altium."
            pending={pending('font')}
            isDefault={draft.font === d.font}
            defaultText={d.font}
            onReset={() => onChange({ font: d.font })}
          >
            <Combobox
              options={FONTS.map((f) => ({ value: f, label: f }))}
              value={draft.font}
              onValueChange={(v) => onChange({ font: v ?? d.font })}
              allowCustom
              searchPlaceholder="Schrift suchen oder eingeben …"
              className="w-48"
            />
          </StyleRow>
          <NumberRow
            label="Schriftgröße"
            value={draft.font_size}
            defaultValue={d.font_size}
            onChange={(v) => onChange({ font_size: Math.round(v) })}
            min={4}
            max={72}
            step={1}
            decimals={0}
            unit="pt"
            pending={pending('font_size')}
          />
        </StyleGroup>

        <StyleGroup title="Formen">
          <StyleRow
            label="Widerstand"
            help="IEC: Rechteck (Europa) · ANSI: Zickzack (USA). Gilt auch für Potis und Trimmer."
            pending={pending('resistor_style')}
            isDefault={draft.resistor_style === d.resistor_style}
            defaultText="IEC"
            onReset={() => onChange({ resistor_style: d.resistor_style })}
          >
            <SegmentedControl<SymbolStyle['resistor_style']>
              aria-label="Widerstandsform"
              size="sm"
              value={draft.resistor_style}
              onValueChange={(v) => onChange({ resistor_style: v })}
              options={[
                { value: 'iec', label: 'IEC', icon: <ResistorGlyph kind="iec" /> },
                { value: 'ansi', label: 'ANSI', icon: <ResistorGlyph kind="ansi" /> },
              ]}
            />
          </StyleRow>
          <StyleRow label="Dioden: Pin 1" help="Kathode oder Anode als Pin 1 – gilt für Symbole und Footprints.">
            <Button asChild size="sm" variant="ghost" rightIcon={<Link2 />}>
              <Link to="/einstellungen/namensregeln">{draft.diode_pin1 === 'cathode' ? 'Kathode' : 'Anode'} · Namensregeln</Link>
            </Button>
          </StyleRow>
        </StyleGroup>
        <ResetAll
          disabled={(Object.keys(d) as (keyof SymbolStyle)[]).every((k) => k === 'diode_pin1' || draft[k] === d[k])}
          onReset={() => onChange({ ...d, diode_pin1: draft.diode_pin1 })}
          label="Alle Symbol-Werte auf Standard"
        />
      </Card>

      <SymbolStylePreview saved={saved} draft={draft} pendingKeys={pendingKeys} className="order-first @[48rem]:sticky @[48rem]:top-[4.5rem] @[48rem]:order-none" />
    </div>
  )
}

// --------------------------------------------------------------------------- Farbe

function ColorRow({
  label,
  help,
  value,
  defaultValue,
  onChange,
}: {
  label: string
  help?: string
  value: string
  defaultValue: string
  onChange: (v: string) => void
}) {
  const valid = HEX.test(value)
  return (
    <StyleRow
      label={label}
      help={help}
      isDefault={value.toUpperCase() === defaultValue.toUpperCase()}
      defaultText={defaultValue}
      onReset={() => onChange(defaultValue)}
    >
      <div className="flex items-center gap-2">
        <label
          className="relative size-8.5 shrink-0 cursor-pointer overflow-hidden rounded-button border border-line-control shadow-[inset_0_0_0_2px_var(--pf-surface)] focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-accent"
          style={{ background: valid ? value : 'transparent' }}
        >
          <span className="sr-only">{label}: Farbe wählen</span>
          <input
            type="color"
            value={valid ? value : defaultValue}
            onChange={(e) => onChange(e.target.value.toUpperCase())}
            className="absolute inset-0 cursor-pointer opacity-0"
          />
        </label>
        <Input
          mono
          value={value}
          onChange={(e) => {
            const v = e.target.value.trim()
            onChange(v.startsWith('#') ? v.toUpperCase() : `#${v.toUpperCase()}`)
          }}
          invalid={!valid}
          maxLength={7}
          containerClassName="w-28"
          aria-label={`${label} (Hex)`}
        />
      </div>
    </StyleRow>
  )
}

function LineGlyph({ weight }: { weight: number }) {
  return (
    <svg aria-hidden viewBox="0 0 24 16" className="h-4 w-6" fill="none">
      <path d="M3 8h18" stroke="currentColor" strokeWidth={weight} strokeLinecap="round" />
    </svg>
  )
}

function ResistorGlyph({ kind }: { kind: 'iec' | 'ansi' }) {
  return (
    <svg aria-hidden viewBox="0 0 28 12" className="h-3 w-7" fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round">
      {kind === 'iec' ? (
        <>
          <path d="M1 6h6M21 6h6" />
          <rect x="7" y="2.5" width="14" height="7" rx="0.5" />
        </>
      ) : (
        <path d="M1 6h5l1.5-3.5 3 7 3-7 3 7 3-7 1.5 3.5h5" />
      )}
    </svg>
  )
}

// --------------------------------------------------------------------------- Vorschau

/** EEPROM im SOIC-8-Stil, Versorgung seitlich (oben/unten stießen die gedrehten Namen an die seitlichen Pins) */
const IC_REQUEST: SymbolRequest = {
  kind: 'ic',
  name: 'EEPROM Beispiel',
  pins: [
    { designator: '8', name: 'VCC', electrical: 'power', side: 'left', part: 1, hidden: false },
    { designator: '1', name: 'A0', electrical: 'input', side: 'left', part: 1, hidden: false },
    { designator: '2', name: 'A1', electrical: 'input', side: 'left', part: 1, hidden: false },
    { designator: '3', name: 'A2', electrical: 'input', side: 'left', part: 1, hidden: false },
    { designator: '5', name: 'SDA', electrical: 'io', side: 'right', part: 1, hidden: false },
    { designator: '6', name: 'SCL', electrical: 'input', side: 'right', part: 1, hidden: false },
    { designator: '7', name: 'WP', electrical: 'input', side: 'right', part: 1, hidden: false },
    { designator: '4', name: 'VSS', electrical: 'power', side: 'right', part: 1, hidden: false },
  ],
}

function SymbolStylePreview({
  saved,
  draft,
  pendingKeys,
  className,
}: {
  saved: SymbolStyle
  draft: SymbolStyle
  pendingKeys: (keyof SymbolStyle)[]
  className?: string
}) {
  // Pinfarbe wirkt über die Variable der Altium-Ansicht
  const style = { '--pf-altium-pin': HEX.test(draft.pin_color) ? draft.pin_color : saved.pin_color } as CSSProperties
  return (
    <Card className={cn('overflow-hidden', className)}>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <h2 className="text-ui font-semibold text-fg">Vorschau</h2>
        <span className="text-2xs text-fg-subtle">Altium-Ansicht</span>
      </div>
      <div className="grid grid-cols-2 gap-px bg-line" style={style}>
        <SymbolTile title="Widerstand" req={{ kind: 'resistor' }} saved={saved} draft={draft} labels={false} />
        <SymbolTile title="Diode" req={{ kind: 'diode' }} saved={saved} draft={draft} labels={false} />
        <SymbolTile title="IC" req={IC_REQUEST} saved={saved} draft={draft} ic comment="24LC256" designator="U1" className="col-span-2 h-64" />
      </div>
      {pendingKeys.length > 0 && (
        <p className="flex items-start gap-2 border-t border-line px-4 py-3 text-2xs leading-snug text-fg-muted">
          <Hourglass aria-hidden className="mt-px size-3 shrink-0" />
          <span>
            Exakt nach dem Speichern:{' '}
            {pendingKeys.map((k, i) => (
              <Badge key={k} className={cn('h-4 px-1.5', i > 0 && 'ml-1')}>
                {PENDING_LABEL[k] ?? k}
              </Badge>
            ))}
          </span>
        </p>
      )}
    </Card>
  )
}

function SymbolTile({
  title,
  req,
  saved,
  draft,
  ic = false,
  comment,
  designator,
  labels = true,
  className,
}: {
  title: string
  req: SymbolRequest
  saved: SymbolStyle
  draft: SymbolStyle
  ic?: boolean
  comment?: string
  designator?: string
  labels?: boolean
  className?: string
}) {
  const q = useStyledSymbolPreview(req)
  const spec = q.data?.spec
  const honored = symbolStyleHonored(spec, draft)
  const display = spec && !honored ? applySymbolStyle(spec, saved, draft, { ic }) : spec
  return (
    <div className={cn('relative h-36 bg-surface', className)}>
      <SymbolCanvas
        spec={display}
        theme="altium"
        interactive={false}
        showInfo={false}
        comment={comment}
        designator={designator}
        showLabels={labels}
        aria-label={`Vorschau ${title}${display ? ` (${display.name})` : ''}`}
        className="h-full"
      />
      <TileLabel loading={q.isFetching}>{title}</TileLabel>
    </div>
  )
}

function TileLabel({ children, loading }: { children: ReactNode; loading: boolean }) {
  return (
    <span className="pointer-events-none absolute left-2 top-2 flex items-center gap-1.5 rounded-sm bg-white/85 px-1.5 py-0.5 text-2xs font-medium text-[#1B2230]">
      {children}
      {loading && <Spinner size={10} />}
    </span>
  )
}
