import { t as tr } from '@/components/preview/i18n'
/**
 * Zustand des Footprint-Generators (zustand, im Browser gespeichert): Familie, Vorlage, Formularwerte, Dichte,
 * Herstellerempfehlung, Name/Beschreibung – plus Entwürfe je Familie (ein Familienwechsel verliert keine Eingaben).
 *
 * Verlauf: Jede Änderung legt den vorigen Stand in einen Rückgängig-Verlauf (Strg+Z / Strg+Y). Tippen in einem Feld
 * zählt als ein Schritt. Ersetzt eine Aktion geänderte Werte (Vorlage laden, Parameter eines gespeicherten
 * Footprints, Zurücksetzen), erscheint zusätzlich ein Hinweis mit „Rückgängig“.
 *
 * Selektoren (Gehäusetyp, Baugröße, Bauteilart, Pinzahl …): Solange die Werte einer Vorlage unverändert sind,
 * wechselt eine neue Auswahl direkt zur passenden Vorlage (SOIC-8 → Pins 14 → SOIC-14). Sind Werte angepasst,
 * bleibt alles stehen und die passende Vorlage wird nur vorgeschlagen.
 */
import { toast } from 'sonner'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { FootprintDensity, FootprintFamily, FootprintPreset } from '@/api/footprints'
import { densityLabel } from '../lib/calc'
import { closestPreset, matchPreset, preferredPreset, presetValues } from '../lib/families'
import {
  changedParams,
  normalizeParams,
  SELECTOR_PARAMS,
  STRONG_SELECTORS,
  withoutDefaults,
  type ParamValue,
  type ParamValues,
} from '../lib/params'

export type Density = FootprintDensity
export type LandReference = 'center' | 'inner' | 'outer'
export type ChangeKind = 'typing' | 'discrete'

/** Herstellerempfehlung (Land Pattern aus dem Datenblatt) statt IPC-Berechnung */
export interface LandPatternState {
  enabled: boolean
  pad_width: number | null
  pad_length: number | null
  row_spacing: number | null
  reference: LandReference
  row_spacing_y: number | null
  ep_width: number | null
  ep_length: number | null
}

export const EMPTY_LAND: LandPatternState = {
  enabled: false,
  pad_width: null,
  pad_length: null,
  row_spacing: null,
  reference: 'center',
  row_spacing_y: null,
  ep_width: null,
  ep_length: null,
}

/** Eigener Name/eigene Beschreibung statt der erzeugten (`FootprintRequest.name/description`) */
export interface NameOverrides {
  name: string | null
  description: string | null
}

export const NO_OVERRIDES: NameOverrides = { name: null, description: null }

interface FamilyDraft {
  preset: string | null
  values: ParamValues
  landPattern: LandPatternState
  overrides?: NameOverrides
}

export interface GeneratorNotice {
  text: string
  /** Zeitstempel – derselbe Text erscheint erneut */
  at: number
}

/** Gespeicherte Erzeugungsparameter eines Footprints (`FootprintSpec.generator`) */
export interface GeneratorSnapshot {
  family?: unknown
  params?: unknown
  density?: unknown
  rounding?: unknown
  preset?: unknown
  land_pattern?: unknown
}

interface GeneratorData {
  family: string | null
  preset: string | null
  values: ParamValues
  /** null = Dichte des Hausstils */
  density: Density | null
  landPattern: LandPatternState
  overrides: NameOverrides
  drafts: Record<string, FamilyDraft>
}

/** Ein Schritt im Verlauf: der Stand vor der Änderung */
interface HistoryEntry {
  snap: GeneratorData
  label: string
  /** Gleicher Schlüssel kurz hintereinander = derselbe Schritt (Tippen in einem Feld) */
  key: string | null
  at: number
}

interface GeneratorState extends GeneratorData {
  lastChange: ChangeKind
  notice: GeneratorNotice | null
  /** Vorlage, die zu den geänderten Selektoren passt (Werte sind angepasst – nur Vorschlag) */
  suggestion: string | null
  past: HistoryEntry[]
  future: HistoryEntry[]

