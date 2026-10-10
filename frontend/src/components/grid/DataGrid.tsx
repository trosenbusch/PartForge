import { useI18n } from '@/lib/i18n'
/**
 * Typisierter Tabellen-Baustein auf Basis von AG Grid (Community, Theme „Forge“):
 * Tastaturnavigation, Zeilenauswahl, gespeicherte Spaltenbreiten/-reihenfolge, Lade-/Leer-Overlays im UI-Kit-Stil,
 * deutsche Texte, Spaltentypen (`quantity`, `mono`, `status`, `badge`, `link`, `symbolRef`, `footprintRef`).
 *
 *   <DataGrid rowData={rows} columnDefs={cols} getRowId={(r) => r['Part Number']} selection="multiple"
 *             persistKey="parts:Resistors" onRowActivated={openDrawer} emptyState={{ title: 'Noch keine Bauteile' }} />
 */
import {
  type CellKeyDownEvent,
  type FullWidthCellKeyDownEvent,
  type ColDef,
  type GridApi,
  type GridReadyEvent,
  type RowSelectionOptions,
  type StateUpdatedEvent,
} from 'ag-grid-community'
import { AgGridReact, type AgGridReactProps } from 'ag-grid-react'
import { useEffect, useMemo, useRef, type Ref } from 'react'
import { cn } from '@/lib/cn'
import { FORGE_COLUMN_TYPES, FORGE_DEFAULT_COL_DEF } from './columnTypes'
import { loadGridState, saveGridState } from './gridPrefs'
import { AG_GRID_LOCALE_DE } from './localeDe'
import './modules' // AG-Grid-Module global registrieren (nur die genutzten, siehe modules.ts)
import { GridOverlay, type GridEmptyState } from './overlays'
import { GRID_DENSITY, forgeGridTheme, type GridDensity } from './theme'
import './grid.css'

const PERSISTED_SOURCES = new Set(['columnOrder', 'columnSizing', 'columnVisibility', 'sort', 'columnPinning'])

export interface DataGridProps<TData>
  extends Omit<
    AgGridReactProps<TData>,
    'rowData' | 'columnDefs' | 'getRowId' | 'rowSelection' | 'loading' | 'theme' | 'modules' | 'initialState'
  > {
  rowData: TData[] | null | undefined
  columnDefs: ColDef<TData>[]
  /** Stabile Zeilen-ID (Pflicht für Auswahl über Neuladen hinweg) */
  getRowId?: (row: TData) => string
  /** Zeilenauswahl: einzeln (Klick), mehrfach (Kontrollkästchen, Umschalt/Strg) oder aus */
  selection?: 'single' | 'multiple' | false
  onSelectionChange?: (rows: TData[]) => void
  /** Enter oder Doppelklick auf einer Zeile (z. B. Detail öffnen) */
  onRowActivated?: (row: TData) => void
  /** Erstes Laden (Overlay) – bei vorhandenen Zeilen zeigt `refreshing` nur einen Ladebalken */
  loading?: boolean
  refreshing?: boolean
  emptyState?: GridEmptyState
  noMatchState?: GridEmptyState
  loadingText?: string
  /** Spaltenzustand speichern unter diesem Schlüssel (z. B. „parts:Resistors“) */
  persistKey?: string
  density?: GridDensity
  className?: string
  /** Zugriff auf die AG-Grid-Instanz (api) */
  gridRef?: Ref<AgGridReact<TData>>
  onApiReady?: (api: GridApi<TData>) => void
  'aria-label'?: string
}

