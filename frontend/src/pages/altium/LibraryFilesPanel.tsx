/**
 * Bibliotheksdateien: jede SchLib/PcbLib der Bibliothek, gruppiert nach Art, mit Einträgen, Größe, Änderung und Abgleich
 * (synchron, ausstehend, fehlt, außerhalb geändert, Lagen) – der Grund steht als Text in der Zeile. Aktionen:
 * Synchronisieren, Prüfen (optional mit Übernahme unbekannter Einträge), je Datei „In Altium öffnen“ und „Im Explorer
 * zeigen“ (Datei markiert; außerhalb des Desktop-Programms wird der Pfad kopiert).
 *
 * Lange Listen (Layout „eine Datei je Bauteil“): keine Animation je Zeile, je Art zuerst {@link FILE_PAGE} Dateien
 * („weitere anzeigen“), ab {@link SEARCH_FROM} Dateien ein Suchfeld.
 */
import {
  ChevronDown,
  CircuitBoard,
  FolderOpen,
  FolderSearch,
  FolderSync,
  Info,
  Layers,
  Search,
  Shapes,
  SquareArrowOutUpRight,
  X,
} from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { libraryKey, type LibraryFile, type LibraryHeights } from '@/api/libraries'
import {
  Badge,
  Button,
  Callout,
  Card,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  EmptyState,
  IconButton,
  Input,
  SegmentedControl,
  Skeleton,
  type BadgeProps,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatBytes, formatDateTime, formatNumber, formatRelativeTime, plural } from '@/lib/format'
import { revealPath, useNativeBridge } from '@/lib/native'
import type { FilesSummary } from './model'
import { SETTINGS_PLACE } from './settingsPlaces'
import { FilterLabel } from './ui'
import type { AltiumActions } from './useAltiumActions'

/** So viele Dateien je Art zeigt die Tabelle zuerst (weitere auf Wunsch) */
export const FILE_PAGE = 60
/** Ab so vielen Dateien gibt es ein Suchfeld */
const SEARCH_FROM = 16

interface FileState {
  label: string
  variant: NonNullable<BadgeProps['variant']>
  /** Grund bzw. nächster Schritt – sichtbar neben dem Zustand */
  reason: string
}

const names = (list: string[], max = 4) => list.slice(0, max).join(', ') + (list.length > max ? ` und ${formatNumber(list.length - max)} weitere` : '')

const NO_HEIGHTS: LibraryHeights = { total: 0, repairable: 0 }

/** Zustände einer Datei, wichtigster zuerst (`heights`: Footprints ohne Höhe laut Prüfbericht) */
function fileStates(f: LibraryFile, heights: LibraryHeights = NO_HEIGHTS): FileState[] {
  const out: FileState[] = []
  if (!f.exists) out.push({ label: 'Datei fehlt', variant: 'danger', reason: '„Synchronisieren“ schreibt sie neu' })
  // beschädigt (nicht lesbar): geht „außerhalb geändert“ vor – Behebung im Prüfbericht („Aus Sicherung wiederherstellen“)
  if (f.exists && f.unreadable) {
    out.push({ label: 'Beschädigt', variant: 'danger', reason: 'nicht lesbar – im Prüfbericht „Aus Sicherung wiederherstellen“' })
  }
  if (f.errors) out.push({ label: plural(f.errors, 'Fehler', 'Fehler'), variant: 'danger', reason: 'Schreiben fehlgeschlagen – Details im Prüfbericht' })
  if (f.pending) out.push({ label: `${formatNumber(f.pending)} ausstehend`, variant: 'warning', reason: 'beim nächsten Synchronisieren' })
  if (f.exists && f.missing.length) {
    out.push({ label: plural(f.missing.length, 'fehlt', 'fehlen'), variant: 'warning', reason: `nicht in der Datei: ${names(f.missing)}` })
  }
  if (f.external_changes && !f.unreadable) {
    out.push({ label: 'Außerhalb geändert', variant: 'warning', reason: 'PartForge ersetzt hier nur noch eigene, geänderte Einträge' })
  }
  if (f.layers_ok === false) {
    out.push({ label: 'Lagen abweichend', variant: 'warning', reason: `unter ${SETTINGS_PLACE.layers.label} übertragen` })
  }
  if (heights.total) {
    out.push({
      label: plural(heights.total, 'Höhe fehlt', 'Höhen fehlen'),
      variant: 'warning',
      reason: heights.repairable
        ? 'Höhe 0 in der PcbLib – „Footprint-Höhen nachtragen“ im Prüfbericht'
        : 'Höhe 0 in der PcbLib – außerhalb geändert: Höhe in Altium eintragen',
    })
  }
  if (f.exists && f.components === null && !f.unreadable) {
    out.push({ label: 'Nicht lesbar', variant: 'neutral', reason: f.message ?? 'Inhalt nicht lesbar' })
  }
  if (f.unregistered.length) {
    out.push({
      label: `${formatNumber(f.unregistered.length)} unbekannt`,
      variant: 'info',
      reason: `nicht registriert: ${names(f.unregistered)} – „Prüfen und unbekannte übernehmen“ registriert sie`,
    })
  }
  return out
}

