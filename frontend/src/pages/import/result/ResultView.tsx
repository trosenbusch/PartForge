import { motion, useReducedMotion } from 'motion/react'
import {
  ArrowRight,
  Check,
  CircleAlert,
  CircuitBoard,
  Component as SymbolIcon,
  FilePlus2,
  ListChecks,
  MonitorCheck,
  RefreshCw,
  TableProperties,
  TriangleAlert,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useAltiumStatus } from '@/api/altium'
import type { DatasheetDetail } from '@/api/datasheets'
import { useCategoryLabel } from '@/api/library'
import { ALTIUM_PATH, altiumActionState, type AltiumActionState } from '@/app/navigation'
import { PageBody, PageTitle } from '@/app/page'
import { Badge, Button, Card, EmptyState, Spinner } from '@/components/ui'
import { cn } from '@/lib/cn'
import { formatDateTime, formatNumber, plural } from '@/lib/format'
import { AltiumNextStep } from '@/pages/altium/AltiumNextStep'
import { altiumAfterWrite, type AfterWriteNotice } from '@/pages/altium/model'
import { formatUsd } from '../lib/format'
import { importPath } from '../lib/useImportActions'

const partLink = (table: string, pn: string) => `/bauteile/${encodeURIComponent(table)}?pn=${encodeURIComponent(pn)}`

/** Symbol der Altium-Zeile je Zustand (`altiumAfterWrite`) */
const ALTIUM_ICON: Record<AfterWriteNotice['tone'], ReactNode> = {
  ok: <MonitorCheck aria-hidden className="size-3.5 shrink-0 text-success-text" />,
  busy: <Spinner size={13} className="shrink-0 text-fg-muted" />,
  manual: <MonitorCheck aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />,
  warn: <TriangleAlert aria-hidden className="size-3.5 shrink-0 text-warning-text" />,
  error: <TriangleAlert aria-hidden className="size-3.5 shrink-0 text-danger-text" />,
  off: <MonitorCheck aria-hidden className="size-3.5 shrink-0 text-fg-subtle" />,
}

