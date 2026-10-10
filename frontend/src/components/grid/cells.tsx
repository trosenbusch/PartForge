import { useI18n, metadataLabel } from '@/lib/i18n'
import { useQuery } from '@tanstack/react-query'
import type { CustomCellRendererProps } from 'ag-grid-react'
import { CircuitBoard, Component as SymbolIcon, ExternalLink, FolderOpen } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Badge, Popover, PopoverAnchor, PopoverContent, Skeleton } from '@/components/ui'
import { FootprintCanvas } from '@/components/preview/FootprintCanvas'
import { SymbolCanvas } from '@/components/preview/SymbolCanvas'
import { errorMessage } from '@/api/client'
import { cn } from '@/lib/cn'
import { baseName } from '@/lib/format'
import type { FootprintSpec, SymbolSpec } from '@/lib/geometry'
import { canOpenPath, openPath } from '@/lib/native'
import { formatEngineering } from '@/lib/units'
import { formatQuantityText, isUrl, linkLabel, splitEnum, statusTone, type BadgeVariant, type StatusTone } from './cellFormat'

const EMPTY = <span className="text-fg-subtle">–</span>

// --------------------------------------------------------------------------- Werte

export interface QuantityCellParams {
  /** Einheit für reine Zahlenwerte (z. B. 'Ω') */
  unit?: string
  /** signifikante Stellen für Zahlen (Standard 3) */
  digits?: number
}

/** Technischer Wert: „10 kΩ“, „0,1 W“, „±1 %“ (Monospace, tabellarische Ziffern) */
export function QuantityCell({ value, unit, digits }: CustomCellRendererProps & QuantityCellParams) {
  useI18n()
  if (value === null || value === undefined || value === '') return EMPTY
  const text = typeof value === 'number' ? formatEngineering(value, unit ?? '', digits ?? 3) : formatQuantityText(String(value))
  return <span className="mono">{text}</span>
}

export interface EnumBadgeCellParams {
  /** Explicit display labels for declared options; arbitrary user values are preserved. */
  labels?: Record<string, string>
  /** Wert → Badge-Variante (Standard: neutral) */
  tones?: Record<string, BadgeVariant>
  mono?: boolean
}

/** Aufzählungswert(e) als Badge (Komma-/Semikolon-getrennte Werte als mehrere Badges) */
export function EnumBadgeCell({ value, tones, mono, labels }: CustomCellRendererProps & EnumBadgeCellParams) {
  useI18n()
  const values = splitEnum(value)
  if (!values.length) return EMPTY
  return (
    <span className="pf-cell-inline min-w-0 gap-1 overflow-hidden">
      {values.map((v) => (
        <Badge key={v} variant={tones?.[v] ?? 'neutral'} className={cn(mono && 'mono')}>
          {labels?.[v] ?? v}
        </Badge>
      ))}
    </span>
  )
}

export interface StatusCellParams {
  /** eigene Zuordnung Wert → Ton (zusätzlich zu den bekannten deutschen Statuswerten) */
  tones?: Record<string, StatusTone>
  /** Anzeigetexte je Wert */
  labels?: Record<string, string>
}

const DOT: Record<StatusTone, string> = {
  success: 'bg-success',
  warning: 'bg-warning',
  danger: 'bg-danger',
  info: 'bg-info',
  neutral: 'bg-fg-subtle',
  spark: 'bg-gradient-spark',
}

const TEXT: Record<StatusTone, string> = {
  success: 'text-fg',
  warning: 'text-warning-text',
  danger: 'text-danger-text',
  info: 'text-fg',
  neutral: 'text-fg-muted',
  spark: 'text-spark-text',
}

/** Status mit Farbpunkt (Lebenszyklus, Synchronisation, Import-Ergebnis) */
export function StatusCell({ value, tones, labels }: CustomCellRendererProps & StatusCellParams) {
  useI18n()
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value)
  const tone = statusTone(text, tones)
  return (
    <span className={cn('pf-cell-inline min-w-0 gap-2', TEXT[tone])}>
      <span aria-hidden className={cn('size-2 shrink-0 rounded-full', DOT[tone], (tone === 'success' || tone === 'danger') && 'shadow-[0_0_6px_currentColor]')} />
      <span className="truncate">{metadataLabel(labels?.[text] ?? text)}</span>
    </span>
  )
}

