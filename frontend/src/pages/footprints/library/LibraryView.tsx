import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { t as tr, getLocale, useI18n } from '@/components/preview/i18n'
/**
 * Footprint-Bibliothek: virtualisierte Galerie der gespeicherten Footprints (Registrierung) mit Suche und Filtern
 * (Familie, Status). Die Liste kommt ohne Vorschaubilder; jede Karte lädt ihr Bild erst im Sichtbereich vom
 * Vorschaubild-Endpunkt (ETag, mit Stand dauerhaft im Browser-Cache). Umschalter „Katalog“: alle Vorlagen nach
 * Familien gegliedert – ein Klick öffnet sie im Generator.
 */
import { BookOpen, Library, Plus, RefreshCw, Search, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { errorMessage } from '@/api/client'
import { useLibraryFootprints, type FootprintFamily, type FootprintPreset, type LibraryFootprint } from '@/api/footprints'
import { PageActions } from '@/app/page'
import { useRegisterCommands } from '@/app/commands'
import { GalleryCard, VirtualGallery } from '@/components/data'
import { CHROME_MUTED } from '@/components/preview'
import { useAltiumEditTargets } from '@/api/altiumEdit'
import { Badge, Button, EmptyState, Input, SegmentedControl, Select, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { familyMatches, familyShortLabel, groupFamilies, presetMatches } from '../lib/families'
import { formatDim } from '../lib/params'
import { PackageGlyph } from '../PackageGlyph'
import { CatalogGrid, type CatalogGroup } from './CatalogGrid'
import { FootprintThumb } from './FootprintThumb'
import { statusMeta, STATUS_META } from './meta'

export type LibrarySource = 'bibliothek' | 'katalog'

export interface LibraryViewProps {
  families: FootprintFamily[]
  active: boolean
  source: LibrarySource
  onSourceChange: (source: LibrarySource) => void
  selected: string | null
  onOpen: (name: string) => void
  onOpenPreset: (family: FootprintFamily, preset: FootprintPreset) => void
  /** Neuer Footprint: Generator mit offener Familienauswahl */
  onNew: () => void
}

const ALL = '__alle__'
const NONE = '__ohne__'

/** Passt der Familienschlüssel zum Filter („Alle“, „Ohne Familie“ oder eine Familie)? */
function familyFits(filter: string, key: string | null | undefined): boolean {
  return filter === ALL || (filter === NONE ? !key : key === filter)
}

export function LibraryView({
  families,
  active,
  source,
  onSourceChange,
  selected,
  onOpen,
  onOpenPreset,
  onNew,
}: LibraryViewProps) {
  useI18n()
  const [search, setSearch] = useState('')
  const [familyChoice, setFamily] = useState<string>(ALL)
  const [status, setStatus] = useState<string>(ALL)
  const searchRef = useRef<HTMLInputElement>(null)

  const list = useLibraryFootprints({}, { enabled: source === 'bibliothek' })
  const effectiveSource: LibrarySource = source
  const familyLabel = useLocalizedMemo(() => new Map(families.map((f) => [f.key, familyShortLabel(f)])), [families])

  // ------------------------------------------------------------------ Daten
  const entries = useLocalizedMemo(() => list.data ?? [], [list.data])
  const ordered = useLocalizedMemo(() => groupFamilies(families).flatMap((g) => g.families), [families])

  // Filter-Optionen mit Zählern
  const familyOptions = useLocalizedMemo(() => {
    const counts = new Map<string, number>()
    if (effectiveSource === 'bibliothek') for (const e of entries) counts.set(e.family ?? '', (counts.get(e.family ?? '') ?? 0) + 1)
    else for (const f of families) counts.set(f.key, f.presets.length)
    const total = effectiveSource === 'bibliothek' ? entries.length : families.reduce((n, f) => n + f.presets.length, 0)
    return [
      { value: ALL, label: tr("Alle Familien ({value0})", { value0: String(formatNumber(total)) }) },
      ...ordered
        .filter((f) => counts.has(f.key))
        .map((f) => ({
          value: f.key,
          label: `${familyShortLabel(f)} (${formatNumber(counts.get(f.key) ?? 0)})`,
          icon: <PackageGlyph family={f.key} className="size-4" />,
        })),
      ...(counts.has('') ? [{ value: NONE, label: tr("Ohne Familie ({value0})", { value0: String(counts.get('')) }) }] : []),
    ]
  }, [effectiveSource, entries, families, ordered])

  // Filter, die es in der aktuellen Quelle nicht gibt, gelten als „Alle“
  const family = familyOptions.some((o) => o.value === familyChoice) ? familyChoice : ALL

  const filtered = useLocalizedMemo(() => {
    const q = search.trim().toLowerCase()
    return entries
      .filter((e) => familyFits(family, e.family))
      .filter((e) => status === ALL || e.status === status)
      .filter((e) => {
        if (!q) return true
        const hay = [e.name, e.ipc_name ?? '', e.family ?? '', familyLabel.get(e.family ?? '') ?? '', e.library].join(' ').toLowerCase()
        return q.split(/\s+/).every((w) => hay.includes(w))
      })
      .sort((a, b) => a.name.localeCompare(b.name, getLocale(), { numeric: true }))
  }, [entries, family, status, search, familyLabel])

  const catalogGroups = useLocalizedMemo<CatalogGroup[]>(() => {
    const q = search.trim()
    return ordered
      .filter((f) => familyFits(family, f.key))
      .map((f) => {
        // Trifft die Suche die Familie selbst („soic“, „qfn“), erscheinen alle ihre Vorlagen
        const whole = q ? familyMatches(f, q) > 0 : true
        const items = f.presets
          .filter((p) => whole || presetMatches(p, q) > 0)
          .map((p) => ({ family: f, preset: p, key: `${f.key}:${p.key}` }))
        return { family: f, items }
      })
      .filter((g) => g.items.length > 0)
  }, [ordered, family, search])
  const catalogCount = catalogGroups.reduce((n, g) => n + g.items.length, 0)
  const catalogTotal = families.reduce((n, f) => n + f.presets.length, 0)

  const statusOptions = useLocalizedMemo(() => {
    const counts = new Map<string, number>()
    for (const e of entries) counts.set(e.status, (counts.get(e.status) ?? 0) + 1)
    return [
      { value: ALL, label: tr('Alle Status') },
      ...Object.keys(STATUS_META)
        .filter((k) => counts.has(k))
        .map((k) => ({ value: k, label: `${tr(STATUS_META[k].label)} (${counts.get(k)})` })),
    ]
  }, [entries])

  const filtersActive = search.trim() !== '' || family !== ALL || status !== ALL
  const resetFilters = () => {
    setSearch('')
    setFamily(ALL)
    setStatus(ALL)
  }

  useRegisterCommands(
    active
      ? [
          {
            id: 'footprints.library.search',
            title: tr('Footprints durchsuchen'),
            group: 'Footprints',
            hotkey: 'mod+f',
            icon: Search,
            run: () => searchRef.current?.focus(),
          },
          {
            id: 'footprints.library.catalog',
            title: effectiveSource === 'katalog' ? tr('Gespeicherte Footprints anzeigen') : tr('Vorlagen-Katalog anzeigen'),
            group: 'Footprints',
            icon: BookOpen,
            run: () => onSourceChange(effectiveSource === 'katalog' ? 'bibliothek' : 'katalog'),
          },
        ]
      : [],
  )

  const count = effectiveSource === 'bibliothek' ? filtered.length : catalogCount
  const total = effectiveSource === 'bibliothek' ? entries.length : catalogTotal

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      {active && (
        <PageActions>
          <Button variant="primary" leftIcon={<Plus />} onClick={onNew}>
            {tr("Neuer Footprint")}
          </Button>
        </PageActions>
      )}

      {/* Werkzeugleiste */}
      <div className="flex flex-wrap items-center gap-2">
        <Input
          ref={searchRef}
          size="sm"
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape' && search) {
              e.stopPropagation()
              setSearch('')
            }
          }}
          placeholder={effectiveSource === 'bibliothek' ? tr('Name oder Familie …') : tr('Vorlage, z. B. SOIC-8 …')}
          aria-label={effectiveSource === 'bibliothek' ? tr('Footprints durchsuchen') : tr('Vorlagen durchsuchen')}
          aria-keyshortcuts="Control+F"
          prefix={<Search />}
          suffix={
            search ? (
              <button type="button" aria-label={tr("Suche leeren")} onClick={() => setSearch('')} className="rounded-sm text-fg-subtle outline-none hover:text-fg focus-ring">
                <X className="size-3.5" />
              </button>
            ) : undefined
          }
          containerClassName="w-56 @[64rem]:w-72"
        />
        <Select size="sm" aria-label={tr("Familie")} value={family} onValueChange={setFamily} options={familyOptions} className="w-48 @[64rem]:w-60" />
        {effectiveSource === 'bibliothek' && (
          <Select size="sm" aria-label={tr("Status")} value={status} onValueChange={setStatus} options={statusOptions} className="w-36 @[64rem]:w-44" />
        )}
        {filtersActive && (
          <Button variant="ghost" size="sm" leftIcon={<X />} onClick={resetFilters}>
            {tr("Filter zurücksetzen")}
          </Button>
        )}
        <div className="ml-auto flex items-center gap-3">
          <span className="sr-only text-xs tabular-nums text-fg-subtle @[64rem]:not-sr-only" aria-live="polite">
            {count === total ? formatNumber(total) : tr("{value0} von {value1}", { value0: String(formatNumber(count)), value1: String(formatNumber(total)) })}{' '}
            {effectiveSource === 'bibliothek' ? 'Footprints' : tr('Vorlagen')}
          </span>
          <SegmentedControl
            size="sm"
            aria-label={tr("Quelle")}
            value={effectiveSource}
            onValueChange={onSourceChange}
            options={[
              { value: 'bibliothek', label: tr('Gespeichert'), icon: <Library /> },
              { value: 'katalog', label: tr('Katalog'), icon: <BookOpen /> },
            ]}
          />
        </div>
      </div>

      <div className="relative min-h-0 flex-1">
        {effectiveSource === 'bibliothek' ? (
          list.isPending ? (
            <GallerySkeleton />
          ) : list.isError ? (
            <div className="flex h-full items-center justify-center rounded-card border border-line bg-surface">
              <EmptyState
                illustration="offline"
                titleAs="h2"
                title={tr("Bibliothek konnte nicht geladen werden")}
                description={errorMessage(list.error)}
                actions={
                  <Button variant="secondary" leftIcon={<RefreshCw />} onClick={() => void list.refetch()}>
                    {tr("Erneut versuchen")}
                  </Button>
                }
              />
            </div>
          ) : entries.length === 0 ? (
            <div className="flex h-full items-center justify-center rounded-card border border-line bg-surface">
              <EmptyState
                illustration="forge"
                size="lg"
                titleAs="h2"
                title={tr("Noch keine Footprints gespeichert")}
                description={tr("Im Generator erzeugte Footprints landen hier – mit Vorschau, Status und 3D-Modell. Der Katalog zeigt alle Vorlagen zum Start.")}
                actions={
                  <>
                    <Button variant="secondary" leftIcon={<Plus />} onClick={onNew}>
                      {tr("Im Generator erstellen")}
                    </Button>
                    <Button variant="ghost" leftIcon={<BookOpen />} onClick={() => onSourceChange('katalog')}>
                      {tr("Katalog ansehen")}
                    </Button>
                  </>
                }
              />
            </div>
          ) : (
            <VirtualGallery<LibraryFootprint>
              aria-label={tr("Gespeicherte Footprints")}
              items={filtered}
              getKey={(e) => e.name}
              minItemWidth={184}
              itemHeight={192}
              gap={12}
              selectedKey={selected}
              // Klick, Leertaste und Enter öffnen genau einmal (Enter löst bei der Galerie auch „Auswählen“ aus)
              onSelect={(e) => onOpen(e.name)}
              className="absolute inset-0 -m-1 p-1"
              empty={
                <EmptyState
                  illustration="search-empty"
                  titleAs="h2"
                  title={tr("Keine Treffer")}
                  description={tr("Kein Footprint passt zu Suche und Filtern.")}
                  actions={
                    <Button variant="secondary" onClick={resetFilters}>
                      {tr("Filter zurücksetzen")}
                    </Button>
                  }
                />
              }
              renderItem={(e, st) => <SavedCard entry={e} familyLabel={familyLabel.get(e.family ?? '') ?? null} selected={st.selected} active={st.active} />}
            />
          )
        ) : (
          <CatalogGrid
            groups={catalogGroups}
            onOpen={onOpenPreset}
            empty={
              <EmptyState
                illustration="search-empty"
                titleAs="h2"
                title={tr("Keine Vorlage gefunden")}
                description={tr("Andere Schreibweise versuchen – z. B. „SOIC-8“, „0805“ oder „QFN“.")}
                actions={
                  <Button variant="secondary" onClick={resetFilters}>
                    {tr("Filter zurücksetzen")}
                  </Button>
                }
              />
            }
          />
        )}
      </div>
    </div>
  )
}

