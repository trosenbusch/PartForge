/**
 * Eingabe für ein Bauteilfeld je Feldart: Auswahlliste (mit vorhandenen Werten, freie Eingabe erlaubt), Ja/Nein,
 * Symbol-/Footprint-Verweis (registrierte Einträge mit Vorschaubild, Pins/Pads, Verwendung und Status – nicht
 * registrierte Namen bleiben eintragbar), Messwerte in Mono mit Einheit, Text, Notizen.
 *
 * Messwerte erscheinen ohne Fokus lesbar formatiert („0.1W“ → „0,1 W“); beim Bearbeiten steht der gespeicherte
 * Text im Feld. Die Einheit als Suffix nur, solange der Text noch keine trägt („10k“ → „10k Ω“).
 *
 * `onCommit` meldet einen abgeschlossenen Wert (Enter, Verlassen des Felds, Auswahl) – für sofortiges Speichern.
 * `onCancel` (Esc) setzt bei Textfeldern auf den Ausgangswert zurück. `describedBy`/`required` verknüpfen
 * Meldungen und Pflichtangabe für Screenreader (wie `Field` im UI-Kit).
 */
import { CircuitBoard, Component as SymbolIcon } from 'lucide-react'
import { useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import type { FieldDef } from '@/api/library'
import { useDistinctValues, useLibraryFootprints, useLibrarySymbols, type FootprintEntry, type SymbolEntry } from '@/api/parts'
import { FootprintThumb } from '@/pages/footprints/library/FootprintThumb'
import { SymbolThumb } from '@/pages/symbole/library/SymbolThumb'
import { Combobox, Input, SegmentedControl, Textarea, type ComboboxOption } from '@/components/ui'
import { FieldContext } from '@/components/ui/fieldContext'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { displayValue, isFootprintRef, isMono, placeholderFor, SYMBOL_REF } from '../model/fields'

export interface FieldInputProps {
  field: FieldDef
  table: string
  value: string
  onChange: (value: string) => void
  onCommit?: (value: string) => void
  onCancel?: () => void
  size?: 'sm' | 'md'
  invalid?: boolean
  disabled?: boolean
  id?: string
  placeholder?: string
  /** Vorhandene Werte der Spalte als Vorschläge (Auswahlfelder, Hersteller, Gehäuse) */
  suggestions?: boolean
  className?: string
  'aria-label'?: string
  /** ID der Meldung unter dem Feld (Fehler/Hinweis) */
  describedBy?: string
  /** Pflichtfeld (→ aria-required) */
  required?: boolean
}

const DISTINCT_FIELDS = new Set(['Manufacturer', 'Package', 'Supplier 1', 'Supplier 2', 'Series'])

export function FieldInput(props: FieldInputProps) {
  const { field, describedBy, required, invalid, disabled } = props
  const auto = `fi-${useId().replace(/:/g, '')}`
  const p = { ...props, id: props.id ?? auto }
  let control: ReactNode
  if (field.column === SYMBOL_REF) control = <RefInput {...p} kind="symbol" />
  else if (isFootprintRef(field.column)) control = <RefInput {...p} kind="footprint" />
  else if (field.kind === 'enum' || (props.suggestions !== false && DISTINCT_FIELDS.has(field.column))) control = <EnumInput {...p} />
  else if (field.kind === 'bool') control = <BoolInput {...p} />
  else if (field.column === 'Notes' || field.column === 'Description') control = <LongTextInput {...p} />
  else control = <TextInput {...p} />
  if (!describedBy && !required) return control
  return (
    <FieldContext.Provider value={{ id: p.id, describedBy, invalid: Boolean(invalid), disabled, required }}>
      {control}
    </FieldContext.Provider>
  )
}

// --------------------------------------------------------------------------- Text

/** Endet der Text schon mit einer Einheit (Buchstabe, %, °, Ω …)? Dann kein Einheiten-Suffix daneben. */
const HAS_UNIT = /[A-Za-zµμΩ°%‰]\s*$/

function TextInput({
  field,
  value,
  onChange,
  onCommit,
  onCancel,
  size = 'md',
  invalid,
  disabled,
  id,
  placeholder,
  className,
  'aria-label': ariaLabel,
}: FieldInputProps) {
  const committed = useRef(value)
  const [focused, setFocused] = useState(false)
  const formatted = field.kind === 'quantity' || field.kind === 'range'
  const shown = formatted && !focused ? displayValue(field, value) : value
  const showUnit = Boolean(field.unit) && field.kind !== 'text' && !HAS_UNIT.test(shown)
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      committed.current = value
      onCommit?.(value)
    } else if (e.key === 'Escape' && onCancel) {
      e.preventDefault()
      e.stopPropagation()
      onCancel()
    }
  }
  return (
    <Input
      id={id}
      size={size}
      value={shown}
      onChange={(e) => onChange(e.target.value)}
      onFocus={() => {
        committed.current = value
        setFocused(true)
      }}
      onBlur={() => {
        setFocused(false)
        if (committed.current !== value) onCommit?.(value)
      }}
      onKeyDown={onKeyDown}
      invalid={invalid}
      disabled={disabled}
      mono={isMono(field)}
      placeholder={placeholder ?? placeholderFor(field)}
      suffix={showUnit ? <span className="mono">{field.unit}</span> : undefined}
      spellCheck={field.kind === 'text' && !isMono(field)}
      inputMode={field.kind === 'int' ? 'numeric' : undefined}
      containerClassName={className}
      aria-label={ariaLabel}
    />
  )
}

