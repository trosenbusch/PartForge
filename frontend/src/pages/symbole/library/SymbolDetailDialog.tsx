import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Detailansicht eines Bibliothekssymbols (Leinwand mit Teilen, Verwendung mit Liste der Bauteile, Datei, Status, Pins)
 * mit „Bearbeiten“ (öffnet den Generator mit `spec.generator`) und „Neu generieren“ (gleiche Anfrage mit dem aktuellen
 * Hausstil; Probelauf zeigt Pinänderungen – erst nach Rückfrage gespeichert) – bzw. eines Symboltyps aus dem Katalog
 * („Im Generator öffnen“). „In Altium bearbeiten“ öffnet die SchLib in Altium; PartForge übernimmt das Speichern dort
 * (`@/pages/_shared/AltiumEdit`) – eine so bearbeitete Fassung ersetzen „Bearbeiten“ und „Neu generieren“ nur nach Rückfrage.
 */
import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Copy, Cpu, ExternalLink, FolderOpen, Microchip, Pencil, RefreshCw, Shapes, Square, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { ApiError, errorMessage } from '@/api/client'
import { altiumPreviousSource } from '@/api/altiumEdit'
import { useCategories } from '@/api/library'
import { usePartsUsing } from '@/api/parts'
import type { Job } from '@/api/system'
import {
  invalidateSymbolLibrary,
  symbolsApi,
  useDeleteSymbol,
  useSymbolDetail,
  useSymbolGeneratorPreview,
  type SymbolEntry,
  type SymbolKindInfo,
  type SymbolRequest,
} from '@/api/symbols'
import { SymbolCanvas, usePreviewPrefs } from '@/components/preview'
import {
  Badge,
  Button,
  Callout,
  confirm,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  KeyValueList,
  Skeleton,
  Spinner,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { baseName, formatDateTime, formatNumber, formatRelativeTime, plural } from '@/lib/format'
import { electricalLabel, partLetter, type SymbolSpec } from '@/lib/geometry'
import { revealPath } from '@/lib/native'
import { AltiumEditButton, AltiumEditStatus } from '@/pages/_shared/AltiumEdit'
import { confirmReplaceAltiumVersion } from '@/pages/_shared/altiumEditRules'
import { OverbarName } from '../shared'
import { copyText, generatorName, generatorRequest, parseUpdated, SOURCE_LABEL, STATUS_LABEL } from '../util'
import { openSpecInGenerator, pinListName, type OpenResult } from '../generator/load'
import { useGenerator } from '../store'

export type DetailTarget = { type: 'symbol'; name: string } | { type: 'kind'; kind: SymbolKindInfo }

export interface SymbolDetailDialogProps {
  target: DetailTarget | null
  onOpenChange: (open: boolean) => void
  kinds: readonly SymbolKindInfo[] | undefined
  /** Einträge der Bibliothek (freier Name beim Übernehmen als Pinliste) */
  entries: readonly SymbolEntry[] | undefined
  /** Symbol wurde in den Generator geladen */
  onEdit: (result: OpenResult) => void
  /** Fokus nach dem Schließen selbst setzen (preventDefault), sonst Standard des UI-Kits */
  onCloseAutoFocus?: (event: Event) => void
  /** Löschen läuft als Hintergrundjob (Altium geöffnet o. Ä.) */
  onJob: (job: Job) => void
}

/** Beispiel-Pinliste für die Katalog-Vorschau des IC-Typs */
const IC_EXAMPLE: SymbolRequest = {
  kind: 'ic',
  name: 'IC Beispiel',
  pins: [
    { designator: '1', name: 'VIN', electrical: 'power', part: 1, hidden: false },
    { designator: '2', name: 'GND', electrical: 'power', part: 1, hidden: false },
    { designator: '3', name: 'EN', electrical: 'input', part: 1, hidden: false },
    { designator: '4', name: 'FB', electrical: 'input', part: 1, hidden: false },
    { designator: '5', name: 'SW', electrical: 'output', part: 1, hidden: false },
    { designator: '6', name: 'PG', electrical: 'open_collector', part: 1, hidden: false },
  ],
}

function CanvasPane({ spec, loading }: { spec: SymbolSpec | null | undefined; loading?: boolean }) {
  useI18n()
  const prefs = usePreviewPrefs()
  const [part, setPart] = useState(1)
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex h-7 items-center justify-between">
        <span className="micro-label">{tr("Vorschau")}</span>
        <button
          type="button"
          aria-pressed={prefs.altium}
          onClick={() => prefs.set({ altium: !prefs.altium })}
          className={cn(
            'flex h-7 items-center gap-1.5 rounded-control px-2 text-xs font-medium text-fg-muted outline-none transition-colors focus-ring hover:bg-surface-2 hover:text-fg',
            prefs.altium && 'bg-accent-soft text-accent-text hover:bg-accent-soft hover:text-accent-text',
          )}
        >
          <Square aria-hidden className={cn('size-3.5', prefs.altium && 'fill-altium-body text-altium-line')} />
          {tr("Altium-Ansicht")}
        </button>
      </div>
      <div className="relative h-[22rem] overflow-hidden rounded-card border border-line">
        {loading && !spec ? (
          <Skeleton className="absolute inset-0 rounded-none" />
        ) : (
          <SymbolCanvas spec={spec} theme={prefs.altium ? 'altium' : 'auto'} part={part} onPartChange={setPart} className="absolute inset-0" />
        )}
      </div>
    </div>
  )
}

