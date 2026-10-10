/**
 * API der Einstellungsseite: Bibliothekseinstellungen (Änderung auf den frischen Serverstand angewendet),
 * Sicherungen, Schema-Designer (Kategorien und Felder), Vorlagen-Vorschau (gespeicherte Vorlagen und beliebige
 * Entwürfe über `render-template`), Symboltypen, Systemstatus (Altium, KI-Verbindungstest) und Lagenaufbau.
 *
 * Typen kommen aus dem OpenAPI-Schema (`schema.d.ts`). Der Altium-Status teilt sich Abfrage und Cache mit der
 * Altium-Seite (`@/api/altium`).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { api, ApiError } from './client'
import { altiumApi, altiumKeys, useAltiumStatus as useSharedAltiumStatus } from './altium'
import { trackJob } from './jobs'
import { libraryKeys, type CategoryDef, type FieldDef } from './library'
import { queryClient } from './queryClient'
import { systemApi, systemKeys, type Job, type LayerMap, type WorkspaceInfo, type WorkspaceSettings } from './system'
import type { Filled, RequestBodyOf, ResponseOf } from './types'

// --------------------------------------------------------------------------- Typen

export type BackupInfo = Filled<ResponseOf<'/api/backups', 'get'>>[number]
export type FieldKindInfo = Filled<ResponseOf<'/api/field-kinds', 'get'>>[number]
export type FieldKind = FieldDef['kind']
export type SymbolKindInfo = Filled<ResponseOf<'/api/symbols/kinds', 'get'>>[number]
export type CategoryCreateInput = RequestBodyOf<'/api/categories', 'post'>
export type CategoryPatch = RequestBodyOf<'/api/categories/{table}', 'patch'>
export type FieldPatch = RequestBodyOf<'/api/categories/{table}/fields/{column}', 'patch'>
export type FieldInput = RequestBodyOf<'/api/categories/{table}/fields', 'post'>
export type DeleteCategoryResult = Filled<ResponseOf<'/api/categories/{table}', 'delete'>>
export type AltiumStatus = Filled<ResponseOf<'/api/altium/status', 'get'>>
export type AltiumBackendStatus = AltiumStatus['backends'][number]
export type AiTestResult = Filled<ResponseOf<'/api/ai/test', 'post'>>
export type RenderTemplateResult = Filled<ResponseOf<'/api/parts/{table}/render-template', 'post'>>
/** „Texte neu erzeugen“: geänderte Bauteile, Sicherung (mehr als 20) und `audit_ids` für „Rückgängig“ */
export type RegenerateTextsResult = Filled<ResponseOf<'/api/parts/{table}/regenerate-texts', 'post'>>
export type LayerStackInfo = Filled<ResponseOf<'/api/libraries/layer-stack', 'get'>>
export type MechLayer = LayerStackInfo['stack']['layers'][string]
/** Ein Lagensatz (Altium „Layer Set“): Name, Lagenkürzel wie `TopOverlay`/`Mechanical9`, aktive Lage, Optionen */
export type LayerSetDef = Filled<ResponseOf<'/api/libraries/layer-set/builtin', 'post'>>
export type LayerSetFile = Filled<ResponseOf<'/api/libraries/layer-set/parse', 'post'>>
export type LibraryStatsInfo = Filled<ResponseOf<'/api/stats', 'get'>>
export type LibraryFileInfo = Filled<ResponseOf<'/api/libraries/files', 'get'>>[number]

/** Eine Zeile einer Kategorietabelle (alle Werte sind Text) */
export type PartRow = Record<string, string | null>

interface PartsPage {
  rows: PartRow[]
  total: number
}

export type { CategoryDef, FieldDef, WorkspaceInfo, WorkspaceSettings }

// --------------------------------------------------------------------------- Query-Keys

