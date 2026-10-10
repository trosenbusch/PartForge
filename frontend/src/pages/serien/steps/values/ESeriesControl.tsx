import { useI18n } from '@/lib/i18n'
/**
 * E-Reihe wählen: „Datenblatt“ (Reihen laut Toleranz bzw. alle lieferbaren Werte) oder E3 … E192 – der
 * Segmentschalter des UI-Kits (Radio-Semantik, gleitende Markierung, Pfeiltasten) mit Reihen in Monospace. Tooltip je
 * Reihe (übliche Toleranz, Werte je Dekade); derselbe Text ist der Name des Segments für Screenreader und beginnt mit
 * der sichtbaren Beschriftung. Reihen, die das Datenblatt nennt, tragen einen Punkt.
 */
import { SegmentedControl, Tooltip, type SegmentedOption } from '@/components/ui'
import { E_SERIES_TOLERANCE, type ESeriesName } from '@/lib/units'
import type { SeriesChoice } from '../../model/settings'
import { SERIES_NAMES, valuesPerDecade } from '../../model/values'

export interface ESeriesControlProps {
  value: SeriesChoice
  onValueChange: (value: SeriesChoice) => void
  /** Reihen laut Datenblatt (leer = das Datenblatt nennt keine) */
  datasheet: ESeriesName[]
  /** Tooltip von „Datenblatt“, wenn das Datenblatt keine Reihe nennt (Standard: alle lieferbaren Werte) */
  fallbackTip?: string
  /** Kurzbeschreibung der gewählten Toleranz für den Tooltip („±1 %“) */
  toleranceLabel?: string | null
  disabled?: boolean
  'aria-label'?: string
}

export function ESeriesControl({
  value,
  onValueChange,
  datasheet,
  toleranceLabel,
  fallbackTip = 'Alle Werte, die laut Datenblatt lieferbar sind',
  disabled,
  'aria-label': ariaLabel = 'E-Reihe',
}: ESeriesControlProps) {
  const { t: tr } = useI18n()
  const choices: { value: SeriesChoice; label: string; tip: string; marked: boolean; mono: boolean }[] = [
    {
      value: 'auto',
      label: tr("Datenblatt"),
      tip: datasheet.length
        ? tr("Reihen laut Datenblatt{v0}: {v1}", { v0: toleranceLabel ? tr(" für {v0}", { v0: toleranceLabel }) : '', v1: datasheet.join(' + ') })
        : tr(fallbackTip),
      marked: false,
      mono: false,
    },
    ...SERIES_NAMES.map((name) => ({
      value: name as SeriesChoice,
      label: name,
      tip: tr("{v0} · übliche Toleranz {v1} · {v2} Werte je Dekade{v3}", { v0: name, v1: E_SERIES_TOLERANCE[name], v2: valuesPerDecade(name), v3: datasheet.includes(name) ? tr("· laut Datenblatt lieferbar") : '' }),
      marked: datasheet.includes(name),
      mono: true,
    })),
  ]
  const options: SegmentedOption<SeriesChoice>[] = choices.map((c) => ({
    value: c.value,
    // Name des Segments (aria-label): beginnt mit der sichtbaren Beschriftung, dann die Erklärung
    title: c.mono ? c.tip : `${c.label} – ${c.tip}`,
    label: (
      <>
        {/* Tooltip über dem ganzen Segment (Maus) – Tastatur und Screenreader bekommen den Text als Namen */}
        <Tooltip content={c.tip}>
          <span aria-hidden className="absolute inset-0 rounded-control" />
        </Tooltip>
        <span className={c.mono ? 'mono' : undefined}>{c.label}</span>
        {c.marked && <span aria-hidden className="absolute bottom-1 left-1/2 size-1 -translate-x-1/2 rounded-full bg-success" />}
      </>
    ),
  }))
  return (
    <SegmentedControl<SeriesChoice>
      fullWidth
      value={value}
      onValueChange={onValueChange}
      disabled={disabled}
      aria-label={tr(ariaLabel)}
      options={options}
    />
  )
}
