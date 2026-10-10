import { localizeMessage } from '@/lib/i18n'
import { t, useI18n } from '@/lib/i18n'
import { Box, ChevronDown, CircleAlert, Combine, Eye, FileStack, LayoutGrid, Undo2, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import type { DimValue, PackageChoice, PackageData, PackageOrigin, RowReference, TerminalLayout } from '@/api/datasheets'
import { useLibraryFootprintNames, useUnmergePackage } from '@/api/datasheets'
import {
  Badge,
  Button,
  Callout,
  Combobox,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  SegmentedControl,
  Select,
} from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatNumber } from '@/lib/format'
import { CellInput, NumberCell } from '../../shared/CommitInput'
import { PackageSourceDialog, PackageTargetDialog } from '../../shared/PackageMergeDialogs'
import { SourceChip } from '../../shared/SourceChip'
import { TipButton } from '../../shared/TipButton'
import { useReviewUi } from '../../store'
import { packageLabel, useReview } from '../context'
import { sectionIssues } from '../issues'
import { OriginPagesDialog } from './OriginPagesDialog'
import { Section } from './Section'

const FAMILY_LABEL: Record<string, string> = {
  chip: 'Chip',
  get molded() { return t("Molded (Tantal, Spule)") },
  melf: 'MELF',
  sod: 'SOD',
  do214: 'DO-214',
  sot23: 'SOT-23',
  sc70: 'SC-70',
  sot523: 'SOT-523',
  sot89: 'SOT-89',
  sot223: 'SOT-223',
  dpak: 'DPAK',
  gullwing: 'Gull-Wing',
  qfp: 'QFP',
  nolead: 'QFN/DFN',
  bga: 'BGA',
  dip: 'DIP',
  axial: 'Axial',
  radial: 'Radial',
  to92: 'TO-92',
  to220: 'TO-220',
  get pin_header() { return t("Stiftleiste") },
}

/** JEDEC-Maßbuchstaben → deutsche Bedeutung (Claude liefert die englische Beschreibung als Tooltip) */
const DIM_LABEL: Record<string, string> = {
  get A() { return t("Bauhöhe") },
  get A1() { return t("Abstand zur Platine") },
  get A2() { return t("Körperdicke") },
  get A3() { return t("Anschlussdicke") },
  get b() { return t("Anschlussbreite") },
  get b1() { return t("Anschlussbreite") },
  get c() { return t("Anschlussdicke") },
  get D() { return t("Körperlänge") },
  get D1() { return t("Körperlänge") },
  get D2() { return t("Exposed Pad, Länge") },
  get E() { return t("Breite über Anschlüsse") },
  get E1() { return t("Körperbreite") },
  get E2() { return t("Exposed Pad, Breite") },
  get e() { return t("Anschlussraster") },
  get e1() { return t("Anschlussraster") },
  get H() { return t("Breite über Anschlüsse") },
  get HE() { return t("Breite über Anschlüsse") },
  get k() { return t("Abstand Anschluss–Pad") },
  get K() { return t("Abstand Anschluss–Pad") },
  get L() { return t("Fußlänge") },
  get L1() { return t("Anschlusslänge") },
  get L2() { return t("Anschlusslänge") },
  get theta() { return t("Fußwinkel") },
  get θ() { return t("Fußwinkel") },
}

const ROW_REFERENCES: { value: RowReference; label: string }[] = [
  { value: 'center_to_center', get label() { return t("Mitte–Mitte") } },
  { value: 'inner_edges', get label() { return t("Innenkanten") } },
  { value: 'outer_edges', get label() { return t("Außenkanten") } },
  { value: 'pad_center_to_component_center', get label() { return t("Bauteilmitte–Padmitte") } },
  { value: 'unclear', get label() { return t("unklar (Mitte–Mitte)") } },
  { value: 'not_applicable', get label() { return t("nicht zutreffend") } },
]

const DENSITY = [
  { value: 'style', get label() { return t("Hausstil") } },
  { value: 'L', get label() { return t("L – kompakt") } },
  { value: 'N', label: 'N – nominal' },
  { value: 'M', label: 'M – robust' },
]

/** Familien mit Anschlüssen auf vier Seiten (Anschlussanordnung, Reihenabstand oben/unten) */
const QUAD_FAMILIES = new Set(['nolead', 'qfp'])
/** Nur QFN kennt Raster oben/unten, Lage von Pin 1 und fehlende Anschlüsse (der QFP-Generator nur die Seitenzahlen) */
const FULL_LAYOUT_FAMILIES = new Set(['nolead'])