export const settingsKeys = {
  backups: ['backups', 'list'] as const,
  categoryTemplates: ['categories', 'templates'] as const,
  fieldKinds: ['categories', 'field-kinds'] as const,
  symbolKinds: ['symbols', 'kinds'] as const,
  samples: (table: string) => ['parts', 'settings-samples', table] as const,
  rendered: (table: string, values: PartRow | null) => ['parts', 'render-templates', table, values] as const,
  /** Entwurf einer Vorlage (Wert → Kommentar → Beschreibung) für ein Beispielbauteil */
  draftRendered: (table: string, templates: readonly string[], values: PartRow | null) =>
    ['parts', 'render-template', table, templates, values] as const,
  libraryFiles: ['libraries', 'files', 'settings'] as const,
  layerStack: ['libraries', 'layer-stack'] as const,
  layerStackFile: (path: string) => ['libraries', 'layer-stack', 'parse', path] as const,
  layerSetFile: (path: string) => ['libraries', 'layer-set', 'parse', path] as const,
  builtinLayerSet: (layers: LayerMap, current: boolean) => ['libraries', 'layer-set', 'builtin', layers, current] as const,
}

// --------------------------------------------------------------------------- Bibliothekseinstellungen

const NO_WORKSPACE = 'Es ist keine Bibliothek geöffnet.'
const OTHER_WORKSPACE =
  'Inzwischen ist eine andere Bibliothek geöffnet – die Änderungen wurden nicht gespeichert, damit sie nicht in der falschen Bibliothek landen.'

/**
 * Prüft vor einer Schreibaktion, dass noch die Bibliothek geöffnet ist, zu der ein Entwurf gehört
 * (`root` = Bibliotheksordner beim Bearbeiten). Wirft sonst einen 409-Fehler mit deutscher Meldung.
 */
export async function assertWorkspaceRoot(root: string, method: string, path: string): Promise<WorkspaceInfo> {
  const fresh = await systemApi.getWorkspace()
  if (!fresh) throw new ApiError(409, NO_WORKSPACE, { code: 'no_workspace', message: NO_WORKSPACE }, method, path)
  if (fresh.root !== root) throw new ApiError(409, OTHER_WORKSPACE, { code: 'workspace_changed', message: OTHER_WORKSPACE }, method, path)
  return fresh
}

/**
 * Bibliothekseinstellungen ändern, ohne Änderungen anderer Bereiche zu überschreiben: frisch laden,
 * `change` anwenden, speichern (PUT ersetzt das ganze Objekt). `root` = Bibliothek, zu der der Entwurf gehört –
 * ist inzwischen eine andere geöffnet, wird nichts gespeichert.
 */
export async function updateWorkspaceSettings({
  change,
  root,
}: {
  change: (current: WorkspaceSettings) => WorkspaceSettings
  root: string
}): Promise<WorkspaceInfo> {
  const fresh = await assertWorkspaceRoot(root, 'PUT', '/api/workspace/settings')
  return api.put<WorkspaceInfo>('/api/workspace/settings', change(fresh.settings))
}

/** Hausstil und Namen beeinflussen Vorschauen, Symbolnamen und Lagenhinweise → diese neu laden */
function invalidateStyleDependent(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: ['footprints'] })
  void qc.invalidateQueries({ queryKey: ['symbols'] })
  void qc.invalidateQueries({ queryKey: settingsKeys.layerStack })
}

export function useUpdateWorkspaceSettings() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: updateWorkspaceSettings,
    meta: { errorTitle: 'Bibliothekseinstellungen konnten nicht gespeichert werden' },
    onSuccess: (info) => {
      qc.setQueryData(systemKeys.workspace, info)
      void qc.invalidateQueries({ queryKey: systemKeys.health })
      void qc.invalidateQueries({ queryKey: systemKeys.recent })
      invalidateStyleDependent(qc)
    },
  })
}

export function useLibraryStatsSummary(enabled = true) {
  return useQuery({
    queryKey: libraryKeys.stats,
    queryFn: ({ signal }) => api.get<LibraryStatsInfo>('/api/stats', { signal }),
    enabled,
    staleTime: 15_000,
  })
}

// --------------------------------------------------------------------------- Sicherungen

export function useBackups(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.backups,
    queryFn: ({ signal }) => api.get<BackupInfo[]>('/api/backups', { signal }),
    enabled,
    staleTime: 5_000,
  })
}

