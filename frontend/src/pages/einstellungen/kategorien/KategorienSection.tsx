import { t as translate, useI18n } from '@/lib/i18n'
/**
 * Kategorien und Felder – der Schema-Designer. Links die Kategorien, rechts die gewählte Kategorie mit den Reitern
 * Felder (sofort gespeichert, mit Rückgängig), Texte (Vorlagen mit Live-Vorschau) und Eigenschaften.
 * Auswahl und Reiter stehen in der Adresse (`?k=Resistors&ansicht=texte`).
 */
import { ArrowUpRight, ListTree, Plus, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams, type Location } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { useCategories } from '@/api/library'
import { useFieldKinds, useUpdateCategory, type CategoryDef, type FieldKindInfo } from '@/api/settings'
import { useWorkspace } from '@/api/system'
import { Badge, Button, Card, EmptyState, Select, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { formatNumber } from '@/lib/format'
import { NoWorkspace } from '../components'
import { useDraft } from '../draft'
import { UnsavedChanges } from '../UnsavedChanges'
import { CategoryList } from './CategoryList'
import { draftErrors, draftPatch, toDraft, type CategoryDraft } from './categoryDraft'
import { FieldsPanel } from './FieldsPanel'
import { NewCategoryDialog } from './NewCategoryDialog'
import { CategoryTile } from './pickers'
import { PropertiesPanel } from './PropertiesPanel'
import { TemplatesPanel } from './TemplatesPanel'

type Tab = 'felder' | 'texte' | 'eigenschaften'
const TABS: Tab[] = ['felder', 'texte', 'eigenschaften']

/** Rückfrage nur bei anderem Bereich oder anderer Kategorie – nicht beim Reiterwechsel */
const leavesCategory = (a: Location, b: Location) =>
  a.pathname !== b.pathname || new URLSearchParams(a.search).get('k') !== new URLSearchParams(b.search).get('k')

function DesignerSkeleton() {
  useI18n()
  return (
    <div className="grid grid-cols-1 gap-5 @[58rem]:grid-cols-[15rem_minmax(0,1fr)]" aria-busy="true" aria-label={translate("Kategorien werden geladen")}>
      <Skeleton className="hidden h-[32rem] rounded-card @[58rem]:block" />
      <Skeleton className="h-[32rem] rounded-card" />
    </div>
  )
}

export default function KategorienSection() {
  useI18n()
  const workspace = useWorkspace()
  if (workspace.isPending) return <DesignerSkeleton />
  if (!workspace.data) return <NoWorkspace what={translate("Kategorien und Felder")} />
  // Abfragen erst mit geöffneter Bibliothek (sonst 409 und ein überflüssiger Hinweis)
  return <SchemaDesigner root={workspace.data.root} />
}

function SchemaDesigner({ root }: { root: string }) {
  useI18n()
  const categories = useCategories()
  const kinds = useFieldKinds()
  const [params, setParams] = useSearchParams()
  const [creating, setCreating] = useState(false)
  const [dirtyTable, setDirtyTable] = useState<string | null>(null)
  const [renamed, setRenamed] = useState<{ from: string; to: string } | null>(null)

  const list = categories.data ?? []
  let k = params.get('k')
  if (k && renamed && k.toLowerCase() === renamed.from.toLowerCase()) k = renamed.to
  const selected = (k ? list.find((c) => c.table.toLowerCase() === k.toLowerCase()) : null) ?? list[0] ?? null
  const rawTab = params.get('ansicht') as Tab | null
  const tab: Tab = rawTab && TABS.includes(rawTab) ? rawTab : 'felder'

  const select = (table: string) =>
    setParams((p) => {
      const next = new URLSearchParams(p)
      next.set('k', table)
      return next
    })
  const setTab = (t: string) =>
    setParams(
      (p) => {
        const next = new URLSearchParams(p)
        if (t === 'felder') next.delete('ansicht')
        else next.set('ansicht', t)
        return next
      },
      { replace: true },
    )

  if (categories.isPending) return <DesignerSkeleton />
  if (categories.isError) {
    return (
      <Card>
        <EmptyState
          illustration="offline"
          titleAs="h2"
          title={translate("Kategorien konnten nicht geladen werden")}
          description={errorMessage(categories.error)}
          actions={<Button onClick={() => void categories.refetch()}>{translate("Erneut versuchen")}</Button>}
        />
      </Card>
    )
  }

  return (
    // Zweispaltig (Liste + Editor) erst ab 58 rem – darunter wählt eine Auswahlliste die Kategorie
    <div className="grid grid-cols-1 items-start gap-5 @[58rem]:grid-cols-[15rem_minmax(0,1fr)]">
      <Card className="sticky top-[4.5rem] hidden max-h-[calc(100dvh-6.5rem)] flex-col overflow-hidden @[58rem]:flex">
        <CategoryList
          categories={list}
          loading={false}
          selected={selected?.table ?? null}
          dirtyTable={dirtyTable}
          onSelect={select}
          onCreate={() => setCreating(true)}
          className="min-h-0 flex-1"
        />
      </Card>

      {/* Schmal: Kategorie als Auswahlliste */}
      <div className="flex items-center gap-2 @[58rem]:hidden">
        <Select
          aria-label={translate("Kategorie")}
          value={selected?.table}
          onValueChange={select}
          options={list.map((c) => ({
            value: c.table,
            label: c.label,
            description: translate("{value1} · {value2} Bauteile", { value1: c.table, value2: formatNumber(c.part_count ?? 0) }),
            icon: <CategoryTile icon={c.icon} color={c.color} size="sm" className="size-5 rounded-md [&_svg]:size-3" />,
          }))}
          className="flex-1"
        />
        <Button variant="secondary" leftIcon={<Plus />} onClick={() => setCreating(true)}>
          {translate("Neue Kategorie")}</Button>
      </div>

      {selected ? (
        <CategoryEditor
          key={selected.table}
          root={root}
          category={selected}
          all={list}
          kinds={kinds.data ?? []}
          tab={tab}
          onTab={setTab}
          onDirtyChange={setDirtyTable}
          onRenamed={(to) => {
            setRenamed({ from: selected.table, to })
            window.setTimeout(() => select(to), 0)
          }}
          onDeleted={() => {
            const next = list.find((c) => c.table !== selected.table)
            if (next) window.setTimeout(() => select(next.table), 0)
          }}
        />
      ) : (
        <Card>
          <EmptyState
            illustration="forge"
            titleAs="h2"
            title={translate("Noch keine Kategorien")}
            description={translate("Kategorien sind die Tabellen Ihrer Bibliothek – je Bauteilart eine, in Altium je eine Bibliothek.")}
            actions={
              <Button variant="secondary" leftIcon={<Plus />} onClick={() => setCreating(true)}>
                {translate("Erste Kategorie anlegen")}</Button>
            }
          />
        </Card>
      )}

      <NewCategoryDialog open={creating} onOpenChange={setCreating} categories={list} onCreated={(table) => select(table)} />
    </div>
  )
}

// --------------------------------------------------------------------------- Editor

function CategoryEditor({
  root,
  category,
  all,
  kinds,
  tab,
  onTab,
  onDirtyChange,
  onRenamed,
  onDeleted,
}: {
  /** Bibliothek, zu der der Entwurf gehört */
  root: string
  category: CategoryDef
  all: CategoryDef[]
  kinds: FieldKindInfo[]
  tab: Tab
  onTab: (tab: string) => void
  onDirtyChange: (table: string | null) => void
  onRenamed: (table: string) => void
  onDeleted: () => void
}) {
  useI18n()
  const saved = toDraft(category)
  const { draft, setDraft, dirty, reset, commit } = useDraft<CategoryDraft>(saved)
  const update = useUpdateCategory()
  const errors = draftErrors(draft, category, all)
  const firstError = Object.values(errors).find(Boolean) ?? null

  useEffect(() => {
    onDirtyChange(dirty ? category.table : null)
    return () => onDirtyChange(null)
  }, [dirty, category.table, onDirtyChange])

  const change = (patch: Partial<CategoryDraft>) => setDraft((d) => ({ ...d, ...patch }))

  const save = async (): Promise<boolean> => {
    if (firstError) return false
    const patch = draftPatch(saved, draft)
    if (Object.keys(patch).length === 0) {
      reset()
      return true
    }
    try {
      const cat = await update.mutateAsync({ table: category.table, patch, root })
      commit(toDraft(cat))
      toast.success(translate("„{value1}“ gespeichert", { value1: cat.label }), {
        description: patch.table ? translate("Tabelle heißt jetzt {value1}.", { value1: cat.table }) : undefined,
      })
      if (patch.table) onRenamed(cat.table)
      return true
    } catch {
      return false
    }
  }

  const parts = category.part_count ?? 0
  const ownFields = category.fields.filter((f) => !f.common).length
  const textErrors = Boolean(errors.comment_template || errors.description_template || errors.value_field)
  const propErrors = Boolean(errors.label || errors.prefix || errors.color || errors.table)

  return (
    <div className="flex min-w-0 flex-col">
      <Card className="overflow-hidden">
        <div className="flex items-start gap-4 px-5 pb-4 pt-5">
          <CategoryTile icon={draft.icon} color={draft.color} size="lg" />
          <div className="min-w-0 flex-1">
            <h2 className="line-clamp-2 text-h3 font-semibold tracking-[-0.02em] text-fg">{draft.label.trim() || category.label}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-fg-muted">
              <span className="mono text-fg">{category.table}</span>
              <span aria-hidden className="text-fg-subtle">·</span>
              <span>
                {translate("Präfix")}{' '}<span className="mono text-fg">{draft.prefix || '–'}</span>
              </span>
              <span aria-hidden className="text-fg-subtle">·</span>
              <span>{parts === 0 ? translate("ohne Bauteile") : `${formatNumber(parts)} ${parts === 1 ? translate("Bauteil") : translate("Bauteile")}`}</span>
              <span aria-hidden className="text-fg-subtle">·</span>
              <span>
                {formatNumber(ownFields)} {' '}{translate("eigene")}{' '}{ownFields === 1 ? translate("Feld") : translate("Felder")}
              </span>
              <span className="flex gap-1.5">
                {category.builtin ? <Badge variant="outline">{translate("aus Vorlage")}</Badge> : <Badge variant="outline">{translate("eigene")}</Badge>}
                {draft.altium_enabled ? (
                  <Badge variant="success" dot>
                    {translate("in Altium")}</Badge>
                ) : (
                  <Badge variant="neutral">{translate("nicht in Altium")}</Badge>
                )}
              </span>
            </div>
          </div>
          <Button asChild variant="ghost" size="sm">
            <Link to={`/bauteile/${encodeURIComponent(category.table)}`}>
              {translate("Bauteile")}<ArrowUpRight aria-hidden />
            </Link>
          </Button>
        </div>

        <Tabs value={tab} onValueChange={onTab}>
          <TabsList className="px-3" aria-label={translate("Bereiche der Kategorie")}>
            <TabsTrigger value="felder" icon={<ListTree />} count={formatNumber(ownFields)}>
              {translate("Felder")}</TabsTrigger>
            <TabsTrigger value="texte" icon={textErrors ? <TriangleAlert className="text-danger-text" /> : undefined}>
              {translate("Texte")}</TabsTrigger>
            <TabsTrigger value="eigenschaften" icon={propErrors ? <TriangleAlert className="text-danger-text" /> : undefined}>
              {translate("Eigenschaften")}</TabsTrigger>
          </TabsList>
          <TabsContent value="felder">
            <FieldsPanel category={category} kinds={kinds} />
          </TabsContent>
          <TabsContent value="texte">
            <TemplatesPanel category={category} draft={draft} saved={saved} onChange={change} dirty={dirty} />
          </TabsContent>
          <TabsContent value="eigenschaften">
            <PropertiesPanel category={category} draft={draft} errors={errors} onChange={change} onDeleted={onDeleted} />
          </TabsContent>
        </Tabs>
      </Card>

      <UnsavedChanges
        dirty={dirty}
        saving={update.isPending}
        onSave={save}
        onDiscard={reset}
        label={category.label}
        invalid={dirty ? firstError : null}
        shouldBlock={leavesCategory}
        root={root}
      />
    </div>
  )
}
