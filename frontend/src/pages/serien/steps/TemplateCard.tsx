import { localizeMessage, t as tr, useI18n } from '@/lib/i18n'
/**
 * Karte einer Hersteller-Serie: Hersteller, Serie, Bauart, Beispiel-Teilenummer mit Aufbau und Kennwerte – alles aus
 * der Vorlagenliste (`TemplateSummary.example`, `mode`, `value_range`, `e_series`, `jumper`, `sources`), ohne eigene
 * Anfragen je Karte. Warnungen (ungeprüft, Lieferbarkeit offen) stehen als Plaketten am Titel – der Normalfall
 * „geprüft“ ist ein ruhiges Schild in der Fußzeile, dessen Tooltip die Quellen nennt (eigener Tabstopp, auch per
 * Tastatur). Würde die Serie das Beispiel nicht anlegen (Pflichtfeld der Kategorie leer …), sagt die Karte warum.
 * Die Karte ist eine Option der Radiogruppe; Prüfvermerk, Datenblatt-Link und Menü liegen außerhalb der Option.
 */
import { Check, ExternalLink, MoreHorizontal, Pencil, ShieldAlert, ShieldCheck, Trash2, TriangleAlert } from 'lucide-react'
import { Fragment, useId, type ComponentProps } from 'react'
import type { SeriesTemplateSummary, TemplateSource } from '@/api/series'
import {
  Badge,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  IconButton,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber, plural } from '@/lib/format'
import { MpnAnatomy } from '../components/MpnAnatomy'
import { displayValue } from '../model/values'

type RadioProps = ComponentProps<'button'> & { ref?: (el: HTMLElement | null) => void }

export interface TemplateCardProps {
  template: SeriesTemplateSummary
  selected: boolean
  radioProps: RadioProps
  onEdit?: () => void
  onDelete?: () => void
}

function sourceLine(s: TemplateSource): string {
  return [s.title, s.document, s.revision ? tr("Stand {v0}", { v0: s.revision }) : null, s.pages ? tr("S. {v0}", { v0: s.pages }) : null]
    .filter(Boolean)
    .join(' · ')
}

function productType(t: SeriesTemplateSummary): string {
  const title = t.builtin ? tr(t.title) : t.title
  const parts = title.split(' – ')
  return parts.length > 1 ? parts.slice(1).join(' – ') : title
}

const NOT_VERIFIED = 'Nicht gegen das Datenblatt geprüft – Werte vor der Freigabe kontrollieren.'
const AVAILABILITY_OPEN =
  'Lieferbarkeit der einzelnen Typen nicht geprüft – Teilenummern beim Hersteller oder Distributor prüfen.'

/** Kennwerte der Fußzeile: Bauformen, E-Reihen, Wertebereich, lieferbare Typen bzw. Katalog, Brücke */
function templateFacts(t: SeriesTemplateSummary): string[] {
  const facts: string[] = []
  if (t.sizes.length) {
    facts.push(
      t.sizes.length > 1
        ? `${plural(t.sizes.length, tr("Bauform"), tr("Bauformen"))} ${t.sizes[0]} … ${t.sizes[t.sizes.length - 1]}`
        : t.sizes[0],
    )
  }
  if (t.mode === 'rules' && t.e_series.length) facts.push(t.e_series.join(' / '))
  const range = t.value_range
  if (range && range.length === 2) facts.push(`${displayValue(range[0], t.value_unit)} … ${displayValue(range[1], t.value_unit)}`)
  if (t.mode === 'matrix' && t.availability_count) facts.push(tr("{v0} lieferbare Typen", { v0: formatNumber(t.availability_count) }))
  if (t.mode === 'catalog' && t.part_count) facts.push(tr("Katalog · {v0}", { v0: plural(t.part_count, tr("Typ"), tr("Typen")) }))
  if (t.jumper) facts.push(tr('0‑Ω‑Brücke'))
  return facts
}

