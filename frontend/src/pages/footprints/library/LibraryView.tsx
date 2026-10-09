/**
 * Footprint-Bibliothek: virtualisierte Galerie der gespeicherten Footprints (Registrierung) mit Suche und Filtern
 * (Familie, Status). Die Liste kommt ohne Vorschaubilder; jede Karte lädt ihr Bild erst im Sichtbereich vom
 * Vorschaubild-Endpunkt (ETag, mit Stand dauerhaft im Browser-Cache). Umschalter „Katalog“: alle Vorlagen nach
 * Familien gegliedert – ein Klick öffnet sie im Generator.
 */
import { BookOpen, Library, Plus, RefreshCw, Search, X } from 'lucide-react'
import { useMemo, useRef, useState } from 'react'
import { errorMessage } from '@/api/client'
import { useLibraryFootprints, type FootprintFamily, type FootprintPreset, type LibraryFootprint } from '@/api/footprints'
import { PageActions } from '@/app/page'
import { useRegisterCommands } from '@/app/commands'
import { GalleryCard, VirtualGallery } from '@/components/data'
import { CHROME_MUTED } from '@/components/preview'
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
  const [search, setSearch] = useState('')
  const [familyChoice, setFamily] = useState<string>(ALL)
  const [status, setStatus] = useState<string>(ALL)
  const searchRef = useRef<HTMLInputElement>(null)

  const list = useLibraryFootprints({}, { enabled: source === 'bibliothek' })
  const effectiveSource: LibrarySource = source
  const familyLabel = useMemo(() => new Map(families.map((f) => [f.key, familyShortLabel(f)])), [families])

  // ------------------------------------------------------------------ Daten
  const entries = useMemo(() => list.data ?? [], [list.data])
  const ordered = useMemo(() => groupFamilies(families).flatMap((g) => g.families), [families])

  // Filter-Optionen mit Zählern
  const familyOptions = useMemo(() => {
    const counts = new Map<string, number>()
    if (effectiveSource === 'bibliothek') for (const e of entries) counts.set(e.family ?? '', (counts.get(e.family ?? '') ?? 0) + 1)
    else for (const f of families) counts.set(f.key, f.presets.length)
    const total = effectiveSource === 'bibliothek' ? entries.length : families.reduce((n, f) => n + f.presets.length, 0)
    return [
      { value: ALL, label: `Alle Familien (${formatNumber(total)})` },
      ...ordered
        .filter((f) => counts.has(f.key))
        .map((f) => ({
          value: f.key,
          label: `${familyShortLabel(f)} (${formatNumber(counts.get(f.key) ?? 0)})`,
          icon: <PackageGlyph family={f.key} className="size-4" />,
        })),
      ...(counts.has('') ? [{ value: NONE, label: `Ohne Familie (${counts.get('')})` }] : []),
    ]
  }, [effectiveSource, entries, families, ordered])

  // Filter, die es in der aktuellen Quelle nicht gibt, gelten als „Alle“
  const family = familyOptions.some((o) => o.value === familyChoice) ? familyChoice : ALL

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return entries
      .filter((e) => familyFits(family, e.family))
      .filter((e) => status === ALL || e.status === status)
      .filter((e) => {
        if (!q) return true
        const hay = [e.name, e.ipc_name ?? '', e.family ?? '', familyLabel.get(e.family ?? '') ?? '', e.library].join(' ').toLowerCase()
        return q.split(/\s+/).every((w) => hay.includes(w))
      })
      .sort((a, b) => a.name.localeCompare(b.name, 'de', { numeric: true }))
  }, [entries, family, status, search, familyLabel])

  const catalogGroups = useMemo<CatalogGroup[]>(() => {
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

  const statusOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const e of entries) counts.set(e.status, (counts.get(e.status) ?? 0) + 1)
    return [
      { value: ALL, label: 'Alle Status' },
      ...Object.keys(STATUS_META)
        .filter((k) => counts.has(k))
        .map((k) => ({ value: k, label: `${STATUS_META[k].label} (${counts.get(k)})` })),
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
            title: 'Footprints durchsuchen',
            group: 'Footprints',
            hotkey: 'mod+f',
            icon: Search,
            run: () => searchRef.current?.focus(),
          },
          {
            id: 'footprints.library.catalog',
            title: effectiveSource === 'katalog' ? 'Gespeicherte Footprints anzeigen' : 'Vorlagen-Katalog anzeigen',
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
            Neuer Footprint
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
          placeholder={effectiveSource === 'bibliothek' ? 'Name oder Familie …' : 'Vorlage, z. B. SOIC-8 …'}
          aria-label={effectiveSource === 'bibliothek' ? 'Footprints durchsuchen' : 'Vorlagen durchsuchen'}
          aria-keyshortcuts="Control+F"
          prefix={<Search />}
          suffix={
            search ? (
              <button type="button" aria-label="Suche leeren" onClick={() => setSearch('')} className="rounded-sm text-fg-subtle outline-none hover:text-fg focus-ring">
                <X className="size-3.5" />
              </button>
            ) : undefined
          }
          containerClassName="w-56 @[64rem]:w-72"
        />
        <Select size="sm" aria-label="Familie" value={family} onValueChange={setFamily} options={familyOptions} className="w-48 @[64rem]:w-60" />
        {effectiveSource === 'bibliothek' && (
          <Select size="sm" aria-label="Status" value={status} onValueChange={setStatus} options={statusOptions} className="w-36 @[64rem]:w-44" />
        )}
        {filtersActive && (
          <Button variant="ghost" size="sm" leftIcon={<X />} onClick={resetFilters}>
            Filter zurücksetzen
          </Button>
        )}
        <div className="ml-auto flex items-center gap-3">
          <span className="sr-only text-xs tabular-nums text-fg-subtle @[64rem]:not-sr-only" aria-live="polite">
            {count === total ? formatNumber(total) : `${formatNumber(count)} von ${formatNumber(total)}`}{' '}
            {effectiveSource === 'bibliothek' ? 'Footprints' : 'Vorlagen'}
          </span>
          <SegmentedControl
            size="sm"
            aria-label="Quelle"
            value={effectiveSource}
            onValueChange={onSourceChange}
            options={[
              { value: 'bibliothek', label: 'Gespeichert', icon: <Library /> },
              { value: 'katalog', label: 'Katalog', icon: <BookOpen /> },
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
                title="Bibliothek konnte nicht geladen werden"
                description={errorMessage(list.error)}
                actions={
                  <Button variant="secondary" leftIcon={<RefreshCw />} onClick={() => void list.refetch()}>
                    Erneut versuchen
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
                title="Noch keine Footprints gespeichert"
                description="Im Generator erzeugte Footprints landen hier – mit Vorschau, Status und 3D-Modell. Der Katalog zeigt alle Vorlagen zum Start."
                actions={
                  <>
                    <Button variant="secondary" leftIcon={<Plus />} onClick={onNew}>
                      Im Generator erstellen
                    </Button>
                    <Button variant="ghost" leftIcon={<BookOpen />} onClick={() => onSourceChange('katalog')}>
                      Katalog ansehen
                    </Button>
                  </>
                }
              />
            </div>
          ) : (
            <VirtualGallery<LibraryFootprint>
              aria-label="Gespeicherte Footprints"
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
                  title="Keine Treffer"
                  description="Kein Footprint passt zu Suche und Filtern."
                  actions={
                    <Button variant="secondary" onClick={resetFilters}>
                      Filter zurücksetzen
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
                title="Keine Vorlage gefunden"
                description="Andere Schreibweise versuchen – z. B. „SOIC-8“, „0805“ oder „QFN“."
                actions={
                  <Button variant="secondary" onClick={resetFilters}>
                    Filter zurücksetzen
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
  const meta = statusMeta(entry.status)
  return (
    <GalleryCard
      board
      selected={selected}
      active={active}
      title={entry.name}
      meta={[
        familyLabel ?? entry.family ?? 'Footprint',
        plural(entry.pad_count, 'Pad', 'Pads'),
        entry.height ? `H ${formatDim(entry.height)}` : null,
      ]
        .filter(Boolean)
        .join(' · ')}
      badge={
        entry.status !== 'ok' ? (
          <Badge variant={meta.variant} dot size="sm">
            {meta.label}
          </Badge>
        ) : (
          <Badge size="sm" variant="outline" className={cn(BOARD_BADGE, entry.usage > 0 ? 'text-[#D5DBE6]' : CHROME_MUTED.board)}>
            {entry.usage === 0 ? 'unbenutzt' : plural(entry.usage, 'Bauteil', 'Bauteile')}
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