function PinList({ spec }: { spec: SymbolSpec }) {
  useI18n()
  const pins = spec.pins ?? []
  const multi = (spec.part_count ?? 1) > 1
  return (
    <div className="max-h-52 overflow-y-auto rounded-card border border-line">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-surface text-left text-2xs uppercase tracking-[0.06em] text-fg-subtle">
          <tr>
            <th scope="col" className="w-14 border-b border-line px-3 py-1.5 font-semibold">
              {tr("Nr.")}
            </th>
            <th scope="col" className="border-b border-line px-3 py-1.5 font-semibold">
              {tr("Name")}
            </th>
            <th scope="col" className="border-b border-line px-3 py-1.5 font-semibold">
              {tr("Typ")}
            </th>
            {multi && (
              <th scope="col" className="w-12 border-b border-line px-3 py-1.5 font-semibold">
                {tr("Teil")}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {pins.map((p, i) => (
            <tr key={`${p.designator}-${i}`} className={cn(p.hidden && 'text-fg-subtle')}>
              <td className="mono border-b border-line px-3 py-1 font-semibold text-fg">{p.designator}</td>
              <td className="mono border-b border-line px-3 py-1 text-fg">
                <OverbarName value={p.name ?? ''} placeholder="–" />
              </td>
              <td className="border-b border-line px-3 py-1 text-fg-muted">
                {electricalLabel(p.electrical)}
                {p.hidden && tr(' · verborgen')}
              </td>
              {multi && <td className="mono border-b border-line px-3 py-1 text-fg-muted">{p.part === 0 ? 'alle' : partLetter(p.part ?? 1)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Verwendung: Zahl und – aufklappbar – die Bauteile mit Sprung in die Tabelle */
function Usage({ name, count, onNavigate }: { name: string; count: number; onNavigate: () => void }) {
  useI18n()
  const [open, setOpen] = useState(false)
  const categories = useCategories()
  const usage = usePartsUsing(SYMBOL_COLUMNS, name, categories.data, open && count > 0)
  const label = new Map((categories.data ?? []).map((c) => [c.table, c.label]))
  return (
    <div className="overflow-hidden rounded-card border border-line bg-surface-2/50">
      <div className="flex items-center gap-3 px-3.5 py-3">
        <span aria-hidden className="flex size-9 items-center justify-center rounded-control border border-line bg-surface text-fg-muted">
          <Microchip className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="mono text-metric leading-none text-fg tabular-nums">{formatNumber(count)}</div>
          <div className="mt-1 text-xs text-fg-muted">{count === 1 ? tr('Bauteil verwendet das Symbol') : tr('Bauteile verwenden das Symbol')}</div>
        </div>
        {count > 0 && (
          <Button
            variant="ghost"
            size="sm"
            rightIcon={<ChevronRight className={cn('transition-transform', open && 'rotate-90')} />}
            aria-expanded={open}
            aria-controls="sym-usage-list"
            onClick={() => setOpen((o) => !o)}
          >
            {open ? tr('Ausblenden') : tr('Bauteile')}
          </Button>
        )}
      </div>
      {open && count > 0 && (
        <div id="sym-usage-list" className="max-h-44 overflow-y-auto border-t border-line px-2 py-1.5">
          {usage.isPending ? (
            <span className="flex items-center gap-2 px-1.5 py-1 text-2xs text-fg-muted">
              <Spinner size={12} /> {tr("Bauteile werden gesucht …")}
            </span>
          ) : usage.isError ? (
            <span className="px-1.5 text-2xs text-danger-text">{errorMessage(usage.error)}</span>
          ) : (usage.data ?? []).length === 0 ? (
            <span className="px-1.5 text-2xs text-fg-muted">{tr("Keine Bauteile gefunden.")}</span>
          ) : (
            <ul className="flex flex-col">
              {(usage.data ?? []).map((hit) => (
                <li key={`${hit.table}:${hit.partNumber}`}>
                  <Link
                    to={`/bauteile/${encodeURIComponent(hit.table)}?pn=${encodeURIComponent(hit.partNumber)}`}
                    onClick={onNavigate}
                    className="group/u flex items-baseline gap-2 rounded-sm px-1.5 py-1 text-2xs outline-none hover:bg-surface-3 focus-ring"
                  >
                    <span className="mono shrink-0 font-semibold text-fg group-hover/u:underline">{hit.partNumber}</span>
                    <span className="min-w-0 flex-1 truncate text-fg-subtle">
                      {label.get(hit.table) ?? hit.table}
                      {hit.description ? ` · ${hit.description}` : ''}
                    </span>
                    <ExternalLink aria-hidden className="size-3 shrink-0 self-center text-fg-subtle" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {usage.data && count > usage.data.length && (
            <p className="px-1.5 pt-1 text-2xs text-fg-subtle">
              {tr("Die ersten")}{' '}{usage.data.length} {tr("von")}{' '}{count} {tr("– alle zeigt die Bauteiltabelle mit dem Filter „Symbol“.")}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/** Spalte, über die Bauteile auf Symbole verweisen */
const SYMBOL_COLUMNS = ['Library Ref'] as const

function LibrarySymbolBody({
  name,
  kinds,
  entries,
  onEdit,
  onClose,
  onJob,
}: {
  name: string
  kinds: readonly SymbolKindInfo[] | undefined
  entries: readonly SymbolEntry[] | undefined
  onEdit: (r: OpenResult) => void
  onClose: () => void
  onJob: (job: Job) => void
}) {
  useI18n()
  const detail = useSymbolDetail(name)
  const remove = useDeleteSymbol()
  const qc = useQueryClient()
  const [rebuilding, setRebuilding] = useState(false)
  const data = detail.data ?? null
  const spec = data?.spec ?? null
  const rec = data?.record
  const kindLabel = rec?.kind ? (kinds?.find((k) => k.key === rec.kind)?.label ?? rec.kind) : tr('Eigenes Symbol (ohne Generator)')
  /** Ohne Generator-Angaben lässt sich das Symbol nur als neue IC-Pinliste übernehmen (Zeichnung bleibt) */
  const asPinList = Boolean(spec && !generatorRequest(spec))
  const status = rec ? (STATUS_LABEL[rec.status] ?? { label: rec.status, tone: 'neutral' as const }) : null
  const updated = parseUpdated(rec?.updated)

  const edit = async () => {
    if (!spec) return
    if (!asPinList && !(await confirmReplaceAltiumVersion(rec, 'edit'))) return
    const result = openSpecInGenerator(spec, kinds, { record: rec, entries })
    if (!result.ok) {
      toast.error(tr('Bearbeiten nicht möglich'), { description: tr('Das Symbol enthält weder Generator-Angaben noch Pins.') })
      return
    }
    onEdit(result)
    onClose()
  }

  /** Gespeicherte Generator-Anfrage (ohne sie lässt sich nichts neu erzeugen) */
  const request = spec ? (generatorRequest(spec) as SymbolRequest | null) : null
  const fromAltium = rec?.source === 'altium'
  // eine in Altium bearbeitete Fassung lässt sich (nach Rückfrage) wieder aus dem Generator erzeugen
  const canRebuild = Boolean(request && rec
    && (rec.source === 'generated' || (fromAltium && altiumPreviousSource(spec?.generator) === 'generated')))

  /**
   * Mit dem aktuellen Hausstil neu erzeugen – nur nach Rückfrage speichern (Pinänderungen aus dem Probelauf). Ein eigener
   * Name (`generator.name`, vom Backend beim Speichern vermerkt) geht mit der Anfrage zurück und bleibt so erhalten; ein
   * erzeugter Name folgt dem Hausstil. Kommt ein anderer Name heraus (z. B. Diodenkonvention umgestellt), nennt die
   * Rückfrage das Ziel – samt Verwendung, wenn es den Namen schon gibt: „Neu generieren“ überschreibt nie still ein
   * anderes Symbol.
   */
  const rebuild = async () => {
    if (!request || !rec || !spec || rebuilding) return
    setRebuilding(true)
    try {
      const fresh = (await symbolsApi.preview({ ...request, name: generatorName(spec) })).spec
      const category = rec.kind ? (kinds?.find((k) => k.key === rec.kind)?.categories[0] ?? null) : null
      const renamed = fresh.name.toLowerCase() !== rec.name.toLowerCase()
      // Ein neuer Name kommt in dieselbe SchLib wie das Original; vorhandene Namen bleiben ohnehin in ihrer Datei
      const known = entries?.some((e) => e.name.toLowerCase() === fresh.name.toLowerCase()) ?? true
      const library = renamed && !known ? rec.library : null
      const input = { spec: fresh, category, source: 'generated' as const, allow_pinout_change: false, library }
      const dry = await symbolsApi.save(input, { dryRun: true })
      const target = dry.library ? baseName(dry.library) : baseName(rec.library)
      if (dry.unchanged) {
        toast.info(renamed ? tr("„{value0}“ ist bereits aktuell", { value0: String(fresh.name) }) : tr("„{value0}“ ist aktuell", { value0: String(rec.name) }), {
          id: 'sym-rebuild',
          description: renamed
            ? tr("Mit dem aktuellen Hausstil heißt das Symbol „{value0}“ – das gibt es unverändert in {value1}.", { value0: String(fresh.name), value1: String(target) })
            : tr('Mit dem aktuellen Hausstil entsteht dieselbe Zeichnung – nichts zu schreiben.'),
        })
        return
      }
      /** Ersetzt der Speichervorgang ein vorhandenes Symbol (dieses oder – umbenannt – ein anderes)? */
      const replaces = !renamed || !dry.new
      const usedBy = dry.usage > 0 ? plural(dry.usage, tr('Bauteil verwendet'), tr('Bauteile verwenden')) : null
      const ok = await confirm({
        title: !renamed ? tr("„{value0}“ neu erzeugen?", { value0: String(rec.name) }) : replaces ? tr("„{value0}“ ersetzen?", { value0: String(fresh.name) }) : tr("Als „{value0}“ neu erzeugen?", { value0: String(fresh.name) }),
        description: (
          <span className="flex flex-col gap-2">
            <span className="block">
              {!renamed
                ? tr("Die Zeichnung entsteht mit dem aktuellen Hausstil neu und ersetzt „{value0}“ in {value1}.", { value0: String(rec.name), value1: String(target) })
                : replaces
                  ? tr("Neu erzeugt heißt das Symbol „{value0}“ – das gibt es schon in {value1}; seine Zeichnung wird ersetzt. „{value2}“ bleibt unverändert.", { value0: String(fresh.name), value1: String(target), value2: String(rec.name) })
                  : tr("Neu erzeugt heißt das Symbol „{value0}“. Es wird zusätzlich in {value1} gespeichert – Bauteile verweisen weiter auf „{value2}“.", { value0: String(fresh.name), value1: String(target), value2: String(rec.name) })}
            </span>
            {dry.changes.length > 0 && (
              <span className="mono block rounded-control border border-warning/30 bg-warning/8 px-2.5 py-1.5 text-xs text-warning-text">
                {dry.changes.slice(0, 6).join(' · ')}
                {dry.changes.length > 6 ? tr(" … und {value0} weitere", { value0: String(formatNumber(dry.changes.length - 6)) }) : ''}
              </span>
            )}
            {!renamed && fromAltium && (
              <span className="block font-medium text-warning-text">
                {tr('„{0}“ wurde in Altium bearbeitet – diese Fassung wird ersetzt; Änderungen, die nur dort gemacht wurden, gehen verloren.', { 0: rec.name })}
              </span>
            )}
            {replaces && usedBy && (
              <span className={cn('block', renamed && 'font-medium text-warning-text')}>
                {tr("{value0} {value1} – {value2} danach die neue Zeichnung.", { value0: String(usedBy), value1: String(renamed ? `„${fresh.name}“` : tr('das Symbol')), value2: String(dry.usage === 1 ? tr('es zeigt') : tr('sie zeigen')) })}
              </span>
            )}
          </span>
        ),
        confirmLabel: dry.needs_confirmation ? tr('Neue Belegung übernehmen') : replaces ? tr('Ersetzen') : tr('Neu speichern'),
        destructive: replaces && (dry.needs_confirmation || dry.usage > 0 || (!renamed && fromAltium)),
      })
      if (!ok) return
      const out = await symbolsApi.save({ ...input, allow_pinout_change: dry.needs_confirmation })
      invalidateSymbolLibrary(qc)
      if (out.job) {
        onJob(out.job as unknown as Job)
        return
      }
      toast.success(renamed && !replaces ? tr("„{value0}“ neu gespeichert", { value0: String(fresh.name) }) : tr("„{value0}“ neu erzeugt", { value0: String(fresh.name) }), {
        id: 'sym-rebuild',
        description: out.record ? tr("In {value0} geschrieben.", { value0: String(out.record.library) }) : undefined,
      })
    } catch (e) {
      const tip = e instanceof ApiError && e.status === 409 ? tr(' Ist die SchLib in Altium geöffnet und geändert?') : ''
      toast.error(tr('Neu erzeugen fehlgeschlagen'), { id: 'sym-rebuild', description: `${errorMessage(e)}${tip}` })
    } finally {
      setRebuilding(false)
    }
  }

  const del = async () => {
    if (!rec) return
    const ok = await confirm({
      title: tr("„{value0}“ löschen?", { value0: String(rec.name) }),
      description: tr("Das Symbol wird aus {value0} und der Registrierung entfernt.", { value0: String(baseName(rec.library)) }),
      confirmLabel: tr('Löschen'),
      destructive: true,
    })
    if (!ok) return
    try {
      const out = await remove.mutateAsync({ name: rec.name })
      if (out.job) onJob(out.job as unknown as Job)
      else toast.success(tr("„{value0}“ gelöscht", { value0: String(rec.name) }))
      onClose()
    } catch {
      // Toast zeigt die Mutation selbst
    }
  }

  let body: ReactNode
  if (detail.isLoading) {
    body = (
      <div className="grid gap-5 @[44rem]:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <CanvasPane spec={null} loading />
        <div className="space-y-3 pt-9">
          <Skeleton className="h-16" />
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      </div>
    )
  } else if (detail.error || !rec) {
    body = (
      <Callout tone="danger" title={tr("Symbol nicht geladen")}>
        {errorMessage(detail.error, tr('Das Symbol wurde nicht gefunden.'))}
      </Callout>
    )
  } else {
    body = (
      <div className="grid gap-5 @[44rem]:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-4">
          <CanvasPane spec={spec} />
          {spec && (spec.pins ?? []).length > 0 && (
            <div className="flex flex-col gap-2">
              <span className="micro-label">{tr("Pins (")}{spec.pins?.length})</span>
              <PinList spec={spec} />
            </div>
          )}
        </div>
        <div className="flex min-w-0 flex-col gap-4 @[44rem]:pt-9">
          <AltiumEditStatus kind="symbol" name={rec.name} />
          <Usage name={rec.name} count={rec.usage} onNavigate={onClose} />
          <KeyValueList
            labelWidth="7.5rem"
            items={[
              { label: tr('Typ'), value: tr(kindLabel) },
              {
                label: tr('Status'),
                value: status ? (
                  <Badge variant={status.tone === 'success' ? 'success' : status.tone === 'danger' ? 'danger' : status.tone === 'warning' ? 'warning' : 'neutral'} dot>
                    {tr(status.label)}
                  </Badge>
                ) : null,
                hint: rec.status_message ? localizeMessage(rec.status_message) : undefined,
              },
              {
                label: tr('Bibliothek'),
                value: (
                  <span className="flex items-center gap-1.5">
                    <span className="mono text-xs">{baseName(rec.library)}</span>
                    {rec.library_abs && data?.file_exists && (
                      <Tooltip content={tr("Im Explorer zeigen")}>
                        <button
                          type="button"
                          aria-label={tr("Bibliotheksdatei im Explorer zeigen")}
                          onClick={() => void revealPath(rec.library_abs as string, { what: tr('Bibliotheksdatei') })}
                          className="flex size-5 items-center justify-center rounded-sm text-fg-subtle outline-none hover:bg-surface-3 hover:text-fg focus-ring"
                        >
                          <FolderOpen aria-hidden className="size-3.5" />
                        </button>
                      </Tooltip>
                    )}
                  </span>
                ),
                copy: rec.library_abs ?? rec.library,
                hint: data?.file_exists === false ? tr('Datei fehlt') : undefined,
              },
              { label: tr('Quelle'), value: tr(SOURCE_LABEL[rec.source]) ?? rec.source },
              {
                label: tr('Geändert'),
                value: updated ? <span title={formatDateTime(updated)}>{formatRelativeTime(updated)}</span> : null,
              },
              {
                label: tr('Pins'),
                value: `${formatNumber(rec.pin_count)}${rec.part_count > 1 ? tr(" · {value0} Teile", { value0: String(formatNumber(rec.part_count)) }) : ''}`,
              },
              { label: tr('Präfix'), value: spec?.designator_prefix ?? null, mono: true },
              ...(spec?.description ? [{ label: tr('Beschreibung'), value: spec.description }] : []),
            ]}
          />
          {data && data.warnings.length > 0 && (
            <Callout tone="warning" title={plural(data.warnings.length, tr('Hinweis'), tr('Hinweise'))}>
              <ul className="list-disc space-y-0.5 pl-4">
                {data.warnings.map((w) => (
                  <li key={w}>{localizeMessage(w)}</li>
                ))}
              </ul>
            </Callout>
          )}
        </div>
      </div>
    )
  }

  const canDelete = Boolean(rec) && rec?.source !== 'external' && rec?.usage === 0
  return (
    <>
      <DialogBody className="@container">{body}</DialogBody>
      <DialogFooter className="justify-between">
        {rec && rec.source !== 'external' ? (
          <Tooltip content={canDelete ? tr('Aus Bibliothek und Registrierung entfernen') : tr("Wird von {value0} verwendet", { value0: String(plural(rec.usage, tr('Bauteil'), tr('Bauteilen'))) })}>
            <span tabIndex={canDelete ? undefined : 0} className="rounded-button outline-none focus-ring">
              <Button variant="ghost" leftIcon={<Trash2 />} disabled={!canDelete} loading={remove.isPending} onClick={() => void del()} className="text-danger-text hover:text-danger-text">
                {tr("Löschen")}
              </Button>
            </span>
          </Tooltip>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          <IconButtonCopy disabled={!rec} onClick={() => rec && void copyText(rec.name, tr('Symbolname'))} />
          <AltiumEditButton kind="symbol" rec={rec} fileExists={data?.file_exists} />
          {canRebuild && (
            <Tooltip content={tr("Mit dem aktuellen Hausstil neu erzeugen – ändert sich etwas, fragt PartForge vor dem Speichern (inkl. Pinbelegung).")}>
              <Button variant="secondary" leftIcon={<RefreshCw />} loading={rebuilding} onClick={() => void rebuild()}>
                {tr("Neu generieren")}
              </Button>
            </Tooltip>
          )}
          {asPinList && spec ? (
            <Tooltip content={tr("Pins als neue IC-Pinliste „{value0}“ übernehmen – die Zeichnung von „{value1}“ bleibt unverändert.", { value0: String(pinListName(spec.name, entries)), value1: String(spec.name) })}>
              <Button variant="primary" leftIcon={<Cpu />} disabled={rec?.source === 'external'} onClick={() => void edit()}>
                {tr("Als IC-Pinliste übernehmen")}
              </Button>
            </Tooltip>
          ) : (
            <Button variant="primary" leftIcon={<Pencil />} disabled={!spec || rec?.source === 'external'} onClick={() => void edit()}>
              {tr("Bearbeiten")}
            </Button>
          )}
        </div>
      </DialogFooter>
    </>
  )
}

function KindBody({ kind, onEdit, onClose }: { kind: SymbolKindInfo; onEdit: (r: OpenResult) => void; onClose: () => void }) {
  useI18n()
  const preview = useSymbolGeneratorPreview(kind.key === 'ic' ? IC_EXAMPLE : { kind: kind.key })
  const spec = preview.data?.spec
  return (
    <>
      <DialogBody className="@container">
        <div className="grid gap-5 @[44rem]:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <CanvasPane spec={spec} loading={preview.isLoading} />
          <div className="flex min-w-0 flex-col gap-4 @[44rem]:pt-9">
            {kind.description && <p className="text-ui leading-relaxed text-fg-muted">{tr(kind.description)}</p>}
            <KeyValueList
              labelWidth="7.5rem"
              items={[
                { label: tr('Gruppe'), value: kind.group },
                { label: tr('Name'), value: spec?.name ?? kind.default_name, mono: true },
                { label: tr('Präfix'), value: kind.prefix, mono: true },
                { label: tr('Parameter'), value: kind.params.length ? kind.params.map((p) => tr(p.label)).join(', ') : tr('keine') },
              ]}
            />
            {preview.error && (
              <Callout tone="danger" title={tr("Vorschau nicht möglich")}>
                {errorMessage(preview.error)}
              </Callout>
            )}
          </div>
        </div>
      </DialogBody>
      <DialogFooter>
        <Button
          variant="primary"
          leftIcon={<Pencil />}
          onClick={() => {
            useGenerator.getState().setKind(kind.key)
            onEdit({ ok: true, kind: kind.key })
            onClose()
          }}
        >
          {tr("Im Generator öffnen")}
        </Button>
      </DialogFooter>
    </>
  )
}

/** „Name kopieren“ als Symbolknopf mit Tooltip (spart Platz in der Fußzeile) */
function IconButtonCopy({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  useI18n()
  return (
    <Tooltip content={tr("Symbolnamen kopieren")}>
      <Button variant="ghost" iconOnly aria-label={tr("Symbolnamen kopieren")} disabled={disabled} onClick={onClick}>
        <Copy />
      </Button>
    </Tooltip>
  )
}

export function SymbolDetailDialog({ target, onOpenChange, kinds, entries, onEdit, onCloseAutoFocus, onJob }: SymbolDetailDialogProps) {
  useI18n()
  // letzten Inhalt während der Schließen-Animation behalten
  const [shown, setShown] = useState<DetailTarget | null>(target)
  if (target && target !== shown) setShown(target)
  const close = () => onOpenChange(false)
  const title = shown?.type === 'symbol' ? shown.name : shown?.type === 'kind' ? tr(shown.kind.label) : ''
  // Doppelklick auf eine Karte: Der erste Klick öffnet den Dialog, der zweite trifft schon seinen Inhalt – er soll dort
  // keinen Text markieren
  const openedAt = useRef(0)
  useEffect(() => {
    if (target) openedAt.current = performance.now()
  }, [target])
  return (
    <Dialog open={target !== null} onOpenChange={onOpenChange}>
      <DialogContent
        size="xl"
        onCloseAutoFocus={onCloseAutoFocus}
        onMouseDown={(e) => {
          if (e.detail > 1 && performance.now() - openedAt.current < 700) e.preventDefault()
        }}
      >
        <DialogHeader
          icon={shown?.type === 'kind' ? <Shapes /> : <Microchip />}
          title={<span className={cn(shown?.type === 'symbol' && 'mono')}>{title}</span>}
          description={shown?.type === 'kind' ? tr("Symboltyp aus dem Katalog · {value0}", { value0: String(shown.kind.default_name) }) : undefined}
        />
        {shown?.type === 'symbol' && (
          <LibrarySymbolBody key={shown.name} name={shown.name} kinds={kinds} entries={entries} onEdit={onEdit} onClose={close} onJob={onJob} />
        )}
        {shown?.type === 'kind' && <KindBody key={shown.kind.key} kind={shown.kind} onEdit={onEdit} onClose={close} />}
      </DialogContent>
    </Dialog>
  )
}
