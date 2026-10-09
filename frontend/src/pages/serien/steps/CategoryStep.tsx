/**
 * Schritt 1 – Kategorie: vier Karten (Widerstände, Kondensatoren, Induktivitäten, Ferrite) mit Zahl der
 * Hersteller-Serien und der Bauteile in der Bibliothek. Darunter Schnellstart aus einer Teilenummer und
 * „Zuletzt verwendet“.
 */
import { ChevronRight, Check, History, RefreshCw } from 'lucide-react'
import { Fragment, useId, useMemo } from 'react'
import { errorMessage } from '@/api/client'
import { useCategories } from '@/api/library'
import { useSeriesTemplates, type DecodedMpn, type SeriesTemplateSummary } from '@/api/series'
import { Button, Callout, Card, Skeleton } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { CategoryGlyph } from '../components/CategoryGlyph'
import { StepHeading } from '../components/StepHeading'
import { useRadioCards } from '../components/useRadioCards'
import { SERIES_CATEGORIES, glyphFor } from '../model/categories'
import { describeSettings } from '../model/describe'
import { useSerien } from '../model/store'
import { QuickStart, type QuickStartApply } from './QuickStart'

export interface CategoryStepProps {
  onPick: (table: string) => void
  onResume: (template: SeriesTemplateSummary) => void
  onApplyDecoded: (apply: QuickStartApply) => void
  /** Schnellstart hat eine Serie erkannt (null = keine) – die Fußleiste bietet sie als Primäraktion an */
  onDecodedChange?: (decoded: DecodedMpn | null) => void
  onCustomTemplate: () => void
}

/** So viele zuletzt benutzte Vorlagen erscheinen unter „Zuletzt verwendet“ */
const RECENT_SHOWN = 3

/** Tabellenname als ID-Teil (ohne Leerzeichen – aria-labelledby trennt an Leerzeichen) */
const slugId = (table: string) => table.replace(/[^A-Za-z0-9_-]+/g, '-')

/** Herstellerliste kurz halten: erste Wörter langer Namen, höchstens vier, Rest als „+n“ */
function makerList(makers: string[]): string {
  const short = makers.map((m) => (m.length > 12 ? m.split(/\s+/)[0] : m))
  return short.length > 4 ? `${short.slice(0, 4).join(' · ')} +${short.length - 4}` : short.join(' · ')
}

interface CategoryCard {
  table: string
  label: string
  description: string
  color: string | null
  templates: SeriesTemplateSummary[]
  parts: number | null
}