export function useCreateBackup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (reason: string) => api.post<BackupInfo>('/api/backups', { reason }),
    meta: { errorTitle: 'Sicherung konnte nicht erstellt werden' },
    onSuccess: () => void qc.invalidateQueries({ queryKey: settingsKeys.backups }),
  })
}

export function useRestoreBackup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (name: string) =>
      api.post<{ ok: boolean; restored: string; job?: Job | null }>(`/api/backups/${encodeURIComponent(name)}/restore`, undefined, {
        timeoutMs: 120_000,
      }),
    meta: { silentError: true }, // der Dialog zeigt den Fehler selbst
    onSuccess: (res) => {
      // Die ganze Datenbank ist ersetzt: alle Bibliotheksdaten neu laden
      void qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'system' })
      void qc.invalidateQueries({ queryKey: systemKeys.health })
      // Job „Bibliotheken nach dem Wiederherstellen abgleichen“ (INT-06): gleicht SchLib/PcbLib mit der wiederhergestellten
      // Registrierung ab und schreibt Fehlendes – Fortschritt in der Pille, Ergebnis als Toast, danach neu laden
      if (res.job) trackJob(res.job)
    },
  })
}

// --------------------------------------------------------------------------- Schema-Designer

export function useCategoryTemplates(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.categoryTemplates,
    queryFn: ({ signal }) => api.get<CategoryDef[]>('/api/category-templates', { signal }),
    enabled,
    staleTime: Infinity,
  })
}

export function useFieldKinds(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.fieldKinds,
    queryFn: ({ signal }) => api.get<FieldKindInfo[]>('/api/field-kinds', { signal }),
    enabled,
    staleTime: Infinity,
  })
}

export function useSymbolKinds(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.symbolKinds,
    queryFn: ({ signal }) => api.get<SymbolKindInfo[]>('/api/symbols/kinds', { signal }),
    enabled,
    staleTime: 5 * 60_000,
  })
}

/** Kategorie in der zwischengespeicherten Liste ersetzen (Zähler bleiben erhalten) */
function putCategory(qc: QueryClient, cat: CategoryDef, previousTable?: string) {
  qc.setQueryData<CategoryDef[]>(libraryKeys.categories, (list) => {
    if (!list) return list
    const key = (previousTable ?? cat.table).toLowerCase()
    let found = false
    const next = list.map((c) => {
      if (c.table.toLowerCase() !== key) return c
      found = true
      return { ...cat, part_count: cat.part_count ?? c.part_count }
    })
    return found ? next : [...next, cat]
  })
}

/** Nach Schemaänderungen: Kategorien, Kennzahlen und Bauteiltabellen neu laden */
function invalidateSchema(qc: QueryClient) {
  void qc.invalidateQueries({ queryKey: libraryKeys.categories })
  void qc.invalidateQueries({ queryKey: libraryKeys.stats })
  void qc.invalidateQueries({ queryKey: ['parts'] })
}

/**
 * Ergebnis einer Schemaänderung in den Cache übernehmen – auch außerhalb von Komponenten nutzbar
 * (z. B. „Rückgängig“ in einem Toast, nachdem der Dialog schon geschlossen ist).
 */
export function applySchemaResult(cat: CategoryDef): void {
  putCategory(queryClient, cat)
  invalidateSchema(queryClient)
  void queryClient.invalidateQueries({ queryKey: settingsKeys.backups })
}

const enc = encodeURIComponent

