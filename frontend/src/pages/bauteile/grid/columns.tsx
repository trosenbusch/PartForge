import { metadataLabel, t } from '@/lib/i18n'
/**
 * Spalten der Bauteiltabelle aus den Felddefinitionen der Kategorie: Beschriftung, Breite, Darstellung je Feldart
 * (Messwerte rechtsbündig in Mono, Auswahlwerte als Badge, Links, Symbol-/Footprint-Verweise mit Vorschau,
 * Systemfelder gedämpft, Freigabe als Status) und Bearbeitung über den {@link PartCellEditor}.
 */
import type { CellClassParams, ColDef, ICellRendererParams, ValueFormatterParams } from 'ag-grid-community'
import type { CategoryDef, FieldDef } from '@/api/library'
import { loadLibraryPreview, type FootprintDetail, type PartRow, type SymbolDetail } from '@/api/parts'
import { queryClient } from '@/api/queryClient'
import { formatQuantityText, type StatusTone } from '@/components/grid/cellFormat'
import { EnumBadgeCell, FootprintRefCell, StatusCell, SymbolRefCell, type RefPreview } from '@/components/grid/cells'
import {
  columnOrder,
  defaultVisible,
  defaultWidth,
  formatDateText,
  isEditable,
  isMono,
  isUnreadable,
  KIND_LABEL,
  PN,
  RELEASE_TONES,
  STATUS,
} from '../model/fields'
import { BoolCell, DatasheetCell, LibraryPathCell, PartNumberCell } from './cells'
import { PartCellEditor } from './PartCellEditor'

const ROHS_TONES: Record<string, StatusTone> = { Ja: 'success', Nein: 'danger', Unbekannt: 'neutral' }

export interface ColumnContext {
  table: string
  /** Teilenummern-Schema der Bibliothek („mpn“ blendet die Hersteller-Teilenummer aus) */
  scheme: string | undefined
  /** Fehler einer Zelle (nach fehlgeschlagenem Speichern) */
  cellError: (pn: string, column: string) => string | undefined
  isSaving: (pn: string, column: string) => boolean
  isNew: (pn: string) => boolean
}

async function loadSymbol(ref: string, _row: unknown, signal: AbortSignal): Promise<RefPreview | null> {
  const d = (await loadLibraryPreview(queryClient, 'symbol', ref, signal)) as SymbolDetail | null
  return d ? { symbol: d.spec, description: d.record.library } : null
}

async function loadFootprint(ref: string, _row: unknown, signal: AbortSignal): Promise<RefPreview | null> {
  const d = (await loadLibraryPreview(queryClient, 'footprint', ref, signal)) as FootprintDetail | null
  return d ? { footprint: d.spec, description: d.record.library } : null
}

/** Leere Zelle: Gedankenstrich (wie die Renderer) – nicht geladene Zeilen bleiben leer (Skelett) */
const emptyText = (p: ValueFormatterParams<PartRow>) => (p.data ? '–' : '')

/** Renderer nur für geladene Zeilen (nicht geladene Zeilen zeigen das Skelett aus bauteile.css) */
function rendererFor(field: FieldDef, ctx: ColumnContext): Pick<ColDef<PartRow>, 'cellRendererSelector' | 'valueFormatter'> {
  const only = (component: unknown, params?: Record<string, unknown>) => ({
    cellRendererSelector: (p: ICellRendererParams<PartRow>) => (p.data ? { component, params } : undefined),
  })
  const col = field.column
  if (col === PN) return only(PartNumberCell, { isNew: ctx.isNew })
  if (col === STATUS) return only(StatusCell, { tones: RELEASE_TONES })
  if (col === 'Lifecycle') return only(StatusCell)
  if (col === 'RoHS') return only(StatusCell, { tones: ROHS_TONES })
  if (col === 'Library Ref') return only(SymbolRefCell, { loadPreview: loadSymbol, libraryField: 'Library Path' })
  if (/^Footprint Ref( \d+)?$/.test(col)) {
    const n = col.match(/(\d+)$/)?.[1]
    return only(FootprintRefCell, { loadPreview: loadFootprint, libraryField: n ? `Footprint Path ${n}` : 'Footprint Path' })
  }
  switch (field.kind) {
    case 'quantity':
    case 'range':
      return {
        valueFormatter: (p: ValueFormatterParams<PartRow>) =>
          !p.value ? emptyText(p) : isUnreadable(field, String(p.value)) ? String(p.value) : formatQuantityText(String(p.value)),
      }
    case 'enum':
      return only(EnumBadgeCell, { mono: isMono(field) || col === 'Size', labels: Object.fromEntries(field.options.map((value) => [value, metadataLabel(value)])) })
    case 'bool':
      return only(BoolCell)
    case 'url':
      return only(DatasheetCell)
    case 'path':
      return only(LibraryPathCell)
    case 'date':
      return { valueFormatter: (p: ValueFormatterParams<PartRow>) => (p.value ? formatDateText(String(p.value)) : emptyText(p)) }
    default:
      return { valueFormatter: (p: ValueFormatterParams<PartRow>) => (p.value ? String(p.value) : emptyText(p)) }
  }
}

