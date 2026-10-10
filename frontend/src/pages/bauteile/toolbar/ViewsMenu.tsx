import { metadataLabel, useI18n } from '@/lib/i18n'
/**
 * Gespeicherte Ansichten (`/api/views`): Suche, Filter, Sortierung und sichtbare Spalten unter einem Namen –
 * anwenden, speichern, überschreiben, löschen. Ansichten ohne Kategorie gelten in allen Kategorien. Weicht der
 * aktuelle Stand von der angewendeten Ansicht ab, bleibt sie gewählt und ist als „geändert“ markiert – genau dann
 * bietet das Menü „aktualisieren“ und „Änderungen verwerfen“ an. „Standardansicht“ setzt auch die Spalten zurück.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bookmark, BookmarkCheck, BookmarkPlus, ChevronDown, Globe, RotateCcw, Save, Trash2, Undo2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import type { CategoryDef } from '@/api/library'
import { partsApi, partsKeys, useSavedViews, type SavedView, type SavedViewInput } from '@/api/parts'
import {
  Button,
  Checkbox,
  confirm,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Field,
  Input,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatRelativeTime, plural } from '@/lib/format'

export interface ViewsMenuProps {
  category: CategoryDef
  activeId: number | null
  /** Aktueller Stand weicht von der angewendeten Ansicht ab */
  modified?: boolean
  /** Aktueller Zustand als Ansicht (Suche, Filter, Sortierung, Spalten) */
  snapshot: () => Omit<SavedViewInput, 'name' | 'table'>
  /**
   * Ansicht anwenden (null = Standardansicht); `silent` = ohne Bestätigungs-Toast, `keep` (mit null) = nur die
   * aktive Ansicht vergessen, Suche/Filter/Spalten bleiben (z. B. nach dem Löschen der Ansicht)
   */
  onApply: (view: SavedView | null, opts?: { silent?: boolean; keep?: boolean }) => void
  compact?: boolean
}

