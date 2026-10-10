/**
 * Stapelbearbeitung: Symbole und Footprints an den Hausstil angleichen (Backend `partforge/altium/conform.py`,
 * `housestyle.py`, Routen `routes_housestyle.py`) und „Hausstil aus Beispielbibliothek übernehmen“ (`learnstyle.py`).
 *
 *   const rules = useHousestyleRules()                 // zuletzt in dieser Bibliothek verwendete Regeln (sonst Standard)
 *   const { job } = await housestyleApi.check({ selection, rules })   // Job „Hausstil prüfen“ → ConformReport
 *   const { job } = await housestyleApi.apply({ selection, rules })   // Job libraries.conform → ConformApplyResult
 *   const undo = useHousestyleUndo()                   // letzte Stapelbearbeitung, die sich rückgängig machen lässt
 *   const proposal = await housestyleApi.learn([pfad]) // Vorschlag für den Hausstil aus einer Beispielbibliothek
 *
 * Alles verlustfrei auf Datensatzebene: was eine Regel nicht betrifft, bleibt Byte für Byte erhalten; Namen ändern sich
 * nie. Jede Datei wird vorher nach `Backups\lib` gesichert.
 */
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from './client'
import type { Job } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

export type ConformInput = RequestBodyOf<'/api/housestyle/check', 'post'>
export type ConformRules = Filled<ResponseOf<'/api/housestyle/rules', 'get'>>
export type SymbolRules = ConformRules['symbols']
export type FootprintRules = ConformRules['footprints']
export type ConformSelection = NonNullable<ConformInput['selection']>
export type LayerRoleName = FootprintRules['roles'][string][string]
export type StyleProposal = Filled<ResponseOf<'/api/housestyle/learn', 'post'>>
export type StyleFinding = StyleProposal['findings'][number]
export type UndoInfo = Filled<NonNullable<ResponseOf<'/api/housestyle/undo', 'get'>>>

export interface ConformChange {
  rule: string
  message: string
}

export interface ConformComponentReport {
  kind: 'symbol' | 'footprint'
  name: string
  library: string
  source: string
  changes: ConformChange[]
  problems: string[]
}

export interface ConformLayerRole {
  layer: string
  role: LayerRoleName
  reason: 'kind' | 'name' | 'content' | 'manual' | 'default'
  primitives: number
  name: string | null
  /** Lagentyp im Bibliothekskopf (MECHKIND) */
  kind?: string | null
  /** Lage des Hausstils mit demselben Lagentyp – „unverändert“ wandert dorthin */
  target?: string | null
  /** Hinweis: wohin die Lage wandert bzw. dass sie auf einer Lage des Hausstils liegt */
  note?: string | null
}

export interface ConformLibraryReport {
  library: string
  kind: 'schlib' | 'pcblib'
  components: number
  selected: number
  affected: number
  roles: ConformLayerRole[]
  header: string[]
  fonts: string[]
  refusal: string | null
  problem: string | null
}

/** `job.result` von „Hausstil prüfen“ (`housestyle.check`) */
export interface ConformReport {
  checked: number
  affected: number
  summary: Record<string, number>
  libraries: ConformLibraryReport[]
  components: ConformComponentReport[]
  truncated: boolean
  message: string
}

/** `job.result` von „Hausstil anwenden“ (`libraries.conform`) */
export interface ConformApplyResult {
  components: number
  libraries: string[]
  skipped: { library: string; message: string }[]
  errors: { library: string; message: string }[]
  undo: string | null
  report: ConformReport | null
  message: string
}

/** `job.result` von „Stapelbearbeitung rückgängig machen“ */
export interface ConformUndoResult {
  restored: string[]
  skipped: { library: string; message: string }[]
  message: string
}

/** Regeln mit deutscher Bezeichnung (wie `conform.RULE_LABELS`) */
export const RULE_LABELS: Record<string, string> = {
  fonts: 'Schriften',
  pin_length: 'Pinlängen',
  prefix: 'Bezeichner-Präfix',
  colors: 'Farben',
  layers: 'Lagen',
  widths: 'Linienbreiten',
  texts: 'Texte',
  add_texts: 'Fehlende Texte',
  add_center: 'Bauteilmitte',
  header: 'Lagen-Kopf',
}

/** Rollen der Footprint-Lagen (wie `conform.ROLE_LABELS`) */
export const ROLE_LABELS: Record<LayerRoleName, string> = {
  silkscreen: 'Bestückungsdruck',
  assembly: 'Bestückungszeichnung',
  designator: 'Bezeichner',
  comment: 'Wert',
  courtyard: 'Courtyard',
  component_center: 'Bauteilmitte',
  component_outline: 'Bauteilumriss',
  body3d: '3D-Körper',
  keep: 'unverändert',
}

/** Woher die Rolle einer Quell-Lage stammt */
export const ROLE_REASON_LABELS: Record<ConformLayerRole['reason'], string> = {
  kind: 'Lagentyp',
  name: 'Lagenname',
  content: 'Inhalt',
  manual: 'von Hand',
  default: '–',
}

export const DEFAULT_RULES: ConformRules = {
  symbols: { fonts: true, pin_length: true, prefix: true, prefix_map: { IC: 'U' }, colors: false },
  footprints: {
    layers: true,
    widths: true,
    silk_width: false,
    texts: true,
    add_texts: true,
    add_center: true,
    header: true,
    roles: {},
  },
}

export const housestyleKeys = {
  all: ['housestyle'] as const,
  rules: ['housestyle', 'rules'] as const,
  undo: ['housestyle', 'undo'] as const,
}

export const housestyleApi = {
  rules: (signal?: AbortSignal) => api.get<ConformRules>('/api/housestyle/rules', { signal }),
  saveRules: (rules: ConformRules) => api.put<ConformRules>('/api/housestyle/rules', rules),
  check: (body: ConformInput) => api.post<{ job: Job<ConformReport> }>('/api/housestyle/check', body),
  apply: (body: ConformInput) => api.post<{ job: Job<ConformApplyResult> }>('/api/housestyle/apply', body),
  undoInfo: (signal?: AbortSignal) => api.get<UndoInfo | null>('/api/housestyle/undo', { signal }),
  undo: () => api.post<{ job: Job<ConformUndoResult> }>('/api/housestyle/undo'),
  learn: (paths: string[]) => api.post<StyleProposal>('/api/housestyle/learn', { paths }),
}

export function useHousestyleRules(enabled = true) {
  return useQuery({
    queryKey: housestyleKeys.rules,
    queryFn: ({ signal }) => housestyleApi.rules(signal),
    enabled,
    staleTime: 60_000,
  })
}

export function useHousestyleUndo(enabled = true) {
  return useQuery({
    queryKey: housestyleKeys.undo,
    queryFn: ({ signal }) => housestyleApi.undoInfo(signal),
    enabled,
    staleTime: 10_000,
  })
}

/** Hausstil aus Beispielbibliotheken ableiten (nur Vorschlag – gespeichert wird über die Einstellungen) */
export function useLearnStyle() {
  return useMutation({
    mutationFn: (paths: string[]) => housestyleApi.learn(paths),
    meta: { errorTitle: 'Beispielbibliothek konnte nicht ausgewertet werden' },
  })
}
