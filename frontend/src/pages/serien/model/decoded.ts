/** Gelesene Teilenummer → Auswahl im Assistenten (Baugröße, Toleranz, TK, Verpackung, Spannung). */
import type { DecodedMpn, SeriesTemplate } from '@/api/series'
import type { SeriesSettings } from './settings'
import { packagingVariable, tcrChoices, toleranceChoices, variable, voltageChoices } from './template'

export function settingsFromDecoded(t: SeriesTemplate, d: DecodedMpn, base: SeriesSettings): SeriesSettings {
  const next: SeriesSettings = { ...base, valueMode: 'range' }
  if (d.size) next.sizes = [d.size]
  const tolerances = toleranceChoices(t)
  if (t.kind === 'catalog') {
    const text = d.attrs.tolerance
    if (text && tolerances.some((o) => o.value === text)) next.tolerance = text
    const volts = d.attrs.voltage
    if (volts && voltageChoices(t).some((o) => o.value === volts)) next.voltages = [volts]
    return next
  }
  const tol = d.codes.tolerance
  if (tol && tolerances.some((o) => o.value === tol)) next.tolerance = tol
  const tcr = tcrChoices(t)
  if (tcr?.kind === 'code' && d.codes.tcr && tcr.options.some((o) => o.value === d.codes.tcr)) next.tcr = d.codes.tcr
  if (tcr?.kind === 'filter' && d.attrs.tcr && tcr.options.some((o) => o.value === d.attrs.tcr)) next.tcr = d.attrs.tcr
  const pack = packagingVariable(t)
  if (pack && d.codes[pack.name] !== undefined) next.packaging = d.codes[pack.name] || null
  if (variable(t, 'voltage') && d.codes.voltage && voltageChoices(t).some((o) => o.value === d.codes.voltage)) {
    next.voltages = [d.codes.voltage]
  }
  if (d.jumper) next.includeJumper = true
  return next
}
