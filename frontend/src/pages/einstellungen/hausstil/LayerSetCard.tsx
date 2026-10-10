/**
 * Lagensatz (Altium „View Configuration › Layer Sets“): PartForge schreibt einen eigenen Lagensatz in den Kopf jeder
 * PcbLib – keiner, „Component Layers“ aus der Lagenzuordnung oder ein Satz aus einer Altium-.layerset-Datei. Die
 * Definition steht in den Einstellungen der Bibliothek (die Datei ist nur die Herkunft, der Bibliotheksordner bleibt
 * in sich vollständig).
 */
import { FileStack, Layers2, TriangleAlert } from 'lucide-react'
import { useEffect } from 'react'
import { errorMessage } from '@/api/client'
import { useBuiltinLayerSet, useParsedLayerSet, type LayerSetDef } from '@/api/settings'
import type { LayerMap, LayerSetSettings } from '@/api/system'
import { Badge, Callout, Card, Input, PathInput, SegmentedControl, Select, Skeleton, Switch } from '@/components/ui'
import { cn } from '@/lib/cn'
import { useDebounced } from '../hooks'
import { StyleRow } from './StyleRow'

/** Rolle der Lagenzuordnung (Farbe und Name wie im Lagenplan) */
export interface LayerSetRole {
  label: string
  color: string
  /** Altium-Lagenname, z. B. „Mechanical 9“ */
  layer: string
}

const MODES: { value: LayerSetSettings['mode']; label: string }[] = [
  { value: 'none', label: 'Keiner' },
  { value: 'builtin', label: 'Aus Zuordnung' },
  { value: 'file', label: 'Aus Datei' },
]

const BUILTIN_NAME = 'Component Layers'

/** Lagenkürzel der .layerset-Datei („Mechanical9“, „TopOverlay“) aus dem Lagennamen („Mechanical 9“) */
const tokenOf = (layer: string) => layer.replace(/[\s-]+/g, '').toUpperCase()
/** „TopOverlay“ → „Top Overlay“, „Mechanical9“ → „Mechanical 9“ */
const layerLabel = (token: string) => token.replace(/([a-z])([A-Z0-9])/g, '$1 $2')

/** Definition eines Satzes der Datei in die Einstellungen übernehmen (`current` bleibt Wahl des Nutzers) */
function fromDef(set: LayerSetDef, value: LayerSetSettings): LayerSetSettings {
  return {
    ...value,
    name: set.name,
    layers: [...set.layers],
    active_layer: set.active_layer,
    locked: set.locked,
    flip_board: set.flip_board,
  }
}

