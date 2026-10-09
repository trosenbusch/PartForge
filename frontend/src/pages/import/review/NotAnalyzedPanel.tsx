import { ArrowRight, CircleAlert, FileScan, KeyRound } from 'lucide-react'
import { Link } from 'react-router'
import { useCostEstimate, type AiStatus, type DatasheetDetail } from '@/api/datasheets'
import { modelDisplayName } from '@/app/shell/useSystemStatus'
import { Button, Illustration } from '@/components/ui'
import { plural } from '@/lib/format'
import { effortLabel, estimateText, formatUsd } from '../lib/format'

/** Datenblatt ohne Analyse: Ursache (kein Schlüssel, Fehler), Kosten bisher und der Weg zur Analyse. */
export function NotAnalyzedPanel({
  ds,
  aiReady,
  aiStatus,
  onAnalyze,
}: {
  ds: DatasheetDetail
  aiReady: boolean
  aiStatus: AiStatus | undefined
  onAnalyze: () => void
}) {
  const imagePages = ds.pages.filter((p) => p.quality !== 'ok').length
  // erwartete Kosten mit den Standardeinstellungen (Schätzung des Backends, keine Claude-Anfrage)
  const est = useCostEstimate(ds.id, null, { enabled: aiReady })
  const expected = est.data ? estimateText(est.data) : null
  return (
    <div className="flex h-full flex-col items-center justify-center overflow-y-auto bg-bg px-8 py-10 text-center">
      <div className="relative mb-6">
        <div aria-hidden className="dot-grid mask-radial absolute -inset-10 opacity-80" />
        <Illustration name="drop-pdf" className="relative h-auto w-44" />
      </div>
      <h2 className="text-h3 font-semibold tracking-[-0.02em] text-fg">{ds.last_error ? 'Analyse fehlgeschlagen' : 'Noch nicht analysiert'}</h2>
      <p className="mt-2 max-w-md text-ui leading-relaxed text-fg-muted">
        {ds.last_error
          ? 'Die letzte Analyse ist nicht durchgelaufen. Bereits bezahlte Anfragen sind gespeichert – ein neuer Versuch, gern mit selbst gewählten Seiten, kostet erneut.'
          : `Das PDF ist gespeichert (${plural(ds.page_count, 'Seite', 'Seiten')}${imagePages ? `, ${imagePages} ohne Textebene` : ''}). Claude liest daraus Bestellnummern, Parameter, Pinbelegung und Gehäusemaße.`}
      </p>
      {ds.last_error && (
        <p className="mt-3 flex max-w-md items-start gap-2 rounded-card border border-danger/30 bg-danger/8 px-3.5 py-2.5 text-left text-xs leading-relaxed text-danger-text">
          <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          {ds.last_error}
        </p>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
        {aiReady ? (
          <Button variant="spark" size="lg" leftIcon={<FileScan />} onClick={onAnalyze}>
            Mit Claude analysieren
          </Button>
        ) : (
          <Button asChild variant="secondary" size="lg">
            <Link to="/einstellungen#ki">
              <KeyRound aria-hidden />{aiStatus?.enabled === false ? 'KI einschalten' : 'Claude-API-Schlüssel hinterlegen'}<ArrowRight aria-hidden />
            </Link>
          </Button>
        )}
      </div>
      <p className="mt-3 text-xs text-fg-subtle">
        {aiStatus
          ? [
              `${aiStatus.model_label || modelDisplayName(aiStatus.model)} · Gründlichkeit ${effortLabel(aiStatus.effort)}`,
              aiReady && expected ? `erwartet ${expected.typical}` : null,
              aiReady && est.data?.pages.length ? `${plural(est.data.pages.length, 'Seite', 'Seiten')} für Claude` : null,
              `höchstens ${formatUsd(aiStatus.max_cost_per_import_usd)} je Import`,
            ]
              .filter(Boolean)
              .join(' · ')
          : ''}
        {ds.cost_usd > 0 ? ` · bisher ${formatUsd(ds.cost_usd)}` : ''}
      </p>
    </div>
  )
}