function splitPath(rel: string): { folder: string; name: string } {
  const i = Math.max(rel.lastIndexOf('\\'), rel.lastIndexOf('/'))
  return i < 0 ? { folder: '', name: rel } : { folder: rel.slice(0, i + 1), name: rel.slice(i + 1) }
}

const KIND = {
  schlib: { title: 'Symbolbibliotheken', unit: ['Symbol', 'Symbole'], icon: Shapes },
  pcblib: { title: 'Footprint-Bibliotheken', unit: ['Footprint', 'Footprints'], icon: CircuitBoard },
} as const

export interface LibraryFilesPanelProps {
  files: LibraryFile[] | undefined
  summary: FilesSummary | null
  loading: boolean
  error: Error | null
  writer: { label: string; ok: boolean }
  actions: AltiumActions
  /** Warum „In Altium öffnen“ gerade nicht geht (`null` = Altium bereit) */
  blocker: string | null
  onRetry: () => void
  /** Footprints ohne Höhe je Bibliotheksdatei (Prüfbericht, `libraryFindings`) */
  heightsByLibrary?: Map<string, LibraryHeights>
}

export function LibraryFilesPanel({
  files,
  summary,
  loading,
  error,
  writer,
  actions,
  blocker,
  onRetry,
  heightsByLibrary,
}: LibraryFilesPanelProps) {
  const navigate = useNavigate()
  const [view, setView] = useState<'all' | 'issues'>('all')
  const [query, setQuery] = useState('')
  const sorted = useMemo(() => [...(files ?? [])].sort((a, b) => a.rel.localeCompare(b.rel, 'de', { numeric: true })), [files])
  const heightsOf = (f: LibraryFile) => heightsByLibrary?.get(libraryKey(f.rel)) ?? NO_HEIGHTS
  const withIssues = sorted.filter((f) => fileStates(f, heightsOf(f)).length > 0)
  // Große Bibliotheken: auf Dateien mit Abweichungen beschränken (nur anbieten, wenn es welche gibt)
  const effectiveView = withIssues.length ? view : 'all'
  const needle = query.trim().toLowerCase()
  const visible = (effectiveView === 'issues' ? withIssues : sorted).filter((f) => !needle || f.rel.toLowerCase().includes(needle))
  const groups = (['schlib', 'pcblib'] as const)
    .map((kind) => ({ kind, files: visible.filter((f) => f.kind === kind) }))
    .filter((g) => g.files.length > 0)
  const needsSync = Boolean(summary && (summary.pending || summary.errors || summary.missingFiles))
  const searchable = sorted.length >= SEARCH_FROM

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {withIssues.length > 0 && (
          <SegmentedControl<'all' | 'issues'>
            size="sm"
            aria-label="Dateien filtern"
            value={effectiveView}
            onValueChange={setView}
            options={[
              { value: 'all', label: <FilterLabel label="Alle" count={sorted.length} /> },
              { value: 'issues', label: <FilterLabel label="Mit Abweichungen" count={withIssues.length} tone="warning" /> },
            ]}
          />
        )}
        {searchable && (
          <Input
            size="sm"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && query) {
                e.stopPropagation()
                setQuery('')
              }
            }}
            placeholder="Datei suchen …"
            aria-label="Bibliotheksdateien durchsuchen"
            prefix={<Search />}
            suffix={query ? <IconButton size="xs" label="Suche leeren" icon={<X />} onClick={() => setQuery('')} tooltip={false} /> : undefined}
            containerClassName="w-56 max-w-full"
          />
        )}
        <div className="min-w-0 text-xs text-fg-muted" aria-live="polite">
          {summary ? (
            summary.total ? (
              <>
                <span className="font-medium text-fg">
                  {needle ? `${formatNumber(visible.length)} von ${plural(summary.total, 'Datei', 'Dateien')}` : plural(summary.total, 'Datei', 'Dateien')}
                </span>
                {' · '}
                {plural(summary.components, 'Eintrag', 'Einträge')}
              </>
            ) : (
              'Noch keine Bibliotheksdateien'
            )
          ) : loading ? (
            <Skeleton className="h-4 w-56" />
          ) : null}
        </div>
        <span className={cn('flex items-center gap-1.5 text-xs', writer.ok ? 'text-fg-subtle' : 'text-warning-text')}>
          <span aria-hidden className={cn('size-1.5 rounded-full', writer.ok ? 'bg-success' : 'bg-warning')} />
          {writer.label}
          {!writer.ok && (
            <Button variant="link" size="xs" className="text-xs" onClick={() => actions.run('writer')}>
              Writer einrichten →
            </Button>
          )}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="secondary" leftIcon={<FolderSearch />} rightIcon={<ChevronDown />} loading={actions.pending.scan}>
                Dateien prüfen
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80">
              <DropdownMenuItem description="Vergleicht Dateien und Registrierung, merkt fehlende Einträge vor" onSelect={() => void actions.scan(false)}>
                Prüfen
              </DropdownMenuItem>
              <DropdownMenuItem
                description="Registriert zusätzlich die unbekannten Einträge – solche, die nur in den Dateien stehen"
                onSelect={() => void actions.scan(true)}
              >
                Prüfen und unbekannte übernehmen
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button size="sm" variant="secondary" leftIcon={<FolderSync />} loading={actions.pending.sync} onClick={() => void actions.sync()}>
            Synchronisieren
            {needsSync && summary && (
              <span className="mono ml-0.5 rounded-full bg-warning/15 px-1.5 text-2xs leading-4 text-warning-text">
                {formatNumber(summary.pending + summary.errors)}
                <span className="sr-only"> ausstehend</span>
              </span>
            )}
          </Button>
        </div>
      </div>

      {error && (
        <Callout
          tone="danger"
          title="Bibliotheksdateien konnten nicht gelesen werden"
          actions={
            <Button size="sm" onClick={onRetry}>
              Erneut versuchen
            </Button>
          }
        >
          {error.message}
        </Callout>
      )}

      <Card className="@container overflow-hidden">
        {loading ? (
          <FilesSkeleton />
        ) : groups.length === 0 && !error && needle ? (
          <EmptyState
            size="sm"
            illustration="search-empty"
            title="Keine Treffer"
            description={`Keine Bibliotheksdatei passt zu „${query.trim()}“.`}
            actions={
              <Button size="sm" onClick={() => setQuery('')}>
                Suche leeren
              </Button>
            }
          />
        ) : groups.length === 0 && !error ? (
          <EmptyState
            illustration="forge"
            title="Noch keine Bibliotheksdateien"
            description="SchLib- und PcbLib-Dateien entstehen mit den ersten Symbolen und Footprints – Serien-Assistent, Datenblatt-Import und Footprint-Generator legen sie automatisch an."
            actions={
              <>
                <Button size="sm" leftIcon={<Layers />} onClick={() => navigate('/serien')}>
                  Serie erzeugen
                </Button>
                <Button size="sm" variant="ghost" leftIcon={<CircuitBoard />} onClick={() => navigate('/footprints')}>
                  Footprint-Generator
                </Button>
              </>
            }
          />
        ) : groups.length > 0 ? (
          <table className="w-full border-collapse text-left">
            <caption className="sr-only">Bibliotheksdateien der Bibliothek</caption>
            <thead>
              <tr className="border-b border-line text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
                <th scope="col" className="min-w-48 py-2.5 pl-4 pr-3 font-semibold">
                  Datei
                </th>
                <th scope="col" className="px-3 py-2.5 text-right font-semibold">
                  Einträge
                </th>
                <th scope="col" className="hidden px-3 py-2.5 text-right font-semibold @[50rem]:table-cell">
                  Größe
                </th>
                <th scope="col" className="px-3 py-2.5 font-semibold">
                  Geändert
                </th>
                <th scope="col" className="px-3 py-2.5 font-semibold">
                  Zustand
                </th>
                <th scope="col" className="py-2.5 pl-3 pr-4 text-right font-semibold">
                  <span className="sr-only">Aktionen</span>
                </th>
              </tr>
            </thead>
            {groups.map((g) => (
              // neue Suche bzw. Ansicht → wieder mit der ersten Seite beginnen
              <FileGroup
                key={`${g.kind}|${effectiveView}|${needle}`}
                kind={g.kind}
                files={g.files}
                actions={actions}
                blocker={blocker}
                heightsOf={heightsOf}
              />
            ))}
          </table>
        ) : null}
      </Card>

      <p className="flex items-start gap-2 px-1 text-xs leading-relaxed text-fg-subtle">
        <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        <span>
          <span className="text-fg-muted">Synchronisieren</span> schreibt ausstehende Symbole und Footprints in ihre Dateien.{' '}
          <span className="text-fg-muted">Prüfen</span> vergleicht Dateien und Registrierung: fehlende Einträge werden vorgemerkt,
          außerhalb geänderte Dateien erkannt; <span className="text-fg-muted">Prüfen und unbekannte übernehmen</span> registriert
          zusätzlich die unbekannten Einträge, die nur in den Dateien stehen. Dateien ohne Kennzeichnung schreibt PartForge
          vollständig selbst; <span className="text-fg-muted">gemischt</span> heißt, die Datei enthält fremde oder außerhalb
          geänderte Einträge – dort ersetzt PartForge nur eigene Einträge einzeln.
        </span>
      </p>
    </div>
  )
}

