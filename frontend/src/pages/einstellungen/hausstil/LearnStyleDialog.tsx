/**
 * „Hausstil aus Beispielbibliothek übernehmen“: PartForge liest eine Bibliothek, deren Bauteile so aussehen, wie alle
 * aussehen sollen (.SchLib, .PcbLib, .IntLib, ein .zip davon oder ein Ordner), und schlägt Schriften, Pinlängen,
 * Farben, Linienbreiten, Texte und die Lagenzuordnung vor (`POST /api/housestyle/learn`). Gewählte Vorschläge gehen in
 * den Entwurf – gespeichert wird wie sonst über die Speicherleiste.
 */
import { FolderOpen, Pipette, Sparkles } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { errorMessage } from '@/api/client'
import { useLearnStyle, type StyleFinding, type StyleProposal } from '@/api/housestyle'
import type { FootprintStyle, LayerMap, SymbolStyle } from '@/api/system'
import {
  Badge,
  Button,
  Callout,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  IconButton,
  PathInput,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { pickFolder, useNativeBridge } from '@/lib/native'

export interface LearnedStyle {
  symbol: Partial<SymbolStyle>
  footprint: Partial<FootprintStyle>
  layers: Partial<LayerMap>
}

const AREAS: { key: StyleFinding['area']; label: string }[] = [
  { key: 'symbol', label: 'Symbole' },
  { key: 'footprint', label: 'Footprints' },
  { key: 'layers', label: 'Lagenzuordnung' },
]

const ENUM_TEXT: Record<string, string> = {
  stroke: 'Strichschrift',
  truetype: 'TrueType',
  house: 'Hausschrift',
  system: 'Systemschrift',
}

/** Wert des Entwurfs so lesbar wie die Vorschläge des Backends („100 mil“, „0,8 mm“, „ja“) */
function formatValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === '') return '–'
  if (typeof value === 'boolean') return value ? 'ja' : 'nein'
  if (typeof value === 'number') {
    const unit = /length|grid/.test(key) ? ' mil' : /size/.test(key) ? ' pt' : /width|height|radius|clearance/.test(key) ? ' mm' : ''
    return `${formatNumber(value)}${unit}`
  }
  const text = String(value)
  return ENUM_TEXT[text] ?? text
}

const keyOf = (f: StyleFinding) => `${f.area}:${f.key}`

/** Vorgeschlagener Wert (aus den vom Backend geprüften Einstellungen des Vorschlags) */
function proposedValue(p: StyleProposal, f: StyleFinding): unknown {
  if (f.area === 'symbol') return p.symbol[f.key as keyof SymbolStyle]
  if (f.area === 'footprint') return p.footprint[f.key as keyof FootprintStyle]
  return p.layers[f.key as keyof LayerMap]
}

