/**
 * Zustände des Datenblatt-Imports:
 *
 * - useActiveImports: laufende Analysen (Datenblatt → Job, URL-Importe ohne Datenblatt-ID) und die letzte
 *                     Datenblattsuche – sessionStorage
 * - useReviewDrafts:  Entscheidungen der Prüfansicht je Datenblatt (Kategorie, Varianten, Werte, Footprints,
 *                     Pinbelegung je Symbol …) und bestätigte Probleme – localStorage, überlebt Navigation und Neustart
 * - useReviewUi:      geteilter Zustand der drei Spalten (aktuelle Seite, Zoom, hervorgehobene Pins, Gehäuse, große
 *                     Seitenansicht, eingeklappte Spalten, abgelehnte Übernahme)
 * - useBatchPrompt:   mehrere abgelegte PDFs – Rückfrage „Alle analysieren?“ (bezahlte Analysen nie ungefragt im Stapel)
 */
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import type { PackageChoice, ProposalChoices, SymbolChoice } from '@/api/datasheets'
import type { PreviewTab } from '@/components/preview'

// --------------------------------------------------------------------------- laufende Analysen

export interface UrlImport {
  jobId: string
  url: string
  startedAt: number
  /** Job „Datenblatt suchen“, aus dem die Adresse stammt (seine Kosten gehen an das Datenblatt) */
  searchJobId?: string | null
}

/** Letzte Datenblattsuche dieser Sitzung (das Ergebnis steht im Job) */
export interface SearchEntry {
  jobId: string
  query: string
  manufacturer: string | null
  startedAt: number
}

interface ActiveImportsState {
  /** Datenblatt-ID → Job-ID der laufenden Analyse */
  jobs: Record<string, string>
  /** URL-Importe, deren Datenblatt-ID erst nach dem Download feststeht */
  urls: UrlImport[]
  search: SearchEntry | null
  start: (datasheetId: string, jobId: string) => void
  finish: (datasheetId: string, jobId?: string) => void
  startUrl: (jobId: string, url: string, searchJobId?: string | null) => void
  finishUrl: (jobId: string) => void
  setSearch: (search: SearchEntry | null) => void
}

const safeSession = createJSONStorage(() => sessionStorage)

export const useActiveImports = create<ActiveImportsState>()(
  persist(
    (set) => ({
      jobs: {},
      urls: [],
      search: null,
      start: (datasheetId, jobId) => set((s) => ({ jobs: { ...s.jobs, [datasheetId]: jobId } })),
      finish: (datasheetId, jobId) =>
        set((s) => {
          if (!(datasheetId in s.jobs) || (jobId && s.jobs[datasheetId] !== jobId)) return s
          const jobs = { ...s.jobs }
          delete jobs[datasheetId]
          return { jobs }
        }),
      startUrl: (jobId, url, searchJobId = null) =>
        set((s) => ({ urls: [...s.urls.filter((u) => u.jobId !== jobId), { jobId, url, startedAt: Date.now(), searchJobId }] })),
      finishUrl: (jobId) => set((s) => ({ urls: s.urls.filter((u) => u.jobId !== jobId) })),
      setSearch: (search) => set({ search }),
    }),
    {
      name: 'pf-import-active',
      version: 2,
      storage: safeSession,
      // v1 → v2: letzte Datenblattsuche
      migrate: (persisted) => ({ search: null, ...(persisted as object) }) as ActiveImportsState,
    },
  ),
)

// --------------------------------------------------------------------------- Entscheidungen je Datenblatt

