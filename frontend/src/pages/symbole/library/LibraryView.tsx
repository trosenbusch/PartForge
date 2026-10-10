import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Bibliothek-Ansicht: alle registrierten Symbole als virtualisierte Galerie (Vorschaubild vom Endpunkt
 * `…/symbols/{name}/thumbnail.svg` – lädt im Sichtbereich, mit Stand dauerhaft im Browser-Cache), Typ, Pins,
 * Verwendung und Status – mit Suche, Filtern (Typ-Gruppe, Quelle, Status) und Sortierung; Detaildialog mit
 * Verwendung, „Bearbeiten“ und „Neu generieren“.
 */
import { ArrowDownWideNarrow, Filter, Plus, RotateCcw, Search, X } from 'lucide-react'
import { useRef } from 'react'
import { useAltiumEditTargets } from '@/api/altiumEdit'
import { errorMessage } from '@/api/client'
import { SYMBOL_GROUPS, useSymbolKinds, useSymbolLibrary, type SymbolEntry, type SymbolKindInfo } from '@/api/symbols'
import { PageActions } from '@/app/page'
import { useTheme } from '@/app/theme'
import { GalleryCard, VirtualGallery } from '@/components/data'
import { Badge, Button, EmptyState, Input, Select, Skeleton } from '@/components/ui'
import { formatNumber, plural } from '@/lib/format'
import { naturalCompare } from '@/lib/geometry'
import type { OpenResult } from '../generator/load'
import { useLibraryFilters, type LibrarySort } from '../store'
import { useSymbolJob } from '../useSymbolJob'
import { parseUpdated, SOURCE_LABEL, STATUS_LABEL } from '../util'
import { SymbolDetailDialog, type DetailTarget } from './SymbolDetailDialog'
import { SymbolThumb } from './SymbolThumb'

export interface LibraryViewProps {
  /** Symbol bzw. Typ wurde in den Generator geladen → zur Generator-Ansicht wechseln */
  onEdit: (result: OpenResult) => void
  onNewSymbol: () => void
}

const OTHER_GROUP = 'Eigene Symbole'
/** Galerie-Maße (Skelett und Galerie identisch, damit beim Laden nichts springt) */
const CARD_MIN_WIDTH = 188
const CARD_HEIGHT = 204

const fold = (s: string) =>
  s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')

