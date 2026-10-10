/**
 * Bibliotheken des Berichts: je Datei eine aufklappbare Zeile mit Art, Pfad, geprüften und abweichenden Bauteilen und
 * Kennzeichen (nicht lesbar, wird übersprungen, Lagen-Kopf, nicht erkannte Lagen, eigene Rollen). Aufgeklappt: Grund
 * für das Überspringen bzw. den Lesefehler, Abweichungen des Lagen-Kopfs, die Schrifttabelle nach der Umstellung
 * (SchLib) und der Editor der Lagenrollen (PcbLib). Viele Dateien (eine je Bauteil): Filter, Suche, seitenweise.
 */
import { AnimatePresence, motion } from 'motion/react'
import { ChevronRight, CircuitBoard, Layers, Search, Shapes, X } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { ConformLibraryReport, ConformRules, LayerRoleName } from '@/api/housestyle'
import { libraryKey } from '@/api/libraries'
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  EmptyState,
  IconButton,
  Input,
  PathText,
  SegmentedControl,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { LayerRoleEditor } from './LayerRoleEditor'
import { manualRolesFor, splitPath, undeterminedLayers, type StyleInfo } from './model'

/** So viele Dateien zeigt die Liste zuerst (weitere auf Wunsch) */
const LIB_PAGE = 30
/** Ab so vielen Dateien gibt es ein Suchfeld */
const SEARCH_FROM = 12
/** So viele Abweichungen des Lagen-Kopfs zeigt eine Datei zuerst (ein fremder Kopf weicht oft in allen 32 Lagen ab) */
const HEADER_FIRST = 6

type Filter = 'all' | 'changes' | 'notes'

const hasChanges = (l: ConformLibraryReport) => !l.problem && (l.affected > 0 || l.header.length > 0)
const hasNotes = (l: ConformLibraryReport) => Boolean(l.problem || l.refusal) || undeterminedLayers(l) > 0

const KIND = {
  schlib: { title: 'Symbolbibliotheken', icon: Shapes },
  pcblib: { title: 'Footprint-Bibliotheken', icon: CircuitBoard },
} as const

/** Rollen, die im Entwurf anders sind als im Bericht (wirken erst nach erneutem Prüfen) */
function pendingRoles(lib: ConformLibraryReport, manual: Record<string, LayerRoleName>): number {
  let n = 0
  for (const r of lib.roles) {
    const own = manual[r.layer]
    if (own !== undefined ? r.reason !== 'manual' || own !== r.role : r.reason === 'manual') n += 1
  }
  return n
}

export interface LibrarySectionProps {
  libraries: ConformLibraryReport[]
  /** Regel-Entwurf (eigene Lagenrollen, Schalter „Lagen“/„Linienbreiten“) */
  rules: ConformRules
  /** Regel „Schriften“ war bei der Prüfung an (Überschrift der Schrifttabelle) */
  fontsChecked: boolean
  onRoleChange: (library: string, layer: string, role: LayerRoleName | null) => void
  layers: StyleInfo['layers'] | null
}

