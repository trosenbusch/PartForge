import { localizeMessage } from '@/lib/i18n'
import { t, useI18n } from '@/lib/i18n'
import { useQueries } from '@tanstack/react-query'
import { CircleAlert, FileScan, FileText } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { datasheetKeys, datasheetsApi, useAiStatus, type CostEstimate } from '@/api/datasheets'
import { Badge, Button, Checkbox, Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { plural } from '@/lib/format'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import { effortLabel, estimateText, formatUsd, runLabel } from '../lib/format'
import { useBatchPrompt, type BatchItem } from '../store'

/**
 * Rückfrage nach dem Ablegen mehrerer PDFs: Gespeichert sind sie schon (kostenlos) – analysiert wird nur, was hier
 * bestätigt wird, mit den erwarteten Kosten je Datenblatt (`POST …/estimate`, keine Claude-Anfrage). Fehlgeschlagene
 * sind abgewählt (ein neuer Versuch kostet erneut), bereits analysierte nicht wählbar.
 */
export function BatchAnalyzeDialog({ onAnalyze }: { onAnalyze: (ids: string[]) => Promise<number> }) {
  useI18n()
  const items = useBatchPrompt((s) => s.items)
  const close = useBatchPrompt((s) => s.close)
  return (
    <Dialog
      open={Boolean(items)}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      {items && (
        <DialogContent size="md">
          <BatchForm key={items.map((i) => i.id).join()} items={items} onClose={close} onAnalyze={onAnalyze} />
        </DialogContent>
      )}
    </Dialog>
  )
}

function BatchForm({ items, onClose, onAnalyze }: { items: BatchItem[]; onClose: () => void; onAnalyze: (ids: string[]) => Promise<number> }) {
  useI18n()
  const ai = useAiStatus().data
  const navigate = useNavigate()
  const [selected, setSelected] = useState(() => new Set(items.filter((i) => i.state === 'new').map((i) => i.id)))
  const [pending, setPending] = useState(false)
  const limit = ai?.max_cost_per_import_usd ?? null

  // Schätzung je Datenblatt mit den Standardeinstellungen (wie die Analyse sie verwendet)
  const estimates = useQueries({
    queries: items.map((i) => ({
      queryKey: datasheetKeys.estimate(i.id, null),
      queryFn: ({ signal }: { signal: AbortSignal }) => datasheetsApi.estimate(i.id, null, signal),
      enabled: i.state !== 'analyzed',
      staleTime: 60_000,
      retry: false,
    })),
  })
  const estimateOf = (id: string): CostEstimate | undefined => estimates[items.findIndex((i) => i.id === id)]?.data
  const chosen = items.filter((i) => selected.has(i.id))
  const known = chosen.map((i) => estimateOf(i.id)).filter((e): e is CostEstimate => Boolean(e))
  const loading = known.length < chosen.length && estimates.some((q) => q.isLoading)
  const total = known.reduce(
    (sum, e) => ({ low: sum.low + e.est_cost_usd_low, high: sum.high + e.est_cost_usd_high }),
    { low: 0, high: 0 },
  )
  const totalText = estimateText({ est_cost_usd_low: total.low, est_cost_usd_high: total.high })
  const analyzable = items.filter((i) => i.state !== 'analyzed').length
  const label =
    runLabel(known[0]?.model_label) ||
    (ai ? t("{0} · Gründlichkeit {1}", { "0": String(ai.model_label || modelDisplayName(ai.model)), "1": String(effortLabel(ai.effort)) }) : '')

  const toggle = (id: string, on: boolean) =>
    setSelected((s) => {
      const next = new Set(s)
      if (on) next.add(id)
      else next.delete(id)
      return next
    })

  const start = async () => {
    setPending(true)
    const ids = chosen.map((i) => i.id)
    onClose()
    navigate('/import')
    await onAnalyze(ids)
    setPending(false)
  }

  return (
    <>
      <DialogHeader
        tone="spark"
        icon={<FileScan />}
        title={t("{0} gespeichert – jetzt analysieren?", { "0": String(plural(items.length, 'PDF', 'PDFs')) })}
        description={
          analyzable < items.length
            ? t("Claude liest jedes gewählte Datenblatt einzeln – jede Analyse kostet. Bereits analysierte bleiben, wie sie sind.")
            : t("Claude liest jedes gewählte Datenblatt einzeln – jede Analyse kostet.")
        }
      />
      <DialogBody className="flex flex-col gap-3 pt-2">
        <ul aria-label={t("Abgelegte Datenblätter")} className="divide-y divide-line rounded-card border border-line">
          {items.map((i, index) => {
            const disabled = i.state === 'analyzed'
            const est = estimates[index]
            const text = est?.data ? estimateText(est.data) : null
            return (
              <li key={i.id} className={cn('flex items-start gap-3 px-3 py-2.5', disabled && 'opacity-70')}>
                <Checkbox
                  aria-label={t("„{0}“ analysieren{1}", { "0": String(i.name), "1": String(text ? t(" – erwartet {0}", { "0": String(text.full) }) : '') })}
                  checked={selected.has(i.id)}
                  disabled={disabled}
                  onCheckedChange={(v) => toggle(i.id, v === true)}
                  className="mt-0.5"
                />
                <FileText aria-hidden className="mt-0.5 size-4 shrink-0 text-fg-subtle" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-ui font-medium text-fg" title={i.name}>
                    {i.name}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-fg-subtle">
                    {i.pageCount > 0 && <span className="tabular-nums">{plural(i.pageCount, t("Seite"), t("Seiten"))}</span>}
                    {est?.data && est.data.pages.length > 0 && <span>{plural(est.data.pages.length, t("Seite"), t("Seiten"))} {t(" für Claude")}</span>}
                    {i.state === 'failed' && (
                      <Badge variant="danger" size="sm">
                        <CircleAlert />
                        {t("Letzte Analyse fehlgeschlagen")}</Badge>
                    )}
                    {i.state === 'analyzed' && (
                      <Badge variant="spark" size="sm">
                        {t("Bereits analysiert")}</Badge>
                    )}
                    {i.state === 'new' && <Badge size="sm">{t("Neu")}</Badge>}
                  </div>
                  {i.state === 'failed' && i.error && <p className="mt-1 line-clamp-2 text-2xs leading-4 text-danger-text">{localizeMessage(i.error)}</p>}
                </div>
                {!disabled && (
                  <span aria-hidden className="mono shrink-0 pt-0.5 text-xs text-fg-muted">
                    {text ? text.typical : est?.isError ? '–' : <Spinner size={11} />}
                  </span>
                )}
              </li>
            )
          })}
        </ul>
        <p className="text-xs leading-relaxed text-fg-muted">
          {label || t("Standardeinstellungen")}
          {limit ? t(" · höchstens {0} je Datenblatt", { "0": String(formatUsd(limit)) }) : ''}{t(". Die Analysen laufen im Hintergrund – Fortschritt und Ergebnis stehen in der Liste.")}</p>
      </DialogBody>
      <DialogFooter className="justify-between">
        <div className="min-w-0 text-xs leading-snug text-fg-muted" aria-live="polite">
          {chosen.length ? (
            <>
              <div className="flex items-center gap-1.5">
                {t("Erwartet ")}<span className="mono whitespace-nowrap font-semibold text-fg">{known.length ? totalText.typical : '…'}</span>
                {loading && <Spinner size={11} />}
              </div>
              {totalText.upTo && known.length > 0 ? (
                <div className="text-2xs text-fg-subtle">{totalText.upTo}</div>
              ) : limit ? (
                <div className="text-2xs text-fg-subtle">{t("höchstens ")}{formatUsd(limit * chosen.length)}</div>
              ) : null}
            </>
          ) : (
            t("Nichts ausgewählt")
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onClose}>
            {t("Nur speichern")}</Button>
          <Button variant="spark" leftIcon={<FileScan />} loading={pending} disabled={!chosen.length} onClick={() => void start()}>
            {chosen.length ? t("{0} analysieren", { "0": String(plural(chosen.length, t("Datenblatt"), t("Datenblätter"))) }) : t("Analysieren")}
          </Button>
        </div>
      </DialogFooter>
    </>
  )
}