export const schemaApi = {
  createCategory: (input: CategoryCreateInput) => api.post<CategoryDef>('/api/categories', input),
  updateCategory: (table: string, patch: CategoryPatch) => api.patch<CategoryDef>(`/api/categories/${enc(table)}`, patch),
  deleteCategory: (table: string) => api.delete<DeleteCategoryResult>(`/api/categories/${enc(table)}`, { timeoutMs: 120_000 }),
  addField: (table: string, field: FieldInput) => api.post<CategoryDef>(`/api/categories/${enc(table)}/fields`, field),
  updateField: (table: string, column: string, patch: FieldPatch) =>
    api.patch<CategoryDef>(`/api/categories/${enc(table)}/fields/${enc(column)}`, patch),
  removeField: (table: string, column: string) =>
    api.delete<CategoryDef>(`/api/categories/${enc(table)}/fields/${enc(column)}`, { timeoutMs: 120_000 }),
  reorderFields: (table: string, columns: string[]) =>
    api.post<CategoryDef>(`/api/categories/${enc(table)}/fields/reorder`, { columns }),
  regenerateTexts: (table: string) =>
    api.post<RegenerateTextsResult>(
      `/api/parts/${enc(table)}/regenerate-texts`,
      { columns: ['Value', 'Comment', 'Description'] },
      { timeoutMs: 120_000 },
    ),
}

export function useCreateCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schemaApi.createCategory,
    meta: { silentError: true }, // Fehler zeigt der Dialog
    onSuccess: (cat) => {
      putCategory(qc, { ...cat, part_count: 0 })
      invalidateSchema(qc)
    },
  })
}

export function useUpdateCategory() {
  const qc = useQueryClient()
  return useMutation({
    /** `root` = Bibliothek, zu der der Entwurf gehört (nie in eine inzwischen geöffnete andere schreiben) */
    mutationFn: async ({ table, patch, root }: { table: string; patch: CategoryPatch; root: string }) => {
      await assertWorkspaceRoot(root, 'PATCH', `/api/categories/${enc(table)}`)
      return schemaApi.updateCategory(table, patch)
    },
    meta: { errorTitle: 'Kategorie konnte nicht gespeichert werden' },
    onSuccess: (cat, { table }) => {
      putCategory(qc, cat, table)
      invalidateSchema(qc)
      void qc.invalidateQueries({ queryKey: ['parts', 'render-templates'] })
    },
  })
}

export function useDeleteCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schemaApi.deleteCategory,
    meta: { silentError: true },
    onSuccess: (_out, table) => {
      qc.setQueryData<CategoryDef[]>(libraryKeys.categories, (list) => list?.filter((c) => c.table !== table))
      invalidateSchema(qc)
      void qc.invalidateQueries({ queryKey: settingsKeys.backups })
    },
  })
}

/** Feldoperationen liefern die geänderte Kategorie – Cache direkt aktualisieren */
export function useFieldMutation<V>(fn: (vars: V) => Promise<CategoryDef>, errorTitle: string, silent = false) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    meta: silent ? { silentError: true } : { errorTitle },
    onSuccess: (cat) => {
      putCategory(qc, cat)
      invalidateSchema(qc)
      void qc.invalidateQueries({ queryKey: settingsKeys.backups })
    },
  })
}

export function useRegenerateTexts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: schemaApi.regenerateTexts,
    meta: { errorTitle: 'Texte konnten nicht neu erzeugt werden' },
    onSuccess: (out) => {
      if (out.updated > 0) void qc.invalidateQueries({ queryKey: ['parts'] })
    },
  })
}

/** Einige echte Bauteile einer Kategorie für die Vorlagen-Vorschau */
export function useSampleParts(table: string | null, limit = 40) {
  return useQuery({
    queryKey: [...settingsKeys.samples(table ?? ''), limit],
    queryFn: ({ signal }) => api.get<PartsPage>(`/api/parts/${enc(table ?? '')}`, { query: { limit }, signal }),
    enabled: Boolean(table),
    staleTime: 30_000,
  })
}

/** Value/Comment/Description, wie die **gespeicherten** Vorlagen sie für diese Werte erzeugen */
export function useRenderedTemplates(table: string | null, values: PartRow | null) {
  return useQuery({
    queryKey: settingsKeys.rendered(table ?? '', values),
    queryFn: ({ signal }) =>
      api.post<Record<string, string>>(`/api/parts/${enc(table ?? '')}/render-templates`, { values: values ?? {} }, { signal }),
    enabled: Boolean(table && values),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  })
}

