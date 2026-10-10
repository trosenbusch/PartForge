import { metadataLabel, localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Zelleneditor der Bauteiltabelle (Popup über der Zelle): Eingabe mit Vorschlägen je Feldart (Auswahllisten,
 * Ja/Nein, Symbole/Footprints der Bibliothek, vorhandene Werte), Einheit als Suffix und **Prüfung vor dem
 * Übernehmen**: Enter (oder Tab) fragt `POST /validate`. Fehler erscheinen direkt unter der Eingabe, der Editor
 * bleibt offen. Kann das Backend den Wert nicht lesen („abc“ als Toleranz), ist das ebenfalls ein Halt: der Hinweis
 * steht unter der Eingabe, ein **zweites Enter** übernimmt den Wert trotzdem. Esc bricht ab.
 */
import type { CustomCellEditorProps } from 'ag-grid-react'
import { CircleAlert, CornerDownLeft, TriangleAlert } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { FieldDef } from '@/api/library'
import {
  PART_NUMBER,
  partsApi,
  useDistinctValues,
  useLibraryFootprints,
  useLibrarySymbols,
  type PartRow,
} from '@/api/parts'
import { errorMessage } from '@/api/client'
import { useSaveHandler } from '@/app/commands'
import { Kbd, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { isMono, ownWarnings, placeholderFor } from '../model/fields'

export interface PartCellEditorParams {
  field: FieldDef
  table: string
}

/** Spalten, für die vorhandene Werte als Vorschläge angeboten werden */
const DISTINCT_SUGGESTIONS = new Set(['Manufacturer', 'Package', 'Supplier 1', 'Supplier 2', 'Mounting', 'Size', 'Series'])
const MAX_OPTIONS = 60

function useEditorOptions(field: FieldDef, table: string): string[] {
  useI18n()
  const isSymbol = field.column === 'Library Ref'
  const isFootprint = /^Footprint Ref( \d+)?$/.test(field.column)
  const symbols = useLibrarySymbols(isSymbol)
  const footprints = useLibraryFootprints(isFootprint)
  const wantsDistinct = DISTINCT_SUGGESTIONS.has(field.column) || field.kind === 'enum'
  const distinct = useDistinctValues(table, field.column, wantsDistinct)
  return useMemo(() => {
    if (isSymbol) return (symbols.data ?? []).map((s) => s.name)
    if (isFootprint) return (footprints.data ?? []).map((f) => f.name)
    if (field.kind === 'bool') return ['Ja', 'Nein']
    const out = [...field.options]
    for (const d of distinct.data ?? []) if (!out.some((o) => o.toLowerCase() === d.value.toLowerCase())) out.push(d.value)
    return out
  }, [isSymbol, isFootprint, symbols.data, footprints.data, field.kind, field.options, distinct.data])
}

export function PartCellEditor(props: CustomCellEditorProps<PartRow, string | null> & PartCellEditorParams) {
  const { t } = useI18n()
  // `value` ist der laufende Editorwert (kontrolliert), `initialValue` der gespeicherte Wert
  const { field, table, initialValue, onValueChange, stopEditing, eventKey, data, eGridCell } = props
  const stored = initialValue ?? ''
  const uid = useId().replace(/:/g, '')
  const startedByChar = Boolean(eventKey && eventKey.length === 1)
  const [text, setText] = useState<string>(() => (startedByChar ? (eventKey as string) : stored))
  const [error, setError] = useState<string | null>(null)
  /** Hinweis des Backends zu diesem Feld – hält an, bis der Wert geändert oder bestätigt wird */
  const [warning, setWarning] = useState<{ text: string; value: string } | null>(null)
  const [checking, setChecking] = useState(false)
  const [active, setActive] = useState(-1)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const options = useEditorOptions(field, table)
  const width = Math.max(eGridCell?.offsetWidth ?? 0, field.column === 'Description' ? 420 : 300)
  const pn = data?.[PART_NUMBER] ?? ''

  // AG Grid legt den Editor in einen eigenen Popup-Rahmen mit role="dialog", aber ohne Namen – den Namen
  // („Beschreibung bearbeiten – CRCW…“) hier nachtragen, damit Screenreader sagen, was bearbeitet wird
  useEffect(() => {
    const popup = rootRef.current?.closest<HTMLElement>('.ag-popup-editor')
    if (!popup) return
    popup.setAttribute('aria-label', pn ? t("{1} bearbeiten – {2}", { 1: metadataLabel(field.label, t), 2: pn }) : t("{1} bearbeiten", { 1: metadataLabel(field.label, t) }))
  }, [field.label, pn, t])

  // Fokus + Auswahl beim Öffnen (beim Start per Taste bleibt die Schreibmarke hinter dem Zeichen)
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.focus({ preventScroll: true })
    if (startedByChar) el.setSelectionRange(el.value.length, el.value.length)
    else el.select()
  }, [startedByChar])

  const query = text.trim().toLowerCase()
  const filtered = useMemo(() => {
    if (!options.length) return []
    const exact = options.some((o) => o.toLowerCase() === query)
    const list = !query || exact ? options : options.filter((o) => (o.toLowerCase().includes(query) || metadataLabel(o, t).toLowerCase().includes(query)))
    return list.slice(0, MAX_OPTIONS)
  }, [options, query, t])

  // aktiven Vorschlag sichtbar halten
  useEffect(() => {
    if (active < 0) return
    listRef.current?.querySelector<HTMLElement>(`[data-index="${active}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [active])

  const update = (next: string) => {
    setText(next)
    setError(null)
    setWarning(null)
    setActive(-1)
    onValueChange(next.trim() === '' ? null : next)
  }

  /** nach dem Rendern übernehmen, damit AG Grid den neuen Wert liest */
  const finish = () => window.setTimeout(() => stopEditing(), 0)

  const commit = async (raw: string) => {
    const next = raw.trim()
    const before = stored.trim()
    onValueChange(next === '' ? null : next)
    if (next === before) {
      stopEditing()
      return
    }
    // zweites Enter nach dem Hinweis: bewusst so übernehmen
    if (warning && warning.value === next) {
      finish()
      return
    }
    setChecking(true)
    try {
      const res = await partsApi.validate(table, { [field.column]: next === '' ? null : next }, { partNumber: pn || null })
      const problem = res.errors[field.column] ?? Object.values(res.errors)[0]
      if (problem) {
        setError(problem)
        inputRef.current?.focus()
        return
      }
      const own = ownWarnings(field, res.warnings)
      if (own.length) {
        setWarning({ text: own.join(' '), value: next })
        inputRef.current?.focus()
        return
      }
      finish()
    } catch (err) {
      // Prüfung nicht möglich (z. B. Netzwerk) → übernehmen; das Speichern meldet Fehler selbst
      if (import.meta.env.DEV) console.warn(t("Prüfung fehlgeschlagen"), errorMessage(err))
      finish()
    } finally {
      setChecking(false)
    }
  }

  // Strg+S übernimmt wie Enter (mit Prüfung) – die Shell fängt die Taste ab, dieser Handler ist der zuletzt eingehängte
  useSaveHandler(() => {
    if (!checking) void commit(text)
  })

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' && filtered.length) {
      e.preventDefault()
      setActive((i) => (i + 1) % filtered.length)
    } else if (e.key === 'ArrowUp' && filtered.length) {
      e.preventDefault()
      setActive((i) => (i <= 0 ? filtered.length - 1 : i - 1))
    } else if (e.key === 'Enter' || e.key === 'Tab') {
      // Tab übernimmt wie Enter (mit Prüfung) – die Tabelle selbst verlässt man mit Tab erst danach
      e.preventDefault()
      const picked = e.key === 'Enter' && active >= 0 ? filtered[active] : undefined
      if (picked !== undefined) setText(picked)
      void commit(picked ?? text)
    }
  }

  const listId = `${uid}-list`
  const msgId = `${uid}-msg`
  return (
    <div
      ref={rootRef}
      className={cn(
        'pf-cell-editor overflow-hidden rounded-control border bg-surface text-fg shadow-pop',
        error ? 'border-danger' : warning ? 'border-warning' : 'border-accent',
      )}
      style={{ width }}
    >
      <div className="flex h-[30px] items-center gap-2 pl-2.5 pr-2">
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => update(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={placeholderFor(field)}
          aria-label={metadataLabel(field.label, t)}
          aria-invalid={error || warning ? true : undefined}
          aria-describedby={error || warning ? msgId : undefined}
          role={filtered.length ? 'combobox' : undefined}
          aria-expanded={filtered.length ? true : undefined}
          aria-controls={filtered.length ? listId : undefined}
          aria-activedescendant={active >= 0 ? `${uid}-opt-${active}` : undefined}
          aria-autocomplete={filtered.length ? 'list' : undefined}
          spellCheck={false}
          className={cn(
            'h-full min-w-0 flex-1 bg-transparent text-ui text-fg outline-none placeholder:text-fg-subtle',
            isMono(field) && 'mono text-xs',
          )}
        />
        {field.unit && <span className="shrink-0 text-2xs text-fg-subtle">{field.unit}</span>}
        {checking ? (
          <Spinner size={13} tone="accent" />
        ) : (
          <CornerDownLeft aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
        )}
      </div>
      {error ? (
        <p id={msgId} role="alert" className="flex items-start gap-1.5 border-t border-danger/25 bg-danger/8 px-2.5 py-1.5 text-xs leading-snug text-danger-text">
          <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
          <span>{localizeMessage(error)}</span>
        </p>
      ) : warning ? (
        <div id={msgId} role="alert" className="flex flex-col gap-1 border-t border-warning/30 bg-warning/8 px-2.5 py-1.5 text-xs leading-snug">
          <p className="flex items-start gap-1.5 text-warning-text">
            <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
            <span>{localizeMessage(warning.text)}</span>
          </p>
          <p className="pl-5 text-fg-muted">
            {t("Nicht gespeichert. Korrigieren – oder")}{' '}
            <button
              type="button"
              onPointerDown={(e) => {
                e.preventDefault()
                void commit(warning.value)
              }}
              className="rounded-sm font-medium text-fg underline underline-offset-2 outline-none hover:text-accent-text focus-ring"
            >
              {t("trotzdem übernehmen")}
            </button>{' '}
            {t("(Enter). Esc bricht ab.")}
          </p>
        </div>
      ) : null}
      {filtered.length > 0 && (
        <div
          ref={listRef}
          id={listId}
          role="listbox"
          aria-label={t("{1} – Vorschläge", { 1: metadataLabel(field.label, t) })}
          className="max-h-56 overflow-y-auto border-t border-line p-1"
        >
          {filtered.map((opt, i) => (
            <div
              key={opt}
              id={`${uid}-opt-${i}`}
              data-index={i}
              role="option"
              aria-selected={i === active}
              onPointerDown={(e) => {
                e.preventDefault()
                setText(opt)
                void commit(opt)
              }}
              onPointerEnter={() => setActive(i)}
              className={cn(
                'flex h-7 cursor-default items-center gap-2 truncate rounded-md px-2 text-ui',
                i === active ? 'bg-[color-mix(in_oklab,var(--pf-fg)_8%,transparent)] text-fg' : 'text-fg-muted',
                opt.toLowerCase() === stored.toLowerCase() && 'font-medium text-fg',
                isMono(field) && 'mono text-xs',
              )}
            >
              <span className="truncate">{field.kind === 'bool' || (field.kind === 'enum' && field.options.includes(opt)) ? metadataLabel(opt, t) : opt}</span>
            </div>
          ))}
        </div>
      )}
      {!warning && (
        <div className="flex items-center justify-between gap-3 overflow-hidden whitespace-nowrap border-t border-line bg-surface-2/60 px-2.5 py-1 text-2xs text-fg-subtle">
          <span className="flex min-w-0 items-center gap-1 truncate">
            <Kbd size="xs">Enter</Kbd>  {t("übernehmen")}
            <span aria-hidden className="px-0.5">
              ·
            </span>
            <Kbd size="xs">Esc</Kbd>  {t("abbrechen")}
          </span>
          {field.kind === 'enum' && <span className="shrink-0 truncate">{t("auch freie Eingabe")}</span>}
        </div>
      )}
    </div>
  )
}