export function ViewsMenu({ category, activeId, modified = false, snapshot, onApply, compact }: ViewsMenuProps) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const views = useSavedViews(category.table)
  const [saveOpen, setSaveOpen] = useState(false)
  const list = (views.data ?? []).filter((v) => !v.table || v.table.toLowerCase() === category.table.toLowerCase())
  const active = list.find((v) => v.id === activeId) ?? null
  const invalidate = () => qc.invalidateQueries({ queryKey: partsKeys.viewsAll })

  const overwrite = useMutation({
    mutationFn: (view: SavedView) => partsApi.updateView(view.id as number, snapshot()),
    meta: { errorTitle: t("Ansicht konnte nicht gespeichert werden") },
    onSuccess: (view) => {
      void invalidate()
      onApply(view, { silent: true })
      toast.success(t("Ansicht „{1}“ aktualisiert", { 1: view.name }))
    },
  })
  const remove = useMutation({
    mutationFn: (view: SavedView) => partsApi.deleteView(view.id as number),
    meta: { errorTitle: t("Ansicht konnte nicht gelöscht werden") },
    onSuccess: (_r, view) => {
      void invalidate()
      if (view.id === activeId) onApply(null, { keep: true })
      toast.success(t("Ansicht „{1}“ gelöscht", { 1: view.name }))
    },
  })

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            leftIcon={active ? <BookmarkCheck className="text-accent" /> : <Bookmark />}
            rightIcon={<ChevronDown className="opacity-60" />}
            aria-label={active ? t("Ansicht: {1}{2}", { 1: active.name, 2: modified ? t(" (geändert)") : '' }) : t("Ansichten")}
            className={cn('relative max-w-56', active && 'text-fg')}
          >
            {!compact && <span className="truncate">{active ? active.name : t("Ansichten")}</span>}
            {active && modified && (
              <span
                aria-hidden
                title={t("Geändert – im Menü aktualisieren oder verwerfen")}
                className={cn('size-1.5 shrink-0 rounded-full bg-accent', compact && 'absolute right-1 top-1')}
              />
            )}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          {active && modified && (
            <>
              <DropdownMenuLabel>{t("„{1}“ – geändert", {1: active.name})}</DropdownMenuLabel>
              <DropdownMenuItem icon={<Save />} onSelect={() => overwrite.mutate(active)} description={t("Mit aktueller Suche, Filtern und Spalten")}>
                {t("„{1}“ aktualisieren", {1: active.name})}
              </DropdownMenuItem>
              <DropdownMenuItem icon={<Undo2 />} onSelect={() => onApply(active)}>
                {t("Änderungen verwerfen")}
              </DropdownMenuItem>
              <DropdownMenuSeparator />
            </>
          )}
          <DropdownMenuLabel>{t("Gespeicherte Ansichten")}</DropdownMenuLabel>
          <DropdownMenuItem icon={<RotateCcw />} onSelect={() => onApply(null)} description={t("Ohne Suche und Filter, Standardspalten")}>
            {t("Standardansicht")}
          </DropdownMenuItem>
          {list.map((v) => (
            <DropdownMenuItem
              key={v.id}
              icon={v.id === activeId ? <BookmarkCheck className="text-accent!" /> : v.table ? <Bookmark /> : <Globe />}
              onSelect={() => onApply(v)}
              description={[
                v.filters.length ? plural(v.filters.length, 'Filter', 'Filter') : null,
                v.search ? t("Suche „{1}“", { 1: v.search }) : null,
                v.table ? null : t("alle Kategorien"),
                v.modified ? formatRelativeTime(v.modified) : null,
              ]
                .filter(Boolean)
                .join(' · ')}
              className={cn(v.id === activeId && 'bg-accent-soft/60')}
            >
              {v.name}
            </DropdownMenuItem>
          ))}
          {views.isPending && <div className="px-2 py-1.5 text-xs text-fg-subtle">{t("Ansichten werden geladen …")}</div>}
          {!views.isPending && list.length === 0 && (
            <div className="px-2 py-1.5 text-xs leading-snug text-fg-subtle">
              {t("Noch keine gespeicherte Ansicht – Suche, Filter, Sortierung und Spalten lassen sich unter einem Namen merken.")}
            </div>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem icon={<BookmarkPlus />} onSelect={() => setSaveOpen(true)}>
            {t("Aktuelle Ansicht speichern …")}
          </DropdownMenuItem>
          {active && (
            <>
              {!modified && (
                <DropdownMenuItem icon={<Save />} onSelect={() => overwrite.mutate(active)}>
                  {t("„{1}“ aktualisieren", {1: active.name})}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                icon={<Trash2 />}
                destructive
                onSelect={() => {
                  void confirm({
                    title: t("Ansicht „{1}“ löschen?", { 1: active.name }),
                    description: t("Die Bauteile bleiben unverändert – nur die gespeicherte Ansicht wird entfernt."),
                    confirmLabel: t("Löschen"),
                    destructive: true,
                  }).then((ok) => ok && remove.mutate(active))
                }}
              >
                {t("Ansicht löschen")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <SaveViewDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        category={category}
        snapshot={snapshot}
        onSaved={(view) => {
          void invalidate()
          onApply(view)
        }}
      />
    </>
  )
}

function SaveViewDialog({
  open,
  onOpenChange,
  category,
  snapshot,
  onSaved,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  category: CategoryDef
  snapshot: ViewsMenuProps['snapshot']
  onSaved: (view: SavedView) => void
}) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [global, setGlobal] = useState(false)
  const save = useMutation({
    mutationFn: () => partsApi.createView({ ...snapshot(), name: name.trim(), table: global ? null : category.table }),
    meta: { errorTitle: t("Ansicht konnte nicht gespeichert werden") },
    onSuccess: (view) => {
      toast.success(t("Ansicht „{1}“ gespeichert", { 1: view.name }))
      onSaved(view)
      onOpenChange(false)
      setName('')
    },
  })
  const snap = open ? snapshot() : null
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (name.trim()) save.mutate()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader
            icon={<BookmarkPlus />}
            title={t("Ansicht speichern")}
            description={t("Suche, Filter, Sortierung und sichtbare Spalten von „{1}“ unter einem Namen merken.", { 1: metadataLabel(category.label, t) })}
          />
          <DialogBody className="flex flex-col gap-4">
            <Field label={t("Name")} required>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("z. B. 0603 · 1 % · aktiv")} />
            </Field>
            {snap && (
              <ul className="flex flex-col gap-1 rounded-button border border-line bg-surface-2/50 px-3 py-2.5 text-xs text-fg-muted">
                <li>{t("Suche:")} {snap.search ? <span className="text-fg">„{snap.search}“</span> : '–'}</li>
                <li>{t("Filter:")} {snap.filters?.length ? <span className="text-fg">{snap.filters.length}</span> : '–'}</li>
                <li>
                  {t("Sortierung:")}{' '}
                  {snap.sort?.length ? (
                    <span className="text-fg">
                      {snap.sort
                        .map((s) => `${metadataLabel(category.fields.find((f) => f.column === s.column)?.label ?? s.column, t)} ${s.desc ? '↓' : '↑'}`)
                        .join(', ')}
                    </span>
                  ) : (
                    t("Teilenummer ↑")
                  )}
                </li>
                <li>{t("Spalten:")} {snap.columns?.length ? <span className="text-fg">{snap.columns.length}  {t("sichtbar")}</span> : t("Standard")}</li>
              </ul>
            )}
            <Checkbox
              checked={global}
              onCheckedChange={(v) => setGlobal(v === true)}
              label={t("In allen Kategorien anbieten")}
              description={t("Spalten, die es in einer Kategorie nicht gibt, werden dort ignoriert.")}
            />
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              {t("Abbrechen")}
            </Button>
            <Button type="submit" variant="primary" loading={save.isPending} disabled={!name.trim()}>
              {t("Speichern")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
