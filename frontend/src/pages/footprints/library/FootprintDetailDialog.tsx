/**
 * Detail eines gespeicherten Footprints: Vorschau (Footprint/3D), Kennwerte, Bibliotheksdatei, Status, Verwendung
 * (Liste der Bauteile mit Links), 3D-Modell – „Bearbeiten“ (Generator mit den gespeicherten Parametern),
 * „Neu generieren“ (Vorlagen-Footprints mit dem aktuellen Hausstil neu berechnen und – nach Rückfrage – ersetzen),
 * STEP und Löschen. Der Fokus startet auf der Hauptaktion.
 *
 * Eigene Namen (z. B. „MY_SOIC8“ statt „SOIC127P600X175-8N“) bleiben bei „Neu generieren“ und „Bearbeiten“ erhalten:
 * Das Backend vermerkt einen eigenen Namen beim Speichern in `spec.generator.name` (nur dann – erzeugte Namen stehen in
 * `generator.names`); er geht als `FootprintRequest.name` zurück an den Generator. Sonst entstünde der Footprint unter
 * dem Vorlagennamen und ersetzte still einen anderen. Ein erzeugter Name folgt dagegen dem Namensschema des Hausstils:
 * Ändert er sich (Schema umgestellt), nennt die Rückfrage das Ziel – samt Verwendung, wenn es den Namen schon gibt.
 */
