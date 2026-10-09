/**
 * Massenbearbeitung: ein oder mehrere Felder auf denselben Wert setzen (oder leeren) – mit passender Eingabe je
 * Feldart, für ausgewählte Bauteile oder **alle Treffer** von Suche und Filtern (Anzahl wird beim Öffnen bestätigt;
 * ändern sich die Treffer bis zum Speichern, meldet das Backend es und der Dialog fragt mit der neuen Zahl).
 *
 * Vorschau: an einem betroffenen Bauteil zeigt der Dialog live, wie Wert, Kommentar und Beschreibung aus den Vorlagen
 * neu entstehen. Vorher wird geprüft: Fehler halten an, nicht lesbare Werte („abc“ als Toleranz) ebenfalls – ein
 * zweites „Ändern“ übernimmt sie bewusst. Alles oder nichts: meldet das Backend einen Fehler, ändert sich kein Bauteil.
 * Danach nimmt „Rückgängig“ in der Erfolgsmeldung die Änderung zurück (`audit_ids` → `restore-updates`).
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CircleAlert, Eraser, PencilLine, Plus, RefreshCw, TriangleAlert, X } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { toast } from 'sonner'
import { ApiError, errorMessage } from '@/api/client'
import type { CategoryDef } from '@/api/library'
import {
  fieldErrors,
  partsApi,
  partsKeys,
  selectionChanged,
  usePartsInvalidation,
  type PartFilter,
  type PartRow,
  type PartSelection,
  type SelectionChanged,
} from '@/api/parts'
import {
  Button,
  Callout,
  Combobox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Spinner,
  Tooltip,
  type ComboboxOption,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { FieldInput } from '../components/FieldInput'
import { displayValue, FIELD_GROUPS, GENERATED_TEXTS, groupOf, isEditable, ownWarnings, PN } from '../model/fields'
import { showChangeToast } from '../model/undo'
import { useDebounced } from '../model/useDebounced'

interface Row {
  id: number
  column: string | null
  value: string
  clear: boolean
}

/** Betroffene Bauteile: ausgewählte Teilenummern oder alle Treffer der Abfrage */
export type BulkTarget = { partNumbers: string[] } | { search: string; filters: PartFilter[]; count: number }

export interface BulkUpdateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  category: CategoryDef
  target: BulkTarget
  /** Ein betroffenes Bauteil – daran prüft das Backend die neuen Werte und zeigt die erzeugten Texte */
  sample?: PartRow | null
  onDone?: () => void
}

const TEXT_LABEL: Record<string, string> = { Value: 'Wert', Comment: 'Kommentar', Description: 'Beschreibung' }

let rowCounter = 0
const newRow = (): Row => ({ id: ++rowCounter, column: null, value: '', clear: false })

