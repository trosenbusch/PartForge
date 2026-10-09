/**
 * Texte einer Kategorie: Wertfeld, Kommentar- und Beschreibungsvorlage mit Live-Vorschau an einem echten Bauteil.
 * Beides rendert das Backend exakt: die gespeicherten Vorlagen über `render-templates`, der Entwurf über
 * `render-template` (entprellt, je Spalte). Bis die Antwort da ist, zeigt der Browser sofort eine Näherung mit
 * denselben Regeln (templateRender.ts) – kein Flackern beim Tippen.
 *
 * Gerendert wird wie bei neuen Bauteilen bzw. „Texte neu erzeugen“ (`parts.regenerate_texts`): Spalten mit Vorlage
 * entstehen der Reihe nach neu (Wert → Kommentar → Beschreibung, „{Value}“ sieht den neuen Wert); gespeicherte Texte
 * des Beispielbauteils zählen nur für Spalten ohne Vorlage.
 */
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, RefreshCw } from 'lucide-react'
import { useId, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import {
  renderTemplate as renderOnServer,
  settingsKeys,
  useRegenerateTexts,
  useRenderedTemplates,
  useSampleParts,
  type CategoryDef,
  type PartRow,
  type RegenerateTextsResult,
} from '@/api/settings'
import { TemplateTokenInput, type TemplateField } from '@/components/data'
import { Button, confirm, Select, Skeleton, Spinner, type SelectGroupDef } from '@/components/ui'
import { FieldContext } from '@/components/ui/fieldContext'
import { cn } from '@/lib/cn'
import { plural } from '@/lib/format'
import { AUTO_BACKUP_THRESHOLD } from '@/pages/bauteile/model/actions'
import { showChangeToast } from '@/pages/bauteile/model/undo'
import { useDebounced } from '../hooks'
import { renderTemplate, type RenderField } from '../templateRender'
import type { CategoryDraft } from './categoryDraft'

const NONE = '__none'
const AUTO = ['Value', 'Comment', 'Description'] as const
type AutoColumn = (typeof AUTO)[number]
type Templates = Pick<CategoryDraft, 'value_field' | 'comment_template' | 'description_template'>

const AUTO_LABEL: Record<AutoColumn, string> = { Value: 'Wert', Comment: 'Kommentar', Description: 'Beschreibung' }

function templatesOf(t: Templates): Record<AutoColumn, string> {
  return {
    Value: t.value_field ? `{${t.value_field}}` : '',
    Comment: t.comment_template ?? '',
    Description: t.description_template ?? '',
  }
}

/** Beispielbauteil ohne die Texte, die die Vorlagen ohnehin neu erzeugen (sonst sähe „{Value}“ den alten Wert) */
function withoutGenerated(part: PartRow, t: Templates): PartRow {
  const templates = templatesOf(t)
  const row: PartRow = { ...part }
  for (const col of AUTO) if (templates[col]) delete row[col]
  return row
}

/** Ergebnis des Backends für einen Entwurf: Texte je Spalte (unbekannte Platzhalter markiert schon die Eingabe) */
interface DraftRender {
  texts: Record<AutoColumn, string>
}

/**
 * Entwurf exakt vom Backend rendern (`render-template` je Spalte, der Reihe nach wie `parts.render_templates`:
 * das Ergebnis einer Spalte steht den folgenden zur Verfügung).
 */
function useDraftRender(table: string, part: PartRow | null, draft: Templates, enabled: boolean) {
  const templates = useDebounced(templatesOf(draft), 250)
  const values = part ? withoutGenerated(part, draft) : null
  const query = useQuery({
    queryKey: settingsKeys.draftRendered(table, AUTO.map((c) => templates[c]), values),
    queryFn: async ({ signal }): Promise<DraftRender> => {
      const row: Record<string, unknown> = { ...values }
      const texts = {} as Record<AutoColumn, string>
      for (const col of AUTO) {
        const tpl = templates[col]
        if (!tpl) {
          texts[col] = ''
          continue
        }
        const res = await renderOnServer(table, tpl, row, signal)
        texts[col] = res.text
        if (!row[col]) row[col] = res.text || null
      }
      return { texts }
    },
    enabled: enabled && Boolean(values),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: false,
  })
  /** Ergebnis gehört zum aktuellen Entwurf (nicht zu einem älteren Tastendruck) */
  const current = Boolean(query.data) && !query.isPlaceholderData && AUTO.every((c) => templates[c] === templatesOf(draft)[c])
  return { ...query, current }
}

/** Wie `parts.render_templates`: Wert → Kommentar → Beschreibung, leere Spalten übernehmen das Ergebnis */
function renderAll(t: Templates, part: PartRow, fields: RenderField[]): Record<AutoColumn, string> {
  const templates = templatesOf(t)
  const row: Record<string, unknown> = withoutGenerated(part, t)
  const out = {} as Record<AutoColumn, string>
  for (const col of AUTO) {
    const rendered = renderTemplate(templates[col], row, fields)
    out[col] = rendered
    if (!row[col]) row[col] = rendered || null
  }
  return out
}

export function TemplatesPanel({
  category,
  draft,
  saved,
  onChange,
  dirty,
}: {
  category: CategoryDef
  draft: CategoryDraft
  saved: CategoryDraft
  onChange: (patch: Partial<CategoryDraft>) => void
  dirty: boolean
}) {
  const table = category.table
  const fields = category.fields
  const samples = useSampleParts(table)
  const rows = samples.data?.rows ?? []
  const [pn, setPn] = useState<string | null>(null)
  const part = rows.find((r) => r['Part Number'] === pn) ?? rows[0] ?? null
  const server = useRenderedTemplates(table, part ? withoutGenerated(part, saved) : null)
  const regenerate = useRegenerateTexts()
  const qc = useQueryClient()

  const renderFields: RenderField[] = useMemo(() => fields.map((f) => ({ column: f.column, unit: f.unit })), [fields])
  const tplFields: TemplateField[] = useMemo(
    () => fields.map((f) => ({ name: f.column, label: f.label, kind: f.kind, unit: f.unit })),
    [fields],
  )
  const templatesChanged =
    draft.value_field !== saved.value_field ||
    draft.comment_template !== saved.comment_template ||
    draft.description_template !== saved.description_template
  const local = part ? renderAll(draft, part, renderFields) : null
  // Entwurf: exaktes Backend-Ergebnis, sobald es zum aktuellen Stand passt – bis dahin die Näherung des Browsers
  const draftServer = useDraftRender(table, part, draft, templatesChanged)
  const draftExact = draftServer.current && draftServer.data ? draftServer.data.texts : null
  // Gleiche Vorlagen wie gespeichert → exaktes Ergebnis der gespeicherten Vorlagen
  const draftResult = !templatesChanged && server.data ? (server.data as Record<AutoColumn, string>) : (draftExact ?? local)
  const savedResult = server.data as Record<AutoColumn, string> | undefined
  const differences = templatesChanged && savedResult && draftResult ? AUTO.filter((c) => (savedResult[c] ?? '') !== (draftResult[c] ?? '')) : []

  const valueGroups: SelectGroupDef[] = [
    { label: '', options: [{ value: NONE, label: 'Kein Wertfeld', description: '„Value“ bleibt leer bzw. wird von Hand gepflegt' }] },
    {
      label: 'Messwerte',
      options: fields
        .filter((f) => f.kind === 'quantity' || f.kind === 'range')
        .map((f) => ({ value: f.column, label: f.label, description: `${f.column}${f.unit ? ` · ${f.unit}` : ''}` })),
    },
    {
      label: 'Weitere Felder',
      options: fields
        .filter((f) => f.kind !== 'quantity' && f.kind !== 'range' && !f.system && !['Value', 'Comment', 'Description'].includes(f.column))
        .map((f) => ({ value: f.column, label: f.label, description: f.column })),
    },
  ].filter((g) => g.options.length > 0)

  const runRegenerate = async () => {
    const count = category.part_count ?? 0
    let result = null as RegenerateTextsResult | null
    const ok = await confirm({
      title: `Texte von ${plural(count, 'Bauteil', 'Bauteilen')} neu erzeugen?`,
      description: `Wert, Kommentar und Beschreibung entstehen neu aus den gespeicherten Vorlagen. Von Hand geänderte Texte werden dabei überschrieben – direkt danach nimmt „Rückgängig“ das zurück.${
        count > AUTO_BACKUP_THRESHOLD ? ' Vorher legt PartForge automatisch eine Sicherung der Datenbank an.' : ''
      }`,
      confirmLabel: 'Texte überschreiben',
      destructive: true,
      icon: <RefreshCw />,
      onConfirm: async () => {
        result = await regenerate.mutateAsync(table)
      },
    })
    if (!ok || !result) return
    if (result.updated === 0) {
      toast.info('Keine Änderungen', { description: `Alle Texte in „${category.label}“ entsprachen bereits den Vorlagen.` })
    } else {
      showChangeToast(
        qc,
        table,
        result,
        `Texte von ${plural(result.updated, 'Bauteil', 'Bauteilen')} neu erzeugt`,
        `${category.label}: Wert, Kommentar und Beschreibung aus den Vorlagen.`,
      )
    }
  }

  const partOptions = rows.map((r) => ({
    value: r['Part Number'] ?? '',
    label: r['Part Number'] ?? '–',
    description: r.Description ?? undefined,
  }))
  const previewOf = (col: AutoColumn) => (part ? draftResult?.[col] || undefined : undefined)
  const loading = (samples.isPending || (part !== null && server.isPending && !templatesChanged)) && !local

  return (
    <div className="flex flex-col">
      {/* Beispielbauteil für alle Vorschauen */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface-2/30 px-5 py-2.5">
        <span className="text-xs text-fg-muted">Vorschau mit</span>
        {samples.isPending ? (
          <Skeleton className="h-7 w-64 rounded-control" />
        ) : rows.length > 0 ? (
          <Select
            size="sm"
            aria-label="Bauteil für die Vorschau"
            value={part?.['Part Number'] ?? ''}
            onValueChange={setPn}
            options={partOptions}
            className="w-72 max-w-full"
            contentClassName="max-w-[28rem]"
          />
        ) : (
          <span className="text-xs text-fg-subtle">noch keinem Bauteil – die Vorschau erscheint, sobald „{category.label}“ Bauteile hat.</span>
        )}
        {(server.isFetching || samples.isFetching || draftServer.isFetching) && <Spinner size={12} label="Vorschau wird berechnet" />}
      </div>

      <div className="flex flex-col divide-y divide-line px-5">
        <TextRow label="Wertfeld" help="Sein formatierter Wert landet in der Spalte „Value“ (z. B. Widerstand → 10kΩ).">
          <div className="flex max-w-[22rem] flex-col gap-1">
            <Select
              value={draft.value_field ?? NONE}
              onValueChange={(v) => onChange({ value_field: v === NONE ? null : v })}
              groups={valueGroups}
            />
            <PreviewLine
              loading={loading}
              value={draft.value_field ? previewOf('Value') : undefined}
              empty={draft.value_field ? '–' : 'von Hand gepflegt'}
            />
          </div>
        </TextRow>
        <TextRow
          label="Kommentar"
          help={
            <>
              Steht im Schaltplan neben dem Bezeichner. Format <span className="mono">:rkm</span> ergibt 4k7, 100n, 6V3.
            </>
          }
        >
          <TemplateTokenInput
            value={draft.comment_template}
            onValueChange={(v) => onChange({ comment_template: v })}
            fields={tplFields}
            preview={previewOf('Comment')}
            previewLoading={loading}
            placeholder="z. B. {Resistance:rkm}"
          />
        </TextRow>
        <TextRow label="Beschreibung" help="Erscheint in Altium und in der Bauteiltabelle. Teile, deren Felder leer sind, fallen weg.">
          <TemplateTokenInput
            value={draft.description_template}
            onValueChange={(v) => onChange({ description_template: v })}
            fields={tplFields}
            preview={previewOf('Description')}
            previewLoading={loading}
            placeholder="z. B. RES {Size} {Resistance} {Tolerance}"
          />
        </TextRow>
      </div>

      {/* Nur wenn der Entwurf etwas anderes ergibt als die gespeicherten Vorlagen */}
      {part && differences.length > 0 && savedResult && draftResult && (
        <div className="border-t border-line bg-surface-2/30 px-5 py-4">
          <h3 className="mb-2 text-ui font-semibold text-fg">
            Änderung an <span className="mono font-medium">{part['Part Number']}</span>
          </h3>
          <div role="table" aria-label="Gespeichert und Entwurf im Vergleich" className="flex flex-col divide-y divide-line">
            <div role="row" className="grid grid-cols-[6.5rem_minmax(0,1fr)_1rem_minmax(0,1fr)] gap-3 pb-1.5">
              <span role="columnheader" className="micro-label">
                Spalte
              </span>
              <span role="columnheader" className="micro-label">
                Bisher
              </span>
              <span aria-hidden />
              <span role="columnheader" className="micro-label">
                Mit Entwurf
              </span>
            </div>
            {differences.map((col) => (
              <div key={col} role="row" className="grid grid-cols-[6.5rem_minmax(0,1fr)_1rem_minmax(0,1fr)] items-baseline gap-3 py-2">
                <span role="rowheader" className="text-xs text-fg-muted">
                  {AUTO_LABEL[col]}
                </span>
                <span
                  role="cell"
                  className={cn('mono min-w-0 break-words text-xs text-fg-subtle', savedResult[col] && 'line-through decoration-fg-subtle/60')}
                >
                  {savedResult[col] || <span className="font-sans">leer</span>}
                </span>
                <span aria-hidden className="self-center">
                  <ArrowRight className="size-3.5 text-accent" />
                </span>
                <span role="cell" className="mono min-w-0 break-words text-xs text-fg">
                  {draftResult[col] || <span className="font-sans text-fg-subtle">leer</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3">
        <p className="min-w-0 flex-1 text-xs text-fg-muted">
          Neue und geänderte Bauteile erhalten die Texte automatisch. Bestehende Bauteile behalten ihre Texte, bis Sie sie neu
          erzeugen.
        </p>
        <Button
          size="sm"
          variant="secondary"
          leftIcon={<RefreshCw />}
          onClick={() => void runRegenerate()}
          disabled={dirty || !(category.part_count ?? 0)}
          title={dirty ? 'Zuerst speichern' : !(category.part_count ?? 0) ? 'Noch keine Bauteile' : undefined}
        >
          Texte neu erzeugen …
        </Button>
      </div>
    </div>
  )
}

/**
 * Einstellungszeile mit breiter Eingabe: Vorlagen sind lang („RES {Size} {Resistance} {Tolerance} …“) – die
 * Standardzeile (`Field layout="row"`, Eingabe höchstens 22 rem) würde sie abschneiden.
 */
function TextRow({ label, help, children }: { label: string; help: ReactNode; children: ReactNode }) {
  const id = `tx-${useId().replace(/:/g, '')}`
  const helpId = `${id}-help`
  return (
    <FieldContext.Provider value={{ id, describedBy: helpId, invalid: false }}>
      <div className="@container py-4">
        <div className="grid gap-x-8 gap-y-2 @[40rem]:grid-cols-[minmax(10rem,16rem)_minmax(0,1fr)] @[40rem]:items-start">
          <div className="flex min-w-0 flex-col gap-1 @[40rem]:pt-1.5">
            <label htmlFor={id} className="text-ui font-medium text-fg">
              {label}
            </label>
            <p id={helpId} className="text-xs leading-snug text-fg-muted">
              {help}
            </p>
          </div>
          <div className="min-w-0">{children}</div>
        </div>
      </div>
    </FieldContext.Provider>
  )
}

/** Vorschauzeile unter dem Wertfeld – im Stil der Vorschau des TemplateTokenInput */
function PreviewLine({ loading, value, empty }: { loading: boolean; value: string | undefined; empty: string }) {
  return (
    <div className="flex min-h-6 items-center gap-2 text-xs" aria-live="polite">
      <span className="micro-label shrink-0">Vorschau</span>
      {loading ? (
        <Spinner size={12} tone="accent" />
      ) : value ? (
        <span className="mono min-w-0 truncate text-fg">{value}</span>
      ) : (
        <span className={cn('text-fg-subtle', empty !== '–' && 'italic')}>{empty}</span>
      )}
    </div>
  )
}

