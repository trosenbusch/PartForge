import { t } from '@/lib/i18n'
import type { CommitScope, FootprintProposal, PartProposal, SymbolProposal } from '@/api/datasheets'
import { plural } from '@/lib/format'
import { pendingPicks, sameBlocker, type ChoiceDraft, type DataSection } from '../store'

export interface ReadinessReason {
  text: string
  section: DataSection
}

/** „Nur Symbol/Footprint speichern“: geht es, was würde geschrieben, und wenn nicht – warum. */
export interface ScopeReadiness {
  scope: Exclude<CommitScope, 'part'>
  ready: boolean
  /** Namen, die geschrieben würden (neu, überschrieben oder mit bestätigter Pinänderung) */
  writes: string[]
  /** Alle Symbole bzw. Footprints des Vorschlags */
  total: number
  /** Erster Grund, warum es nicht geht (`null` = bereit) */
  reason: string | null
  /** Abschnitt zum Grund (Sprung aus dem Menü) */
  section: DataSection
  /** Alles schon in der Bibliothek – nichts zu schreiben */
  saved: boolean
  /** Offene bzw. bestätigte Probleme, die diesen Umfang betreffen (`BlockerTarget.scopes`) */
  openBlockers: string[]
  confirmedBlockers: string[]
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
  /** Gehäusezeichnung ohne Bauteil (`PartProposal.package_only`): nur Footprints */
  packageOnly: boolean
  symbols: ScopeReadiness
  footprints: ScopeReadiness
}

function emptyScope(scope: ScopeReadiness['scope']): ScopeReadiness {
  return {
    scope,
    ready: false,
    writes: [],
    total: 0,
    reason: null,
    section: scope === 'symbols' ? 'pins' : 'gehaeuse',
    saved: false,
    openBlockers: [],
    confirmedBlockers: [],
  }
}

function scopeReadiness(
  p: PartProposal,
  scope: ScopeReadiness['scope'],
  choices: ChoiceDraft,
  isAck: (blocker: string) => boolean,
): ScopeReadiness {
  const out = emptyScope(scope)
  const items: (SymbolProposal | FootprintProposal)[] = scope === 'symbols' ? p.symbols : p.footprints
  const noun = scope === 'symbols' ? 'Symbol' : 'Footprint'
  const targets = p.blocker_targets.filter((t) => t.scopes.includes(scope))
  out.openBlockers = targets.filter((t) => !isAck(t.blocker)).map((t) => t.blocker)
  out.confirmedBlockers = targets.filter((t) => isAck(t.blocker)).map((t) => t.blocker)
  out.total = items.length
  out.writes = items.filter((i) => i.valid && willWrite(i, choices.overwriteExisting)).flatMap((i) => (i.name ? [i.name] : []))
  const picks = pendingPicks(choices)
  const invalid = items.find((i) => !i.valid)
  if (!items.length) out.reason = t("Kein {0} im Vorschlag", { "0": String(noun) })
  else if (scope === 'symbols' && picks.symbols.length) out.reason = t("Vorhandenes Symbol wählen")
  else if (scope === 'footprints' && picks.footprints.length) out.reason = t("Vorhandenen Footprint wählen")
  else if (invalid) {
    out.reason =
      'package_label' in invalid
        ? footprintReason(invalid)
        : `Symbol${invalid.name ? ` „${invalid.name}“` : ''}: ${invalid.warnings[0] ?? t("ungültig")}`
  } else if (!out.writes.length) {
    out.saved = true
    out.reason = items.length > 1 ? t("Alle {0}s sind schon in der Bibliothek", { "0": String(noun) }) : t("{0} ist schon in der Bibliothek", { "0": String(noun) })
  } else if (out.openBlockers.length) {
    out.reason = t("{0} bestätigen", { "0": String(plural(out.openBlockers.length, 'Problem', t("Probleme"))) })
    out.section = 'pruefen'
  }
  out.ready = out.reason === null
  return out
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

/** „Footprint für SOIC-8 (D): …“ – ohne den Gehäusenamen doppelt (Meldungen des Generators beginnen oft schon damit) */
export function footprintReason(f: FootprintProposal): string {
  const label = f.package_label || f.package
  const warning = f.warnings[0] ?? t("ungültig")
  return t("Footprint für {0}: {1}", { "0": String(label), "1": String(warning.startsWith(`${label}: `) ? warning.slice(label.length + 2) : warning) })
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
    packageOnly: false,
    symbols: emptyScope('symbols'),
    footprints: emptyScope('footprints'),
  }
  if (!p) return out
  const isAck = (b: string) => acknowledged.some((a) => sameBlocker(a, b))
  out.openBlockers = p.blockers.filter((b) => !isAck(b))
  out.confirmedBlockers = p.blockers.filter(isAck)
  out.packageOnly = p.package_only
  out.symbols = scopeReadiness(p, 'symbols', choices, isAck)
  out.footprints = scopeReadiness(p, 'footprints', choices, isAck)
  if (p.package_only) {
    // Gehäusezeichnung: es gibt nur Footprints – deren Gründe gelten als offene Punkte der Ansicht
    if (out.footprints.reason && !out.footprints.saved && out.footprints.section !== 'pruefen') {
      out.reasons.push({ text: out.footprints.reason, section: 'gehaeuse' })
    }
    for (const f of p.footprints) {
      if (f.valid) {
        if (willWrite(f, choices.overwriteExisting)) out.footprintsWritten += 1
        else out.footprintsReused += 1
        if (!f.exists && f.mode !== 'existing') out.footprintsNew += 1
      }
    }
    return out
  }
  if (!p.category) out.reasons.push({ text: t("Kategorie wählen"), section: 'identitaet' })
  if (!p.variants.length) out.reasons.push({ text: t("Mindestens eine Bestellnummer auswählen"), section: 'varianten' })
  for (const s of p.symbols) {
    if (!s.valid) {
      out.reasons.push({
        text: `Symbol ${s.name ? `„${s.name}“` : t("für {0}", { "0": String(s.packages.join(', ') || t("das Bauteil")) })}: ${s.warnings[0] ?? t("ungültig")}`,
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
      out.reasons.push({ text: footprintReason(f), section: 'gehaeuse' })
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
    if (!v.symbol) out.reasons.push({ text: t("{0}: kein Symbol", { "0": String(v.mpn) }), section: 'pins' })
    if (!v.footprint) out.reasons.push({ text: t("{0}: kein Footprint", { "0": String(v.mpn) }), section: 'gehaeuse' })
    if (v.status === 'conflict') {
      out.reasons.push({
        text: t("{0}: Teilenummer schon in „{1}“ vergeben", { "0": String(v.mpn), "1": String(v.existing_table ?? t("anderer Kategorie")) }),
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
    out.reasons.unshift({ text: t("Vorhandenes Symbol wählen ({0})", { "0": String(picks.symbols.map(label).join(', ')) }), section: 'pins' })
  }
  for (const code of picks.footprints) out.reasons.unshift({ text: t("Vorhandenen Footprint für {0} wählen", { "0": String(label(code)) }), section: 'gehaeuse' })
  out.allExist = !out.reasons.length && out.writeCount === 0 && out.existsCount > 0 && out.conflictCount === 0
  out.ready = out.reasons.length === 0 && out.openBlockers.length === 0 && out.writeCount > 0
  return out
}