/** Vom Benutzer festgelegte Teile von `ProposalChoices` (der Rest sind Standardwerte des Backends). */
export interface ChoiceDraft {
  device: string | null
  category: string | null
  /** `null` = alle Bestellnummern des Bauteils */
  variants: string[] | null
  /** Spalte → Wert für alle Bestellnummern */
  values: Record<string, string>
  /** Bestellnummer → Spalte → Wert (Werte, die je Bestellnummer verschieden sind) */
  variantValues: Record<string, Record<string, string>>
  packages: Record<string, PackageChoice>
  symbols: Record<string, SymbolChoice>
  mode: ProposalChoices['mode']
  link: ProposalChoices['link']
  /**
   * Registrierte Symbole, die die neue Pinbelegung bekommen dürfen – je Symbol entschieden (erzeugter Name, bei einem
   * umbenannten Symbol `SymbolProposal.taken_name`). Alle anderen bekommen bei abweichender Belegung einen freien Namen.
   */
  allowPinChanges: string[]
  overwriteExisting: boolean
}

export interface ReviewDraft {
  choices: ChoiceDraft
  /** Bestätigte Probleme (Texte aus `PartProposal.blockers`) */
  acknowledged: string[]
  touched: number
}

export const EMPTY_CHOICES: ChoiceDraft = {
  device: null,
  category: null,
  variants: null,
  values: {},
  variantValues: {},
  packages: {},
  symbols: {},
  mode: 'skip',
  link: 'auto',
  allowPinChanges: [],
  overwriteExisting: false,
}

/** Gleicher Symbolname? (Backend: ohne Groß-/Kleinschreibung, Leerraum am Rand egal) */
export function sameSymbolName(a: string | null | undefined, b: string | null | undefined): boolean {
  return Boolean(a && b) && (a as string).trim().toLocaleLowerCase('en') === (b as string).trim().toLocaleLowerCase('en')
}

/** Bestätigter Blocker? (Backend: Leerraum egal) */
export function sameBlocker(a: string, b: string): boolean {
  return a.split(/\s+/).join(' ').trim() === b.split(/\s+/).join(' ').trim()
}

const EMPTY_DRAFT: ReviewDraft = { choices: EMPTY_CHOICES, acknowledged: [], touched: 0 }
const MAX_DRAFTS = 40

interface ReviewDraftsState {
  drafts: Record<string, ReviewDraft>
  update: (id: string, change: (draft: ReviewDraft) => ReviewDraft) => void
  setChoices: (id: string, change: (choices: ChoiceDraft) => ChoiceDraft) => void
  reset: (id: string) => void
}

function prune(drafts: Record<string, ReviewDraft>): Record<string, ReviewDraft> {
  const entries = Object.entries(drafts)
  if (entries.length <= MAX_DRAFTS) return drafts
  return Object.fromEntries(entries.sort((a, b) => b[1].touched - a[1].touched).slice(0, MAX_DRAFTS))
}

export const useReviewDrafts = create<ReviewDraftsState>()(
  persist(
    (set) => ({
      drafts: {},
      update: (id, change) =>
        set((s) => ({ drafts: prune({ ...s.drafts, [id]: { ...change(s.drafts[id] ?? EMPTY_DRAFT), touched: Date.now() } }) })),
      setChoices: (id, change) =>
        set((s) => {
          const current = s.drafts[id] ?? EMPTY_DRAFT
          return { drafts: prune({ ...s.drafts, [id]: { ...current, choices: change(current.choices), touched: Date.now() } }) }
        }),
      reset: (id) =>
        set((s) => {
          const drafts = { ...s.drafts }
          delete drafts[id]
          return { drafts }
        }),
    }),
    {
      name: 'pf-import-drafts',
      version: 3,
      storage: createJSONStorage(() => localStorage),
      // v1 → v2: Werte je Bestellnummer (`variantValues`); v2 → v3: Pinbelegung je Symbol (`allowPinChanges` als
      // Liste – die frühere Pauschalentscheidung gilt nicht weiter: neu entscheiden, vorhandene Bauteile bleiben)
      migrate: (persisted) => {
        const state = (persisted ?? {}) as { drafts?: Record<string, ReviewDraft> }
        const drafts: Record<string, ReviewDraft> = {}
        for (const [id, d] of Object.entries(state.drafts ?? {})) {
          const old = (d.choices ?? {}) as Partial<ChoiceDraft> & { allowPinChanges?: unknown }
          drafts[id] = {
            ...d,
            choices: {
              ...EMPTY_CHOICES,
              ...old,
              variantValues: old.variantValues ?? {},
              allowPinChanges: Array.isArray(old.allowPinChanges) ? old.allowPinChanges.filter((n) => typeof n === 'string') : [],
            },
          }
        }
        return { drafts } as ReviewDraftsState
      },
    },
  ),
)

