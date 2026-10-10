import { localizeMessage } from '@/lib/i18n'
import { t as translate, useI18n } from '@/lib/i18n'
import { Check, Combine, FileSearch, TriangleAlert } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { errorMessage } from '@/api/client'
import {
  useExtraction,
  useMergePackage,
  usePackageSources,
  usePackageTargets,
  type DatasheetSummary,
  type ExtractionData,
  type PackageSource,
  type PackageTarget,
} from '@/api/datasheets'
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  EmptyState,
  Select,
  Skeleton,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { plural } from '@/lib/format'
import { useRadioCards } from '@/pages/serien/components/useRadioCards'
import { importPath } from '../lib/useImportActions'
import { PageImage } from './PageImage'

const WHAT = 'Maße, Herstellerempfehlung, Exposed-Pad-Nummer und Anschlussanordnung werden übernommen – Code und Name des Gehäuses bleiben. Die Übernahme lässt sich aufheben.'

const keyOf = (c: { datasheet_id: string; package: string }) => `${c.datasheet_id}|${c.package}`

// --------------------------------------------------------------------------- Maße in dieses Datenblatt holen

export interface PackageSourceDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Datenblatt, dessen Gehäuse die Maße bekommt */
  datasheetId: string
  packageCode: string
  /** „VQFN-19 3.5x4.5 (RGY)“ */
  packageLabel: string
}