export function LayerSetCard({
  value,
  saved,
  map,
  roles,
  onChange,
}: {
  value: LayerSetSettings
  saved: LayerSetSettings
  map: LayerMap
  roles: LayerSetRole[]
  onChange: (next: LayerSetSettings) => void
}) {
  const changed = JSON.stringify(value) !== JSON.stringify(saved)
  const debouncedMap = useDebounced(map, 400)
  const builtin = useBuiltinLayerSet(value.mode === 'builtin' ? debouncedMap : null, value.current)
  const filePath = useDebounced(value.mode === 'file' ? value.file?.trim() || null : null, 500)
  const parsed = useParsedLayerSet(filePath)
  const sets = parsed.data?.sets ?? []
  const selected = sets.find((s) => s.name === value.name) ?? null

  // Neue Datei (noch keine Definition daraus): den ersten Satz übernehmen – bei mehreren lässt er sich unten wechseln
  const fileSets = parsed.data && filePath && value.mode === 'file' ? sets : null
  const needsPick = Boolean(fileSets?.length) && !selected && value.layers.length === 0
  useEffect(() => {
    if (needsPick && fileSets) onChange(fromDef(fileSets[0], value))
    // eslint-disable-next-line react-hooks/exhaustive-deps -- nur beim Eintreffen der Datei, nicht bei jeder Änderung
  }, [needsPick, fileSets])

  const shown: { name: string; layers: string[]; active: string | null } | null =
    value.mode === 'builtin'
      ? builtin.data
        ? { name: value.name?.trim() || builtin.data.name, layers: builtin.data.layers, active: builtin.data.active_layer }
        : null
      : value.mode === 'file' && value.layers.length
        ? { name: value.name ?? '', layers: value.layers, active: value.active_layer ?? null }
        : null
  const tokens = new Set((shown?.layers ?? []).map((t) => t.toUpperCase()))
  const roleByToken = new Map(roles.map((r) => [tokenOf(r.layer), r]))
  const missingRoles = shown ? roles.filter((r) => !tokens.has(tokenOf(r.layer))) : []

  const clearDefinition = { name: null, layers: [], active_layer: null, locked: false, flip_board: false }
  const setMode = (mode: LayerSetSettings['mode']) => {
    if (mode === value.mode) return
    // „name“ ist bei der Zuordnung ein eigener Name, bei einer Datei der Name des Satzes – beim Wechsel nicht mitnehmen;
    // zurück zur Datei liest PartForge den Satz neu aus ihr
    if (mode === 'builtin') onChange({ ...value, mode, name: null })
    else if (mode === 'file') onChange({ ...value, mode, ...clearDefinition })
    else onChange({ ...value, mode })
  }
  const setFile = (file: string | null) => onChange({ ...value, file, ...clearDefinition })

  return (
    <Card className="overflow-hidden">
      <div className="border-b border-line px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-ui font-semibold text-fg">
          Lagensatz
          {changed && (
            <Badge variant="accent" className="h-4 px-1.5">
              geändert
            </Badge>
          )}
        </h2>
        <p className="text-xs text-fg-muted">
          Eigener Lagensatz in jeder PcbLib – in Altium unter „View Configuration › Layer Sets“, beim Öffnen auf Wunsch aktiv
        </p>
      </div>
      <div className="flex flex-col divide-y divide-line px-5">
        <StyleRow
          label="Lagensatz"
          help={
            value.mode === 'none'
              ? 'Nur die eingebauten Sätze von Altium (All Layers, Signal Layers …).'
              : value.mode === 'builtin'
                ? 'Kupfer, Paste, Lötstopp, Bestückungsdruck, Bohrlagen und alle Mechanik-Lagen der Zuordnung.'
                : 'Ein Satz aus einer Altium-Lagensatz-Datei (.layerset) – die Definition wird gespeichert.'
          }
          isDefault={value.mode === 'none'}
          defaultText="Keiner"
          onReset={() => setMode('none')}
        >
          <SegmentedControl<LayerSetSettings['mode']> aria-label="Lagensatz" size="sm" value={value.mode} onValueChange={setMode} options={MODES} />
        </StyleRow>

        {value.mode === 'file' && (
          <div className="flex flex-col gap-3 py-3">
            <PathInput
              value={value.file ?? ''}
              onValueChange={(v) => setFile(v.trim() ? v : null)}
              prefix={<FileStack />}
              browse="file"
              fileFilters={['Altium-Lagensatz (*.layerset)']}
              placeholder="Pfad der .layerset-Datei"
              aria-label="Pfad der .layerset-Datei"
              invalid={Boolean(filePath && parsed.isError && !value.layers.length)}
            />
            {filePath && parsed.isFetching && <p className="text-xs text-fg-muted">Lese Lagensatz …</p>}
            {filePath && parsed.isError && (
              <Callout tone={value.layers.length ? 'warning' : 'danger'} title="Datei nicht lesbar">
                {errorMessage(parsed.error)}
                {value.layers.length > 0 && ` Gespeichert bleibt „${value.name ?? ''}“ mit ${value.layers.length} Lagen.`}
              </Callout>
            )}
            {sets.length > 1 && (
              <StyleRow label="Satz aus der Datei" help={`${sets.length} Lagensätze in der Datei`} className="py-0">
                <Select
                  value={selected?.name ?? ''}
                  onValueChange={(name) => {
                    const set = sets.find((s) => s.name === name)
                    if (set) onChange(fromDef(set, value))
                  }}
                  options={sets.map((s) => ({ value: s.name, label: s.name, description: `${s.layers.length} Lagen` }))}
                  placeholder="Lagensatz wählen"
                  className="w-56"
                  aria-label="Lagensatz aus der Datei"
                />
              </StyleRow>
            )}
          </div>
        )}

        {value.mode === 'builtin' && (
          <StyleRow label="Name" help="So heißt der Satz in Altium." isDefault={!value.name?.trim()} defaultText={BUILTIN_NAME} onReset={() => onChange({ ...value, name: null })}>
            <Input
              value={value.name ?? ''}
              onChange={(e) => onChange({ ...value, name: e.target.value || null })}
              placeholder={BUILTIN_NAME}
              maxLength={60}
              containerClassName="w-56"
            />
          </StyleRow>
        )}

        {value.mode !== 'none' && (
          <StyleRow
            label="Beim Öffnen aktiv"
            help="Altium zeigt beim Öffnen der Bibliothek nur die Lagen dieses Satzes."
            isDefault={value.current}
            defaultText="an"
            onReset={() => onChange({ ...value, current: true })}
          >
            <Switch checked={value.current} onCheckedChange={(current) => onChange({ ...value, current })} />
          </StyleRow>
        )}
      </div>

      {value.mode !== 'none' && (
        <div className="border-t border-line bg-surface-2/30 px-5 py-3">
          {value.mode === 'builtin' && builtin.isPending ? (
            <div className="flex flex-wrap gap-1.5" aria-busy="true">
              {Array.from({ length: 12 }, (_, i) => (
                <Skeleton key={i} className="h-5 w-20 rounded-sm" />
              ))}
            </div>
          ) : value.mode === 'builtin' && builtin.isError ? (
            <p className="text-xs text-danger-text">{errorMessage(builtin.error)}</p>
          ) : shown ? (
            <>
              <p className="mb-2 flex items-center gap-1.5 text-xs text-fg-muted">
                <Layers2 aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />
                <span className="min-w-0">
                  <span className="font-medium text-fg">„{shown.name}“</span> · {shown.layers.length} Lagen
                  {shown.active ? ` · aktive Lage ${layerLabel(shown.active)}` : ''}
                </span>
              </p>
              <ul className="flex flex-wrap gap-1.5" aria-label={`Lagen von ${shown.name}`}>
                {shown.layers.map((t) => {
                  const role = roleByToken.get(t.toUpperCase())
                  return (
                    <li
                      key={t}
                      title={role ? `${layerLabel(t)} – ${role.label}` : layerLabel(t)}
                      className={cn(
                        'flex h-5 items-center gap-1 rounded-sm border px-1.5 text-2xs',
                        role ? 'border-line-strong bg-surface text-fg' : 'border-line bg-surface-2/60 text-fg-muted',
                      )}
                    >
                      {role && <span aria-hidden className="size-1.5 shrink-0 rounded-[2px]" style={{ background: role.color }} />}
                      {layerLabel(t)}
                    </li>
                  )
                })}
              </ul>
              {missingRoles.length > 0 && (
                <p className="mt-2 flex items-start gap-1.5 text-xs text-warning-text">
                  <TriangleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
                  Nicht im Satz: {missingRoles.map((r) => `${r.label} (${r.layer})`).join(', ')} – diese Lagen blendet der Satz aus.
                </p>
              )}
            </>
          ) : (
            <p className="text-xs text-fg-muted">Noch kein Lagensatz gewählt.</p>
          )}
          <p className="mt-2 text-2xs leading-snug text-fg-subtle">
            Neue Footprint-Bibliotheken erhalten den Satz automatisch; vorhandene über „Auf Bibliotheken anwenden …“ oder die
            Stapelbearbeitung (Lagen-Kopf).
          </p>
        </div>
      )}
    </Card>
  )
}