export function CategoryStep({ onPick, onResume, onApplyDecoded, onDecodedChange, onCustomTemplate }: CategoryStepProps) {
  const uid = useId().replace(/:/g, '')
  const templates = useSeriesTemplates()
  const categories = useCategories()
  const selected = useSerien((s) => s.category)
  const setCategory = useSerien((s) => s.setCategory)
  const recent = useSerien((s) => s.recent)
  const settings = useSerien((s) => s.settings)

  const cards = useMemo<CategoryCard[]>(() => {
    const all = templates.data ?? []
    const known = SERIES_CATEGORIES.map((c) => c.table)
    // eigene Vorlagen für weitere Kategorien bekommen eigene Karten
    const extra = [...new Set(all.map((t) => t.category))].filter((t) => !known.includes(t))
    return [...known, ...extra].map((table) => {
      const meta = SERIES_CATEGORIES.find((c) => c.table === table)
      const def = categories.data?.find((c) => c.table === table)
      return {
        table,
        label: def?.label ?? meta?.label ?? table,
        description: meta?.description ?? 'Eigene Hersteller-Serien dieser Kategorie.',
        color: def?.color ?? null,
        templates: all.filter((t) => t.category === table),
        parts: def ? def.part_count : null,
      }
    })
  }, [templates.data, categories.data])

  const keys = cards.map((c) => c.table)
  const { radioProps } = useRadioCards({
    keys,
    value: selected,
    onChange: (k) => setCategory(k),
    onActivate: onPick,
    activateOnClick: true,
  })

  const recentTemplates = recent
    .map((id) => templates.data?.find((t) => t.id === id))
    .filter((t): t is SeriesTemplateSummary => Boolean(t))
    .slice(0, RECENT_SHOWN)
  const categoryLabel = (table: string) => cards.find((c) => c.table === table)?.label ?? table
  const failed = templates.isError
  const counts = !failed

  return (
    <section aria-labelledby="serien-kategorie" className="flex flex-col gap-5">
      <StepHeading
        id="serien-kategorie"
        title="Welche Bauteile sollen entstehen?"
        description="PartForge kennt die Teilenummern-Muster, Codetabellen und lieferbaren Werte der Hersteller – Sie wählen nur noch Bauformen und Bereich."
      />

      {failed && (
        <Callout
          tone="danger"
          urgent
          title="Hersteller-Serien nicht geladen"
          actions={
            <Button
              size="sm"
              variant="secondary"
              leftIcon={<RefreshCw />}
              loading={templates.isFetching}
              onClick={() => void templates.refetch()}
            >
              Erneut versuchen
            </Button>
          }
        >
          {errorMessage(templates.error)} Die Zahl der Serien je Kategorie ist deshalb unbekannt.
        </Callout>
      )}

      <div
        role="radiogroup"
        aria-labelledby="serien-kategorie"
        className="grid grid-cols-1 gap-4 @[40rem]:grid-cols-2 @[72rem]:grid-cols-4"
      >
        {templates.isPending
          ? SERIES_CATEGORIES.map((c) => <Skeleton key={c.table} className="h-[8.5rem] rounded-card @[72rem]:h-[15rem]" />)
          : cards.map((card) => {
              const isSelected = card.table === selected
              const makers = [...new Set(card.templates.map((t) => t.manufacturer))]
              return (
                <button
                  key={card.table}
                  type="button"
                  {...radioProps(card.table)}
                  aria-labelledby={`${uid}-${slugId(card.table)}-name`}
                  aria-describedby={`${uid}-${slugId(card.table)}-desc`}
                  className={cn(
                    'group/card relative flex min-h-[8.5rem] overflow-hidden rounded-card border bg-surface text-left shadow-card outline-none',
                    'flex-row @[72rem]:min-h-[15rem] @[72rem]:flex-col',
                    'transition-[transform,border-color,box-shadow] duration-200 ease-out focus-ring active:scale-[.99]',
                    'hover:-translate-y-px hover:border-line-strong hover:shadow-raised',
                    isSelected ? 'border-accent/60 shadow-[0_0_0_3px_var(--pf-accent-soft),var(--pf-shadow-raised)]' : 'border-line',
                  )}
                >
                  <span
                    className={cn(
                      'relative flex shrink-0 items-center justify-center bg-surface-2/60',
                      'w-[8.5rem] border-r border-line @[72rem]:h-[6.5rem] @[72rem]:w-auto @[72rem]:border-b @[72rem]:border-r-0',
                    )}
                  >
                    <span aria-hidden className="dot-grid absolute inset-0 opacity-70 mask-radial" />
                    <span
                      aria-hidden
                      className={cn(
                        'absolute inset-0 bg-[radial-gradient(closest-side,var(--pf-ember),transparent)] transition-opacity duration-300',
                        isSelected ? 'opacity-80' : 'opacity-0 group-hover/card:opacity-50',
                      )}
                    />
                    <CategoryGlyph
                      kind={glyphFor(card.table)}
                      className={cn(
                        'relative w-24 transition-[color,transform] duration-300 group-hover/card:scale-[1.04] @[72rem]:w-30',
                        isSelected ? 'text-accent' : 'text-fg-muted group-hover/card:text-fg',
                      )}
                    />
                    {isSelected && (
                      <span className="absolute right-2.5 top-2.5 flex size-5 items-center justify-center rounded-full bg-gradient-forge text-on-accent shadow-glow">
                        <Check aria-hidden className="size-3.5" strokeWidth={2.5} />
                      </span>
                    )}
                  </span>
                  <span className="flex min-w-0 flex-1 flex-col gap-1.5 px-4 pb-3.5 pt-3">
                    <span className="flex items-center gap-2">
                      {card.color && (
                        <span aria-hidden className="size-2 shrink-0 rounded-full" style={{ backgroundColor: card.color }} />
                      )}
                      <span id={`${uid}-${slugId(card.table)}-name`} className="text-md font-semibold tracking-[-0.01em] text-fg">
                        {card.label}
                      </span>
                    </span>
                    <span id={`${uid}-${slugId(card.table)}-desc`} className="line-clamp-2 text-xs leading-relaxed text-fg-muted">
                      {card.description}
                      <span className="sr-only">
                        {counts
                          ? ` ${plural(card.templates.length, 'Hersteller-Serie', 'Hersteller-Serien')}`
                          : ' Zahl der Hersteller-Serien unbekannt'}
                        {card.parts !== null ? `, ${formatNumber(card.parts)} in der Bibliothek.` : '.'}
                      </span>
                    </span>
                    {/* Kennzahlen untereinander – alle Karten gleich (nebeneinander bräche je nach Zahl mal um, mal nicht) */}
                    <span aria-hidden className="mt-auto flex flex-col gap-0.5 pt-1.5 text-xs text-fg-subtle">
                      <span>
                        <span className="mono font-semibold text-fg">{counts ? formatNumber(card.templates.length) : '–'}</span>{' '}
                        {counts && card.templates.length === 1 ? 'Hersteller-Serie' : 'Hersteller-Serien'}
                      </span>
                      {card.parts !== null && (
                        <span>
                          <span className="mono font-semibold text-fg">{formatNumber(card.parts)}</span> in der Bibliothek
                        </span>
                      )}
                    </span>
                    {counts && (
                      <span aria-hidden className="truncate text-2xs text-fg-subtle">
                        {makers.length ? makerList(makers) : 'Eigene Vorlage möglich'}
                      </span>
                    )}
                  </span>
                </button>
              )
            })}
      </div>

      <div
        className={cn(
          'grid grid-cols-1 items-start gap-4',
          recentTemplates.length > 0 && '@[64rem]:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]',
        )}
      >
        <QuickStart onApply={onApplyDecoded} onDecodedChange={onDecodedChange} onCustomTemplate={onCustomTemplate} />
        {recentTemplates.length > 0 && (
          <Card className="flex flex-col">
            <div className="flex items-start gap-3 px-4 pb-3 pt-4">
              <span
                aria-hidden
                className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted"
              >
                <History className="size-4" />
              </span>
              <div className="min-w-0 flex-1">
                <h3 id={`${uid}-recent`} className="text-sm font-semibold text-fg">
                  Zuletzt verwendet
                </h3>
                <p className="mt-0.5 text-xs text-fg-muted">Mit der gemerkten Auswahl weitermachen.</p>
              </div>
            </div>
            <ul aria-labelledby={`${uid}-recent`} className="flex flex-col divide-y divide-line border-t border-line">
              {recentTemplates.map((t) => {
                const saved = settings[t.id]
                const details = saved ? describeSettings(t, saved) : []
                return (
                  <li key={t.id}>
                    <button
                      type="button"
                      onClick={() => onResume(t)}
                      className="group/recent flex w-full items-center gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-surface-2/70 focus-ring-inset"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="micro-label block">{categoryLabel(t.category)}</span>
                        <span className="mt-0.5 block truncate text-ui font-medium text-fg">{t.title}</span>
                        {details.length > 0 && (
                          <span className="mt-0.5 block text-xs text-fg-muted">
                            {details.map((d, i) => (
                              <Fragment key={d}>
                                <span className="whitespace-nowrap">
                                  {d}
                                  {i < details.length - 1 && (
                                    <span aria-hidden className="ml-1.5 text-fg-subtle">
                                      ·
                                    </span>
                                  )}
                                </span>{' '}
                              </Fragment>
                            ))}
                          </span>
                        )}
                      </span>
                      <span className="sr-only">Fortsetzen</span>
                      <ChevronRight
                        aria-hidden
                        className="size-4 shrink-0 text-fg-subtle transition-[color,transform] group-hover/recent:translate-x-0.5 group-hover/recent:text-fg"
                      />
                    </button>
                  </li>
                )
              })}
            </ul>
          </Card>
        )}
      </div>
    </section>
  )
}