function FileGroup({
  kind,
  files,
  actions,
  blocker,
  heightsOf,
}: {
  kind: 'schlib' | 'pcblib'
  files: LibraryFile[]
  actions: AltiumActions
  blocker: string | null
  heightsOf: (f: LibraryFile) => LibraryHeights
}) {
  const [limit, setLimit] = useState(FILE_PAGE)
  const meta = KIND[kind]
  const Icon = meta.icon
  const folders = new Set(files.map((f) => splitPath(f.rel).folder))
  const common = folders.size === 1 ? [...folders][0] : null
  const entries = files.reduce((n, f) => n + (f.components ?? 0), 0)
  const shown = files.slice(0, limit)
  const rest = files.length - shown.length
  return (
    <tbody className="border-t border-line first-of-type:border-t-0">
      <tr className="bg-[color-mix(in_oklab,var(--pf-surface-2)_55%,transparent)]">
        <th scope="colgroup" colSpan={6} className="px-4 py-1.5 text-left font-normal">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            <Icon aria-hidden className="size-3.5 text-fg-muted" />
            <span className="font-semibold text-fg">{meta.title}</span>
            <span className="text-fg-subtle">
              {common ? <span className="mono">{common}</span> : 'mehrere Ordner'} · {plural(files.length, 'Datei', 'Dateien')} ·{' '}
              {plural(entries, meta.unit[0], meta.unit[1])}
            </span>
          </span>
        </th>
      </tr>
      {shown.map((f) => (
        <FileRow key={f.path} file={f} actions={actions} blocker={blocker} showFolder={!common} heights={heightsOf(f)} />
      ))}
      {rest > 0 && (
        <tr className="border-t border-line">
          <td colSpan={6} className="px-4 py-2 text-2xs text-fg-subtle">
            <Button size="xs" variant="ghost" className="mr-3" onClick={() => setLimit((l) => l + FILE_PAGE * 4)}>
              {formatNumber(Math.min(FILE_PAGE * 4, rest))} weitere anzeigen
            </Button>
            {formatNumber(shown.length)} von {plural(files.length, 'Datei', 'Dateien')} angezeigt
          </td>
        </tr>
      )}
    </tbody>
  )
}