import { useQueryClient } from '@tanstack/react-query'
import { ChevronRight, Download, ExternalLink, FolderOpen, PencilRuler, RefreshCw, Trash2, TriangleAlert } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
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
              <Callout tone="danger" title="Footprint konnte nicht geladen werden">
                {errorMessage(detail.error)}
              </Callout>
            </DialogBody>
          </>
        ) : (
          <>
            <DialogHeader icon={<PackageGlyph family={null} />} title={shownName ?? 'Footprint'} description="Wird geladen …" />
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
  const hasStep = Boolean(detail.step?.exists || (detail.bodies ?? []).length)
  const external = rec.source === 'external'

  const categories = useCategories()
  const usage = usePartsUsing(FOOTPRINT_COLUMNS, rec.name, categories.data, showUsage && rec.usage > 0)
  const categoryLabel = new Map((categories.data ?? []).map((c) => [c.table, c.label]))
  // „Neu generieren“: nur für Vorlagen mit Standardmaßen (der Name hängt dann nur an Vorlage und Hausstil) – die
  // Vorlage steht im Spec oder ergibt sich aus den Selektoren der gespeicherten Parameter (wie im Generator)
  const presetKey = useMemo(() => {
    if (!family || generator?.standard !== true) return null
    if (typeof generator.preset === 'string') return generator.preset
    const params = generator.params && typeof generator.params === 'object' ? (generator.params as Record<string, unknown>) : {}
    return closestPreset(family, normalizeParams(family.params, params))?.key ?? null
  }, [family, generator])
  const canRebuild = Boolean(family && presetKey && rec.source === 'generated')

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
      notifySaveResult(result, { what: 'STEP-Modell', id: 'fp-file' })
    } catch (e) {
      toast.error('STEP-Modell nicht verfügbar', { id: 'fp-file', description: errorMessage(e) })
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
        toast.error('Neu berechnen nicht möglich', { id: 'fp-rebuild', description: errors[0].message })
        return
      }
      const fresh = preview.spec
      const dry = await footprintsApi.save(fresh, { dryRun: true })
      const renamed = !sameName(fresh.name, rec.name)
      const target = dry.library ? baseName(dry.library) : 'der Bibliothek'
      const sameGeometry = fresh.generator?.geometry_hash === generator?.geometry_hash && rec.status === 'ok'
      if (!renamed && (dry.unchanged || sameGeometry)) {
        toast.info(`„${rec.name}“ ist aktuell`, { id: 'fp-rebuild', description: 'Mit dem aktuellen Hausstil entsteht dieselbe Geometrie – nichts zu schreiben.' })
        return
      }
      if (renamed && dry.unchanged) {
        toast.info(`„${fresh.name}“ ist bereits aktuell`, {
          id: 'fp-rebuild',
          description: `Mit dem aktuellen Hausstil heißt der Footprint „${fresh.name}“ – den gibt es unverändert in ${target}. Bauteile verweisen weiter auf „${rec.name}“.`,
        })
        return
      }
      const usedBy = dry.usage ? plural(dry.usage, 'Bauteil verwendet', 'Bauteile verwenden') : null
      const ok = !renamed
        ? await confirm({
            title: `„${rec.name}“ neu erzeugen?`,
            description: `Die Geometrie wird mit dem aktuellen Hausstil neu berechnet und ersetzt den Footprint in ${target}${usedBy ? ` – ${usedBy} ihn.` : '.'}`,
            confirmLabel: 'Ersetzen',
            destructive: dry.usage > 0,
          })
        : !dry.new
          ? await confirm({
              // Den neuen Namen gibt es schon: dieser andere Footprint wird ersetzt – das Original bleibt
              title: `„${fresh.name}“ ersetzen?`,
              description: (
                <span className="flex flex-col gap-2">
                  <span className="block">
                    Mit dem aktuellen Hausstil heißt der Footprint „<span className="mono text-fg">{fresh.name}</span>“. Diesen Footprint
                    gibt es schon in {target} – seine Geometrie wird ersetzt.
                  </span>
                  <span className={cn('block', dry.usage > 0 && 'font-medium text-warning-text')}>
                    {usedBy
                      ? `${usedBy} „${fresh.name}“ – ${dry.usage === 1 ? 'es bekommt' : 'sie bekommen'} die neue Geometrie.`
                      : `Noch verwendet kein Bauteil „${fresh.name}“.`}
                  </span>
                  <span className="block">„{rec.name}“ bleibt unverändert; seine Bauteile verweisen weiter darauf.</span>
                </span>
              ),
              confirmLabel: 'Ersetzen',
              destructive: dry.usage > 0,
            })
          : await confirm({
              title: `Als „${fresh.name}“ neu erzeugen?`,
              description: `Mit dem aktuellen Hausstil heißt der Footprint „${fresh.name}“. Er wird zusätzlich in ${target} gespeichert – Bauteile verweisen weiter auf „${rec.name}“.`,
              confirmLabel: 'Neu speichern',
            })
      if (!ok) return
      const out = await footprintsApi.save(fresh)
      void qc.invalidateQueries({ queryKey: footprintKeys.library, predicate: (q) => q.queryKey[2] !== 'thumb' })
      void qc.invalidateQueries({ queryKey: ['parts', 'library'] })
      if (out.job) {
        trackJob(out.job as unknown as Job, { openDock: false })
        return
      }
      toast.success(renamed && dry.new ? `„${fresh.name}“ neu gespeichert` : `„${fresh.name}“ neu erzeugt`, {
        id: 'fp-rebuild',
        description: out.record ? `In ${out.record.library} geschrieben.` : undefined,
      })
    } catch (e) {
      const tip = e instanceof ApiError && e.status === 409 ? ' Ist die PcbLib in Altium geöffnet und geändert?' : ''
      toast.error('Neu erzeugen fehlgeschlagen', { id: 'fp-rebuild', description: `${errorMessage(e)}${tip}` })
    } finally {
      setRebuilding(false)
    }
  }

  /**
   * Im Generator öffnen: die gespeicherten Parameter – und ein eigener Name (`generator.name`), damit „Speichern“ diesen
   * Footprint aktualisiert statt unter dem erzeugten Namen einen anderen zu ersetzen.
   */
  const edit = () => {
    if (!family || !generator) return
    onRegenerate(family, generator, { name: customName(generator) })
  }

  const del = async () => {
    const used = rec.usage
    const ok = await confirm({
      title: `„${rec.name}“ löschen?`,
      description: external
        ? 'Der Footprint gehört zu einer externen Bibliothek: PartForge vergisst ihn nur, die Datei bleibt unverändert.'
        : used
          ? `Er wird von ${plural(used, 'Bauteil', 'Bauteilen')} verwendet – deren Verweis zeigt danach ins Leere. Der Footprint wird aus ${baseName(rec.library)} entfernt.`
          : `Der Footprint wird aus ${baseName(rec.library)} entfernt.`,
      confirmLabel: used ? 'Trotzdem löschen' : 'Löschen',
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
        toast.error('Nicht gelöscht', { description: refused })
        return
      }
      toast.success(`„${rec.name}“ gelöscht`, {
        description: result?.unregistered.length ? 'Nur aus PartForge entfernt (externe Bibliothek).' : baseName(rec.library),
      })
      onDeleted()
    } catch (e) {
      toast.error('Löschen fehlgeschlagen', { description: errorMessage(e) })
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
              {meta.label}
            </Badge>
          </span>
        }
      />
      <DialogBody className="grid min-h-0 grid-cols-[minmax(0,1fr)_17.5rem] gap-5 overflow-hidden">
        {spec ? (
          <PreviewPanel footprint={spec} hideEmptyTabs defaultTab="footprint" title={rec.name} className="h-full min-h-[22rem]" />
        ) : (
          <div className="flex items-center justify-center rounded-card border border-line bg-surface">
            <EmptyState
              icon={<PackageGlyph family={rec.family} className="size-6" />}
              title="Keine Geometrie gespeichert"
              description={
                external
                  ? 'Der Footprint stammt aus einer externen Bibliothek – PartForge kennt nur den Namen.'
                  : 'Für diesen Eintrag liegt keine Geometrie vor.'
              }
            />
          </div>
        )}
        <aside aria-label="Angaben" className="flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
          {rec.status !== 'ok' && (
            <Callout tone={meta.variant === 'warning' ? 'warning' : 'danger'} title={meta.label}>
              {rec.status_message ?? meta.text}
            </Callout>
          )}
          <KeyValueList
            dense
            labelWidth="6.5rem"
            items={[
              { label: 'IPC-Name', value: spec?.ipc_name ?? rec.ipc_name ?? '–', mono: true, copy: spec?.ipc_name ?? rec.ipc_name ?? undefined },
              { label: 'Pads', value: rec.pad_count, mono: true },
              { label: 'Höhe', value: rec.height ? `${formatDim(rec.height)} mm` : '–', mono: true },
              {
                label: 'Dichte',
                value: densityLabel(density),
              },
              { label: 'Herkunft', value: SOURCE_LABEL[rec.source] ?? rec.source },
              {
                label: 'Verwendet',
                value: rec.usage ? (
                  <button
                    type="button"
                    aria-expanded={showUsage}
                    aria-controls="fp-usage-list"
                    onClick={() => setShowUsage((v) => !v)}
                    className="-mx-1 inline-flex items-center gap-1 rounded-sm px-1 text-accent-text outline-none hover:underline focus-ring"
                  >
                    {plural(rec.usage, 'Bauteil', 'Bauteile')}
                    <ChevronRight aria-hidden className={cn('size-3.5 transition-transform', showUsage && 'rotate-90')} />
                  </button>
                ) : (
                  'von keinem Bauteil'
                ),
              },
              {
                label: 'Aktualisiert',
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
                  <Spinner size={12} /> Bauteile werden gesucht …
                </span>
              ) : usage.isError ? (
                <span className="px-1 text-2xs text-danger-text">{errorMessage(usage.error)}</span>
              ) : (usage.data ?? []).length === 0 ? (
                <span className="px-1 text-2xs text-fg-muted">Keine Bauteile gefunden (Verweis in einer Zusatzspalte?).</span>
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
                  Die ersten {formatNumber(usage.data.length)} von {formatNumber(rec.usage)} – alle zeigt die Bauteiltabelle mit dem
                  Filter „Footprint“.
                </p>
              )}
            </div>
          )}
          <div className="flex flex-col gap-1.5 border-t border-line pt-3">
            <div className="micro-label">Bibliothek</div>
            <div className="flex items-start gap-1">
              <PathText path={rec.library_abs ?? rec.library} className="mono min-w-0 text-xs text-fg-muted" />
              {rec.library_abs && detail.file_exists && (
                <IconButton
                  size="xs"
                  label="Im Explorer zeigen"
                  icon={<FolderOpen />}
                  onClick={() => void revealPath(rec.library_abs as string, { what: 'Bibliotheksdatei' })}
                />
              )}
            </div>
            {!detail.file_exists && <p className="text-2xs text-warning-text">Die Bibliotheksdatei wurde nicht gefunden.</p>}
          </div>
          <div className="flex flex-col gap-1.5 border-t border-line pt-3">
            <div className="micro-label">3D-Modell</div>
            {detail.step ? (
              <p className="mono break-all text-xs text-fg-muted">
                {baseName(detail.step.file)}{' '}
                {detail.step.exists ? (
                  <Badge variant="success" size="sm">
                    vorhanden
                  </Badge>
                ) : (
                  <Badge variant="warning" size="sm">
                    fehlt
                  </Badge>
                )}
              </p>
            ) : (
              <p className="text-xs text-fg-muted">
                {(detail.bodies ?? []).length
                  ? plural(detail.bodies.length, 'extrudierter Körper', 'extrudierte Körper')
                  : 'Kein 3D-Modell hinterlegt'}
              </p>
            )}
          </div>
          {detail.warnings.length > 0 && (
            <ul className="flex flex-col gap-1 border-t border-line pt-3">
              {detail.warnings.map((w) => (
                <li key={w} className="flex gap-1.5 text-2xs leading-4 text-warning-text">
                  <TriangleAlert aria-hidden className="mt-px size-3 shrink-0" />
                  {w}
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
          Löschen
        </Button>
        {!canRegenerate && <span className="text-2xs text-fg-subtle">Ohne Generator-Parameter (importiert) – nur ansehen.</span>}
        <Button variant="secondary" leftIcon={<Download />} loading={busy} disabled={!hasStep} onClick={() => void step()}>
          STEP
        </Button>
        {canRebuild && (
          <Tooltip content={`Vorlage ${presetKey} mit dem aktuellen Hausstil neu berechnen – ändert sich die Geometrie, fragt PartForge vor dem Ersetzen.`}>
            <Button variant="secondary" leftIcon={<RefreshCw />} loading={rebuilding} onClick={() => void rebuild()}>
              Neu generieren
            </Button>
          </Tooltip>
        )}
        <Button
          ref={primaryRef}
          data-autofocus={canRegenerate || undefined}
          variant="primary"
          leftIcon={<PencilRuler />}
          disabled={!canRegenerate}
          onClick={edit}
        >
          Bearbeiten
        </Button>
      </DialogFooter>
    </>
  )
}