export interface LinkCellParams {
  /** url (Standard bei http…), path (Datei/Ordner im Explorer öffnen) */
  kind?: 'url' | 'path'
  /** eigener Anzeigetext */
  label?: (value: string) => string
}

/** Link (Datenblatt-URL) oder Pfad (öffnet im Explorer, sofern die Desktop-Brücke es anbietet) */
export function LinkCell({ value, kind, label }: CustomCellRendererProps & LinkCellParams) {
  const { t: tr } = useI18n()
  if (value === null || value === undefined || value === '') return EMPTY
  const text = String(value)
  const asUrl = kind ? kind === 'url' : isUrl(text)
  if (asUrl) {
    return (
      <a
        href={text}
        target="_blank"
        rel="noreferrer noopener"
        tabIndex={-1}
        title={text}
        onClick={(e) => e.stopPropagation()}
        className="group/link pf-cell-inline min-w-0 gap-1.5 text-accent-text underline-offset-2 hover:underline"
      >
        <ExternalLink aria-hidden className="size-3.5 shrink-0 opacity-70 group-hover/link:opacity-100" />
        <span className="truncate">{label ? label(text) : linkLabel(text)}</span>
      </a>
    )
  }
  const openable = canOpenPath()
  const content = (
    <>
      <FolderOpen aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
      <span className="truncate">{label ? label(text) : baseName(text.replace(/\\/g, '/'))}</span>
    </>
  )
  return openable ? (
    <button
      type="button"
      tabIndex={-1}
      title={tr("{0} – im Explorer öffnen", { "0": String(text) })}
      onClick={(e) => {
        e.stopPropagation()
        void openPath(text)
      }}
      className="pf-cell-inline min-w-0 gap-1.5 text-fg hover:text-accent-text"
    >
      {content}
    </button>
  ) : (
    <span title={text} className="pf-cell-inline min-w-0 gap-1.5">
      {content}
    </span>
  )
}

// --------------------------------------------------------------------------- Symbol-/Footprint-Verweis mit Vorschau

/** Was ein Vorschau-Lader liefert: Spec (bevorzugt) oder fertiges SVG */
export interface RefPreview {
  symbol?: SymbolSpec | null
  footprint?: FootprintSpec | null
  /** SVG-Markup (z. B. vom Backend-Renderer) als Bild */
  svg?: string | null
  /** Zusatzzeile (Bibliothek, Beschreibung) */
  description?: string | null
}

export interface RefCellParams<TData = unknown> {
  /**
   * Vorschau laden (gecacht über React Query). Ohne Lader zeigt die Karte nur Name und Bibliothek.
   * Beispiel: `(ref, row, signal) => api.post('/api/footprints/preview', requestFor(row), { signal }).then((p) => ({ footprint: p.spec }))`
   */
  loadPreview?: (ref: string, row: TData | undefined, signal: AbortSignal) => Promise<RefPreview | null>
  /** Spalte mit dem Bibliothekspfad (z. B. „Library Path“ / „Footprint Path“) */
  libraryField?: string
}

