import { useLocalizedMemo } from '@/components/preview/useLocalizedMemo'
import { localizeMessage, t as tr, useI18n } from '@/components/preview/i18n'
/**
 * Detail eines gespeicherten Footprints: Vorschau (Footprint/3D), Kennwerte, Bibliotheksdatei, Status, Verwendung
 * (Liste der Bauteile mit Links), 3D-Modell – „Bearbeiten“ (Generator mit den gespeicherten Parametern),
 * „Neu generieren“ (Vorlagen-Footprints mit dem aktuellen Hausstil neu berechnen und – nach Rückfrage – ersetzen),
 * „In Altium bearbeiten“ (Bibliothek in Altium öffnen; PartForge übernimmt das Speichern dort, `@/pages/_shared/AltiumEdit`),
 * STEP und Löschen. Der Fokus startet auf der Hauptaktion. Eine in Altium bearbeitete Fassung (`source = 'altium'`)
 * ersetzen „Bearbeiten“ und „Neu generieren“ nur nach Rückfrage.
 *
 * Eigene Namen (z. B. „MY_SOIC8“ statt „SOIC127P600X175-8N“) bleiben bei „Neu generieren“ und „Bearbeiten“ erhalten:
 * Das Backend vermerkt einen eigenen Namen beim Speichern in `spec.generator.name` (nur dann – erzeugte Namen stehen in
 * `generator.names`); er geht als `FootprintRequest.name` zurück an den Generator. Sonst entstünde der Footprint unter
 * dem Vorlagennamen und ersetzte still einen anderen. Ein erzeugter Name folgt dagegen dem Namensschema des Hausstils:
 * Ändert er sich (Schema umgestellt), nennt die Rückfrage das Ziel – samt Verwendung, wenn es den Namen schon gibt.
 */
import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Download, ExternalLink, FolderOpen, PencilRuler, RefreshCw, Trash2, TriangleAlert } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { toast } from 'sonner'
import { ApiError, errorMessage } from '@/api/client'
import {
  footprintKeys,
  footprintsApi,
  useDeleteFootprint,
  useLibraryFootprint,
  type FootprintFamily,
  type LibraryFootprintDetail,
} from '@/api/footprints'
import { altiumPreviousSource } from '@/api/altiumEdit'
import { trackJob } from '@/api/jobs'
import { useCategories } from '@/api/library'
import { usePartsUsing } from '@/api/parts'
import type { Job } from '@/api/system'
import { PreviewPanel } from '@/components/preview'
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
  EmptyState,
  IconButton,
  KeyValueList,
  PathText,
  Skeleton,
  Spinner,
  Tooltip,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { FILE_TYPES, notifySaveResult, saveFile } from '@/lib/download'
import { baseName, formatDateTime, formatNumber, formatRelativeTime, plural } from '@/lib/format'
import type { FootprintRequest } from '@/lib/geometry'
import { revealPath } from '@/lib/native'
import { AltiumEditButton, AltiumEditStatus } from '@/pages/_shared/AltiumEdit'
import { confirmReplaceAltiumVersion } from '@/pages/_shared/altiumEditRules'
import { densityLabel } from '../lib/calc'
import { closestPreset, familyShortLabel } from '../lib/families'
import { formatDim, normalizeParams } from '../lib/params'
import { PackageGlyph } from '../PackageGlyph'
import { SOURCE_LABEL, statusMeta } from './meta'

/** Spalten, über die Bauteile auf Footprints verweisen */
const FOOTPRINT_COLUMNS = ['Footprint Ref', 'Footprint Ref 2', 'Footprint Ref 3'] as const

/** Gespeicherte Parameter im Generator öffnen; `name` = eigener Name des Footprints (bleibt beim Speichern erhalten) */
export type RegenerateHandler = (family: FootprintFamily, generator: Record<string, unknown>, opts: { name: string | null }) => void

export interface FootprintDetailDialogProps {
  name: string | null
  families: FootprintFamily[]
  onClose: () => void
  onRegenerate: RegenerateHandler
}