  selectFamily: (family: FootprintFamily, preset?: FootprintPreset | null) => void
  selectPreset: (family: FootprintFamily, preset: FootprintPreset) => void
  setParam: (family: FootprintFamily, name: string, value: ParamValue, opts?: { mode?: ChangeKind; commit?: boolean }) => void
  resetParam: (family: FootprintFamily, name: string) => void
  /** Alle Werte auf die Vorlage (bzw. die Standardwerte) zurücksetzen */
  resetAll: (family: FootprintFamily) => void
  setDensity: (density: Density) => void
  setLandPattern: (patch: Partial<LandPatternState>, mode?: ChangeKind) => void
  setOverrides: (patch: Partial<NameOverrides>, mode?: ChangeKind) => void
  /**
   * Footprint aus gespeicherten Generator-Parametern laden („Im Generator öffnen“, Alias ohne Vorlage); `name` = eigener
   * Name des gespeicherten Footprints (wird als Namensvorgabe übernommen, sonst gilt der erzeugte Name)
   */
  loadSnapshot: (
    family: FootprintFamily,
    snapshot: GeneratorSnapshot,
    opts?: { styleRounding?: string | null; notice?: string | null; label?: string; name?: string | null },
  ) => void
  /** Letzten Schritt zurücknehmen; liefert die Beschreibung des Schritts (oder null) */
  undo: () => string | null
  redo: () => string | null
  showNotice: (text: string) => void
  dismissNotice: () => void
}

const HISTORY_LIMIT = 60
const COALESCE_MS = 1500

const notice = (text: string): GeneratorNotice => ({ text, at: Date.now() })

function findPreset(family: FootprintFamily, key: string | null | undefined): FootprintPreset | null {
  if (!key) return null
  return family.presets.find((p) => p.key.toLowerCase() === key.toLowerCase()) ?? null
}

/** Unveränderte Vorlage (oder ganz leeres Formular)? `except` = gerade geänderter Selektor zählt nicht mit */
function isPristine(family: FootprintFamily, presetKey: string | null, values: ParamValues, except?: string): boolean {
  const preset = findPreset(family, presetKey)
  if (!preset) return Object.keys(values).filter((k) => k !== except).length === 0
  return changedParams(family.params, values, presetValues(family, preset)).filter((n) => n !== except).length === 0
}

/** Wie viele eigene Eingaben ein Stand gegenüber seiner Vorlage hat (Werte, Herstellerempfehlung, Name) */
function editCount(family: FootprintFamily, d: Pick<FamilyDraft, 'preset' | 'values' | 'landPattern' | 'overrides'>): number {
  const preset = findPreset(family, d.preset)
  const values = preset
    ? changedParams(family.params, d.values, presetValues(family, preset)).length
    : Object.keys(d.values).length
  const ov = d.overrides ?? NO_OVERRIDES
  return values + (d.landPattern.enabled ? 1 : 0) + (ov.name ? 1 : 0) + (ov.description ? 1 : 0)
}

function landFromSnapshot(raw: unknown): LandPatternState {
  if (!raw || typeof raw !== 'object') return EMPTY_LAND
  const r = raw as Record<string, unknown>
  const num = (v: unknown) =>
    typeof v === 'number' && Number.isFinite(v)
      ? v
      : typeof v === 'string' && v.trim() && Number.isFinite(Number(v.replace(',', '.')))
        ? Number(v.replace(',', '.'))
        : null
  const ref = String(r.reference ?? r.row_spacing_reference ?? 'center').toLowerCase()
  return {
    enabled: true,
    pad_width: num(r.pad_width),
    pad_length: num(r.pad_length),
    row_spacing: num(r.row_spacing),
    reference: ref.startsWith('inner') ? 'inner' : ref.startsWith('outer') ? 'outer' : 'center',
    row_spacing_y: num(r.row_spacing_y),
    ep_width: num(r.ep_width),
    ep_length: num(r.ep_length),
  }
}