export function TemplateCard({ template: t, selected, radioProps, onEdit, onDelete }: TemplateCardProps) {
  const { t: tr } = useI18n()
  const id = useId()
  const sources = t.sources
  const facts = templateFacts(t)

  const verification = t.verified
    ? tr("Gegen das Datenblatt geprüft{v0}.", { v0: sources.length ? `: ${sources.map(sourceLine).join('; ')}` : '' })
    : tr(NOT_VERIFIED)
  const availability = t.availability_certain ? '' : ` ${tr(AVAILABILITY_OPEN)}`
  const ex = t.example
  const exampleText = ex ? tr(" Beispiel: {v0}{v1}.", { v0: ex.mpn, v1: ex.valid ? '' : tr(" – ungültig: {v0}", { v0: localizeMessage(ex.message ?? '') }) }) : ''

  return (
    <div
      className={cn(
        'group/card relative flex flex-col rounded-card border bg-surface shadow-card transition-[border-color,box-shadow,transform] duration-200',
        'hover:-translate-y-px hover:shadow-raised',
        selected
          ? 'border-accent/60 shadow-[0_0_0_3px_var(--pf-accent-soft),var(--pf-shadow-raised)]'
          : 'border-line hover:border-line-strong',
      )}
    >
      <button
        type="button"
        {...radioProps}
        // Name = Hersteller + Serie („Vishay D/CRCW e3“) – der Seriencode allein ist mehrdeutig (CR, RC_L …)
        aria-labelledby={`${id}-maker ${id}-title`}
        aria-describedby={`${id}-desc`}
        className="flex flex-1 flex-col gap-3 rounded-t-card px-4 pb-3.5 pt-3.5 text-left outline-none focus-ring"
      >
        <span className="flex w-full items-start gap-3">
          <span className="min-w-0 flex-1">
            <span id={`${id}-maker`} className="micro-label block truncate">
              {t.manufacturer}
            </span>
            <span id={`${id}-title`} className="mt-0.5 block truncate text-md font-semibold tracking-[-0.01em] text-fg">
              {t.series}
            </span>
            {/* zwei Zeilen reserviert: Beispiele der Karten einer Reihe stehen auf gleicher Höhe */}
            <span className="mt-0.5 line-clamp-2 min-h-[2lh] text-xs leading-snug text-fg-muted">{productType(t)}</span>
          </span>
          {selected ? (
            <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-gradient-forge text-on-accent shadow-glow">
              <Check aria-hidden className="size-3.5" strokeWidth={2.5} />
            </span>
          ) : (
            <span aria-hidden className="size-5 shrink-0 rounded-full border border-line-strong bg-surface-2" />
          )}
        </span>

        {(!t.verified || !t.availability_certain || !t.builtin) && (
          <span aria-hidden className="-mt-1 flex flex-wrap items-center gap-1">
            {!t.verified && (
              <Badge variant="warning">
                <ShieldAlert />
                {tr("Ungeprüft")}</Badge>
            )}
            {!t.availability_certain && (
              <Badge variant="warning">
                <TriangleAlert />
                {tr("Lieferbarkeit offen")}</Badge>
            )}
            {!t.builtin && <Badge variant="outline">{tr("Eigene Vorlage")}</Badge>}
          </span>
        )}

        <span
          className={cn(
            'flex min-h-[3.75rem] flex-col justify-center gap-1.5 rounded-control border px-3 py-2',
            ex && !ex.valid ? 'border-warning/35 bg-warning/5' : 'border-line bg-surface-2/55',
          )}
        >
          <span className="micro-label">
            {tr("Beispiel")}{ex?.size ? ` · ${ex.size}` : ''}
            {ex && !ex.valid ? <span className="text-warning-text"> {tr("· ungültig")}</span> : null}
          </span>
          {ex ? (
            <>
              <MpnAnatomy mpn={ex.mpn} segments={ex.segments.length > 1 ? ex.segments : null} labels="short" size="sm" />
              {!ex.valid && ex.message && (
                <span className="flex items-start gap-1.5 text-2xs leading-snug text-warning-text">
                  <TriangleAlert aria-hidden className="mt-px size-3 shrink-0" />
                  {localizeMessage(ex.message)}
                </span>
              )}
            </>
          ) : (
            <span className="mono truncate text-ui text-fg-muted">{t.pattern ?? tr("Katalog mit festen Teilenummern")}</span>
          )}
        </span>
        <span id={`${id}-desc`} className="sr-only">
          {`${t.builtin ? tr(t.title) : t.title}. ${verification}${availability} ${facts.join(', ')}.${exampleText}`}
        </span>
      </button>

      <div className="flex min-h-10 items-center gap-1 border-t border-line py-1 pl-1.5 pr-1.5">
        <Tooltip
          side="bottom"
          align="start"
          content={
            t.verified ? (
              <span className="flex flex-col gap-1">
                <span className="font-medium">{tr("Gegen das Datenblatt geprüft")}</span>
                {sources.length ? (
                  sources.map((src) => (
                    <span key={src.title} className="text-fg-muted">
                      {sourceLine(src)}
                    </span>
                  ))
                ) : (
                  <span className="text-fg-muted">{tr("Quelle in der Vorlage nicht angegeben.")}</span>
                )}
                {!t.availability_certain && <span className="text-warning-text">{tr(AVAILABILITY_OPEN)}</span>}
              </span>
            ) : (
              <span className="flex flex-col gap-1">
                <span className="font-medium">{tr(NOT_VERIFIED)}</span>
                {!t.availability_certain && <span className="text-fg-muted">{tr(AVAILABILITY_OPEN)}</span>}
              </span>
            )
          }
        >
          <button
            type="button"
            aria-label={tr("Prüfstatus von {v0}: {v1}", { v0: t.builtin ? tr(t.title) : t.title, v1: t.verified ? tr("gegen das Datenblatt geprüft") : tr("ungeprüft") })}
            className={cn(
              'flex size-7 shrink-0 items-center justify-center rounded-control outline-none transition-colors hover:bg-surface-2 focus-ring [&_svg]:size-4',
              t.verified ? 'text-success' : 'text-warning',
            )}
          >
            {t.verified ? <ShieldCheck aria-hidden /> : <ShieldAlert aria-hidden />}
          </button>
        </Tooltip>
        <span aria-hidden className="min-w-0 flex-1 py-1 pl-0.5 text-2xs leading-relaxed text-fg-subtle">
          {facts.map((f, i) => (
            <Fragment key={f}>
              {/* Trenner am Zeilenende statt am Anfang der nächsten Zeile */}
              <span className="whitespace-nowrap">
                {f}
                {i < facts.length - 1 && <span className="ml-1.5">·</span>}
              </span>{' '}
            </Fragment>
          ))}
        </span>
        {t.datasheet_url && (
          <Tooltip content={tr('Datenblatt öffnen')}>
            <a
              href={t.datasheet_url}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={tr("Datenblatt von {v0} (öffnet extern)", { v0: t.builtin ? tr(t.title) : t.title })}
              className="flex size-7 shrink-0 items-center justify-center rounded-control text-fg-muted outline-none transition-colors hover:bg-surface-2 hover:text-fg focus-ring"
            >
              <ExternalLink aria-hidden className="size-3.5" />
            </a>
          </Tooltip>
        )}
        {(onEdit || onDelete) && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <IconButton size="sm" variant="ghost" label={tr("Aktionen für {v0}", { v0: t.builtin ? tr(t.title) : t.title })} icon={<MoreHorizontal />} tooltip={false} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {onEdit && (
                <DropdownMenuItem icon={<Pencil />} onSelect={onEdit}>
                  {tr("Bearbeiten")}</DropdownMenuItem>
              )}
              {onEdit && onDelete && <DropdownMenuSeparator />}
              {onDelete && (
                <DropdownMenuItem icon={<Trash2 />} destructive onSelect={onDelete}>
                  {tr("Löschen …")}</DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
    </div>
  )
}
