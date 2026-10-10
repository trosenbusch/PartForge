import { t as translate, useI18n } from '@/lib/i18n'
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
  useI18n()
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
          {translate("Lagensatz")}{changed && (
            <Badge variant="accent" className="h-4 px-1.5">
              {translate("geändert")}</Badge>
          )}
        </h2>
        <p className="text-xs text-fg-muted">
          {translate("Eigener Lagensatz in jeder PcbLib – in Altium unter „View Configuration › Layer Sets“, beim Öffnen auf Wunsch aktiv")}</p>
      </div>
      <div className="flex flex-col divide-y divide-line px-5">
        <StyleRow
          label={translate("Lagensatz")}
          help={
            value.mode === 'none'
              ? translate("Nur die eingebauten Sätze von Altium (All Layers, Signal Layers …).")
              : value.mode === 'builtin'
                ? translate("Kupfer, Paste, Lötstopp, Bestückungsdruck, Bohrlagen und alle Mechanik-Lagen der Zuordnung.")
                : translate("Ein Satz aus einer Altium-Lagensatz-Datei (.layerset) – die Definition wird gespeichert.")
          }
          isDefault={value.mode === 'none'}
          defaultText={translate("Keiner")}
          onReset={() => setMode('none')}
        >
          <SegmentedControl<LayerSetSettings['mode']> aria-label={translate("Lagensatz")} size="sm" value={value.mode} onValueChange={setMode} options={MODES.map((mode) => ({ ...mode, label: translate(mode.label) }))} />
        </StyleRow>

        {value.mode === 'file' && (
          <div className="flex flex-col gap-3 py-3">
            <PathInput
              value={value.file ?? ''}
              onValueChange={(v) => setFile(v.trim() ? v : null)}
              prefix={<FileStack />}
              browse="file"
              fileFilters={[translate("Altium-Lagensatz (*.layerset)")]}
              placeholder={translate("Pfad der .layerset-Datei")}
              aria-label={translate("Pfad der .layerset-Datei")}
              invalid={Boolean(filePath && parsed.isError && !value.layers.length)}
            />
            {filePath && parsed.isFetching && <p className="text-xs text-fg-muted">{translate("Lese Lagensatz …")}</p>}
            {filePath && parsed.isError && (
              <Callout tone={value.layers.length ? 'warning' : 'danger'} title={translate("Datei nicht lesbar")}>
                {errorMessage(parsed.error)}
                {value.layers.length > 0 && translate(" Gespeichert bleibt „{value1}“ mit {value2} Lagen.", { value1: value.name ?? '', value2: value.layers.length })}
              </Callout>
            )}
            {sets.length > 1 && (
              <StyleRow label={translate("Satz aus der Datei")} help={translate("{value1} Lagensätze in der Datei", { value1: sets.length })} className="py-0">
                <Select
                  value={selected?.name ?? ''}
                  onValueChange={(name) => {
                    const set = sets.find((s) => s.name === name)
                    if (set) onChange(fromDef(set, value))
                  }}
                  options={sets.map((s) => ({ value: s.name, label: s.name, description: translate("{value1} Lagen", { value1: s.layers.length }) }))}
                  placeholder={translate("Lagensatz wählen")}
                  className="w-56"
                  aria-label={translate("Lagensatz aus der Datei")}
                />
              </StyleRow>
            )}
          </div>
        )}

        {value.mode === 'builtin' && (
          <StyleRow label="Name" help={translate("So heißt der Satz in Altium.")} isDefault={!value.name?.trim()} defaultText={BUILTIN_NAME} onReset={() => onChange({ ...value, name: null })}>
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
            label={translate("Beim Öffnen aktiv")}
            help={translate("Altium zeigt beim Öffnen der Bibliothek nur die Lagen dieses Satzes.")}
            isDefault={value.current}
            defaultText={translate("an")}
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
                  <span className="font-medium text-fg">„{shown.name}“</span> · {shown.layers.length} {' '}{translate("Lagen")}{shown.active ? translate(" · aktive Lage {value1}", { value1: layerLabel(shown.active) }) : ''}
                </span>
              </p>
              <ul className="flex flex-wrap gap-1.5" aria-label={translate("Lagen von {value1}", { value1: shown.name })}>
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
                  {translate("Nicht im Satz:")}{' '}{missingRoles.map((r) => `${r.label} (${r.layer})`).join(', ')} {' '}{translate("– diese Lagen blendet der Satz aus.")}</p>
              )}
            </>
          ) : (
            <p className="text-xs text-fg-muted">{translate("Noch kein Lagensatz gewählt.")}</p>
          )}
          <p className="mt-2 text-2xs leading-snug text-fg-subtle">
            {translate("Neue Footprint-Bibliotheken erhalten den Satz automatisch; vorhandene über „Auf Bibliotheken anwenden …“ oder die Stapelbearbeitung (Lagen-Kopf).")}</p>
        </div>
      )}
    </Card>
  )
}
