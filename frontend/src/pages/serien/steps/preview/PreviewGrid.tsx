import { localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Tabelle der Serienvorschau (AG Grid über `DataGrid`, lazy geladen): Status, Teilenummer, Wert, Bauform, Hinweise
 * des Backends (gleich danach – der Grund für „Konflikt“/„ungültig“ bleibt ohne Scrollen sichtbar), Footprint
 * (Vorschau beim Überfahren, „neu“ = wird erzeugt, Kennung im Namen gedämpft – warum, sagt der Tooltip der Zelle),
 * Beschreibung, Kennwerte der Kategorie, Kommentar. Hinweise, die für alle Zeilen gelten, stehen über der Tabelle statt
 * in jeder Zeile. Ungültige Zeilen erscheinen gedämpft. Die Höhe gibt die Seite vor (`style`, passt sich den Zeilen an).
 */
import type { ColDef, GridApi, RowClassRules } from 'ag-grid-community'
import type { CustomCellRendererProps } from 'ag-grid-react'
import { TriangleAlert } from 'lucide-react'
import { useMemo, type CSSProperties } from 'react'
import type { PreviewRow, RowStatus, SeriesFootprintRef, SeriesTemplate } from '@/api/series'
import { DataGrid, FootprintRefCell, type RefCellParams } from '@/components/grid'
import { cn } from '@/lib/cn'
import { loadFootprintPreview } from '../../model/footprintPreview'
import type { Density } from '../../model/settings'
import { ROW_STATUS, rowMessages, STATUS_ORDER, TONE_DOT, TONE_TEXT } from '../../model/status'
import { valueLabelFor } from '../../model/template'
import './preview-grid.css'

export interface GridRow extends PreviewRow {
  index: number
}

/** Kennwerte, die als eigene Spalten erscheinen (sofern die Serie sie füllt) */
const FACT_COLUMNS = [
  'Tolerance',
  'Power',
  'Voltage',
  'TCR',
  'Dielectric',
  'Height',
  'Current Rating',
  'Saturation Current',
  'DCR',
  'SRF',
]

const VALUE_FIELDS = ['Resistance', 'Capacitance', 'Inductance', 'Impedance']

function StatusRenderer({ value }: CustomCellRendererProps<GridRow, RowStatus>) {
  const { t: tr } = useI18n()
  if (!value) return null
  const meta = ROW_STATUS[value]
  return (
    <span className="pf-cell-inline gap-1.5">
      <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', TONE_DOT[meta.tone])} />
      <span className={cn('font-medium', TONE_TEXT[meta.tone])}>{tr(meta.label)}</span>
    </span>
  )
}

function PartNumberRenderer({ value, data }: CustomCellRendererProps<GridRow, string>) {
  const { t: tr } = useI18n()
  if (value) return <span className="mono">{value}</span>
  if (data?.status === 'invalid') return <span className="text-fg-subtle">–</span>
  return <span className="italic text-fg-subtle">{tr("wird vergeben")}</span>
}

function FootprintRenderer(props: CustomCellRendererProps<GridRow> & RefCellParams<GridRow>) {
  const { t: tr } = useI18n()
  const fp = props.data?.footprint
  return (
    <span className="pf-cell-inline w-full min-w-0 gap-2">
      <span className="flex min-w-0 flex-1">
        <FootprintRefCell {...(props as CustomCellRendererProps & RefCellParams)} />
      </span>
      {fp && !fp.exists && (
        <span className="shrink-0 rounded-full border border-info/30 bg-info/10 px-1.5 text-2xs font-medium leading-4 text-info-text">
          {tr("neu")}</span>
      )}
    </span>
  )
}

function MessagesRenderer({ value, data }: CustomCellRendererProps<GridRow, string>) {
  if (!value) return <span className="text-fg-subtle">–</span>
  const blocked = data?.status === 'invalid' || data?.status === 'conflict'
  return (
    <span className={cn('pf-cell-inline min-w-0 gap-1.5', blocked ? 'text-fg' : 'text-fg-muted')}>
      <TriangleAlert
        aria-hidden
        className={cn('size-3.5 shrink-0', data?.status === 'conflict' ? 'text-danger' : 'text-warning')}
      />
      <span className="truncate">{value}</span>
    </span>
  )
}

export interface PreviewGridProps {
  rows: GridRow[]
  /** Hinweise, die über der Tabelle stehen (gelten für alle Zeilen) – nicht je Zeile wiederholen */
  hiddenMessages: ReadonlySet<string>
  template: SeriesTemplate
  /** Spaltenname → deutsche Bezeichnung (Felder der Kategorie) */
  labels: Record<string, string>
  internalScheme: boolean
  density: Density
  quickFilter: string
  onApiReady: (api: GridApi<GridRow>) => void
  /** Footprints der Vorschau – je Name einmal mit `name_reason` (Grund einer Kennung im Namen) */
  footprints: SeriesFootprintRef[]
  className?: string
  style?: CSSProperties
}

export default function PreviewGrid({
  rows,
  hiddenMessages,
  template,
  labels,
  internalScheme,
  density,
  quickFilter,
  onApiReady,
  footprints,
  className,
  style,
}: PreviewGridProps) {
  const { t: tr } = useI18n()
  const reasons = useMemo(() => {
    const out = new Map<string, string>()
    for (const f of footprints) if (f.name_reason) out.set(f.name, f.name_reason)
    return out
  }, [footprints])
  const present = useMemo(() => {
    const keys = new Set<string>()
    for (const r of rows.slice(0, 400)) for (const [k, v] of Object.entries(r.values)) if (v) keys.add(k)
    return keys
  }, [rows])
  const hasMessages = useMemo(() => rows.some((r) => r.messages.some((m) => !hiddenMessages.has(m))), [rows, hiddenMessages])

  const columns = useMemo<ColDef<GridRow>[]>(() => {
    const valueField = VALUE_FIELDS.find((f) => present.has(f))
    const loadPreview: RefCellParams<GridRow>['loadPreview'] = (name, row, signal) => {
      const ref = row?.footprint ?? { name, exists: true, size: row?.size ?? null, library: null }
      return loadFootprintPreview(ref, template, density, signal)
    }
    const cols: (ColDef<GridRow> | null)[] = [
      {
        colId: 'status',
        headerName: tr("Status"),
        field: 'status',
        width: 108,
        pinned: 'left',
        cellRenderer: StatusRenderer,
        comparator: (a: RowStatus, b: RowStatus) => STATUS_ORDER.indexOf(a) - STATUS_ORDER.indexOf(b),
        filterValueGetter: (p) => (p.data ? tr(ROW_STATUS[p.data.status].label) : ''),
      },
      {
        colId: 'pn',
        headerName: tr("Teilenummer"),
        valueGetter: (p) => p.data?.part_number ?? '',
        width: 200,
        pinned: 'left',
        cellClass: 'pf-cell-mono',
        cellRenderer: PartNumberRenderer,
      },
      internalScheme
        ? { colId: 'mpn', headerName: tr("Hersteller-Teilenummer"), field: 'mpn', width: 200, type: 'mono' }
        : null,
      {
        colId: 'value',
        headerName: labels[valueField ?? ''] ?? valueLabelFor(template),
        valueGetter: (p) => (p.data ? (valueField ? (p.data.values[valueField] ?? p.data.value) : p.data.value) : ''),
        width: 112,
        type: ['quantity', 'right'],
      },
      { colId: 'size', headerName: tr("Bauform"), field: 'size', width: 88, type: 'mono' },
      hasMessages
        ? {
            colId: 'messages',
            headerName: tr("Hinweise"),
            valueGetter: (p) => (p.data ? rowMessages(p.data, hiddenMessages).map(localizeMessage).join(' · ') : ''),
            getQuickFilterText: (p) => p.data ? `${rowMessages(p.data, hiddenMessages).join(' · ')} ${p.value ?? ''}` : '',
            flex: 1.6,
            minWidth: 280,
            cellRenderer: MessagesRenderer,
            tooltip: (p) => (p.value ? String(p.value) : undefined),
          }
        : null,
      {
        colId: 'footprint',
        headerName: tr("Footprint"),
        valueGetter: (p) => p.data?.footprint?.name ?? '',
        width: 200,
        cellRenderer: FootprintRenderer,
        cellRendererParams: { loadPreview } satisfies RefCellParams<GridRow>,
        tooltip: (p) => {
          const reason = p.value ? reasons.get(String(p.value)) : undefined
          return reason ? localizeMessage(reason) : undefined
        },
      },
      {
        colId: 'description',
        headerName: labels.Description ?? tr("Beschreibung"),
        valueGetter: (p) => p.data?.values.Description ?? '',
        flex: 1.3,
        minWidth: 220,
        tooltip: (p) => (p.value ? String(p.value) : undefined),
      },
      ...FACT_COLUMNS.filter((c) => present.has(c)).map<ColDef<GridRow>>((c) => ({
        colId: `f:${c}`,
        headerName: labels[c] ?? c,
        valueGetter: (p) => p.data?.values[c] ?? '',
        width: c === 'Voltage' || c === 'TCR' || c === 'Current Rating' || c === 'Saturation Current' ? 128 : 104,
        type: 'quantity',
      })),
      {
        colId: 'comment',
        headerName: labels.Comment ?? tr("Kommentar"),
        valueGetter: (p) => p.data?.values.Comment ?? '',
        width: 112,
        type: 'mono',
      },
    ]
    return cols.filter((c): c is ColDef<GridRow> => c !== null)
  }, [present, labels, internalScheme, template, density, hasMessages, hiddenMessages, reasons, tr])

  const rowClassRules = useMemo<RowClassRules<GridRow>>(
    () => ({
      'pf-series-invalid': (p) => p.data?.status === 'invalid',
      'pf-series-conflict': (p) => p.data?.status === 'conflict',
    }),
    [],
  )

  return (
    <div className={className} style={style}>
      <DataGrid<GridRow>
        aria-label={tr("Vorschau der Serie")}
        rowData={rows}
        columnDefs={columns}
        getRowId={(r) => String(r.index)}
        persistKey={`serien:vorschau-v2:${template.category}`}
        quickFilterText={quickFilter}
        rowClassRules={rowClassRules}
        onApiReady={onApiReady}
        noMatchState={{ title: tr("Keine Zeile passt"), description: tr("Filter oder Suche anpassen."), illustration: 'search-empty' }}
        emptyState={{ title: tr("Keine Zeilen"), description: tr("Mit diesem Filter gibt es keine Zeilen."), illustration: 'search-empty' }}
        className="pf-series-grid h-full"
      />
    </div>
  )
}
