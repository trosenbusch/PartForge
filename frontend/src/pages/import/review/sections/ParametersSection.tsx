import { metadataLabel, t, useI18n } from '@/lib/i18n'
import { ChevronDown, CircleAlert, ListTree, RotateCcw, SlidersHorizontal, TriangleAlert, Wand2 } from 'lucide-react'
import { useState } from 'react'
import type { FieldDef } from '@/api/library'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { Button, IconButton, Popover, PopoverContent, PopoverTrigger, Select } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { CommitInput } from '../../shared/CommitInput'
import { SourceChip } from '../../shared/SourceChip'
import { TipButton } from '../../shared/TipButton'
import type { ChoiceDraft } from '../../store'
import { useReview } from '../context'
import { commonValue, fieldGroups, proposalErrors, proposalValues } from '../values'
import { Section } from './Section'

const NONE = '__none__'

const isMono = (field: FieldDef) => field.kind === 'quantity' || field.kind === 'range' || field.kind === 'int'

/**
 * Anzeige technischer Werte wie in der Bauteiltabelle („0.8mm“ → „0,8 mm“, „-40°C … 85°C“ → „−40 °C … 85 °C“) – nur ohne
 * Fokus; bearbeitet und gespeichert wird der Text des Backends.
 */
const displayOf = (field: FieldDef) => (field.kind === 'quantity' || field.kind === 'range' ? formatQuantityText : undefined)

/** Wert für alle Bestellnummern setzen (`null` = Wert aus dem Datenblatt); Einzelwerte dieser Spalte entfallen. */
function setForAll(c: ChoiceDraft, column: string, text: string | null): ChoiceDraft {
  const values = { ...c.values }
  if (text === null || !text.trim()) delete values[column]
  else values[column] = text.trim()
  return { ...c, values, variantValues: withoutColumn(c.variantValues, column) }
}

function withoutColumn(map: ChoiceDraft['variantValues'] | undefined, column: string): ChoiceDraft['variantValues'] {
  const out: ChoiceDraft['variantValues'] = {}
  for (const [mpn, values] of Object.entries(map ?? {})) {
    const rest = { ...values }
    delete rest[column]
    if (Object.keys(rest).length) out[mpn] = rest
  }
  return out
}

/** Wert einer einzelnen Bestellnummer (`null` = Wert aus dem Datenblatt) */
function setForVariant(c: ChoiceDraft, mpn: string, column: string, text: string | null): ChoiceDraft {
  const map = { ...(c.variantValues ?? {}) }
  const values = { ...(map[mpn] ?? {}) }
  if (text === null || !text.trim()) delete values[column]
  else values[column] = text.trim()
  if (Object.keys(values).length) map[mpn] = values
  else delete map[mpn]
  return { ...c, variantValues: map }
}

function FieldRow({ field }: { field: FieldDef }) {
  useI18n()
  const { device, proposal, choices, setChoices } = useReview()
  const override = choices.values[field.column]
  const values = proposalValues(proposal, field.column)
  const shared = commonValue(values)
  const varies = shared === null && values.length > 1
  const perVariant = Object.values(choices.variantValues ?? {}).some((v) => v[field.column] !== undefined)
  const value = override ?? shared ?? ''
  const source = device.parameters.find((p) => p.column.toLowerCase() === field.column.toLowerCase())
  const errors = proposalErrors(proposal, field.column)
  const normalized = source && source.raw && source.value !== source.raw ? source.raw : null
  const id = `param-${field.column.replace(/\W+/g, '-')}`

  const setAll = (text: string | null) => setChoices((c) => setForAll(c, field.column, text))

  return (
    <div className="grid grid-cols-[minmax(0,9.5rem)_minmax(0,1fr)_auto] items-center gap-x-2 border-b border-line py-1.5 last:border-b-0 @[34rem]:grid-cols-[minmax(0,12rem)_minmax(0,1fr)_auto]">
      <label htmlFor={id} className="flex min-w-0 items-center gap-1 text-xs text-fg-muted">
        <span className="line-clamp-2 leading-tight">{metadataLabel(field.label)}</span>
        {field.unit && <span className="shrink-0 text-2xs text-fg-subtle">[{field.unit}]</span>}
      </label>
      <div className="flex min-w-0 items-center gap-1">
        {varies && override === undefined ? (
          // verschiedene Werte je Bestellnummer: nie stillschweigend für alle überschreiben
          <PerVariantEditor id={id} field={field} invalid={errors.length > 0} />
        ) : field.kind === 'enum' && field.options.length > 0 ? (
          <Select
            id={id}
            size="sm"
            value={value || NONE}
            onValueChange={(v) => setAll(v === NONE ? null : v === shared && !perVariant ? null : v)}
            options={[{ value: NONE, label: '–' }, ...field.options.map((o) => ({ value: o, label: o }))]}
            invalid={errors.length > 0}
            className="min-w-0 flex-1"
          />
        ) : (
          <CommitInput
            id={id}
            size="sm"
            value={value}
            display={displayOf(field)}
            mono={isMono(field)}
            placeholder="–"
            invalid={errors.length > 0}
            onCommit={(t) => setAll(t === shared && !perVariant ? null : t)}
            containerClassName="min-w-0 flex-1"
          />
        )}
        {(override !== undefined || (perVariant && !varies)) && (
          <IconButton size="xs" label={t("Wert aus dem Datenblatt verwenden")} icon={<RotateCcw />} onClick={() => setAll(null)} />
        )}
      </div>
      <div className="flex min-w-[3.25rem] items-center justify-end gap-1">
        {errors.length > 0 ? (
          <TipButton tip={errors.join(' · ')} label={t("Ungültig: {0}", { "0": String(errors.join(', ')) })} className="rounded-sm text-danger-text">
            <CircleAlert aria-hidden className="size-3.5" />
          </TipButton>
        ) : source?.warning ? (
          <TipButton tip={source.warning} label={t("Hinweis: {0}", { "0": String(source.warning) })} className="rounded-sm text-warning-text">
            <TriangleAlert aria-hidden className="size-3.5" />
          </TipButton>
        ) : normalized && override === undefined ? (
          <TipButton
            tip={t("Im Datenblatt: „{0}“ – einheitlich geschrieben", { "0": String(normalized) })}
            label={t("Normalisiert aus „{0}“", { "0": String(normalized) })}
            className="rounded-sm text-fg-subtle"
          >
            <Wand2 aria-hidden className="size-3.5" />
          </TipButton>
        ) : null}
        <SourceChip pages={[source?.page]} what={metadataLabel(field.label)} />
      </div>
    </div>
  )
}

