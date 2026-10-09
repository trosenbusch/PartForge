/**
 * Spaltentypen des DataGrid: `{ field: 'Resistance', type: 'quantity' }` statt Renderer/Klassen je Spalte.
 * Mehrere Typen kombinierbar: `type: ['mono', 'right']`.
 */
import type { ColDef, ColTypeDefs } from 'ag-grid-community'
import { quantityComparator } from './cellFormat'
import { EnumBadgeCell, FootprintRefCell, LinkCell, QuantityCell, StatusCell, SymbolRefCell } from './cells'

export const FORGE_COLUMN_TYPES: ColTypeDefs = {
  /** Monospace (Werte, MPNs, Codes) */
  mono: { cellClass: 'pf-cell-mono' },
  /** rechtsbündig (Zahlen) */
  right: { cellClass: 'pf-cell-right', headerClass: 'pf-header-right' },
  /** technischer Wert mit Einheit, sortiert numerisch */
  quantity: { cellRenderer: QuantityCell, comparator: quantityComparator, filter: 'agTextColumnFilter' },
  /** Ganzzahl / Zahl */
  number: { cellClass: ['pf-cell-mono', 'pf-cell-right'], headerClass: 'pf-header-right', filter: 'agNumberColumnFilter' },
  /** Aufzählung als Badge */
  badge: { cellRenderer: EnumBadgeCell },
  /** Status mit Farbpunkt */
  status: { cellRenderer: StatusCell },
  /** URL oder Pfad */
  link: { cellRenderer: LinkCell },
  /** Symbolverweis mit Vorschau */
  symbolRef: { cellRenderer: SymbolRefCell, minWidth: 140 },
  /** Footprintverweis mit Vorschau */
  footprintRef: { cellRenderer: FootprintRefCell, minWidth: 160 },
}

/** Standard-Spaltendefinition: veränderbar, sortierbar, verschiebbar, Textfilter */
export const FORGE_DEFAULT_COL_DEF: ColDef = {
  resizable: true,
  sortable: true,
  filter: true,
  minWidth: 72,
  suppressHeaderMenuButton: false,
}