/** Beliebige Vorlage für diese Werte rendern (`POST /api/parts/{table}/render-template`, Werte wie beim Speichern) */
export function renderTemplate(table: string, template: string, values: Record<string, unknown>, signal?: AbortSignal) {
  return api.post<RenderTemplateResult>(`/api/parts/${enc(table)}/render-template`, { template, values }, { signal })
}

// --------------------------------------------------------------------------- Systemstatus

/** Status von Altium, Bibliotheks-Writern, DbLib und Aktualisierung (gleiche Abfrage wie auf der Altium-Seite) */
export function useAltiumStatus(enabled = true) {
  return useSharedAltiumStatus(enabled)
}

/**
 * Altium-Status sofort neu laden (z. B. nach dem Speichern eines Writer- oder X2-Pfads) – aktualisiert alle Anzeigen
 * (Kacheln, Seitenleiste, Altium-Seite) ohne auf das 15-s-Abfrageintervall zu warten und liefert den frischen Stand.
 */
export function refreshAltiumStatus(qc: QueryClient = queryClient): Promise<AltiumStatus> {
  return qc.fetchQuery({ queryKey: altiumKeys.status, queryFn: ({ signal }) => altiumApi.status(signal), staleTime: 0 })
}

export function useAiTest() {
  return useMutation({
    mutationFn: () => api.post<AiTestResult>('/api/ai/test', undefined, { timeoutMs: 60_000 }),
    meta: { silentError: true }, // Ergebnis erscheint in der Karte
  })
}

// --------------------------------------------------------------------------- Bibliotheksdateien

/** SchLib-/PcbLib-Dateien der Bibliothek (ohne Lagenprüfung – schnell), für die Vorschau der Aufteilung */
export function useLibraryFiles(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.libraryFiles,
    queryFn: ({ signal }) => api.get<LibraryFileInfo[]>('/api/libraries/files', { query: { layers: false }, signal }),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

// --------------------------------------------------------------------------- Lagenaufbau

export function useLayerStack(enabled = true) {
  return useQuery({
    queryKey: settingsKeys.layerStack,
    queryFn: ({ signal }) => api.get<LayerStackInfo>('/api/libraries/layer-stack', { signal }),
    enabled,
    staleTime: 30_000,
    retry: false,
  })
}

/** .stackup-Datei lesen (Vorschau, bevor sie in den Einstellungen steht) */
export function useParsedLayerStack(path: string | null) {
  return useQuery({
    queryKey: settingsKeys.layerStackFile(path ?? ''),
    queryFn: ({ signal }) => api.post<LayerStackInfo>('/api/libraries/layer-stack/parse', { path: path ?? '' }, { signal }),
    enabled: Boolean(path),
    staleTime: 30_000,
    retry: false,
  })
}

/** .layerset-Datei lesen: alle Lagensätze der Datei (Auswahl in den Einstellungen) */
export function useParsedLayerSet(path: string | null) {
  return useQuery({
    queryKey: settingsKeys.layerSetFile(path ?? ''),
    queryFn: ({ signal }) => api.post<LayerSetFile>('/api/libraries/layer-set/parse', { path: path ?? '' }, { signal }),
    enabled: Boolean(path),
    staleTime: 30_000,
    retry: false,
  })
}

/** Der eingebaute Lagensatz „Component Layers“ für eine Lagenzuordnung (Vorschau des Entwurfs) */
export function useBuiltinLayerSet(layers: LayerMap | null, current: boolean) {
  return useQuery({
    queryKey: settingsKeys.builtinLayerSet(layers ?? ({} as LayerMap), current),
    queryFn: ({ signal }) => api.post<LayerSetDef>('/api/libraries/layer-set/builtin', { layers, current }, { signal }),
    enabled: Boolean(layers),
    staleTime: 60_000,
    retry: false,
  })
}

export function useApplyLayerStack() {
  return useMutation({
    mutationFn: () => api.post<{ job: Job }>('/api/libraries/layer-stack/apply'),
    meta: { errorTitle: 'Lagen konnten nicht übertragen werden' },
  })
}