export function LibrarySection({ libraries, rules, fontsChecked, onRoleChange, layers }: LibrarySectionProps) {
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [limit, setLimit] = useState(LIB_PAGE)
  // wenige Dateien: gleich aufgeklappt
  const [open, setOpen] = useState<Set<string>>(
    () => new Set(libraries.length <= 3 ? libraries.map((l) => libraryKey(l.library)) : []),
  )

  const changed = useMemo(() => libraries.filter(hasChanges), [libraries])
  const notes = useMemo(() => libraries.filter(hasNotes), [libraries])
  const effectiveFilter: Filter = libraries.length > 1 ? filter : 'all'
  const needle = query.trim().toLowerCase()
  const base = effectiveFilter === 'changes' ? changed : effectiveFilter === 'notes' ? notes : libraries
  const visible = needle ? base.filter((l) => l.library.toLowerCase().includes(needle)) : base
  const shown = visible.slice(0, limit)
  const rest = visible.length - shown.length
  const groups = (['schlib', 'pcblib'] as const)
    .map((kind) => ({ kind, libs: shown.filter((l) => l.kind === kind) }))
    .filter((g) => g.libs.length > 0)
  const rolesInactive = !rules.footprints.layers && !rules.footprints.widths

  const toggle = (key: string) =>
    setOpen((cur) => {
      const next = new Set(cur)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Bibliotheken"
        description={`${plural(libraries.length, 'Datei', 'Dateien')} in der Auswahl – aufklappen für Lagenrollen, Lagen-Kopf und Schriften`}
      />
      {(libraries.length > 1 || libraries.length >= SEARCH_FROM) && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5">
          {libraries.length > 1 && (
            <SegmentedControl<Filter>
              size="sm"
              aria-label="Bibliotheken filtern"
              value={effectiveFilter}
              onValueChange={(v) => {
                setFilter(v)
                setLimit(LIB_PAGE)
              }}
              options={[
                { value: 'all', label: `Alle ${formatNumber(libraries.length)}` },
                { value: 'changes', label: `Mit Änderungen ${formatNumber(changed.length)}` },
                { value: 'notes', label: `Mit Hinweisen ${formatNumber(notes.length)}` },
              ]}
            />
          )}
          {libraries.length >= SEARCH_FROM && (
            <Input
              size="sm"
              type="search"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value)
                setLimit(LIB_PAGE)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Escape' && query) {
                  e.stopPropagation()
                  setQuery('')
                }
              }}
              placeholder="Datei suchen …"
              aria-label="Bibliotheken durchsuchen"
              prefix={<Search />}
              suffix={
                query ? (
                  <IconButton
                    size="xs"
                    label="Suche leeren"
                    icon={<X />}
                    onClick={() => setQuery('')}
                    tooltip={false}
                  />
                ) : undefined
              }
              containerClassName="w-52 min-w-0 flex-1 basis-36 @[60rem]:max-w-64"
            />
          )}
        </div>
      )}

      {groups.length === 0 ? (
        <div className="border-t border-line">
          <EmptyState
            size="sm"
            illustration="search-empty"
            title="Keine Treffer"
            description={needle ? `Keine Bibliothek passt zu „${query.trim()}“.` : 'Keine Bibliothek in diesem Filter.'}
            actions={
              <Button
                size="sm"
                onClick={() => {
                  setQuery('')
                  setFilter('all')
                }}
              >
                Filter zurücksetzen
              </Button>
            }
          />
        </div>
      ) : (
        groups.map((g) => {
          const Icon = KIND[g.kind].icon
          return (
            <section key={g.kind} aria-label={KIND[g.kind].title} className="border-t border-line">
              <div className="flex items-center gap-2 bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)] px-4 py-1.5 text-xs">
                <Icon aria-hidden className="size-3.5 text-fg-muted" />
                <span className="font-semibold text-fg">{KIND[g.kind].title}</span>
              </div>
              <ul className="divide-y divide-line border-t border-line">
                {g.libs.map((lib) => {
                  const key = libraryKey(lib.library)
                  return (
                    <LibraryRow
                      key={key}
                      lib={lib}
                      open={open.has(key)}
                      onToggle={() => toggle(key)}
                      manual={manualRolesFor(rules, lib.library)}
                      fontsChecked={fontsChecked}
                      rolesInactive={rolesInactive}
                      layers={layers}
                      onRoleChange={(layer, role) => onRoleChange(lib.library, layer, role)}
                    />
                  )
                })}
              </ul>
            </section>
          )
        })
      )}

      {rest > 0 && (
        <div className="flex items-center gap-3 border-t border-line px-4 py-2">
          <Button size="xs" variant="ghost" onClick={() => setLimit((l) => l + LIB_PAGE * 4)}>
            {formatNumber(Math.min(LIB_PAGE * 4, rest))} weitere anzeigen
          </Button>
          <span className="text-2xs text-fg-subtle">
            {formatNumber(shown.length)} von {plural(visible.length, 'Datei', 'Dateien')} angezeigt
          </span>
        </div>
      )}
    </Card>
  )
}

