/**
 * AG-Grid-Module, die PartForge nutzt – statt `AllCommunityModule` (~1,2 MB) landen nur diese im Bundle.
 *
 * Global registriert (`ModuleRegistry`), sobald `@/components/grid` geladen ist: `DataGrid` und eigene
 * `<AgGridReact>`-Instanzen brauchen kein `modules`. Zusätzlich ersetzt `vite.config.ts` den Export
 * `AllCommunityModule` für Quelldateien durch {@link ForgeCommunityModule} (gleiche Module) – ältere
 * `modules={[AllCommunityModule]}` laden so nicht mehr das ganze Paket.
 *
 * **Neue Grid-Funktion?** Fehlt ein Modul, meldet AG Grid im Entwicklungsmodus (ValidationModule)
 * „error #200 … Module is not registered“ mit dem Modulnamen → hier ergänzen. Die Kommentare nennen, wofür.
 */
import {
  ClientSideRowModelModule,
  ColumnApiModule,
  ColumnAutoSizeModule,
  CellStyleModule,
  CustomEditorModule,
  DateFilterModule,
  EventApiModule,
  GridStateModule,
  HighlightChangesModule,
  InfiniteRowModelModule,
  LocaleModule,
  ModuleRegistry,
  NumberEditorModule,
  NumberFilterModule,
  QuickFilterModule,
  RenderApiModule,
  RowApiModule,
  RowSelectionModule,
  RowStyleModule,
  ScrollApiModule,
  TextEditorModule,
  TextFilterModule,
  TooltipModule,
  ValidationModule,
  type Module,
} from 'ag-grid-community'

export const FORGE_GRID_MODULES: Module[] = [
  ClientSideRowModelModule, // DataGrid: rowData
  InfiniteRowModelModule, // Bauteiltabelle: Server-Paging (rowModelType="infinite", refreshInfiniteCache)
  RowSelectionModule, // rowSelection, setNodesSelected, selectAll, getSelectedRows
  TextEditorModule, // editable ohne eigenen Editor
  NumberEditorModule, // editable bei Zahlenspalten
  CustomEditorModule, // eigene Zelleditoren (PartCellEditor)
  TextFilterModule, // filter: true, Spaltentyp „quantity“
  NumberFilterModule, // Spaltentyp „number“
  DateFilterModule, // filter: true bei Datumsspalten (Datentyp-Erkennung)
  QuickFilterModule, // quickFilterText
  GridStateModule, // initialState, onStateUpdated (gespeicherte Spalten)
  ColumnApiModule, // applyColumnState, getColumnState, setColumnsVisible, getAllDisplayedColumns
  ColumnAutoSizeModule, // Doppelklick auf den Spaltenrand, autoSizeColumns
  RowApiModule, // getRowNode, forEachNode, getDisplayedRowAtIndex, redrawRows
  ScrollApiModule, // ensureIndexVisible, ensureNodeVisible
  RenderApiModule, // refreshCells
  EventApiModule, // api.addEventListener
  HighlightChangesModule, // flashCells (gespeicherte Zellen aufleuchten)
  CellStyleModule, // cellClass, cellClassRules
  RowStyleModule, // rowClass, rowClassRules
  TooltipModule, // headerTooltip, tooltipValueGetter
  LocaleModule, // localeText (deutsch)
]

/** Ersatz für `AllCommunityModule` (siehe vite.config.ts): dieselben Module wie {@link FORGE_GRID_MODULES} */
export const ForgeCommunityModule: Module = {
  moduleName: 'AllCommunity',
  version: ClientSideRowModelModule.version,
  dependsOn: FORGE_GRID_MODULES,
} as Module

let registered = false

/** Module einmalig global registrieren (im Entwicklungsmodus mit ausführlichen Prüfmeldungen). */
export function registerForgeGridModules(): void {
  if (registered) return
  registered = true
  ModuleRegistry.registerModules(import.meta.env.DEV ? [...FORGE_GRID_MODULES, ValidationModule] : FORGE_GRID_MODULES)
}

registerForgeGridModules()
