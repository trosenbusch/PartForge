import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Bühne des Generators: große Footprint-Leinwand mit Bemaßung aus dem Rechenprotokoll, ein 3D-Reiter und – bei
 * schmalen Fenstern – der Reiter „Berechnung“ plus Messleiste unter der Leinwand. Die Ansicht bleibt beim Ändern
 * der Maße stehen, sobald der Nutzer gezoomt hat (neue Familie/Vorlage passt neu ein). Beim Rechnen läuft oben ein
 * dünner Glutstreifen; ein Fehler legt sich über den letzten gültigen Stand.
 */
import {
  Box as BoxIcon,
  Calculator,
  CircuitBoard,
  Hash,
  Layers,
  Maximize2,
  Minus,
  Plus,
  Rotate3d,
  RotateCcw,
  Ruler,
  Scan,
  TriangleAlert,
} from 'lucide-react'
import { useRef, useState, type ReactNode } from 'react'
import {
  CanvasBadge,
  CHROME_MUTED,
  CHROME_SURFACE,
  DEFAULT_LAYER_VISIBILITY,
  FootprintCanvas,
  Package3D,
  usePreviewPrefs,
  type CanvasHandle,
} from '@/components/preview'
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
  Skeleton,
  Spinner,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { footprintLayers, LAYERS, layerColor, type CanvasLayer, type FootprintSpec } from '@/lib/geometry'
import { PackageGlyph } from '../PackageGlyph'

export type StageTab = 'footprint' | '3d' | 'calc'

export interface GeneratorStageProps {
  spec: FootprintSpec | null
  calc: unknown
  /** Erste Berechnung läuft (noch nichts zu zeigen) */
  loading: boolean
  /** Neue Berechnung läuft, der letzte Stand bleibt sichtbar */
  updating: boolean
  error: string | null
  /** Neuer Wert → Ansicht wieder einpassen (Familie/Vorlage) */
  resetKey: string
  family: string | null
  /** Gesteuerter Reiter (sonst intern, Start mit `defaultTab`) */
  tab?: StageTab
  defaultTab?: StageTab
  onTabChange?: (tab: StageTab) => void
  /** Inhalt des Reiters „Berechnung“ (nur bei schmalen Fenstern) */
  calcPanel?: ReactNode
  /** Zähler am Reiter „Berechnung“ */
  calcBadge?: ReactNode
  /** Messleiste unter Leinwand und 3D */
  readout?: ReactNode
  /** Hinweis oben rechts auf der Leinwand (z. B. Warnungszähler) */
  overlay?: ReactNode
  allowFullscreen?: boolean
  className?: string
}