function LongTextInput({
  field,
  value,
  onChange,
  onCommit,
  onCancel,
  invalid,
  disabled,
  id,
  className,
  placeholder,
  'aria-label': ariaLabel,
}: FieldInputProps) {
  const committed = useRef(value)
  return (
    <Textarea
      id={id}
      value={value}
      rows={field.column === 'Notes' ? 2 : 1}
      autoResize
      onChange={(e) => onChange(e.target.value)}
      onFocus={() => {
        committed.current = value
      }}
      onBlur={() => {
        if (committed.current !== value) onCommit?.(value)
      }}
      onKeyDown={(e) => {
        // Enter speichert (Umschalt+Enter = neue Zeile in Notizen), Esc verwirft
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault()
          committed.current = value
          onCommit?.(value)
        } else if (e.key === 'Escape' && onCancel) {
          e.preventDefault()
          e.stopPropagation()
          onCancel()
        }
      }}
      invalid={invalid}
      disabled={disabled}
      placeholder={placeholder}
      className={cn('min-h-0 py-1.5 text-ui', className)}
      aria-label={ariaLabel}
    />
  )
}

// --------------------------------------------------------------------------- Auswahl

function EnumInput({
  field,
  table,
  value,
  onChange,
  onCommit,
  size = 'md',
  invalid,
  disabled,
  id,
  placeholder,
  suggestions = true,
  className,
  'aria-label': ariaLabel,
}: FieldInputProps) {
  const distinct = useDistinctValues(table, field.column, suggestions)
  const options = useMemo<ComboboxOption[]>(() => {
    const out: ComboboxOption[] = field.options.map((o) => ({ value: o, label: o, group: field.options.length ? 'Auswahlliste' : undefined }))
    for (const d of distinct.data ?? []) {
      if (out.some((o) => o.value.toLowerCase() === d.value.toLowerCase())) continue
      out.push({ value: d.value, label: d.value, description: `${formatNumber(d.count)}× verwendet`, group: 'In der Bibliothek' })
    }
    if (value && !out.some((o) => o.value === value)) out.push({ value, label: value, group: 'Aktueller Wert' })
    return out
  }, [field.options, distinct.data, value])
  return (
    <Combobox
      id={id}
      options={options}
      value={value || null}
      onValueChange={(v) => {
        const next = v ?? ''
        onChange(next)
        onCommit?.(next)
      }}
      allowCustom
      customLabel={(q) => `„${q}“ übernehmen`}
      clearable
      size={size}
      invalid={invalid}
      disabled={disabled}
      mono={isMono(field)}
      placeholder={placeholder ?? 'Auswählen …'}
      searchPlaceholder={`${field.label} suchen …`}
      emptyText="Keine Treffer – eigenen Wert eingeben"
      className={className}
      aria-label={ariaLabel}
    />
  )
}

const BOOL_EMPTY = '__leer__'

function BoolInput({ value, onChange, onCommit, disabled, 'aria-label': ariaLabel, field, className }: FieldInputProps) {
  const lower = value.trim().toLowerCase()
  const current = ['ja', 'yes', 'true', '1'].includes(lower) ? 'Ja' : ['nein', 'no', 'false', '0'].includes(lower) ? 'Nein' : BOOL_EMPTY
  return (
    <SegmentedControl
      size="sm"
      aria-label={ariaLabel ?? field.label}
      value={current}
      disabled={disabled}
      onValueChange={(v) => {
        const next = v === BOOL_EMPTY ? '' : v
        onChange(next)
        onCommit?.(next)
      }}
      options={[
        { value: 'Ja', label: 'Ja' },
        { value: 'Nein', label: 'Nein' },
        { value: BOOL_EMPTY, label: '–', title: 'Keine Angabe' },
      ]}
      className={className}
    />
  )
}

// --------------------------------------------------------------------------- Symbol / Footprint

