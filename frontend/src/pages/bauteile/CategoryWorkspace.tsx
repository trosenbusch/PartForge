import { metadataLabel, useI18n } from '@/lib/i18n'
/**
 * Arbeitsbereich einer Kategorie: Werkzeugleiste (Suche, Filter, Ansichten, Spalten, Export, Import), aktive Filter,
 * Tabelle mit Mehrfachauswahl und Leiste, Detailbereich – plus Massenbearbeitung, Duplizieren, Löschen, Befehle
 * (Strg+K) und Tastenkürzel. Das geöffnete Bauteil steht in der Adresse (`?pn=`).
 *
 * Tastatur zwischen den Bereichen: **F6** springt Suche → Tabelle → Details (⇧F6 zurück); Tab verlässt die Tabelle.
 */
import { useQueryClient } from '@tanstack/react-query'
import { ArrowDownAZ, Columns3, Download, FileScan, FilterX, Layers, ListFilter, PanelLeft, PencilLine, Plus, Search, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { useRegisterCommands } from '@/app/commands'
import type { CategoryDef } from '@/api/library'
import { errorMessage } from '@/api/client'
import {
  invalidateParts,
  partsApi,
  partsKeys,
  PART_NUMBER,
  useSavedViews,
  type ExportFormat,
  type PartFilter,
  type PartRow,
  type SavedView,
  type SortSpec,
} from '@/api/parts'
import { useWorkspace } from '@/api/system'
import { Button } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useHotkey } from '@/lib/hotkeys'
import type { GridEmptyState } from '@/components/grid'
import { BulkBar } from './BulkBar'
import { DetailDock } from './DetailDock'
import { PartDetailPanel } from './detail/PartDetailPanel'
import { BulkUpdateDialog, type BulkTarget } from './dialogs/BulkUpdateDialog'
import { DuplicateDialog } from './dialogs/DuplicateDialog'
import { PartsGrid, type LocateResult, type PartsGridHandle } from './grid/PartsGrid'
import { RowContextMenu } from './grid/RowContextMenu'
import { confirmAndDelete, fetchMatchingRows, type DeleteTarget } from './model/actions'
import { canonicalFilterOp, DATASHEET, fromPartFilters, toPartFilters } from './model/fields'
import { openDatasheet } from './model/links'
import { useBauteile, useTableQuery, useTreeVisibility } from './model/store'
import { showChangeToast } from './model/undo'
import { useExport } from './model/useExport'
import { ColumnChooser } from './toolbar/ColumnChooser'
import { ExportMenu } from './toolbar/ExportMenu'
import { ActiveFilters, FilterBuilder } from './toolbar/FilterBuilder'
import { PartsToolbar } from './toolbar/PartsToolbar'
import { ViewsMenu } from './toolbar/ViewsMenu'

export interface CategoryWorkspaceProps {
  category: CategoryDef
  /** Gerade angelegte Teilenummern (Markierung „neu“) */
  newPns: ReadonlySet<string>
  onNewPns: (pns: string[]) => void
  onNewPart: () => void
  onImport: () => void
  /** Trefferzahl der Tabelle (null = unbekannt) */
  onTotalChange?: (total: number | null) => void
}

/** Filter vergleichbar machen (Reihenfolge, Wertdarstellung und Schreibweise „before“/„lt“ egal) */
const filterKey = (filters: PartFilter[]) =>
  filters
    .map(
      (f) =>
        `${f.column}|${canonicalFilterOp(f.op)}|${JSON.stringify(Array.isArray(f.value) ? [...f.value].map(String).sort() : (f.value ?? null))}`,
    )
    .sort()
    .join('\n')
const sortKey = (sort: SortSpec[]) => sort.map((s) => `${s.column}:${s.desc ? 'desc' : 'asc'}`).join(',')

