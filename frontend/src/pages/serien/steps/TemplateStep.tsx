import { getLocale, useI18n } from '@/lib/i18n'
/**
 * Schritt 2 – Hersteller-Serie: Vorlagen der Kategorie als Karten (Beispiel-Teilenummer aus der Vorlagenliste,
 * Prüfstatus mit Quellen), Suche und Filter, eigene Vorlagen anlegen/bearbeiten/löschen.
 */
import { FilePlus2, Search } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useSeriesTemplates, type SeriesTemplateSummary } from '@/api/series'
import { Button, EmptyState, Input, SegmentedControl, Skeleton } from '@/components/ui'
import { plural } from '@/lib/format'
import { focusWhenReady } from '../components/focus'
import { LoadError } from '../components/LoadError'
import { StepHeading } from '../components/StepHeading'
import { useRadioCards } from '../components/useRadioCards'
import { TemplateCard } from './TemplateCard'

type Filter = 'all' | 'verified' | 'custom'

export interface TemplateStepProps {
  category: string
  categoryLabel: string
  value: string | null
  onChange: (id: string) => void
  onNext: (id: string) => void
  onCustomTemplate: (edit?: SeriesTemplateSummary) => void
  onDeleteCustom: (template: SeriesTemplateSummary) => void
  /** gerade gespeicherte eigene Vorlage: in den Blick holen und fokussieren, sobald sie in der Liste steht */
  revealId?: string | null
  onRevealed?: () => void
}

const fold = (s: string) => s.toLocaleLowerCase(getLocale())