function LibraryRow({
  lib,
  open,
  onToggle,
  manual,
  fontsChecked,
  rolesInactive,
  layers,
  onRoleChange,
}: {
  lib: ConformLibraryReport
  open: boolean
  onToggle: () => void
  manual: Record<string, LayerRoleName>
  fontsChecked: boolean
  rolesInactive: boolean
  layers: StyleInfo['layers'] | null
  onRoleChange: (layer: string, role: LayerRoleName | null) => void
}) {
  const { folder, name } = splitPath(lib.library)
  const detailId = `lib-${libraryKey(lib.library).replace(/[^a-z0-9]+/gi, '-')}`
  const undetermined = undeterminedLayers(lib)
  const manualCount = Object.keys(manual).length
  const pending = pendingRoles(lib, manual)
  const status = lib.problem
    ? 'nicht lesbar'
    : `${plural(lib.selected, 'Bauteil', 'Bauteile')} geprüft${
        lib.affected > 0
          ? `, ${formatNumber(lib.affected)} ${lib.affected === 1 ? 'weicht' : 'weichen'} ab`
          : lib.header.length
            ? ''
            : ', im Hausstil'
      }${lib.components > lib.selected ? ` · Datei enthält ${formatNumber(lib.components)}` : ''}`

  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={onToggle}
        className="flex w-full items-start gap-2.5 px-4 py-2.5 text-left outline-none transition-colors hover:bg-surface-2/60 focus-ring-inset"
      >
        <ChevronRight
          aria-hidden
          className={cn('mt-0.5 size-4 shrink-0 text-fg-subtle transition-transform duration-200', open && 'rotate-90')}
        />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-ui font-medium text-fg [overflow-wrap:anywhere]">{name}</span>
            {lib.problem && (
              <Badge variant="danger" dot>
                Nicht lesbar
              </Badge>
            )}
            {lib.refusal && (
              <Badge variant="warning" dot>
                Wird übersprungen
              </Badge>
            )}
            {lib.header.length > 0 && (
              <Badge variant="info" dot>
                Lagen-Kopf
              </Badge>
            )}
            {undetermined > 0 && (
              <Badge variant="warning">
                {undetermined === 1 ? '1 Lage nicht erkannt' : `${formatNumber(undetermined)} Lagen nicht erkannt`}
              </Badge>
            )}
            {manualCount > 0 && (
              <Badge variant="outline" className="font-normal">
                {manualCount === 1 ? '1 Rolle von Hand' : `${formatNumber(manualCount)} Rollen von Hand`}
              </Badge>
            )}
            {pending > 0 && (
              <Badge variant="accent" dot>
                Rollen geändert
              </Badge>
            )}
          </span>
          <span className="mt-0.5 block text-2xs leading-snug text-fg-subtle">
            {folder && (
              <>
                <PathText path={folder} />
                {' · '}
              </>
            )}
            {status}
          </span>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={detailId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-4 pb-4 pl-[2.625rem] pr-4 pt-0.5">
              {lib.problem && (
                <Callout tone="danger" title="Nicht lesbar – bleibt unverändert">
                  {lib.problem}
                </Callout>
              )}
              {lib.refusal && (
                <Callout tone="warning" title="Wird beim Anwenden übersprungen">
                  {lib.refusal}
                </Callout>
              )}
              {lib.header.length > 0 && (
                <div className="flex flex-col gap-1">
                  <h4 className="text-xs font-medium text-fg">Lagen-Kopf weicht ab</h4>
                  <p className="text-2xs leading-snug text-fg-subtle">
                    „Anwenden“ übernimmt Lagenaufbau und Lagensatz des Hausstils.
                  </p>
                  <HeaderDeviations items={lib.header} />
                </div>
              )}
              {lib.kind === 'schlib' && lib.fonts.length > 0 && (
                <div className="flex flex-col gap-1">
                  <h4 className="text-xs font-medium text-fg">
                    {fontsChecked ? 'Schrifttabelle nach der Umstellung' : 'Schrifttabelle'}
                  </h4>
                  <ol className="mt-1 flex flex-wrap gap-1.5">
                    {lib.fonts.map((f, i) => (
                      <li key={`${i}-${f}`}>
                        <Badge variant="neutral" className="gap-1.5 font-normal">
                          <span className="mono text-fg-subtle">{i + 1}</span>
                          {f}
                        </Badge>
                      </li>
                    ))}
                  </ol>
                </div>
              )}
              {lib.kind === 'pcblib' &&
                !lib.problem &&
                (lib.roles.length > 0 ? (
                  <LayerRoleEditor
                    library={lib}
                    manual={manual}
                    onChange={onRoleChange}
                    layers={layers}
                    inactive={rolesInactive}
                  />
                ) : (
                  <p className="text-xs text-fg-muted">Die Footprints dieser Datei nutzen keine mechanischen Lagen.</p>
                ))}
              {lib.kind === 'schlib' && !lib.problem && !lib.fonts.length && !lib.refusal && (
                <p className="text-xs text-fg-muted">Keine weiteren Angaben zu dieser Datei.</p>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </li>
  )
}


/** Abweichungen des Lagen-Kopfs: die ersten {@link HEADER_FIRST}, der Rest auf Wunsch */
function HeaderDeviations({ items }: { items: string[] }) {
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, HEADER_FIRST)
  const hidden = items.length - shown.length
  return (
    <>
      <ul className="mt-1 flex flex-col gap-1 text-xs leading-snug text-fg-muted">
        {shown.map((h, i) => (
          <li key={i} className="flex items-start gap-1.5">
            <Layers aria-hidden className="mt-px size-3.5 shrink-0 text-info-text" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{h}</span>
          </li>
        ))}
      </ul>
      {(hidden > 0 || all) && items.length > HEADER_FIRST && (
        <Button size="xs" variant="ghost" className="self-start" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? 'Weniger anzeigen' : `${plural(hidden, 'weitere Abweichung', 'weitere Abweichungen')} anzeigen`}
        </Button>
      )}
    </>
  )
}
