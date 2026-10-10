import { useI18n, localizeMessage } from '@/lib/i18n'
import { t as tr } from '@/lib/i18n'
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
  schlib: { get title() { return tr("Symbolbibliotheken") }, icon: Shapes },
  pcblib: { get title() { return tr("Footprint-Bibliotheken") }, icon: CircuitBoard },
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
  const { t: tr } = useI18n()
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
        title={tr("Bibliotheken")}
        description={tr("{0} in der Auswahl – aufklappen für Lagenrollen, Lagen-Kopf und Schriften", { "0": String(plural(libraries.length, tr("Datei"), tr("Dateien"))) })}
      />
      {(libraries.length > 1 || libraries.length >= SEARCH_FROM) && (
        <div className="flex flex-wrap items-center gap-2 border-t border-line px-4 py-2.5">
          {libraries.length > 1 && (
            <SegmentedControl<Filter>
              size="sm"
              aria-label={tr("Bibliotheken filtern")}
              value={effectiveFilter}
              onValueChange={(v) => {
                setFilter(v)
                setLimit(LIB_PAGE)
              }}
              options={[
                { value: 'all', label: tr("Alle {0}", { "0": String(formatNumber(libraries.length)) }) },
                { value: 'changes', label: tr("Mit Änderungen {0}", { "0": String(formatNumber(changed.length)) }) },
                { value: 'notes', label: tr("Mit Hinweisen {0}", { "0": String(formatNumber(notes.length)) }) },
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
              placeholder={tr("Datei suchen …")}
              aria-label={tr("Bibliotheken durchsuchen")}
              prefix={<Search />}
              suffix={
                query ? (
                  <IconButton
                    size="xs"
                    label={tr("Suche leeren")}
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
            title={tr("Keine Treffer")}
            description={needle ? tr("Keine Bibliothek passt zu „{0}“.", { "0": String(query.trim()) }) : tr("Keine Bibliothek in diesem Filter.")}
            actions={
              <Button
                size="sm"
                onClick={() => {
                  setQuery('')
                  setFilter('all')
                }}
              >
                {tr("Filter zurücksetzen")}</Button>
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
            {formatNumber(Math.min(LIB_PAGE * 4, rest))} {tr(" weitere anzeigen")}</Button>
          <span className="text-2xs text-fg-subtle">
            {formatNumber(shown.length)} {tr(" von ")}{plural(visible.length, tr("Datei"), tr("Dateien"))} {' '}{tr("angezeigt")}</span>
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
  const { t: tr } = useI18n()
  const { folder, name } = splitPath(lib.library)
  const detailId = `lib-${libraryKey(lib.library).replace(/[^a-z0-9]+/gi, '-')}`
  const undetermined = undeterminedLayers(lib)
  const manualCount = Object.keys(manual).length
  const pending = pendingRoles(lib, manual)
  const status = lib.problem
    ? tr("nicht prüfbar")
    : tr("{0} geprüft{1}{2}", { "0": String(plural(lib.selected, tr("Bauteil"), tr("Bauteile"))), "1": String(lib.affected > 0
          ? tr(", {0} {1} ab", { 0: String(formatNumber(lib.affected)), 1: String(lib.affected === 1 ? tr("weicht") : tr("weichen")) })
          : lib.header.length
            ? ''
            : tr(", im Hausstil")), "2": String(lib.components > lib.selected ? tr(" · Datei enthält {0}", { 0: String(formatNumber(lib.components)) }) : '') })

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
                {tr("Nicht prüfbar")}</Badge>
            )}
            {lib.refusal && (
              <Badge variant="warning" dot>
                {tr("Wird übersprungen")}</Badge>
            )}
            {lib.header.length > 0 && (
              <Badge variant="info" dot>
                {tr("Lagen-Kopf")}</Badge>
            )}
            {undetermined > 0 && (
              <Badge variant="warning">
                {undetermined === 1 ? tr("1 Lage nicht erkannt") : tr("{0} Lagen nicht erkannt", { "0": String(formatNumber(undetermined)) })}
              </Badge>
            )}
            {manualCount > 0 && (
              <Badge variant="outline" className="font-normal">
                {manualCount === 1 ? tr("1 Rolle von Hand") : tr("{0} Rollen von Hand", { "0": String(formatNumber(manualCount)) })}
              </Badge>
            )}
            {pending > 0 && (
              <Badge variant="accent" dot>
                {tr("Rollen geändert")}</Badge>
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
                <Callout tone="danger" title={tr("Nicht prüfbar – bleibt unverändert")}>
                  {localizeMessage(lib.problem)}
                </Callout>
              )}
              {lib.refusal && (
                <Callout tone="warning" title={tr("Wird beim Anwenden übersprungen")}>
                  {localizeMessage(lib.refusal)}
                </Callout>
              )}
              {lib.header.length > 0 && (
                <div className="flex flex-col gap-1">
                  <h4 className="text-xs font-medium text-fg">{tr("Lagen-Kopf weicht ab")}</h4>
                  <p className="text-2xs leading-snug text-fg-subtle">
                    {tr("„Anwenden“ übernimmt Lagenaufbau und Lagensatz des Hausstils.")}</p>
                  <HeaderDeviations items={lib.header} />
                </div>
              )}
              {lib.kind === 'schlib' && lib.fonts.length > 0 && (
                <div className="flex flex-col gap-1">
                  <h4 className="text-xs font-medium text-fg">
                    {fontsChecked ? tr("Schrifttabelle nach der Umstellung") : tr("Schrifttabelle")}
                  </h4>
                  <ol className="mt-1 flex flex-wrap gap-1.5">
                    {lib.fonts.map((f, i) => (
                      <li key={`${i}-${f}`}>
                        <Badge variant="neutral" className="gap-1.5 font-normal">
                          <span className="mono text-fg-subtle">{i + 1}</span>
                          {localizeMessage(f)}
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
                  <p className="text-xs text-fg-muted">{tr("Die Footprints dieser Datei nutzen keine mechanischen Lagen.")}</p>
                ))}
              {lib.kind === 'schlib' && !lib.problem && !lib.fonts.length && !lib.refusal && (
                <p className="text-xs text-fg-muted">{tr("Keine weiteren Angaben zu dieser Datei.")}</p>
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
  const { t: tr } = useI18n()
  const [all, setAll] = useState(false)
  const shown = all ? items : items.slice(0, HEADER_FIRST)
  const hidden = items.length - shown.length
  return (
    <>
      <ul className="mt-1 flex flex-col gap-1 text-xs leading-snug text-fg-muted">
        {shown.map((h, i) => (
          <li key={i} className="flex items-start gap-1.5">
            <Layers aria-hidden className="mt-px size-3.5 shrink-0 text-info-text" />
            <span className="min-w-0 [overflow-wrap:anywhere]">{localizeMessage(h)}</span>
          </li>
        ))}
      </ul>
      {(hidden > 0 || all) && items.length > HEADER_FIRST && (
        <Button size="xs" variant="ghost" className="self-start" onClick={() => setAll((v) => !v)} aria-expanded={all}>
          {all ? tr("Weniger anzeigen") : tr("{0} anzeigen", { "0": String(plural(hidden, tr("weitere Abweichung"), tr("weitere Abweichungen"))) })}
        </Button>
      )}
    </>
  )
}
