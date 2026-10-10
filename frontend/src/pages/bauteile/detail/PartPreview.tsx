import { localizeMessage, useI18n } from '@/lib/i18n'
/**
 * Vorschau eines Bauteils (Symbol | Footprint | 3D) aus der Bibliothek: Geometrie über
 * `GET /api/libraries/symbols/{name}?svg=false` bzw. `…/footprints/{name}?svg=false` (die Leinwände zeichnen selbst).
 * Nicht registrierte Verweise zeigen einen ruhigen Platzhalter mit dem Namen statt eines Fehlers. Darunter der Stand in
 * den Bibliotheksdateien: ist das Symbol schon in der SchLib, der Footprint in der PcbLib – oder steht das Schreiben aus?
 */
import { CircuitBoard, Component as SymbolIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { errorMessage } from '@/api/client'
import {
  findEntry,
  useLibraryFootprint,
  useLibraryFootprints,
  useLibrarySymbol,
  useLibrarySymbols,
  type LibraryItemState,
  type PartRow,
} from '@/api/parts'
import type { StatusTone } from '@/components/grid/cellFormat'
import { PreviewPanel } from '@/components/preview'
import { cn } from '@/lib/cn'
import { baseName } from '@/lib/format'
import { STATUS_DOT, STATUS_TEXT } from '../model/status'
import { useBauteile } from '../model/store'

function Placeholder({ icon, title, name, hint }: { icon: ReactNode; title: string; name?: string | null; hint: string }) {
  useI18n()
  return (
    <span className="flex max-w-72 flex-col items-center gap-2 text-center">
      <span aria-hidden className="flex size-9 items-center justify-center rounded-button border border-line-strong bg-surface-2/80 text-fg-subtle [&_svg]:size-4">
        {icon}
      </span>
      <span className="text-ui font-medium text-fg">{title}</span>
      {name && <span className="mono rounded-control bg-surface-3/70 px-2 py-0.5 text-xs text-fg">{name}</span>}
      <span className="text-xs leading-relaxed text-fg-muted">{hint}</span>
    </span>
  )
}

function stateText(item: LibraryItemState<unknown>): { notRegistered: boolean; message: string | null } {
  return { notRegistered: item.notRegistered, message: item.error ? errorMessage(item.error) : null }
}

export function PartPreview({ row, designatorPrefix, className }: { row: PartRow; designatorPrefix: string; className?: string }) {
  const { t } = useI18n()
  const symbolName = row['Library Ref'] || null
  const footprintName = row['Footprint Ref'] || null
  const symbol = useLibrarySymbol(symbolName)
  const footprint = useLibraryFootprint(footprintName)
  const s = stateText(symbol)
  const f = stateText(footprint)
  const tab = useBauteile((st) => st.previewTab)
  const setTab = useBauteile((st) => st.setPreviewTab)

  const symbolEmpty = !symbolName ? (
    <Placeholder icon={<SymbolIcon />} title={t("Kein Symbol zugeordnet")} hint={t("Im Feld „Symbol“ ein Bibliothekssymbol wählen.")} />
  ) : s.notRegistered || (symbol.data && !symbol.data.spec) ? (
    <Placeholder
      icon={<SymbolIcon />}
      title={s.notRegistered ? t("Nicht in der Bibliothek registriert") : t("Keine Geometrie gespeichert")}
      name={symbolName}
      hint={t("Das Symbol liegt nicht in einer PartForge-Bibliothek – Altium findet es nur, wenn die SchLib es enthält.")}
    />
  ) : null

  const footprintEmpty = !footprintName ? (
    <Placeholder icon={<CircuitBoard />} title={t("Kein Footprint zugeordnet")} hint={t("Im Feld „Footprint“ einen Footprint der Bibliothek wählen.")} />
  ) : f.notRegistered || (footprint.data && !footprint.data.spec) ? (
    <Placeholder
      icon={<CircuitBoard />}
      title={f.notRegistered ? t("Nicht in der Bibliothek registriert") : t("Keine Geometrie gespeichert")}
      name={footprintName}
      hint={t("Der Footprint liegt nicht in einer PartForge-Bibliothek – Altium findet ihn nur, wenn die PcbLib ihn enthält.")}
    />
  ) : null

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <PreviewPanel
        tab={tab}
        onTabChange={setTab}
        symbol={symbol.data?.spec ?? null}
        footprint={footprint.data?.spec ?? null}
        loading={{ symbol: symbol.isFetching && !symbol.data, footprint: footprint.isFetching && !footprint.data }}
        error={{ symbol: s.message, footprint: f.message }}
        emptyText={{
          symbol: symbolEmpty ?? t("Kein Symbol"),
          footprint: footprintEmpty ?? t("Kein Footprint"),
          '3d': footprintEmpty ?? t("Kein Footprint"),
        }}
        designator={`${designatorPrefix}?`}
        comment={row.Comment ?? row.Value ?? undefined}
        title={[row['Part Number'], symbolName, footprintName].filter(Boolean).join(' · ')}
        className="h-[272px]"
      />
      {(symbolName || footprintName) && (
        <ul aria-label={t("Stand in den Bibliotheksdateien")} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-1 text-2xs">
          {symbolName && <LibraryStatus kind="symbol" name={symbolName} />}
          {footprintName && <LibraryStatus kind="footprint" name={footprintName} />}
        </ul>
      )}
    </div>
  )
}

const FILE_LABEL = { symbol: 'SchLib', footprint: 'PcbLib' } as const

/** Stand eines Verweises in der Bibliotheksdatei (aus der Registrierung: ok, ausstehend, fehlt, Fehler) */
function LibraryStatus({ kind, name }: { kind: 'symbol' | 'footprint'; name: string }) {
  const { t } = useI18n()
  const symbols = useLibrarySymbols(kind === 'symbol')
  const footprints = useLibraryFootprints(kind === 'footprint')
  const q = kind === 'symbol' ? symbols : footprints
  if (q.isPending || q.isError) return null
  const entry = findEntry<{ name: string; status: string; library: string; status_message: string | null }>(q.data, name)
  const file = FILE_LABEL[kind]
  const what = kind === 'symbol' ? 'Symbol' : 'Footprint'
  let tone: StatusTone = 'neutral'
  let text = t("nicht registriert")
  if (entry?.status === 'ok') {
    tone = 'success'
    text = t("in der {1}", { 1: file })
  } else if (entry?.status === 'pending') {
    tone = 'warning'
    text = t("noch nicht in die {1} geschrieben", { 1: file })
  } else if (entry?.status === 'missing') {
    tone = 'danger'
    text = t("fehlt in der {1}", { 1: file })
  } else if (entry) {
    tone = 'danger'
    text = t("Fehler beim Schreiben")
  }
  const title = entry ? [entry.library, entry.status_message ? localizeMessage(entry.status_message) : null].filter(Boolean).join(' – ') : undefined
  return (
    <li className="flex min-w-0 items-center gap-1.5" title={title}>
      <span aria-hidden className={cn('size-1.5 shrink-0 rounded-full', STATUS_DOT[tone])} />
      <span className="text-fg-subtle">{what}</span>
      <span className={cn('min-w-0 truncate', tone === 'success' ? 'text-fg-muted' : STATUS_TEXT[tone])}>
        {text}
        {entry?.library && tone === 'success' && <span className="text-fg-subtle"> · {baseName(entry.library.replace(/\\/g, '/'))}</span>}
      </span>
    </li>
  )
}