/**
 * Feld mit verschiedenen Werten je Bestellnummer (z. B. Gehäuse): zeigt die Werte, bearbeitet wird je Bestellnummer
 * (`variant_values`). „Für alle gleich setzen …“ ist ein ausdrücklicher Schritt mit Warnung.
 */
function PerVariantEditor({ id, field, invalid }: { id: string; field: FieldDef; invalid: boolean }) {
  useI18n()
  const { proposal, choices, setChoices } = useReview()
  const [open, setOpen] = useState(false)
  const [allMode, setAllMode] = useState(false)
  const [allText, setAllText] = useState('')
  const rows = (proposal?.variants ?? []).map((v) => ({ mpn: v.mpn, value: v.values[field.column] ?? '' }))
  const distinct = [...new Set(rows.map((r) => r.value))]
  const show = displayOf(field)
  const preview = distinct.map((v) => (v ? (show ? show(v) : v) : '–')).join(' · ')
  const enumOptions = field.kind === 'enum' && field.options.length > 0 ? field.options : null

  const setVariant = (mpn: string, text: string | null) => setChoices((c) => setForVariant(c, mpn, field.column, text))
  const applyAll = () => {
    if (!allText.trim()) return
    setChoices((c) => setForAll(c, field.column, allText))
    setAllMode(false)
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (!o) setAllMode(false)
      }}
    >
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          // Name kommt vom <label> des Feldes; die Werte beschreiben den Knopf (kein abweichendes aria-label)
          aria-describedby={`${id}-values`}
          className={cn(
            'flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-control border border-dashed border-line-control bg-control px-2 text-left text-xs outline-none transition-colors hover:border-line-strong focus-ring',
            invalid && 'border-danger/60',
          )}
        >
          <ListTree aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
          <span id={`${id}-values`} className={cn('min-w-0 flex-1 truncate text-fg', isMono(field) && 'mono')}>
            {preview}
            <span className="sr-only"> – {distinct.length} {t(" verschiedene Werte je Bestellnummer, bearbeiten")}</span>
          </span>
          <span className="shrink-0 rounded-full bg-surface-3 px-1.5 text-2xs tabular-nums leading-4 text-fg-muted">
            {t("je Nr.")}</span>
          <ChevronDown aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" aria-label={t("{0} je Bestellnummer", { "0": String(field.label) })} className="w-[26rem] p-0">
        <div className="border-b border-line px-3.5 py-2.5">
          <div className="text-ui font-semibold text-fg">{field.label} {t(" je Bestellnummer")}</div>
          <p className="mt-0.5 text-xs leading-snug text-fg-muted">
            {distinct.length} {t(" verschiedene Werte – jede Bestellnummer behält ihren eigenen Wert.")}</p>
        </div>
        <ul className="max-h-72 divide-y divide-line overflow-y-auto px-3.5 py-1">
          {rows.map((r) => {
            const overridden = choices.variantValues?.[r.mpn]?.[field.column] !== undefined
            return (
              <li key={r.mpn} className="grid grid-cols-[minmax(0,1fr)_minmax(0,11rem)_1.5rem] items-center gap-2 py-1">
                <span className="mono truncate text-xs text-fg" title={r.mpn}>
                  {r.mpn}
                </span>
                {enumOptions ? (
                  <Select
                    size="sm"
                    aria-label={t("{0} von {1}", { "0": String(field.label), "1": String(r.mpn) })}
                    value={r.value || NONE}
                    onValueChange={(v) => setVariant(r.mpn, v === NONE ? null : v)}
                    options={[{ value: NONE, label: '–' }, ...enumOptions.map((o) => ({ value: o, label: o }))]}
                  />
                ) : (
                  <CommitInput
                    size="sm"
                    aria-label={t("{0} von {1}", { "0": String(field.label), "1": String(r.mpn) })}
                    value={r.value}
                    display={show}
                    mono={isMono(field)}
                    placeholder="–"
                    onCommit={(t) => setVariant(r.mpn, t === r.value ? r.value : t)}
                  />
                )}
                {overridden ? (
                  <IconButton size="xs" label={t("{0}: Wert aus dem Datenblatt", { "0": String(r.mpn) })} icon={<RotateCcw />} onClick={() => setVariant(r.mpn, null)} />
                ) : (
                  <span aria-hidden />
                )}
              </li>
            )
          })}
        </ul>
        <div className="border-t border-line bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)] px-3.5 py-2.5">
          {allMode ? (
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                applyAll()
              }}
            >
              <p className="flex items-start gap-1.5 text-xs leading-snug text-warning-text">
                <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                {t("Überschreibt ")}{formatNumber(distinct.length)} {t(" verschiedene Werte bei ")}{formatNumber(rows.length)} {t(" Bestellnummern.")}</p>
              <div className="flex items-center gap-2">
                {enumOptions ? (
                  <Select
                    size="sm"
                    aria-label={t("{0} für alle", { "0": String(field.label) })}
                    value={allText || undefined}
                    placeholder={t("Wert wählen …")}
                    onValueChange={setAllText}
                    options={enumOptions.map((o) => ({ value: o, label: o }))}
                    className="min-w-0 flex-1"
                  />
                ) : (
                  <input
                    // oxlint-disable-next-line jsx-a11y/no-autofocus -- ausdrücklich geöffnetes Eingabefeld
                    autoFocus
                    aria-label={t("{0} für alle", { "0": String(field.label) })}
                    value={allText}
                    onChange={(e) => setAllText(e.target.value)}
                    placeholder={t("Wert für alle …")}
                    className={cn(
                      'h-7 min-w-0 flex-1 rounded-control border border-line-control bg-control px-2 text-xs text-fg outline-none focus:border-accent focus:shadow-[0_0_0_3px_var(--pf-accent-soft)]',
                      isMono(field) && 'mono',
                    )}
                  />
                )}
                <Button size="xs" variant="ghost" onClick={() => setAllMode(false)}>
                  {t("Abbrechen")}</Button>
                <Button size="xs" variant="secondary" type="submit" disabled={!allText.trim()}>
                  {t("Für alle setzen")}</Button>
              </div>
            </form>
          ) : (
            <Button size="xs" variant="ghost" onClick={() => setAllMode(true)}>
              {t("Für alle gleich setzen …")}</Button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** Parameter der gewählten Kategorie (mit Einheiten): Werte aus dem Datenblatt, normalisiert und überschreibbar. */
export function ParametersSection() {
  useI18n()
  const { category, device } = useReview()
  const { specific, general } = fieldGroups(category)
  const found = device.parameters.length
  return (
    <Section
      id="parameter"
      title={t("Parameter")}
      icon={<SlidersHorizontal />}
      count={category ? specific.length + general.length : undefined}
      aside={<span className="text-2xs text-fg-subtle">{found ? t("{0} aus dem Datenblatt", { "0": String(found) }) : t("keine im Datenblatt gefunden")}</span>}
    >
      {!category ? (
        <p className="text-xs text-fg-muted">{t("Erst eine Kategorie wählen – dann erscheinen ihre Felder.")}</p>
      ) : (
        <div className="flex flex-col gap-3">
          {specific.length > 0 && (
            <div>
              <h3 className="micro-label mb-1">{metadataLabel(category.label)}</h3>
              <div className="rounded-card border border-line bg-surface px-3">
                {specific.map((f) => (
                  <FieldRow key={f.column} field={f} />
                ))}
              </div>
            </div>
          )}
          {general.length > 0 && (
            <div>
              <h3 className="micro-label mb-1">{t("Allgemein")}</h3>
              <div className="rounded-card border border-line bg-surface px-3">
                {general.map((f) => (
                  <FieldRow key={f.column} field={f} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}