export function LearnStyleDialog({
  open,
  onOpenChange,
  draft,
  onApply,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Aktueller Entwurf – Vergleich und Vorauswahl richten sich nach ihm, nicht nach dem gespeicherten Stand */
  draft: { symbol: SymbolStyle; footprint: FootprintStyle; layers: LayerMap }
  onApply: (learned: LearnedStyle, count: number) => void
}) {
  const bridge = useNativeBridge()
  const learn = useLearnStyle()
  const [path, setPath] = useState('')
  const [chosen, setChosen] = useState<Set<string>>(new Set())

  const current = (f: StyleFinding): unknown =>
    f.area === 'symbol'
      ? draft.symbol[f.key as keyof SymbolStyle]
      : f.area === 'footprint'
        ? draft.footprint[f.key as keyof FootprintStyle]
        : draft.layers[f.key as keyof LayerMap]

  const proposal = learn.data ?? null
  const differs = (f: StyleFinding) => proposal !== null && JSON.stringify(current(f)) !== JSON.stringify(proposedValue(proposal, f))
  const findings = proposal?.findings ?? []
  const differing = findings.filter(differs)

  const close = (next: boolean) => {
    if (!next) {
      learn.reset()
      setChosen(new Set())
    }
    onOpenChange(next)
  }

  const run = (e?: FormEvent) => {
    e?.preventDefault()
    const p = path.trim()
    if (!p) return
    learn.mutate([p], {
      onSuccess: (result) => {
        // Vorauswahl: alles, was vom Entwurf abweicht
        const pre = new Set<string>()
        for (const f of result.findings ?? []) {
          if (JSON.stringify(current(f)) !== JSON.stringify(proposedValue(result, f))) pre.add(keyOf(f))
        }
        setChosen(pre)
      },
    })
  }

  const chooseFolder = async () => {
    const picked = await pickFolder(path || null)
    if (picked) setPath(picked)
  }

  const toggle = (f: StyleFinding, on: boolean) =>
    setChosen((prev) => {
      const next = new Set(prev)
      if (on) next.add(keyOf(f))
      else next.delete(keyOf(f))
      return next
    })

  const apply = () => {
    if (!proposal) return
    const learned: LearnedStyle = { symbol: {}, footprint: {}, layers: {} }
    let count = 0
    for (const f of findings) {
      if (!chosen.has(keyOf(f)) || !differs(f)) continue
      const value = proposedValue(proposal, f)
      if (f.area === 'symbol') Object.assign(learned.symbol, { [f.key]: value })
      else if (f.area === 'footprint') Object.assign(learned.footprint, { [f.key]: value })
      else Object.assign(learned.layers, { [f.key]: value })
      count += 1
    }
    onApply(learned, count)
    close(false)
  }

  const selectedCount = differing.filter((f) => chosen.has(keyOf(f))).length

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent size="lg">
        <DialogHeader
          tone="accent"
          icon={<Pipette />}
          title="Hausstil aus Beispielbibliothek übernehmen"
          description="Eine Bibliothek, deren Bauteile so aussehen, wie alle aussehen sollen: PartForge liest Schriften, Pinlängen, Farben, Linienbreiten, Texte und die Lagenzuordnung und schlägt die Einstellungen vor."
        />
        <DialogBody className="flex flex-col gap-4">
          <form onSubmit={run} className="flex flex-col gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <PathInput
                value={path}
                onValueChange={setPath}
                browse="file"
                fileFilters={['Altium-Bibliotheken (*.SchLib;*.PcbLib;*.IntLib;*.zip)']}
                placeholder="Beispielbibliothek: .SchLib, .PcbLib, .IntLib, .zip oder Ordner"
                aria-label="Pfad der Beispielbibliothek"
                className="min-w-0 flex-1"
              />
              {bridge.canPickFolder && <IconButton label="Ordner wählen" variant="secondary" icon={<FolderOpen />} onClick={() => void chooseFolder()} />}
              <Button type="submit" variant={proposal ? 'secondary' : 'primary'} loading={learn.isPending} disabled={!path.trim()} leftIcon={<Sparkles />}>
                Auswerten
              </Button>
            </div>
            <p className="text-xs text-fg-muted">Nur gelesen – die Beispielbibliothek bleibt unverändert, gespeichert wird erst über die Speicherleiste.</p>
          </form>

          {learn.isError && (
            <Callout tone="danger" title="Nicht auswertbar" urgent>
              {errorMessage(learn.error)}
            </Callout>
          )}

          {proposal && (
            <div className="flex flex-col gap-3">
              <Callout tone={differing.length ? 'info' : 'success'} title={differing.length ? 'Vorschläge' : 'Der Entwurf entspricht dem Beispiel'} live>
                {formatNumber(proposal.symbols)} {proposal.symbols === 1 ? 'Symbol' : 'Symbole'} und {formatNumber(proposal.footprints)}{' '}
                {proposal.footprints === 1 ? 'Footprint' : 'Footprints'} ausgewertet
                {differing.length ? ` – ${plural(differing.length, 'Einstellung weicht', 'Einstellungen weichen')} vom Entwurf ab.` : '.'}
              </Callout>
              {(proposal.notes ?? []).map((n) => (
                <p key={n} className="text-xs text-warning-text">
                  {n}
                </p>
              ))}
              {AREAS.map((area) => {
                const items = findings.filter((f) => f.area === area.key)
                if (!items.length) return null
                return (
                  <section key={area.key} aria-label={area.label} className="overflow-hidden rounded-card border border-line">
                    <h3 className="border-b border-line bg-surface-2/40 px-4 py-2 text-xs font-semibold uppercase tracking-[0.06em] text-fg-muted">
                      {area.label}
                    </h3>
                    <ul className="divide-y divide-line">
                      {items.map((f) => {
                        const diff = differs(f)
                        const id = keyOf(f)
                        return (
                          <li key={id} className={cn('flex items-start gap-3 px-4 py-2.5', !diff && 'opacity-70')}>
                            <Checkbox
                              checked={diff && chosen.has(id)}
                              disabled={!diff}
                              onCheckedChange={(v) => toggle(f, v === true)}
                              aria-label={`${f.label} übernehmen`}
                              className="mt-0.5"
                            />
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-baseline gap-x-2">
                                <span className="text-ui font-medium text-fg">{f.label}</span>
                                {!diff && <Badge className="h-4 px-1.5">wie Entwurf</Badge>}
                              </div>
                              <p className="text-2xs text-fg-subtle">Beleg: {f.evidence}</p>
                            </div>
                            <div className="flex shrink-0 items-center gap-2 text-xs">
                              {diff && <span className="mono text-fg-subtle line-through decoration-fg-subtle/60">{formatValue(f.key, current(f))}</span>}
                              <span className={cn('mono', diff ? 'font-medium text-fg' : 'text-fg-muted')}>{f.proposed}</span>
                            </div>
                          </li>
                        )
                      })}
                    </ul>
                  </section>
                )
              })}
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="ghost" onClick={() => close(false)}>
            {proposal && !differing.length ? 'Schließen' : 'Abbrechen'}
          </Button>
          {proposal && differing.length > 0 && (
            <Button variant="primary" onClick={apply} disabled={!selectedCount}>
              {selectedCount === 1 ? '1 Einstellung übernehmen' : `${formatNumber(selectedCount)} Einstellungen übernehmen`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