export function BulkUpdateDialog({ open, onOpenChange, category, target, sample, onDone }: BulkUpdateDialogProps) {
  const table = category.table
  const [rows, setRows] = useState<Row[]>(() => [newRow()])
  const [problems, setProblems] = useState<string[]>([])
  /** Prüfergebnis je Feld (Fehler halten an, Hinweise bis zur Bestätigung) */
  const [checks, setChecks] = useState<{ errors: Record<string, string>; hints: Record<string, string[]>; key: string } | null>(null)
  const [checking, setChecking] = useState(false)
  /** 409 „selection_changed“ – neue Zahl bestätigen */
  const [changed, setChanged] = useState<SelectionChanged | null>(null)
  const qc = useQueryClient()
  const invalidate = usePartsInvalidation()
  const fields = useMemo(() => new Map(category.fields.map((f) => [f.column, f])), [category])
  const groupLabel = useMemo(() => new Map(FIELD_GROUPS.map((g) => [g.id, g.label])), [])
  const fieldOptions = useMemo<ComboboxOption[]>(
    () =>
      category.fields
        .filter((f) => isEditable(f) && f.column !== PN)
        .map((f) => ({
          value: f.column,
          label: f.label,
          description: f.unit ? `${f.column} · ${f.unit}` : f.column !== f.label ? f.column : undefined,
          keywords: [f.column],
          group: groupLabel.get(groupOf(f)),
        })),
    [category, groupLabel],
  )

  /** Je Öffnen eine eigene Zählung (Schlüssel) – nie die Zahl eines früheren Öffnens aus dem Cache */
  const [opening, setOpening] = useState(0)
  /** Beim Öffnen festgehaltene Trefferzahl (null = wird gezählt) */
  const [captured, setCaptured] = useState<number | null>(null)

  // Beim Öffnen neu beginnen (abgeleiteter Zustand)
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setRows([newRow()])
      setProblems([])
      setChecks(null)
      setChanged(null)
      setCaptured(null)
      setOpening((n) => n + 1)
    }
  }

  // Alle Treffer: Anzahl einmal beim Öffnen frisch zählen und festhalten (Grundlage für expected_count). Danach ändert
  // sie sich nur über die Rückfrage nach einem 409 „selection_changed“ – nie still, weil währenddessen etwas die
  // Bauteile neu lädt (z. B. ein Import, der im Hintergrund endet). Die Abfrage liegt darum nicht unter
  // ['parts', table] (dort lädt jede Änderung neu), ist nach dem Festhalten abgeschaltet und `static` (Job-Abschluss).
  const byQuery = 'search' in target
  const counted = useQuery({
    queryKey: ['parts', 'bulk-count', table, opening, byQuery ? target.search : '', byQuery ? target.filters : []] as const,
    queryFn: ({ signal }) => partsApi.count(table, byQuery ? { search: target.search, filters: target.filters, sample: 0 } : {}, signal),
    enabled: open && byQuery && captured === null,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    meta: { static: true },
  })
  if (open && byQuery && captured === null && counted.data) setCaptured(counted.data.count)
  /** Zählung läuft noch (Ändern erst danach – sonst ginge die ungeprüfte Zahl der Tabelle ans Backend) */
  const counting = byQuery && captured === null && !counted.isError
  const confirmedCount = changed?.count ?? (byQuery ? (captured ?? target.count) : target.partNumbers.length)
  const selection: PartSelection = byQuery
    ? { search: target.search, filters: target.filters, expectedCount: confirmedCount }
    : { partNumbers: target.partNumbers }

  const values = useMemo(() => {
    const out: Record<string, string | null> = {}
    for (const r of rows) if (r.column && (r.clear || r.value.trim())) out[r.column] = r.clear ? null : r.value.trim()
    return out
  }, [rows])
  const changeCount = Object.keys(values).length

  // Live-Vorschau der erzeugten Texte am Beispielbauteil
  const samplePn = sample ? String(sample[PN] ?? '') : ''
  const debouncedValues = useDebounced(values, 350)
  const preview = useQuery({
    queryKey: [...partsKeys.table(table), 'bulk-preview', samplePn, debouncedValues] as const,
    queryFn: ({ signal }) => partsApi.validate(table, debouncedValues, { partNumber: samplePn, signal }),
    enabled: open && Boolean(samplePn) && Object.keys(debouncedValues).length > 0,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: false,
  })
  const textChanges = useMemo(() => {
    if (!sample || !preview.data || !Object.keys(debouncedValues).length) return []
    return GENERATED_TEXTS.filter((col) => fields.has(col) && !(col in debouncedValues))
      .map((col) => ({ col, before: sample[col] ?? '', after: preview.data.values[col] ?? '' }))
      .filter((c) => c.before !== c.after)
  }, [sample, preview.data, debouncedValues, fields])

  const save = useMutation({
    mutationFn: (sel: PartSelection) => partsApi.bulkUpdate(table, sel, values),
    meta: { silentError: true },
    onSuccess: (res) => {
      invalidate(table, { counts: false })
      if (res.updated === 0) toast.success('Keine Änderung nötig', { description: 'Alle Bauteile hatten die Werte bereits.' })
      else showChangeToast(qc, table, res, `${plural(res.updated, 'Bauteil', 'Bauteile')} geändert`)
      if (res.warnings.length) {
        toast.warning('Bitte prüfen', { description: res.warnings.slice(0, 4).join(' · ') + (res.warnings.length > 4 ? ' …' : '') })
      }
      onOpenChange(false)
      onDone?.()
    },
    onError: (err) => {
      const moved = selectionChanged(err)
      if (moved) {
        setChanged(moved)
        setProblems([])
        return
      }
      const errs = fieldErrors(err)
      const list = Object.entries(errs).map(([k, v]) => `${fields.get(k)?.label ?? k}: ${v}`)
      setProblems(list.length ? list : [errorMessage(err)])
      if (!(err instanceof ApiError)) toast.error('Massenbearbeitung fehlgeschlagen', { description: errorMessage(err) })
    },
  })

  const update = (id: number, change: Partial<Row>) => {
    setProblems([])
    setChecks(null)
    setRows((rs) => rs.map((r) => (r.id === id ? { ...r, ...change } : r)))
  }
  const used = new Set(rows.map((r) => r.column).filter(Boolean))
  const valuesKey = JSON.stringify(values)
  const confirmed = checks !== null && checks.key === valuesKey && Object.keys(checks.errors).length === 0

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!changeCount || save.isPending || checking || confirmedCount === 0 || counting) return
    // zweites „Ändern“ nach den Hinweisen (bzw. nach geänderter Trefferzahl): so übernehmen
    if (confirmed || changed) {
      save.mutate(selection)
      return
    }
    if (samplePn) {
      setChecking(true)
      try {
        const res = await partsApi.validate(table, values, { partNumber: samplePn })
        const errors = Object.fromEntries(Object.entries(res.errors).filter(([col]) => col in values))
        const hints: Record<string, string[]> = {}
        for (const col of Object.keys(values)) {
          const field = fields.get(col)
          const own = field ? ownWarnings(field, res.warnings) : []
          if (own.length) hints[col] = own
        }
        if (Object.keys(errors).length || Object.keys(hints).length) {
          setChecks({ errors, hints, key: valuesKey })
          return
        }
      } catch {
        // Prüfung nicht möglich – das Speichern meldet Fehler selbst
      } finally {
        setChecking(false)
      }
    }
    save.mutate(selection)
  }

  const countText = plural(confirmedCount, 'Bauteil', 'Bauteile')
  /** „bei allen 240 Treffern“ / „bei 3 Bauteilen“ / „bei dem Bauteil“ */
  const scopeDative =
    confirmedCount === 1
      ? 'bei dem Bauteil'
      : byQuery
        ? `bei allen ${formatNumber(confirmedCount)} Treffern`
        : `bei ${plural(confirmedCount, 'Bauteil', 'Bauteilen')}`

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <form onSubmit={(e) => void submit(e)} className="flex min-h-0 flex-1 flex-col">
          <DialogHeader
            icon={<PencilLine />}
            title={byQuery ? `Alle ${formatNumber(confirmedCount)} Treffer bearbeiten` : `${countText} bearbeiten`}
            description={`Gewählte Felder werden ${scopeDative} in „${category.label}“ auf denselben Wert gesetzt. Wert, Kommentar und Beschreibung passen sich automatisch an.`}
          />
          <DialogBody className="flex flex-col gap-3">
            {byQuery && (
              <p className="flex items-center gap-2 text-xs text-fg-muted" aria-live="polite">
                {counting ? <Spinner size={12} tone="accent" /> : <RefreshCw aria-hidden className="size-3.5 text-fg-subtle" />}
                {counting
                  ? 'Treffer werden gezählt …'
                  : `Gilt für alle ${formatNumber(confirmedCount)} Treffer von Suche und Filtern – auch für Zeilen, die die Tabelle noch nicht geladen hat.`}
              </p>
            )}
            <ul className="flex flex-col gap-2">
              {rows.map((r) => {
                const field = r.column ? fields.get(r.column) : undefined
                return (
                  <li key={r.id} className="grid grid-cols-[minmax(0,14rem)_minmax(0,1fr)_auto_auto] items-start gap-2">
                    <Combobox
                      options={fieldOptions.map((o) => ({ ...o, disabled: o.value !== r.column && used.has(o.value) }))}
                      value={r.column}
                      onValueChange={(column) => update(r.id, { column, value: '', clear: false })}
                      placeholder="Feld wählen …"
                      searchPlaceholder="Feld suchen …"
                      aria-label="Feld"
                    />
                    {field ? (
                      r.clear ? (
                        <div className="flex h-8.5 items-center rounded-button border border-dashed border-line-strong px-3 text-ui text-fg-muted">
                          Feld wird geleert
                        </div>
                      ) : (
                        <FieldInput
                          field={field}
                          table={table}
                          value={r.value}
                          onChange={(value) => update(r.id, { value })}
                          aria-label={`Neuer Wert für ${field.label}`}
                        />
                      )
                    ) : (
                      <div className="flex h-8.5 items-center px-1 text-ui text-fg-subtle">← zuerst ein Feld wählen</div>
                    )}
                    <Tooltip content={r.clear ? 'Doch einen Wert setzen' : 'Feld leeren'}>
                      <Button
                        variant="ghost"
                        iconOnly
                        aria-pressed={r.clear}
                        aria-label={`${field?.label ?? 'Feld'} leeren`}
                        disabled={!field || field.required}
                        onClick={() => update(r.id, { clear: !r.clear })}
                        className={cn(r.clear && 'bg-accent-soft text-accent-text')}
                      >
                        <Eraser />
                      </Button>
                    </Tooltip>
                    <Button
                      variant="ghost"
                      iconOnly
                      aria-label="Zeile entfernen"
                      disabled={rows.length === 1}
                      onClick={() => setRows((rs) => rs.filter((x) => x.id !== r.id))}
                    >
                      <X />
                    </Button>
                    {r.column && checks?.key === valuesKey && (checks.errors[r.column] || checks.hints[r.column]) && (
                      <p
                        role="alert"
                        className={cn(
                          'col-start-2 col-end-5 flex items-start gap-1.5 text-xs leading-snug',
                          checks.errors[r.column] ? 'text-danger-text' : 'text-warning-text',
                        )}
                      >
                        {checks.errors[r.column] ? (
                          <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                        ) : (
                          <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                        )}
                        <span>
                          {checks.errors[r.column] ?? checks.hints[r.column]?.join(' ')}
                          {!checks.errors[r.column] && <span className="text-fg-muted"> – erneut „Ändern“ übernimmt den Wert trotzdem.</span>}
                        </span>
                      </p>
                    )}
                  </li>
                )
              })}
            </ul>
            <div>
              <Button variant="ghost" size="sm" leftIcon={<Plus />} onClick={() => setRows((rs) => [...rs, newRow()])}>
                Weiteres Feld
              </Button>
            </div>
            {changeCount > 0 && (
              <div className="overflow-hidden rounded-button border border-line bg-surface-2/50 text-xs text-fg-muted" aria-live="polite">
                <p className="px-3 py-2">
                  Setzt{' '}
                  {Object.entries(values).map(([col, v], i) => (
                    <span key={col}>
                      {i > 0 && ', '}
                      <span className="font-medium text-fg">{fields.get(col)?.label ?? col}</span>{' '}
                      {v === null ? (
                        'auf leer'
                      ) : (
                        <>
                          = <span className="mono text-fg">{displayValue(fields.get(col), v)}</span>
                        </>
                      )}
                    </span>
                  ))}{' '}
                  {scopeDative}.
                </p>
                {samplePn && (textChanges.length > 0 || preview.isFetching) && (
                  <div className="border-t border-line px-3 py-2">
                    <div className="mb-1 flex items-center gap-2">
                      <span className="micro-label">Vorschau</span>
                      <span className="mono text-2xs text-fg-subtle">{samplePn}</span>
                      {preview.isFetching && <Spinner size={11} />}
                    </div>
                    <dl className="flex flex-col gap-1">
                      {textChanges.map((c) => (
                        <div key={c.col} className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-baseline gap-2">
                          <dt className="text-fg-subtle">{TEXT_LABEL[c.col] ?? c.col}</dt>
                          <dd className="flex min-w-0 flex-wrap items-baseline gap-x-1.5">
                            {c.before && <span className="mono break-words text-fg-subtle line-through decoration-fg-subtle/50">{c.before}</span>}
                            <ArrowRight aria-label="wird zu" className="size-3 shrink-0 self-center text-accent" />
                            <span className="mono break-words text-fg">{c.after || '–'}</span>
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                )}
              </div>
            )}
            {changed && (
              <Callout tone="warning" title="Die Treffer haben sich geändert" urgent>
                Inzwischen passen {plural(changed.count, 'Bauteil', 'Bauteile')} statt {formatNumber(changed.expected)} zu Suche und Filtern
                (jemand hat Bauteile angelegt, geändert oder gelöscht). Erneut „Ändern“ übernimmt die Werte für alle{' '}
                {formatNumber(changed.count)}.
              </Callout>
            )}
            {problems.length > 0 && (
              <Callout tone="danger" title="Nicht gespeichert – kein Bauteil wurde geändert" urgent>
                <ul className="mt-1 flex flex-col gap-0.5">
                  {problems.slice(0, 8).map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                  {problems.length > 8 && <li>… und {formatNumber(problems.length - 8)} weitere</li>}
                </ul>
              </Callout>
            )}
          </DialogBody>
          <DialogFooter>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Abbrechen
            </Button>
            <Button
              type="submit"
              variant="primary"
              loading={save.isPending || checking}
              disabled={!changeCount || confirmedCount === 0 || counting}
            >
              {!changeCount
                ? 'Ändern'
                : changed
                  ? `${formatNumber(changed.count)} ändern`
                  : confirmed
                    ? 'Trotzdem ändern'
                    : `${countText} ändern`}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
