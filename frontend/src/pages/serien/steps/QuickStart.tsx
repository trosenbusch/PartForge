/**
 * Schnellstart: eine Teilenummer einfügen – PartForge erkennt Hersteller-Serie, Baugröße und Codes
 * (`/api/series/decode`) und übernimmt sie als Auswahl.
 */
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, CircleCheck, FilePlus2, ScanLine, TriangleAlert } from 'lucide-react'
import { useEffect, useId, useState } from 'react'
import { errorMessage } from '@/api/client'
import { queryClient } from '@/api/queryClient'
import { seriesApi, seriesKeys, useSeriesTemplate, type DecodedMpn } from '@/api/series'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { Badge, Button, Card, Input, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { MpnAnatomy } from '../components/MpnAnatomy'
import { useDebounced } from '../components/useDebounced'
import { splitMpn } from '../model/anatomy'

export interface QuickStartApply {
  decoded: DecodedMpn
}

const EXAMPLES = ['CRCW060310K0FKEA', 'RC0603FR-0710KL', 'C0603C104K5RACTU']
const FIELD_ORDER = ['Tolerance', 'TCR', 'Voltage', 'Power', 'Dielectric', 'Current Rating']

interface Chip {
  /** Beschriftung in Klartext (optional) */
  label?: string
  value: string
  mono: boolean
}

const decodeOptions = (mpn: string) => ({
  queryKey: seriesKeys.decode(mpn, null),
  queryFn: ({ signal }: { signal: AbortSignal }) => seriesApi.decode(mpn, null, signal),
  staleTime: 60_000,
})

export function QuickStart({
  onApply,
  onDecodedChange,
  onCustomTemplate,
}: {
  onApply: (apply: QuickStartApply) => void
  /** erkannte Serie (oder null) – z. B. für die Primäraktion der Fußleiste */
  onDecodedChange?: (decoded: DecodedMpn | null) => void
  onCustomTemplate: () => void
}) {
  const id = useId()
  const [text, setText] = useState('')
  const query = useDebounced(text.trim(), 380)
  const decode = useQuery({ ...decodeOptions(query), enabled: query.length >= 4 })
  const best = query.length >= 4 ? decode.data?.best : undefined
  const detail = useSeriesTemplate(best?.template_id ?? null)
  const segments = best && detail.data ? splitMpn(detail.data, best) : null
  const others = (decode.data?.matches ?? []).filter((m) => m.template_id !== best?.template_id)
  const pending = text.trim() !== query || decode.isFetching
  const shown = best && !pending ? best : null

  const report = onDecodedChange
  useEffect(() => {
    report?.(shown)
  }, [shown, report])
  useEffect(() => () => report?.(null), [report])

  /** Enter direkt nach dem Einfügen: nicht auf die Entprellung warten */
  const applyNow = async () => {
    const mpn = text.trim()
    if (mpn.length < 4) return
    if (best && mpn === query) {
      onApply({ decoded: best })
      return
    }
    try {
      const result = await queryClient.fetchQuery(decodeOptions(mpn))
      if (result.best && text.trim() === mpn) onApply({ decoded: result.best })
    } catch {
      // Fehler zeigt die Abfrage selbst, sobald die Eingabe entprellt ist
    }
  }

  const chips: Chip[] = best
    ? [
        best.size ? { label: 'Baugröße', value: best.size, mono: true } : null,
        best.jumper
          ? { value: '0-Ω-Brücke', mono: false }
          : best.value_text
            ? { value: formatQuantityText(best.value_text), mono: true }
            : null,
        ...FIELD_ORDER.map((f) => (best.fields[f] ? { value: formatQuantityText(best.fields[f]), mono: true } : null)),
      ].filter((c): c is Chip => c !== null)
    : []

  return (
    <Card className="flex flex-col">
      <div className="flex items-start gap-3 px-4 pb-3 pt-4">
        <span
          aria-hidden
          className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted"
        >
          <ScanLine className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id={`${id}-title`} className="text-sm font-semibold text-fg">
            Schnellstart aus einer Teilenummer
          </h3>
          <p className="mt-0.5 text-xs text-fg-muted">
            Teilenummer einfügen – Serie, Baugröße, Toleranz und Verpackung werden übernommen.
          </p>
        </div>
      </div>
      <div className="flex flex-col gap-3 px-4 pb-4">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.ctrlKey && !e.metaKey) {
              e.preventDefault()
              void applyNow()
            }
          }}
          mono
          spellCheck={false}
          autoComplete="off"
          placeholder="z. B. CRCW060310K0FKEA"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-result`}
          prefix={<ScanLine className="size-4" />}
          suffix={pending && query.length >= 4 ? <Spinner size={14} /> : undefined}
        />
        <div id={`${id}-result`} aria-live="polite">
          {query.length < 4 ? (
            <div className="flex flex-wrap items-center gap-1.5 text-xs text-fg-subtle">
              <span>Beispiele:</span>
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => setText(ex)}
                  className="mono rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-2xs text-fg-muted outline-none transition-colors hover:border-line-strong hover:text-fg focus-ring"
                >
                  {ex}
                </button>
              ))}
            </div>
          ) : decode.isError ? (
            <p className="text-xs text-danger-text">{errorMessage(decode.error)}</p>
          ) : best ? (
            <div className="flex flex-col gap-2.5 rounded-control border border-line bg-surface-2/50 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="micro-label">{best.manufacturer}</div>
                  <div className="truncate text-ui font-medium text-fg">{best.template_title}</div>
                </div>
                {best.valid ? (
                  <Badge variant="success">
                    <CircleCheck />
                    Lieferbar laut Datenblatt
                  </Badge>
                ) : (
                  <Badge variant="warning">
                    <TriangleAlert />
                    Nicht lieferbar
                  </Badge>
                )}
              </div>
              <MpnAnatomy mpn={best.mpn} segments={segments} labels size="md" />
              {chips.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {chips.map((c) => (
                    <Badge key={`${c.label ?? ''}${c.value}`} variant="neutral">
                      {c.label}
                      <span className={cn(c.mono && 'mono', c.label && 'text-fg')}>{c.value}</span>
                    </Badge>
                  ))}
                </div>
              )}
              {best.messages.length > 0 && <p className="text-xs text-fg-muted">{best.messages[0]}</p>}
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-2xs text-fg-subtle">
                  {others.length > 0 ? `Passt auch zu: ${others.map((o) => o.template_title).join(', ')}` : ''}
                </span>
                <Button variant="secondary" size="sm" rightIcon={<ArrowRight />} onClick={() => onApply({ decoded: best })}>
                  Serie übernehmen
                </Button>
              </div>
            </div>
          ) : decode.isSuccess && !pending ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-dashed border-line-strong px-3 py-2.5">
              <p className="text-xs text-fg-muted">
                Keine Hersteller-Serie erkennt <span className="mono text-fg">{query}</span>.
              </p>
              <Button variant="ghost" size="sm" leftIcon={<FilePlus2 />} onClick={onCustomTemplate}>
                Eigene Vorlage anlegen
              </Button>
            </div>
          ) : null}
        </div>
      </div>
    </Card>
  )
}
