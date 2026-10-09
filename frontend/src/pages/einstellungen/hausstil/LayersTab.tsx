/**
 * Lagen: Zuordnung der logischen Footprint-Lagen zu Altium-Lagen (Top Overlay, Mechanical 1–32) mit
 * Vorlagen (Ihre Standardvorlage / IPC-Wizard der TR-Bibliotheken), optionaler .stackup-Datei und einem
 * Lagenplan im Leiterplatten-Look (Mechanical 1–32 mit Namen und Rollen).
 */
import { Check, CircuitBoard, FileStack, Layers3, Lightbulb, TriangleAlert, Wand2 } from 'lucide-react'
import { useState } from 'react'
import { errorMessage } from '@/api/client'
import { trackJob } from '@/api/jobs'
import { useApplyLayerStack, useLayerStack, useParsedLayerStack, type LayerStackInfo, type MechLayer } from '@/api/settings'
import type { LayerMap } from '@/api/system'
import { Badge, Button, Callout, Card, confirm, PathInput, Select, Skeleton, type SelectGroupDef } from '@/components/ui'
import { cn } from '@/lib/cn'
import { LAYERS } from '@/lib/geometry'
import { useDebounced } from '../hooks'
import { StyleRow } from './StyleRow'

type Role = keyof LayerMap

interface RoleDef {
  key: Role
  label: string
  description: string
  /** Farbe im Lagenplan (gut unterscheidbar, auf dunkler Leiterplatte) */
  color: string
  /** Altium-Lagentyp, den die Rolle erwartet (MECHKIND) */
  kind?: string
  short: string
}

const ROLES: RoleDef[] = [
  { key: 'silkscreen', label: 'Bestückungsdruck', description: 'Umrisse und Pin‑1‑Punkt auf der Platine', color: LAYERS.top_silk.color.dark, short: 'Druck' },
  { key: 'assembly', label: 'Bestückungszeichnung', description: 'Gehäuseumriss für die Bestückungsdoku', color: LAYERS.assembly.color.dark, kind: 'AssemblyTop', short: 'Bestückung' },
  { key: 'designator', label: 'Bezeichner', description: '.Designator in der Bauteilmitte', color: '#22D3EE', kind: 'DesignatorTop', short: 'Bezeichner' },
  { key: 'body3d', label: '3D-Körper', description: 'Extrudierte Gehäuse und STEP-Modelle', color: LAYERS.body3d.color.dark, kind: '3DBodyTop', short: '3D' },
  { key: 'courtyard', label: 'Courtyard', description: 'Platzbedarf inklusive Abstand', color: LAYERS.courtyard.color.dark, kind: 'CourtyardTop', short: 'Courtyard' },
  { key: 'component_center', label: 'Bauteilmitte', description: 'Kreuz im Ursprung (Bestückungsautomat)', color: '#FB7185', kind: 'ComponentCenterTop', short: 'Mitte' },
  { key: 'comment', label: 'Wert', description: '.Comment, z. B. „10k“', color: '#A3E635', kind: 'ValueTop', short: 'Wert' },
  { key: 'component_outline', label: 'Bauteilumriss', description: 'Nennmaß des Gehäuses', color: '#94A3B8', kind: 'ComponentOutlineTop', short: 'Umriss' },
]

const NBSP = '\u00a0'

const PRESETS: { key: string; label: string; detail: string; note?: string; map: LayerMap }[] = [
  {
    key: 'standard',
    label: 'Standard',
    detail: `Ihre Vorlage: Mech${NBSP}9/11/13/15/17/19/21`,
    map: {
      silkscreen: 'Top Overlay',
      assembly: 'Mechanical 9',
      designator: 'Mechanical 11',
      body3d: 'Mechanical 13',
      courtyard: 'Mechanical 15',
      component_center: 'Mechanical 17',
      comment: 'Mechanical 19',
      component_outline: 'Mechanical 21',
    },
  },
  {
    key: 'ipc',
    label: 'IPC-Wizard',
    detail: `TR-Bibliotheken: Mech${NBSP}5/7/9/13/15/17/19`,
    note: 'Passt zum .stackup der TR-Bibliotheken',
    map: {
      silkscreen: 'Top Overlay',
      assembly: 'Mechanical 5',
      designator: 'Mechanical 9',
      body3d: 'Mechanical 13',
      courtyard: 'Mechanical 15',
      component_center: 'Mechanical 17',
      comment: 'Mechanical 7',
      component_outline: 'Mechanical 19',
    },
  },
]