/** Erfolg nach „Bauteile anlegen“: angelegte/aktualisierte Bauteile (Links), Symbole, Footprints, Fehler, Kosten. */
export function ResultView({ ds }: { ds: DatasheetDetail }) {
  const reduce = useReducedMotion()
  // „Nur Symbol/Footprint speichern“ legt keine Bauteile an – das Ergebnis zeigt die letzte Bauteil-Übernahme
  const commits = ds.committed.filter((c) => c.scope === 'part')
  const last = commits[commits.length - 1]
  const tableLabel = useCategoryLabel(last?.table)
  // geteilter, regelmäßig erneuerter Altium-Status (nach Altium-Jobs wie Installieren sofort neu geladen)
  const altium = useAltiumStatus(Boolean(last))

  if (!last) {
    return (
      <PageBody width="narrow">
        <PageTitle title={ds.title || ds.original_name} />
        <EmptyState
          illustration="no-parts"
          titleAs="h2"
          title="Aus diesem Datenblatt wurde noch nichts angelegt"
          actions={
            <Button asChild variant="secondary">
              <Link to={importPath(ds.id)}>
                <ListChecks aria-hidden />Zur Prüfansicht
              </Link>
            </Button>
          }
        />
      </PageBody>
    )
  }

  const created = last.created
  const updated = last.updated
  const errors = Object.entries(last.errors)
  const total = created.length + updated.length
  const firstPn = created[0] ?? updated[0]
  const label = tableLabel ?? last.table
  const ok = errors.length === 0
  const running = altium.data?.altium_running
  const notice = altiumAfterWrite(altium.data)

  return (
    <PageBody width="default" className="pb-16">
      <PageTitle
        title={ds.title || ds.original_name}
        subtitle={`Übernommen ${formatDateTime(last.ts)}`}
      />
      <motion.div
        initial={reduce ? false : { opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        className="mx-auto max-w-4xl"
      >
        <Card className="relative overflow-hidden">
          <div
            aria-hidden
            className="pointer-events-none absolute -top-48 left-1/2 size-[36rem] -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,var(--pf-ember),transparent)]"
          />
          <div className="relative flex flex-col items-center px-8 pb-8 pt-10 text-center">
            <motion.span
              initial={reduce ? false : { scale: 0.6, rotate: -12 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ type: 'spring', stiffness: 320, damping: 18, delay: 0.08 }}
              className={cn(
                'flex size-16 items-center justify-center rounded-full [&_svg]:size-8',
                ok ? 'bg-gradient-forge text-on-accent shadow-glow' : 'border border-warning/40 bg-warning/15 text-warning-text',
              )}
            >
              {ok ? <Check /> : <CircleAlert />}
            </motion.span>
            <h2 className="mt-5 text-h2 font-semibold tracking-[-0.02em] text-fg">
              {total ? `${plural(total, 'Bauteil', 'Bauteile')} ${created.length && !updated.length ? 'angelegt' : 'übernommen'}` : 'Nichts angelegt'}
            </h2>
            <p className="mt-1.5 max-w-xl text-ui leading-relaxed text-fg-muted">
              in <span className="font-medium text-fg">{label}</span>
              {created.length && updated.length ? ` · ${created.length} neu, ${updated.length} aktualisiert` : ''}
              {last.symbols.length || last.footprints.length
                ? ` · ${[
                    last.symbols.length ? plural(last.symbols.length, 'Symbol', 'Symbole') : null,
                    last.footprints.length ? plural(last.footprints.length, 'Footprint', 'Footprints') : null,
                  ]
                    .filter(Boolean)
                    .join(' und ')} geschrieben`
                : ' · Symbol und Footprint waren schon vorhanden'}
              {errors.length ? ` · ${plural(errors.length, 'Bestellnummer', 'Bestellnummern')} nicht angelegt` : ''}
            </p>
            <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
              {firstPn && (
                <Button asChild variant="primary" size="lg">
                  <Link to={partLink(last.table, firstPn)}>
                    <TableProperties aria-hidden />In der Bauteiltabelle öffnen
                  </Link>
                </Button>
              )}
              <Button asChild variant="secondary" size="lg">
                <Link to="/import">
                  <FilePlus2 aria-hidden />Nächstes Datenblatt
                </Link>
              </Button>
              <Button asChild variant="ghost" size="lg">
                <Link to={importPath(ds.id)}>
                  <ListChecks aria-hidden />Zur Prüfansicht
                </Link>
              </Button>
            </div>
            {/* was Altium jetzt sieht – echter Zustand (installiert? übersprungen?) mit dem nächsten Schritt */}
            {notice && (
              <p className="mt-5 flex items-center justify-center gap-1.5 text-xs text-fg-subtle">
                {ALTIUM_ICON[notice.tone]}
                <span className="min-w-0">
                  {notice.text}
                  {notice.next && <AltiumNextStep next={notice.next} className="ml-2" />}
                </span>
              </p>
            )}
          </div>

          <div className="relative grid gap-px border-t border-line bg-line @[48rem]:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="bg-surface px-6 py-5">
              <PartList title="Neu angelegt" table={last.table} pns={created} />
              <div className="mt-5">
                <h3 className="micro-label mb-1">Als Nächstes</h3>
                {/* die Übernahme hat Symbole und Footprints schon in die Bibliotheksdateien geschrieben */}
                <p className="mb-2 text-xs leading-relaxed text-fg-subtle">
                  {last.symbols.length || last.footprints.length
                    ? 'Symbole und Footprints stehen schon in den Bibliotheksdateien (SchLib/PcbLib) – zu synchronisieren ist nichts.'
                    : 'Die Bauteile verwenden vorhandene Symbole und Footprints der Bibliothek.'}
                </p>
                <ul className="flex flex-col gap-1">
                  {notice?.next?.action === 'refresh' && (
                    <NextStep
                      to={ALTIUM_PATH}
                      state={altiumActionState('aktualisieren')}
                      title="In Altium Designer aktualisieren"
                      text="Neue Bauteile, Symbole und Footprints in der laufenden Sitzung laden"
                    />
                  )}
                  <NextStep
                    to={ALTIUM_PATH}
                    state={altiumActionState('pruefen')}
                    title="Bibliothek prüfen"
                    text="Verweise, Pflichtfelder und Dateien der neuen Bauteile kontrollieren"
                  />
                  {!running && (
                    <NextStep to={ALTIUM_PATH} title="Altium-Anbindung ansehen" text="DbLib-Status und Installation in Altium Designer" />
                  )}
                </ul>
              </div>
              {updated.length > 0 && <PartList title="Aktualisiert" table={last.table} pns={updated} className="mt-5" />}
              {errors.length > 0 && (
                <div className="mt-5">
                  <h3 className="micro-label mb-2 text-danger-text">Nicht angelegt</h3>
                  <ul className="flex flex-col gap-1.5">
                    {errors.map(([pn, msg]) => (
                      <li key={pn} className="flex items-start gap-2 text-xs leading-relaxed">
                        <CircleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0 text-danger-text" />
                        <span>
                          <span className="mono font-medium text-fg">{pn}</span>
                          <span className="text-fg-muted"> – {msg}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="flex flex-col gap-5 bg-surface px-6 py-5">
              <LibraryList
                title="Symbole"
                icon={<SymbolIcon />}
                names={last.symbols}
                empty="vorhandene verwendet"
                to={() => '/symbole?ansicht=bibliothek'}
              />
              <LibraryList
                title="Footprints"
                icon={<CircuitBoard />}
                names={last.footprints}
                empty="vorhandene verwendet"
                to={(n) => `/footprints?ansicht=bibliothek&fp=${encodeURIComponent(n)}`}
              />
              <div className="mt-auto border-t border-line pt-4 text-xs text-fg-muted">
                <div className="flex items-center justify-between gap-3">
                  <span>{ds.runs.some((r) => r.kind === 'find') ? 'Kosten dieses Datenblatts (Suche und Analyse)' : 'Analysekosten dieses Datenblatts'}</span>
                  <span className="mono font-semibold text-fg">{formatUsd(ds.cost_usd)}</span>
                </div>
                {commits.length > 1 && (
                  <div className="mt-1 flex items-center gap-1.5 text-2xs text-fg-subtle">
                    <RefreshCw aria-hidden className="size-3" />
                    {formatNumber(commits.length)}. Übernahme aus diesem Datenblatt
                  </div>
                )}
              </div>
            </div>
          </div>
          {last.warnings.length > 0 && (
            <div className="relative border-t border-line bg-surface-2/40 px-6 py-4">
              <h3 className="micro-label mb-1.5">Hinweise</h3>
              <ul className="flex flex-col gap-1">
                {last.warnings.slice(0, 8).map((w) => (
                  <li key={w} className="text-xs leading-relaxed text-fg-muted">
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </motion.div>
    </PageBody>
  )
}

/** `state`: Aktion der Altium-Seite als Router-State (nie als `?aktion=` in der Adresse) */
function NextStep({ to, state, title, text }: { to: string; state?: AltiumActionState; title: string; text: string }) {
  return (
    <li>
      <Link
        to={to}
        state={state}
        className="group/next flex items-center gap-3 rounded-control px-2 py-1.5 outline-none transition-colors hover:bg-surface-2 focus-ring -mx-2"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-ui font-medium text-fg">{title}</span>
          <span className="block text-xs text-fg-subtle">{text}</span>
        </span>
        <ArrowRight aria-hidden className="size-4 shrink-0 text-fg-subtle transition-transform group-hover/next:translate-x-0.5" />
      </Link>
    </li>
  )
}

function PartList({ title, table, pns, className }: { title: string; table: string; pns: string[]; className?: string }) {
  return (
    <div className={className}>
      <div className="mb-2 flex items-center gap-2">
        <h3 className="micro-label">{title}</h3>
        <Badge size="sm">{formatNumber(pns.length)}</Badge>
      </div>
      {pns.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {pns.slice(0, 40).map((pn) => (
            <li key={pn}>
              <Link
                to={partLink(table, pn)}
                className="mono group/pn inline-flex h-7 items-center gap-1 rounded-control border border-line-strong bg-surface-2 px-2 text-xs text-fg outline-none transition-colors hover:border-line-control hover:bg-surface-3 focus-ring"
              >
                {pn}
                <ArrowRight aria-hidden className="size-3 text-fg-subtle opacity-0 transition-opacity group-hover/pn:opacity-100" />
              </Link>
            </li>
          ))}
          {pns.length > 40 && <li className="self-center text-xs text-fg-subtle">… und {pns.length - 40} weitere</li>}
        </ul>
      ) : (
        <p className="text-xs text-fg-subtle">keine</p>
      )}
    </div>
  )
}

function LibraryList({
  title,
  icon,
  names,
  empty,
  to,
}: {
  title: string
  icon: ReactNode
  names: string[]
  empty: string
  to: (name: string) => string
}) {
  return (
    <div>
      <h3 className="micro-label mb-2 flex items-center gap-1.5 [&_svg]:size-3.5">
        {icon}
        {title}
      </h3>
      {names.length ? (
        <ul className="flex flex-col gap-1">
          {names.map((n) => (
            <li key={n}>
              <Link to={to(n)} className="mono flex items-center gap-1.5 rounded-sm text-xs text-fg outline-none hover:underline focus-ring">
                <Badge variant="success" size="sm">
                  neu
                </Badge>
                <span className="truncate">{n}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-fg-subtle">{empty}</p>
      )}
    </div>
  )
}
