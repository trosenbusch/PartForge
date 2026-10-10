/**
 * Lagenrollen einer PcbLib: je mechanischer Quell-Lage die erkannte Rolle (am Lagentyp oder -namen im
 * Bibliothekskopf, sonst am Inhalt) mit Name im Kopf und Anzahl der Primitive. Eine andere Rolle zu wählen schreibt
 * `rules.footprints.roles[Bibliothek][Lage]` (wirkt nach erneutem Prüfen); „automatisch“ entfernt die eigene Rolle.
 */
import { RotateCcw } from 'lucide-react'
import {
  ROLE_LABELS,
  ROLE_REASON_LABELS,
  type ConformLayerRole,
  type ConformLibraryReport,
  type LayerRoleName,
} from '@/api/housestyle'
import { Badge, IconButton, Select, type BadgeProps } from '@/components/ui'
import { formatNumber } from '@/lib/format'
import { ROLE_ORDER, roleTarget, splitPath, type StyleInfo } from './model'

type Reason = ConformLayerRole['reason']

const REASON_VARIANT: Record<Reason, NonNullable<BadgeProps['variant']>> = {
  kind: 'neutral',
  name: 'neutral',
  content: 'info',
  manual: 'accent',
  default: 'warning',
}

/** Woran die Rolle erkannt wurde – als Tooltip am Kennzeichen */
const REASON_HINT: Record<Reason, string> = {
  kind: 'Erkannt am Lagentyp im Bibliothekskopf',
  name: 'Erkannt am Namen der Lage im Bibliothekskopf',
  content: 'Erkannt am Inhalt der Footprints: äußere Kontur um die Pads = Courtyard, innere = Bestückungszeichnung',
  manual: 'Von Hand gewählt',
  default: 'Nicht erkannt – die Primitive bleiben, wo sie sind',
}

/** Kennzeichen „Erkannt an“ (bei „–“ ausgeschrieben) */
const reasonText = (reason: Reason) => (reason === 'default' ? 'nicht erkannt' : ROLE_REASON_LABELS[reason])

export interface LayerRoleEditorProps {
  library: ConformLibraryReport
  /** eigene Rollen dieser Bibliothek im aktuellen Regel-Entwurf (Lage → Rolle) */
  manual: Record<string, LayerRoleName>
  onChange: (layer: string, role: LayerRoleName | null) => void
  layers: StyleInfo['layers'] | null
  /** Regeln „Lagen“ und „Linienbreiten“ aus – die Rollen wirken dann nicht */
  inactive: boolean
}

export function LayerRoleEditor({ library, manual, onChange, layers, inactive }: LayerRoleEditorProps) {
  const options = ROLE_ORDER.map((role) => ({
    value: role,
    label: ROLE_LABELS[role],
    description: roleTarget(role, layers),
  }))
  const fileName = splitPath(library.library).name

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5">
        <h4 className="text-xs font-medium text-fg">Lagenrollen</h4>
        <p className="text-2xs leading-snug text-fg-subtle">
          Die Rolle bestimmt, auf welche Lage der Lagenzuordnung die Primitive einer Quell-Lage wandern. Mittelkreuz,
          .Designator/.Comment und 3D-Körper erkennt PartForge unabhängig von ihrer Lage.
          {inactive && ' Die Regeln „Lagen“ und „Linienbreiten“ sind ausgeschaltet – die Rollen wirken derzeit nicht.'}
        </p>
      </div>
      <table className="w-full table-fixed border-collapse text-left">
        <caption className="sr-only">Lagenrollen von {fileName}</caption>
        <thead>
          <tr className="text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
            <th scope="col" className="py-1.5 pr-2 font-semibold">
              Quell-Lage
            </th>
            <th scope="col" className="w-[4.5rem] px-2 py-1.5 text-right font-semibold">
              Primitive
            </th>
            <th scope="col" className="w-[14.5rem] py-1.5 pl-2 font-semibold">
              Rolle
            </th>
          </tr>
        </thead>
        <tbody>
          {library.roles.map((r) => {
            const own = manual[r.layer]
            // eigene Rolle aus dem Entwurf; nach „automatisch“ bis zur nächsten Prüfung unbestimmt
            const removed = own === undefined && r.reason === 'manual'
            const value: LayerRoleName | '' = own ?? (removed ? '' : r.role)
            const pending = own !== undefined ? r.reason !== 'manual' || own !== r.role : removed
            const badge =
              own !== undefined
                ? { text: ROLE_REASON_LABELS.manual, variant: 'accent' as const, hint: REASON_HINT.manual }
                : removed
                  ? { text: 'automatisch', variant: 'accent' as const, hint: 'Wird beim nächsten Prüfen neu erkannt' }
                  : { text: reasonText(r.reason), variant: REASON_VARIANT[r.reason], hint: REASON_HINT[r.reason] }
            return (
              <tr key={r.layer} className="border-t border-line align-middle">
                <td className="min-w-0 py-1.5 pr-2">
                  <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
                    <span className="mono text-xs text-fg">{r.layer}</span>
                    <Badge variant={badge.variant} className="font-normal" title={badge.hint}>
                      {badge.text}
                      <span className="sr-only"> – {badge.hint}</span>
                    </Badge>
                  </span>
                  {r.name && r.name !== r.layer && (
                    <span className="mt-0.5 block text-2xs text-fg-subtle [overflow-wrap:anywhere]">
                      im Kopf: „{r.name}“
                    </span>
                  )}
                </td>
                <td className="mono px-2 py-1.5 text-right text-xs text-fg-muted">{formatNumber(r.primitives)}</td>
                <td className="py-1.5 pl-2">
                  <div className="flex items-center gap-1">
                    <Select<LayerRoleName | ''>
                      size="sm"
                      className="min-w-0 flex-1"
                      aria-label={`Rolle von ${r.layer}`}
                      placeholder="automatisch …"
                      value={value}
                      options={options}
                      onValueChange={(role) => {
                        if (!role) return
                        // dieselbe Rolle wie erkannt: nichts festschreiben
                        if (own === undefined && r.reason !== 'manual' && role === r.role) return
                        onChange(r.layer, role)
                      }}
                    />
                    {own !== undefined ? (
                      <IconButton
                        size="xs"
                        label={`Rolle von ${r.layer} wieder automatisch bestimmen`}
                        icon={<RotateCcw />}
                        onClick={() => onChange(r.layer, null)}
                      />
                    ) : (
                      <span aria-hidden className="size-6 shrink-0" />
                    )}
                    <span
                      role={pending ? 'img' : undefined}
                      aria-label={pending ? 'geändert – wirkt nach erneutem Prüfen' : undefined}
                      aria-hidden={pending ? undefined : true}
                      title={pending ? 'Geändert – wirkt nach erneutem Prüfen' : undefined}
                      className={
                        pending
                          ? 'size-1.5 shrink-0 rounded-full bg-accent shadow-[0_0_6px_var(--pf-accent)]'
                          : 'size-1.5 shrink-0'
                      }
                    />
                  </div>
                  {r.note && own === undefined && !removed && (
                    <span className={`mt-0.5 block text-2xs leading-snug [overflow-wrap:anywhere] ${r.target ? 'text-fg-subtle' : 'text-warning-text'}`}>
                      {r.note}
                    </span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