/**
 * Mechanical 2–7 deklariert der Rust-Writer als typisierte Lagen (Assembly/Courtyard/3D). Das gilt nur, solange
 * PartForge den Lagenkopf der PcbLibs nicht selbst schreibt (`patch_enabled` = false) – sonst bestimmt der
 * Lagenaufbau Namen und Typen.
 */
const RESERVED = new Set([2, 3, 4, 5, 6, 7])
const mechNumber = (name: string): number | null => {
  const m = /^Mechanical (\d+)$/i.exec(name.trim())
  return m ? Number(m[1]) : null
}
const sameMap = (a: LayerMap, b: LayerMap) => ROLES.every((r) => a[r.key] === b[r.key])
const roleColor = (r: RoleDef) => r.color

interface Issue {
  level: 'warn' | 'info'
  text: string
}

/** Wie `stackup.layer_map_issues` (Backend) – plus Hinweis auf die Lagen 2–7, wenn der Writer sie festlegt */
function mapIssues(map: LayerMap, layers: Record<string, MechLayer> | null, reserved: boolean): Issue[] {
  const issues: Issue[] = []
  const used = new Map<number, string[]>()
  for (const r of ROLES) {
    const n = mechNumber(map[r.key])
    if (n === null) continue
    used.set(n, [...(used.get(n) ?? []), r.label])
    if (reserved && RESERVED.has(n) && r.key !== 'silkscreen') {
      issues.push({
        level: 'warn',
        text: `${r.label}: Mechanical ${n} belegt der Bibliotheks-Writer mit festen Typen (Assembly/Courtyard/3D) – besser eine Lage ab 8 wählen.`,
      })
    }
    if (!layers) continue
    const layer = layers[String(n)]
    if (!layer) {
      issues.push({ level: 'info', text: `${r.label}: Mechanical ${n} ist im Lagenaufbau nicht definiert – PartForge legt sie in den Bibliotheken an.` })
    } else {
      if (r.kind && layer.kind && layer.kind !== r.kind) {
        issues.push({ level: 'warn', text: `${r.label}: Mechanical ${n} ist „${layer.name}“ (Typ ${layer.kind}), erwartet wird ${r.kind}.` })
      }
      if (!layer.enabled) issues.push({ level: 'info', text: `${r.label}: Mechanical ${n} ist im Lagenaufbau deaktiviert – wird in den Bibliotheken aktiviert.` })
    }
  }
  for (const [n, roles] of used) {
    if (roles.length > 1) issues.push({ level: 'warn', text: `Mechanical ${n} trägt mehrere Rollen: ${roles.join(', ')}.` })
  }
  return issues
}

