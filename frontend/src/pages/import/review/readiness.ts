/**
 * Bereitschaft für „Bauteile anlegen“ – dieselben Regeln wie `proposal._ready` im Backend, aber mit Gründen
 * (für die Übernahmeleiste) und ohne erneute Anfrage beim Bestätigen von Problemen.
 */
import type { FootprintProposal, PartProposal, SymbolProposal } from '@/api/datasheets'
import { pendingPicks, sameBlocker, type ChoiceDraft, type DataSection } from '../store'

export interface ReadinessReason {
  text: string
  section: DataSection
}

export interface Readiness {
  ready: boolean
  reasons: ReadinessReason[]
  /** Probleme des Vorschlags, die noch bestätigt werden müssen */
  openBlockers: string[]
  /** Bestätigte Probleme – genau die Texte des Vorschlags (gehen als `accept_issues` an die Übernahme) */
  confirmedBlockers: string[]
  /** Bestellnummern, die angelegt bzw. aktualisiert werden */
  writeCount: number
  /** davon vorhandene, die aktualisiert werden (Modus „Aktualisieren“) */
  updateCount: number
  newCount: number
  existsCount: number
  /**
   * Alle gewählten Bestellnummern sind schon angelegt und werden übersprungen – kein Problem, sondern ein fertiger
   * Stand („Bereits übernommen“); „Aktualisieren“ schreibt sie erneut.
   */
  allExist: boolean
  /** Erstes vorhandenes Bauteil (Link in die Bauteiltabelle) */
  existingPart: { table: string; partNumber: string } | null
  conflictCount: number
  symbolsWritten: number
  symbolsReused: number
  /** neu angelegte (noch nicht registrierte) Symbole/Footprints */
  symbolsNew: number
  footprintsWritten: number
  footprintsReused: number
  footprintsNew: number
  pinChanges: number
}

/**
 * Name, um den es bei einer abweichenden Pinbelegung geht: der erzeugte Name (bei einem umbenannten Symbol
 * `taken_name`) – genau der geht als `allow_pin_changes` an Vorschlag und Übernahme. `null` = kein Konflikt
 * (`SymbolProposal.taken_changes` leer).
 */
export function conflictName(s: SymbolProposal): string | null {
  if (!s.taken_changes.length) return null
  return s.taken_name ?? s.name
}

/** Schreibt die Übernahme dieses Symbol/diesen Footprint? (wie `proposal._will_write`) */
export function willWrite(item: SymbolProposal | FootprintProposal, overwrite: boolean): boolean {
  if (!item.spec) return false
  if ('source' in item ? item.source === 'existing' : item.mode === 'existing') return false
  if (!item.exists || overwrite || (item.status !== null && item.status !== 'ok')) return true
  return 'pin_changes' in item && item.pin_changes.length > 0
}

export function readiness(p: PartProposal | undefined, choices: ChoiceDraft, acknowledged: readonly string[]): Readiness {
  const out: Readiness = {
    ready: false,
    reasons: [],
    openBlockers: [],
    confirmedBlockers: [],
    writeCount: 0,
    updateCount: 0,
    newCount: 0,
    existsCount: 0,
    allExist: false,
    existingPart: null,
    conflictCount: 0,
    symbolsWritten: 0,
    symbolsReused: 0,
    symbolsNew: 0,
    footprintsWritten: 0,
    footprintsReused: 0,
    footprintsNew: 0,
    pinChanges: 0,
  }
  if (!p) return out
  const isAck = (b: string) => acknowledged.some((a) => sameBlocker(a, b))
  out.openBlockers = p.blockers.filter((b) => !isAck(b))
  out.confirmedBlockers = p.blockers.filter(isAck)
  if (!p.category) out.reasons.push({ text: 'Kategorie wählen', section: 'identitaet' })
  if (!p.variants.length) out.reasons.push({ text: 'Mindestens eine Bestellnummer auswählen', section: 'varianten' })
  for (const s of p.symbols) {
    if (!s.valid) {
      out.reasons.push({
        text: `Symbol ${s.name ? `„${s.name}“` : `für ${s.packages.join(', ') || 'das Bauteil'}`}: ${s.warnings[0] ?? 'ungültig'}`,
        section: 'pruefen',
      })
    } else {
      if (willWrite(s, choices.overwriteExisting)) out.symbolsWritten += 1
      else out.symbolsReused += 1
      if (!s.exists && s.source !== 'existing') out.symbolsNew += 1
    }
    out.pinChanges += s.pin_changes.length ? 1 : 0
  }
  for (const f of p.footprints) {
    if (!f.valid) {
      out.reasons.push({ text: `Footprint für ${f.package_label || f.package}: ${f.warnings[0] ?? 'ungültig'}`, section: 'gehaeuse' })
    } else {
      if (willWrite(f, choices.overwriteExisting)) out.footprintsWritten += 1
      else out.footprintsReused += 1
      if (!f.exists && f.mode !== 'existing') out.footprintsNew += 1
    }
  }
  for (const v of p.variants) {
    if (v.status === 'new') out.newCount += 1
    else if (v.status === 'exists') {
      out.existsCount += 1
      if (!out.existingPart && v.existing_table) out.existingPart = { table: v.existing_table, partNumber: v.part_number ?? v.mpn }
    } else out.conflictCount += 1
    if (!v.symbol) out.reasons.push({ text: `${v.mpn}: kein Symbol`, section: 'pins' })
    if (!v.footprint) out.reasons.push({ text: `${v.mpn}: kein Footprint`, section: 'gehaeuse' })
    if (v.status === 'conflict') {
      out.reasons.push({
        text: `${v.mpn}: Teilenummer schon in „${v.existing_table ?? 'anderer Kategorie'}“ vergeben`,
        section: 'varianten',
      })
      continue
    }
    if (v.status === 'exists' && choices.mode === 'skip') continue
    const errors = Object.entries(v.errors)
    if (errors.length) out.reasons.push({ text: `${v.mpn}: ${errors[0][0]} – ${errors[0][1]}`, section: 'parameter' })
    else {
      out.writeCount += 1
      if (v.status === 'exists') out.updateCount += 1
    }
  }
  const picks = pendingPicks(choices)
  const label = (code: string) => p.footprints.find((f) => f.package === code)?.package_label || code
  if (picks.symbols.length) {
    out.reasons.unshift({ text: `Vorhandenes Symbol wählen (${picks.symbols.map(label).join(', ')})`, section: 'pins' })
  }
  for (const code of picks.footprints) out.reasons.unshift({ text: `Vorhandenen Footprint für ${label(code)} wählen`, section: 'gehaeuse' })
  out.allExist = !out.reasons.length && out.writeCount === 0 && out.existsCount > 0 && out.conflictCount === 0
  out.ready = out.reasons.length === 0 && out.openBlockers.length === 0 && out.writeCount > 0
  return out
}
