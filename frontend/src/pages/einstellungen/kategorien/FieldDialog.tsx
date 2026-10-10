import { t as translate, useI18n } from '@/lib/i18n'
/**
 * Feld anlegen oder bearbeiten: Spaltenname (= Altium-Parameter), Beschriftung, Art, Einheit, Auswahloptionen,
 * Merkmale, weiche Längengrenze und Hilfetext. Geschützte Felder erlauben nur Beschriftung, Hilfe, Pflicht,
 * Schaltplan und Länge; Standardfelder lassen sich nicht umbenennen.
 */
import { ArrowDownAZ, Lock, Pencil, Plus, TableProperties, TriangleAlert, X } from 'lucide-react'
import { useState, type FormEvent, type KeyboardEvent } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import { schemaApi, useFieldMutation, type CategoryDef, type FieldDef, type FieldInput, type FieldKind, type FieldKindInfo, type FieldPatch } from '@/api/settings'
import {
  Button,
  Callout,
  Combobox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  Input,
  NumberInput,
  Select,
  Switch,
  Textarea,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { defaultLength, FIELD_KIND_META, kindIcon, normalizeName, suggestColumn, UNIT_SUGGESTIONS, validateColumnName } from './meta'
import { runUndo } from './undo'

interface FieldForm {
  column: string
  label: string
  kind: FieldKind
  unit: string | null
  options: string[]
  required: boolean
  show_on_schematic: boolean
  add_to_design: boolean
  system: boolean
  length: number | null
  help: string
}

const EMPTY: FieldForm = {
  column: '',
  label: '',
  kind: 'text',
  unit: null,
  options: [],
  required: false,
  show_on_schematic: false,
  add_to_design: true,
  system: false,
  length: null,
  help: '',
}

function fromField(f: FieldDef): FieldForm {
  return {
    column: f.column,
    label: f.label,
    kind: f.kind,
    unit: f.unit ?? null,
    options: f.options ?? [],
    required: f.required,
    show_on_schematic: f.show_on_schematic,
    add_to_design: f.add_to_design,
    system: f.system,
    length: f.length ?? null,
    help: f.help ?? '',
  }
}

const hasUnit = (kind: FieldKind) => kind === 'quantity' || kind === 'range'

/** Nur geänderte Eigenschaften (für PATCH und „Rückgängig“) */
function diff(before: FieldForm, after: FieldForm): FieldPatch {
  const patch: FieldPatch = {}
  if (normalizeName(after.column) !== before.column) patch.column = normalizeName(after.column)
  if (after.label.trim() !== before.label) patch.label = after.label.trim()
  if (after.kind !== before.kind) patch.kind = after.kind
  const unit = hasUnit(after.kind) ? after.unit?.trim() || null : null
  if (unit !== (before.unit ?? null)) patch.unit = unit
  const options = after.kind === 'enum' ? after.options : []
  if (JSON.stringify(options) !== JSON.stringify(before.options)) patch.options = options
  if (after.required !== before.required) patch.required = after.required
  if (after.show_on_schematic !== before.show_on_schematic) patch.show_on_schematic = after.show_on_schematic
  if (after.add_to_design !== before.add_to_design) patch.add_to_design = after.add_to_design
  if (after.system !== before.system) patch.system = after.system
  if (after.length !== before.length) patch.length = after.length
  if ((after.help.trim() || null) !== (before.help || null)) patch.help = after.help.trim() || null
  return patch
}

/** Gegenstück eines Patches (alte Werte) – für „Rückgängig“ */
function inverse(patch: FieldPatch, before: FieldForm): FieldPatch {
  const back: FieldPatch = {}
  for (const key of Object.keys(patch) as (keyof FieldPatch)[]) {
    if (key === 'column') back.column = before.column
    else if (key === 'help') back.help = before.help || null
    else (back as Record<string, unknown>)[key] = before[key as keyof FieldForm]
  }
  return back
}

export interface FieldDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  category: CategoryDef
  /** Bearbeiten (sonst neues Feld) */
  field?: FieldDef | null
  kinds: FieldKindInfo[]
}

export function FieldDialog(props: FieldDialogProps) {
  useI18n()
  // Formular bei jedem Öffnen neu aufbauen
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent size="lg">
        {props.open && <FieldDialogBody key={props.field?.column ?? '__neu'} {...props} />}
      </DialogContent>
    </Dialog>
  )
}

