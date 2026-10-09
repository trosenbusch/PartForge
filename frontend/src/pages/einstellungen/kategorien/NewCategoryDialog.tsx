/**
 * Neue Kategorie: aus einer eingebauten Vorlage (Felder, Vorlagen und Standardsymbol werden übernommen – auch
 * mehrfach, z. B. „Präzisionswiderstände“ auf Basis „Widerstände“) oder leer (nur Standardfelder).
 */
import { FilePlus2, LayoutTemplate, Plus, Search } from 'lucide-react'
import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { useCategoryTemplates, useCreateCategory, type CategoryCreateInput, type CategoryDef } from '@/api/settings'
import {
  Button,
  Callout,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  Input,
  SegmentedControl,
  Skeleton,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { normalizeName, suggestColumn, validateTableName } from './meta'
import { CategoryTile, ColorPicker, IconPicker } from './pickers'

type Mode = 'vorlage' | 'leer'

interface Form {
  table: string
  label: string
  prefix: string
  icon: string
  color: string
}

const BLANK: Form = { table: '', label: '', prefix: 'U', icon: 'box', color: '#94A3B8' }

/** Tabellenname aus der Bezeichnung (ASCII, ohne Sonderzeichen) */
function suggestTable(label: string): string {
  const ascii = suggestColumn(label).replace(/[^A-Za-z0-9 _-]/g, ' ')
  const cleaned = normalizeName(ascii).replace(/^[^A-Za-z]+/, '')
  return cleaned.slice(0, 64)
}

function uniqueTable(base: string, existing: CategoryDef[]): string {
  const taken = new Set(existing.map((c) => c.table.toLowerCase()))
  if (!taken.has(base.toLowerCase())) return base
  for (let i = 2; i < 100; i++) {
    const name = `${base} ${i}`
    if (!taken.has(name.toLowerCase())) return name
  }
  return base
}

export function NewCategoryDialog({
  open,
  onOpenChange,
  categories,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  categories: CategoryDef[]
  onCreated: (table: string) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl">{open && <Body categories={categories} onOpenChange={onOpenChange} onCreated={onCreated} />}</DialogContent>
    </Dialog>
  )
}

function Body({
  categories,
  onOpenChange,
  onCreated,
}: {
  categories: CategoryDef[]
  onOpenChange: (open: boolean) => void
  onCreated: (table: string) => void
}) {
  const templates = useCategoryTemplates()
  const create = useCreateCategory()
  const [mode, setMode] = useState<Mode>('vorlage')
  const [template, setTemplate] = useState<CategoryDef | null>(null)
  const [form, setForm] = useState<Form>(BLANK)
  const [tableTouched, setTableTouched] = useState(false)
  const [query, setQuery] = useState('')
  const [error, setError] = useState<string | null>(null)
  const gridRef = useRef<HTMLDivElement>(null)

  const list = templates.data ?? []
  const q = query.trim().toLocaleLowerCase('de-DE')
  const shown = q ? list.filter((t) => `${t.label} ${t.table}`.toLocaleLowerCase('de-DE').includes(q)) : list

  const pick = (t: CategoryDef) => {
    setTemplate(t)
    const exists = categories.some((c) => c.table.toLowerCase() === t.table.toLowerCase())
    setForm({
      table: uniqueTable(t.table, categories),
      label: exists ? `${t.label} (neu)` : t.label,
      prefix: t.prefix,
      icon: t.icon,
      color: t.color,
    })
    setTableTouched(false)
    setError(null)
  }

  const switchMode = (m: Mode) => {
    setMode(m)
    setError(null)
    if (m === 'leer') {
      setTemplate(null)
      setForm(BLANK)
      setTableTouched(false)
    }
  }

  const set = <K extends keyof Form>(key: K, value: Form[K]) => setForm((f) => ({ ...f, [key]: value }))
  const tableError = form.table ? validateTableName(form.table, categories) : null
  const labelError = normalizeName(form.label) ? null : 'Bitte eine Bezeichnung eingeben.'
  const prefixError = /^[A-Za-z]{1,8}$/.test(form.prefix) ? null : '1–8 Buchstaben, z. B. R, C, U.'
  const ready = (mode === 'leer' || template) && form.table && !tableError && !labelError && !prefixError

  const submit = (e: FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!ready || create.isPending) return
    const input: CategoryCreateInput = {
      table: normalizeName(form.table),
      label: normalizeName(form.label),
      prefix: form.prefix.toUpperCase(),
      icon: form.icon,
      color: form.color,
      altium_enabled: true,
      fields: [],
      template: mode === 'vorlage' ? template?.table ?? null : null,
    }
    setError(null)
    create.mutate(input, {
      onSuccess: (cat) => {
        onOpenChange(false)
        onCreated(cat.table)
        const fieldCount = cat.fields?.filter((f) => !f.common).length ?? 0
        toast.success(`Kategorie „${cat.label}“ angelegt`, {
          description:
            fieldCount > 0
              ? `${formatNumber(fieldCount)} eigene Felder · erscheint als Tabelle ${cat.table} in der DbLib.`
              : `Tabelle ${cat.table} mit den Standardfeldern – jetzt eigene Felder hinzufügen.`,
        })
      },
      onError: (err) => setError(errorMessage(err)),
    })
  }

  const onGridKey = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const buttons = Array.from(gridRef.current?.querySelectorAll<HTMLButtonElement>('[role="radio"]') ?? [])
    if (!buttons.length) return
    const top = buttons[0].getBoundingClientRect().top
    const cols = Math.max(1, buttons.filter((b) => Math.abs(b.getBoundingClientRect().top - top) < 2).length)
    const delta: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: cols, ArrowUp: -cols }
    if (!(e.key in delta)) return
    e.preventDefault()
    const next = Math.max(0, Math.min(shown.length - 1, index + delta[e.key]))
    pick(shown[next])
    buttons[next]?.focus()
  }

  const selectedIndex = template ? shown.findIndex((t) => t.table === template.table) : -1
  const templateExists = template ? categories.some((c) => c.table.toLowerCase() === template.table.toLowerCase()) : false

  return (
    <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
      <DialogHeader
        tone="accent"
        icon={<FilePlus2 />}
        title="Neue Kategorie"
        description="Jede Kategorie ist eine eigene Tabelle – in Altium erscheint sie als Bibliothek im Components-Panel."
      />
      <DialogBody className="@container flex flex-col gap-4">
        <SegmentedControl<Mode>
          aria-label="Ausgangspunkt"
          value={mode}
          onValueChange={switchMode}
          options={[
            { value: 'vorlage', label: 'Aus Vorlage', icon: <LayoutTemplate /> },
            { value: 'leer', label: 'Leer beginnen', icon: <Plus /> },
          ]}
          className="self-start"
        />

        {mode === 'vorlage' && (
          <div className="flex flex-col gap-2.5">
            <Input
              size="sm"
              prefix={<Search />}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Vorlage suchen …"
              aria-label="Vorlagen durchsuchen"
              containerClassName="max-w-72"
            />
            {templates.isPending ? (
              <div className="grid grid-cols-1 gap-2 @[40rem]:grid-cols-3">
                {Array.from({ length: 6 }, (_, i) => (
                  <Skeleton key={i} className="h-16 rounded-button" />
                ))}
              </div>
            ) : templates.isError ? (
              <Callout tone="warning" title="Vorlagen konnten nicht geladen werden">
                {errorMessage(templates.error)}
              </Callout>
            ) : (
              <div
                ref={gridRef}
                role="radiogroup"
                aria-label="Vorlagen"
                className="grid max-h-[17.5rem] grid-cols-1 gap-2 overflow-y-auto p-0.5 @[30rem]:grid-cols-2 @[48rem]:grid-cols-3"
              >
                {shown.map((t, i) => {
                  const active = template?.table === t.table
                  const own = (t.fields ?? []).filter((f) => !f.common).length
                  return (
                    <button
                      key={t.table}
                      type="button"
                      role="radio"
                      aria-checked={active}
                      tabIndex={i === (selectedIndex >= 0 ? selectedIndex : 0) ? 0 : -1}
                      onClick={() => pick(t)}
                      onKeyDown={(e) => onGridKey(e, i)}
                      className={cn(
                        'flex min-h-14 min-w-0 items-center gap-2.5 rounded-button border px-2.5 py-2 text-left outline-none transition-colors focus-ring',
                        active
                          ? 'border-accent bg-accent-soft/60 shadow-[0_0_0_1px_var(--pf-accent)]'
                          : 'border-line bg-surface-2/40 hover:border-line-strong hover:bg-surface-2',
                      )}
                    >
                      <CategoryTile icon={t.icon} color={t.color} size="sm" />
                      <span className="min-w-0 flex-1">
                        <span className="line-clamp-2 text-ui font-medium leading-snug text-fg">{t.label}</span>
                        <span className="flex items-center gap-1.5 text-2xs text-fg-subtle">
                          <span className="mono truncate">{t.table}</span>
                          <span aria-hidden>·</span>
                          <span className="shrink-0">{own === 1 ? '1 Feld' : `${own} Felder`}</span>
                        </span>
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )}

        {mode === 'vorlage' && template && templateExists && (
          <p className="-mb-1 text-xs text-fg-muted">
            „{template.label}“ gibt es in dieser Bibliothek schon. Die neue Kategorie wird eine eigene Tabelle mit denselben Feldern –
            etwa für eine Variante.
          </p>
        )}

        {(mode === 'leer' || template) && (
          <div className="grid grid-cols-1 gap-4 rounded-card border border-line bg-surface-2/30 p-4 @[40rem]:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem]">
            <Field label="Bezeichnung" required error={form.label ? labelError ?? undefined : undefined}>
              <Input
                value={form.label}
                onChange={(e) => {
                  const label = e.target.value
                  setForm((f) => ({ ...f, label, table: tableTouched ? f.table : suggestTable(label) || f.table }))
                }}
                placeholder="z. B. Präzisionswiderstände"
              />
            </Field>
            <Field label="Tabellenname" required hint="ASCII" error={tableError ?? undefined}>
              <Input
                mono
                value={form.table}
                onChange={(e) => {
                  setTableTouched(true)
                  set('table', e.target.value)
                }}
                placeholder="Precision Resistors"
                spellCheck={false}
              />
            </Field>
            <Field label="Präfix" required error={form.prefix ? prefixError ?? undefined : undefined}>
              <Input
                mono
                value={form.prefix}
                onChange={(e) => set('prefix', e.target.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 8))}
                placeholder="R"
              />
            </Field>
            {mode === 'leer' && (
              <div className="flex flex-col gap-3 @[40rem]:col-span-3">
                <div className="flex items-center gap-3">
                  <CategoryTile icon={form.icon} color={form.color} size="lg" />
                  <ColorPicker value={form.color} onChange={(color) => set('color', color)} className="min-w-0 flex-1" />
                </div>
                <IconPicker value={form.icon} onChange={(icon) => set('icon', icon)} color={form.color} />
              </div>
            )}
          </div>
        )}

        {mode === 'vorlage' && !template && !templates.isPending && (
          <p className="text-xs text-fg-muted">Vorlage wählen – Felder, Beschreibungs- und Kommentarvorlage sowie das Standardsymbol werden übernommen.</p>
        )}

        {error && (
          <Callout tone="danger" title="Anlegen fehlgeschlagen" urgent>
            {error}
          </Callout>
        )}
      </DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={create.isPending}>
          Abbrechen
        </Button>
        <Button type="submit" variant="primary" leftIcon={<Plus />} loading={create.isPending} disabled={!ready}>
          Kategorie anlegen
        </Button>
      </DialogFooter>
    </form>
  )
}
