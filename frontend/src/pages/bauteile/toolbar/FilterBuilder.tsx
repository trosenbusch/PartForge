import { metadataLabel, t, tc, useI18n, getLocale } from '@/lib/i18n'
/**
 * Filter-Baukasten: Bedingungen je Spalte mit Operatoren passend zur Feldart – Messwerte vergleichen Werte mit
 * Einheiten im Backend („> 1k“, „zwischen 10 n … 1 µ“), Datumsfelder deutsch („09.10.2026“, „heute“, Schnellwahl
 * „letzte 7 Tage“), Auswahlfelder per Chips (Liste + vorhandene Werte), Text „enthält/beginnt mit“, leer/gesetzt.
 * Änderungen wirken sofort (entprellt). Darunter die aktiven Filter als Chips.
 */
import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, FilterX, ListFilter, Trash2, X } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { CategoryDef, FieldDef } from '@/api/library'
import { useDistinctValues } from '@/api/parts'
import {
  Button,
  ChipGroup,
  Combobox,
  Input,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Select,
  type ComboboxOption,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import {
  conditionLabel,
  dateInputLabel,
  daysAgoInput,
  defaultOp,
  FIELD_GROUPS,
  formatDateInput,
  groupOf,
  isComplete,
  isMono,
  isNumericKind,
  needsValue,
  newConditionId,
  opLabel,
  opsFor,
  parseDateInput,
  placeholderFor,
  type FilterCondition,
  type UiFilterOp,
} from '../model/fields'

export interface FilterBuilderProps {
  category: CategoryDef
  filters: FilterCondition[]
  onChange: (filters: FilterCondition[]) => void
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Bedingung, die beim Öffnen hervorgehoben wird (Klick auf einen Chip) */
  focusId?: string | null
  compact?: boolean
}

function fieldOptions(category: CategoryDef, translate = t): ComboboxOption[] {
  const label = new Map(FIELD_GROUPS.map((g) => [g.id, metadataLabel(g.label, t)]))
  return category.fields.map((f) => ({
    value: f.column,
    label: metadataLabel(f.label, translate),
    description: f.unit ? `${f.column} · ${f.unit}` : f.column !== f.label ? f.column : undefined,
    keywords: [f.column],
    group: label.get(groupOf(f)),
  }))
}

export function FilterBuilder({ category, filters, onChange, open, onOpenChange, focusId, compact }: FilterBuilderProps) {
  const { t } = useI18n()
  const [draft, setDraft] = useState<FilterCondition[]>(filters)
  const [adding, setAdding] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const fieldsByColumn = useMemo(() => new Map(category.fields.map((f) => [f.column, f])), [category])
  const options = useMemo(() => fieldOptions(category, t), [category, t])
  const active = filters.filter((c) => isComplete(c, fieldsByColumn.get(c.column))).length

  // beim Öffnen vom angewendeten Stand ausgehen (abgeleiteter Zustand, kein Effekt nötig)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setDraft(filters)
  }
  useEffect(() => () => window.clearTimeout(timer.current), [])

  const push = (next: FilterCondition[], immediate = false) => {
    setDraft(next)
    window.clearTimeout(timer.current)
    if (immediate) onChange(next)
    else timer.current = window.setTimeout(() => onChange(next), 350)
  }

  const add = (column: string | null) => {
    setAdding(null)
    if (!column) return
    const field = fieldsByColumn.get(column)
    if (!field) return
    push([...draft, { id: newConditionId(), column, op: defaultOp(field) }], true)
  }

  const update = (id: string, change: Partial<FilterCondition>, immediate = false) =>
    push(
      draft.map((c) => (c.id === id ? { ...c, ...change } : c)),
      immediate,
    )
  const remove = (id: string) => push(
    draft.filter((c) => c.id !== id),
    true,
  )

  return (
    <Popover open={open} onOpenChange={onOpenChange}>
      <PopoverTrigger asChild>
        <Button
          variant={active ? 'secondary' : 'ghost'}
          size="sm"
          leftIcon={<ListFilter />}
          aria-label={active ? t("Filter ({1} aktiv)", { 1: active }) : 'Filter'}
          className={cn(active > 0 && 'border-accent/40 text-accent-text')}
        >
          {!compact && 'Filter'}
          {active > 0 && (
            <span className="rounded-full bg-accent-soft px-1.5 text-2xs font-semibold tabular-nums leading-4 text-accent-text">
              {active}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" aria-labelledby="pf-filter-title" className="w-[min(36rem,calc(100vw-2rem))] p-0">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <div>
            <h2 id="pf-filter-title" className="text-ui font-semibold text-fg">
              Filter
            </h2>
            <p className="text-xs text-fg-muted">{t("Werte mit Einheiten werden verglichen – „> 1k“ findet auch „4,7 kΩ“.")}</p>
          </div>
          {draft.length > 0 && (
            <Button variant="ghost" size="xs" leftIcon={<Trash2 />} onClick={() => push([], true)}>
              {t("Alle entfernen")}
            </Button>
          )}
        </div>
        <div className="flex max-h-[min(26rem,60vh)] flex-col gap-2 overflow-y-auto px-4 py-3">
          {draft.length === 0 && (
            <p className="rounded-control border border-dashed border-line-strong px-3 py-4 text-center text-xs text-fg-muted">
              {t("Noch keine Bedingung. Wählen Sie unten eine Spalte – z. B. „{1}“.", {1: metadataLabel(category.fields.find((f) => !f.common)?.label ?? "Hersteller", t)})}
            </p>
          )}
          <RecentPresets
            category={category}
            draft={draft}
            onApply={(column, days) => {
              const rest = draft.filter((c) => !(c.column === column && (c.op === 'ge' || c.op === 'eq' || c.op === 'between')))
              push([...rest, { id: newConditionId(), column, op: days === 0 ? 'eq' : 'ge', value: daysAgoInput(days) }], true)
            }}
          />
          <AnimatePresence initial={false}>
            {draft.map((c) => {
              const field = fieldsByColumn.get(c.column)
              if (!field) return null
              return (
                <motion.div
                  key={c.id}
                  layout
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0 }}
                  transition={{ duration: 0.16 }}
                  className={cn(
                    'rounded-button border border-line bg-surface-2/50 p-2',
                    focusId === c.id && 'border-accent/45 shadow-[0_0_0_3px_var(--pf-accent-soft)]',
                  )}
                >
                  <ConditionRow
                    condition={c}
                    field={field}
                    table={category.table}
                    fieldOptions={options}
                    onChange={(change, immediate) => update(c.id, change, immediate)}
                    onFieldChange={(column) => {
                      const next = fieldsByColumn.get(column)
                      if (next) update(c.id, { column, op: defaultOp(next), value: undefined, to: undefined, values: undefined }, true)
                    }}
                    onRemove={() => remove(c.id)}
                  />
                </motion.div>
              )
            })}
          </AnimatePresence>
        </div>
        <div className="flex items-center gap-2 border-t border-line bg-surface-2/40 px-4 py-2.5">
          <Combobox
            options={options}
            value={adding}
            onValueChange={add}
            size="sm"
            placeholder={t("Bedingung hinzufügen …")}
            searchPlaceholder={t("Spalte suchen …")}
            className="w-60"
            aria-label={t("Spalte für neue Bedingung")}
          />
          <span className="ml-auto text-2xs text-fg-subtle">{t("Alle Bedingungen müssen zutreffen")}</span>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function ConditionRow({
  condition: c,
  field,
  table,
  fieldOptions: options,
  onChange,
  onFieldChange,
  onRemove,
}: {
  condition: FilterCondition
  field: FieldDef
  table: string
  fieldOptions: ComboboxOption[]
  onChange: (change: Partial<FilterCondition>, immediate?: boolean) => void
  onFieldChange: (column: string) => void
  onRemove: () => void
}) {
  const { t } = useI18n()
  const ops = opsFor(field)
  const multi = c.op === 'in' || c.op === 'notin'
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Combobox
          options={options}
          value={c.column}
          onValueChange={(v) => v && onFieldChange(v)}
          size="sm"
          searchPlaceholder={t("Spalte suchen …")}
          className="min-w-0 flex-1"
          aria-label={t("Spalte")}
        />
        <Select<UiFilterOp>
          size="sm"
          value={c.op}
          onValueChange={(op) => onChange({ op }, true)}
          options={ops.map((op) => ({ value: op, label: opLabel(op, field) }))}
          className="w-36"
          aria-label={t("Vergleich")}
        />
        <Button variant="ghost" size="sm" iconOnly aria-label={t("Bedingung entfernen")} onClick={onRemove}>
          <X />
        </Button>
      </div>
      {needsValue(c.op) &&
        (multi ? (
          <ValueChips field={field} table={table} values={c.values ?? []} onChange={(values) => onChange({ values }, true)} />
        ) : field.kind === 'date' ? (
          <DateValues condition={c} field={field} onChange={onChange} />
        ) : c.op === 'between' ? (
          <div className="flex items-center gap-2">
            <ValueInput field={field} value={c.value ?? ''} onChange={(value) => onChange({ value })} label={tc('range', 'von')} className="flex-1" />
            <span className="text-xs text-fg-subtle">{t("bis")}</span>
            <ValueInput field={field} value={c.to ?? ''} onChange={(to) => onChange({ to })} label={t("bis")} className="flex-1" />
          </div>
        ) : (
          <ValueInput field={field} value={c.value ?? ''} onChange={(value) => onChange({ value })} label={t("Wert")} />
        ))}
    </div>
  )
}

function ValueInput({
  field,
  value,
  onChange,
  label,
  className,
}: {
  field: FieldDef
  value: string
  onChange: (v: string) => void
  label: string
  className?: string
}) {
  const { t } = useI18n()
  const numeric = isNumericKind(field.kind)
  return (
    <Input
      size="sm"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      mono={numeric || isMono(field)}
      placeholder={numeric ? placeholderFor(field) : t("Text …")}
      suffix={field.unit ? <span className="mono">{field.unit}</span> : undefined}
      aria-label={`${metadataLabel(field.label, t)} ${label}`}
      containerClassName={cn('min-w-0', className)}
    />
  )
}

/** Datum (TT.MM.JJJJ, „heute“, „gestern“) mit Deutung und Schnellwahl für „mindestens“ */
function DateValues({
  condition: c,
  field,
  onChange,
}: {
  condition: FilterCondition
  field: FieldDef
  onChange: (change: Partial<FilterCondition>, immediate?: boolean) => void
}) {
  const { t } = useI18n()
  const presets = [
    { label: t("Heute"), days: 0 },
    { label: t("Letzte 7 Tage"), days: 7 },
    { label: t("Letzte 30 Tage"), days: 30 },
  ]
  return (
    <div className="flex flex-col gap-2">
      {c.op === 'between' ? (
        <div className="flex items-start gap-2">
          <DateInput field={field} value={c.value ?? ''} onChange={(value) => onChange({ value })} label={tc('range', 'von')} className="flex-1" />
          <span className="pt-1.5 text-xs text-fg-subtle">{t("bis")}</span>
          <DateInput field={field} value={c.to ?? ''} onChange={(to) => onChange({ to })} label={t("bis einschließlich")} className="flex-1" />
        </div>
      ) : (
        <DateInput field={field} value={c.value ?? ''} onChange={(value) => onChange({ value })} label={dateInputLabel(c.op)} />
      )}
      {c.op === 'ge' && (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("Schnellwahl")}>
          {presets.map((p) => {
            const value = daysAgoInput(p.days)
            const on = parseDateInput(c.value) === parseDateInput(value)
            return (
              <button
                key={p.label}
                type="button"
                aria-pressed={on}
                onClick={() => onChange({ value }, true)}
                className={cn(
                  'h-6 rounded-full border px-2.5 text-2xs outline-none transition-colors focus-ring',
                  on ? 'border-accent/40 bg-accent-soft text-accent-text' : 'border-line text-fg-muted hover:border-line-strong hover:text-fg',
                )}
              >
                {metadataLabel(p.label, t)}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

/** Datumsfelder für die Schnellwahl (Bezeichnung aus der Kategorie) */
const RECENT_COLUMNS = ['PF Modified', 'PF Created'] as const
const RECENT_PRESETS = [
  { get label() { return t("heute") }, days: 0 },
  { get label() { return t("7 Tage") }, days: 7 },
  { get label() { return t("30 Tage") }, days: 30 },
]

/** Schnellwahl „Geändert/Angelegt: heute · 7 Tage · 30 Tage“ – setzt bzw. ersetzt die Datumsbedingung */
function RecentPresets({
  category,
  draft,
  onApply,
}: {
  category: CategoryDef
  draft: FilterCondition[]
  onApply: (column: string, days: number) => void
}) {
  const { t } = useI18n()
  // nur Felder ohne eigene Bedingung – die bringt ihre Schnellwahl selbst mit
  const fields = RECENT_COLUMNS.map((col) => category.fields.find((f) => f.column === col)).filter(
    (f): f is FieldDef => Boolean(f) && !draft.some((c) => c.column === f?.column),
  )
  if (!fields.length) return null
  return (
    <div className="flex flex-col gap-1.5 rounded-button border border-line bg-surface-2/30 px-3 py-2">
      {fields.map((f) => {
        const current = draft.find((c) => c.column === f.column && (c.op === 'ge' || c.op === 'eq'))
        const iso = current ? parseDateInput(current.value) : null
        return (
          <div key={f.column} className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t("{1}: Schnellwahl", { 1: metadataLabel(f.label, t) })}>
            <CalendarDays aria-hidden className="size-3.5 text-fg-subtle" />
            <span className="mr-1 text-xs text-fg-muted">{metadataLabel(f.label, t)}</span>
            {RECENT_PRESETS.map((p) => {
              const on = Boolean(current && iso === parseDateInput(daysAgoInput(p.days)) && (p.days === 0 ? current.op === 'eq' : current.op === 'ge'))
              return (
                <button
                  key={p.label}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onApply(f.column, p.days)}
                  className={cn(
                    'h-6 rounded-full border px-2.5 text-2xs outline-none transition-colors focus-ring',
                    on ? 'border-accent/40 bg-accent-soft text-accent-text' : 'border-line text-fg-muted hover:border-line-strong hover:text-fg',
                  )}
                >
                  {p.days === 0 ? p.label : t("letzte {1}", { 1: metadataLabel(p.label, t) })}
                </button>
              )
            })}
          </div>
        )
      })}
    </div>
  )
}

const weekday = (date: Date) => new Intl.DateTimeFormat(getLocale(), { weekday: 'short' }).format(date)

function DateInput({
  field,
  value,
  onChange,
  label,
  className,
}: {
  field: FieldDef
  value: string
  onChange: (v: string) => void
  label: string
  className?: string
}) {
  const { t } = useI18n()
  const iso = parseDateInput(value)
  const invalid = Boolean(value.trim()) && !iso
  const day = iso ? new Date(`${iso}T12:00:00`) : null
  const echo = iso && value.trim() !== formatDateInput(iso) ? `${weekday(day as Date)}, ${formatDateInput(iso)}` : null
  return (
    <div className={cn('flex min-w-0 flex-col gap-1', className)}>
      <Input
        size="sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        mono
        invalid={invalid}
        placeholder={t("TT.MM.JJJJ")}
        prefix={<CalendarDays />}
        aria-label={`${metadataLabel(field.label, t)} ${label}`}
        aria-describedby={invalid || echo ? `${field.column}-${label}-hint`.replace(/[^a-z0-9-]+/gi, '-') : undefined}
        containerClassName="min-w-0"
      />
      {(invalid || echo) && (
        <p
          id={`${field.column}-${label}-hint`.replace(/[^a-z0-9-]+/gi, '-')}
          className={cn('text-2xs', invalid ? 'text-danger-text' : 'text-fg-subtle')}
        >
          {invalid ? t("Datum als TT.MM.JJJJ eingeben – z. B. 09.10.2026, „heute“") : `= ${echo}`}
        </p>
      )}
    </div>
  )
}

function ValueChips({
  field,
  table,
  values,
  onChange,
}: {
  field: FieldDef
  table: string
  values: string[]
  onChange: (values: string[]) => void
}) {
  const { t } = useI18n()
  const distinct = useDistinctValues(table, field.column)
  const options = useMemo(() => {
    const counts = new Map((distinct.data ?? []).map((d) => [d.value, d.count]))
    const base = field.kind === 'bool' ? ['Ja', 'Nein'] : field.options
    const all = [...base]
    for (const d of distinct.data ?? []) if (!all.some((o) => o.toLowerCase() === d.value.toLowerCase())) all.push(d.value)
    for (const v of values) if (!all.includes(v)) all.push(v)
    return all.map((v) => ({ value: v, label: field.kind === 'bool' || field.options.includes(v) ? metadataLabel(v, t) : v, meta: counts.has(v) ? formatNumber(counts.get(v) ?? 0) : undefined }))
  }, [distinct.data, field, values, t])
  if (!options.length) {
    return <p className="text-xs text-fg-subtle">{distinct.isPending ? t("Werte werden geladen …") : t("Noch keine Werte vorhanden.")}</p>
  }
  return (
    <ChipGroup
      size="sm"
      mono={isMono(field) || field.column === 'Size'}
      value={values}
      onValueChange={onChange}
      options={options}
      aria-label={t("{1}: Werte", { 1: metadataLabel(field.label, t) })}
      className="max-h-32 overflow-y-auto"
    />
  )
}

// --------------------------------------------------------------------------- aktive Filter

export function ActiveFilters({
  category,
  filters,
  onRemove,
  onClear,
  onEdit,
}: {
  category: CategoryDef
  filters: FilterCondition[]
  onRemove: (id: string) => void
  onClear: () => void
  onEdit: (id: string) => void
}) {
  const { t } = useI18n()
  const fields = new Map(category.fields.map((f) => [f.column, f]))
  const complete = filters.filter((c) => isComplete(c, fields.get(c.column)))
  return (
    <AnimatePresence initial={false}>
      {complete.length > 0 && (
        <motion.div
          key="chips"
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          exit={{ opacity: 0, height: 0 }}
          transition={{ duration: 0.18 }}
          className="overflow-hidden"
        >
          <ul aria-label={t("Aktive Filter")} className="flex flex-wrap items-center gap-1.5 pb-2.5">
            {complete.map((c) => {
              const text = conditionLabel(c, fields.get(c.column))
              return (
                <li key={c.id} className="flex h-6 items-center overflow-hidden rounded-full border border-accent/30 bg-accent-soft text-xs">
                  <button
                    type="button"
                    onClick={() => onEdit(c.id)}
                    className="flex h-full items-center gap-1 pl-2.5 pr-1 outline-none focus-ring-inset"
                    aria-label={t("Filter bearbeiten: {1}{2}", { 1: text.field, 2: text.rest })}
                  >
                    <span className="font-medium text-accent-text">{text.field}</span>
                    <span
                      className={cn(
                        'text-fg',
                        (isNumericKind(fields.get(c.column)?.kind ?? 'text') || fields.get(c.column)?.kind === 'date') && 'mono text-2xs',
                      )}
                    >
                      {text.rest}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemove(c.id)}
                    aria-label={t("Filter „{1}“ entfernen", { 1: text.field })}
                    className="flex h-full w-6 items-center justify-center text-accent-text outline-none hover:bg-accent/15 focus-ring-inset"
                  >
                    <X aria-hidden className="size-3" />
                  </button>
                </li>
              )
            })}
            <li>
              <Button variant="ghost" size="xs" onClick={onClear} leftIcon={<FilterX />}>
                {t("Alle entfernen")}
              </Button>
            </li>
          </ul>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