export function LayersTab({
  savedMap,
  map,
  savedStackup,
  stackup,
  dirty,
  onMap,
  onStackup,
}: {
  savedMap: LayerMap
  map: LayerMap
  savedStackup: string | null
  stackup: string | null
  dirty: boolean
  onMap: (map: LayerMap) => void
  onStackup: (path: string | null) => void
}) {
  const server = useLayerStack()
  const pathForParse = useDebounced(stackup && stackup !== savedStackup ? stackup : null, 600)
  const parsed = useParsedLayerStack(pathForParse)
  const apply = useApplyLayerStack()
  const [hover, setHover] = useState<Role | null>(null)

  /** Lagenaufbau nicht lesbar – Plan zeigt dann nur die Standardnamen */
  const missing = server.isError
  const stackInfo: LayerStackInfo | undefined = pathForParse && parsed.data ? parsed.data : server.data
  const layers = stackInfo?.stack.layers ?? null
  // Lagen 2–7 nur dann „reserviert“, wenn PartForge den Lagenkopf nicht selbst schreibt
  const reserved = stackInfo?.patch_enabled === false
  const issues = mapIssues(map, layers, reserved)
  const ipcActive = sameMap(PRESETS[1].map, map)
  const builtinStack = !stackInfo || stackInfo.stack.source === 'builtin'
  const suggested = stackInfo?.suggested_layer_map
  const suggestionDiffers = suggested ? !sameMap(suggested, map) : false

  const options = (role: RoleDef): SelectGroupDef[] => {
    const mech = Array.from({ length: 32 }, (_, i) => i + 1).map((n) => {
      const layer = layers?.[String(n)]
      const fixed = reserved && RESERVED.has(n)
      return {
        value: `Mechanical ${n}`,
        label: `Mechanical ${n}`,
        description: [layer?.name && layer.name !== `Mechanical ${n}` ? layer.name : null, fixed ? 'vom Bibliotheks-Writer reserviert' : null]
          .filter(Boolean)
          .join(' · ') || undefined,
      }
    })
    const overlay = [
      { value: 'Top Overlay', label: 'Top Overlay', description: 'Bestückungsdruck oben' },
      { value: 'Bottom Overlay', label: 'Bottom Overlay', description: 'Bestückungsdruck unten' },
    ]
    return role.key === 'silkscreen'
      ? [
          { label: 'Bestückungsdruck', options: overlay },
          { label: 'Mechanik', options: mech },
        ]
      : [{ label: 'Mechanik', options: mech }]
  }

  const runApply = async () => {
    const ok = await confirm({
      title: 'Lagen in alle Footprint-Bibliotheken übernehmen?',
      description:
        'PartForge schreibt Lagennamen, -typen und Paare des Lagenaufbaus in den Kopf jeder PcbLib. Primitive bleiben unverändert; bei unerwartetem Dateiaufbau bleibt die Datei unberührt.',
      confirmLabel: 'Übernehmen',
      icon: <Layers3 />,
    })
    if (!ok) return
    try {
      const { job } = await apply.mutateAsync()
      trackJob(job)
    } catch {
      // Fehler-Toast kommt von der Mutation
    }
  }

  return (
    <div className="grid grid-cols-1 items-start gap-5 @[46rem]:grid-cols-[minmax(0,1fr)_minmax(0,21rem)]">
      <div className="flex min-w-0 flex-col gap-5">
        <Card className="@container overflow-hidden">
          <div className="border-b border-line px-5 py-3.5">
            <h2 className="text-ui font-semibold text-fg">Zuordnung</h2>
            <p className="text-xs text-fg-muted">Auf welcher Altium-Lage PartForge was zeichnet – Vorlage wählen oder einzeln zuordnen</p>
            <div role="group" aria-label="Vorlagen" className="mt-3 grid grid-cols-1 gap-2 @[30rem]:grid-cols-2">
              {PRESETS.map((p) => {
                const active = sameMap(p.map, map)
                return (
                  <button
                    key={p.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => onMap({ ...p.map })}
                    className={cn(
                      'flex min-w-0 items-start gap-2.5 rounded-button border px-3 py-2.5 text-left outline-none transition-colors focus-ring',
                      active
                        ? 'border-accent bg-accent-soft/50 shadow-[0_0_0_1px_var(--pf-accent)]'
                        : 'border-line bg-surface-2/40 hover:border-line-strong hover:bg-surface-2',
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        'mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border',
                        active ? 'border-transparent bg-gradient-forge text-on-accent' : 'border-line-control',
                      )}
                    >
                      {active && <Check className="size-3" />}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-ui font-medium text-fg">{p.label}</span>
                      <span className="block text-2xs leading-snug text-fg-muted">{p.detail}</span>
                      {p.note && <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle">{p.note}</span>}
                    </span>
                  </button>
                )
              })}
            </div>
            {/* Direkt unter den Vorlagen, damit der Hinweis beim Klick auf „IPC-Wizard“ sofort sichtbar ist */}
            {ipcActive && builtinStack && !missing && (
              <Callout tone="info" icon={<FileStack />} title="Dazu den Lagenaufbau der TR-Bibliotheken wählen" className="mt-3">
                Die Vorlage „IPC-Wizard“ gehört zum Lagenaufbau der TR-Bibliotheken. Wählen Sie unten deren .stackup-Datei – mit
                dem eingebauten Standard tragen einige Lagen andere Typen (siehe Hinweise).
              </Callout>
            )}
          </div>
          <div className="flex flex-col divide-y divide-line px-5">
            {ROLES.map((r) => {
              const n = mechNumber(map[r.key])
              const changed = map[r.key] !== savedMap[r.key]
              return (
                <div
                  key={r.key}
                  onPointerEnter={() => setHover(r.key)}
                  onPointerLeave={() => setHover((h) => (h === r.key ? null : h))}
                  onFocus={() => setHover(r.key)}
                  onBlur={() => setHover((h) => (h === r.key ? null : h))}
                  className={cn('-mx-5 px-5 transition-colors', hover === r.key && 'bg-surface-2/50')}
                >
                  <StyleRow
                    label={r.label}
                    help={
                      <span className="flex items-center gap-1.5">
                        <span aria-hidden className="size-2 shrink-0 rounded-[3px] shadow-[inset_0_0_0_1px_rgba(0,0,0,.28)]" style={{ background: roleColor(r) }} />
                        {r.description}
                        {changed && <Badge variant="accent" className="ml-1 h-4 px-1.5">geändert</Badge>}
                      </span>
                    }
                  >
                    <Select
                      value={map[r.key]}
                      onValueChange={(v) => onMap({ ...map, [r.key]: v })}
                      groups={options(r)}
                      className={cn('w-52', reserved && n !== null && RESERVED.has(n) && 'border-warning')}
                      contentClassName="max-h-80"
                    />
                  </StyleRow>
                </div>
              )
            })}
          </div>
          {issues.length > 0 && (
            <ul className="flex flex-col gap-1.5 border-t border-line bg-surface-2/30 px-5 py-3" aria-label="Hinweise zur Zuordnung">
              {issues.map((i) => (
                <li key={i.text} className={cn('flex items-start gap-2 text-xs', i.level === 'warn' ? 'text-warning-text' : 'text-fg-muted')}>
                  <TriangleAlert aria-hidden className={cn('mt-px size-3.5 shrink-0', i.level === 'info' && 'opacity-60')} />
                  {i.text}
                </li>
              ))}
            </ul>
          )}
          {suggested && suggestionDiffers && !missing && (
            <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3">
              <Lightbulb aria-hidden className="size-4 shrink-0 text-fg-subtle" />
              <p className="min-w-0 flex-1 text-xs text-fg-muted">Der Lagenaufbau legt eine andere Zuordnung nahe (nach Lagentyp).</p>
              <Button size="sm" variant="secondary" leftIcon={<Wand2 />} onClick={() => onMap({ ...suggested })}>
                Vorschlag übernehmen
              </Button>
            </div>
          )}
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-line px-5 py-3.5">
            <h2 className="text-ui font-semibold text-fg">Lagenaufbau (.stackup)</h2>
            <p className="text-xs text-fg-muted">Optional: Namen und Typen der Mechanik-Lagen aus Ihrer Altium-Vorlage</p>
          </div>
          <div className="flex flex-col gap-3 px-5 py-4">
            <PathInput
              value={stackup ?? ''}
              onValueChange={(v) => onStackup(v.trim() ? v : null)}
              prefix={<FileStack />}
              browse="file"
              fileFilters={['Altium-Lagenaufbau (*.stackup)']}
              placeholder="Leer = eingebauter Standard (Mechanical_Stackup_Standard)"
              aria-label="Pfad der .stackup-Datei"
            />
            {pathForParse && parsed.isFetching && <p className="text-xs text-fg-muted">Lese Lagenaufbau …</p>}
            {pathForParse && parsed.isError && (
              <Callout tone="danger" title="Datei nicht lesbar">
                {errorMessage(parsed.error)}
              </Callout>
            )}
            {pathForParse && parsed.data && <ParsedSummary layers={parsed.data.stack.layers ?? {}} />}
            {(stackInfo?.notes ?? []).map((n) => (
              <p key={n} className="text-xs text-warning-text">
                {n}
              </p>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-3 border-t border-line bg-surface-2/30 px-5 py-3">
            <p className="min-w-0 flex-1 text-xs text-fg-muted">
              Neue Footprints erhalten die Lagen automatisch. Vorhandene PcbLib-Dateien lassen sich nachträglich angleichen.
            </p>
            <Button
              size="sm"
              variant="secondary"
              leftIcon={<Layers3 />}
              onClick={() => void runApply()}
              loading={apply.isPending}
              disabled={dirty || missing || stackInfo?.patch_enabled === false}
              title={dirty ? 'Zuerst speichern' : undefined}
            >
              Auf Bibliotheken anwenden …
            </Button>
          </div>
        </Card>
      </div>

      <StackDiagram
        map={map}
        info={stackInfo}
        loading={server.isPending}
        missing={missing}
        error={server.error ? errorMessage(server.error) : null}
        reserved={reserved}
        hover={hover}
        onHover={setHover}
        className="@[46rem]:sticky @[46rem]:top-[4.5rem]"
      />
    </div>
  )
}

// --------------------------------------------------------------------------- Lagenplan

/** „51 Mechanik-Lagen gelesen“ – PartForge nutzt davon nur Mechanical 1–32 (so viele kennt der Kopf einer PcbLib) */
function ParsedSummary({ layers }: { layers: Record<string, MechLayer> }) {
  const all = Object.keys(layers).length
  const used = Object.keys(layers).filter((n) => Number(n) >= 1 && Number(n) <= 32).length
  return (
    <p className="text-xs text-success-text">
      {all} Mechanik-Lagen gelesen{all > used ? `, davon nutzt PartForge Mechanical 1–32 (${used} Lagen)` : ''} – rechts als
      Vorschau, gilt nach dem Speichern.
    </p>
  )
}

function StackDiagram({
  map,
  info,
  loading,
  missing,
  error,
  reserved,
  hover,
  onHover,
  className,
}: {
  map: LayerMap
  info: LayerStackInfo | undefined
  loading: boolean
  missing: boolean
  /** Lagenaufbau konnte nicht gelesen werden */
  error: string | null
  /** Lagen 2–7 legt der Writer fest (nur ohne eigenen Lagenkopf) */
  reserved: boolean
  hover: Role | null
  onHover: (role: Role | null) => void
  className?: string
}) {
  const layers = info?.stack.layers ?? null
  const rolesOn = (layer: string) => ROLES.filter((r) => map[r.key] === layer)
  const overlays = ['Top Overlay', 'Bottom Overlay']
  return (
    <Card className={cn('overflow-hidden', className)}>
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <CircuitBoard aria-hidden className="size-4 text-fg-subtle" />
        <div className="min-w-0">
          <h2 className="text-ui font-semibold text-fg">Lagenplan</h2>
          <p className="truncate text-2xs text-fg-subtle" title={info?.stack.source}>
            {info ? (info.stack.source === 'builtin' ? info.stack.name || 'Eingebauter Standard' : info.stack.source) : missing ? 'Standardnamen' : '…'}
          </p>
        </div>
      </div>
      <div className="dot-grid bg-canvas p-3" role="list" aria-label="Lagen mit zugeordneten Rollen">
        <div className="mb-2 grid grid-cols-2 gap-1.5">
          {overlays.map((name) => (
            <LayerCell key={name} title={name} name={name === 'Top Overlay' ? 'Bestückungsdruck oben' : 'Bestückungsdruck unten'} roles={rolesOn(name)} hover={hover} onHover={onHover} />
          ))}
        </div>
        {loading && !missing ? (
          <div className="grid grid-cols-4 gap-1.5">
            {Array.from({ length: 32 }, (_, i) => (
              <Skeleton key={i} className="h-12 rounded-md bg-white/5" />
            ))}
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-1.5">
            {Array.from({ length: 32 }, (_, i) => i + 1).map((n) => {
              const layer = layers?.[String(n)]
              return (
                <LayerCell
                  key={n}
                  title={`M${n}`}
                  name={layer?.name && layer.name !== `Mechanical ${n}` ? layer.name : missing ? '' : '–'}
                  kind={layer?.kind ?? undefined}
                  enabled={layer ? layer.enabled : !layers}
                  reserved={reserved && RESERVED.has(n)}
                  roles={rolesOn(`Mechanical ${n}`)}
                  hover={hover}
                  onHover={onHover}
                />
              )
            })}
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1.5 border-t border-white/10 bg-canvas px-4 py-2.5">
        {ROLES.map((r) => (
          <span key={r.key} className="flex items-center gap-1.5 text-2xs text-[#AEB7C7]">
            <span aria-hidden className="size-2 rounded-[3px]" style={{ background: roleColor(r) }} />
            {r.short}
          </span>
        ))}
        {reserved && (
          <span className="flex items-center gap-1.5 text-2xs text-[#AEB7C7]">
            <span aria-hidden className="size-2 rounded-[3px] bg-[repeating-linear-gradient(135deg,#9AA4B6_0_2px,transparent_2px_4px)]" />
            reserviert (2–7)
          </span>
        )}
      </div>
      {missing && error && (
        <div className="border-t border-line px-4 py-3">
          <Callout tone="warning" title="Lagenaufbau nicht gelesen">
            {error} Angezeigt werden die Standardnamen.
          </Callout>
        </div>
      )}
    </Card>
  )
}

function LayerCell({
  title,
  name,
  kind,
  enabled = true,
  reserved,
  roles,
  hover,
  onHover,
}: {
  title: string
  name: string
  kind?: string
  enabled?: boolean
  reserved?: boolean
  roles: RoleDef[]
  hover: Role | null
  onHover: (role: Role | null) => void
}) {
  const active = roles.length > 0
  const highlighted = roles.some((r) => r.key === hover)
  const color = active ? roleColor(roles[0]) : undefined
  const label = `${title}${name ? ` (${name})` : ''}${roles.length ? ` – ${roles.map((r) => r.label).join(', ')}` : ''}${reserved ? ' – vom Bibliotheks-Writer reserviert' : ''}${!enabled ? ' – deaktiviert' : ''}`
  return (
    <div
      role="listitem"
      aria-label={label}
      title={`${label}${kind ? ` · Typ ${kind}` : ''}`}
      onPointerEnter={() => roles[0] && onHover(roles[0].key)}
      onPointerLeave={() => roles[0] && onHover(null)}
      className={cn(
        'relative min-w-0 overflow-hidden rounded-md border px-1.5 py-1 transition-[transform,box-shadow,border-color] duration-150',
        active ? 'border-white/25' : 'border-white/[0.07]',
        !enabled && !active && 'opacity-45',
        highlighted && 'scale-[1.04] shadow-[0_0_0_1px_rgba(255,255,255,.6),0_6px_18px_-6px_rgba(0,0,0,.8)]',
      )}
      style={{
        background: active
          ? `linear-gradient(135deg, color-mix(in oklab, ${color} 34%, #0D1118), color-mix(in oklab, ${color} 14%, #0D1118))`
          : reserved
            ? 'repeating-linear-gradient(135deg, rgba(154,164,182,.10) 0 4px, rgba(13,17,24,.6) 4px 8px)'
            : 'rgba(255,255,255,.03)',
      }}
    >
      <div className="flex items-center justify-between gap-1">
        <span className={cn('mono text-2xs font-semibold', active ? 'text-white' : 'text-[#9AA4B6]')}>{title}</span>
        {roles.length > 1 && <span className="text-2xs font-semibold text-[#FFC27A]">×{roles.length}</span>}
      </div>
      <div className={cn('truncate text-2xs leading-tight', active ? 'text-[#E6EAF2]' : 'text-[#9AA4B6]')}>
        {active ? roles.map((r) => r.short).join(' · ') : name || ' '}
      </div>
    </div>
  )
}