const STATUS_LABEL: Record<string, string> = {
  ok: 'synchron',
  pending: 'noch nicht geschrieben',
  missing: 'fehlt in der Datei',
  error: 'Fehler beim Schreiben',
}

/**
 * Vorschaubild als Kachel in der Auswahlliste – im Auslöser (Feld) kleiner. Symbole auf dem App-Hintergrund,
 * Footprints auf der dunklen Leiterplatte.
 */
function RefTile({ children, board }: { children: ReactNode; board?: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'relative flex h-8 w-11 shrink-0 overflow-hidden rounded-md border',
        board ? 'border-white/8 bg-canvas' : 'dot-grid border-line bg-bg',
        '[[role=combobox]_&]:h-5 [[role=combobox]_&]:w-7 [[role=combobox]_&]:rounded-sm',
      )}
    >
      {children}
    </span>
  )
}

function symbolOption(entry: SymbolEntry): ComboboxOption {
  const meta: string[] = []
  if (entry.pin_count) meta.push(`${entry.pin_count} ${entry.pin_count === 1 ? 'Pin' : 'Pins'}`)
  if (entry.part_count > 1) meta.push(`${entry.part_count} Teile`)
  if (entry.usage) meta.push(`${formatNumber(entry.usage)}× verwendet`)
  if (entry.status !== 'ok') meta.push(STATUS_LABEL[entry.status] ?? entry.status)
  return {
    value: entry.name,
    label: entry.name,
    description: meta.join(' · ') || entry.library,
    keywords: [entry.library, entry.kind ?? ''],
    icon: (
      <RefTile>
        <SymbolThumb entry={entry} inset="p-0.5" compact />
      </RefTile>
    ),
  }
}

function footprintOption(entry: FootprintEntry): ComboboxOption {
  const meta: string[] = []
  if (entry.pad_count) meta.push(`${entry.pad_count} ${entry.pad_count === 1 ? 'Pad' : 'Pads'}`)
  if (entry.ipc_name && entry.ipc_name !== entry.name) meta.push(entry.ipc_name)
  if (entry.usage) meta.push(`${formatNumber(entry.usage)}× verwendet`)
  if (entry.status !== 'ok') meta.push(STATUS_LABEL[entry.status] ?? entry.status)
  return {
    value: entry.name,
    label: entry.name,
    description: meta.join(' · ') || entry.library,
    keywords: [entry.library, entry.family ?? '', entry.ipc_name ?? ''],
    icon: (
      <RefTile board>
        <FootprintThumb entry={entry} inset="p-0.5" compact />
      </RefTile>
    ),
  }
}

function RefInput({ kind, ...props }: FieldInputProps & { kind: 'symbol' | 'footprint' }) {
  const symbols = useLibrarySymbols(kind === 'symbol')
  const footprints = useLibraryFootprints(kind === 'footprint')
  const q = kind === 'symbol' ? symbols : footprints
  const options = useMemo<ComboboxOption[]>(() => {
    const list =
      kind === 'symbol'
        ? (symbols.data ?? []).map(symbolOption)
        : (footprints.data ?? []).map(footprintOption)
    if (props.value && !list.some((o) => o.value.toLowerCase() === props.value.toLowerCase())) {
      const icon = kind === 'symbol' ? <SymbolIcon className="size-4 text-fg-subtle" /> : <CircuitBoard className="size-4 text-fg-subtle" />
      list.unshift({ value: props.value, label: props.value, description: 'nicht in der Bibliothek registriert', icon })
    }
    return list
  }, [kind, symbols.data, footprints.data, props.value])

  // Liste nicht ladbar: der Name bleibt als Freitext eintragbar
  if (q.isError && !q.data) return <TextInput {...props} />
  return (
    <Combobox
      id={props.id}
      options={options}
      value={props.value || null}
      onValueChange={(v) => {
        const next = v ?? ''
        props.onChange(next)
        props.onCommit?.(next)
      }}
      allowCustom
      customLabel={(text) => `„${text}“ verwenden (nicht registriert)`}
      clearable
      mono
      size={props.size ?? 'md'}
      invalid={props.invalid}
      disabled={props.disabled}
      placeholder={q.isPending ? 'Bibliothek wird geladen …' : kind === 'symbol' ? 'Symbol wählen …' : 'Footprint wählen …'}
      searchPlaceholder={kind === 'symbol' ? 'Symbol suchen (Name, Typ) …' : 'Footprint suchen (Name, Familie, IPC) …'}
      emptyText="Kein Treffer – Namen eingeben, um ihn zu übernehmen"
      className={props.className}
      contentClassName="w-[min(28rem,calc(100vw-2rem))]"
      aria-label={props['aria-label']}
    />
  )
}