function headerTooltip(field: FieldDef): string {
  const parts = [metadataLabel(field.label, t)]
  if (field.column !== field.label) parts.push(t("Altium-Parameter „{1}“", { 1: field.column }))
  parts.push(field.unit ? t("{1} in {2}", { 1: KIND_LABEL[field.kind], 2: field.unit }) : KIND_LABEL[field.kind])
  if (field.required) parts.push(t("Pflichtfeld"))
  if (field.help) parts.push(metadataLabel(field.help, t))
  return parts.join(' · ')
}

export function buildColumnDefs(category: CategoryDef, ctx: ColumnContext, translate = t): ColDef<PartRow>[] {
  return columnOrder(category).map((field) => {
    const col = field.column
    const numeric = field.kind === 'quantity' || field.kind === 'int'
    const cellClass = [
      isMono(field) ? 'pf-cell-mono' : '',
      numeric ? 'pf-cell-right' : '',
      field.system && col !== STATUS ? 'pf-cell-system' : '',
      field.kind === 'date' ? 'pf-cell-system pf-cell-mono' : '',
    ].filter(Boolean)
    const headerClass = [numeric ? 'pf-header-right' : '', field.system ? 'pf-header-system' : ''].filter(Boolean)
    const key = (p: CellClassParams<PartRow>) => (p.data ? String(p.data[PN] ?? '') : '')
    const def: ColDef<PartRow> = {
      colId: col,
      headerName: metadataLabel(field.label, translate),
      headerTooltip: headerTooltip(field),
      valueGetter: (p) => (p.data ? (p.data[col] ?? null) : undefined),
      valueSetter: (p) => {
        if (!p.data) return false
        const raw: unknown = p.newValue
        const next = raw === null || raw === undefined || String(raw).trim() === '' ? null : String(raw)
        if ((p.data[col] ?? null) === next) return false
        p.data[col] = next
        return true
      },
      width: defaultWidth(field),
      minWidth: col === PN ? 140 : 72,
      hide: !defaultVisible(field, ctx.scheme, category),
      pinned: col === PN ? 'left' : undefined,
      lockPinned: col === PN,
      lockVisible: col === PN,
      suppressMovable: col === PN,
      sortable: true,
      filter: false,
      editable: (p) => Boolean(p.data) && isEditable(field) && col !== PN,
      cellEditor: PartCellEditor,
      cellEditorPopup: true,
      cellEditorPopupPosition: 'over',
      cellEditorParams: { field, table: ctx.table },
      cellClass,
      headerClass,
      cellClassRules: {
        'pf-cell-empty': (p) => Boolean(p.data) && (p.value === null || p.value === undefined || p.value === ''),
        'pf-cell-error': (p) => Boolean(p.data && ctx.cellError(key(p), col)),
        'pf-cell-saving': (p) => Boolean(p.data && ctx.isSaving(key(p), col)),
        // Wert, den das Backend nicht lesen kann (z. B. „abc“ als Toleranz): zählt beim Sortieren/Filtern nicht
        'pf-cell-unreadable': (p) => Boolean(p.data) && typeof p.value === 'string' && isUnreadable(field, p.value),
      },
      // `tooltip` mit Funktion statt `tooltipValueGetter` (seit AG Grid 36.2 veraltet, Warnung #306)
      tooltip: (p) => {
        if (!p.data) return undefined
        const err = ctx.cellError(String(p.data[PN] ?? ''), col)
        if (err) return t("Nicht gespeichert: {1}", { 1: err })
        if (typeof p.value === 'string' && isUnreadable(field, p.value)) {
          return t("„{1}“ ist als {2}{3} nicht lesbar – zählt beim Sortieren und Filtern nicht. F2 bearbeitet.", { 1: p.value, 2: KIND_LABEL[field.kind], 3: field.unit ? t(" in {1}", { 1: field.unit }) : '' })
        }
        // lange Texte (Beschreibung) vollständig zeigen
        const v = p.value === null || p.value === undefined ? '' : String(p.value)
        return v.length > 32 && (field.kind === 'text' || field.kind === 'url') ? v : undefined
      },
      ...rendererFor(field, ctx),
    }
    return def
  })
}
