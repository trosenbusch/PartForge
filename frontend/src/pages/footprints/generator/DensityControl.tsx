import { t as tr, useI18n } from '@/components/preview/i18n'
/** Dichte nach IPC-7351 („Klein (L) · Nominal (N) · Groß (M)“) mit deutscher Erklärung; Hausstil-Vorgabe ist markiert. */
import { Badge, Button, SegmentedControl } from '@/components/ui'
import { DENSITY_INFO, DENSITY_ORDER, densityLabel } from '../lib/calc'
import { SectionLabel } from '../parts'
import type { Density } from './store'

export function DensityControl({
  value,
  styleDensity,
  onChange,
}: {
  value: Density
  styleDensity: Density
  onChange: (density: Density) => void
}) {
  useI18n()
  const info = DENSITY_INFO[value]
  return (
    <section aria-labelledby="fp-density-label" className="flex flex-col gap-2">
      <SectionLabel
        id="fp-density-label"
        actions={
          value === styleDensity ? (
            <Badge size="sm" variant="outline">
              {tr("Hausstil")}
            </Badge>
          ) : (
            <Button variant="ghost" size="xs" onClick={() => onChange(styleDensity)}>
              {tr("Hausstil:")}{' '}{densityLabel(styleDensity)}
            </Button>
          )
        }
      >
        {tr("Dichte · IPC-7351")}
      </SectionLabel>
      <SegmentedControl
        fullWidth
        size="sm"
        aria-label={tr("Dichte")}
        value={value}
        onValueChange={onChange}
        options={DENSITY_ORDER.map((d) => ({
          value: d,
          label: (
            <span className="flex items-baseline gap-1">
              <span>{tr(DENSITY_INFO[d].name)}</span>
              <span className="mono text-fg-subtle">({d})</span>
            </span>
          ),
        }))}
      />
      <p className="text-2xs leading-4 text-fg-muted">
        {tr(info.text)}{' '}
        <span className="whitespace-nowrap text-fg-subtle">IPC {info.level}</span>
      </p>
    </section>
  )
}