const PIN1_OPTIONS: { value: TerminalLayout['pin1']; label: string; description: string }[] = [
  { value: 'left', get label() { return t("Linke Seite, oben") }, get description() { return t("JEDEC-Standard") } },
  { value: 'top', get label() { return t("Obere Seite, links") }, get description() { return t("z. B. TI RGY (Pins an den Stirnseiten)") } },
]

const EMPTY_LAYOUT: TerminalLayout = { pins_x: null, pins_y: null, pitch_x: null, pin1: 'left', missing: [] }

function isDefaultLayout(l: TerminalLayout): boolean {
  return l.pins_x === null && l.pins_y === null && l.pitch_x === null && l.pin1 === 'left' && l.missing.length === 0
}

/** „2 oben/unten · 8 links/rechts · Pin 1 oben · ohne 14“ – Kurzfassung einer Anschlussanordnung */
function layoutSummary(l: TerminalLayout | null | undefined): string {
  if (!l || isDefaultLayout(l)) return t("gleichmäßig verteilt")
  return [
    l.pins_x !== null ? t("{0} oben/unten", { "0": String(l.pins_x) }) : null,
    l.pins_y !== null ? t("{0} links/rechts", { "0": String(l.pins_y) }) : null,
    l.pitch_x !== null ? t("Raster oben/unten {0} mm", { "0": String(formatNumber(l.pitch_x)) }) : null,
    l.pin1 === 'top' ? t("Pin 1 oben") : null,
    l.missing.length ? t("ohne {0}", { "0": String(l.missing.join(', ')) }) : null,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** „14, 20“ → [14, 20] (ganze, positive Positionen; Rest wird ignoriert) */
function parsePositions(text: string): number[] {
  const out = new Set<number>()
  for (const token of text.split(/[,;\s]+/)) {
    if (/^\d+$/.test(token) && Number(token) > 0) out.add(Number(token))
  }
  return [...out].sort((a, b) => a - b)
}

/** Seiten der übernommenen Zeichnung (Umriss und Lötflächen) – Seiten des anderen PDFs */
function originPages(pkg: PackageData): number[] {
  return [...new Set([...pkg.pages, ...pkg.land_pattern.pages])].filter((p) => p > 0).sort((a, b) => a - b)
}

function DimRow({ dim, onChange }: { dim: DimValue; onChange: (field: 'min' | 'nom' | 'max', v: number | null) => void }) {
  useI18n()
  const label = DIM_LABEL[dim.symbol] ?? DIM_LABEL[dim.symbol.toUpperCase()] ?? dim.description
  const bad = dim.min !== null && dim.max !== null && dim.min > dim.max
  return (
    <tr>
      <td className="border-b border-line py-0.5 pl-1 pr-2 align-middle">
        <TipButton tip={dim.description || dim.symbol} label={`${dim.symbol}: ${dim.description || label}`} className="mono rounded-sm font-semibold text-fg">
          {dim.symbol === 'theta' ? 'θ' : dim.symbol || '–'}
        </TipButton>
      </td>
      <td className="hidden max-w-0 truncate border-b border-line py-0.5 pr-2 align-middle text-fg-muted @[26rem]:table-cell">{label}</td>
      {(['min', 'nom', 'max'] as const).map((k) => (
        <td key={k} className="w-[4.25rem] border-b border-line py-0.5 align-middle">
          <NumberCell
            aria-label={`${dim.symbol} ${k === 'min' ? 'Minimum' : k === 'nom' ? t("Nennwert") : 'Maximum'}`}
            value={dim[k]}
            onCommit={(v) => onChange(k, v)}
            invalid={bad && k !== 'nom'}
            placeholder="–"
            className="text-right"
          />
        </td>
      ))}
      <td className="w-6 border-b border-line py-0.5 pl-1 align-middle text-2xs text-fg-subtle">{dim.unit === 'deg' ? '°' : 'mm'}</td>
    </tr>
  )
}

function PackageBlock({ code }: { code: string }) {
  useI18n()
  const { ds, extraction, device, packageOnly, proposal, choices, setChoices, edit } = useReview()
  const setPreviewPackage = useReviewUi((s) => s.setPreviewPackage)
  const setPreviewTab = useReviewUi((s) => s.setPreviewTab)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [targetOpen, setTargetOpen] = useState(false)
  const [originOpen, setOriginOpen] = useState(false)
  const unmerge = useUnmergePackage(ds.id)
  const pi = extraction.packages.findIndex((p) => p.code === code)
  const pkg = extraction.packages[pi]
  const fp = proposal?.footprints.find((f) => f.package === code)
  const choice: PackageChoice = choices.packages[code] ?? { footprint: 'ipc' }
  const lp = pkg?.land_pattern
  const lpComplete = Boolean(lp?.present && lp.pad_width !== null && lp.pad_length !== null && lp.row_spacing !== null)
  const library = useLibraryFootprintNames(choice.footprint === 'existing')
  const issues = sectionIssues(extraction.issues, 'gehaeuse', device, undefined, code)
  const dimsMissing = issues.some((i) => i.code === 'dims_missing' && i.package === code)
  const quad = Boolean(pkg?.family && QUAD_FAMILIES.has(pkg.family))
  // Die Anordnung ist gefragt, wenn der Generator die Anschlüsse nicht verteilen kann (oder schon eine eingetragen ist)
  const layoutNeeded = Boolean(fp && !fp.valid && fp.warnings.some((w) => /je Seite|durch 4 teilbar|passen nicht/.test(w)))
  const [layoutOpen, setLayoutOpen] = useState(false)
  const showLayout = quad && (layoutOpen || layoutNeeded || Boolean(pkg?.layout))
  const label = pkg ? packageLabel(pkg) : code
  // Zeichnung an ein Bauteil-Datenblatt geben: Gehäusezeichnungen – und Bauteile ohne Bestellnummer (oft ein Platzhalter)
  const canGive = Boolean(pkg && !pkg.origin) && (packageOnly || device.variants.length === 0)

  const setChoice = (patch: Partial<PackageChoice>) => {
    setChoices((c) => ({ ...c, packages: { ...c.packages, [code]: { ...choice, ...patch } } }))
    setPreviewPackage(code)
    setPreviewTab('footprint')
  }
  const patchPkg = (label: string, fn: (p: NonNullable<typeof pkg>) => void) =>
    edit.apply(label, (d) => {
      const p = d.packages[pi]
      if (p) fn(p)
    })
  const setLayout = (what: string, patch: Partial<TerminalLayout>) =>
    patchPkg(what, (p) => {
      const next: TerminalLayout = { ...EMPTY_LAYOUT, ...(p.layout ?? {}), ...patch }
      p.layout = isDefaultLayout(next) ? null : next
    })
  const askUnmerge = async (origin: PackageOrigin) => {
    const ok = await confirm({
      title: t("Übernahme aufheben?"),
      description: t("{0} bekommt wieder die Angaben aus diesem Datenblatt – die Maße aus „{1}“ werden entfernt. Die Analyse von „{2}“ bleibt unverändert.", { "0": String(label), "1": String(origin.file), "2": String(origin.file) }),
      confirmLabel: t("Aufheben"),
      icon: <Undo2 />,
      onConfirm: () => unmerge.mutateAsync(code),
    })
    if (ok) toast.success(t("Übernahme aufgehoben"), { description: t("{0}: wieder die Angaben aus diesem Datenblatt", { "0": String(label) }) })
  }

  if (!pkg) {
    return (
      <div className="rounded-card border border-dashed border-line-strong px-3 py-2.5 text-xs text-fg-muted">
        {t("Gehäuse „")}{code}{t("“ ist im Datenblatt nicht beschrieben – bitte einen vorhandenen Footprint wählen.")}</div>
    )
  }

  return (
    <article aria-labelledby={`pkg-${code}`} className="rounded-card border border-line bg-surface">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-line px-3 py-2.5">
        <h3 id={`pkg-${code}`} className="text-ui font-semibold text-fg">
          {packageLabel(pkg)}
        </h3>
        {pkg.family ? (
          <Badge size="sm">{FAMILY_LABEL[pkg.family] ?? pkg.family}</Badge>
        ) : (
          <Badge size="sm" variant="warning">
            {t("Familie unbekannt")}</Badge>
        )}
        <span className="text-2xs text-fg-subtle">
          {[
            pkg.pin_count ? t("{0} Anschlüsse", { "0": String(pkg.pin_count) }) : null,
            pkg.mounting,
            pkg.exposed_pad ? `Exposed Pad${pkg.exposed_pad_number ? ` ${pkg.exposed_pad_number}` : ''}` : null,
            pkg.outline_reference || null,
          ]
            .filter(Boolean)
            .join(' · ')}
        </span>
        <div className="ml-auto flex items-center gap-1">
          {pkg.origin ? (
            <OriginMenu
              origin={pkg.origin}
              busy={unmerge.isPending}
              onShow={() => setOriginOpen(true)}
              onReplace={() => setSourceOpen(true)}
              onUnmerge={() => void askUnmerge(pkg.origin as PackageOrigin)}
            />
          ) : (
            <SourceChip pages={pkg.pages} what={t("Maßzeichnung {0}", { "0": String(label) })} />
          )}
          {canGive && (
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<Combine />}
              onClick={() => setTargetOpen(true)}
              title={t("Diese Zeichnung in das Datenblatt des Bauteils übernehmen, dem sie gehört")}
            >
              {t("Einem Bauteil geben …")}</Button>
          )}
          {!packageOnly && !pkg.origin && (
            <Button
              size="xs"
              variant="ghost"
              leftIcon={<Combine />}
              onClick={() => setSourceOpen(true)}
              title={t("Maße, Herstellerempfehlung und Exposed Pad aus einer eigenen Gehäusezeichnung des Herstellers übernehmen")}
            >
              {t("Maße übernehmen …")}</Button>
          )}
        </div>
      </header>
      {!packageOnly && (
        <PackageSourceDialog open={sourceOpen} onOpenChange={setSourceOpen} datasheetId={ds.id} packageCode={code} packageLabel={label} />
      )}
      {canGive && (
        <PackageTargetDialog open={targetOpen} onOpenChange={setTargetOpen} sourceId={ds.id} sourcePackage={code} sourceLabel={label} />
      )}
      {pkg.origin && (
        <OriginPagesDialog open={originOpen} onOpenChange={setOriginOpen} origin={pkg.origin} pages={originPages(pkg)} label={label} />
      )}

      {/* Footprint-Entscheidung */}
      <div className="flex flex-col gap-2 border-b border-line px-3 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl<PackageChoice['footprint']>
            size="sm"
            aria-label={t("Footprint für {0}", { "0": String(packageLabel(pkg)) })}
            value={choice.footprint}
            onValueChange={(v) => setChoice({ footprint: v })}
            options={[
              { value: 'ipc', label: 'IPC-7351B' },
              { value: 'manufacturer', label: t("Hersteller"), disabled: !lpComplete },
              { value: 'existing', label: t("Vorhanden") },
            ]}
          />
          {choice.footprint !== 'existing' && (
            <Select
              size="sm"
              aria-label={t("Dichte")}
              value={choice.density ?? 'style'}
              onValueChange={(v) => setChoice({ density: v === 'style' ? null : (v as 'L' | 'N' | 'M') })}
              options={DENSITY}
              className="w-auto min-w-28"
            />
          )}
          {!lpComplete && choice.footprint !== 'existing' && (
            <span className="text-2xs text-fg-subtle">{lp?.present ? t("Herstellerempfehlung unvollständig") : t("keine Herstellerempfehlung")}</span>
          )}
        </div>
        {choice.footprint === 'existing' && (
          <Combobox
            size="sm"
            aria-label={t("Vorhandenen Footprint wählen")}
            placeholder={library.isLoading ? t("Footprints werden geladen …") : t("Footprint aus der Bibliothek wählen …")}
            searchPlaceholder="Footprint suchen …"
            mono
            value={choice.existing ?? null}
            onValueChange={(v) => setChoice({ existing: v })}
            options={(library.data ?? []).map((f) => ({
              value: f.name,
              label: f.name,
              description: [f.family ? FAMILY_LABEL[f.family] ?? f.family : null, f.pad_count ? `${f.pad_count} Pads` : null]
                .filter(Boolean)
                .join(' · '),
              group: f.family && f.family === pkg.family ? t("Passende Familie") : t("Weitere"),
            }))}
          />
        )}
        {fp && (
          <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-xs">
            <span className="text-fg-subtle">Footprint</span>
            <button
              type="button"
              onClick={() => {
                setPreviewPackage(code)
                setPreviewTab('footprint')
              }}
              className="mono min-w-0 truncate rounded-sm font-medium text-fg outline-none hover:underline focus-ring"
            >
              {fp.name ?? '–'}
            </button>
            {!fp.valid ? (
              <Badge variant="danger" size="sm">
                {t("ungültig")}</Badge>
            ) : fp.exists ? (
              <Badge size="sm">{fp.status === 'ok' || fp.status === null ? t("vorhanden") : 'vorhanden · ausstehend'}</Badge>
            ) : (
              <Badge variant="success" size="sm">
                {t("neu")}</Badge>
            )}
            {fp.pad_count > 0 && <span className="text-2xs text-fg-subtle">{formatNumber(fp.pad_count)} Pads</span>}
          </div>
        )}
        {fp && fp.warnings.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {fp.warnings.slice(0, 4).map((w) => (
              <li key={w} className={cn('flex items-start gap-1.5 text-2xs leading-4', fp.valid ? 'text-warning-text' : 'text-danger-text')}>
                {fp.valid ? <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0" /> : <CircleAlert aria-hidden className="mt-0.5 size-3 shrink-0" />}
                <span>{localizeMessage(w)}</span>
              </li>
            ))}
          </ul>
        )}
        {issues.length > 0 && (
          <ul className="flex flex-col gap-0.5">
            {issues.map((i) => (
              <li
                key={i.message}
                className={cn(
                  'flex items-start gap-1.5 text-2xs leading-4',
                  i.severity === 'error' ? 'text-danger-text' : i.severity === 'warning' ? 'text-warning-text' : 'text-fg-subtle',
                )}
              >
                {i.severity === 'error' ? <CircleAlert aria-hidden className="mt-0.5 size-3 shrink-0" /> : <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0" />}
                <span>{localizeMessage(i.message)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Maße */}
      <div className="px-3 pb-2 pt-2.5">
        {dimsMissing && !pkg.origin && !packageOnly && (
          <Callout
            tone="info"
            icon={<FileStack />}
            className="mb-2.5"
            actions={
              <Button size="sm" variant="secondary" leftIcon={<Combine />} onClick={() => setSourceOpen(true)}>
                {t("Maße übernehmen …")}</Button>
            }
          >
            {t("Maße fehlen. Viele Hersteller (z. B. TI) veröffentlichen die Gehäusezeichnung als eigenes PDF – dieses analysieren und die Maße hier übernehmen.")}</Callout>
        )}
        <div className="mb-1 flex items-center gap-2">
          <h4 className="micro-label">{t("Maße")}</h4>
          <span className="min-w-0 truncate text-2xs text-fg-subtle">
            {pkg.dimensions.length} {t(" aus ")}{pkg.origin ? `„${pkg.origin.file}“ (${pkg.origin.package})` : t("der Zeichnung")}
          </span>
        </div>
        {pkg.dimensions.length ? (
          <table className="w-full border-separate border-spacing-0 text-xs">
            <thead>
              <tr className="text-left text-2xs font-semibold uppercase tracking-[0.06em] text-fg-subtle">
                <th scope="col" className="w-12 pb-1 pl-1 pr-2 font-semibold">
                  {t("Maß")}</th>
                <th scope="col" className="hidden pb-1 font-semibold @[26rem]:table-cell">
                  {t("Bedeutung")}</th>
                <th scope="col" className="pb-1 pr-1.5 text-right font-semibold">
                  min
                </th>
                <th scope="col" className="pb-1 pr-1.5 text-right font-semibold">
                  nom
                </th>
                <th scope="col" className="pb-1 pr-1.5 text-right font-semibold">
                  max
                </th>
                <th scope="col" className="pb-1">
                  <span className="sr-only">{t("Einheit")}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {pkg.dimensions.map((d, k) => (
                <DimRow
                  key={`${d.symbol}-${k}`}
                  dim={d}
                  onChange={(field, v) =>
                    patchPkg(t("Maß {0} ({1})", { "0": String(d.symbol), "1": String(field) }), (p) => {
                      p.dimensions[k][field] = v
                    })
                  }
                />
              ))}
            </tbody>
          </table>
        ) : (
          <p className="py-1 text-xs text-fg-muted">{t("Keine Maße gefunden – der Footprint entsteht aus der Vorlage der Familie.")}</p>
        )}
      </div>

      {/* Anschlussanordnung (QFN/QFP, die nicht gleichmäßig verteilt sind) */}
      {quad &&
        (showLayout ? (
          <LayoutBlock
            layout={pkg.layout ?? EMPTY_LAYOUT}
            full={FULL_LAYOUT_FAMILIES.has(pkg.family ?? '')}
            needed={layoutNeeded}
            pitch={pkg.dimensions.find((d) => d.symbol === 'e')}
            onChange={setLayout}
          />
        ) : (
          <div className="flex items-center gap-2 border-t border-line px-3 py-2 text-xs">
            <LayoutGrid aria-hidden className="size-3.5 text-fg-subtle" />
            <span className="text-fg-subtle">{t("Anschlussanordnung:")}</span>
            <span className="text-fg-muted">{t("gleichmäßig verteilt")}</span>
            <Button size="xs" variant="ghost" className="ml-auto" onClick={() => setLayoutOpen(true)}>
              {t("Anpassen …")}</Button>
          </div>
        ))}

      {/* Herstellerempfehlung */}
      <div className="border-t border-line px-3 pb-3 pt-2.5">
        <div className="mb-1.5 flex items-center gap-2">
          <h4 className="micro-label">{t("Lötflächen laut Hersteller")}</h4>
          {lp?.present ? (
            <Badge size="sm" variant={lpComplete ? 'success' : 'warning'}>
              {lpComplete ? t("vollständig") : t("unvollständig")}
            </Badge>
          ) : null}
          <span className="ml-auto">
            {lp?.present && !pkg.origin && <SourceChip pages={lp.pages} what={t("Empfohlene Lötflächen")} />}
          </span>
        </div>
        {lp?.present ? (
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 text-xs @[30rem]:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
            <LpNumber label={t("Padbreite")} value={lp.pad_width} onCommit={(v) => patchPkg(t("Padbreite"), (p) => void (p.land_pattern.pad_width = v))} />
            <LpNumber label={t("Padlänge")} value={lp.pad_length} onCommit={(v) => patchPkg(t("Padlänge"), (p) => void (p.land_pattern.pad_length = v))} />
            <LpNumber label={t("Raster der Lötflächen")} value={lp.pitch} onCommit={(v) => patchPkg(t("Raster der Lötflächen"), (p) => void (p.land_pattern.pitch = v))} />
            <LpNumber
              label={quad ? t("Reihenabstand links/rechts") : t("Reihenabstand")}
              value={lp.row_spacing}
              onCommit={(v) => patchPkg(t("Reihenabstand"), (p) => void (p.land_pattern.row_spacing = v))}
            />
            {quad && (
              <LpNumber
                label={t("Reihenabstand oben/unten")}
                value={lp.row_spacing_y}
                placeholder={t("wie links/rechts")}
                hint={t("Bei rechteckigem Körper nötig (gleicher Bezug wie links/rechts)")}
                onCommit={(v) => patchPkg(t("Reihenabstand oben/unten"), (p) => void (p.land_pattern.row_spacing_y = v))}
              />
            )}
            <dt className="text-fg-subtle">{t("Bezug")}</dt>
            <dd className="min-w-0 @[30rem]:col-span-3">
              <Select
                size="sm"
                aria-label={t("Bezug des Reihenabstands")}
                value={lp.row_spacing_reference}
                onValueChange={(v) => patchPkg(t("Bezug des Reihenabstands"), (p) => void (p.land_pattern.row_spacing_reference = v))}
                options={ROW_REFERENCES}
                className="h-7 border-transparent bg-transparent px-1.5 text-xs shadow-none hover:border-line-strong"
              />
            </dd>
            {(lp.thermal_pad_width !== null || pkg.exposed_pad) && (
              <>
                <LpNumber
                  label={t("Thermal-Pad B")}
                  value={lp.thermal_pad_width}
                  onCommit={(v) => patchPkg(t("Thermal-Pad Breite"), (p) => void (p.land_pattern.thermal_pad_width = v))}
                />
                <LpNumber
                  label={t("Thermal-Pad L")}
                  value={lp.thermal_pad_length}
                  onCommit={(v) => patchPkg(t("Thermal-Pad Länge"), (p) => void (p.land_pattern.thermal_pad_length = v))}
                />
              </>
            )}
            {lp.notes && (
              <>
                <dt className="text-fg-subtle">{t("Notiz")}</dt>
                <dd className="min-w-0 @[30rem]:col-span-3">
                  <CellInput
                    aria-label={t("Notiz zu den Lötflächen")}
                    value={lp.notes}
                    onCommit={(v) => patchPkg(t("Notiz Lötflächen"), (p) => void (p.land_pattern.notes = v))}
                    className="text-fg-muted"
                  />
                </dd>
              </>
            )}
          </dl>
        ) : (
          <p className="text-xs text-fg-muted">{t("Keine Empfehlung im Datenblatt – der Footprint wird nach IPC-7351B berechnet.")}</p>
        )}
      </div>
    </article>
  )
}

function LpNumber({
  label,
  value,
  onCommit,
  placeholder = '–',
  hint,
}: {
  label: string
  value: number | null
  onCommit: (v: number | null) => void
  placeholder?: string
  hint?: string
}) {
  useI18n()
  return (
    <>
      <dt className="text-fg-subtle" title={hint}>
        {label}
      </dt>
      <dd className="flex min-w-0 items-center gap-1">
        <NumberCell
          aria-label={`${label} in mm`}
          value={value}
          onCommit={onCommit}
          placeholder={placeholder}
          title={hint}
          className={cn('text-right', placeholder.length > 3 ? 'max-w-28' : 'max-w-20')}
        />
        <span className="text-2xs text-fg-subtle">mm</span>
      </dd>
    </>
  )
}

/**
 * Anschlussanordnung eines QFN/QFP, die die Maße nicht beschreiben – etwa TI RGY: Pin 1 und 19 oben, 10 und 11 unten im
 * Abstand 1,5 mm, rechts eine Position frei. Positionen zählen gegen den Uhrzeigersinn ab Pin 1, als wären alle bestückt.
 */
function LayoutBlock({
  layout,
  full,
  needed,
  pitch,
  onChange,
}: {
  layout: TerminalLayout
  /** QFN: auch Raster oben/unten, Lage von Pin 1, fehlende Anschlüsse */
  full: boolean
  /** Der Footprint scheitert an der Verteilung der Anschlüsse */
  needed: boolean
  pitch: DimValue | undefined
  onChange: (what: string, patch: Partial<TerminalLayout>) => void
}) {
  useI18n()
  const count = (v: number | null) => (v === null || !Number.isFinite(v) || v < 1 ? null : Math.round(v))
  const pitchText = pitch ? formatNumber(pitch.nom ?? pitch.max ?? pitch.min ?? 0) : null
  return (
    <div className="border-t border-line px-3 pb-3 pt-2.5">
      <div className="mb-1.5 flex items-center gap-2">
        <h4 className="micro-label">{t("Anschlussanordnung")}</h4>
        <span className="min-w-0 truncate text-2xs text-fg-subtle">{layoutSummary(layout)}</span>
      </div>
      {needed && isDefaultLayout(layout) && (
        <p className="mb-2 flex items-start gap-1.5 text-2xs leading-4 text-warning-text">
          <TriangleAlert aria-hidden className="mt-0.5 size-3 shrink-0" />
          {t("Die Anschlüsse lassen sich nicht gleichmäßig auf vier Seiten verteilen – bitte die Anordnung aus der Zeichnung eintragen.")}</p>
      )}
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-0.5 text-xs @[30rem]:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]">
        <dt className="text-fg-subtle">{t("Oben/unten je Seite")}</dt>
        <dd className="flex min-w-0 items-center gap-1">
          <NumberCell
            aria-label={t("Anschlüsse oben und unten je Seite")}
            digits={0}
            value={layout.pins_x}
            placeholder={t("gleichmäßig")}
            onCommit={(v) => onChange(t("Anschlüsse oben/unten"), { pins_x: count(v) })}
            className="max-w-28 text-right"
          />
        </dd>
        <dt className="text-fg-subtle">{t("Links/rechts je Seite")}</dt>
        <dd className="flex min-w-0 items-center gap-1">
          <NumberCell
            aria-label={t("Anschlüsse links und rechts je Seite")}
            digits={0}
            value={layout.pins_y}
            placeholder={t("gleichmäßig")}
            onCommit={(v) => onChange(t("Anschlüsse links/rechts"), { pins_y: count(v) })}
            className="max-w-28 text-right"
          />
        </dd>
        {full && (
          <>
            <dt className="text-fg-subtle">{t("Raster oben/unten")}</dt>
            <dd className="flex min-w-0 items-center gap-1">
              <NumberCell
                aria-label={t("Raster der Anschlüsse oben und unten in mm")}
                value={layout.pitch_x}
                placeholder={pitchText ? t("wie e ({0})", { "0": String(pitchText) }) : t("wie e")}
                onCommit={(v) => onChange(t("Raster oben/unten"), { pitch_x: v !== null && v > 0 ? v : null })}
                className="max-w-28 text-right"
              />
              <span className="text-2xs text-fg-subtle">mm</span>
            </dd>
            <dt className="text-fg-subtle">Pin 1</dt>
            <dd className="min-w-0">
              <Select
                size="sm"
                aria-label={t("Lage von Pin 1")}
                value={layout.pin1}
                onValueChange={(v) => onChange(t("Lage von Pin 1"), { pin1: v as TerminalLayout['pin1'] })}
                options={PIN1_OPTIONS}
                className="h-7 border-transparent bg-transparent px-1.5 text-xs shadow-none hover:border-line-strong"
              />
            </dd>
            <dt className="text-fg-subtle">{t("Fehlende Anschlüsse")}</dt>
            <dd className="min-w-0 @[30rem]:col-span-3">
              <CellInput
                aria-label={t("Fehlende Anschlüsse (Positionen)")}
                value={layout.missing.join(', ')}
                placeholder={t("keine – z. B. „14“")}
                onCommit={(v) => onChange(t("Fehlende Anschlüsse"), { missing: parsePositions(v) })}
                className="mono max-w-56"
              />
            </dd>
          </>
        )}
      </dl>
      {full && (
        <p className="mt-1.5 text-2xs leading-4 text-fg-subtle">
          {t("Positionen zählen ab Pin 1 gegen den Uhrzeigersinn, als wären alle bestückt; die Pins werden über die übrigen Positionen durchnummeriert.")}</p>
      )}
    </div>
  )
}

/** Herkunft eines übernommenen Gehäuses: Zeichnung ansehen, andere Zeichnung wählen, Übernahme aufheben. */
function OriginMenu({
  origin,
  busy,
  onShow,
  onReplace,
  onUnmerge,
}: {
  origin: PackageOrigin
  busy: boolean
  onShow: () => void
  onReplace: () => void
  onUnmerge: () => void
}) {
  useI18n()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={busy}
          className={cn(
            'inline-flex h-5 max-w-56 shrink items-center gap-1 rounded-md border border-accent/30 bg-accent-soft/50 px-1.5 text-2xs font-medium text-accent-text',
            'outline-none transition-colors hover:border-accent/60 focus-ring disabled:opacity-60',
          )}
        >
          <Combine aria-hidden className="size-3 shrink-0" />
          <span className="truncate">{t("aus ")}{origin.file}</span>
          <ChevronDown aria-hidden className="size-3 shrink-0" />
          <span className="sr-only"> {t(" – Maße übernommen aus ")}{origin.label || origin.package}{t(", Aktionen")}</span>
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-64">
        <DropdownMenuItem icon={<Eye />} description={origin.label || origin.package} onSelect={onShow}>
          {t("Zeichnung ansehen")}</DropdownMenuItem>
        <DropdownMenuItem icon={<Combine />} description={t("Maße aus einem anderen Datenblatt übernehmen")} onSelect={onReplace}>
          {t("Andere Zeichnung wählen …")}</DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem icon={<Undo2 />} description={t("Wieder die Angaben dieses Datenblatts")} onSelect={onUnmerge}>
          {t("Übernahme aufheben …")}</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/** Gehäuse der gewählten Bestellnummern: Footprint-Entscheidung (IPC/Hersteller/vorhanden), Maße, Lötflächen. */
export function PackagesSection() {
  useI18n()
  const { extraction, device, codes, packageOnly } = useReview()
  const issues = sectionIssues(extraction.issues, 'gehaeuse', device, codes)
  const others = extraction.packages.filter((p) => !codes.includes(p.code))
  return (
    <Section id="gehaeuse" title={t("Gehäuse")} icon={<Box />} count={codes.length} issues={issues}>
      <div className="flex flex-col gap-3">
        {packageOnly && (
          <Callout tone="info" icon={<FileStack />} title={t("Gehäusezeichnung ohne Bauteil")}>
            {t("Hier entsteht nur der Footprint („Footprint speichern“, in die PcbLib). Für das vollständige Bauteil die Maße mit „Einem Bauteil geben …“ in das Datenblatt des Bauteils übernehmen – oder dort unter „Gehäuse“ mit „Maße übernehmen …“.")}</Callout>
        )}
        {codes.map((code) => (
          <PackageBlock key={code} code={code} />
        ))}
        {codes.length === 0 && <p className="text-xs text-fg-muted">{t("Keine Bestellnummer gewählt.")}</p>}
        {others.length > 0 && (
          <p className="text-2xs text-fg-subtle">
            {t("Ohne gewählte Bestellnummer: ")}{others.map((p) => packageLabel(p)).join(', ')}
          </p>
        )}
      </div>
    </Section>
  )
}
