import { metadataLabel, localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Bauteile (`/bauteile`, `/bauteile/:table`): links der Kategoriebaum, rechts die Tabelle der Kategorie mit
 * Werkzeugleiste und Detailbereich – oder „Alle Kategorien“ (Übersicht + Suche über die ganze Bibliothek).
 * „Neues Bauteil“ (Strg+N, `?neu=1`), Tabellen-Import und die Bauteil-Schnellsuche (Strg+K) hängen hier.
 * Tabellen-Seite: kein großer Seitenkopf – Titel, Trefferzahl und die eine Primäraktion stehen in der Topbar.
 *
 * Router-State `{ partsUpload: { token, fileName, rows, label? } }` (z. B. „Bauteile anlegen …“ des
 * Bibliotheksimports) öffnet den Tabellen-Import mit dieser vorbereiteten Tabelle – einmal: der State wird danach
 * gelöscht (Neuladen und Zurück öffnen ihn nicht erneut).
 */
import { useQueryClient } from '@tanstack/react-query'
import { FileScan, FolderTree, Microchip, Plus, Settings2, Upload } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router'
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
import { ImportWizard, type ImportWizardUpload } from './import/ImportWizard'
import { NewPartDialog } from './dialogs/NewPartDialog'
import { useBauteile, useTreeVisibility } from './model/store'
import { AllCategoriesView } from './overview/AllCategoriesView'

const EMPTY_PNS: ReadonlySet<string> = new Set()

/** Vorbereitete Tabelle aus dem Router-State (`{ partsUpload: … }`) – geprüft, sonst `null` */
function partsUploadFromState(state: unknown): ImportWizardUpload | null {
  if (!state || typeof state !== 'object') return null
  const raw = (state as { partsUpload?: unknown }).partsUpload
  if (!raw || typeof raw !== 'object') return null
  const { token, fileName, rows, label } = raw as Record<string, unknown>
  if (typeof token !== 'string' || !/^[A-Za-z0-9_-]{8,128}$/.test(token)) return null
  if (typeof fileName !== 'string' || !fileName.trim()) return null
  if (typeof rows !== 'number' || !Number.isFinite(rows) || rows < 0) return null
  return {
    token,
    fileName: fileName.trim(),
    rows: Math.round(rows),
    label: typeof label === 'string' && label.trim() ? label.trim() : undefined,
  }
}

export default function BauteilePage() {
  const { t } = useI18n()
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
  // „neu“-Markierungen samt der Kategorie, für die sie gelten (ein Bauteil, das aus der Übersicht oder einer anderen
  // Kategorie heraus angelegt wird, trägt sie nach dem Wechsel in seine Kategorie)
  const [newPns, setNewPns] = useState<{ table?: string; pns: ReadonlySet<string> }>(() => ({ pns: new Set() }))

  // Vorbereitete Tabelle (Router-State, z. B. vom Bibliotheksimport): den Tabellen-Import damit öffnen – je Navigation
  // einmal; danach den State löschen, damit Neuladen und Zurück ihn nicht erneut öffnen
  const location = useLocation()
  const incomingUpload = partsUploadFromState(location.state)
  const [preparedUpload, setPreparedUpload] = useState<ImportWizardUpload | null>(null)
  const [uploadFrom, setUploadFrom] = useState<string | null>(null)
  if (incomingUpload && uploadFrom !== location.key) {
    setUploadFrom(location.key)
    setPreparedUpload(incomingUpload)
    setImportOpen(true)
  }
  const hasIncomingUpload = incomingUpload !== null
  useEffect(() => {
    if (hasIncomingUpload) navigate(`${location.pathname}${location.search}`, { replace: true, state: null })
  }, [hasIncomingUpload, location.pathname, location.search, navigate])
  const setImportDialogOpen = (open: boolean) => {
    setImportOpen(open)
    if (!open) setPreparedUpload(null)
  }
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
  // „neu“-Markierungen gelten je Kategorie (abgeleiteter Zustand): in einer anderen Kategorie verfallen sie
  if (newPns.table !== undefined && category?.table !== newPns.table) setNewPns({ pns: new Set() })

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
    setNewPns((s) => ({ table, pns: new Set(s.table === table ? [...s.pns, pn] : [pn]) }))
    toast.success(t("„{1}“ angelegt", { 1: pn }), {
      description: result.part.Description ?? undefined,
      action: { label: t("Weiteres anlegen"), onClick: () => setNewOpen(true) },
    })
    if (result.warnings.length) toast.warning(t("Bitte prüfen"), { description: result.warnings.map(localizeMessage).join(' · ') })
    openPart(table, pn)
  }

  const onImported = (table: string, result: ImportResult) => {
    invalidateParts(qc, table)
    if (result.created_part_numbers.length) setNewPns({ table, pns: new Set(result.created_part_numbers.slice(0, 500)) })
    if (!category || category.table !== table) navigate(`/bauteile/${encodeURIComponent(table)}`)
  }

  // Strg+S: Bauteile speichert PartForge sofort – hier nur der Hinweis. Offene Eingaben (Zelleneditor, Detailbereich,
  // Dialog „Neues Bauteil“) registrieren eigene Handler und haben Vorrang (später eingehängt bzw. modal).
  useSaveHandler(() => {
    toast.info(t("Nichts zu speichern"), {
      id: 'parts-save-hint',
      description: t("Änderungen in der Tabelle und im Detailbereich speichert PartForge sofort beim Verlassen des Felds."),
    })
  })

  // ------------------------------------------------------------------ Befehle und Schnellsuche
  useRegisterCommands([
    {
      id: 'parts.new',
      title: t("Neues Bauteil"),
      subtitle: category ? t("In „{1}“ – mit Smart-Eingabe", { 1: metadataLabel(category.label, t) }) : t("Geführte Anlage mit Smart-Eingabe"),
      group: 'Aktionen',
      icon: Plus,
      hotkey: 'mod+n',
      priority: 100,
      keywords: ['anlegen', 'erstellen', 'part', t("neu")],
      run: ({ close }) => {
        close()
        setNewOpen(true)
      },
    },
    {
      id: 'parts.import',
      title: t("Tabelle importieren"),
      subtitle: t("CSV, Excel oder ODS – Spalten werden automatisch zugeordnet"),
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
        meta: metadataLabel(h.label, t),
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
        .filter((c) => `${metadataLabel(c.label, t)} ${c.label} ${c.table}`.toLowerCase().includes(needle))
        .slice(0, 5)
        .map((c) => ({
          id: `kategorie:${c.table}`,
          title: metadataLabel(c.label, t),
          mono: false,
          subtitle: plural(c.part_count ?? 0, t("Bauteil"), t("Bauteile")),
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
    ? [CATEGORY_GROUPS[category.table] && t(CATEGORY_GROUPS[category.table]), category.prefix ? t("Bezeichner {1}", { 1: category.prefix }) : null].filter(Boolean).join(' · ') ||
      plural(category.part_count ?? 0, t("Bauteil"), t("Bauteile"))
    : categories.data
      ? t("{1} in {2}", { 1: plural(sum, t("Bauteil"), t("Bauteile")), 2: plural(categories.data.length, t("Kategorie"), t("Kategorien")) })
      : undefined
  const unknown = Boolean(tableParam && categories.isSuccess && !category)

  return (
    <PageBody width="full" flush className="flex h-[calc(100dvh-3.5rem)] min-h-[600px] flex-col">
      <PageTitle title={category ? metadataLabel(category.label, t) : (tableParam ? tableParam : t("Bauteile"))} subtitle={subtitle} />
      <PageActions>
        <Button variant="spark" leftIcon={<FileScan />} onClick={() => navigate('/import')}>
          {t("Aus Datenblatt")}
        </Button>
        <Button variant="primary" leftIcon={<Plus />} onClick={() => setNewOpen(true)} aria-keyshortcuts="Control+N">
          {t("Neues Bauteil")}
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
          label={t("Breite des Kategoriebaums")}
          className="min-h-0 flex-1"
          start={
            <nav aria-label={t("Kategorien")} className="flex h-full min-h-0 flex-col pr-3">
              <div className="flex h-9 shrink-0 items-center justify-between pl-1">
                <span className="micro-label">{t("Kategorien")}</span>
                <IconButton
                  size="sm"
                  label={t("Kategorien und Felder verwalten")}
                  icon={<Settings2 />}
                  onClick={() => navigate('/einstellungen/kategorien')}
                />
              </div>
              <CategoryTree
                items={tree.items}
                value={category?.table ?? (tableParam ? null : '')}
                onValueChange={(id) => navigate(id ? `/bauteile/${encodeURIComponent(id)}` : '/bauteile')}
                allItem={{ label: t("Alle Kategorien"), count: tree.total }}
                groupOrder={CATEGORY_GROUP_ORDER}
                loading={tree.isLoading}
                persistKey="bauteile"
                searchable={tree.items.length > 12}
                searchPlaceholder={t("Kategorie filtern …")}
                className="mt-1 min-h-0 flex-1"
                aria-label={t("Kategorien")}
              />
            </nav>
          }
          end={
            category ? (
              <CategoryWorkspace
                key={category.table}
                category={category}
                newPns={newPns.table === category.table ? newPns.pns : EMPTY_PNS}
                onNewPns={(pns) => setNewPns((s) => ({ table: category.table, pns: new Set([...(s.table === category.table ? s.pns : []), ...pns]) }))}
                onNewPart={() => setNewOpen(true)}
                onImport={() => setImportOpen(true)}
              />
            ) : unknown ? (
              <div className="flex h-full items-center justify-center pl-4">
                <EmptyState
                  titleAs="h2"
                  illustration="search-empty"
                  title={t("Kategorie „{1}“ gibt es nicht", { 1: tableParam ?? '' })}
                  description={t("Vielleicht wurde sie umbenannt oder gelöscht. Wählen Sie links eine Kategorie.")}
                  actions={
                    <Button variant="secondary" onClick={() => navigate('/bauteile')}>
                      {t("Alle Kategorien")}
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
      <ImportWizard
        open={importOpen}
        onOpenChange={setImportDialogOpen}
        defaultTable={defaultTable}
        onImported={onImported}
        initialUpload={preparedUpload}
      />
    </PageBody>
  )
}
