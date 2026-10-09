/** Prüfungen (Issues) der Extraktion je Abschnitt – Grundlage der Konfidenz-Abzeichen. */
import type { DeviceData, ExtractionIssue } from '@/api/datasheets'
import type { DataSection } from '../store'

const SECTION_CODES: Partial<Record<DataSection, readonly string[]>> = {
  identitaet: ['no_device', 'category'],
  varianten: ['no_variants', 'variant_package'],
  pins: ['pin_duplicate', 'pin_table_package', 'pin_count', 'exposed_pad', 'exposed_pad_pin', 'no_pins'],
  gehaeuse: [
    'dim_negative',
    'dim_order',
    'dims_missing',
    'inch_values',
    'lead_width',
    'span_body',
    'height',
    'land_pattern_incomplete',
    'pitch_mismatch',
    'row_reference',
    'row_reference_half',
    'land_pattern_overlap',
    'unknown_family',
  ],
}

/** Issues des gewählten Bauteils (und der gewählten Gehäuse) für einen Abschnitt. */
export function sectionIssues(
  issues: readonly ExtractionIssue[],
  section: DataSection,
  device: DeviceData | undefined,
  codes?: readonly string[],
  packageCode?: string,
): ExtractionIssue[] {
  const wanted = SECTION_CODES[section]
  return issues.filter((i) => {
    if (wanted && !wanted.includes(i.code)) return false
    if (!wanted && Object.values(SECTION_CODES).some((list) => list?.includes(i.code))) return false
    if (i.device && device && i.device !== device.base_part) return false
    if (packageCode !== undefined) return !i.package || i.package === packageCode
    if (codes && i.package && !codes.includes(i.package)) return false
    return true
  })
}

export function severityCounts(issues: readonly ExtractionIssue[]) {
  return {
    error: issues.filter((i) => i.severity === 'error').length,
    warning: issues.filter((i) => i.severity === 'warning').length,
    info: issues.filter((i) => i.severity === 'info').length,
  }
}
