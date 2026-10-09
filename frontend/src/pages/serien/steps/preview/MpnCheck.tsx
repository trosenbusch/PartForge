/**
 * „MPN prüfen“: eine Teilenummer mit der gewählten Serie lesen (`/api/series/decode`) – gültig? In dieser Vorschau
 * enthalten (Status, „Zeile zeigen“)? Passt sie nicht, wird mit allen Vorlagen gelesen („erkannt als …“).
 */
import { useMutation } from '@tanstack/react-query'
import { CircleCheck, CircleX, ScanSearch, TriangleAlert, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { errorMessage } from '@/api/client'
import { seriesApi, type DecodedMpn } from '@/api/series'
import { formatQuantityText } from '@/components/grid/cellFormat'
import { Button, IconButton, Input, Popover, PopoverAnchor, PopoverContent } from '@/components/ui'
import { cn } from '@/lib/cn'
import { ROW_STATUS, TONE_TEXT } from '../../model/status'
import type { GridRow } from './PreviewGrid'

const compact = (mpn: string) => mpn.replace(/[\s-]+/g, '').toUpperCase()

interface CheckResult {
  input: string
  own: DecodedMpn | null
  other: DecodedMpn | null
  row: GridRow | null
}

export interface MpnCheckProps {
  templateId: string
  templateTitle: string
  rows: GridRow[]
  sizes: string[]
  onReveal: (row: GridRow) => void
}

export function MpnCheck({ templateId, templateTitle, rows, sizes, onReveal }: MpnCheckProps) {
  const [text, setText] = useState('')
  const [result, setResult] = useState<CheckResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  /** „Zeile zeigen“: den Fokus bekommt die Tabelle, nicht wieder das Eingabefeld */
  const revealing = useRef(false)
  const check = useMutation({
    mutationFn: async (mpn: string): Promise<CheckResult> => {
      const own = (await seriesApi.decode(mpn, templateId)).best
      const other = own ? null : (await seriesApi.decode(mpn)).best
      const key = compact(own?.mpn ?? mpn)
      const row = rows.find((r) => compact(r.mpn) === key) ?? null
      return { input: mpn, own, other, row }
    },
    onSuccess: setResult,
    meta: { silentError: true },
  })

  const submit = () => {
    const mpn = text.trim()
    if (mpn) check.mutate(mpn)
  }

  let tone: 'success' | 'warning' | 'danger' = 'danger'
  let title = ''
  let detail: string | null = null
  if (result) {
    const d = result.own
    if (d && result.row) {
      tone = result.row.status === 'new' || result.row.status === 'exists' ? 'success' : 'warning'
      title = `${d.mpn} ist in dieser Vorschau – Status „${ROW_STATUS[result.row.status].label}“`
      detail = result.row.messages[0] ?? null
    } else if (d && d.valid) {
      tone = 'warning'
      title = `${d.mpn} gehört zur Serie, aber nicht zu dieser Auswahl`
      detail = d.size && !sizes.includes(d.size) ? `Bauform ${d.size} ist nicht gewählt.` : 'Wert oder Variante liegt außerhalb der Auswahl.'
    } else if (d) {
      tone = 'warning'
      title = `${d.mpn} folgt dem Muster, ist aber nicht lieferbar`
      detail = d.messages[0] ?? null
    } else if (result.other) {
      title = `Passt nicht zu ${templateTitle}`
      detail = `Erkannt als ${result.other.template_title} (${result.other.mpn}).`
    } else {
      title = `Keine Vorlage erkennt „${result.input}“`
      detail = 'Schreibweise prüfen oder eine eigene Vorlage anlegen.'
    }
  }
  const facts = result?.own
    ? [
        result.own.size ? `Bauform ${result.own.size}` : null,
        result.own.jumper ? '0-Ω-Brücke' : result.own.value_text ? formatQuantityText(result.own.value_text) : null,
        ...['Tolerance', 'TCR', 'Voltage', 'Power'].map((f) => (result.own?.fields[f] ? formatQuantityText(result.own.fields[f]) : null)),
      ].filter((x): x is string => Boolean(x))
    : []
  const Icon = tone === 'success' ? CircleCheck : tone === 'warning' ? TriangleAlert : CircleX

  return (
    <Popover
      open={Boolean(result) || check.isError}
      onOpenChange={(o) => {
        if (!o) {
          setResult(null)
          check.reset()
        }
      }}
    >
      <PopoverAnchor asChild>
        <form
          className="flex items-center gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <Input
            ref={inputRef}
            size="sm"
            mono
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Teilenummer prüfen …"
            aria-label="Teilenummer prüfen"
            spellCheck={false}
            autoComplete="off"
            prefix={<ScanSearch />}
            containerClassName="w-56"
          />
          <Button type="submit" size="sm" variant="secondary" loading={check.isPending} disabled={!text.trim()}>
            Prüfen
          </Button>
        </form>
      </PopoverAnchor>
      <PopoverContent
        align="end"
        side="bottom"
        className="w-[26rem] p-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onCloseAutoFocus={(e) => {
          e.preventDefault()
          if (!revealing.current) inputRef.current?.focus()
          revealing.current = false
        }}
        aria-label="Ergebnis der Prüfung"
      >
        {check.isError ? (
          <p className="px-4 py-3 text-xs text-danger-text">{errorMessage(check.error)}</p>
        ) : result ? (
          <div role="status" className="flex items-start gap-3 px-4 py-3">
            <span
              aria-hidden
              className={cn(
                'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full border',
                tone === 'success' && 'border-success/30 bg-success/10',
                tone === 'warning' && 'border-warning/30 bg-warning/10',
                tone === 'danger' && 'border-danger/30 bg-danger/10',
              )}
            >
              <Icon className={cn('size-4', TONE_TEXT[tone])} />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-ui font-medium leading-snug text-fg">{title}</p>
              {facts.length > 0 && <p className="mono mt-1 text-2xs text-fg-muted">{facts.join(' · ')}</p>}
              {detail && <p className="mt-1 text-xs text-fg-muted">{detail}</p>}
              {result.row && (
                <Button
                  size="xs"
                  variant="secondary"
                  className="mt-2.5"
                  onClick={() => {
                    revealing.current = true
                    setResult(null)
                    if (result.row) onReveal(result.row)
                  }}
                >
                  Zeile zeigen
                </Button>
              )}
            </div>
            <IconButton size="xs" label="Schließen" icon={<X />} onClick={() => setResult(null)} />
          </div>
        ) : null}
      </PopoverContent>
    </Popover>
  )
}