export function GeneratorStage({
  spec,
  calc,
  loading,
  updating,
  error,
  resetKey,
  family,
  tab: tabProp,
  defaultTab = 'footprint',
  onTabChange,
  calcPanel,
  calcBadge,
  readout,
  overlay,
  allowFullscreen = true,
  className,
}: GeneratorStageProps) {
  useI18n()
  const prefs = usePreviewPrefs()
  const [ownTab, setOwnTab] = useState<StageTab>(defaultTab)
  const requested = tabProp ?? ownTab
  const tab: StageTab = requested === 'calc' && !calcPanel ? 'footprint' : requested
  const [visited3d, setVisited3d] = useState(tab === '3d')
  if (tab === '3d' && !visited3d) setVisited3d(true)
  const [zoom, setZoom] = useState(1)
  const [fullscreen, setFullscreen] = useState(false)
  const canvasRef = useRef<CanvasHandle>(null)
  const threeRef = useRef<CanvasHandle>(null)
  const present = spec ? footprintLayers(spec) : []
  const layerOn = (l: CanvasLayer) => prefs.layers[l] ?? DEFAULT_LAYER_VISIBILITY[l]
  const active = tab === '3d' ? threeRef : canvasRef
  const bodies = spec?.bodies?.length ?? 0
  const drawing = tab !== 'calc'

  const setTab = (v: StageTab) => {
    setOwnTab(v)
    onTabChange?.(v)
  }
  const pressed = (on: boolean) => cn(on && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text')

  return (
    <div className={cn('@container/stage flex min-h-0 flex-col overflow-hidden rounded-card border border-line bg-surface shadow-card', className)}>
      <h2 className="sr-only">{tr("Vorschau")}</h2>
      <Tabs value={tab} onValueChange={(v) => setTab(v as StageTab)} variant="pill" className="flex min-h-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line px-2">
          <TabsList aria-label={tr("Ansicht")}>
            <TabsTrigger value="footprint" icon={<CircuitBoard />} className="h-7 px-2.5 text-xs [&_svg]:size-3.5">
              Footprint
            </TabsTrigger>
            <TabsTrigger value="3d" icon={<BoxIcon />} className="h-7 px-2.5 text-xs [&_svg]:size-3.5">
              3D
              {spec && bodies === 0 && <span className="sr-only"> {tr("(keine 3D-Körper)")}</span>}
            </TabsTrigger>
            {calcPanel && (
              <TabsTrigger value="calc" icon={<Calculator />} className="h-7 px-2.5 text-xs [&_svg]:size-3.5">
                {tr("Berechnung")}
                {calcBadge}
              </TabsTrigger>
            )}
          </TabsList>
          <div className="ml-auto flex items-center gap-0.5">
            {tab === 'footprint' && present.length > 0 && (
              <DropdownMenu>
                <Tooltip content={tr("Lagen ein- und ausblenden")}>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      aria-label={tr("Lagen")}
                      className="flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium text-fg-muted outline-none transition-colors focus-ring hover:bg-surface-2 hover:text-fg data-[state=open]:bg-surface-2 data-[state=open]:text-fg"
                    >
                      <Layers aria-hidden className="size-3.5" />
                      <span className="hidden @[40rem]/stage:inline">{tr("Lagen")}</span>
                    </button>
                  </DropdownMenuTrigger>
                </Tooltip>
                <DropdownMenuContent align="end" className="min-w-60">
                  <DropdownMenuLabel>{tr("Lagen")}</DropdownMenuLabel>
                  {present.map((l) => (
                    <DropdownMenuCheckboxItem
                      key={l}
                      checked={layerOn(l)}
                      onCheckedChange={(on) => prefs.set({ layers: { ...prefs.layers, [l]: on === true } })}
                      onSelect={(e) => e.preventDefault()}
                    >
                      <span className="flex items-center gap-2">
                        <span aria-hidden className="size-2.5 rounded-sm" style={{ background: layerColor(l) }} />
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
                  <DropdownMenuCheckboxItem
                    checked={prefs.dimensions}
                    onCheckedChange={(on) => prefs.set({ dimensions: on === true })}
                    onSelect={(e) => e.preventDefault()}
                  >
                    {tr("Bemaßung (IPC‑7351)")}
                  </DropdownMenuCheckboxItem>
                </DropdownMenuContent>
              </DropdownMenu>
            )}
            {tab === 'footprint' && (
              <>
                <IconButton
                  size="sm"
                  label={prefs.dimensions ? tr('Bemaßung ausblenden') : tr('Bemaßung einblenden')}
                  icon={<Ruler />}
                  aria-pressed={prefs.dimensions}
                  className={pressed(prefs.dimensions)}
                  onClick={() => prefs.set({ dimensions: !prefs.dimensions })}
                />
                <IconButton
                  size="sm"
                  label={prefs.padNumbers ? tr('Pad-Nummern ausblenden') : tr('Pad-Nummern einblenden')}
                  icon={<Hash />}
                  aria-pressed={prefs.padNumbers}
                  className={pressed(prefs.padNumbers)}
                  onClick={() => prefs.set({ padNumbers: !prefs.padNumbers })}
                />
              </>
            )}
            {tab === '3d' && (
              <>
                <IconButton
                  size="sm"
                  label={prefs.autoRotate ? tr('Drehung anhalten') : tr('Automatisch drehen')}
                  icon={<Rotate3d />}
                  aria-pressed={prefs.autoRotate}
                  className={pressed(prefs.autoRotate)}
                  onClick={() => prefs.set({ autoRotate: !prefs.autoRotate })}
                />
                <IconButton size="sm" label={tr("Ansicht zurücksetzen")} icon={<RotateCcw />} onClick={() => threeRef.current?.fit()} />
              </>
            )}
            {drawing && (
              <>
                <span aria-hidden className="mx-1 h-4 w-px bg-line-strong" />
                <div className={cn('hidden items-center gap-0.5', calcPanel ? '@[40rem]/stage:flex' : '@[28rem]/stage:flex')}>
                  <IconButton size="sm" label={tr("Verkleinern")} icon={<Minus />} onClick={() => active.current?.zoomOut()} />
                  {tab === 'footprint' && (
                    <span className="mono w-10 text-center text-2xs text-fg-muted tabular-nums" aria-hidden>
                      {Math.round(zoom * 100)} %
                    </span>
                  )}
                  <IconButton size="sm" label={tr("Vergrößern")} icon={<Plus />} onClick={() => active.current?.zoomIn()} />
                </div>
                {tab === 'footprint' && <IconButton size="sm" label={tr("Einpassen")} icon={<Scan />} onClick={() => canvasRef.current?.fit()} />}
              </>
            )}
            {allowFullscreen && drawing && <IconButton size="sm" label={tr("Vollbild")} icon={<Maximize2 />} onClick={() => setFullscreen(true)} />}
          </div>
        </div>

        <div className={cn('relative min-h-0 flex-1', drawing ? 'bg-canvas' : 'bg-surface')}>
          {/* Footprint */}
          <TabsContent value="footprint" forceMount tabIndex={-1} className="absolute inset-0 data-[state=inactive]:invisible">
            {spec && (
              <FootprintCanvas
                ref={canvasRef}
                spec={spec}
                calc={calc}
                showDimensions={prefs.dimensions}
                layers={prefs.layers}
                onLayersChange={(layers) => prefs.set({ layers })}
                showPadNumbers={prefs.padNumbers}
                showLegend="wide"
                controls={false}
                onZoomChange={setZoom}
                resetKey={resetKey}
                className={cn('absolute inset-0 transition-[filter,opacity] duration-300', error && 'opacity-45 saturate-50')}
              />
            )}
          </TabsContent>
          {/* 3D – erst beim ersten Öffnen laden (three.js-Chunk), danach bleibt die Szene erhalten */}
          <TabsContent value="3d" forceMount={visited3d || undefined} tabIndex={-1} className="absolute inset-0 data-[state=inactive]:invisible">
            {visited3d && spec && (
              <Package3D
                ref={threeRef}
                spec={spec}
                autoRotate={prefs.autoRotate}
                onAutoRotateChange={(autoRotate) => prefs.set({ autoRotate })}
                className={cn('absolute inset-0', error && 'opacity-45')}
              />
            )}
          </TabsContent>
          {calcPanel && (
            <TabsContent value="calc" tabIndex={-1} className="absolute inset-0 overflow-y-auto [scrollbar-gutter:stable]">
              {calcPanel}
            </TabsContent>
          )}

          {drawing && !spec && loading && <StageSkeleton family={family} />}
          {drawing && !spec && !loading && !error && (
            <div className={cn('absolute inset-0 flex items-center justify-center text-ui', CHROME_MUTED.board)}>{tr("Gehäusefamilie wählen")}</div>
          )}

          {updating && spec && drawing && (
            <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 z-20 h-0.5 overflow-hidden">
              <div className="progress-indeterminate h-full w-1/3 bg-[linear-gradient(90deg,transparent,var(--pf-accent),transparent)]" />
            </div>
          )}

          {drawing && overlay && <div className="absolute right-3 top-3 z-20">{overlay}</div>}

          {error && (
            <div className={cn('pointer-events-none absolute inset-x-0 bottom-0 z-20 flex justify-center p-4', !drawing && 'hidden')}>
              <div
                role="alert"
                className={cn('pointer-events-auto flex max-w-lg items-start gap-3 rounded-card px-4 py-3 text-ui', CHROME_SURFACE.board, 'border-danger/40')}
              >
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full bg-danger/20 text-danger">
                  <TriangleAlert aria-hidden className="size-3.5" />
                </span>
                <div className="min-w-0">
                  <div className="font-semibold">{tr("Mit diesen Maßen entsteht kein Footprint")}</div>
                  <p className={cn('mt-0.5 text-xs leading-relaxed', CHROME_MUTED.board)}>{localizeMessage(error)}</p>
                  {spec && <p className={cn('mt-1.5 text-2xs', CHROME_MUTED.board)}>{tr("Angezeigt wird der letzte gültige Stand.")}</p>}
                </div>
              </div>
            </div>
          )}
        </div>
        {readout && drawing && readout}
      </Tabs>

      {allowFullscreen && (
        <Dialog open={fullscreen} onOpenChange={setFullscreen}>
          <DialogContent size="full" aria-describedby={undefined}>
            <DialogHeader icon={<PackageGlyph family={family} />} title={spec?.name ?? tr('Vorschau')} />
            <div className="flex min-h-0 flex-1 flex-col px-6 pb-6">
              {fullscreen && (
                <GeneratorStage
                  spec={spec}
                  calc={calc}
                  loading={loading}
                  updating={updating}
                  error={error ? localizeMessage(error) : error}
                  resetKey={resetKey}
                  family={family}
                  defaultTab={tab === 'calc' ? 'footprint' : tab}
                  readout={readout}
                  overlay={overlay}
                  allowFullscreen={false}
                  className="min-h-0 flex-1"
                />
              )}
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}

function StageSkeleton({ family }: { family: string | null }) {
  useI18n()
  return (
    <div className="absolute inset-0 flex items-center justify-center">
      <Skeleton className="absolute inset-8 rounded-card opacity-[0.08]" />
      <div className="relative flex flex-col items-center gap-3">
        <span className={cn('flex size-14 items-center justify-center rounded-card', CHROME_SURFACE.board)}>
          <PackageGlyph family={family} className="size-8" />
        </span>
        <CanvasBadge tone="board" className="h-8 rounded-full px-3.5 text-xs">
          <Spinner size={14} tone="accent" />
          {tr("Footprint wird berechnet …")}
        </CanvasBadge>
      </div>
    </div>
  )
}
