import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Vorschau-Panel „Symbol | Footprint | 3D“ mit Werkzeugleiste (Einpassen, Zoom, Lagen, Bemaßung, Altium-Ansicht,
 * automatische Drehung, Vollbild). Für Detail-Drawer, Generatoren und den Datenblatt-Import.
 *
 *   <PreviewPanel symbol={symbolSpec} footprint={fp.spec} calc={fp.calc} highlight={['1']} className="h-[420px]" />
 */
import {
  TriangleAlert,
  Box as BoxIcon,
  CircuitBoard,
  Columns3,
  Layers,
  Maximize2,
  Minus,
  Plus,
  Rotate3d,
  RotateCcw,
  Ruler,
  Scan,
  Square,
  Component as SymbolIcon,
} from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import type { StepSource } from '@/api/stepModels'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  SegmentedControl,
  Skeleton,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import {
  LAYERS,
  footprintLayers,
  layerColor,
  type CanvasLayer,
  type FootprintSpec,
  type SymbolSpec,
} from '@/lib/geometry'
import { FootprintCanvas } from './FootprintCanvas'
import { DEFAULT_LAYER_VISIBILITY } from './layerVisibility'
import { Package3D } from './Package3D'
import { usePreviewPrefs } from './previewPrefs'
import { SymbolCanvas } from './SymbolCanvas'
import type { CanvasHandle } from './types'

export type PreviewTab = 'symbol' | 'footprint' | '3d'
export type PreviewLayout = 'tabs' | 'split'

type PerTab<T> = T | Partial<Record<PreviewTab, T>>

export interface PreviewPanelProps {
  symbol?: SymbolSpec | null
  footprint?: FootprintSpec | null
  stepSource?: StepSource
  /** Rechenprotokoll des Footprint-Generators (Bemaßung Zmax/Gmin/Xmax) */
  calc?: unknown
  tab?: PreviewTab
  defaultTab?: PreviewTab
  onTabChange?: (tab: PreviewTab) => void
  /** Pin-/Padnummern hervorheben (Symbol und Footprint) */
  highlight?: readonly string[]
  /** Lädt (je Ansicht oder für alle) – vorhandene Inhalte bleiben sichtbar */
  loading?: PerTab<boolean>
  /** Fehlertext (je Ansicht oder für alle) */
  error?: PerTab<string | null | undefined>
  /** Text bei fehlendem Inhalt je Ansicht */
  emptyText?: Partial<Record<PreviewTab, ReactNode>>
  /** Zusätzliche Aktionen rechts in der Werkzeugleiste (z. B. STEP-Download) */
  actions?: ReactNode
  /** Titel des Vollbild-Dialogs (Standard: Symbol-/Footprintname) */
  title?: string
  /** Symbol: echter Bezeichner/Kommentar statt „U?“/„*“ */
  designator?: string
  comment?: string
  /** Ansichten ohne Inhalt ausblenden (Standard: nein – sie zeigen einen Hinweis) */
  hideEmptyTabs?: boolean
  /** Vollbild-Knopf (Standard: an) */
  allowFullscreen?: boolean
  /** Vollbild-Dialog geöffnet (kontrolliert) */
  fullscreen?: boolean
  defaultFullscreen?: boolean
  onFullscreenChange?: (open: boolean) => void
  /** Darstellung: Reiter oder alle Ansichten nebeneinander */
  layout?: PreviewLayout
  /** Umschalter „Einzeln | Nebeneinander“ zeigen (im Vollbild automatisch) */
  allowLayoutSwitch?: boolean
  className?: string
}

const TAB_LABEL: Record<PreviewTab, string> = { symbol: 'Symbol', footprint: 'Footprint', '3d': '3D' }
const TAB_ICON: Record<PreviewTab, ReactNode> = {
  symbol: <SymbolIcon />,
  footprint: <CircuitBoard />,
  '3d': <BoxIcon />,
}

function perTab<T>(value: PerTab<T> | undefined, tab: PreviewTab): T | undefined {
  if (value !== null && typeof value === 'object' && !Array.isArray(value)) return (value as Partial<Record<PreviewTab, T>>)[tab]
  return value as T | undefined
}