const snapshotOf = (s: GeneratorData): GeneratorData => ({
  family: s.family,
  preset: s.preset,
  values: s.values,
  density: s.density,
  landPattern: s.landPattern,
  overrides: s.overrides,
  drafts: s.drafts,
})

const sameData = (a: GeneratorData, b: GeneratorData) => JSON.stringify(a) === JSON.stringify(b)

/** Hinweis „… geladen – Rückgängig“, wenn dabei eigene Eingaben ersetzt wurden */
function announceReplaced(label: string, lost: number) {
  if (lost <= 0) return
  toast(label, {
    id: 'fp-undo',
    description: lost === 1 ? tr('1 eigene Eingabe ersetzt') : tr("{value0} eigene Eingaben ersetzt", { value0: String(lost) }),
    action: { label: tr('Rückgängig'), onClick: () => void useGenerator.getState().undo() },
  })
}

export const useGenerator = create<GeneratorState>()(
  persist(
    (set, get) => {
      /** Änderung übernehmen und – falls sich etwas ändert – den vorigen Stand in den Verlauf legen */
      const commit = (label: string, key: string | null, patch: Partial<GeneratorState>) => {
        const s = get()
        const before = snapshotOf(s)
        const after = snapshotOf({ ...s, ...patch })
        if (sameData(before, after)) {
          set(patch)
          return
        }
        const last = s.past[s.past.length - 1]
        const now = Date.now()
        const past =
          key && last && last.key === key && now - last.at < COALESCE_MS
            ? [...s.past.slice(0, -1), { ...last, at: now }]
            : [...s.past, { snap: before, label, key, at: now }].slice(-HISTORY_LIMIT)
        set({ ...patch, past, future: [] })
      }

      /** Entwürfe inkl. des aktuellen Stands der aktuellen Familie */
      const withCurrentDraft = (s: GeneratorState): Record<string, FamilyDraft> =>
        s.family
          ? { ...s.drafts, [s.family]: { preset: s.preset, values: s.values, landPattern: s.landPattern, overrides: s.overrides } }
          : { ...s.drafts }

      return {
        family: null,
        preset: null,
        values: {},
        density: null,
        landPattern: EMPTY_LAND,
        overrides: NO_OVERRIDES,
        drafts: {},
        lastChange: 'discrete',
        notice: null,
        suggestion: null,
        past: [],
        future: [],

        selectFamily: (family, preset) => {
          const s = get()
          const drafts = withCurrentDraft(s)
          const draft = drafts[family.key]
          let next: FamilyDraft
          let lost = 0
          if (preset) {
            // Vorlage ausdrücklich gewählt: ersetzt den Entwurf dieser Familie (rückgängig machbar)
            if (draft) lost = editCount(family, draft)
            next = { preset: preset.key, values: presetValues(family, preset), landPattern: EMPTY_LAND, overrides: NO_OVERRIDES }
          } else if (draft) next = draft
          else {
            const p = preferredPreset(family)
            next = { preset: p?.key ?? null, values: p ? presetValues(family, p) : {}, landPattern: EMPTY_LAND, overrides: NO_OVERRIDES }
          }
          const label = preset ? tr("Vorlage „{value0}“ geladen", { value0: String(preset.key) }) : tr("Familie {value0} gewählt", { value0: String(family.label.replace(/\s*\([^)]*\)\s*$/, '')) })
          commit(label, null, {
            family: family.key,
            preset: next.preset,
            values: next.values,
            landPattern: next.landPattern,
            overrides: next.overrides ?? NO_OVERRIDES,
            drafts,
            lastChange: 'discrete',
            notice: null,
            suggestion: null,
          })
          if (preset) announceReplaced(label, lost)
        },

        selectPreset: (family, preset) => {
          const s = get()
          const lost = s.family === family.key ? editCount(family, s) : 0
          const label = tr("Vorlage „{value0}“ geladen", { value0: String(preset.key) })
          commit(label, null, {
            family: family.key,
            preset: preset.key,
            values: presetValues(family, preset),
            landPattern: s.family === family.key ? s.landPattern : EMPTY_LAND,
            overrides: NO_OVERRIDES,
            lastChange: 'discrete',
            notice: null,
            suggestion: null,
          })
          // Herstellerempfehlung bleibt bei einem Vorlagenwechsel erhalten – sie zählt nicht als ersetzt
          announceReplaced(label, lost - (s.landPattern.enabled ? 1 : 0))
        },

        setParam: (family, name, value, opts = {}) => {
          const { mode = 'typing', commit: applySelectors = true } = opts
          const s = get()
          const spec = family.params.find((p) => p.name === name)
          const label = tr("{value0} geändert", { value0: tr(spec?.label ?? name) })
          const key = mode === 'typing' ? `param:${name}` : null
          const values: ParamValues = { ...s.values }
          if (value === null || value === undefined || value === '') delete values[name]
          else values[name] = value
          let preset = s.preset
          let note: GeneratorNotice | null = null
          let suggestion: string | null = null

          if (spec && applySelectors && SELECTOR_PARAMS.includes(name) && spec.kind !== 'tol') {
            const pristine = isPristine(family, s.preset, s.values, name)
            const match = matchPreset(family, values)
            if (match && match.key !== s.preset) {
              if (pristine) {
                commit(label, key, {
                  preset: match.key,
                  values: presetValues(family, match),
                  lastChange: 'discrete',
                  notice: notice(tr("Vorlage „{value0}“ übernommen", { value0: String(match.key) })),
                  suggestion: null,
                })
                return
              }
              suggestion = match.key
            } else if (!match && pristine && spec.kind === 'enum' && STRONG_SELECTORS.includes(name)) {
              // Keine Vorlage für diese Auswahl: Maße aus den Standardtabellen der Familie ableiten lassen
              for (const p of family.params) if (p.kind === 'tol') delete values[p.name]
              preset = null
              note = notice(tr('Keine Vorlage für diese Auswahl – Maße kommen aus den Standardtabellen.'))
            }
          }
          commit(label, key, { values, preset, lastChange: mode, notice: note ?? s.notice, suggestion })
        },

        resetParam: (family, name) => {
          const s = get()
          const preset = findPreset(family, s.preset)
          const base = preset ? presetValues(family, preset) : {}
          const values = { ...s.values }
          if (base[name] === undefined) delete values[name]
          else values[name] = base[name]
          const spec = family.params.find((p) => p.name === name)
          commit(tr("{value0} zurückgesetzt", { value0: tr(spec?.label ?? name) }), null, { values, lastChange: 'discrete', suggestion: null })
        },

        resetAll: (family) => {
          const s = get()
          const preset = findPreset(family, s.preset)
          const lost = changedParams(family.params, s.values, preset ? presetValues(family, preset) : {}).length
          const label = preset ? tr("Werte von „{value0}“ wiederhergestellt", { value0: String(preset.key) }) : tr('Werte zurückgesetzt')
          commit(label, null, {
            values: preset ? presetValues(family, preset) : {},
            lastChange: 'discrete',
            notice: null,
            suggestion: null,
          })
          announceReplaced(label, lost)
        },

        setDensity: (density) => commit(tr("Dichte {value0}", { value0: String(densityLabel(density)) }), null, { density, lastChange: 'discrete' }),

        setLandPattern: (patch, mode = 'typing') =>
          commit(tr('Herstellerempfehlung geändert'), mode === 'typing' ? `land:${Object.keys(patch).join(',')}` : null, {
            landPattern: { ...get().landPattern, ...patch },
            lastChange: mode,
          }),

        setOverrides: (patch, mode = 'discrete') =>
          commit(patch.name !== undefined ? tr('Name geändert') : tr('Beschreibung geändert'), mode === 'typing' ? `ov:${Object.keys(patch).join(',')}` : null, {
            overrides: { ...get().overrides, ...patch },
            lastChange: 'discrete',
          }),

        loadSnapshot: (family, snapshot, opts = {}) => {
          const s = get()
          const drafts = withCurrentDraft(s)
          const draft = drafts[family.key]
          const lost = draft ? editCount(family, draft) : 0
          const params = snapshot.params && typeof snapshot.params === 'object' ? (snapshot.params as Record<string, unknown>) : {}
          const values = withoutDefaults(family.params, normalizeParams(family.params, params))
          const rounding = typeof snapshot.rounding === 'string' ? snapshot.rounding : null
          if (rounding && family.params.some((p) => p.name === 'rounding') && values.rounding === undefined && rounding !== opts.styleRounding) {
            values.rounding = rounding
          }
          const presetKey = typeof snapshot.preset === 'string' ? snapshot.preset : null
          const preset = findPreset(family, presetKey) ?? closestPreset(family, values)
          const density = snapshot.density === 'L' || snapshot.density === 'N' || snapshot.density === 'M' ? snapshot.density : s.density
          const label = opts.label ?? tr('Gespeicherte Parameter geladen')
          commit(label, null, {
            family: family.key,
            preset: preset?.key ?? null,
            values,
            density,
            landPattern: snapshot.land_pattern ? landFromSnapshot(snapshot.land_pattern) : EMPTY_LAND,
            overrides: opts.name?.trim() ? { name: opts.name.trim(), description: null } : NO_OVERRIDES,
            drafts,
            lastChange: 'discrete',
            notice: opts.notice === null ? null : notice(opts.notice ?? tr('Parameter des gespeicherten Footprints geladen')),
            suggestion: null,
          })
          announceReplaced(label, lost)
        },

        undo: () => {
          const s = get()
          const entry = s.past[s.past.length - 1]
          if (!entry) return null
          set({
            ...entry.snap,
            past: s.past.slice(0, -1),
            future: [...s.future, { snap: snapshotOf(s), label: entry.label, key: null, at: Date.now() }],
            lastChange: 'discrete',
            notice: null,
            suggestion: null,
          })
          return entry.label
        },

        redo: () => {
          const s = get()
          const entry = s.future[s.future.length - 1]
          if (!entry) return null
          set({
            ...entry.snap,
            future: s.future.slice(0, -1),
            past: [...s.past, { snap: snapshotOf(s), label: entry.label, key: null, at: Date.now() }].slice(-HISTORY_LIMIT),
            lastChange: 'discrete',
            notice: null,
            suggestion: null,
          })
          return entry.label
        },

        showNotice: (text) => set({ notice: notice(text) }),

        dismissNotice: () => set({ notice: null }),
      }
    },
    {
      name: 'pf-footprint-generator',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: (s): GeneratorData => snapshotOf(s),
    },
  ),
)

/** Parameter, die von der gewählten Vorlage abweichen (für „geändert“-Hinweise) */
export function changedFromPreset(family: FootprintFamily | null, presetKey: string | null, values: ParamValues): string[] {
  if (!family) return []
  const preset = findPreset(family, presetKey)
  if (!preset) return []
  return changedParams(family.params, values, presetValues(family, preset))
}

/** Schritt zurück/vor mit kurzer Rückmeldung (Strg+Z / Strg+Y, Befehlspalette) */
export function undoWithFeedback(direction: 'undo' | 'redo'): void {
  const st = useGenerator.getState()
  const label = direction === 'undo' ? st.undo() : st.redo()
  if (!label) {
    toast(direction === 'undo' ? tr('Nichts rückgängig zu machen') : tr('Nichts zu wiederholen'), { id: 'fp-undo' })
    return
  }
  toast(direction === 'undo' ? tr('Rückgängig gemacht') : tr('Wiederholt'), {
    id: 'fp-undo',
    description: label,
    action:
      direction === 'undo'
        ? { label: tr('Wiederholen'), onClick: () => undoWithFeedback('redo') }
        : { label: tr('Rückgängig'), onClick: () => undoWithFeedback('undo') },
  })
}

export { findPreset }
