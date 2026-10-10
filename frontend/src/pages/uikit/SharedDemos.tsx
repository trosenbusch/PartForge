import { metadataLabel, t as tr, useI18n } from '@/lib/i18n'
/**
 * UI-Kit, Bereich „Vorschau und Daten“: Live-Demos der geteilten Komponenten (components/preview, grid, data)
 * mit echten Backend-Daten (Footprint-/Symbol-Generator, Bauteile und Kategorien der geöffneten Bibliothek).
 */
import { useQuery } from '@tanstack/react-query'
import type { ColDef } from 'ag-grid-community'
import { Database } from 'lucide-react'
import { useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { api, errorMessage } from '@/api/client'
import { useCategories, type CategoryDef } from '@/api/library'
import { useWorkspace } from '@/api/system'
import type { Filled, ResponseOf } from '@/api/types'
import {
  CategoryTree,
  FileDropZone,
  GalleryCard,
  LazyThumbnail,
  SplitPane,
  TemplateTokenInput,
  VirtualGallery,
  useCategoryTreeItems,
  CATEGORY_GROUP_ORDER,
  type CategoryTreeItem,
  type TemplateField,
} from '@/components/data'
import { DataGrid, type RefPreview } from '@/components/grid'
import {
  FootprintCanvas,
  Package3D,
  PreviewPanel,
  SymbolCanvas,
  useFootprintPreview,
  useSymbolPreview,
  type FootprintPreviewData,
  type SymbolPreviewData,
} from '@/components/preview'
import { Badge, Callout, Card, CardContent, CardHeader, Field, SegmentedControl } from '@/components/ui'
import { formatNumber } from '@/lib/format'
import type { FootprintRequest } from '@/lib/geometry'
import { formatRkm, parseEngineering } from '@/lib/units'
import { DEMO_IC_REQUEST, OPAMP_DUAL_REQUEST, QFN16_REQUEST, SOIC8_REQUEST } from './demoData'

type FamilyInfo = Filled<ResponseOf<'/api/footprints/families', 'get'>>[number]
type PartsPage = Filled<ResponseOf<'/api/parts/{table}', 'get'>>
type PartRow = Record<string, unknown>
type StandardMatch = Filled<ResponseOf<'/api/symbols/standard-for', 'get'>>

function DemoSection({ title, description, actions, children }: { title: string; description?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <CardHeader title={title} description={description} actions={actions} className="border-b border-line pb-3" />
      <CardContent className="pt-4">{children}</CardContent>
    </Card>
  )
}

// --------------------------------------------------------------------------- Vorschau

function PreviewDemos({ fullscreen3d }: { fullscreen3d: boolean }) {
  const { t: tr } = useI18n()
  const soic = useFootprintPreview(SOIC8_REQUEST)
  const qfn = useFootprintPreview(QFN16_REQUEST)
  const opamp = useSymbolPreview(OPAMP_DUAL_REQUEST)
  const ic = useSymbolPreview({ ...DEMO_IC_REQUEST, description: tr(DEMO_IC_REQUEST.description ?? '') })
  const [highlight, setHighlight] = useState<string[]>(['3', '11'])

  return (
    <>
      <div className="grid grid-cols-1 gap-5 @[64rem]:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <DemoSection
          title="PreviewPanel"
          description={tr("Symbol, Footprint und 3D in einem Panel – Demo-IC mit QFN-16 (Exposed Pad), Bemaßung aus dem Generator-Protokoll")}
        >
          <PreviewPanel
            symbol={ic.data?.spec}
            footprint={qfn.data?.spec}
            calc={qfn.data?.calc}
            highlight={highlight}
            defaultTab={fullscreen3d ? '3d' : 'footprint'}
            defaultFullscreen={fullscreen3d}
            loading={{ symbol: ic.isFetching, footprint: qfn.isFetching }}
            error={{ symbol: ic.error ? errorMessage(ic.error) : null, footprint: qfn.error ? errorMessage(qfn.error) : null }}
            className="h-[520px]"
          />
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
            <span className="micro-label">{tr("Hervorheben")}</span>
            {[['3', '11'], ['1', '2', '15'], ['17'], []].map((h) => (
              <button
                key={h.join(',') || tr("keine")}
                type="button"
                aria-pressed={highlight.join(',') === h.join(',')}
                onClick={() => setHighlight(h)}
                className="mono rounded-control border border-line-strong px-2 py-0.5 text-2xs outline-none transition-colors focus-ring hover:bg-surface-2 aria-pressed:border-accent/40 aria-pressed:bg-accent-soft aria-pressed:text-accent-text"
              >
                {h.length ? h.join(' · ') : tr("keine")}
              </button>
            ))}
          </div>
        </DemoSection>
        <DemoSection title={tr("Kompakt (Detail-Drawer)")} description={tr("Zweifach-OPV (Teile A/B, Versorgung C) mit SOIC-8")}>
          <PreviewPanel
            symbol={opamp.data?.spec}
            footprint={soic.data?.spec}
            calc={soic.data?.calc}
            loading={{ symbol: opamp.isFetching, footprint: soic.isFetching }}
            className="h-[520px]"
          />
        </DemoSection>
      </div>

      <div className="grid grid-cols-1 gap-5 @[64rem]:grid-cols-3">
        <DemoSection title="SymbolCanvas" description={tr("theme=\"altium\", Teile A/B/C, Pin-Tooltip")}>
          <SymbolCanvas spec={opamp.data?.spec} theme="altium" className="h-72 rounded-control border border-line" />
        </DemoSection>
        <DemoSection title="FootprintCanvas" description={tr("SOIC-8 mit Bemaßung (Z/G/X/e), Pad 1 hervorgehoben")}>
          <FootprintCanvas spec={soic.data?.spec} calc={soic.data?.calc} highlight={['1']} className="h-72 rounded-control" />
        </DemoSection>
        <DemoSection title="Package3D" description={tr("lazy geladen, offline beleuchtet")}>
          <Package3D spec={soic.data?.spec} className="h-72 rounded-control" />
        </DemoSection>
      </div>
    </>
  )
}

// --------------------------------------------------------------------------- Tabelle

const FIELD_COLUMN_TYPE: Record<string, string | string[] | undefined> = {
  quantity: 'quantity',
  range: 'quantity',
  int: 'number',
  url: 'link',
  path: 'link',
}

/** Spalten aus den Felddefinitionen der Kategorie (Beispiel für Seiten) */
function columnsFor(category: CategoryDef | undefined, loaders: { symbol: LoaderFn; footprint: LoaderFn }, translate = tr): ColDef<PartRow>[] {
  const fields = category?.fields ?? []
  const wanted = [
    'Part Number',
    'Value',
    'Package',
    'Library Ref',
    'Footprint Ref',
    'Lifecycle',
    'PF Status',
    'Manufacturer',
    ...fields.filter((f) => f.kind === 'quantity' && !f.system && !f.common).map((f) => f.column),
    'ComponentLink1URL',
    'Footprint Path',
  ]
  const seen = new Set<string>()
  const cols: ColDef<PartRow>[] = []
  for (const column of wanted) {
    if (seen.has(column)) continue
    seen.add(column)
    const f = fields.find((x) => x.column === column)
    if (!f && fields.length) continue
    const col: ColDef<PartRow> = { field: column, headerName: metadataLabel(f?.label ?? column, translate), colId: column }
    if (column === 'Part Number') Object.assign(col, { type: 'mono', pinned: 'left', minWidth: 190 })
    else if (column === 'Value') Object.assign(col, { type: 'quantity', width: 110 })
    else if (column === 'Package') Object.assign(col, { type: 'badge', cellRendererParams: { mono: true }, width: 110 })
    else if (column === 'Library Ref')
      Object.assign(col, { type: 'symbolRef', cellRendererParams: { loadPreview: loaders.symbol, libraryField: 'Library Path' } })
    else if (column === 'Footprint Ref')
      Object.assign(col, { type: 'footprintRef', cellRendererParams: { loadPreview: loaders.footprint, libraryField: 'Footprint Path' } })
    else if (column === 'Lifecycle' || column === 'PF Status') Object.assign(col, { type: 'status', width: 130 })
    else if (f) col.type = FIELD_COLUMN_TYPE[f.kind]
    if (f?.kind === 'quantity') col.width = 120
    cols.push(col)
  }
  return cols
}

type LoaderFn = (ref: string, row: PartRow | undefined, signal: AbortSignal) => Promise<RefPreview | null>

function GridDemo() {
  const { t: tr } = useI18n()
  const workspace = useWorkspace()
  const hasWorkspace = Boolean(workspace.data)
  const categories = useCategories()
  const [table, setTable] = useState<'Resistors' | 'Capacitors'>('Resistors')
  const [mode, setMode] = useState<'daten' | 'laden' | 'leer'>('daten')
  const parts = useQuery({
    queryKey: ['parts', 'uikit-demo', table],
    queryFn: ({ signal }) => api.get<PartsPage>(`/api/parts/${encodeURIComponent(table)}`, { query: { limit: 200 }, signal }),
    enabled: hasWorkspace,
  })
  const category = categories.data?.find((c) => c.table === table)

  const loaders = useMemo(
    () => ({
      symbol: async (_ref: string, row: PartRow | undefined, signal: AbortSignal): Promise<RefPreview | null> => {
        const match = await api.get<StandardMatch>('/api/symbols/standard-for', {
          query: { table, values: JSON.stringify(row ?? {}) },
          signal,
        })
        if (!match.request) return null
        const preview = await api.post<SymbolPreviewData>('/api/symbols/preview', match.request, { signal })
        return { symbol: preview.spec }
      },
      footprint: async (_ref: string, row: PartRow | undefined, signal: AbortSignal): Promise<RefPreview | null> => {
        const size = String(row?.Size ?? row?.Package ?? '')
        if (!size) return null
        const req: FootprintRequest = {
          family: 'chip',
          density: 'N',
          with_3d: false,
          params: { kind: table === 'Capacitors' ? 'C' : 'R', size },
        }
        const preview = await api.post<FootprintPreviewData>('/api/footprints/preview', req, { signal })
        return { footprint: preview.spec }
      },
    }),
    [table],
  )
  const columns = useMemo(() => columnsFor(category, loaders, tr), [category, loaders, tr])
  const rows = mode === 'leer' || !hasWorkspace ? [] : (parts.data?.rows as PartRow[] | undefined)

  return (
    <DemoSection
      title="DataGrid"
      description={tr("AG Grid mit Theme „Forge“: Mengen-, Status-, Badge-, Link- und Verweis-Zellen (Vorschau beim Überfahren), Spaltenbreiten werden gespeichert")}
      actions={
        <div className="flex items-center gap-2">
          <SegmentedControl
            size="sm"
            aria-label={tr("Kategorie")}
            value={table}
            onValueChange={setTable}
            options={[
              { value: 'Resistors', label: tr("Widerstände") },
              { value: 'Capacitors', label: tr("Kondensatoren") },
            ]}
          />
          <SegmentedControl
            size="sm"
            aria-label={tr("Zustand")}
            value={mode}
            onValueChange={setMode}
            options={[
              { value: 'daten', label: tr("Daten") },
              { value: 'laden', label: tr("Lädt") },
              { value: 'leer', label: tr("Leer") },
            ]}
          />
        </div>
      }
    >
      {!hasWorkspace && (
        <Callout tone="info" title={tr("Keine Bibliothek geöffnet")} className="mb-3">
          {tr("Die Tabelle zeigt Bauteile der geöffneten Bibliothek – bitte eine Bibliothek öffnen oder anlegen.")}</Callout>
      )}
      <DataGrid<PartRow>
        aria-label={tr("Bauteile – {v0}", { v0: metadataLabel(category?.label ?? table, tr) })}
        rowData={rows}
        columnDefs={columns}
        getRowId={(r) => String(r['Part Number'])}
        selection="multiple"
        persistKey={`uikit:${table}`}
        loading={mode === 'laden' || (hasWorkspace && parts.isLoading)}
        refreshing={parts.isFetching && !parts.isLoading}
        loadingText={tr("Bauteile werden geladen …")}
        emptyState={{
          title: tr("Noch keine Bauteile"),
          description: tr("Erstes Bauteil anlegen oder eine Serie importieren – die Tabelle füllt sich sofort."),
          illustration: 'no-parts',
        }}
        onRowActivated={(r) => toast(tr("Geöffnet: {v0}", { v0: String(r['Part Number']) }))}
        onSelectionChange={(sel) => sel.length > 1 && toast(tr("{v0} Bauteile ausgewählt", { v0: formatNumber(sel.length) }), { id: 'uikit-grid-sel' })}
        className="h-[268px]"
      />
    </DemoSection>
  )
}

// --------------------------------------------------------------------------- Kategorien, Galerie, SplitPane

const FAMILY_ICON: Record<string, string> = {
  'Chip-Bauteile': 'square-split-horizontal',
  Dioden: 'triangle-right',
  'Transistoren (SOT/TO)': 'git-fork',
  'ICs (Gull-Wing)': 'cpu',
  'ICs (No-Lead)': 'microchip',
  'ICs (BGA)': 'circuit-board',
  Bedrahtet: 'plug',
}

function FootprintBrowser() {
  const { t: tr } = useI18n()
  const families = useQuery({
    queryKey: ['footprints', 'families'],
    queryFn: ({ signal }) => api.get<FamilyInfo[]>('/api/footprints/families', { signal }),
    staleTime: 10 * 60_000,
  })
  const [family, setFamily] = useState<string>('gullwing')
  const [selected, setSelected] = useState<string | null>(null)

  const items: CategoryTreeItem[] = useMemo(
    () =>
      (families.data ?? []).map((f) => ({
        id: f.key,
        label: tr(f.label),
        group: tr(f.group),
        count: f.presets.length,
        icon: FAMILY_ICON[f.group] ?? 'package',
        keywords: f.presets.map((p) => p.key).join(' '),
      })),
    [families.data, tr],
  )
  const groupOrder = useMemo(() => [...new Set((families.data ?? []).map((f) => tr(f.group)))], [families.data, tr])
  const presets = useMemo(() => {
    const list = (families.data ?? []).filter((f) => !family || f.key === family)
    return list.flatMap((f) => f.presets.map((p) => ({ family: f, preset: p })))
  }, [families.data, family])
  const total = (families.data ?? []).reduce((s, f) => s + f.presets.length, 0)

  return (
    <DemoSection
      title="SplitPane · CategoryTree · VirtualGallery"
      description={tr("Footprint-Generator: Gehäusefamilien als Baum (Suche, Tastatur), Vorlagen als virtualisierte Galerie mit nachgeladenen Vorschaubildern")}
    >
      <div className="h-[470px] overflow-hidden rounded-card border border-line bg-surface">
        <SplitPane
          persistKey="uikit.galerie"
          defaultSize={268}
          minSize={210}
          maxSize={380}
          label={tr("Breite des Baums")}
          collapsible
          start={
            <CategoryTree
              items={items}
              value={family}
              onValueChange={(id) => setFamily(id)}
              allItem={{ label: tr("Alle Gehäuse"), count: total }}
              groupOrder={groupOrder}
              loading={families.isLoading}
              persistKey="uikit.familien"
              aria-label={tr("Gehäusefamilien")}
              className="h-full p-3"
            />
          }
          end={
            <VirtualGallery
              aria-label={tr("Gehäusevorlagen")}
              items={presets}
              getKey={(x) => `${x.family.key}:${x.preset.key}`}
              minItemWidth={172}
              itemHeight={188}
              gap={12}
              padding={14}
              selectedKey={selected}
              onSelect={(x) => setSelected(`${x.family.key}:${x.preset.key}`)}
              onActivate={(x) => toast(tr("Vorlage „{v0}“ öffnen", { v0: x.preset.key }), { description: tr(x.preset.label) })}
              className="h-full"
              renderItem={(x, s) => (
                <GalleryCard
                  board
                  selected={s.selected}
                  active={s.active}
                  title={x.preset.key}
                  meta={tr(x.preset.label)}
                  thumbnail={
                    <LazyThumbnail
                      queryKey={['footprints', 'preset-thumb', x.family.key, x.preset.key]}
                      alt={tr("Footprint {v0}", { v0: x.preset.key })}
                      loadSvg={async (signal) => {
                        const req: FootprintRequest = { family: x.family.key, params: x.preset.params, density: 'N', with_3d: false }
                        const p = await api.post<FootprintPreviewData>('/api/footprints/preview', req, { signal })
                        return p.svg ?? ''
                      }}
                    />
                  }
                />
              )}
            />
          }
        />
      </div>
    </DemoSection>
  )
}

function CategoriesAndDrops() {
  const { t: tr } = useI18n()
  const workspace = useWorkspace()
  const tree = useCategoryTreeItems()
  const [category, setCategory] = useState<string>('Resistors')
  const onFiles = (files: File[]) =>
    toast.success(files.length === 1 ? tr("„{v0}“ übernommen", { v0: files[0].name }) : tr("{v0} Dateien übernommen", { v0: files.length }), {
      description: tr("Demo – es wird nichts hochgeladen."),
    })
  return (
    <div className="grid grid-cols-1 gap-5 @[64rem]:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <DemoSection title="CategoryTree" description={tr("Kategorien der Bibliothek mit Symbol, Farbe und Zähler")}>
        {workspace.data ? (
          <CategoryTree
            items={tree.items}
            value={category}
            onValueChange={setCategory}
            allItem={{ label: tr("Alle Bauteile"), count: tree.total }}
            groupOrder={CATEGORY_GROUP_ORDER}
            loading={tree.isLoading}
            persistKey="uikit.kategorien"
            className="h-[392px]"
          />
        ) : (
          <div className="flex h-[392px] flex-col items-center justify-center gap-2 text-center text-ui text-fg-subtle">
            <Database aria-hidden className="size-5" />
            {tr("Keine Bibliothek geöffnet")}</div>
        )}
      </DemoSection>
      <DemoSection title="FileDropZone" description={tr("Datenblatt (KI), Tabelle (CSV/XLSX) und kompakt – Typprüfung mit deutschen Hinweisen")}>
        <div className="grid grid-cols-1 gap-4 @[48rem]:grid-cols-2">
          <FileDropZone variant="pdf" size="md" onFiles={onFiles} className="@[48rem]:row-span-2" />
          <FileDropZone variant="table" size="md" multiple={false} onFiles={onFiles} />
          <FileDropZone variant="csv" size="sm" multiple={false} onFiles={onFiles} />
        </div>
      </DemoSection>
    </div>
  )
}

// --------------------------------------------------------------------------- Vorlagen

/** Vereinfachte Vorschau im Browser (Backend-Funktion für beliebige Vorlagen fehlt noch, siehe FOUNDATION.md) */
function renderLocal(template: string, values: PartRow): string {
  return template
    .replace(/\{([^{}:]+?)(?::([A-Za-z]+))?\}/g, (_m, name: string, format?: string) => {
      const key = Object.keys(values).find((k) => k.toLowerCase() === name.trim().toLowerCase())
      const raw = key ? values[key] : null
      if (raw === null || raw === undefined || raw === '') return ''
      const text = String(raw)
      switch (format?.toLowerCase()) {
        case 'upper':
          return text.toUpperCase()
        case 'lower':
          return text.toLowerCase()
        case 'rkm': {
          const v = parseEngineering(text)
          return v === null ? text : formatRkm(v)
        }
        case 'nounit':
          return text.replace(/[^\d.,kMGmunpµ±+-]+$/u, '')
        default:
          return text
      }
    })
    .replace(/\s{2,}/g, ' ')
    .trim()
}

function TemplateDemo() {
  const { t: tr } = useI18n()
  const categories = useCategories()
  const workspace = useWorkspace()
  const sample = useQuery({
    queryKey: ['parts', 'uikit-demo', 'Resistors'],
    queryFn: ({ signal }) => api.get<PartsPage>('/api/parts/Resistors', { query: { limit: 200 }, signal }),
    enabled: Boolean(workspace.data),
  })
  const category = categories.data?.find((c) => c.table === 'Resistors')
  const fields: TemplateField[] = useMemo(
    () => (category?.fields ?? []).map((f) => ({ name: f.column, label: metadataLabel(f.label, tr), kind: f.kind, unit: f.unit })),
    [category, tr],
  )
  const [template, setTemplate] = useState(category?.description_template ?? 'RES {Size} {Resistance} {Tolerance} {Power}')
  const [comment, setComment] = useState('{Resistance:rkm}')
  const values = (sample.data?.rows?.[1] ?? sample.data?.rows?.[0] ?? {}) as PartRow
  const [preview, setPreview] = useState('')
  const [commentPreview, setCommentPreview] = useState('')

  return (
    <DemoSection
      title="TemplateTokenInput"
      description={tr("Vorlagen für Beschreibung und Kommentar: Platzhalter als Chips, „{“ öffnet die Felder, „:“ die Formate, Strg+Leertaste fügt ein")}
      actions={values['Part Number'] ? <Badge variant="outline" className="mono">{String(values['Part Number'])}</Badge> : undefined}
    >
      <div className="grid grid-cols-1 gap-5 @[48rem]:grid-cols-2">
        <Field label={tr("Beschreibung (Vorlage)")} help={tr("Felder der Kategorie „Widerstände“; unbekannte Felder werden rot markiert")}>
          <TemplateTokenInput
            value={template}
            onValueChange={setTemplate}
            fields={fields}
            preview={preview}
            onPreviewRequest={(t) => setPreview(renderLocal(t, values))}
          />
        </Field>
        <Field label={tr("Kommentar (Vorlage)")} help={tr("Format „rkm“: 4k7, 100n, 6V3")}>
          <TemplateTokenInput
            value={comment}
            onValueChange={setComment}
            fields={fields}
            preview={commentPreview}
            onPreviewRequest={(t) => setCommentPreview(renderLocal(t, values))}
          />
        </Field>
      </div>
    </DemoSection>
  )
}

// --------------------------------------------------------------------------- Gesamt

export function SharedDemos({ fullscreen3d = false }: { fullscreen3d?: boolean }) {
  return (
    <div className="flex flex-col gap-5">
      <PreviewDemos fullscreen3d={fullscreen3d} />
      <GridDemo />
      <FootprintBrowser />
      <CategoriesAndDrops />
      <TemplateDemo />
    </div>
  )
}