/** Platzhalter, Ladezustand und Fehler über der Leinwand */
function ViewState({
  hasContent,
  loading,
  error,
  empty,
  board,
}: {
  hasContent: boolean
  loading?: boolean
  error?: string | null
  empty: ReactNode
  board?: boolean
}) {
  useI18n()
  if (!hasContent && loading) {
    return (
      <div className={cn('absolute inset-0 flex items-center justify-center', board ? 'bg-canvas' : 'bg-bg')}>
        <Skeleton className="absolute inset-6 rounded-card opacity-40" />
        <div
          className={cn(
            'relative flex items-center gap-2 rounded-full px-3.5 py-1.5 text-xs',
            board ? 'border border-white/10 bg-white/5 text-[#C9D1DE]' : 'border border-line bg-surface text-fg-muted',
          )}
        >
          <Spinner size={14} tone="accent" />
          {tr("Vorschau wird berechnet …")}
        </div>
      </div>
    )
  }
  return (
    <>
      {!hasContent && !error && (
        <div
          className={cn(
            'absolute inset-0 flex items-center justify-center px-6 text-center text-ui',
            board ? 'bg-canvas text-[#9AA4B6]' : 'bg-bg text-fg-subtle',
          )}
        >
          {empty}
        </div>
      )}
      {loading && hasContent && (
        <div className="pointer-events-none absolute right-3 top-12 z-20 flex items-center gap-1.5 rounded-full border border-line-strong bg-surface/90 px-2.5 py-1 text-2xs text-fg-muted shadow-raised backdrop-blur">
          <Spinner size={12} tone="accent" />
          {tr("aktualisiert …")}
        </div>
      )}
      {error && (
        <div className={cn('absolute inset-0 z-20 flex items-center justify-center p-6', hasContent && 'bg-[color-mix(in_oklab,var(--pf-bg)_55%,transparent)] backdrop-blur-[2px]')}>
          <div role="alert" className="flex max-w-md items-start gap-2.5 rounded-card border border-danger/30 bg-surface px-4 py-3 text-ui shadow-raised">
            <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-danger-text" />
            <div>
              <div className="font-semibold text-fg">{tr("Vorschau nicht möglich")}</div>
              <p className="mt-0.5 text-xs leading-relaxed text-fg-muted">{localizeMessage(error)}</p>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

export function PreviewPanel({
  symbol,
  footprint,
  stepSource,
  calc,
  tab: tabProp,
  defaultTab,
  onTabChange,
  highlight,
  loading,
  error,
  emptyText,
  actions,
  title,
  designator,
  comment,
  hideEmptyTabs = false,
  allowFullscreen = true,
  fullscreen: fullscreenProp,
  defaultFullscreen = false,
  onFullscreenChange,
  layout: layoutProp,
  allowLayoutSwitch = false,
  className,
}: PreviewPanelProps) {
  useI18n()
  const prefs = usePreviewPrefs()
  const available: PreviewTab[] = useLocalizedMemo(() => {
    const all: PreviewTab[] = ['symbol', 'footprint', '3d']
    if (!hideEmptyTabs) return all
    return all.filter((t) =>
      t === 'symbol' ? Boolean(symbol) || Boolean(perTab(loading, t)) : Boolean(footprint) || (t === '3d' && Boolean(stepSource)) || Boolean(perTab(loading, t)),
    )
  }, [hideEmptyTabs, symbol, footprint, stepSource, loading])

  const [innerTab, setInnerTab] = useState<PreviewTab>(defaultTab ?? (symbol ? 'symbol' : footprint ? 'footprint' : 'symbol'))
  const tab = available.includes(tabProp ?? innerTab) ? (tabProp ?? innerTab) : (available[0] ?? 'symbol')
  const setTab = (t: PreviewTab) => {
    if (tabProp === undefined) setInnerTab(t)
    onTabChange?.(t)
  }
  const [innerLayout, setInnerLayout] = useState<PreviewLayout>(layoutProp ?? 'tabs')
  const layout = layoutProp ?? innerLayout

  const [innerFullscreen, setInnerFullscreen] = useState(defaultFullscreen)
  const fullscreen = allowFullscreen && (fullscreenProp ?? innerFullscreen)
  const setFullscreen = (open: boolean) => {
    if (fullscreenProp === undefined) setInnerFullscreen(open)
    onFullscreenChange?.(open)
  }
  const [zoom, setZoom] = useState(1)
  const [hover, setHover] = useState<string | null>(null)

  const symbolRef = useRef<CanvasHandle>(null)
  const footprintRef = useRef<CanvasHandle>(null)
  const threeRef = useRef<CanvasHandle>(null)
  const activeRef = tab === 'symbol' ? symbolRef : tab === 'footprint' ? footprintRef : threeRef

  const presentLayers = useLocalizedMemo(() => (footprint ? footprintLayers(footprint) : []), [footprint])
  const layerVisible = (l: CanvasLayer) => prefs.layers[l] ?? DEFAULT_LAYER_VISIBILITY[l]
  const hasCalc = Boolean(calc)

  const symbolView = (controls: boolean) => (
    <div className="relative size-full">
      <SymbolCanvas
        ref={symbolRef}
        spec={symbol}
        theme={prefs.altium ? 'altium' : 'auto'}
        highlight={highlight}
        hoverDesignator={layout === 'split' ? hover : null}
        onPinHover={(p) => setHover(p?.designator ?? null)}
        designator={designator}
        comment={comment}
        controls={controls}
        onZoomChange={tab === 'symbol' ? setZoom : undefined}
        className="absolute inset-0"
      />
      <ViewState
        hasContent={Boolean(symbol)}
        loading={perTab(loading, 'symbol')}
        error={perTab(error, 'symbol')}
        empty={emptyText?.symbol ?? tr('Kein Symbol zugeordnet')}
      />
    </div>
  )

  const footprintView = (controls: boolean) => (
    <div className="relative size-full">
      <FootprintCanvas
        ref={footprintRef}
        spec={footprint}
        calc={calc}
        showDimensions={hasCalc ? prefs.dimensions : false}
        highlight={highlight}
        hoverDesignator={layout === 'split' ? hover : null}
        onPadHover={(p) => setHover(p?.designator ?? null)}
        layers={prefs.layers}
        onLayersChange={(layers) => prefs.set({ layers })}
        showPadNumbers={prefs.padNumbers}
        showLegend="wide"
        controls={controls}
        onZoomChange={tab === 'footprint' ? setZoom : undefined}
        className="absolute inset-0"
      />
      <ViewState
        hasContent={Boolean(footprint)}
        loading={perTab(loading, 'footprint')}
        error={perTab(error, 'footprint')}
        empty={emptyText?.footprint ?? tr('Kein Footprint zugeordnet')}
        board
      />
    </div>
  )

  const threeSpec: FootprintSpec | null = footprint ?? (stepSource ? {
    name: stepSource.name, description: '', family: '', pads: [], tracks: [], arcs: [], regions: [], texts: [], bodies: [],
  } : null)
  const threeView = () => (
    <div className="relative size-full">
      {threeSpec && (
        <Package3D
          ref={threeRef}
          spec={threeSpec}
          stepSource={stepSource}
          autoRotate={prefs.autoRotate}
          onAutoRotateChange={(autoRotate) => prefs.set({ autoRotate })}
          className="absolute inset-0"
        />
      )}
      <ViewState
        hasContent={Boolean(threeSpec)}
        loading={perTab(loading, '3d') ?? perTab(loading, 'footprint')}
        error={perTab(error, '3d') ?? perTab(error, 'footprint')}
        empty={emptyText?.['3d'] ?? tr('Kein Footprint zugeordnet')}
        board
      />
    </div>
  )

  const toolbarToggle = (pressed: boolean) =>
    cn(pressed && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text')

  const showSymbolTools = layout === 'split' ? Boolean(symbol) : tab === 'symbol'
  const showFootprintTools = layout === 'split' ? Boolean(footprint) : tab === 'footprint'
  const show3dTools = layout === 'split' ? Boolean(footprint) : tab === '3d'

  const toolbar = (
    <div className="ml-auto flex items-center gap-0.5">
      {showSymbolTools && (
        <Tooltip content={prefs.altium ? tr('PartForge-Darstellung') : tr('Wie in Altium Designer (weißes Blatt)')}>
          <button
            type="button"
            aria-label={tr("Altium-Ansicht")}
            aria-pressed={prefs.altium}
            onClick={() => prefs.set({ altium: !prefs.altium })}
            className={cn(
              'flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium text-fg-muted outline-none transition-colors focus-ring hover:bg-surface-2 hover:text-fg',
              prefs.altium && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text',
            )}
          >
            <Square aria-hidden className={cn('size-3.5', prefs.altium ? 'fill-[#FFFFB0] text-[#800000]' : '')} />
            <span className="hidden whitespace-nowrap @[34rem]:inline">{tr("Altium-Ansicht")}</span>
          </button>
        </Tooltip>
      )}
      {showFootprintTools && presentLayers.length > 0 && (
        <DropdownMenu>
          <Tooltip content={tr("Lagen ein- und ausblenden")}>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={tr("Lagen")}
                className="flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium text-fg-muted outline-none transition-colors focus-ring hover:bg-surface-2 hover:text-fg data-[state=open]:bg-surface-2 data-[state=open]:text-fg"
              >
                <Layers aria-hidden className="size-3.5" />
                <span className="hidden @[34rem]:inline">{tr("Lagen")}</span>
              </button>
            </DropdownMenuTrigger>
          </Tooltip>
          <DropdownMenuContent align="end" className="min-w-60">
            <DropdownMenuLabel>{tr("Lagen")}</DropdownMenuLabel>
            {presentLayers.map((l) => (
              <DropdownMenuCheckboxItem
                key={l}
                checked={layerVisible(l)}
                onCheckedChange={(on) => prefs.set({ layers: { ...prefs.layers, [l]: on === true } })}
                onSelect={(e) => e.preventDefault()}
              >
                <span className="flex items-center gap-2">
                  <span aria-hidden className="size-2.5 rounded-[3px]" style={{ background: layerColor(l) }} />
                  {tr(LAYERS[l].label)}
                  <span className="text-2xs text-fg-subtle">{LAYERS[l].altium}</span>
                </span>
              </DropdownMenuCheckboxItem>
            ))}
            <DropdownMenuSeparator />
            <DropdownMenuCheckboxItem
              checked={prefs.padNumbers}
              onCheckedChange={(on) => prefs.set({ padNumbers: on === true })}
              onSelect={(e) => e.preventDefault()}
            >
              {tr("Pad-Nummern")}
            </DropdownMenuCheckboxItem>
            {hasCalc && (
              <DropdownMenuCheckboxItem
                checked={prefs.dimensions}
                onCheckedChange={(on) => prefs.set({ dimensions: on === true })}
                onSelect={(e) => e.preventDefault()}
              >
                {tr("Bemaßung (IPC‑7351)")}
              </DropdownMenuCheckboxItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      {showFootprintTools && hasCalc && (
        <IconButton
          size="sm"
          label={prefs.dimensions ? tr('Bemaßung ausblenden') : tr('Bemaßung einblenden')}
          icon={<Ruler />}
          aria-pressed={prefs.dimensions}
          className={toolbarToggle(prefs.dimensions)}
          onClick={() => prefs.set({ dimensions: !prefs.dimensions })}
        />
      )}
      {show3dTools && (
        <>
          <IconButton
            size="sm"
            label={prefs.autoRotate ? tr('Drehung anhalten') : tr('Automatisch drehen')}
            icon={<Rotate3d />}
            aria-pressed={prefs.autoRotate}
            className={toolbarToggle(prefs.autoRotate)}
            onClick={() => prefs.set({ autoRotate: !prefs.autoRotate })}
          />
          {layout === 'tabs' && (
            <IconButton size="sm" label={tr("Ansicht zurücksetzen")} icon={<RotateCcw />} onClick={() => threeRef.current?.fit()} />
          )}
        </>
      )}
      {layout === 'tabs' && (
        <>
          <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
          <div className="hidden items-center gap-0.5 @[30rem]:flex">
            <IconButton size="sm" label={tr("Verkleinern")} icon={<Minus />} onClick={() => activeRef.current?.zoomOut()} />
            {tab !== '3d' && (
              <span className="mono w-10 text-center text-2xs text-fg-muted tabular-nums" aria-hidden>
                {Math.round(zoom * 100)} %
              </span>
            )}
            <IconButton size="sm" label={tr("Vergrößern")} icon={<Plus />} onClick={() => activeRef.current?.zoomIn()} />
          </div>
          {tab !== '3d' && (
            <IconButton size="sm" label={tr("Einpassen")} icon={<Scan />} onClick={() => activeRef.current?.fit()} />
          )}
        </>
      )}
      {allowLayoutSwitch && (
        <>
          <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
          <SegmentedControl
            size="sm"
            aria-label={tr("Anordnung")}
            value={layout}
            onValueChange={(v) => setInnerLayout(v)}
            options={[
              { value: 'tabs', label: tr('Einzeln') },
              { value: 'split', icon: <Columns3 />, label: tr('Nebeneinander') },
            ]}
          />
        </>
      )}
      {actions && (
        <>
          <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
          {actions}
        </>
      )}
      {allowFullscreen && (
        <IconButton size="sm" label={tr("Vollbild")} icon={<Maximize2 />} onClick={() => setFullscreen(true)} />
      )}
    </div>
  )

  const content =
    layout === 'split' ? (
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line @[52rem]:grid-cols-3">
        {available.map((t) => (
          <section key={t} aria-labelledby={`pv-${t}`} className="flex min-h-[240px] min-w-0 flex-col bg-surface">
            <header className="flex h-8 shrink-0 items-center gap-2 border-b border-line px-3 text-fg-subtle [&_svg]:size-3.5">
              {TAB_ICON[t]}
              <h3 id={`pv-${t}`} className="micro-label">
                {tr(TAB_LABEL[t])}
              </h3>
            </header>
            <div className="relative min-h-0 flex-1">
              {fullscreen ? null : t === 'symbol' ? symbolView(true) : t === 'footprint' ? footprintView(true) : threeView()}
            </div>
          </section>
        ))}
      </div>
    ) : (
      <>
        {available.map((t) => (
          <TabsContent key={t} value={t} className="relative min-h-0 flex-1 data-[state=inactive]:hidden" tabIndex={-1}>
            {fullscreen ? (
              <div className="absolute inset-0 flex items-center justify-center bg-bg text-ui text-fg-subtle">{tr("Im Vollbild geöffnet")}</div>
            ) : t === 'symbol' ? (
              symbolView(false)
            ) : t === 'footprint' ? (
              footprintView(false)
            ) : (
              threeView()
            )}
          </TabsContent>
        ))}
      </>
    )

  const dialogTitle = title ?? ([symbol?.name, footprint?.name].filter(Boolean).join(' · ') || tr('Vorschau'))

  return (
    <div className={cn('@container flex min-h-[280px] flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card', className)}>
      <Tabs value={tab} onValueChange={(v) => setTab(v as PreviewTab)} variant="pill" className="min-h-0 flex-1">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-2">
          {layout === 'tabs' ? (
            <TabsList aria-label={tr("Vorschau")}>
              {available.map((t) => (
                <TabsTrigger key={t} value={t} icon={TAB_ICON[t]} className="h-7 px-2.5 text-xs [&_svg]:size-3.5">
                  {tr(TAB_LABEL[t])}
                </TabsTrigger>
              ))}
            </TabsList>
          ) : (
            <span className="px-1.5 text-xs font-semibold text-fg">{tr("Alle Ansichten")}</span>
          )}
          {toolbar}
        </div>
        {content}
      </Tabs>

      {allowFullscreen && (
        <Dialog open={fullscreen} onOpenChange={setFullscreen}>
          <DialogContent size="full" aria-describedby={undefined}>
            <DialogHeader icon={TAB_ICON[tab]} title={dialogTitle} />
            <div className="flex min-h-0 flex-1 flex-col px-6 pb-6">
              <PreviewPanel
                symbol={symbol}
                footprint={footprint}
                stepSource={stepSource}
                calc={calc}
                tab={tab}
                onTabChange={setTab}
                highlight={highlight}
                loading={loading}
                error={error}
                emptyText={emptyText}
                actions={actions}
                designator={designator}
                comment={comment}
                hideEmptyTabs={hideEmptyTabs}
                allowFullscreen={false}
                allowLayoutSwitch
                className="min-h-0 flex-1"
              />
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