/**
 * Eigener Name des gespeicherten Footprints („MY_SOIC8“) aus `spec.generator.name` – das Backend setzt ihn beim
 * Speichern nur für Namen, die weder IPC- noch Hausname der Parameter sind (`with_name_record`); `null` = erzeugter Name.
 */
function customName(generator: Record<string, unknown> | null): string | null {
  const name = generator?.name
  return typeof name === 'string' && name.trim() ? name : null
}

const sameName = (a: string, b: string) => a.toLowerCase() === b.toLowerCase()

export function FootprintDetailDialog({ name, families, onClose, onRegenerate }: FootprintDetailDialogProps) {
  useI18n()
  // Inhalt beim Schließen stehen lassen (Ausblende-Animation)
  const [shownName, setShownName] = useState(name)
  if (name && name !== shownName) setShownName(name)
  // Nur bei offenem Dialog abfragen – nach dem Schließen (z. B. Löschen) kein erneutes Holen
  const detail = useLibraryFootprint(shownName, Boolean(name))
  // Doppelklick auf eine Karte: Der erste Klick öffnet den Dialog, der zweite trifft schon seinen Inhalt – er soll dort
  // keinen Text markieren
  const openedAt = useRef(0)
  useEffect(() => {
    if (name) openedAt.current = performance.now()
  }, [name])
  return (
    <Dialog open={Boolean(name)} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        size="xl"
        centered
        className="h-[min(760px,calc(100dvh-3rem))]"
        onMouseDown={(e) => {
          if (e.detail > 1 && performance.now() - openedAt.current < 700) e.preventDefault()
        }}
        onOpenAutoFocus={(e) => {
          // Fokus auf die Hauptaktion statt auf „Schließen“ (lädt sie noch: auf den Dialog selbst)
          const root = e.currentTarget as HTMLElement | null
          const target = root?.querySelector<HTMLElement>('[data-autofocus]') ?? root
          if (target) {
            e.preventDefault()
            target.focus()
          }
        }}
      >
        {detail.data ? (
          <DetailContent detail={detail.data} families={families} onRegenerate={onRegenerate} onDeleted={onClose} />
        ) : detail.isError ? (
          <>
            <DialogHeader icon={<TriangleAlert />} tone="danger" title={shownName ?? 'Footprint'} />
            <DialogBody>
              <Callout tone="danger" title={tr("Footprint konnte nicht geladen werden")}>
                {errorMessage(detail.error)}
              </Callout>
            </DialogBody>
          </>
        ) : (
          <>
            <DialogHeader icon={<PackageGlyph family={null} />} title={shownName ?? 'Footprint'} description={tr("Wird geladen …")} />
            <DialogBody className="grid grid-cols-[minmax(0,1fr)_17rem] gap-5">
              <Skeleton className="h-full min-h-80 rounded-card" />
              <div className="flex flex-col gap-3">
                {Array.from({ length: 8 }, (_, i) => (
                  <Skeleton key={i} className="h-4" />
                ))}
              </div>
            </DialogBody>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}

function DetailContent({
  detail,
  families,
  onRegenerate,
  onDeleted,
}: {
  detail: LibraryFootprintDetail
  families: FootprintFamily[]
  onRegenerate: RegenerateHandler
  onDeleted: () => void
}) {
  useI18n()
  const qc = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [rebuilding, setRebuilding] = useState(false)
  const [showUsage, setShowUsage] = useState(false)
  const primaryRef = useRef<HTMLButtonElement>(null)
  const remove = useDeleteFootprint()
  const rec = detail.record
  const spec = detail.spec
  const family = families.find((f) => f.key === (spec?.generator?.family ?? rec.family)) ?? null
  const generator = spec?.generator && typeof spec.generator === 'object' ? (spec.generator as Record<string, unknown>) : null
  const meta = statusMeta(rec.status)
  const canRegenerate = Boolean(family && generator && generator.params)
  // An imported model need not be extracted yet: the download reads it from the source library.
  const hasStep = Boolean(detail.step?.exists || (detail.bodies ?? []).length
    || (detail.step && (rec.source === 'imported' || rec.source === 'external' || rec.source === 'altium')))
  const fromAltium = rec.source === 'altium'
  const external = rec.source === 'external'

  const categories = useCategories()
  const usage = usePartsUsing(FOOTPRINT_COLUMNS, rec.name, categories.data, showUsage && rec.usage > 0)
  const categoryLabel = new Map((categories.data ?? []).map((c) => [c.table, c.label]))
  // „Neu generieren“: nur für Vorlagen mit Standardmaßen (der Name hängt dann nur an Vorlage und Hausstil) – die
  // Vorlage steht im Spec oder ergibt sich aus den Selektoren der gespeicherten Parameter (wie im Generator)
  const presetKey = useLocalizedMemo(() => {
    if (!family || generator?.standard !== true) return null
    if (typeof generator.preset === 'string') return generator.preset
    const params = generator.params && typeof generator.params === 'object' ? (generator.params as Record<string, unknown>) : {}
    return closestPreset(family, normalizeParams(family.params, params))?.key ?? null
  }, [family, generator])
  // eine in Altium bearbeitete Vorlage lässt sich (nach Rückfrage) wieder aus dem Generator erzeugen
  const canRebuild = Boolean(family && presetKey
    && (rec.source === 'generated' || (fromAltium && altiumPreviousSource(generator) === 'generated')))

  // Daten kamen nach dem Öffnen: Fokus vom Dialog auf die Hauptaktion setzen
  useEffect(() => {
    const root = primaryRef.current?.closest('[role="dialog"]')
    if (root && document.activeElement === root) primaryRef.current?.focus()
  }, [])

  const step = async () => {
    setBusy(true)
    try {
      const result = await saveFile({
        suggestedName: detail.step?.file ? baseName(detail.step.file) : `${rec.name}.step`,
        load: () => footprintsApi.libraryStep(rec.name),
        type: FILE_TYPES.step,
      })
      notifySaveResult(result, { what: tr('STEP-Modell'), id: 'fp-file' })
    } catch (e) {
      toast.error(tr('STEP-Modell nicht verfügbar'), { id: 'fp-file', description: errorMessage(e) })
    } finally {
      setBusy(false)
    }
  }

  const storedDensity = generator?.density === 'L' || generator?.density === 'M' ? generator.density : 'N'

  /**
   * Vorlage mit dem aktuellen Hausstil neu berechnen; ändert sich etwas, nach Rückfrage speichern. Ein eigener Name
   * (`generator.name`) geht als `name` mit und bleibt so erhalten. Wechselt ein erzeugter Name (anderes Namensschema im
   * Hausstil), nennt die Rückfrage das Ziel: neu in der Bibliothek – oder ein vorhandener Footprint, der ersetzt wird.
   */
  const rebuild = async () => {
    if (!family || !presetKey || rebuilding) return
    setRebuilding(true)
    try {
      const request: FootprintRequest = {
        family: family.key,
        params: { preset: presetKey },
        density: storedDensity,
        with_3d: true,
        name: customName(generator),
      }
      const preview = await footprintsApi.preview(request)
      const errors = preview.issues.filter((i) => i.severity === 'error')
      if (errors.length) {
        toast.error(tr('Neu berechnen nicht möglich'), { id: 'fp-rebuild', description: localizeMessage(errors[0].message) })
        return
      }
      const fresh = preview.spec
      const dry = await footprintsApi.save(fresh, { dryRun: true })
      const renamed = !sameName(fresh.name, rec.name)
      const target = dry.library ? baseName(dry.library) : tr('der Bibliothek')
      const sameGeometry = fresh.generator?.geometry_hash === generator?.geometry_hash && rec.status === 'ok'
      if (!renamed && (dry.unchanged || sameGeometry)) {
        toast.info(tr("„{value0}“ ist aktuell", { value0: String(rec.name) }), { id: 'fp-rebuild', description: tr('Mit dem aktuellen Hausstil entsteht dieselbe Geometrie – nichts zu schreiben.') })
        return
      }
      if (renamed && dry.unchanged) {
        toast.info(tr("„{value0}“ ist bereits aktuell", { value0: String(fresh.name) }), {
          id: 'fp-rebuild',
          description: tr("Mit dem aktuellen Hausstil heißt der Footprint „{value0}“ – den gibt es unverändert in {value1}. Bauteile verweisen weiter auf „{value2}“.", { value0: String(fresh.name), value1: String(target), value2: String(rec.name) }),
        })
        return
      }
      const usedBy = dry.usage ? plural(dry.usage, tr('Bauteil verwendet'), tr('Bauteile verwenden')) : null
      const altiumNote = fromAltium ? (
        <span className="block font-medium text-warning-text">
          {tr('„{0}“ wurde in Altium bearbeitet – diese Fassung wird ersetzt; Änderungen, die nur dort gemacht wurden, gehen verloren.', { 0: rec.name })}
        </span>
      ) : null
      const ok = !renamed
        ? await confirm({
            title: tr("„{value0}“ neu erzeugen?", { value0: String(rec.name) }),
            description: (
              <span className="flex flex-col gap-2">
                <span className="block">
                  {tr("Die Geometrie wird mit dem aktuellen Hausstil neu berechnet und ersetzt den Footprint in {value0}{value1}", { value0: String(target), value1: String(usedBy ? tr(" – {value0} ihn.", { value0: String(usedBy) }) : '.') })}
                </span>
                {altiumNote}
              </span>
            ),
            confirmLabel: tr('Ersetzen'),
            destructive: dry.usage > 0 || fromAltium,
          })
        : !dry.new
          ? await confirm({
              // Den neuen Namen gibt es schon: dieser andere Footprint wird ersetzt – das Original bleibt
              title: tr("„{value0}“ ersetzen?", { value0: String(fresh.name) }),
              description: (
                <span className="flex flex-col gap-2">
                  <span className="block">
                    {tr("Mit dem aktuellen Hausstil heißt der Footprint „")}<span className="mono text-fg">{fresh.name}</span>{tr("“. Diesen Footprint gibt es schon in")}{' '}{target} {tr("– seine Geometrie wird ersetzt.")}
                  </span>
                  <span className={cn('block', dry.usage > 0 && 'font-medium text-warning-text')}>
                    {usedBy
                      ? tr("{value0} „{value1}“ – {value2} die neue Geometrie.", { value0: String(usedBy), value1: String(fresh.name), value2: String(dry.usage === 1 ? tr('es bekommt') : tr('sie bekommen')) })
                      : tr("Noch verwendet kein Bauteil „{value0}“.", { value0: String(fresh.name) })}
                  </span>
                  <span className="block">„{rec.name}{tr("“ bleibt unverändert; seine Bauteile verweisen weiter darauf.")}</span>
                </span>
              ),
              confirmLabel: tr('Ersetzen'),
              destructive: dry.usage > 0,
            })
          : await confirm({
              title: tr("Als „{value0}“ neu erzeugen?", { value0: String(fresh.name) }),
              description: tr("Mit dem aktuellen Hausstil heißt der Footprint „{value0}“. Er wird zusätzlich in {value1} gespeichert – Bauteile verweisen weiter auf „{value2}“.", { value0: String(fresh.name), value1: String(target), value2: String(rec.name) }),
              confirmLabel: tr('Neu speichern'),
            })
      if (!ok) return
      const out = await footprintsApi.save(fresh)
      void qc.invalidateQueries({ queryKey: footprintKeys.library, predicate: (q) => q.queryKey[2] !== 'thumb' })
      void qc.invalidateQueries({ queryKey: ['parts', 'library'] })
      if (out.job) {
        trackJob(out.job as unknown as Job, { openDock: false })
        return
      }
      toast.success(renamed && dry.new ? tr("„{value0}“ neu gespeichert", { value0: String(fresh.name) }) : tr("„{value0}“ neu erzeugt", { value0: String(fresh.name) }), {
        id: 'fp-rebuild',
        description: out.record ? tr("In {value0} geschrieben.", { value0: String(out.record.library) }) : undefined,
      })
    } catch (e) {
      const tip = e instanceof ApiError && e.status === 409 ? tr(' Ist die PcbLib in Altium geöffnet und geändert?') : ''
      toast.error(tr('Neu erzeugen fehlgeschlagen'), { id: 'fp-rebuild', description: `${errorMessage(e)}${tip}` })
    } finally {
      setRebuilding(false)
    }
  }

  /**
   * Im Generator öffnen: die gespeicherten Parameter – und ein eigener Name (`generator.name`), damit „Speichern“ diesen
   * Footprint aktualisiert statt unter dem erzeugten Namen einen anderen zu ersetzen.
   */
  const edit = async () => {
    if (!family || !generator) return
    if (!(await confirmReplaceAltiumVersion(rec, 'edit'))) return
    onRegenerate(family, generator, { name: customName(generator) })
  }

  const del = async () => {
    const used = rec.usage
    const ok = await confirm({
      title: tr("„{value0}“ löschen?", { value0: String(rec.name) }),
      description: external
        ? tr('Der Footprint gehört zu einer externen Bibliothek: PartForge vergisst ihn nur, die Datei bleibt unverändert.')
        : used
          ? tr("Er wird von {value0} verwendet – deren Verweis zeigt danach ins Leere. Der Footprint wird aus {value1} entfernt.", { value0: String(plural(used, tr('Bauteil'), tr('Bauteilen'))), value1: String(baseName(rec.library)) })
          : tr("Der Footprint wird aus {value0} entfernt.", { value0: String(baseName(rec.library)) }),
      confirmLabel: used ? tr('Trotzdem löschen') : tr('Löschen'),
      destructive: true,
    })
    if (!ok) return
    try {
      const out = await remove.mutateAsync({ name: rec.name, force: used > 0 })
      if (out.job) {
        // Läuft im Hintergrund: Fortschritt und Ergebnis meldet das Job-Dock – der Dialog schließt
        trackJob(out.job as unknown as Job, { openDock: false })
        onDeleted()
        return
      }
      const result = out.result
      const refused = result ? Object.values(result.refused)[0] : undefined
      if (refused) {
        toast.error(tr('Nicht gelöscht'), { description: refused })
        return
      }
      toast.success(tr("„{value0}“ gelöscht", { value0: String(rec.name) }), {
        description: result?.unregistered.length ? tr('Nur aus PartForge entfernt (externe Bibliothek).') : baseName(rec.library),
      })
      onDeleted()
    } catch (e) {
      toast.error(tr('Löschen fehlgeschlagen'), { description: errorMessage(e) })
    }
  }

  const density = spec?.density ?? (typeof generator?.density === 'string' ? generator.density : null)

  return (
    <>
      <DialogHeader
        icon={<PackageGlyph family={family?.key ?? rec.family} />}
        title={<span className="mono break-all">{rec.name}</span>}
        description={
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>{family ? familyShortLabel(family) : (rec.family ?? 'Footprint')}</span>
            <span aria-hidden>·</span>
            <span className="mono text-xs">{baseName(rec.library)}</span>
            <Badge variant={meta.variant} dot size="sm">
              {tr(meta.label)}
            </Badge>
          </span>
        }
      />
      <DialogBody className="grid min-h-0 grid-cols-[minmax(0,1fr)_17.5rem] gap-5 overflow-hidden">
        {spec || rec.source === 'imported' || rec.source === 'external' || fromAltium ? (
          <PreviewPanel footprint={spec} stepSource={{ name: rec.name, revision: rec.content_hash ?? rec.updated }}
            hideEmptyTabs defaultTab={spec ? 'footprint' : '3d'} title={rec.name} className="h-full min-h-[22rem]" />
        ) : (
          <div className="flex items-center justify-center rounded-card border border-line bg-surface">
            <EmptyState
              icon={<PackageGlyph family={rec.family} className="size-6" />}
              title={tr("Keine Geometrie gespeichert")}
              description={
                external
                  ? tr('Der Footprint stammt aus einer externen Bibliothek – PartForge kennt nur den Namen.')
                  : tr('Für diesen Eintrag liegt keine Geometrie vor.')
              }
            />
          </div>
        )}
        <aside aria-label={tr("Angaben")} className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
          <AltiumEditStatus kind="footprint" name={rec.name} />
          {rec.status !== 'ok' && (
            <Callout tone={meta.variant === 'warning' ? 'warning' : 'danger'} title={tr(meta.label)}>
              {localizeMessage(rec.status_message ?? meta.text)}
            </Callout>
          )}
          <KeyValueList
            dense
            labelWidth="6.5rem"
            items={[
              { label: tr('IPC-Name'), value: spec?.ipc_name ?? rec.ipc_name ?? '–', mono: true, copy: spec?.ipc_name ?? rec.ipc_name ?? undefined },
              { label: tr('Pads'), value: rec.pad_count, mono: true },
              { label: tr('Höhe'), value: rec.height ? `${formatDim(rec.height)} mm` : '–', mono: true },
              {
                label: tr('Dichte'),
                value: densityLabel(density),
              },
              { label: tr('Herkunft'), value: tr(SOURCE_LABEL[rec.source]) ?? rec.source },
              {
                label: tr('Verwendet'),
                value: rec.usage ? (
                  <button
                    type="button"
                    aria-expanded={showUsage}
                    aria-controls="fp-usage-list"
                    onClick={() => setShowUsage((v) => !v)}
                    className="-mx-1 inline-flex items-center gap-1 rounded-sm px-1 text-accent-text outline-none hover:underline focus-ring"
                  >
                    {plural(rec.usage, tr('Bauteil'), tr('Bauteile'))}
                    <ChevronRight aria-hidden className={cn('size-3.5 transition-transform', showUsage && 'rotate-90')} />
                  </button>
                ) : (
                  tr('von keinem Bauteil')
                ),
              },
              {
                label: tr('Aktualisiert'),
                value: rec.updated ? (
                  <Tooltip content={formatDateTime(rec.updated)}>
                    <button type="button" className="cursor-help rounded-sm outline-none focus-ring">
                      {formatRelativeTime(rec.updated)}
                    </button>
                  </Tooltip>
                ) : (
                  '–'
                ),
              },
            ]}
          />
          {showUsage && rec.usage > 0 && (
            <div id="fp-usage-list" className="-mt-2 flex flex-col gap-1 rounded-control border border-line bg-surface-2/50 p-2">
              {usage.isPending ? (
                <span className="flex items-center gap-2 px-1 py-1 text-2xs text-fg-muted">
                  <Spinner size={12} /> {tr("Bauteile werden gesucht …")}
                </span>
              ) : usage.isError ? (
                <span className="px-1 text-2xs text-danger-text">{errorMessage(usage.error)}</span>
              ) : (usage.data ?? []).length === 0 ? (
                <span className="px-1 text-2xs text-fg-muted">{tr("Keine Bauteile gefunden (Verweis in einer Zusatzspalte?).")}</span>
              ) : (
                <ul className="flex flex-col">
                  {(usage.data ?? []).map((hit) => (
                    <li key={`${hit.table}:${hit.partNumber}`}>
                      <Link
                        to={`/bauteile/${encodeURIComponent(hit.table)}?pn=${encodeURIComponent(hit.partNumber)}`}
                        className="group/u flex items-baseline gap-2 rounded-sm px-1 py-0.5 text-2xs outline-none hover:bg-surface-3 focus-ring"
                      >
                        <span className="mono shrink-0 font-semibold text-fg group-hover/u:underline">{hit.partNumber}</span>
                        <span className="min-w-0 flex-1 truncate text-fg-subtle">
                          {categoryLabel.get(hit.table) ?? hit.table}
                          {hit.description ? ` · ${hit.description}` : ''}
                        </span>
                        <ExternalLink aria-hidden className="size-3 shrink-0 self-center text-fg-subtle" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              {usage.data && rec.usage > usage.data.length && (
                <p className="px-1 pt-1 text-2xs text-fg-subtle">
                  {tr("Die ersten")}{' '}{formatNumber(usage.data.length)} {tr("von")}{' '}{formatNumber(rec.usage)} {tr("– alle zeigt die Bauteiltabelle mit dem Filter „Footprint“.")}
                </p>
              )}
            </div>
          )}
          <div className="flex flex-col gap-1.5 border-t border-line pt-3">
            <div className="micro-label">{tr("Bibliothek")}</div>
            <div className="flex items-start gap-1">
              <PathText path={rec.library_abs ?? rec.library} className="mono min-w-0 text-xs text-fg-muted" />
              {rec.library_abs && detail.file_exists && (
                <IconButton
                  size="xs"
                  label={tr("Im Explorer zeigen")}
                  icon={<FolderOpen />}
                  onClick={() => void revealPath(rec.library_abs as string, { what: tr('Bibliotheksdatei') })}
                />
              )}
            </div>
            {!detail.file_exists && <p className="text-2xs text-warning-text">{tr("Die Bibliotheksdatei wurde nicht gefunden.")}</p>}
          </div>
          <div className="flex flex-col gap-1.5 border-t border-line pt-3">
            <div className="micro-label">{tr("3D-Modell")}</div>
            {detail.step ? (
              <p className="mono break-all text-xs text-fg-muted">
                {baseName(detail.step.file)}{' '}
                {detail.step.exists ? (
                  <Badge variant="success" size="sm">
                    {tr("vorhanden")}
                  </Badge>
                ) : (
                  <Badge variant="warning" size="sm">
                    {tr("fehlt")}
                  </Badge>
                )}
              </p>
            ) : (
              <p className="text-xs text-fg-muted">
                {(detail.bodies ?? []).length
                  ? plural(detail.bodies.length, tr('extrudierter Körper'), tr('extrudierte Körper'))
                  : tr('Kein 3D-Modell hinterlegt')}
              </p>
            )}
          </div>
          {detail.warnings.length > 0 && (
            <ul className="flex flex-col gap-1 border-t border-line pt-3">
              {detail.warnings.map((w) => (
                <li key={w} className="flex gap-1.5 text-2xs leading-4 text-warning-text">
                  <TriangleAlert aria-hidden className="mt-px size-3 shrink-0" />
                  {localizeMessage(w)}
                </li>
              ))}
            </ul>
          )}
        </aside>
      </DialogBody>
      <DialogFooter>
        <Button
          variant="ghost"
          leftIcon={<Trash2 />}
          loading={remove.isPending}
          onClick={() => void del()}
          className="mr-auto text-danger-text hover:bg-danger/10 hover:text-danger-text"
        >
          {tr("Löschen")}
        </Button>
        {!canRegenerate && <span className="text-2xs text-fg-subtle">{tr("Ohne Generator-Parameter – in PartForge nicht bearbeitbar.")}</span>}
        <AltiumEditButton kind="footprint" rec={rec} fileExists={detail.file_exists} />
        <Button variant="secondary" leftIcon={<Download />} loading={busy} disabled={!hasStep} onClick={() => void step()}>
          STEP
        </Button>
        {canRebuild && (
          <Tooltip content={tr("Vorlage {value0} mit dem aktuellen Hausstil neu berechnen – ändert sich die Geometrie, fragt PartForge vor dem Ersetzen.", { value0: String(presetKey) })}>
            <Button variant="secondary" leftIcon={<RefreshCw />} loading={rebuilding} onClick={() => void rebuild()}>
              {tr("Neu generieren")}
            </Button>
          </Tooltip>
        )}
        <Button
          ref={primaryRef}
          data-autofocus={canRegenerate || undefined}
          variant="primary"
          leftIcon={<PencilRuler />}
          disabled={!canRegenerate}
          onClick={() => void edit()}
        >
          {tr("Bearbeiten")}
        </Button>
      </DialogFooter>
    </>
  )
}