export function useReviewDraft(id: string): ReviewDraft {
  return useReviewDrafts((s) => s.drafts[id] ?? EMPTY_DRAFT)
}

/**
 * Entscheidungen → vollständige `ProposalChoices` für Vorschlag und Übernahme. „Vorhandenes Symbol/Footprint“ ohne
 * gewählten Namen bleibt beim Vorschlag (die Prüfung meldet die offene Auswahl, siehe `pendingPicks`).
 * Bestätigte Probleme (`accept_issues`) und der geprüfte Fingerabdruck (`expected_fingerprint`) setzt erst die
 * Übernahme – sie zählen nicht zum Fingerabdruck, der Vorschlag wird dafür nicht neu berechnet.
 */
export function toProposalChoices(c: ChoiceDraft): ProposalChoices {
  const symbols = Object.fromEntries(
    Object.entries(c.symbols).map(([code, s]) => [code, s.mode === 'existing' && !s.existing ? { mode: 'auto' as const } : s]),
  )
  const packages = Object.fromEntries(
    Object.entries(c.packages).map(([code, p]) => [
      code,
      p.footprint === 'existing' && !p.existing ? { ...p, footprint: 'ipc' as const, existing: null } : p,
    ]),
  )
  return {
    device: c.device,
    category: c.category,
    variants: c.variants,
    values: c.values,
    variant_values: c.variantValues ?? {},
    packages,
    symbol: { mode: 'auto' },
    symbols,
    mode: c.mode,
    overwrite_existing: c.overwriteExisting,
    link: c.link,
    accept_issues: [],
    allow_pin_changes: [...new Set(c.allowPinChanges)].sort((a, b) => a.localeCompare(b)),
    // „Nur Symbol/Footprint speichern“ setzt erst die Übernahme (zählt nicht zum Fingerabdruck)
    scope: 'part',
  }
}

/** Gewählte „vorhanden“-Modi ohne Namen (Gehäusecodes) */
export function pendingPicks(c: ChoiceDraft): { symbols: string[]; footprints: string[] } {
  return {
    symbols: Object.entries(c.symbols)
      .filter(([, s]) => s.mode === 'existing' && !s.existing)
      .map(([code]) => code),
    footprints: Object.entries(c.packages)
      .filter(([, p]) => p.footprint === 'existing' && !p.existing)
      .map(([code]) => code),
  }
}

// --------------------------------------------------------------------------- geteilter Zustand der Prüfansicht

export type DataSection = 'pruefen' | 'identitaet' | 'varianten' | 'parameter' | 'pins' | 'gehaeuse' | 'hinweise'

/**
 * Abgelehnte Übernahme (Job `datasheet-commit` mit `CommitRefused`, nichts geschrieben): `blockers` = neue, noch nicht
 * bestätigte Probleme (`detail.unconfirmed_blockers`), `changed` = der Vorschlag hat sich seit der Prüfung geändert.
 */
export interface CommitRefusal {
  kind: 'blockers' | 'changed' | 'invalid'
  /** Blocker-Texte (bei `blockers`) */
  items: string[]
  /** Meldung des Backends */
  message: string
  nonce: number
}

