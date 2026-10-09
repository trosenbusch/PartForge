import { Bot, FileScan, TriangleAlert } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'
import { useAiStatus, useCostEstimate, useDatasheet, type ExtractOptions } from '@/api/datasheets'
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  Field,
  Input,
  NumberInput,
  SegmentedControl,
  Select,
  Spinner,
  type SelectOption,
} from '@/components/ui'
import { estimateText, formatUsd, pagesText, parsePageInput } from '../lib/format'
import { useDebounced } from './useDebounced'

const MODELS: SelectOption[] = [
  { value: 'claude-opus-5-5', label: 'Claude Opus 5.5', description: 'Liest Zeichnungen und Tabellen am genauesten' },
  { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', description: 'Ausgewogen, etwa halb so teuer' },
  { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', description: 'Sehr günstig, für einfache Datenblätter' },
]

/** Höchstzahl manuell gewählter Seiten (`partforge.datasheet.pages.MANUAL_PAGE_LIMIT`) */
const MANUAL_LIMIT = 40

export interface ReanalyzeTarget {
  id: string
  name: string
  pageCount: number
  costUsd: number
  edited: boolean
  hasExtraction: boolean
  /** zuletzt gelesene Seiten (Vorbelegung „Selbst wählen“) – `null` = aus dem Datenblatt laden */
  selectedPages: number[] | null
}

/**
 * Analyse mit Optionen starten: Seiten selbst wählen, Modell, Gründlichkeit, Kontrolle, Kostenlimit – mit den erwarteten
 * Kosten aus `POST …/estimate` (dieselbe Seitenauswahl wie die Analyse, keine Claude-Anfrage).
 */
export function ReanalyzeDialog({
  target,
  open,
  onOpenChange,
  onStart,
}: {
  target: ReanalyzeTarget | null
  open: boolean
  onOpenChange: (open: boolean) => void
  onStart: (options: Partial<ExtractOptions>) => Promise<boolean>
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {target && (
        <DialogContent size="md">
          <ReanalyzeForm key={target.id} target={target} onCancel={() => onOpenChange(false)} onStart={onStart} />
        </DialogContent>
      )}
    </Dialog>
  )
}

/** „1, 2, 99–120“ → was wegfällt: „99–120 (das PDF hat 26 Seiten)“, „„a“ (keine Seitenzahl)“ – oder `null` */
function droppedText(outOfRange: number[], invalid: string[], pageCount: number): string | null {
  const parts: string[] = []
  if (outOfRange.length) parts.push(`${pagesText(outOfRange)} (das PDF hat ${pageCount} ${pageCount === 1 ? 'Seite' : 'Seiten'})`)
  if (invalid.length) parts.push(`„${invalid.slice(0, 3).join('“, „')}“ (${invalid.length === 1 ? 'keine Seitenzahl' : 'keine Seitenzahlen'})`)
  return parts.length ? parts.join(' und ') : null
}

function ReanalyzeForm({
  target,
  onCancel,
  onStart,
}: {
  target: ReanalyzeTarget
  onCancel: () => void
  onStart: (options: Partial<ExtractOptions>) => Promise<boolean>
}) {
  const ai = useAiStatus().data
  // aus der Liste geöffnet: gelesene Seiten und Kosten aus dem Datenblatt
  const detail = useDatasheet(target.selectedPages === null ? target.id : null).data
  const lastPages = target.selectedPages ?? detail?.selected_pages ?? []
  const [pageMode, setPageMode] = useState<'auto' | 'manual'>('auto')
  const [pagesInput, setPagesInput] = useState<string | null>(null)
  const [model, setModel] = useState(ai?.model ?? 'claude-opus-5-5')
  const [effort, setEffort] = useState<NonNullable<ExtractOptions['effort']>>(
    (ai?.effort as NonNullable<ExtractOptions['effort']>) ?? 'low',
  )
  const [vision, setVision] = useState<NonNullable<ExtractOptions['vision']>>('auto')
  const [limit, setLimit] = useState<number | null>(ai?.max_cost_per_import_usd ?? 2)
  const [pending, setPending] = useState(false)

  const text = pagesInput ?? pagesText(lastPages)
  const parsed = parsePageInput(text, target.pageCount)
  const pages = parsed.pages
  const dropped = pageMode === 'manual' ? droppedText(parsed.outOfRange, parsed.invalid, target.pageCount) : null
  const pagesError =
    pageMode === 'manual'
      ? pages.length === 0
        ? dropped
          ? `Keine gültige Seite – nicht vorhanden: ${dropped}.`
          : 'Bitte Seiten angeben, z. B. „1, 2, 17–24“.'
        : pages.length > MANUAL_LIMIT
          ? `Höchstens ${MANUAL_LIMIT} Seiten.`
          : null
      : null
  const modelOptions = MODELS.some((m) => m.value === model) ? MODELS : [{ value: model, label: model }, ...MODELS]
  const cap = limit && limit > 0 ? Math.min(limit, 25) : null
  const chosenPages = pageMode === 'manual' && !pagesError ? pages : null

  // Schätzung des Backends – entprellt, damit das Tippen der Seiten nicht jede Taste anfragt
  const options = useMemo<Partial<ExtractOptions>>(
    () => ({ model, effort, vision, pages: chosenPages, max_cost_usd: cap }),
    [model, effort, vision, chosenPages, cap],
  )
  const asked = useDebounced(options, 300)
  const enabled = !pagesError
  const est = useCostEstimate(target.id, asked, { enabled })
  // Aufpreis der Kontrolle mit Seitenbildern: „high“ mit und ohne Kontrolle
  const withCheck = useCostEstimate(target.id, { ...asked, vision: 'on' }, { enabled })
  const withoutCheck = useCostEstimate(target.id, { ...asked, vision: 'off' }, { enabled })
  const checkExtra =
    withCheck.data && withoutCheck.data ? Math.max(0, withCheck.data.est_cost_usd_high - withoutCheck.data.est_cost_usd_high) : null
  const expected = est.data ? estimateText(est.data, vision === 'on' && checkExtra ? checkExtra : 0) : null
  const fresh = JSON.stringify(asked) === JSON.stringify(options) && !est.isFetching
  const overBudget = Boolean(est.data?.exceeds_budget)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (pagesError) return
    setPending(true)
    const ok = await onStart({
      model,
      effort,
      vision,
      pages: pageMode === 'manual' ? pages : null,
      max_cost_usd: cap,
    })
    setPending(false)
    if (ok) onCancel()
  }

  const auto = est.data && pageMode === 'auto' ? est.data : null
  const help =
    pageMode === 'auto'
      ? auto && auto.pages.length
        ? `PartForge wählt die Seiten mit Pinbelegung, Bestellangaben und Zeichnungen – diesmal ${auto.pages.length} von ${auto.pages_total}: ${pagesText(auto.pages)}${
            auto.drawing_pages.length ? ` (${auto.drawing_pages.length} als Bild)` : ''
          }${auto.triage ? ', vorher eine Vorauswahl mit dem schnellen Modell' : ''}.`
        : 'PartForge wählt die Seiten mit Pinbelegung, Bestellangaben und Zeichnungen (höchstens 12).'
      : (pagesError ??
        `${pages.length} von ${target.pageCount} Seiten – alle gehen an beide Durchgänge.${dropped ? ` Nicht übernommen: ${dropped}.` : ''}`)

  return (
    <form className="flex min-h-0 flex-1 flex-col" onSubmit={(e) => void submit(e)}>
      <DialogHeader
        tone="spark"
        icon={<FileScan />}
        title={target.hasExtraction ? 'Neu analysieren' : 'Mit Claude analysieren'}
        description={target.name}
      />
      <DialogBody className="flex flex-col gap-4">
        {target.hasExtraction && (
          <div className="flex items-start gap-2.5 rounded-card border border-warning/30 bg-warning/8 px-3.5 py-2.5 text-xs leading-relaxed text-fg-muted">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning-text" />
            <span>
              Das neue Ergebnis ersetzt die bisherige Analyse
              {target.edited ? ' einschließlich Ihrer Korrekturen' : ''}. Bisher bezahlt: {formatUsd(target.costUsd)}.
            </span>
          </div>
        )}
        <Field label="Seiten" help={help} error={pagesError ?? undefined}>
          <div className="flex flex-col gap-2">
            <SegmentedControl
              aria-label="Seitenauswahl"
              value={pageMode}
              onValueChange={setPageMode}
              options={[
                { value: 'auto', label: 'Automatisch' },
                { value: 'manual', label: 'Selbst wählen' },
              ]}
            />
            {pageMode === 'manual' && (
              <Input
                aria-label="Seiten"
                mono
                value={text}
                onChange={(e) => setPagesInput(e.target.value)}
                placeholder="1, 2, 17–24"
                invalid={Boolean(pagesError)}
              />
            )}
          </div>
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Modell">
            <Select value={model} onValueChange={setModel} options={modelOptions} prefix={<Bot />} />
          </Field>
          <Field label="Kostenlimit" hint="für diesen Import">
            <NumberInput value={limit} onValueChange={setLimit} min={0.05} max={25} step={0.5} decimals={2} unit="$" allowEmpty />
          </Field>
        </div>
        <Field label="Gründlichkeit" help="Höher hilft bei dichten Gehäusen (QFN, BGA) – langsamer und teurer.">
          <SegmentedControl
            aria-label="Gründlichkeit"
            fullWidth
            value={effort}
            onValueChange={setEffort}
            options={[
              { value: 'low', label: 'Niedrig' },
              { value: 'medium', label: 'Mittel' },
              { value: 'high', label: 'Hoch' },
            ]}
          />
        </Field>
        <Field
          label="Kontrolle mit Seitenbildern"
          help={`Prüft Pintabellen und Maßzeichnungen zusätzlich an hochaufgelösten Bildern${
            checkExtra !== null ? ` – je Kontrolle bis zu ${formatUsd(Math.max(0.01, checkExtra))} mehr` : ''
          }.`}
        >
          <SegmentedControl
            aria-label="Kontrolle mit Seitenbildern"
            fullWidth
            value={vision}
            onValueChange={setVision}
            options={[
              { value: 'auto', label: 'Bei Auffälligkeiten' },
              { value: 'on', label: 'Immer' },
              { value: 'off', label: 'Nie' },
            ]}
          />
        </Field>
      </DialogBody>
      <DialogFooter className="justify-between">
        <div className="min-w-0 text-xs leading-snug text-fg-muted" aria-live="polite">
          {expected ? (
            <>
              <div className="flex items-center gap-1.5">
                Erwartet <span className="mono whitespace-nowrap font-semibold text-fg">{expected.typical}</span>
                {!fresh && <Spinner size={11} />}
              </div>
              <div className={overBudget ? 'text-2xs text-warning-text' : 'text-2xs text-fg-subtle'}>
                {overBudget
                  ? `Über dem Kostenlimit von ${formatUsd(est.data?.budget_usd ?? cap)} – die Analyse bricht dort ab`
                  : [expected.upTo, cap ? `Limit ${formatUsd(cap)}` : 'ohne Kostenlimit'].filter(Boolean).join(' · ')}
              </div>
            </>
          ) : est.isError ? (
            <div className="text-2xs text-fg-subtle">Kosten lassen sich gerade nicht schätzen{cap ? ` · höchstens ${formatUsd(cap)}` : ''}</div>
          ) : pagesError ? null : (
            <div className="flex items-center gap-1.5 text-2xs text-fg-subtle">
              <Spinner size={11} />
              Kosten werden geschätzt …
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onCancel}>
            Abbrechen
          </Button>
          <Button type="submit" variant="spark" leftIcon={<FileScan />} loading={pending} disabled={Boolean(pagesError)}>
            Analyse starten
          </Button>
        </div>
      </DialogFooter>
    </form>
  )
}