function FieldDialogBody({ onOpenChange, category, field, kinds }: FieldDialogProps) {
  useI18n()
  const editing = Boolean(field)
  const initial = field ? fromField(field) : EMPTY
  const [form, setForm] = useState<FieldForm>(initial)
  const [columnTouched, setColumnTouched] = useState(editing)
  const [error, setError] = useState<string | null>(null)
  const protectedField = Boolean(field?.protected)
  const renameLocked = Boolean(field && (field.protected || field.common))
  const table = category.table

  const add = useFieldMutation((f: FieldInput) => schemaApi.addField(table, f), translate("Feld konnte nicht angelegt werden"), true)
  const update = useFieldMutation(
    ({ column, patch }: { column: string; patch: FieldPatch }) => schemaApi.updateField(table, column, patch),
    translate("Feld konnte nicht gespeichert werden"),
    true,
  )

  const set = <K extends keyof FieldForm>(key: K, value: FieldForm[K]) => setForm((f) => ({ ...f, [key]: value }))

  const columnError = renameLocked ? null : validateColumnName(form.column, category.fields, field?.column)
  const labelError = form.label.trim() ? null : translate("Bitte eine Beschriftung eingeben.")
  const patch = field ? diff(initial, form) : null
  const renamed = Boolean(field && patch?.column)
  const nothingChanged = Boolean(field && patch && Object.keys(patch).length === 0)
  const busy = add.isPending || update.isPending
  const canSubmit = !columnError && !labelError && !nothingChanged && !busy

  const submit = (e: FormEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!canSubmit) return
    setError(null)
    if (!field) {
      const column = normalizeName(form.column)
      const input: FieldInput = {
        column,
        label: form.label.trim(),
        kind: form.kind,
        unit: hasUnit(form.kind) ? form.unit?.trim() || null : null,
        options: form.kind === 'enum' ? form.options : [],
        required: form.required,
        show_on_schematic: form.show_on_schematic,
        add_to_design: form.add_to_design,
        system: form.system,
        common: false,
        sort_order: 0,
        protected: false,
        length: form.length,
        help: form.help.trim() || null,
      }
      add.mutate(input, {
        onSuccess: () => {
          onOpenChange(false)
          toast.success(translate("Feld „{value1}“ hinzugefügt", { value1: input.label }), {
            description: translate("Neue Spalte {value1} in {value2} – erscheint in Tabelle, Formularen und DbLib.", { value1: column, value2: table }),
            action: { label: translate("Rückgängig"), onClick: () => void runUndo(() => schemaApi.removeField(table, column), translate("Feld „{value1}“ wieder entfernt", { value1: input.label })) },
          })
        },
        onError: (err) => setError(errorMessage(err)),
      })
      return
    }
    if (!patch) return
    const before = initial
    update.mutate(
      { column: field.column, patch },
      {
        onSuccess: () => {
          onOpenChange(false)
          const newColumn = patch.column ?? field.column
          toast.success(renamed ? translate("Spalte umbenannt in „{value1}“", { value1: newColumn }) : translate("Feld „{value1}“ gespeichert", { value1: form.label.trim() }), {
            action: {
              label: translate("Rückgängig"),
              onClick: () => void runUndo(() => schemaApi.updateField(table, newColumn, inverse(patch, before))),
            },
          })
        },
        onError: (err) => setError(errorMessage(err)),
      },
    )
  }

  const kindOptions = kinds.map((k) => ({
    value: k.kind,
    label: translate(k.label),
    description: translate(FIELD_KIND_META[k.kind]?.help ?? ''),
    icon: kindIcon(k.kind),
  }))

  return (
    <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
      <DialogHeader
        icon={editing ? <Pencil /> : <TableProperties />}
        title={editing ? translate("Feld „{value1}“ bearbeiten", { value1: field?.label ?? '' }) : translate("Feld hinzufügen")}
        description={
          editing
            ? translate("Kategorie {value1} · Spalte {value2}", { value1: category.label, value2: field?.column ?? '' })
            : translate("Neue Spalte in {value1} – wird zum Altium-Parameter und erscheint in Tabelle und Formularen.", { value1: category.label })
        }
      />
      <DialogBody className="@container flex flex-col gap-5">
        {protectedField && (
          <Callout tone="neutral" icon={<Lock />} title={translate("Geschütztes Feld")}>
            {translate("Wird für die Altium-Verknüpfung bzw. die Verwaltung gebraucht. Änderbar sind Beschriftung, Hilfetext, Pflichtfeld, Schaltplan-Sichtbarkeit und Länge.")}</Callout>
        )}

        <div className="grid grid-cols-1 gap-4 @[34rem]:grid-cols-2">
          <Field label={translate("Beschriftung")} required error={form.label && labelError ? labelError : undefined} hint={translate("frei wählbar")}>
            <Input
              value={form.label}
              onChange={(e) => {
                const label = e.target.value
                setForm((f) => ({ ...f, label, column: columnTouched ? f.column : suggestColumn(label) }))
              }}
              placeholder={translate("z. B. Nennstrom")}
            />
          </Field>
          <Field
            label={translate("Spaltenname")}
            required
            hint={renameLocked ? translate("fest") : translate("Altium-Parameter")}
            error={form.column && columnError ? columnError : undefined}
            help={renameLocked ? translate("Standardfelder behalten ihren Namen.") : translate("ASCII, ohne . : { } [ ] – z. B. „Current Rating“.")}
          >
            <Input
              mono
              value={form.column}
              disabled={renameLocked}
              onChange={(e) => {
                setColumnTouched(true)
                set('column', e.target.value)
              }}
              placeholder="Current Rating"
              spellCheck={false}
              autoComplete="off"
              suffix={renameLocked ? <Lock /> : undefined}
            />
          </Field>
        </div>

        {renamed && (
          <Callout tone="warning" icon={<TriangleAlert />} title={translate("Altium-Designs behalten den alten Parameternamen")}>
            {translate("Vorlagen und gespeicherte Ansichten passt PartForge an. In Schaltplänen bereits platzierte Bauteile führen den Parameter aber weiter als „")}{field?.column}{translate("“, bis sie aus der Datenbank aktualisiert werden (Altium: Tools › Update Parameters From Database).")}</Callout>
        )}

        <div className="grid grid-cols-1 gap-4 @[34rem]:grid-cols-2">
          <Field label={translate("Art")} help={translate(FIELD_KIND_META[form.kind]?.help ?? '')}>
            <Select<FieldKind>
              value={form.kind}
              onValueChange={(v) => set('kind', v)}
              options={kindOptions}
              disabled={protectedField}
            />
          </Field>
          {hasUnit(form.kind) ? (
            <Field label={translate("Einheit")} hint={translate("empfohlen")} help={translate("Ohne Einheit werden Werte als reine Zahlen gespeichert.")}>
              <Combobox
                options={UNIT_SUGGESTIONS.map((u) => ({ value: u.value, label: u.value, description: translate(u.label), keywords: [u.label, translate(u.label)] }))}
                value={form.unit}
                onValueChange={(v) => set('unit', v)}
                allowCustom
                clearable
                mono
                placeholder={translate("Einheit wählen …")}
                searchPlaceholder={translate("Einheit suchen oder eingeben …")}
                disabled={protectedField}
              />
            </Field>
          ) : (
            <div className="hidden @[34rem]:block" />
          )}
        </div>

        {form.kind === 'enum' && (
          <Field label={translate("Auswahloptionen")} hint={translate("{value1} Optionen", { value1: form.options.length })} help={translate("Enter fügt hinzu, Einfügen mehrerer Werte (durch Komma oder Zeilen getrennt) geht auch. Freie Eingabe bleibt erlaubt.")}>
            <OptionsEditor value={form.options} onChange={(v) => set('options', v)} disabled={protectedField} />
          </Field>
        )}

        <div className="grid grid-cols-1 gap-x-6 gap-y-3 rounded-card border border-line bg-surface-2/40 p-4 @[34rem]:grid-cols-2">
          <Switch
            checked={form.required}
            onCheckedChange={(v) => set('required', v)}
            disabled={field?.column === 'Part Number'}
            label={translate("Pflichtfeld")}
            description={translate("Bauteile ohne Wert gelten als unvollständig.")}
          />
          <Switch
            checked={form.show_on_schematic}
            onCheckedChange={(v) => set('show_on_schematic', v)}
            label={translate("Im Schaltplan sichtbar")}
            description={translate("Parameter wird beim Platzieren angezeigt.")}
          />
          <Switch
            checked={form.add_to_design}
            onCheckedChange={(v) => set('add_to_design', v)}
            disabled={protectedField}
            label={translate("Ins Design übernehmen")}
            description={translate("Als Bauteilparameter in den Schaltplan kopieren.")}
          />
          <Switch
            checked={form.system}
            onCheckedChange={(v) => set('system', v)}
            disabled={protectedField}
            label={translate("Systemfeld")}
            description={translate("Verknüpfung/Verwaltung statt Bauteilparameter.")}
          />
        </div>

        <div className="grid grid-cols-1 gap-4 @[34rem]:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
          <Field
            label={translate("Höchstlänge")}
            hint={translate("weiche Grenze")}
            help={translate("Leer = Standard ({value1} Zeichen), 0 = unbegrenzt. Längere Werte werden gespeichert, aber gemeldet.", { value1: formatNumber(defaultLength({ column: normalizeName(form.column), kind: form.kind })) })}
          >
            <NumberInput
              value={form.length}
              onValueChange={(v) => set('length', v === null ? null : Math.round(v))}
              allowEmpty
              min={0}
              max={100000}
              step={1}
              decimals={0}
              unit={translate("Zeichen")}
              placeholder={translate("Standard ({value1})", { value1: formatNumber(defaultLength({ column: normalizeName(form.column), kind: form.kind })) })}
            />
          </Field>
          <Field label={translate("Hilfetext")} hint={translate("optional")}>
            <Textarea
              rows={2}
              autoResize
              value={form.help}
              onChange={(e) => set('help', e.target.value)}
              placeholder={translate("Erscheint als Hinweis in Formularen und Tabellenköpfen.")}
            />
          </Field>
        </div>

        {error && (
          <Callout tone="danger" title={editing ? translate("Speichern fehlgeschlagen") : translate("Anlegen fehlgeschlagen")} urgent>
            {error}
          </Callout>
        )}
      </DialogBody>
      <DialogFooter>
        {nothingChanged && <span className="mr-auto text-xs text-fg-subtle">{translate("Keine Änderungen")}</span>}
        <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
          {translate("Abbrechen")}</Button>
        <Button type="submit" variant="primary" loading={busy} disabled={!canSubmit} leftIcon={editing ? undefined : <Plus />}>
          {editing ? (renamed ? translate("Umbenennen und speichern") : translate("Speichern")) : translate("Feld hinzufügen")}
        </Button>
      </DialogFooter>
    </form>
  )
}