function FileRow({
  file: f,
  actions,
  blocker,
  showFolder,
  heights,
}: {
  file: LibraryFile
  actions: AltiumActions
  blocker: string | null
  showFolder: boolean
  /** Footprints ohne Höhe in dieser PcbLib (Prüfbericht) */
  heights: LibraryHeights
}) {
  const bridge = useNativeBridge()
  const { folder, name } = splitPath(f.rel)
  const states = fileStates(f, heights)
  const managedLabel = f.managed ? null : f.registered === 0 ? 'fremde Datei' : 'gemischt'
  const openLabel = blocker ? `${name} in Altium öffnen – ${blocker}` : `${name} in Altium öffnen`
  // Desktop: Explorer mit markierter Datei; Browser: Pfad kopieren (revealPath meldet es)
  const revealLabel = bridge.canRevealPath || bridge.canOpenPath ? `${name} im Explorer zeigen` : `Pfad von ${name} kopieren`

  return (
    <tr className="group/row border-t border-line align-top transition-colors hover:bg-surface-2/60">
      <td className="py-2 pl-4 pr-3">
        <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <span className="min-w-0 break-all text-ui font-medium text-fg" title={f.path}>
            {name}
          </span>
          {showFolder && folder && <span className="mono text-2xs text-fg-subtle">{folder}</span>}
          {managedLabel && (
            <Badge variant="outline" size="sm" className="self-center font-normal">
              {managedLabel}
            </Badge>
          )}
        </div>
      </td>
      <td className="px-3 py-2 text-right">
        <span className="mono text-ui text-fg">{f.components === null ? '–' : formatNumber(f.components)}</span>
        {f.components !== null && f.registered !== f.components && (
          <div className="whitespace-nowrap text-2xs text-fg-subtle">{formatNumber(f.registered)} registriert</div>
        )}
      </td>
      <td className="mono hidden whitespace-nowrap px-3 py-2 text-right text-xs leading-5 text-fg-muted @[50rem]:table-cell">
        {f.size === null ? '–' : formatBytes(f.size)}
      </td>
      <td className="whitespace-nowrap px-3 py-2 text-xs leading-5 text-fg-muted">
        {f.modified ? <time dateTime={f.modified} title={formatDateTime(f.modified)}>{formatRelativeTime(f.modified)}</time> : '–'}
      </td>
      <td className="px-3 py-2">
        {states.length === 0 ? (
          <span className="inline-flex items-center gap-1.5 text-xs leading-5 text-fg-muted">
            <span aria-hidden className={cn('size-1.5 rounded-full', f.in_sync ? 'bg-success' : 'bg-fg-subtle')} />
            {f.in_sync ? 'Synchron' : 'Geprüft'}
          </span>
        ) : (
          <ul className="flex flex-col gap-1">
            {states.map((s) => (
              <li key={s.label} className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                <Badge variant={s.variant} dot>
                  {s.label}
                </Badge>
                <span className="min-w-0 text-2xs leading-snug text-fg-muted">{s.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </td>
      <td className="py-1.5 pl-3 pr-4">
        <div className="flex items-center justify-end gap-0.5">
          {blocker || !f.exists ? (
            <IconButton
              size="xs"
              label={f.exists ? openLabel : `${name} fehlt – nichts zu öffnen`}
              icon={<SquareArrowOutUpRight />}
              aria-disabled
              className="aria-disabled:pointer-events-auto aria-disabled:cursor-not-allowed"
            />
          ) : (
            <IconButton size="xs" label={openLabel} icon={<SquareArrowOutUpRight />} onClick={() => void actions.openInAltium(f.path)} />
          )}
          {f.exists ? (
            <IconButton size="xs" label={revealLabel} icon={<FolderOpen />} onClick={() => void revealPath(f.path, { what: 'Bibliotheksdatei' })} />
          ) : (
            <IconButton
              size="xs"
              label={`${name} fehlt – nichts im Explorer zu zeigen`}
              icon={<FolderOpen />}
              aria-disabled
              className="aria-disabled:pointer-events-auto aria-disabled:cursor-not-allowed"
            />
          )}
        </div>
      </td>
    </tr>
  )
}

function FilesSkeleton() {
  return (
    <div className="divide-y divide-line" aria-busy="true" aria-label="Bibliotheksdateien werden gelesen">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center gap-3 px-4 py-3">
          <div className="flex-1">
            <Skeleton className="h-3.5 w-48" />
          </div>
          <Skeleton className="h-3.5 w-12" />
          <Skeleton className="h-3.5 w-16" />
          <Skeleton className="h-5 w-20 rounded-full" />
          <Skeleton className="h-5 w-24 rounded-full" />
        </div>
      ))}
    </div>
  )
}