/** „Maße aus anderem Datenblatt übernehmen“ – Zeichnungen anderer Analysen, bestes zuerst. */
export function PackageSourceDialog({ open, onOpenChange, datasheetId, packageCode, packageLabel }: PackageSourceDialogProps) {
  useI18n()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader icon={<Combine />} tone="accent" title={translate("Maße für {0} übernehmen", { "0": String(packageLabel) })} description={translate(WHAT)} />
        {open && <SourceList datasheetId={datasheetId} packageCode={packageCode} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function SourceList({ datasheetId, packageCode, onDone }: { datasheetId: string; packageCode: string; onDone: () => void }) {
  useI18n()
  const navigate = useNavigate()
  const sources = usePackageSources(datasheetId, packageCode)
  const merge = useMergePackage()
  const items = sources.data ?? []
  const [picked, setPicked] = useState<string | null>(null)
  const keys = items.map(keyOf)
  const chosenKey = picked && keys.includes(picked) ? picked : (keys[0] ?? null)
  const chosen = items.find((c) => keyOf(c) === chosenKey)

  const apply = async (c: PackageSource | undefined) => {
    if (!c || merge.isPending) return
    const out = await merge
      .mutateAsync({ id: datasheetId, package: packageCode, source_id: c.datasheet_id, source_package: c.package })
      .catch(() => null)
    if (!out) return
    toast.success(translate("Maße übernommen"), { description: out.notes.map(localizeMessage).join(' ') })
    onDone()
  }
  const { radioProps } = useRadioCards({ keys, value: chosenKey, onChange: setPicked, onActivate: (k) => void apply(items.find((c) => keyOf(c) === k)) })

  let body: ReactNode
  if (sources.isLoading) body = <ListSkeleton />
  else if (sources.isError) body = <p className="text-ui text-danger-text">{errorMessage(sources.error)}</p>
  else if (!items.length)
    body = (
      <EmptyState
        illustration="search-empty"
        size="sm"
        title={translate("Keine Zeichnung zum Übernehmen")}
        description={translate("Die Gehäusezeichnung des Herstellers (bei TI z. B. „RGY0019B“ als eigenes PDF) importieren und analysieren – danach steht sie hier zur Auswahl.")}
        actions={
          <Button variant="secondary" leftIcon={<FileSearch />} onClick={() => navigate('/import')}>
            {translate("Zum Datenblatt-Import")}</Button>
        }
      />
    )
  else
    body = (
      <div role="radiogroup" aria-label={translate("Gehäusezeichnung")} className="flex flex-col gap-2">
        {items.map((c, i) => (
          <CandidateCard
            key={keyOf(c)}
            radio={radioProps(keyOf(c))}
            checked={keyOf(c) === chosenKey}
            best={i === 0 && c.problems.length === 0 && items.length > 1}
            thumb={{ id: c.datasheet_id, page: c.pages[0] ?? 1 }}
            title={c.label}
            subtitle={[c.file, c.title && c.title !== c.label ? c.title : null].filter(Boolean).join(' · ')}
            facts={[
              c.package_only ? translate("Gehäusezeichnung") : null,
              c.pin_count ? plural(c.pin_count, translate("Anschluss"), translate("Anschlüsse")) : null,
              c.exposed_pad ? `Exposed Pad${c.exposed_pad_number ? ` ${c.exposed_pad_number}` : ''}` : null,
              plural(c.dimensions, translate("Maß"), translate("Maße")),
              c.land_pattern ? translate("Herstellerempfehlung") : null,
              c.layout ? translate("Anschlussanordnung") : null,
            ]}
            matches={c.matches}
            problems={c.problems}
          />
        ))}
      </div>
    )

  return (
    <>
      <DialogBody className="pt-2">{body}</DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          {translate("Abbrechen")}</Button>
        <Button variant="primary" leftIcon={<Combine />} disabled={!chosen} loading={merge.isPending} onClick={() => void apply(chosen)}>
          {translate("Maße übernehmen")}</Button>
      </DialogFooter>
    </>
  )
}

// --------------------------------------------------------------------------- Zeichnung an ein Bauteil-Datenblatt geben

export interface PackageTargetDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Gehäusezeichnung (Datenblatt ohne Bauteil) */
  sourceId: string
  sourcePackage: string
  sourceLabel: string
}

/** „In Datenblatt eines Bauteils übernehmen“ – die Gegenrichtung aus einer Gehäusezeichnung heraus. */
export function PackageTargetDialog({ open, onOpenChange, sourceId, sourcePackage, sourceLabel }: PackageTargetDialogProps) {
  useI18n()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader
          icon={<Combine />}
          tone="accent"
          title={translate("{0} einem Bauteil geben", { "0": String(sourceLabel) })}
          description={translate("Das Datenblatt des Bauteils bekommt die Zeichnung. {0}", { "0": translate(WHAT) })}
        />
        {open && <TargetList sourceId={sourceId} sourcePackage={sourcePackage} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function TargetList({ sourceId, sourcePackage, onDone }: { sourceId: string; sourcePackage: string; onDone: () => void }) {
  useI18n()
  const navigate = useNavigate()
  const targets = usePackageTargets(sourceId, sourcePackage)
  const merge = useMergePackage()
  const items = targets.data ?? []
  const [picked, setPicked] = useState<string | null>(null)
  const keys = items.map(keyOf)
  const chosenKey = picked && keys.includes(picked) ? picked : (keys[0] ?? null)
  const chosen = items.find((t) => keyOf(t) === chosenKey)

  const apply = async (t: PackageTarget | undefined) => {
    if (!t || merge.isPending) return
    const out = await merge
      .mutateAsync({ id: t.datasheet_id, package: t.package, source_id: sourceId, source_package: sourcePackage })
      .catch(() => null)
    if (!out) return
    toast.success(translate("Maße an {0} übergeben", { "0": String(t.devices[0] ?? t.file) }), { description: out.notes.map(localizeMessage).join(' ') })
    onDone()
    navigate(importPath(t.datasheet_id))
  }
  const { radioProps } = useRadioCards({ keys, value: chosenKey, onChange: setPicked, onActivate: (k) => void apply(items.find((t) => keyOf(t) === k)) })

  let body: ReactNode
  if (targets.isLoading) body = <ListSkeleton />
  else if (targets.isError) body = <p className="text-ui text-danger-text">{errorMessage(targets.error)}</p>
  else if (!items.length)
    body = (
      <EmptyState
        illustration="search-empty"
        size="sm"
        title={translate("Kein Bauteil-Datenblatt gefunden")}
        description={translate("Zuerst das Datenblatt des Bauteils importieren und analysieren – danach hier übernehmen oder dort unter „Gehäuse“ „Maße übernehmen …“ wählen.")}
      />
    )
  else
    body = (
      <div role="radiogroup" aria-label={translate("Bauteil-Datenblatt")} className="flex flex-col gap-2">
        {items.map((t, i) => (
          <CandidateCard
            key={keyOf(t)}
            radio={radioProps(keyOf(t))}
            checked={keyOf(t) === chosenKey}
            best={i === 0 && t.problems.length === 0 && items.length > 1}
            thumb={{ id: t.datasheet_id, page: 1 }}
            title={`${t.devices.join(', ') || t.file} · ${t.label}`}
            subtitle={[t.file, t.title].filter(Boolean).join(' · ')}
            facts={[
              t.pin_count ? plural(t.pin_count, translate("Anschluss"), translate("Anschlüsse")) : null,
              t.dims_missing ? null : plural(t.dimensions, translate("Maß"), translate("Maße")),
              t.merged_from ? translate("Maße bisher aus „{0}“", { "0": String(t.merged_from) }) : null,
            ]}
            flag={t.dims_missing ? translate("Maße fehlen") : undefined}
            matches={t.matches.filter((m) => m !== 'Maße fehlen dort')}
            problems={t.problems}
          />
        ))}
      </div>
    )

  return (
    <>
      <DialogBody className="pt-2">{body}</DialogBody>
      <DialogFooter>
        <Button variant="ghost" onClick={onDone}>
          {translate("Abbrechen")}</Button>
        <Button variant="primary" leftIcon={<Combine />} disabled={!chosen} loading={merge.isPending} onClick={() => void apply(chosen)}>
          {translate("Übernehmen und öffnen")}</Button>
      </DialogFooter>
    </>
  )
}

// --------------------------------------------------------------------------- aus der Datenblattliste

/** Gehäuse mit Zeichnung (Maße oder Herstellerempfehlung) – wie `PackageData.has_geometry` */
function drawn(p: ExtractionData['packages'][number]): boolean {
  return p.land_pattern.present || p.dimensions.some((d) => d.unit === 'mm' && (d.nom ?? d.min ?? d.max) !== null)
}

/** Richtung des Zusammenführens: Maße in dieses Datenblatt holen (`take`) oder seine Zeichnung abgeben (`give`) */
export type MergeDirection = 'take' | 'give'

/**
 * „Zusammenführen“ aus der Datenblattliste: ein Bauteil-Datenblatt holt die Maße für ein Gehäuse (zuerst eines mit
 * fehlenden Maßen; bei mehreren wählbar), eine Gehäusezeichnung gibt ihre Zeichnung einem Bauteil-Datenblatt.
 */
export function DatasheetMergeDialog({
  datasheet,
  direction,
  open,
  onOpenChange,
}: {
  datasheet: DatasheetSummary | null
  direction: MergeDirection
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  useI18n()
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        {open && datasheet && <MergeChooser key={`${datasheet.id}-${direction}`} datasheet={datasheet} direction={direction} onDone={() => onOpenChange(false)} />}
      </DialogContent>
    </Dialog>
  )
}

function MergeChooser({ datasheet, direction, onDone }: { datasheet: DatasheetSummary; direction: MergeDirection; onDone: () => void }) {
  useI18n()
  const extractionQ = useExtraction(datasheet.id, { enabled: datasheet.has_extraction })
  const data = extractionQ.data?.extraction
  const giving = direction === 'give'
  const missing = new Set((data?.issues ?? []).filter((i) => i.code === 'dims_missing' && i.package).map((i) => i.package as string))
  // abgeben: nur eigene Zeichnungen; holen: Gehäuse, die ihre Maße noch nicht aus einem anderen Datenblatt haben
  const packages = (data?.packages ?? []).filter((p) => !p.origin && (!giving || drawn(p)))
  const ordered = [...packages].sort((a, b) => Number(missing.has(b.code)) - Number(missing.has(a.code)))
  const [picked, setPicked] = useState<string | null>(null)
  const pkg = ordered.find((p) => p.code === picked) ?? ordered[0]
  const label = pkg ? (pkg.name && pkg.name !== pkg.code ? `${pkg.name} (${pkg.code})` : pkg.code) : ''
  const chooser = ordered.length > 1 && (
    <Select
      size="sm"
      aria-label={giving ? translate("Gehäuse, dessen Zeichnung abgegeben wird") : translate("Gehäuse, das die Maße bekommt")}
      value={pkg?.code}
      onValueChange={setPicked}
      options={ordered.map((p) => ({
        value: p.code,
        label: p.name && p.name !== p.code ? `${p.name} (${p.code})` : p.code,
        description: missing.has(p.code) ? translate("Maße fehlen") : undefined,
      }))}
      className="mt-2.5 w-auto min-w-56"
    />
  )

  const header = giving ? (
    <DialogHeader
      icon={<Combine />}
      tone="accent"
      title={pkg ? translate("{0} einem Bauteil geben", { "0": String(label) }) : translate("Zeichnung einem Bauteil geben")}
      description={translate("Das Datenblatt des Bauteils bekommt die Zeichnung aus „{0}“. {1}", { "0": String(datasheet.original_name), "1": translate(WHAT) })}
    >
      {chooser}
    </DialogHeader>
  ) : (
    <DialogHeader
      icon={<Combine />}
      tone="accent"
      title={pkg ? translate("Maße für {0} übernehmen", { "0": String(label) }) : translate("Maße aus anderem Datenblatt übernehmen")}
      description={translate(WHAT)}
    >
      {chooser}

    </DialogHeader>
  )

  let content: ReactNode
  if (extractionQ.isLoading) content = <DialogBody><ListSkeleton /></DialogBody>
  else if (extractionQ.isError) content = <DialogBody><p className="text-ui text-danger-text">{errorMessage(extractionQ.error)}</p></DialogBody>
  else if (!pkg)
    content = (
      <DialogBody>
        <EmptyState
          illustration="search-empty"
          size="sm"
          title={giving ? translate("Keine Zeichnung mit Maßen") : translate("Kein Gehäuse zum Zusammenführen")}
          description={
            giving
              ? translate("Die Analyse hat in diesem Dokument keine eigenen Maße gefunden.")
              : translate("Alle Gehäuse dieses Datenblatts haben ihre Maße schon aus einem anderen Datenblatt.")
          }
        />
      </DialogBody>
    )
  else if (giving) content = <TargetList key={pkg.code} sourceId={datasheet.id} sourcePackage={pkg.code} onDone={onDone} />
  else content = <SourceList key={pkg.code} datasheetId={datasheet.id} packageCode={pkg.code} onDone={onDone} />
  return (
    <>
      {header}
      {content}
    </>
  )
}

// --------------------------------------------------------------------------- gemeinsame Bausteine

function CandidateCard({
  radio,
  checked,
  best,
  thumb,
  title,
  subtitle,
  facts,
  flag,
  matches,
  problems,
}: {
  radio: ReturnType<ReturnType<typeof useRadioCards>['radioProps']>
  checked: boolean
  best: boolean
  thumb: { id: string; page: number }
  title: string
  subtitle: string
  facts: (string | null)[]
  flag?: string
  matches: string[]
  problems: string[]
}) {
  useI18n()
  return (
    <button
      type="button"
      {...radio}
      className={cn(
        'flex w-full items-start gap-3 rounded-card border px-3 py-2.5 text-left outline-none transition-colors focus-ring',
        checked ? 'border-accent/50 bg-accent-soft/40' : 'border-line bg-surface hover:border-line-strong hover:bg-surface-2/60',
      )}
    >
      <PageImage datasheetId={thumb.id} page={thumb.page} dpi={48} alt="" className="w-12 shrink-0 rounded-sm border border-line shadow-card" />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-ui font-medium text-fg">{title}</span>
          {best && (
            <Badge variant="success" size="sm">
              {translate("passt am besten")}</Badge>
          )}
          {flag && (
            <Badge variant="warning" size="sm">
              {flag}
            </Badge>
          )}
        </span>
        <span className="block truncate text-2xs text-fg-subtle">{subtitle}</span>
        <span className="mt-1.5 flex flex-wrap gap-1">
          {facts.filter(Boolean).map((f) => (
            <Badge key={f} size="sm" variant="outline">
              {f}
            </Badge>
          ))}
        </span>
        {(matches.length > 0 || problems.length > 0) && (
          <span className="mt-1.5 flex flex-col gap-0.5 text-2xs leading-4">
            {matches.length > 0 && (
              <span className="flex items-start gap-1 text-success-text">
                <Check aria-hidden className="mt-0.5 size-3 shrink-0" />
                {matches.map(localizeMessage).join(' · ')}
              </span>
            )}
            {problems.map((p) => (
              <span key={p} className="flex items-start gap-1 text-warning-text">
                <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0" />
                {localizeMessage(p)}
              </span>
            ))}
          </span>
        )}
      </span>
      <span
        aria-hidden
        className={cn(
          'mt-1 flex size-4 shrink-0 items-center justify-center rounded-full border',
          checked ? 'border-accent bg-accent' : 'border-line-strong',
        )}
      >
        {checked && <span className="size-1.5 rounded-full bg-on-accent" />}
      </span>
    </button>
  )
}

function ListSkeleton() {
  useI18n()
  return (
    <div className="flex flex-col gap-2" aria-busy>
      {[0, 1].map((i) => (
        <div key={i} className="flex items-start gap-3 rounded-card border border-line px-3 py-2.5">
          <Skeleton className="h-16 w-12 rounded-sm" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-3.5 w-1/2" />
            <Skeleton className="h-3 w-1/3" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      ))}
    </div>
  )
}