export function DataGrid<TData>({
  rowData,
  columnDefs,
  getRowId,
  selection = false,
  onSelectionChange,
  onRowActivated,
  loading,
  refreshing,
  emptyState,
  noMatchState,
  loadingText,
  persistKey,
  density = 'compact',
  className,
  gridRef,
  onApiReady,
  defaultColDef,
  columnTypes,
  'aria-label': ariaLabel,
  ...rest
}: DataGridProps<TData>) {
  const { language } = useI18n()
  const initialState = useMemo(() => (persistKey ? loadGridState(persistKey) : undefined), [persistKey])
  const saveTimer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(saveTimer.current), [])

  const rowSelection = useMemo<RowSelectionOptions<TData> | undefined>(() => {
    if (selection === 'multiple') {
      return { mode: 'multiRow', checkboxes: true, headerCheckbox: true, enableClickSelection: true }
    }
    if (selection === 'single') return { mode: 'singleRow', checkboxes: false, enableClickSelection: true }
    return undefined
  }, [selection])

  const mergedDefaultColDef = useMemo<ColDef<TData>>(
    () => ({ ...(FORGE_DEFAULT_COL_DEF as ColDef<TData>), ...defaultColDef }),
    [defaultColDef],
  )
  const mergedTypes = useMemo(() => ({ ...FORGE_COLUMN_TYPES, ...columnTypes }), [columnTypes])
  const overlayParams = useMemo(() => ({ empty: emptyState, noMatch: noMatchState, loadingText }), [emptyState, noMatchState, loadingText])
  const rowIdFn = useMemo(() => (getRowId ? ({ data }: { data: TData }) => getRowId(data) : undefined), [getRowId])

  const onStateUpdated = (e: StateUpdatedEvent<TData>) => {
    if (!persistKey || !e.sources.some((s) => PERSISTED_SOURCES.has(s))) return
    window.clearTimeout(saveTimer.current)
    const state = e.state
    saveTimer.current = window.setTimeout(() => saveGridState(persistKey, state), 400)
  }

  const onCellKeyDown = (e: CellKeyDownEvent<TData> | FullWidthCellKeyDownEvent<TData>) => {
    const ev = e.event as KeyboardEvent | null
    if (!ev || ev.key !== 'Enter' || ev.ctrlKey || ev.altKey || ev.metaKey) return
    if (e.api.getEditingCells().length) return
    // Enter auf einer Zelle mit Link/Knopf (Datenblatt, Vorschau) löst diesen aus – sonst Zeile aktivieren
    const cell = (ev.target as HTMLElement | null)?.closest('.ag-cell')
    const action = cell?.querySelector<HTMLElement>('a[href], button')
    if (action) {
      ev.preventDefault()
      action.click()
      return
    }
    if (e.data && onRowActivated) {
      ev.preventDefault()
      onRowActivated(e.data)
    }
  }

  const heights = GRID_DENSITY[density]
  return (
    <div
      role="region"
      aria-label={ariaLabel}
      aria-busy={loading || refreshing || undefined}
      className={cn(
        'pf-grid relative isolate min-h-0 overflow-hidden rounded-card border border-line bg-surface shadow-card',
        refreshing && !loading && 'pf-grid-refreshing',
        className,
      )}
    >
      <AgGridReact<TData>
        {...rest}
        key={`${persistKey ?? 'grid'}:${language}`}
        ref={gridRef}
        theme={forgeGridTheme}
        rowData={rowData ?? null}
        columnDefs={columnDefs}
        defaultColDef={mergedDefaultColDef}
        columnTypes={mergedTypes}
        getRowId={rowIdFn}
        rowSelection={rowSelection}
        selectionColumnDef={{ width: 44, minWidth: 44, maxWidth: 44, pinned: 'left', suppressHeaderMenuButton: true, resizable: false }}
        loading={loading}
        overlayComponent={GridOverlay}
        overlayComponentParams={overlayParams}
        localeText={language === 'de' ? AG_GRID_LOCALE_DE : undefined}
        initialState={initialState}
        onStateUpdated={onStateUpdated}
        onGridReady={(e: GridReadyEvent<TData>) => {
          onApiReady?.(e.api)
          rest.onGridReady?.(e)
        }}
        onSelectionChanged={(e) => {
          onSelectionChange?.(e.api.getSelectedRows())
          rest.onSelectionChanged?.(e)
        }}
        onRowDoubleClicked={(e) => {
          if (e.data) onRowActivated?.(e.data)
          rest.onRowDoubleClicked?.(e)
        }}
        onCellKeyDown={(e) => {
          onCellKeyDown(e)
          rest.onCellKeyDown?.(e)
        }}
        rowHeight={rest.rowHeight ?? heights.rowHeight}
        headerHeight={rest.headerHeight ?? heights.headerHeight}
        animateRows={rest.animateRows ?? true}
        ensureDomOrder={rest.ensureDomOrder ?? true}
        suppressDragLeaveHidesColumns={rest.suppressDragLeaveHidesColumns ?? true}
        tooltipShowDelay={rest.tooltipShowDelay ?? 450}
      />
    </div>
  )
}