export function TemplateStep({
  category,
  categoryLabel,
  value,
  onChange,
  onNext,
  onCustomTemplate,
  onDeleteCustom,
  revealId,
  onRevealed,
}: TemplateStepProps) {
  const { t: tr, tc } = useI18n()
  const templates = useSeriesTemplates(category)
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<Filter>('all')
  const all = useMemo(() => templates.data ?? [], [templates.data])
  const hasCustom = all.some((t) => !t.builtin)

  const shown = useMemo(() => {
    const q = fold(search.trim())
    return all.filter((t) => {
      if (filter === 'verified' && !t.verified) return false
      if (filter === 'custom' && t.builtin) return false
      if (!q) return true
      return [t.manufacturer, t.series, t.title, t.description, t.pattern ?? ''].some((x) => fold(x).includes(q))
    })
  }, [all, search, filter])

  const keys = shown.map((t) => t.id)
  const { radioProps, element } = useRadioCards({ keys, value, onChange, onActivate: onNext })
  const verifiedCount = all.filter((t) => t.verified).length

  // gespeicherte Vorlage: Filter/Suche dürfen sie nicht verstecken, dann hinscrollen und fokussieren
  const revealShown = Boolean(revealId && shown.some((t) => t.id === revealId))
  const revealListed = Boolean(revealId && all.some((t) => t.id === revealId))
  if (revealId && revealListed && !revealShown && (search || filter !== 'all')) {
    setSearch('')
    setFilter('all')
  }
  useEffect(() => {
    if (!revealId || !revealShown) return
    const cancel = focusWhenReady(() => element(revealId), { scroll: { block: 'center', behavior: 'smooth' } })
    const done = window.setTimeout(() => onRevealed?.(), 400)
    return () => {
      cancel()
      window.clearTimeout(done)
    }
  }, [revealId, revealShown, element, onRevealed])

  return (
    <section aria-labelledby="serien-vorlage" className="flex flex-col gap-5">
      <StepHeading
        id="serien-vorlage"
        title={tr("Hersteller-Serie für {v0}", { v0: categoryLabel })}
        description={
          all.length
            ? tr("{v0}, davon {v1} gegen das Datenblatt geprüft. Die Beispiele baut PartForge aus den Codetabellen und prüft sie gegen die Pflichtfelder der Kategorie.", { v0: plural(all.length, tr("Serie"), tr("Serien")), v1: verifiedCount })
            : templates.isError
              ? tr("Die Hersteller-Serien ließen sich nicht laden.")
              : templates.isPending
                ? tr("Hersteller-Serien werden geladen …")
                : tr("Für diese Kategorie gibt es noch keine Hersteller-Serie.")
        }
        actions={
          all.length > 3 ? (
            <>
              {hasCustom && (
                <SegmentedControl<Filter>
                  size="sm"
                  aria-label={tr("Vorlagen filtern")}
                  value={filter}
                  onValueChange={setFilter}
                  options={[
                    { value: 'all', label: tr("Alle") },
                    { value: 'verified', label: tc('verification', 'Geprüft') },
                    { value: 'custom', label: tr("Eigene") },
                  ]}
                />
              )}
              <Input
                size="sm"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={tr("Hersteller oder Serie …")}
                aria-label={tr("Serien durchsuchen")}
                prefix={<Search />}
                containerClassName="w-56"
              />
            </>
          ) : undefined
        }
      />

      {templates.isError && !templates.data ? (
        <LoadError
          title={tr("Hersteller-Serien nicht geladen")}
          error={templates.error}
          onRetry={() => void templates.refetch()}
          retrying={templates.isFetching}
        />
      ) : templates.isPending ? (
        <div className="grid grid-cols-1 gap-4 @[44rem]:grid-cols-2 @[66rem]:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[13.5rem] rounded-card" />
          ))}
        </div>
      ) : !all.length ? (
        <div className="rounded-panel border border-dashed border-line-strong bg-surface/50 py-6">
          <EmptyState
            illustration="forge"
            titleAs="h3"
            title={tr("Noch keine Hersteller-Serie für {v0}", { v0: categoryLabel })}
            description={tr("Eigene Vorlage anlegen: Teilenummern-Muster, Codetabellen und Baugrößen – PartForge prüft sie sofort mit Beispielwerten.")}
            actions={
              <Button variant="secondary" leftIcon={<FilePlus2 />} onClick={() => onCustomTemplate()}>
                {tr("Eigene Vorlage anlegen")}</Button>
            }
          />
        </div>
      ) : (
        <>
          <div
            role="radiogroup"
            aria-labelledby="serien-vorlage"
            className="grid grid-cols-1 gap-4 @[44rem]:grid-cols-2 @[66rem]:grid-cols-3"
          >
            {shown.map((t) => (
              <TemplateCard
                key={t.id}
                template={t}
                selected={t.id === value}
                radioProps={radioProps(t.id)}
                onEdit={t.builtin ? undefined : () => onCustomTemplate(t)}
                onDelete={t.builtin ? undefined : () => onDeleteCustom(t)}
              />
            ))}
          </div>
          {!shown.length && (
            <p className="rounded-card border border-dashed border-line px-4 py-8 text-center text-ui text-fg-muted">
              {tr("Keine Serie passt zu „")}{search}{tr("“.")}</p>
          )}
          <button
            type="button"
            onClick={() => onCustomTemplate()}
            className="group/new flex items-center gap-3 rounded-card border border-dashed border-line-strong px-4 py-3 text-left outline-none transition-colors hover:border-line-control hover:bg-surface/60 focus-ring"
          >
            <span className="flex size-8 shrink-0 items-center justify-center rounded-control border border-line bg-surface-2 text-fg-muted transition-colors group-hover/new:text-fg">
              <FilePlus2 aria-hidden className="size-4" />
            </span>
            <span className="min-w-0">
              <span className="block text-ui font-medium text-fg">{tr("Serie fehlt? Eigene Vorlage anlegen")}</span>
              <span className="block text-xs text-fg-subtle">
                {tr("Teilenummern-Muster wie")} <span className="mono">ABC{'{size}{value}{tolerance}'}</span> {tr("mit Codetabellen – sofort mit Beispielwerten testbar.")}</span>
            </span>
          </button>
        </>
      )}
    </section>
  )
}
