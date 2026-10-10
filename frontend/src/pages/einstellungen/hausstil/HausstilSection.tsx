/**
 * Hausstil: Footprints (FootprintStyle), Lagen (LayerMap + .stackup + Lagensatz) und Symbole (SymbolStyle) – ein
 * gemeinsamer Entwurf für alle drei Reiter, gespeichert über PUT /api/workspace/settings (Strg+S).
 * Footprint-Namen und die Dioden-Konvention stehen unter „Namensregeln“ und bleiben hier unberührt.
 * „Aus Beispielbibliothek …“ schlägt Werte aus einer Altium-Bibliothek vor (`LearnStyleDialog`) – sie gehen in den
 * Entwurf und werden wie jede Änderung gespeichert.
 */
import { CircuitBoard, Layers3, Pipette, Shapes } from 'lucide-react'
import { useState } from 'react'
import { useSearchParams, type Location } from 'react-router'
import { toast } from 'sonner'
import type { FootprintStyle, LayerMap, LayerSetSettings, SymbolStyle, WorkspaceSettings } from '@/api/system'
import { Button, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui'
import { NoWorkspace } from '../components'
import { useWorkspaceDraft } from '../draft'
import { UnsavedChanges } from '../UnsavedChanges'
import { FootprintStyleTab } from './FootprintStyleTab'
import { LayersTab } from './LayersTab'
import { LearnStyleDialog, type LearnedStyle } from './LearnStyleDialog'
import { SymbolStyleTab } from './SymbolStyleTab'

interface StyleDraft {
  footprint: FootprintStyle
  layers: LayerMap
  layer_stackup: string | null
  layer_set: LayerSetSettings
  symbol: SymbolStyle
}

const selectStyle = (s: WorkspaceSettings): StyleDraft => ({
  footprint: s.footprint,
  layers: s.layers,
  layer_stackup: s.layer_stackup ?? null,
  layer_set: s.layer_set,
  symbol: s.symbol,
})

const applyStyle = (s: WorkspaceSettings, v: StyleDraft): WorkspaceSettings => ({
  ...s,
  // Namensschema und Dioden-Konvention gehören zu „Namensregeln“ – vom aktuellen Serverstand übernehmen
  footprint: { ...v.footprint, naming: s.footprint.naming },
  symbol: { ...v.symbol, diode_pin1: s.symbol.diode_pin1 },
  layers: v.layers,
  layer_stackup: v.layer_stackup?.trim() || null,
  layer_set: { ...v.layer_set, file: v.layer_set.file?.trim() || null, name: v.layer_set.name?.trim() || null },
})

type Tab = 'footprints' | 'lagen' | 'symbole'
const TABS: Tab[] = ['footprints', 'lagen', 'symbole']
const HEX = /^#[0-9A-Fa-f]{6}$/

/** Reiterwechsel brauchen keine Rückfrage – der Entwurf gilt für alle drei Reiter */
const leavesSection = (a: Location, b: Location) => a.pathname !== b.pathname

export default function HausstilSection() {
  const ws = useWorkspaceDraft(selectStyle, applyStyle, {
    label: 'Hausstil',
    savedDescription: 'Gilt für neu erzeugte Footprints und Symbole.',
  })
  const [params, setParams] = useSearchParams()
  const raw = params.get('ansicht') as Tab | null
  const tab: Tab = raw && TABS.includes(raw) ? raw : 'footprints'
  const [learnOpen, setLearnOpen] = useState(false)

  if (ws.workspace.isPending) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <Skeleton className="h-10 w-80 rounded-button" />
        <div className="grid grid-cols-1 gap-5 @[48rem]:grid-cols-[minmax(0,1fr)_22rem]">
          <Skeleton className="h-[36rem] rounded-card" />
          <Skeleton className="h-[28rem] rounded-card" />
        </div>
      </div>
    )
  }
  if (!ws.info || !ws.draft || !ws.saved) return <NoWorkspace what="Hausstil und Lagenzuordnung" />

  const draft = ws.draft
  const saved = ws.saved
  const setFootprint = (patch: Partial<FootprintStyle>) => ws.setDraft((d) => ({ ...d, footprint: { ...d.footprint, ...patch } }))
  const setSymbol = (patch: Partial<SymbolStyle>) => ws.setDraft((d) => ({ ...d, symbol: { ...d.symbol, ...patch } }))

  const changed = {
    footprints: JSON.stringify(draft.footprint) !== JSON.stringify(saved.footprint),
    lagen:
      JSON.stringify(draft.layers) !== JSON.stringify(saved.layers) ||
      (draft.layer_stackup ?? '') !== (saved.layer_stackup ?? '') ||
      JSON.stringify(draft.layer_set) !== JSON.stringify(saved.layer_set),
    symbole: JSON.stringify(draft.symbol) !== JSON.stringify(saved.symbol),
  }
  const s = draft.symbol
  const invalid = [s.ic_line_color, s.ic_fill_color, s.discrete_line_color, s.pin_color].some((c) => !HEX.test(c))
    ? 'Ungültige Farbe – bitte #RRGGBB eingeben.'
    : draft.layer_set.mode === 'file' && !draft.layer_set.layers.length
      ? 'Lagensatz: bitte eine lesbare .layerset-Datei wählen (oder „Keiner“).'
      : null

  const applyLearned = (learned: LearnedStyle, count: number) => {
    if (!count) return
    ws.setDraft((d) => ({
      ...d,
      symbol: { ...d.symbol, ...learned.symbol },
      footprint: { ...d.footprint, ...learned.footprint },
      layers: { ...d.layers, ...learned.layers },
    }))
    toast.success(count === 1 ? '1 Einstellung übernommen' : `${count} Einstellungen übernommen`, {
      description: 'Bitte prüfen und speichern (Strg+S).',
    })
  }

  const dot = (on: boolean) =>
    on ? <span aria-label="geändert" role="img" className="size-1.5 rounded-full bg-accent shadow-[0_0_6px_var(--pf-accent)]" /> : null

  return (
    <div className="flex flex-col">
      <Tabs
        value={tab}
        onValueChange={(t) =>
          setParams(
            (p) => {
              const next = new URLSearchParams(p)
              if (t === 'footprints') next.delete('ansicht')
              else next.set('ansicht', t)
              return next
            },
            { replace: true },
          )
        }
        className="gap-5"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList aria-label="Hausstil-Bereiche">
            <TabsTrigger value="footprints" icon={<CircuitBoard />}>
              Footprints {dot(changed.footprints)}
            </TabsTrigger>
            <TabsTrigger value="lagen" icon={<Layers3 />}>
              Lagen {dot(changed.lagen)}
            </TabsTrigger>
            <TabsTrigger value="symbole" icon={<Shapes />}>
              Symbole {dot(changed.symbole)}
            </TabsTrigger>
          </TabsList>
          <Button size="sm" variant="secondary" leftIcon={<Pipette />} onClick={() => setLearnOpen(true)}>
            Aus Beispielbibliothek …
          </Button>
        </div>
        <TabsContent value="footprints">
          <FootprintStyleTab saved={saved.footprint} draft={draft.footprint} onChange={setFootprint} />
        </TabsContent>
        <TabsContent value="lagen">
          <LayersTab
            savedMap={saved.layers}
            map={draft.layers}
            savedStackup={saved.layer_stackup}
            stackup={draft.layer_stackup}
            savedLayerSet={saved.layer_set}
            layerSet={draft.layer_set}
            dirty={ws.dirty}
            onMap={(layers) => ws.setDraft((d) => ({ ...d, layers }))}
            onStackup={(layer_stackup) => ws.setDraft((d) => ({ ...d, layer_stackup }))}
            onLayerSet={(layer_set) => ws.setDraft((d) => ({ ...d, layer_set }))}
          />
        </TabsContent>
        <TabsContent value="symbole">
          <SymbolStyleTab saved={saved.symbol} draft={draft.symbol} onChange={setSymbol} />
        </TabsContent>
      </Tabs>

      <LearnStyleDialog
        open={learnOpen}
        onOpenChange={setLearnOpen}
        draft={{ symbol: draft.symbol, footprint: draft.footprint, layers: draft.layers }}
        onApply={applyLearned}
      />

      <UnsavedChanges
        dirty={ws.dirty}
        saving={ws.saving}
        onSave={ws.save}
        onDiscard={ws.reset}
        label="Hausstil"
        invalid={ws.dirty ? invalid : null}
        shouldBlock={leavesSection}
        root={ws.root}
      />
    </div>
  )
}