// --------------------------------------------------------------------------- Optionen

function OptionsEditor({ value, onChange, disabled }: { value: string[]; onChange: (v: string[]) => void; disabled?: boolean }) {
  useI18n()
  const [text, setText] = useState('')
  const addMany = (raw: string) => {
    const items = raw
      .split(/[\n;,]/)
      .map((s) => normalizeName(s))
      .filter(Boolean)
    if (!items.length) return
    const next = [...value]
    for (const item of items) if (!next.includes(item)) next.push(item)
    onChange(next)
    setText('')
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      e.stopPropagation()
      addMany(text)
    } else if (e.key === 'Backspace' && !text && value.length) {
      onChange(value.slice(0, -1))
    }
  }
  return (
    <div className={cn('flex flex-col gap-2 rounded-button border border-line-control bg-control p-2', disabled && 'opacity-55')}>
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={translate("Optionen")}>
          {value.map((o) => (
            <li key={o} className="flex h-6 items-center gap-1 rounded-md border border-line bg-surface-2 pl-2 pr-0.5 text-xs text-fg">
              {o}
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(value.filter((x) => x !== o))}
                aria-label={translate("Option „{value1}“ entfernen", { value1: o })}
                className="flex size-5 items-center justify-center rounded-sm text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
              >
                <X aria-hidden className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex items-center gap-1.5">
        <input
          value={text}
          disabled={disabled}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={(e) => {
            const pasted = e.clipboardData.getData('text')
            if (/[\n;,]/.test(pasted)) {
              e.preventDefault()
              addMany(pasted)
            }
          }}
          placeholder={value.length ? translate("Weitere Option …") : translate("Option eingeben und Enter drücken")}
          aria-label={translate("Option hinzufügen")}
          className="h-7 min-w-0 flex-1 bg-transparent px-1 text-ui text-fg outline-none placeholder:text-fg-subtle"
        />
        <Button size="xs" variant="ghost" leftIcon={<Plus />} onClick={() => addMany(text)} disabled={disabled || !text.trim()}>
          {translate("Hinzufügen")}</Button>
        {value.length > 1 && (
          <Button
            size="xs"
            variant="ghost"
            leftIcon={<ArrowDownAZ />}
            disabled={disabled}
            onClick={() => onChange([...value].sort((a, b) => a.localeCompare(b, 'de', { numeric: true })))}
          >
            A–Z
          </Button>
        )}
      </div>
    </div>
  )
}