export function CategoryWorkspace({ category, newPns, onNewPns, onNewPart, onImport, onTotalChange }: CategoryWorkspaceProps) {
  const { t } = useI18n()
  const table = category.table
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const scheme = useWorkspace().data?.settings.part_number_scheme
  const query = useTableQuery(table)
  const setSearch = useBauteile((s) => s.setSearch)
  const setFilters = useBauteile((s) => s.setFilters)
  const setQuery = useBauteile((s) => s.setQuery)
  const density = useBauteile((s) => s.density)
  const setDensity = useBauteile((s) => s.setDensity)
  const detailWidth = useBauteile((s) => s.detailWidth)
  const setDetailWidth = useBauteile((s) => s.setDetailWidth)

  const grid = useRef<PartsGridHandle | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const [total, setTotal] = useState<number | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)
  const [selection, setSelection] = useState<PartRow[]>([])
  /** Auswahl umfasst alle geladenen Zeilen (dann „Alle Treffer auswählen“ anbieten) */
  const [coversLoaded, setCoversLoaded] = useState(false)
  const [allMatching, setAllMatching] = useState(false)
  const [filterOpen, setFilterOpen] = useState(false)
  const [filterFocus, setFilterFocus] = useState<string | null>(null)
  const [bulkOpen, setBulkOpen] = useState(false)
  const [duplicateRows, setDuplicateRows] = useState<PartRow[] | null>(null)
  const [width, setWidth] = useState(1200)
  const rootRef = useRef<HTMLDivElement>(null)

  // Nur Bedingungen auf vorhandene Felder (Kategorie kann sich geändert haben); Datumswerte als ISO
  const partFilters = useMemo(() => {
    const columns = new Set(category.fields.map((f) => f.column))
    return toPartFilters(
      query.filters.filter((f) => columns.has(f.column)),
      category.fields,
    )
  }, [query.filters, category.fields])
  const hasQuery = Boolean(query.search.trim() || partFilters.length)

  // „Alle Treffer“ gilt nur für die Abfrage, für die es gewählt wurde
  const queryKey = JSON.stringify([query.search, partFilters])
  const [selectedFor, setSelectedFor] = useState(queryKey)
  if (selectedFor !== queryKey) {
    setSelectedFor(queryKey)
    setAllMatching(false)
  }

  // ------------------------------------------------------------------ Detail (?pn=)
  const detailPn = params.get('pn')
  const tree = useTreeVisibility(Boolean(detailPn))
  const [rowCache, setRowCache] = useState<PartRow | null>(null)
  /** Doppelklick auf einen Wert: dieses Feld im Detailbereich fokussieren (neuer `nonce` = erneut) */
  const [focusField, setFocusField] = useState<{ pn: string; column: string; nonce: number } | null>(null)
  const internalPn = useRef<string | null>(null)
  const openDetail = useCallback(
    (row: PartRow, focusColumn?: string) => {
      const pn = String(row[PART_NUMBER] ?? '')
      if (!pn) return
      internalPn.current = pn
      setRowCache(row)
      setFocusField(focusColumn ? { pn, column: focusColumn, nonce: Date.now() } : null)
      setParams(
        (p) => {
          const next = new URLSearchParams(p)
          next.set('pn', pn)
          return next
        },
        { replace: true },
      )
    },
    [setParams],
  )
  const closeDetail = useCallback(() => {
    const previous = internalPn.current
    internalPn.current = null
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        next.delete('pn')
        return next
      },
      { replace: true },
    )
    // Fokus zurück auf die Zeile, deren Details offen waren
    window.setTimeout(() => (previous ? grid.current?.focusRow(previous) : grid.current?.focus()), 0)
  }, [setParams])

  // von außen gesetzt (Schnellsuche, Übersicht, neu angelegt) → Zeile suchen, hinscrollen, sonst erklären
  const resetQuery = useCallback(() => setQuery(table, { search: '', filters: [], viewId: null }), [setQuery, table])
  useEffect(() => {
    if (!detailPn || internalPn.current === detailPn) return
    internalPn.current = detailPn
    let cancelled = false
    const report = (result: LocateResult) => {
      if (result === 'hidden') {
        toast.info(t("Bauteil ist durch Suche oder Filter ausgeblendet"), {
          id: 'pn-hidden',
          description: detailPn,
          action: { label: t("Zurücksetzen"), onClick: resetQuery },
        })
      } else if (result === 'unsorted') {
        toast.info(t("Bauteil geöffnet – in der Tabelle nicht markiert"), {
          id: 'pn-unsorted',
          description: t("Bei dieser Sortierung lässt sich die Zeile nicht anspringen."),
          action: {
            label: t("Nach Teilenummer sortieren"),
            onClick: () => {
              grid.current?.sortByPartNumber()
              window.setTimeout(() => void grid.current?.locate(detailPn), 400)
            },
          },
        })
      }
      // 'missing': der Detailbereich zeigt „Bauteil nicht gefunden“
    }
    const attempt = async (tries: number) => {
      const result = (await grid.current?.locate(detailPn)) ?? 'pending'
      if (cancelled) return
      if (result === 'pending' && tries > 0) window.setTimeout(() => void attempt(tries - 1), 300)
      else report(result)
    }
    // erst nach dem ersten Laden der Tabelle
    const locateTimer = window.setTimeout(() => void attempt(8), 120)
    return () => {
      cancelled = true
      window.clearTimeout(locateTimer)
    }
  }, [detailPn, resetQuery, t])

  // ------------------------------------------------------------------ Breite (kompakte Werkzeugleiste)
  useEffect(() => {
    const el = rootRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // Werkzeugleiste: Beschriftungen entfallen schrittweise, wenn es eng wird (die Suche schrumpft zuerst)
  const level: 0 | 1 | 2 = width >= 860 ? 0 : width >= 660 ? 1 : 2
  const compact = level === 2

  // ------------------------------------------------------------------ Auswahl
  const selectionCount = allMatching ? (total ?? selection.length) : selection.length
  const resolveRows = useCallback(
    async (rows: PartRow[]): Promise<PartRow[]> => (allMatching ? fetchMatchingRows(table, query.search, partFilters) : rows),
    [allMatching, table, query.search, partFilters],
  )
  const clearSelection = useCallback(() => {
    setAllMatching(false)
    grid.current?.deselectAll()
  }, [])

  /**
   * Löschen – `fromSelection`: die Mehrfachauswahl; bei „alle Treffer“ löscht das Backend alle Treffer von Suche und
   * Filtern (Anzahl wird vorher bestätigt), ohne dass die Zeilen erst geladen werden.
   */
  const handleDelete = useCallback(
    async (rows: PartRow[], fromSelection: boolean) => {
      const target: DeleteTarget = fromSelection && allMatching ? { search: query.search, filters: partFilters } : { rows }
      const deleted = await confirmAndDelete(qc, table, category.label, target)
      if (!deleted.length) return
      const gone = new Set(deleted.map((pn) => pn.toLowerCase()))
      if (detailPn && gone.has(detailPn.toLowerCase())) closeDetail()
      clearSelection()
    },
    [allMatching, query.search, partFilters, qc, table, category.label, detailPn, closeDetail, clearSelection],
  )
  /** Betroffene Bauteile der Massenbearbeitung (bei „alle Treffer“ die Abfrage selbst) */
  const bulkTarget: BulkTarget = allMatching
    ? { search: query.search, filters: partFilters, count: total ?? selection.length }
    : { partNumbers: selection.map((r) => String(r[PART_NUMBER] ?? '')).filter(Boolean) }

  const selectedPns = useMemo(() => new Set(selection.map((r) => String(r[PART_NUMBER] ?? ''))), [selection])
  const root = useWorkspace().data?.root
  const regenerate = async (row: PartRow) => {
    const pn = String(row[PART_NUMBER] ?? '')
    try {
      const res = await partsApi.regenerateTexts(table, [pn])
      invalidateParts(qc, table, { counts: false })
      if (res.updated) showChangeToast(qc, table, res, t("Texte aus den Vorlagen erzeugt"), pn)
      else toast.success(t("Texte entsprechen bereits den Vorlagen"), { description: pn })
    } catch (err) {
      toast.error(t("Texte konnten nicht erzeugt werden"), { description: errorMessage(err) })
    }
  }

  // ------------------------------------------------------------------ Export
  const exporter = useExport(table, category.label)
  const runExport = useCallback(
    (format: ExportFormat, opts: { onlySelection: boolean; visibleOnly: boolean }) =>
      exporter(
        {
          format,
          partNumbers: opts.onlySelection ? selection.map((r) => String(r[PART_NUMBER] ?? '')) : undefined,
          columns: opts.visibleOnly ? grid.current?.getVisibleColumns() : undefined,
          search: query.search,
          filters: partFilters,
          sort: grid.current?.getSort() ?? [],
        },
        // erwartete Zeilen: große Excel-Exporte laufen als Job (Fortschritt im Job-Dock)
        opts.onlySelection ? selection.length : total,
      ),
    [exporter, selection, query.search, partFilters, total],
  )

  // ------------------------------------------------------------------ Ansichten
  const snapshot = useCallback(
    () => ({
      search: query.search || null,
      filters: partFilters,
      sort: grid.current?.getSort() ?? [],
      columns: grid.current?.getVisibleColumns() ?? [],
    }),
    [query.search, partFilters],
  )
  const views = useSavedViews(table)
  const activeView: SavedView | null = (views.data ?? []).find((v) => v.id === query.viewId) ?? null
  // Spalten/Sortierung weichen von der Ansicht ab (gemeldet von der Tabelle, verglichen nach jeder Änderung)
  const [layoutDiffers, setLayoutDiffers] = useState(false)
  const compareLayout = useCallback(() => {
    const view = (views.data ?? []).find((v) => v.id === useBauteile.getState().queries[table]?.viewId)
    if (!view || !grid.current) {
      setLayoutDiffers(false)
      return
    }
    const known = new Set(category.fields.map((f) => f.column))
    const sortDiffers = sortKey(grid.current.getSort()) !== sortKey(view.sort)
    const viewColumns = view.columns.filter((c) => known.has(c))
    const columnsDiffer = viewColumns.length > 0 && grid.current.getVisibleColumns().join('|') !== viewColumns.join('|')
    setLayoutDiffers(sortDiffers || columnsDiffer)
  }, [views.data, table, category.fields, setLayoutDiffers])
  const viewModified = Boolean(
    activeView &&
      ((activeView.search ?? '') !== query.search.trim() || filterKey(activeView.filters) !== filterKey(partFilters) || layoutDiffers),
  )
  const applyView = (view: SavedView | null, opts: { silent?: boolean; keep?: boolean } = {}) => {
    if (!view) {
      if (opts.keep) {
        useBauteile.getState().setView(table, null)
        return
      }
      setQuery(table, { search: '', filters: [], viewId: null })
      grid.current?.resetColumns()
      setLayoutDiffers(false)
      if (!opts.silent) toast.success(t("Standardansicht"), { id: 'view-applied', description: t("Ohne Suche und Filter, Standardspalten"), duration: 1800 })
      return
    }
    setQuery(table, { search: view.search ?? '', filters: fromPartFilters(view.filters, category.fields), viewId: view.id })
    grid.current?.applyView(view.columns, view.sort)
    setLayoutDiffers(false)
    if (!opts.silent) toast.success(t("Ansicht „{1}“", { 1: view.name }), { id: 'view-applied', duration: 1800 })
  }

  // ------------------------------------------------------------------ Befehle (Strg+K) und Kürzel
  const focusSearch = () => {
    searchRef.current?.focus()
    searchRef.current?.select()
  }
  /** F6: zwischen Suche, Tabelle und Detailbereich wechseln */
  const cyclePane = (backwards: boolean) => {
    const detail = rootRef.current?.querySelector<HTMLElement>('[data-pf-pane="detail"]') ?? null
    const active = document.activeElement
    const inSearch = active === searchRef.current
    const inGrid = grid.current?.hasFocus() ?? false
    const inDetail = Boolean(detail && active && detail.contains(active))
    const panes: (() => void)[] = [focusSearch, () => grid.current?.focus()]
    if (detail) panes.push(() => detail.focus())
    const current = inSearch ? 0 : inGrid ? 1 : inDetail ? 2 : -1
    const next = current < 0 ? (backwards ? panes.length - 1 : 1) : (current + (backwards ? -1 : 1) + panes.length) % panes.length
    panes[next]()
  }
  useHotkey('f6', () => cyclePane(false), { allowInInputs: true })
  useHotkey('shift+f6', () => cyclePane(true), { allowInInputs: true })

  useRegisterCommands([
    {
      id: 'parts.search',
      title: t("{1} durchsuchen", { 1: metadataLabel(category.label, t) }),
      group: 'Aktionen',
      icon: Search,
      hotkey: 'mod+f',
      priority: 70,
      keywords: ['suchen', 'filtern', 'finden'],
      run: ({ close }) => {
        close()
        window.setTimeout(focusSearch, 0)
      },
    },
    {
      id: 'parts.export',
      title: t("{1} als Excel exportieren", { 1: metadataLabel(category.label, t) }),
      subtitle: hasQuery ? t("Mit aktueller Suche und Filtern") : t("Alle Bauteile der Kategorie"),
      group: 'Aktionen',
      icon: Download,
      priority: 40,
      keywords: ['export', 'xlsx', 'excel', 'tabelle', 'herunterladen'],
      run: () => runExport('xlsx', { onlySelection: selection.length > 0 && !allMatching, visibleOnly: true }),
    },
    {
      id: 'parts.export.csv',
      title: t("{1} als CSV exportieren", { 1: metadataLabel(category.label, t) }),
      group: 'Aktionen',
      icon: Download,
      priority: 39,
      keywords: ['export', 'csv'],
      run: () => runExport('csv', { onlySelection: selection.length > 0 && !allMatching, visibleOnly: true }),
    },
    {
      id: 'parts.filter',
      title: t("Filter bearbeiten"),
      subtitle: metadataLabel(category.label, t),
      group: 'Aktionen',
      icon: ListFilter,
      priority: 35,
      keywords: ['filter', 'bedingung', t("größer"), 'kleiner'],
      run: ({ close }) => {
        close()
        window.setTimeout(() => setFilterOpen(true), 0)
      },
    },
    {
      id: 'parts.filter.clear',
      title: t("Suche und Filter zurücksetzen"),
      group: 'Aktionen',
      icon: FilterX,
      priority: 34,
      when: () => hasQuery,
      run: () => setQuery(table, { search: '', filters: [], viewId: null }),
    },
    {
      id: 'parts.bulk',
      title: t("Auswahl bearbeiten ({1})", { 1: selectionCount }),
      group: 'Aktionen',
      icon: PencilLine,
      priority: 33,
      when: () => selectionCount > 0,
      run: () => setBulkOpen(true),
    },
    {
      id: 'parts.delete',
      title: t("Auswahl löschen ({1})", { 1: selectionCount }),
      subtitle: t("Entf in der Tabelle"),
      group: 'Aktionen',
      icon: Trash2,
      priority: 32,
      when: () => selectionCount > 0,
      run: () => void handleDelete(selection, true),
    },
    {
      id: 'parts.columns.reset',
      title: t("Spalten zurücksetzen"),
      subtitle: metadataLabel(category.label, t),
      group: 'Darstellung',
      icon: Columns3,
      keywords: ['spalten', 'breite', 'standard'],
      run: () => grid.current?.resetColumns(),
    },
    {
      id: 'parts.sort.pn',
      title: t("Nach Teilenummer sortieren"),
      subtitle: metadataLabel(category.label, t),
      group: 'Darstellung',
      icon: ArrowDownAZ,
      keywords: ['sortierung', 'standard'],
      run: () => grid.current?.sortByPartNumber(),
    },
    {
      id: 'parts.tree',
      title: tree.collapsed ? t("Kategoriebaum einblenden") : t("Kategoriebaum ausblenden"),
      group: 'Darstellung',
      icon: PanelLeft,
      run: () => tree.setCollapsed(!tree.collapsed),
    },
  ])

  // ------------------------------------------------------------------ Leere Zustände
  const emptyState = useMemo<GridEmptyState>(
    () => ({
      title: t("Noch keine {1}", { 1: metadataLabel(category.label, t) }),
      description: t("Einzeln anlegen, als komplette Serie erzeugen, aus einem Datenblatt lesen oder aus einer Tabelle übernehmen."),
      illustration: 'no-parts',
      actions: (
        <>
          <Button variant="secondary" size="sm" leftIcon={<Layers />} onClick={() => navigate('/serien')}>
            {t("Serien-Assistent")}
          </Button>
          <Button variant="spark" size="sm" leftIcon={<FileScan />} onClick={() => navigate('/import')}>
            {t("Aus Datenblatt")}
          </Button>
          <Button variant="secondary" size="sm" leftIcon={<Upload />} onClick={onImport}>
            {t("Tabelle importieren")}
          </Button>
          <Button variant="ghost" size="sm" leftIcon={<Plus />} onClick={onNewPart}>
            {t("Bauteil anlegen")}
          </Button>
        </>
      ),
    }),
    [category.label, navigate, onImport, onNewPart, t],
  )
  const noMatchState = useMemo<GridEmptyState>(
    () => ({
      title: t("Keine Treffer"),
      description: query.search.trim()
        ? t("Kein Bauteil in „{1}“ passt zu „{2}“{3}.", { 1: metadataLabel(category.label, t), 2: query.search.trim(), 3: partFilters.length ? t(" und den Filtern") : '' })
        : t("Kein Bauteil in „{1}“ erfüllt die Filter.", { 1: metadataLabel(category.label, t) }),
      illustration: 'search-empty',
      actions: (
        <Button variant="secondary" size="sm" leftIcon={<FilterX />} onClick={() => setQuery(table, { search: '', filters: [], viewId: null })}>
          {t("Suche und Filter zurücksetzen")}
        </Button>
      ),
    }),
    [category.label, query.search, partFilters.length, setQuery, table, t],
  )

  // ------------------------------------------------------------------ Darstellung
  const handleTotal = useCallback(
    (t: number | null) => {
      setTotal(t)
      onTotalChange?.(t)
    },
    [onTotalChange, t],
  )
  const handleLoadError = useCallback((err: unknown) => setLoadFailed(err !== null), [])
  const loadedAll = coversLoaded && total !== null && selection.length < total

  return (
    <div ref={rootRef} className={cn('flex h-full min-h-0 min-w-0 flex-col', tree.collapsed ? 'pl-2' : 'pl-4')}>
      <PartsToolbar
        label={metadataLabel(category.label, t)}
        search={query.search}
        onSearchChange={(s) => setSearch(table, s)}
        searchRef={searchRef}
        filter={
          <FilterBuilder
            category={category}
            filters={query.filters}
            onChange={(filters) => setFilters(table, filters)}
            open={filterOpen}
            onOpenChange={(o) => {
              setFilterOpen(o)
              if (!o) setFilterFocus(null)
            }}
            focusId={filterFocus}
            compact={compact}
          />
        }
        views={
          <ViewsMenu
            category={category}
            activeId={query.viewId}
            modified={viewModified}
            snapshot={snapshot}
            compact={compact}
            onApply={applyView}
          />
        }
        columns={
          <ColumnChooser category={category} grid={grid} compact={level >= 1} density={density} onDensityChange={setDensity} />
        }
        exportMenu={
          <ExportMenu total={total} selectionCount={selectionCount} allMatching={allMatching} onExport={runExport} compact={level >= 1} />
        }
        total={total}
        unfilteredTotal={category.part_count ?? null}
        loading={false}
        failed={loadFailed}
        onImport={onImport}
        treeCollapsed={tree.collapsed}
        onToggleTree={() => tree.setCollapsed(!tree.collapsed)}
        detailOpen={Boolean(detailPn)}
        onToggleDetail={() => {
          if (detailPn) {
            closeDetail()
            return
          }
          const row = grid.current?.getFocusedRow() ?? selection[0]
          if (row) openDetail(row)
          else
            toast.info(t("Zuerst eine Zeile wählen"), {
              description: t("Doppelklick auf eine Zeile, Klick auf die Teilenummer oder Enter öffnet die Details."),
              id: 'detail-hint',
            })
        }}
        canOpenDetail={(total ?? 0) > 0}
        level={level}
      />
      <div className="pt-2">
        <ActiveFilters
          category={category}
          filters={query.filters}
          onRemove={(id) => setFilters(table, query.filters.filter((f) => f.id !== id))}
          onClear={() => setFilters(table, [])}
          onEdit={(id) => {
            setFilterFocus(id)
            setFilterOpen(true)
          }}
        />
      </div>
      <DetailDock
        open={Boolean(detailPn)}
        width={detailWidth}
        onWidthChange={setDetailWidth}
        main={
          <>
            <RowContextMenu
              resolveRow={(el) => grid.current?.rowFromElement(el) ?? null}
              resolveCell={(el) => grid.current?.cellFromElement(el) ?? null}
              onEditCell={(row, column) => grid.current?.editCell(String(row[PART_NUMBER] ?? ''), column)}
              selectedPns={selectedPns}
              selectionCount={selectionCount}
              onOpen={openDetail}
              onDatasheet={(row) => {
                const link = String(row[DATASHEET] ?? '')
                void openDatasheet(link, root).then((ok) => {
                  if (!ok) toast.info(t("Datenblatt liegt als Datei vor"), { description: t("{1} – im Desktop-Programm öffnen.", { 1: link }) })
                })
              }}
              onDuplicate={async (rows) => setDuplicateRows(rows === 'selection' ? await resolveRows(selection) : rows)}
              onRegenerate={(row) => void regenerate(row)}
              onBulkEdit={() => setBulkOpen(true)}
              onDelete={(rows) => void (rows === 'selection' ? handleDelete(selection, true) : handleDelete(rows, false))}
            >
              <div className="flex min-h-0 flex-1 flex-col">
                <PartsGrid
                  key={table}
                  handleRef={grid}
                  category={category}
                  scheme={scheme}
                  search={query.search}
                  filters={partFilters}
                  density={density}
                  activePn={detailPn}
                  newPns={newPns}
                  selectAllMatching={allMatching}
                  emptyState={emptyState}
                  noMatchState={noMatchState}
                  onActivate={openDetail}
                  onFocusRow={(row) => {
                    // geöffnetes Detail folgt dem Tastaturfokus
                    if (params.get('pn') && row[PART_NUMBER] !== params.get('pn')) openDetail(row)
                  }}
                  onSelectionChange={(rows) => {
                    setSelection(rows)
                    setCoversLoaded(rows.length > 0 && rows.length === (grid.current?.loadedCount() ?? -1))
                  }}
                  onExitAllMatching={() => setAllMatching(false)}
                  onTotalChange={handleTotal}
                  onLoadError={handleLoadError}
                  onLayoutChange={compareLayout}
                  onDelete={(rows) => void handleDelete(rows, selection.length > 0)}
                  onRowSaved={(row, previousPn) => {
                    qc.setQueryData(partsKeys.detail(table, String(row[PART_NUMBER] ?? previousPn)), row)
                    void qc.invalidateQueries({ queryKey: partsKeys.history(table, previousPn) })
                  }}
                  onEscape={() => {
                    if (detailPn) closeDetail()
                    else if (selection.length) clearSelection()
                  }}
                  className="min-h-0 flex-1"
                />
              </div>
            </RowContextMenu>
            <BulkBar
              count={selection.length}
              total={total}
              allMatching={allMatching}
              canSelectAllMatching={loadedAll}
              onSelectAllMatching={() => {
                setAllMatching(true)
                grid.current?.selectAllLoaded()
              }}
              onEdit={() => setBulkOpen(true)}
              onDuplicate={async () => setDuplicateRows(await resolveRows(selection))}
              onExport={() => runExport('xlsx', { onlySelection: !allMatching, visibleOnly: true })}
              onDelete={() => void handleDelete(selection, true)}
              onClear={clearSelection}
              compact={width - (detailPn ? detailWidth : 0) < 780}
            />
          </>
        }
        panel={
          detailPn ? (
            <PartDetailPanel
              key={detailPn}
              category={category}
              pn={detailPn}
              initialRow={rowCache && rowCache[PART_NUMBER] === detailPn ? rowCache : null}
              focusRequest={focusField && focusField.pn === detailPn ? focusField : null}
              onClose={closeDetail}
              onSaved={(row, previousPn) => {
                const pn = String(row[PART_NUMBER] ?? previousPn)
                grid.current?.refresh()
                if (pn !== previousPn) openDetail(row)
              }}
              onDuplicate={(row) => setDuplicateRows([row])}
              onDelete={(row) => void handleDelete([row], false)}
            />
          ) : null
        }
      />
      <BulkUpdateDialog
        open={bulkOpen}
        onOpenChange={setBulkOpen}
        category={category}
        target={bulkTarget}
        sample={selection[0] ?? null}
        onDone={() => grid.current?.refresh()}
      />
      <DuplicateDialog
        open={duplicateRows !== null}
        onOpenChange={(o) => !o && setDuplicateRows(null)}
        category={category}
        rows={duplicateRows ?? []}
        scheme={scheme}
        onDone={(created) => {
          onNewPns(created)
          clearSelection()
          if (created[0]) {
            internalPn.current = null
            setParams(
              (p) => {
                const next = new URLSearchParams(p)
                next.set('pn', created[0])
                return next
              },
              { replace: true },
            )
          }
        }}
      />
    </div>
  )
}
