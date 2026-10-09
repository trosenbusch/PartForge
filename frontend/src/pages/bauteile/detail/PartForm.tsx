/**
 * Parameter eines Bauteils, gruppiert (Allgemein, Werte, Altium, Beschaffung, Verwaltung) mit Eingaben je Feldart.
 * **Speichern sofort** beim Verlassen eines Felds, mit Enter oder bei einer Auswahl (`PATCH`) – aber erst nach der
 * Prüfung (`POST validate`): Fehler halten an, und ein Wert, den das Backend nicht lesen kann („zehn Prozent“ als
 * Toleranz), wird ebenfalls **nicht** gespeichert. Der Hinweis steht am Feld; ein zweites Enter oder „Trotzdem
 * speichern“ übernimmt den Wert bewusst. Esc verwirft. Vom Backend neu erzeugte Werte (Beschreibung, Kommentar …)
 * leuchten kurz auf.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { ChevronRight, CircleAlert, ExternalLink, FolderOpen, Lock, RefreshCw, TriangleAlert, Wand } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import type { CategoryDef, FieldDef } from '@/api/library'
import { fieldErrors, partsApi, PART_NUMBER, partsKeys, type PartRow } from '@/api/parts'
import { useSaveHandler } from '@/app/commands'
import { useWorkspace } from '@/api/system'
import { Button, confirm, IconButton, Spinner, Tooltip } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatRelativeTime } from '@/lib/format'
import { readPref, writePref } from '@/lib/prefs'
import { revealPath } from '@/lib/native'
import { FieldInput } from '../components/FieldInput'
import {
  BOOKKEEPING,
  DATASHEET,
  displayValue,
  GENERATED_TEXTS,
  groupFields,
  groupOf,
  otherWarnings,
  ownWarnings,
  parseDateText,
  type FieldGroupId,
} from '../model/fields'
import { openDatasheet, pathLabel, resolveLibraryPath } from '../model/links'
import { showChangeToast } from '../model/undo'

const COLLAPSED_PREF = 'pf-bauteile-gruppen'
/** Zeitstempel für die Statuszeile (außerhalb des Renderns aufgerufen) */
const now = () => Date.now()
const DEFAULT_COLLAPSED: FieldGroupId[] = ['beschaffung', 'verwaltung']

function readCollapsed(): Set<FieldGroupId> {
  try {
    const raw = readPref(COLLAPSED_PREF)
    return new Set(raw ? (JSON.parse(raw) as FieldGroupId[]) : DEFAULT_COLLAPSED)
  } catch {
    return new Set(DEFAULT_COLLAPSED)
  }
}

const fieldDomId = (column: string) => `pf-field-${column.replace(/[^a-z0-9]+/gi, '-')}`

export interface PartFormProps {
  category: CategoryDef
  row: PartRow
  /** Gespeichert: neue Zeile (ggf. mit neuer Teilenummer) */
  onSaved: (row: PartRow, previousPn: string) => void
  /** Speichern läuft / zuletzt gespeichert (für die Statuszeile) */
  onStatus?: (status: { saving: boolean; savedAt: number | null }) => void
  /** Feld aufklappen und fokussieren (z. B. „Datenblatt hinzufügen“) – neuer `nonce` = erneut */
  focusRequest?: { column: string; nonce: number } | null
}

