/**
 * Bauteile (`/bauteile`, `/bauteile/:table`): links der Kategoriebaum, rechts die Tabelle der Kategorie mit
 * Werkzeugleiste und Detailbereich – oder „Alle Kategorien“ (Übersicht + Suche über die ganze Bibliothek).
 * „Neues Bauteil“ (Strg+N, `?neu=1`), Tabellen-Import und die Bauteil-Schnellsuche (Strg+K) hängen hier.
 * Tabellen-Seite: kein großer Seitenkopf – Titel, Trefferzahl und die eine Primäraktion stehen in der Topbar.
 */
import { useQueryClient } from '@tanstack/react-query'
import { FileScan, FolderTree, Microchip, Plus, Settings2, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { toast } from 'sonner'
import { useRegisterCommands, useRegisterSearchProvider, useSaveHandler } from '@/app/commands'
import { PageActions, PageBody, PageTitle } from '@/app/page'
import { libraryApi, useCategories } from '@/api/library'
import { invalidateParts, PART_NUMBER, type ImportResult, type PartWriteOut } from '@/api/parts'
import { useWorkspace } from '@/api/system'
import { CATEGORY_GROUP_ORDER, CategoryTree, SplitPane, useCategoryTreeItems } from '@/components/data'
import { CATEGORY_GROUPS } from '@/components/data/categoryTreeItems'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { Button, EmptyState, IconButton } from '@/components/ui'
import { plural } from '@/lib/format'
import { CategoryWorkspace } from './CategoryWorkspace'
import { ImportWizard } from './import/ImportWizard'
import { NewPartDialog } from './dialogs/NewPartDialog'
import { useBauteile, useTreeVisibility } from './model/store'
import { AllCategoriesView } from './overview/AllCategoriesView'

export default function BauteilePage() {
  const { table: tableParam } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const categories = useCategories()
  const tree = useCategoryTreeItems()
  const lastTable = useBauteile((s) => s.lastTable)
  const setLastTable = useBauteile((s) => s.setLastTable)

  const category = useMemo(
    () => (tableParam ? (categories.data?.find((c) => c.table.toLowerCase() === tableParam.toLowerCase()) ?? null) : null),
    [categories.data, tableParam],
  )
  const [newOpen, setNewOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [newPns, setNewPns] = useState<ReadonlySet<string>>(() => new Set())
  const [globalSearch, setGlobalSearch] = useState(() => params.get('suche') ?? '')
  // /bauteile?suche=… (z. B. „In allen Kategorien suchen“ aus dem Detailbereich) übernimmt die Suche
  const searchParam = params.get('suche')
  const [seenSearchParam, setSeenSearchParam] = useState(searchParam)
  if (searchParam !== seenSearchParam) {
    setSeenSearchParam(searchParam)
    if (searchParam !== null) setGlobalSearch(searchParam)
  }

  // Kategoriebaum: bei geöffnetem Detailbereich automatisch eingeklappt (mehr Platz für die Tabelle)
  const detailOpen = Boolean(category && params.get('pn'))
  const treeVisibility = useTreeVisibility(detailOpen)
  useEffect(() => {
    if (!detailOpen) useBauteile.getState().setTreeShownWithDetail(false)
  }, [detailOpen])

  // Bibliothek gewechselt → Suche und Filter der alten Bibliothek verwerfen
  const root = useWorkspace().data?.root ?? null
  useEffect(() => {
    useBauteile.getState().syncWorkspace(root)
  }, [root])

  // Kategorie merken (Vorauswahl „Neues Bauteil“ auf der Übersicht)
  useEffect(() => {
    if (category) setLastTable(category.table)
  }, [category, setLastTable])
  // „neu“-Markierungen gelten je Kategorie (abgeleiteter Zustand)
  const [shownTable, setShownTable] = useState(category?.table)
  if (category?.table !== shownTable) {
    setShownTable(category?.table)
    setNewPns(new Set())
  }

  // /bauteile?neu=1 (Befehl der Shell, Übersicht) öffnet den Dialog; beim Schließen verschwindet der Parameter
  const neu = params.get('neu') === '1'
  const dialogOpen = newOpen || neu
  const setDialogOpen = (open: boolean) => {
    setNewOpen(open)
    if (!open && neu) {
      setParams(
        (p) => {
          const next = new URLSearchParams(p)
          next.delete('neu')
          return next
        },
        { replace: true },
      )
    }
  }

  // Ohne bekannte Kategorie fragt der Dialog (Schnellwahl, Erkennung über die Hersteller-Teilenummer)
  const defaultTable = category?.table ?? lastTable ?? null
  const openPart = useCallback(
    (table: string, pn: string) => navigate(`/bauteile/${encodeURIComponent(table)}?pn=${encodeURIComponent(pn)}`),
    [navigate],
  )

  const onCreated = (table: string, result: PartWriteOut) => {
    const pn = String(result.part[PART_NUMBER] ?? '')
    invalidateParts(qc, table)
    setNewPns((s) => new Set(s).add(pn))
    toast.success(`„${pn}“ angelegt`, {
      description: result.part.Description ?? undefined,
      action: { label: 'Weiteres anlegen', onClick: () => setNewOpen(true) },
    })
    if (result.warnings.length) toast.warning('Bitte prüfen', { description: result.warnings.join(' · ') })
    openPart(table, pn)
  }

  const onImported = (table: string, result: ImportResult) => {
    invalidateParts(qc, table)
    if (result.created_part_numbers.length) setNewPns(new Set(result.created_part_numbers.slice(0, 500)))
    if (!category || category.table !== table) navigate(`/bauteile/${encodeURIComponent(table)}`)
  }

  // Strg+S: Bauteile speichert PartForge sofort – hier nur der Hinweis. Offene Eingaben (Zelleneditor, Detailbereich,
  // Dialog „Neues Bauteil“) registrieren eigene Handler und haben Vorrang (später eingehängt bzw. modal).
  useSaveHandler(() => {
    toast.info('Nichts zu speichern', {
      id: 'parts-save-hint',
      description: 'Änderungen in der Tabelle und im Detailbereich speichert PartForge sofort beim Verlassen des Felds.',
    })
  })

  // ------------------------------------------------------------------ Befehle und Schnellsuche
  useRegisterCommands([
    {
      id: 'parts.new',
      title: 'Neues Bauteil',
      subtitle: category ? `In „${category.label}“ – mit Smart-Eingabe` : 'Geführte Anlage mit Smart-Eingabe',
      group: 'Aktionen',
      icon: Plus,
      hotkey: 'mod+n',
      priority: 100,
      keywords: ['anlegen', 'erstellen', 'part', 'neu'],
      run: ({ close }) => {
        close()
        setNewOpen(true)
      },
    },
    {
      id: 'parts.import',
      title: 'Tabelle importieren',
      subtitle: 'CSV, Excel oder ODS – Spalten werden automatisch zugeordnet',
      group: 'Aktionen',
      icon: Upload,
      priority: 75,
      keywords: ['import', 'csv', 'xlsx', 'excel', 'tabelle', 'einlesen'],
      run: ({ close }) => {
        close()
        setImportOpen(true)
      },
    },
  ])

  useRegisterSearchProvider({
    id: 'parts',
    group: 'Bauteile',
    minQueryLength: 2,
    search: async (q, signal) => {
      const hits = await libraryApi.search(q, 10, signal)
      return hits.map((h) => ({
        id: `${h.table}:${h.part_number}`,
        title: h.part_number,
        subtitle: [h.value ? formatQuantityText(h.value) : null, h.description].filter(Boolean).join(' · ') || undefined,
        meta: h.label,
        color: h.color,
        icon: Microchip,
        run: ({ navigate: go, close }) => {
          close()
          go(`/bauteile/${encodeURIComponent(h.table)}?pn=${encodeURIComponent(h.part_number)}`)
        },
      }))
    },
  })
  useRegisterSearchProvider({
    id: 'bauteile.kategorien',
    group: 'Kategorien',
    minQueryLength: 1,
    search: async (q) => {
      const needle = q.trim().toLowerCase()
      return (categories.data ?? [])
        .filter((c) => `${c.label} ${c.table}`.toLowerCase().includes(needle))
        .slice(0, 5)
        .map((c) => ({
          id: `kategorie:${c.table}`,
          title: c.label,
          mono: false,
          subtitle: plural(c.part_count ?? 0, 'Bauteil', 'Bauteile'),
          meta: c.table,
          color: c.color,
          icon: FolderTree,
          run: ({ navigate: go, close }) => {
            close()
            go(`/bauteile/${encodeURIComponent(c.table)}`)
          },
        }))
    },
  })

  // ------------------------------------------------------------------ Titel
  const sum = (categories.data ?? []).reduce((s, c) => s + (c.part_count ?? 0), 0)
  // Die Trefferzahl steht in der Werkzeugleiste – der Untertitel ordnet die Kategorie ein
  const subtitle = category
    ? [CATEGORY_GROUPS[category.table], category.prefix ? `Bezeichner ${category.prefix}` : null].filter(Boolean).join(' · ') ||
      plural(category.part_count ?? 0, 'Bauteil', 'Bauteile')
    : categories.data
      ? `${plural(sum, 'Bauteil', 'Bauteile')} in ${plural(categories.data.length, 'Kategorie', 'Kategorien')}`
      : undefined
  const unknown = Boolean(tableParam && categories.isSuccess && !category)

  return (
    <PageBody width="full" flush className="flex h-[calc(100dvh-3.5rem)] min-h-[600px] flex-col">
      <PageTitle title={category?.label ?? (tableParam ? tableParam : 'Bauteile')} subtitle={subtitle} />
      <PageActions>
        <Button variant="spark" leftIcon={<FileScan />} onClick={() => navigate('/import')}>
          Aus Datenblatt
        </Button>
        <Button variant="primary" leftIcon={<Plus />} onClick={() => setNewOpen(true)} aria-keyshortcuts="Control+N">
          Neues Bauteil
        </Button>
      </PageActions>

      <div className="flex min-h-0 flex-1 px-6 pb-5 pt-1">
        <SplitPane
          persistKey="bauteile.baum"
          primary="start"
          defaultSize={248}
          minSize={200}
          maxSize={380}
          minRest={560}
          collapsible
          collapsed={treeVisibility.collapsed}
          onCollapsedChange={treeVisibility.setCollapsed}
          label="Breite des Kategoriebaums"
          className="min-h-0 flex-1"
          start={
            <nav aria-label="Kategorien" className="flex h-full min-h-0 flex-col pr-3">
              <div className="flex h-9 shrink-0 items-center justify-between pl-1">
                <span className="micro-label">Kategorien</span>
                <IconButton
                  size="sm"
                  label="Kategorien und Felder verwalten"
                  icon={<Settings2 />}
                  onClick={() => navigate('/einstellungen/kategorien')}
                />
              </div>
              <CategoryTree
                items={tree.items}
                value={category?.table ?? (tableParam ? null : '')}
                onValueChange={(id) => navigate(id ? `/bauteile/${encodeURIComponent(id)}` : '/bauteile')}
                allItem={{ label: 'Alle Kategorien', count: tree.total }}
                groupOrder={CATEGORY_GROUP_ORDER}
                loading={tree.isLoading}
                persistKey="bauteile"
                searchable={tree.items.length > 12}
                searchPlaceholder="Kategorie filtern …"
                className="mt-1 min-h-0 flex-1"
                aria-label="Kategorien"
              />
            </nav>
          }
          end={
            category ? (
              <CategoryWorkspace
                key={category.table}
                category={category}
                newPns={newPns}
                onNewPns={(pns) => setNewPns((s) => new Set([...s, ...pns]))}
                onNewPart={() => setNewOpen(true)}
                onImport={() => setImportOpen(true)}
              />
            ) : unknown ? (
              <div className="flex h-full items-center justify-center pl-4">
                <EmptyState
                  titleAs="h2"
                  illustration="search-empty"
                  title={`Kategorie „${tableParam}“ gibt es nicht`}
                  description="Vielleicht wurde sie umbenannt oder gelöscht. Wählen Sie links eine Kategorie."
                  actions={
                    <Button variant="secondary" onClick={() => navigate('/bauteile')}>
                      Alle Kategorien
                    </Button>
                  }
                />
              </div>
            ) : (
              <AllCategoriesView
                search={globalSearch}
                onSearchChange={setGlobalSearch}
                onNewPart={() => setNewOpen(true)}
                onImport={() => setImportOpen(true)}
              />
            )
          }
        />
      </div>

      <NewPartDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        defaultTable={defaultTable}
        onCreated={onCreated}
        onOpenExisting={openPart}
      />
      <ImportWizard open={importOpen} onOpenChange={setImportOpen} defaultTable={defaultTable} onImported={onImported} />
    </PageBody>
  )
}