/** Marke auf der (immer dunklen) Leiterplatten-Fläche der Karte – ohne Unschärfe (viele Karten) */
const BOARD_BADGE = 'border-white/12 bg-[rgba(13,17,24,0.86)]'

function SavedCard({
  entry,
  familyLabel,
  selected,
  active,
}: {
  entry: LibraryFootprint
  familyLabel: string | null
  selected: boolean
  active: boolean
}) {
  useI18n()
  const meta = statusMeta(entry.status)
  const inAltium = useAltiumEditTargets('footprint').has(entry.name.toLocaleLowerCase('en'))
  return (
    <GalleryCard
      board
      selected={selected}
      active={active}
      title={entry.name}
      meta={[
        familyLabel ?? entry.family ?? 'Footprint',
        plural(entry.pad_count, tr('Pad'), tr('Pads')),
        entry.height ? `H ${formatDim(entry.height)}` : null,
      ]
        .filter(Boolean)
        .join(' · ')}
      badge={
        inAltium ? (
          <Badge variant="info" dot size="sm">
            {tr('In Altium geöffnet')}
          </Badge>
        ) : entry.status !== 'ok' ? (
          <Badge variant={meta.variant} dot size="sm">
            {tr(meta.label)}
          </Badge>
        ) : (
          <Badge size="sm" variant="outline" className={cn(BOARD_BADGE, entry.usage > 0 ? 'text-[#D5DBE6]' : CHROME_MUTED.board)}>
            {entry.usage === 0 ? tr('unbenutzt') : plural(entry.usage, tr('Bauteil'), tr('Bauteile'))}
          </Badge>
        )
      }
      thumbnail={<FootprintThumb entry={entry} />}
    />
  )
}

function GallerySkeleton() {
  return (
    <div aria-hidden className="grid grid-cols-[repeat(auto-fill,minmax(184px,1fr))] gap-3">
      {Array.from({ length: 12 }, (_, i) => (
        <div key={i} className="flex h-[192px] flex-col overflow-hidden rounded-card border border-line bg-surface">
          <div className="flex-1 bg-canvas p-4">
            <Skeleton className="size-full opacity-[0.12]" />
          </div>
          <div className="flex flex-col gap-1.5 px-3 py-2.5">
            <Skeleton className="h-3 w-3/4" />
            <Skeleton className="h-2.5 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  )
}
