import { metadataLabel, localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Bauteiltabelle mit **Server-Paging** (AG Grid Infinite Row Model, Blöcke à 100 Zeilen): Suche, Filter und
 * Sortierung rechnet das Backend (Werte mit Einheiten werden verglichen), nur sichtbare Blöcke werden geladen –
 * 10.000 Zeilen scrollen flüssig. Bei neuer Suche/Filter wird der erste Block vorab geladen und dann getauscht
 * (kein Aufblitzen leerer Zeilen). Inline-Bearbeitung mit Prüfung, Fehler direkt an der Zelle.
 *
 * Tastatur: Enter = Details, F2/Tippen = bearbeiten, Leertaste = auswählen, Entf = löschen, Strg+A = alle geladenen
 * Zeilen wählen, Esc = Details schließen. **Tab verlässt die Tabelle** (Pfeiltasten bewegen sich darin).
 * Maus (wie jede Tabelle der App, Vertrag `onRowActivated`): Klick auf die Teilenummer oder **Doppelklick** auf eine
 * Zeile öffnet die Details – ein Doppelklick auf einen Wert setzt den Fokus dort gleich in dieses Feld. In der Tabelle
 * selbst bearbeitet F2/Tippen oder das Kontextmenü („… bearbeiten“).
 *
 * Überholte Abfragen (neue Suche/Filter, andere Sortierung) werden abgebrochen (`AbortSignal`).
 */
import {
  type CellClickedEvent,
  type CellDoubleClickedEvent,
  type CellFocusedEvent,
  type CellKeyDownEvent,
  type CellValueChangedEvent,
  type ColDef,
  type FullWidthCellKeyDownEvent,
  type GridApi,
  type GridReadyEvent,
  type IDatasource,
  type IRowNode,
  type RowSelectionOptions,
  type SelectionChangedEvent,
  type SortModelItem,
  type StateUpdatedEvent,
  type SuppressKeyboardEventParams,
} from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { RotateCw, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState, type Ref } from 'react'
import { toast } from 'sonner'
import type { CategoryDef } from '@/api/library'
import { errorMessage, isAbortError } from '@/api/client'
import {
  partsApi,
  partsKeys,
  fieldErrors,
  PART_NUMBER,
  type PartFilter,
  type PartRow,
  type PartsPage,
  type SortSpec,
} from '@/api/parts'
import { useQuery } from '@tanstack/react-query'
import {
  AG_GRID_LOCALE_DE,
  FORGE_COLUMN_TYPES,
  forgeGridTheme,
  GRID_DENSITY,
  GridOverlay,
  loadGridState,
  saveGridState,
  type GridDensity,
  type GridEmptyState,
} from '@/components/grid'
import { Button, EmptyState } from '@/components/ui'
import { cn } from '@/lib/cn'
import { isUnreadable, otherWarnings } from '../model/fields'
import { buildColumnDefs } from './columns'
import { SelectAllHeader } from './cells'
import '../bauteile.css'

const BLOCK_SIZE = 100
const PERSISTED_SOURCES = new Set(['columnOrder', 'columnSizing', 'columnVisibility', 'sort', 'columnPinning'])
/** Quellen, die eine gespeicherte Ansicht verändern (Breiten zählen nicht) */
const LAYOUT_SOURCES = new Set(['columnOrder', 'columnVisibility', 'sort'])
const SOURCE_REVERT = 'pf-revert'
const TRACKED = new Set(['PF Modified', 'PF Author', 'PF Created'])

/**
 * Ergebnis von `locate`: gefunden, durch Suche/Filter ausgeblendet, gar nicht vorhanden, bei der aktuellen
 * Sortierung nicht berechenbar oder Tabelle noch nicht bereit.
 */
export type LocateResult = 'found' | 'hidden' | 'missing' | 'unsorted' | 'pending'

export interface PartsGridHandle {
  /** Sichtbare Zeilen neu laden (Position bleibt) */
  refresh: () => void
  /** Fokus in die Tabelle (aktive bzw. erste Zeile) */
  focus: () => void
  /** Fokus auf eine bestimmte (geladene) Zeile */
  focusRow: (pn: string) => void
  /** Liegt der Tastaturfokus in der Tabelle? */
  hasFocus: () => boolean
  /** Zeile mit dem Tastaturfokus (oder null) */
  getFocusedRow: () => PartRow | null
  /** Zeile zu einem Element der Tabelle (Kontextmenü) */
  rowFromElement: (el: HTMLElement) => PartRow | null
  /** Zeile suchen, hinscrollen und fokussieren */
  locate: (pn: string) => Promise<LocateResult>
  /** Zelle einer geladenen Zeile bearbeiten (Kontextmenü „… bearbeiten“) – false, wenn das nicht geht */
  editCell: (pn: string, column: string) => boolean
  /** Spalte einer Zelle der Tabelle (Kontextmenü) und ob sie bearbeitbar ist */
  cellFromElement: (el: HTMLElement) => { column: string; label: string; editable: boolean } | null
  selectAllLoaded: () => void
  deselectAll: () => void
  /** Sortierung der Tabelle (für Ansichten, Export) */
  getSort: () => SortSpec[]
  /** Sichtbare Spalten in Reihenfolge */
  getVisibleColumns: () => string[]
  /** Alle Spalten mit Sichtbarkeit (Spaltenwahl) */
  getColumns: () => { colId: string; visible: boolean }[]
  setColumnVisible: (colId: string, visible: boolean) => void
  /** Ansicht anwenden: Spalten (leer = Standard) und Sortierung */
  applyView: (columns: string[], sort: SortSpec[]) => void
  /** Spalten auf den Standard zurücksetzen (Breiten, Reihenfolge, Sichtbarkeit, Sortierung) */
  resetColumns: () => void
  /** Nach Teilenummer sortieren (Standard) */
  sortByPartNumber: () => void
  /** Geladene Zeilen (z. B. für „Alle Treffer auswählen“) */
  loadedCount: () => number
}

export interface PartsGridProps {
  category: CategoryDef
  /** Teilenummern-Schema der Bibliothek */
  scheme: string | undefined
  search: string
  filters: PartFilter[]
  density: GridDensity
  /** Bauteil im Detailbereich (Zeile wird hervorgehoben) */
  activePn: string | null
  /** Gerade angelegte Teilenummern („neu“) */
  newPns: ReadonlySet<string>
  /** „Alle Treffer ausgewählt“: nachgeladene Zeilen werden mit ausgewählt */
  selectAllMatching: boolean
  emptyState: GridEmptyState
  noMatchState: GridEmptyState
  /** Details öffnen (Enter, Klick auf die Teilenummer, Doppelklick) – `focusColumn` = doppelt angeklickter Wert */
  onActivate: (row: PartRow, focusColumn?: string) => void
  onFocusRow?: (row: PartRow) => void
  onSelectionChange: (rows: PartRow[]) => void
  onExitAllMatching: () => void
  onTotalChange: (total: number | null) => void
  onDelete: (rows: PartRow[]) => void
  onRowSaved: (row: PartRow, previousPn: string) => void
  onEscape?: () => void
  /** Laden fehlgeschlagen (null = wieder in Ordnung) */
  onLoadError?: (error: unknown) => void
  /** Spalten (Reihenfolge, Sichtbarkeit) oder Sortierung geändert – z. B. für „Ansicht geändert“ */
  onLayoutChange?: () => void
  handleRef?: Ref<PartsGridHandle>
  className?: string
}

const cellKey = (pn: string, col: string) => `${pn}\u0000${col}`

/** Zustand einzelner Zellen/Zeilen außerhalb von React (AG Grid fragt ihn über Klassenregeln ab) */
function createCellStore() {
  const errors = new Map<string, string>()
  const saving = new Set<string>()
  let fresh: ReadonlySet<string> = new Set()
  let activePn: string | null = null
  return {
    error: (pn: string, col: string) => errors.get(cellKey(pn, col)),
    isSaving: (pn: string, col: string) => saving.has(cellKey(pn, col)),
    isNew: (pn: string) => fresh.has(pn),
    active: () => activePn,
    setActive: (pn: string | null) => {
      activePn = pn
    },
    setNew: (pns: ReadonlySet<string>) => {
      fresh = pns
    },
    startSaving: (pn: string, col: string) => {
      errors.delete(cellKey(pn, col))
      saving.add(cellKey(pn, col))
    },
    saved: (pn: string, col: string) => {
      saving.delete(cellKey(pn, col))
    },
    failed: (pn: string, col: string, message: string) => {
      saving.delete(cellKey(pn, col))
      errors.set(cellKey(pn, col), message)
    },
  }
}
const toSort = (model: SortModelItem[]): SortSpec[] => model.map((m) => ({ column: m.colId, desc: m.sort === 'desc' }))
const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

interface LoadError {
  error: unknown
  /** Noch keine Zeile dieser Abfrage geladen → Fehler statt Tabelle */
  first: boolean
}

export function PartsGrid({
  category,
  scheme,
  search,
  filters,
  density,
  activePn,
  newPns,
  selectAllMatching,
  emptyState,
  noMatchState,
  onActivate,
  onFocusRow,
  onSelectionChange,
  onExitAllMatching,
  onTotalChange,
  onDelete,
  onRowSaved,
  onEscape,
  onLoadError,
  onLayoutChange,
  handleRef,
  className,
}: PartsGridProps) {
  const { t, language } = useI18n()
  const table = category.table
  const persistKey = `parts:${table}`
  const apiRef = useRef<GridApi<PartRow> | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const [loadError, setLoadError] = useState<LoadError | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loadedOnce, setLoadedOnce] = useState(false)
  const loadedOnceRef = useRef(false)
  useEffect(() => {
    loadedOnceRef.current = loadedOnce
  }, [loadedOnce])

  // aktuelle Werte für Rückruffunktionen der Tabelle (die AG Grid nicht neu bindet)
  const queryRef = useRef({ search, filters })
  const totalRef = useRef<number | null>(null)
  const latest = useRef({
    onActivate,
    onFocusRow,
    onSelectionChange,
    onExitAllMatching,
    onTotalChange,
    onDelete,
    onRowSaved,
    onEscape,
    onLoadError,
    onLayoutChange,
  })
  useEffect(() => {
    queryRef.current = { search, filters }
    latest.current = {
      onActivate,
      onFocusRow,
      onSelectionChange,
      onExitAllMatching,
      onTotalChange,
      onDelete,
      onRowSaved,
      onEscape,
      onLoadError,
      onLayoutChange,
    }
  })

  // ------------------------------------------------------------------ Zellzustände (Speichern, Fehler, neu, aktiv)
  const cells = useMemo(() => createCellStore(), [])
  const ctx = useMemo(
    () => ({
      table,
      scheme,
      cellError: (pn: string, col: string) => cells.error(pn, col),
      isSaving: (pn: string, col: string) => cells.isSaving(pn, col),
      isNew: (pn: string) => cells.isNew(pn),
    }),
    [table, scheme, cells],
  )
  const columnDefs = useMemo(() => buildColumnDefs(category, ctx, t), [category, ctx, t])
  const labelOf = useCallback((col: string) => metadataLabel(category.fields.find((f) => f.column === col)?.label ?? col, t), [category, t])

  const refreshCell = (node: IRowNode<PartRow>, col: string) =>
    apiRef.current?.refreshCells({ rowNodes: [node], columns: [col], force: true })

  // „neu“-Markierung aktualisieren
  useEffect(() => {
    cells.setNew(newPns)
    apiRef.current?.refreshCells({ columns: [PART_NUMBER], force: true })
  }, [newPns, cells])

  // aktive Zeile hervorheben (nur die beiden betroffenen Zeilen neu zeichnen)
  useEffect(() => {
    const api = apiRef.current
    const before = cells.active()
    cells.setActive(activePn)
    if (!api || before === activePn) return
    const nodes = [before, activePn].map((pn) => (pn ? api.getRowNode(pn) : undefined)).filter((n): n is IRowNode<PartRow> => Boolean(n))
    if (nodes.length) api.redrawRows({ rowNodes: nodes })
  }, [activePn, cells])

  // ------------------------------------------------------------------ Datenquelle (Server-Paging)
  const queryKey = JSON.stringify({ search, filters })
  const [generation, setGeneration] = useState(0)
  const primed = useRef<{ key: string; sort: string; page: PartsPage } | null>(null)
  const firstQuery = useRef(queryKey)
  /** Generation, für die schon Zeilen kamen (Fehler danach betreffen nur einzelne Blöcke) */
  const loadedGeneration = useRef(-1)

  const reportTotal = useCallback((total: number) => {
    totalRef.current = total
    latest.current.onTotalChange(total)
  }, [])

  const reportError = useCallback((next: LoadError | null) => {
    setLoadError(next)
    latest.current.onLoadError?.(next ? next.error : null)
  }, [])

  const currentSort = useCallback((): SortSpec[] => {
    const api = apiRef.current
    if (!api) return []
    return api
      .getColumnState()
      .filter((c) => c.sort)
      .sort((a, b) => (a.sortIndex ?? 0) - (b.sortIndex ?? 0))
      .map((c) => ({ column: c.colId, desc: c.sort === 'desc' }))
  }, [])

  // neue Suche/Filter: ersten Block vorab laden, dann Datenquelle tauschen. Tippt man weiter, bricht die nächste
  // Suche diese Abfrage ab (Server und Tabelle rechnen nicht mehr für überholte Suchbegriffe).
  useEffect(() => {
    if (queryKey === firstQuery.current) return
    firstQuery.current = queryKey
    const controller = new AbortController()
    const sort = currentSort()
    const q = JSON.parse(queryKey) as { search: string; filters: PartFilter[] }
    setRefreshing(true)
    partsApi
      .query(table, { search: q.search || null, filters: q.filters, sort, offset: 0, limit: BLOCK_SIZE }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return
        primed.current = { key: queryKey, sort: JSON.stringify(sort), page }
      })
      .catch(() => {
        if (controller.signal.aborted) return
        primed.current = null // die Datenquelle lädt selbst und meldet den Fehler
      })
      .finally(() => {
        if (controller.signal.aborted) return
        setRefreshing(false)
        apiRef.current?.deselectAll()
        setGeneration((g) => g + 1)
      })
    return () => controller.abort()
  }, [queryKey, table, currentSort])

  const datasource = useMemo<IDatasource & { generation: number }>(() => {
    /** laufende Abfragen dieser Datenquelle → ihre Sortierung (andere Sortierung = überholt) */
    const inflight = new Map<AbortController, string>()
    return {
      generation,
      // AG Grid ruft `destroy` beim Tausch der Datenquelle (neue Suche/Filter) und beim Abbau der Tabelle
      destroy: () => {
        for (const controller of inflight.keys()) controller.abort()
        inflight.clear()
      },
      getRows: (params) => {
        const q = queryRef.current
        const sort = toSort(params.sortModel)
        const sortText = JSON.stringify(sort)
        // neue Sortierung: Blöcke der alten Sortierung braucht niemand mehr
        for (const [controller, key] of inflight) {
          if (key !== sortText) {
            controller.abort()
            inflight.delete(controller)
          }
        }
        const ok = (page: PartsPage) => {
          params.successCallback(page.rows, page.total)
          reportTotal(page.total)
          loadedGeneration.current = generation
          reportError(null)
          setLoadedOnce(true)
        }
        const p = primed.current
        if (p && params.startRow === 0 && p.key === JSON.stringify(q) && p.sort === sortText) {
          primed.current = null
          ok(p.page)
          return
        }
        const controller = new AbortController()
        inflight.set(controller, sortText)
        partsApi
          .query(
            table,
            {
              search: q.search || null,
              filters: q.filters,
              sort,
              offset: params.startRow,
              limit: params.endRow - params.startRow,
            },
            controller.signal,
          )
          .then(ok)
          .catch((err: unknown) => {
            params.failCallback()
            // abgebrochen (überholt) – kein Fehler für die Anzeige
            if (controller.signal.aborted || isAbortError(err)) return
            const first = loadedGeneration.current !== generation
            if (first) {
              totalRef.current = null
              latest.current.onTotalChange(null)
            }
            reportError({ error: err, first })
          })
          .finally(() => inflight.delete(controller))
      },
    }
    // generation: neue Datenquelle = vollständiger Neuaufbau (Suche/Filter geändert, „Erneut versuchen“)
  }, [table, generation, reportTotal, reportError])

  const retry = () => {
    const first = loadError?.first ?? false
    reportError(null)
    if (first) setGeneration((g) => g + 1)
    else apiRef.current?.refreshInfiniteCache()
  }

  // Jede Invalidierung von ['parts', table] (eigene Änderungen, beendete Jobs) lädt die sichtbaren Zeilen neu
  const revision = useQuery({
    queryKey: partsKeys.revision(table),
    queryFn: () => Date.now(),
    staleTime: Infinity,
  })
  const seenRevision = useRef<number | undefined>(undefined)
  useEffect(() => {
    if (revision.data === undefined) return
    if (seenRevision.current !== undefined && seenRevision.current !== revision.data) {
      apiRef.current?.refreshInfiniteCache()
    }
    seenRevision.current = revision.data
  }, [revision.data])

  // ------------------------------------------------------------------ Auswahl
  const selectAllRef = useRef(selectAllMatching)
  useEffect(() => {
    selectAllRef.current = selectAllMatching
  }, [selectAllMatching])

  const selectLoaded = useCallback((value: boolean) => {
    const api = apiRef.current
    if (!api) return
    const nodes: IRowNode<PartRow>[] = []
    api.forEachNode((n) => {
      if (n.data && n.isSelected() !== value) nodes.push(n)
    })
    if (nodes.length) api.setNodesSelected({ nodes, newValue: value, source: 'api' })
  }, [])

  const onSelectionChanged = (e: SelectionChangedEvent<PartRow>) => {
    const rows = e.api.getSelectedRows()
    latest.current.onSelectionChange(rows)
    if (selectAllRef.current && e.source !== 'api') {
      let unselected = false
      e.api.forEachNode((n) => {
        if (n.data && !n.isSelected()) unselected = true
      })
      if (unselected) latest.current.onExitAllMatching()
    }
  }

  // ------------------------------------------------------------------ Bearbeiten
  const onCellValueChanged = (e: CellValueChangedEvent<PartRow>) => {
    if (e.source === SOURCE_REVERT || !e.data) return
    const col = e.column.getColId()
    const oldValue = (e.oldValue ?? null) as string | null
    const newValue = (e.newValue ?? null) as string | null
    if (oldValue === newValue) return
    const pn = String(e.data[PART_NUMBER] ?? '')
    const key = cellKey(pn, col)
    const node = e.node
    cells.startSaving(pn, col)
    refreshCell(node, col)
    partsApi
      .update(table, pn, { [col]: newValue })
      .then((res) => {
        cells.saved(pn, col)
        const before = node.data ?? {}
        const changed = Object.keys(res.part).filter(
          (c) => c !== col && !TRACKED.has(c) && (before[c] ?? null) !== (res.part[c] ?? null),
        )
        node.setData(res.part)
        if (changed.length) apiRef.current?.flashCells({ rowNodes: [node], columns: changed, flashDuration: 900, fadeDuration: 900 })
        latest.current.onRowSaved(res.part, pn)
        // Hinweise zum bearbeiteten Feld hat der Editor schon gezeigt (und bestätigen lassen) – nur die übrigen melden
        const field = category.fields.find((f) => f.column === col)
        const rest = field ? otherWarnings([field], res.warnings) : res.warnings
        if (rest.length) {
          toast.warning(t("{1} gespeichert – bitte prüfen", { 1: labelOf(col) }), { description: rest.map(localizeMessage).join(' · ') })
        }
      })
      .catch((err: unknown) => {
        const message = fieldErrors(err)[col] ?? Object.values(fieldErrors(err))[0] ?? errorMessage(err)
        cells.failed(pn, col, message)
        node.setDataValue(col, oldValue, SOURCE_REVERT)
        refreshCell(node, col)
        toast.error(t("{1} nicht gespeichert", { 1: labelOf(col) }), { id: `cell:${key}`, description: message })
      })
  }

  // ------------------------------------------------------------------ Tastatur
  const suppressKeys = useCallback((p: SuppressKeyboardEventParams<PartRow>) => {
    const ev = p.event
    const mod = ev.ctrlKey || ev.metaKey
    // Im Editor: Enter/Tab prüft der Editor selbst, ↑/↓ blättern in den Vorschlägen
    if (p.editing) return ev.key === 'Enter' || ev.key === 'Tab' || ev.key === 'ArrowUp' || ev.key === 'ArrowDown'
    if (ev.key === 'Enter' && !mod && !ev.altKey && !ev.shiftKey) return true
    if (ev.key === 'Delete') return true
    if (mod && ev.key.toLowerCase() === 'a') {
      // Hier – nicht erst in onCellKeyDown: AG Grid meldet cellKeyDown asynchron, dann markiert der Browser schon den
      // ganzen Seitentext. suppressKeyboardEvent läuft synchron im keydown.
      if (ev.type === 'keydown') ev.preventDefault()
      return true
    }
    return false
  }, [])

  const onCellKeyDown = (e: CellKeyDownEvent<PartRow> | FullWidthCellKeyDownEvent<PartRow>) => {
    const ev = e.event as KeyboardEvent | null
    if (!ev || e.api.getEditingCells().length) return
    const mod = ev.ctrlKey || ev.metaKey
    if (ev.key === 'Enter' && !mod && !ev.altKey && !ev.shiftKey) {
      const cell = (ev.target as HTMLElement | null)?.closest('.ag-cell')
      const action = cell?.querySelector<HTMLElement>('a[href], button')
      if (action) {
        ev.preventDefault()
        action.click()
        return
      }
      if (e.data) {
        ev.preventDefault()
        latest.current.onActivate(e.data)
      }
    } else if (ev.key === 'Delete') {
      ev.preventDefault()
      const selected = e.api.getSelectedRows()
      const rows = selected.length ? selected : e.data ? [e.data] : []
      if (rows.length) latest.current.onDelete(rows)
    } else if (mod && ev.key.toLowerCase() === 'a') {
      // Textauswahl verhindert schon suppressKeys (synchron) – hier nur die Zeilen wählen
      selectLoaded(true)
    } else if (ev.key === 'Escape') {
      latest.current.onEscape?.()
    }
  }

  const focusTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(focusTimer.current), [])
  const onCellFocused = (e: CellFocusedEvent<PartRow>) => {
    if (e.rowIndex === null || e.rowPinned) return
    const node = e.api.getDisplayedRowAtIndex(e.rowIndex)
    if (!node?.data) return
    const row = node.data
    window.clearTimeout(focusTimer.current)
    focusTimer.current = window.setTimeout(() => latest.current.onFocusRow?.(row), 140)
  }

  const onCellClicked = (e: CellClickedEvent<PartRow>) => {
    if (e.column.getColId() === PART_NUMBER && e.data) latest.current.onActivate(e.data)
  }

  /** Doppelklick öffnet die Details (wie Enter); auf einem bearbeitbaren Wert mit dem Fokus in diesem Feld */
  const onCellDoubleClicked = (e: CellDoubleClickedEvent<PartRow>) => {
    const col = e.column.getColId()
    if (!e.data || col.startsWith('ag-Grid-')) return // Auswahlspalte: Doppelklick wählt nur
    latest.current.onActivate(e.data, col !== PART_NUMBER && e.column.isCellEditable(e.node) ? col : undefined)
  }

  // ------------------------------------------------------------------ Zustand speichern
  const initialState = useMemo(() => loadGridState(persistKey), [persistKey])
  const saveTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(saveTimer.current), [])
  const onStateUpdated = (e: StateUpdatedEvent<PartRow>) => {
    if (!e.sources.some((s) => PERSISTED_SOURCES.has(s))) return
    window.clearTimeout(saveTimer.current)
    const state = e.state
    saveTimer.current = window.setTimeout(() => saveGridState(persistKey, state), 400)
    if (e.sources.some((s) => LAYOUT_SOURCES.has(s))) latest.current.onLayoutChange?.()
  }

  // ------------------------------------------------------------------ Steuerung von außen
  const focusNode = (api: GridApi<PartRow>, node: IRowNode<PartRow>) => {
    if (node.rowIndex === null) return
    api.ensureNodeVisible(node, 'middle')
    api.setFocusedCell(node.rowIndex, PART_NUMBER)
  }

  const focusDefault = useCallback(() => {
    const api = apiRef.current
    if (!api) return
    const activeId = cells.active()
    const active = activeId ? api.getRowNode(activeId) : undefined
    if (active?.rowIndex != null && active.rowIndex !== undefined) {
      api.ensureNodeVisible(active, 'middle')
      api.setFocusedCell(active.rowIndex, PART_NUMBER)
    } else if (api.getDisplayedRowCount() > 0) api.setFocusedCell(0, PART_NUMBER)
  }, [cells])

  /** Anzahl der Treffer (nur die Zahl, keine Zeilen) */
  const count = useCallback(
    async (extra: PartFilter[], withQuery = true) => {
      const q = queryRef.current
      const page = await partsApi.query(table, {
        search: withQuery ? q.search || null : null,
        filters: [...(withQuery ? q.filters : []), ...extra],
        sort: [],
        offset: 0,
        limit: 1,
      })
      return page
    },
    [table],
  )

  /**
   * Position einer Zeile unter der aktuellen Sortierung (Zeilen davor) – so sortiert das Backend: Werte
   * aufsteigend/absteigend (Messwerte numerisch, nicht lesbare danach), leere Werte zuletzt, bei Gleichstand nach
   * Teilenummer. Mehrspaltige Sortierungen → null.
   */
  const positionOf = useCallback(
    async (pn: string, row: PartRow, sort: SortSpec[]): Promise<number | null> => {
      const byPn = { column: PART_NUMBER, op: 'lt' as const, value: pn }
      if (sort.length === 0 || (sort.length === 1 && sort[0].column === PART_NUMBER)) {
        const before = (await count([byPn])).total
        const total = totalRef.current ?? before + 1
        return sort[0]?.desc ? Math.max(0, total - 1 - before) : before
      }
      if (sort.length !== 1) return null
      const { column, desc } = sort[0]
      const field = category.fields.find((f) => f.column === column)
      const value = row[column] ?? ''
      if (!value.trim()) {
        const [filled, emptyBefore] = await Promise.all([
          count([{ column, op: 'notempty' }]),
          count([{ column, op: 'empty' }, byPn]),
        ])
        return filled.total + emptyBefore.total
      }
      if (isUnreadable(field, value)) return null
      const [before, ties] = await Promise.all([
        count([{ column, op: desc ? 'gt' : 'lt', value }]),
        count([{ column, op: 'eq', value }, byPn]),
      ])
      return before.total + ties.total
    },
    [category.fields, count],
  )

  useImperativeHandle(
    handleRef,
    (): PartsGridHandle => ({
      refresh: () => apiRef.current?.refreshInfiniteCache(),
      focus: () => focusDefault(),
      focusRow: (pn) => {
        const api = apiRef.current
        const node = api?.getRowNode(pn)
        if (api && node?.data && node.rowIndex !== null) focusNode(api, node)
        else focusDefault()
      },
      hasFocus: () => Boolean(rootRef.current?.contains(document.activeElement)),
      rowFromElement: (el) => {
        const id = el.closest('[row-id]')?.getAttribute('row-id')
        return id ? (apiRef.current?.getRowNode(id)?.data ?? null) : null
      },
      getFocusedRow: () => {
        const api = apiRef.current
        const cell = api?.getFocusedCell()
        if (!api || !cell || cell.rowIndex === null) return null
        return api.getDisplayedRowAtIndex(cell.rowIndex)?.data ?? null
      },
      locate: async (pn) => {
        const api = apiRef.current
        if (!api || !loadedOnceRef.current) return 'pending'
        const loaded = api.getRowNode(pn)
        if (loaded?.data && loaded.rowIndex !== null) {
          focusNode(api, loaded)
          return 'found'
        }
        try {
          const hit = await count([{ column: PART_NUMBER, op: 'eq', value: pn }])
          const row = hit.rows[0]
          if (!hit.total || !row) {
            // mit Suche/Filter nicht dabei – oder gar nicht vorhanden?
            const any = await count([{ column: PART_NUMBER, op: 'eq', value: pn }], false)
            return any.total ? 'hidden' : 'missing'
          }
          const index = await positionOf(pn, row, currentSort())
          if (index === null) return 'unsorted'
          if (apiRef.current !== api || api.isDestroyed()) return 'pending'
          api.ensureIndexVisible(Math.min(index, Math.max(0, api.getDisplayedRowCount() - 1)), 'middle')
          for (let i = 0; i < 40; i++) {
            const node = api.isDestroyed() ? undefined : api.getRowNode(pn)
            if (node?.data && node.rowIndex !== null) {
              focusNode(api, node)
              return 'found'
            }
            await wait(60)
          }
        } catch {
          return 'pending'
        }
        return 'unsorted'
      },
      editCell: (pn, column) => {
        const api = apiRef.current
        const node = api?.getRowNode(pn)
        const col = api?.getColumn(column)
        if (!api || !node?.data || node.rowIndex === null || !col || !col.isCellEditable(node)) return false
        api.ensureNodeVisible(node)
        api.ensureColumnVisible(col)
        api.setFocusedCell(node.rowIndex, column)
        api.startEditingCell({ rowIndex: node.rowIndex, colKey: column })
        return true
      },
      cellFromElement: (el) => {
        const api = apiRef.current
        const id = el.closest('[row-id]')?.getAttribute('row-id')
        const column = el.closest('.ag-cell[col-id]')?.getAttribute('col-id')
        const node = id ? api?.getRowNode(id) : undefined
        const col = column ? api?.getColumn(column) : undefined
        if (!api || !column || !col || !node?.data || column.startsWith('ag-Grid-')) return null
        return { column, label: labelOf(column), editable: column !== PART_NUMBER && col.isCellEditable(node) }
      },
      selectAllLoaded: () => selectLoaded(true),
      deselectAll: () => apiRef.current?.deselectAll(),
      getSort: currentSort,
      getVisibleColumns: () =>
        (apiRef.current?.getAllDisplayedColumns() ?? [])
          .map((c) => c.getColId())
          .filter((id) => !id.startsWith('ag-Grid-')),
      getColumns: () =>
        (apiRef.current?.getColumnState() ?? [])
          .filter((c) => !c.colId.startsWith('ag-Grid-'))
          .map((c) => ({ colId: c.colId, visible: !c.hide })),
      setColumnVisible: (colId, visible) => apiRef.current?.setColumnsVisible([colId], visible),
      applyView: (columns, sort) => {
        const api = apiRef.current
        if (!api) return
        if (columns.length) {
          const all = api.getColumnState().filter((c) => !c.colId.startsWith('ag-Grid-'))
          const rest = all.filter((c) => !columns.includes(c.colId)).map((c) => ({ colId: c.colId, hide: true }))
          api.applyColumnState({
            state: [...columns.filter((c) => all.some((a) => a.colId === c)).map((colId) => ({ colId, hide: false })), ...rest],
            applyOrder: true,
          })
        } else {
          api.resetColumnState()
        }
        api.applyColumnState({
          state: sort.map((s, i) => ({ colId: s.column, sort: s.desc ? 'desc' : 'asc', sortIndex: i })),
          defaultState: { sort: null },
        })
      },
      resetColumns: () => {
        const api = apiRef.current
        if (!api) return
        api.resetColumnState()
        api.applyColumnState({ defaultState: { sort: null } })
      },
      sortByPartNumber: () => apiRef.current?.applyColumnState({ defaultState: { sort: null } }),
      loadedCount: () => {
        let n = 0
        apiRef.current?.forEachNode((node) => {
          if (node.data) n += 1
        })
        return n
      },
    }),
    [currentSort, selectLoaded, focusDefault, count, positionOf, labelOf],
  )
  // ------------------------------------------------------------------ Darstellung
  const hasQuery = Boolean(search.trim() || filters.length)
  const overlayParams = useMemo(
    () => ({ empty: hasQuery ? noMatchState : emptyState, noMatch: noMatchState, loadingText: t("Bauteile werden geladen …") }),
    [hasQuery, emptyState, noMatchState, t],
  )
  const rowSelection = useMemo<RowSelectionOptions<PartRow>>(
    () => ({
      mode: 'multiRow',
      checkboxes: true,
      headerCheckbox: false,
      enableClickSelection: false,
      // nachladende Zeilen (Skelett) haben kein Kontrollkästchen
      isRowSelectable: (node) => Boolean(node.data),
      hideDisabledCheckboxes: true,
    }),
    [],
  )
  const defaultColDef = useMemo<ColDef<PartRow>>(
    () => ({ resizable: true, sortable: true, filter: false, minWidth: 72, suppressKeyboardEvent: suppressKeys }),
    [suppressKeys],
  )
  const selectionColumnDef = useMemo(
    () => ({
      width: 44,
      minWidth: 44,
      maxWidth: 44,
      pinned: 'left' as const,
      resizable: false,
      suppressHeaderMenuButton: true,
      headerComponent: SelectAllHeader,
      suppressKeyboardEvent: suppressKeys,
    }),
    [suppressKeys],
  )
  const getRowId = useCallback((p: { data: PartRow }) => String(p.data[PART_NUMBER] ?? ''), [])
  const rowClassRules = useMemo(
    () => ({
      'pf-row-loading': (p: { data?: PartRow }) => !p.data,
      'pf-row-active': (p: { data?: PartRow }) => Boolean(p.data && p.data[PART_NUMBER] === cells.active()),
    }),
    [cells],
  )
  const heights = GRID_DENSITY[density]
  // Skelettzeilen beim ersten Laden: so viele, wie die Kategorie voraussichtlich hat (höchstens eine Seite)
  const initialRows = Math.max(1, Math.min(24, category.part_count ?? 24))
  const firstFailed = loadError?.first === true

  return (
    <div
      ref={rootRef}
      role="region"
      aria-label={t("Bauteile: {1}", { 1: metadataLabel(category.label, t) })}
      aria-busy={((refreshing || !loadedOnce) && !loadError) || undefined}
      className={cn(
        'pf-grid pf-parts-grid relative isolate min-h-0 overflow-hidden rounded-card border border-line bg-surface shadow-card',
        refreshing && 'pf-grid-refreshing',
        loadError && 'pf-grid-failed',
        className,
      )}
    >
      <AgGridReact<PartRow>
        // localeText applies when the grid is created: a new language needs a new grid
        key={language}
        theme={forgeGridTheme}
        localeText={language === 'de' ? AG_GRID_LOCALE_DE : undefined}
        columnTypes={FORGE_COLUMN_TYPES}
        rowModelType="infinite"
        datasource={datasource}
        cacheBlockSize={BLOCK_SIZE}
        maxBlocksInCache={80}
        infiniteInitialRowCount={initialRows}
        blockLoadDebounceMillis={60}
        maxConcurrentDatasourceRequests={2}
        getRowId={getRowId}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        rowSelection={rowSelection}
        selectionColumnDef={selectionColumnDef}
        rowClassRules={rowClassRules}
        overlayComponent={GridOverlay}
        overlayComponentParams={overlayParams}
        initialState={initialState}
        onStateUpdated={onStateUpdated}
        onGridReady={(e: GridReadyEvent<PartRow>) => {
          apiRef.current = e.api
        }}
        onGridPreDestroyed={() => {
          apiRef.current = null
        }}
        onSelectionChanged={onSelectionChanged}
        onModelUpdated={() => {
          if (selectAllRef.current) selectLoaded(true)
        }}
        onCellValueChanged={onCellValueChanged}
        onCellKeyDown={onCellKeyDown}
        onCellFocused={onCellFocused}
        onCellClicked={onCellClicked}
        onCellDoubleClicked={onCellDoubleClicked}
        // Klicks starten keinen Editor (Doppelklick = Details); bearbeitet wird mit F2, Tippen oder dem Kontextmenü
        suppressClickEdit
        // Tab verlässt die Tabelle (Zelle für Zelle wäre bei 10.000 Zeilen eine Falle) – navigiert wird mit Pfeilen
        tabToNextCell={() => false}
        tabToNextHeader={() => false}
        // Mit Tab hinein: auf die aktive (bzw. erste) Zeile statt auf die Kopfzeile
        focusGridInnerElement={() => {
          const api = apiRef.current
          if (!api || api.getDisplayedRowCount() === 0) return false
          focusDefault()
          return true
        }}
        rowHeight={heights.rowHeight}
        headerHeight={heights.headerHeight}
        rowBuffer={12}
        animateRows={false}
        stopEditingWhenCellsLoseFocus
        tooltipShowDelay={500}
        suppressDragLeaveHidesColumns
      />
      {loadError !== null &&
        (firstFailed ? (
          <div
            className="absolute inset-x-0 bottom-0 z-sticky flex items-center justify-center overflow-y-auto bg-surface"
            style={{ top: heights.headerHeight }}
          >
            <EmptyState
              size="sm"
              titleAs="h2"
              illustration="offline"
              title={t("Bauteile konnten nicht geladen werden")}
              description={errorMessage(loadError.error)}
              actions={
                <Button variant="secondary" size="sm" leftIcon={<RotateCw />} onClick={retry}>
                  {t("Erneut versuchen")}
                </Button>
              }
            />
            <p role="alert" className="sr-only">
              {t("Bauteile konnten nicht geladen werden.")} {errorMessage(loadError.error)}
            </p>
          </div>
        ) : (
          <div
            className="absolute inset-x-0 z-sticky flex items-center gap-3 border-b border-danger/30 bg-[color-mix(in_oklab,var(--pf-surface)_92%,var(--pf-danger))] px-4 py-2"
            style={{ top: heights.headerHeight }}
          >
            <TriangleAlert aria-hidden className="size-4 shrink-0 text-danger-text" />
            <p role="alert" className="min-w-0 flex-1 text-ui text-fg">
              <span className="font-medium">{t("Einige Zeilen konnten nicht geladen werden.")}</span>{' '}
              <span className="text-fg-muted">{errorMessage(loadError.error)}</span>
            </p>
            <Button size="sm" variant="secondary" leftIcon={<RotateCw />} onClick={retry}>
              {t("Erneut versuchen")}
            </Button>
          </div>
        ))}
    </div>
  )
}
