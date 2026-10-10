import { t } from '@/lib/i18n'
import type { DeviceData, ExtractionData } from '@/api/datasheets'
import type { DataSection } from '../store'
import { packageLabel } from './context'

export interface PageReference {
  section: DataSection
  label: string
}

export function pageReferences(extraction: ExtractionData, device: DeviceData | undefined, translate: typeof t = t): Map<number, PageReference[]> {
  const out = new Map<number, PageReference[]>()
  const add = (pages: readonly (number | null | undefined)[], ref: PageReference) => {
    for (const p of pages) {
      if (typeof p !== 'number' || p < 1) continue
      const list = out.get(p) ?? []
      if (!list.some((r) => r.section === ref.section && r.label === ref.label)) list.push(ref)
      out.set(p, list)
    }
  }
  if (device) {
    add(
      device.parameters.map((p) => p.page),
      { section: 'parameter', label: translate("Parameter") },
    )
    add(
      device.variants.flatMap((v) => v.pages),
      { section: 'varianten', label: translate("Bestellnummern") },
    )
    for (const t of device.pin_tables) {
      add(t.pages, { section: 'pins', label: `Pins ${packageLabel(extraction.packages.find((p) => p.code === t.package), t.package)}` })
    }
  }
  for (const pkg of extraction.packages) {
    if (pkg.origin) continue // aus einem anderen Datenblatt übernommen: die Seiten gehören zu dessen PDF
    add(pkg.pages, { section: 'gehaeuse', label: translate("Maße {0}", { "0": String(packageLabel(pkg)) }) })
    add(pkg.land_pattern.pages, { section: 'gehaeuse', label: translate("Lötflächen {0}", { "0": String(packageLabel(pkg)) }) })
  }
  return out
}
