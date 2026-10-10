import { t, useI18n } from '@/lib/i18n'
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
  { value: 'claude-opus-5-5', label: 'Claude Opus 5.5', get description() { return t("Liest Zeichnungen und Tabellen am genauesten") } },
  { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5', get description() { return t("Ausgewogen, etwa halb so teuer") } },
  { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5', get description() { return t("Sehr günstig, für einfache Datenblätter") } },
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
  useI18n()
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
  if (outOfRange.length) parts.push(t("{0} (das PDF hat {1} {2})", { "0": String(pagesText(outOfRange)), "1": String(pageCount), "2": String(pageCount === 1 ? t("Seite") : t("Seiten")) }))
  if (invalid.length) parts.push(`„${invalid.slice(0, 3).join('“, „')}“ (${invalid.length === 1 ? t("keine Seitenzahl") : t("keine Seitenzahlen")})`)
  return parts.length ? parts.join(t(' und ')) : null
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
  useI18n()
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
          ? t("Keine gültige Seite – nicht vorhanden: {0}.", { "0": String(dropped) })
          : t("Bitte Seiten angeben, z. B. „1, 2, 17–24“.")
        : pages.length > MANUAL_LIMIT
          ? t("Höchstens {0} Seiten.", { "0": String(MANUAL_LIMIT) })
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
        ? t("PartForge wählt die Seiten mit Pinbelegung, Bestellangaben und Zeichnungen – diesmal {0} von {1}: {2}{3}{4}.", { "0": String(auto.pages.length), "1": String(auto.pages_total), "2": String(pagesText(auto.pages)), "3": String(auto.drawing_pages.length ? t(" ({0} als Bild)", { "0": String(auto.drawing_pages.length) }) : ''), "4": String(auto.triage ? t(", vorher eine Vorauswahl mit dem schnellen Modell") : '') })
        : t("PartForge wählt die Seiten mit Pinbelegung, Bestellangaben und Zeichnungen (höchstens 12).")
      : (pagesError ??
        t("{0} von {1} Seiten – alle gehen an beide Durchgänge.{2}", { "0": String(pages.length), "1": String(target.pageCount), "2": String(dropped ? t(" Nicht übernommen: {0}.", { "0": String(dropped) }) : '') }))

  return (
    <form className="flex min-h-0 flex-1 flex-col" onSubmit={(e) => void submit(e)}>
      <DialogHeader
        tone="spark"
        icon={<FileScan />}
        title={target.hasExtraction ? t("Neu analysieren") : t("Mit Claude analysieren")}
        description={target.name}
      />
      <DialogBody className="flex flex-col gap-4">
        {target.hasExtraction && (
          <div className="flex items-start gap-2.5 rounded-card border border-warning/30 bg-warning/8 px-3.5 py-2.5 text-xs leading-relaxed text-fg-muted">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-warning-text" />
            <span>
              {t("Das neue Ergebnis ersetzt die bisherige Analyse")}{target.edited ? t(" einschließlich Ihrer Korrekturen und übernommener Gehäusemaße") : ''}{t(". Bisher bezahlt:")}{' '}
              {formatUsd(target.costUsd)}.
            </span>
          </div>
        )}
        <Field label={t("Seiten")} help={help} error={pagesError ?? undefined}>
          <div className="flex flex-col gap-2">
            <SegmentedControl
              aria-label={t("Seitenauswahl")}
              value={pageMode}
              onValueChange={setPageMode}
              options={[
                { value: 'auto', label: t("Automatisch") },
                { value: 'manual', label: t("Selbst wählen") },
              ]}
            />
            {pageMode === 'manual' && (
              <Input
                aria-label={t("Seiten")}
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
          <Field label={t("Modell")}>
            <Select value={model} onValueChange={setModel} options={modelOptions} prefix={<Bot />} />
          </Field>
          <Field label={t("Kostenlimit")} hint={t("für diesen Import")}>
            <NumberInput value={limit} onValueChange={setLimit} min={0.05} max={25} step={0.5} decimals={2} unit="$" allowEmpty />
          </Field>
        </div>
        <Field label={t("Gründlichkeit")} help={t("Höher hilft bei dichten Gehäusen (QFN, BGA) – langsamer und teurer.")}>
          <SegmentedControl
            aria-label={t("Gründlichkeit")}
            fullWidth
            value={effort}
            onValueChange={setEffort}
            options={[
              { value: 'low', label: t("Niedrig") },
              { value: 'medium', label: t("Mittel") },
              { value: 'high', label: t("Hoch") },
            ]}
          />
        </Field>
        <Field
          label={t("Kontrolle mit Seitenbildern")}
          help={t("Prüft Pintabellen und Maßzeichnungen zusätzlich an hochaufgelösten Bildern{0}.", { "0": String(checkExtra !== null ? t(" – je Kontrolle bis zu {0} mehr", { "0": String(formatUsd(Math.max(0.01, checkExtra))) }) : '') })}
        >
          <SegmentedControl
            aria-label={t("Kontrolle mit Seitenbildern")}
            fullWidth
            value={vision}
            onValueChange={setVision}
            options={[
              { value: 'auto', label: t("Bei Auffälligkeiten") },
              { value: 'on', label: t("Immer") },
              { value: 'off', label: t("Nie") },
            ]}
          />
        </Field>
      </DialogBody>
      <DialogFooter className="justify-between">
        <div className="min-w-0 text-xs leading-snug text-fg-muted" aria-live="polite">
          {expected ? (
            <>
              <div className="flex items-center gap-1.5">
                {t("Erwartet ")}<span className="mono whitespace-nowrap font-semibold text-fg">{expected.typical}</span>
                {!fresh && <Spinner size={11} />}
              </div>
              <div className={overBudget ? 'text-2xs text-warning-text' : 'text-2xs text-fg-subtle'}>
                {overBudget
                  ? t("Über dem Kostenlimit von {0} – die Analyse bricht dort ab", { "0": String(formatUsd(est.data?.budget_usd ?? cap)) })
                  : [expected.upTo, cap ? `Limit ${formatUsd(cap)}` : t("ohne Kostenlimit")].filter(Boolean).join(' · ')}
              </div>
            </>
          ) : est.isError ? (
            <div className="text-2xs text-fg-subtle">{t("Kosten lassen sich gerade nicht schätzen")}{cap ? t(" · höchstens {0}", { "0": String(formatUsd(cap)) }) : ''}</div>
          ) : pagesError ? null : (
            <div className="flex items-center gap-1.5 text-2xs text-fg-subtle">
              <Spinner size={11} />
              {t("Kosten werden geschätzt …")}</div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onCancel}>
            {t("Abbrechen")}</Button>
          <Button type="submit" variant="spark" leftIcon={<FileScan />} loading={pending} disabled={Boolean(pagesError)}>
            {t("Analyse starten")}</Button>
        </div>
      </DialogFooter>
    </form>
  )
}
