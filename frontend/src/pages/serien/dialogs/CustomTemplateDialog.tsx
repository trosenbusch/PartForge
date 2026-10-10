import { localizeMessage, metadataLabel, t as translate, useI18n } from '@/lib/i18n'
/**
 * Eigene Serienvorlage anlegen oder bearbeiten: Grunddaten, Teilenummern-Muster (Platzhalter als Chips),
 * Werteformat, Baugrößen mit Kennwerten, Codetabellen, Gültigkeit (Bereich + E-Reihen), Brücke und Prüfvermerk.
 * Rechts läuft der Test live (POST /api/series/templates/test): Teilenummern für Beispielwerte bauen und
 * zurücklesen, eingefügte Teilenummern lesen – und je Beispiel prüft das Backend die Pflichtfelder der Kategorie wie
 * die Vorschau der Serie (`missing_fields`, `not_applicable`, gespeicherte `values`). Damit jede gewählte Baugröße
 * geprüft wird, gehen unsichtbare Prüfbeispiele für die übrigen Baugrößen mit. Fehlt ein Pflichtfeld (z. B. Leistung bei
 * Widerständen), wäre jede Zeile der Serie „ungültig“: der Dialog markiert das Eingabefeld, das es füllt, und speichert
 * erst, wenn nichts mehr fehlt. Speichern: POST/PUT /api/series/templates/custom (auch Strg+S); ungespeicherte
 * Eingaben verwirft der Dialog nur nach Rückfrage. Beim Öffnen steht der Fokus im ersten Feld.
 */
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleCheck, CircleX, FilePlus2, FlaskConical, Info, Plus, Trash2, TriangleAlert } from 'lucide-react'
import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, errorMessage } from '@/api/client'
import { useCategories } from '@/api/library'
import {
  seriesApi,
  seriesKeys,
  useSaveCustomTemplate,
  type SeriesTemplate,
  type TemplateSampleResult,
  type TemplateTestBody,
  type TemplateTestResult,
  type ValueStyle,
} from '@/api/series'
import { useSaveHandler } from '@/app/commands'
import { TemplateTokenInput } from '@/components/data'
import {
  Button,
  Callout,
  Checkbox,
  confirm,
  ChipGroup,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  IconButton,
  Input,
  Select,
  Spinner,
  Switch,
  Textarea,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import type { ESeriesName } from '@/lib/units'
import { useDebounced } from '../components/useDebounced'
import { SERIES_CATEGORIES, unitFor } from '../model/categories'
import { SERIES_NAMES } from '../model/values'
import { CodeTable } from './CodeTable'
import {
  autoId,
  autoTitle,
  CHIP_SIZES,
  complexRules,
  defaultSamples,
  emptyDraft,
  fieldsFor,
  fromTemplate,
  METRIC,
  optionKey,
  patternVariables,
  requiredGaps,
  SCALES,
  syncVariables,
  toTemplate,
  typicalValue,
  VALUE_STYLES,
  type DraftSize,
  type SizeAttr,
  type TemplateDraft,
} from './customTemplate'

export interface CustomTemplateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** ID einer eigenen Vorlage zum Bearbeiten (null = neu) */
  editId: string | null
  defaultCategory: string
  /**
   * Gespeichert (der Dialog schließt danach). Rückgabe `true`: die Seite setzt den Fokus selbst (z. B. auf die neue
   * Karte) – dann gibt der Dialog ihn nicht an den Auslöser zurück.
   */
  onSaved: (template: SeriesTemplate, info: { created: boolean }) => boolean | void
}

/** Vergleichsschlüssel für „ungespeicherte Änderungen“ (ohne die gespeicherte Vorlage selbst) */
const draftKey = (d: TemplateDraft, samples: { size: string; value: string }[], mpns: string) =>
  JSON.stringify({
    ...d,
    original: null,
    variables: d.variables.map((v) => ({ ...v, options: v.options.map(({ key: _k, ...o }) => o) })),
    samples: samples.map((x) => [x.size, x.value]),
    mpns,
  })

function RequiredMark() {
  return (
    <span className="ml-0.5 text-accent-text" aria-hidden>
      *
    </span>
  )
}

function FormSection({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-b border-line py-5 first:pt-1 last:border-b-0">
      <div>
        <h3 className="text-sm font-semibold text-fg">{title}</h3>
        {description && <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{description}</p>}
      </div>
      {children}
    </section>
  )
}

/** Fehlertext des Backends ohne „Ungültige Eingabe. template.“-Vorspann */
function cleanError(error: unknown): string {
  const text = errorMessage(error)
  const prefix = translate('Ungültige Eingabe.')
  return (text.startsWith(prefix) ? text.slice(prefix.length).trimStart() : text).replace(/\btemplate\./g, '')
}

/** Erstes bedienbares Feld des Formulars (Kategorie bzw. beim Bearbeiten „Hersteller“) – nicht der Schließen-Knopf */
const FIRST_FIELD =
  'input:not([disabled]):not([type="hidden"]), textarea:not([disabled]), button[role="combobox"]:not([disabled]):not([data-disabled])'

/** Meldung des Backends zu leeren Pflichtfeldern – steht als eigene Zeile (`missing_fields`) */
const MISSING_MESSAGE = /^Pflichtfeld(er)? der Kategorie/