interface ReviewUiState {
  datasheetId: string | null
  page: number
  /** Kurz aufleuchtende Seite (Sprung zu einer Fundstelle) – `nonce` erneuert die Animation */
  flash: { page: number; nonce: number } | null
  /** Seite, deren Fundstelle gerade überfahren wird (Miniatur hervorheben) */
  hoverPage: number | null
  zoom: number
  /** Pins/Pads, die in der Vorschau hervorgehoben werden */
  highlight: string[]
  /** Gehäuse (Code), dessen Symbol/Footprint die Vorschau zeigt */
  previewPackage: string | null
  previewTab: PreviewTab
  /** Sprungziel im Datenbereich (`nonce` erneuert den Sprung) */
  focusSection: { id: DataSection; nonce: number } | null
  /** Große Seitenansicht (Fundstelle prüfen) – `what` sagt, was dort steht („Maße SOIC-8 (D)“) */
  overlay: { page: number; what?: string } | null
  /** PDF-Spalte eingeklappt: `null` = automatisch (schmales Fenster), sonst die Wahl des Benutzers (gilt für die Sitzung) */
  pdfCollapsed: boolean | null
  previewCollapsed: boolean
  /** Letzte abgelehnte Übernahme dieses Datenblatts (bis zur nächsten Übernahme bzw. einem anderen Datenblatt) */
  refusal: CommitRefusal | null
  open: (datasheetId: string, page: number) => void
  setPage: (page: number) => void
  jumpToPage: (page: number) => void
  setHoverPage: (page: number | null) => void
  setZoom: (zoom: number) => void
  setHighlight: (pins: string[]) => void
  setPreviewPackage: (code: string | null) => void
  setPreviewTab: (tab: PreviewTab) => void
  showSection: (id: DataSection) => void
  openOverlay: (page: number, what?: string) => void
  closeOverlay: () => void
  setPdfCollapsed: (collapsed: boolean | null) => void
  setPreviewCollapsed: (collapsed: boolean) => void
  setRefusal: (refusal: Omit<CommitRefusal, 'nonce'> | null) => void
}

export const useReviewUi = create<ReviewUiState>()((set) => ({
  datasheetId: null,
  page: 1,
  flash: null,
  hoverPage: null,
  zoom: 1,
  highlight: [],
  previewPackage: null,
  previewTab: 'symbol',
  focusSection: null,
  overlay: null,
  pdfCollapsed: null,
  previewCollapsed: false,
  refusal: null,
  open: (datasheetId, page) =>
    set((s) =>
      s.datasheetId === datasheetId
        ? s
        : {
            datasheetId,
            page,
            zoom: 1,
            flash: null,
            hoverPage: null,
            highlight: [],
            previewPackage: null,
            focusSection: null,
            overlay: null,
            refusal: null,
          },
    ),
  setPage: (page) => set({ page }),
  jumpToPage: (page) => set({ page, flash: { page, nonce: Date.now() } }),
  setHoverPage: (hoverPage) => set({ hoverPage }),
  setZoom: (zoom) => set({ zoom }),
  setHighlight: (highlight) => set((s) => (s.highlight.join('|') === highlight.join('|') ? s : { highlight })),
  setPreviewPackage: (previewPackage) => set({ previewPackage }),
  setPreviewTab: (previewTab) => set({ previewTab }),
  showSection: (id) => set({ focusSection: { id, nonce: Date.now() } }),
  openOverlay: (page, what) => set({ overlay: { page, what }, page, flash: { page, nonce: Date.now() } }),
  closeOverlay: () => set({ overlay: null }),
  setPdfCollapsed: (pdfCollapsed) => set({ pdfCollapsed }),
  setPreviewCollapsed: (previewCollapsed) => set({ previewCollapsed }),
  setRefusal: (refusal) => set({ refusal: refusal ? { ...refusal, nonce: Date.now() } : null }),
}))

// --------------------------------------------------------------------------- mehrere PDFs: Rückfrage vor der Analyse

export interface BatchItem {
  id: string
  name: string
  pageCount: number
  /** neu = noch nie analysiert · failed = letzte Analyse fehlgeschlagen · analyzed = Ergebnis vorhanden */
  state: 'new' | 'failed' | 'analyzed'
  error?: string | null
}

interface BatchPromptState {
  items: BatchItem[] | null
  show: (items: BatchItem[]) => void
  close: () => void
}

export const useBatchPrompt = create<BatchPromptState>()((set) => ({
  items: null,
  show: (items) => set({ items }),
  close: () => set({ items: null }),
}))