export function PartForm({ category, row, onSaved, onStatus, focusRequest }: PartFormProps) {
  const qc = useQueryClient()
  const table = category.table
  const pn = String(row[PART_NUMBER] ?? '')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [hints, setHints] = useState<Record<string, string[]>>({})
  /** Wert je Feld, der wegen eines Hinweises nicht gespeichert wurde (zweites Enter = trotzdem) */
  const [held, setHeld] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const [flash, setFlash] = useState<Set<string>>(new Set())
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const groups = useMemo(() => groupFields(category.fields), [category])
  const validateTimer = useRef<number | undefined>(undefined)
  const validateAbort = useRef<AbortController | null>(null)
  useEffect(
    () => () => {
      window.clearTimeout(validateTimer.current)
      validateAbort.current?.abort()
    },
    [],
  )

  // Texte aus den Vorlagen – zeigt, ob Beschreibung/Kommentar/Wert manuell abweichen
  const rendered = useQuery({
    queryKey: [...partsKeys.detail(table, pn), 'rendered', row] as const,
    queryFn: ({ signal }) => partsApi.renderTemplates(table, row, signal),
    staleTime: 60_000,
    enabled: Boolean(pn),
  })

  const toggleGroup = (id: FieldGroupId) => {
    const next = new Set(collapsed)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    writePref(COLLAPSED_PREF, JSON.stringify([...next]))
    setCollapsed(next)
  }

  // Feld von außen ansteuern: Gruppe aufklappen (ohne die gespeicherte Vorliebe zu ändern), dann fokussieren
  const [handledRequest, setHandledRequest] = useState<number | null>(null)
  if (focusRequest && focusRequest.nonce !== handledRequest) {
    setHandledRequest(focusRequest.nonce)
    const field = category.fields.find((f) => f.column === focusRequest.column)
    const group = field ? groupOf(field) : null
    if (group && collapsed.has(group)) {
      setCollapsed((prev) => {
        const next = new Set(prev)
        next.delete(group)
        return next
      })
    }
  }
  useEffect(() => {
    if (!focusRequest) return
    const t = window.setTimeout(() => {
      const el = document.getElementById(fieldDomId(focusRequest.column))
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      el?.focus({ preventScroll: true })
    }, 220)
    return () => window.clearTimeout(t)
  }, [focusRequest])

  const valueOf = (col: string) => drafts[col] ?? row[col] ?? ''

  const clearField = (col: string) => {
    setDrafts((d) => omit(d, col))
    setErrors((e) => omit(e, col))
    setHints((h) => omit(h, col))
    setHeld((h) => omit(h, col))
  }

  const liveValidate = (field: FieldDef, value: string) => {
    window.clearTimeout(validateTimer.current)
    validateAbort.current?.abort()
    if (value === (row[field.column] ?? '')) {
      setErrors((e) => omit(e, field.column))
      setHints((h) => omit(h, field.column))
      return
    }
    validateTimer.current = window.setTimeout(() => {
      const controller = new AbortController()
      validateAbort.current = controller
      partsApi
        .validate(table, { [field.column]: value || null }, { partNumber: pn, signal: controller.signal })
        .then((res) => {
          const err = res.errors[field.column]
          setErrors((e) => (err ? { ...e, [field.column]: err } : omit(e, field.column)))
          const own = ownWarnings(field, res.warnings)
          const conflict = field.column === PART_NUMBER && res.conflict ? [res.conflict.message] : []
          setHints((h) => (own.length || conflict.length ? { ...h, [field.column]: [...conflict, ...own] } : omit(h, field.column)))
        })
        .catch(() => {
          // abgebrochen oder Netzwerk – Speichern prüft ohnehin
        })
    }, 380)
  }

  const save = async (field: FieldDef, value: string, force = false) => {
    const col = field.column
    const before = row[col] ?? ''
    const next = value.trim()
    if (value === before || next === before.trim()) {
      clearField(col)
      return
    }
    window.clearTimeout(validateTimer.current)
    validateAbort.current?.abort()
    // Prüfen vor dem Speichern: Fehler halten an – Hinweise zu genau diesem Feld auch, bis zur Bestätigung
    if (!force && held[col] !== next) {
      try {
        const res = await partsApi.validate(table, { [col]: next || null }, { partNumber: pn })
        const err = res.errors[col] ?? Object.values(res.errors)[0]
        if (err) {
          setErrors((e) => ({ ...e, [col]: err }))
          return
        }
        const own = ownWarnings(field, res.warnings)
        if (own.length) {
          setHints((h) => ({ ...h, [col]: own }))
          setHeld((h) => ({ ...h, [col]: next }))
          return
        }
      } catch {
        // Prüfung nicht möglich – das Speichern meldet Fehler selbst
      }
    }
    if (col === PART_NUMBER) {
      const ok = await confirm({
        title: 'Teilenummer ändern?',
        description: `Schaltpläne, die „${before}“ bereits verwenden, finden das Bauteil danach nicht mehr über die Datenbank-Bibliothek. Neue Teilenummer: „${next}“.`,
        confirmLabel: 'Ändern',
      })
      if (!ok) {
        clearField(col)
        return
      }
    }
    setSaving(col)
    onStatus?.({ saving: true, savedAt: null })
    try {
      const res = await partsApi.update(table, pn, { [col]: next === '' ? null : next })
      const changed = Object.keys(res.part).filter(
        (c) => c !== col && !BOOKKEEPING.has(c) && (row[c] ?? null) !== (res.part[c] ?? null),
      )
      clearField(col)
      if (changed.length) {
        setFlash(new Set(changed))
        window.setTimeout(() => setFlash(new Set()), 1400)
      }
      onSaved(res.part, pn)
      onStatus?.({ saving: false, savedAt: now() })
      // Hinweise zu diesem Feld wurden bestätigt – nur die übrigen melden (z. B. zu lange Beschreibung)
      const rest = otherWarnings([field], res.warnings)
      if (rest.length) toast.warning(`${field.label} gespeichert – bitte prüfen`, { description: rest.join(' · ') })
    } catch (err) {
      const msg = fieldErrors(err)[col] ?? Object.values(fieldErrors(err))[0] ?? errorMessage(err)
      setErrors((e) => ({ ...e, [col]: msg }))
      onStatus?.({ saving: false, savedAt: null })
    } finally {
      setSaving(null)
    }
  }

  // Strg+S: offene Eingaben jetzt speichern (sonst beim Verlassen des Felds bzw. mit Enter) – mit derselben Prüfung
  const pendingDrafts = Object.keys(drafts).length > 0
  useSaveHandler(
    () => {
      for (const [col, value] of Object.entries(drafts)) {
        const field = category.fields.find((f) => f.column === col)
        if (field) void save(field, value)
      }
    },
    { enabled: pendingDrafts && saving === null },
  )

  const regenerate = async () => {
    try {
      const res = await partsApi.regenerateTexts(table, [pn])
      const fresh = await partsApi.get(table, pn)
      onSaved(fresh, pn)
      if (res.updated) showChangeToast(qc, table, res, 'Texte aus den Vorlagen erzeugt')
      else toast.success('Texte entsprechen bereits den Vorlagen')
    } catch (err) {
      toast.error('Texte konnten nicht erzeugt werden', { description: errorMessage(err) })
    }
  }

  return (
    <div className="flex flex-col gap-1">
      {groups.map((g) => {
        const open = !collapsed.has(g.id)
        const filled = g.fields.filter((f) => (row[f.column] ?? '') !== '').length
        const groupErrors = g.fields.filter((f) => errors[f.column]).length
        const groupHeld = g.fields.filter((f) => f.column in held).length
        return (
          <section key={g.id} aria-labelledby={`grp-${g.id}`} className="border-b border-line last:border-b-0">
            <h3 id={`grp-${g.id}`}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => toggleGroup(g.id)}
                className="group/grp flex h-9 w-full items-center gap-2 rounded-control px-1 text-left outline-none focus-ring-inset"
              >
                <ChevronRight aria-hidden className={cn('size-3.5 text-fg-subtle transition-transform duration-150', open && 'rotate-90')} />
                <span className="micro-label flex-1 text-fg-muted group-hover/grp:text-fg">{g.label}</span>
                {groupErrors > 0 ? (
                  <CircleAlert aria-label="Fehler" className="size-3.5 text-danger-text" />
                ) : groupHeld > 0 ? (
                  <TriangleAlert aria-label="Nicht gespeichert" className="size-3.5 text-warning-text" />
                ) : null}
                <span className="mono text-2xs tabular-nums text-fg-subtle">
                  {filled}/{g.fields.length}
                </span>
              </button>
            </h3>
            <AnimatePresence initial={false}>
              {open && (
                <motion.div
                  key="body"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                  className="overflow-hidden"
                >
                  <div className="flex flex-col gap-2 pb-3 pl-1 pt-0.5">
                    {g.fields.map((field) => (
                      <FieldRow
                        key={field.column}
                        field={field}
                        table={table}
                        row={row}
                        value={valueOf(field.column)}
                        dirty={field.column in drafts}
                        error={errors[field.column]}
                        hints={hints[field.column]}
                        held={field.column in held}
                        saving={saving === field.column}
                        flash={flash.has(field.column)}
                        manualText={
                          (GENERATED_TEXTS as readonly string[]).includes(field.column) &&
                          rendered.data !== undefined &&
                          Boolean(row[field.column]) &&
                          (rendered.data[field.column] ?? '') !== '' &&
                          rendered.data[field.column] !== row[field.column]
                        }
                        templateText={rendered.data?.[field.column]}
                        onRegenerate={regenerate}
                        onChange={(v) => {
                          setDrafts((d) => ({ ...d, [field.column]: v }))
                          setHeld((h) => omit(h, field.column))
                          liveValidate(field, v)
                        }}
                        onCommit={(v) => void save(field, v)}
                        onForce={() => void save(field, valueOf(field.column), true)}
                        onCancel={() => clearField(field.column)}
                      />
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </section>
        )
      })}
    </div>
  )
}

function dateText(field: FieldDef, stored: string): string {
  const ts = parseDateText(stored)
  return ts === null ? displayValue(field, stored) : `${displayValue(field, stored)} · ${formatRelativeTime(ts)}`
}

function omit<T>(obj: Record<string, T>, key: string): Record<string, T> {
  if (!(key in obj)) return obj
  const next = { ...obj }
  delete next[key]
  return next
}

function FieldRow({
  field,
  table,
  row,
  value,
  dirty,
  error,
  hints,
  held,
  saving,
  flash,
  manualText,
  templateText,
  onRegenerate,
  onChange,
  onCommit,
  onForce,
  onCancel,
}: {
  field: FieldDef
  table: string
  row: PartRow
  value: string
  dirty: boolean
  error?: string
  hints?: string[]
  /** Wert wegen eines Hinweises nicht gespeichert – wartet auf Bestätigung */
  held: boolean
  saving: boolean
  flash: boolean
  manualText: boolean
  templateText?: string
  onRegenerate: () => void
  onChange: (value: string) => void
  onCommit: (value: string) => void
  onForce: () => void
  onCancel: () => void
}) {
  const id = fieldDomId(field.column)
  const root = useWorkspace().data?.root
  const readOnly = BOOKKEEPING.has(field.column)
  const stored = row[field.column] ?? ''
  const msgId = `${id}-msg`
  const hasMessage = Boolean(error || hints?.length)

  let extra = null
  if (field.column === DATASHEET && stored) {
    extra = (
      <IconButton
        size="sm"
        label="Datenblatt öffnen"
        icon={<ExternalLink />}
        onClick={() =>
          void openDatasheet(stored, root).then((ok) => {
            if (!ok) toast.info('Datei kann im Browser nicht geöffnet werden', { description: stored })
          })
        }
      />
    )
  } else if (field.kind === 'path' && stored) {
    // Datei markiert im Explorer zeigen (außerhalb des Desktop-Programms: Pfad kopieren)
    extra = (
      <IconButton
        size="sm"
        label="Im Explorer zeigen"
        icon={<FolderOpen />}
        onClick={() => void revealPath(resolveLibraryPath(root, stored), { what: pathLabel(field.column) })}
      />
    )
  }

  // Wert/Kommentar/Beschreibung sind Texte für Altium (aus den Vorlagen): Zahlen mit Dezimalpunkt und ohne
  // Leerzeichen („10kΩ“), anders als die deutsch formatierten Messwerte daneben („10 kΩ“) – darum gekennzeichnet
  const altiumText = (GENERATED_TEXTS as readonly string[]).includes(field.column)

  return (
    <div className="grid grid-cols-[9rem_minmax(0,1fr)] items-start gap-x-3">
      <div className="flex min-h-7 flex-wrap items-center gap-x-1.5 gap-y-0.5 py-1">
        <label htmlFor={id} className="flex items-center gap-1 text-xs leading-tight text-fg-muted" title={field.help ?? field.column}>
          <span className="break-words">{field.label}</span>
          {field.required && (
            <span aria-hidden className="text-accent-text">
              *
            </span>
          )}
        </label>
        {altiumText && (
          <span
            title="Text für Altium aus der Vorlage der Kategorie – Zahlen mit Dezimalpunkt, so wie Altium sie zeigt"
            className="rounded-sm border border-line px-1 text-2xs leading-4 text-fg-subtle"
          >
            Altium-Text
          </span>
        )}
      </div>
      <div className="min-w-0">
        {readOnly ? (
          <div id={id} className="flex h-7 items-center gap-1.5 text-xs text-fg-muted">
            <Lock aria-hidden className="size-3 text-fg-subtle" />
            <span className="truncate">
              {field.kind === 'date' && stored ? dateText(field, stored) : stored || '–'}
            </span>
          </div>
        ) : (
          <div
            className={cn(
              'flex items-center gap-1 rounded-control transition-[box-shadow,background-color] duration-700',
              flash && 'bg-accent-soft shadow-[0_0_0_3px_var(--pf-accent-soft)] duration-150',
            )}
          >
            <FieldInput
              id={id}
              field={field}
              table={table}
              value={value}
              size="sm"
              invalid={Boolean(error)}
              onChange={onChange}
              onCommit={onCommit}
              onCancel={onCancel}
              className={cn('min-w-0 flex-1', held && !error && 'border-warning hover:border-warning')}
              aria-label={field.label}
              describedBy={hasMessage ? msgId : undefined}
              required={field.required}
            />
            {saving ? (
              <span className="flex size-7 shrink-0 items-center justify-center" aria-label="Wird gespeichert">
                <Spinner size={13} tone="accent" />
              </span>
            ) : (
              extra
            )}
          </div>
        )}
        {error ? (
          <p id={msgId} role="alert" className="mt-1 flex items-start gap-1.5 text-xs leading-snug text-danger-text">
            <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
            <span>
              {error}
              {dirty && <span className="text-fg-subtle"> · Esc verwirft</span>}
            </span>
          </p>
        ) : hints?.length ? (
          <div id={msgId} role={held ? 'alert' : undefined} className="mt-1 flex items-start gap-1.5 text-xs leading-snug">
            <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0 text-warning-text" />
            <div className="min-w-0">
              <p className="text-warning-text">{hints.join(' · ')}</p>
              {held && (
                <p className="mt-0.5 text-fg-muted">
                  Nicht gespeichert.{' '}
                  <Button variant="link" size="xs" onClick={onForce} className="h-auto p-0 align-baseline">
                    Trotzdem speichern
                  </Button>{' '}
                  (Enter) · Esc verwirft
                </p>
              )}
            </div>
          </div>
        ) : manualText ? (
          <p className="mt-1 flex items-center gap-1.5 text-2xs text-fg-subtle">
            <Wand aria-hidden className="size-3 shrink-0" />
            <span className="min-w-0 truncate">
              Manuell – Vorlage ergibt <span className="mono text-fg-muted">{templateText}</span>
            </span>
            <Tooltip content="Wert, Kommentar und Beschreibung aus den Vorlagen der Kategorie neu erzeugen">
              <Button variant="link" size="xs" leftIcon={<RefreshCw />} onClick={onRegenerate} className="shrink-0">
                übernehmen
              </Button>
            </Tooltip>
          </p>
        ) : null}
      </div>
    </div>
  )
}