function SvgImage({ svg, alt }: { svg: string; alt: string }) {
  useI18n()
  const url = useMemo(() => URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' })), [svg])
  useEffect(() => () => URL.revokeObjectURL(url), [url])
  return <img src={url} alt={alt} className="size-full object-contain p-3" />
}

function RefPreviewBody({
  kind,
  name,
  row,
  loader,
}: {
  kind: 'symbol' | 'footprint'
  name: string
  row: unknown
  loader?: RefCellParams['loadPreview']
}) {
  const { t: tr } = useI18n()
  const q = useQuery({
    queryKey: [kind === 'symbol' ? 'symbols' : 'footprints', 'ref-preview', name],
    queryFn: ({ signal }) => (loader ? loader(name, row, signal) : Promise.resolve(null)),
    enabled: Boolean(loader),
    staleTime: 5 * 60_000,
  })
  const board = kind === 'footprint'
  if (!loader) {
    return <div className="flex h-full items-center justify-center px-4 text-center text-xs text-fg-subtle">{tr("Keine Vorschau verfügbar")}</div>
  }
  if (q.isPending) return <Skeleton className="m-3 h-[calc(100%-24px)]" />
  if (q.isError) return <div className="flex h-full items-center justify-center px-4 text-center text-xs text-danger-text">{errorMessage(q.error)}</div>
  const data = q.data
  if (data?.symbol && !board) {
    return <SymbolCanvas spec={data.symbol} interactive={false} controls={false} showInfo={false} showPartTabs={false} className="size-full" />
  }
  if (data?.footprint && board) {
    return (
      <FootprintCanvas
        spec={data.footprint}
        interactive={false}
        controls={false}
        showInfo={false}
        showLegend={false}
        className="size-full"
      />
    )
  }
  if (data?.svg) return <SvgImage svg={data.svg} alt={name} />
  return <div className="flex h-full items-center justify-center text-xs text-fg-subtle">{tr("Keine Vorschau verfügbar")}</div>
}

function RefCell({
  kind,
  value,
  data,
  loadPreview,
  libraryField,
  icon,
}: CustomCellRendererProps &
  RefCellParams & {
    kind: 'symbol' | 'footprint'
    icon: ReactNode
  }) {
  const { t: tr } = useI18n()
  const [open, setOpen] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [tr])
  if (value === null || value === undefined || value === '') return EMPTY
  const name = String(value)
  const library =
    libraryField && data && typeof data === 'object' ? (data as Record<string, unknown>)[libraryField] : undefined
  const enter = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(true), 380)
  }
  const leave = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setOpen(false), 160)
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <button
          type="button"
          tabIndex={-1}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-label={tr("{0} {1} – Vorschau", { "0": String(kind === 'symbol' ? 'Symbol' : 'Footprint'), "1": String(name) })}
          onPointerEnter={enter}
          onPointerLeave={leave}
          onClick={(e) => {
            e.stopPropagation()
            window.clearTimeout(timer.current)
            setOpen((o) => !o)
          }}
          className="pf-cell-inline min-w-0 gap-1.5 text-left text-fg outline-none hover:text-accent-text"
        >
          <span aria-hidden className="flex shrink-0 text-fg-subtle [&_svg]:size-3.5">
            {icon}
          </span>
          <span className="mono truncate">{name}</span>
        </button>
      </PopoverAnchor>
      <PopoverContent
        side="right"
        align="start"
        className="w-[320px] overflow-hidden p-0"
        onOpenAutoFocus={(e) => e.preventDefault()}
        onPointerEnter={() => window.clearTimeout(timer.current)}
        onPointerLeave={leave}
      >
        <div className="flex items-center gap-2 border-b border-line px-3 py-2">
          <span aria-hidden className="text-fg-subtle [&_svg]:size-4">
            {icon}
          </span>
          <div className="min-w-0">
            <div className="mono truncate text-ui font-semibold text-fg">{name}</div>
            {typeof library === 'string' && library && (
              <div className="truncate text-2xs text-fg-subtle">{baseName(library.replace(/\\/g, '/'))}</div>
            )}
          </div>
        </div>
        <div className={cn('h-[200px]', kind === 'footprint' ? 'bg-canvas' : 'bg-bg')}>
          {open && <RefPreviewBody kind={kind} name={name} row={data} loader={loadPreview} />}
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** Symbolverweis („Library Ref“) mit Vorschau beim Überfahren (bzw. Enter auf der Zelle) */
export function SymbolRefCell(props: CustomCellRendererProps & RefCellParams) {
  useI18n()
  return <RefCell {...props} kind="symbol" icon={<SymbolIcon />} />
}

/** Footprintverweis („Footprint Ref“) mit Vorschau beim Überfahren (bzw. Enter auf der Zelle) */
export function FootprintRefCell(props: CustomCellRendererProps & RefCellParams) {
  useI18n()
  return <RefCell {...props} kind="footprint" icon={<CircuitBoard />} />
}