/** Pflichtfelder des Tests (nur, wenn das Backend gegen die Kategorie prüfen konnte) */
const gapsOf = (draft: TemplateDraft, data: TemplateTestResult | undefined) =>
  data?.category_checked ? requiredGaps(draft, data.samples) : []

export function CustomTemplateDialog({ open, onOpenChange, editId, defaultCategory, onSaved }: CustomTemplateDialogProps) {
  const { t: tr } = useI18n()
  const uid = useId().replace(/:/g, '')
  const [draft, setDraft] = useState<TemplateDraft>(() => emptyDraft(defaultCategory))
  const [samples, setSamples] = useState(() => defaultSamples(defaultCategory, draft.sizes.map((s) => s.size)))
  const [mpns, setMpns] = useState('')
  const [loadedFor, setLoadedFor] = useState<string | null | undefined>(undefined)
  const [idError, setIdError] = useState<string | null>(null)
  const [initial, setInitial] = useState('')
  /** leere Pflichtzellen erst nach dem ersten Verlassen rot – nicht schon beim Öffnen */
  const [touched, setTouched] = useState<Partial<Record<SizeAttr, boolean>>>({})
  const save = useSaveCustomTemplate()
  const qc = useQueryClient()
  const categories = useCategories()
  /** nach dem Speichern: Fokus nicht an den Auslöser zurückgeben (die Seite fokussiert die neue Karte) */
  const keepFocus = useRef(false)
  const formRef = useRef<HTMLFormElement>(null)

  // beim Öffnen: neuer Entwurf bzw. die zu bearbeitende Vorlage laden
  const editQuery = useQuery({
    queryKey: seriesKeys.template(editId ?? '–', true),
    queryFn: ({ signal }) => seriesApi.template(editId as string, true, signal),
    enabled: open && Boolean(editId),
    meta: { static: true },
  })
  const openKey = open ? (editId ?? null) : undefined
  if (open && openKey !== loadedFor && (!editId || editQuery.data)) {
    const next = editId && editQuery.data ? fromTemplate(editQuery.data) : emptyDraft(defaultCategory)
    const nextSamples = defaultSamples(next.category, next.sizes.map((s) => s.size))
    setLoadedFor(openKey)
    setDraft(next)
    setSamples(nextSamples)
    setMpns('')
    setIdError(null)
    setTouched({})
    setInitial(draftKey(next, nextSamples, ''))
  }
  if (!open && loadedFor !== undefined) setLoadedFor(undefined)
  // alte Fehler eines früheren Speicherversuchs nicht wieder zeigen
  const resetSave = save.reset
  useEffect(() => {
    if (open) resetSave()
  }, [open, resetSave])
  // Fokus ins erste Feld, sobald das Formular steht (beim Bearbeiten erst nach dem Laden der Vorlage)
  const formReady = open && openKey === loadedFor
  useEffect(() => {
    if (!formReady) return
    const frame = window.requestAnimationFrame(() => formRef.current?.querySelector<HTMLElement>(FIRST_FIELD)?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [formReady, openKey])

  const unit = unitFor(draft.category)
  const editing = Boolean(editId)
  const keepRules = complexRules(draft.original)
  const template = useMemo(() => toTemplate(draft), [draft])
  const used = useMemo(() => new Set(patternVariables(draft.pattern)), [draft.pattern])
  const update = (patch: Partial<TemplateDraft>) =>
    setDraft((d) => {
      const next = { ...d, ...patch }
      if (!next.idTouched) next.id = autoId(next)
      if (!next.titleTouched) next.title = autoTitle(next)
      if (patch.pattern !== undefined || patch.category !== undefined) next.variables = syncVariables(next)
      return next
    })

  // ------------------------------------------------------------------ Live-Test
  /** Beispiele mit Größe und Wert – ihre Ergebnisse kommen in dieser Reihenfolge zurück */
  const shownSamples = useMemo(() => samples.filter((s) => s.size && s.value.trim()), [samples])
  const testBody = useMemo<TemplateTestBody | null>(() => {
    if (!open || !template.pattern || !template.id) return null
    // je weitere Baugröße ein unsichtbares Prüfbeispiel: Pflichtfelder wie die Leistung hängen von der Baugröße ab
    const covered = new Set(shownSamples.map((s) => s.size))
    const checkValue = shownSamples[0]?.value.trim() || typicalValue(draft.category)
    const checks = draft.sizes.filter((x) => !covered.has(x.size)).map((x) => ({ size: x.size, value: checkValue, codes: {} }))
    return {
      template,
      samples: [...shownSamples.map((x) => ({ size: x.size, value: x.value.trim(), codes: {} })), ...checks],
      mpns: mpns
        .split(/[\n,;]+/)
        .map((m) => m.trim())
        .filter(Boolean)
        .slice(0, 20),
    }
  }, [open, template, shownSamples, mpns, draft.sizes, draft.category])
  const debounced = useDebounced(testBody, 450)
  const test = useQuery({
    queryKey: seriesKeys.test(debounced),
    queryFn: ({ signal }) => seriesApi.test(debounced as TemplateTestBody, signal),
    enabled: Boolean(debounced),
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  })
  const testing = test.isFetching || debounced !== testBody
  const testData = test.data && !test.isError ? test.data : undefined
  /** Ergebnis eines sichtbaren Beispiels (nur, wenn es noch zu Größe und Wert passt – während des Tests gilt das alte) */
  const resultFor = (sample: { key: string; size: string; value: string }): TemplateSampleResult | undefined => {
    const index = shownSamples.findIndex((x) => x.key === sample.key)
    const r = index >= 0 ? testData?.samples[index] : undefined
    return r && r.sample.size === sample.size && r.sample.value === sample.value.trim() ? r : undefined
  }
  const shownResults = shownSamples.map(resultFor).filter((r): r is TemplateSampleResult => Boolean(r))
  const okSamples = shownResults.filter((r) => r.valid && r.roundtrip && !r.missing_fields.length).length

  // Pflichtfelder der Kategorie (z. B. Leistung), die laut Test leer blieben – jede Zeile der Serie wäre „ungültig“
  const gaps = useMemo(() => gapsOf(draft, testData).map((g) => ({ ...g, label: metadataLabel(g.label, tr), hint: tr(g.hint) })), [draft, testData, tr])
  const sizeGaps = useMemo(() => {
    const out: Partial<Record<SizeAttr, Set<string>>> = {}
    for (const g of gaps) if (g.sizeAttr) out[g.sizeAttr] = new Set(g.sizes)
    return out
  }, [gaps])
  const categoryDef = categories.data?.find((c) => c.table === draft.category)
  /** Bezeichnung einer Spalte der Kategorie („Power“ → „Leistung“) */
  const fieldLabel = (column: string) => metadataLabel(categoryDef?.fields.find((f) => f.column === column)?.label ?? column, tr)
  const fieldMap = draft.original?.fields ?? fieldsFor(draft.category)
  /** Größen-Attribut füllt ein Pflichtfeld der Kategorie (Leistung bei Widerständen …) – Stern an der Spalte */
  const requiredAttr = (attr: SizeAttr) =>
    (categoryDef?.fields ?? []).some((f) => f.required && (fieldMap[f.column] ?? '').includes(`{${attr}}`))
  const categoryLabel = tr(categoryDef?.label ?? SERIES_CATEGORIES.find((c) => c.table === draft.category)?.label ?? draft.category)

  const dirty = open && initial !== '' && draftKey(draft, samples, mpns) !== initial

  const close = () => {
    keepFocus.current = false
    onOpenChange(false)
  }
  /** Schließen über Esc, Klick daneben, ✕ oder „Abbrechen“: ungespeicherte Eingaben nur nach Rückfrage verwerfen */
  const requestClose = async () => {
    if (!dirty || save.isPending) {
      close()
      return
    }
    const ok = await confirm({
      title: tr("Eingaben verwerfen?"),
      description: editing
        ? tr("Die Änderungen an der Vorlage sind noch nicht gespeichert.")
        : tr("Die neue Vorlage ist noch nicht gespeichert."),
      confirmLabel: tr("Verwerfen"),
      cancelLabel: tr("Weiter bearbeiten"),
      destructive: true,
    })
    if (ok) close()
  }

  const submit = async () => {
    if (!canSave || save.isPending) return
    // Eingabe noch nicht geprüft (Strg+S direkt nach dem Tippen): erst den Test zu genau diesem Stand abwarten
    if (testBody && testing) {
      try {
        const fresh = await qc.fetchQuery({
          queryKey: seriesKeys.test(testBody),
          queryFn: ({ signal }) => seriesApi.test(testBody, signal),
          staleTime: 60_000,
        })
        if (gapsOf(draft, fresh).length) return // der Test zeigt gleich, was fehlt
      } catch {
        // Test fehlgeschlagen – das Speichern meldet den Fehler des Backends
      }
    }
    try {
      const saved = await save.mutateAsync({ template, existingId: editing ? editId : null })
      keepFocus.current = onSaved(saved, { created: !editing }) === true
      onOpenChange(false)
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) setIdError(error.message)
    }
  }

  const sizeRows = draft.sizes
  const setSize = (size: string, patch: Partial<DraftSize>) =>
    update({ sizes: draft.sizes.map((s) => (s.size === size ? { ...s, ...patch } : s)) })
  const tokenFields = [
    { name: 'size', label: tr("Baugröße"), description: tr("Code der Baugröße") },
    { name: 'value', label: tr("Wert"), description: tr("Wertcode nach Werteformat") },
    { name: 'tolerance', label: tr("Toleranz") },
    { name: 'tcr', label: tr("Temperaturkoeffizient") },
    { name: 'voltage', label: tr("Nennspannung") },
    { name: 'dielectric', label: tr("Dielektrikum") },
    { name: 'packaging', label: tr("Verpackung") },
    ...draft.variables
      .filter((v) => !['tolerance', 'tcr', 'voltage', 'dielectric', 'packaging'].includes(v.name))
      .map((v) => ({ name: v.name, label: tr(v.label) })),
  ]
  const firstSample = test.data?.samples.find((s) => s.mpn)
  const basicsOk = Boolean(template.id && template.manufacturer && template.series && template.pattern && draft.sizes.length)
  const canSave = basicsOk && gaps.length === 0
  useSaveHandler(() => void submit(), { modal: true, enabled: open && canSave && !save.isPending })

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (next) onOpenChange(true)
        else void requestClose()
      }}
    >
      <DialogContent
        size="full"
        // nicht auf „Schließen“ springen, solange das Formular lädt – den Fokus setzt das Formular selbst (erstes Feld)
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => {
          if (keepFocus.current) e.preventDefault()
          keepFocus.current = false
        }}
      >
        <DialogHeader
          icon={<FilePlus2 />}
          title={editing ? tr("Serienvorlage bearbeiten") : tr("Eigene Serienvorlage")}
          description={tr("Teilenummern-Muster, Codetabellen und Baugrößen – rechts sofort mit Beispielwerten getestet.")}
        />
        {editId && !editQuery.data ? (
          <DialogBody className="flex items-center justify-center">
            {editQuery.isError ? (
              <Callout tone="danger" title={tr("Vorlage nicht geladen")}>
                {errorMessage(editQuery.error)}
              </Callout>
            ) : (
              <Spinner label={tr("Vorlage wird geladen")} />
            )}
          </DialogBody>
        ) : (
          <form
            ref={formRef}
            className="flex min-h-0 flex-1 flex-col"
            onSubmit={(e) => {
              e.preventDefault()
              if (canSave) void submit()
            }}
          >
            <DialogBody className="@container overflow-hidden p-0">
              <div className="grid h-full min-h-0 grid-cols-1 overflow-y-auto @[60rem]:grid-cols-[minmax(0,1fr)_24rem] @[60rem]:grid-rows-[minmax(0,1fr)] @[60rem]:overflow-hidden">
              <div className="min-w-0 px-6 pb-4 @[60rem]:min-h-0 @[60rem]:overflow-y-auto">
                <FormSection title={tr("Serie")}>
                  <div className="grid grid-cols-1 gap-x-4 gap-y-3 @[34rem]:grid-cols-2">
                    <Field label={tr("Kategorie")} required>
                      <Select
                        value={draft.category}
                        disabled={editing}
                        onValueChange={(category) => {
                          update({ category, variables: [] })
                          setSamples(defaultSamples(category, draft.sizes.map((s) => s.size)))
                        }}
                        options={SERIES_CATEGORIES.map((c) => ({ value: c.table, label: tr(c.label), description: tr("Wert in {v0}", { v0: c.unit }) }))}
                      />
                    </Field>
                    <Field label={tr("Hersteller")} required>
                      <Input value={draft.manufacturer} onChange={(e) => update({ manufacturer: e.target.value })} placeholder={tr("z. B. Walsin")} />
                    </Field>
                    <Field label={tr("Serienname")} required>
                      <Input value={draft.series} onChange={(e) => update({ series: e.target.value })} placeholder={tr("z. B. WR06")} />
                    </Field>
                    <Field label={tr("Titel")} hint={tr("für Karten und Listen")}>
                      <Input
                        value={draft.title}
                        onChange={(e) => update({ title: e.target.value, titleTouched: Boolean(e.target.value) })}
                        placeholder={tr("Hersteller Serie – Bauart")}
                      />
                    </Field>
                    <Field label="ID" required error={idError ? localizeMessage(idError) : undefined} hint={editing ? tr("nicht änderbar") : tr("automatisch")}>
                      <Input
                        mono
                        value={draft.id}
                        disabled={editing}
                        onChange={(e) => {
                          setIdError(null)
                          update({ id: e.target.value.replace(/\s+/g, '-'), idTouched: Boolean(e.target.value) })
                        }}
                        placeholder="eigen-hersteller-serie"
                      />
                    </Field>
                    <Field label={tr("Datenblatt-Link")} hint="optional">
                      <Input value={draft.datasheetUrl} onChange={(e) => update({ datasheetUrl: e.target.value })} placeholder="https://…" />
                    </Field>
                  </div>
                  <Field label={tr("Beschreibung")} hint="optional">
                    <Textarea
                      rows={2}
                      autoResize
                      value={draft.description}
                      onChange={(e) => update({ description: e.target.value })}
                      placeholder={tr("Bauart, Toleranzen, Besonderheiten der Serie")}
                    />
                  </Field>
                </FormSection>

                <FormSection
                  title={tr("Teilenummern-Muster")}
                  description={
                    <>
                      {tr("Platzhalter in geschweiften Klammern:")} <span className="mono">{'{size}'}</span> {tr("Baugröße,")}{' '}
                      <span className="mono">{'{value}'}</span> {tr("Wert – jede weitere Variable bekommt unten eine Codetabelle.")}</>
                  }
                >
                  <Field label={tr("Muster")} required>
                    <TemplateTokenInput
                      value={draft.pattern}
                      onValueChange={(pattern) => update({ pattern })}
                      fields={tokenFields}
                      formats={[]}
                      placeholder={tr("z. B. WR{size}{tolerance}{value}T{packaging}")}
                      preview={firstSample?.mpn ? <span className="mono">{firstSample.mpn}</span> : undefined}
                      previewLoading={testing}
                    />
                  </Field>
                  <div className="grid grid-cols-1 gap-x-4 gap-y-3 @[34rem]:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
                    <Field label={tr("Werteformat")} help={tr(VALUE_STYLES.find((s) => s.value === draft.valueStyle)?.description ?? '')}>
                      <Select<ValueStyle>
                        value={draft.valueStyle}
                        onValueChange={(valueStyle) => update({ valueStyle })}
                        options={VALUE_STYLES.map((s) => ({ value: s.value, label: tr(s.label), description: s.example(unit) }))}
                      />
                    </Field>
                    {SCALES[unit] && SCALES[unit].length > 1 ? (
                      <Field label={tr("Code-Einheit")} help={tr("Wert einer Einheit im Code")}>
                        <Select
                          value={String(draft.valueScale)}
                          onValueChange={(v) => update({ valueScale: Number(v) })}
                          options={SCALES[unit].map((s) => ({ value: String(s.value), label: s.label }))}
                        />
                      </Field>
                    ) : null}
                    {draft.valueStyle === 'uniohm4' && (
                      <Field label={tr("Stellen")}>
                        <Select
                          value={String(draft.valueDigits)}
                          onValueChange={(v) => update({ valueDigits: v === '2' ? 2 : 3 })}
                          options={[
                            { value: '3', label: tr("3 Ziffern (±1 %)") },
                            { value: '2', label: tr("2 Ziffern (±5 %)") },
                          ]}
                        />
                      </Field>
                    )}
                  </div>
                </FormSection>

                <FormSection title={tr("Baugrößen")} description={tr("Footprints entstehen nach IPC-7351B. Code nur angeben, wenn das Muster die Größe anders schreibt (z. B. „1J“ für 0603).")}>
                  <ChipGroup
                    aria-label={tr("Baugrößen")}
                    mono
                    value={draft.sizes.map((s) => s.size)}
                    onValueChange={(sizes) =>
                      update({
                        sizes: CHIP_SIZES.filter((s) => sizes.includes(s)).map(
                          (size) => draft.sizes.find((x) => x.size === size) ?? { size, code: '', power: '', voltage: '', height: '' },
                        ),
                      })
                    }
                    options={CHIP_SIZES.map((s) => ({ value: s, label: s, meta: METRIC[s] }))}
                  />
                  {sizeRows.length > 0 && (
                    <table className="w-full table-fixed text-left">
                      <thead>
                        <tr className="text-2xs text-fg-subtle">
                          <th scope="col" className="w-20 pb-1 font-medium">
                            {tr("Baugröße")}</th>
                          <th scope="col" className="px-1 pb-1 font-medium">
                            {tr("Code im Muster")}</th>
                          {unit === 'Ω' && (
                            <>
                              <th scope="col" className="px-1 pb-1 font-medium">
                                {tr("Leistung")}{requiredAttr('power') && <RequiredMark />}
                              </th>
                              <th scope="col" className="px-1 pb-1 font-medium">
                                {tr("Spannung")}{requiredAttr('voltage') && <RequiredMark />}
                              </th>
                            </>
                          )}
                          <th scope="col" className="px-1 pb-1 font-medium">
                            {tr("Höhe")}{requiredAttr('height') && <RequiredMark />}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {sizeRows.map((s, row) => (
                          <tr key={s.size}>
                            <td className="mono py-0.5 text-ui text-fg">{s.size}</td>
                            <td className="px-1 py-0.5">
                              <Input size="sm" mono value={s.code} placeholder={s.size} onChange={(e) => setSize(s.size, { code: e.target.value })} aria-label={tr("Code für {v0}", { v0: s.size })} />
                            </td>
                            {unit === 'Ω' && (
                              <>
                                <td className="px-1 py-0.5">
                                  <Input
                                    size="sm"
                                    mono
                                    value={s.power}
                                    placeholder={sizeGaps.power?.has(s.size) ? tr("Pflichtfeld") : row === 0 ? tr("z. B. 0.1W") : '–'}
                                    invalid={Boolean(sizeGaps.power?.has(s.size) && touched.power)}
                                    aria-required={requiredAttr('power') || undefined}
                                    onChange={(e) => setSize(s.size, { power: e.target.value })}
                                    onBlur={() => setTouched((t) => ({ ...t, power: true }))}
                                    aria-label={tr("Leistung {v0}", { v0: s.size })}
                                  />
                                </td>
                                <td className="px-1 py-0.5">
                                  <Input
                                    size="sm"
                                    mono
                                    value={s.voltage}
                                    placeholder={sizeGaps.voltage?.has(s.size) ? tr("Pflichtfeld") : row === 0 ? tr("z. B. 75V") : '–'}
                                    invalid={Boolean(sizeGaps.voltage?.has(s.size) && touched.voltage)}
                                    aria-required={requiredAttr('voltage') || undefined}
                                    onChange={(e) => setSize(s.size, { voltage: e.target.value })}
                                    onBlur={() => setTouched((t) => ({ ...t, voltage: true }))}
                                    aria-label={tr("Spannung {v0}", { v0: s.size })}
                                  />
                                </td>
                              </>
                            )}
                            <td className="px-1 py-0.5">
                              <Input size="sm" mono value={s.height} placeholder={row === 0 ? tr("z. B. 0.5mm") : '–'} onChange={(e) => setSize(s.size, { height: e.target.value })} aria-label={tr("Höhe {v0}", { v0: s.size })} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                  {gaps.some((g) => g.sizeAttr) && (
                    <p className="flex items-start gap-2 text-xs leading-relaxed text-warning-text">
                      <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                      <span>
                        {gaps
                          .filter((g) => g.sizeAttr)
                          .map((g) => tr("{v0} ist ein Pflichtfeld der Kategorie {v1}", { v0: tr(g.label), v1: categoryLabel }))
                          .join(' · ')}{' '}
                        {tr("– ohne Angabe wären alle Bauteile dieser Baugrößen „ungültig“.")}</span>
                    </p>
                  )}
                </FormSection>

                {draft.variables.length > 0 && (
                  <FormSection title={tr("Codetabellen")} description={tr("Je Platzhalter: Code in der Teilenummer, Bedeutung als Feldwert (±1%, 50V, X7R), Vorgabe für die Serie.")}>
                    <div className="flex flex-col gap-3">
                      {draft.variables.map((v) => (
                        <CodeTable
                          key={v.name}
                          variable={v}
                          unused={!used.has(v.name)}
                          onChange={(nv) => update({ variables: draft.variables.map((x) => (x.name === v.name ? nv : x)) })}
                        />
                      ))}
                    </div>
                  </FormSection>
                )}

                <FormSection title={tr("Gültigkeit")} description={tr("Welche Werte lieferbar sind – eine Regel für alle Baugrößen. Ohne Bereich prüft PartForge die Lieferbarkeit nicht.")}>
                  {keepRules && (
                    <Callout tone="info" title={tr("{v0} Regeln aus der gespeicherten Vorlage", { v0: draft.original?.rules.length ?? 0 })}>
                      {tr("Bereiche mit Bedingungen je Baugröße oder Code lassen sich hier nicht bearbeiten – sie bleiben unverändert erhalten.")}</Callout>
                  )}
                  {(draft.original?.availability_count ?? 0) > 0 || (draft.original?.catalog.length ?? 0) > 0 ? (
                    <Callout tone="info" title={tr("Lieferbarkeitsmatrix bzw. Katalog bleibt erhalten")}>
                      {tr("Diese Vorlage legt die lieferbaren Typen über eine Matrix oder einen Katalog fest – das Formular ändert sie nicht.")}</Callout>
                  ) : null}
                  <div className="grid grid-cols-1 gap-x-4 gap-y-3 @[34rem]:grid-cols-2">
                    <Field label={tr("Von")} hint={unit} disabled={keepRules}>
                      <Input mono value={draft.rangeMin} onChange={(e) => update({ rangeMin: e.target.value })} placeholder={unit === 'F' ? '10p' : '1'} />
                    </Field>
                    <Field label={tr("Bis")} hint={unit} disabled={keepRules}>
                      <Input mono value={draft.rangeMax} onChange={(e) => update({ rangeMax: e.target.value })} placeholder={unit === 'F' ? '10µ' : '10M'} />
                    </Field>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <span id={`${uid}-series`} className="text-ui font-medium text-fg">
                      {tr("E-Reihen")}</span>
                    <ChipGroup<ESeriesName>
                      aria-label={tr("E-Reihen")}
                      mono
                      disabled={keepRules}
                      value={draft.eSeries}
                      onValueChange={(list) => update({ eSeries: SERIES_NAMES.filter((s) => list.includes(s)) })}
                      options={SERIES_NAMES.map((s) => ({ value: s, label: s }))}
                    />
                  </div>
                  {unit === 'Ω' && (
                    <div className="flex flex-col gap-3">
                      <Switch
                        checked={draft.jumper}
                        onCheckedChange={(jumper) => update({ jumper })}
                        label={tr("0-Ω-Brücke")}
                        description={tr("Die Serie hat eine Brücke mit eigenem Wertcode.")}
                      />
                      {draft.jumper && (
                        <div className="grid grid-cols-1 gap-x-4 gap-y-3 pl-11 @[34rem]:grid-cols-2">
                          <Field label={tr("Wertcode der Brücke")}>
                            <Input mono value={draft.jumperCode} onChange={(e) => update({ jumperCode: e.target.value })} placeholder="0R" />
                          </Field>
                          {draft.variables
                            .filter((v) => used.has(v.name) && v.options.length > 1)
                            .map((v) => (
                              <Field key={v.name} label={tr("{v0} bei Brücken", { v0: tr(v.label) })}>
                                <Select
                                  value={draft.jumperCodes[v.name] || '__std'}
                                  onValueChange={(code) => update({ jumperCodes: { ...draft.jumperCodes, [v.name]: code === '__std' ? '' : code } })}
                                  options={[
                                    { value: '__std', label: tr("Vorgabe") },
                                    ...v.options.filter((o) => o.code).map((o) => ({ value: o.code, label: `${o.code}${o.value ? ` · ${o.value}` : ''}` })),
                                  ]}
                                />
                              </Field>
                            ))}
                        </div>
                      )}
                    </div>
                  )}
                </FormSection>

                <FormSection title={tr("Prüfung")}>
                  <Checkbox
                    checked={draft.verified}
                    onCheckedChange={(v) => update({ verified: v === true })}
                    label={tr("Gegen das Datenblatt geprüft")}
                    description={tr("Codes, Bereiche und Kennwerte stimmen mit dem Datenblatt überein – die Karte zeigt „Geprüft“ mit Quelle.")}
                  />
                  {draft.verified && (
                    <div className="pl-7">
                      <Checkbox
                        checked={draft.availabilityChecked}
                        disabled={keepRules ? false : !(draft.rangeMin.trim() && draft.rangeMax.trim()) && !draft.eSeries.length}
                        onCheckedChange={(v) => update({ availabilityChecked: v === true })}
                        label={tr("Lieferbare Werte stimmen mit dem Datenblatt überein")}
                        description={tr("Bereich und E-Reihen unter „Gültigkeit“ sind geprüft – sonst zeigt die Karte „Lieferbarkeit offen“.")}
                      />
                    </div>
                  )}
                  {draft.verified && (
                    <div className="grid grid-cols-1 gap-x-4 gap-y-3 pl-7 @[34rem]:grid-cols-2">
                      <Field label={tr("Quelle")}>
                        <Input value={draft.sourceTitle} onChange={(e) => update({ sourceTitle: e.target.value })} placeholder={tr("Titel des Datenblatts, Stand")} />
                      </Field>
                      <Field label={tr("Link zur Quelle")} hint="optional">
                        <Input value={draft.sourceUrl} onChange={(e) => update({ sourceUrl: e.target.value })} placeholder="https://…" />
                      </Field>
                    </div>
                  )}
                </FormSection>
              </div>

              {/* ------------------------------------------------------- Test */}
              <aside
                aria-label={tr("Test der Vorlage")}
                className="flex min-w-0 flex-col gap-4 border-t border-line bg-surface-2/40 px-5 py-5 @[60rem]:min-h-0 @[60rem]:overflow-y-auto @[60rem]:border-l @[60rem]:border-t-0"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-sm font-semibold text-fg">
                    <FlaskConical aria-hidden className="size-4 text-fg-muted" />
                    {tr("Test")}</h3>
                  <span className="flex items-center gap-1.5 text-2xs text-fg-subtle" aria-live="polite">
                    {testing ? (
                      <>
                        <Spinner size={12} /> {tr("wird geprüft …")}</>
                    ) : testData && gaps.length ? (
                      <span className="font-medium text-warning-text">{tr("Bauteile unvollständig")}</span>
                    ) : testData ? (
                      tr("{v0} von {v1} in Ordnung", { v0: okSamples, v1: shownSamples.length })
                    ) : null}
                  </span>
                </div>

                {!testBody ? (
                  <p className="text-xs text-fg-muted">{tr("Muster und ID angeben – dann baut PartForge hier Teilenummern.")}</p>
                ) : test.isError ? (
                  <Callout tone="danger" title={tr("Vorlage so nicht verwendbar")}>
                    {cleanError(test.error)}
                  </Callout>
                ) : testData && !testData.category_checked && testData.category_note ? (
                  <Callout tone="info" title={tr("Pflichtfelder nicht geprüft")}>
                    {testData.category_note}
                  </Callout>
                ) : null}
                {gaps.length > 0 && (
                  <Callout
                    tone="warning"
                    title={tr("{v0} leer", { v0: gaps.length === 1 ? tr("Ein Pflichtfeld bleibt") : tr("{v0} Pflichtfelder bleiben", { v0: gaps.length }) })}
                  >
                    <ul className="flex flex-col gap-0.5">
                      {gaps.map((g) => (
                        <li key={g.column}>
                          <span className="font-medium text-fg">{tr(g.label)}:</span> {g.hint}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-1">
                      {tr("So")} {gaps.every((g) => g.sizes.length === draft.sizes.length) ? tr("wäre jedes Bauteil der Serie") : tr("wären diese Bauteile")}{' '}
                      {tr("„ungültig“ und würden nicht angelegt.")}</p>
                  </Callout>
                )}

                <div className="flex flex-col gap-2">
                  <span className="micro-label">{tr("Beispielwerte")}</span>
                  <ul className="flex flex-col gap-2">
                    {samples.map((s, i) => {
                      const r = resultFor(s)
                      return (
                        <li key={s.key} className="rounded-control border border-line bg-surface px-2.5 py-2">
                          <div className="flex items-center gap-1.5">
                            <Select
                              size="sm"
                              aria-label={tr("Baugröße Beispiel {v0}", { v0: i + 1 })}
                              value={s.size || undefined}
                              placeholder={tr("Größe")}
                              onValueChange={(size) => setSamples((list) => list.map((x) => (x.key === s.key ? { ...x, size } : x)))}
                              options={draft.sizes.map((x) => ({ value: x.size, label: x.size }))}
                              className="w-28 shrink-0"
                            />
                            <Input
                              size="sm"
                              mono
                              value={s.value}
                              aria-label={tr("Wert Beispiel {v0}", { v0: i + 1 })}
                              onChange={(e) => setSamples((list) => list.map((x) => (x.key === s.key ? { ...x, value: e.target.value } : x)))}
                              suffix={<span className="text-2xs">{unit}</span>}
                            />
                            <IconButton
                              size="xs"
                              label={tr("Beispiel {v0} entfernen", { v0: i + 1 })}
                              icon={<Trash2 />}
                              onClick={() => setSamples((list) => list.filter((x) => x.key !== s.key))}
                            />
                          </div>
                          {r && <SampleOutcome result={r} fieldLabel={fieldLabel} />}
                        </li>
                      )
                    })}
                  </ul>
                  <Button
                    size="xs"
                    variant="ghost"
                    leftIcon={<Plus />}
                    className="self-start"
                    onClick={() => setSamples((list) => [...list, { key: optionKey(), size: draft.sizes[0]?.size ?? '', value: '' }])}
                  >
                    {tr("Beispielwert")}</Button>
                </div>

                <div className="flex flex-col gap-2">
                  <label htmlFor={`${uid}-mpns`} className="micro-label">
                    {tr("Teilenummern lesen")}</label>
                  <Textarea
                    id={`${uid}-mpns`}
                    rows={2}
                    autoResize
                    className="mono text-ui"
                    value={mpns}
                    onChange={(e) => setMpns(e.target.value)}
                    placeholder={tr("Echte Teilenummern aus dem Datenblatt, eine je Zeile")}
                    spellCheck={false}
                  />
                  {testData && testData.decoded.length > 0 && (
                    <ul className="flex flex-col gap-1">
                      {testData.decoded.map((d, i) => {
                        const input = testBody?.mpns?.[i] ?? ''
                        return (
                          <li key={`${input}-${i}`} className="flex items-start gap-1.5 text-xs">
                            {d ? (
                              <CircleCheck aria-hidden className={cn('mt-0.5 size-3.5 shrink-0', d.valid ? 'text-success' : 'text-warning')} />
                            ) : (
                              <CircleX aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger" />
                            )}
                            <span className="min-w-0">
                              <span className="mono text-fg">{input}</span>{' '}
                              <span className="text-fg-muted">
                                {d
                                  ? `→ ${[d.size, d.value_text, ...Object.values(d.codes).filter(Boolean)].filter(Boolean).join(' · ')}`
                                  : tr("→ passt nicht zum Muster")}
                              </span>
                            </span>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>

                {testData?.regex && (
                  <details className="text-2xs text-fg-subtle">
                    <summary className="cursor-pointer rounded-sm outline-none focus-ring">{tr("Regulärer Ausdruck zum Lesen")}</summary>
                    <code className="mono mt-1.5 block break-all rounded-control border border-line bg-bg/60 p-2 text-fg-muted">
                      {testData.regex}
                    </code>
                  </details>
                )}
              </aside>
              </div>
            </DialogBody>
            <DialogFooter className="justify-between">
              <span className="text-xs text-fg-muted">
                {save.isError && !idError ? (
                  <span className="text-danger-text">{cleanError(save.error)}</span>
                ) : !basicsOk ? (
                  tr("Hersteller, Serie, ID, Muster und mindestens eine Baugröße angeben.")
                ) : gaps.length ? (
                  <span className="text-warning-text">{gaps[0].hint}</span>
                ) : (
                  tr("Eigene Vorlagen gehören zu dieser Bibliothek.")
                )}
              </span>
              <div className="flex gap-2">
                <Button type="button" variant="ghost" onClick={() => void requestClose()}>
                  {tr("Abbrechen")}</Button>
                <Button type="submit" variant="primary" loading={save.isPending} disabled={!canSave} aria-keyshortcuts="Control+S">
                  {editing ? tr("Speichern") : tr("Vorlage anlegen")}
                </Button>
              </div>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}

/**
 * Ergebnis eines Beispiels: Teilenummer, Lieferbarkeit/Rücklesen, leere Pflichtfelder (`missing_fields`), Felder, die
 * für Brücken nicht gelten (`not_applicable`), Beschreibung und – aufklappbar – alle Werte, wie die Serie sie speichert.
 */
function SampleOutcome({ result: r, fieldLabel }: { result: TemplateSampleResult; fieldLabel: (column: string) => string }) {
  const { t: tr } = useI18n()
  const ok = r.valid && r.roundtrip
  const missing = r.missing_fields
  const others = r.messages.filter((m) => !MISSING_MESSAGE.test(m)).map(localizeMessage)
  const values = Object.entries(r.values).filter(([, v]) => v !== null && v !== '')
  const description = r.values.Description ?? null
  return (
    <div className="mt-1.5 flex items-start gap-1.5">
      {ok && !missing.length ? (
        <CircleCheck aria-hidden className="mt-0.5 size-3.5 shrink-0 text-success" />
      ) : r.mpn ? (
        <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-warning" />
      ) : (
        <CircleX aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger" />
      )}
      <div className="min-w-0 flex-1">
        <div className={cn('mono break-all text-ui', r.mpn ? 'text-fg' : 'text-fg-subtle')}>{r.mpn ?? tr("keine Teilenummer")}</div>
        <div className="text-2xs text-fg-muted">
          {ok
            ? tr("Teilenummer gültig · wird eindeutig zurückgelesen")
            : [r.mpn && !r.valid ? tr("laut Regeln nicht lieferbar") : null, ...others].filter(Boolean).join(' · ')}
        </div>
        {ok && others.length > 0 && <div className="text-2xs text-fg-muted">{others.join(' · ')}</div>}
        {missing.length > 0 && (
          <div className="text-2xs text-warning-text">
            {tr("Bauteil wäre ungültig:")} {missing.map((f) => tr(f.label)).join(', ')} {missing.length === 1 ? tr("fehlt") : tr("fehlen")}
          </div>
        )}
        {r.not_applicable.length > 0 && (
          <div className="flex items-start gap-1 text-2xs text-fg-subtle">
            <Info aria-hidden className="mt-px size-3 shrink-0" />
            <span>{tr("Gilt nicht für die Brücke:")} {r.not_applicable.map(fieldLabel).join(', ')}</span>
          </div>
        )}
        {description && <div className="mt-0.5 truncate text-2xs text-fg-muted" title={description}>{description}</div>}
        {values.length > 0 && (
          <details className="mt-1 text-2xs text-fg-subtle">
            <summary className="w-fit cursor-pointer rounded-sm outline-none hover:text-fg focus-ring">
              {tr("Gespeicherte Werte (")}{values.length})
            </summary>
            <dl className="mt-1 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 rounded-control border border-line bg-bg/60 p-2">
              {values.map(([column, value]) => (
                <div key={column} className="contents">
                  <dt className="text-fg-subtle">{fieldLabel(column)}</dt>
                  <dd className="mono min-w-0 break-words text-fg">{value}</dd>
                </div>
              ))}
            </dl>
          </details>
        )}
      </div>
    </div>
  )
}