/** Platzhalter im Raster der Galerie (gleicher Rand, gleiche Spaltenformel wie `VirtualGallery`) */
function GallerySkeleton() {
  useI18n()
  return (
    <div className="h-full min-h-0 overflow-hidden px-4 pb-4 pt-3" aria-busy="true">
      <span className="sr-only">{tr("Symbole werden geladen …")}</span>
      <div className="grid gap-3 p-2" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${CARD_MIN_WIDTH}px, 1fr))` }} aria-hidden>
        {Array.from({ length: 15 }, (_, i) => (
          <div key={i} className="overflow-hidden rounded-card border border-line bg-surface" style={{ height: CARD_HEIGHT }}>
            <Skeleton className="h-[148px] rounded-none opacity-60" />
            <div className="space-y-1.5 p-3">
              <Skeleton className="h-3 w-2/3" />
              <Skeleton className="h-2.5 w-1/2" />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Typ eines Eintrags: Generator-Typ bzw. Herkunft eigener Symbole („Importiert“, „Datenblatt“ …) */
function entryTypeLabel(e: SymbolEntry, kindLabel: (key: string) => string | undefined): string {
  if (e.kind) return tr(kindLabel(e.kind) ?? e.kind)
  return e.source === 'generated' ? tr('Eigenes Symbol') : (tr(SOURCE_LABEL[e.source]) ?? tr('Eigenes Symbol'))
}

function StatusOrUsage({ entry }: { entry: SymbolEntry }) {
  useI18n()
  const status = STATUS_LABEL[entry.status]
  const inAltium = useAltiumEditTargets('symbol').has(entry.name.toLocaleLowerCase('en'))
  if (inAltium) {
    return (
      <Badge variant="info" dot>
        {tr('In Altium geöffnet')}
      </Badge>
    )
  }
  if (status && status.tone !== 'success') {
    return (
      <Badge variant={status.tone === 'danger' ? 'danger' : 'warning'} dot>
        {tr(status.label)}
      </Badge>
    )
  }
  if (entry.usage > 0) return <Badge className="bg-surface/90">{plural(entry.usage, tr('Bauteil'), tr('Bauteile'))}</Badge>
  return (
    <Badge variant="outline" className="bg-surface/90">
      {tr("unbenutzt")}
    </Badge>
  )
}

export function LibraryView({ onEdit, onNewSymbol }: LibraryViewProps) {
  useI18n()
  const { resolvedTheme } = useTheme()
  const lib = useSymbolLibrary()
  const kinds = useSymbolKinds(resolvedTheme)
  // Suche, Filter, Sortierung und Auswahl bleiben beim Wechsel zum Generator und zurück erhalten
  // (auch die geöffnete Detailansicht – „In der Bibliothek zeigen“ nach dem Speichern setzt sie über `showSymbol`)
  const { query, group, source, status, sort, selected, detail: detailState, set: setFilters, reset: resetFilters } = useLibraryFilters()
  const setQuery = (v: string) => setFilters({ query: v })
  const setSelected = (v: string | null) => setFilters({ selected: v })
  const contentRef = useRef<HTMLDivElement>(null)
  const startJob = useSymbolJob()

  const kindByKey = useLocalizedMemo(() => new Map((kinds.data ?? []).map((k) => [k.key, k])), [kinds.data])
  const kindOf = detailState?.type === 'kind' ? kindByKey.get(detailState.key) : undefined
  const detail: DetailTarget | null =
    detailState?.type === 'symbol' ? detailState : kindOf ? { type: 'kind', kind: kindOf } : null
  const setDetail = (target: { type: 'symbol'; name: string } | { type: 'kind'; kind: SymbolKindInfo } | null) =>
    setFilters({ detail: target === null ? null : target.type === 'symbol' ? target : { type: 'kind', key: target.kind.key } })
  const entries = useLocalizedMemo(() => lib.data ?? [], [lib.data])
  const kindLabel = (e: SymbolEntry) => entryTypeLabel(e, (key) => kindByKey.get(key)?.label)

  // Filter-Optionen nur mit vorhandenen Werten (mit Zählern)
  const counts = useLocalizedMemo(() => {
    const g = new Map<string, number>()
    const s = new Map<string, number>()
    const st = new Map<string, number>()
    for (const e of entries) {
      const gr = e.kind ? (kindByKey.get(e.kind)?.group ?? OTHER_GROUP) : OTHER_GROUP
      g.set(gr, (g.get(gr) ?? 0) + 1)
      s.set(e.source, (s.get(e.source) ?? 0) + 1)
      st.set(e.status, (st.get(e.status) ?? 0) + 1)
    }
    return { g, s, st }
  }, [entries, kindByKey])

  const filtered = useLocalizedMemo(() => {
    const q = fold(query.trim())
    const list = entries.filter((e) => {
      if (group !== 'alle' && (e.kind ? (kindByKey.get(e.kind)?.group ?? OTHER_GROUP) : OTHER_GROUP) !== group) return false
      if (source !== 'alle' && e.source !== source) return false
      if (status !== 'alle' && e.status !== status) return false
      if (!q) return true
      const hay = fold([e.name, e.library, e.kind ?? '', e.kind ? (kindByKey.get(e.kind)?.label ?? '') : ''].join(' '))
      return q.split(/\s+/).every((t) => hay.includes(t))
    })
    const sorted = [...list]
    if (sort === 'name') sorted.sort((a, b) => naturalCompare(a.name, b.name))
    else if (sort === 'usage') sorted.sort((a, b) => b.usage - a.usage || naturalCompare(a.name, b.name))
    else sorted.sort((a, b) => (parseUpdated(b.updated) ?? 0) - (parseUpdated(a.updated) ?? 0) || naturalCompare(a.name, b.name))
    return sorted
  }, [entries, query, group, source, status, sort, kindByKey])

  /** Liste geladen (sonst Laden bzw. Fehler – dann keine Zähler, die „0“ behaupten) */
  const loaded = lib.data !== undefined
  const filtersActive = query.trim() !== '' || group !== 'alle' || source !== 'alle' || status !== 'alle'

  const groupOptions = [
    { value: 'alle', label: tr('Alle Typen') },
    ...[...SYMBOL_GROUPS, OTHER_GROUP]
      .filter((g) => counts.g.has(g))
      .map((g) => ({
        value: g,
        label: tr(g),
        badge: <span className="text-2xs tabular-nums text-fg-subtle">{formatNumber(counts.g.get(g) ?? 0)}</span>,
      })),
  ]

  const toolbar = (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-6 py-2.5">
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
        placeholder={tr("Symbol, Bibliothek oder Typ suchen")}
        aria-label={tr("Symbole durchsuchen")}
        prefix={<Search />}
        containerClassName="w-64"
      />
      <Select size="sm" aria-label={tr("Typ-Gruppe")} prefix={<Filter />} value={group} onValueChange={(v) => setFilters({ group: v })} options={groupOptions} className="w-44" />
      <Select
        size="sm"
        aria-label={tr("Quelle")}
        disabled={!loaded}
        value={source}
        onValueChange={(v) => setFilters({ source: v })}
        className="w-40"
        options={[
          { value: 'alle', label: tr('Alle Quellen') },
          ...[...counts.s.keys()].map((s) => ({
            value: s,
            label: tr(SOURCE_LABEL[s]) ?? s,
            badge: <span className="text-2xs tabular-nums text-fg-subtle">{formatNumber(counts.s.get(s) ?? 0)}</span>,
          })),
        ]}
      />
      <Select
        size="sm"
        aria-label={tr("Status")}
        disabled={!loaded}
        value={status}
        onValueChange={(v) => setFilters({ status: v })}
        className="w-36"
        options={[
          { value: 'alle', label: tr('Jeder Status') },
          ...[...counts.st.keys()].map((s) => ({
            value: s,
            label: tr(STATUS_LABEL[s]?.label ?? s),
            badge: <span className="text-2xs tabular-nums text-fg-subtle">{formatNumber(counts.st.get(s) ?? 0)}</span>,
          })),
        ]}
      />
      <Select<LibrarySort>
        size="sm"
        aria-label={tr("Sortierung")}
        disabled={!loaded}
        prefix={<ArrowDownWideNarrow />}
        value={sort}
        onValueChange={(v) => setFilters({ sort: v })}
        className="w-44"
        options={[
          { value: 'name', label: tr('Nach Name') },
          { value: 'usage', label: tr('Meist verwendet') },
          { value: 'updated', label: tr('Zuletzt geändert') },
        ]}
      />
      {filtersActive && (
        <Button size="sm" variant="ghost" leftIcon={<X />} onClick={resetFilters}>
          {tr("Filter zurücksetzen")}
        </Button>
      )}
      <span className="ml-auto text-xs tabular-nums text-fg-subtle" aria-live="polite">
        {!loaded
          ? null
          : filtersActive
            ? tr("{value0} von {value1}", { value0: String(formatNumber(filtered.length)), value1: String(plural(entries.length, tr('Symbol'), tr('Symbolen'))) })
            : plural(entries.length, tr('Symbol'), tr('Symbole'))}
      </span>
    </div>
  )

  let content
  if (lib.isLoading && !lib.data) {
    content = <GallerySkeleton />
  } else if (lib.error && !lib.data) {
    content = (
      <EmptyState
        illustration="offline"
        titleAs="h2"
        title={tr("Symbolbibliothek nicht geladen")}
        description={errorMessage(lib.error)}
        actions={
          <Button variant="secondary" leftIcon={<RotateCcw />} onClick={() => void lib.refetch()}>
            {tr("Erneut versuchen")}
          </Button>
        }
        className="h-full"
      />
    )
  } else if (entries.length === 0) {
    content = (
      <EmptyState
        illustration="forge"
        titleAs="h2"
        size="lg"
        title={tr("Noch keine Symbole in der Bibliothek")}
        description={tr("Erzeugen Sie Standardsymbole oder IC-Symbole im Generator und speichern Sie sie – sie erscheinen dann hier mit Vorschau und Verwendung.")}
        actions={
          <Button variant="secondary" leftIcon={<Plus />} onClick={onNewSymbol}>
            {tr("Symbol erzeugen")}
          </Button>
        }
        className="h-full"
      />
    )
  } else {
    content = (
      <div className="h-full min-h-0 px-4 pb-4 pt-3">
        <VirtualGallery<SymbolEntry>
          aria-label={tr("Symbole der Bibliothek")}
          items={filtered}
          getKey={(e) => e.name}
          minItemWidth={CARD_MIN_WIDTH}
          itemHeight={CARD_HEIGHT}
          padding={8}
          selectedKey={selected}
          onSelect={(e) => {
            setSelected(e.name)
            setDetail({ type: 'symbol', name: e.name })
          }}
          onActivate={(e) => setDetail({ type: 'symbol', name: e.name })}
          className="h-full"
          empty={
            <EmptyState
              illustration="search-empty"
              titleAs="h2"
              size="sm"
              title={tr("Keine Symbole gefunden")}
              description={tr("Kein Symbol passt zu Suche und Filtern.")}
              actions={
                <Button size="sm" variant="secondary" onClick={resetFilters}>
                  {tr("Filter zurücksetzen")}
                </Button>
              }
              className="h-full"
            />
          }
          renderItem={(e, s) => (
            <GalleryCard
              title={e.name}
              meta={
                <span title={`${kindLabel(e)} · ${plural(e.pin_count, tr('Pin'), tr('Pins'))}${e.part_count > 1 ? tr(" · {value0} Teile", { value0: String(formatNumber(e.part_count)) }) : ''}`}>
                  {plural(e.pin_count, tr('Pin'), tr('Pins'))}
                  {e.part_count > 1 ? tr(" · {value0} Teile", { value0: String(formatNumber(e.part_count)) }) : ''} · {kindLabel(e)}
                </span>
              }
              selected={s.selected}
              active={s.active}
              badge={<StatusOrUsage entry={e} />}
              thumbnail={<SymbolThumb entry={e} />}
            />
          )}
        />
      </div>
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageActions>
        <Button variant="primary" leftIcon={<Plus />} onClick={onNewSymbol}>
          {tr("Symbol erzeugen")}
        </Button>
      </PageActions>
      {toolbar}
      <div ref={contentRef} className="min-h-0 flex-1">
        {content}
      </div>
      <SymbolDetailDialog
        target={detail}
        onOpenChange={(open) => !open && setDetail(null)}
        onCloseAutoFocus={(e) => {
          // Fokus zurück in die Galerie (der Rückfall des UI-Kits behandelt Listboxen wie Overlays)
          const gallery = contentRef.current?.querySelector<HTMLElement>('[role="listbox"]')
          if (gallery) {
            e.preventDefault()
            gallery.focus({ preventScroll: true })
          }
        }}
        kinds={kinds.data}
        entries={entries}
        onEdit={onEdit}
        onJob={(job) => startJob(job, { openDock: true })}
      />
    </div>
  )
}
