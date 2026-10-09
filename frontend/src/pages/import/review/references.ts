/** Fundstellen: welche extrahierten Angaben von welcher Datenblattseite stammen (für Sprünge in beide Richtungen). */
import type { DeviceData, ExtractionData } from '@/api/datasheets'
import type { DataSection } from '../store'
import { packageLabel } from './context'

export interface PageReference {
  section: DataSection
  label: string
}

export function pageReferences(extraction: ExtractionData, device: DeviceData | undefined): Map<number, PageReference[]> {
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
      { section: 'parameter', label: 'Parameter' },
    )
    add(
      device.variants.flatMap((v) => v.pages),
      { section: 'varianten', label: 'Bestellnummern' },
    )
    for (const t of device.pin_tables) {
      add(t.pages, { section: 'pins', label: `Pins ${packageLabel(extraction.packages.find((p) => p.code === t.package), t.package)}` })
    }
  }
  for (const pkg of extraction.packages) {
    add(pkg.pages, { section: 'gehaeuse', label: `Maße ${packageLabel(pkg)}` })
    add(pkg.land_pattern.pages, { section: 'gehaeuse', label: `Lötflächen ${packageLabel(pkg)}` })
  }
  return out
}
