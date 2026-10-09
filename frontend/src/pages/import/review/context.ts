import { createContext, useContext } from 'react'
import type {
  DatasheetDetail,
  DeviceData,
  ExtractionData,
  ExtractionOut,
  PackageData,
  PartProposal,
} from '@/api/datasheets'
import type { CategoryDef } from '@/api/library'
import type { ChoiceDraft } from '../store'
import type { ExtractionEditor } from './useExtractionEditor'

export interface ReviewContextValue {
  ds: DatasheetDetail
  extractionOut: ExtractionOut
  extraction: ExtractionData
  /** gewähltes Bauteil (Datenblätter mit mehreren Bauteilen); bei einer Gehäusezeichnung ein leeres Bauteil */
  device: DeviceData
  deviceIndex: number
  /** Gehäusezeichnung ohne Bauteil: nur Gehäuse und Footprints (keine Identität, Varianten, Parameter, Pins) */
  packageOnly: boolean
  proposal: PartProposal | undefined
  /** Vorschlag wird (neu) berechnet – vorhandene Daten bleiben sichtbar */
  proposalFetching: boolean
  proposalError: unknown
  choices: ChoiceDraft
  setChoices: (change: (c: ChoiceDraft) => ChoiceDraft) => void
  acknowledged: string[]
  setAcknowledged: (list: string[]) => void
  categories: CategoryDef[]
  category: CategoryDef | undefined
  edit: ExtractionEditor
  /** Gehäuse der gewählten Bestellnummern (Reihenfolge des Vorschlags) */
  codes: string[]
  packageOf: (code: string) => PackageData | undefined
}

export const ReviewContext = createContext<ReviewContextValue | null>(null)

export function useReview(): ReviewContextValue {
  const value = useContext(ReviewContext)
  if (!value) throw new Error('useReview() außerhalb der Prüfansicht')
  return value
}

/** „SOIC-8 (D)“ – wie `PackageData.label` im Backend (Code entfällt, wenn er schon im Namen steht) */
export function packageLabel(pkg: Pick<PackageData, 'code' | 'name'> | undefined, fallback = ''): string {
  if (!pkg) return fallback
  if (pkg.name && pkg.code) {
    const tokens = new Set(pkg.name.split(/[^A-Za-z0-9]+/).filter(Boolean).map((t) => t.toLowerCase()))
    if (!tokens.has(pkg.code.toLowerCase()) && pkg.code.toLowerCase() !== pkg.name.toLowerCase()) return `${pkg.name} (${pkg.code})`
  }
  return pkg.name || pkg.code || fallback
}
